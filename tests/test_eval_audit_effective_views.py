from __future__ import annotations

import json
from pathlib import Path

import pytest

from finetune.audit_v4_1_effective_views import (
    EffectiveViewAuditError,
    effective_frame_identity,
    near_duplicate_clusters,
    verify_materialized_media,
    write_audit,
)


def _candidate(
    candidate_id: str,
    frames: list[int],
    *,
    source: str = "video_0001",
    pool: str = "automatic_candidate",
) -> dict[str, object]:
    identity = effective_frame_identity(
        {
            "candidate_id": candidate_id,
            "source_video": source,
            "actual_frame_mapping": [
                {"input_index": index, "original_frame": frame}
                for index, frame in enumerate(frames)
            ],
        }
    )
    return {
        "candidate_id": candidate_id,
        "source_video": source,
        "pool": pool,
        **identity,
    }


def test_effective_frame_identity_is_source_aware() -> None:
    left = effective_frame_identity(
        {
            "candidate_id": "left",
            "source_video": "video_0001",
            "actual_frame_mapping": [{"original_frame": 1}, {"original_frame": 9}],
        }
    )
    right = effective_frame_identity(
        {
            "candidate_id": "right",
            "source_video": "video_0002",
            "actual_frame_mapping": [{"original_frame": 1}, {"original_frame": 9}],
        }
    )

    assert left["effective_frame_signature"] != right["effective_frame_signature"]


def test_effective_frame_identity_rejects_non_monotonic_frames() -> None:
    with pytest.raises(EffectiveViewAuditError, match="严格递增"):
        effective_frame_identity(
            {
                "candidate_id": "bad",
                "source_video": "video_0001",
                "actual_frame_mapping": [
                    {"original_frame": 9},
                    {"original_frame": 1},
                ],
            }
        )


def test_near_duplicate_clusters_only_join_same_source() -> None:
    records = [
        _candidate("a", [0, 10, 20]),
        _candidate("b", [1, 10, 19], pool="released"),
        _candidate("c", [0, 10, 20], source="video_0002"),
        _candidate("d", [100, 110, 120]),
    ]

    clusters = near_duplicate_clusters(records, threshold=0.8)

    assert len(clusters) == 1
    assert clusters[0]["candidate_ids"] == ["a", "b"]
    assert clusters[0]["cross_pool"] is True


def test_write_audit_keeps_development_and_test_queues_separate(
    tmp_path: Path,
) -> None:
    audit = {
        "schema_version": "test/v1",
        "audit_id": "audit-test",
        "identity": {},
        "inputs": {},
        "inventory": [],
        "coverage": {},
        "near_duplicate_clusters": [],
        "independent_evidence": {},
        "source_cap_violations": {},
        "leakage": {"passed": True},
        "review_queues": {
            "development": [{"candidate_id": "dev"}],
            "sealed_test": [{"candidate_id": "test"}],
        },
        "test_candidate_status": {},
        "unable_judgment_coverage": {},
        "completion": {"creates_training_release": False},
    }

    write_audit(tmp_path, audit)

    development = json.loads(
        (tmp_path / "development_review_candidates.json").read_text()
    )
    sealed_test = json.loads(
        (tmp_path / "sealed_test_review_candidates.json").read_text()
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert development["candidates"] == [{"candidate_id": "dev"}]
    assert sealed_test["candidates"] == [{"candidate_id": "test"}]
    assert development["labels_are_truth"] is False
    assert sealed_test["labels_are_truth"] is False
    assert manifest["completion"]["creates_training_release"] is False


def test_verify_materialized_media_checks_video_and_frames(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    frame = tmp_path / "frame.jpg"
    video.write_bytes(b"video")
    frame.write_bytes(b"frame")

    import hashlib

    result = verify_materialized_media(
        [
            {
                "candidate_id": "candidate",
                "video_path": str(video),
                "video_sha256": hashlib.sha256(b"video").hexdigest(),
                "frame_artifacts": [
                    {
                        "path": str(frame),
                        "size_bytes": 5,
                        "sha256": hashlib.sha256(b"frame").hexdigest(),
                    }
                ],
            }
        ],
        media_root=tmp_path,
    )

    assert result["passed"] is True
    assert result["verified_candidate_count"] == 1
    assert result["verified_frame_count"] == 1
