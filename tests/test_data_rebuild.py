from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.current_data import current_data_context
from pipeline.data_rebuild import (
    DataRebuildError,
    append_jsonl,
    build_promotion_manifest,
    has_completed_stage_record,
    initialize_state,
    promote,
    tree_inventory,
    update_state,
)
import pipeline.scripts.rebuild_v4_1_data as rebuild_cli
import pipeline.data_rebuild as rebuild_module
from pipeline.scripts.rebuild_v4_1_data import (
    _artifact_bytes,
    _candidate_space_requirement,
    _estimate_candidate_media_bytes,
    _space_guard,
)


def _ready_run(project: Path) -> tuple[Path, dict[str, str]]:
    run = project / "workspace/data-rebuild/rebuild-test"
    current = current_data_context(project)
    current.root.mkdir(parents=True)
    source_fingerprint = {"source_snapshot_id": "source-snapshot-test"}
    state = initialize_state(
        project,
        run,
        roi_mode="reuse",
        review_mode="reuse",
        source_identity=source_fingerprint,
        git_commit="abc123",
    )
    state = update_state(run, state, "ready_to_promote")
    append_jsonl(
        run / "control/commands.jsonl",
        {
            "stage": "ready_to_promote",
            "record_status": "completed",
        },
    )
    data = run / "data"
    artifact = data / "derived/metadata/source_snapshots/source-snapshot-test"
    release = data / "releases/v4.1.0-test"
    artifact.mkdir(parents=True)
    release.mkdir(parents=True)
    (artifact / "manifest.json").write_text('{"artifact": true}\n')
    (release / "manifest.json").write_text('{"release": true}\n')
    build_promotion_manifest(
        project,
        run,
        [
            (
                "source_snapshot",
                artifact,
                current.metadata / "source_snapshots/source-snapshot-test",
            ),
            (
                "release",
                release,
                current.training_releases / "v4.1.0-test",
            ),
        ],
        release_name="release",
        source_fingerprint=source_fingerprint,
        git_commit="abc123",
    )
    assert state["state"] == "ready_to_promote"
    return run, source_fingerprint


def test_promotion_moves_release_last_and_is_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)

    result = promote(
        project,
        run,
        expected_git_commit="abc123",
        current_source_fingerprint=fingerprint,
    )

    assert result["status"] == "promoted"
    assert [row["name"] for row in result["entries"]] == [
        "source_snapshot",
        "release",
    ]
    current = current_data_context(project)
    assert (current.training_releases / "v4.1.0-test").is_dir()
    state = json.loads((run / "control/rebuild.json").read_text())
    assert state["state"] == "promoted"

    repeated = promote(
        project,
        run,
        expected_git_commit="abc123",
        current_source_fingerprint=fingerprint,
    )
    assert all(
        item["status"] == "already_present" for item in repeated["journal"]
    )


def test_promotion_rejects_target_collision(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)
    target = (
        current_data_context(project).metadata
        / "source_snapshots/source-snapshot-test"
    )
    target.mkdir(parents=True)
    (target / "manifest.json").write_text('{"different": true}\n')

    with pytest.raises(DataRebuildError, match="同名但内容不同"):
        promote(
            project,
            run,
            expected_git_commit="abc123",
            current_source_fingerprint=fingerprint,
        )


def test_tree_inventory_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "artifact"
    root.mkdir()
    target = tmp_path / "target"
    target.write_text("x")
    (root / "link").symlink_to(target)

    with pytest.raises(DataRebuildError, match="symlink"):
        tree_inventory(root)


def test_promotion_resolves_cas_inside_lock(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)
    calls: list[str] = []

    result = promote(
        project,
        run,
        expected_git_commit=lambda: calls.append("git") or "abc123",
        current_source_fingerprint=lambda: (
            calls.append("source") or fingerprint
        ),
    )

    assert result["status"] == "promoted"
    assert calls == ["git", "source"]


def test_promotion_rejects_manifest_path_escape(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)
    manifest_path = run / "control/promotion.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["target"] = "../escaped"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(DataRebuildError, match="安全相对路径"):
        promote(
            project,
            run,
            expected_git_commit="abc123",
            current_source_fingerprint=fingerprint,
        )


def test_resume_can_revalidate_completed_stage_without_state_regression(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    run, _ = _ready_run(project)
    state = json.loads((run / "control/rebuild.json").read_text())

    resumed = update_state(
        run,
        state,
        "source_validated",
        artifacts={"source_revalidated": True},
        allow_completed=True,
    )

    assert resumed["state"] == "ready_to_promote"
    assert resumed["artifacts"]["source_revalidated"] is True


def test_commands_jsonl_appends_without_rewriting_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "control/commands.jsonl"
    append_jsonl(path, {"stage": "source_validated", "hash": "a"})
    first = path.read_bytes()
    append_jsonl(path, {"stage": "source_snapshotted", "hash": "b"})

    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert path.read_bytes().startswith(first)
    assert json.loads(lines[0])["stage"] == "source_validated"
    assert json.loads(lines[1])["stage"] == "source_snapshotted"


def test_candidate_space_estimate_uses_plan_duration_frames_and_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roi = tmp_path / "roi"
    video = roi / "videos/video_0001.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x" * 1_000)
    candidate = {
        "source_video": "video_0001",
        "duration": 5.0,
    }
    plan = {
        "development_candidates": [candidate],
        "test_candidate_audit": [],
    }
    inputs = {
        "records": {
            "video_0001": {
                "duration": 10.0,
                "width": 100,
                "height": 200,
            }
        }
    }
    required = _estimate_candidate_media_bytes(plan, inputs, roi)
    per_candidate = 500 + 100 * 200 * 3 * 8 + 64 * 1024
    assert required == per_candidate * 2

    class Usage:
        free = int(required * 1.2) - 1

    monkeypatch.setattr("shutil.disk_usage", lambda _: Usage())
    with pytest.raises(DataRebuildError, match="空间不足"):
        _space_guard(tmp_path / "run", required)


def test_incomplete_existing_candidate_dirs_cannot_reduce_space_guard(
    tmp_path: Path,
) -> None:
    parts = []
    for name in ("videos", "frames", "media"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "partial").write_bytes(b"x")
        parts.append(_artifact_bytes(directory))

    assert _candidate_space_requirement(tuple(parts), 1_092_072) == 1_092_072


def test_resume_rejects_runtime_provenance_drift(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    run = project / "workspace/data-rebuild/rebuild-test"
    common = {
        "project_root": project,
        "run_root": run,
        "roi_mode": "reuse",
        "review_mode": "reuse",
        "source_identity": {"fingerprint": "same"},
        "git_commit": "abc123",
    }
    initialize_state(
        **common,
        runtime_identity={"python_version": "3.12"},
    )

    with pytest.raises(DataRebuildError, match="输入身份不一致"):
        initialize_state(
            **common,
            runtime_identity={"python_version": "3.13"},
        )


def test_stage_wal_fails_closed_between_state_and_completion_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "repo"
    run = project / "workspace/data-rebuild/rebuild-test"
    state = initialize_state(
        project,
        run,
        roi_mode="reuse",
        review_mode="reuse",
        source_identity={"fingerprint": "same"},
        git_commit="abc123",
    )
    real_append = append_jsonl
    calls = 0

    def crash_on_completion(path: Path, payload: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash")
        real_append(path, payload)

    monkeypatch.setattr(rebuild_cli, "append_jsonl", crash_on_completion)
    with pytest.raises(OSError, match="simulated crash"):
        rebuild_cli._record_stage(run, state, "ready_to_promote")

    stored = json.loads((run / "control/rebuild.json").read_text())
    assert stored["state"] == "ready_to_promote"
    assert not has_completed_stage_record(run, "ready_to_promote")


def test_promote_recovers_missing_completion_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)
    real_append = append_jsonl
    calls = 0

    def crash_on_completion(path: Path, payload: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash")
        real_append(path, payload)

    monkeypatch.setattr(rebuild_module, "append_jsonl", crash_on_completion)
    with pytest.raises(OSError, match="simulated crash"):
        promote(
            project,
            run,
            expected_git_commit="abc123",
            current_source_fingerprint=fingerprint,
        )
    assert not has_completed_stage_record(run, "promoted")

    monkeypatch.setattr(rebuild_module, "append_jsonl", real_append)
    recovered = promote(
        project,
        run,
        expected_git_commit="abc123",
        current_source_fingerprint=fingerprint,
    )
    assert recovered["status"] == "promoted"
    assert has_completed_stage_record(run, "promoted")
