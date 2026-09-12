from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from pipeline.current_data import current_data_context
from pipeline.data_roots import DataRootError
from pipeline.data_rebuild import (
    ALLOWED_TRANSITIONS,
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
import pipeline.scripts.rebuild_data as rebuild_cli
import pipeline.data_rebuild as rebuild_module
from pipeline.scripts.rebuild_data import (
    _artifact_bytes,
    _candidate_space_requirement,
    _estimate_candidate_media_bytes,
    _space_guard,
    _roi_discovered_schema,
)
from pipeline.source_bootstrap import canonical_bytes, sha256_file
from pipeline.v4_1_training_release import (
    RELEASE_SCHEMA_VERSION_V2,
    canonical_release_identity_bytes,
)


# 快照 payload 统计常量（真实 bootstrap 形态；供多个 fixture 共用）
_SOURCE_STATS = {
    "video_count": 2,
    "tag_count": 3,
    "mapping_count": 2,
    "material_difference_count": 0,
    "media_difference_count": 1,
}
_SPLIT_N_FOLDS = 5
_SPLIT_TEST_IDS = ["video-a", "video-b"]


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
            # 测试修正（reviewer P2 后续）：真实链路中 source_bootstrap
            # 无条件生成快照 payload；fixture 须携带真实形态 payload，
            # 以便 promote 的索引重建 fail-closed 语义可成立。
            if name == "source_snapshot":
                (artifact / "validation_report.json").write_text(
                    json.dumps(
                        {"status": "passed", **_SOURCE_STATS},
                        sort_keys=True,
                    )
                    + "\n"
                )
            elif name == "split_snapshot":
                (artifact / "split_decision.json").write_text(
                    json.dumps(
                        {"n_folds": _SPLIT_N_FOLDS, "seed": 42},
                        sort_keys=True,
                    )
                    + "\n"
                )
                (artifact / "test.json").write_text(
                    json.dumps(
                        {
                            "split": "test",
                            "video_ids": list(_SPLIT_TEST_IDS),
                            "count": len(_SPLIT_TEST_IDS),
                        },
                        sort_keys=True,
                    )
                    + "\n"
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


def test_roi_schema_discovery_dispatches_v1_v2_and_rejects_unknown(
    tmp_path: Path,
) -> None:
    context = current_data_context(tmp_path)

    def write(root: Path, artifact_id: str, schema: str) -> None:
        directory = root / artifact_id
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": schema,
                    "roi_manifest_id": artifact_id,
                }
            )
        )

    legacy_root = context.legacy_metadata_collection("roi_manifests")
    semantic_root = context.metadata_collection("roi_manifests")
    write(legacy_root, "roi-manifest-v1", "tensile-roi-manifest/v1")
    write(semantic_root, "roi-manifest-v2", "tensile-roi-manifest/v2")
    write(semantic_root, "roi-manifest-unknown", "tensile-roi-manifest/v999")

    assert (
        _roi_discovered_schema(context, "roi-manifest-v1")
        == "tensile-roi-manifest/v1"
    )
    assert (
        _roi_discovered_schema(context, "roi-manifest-v2")
        == "tensile-roi-manifest/v2"
    )
    with pytest.raises(DataRebuildError, match="不受支持"):
        _roi_discovered_schema(context, "roi-manifest-unknown")

    write(legacy_root, "roi-manifest-conflict", "tensile-roi-manifest/v1")
    write(semantic_root, "roi-manifest-conflict", "tensile-roi-manifest/v2")
    with pytest.raises(DataRebuildError, match="冲突"):
        _roi_discovered_schema(context, "roi-manifest-conflict")


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


# --- Defect #4: review 模式首跑 source_snapshotted -> waiting_for_roi_review ---


def test_update_state_allows_source_snapshotted_to_waiting_for_roi_review(
    tmp_path: Path,
) -> None:
    # #4-A: review 模式首次运行（无 staged roi_decisions.json）需要从
    # source_snapshotted 直接跳入 waiting_for_roi_review 等待人工标注。
    state = {"state": "source_snapshotted"}

    updated = update_state(tmp_path, state, "waiting_for_roi_review")

    assert updated["state"] == "waiting_for_roi_review"


def test_update_state_rejects_promoted_to_waiting_for_roi_review(
    tmp_path: Path,
) -> None:
    # #4-A 过宽实现护栏：promoted 不得允许跳入 waiting_for_roi_review。
    with pytest.raises(DataRebuildError, match="状态不能回退|非法状态跳转"):
        update_state(tmp_path, {"state": "promoted"}, "waiting_for_roi_review")


@pytest.mark.parametrize(
    ("current", "target", "legal"),
    (
        ("roi_validated", "waiting_for_roi_review", True),
        ("waiting_for_roi_review", "roi_media_ready", True),
        ("source_snapshotted", "roi_validated", True),
        ("initialized", "waiting_for_roi_review", False),
        ("source_validated", "waiting_for_roi_review", False),
        ("roi_validated", "candidate_media_ready", False),
        ("candidate_media_ready", "promoted", False),
        ("waiting_for_roi_review", "candidate_media_ready", False),
    ),
)
def test_allowed_transitions_roi_review_boundaries_guard(
    tmp_path: Path, current: str, target: str, legal: bool
) -> None:
    # #4-C 回归护栏：既有 ALLOWED_TRANSITIONS 边界不变；所有用例均为
    # STATES 中的前向或同级目标，隔离 ALLOWED_TRANSITIONS 而非回退检查。
    if legal:
        assert target in ALLOWED_TRANSITIONS[current]
        updated = update_state(tmp_path, {"state": current}, target)
        assert updated["state"] == target
    else:
        assert target not in ALLOWED_TRANSITIONS[current]
        assert current in ALLOWED_TRANSITIONS
        with pytest.raises(DataRebuildError, match="非法状态跳转"):
            update_state(tmp_path, {"state": current}, target)


# --- TODO #3: promote 须传播 source/split 集合 index.json 与 LATEST ---


def _ready_run_with_snapshot_payloads(
    project: Path,
) -> tuple[Path, dict[str, str]]:
    """ready_to_promote staging with bootstrap-shaped snapshot payloads.

    source snapshot 目录携带 validation_report.json（含计数统计），
    split snapshot 目录携带 split_decision.json 与 test.json（真实布局），
    以便 promote 能从被晋级快照内容构造 index entry 的 stats 字段。
    """
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
        state = update_state(run, state, stage, artifacts=outputs)
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
            if name == "source_snapshot":
                (artifact / "source_manifest.json").write_text(
                    json.dumps({"artifact": name}) + "\n"
                )
                (artifact / "validation_report.json").write_text(
                    json.dumps(
                        {"status": "passed", **_SOURCE_STATS},
                        sort_keys=True,
                    )
                    + "\n"
                )
            elif name == "split_snapshot":
                (artifact / "split_manifest.json").write_text(
                    json.dumps({"artifact": name}) + "\n"
                )
                (artifact / "split_decision.json").write_text(
                    json.dumps(
                        {"n_folds": _SPLIT_N_FOLDS, "seed": 42},
                        sort_keys=True,
                    )
                    + "\n"
                )
                (artifact / "test.json").write_text(
                    json.dumps(
                        {
                            "split": "test",
                            "video_ids": list(_SPLIT_TEST_IDS),
                            "count": len(_SPLIT_TEST_IDS),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
            else:
                (artifact / "manifest.json").write_text(
                    json.dumps({"artifact": name}) + "\n"
                )
        entries.append((name, artifact, current.root / prefix / leaf))
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


def test_promote_writes_snapshot_collection_indexes(
    tmp_path: Path,
) -> None:
    """TODO #3-A: promote 后正式 source/split 集合具备 index entry 与 LATEST。"""
    from pipeline.artifact_index import read_index

    project = tmp_path / "repo"
    run, fingerprint = _ready_run_with_snapshot_payloads(project)

    promote(
        project,
        run,
        expected_git_commit="abc123",
        current_source_fingerprint=fingerprint,
    )

    current = current_data_context(project)
    source_collection = current.metadata_collection("source_snapshots")
    split_collection = current.metadata_collection("split_snapshots")

    source_ids = [
        entry["id"] for entry in read_index(source_collection)
    ]
    assert source_ids == ["source-snapshot-test"]
    source_entry = read_index(source_collection)[0]
    assert source_entry["step"] == "source"
    assert source_entry["inputs"] == {}
    assert source_entry["stats"] == _SOURCE_STATS
    assert (
        (source_collection / "LATEST").read_text().strip()
        == "source-snapshot-test"
    )

    split_ids = [entry["id"] for entry in read_index(split_collection)]
    assert split_ids == ["split_snapshot-test"]
    split_entry = read_index(split_collection)[0]
    assert split_entry["step"] == "source"
    assert split_entry["inputs"] == {
        "source_snapshot": "source-snapshot-test"
    }
    assert split_entry["stats"] == {
        "fold_count": _SPLIT_N_FOLDS,
        "test_count": len(_SPLIT_TEST_IDS),
    }
    assert (
        (split_collection / "LATEST").read_text().strip()
        == "split_snapshot-test"
    )


def test_promote_index_updates_are_idempotent_on_reentry(
    tmp_path: Path,
) -> None:
    """TODO #3-B: already_present 重入不重复追加 entry、不改变 LATEST。"""
    from pipeline.artifact_index import read_index

    project = tmp_path / "repo"
    run, fingerprint = _ready_run_with_snapshot_payloads(project)

    promote(
        project,
        run,
        expected_git_commit="abc123",
        current_source_fingerprint=fingerprint,
    )
    current = current_data_context(project)
    source_collection = current.metadata_collection("source_snapshots")
    split_collection = current.metadata_collection("split_snapshots")
    source_before = read_index(source_collection)
    split_before = read_index(split_collection)
    source_latest_before = (source_collection / "LATEST").read_text()
    split_latest_before = (split_collection / "LATEST").read_text()

    repeated = promote(
        project,
        run,
        expected_git_commit="abc123",
        current_source_fingerprint=fingerprint,
    )
    assert all(
        item["status"] == "already_present"
        for item in repeated["journal"]
    )

    assert [entry["id"] for entry in read_index(source_collection)] == [
        "source-snapshot-test"
    ]
    assert [entry["id"] for entry in read_index(split_collection)] == [
        "split_snapshot-test"
    ]
    assert read_index(source_collection) == source_before
    assert read_index(split_collection) == split_before
    assert (source_collection / "LATEST").read_text() == (
        source_latest_before
    )
    assert (split_collection / "LATEST").read_text() == split_latest_before


def test_promote_index_updates_fail_when_promote_lock_held(
    tmp_path: Path,
) -> None:
    """TODO #3-C: 互斥锁被占用时 promote 报错，不静默丢失索引更新。"""
    import fcntl

    project = tmp_path / "repo"
    run, fingerprint = _ready_run_with_snapshot_payloads(project)
    current = current_data_context(project)
    lock_path = current.root / ".locks/v4-1-promote.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(
            lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
        )
        with pytest.raises(DataRebuildError, match="互斥锁"):
            promote(
                project,
                run,
                expected_git_commit="abc123",
                current_source_fingerprint=fingerprint,
            )
        assert not (
            current.metadata_collection("source_snapshots")
            / "index.json"
        ).exists()
        assert not (
            current.metadata_collection("split_snapshots") / "index.json"
        ).exists()


# --- Reviewer P2/P3-a: promote 索引重建必须 fail-closed（DataRebuildError） ---


def _staging_snapshot(run: Path, name: str) -> Path:
    """定位 ready_to_promote staging 中的 source/split 快照目录。"""
    prefix = PROMOTION_PREFIXES[name]
    leaf = (
        "source-snapshot-test"
        if name == "source_snapshot"
        else f"{name}-test"
    )
    return run / "data" / prefix / leaf


def _refresh_promotion_entry_hash(run: Path, artifact: Path, name: str) -> None:
    """fixture 破坏 payload 后重算 promotion manifest 中对应 entry 的 tree hash。

    以便 promote 的哈希校验通过、缺陷恰好落在索引重建 fail-closed 路径，
    而不是被更早的「晋级源缺失或漂移」拦截。
    """
    manifest_path = run / "control/promotion.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["entries"]:
        if entry["name"] == name:
            entry["tree_sha256"] = tree_inventory(artifact)["tree_sha256"]
    manifest_path.write_text(json.dumps(manifest))


def _promote_ready(
    project: Path,
    run: Path,
    fingerprint: dict[str, str],
) -> dict:
    return promote(
        project,
        run,
        expected_git_commit="abc123",
        current_source_fingerprint=fingerprint,
    )


def test_promote_fails_closed_when_source_validation_report_missing(
    tmp_path: Path,
) -> None:
    """P2: source 快照缺 validation_report.json → fail-closed，不静默 promoted。"""
    project = tmp_path / "repo"
    run, fingerprint = _ready_run_with_snapshot_payloads(project)
    artifact = _staging_snapshot(run, "source_snapshot")
    (artifact / "validation_report.json").unlink()
    _refresh_promotion_entry_hash(run, artifact, "source_snapshot")

    with pytest.raises(DataRebuildError, match="validation_report"):
        _promote_ready(project, run, fingerprint)

    # promote 不得静默置 promoted、不得留下已晋级快照。
    state = json.loads((run / "control/rebuild.json").read_text())
    assert state["state"] != "promoted"
    current = current_data_context(project)
    assert not (
        current.metadata_collection("source_snapshots") / "index.json"
    ).exists()


def test_promote_fails_closed_when_split_decision_missing(
    tmp_path: Path,
) -> None:
    """P2: split 快照缺 split_decision.json → fail-closed。"""
    project = tmp_path / "repo"
    run, fingerprint = _ready_run_with_snapshot_payloads(project)
    artifact = _staging_snapshot(run, "split_snapshot")
    (artifact / "split_decision.json").unlink()
    _refresh_promotion_entry_hash(run, artifact, "split_snapshot")

    with pytest.raises(DataRebuildError, match="split_decision"):
        _promote_ready(project, run, fingerprint)

    state = json.loads((run / "control/rebuild.json").read_text())
    assert state["state"] != "promoted"
    current = current_data_context(project)
    assert not (
        current.metadata_collection("split_snapshots") / "index.json"
    ).exists()


def test_promote_fails_closed_when_split_test_json_missing(
    tmp_path: Path,
) -> None:
    """P2: split 快照缺 test.json → fail-closed。"""
    project = tmp_path / "repo"
    run, fingerprint = _ready_run_with_snapshot_payloads(project)
    artifact = _staging_snapshot(run, "split_snapshot")
    (artifact / "test.json").unlink()
    _refresh_promotion_entry_hash(run, artifact, "split_snapshot")

    with pytest.raises(DataRebuildError, match="test\\.json"):
        _promote_ready(project, run, fingerprint)

    state = json.loads((run / "control/rebuild.json").read_text())
    assert state["state"] != "promoted"


def test_promote_fails_closed_when_validation_report_missing_key(
    tmp_path: Path,
) -> None:
    """P3-a: validation_report.json 缺必要 key → DataRebuildError（非 KeyError）。"""
    project = tmp_path / "repo"
    run, fingerprint = _ready_run_with_snapshot_payloads(project)
    artifact = _staging_snapshot(run, "source_snapshot")
    report_path = artifact / "validation_report.json"
    report = json.loads(report_path.read_text())
    del report["video_count"]
    report_path.write_text(json.dumps(report, sort_keys=True) + "\n")
    _refresh_promotion_entry_hash(run, artifact, "source_snapshot")

    with pytest.raises(DataRebuildError, match="video_count"):
        _promote_ready(project, run, fingerprint)

    state = json.loads((run / "control/rebuild.json").read_text())
    assert state["state"] != "promoted"


def test_promote_fails_closed_when_split_decision_missing_key(
    tmp_path: Path,
) -> None:
    """P3-a: split_decision.json 缺 n_folds → DataRebuildError（非 KeyError）。"""
    project = tmp_path / "repo"
    run, fingerprint = _ready_run_with_snapshot_payloads(project)
    artifact = _staging_snapshot(run, "split_snapshot")
    decision_path = artifact / "split_decision.json"
    decision = json.loads(decision_path.read_text())
    del decision["n_folds"]
    decision_path.write_text(json.dumps(decision, sort_keys=True) + "\n")
    _refresh_promotion_entry_hash(run, artifact, "split_snapshot")

    with pytest.raises(DataRebuildError, match="n_folds"):
        _promote_ready(project, run, fingerprint)

    state = json.loads((run / "control/rebuild.json").read_text())
    assert state["state"] != "promoted"


@pytest.mark.parametrize("module_name", ["release_build", "release_build_phase2", "rebuild_data"])
def test_retired_data_cli_stops_before_legacy_selection(module_name, monkeypatch, capsys):
    import importlib
    import sys
    module = importlib.import_module("pipeline.scripts." + module_name)
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy selection or dispatch reached")
    for name in ["parse_args", "build_parser", "current_data_context", "current_data_paths"]:
        if hasattr(module, name):
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(sys, "argv", [module_name, "--run-root", "/must-not-write"])
    assert module.main() == 2
    assert "python -m versioning" in capsys.readouterr().err


@pytest.mark.parametrize("script", ["release_build.py", "release_build_phase2.py", "rebuild_data.py"])
def test_retired_data_script_has_no_write_cli(script, tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / "pipeline/scripts" / script)]
    result = subprocess.run(command + ["--releases-dir", str(tmp_path / "output")],
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 2
    assert "python -m versioning" in result.stderr
    assert not (tmp_path / "output").exists()
    help_result = subprocess.run(command + ["--help"], cwd=tmp_path, text=True, capture_output=True)
    assert help_result.returncode == 0
    assert "已停用" in help_result.stdout


@pytest.mark.parametrize("module", ["roi_freeze_decisions", "roi_materialize_videos", "subvideo_build_plan", "subvideo_materialize_media", "review_build_queue", "review_build_phase2_queues", "review_route_from_history"])
def test_retired_auxiliary_cli_rejects_without_business_imports(module, tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    for prefix in ([sys.executable, "-S", str(root / "pipeline/scripts" / (module + ".py"))],
                   [sys.executable, "-S", "-m", "pipeline.scripts." + module]):
        for arguments, expected in (([], 2), (["--legacy"], 2),
                                    (["--output-dir", str(tmp_path / "output")], 2),
                                    (["--check-only"], 2), (["--help"], 0), (["-h"], 0)):
            result = subprocess.run(prefix + arguments, cwd=root, text=True, capture_output=True)
            assert result.returncode == expected, result.stderr
            assert "python -m versioning data" in result.stdout + result.stderr
            assert not (tmp_path / "output").exists()
