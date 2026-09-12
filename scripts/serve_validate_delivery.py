#!/usr/bin/env python3
"""Validate lightweight model and service delivery component identities."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.model_registry import load_model_manifest, resolve_service_model  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected object")
    return value


def _validate_legacy_components(
    root: Path = ROOT,
    *,
    require_source_ancestor: bool = True,
) -> dict[str, Any]:
    model_path = root / "delivery/model_component.json"
    service_path = root / "delivery/service_component.json"
    model = _load(model_path)
    service = _load(service_path)
    errors: list[str] = []
    if model.get("schema_version") != "tensile-delivery/model-component/v1":
        errors.append("invalid model component schema")
    if service.get("schema_version") != "tensile-delivery/service-component/v1":
        errors.append("invalid service component schema")
    if (
        model.get("model_tier") != "intermediate_development_model"
        or model.get("full_data_final") is not False
        or model.get("production_approved") is not False
    ):
        errors.append("model capability boundary is invalid")
    if service.get("runtime", {}).get("production_alias") is not False:
        errors.append("service must not claim a production alias")
    if service.get("runtime", {}).get("host") != "127.0.0.1":
        errors.append("service must remain loopback-only")
    if service.get("model_component_path") != "delivery/model_component.json":
        errors.append("service/model component binding mismatch")
    registry_path = root / str(model.get("registry_manifest_path", ""))
    try:
        registry = load_model_manifest(registry_path)
    except (OSError, ValueError):
        registry = {}
        errors.append("model registry manifest is invalid")
    if (
        model.get("model_name") != registry.get("model_name")
        or model.get("component_name") != registry.get("model_name")
        or model.get("artifact", {}).get("managed_remote_path")
        != registry.get("artifacts", {}).get("merged", {}).get("managed_path")
        or model.get("artifact", {}).get("aggregate_sha256")
        != registry.get("artifacts", {}).get("merged", {}).get(
            "aggregate_sha256"
        )
    ):
        errors.append("model component/registry binding mismatch")
    policy = model.get("intermediate_delivery_policy", {})
    if (
        policy.get("primary_gate") != "artifact_and_runtime_chain"
        or policy.get("performance_metrics_mode") != "record_only_non_blocking"
        or policy.get("performance_thresholds_block_delivery") is not False
        or policy.get("optimization_status") != "paused"
        or policy.get("retraining_authorized") is not False
    ):
        errors.append("intermediate delivery performance policy is invalid")
    artifact_gate = model.get("artifact_gate", {})
    required_artifact_checks = (
        "merged_bf16_present",
        "expected_safetensors_shards_present",
        "full_hash_verified",
        "manifest_identity_verified",
    )
    if (
        artifact_gate.get("passed") is not True
        or not all(artifact_gate.get(name) is True for name in required_artifact_checks)
    ):
        errors.append("model artifact gate is incomplete")
    runtime_gate = service.get("runtime_gate", {})
    required_runtime_checks = (
        "contract_identity_verified",
        "deployment_identity_verified",
        "loopback_only_verified",
        "real_media_smoke_passed",
        "v2_rollback_rehearsal_passed",
    )
    if (
        runtime_gate.get("passed") is not True
        or not all(runtime_gate.get(name) is True for name in required_runtime_checks)
    ):
        errors.append("service runtime gate is incomplete")
    for binding, owner in (
        (model.get("evidence", {}), "acceptance_summary"),
        (service.get("evidence", {}), "deployment_summary"),
    ):
        path = root / str(binding.get(f"{owner}_path", ""))
        expected = binding.get(f"{owner}_sha256")
        if not path.is_file() or _sha256(path) != expected:
            errors.append(f"{owner} hash mismatch")
    deployment = root / str(service.get("deployment_manifest_path", ""))
    if (
        not deployment.is_file()
        or _sha256(deployment) != service.get("deployment_manifest_sha256")
    ):
        errors.append("deployment manifest hash mismatch")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_commits = {
        model.get("source_repository_commit"),
        service.get("source_repository_commit"),
    }
    if len(source_commits) != 1 or not next(iter(source_commits), None):
        errors.append("source repository commit binding mismatch")
    elif require_source_ancestor:
        source_commit = str(next(iter(source_commits)))
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_commit, head],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if ancestry.returncode != 0:
            errors.append("source repository commit is not an ancestor of HEAD")
    return {
        "schema_version": "tensile-delivery/component-validation/v1",
        "model_component_sha256": _sha256(model_path),
        "service_component_sha256": _sha256(service_path),
        "repository_commit": head,
        "errors": errors,
        "passed": not errors,
    }


def validate_components(root: Path, *, alias: str | None = None,
                        service_mode: str | None = None) -> dict[str, Any]:
    """Validate current Registry eligibility, not historical development exemptions."""
    if alias is None or service_mode is None:
        raise ValueError("explicit alias and service_mode are required")
    binding = resolve_service_model(root, alias=alias, service_mode=service_mode)
    return {**binding, "passed": True, "runtime_verified": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--alias", choices=("candidate", "production"), required=True)
    parser.add_argument("--service-mode", choices=("development", "production"), required=True)
    args = parser.parse_args()
    report = validate_components(args.root, alias=args.alias, service_mode=args.service_mode)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
