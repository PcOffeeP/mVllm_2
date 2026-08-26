from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from pipeline import artifact_index, artifact_resolver
from pipeline.source_bootstrap import canonical_bytes
from pipeline.data_rebuild import tree_inventory
from pipeline.v4_1_review_decisions import build_review_payload, save_review_payload
from pipeline.v4_1_review_workflow import (
    build_v4_1_review_queue,
    load_review_queue,
    new_decision,
    save_v4_1_review_queue,
)
from pipeline.v4_1_training_release import (
    RELEASE_SCHEMA_VERSION_V2,
    V4_1TrainingReleaseError,
    build_v4_1_training_release,
)
from finetune.v4_1_runtime import _validate_v2_snapshot_binding


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _labels(state: str) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": "韧性断裂" if state == "发生断裂" else None,
        "location": "inside_gauge" if state == "发生断裂" else None,
        "root_break": False if state == "发生断裂" else None,
        "special_case": None,
    }


def _candidate(
    root: Path,
    candidate_id: str,
    source_video: str,
    *,
    state: str,
    role: str,
    variant: str | None,
    disposition: str,
) -> dict[str, object]:
    video = root / "data/media" / f"{candidate_id}.mp4"
    frame = root / "data/frames" / candidate_id / "frame_0000.jpg"
    video.parent.mkdir(parents=True, exist_ok=True)
    frame.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(f"video:{candidate_id}".encode())
    frame.write_bytes(f"frame:{candidate_id}".encode())
    return {
        "candidate_id": candidate_id,
        "scope": "development",
        "source_video": source_video,
        "source_type": "韧性断裂",
        "source_location": "inside_gauge",
        "window_role": role,
        "window_variant": variant,
        "review_disposition": disposition,
        "candidate_v3_labels": _labels(state),
        "media_status": "materialized_gate_passed",
        "sampling_gate": {"status": "passed"},
        "video_path": str(video.relative_to(root)),
        "video_sha256": _sha(video),
        "frame_artifacts": [
            {
                "path": str(frame.relative_to(root)),
                "sha256": _sha(frame),
                "size_bytes": frame.stat().st_size,
            }
        ],
        "actual_frame_mapping": [
            {
                "input_index": 0,
                "original_frame": 1,
                "timestamp": 0.1,
                "clip_frame": 0,
                "clip_timestamp": 0.0,
            }
        ],
        "processor_fingerprint": "processor:test",
    }


def _fixture(tmp_path: Path) -> dict[str, Path]:
    contract = {
        "contract_version": "tensile-vlm/v4.1",
        "analysis": {
            "system_prompt": "system",
            "user_prompt": "user",
        },
    }
    contract["contract_hash"] = hashlib.sha256(
        json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    contract_path = tmp_path / "pipeline/contracts/tensile_vlm_v4_1.json"
    _write_json(contract_path, contract)

    candidates = [
        _candidate(
            tmp_path,
            "video_0001_transition",
            "video_0001",
            state="发生断裂",
            role="transition",
            variant=None,
            disposition="manual_required",
        ),
        _candidate(
            tmp_path,
            "video_0001_pre_front",
            "video_0001",
            state="未断裂",
            role="pre_event",
            variant="pre_event_front",
            disposition="automatic_validation",
        ),
        _candidate(
            tmp_path,
            "video_0002_pre_back",
            "video_0002",
            state="未断裂",
            role="pre_event",
            variant="pre_event_back",
            disposition="automatic_validation",
        ),
        _candidate(
            tmp_path,
            "video_0002_pre_front",
            "video_0002",
            state="未断裂",
            role="pre_event",
            variant="pre_event_front",
            disposition="automatic_validation",
        ),
    ]
    materialized = tmp_path / "data/results/development_materialized.json"
    _write_json(
        materialized,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "candidate-media-test",
            "scope": "development",
            "candidates": candidates,
        },
    )
    media_manifest = tmp_path / "data/results/manifest.json"
    _write_json(
        media_manifest,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "candidate-media-test",
            "artifacts": {
                materialized.name: {
                    "sha256": _sha(materialized),
                    "size_bytes": materialized.stat().st_size,
                }
            },
        },
    )

    queue_payload = build_v4_1_review_queue(
        materialized_path=materialized,
        manifest_path=media_manifest,
        project_root=tmp_path,
        contract_path=contract_path,
    )
    queue = tmp_path / "data/review_queue.json"
    save_v4_1_review_queue(queue, queue_payload)
    _, joined = load_review_queue(queue, project_root=tmp_path)
    decisions = [
        new_decision(
            candidate,
            status="approved",
            corrected_labels=None,
            historical_suggested_labels=None,
            historical_reference_ids=[],
            reviewer_notes="",
            reviewer_id="reviewer",
            reviewed_at="2026-07-23T00:00:00+00:00",
        )
        for candidate in joined
    ]
    decisions_path = tmp_path / "data/decisions.json"
    save_review_payload(
        decisions_path,
        build_review_payload(
            decisions,
            batch_id="review-batch-test",
            created_at="2026-07-23T00:00:00+00:00",
        ),
    )

    splits = tmp_path / "data/splits"
    for fold in range(3):
        train = ["video_0001"] if fold % 2 == 0 else ["video_0002"]
        val = ["video_0002"] if fold % 2 == 0 else ["video_0001"]
        _write_json(
            splits / f"fold_{fold}_train.json",
            {"video_ids": train},
        )
        _write_json(
            splits / f"fold_{fold}_val.json",
            {"video_ids": val},
        )
    _write_json(splits / "test.json", {"video_ids": ["video_0099"]})
    return {
        "project_root": tmp_path,
        "materialized": materialized,
        "media_manifest": media_manifest,
        "queue": queue,
        "decisions": decisions_path,
        "contract": contract_path,
        "splits": splits,
        "releases": tmp_path / "data/releases",
    }


def _build(
    paths: dict[str, Path],
    *,
    source_snapshot_id: str | None = None,
    split_snapshot_id: str | None = None,
    source_snapshot_dir: Path | None = None,
    expected_source_tree_hash: str | None = None,
    expected_split_tree_hash: str | None = None,
) -> tuple[Path, dict[str, object]]:
    if source_snapshot_dir is not None:
        expected_source_tree_hash = expected_source_tree_hash or str(
            tree_inventory(source_snapshot_dir)["tree_sha256"]
        )
        expected_split_tree_hash = expected_split_tree_hash or str(
            tree_inventory(paths["splits"])["tree_sha256"]
        )
    return build_v4_1_training_release(
        project_root=paths["project_root"],
        materialized_path=paths["materialized"],
        media_manifest_path=paths["media_manifest"],
        queue_path=paths["queue"],
        decisions_path=paths["decisions"],
        contract_path=paths["contract"],
        splits_dir=paths["splits"],
        releases_dir=paths["releases"],
        source_snapshot_id=source_snapshot_id,
        split_snapshot_id=split_snapshot_id,
        source_snapshot_dir=source_snapshot_dir,
        expected_source_tree_hash=expected_source_tree_hash,
        expected_split_tree_hash=expected_split_tree_hash,
    )


def _semantic_snapshots(paths: dict[str, Path]) -> tuple[Path, Path]:
    source_identity = {
        "schema_version": "tensile-source-snapshot/v2",
        "fixture": "source",
    }
    source_digest = hashlib.sha256(canonical_bytes(source_identity)).hexdigest()
    source_id = f"source-snapshot-{source_digest[:12]}"
    source_dir = paths["project_root"] / "snapshots" / source_id
    source_payload = source_dir / "video_meta.json"
    _write_json(source_payload, [])
    _write_json(
        source_dir / "source_manifest.json",
        {
            "schema_version": "tensile-source-snapshot/v2",
            "source_snapshot_id": source_id,
            "identity_sha256": source_digest,
            "identity": source_identity,
            "artifacts": {
                "video_meta.json": {"sha256": _sha(source_payload)}
            },
        },
    )

    split_dir = paths["splits"]
    decision = split_dir / "split_decision.json"
    _write_json(decision, {"seed": 42})
    artifacts = {
        path.name: {"sha256": _sha(path)}
        for path in sorted(split_dir.glob("*.json"))
    }
    split_seed = {
        "schema_version": "tensile-split-snapshot/v1",
        "source_snapshot_id": source_id,
        "policy": {"version": "fixture", "seed": 42},
        "member_ids_sha256": "fixture",
        "artifacts": artifacts,
    }
    split_digest = hashlib.sha256(canonical_bytes(split_seed)).hexdigest()
    split_id = f"split-snapshot-{split_digest[:12]}"
    split_target = split_dir.with_name(split_id)
    split_dir.rename(split_target)
    _write_json(
        split_target / "split_manifest.json",
        {
            **split_seed,
            "split_snapshot_id": split_id,
            "identity_sha256": split_digest,
        },
    )
    paths["splits"] = split_target
    return source_dir, split_target


def test_builds_deterministic_immutable_release(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    release_dir, manifest = _build(paths)

    assert manifest["status"] == "training_ready"
    assert manifest["label_semantics"] == "frame_window_authoritative"
    assert manifest["counts"]["published_candidates"] == 4
    assert manifest["counts"]["reviewed_candidates"] == 2
    assert manifest["counts"]["automatic_unreviewed_candidates"] == 2
    assert len(json.loads((release_dir / "datasets/train/fold_0.json").read_text())) == 2
    metadata = json.loads(
        (release_dir / "metadata/training_candidates.json").read_text()
    )
    assert metadata["candidate_count"] == 4
    assert {
        row["labels"]["clip_state"] for row in metadata["candidates"]
    } == {"未断裂", "发生断裂", "临界未断裂"}

    repeated_dir, repeated_manifest = _build(paths)
    assert repeated_dir == release_dir
    assert repeated_manifest == manifest


def test_release_appends_index_and_latest(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    release_dir, manifest = _build(paths)
    releases = paths["releases"]

    index = artifact_index.read_index(releases)
    assert len(index) == 1
    assert index[0]["id"] == manifest["release_id"]
    assert index[0]["step"] == "release"
    assert index[0]["inputs"]["queue_id"] == manifest["source_queue_id"]
    assert index[0]["inputs"]["review_batch_id"] == manifest["source_review_batch_id"]
    assert index[0]["inputs"]["media_id"] == manifest["source_media_id"]
    assert (
        index[0]["stats"]["published_candidates"]
        == manifest["counts"]["published_candidates"]
    )
    latest = (
        releases / artifact_resolver.LATEST_FILENAME
    ).read_text(encoding="utf-8").strip()
    assert latest == manifest["release_id"]

    # Idempotent rerun keeps the same index state.
    _, same_manifest = _build(paths)
    assert same_manifest == manifest
    assert len(artifact_index.read_index(releases)) == 1
    assert (
        releases / artifact_resolver.LATEST_FILENAME
    ).read_text(encoding="utf-8").strip() == manifest["release_id"]


def test_existing_release_rerun_backfills_index(tmp_path: Path) -> None:
    """Re-running a release that already exists without an index must backfill it."""
    paths = _fixture(tmp_path)
    release_dir, manifest = _build(paths)

    # Simulate a release directory that predates the collection index.
    releases_without_index = tmp_path / "data/releases_without_index"
    shutil.copytree(release_dir, releases_without_index / release_dir.name)
    assert not (releases_without_index / "index.json").exists()

    paths["releases"] = releases_without_index
    rerun_dir, rerun_manifest = _build(paths)
    assert rerun_dir == releases_without_index / release_dir.name
    assert rerun_manifest == manifest

    index = artifact_index.read_index(releases_without_index)
    assert len(index) == 1
    assert index[0]["id"] == manifest["release_id"]
    assert index[0]["step"] == "release"
    latest = (
        (releases_without_index / artifact_resolver.LATEST_FILENAME)
        .read_text(encoding="utf-8")
        .strip()
    )
    assert latest == manifest["release_id"]


def test_release_can_bind_source_snapshot_directly(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _, manifest = _build(
        paths,
        source_snapshot_id="source-snapshot-0123456789ab",
    )
    assert manifest["source_snapshot_id"] == "source-snapshot-0123456789ab"
    assert (
        manifest["provenance"]["source_snapshot_id"]
        == "source-snapshot-0123456789ab"
    )


def test_semantic_release_binds_source_and_split_snapshots(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    source_dir, split_dir = _semantic_snapshots(paths)

    _, manifest = _build(
        paths,
        source_snapshot_id=source_dir.name,
        split_snapshot_id=split_dir.name,
        source_snapshot_dir=source_dir,
    )

    assert manifest["schema_version"] == RELEASE_SCHEMA_VERSION_V2
    assert manifest["source_snapshot_id"] == source_dir.name
    assert manifest["split_snapshot_id"] == split_dir.name
    assert manifest["provenance"]["release_schema_version"] == (
        RELEASE_SCHEMA_VERSION_V2
    )
    assert len(
        manifest["provenance"]["source_snapshot_manifest_sha256"]
    ) == 64
    assert len(
        manifest["provenance"]["split_snapshot_manifest_sha256"]
    ) == 64
    _validate_v2_snapshot_binding(manifest)


def test_semantic_release_rejects_partial_or_swapped_snapshot_binding(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    source_dir, split_dir = _semantic_snapshots(paths)

    with pytest.raises(V4_1TrainingReleaseError, match="同时绑定"):
        _build(
            paths,
            source_snapshot_id=source_dir.name,
            split_snapshot_id=split_dir.name,
        )

    manifest_path = split_dir / "split_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_snapshot_id"] = "source-snapshot-000000000000"
    _write_json(manifest_path, manifest)
    with pytest.raises(V4_1TrainingReleaseError, match="校验失败|不匹配"):
        _build(
            paths,
            source_snapshot_id=source_dir.name,
            split_snapshot_id=split_dir.name,
            source_snapshot_dir=source_dir,
        )


def test_semantic_release_uses_frozen_external_tree_anchor(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    source_dir, split_dir = _semantic_snapshots(paths)
    frozen_source_tree = str(tree_inventory(source_dir)["tree_sha256"])
    frozen_split_tree = str(tree_inventory(split_dir)["tree_sha256"])
    _write_json(source_dir / "video_meta.json", [{"drift": True}])
    manifest_path = source_dir / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["video_meta.json"]["sha256"] = _sha(
        source_dir / "video_meta.json"
    )
    _write_json(manifest_path, manifest)

    with pytest.raises(V4_1TrainingReleaseError, match="外部锚点"):
        _build(
            paths,
            source_snapshot_id=source_dir.name,
            split_snapshot_id=split_dir.name,
            source_snapshot_dir=source_dir,
            expected_source_tree_hash=frozen_source_tree,
            expected_split_tree_hash=frozen_split_tree,
        )

def test_rejects_non_negative_automatic_candidate(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    payload = json.loads(paths["materialized"].read_text())
    candidate = next(
        row
        for row in payload["candidates"]
        if row["candidate_id"] == "video_0001_pre_front"
    )
    candidate["candidate_v3_labels"] = {
        "clip_state": "无法判断",
        "fracture_mechanism": None,
        "location": None,
        "root_break": None,
        "special_case": None,
    }
    _write_json(paths["materialized"], payload)
    media_manifest = json.loads(paths["media_manifest"].read_text())
    media_manifest["artifacts"][paths["materialized"].name]["sha256"] = _sha(
        paths["materialized"]
    )
    _write_json(paths["media_manifest"], media_manifest)
    paths["queue"].unlink()
    save_v4_1_review_queue(
        paths["queue"],
        build_v4_1_review_queue(
            materialized_path=paths["materialized"],
            manifest_path=paths["media_manifest"],
            project_root=tmp_path,
            contract_path=paths["contract"],
        ),
    )

    with pytest.raises(
        V4_1TrainingReleaseError,
        match="未审自动候选不是普通未断裂",
    ):
        _build(paths)


def test_rejects_drifted_media(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    video = tmp_path / "data/media/video_0001_transition.mp4"
    video.write_bytes(b"drift")

    with pytest.raises(V4_1TrainingReleaseError, match="SHA-256 不一致"):
        _build(paths)


def test_accepts_absolute_canonical_frame_paths_behind_workspace_links(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    workspace_frames = tmp_path / "data/frames"
    canonical_frames = tmp_path.parent / f"{tmp_path.name}-canonical/frames"
    canonical_frames.parent.mkdir(parents=True, exist_ok=True)
    workspace_frames.rename(canonical_frames)
    workspace_frames.symlink_to(canonical_frames, target_is_directory=True)

    materialized = json.loads(paths["materialized"].read_text())
    for candidate in materialized["candidates"]:
        for frame in candidate["frame_artifacts"]:
            relative = Path(frame["path"]).relative_to("data/frames")
            frame["path"] = str((canonical_frames / relative).resolve())
    _write_json(paths["materialized"], materialized)
    media_manifest = json.loads(paths["media_manifest"].read_text())
    media_manifest["artifacts"][paths["materialized"].name]["sha256"] = _sha(
        paths["materialized"]
    )
    _write_json(paths["media_manifest"], media_manifest)
    paths["queue"].unlink()
    save_v4_1_review_queue(
        paths["queue"],
        build_v4_1_review_queue(
            materialized_path=paths["materialized"],
            manifest_path=paths["media_manifest"],
            project_root=tmp_path,
            contract_path=paths["contract"],
        ),
    )

    release_dir, _ = _build(paths)
    metadata = json.loads(
        (release_dir / "metadata/training_candidates.json").read_text()
    )
    assert all(
        frame["path"].startswith("data/frames/")
        for row in metadata["candidates"]
        for frame in row["frames"]
    )
