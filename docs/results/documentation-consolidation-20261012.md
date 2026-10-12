# 文档整理与正式整合记录

## 正式文档入口

2026-10-12用户已认可四份文档分工，并授权正式替换根README、清理被覆盖旧说明，同时保留唯一任务台账、设计决策与原始验证证据。本轮执行平台为Mac/Codex，代码起点 `f8af0bba`；未SSH、安装环境、实际数据处理、训练、推理或评测。

现行入口只有根[README](../../README.md)与三份流程/现状正文：[数据处理](../data-workflow.md)、[模型流程](../model-workflow.md)、[项目现状](../project-status.md)。[项目TODO](../project-todo.md)仍是唯一任务台账；代码附近SCRIPTS索引负责完整参数，历史报告不作为当前操作手册。

| 整合内容 | 处理结果 |
| --- | --- |
| 候选README及三份正文 | 正式发布到根README和docs一级，删除候选目录，校正所有相对链接 |
| CURRENT_PROJECT_STATUS、DATA_PROCESSING_RUNBOOK、INFERENCE_SERVICE_RUNBOOK、V4_1_DATA_RELEASES、WORKSPACE_METADATA_GUIDE、project-guide、finetune/README | 删除七份已覆盖的重复说明，历史版本由Git追溯，不留平行提示页 |
| MODEL_GATE_BASELINE | 保留完整现场事实，归档到[2026-09-14核查档案](model-gate-baseline-20260914.md) |
| MODEL_INVENTORY | 保留配置/指标及第8节清理验收，归档到[历史模型清单](model-inventory.md) |
| V4_1_PHASE1_EFFECTIVE_VIEW_AUDIT | 保留审计方法/来源/结果，归档到[历史审计报告](v4_1_phase1_effective_view_audit/report.md) |
| 任务台账、设计/ADR、迁移Intent/Spec/Plan、研究资料与results原始产物 | 保留；只修正必要导航，确认规则、身份、数据和验证事实不重写 |
| AGENTS、架构、接口索引、旧CLI停用提示 | 更新入口位置；旧CLI仍停用，业务算法和授权规则不变 |

## 正式整合的检查与审查

独立reviewer最终结论通过，无可执行问题。冻结整合版本覆盖50份Markdown、289个本地链接及锚点，0错误；四份正式正文25个shell代码块经bash -n全部通过。原30任务标识保留，31标识唯一；65份原始非Markdown结果文件逐字节一致，ADR/迁移Intent-Spec-Plan/研究资料及AGENTS和权威设计决策日志保持原文。归档模型清单和审计报告的表格、列表事实与清理标准完整；十个Python文件严格仅替换停用提示中的文档路径，AST解析通过。`git diff --cached --check`通过。验收回填后再次检查链接及diff，不修改操作正文。本轮没有复跑下文历史测试，不将前序34项ROI验证记成本次运行。整理提交由 `git log -- README.md docs/project-todo.md` 追溯。

## 历史阶段记录

下文保存候选撰写及ROI修复批次的决定、检查和限制；其中“待审阅”“未替换”是当时状态，正式采用的授权与完成结果以上文为准。

## 首次候选文档交付范围

本目录是2026-10-12按用户要求新建的候选手册。用户要求先在新文件夹查看结果，认可后再决定旧文档替换；因此首次候选交付只新增本目录，原README、docs正文、任务台账、代码和产物不改不删。

四份面向使用者的文档按职责分开：

| 文档 | 负责内容 | 不重复的内容 |
| --- | --- | --- |
| [README](../../README.md) | 项目概念、四字段、初步成果、环境初装与阅读入口 | 实验施工过程、完整接口schema |
| [数据处理](../data-workflow.md) | 原始输入、ROI、候选与审查、train/test发布、DVC和数据引用 | 模型训练与正式评分的完整步骤 |
| [模型流程](../model-workflow.md) | Prompt/训练冻结、评测、模型登记晋级、服务及备份 | 初次安装与重复数据制作说明 |
| [项目现状](../project-status.md) | 带日期的能力、成果、资产/资格缺口和证据来源 | 第二套项目任务排序或授权 |

本文件只记录整理和验收，不是另一份项目TODO。现有 `docs/project-todo.md` 仍是唯一台账；候选整合并未切换项目权威入口或批准删除。

## 原内容去向

盘点基线为 `3827363a`，原docs共105个文件：22份非results正文、83份results材料。没有读取受限test报告的逐样本语义、真值或预测。

| 原材料 | 新正文承接位置 | 后续处理建议（本轮未执行） |
| --- | --- | --- |
| 根README | 新README | 验收后替换根入口，重新计算其相对链接；不能直接移动后留下失效链接 |
| DATA_PROCESSING_RUNBOOK、V4_1_DATA_RELEASES、WORKSPACE_METADATA_GUIDE | 数据处理；发布映射和历史统计放项目现状 | 收敛使用说明，完整历史由Git和结果文件追溯 |
| project-guide | 新README、数据处理、模型流程、项目现状的双机位置 | 业务链路和双机信息合并，避免平行流程导航 |
| CURRENT_PROJECT_STATUS、MODEL_GATE_BASELINE | 项目现状 | 旧现场记录与结果证据仍按原日期留存，不抹去来源/未知项 |
| INFERENCE_SERVICE_RUNBOOK、finetune/README | 模型流程 | 集中模型生命周期说明；finetune可只保留代码模块入口索引 |
| V4_1_PHASE1_EFFECTIVE_VIEW_AUDIT | 项目现状引用对应results | 审计事实与结果保留，操作概览可由新数据说明承接 |
| MODEL_INVENTORY | 项目现状引用历史证据与归档任务 | 保留历史模型/清理核查记录，不将目录存在性写成归档通过 |
| project-todo | 不复制，项目现状链接原台账 | 仍保留唯一任务台账；是否调整位置需在正式整合时统一导航 |
| adr/ADR-0001、plans设计/实施、tasks迁移Intent/Spec/Plan | 项目现状与模型流程引用确认规则 | 保留独立决策和确认链；不让已执行计划成为当前操作入口 |
| reports历史测试报告 | 不摘抄受限测试细节 | 保留独立证据，按原测试政策限制消费 |
| research五份材料 | 不改写为本项目成果 | 保留独立研究参考，不作为本项目已验证能力 |
| results全部材料 | 链接到必要具体证据 | 原始配置、指标、清单、映射及验收事实保留，避免因概览清理一并丢失 |
| versioning/各SCRIPTS.md、部署索引 | 需要精确schema时从新正文引用 | 保留靠近代码的接口索引，与概览分工，不复制整份参数规范 |

“旧文档替换”不是清空整个docs。说明正文、唯一台账、确认设计和结果证据承担不同职责；最终删除/移动对象应依据本表逐项核定。新正文不依赖拟替换的旧一级使用手册，但保留代码接口与证据链接。

## 验收要求

- 新读者从README能理解用途、输出和初步成果，能选择环境与下一份说明。
- 数据与模型操作的入口、前置输入、产生的文件及下游消费可追溯，不能出现无来源的参数。
- 现行完整身份、输入冻结、人工审查、test隔离/一次性授权和模型准入与代码一致。
- 已确认工程交付、历史模型效果和未验证真实成功路径分开；9月现场记录不冒充10月刷新。
- 不提供旧停用CLI操作、不虚构公开许可/下载/演示，不扩大真实运行授权。
- 原文件保持不变；本目录链接和代码路径有效；不同Agent对权威操作说明独立核查。

## 首次候选交付的检查与审查结果

已完成四份正文与本整理说明。独立reviewer首轮对照当前CLI、数据/训练/Registry/服务/备份实现检查全链路，发现两项P2：

1. Mac ROI决定复制到训练机时，metadata必须使用两机一致的项目内相对媒体布局；绝对Mac路径不满足训练机video pin验签。修正文档要求在人工决定前准备便携metadata，不手改冻结决定。
2. 当前训练执行证据只覆盖adapter，参数层接受merged不代表现有正式链已有合并与登记证据通路。修正文档将真实merged/production_bundle的完整实现与证据作为缺口，不把另备权重写成现成可晋级路径。

两项均为候选文档准确性修正，没有实现新功能、放宽门禁或改变既有工程结项。最终独立静态增量复核通过，两项P2均关闭，无新增或剩余可执行问题。主Agent及reviewer复查最终新目录77个本地链接与锚点，0问题；JSON格式示例解析通过，`git diff --cached --check`通过；`git diff --exit-code 3827363a -- . ':!docs/project-handbook'`为0，原文件保持不变。本轮不安装环境、不启动应用或pytest、不SSH、不训练、推理或评测；文档命令的准确性依据当前代码参数、调用链和已有证据核对，不代表真实环境已经执行。

在首次候选交付时，用户尚未审阅，静态核查通过也不代表当时获得旧文档删除批准。当前项目任务和下一轮训练机只读刷新仍按原台账执行。


## 续办：ROI入口与两平台运行约定

用户随后明确授权修复ROI脚本导入、调整新文档命令并统一Python 3.11声明，且澄清Mac开发使用uv、训练机仍使用对应Conda环境的Python。代码起点为 `389c797e`，执行平台Mac/Codex，修复提交由 `git log -- pipeline/scripts/roi_annotation_app.py` 追溯。

本批在ROI脚本导入业务模块之前加入仓库根路径，与现有审查UI一致；新增入口测试从仓库外且清除PYTHONPATH运行，覆盖直接文件入口和Streamlit控制台路径设置。测试只执行参数help，不启动界面、服务或读取视频。Mac的首次部署/日常检查及两个UI示例改用显式解释器的uv no-project命令；训练机数据、模型及服务示例仍直接使用已核验的Conda Python。Linux部署脚本的现有新venv机制未改，不宣称它会创建或修补Conda。

pyproject支持范围收紧为 `>=3.11,<3.12`，uv重新解析锁后规范化为 `==3.11.*`，与.python-version及部署/doctor的3.11检查一致。原3.11包版本保留，仅移除numpy2.5.0/scipy1.18.1的高Python版本分支，没有新增包版本。Linux GPU锁、部署脚本和旧文档未修改，也未安装/同步环境。首次离线锁解析因psutil缓存元数据不足失败，随后只联网补充解析元数据并正常生成179包锁；后续离线lock --check通过。

实际检查：现有.venv Python3.11.14运行 `python -B -m pytest -p no:cacheprovider tests/test_roi_entrypoint.py tests/test_roi_annotation_app.py -q`，34 passed、exit0（新增2项、现有32项）；两种未修复入口敏感性反例都捕获ModuleNotFoundError。历史pytest临时目录清理产生297条warning，不影响结果，未清理它们。主Agent通过显式Mac uv解释器直接运行ROI文件 --help，exit0。文档25个shell block经bash -n检查通过。独立reviewer结论通过，无剩余可执行问题：另独立运行新增2项测试通过，从仓库根/脚本目录/仓库外分别验证直接文件与Streamlit路径，共6次help exit0，基线两入口反例仍失败；显式uv解释器选择与离线lock检查通过。锁结构核对确认未删除兼容3.11的轮子、未改变保留包版本/来源/sdist哈希。最终候选目录79个本地链接及锚点0问题，diff检查通过。独立核查没有借用作者34项组合冒充复跑，也没有验证训练机Conda现场。

本批没有实际数据处理、训练、推理、评测、UI/server启动或SSH。训练机Conda环境状态没有刷新，本文只说明运行约定及验收要求，不证明现场环境已合格。旧文档仍保留，当批候选手册仍待用户审阅，未推送/合并或切换正式入口。
