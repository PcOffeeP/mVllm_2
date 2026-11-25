# 项目设计与规则导航

本文件帮助读者和 Agent 定位当前源级材料与专题文档，不替代专题中的完整设计或规则。项目进度、依赖和下一步以 [TODO](TODO.md) 为准，设计与代码事实见 [facts.yaml](facts.yaml)，重要决定及其状态见[决策总览](decisions/README.md)。

## 本轮源级材料

- 标注表：[data/annotation-table-full.csv](../data/annotation-table-full.csv)。
- 对应原视频副本：[data/videos/](../data/videos/)。
- 人工标注依据：[标签说明](label.md)。

本轮标注及结果整理已完成；上述材料不因此成为已冻结或已发布的数据，也不代表已有独立备份或已接入训练和评价。标注工具默认路径仍是旧位置，详见 TODO 的 LABEL-ANNOTATION 条目。

标注表、来源分组、数据划分和 ROI 的非视频结果记录纳入 Git 管理；视频媒体及运行锁等临时文件继续忽略。提交本地记录不等于已推送或建立独立备份。ROI 清单含当前机器的绝对路径，迁移机器或项目目录后须核对输入和结果身份并重新扫描，不能直接把旧路径当作新机器上的可用位置。

## 已有专题入口

### 标签、ROI 与数据划分

| 专题 | 文档及状态 |
| --- | --- |
| 人工标签 | [标签说明](label.md)：本轮五类 11 叶字段人工标注依据。 |
| 源标注待改清单 | [待修改原视频源标注字段](pending-source-relabels.md)：已确认的源表待改项精简清单（8 源 10 字段，完整台账与待定项见 `docs/TODO.md` §8）。 |
| 标签分布 | [整体标签分布](label-distribution.md)：110 条源视频标注的当前分布快照。 |
| 位置样例校准 | [位置校准样例集](label-calibration/README.md)：`DEC-003` 第 7 条确认的 9 例位置校准参考图与说明。 |
| 视频 ROI 裁剪 | [视频 ROI 裁剪规则](roi-rules.md)：ROI 裁剪、补边、审核与验收规则。 |
| 数据划分 | [划分规则设计](split/data-split-design.md) · [本轮划分结果](split/data-split-result.md) · [DEC-007 选项 A 排除口径](decisions/0007-dev-test-dedup-exclusion.md)：89 开发三折与 21 固定 test 划分规则及当前计数；2026-11-25 按 `DEC-007` 与 `data/splits/dev-exclusions.json` 在训练与开发调参中排除近重复开发源 `video_0006`/`video_0079`（有效开发源 87，每折 `58/29`）。 |

### 子视频生成、审核与跨机运行

| 专题 | 文档及状态 |
| --- | --- |
| 子视频生成 | [子视频生成与审核规则](subvideo-current-logic.md)：当前候选窗口选择、覆盖判据、未夹紧锚点与命名规则（受代码与测试锚定，路径不可改）。 |
| 子视频审核衔接 | [子视频审核与评价衔接](subvideo-review-workflow.md)：审核记录规范、真实/虚拟追踪与评分衔接口径。 |
| 子视频分层与 B2 抽样 | [子视频候选分层与 B2 抽样草稿](subvideo-eval-subset-draft.md)：第 2 批 1,633 条子视频分层覆盖统计与 B2 180 条抽样过程留档（已被正式冻结集 `data/eval-subsets/eval-{dev,test}-v1.json` 取代）。 |
| 跨机审查运行 | [训练机生成 + 本机 SSH 审查运行手册](training-machine-review-runbook.md)：跨机启动、自检、SSH 隧道、单向同步边界与收尾流程。 |

### 模型评价、取证与跨仓契约

| 专题 | 文档及状态 |
| --- | --- |
| 整体测评方案 | [整体模型测评方案](design-test.md)：五类离线评价体系、分母口径、失败处理与测试安排。 |
| 评测输入契约与基座方案 | [评测专题目录](eval/README.md)：含 6 篇输入契约（输出/Prompt/入口/输入记录/[评测子集](eval/eval-subset.md) §6.1 已冻结 `data/eval-subsets/eval-{dev,test}-v1.json`）及 [基座模型测评方案](eval/base-model-eval-plan.md)。 |
| 正式评测结果总入口 | [正式评测结果总入口](eval/runs/README.md)：归档 `eval-dev-v1` 正式评测轻量报告与跨模型对照总表（首批已完成 `MiniCPM-V-4.5` Run A `transformers` 主榜、`vLLM` 对照与 Run B 无画面盲答；预留其余 3 款第一梯队基座对比位）。 |
| 评测抽帧与首轮模型名单 | [DEC-006 评测抽帧口径与首轮模型名单](decisions/0006-eval-frame-sampling-and-model-lineup.md)：2026-11-25 确认 8 帧 `evenly_spaced_inclusive`、短片 `fail_closed`、L3 `resize: null`、MiniCPM 首轮官方风格（登记后续对照优化项）、首轮 3+1 基座名单及 GLM-4.1V 主榜原生格式罚分。 |
| 帧对应抽帧取证 | [帧对应抽帧取证](frame-correspondence-evidence.md)：设计已定、独立 CLI 已落地（PR #21，`script/frame_correspondence/`），前置条件 1 已按 [DEC-006](decisions/0006-eval-frame-sampling-and-model-lineup.md) 拍板。 |
| 跨仓交接契约 | [虚拟数据集交接契约](virtual-dataset-handoff-contract.md)（`BlenderTensileVideo` → 本仓） · [Agent 视觉与交付契约草案](eval/agent-handoff-contract-draft.md)（本仓 → `TensileAgent`，未冻结）。 |

### 检查台账、调研与变更窗口

| 专题 | 文档及状态 |
| --- | --- |
| 检查机制台账 | [检查机制台账](checks.md)：全项目 134 处检查的位置、触发方式与快照状态。 |
| 专项调研 | [测评数据覆盖与虚拟数据建议](research/evaluation-data-requirements.md) · [MiniCPM 视频加载核查](research/minicpm-video-loading.md) · [65 条虚拟视频溯源](research/virtual-video-provenance.md) · [虚拟视频测试集泄漏审查与 110 条真实源视频去重审计](research/source-video-dedup-audit.md) · [8B/9B 开源视频多模态基座选型](research/vlm-8b-9b-model-comparison.md) · [模型输入 8 帧抽帧口径方案](research/model-input-frame-sampling-options.md) · [训练机前置体检与推理适配器规划](research/eval-preflight-and-adapter-plan.md)。 |
| 变更窗口声明 | `docs/changes/`：按 `AGENTS.md` 规范留存，自「已完成」记录之日起保留 7 天，期满直接删除。 |

> 注：原 `mVllm_2` 冻结线的架构说明（`ARCHITECTURE.md`）与历史模型清单（`docs/results/model-inventory.md`）未在本 sparse-checkout 工作区检出；追溯历史信息请回原 `mVllm_2` 工作区。

## 待梳理或补充的专题

以下专题尚未形成适用于本轮的完整正式文档，后续应先梳理并确认再补充入口：

- 数据处理与新数据链路接入。
- 模型训练。
- 实际测评的执行、输入与结果记录，以及新评价设计和现有链路的衔接。

## 训练机历史配置

原项目提交 `2c272ce` 的 `AGENTS.md`「训练机操作」记录：训练机代码目录为 `/home/liuyang/文档/mVllm_2`。这只是历史已记录配置，使用前须核对训练机、分支和文件状态，不代表当前连接或路径已现场验证。

## 使用方式与边界

先按专题找到文档，再阅读其具体规则和适用范围。已确认的设计、代码实际接入和真实运行验证是不同状态，不能相互替代；旧契约和历史结果也不能直接视为本轮新标签的实现或效果。发现文档与代码冲突时，先明确报告冲突，不自行择一执行。

**失效条件：**当本导航被新的项目级设计与规则入口取代且不再使用时作废；届时将仍有效内容并入 `docs/facts.yaml`，或删除本文件。
