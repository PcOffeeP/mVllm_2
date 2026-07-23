from pipeline.v4_1_review_workflow import (
    _is_incipient_candidate,
    _proposal,
    migrate_v4_decisions,
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
