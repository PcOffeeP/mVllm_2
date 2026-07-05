# Training Data Review Pipeline Implementation

## Goal

Refactor the training-data generation chain so generated subvideos are not converted directly into ShareGPT JSON. The new chain must insert a manual media review step and an automatic label review step after subvideo generation.

The intended chain is:

1. `dataset_manager.py`: CSV annotations to `video_meta.json` and split files.
2. `subvideo_builder.py`: non-test videos to candidate mp4 subvideos, sampled frame folders, and `subvideos_meta.json`.
3. Manual review: humans inspect mp4 files and sampled frame folders, then delete both media artifacts for bad samples.
4. `prune_reviewed_subvideos.py`: remove only samples whose mp4 and frame folder were both deleted.
5. `repair_review_media.py`: repair inconsistent manual-review states where only one artifact is missing.
6. `review_subvideo_labels.py`: verify labels against source metadata and generation logic.
7. `training_sample_builder.py`: convert reviewed metadata to ShareGPT JSON.
8. Existing validation and freeze steps.

## Non-Goals

- Do not change the split algorithm unless required for compatibility.
- Do not create a manual review UI.
- Do not keep the tail-contamination workflow in the main path.
- Do not infer labels from frame pixels. The label review is metadata/contract validation.

## Current Files

Main files to update:

- `README.md`
- `pipeline/scripts/subvideo_builder.py`
- `pipeline/scripts/training_sample_builder.py`
- `pipeline/scripts/quality_check.py`
- `scripts/validate_no_oob.py` if it assumes only `subvideos_meta.json`
- `tests/test_tail_review.py`
- `tests/test_frame_contract.py`

Scripts to remove from the documented/main workflow:

- `pipeline/scripts/audit_tail_contamination.py`
- `pipeline/scripts/apply_tail_review_decisions.py`
- `pipeline/scripts/prune_missing_review_media.py`

The old scripts may be deleted if no tests or imports still depend on them. If deletion is too disruptive, leave them unreferenced and add a deprecation note in code comments.

## Dataset Manager Changes

Keep `dataset_manager.py` focused on:

- reading CSV annotations,
- producing `data/07_metadata/video_meta.json`,
- producing `data/05_splits/*.json`.

`inventory_report.json`, `stratified_split_decision_log.json`, and `frame_index_validation.json` should not be required by the main pipeline. Prefer one of these implementation options:

- make them optional behind `--debug-report`, or
- leave generation in place for now, but ensure no downstream script depends on them.

The acceptance criterion is that the documented main chain depends only on `video_meta.json` and split JSON files from step 1.

## Subvideo Builder Changes

`subvideo_builder.py` should become the generator of a reviewable candidate package:

- Skip all `test` videos.
- Generate mp4 media for selected train/val subvideos.
- Generate sampled frame images by default into `data/04_frames/<subvideo_id>/`.
- Write `frame_paths` for each generated sample.
- Preserve `actual_frame_mapping`, `processor_fingerprint`, `processor_info`, `crop_type`, `source_video`, `start_time`, `end_time`, `start_frame`, `end_frame`, `has_fracture`, `fracture_between`, `type`, and `location`.

CLI behavior:

- `--extract-frames` should no longer be required for normal operation.
- Keep `--extract-frames` as a backward-compatible no-op or explicit true flag.
- If adding a disabling option is useful, name it `--no-extract-frames`, but the default must produce frame folders.

Be careful with full-video samples:

- Their `video_path` may point to `data/01_videos/<video_id>.mp4`.
- Their frame folder still belongs under `data/04_frames/<subvideo_id>/`.
- Manual deletion of a full-video sample should not require deleting the source video. It should be represented by deleting that sample's frame folder and a review marker, or by using a copied review mp4 if the implementation chooses to materialize full samples.

Recommended resolution for full-video deletion:

- Do not ask users to delete files under `data/01_videos/`.
- For full samples, treat `data/04_frames/<subvideo_id>/` plus an optional review-side marker as the deletable review artifact.
- If the implementation needs strict "mp4 plus frames both deleted" semantics for all samples, materialize full review mp4 files under `data/03_subvideos/<subvideo_id>.mp4` and point `video_path` there.

## Manual Review Semantics

The user-approved rule is:

- Both mp4 and frame folder exist: keep the sample.
- Both mp4 and frame folder are missing: treat as manually deleted and remove from reviewed metadata.
- Only mp4 missing or only frame folder missing: fail with an inconsistency error.

The implementation must make this rule explicit in code and tests.

## New Script: prune_reviewed_subvideos.py

Add `pipeline/scripts/prune_reviewed_subvideos.py`.

Suggested CLI:

```bash
python3 pipeline/scripts/prune_reviewed_subvideos.py \
  --input-meta data/07_metadata/subvideos_meta.json \
  --output-meta data/07_metadata/subvideos_meta.reviewed.json \
  --report data/07_metadata/manual_review_prune_report.json
```

Behavior:

- Load metadata payloads shaped either as `{"subvideos": [...]}` or a raw list.
- For each subvideo, resolve the mp4 path from `video_path`.
- Resolve the frame directory as `data/04_frames/<subvideo_id>`.
- Classify each row as `kept`, `dropped`, or `inconsistent`.
- Drop only rows where both artifacts are missing.
- Preserve top-level metadata such as `candidates`, `exclusions`, `seed`, and `preprocessor_fingerprint` where practical.
- If any inconsistent rows exist, exit non-zero and do not write the reviewed metadata unless an explicit `--allow-partial-report` is provided.
- Always write or print a report listing inconsistent rows with enough information to repair them.

Report fields should include:

- `subvideo_id`
- `source_video`
- `video_path`
- `frame_dir`
- `video_exists`
- `frame_dir_exists`
- `status`
- `reason`

Tests:

- both present means keep,
- both missing means drop,
- only video missing fails,
- only frame dir missing fails,
- dict-shaped metadata preserves top-level fields.

## New Script: repair_review_media.py

Add `pipeline/scripts/repair_review_media.py`.

Suggested CLI:

```bash
python3 pipeline/scripts/repair_review_media.py \
  --input-meta data/07_metadata/subvideos_meta.json \
  --report data/07_metadata/manual_review_repair_report.json
```

Behavior:

- Detect the same inconsistent states as `prune_reviewed_subvideos.py`.
- If frame folder is missing and mp4 exists, recreate frames from `actual_frame_mapping`.
- If mp4 is missing and frame folder exists, recreate mp4 from the source video and `start_time` / `end_time`.
- For full-video samples, do not overwrite or delete source videos. Use the same full-video policy chosen in `subvideo_builder.py`.
- Do not modify labels.
- Exit non-zero if a repair cannot be completed.

Implementation reuse:

- Reuse path resolution and frame extraction helpers from `subvideo_builder.py` where possible.
- Avoid duplicating ffmpeg command construction if a small shared helper is reasonable.

Tests:

- missing frames are regenerated from an existing mp4 and mapping,
- missing cropped mp4 is regenerated from source video timing metadata,
- unrecoverable source-video absence produces a clear error,
- no-op when all artifacts are consistent.

## New Script: review_subvideo_labels.py

Add `pipeline/scripts/review_subvideo_labels.py`.

Suggested CLI:

```bash
python3 pipeline/scripts/review_subvideo_labels.py \
  --input-meta data/07_metadata/subvideos_meta.reviewed.json \
  --video-meta data/07_metadata/video_meta.json \
  --output-meta data/07_metadata/subvideos_meta.label_reviewed.json \
  --report data/07_metadata/subvideo_label_review_report.json
```

Behavior:

- Load reviewed subvideo metadata and `video_meta.json`.
- Validate media contract:
  - `actual_frame_mapping` is non-empty,
  - frame count is <= 8,
  - frame folder exists,
  - frame image count equals mapping count,
  - processor fingerprint is present and not mock/theoretical.
- Validate full samples:
  - label fields match the governed source record from `video_meta.json`,
  - full positive samples recompute `fracture_between` from source event frame and mapping unless the type is a special anomaly with intentionally unknown timing.
- Validate focus positive samples:
  - source video has a reliable event frame,
  - recomputed `fracture_between` equals stored `fracture_between`,
  - `has_fracture` is true,
  - `type` and `location` match governed source semantics.
- Validate negative samples:
  - `has_fracture` is false,
  - `fracture_between` is null,
  - `location` is null,
  - negative windows do not include post-event hard negatives.
- Validate special types:
  - `视频异常` keeps anomaly semantics and should not invent `fracture_between`,
  - `未夹紧` follows the current governed behavior for event/no-event records.

On success:

- Write `subvideos_meta.label_reviewed.json`.
- Write a report with counts by status, crop type, source type, and warnings.

On failure:

- Exit non-zero.
- Write a report listing each failed row and the failed rule.
- Do not write output metadata unless an explicit `--write-invalid-report-only` style option is added.

Tests:

- valid full positive passes,
- valid focus positive passes,
- changed `fracture_between` fails,
- negative sample with non-null label fields fails,
- missing frame mapping fails,
- special anomaly cases pass only under the documented combinations.

## Training Sample Builder Changes

`training_sample_builder.py` must no longer silently consume unreviewed metadata in the documented path.

Recommended behavior:

- Change the default `--subvideos-meta` to `data/07_metadata/subvideos_meta.label_reviewed.json`.
- If that file does not exist, fail with a message telling the user to run manual prune and label review, or pass `--subvideos-meta` explicitly.
- Preserve explicit override support for tests and debugging.

The generated ShareGPT JSON should remain the same shape:

- `messages`
- `videos`

Do not add debug metadata fields to the final training JSON.

## Quality Checks

Update `quality_check.py` so it aligns with the reviewed metadata path.

Required checks:

- Final ShareGPT files exist.
- Media paths exist.
- Assistant content is valid five-field JSON.
- Legal label combinations are enforced.
- No test ShareGPT training file exists.
- Cross-split leakage is absent.
- Processor fingerprints are consistent and non-mock.
- Train positive/negative ratio is reported after manual review.

If the positive/negative ratio falls outside the configured range after manual deletion, the check should fail or warn based on the existing project policy. The current behavior fails outside `0.5:1 ~ 2:1`; keep that unless the user asks otherwise.

## README Follow-Up

README has already been updated to describe the intended chain and commands. Once implementation is complete, verify command names, option names, and default paths against the final code.

## Migration Notes

Existing generated artifacts may not have frame folders for every subvideo. After changing defaults:

1. Regenerate subvideos on the GPU/Linux machine, or
2. Run `repair_review_media.py` to backfill frames where possible.

Do not delete `data/01_videos/` source videos during manual review.

## Acceptance Criteria

- Running `subvideo_builder.py --model models/minicpmv4_5` produces mp4s, frame folders, and `subvideos_meta.json`.
- Manually deleting both mp4 and frame folder for a sample causes `prune_reviewed_subvideos.py` to remove that sample.
- Deleting only one artifact causes `prune_reviewed_subvideos.py` to fail with an inconsistency report.
- `repair_review_media.py` can restore the missing counterpart for supported inconsistent rows.
- `review_subvideo_labels.py` fails on label/mapping mismatches and writes reviewed metadata only when checks pass.
- `training_sample_builder.py` defaults to reviewed metadata.
- Old tail-contamination commands are absent from README's main workflow.
- Existing tests are updated and new tests cover prune, repair, and label review behavior.
