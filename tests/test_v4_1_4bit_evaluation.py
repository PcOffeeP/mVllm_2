from __future__ import annotations

from pathlib import Path

import pytest

from finetune.run_v4_1_evaluation import _run_identity
from finetune.run_v4_1_visual_4bit_evaluation import compare_record_sets
from finetune.validation.model_runtime import (
    FOUR_BIT_INFERENCE_PRECISION,
    FOUR_BIT_SKIP_MODULES,
)


def _record(state: str, timestamps: list[float] | None = None) -> dict:
    return {
        "target": {"clip_state": "未断裂"},
        "prediction": {
            "clip_state": state,
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": None,
        },
        "sampled_timestamps": timestamps or [0.0, 1.0],
    }


def test_four_bit_identity_is_distinct_from_bf16(tmp_path: Path) -> None:
    bf16 = _run_identity(0, tmp_path, 1)
    four_bit = _run_identity(
        0,
        tmp_path,
        1,
        quantization_bit=4,
    )

    assert "inference_precision" not in bf16
    assert four_bit["inference_precision"] == FOUR_BIT_INFERENCE_PRECISION
    assert FOUR_BIT_SKIP_MODULES == ("resampler",)


def test_compare_record_sets_reports_normalized_agreement() -> None:
    bf16 = {
        "same": _record("未断裂"),
        "changed": _record("发生断裂"),
    }
    four_bit = {
        "same": _record("未断裂"),
        "changed": _record("临界未断裂"),
    }

    result = compare_record_sets(bf16, four_bit)

    assert result["total_samples"] == 2
    assert result["exact_prediction_match_rate"] == 0.5
    assert result["field_agreement_rates"]["clip_state"] == 0.5
    assert result["field_agreement_rates"]["fracture_site"] == 1.0
    assert result["changed_candidate_ids"] == ["changed"]
    assert result["clip_state_transition"]["发生断裂"] == {
        "临界未断裂": 1
    }


def test_compare_record_sets_rejects_different_frames() -> None:
    bf16 = {"sample": _record("未断裂", [0.0, 1.0])}
    four_bit = {"sample": _record("未断裂", [0.0, 2.0])}

    with pytest.raises(RuntimeError, match="输入帧时间戳不一致"):
        compare_record_sets(bf16, four_bit)
