# `docs/results/` 文件索引（141 个文件）

## A. 头部声明

- 覆盖范围：`docs/results/` 全部 **141** 个文件（顶层散落 57 个，其余分布在 14 个一级子目录；子目录与文件数照抄第 4.2 节）。
- 数据来源：2026-10-18 全项目审计清单第 4.5 节主表（141 行）与第 4.6 节 C 类清单，文件路径 `/Users/pcoffeep/pi-workspace/mVllm_2-audit/project-inventory-audit-20261018.md`（仓库外，本机另存，不入 Git）。
- 审计采集基线 `36016711`；本索引编写基线 `21229565`（分支 `feat/evaluation-development`）。
- 本文件只做索引与状态标注：**判据、体积、档位、mtime、引用数全部照抄审计清单**，不重新统计、不新增比率与汇总数字、不判定删除。
- 本文件 `INDEX.md` 自身不计入 141：审计集为 141 个文件，目录现为 142 个文件（含本索引）。
- 全部路径使用行内代码书写，未使用 Markdown 链接，故不存在失效链接。

## B. 分级汇总（照抄审计第 4.1 节）

| 分级 | 判据 | 文件数 | 合计体积 |
|---|---|---|---|
| A | 被 `*.py`、`README.md`、`AGENTS.md` 或 `docs/*.md` 正文引用 | 44 | 8,364,288 B |
| B | 仅被 `docs/results/**` 其它文件或 `docs/project-todo.md` 引用 | 70 | 4,314,200 B |
| C | 零引用 | 27 | 170,912 B |
| 合计 | A+B+C | 141 | 12,849,400 B |

自检：44 + 70 + 27 = 141，与文件总数相等。总量换算：12,849,400 B = 12.25 MiB（审计报告写作「12.25 MB」）。

C 类构成（第 4.6 节）：真零引用 5 个 / 110,718 B + NOISY 降级 22 个 / 60,194 B = 170,912 B。

## C. 主表：141 行 × 9 字段

分组顺序照抄第 4.2 节表（14 个一级子目录在前，`（顶层散落文件）` 在最后），组内按体积降序；每组前置小标题并重复表头，组内文件数照抄第 4.2 节。

`档位` 的 A/B/C 判据见 B 节；`建议` 按档位给出，C 类按第 4.6 节区分真零引用与 NOISY 降级。

### `evaluation-tokenizer-compatibility-materials-20261016/`（4 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/evaluation-tokenizer-compatibility-materials-20261016/qwen3.5-9b-audit.json` | 307380 B（300.2 KB） | B | 受审分词等价材料（JSON 顶层键：golden_cases） | 2026-10-16 09:46 | 无训练实验；tokenizer 材料批次 2026-10-16 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-materials-20261016/ornith-1.5-9b-audit.json` | 307349 B（300.1 KB） | B | 受审分词等价材料（JSON 顶层键：golden_cases） | 2026-10-16 09:46 | 无训练实验；tokenizer 材料批次 2026-10-16 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-materials-20261016/offline-validation.json` | 12386 B（12.1 KB） | B | 材料离线校验结果（JSON 顶层键：validation） | 2026-10-16 09:47 | 无训练实验；tokenizer 材料批次 2026-10-16 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-materials-20261016/tokenizer-sources.json` | 3880 B（3.8 KB） | B | 两评审模型 tokenizer 来源（JSON 顶层键：模型名） | 2026-10-16 09:46 | 无训练实验；tokenizer 材料批次 2026-10-16 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |

### `evaluation-tokenizer-materials/`（4 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/evaluation-tokenizer-materials/hf-only-render-cases-20261015.json` | 465288 B（454.4 KB） | B | HF 侧合成渲染用例（JSON 顶层键：models） | 2026-10-15 22:16 | 无训练实验；tokenizer 材料批次 2026-10-15 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-materials/official-wheel-inventory.json` | 14252 B（13.9 KB） | B | 官方 wheel 明细清单（JSON 顶层键：包名） | 2026-10-15 22:17 | 无训练实验；tokenizer 材料批次 2026-10-15 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-materials/environment-verification.json` | 6728 B（6.6 KB） | B | 独立环境核验（JSON 顶层键：freeze_sha256） | 2026-10-15 22:17 | 无训练实验；tokenizer 材料批次 2026-10-15 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-materials/installed-freeze.txt` | 481 B（481 B） | B | 独立环境已装包冻结清单（文件正文：包==版本） | 2026-10-15 22:17 | 无训练实验；tokenizer 材料批次 2026-10-15 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |

### `model-inventory-audit-20260831/`（1 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/model-inventory-audit-20260831/remote_snapshot.json` | 108733 B（106.2 KB） | B | 训练机资产盘点快照（JSON 顶层键：runs/symlinks） | 2026-08-31 15:33 | 无训练实验（训练机资产盘点 2026-08-31） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |

### `model_evidence/`（40 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/adapter/trainer_state.json` | 43849 B（42.8 KB） | B | 训练 state 与 loss 日志（JSON 顶层键：log_history） | 2026-07-28 04:15 | v4.1-phase2-coverage-first-v1-seed3411 | 过程中间产物 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/adapter/trainer_state.json` | 43842 B（42.8 KB） | B | 训练 state 与 loss 日志（JSON 顶层键：log_history） | 2026-07-26 21:20 | v4.1-phase2-source-aware-v1-seed3407 | 过程中间产物 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/adapter/trainer_state.json` | 43830 B（42.8 KB） | B | 训练 state 与 loss 日志（JSON 顶层键：log_history） | 2026-07-27 02:37 | v4.1-phase2-source-aware-v1-seed3411 | 过程中间产物 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/adapter/trainer_state.json` | 43809 B（42.8 KB） | B | 训练 state 与 loss 日志（JSON 顶层键：log_history） | 2026-07-28 09:42 | v4.1-phase2-coverage-fallback-v1-seed3413 | 过程中间产物 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/adapter/trainer_state.json` | 43694 B（42.7 KB） | B | 训练 state 与 loss 日志（JSON 顶层键：log_history） | 2026-09-01 10:08 | v4.1-prompt-minimal-v1-seed3411 | 过程中间产物 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/MANIFEST.json` | 11832 B（11.6 KB） | A | 归档证据包清单与哈希（README 自述：归档证据包） | 2026-09-01 15:24 | v4.1-phase2-coverage-first-v1-seed3411 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/MANIFEST.json` | 11770 B（11.5 KB） | A | 归档证据包清单与哈希（README 自述：归档证据包） | 2026-09-01 15:24 | v4.1-phase2-coverage-fallback-v1-seed3413 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/MANIFEST.json` | 11653 B（11.4 KB） | A | 归档证据包清单与哈希（README 自述：归档证据包） | 2026-09-01 15:24 | v4.1-phase2-source-aware-v1-seed3411 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/MANIFEST.json` | 11652 B（11.4 KB） | A | 归档证据包清单与哈希（README 自述：归档证据包） | 2026-09-01 15:24 | v4.1-phase2-source-aware-v1-seed3407 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/MANIFEST.json` | 9929 B（9.7 KB） | A | 归档证据包清单与哈希（README 自述：归档证据包） | 2026-09-01 10:09 | v4.1-prompt-minimal-v1-seed3411 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/README.md` | 7288 B（7.1 KB） | C | 归档证据包说明（README 自述） | 2026-09-01 15:25 | v4.1-phase2-source-aware-v1-seed3411 | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/README.md` | 7287 B（7.1 KB） | C | 归档证据包说明（README 自述） | 2026-09-01 15:25 | v4.1-phase2-source-aware-v1-seed3407 | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/README.md` | 7254 B（7.1 KB） | C | 归档证据包说明（README 自述） | 2026-09-01 15:25 | v4.1-phase2-coverage-fallback-v1-seed3413 | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/README.md` | 7222 B（7.1 KB） | C | 归档证据包说明（README 自述） | 2026-09-01 15:25 | v4.1-phase2-coverage-first-v1-seed3411 | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/evaluation/evidence_manifest.json` | 6097 B（6.0 KB） | B | 语义实验证据清单（JSON 顶层键：experiment_id） | 2026-09-01 10:08 | v4.1-prompt-minimal-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/README.md` | 5982 B（5.8 KB） | C | 模型归档证据包目录索引（README 自述） | 2026-10-12 15:12 | 无（跨实验索引） | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 44） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/input/merged_model_file_manifest.json` | 5670 B（5.5 KB） | B | 合并文件清单与种子（JSON 顶层键：run_id/seed） | 2026-07-28 04:32 | v4.1-phase2-coverage-first-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/input/merged_model_file_manifest.json` | 5321 B（5.2 KB） | B | 合并文件清单与种子（JSON 顶层键：run_id/seed） | 2026-07-28 10:01 | v4.1-phase2-coverage-fallback-v1-seed3413 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/README.md` | 3368 B（3.3 KB） | C | 归档证据包说明（README 自述） | 2026-09-01 10:09 | v4.1-prompt-minimal-v1-seed3411 | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/input/experiment_contract.json` | 3176 B（3.1 KB） | B | 实验契约快照（README 自述：归档证据包） | 2026-09-01 10:08 | v4.1-prompt-minimal-v1-seed3411 | 历史归档 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/input/training_run_manifest.json` | 2592 B（2.5 KB） | A | 训练 run 清单（JSON 顶层键：sampling_summary） | 2026-07-28 04:19 | v4.1-phase2-coverage-first-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/input/training_run_manifest.json` | 2566 B（2.5 KB） | A | 训练 run 清单（JSON 顶层键：sampling_summary） | 2026-07-28 09:46 | v4.1-phase2-coverage-fallback-v1-seed3413 | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/input/training_run_manifest.json` | 2533 B（2.5 KB） | A | 训练 run 清单（JSON 顶层键：sampling_summary） | 2026-07-27 02:41 | v4.1-phase2-source-aware-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/input/training_run_manifest.json` | 2532 B（2.5 KB） | A | 训练 run 清单（JSON 顶层键：sampling_summary） | 2026-07-26 21:31 | v4.1-phase2-source-aware-v1-seed3407 | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/evaluation/evaluation_summary.json` | 2226 B（2.2 KB） | B | 该 run 评测指标摘要（JSON 顶层键：strict_valid_rate） | 2026-09-01 10:08 | v4.1-prompt-minimal-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/input/summary.json` | 1911 B（1.9 KB） | C | 固定 Prompt 数据集摘要（JSON 顶层键：status=ready） | 2026-09-01 10:08 | v4.1-prompt-minimal-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 78） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/evaluation/evaluation_summary.json` | 1599 B（1.6 KB） | B | 该 run 评测指标摘要（JSON 顶层键：strict_valid_rate） | 2026-07-26 21:41 | v4.1-phase2-source-aware-v1-seed3407 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/evaluation/evaluation_summary.json` | 1598 B（1.6 KB） | B | 该 run 评测指标摘要（JSON 顶层键：strict_valid_rate） | 2026-07-27 02:54 | v4.1-phase2-source-aware-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/evaluation/evaluation_summary.json` | 1583 B（1.5 KB） | B | 该 run 评测指标摘要（JSON 顶层键：strict_valid_rate） | 2026-07-28 04:40 | v4.1-phase2-coverage-first-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/evaluation/evaluation_summary.json` | 1548 B（1.5 KB） | B | 该 run 评测指标摘要（JSON 顶层键：strict_valid_rate） | 2026-07-28 10:09 | v4.1-phase2-coverage-fallback-v1-seed3413 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/identity/run_identity.json` | 1027 B（1.0 KB） | C | 评测 run 身份（JSON 顶层键：contract_hash） | 2026-09-01 10:08 | v4.1-prompt-minimal-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/input/dataset_info.json` | 918 B（918 B） | C | 数据集信息条目（JSON 顶层键：数据集名） | 2026-09-01 10:08 | v4.1-prompt-minimal-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 40） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/identity/model_identity.json` | 648 B（648 B） | A | 模型身份记录（README 自述：归档证据包） | 2026-07-29 10:42 | v4.1-phase2-coverage-first-v1-seed3411 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/identity/model_identity.json` | 626 B（626 B） | A | 模型身份记录（README 自述：归档证据包） | 2026-07-29 10:42 | v4.1-phase2-coverage-fallback-v1-seed3413 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/identity/model_identity.json` | 612 B（612 B） | A | 模型身份记录（README 自述：归档证据包） | 2026-07-29 10:42 | v4.1-phase2-source-aware-v1-seed3407 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/identity/model_identity.json` | 612 B（612 B） | A | 模型身份记录（README 自述：归档证据包） | 2026-07-29 10:42 | v4.1-phase2-source-aware-v1-seed3411 | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/identity/run_identity.json` | 428 B（428 B） | C | 评测 run 身份（JSON 顶层键：contract_hash） | 2026-07-28 04:32 | v4.1-phase2-coverage-first-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/identity/run_identity.json` | 417 B（417 B） | C | 评测 run 身份（JSON 顶层键：contract_hash） | 2026-07-28 10:01 | v4.1-phase2-coverage-fallback-v1-seed3413 | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/identity/run_identity.json` | 413 B（413 B） | C | 评测 run 身份（JSON 顶层键：contract_hash） | 2026-07-26 21:34 | v4.1-phase2-source-aware-v1-seed3407 | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/identity/run_identity.json` | 413 B（413 B） | C | 评测 run 身份（JSON 顶层键：contract_hash） | 2026-07-27 02:47 | v4.1-phase2-source-aware-v1-seed3411 | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 21） |

### `v4_1_0_760050fad303_20260724_visual/`（4 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_0_760050fad303_20260724_visual/evidence_manifest.json` | 28416 B（27.8 KB） | B | 运行证据冻结清单与哈希（JSON 顶层键：result_files） | 2026-07-24 20:48 | v4_1_0_760050fad303_20260724_visual | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/v4_1_0_760050fad303_20260724_visual/metrics_report.json` | 22268 B（21.7 KB） | B | 三形态合并模型指标（JSON 顶层键：merged_bf16） | 2026-07-24 20:48 | v4_1_0_760050fad303_20260724_visual | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/v4_1_0_760050fad303_20260724_visual/invalid_output_analysis.json` | 17314 B（16.9 KB） | B | 严格非法输出归因（JSON 顶层键：root_cause） | 2026-07-24 20:48 | v4_1_0_760050fad303_20260724_visual | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/v4_1_0_760050fad303_20260724_visual/README.md` | 3891 B（3.8 KB） | C | 视觉运行证据冻结说明（README 自述） | 2026-07-24 20:49 | v4_1_0_760050fad303_20260724_visual | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |

### `v4_1_agent_pipeline_fold0_r1/`（2 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_agent_pipeline_fold0_r1/deployment_summary.json` | 2340 B（2.3 KB） | B | 部署与冒烟验证摘要（JSON 顶层键：agent_pipeline_smoke） | 2026-07-29 10:37 | v4.1-agent-pipeline-fold0-r1 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/v4_1_agent_pipeline_fold0_r1/README.md` | 1075 B（1.0 KB） | C | Fold0 R1 晋级部署说明（README 自述） | 2026-07-29 11:04 | v4.1-agent-pipeline-fold0-r1 | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |

### `v4_1_phase1_effective_view_audit/`（9 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_phase1_effective_view_audit/audit_manifest.json` | 6002018 B（5.72 MB） | A | 有效视野审计总清单（JSON 顶层键：audit_id/coverage） | 2026-07-25 12:13 | effective-view-audit-eeb18caba8bd | 现行有效 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_phase1_effective_view_audit/development_review_candidates.json` | 823418 B（804.1 KB） | A | 开发集人工复审候选（JSON 顶层键：candidates） | 2026-07-25 12:13 | effective-view-audit-eeb18caba8bd | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_phase1_effective_view_audit/sealed_test_review_candidates.json` | 721018 B（704.1 KB） | A | 密封集人工复审候选（JSON 顶层键：candidates） | 2026-07-25 12:13 | effective-view-audit-eeb18caba8bd | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_phase1_effective_view_audit/leakage_report.json` | 59789 B（58.4 KB） | A | 泄漏与近重复簇报告（JSON 顶层键：leakage） | 2026-07-25 12:13 | effective-view-audit-eeb18caba8bd | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_phase1_effective_view_audit/coverage_report.json` | 23311 B（22.8 KB） | A | 审计覆盖率与无法判读池（JSON 顶层键：coverage） | 2026-07-25 12:13 | effective-view-audit-eeb18caba8bd | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_phase1_effective_view_audit/report.md` | 3740 B（3.7 KB） | A | 有效视野审计历史报告（本文自述：非现行手册） | 2026-10-12 15:14 | effective-view-audit-eeb18caba8bd | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_phase1_effective_view_audit/unable_judgment_pool.json` | 1150 B（1.1 KB） | A | 无法判读样本池（JSON 顶层键：scope） | 2026-07-25 12:13 | effective-view-audit-eeb18caba8bd | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_phase1_effective_view_audit/manifest.json` | 1023 B（1023 B） | C | 审计产物清单与完成度（JSON 顶层键：artifacts） | 2026-07-25 12:13 | effective-view-audit-eeb18caba8bd | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 109） |
| `docs/results/v4_1_phase1_effective_view_audit/README.md` | 342 B（342 B） | C | 审计目录说明与冻结 ID（README 自述） | 2026-10-12 15:14 | effective-view-audit-eeb18caba8bd | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |

### `v4_1_phase2_development_release/`（2 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_phase2_development_release/README.md` | 2410 B（2.4 KB） | C | 阶段2 development 发布冻结说明（README 自述） | 2026-08-25 14:40 | v4.1.0-ecb5aeb9657c（阶段2 development 发布） | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/v4_1_phase2_development_release/release_summary.json` | 1329 B（1.3 KB） | A | 发布冻结摘要与数量闭合（JSON 顶层键：counts） | 2026-07-26 16:17 | v4.1.0-ecb5aeb9657c（阶段2 development 发布） | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |

### `v4_1_phase2_review_queues/`（2 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_phase2_review_queues/README.md` | 1957 B（1.9 KB） | C | 两隔离人工审查队列说明（README 自述） | 2026-07-26 14:50 | v4-1-phase2 审查队列（development/sealed_test） | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/v4_1_phase2_review_queues/manifest.json` | 1830 B（1.8 KB） | C | 审查队列冻结清单（JSON 顶层键：queues） | 2026-07-25 14:09 | v4-1-phase2 审查队列（development/sealed_test） | 证据-可复核底稿 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 110） |

### `v4_1_phase2_source_aware_3k_coverage_first/`（1 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_phase2_source_aware_3k_coverage_first/stage_b_canary_gate_summary.json` | 2458 B（2.4 KB） | C | Stage B 金丝雀门失败结论（JSON 顶层键：status） | 2026-07-27 08:46 | v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3 | 门禁或准入结论 | 无（未见取代记录） | 保留待用户核定（门禁/准备结论唯一凭证） |

### `v4_1_prompt_concise_cv_v1_seed3411/`（1 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md` | 21357 B（20.9 KB） | B | 三折训练与历史模型对比报告（README 自述） | 2026-08-25 14:40 | v4.1-prompt-concise-cv-v1-seed3411 | 说明文档 | 无（未见取代记录） | 保留（实验间互相引用） |

### `v4_1_stage_b_intermediate/`（2 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_stage_b_intermediate/acceptance_summary.json` | 1950 B（1.9 KB） | A | 中间模型准入结论与产物门（JSON 顶层键：artifact_gate） | 2026-07-27 09:39 | v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3 | 现行有效 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_stage_b_intermediate/README.md` | 1449 B（1.4 KB） | C | Stage B 中间模型准入说明（README 自述） | 2026-07-27 09:39 | v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3 | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |

### `v4_1_stage_d_sealed_test_release/`（4 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/v4_1_stage_d_sealed_test_release/README.md` | 2289 B（2.2 KB） | C | Stage D 密封测试发布说明（README 自述） | 2026-07-27 17:11 | stage-d-run-da566a5644f8；release v4.1-sealed-test-5546b8bf1ec3 | 说明文档 | 无（未见取代记录） | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/v4_1_stage_d_sealed_test_release/release_summary.json` | 1765 B（1.7 KB） | A | 密封测试 release 摘要（JSON 顶层键：counts） | 2026-07-27 16:07 | stage-d-run-da566a5644f8；release v4.1-sealed-test-5546b8bf1ec3 | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/v4_1_stage_d_sealed_test_release/preparation_summary.json` | 1297 B（1.3 KB） | C | 一次性推理准备结论（JSON 顶层键：status） | 2026-07-27 16:30 | stage-d-run-da566a5644f8；release v4.1-sealed-test-5546b8bf1ec3 | 门禁或准入结论 | 无（未见取代记录） | 保留待用户核定（门禁/准备结论唯一凭证） |
| `docs/results/v4_1_stage_d_sealed_test_release/public_gate_summary.json` | 1013 B（1013 B） | B | 公开门结果与完整性（JSON 顶层键：gates/passed） | 2026-07-27 17:11 | stage-d-run-da566a5644f8；release v4.1-sealed-test-5546b8bf1ec3 | 门禁或准入结论 | 无（未见取代记录） | 保留（实验间互相引用） |

### `version-control-migration/`（8 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/version-control-migration/verification.md` | 274882 B（268.4 KB） | A | 迁移只读调研与 payload 哈希证据（H1 标题自述） | 2026-10-12 13:31 | 2026-09-07-readable-version-control-migration | 现行有效 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/history-summary.yaml` | 186698 B（182.3 KB） | A | 历史接受汇总（YAML 顶层键：history_summary_schema） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/historical-review-attestation.json` | 40221 B（39.3 KB） | B | 历史人工审批回执比对（JSON 顶层键：object_comparison） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/version-control-migration/source-inventory.yaml` | 12249 B（12.0 KB） | A | M0 源对象清单草稿（YAML 顶层注释自述） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/object-mapping.yaml` | 11649 B（11.4 KB） | A | M0 对象映射候选（YAML 顶层注释自述） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/entrypoint-map.md` | 10797 B（10.5 KB） | A | 迁移入口调用图与保护清单（H1 标题自述） | 2026-10-12 13:10 | 2026-09-07-readable-version-control-migration | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/handoff.md` | 2910 B（2.8 KB） | A | 迁移交接与验收范围（H1 标题自述） | 2026-10-12 15:12 | 2026-09-07-readable-version-control-migration | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/mac-review-return-verification.json` | 677 B（677 B） | B | Mac 侧复审回执校验（JSON 顶层键：return_sha256） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |

### 顶层散落文件（57 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/ollama-tokenizer-reference-20261015.json` | 816853 B（797.7 KB） | B | Ollama 分词观测数据（JSON 顶层键：comparison_count） | 2026-10-15 22:57 | ollama-tokenizer-reference（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-counter-20261015.json` | 326172 B（318.5 KB） | B | 分词计数比对（JSON 顶层键：comparison_summary） | 2026-10-15 22:22 | evaluation-tokenizer-counter（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-20261016.json` | 323224 B（315.6 KB） | B | HF/GGUF 分词兼容复验（JSON 顶层键：summary） | 2026-10-16 09:44 | evaluation-tokenizer-compatibility（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-state-refresh-20261013.json` | 144425 B（141.0 KB） | B | 训练机只读现状快照（JSON 顶层键：queries） | 2026-10-13 16:17 | remote-state-refresh（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/conda-environment-setup-20261013.json` | 144182 B（140.8 KB） | B | 训练机 Conda 部署与体检（JSON 顶层键：doctor） | 2026-10-13 17:07 | conda-environment-setup（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/development-source-map-observation-20261016.json` | 119983 B（117.2 KB） | B | 候选与源视频映射观测（JSON 顶层键：mapping） | 2026-10-16 12:01 | development-source-map-observation（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/development-source-groups-20261016.json` | 100105 B（97.8 KB） | B | 开发集来源分组与折独立性（JSON 顶层键：source_groups） | 2026-10-16 12:33 | development-source-groups（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-fixed-revision-upstream-20261016.json` | 94381 B（92.2 KB） | B | 固定 revision 取证（JSON 顶层键：status） | 2026-10-16 11:29 | minicpm-fixed-revision-upstream（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-base-static-source-20261016.json` | 82644 B（80.7 KB） | B | 基座静态源码闭包（JSON 顶层键：static_python_closure） | 2026-10-16 11:29 | remote-base-static-source（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-base-integrity-20261016.json` | 62530 B（61.1 KB） | B | 训练机基座完整性（JSON 顶层键：successful_hash_phase） | 2026-10-16 10:15 | remote-base-integrity（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-postinit-runtime-source-20261016.json` | 61106 B（59.7 KB） | B | 训练机源码采集（JSON 顶层键：transformers_sources） | 2026-10-16 11:45 | minicpm-postinit-runtime-source（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-base-download-origin-20261016.json` | 58830 B（57.5 KB） | B | 基座下载来源取证（JSON 顶层键：file_comparisons） | 2026-10-16 11:29 | minicpm-base-download-origin（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model-r1-effect-profile-20261018.json` | 52126 B（50.9 KB） | C | R1 效果档案配套数据（JSON 顶层键：model/statement） | 2026-10-18 17:05 | v4.1-agent-pipeline-fold0-r1（顶层散文件，未归属实验目录） | 现行有效 | 无（未见取代记录） | 保留（新入库证据，不得删） |
| `docs/results/model-r1-effect-profile-20261018.md` | 50174 B（49.0 KB） | C | R1 模型效果档案正文（H1 标题自述） | 2026-10-18 17:06 | v4.1-agent-pipeline-fold0-r1（顶层散文件，未归属实验目录） | 现行有效 | 无（未见取代记录） | 保留（新入库证据，不得删） |
| `docs/results/train-video-cleanup-candidates-20260913.json` | 47010 B（45.9 KB） | B | 训练视频清理候选清单（JSON 顶层键：rows） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | train-video-cleanup-candidates（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/development-input-inventory-20261016.json` | 42556 B（41.6 KB） | B | 开发输入与契约绑定（JSON 顶层键：prompt_and_contract） | 2026-10-16 12:04 | development-input-inventory（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-preparation-audit-connected-20261016.json` | 41081 B（40.1 KB） | B | 连通后的训练机准备审计（JSON 顶层键：remote_result） | 2026-10-16 10:12 | remote-preparation-audit-connected（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model-diagnostics-preflight-20260913.json` | 40146 B（39.2 KB） | A | 只读模型诊断预检执行（JSON 顶层键：executions） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | model-diagnostics-preflight（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/evaluation-review-environment-audit-20261016.json` | 27087 B（26.5 KB） | B | 本机评审环境审计（JSON 顶层键：baseline_commit） | 2026-10-16 10:12 | evaluation-review-environment-audit（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-postinit-purpose-analysis-20261016.json` | 25402 B（24.8 KB） | B | post_init 用途静态分析（JSON 顶层键：direct_answer） | 2026-10-16 11:46 | minicpm-postinit-purpose-analysis（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model-inventory.md` | 18290 B（17.9 KB） | B | V4.1 模型清单与效果对比（H1 标题自述） | 2026-10-16 10:20 | model-inventory（顶层散文件，未归属实验目录） | 说明文档 | `model-gate-baseline-20260914.md`（本文自述指向） | 保留（实验间互相引用） |
| `docs/results/development-runtime-readiness-20261016.json` | 17013 B（16.6 KB） | B | 运行时就绪与资源预算（JSON 顶层键：ready_for_real_run） | 2026-10-16 12:33 | development-runtime-readiness（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-review-readiness-20261016.json` | 16633 B（16.2 KB） | B | 评审就绪清单（JSON 顶层键：ready_for_real_review） | 2026-10-16 09:48 | evaluation-review-readiness（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/training-data-ledger-20261017.json` | 14118 B（13.8 KB） | B | r2 数据台账结构化数据（JSON 顶层键：counts/folds） | 2026-10-18 13:07（文件名日期 2026-10-17，与 mtime 不同源） | training-data-ledger（顶层散文件，未归属实验目录） | 现行有效 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-hf-assets-20261015.json` | 13904 B（13.6 KB） | B | HF tokenizer 固定资产清单（JSON 顶层键：kind） | 2026-10-15 22:18 | evaluation-tokenizer-hf-assets（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/conditional-cleanup-preflight-20260913.json` | 13170 B（12.9 KB） | B | 有条件清理预检与删除记录（JSON 顶层键：bytes_freed） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | conditional-cleanup-preflight（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-independent-20261016.json` | 12631 B（12.3 KB） | B | 独立复核分词兼容（JSON 顶层键：replay_script） | 2026-10-16 09:45 | evaluation-tokenizer-compatibility-independent（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-materials-20261015.md` | 11868 B（11.6 KB） | A | tokenizer 来源与映射材料记录（H1 标题自述） | 2026-10-15 22:33 | evaluation-tokenizer-materials（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/documentation-consolidation-20261012.md` | 11558 B（11.3 KB） | A | 文档整理与正式入口梳理记录（H1 标题自述） | 2026-10-12 15:24 | documentation-consolidation（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/evaluation-readiness-20261015.md` | 11373 B（11.1 KB） | B | 真实运行前环境与资产核验（H1 标题自述） | 2026-10-15 22:04 | evaluation-readiness（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-independent-performance-admission-20261015.md` | 11328 B（11.1 KB） | A | 独立评分、性能与准入接线（H1 标题自述） | 2026-10-15 21:49 | evaluation-independent-performance-admission（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model-gate-baseline-20260914.md` | 10546 B（10.3 KB） | B | 模型资产与门禁背景档案（文档契约 Purpose） | 2026-10-12 15:14（文件名日期 2026-09-14，与 mtime 不同源） | model-gate-baseline（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-state-refresh-20261013.md` | 10487 B（10.2 KB） | A | 训练机只读现状核查正文（H1 标题自述） | 2026-10-13 16:25 | remote-state-refresh（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/development-input-runtime-preparation-20261016.md` | 10180 B（9.9 KB） | A | 开发输入与资源预算运行前核验（H1 标题自述） | 2026-10-16 12:33 | development-input-runtime-preparation（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/evaluation-development-implementation-20261015.md` | 9278 B（9.1 KB） | A | 测评基础能力与开发接线记录（H1 标题自述） | 2026-10-15 20:37 | evaluation-development-implementation（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/ollama-tokenizer-verification-20261015.md` | 8038 B（7.8 KB） | A | Ollama 分词核验与 NFC/NFD 差异（H1 标题自述） | 2026-10-16 09:40（文件名日期 2026-10-15，与 mtime 不同源） | ollama-tokenizer-verification（顶层散文件，未归属实验目录） | 历史归档 | `evaluation-review-compatibility-repair-20261016.md`（本文自述） | 保留（被代码或正式文档引用） |
| `docs/results/evaluation-review-isolation-preflight-20261016.json` | 8009 B（7.8 KB） | B | 评审隔离合成预检（JSON 顶层键：synthetic） | 2026-10-16 09:59 | evaluation-review-isolation-preflight（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/todo-preparation-progress-20261016.md` | 7605 B（7.4 KB） | A | TODO 推进与运行前核验记录（H1 标题自述） | 2026-10-16 10:22 | todo-preparation-progress（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration-20260907.md` | 7138 B（7.0 KB） | A | 迁移只读调查记录（H1 标题自述） | 2026-09-14 01:37（文件名日期 2026-09-07，与 mtime 不同源） | version-control-migration（顶层散文件，未归属实验目录） | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/minicpm-fixed-source-audit-20261016.md` | 6683 B（6.5 KB） | A | 基座固定 revision 来源核验（H1 标题自述） | 2026-10-16 11:35 | minicpm-fixed-source-audit（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/evaluation-review-compatibility-repair-20261016.md` | 6278 B（6.1 KB） | A | 评审 tokenizer 兼容修复记录（H1 标题自述） | 2026-10-16 09:49 | evaluation-review-compatibility-repair（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model-location-followup-20260913.json` | 6271 B（6.1 KB） | B | 模型位置跟进探测结果（JSON 顶层键：result） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | model-location-followup（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/training-readiness-20260913.json` | 6107 B（6.0 KB） | B | 训练就绪检查（JSON 顶层键：environment） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | training-readiness（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-isolation-display-preflight-20261016.md` | 6016 B（5.9 KB） | A | 评审隔离与显示测点接线（H1 标题自述） | 2026-10-16 10:03 | evaluation-isolation-display-preflight（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/evaluation-readiness-blob-integrity-20261015.json` | 5826 B（5.7 KB） | B | Ollama blob 完整性核验（JSON 顶层键：records） | 2026-10-15 22:01 | evaluation-readiness-blob-integrity（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/conda-environment-setup-20261013.md` | 5679 B（5.5 KB） | A | Conda 环境部署与绑定记录（H1 标题自述） | 2026-10-13 17:13 | conda-environment-setup（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/train-input-preflight-20260913.json` | 5473 B（5.3 KB） | B | 训练输入预检（JSON 顶层键：media_summary） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | train-input-preflight（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model-recovery-targets-20260913.json` | 5393 B（5.3 KB） | B | 模型恢复目标清单（JSON 顶层键：recovery_targets） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | model-recovery-targets（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/training-data-ledger-20261017.md` | 4663 B（4.6 KB） | C | r2 数据台账分折表正文（H1 标题自述） | 2026-10-18 13:08（文件名日期 2026-10-17，与 mtime 不同源） | training-data-ledger（顶层散文件，未归属实验目录） | 现行有效 | 无（未见取代记录） | 保留（新入库证据，不得删） |
| `docs/results/minicpm-base-upstream-comparison-20261016.json` | 4249 B（4.1 KB） | B | 官方仓元数据与权重比对（JSON 顶层键：files） | 2026-10-16 10:17 | minicpm-base-upstream-comparison（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-readiness-model-inventory-20261015.json` | 4095 B（4.0 KB） | B | 评审模型元数据库存（JSON 顶层键：metadata_only） | 2026-10-15 21:56 | evaluation-readiness-model-inventory（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-postinit-origin-purpose-20261016.md` | 3776 B（3.7 KB） | A | 构造收尾调用核验与停止追查（H1 标题自述） | 2026-10-16 11:49 | minicpm-postinit-origin-purpose（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/remote-preparation-audit-20261016.json` | 3753 B（3.7 KB） | B | SSH 超时的准备审计记录（JSON 顶层键：status=partial） | 2026-10-16 10:09 | remote-preparation-audit（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-readiness-offline-20261015.json` | 3584 B（3.5 KB） | B | 离线评审就绪清单（JSON 顶层键：blockers） | 2026-10-15 21:59 | evaluation-readiness-offline（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-display-client-preflight-20261016.json` | 3496 B（3.4 KB） | B | 显示测点合成预检（JSON 顶层键：dom_render_verified） | 2026-10-16 10:01 | evaluation-display-client-preflight（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-base-source-rejection-preflight-20261016.json` | 2492 B（2.4 KB） | B | 无来源声明时基座被拒（JSON 顶层键：exit_code） | 2026-10-16 11:34 | minicpm-base-source-rejection-preflight（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-client-source-inventory-20261016.json` | 2278 B（2.2 KB） | B | 客户端源码运行前清单（JSON 顶层键：candidate_only） | 2026-10-16 09:58 | evaluation-client-source-inventory（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |

## D. 当前有效（7 条，不新增第 8 条）

| # | 路径 | 入选理由与证据 |
|---|---|---|
| 1 | `docs/results/training-data-ledger-20261017.json` | 现行 r2 数据台账结构化数据，`docs/project-todo.md` 的 R2-REALTRAIN 条直接引用其 `state` / `status` / `training_allowed` 字段。 |
| 2 | `docs/results/training-data-ledger-20261017.md` | 同一台账的分折表正文（1,678 候选 / 85 来源、三折拆分），被 R2-REALTRAIN 条与 `.json` 并列引用。 |
| 3 | `docs/results/model-r1-effect-profile-20261018.md` | 最新 R1 模型效果档案，`docs/project-todo.md` 的 R2-REALTRAIN 条「证据位置」四条之一。 |
| 4 | `docs/results/model-r1-effect-profile-20261018.json` | 上述档案的配套数据文件，同条「证据位置」。 |
| 5 | `docs/results/v4_1_phase1_effective_view_audit/audit_manifest.json` | 有效视野审计的唯一可复核输入：`finetune/eval_audit_effective_views.py:760` 的产物名 `audit_manifest.json`，`pipeline/v4_1_review_workflow.py` 构造时读取同一审计 manifest（两条均已核实）。`pipeline/scripts/release_build_phase2.py:84-86` 的引用按 basename 计——脚本实际指向 `paths.metadata/v4_1/effective_view_audits/phase1_verified/audit_manifest.json`（store 侧同名文件），不是本仓库路径（第 4.5 节引用数 7）。 |
| 6 | `docs/results/v4_1_stage_b_intermediate/acceptance_summary.json` | 当前晋级中间模型的准入结论：`delivery/model_component.json` 以 `acceptance_summary_path` + `acceptance_summary_sha256` 直接指向，`pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json` 的 `acceptance_summary_path` 同指。 |
| 7 | `docs/results/version-control-migration/verification.md` | 版本控制迁移验收凭证，被 `ARCHITECTURE.md`、`versioning/SCRIPTS.md`、`docs/project-todo.md`、`docs/model-workflow.md` 等引用（第 4.5 节引用数 16）。 |

> 说明：本表只声明「当前有效」，不改变 C 节任何档位；C 类中真零引用 5 个的处置见 E 节。

## E. C 类专节（真零引用 5 / NOISY 降级 22）

### E.1 真零引用 5 个（第 4.6 节）

| 路径 | 体积 | 建议 |
|---|---|---|
| `docs/results/model-r1-effect-profile-20261018.json` | 52126 B（50.9 KB） | 保留（新入库证据，不得删） |
| `docs/results/model-r1-effect-profile-20261018.md` | 50174 B（49.0 KB） | 保留（新入库证据，不得删） |
| `docs/results/training-data-ledger-20261017.md` | 4663 B（4.6 KB） | 保留（新入库证据，不得删） |
| `docs/results/v4_1_phase2_source_aware_3k_coverage_first/stage_b_canary_gate_summary.json` | 2458 B（2.4 KB） | 保留待用户核定（门禁/准备结论唯一凭证） |
| `docs/results/v4_1_stage_d_sealed_test_release/preparation_summary.json` | 1297 B（1.3 KB） | 保留待用户核定（门禁/准备结论唯一凭证） |

前 3 个为随 `187822fe`、`36016711` 入库的新证据，不得删；后 2 个为门禁/准备结论的唯一凭证，须由用户核定。

### E.2 NOISY 降级 22 个（basename 命中取第 4.6 节）

| 路径 | 体积 | basename 命中 | 建议 |
|---|---|---|---|
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/README.md` | 7288 B（7.1 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/README.md` | 7287 B（7.1 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/README.md` | 7254 B（7.1 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/README.md` | 7222 B（7.1 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/README.md` | 5982 B（5.8 KB） | 44 | 不得判可删，NOISY 降级（basename 命中 44） |
| `docs/results/v4_1_0_760050fad303_20260724_visual/README.md` | 3891 B（3.8 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/README.md` | 3368 B（3.3 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/v4_1_phase2_development_release/README.md` | 2410 B（2.4 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/v4_1_stage_d_sealed_test_release/README.md` | 2289 B（2.2 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/v4_1_phase2_review_queues/README.md` | 1957 B（1.9 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/input/summary.json` | 1911 B（1.9 KB） | 78 | 不得判可删，NOISY 降级（basename 命中 78） |
| `docs/results/v4_1_phase2_review_queues/manifest.json` | 1830 B（1.8 KB） | 110 | 不得判可删，NOISY 降级（basename 命中 110） |
| `docs/results/v4_1_stage_b_intermediate/README.md` | 1449 B（1.4 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/v4_1_agent_pipeline_fold0_r1/README.md` | 1075 B（1.0 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/identity/run_identity.json` | 1027 B（1.0 KB） | 21 | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/v4_1_phase1_effective_view_audit/manifest.json` | 1023 B（1023 B） | 109 | 不得判可删，NOISY 降级（basename 命中 109） |
| `docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/input/dataset_info.json` | 918 B（918 B） | 40 | 不得判可删，NOISY 降级（basename 命中 40） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/identity/run_identity.json` | 428 B（428 B） | 21 | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/identity/run_identity.json` | 417 B（417 B） | 21 | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/identity/run_identity.json` | 413 B（413 B） | 21 | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/identity/run_identity.json` | 413 B（413 B） | 21 | 不得判可删，NOISY 降级（basename 命中 21） |
| `docs/results/v4_1_phase1_effective_view_audit/README.md` | 342 B（342 B） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |

22 个 NOISY 放开规则后全部落 A 类，故「C 类 27 个」不等于「27 个可删」。

> 基线说明：审计采集于 `36016711`，该提交时 `docs/project-todo.md` 尚无 R2-REALTRAIN 条（`grep -c R2-REALTRAIN` = 0）；`c5ad8311` 新增该条、`21229565` 补记进展后，该条已把 `model-r1-effect-profile-20261018.*` 与两份数据台账列为证据位置。档位与计数仍按审计清单如实照抄，不作重算。

## F. 机器自检

自检脚本：`/Users/pcoffeep/pi-workspace/mVllm_2-audit/check_index.py`（仓库外），解析本文件主表并与审计第 4.5 节逐条比对。

```
命令（仓库根 `/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2` 下执行）：
$ python3 /Users/pcoffeep/pi-workspace/mVllm_2-audit/check_index.py
退出码：0

== A. 主表行数与字段 ==
PASS 主表数据行数 = 141  -> 实测 141
PASS 9 列逐格非空（空单元格数 = 0）  -> 空单元格 0 处 []
PASS 每行恰 9 个字段（无多余分隔符）
== B. 路径与 4.5 节一一对应 ==
PASS 无重复路径  -> []
PASS 仅在 INDEX 出现的路径（应为空集）  -> []
PASS 仅在 4.5 节出现的路径（应为空集）  -> []
路径集合 diff：only_in_index=0，only_in_audit=0，交集=141
== C. 体积 / 档位 / 时点 与 4.5 节逐条一致 ==
PASS 体积字符串逐条照抄 4.5 节  -> []
PASS 档位逐条照抄 4.5 节  -> []
PASS 档位只出现 A/B/C
PASS 时点以 4.5 节 mtime 开头  -> []
== D. 分级计数与体积累加 ==
PASS A/B/C = 44/70/27  -> {'A': 44, 'B': 70, 'C': 27}
PASS A+B+C = 141  -> 141
PASS 分级体积累加 = 8,364,288 / 4,314,200 / 170,912 B  -> {'A': 8364288, 'B': 4314200, 'C': 170912}
PASS 体积列字节数累加 = 12,849,400 B  -> 12,849,400
== E. 状态词表与「当前有效」 ==
PASS 状态只用词表内 7 个值  -> []
PASS 「现行有效」正好 7 条且与 D 节一致  -> 实测 7 条
PASS D 节「当前有效」表格行数 = 7  -> 7
PASS D 节 7 条路径与预期一致
== F. C 类 5 + 22 拆分 ==
PASS E 节 5 + 22 = 27  -> 真零引用 5，NOISY 22
PASS 真零引用体积累加 = 110,718 B  -> 110,718
PASS NOISY 体积累加 = 60,194 B  -> 60,194
PASS 110,718 + 60,194 = 170,912 B  -> 170,912
PASS C 类 27 条与 4.6 节集合一致
PASS 22 条 NOISY 建议列含指定原文且 N 取自 4.6 节  -> []
PASS 前 3 条真零引用建议原文正确
PASS 后 2 条真零引用建议原文正确
PASS E 节含 NOISY 敏感性结论句
== G. 单元格长度 ==
PASS 是什么 ≤ 40 字符  -> []
PASS 时点 ≤ 55 字符（mtime 全值 + 文件名日期注记）  -> []
PASS 建议 ≤ 40 字符  -> []
PASS 体积 ≤ 30 字符  -> []
PASS 档位 ≤ 30 字符  -> []
PASS 状态 ≤ 30 字符  -> []
PASS 对应实验 中文字符 ≤ 25（实验标识与固定后缀以拉丁字符为主）  -> []
PASS 对应实验 总长度 ≤ 80 字符  -> max=62
PASS 取代者 中文字符 ≤ 25（含路径时长度由路径决定）  -> []
PASS 取代者 总长度 ≤ 60 字符  -> max=58
== H. 无 Markdown 链接 ==
PASS INDEX.md 内 Markdown 链接数 = 0  -> []
== I. 仓库状态 ==
PASS grep -c "^### " docs/project-todo.md = 40  -> 40
PASS git status --porcelain -uall 只有 INDEX.md 一行  -> ['?? docs/results/INDEX.md']
PASS git diff --check（--no-index /dev/null）无空白/冲突提示
== J. 实测体积与 4.5 节的偏差（信息项，不判失败） ==
实测体积偏差条数：0（无偏差）

结果：共 41 项检查，失败 0 项
```

## G. 偏差

无。实测 141 个文件体积与第 4.5 节主表逐条一致（F 节 J 段输出「实测体积偏差条数：0（无偏差）」）；本次未发现需要逐条列出的「路径 / 主表值 / 实测值」差异。

补充说明（非体积偏差，供复核）：

- 单元格长度与「（顶层散文件，未归属实验目录）」后缀是本索引自定的书写约定，**非任务书要求**；本表「是什么」按字符数 ≤40 执行；「对应实验」「取代者」两列以实验标识符（如 `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3`）和文件路径为主体，另加本索引自定的固定后缀「（顶层散文件，未归属实验目录）」，按中文字符数 ≤25 校验（两列最长分别为 62 / 58 字符，均为拉丁标识）。
- 审计清单置于仓库外，本文件只以行内代码记录其路径；仅引用其判据与体积数值，未复制审计正文段落，未建立链接。
