# TensileAgent

材料拉伸试验视频的断裂行为理解项目。当前主线采用 **frame-interval 微调模型 + Meta-Agent 迭代定位**：微调模型判断给定视频片段中“断裂发生在哪两帧之间”，Meta-Agent 据此多轮缩小时间区间，最终输出断裂区间、类型、位置及置信度。

- 微调模型输出结构化 JSON，核心字段为 `has_fracture`、`fracture_between`、`type`、`location`、`confidence`。
- Agent 通过 Native Function Calling 调用 `sample_and_infer`，逐步收敛候选区间，最终调用 `terminate` 输出结果。
- 旧单点预测基线文件仍保留在 Git 索引中，但已冻结，仅用于对比。

> 详细开发约束、命名约定、提交规范见 [AGENTS.md](./AGENTS.md)。
> 接口契约、训练设计、Agent 设计分别见：
> - [docs/model_agent_interface.md](./docs/model_agent_interface.md)
> - [docs/model_finetuning_design.md](./docs/model_finetuning_design.md)
> - [docs/agent_iteration_design.md](./docs/agent_iteration_design.md)

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
├── data/
│   ├── 01_videos/          # 原始视频（本地，不提交）
│   ├── 02_annotations/     # CSV 标注与映射文件
│   ├── 03_splits/          # 旧 stratified_3_fold_* 基线 + 新 fold/test 划分
│   ├── 04_merged/          # 旧基线训练/验证 JSON（冻结保留）
│   ├── 02_subvideos/       # 新 interval 子视频产物（本地，不提交）
│   ├── 03_frames/          # 帧图缓存（本地，不提交）
│   ├── 04_new_merged/      # 新 interval ShareGPT 训练 JSON（本地，不提交）
│   └── metadata/           # video_meta.json / subvideos_meta.json（本地，不提交）
├── docs/                   # 设计文档与接口契约
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

若需要开发依赖（pytest、streamlit 等），使用：

```bash
pip install -e ".[dev]"
```

- 本地模型默认放在 `models/minicpm-v-4.6`，不提交模型权重或 checkpoint。
- Agent 远程后端需要配置 `LLM_API_KEY` 或在 `agent/config.yaml` 中填入 `agent.remote.api_key`。

## 当前主流程

### 1. 数据准备

从仓库根目录执行：

```bash
# 读取 CSV 与原始视频，生成 video_meta.json 与新 video-level 划分
python3 pipeline/scripts/dataset_manager.py

# 基于划分与 video_meta 生成子视频、帧图缓存和 subvideos_meta.json
python3 pipeline/scripts/subvideo_builder.py

# 将子视频元数据转换为 LLaMA-Factory ShareGPT JSON
python3 pipeline/scripts/training_sample_builder.py

# 校验 fracture_between 与 start_frame/end_frame 一致性
python3 scripts/validate_no_oob.py
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

llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_interval_fold0.yaml
llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_interval_fold1.yaml
llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_interval_fold2.yaml
```

训练完成后如需合并 LoRA，可参考 `finetune/MiniCPM/config/merge.yaml`。
使用该文件前，请将其中的 `adapter_name_or_path` 和 `export_dir` 替换为当前 fold 对应的 interval 路径：

| fold | adapter_name_or_path | export_dir |
|------|----------------------|------------|
| 0    | `../LlamaFactory/saves/minicpmv4_6/lora/sft_interval_3k0` | `../LlamaFactory/saves/minicpmv4_6/lora/sft_interval_3k0_merged` |
| 1    | `../LlamaFactory/saves/minicpmv4_6/lora/sft_interval_3k1` | `../LlamaFactory/saves/minicpmv4_6/lora/sft_interval_3k1_merged` |
| 2    | `../LlamaFactory/saves/minicpmv4_6/lora/sft_interval_3k2` | `../LlamaFactory/saves/minicpmv4_6/lora/sft_interval_3k2_merged` |

执行合并：

```bash
llamafactory-cli export MiniCPM/config/merge.yaml
```

> 注意：`merge.yaml` 当前仍保留旧的 `sft_3k0` / `sft_3k0_merged` 示例路径，合并前必须按上表修改。

### 3. 验证

对训练好的 fold checkpoint 运行推理：

```bash
python3 finetune/validation/run_inference.py \
  --task joint \
  --fold 0 \
  --model-dir LlamaFactory/saves/minicpmv4_6/lora/sft_interval_3k0_merged \
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

Agent 由共享执行内核 `agent/runner.py` 驱动，支持 Streamlit UI 与命令行两种入口。CLI 入口为 `agent/run.py`。

#### 启动方式

1. **Streamlit UI**

```bash
python3 -m streamlit run ui/agent_app.py
```

2. **CLI 单视频**

```bash
python3 -m agent.run --video data/01_videos/video_0001.mp4 --mock
```

3. **CLI 批量**

```bash
python3 -m agent.run --videos-dir data/01_videos --mock
```

#### Mock 模式

`--mock` 会启用 Mock 推理模式（设置环境变量 `INFERENCE_MOCK=1`），用于在没有模型服务时测试 Agent 状态机、工具调用与整体流程。Mock 不调用真实模型，仅返回占位结果，便于快速验证链路。

#### 真实运行

正式推理前，需要启动微调模型推理服务（LLaMA-Factory API），并确保环境变量 `LLM_API_KEY` 已配置（或在 `agent/config.yaml` 的 `agent.remote.api_key` 中填入有效 key）。去掉 `--mock` 后即可使用真实模型运行，例如：

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

# 自定义输入输出路径 / 采样参数
python3 pipeline/scripts/training_sample_builder.py \
  --subvideos-meta data/metadata/subvideos_meta.json \
  --splits-dir data/03_splits \
  --output-dir data/04_new_merged \
  --video-fps 8.0 \
  --video-maxlen 36
```

## 已知限制 / 当前状态

- `scripts/validate_no_oob.py` 在 `data/metadata/subvideos_meta.json` 不存在时会输出 `SKIP` 并正常退出；生成产物后才会执行严格 OOB 校验。
- `subvideo_builder.py` 的快速模式（`--fast`）依赖已有 `subvideos_meta.json`，若元数据不存在会自动退回到完整生成。
- uniform 采样换算目前假设固定 `video_fps=8.0`、`video_maxlen=36`；实际采样帧数由子视频时长、帧率与上限共同决定。
- 子视频生成依赖 `ffmpeg` / `ffprobe`，请确保系统已安装。
- 新 interval 数据产物（`data/02_subvideos/`、`data/03_frames/`、`data/04_new_merged/`、`data/metadata/`）默认被 `.gitignore` 忽略，不提交。
- 旧基线文件（`data/03_splits/stratified_3_fold_*.json`、`data/04_merged/stratified_3_fold_*_{train,val}.json`）保留在索引中，不要误删。

## 开发约束

开发、提交、测试与代码风格规范见 [AGENTS.md](./AGENTS.md)。本 README 不再重复。
