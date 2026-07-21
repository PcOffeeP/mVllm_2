import hashlib
import json

import pytest

from pipeline.review_evidence import build_reference_bundle, write_reference_bundle


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _source(video_id, fracture=True, fracture_type="韧性断裂", event=10.0):
    return {
        "video_id": video_id,
        "has_fracture_canonical": fracture,
        "type": fracture_type,
        "location_canonical": "inside_gauge" if fracture else None,
        "is_abnormal": fracture_type in {"未夹紧", "视频异常"},
        "event_time_reliable": fracture,
        "event_time": event if fracture else None,
    }


def _metadata(clip_id, source, status="approved", fracture_type="韧性断裂"):
    return {
        "subvideo_id": clip_id,
        "source_video": source,
        "review_status": status,
        "type": fracture_type,
        "location": "inside_gauge",
        "start_time": 9.0,
        "end_time": 11.0,
        "actual_frame_mapping": [
            {"original_frame": 9, "timestamp": 9.0},
            {"original_frame": 11, "timestamp": 11.0},
        ],
    }


def _decision(clip_id, status="approved", original_type="韧性断裂", corrected=None):
    return {
        "subvideo_id": clip_id,
        "status": status,
        "reviewed_at": "2026-07-20T00:00:00+00:00",
        "reviewer_notes": "kept",
        "original_labels": {
            "has_fracture": True,
            "type": original_type,
            "location": "inside_gauge",
            "fracture_between": [0, 1],
        },
        "corrected_labels": corrected,
    }


def _fixture(tmp_path, *, leak=False, conflicting=False):
    root = tmp_path
    video = _write(
        root / "video.json",
        [_source("video_0001"), _source("video_0002", fracture_type="脆性断裂")],
    )
    split = _write(root / "test.json", {"video_ids": ["video_0002"], "count": 1})
    train_source = "video_0002" if leak else "video_0001"
    train_clip = f"{train_source}_clip"
    train_rows = [_metadata(train_clip, train_source)]
    train_decisions = [_decision(train_clip)]
    if conflicting:
        train_rows.append(_metadata("video_0001_clip_b", "video_0001", fracture_type="脆性断裂"))
        train_decisions.append(_decision("video_0001_clip_b", original_type="脆性断裂"))
    paths = {
        "train_review_decisions_path": _write(
            root / "train_decisions.json", {"decisions": train_decisions}
        ),
        "train_reviewed_metadata_path": _write(
            root / "train_meta.json", {"subvideos": train_rows}
        ),
        "test_review_decisions_path": _write(
            root / "test_decisions.json",
            {"decisions": [_decision("video_0002_clip", original_type="脆性断裂")]},
        ),
        "test_reviewed_metadata_path": _write(
            root / "test_meta.json",
            {"subvideos": [_metadata("video_0002_clip", "video_0002", fracture_type="脆性断裂")]},
        ),
        "video_metadata_path": video,
        "test_manifest_path": split,
        "project_root": root,
        "generated_at": "2026-07-20T00:00:00+00:00",
    }
    return paths


def test_builds_disjoint_development_and_test_artifacts(tmp_path):
    bundle = build_reference_bundle(**_fixture(tmp_path))
    development = bundle["development_reference.json"]
    test = bundle["test_reference_audit.json"]
    assert development["source_inventory"] == ["video_0001"]
    assert test["source_inventory"] == ["video_0002"]
    assert {row["source_video"] for row in development["records"]} == {"video_0001"}
    assert {row["source_video"] for row in test["records"]} == {"video_0002"}
    assert bundle["manifest.json"]["split_guard"]["overlap_count"] == 0


def test_test_source_in_development_input_is_quarantined(tmp_path):
    bundle = build_reference_bundle(**_fixture(tmp_path, leak=True))
    assert bundle["development_reference.json"]["records"] == []
    quarantined = bundle["quarantined_cross_split.json"]
    assert {row["source_video"] for row in quarantined["records"]} == {"video_0002"}
    assert bundle["manifest.json"]["split_guard"]["quarantined_record_count"] == 1


def test_corrected_labels_take_priority_and_original_is_preserved(tmp_path):
    paths = _fixture(tmp_path)
    corrected = {
        "has_fracture": True,
        "type": "界面脱粘、齐根断裂",
        "location": "outside_gauge",
        "fracture_between": [0, 1],
    }
    _write(
        paths["train_review_decisions_path"],
        {"decisions": [_decision("video_0001_clip", corrected=corrected)]},
    )
    record = build_reference_bundle(**paths)["development_reference.json"]["records"][0]
    assert record["original_labels"]["type"] == "韧性断裂"
    assert record["corrected_labels"]["type"] == "界面脱粘、齐根断裂"
    assert record["effective_legacy_labels"] == corrected
    assert record["effective_label_source"] == "corrected_labels"
    assert record["candidate_v3_labels"]["fracture_mechanism"] == "界面脱粘"
    assert record["candidate_v3_labels"]["root_break"] is True


def test_dropped_record_is_preserved_but_not_used_for_consensus(tmp_path):
    paths = _fixture(tmp_path)
    _write(
        paths["train_review_decisions_path"],
        {"decisions": [_decision("video_0001_clip", status="dropped")]},
    )
    artifact = build_reference_bundle(**paths)["development_reference.json"]
    assert artifact["records"][0]["review_status"] == "dropped"
    consensus = artifact["source_consensus"][0]
    assert consensus["consensus_status"] == "unavailable"
    assert consensus["supporting_reference_ids"] == []


def test_conflicting_human_records_are_reported_not_majority_voted(tmp_path):
    bundle = build_reference_bundle(**_fixture(tmp_path, conflicting=True))
    consensus = bundle["development_reference.json"]["source_consensus"][0]
    assert consensus["consensus_status"] == "conflict"
    assert consensus["consensus"]["fracture_mechanism"] is None
    assert consensus["conflicts"]["fracture_mechanism"] == ["脆性断裂", "韧性断裂"]
    assert len(bundle["conflicts.json"]["development"]) == 1


def test_reference_id_and_artifacts_are_deterministic(tmp_path):
    paths = _fixture(tmp_path)
    first = build_reference_bundle(**paths)
    second = build_reference_bundle(**paths)
    assert first == second
    assert first["manifest.json"]["reference_id"].startswith("review-ref-")


def test_inputs_are_not_modified(tmp_path):
    paths = _fixture(tmp_path)
    input_paths = [
        value
        for key, value in paths.items()
        if key.endswith("_path") and key != "project_root"
    ]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths}
    build_reference_bundle(**paths)
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths}
    assert before == after


def test_bundle_write_is_idempotent_and_non_overwriting(tmp_path):
    paths = _fixture(tmp_path / "inputs")
    bundle = build_reference_bundle(**paths)
    destination, created = write_reference_bundle(tmp_path / "out", bundle)
    assert created is True
    assert (destination / "manifest.json").exists()
    assert write_reference_bundle(tmp_path / "out", bundle) == (destination, False)
    retry = json.loads(json.dumps(bundle))
    retry["manifest.json"]["generated_at"] = "2026-07-21T00:00:00+00:00"
    assert write_reference_bundle(tmp_path / "out", retry) == (destination, False)
    changed = {**bundle, "build_report.json": {"changed": True}}
    with pytest.raises(FileExistsError, match="拒绝覆盖"):
        write_reference_bundle(tmp_path / "out", changed)
