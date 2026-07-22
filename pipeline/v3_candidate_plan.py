"""Plan immutable v3 subvideo candidates without reading or writing media."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.v3_labels import (
    SOURCE_FRACTURE,
    SOURCE_NO_FRACTURE,
    SOURCE_UNCLAMPED,
    SOURCE_VIDEO_ABNORMAL,
    map_legacy_fracture_type,
    validate_v3_labels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAN_SCHEMA_VERSION = "tensile-subvideo-candidate-plan/v1"
POLICY_VERSION = "v3-candidate-policy/1.0"
TARGET_DURATIONS = (20.0, 10.0, 5.0, 3.0, 2.0)
EVENT_GUARD_SECONDS = 0.5
MIN_CANDIDATE_SECONDS = 1.0
USABLE_REFERENCE_STATUSES = frozenset({"approved", "corrected"})

TRANSITION_TEMPLATES = (
    (20.0, 0.50),
    (10.0, 0.35),
    (10.0, 0.65),
    (5.0, 0.50),
    (3.0, 0.35),
    (3.0, 0.65),
    (2.0, 0.50),
)
STABLE_TEMPLATES = (
    (20.0, 0.00),
    (10.0, 0.50),
    (5.0, 1.00),
    (3.0, 0.25),
    (3.0, 0.75),
    (2.0, 0.50),
)
POST_EVENT_TEMPLATES = ((5.0, 0.00), (2.0, 1.00))
UNKNOWN_TEMPLATES = ((20.0, 0.00), (10.0, 0.50), (5.0, 1.00))

STATE_SLUGS = {
    "未断裂": "pre",
    "发生断裂": "transition",
    "已断裂": "post",
    "无法判断": "unknown",
}


class CandidatePlanError(RuntimeError):
    """Candidate planning cannot continue without violating an invariant."""


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _content_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CandidatePlanError(f"文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CandidatePlanError(f"JSON 无法解析: {path}: {exc}") from exc


def _require_artifact_hash(manifest: Mapping[str, Any], name: str, path: Path) -> str:
    expected = ((manifest.get("artifacts") or {}).get(name) or {}).get("sha256")
    actual = _sha256_file(path)
    if not isinstance(expected, str) or expected != actual:
        raise CandidatePlanError(f"artifact SHA-256 不一致: {name}")
    return actual


def _finite_positive(value: Any, field: str, video_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidatePlanError(f"{video_id}: {field} 必须是正有限数")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise CandidatePlanError(f"{video_id}: {field} 必须是正有限数")
    return result


def _event_time(record: Mapping[str, Any]) -> float | None:
    for key in ("event_time_effective", "event_time"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        result = float(value)
        if math.isfinite(result):
            return result
    return None


def _source_kind(record: Mapping[str, Any]) -> tuple[str, str | None]:
    source_type = record.get("type")
    if source_type == "未夹紧":
        return SOURCE_UNCLAMPED, "未夹紧"
    if source_type == "视频异常" or record.get("is_abnormal_canonical") is True:
        return SOURCE_VIDEO_ABNORMAL, "视频异常"
    has_fracture = record.get("has_fracture_canonical", record.get("has_fracture"))
    if has_fracture is True:
        return SOURCE_FRACTURE, None
    if has_fracture is False:
        return SOURCE_NO_FRACTURE, None
    return SOURCE_VIDEO_ABNORMAL, "视频异常"


def _validate_contract(contract: Mapping[str, Any]) -> str:
    if contract.get("contract_version") != "tensile-vlm/v3":
        raise CandidatePlanError("候选计划必须使用 tensile-vlm/v3 契约")
    normalized = dict(contract)
    artifact_hash = normalized.pop("contract_hash", None)
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    actual = hashlib.sha256(canonical).hexdigest()
    if artifact_hash != actual:
        raise CandidatePlanError("tensile-vlm/v3 contract hash 无效")
    return actual


def load_plan_inputs(
    roi_media_dir: Path,
    review_reference_dir: Path,
    contract_path: Path,
) -> dict[str, Any]:
    """Load and verify all lightweight inputs required by the dry-run planner."""
    roi_media_dir = roi_media_dir.resolve()
    review_reference_dir = review_reference_dir.resolve()
    contract_path = contract_path.resolve()

    roi_manifest_path = roi_media_dir / "manifest.json"
    roi_metadata_path = roi_media_dir / "video_meta.roi.json"
    roi_manifest = _load_json(roi_manifest_path)
    roi_metadata = _load_json(roi_metadata_path)
    if not isinstance(roi_manifest, dict) or not isinstance(roi_metadata, list):
        raise CandidatePlanError("ROI media manifest 或 video_meta.roi.json 格式无效")
    roi_metadata_hash = _require_artifact_hash(
        roi_manifest, "video_meta.roi.json", roi_metadata_path
    )
    roi_media_id = roi_manifest.get("roi_media_id")
    if not isinstance(roi_media_id, str) or not roi_media_id:
        raise CandidatePlanError("ROI media manifest 缺少 roi_media_id")

    records: dict[str, dict[str, Any]] = {}
    for raw in roi_metadata:
        if not isinstance(raw, dict):
            raise CandidatePlanError("video_meta.roi.json 必须是对象列表")
        video_id = raw.get("video_id")
        if not isinstance(video_id, str) or not video_id or video_id in records:
            raise CandidatePlanError(f"ROI metadata 存在无效或重复 video_id: {video_id}")
        duration = _finite_positive(raw.get("duration"), "duration", video_id)
        fps = _finite_positive(raw.get("fps"), "fps", video_id)
        total_frames = raw.get("total_frames")
        if isinstance(total_frames, bool) or not isinstance(total_frames, int) or total_frames < 2:
            raise CandidatePlanError(f"{video_id}: total_frames 必须是至少 2 的整数")
        provenance = raw.get("roi_provenance")
        if not isinstance(provenance, dict) or provenance.get("roi_media_id") != roi_media_id:
            raise CandidatePlanError(f"{video_id}: roi_provenance 与 ROI media 不一致")
        event = _event_time(raw)
        if event is not None and not (0 <= event <= duration):
            raise CandidatePlanError(f"{video_id}: event_time 越界")
        normalized = dict(raw)
        normalized["duration"] = duration
        normalized["fps"] = fps
        records[video_id] = normalized

    reference_manifest_path = review_reference_dir / "manifest.json"
    development_path = review_reference_dir / "development_reference.json"
    test_path = review_reference_dir / "test_reference_audit.json"
    reference_manifest = _load_json(reference_manifest_path)
    development = _load_json(development_path)
    test_audit = _load_json(test_path)
    if not all(isinstance(item, dict) for item in (reference_manifest, development, test_audit)):
        raise CandidatePlanError("历史审查参考格式无效")
    development_hash = _require_artifact_hash(
        reference_manifest, "development_reference.json", development_path
    )
    test_hash = _require_artifact_hash(
        reference_manifest, "test_reference_audit.json", test_path
    )
    reference_id = reference_manifest.get("reference_id")
    if development.get("reference_id") != reference_id or test_audit.get("reference_id") != reference_id:
        raise CandidatePlanError("历史审查 reference_id 不一致")

    development_ids = set(development.get("source_inventory") or [])
    test_ids = set(test_audit.get("source_inventory") or [])
    if development_ids & test_ids:
        raise CandidatePlanError("development/test source inventory 存在交叉")
    if development_ids | test_ids != set(records):
        missing = sorted(set(records) - development_ids - test_ids)
        extra = sorted((development_ids | test_ids) - set(records))
        raise CandidatePlanError(f"split inventory 未完整覆盖 ROI metadata: missing={missing} extra={extra}")
    if len(development_ids) != 89 or len(test_ids) != 21:
        raise CandidatePlanError("阶段 B 冻结 split 必须保持 89 development / 21 test")

    contract = _load_json(contract_path)
    if not isinstance(contract, dict):
        raise CandidatePlanError("v3 contract 必须是对象")
    contract_hash = _validate_contract(contract)

    return {
        "records": records,
        "development_ids": development_ids,
        "test_ids": test_ids,
        "development_reference": development,
        "test_reference": test_audit,
        "identity_inputs": {
            "roi_media_id": roi_media_id,
            "roi_manifest_sha256": _sha256_file(roi_manifest_path),
            "roi_metadata_sha256": roi_metadata_hash,
            "review_reference_id": reference_id,
            "review_reference_manifest_sha256": _sha256_file(reference_manifest_path),
            "development_reference_sha256": development_hash,
            "test_reference_audit_sha256": test_hash,
            "tensile_vlm_v3_contract_sha256": contract_hash,
        },
        "input_paths": {
            "roi_media_manifest": _portable_path(roi_manifest_path),
            "roi_metadata": _portable_path(roi_metadata_path),
            "review_reference_manifest": _portable_path(reference_manifest_path),
            "development_reference": _portable_path(development_path),
            "test_reference_audit": _portable_path(test_path),
            "tensile_vlm_v3_contract": _portable_path(contract_path),
        },
    }


def _aligned_interval(
    record: Mapping[str, Any], start_time: float, end_time: float
) -> dict[str, Any] | None:
    fps = float(record["fps"])
    total_frames = int(record["total_frames"])
    duration = float(record["duration"])
    start_frame = max(0, min(total_frames - 1, round(start_time * fps)))
    end_frame = max(start_frame + 1, min(total_frames, round(end_time * fps)))
    aligned_start = start_frame / fps
    aligned_end = min(duration, end_frame / fps)
    if aligned_end <= aligned_start:
        return None
    return {
        "start_frame": start_frame,
        "end_frame": end_frame,
        "start_time": round(aligned_start, 4),
        "end_time": round(aligned_end, 4),
        "duration": round(aligned_end - aligned_start, 4),
    }


def _state_for_interval(record: Mapping[str, Any], interval: Mapping[str, Any]) -> str:
    kind, _ = _source_kind(record)
    if kind in {SOURCE_UNCLAMPED, SOURCE_VIDEO_ABNORMAL}:
        return "无法判断"
    if kind == SOURCE_NO_FRACTURE:
        return "未断裂"
    event = _event_time(record)
    if event is None or record.get("event_time_reliable") is not True:
        return "无法判断"
    start = float(interval["start_time"])
    end = float(interval["end_time"])
    if end <= event - EVENT_GUARD_SECONDS:
        return "未断裂"
    if start >= event + EVENT_GUARD_SECONDS:
        return "已断裂"
    if start < event < end:
        return "发生断裂"
    return "无法判断"


def _candidate_labels(record: Mapping[str, Any], state: str) -> dict[str, Any]:
    _, special_case = _source_kind(record)
    mapping = map_legacy_fracture_type(record.get("type"))
    visible_fracture = state in {"发生断裂", "已断裂"}
    location = record.get("location_canonical")
    if location not in {"inside_gauge", "outside_gauge"}:
        location = None
    labels = {
        "clip_state": state,
        "fracture_mechanism": mapping.fracture_mechanism if visible_fracture else None,
        "root_break": mapping.root_break if visible_fracture else None,
        "location": location if visible_fracture else None,
        "special_case": special_case if state == "无法判断" else None,
    }
    validation = validate_v3_labels(labels)
    if not validation.valid:
        validation.raise_for_errors()
    return labels


def _window_in_region(
    record: Mapping[str, Any],
    region_start: float,
    region_end: float,
    target_duration: float,
    position: float,
) -> dict[str, Any] | None:
    available = region_end - region_start
    if available < target_duration or target_duration < MIN_CANDIDATE_SECONDS:
        return None
    start = region_start + (available - target_duration) * position
    return _aligned_interval(record, start, start + target_duration)


def _transition_window(
    record: Mapping[str, Any], target_duration: float, event_ratio: float
) -> dict[str, Any] | None:
    duration = float(record["duration"])
    event = _event_time(record)
    if event is None or target_duration > duration:
        return None
    start = event - target_duration * event_ratio
    start = max(0.0, min(duration - target_duration, start))
    interval = _aligned_interval(record, start, start + target_duration)
    if interval is None or not (
        float(interval["start_time"]) < event < float(interval["end_time"])
    ):
        return None
    return interval


def _pre_event_limit(record: Mapping[str, Any]) -> int:
    mechanism = map_legacy_fracture_type(record.get("type")).fracture_mechanism
    if mechanism == "脆性断裂":
        return 3
    if mechanism in {"韧性断裂", "半脆半韧断裂"}:
        return 6
    return 4


def _raw_candidates_for_source(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    duration = float(record["duration"])
    kind, _ = _source_kind(record)
    event = _event_time(record)
    event_reliable = record.get("event_time_reliable") is True and event is not None
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    role_counts: Counter[str] = Counter()

    def add(
        interval: dict[str, Any] | None,
        *,
        role: str,
        target_duration: float,
        event_position_ratio: float | None = None,
        role_limit: int | None = None,
    ) -> None:
        if interval is None or interval["duration"] < MIN_CANDIDATE_SECONDS:
            return
        state = _state_for_interval(record, interval)
        expected_state = {
            "transition": "发生断裂",
            "pre_event": "未断裂",
            "post_event": "已断裂",
            "stable_negative": "未断裂",
            "unknown": "无法判断",
        }[role]
        if state != expected_state:
            return
        key = (int(interval["start_frame"]), int(interval["end_frame"]), state)
        if key in seen or (role_limit is not None and role_counts[role] >= role_limit):
            return
        seen.add(key)
        role_counts[role] += 1
        item = dict(interval)
        item.update(
            {
                "window_role": role,
                "target_duration_seconds": target_duration,
                "event_position_ratio": event_position_ratio,
                "candidate_v3_labels": _candidate_labels(record, state),
            }
        )
        results.append(item)

    if duration <= max(TARGET_DURATIONS):
        full = _aligned_interval(record, 0.0, duration)
        if kind == SOURCE_FRACTURE and event_reliable:
            role = "transition"
            limit = len(TRANSITION_TEMPLATES)
        elif kind == SOURCE_NO_FRACTURE:
            role = "stable_negative"
            limit = 6
        else:
            role = "unknown"
            limit = 3
        add(full, role=role, target_duration=duration, role_limit=limit)

    if kind == SOURCE_FRACTURE and event_reliable:
        for target, ratio in TRANSITION_TEMPLATES:
            add(
                _transition_window(record, target, ratio),
                role="transition",
                target_duration=target,
                event_position_ratio=ratio,
                role_limit=len(TRANSITION_TEMPLATES),
            )
        assert event is not None
        pre_end = max(0.0, event - EVENT_GUARD_SECONDS)
        pre_limit = _pre_event_limit(record)
        for target, position in STABLE_TEMPLATES:
            add(
                _window_in_region(record, 0.0, pre_end, target, position),
                role="pre_event",
                target_duration=target,
                role_limit=pre_limit,
            )
        post_start = min(duration, event + EVENT_GUARD_SECONDS)
        for target, position in POST_EVENT_TEMPLATES:
            add(
                _window_in_region(record, post_start, duration, target, position),
                role="post_event",
                target_duration=target,
                role_limit=2,
            )
    elif kind == SOURCE_NO_FRACTURE:
        for target, position in STABLE_TEMPLATES:
            add(
                _window_in_region(record, 0.0, duration, target, position),
                role="stable_negative",
                target_duration=target,
                role_limit=6,
            )
    else:
        for target, position in UNKNOWN_TEMPLATES:
            add(
                _window_in_region(record, 0.0, duration, target, position),
                role="unknown",
                target_duration=target,
                role_limit=3,
            )
    return results


def _reference_index(payload: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise CandidatePlanError("历史参考缺少 records 列表")
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        if not isinstance(item, dict):
            raise CandidatePlanError("历史参考 records 必须是对象列表")
        source = item.get("source_video")
        if isinstance(source, str):
            result[source].append(item)
    return result


def _reference_range(record: Mapping[str, Any]) -> tuple[float, float] | None:
    time_range = record.get("time_range")
    if not isinstance(time_range, Mapping):
        return None
    start = time_range.get("start_time")
    end = time_range.get("end_time")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    start_float, end_float = float(start), float(end)
    if not math.isfinite(start_float) or not math.isfinite(end_float) or start_float >= end_float:
        return None
    return start_float, end_float


def _exact_frame_match(candidate: Mapping[str, Any], reference: Mapping[str, Any]) -> bool:
    time_range = reference.get("time_range")
    if not isinstance(time_range, Mapping):
        return False
    return (
        time_range.get("start_frame") == candidate.get("start_frame")
        and time_range.get("end_frame") == candidate.get("end_frame")
        and isinstance(time_range.get("start_frame"), int)
        and isinstance(time_range.get("end_frame"), int)
    )


def _match_reference(
    candidate: Mapping[str, Any], references: Iterable[Mapping[str, Any]]
) -> tuple[str, dict[str, Any]]:
    usable = [
        item
        for item in references
        if item.get("review_status") in USABLE_REFERENCE_STATUSES
    ]
    exact = [item for item in usable if _exact_frame_match(candidate, item)]
    compatible = [
        item
        for item in exact
        if item.get("candidate_v3_labels") == candidate.get("candidate_v3_labels")
    ]
    if compatible:
        ids = sorted(str(item["reference_record_id"]) for item in compatible)
        return "reference_exact", {"kind": "exact", "reference_ids": ids}
    if exact:
        ids = sorted(str(item["reference_record_id"]) for item in exact)
        return "needs_review", {"kind": "exact_label_conflict", "reference_ids": ids}

    candidate_start = float(candidate["start_time"])
    candidate_end = float(candidate["end_time"])
    overlaps: list[tuple[float, str]] = []
    for item in usable:
        interval = _reference_range(item)
        if interval is None:
            continue
        start, end = interval
        intersection = max(0.0, min(candidate_end, end) - max(candidate_start, start))
        if intersection <= 0:
            continue
        union = max(candidate_end, end) - min(candidate_start, start)
        iou = intersection / union if union > 0 else 0.0
        overlaps.append((iou, str(item["reference_record_id"])))
    if overlaps:
        overlaps.sort(key=lambda item: (-item[0], item[1]))
        top = [
            {"reference_id": reference_id, "time_iou": round(iou, 6)}
            for iou, reference_id in overlaps[:3]
        ]
        return "needs_review", {"kind": "partial_overlap", "references": top}
    return "needs_review", {"kind": "none", "reference_ids": []}


def _build_scope_candidates(
    records: Mapping[str, dict[str, Any]],
    source_ids: Iterable[str],
    reference_payload: Mapping[str, Any],
    scope: str,
    plan_id: str,
) -> list[dict[str, Any]]:
    references = _reference_index(reference_payload)
    candidates: list[dict[str, Any]] = []
    for video_id in sorted(source_ids):
        record = records[video_id]
        for raw in _raw_candidates_for_source(record):
            labels = raw["candidate_v3_labels"]
            state = str(labels["clip_state"])
            candidate_id = (
                f"{video_id}_v3_{STATE_SLUGS[state]}_"
                f"f{raw['start_frame']:06d}-{raw['end_frame']:06d}"
            )
            candidate = {
                "candidate_id": candidate_id,
                "source_video": video_id,
                "scope": scope,
                "source_video_path": record["video_path"],
                "planned_video_path": (
                    f"data/03_subvideos_roi/{plan_id}/videos/{candidate_id}.mp4"
                ),
                "planned_frame_dir": (
                    f"data/04_frames_roi/{plan_id}/{candidate_id}"
                ),
                "media_status": "planned_not_materialized",
                "start_time": raw["start_time"],
                "end_time": raw["end_time"],
                "start_frame": raw["start_frame"],
                "end_frame": raw["end_frame"],
                "duration": raw["duration"],
                "target_duration_seconds": raw["target_duration_seconds"],
                "window_role": raw["window_role"],
                "event_position_ratio": raw["event_position_ratio"],
                "candidate_v3_labels": labels,
                "source_type": record.get("type"),
                "source_location": record.get("location_canonical"),
                "roi_provenance": record.get("roi_provenance"),
            }
            disposition, match = _match_reference(candidate, references.get(video_id, []))
            candidate["review_disposition"] = disposition
            candidate["reference_match"] = match
            candidates.append(candidate)
    ids = [item["candidate_id"] for item in candidates]
    if len(ids) != len(set(ids)):
        raise CandidatePlanError(f"{scope}: candidate_id 冲突")
    return candidates


def _statistics(candidates: list[dict[str, Any]], source_inventory: set[str]) -> dict[str, Any]:
    per_source = Counter(item["source_video"] for item in candidates)
    contributions = list(per_source.values())
    return {
        "source_inventory_count": len(source_inventory),
        "sources_with_candidates": len(per_source),
        "sources_without_candidates": sorted(source_inventory - set(per_source)),
        "candidate_count": len(candidates),
        "clip_state_counts": dict(
            sorted(Counter(item["candidate_v3_labels"]["clip_state"] for item in candidates).items())
        ),
        "window_role_counts": dict(
            sorted(Counter(item["window_role"] for item in candidates).items())
        ),
        "target_duration_counts": dict(
            sorted(Counter(str(item["target_duration_seconds"]) for item in candidates).items())
        ),
        "fracture_mechanism_counts": dict(
            sorted(
                Counter(
                    str(item["candidate_v3_labels"]["fracture_mechanism"])
                    for item in candidates
                ).items()
            )
        ),
        "location_counts": dict(
            sorted(
                Counter(str(item["candidate_v3_labels"]["location"]) for item in candidates).items()
            )
        ),
        "review_disposition_counts": dict(
            sorted(Counter(item["review_disposition"] for item in candidates).items())
        ),
        "per_source_contribution": {
            "min": min(contributions) if contributions else 0,
            "max": max(contributions) if contributions else 0,
            "mean": round(sum(contributions) / len(contributions), 4) if contributions else 0.0,
            "counts": dict(sorted(per_source.items())),
        },
    }


def build_candidate_plan(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic in-memory plan; this function performs no writes."""
    policy = {
        "policy_version": POLICY_VERSION,
        "target_durations_seconds": list(TARGET_DURATIONS),
        "event_guard_seconds": EVENT_GUARD_SECONDS,
        "minimum_candidate_seconds": MIN_CANDIDATE_SECONDS,
        "transition_templates": [list(item) for item in TRANSITION_TEMPLATES],
        "stable_templates": [list(item) for item in STABLE_TEMPLATES],
        "post_event_templates": [list(item) for item in POST_EVENT_TEMPLATES],
        "unknown_templates": [list(item) for item in UNKNOWN_TEMPLATES],
        "brittle_pre_event_cap": 3,
        "ductile_pre_event_cap": 6,
        "other_pre_event_cap": 4,
        "post_event_cap": 2,
        "normal_negative_cap": 6,
        "unknown_cap": 3,
    }
    identity = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "inputs": inputs["identity_inputs"],
        "policy": policy,
    }
    plan_id = f"candidate-plan-{_content_hash(identity)[:12]}"
    development = _build_scope_candidates(
        inputs["records"],
        inputs["development_ids"],
        inputs["development_reference"],
        "development",
        plan_id,
    )
    test = _build_scope_candidates(
        inputs["records"],
        inputs["test_ids"],
        inputs["test_reference"],
        "test_audit",
        plan_id,
    )
    development_sources = {item["source_video"] for item in development}
    test_sources = {item["source_video"] for item in test}
    if development_sources & test_sources:
        raise CandidatePlanError("候选计划发生 development/test 交叉")
    statistics = {
        "development": _statistics(development, set(inputs["development_ids"])),
        "test_audit": _statistics(test, set(inputs["test_ids"])),
    }
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "identity": identity,
        "input_paths": dict(inputs["input_paths"]),
        "development_candidates": development,
        "test_candidate_audit": test,
        "needs_review": [
            item for item in development if item["review_disposition"] == "needs_review"
        ],
        "statistics": statistics,
    }


def _atomic_write(path: Path, payload: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        temporary.write_bytes(_canonical_bytes(payload))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_existing_plan(destination: Path, plan: Mapping[str, Any]) -> None:
    manifest = _load_json(destination / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("identity") != plan.get("identity"):
        raise CandidatePlanError(f"既有候选计划身份不一致: {destination}")
    if manifest.get("input_paths") != plan.get("input_paths"):
        raise CandidatePlanError(f"既有候选计划输入路径不一致: {destination}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise CandidatePlanError("既有候选计划 manifest 缺少 artifacts")
    for name, metadata in artifacts.items():
        path = destination / name
        if not path.is_file() or _sha256_file(path) != (metadata or {}).get("sha256"):
            raise CandidatePlanError(f"既有候选计划 artifact 漂移: {name}")


def materialize_candidate_plan(plan: Mapping[str, Any], output_root: Path) -> Path:
    """Write only immutable metadata artifacts; no media paths are touched."""
    destination = output_root / str(plan["plan_id"])
    if (destination / "manifest.json").exists():
        _validate_existing_plan(destination, plan)
        return destination
    if destination.exists():
        raise CandidatePlanError(f"拒绝覆盖未完成的候选计划目录: {destination}")
    destination.mkdir(parents=True)

    payloads = {
        "development_candidates.json": {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan["plan_id"],
            "scope": "development",
            "candidates": plan["development_candidates"],
        },
        "test_candidate_audit.json": {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan["plan_id"],
            "scope": "test_audit",
            "candidates": plan["test_candidate_audit"],
        },
        "needs_review.json": {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan["plan_id"],
            "scope": "development",
            "candidates": plan["needs_review"],
        },
        "statistics.json": {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan["plan_id"],
            "statistics": plan["statistics"],
        },
    }
    for name, payload in payloads.items():
        _atomic_write(destination / name, payload)
    artifacts = {
        name: {"sha256": _sha256_file(destination / name)} for name in sorted(payloads)
    }
    manifest = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan["plan_id"],
        "identity": plan["identity"],
        "input_paths": plan["input_paths"],
        "counts": {
            "development_candidates": len(plan["development_candidates"]),
            "test_candidate_audit": len(plan["test_candidate_audit"]),
            "development_needs_review": len(plan["needs_review"]),
        },
        "artifacts": artifacts,
        "media_generated": False,
    }
    _atomic_write(destination / "manifest.json", manifest)
    return destination
