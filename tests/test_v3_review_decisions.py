import json

import pytest

from pipeline.v3_review_decisions import (
    build_review_payload,
    effective_labels,
    save_review_payload,
    validate_review_payload,
)


def _labels(state="发生断裂"):
    if state == "未断裂":
        return {
            "clip_state": state,
            "fracture_mechanism": None,
            "root_break": None,
            "location": None,
            "special_case": None,
        }
    return {
        "clip_state": state,
        "fracture_mechanism": "韧性断裂",
        "root_break": False,
        "location": "inside_gauge",
        "special_case": None,
    }


def _record(**overrides):
    record = {
        "clip_id": "clip-1",
        "source_video": "video_0001",
        "review_status": "approved",
        "system_proposed_labels": _labels(),
        "historical_suggested_labels": _labels("未断裂"),
        "corrected_labels": None,
        "reviewer_notes": "",
        "reviewed_at": "2026-07-20T00:00:00+00:00",
        "reviewer_id": "reviewer-a",
        "evidence": {
            "media_sha256": "abc",
            "historical_reference_ids": ["old-1"],
            "actual_sampled_timestamps": [9.9, 10.1],
        },
    }
    record.update(overrides)
    return record


def test_historical_suggestion_never_becomes_effective():
    record = _record()
    assert effective_labels(record) == _labels()
    assert effective_labels(record) != record["historical_suggested_labels"]


def test_corrected_labels_win():
    corrected = {
        "clip_state": "已断裂",
        "fracture_mechanism": "脆性断裂",
        "root_break": True,
        "location": "outside_gauge",
        "special_case": None,
    }
    record = _record(review_status="corrected", corrected_labels=corrected)
    assert effective_labels(record) == corrected


@pytest.mark.parametrize("status", ["dropped", "needs_regenerate", "needs_review"])
def test_non_final_status_has_no_effective_labels(status):
    payload = build_review_payload(
        [_record(review_status=status, reviewed_at=None)],
        batch_id="batch-1",
        created_at="2026-07-20T00:00:00+00:00",
    )
    assert payload["decisions"][0]["effective_labels"] is None


def test_corrected_status_requires_correction():
    with pytest.raises(ValueError, match="corrected_labels"):
        build_review_payload(
            [_record(review_status="corrected", corrected_labels=None)],
            batch_id="batch-1",
        )


def test_approved_status_rejects_hidden_correction():
    with pytest.raises(ValueError, match="corrected_labels"):
        build_review_payload(
            [_record(review_status="approved", corrected_labels=_labels("未断裂"))],
            batch_id="batch-1",
        )


def test_build_preserves_proposal_history_correction_and_evidence():
    corrected = _labels("未断裂")
    payload = build_review_payload(
        [_record(review_status="corrected", corrected_labels=corrected)],
        batch_id="batch-1",
        created_at="2026-07-20T00:00:00+00:00",
    )
    decision = payload["decisions"][0]
    assert decision["system_proposed_labels"] == _labels()
    assert decision["historical_suggested_labels"] == _labels("未断裂")
    assert decision["corrected_labels"] == corrected
    assert decision["effective_labels"] == corrected
    assert decision["evidence"]["historical_reference_ids"] == ["old-1"]
    validate_review_payload(payload)


def test_duplicate_clip_id_is_rejected():
    with pytest.raises(ValueError, match="不能重复"):
        build_review_payload([_record(), _record()], batch_id="batch-1")


def test_save_is_atomic_idempotent_and_refuses_overwrite(tmp_path):
    path = tmp_path / "reviews" / "batch-1.json"
    payload = build_review_payload(
        [_record()],
        batch_id="batch-1",
        created_at="2026-07-20T00:00:00+00:00",
    )
    assert save_review_payload(path, payload) is True
    assert save_review_payload(path, payload) is False
    assert json.loads(path.read_text(encoding="utf-8")) == payload

    changed = build_review_payload(
        [_record(reviewer_notes="changed")],
        batch_id="batch-1",
        created_at="2026-07-20T00:00:00+00:00",
    )
    with pytest.raises(FileExistsError, match="拒绝覆盖"):
        save_review_payload(path, changed)


def test_payload_rejects_old_label_schema():
    payload = build_review_payload(
        [_record()],
        batch_id="batch-1",
        created_at="2026-07-20T00:00:00+00:00",
    )
    payload["label_schema_version"] = "tensile-label/v2"
    with pytest.raises(ValueError, match="label_schema_version"):
        validate_review_payload(payload)
