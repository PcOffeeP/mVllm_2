# mVllm_2

**面向材料拉伸试验视频的视觉模型与数据工作流。** 本项目基于 MiniCPM-V-4.5，从视频中提取按时间排列的采样帧，判断试样是否断裂、可能的断裂机制、断裂位置及画面中的特殊情况，并把结果输出为统一的 JSON，供后续视频分析与检索使用。

仓库包含数据准备、人工审查、LoRA 微调、评测和推理服务代码，以及已有实验的轻量结果与验证记录。当前仍处于模型研发阶段：数据与模型管理流程已有工程交付，尚无经最终独立测试验收的对外最终模型。

## 项目介绍

### 从视频画面到结构化判断

拉伸试验视频记录了试样伸长、颈缩、断裂和分离等过程。本项目关注其中一个有限时间窗口：模型只依据该窗口内实际可见的画面判断，不能用片段外发生的事件补全答案。

处理过程由以下环节组成：

1. **准备视频证据**：保留原始来源与数据划分，标注 ROI（感兴趣区域，即需要观察的试样区域），生成子视频和采样帧。
2. **建立训练样本**：人工审查关键窗口及标签，将审核后的样本封存为可追溯的数据发布。
3. **微调与评测**：通过 LoRA 更新少量附加参数，适配材料拉伸画面；使用三折训练与验证比较开发阶段效果，即分别训练三次，每次使用对应划分的训练集和验证集。
4. **提供视觉判断**：服务按统一契约返回结构化结果，供上层应用进一步组织视频搜索和展示。

当前输出契约为 `tensile-vlm/v4.1`，每个窗口最多使用 8 帧，包含四个字段：

| 字段 | 回答的问题 | 可选值 |
| --- | --- | --- |
| `clip_state` | 当前窗口是否已经出现断裂？ | 未断裂、临界未断裂、发生断裂、已断裂、无法判断 |
| `fracture_mechanism` | 画面支持哪种断裂机制判断？ | 韧性断裂、脆性断裂、界面脱粘、爆炸性断裂、半脆半韧断裂，或 `null` |
| `fracture_site` | 断裂发生在哪里？ | `inside_gauge`（标距内）、`outside_gauge_non_root`（标距外且非夹具根部）、`grip_root`（夹具根部），或 `null` |
| `special_case` | 是否存在影响判断的特殊情况？ | 未夹紧、视频异常，或 `null` |

下面仅为输出格式示例，不是实际推理结果：

```json
{
  "clip_state": "发生断裂",
  "fracture_mechanism": "韧性断裂",
  "fracture_site": "inside_gauge",
  "special_case": null
}
```

“发生断裂”表示窗口内可见从连续到分离的变化；“已断裂”表示可靠画面从窗口开始就已经分离。这种区分可以帮助上层应用判断断裂事件位于窗口内、之前还是之后。“无法判断”不提供搜索方向。字段之间也有约束，例如“未断裂”时其余三个字段均须为 `null`。完整定义见 [V4.1 契约](pipeline/contracts/tensile_vlm_v4_1.json)。

本仓库负责视觉判断及其数据、训练和服务流程。自然语言任务编排、多轮视频搜索与结果展示由独立的TensileAgent 项目负责，双方通过冻结的视觉契约和部署身份对接。

### 已有成果与当前边界

项目已经建立从原始视频、ROI、子视频与采样帧、人工审查到数据发布的流程，并提供训练、评测、模型登记和服务入口。现行流程以显式版本绑定数据、Prompt、训练、模型和评测，便于追溯某次结果使用了什么输入和配置。已有三折实验、逐样本评测材料和历史服务联调记录。

作为初步模型成果，历史 Fold0 中间开发模型曾走通微调、权重合并、视频推理服务和 TensileAgent 调用。其在 **425 条开发侧 validation 样本**上的历史结果为：

| 指标 | 结果 | 含义 |
| --- | ---: | --- |
| 严格输出合法率 | 100% | 输出符合四字段契约及其约束 |
| 四字段联合正确率 | 41.18% | 四个字段同时符合参考标签 |

这些结果说明结构化输出和调用链路已有基础，但任务效果仍需改善。它们来自一个 Fold0 开发模型，不代表三折总体结果、最终独立 test 成绩或生产可用性。来源和评测口径见[模型效果基线](docs/MODEL_GATE_BASELINE.md#3-已知效果仅引用历史开发侧证据)及[历史服务联调记录](docs/results/v4_1_agent_pipeline_fold0_r1/README.md)。

当前使用者还需了解以下边界：

- 克隆代码不会获得原始视频、基座权重、LoRA adapter 或完整实验目录，这些资产需要另行准备。
- 独立 test 的使用资格、最终模型质量、现行正式模型的真实服务成功路径，以及大型产物组合恢复仍有未完成验收项。
- 已迁移的数据发布仍可能引用外部媒体，不能假定一个 store 目录包含全部数据。

## 快速开始

### 1. 先了解输出与结果

没有 GPU 或模型资产，也可以先阅读本仓库：

- 阅读上面的四字段定义和 [V4.1 契约](pipeline/contracts/tensile_vlm_v4_1.json)，了解一个窗口的判断范围。
- 查看 [模型证据索引](docs/results/model_evidence/README.md)和 [历史三折实验报告](docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md)，了解效果、失败类型与证据限制。
- 查看 [数据发布说明](docs/V4_1_DATA_RELEASES.md)，了解样本组成和 train/validation 划分。

以下安装步骤用于建立代码运行环境。安装完成后可以查看统一 CLI、开展代码检查，并按手册准备自己的输入；它不会自动下载模型，也不会自动执行视频推理。

### 2. 准备运行环境

取得仓库代码后，在项目根目录执行命令。当前提供两个锁定环境配置：

| 配置 | 适用平台与用途 | 依赖来源 |
| --- | --- | --- |
| `mac` | macOS；代码检查、人工审查 UI、已同步结果复核 | `pyproject.toml` 与 `uv.lock`，包含开发依赖 |
| `linux-gpu` | Linux x86_64 NVIDIA GPU 训练机；数据处理、训练与推理 | `requirements-linux-gpu.lock` 与固定的 LlamaFactory 子模块 |

先安装 **Python 3.11、uv、Git、ffmpeg 和 ffprobe**，确保后四项在 `PATH` 中可用。Linux GPU 还需要可用的 NVIDIA 驱动，`nvidia-smi` 能正常运行。部署脚本不会安装这些系统工具。

下面的命令使用两个占位路径，执行前请替换：

- `/absolute/python3.11`：已有 Python 3.11 解释器的绝对路径。
- `/absolute/new/environment`：准备创建的新环境绝对路径，目录须不存在；路径不能经过符号链接或包含 `..`。

**macOS：**

```bash
python3 scripts/source_prepare_environment.py --profile mac \
  --env /absolute/new/environment --python /absolute/python3.11
```

**Linux GPU：** 先初始化项目固定的子模块，再部署环境。[.gitmodules](.gitmodules) 中的 LlamaFactory 使用 Gitee SSH 地址，需具备相应 SSH 认证与仓库访问资格；子模块必须保持干净并匹配当前项目提交固定的版本。

```bash
git submodule update --init --recursive

python3 scripts/source_prepare_environment.py --profile linux-gpu \
  --env /absolute/new/environment --python /absolute/python3.11
```

两种配置分别安装，不要叠加到同一个环境。Linux 默认使用 PyPI，镜像选项与部署维护说明见[环境部署脚本索引](scripts/SCRIPTS.md)。安装失败时脚本保留部分创建的环境；重试应选择新的目标目录，不会自动覆盖原目录。

### 3. 检查安装并查看入口

安装退出码为 0 且输出 `Deployment verified` 表示环境检查通过。之后直接使用新环境的解释器，无需依赖 shell 当前激活的环境：

```bash
/absolute/new/environment/bin/python -m versioning --help

# macOS 手动复查；Linux GPU 将 mac 换为 linux-gpu。
/absolute/new/environment/bin/python scripts/source_validate_environment.py --profile mac
```

环境检查涵盖锁定依赖、依赖冲突、公共入口和媒体工具；Linux 还检查 CUDA 及 LlamaFactory 来源。检查不会加载模型或执行训练、推理和评测。Linux 的 LlamaFactory 以 editable 方式绑定当前代码工作区，使用该环境时应保留对应工作区。

`versioning` 是正式数据与模型流程的统一 CLI。数据、Prompt、训练、模型、评测使用`<kind>-v<协议>-r<N>` 完整身份，例如 `data-v4.1-r2`；这些示例身份不表示本地已具备相应资产。命令不自动选择“最新版本”，缺少必要输入或引用不合法时会停止。

### 4. 按目标准备资产并运行

正式操作还需要实际数据、基座模型、冻结 Prompt 和相应配置。模型服务还需要与训练和评测证据一致的模型身份、权重及部署配置。当前没有可直接从本 README 下载并运行的最终模型演示，请沿对应手册准备输入：

| 你希望做什么 | 下一份文档 | 主要前置输入 |
| --- | --- | --- |
| 将试验视频整理成训练数据 | [数据处理手册](docs/DATA_PROCESSING_RUNBOOK.md) | 原始视频、注释与既定划分、ROI 和人工审查决定 |
| 微调并评估模型 | [训练与评测说明](finetune/README.md) | 正式数据发布、冻结 Prompt、MiniCPM-V-4.5 基座及训练配置 |
| 部署视觉推理服务 | [服务运行手册](docs/INFERENCE_SERVICE_RUNBOOK.md) | 合格的模型与评测记录、权重、正式 Prompt 及部署配置 |
| 查找精确命令和参数 | [统一 CLI 索引](versioning/SCRIPTS.md) | 对应领域的显式输入和完整版本身份 |

项目采用开发机与训练机分工：macOS 用于开发、审查和结果复核；GPU 训练、推理、完整评测及长时间数据处理在训练机执行。具体流程和资产位置见 [项目指南](docs/project-guide.md)。

## 仓库导航

| 路径 | 内容 |
| --- | --- |
| [versioning/](versioning/) | 正式版本身份、数据编排和统一 CLI |
| [pipeline/](pipeline/) | 视频处理、视觉契约、审查工具和推理服务 |
| [finetune/](finetune/) | LoRA 训练、模型合并和严格评测 |
| [scripts/](scripts/) | 环境部署及各阶段操作脚本 |
| [docs/](docs/) | 使用手册、实验结果、设计与决策记录 |
| [tests/](tests/) | 数据、契约、版本管理及评测测试 |

当前能力与限制见 [项目状态](docs/CURRENT_PROJECT_STATUS.md)，开发任务见 [项目 TODO](docs/project-todo.md)。希望了解实现与设计，可继续阅读 [架构说明](ARCHITECTURE.md)和[可读版本控制决策](docs/adr/ADR-0001.md)。`workspace/` 与 `models/` 用于本地资产，不随 Git 分发；历史流程资料保留作追溯，当前操作从以上手册与统一 CLI 进入。
