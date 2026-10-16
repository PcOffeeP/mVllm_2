"""Plan immutable subvideo candidates under the tensile-vlm/v3 contract.

The v3 name describes the candidate-planning contract enforced here, not the
downstream training-release contract. The legacy rebuild flow loads
tensile_vlm_v3.json for this stage, then reuses its candidates in V4.1 review
and release stages that load tensile_vlm_v4_1.json separately. This module
does not read or write media; its name does not select a release protocol.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline import artifact_index, artifact_resolver
from pipeline.v3_labels import (
    SOURCE_FRACTURE,
    SOURCE_NO_FRACTURE,
    SOURCE_UNCLAMPED,
    SOURCE_VIDEO_ABNORMAL,
    map_legacy_fracture_type,
    validate_v3_labels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAN_SCHEMA_VERSION = "tensile-subvideo-candidate-plan/v2"
POLICY_VERSION = "v3-candidate-policy/2.0"
TARGET_DURATIONS = (2.0, 3.0, 5.0, 10.0, 20.0)
EVENT_POSITIONS = (0.20, 0.35, 0.50, 0.65, 0.80)
EVENT_GUARD_SECONDS = 0.5
MIN_CANDIDATE_SECONDS = 1.0
USABLE_REFERENCE_STATUSES = frozenset({"approved", "corrected"})
PROCESS_POSITIONS = (0.0, 0.5, 1.0)
TRANSITION_CAP = 10
BRITTLE_PRE_EVENT_CAP = 3
DUCTILE_PRE_EVENT_CAP = 15
OTHER_PRE_EVENT_CAP = 4
POST_EVENT_CAP = 4
NORMAL_NEGATIVE_CAP = 5

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


def _portable_path(path: Path, data_root: Path | None = None) -> str:
    if data_root is not None:
        try:
            relative = path.resolve().relative_to(Path(data_root).resolve())
        except ValueError:
            pass
        else:
            if relative.parts and relative.parts[0] in {
                "source",
                "derived",
                "releases",
            }:
                return relative.as_posix()
            raise CandidatePlanError(f"输入不是受管语义路径: {path}")
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        raise CandidatePlanError(f"输入路径无法转换为稳定身份: {path}")


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
    *,
    data_root: Path | None = None,
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
            "roi_media_manifest": _portable_path(roi_manifest_path, data_root),
            "roi_metadata": _portable_path(roi_metadata_path, data_root),
            "review_reference_manifest": _portable_path(
                reference_manifest_path, data_root
            ),
            "development_reference": _portable_path(
                development_path, data_root
            ),
            "test_reference_audit": _portable_path(test_path, data_root),
            "tensile_vlm_v3_contract": _portable_path(
                contract_path, data_root
            ),
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
    if target_duration < MIN_CANDIDATE_SECONDS:
        return None
    fps = float(record["fps"])
    region_start_frame = max(0, math.ceil(region_start * fps - 1e-9))
    region_end_frame = min(
        int(record["total_frames"]), math.floor(region_end * fps + 1e-9)
    )
    target_frames = max(1, round(target_duration * fps))
    available_start_frames = region_end_frame - region_start_frame - target_frames
    if available_start_frames < 0:
        return None
    start_frame = region_start_frame + round(available_start_frames * position)
    return _interval_from_frames(record, start_frame, start_frame + target_frames)


def _transition_window(
    record: Mapping[str, Any], target_duration: float, event_ratio: float
) -> dict[str, Any] | None:
    duration = float(record["duration"])
    event = _event_time(record)
    if event is None or target_duration > duration:
        return None
    start = event - target_duration * event_ratio
    if start < 0.0 or start + target_duration > duration:
        return None
    interval = _aligned_interval(record, start, start + target_duration)
    if interval is None or not (
        float(interval["start_time"]) < event < float(interval["end_time"])
    ):
        return None
    return interval


def _adaptive_transition_window(
    record: Mapping[str, Any], event_ratio: float
) -> dict[str, Any] | None:
    duration = float(record["duration"])
    event = _event_time(record)
    if event is None:
        return None
    before_limit = event / event_ratio
    after_limit = (duration - event) / (1.0 - event_ratio)
    adaptive_duration = min(before_limit, after_limit)
    if adaptive_duration < MIN_CANDIDATE_SECONDS:
        return None
    start = event - adaptive_duration * event_ratio
    interval = _aligned_interval(record, start, start + adaptive_duration)
    if interval is None or not (
        float(interval["start_time"]) < event < float(interval["end_time"])
    ):
        return None
    return interval


def _normal_negative_window(
    record: Mapping[str, Any], target_duration: float, center_ratio: float
) -> dict[str, Any] | None:
    duration = float(record["duration"])
    if target_duration > duration:
        return None
    target_center = duration * center_ratio
    start = max(0.0, min(duration - target_duration, target_center - target_duration / 2.0))
    return _aligned_interval(record, start, start + target_duration)


def _interval_from_frames(
    record: Mapping[str, Any], start_frame: int, end_frame: int
) -> dict[str, Any] | None:
    fps = float(record["fps"])
    total_frames = int(record["total_frames"])
    duration = float(record["duration"])
    if start_frame < 0 or end_frame > total_frames or end_frame <= start_frame:
        return None
    start_time = start_frame / fps
    end_time = min(duration, end_frame / fps)
    if end_time <= start_time:
        return None
    return {
        "start_frame": start_frame,
        "end_frame": end_frame,
        "start_time": round(start_time, 4),
        "end_time": round(end_time, 4),
        "duration": round(end_time - start_time, 4),
    }


def _post_event_windows(record: Mapping[str, Any], post_start: float) -> list[dict[str, Any]]:
    fps = float(record["fps"])
    total_frames = int(record["total_frames"])
    start_frame = max(0, math.ceil(post_start * fps - 1e-9))
    available_frames = total_frames - start_frame
    if available_frames / fps < MIN_CANDIDATE_SECONDS:
        return []

    full = _interval_from_frames(record, start_frame, total_frames)
    if full is None:
        return []
    results = [dict(full, window_variant="post_event_full")]
    length = float(full["duration"])
    part_count = 3 if length >= 6.0 else 2 if length >= 3.0 else 1
    if part_count == 1:
        return results

    quotient, remainder = divmod(available_frames, part_count)
    cursor = start_frame
    for index in range(part_count):
        part_frames = quotient + (1 if index < remainder else 0)
        end_frame = cursor + part_frames
        part = _interval_from_frames(record, cursor, end_frame)
        cursor = end_frame
        if part is None or float(part["duration"]) < MIN_CANDIDATE_SECONDS:
            return results[:1]
        results.append(dict(part, window_variant=f"post_event_part_{index + 1}_of_{part_count}"))
    return results


def _skip_record(record: Mapping[str, Any], scope: str) -> dict[str, Any]:
    video_id = str(record["video_id"])
    kind, special_case = _source_kind(record)
    if special_case == "未夹紧":
        reason = "unclamped"
    elif special_case == "视频异常":
        reason = "video_abnormal"
    elif kind == SOURCE_FRACTURE:
        reason = "missing_reliable_event_time"
    else:
        reason = "state_not_derivable"
    return {
        "source_video": video_id,
        "scope": scope,
        "source_type": record.get("type"),
        "skip_reason": reason,
        "special_case": special_case,
    }


def _compatible_exact_count(
    interval: Mapping[str, Any],
    labels: Mapping[str, Any],
    references: Iterable[Mapping[str, Any]],
) -> int:
    candidate = dict(interval)
    candidate["candidate_v3_labels"] = labels
    return sum(
        1
        for reference in references
        if reference.get("review_status") in USABLE_REFERENCE_STATUSES
        and _exact_frame_match(candidate, reference)
        and reference.get("candidate_v3_labels") == labels
    )


def _transition_templates_for_source(
    record: Mapping[str, Any], references: Iterable[Mapping[str, Any]]
) -> list[tuple[float, float, dict[str, Any] | None]]:
    labels = _candidate_labels(record, "发生断裂")
    scored_shifts: list[tuple[int, int, list[tuple[float, float, dict[str, Any] | None]]]] = []
    for shift in range(len(EVENT_POSITIONS)):
        templates: list[tuple[float, float, dict[str, Any] | None]] = []
        exact_count = 0
        for index, target in enumerate(TARGET_DURATIONS):
            ratio = EVENT_POSITIONS[(index + shift) % len(EVENT_POSITIONS)]
            interval = _transition_window(record, target, ratio)
            templates.append((target, ratio, interval))
            if interval is not None:
                exact_count += _compatible_exact_count(interval, labels, references)
        scored_shifts.append((-exact_count, shift, templates))
    scored_shifts.sort(key=lambda item: (item[0], item[1]))
    selected = scored_shifts[:2]
    return [template for _, _, group in selected for template in group]


def _selected_pre_event_durations(
    record: Mapping[str, Any], pre_end: float
) -> tuple[str, list[float]]:
    mapping = map_legacy_fracture_type(record.get("type"))
    mechanism = mapping.fracture_mechanism
    feasible = [target for target in TARGET_DURATIONS if target <= pre_end]
    if mechanism in {"脆性断裂", "爆炸性断裂"}:
        if len(feasible) <= BRITTLE_PRE_EVENT_CAP:
            return "abrupt_end_aligned", feasible
        middle = feasible[len(feasible) // 2]
        return "abrupt_end_aligned", [feasible[0], middle, feasible[-1]]
    if mechanism in {"韧性断裂", "半脆半韧断裂"}:
        return "process_front_middle_back", feasible
    if len(feasible) == len(TARGET_DURATIONS):
        feasible = [2.0, 5.0, 10.0, 20.0]
    return "other_end_aligned", feasible[:OTHER_PRE_EVENT_CAP]


def _raw_candidates_for_source(
    record: Mapping[str, Any], references: Iterable[Mapping[str, Any]] = ()
) -> list[dict[str, Any]]:
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
        duration_policy: str = "standard",
        window_variant: str | None = None,
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
                "duration_policy": duration_policy,
                "window_variant": window_variant,
                "candidate_v3_labels": _candidate_labels(record, state),
            }
        )
        results.append(item)

    if kind == SOURCE_FRACTURE and event_reliable:
        templates = _transition_templates_for_source(record, references)
        failed: list[tuple[int, float, int, float, float, dict[str, Any]]] = []
        transition_labels = _candidate_labels(record, "发生断裂")
        for order, (target, ratio, interval) in enumerate(templates):
            if interval is None:
                adaptive = _adaptive_transition_window(record, ratio)
                if adaptive is not None:
                    failed.append(
                        (
                            -_compatible_exact_count(adaptive, transition_labels, references),
                            -float(adaptive["duration"]),
                            order,
                            target,
                            ratio,
                            adaptive,
                        )
                    )
                continue
            add(
                interval,
                role="transition",
                target_duration=target,
                event_position_ratio=ratio,
                role_limit=TRANSITION_CAP,
            )
        if failed and role_counts["transition"] < TRANSITION_CAP:
            _, _, _, target, ratio, adaptive = sorted(failed)[0]
            add(
                adaptive,
                role="transition",
                target_duration=target,
                event_position_ratio=ratio,
                duration_policy="adaptive",
                window_variant="transition_adaptive",
                role_limit=TRANSITION_CAP,
            )

        assert event is not None
        pre_end = max(0.0, event - EVENT_GUARD_SECONDS)
        pre_strategy, pre_durations = _selected_pre_event_durations(record, pre_end)
        if pre_strategy == "process_front_middle_back":
            for target in pre_durations:
                for position in PROCESS_POSITIONS:
                    add(
                        _window_in_region(record, 0.0, pre_end, target, position),
                        role="pre_event",
                        target_duration=target,
                        window_variant=(
                            "pre_event_front"
                            if position == 0.0
                            else "pre_event_middle"
                            if position == 0.5
                            else "pre_event_back"
                        ),
                        role_limit=DUCTILE_PRE_EVENT_CAP,
                    )
        else:
            for target in pre_durations:
                add(
                    _window_in_region(record, 0.0, pre_end, target, 1.0),
                    role="pre_event",
                    target_duration=target,
                    window_variant=pre_strategy,
                    role_limit=(
                        BRITTLE_PRE_EVENT_CAP
                        if pre_strategy == "abrupt_end_aligned"
                        else OTHER_PRE_EVENT_CAP
                    ),
                )

        post_start = min(duration, event + EVENT_GUARD_SECONDS)
        for interval in _post_event_windows(record, post_start):
            add(
                interval,
                role="post_event",
                target_duration=float(interval["duration"]),
                duration_policy="adaptive",
                window_variant=str(interval["window_variant"]),
                role_limit=POST_EVENT_CAP,
            )
    elif kind == SOURCE_NO_FRACTURE:
        rotation = int(
            hashlib.sha256(str(record["video_id"]).encode("utf-8")).hexdigest(), 16
        ) % len(EVENT_POSITIONS)
        for index, target in enumerate(TARGET_DURATIONS):
            position = EVENT_POSITIONS[(index + rotation) % len(EVENT_POSITIONS)]
            add(
                _normal_negative_window(record, target, position),
                role="stable_negative",
                target_duration=target,
                event_position_ratio=position,
                window_variant="normal_negative_rotated",
                role_limit=NORMAL_NEGATIVE_CAP,
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    references = _reference_index(reference_payload)
    candidates: list[dict[str, Any]] = []
    skipped_sources: list[dict[str, Any]] = []
    for video_id in sorted(source_ids):
        record = records[video_id]
        kind, _ = _source_kind(record)
        event_reliable = (
            record.get("event_time_reliable") is True and _event_time(record) is not None
        )
        if kind not in {SOURCE_FRACTURE, SOURCE_NO_FRACTURE} or (
            kind == SOURCE_FRACTURE and not event_reliable
        ):
            skipped_sources.append(_skip_record(record, scope))
            continue
        for raw in _raw_candidates_for_source(record, references.get(video_id, [])):
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
                "duration_policy": raw["duration_policy"],
                "window_variant": raw["window_variant"],
                "candidate_v3_labels": labels,
                "source_type": record.get("type"),
                "source_location": record.get("location_canonical"),
                "roi_provenance": record.get("roi_provenance"),
            }
            _, match = _match_reference(candidate, references.get(video_id, []))
            candidate["review_disposition"] = (
                "manual_required"
                if state in {"发生断裂", "已断裂"}
                else "automatic_validation"
            )
            candidate["reference_match"] = match
            candidates.append(candidate)
    ids = [item["candidate_id"] for item in candidates]
    if len(ids) != len(set(ids)):
        raise CandidatePlanError(f"{scope}: candidate_id 冲突")
    return candidates, skipped_sources


def _statistics(
    candidates: list[dict[str, Any]],
    source_inventory: set[str],
    skipped_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    per_source = Counter(item["source_video"] for item in candidates)
    contributions = list(per_source.values())
    return {
        "source_inventory_count": len(source_inventory),
        "sources_with_candidates": len(per_source),
        "sources_without_candidates": sorted(source_inventory - set(per_source)),
        "skipped_source_count": len(skipped_sources),
        "skip_reason_counts": dict(
            sorted(Counter(item["skip_reason"] for item in skipped_sources).items())
        ),
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
        "event_positions": list(EVENT_POSITIONS),
        "transition_rounds": 2,
        "transition_cap": TRANSITION_CAP,
        "transition_adaptive_cap": 1,
        "transition_pairing": "two_distinct_cyclic_shifts_ranked_by_compatible_exact_matches",
        "transition_adaptive_selection": "compatible_exact_then_longest_then_template_order",
        "process_positions": list(PROCESS_POSITIONS),
        "brittle_pre_event_cap": BRITTLE_PRE_EVENT_CAP,
        "brittle_pre_event_selection": "shortest_floor_median_longest_end_aligned",
        "ductile_pre_event_cap": DUCTILE_PRE_EVENT_CAP,
        "ductile_pre_event_selection": "each_duration_front_middle_back",
        "other_pre_event_cap": OTHER_PRE_EVENT_CAP,
        "other_pre_event_all_feasible_selection": [2.0, 5.0, 10.0, 20.0],
        "post_event_cap": POST_EVENT_CAP,
        "post_event_partition_thresholds_seconds": [3.0, 6.0],
        "post_event_partition_counts": [1, 2, 3],
        "normal_negative_cap": NORMAL_NEGATIVE_CAP,
        "normal_negative_positioning": "center_at_event_positions_rotated_by_video_id_sha256",
        "unknown_candidates_generated": False,
        "manual_review_states": ["发生断裂", "已断裂"],
    }
    identity = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "inputs": inputs["identity_inputs"],
        "policy": policy,
    }
    plan_id = f"candidate-plan-{_content_hash(identity)[:12]}"
    development, development_skipped = _build_scope_candidates(
        inputs["records"],
        inputs["development_ids"],
        inputs["development_reference"],
        "development",
        plan_id,
    )
    test, test_skipped = _build_scope_candidates(
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
        "development": _statistics(
            development, set(inputs["development_ids"]), development_skipped
        ),
        "test_audit": _statistics(test, set(inputs["test_ids"]), test_skipped),
    }
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "identity": identity,
        "input_paths": dict(inputs["input_paths"]),
        "development_candidates": development,
        "development_skipped_sources": development_skipped,
        "test_candidate_audit": test,
        "test_skipped_sources": test_skipped,
        "needs_review": [
            item for item in development if item["review_disposition"] == "manual_required"
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


def _artifact_payloads(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "development_candidates.json": {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan["plan_id"],
            "scope": "development",
            "candidates": plan["development_candidates"],
            "skipped_sources": plan["development_skipped_sources"],
        },
        "test_candidate_audit.json": {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_id": plan["plan_id"],
            "scope": "test_audit",
            "candidates": plan["test_candidate_audit"],
            "skipped_sources": plan["test_skipped_sources"],
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


def _validate_existing_plan(destination: Path, plan: Mapping[str, Any]) -> None:
    manifest = _load_json(destination / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("identity") != plan.get("identity"):
        raise CandidatePlanError(f"既有候选计划身份不一致: {destination}")
    if manifest.get("input_paths") != plan.get("input_paths"):
        raise CandidatePlanError(f"既有候选计划输入路径不一致: {destination}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise CandidatePlanError("既有候选计划 manifest 缺少 artifacts")
    expected_payloads = _artifact_payloads(plan)
    if set(artifacts) != set(expected_payloads):
        raise CandidatePlanError("既有候选计划 artifact 清单与重算结果不一致")
    for name, payload in expected_payloads.items():
        path = destination / name
        expected_hash = _content_hash(payload)
        if (
            not path.is_file()
            or _sha256_file(path) != expected_hash
            or (artifacts.get(name) or {}).get("sha256") != expected_hash
        ):
            raise CandidatePlanError(f"既有候选计划 artifact 漂移: {name}")


def _append_candidate_plan_index(
    output_root: Path, plan: Mapping[str, Any]
) -> None:
    artifact_index.append_entry(
        output_root,
        {
            "id": plan["plan_id"],
            "created_at": artifact_index.utc_now(),
            "step": "candidate_plan",
            "inputs": {
                "roi_media_id": plan["identity"]["inputs"]["roi_media_id"],
                "review_reference_id": plan["identity"]["inputs"][
                    "review_reference_id"
                ],
            },
            "stats": {
                "development_candidates": len(plan["development_candidates"]),
                "test_candidate_audit": len(plan["test_candidate_audit"]),
                "development_needs_review": len(plan["needs_review"]),
            },
            "note": "v3 candidate plan",
        },
    )


def materialize_candidate_plan(plan: Mapping[str, Any], output_root: Path) -> Path:
    """Write only immutable metadata artifacts; no media paths are touched."""
    destination = output_root / str(plan["plan_id"])
    if (destination / "manifest.json").exists():
        _validate_existing_plan(destination, plan)
        _append_candidate_plan_index(output_root, plan)
        artifact_resolver.update_latest(output_root, plan["plan_id"])
        return destination
    if destination.exists():
        raise CandidatePlanError(f"拒绝覆盖未完成的候选计划目录: {destination}")
    destination.mkdir(parents=True)

    payloads = _artifact_payloads(plan)
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
            "development_skipped_sources": len(plan["development_skipped_sources"]),
            "test_candidate_audit": len(plan["test_candidate_audit"]),
            "test_skipped_sources": len(plan["test_skipped_sources"]),
            "development_needs_review": len(plan["needs_review"]),
        },
        "artifacts": artifacts,
        "media_generated": False,
    }
    _atomic_write(destination / "manifest.json", manifest)
    _append_candidate_plan_index(output_root, plan)
    artifact_resolver.update_latest(output_root, plan["plan_id"])
    return destination
