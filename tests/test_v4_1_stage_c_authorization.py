from __future__ import annotations

import json
from pathlib import Path

import pytest

from finetune.authorize_v4_1_stage_c import (
    StageCAuthorizationError,
    _write_immutable,
    build_authorization,
)
from finetune.run_v4_1_source_aware_3k import (
    RELEASE_ID,
    RUN_ID,
    SAMPLING_ID,
    SEEDS,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _gate_report() -> dict:
    return {
        "schema_version": "tensile-vlm-v4.1-source-aware-3k-gates/v1",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "passed": True,
        "seeds": [
            {"seed": seed, "passed": True}
            for seed in SEEDS
        ],
    }


def _evidence() -> dict:
    return {
        "schema_version": "tensile-vlm-v4.1-source-aware-3k-evidence/v1",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "sampling_id": SAMPLING_ID,
        "model_hash_mode": "full",
        "trainer_states": {
            str(seed): {"global_step": 1125}
            for seed in SEEDS
        },
        "adapter_coverage": {
            str(seed): {
                "visual": True,
                "visual_weight_count": 1,
                "resampler_weight_count": 1,
                "resampler_saved": True,
            }
            for seed in SEEDS
        },
        "model_artifacts": {
            f"seed{seed}_{role}": {
                "hash_mode": "full",
                "aggregate_sha256": "a" * 64,
            }
            for seed in SEEDS
            for role in ("adapter", "merged_bf16")
        },
    }


def test_authorizes_only_passed_full_hash_evidence(tmp_path: Path) -> None:
    gates = tmp_path / "gates.json"
    evidence = tmp_path / "evidence.json"
    _write(gates, _gate_report())
    _write(evidence, _evidence())

    authorization_id, payload = build_authorization(
        gate_report_path=gates,
        evidence_manifest_path=evidence,
    )

    assert authorization_id.startswith("stage-c-authorization-")
    assert payload["stage_b_passed"] is True
    assert payload["stage_c_authorized"] is True


def test_rejects_metadata_only_model_hashes(tmp_path: Path) -> None:
    gates = tmp_path / "gates.json"
    evidence = tmp_path / "evidence.json"
    payload = _evidence()
    payload["model_hash_mode"] = "metadata"
    _write(gates, _gate_report())
    _write(evidence, payload)

    with pytest.raises(StageCAuthorizationError, match="full model hashes"):
        build_authorization(
            gate_report_path=gates,
            evidence_manifest_path=evidence,
        )


def test_rejects_one_failed_seed(tmp_path: Path) -> None:
    gates = tmp_path / "gates.json"
    evidence = tmp_path / "evidence.json"
    payload = _gate_report()
    payload["seeds"][1]["passed"] = False
    _write(gates, payload)
    _write(evidence, _evidence())

    with pytest.raises(StageCAuthorizationError, match="双 seed"):
        build_authorization(
            gate_report_path=gates,
            evidence_manifest_path=evidence,
        )


def test_authorization_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "stage_c_authorization.json"
    _write_immutable(path, {"authorization_id": "a"})
    _write_immutable(path, {"authorization_id": "a"})

    with pytest.raises(StageCAuthorizationError, match="拒绝覆盖"):
        _write_immutable(path, {"authorization_id": "b"})
