# `docs/results/` 文件索引（117 个文件）

> **变更记录** 2026-10-18 清理：移除 24 个文件，现存 117 个。N/M 由 `find docs/results -type f` + `os.path.getsize` 统计；清单见 C 节主表，被清空的两个一级子目录（`v4_1_0_760050fad303_20260724_visual/`、`v4_1_prompt_concise_cv_v1_seed3411/`）整组移除。
> **变更记录** 2026-10-18 另有 R1 训练过程信息 24 个文件同步入库，落位 `records/r1-run-20261018/`，不属 `docs/results` 范围，故不计入本索引统计。

## A. 头部声明

- 覆盖范围：`docs/results/` 现存活 **117** 个文件（顶层散落 38 个，其余分布在 12 个一级子目录）。2026-10-18 清理移除 24 个后，子目录数与各组文件数按磁盘实测重算。
- 数据来源：2026-10-18 全项目审计清单第 4.5 节主表（原 141 行，清理后 117 行）与第 4.6 节 C 类清单，文件路径 `/Users/pcoffeep/pi-workspace/mVllm_2-audit/project-inventory-audit-20261018.md`（仓库外，本机另存，不入 Git）。
- 审计采集基线 `36016711`；本索引编写基线 `21229565`（分支 `feat/evaluation-development`）。
- 本文件只做索引与状态标注：**档位与 mtime 照抄审计清单**；2026-10-18 清理后体积由 `find docs/results -type f` + `os.path.getsize` 逐文件实测，B 节计数与体积累加同由该实测集重算（F 节 `check_index_v2.py`）。不新增比率、不判定删除。
- 本文件 `INDEX.md` 自身不计入主表：主表 117 个文件，目录现有 118 个文件（含本索引）。
- 全部路径使用行内代码书写，未使用 Markdown 链接，故不存在失效链接。

## B. 分级汇总（判据照抄审计第 4.1 节；计数与体积按清理后磁盘实测重算）

| 分级 | 判据 | 文件数 | 合计体积 |
|---|---|---|---|
| A | 被 `*.py`、`README.md`、`AGENTS.md` 或 `docs/*.md` 正文引用 | 38 | 8,287,868 B |
| B | 仅被 `docs/results/**` 其它文件或 `docs/project-todo.md` 引用 | 53 | 3,929,090 B |
| C | 零引用 | 26 | 167,089 B |
| 合计 | A+B+C | 117 | 12,384,047 B |

自检：38 + 53 + 26 = 117，与现存活文件总数相等。总量换算：12,384,047 B = 11.81 MiB。

C 类构成（第 4.6 节口径，清理后重算）：真零引用 5 个 / 110,786 B + NOISY 降级 21 个 / 56,303 B = 167,089 B。

## C. 主表：117 行 × 9 字段

分组顺序照抄第 4.2 节表（一级子目录在前，`（顶层散落文件）` 在最后），组内沿用原体积降序；每组前置小标题并重复表头，组内文件数为清理后的实测值。

`档位` 的 A/B/C 判据见 B 节；`建议` 按档位给出，C 类按第 4.6 节区分真零引用与 NOISY 降级。

### `evaluation-tokenizer-compatibility-materials-20261016/`（4 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/evaluation-tokenizer-compatibility-materials-20261016/qwen3.5-9b-audit.json` | 307380 B（300.2 KB） | B | 受审分词等价材料（JSON 顶层键：golden_cases） | 2026-10-16 09:46 | 无训练实验；tokenizer 材料批次 2026-10-16 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-materials-20261016/ornith-1.5-9b-audit.json` | 307349 B（300.1 KB） | B | 受审分词等价材料（JSON 顶层键：golden_cases） | 2026-10-16 09:46 | 无训练实验；tokenizer 材料批次 2026-10-16 | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-materials-20261016/offline-validation.json` | 12386 B（12.1 KB） | B | 材料离线校验结果（JSON 顶层键：validation） | 2026-10-16 09:47 | 无训练实验；tokenizer 材料批次 2026-10-16 | 证据-可复核底稿 | 无（未见取代记录） | 保留（原引用者已移除，处置建议不变） |
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
| `docs/results/version-control-migration/verification.md` | 275007 B（268.6 KB） | A | 迁移只读调研与 payload 哈希证据（H1 标题自述） | 2026-10-12 13:31 | 2026-09-07-readable-version-control-migration | 现行有效 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/history-summary.yaml` | 186698 B（182.3 KB） | A | 历史接受汇总（YAML 顶层键：history_summary_schema） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/historical-review-attestation.json` | 40221 B（39.3 KB） | B | 历史人工审批回执比对（JSON 顶层键：object_comparison） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/version-control-migration/source-inventory.yaml` | 12344 B（12.1 KB） | A | M0 源对象清单草稿（YAML 顶层注释自述） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/object-mapping.yaml` | 11770 B（11.5 KB） | A | M0 对象映射候选（YAML 顶层注释自述） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/entrypoint-map.md` | 11222 B（11.0 KB） | A | 迁移入口调用图与保护清单（H1 标题自述） | 2026-10-12 13:10 | 2026-09-07-readable-version-control-migration | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/handoff.md` | 2910 B（2.8 KB） | A | 迁移交接与验收范围（H1 标题自述） | 2026-10-12 15:12 | 2026-09-07-readable-version-control-migration | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration/mac-review-return-verification.json` | 677 B（677 B） | B | Mac 侧复审回执校验（JSON 顶层键：return_sha256） | 2026-09-14 01:37 | 2026-09-07-readable-version-control-migration | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |

### 顶层散落文件（38 个文件）

| 路径 | 体积 | 档位 | 是什么 | 时点 | 对应实验 | 状态 | 取代者 | 建议 |
|---|---|---|---|---|---|---|---|---|
| `docs/results/ollama-tokenizer-reference-20261015.json` | 816853 B（797.7 KB） | B | Ollama 分词观测数据（JSON 顶层键：comparison_count） | 2026-10-15 22:57 | ollama-tokenizer-reference（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-counter-20261015.json` | 326172 B（318.5 KB） | B | 分词计数比对（JSON 顶层键：comparison_summary） | 2026-10-15 22:22 | evaluation-tokenizer-counter（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-20261016.json` | 323224 B（315.6 KB） | B | HF/GGUF 分词兼容复验（JSON 顶层键：summary） | 2026-10-16 09:44 | evaluation-tokenizer-compatibility（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-state-refresh-20261013.json` | 144425 B（141.0 KB） | B | 训练机只读现状快照（JSON 顶层键：queries） | 2026-10-13 16:17 | remote-state-refresh（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/development-source-map-observation-20261016.json` | 119983 B（117.2 KB） | B | 候选与源视频映射观测（JSON 顶层键：mapping） | 2026-10-16 12:01 | development-source-map-observation（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/development-source-groups-20261016.json` | 100105 B（97.8 KB） | B | 开发集来源分组与折独立性（JSON 顶层键：source_groups） | 2026-10-16 12:33 | development-source-groups（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-fixed-revision-upstream-20261016.json` | 94381 B（92.2 KB） | B | 固定 revision 取证（JSON 顶层键：status） | 2026-10-16 11:29 | minicpm-fixed-revision-upstream（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-base-static-source-20261016.json` | 82644 B（80.7 KB） | B | 基座静态源码闭包（JSON 顶层键：static_python_closure） | 2026-10-16 11:29 | remote-base-static-source（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-base-integrity-20261016.json` | 62530 B（61.1 KB） | B | 训练机基座完整性（JSON 顶层键：successful_hash_phase） | 2026-10-16 10:15 | remote-base-integrity（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-postinit-runtime-source-20261016.json` | 61106 B（59.7 KB） | B | 训练机源码采集（JSON 顶层键：transformers_sources） | 2026-10-16 11:45 | minicpm-postinit-runtime-source（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-base-download-origin-20261016.json` | 58830 B（57.5 KB） | B | 基座下载来源取证（JSON 顶层键：file_comparisons） | 2026-10-16 11:29 | minicpm-base-download-origin（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model-r1-effect-profile-20261018.json` | 52181 B（51.0 KB） | C | R1 效果档案配套数据（JSON 顶层键：model/statement） | 2026-10-18 17:05 | v4.1-agent-pipeline-fold0-r1（顶层散文件，未归属实验目录） | 现行有效 | 无（未见取代记录） | 保留（新入库证据，不得删） |
| `docs/results/model-r1-effect-profile-20261018.md` | 50187 B（49.0 KB） | C | R1 模型效果档案正文（H1 标题自述） | 2026-10-18 17:06 | v4.1-agent-pipeline-fold0-r1（顶层散文件，未归属实验目录） | 现行有效 | 无（未见取代记录） | 保留（新入库证据，不得删） |
| `docs/results/development-input-inventory-20261016.json` | 42556 B（41.6 KB） | B | 开发输入与契约绑定（JSON 顶层键：prompt_and_contract） | 2026-10-16 12:04 | development-input-inventory（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-preparation-audit-connected-20261016.json` | 41081 B（40.1 KB） | B | 连通后的训练机准备审计（JSON 顶层键：remote_result） | 2026-10-16 10:12 | remote-preparation-audit-connected（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-postinit-purpose-analysis-20261016.json` | 25402 B（24.8 KB） | B | post_init 用途静态分析（JSON 顶层键：direct_answer） | 2026-10-16 11:46 | minicpm-postinit-purpose-analysis（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/model-inventory.md` | 18372 B（17.9 KB） | B | V4.1 模型清单与效果对比（H1 标题自述） | 2026-10-16 10:20 | model-inventory（顶层散文件，未归属实验目录） | 说明文档 | `model-gate-baseline-20260914.md`（本文自述指向） | 保留（实验间互相引用） |
| `docs/results/development-runtime-readiness-20261016.json` | 17013 B（16.6 KB） | B | 运行时就绪与资源预算（JSON 顶层键：ready_for_real_run） | 2026-10-16 12:33 | development-runtime-readiness（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/training-data-ledger-20261017.json` | 14118 B（13.8 KB） | B | r2 数据台账结构化数据（JSON 顶层键：counts/folds） | 2026-10-18 13:07（文件名日期 2026-10-17，与 mtime 不同源） | training-data-ledger（顶层散文件，未归属实验目录） | 现行有效 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-hf-assets-20261015.json` | 14114 B（13.8 KB） | B | HF tokenizer 固定资产清单（JSON 顶层键：kind） | 2026-10-15 22:18 | evaluation-tokenizer-hf-assets（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-compatibility-independent-20261016.json` | 12631 B（12.3 KB） | B | 独立复核分词兼容（JSON 顶层键：replay_script） | 2026-10-16 09:45 | evaluation-tokenizer-compatibility-independent（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-tokenizer-materials-20261015.md` | 11925 B（11.6 KB） | A | tokenizer 来源与映射材料记录（H1 标题自述） | 2026-10-15 22:33 | evaluation-tokenizer-materials（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/evaluation-independent-performance-admission-20261015.md` | 11328 B（11.1 KB） | A | 独立评分、性能与准入接线（H1 标题自述） | 2026-10-15 21:49 | evaluation-independent-performance-admission（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/model-gate-baseline-20260914.md` | 10628 B（10.4 KB） | B | 模型资产与门禁背景档案（文档契约 Purpose） | 2026-10-12 15:14（文件名日期 2026-09-14，与 mtime 不同源） | model-gate-baseline（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/remote-state-refresh-20261013.md` | 10487 B（10.2 KB） | A | 训练机只读现状核查正文（H1 标题自述） | 2026-10-13 16:25 | remote-state-refresh（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/development-input-runtime-preparation-20261016.md` | 10180 B（9.9 KB） | A | 开发输入与资源预算运行前核验（H1 标题自述） | 2026-10-16 12:33 | development-input-runtime-preparation（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/evaluation-development-implementation-20261015.md` | 9278 B（9.1 KB） | A | 测评基础能力与开发接线记录（H1 标题自述） | 2026-10-15 20:37 | evaluation-development-implementation（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/ollama-tokenizer-verification-20261015.md` | 8077 B（7.9 KB） | A | Ollama 分词核验与 NFC/NFD 差异（H1 标题自述） | 2026-10-16 09:40（文件名日期 2026-10-15，与 mtime 不同源） | ollama-tokenizer-verification（顶层散文件，未归属实验目录） | 历史归档 | 原指向的兼容修复记录已随 2026-10-18 清理移除 | 保留（被代码或正式文档引用） |
| `docs/results/version-control-migration-20260907.md` | 7138 B（7.0 KB） | A | 迁移只读调查记录（H1 标题自述） | 2026-09-14 01:37（文件名日期 2026-09-07，与 mtime 不同源） | version-control-migration（顶层散文件，未归属实验目录） | 历史归档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/minicpm-fixed-source-audit-20261016.md` | 6683 B（6.5 KB） | A | 基座固定 revision 来源核验（H1 标题自述） | 2026-10-16 11:35 | minicpm-fixed-source-audit（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/training-readiness-20260913.json` | 6107 B（6.0 KB） | B | 训练就绪检查（JSON 顶层键：environment） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | training-readiness（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/train-input-preflight-20260913.json` | 5473 B（5.3 KB） | B | 训练输入预检（JSON 顶层键：media_summary） | 2026-09-14 01:37（文件名日期 2026-09-13，与 mtime 不同源） | train-input-preflight（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/training-data-ledger-20261017.md` | 4663 B（4.6 KB） | C | r2 数据台账分折表正文（H1 标题自述） | 2026-10-18 13:08（文件名日期 2026-10-17，与 mtime 不同源） | training-data-ledger（顶层散文件，未归属实验目录） | 现行有效 | 无（未见取代记录） | 保留（新入库证据，不得删） |
| `docs/results/minicpm-base-upstream-comparison-20261016.json` | 4249 B（4.1 KB） | B | 官方仓元数据与权重比对（JSON 顶层键：files） | 2026-10-16 10:17 | minicpm-base-upstream-comparison（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/minicpm-postinit-origin-purpose-20261016.md` | 3776 B（3.7 KB） | A | 构造收尾调用核验与停止追查（H1 标题自述） | 2026-10-16 11:49 | minicpm-postinit-origin-purpose（顶层散文件，未归属实验目录） | 说明文档 | 无（未见取代记录） | 保留（被代码或正式文档引用） |
| `docs/results/remote-preparation-audit-20261016.json` | 3753 B（3.7 KB） | B | SSH 超时的准备审计记录（JSON 顶层键：status=partial） | 2026-10-16 10:09 | remote-preparation-audit（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（原引用者已移除，处置建议不变） |
| `docs/results/minicpm-base-source-rejection-preflight-20261016.json` | 2492 B（2.4 KB） | B | 无来源声明时基座被拒（JSON 顶层键：exit_code） | 2026-10-16 11:34 | minicpm-base-source-rejection-preflight（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（实验间互相引用） |
| `docs/results/evaluation-client-source-inventory-20261016.json` | 2278 B（2.2 KB） | B | 客户端源码运行前清单（JSON 顶层键：candidate_only） | 2026-10-16 09:58 | evaluation-client-source-inventory（顶层散文件，未归属实验目录） | 证据-可复核底稿 | 无（未见取代记录） | 保留（原引用者已移除，处置建议不变） |

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

## E. C 类专节（真零引用 5 / NOISY 降级 21）

### E.1 真零引用 5 个（第 4.6 节）

| 路径 | 体积 | 建议 |
|---|---|---|
| `docs/results/model-r1-effect-profile-20261018.json` | 52181 B（51.0 KB） | 保留（新入库证据，不得删） |
| `docs/results/model-r1-effect-profile-20261018.md` | 50187 B（49.0 KB） | 保留（新入库证据，不得删） |
| `docs/results/training-data-ledger-20261017.md` | 4663 B（4.6 KB） | 保留（新入库证据，不得删） |
| `docs/results/v4_1_phase2_source_aware_3k_coverage_first/stage_b_canary_gate_summary.json` | 2458 B（2.4 KB） | 保留待用户核定（门禁/准备结论唯一凭证） |
| `docs/results/v4_1_stage_d_sealed_test_release/preparation_summary.json` | 1297 B（1.3 KB） | 保留待用户核定（门禁/准备结论唯一凭证） |

前 3 个为随 `187822fe`、`36016711` 入库的新证据，不得删；后 2 个为门禁/准备结论的唯一凭证，须由用户核定。

### E.2 NOISY 降级 21 个（basename 命中取第 4.6 节）

| 路径 | 体积 | basename 命中 | 建议 |
|---|---|---|---|
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3411/README.md` | 7288 B（7.1 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/README.md` | 7287 B（7.1 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-coverage-fallback-v1-seed3413/README.md` | 7254 B（7.1 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/v4.1-phase2-coverage-first-v1-seed3411/README.md` | 7222 B（7.1 KB） | 45 | 不得判可删，NOISY 降级（basename 命中 45） |
| `docs/results/model_evidence/README.md` | 5982 B（5.8 KB） | 44 | 不得判可删，NOISY 降级（basename 命中 44） |
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

21 个 NOISY 放开规则后全部落 A 类，故「清理后 C 类 26 个」不等于「26 个可删」。

> 基线说明：审计采集于 `36016711`，该提交时 `docs/project-todo.md` 尚无 R2-REALTRAIN 条（`grep -c R2-REALTRAIN` = 0）；`c5ad8311` 新增该条、`21229565` 补记进展后，该条已把 `model-r1-effect-profile-20261018.*` 与两份数据台账列为证据位置。档位仍按审计清单如实照抄；文件数与体积按 2026-10-18 清理后的磁盘实测重算（见 B 节与 F 节）。

### E.3 档位重算差异登记（不改档位，逐条留证）

`check_index_v2.py` 已改为用仓库内引用（`git grep`）重算零引用判定（A/B 分界沿用审计 4.1 节，不随引用变化重算）并逐条比对。下列 6 处重算结果与本表抄录的审计归属不同：一律**保留审计档位不改**，在此逐条留证；脚本会断言「重算差异集合 = 本节登记集合」，任何未登记的新漂移都会让自检失败。

| # | 文件 | 表内档位 | 重算档位 | 差异原因 |
|---|---|---|---|---|
| 1 | evaluation-client-source-inventory-20261016.json | B | C | 唯一引用者 `evaluation-isolation-display-preflight-20261016.md` 已随 2026-10-18 清理移除 |
| 2 | evaluation-tokenizer-compatibility-materials-20261016/offline-validation.json | B | C | 唯一引用者 `evaluation-review-compatibility-repair-20261016.md` 已随 2026-10-18 清理移除 |
| 3 | remote-preparation-audit-20261016.json | B | C | 唯一引用者 `todo-preparation-progress-20261016.md` 已随 2026-10-18 清理移除 |
| 4 | model-r1-effect-profile-20261018.json | C | B | `c5ad8311` 在审计采集（17:11）之后把该文件登记为证据位置（`docs/project-todo.md`），已不是零引用 |
| 5 | model-r1-effect-profile-20261018.md | C | B | 同上 |
| 6 | training-data-ledger-20261017.md | C | B | 同上 |

本批引用清理还在「零引用边界」之外造成 2 处 A/B 分界漂移（两者仍被引用，故不属于上面的零引用差异集合；档位一律不改，沿用审计 4.1 节）：

| 文件 | 表内档位 | 按 B 节判据 | 引用来源 | 处置 |
|---|---|---|---|---|
| docs/results/model-inventory.md | 表=B | 应为 A | `docs/project-status.md`（本批新增引用） | 档位不改，沿用审计 4.1 节 |
| docs/results/model-gate-baseline-20260914.md | 表=B | 应为 A | `docs/project-status.md`（本批新增引用） | 档位不改，沿用审计 4.1 节 |

受影响的表述：E.1「真零引用 5 条」中第 4–6 项现已被 `docs/project-todo.md` 引用（按判据属 B），但三条的处置建议（保留、不得删）不因此改变；第 1–3 项在被引者删除后已变为零引用，处置建议仍按原登记保留，不据此判可删。上表 2 处 A/B 分界漂移同理：`docs/project-status.md` 只是本批新增的引用来源，档位与处置建议均不因此改变，自检脚本另有专门断言防止此类漂移静默。


## F. 机器自检

自检脚本：`/Users/pcoffeep/pi-workspace/mVllm_2-audit/check_index_v2.py`（仓库外）。清理后的期望值全部由磁盘推导：文件集来自 `os.walk('docs/results')`，逐文件字节数取 `os.path.getsize`，B 节分级汇总、C 类拆分、头部「移除 N 个文件，现存 M 个」均由该实测集重算；审计清单只用于 mtime、basename 命中和 A/B 分界这类清理无法改变的事实。档位里只有「是否零引用」用 `git grep` 在仓库内重算（A/B 分界沿用审计 4.1 节，不随引用变化重算）；6 处零引用边界差异与 2 处 A/B 分界漂移都逐条登记在 E.3，脚本分别断言「零引用重算差异集合 = E.3 零引用登记集合」和「A/B 分界漂移已登记」。

体积与汇总数字由两个同步脚本写入，均为 `os.path.getsize` 现场计算、不含手改：`sync_index_sizes.py`（主表逐文件体积，含同一路径在 E 节重复出现的情形）与 `sync_index_totals.py`（头部与 A 节计数、B 节 A/B/C/合计、自检句、MiB 换算、C 类构成句、C 节行数）。清理前的 `check_index.py` 在同一目录保留为历史基线（其 141 行期望值已不适用于当前文件集，不再执行）。

下面是本工作区当前代码状态下的**真实运行输出**（未删改、未重新排版）：

```
命令（仓库根 `/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2` 下执行）：
$ python3 /Users/pcoffeep/pi-workspace/mVllm_2-audit/check_index_v2.py
退出码：0

PASS 索引文件自身在磁盘上
磁盘实测：docs/results 共 118 个文件（含 INDEX.md），主表应覆盖 117 个，合计 12,384,047 B
== A. 主表行数与字段 ==
PASS 主表数据行数 = 磁盘实际文件数  -> 主表 117 行 / 磁盘 117 个
PASS 每行恰 9 个字段（无多余分隔符）
PASS 9 列逐格非空（空单元格数 = 0）  -> 空单元格 0 处 []
== B. 路径与磁盘文件集一一对应 ==
PASS 无重复路径  -> []
PASS 仅在 INDEX 出现的路径（应为空集）  -> []
PASS 磁盘上存在但未入主表的路径（应为空集）  -> []
路径集合 diff：only_in_index=0，only_on_disk=0，交集=117
== C. 体积逐条等于磁盘实测 ==
PASS 体积列逐条等于 os.path.getsize  -> []
== D. 档位 / 时点仍与审计 4.5 节一致（仅对存活文件） ==
PASS 每个存活文件在审计 4.5 节都有对应行  -> []
PASS 档位逐条照抄审计 4.5 节  -> []
PASS 档位只出现 A/B/C
PASS 时点以审计 4.5 节 mtime 开头  -> []
== D2. 零引用重算（A/B 沿用审计 4.1 节，不随引用变化重算） ==
NOISY（改用完整路径判据）的 basename：['README.md(basename 命中 43)', 'dataset_info.json(basename 命中 41)', 'evaluation_summary.json(basename 命中 27)', 'experiment_contract.json(basename 命中 23)', 'manifest.json(basename 命中 106)', 'run_identity.json(basename 命中 19)', 'summary.json(basename 命中 74)', 'trainer_state.json(basename 命中 26)', 'training_run_manifest.json(basename 命中 17)', 'verification.md(basename 命中 18)']
零引用判定与 INDEX 档位不一致：6 处
  漂移 docs/results/evaluation-client-source-inventory-20261016.json 表=B 重算=C 引用来源=[]
  漂移 docs/results/evaluation-tokenizer-compatibility-materials-20261016/offline-validation.json 表=B 重算=C 引用来源=[]
  漂移 docs/results/model-r1-effect-profile-20261018.json 表=C 重算=B 引用来源=['docs/project-todo.md']
  漂移 docs/results/model-r1-effect-profile-20261018.md 表=C 重算=B 引用来源=['docs/project-todo.md']
  漂移 docs/results/remote-preparation-audit-20261016.json 表=B 重算=C 引用来源=[]
  漂移 docs/results/training-data-ledger-20261017.md 表=C 重算=B 引用来源=['docs/project-todo.md']
PASS 零引用边界重算差异 = INDEX E.3 逐条登记集合（不含 A/B 分界漂移）  -> 重算 6 / 登记 6；未登记 []；登记多余 []
PASS E.3 登记的 2 个 A/B 分界漂移确实被 docs/*.md 等 A 类来源引用（仍是表内 B 档）  -> 实测应按 A 计：['docs/results/model-inventory.md', 'docs/results/model-gate-baseline-20260914.md']
PASS 该 2 个文件在主表仍标 B（档位不随引用变化重算）  -> []
PASS 上述 A/B 分界漂移已逐条登记在 E.3 A/B 分界表  -> 登记 ['docs/results/model-gate-baseline-20260914.md', 'docs/results/model-inventory.md'] / 期望 ['docs/results/model-gate-baseline-20260914.md', 'docs/results/model-inventory.md']
PASS E.2 恰 21 条（放开 basename 后全部落 A 的断言基数）  -> 21 条
PASS E.2 的 21 个 NOISY 条目在放开 basename 规则后全部落 A 类  -> 未落 A：[]
== E. 分级计数与体积累加（由磁盘重算） ==
重算结果：A=38/8,287,868 B=53 3,929,090 C=26 167,089
PASS B 节 A 行 = 磁盘实测计数与体积  -> 表=38/8,287,868 B 实测=38/8,287,868
PASS B 节 B 行 = 磁盘实测计数与体积  -> 表=53/3,929,090 B 实测=53/3,929,090
PASS B 节 C 行 = 磁盘实测计数与体积  -> 表=26/167,089 B 实测=26/167,089
PASS B 节合计行 = 磁盘实测  -> 表=117/12,384,047 B 实测=117/12,384,047
PASS A+B+C = 主表行数  -> 117 vs 117
PASS B 节自检句与重算一致
== F. 状态词表与「当前有效」 ==
PASS 状态只用词表内 7 个值  -> []
PASS 「现行有效」正好 7 条且与 D 节一致  -> 实测 7 条
PASS D 节「当前有效」表格行数 = 7  -> 7
PASS D 节 7 条路径与预期一致
PASS D 节 7 条路径在磁盘上真实存在
== G. C 类专节（保留清单 + 磁盘重算） ==
PASS E 节总条数 = C 档计数  -> 26 vs 26
PASS E 节集合 = 主表 C 档集合
PASS C_NEW / C_GATE 5 条全部仍在 E 节  -> []
PASS E.1 恰为真零引用 5 条（C_NEW 3 + C_GATE 2）  -> ['docs/results/model-r1-effect-profile-20261018.json', 'docs/results/model-r1-effect-profile-20261018.md', 'docs/results/training-data-ledger-20261017.md', 'docs/results/v4_1_phase2_source_aware_3k_coverage_first/stage_b_canary_gate_summary.json', 'docs/results/v4_1_stage_d_sealed_test_release/preparation_summary.json']
PASS E.2 恰为剩余 NOISY 条目  -> 21 条
PASS E.1+E.2 体积 = C 档体积  -> 110,786+56,303 vs 167,089
PASS B 节 C 类构成句由磁盘重算得出
PASS E.2 命中数仍取审计 4.6 节（存活文件可核对）  -> []
PASS C_NEW 3 条建议原文正确
PASS C_GATE 2 条建议原文正确
== H. 单元格长度 ==
PASS 是什么 ≤ 40 字符  -> []
PASS 时点 ≤ 55 字符  -> []
PASS 建议 ≤ 40 字符  -> []
PASS 体积 ≤ 30 字符  -> []
PASS 档位 ≤ 30 字符  -> []
PASS 状态 ≤ 30 字符  -> []
PASS 对应实验 中文字符 ≤ 25  -> []
PASS 对应实验 总长度 ≤ 80 字符  -> max=62
PASS 取代者 中文字符 ≤ 25  -> []
PASS 取代者 总长度 ≤ 60 字符  -> max=41
== I. 无 Markdown 链接 ==
PASS INDEX.md 内 Markdown 链接数 = 0  -> []
PASS 无空链接 / 占位链接
== J. 头部变更记录与仓库状态 ==
PASS 头部清理变更记录 N/M = 磁盘实测推导（移除 = 141 基线 - 现存数；现存 = 主表行数）  -> 表=移除 24 个文件，现存 117 个 推导=移除 24 个 / 现存 117 个
git status 已暂存删除（仅用于一致性核对，不硬编码条数）：50 条
PASS 已删除路径均不在磁盘上且不在主表（磁盘侧）  -> []
PASS 已删除路径均不在磁盘上且不在主表（主表侧）  -> []
PASS grep -c "^### " docs/project-todo.md = 40  -> 40
PASS git diff --check 无空白/冲突提示

结果：共 56 项检查，失败 0 项
```

## G. 偏差

无未解释偏差。117 个存活文件的体积逐条等于磁盘实测（F 节 C 段输出「体积列逐条等于 os.path.getsize  -> []」），路径集合与磁盘文件集双向一致（only_in_index=0，only_on_disk=0）。

已解释的偏差（供复核）：

- 本轮引用清理改写了 11 个仍存活的 `docs/results/` 文件正文（`version-control-migration/verification.md`、`version-control-migration/entrypoint-map.md`、`version-control-migration/object-mapping.yaml`、`version-control-migration/source-inventory.yaml`、`model-r1-effect-profile-20261018.md`、`model-r1-effect-profile-20261018.json`、`model-inventory.md`、`model-gate-baseline-20260914.md`、`evaluation-tokenizer-materials-20261015.md`、`evaluation-tokenizer-hf-assets-20261015.json`、`ollama-tokenizer-verification-20261015.md`），其体积因此不再等于审计第 4.5 节快照值；主表体积按清理后磁盘实测填写，B 节汇总同源。逐文件实测偏差：verification.md +125 B、entrypoint-map.md +425 B、object-mapping.yaml +121 B、source-inventory.yaml +95 B、model-r1-effect-profile-20261018.md +13 B、model-r1-effect-profile-20261018.json +55 B、model-inventory.md +82 B、model-gate-baseline-20260914.md +82 B、evaluation-tokenizer-materials-20261015.md +57 B、evaluation-tokenizer-hf-assets-20261015.json +210 B、ollama-tokenizer-verification-20261015.md +39 B。
- 档位（A/B/C）与 mtime 仍照抄审计清单，不因清理重算；被删文件只影响 A/B/C 计数，判据不变。
- 单元格长度与「（顶层散文件，未归属实验目录）」后缀是本索引自定的书写约定，**非任务书要求**；本表「是什么」按字符数 ≤40 执行；「对应实验」「取代者」两列以实验标识符（如 `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3`）和文件路径为主体，另加本索引自定的固定后缀，按中文字符数 ≤25 校验（两列当前最长分别为 62 / 41 字符，均为拉丁标识）。
- 审计清单置于仓库外，本文件只以行内代码记录其路径；仅引用其判据与数值，未复制审计正文段落，未建立链接。
