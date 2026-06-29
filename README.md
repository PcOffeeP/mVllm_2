# TensileAgent

> 材料拉伸试验视频断裂行为理解 — 基于 MiniCPM-V-4.5 的 frame-interval 精细化微调与评估

**一句话定位**：采用 **frame-interval 多帧区间建模**，对材料拉伸试验视频进行断裂时间定位与断裂类型分类。

## 目录结构

```
TensileAgent/
├── pipeline/                  # 数据流水线 + 预处理适配层
│   ├── scripts/               #   数据处理脚本（划分→子视频→训练样本→质量检查→冻结）
│   ├── preprocessing/         #   视频预处理适配层（MiniCPM processor 封装）
│   ├── server_proxy.py        #   同进程推理服务（LLaMA-Factory ChatModel 封装）
│   ├── server_adapter.py      #   推理服务适配层
│   └── llamafactory_contract.py  # Processor contract（帧数上限 8 + 帧捕获）
├── finetune/                  # 微调训练与验证
│   ├── train_with_contract.py #   训练入口
│   ├── MiniCPM/config/        #   3-fold YAML 配置文件
│   ├── validation/            #   推理 + 三种评估脚本
│   └── dataset_info.json      #   LLaMA-Factory 数据集注册表
├── data/                      # 数据资产（视频、标注、划分、子视频、训练 JSON、元数据）
├── LlamaFactory/              # LLaMA-Factory git submodule（训练框架）
├── models/                    # 基座模型权重（.gitignore）
├── docs/                      # 项目文档
├── scripts/                   # 辅助工具脚本（清理、调试、校验）
├── assets/                    # 领域参考文档与原始说明材料
├── pyproject.toml             # Hatchling 构建配置
└── README.md
```

## 环境准备

项目使用 **Conda + pip** 管理 Python 环境（推荐），训练依赖在远程 4090 Linux 系统上运行。

### 初始化子模块

```bash
git submodule update --init --recursive
```

### 创建 Conda 环境

**Step 1：创建最小 Conda 环境**

```bash
conda create -n mVllm2 python=3.11 pip -y
conda activate mVllm2
```

**Step 2：pip 安装所有依赖**

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**Step 3：安装本地子模块**

```bash
pip install -e ./LlamaFactory
```

如果某个包安装失败，pip 会继续安装其余包，最后单独处理失败的那一个即可。

> **Mac 开发机**：如需在本地运行数据流水线等，可手动创建不带 CUDA 的环境：
>
> ```bash
> conda create -n mVllm2 python=3.11 pip
> conda activate mVllm2
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> pip install -e ./LlamaFactory
> conda install av pandas Pillow pyyaml fastapi uvicorn python-multipart
> ```

### 下载模型

将 MiniCPM-V-4.5 基座模型下载至 `models/` 目录。

## 方法论：Frame-Interval 精细化微调

传统做法对整段视频做单次预测，难以精确到秒级断裂定位。本项目采用 **frame-interval 建模**：

1. **帧级粒度**：通过 MiniCPM-V-4.5 的 processor 将视频解码为离散帧序列（默认最多 8 帧），每帧关联精确时间戳。
2. **区间标注**：断裂位置标注为相邻帧索引对 `[i, i+1]`（即 fracture\_between），由真实 processor 的帧选结果推导，确保标注与模型输入一致。
3. **子视频采样**：围绕断裂时刻构造多种时间窗口的子视频（聚焦窗口 3s/5s/10s/20s + 断裂前负样本 + 断裂后困难负样本），构造丰富的正负样本对。
4. **3-fold 交叉验证**：按视频分层划分 3 折，每折独立训练 + 验证，确保评估稳定性。

## 数据流水线

从原始 CSV 标注到可训练的 ShareGPT JSON，共 **7 步**：

```
原始视频 + CSV 标注
    │
    ├─① dataset_manager.py     读取 CSV → 构建 video_meta.json → 3-fold 分层划分
    │                           输出: data/05_splits/, data/07_metadata/video_meta.json
    │
    ├─② subvideo_builder.py    加载 MiniCPM processor → 生成候选子视频
    │    3 阶段                  阶段1: 生成候选清单（全时长 + focus 窗口 + 负样本）
    │                           阶段2: 按正:负 1:1~2:1 选样
    │                           阶段3: 编码子视频 → data/03_subvideos/
    │                           输出: data/07_metadata/subvideos_meta.json
    │
    ├─③ training_sample_builder.py  子视频元数据 → ShareGPT JSON
    │                                 输出: data/06_merged/fold_*_train.json / val.json
    │
    ├─④ validate_no_oob.py     校验 fracture_between 与 start/end_frame 一致性
    │
    ├─⑤ quality_check.py       强制质量检查（路径存在性、字段合法性、leakage 检测等）
    │                           输出: data/07_metadata/quality_check_report.json
    │
    ├─⑥ freeze_data_version.py 冻结数据版本（git commit、配置哈希、processor 指纹等）
    │                           输出: data/07_metadata/data_version_lock.json
    │
    └─⑦ calibration.py         （可选）校验预处理适配层与 LLaMA-Factory 真实 batch 加载一致
                               输出: data/07_metadata/calibration_report.json
```

### 子视频元信息

步骤 ② 生成的 `subvideos_meta.json` 记录的是“训练时真正会用到的子视频契约”，不是简单的裁剪日志。关键字段包括：

- `video_path`：子视频实际文件路径
- `start_time` / `end_time` / `start_frame` / `end_frame` / `duration`
- `crop_type`、`source_video`、`selection_reason`
- `has_fracture`、`fracture_between`、`type`、`location`
- `processor_fingerprint`、`processor_info`
- `actual_frame_mapping`、`sampled_frames`

其中最关键的是 `actual_frame_mapping`。它同时保留两套坐标：

- `original_frame` / `timestamp`：映射回源视频后的全局帧号和时间戳
- `clip_frame` / `clip_timestamp`：裁剪后子视频内部的帧号和时间戳

当前流程不会再用 PyAV 伪造这份映射，也不会在 processor 失败时静默回退。真实 MiniCPM processor 不可用时，子视频会直接失败，不会进入训练链路。

### 帧契约

MiniCPM-V-4.5 当前的训练帧抽取契约是：

- `video_fps = 2.0`
- `video_maxlen = 8`
- 先对实际训练会读取的子视频文件按真实时长采样，再按 `np.linspace(...).astype(np.int32)` 选帧

这意味着数据生成阶段必须和训练阶段读取的是同一个子视频文件，并且按同一套抽帧规则记录帧索引。不能再拿源视频窗口的近似帧号去替代真实训练帧映射。

### 完整复现命令

以下命令从仓库根目录执行，按顺序依次运行：

```bash
# ① 读取 CSV，生成视频元数据与 3-fold 划分
python3 pipeline/scripts/dataset_manager.py

# ② 加载 MiniCPM processor，生成子视频与元数据（需 GPU/Linux 环境）
python3 pipeline/scripts/subvideo_builder.py --model models/minicpmv4_5 --extract-frames

# ③ 子视频元数据 → ShareGPT 训练 JSON
python3 pipeline/scripts/training_sample_builder.py

# ④ 校验 fracture_between 与帧范围一致性
python3 scripts/validate_no_oob.py

# ⑤ 强制质量检查（路径、字段、数据泄漏）
python3 pipeline/scripts/quality_check.py

# ⑥ 冻结数据版本
python3 pipeline/scripts/freeze_data_version.py

# ⑦ （可选）校准检查
python3 pipeline/scripts/calibration.py
```

#### 步骤 ② 参数说明

| 参数                   | 必传？             | 默认值                  | 说明                                                |
| -------------------- | --------------- | -------------------- | ------------------------------------------------- |
| `--model`            | **是**（模型路径非默认时） | `models/minicpmv4_5` | MiniCPM-V 4.5 模型目录；也兼容 `models/minicpm_v_4_5` 等本地别名 |
| `--preprocessor`     | 否               | `minicpm`            | 当前只有 MiniCPM，不传即为默认值                              |
| `--extract-frames`   | 否               | 不抽帧                  | 加上后同时抽取子视频的采样帧图到 `data/04_frames/`                |
| `--fast`             | 否               | 完整模式                 | 快速模式：仅更新元数据，不重新编码 mp4                             |
| `--seed`             | 否               | `42`                 | 随机种子，保持默认即可                                       |
| `--skip-healthcheck` | 否               | 执行检查                 | 首次建议不传，让脚本验证 processor 加载正常                       |

> **注意事项**：
>
> - 步骤 ② 依赖 MiniCPM 视频处理器（需 GPU / Linux 环境），在 macOS 上无法完整运行。
> - `--model` 的默认路径是 `models/minicpmv4_5`。如果本地目录名不同，建议显式指定；代码会兼容常见的 `minicpm_v_4_5` / `minicpm-v-4.5` 别名。
> - 步骤 ② 完成后，后续步骤才可继续。步骤 ③ 会拒绝旧的或不完整 `processor_fingerprint`，避免历史 `subvideos_meta.json` 混入训练。
> - 步骤 ② 默认会编码 mp4 子视频到 `data/03_subvideos/`，可通过 `--fast` 跳过（仅更新元数据）。

### 子视频快速模式

仅更新元数据而不重新编码视频：

```bash
python3 -m pipeline.scripts.subvideo_builder --fast
```

### 清理旧产物

```bash
python3 -m scripts.clear_data_outputs
```

受保护的目录（`data/01_videos/`、`data/02_annotations/`）不会被清理。

## 训练

### 启动训练

```bash
cd finetune

python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml
```

每个 fold 对应一份 YAML 配置，手动或串行依次启动 `fold0`、`fold1`、`fold2`：

```bash
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold1.yaml
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold2.yaml
```

### 关键超参

| 参数            | 值                                     | 说明                      |
| ------------- | ------------------------------------- | ----------------------- |
| 基座模型          | MiniCPM-V-4.5                         | 多模态视觉-语言模型              |
| 微调方式          | LoRA (rank=16, alpha=32, dropout=0.1) | 参数高效微调                  |
| 每卡 batch size | 1 × gradient accumulation 16 = 有效 16  | 适配 24GB 显存              |
| 学习率           | 1.5e-5, cosine 调度, warmup 5%          | <br />                  |
| 训练轮数          | 8 epochs                              | 每 epoch 验证 + 保存         |
| 精度            | BF16 混合精度                             | <br />                  |
| 优化器           | paged\_adamw\_8bit                    | 节省显存                    |
| 最大帧数          | 8 帧/视频                                | 与 processor contract 一致 |
| 最大序列长度        | 2048                                  | <br />                  |

训练时真正读取的是 `data/03_subvideos/` 下的子视频文件，训练 JSON 由 `data/07_metadata/subvideos_meta.json` 生成。也就是说，子视频生成阶段必须先把“实际会喂给 MiniCPM 的视频文件”和“对应帧映射”记录正确，训练阶段只是消费这些已冻结的元数据，不再重新猜帧。

### LoRA 合并

训练完成后，将 LoRA adapter 合并回基座模型。编辑 `finetune/MiniCPM/config/merge.yaml`，替换 `adapter_name_or_path` 和 `export_dir` 为对应 fold 的路径：

| fold | adapter\_name\_or\_path                                   | export\_dir                                                      |
| ---- | --------------------------------------------------------- | ---------------------------------------------------------------- |
| 0    | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged` |
| 1    | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k1` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k1_merged` |
| 2    | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k2` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k2_merged` |

```bash
cd finetune
llamafactory-cli export MiniCPM/config/merge.yaml
```

## 验证

验证流程：推理 → 评估 → 模型对比。

正式报告必须使用同一 `split`、同一 `prompt_preset`、同一 `generation` 参数，确保基座模型与微调模型在同一协议下可公平对比。

### Prompt 协议

当前评估使用 **interval 五字段协议**，模型需输出以下 JSON 对象：

```json
{
  "has_fracture": true | false | null,
  "fracture_between": [i, i+1] | null,
  "type": "韧性断裂" | "脆性断裂" | ...,
  "location": "inside_gauge" | "outside_gauge" | null,
  "confidence": 0.0 ~ 1.0
}
```

五字段协议通过 `strict_interval` 或 `fewshot_interval` prompt preset 启用，与训练数据的 assistant 输出格式一致。

**合法组合规则**：

- 七类断裂类型：`has_fracture=true`，`fracture_between=[i, i+1]`，`location=inside_gauge/outside_gauge`
- 未断裂/未夹紧：`has_fracture=false`，`fracture_between=null`，`location=null`
- 视频异常：`has_fracture=null`，`fracture_between=null`，`location=null`
- `confidence` 始终为 0\~1 数字

### 推理

从项目根目录（`TensileAgent/`）运行：

```bash
# 基座模型推理（test split）
python3 -m finetune.validation.run_inference \
    --task joint \
    --split test \
    --model-dir models/minicpm-v-4.5 \
    --model-name base \
    --prompt-preset strict_interval \
    --output results/base_test.jsonl

# 微调模型推理（fold_0 val split）
python3 -m finetune.validation.run_inference \
    --task joint \
    --split fold_0_val \
    --model-dir LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged \
    --model-name finetuned_fold0 \
    --prompt-preset strict_interval \
    --output results/finetuned_fold0_val.jsonl

# 微调模型推理（test split）
python3 -m finetune.validation.run_inference \
    --task joint \
    --split test \
    --model-dir LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged \
    --model-name finetuned_test \
    --prompt-preset strict_interval \
    --output results/finetuned_test.jsonl

# 兼容旧模式（fold 参数）
python3 -m finetune.validation.run_inference \
    --task joint \
    --fold 0 \
    --model-dir LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged \
    --output results/joint_fold0.jsonl
```

**支持的 split**: `fold_0_val`, `fold_1_val`, `fold_2_val`, `test`

**重要**：

- 基座模型和微调模型必须使用 **同一 prompt preset**。不要给基座模型加额外提示词。
- Generation 参数固定为 `do_sample=False, num_beams=1, max_new_tokens=256`，不在正式评估中使用随机采样。
- **帧映射生成**：test split 的视频帧映射从 `all_videos_tag.csv` 中的 `视频总帧数` 和 `视频帧率` 自动生成（匹配 MiniCPM processor 的均匀采样行为）。如果 CSV 元数据完整，test split 的 interval 评估可以正常运行。fold val split 继续使用 `subvideos_meta.json` 的完整帧映射。
- 如果本地没有远程视频文件（`data/01_videos/`），推理会因 `video_load_failed` 失败——这不是评估逻辑的缺陷。正式评估应在远程 4090 完整数据目录运行。

### 评估

三种评估维度，均在项目根目录运行：

```bash
# 1. 时间定位评估（区间命中率、中点 MAE/MSE、within_1s/3s/5s）
python3 -m finetune.validation.evaluate_time \
    --inputs results/base_test.jsonl \
    --out-dir results/eval_time_base

# 2. 类型分类评估（Accuracy、Macro-F1、FP/FN 率、混淆矩阵）
python3 -m finetune.validation.evaluate_type \
    --inputs results/base_test.jsonl \
    --out-dir results/eval_type_base

# 3. 联合评估（interval 协议联合成功率、失败原因分布）
python3 -m finetune.validation.evaluate_joint \
    --inputs results/base_test.jsonl \
    --out-dir results/eval_joint_base
```

可选 `--split` 参数过滤（从 split JSON 加载 video\_id 集合）：

```bash
python3 -m finetune.validation.evaluate_time \
    --inputs results/finetuned_fold0_val.jsonl \
    --out-dir results/eval_time_fold0 \
    --split fold_0_val
```

**输出说明**：

| 评估脚本             | JSON 输出                                                                                 | CSV 输出                                                                                                        |
| ---------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `evaluate_time`  | `time_metrics.json`（正式指标：`interval_metrics`；`deprecated_legacy_metrics` 仅用于向后兼容）        | `interval_errors.csv`, `invalid_schema.csv`, `time_errors.csv`（legacy）, `time_confidence_buckets.csv`（legacy） |
| `evaluate_type`  | `type_metrics.json`（accuracy, macro\_f1, fp/fn rates）                                   | `type_per_class.csv`, `type_confusion_matrix.csv`, `invalid_schema.csv`                                       |
| `evaluate_joint` | `joint_metrics.json`（正式指标：`joint_interval_metrics`；`deprecated_legacy_metrics` 仅用于向后兼容） | `joint_interval_failures.csv`, `joint_failures.csv`（legacy）, `invalid_schema.csv`                             |

> **正式报告指标**：所有 `time_metrics.json` 和 `joint_metrics.json` 中，请只引用 `interval_metrics` 和 `joint_interval_metrics` 作为正式指标。`deprecated_legacy_metrics` 子对象包含使用旧 prompt 协议（time/type 字段）的聚合指标，保留仅供向下兼容，不应在 interval 五字段协议评估中使用。

### 模型对比

对比基座模型与微调模型在同一 split 上的性能差异：

```bash
python3 -m finetune.validation.compare_models \
    --inputs \
        base=results/base_test.jsonl \
        finetuned=results/finetuned_test.jsonl \
    --out-dir results/compare_test
```

**输出**：

| 文件                          | 说明                                                |
| --------------------------- | ------------------------------------------------- |
| `model_summary.json`        | 所有模型的完整指标汇总                                       |
| `delta_summary.json`        | finetuned - base 的指标差值                            |
| `paired_samples.csv`        | 逐 video\_id 对比表（含 improvement/regression/same 标记） |
| `by_type_delta.csv`         | 按 gt\_type 分组的准确率变化                               |
| `{model_name}_summary.json` | 单模型详细指标                                           |

`compare_models` 会自动校验所有输入是否覆盖同一批 `video_id`，不一致时报错。

### 推理服务（同进程部署）

对单条视频进行端到端推理（预处理 → 模型推理 → 结果返回）：

```bash
python3 -m pipeline.server_proxy \
    --model /path/to/merged_model \
    --deployment-manifest /path/to/deployment_manifest.json

**必需参数说明**：
- `--model`：合并后的模型路径
- `--deployment-manifest`：部署清单 JSON 文件路径（包含 `processor_version`、`max_frames` 等）
- `--host` （可选，默认 `127.0.0.1`）
- `--port` （可选，默认 `8001`）
```

### 本地 Mac 开发注意事项

- **媒体文件缺失**：本地 Mac 通常不包含远程视频文件（`data/01_videos/`）和子视频（`data/03_subvideos/`）。运行推理会因 `video_load_failed` 或 `frame_mapping_missing` 失败，这**不是**评估逻辑缺陷。
- **数据文件可用**：`data/05_splits/`、`data/06_merged/`、`data/07_metadata/subvideos_meta.json` 等非媒体数据文件已在仓库中，`load_test_split_samples()` 等加载函数可在本地正常工作。
- **评估脚本可本地运行**：只要有推理产出的 JSONL 文件，`evaluate_time/type/joint` 和 `compare_models` 可在本地 Mac 上运行。
- **正式评估**：应在远程 4090 服务器上使用完整数据目录运行。

## 已知限制

- **负样本偏差**：当前正:负采样比约 1:1\~2:1，与真实场景分布不同；部署时需调低断裂先验阈值。
- **训练环境差异**：本地 Mac 开发，远程 4090 Linux 训练；submodule 和虚拟环境需同步。
- **评估指标相关性**：时间定位精度与断裂类型分类存在耦合（时间误差大时类型分类必然不准）。
- **数据版本管理**：数据版本依赖 git lfs 或手动同步；产物被 `.gitignore` 忽略，不提交。
- **子视频生成依赖**：`subvideo_builder.py` 需要系统安装 `ffmpeg` / `ffprobe`。
