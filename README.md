# TensileAgent-Finetune

本工作区是 `mVllm_2` 仓库的 **sparse-checkout worktree**（长期主线分支 `feat/tensileagent-finetune`），负责新一代**五类 11 叶字段**（断裂状态、断裂模式、断裂位置、异常情况、断裂现象）的数据标注、ROI、划分、子视频生成/人工审核、离线五类评测及后续训练演进。

`main` 分支（原 `mVllm_2` 工作区）仅作为 `tensile-vlm/v4.1` 历史冻结线保留，不与本工作区混用。

[设计与规则导航](docs/guide.md) · [标签说明](docs/label.md) · [评价设计](docs/design-test.md) · [项目 TODO](docs/TODO.md) · [项目事实](docs/facts.yaml) · [数据目录说明](data/README.md)

## 项目概览

本项目围绕材料拉伸试验视频的新一代五类标签体系展开，覆盖人工标注、ROI 裁剪、数据划分、子视频生成与人工审核、离线五类评价及后续微调链路。具体标注判断与填写规则见[标签说明](docs/label.md)。

### 当前状态

- 本轮真实源视频的人工标注及结果整理已完成，源级材料与使用边界见[设计与规则导航](docs/guide.md)与[数据目录说明](data/README.md)。
- 五类评价口径与离线评测设计持续推进中，详见[整体模型测评设计](docs/design-test.md)与[项目 TODO](docs/TODO.md)；正式阈值、真实模型测评及晋级衔接尚未落地。
- 原 `mVllm_2` 工作区维护的冻结 `v4.1` 四字段契约（原路径 `pipeline/contracts/tensile_vlm_v4_1.json`）及历史模型清单（原路径 `docs/results/model-inventory.md`）均属于历史冻结线，不能与本工作区新五类标签直接混用。

当前任务、依赖和下一步以[项目 TODO](docs/TODO.md)为准，设计与代码事实以[项目事实](docs/facts.yaml)为准。

## 跨仓边界与上下游关系

| 角色 | 仓库 / 工作区 | 职责与协作边界 |
| --- | --- | --- |
| 上游（虚拟数据） | `BlenderTensileVideo` | 提供只读整片虚拟数据集包，按版本导入至 `data/virtual/<version>/`，与真实数据物理隔离；导入校验与使用边界见[数据目录说明](data/README.md)。 |
| 本工作区（数据与微调演进） | `TensileAgent-Finetune`（`feat/tensileagent-finetune`） | 负责新五类 11 叶字段的真实/虚拟数据整理、ROI、划分、子视频生成与人审、离线五类评测及后续微调训练。 |
| 历史冻结线 | `mVllm_2`（`main`） | 保留旧 `tensile-vlm/v4.1` 冻结链路、旧契约与历史结果证据，不作为本工作区的开发主线。 |
| 下游（运行时与前端） | `TensileAgent` | Agent 决策运行时与 Web 工作台；当前仍消费 `mVllm_2` 冻结的 `v4.1` 契约，本工作区的新五类模型尚未形成运行时契约与推理服务交付，待后续阶段衔接。 |

## 文档导航

从[设计与规则导航](docs/guide.md)定位专题，再阅读对应详细文档：

| 文档 | 内容 |
| --- | --- |
| [设计与规则导航](docs/guide.md) | 源级材料入口、专题文档索引与使用边界 |
| [标签说明](docs/label.md) | 本轮五类 11 叶字段的人工标注依据与填写规则 |
| [整体模型测评设计](docs/design-test.md) | 五类离线评价体系、分母口径、失败处理与测试安排 |
| [项目 TODO](docs/TODO.md) | 项目唯一任务台账、当前状态与下一步 |
| [项目事实](docs/facts.yaml) | 设计与代码事实及其证据台账 |
| [训练机生成 + 本机 SSH 审查运行手册](docs/training-machine-review-runbook.md) | 跨机子视频生成、SSH 隧道审查、同步边界与收尾流程 |
| [数据目录说明](data/README.md) | 真实数据与 `data/virtual/<version>/` 虚拟数据的物理隔离、SHA-256 导入校验与 Git 边界 |

> 注：原 `mVllm_2` 工作区的系统架构文档（`ARCHITECTURE.md`）、历史模型清单（`docs/results/model-inventory.md`）、旧 v4.1 契约（`pipeline/contracts/tensile_vlm_v4_1.json`）及旧版本管理脚本索引（`versioning/SCRIPTS.md`）均属于 `mVllm_2` 冻结线，未在本 sparse-checkout 工作区检出；查阅历史信息请回到原 `mVllm_2` 工作区。

## 运行环境与双机分工

本项目采用 **Python 3.11.x**，按平台分工协作：

- **本机（Mac）**：通过 `pyproject.toml` + `uv.lock`（本地 `.venv`）进行开发、轻量检查、ROI 与人工审查 UI，以及同步结果复核。
- **Linux GPU 训练机**：负责模型训练、GPU 推理、完整评测及长时间媒体处理（含子视频生成）；使用训练机前须核对其环境、分支与文件状态，跨机审查流程见[训练机生成 + 本机 SSH 审查运行手册](docs/training-machine-review-runbook.md)。

两机均需在 `PATH` 中具备 `git`、`ffmpeg`、`ffprobe` 与 `uv`。历史 `mVllm_2` 冻结线的环境准备与校验脚本（原 `scripts/` 目录及 `versioning/` 入口）已不在本工作区检出，如需追溯历史部署方式请查阅原 `mVllm_2` 工作区或[设计与规则导航](docs/guide.md)。

## 仓库结构

下表仅列出当前 sparse-checkout 工作区实际检出的主要目录：

| 路径 | 用途 |
| --- | --- |
| [script/](script/) | 当前在用的工程脚本：标注（`annotation/`）、ROI（`roi/`）、数据划分（`data_split/`）、子视频生成（`subvideo_generation/`）、人工审核（`subvideo_review/`）、离线五类评测（`five_label_eval/`）、一致性检查（`checks/`）与集成测试（`integration_tests/`） |
| [data/](data/) | 真实视频链路记录（标注表、ROI、划分、子视频清单、审核记录）与 `virtual/<version>/` 虚拟数据集（视频媒体不入 Git，详见[数据目录说明](data/README.md)） |
| [config/](config/) | 离线评测路径等配置文件（如 `eval_paths.json`） |
| [docs/](docs/) | 专题设计、规则导航、决策记录（`decisions/`）、评测契约（`eval/`）、任务台账与事实库 |
| [tests/](tests/) | 工作区布局守卫与项目级测试 |
| [LlamaFactory/](LlamaFactory/) | 训练框架 Git 子模块（配置见[.gitmodules](.gitmodules)） |

**未在本工作区检出的历史目录**：`pipeline/`、`finetune/`、`versioning/`、`docs/results/` 等属于原 `mVllm_2` 冻结线（`main` 分支），在本 sparse-checkout 工作区中未检出；历史 `scripts/` 目录亦已移除，不应与本工作区的 `script/` 混淆。
