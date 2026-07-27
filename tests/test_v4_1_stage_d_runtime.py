from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from finetune.v4_1_stage_d_runtime import (
    AUTHORIZATION_SCHEMA_VERSION,
    DEFAULT_THRESHOLDS,
    PREPARATION_SCHEMA_VERSION,
    StageDRuntimeError,
    atomic_write,
    build_authorization,
    build_gate_reports,
    build_preparation,
    build_run_identity,
    claim_one_time_run,
    freeze_preparation,
    git_head,
    load_sealed_release,
    pretty_bytes,
    sha256_bytes,
    validate_authorization,
)
from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_sealed_test_release import (
    READY_STATUS,
    SEALED_GROUND_TRUTH_SCHEMA_VERSION,
    SEALED_TEST_RELEASE_SCHEMA_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, mode)


def _contract(tmp_path: Path) -> Path:
    value: dict[str, object] = {
        "contract_version": "tensile-vlm/v4.1",
        "analysis": {
            "system_prompt": "system",
            "user_prompt": "user",
            "generation": {"max_new_tokens": 128, "do_sample": False},
        },
    }
    value["contract_hash"] = sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    path = tmp_path / "contract.json"
    _write_json(path, value)
    return path


def _labels(state: str) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": None,
        "fracture_site": None,
        "special_case": None,
    }


def _sealed_release(tmp_path: Path, contract_hash: str) -> Path:
    release_id = "v4.1-sealed-test-unit"
    release_dir = tmp_path / release_id
    states = ("未断裂", "临界未断裂", "发生断裂", "已断裂")
    candidates = [
        {
            "candidate_id": f"candidate-{index}",
            "source_video": f"video_{index:04d}",
            "video_path": f"data/video_{index:04d}.mp4",
            "video_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
            "frames": [{"path": f"frame-{index}.jpg", "sha256": "a" * 64}],
            "labels": _labels(state),
        }
        for index, state in enumerate(states, start=1)
    ]
    truth = {
        "schema_version": SEALED_GROUND_TRUTH_SCHEMA_VERSION,
        "release_id": release_id,
        "candidate_count": len(candidates),
        "excluded_count": 0,
        "source_count": len(candidates),
        "candidates": candidates,
        "excluded": [],
    }
    truth_path = release_dir / "metadata/sealed_ground_truth.json"
    _write_json(truth_path, truth)
    manifest = {
        "schema_version": SEALED_TEST_RELEASE_SCHEMA_VERSION,
        "release_id": release_id,
        "status": READY_STATUS,
        "immutable": True,
        "sealed": True,
        "contract_version": "tensile-vlm/v4.1",
        "contract_hash": contract_hash,
        "counts": {
            "admitted_candidates": len(candidates),
            "admitted_sources": len(candidates),
        },
        "access_policy": {"one_time_evaluation_authorized": False},
        "files": [
            {
                "path": "metadata/sealed_ground_truth.json",
                "size_bytes": truth_path.stat().st_size,
                "sha256": sha256_file(truth_path),
                "access": "restricted",
            }
        ],
    }
    _write_json(release_dir / "manifest/release_manifest.json", manifest)
    for directory in (
        release_dir,
        release_dir / "metadata",
        release_dir / "manifest",
    ):
        os.chmod(directory, 0o700)
    return release_dir


def _preparation_fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    contract_path = _contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    release_dir = _sealed_release(tmp_path, contract["contract_hash"])
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    model_aggregate = "1" * 64
    stage_b = {
        "schema_version": (
            "tensile-vlm-v4.1-stage-b-intermediate-acceptance/v1"
        ),
        "acceptance_id": "stage-b-intermediate-test",
        "status": "accepted_as_intermediate_with_known_limits",
        "original_stage_b_quality_gate_passed": False,
        "stage_d_independent_model_acceptance_authorized": False,
        "models": {
            "merged_bf16": {
                "hash_mode": "full",
                "aggregate_sha256": model_aggregate,
                "path_at_freeze": str(model_dir.resolve()),
            }
        },
    }
    stage_b_path = tmp_path / "stage_b.json"
    _write_json(stage_b_path, stage_b)
    deployment = {
        "acceptance_id": "stage-b-intermediate-test",
        "contract_hash": contract["contract_hash"],
        "model_aggregate_sha256": model_aggregate,
        "authorization_scope": {
            "stage_d_independent_model_acceptance": False
        },
    }
    deployment_path = tmp_path / "deployment.json"
    _write_json(deployment_path, deployment)
    agent = {
        "agent_acceptance_id": "agent-acceptance-test",
        "agent_runtime_commit": "2" * 40,
        "stage_b_intermediate_acceptance_id": "stage-b-intermediate-test",
        "visual_contract_hash": contract["contract_hash"],
        "heldout_semantics_opened": False,
    }
    agent_path = tmp_path / "agent.json"
    _write_json(agent_path, agent)
    runner = tmp_path / "runner.py"
    evaluator = tmp_path / "evaluator.py"
    runner.write_text("runner\n", encoding="utf-8")
    evaluator.write_text("evaluator\n", encoding="utf-8")
    preparation = build_preparation(
        project_root=ROOT,
        release_dir=release_dir,
        model_dir=model_dir,
        model_aggregate_sha256=model_aggregate,
        stage_b_acceptance_path=stage_b_path,
        deployment_summary_path=deployment_path,
        agent_acceptance_summary_path=agent_path,
        contract_path=contract_path,
        runner_path=runner,
        evaluator_path=evaluator,
        output_root=tmp_path / "runs",
    )
    prepared_path = tmp_path / "prepared.json"
    freeze_preparation(prepared_path, preparation)
    return preparation, prepared_path


def test_builds_stable_preparation_and_validates_authorization(
    tmp_path: Path,
) -> None:
    preparation, prepared_path = _preparation_fixture(tmp_path)
    assert preparation["schema_version"] == PREPARATION_SCHEMA_VERSION
    assert preparation["authorization"]["authorized"] is False
    assert preparation["sealed_test"]["sample_count"] == 4

    authorization = build_authorization(
        prepared_manifest_path=prepared_path,
        authorized_by="pcoffeep",
        user_authorization_reference="thread-message:test",
        authorized_at="2026-07-27T00:00:00+00:00",
    )
    assert authorization["schema_version"] == AUTHORIZATION_SCHEMA_VERSION
    authorization_path = tmp_path / "authorization.json"
    atomic_write(authorization_path, pretty_bytes(authorization))
    loaded_preparation, loaded_authorization = validate_authorization(
        authorization_path,
        prepared_manifest_path=prepared_path,
    )
    run_identity = build_run_identity(
        loaded_preparation,
        loaded_authorization,
    )
    assert run_identity["identity"]["sample_count"] == 4


def test_claim_is_idempotent_for_same_run_and_rejects_other_run(
    tmp_path: Path,
) -> None:
    preparation, prepared_path = _preparation_fixture(tmp_path)
    authorization = build_authorization(
        prepared_manifest_path=prepared_path,
        authorized_by="pcoffeep",
        user_authorization_reference="thread-message:test",
        authorized_at="2026-07-27T00:00:00+00:00",
    )
    run_identity = build_run_identity(preparation, authorization)
    claim_path = tmp_path / "claim.json"
    first = claim_one_time_run(
        claim_path,
        run_identity=run_identity,
        authorization=authorization,
    )
    second = claim_one_time_run(
        claim_path,
        run_identity=run_identity,
        authorization=authorization,
    )
    assert second == first

    other = json.loads(json.dumps(run_identity))
    other["run_id"] = "stage-d-run-other"
    with pytest.raises(StageDRuntimeError, match="其他 Stage D run"):
        claim_one_time_run(
            claim_path,
            run_identity=other,
            authorization=authorization,
        )


def test_public_gate_withholds_semantic_metrics() -> None:
    states = ("未断裂", "临界未断裂", "发生断裂", "已断裂")
    records = [
        {
            "candidate_id": f"candidate-{index}",
            "target": _labels(state),
            "prediction": _labels(state),
            "strict_valid": True,
            "runtime_error": None,
            "scores": {"joint_correct": True},
        }
        for index, state in enumerate(states)
    ]
    run_identity = {
        "run_id": "stage-d-run-test",
        "identity": {"sample_count": 4},
    }
    restricted, public = build_gate_reports(
        run_identity=run_identity,
        records=records,
        thresholds=DEFAULT_THRESHOLDS,
    )
    assert restricted["passed"] is True
    assert "metrics" in restricted
    assert public["passed"] is True
    assert "metrics" not in public
    assert all(set(row) == {"passed"} for row in public["gates"].values())


def test_sealed_release_rejects_relaxed_permissions(tmp_path: Path) -> None:
    contract_path = _contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    release_dir = _sealed_release(tmp_path, contract["contract_hash"])
    manifest, candidates, _ = load_sealed_release(release_dir)
    assert manifest["release_id"] == "v4.1-sealed-test-unit"
    assert len(candidates) == 4
    truth_path = release_dir / "metadata/sealed_ground_truth.json"
    os.chmod(truth_path, 0o644)
    with pytest.raises(StageDRuntimeError, match="权限"):
        load_sealed_release(release_dir)
