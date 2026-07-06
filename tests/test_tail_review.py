from __future__ import annotations

import json
import sys

import pytest

from pipeline.scripts import prune_reviewed_subvideos, repair_review_media
from pipeline.scripts import review_subvideo_labels as review_labels_module


def _write_meta(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_subvideo(tmp_path, subvideo_id, *, video_exists=True, frames_exist=True):
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    if video_exists:
        mp4.parent.mkdir(parents=True, exist_ok=True)
        mp4.write_bytes(b"mp4")
    if frames_exist:
        frame_dir.mkdir(parents=True, exist_ok=True)
        (frame_dir / "frame_0000.jpg").write_bytes(b"jpg")
    return {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "full_pos",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "actual_frame_mapping": [{"input_index": 0, "original_frame": 0, "timestamp": 0.0}],
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }


def _frame_dir(tmp_path):
    return tmp_path / "data" / "04_frames"


def test_prune_keeps_both_present(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "keep")
    _write_meta(meta_path, {"subvideos": [sub]})

    kept, dropped, inconsistent = prune_reviewed_subvideos.prune_reviewed_subvideos(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(kept) == 1
    assert len(dropped) == 0
    assert len(inconsistent) == 0
    assert out_path.exists()


def test_prune_drops_both_missing(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "drop", video_exists=False, frames_exist=False)
    _write_meta(meta_path, {"subvideos": [sub]})

    kept, dropped, inconsistent = prune_reviewed_subvideos.prune_reviewed_subvideos(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(kept) == 0
    assert len(dropped) == 1
    assert len(inconsistent) == 0
    assert out_path.exists()
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["subvideos"] == []


def test_prune_fails_only_video_missing(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "bad", video_exists=False, frames_exist=True)
    _write_meta(meta_path, {"subvideos": [sub]})

    kept, dropped, inconsistent = prune_reviewed_subvideos.prune_reviewed_subvideos(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(inconsistent) == 1
    assert not out_path.exists()


def test_prune_fails_only_frames_missing(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "bad", video_exists=True, frames_exist=False)
    _write_meta(meta_path, {"subvideos": [sub]})

    kept, dropped, inconsistent = prune_reviewed_subvideos.prune_reviewed_subvideos(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(inconsistent) == 1
    assert not out_path.exists()


def test_prune_cli_returns_nonzero_on_inconsistent(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "bad", video_exists=False, frames_exist=True)
    _write_meta(meta_path, {"subvideos": [sub]})

    monkeypatch.setattr(
        sys, "argv",
        [
            "prune_reviewed_subvideos.py",
            "--subvideos-meta", str(meta_path),
            "--output-meta", str(out_path),
            "--report", str(report_path),
            "--frame-dir", str(_frame_dir(tmp_path)),
            "--project-root", str(tmp_path),
        ],
    )
    rc = prune_reviewed_subvideos.main()
    assert rc == 1


def test_prune_preserves_top_level_fields(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "keep")
    _write_meta(meta_path, {"subvideos": [sub], "seed": 42, "candidates": [sub]})

    prune_reviewed_subvideos.prune_reviewed_subvideos(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out.get("seed") == 42
    assert "candidates" in out


def test_repair_regenerates_missing_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(
        repair_review_media.subvideo_builder, "extract_sampled_frames",
        lambda video_path, output_dir, mapping: [output_dir / "frame_0000.jpg"],
    )

    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "repair_frames", video_exists=True, frames_exist=False)
    _write_meta(meta_path, {"subvideos": [sub]})

    repaired, failed = repair_review_media.repair_review_media(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(repaired) == 1
    assert len(failed) == 0
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["subvideos"][0]["frame_paths"] == ["04_frames/repair_frames/frame_0000.jpg"]


def test_repair_regenerates_missing_cropped_video(tmp_path, monkeypatch):
    calls = []

    def fake_crop(source, output, start, end):
        calls.append((source, output, start, end))
        output.write_bytes(b"mp4")

    monkeypatch.setattr(repair_review_media.subvideo_builder, "crop_video", fake_crop)

    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    source = tmp_path / "data" / "01_videos" / "video_0001.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")

    sub = _make_subvideo(tmp_path, "repair_video", video_exists=False, frames_exist=True)
    sub["crop_type"] = "focus_3s"
    sub["start_time"] = 5.0
    sub["end_time"] = 8.0
    sub["video_path"] = "data/03_subvideos/repair_video.mp4"
    _write_meta(meta_path, {"subvideos": [sub]})

    repaired, failed = repair_review_media.repair_review_media(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(repaired) == 1
    assert len(failed) == 0
    assert calls[0][2] == 5.0
    assert calls[0][3] == 8.0


def test_repair_copies_full_video(tmp_path, monkeypatch):
    calls = []

    def fake_copy(source, output):
        calls.append((source, output))
        output.write_bytes(b"mp4")

    monkeypatch.setattr(repair_review_media.subvideo_builder, "copy_as_subvideo", fake_copy)

    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    source = tmp_path / "data" / "01_videos" / "video_0001.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")

    sub = _make_subvideo(tmp_path, "repair_full", video_exists=False, frames_exist=True)
    sub["crop_type"] = "full_pos"
    sub["video_path"] = "data/03_subvideos/repair_full.mp4"
    _write_meta(meta_path, {"subvideos": [sub]})

    repaired, failed = repair_review_media.repair_review_media(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(repaired) == 1
    assert len(failed) == 0
    assert calls[0][0] == source


def test_repair_treats_empty_video_as_missing(tmp_path):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "empty", video_exists=False, frames_exist=True)
    mp4 = tmp_path / "data" / "03_subvideos" / "empty.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")

    _write_meta(meta_path, {"subvideos": [sub]})

    repaired, failed = repair_review_media.repair_review_media(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(repaired) == 0
    assert len(failed) == 1


def test_prune_empty_video_with_missing_frames_is_inconsistent(tmp_path):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "empty_bad", video_exists=False, frames_exist=False)
    mp4 = tmp_path / "data" / "03_subvideos" / "empty_bad.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")

    _write_meta(meta_path, {"subvideos": [sub]})

    kept, dropped, inconsistent = prune_reviewed_subvideos.prune_reviewed_subvideos(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(inconsistent) == 1
    assert inconsistent[0]["reason"] == "invalid_video"
    assert len(dropped) == 0


def test_prune_reports_empty_video_as_inconsistent(tmp_path):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "empty", video_exists=False, frames_exist=True)
    mp4 = tmp_path / "data" / "03_subvideos" / "empty.mp4"
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"")

    _write_meta(meta_path, {"subvideos": [sub]})

    kept, dropped, inconsistent = prune_reviewed_subvideos.prune_reviewed_subvideos(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(inconsistent) == 1
    assert inconsistent[0]["reason"] in {"missing_video", "invalid_video"}


def test_repair_reports_both_missing(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "gone", video_exists=False, frames_exist=False)
    _write_meta(meta_path, {"subvideos": [sub]})

    repaired, failed = repair_review_media.repair_review_media(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(repaired) == 0
    assert len(failed) == 1
    assert failed[0]["reason"] == "both_missing_not_repairable"


def test_label_review_passes_valid_full_positive(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = _make_subvideo(tmp_path, "valid_full")
    sub["crop_type"] = "full_pos"
    sub["type"] = "韧性断裂"
    sub["location"] = "inside_gauge"
    sub["actual_frame_mapping"] = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
    ]
    sub["fracture_between"] = [0, 1]
    (_frame_dir(tmp_path) / "valid_full" / "frame_0001.jpg").write_bytes(b"jpg")
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": "inside_gauge",
        "event_frame_effective": 5,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(passed) == 1
    assert len(failed) == 0
    assert out_path.exists()


def test_label_review_fails_type_mismatch(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = _make_subvideo(tmp_path, "mismatch")
    sub["crop_type"] = "full_pos"
    sub["type"] = "脆性断裂"
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": None,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(failed) == 1
    assert not out_path.exists()


def test_label_review_fails_negative_with_label(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = _make_subvideo(tmp_path, "bad_neg")
    sub["crop_type"] = "neg_before"
    sub["has_fracture"] = False
    sub["has_fracture_canonical"] = False
    sub["fracture_between"] = [0, 1]
    sub["type"] = "未断裂"
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "未断裂",
        "has_fracture_canonical": False,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(failed) == 1
    assert any("fracture_between_should_be_null" in r for r in failed[0]["reasons"])
    assert not out_path.exists()


def test_full_positive_fracture_between_mismatch_fails(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    subvideo_id = "full_pos_bad_fb"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True, exist_ok=True)

    mapping = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
        {"input_index": 2, "original_frame": 20, "timestamp": 2.0},
        {"input_index": 3, "original_frame": 30, "timestamp": 3.0},
    ]
    for i in range(len(mapping)):
        (frame_dir / f"frame_{i:04d}.jpg").write_bytes(b"jpg")

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "full_pos",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "fracture_between": [0, 1],
        "actual_frame_mapping": mapping,
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": "inside_gauge",
        "event_frame_effective": 15,
    }])

    monkeypatch.setattr(sys, "argv", [
        "review_subvideo_labels.py",
        "--subvideos-meta", str(meta_path),
        "--video-meta", str(video_meta_path),
        "--output-meta", str(out_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
    ])
    rc = review_labels_module.main()
    assert rc != 0
    assert not out_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(
        "full_positive_fracture_between_mismatch" in r
        for item in report["failed"]
        for r in item["reasons"]
    )


def test_full_positive_missing_event_frame_fails(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    subvideo_id = "full_pos_missing_event"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True, exist_ok=True)

    mapping = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
        {"input_index": 2, "original_frame": 20, "timestamp": 2.0},
        {"input_index": 3, "original_frame": 30, "timestamp": 3.0},
    ]
    for i in range(len(mapping)):
        (frame_dir / f"frame_{i:04d}.jpg").write_bytes(b"jpg")

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "full_pos",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "fracture_between": [1, 2],
        "actual_frame_mapping": mapping,
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": "inside_gauge",
    }])

    monkeypatch.setattr(sys, "argv", [
        "review_subvideo_labels.py",
        "--subvideos-meta", str(meta_path),
        "--video-meta", str(video_meta_path),
        "--output-meta", str(out_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
    ])
    rc = review_labels_module.main()
    assert rc != 0
    assert not out_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(
        "full_positive_missing_event_frame" in r
        for item in report["failed"]
        for r in item["reasons"]
    )


def test_focus_location_mismatch_fails(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    subvideo_id = "focus_bad_loc"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True, exist_ok=True)

    mapping = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
        {"input_index": 2, "original_frame": 20, "timestamp": 2.0},
        {"input_index": 3, "original_frame": 30, "timestamp": 3.0},
    ]
    for i in range(len(mapping)):
        (frame_dir / f"frame_{i:04d}.jpg").write_bytes(b"jpg")

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "focus_3s",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "fracture_between": [1, 2],
        "actual_frame_mapping": mapping,
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": "outside_gauge",
        "event_frame_effective": 15,
    }])

    monkeypatch.setattr(sys, "argv", [
        "review_subvideo_labels.py",
        "--subvideos-meta", str(meta_path),
        "--video-meta", str(video_meta_path),
        "--output-meta", str(out_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
    ])
    rc = review_labels_module.main()
    assert rc != 0
    assert not out_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(
        "focus_location_mismatch" in r
        for item in report["failed"]
        for r in item["reasons"]
    )


def test_repair_default_does_not_overwrite_input(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "keep")
    original_payload = {"subvideos": [sub]}
    original_content = json.dumps(original_payload, ensure_ascii=False)
    _write_meta(meta_path, original_payload)

    monkeypatch.setattr(sys, "argv", [
        "repair_review_media.py",
        "--subvideos-meta", str(meta_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
    ])
    rc = repair_review_media.main()
    assert rc == 0
    assert meta_path.read_text(encoding="utf-8") == original_content
    expected_output = tmp_path / "data" / "07_metadata" / "subvideos_meta.repaired.json"
    assert expected_output.exists()


def test_repair_unrepairable_exits_nonzero(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "gone", video_exists=False, frames_exist=False)
    _write_meta(meta_path, {"subvideos": [sub]})

    monkeypatch.setattr(sys, "argv", [
        "repair_review_media.py",
        "--subvideos-meta", str(meta_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
    ])
    rc = repair_review_media.main()
    assert rc != 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(report["failed"]) == 1
    expected_output = tmp_path / "data" / "07_metadata" / "subvideos_meta.repaired.json"
    assert expected_output.exists()


def test_repair_reports_failure_when_output_video_not_created(tmp_path, monkeypatch):
    """Patch 1: 源视频存在但 copy/crop 未写出目标 mp4 时不能误报成功。"""
    monkeypatch.setattr(
        repair_review_media.subvideo_builder, "crop_video",
        lambda source, output, start, end: None,
    )

    source = tmp_path / "data" / "01_videos" / "video_0001.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"corrupt_source")

    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "repair_no_output", video_exists=False, frames_exist=True)
    sub["crop_type"] = "focus_3s"
    sub["start_time"] = 1.0
    sub["end_time"] = 2.0
    sub["video_path"] = "data/03_subvideos/repair_no_output.mp4"
    _write_meta(meta_path, {"subvideos": [sub]})

    repaired, failed = repair_review_media.repair_review_media(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(repaired) == 0
    assert len(failed) == 1
    assert "output video not created" in failed[0]["reason"]

    monkeypatch.setattr(sys, "argv", [
        "repair_review_media.py",
        "--subvideos-meta", str(meta_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
    ])
    rc = repair_review_media.main()
    assert rc != 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["failed_count"] == 1
    assert not (tmp_path / "data" / "03_subvideos" / "repair_no_output.mp4").exists()


def test_label_review_rejects_deprecated_post_event_negative(tmp_path, monkeypatch):
    """Patch 2: crop_type="neg_after" 的旧负样本必须被拒绝。"""
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    subvideo_id = "bad_neg_after"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True)
    (frame_dir / "frame_0000.jpg").write_bytes(b"jpg")

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "neg_after",
        "has_fracture": False,
        "has_fracture_canonical": False,
        "fracture_between": None,
        "type": "未断裂",
        "location": None,
        "location_canonical": None,
        "actual_frame_mapping": [
            {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        ],
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "未断裂",
        "has_fracture_canonical": False,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(passed) == 0
    assert len(failed) == 1
    assert any("deprecated_post_event_negative" in r for r in failed[0]["reasons"])
    assert not out_path.exists()


def test_repair_fails_invalid_time_range(tmp_path, monkeypatch):
    """Patch 1: end_time <= start_time 的裁剪区间必须失败。"""
    source = tmp_path / "data" / "01_videos" / "video_0001.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")

    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "bad_range", video_exists=False, frames_exist=True)
    sub["crop_type"] = "focus_3s"
    sub["start_time"] = 5.0
    sub["end_time"] = 3.0
    sub["video_path"] = "data/03_subvideos/bad_range.mp4"
    _write_meta(meta_path, {"subvideos": [sub]})

    repaired, failed = repair_review_media.repair_review_media(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(repaired) == 0
    assert len(failed) == 1
    assert "invalid clip range" in failed[0]["reason"]


def test_label_review_clamped_event_full_recomputes_fracture_between(tmp_path, monkeypatch):
    """Patch 3: 未夹紧有事件 full 正样本必须复算 fracture_between。"""
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    subvideo_id = "clamped_full"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True)

    mapping = [
        {"input_index": 0, "original_frame": 10, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 20, "timestamp": 1.0},
        {"input_index": 2, "original_frame": 30, "timestamp": 2.0},
    ]
    for i in range(len(mapping)):
        (frame_dir / f"frame_{i:04d}.jpg").write_bytes(b"jpg")

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "full",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "未夹紧",
        "location": None,
        "location_canonical": None,
        "fracture_between": None,
        "actual_frame_mapping": mapping,
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "未夹紧",
        "event_frame_effective": 15,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(passed) == 0
    assert len(failed) == 1
    assert any(
        "clamped_event_full_fracture_between_mismatch" in r
        for r in failed[0]["reasons"]
    )
    assert not out_path.exists()


def test_clamped_event_full_location_must_be_null(tmp_path):
    """警告项：source_type=未夹紧 且 event_frame 非 None 时 location 必须为 null。"""
    subvideo_id = "clamped_full_loc"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True)

    mapping = [
        {"input_index": 0, "original_frame": 10, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 20, "timestamp": 1.0},
    ]
    for i in range(len(mapping)):
        (frame_dir / f"frame_{i:04d}.jpg").write_bytes(b"jpg")

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "full",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "未夹紧",
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "fracture_between": [0, 1],
        "actual_frame_mapping": mapping,
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    video_meta_path = tmp_path / "video_meta.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "subvideo_report.json"
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "未夹紧",
        "event_frame_effective": 15,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=data_dir / "04_frames", project_root=tmp_path,
    )

    assert len(passed) == 0
    assert len(failed) == 1
    assert "clamped_event_full_location_should_be_null" in failed[0]["reasons"]
    assert not out_path.exists()


def _build_focus_subvideo(tmp_path, subvideo_id, mapping, event_frame):
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True, exist_ok=True)
    for i in range(len(mapping)):
        (frame_dir / f"frame_{i:04d}.jpg").write_bytes(b"jpg")
    return {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "focus_3s",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "fracture_between": [1, 2],
        "actual_frame_mapping": mapping,
        "frame_paths": [f"04_frames/{subvideo_id}/frame_{i:04d}.jpg" for i in range(len(mapping))],
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
        "processor_info": {"backend": "test"},
    }


def test_label_review_passes_valid_focus_positive(tmp_path):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    mapping = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
        {"input_index": 2, "original_frame": 20, "timestamp": 2.0},
        {"input_index": 3, "original_frame": 30, "timestamp": 3.0},
    ]
    sub = _build_focus_subvideo(tmp_path, "valid_focus", mapping, event_frame=15)
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": "inside_gauge",
        "event_frame_effective": 15,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(passed) == 1
    assert len(failed) == 0
    assert out_path.exists()


@pytest.mark.parametrize(
    "has_fracture,fracture_between,should_pass",
    [
        (None, None, True),
        (True, None, True),
        (True, [0, 1], False),
    ],
)
def test_label_review_special_anomaly_combinations(
    tmp_path, has_fracture, fracture_between, should_pass
):
    subvideo_id = "anomaly"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True, exist_ok=True)

    mapping = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
    ]
    for i in range(len(mapping)):
        (frame_dir / f"frame_{i:04d}.jpg").write_bytes(b"jpg")

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "full_anomaly",
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "type": "视频异常",
        "location": None,
        "location_canonical": None,
        "fracture_between": fracture_between,
        "actual_frame_mapping": mapping,
        "frame_paths": [f"04_frames/{subvideo_id}/frame_{i:04d}.jpg" for i in range(len(mapping))],
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
        "processor_info": {"backend": "test"},
    }
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    rec_has = None if has_fracture is None else True
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "视频异常",
        "has_fracture_canonical": rec_has,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    if should_pass:
        assert len(passed) == 1 and len(failed) == 0
        assert out_path.exists()
    else:
        assert len(failed) == 1
        assert any("anomaly_fracture_between_should_be_null" in r for r in failed[0]["reasons"])
        assert not out_path.exists()


def test_label_review_reports_warning_when_frame_paths_missing(tmp_path):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = _make_subvideo(tmp_path, "warn_frames")
    sub.pop("frame_paths", None)
    sub["actual_frame_mapping"] = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
    ]
    sub["fracture_between"] = [0, 1]
    (_frame_dir(tmp_path) / "warn_frames" / "frame_0001.jpg").write_bytes(b"jpg")
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": "inside_gauge",
        "event_frame_effective": 5,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
    )

    assert len(passed) == 1
    assert len(failed) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "frame_paths_field_missing" in report.get("warnings", [])


def test_label_review_write_invalid_output(tmp_path):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = _make_subvideo(tmp_path, "bad_neg")
    sub["crop_type"] = "neg_before"
    sub["has_fracture"] = False
    sub["has_fracture_canonical"] = False
    sub["fracture_between"] = [0, 1]
    sub["type"] = "未断裂"
    sub["location"] = None
    sub["location_canonical"] = None
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "未断裂",
        "has_fracture_canonical": False,
    }])

    passed, failed = review_labels_module.review_subvideo_labels(
        meta_path, video_meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
        write_invalid_output=True,
    )

    assert len(failed) == 1
    assert out_path.exists()
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["subvideos"][0].get("__review_failed_reasons") == failed[0]["reasons"]


def test_label_review_cli_accepts_input_meta_alias_and_write_invalid_output(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = _make_subvideo(tmp_path, "bad_neg")
    sub["crop_type"] = "neg_before"
    sub["has_fracture"] = False
    sub["has_fracture_canonical"] = False
    sub["fracture_between"] = [0, 1]
    sub["type"] = "未断裂"
    sub["location"] = None
    sub["location_canonical"] = None
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "未断裂",
        "has_fracture_canonical": False,
    }])

    monkeypatch.setattr(sys, "argv", [
        "review_subvideo_labels.py",
        "--input-meta", str(meta_path),
        "--video-meta", str(video_meta_path),
        "--output-meta", str(out_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
        "--write-invalid-output",
    ])
    rc = review_labels_module.main()
    assert rc == 1
    assert out_path.exists()


def test_write_invalid_report_only_cli(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = _make_subvideo(tmp_path, "bad_neg")
    sub["crop_type"] = "neg_before"
    sub["has_fracture"] = False
    sub["has_fracture_canonical"] = False
    sub["fracture_between"] = [0, 1]
    sub["type"] = "未断裂"
    sub["location"] = None
    sub["location_canonical"] = None
    _write_meta(meta_path, {"subvideos": [sub]})
    _write_meta(video_meta_path, [{
        "video_id": "video_0001",
        "type": "未断裂",
        "has_fracture_canonical": False,
    }])

    monkeypatch.setattr(sys, "argv", [
        "review_subvideo_labels.py",
        "--input-meta", str(meta_path),
        "--video-meta", str(video_meta_path),
        "--output-meta", str(out_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
        "--write-invalid-report-only",
    ])
    rc = review_labels_module.main()
    assert rc == 1
    assert out_path.exists()


def test_prune_allow_partial_report_writes_kept_only(tmp_path):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    kept_sub = _make_subvideo(tmp_path, "keep")
    bad_sub = _make_subvideo(tmp_path, "bad", video_exists=True, frames_exist=False)
    _write_meta(meta_path, {"subvideos": [kept_sub, bad_sub]})

    kept, dropped, inconsistent = prune_reviewed_subvideos.prune_reviewed_subvideos(
        meta_path, out_path, report_path,
        frame_dir_root=_frame_dir(tmp_path), project_root=tmp_path,
        allow_partial_report=True,
    )

    assert len(kept) == 1
    assert len(inconsistent) == 1
    assert out_path.exists()
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(out["subvideos"]) == 1
    assert out["subvideos"][0]["subvideo_id"] == "keep"


def test_prune_allow_partial_report_cli_returns_nonzero(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    out_path = tmp_path / "subvideos_meta.reviewed.json"
    report_path = tmp_path / "report.json"

    kept_sub = _make_subvideo(tmp_path, "keep")
    bad_sub = _make_subvideo(tmp_path, "bad", video_exists=True, frames_exist=False)
    _write_meta(meta_path, {"subvideos": [kept_sub, bad_sub]})

    monkeypatch.setattr(sys, "argv", [
        "prune_reviewed_subvideos.py",
        "--input-meta", str(meta_path),
        "--output-meta", str(out_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
        "--allow-partial-report",
    ])
    rc = prune_reviewed_subvideos.main()
    assert rc == 1
    assert out_path.exists()
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(out["subvideos"]) == 1


def test_repair_cli_accepts_input_meta_alias(tmp_path, monkeypatch):
    meta_path = tmp_path / "subvideos_meta.json"
    report_path = tmp_path / "report.json"

    sub = _make_subvideo(tmp_path, "keep")
    _write_meta(meta_path, {"subvideos": [sub]})

    monkeypatch.setattr(sys, "argv", [
        "repair_review_media.py",
        "--input-meta", str(meta_path),
        "--report", str(report_path),
        "--frame-dir", str(_frame_dir(tmp_path)),
        "--project-root", str(tmp_path),
    ])
    rc = repair_review_media.main()
    assert rc == 0
    expected_output = tmp_path / "data" / "07_metadata" / "subvideos_meta.repaired.json"
    assert expected_output.exists()
