"""Independent contract checks for the new ROI-to-subvideo entry.

Only tiny synthetic media is processed. Production project media is never read.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from script.sub_video import generate as generator
from script.sub_video import verification


def media(count=600, fps=10):
    return {"fps": fps, "total_frames": count, "duration": count / fps,
            "timestamps": [i / fps for i in range(count)], "width": 96, "height": 64,
            "nominal_frame_rate": str(fps), "timestamp_origin": 0.0}


def annotation(video_id="video_0003", **changes):
    return {"id": video_id, "断裂状态": "发生断裂", "断裂模式": "脆性断裂",
            "断裂位置": "标距内", "异常_未夹紧": "否", "异常_视频异常": "否",
            "异常_爆炸性断裂": "否", "现象_伸长": "否", "现象_颈缩": "否",
            "现象_开裂": "否", "现象_界面分离": "否", "现象_断后脱夹": "否",
            "视频帧率": "10", "断裂时间点": "30", "断裂帧_前": "299",
            "断裂帧_后": "300", "断裂时间范围_下界": "", "断裂时间范围_上界": "",
            **changes}


@pytest.mark.parametrize("changes", [
    {"异常_视频异常": "是"},
    {"断裂模式": "无法确定"},
    {"断裂位置": "无法确定"},
    {"异常_爆炸性断裂": "是", "断裂模式": "脆性断裂"},
    {"异常_视频异常": "无法判断", "断裂模式": "无法确定"},
])
def test_reliable_event_is_not_discarded_for_compatible_new_labels(changes):
    row = annotation(**changes)
    record = generator.adapt_annotation(row, media())
    windows, _ = generator.plan_windows(record, media())
    assert windows
    assert any(w["window_role"] == "transition" for w in windows)
    assert row == annotation(**changes), "planning must not rewrite original annotations"


def test_video_abnormal_without_event_reports_the_actual_label():
    row = annotation(异常_视频异常="是", 断裂状态="未断裂", 断裂模式="无",
                     断裂帧_前="无", 断裂帧_后="无", 断裂时间点="无")
    with pytest.raises(generator.PendingSource) as caught:
        generator.adapt_annotation(row, media())
    assert str(caught.value) == "视频异常"


def test_unclamped_missing_phenomenon_time_cannot_borrow_fracture_anchor():
    with pytest.raises(generator.PendingSource, match="未夹紧.*缺少现象时刻"):
        generator.adapt_annotation(annotation(异常_未夹紧="是"), media())


def test_unknown_state_without_time_is_not_a_negative_example():
    with pytest.raises(generator.PendingSource, match="无法确定"):
        generator.adapt_annotation(annotation(断裂状态="无法确定", 断裂帧_前="无",
                                             断裂帧_后="无", 断裂时间点=""), media())


def test_exact_event_windows_keep_guard_and_two_second_post_material():
    record = generator.adapt_annotation(annotation(), media())
    windows, _ = generator.plan_windows(record, media())
    assert windows
    for w in windows:
        assert w["end_frame"] > w["start_frame"]
        assert w["duration"] >= 1.0 - 1e-6
        if w["window_role"] == "pre_event":
            assert w["end_time"] <= 29.5 + 1e-8
        elif w["window_role"] == "post_event":
            assert w["start_time"] >= 30.5 - 1e-8
        elif w["window_role"] == "transition":
            assert w["start_frame"] < 300 < w["end_frame"]


def test_complete_range_is_covered_without_using_a_midpoint():
    row = annotation(断裂模式="无法确定", 断裂帧_前="无", 断裂帧_后="无", 断裂时间点="",
                     断裂时间范围_下界="29", 断裂时间范围_上界="31")
    record = generator.adapt_annotation(row, media())
    windows, _ = generator.plan_windows(record, media())
    event_windows = [w for w in windows if w["window_role"] == "transition"]
    assert event_windows
    for w in windows:
        if w["window_role"] == "transition":
            assert w["start_frame"] <= 290 and w["end_frame"] > 310
        elif w["window_role"] == "pre_event":
            assert w["end_time"] <= 28.5 + 1e-8
        elif w["window_role"] == "post_event":
            assert w["start_time"] >= 31.5 - 1e-8


@pytest.mark.parametrize("count,post_allowed", [(324, False), (325, True)])
def test_post_material_threshold_is_separate_from_clip_minimum(count, post_allowed):
    description = media(count=count)
    record = generator.adapt_annotation(annotation(), description)
    windows, _ = generator.plan_windows(record, description)
    assert any(w["window_role"] == "post_event" for w in windows) is post_allowed


@pytest.mark.parametrize("role,expected", [("pre", "未断裂"), ("fracture", "发生断裂"),
                                           ("post", "已断裂"), ("no_fracture", "未断裂")])
def test_candidate_state_follows_the_clip_and_does_not_rewrite_source(role, expected):
    row = annotation(断裂模式="无法确定", 断裂位置="无法确定", 异常_视频异常="是")
    labels = generator.candidate_labels(row, role)
    assert labels["断裂状态"] == expected
    assert labels["异常情况"]["视频异常"] == "是"
    assert labels["断裂模式"] == ("无" if expected == "未断裂" else "无法确定")
    assert labels["断裂位置"] == ("无" if expected == "未断裂" else "无法确定")
    assert row["断裂状态"] == "发生断裂"
    assert row["断裂模式"] == row["断裂位置"] == "无法确定"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encode(command):
    subprocess.run(command, check=True, capture_output=True)


@pytest.fixture
def synthetic_project(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required for synthetic media integration")
    # All file encodes, decodes, frame/PTS checks and proof hashes remain real.
    # The local FFmpeg version is not the production-pinned 4.4.2 toolchain.
    monkeypatch.setattr(verification, "_toolchain", lambda: {"synthetic_version_gate": "simulated"})
    root = tmp_path / "project"
    split = root / "data/splits/three-fold"
    split.mkdir(parents=True)
    ids = ["video_0001", "video_0003", "video_0004"]
    (split / "test.json").write_text(json.dumps({"video_ids": ["video_9999"]}))
    for fold in range(3):
        for part, values in (("val", [ids[fold]]),
                             ("train", [x for x in ids if x != ids[fold]])):
            (split / f"fold_{fold}_{part}.json").write_text(json.dumps({"video_ids": values}))
    rows = [annotation(ids[0]),
            annotation(ids[1], 异常_视频异常="是", 断裂模式="无法确定",
                       断裂帧_前="29", 断裂帧_后="30", 断裂时间点="3"),
            annotation(ids[2], 断裂状态="未断裂", 断裂模式="无", 断裂位置="无",
                       断裂帧_前="无", 断裂帧_后="无", 断裂时间点="无")]
    csv_path = root / "data/annotation-table-full.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        writer.writerow(annotation("video_9999", 断裂状态="TEST_MUST_NOT_BE_INTERPRETED"))
    template = tmp_path / "synthetic-source.mp4"
    encode(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=10",
            "-t", "6", "-threads", "1", "-c:v", "libx264", "-crf", "18",
            "-pix_fmt", "yuv420p", str(template)])
    roi_rows = []
    for video_id in ids:
        source = root / "data/videos" / f"{video_id}.mp4"
        roi = root / "data/roi/videos" / f"{video_id}.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        roi.parent.mkdir(parents=True, exist_ok=True)
        if video_id == ids[0]:
            # Validation media deliberately does not exist: opening it is a bug.
            roi_rows.append({"video_id": video_id, "status": "VALIDATION_MUST_NOT_BE_READ"})
            continue
        shutil.copyfile(template, source)
        encode(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source),
                "-map", "0:v:0", "-vf", "crop=64:48:2:4,setsar=1", "-vsync", "0",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-an", "-movflags", "+faststart", str(roi)])
        roi_rows.append({"video_id": video_id, "status": "success", "source": {"sha256": digest(source)},
                         "decision": {"source_sha256": digest(source), "mode": "fixed_roi",
                                      "source_resolution": [96, 64],
                                      "pixel_box": {"x": 2, "y": 4, "width": 64, "height": 48}},
                         "output": {"sha256": digest(roi), "encoding": {"video_codec": "libx264",
                                    "preset": "fast", "crf": 23, "pixel_format": "yuv420p",
                                    "audio": "dropped", "frame_sync": "vsync_0_passthrough"},
                                    "geometry": {"filter": "crop=64:48:2:4,setsar=1",
                                        "effective_pixel_box": {"x": 2, "y": 4, "width": 64, "height": 48},
                                        "pad_pixels": {"left": 0, "right": 0, "top": 0, "bottom": 0},
                                        "output_resolution": [64, 48]}}})
    roi_rows.append({"video_id": "video_9999", "status": "TEST_MUST_NOT_BE_READ"})
    (root / "data/roi/manifest.json").write_text(json.dumps({"videos": roi_rows}))
    return root


def test_full_run_uses_only_selected_training_fold_and_persists_real_proofs(synthetic_project):
    root = synthetic_project
    manifest = generator.run(root, fold=0)
    output = root / "data/sub_video"
    persisted = json.loads((output / "manifest.json").read_text())
    summary = json.loads((output / "summary.json").read_text())
    assert manifest == persisted
    assert {s["video_id"] for s in persisted["sources"]} == {"video_0003", "video_0004"}
    clips = persisted["candidates"]
    assert clips and summary
    assert persisted["published"] is False
    assert all(c["source_video_id"] in {"video_0003", "video_0004"} for c in clips)
    for c in clips:
        path = output / c["output_path"]
        assert re.fullmatch(r"video_000[34]_(pre|fracture|post|no_fracture)_\d{2,}\.mp4", path.name)
        assert c["status"] == "cropped" and path.is_file()
        actual = c["output"]
        assert digest(path) == actual["sha256"]
        assert actual["frame_preserving_replay"]["status"] == verification.VERIFIED
        assert actual["media"]["total_frames"] == c["end_frame"] - c["start_frame"]
        assert c["manual_review"] == "required"
        assert c["final_labels"] is None and c["review"]["status"] == "未审核"
        assert c["source_labels"]["断裂状态"] in {"发生断裂", "未断裂"}
        assert "candidate_v3_labels" not in c
        for anchor in actual["frame_mapping"]["anchors"]:
            assert anchor["output_frame"] == anchor["source_frame"] - c["start_frame"]
    assert len(list((output / "videos").glob("*.mp4"))) == len(clips)
    for video_id in {c["source_video_id"] for c in clips}:
        for role in {c["role"] for c in clips}:
            group = [c for c in clips if c["source_video_id"] == video_id and c["role"] == role]
            order = sorted(group, key=lambda c: (c["start_frame"], c["end_frame"]))
            assert [c["sequence"] for c in order] == list(range(1, len(order) + 1))


def test_failed_clip_proof_cannot_leave_a_published_output(synthetic_project, monkeypatch):
    def reject(*args, **kwargs):
        raise verification.ReplayUncertain("synthetic_clip_proof_refusal")
    monkeypatch.setattr(verification, "verify_clip_replay", reject)
    manifest = generator.run(synthetic_project, fold=0)
    assert manifest["candidates"]
    assert not any(c["status"] == "cropped" for c in manifest["candidates"])
    assert manifest["complete"] is False and manifest["published"] is False
    assert not list((synthetic_project / "data/sub_video/videos").glob("*.mp4"))


def test_real_same_count_one_frame_shift_cannot_pass_the_new_entry(synthetic_project, monkeypatch):
    real_command = generator.aligned.build_crop_command

    def shifted_command(source, output, candidate):
        shifted = dict(candidate, start_frame=candidate["start_frame"] + 1,
                       end_frame=candidate["end_frame"] + 1)
        return real_command(source, output, shifted)

    monkeypatch.setattr(generator.aligned, "build_crop_command", shifted_command)
    manifest = generator.run(synthetic_project, fold=0)
    assert manifest["candidates"] and not manifest["complete"]
    assert not any(c["status"] == "cropped" for c in manifest["candidates"])
    assert not list((synthetic_project / "data/sub_video/videos").glob("*.mp4"))


def test_failed_source_proof_cannot_create_candidates(synthetic_project, monkeypatch):
    def reject(*args, **kwargs):
        raise verification.ReplayUncertain("synthetic_proof_refusal")
    monkeypatch.setattr(verification, "verify_source_replay", reject)
    manifest = generator.run(synthetic_project, fold=0, plan_only=True)
    assert manifest["candidates"] == []
    assert not list((synthetic_project / "data/sub_video/videos").glob("*.mp4"))


@pytest.mark.parametrize("changes,reason", [
    ({"异常_视频异常": "是", "断裂状态": "未断裂"}, "视频异常"),
    ({"异常_未夹紧": "是", "异常_视频异常": "否", "断裂状态": "未断裂"}, "未夹紧"),
])
def test_label_only_rejections_precede_media_reads_and_never_fall_back_to_negative(
        synthetic_project, changes, reason):
    root = synthetic_project
    csv_path = root / "data/annotation-table-full.csv"
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows, fields = list(reader), reader.fieldnames
    selected = next(r for r in rows if r["id"] == "video_0003")
    selected.update({"断裂帧_前": "无", "断裂帧_后": "无", "断裂时间点": "无", **changes})
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    # Missing files ensure that the exact rejection reason comes from labels,
    # rather than silently touching media before applying those rules.
    (root / "data/videos/video_0003.mp4").unlink()
    (root / "data/roi/videos/video_0003.mp4").unlink()
    manifest = generator.run(root, fold=0, plan_only=True)
    source = next(s for s in manifest["sources"] if s["video_id"] == "video_0003")
    assert source["status"] == "pending" and source["reason"].startswith(reason)
    assert not any(c["source_video_id"] == "video_0003" for c in manifest["candidates"])


def test_existing_results_are_not_overwritten(synthetic_project):
    output = synthetic_project / "data/sub_video"
    output.mkdir()
    marker = output / "manifest.json"
    marker.write_bytes(b"existing user results")
    with pytest.raises(generator.base.PilotError, match="exist|已存在"):
        generator.run(synthetic_project, fold=0, plan_only=True)
    assert marker.read_bytes() == b"existing user results"


def test_resume_cannot_switch_the_selected_training_fold(synthetic_project):
    generator.run(synthetic_project, fold=0, plan_only=True)
    output = synthetic_project / "data/sub_video"
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(generator.base.PilotError, match="fold|identity"):
        generator.run(synthetic_project, fold=1, plan_only=True, resume=True)
    assert (output / "manifest.json").read_bytes() == before
