from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pipeline.current_data import current_data_paths
from pipeline.project_workspace import (
    CURRENT_EXPERIMENT_ID,
    ProjectWorkspaceError,
    experiment_workspace_paths,
    project_workspace_paths,
    validate_experiment_id,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_v4_1_paths_are_project_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TENSILE_DATA_HOME", str(tmp_path / "external"))
    paths = current_data_paths(tmp_path / "repo")

    assert paths.root == (tmp_path / "repo/workspace/data").resolve()
    assert paths.training_releases == paths.root / "releases"
    assert paths.compatibility_workspace == paths.root
    assert "tensile-data" not in str(paths.root)


def test_semantic_experiment_id_drives_git_and_run_directories(
    tmp_path: Path,
) -> None:
    paths = experiment_workspace_paths(tmp_path, CURRENT_EXPERIMENT_ID)

    assert paths.git_dir == (
        tmp_path / "finetune/experiments" / CURRENT_EXPERIMENT_ID
    ).resolve()
    assert paths.run_dir == (
        tmp_path / "workspace/runs" / CURRENT_EXPERIMENT_ID
    ).resolve()
    assert paths.input == paths.run_dir / "input"
    assert paths.adapter == paths.run_dir / "adapter"
    assert paths.merged == paths.run_dir / "merged"
    assert validate_experiment_id(CURRENT_EXPERIMENT_ID) == CURRENT_EXPERIMENT_ID

    with pytest.raises(ProjectWorkspaceError):
        validate_experiment_id("hash-8fe58f171667")


def test_workspace_is_ignored_by_git() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "workspace/probe"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_project_workspace_has_no_environment_dependency(
    tmp_path: Path,
) -> None:
    before = dict(os.environ)
    paths = project_workspace_paths(tmp_path)
    assert paths.data == tmp_path.resolve() / "workspace/data"
    assert dict(os.environ) == before
