from __future__ import annotations

from finetune.run_v4_1_evaluation import (
    load_validation_samples,
    summarize_records,
)
from finetune.v4_1_runtime import score_v4_1_prediction


def _labels(
    state: str,
    mechanism: str | None = None,
    site: str | None = None,
) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": mechanism,
        "fracture_site": site,
        "special_case": None,
    }


def _record(
    target: dict[str, object],
    prediction: dict[str, object] | None,
    *,
    runtime_error: str | None = None,
) -> dict[str, object]:
    return {
        "target": target,
        "prediction": prediction,
        "strict_valid": prediction is not None,
        "runtime_error": runtime_error,
        "scores": score_v4_1_prediction(target, prediction),
    }


def test_loads_committed_fold_validation_sets() -> None:
    assert len(load_validation_samples(0)) == 425
    assert len(load_validation_samples(1)) == 445
    assert len(load_validation_samples(2)) == 346


def test_summarizes_strict_metrics_and_confusion() -> None:
    fracture = _labels("发生断裂", "韧性断裂", "inside_gauge")
    stable = _labels("未断裂")
    records = [
        _record(fracture, fracture),
        _record(stable, fracture),
        _record(fracture, None, runtime_error="boom"),
    ]

    summary = summarize_records(records)

    assert summary["total_samples"] == 3
    assert summary["runtime_failure_count"] == 1
    assert summary["strict_valid_rate"] == 0.666667
    assert summary["metrics"]["joint_correct_rate"] == 0.333333
    assert summary["clip_state_confusion"]["发生断裂"]["发生断裂"] == 1
    assert summary["clip_state_confusion"]["发生断裂"]["__invalid__"] == 1
    assert summary["clip_state_confusion"]["未断裂"]["发生断裂"] == 1
