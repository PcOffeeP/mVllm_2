from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.model_registry import (
    CURRENT_SCHEMA_VERSION,
    MODEL_SCHEMA_VERSION,
    ModelRegistryError,
    load_current_model,
    parse_model_name,
    validate_model_manifest,
)


def _manifest() -> dict:
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_name": "v4.1-agent-pipeline-fold0-r1",
        "protocol_version": "v4.1",
        "core_purpose": "agent-pipeline",
        "training_scope": "fold0",
        "round": 1,
        "lifecycle_status": "current",
        "contract": {
            "version": "tensile-vlm/v4.1",
            "sha256": "a" * 64,
        },
        "artifacts": {
            name: {
                "managed_path": (
                    "workspace/models/releases/"
                    f"v4.1-agent-pipeline-fold0-r1/{name}"
                ),
                "path_at_freeze": f"/old/{name}",
                "aggregate_sha256": ("b" if name == "adapter" else "c") * 64,
            }
            for name in ("adapter", "merged")
        },
    }


def test_model_name_exposes_all_four_required_parts() -> None:
    parsed = parse_model_name("v4.1-agent-pipeline-fold0-r1")

    assert parsed.protocol_version == "v4.1"
    assert parsed.core_purpose == "agent-pipeline"
    assert parsed.training_scope == "fold0"
    assert parsed.round == 1

    for invalid in (
        "coverage-first-seed3407",
        "v4.1-agent-pipeline-r1",
        "v4.1-agent-pipeline-fold0",
        "v4.1-agent-pipeline-fold0-r0",
    ):
        with pytest.raises(ModelRegistryError):
            parse_model_name(invalid)


def test_manifest_identity_must_match_model_name() -> None:
    manifest = _manifest()
    assert validate_model_manifest(manifest)["model_name"] == manifest["model_name"]

    manifest["training_scope"] = "full"
    with pytest.raises(ModelRegistryError, match="training_scope"):
        validate_model_manifest(manifest)


def test_managed_artifacts_cannot_escape_workspace_models() -> None:
    manifest = _manifest()
    manifest["artifacts"]["merged"]["managed_path"] = (
        "LlamaFactory/saves/model"
    )
    with pytest.raises(ModelRegistryError, match="workspace/models"):
        validate_model_manifest(manifest)


def test_current_pointer_resolves_exact_release(tmp_path: Path) -> None:
    root = tmp_path
    registry = root / "pipeline/model_registry"
    releases = registry / "releases"
    releases.mkdir(parents=True)
    manifest = _manifest()
    (releases / f"{manifest['model_name']}.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (registry / "current.json").write_text(
        json.dumps(
            {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "model_name": manifest["model_name"],
                "manifest_path": (
                    "pipeline/model_registry/releases/"
                    f"{manifest['model_name']}.json"
                ),
                "aggregate_sha256": manifest["artifacts"]["merged"][
                    "aggregate_sha256"
                ],
            }
        ),
        encoding="utf-8",
    )

    current, loaded = load_current_model(root)
    assert current["model_name"] == loaded["model_name"]
