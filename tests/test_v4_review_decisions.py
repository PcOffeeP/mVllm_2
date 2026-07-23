import pytest

from pipeline.v4_review_decisions import (
    build_review_payload,
    effective_labels,
    validate_review_payload,
)


def labels(site="inside_gauge"):
    return {
        "clip_state": "发生断裂",
        "fracture_mechanism": "韧性断裂",
        "fracture_site": site,
        "special_case": None,
    }


def record(status="approved", corrected=None):
    return {
        "clip_id": "clip-1",
        "source_video": "source.mp4",
        "review_status": status,
        "system_proposed_labels": labels(),
        "historical_suggested_labels": None,
        "corrected_labels": corrected,
        "reviewer_notes": "",
        "reviewed_at": "2026-07-23T00:00:00+00:00",
        "reviewer_id": "reviewer",
        "evidence": {
            "media_sha256": "a" * 64,
            "historical_reference_ids": [],
            "actual_sampled_timestamps": [0.0],
            "migration": None,
        },
    }


def test_v4_review_payload_round_trip():
    payload = build_review_payload([record()], batch_id="batch")
    validate_review_payload(payload)
    assert effective_labels(payload["decisions"][0]) == labels()


def test_v4_corrected_uses_corrected_labels():
    corrected = labels("grip_root")
    payload = build_review_payload(
        [record("corrected", corrected)], batch_id="batch"
    )
    assert effective_labels(payload["decisions"][0]) == corrected


def test_v4_approved_rejects_corrected_labels():
    with pytest.raises(ValueError, match="approved"):
        build_review_payload([record("approved", labels("grip_root"))], batch_id="batch")


def test_v4_migration_provenance_is_preserved():
    item = record()
    item["evidence"]["migration"] = {
        "source_schema_version": "tensile-review-decision/v3",
        "source_sha256": "b" * 64,
        "policy_version": "v3-to-v4-fracture-site/v1",
    }
    payload = build_review_payload([item], batch_id="batch")
    assert payload["decisions"][0]["evidence"]["migration"] == item["evidence"]["migration"]
