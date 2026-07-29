from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pipeline.current_data import current_data_paths, data_context_for_root
from pipeline.data_roots import DataRootError
from pipeline.project_workspace import (
    CURRENT_EXPERIMENT_ID,
    ProjectWorkspaceError,
    experiment_workspace_paths,
    project_workspace_paths,
    validate_experiment_id,
    validate_model_output_path,
)
from pipeline.v3_candidate_plan import _portable_path
from pipeline.v3_candidate_media import _frame_artifacts
from pipeline.v4_1_review_workflow import _portable_identity_path

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


def test_rebuild_context_maps_legacy_paths_inside_isolated_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    root = project / "workspace/data-rebuild/rebuild-123/data"
    context = data_context_for_root(project, root)

    assert context.root == root.resolve()
    assert context.resolve_artifact("data/01_videos/video_0001.mp4") == (
        root / "source/videos/video_0001.mp4"
    ).resolve()
    assert (
        context.semantic_path("data/01_videos/video_0001.mp4")
        == "source/videos/video_0001.mp4"
    )


def test_rebuild_context_rejects_wrong_root_and_path_escape(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    with pytest.raises(DataRootError, match="rebuild data root"):
        data_context_for_root(project, project / "workspace/data")

    context = data_context_for_root(
        project,
        project / "workspace/data-rebuild/rebuild-123/data",
    )
    with pytest.raises(DataRootError, match="父目录跳转"):
        context.resolve_artifact("../outside")
    with pytest.raises(DataRootError, match="无法映射"):
        context.resolve_artifact(tmp_path / "other/video.mp4")


def test_rebuild_context_maps_frozen_absolute_paths(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    context = data_context_for_root(
        project,
        project / "workspace/data-rebuild/rebuild-123/data",
    )

    assert context.resolve_artifact(
        "/old/repo/data/01_videos/video_0001.mp4"
    ) == context.videos / "video_0001.mp4"
    assert context.resolve_artifact(
        "/old/repo/workspace/data/derived/frames/frame.jpg"
    ) == context.frames / "frame.jpg"


def test_candidate_plan_paths_do_not_embed_rebuild_id(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    alpha = project / "workspace/data-rebuild/alpha/data"
    beta = project / "workspace/data-rebuild/beta/data"

    assert _portable_path(
        alpha / "derived/roi_videos/batch/manifest.json",
        alpha,
    ) == _portable_path(
        beta / "derived/roi_videos/batch/manifest.json",
        beta,
    )


def test_candidate_and_review_paths_do_not_embed_rebuild_id(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    roots = [
        project / f"workspace/data-rebuild/{name}/data"
        for name in ("alpha", "beta")
    ]
    artifacts = []
    for root in roots:
        frame_dir = root / "derived/frames/plan/candidate"
        frame_dir.mkdir(parents=True)
        (frame_dir / "frame_0000.jpg").write_bytes(b"same-frame")
        artifacts.append(_frame_artifacts(frame_dir, root))

    assert artifacts[0] == artifacts[1]
    assert _portable_identity_path(
        roots[0] / "derived/metadata/results/manifest.json",
        roots[0],
    ) == _portable_identity_path(
        roots[1] / "derived/metadata/results/manifest.json",
        roots[1],
    )


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
    assert paths.models == tmp_path.resolve() / "workspace/models"
    assert paths.model_releases == paths.models / "releases"
    assert paths.model_archive == paths.models / "archive"
    assert dict(os.environ) == before


def test_model_outputs_must_stay_under_workspace_runs(tmp_path: Path) -> None:
    expected = tmp_path / "workspace/runs/experiment/fold0/adapter"
    assert validate_model_output_path(tmp_path, expected) == expected.resolve()

    with pytest.raises(ProjectWorkspaceError, match="workspace/runs"):
        validate_model_output_path(
            tmp_path,
            "LlamaFactory/saves/minicpmv4_5/lora/model",
        )
