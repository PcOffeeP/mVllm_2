# mVllm_2

本项目研究利用多模态模型理解材料拉伸试验视频中的断裂信息，并维护数据处理、模型训练、评测和服务的工程链路。

[设计与规则导航](docs/guide.md) · [标签说明](docs/label.md) · [评价设计](docs/design-test.md) · [项目进度](docs/TODO.md) · [架构](ARCHITECTURE.md)

## 项目概览

项目围绕拉伸视频的人工标注、数据处理、模型训练及评价展开。本轮人工标注基准覆盖**断裂状态、断裂模式、断裂位置、异常情况和断裂现象**五类信息；具体判断和填写规则见[标签说明](docs/label.md)。

### 当前状态

- 本轮人工标注及结果整理已完成，源级材料和使用边界见[设计与规则导航](docs/guide.md)。本机材料未发布为训练或评价数据，也不构成独立备份。
- [整体模型测评设计](docs/design-test.md)已有初稿，仍需进一步确认；新评价接口、正式阈值及晋级衔接尚未落地，不代表已完成本轮真实模型测评。
- 现有旧链路使用冻结的 [v4.1 四字段契约](pipeline/contracts/tensile_vlm_v4_1.json)；本轮新标签尚未接入数据或模型链路，不能与旧契约直接混用。

当前任务、依赖和下一步以[项目 TODO](docs/TODO.md)为准。历史结果及其限制见[模型清单](docs/results/model-inventory.md)。

## 文档导航

从[设计与规则导航](docs/guide.md)定位专题，再阅读对应的详细文档。

| 文档 | 内容 |
| --- | --- |
| [标签说明](docs/label.md) | 本轮人工标注依据和填写规则 |
| [整体模型测评设计](docs/design-test.md) | 待确认的评价设计初稿 |
| [项目 TODO](docs/TODO.md) | 项目唯一任务台账、当前状态和下一步 |
| [项目事实](docs/facts.yaml) | 设计与代码事实及其证据 |
| [架构说明](ARCHITECTURE.md) | 系统、模块及新旧入口边界 |
| [模型清单](docs/results/model-inventory.md) | 历史模型结果与证据限制 |

## 快速开始

下面的步骤用于准备或核验开发环境，以及查看已有命令入口；环境检查通过不等于新标签已接入或模型效果通过验收。

### 环境要求

> **状态说明（2026-11-14）：** 本节的环境准备与核验命令所引用的历史 `scripts/` 目录已按用户要求删除，下面的命令与脚本索引均为历史记录，**当前检出中不可执行**。当前真正在用的代码在 `script/`（子视频生成、视频审查等）与 `docs/`。

本项目支持 **Python 3.11.x**。当前 Mac 用于开发、ROI/审查 UI 和轻量结果检查，通过 `uv` 调用已部署的 Mac 解释器；实际数据处理、训练、评测和模型服务在 Linux GPU 训练机上，直接使用对应的 **Conda 环境 Python**。两平台的依赖保持分开：

| 平台 | 依赖来源与用途 |
| --- | --- |
| Mac | `pyproject.toml` + `uv.lock`；代码检查、ROI/审查 UI 和同步结果复核，无需初始化 LlamaFactory 子模块 |
| Linux GPU 训练机 | `requirements-linux-gpu.lock` + 固定 LlamaFactory 子模块；真实数据处理、训练、评测和服务 |

两机都需要 Git、ffmpeg、ffprobe 和 uv 在 PATH 中可用。训练机的运行入口仍是 Conda Python；环境检查器内部使用 `uv pip check`，所以 uv 也是检查工具前置。训练机另需 Linux x86_64、NVIDIA 驱动及可用 `nvidia-smi`。

<details>
<summary>Mac：首次部署与日常运行</summary>

### Mac：首次部署与日常运行

先准备一个已经存在的 Python 3.11.x 解释器，以其绝对路径设置 `BOOTSTRAP_PYTHON`。`MAC_ENV` 是准备新建且尚不存在的环境绝对目录，不得经过符号链接或包含 `..`。本节命令所引用的脚本原位于已按用户要求删除的历史 `scripts/` 目录，仅作历史记录保留，当前检出中不可执行。从仓库根运行：

```bash
# 历史命令（当前不可执行）：脚本原位于已删除的 scripts/ 目录
BOOTSTRAP_PYTHON=/absolute/existing/python3.11
MAC_ENV=/absolute/new/mac-environment
uv --no-config run --no-project --no-python-downloads --python "$BOOTSTRAP_PYTHON" \
  python scripts/source_prepare_environment.py --profile mac \
  --env "$MAC_ENV" --python "$BOOTSTRAP_PYTHON"
```

首次调用跳过项目环境发现，用已有解释器启动部署脚本；脚本再按 Mac 锁创建新环境。退出码为 0 且输出 `Deployment verified` 才表示环境检查通过。失败时保留部分环境，调查后重试选择新的目标目录。

日常开发时，`MAC_PYTHON` 指向上述成功部署的 Mac 环境解释器。已部署环境可以直接设置其实际路径，无需重复创建。本节命令所引用的脚本原位于已按用户要求删除的历史 `scripts/` 目录，仅作历史记录保留，当前检出中不可执行。

```bash
# 历史命令（当前不可执行）：脚本原位于已删除的 scripts/ 目录
MAC_PYTHON="$MAC_ENV/bin/python"
uv --no-config run --no-project --no-python-downloads --python "$MAC_PYTHON" \
  python -m versioning --help
uv --no-config run --no-project --no-python-downloads --python "$MAC_PYTHON" \
  python scripts/source_validate_environment.py --profile mac
```

这里 `uv run` 复用显式选定的解释器，跳过项目依赖自动同步并禁止下载 Python；它不替代首次部署。不要用未指定解释器的默认 `uv run` 去选择另一套环境。

</details>

<details>
<summary>训练机：核验已有 Conda 环境</summary>

### 训练机：核验已有 Conda 环境

先确认具备[子模块](.gitmodules)对应 Gitee SSH 仓库的访问资格，初始化固定版本并保持干净：

```bash
git submodule update --init --recursive
```

使用已准备好、按 Linux GPU 锁和当前 checkout 核验的 Conda Python 3.11.x 环境。可以先激活该环境，也可以全程使用其解释器绝对路径；以下写法不依赖 shell 激活状态。本节命令所引用的脚本原位于已按用户要求删除的历史 `scripts/` 目录，仅作历史记录保留，当前检出中不可执行。

```bash
# 历史命令（当前不可执行）：脚本原位于已删除的 scripts/ 目录
PYTHON=/absolute/verified/conda-environment/bin/python
"$PYTHON" scripts/source_validate_environment.py --profile linux-gpu
"$PYTHON" -m versioning --help
```

非交互 SSH 会话（`ssh <host> '...'`）不加载 `.bashrc` 和 `.profile`，Conda 在交互式登录时设置的 `PATH` 不会生效。环境检查器会以隔离模式重新执行自身，并剥离 `VIRTUAL_ENV` 以及全部 `PYTHON*`、`UV_*`、`PIP_*` 环境变量；`uv`、`ffmpeg`、`ffprobe` 都经 `shutil.which` 从 `PATH` 查找，缺失者记为 `missing prerequisite <tool>` 并返回非零，`uv` 缺失时即报 `missing prerequisite uv`。`uv` 存在时，检查器还执行 `uv --no-config pip check --python <解释器>`。因此这类会话要先让该环境的 `bin` 进入 `PATH`，例如 `PATH=/absolute/verified/conda-environment/bin:$PATH "$PYTHON" scripts/source_validate_environment.py --profile linux-gpu`。`conda run -n <env> ...` 与登录 shell（`ssh <host> 'bash -lc "..."'`）同样满足这一条件。

检查覆盖锁定依赖、公共入口、媒体工具、CUDA 和训练模块来源，不下载或加载模型，也不训练或推理。Linux editable 依赖绑定代码工作区，后续使用时须保留或重新核定该来源。只有检查通过的环境才用于后续实际处理；历史环境名字不能代替核验。

如果没有合格的 Conda 环境，先准备并核验，不能直接开始真实任务。现有 `source_prepare_environment.py --profile linux-gpu` 创建的是新的 venv，既不创建 Conda 环境，也不修补已有 Conda 环境；其 `--env` 不接受已存在目录。部署接口与依赖维护规则见脚本索引 `scripts/SCRIPTS.md`（该文件已随历史 `scripts/` 目录按用户要求删除，当前检出中不存在）。

</details>

### 准备实际输入

正式版本只有 data、prompt、train、model、eval 五类，名称为 `<kind>-v<协议>-r<N>`，例如 `data-v4.1-r2`。示例身份不表示你本地已有资产；版本和输入必须显式提供，不自动猜测“最新”。

后续数据接入、训练和评价流程以新标签为基础另行设计。GPU 训练、推理、完整评测及长时间媒体处理在训练机执行。环境安装通过与实际模型效果达标分别验收。

## 仓库结构

| 路径 | 用途 |
| --- | --- |
| [versioning/](versioning) | 新体系入口及版本管理；命令见[脚本接口索引](versioning/SCRIPTS.md) |
| [pipeline/](pipeline) | 数据处理与人工审查相关代码 |
| [finetune/](finetune) | 训练与评测相关代码 |
| `scripts/`（已删除） | 历史环境等项目脚本目录，已按用户要求删除；原脚本索引 `scripts/SCRIPTS.md` 随之删除，当前检出中不存在 |
| [docs/](docs) | 专题文档、任务台账与历史结果 |
| [tests/](tests) | 项目测试 |

各入口的新旧体系适用边界见[架构说明](ARCHITECTURE.md)。`docs/results/`、`docs/reports/` 保存历史结果，应结合版本和日期理解，不能直接当作本轮效果证据。
