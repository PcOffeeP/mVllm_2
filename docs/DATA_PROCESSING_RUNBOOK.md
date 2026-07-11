# 数据处理与训练运行手册

本文件是本项目从零开始构建训练数据的唯一运行手册。适用起点为：只有原始视频、原始 CSV 标注和项目代码。所有命令从项目根目录运行；完整视频处理、MiniCPM 选帧和模型训练在训练电脑执行。

## 1. 核心原则

1. 划分以源视频为单位，先冻结，再生成子视频；不得在人工审查后重新划分。
2. 每个训练子视频必须有实际 MP4、实际抽帧图和 `actual_frame_mapping`。`fracture_between` 只对应这份实际映射。
3. 人工 `approved` 标签是当前训练样本的最终标签；源视频标签用于生成下一轮媒体和追溯，不能静默覆盖人工标签。
4. `dropped` 不进入训练；`needs_regenerate` 不得进入训练，必须完成增量生成和复审后才可转为 `approved` 或 `dropped`。
5. 全量人工审查完成后，只能进行增量复审，不能因为少量问题重做全体 approved 样本。

## 2. 目录与关键文件

| 阶段 | 文件或目录 | 角色 |
|---|---|---|
| 输入 | `data/01_videos/` | 原始视频 |
| 输入 | `data/02_annotations/all_videos_tag.csv` | 源视频标签：时间、帧号、类型、位置等 |
| 冻结源元数据 | `data/07_metadata/video_meta.json` | CSV 规范化后的源标签；子视频生成使用它 |
| 冻结划分 | `data/05_splits/*.json` | 3-fold train/val 与 test 的源视频级划分 |
| 候选媒体 | `data/03_subvideos/`、`data/04_frames/` | 子视频 MP4 与模型实际抽帧图 |
| 候选元数据 | `data/07_metadata/subvideos_meta.json` | 裁剪、抽帧映射、自动标签、fold 信息 |
| 人工基线 | `data/07_metadata/subvideo_train_review_decisions.json` | 全量人工审查决策；增量轮次中只读保留 |
| 增量队列 | `data/07_metadata/incremental_review_queue_metadata.json` | 仅本轮需重审的样本清单 |
| 最终决策 | `data/07_metadata/subvideo_train_review_decisions_final.json` | 基线与所有 delta 安全合并后的决策 |
| 最终元数据 | `data/07_metadata/subvideos_meta.label_reviewed.json` | 唯一允许输入训练样本导出的 metadata |
| 训练数据 | `data/06_merged/` | 各 fold 的 ShareGPT 样本、测试输入、统计信息 |

## 3. 从零开始：源标签与划分

### 3.1 准备输入

确认原始视频文件名与 CSV 的 `video_path` 一致，CSV 至少包括断裂时间、断裂帧数、断裂模式、断裂位置、`has_fracture` 和 `is_abnormal`。

### 3.2 生成源元数据和固定划分

```bash
python pipeline/scripts/dataset_manager.py \
  --csv data/02_annotations/all_videos_tag.csv \
  --video-dir data/01_videos \
  --metadata-dir data/07_metadata \
  --splits-dir data/05_splits \
  --seed 42
```

此命令是新数据集初始化步骤，会写出 `video_meta.json`、`data/05_splits/*.json` 和 `test_manifest_sha256.json`。一旦进入人工审查，必须冻结这些文件；后续只更新源标签用于增量媒体生成，不重新执行划分。

## 4. 从零开始：生成候选子视频与实际帧

先在训练电脑做小样本烟雾测试：

```bash
python pipeline/scripts/subvideo_builder.py \
  --model models/minicpmv4_5 \
  --sample-size 10 \
  --sample-output-dir data/sample_subvideos
```

确认 sample manifest、MP4 和帧图正确后，完整生成：

```bash
python pipeline/scripts/subvideo_builder.py \
  --model models/minicpmv4_5
```

输出的 `subvideos_meta.json`、MP4、帧图必须一同保存。不要只同步 metadata；没有媒体就无法进行可信人工审查。

## 5. 全量人工审查：建立历史基线

启动 UI：

```bash
streamlit run pipeline/scripts/review_subvideos_app.py -- \
  --metadata data/07_metadata/subvideos_meta.json \
  --output data/07_metadata/subvideo_train_review_decisions.json
```

人工对每条非 `neg_before` 子视频设置：

- `approved`：可修改 `has_fracture`、`type`、`location`、`fracture_between`；这些人工值是训练标签。
- `dropped`：排除训练。
- `needs_regenerate`：不能进入训练，必须进入第 6 节。

`neg_before` 是断裂前负样本，系统自动批准，无需生成单独人工决策。

## 6. 增量复审：只处理未完成或明确冲突样本

### 6.1 生成只读复审队列

默认只选 `needs_regenerate`。若本轮还要复核 approved 的帧区间冲突，显式加入开关：

```bash
python pipeline/scripts/prepare_incremental_review_queue.py \
  --metadata data/07_metadata/subvideos_meta.json \
  --decisions data/07_metadata/subvideo_train_review_decisions.json \
  --video-meta data/07_metadata/video_meta.json \
  --output-metadata data/07_metadata/incremental_review_queue_metadata.json \
  --output-csv data/07_metadata/incremental_review_queue.csv \
  --include-approved-interval-conflicts
```

该命令不改历史决策、不改 split、不生成媒体。

### 6.2 只为队列重新生成媒体

在训练电脑创建新的版本目录；不要覆盖历史 `data/03_subvideos` 或 `data/04_frames`：

```bash
python pipeline/scripts/materialize_incremental_review_media.py \
  --queue data/07_metadata/incremental_review_queue_metadata.json \
  --video-meta data/07_metadata/video_meta.json \
  --output-root data/08_incremental_review/round_01 \
  --output-metadata data/07_metadata/incremental_review_round_01_metadata.json \
  --report data/07_metadata/incremental_review_round_01_report.json \
  --model models/minicpmv4_5
```

默认只生成 `baseline_needs_regenerate`。如需同时生成 approved 帧区间冲突样本：

```bash
--reasons baseline_needs_regenerate approved_interval_conflict
```

若生成报告含失败项，不要对缺媒体队列启动 UI。失败项必须先有明确处置：重新生成，或由数据负责人明确决定 `dropped`。后一种情况在第 6.4 节追加为带审计记录的 delta。

### 6.3 使用同一 UI 审查增量媒体

```bash
streamlit run pipeline/scripts/review_subvideos_app.py -- \
  --metadata data/07_metadata/incremental_review_round_01_metadata.json \
  --incremental-delta \
  --output data/07_metadata/incremental_review_delta_decisions.json
```

增量模式只输出本轮 delta，不会覆盖历史基线。界面会显示历史决策和队列原因作为只读上下文。

### 6.4 将无法生成且已确认剔除的样本追加到 delta（按需）

本轮若存在“无法形成可审查映射”的生成失败，且数据负责人决定剔除，**先完成所有实际生成媒体的人工审查**，再基于最新 UI delta 运行：

```bash
python pipeline/scripts/append_incremental_failure_drops.py \
  --baseline data/07_metadata/subvideo_train_review_decisions.json \
  --delta data/07_metadata/incremental_review_delta_decisions.json \
  --queue data/07_metadata/incremental_review_queue_metadata.json \
  --report data/07_metadata/incremental_review_round_01_report.json \
  --output data/07_metadata/incremental_review_delta_decisions_resolved.json
```

这一步只将报告中的失败样本显式标为 `dropped`，并写入失败原因；它不覆盖历史基线。若所有生成都成功，或失败项将重新生成，则跳过本节，直接使用 UI 输出的 delta。

### 6.5 安全合并最终 delta

当第 6.4 节执行过时，合并 `*_resolved.json`；否则合并 UI 输出的 delta：

```bash
python pipeline/scripts/merge_incremental_review_decisions.py \
  --baseline data/07_metadata/subvideo_train_review_decisions.json \
  --delta data/07_metadata/incremental_review_delta_decisions_resolved.json \
  --queue data/07_metadata/incremental_review_queue_metadata.json \
  --output data/07_metadata/subvideo_train_review_decisions_final.json
```

默认不允许替换历史 `approved`。确实需要推翻已批准样本时，人工复审记录必须写明原因，且合并时显式传入：

```bash
--allow-approved-supersede
```

每次增量轮次使用新的 `round_XX`、queue、delta 和 final 文件；不要复用输出路径。一次已完成的历史人工审查不需要重做：只处理本轮 `needs_regenerate`、媒体失败或明确要求复核的样本。

## 7. 构建最终训练 metadata

先审计最终决策，确认没有未解决项：

```bash
python pipeline/scripts/audit_review_decisions.py \
  --decisions data/07_metadata/subvideo_train_review_decisions_final.json \
  --subvideos-meta data/07_metadata/subvideos_meta.json \
  --output-dir data/07_metadata/final_review_audit
```

严格应用最终决策：

```bash
python pipeline/scripts/apply_review_decisions.py \
  --metadata data/07_metadata/subvideos_meta.json \
  --decisions data/07_metadata/subvideo_train_review_decisions_final.json \
  --output data/07_metadata/subvideos_meta.reviewed.json \
  --strict
```

再把人工 corrected labels 覆盖为最终训练标签：

```bash
python pipeline/scripts/apply_label_corrections.py \
  --metadata data/07_metadata/subvideos_meta.reviewed.json \
  --output data/07_metadata/subvideos_meta.label_reviewed.json
```

`--strict` 失败时不得绕过；应回到第 6 节，完成所有 `needs_regenerate` 或将其标为 `dropped`。

## 8. 导出训练数据与质量门

```bash
python scripts/validate_no_oob.py \
  --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json

python pipeline/scripts/training_sample_builder.py \
  --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json \
  --video-meta data/07_metadata/video_meta.json \
  --splits-dir data/05_splits \
  --output-dir data/06_merged \
  --seed 42

python pipeline/scripts/quality_check.py \
  --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json \
  --merged-dir data/06_merged

python pipeline/scripts/freeze_data_version.py \
  --merged-dir data/06_merged \
  --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json \
  --video-meta data/07_metadata/video_meta.json \
  --splits-dir data/05_splits \
  --subvideo-dir data/03_subvideos \
  --lock data/07_metadata/data_version_lock.json
```

注意：当前人工标签优先策略下，`review_subvideo_labels.py` 不应作为会覆盖人工类型/位置判断的最终门；它只能用于检查媒体、映射或源标签诊断。最终训练门使用审计、严格决策应用、越界检查和质量检查。

## 9. 训练

只有第 8 节所有命令成功后，才在训练电脑启动训练。分别运行三个 fold：

```bash
cd finetune

python train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml
python train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold1.yaml
python train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold2.yaml
```

训练完成后，基于训练电脑实际产出的 checkpoint、adapter、评测预测和指标做验收；训练 loss 下降不能单独证明断裂识别效果。

## 10. 禁止事项

- 人工审查后不要重新运行 `dataset_manager.py` 来重新划分当前训练集。
- 不要把增量 UI 的输出指向历史完整决策文件。
- 不要使用 `--no-strict` 生成正式训练数据。
- 不要把 `needs_regenerate`、未审查样本或缺媒体样本带入训练。
- 不要用源视频旧标签静默覆盖已 approved 的人工标签。
