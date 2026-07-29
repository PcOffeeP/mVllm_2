from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from pipeline.current_data import (
    LEGACY_REBUILD_LAYOUT,
    current_data_paths,
    create_staging_context,
    data_context_for_root,
    inspect_legacy_context,
    resume_staging_context,
)
import pipeline.current_data as current_data_module
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
    root = project / "workspace/data-staging/rebuild-123/data"
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
    with pytest.raises(DataRootError, match="staging data root"):
        data_context_for_root(project, project / "workspace/data")

    context = data_context_for_root(
        project,
        project / "workspace/data-staging/rebuild-123/data",
    )
    with pytest.raises(DataRootError, match="父目录跳转"):
        context.resolve_artifact("../outside")
    with pytest.raises(DataRootError, match="无法映射"):
        context.resolve_artifact(tmp_path / "other/video.mp4")


def test_rebuild_context_maps_frozen_absolute_paths(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    context = data_context_for_root(
        project,
        project / "workspace/data-staging/rebuild-123/data",
    )

    assert context.resolve_artifact(
        "/old/repo/data/01_videos/video_0001.mp4"
    ) == context.videos / "video_0001.mp4"
    assert context.resolve_artifact(
        "/old/repo/workspace/data/derived/frames/frame.jpg"
    ) == context.frames / "frame.jpg"


def test_candidate_plan_paths_do_not_embed_rebuild_id(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    alpha = project / "workspace/data-staging/alpha/data"
    beta = project / "workspace/data-staging/beta/data"

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
        project / f"workspace/data-staging/{name}/data"
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


def test_inspect_legacy_context_is_read_only_and_requires_frozen_roots(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    run = project / "workspace/data-rebuild/legacy-run"
    data = run / "data"
    data.mkdir(parents=True)
    state = {
        "run_root": str(run.resolve()),
        "data_root": str(data.resolve()),
        "git_commit": "producer-commit",
    }
    control = run / "control"
    control.mkdir()
    (control / "rebuild.json").write_text(json.dumps(state))

    inspected = inspect_legacy_context(project, run)

    assert inspected["layout_profile"] == LEGACY_REBUILD_LAYOUT
    assert inspected["producer_git_commit"] == "producer-commit"
    with pytest.raises(DataRootError, match="legacy run"):
        inspect_legacy_context(
            project,
            project / "workspace/data-rebuild/missing",
        )


def test_staging_create_gate_and_resume_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "repo"
    run = project / "workspace/data-staging/run-1"
    monkeypatch.setattr(
        current_data_module,
        "SEMANTIC_STAGING_CREATE_ENABLED",
        False,
    )
    with pytest.raises(DataRootError, match="gate"):
        create_staging_context(project, run)

    data = run / "data"
    data.mkdir(parents=True)
    control = run / "control"
    control.mkdir()
    (control / "rebuild.json").write_text(
        json.dumps(
            {
                "schema_version": "tensile-v4.1-data-rebuild/v2",
                "layout_profile": "semantic-staging-v2",
                "run_root": str(run.resolve()),
                "data_root": str(data.resolve()),
                "git_commit": "producer",
            }
        )
    )
    assert resume_staging_context(project, run, "producer").root == data
    with pytest.raises(DataRootError, match="身份不匹配"):
        resume_staging_context(project, run, "different")


def test_resume_rejects_symlinked_run_or_data_root(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    real = project / "workspace/data-staging/real"
    data = real / "data"
    data.mkdir(parents=True)
    control = real / "control"
    control.mkdir()
    (control / "rebuild.json").write_text(
        json.dumps(
            {
                "schema_version": "tensile-v4.1-data-rebuild/v2",
                "layout_profile": "semantic-staging-v2",
                "run_root": str(real.resolve()),
                "data_root": str(data.resolve()),
                "git_commit": "producer",
            }
        )
    )
    alias = project / "workspace/data-staging/alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(DataRootError, match="物理目录"):
        resume_staging_context(project, alias, "producer")

    alias.unlink()
    moved = project / "workspace/data-staging/other/data"
    moved.mkdir(parents=True)
    data.rmdir()
    data.symlink_to(moved, target_is_directory=True)
    with pytest.raises(DataRootError, match="物理目录"):
        resume_staging_context(project, real, "producer")


def test_writer_output_guard_rejects_legacy_and_versioned_roots(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    context = current_data_paths(project)
    managed = context.metadata_collection("review_queues")

    assert context.require_managed_output(
        managed / "queue-id",
        managed,
        label="queue output",
    ) == (managed / "queue-id").resolve()
    for forbidden in (
        project
        / "workspace/data-rebuild/run/data/derived/metadata/v4_1/review_queues",
        context.metadata / "v4_1/review_queues",
        tmp_path / "outside",
    ):
        with pytest.raises(DataRootError, match="必须位于"):
            context.require_managed_output(
                forbidden,
                managed,
                label="queue output",
            )
    managed.mkdir(parents=True)
    outside = tmp_path / "symlink-target"
    outside.mkdir()
    (managed / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DataRootError, match="symlink"):
        context.require_managed_output(
            managed / "linked/queue-id",
            managed,
            label="queue output",
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
