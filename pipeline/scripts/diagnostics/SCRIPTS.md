<!-- DOCUMENT-CONTRACT
Purpose: 登记 2026-10-18 从诊断分支迁入的 14 个 2026-07 诊断脚本、6 个明确未迁脚本的索引与理由，以及本目录的命名豁免。
Scope: 仅覆盖 pipeline/scripts/diagnostics/ 目录；不描述主链数据/训练/服务入口。
Must Preserve:
- 迁入脚本与 bcdf4f36 正文逐字节一致，仅头部加「迁入说明」块；本目录当期未接入主链，仅供历史证据复核。
- 未迁脚本必须写明「main 是否有等价物（检查命令与结论）」与「不迁理由」，且不得把判断写成已证事实。
Non-goals:
- 不记录批次执行过程、体积统计或 INDEX 档位（见 docs/results/INDEX.md 与仓库外执行报告）。
-->

# pipeline/scripts/diagnostics — 诊断脚本索引

本目录的 14 个脚本是 **2026-10-18 从 `codeup/diagnostics/data-visual-audit` @ `bcdf4f36` 迁入**的 2026-07 诊断工具，**仅供历史证据复核，当期未接入主链**（不属现行数据/训练/服务入口，不被任何现行流程调用）。

- **正文逐字节未改**：14 个文件与 `bcdf4f36` 上同名文件正文逐字节一致，仅在头部加「迁入说明」注释块（来源提交、原始提交日期、失效路径、未随迁依赖、迁移已知影响）。
- **数据产物未随迁**：正文原先读写的 `finetune/results/diagnostics/` 下输入/输出数据、模型目录与日志均未迁入，留在 `bcdf4f36` + `archive-diagnostics-20261018.bundle`。
- **可读不可跑**：脚本头部说明块已列出各文件的失效路径与已知不可用项；如需重跑，必须先补齐数据并修复路径/导入（见下表「已知失效/不可用项」）。
- **shebang 不在首行**：说明块加在最前，`#!/usr/bin/env python3` 落到第 2 行之后；`python <file>` 可正常解析，`./<file>` 会由 shell 解释。

## 1. 迁入脚本索引（14）

| 脚本 | 用途 | 原路径（`bcdf4f36` 上） | 已知失效/不可用项 |
|---|---|---|---|
| `prepare_visual_audit.py` | 阶段 2 视觉盲审准备：对 `val_manifest` 做模型推理并按分层抽样挑 32 条用于人工盲审 | `finetune/results/diagnostics/visual_audit/prepare_visual_audit.py` | 失效路径 `data/04_frames`；未随迁 `visual_audit/val_manifest.json`、`visual_audit/sampling_strategy.json`；`Path(__file__).resolve().parents[4]` 迁入后已不指向仓库根 |
| `generate_preparation_artifacts.py` | 阶段 2 视觉盲审准备：生成不依赖 GPU 的工件 | `finetune/results/diagnostics/visual_audit/generate_preparation_artifacts.py` | 失效路径 `data/06_merged/fold_0_val.json`、`data/07_metadata/subvideos_meta.label_reviewed.json`、`data/07_metadata/video_meta.json`、`data/03_subvideos/video_0001_focus_3s_65pct.mp4`；未随迁 `data_audit/training_distribution.json`；`parents[4]` 已不指向仓库根 |
| `export_review_frames.py` | 导出验证运行时实际使用的均匀采样帧 | `finetune/results/diagnostics/visual_audit/export_review_frames.py` | 失效路径 `data/03_subvideos`；未随迁 `visual_audit/sample_manifest.json`、`visual_audit/frames`；`parents[4]` 已不指向仓库根 |
| `finalize_visual_audit.py` | 合并两轮审查决定并生成第二阶段审计报告 | `finetune/results/diagnostics/visual_audit/finalize_visual_audit.py` | 说明块记「失效路径：无」「未随迁：无」（仅需人工审查决定 json，即在 `bcdf4f36` 上） |
| `verify_frame_mapping_alignment.py` | 校验落盘训练映射与推理期采样帧一致 | `finetune/results/diagnostics/visual_audit/verify_frame_mapping_alignment.py` | 说明块记「失效路径：无」「未随迁：无」 |
| `build_review_montages.py` | 由精确帧 contact sheet 拼装带标注的紧凑 montage | `finetune/results/diagnostics/control_experiments/build_review_montages.py` | 说明块记「失效路径：无」「未随迁：无」 |
| `generate_distribution.py` | 数据审计：生成 `training_distribution.json`（样本级/源视频级统计、裁剪方式与标签相关性、区间标签检查） | `finetune/results/diagnostics/data_audit/generate_distribution.py` | 失效路径 `data/06_merged/fold_0_train.json`、`data/06_merged/fold_0_val.json`、`data/07_metadata/subvideos_meta.label_reviewed.json`、`data/07_metadata/video_meta.json`；未随迁 `data_audit/` |
| `prepare_control_experiments.py` | 准备 source-paired / interval-balanced 数据与 E 组训练配置 | `finetune/results/diagnostics/prepare_control_experiments.py` | 失效路径 `data/06_merged/fold_0_train.json`；未随迁 `control_experiments/` |
| `prepare_minimal_overfit.py` | 构建确定性 16 例记忆数据集与训练配置 | `finetune/results/diagnostics/prepare_minimal_overfit.py` | 失效路径 `data/06_merged/fold_0_train.json`；未随迁 `minimal_overfit/` |
| `run_checkpoint_comparison.py` | 串联 merge → evaluate → score → summarize 的 checkpoint 序列对比 | `finetune/results/diagnostics/run_checkpoint_comparison.py` | 失效路径 `models/minicpmv4_5`、`data/06_merged`；未随迁 `checkpoint_comparison/` 与 `run_dataset_evaluation.py`；正文写死的 `finetune/results/diagnostics/score_diagnostic_evaluation.py` 已失效（该脚本已迁至本目录同名文件） |
| `run_control_experiments.py` | 跑带门禁的 E 组受控训练并做任务级模型选择 | `finetune/results/diagnostics/run_control_experiments.py` | 失效路径 `models/minicpmv4_5`；未随迁 `control_experiments/`、`checkpoint_comparison/full_run_exact/final` |
| `run_minimal_overfit_postprocess.py` | minimal-overfit 的 merge → score → counterfactuals 后处理链 | `finetune/results/diagnostics/run_minimal_overfit_postprocess.py` | 失效路径 `data/diagnostic_overfit.json`、`models/minicpmv4_5`；未随迁 `minimal_overfit/` 与 `run_dataset_evaluation.py`；正文写死的 `score_diagnostic_evaluation.py`、`run_visual_counterfactuals.py` 路径已失效（两者均已迁至本目录同名文件） |
| `run_visual_counterfactuals.py` | 生成受控帧变体并评估视觉敏感性 | `finetune/results/diagnostics/run_visual_counterfactuals.py` | 说明块记「失效路径：无」；但正文 `from finetune.results.diagnostics.*` 导入在迁入后不可解析（`run_dataset_evaluation.py` 未迁、`score_diagnostic_evaluation.py` 已落入本目录），故不可执行 |
| `score_diagnostic_evaluation.py` | 对诊断评测 JSONL 计算任务级与来源级指标 | `finetune/results/diagnostics/score_diagnostic_evaluation.py` | 说明块记「失效路径：无」「未随迁：无」 |

## 2. 未迁清单（6 个脚本 + 1 个测试）

检查命令均在仓库根执行（`HEAD` = 迁入批之后）。「main 是否有等价物」一栏区分**结论来源**：命令实测为事实，功能重叠判断标注为「判断」。

| 未迁文件（`bcdf4f36` 上路径） | main 是否已有等价物（检查命令与结论） | 不迁理由 |
|---|---|---|
| `finetune/results/diagnostics/control_experiments/prepare_visual_gate.py` | `git grep -ln 'visual_gate' HEAD -- '*.py' ':!pipeline/scripts/diagnostics'` → 0 命中；`git ls-tree -r --name-only HEAD \| grep prepare_visual_gate` → 同名文件 0 | 功能与本目录 `prepare_visual_audit.py` 重叠（**判断**，非已证事实）：两者都做盲审抽样与准备工件，迁入会造成两份等价实现，故不迁；`bcdf4f36` + bundle 可溯源 |
| `finetune/results/diagnostics/control_experiments/finalize_visual_gate.py` | 同上（`visual_gate` 0 命中，`finalize_visual_gate` 同名 0） | 功能与本目录 `finalize_visual_audit.py` 重叠（**判断**，非已证事实），理由同上 |
| `finetune/results/diagnostics/control_experiments/build_temporal_reindexed_control_dataset.py` | 无对应检查项：属一次性数据集构建 | 一次性 E 组数据集构建脚本，其产物（`control_experiments/data/` 下 json）未迁，脚本单独留存无使用价值 |
| `finetune/results/diagnostics/control_experiments/run_after_checkpoint.sh` | 无对应检查项：属训练机串行编排壳 | 绑定训练机路径与串行流程，离开该机器与数据即不可用 |
| `finetune/results/diagnostics/audit_training_inference_alignment.py` | `git grep -n '_regularize_video_frame' HEAD` → 0 命中（该符号在 main 已不存在） | 正文 import `finetune.validation.model_runtime._regularize_video_frame`，迁入即 ImportError；同一「训练/推理预处理对齐」命题由 main 的 `tests/test_dev_eval_preprocess_alignment.py` 覆盖 |
| `finetune/results/diagnostics/run_dataset_evaluation.py` | `ls finetune/validation/run_evaluation.py` → 存在 | 与 main `finetune/validation/run_evaluation.py` 评估链功能重复，不迁以避免双份评估实现 |
| `tests/test_diagnostic_scorer.py` | 被唯一被测对象 `score_diagnostic_evaluation.py` 已迁入本目录（`ls pipeline/scripts/diagnostics/score_diagnostic_evaluation.py` → 存在） | 测试用 `importlib.util.spec_from_file_location` 硬编码 `finetune/results/diagnostics/score_diagnostic_evaluation.py`，迁入须改代码；且放进 `tests/` 会改变 pytest 收集基线（3286），故未迁。如需恢复，须先在训练机跑通再单独调整基线 |

## 3. 命名豁免说明（已知规范偏差）

本目录 14 个文件**保留 `bcdf4f36` 上的原文件名**，未按仓库级命名规范 `<阶段前缀>_<动作>_<对象>.py` 改名：

1. **溯源优先**：迁入批的核心验收是「与源提交正文逐字节可比对」，保持同名才能用 `diff <(git show bcdf4f36:<原路径>) <(tail -n +<N> <文件>)` 直接复核；改名会同时破坏脚本间互相引用与这份可比对性。
2. **动作用词表不含其动词**：`generate_` / `finalize_` / `score_` / `export_` / `verify_` 均不在仓库动作用词表（build_ / prepare_ / run_ / validate_ / audit_ / freeze_ / materialize_ / monitor_ / smoke_ / route_ / rebuild_ / manage_）内，按规范改名等于重写命名，超出「只加说明块」的授权范围。
3. **已知偏差的处置**：本目录当期未接入主链，属历史证据留存；若将来要正式纳入主链，应先按规范改名、修路径与导入，再单独提交——不做「改一半」的折中。
