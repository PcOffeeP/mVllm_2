from __future__ import annotations

import json
from pathlib import Path

import pytest

from finetune.v4_1_runtime import (
    CONTRACT_HASH,
    RELEASE_ID,
    V4_1FinetuneError,
    parse_v4_1_output,
    score_v4_1_prediction,
    summarize_v4_1_scores,
    validate_release,
    validate_training_config,
    validate_training_row,
)

ROOT = Path(__file__).resolve().parents[1]


def _labels(state: str = "临界未断裂") -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": "韧性断裂" if state == "临界未断裂" else None,
        "fracture_site": "inside_gauge" if state == "临界未断裂" else None,
        "special_case": None,
    }


def test_committed_release_and_configs_are_v4_1_bound() -> None:
    result = validate_release(ROOT)

    assert result["release_id"] == RELEASE_ID
    assert result["contract_hash"] == CONTRACT_HASH
    assert result["split_counts"]["fold_0_train"] == 850
    for fold in range(3):
        config = validate_training_config(
            ROOT / f"finetune/MiniCPM/config/train_v4_1_fold{fold}.yaml",
            fold=fold,
            project_root=ROOT,
        )
        assert config["dataset"] == f"tensile_v4_1_fold{fold}_train"
        assert config["eval_dataset"] == f"tensile_v4_1_fold{fold}_val"


def test_training_row_and_output_use_exact_four_fields() -> None:
    labels = _labels()
    row = {
        "videos": ["data/example.mp4"],
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "<video>\nuser"},
            {
                "role": "assistant",
                "content": json.dumps(labels, ensure_ascii=False),
            },
        ],
    }

    assert validate_training_row(row) == ("data/example.mp4", labels)
    assert parse_v4_1_output(json.dumps(labels, ensure_ascii=False)) == labels


def test_rejects_legacy_v2_output() -> None:
    with pytest.raises(V4_1FinetuneError, match="不符合 V4.1"):
        parse_v4_1_output(
            '{"has_fracture":true,"fracture_between":[1,2],'
            '"type":"韧性断裂","location":"inside_gauge"}'
        )


def test_v4_1_metrics_score_fields_and_joint() -> None:
    target = _labels()
    correct = score_v4_1_prediction(target, target)
    wrong = score_v4_1_prediction(target, _labels("未断裂"))
    summary = summarize_v4_1_scores([correct, wrong])

    assert correct["joint_correct"] is True
    assert wrong["clip_state_correct"] is False
    assert summary["contract_valid_rate"] == 1.0
    assert summary["joint_correct_rate"] == 0.5
    assert summary["special_case_correct_rate"] == 1.0

