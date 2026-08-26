from pathlib import Path

import pytest

from pipeline import artifact_index, artifact_resolver
from pipeline.v4_1_review_workflow import (
    _is_incipient_candidate,
    _proposal,
    append_review_queue_index,
    freeze_completed_batch,
    migrate_v4_decisions,
    new_decision,
)


def v3_labels(state="未断裂"):
    return {
        "clip_state": state,
        "fracture_mechanism": "韧性断裂" if state != "未断裂" else None,
        "root_break": False if state != "未断裂" else None,
        "location": "inside_gauge" if state != "未断裂" else None,
        "special_case": None,
    }


def candidate(state="未断裂", variant="pre_event_back", source_type="韧性断裂"):
    return {
        "candidate_id": "clip-1",
        "source_video": "video-1",
        "window_role": "pre_event",
        "window_variant": variant,
        "source_type": source_type,
        "source_location": "inside_gauge",
        "candidate_v3_labels": v3_labels(state),
        "video_sha256": "a" * 64,
        "_actual_sampled_timestamps": [0.0],
    }


def test_only_ductile_pre_event_back_is_incipient():
    assert _is_incipient_candidate(candidate())
    assert not _is_incipient_candidate(candidate(variant="pre_event_front"))
    assert not _is_incipient_candidate(candidate(source_type="脆性断裂"))
    assert _proposal(candidate()) == {
        "clip_state": "临界未断裂",
        "fracture_mechanism": "韧性断裂",
        "fracture_site": "inside_gauge",
        "special_case": None,
    }


def test_freeze_completed_batch_appends_review_decision_index(tmp_path: Path) -> None:
    collection_dir = tmp_path / "review_decisions"
    output_root = collection_dir / "v4-1-review-abc123" / "workspace-hash"
    candidate_data = {
        "candidate_id": "c1",
        "source_video": "video-1",
        "candidate_v4_labels": {
            "clip_state": "未断裂",
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": None,
        },
        "video_sha256": "a" * 64,
        "_actual_sampled_timestamps": [0.0],
    }
    record = new_decision(
        candidate_data,
        status="approved",
        corrected_labels=None,
        historical_suggested_labels=None,
        historical_reference_ids=[],
        reviewer_notes="",
        reviewer_id="reviewer",
        reviewed_at="2026-07-23T00:00:00+00:00",
    )
    identity = {
        "queue_schema_version": "tensile-v4.1-review-queue/v1",
        "queue_id": "v4-1-review-abc123",
        "queue_sha256": "b" * 64,
        "contract_hash": "c" * 64,
        "media_id": "candidate-media-test",
        "full_queue_count": 1,
        "full_candidate_ids_sha256": "d" * 64,
        "selected_candidate_ids": ["c1"],
        "selected_candidate_ids_sha256": "d" * 64,
    }
    batch_dir = freeze_completed_batch(
        output_root,
        identity,
        {"c1": record},
        collection_dir=collection_dir,
    )

    index = artifact_index.read_index(collection_dir)
    assert len(index) == 1
    entry = index[0]
    assert entry["id"] == batch_dir.name
    assert entry["id"].startswith("review-batch-")
    assert entry["step"] == "review"
    assert entry["inputs"]["queue_id"] == "v4-1-review-abc123"
    assert entry["inputs"]["media_id"] == "candidate-media-test"
    assert entry["stats"]["decision_count"] == 1
    assert entry["stats"]["status_counts"] == {"approved": 1}
    assert (
        (collection_dir / artifact_resolver.LATEST_FILENAME)
        .read_text(encoding="utf-8")
        .strip()
        == entry["id"]
    )

    # Idempotent.
    freeze_completed_batch(
        output_root,
        identity,
        {"c1": record},
        collection_dir=collection_dir,
    )
    assert len(artifact_index.read_index(collection_dir)) == 1


def test_stable_negative_is_not_added_to_manual_queue():
    item = candidate(variant="normal_negative_rotated")
    item["window_role"] = "stable_negative"
    item["source_type"] = None
    assert _proposal(item) is None


def test_existing_observed_candidate_keeps_v4_semantics():
    item = candidate(state="发生断裂")
    item["window_role"] = "transition"
    item["window_variant"] = "transition_centered"
    assert _proposal(item)["fracture_site"] == "inside_gauge"


def test_append_review_queue_index_records_phase1_queue(tmp_path: Path) -> None:
    payload = {
        "schema_version": "tensile-v4.1-review-queue/v1",
        "queue_id": "v4-1-review-abc123def456",
        "source_media": {
            "media_id": "candidate-media-test",
            "materialized_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
        },
        "candidate_count": 5,
        "observed_count": 3,
        "incipient_count": 2,
    }
    collection_dir = tmp_path / "review_queues"
    append_review_queue_index(collection_dir, payload)

    index = artifact_index.read_index(collection_dir)
    assert len(index) == 1
    entry = index[0]
    assert entry["id"] == payload["queue_id"]
    assert entry["step"] == "review"
    assert entry["inputs"]["media_id"] == "candidate-media-test"
    assert entry["stats"]["candidate_count"] == 5
    assert entry["stats"]["observed_count"] == 3
    assert entry["stats"]["incipient_count"] == 2
    assert (
        (collection_dir / artifact_resolver.LATEST_FILENAME)
        .read_text(encoding="utf-8")
        .strip()
        == payload["queue_id"]
    )

    # Idempotent.
    append_review_queue_index(collection_dir, payload)
    assert len(artifact_index.read_index(collection_dir)) == 1


def test_append_review_queue_index_records_phase2_queue(tmp_path: Path) -> None:
    payload = {
        "schema_version": "tensile-v4.1-phase2-review-queue/v1",
        "queue_id": "v4-1-phase2-development-abc123def456",
        "review_scope": "development",
        "source_audit": {"audit_id": "audit-test", "sha256": "c" * 64},
        "source_media": {
            "media_id": "candidate-media-phase2",
            "materialized_sha256": "d" * 64,
        },
        "candidate_count": 7,
    }
    collection_dir = tmp_path / "review_queues"
    append_review_queue_index(collection_dir, payload)

    entry = artifact_index.read_index(collection_dir)[0]
    assert entry["id"] == payload["queue_id"]
    assert entry["inputs"]["audit_id"] == "audit-test"
    assert entry["inputs"]["scope"] == "development"
    assert entry["stats"]["candidate_count"] == 7
    assert "observed_count" not in entry["stats"]


def test_append_review_queue_index_rejects_missing_queue_id(tmp_path: Path) -> None:
    payload = {
        "schema_version": "tensile-v4.1-review-queue/v1",
        "source_media": {
            "media_id": "candidate-media-test",
            "materialized_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
        },
        "candidate_count": 1,
    }
    with pytest.raises(ValueError, match="queue_id"):
        append_review_queue_index(tmp_path / "review_queues", payload)


def test_v4_decision_migrates_without_semantic_change():
    item = candidate(state="发生断裂")
    item["window_role"] = "transition"
    item["candidate_v4_labels"] = _proposal(item)
    record = {
        "clip_id": "clip-1",
        "source_video": "video-1",
        "review_status": "approved",
        "system_proposed_labels": dict(item["candidate_v4_labels"]),
        "historical_suggested_labels": None,
        "corrected_labels": None,
        "reviewer_notes": "",
        "reviewed_at": "2026-07-23T00:00:00+00:00",
        "reviewer_id": None,
        "evidence": {
            "media_sha256": "a" * 64,
            "historical_reference_ids": [],
            "actual_sampled_timestamps": [0.0],
        },
    }
    migrated, conflicts = migrate_v4_decisions(
        [record], [item], source_sha256="b" * 64
    )
    assert conflicts == []
    assert migrated["clip-1"]["effective_labels"] == item["candidate_v4_labels"]
