import csv
import json
from pathlib import Path

from pipeline.scripts.audit_review_decisions import audit_review_decisions


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_audit_flags_source_conflict_and_recomputes_interval(tmp_path):
    decisions = tmp_path / "decisions.json"
    annotations = tmp_path / "annotations.csv"
    video_meta = tmp_path / "video_meta.json"
    subvideos = tmp_path / "subvideos_meta.json"
    output = tmp_path / "audit"
    _write_json(decisions, {"decisions": [{
        "subvideo_id": "video_0001_focus_3s_50pct", "status": "approved",
        "original_labels": {"type": "韧性断裂", "fracture_between": [1, 2]},
        "corrected_labels": {"type": "脆性断裂", "fracture_between": [2, 3]},
    }]})
    with annotations.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "has_fracture", "断裂模式", "断裂位置", "断裂时间点", "断裂帧数", "视频帧率", "视频时长", "视频总帧数"])
        writer.writeheader()
        writer.writerow({"id": "video_0001", "has_fracture": "TRUE", "断裂模式": "韧性断裂", "断裂位置": "inside_gauge", "断裂时间点": "1.0s", "断裂帧数": "10", "视频帧率": "10", "视频时长": "2", "视频总帧数": "20"})
    _write_json(video_meta, [{"video_id": "video_0001", "video_path": "missing.mp4"}])
    _write_json(subvideos, {"subvideos": [{"subvideo_id": "video_0001_focus_3s_50pct", "actual_frame_mapping": [{"original_frame": 1}, {"original_frame": 7}, {"original_frame": 9}, {"original_frame": 12}]}]})

    report = audit_review_decisions(decisions, annotations, video_meta, output, subvideos)

    assert report["source_reannotation_required_video_ids"] == ["video_0001"]
    assert report["fracture_interval_changes"][0]["verification"] == "verified"
    assert (output / "review_key_label_change_queue.csv").exists()
    assert (output / "review_decision_audit.md").exists()


def test_audit_blocks_unknown_type_and_location(tmp_path):
    decisions = tmp_path / "decisions.json"
    annotations = tmp_path / "annotations.csv"
    video_meta = tmp_path / "video_meta.json"
    output = tmp_path / "audit"
    _write_json(decisions, {"decisions": [{
        "subvideo_id": "video_0001_full", "status": "approved",
        "original_labels": {"type": "脆性断裂", "location": "outside_gauge"},
        "corrected_labels": {"type": "脆性断裂、齐根断裂", "location": "outside_guage"},
    }]})
    with annotations.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "has_fracture", "断裂模式", "断裂位置", "断裂时间点", "断裂帧数", "视频帧率", "视频时长", "视频总帧数"])
        writer.writeheader()
        writer.writerow({"id": "video_0001", "has_fracture": "TRUE", "断裂模式": "脆性断裂", "断裂位置": "outside_gauge", "断裂时间点": "", "断裂帧数": "", "视频帧率": "30", "视频时长": "2", "视频总帧数": "60"})
    _write_json(video_meta, [{"video_id": "video_0001", "video_path": "missing.mp4"}])

    report = audit_review_decisions(decisions, annotations, video_meta, output)

    assert {row["invalid_value_reason"] for row in report["invalid_corrected_values"]} == {"invalid_type", "invalid_location"}
