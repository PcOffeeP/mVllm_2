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

从原始 CSV 标注到可训练的 ShareGPT JSON，主链路分为 **8 个必需步骤**，另有
1 个只在人工审核状态不一致时使用的可选修复步骤：

```
原始视频 + CSV 标注
    │
    ├─① dataset_manager.py     读取 CSV → 构建 video_meta.json → 3-fold 分层划分
    │                           主输出: data/05_splits/, data/07_metadata/video_meta.json
    │
    ├─② subvideo_builder.py    跳过 test，仅为 train/val 生成训练候选子视频包
    │                           输出: data/03_subvideos/, data/04_frames/,
    │                                 data/07_metadata/subvideos_meta.json
    │
    ├─③ 人工审核                 人工查看 mp4 与采样帧图片，删除脏样本的 mp4 和帧目录
    │
    ├─④ prune_reviewed_subvideos.py
    │                           根据人工删除结果清洗 subvideos_meta；不一致状态会失败
    │                           输出: data/07_metadata/subvideos_meta.reviewed.json,
    │                                 data/07_metadata/manual_review_prune_report.json
    │
    ├─可选 repair_review_media.py
    │                           只在 mp4/帧目录只缺一份时修复后重跑 ④
    │                           输出: data/07_metadata/subvideos_meta.repaired.json,
    │                                 data/07_metadata/manual_review_repair_report.json
    │
    ├─⑤ review_subvideo_labels.py
    │                           复检 full/focus/negative 等样本标签与帧映射
    │                           输出: data/07_metadata/subvideos_meta.label_reviewed.json,
    │                                 data/07_metadata/subvideo_label_review_report.json
    │
    ├─⑥ training_sample_builder.py  复检后的子视频元数据 → ShareGPT JSON
    │                                 输出: data/06_merged/fold_*_train.json / val.json
    │
    ├─⑦ validate_no_oob.py + quality_check.py
    │                           基于 label_reviewed metadata 校验区间、路径、字段、leakage、比例等
    │                           输出: data/07_metadata/quality_check_report.json
    │
    ├─⑧ freeze_data_version.py 冻结数据版本（git commit、配置哈希、processor 指纹等）
    │                           输出: data/07_metadata/data_version_lock.json
    │
    └─可选 calibration.py       校验预处理适配层与 LLaMA-Factory 真实 batch 加载一致
                               输出: data/07_metadata/calibration_report.json
```

步骤 ① 的 `inventory_report.json`、`stratified_split_decision_log.json` 和
`frame_index_validation.json` 属于诊断/审计产物，当前只在传入 `--debug-report`
时生成，不是训练数据主链路的必需输入。主链路只依赖 `video_meta.json` 与
`data/05_splits/` 下的 split 文件。

### 子视频元信息

步骤 ② 生成的 `subvideos_meta.json` 记录的是训练候选子视频契约，不是简单的裁剪日志。关键字段包括：

- `video_path`：子视频实际文件路径
- `start_time` / `end_time` / `start_frame` / `end_frame` / `duration`
- `crop_type`、`source_video`、`selection_reason`
- `has_fracture`、`fracture_between`、`type`、`location`
- `processor_fingerprint`、`processor_info`
- `actual_frame_mapping`、`sampled_frames`、`frame_paths`

其中最关键的是 `actual_frame_mapping`。它同时保留两套坐标：

- `original_frame` / `timestamp`：映射回源视频后的全局帧号和时间戳
- `clip_frame` / `clip_timestamp`：裁剪后子视频内部的帧号和时间戳

步骤 ② 默认应导出采样帧图片到 `data/04_frames/<subvideo_id>/`，`frame_paths` 中的图片按 `actual_frame_mapping` 逐帧导出：裁剪子视频优先使用 `clip_frame`，完整视频使用同源坐标。图片数量必须和 `actual_frame_mapping` 条数一致，不再通过 ffmpeg `fps` 滤镜重新近似采样。

当前流程不会再用 PyAV 伪造这份映射，也不会在 processor 失败时静默回退。真实 MiniCPM processor 不可用时，子视频会直接失败，不会进入训练链路。

### 人工审核与标签复检

子视频和标签由代码生成，仍可能受到脏片尾、额外图像数据、非预期抽帧或标签边界偏差影响。因此 ShareGPT 训练 JSON 生成前必须经过人工审核和标签复检。

人工审核以 `data/03_subvideos/*.mp4` 与 `data/04_frames/<subvideo_id>/` 为准：

- 保留样本：mp4 与对应帧目录都存在。
- 删除样本：人工删除该样本的 mp4 或对应帧目录即可，清洗脚本会从 metadata 中剔除该样本。
- 不一致状态：mp4 文件仍存在但为空/无效且帧目录仍存在时，不允许继续清洗 metadata，必须先修复。

不要删除 `data/01_videos/` 下的源视频。完整视频样本也需要有可审核的 `data/03_subvideos/<subvideo_id>.mp4` 或等价审核媒体；如果完整视频样本有问题，只删除该样本自己的审核媒体和帧目录。

人工审核后运行：

```bash
python3 pipeline/scripts/prune_reviewed_subvideos.py \
  --subvideos-meta data/07_metadata/subvideos_meta.json \
  --output-meta data/07_metadata/subvideos_meta.reviewed.json \
  --report data/07_metadata/manual_review_prune_report.json
```

如果出现 mp4 文件仍存在但为空/无效等非人工删除状态，先运行修复脚本补齐异常媒体，再重新执行清洗。人工删除导致的 mp4 或帧目录缺失不会被修复脚本重新生成：

```bash
python3 pipeline/scripts/repair_review_media.py \
  --subvideos-meta data/07_metadata/subvideos_meta.json \
  --output-meta data/07_metadata/subvideos_meta.repaired.json \
  --report data/07_metadata/manual_review_repair_report.json

python3 pipeline/scripts/prune_reviewed_subvideos.py \
  --subvideos-meta data/07_metadata/subvideos_meta.repaired.json \
  --output-meta data/07_metadata/subvideos_meta.reviewed.json \
  --report data/07_metadata/manual_review_prune_report.json
```

随后进行标签复检：

```bash
python3 pipeline/scripts/review_subvideo_labels.py \
  --subvideos-meta data/07_metadata/subvideos_meta.reviewed.json \
  --output-meta data/07_metadata/subvideos_meta.label_reviewed.json \
  --report data/07_metadata/subvideo_label_review_report.json
```

标签复检规则：

- full 原视频样本必须与 `video_meta.json` 中的治理后标签一致。
- focus 正样本必须能用 `actual_frame_mapping` 和原视频事件帧重新算出相同的 `fracture_between`。
- negative 样本必须保持 `has_fracture=false`、`fracture_between=null`、`location=null`。
- 每条保留样本必须有非空 `actual_frame_mapping`，帧数不超过 8，帧图片数量与映射数量一致。
- `视频异常`、`未夹紧` 等特殊类型按标签治理语义单独校验。

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

# 如需额外审计报告，可加 --debug-report
# python3 pipeline/scripts/dataset_manager.py --debug-report

# ②a 先跑小样本子视频生成，检查 adaptive focus、命名、帧映射和输出目录
python3 pipeline/scripts/subvideo_builder.py \
  --model models/minicpmv4_5 \
  --sample-size 10 \
  --sample-seed 42 \
  --sample-boundary-weighted \
  --sample-output-dir data/sample_subvideos

# 检查 data/sample_subvideos/ 下的 sample_manifest.json、03_subvideos/、04_frames/。
# 确认无问题后，再显式运行全量生成；sample 模式不会自动继续全量生成。

# ②b 加载 MiniCPM processor，生成全量子视频与元数据（需 GPU/Linux 环境）
python3 pipeline/scripts/subvideo_builder.py --model models/minicpmv4_5

# ③ 人工审核 data/03_subvideos/ 与 data/04_frames/，删除脏样本的 mp4 或帧目录

# ④ 根据人工审核结果清洗 metadata
python3 pipeline/scripts/prune_reviewed_subvideos.py \
  --subvideos-meta data/07_metadata/subvideos_meta.json \
  --output-meta data/07_metadata/subvideos_meta.reviewed.json \
  --report data/07_metadata/manual_review_prune_report.json

# 若上一步报告 mp4/帧目录不一致，先修复后重新清洗：
# python3 pipeline/scripts/repair_review_media.py \
#   --subvideos-meta data/07_metadata/subvideos_meta.json \
#   --output-meta data/07_metadata/subvideos_meta.repaired.json \
#   --report data/07_metadata/manual_review_repair_report.json
# python3 pipeline/scripts/prune_reviewed_subvideos.py \
#   --subvideos-meta data/07_metadata/subvideos_meta.repaired.json \
#   --output-meta data/07_metadata/subvideos_meta.reviewed.json \
#   --report data/07_metadata/manual_review_prune_report.json

# ⑤ 复检子视频标签
python3 pipeline/scripts/review_subvideo_labels.py \
  --subvideos-meta data/07_metadata/subvideos_meta.reviewed.json \
  --output-meta data/07_metadata/subvideos_meta.label_reviewed.json \
  --report data/07_metadata/subvideo_label_review_report.json

# ⑥ 子视频元数据 → ShareGPT 训练 JSON
python3 pipeline/scripts/training_sample_builder.py \
  --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json

# ⑦ 校验 fracture_between、路径、字段、数据泄漏
python3 scripts/validate_no_oob.py
python3 pipeline/scripts/quality_check.py \
  --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json

# ⑧ 冻结数据版本
python3 pipeline/scripts/freeze_data_version.py \
  --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json

# 可选：校准检查
python3 pipeline/scripts/calibration.py
```

#### 步骤 ② 参数说明

| 参数                   | 必传？             | 默认值                  | 说明                                                |
| -------------------- | --------------- | -------------------- | ------------------------------------------------- |
| `--model`            | **是**（模型路径非默认时） | `models/minicpmv4_5` | MiniCPM-V 4.5 模型目录；也兼容 `models/minicpm_v_4_5` 等本地别名 |
| `--preprocessor`     | 否               | `minicpm`            | 当前只有 MiniCPM，不传即为默认值                              |
| `--extract-frames`   | 否               | 默认抽帧                 | 保留兼容参数；子视频生成应默认输出采样帧图到 `data/04_frames/`       |
| `--fast`             | 否               | 完整模式                 | 快速模式：仅更新元数据，不重新编码 mp4                             |
| `--seed`             | 否               | `42`                 | 随机种子，保持默认即可                                       |
| `--skip-healthcheck` | 否               | 执行检查                 | 首次建议不传，让脚本验证 processor 加载正常                       |

#### 步骤 ② 小样本生成参数

小样本模式用于在全量生成前先抽取一小批视频跑通子视频生成逻辑，尤其适合检查 adaptive focus、边界事件、文件命名、`crop_type`、帧映射和输出质量。只要传入 `--sample-size` 或 `--video-ids`，脚本就会进入 sample 模式，生成样本后直接退出，不会自动继续全量生成。

默认 sample 输出写入 `data/sample_subvideos/`，结构为：

- `data/sample_subvideos/03_subvideos/`：样本 mp4 子视频
- `data/sample_subvideos/04_frames/`：样本采样帧图片
- `data/sample_subvideos/sample_manifest.json`：样本清单、计数、输出路径和排除原因

| 参数 | 必传？ | 默认值 | 说明 |
| ---- | ------ | ------ | ---- |
| `--sample-size` | 否 | 不启用 | 抽取多少个源视频生成小样本；传入时必须 `>= 1`，例如 `--sample-size 10` |
| `--sample-seed` | 否 | `--seed` 的值 | 小样本抽样随机种子；同一输入和种子应得到同一批样本 |
| `--sample-output-dir` | 否 | `data/sample_subvideos` | 小样本输出根目录；不会写入正式 `data/03_subvideos/`、`data/04_frames/` 或 `data/07_metadata/subvideos_meta.json` |
| `--video-ids` | 否 | 不启用 | 显式指定要生成的小样本视频 ID；传入后只处理这些 ID，例如 `--video-ids VID001 VID002` |
| `--sample-boundary-weighted` | 否 | 关闭 | 边界加权抽样，优先选择断裂时刻靠近开头/结尾、更容易触发 adaptive focus 的视频 |

常用示例：

```bash
# 随机抽 10 个训练/验证视频，但优先覆盖边界事件
python3 pipeline/scripts/subvideo_builder.py \
  --model models/minicpmv4_5 \
  --sample-size 10 \
  --sample-seed 42 \
  --sample-boundary-weighted \
  --sample-output-dir data/sample_subvideos

# 只生成指定视频的小样本，方便复现单个问题
python3 pipeline/scripts/subvideo_builder.py \
  --model models/minicpmv4_5 \
  --video-ids VIDEO_ID_001 VIDEO_ID_002 \
  --sample-output-dir data/sample_subvideos/debug_case
```

> **注意事项**：
>
> - 步骤 ② 依赖 MiniCPM 视频处理器（需 GPU / Linux 环境），在 macOS 上无法完整运行。
> - `--model` 的默认路径是 `models/minicpmv4_5`。如果本地目录名不同，建议显式指定；代码会兼容常见的 `minicpm_v_4_5` / `minicpm-v-4.5` 别名。
> - 步骤 ② 完成后，必须先经过人工审核、metadata 清洗与标签复检，再生成 ShareGPT 训练 JSON。
> - 步骤 ② 默认会编码 mp4 子视频到 `data/03_subvideos/`，可通过 `--fast` 跳过（仅更新元数据）。
> - 小样本模式只用于预检，不会写正式全量输出；全量生成必须在检查 sample 输出后单独显式运行。

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

训练时真正读取的是复检后 metadata 指向的视频文件，训练 JSON 由 `data/07_metadata/subvideos_meta.label_reviewed.json` 生成。`training_sample_builder.py`、`quality_check.py`、`validate_no_oob.py` 和 `freeze_data_version.py` 当前都默认使用这份 label-reviewed metadata；如需临时检查未复检文件，必须显式传参，`quality_check.py` 还需要额外传入 `--allow-unreviewed-meta`。也就是说，子视频生成和人工复检阶段必须先把“实际会喂给 MiniCPM 的视频文件”和“对应帧映射”记录正确，训练阶段只是消费这些已冻结的元数据，不再重新猜帧。

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

正式报告必须使用同一 `dataset`、同一 `prompt`、同一 `generation` 参数，确保不同模型在同一协议下可公平对比。

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

五字段协议由 `training` 和 `system` 两版 prompt 共同约束：`training` 与训练样本提示保持一致，`system` 额外强调字段取值和组合规则。

**合法组合规则**：

- 七类断裂类型：`has_fracture=true`，`fracture_between=[i, i+1]`，`location=inside_gauge/outside_gauge`
- 未断裂/未夹紧：`has_fracture=false`，`fracture_between=null`，`location=null`
- 视频异常：`has_fracture=null`，`fracture_between=null`，`location=null`
- `confidence` 始终为 0\~1 数字

### 直接返回评估

测试架构已重构为单一路径：直接查看模型最终返回的五字段 JSON，不再做旧的 time/type/joint 二次转换评估。

每次评估只选择三项：

1. `--dataset`：`test` / `test_subvideos` / `fold_0_val` / `fold_1_val` / `fold_2_val`
2. `--model-dir`：微调后模型地址
3. `--prompt`：`training`（训练时 prompt）或 `system`（带输出约束的 prompt）

训练机上运行完整推理与评估（需要模型、视频文件和 GPU）：

```bash
python3 -m finetune.validation.run_evaluation \
    --dataset test_subvideos \
    --model-dir LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged \
    --prompt system \
    --out-dir results/eval_test_subvideos_system
```

本地 Mac 只复核已有预测 JSONL（不跑模型、不需要 GPU）：

```bash
python3 -m finetune.validation.run_evaluation \
    --dataset test_subvideos \
    --predictions finetune/results/direct_test_subvideos_system.jsonl \
    --prompt system \
    --out-dir results/eval_test_subvideos_system
```

预测 JSONL 至少需要包含 `video_id` 和 `raw_output`；`raw_output` 是模型原始返回文本。

输出文件：

| 文件 | 说明 |
| ---- | ---- |
| `evaluation_summary.json` | 格式合格率、直接预测正确率、五字段逐字段准确率 |
| `evaluation_records.jsonl` | 每个样本的 raw output、解析 payload、目标值、字段比较结果 |
| `failures.csv` | 运行失败、格式不合格、预测错误样本 |

正式验收只看两类信息：

- 返回格式是否满足五字段协议：`has_fracture`、`fracture_between`、`type`、`location`、`confidence`
- 每个可评估字段的最终预测是否正确

`confidence` 没有人工 ground truth，评估只检查它是否为 `[0, 1]` 数字。若数据集缺少某个字段的 ground truth，该字段会标记为 `unavailable` 并从该字段准确率中排除。

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
- **数据文件可用**：`data/05_splits/`、`data/06_merged/`、`data/07_metadata/subvideos_meta.label_reviewed.json` 等非媒体数据文件可在仓库或同步产物中使用，`load_test_split_samples()` 等加载函数可在本地正常工作。
- **评估脚本可本地运行**：只要有包含 `video_id` 和 `raw_output` 的预测 JSONL，`run_evaluation --predictions ...` 可在本地 Mac 上运行。
- **正式评估**：应在远程 4090 服务器上使用完整数据目录运行。

## 已知限制

- **负样本偏差**：当前正:负采样比约 1:1\~2:1，与真实场景分布不同；部署时需调低断裂先验阈值。
- **训练环境差异**：本地 Mac 开发，远程 4090 Linux 训练；submodule 和虚拟环境需同步。
- **评估指标相关性**：时间定位精度与断裂类型分类存在耦合（时间误差大时类型分类必然不准）。
- **数据版本管理**：数据版本依赖 git lfs 或手动同步；产物被 `.gitignore` 忽略，不提交。
- **子视频生成依赖**：`subvideo_builder.py` 需要系统安装 `ffmpeg` / `ffprobe`。
