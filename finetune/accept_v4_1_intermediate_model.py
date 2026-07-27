#!/usr/bin/env python3
"""Freeze a user-approved Stage B intermediate model without hiding failed quality gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = (
    ROOT / "finetune/policies/v4_1_intermediate_model_acceptance.json"
)
DEFAULT_RESULT_ROOT = (
    ROOT
    / "finetune/results"
    / "v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3"
)
DEFAULT_ADAPTER = (
    ROOT
    / "LlamaFactory/saves/minicpmv4_5/lora"
    / "sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3_seed3407"
)
DEFAULT_MERGED = DEFAULT_ADAPTER.with_name(f"{DEFAULT_ADAPTER.name}_merged")
DEFAULT_CONTRACT = ROOT / "pipeline/contracts/tensile_vlm_v4_1.json"
MODEL_METADATA_NAMES = {
    "adapter_config.json",
    "all_results.json",
    "chat_template.jinja",
    "config.json",
    "eval_results.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "preprocessor_config.json",
    "processor_config.json",
    "tokenizer_config.json",
    "train_results.json",
    "trainer_state.json",
}


class IntermediateAcceptanceError(ValueError):
    """The intermediate-model policy or its bound artifacts are invalid."""


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntermediateAcceptanceError(f"无法读取 {label}: {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise IntermediateAcceptanceError(f"证据文件不存在: {path}")
    return {"size_bytes": path.stat().st_size, "sha256": _sha256(path)}


def _aggregate_identity(files: Mapping[str, Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _model_identity(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        raise IntermediateAcceptanceError(f"模型目录不存在: {path}")
    selected = [
        child
        for child in sorted(path.iterdir())
        if child.is_file()
        and (child.name in MODEL_METADATA_NAMES or child.suffix == ".safetensors")
    ]
    if not selected or not any(path.suffix == ".safetensors" for path in selected):
        raise IntermediateAcceptanceError(f"模型目录缺少 safetensors: {path}")
    files = {child.name: _identity(child) for child in selected}
    return {
        "path_at_freeze": str(path.resolve()),
        "hash_mode": "full",
        "files": files,
        "aggregate_sha256": _aggregate_identity(files),
    }


def _canonical_contract_hash(contract: Mapping[str, Any]) -> str:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    return hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise IntermediateAcceptanceError("无法读取仓库 HEAD")
    return result.stdout.strip()


def _validate_policy(policy: Mapping[str, Any]) -> None:
    if (
        policy.get("schema_version")
        != "tensile-vlm-v4.1-stage-b-intermediate-policy/v1"
        or policy.get("stage_b_status")
        != "accepted_as_intermediate_with_known_limits"
        or policy.get("decision_basis")
        != "user_directed_no_additional_retraining_for_current_version"
    ):
        raise IntermediateAcceptanceError("Stage B intermediate policy 身份非法")
    scope = policy.get("authorization_scope")
    disclosure = policy.get("quality_disclosure")
    if (
        not isinstance(scope, Mapping)
        or scope.get("stage_c_additional_training") is not False
        or scope.get("stage_e_pre_acceptance_integration") is not True
        or scope.get("stage_f_agent_integration") is not True
        or scope.get("stage_d_independent_model_acceptance") is not False
        or scope.get("production_alias") is not False
        or not isinstance(disclosure, Mapping)
        or disclosure.get("original_stage_b_performance_gate_passed") is not False
        or disclosure.get("leave_one_source_out_gate_passed") is not False
        or disclosure.get("sealed_labels_read") is not False
    ):
        raise IntermediateAcceptanceError("intermediate policy 授权范围被扩大")


def build_acceptance(
    *,
    policy_path: Path,
    result_root: Path,
    adapter_dir: Path,
    merged_dir: Path,
    contract_path: Path,
) -> tuple[str, dict[str, Any]]:
    policy = _read_json(policy_path, "intermediate policy")
    if not isinstance(policy, Mapping):
        raise IntermediateAcceptanceError("intermediate policy 必须为对象")
    _validate_policy(policy)
    seed = int(policy["seed"])
    training_manifest_path = result_root / f"seed{seed}/training_run_manifest.json"
    evaluation_root = result_root / f"seed{seed}/fold0"
    evaluation_summary_path = evaluation_root / "evaluation_summary.json"
    evaluation_records_path = evaluation_root / "evaluation_records.jsonl"
    runtime_failures_path = evaluation_root / "runtime_failures.csv"
    gate_report_path = result_root / f"seed{seed}_canary_gate_report.json"

    training_identity = _identity(training_manifest_path)
    records_identity = _identity(evaluation_records_path)
    gate_identity = _identity(gate_report_path)
    if training_identity["sha256"] != policy["training_run_manifest_sha256"]:
        raise IntermediateAcceptanceError("training run manifest SHA256 漂移")
    if records_identity["sha256"] != policy["evaluation_records_sha256"]:
        raise IntermediateAcceptanceError("evaluation records SHA256 漂移")
    if gate_identity["sha256"] != policy["failed_quality_gate_report_sha256"]:
        raise IntermediateAcceptanceError("failed quality gate report SHA256 漂移")

    training = _read_json(training_manifest_path, "training run manifest")
    summary = _read_json(evaluation_summary_path, "evaluation summary")
    gate = _read_json(gate_report_path, "failed quality gate report")
    contract = _read_json(contract_path, "runtime contract")
    required = policy["minimum_artifact_gate"]
    coverage = training.get("adapter_coverage") if isinstance(training, Mapping) else None
    if (
        not isinstance(training, Mapping)
        or training.get("run_id") != policy["source_run_id"]
        or training.get("release_id") != policy["release_id"]
        or training.get("sampling_id") != policy["sampling_id"]
        or training.get("seed") != seed
        or training.get("actual_optimizer_steps")
        != required["actual_optimizer_steps"]
        or not isinstance(coverage, Mapping)
        or coverage.get("visual") is not True
        or coverage.get("resampler_saved") is not True
        or coverage.get("visual_weight_count") != required["visual_weight_count"]
        or coverage.get("resampler_weight_count")
        != required["resampler_weight_count"]
    ):
        raise IntermediateAcceptanceError("训练步数、身份或视觉 adapter 覆盖不完整")
    record_count = sum(
        bool(line.strip())
        for line in evaluation_records_path.read_text(encoding="utf-8").splitlines()
    )
    if (
        not isinstance(summary, Mapping)
        or summary.get("release_id") != policy["release_id"]
        or summary.get("contract_hash") != policy["training_contract_hash"]
        or summary.get("sample_count") != required["evaluation_sample_count"]
        or summary.get("total_samples") != required["evaluation_sample_count"]
        or record_count != required["evaluation_sample_count"]
        or summary.get("runtime_failure_count") != required["runtime_failure_count"]
        or float(summary.get("strict_valid_rate", 0.0))
        < float(required["minimum_strict_valid_rate"])
    ):
        raise IntermediateAcceptanceError("严格评测完整性门未通过")
    runtime_failures = runtime_failures_path.read_text(encoding="utf-8").splitlines()
    if len([line for line in runtime_failures if line.strip()]) > 1:
        raise IntermediateAcceptanceError("runtime_failures.csv 包含失败记录")
    if (
        not isinstance(gate, Mapping)
        or gate.get("run_id") != policy["source_run_id"]
        or gate.get("release_id") != policy["release_id"]
        or gate.get("seed") != seed
        or gate.get("passed") is not False
    ):
        raise IntermediateAcceptanceError("原质量 gate 必须明确保留 failed 状态")
    actual_contract_hash = (
        _canonical_contract_hash(contract)
        if isinstance(contract, Mapping)
        else None
    )
    if (
        actual_contract_hash != policy["runtime_contract_hash"]
        or contract.get("contract_hash") != actual_contract_hash
    ):
        raise IntermediateAcceptanceError("promoted runtime contract hash 漂移")

    evidence = {
        "policy": _identity(policy_path),
        "training_run_manifest": training_identity,
        "evaluation_summary": _identity(evaluation_summary_path),
        "evaluation_records": records_identity,
        "runtime_failures": _identity(runtime_failures_path),
        "failed_quality_gate_report": gate_identity,
        "runtime_contract": _identity(contract_path),
    }
    models = {
        "adapter": _model_identity(adapter_dir),
        "merged_bf16": _model_identity(merged_dir),
    }
    payload_seed = {
        "schema_version": "tensile-vlm-v4.1-stage-b-intermediate-acceptance/v1",
        "decision_id": policy["decision_id"],
        "run_id": policy["source_run_id"],
        "seed": seed,
        "runtime_contract_hash": policy["runtime_contract_hash"],
        "evidence_aggregate_sha256": _aggregate_identity(evidence),
        "model_aggregate_sha256": _aggregate_identity(
            {
                name: {"sha256": value["aggregate_sha256"], "size_bytes": 0}
                for name, value in models.items()
            }
        ),
    }
    acceptance_id = "stage-b-intermediate-" + hashlib.sha256(
        json.dumps(payload_seed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return acceptance_id, {
        **payload_seed,
        "acceptance_id": acceptance_id,
        "status": "accepted_as_intermediate_with_known_limits",
        "original_stage_b_quality_gate_passed": False,
        "stage_c_additional_training_authorized": False,
        "stage_e_pre_acceptance_integration_authorized": True,
        "stage_f_agent_integration_authorized": True,
        "stage_d_independent_model_acceptance_authorized": False,
        "production_alias_authorized": False,
        "sealed_labels_read": False,
        "acceptance_code_commit": _git_head(),
        "policy": dict(policy),
        "training": {
            "actual_optimizer_steps": training["actual_optimizer_steps"],
            "adapter_coverage": dict(coverage),
            "training_code_commit": training["training_code_commit"],
        },
        "evaluation": {
            "sample_count": summary["sample_count"],
            "strict_valid_rate": summary["strict_valid_rate"],
            "runtime_failure_count": summary["runtime_failure_count"],
            "metrics": summary["metrics"],
        },
        "evidence": evidence,
        "models": models,
    }


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise IntermediateAcceptanceError(f"拒绝覆盖已有 acceptance: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument("--adapter-dir", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--merged-dir", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "finetune/results/v4_1_stage_b_intermediate_acceptances",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    acceptance_id, payload = build_acceptance(
        policy_path=args.policy,
        result_root=args.result_root,
        adapter_dir=args.adapter_dir,
        merged_dir=args.merged_dir,
        contract_path=args.contract,
    )
    output = args.output_root / acceptance_id / "intermediate_model_acceptance.json"
    if not args.validate_only:
        _write_immutable(output, payload)
    print(
        json.dumps(
            {
                "mode": "validate-only" if args.validate_only else "frozen",
                "output": str(output),
                **payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
