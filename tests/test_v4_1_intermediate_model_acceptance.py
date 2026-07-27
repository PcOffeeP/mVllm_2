from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from finetune.accept_v4_1_intermediate_model import (
    IntermediateAcceptanceError,
    build_acceptance,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _fixture(tmp_path: Path) -> dict[str, Path]:
    run_id = "run"
    release_id = "release"
    sampling_id = "sampling"
    result_root = tmp_path / "results"
    seed_root = result_root / "seed3407"
    eval_root = seed_root / "fold0"
    training = {
        "run_id": run_id,
        "release_id": release_id,
        "sampling_id": sampling_id,
        "seed": 3407,
        "actual_optimizer_steps": 1125,
        "training_code_commit": "a" * 40,
        "adapter_coverage": {
            "visual": True,
            "resampler_saved": True,
            "visual_weight_count": 324,
            "resampler_weight_count": 13,
        },
    }
    summary = {
        "release_id": release_id,
        "contract_hash": "old-contract",
        "sample_count": 425,
        "total_samples": 425,
        "strict_valid_rate": 0.995,
        "runtime_failure_count": 0,
        "metrics": {"joint_correct_rate": 0.4},
    }
    gate = {
        "run_id": run_id,
        "release_id": release_id,
        "seed": 3407,
        "passed": False,
    }
    training_path = seed_root / "training_run_manifest.json"
    records_path = eval_root / "evaluation_records.jsonl"
    gate_path = result_root / "seed3407_canary_gate_report.json"
    _write(training_path, training)
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text("{}\n" * 425, encoding="utf-8")
    _write(eval_root / "evaluation_summary.json", summary)
    (eval_root / "runtime_failures.csv").write_text("candidate_id,error\n", encoding="utf-8")
    _write(gate_path, gate)
    contract = {
        "contract_version": "tensile-vlm/v4.1",
        "analysis": {"user_prompt": "clarified"},
    }
    normalized = json.dumps(
        contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    contract["contract_hash"] = hashlib.sha256(normalized).hexdigest()
    contract_path = tmp_path / "contract.json"
    _write(contract_path, contract)
    adapter = tmp_path / "adapter"
    merged = tmp_path / "merged"
    for model in (adapter, merged):
        model.mkdir()
        (model / "model.safetensors").write_bytes(b"weights")
        _write(model / "config.json", {"model": model.name})
    policy = {
        "schema_version": "tensile-vlm-v4.1-stage-b-intermediate-policy/v1",
        "decision_id": "decision",
        "decision_basis": "user_directed_no_additional_retraining_for_current_version",
        "stage_b_status": "accepted_as_intermediate_with_known_limits",
        "source_run_id": run_id,
        "release_id": release_id,
        "sampling_id": sampling_id,
        "seed": 3407,
        "training_contract_hash": "old-contract",
        "runtime_contract_hash": contract["contract_hash"],
        "training_run_manifest_sha256": _sha(training_path),
        "evaluation_records_sha256": _sha(records_path),
        "failed_quality_gate_report_sha256": _sha(gate_path),
        "minimum_artifact_gate": {
            "actual_optimizer_steps": 1125,
            "visual_weight_count": 324,
            "resampler_weight_count": 13,
            "evaluation_sample_count": 425,
            "minimum_strict_valid_rate": 0.99,
            "runtime_failure_count": 0,
        },
        "authorization_scope": {
            "stage_c_additional_training": False,
            "stage_e_pre_acceptance_integration": True,
            "stage_f_agent_integration": True,
            "stage_d_independent_model_acceptance": False,
            "production_alias": False,
        },
        "quality_disclosure": {
            "original_stage_b_performance_gate_passed": False,
            "leave_one_source_out_gate_passed": False,
            "sealed_labels_read": False,
        },
    }
    policy_path = tmp_path / "policy.json"
    _write(policy_path, policy)
    return {
        "policy": policy_path,
        "result_root": result_root,
        "adapter": adapter,
        "merged": merged,
        "contract": contract_path,
        "gate": gate_path,
    }


def test_accepts_complete_model_without_relabeling_failed_quality_gate(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    acceptance_id, payload = build_acceptance(
        policy_path=paths["policy"],
        result_root=paths["result_root"],
        adapter_dir=paths["adapter"],
        merged_dir=paths["merged"],
        contract_path=paths["contract"],
    )
    assert acceptance_id.startswith("stage-b-intermediate-")
    assert payload["original_stage_b_quality_gate_passed"] is False
    assert payload["stage_e_pre_acceptance_integration_authorized"] is True
    assert payload["stage_c_additional_training_authorized"] is False
    assert payload["production_alias_authorized"] is False
    assert payload["models"]["merged_bf16"]["hash_mode"] == "full"


def test_rejects_attempt_to_mark_failed_quality_gate_as_passed(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    gate = json.loads(paths["gate"].read_text(encoding="utf-8"))
    gate["passed"] = True
    _write(paths["gate"], gate)
    policy = json.loads(paths["policy"].read_text(encoding="utf-8"))
    policy["failed_quality_gate_report_sha256"] = _sha(paths["gate"])
    _write(paths["policy"], policy)
    with pytest.raises(IntermediateAcceptanceError, match="failed 状态"):
        build_acceptance(
            policy_path=paths["policy"],
            result_root=paths["result_root"],
            adapter_dir=paths["adapter"],
            merged_dir=paths["merged"],
            contract_path=paths["contract"],
        )
