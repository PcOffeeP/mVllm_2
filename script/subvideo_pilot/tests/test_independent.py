"""Independent behavioral oracles from the pre-migration planner.

The frame ranges below were obtained from mVllm_2 commit
2c272ce3548c917bbfa96fe474858f9bf1998893 on synthetic records, with no
references. They deliberately do not calculate expectations using the new
implementation or read any project media.
"""
from __future__ import annotations

import pytest
import csv
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from script.subvideo_pilot import geometry, pilot


def source_record(**changes):
    return {
        "video_id": "fixture_ductile", "type": "韧性断裂",
        "has_fracture": True, "is_abnormal_canonical": False,
        "location_canonical": "inside_gauge", "duration": 60.0,
        "fps": 10.0, "total_frames": 600, "event_time": 30.0,
        "event_time_reliable": True, **changes,
    }


TRANSITION_RANGES = [
    (296, 316), (290, 320), (275, 325), (235, 335), (140, 340),
    (293, 313), (285, 315), (268, 318), (220, 320), (260, 460),
]
DUCTILE_PRE_RANGES = [
    (0, 20), (138, 158), (275, 295),
    (0, 30), (132, 162), (265, 295),
    (0, 50), (122, 172), (245, 295),
    (0, 100), (98, 198), (195, 295),
    (0, 200), (48, 248), (95, 295),
]
POST_RANGES = [(305, 600), (305, 404), (404, 502), (502, 600)]


@pytest.mark.parametrize("record, expected", [
    (
        source_record(),
        [("transition", *r) for r in TRANSITION_RANGES]
        + [("pre_event", *r) for r in DUCTILE_PRE_RANGES]
        + [("post_event", *r) for r in POST_RANGES],
    ),
    (
        source_record(video_id="fixture_brittle", type="脆性断裂"),
        [("transition", *r) for r in TRANSITION_RANGES]
        + [("pre_event", *r) for r in [(275, 295), (245, 295), (95, 295)]]
        + [("post_event", *r) for r in POST_RANGES],
    ),
    (
        source_record(video_id="fixture_negative", type="无",
                      has_fracture=False, event_time=None),
        [("stable_negative", *r) for r in [
            (110, 130), (195, 225), (275, 325), (340, 440), (380, 580),
        ]],
    ),
])
def test_migrated_geometry_keeps_original_empty_reference_windows(record, expected):
    windows = geometry._raw_candidates_for_source(record, references=())
    actual = [(w["window_role"], w["start_frame"], w["end_frame"]) for w in windows]
    assert actual == expected


@pytest.mark.parametrize("changes", [
    {"event_time": None},
    {"event_time_reliable": False},
    {"is_abnormal_canonical": True},
    {"type": "未夹紧"},
    {"has_fracture": None},
])
def test_old_geometry_does_not_invent_windows_for_unsupported_sources(changes):
    assert geometry._raw_candidates_for_source(source_record(**changes)) == []


@pytest.mark.parametrize("duration, total_frames, post_allowed", [
    (32.5, 325, True),
    (32.4, 324, False),
    # Header duration reaches two seconds after the guard, but decoded frames
    # stop 0.1 seconds earlier. The extra header time is not usable material.
    (32.5, 324, False),
    # The opposite mismatch must still honor the shorter declared duration.
    (32.4, 325, False),
])
def test_post_admission_checks_source_material_after_guard(duration, total_frames, post_allowed):
    record = source_record(duration=duration, total_frames=total_frames)
    original = geometry._raw_candidates_for_source(record)
    assert any(w["window_role"] == "post_event" for w in original)
    accepted, excluded = pilot.plan_windows(record)
    posts = [w for w in accepted if w["window_role"] == "post_event"]
    assert bool(posts) is post_allowed
    # Tightening may remove old windows; it must never create a new interval.
    signature = lambda w: (w["window_role"], w["start_frame"], w["end_frame"])
    assert {signature(w) for w in accepted} <= {signature(w) for w in original}
    assert [signature(w) for w in accepted if w["window_role"] != "post_event"] == [
        signature(w) for w in original if w["window_role"] != "post_event"
    ]
    if not post_allowed:
        assert excluded and all(
            w["reason"] == "post_source_remaining_after_guard_less_than_two_seconds"
            for w in excluded
        )


MEDIA = {"width": 320, "height": 240, "fps": 10.0,
         "nominal_frame_rate": "10", "total_frames": 600, "duration": 60.0}


@pytest.mark.parametrize("changes", [
    {"断裂状态": "无法确定"},
    {"断裂时间点": "", "断裂时间范围_下界": "29", "断裂时间范围_上界": "31"},
    {"断裂时间点": "31"},
    {"断裂帧_前": "298"},
    {"异常_爆炸性断裂": "是"},
])
def test_current_annotations_do_not_fabricate_reliable_events_or_override_conflicts(changes):
    row = {"id": "video_0001", "断裂状态": "发生断裂", "断裂模式": "韧性断裂",
           "异常_未夹紧": "否", "异常_视频异常": "否", "异常_爆炸性断裂": "否",
           "断裂时间点": "30", "断裂帧_前": "299", "断裂帧_后": "300", **changes}
    with pytest.raises(pilot.SkipSource):
        pilot.adapt_annotation(row, MEDIA)


def synthetic_project(tmp_path):
    """Three development sources, one deliberately unusable test record."""
    root = tmp_path / "project"
    ids = ["video_0001", "video_0002", "video_0003"]
    splitdir = root / "data/splits/three-fold"
    splitdir.mkdir(parents=True)
    (splitdir / "test.json").write_text(json.dumps({"video_ids": ["video_9999"]}))
    for fold in range(3):
        for part, values in (("val", [ids[fold]]),
                             ("train", [v for v in ids if v != ids[fold]])):
            (splitdir / f"fold_{fold}_{part}.json").write_text(json.dumps({"video_ids": values}))
    fields = ["id", "断裂状态", "断裂模式", "异常_未夹紧", "异常_视频异常",
              "异常_爆炸性断裂", "断裂时间点", "断裂帧_前", "断裂帧_后"]
    annotation = root / "data/annotation-table-full.csv"
    with annotation.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for video_id in ids:
            writer.writerow({"id": video_id, "断裂状态": "未断裂", "断裂模式": "无",
                             "异常_未夹紧": "否", "异常_视频异常": "否",
                             "异常_爆炸性断裂": "否", "断裂时间点": "无",
                             "断裂帧_前": "无", "断裂帧_后": "无"})
        writer.writerow({"id": "video_9999", "断裂状态": "TEST_VALUES_MUST_NOT_BE_INTERPRETED"})
    records = []
    for video_id in ids:
        raw = root / "data/videos" / f"{video_id}.mp4"
        roi = root / "data/roi/videos" / f"{video_id}.mp4"
        raw.parent.mkdir(parents=True, exist_ok=True)
        roi.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes((video_id + ":source").encode())
        roi.write_bytes((video_id + ":ROI").encode())
        source_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
        records.append({"video_id": video_id, "status": "success",
                        "source": {"sha256": source_sha},
                        "output": {"sha256": hashlib.sha256(roi.read_bytes()).hexdigest()},
                        "decision": {"source_sha256": source_sha}})
    records.append({"video_id": "video_9999", "status": "TEST_ROI_MUST_NOT_BE_INTERPRETED"})
    (root / "data/roi/manifest.json").write_text(json.dumps({"videos": records}))
    return root


def fake_media_tools(monkeypatch):
    monkeypatch.setattr(pilot.shutil, "which", lambda _: "/synthetic/tool")
    monkeypatch.setattr(pilot, "probe_video", lambda _: dict(MEDIA))


def test_run_filters_test_before_touching_media_and_keeps_labels_unassigned(tmp_path, monkeypatch):
    root = synthetic_project(tmp_path)
    fake_media_tools(monkeypatch)
    real_sha = pilot.sha256_file
    accessed = []

    def checked_sha(path):
        assert Path(path).name != "video_9999.mp4"
        accessed.append(Path(path))
        return real_sha(path)

    def checked_probe(path):
        assert Path(path).name != "video_9999.mp4"
        accessed.append(Path(path))
        return dict(MEDIA)

    monkeypatch.setattr(pilot, "sha256_file", checked_sha)
    monkeypatch.setattr(pilot, "probe_video", checked_probe)
    manifest = pilot.run(root, tmp_path / "initial-cuts", plan_only=True)
    assert {s["video_id"] for s in manifest["sources"]} == {
        "video_0001", "video_0002", "video_0003"
    }
    assert manifest["candidates"] and accessed
    assert manifest["five_category_labels"] == "not_assigned_pending_clip_review"
    assert manifest["published"] is False
    assert all(c["scope"] == "development" and c["manual_review"] == "required"
               and c["labels_status"] == "unassigned" for c in manifest["candidates"])


def test_existing_output_is_rejected_without_replacing_files(tmp_path, monkeypatch):
    root = synthetic_project(tmp_path)
    fake_media_tools(monkeypatch)
    output = tmp_path / "existing-output"
    output.mkdir()
    marker = output / "manifest.json"
    marker.write_bytes(b"existing results")
    with pytest.raises(pilot.PilotError, match="output already exists"):
        pilot.run(root, output, plan_only=True)
    assert marker.read_bytes() == b"existing results"


def test_changed_roi_digest_is_not_admitted_to_candidates(tmp_path, monkeypatch):
    root = synthetic_project(tmp_path)
    fake_media_tools(monkeypatch)
    (root / "data/roi/videos/video_0001.mp4").write_bytes(b"changed ROI")
    manifest = pilot.run(root, tmp_path / "initial-cuts", plan_only=True)
    source = next(s for s in manifest["sources"] if s["video_id"] == "video_0001")
    assert source["status"] == "skipped"
    assert source["reason"] == "source_or_ROI_sha256_mismatch"
    assert not any(c["source_video_id"] == "video_0001" for c in manifest["candidates"])


def test_media_changed_during_cut_cannot_be_recorded_as_success(tmp_path, monkeypatch):
    root = synthetic_project(tmp_path)
    fake_media_tools(monkeypatch)
    output = tmp_path / "initial-cuts"

    cuts = {}

    def synthetic_ffmpeg(command):
        if "-vf" in command:
            source = Path(command[command.index("-i") + 1])
            destination = Path(command[-1])
            trim = command[command.index("-vf") + 1]
            start, end = map(int, re.search(r"start_frame=(\d+):end_frame=(\d+)", trim).groups())
            destination.write_bytes(b"synthetic cut")
            cuts[destination] = {**MEDIA, "total_frames": end - start,
                                 "duration": (end - start) / MEDIA["fps"]}
            if source.name == "video_0001.mp4":
                source.write_bytes(b"changed during processing")
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(pilot, "_checked", synthetic_ffmpeg)
    monkeypatch.setattr(pilot, "probe_video", lambda path: cuts.get(Path(path), dict(MEDIA)))
    try:
        pilot.run(root, output)
    except pilot.PilotError:
        pass
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["complete"] is False
    assert not any(c["source_video_id"] == "video_0001" and c["status"] == "cropped"
                   for c in manifest["candidates"])
