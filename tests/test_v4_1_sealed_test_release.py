from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_review_workflow import (
    build_phase2_review_queue,
    freeze_completed_batch,
    load_review_queue,
    new_decision,
    save_v4_1_review_queue,
)
from pipeline.v4_1_sealed_test_release import (
    READY_STATUS,
    SEALED_TEST_RELEASE_SCHEMA_VERSION,
    build_v4_1_sealed_test_release,
)
from pipeline.v4_1_training_release import (
    RELEASE_SCHEMA_VERSION,
    V4_1TrainingReleaseError,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _contract(tmp_path: Path) -> Path:
    payload: dict[str, object] = {
        "contract_version": "tensile-vlm/v4.1",
        "analysis": {"system_prompt": "system", "user_prompt": "user"},
    }
    payload["contract_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    path = tmp_path / "contract.json"
    _write_json(path, payload)
    return path


def _candidate(
    tmp_path: Path,
    candidate_id: str,
    source_video: str,
) -> dict[str, object]:
    video = tmp_path / "media" / f"{candidate_id}.mp4"
    frame = tmp_path / "frames" / f"{candidate_id}.jpg"
    video.parent.mkdir(parents=True, exist_ok=True)
    frame.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(f"video:{candidate_id}".encode())
    frame.write_bytes(f"frame:{candidate_id}".encode())
    return {
        "candidate_id": candidate_id,
        "source_video": source_video,
        "video_path": str(video),
        "video_sha256": sha256_file(video),
        "actual_frame_mapping": [
            {"input_index": 0, "original_frame": 10, "timestamp": 1.0}
        ],
        "frame_artifacts": [
            {
                "path": str(frame),
                "sha256": sha256_file(frame),
                "size_bytes": frame.stat().st_size,
            }
        ],
        "processor_fingerprint": "processor:test",
    }


def _audit_row(candidate: dict[str, object]) -> dict[str, object]:
    return {
        "candidate_id": candidate["candidate_id"],
        "review_scope": "sealed_test",
        "truth_status": "unreviewed",
        "source_video": candidate["source_video"],
        "video_sha256": candidate["video_sha256"],
        "actual_frame_mapping": candidate["actual_frame_mapping"],
        "effective_frame_signature": hashlib.sha256(
            f"{candidate['candidate_id']}:10".encode()
        ).hexdigest(),
        "labels": {
            "clip_state": "未断裂",
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": None,
        },
    }


def _development_release(tmp_path: Path, source_video: str = "video_0001") -> Path:
    release_dir = tmp_path / "development_release"
    metadata_path = release_dir / "metadata/training_candidates.json"
    _write_json(
        metadata_path,
        {
            "candidate_count": 1,
            "excluded_count": 0,
            "candidates": [
                {"candidate_id": "dev-1", "source_video": source_video}
            ],
            "excluded": [],
        },
    )
    manifest_path = release_dir / "manifest/release_manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": RELEASE_SCHEMA_VERSION,
            "release_id": "v4.1.0-test",
            "status": "training_ready",
            "immutable": True,
            "files": [
                {
                    "path": "metadata/training_candidates.json",
                    "size_bytes": metadata_path.stat().st_size,
                    "sha256": sha256_file(metadata_path),
                }
            ],
        },
    )
    return manifest_path


def _fixture(tmp_path: Path) -> dict[str, Path]:
    contract_path = _contract(tmp_path)
    candidates = [
        _candidate(tmp_path, "test-a", "video_0099"),
        _candidate(tmp_path, "test-b", "video_0099"),
        _candidate(tmp_path, "test-c", "video_0100"),
    ]
    materialized_path = tmp_path / "test_materialized.json"
    _write_json(
        materialized_path,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "sealed-media-test",
            "candidates": candidates,
        },
    )
    audit_path = tmp_path / "audit_manifest.json"
    _write_json(
        audit_path,
        {
            "schema_version": "tensile-vlm-v4.1-effective-view-audit/v1",
            "audit_id": "audit-test",
            "identity": {
                "policy": {
                    "automatic_labels_are_truth": False,
                    "v3_test_labels_are_truth": False,
                }
            },
            "inputs": {
                "experimental_materialized": {
                    "path": str(tmp_path / "unused-development.json"),
                    "sha256": "unused",
                },
                "test_materialized": {
                    "path": str(materialized_path),
                    "sha256": sha256_file(materialized_path),
                },
            },
            "leakage": {"passed": True},
            "review_queues": {
                "development": [],
                "sealed_test": [_audit_row(row) for row in candidates],
            },
            "completion": {
                "ready_for_human_review": True,
                "creates_training_release": False,
            },
        },
    )
    queue_payload = build_phase2_review_queue(
        audit_manifest_path=audit_path,
        scope="sealed_test",
        project_root=tmp_path,
        contract_path=contract_path,
    )
    queue_path = tmp_path / "review_queue.json"
    save_v4_1_review_queue(queue_path, queue_payload)
    identity, joined = load_review_queue(queue_path, project_root=tmp_path)
    records = {
        "test-a": new_decision(
            joined[0],
            status="approved",
            corrected_labels=None,
            historical_suggested_labels=None,
            historical_reference_ids=[],
            reviewer_notes="",
            reviewer_id="reviewer",
            reviewed_at="2026-07-27T00:00:00+00:00",
        ),
        "test-b": new_decision(
            joined[1],
            status="dropped",
            corrected_labels=None,
            historical_suggested_labels=None,
            historical_reference_ids=[],
            reviewer_notes="unusable",
            reviewer_id="reviewer",
            reviewed_at="2026-07-27T00:01:00+00:00",
        ),
        "test-c": new_decision(
            joined[2],
            status="corrected",
            corrected_labels={
                "clip_state": "临界未断裂",
                "fracture_mechanism": None,
                "fracture_site": None,
                "special_case": None,
            },
            historical_suggested_labels=None,
            historical_reference_ids=[],
            reviewer_notes="corrected",
            reviewer_id="reviewer",
            reviewed_at="2026-07-27T00:02:00+00:00",
        ),
    }
    batch_dir = freeze_completed_batch(
        tmp_path / "review_decisions",
        identity,
        records,
    )
    split_path = tmp_path / "test.json"
    _write_json(
        split_path,
        {"video_ids": ["video_0099", "video_0100", "video_0101"]},
    )
    return {
        "project_root": tmp_path,
        "contract": contract_path,
        "queue": queue_path,
        "decisions": batch_dir / "decisions.json",
        "development_manifest": _development_release(tmp_path),
        "test_split": split_path,
        "releases_dir": tmp_path / "sealed_releases",
    }


def _build(paths: dict[str, Path], *, validate_only: bool):
    return build_v4_1_sealed_test_release(
        project_root=paths["project_root"],
        queue_path=paths["queue"],
        decisions_path=paths["decisions"],
        contract_path=paths["contract"],
        development_release_manifest_path=paths["development_manifest"],
        test_split_path=paths["test_split"],
        releases_dir=paths["releases_dir"],
        validate_only=validate_only,
    )


def test_builds_content_bound_restricted_sealed_release(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    expected_dir, preflight = _build(paths, validate_only=True)
    assert not expected_dir.exists()
    assert preflight["schema_version"] == SEALED_TEST_RELEASE_SCHEMA_VERSION
    assert preflight["status"] == READY_STATUS
    assert preflight["counts"]["review_queue_candidates"] == 3
    assert preflight["counts"]["admitted_candidates"] == 2
    assert preflight["counts"]["excluded_candidates"] == 1
    assert preflight["counts"]["admitted_sources"] == 2
    assert preflight["access_policy"]["one_time_evaluation_authorized"] is False

    release_dir, manifest = _build(paths, validate_only=False)
    assert release_dir == expected_dir
    assert manifest == preflight
    ground_truth = release_dir / "metadata/sealed_ground_truth.json"
    assert ground_truth.is_file()
    assert stat.S_IMODE(ground_truth.stat().st_mode) == 0o600
    assert stat.S_IMODE(release_dir.stat().st_mode) == 0o700

    same_dir, same_manifest = _build(paths, validate_only=False)
    assert same_dir == release_dir
    assert same_manifest == manifest


def test_rejects_development_source_overlap(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["development_manifest"] = _development_release(
        tmp_path / "overlap",
        source_video="video_0099",
    )
    with pytest.raises(V4_1TrainingReleaseError, match="source 重叠"):
        _build(paths, validate_only=True)


def test_rejects_frozen_summary_drift(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    summary_path = paths["decisions"].with_name("summary.json")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["decision_count"] = 2
    _write_json(summary_path, payload)
    with pytest.raises(V4_1TrainingReleaseError, match="summary"):
        _build(paths, validate_only=True)
