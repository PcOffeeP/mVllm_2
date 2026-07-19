from __future__ import annotations

from collections import Counter
from typing import Any


def score_record(record: dict[str, Any]) -> dict[str, Any] | None:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return None
    target = metadata.get("ground_truth")
    if not isinstance(target, dict):
        return None

    prediction = record.get("normalized_output")
    if not isinstance(prediction, dict):
        prediction = {}
    contract_valid = record.get("normalized_valid") is True

    has_correct = prediction.get("has_fracture", object()) == target.get("has_fracture")
    type_correct = prediction.get("type", object()) == target.get("type")
    location_correct = prediction.get("location", object()) == target.get("location")

    target_interval = target.get("fracture_between")
    interval_available = _valid_interval(target_interval)
    interval_correct = (
        prediction.get("fracture_between") == target_interval
        if interval_available
        else None
    )

    target_has_fracture = target.get("has_fracture")
    positive = target_has_fracture is True
    time_target = _target_event_time(metadata)
    time_available = positive and time_target is not None
    predicted_time_range = _predicted_time_range(
        prediction.get("fracture_between"),
        record.get("sampled_timestamps"),
    )
    time_hit = (
        predicted_time_range[0] <= time_target <= predicted_time_range[1]
        if time_available and predicted_time_range is not None
        else (False if time_available else None)
    )

    if interval_available:
        temporal_correct = interval_correct is True
    elif time_available:
        temporal_correct = time_hit is True
    else:
        temporal_correct = prediction.get("fracture_between") == target_interval

    joint_success = (
        contract_valid
        and has_correct
        and type_correct
        and location_correct
        and temporal_correct
    )
    return {
        "positive_target": positive,
        "contract_valid": contract_valid,
        "has_fracture_correct": has_correct,
        "type_correct": type_correct,
        "location_correct": location_correct,
        "interval_available": interval_available,
        "interval_correct": interval_correct,
        "target_event_time_sec": time_target,
        "predicted_time_range_sec": predicted_time_range,
        "time_available": time_available,
        "time_hit": time_hit,
        "joint_success": joint_success,
    }


def summarize_task_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    for record in records:
        score = record.get("task_scores")
        if not isinstance(score, dict):
            score = score_record(record)
        if score is not None:
            scored.append(score)

    positive = [score for score in scored if score["positive_target"]]
    interval = [score for score in scored if score["interval_available"]]
    timed = [score for score in scored if score["time_available"]]
    return {
        "scored_samples": len(scored),
        "positive_samples": len(positive),
        "has_fracture_accuracy": _accuracy(scored, "has_fracture_correct"),
        "type_accuracy": _accuracy(scored, "type_correct"),
        "type_accuracy_positive": _accuracy(positive, "type_correct"),
        "location_accuracy": _accuracy(scored, "location_correct"),
        "location_accuracy_positive": _accuracy(positive, "location_correct"),
        "interval_exact_accuracy": _accuracy(interval, "interval_correct"),
        "interval_scored_samples": len(interval),
        "time_hit_rate": _accuracy(timed, "time_hit"),
        "time_scored_samples": len(timed),
        "joint_success_rate": _accuracy(scored, "joint_success"),
        "has_fracture_confusion": _has_fracture_confusion(records),
        "notes": [
            "Field metrics credit each valid normalized field independently; missing or invalid fields remain incorrect.",
            "Joint success additionally requires the complete normalized output contract to be valid.",
            "Interval accuracy is exact sampled-frame bracket accuracy where a target interval exists.",
            "Time hit requires the ground-truth event time to fall inside the predicted sampled-frame time bracket.",
            "Joint success uses exact interval agreement when available, otherwise time hit for timed positive source videos.",
        ],
    }


def _accuracy(items: list[dict[str, Any]], key: str) -> float | None:
    if not items:
        return None
    return round(sum(value.get(key) is True for value in items) / len(items), 6)


def _valid_interval(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(index, int) and not isinstance(index, bool) for index in value)
    )


def _predicted_time_range(interval: Any, timestamps: Any) -> list[float] | None:
    if not _valid_interval(interval) or not isinstance(timestamps, list):
        return None
    left, right = interval
    if left < 0 or right >= len(timestamps):
        return None
    try:
        return [round(float(timestamps[left]), 6), round(float(timestamps[right]), 6)]
    except (TypeError, ValueError):
        return None


def _target_event_time(metadata: dict[str, Any]) -> float | None:
    raw = metadata.get("event_time")
    if raw is None:
        return None
    try:
        event_time = float(raw)
        start_time = float(metadata.get("start_time") or 0.0)
    except (TypeError, ValueError):
        return None
    return round(event_time - start_time, 6)


def _has_fracture_confusion(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        metadata = record.get("metadata")
        target = metadata.get("ground_truth") if isinstance(metadata, dict) else None
        if not isinstance(target, dict):
            continue
        prediction = record.get("normalized_output")
        predicted = prediction.get("has_fracture") if isinstance(prediction, dict) else "invalid"
        counts[f"target={_label(target.get('has_fracture'))}|pred={_label(predicted)}"] += 1
    return dict(sorted(counts.items()))


def _label(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return "invalid"
