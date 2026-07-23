from pipeline.v4_review_workflow import migrate_v3_decisions


def v3_labels(root=False, location="inside_gauge"):
    return {
        "clip_state": "发生断裂",
        "fracture_mechanism": "韧性断裂",
        "root_break": root,
        "location": location,
        "special_case": None,
    }


def candidate():
    return {
        "candidate_id": "clip-1",
        "source_video": "source.mp4",
        "candidate_v4_labels": {
            "clip_state": "发生断裂",
            "fracture_mechanism": "韧性断裂",
            "fracture_site": "inside_gauge",
            "special_case": None,
        },
        "video_sha256": "a" * 64,
        "_actual_sampled_timestamps": [0.0, 1.0],
    }


def v3_record():
    return {
        "clip_id": "clip-1",
        "source_video": "source.mp4",
        "review_status": "approved",
        "system_proposed_labels": v3_labels(),
        "historical_suggested_labels": None,
        "corrected_labels": None,
        "reviewer_notes": "",
        "reviewed_at": "2026-07-23T00:00:00+00:00",
        "reviewer_id": "reviewer",
        "evidence": {
            "media_sha256": "a" * 64,
            "historical_reference_ids": [],
            "actual_sampled_timestamps": [0.0, 1.0],
        },
    }


def test_migrate_v3_decision_preserves_terminal_review():
    migrated, conflicts = migrate_v3_decisions(
        [v3_record()], [candidate()], source_sha256="b" * 64
    )
    assert conflicts == []
    assert migrated["clip-1"]["review_status"] == "approved"
    assert migrated["clip-1"]["effective_labels"]["fracture_site"] == "inside_gauge"
    assert migrated["clip-1"]["evidence"]["migration"]["source_sha256"] == "b" * 64


def test_migrate_v3_decision_rejects_media_drift():
    item = v3_record()
    item["evidence"]["media_sha256"] = "c" * 64
    migrated, conflicts = migrate_v3_decisions(
        [item], [candidate()], source_sha256="b" * 64
    )
    assert migrated == {}
    assert conflicts[0]["reason"] == "media_sha256 不一致"
