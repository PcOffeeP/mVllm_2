"""Window geometry reused from mVllm_2, without its data/test/model orchestration.

Source commit: 2c272ce3548c917bbfa96fe474858f9bf1998893.
The selected original constants/functions below are byte-for-byte source segments.
Legacy labels are internal geometry aids, never final five-category clip labels.
"""
from __future__ import annotations
import hashlib
import math
from collections import Counter
from typing import Any, Iterable, Mapping
try:
    from ._geometry_labels import (SOURCE_FRACTURE, SOURCE_NO_FRACTURE,
        SOURCE_UNCLAMPED, SOURCE_VIDEO_ABNORMAL, map_legacy_fracture_type, validate_v3_labels)
except ImportError:
    from _geometry_labels import (SOURCE_FRACTURE, SOURCE_NO_FRACTURE,
        SOURCE_UNCLAMPED, SOURCE_VIDEO_ABNORMAL, map_legacy_fracture_type, validate_v3_labels)

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
