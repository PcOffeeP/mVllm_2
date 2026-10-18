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
    # interval_available is decided solely by the target side
    # (_valid_interval(target_interval)). When the prediction side is missing, the
    # sample still stays in the interval denominator and interval_correct scores it
    # incorrect — so "emit no interval" cannot escape the denominator.
    interval_available = _valid_interval(target_interval)
    predicted_interval = prediction.get("fracture_between")
    # The _valid_interval guard below is NOT redundant: JSON true/false arrive as Python
    # bool, and bool is an int subclass, so [True, 2] == [1, 2] holds. Explicitly
    # rejecting bool stops an output like [true, 2] from being credited as interval-correct.
    interval_correct = (
        _valid_interval(predicted_interval) and predicted_interval == target_interval
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
        # Neither an interval comparison nor a time hit is possible: a missing interval
        # on either side must not be treated as agreement (e.g. None == None).
        temporal_correct = False

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
            "Joint success uses exact interval agreement when the target interval is comparable, otherwise time hit for timed positive source videos; only when the target interval is not comparable and the time branch does not apply is the sample not credited as correct.",
            "joint_success_rate divides by all scored samples, while negative targets and positive targets with neither a comparable interval nor time evidence can never reach joint success structurally, so its value is capped by the positive-sample share of the scored set. For raw outputs that omit the legacy fracture_between key (that is the v2 field set minus the interval field, NOT the four-field v4.1 contract shape), neither the interval nor the time branch can ever be credited as correct: the predicted time bracket is derived from the prediction-side fracture_between together with the sampled timestamps, so with that key absent predicted_time_range stays None and time_hit stays False even for a positive target that carries an event time. That drives interval_exact_accuracy to 0 whenever the target set carries intervals (with an empty denominator it reads None instead), time_hit_rate to 0 for every timed positive target (or None when there is none), and joint_success_rate to 0; those readings must not be cited as a model capability measurement in that case. Such outputs can still pass the normalized contract because the key is optional, so a high contract-valid rate alongside zero interval/time/joint readings is expected and is not evidence of contract violation. A true four-field v4.1 raw lacks the legacy fields themselves as well, in which case normalized validity fails and the field accuracies are not interpretable either. joint_success_rate is a legacy v2 field-contract joint (has_fracture, type, location and either a matching fracture_between interval or a time hit, plus contract validity, over all scored samples) and is not the v4.1 four-field joint_correct_rate scored elsewhere; the two are different metrics and this rate must not be quoted as the gating joint.",
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
