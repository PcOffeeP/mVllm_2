#!/usr/bin/env python3
"""Validate lightweight model and service delivery component identities."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


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


def validate_components(
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    report = validate_components(
        args.root.resolve(),
        require_source_ancestor=True,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
