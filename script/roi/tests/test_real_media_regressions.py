"""Small generated media protects behavior that mocked ffmpeg cannot verify."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from script.roi import core


def run(command):
    return subprocess.run(command, check=True, capture_output=True)


def make_source(path: Path, *, duration=1, rate=30, solid=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    pattern = "color=red" if solid else "testsrc2"
    run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         f"{pattern}=size=64x48:rate={rate}:duration={duration}" if not solid else
         f"color=red:size=64x48:rate={rate}:duration={duration}",
         "-c:v", "libx264", "-g", "90", "-bf", "0", "-pix_fmt", "yuv420p", str(path)])


def review(duration):
    return {"items": {key: {"result": "judgable", "cause": "source", "note": ""}
                      for key in core.EVIDENCE_ITEMS},
            "checked_intervals": [[0, duration]], "confirmed": True}


def test_recorded_no_crop_padding_equals_real_output_pixels(tmp_path):
    source = tmp_path / "red.mp4"
    output = tmp_path / "padded.mp4"
    make_source(source, rate=10, solid=True)
    decision = {"mode": "no_crop", "source_resolution": [64, 48]}
    geometry = core.geometry(decision)
    run(core.build_ffmpeg_command(source, output, decision))
    width, height = geometry["output_resolution"]
    pixels = run(["ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
                  "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    assert len(pixels) == width * height
    positions = [(i % width, i // width) for i, value in enumerate(pixels) if value > 40]
    left = min(x for x, _ in positions)
    right = max(x for x, _ in positions)
    top = min(y for _, y in positions)
    bottom = max(y for _, y in positions)
    assert (left, top, right - left + 1, bottom - top + 1) == (
        geometry["pad_pixels"]["left"], geometry["pad_pixels"]["top"], 64, 48)
    assert width - right - 1 == geometry["pad_pixels"]["right"]
    assert height - bottom - 1 == geometry["pad_pixels"]["bottom"]


def test_trim_with_header_preroll_generates_using_decoded_count_and_reuses_verification(tmp_path, monkeypatch):
    original = tmp_path / "full.mp4"
    make_source(original, duration=3)
    videos = tmp_path / "videos"
    videos.mkdir()
    trimmed = videos / "trimmed.mp4"
    run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(original), "-t", "1",
         "-c", "copy", str(trimmed)])
    metadata = json.loads(run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                              "-show_entries", "stream=nb_frames,nb_read_frames", "-of", "json",
                              str(trimmed)]).stdout)["streams"][0]
    assert int(metadata["nb_frames"]) > int(metadata["nb_read_frames"]) == 30
    calls = []
    original_run = core.subprocess.run

    def record_count(command, **kwargs):
        if command[0] == "ffprobe" and "-count_frames" in command:
            calls.append(str(command[-1]))
        return original_run(command, **kwargs)

    monkeypatch.setattr(core.subprocess, "run", record_count)
    work = core.Workspace(videos, tmp_path / "roi")
    row = work.refresh()["videos"][0]
    assert calls == []  # Browsing the list must not decode every source.
    work.save_decision(row, {"mode": "no_crop", "source_review": review(1)})
    work.generate("trimmed")
    generated = work.inventory()["videos"][0]
    assert generated["status"] == "success"
    assert generated["source"]["media"]["frame_count"] == 30
    assert generated["output"]["media"]["frame_count"] == 30
    source_count_calls = calls.count(str(trimmed))
    assert source_count_calls == 1
    count_after_generation = len(calls)
    work.refresh()
    work.save_output_review("trimmed", review(1))
    work.refresh(verify_source_ids={"trimmed"})
    assert work.inventory()["complete"] is True
    assert calls.count(str(trimmed)) == source_count_calls
    assert len(calls) == count_after_generation


def test_explicit_new_no_crop_rebuilds_padding_without_altering_legacy_file(tmp_path):
    source = tmp_path / "videos/red.mp4"
    make_source(source, rate=10, solid=True)
    work = core.Workspace(source.parent, tmp_path / "roi")
    row = work.refresh()["videos"][0]
    work.save_decision(row, {"mode": "no_crop", "source_review": review(1)})
    work.existing_media_dir.mkdir(parents=True)
    candidate = work.existing_media_dir / "red.mp4"
    old_filter = "pad=66:88:1:20:color=black,setsar=1"
    run(["ffmpeg", "-v", "error", "-i", str(source), "-vf", old_filter,
         "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-an", "-vsync", "0", str(candidate)])
    old_hash = core.sha256_file(candidate)
    core.atomic_json(work.existing_manifest, {
        "encoding_profile": {"video_codec": "libx264", "preset": "fast", "crf": 23,
                             "pixel_format": "yuv420p", "audio": "dropped",
                             "frame_sync": "vsync_0_passthrough"},
        "videos": [{"source_video_id": "red", "source_sha256": row["source"]["sha256"],
                    "mode": "no_crop", "output_sha256": old_hash, "video_filter": old_filter}],
    })
    work.generate("red")
    output = work.inventory()["videos"][0]
    assert output["output"]["origin"] == "generated"
    assert output["status"] == "success"
    assert core.sha256_file(candidate) == old_hash


def test_preview_near_video_end_does_not_crash_the_page(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    make_source(tmp_path / "data/videos/short.mp4", rate=10)
    app = Path(core.__file__).with_name("app.py")
    monkeypatch.syspath_prepend(str(app.parent))
    monkeypatch.setattr(sys, "argv", [str(app), "--project-root", str(tmp_path)])
    page = AppTest.from_file(str(app)).run(timeout=10)
    assert not page.exception
    preview = next(widget for widget in page.slider if widget.label == "抽帧时间（可拖动）")
    page = preview.set_value(0.99).run(timeout=10)
    assert not page.exception
    preview = next(widget for widget in page.slider if widget.label == "抽帧时间（可拖动）")
    page = preview.set_value(0.5).run(timeout=10)
    assert not page.exception
    assert any(widget.label == "保存当前决定" for widget in page.button)


def install_real_legacy(work, source, candidate, *, mode, box, video_filter):
    media = core.probe_video(source)
    output_media = core.probe_video(candidate)
    decision = {"source_video_id": source.stem, "source_sha256": core.sha256_file(source),
                "source_resolution": [media["width"], media["height"]],
                "mode": mode, "pixel_box": box, "review_status": "approved"}
    core.atomic_json(work.candidate_path, {"decisions": [decision]})
    core.atomic_json(work.existing_manifest, {"videos": [{
        "source_video_id": source.stem, "source_sha256": decision["source_sha256"],
        "mode": mode, "pixel_box": box, "output_sha256": core.sha256_file(candidate),
        "output_resolution": [output_media["width"], output_media["height"]],
        "duration": output_media["duration"], "nominal_frame_rate": output_media["nominal_frame_rate"],
        "video_filter": video_filter,
    }]})


def test_old_rounded_padding_is_kept_byte_for_byte_and_records_real_margins(tmp_path):
    source = tmp_path / "videos/red.mp4"
    make_source(source, rate=10, solid=True)
    work = core.Workspace(source.parent, tmp_path / "roi")
    work.existing_media_dir.mkdir(parents=True)
    candidate = work.existing_media_dir / "red.mp4"
    old_filter = "pad=66:88:1:20:color=black,setsar=1"
    run(["ffmpeg", "-v", "error", "-i", str(source), "-vf", old_filter,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(candidate)])
    old_bytes = candidate.read_bytes()
    install_real_legacy(work, source, candidate, mode="no_crop", box=None, video_filter=old_filter)
    result = work.refresh()
    row = result["videos"][0]
    assert result["complete"] is True
    assert row["status"] == "success"
    assert row["output"]["origin"] == "preserved_legacy"
    assert Path(row["output"]["path"]).read_bytes() == old_bytes == candidate.read_bytes()
    assert row["output"]["geometry"]["pad_pixels"] == {"left": 0, "right": 2, "top": 20, "bottom": 20}
    raw = run(["ffmpeg", "-v", "error", "-i", str(candidate), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"]).stdout
    positions = [(i % 66, i // 66) for i, value in enumerate(raw) if value > 40]
    assert (min(x for x, _ in positions), max(x for x, _ in positions)) == (0, 63)
    assert (min(y for _, y in positions), max(y for _, y in positions)) == (20, 67)
    assert row["visual_review"] == {"required": False, "status": "not_recorded"}
    assert not row.get("output_review")


def test_old_nonexact_crop_is_kept_with_effective_offset_not_silently_reencoded(tmp_path):
    source = tmp_path / "videos/cropped.mp4"
    make_source(source, rate=10)
    work = core.Workspace(source.parent, tmp_path / "roi")
    work.existing_media_dir.mkdir(parents=True)
    candidate = work.existing_media_dir / "cropped.mp4"
    old_filter = "crop=30:40:3:3,setsar=1"
    run(["ffmpeg", "-v", "error", "-i", str(source), "-vf", old_filter,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(candidate)])
    box = {"x": 3, "y": 3, "width": 30, "height": 40}
    install_real_legacy(work, source, candidate, mode="fixed_roi", box=box, video_filter=old_filter)
    old_hash = core.sha256_file(candidate)
    row = work.refresh()["videos"][0]
    assert row["status"] == "success"
    assert row["output"]["origin"] == "preserved_legacy"
    assert row["output"]["sha256"] == old_hash
    assert core.sha256_file(Path(row["output"]["path"])) == old_hash
    geometry = row["output"]["geometry"]
    assert geometry["requested_pixel_box"] == box
    assert geometry["effective_pixel_box"] == {"x": 2, "y": 2, "width": 30, "height": 40}
    assert geometry["crop_pixels"] == {"left": 2, "right": 32, "top": 2, "bottom": 6}
    assert not row.get("output_review")


def test_existing_roi_page_shows_prefilled_labels_without_requiring_approval(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    source = tmp_path / "data/videos/old.mp4"
    make_source(source, rate=10)
    work = core.Workspace(source.parent, tmp_path / "data/roi")
    work.existing_media_dir.mkdir(parents=True)
    candidate = work.existing_media_dir / "old.mp4"
    old_filter = "crop=30:40:3:3,setsar=1"
    run(["ffmpeg", "-v", "error", "-i", str(source), "-vf", old_filter,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(candidate)])
    install_real_legacy(work, source, candidate, mode="fixed_roi",
                        box={"x": 3, "y": 3, "width": 30, "height": 40}, video_filter=old_filter)
    app = Path(core.__file__).with_name("app.py")
    monkeypatch.syspath_prepend(str(app.parent))
    monkeypatch.setattr(sys, "argv", [str(app), "--project-root", str(tmp_path)])
    page = AppTest.from_file(str(app)).run(timeout=10)
    assert not page.exception
    selectors = {widget.label: widget for widget in page.selectbox}
    assert {"选择视频", "断裂状态", "断裂模式", "断裂位置", "未夹紧", "视频异常", "爆炸性断裂",
            "伸长", "颈缩", "开裂", "界面分离", "断后脱夹"} <= set(selectors)
    # Missing annotation cells remain blank, rather than defaulting to a label.
    assert selectors["断裂状态"].value == ""
    assert selectors["未夹紧"].value == ""
    assert {"上夹具清晰可见", "下夹具清晰可见", "完整试样清晰可见", "仍可判断标距内/外位置",
            "仍可判断是否齐根断裂", "我已检查关键时刻预览"} <= {widget.label for widget in page.checkbox}
    assert not any("审核" in widget.label or "通过" in widget.label for widget in page.button)
    manifest = core.load_json(work.manifest_path)
    assert manifest["complete"] is True
    assert manifest["videos"][0]["visual_review"]["status"] == "not_recorded"
