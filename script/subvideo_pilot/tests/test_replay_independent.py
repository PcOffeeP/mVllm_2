"""Independent synthetic-media checks for restricted, exact pipeline replay."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from script.subvideo_pilot import aligned, replay


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(args):
    subprocess.run(args, check=True, capture_output=True)


def fixed_roi_command(source, output, video_filter="crop=64:48:2:4,setsar=1"):
    """Fixed old ROI encoding recipe, independently specified in this fixture."""
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
            "-i", str(source), "-map", "0:v:0", "-vf", video_filter, "-vsync", "0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-an", "-movflags", "+faststart", str(output)]


def roi_record(source, roi, video_filter="crop=64:48:2:4,setsar=1"):
    return {"video_id": "video_0001", "source": {"sha256": digest(source)},
            "decision": {"source_sha256": digest(source), "mode": "fixed_roi",
                         "source_resolution": [96, 64],
                         "pixel_box": {"x": 2, "y": 4, "width": 64, "height": 48}},
            "output": {"sha256": digest(roi),
                       "encoding": {"video_codec": "libx264", "preset": "fast", "crf": 23,
                                    "pixel_format": "yuv420p", "audio": "dropped",
                                    "frame_sync": "vsync_0_passthrough"},
                       "geometry": {"filter": video_filter,
                                    "geometry_status": "verified_from_filter_and_source_format",
                                    "output_resolution": [64, 48],
                                    "effective_pixel_box": {"x": 2, "y": 4, "width": 64, "height": 48},
                                    "pad_pixels": {"left": 0, "right": 0, "top": 0, "bottom": 0}}}}


@pytest.fixture
def source_pair(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required for synthetic exact-pipeline replay")
    # Only the version boundary is simulated on the Mac. All encodes, decodes,
    # frame/PTS comparisons and input hashes remain real.
    monkeypatch.setattr(replay, "_toolchain", lambda: {"ffmpeg": "synthetic-local-version-gate",
                                                     "ffprobe": "synthetic-local-version-gate"})
    source, roi = tmp_path / "source.mp4", tmp_path / "roi.mp4"
    command(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=10",
             "-t", "6", "-threads", "1", "-c:v", "libx264", "-crf", "18",
             "-pix_fmt", "yuv420p", str(source)])
    command(fixed_roi_command(source, roi))
    return source, roi, roi_record(source, roi)


def test_exact_source_replay_matches_a_fixed_spatial_pipeline(source_pair):
    source, roi, record = source_pair
    before = (source.read_bytes(), roi.read_bytes())
    proof = replay.verify_source_replay(source, roi, record)
    assert proof["status"] == "verified_frame_preserving_replay"
    assert proof["source_sha256"] == digest(source)
    assert proof["roi_sha256"] == digest(roi)
    assert (source.read_bytes(), roi.read_bytes()) == before


def test_exact_padding_replay_preserves_all_source_frames(source_pair, tmp_path):
    source, _roi, record = source_pair
    output = tmp_path / "padded.mp4"
    video_filter = "pad=96:128:0:32:color=black,setsar=1"
    command(fixed_roi_command(source, output, video_filter))
    record["decision"].update(mode="no_crop", pixel_box=None)
    record["output"]["sha256"] = digest(output)
    record["output"]["geometry"].update(
        filter=video_filter, output_resolution=[96, 128],
        effective_pixel_box={"x": 0, "y": 0, "width": 96, "height": 64},
        pad_pixels={"left": 0, "right": 0, "top": 32, "bottom": 32},
    )
    result = replay.verify_source_replay(source, output, record)
    assert result["status"] == replay.VERIFIED
    assert result["source_decode"]["frame_count"] == result["roi_decode"]["frame_count"] == 60


def test_effective_crop_must_follow_actual_chroma_rounding(source_pair, tmp_path):
    source, _roi, record = source_pair
    output = tmp_path / "odd-request.mp4"
    video_filter = "crop=64:48:3:4,setsar=1"
    command(fixed_roi_command(source, output, video_filter))
    record["decision"]["pixel_box"]["x"] = 3
    record["output"]["sha256"] = digest(output)
    record["output"]["geometry"]["filter"] = video_filter
    # yuv420p's non-exact crop rounds the actual x coordinate down to 2.
    assert replay.verify_source_replay(source, output, record)["status"] == replay.VERIFIED
    record["output"]["geometry"]["effective_pixel_box"]["x"] = 3
    with pytest.raises(replay.ReplayUncertain, match="effective_geometry_not_verified"):
        replay.verify_source_replay(source, output, record)


@pytest.mark.parametrize("extra_filter", ["fps=5", "reverse", "setpts=2*PTS", "tmix=frames=2"])
def test_source_proof_rejects_any_temporal_filter(source_pair, extra_filter):
    source, roi, record = source_pair
    record["output"]["geometry"]["filter"] = f"crop=64:48:2:4,{extra_filter},setsar=1"
    with pytest.raises(replay.ReplayUncertain):
        replay.verify_source_replay(source, roi, record)


def test_source_proof_rejects_a_changed_pinned_source(source_pair):
    source, roi, record = source_pair
    source.write_bytes(source.read_bytes() + b"changed-after-pin")
    with pytest.raises(replay.ReplayUncertain):
        replay.verify_source_replay(source, roi, record)


def test_source_proof_rejects_a_changed_pinned_roi(source_pair):
    source, roi, record = source_pair
    roi.write_bytes(roi.read_bytes() + b"changed-after-pin")
    with pytest.raises(replay.ReplayUncertain):
        replay.verify_source_replay(source, roi, record)


def test_source_change_during_reference_encode_invalidates_the_receipt(source_pair, monkeypatch):
    source, roi, record = source_pair
    original_checked = replay._checked

    def checked_then_changed(command_args):
        result = original_checked(command_args)
        if "-vf" in command_args and command_args[command_args.index("-i") + 1] == str(source.resolve()):
            source.write_bytes(source.read_bytes() + b"changed-during-replay")
        return result

    monkeypatch.setattr(replay, "_checked", checked_then_changed)
    with pytest.raises(replay.ReplayUncertain, match="identity_changed_during_check"):
        replay.verify_source_replay(source, roi, record)


def test_matching_record_sha_cannot_hide_reversed_video(source_pair, tmp_path):
    source, _roi, record = source_pair
    reversed_roi = tmp_path / "reversed.mp4"
    command(fixed_roi_command(source, reversed_roi, "crop=64:48:2:4,reverse,setsar=1"))
    record["output"]["sha256"] = digest(reversed_roi)
    with pytest.raises(replay.ReplayUncertain):
        replay.verify_source_replay(source, reversed_roi, record)


def test_matching_record_sha_cannot_hide_retimed_video(source_pair, tmp_path):
    source, _roi, record = source_pair
    retimed_roi = tmp_path / "retimed.mp4"
    command(fixed_roi_command(source, retimed_roi, "crop=64:48:2:4,setpts=2*PTS,setsar=1"))
    record["output"]["sha256"] = digest(retimed_roi)
    with pytest.raises(replay.ReplayUncertain):
        replay.verify_source_replay(source, retimed_roi, record)


def test_multiple_video_streams_are_not_silently_reduced_to_first(source_pair, tmp_path):
    source, _roi, _record = source_pair
    multi = tmp_path / "multi.mp4"
    roi = tmp_path / "multi-roi.mp4"
    command(["ffmpeg", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:v:0",
             "-c", "copy", str(multi)])
    command(fixed_roi_command(multi, roi))
    with pytest.raises(replay.ReplayUncertain):
        replay.verify_source_replay(multi, roi, roi_record(multi, roi))


@pytest.mark.parametrize("unsupported_tool", ["ffmpeg", "ffprobe"])
def test_real_toolchain_gate_rejects_an_unverified_version(unsupported_tool, monkeypatch):
    monkeypatch.setattr(replay.shutil, "which", lambda name: f"/synthetic/tools/{name}")
    monkeypatch.setattr(replay.base, "sha256_file", lambda _path: "synthetic-binary-sha")

    def version(command, **_kwargs):
        name = Path(command[0]).name
        value = "8.1.1" if name == unsupported_tool else "4.4.2"
        return SimpleNamespace(returncode=0, stdout=f"{name} version {value}\n", stderr="")

    monkeypatch.setattr(replay.subprocess, "run", version)
    with pytest.raises(replay.ReplayUncertain, match="requires_verified_ffmpeg_ffprobe_4_4_2"):
        replay._toolchain()


@pytest.mark.parametrize("duration_field", ["pkt_duration_time", "duration_time"])
def test_alignment_probe_keeps_the_decoded_last_frame_duration_across_ffprobe_versions(duration_field, monkeypatch):
    payload = {"streams": [{"width": 64, "height": 48, "r_frame_rate": "10/1",
                            "duration": ".4", "time_base": "1/1000"}],
               "frames": [{"best_effort_timestamp_time": str(i / 10), duration_field: ".1"}
                          for i in range(4)]}

    def probe(command_args):
        fields = command_args[command_args.index("-show_entries") + 1]
        frame_fields = next(part.split("=", 1)[1].split(",") for part in fields.split(":")
                            if part.startswith("frame="))
        assert duration_field in frame_fields
        return SimpleNamespace(stdout=json.dumps(payload))

    monkeypatch.setattr(aligned.base, "_checked", probe)
    result = aligned.probe_video(Path("synthetic.mp4"))
    assert result["total_frames"] == 4
    assert result["duration"] == pytest.approx(.4)


def annotation(*, event_frame=30, range_frames=None):
    row = {"id": "video_0001", "断裂状态": "发生断裂", "断裂模式": "脆性断裂",
           "异常_未夹紧": "否", "异常_视频异常": "否", "异常_爆炸性断裂": "否",
           "视频帧率": "10", "断裂时间点": str(event_frame / 10),
           "断裂帧_前": str(event_frame - 1), "断裂帧_后": str(event_frame),
           "断裂时间范围_下界": "", "断裂时间范围_上界": ""}
    if range_frames:
        row.update(断裂时间点="", 断裂帧_前="无", 断裂帧_后="无",
                   断裂时间范围_下界=str(range_frames[0] / 10),
                   断裂时间范围_上界=str(range_frames[1] / 10))
    return row


def candidate(source, roi, start=20, end=40, *, anchors=(29, 30), kind="exact", role="transition"):
    return {"source_video_id": "video_0001", "source_sha256": digest(source), "roi_sha256": digest(roi),
            "start_frame": start, "end_frame": end, "source_frame_range": [start, end],
            "source_anchor_frames": list(anchors), "event_kind": kind, "window_role": role}


def actual_trim(roi, output, clip):
    # This is the primary output under test. Replay must independently select
    # absolute frames, rather than asking this same trim function for evidence.
    command(aligned.build_crop_command(roi, output, clip))


def test_clip_replay_independently_selects_the_annotated_frames(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record, source_annotation=annotation())
    clip = candidate(source, roi)
    output = tmp_path / "cut.mp4"
    actual_trim(roi, output, clip)
    result = replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)
    assert result["status"] == "verified_frame_preserving_replay"
    assert result["decoded_frame_count"] == 20
    assert result["anchors"] == [
        {"source_frame": 29, "roi_frame": 29, "output_frame": 9},
        {"source_frame": 30, "roi_frame": 30, "output_frame": 10},
    ]
    assert "select=between" in result["command"][result["command"].index("-vf") + 1]
    assert result["output_sha256"] == digest(output)
    assert "not_human_review" in result["limitations"]


def test_same_count_one_frame_shift_cannot_pass_clip_replay(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record, source_annotation=annotation())
    claimed = candidate(source, roi)
    output = tmp_path / "shifted.mp4"
    actual_trim(roi, output, claimed | {"start_frame": 21, "end_frame": 41})
    before = output.read_bytes()
    with pytest.raises(replay.ReplayUncertain):
        replay.verify_clip_replay(roi, output, claimed, {"width": 64, "height": 48}, proof)
    assert output.read_bytes() == before


def test_range_clip_must_cover_the_entire_recorded_range(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record,
                                        source_annotation=annotation(range_frames=(28, 32)))
    clip = candidate(source, roi, start=20, end=31, anchors=(28, 32), kind="range")
    output = tmp_path / "incomplete-range.mp4"
    actual_trim(roi, output, clip)
    with pytest.raises(replay.ReplayUncertain, match="transition_does_not_cover_annotation_bounds"):
        replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)


def test_complete_range_clip_has_both_source_anchor_mappings(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record,
                                        source_annotation=annotation(range_frames=(28, 32)))
    clip = candidate(source, roi, start=20, end=40, anchors=(28, 32), kind="range")
    output = tmp_path / "complete-range.mp4"
    actual_trim(roi, output, clip)
    result = replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)
    assert result["status"] == replay.VERIFIED
    assert result["window"]["event_kind"] == "range"
    assert result["anchors"] == [
        {"source_frame": 28, "roi_frame": 28, "output_frame": 8},
        {"source_frame": 32, "roi_frame": 32, "output_frame": 12},
    ]


@pytest.mark.parametrize("start,end,role", [(0, 24, "pre_event"), (35, 60, "post_event")])
def test_range_protection_intervals_are_checked_independently(source_pair, tmp_path, start, end, role):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record,
                                        source_annotation=annotation(range_frames=(28, 32)))
    clip = candidate(source, roi, start=start, end=end, anchors=(28, 32), kind="range", role=role)
    output = tmp_path / f"crossed-{role}.mp4"
    actual_trim(roi, output, clip)
    with pytest.raises(replay.ReplayUncertain, match="guard"):
        replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)


def test_wrong_recorded_anchor_cannot_be_certified_by_correct_media(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record, source_annotation=annotation())
    clip = candidate(source, roi, anchors=(28, 29))
    output = tmp_path / "wrong-record.mp4"
    actual_trim(roi, output, clip)
    with pytest.raises(replay.ReplayUncertain, match="recorded_frame_binding_mismatch"):
        replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)


@pytest.mark.parametrize("field,wrong_value", [
    ("source_start_pts", 2.1), ("source_end_pts", 4.1), ("source_duration", 1.9),
    ("start_time", 2.1), ("end_time", 4.1), ("duration", 1.9),
])
def test_correct_frame_numbers_cannot_hide_wrong_recorded_seconds(source_pair, tmp_path, field, wrong_value):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record, source_annotation=annotation())
    clip = candidate(source, roi) | {field: wrong_value}
    output = tmp_path / "wrong-time-mapping.mp4"
    actual_trim(roi, output, clip)
    with pytest.raises(replay.ReplayUncertain, match="recorded_source_time_mapping_mismatch"):
        replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)


def test_post_clip_cannot_use_insufficient_material_after_guard(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record,
                                        source_annotation=annotation(event_frame=40))
    clip = candidate(source, roi, start=45, end=60, anchors=(39, 40), role="post_event")
    output = tmp_path / "short-post.mp4"
    actual_trim(roi, output, clip)
    with pytest.raises(replay.ReplayUncertain, match="post_guard_or_remaining_material_failed"):
        replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)


def test_post_clip_with_exactly_two_seconds_after_guard_can_be_proven(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record,
                                        source_annotation=annotation(event_frame=35))
    clip = candidate(source, roi, start=40, end=60, anchors=(34, 35), role="post_event")
    output = tmp_path / "exactly-two.mp4"
    actual_trim(roi, output, clip)
    result = replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)
    assert result["status"] == replay.VERIFIED
    assert result["decoded_frame_count"] == 20


def test_existing_one_second_minimum_is_not_silently_changed_to_two(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record, source_annotation=annotation())
    clip = candidate(source, roi, start=25, end=40)
    output = tmp_path / "one-and-half.mp4"
    actual_trim(roi, output, clip)
    result = replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)
    assert result["status"] == replay.VERIFIED
    assert result["decoded_frame_count"] == 15


def test_missing_source_proof_cannot_fall_back_to_clear_picture_match(source_pair, tmp_path):
    source, roi, _record = source_pair
    output = tmp_path / "missing-proof.mp4"
    clip = candidate(source, roi)
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.crop_video(roi, output, clip, aligned.probe_video(roi), aligned._features(roi), source_proof=None)
    assert not output.exists()


def test_failed_clip_proof_cannot_publish_even_a_clear_picture_match(source_pair, tmp_path, monkeypatch):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record, source_annotation=annotation())
    output = tmp_path / "must-not-publish.mp4"

    def refuse_proof(*_args, **_kwargs):
        raise replay.ReplayUncertain("synthetic_independent_select_proof_failed")

    monkeypatch.setattr(replay, "verify_clip_replay", refuse_proof)
    with pytest.raises(aligned.AlignmentUncertain, match="replay_unverified"):
        aligned.crop_video(roi, output, candidate(source, roi), aligned.probe_video(roi),
                           aligned._features(roi), source_proof=proof)
    assert not output.exists()
    assert not list(tmp_path.glob(".aligned-cut-*.mp4"))


def test_failed_source_replay_cannot_plan_candidates_using_picture_similarity(source_pair, tmp_path, monkeypatch):
    source, roi, record = source_pair
    root = tmp_path / "project"
    raw_path = root / "data/videos/video_0001.mp4"
    roi_path = root / "data/roi/videos/video_0001.mp4"
    raw_path.parent.mkdir(parents=True)
    roi_path.parent.mkdir(parents=True)
    shutil.copyfile(source, raw_path)
    shutil.copyfile(roi, roi_path)
    monkeypatch.setattr(aligned.base, "load_inputs", lambda _root: (
        {"video_0001": annotation()}, {"video_0001": record | {"status": "success"}},
        {"video_0001": {"0": "train", "1": "val", "2": "train"}}, {},
    ))
    clear_frames = np.random.default_rng(22).integers(0, 256, (60, 64, 64), dtype="uint8")
    monkeypatch.setattr(aligned, "_features", lambda *_args, **_kwargs: clear_frames)

    def refuse_proof(*_args, **_kwargs):
        raise replay.ReplayUncertain("synthetic_strict_source_proof_failed")

    monkeypatch.setattr(replay, "verify_source_replay", refuse_proof)
    result = aligned.run(root, tmp_path / "planned", plan_only=True)
    assert result["sources"][0]["status"] == "pending"
    assert result["candidates"] == []


def test_successful_run_persists_both_proofs_without_claiming_review_or_release(source_pair, tmp_path, monkeypatch):
    source, roi, record = source_pair
    root = tmp_path / "project"
    raw_path = root / "data/videos/video_0001.mp4"
    roi_path = root / "data/roi/videos/video_0001.mp4"
    raw_path.parent.mkdir(parents=True)
    roi_path.parent.mkdir(parents=True)
    shutil.copyfile(source, raw_path)
    shutil.copyfile(roi, roi_path)
    monkeypatch.setattr(aligned.base, "load_inputs", lambda _root: (
        {"video_0001": annotation()}, {"video_0001": record | {"status": "success"}},
        {"video_0001": {"0": "train", "1": "val", "2": "train"}}, {},
    ))
    output = tmp_path / "proven-cuts"
    result = aligned.run(root, output)
    persisted = json.loads((output / "manifest.json").read_text())
    assert result["complete"] and persisted["complete"]
    source_receipt = persisted["sources"][0]["frame_preserving_replay"]
    assert source_receipt["status"] == replay.VERIFIED
    assert source_receipt["receipt_sha256"] == result["sources"][0]["frame_preserving_replay"]["receipt_sha256"]
    assert persisted["candidates"]
    for clip in persisted["candidates"]:
        assert clip["status"] == "cropped"
        assert clip["output"]["frame_preserving_replay"]["status"] == replay.VERIFIED
        assert clip["output"]["frame_preserving_replay"]["source_receipt_sha256"] == source_receipt["receipt_sha256"]
        assert clip["manual_review"] == "required" and clip["labels_status"] == "unassigned"
    assert persisted["published"] is False


def test_static_pictures_can_pass_only_the_exact_replayed_pipeline(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required for synthetic strict replay")
    monkeypatch.setattr(replay, "_toolchain", lambda: {"ffmpeg": "synthetic-local-version-gate",
                                                     "ffprobe": "synthetic-local-version-gate"})
    source, roi, output = tmp_path / "static.mp4", tmp_path / "static-roi.mp4", tmp_path / "cut.mp4"
    command(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=gray:size=96x64:rate=10",
             "-t", "6", "-threads", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)])
    command(fixed_roi_command(source, roi))
    record = roi_record(source, roi)
    proof = replay.verify_source_replay(source, roi, record, source_annotation=annotation())
    features = aligned._features(roi)
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.compare_sequences(features, features, [29, 30])
    result = aligned.crop_video(roi, output, candidate(source, roi), aligned.probe_video(roi),
                                features, source_proof=proof)
    assert result["frame_preserving_replay"]["status"] == replay.VERIFIED
    assert result["picture_correspondence"]["status"] == "pending"
    assert result["frame_mapping"]["anchors"] == [
        {"source_frame": 29, "roi_frame": 29, "output_frame": 9},
        {"source_frame": 30, "roi_frame": 30, "output_frame": 10},
    ]
    assert "not_human_review" in result["frame_preserving_replay"]["limitations"]
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        aligned.crop_video(roi, output, candidate(source, roi), aligned.probe_video(roi),
                           features, source_proof=proof)
    assert output.read_bytes() == before


@pytest.mark.parametrize("corruption", ["frame_hash", "pts"])
def test_exact_file_match_also_requires_complete_decoded_frame_evidence(source_pair, monkeypatch, corruption):
    source, roi, record = source_pair
    original_decode = replay._decode_rgb

    def inconsistent_decode(path, info):
        evidence = original_decode(path, info)
        if Path(path).name == "reference.mp4":
            evidence = deepcopy(evidence)
            if corruption == "frame_hash":
                evidence["frames"][20]["sha256"] = "0" * 64
            else:
                evidence["frames"][20]["pts"] += 1
        return evidence

    monkeypatch.setattr(replay, "_decode_rgb", inconsistent_decode)
    with pytest.raises(replay.ReplayUncertain, match="full_RGB_PTS_sequence_mismatch"):
        replay.verify_source_replay(source, roi, record)


def test_source_receipt_without_bound_current_annotation_cannot_certify_clip(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record)
    clip = candidate(source, roi)
    output = tmp_path / "unbound.mp4"
    actual_trim(roi, output, clip)
    with pytest.raises(replay.ReplayUncertain, match="bound_current_annotation"):
        replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)


def test_tampering_with_source_receipt_invalidates_clip_proof(source_pair, tmp_path):
    source, roi, record = source_pair
    proof = replay.verify_source_replay(source, roi, record, source_annotation=annotation())
    proof["source_annotation"]["断裂帧_后"] = "31"
    clip = candidate(source, roi)
    output = tmp_path / "tampered.mp4"
    actual_trim(roi, output, clip)
    with pytest.raises(replay.ReplayUncertain, match="source_receipt_not_current_or_complete"):
        replay.verify_clip_replay(roi, output, clip, {"width": 64, "height": 48}, proof)


@pytest.mark.parametrize("video_id", ["video_0002", "video_0015", "video_0050"])
def test_replay_held_ids_are_rejected_before_any_media_read(video_id, tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("held source replay attempted media access")

    monkeypatch.setattr(replay.base, "sha256_file", forbidden)
    monkeypatch.setattr(replay, "_toolchain", forbidden)
    with pytest.raises(replay.ReplayUncertain, match="special_video_reserved"):
        replay.verify_source_replay(tmp_path / "missing-source", tmp_path / "missing-roi", {"video_id": video_id})
