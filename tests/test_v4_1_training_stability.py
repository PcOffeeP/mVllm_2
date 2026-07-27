from __future__ import annotations

import json
from pathlib import Path

import pytest

from finetune.analyze_v4_1_training_stability import StabilityError, compare_pair, final_disposition


POLICY = {
    "relative_limits_percentage_points": {"fracture_recall": 5.0},
    "max_prediction_disagreement_rate": 0.1,
}


def records(path: Path, values: list[tuple[str, float, bool]]) -> Path:
    path.write_text("".join(json.dumps({"candidate_id": i, "fracture_recall": m, "predicted_has_fracture": p}) + "\n" for i, m, p in values))
    return path


def test_relative_boundaries_and_record_only(tmp_path: Path) -> None:
    a = records(tmp_path / "a", [(str(i), .37, i == 0) for i in range(10)])
    b = records(tmp_path / "b", [(str(i), .42, i in (0, 1)) for i in range(10)])
    gate = compare_pair(a, b, POLICY, left_seed=3407, right_seed=3411)
    assert gate["overall"] is True
    assert gate["prediction_disagreement_rate"] == .1


def test_out_of_range_and_fallback_disposition(tmp_path: Path) -> None:
    a = records(tmp_path / "a", [("x", .37, False)])
    b = records(tmp_path / "b", [("x", .55, True)])
    primary = compare_pair(a, b, POLICY, left_seed=3407, right_seed=3411)
    assert primary["overall"] is False
    passed = {**primary, "pair": [3407, 3413], "overall": True}
    assert final_disposition(primary, [passed])["status"] == "fallback_pass_with_outlier"
    assert final_disposition(primary, [primary])["status"] == "stability_unresolved_record_only"


def test_candidate_mismatch_duplicate_and_runtime_fail_closed(tmp_path: Path) -> None:
    a = records(tmp_path / "a", [("x", .4, False)])
    b = records(tmp_path / "b", [("y", .4, False)])
    with pytest.raises(StabilityError):
        compare_pair(a, b, POLICY, left_seed=3407, right_seed=3411)
    dup = tmp_path / "dup"
    dup.write_text('{"candidate_id":"x","fracture_recall":0.4,"predicted_has_fracture":false}\n' * 2)
    with pytest.raises(StabilityError):
        compare_pair(dup, a, POLICY, left_seed=3407, right_seed=3411)
    gate = compare_pair(a, a, POLICY, left_seed=3407, right_seed=3411, runtime_failures={3411: 1})
    assert gate["overall"] is False


def test_real_strict_evaluation_record_shape(tmp_path: Path) -> None:
    values = [
        {
            "candidate_id": str(index),
            "target": {"clip_state": "发生断裂" if index < 5 else "未断裂"},
            "prediction": {"clip_state": "发生断裂" if index < 4 else "未断裂"},
            "strict_valid": True,
        }
        for index in range(10)
    ]
    left = tmp_path / "left"
    right = tmp_path / "right"
    text = "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values)
    left.write_text(text)
    right.write_text(text)
    policy = {
        "relative_limits_percentage_points": {
            "fracture_recall": 5.0,
            "non_fracture_recall": 5.0,
            "fracture_f1": 5.0,
            "macro_f1": 5.0,
            "strict_valid_rate": 1.0,
        },
        "max_prediction_disagreement_rate": 0.1,
    }
    gate = compare_pair(left, right, policy, left_seed=3407, right_seed=3411)
    assert gate["overall"] is True
    assert gate["metric_gates"]["fracture_recall"]["left"] == 0.8
