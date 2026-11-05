# 文档目录

本页按用途查找文档。人工标注从[标签说明](label.md)开始；项目进度以 [TODO](TODO.md) 为准。历史设计、结果和研究只反映其版本与日期，不能直接作为新标签的实施或评测结论。

本目录在文档结构或权威入口发生变化时失效，应同步更新；不再需要时删除。

## 当前工作与操作

| 文档 | 用途 |
| --- | --- |
| [断裂标签说明](label.md) | 人工标注的五类标签、含义及填写规则。 |
| [Project TODO](TODO.md) | 项目唯一任务台账；查看标注和评价设计的下一步。 |
| [项目现状与证据](project-status.md) | 项目阶段、机器位置、工程能力和证据边界。 |
| [从原始视频到可用数据](data-workflow.md) | 现有数据处理入口、输入与产物。 |
| [模型训练、评测与服务](model-workflow.md) | 现有训练、评测与服务操作入口。 |
| [模型评测设计](model-evaluation.md) | v4.1 的评价设计；不直接套用新标签。 |
| [design-facts.md](design-facts.md) | 由 YAML 生成的设计事实与证据索引。 |
| [未结事项登记册](pending-blockers.md) | 旧事项清理说明及历史查找方式，不是新的待办清单。 |

## 历史设计与决策

| 文档 | 用途 |
| --- | --- |
| [ADR-0001：采用可读版本控制与单向记录链路](adr/ADR-0001.md) | 采用可读版本控制的决策及边界。 |
| [可读版本控制架构设计](plans/2026-09-01-readable-version-control-design.md) | 可读版本控制体系的已确认设计。 |
| [可读版本控制架构实施台账（refactor/readable-version-control）](plans/2026-09-01-readable-version-control-implementation.md) | 版本体系基础设施的历史实施记录。 |
| [已撤回：评审分词计数对齐方案讨论](plans/2026-10-15-review-tokenizer-alignment-design.md) | 已撤回的评审分词对齐方案讨论。 |
| [测评管线重设计：从形式合法到语义可判](plans/2026-10-18-evaluation-pipeline-redesign.md) | 历史评测管线重设计与诊断背景。 |
| [全链路质疑验证方案（R2 开训闸门）](plans/2026-10-18-full-chain-validation.md) | 历史全链路验证方案，不代表全部已执行。 |
| [断裂标签重建：以可见分离第一帧为锚点重算事件时刻](plans/2026-10-18-label-rebuild.md) | 可见分离锚点及标签重建的历史设计依据。 |
| [模型评测实施计划](plans/model-evaluation-implementation.md) | v4.1 评测接线的实施计划与验收背景。 |
| [Problem](tasks/2026-09-07-readable-version-control-migration/intent.md) | 正式迁移任务的原始目标。 |
| [正式迁移行为规格](tasks/2026-09-07-readable-version-control-migration/spec.md) | 正式迁移的行为规格。 |
| [可读版本控制正式迁移实施计划](tasks/2026-09-07-readable-version-control-migration/plan.md) | 正式迁移的实施计划与证据入口。 |

## 历史结果与核验

| 文档 | 用途 |
| --- | --- |
| [历史结果索引](results/INDEX.md) | 历史结果的分类入口。 |
| [训练数据台账 2026-10-17](results/training-data-ledger-20261017.md) | 训练数据来源、准备工作和历史核验。 |
| [V4.1 模型清单与效果对比](results/model-inventory.md) | v4.1 模型资产及效果对比。 |
| [R1 模型效果档案：v4.1-agent-pipeline-fold0-r1](results/model-r1-effect-profile-20261018.md) | R1 开发侧效果、数据及参数证据。 |
| [模型资产与门禁现场核查（2026-09-14）](results/model-gate-baseline-20260914.md) | 历史模型资产和准入门核查。 |
| [2026-10-13 训练机只读现状核查](results/remote-state-refresh-20261013.md) | 训练机在核查日期的只读快照。 |
| [测评基础能力与开发验证接线实施记录](results/evaluation-development-implementation-20261015.md) | 开发评分和验证接线的实施证据。 |
| [独立评分、性能与准入工程接线记录](results/evaluation-independent-performance-admission-20261015.md) | 独立评分、性能及准入接线证据。 |
| [固定tokenizer来源、独立评审环境与映射材料](results/evaluation-tokenizer-materials-20261015.md) | 评审模型分词来源、环境与映射材料。 |
| [Ollama安装包分词核验与NFC/NFD差异](results/ollama-tokenizer-verification-20261015.md) | Ollama 分词及规范化差异的历史观察。 |
| [基座固定 revision 配置、tokenizer 与代码来源核验](results/minicpm-fixed-source-audit-20261016.md) | 基座固定来源的配置、分词器及代码核验。 |
| [MiniCPM 构造收尾调用核验与取消追查记录](results/minicpm-postinit-origin-purpose-20261016.md) | 基座构造调用的用途核验及取消追查记录。 |
| [Checkpoint 对比](results/diagnostics-checkpoint-comparison-full-run-exact-20260719.md) | 完整运行口径下的 checkpoint 历史比较。 |
| [Checkpoint 对比](results/diagnostics-checkpoint-comparison-production-prompt-20260719.md) | 生产 Prompt 口径下的 checkpoint 历史比较。 |
| [mVllm_2 诊断执行报告](results/diagnostics-data-visual-audit-20260719.md) | 数据及视觉诊断执行记录。 |
| [mVllm_2 诊断流程](results/diagnostics-data-visual-audit-plan-20260717.md) | 数据和视觉诊断的历史流程。 |
| [视觉盲审准备报告](results/diagnostics-visual-audit-preparation-report-20260717.md) | 视觉盲审的准备记录。 |
| [阶段 2 视觉输入盲审报告](results/diagnostics-visual-audit-report-20260719.md) | 视觉输入盲审的结果记录。 |
| [V4.1 Agent pipeline Fold0 R1 deployment](results/v4_1_agent_pipeline_fold0_r1/README.md) | v4.1 Fold0 R1 模型服务历史记录。 |
| [V4.1 Phase 1 effective-view audit](results/v4_1_phase1_effective_view_audit/README.md) | v4.1 第一阶段有效视图审计入口。 |
| [V4.1 有效视图审计历史报告（2026-07-25）](results/v4_1_phase1_effective_view_audit/report.md) | v4.1 第一阶段有效视图审计报告。 |
| [V4.1 Phase 2 development 发布冻结](results/v4_1_phase2_development_release/README.md) | v4.1 第二阶段开发数据发布记录。 |
| [V4.1 阶段 2 隔离审查队列](results/v4_1_phase2_review_queues/README.md) | v4.1 第二阶段隔离审查队列记录。 |
| [V4.1 Stage B intermediate model acceptance](results/v4_1_stage_b_intermediate/README.md) | v4.1 中间模型验收记录。 |
| [V4.1 Stage D sealed-test release](results/v4_1_stage_d_sealed_test_release/README.md) | v4.1 封存测试发布的历史记录。 |
| [2026-09-07 可读版本控制迁移只读调查](results/version-control-migration-20260907.md) | 版本体系迁移前的只读调查。 |
| [迁移入口调用图与保护清单](results/version-control-migration/entrypoint-map.md) | 迁移入口和历史依赖的对应清单。 |
| [可读版本控制迁移交接](results/version-control-migration/handoff.md) | 迁移交接记录。 |
| [迁移证据：训练机只读调研与完整 payload hash 验证](results/version-control-migration/verification.md) | 迁移过程与验收证据。 |
| [当前发布模型独立测试集分布与性能终审报告](reports/2026-07-30-current-release-model-sealed-test-performance-report.md) | 历史发布模型独立测试分布与性能报告。 |

## 模型原理研究

| 文档 | 用途 |
| --- | --- |
| [MiniCPM-V-4.5 基座模型架构与原理综述](research/MiniCPM-V-4.5_架构与原理综述.md) | MiniCPM-V-4.5 架构与原理综合介绍。 |
| [调研主题：MiniCPM-V-4.5 整体架构总览（范围 A）](research/MiniCPM-V-4_5_architecture_research.md) | 模型整体架构专题调研。 |
| [调研主题：范围 C —— MiniCPM-V-4.5 的语言模型 backbone（Qwen3）架构与 MiniCPM 家族自研 LLM 训练原理](research/minicpm_llm_backbone_report.md) | 语言模型 backbone 专题调研。 |
| [调研主题：范围 D — MiniCPM-V-4.5 多模态训练范式与对话格式](research/minicpmv45_范围D_多模态训练范式与对话格式.md) | 多模态训练和对话格式专题调研。 |
| [调研主题：MiniCPM-V 系列（重点是 4.5）与 LoRA/SFT 微调直接相关的工程细节（范围 E）](research/范围E_MiniCPM-V_LoRA_SFT工程细节调研.md) | LoRA 与 SFT 微调工程专题调研。 |
