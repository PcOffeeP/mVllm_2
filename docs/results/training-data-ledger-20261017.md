# 训练数据台账 2026-10-17

身份 `data-v4.1-r2`（`tensile-vlm/v4.1`，sealed / active / training_allowed=true）：1678 候选、85 个来源视频、三折划分，正式 development release。训练机只读实测 + 本机只读统计，未重跑训练；逐文件 sha256、统计口径与出处在同目录 `training-data-ledger-20261017.json`。

## 数据身份与哈希
| 项 | 值 |
| --- | --- |
| version / protocol / state / status / purpose | data-v4.1-r2 / tensile-vlm/v4.1 / sealed / active / development |
| training_allowed / release.yaml sha256 | true / `3a42da0db7837c3a21d36d923a428b1b009f7b2d7b00bde7cf7ecafab84f0039`（476B） |
| 主清单 metadata/training_candidates.json sha256 | `390447dee4bdec6ead93df7ed2ebf8eac0dd5b41f6f1aecf21320c0201a0eacf`（4.46MB） |

release.yaml 无 content_hash/digest/sha256/checksum 字段，目录内无 index.json / LATEST / manifest，故 **data 身份哈希由 release.yaml 文件内容哈希承担**。
## 候选与来源
| 项 | 值 |
| --- | --- |
| 候选 / 排除 / 来源视频 | 1678（candidate_count = 列表长度 = distinct）/ 17 / 85 |
| media 引用 | video 1678 条（distinct 1678，1 条/候选）；frame 10308 条（distinct 10308，2–8 帧/候选） |

统计口径：候选 ID = datasets 中 `videos[0]` basename 去 `.mp4`；分母 = candidate_count=1678；每折样本数按折文件条数计（dup_ids=0）；排除项含 17 个 excluded 候选与 sealed test 集。
## 三折划分
| 折 | train | validation | val 来源组 | train 来源组 |
| --- | --- | --- | --- | --- |
| fold_0 | 1253 | 425 | 29 | 56 |
| fold_1 | 1014 | 664 | 29 | 56 |
| fold_2 | 1186 | 492 | 22 | 63 |

## 交叉验证

- 每折 train∪val = 1678、train∩val = 0、dup_ids = 0；六折数据集与全量双向差集 = 0（无野 ID、无遗漏）。
- 三折 validation 两两交集 0/0/0，并集 1581 = 425+664+492；全量减并集 = 97 个「仅 train」候选，与任一 validation 交集 0，三折 train 中均存在（缺失 [0,0,0]），排序拼接 sha256 `c9d461b045a9be3806fe787f893e4c31e21956dcdd669cda41a702c6ddcba4ad`。

## 试件分组
本台账 `source_groups`（分组口径、折内组检查与用户原话）与 `source_map.mapping`（1,678 条 candidate→source_video 本体；原分组材料的 candidate→group 表与之逐条相同，故只存一份）：85 组，组内候选 3 / 20.0 / 43（min/median/max）；val 组 29/29/22（去重 80），三折 val 组两两交集 0/0/0；5 组从不进入任何 validation。分组依据为**用户直接确认「每个试样只对应一个视频」**，非独立物理观测。原分组材料 sha256 `781aa0b142e20fc03568fcb8286639bc9670d42e7233b265cd03a808a242bd04`（100,105 B），2026-10-18 并入台账后原文件已移除。

## 质量预算（耗时派生，非已批准预算）
| 项 | 值 |
| --- | --- |
| 基准单步耗时 | 14.9309 s/step（16797.2917 s / 1125 步；run 2a84e8b6，旧 release v4.1.0-ecb5aeb9657c） |
| 同机 6 个完成态 run 区间 | 14.6582 – 14.9882 s/step |
| r2 三折步数 | 470 / 381 / 445，合计 1296 步 |
| r2 三折训练 | 5.3751 h（区间 5.2770 – 5.3957 h） |
| 独立 validation 推理（每折 1 次） | 0.2104 h（0.479 s/样本 × 1581） |
| 三折训练 + 该推理 | 5.4873 – 5.6061 h |
| full（1678 × 3 epoch） | 2.6129 h — **条件值，该定义未确认** |

训练质量预算未冻结（quality_estimate_gpu_hours / quality_cap_gpu_hours 均 null，quality_budget_frozen=false）；`performance_formal_cap_gpu_hours=20` 是**交互性能**预算，不是本项。不可用「单折 4.67 h × 3」：历史 run 每折 3000 样本/1125 步，r2 各折仅 1253/1014/1186 样本。
## 这份台账回答了什么
- r2 的版本身份、12 个文件的 sha256、主清单位置与统计口径；候选/来源/媒体引用规模与三折实际样本数、来源组数。
- 折间隔离是否成立：train/val 不重叠、validation 互不重叠、数据集与全量双向差集为 0。
- 哪些候选从不参与验证（97 个 / 5 个来源组），及结论适用范围须限定在 1581 个 validation 候选。
- 基于实测单步耗时的三折训练与验证推理耗时区间。
## 这份台账没回答什么
- 模型效果、准确率，以及 sealed test 集性能（未读取其语义）。
- 人工审查通过率与覆盖率：phase2 410 条提交中 403 admitted / 7 dropped，其余历史候选来自既有批次。
- 「数据已审查通过」这一结论本身。
- r2 的真实训练耗时（仅旧 release 3k run 的派生外推，且含训练内 eval 开销），以及 5 个从未进入验证的来源组上的泛化表现。

## 限制与声明
逐条限制见 JSON 的 `limitations` 与 `timing_baseline.assumptions`（旧 release 外推、试件分组依据、内部 eval 开销、未重跑训练等）。**本文件不代表数据已审查通过。**

## 2026-10-18 并入原始核验材料

2026-10-16 的五个开发输入核验文件（盘点、运行前核验正文、运行时就绪、试件分组、映射观测）已整体并入本台账 `training-data-ledger-20261017.json`，原文件随后移除；其 sha256、体积与并入去向记在 JSON 的 `merged_source_materials.originals`，原文件名可由本批提交的删除记录（`git show --diff-filter=D --name-only <本批提交> -- docs/results`）追溯。

五类关键事实与新位置：

| 事实类 | 内容摘要 | 台账内位置 |
| --- | --- | --- |
| 映射本体与折分配 | 1,678 条 candidate→source_video；85 个来源的三折 train/validation 分配全表 | JSON `source_map.mapping`、`source_map.source_fold_allocations`（sha256 由 mapping 复算校验） |
| 试件分组 | 85 组、组内候选 3/20.0/43、val 组 29/29/22（去重 80）、组交集 0、用户原话依据 | JSON `source_groups`（candidate→group 表与 `source_map.mapping` 相同，未重复存储） |
| 源码/配置指纹 | 22 份文件的逐文件 sha256 与字节数、生成参数四项 | JSON `source_fingerprints.files`、`source_fingerprints.generation` |
| 契约双 hash 与差异 | 历史 `47e393…` / 当前 `3798f0…`、四处差异路径、canonical 复算与语义边界 | JSON `contract_analysis` |
| 旧 Fold0 训练 YAML | 1,535 B 恢复全文、sha256 `036c9c69…`、当前 active `d3fd4000…`、两份 metadata 探测 | JSON `legacy_yaml_recovery` |

其余一并并入的事实：开发输入盘点的基线 HEAD、只读采集调用与成功采集脚本全文、4 次尝试历史、release 授权观测、Prompt 与契约身份、旧 Fold0 绑定、6 份非 release 文件证据、三条 limits（JSON `development_inputs`）；三入口路径对齐、变体未选、性能与时间上限、评审调用边界、样本量算术（JSON `runtime_readiness`）；运行前核验正文的 12 条本轮约束与收尾核查结论（JSON `development_inputs.round_constraints`、`development_inputs.closeout_review`）。

体积：并入前 14,118 B，并入后 211,453 B，未超 500 KB，故未拆分，未产生 `.sources.json`。逐条覆盖核对（102 条事实，0 失败）由仓库外脚本 `~/pi-workspace/mVllm_2-audit/verify_ledger_coverage.py` 在删除前完成，含 1,678 条映射逐条相等、22 份指纹逐项相等、恢复 YAML 字符串相等与 sha256/size 复算、四处差异列表相等、计数相等。
