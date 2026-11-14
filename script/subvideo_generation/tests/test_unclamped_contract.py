"""Unclamped anchors and frame-preserving outputs, using synthetic inputs only."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from script.subvideo_generation._legacy.core import generate as generator
from script.subvideo_generation._legacy.core import verification
from script.subvideo_generation.tests.test_generation_contract import (
    annotation, digest, encode, media, synthetic_project,
)


START = "<!-- unclamped-anchors:start -->"
END = "<!-- unclamped-anchors:end -->"


def anchor_document(path: Path, rows=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "# Test rules\n\n" + START + "\n"
    text += "| 视频 ID | 源视频帧号 | 源视频 SHA-256 |\n| --- | --- | --- |\n"
    text += "".join(f"| {video_id} | {frame} | {sha} |\n" for video_id, frame, sha in rows)
    path.write_text(text + END + "\n", encoding="utf-8")
    return path


def unclamped_row(video_id="video_0003"):
    return annotation(video_id, 断裂状态="未断裂", 断裂模式="无", 断裂位置="无",
                      异常_未夹紧="是", 断裂时间点="无", 断裂帧_前="无", 断裂帧_后="无")


def parsed_anchor(tmp_path, frame=300, sha="a" * 64):
    from script.subvideo_generation._legacy.core import anchors
    path = anchor_document(tmp_path / "rules.md", [("video_0003", frame, sha)])
    return anchors.load_anchors(path)["video_0003"]


def test_markdown_anchor_reads_explicit_source_frame_without_mutating_document(tmp_path):
    from script.subvideo_generation._legacy.core import anchors
    path = anchor_document(tmp_path / "rules.md", [("video_0003", 300, "a" * 64)])
    before = path.read_bytes()
    result = anchors.load_anchors(path)
    assert set(result) == {"video_0003"}
    assert result["video_0003"]["source_frame"] == 300
    assert type(result["video_0003"]["source_frame"]) is int
    assert result["video_0003"]["source_sha256"] == "a" * 64
    assert path.read_bytes() == before


@pytest.mark.parametrize("rows", [
    [("video_0003", 300, "a" * 64), ("video_0003", 301, "a" * 64)],
    [("video_0003", -1, "a" * 64)],
    [("video_0003", "300.5", "a" * 64)],
    [("video_0003", "true", "a" * 64)],
    [("../video_0003", 300, "a" * 64)],
    [("video_0003", 300, "not-a-content-hash")],
])
def test_markdown_anchor_rejects_ambiguous_or_unusable_records(tmp_path, rows):
    from script.subvideo_generation._legacy.core import anchors
    path = anchor_document(tmp_path / "rules.md", rows)
    with pytest.raises(anchors.AnchorError):
        anchors.load_anchors(path)


def test_unclamped_anchor_is_a_phenomenon_and_produces_five_centered_windows(tmp_path):
    row = unclamped_row()
    before = dict(row)
    record = generator.adapt_annotation(row, media(), phenomenon_anchor=parsed_anchor(tmp_path))
    assert record["event_kind"] == "unclamped"
    assert record["anchor_frames"] == [300]
    windows, _ = generator.plan_windows(record, media())
    assert len(windows) == 5
    assert {w["target_duration_seconds"] for w in windows} == {2.0, 3.0, 5.0, 10.0, 20.0}
    for w in windows:
        assert w["window_role"] == "unclamped"
        assert w["start_frame"] < 300 < w["end_frame"]
        assert w["start_time"] + w["end_time"] == pytest.approx(60.0)
        assert w["duration"] == pytest.approx(w["target_duration_seconds"])
    assert row == before
    labels = generator.candidate_labels(row, "unclamped")
    assert labels["断裂状态"] != "发生断裂"
    assert labels["断裂模式"] == labels["断裂位置"] == "无"
    assert labels["异常情况"]["未夹紧"] == "是"


def test_phenomenon_anchor_outside_source_cannot_be_planned(tmp_path):
    with pytest.raises(generator.PendingSource):
        generator.adapt_annotation(unclamped_row(), media(), phenomenon_anchor=parsed_anchor(tmp_path, 600))


def test_ordinary_annotation_cannot_be_reinterpreted_as_unclamped(tmp_path):
    try:
        record = generator.adapt_annotation(annotation(), media(), phenomenon_anchor=parsed_anchor(tmp_path))
    except generator.PendingSource:
        return
    windows, _ = generator.plan_windows(record, media())
    assert record["event_kind"] != "unclamped"
    assert not any(w["window_role"] == "unclamped" for w in windows)


@pytest.fixture
def synthetic_unclamped_project(synthetic_project):
    root = synthetic_project
    csv_path = root / "data/annotation-table-full.csv"
    with csv_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows, fields = list(reader), reader.fieldnames
    selected = next(row for row in rows if row["id"] == "video_0003")
    selected.update(unclamped_row())
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    raw = root / "data/videos/video_0003.mp4"
    anchor_document(root / "docs/subvideo-current-logic.md", [("video_0003", 30, digest(raw))])
    return root


def test_real_synthetic_unclamped_output_records_phenomenon_frame_and_review(synthetic_unclamped_project):
    root = synthetic_unclamped_project
    csv_path = root / "data/annotation-table-full.csv"
    before_csv = csv_path.read_bytes()
    result = generator.run(root, fold=0)
    clips = [c for c in result["candidates"] if c["source_video_id"] == "video_0003"]
    assert clips
    assert all(c["role"] == "unclamped" for c in clips)
    for c in clips:
        path = root / "data/sub_video" / c["output_path"]
        assert c["status"] == "cropped" and path.is_file()
        assert path.name.startswith("video_0003_unclamped_")
        assert c["event_kind"] == "unclamped" and c["source_anchor_frames"] == [30]
        assert c["candidate_labels"]["断裂状态"] != "发生断裂"
        assert c["candidate_labels"]["断裂模式"] == c["candidate_labels"]["断裂位置"] == "无"
        assert c["source_labels"]["异常情况"]["未夹紧"] == "是"
        assert c["final_labels"] is None and c["review"]["status"] == "未审核"
        proof = c["output"]["frame_preserving_replay"]
        assert proof["status"] == verification.VERIFIED
        assert digest(path) == c["output"]["sha256"]
        assert c["output"]["frame_mapping"]["anchors"] == [
            {"source_frame": 30, "roi_frame": 30, "output_frame": 30 - c["start_frame"]}
        ]
    assert csv_path.read_bytes() == before_csv
    persisted = json.loads((root / "data/sub_video/manifest.json").read_text())
    assert persisted == result
    assert {s["video_id"] for s in result["sources"]} == {"video_0003", "video_0004"}
    assert result["published"] is False


def test_source_content_pin_blocks_mismatched_phenomenon(synthetic_unclamped_project):
    root = synthetic_unclamped_project
    anchor_document(root / "docs/subvideo-current-logic.md", [("video_0003", 30, "0" * 64)])
    result = generator.run(root, fold=0, plan_only=True)
    source = next(s for s in result["sources"] if s["video_id"] == "video_0003")
    assert source["status"] == "pending"
    assert not any(c["source_video_id"] == "video_0003" for c in result["candidates"])


def test_resume_rejects_changed_phenomenon_document_before_writing(synthetic_unclamped_project):
    root = synthetic_unclamped_project
    generator.run(root, fold=0, plan_only=True)
    manifest_path = root / "data/sub_video/manifest.json"
    before = manifest_path.read_bytes()
    anchor_document(root / "docs/subvideo-current-logic.md", [
        ("video_0003", 31, digest(root / "data/videos/video_0003.mp4"))])
    with pytest.raises(generator.base.PilotError, match="identity|input|身份|输入"):
        generator.run(root, fold=0, plan_only=True, resume=True)
    assert manifest_path.read_bytes() == before


def test_real_wrong_frame_crop_is_rejected_for_unclamped_output(synthetic_unclamped_project, monkeypatch):
    real_command = generator.aligned.build_crop_command

    def shifted_command(source, output, candidate):
        return real_command(source, output, dict(candidate, start_frame=candidate["start_frame"] + 1,
                                                 end_frame=candidate["end_frame"] + 1))

    monkeypatch.setattr(generator.aligned, "build_crop_command", shifted_command)
    result = generator.run(synthetic_unclamped_project, fold=0)
    clips = [c for c in result["candidates"] if c["source_video_id"] == "video_0003"]
    assert clips and not any(c["status"] == "cropped" for c in clips)
    assert not list((synthetic_unclamped_project / "data/sub_video/videos").glob("video_0003_unclamped_*.mp4"))


def test_near_end_phenomenon_moves_full_windows_without_clipping_or_duplicates(tmp_path):
    description = media(count=194, fps=30)
    row = unclamped_row()
    record = generator.adapt_annotation(row, description, phenomenon_anchor=parsed_anchor(tmp_path, 174))
    windows, excluded = generator.plan_windows(record, description)
    assert len(windows) == 3
    assert {w["target_duration_seconds"] for w in windows} == {2.0, 3.0, 5.0}
    assert {w["target_duration_seconds"] for w in excluded} == {10.0, 20.0}
    assert all(w["end_frame"] == 194 and w["start_frame"] < 174 for w in windows)
    assert {w["start_frame"] for w in windows} == {134, 104, 44}
    assert all(w["duration"] == pytest.approx(w["target_duration_seconds"], abs=1e-6) for w in windows)
    assert all(w.get("reason") for w in excluded)


def test_tampered_phenomenon_frame_cannot_reuse_a_valid_source_proof(synthetic_unclamped_project):
    root = synthetic_unclamped_project
    result = generator.run(root, fold=0, plan_only=True)
    source = next(s for s in result["sources"] if s["video_id"] == "video_0003")
    candidate = dict(next(c for c in result["candidates"] if c["source_video_id"] == "video_0003"))
    candidate["source_anchor_frames"] = [31]
    destination = root / "data/sub_video/videos/tampered.mp4"
    with pytest.raises(verification.ReplayUncertain):
        generator.crop_video(root / source["roi_path"], destination, candidate,
                             source["roi_media"], source["frame_preserving_replay"])
    assert not destination.exists()


def test_nonuniform_source_pts_keep_the_same_phenomenon_frame(synthetic_unclamped_project, tmp_path):
    root = synthetic_unclamped_project
    source = root / "data/videos/video_0003.mp4"
    roi = root / "data/roi/videos/video_0003.mp4"
    replacement = tmp_path / "nonuniform.mp4"
    encode(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=10",
            "-frames:v", "60", "-vf", "settb=1/1000,setpts=N*100+mod(N\\,3)*4",
            "-vsync", "0", "-enc_time_base", "1/1000", "-threads", "1", "-c:v", "libx264",
            "-crf", "18", "-pix_fmt", "yuv420p", str(replacement)])
    source.write_bytes(replacement.read_bytes())
    roi.unlink()
    encode(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source),
            "-map", "0:v:0", "-vf", "crop=64:48:2:4,setsar=1", "-vsync", "0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-an", "-movflags", "+faststart", str(roi)])
    roi_manifest = root / "data/roi/manifest.json"
    metadata = json.loads(roi_manifest.read_text())
    record = next(r for r in metadata["videos"] if r["video_id"] == "video_0003")
    record["source"]["sha256"] = record["decision"]["source_sha256"] = digest(source)
    record["output"]["sha256"] = digest(roi)
    roi_manifest.write_text(json.dumps(metadata))
    anchor_document(root / "docs/subvideo-current-logic.md", [("video_0003", 30, digest(source))])
    measured = generator.aligned.probe_video(source)
    intervals = [round(b-a, 6) for a, b in zip(measured["timestamps"], measured["timestamps"][1:])]
    assert len(set(intervals)) > 1, "the fixture must exercise nonuniform decoded source PTS"
    result = generator.run(root, fold=0)
    clips = [c for c in result["candidates"] if c["source_video_id"] == "video_0003"]
    assert clips and all(c["status"] == "cropped" for c in clips)
    for candidate in clips:
        assert candidate["source_anchor_frames"] == [30]
        mapping = candidate["output"]["frame_mapping"]["anchors"]
        assert mapping == [{"source_frame": 30, "roi_frame": 30,
                            "output_frame": 30 - candidate["start_frame"]}]
        assert candidate["source_start_pts"] == pytest.approx(measured["timestamps"][candidate["start_frame"]])
        assert candidate["output"]["frame_preserving_replay"]["status"] == verification.VERIFIED


def test_live_document_change_invalidates_phenomenon_proof_before_encoding(synthetic_unclamped_project):
    root = synthetic_unclamped_project
    result = generator.run(root, fold=0, plan_only=True)
    source = next(s for s in result["sources"] if s["video_id"] == "video_0003")
    candidate = next(c for c in result["candidates"] if c["source_video_id"] == "video_0003")
    anchor_document(root / "docs/subvideo-current-logic.md", [
        ("video_0003", 31, digest(root / "data/videos/video_0003.mp4"))])
    output = root / "data/sub_video/videos/changed-document.mp4"
    with pytest.raises(verification.ReplayUncertain):
        generator.crop_video(root / source["roi_path"], output, candidate,
                             source["roi_media"], source["frame_preserving_replay"])
    assert not output.exists()


def test_duplicate_markdown_anchor_is_pending_and_cannot_fall_back_to_negative(synthetic_unclamped_project):
    root = synthetic_unclamped_project
    sha = digest(root / "data/videos/video_0003.mp4")
    anchor_document(root / "docs/subvideo-current-logic.md", [
        ("video_0003", 30, sha), ("video_0003", 31, sha)])
    result = generator.run(root, fold=0, plan_only=True)
    source = next(s for s in result["sources"] if s["video_id"] == "video_0003")
    assert source["status"] == "pending"
    assert not any(c["source_video_id"] == "video_0003" for c in result["candidates"])


@pytest.mark.parametrize("mutation_point", ["proof", "crop_return"])
def test_document_change_after_clip_proof_removes_new_clip_but_preserves_existing_files(
        synthetic_unclamped_project, monkeypatch, mutation_point):
    root = synthetic_unclamped_project
    generator.run(root, fold=0, plan_only=True)
    output_dir = root / "data/sub_video/videos"
    sentinel = output_dir / "user-existing.mp4"
    sentinel.write_bytes(b"previous independent file must survive")
    document = root / "docs/subvideo-current-logic.md"
    original = verification.verify_clip_replay if mutation_point == "proof" else generator.crop_video
    changed = False

    def change_after_verified(*args, **kwargs):
        nonlocal changed
        receipt = original(*args, **kwargs)
        if not changed:
            document.write_text(document.read_text() + "\nInput changed after clip verification.\n")
            changed = True
        return receipt

    if mutation_point == "proof":
        monkeypatch.setattr(verification, "verify_clip_replay", change_after_verified)
    else:
        monkeypatch.setattr(generator, "crop_video", change_after_verified)
    with pytest.raises(generator.base.PilotError, match="input|metadata|document|输入|文档"):
        generator.run(root, fold=0, resume=True)
    assert changed, "the injected mutation must actually occur after a real clip proof"
    assert not list(output_dir.glob("video_0003_unclamped_*.mp4"))
    assert sentinel.read_bytes() == b"previous independent file must survive"
