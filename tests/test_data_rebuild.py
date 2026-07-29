from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from pipeline.current_data import current_data_context
from pipeline.data_roots import DataRootError
from pipeline.data_rebuild import (
    DataRebuildError,
    PROMOTION_PREFIXES,
    append_jsonl,
    build_promotion_manifest,
    has_completed_stage_record,
    initialize_state,
    promote,
    rebuild_paths,
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
from pipeline.source_bootstrap import canonical_bytes, sha256_file
from pipeline.v4_1_training_release import (
    RELEASE_SCHEMA_VERSION_V2,
    canonical_release_identity_bytes,
)


def _formal_gate_artifacts(data: Path) -> tuple[Path, Path, str]:
    queue_identity = {"queue_id": "queue-test"}
    decisions_records: list[dict] = []
    batch_digest = hashlib.sha256(
        canonical_bytes(
            {
                "queue_identity": queue_identity,
                "decisions": decisions_records,
            }
        )
    ).hexdigest()
    batch_id = f"review-batch-{batch_digest[:12]}"
    batch = (
        data
        / "derived/metadata/review_decisions/queue-test"
        / batch_id
    )
    batch.mkdir(parents=True)
    decisions = batch / "decisions.json"
    decisions.write_text(
        json.dumps(
            {
                "schema_version": "tensile-review-decision/v4.1",
                "batch_id": batch_id,
                "decisions": decisions_records,
            },
            sort_keys=True,
        )
    )
    (batch / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "tensile-review-workspace/v4.1",
                "batch_id": batch_id,
                "queue_identity": queue_identity,
                "artifacts": {
                    "decisions.json": {"sha256": sha256_file(decisions)}
                },
            },
            sort_keys=True,
        )
    )

    provenance = {
        "data_version": "4.1.0",
        "release_schema_version": RELEASE_SCHEMA_VERSION_V2,
        "source_snapshot_id": "source-snapshot-test",
        "split_snapshot_id": "split-snapshot-test",
        "source_snapshot_tree_sha256": "1" * 64,
        "split_snapshot_tree_sha256": "2" * 64,
        "source_snapshot_manifest_sha256": "3" * 64,
        "split_snapshot_manifest_sha256": "4" * 64,
    }
    release_id = (
        "v4.1.0-"
        + hashlib.sha256(
            canonical_release_identity_bytes(provenance)
        ).hexdigest()[:12]
    )
    release = data / "releases" / release_id
    payloads = {
        "dataset_info.json": b"{}\n",
        "metadata/training_candidates.json": b"{}\n",
        "reports/quality_report.json": b"{}\n",
    }
    files = []
    for relative, content in payloads.items():
        path = release / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        files.append(
            {
                "path": relative,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schema_version": RELEASE_SCHEMA_VERSION_V2,
        "release_id": release_id,
        "status": "training_ready",
        "immutable": True,
        "source_snapshot_id": provenance["source_snapshot_id"],
        "split_snapshot_id": provenance["split_snapshot_id"],
        "provenance": provenance,
        "files": files,
    }
    manifest_path = release / "manifest/release_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    return decisions, release, release_id


def _ready_run(project: Path) -> tuple[Path, dict[str, str]]:
    run = project / "workspace/data-staging/rebuild-test"
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
    data = run / "data"
    decisions, release, release_id = _formal_gate_artifacts(data)
    final_artifacts = {
        "review_decisions": str(decisions),
        "review_decisions_tree_sha256": tree_inventory(decisions.parent)[
            "tree_sha256"
        ],
        "release": str(release),
        "release_id": release_id,
        "release_tree_sha256": tree_inventory(release)["tree_sha256"],
    }
    for stage in (
        "source_validated",
        "source_snapshotted",
        "roi_validated",
        "roi_media_ready",
        "candidate_media_ready",
        "review_validated",
        "release_validated",
    ):
        outputs = final_artifacts if stage == "release_validated" else {}
        state = update_state(
            run,
            state,
            stage,
            artifacts=outputs,
        )
        append_jsonl(
            run / "control/commands.jsonl",
            {
                "schema_version": "tensile-v4.1-stage-completion/v1",
                "stage": stage,
                "record_status": "completed",
                "git_commit": "abc123",
                "outputs": outputs,
            },
        )
        if stage == "release_validated":
            append_jsonl(
                run / "control/commands.jsonl",
                {
                    "schema_version": "tensile-v4.1-stage-completion/v1",
                    "stage": stage,
                    "record_status": "completed",
                    "git_commit": "abc123",
                    "outputs": outputs,
                },
            )
    entries = []
    for name, prefix in PROMOTION_PREFIXES.items():
        leaf = (
            "source-snapshot-test"
            if name == "source_snapshot"
            else release_id
            if name == "release"
            else f"queue-test/{decisions.parent.name}"
            if name == "review_decisions"
            else f"{name}-test"
        )
        artifact = data / prefix / leaf
        if name not in {"review_decisions", "release"}:
            artifact.mkdir(parents=True)
            (artifact / "manifest.json").write_text(
                json.dumps({"artifact": name}) + "\n"
            )
        entries.append(
            (
                name,
                artifact,
                current.root / prefix / leaf,
            )
        )
    build_promotion_manifest(
        project,
        run,
        entries,
        release_name="release",
        source_fingerprint=source_fingerprint,
        git_commit="abc123",
    )
    state = update_state(run, state, "ready_to_promote")
    append_jsonl(
        run / "control/commands.jsonl",
        {
            "schema_version": "tensile-v4.1-stage-completion/v1",
            "stage": "ready_to_promote",
            "record_status": "completed",
            "git_commit": "abc123",
            "outputs": {},
        },
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
    assert {row["name"] for row in result["entries"]} == set(
        PROMOTION_PREFIXES
    )
    assert result["entries"][-1]["name"] == "release"
    current = current_data_context(project)
    release_id = json.loads(
        (run / "control/rebuild.json").read_text()
    )["artifacts"]["release_id"]
    assert (current.training_releases / release_id).is_dir()
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

    with pytest.raises(DataRebuildError, match="安全相对路径|allowlist"):
        promote(
            project,
            run,
            expected_git_commit="abc123",
            current_source_fingerprint=fingerprint,
        )


def test_promote_revalidates_allowlist_after_manifest_tampering(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)
    manifest_path = run / "control/promotion.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["target"] = (
        "derived/metadata/v3/source_snapshots/source-snapshot-test"
    )
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(DataRebuildError, match="allowlist"):
        promote(
            project,
            run,
            expected_git_commit="abc123",
            current_source_fingerprint=fingerprint,
        )


def test_promote_rejects_truncated_inventory_before_release_move(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)
    manifest_path = run / "control/promotion.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"] = [
        entry
        for entry in manifest["entries"]
        if entry["name"] in {"source_snapshot", "release"}
    ]
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(DataRebuildError, match="entry 集不完整"):
        promote(
            project,
            run,
            expected_git_commit="abc123",
            current_source_fingerprint=fingerprint,
        )
    assert not (
        current_data_context(project).training_releases / "v4.1.0-test"
    ).exists()


def test_promote_preflights_all_parent_symlinks_before_any_move(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)
    current = current_data_context(project)
    legacy = current.metadata / "v3/source_snapshots"
    legacy.mkdir(parents=True)
    semantic = current.metadata_collection("source_snapshots")
    semantic.symlink_to(legacy, target_is_directory=True)

    with pytest.raises(DataRebuildError, match="symlink"):
        promote(
            project,
            run,
            expected_git_commit="abc123",
            current_source_fingerprint=fingerprint,
        )

    assert not any(legacy.iterdir())
    release_id = json.loads(
        (run / "control/rebuild.json").read_text()
    )["artifacts"]["release_id"]
    assert not (current.training_releases / release_id).exists()


def test_promotion_manifest_rejects_control_or_wrong_semantic_target(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    run, fingerprint = _ready_run(project)
    current = current_data_context(project)
    (run / "control/promotion.json").unlink()
    forbidden = run / "data/control/chain-validation"
    forbidden.mkdir(parents=True)
    (forbidden / "report.json").write_text("{}")
    release = run / "data/releases/release-test"
    release.mkdir(parents=True)
    (release / "manifest.json").write_text("{}")

    with pytest.raises(DataRebuildError, match="allowlist"):
        build_promotion_manifest(
            project,
            run,
            [
                (
                    "source_snapshot",
                    forbidden,
                    current.metadata
                    / "source_snapshots/source-snapshot-test",
                ),
                ("release", release, current.training_releases / release.name),
            ],
            release_name="release",
            source_fingerprint=fingerprint,
            git_commit="abc123",
        )


def test_promotion_manifest_requires_completed_release_and_human_gate(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    run = project / "workspace/data-staging/rebuild-test"
    initialize_state(
        project,
        run,
        roi_mode="review",
        review_mode="review",
        source_identity={"fingerprint": "same"},
        git_commit="abc123",
    )

    with pytest.raises(DataRebuildError, match="release_validated"):
        build_promotion_manifest(
            project,
            run,
            [],
            release_name="release",
            source_fingerprint={"fingerprint": "same"},
            git_commit="abc123",
        )
    assert not (run / "control/promotion.json").exists()


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
    run = project / "workspace/data-staging/rebuild-test"
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


def test_rebuild_paths_rejects_forged_existing_state(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    run = project / "workspace/data-staging/forged"
    (run / "data").mkdir(parents=True)
    (run / "control").mkdir()
    (run / "control/rebuild.json").write_text(
        json.dumps(
            {
                "schema_version": "forged",
                "layout_profile": "legacy-rebuild-v1",
                "run_root": str(run.resolve()),
                "data_root": str((run / "data").resolve()),
                "git_commit": "abc123",
            }
        )
    )

    with pytest.raises(DataRootError, match="schema/layout/root/Git"):
        rebuild_paths(project, run)


def test_rebuild_paths_rejects_symlink_alias(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    run = project / "workspace/data-staging/real"
    initialize_state(
        project,
        run,
        roi_mode="reuse",
        review_mode="reuse",
        source_identity={"fingerprint": "same"},
        git_commit="abc123",
    )
    alias = project / "workspace/data-staging/alias"
    alias.symlink_to(run, target_is_directory=True)

    with pytest.raises(DataRebuildError, match="symlink"):
        rebuild_paths(project, alias)


def test_stage_wal_fails_closed_between_state_and_completion_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "repo"
    run = project / "workspace/data-staging/rebuild-test"
    state = initialize_state(
        project,
        run,
        roi_mode="reuse",
        review_mode="reuse",
        source_identity={"fingerprint": "same"},
        git_commit="abc123",
    )
    for stage in (
        "source_validated",
        "source_snapshotted",
        "roi_validated",
        "roi_media_ready",
        "candidate_media_ready",
        "review_validated",
        "release_validated",
    ):
        state = update_state(run, state, stage)
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
