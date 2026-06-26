# TensileAgent

材料拉伸试验视频的断裂行为理解项目。当前主线采用 **frame-interval 微调模型 + Meta-Agent 迭代定位**：微调模型判断给定视频片段中“断裂发生在哪两帧之间”，Meta-Agent 据此多轮缩小时间区间，最终输出断裂区间、类型、位置及置信度。

- 微调模型输出结构化 JSON，核心字段为 `has_fracture`、`fracture_between`、`type`、`location`、`confidence`。
- Agent 通过 Native Function Calling 调用 `sample_and_infer`，逐步收敛候选区间，最终输出 `fracture`、`no_fracture` 或 `unrecognized`。
- 旧单点预测方案由另一个项目维护，本项目只导入其版本化预测产物进行统一比较。

> 详细开发约束、命名约定、提交规范见 [AGENTS.md](./AGENTS.md)。
> 当前项目设计见 [docs/PROJECT_PLAN.md](./docs/PROJECT_PLAN.md)，分步骤实施设计见 [docs/IMPLEMENTATIONS/](./docs/IMPLEMENTATIONS/)。

## 仓库结构

```text
TensileAgent/
├── agent/                  # Agent 状态机、LLM 后端、推理客户端、采样与 prompt/schema
├── pipeline/
│   ├── scripts/            # 数据准备、子视频生成、训练样本构建脚本
│   ├── config/             # 旧问题池与 JSON 模板（基线遗留）
│   └── templates/          # 旧问题模板（基线遗留）
├── finetune/
│   ├── MiniCPM/config/     # 3-fold interval 训练 YAML 与 LoRA merge 配置
│   ├── validation/         # 推理、评估脚本与结果目录
│   └── dataset_info.json   # 数据集注册表
├── LlamaFactory/           # LLaMA-Factory git submodule
├── scripts/
│   └── validate_no_oob.py  # 生成产物一致性 / OOB 校验
├── tests/                  # 项目级 pytest
├── docs/                   # 当前项目计划、实施方案和历史设计归档
├── assets/                 # 领域参考文档与项目原始说明材料
├── data/
│   ├── 01_videos/          # 原始视频（本地，不提交）
│   ├── 02_annotations/     # CSV 标注与映射文件
│   ├── 05_splits/          # 新 interval fold/test 划分
│   ├── 03_subvideos/       # 新 interval 子视频产物（本地，不提交）
│   ├── 04_frames/          # 帧图缓存（本地，不提交）
│   ├── 06_merged/          # 新 interval ShareGPT 训练 JSON（本地，不提交）
│   └── 07_metadata/        # video_meta.json / subvideos_meta.json（本地，不提交）
├── AGENTS.md               # 仓库开发规范
└── README.md
```

## 环境准备

- Python 3.11（仓库根目录 `.python-version`）。
- 初始化 LLaMA-Factory 子模块：

```bash
git submodule update --init --recursive
```

- 安装训练依赖（手动安装，或参考 [LLaMA-Factory 文档](https://github.com/hiyouga/LLaMA-Factory)）：

```bash
cd LlamaFactory/
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt
```

- 安装项目根依赖（运行 Agent CLI/UI 必需）：

```bash
pip install -e .
```

若需要开发依赖（pytest 等），使用：

```bash
pip install -e ".[dev]"
```

- 本地模型默认放在 `models/minicpm-v-4.5`，不提交模型权重或 checkpoint。
- Agent 远程后端需要配置 `LLM_API_KEY` 或在 `agent/config.yaml` 中填入 `agent.remote.api_key`。

## 数据复现流程

本节说明从原始输入到冻结数据版本的完整复现命令。以下命令均从仓库根目录执行。

### 前提条件

- 输入数据：`data/01_videos/` 原始视频、`data/02_annotations/` CSV 标注与映射文件。
- 本地模型：`models/minicpm-v-4.5/` 已放置 MiniCPM-V 4.5 权重。
- Python 依赖：按[环境准备](#环境准备)安装项目根依赖与 LLaMA-Factory 依赖；`subvideo_builder.py` 需要 `torch` 等训练环境依赖。
- 系统依赖：`ffmpeg` / `ffprobe` 已安装。
- 平台要求：真实 MiniCPM 预处理逻辑需在 Linux 训练机上运行；当前 macOS/Darwin 环境会触发平台保护逻辑并缺失 `torch`，无法完成完整复现。

### 复现步骤

```bash
# 1. （可选）清空旧产物
python3 -m scripts.clear_data_outputs
```

清理 `data/03_subvideos/`、`data/04_frames/`、`data/05_splits/`、`data/06_merged/`、`data/07_metadata/`、`data/08_runtime/` 等目录中的历史产物，避免旧数据污染新版本。`data/01_videos/` 与 `data/02_annotations/` 受保护，不会被清空。

```bash
# 2. 划分数据集与生成元数据
python3 -m pipeline.scripts.dataset_manager
```

读取 `data/02_annotations/` 中的 CSV 与映射，生成 `data/05_splits/` 下的 fold/test 划分，以及 `data/07_metadata/video_meta.json` 等视频级元数据。当前 macOS 环境此步骤可成功运行。

```bash
# 3. 生成子视频与帧图缓存
python3 -m pipeline.scripts.subvideo_builder --model models/minicpm-v-4.5
```

基于划分与 `video_meta.json` 生成 `data/03_subvideos/` 子视频、`data/04_frames/` 帧图缓存，以及 `data/07_metadata/subvideos_meta.json` 子视频元数据。该步骤调用真实 MiniCPM 视频处理器生成最多 8 帧映射。当前 macOS/Darwin 环境会失败退出，因为 `pipeline/preprocessing/minicpm_preprocessor.py` 在该平台禁用了真实处理器，且系统 Python 缺少 `torch`；需在 Linux 训练机上运行。

```bash
# 4. 构建训练样本
python3 -m pipeline.scripts.training_sample_builder
```

将子视频元数据转换为 LLaMA-Factory ShareGPT 格式，输出到 `data/06_merged/`。当前 macOS 环境阻塞，依赖步骤 3 产物。

```bash
# 5. 越界校验
python3 -m scripts.validate_no_oob
```

扫描 `data/06_merged/` 与 `data/07_metadata/`，校验 `fracture_between` 与 `start_frame/end_frame` 一致性。不产生新产物。当前 macOS 环境缺少步骤 3 产物时，`validate_no_oob.py` 会输出 `SKIP` 并以退出码 0 正常退出，无法执行严格 OOB 校验。

```bash
# 6. 质量检查
python3 -m pipeline.scripts.quality_check
```

对 `data/06_merged/` 执行强制检查，输出 `data/07_metadata/quality_check_report.json`。当前 macOS 环境阻塞，依赖步骤 3 产物。

```bash
# 7. 冻结数据版本
python3 -m pipeline.scripts.freeze_data_version
```

收集 git commit、配置哈希、处理器指纹、输入/划分/样本清单哈希与统计报告，输出 `data/07_metadata/data_version_lock.json`。当前 macOS 环境阻塞，依赖步骤 3 产物。

```bash
# 8. （可选）校准
python3 -m pipeline.scripts.calibration
```

运行可选校准，生成 `data/07_metadata/calibration_report.json`。当前 macOS 环境阻塞，依赖步骤 3 产物。

### 复现性保障

- 随机种子固定为 `42`，确保划分结果可复现。
- `quality_check.py` 与 `training_sample_builder.py` 会拒绝 mock/theoretical fingerprint，确保训练样本与质量检查对应真实运行环境。
- `freeze_data_version.py` 负责记录当前 git commit、配置哈希、处理器指纹、输入/划分/样本清单哈希与统计报告，输出 `data/07_metadata/data_version_lock.json`，不执行拒绝逻辑。
- 数据版本产物被 `.gitignore` 忽略，不提交；复现时按上述流程重新生成。

### 当前环境真实状态

- `dataset_manager.py` 可在当前 macOS 跑通，生成 `data/05_splits/` 与 `data/07_metadata/` 的部分文件。
- `subvideo_builder.py` 在 macOS 会失败，因此 `data/03_subvideos/`、`data/04_frames/` 与后续 `data/06_merged/` 在当前环境无法生成。
- 后续 `training_sample_builder.py`、`pipeline/scripts/quality_check.py`、`pipeline/scripts/freeze_data_version.py` 依赖 `subvideo_builder.py` 产物，在当前 macOS 环境同样阻塞；`scripts/validate_no_oob.py` 则标记为 `SKIP`（无法执行严格校验）。
- `data/08_runtime/` 用于运行时/验证临时文件，不属于当前数据复现流程在 macOS 上的可生成产物。

## 当前主流程

### 1. 数据准备

> 详细复现流程见上文 `## 数据复现流程`。

从仓库根目录执行：

```bash
# 读取 CSV 与原始视频，生成 video_meta.json 与新 video-level 划分
python3 -m pipeline.scripts.dataset_manager

# 基于划分与 video_meta 生成子视频、帧图缓存和 subvideos_meta.json
python3 -m pipeline.scripts.subvideo_builder --model models/minicpm-v-4.5

# 将子视频元数据转换为 LLaMA-Factory ShareGPT JSON
python3 -m pipeline.scripts.training_sample_builder

# 校验 fracture_between 与 start_frame/end_frame 一致性
python3 -m scripts.validate_no_oob
```

`subvideo_builder.py` 支持快速模式，仅更新已有子视频元数据而不重新编码：

```bash
python3 pipeline/scripts/subvideo_builder.py --fast
```

### 2. 训练

在 `LlamaFactory/` 子模块中使用项目配置文件训练 3 个 fold：

```bash
cd finetune/
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold1.yaml
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold2.yaml
```

训练完成后如需合并 LoRA，可参考 `finetune/MiniCPM/config/merge.yaml`。
使用该文件前，请将其中的 `adapter_name_or_path` 和 `export_dir` 替换为当前 fold 对应的 interval 路径：

| fold | adapter_name_or_path | export_dir |
|------|----------------------|------------|
| 0    | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged` |
| 1    | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k1` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k1_merged` |
| 2    | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k2` | `../LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k2_merged` |

执行合并：

```bash
llamafactory-cli export MiniCPM/config/merge.yaml
```

> 注意：`merge.yaml` 当前仍保留旧的 `sft_interval_3k0` / `sft_interval_3k0_merged` 示例路径，合并前必须按上表修改。

### 3. 验证

对训练好的 fold checkpoint 运行推理：

```bash
python3 finetune/validation/run_inference.py \
  --task joint \
  --fold 0 \
  --model-dir LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged \
  --output finetune/validation/results/joint_fold0.jsonl
```

然后运行对应评估脚本：

```bash
python3 finetune/validation/evaluate_joint.py \
  --inputs finetune/validation/results/joint_fold0.jsonl \
  --out-dir finetune/validation/results/joint_eval \
  --split fold_0_val
```

### 4. Agent 推理

Agent 由共享执行内核 `agent/runner.py` 驱动，支持命令行入口。CLI 入口为 `agent/run.py`。

#### 启动方式

1. **CLI 单视频**

```bash
python3 -m agent.run --video data/01_videos/video_0001.mp4 --mock
```

2. **CLI 批量**

```bash
python3 -m agent.run --videos-dir data/01_videos --mock
```

#### Mock 模式

`--mock` 会启用 Mock 推理模式（设置环境变量 `INFERENCE_MOCK=1`），用于在没有模型服务时测试 Agent 状态机、工具调用与整体流程。Mock 不调用真实模型，仅返回占位结果，便于快速验证链路。

#### 真实运行

正式推理前，需要启动项目侧 `pipeline.server_proxy` 同进程集成服务。它直接创建 LLaMA-Factory ChatModel，包装模型实际使用的 MiniCPM-V 4.5 子处理器，并把本次真实输入帧和 tensor digest 注入内部 `preprocessing` 元数据；Agent 不能直接连接 stock endpoint。部署清单格式见 `pipeline/server_deployment_manifest.example.json`。

```bash
python3 -m pipeline.server_proxy \
  --model models/minicpm-v-4.5 \
  --deployment-manifest /path/to/deployment-manifest.json
```

随后配置 `LLM_API_KEY`（或 `agent/config.yaml` 中的对应字段），并让 inference endpoint 指向 proxy。去掉 `--mock` 后运行：

```bash
export LLM_API_KEY="your-api-key"
python3 -m agent.run --video data/01_videos/video_0001.mp4
```

## 测试

从仓库根目录运行：

```bash
python3 -m pytest tests/ -q
```

## 关键脚本命令

```bash
# 生成子视频与元数据
python3 pipeline/scripts/subvideo_builder.py

# 快速模式：仅更新已有子视频元数据
python3 pipeline/scripts/subvideo_builder.py --fast

# 校验生成产物
python3 scripts/validate_no_oob.py

# 构建训练样本（默认参数）
python3 pipeline/scripts/training_sample_builder.py

# 自定义输入输出路径
python3 pipeline/scripts/training_sample_builder.py \
  --subvideos-meta data/07_metadata/subvideos_meta.json \
  --splits-dir data/05_splits \
  --output-dir data/06_merged
```

## 已知限制 / 当前状态

- `scripts/validate_no_oob.py` 在 `data/07_metadata/subvideos_meta.json` 不存在时会输出 `SKIP` 并正常退出；生成产物后才会执行严格 OOB 校验。
- `subvideo_builder.py` 的快速模式（`--fast`）依赖已有 `subvideos_meta.json`，若元数据不存在会自动退回到完整生成。
- 正式数据构建必须使用 MiniCPM-V 真实视频处理器产生的最多 8 帧映射；缺少映射时显式失败，不按 FPS 或区间宽度推算。
- 子视频生成依赖 `ffmpeg` / `ffprobe`，请确保系统已安装。
- 新 interval 数据产物（`data/03_subvideos/`、`data/04_frames/`、`data/05_splits/`、`data/06_merged/`、`data/07_metadata/`、`data/08_runtime/`）默认被 `.gitignore` 忽略，不提交。
- 旧直接预测方案不在本项目维护；对比时只导入外部项目生成的版本化预测产物。

## 开发约束

开发、提交、测试与代码风格规范见 [AGENTS.md](./AGENTS.md)。本 README 不再重复。
