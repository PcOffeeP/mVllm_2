from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from finetune.archive.run_v4_1_visual_three_fold import (
    FOLDS as VISUAL_FOLDS,
)
from finetune.v4_1_runtime import (
    CONTRACT_HASH,
    RELEASE_ID,
    V4_1FinetuneError,
    parse_v4_1_output,
    score_v4_1_prediction,
    summarize_v4_1_scores,
    validate_release,
    validate_training_row,
    _validate_v2_snapshot_binding,
)
from pipeline.v4_1_training_release import (
    canonical_release_identity_bytes,
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
    if not (
        ROOT
        / "workspace/data/releases"
        / RELEASE_ID
    ).is_dir():
        pytest.skip("project-local V4.1 workspace data is not present")
    result = validate_release(ROOT)

    assert result["release_id"] == RELEASE_ID
    assert result["contract_hash"] == CONTRACT_HASH
    assert result["split_counts"]["fold_0_train"] == 850


def test_release_validation_uses_explicit_expected_contract_hash() -> None:
    if not (
        ROOT
        / "workspace/data/releases"
        / RELEASE_ID
    ).is_dir():
        pytest.skip("project-local V4.1 workspace data is not present")

    with pytest.raises(V4_1FinetuneError, match="contract_hash 漂移"):
        validate_release(
            ROOT,
            expected_contract_hash="0" * 64,
        )


def test_v2_release_requires_complete_snapshot_provenance() -> None:
    manifest = {
        "source_snapshot_id": None,
        "split_snapshot_id": None,
        "provenance": {},
    }
    with pytest.raises(V4_1FinetuneError, match="snapshot binding"):
        _validate_v2_snapshot_binding(manifest)

    provenance = {
        "data_version": "4.1.0",
        "release_schema_version": "tensile-training-release/v4.1-v2",
        "source_snapshot_id": "source-snapshot-0123456789ab",
        "split_snapshot_id": "split-snapshot-0123456789ab",
        "source_snapshot_tree_sha256": "1" * 64,
        "split_snapshot_tree_sha256": "2" * 64,
        "source_snapshot_manifest_sha256": "3" * 64,
        "split_snapshot_manifest_sha256": "4" * 64,
    }
    canonical = canonical_release_identity_bytes(provenance)
    valid = {
        "source_snapshot_id": provenance["source_snapshot_id"],
        "split_snapshot_id": provenance["split_snapshot_id"],
        "provenance": provenance,
        "release_id": (
            "v4.1.0-" + hashlib.sha256(canonical).hexdigest()[:12]
        ),
    }
    _validate_v2_snapshot_binding(valid)
    attacked = json.loads(json.dumps(valid))
    attacked["source_snapshot_id"] = "source-snapshot-fedcba987654"
    attacked["provenance"]["source_snapshot_id"] = (
        "source-snapshot-fedcba987654"
    )
    attacked["provenance"]["source_snapshot_tree_sha256"] = "f" * 64
    with pytest.raises(V4_1FinetuneError, match="canonical identity"):
        _validate_v2_snapshot_binding(attacked)


def test_formal_visual_configs_keep_release_and_safe_memory_recipe() -> None:
    for fold in VISUAL_FOLDS:
        config = yaml.safe_load(fold.train_config.read_text(encoding="utf-8"))
        assert config["dataset"] == f"tensile_v4_1_fold{fold.index}_train"
        assert config["freeze_vision_tower"] is False
        assert config["additional_target"] == "resampler"
        assert config["quantization_bit"] == 4
        assert config["optim"] == "adamw_torch"


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
