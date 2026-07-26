from __future__ import annotations

from typing import Any

from finetune.analyze_v4_1_source_aware_3k import (
    _absolute_gate_results,
    _loso_analysis,
    _primary_improvement,
    summarize,
)


def _record(
    candidate_id: str,
    source: str,
    target: str,
    predicted: str | None,
) -> dict[str, Any]:
    prediction = {"clip_state": predicted} if predicted is not None else None
    correct = target == predicted
    return {
        "candidate_id": candidate_id,
        "source_video": source,
        "target": {"clip_state": target},
        "prediction": prediction,
        "strict_valid": prediction is not None,
        "runtime_error": None,
        "scores": {"joint_correct": correct},
    }


def _four_state_records(*, perfect: bool) -> list[dict[str, Any]]:
    states = ("临界未断裂", "发生断裂", "已断裂", "未断裂")
    records = []
    for source_index in range(2):
        for state_index, state in enumerate(states):
            predicted = state if perfect else states[(state_index + 1) % len(states)]
            records.append(
                _record(
                    f"c{source_index}_{state_index}",
                    f"video_{source_index:04d}",
                    state,
                    predicted,
                )
            )
    return records


def test_summary_counts_invalid_as_wrong() -> None:
    records = _four_state_records(perfect=True)
    records[0]["prediction"] = None
    records[0]["strict_valid"] = False
    records[0]["scores"]["joint_correct"] = False

    result = summarize(records)

    assert result["clip_state_recall"]["临界未断裂"] == 0.5
    assert result["strict_valid_rate"] == 0.875
    assert result["joint_correct_rate"] == 0.875


def test_absolute_gates_require_every_threshold() -> None:
    summary = {
        "fracture_three_state_macro_recall": 0.3272,
        "four_state_macro_recall": 0.4382,
        "已断裂_recall": 0.2015,
        "未断裂_recall": 0.751,
        "joint_correct_rate": 0.4112,
        "strict_valid_rate": 1.0,
        "runtime_failure_count": 0,
    }
    results = _absolute_gate_results(summary)

    assert all(item["passed"] for item in results.values())
    summary["strict_valid_rate"] = 0.999
    assert _absolute_gate_results(summary)["strict_valid_rate"]["passed"] is False


def test_primary_improvement_uses_three_recall_metrics() -> None:
    baseline = {
        "fracture_three_state_macro_recall": 0.2,
        "four_state_macro_recall": 0.3,
        "已断裂_recall": 0.1,
    }
    candidate = {
        "fracture_three_state_macro_recall": 0.3,
        "four_state_macro_recall": 0.35,
        "已断裂_recall": 0.2,
    }

    result = _primary_improvement(candidate, baseline)

    assert result["aggregate"] == 0.083333


def test_loso_detects_single_source_dominance() -> None:
    baseline = _four_state_records(perfect=False)
    improved = _four_state_records(perfect=False)
    for record in improved:
        if record["source_video"] == "video_0000":
            record["prediction"] = {
                "clip_state": record["target"]["clip_state"],
            }
            record["scores"]["joint_correct"] = True

    result = _loso_analysis(baseline, improved)

    assert result["passed"] is False
    assert result["minimum_retention"] == 0.0
