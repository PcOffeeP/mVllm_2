from __future__ import annotations

import json
from pathlib import Path

import pytest

from finetune.archive.freeze_v4_1_source_aware_3k_evidence import (
    StageBEvidenceError,
    _verify_gate_report,
    _verify_trainer_state,
    _write_immutable,
)


def test_gate_report_requires_both_seeds_to_pass(tmp_path: Path) -> None:
    path = tmp_path / "gates.json"
    payload = {
        "schema_version": "tensile-vlm-v4.1-source-aware-3k-gates/v1",
        "run_id": "v4_1_phase2_source_aware_3k_dd89b70e9d63",
        "release_id": "v4.1.0-ecb5aeb9657c",
        "passed": True,
        "seeds": [
            {"seed": 3407, "passed": True},
            {"seed": 3411, "passed": True},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _verify_gate_report(path)["passed"] is True

    payload["seeds"][1]["passed"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StageBEvidenceError, match="两个 seed"):
        _verify_gate_report(path)


def test_trainer_state_requires_exact_1125_steps(tmp_path: Path) -> None:
    path = tmp_path / "trainer_state.json"
    path.write_text(
        json.dumps({"global_step": 1125, "epoch": 3.0, "log_history": [{}]}),
        encoding="utf-8",
    )
    assert _verify_trainer_state(path)["global_step"] == 1125

    path.write_text(
        json.dumps({"global_step": 1124, "log_history": [{}]}),
        encoding="utf-8",
    )
    with pytest.raises(StageBEvidenceError, match="1125"):
        _verify_trainer_state(path)


def test_immutable_evidence_refuses_drift(tmp_path: Path) -> None:
    target = tmp_path / "evidence"
    manifest = {"schema_version": "test/v1", "evidence_id": "x"}
    _write_immutable(target, manifest)
    _write_immutable(target, manifest)

    with pytest.raises(StageBEvidenceError, match="拒绝覆盖"):
        _write_immutable(target, {**manifest, "evidence_id": "y"})
