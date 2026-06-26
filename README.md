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

### 创建 Conda 环境（两步法）

> **为什么不用 `conda env create -f environment.yml`？**
> 该命令的 pip 子进程将全部依赖捆绑安装，任一个包失败即整体回滚，且本地路径安装兼容性差。
> 拆分为两步可逐个排查，失败不影响已安装部分。

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
> ```bash
> conda create -n mVllm2 python=3.11 pip
> conda activate mVllm2
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> pip install -e ./LlamaFactory
> conda install av pandas Pillow pyyaml fastapi uvicorn python-multipart
> ```

### 下载模型

将 MiniCPM-V-4.5 基座模型下载至 `models/` 目录。

### 环境变量

训练前需设置以下环境变量（训练命令需在 `finetune/` 目录下执行）：

```bash
export DOWNSAMPLE_MODE=4x    # MiniCPM 视频预处理下采样策略
export DISABLE_VERSION_CHECK=1
```

## 方法论：Frame-Interval 精细化微调

传统做法对整段视频做单次预测，难以精确到秒级断裂定位。本项目采用 **frame-interval 建模**：

1. **帧级粒度**：通过 MiniCPM-V-4.5 的 processor 将视频解码为离散帧序列（默认最多 8 帧），每帧关联精确时间戳。
2. **区间标注**：断裂位置标注为相邻帧索引对 `[i, i+1]`（即 fracture_between），由真实 processor 的帧选结果推导，确保标注与模型输入一致。
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

### 完整复现命令

以下命令从仓库根目录执行，按顺序依次运行：

```bash
# ① 读取 CSV，生成视频元数据与 3-fold 划分
python3 -m pipeline.scripts.dataset_manager --csv data/02_annotations/all_videos_tag.csv

# ② 加载 MiniCPM processor，生成编码子视频与元数据
python3 -m pipeline.scripts.subvideo_builder --model models/minicpm-v-4.5

# ③ 子视频元数据 → ShareGPT 训练 JSON
python3 -m pipeline.scripts.training_sample_builder

# ④ 校验 fracture_between 与帧范围一致性
python3 -m scripts.validate_no_oob

# ⑤ 强制质量检查（路径、字段、数据泄漏）
python3 -m pipeline.scripts.quality_check

# ⑥ 冻结数据版本
python3 -m pipeline.scripts.freeze_data_version

# ⑦ （可选）校准检查
python3 -m pipeline.scripts.calibration
```

> **注意**：步骤 ② 依赖真实 MiniCPM 视频处理器（需 GPU / Linux 环境），在 macOS 上无法完整运行。步骤 ② 完成后，后续步骤才可继续。

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
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml
```

每个 fold 对应一份 YAML 配置，手动或串行依次启动 `fold0`、`fold1`、`fold2`：

```bash
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold1.yaml
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold2.yaml
```

### 关键超参

| 参数 | 值 | 说明 |
|------|-----|------|
| 基座模型 | MiniCPM-V-4.5 | 多模态视觉-语言模型 |
| 微调方式 | LoRA (rank=16, alpha=32, dropout=0.1) | 参数高效微调 |
| 每卡 batch size | 1 × gradient accumulation 16 = 有效 16 | 适配 24GB 显存 |
| 学习率 | 1.5e-5, cosine 调度, warmup 5% | |
| 训练轮数 | 8 epochs | 每 epoch 验证 + 保存 |
| 精度 | BF16 混合精度 | |
| 优化器 | paged_adamw_8bit | 节省显存 |
| 最大帧数 | 8 帧/视频 | 与 processor contract 一致 |
| 最大序列长度 | 2048 | |

### LoRA 合并

训练完成后，将 LoRA adapter 合并回基座模型。编辑 `finetune/MiniCPM/config/merge.yaml`，替换 `adapter_name_or_path` 和 `export_dir` 为对应 fold 的路径：

| fold | adapter_name_or_path | export_dir |
|------|----------------------|------------|
| 0 | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged` |
| 1 | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k1` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k1_merged` |
| 2 | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k2` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k2_merged` |

```bash
cd finetune
llamafactory-cli export MiniCPM/config/merge.yaml
```

## 验证

验证流程：推理 → 评估。

### 推理

对指定 fold 的验证集运行模型推理，输出 JSONL：

```bash
cd finetune
python3 -m validation.run_inference \
    --task joint \
    --fold 0 \
    --model-dir ../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0/checkpoint-xxx \
    --output results/joint_fold0.jsonl
```

### 评估

三种评估维度：

```bash
# 断裂时间定位评估（MAE、MSE、±2s 命中率、区间命中率、置信度分桶）
python3 -m validation.evaluate_time \
    --inputs results/joint_fold0.jsonl --split fold_0_val

# 断裂类型分类评估（Accuracy、Macro-F1、混淆矩阵、逐类指标）
python3 -m validation.evaluate_type \
    --inputs results/joint_fold0.jsonl --out-dir results/type_eval

# 联合评估（时间 + 类型联合成功率、失败原因分布）
python3 -m validation.evaluate_joint \
    --inputs results/joint_fold0.jsonl --out-dir results/joint_eval --split fold_0_val
```

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

## 已知限制

- **负样本偏差**：当前正:负采样比约 1:1~2:1，与真实场景分布不同；部署时需调低断裂先验阈值。
- **训练环境差异**：本地 Mac 开发，远程 4090 Linux 训练；submodule 和虚拟环境需同步。
- **评估指标相关性**：时间定位精度与断裂类型分类存在耦合（时间误差大时类型分类必然不准）。
- **数据版本管理**：数据版本依赖 git lfs 或手动同步；产物被 `.gitignore` 忽略，不提交。
- **子视频生成依赖**：`subvideo_builder.py` 需要系统安装 `ffmpeg` / `ffprobe`。
