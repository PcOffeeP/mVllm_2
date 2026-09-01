# mVllm_2

基于 MiniCPM-V-4.5 的材料拉伸视频视觉模型研发仓库，覆盖从原始视频治理、帧窗口标注、
训练数据发布、LoRA 微调、严格评测，到模型发布和推理服务交付的完整流程。

## 项目简介

本项目解决的核心问题，是把材料拉伸试验视频转化为来源可追踪、标签可审查的视觉训练样本，
并在此基础上完成受控微调、严格评测与可复现交付。

主要工作方式：

- **以帧窗口证据为中心**：物化子视频与实际采样帧，不把近重复画面当作独立证据；
- **受控微调**：数据 release、Prompt revision、契约 schema、fold、seed 和训练参数
  全部冻结后再进行比较；
- **严格评测**：除训练 loss 外，检查 schema 合法率、四字段准确率、`clip_state` 混淆表、
  分类别召回和失败样例；
- **模型生命周期管理**：实验产物先进入 `workspace/runs/`，人工确认后才晋级为
  `workspace/models/releases/`，最终由推理服务加载；
- **与 TensileAgent 对接**：自然语言任务编排、多轮视频搜索和结果展示由独立
  TensileAgent 项目负责，两个项目通过冻结的视觉契约和 deployment identity 对接。

当前 `main` 维护 `tensile-vlm/v4.1`。V2 已封存为回滚与历史复现对象，不再是默认开发链路。

## 项目状态

`main` 当前维护 `tensile-vlm/v4.1`。数据、训练、模型发布和推理服务流程均已跑通，
并保留了一款可用于服务与 Agent 联调的中间发布模型；当前模型质量仍未通过最终验收。
最新完整三折实验也已完成，但仍暴露出输出契约退化和类别偏置问题。

当前发布模型：`v4.1-agent-pipeline-fold0-r1`（Fold0 中间模型，仅用于工程链路验证）。

详情见 [当前项目状态与开发原则](docs/CURRENT_PROJECT_STATUS.md)。

## V4.1 视觉契约（简要）

单个帧窗口输出四个字段：

- `clip_state`：`未断裂`、`临界未断裂`、`发生断裂`、`已断裂`、`无法判断`
- `fracture_mechanism`：断裂机制；普通未断裂或无法判断时为 `null`
- `fracture_site`：`inside_gauge`、`outside_gauge_non_root`、`grip_root` 或 `null`
- `special_case`：特殊情况或 `null`

权威 artifact：

- `pipeline/contracts/tensile_vlm_v4_1.json`
- `pipeline/v4_1_labels.py`
- `finetune/v4_1_runtime.py`
- `pipeline/prompt_control/active_prompt.yaml`（新固定全字段实验的唯一 Prompt 编辑入口）
- `pipeline/prompt_registry/`（不可变 Prompt revision）

## 环境

本项目采用双环境工作流：本机（Mac）使用 uv 做代码检查、文档整理与轻量校验；训练机
（Linux/GPU）使用 Conda 执行训练、推理与重数据处理。

### Mac 本地开发（uv）

- Python 3.11
- 依赖管理：`pyproject.toml`、`uv.lock`
- 典型用途：代码检查、文档整理、Streamlit 审查 UI、已同步结果复核

> 训练、GPU 推理、完整评测必须在训练机执行，不能在本机运行。

### 训练机（Conda）

```bash
git submodule update --init --recursive
conda create -n mVllm2 python=3.11 pip -y
conda activate mVllm2
pip install -r requirements.txt
pip install -e ./LlamaFactory
```

子视频处理需要 `ffmpeg` / `ffprobe`。MiniCPM-V-4.5 基座模型放在 `models/`，或
通过具体运行配置指定。

## 快速开始

按场景进入对应文档：

- [数据处理与训练发布运行手册](docs/DATA_PROCESSING_RUNBOOK.md)：数据迁移、ROI、
  候选物化、人工审查、不可覆盖 release 构建；
- [微调、合并与评测](finetune/README.md)：三折 LoRA 训练、模型合并、严格评测、
  证据冻结；
- [推理服务运行手册](docs/INFERENCE_SERVICE_RUNBOOK.md)：当前中间服务启动、预检、
  smoke、TensileAgent 接入与停止；
- [当前项目状态](docs/CURRENT_PROJECT_STATUS.md)：发布模型身份、最新实验结果、
  下一轮优化目标；
- [V4.1 数据发布](docs/V4_1_DATA_RELEASES.md)：当前与历史 development release 统计。

## 项目结构

```text
pipeline/      数据处理、V4.1 契约、模型注册表与推理服务
finetune/      三折训练、模型合并、严格评测
workspace/     训练机本地数据、实验运行和模型资产（Git 忽略）
data/          旧外部数据根的兼容入口
config/        数据根配置
docs/          运行手册、设计、迁移报告与结果摘要
tests/         数据、契约和评测测试
LlamaFactory/  LLaMA-Factory 子模块
models/        本地模型目录
```

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [docs/CURRENT_PROJECT_STATUS.md](docs/CURRENT_PROJECT_STATUS.md) | 当前项目状态、发布模型身份、最新实验结果、开发原则 |
| [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md) | 当前数据处理链路的完整操作手册（正文声明当前支持版本） |
| [docs/V4_1_DATA_RELEASES.md](docs/V4_1_DATA_RELEASES.md) | 当前与历史 development release 统计与说明 |
| [docs/INFERENCE_SERVICE_RUNBOOK.md](docs/INFERENCE_SERVICE_RUNBOOK.md) | 当前中间推理服务启动与运维 |
| [finetune/README.md](finetune/README.md) | 微调、合并、评测与证据冻结 |
| [docs/V4_1_PHASE1_EFFECTIVE_VIEW_AUDIT.md](docs/V4_1_PHASE1_EFFECTIVE_VIEW_AUDIT.md) | V4.1 有效视图审计 |
| [docs/results/v4_1_agent_pipeline_fold0_r1/README.md](docs/results/v4_1_agent_pipeline_fold0_r1/README.md) | 当前发布模型部署证据 |
| [docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md](docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md) | 最新三折实验结果 |
| [docs/results/model_evidence/README.md](docs/results/model_evidence/README.md) | 模型归档证据包引导索引（查找模型测试结果入口） |
| [AGENTS.md](AGENTS.md) | Agent 工作说明与双机纪律 |

V2/V3 Prompt、旧审核和旧数据流水线文档只用于历史追溯。新工作应从本 README、
V4.1 契约、当前数据运行手册和冻结发布清单开始。
