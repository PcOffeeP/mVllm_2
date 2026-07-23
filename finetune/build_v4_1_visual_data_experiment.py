"""Build an experimental fold0 dataset with additional fracture subvideos.

This experiment deliberately bypasses human review to measure whether more
temporal views improve learning.  Its outputs are never valid production
training releases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from finetune.v4_1_runtime import RELEASE_ID, release_dir, validate_training_row
from pipeline.current_data import current_data_paths
from pipeline.preprocessing import MiniCPMVideoPreprocessor
from pipeline.v3_candidate_media import load_media_plan, materialize_media_plan
from pipeline.v3_candidate_plan import (
    PLAN_SCHEMA_VERSION,
    _candidate_labels,
    _transition_window,
    _window_in_region,
    materialize_candidate_plan,
)
from pipeline.v4_1_labels import V4_1_LABEL_FIELDS, migrate_v3_to_v4_1_labels

ROOT = Path(__file__).resolve().parents[1]
POLICY_VERSION = "v4.1-visual-data-experiment/1.0"
EXPERIMENT_NAME = "v4_1_subvideo_exp_v1"
ROI_MEDIA_ID = "roi-media-84ea2bd3a052"
BASE_PLAN_ID = "candidate-plan-ce36b9226be5"
TRANSITION_DURATIONS = (1.5, 2.5, 4.0, 6.0)
TRANSITION_RATIOS = (0.15, 0.40, 0.65, 0.85)
TRANSITION_ROUNDS = 2
POST_DURATIONS = (1.5, 2.5, 4.0)
POST_POSITIONS = (0.0, 1.0)
EVENT_GUARD_SECONDS = 0.5
DATASET_TRAIN_NAME = "tensile_v4_1_exp_fold0_train"
DATASET_VAL_NAME = "tensile_v4_1_exp_fold0_val"


class VisualDataExperimentError(RuntimeError):
    """The experimental dataset cannot be built reproducibly."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualDataExperimentError(f"无法读取 JSON {path}: {exc}") from exc


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _source_id(video_path: str) -> str:
    name = Path(video_path).stem
    parts = name.split("_")
    if len(parts) < 2 or parts[0] != "video" or not parts[1].isdigit():
        raise VisualDataExperimentError(f"无法从候选路径解析源视频: {video_path}")
    return f"video_{parts[1]}"


def _fold0_train_sources(base_release: Path) -> set[str]:
    rows = _read_json(base_release / "datasets/train/fold_0.json")
    if not isinstance(rows, list):
        raise VisualDataExperimentError("fold0 train 不是列表")
    result: set[str] = set()
    for index, row in enumerate(rows):
        video_path, _ = validate_training_row(row, "fold0_train", index)
        result.add(_source_id(video_path))
    return result


def _existing_intervals(base_plan_path: Path) -> set[tuple[str, int, int]]:
    payload = _read_json(base_plan_path)
    rows = payload.get("candidates") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise VisualDataExperimentError("基础候选计划 candidates 缺失")
    return {
        (
            str(item["source_video"]),
            int(item["start_frame"]),
            int(item["end_frame"]),
        )
        for item in rows
        if isinstance(item, Mapping)
    }


def _candidate(
    *,
    record: Mapping[str, Any],
    plan_id: str,
    interval: Mapping[str, Any],
    state: str,
    role: str,
    duration: float,
    ratio: float | None,
    variant: str,
) -> dict[str, Any]:
    video_id = str(record["video_id"])
    start_frame = int(interval["start_frame"])
    end_frame = int(interval["end_frame"])
    candidate_id = (
        f"{video_id}_v41exp_{role}_"
        f"f{start_frame:06d}-{end_frame:06d}"
    )
    return {
        "candidate_id": candidate_id,
        "source_video": video_id,
        "scope": "development",
        "source_video_path": record["video_path"],
        "planned_video_path": (
            f"data/03_subvideos_roi/{plan_id}/videos/{candidate_id}.mp4"
        ),
        "planned_frame_dir": f"data/04_frames_roi/{plan_id}/{candidate_id}",
        "media_status": "planned_not_materialized",
        "start_time": interval["start_time"],
        "end_time": interval["end_time"],
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration": interval["duration"],
        "target_duration_seconds": duration,
        "window_role": role,
        "event_position_ratio": ratio,
        "duration_policy": "experimental_dense",
        "window_variant": variant,
        "candidate_v3_labels": _candidate_labels(record, state),
        "source_type": record.get("type"),
        "source_location": record.get("location_canonical"),
        "roi_provenance": record.get("roi_provenance"),
        "review_disposition": "experimental_auto_label",
        "reference_match": {"kind": "experimental_not_reviewed"},
    }


def build_experimental_plan(
    *,
    roi_records: Iterable[Mapping[str, Any]],
    fold0_train_sources: set[str],
    existing_intervals: set[tuple[str, int, int]],
    identity_inputs: Mapping[str, Any],
    input_paths: Mapping[str, str],
) -> dict[str, Any]:
    """Build deterministic extra transition/post candidates for fold0 only."""
    policy = {
        "policy_version": POLICY_VERSION,
        "fold": 0,
        "base_release_id": RELEASE_ID,
        "transition_durations": list(TRANSITION_DURATIONS),
        "transition_ratios": list(TRANSITION_RATIOS),
        "transition_rounds": TRANSITION_ROUNDS,
        "post_durations": list(POST_DURATIONS),
        "post_positions": list(POST_POSITIONS),
        "event_guard_seconds": EVENT_GUARD_SECONDS,
        "states": ["发生断裂", "已断裂"],
        "labels": "source_metadata_automatic_experimental",
        "human_reviewed": False,
    }
    identity = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "inputs": dict(identity_inputs),
        "policy": policy,
    }
    plan_id = f"candidate-plan-v41exp-{_content_hash(identity)[:12]}"
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for record in sorted(roi_records, key=lambda item: str(item.get("video_id"))):
        video_id = str(record.get("video_id") or "")
        if video_id not in fold0_train_sources:
            continue
        event = record.get("event_time")
        if (
            record.get("has_fracture_canonical") is not True
            or record.get("event_time_reliable") is not True
            or isinstance(event, bool)
            or not isinstance(event, (int, float))
        ):
            skipped.append(
                {
                    "source_video": video_id,
                    "scope": "development",
                    "skip_reason": "fracture_event_not_reliable",
                }
            )
            continue
        seen: set[tuple[int, int, str]] = set()
        for round_index in range(TRANSITION_ROUNDS):
            for index, duration in enumerate(TRANSITION_DURATIONS):
                ratio = TRANSITION_RATIOS[
                    (index + round_index) % len(TRANSITION_RATIOS)
                ]
                interval = _transition_window(record, duration, ratio)
                if interval is None:
                    continue
                key = (
                    int(interval["start_frame"]),
                    int(interval["end_frame"]),
                    "transition",
                )
                source_interval = (video_id, key[0], key[1])
                if key in seen or source_interval in existing_intervals:
                    continue
                seen.add(key)
                candidates.append(
                    _candidate(
                        record=record,
                        plan_id=plan_id,
                        interval=interval,
                        state="发生断裂",
                        role="transition",
                        duration=duration,
                        ratio=ratio,
                        variant=f"dense_round_{round_index + 1}",
                    )
                )

        post_start = float(event) + EVENT_GUARD_SECONDS
        source_duration = float(record["duration"])
        for duration in POST_DURATIONS:
            for position in POST_POSITIONS:
                interval = _window_in_region(
                    record,
                    post_start,
                    source_duration,
                    duration,
                    position,
                )
                if interval is None:
                    continue
                key = (
                    int(interval["start_frame"]),
                    int(interval["end_frame"]),
                    "post",
                )
                source_interval = (video_id, key[0], key[1])
                if key in seen or source_interval in existing_intervals:
                    continue
                seen.add(key)
                candidates.append(
                    _candidate(
                        record=record,
                        plan_id=plan_id,
                        interval=interval,
                        state="已断裂",
                        role="post_event",
                        duration=duration,
                        ratio=None,
                        variant=(
                            "post_dense_front"
                            if position == 0.0
                            else "post_dense_back"
                        ),
                    )
                )

    ids = [item["candidate_id"] for item in candidates]
    if not candidates or len(ids) != len(set(ids)):
        raise VisualDataExperimentError("实验候选为空或 candidate_id 重复")
    state_counts = Counter(
        item["candidate_v3_labels"]["clip_state"] for item in candidates
    )
    source_counts = Counter(item["source_video"] for item in candidates)
    statistics = {
        "development": {
            "source_inventory_count": len(fold0_train_sources),
            "sources_with_candidates": len(source_counts),
            "candidate_count": len(candidates),
            "clip_state_counts": dict(sorted(state_counts.items())),
            "per_source_contribution": dict(sorted(source_counts.items())),
        },
        "test_audit": {
            "source_inventory_count": 0,
            "sources_with_candidates": 0,
            "candidate_count": 0,
        },
    }
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "identity": identity,
        "input_paths": dict(input_paths),
        "development_candidates": candidates,
        "development_skipped_sources": skipped,
        "test_candidate_audit": [],
        "test_skipped_sources": [],
        "needs_review": [],
        "statistics": statistics,
    }


def _frame_signature(candidate: Mapping[str, Any]) -> tuple[str, tuple[int, ...]]:
    mapping = candidate.get("actual_frame_mapping")
    if not isinstance(mapping, list) or not mapping:
        raise VisualDataExperimentError(
            f"{candidate.get('candidate_id')}: actual_frame_mapping 缺失"
        )
    frames = tuple(int(item["original_frame"]) for item in mapping)
    return str(candidate["source_video"]), frames


def _dataset_row(
    video_path: str,
    labels: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    analysis = contract["analysis"]
    target = {field: labels[field] for field in V4_1_LABEL_FIELDS}
    return {
        "videos": [video_path],
        "messages": [
            {"role": "system", "content": analysis["system_prompt"]},
            {
                "role": "user",
                "content": f"<video>\n{analysis['user_prompt']}",
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    target,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
    }


def build_experimental_dataset(
    *,
    base_release: Path,
    base_materialized_path: Path,
    experimental_materialized_path: Path,
    contract_path: Path,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Append unique experimental frame views to the fold0 training split."""
    base_train = _read_json(base_release / "datasets/train/fold_0.json")
    base_val = _read_json(base_release / "datasets/validation/fold_0.json")
    base_materialized = _read_json(base_materialized_path)
    experimental = _read_json(experimental_materialized_path)
    contract = _read_json(contract_path)
    for label, value in (
        ("base train", base_train),
        ("base val", base_val),
        ("base materialized", base_materialized),
        ("experimental materialized", experimental),
    ):
        if not isinstance(value, (list, dict)):
            raise VisualDataExperimentError(f"{label} 格式非法")
    base_candidates = base_materialized.get("candidates")
    extra_candidates = experimental.get("candidates")
    if not isinstance(base_candidates, list) or not isinstance(extra_candidates, list):
        raise VisualDataExperimentError("materialized candidates 缺失")
    signatures = {_frame_signature(item) for item in base_candidates}
    accepted: list[dict[str, Any]] = []
    duplicate_count = 0
    for candidate in extra_candidates:
        signature = _frame_signature(candidate)
        if signature in signatures:
            duplicate_count += 1
            continue
        signatures.add(signature)
        labels = migrate_v3_to_v4_1_labels(candidate["candidate_v3_labels"])
        accepted.append(
            {
                "candidate_id": candidate["candidate_id"],
                "source_video": candidate["source_video"],
                "video_path": candidate["video_path"],
                "video_sha256": candidate["video_sha256"],
                "actual_frame_mapping": candidate["actual_frame_mapping"],
                "frame_signature_sha256": _content_hash(signature),
                "labels": labels,
                "label_source": "automatic_experimental_source_metadata",
                "human_reviewed": False,
            }
        )
    if not accepted:
        raise VisualDataExperimentError("真实抽帧去重后没有新增实验候选")
    augmented_rows = list(base_train)
    augmented_rows.extend(
        _dataset_row(item["video_path"], item["labels"], contract)
        for item in accepted
    )
    common = {
        "formatting": "sharegpt",
        "columns": {"messages": "messages", "videos": "videos"},
        "tags": {
            "role_tag": "role",
            "content_tag": "content",
            "user_tag": "user",
            "assistant_tag": "assistant",
            "observation_tag": "observation",
            "function_tag": "function_call",
            "system_tag": "system",
        },
    }
    registry = {
        DATASET_TRAIN_NAME: {
            **common,
            "file_name": "datasets/train/fold_0.json",
        },
        DATASET_VAL_NAME: {
            **common,
            "file_name": "datasets/validation/fold_0.json",
        },
    }
    state_counts = Counter(item["labels"]["clip_state"] for item in accepted)
    manifest = {
        "schema_version": "tensile-v4.1-visual-data-experiment/v1",
        "experiment_name": EXPERIMENT_NAME,
        "experimental_only": True,
        "production_release": False,
        "human_reviewed": False,
        "base_release_id": RELEASE_ID,
        "contract_version": contract["contract_version"],
        "contract_hash": contract["contract_hash"],
        "counts": {
            "base_train": len(base_train),
            "validation": len(base_val),
            "experimental_materialized": len(extra_candidates),
            "experimental_unique_accepted": len(accepted),
            "experimental_duplicate_frame_views": duplicate_count,
            "augmented_train": len(augmented_rows),
        },
        "experimental_clip_state_counts": dict(sorted(state_counts.items())),
        "label_policy": {
            "states": ["发生断裂", "已断裂"],
            "source": "reliable_event_time_and_source_metadata",
            "human_review_required_before_production": True,
        },
        "candidates": accepted,
    }
    files = {
        "datasets/train/fold_0.json": _canonical_bytes(augmented_rows),
        "datasets/validation/fold_0.json": _canonical_bytes(base_val),
        "dataset_info.json": _canonical_bytes(registry),
        "experiment_manifest.json": _canonical_bytes(manifest),
    }
    return files, manifest


def _write_dataset(destination: Path, files: Mapping[str, bytes]) -> None:
    if destination.exists():
        for relative, content in files.items():
            path = destination / relative
            if not path.is_file() or path.read_bytes() != content:
                raise VisualDataExperimentError(
                    f"拒绝覆盖漂移的实验数据集: {destination}"
                )
        return
    for relative, content in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
        temporary.write_bytes(content)
        os.replace(temporary, path)


def validate_experiment_config(
    config_path: Path,
    *,
    visual: bool,
    augmented: bool,
) -> dict[str, Any]:
    """Reject configs that silently miss the intended ablation variable."""
    try:
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise VisualDataExperimentError(
            f"无法读取训练配置 {config_path}: {exc}"
        ) from exc
    if not isinstance(config, dict):
        raise VisualDataExperimentError(f"训练配置不是对象: {config_path}")
    expected = {
        "stage": "sft",
        "do_train": True,
        "do_eval": True,
        "finetuning_type": "lora",
        "lora_target": "all",
        "video_maxlen": 8,
        "freeze_vision_tower": not visual,
        "freeze_multi_modal_projector": not visual,
    }
    for field, value in expected.items():
        if config.get(field) != value:
            raise VisualDataExperimentError(
                f"{Path(config_path).name}: {field} 应为 {value!r}"
            )
    if visual and config.get("additional_target") != "resampler":
        raise VisualDataExperimentError("视觉实验必须保存 resampler")
    if visual and (
        config.get("quantization_bit") != 4
        or config.get("quantization_method") != "bnb"
        or config.get("optim") != "adamw_torch"
    ):
        raise VisualDataExperimentError(
            "视觉实验必须使用 4-bit bnb 基座和 adamw_torch 优化器"
        )
    if not visual and config.get("additional_target") is not None:
        raise VisualDataExperimentError("语言对照不得包含 additional_target")
    expected_train = (
        DATASET_TRAIN_NAME if augmented else "tensile_v4_1_fold0_train"
    )
    expected_val = (
        DATASET_VAL_NAME if augmented else "tensile_v4_1_fold0_val"
    )
    if (
        config.get("dataset") != expected_train
        or config.get("eval_dataset") != expected_val
    ):
        raise VisualDataExperimentError("实验配置数据集名称与对照变量不一致")
    output = str(config.get("output_dir") or "")
    if visual and "visual" not in output:
        raise VisualDataExperimentError("视觉实验 output_dir 缺少 visual 身份")
    if augmented and EXPERIMENT_NAME not in output:
        raise VisualDataExperimentError("扩充实验 output_dir 缺少实验身份")
    return config


def validate_adapter_coverage(adapter_dir: Path, *, visual: bool) -> dict[str, Any]:
    """Verify saved PEFT metadata proves the requested modules were trained."""
    path = Path(adapter_dir) / "adapter_config.json"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise VisualDataExperimentError(f"adapter_config 不是对象: {path}")
    targets = payload.get("target_modules")
    if not isinstance(targets, list):
        raise VisualDataExperimentError("adapter target_modules 缺失")
    visual_targets = [str(item) for item in targets if "vpm" in str(item)]
    modules_to_save = payload.get("modules_to_save") or []
    if not isinstance(modules_to_save, list):
        raise VisualDataExperimentError("adapter modules_to_save 非法")
    saved_resampler = any("resampler" in str(item) for item in modules_to_save)
    if visual and (not visual_targets or not saved_resampler):
        raise VisualDataExperimentError(
            "视觉 adapter 未同时覆盖 vpm 和 resampler"
        )
    if not visual and (visual_targets or saved_resampler):
        raise VisualDataExperimentError("语言对照意外包含视觉模块")
    return {
        "visual": visual,
        "target_module_count": len(targets),
        "visual_target_module_count": len(visual_targets),
        "resampler_saved": saved_resampler,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "models/minicpmv4_5",
    )
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = current_data_paths(ROOT)
    base_release = release_dir(ROOT)
    roi_media_dir = paths.roi_videos / ROI_MEDIA_ID
    roi_metadata_path = roi_media_dir / "video_meta.roi.json"
    base_plan_path = (
        paths.metadata
        / f"v3/candidate_plans/{BASE_PLAN_ID}/development_candidates.json"
    )
    base_materialized_path = (
        paths.metadata
        / "v3/candidate_media_results/candidate-media-8de972530561/"
        "development_materialized.json"
    )
    plan_root = paths.metadata / "v4_1/experiments/subvideo_plans"
    media_result_root = (
        paths.metadata / "v4_1/experiments/candidate_media_results"
    )
    dataset_root = (
        paths.derived / f"experiments/{EXPERIMENT_NAME}/dataset"
    )
    roi_records = _read_json(roi_metadata_path)
    if not isinstance(roi_records, list):
        raise VisualDataExperimentError("ROI metadata 不是列表")
    plan = build_experimental_plan(
        roi_records=roi_records,
        fold0_train_sources=_fold0_train_sources(base_release),
        existing_intervals=_existing_intervals(base_plan_path),
        identity_inputs={
            "roi_media_id": ROI_MEDIA_ID,
            "roi_metadata_sha256": _sha256(roi_metadata_path),
            "base_release_id": RELEASE_ID,
            "base_train_sha256": _sha256(
                base_release / "datasets/train/fold_0.json"
            ),
            "base_plan_sha256": _sha256(base_plan_path),
        },
        input_paths={
            "roi_metadata": str(roi_metadata_path),
            "base_release": str(base_release),
            "base_plan": str(base_plan_path),
        },
    )
    plan_dir = materialize_candidate_plan(plan, plan_root)
    if args.plan_only:
        print(
            json.dumps(
                {
                    "plan_dir": str(plan_dir),
                    "plan_id": plan["plan_id"],
                    "statistics": plan["statistics"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    processor = MiniCPMVideoPreprocessor(
        model_path_or_name=str(args.model),
        max_frames=8,
    )
    loaded = load_media_plan(
        plan_dir,
        roi_media_dir,
        paths.compatibility_workspace,
        processor_fingerprint=processor.fingerprint(),
        scopes=("development",),
    )
    media_dir = materialize_media_plan(
        loaded,
        model_path=str(args.model),
        video_output_root=paths.subvideos,
        frame_output_root=paths.frames,
        result_root=media_result_root,
        preprocessor=processor,
    )
    files, manifest = build_experimental_dataset(
        base_release=base_release,
        base_materialized_path=base_materialized_path,
        experimental_materialized_path=media_dir / "development_materialized.json",
        contract_path=ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    _write_dataset(dataset_root, files)
    print(
        json.dumps(
            {
                "plan_dir": str(plan_dir),
                "media_dir": str(media_dir),
                "dataset_dir": str(dataset_root),
                "experimental_only": manifest["experimental_only"],
                "production_release": manifest["production_release"],
                "counts": manifest["counts"],
                "experimental_clip_state_counts": manifest[
                    "experimental_clip_state_counts"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
