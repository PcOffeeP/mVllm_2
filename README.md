# mVllm_2

**把材料拉伸试验视频转化为可审查的视觉样本与结构化判断。** 本项目基于 MiniCPM-V-4.5，围绕试样是否断裂、断裂机制、断裂位置及特殊情况，提供数据准备、人工审查、LoRA 微调、严格评测和视觉服务流程。

项目当前工程能力、历史效果及尚未完成的验收见[项目现状](docs/project-status.md)。

## 项目介绍

### 判断一个时间窗口里的画面

模型观察一个有限视频窗口中的采样帧，每个窗口最多 8 帧。它依据窗口内实际可见的证据回答问题，不用片段外事件补全标签，也不直接把整段长视频当作一个训练样本。

当前使用 `tensile-vlm/v4.1` 四字段契约：

| 字段 | 含义 |
| --- | --- |
| `clip_state` | 未断裂、临界未断裂、发生断裂、已断裂或无法判断 |
| `fracture_mechanism` | 可见证据支持的断裂机制，不能判断或不适用时为 `null` |
| `fracture_site` | 标距内、标距外非夹具根部、夹具根部，或 `null` |
| `special_case` | 未夹紧、视频异常，或 `null` |

格式示例，不代表实际推理结果：

```json
{
  "clip_state": "发生断裂",
  "fracture_mechanism": "韧性断裂",
  "fracture_site": "inside_gauge",
  "special_case": null
}
```

“发生断裂”表示窗口内可见连续到分离的变化；“已断裂”表示可靠画面从窗口开始就已分离。普通“未断裂”窗口的其余三个字段均为 `null`。完整枚举与约束见[业务契约](pipeline/contracts/tensile_vlm_v4_1.json)。

### 从视频到模型

先保留视频来源和源视频级划分，以 ROI（需要观察的试样区域）裁剪或保留画面，生成候选窗口及采样帧。人工审查结果与媒体一起冻结成数据发布，再用 LoRA 更新少量附加参数，使基座适配拉伸试验画面。

开发阶段沿用三折 train/validation 划分，分别训练和验证以比较方案；最终 full 模型使用合格开发数据全集训练，另用独立 test 验收。上层自然语言任务编排、视频搜索和展示由独立的 TensileAgent 项目负责，本仓库提供视觉判断与相关数据、模型流程。

### 初步成果

数据处理、审查交接、版本管理及训练/评测/服务入口已有工程实现与验收记录。历史 Fold0 中间模型曾完成权重合并、真实视频服务和 Agent 调用；其 425 条开发侧 validation 的严格输出合法率为 **99.53%（423/425）**，四字段联合正确率为 **41.18%**；合法率取自 [stage-b 中间模型验收摘要](docs/results/v4_1_stage_b_intermediate/acceptance_summary.json) 的 `artifact_gate.strict_valid_rate: 0.995294` 与 `artifact_gate.evaluation_sample_count: 425`。该组数字属旧 strict v4.1 协议、实验身份为 Fold0 中间模型（发布身份 `v4.1-agent-pipeline-fold0-r1`，来源实验 `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3`，seed3407、fold0）、口径为开发侧 validation，与后续 concise 三折记录（实验 `v4.1-prompt-concise-cv-v1-seed3411`，1,581 条，合法率 79.63%、联合正确率 32.07%）不是同一次评测，两者不可混读。这是单折开发结果，尚未证明最终独立 test 通过或生产可用。

当前重点仍是提升任务效果并完成真实模型验收。代码不附带原始视频、基座、adapter 或完整实验目录，也没有可据现有证据提供的一键最终模型演示。历史效果、资产缺口和当前工程边界统一见[项目现状](docs/project-status.md)。

## 快速开始

### 1. 不安装也能了解项目

先阅读上面的输出示例，然后按目标选一份说明：

| 目标 | 阅读入口 |
| --- | --- |
| 把自己的试验视频整理成可训练数据 | [数据处理](docs/data-workflow.md) |
| 准备实验、评测模型并部署服务 | [模型流程](docs/model-workflow.md) |
| 了解已确认的测评指标、通过标准和执行框架 | [模型测评方案](docs/model-evaluation.md) |
| 了解现有成果、未完成项和证据日期 | [项目现状](docs/project-status.md) |

### 2. 按机器准备 Python 3.11.x 环境

本项目支持 **Python 3.11.x**。当前 Mac 用于开发、ROI/审查 UI 和轻量结果检查，通过 `uv` 调用已部署的 Mac 解释器；实际数据处理、训练、评测和模型服务在 Linux GPU 训练机上，直接使用对应的 **Conda 环境 Python**。两平台的依赖保持分开：

| 平台 | 依赖来源与用途 |
| --- | --- |
| Mac | `pyproject.toml` + `uv.lock`；代码检查、ROI/审查 UI 和同步结果复核，无需初始化 LlamaFactory 子模块 |
| Linux GPU 训练机 | `requirements-linux-gpu.lock` + 固定 LlamaFactory 子模块；真实数据处理、训练、评测和服务 |

两机都需要 Git、ffmpeg、ffprobe 和 uv 在 PATH 中可用。训练机的运行入口仍是 Conda Python；环境检查器内部使用 `uv pip check`，所以 uv 也是检查工具前置。训练机另需 Linux x86_64、NVIDIA 驱动及可用 `nvidia-smi`。

#### Mac：首次部署与日常运行

先准备一个已经存在的 Python 3.11.x 解释器，以其绝对路径设置 `BOOTSTRAP_PYTHON`。`MAC_ENV` 是准备新建且尚不存在的环境绝对目录，不得经过符号链接或包含 `..`。从仓库根运行：

```bash
BOOTSTRAP_PYTHON=/absolute/existing/python3.11
MAC_ENV=/absolute/new/mac-environment
uv --no-config run --no-project --no-python-downloads --python "$BOOTSTRAP_PYTHON" \
  python scripts/source_prepare_environment.py --profile mac \
  --env "$MAC_ENV" --python "$BOOTSTRAP_PYTHON"
```

首次调用跳过项目环境发现，用已有解释器启动部署脚本；脚本再按 Mac 锁创建新环境。退出码为 0 且输出 `Deployment verified` 才表示环境检查通过。失败时保留部分环境，调查后重试选择新的目标目录。

日常开发时，`MAC_PYTHON` 指向上述成功部署的 Mac 环境解释器。已部署环境可以直接设置其实际路径，无需重复创建：

```bash
MAC_PYTHON="$MAC_ENV/bin/python"
uv --no-config run --no-project --no-python-downloads --python "$MAC_PYTHON" \
  python -m versioning --help
uv --no-config run --no-project --no-python-downloads --python "$MAC_PYTHON" \
  python scripts/source_validate_environment.py --profile mac
```

这里 `uv run` 复用显式选定的解释器，跳过项目依赖自动同步并禁止下载 Python；它不替代首次部署。不要用未指定解释器的默认 `uv run` 去选择另一套环境。

#### 训练机：核验已有 Conda 环境

先确认具备[子模块](.gitmodules)对应 Gitee SSH 仓库的访问资格，初始化固定版本并保持干净：

```bash
git submodule update --init --recursive
```

使用已准备好、按 Linux GPU 锁和当前 checkout 核验的 Conda Python 3.11.x 环境。可以先激活该环境，也可以全程使用其解释器绝对路径；以下写法不依赖 shell 激活状态：

```bash
PYTHON=/absolute/verified/conda-environment/bin/python
"$PYTHON" scripts/source_validate_environment.py --profile linux-gpu
"$PYTHON" -m versioning --help
```

检查覆盖锁定依赖、公共入口、媒体工具、CUDA 和训练模块来源，不下载或加载模型，也不训练或推理。Linux editable 依赖绑定代码工作区，后续使用时须保留或重新核定该来源。只有检查通过的环境才用于后续实际处理；历史环境名字不能代替核验。

如果没有合格的 Conda 环境，先准备并核验，不能直接开始真实任务。现有 `source_prepare_environment.py --profile linux-gpu` 创建的是新的 venv，既不创建 Conda 环境，也不修补已有 Conda 环境；其 `--env` 不接受已存在目录。部署接口与依赖维护规则见[脚本索引](scripts/SCRIPTS.md)。

### 3. 准备实际输入

正式版本只有 data、prompt、train、model、eval 五类，名称为 `<kind>-v<协议>-r<N>`，例如 `data-v4.1-r2`。示例身份不表示你本地已有资产；版本和输入必须显式提供，不自动猜测“最新”。

接下来按[数据处理](docs/data-workflow.md)准备视频、注释、split 和人工决定；按[模型流程](docs/model-workflow.md)准备基座、正式数据、Prompt 和配置。GPU 训练、推理、完整评测及长时间媒体处理在训练机执行。环境安装通过与实际模型效果达标分别验收。

## 文档与代码导航

首次使用从四份主说明进入：本页负责介绍与初次安装，数据说明负责视频到发布，模型说明负责训练到服务，现状说明负责成果及限制。[模型测评方案](docs/model-evaluation.md)补充已确认的质量和性能标准；[实施计划](docs/plans/model-evaluation-implementation.md)列出现有功能差距，方案确认不表示代码已实现或模型已通过。

实现入口为 [versioning](versioning)、[pipeline](pipeline)、[finetune](finetune) 和[脚本接口索引](versioning/SCRIPTS.md)。设计决定与历史验证作为证据保留，不需要首次访问者先读完。

当前任务与执行顺序以[项目台账](docs/project-todo.md)为准，设计边界见[架构说明](ARCHITECTURE.md)。目录整理与核查记录见[文档整合记录](docs/results/documentation-consolidation-20261012.md)。
