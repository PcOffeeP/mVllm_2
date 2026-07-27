import json
from pathlib import Path

import pytest

from finetune.v4_1_manifest_runtime import ManifestRuntimeError, atomic_json, launch_singleton, sha256_file


def manifest(tmp_path: Path) -> Path:
    marker = tmp_path / "input"
    marker.write_text("frozen")
    path = tmp_path / "run_manifest.json"
    atomic_json(path, {"immutable": True, "run_id": "test-run", "repo_root": str(tmp_path), "state_path": str(tmp_path / "state.json"), "log_root": str(tmp_path / "logs"), "input_sha256": {"input": sha256_file(marker)}, "commands": {"train": ["/bin/sh", "-c", "true", "test-run"]}}, immutable=True)
    return path


def test_manifest_drift_fails_closed(tmp_path: Path):
    path = manifest(tmp_path)
    (tmp_path / "input").write_text("drift")
    with pytest.raises(ManifestRuntimeError):
        launch_singleton(path, "train")


def test_single_phase_launch_records_pid(tmp_path: Path):
    state = launch_singleton(manifest(tmp_path), "train")
    assert state["phase"] == "train"
    assert isinstance(state["pid"], int)
