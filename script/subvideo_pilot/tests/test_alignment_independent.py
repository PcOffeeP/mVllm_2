"""Independent alignment and input-boundary oracles using synthetic data only.

The expected frame identity is fixed by construction.  No test reads project
media or infers its expected mapping using the production matcher.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from script.subvideo_pilot import aligned


def distinct_frames(count=12):
    """Deterministic per-frame texture makes a one-frame error observable."""
    rng = np.random.default_rng(4261)
    return rng.integers(20, 236, size=(count, 32, 40), dtype=np.uint8)


def test_lossy_pixel_changes_keep_the_known_frame_correspondence():
    expected = distinct_frames()
    # Small bounded coding error is deliberately not pixel/hash identity.
    noise = np.random.default_rng(735).integers(-2, 3, size=expected.shape)
    actual = (expected.astype(np.int16) + noise).astype(np.uint8)
    evidence = aligned.compare_sequences(expected, actual, [3, 4, 8])
    assert isinstance(evidence, dict)


@pytest.mark.parametrize("corruption", ["shift", "swap", "duplicate"])
def test_same_frame_count_does_not_hide_a_wrong_event_frame(corruption):
    expected = distinct_frames()
    actual = expected.copy()
    if corruption == "shift":
        actual = np.concatenate([expected[1:], expected[-1:]])
    elif corruption == "swap":
        actual[[4, 5]] = actual[[5, 4]]
    else:
        actual[4] = actual[3]
    assert len(expected) == len(actual)
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.compare_sequences(expected, actual, [3, 4, 5])


def test_static_frames_do_not_prove_a_unique_event_frame():
    static = np.full((9, 32, 40), 117, dtype=np.uint8)
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.compare_sequences(static, static.copy(), [4])


def test_repeated_adjacent_frame_is_ambiguous_even_at_zero_pixel_error():
    repeated = distinct_frames()
    repeated[5] = repeated[4]
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.compare_sequences(repeated, repeated.copy(), [4])


def test_distant_near_identical_frames_cannot_swap_and_keep_a_local_match():
    values = np.asarray([0, 220, 120, 50, 180, 100, 200, 90, 51, 140, 230, 30], dtype=np.uint8)
    expected = np.broadcast_to(values[:, None, None], (12, 16, 16)).copy()
    actual = expected.copy()
    actual[[3, 8]] = actual[[8, 3]]
    # Both wrong same-index pictures differ by only one grey level. Their exact
    # matches lie five frames away, outside a local +/- 2 search neighborhood.
    assert np.abs(expected.astype(np.int16) - actual.astype(np.int16)).max() == 1
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.compare_sequences(expected, actual, [3, 8])


def test_competing_distant_frame_within_codec_error_envelope_is_ambiguous():
    values = np.asarray([0, 220, 120, 50, 180, 100, 200, 90, 51, 140, 230, 30], dtype=np.uint8)
    expected = np.broadcast_to(values[:, None, None], (12, 16, 16)).copy()
    actual = expected.copy()
    actual[3] = 51  # A different source picture was moved into the anchor position.
    actual[8] = 52  # The anchor picture moved here, then acquired codec error +2.
    # For anchor 3, the incorrect same-index picture is numerically closer
    # (MAE 1) than the displaced original (MAE 2). Both are inside the accepted
    # codec-error envelope, so a fixed winner margin cannot prove identity.
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.compare_sequences(expected, actual, [3])


def test_h264_roundtrip_keeps_the_known_event_frame(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required for a synthetic lossy-codec check")
    # Broad textured regions retain clear identities after ordinary H.264
    # compression; white-noise pixels would test a codec-error threshold instead.
    tiles = np.random.default_rng(4261).integers(20, 236, size=(12, 4, 5), dtype=np.uint8)
    expected = tiles.repeat(8, axis=1).repeat(8, axis=2)
    media = tmp_path / "synthetic.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
        "-s", "40x32", "-r", "10", "-i", "pipe:0", "-an", "-threads", "1",
        "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", str(media),
    ], input=expected.tobytes(), check=True)
    decoded = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(media), "-f", "rawvideo",
        "-pix_fmt", "gray", "pipe:1",
    ])
    actual = np.frombuffer(decoded, dtype=np.uint8).reshape(expected.shape)
    assert not np.array_equal(expected, actual), "fixture must exercise lossy pixels"
    evidence = aligned.compare_sequences(expected, actual, [3, 4, 8])
    assert isinstance(evidence, dict)


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def held_only_project(tmp_path):
    root = tmp_path / "project"
    ids = ["video_0002", "video_0015", "video_0050"]
    split = root / "data/splits/three-fold"
    write_json(split / "test.json", {"video_ids": ["video_9999"]})
    for fold in range(3):
        write_json(split / f"fold_{fold}_val.json", {"video_ids": [ids[fold]]})
        write_json(split / f"fold_{fold}_train.json",
                   {"video_ids": [v for v in ids if v != ids[fold]]})
    table = root / "data/annotation-table-full.csv"
    with table.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "断裂状态"])
        writer.writeheader()
        # Even if they appeared ordinary, the explicit user hold takes priority.
        writer.writerows({"id": v, "断裂状态": "未断裂"} for v in ids)
        writer.writerow({"id": "video_9999", "断裂状态": "TEST_MUST_NOT_BE_INTERPRETED"})
    write_json(root / "data/roi/manifest.json", {
        "videos": [{"video_id": v, "status": "MEDIA_FIELDS_MUST_NOT_BE_ACCESSED"}
                   for v in ids + ["video_9999"]],
    })
    return root, ids


def test_special_videos_are_held_before_any_media_access(tmp_path, monkeypatch):
    root, ids = held_only_project(tmp_path)
    monkeypatch.setattr(aligned.shutil, "which", lambda _: "/synthetic/tool")
    real_sha = aligned.base.sha256_file

    def guarded_sha(path):
        assert Path(path).suffix.lower() != ".mp4", "held/test media was read"
        return real_sha(path)

    def forbidden_probe(*_args, **_kwargs):
        pytest.fail("held/test media was probed")

    monkeypatch.setattr(aligned.base, "sha256_file", guarded_sha)
    monkeypatch.setattr(aligned, "probe_video", forbidden_probe)
    result = aligned.run(root, tmp_path / "cuts", plan_only=True)
    assert {s["video_id"] for s in result["sources"]} == set(ids)
    assert all(s["status"] == "held" and
               s["reason"] == "special_video_reserved_for_later_discussion"
               for s in result["sources"])
    assert result["candidates"] == []
    assert not list((tmp_path / "cuts").rglob("*.mp4"))


def test_aligned_entry_refuses_to_replace_existing_results(tmp_path, monkeypatch):
    root, _ = held_only_project(tmp_path)
    monkeypatch.setattr(aligned.shutil, "which", lambda _: "/synthetic/tool")
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "manifest.json"
    marker.write_bytes(b"existing reviewed record")
    with pytest.raises(aligned.base.PilotError, match="output already exists"):
        aligned.run(root, output, plan_only=True)
    assert marker.read_bytes() == b"existing reviewed record"


def ffprobe_payload(times):
    return {
        "streams": [{"width": 40, "height": 32, "r_frame_rate": "30/1",
                     "duration": "0.142"}],
        "frames": [{"best_effort_timestamp_time": str(t), "pkt_duration_time": "0.04"}
                   for t in times],
    }


def test_monotonic_nonuniform_pts_is_not_rejected_as_a_cfr_grid_error(monkeypatch):
    payload = ffprobe_payload([100.0, 100.031, 100.071, 100.102])
    monkeypatch.setattr(aligned.base, "_checked",
                        lambda _cmd: SimpleNamespace(stdout=json.dumps(payload)))
    result = aligned.probe_video(Path("synthetic.mp4"))
    assert result["total_frames"] == 4
    assert result["timestamps"] == pytest.approx([0, .031, .071, .102])
    assert result["timestamp_origin"] == 100


@pytest.mark.parametrize("times", [
    [0, .033, .033, .1],  # Duplicate presentation instant.
    [0, .066, .033, .1],  # Frame presentation order goes backwards.
    [0, .033, float("nan"), .1],
])
def test_unusable_pts_still_requires_separate_handling(times, monkeypatch):
    payload = ffprobe_payload(times)
    monkeypatch.setattr(aligned.base, "_checked",
                        lambda _cmd: SimpleNamespace(stdout=json.dumps(payload)))
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.probe_video(Path("synthetic.mp4"))


def irregular_media(total=600, duration=None):
    # At each twentieth frame there is a 20 ms extra interval.  The sequence
    # is monotonic and visibly differs from seconds * nominal frame rate.
    times = [i / 10 + .02 * (i // 20) for i in range(total)]
    return {"width": 40, "height": 32, "fps": 10.0, "nominal_frame_rate": "10",
            "total_frames": total, "duration": times[-1] + .1 if duration is None else duration,
            "timestamps": times}


def fracture_row(**changes):
    return {"id": "video_0001", "断裂状态": "发生断裂", "断裂模式": "韧性断裂",
            "异常_未夹紧": "否", "异常_视频异常": "否", "异常_爆炸性断裂": "否",
            "断裂时间点": "30", "断裂帧_前": "299", "断裂帧_后": "300",
            "断裂时间范围_下界": "", "断裂时间范围_上界": "", "视频帧率": "10",
            **changes}


def range_row():
    return fracture_row(断裂时间点="", 断裂帧_前="无", 断裂帧_后="无",
                        断裂时间范围_下界="29", 断裂时间范围_上界="31")


def test_precise_event_uses_authoritative_frame_when_pts_differs_from_label_seconds():
    media = irregular_media()
    result = aligned.adapt_annotation(fracture_row(), media)
    assert result["event_kind"] == "exact"
    assert result["anchor_frames"] == [299, 300]
    assert result["event_frame"] == 300
    assert result["source_event_pts"] == pytest.approx(30.3)
    # The label's FPS-derived 30 seconds must not move the anchor to frame 297.
    assert media["timestamps"][300] != 30


def test_range_recovers_both_marked_frames_and_uses_actual_pts_for_guards():
    media = irregular_media()
    record = aligned.adapt_annotation(range_row(), media)
    assert record["event_kind"] == "range"
    assert record["anchor_frames"] == [290, 310]
    assert record["source_event_range_pts"] == pytest.approx([29.28, 31.3])
    accepted, _excluded = aligned.plan_windows(record, media)
    roles = {w["window_role"] for w in accepted}
    assert roles == {"pre_event", "transition", "post_event"}
    for window in accepted:
        start, end = window["start_frame"], window["end_frame"]
        assert window["source_frame_range"] == [start, end]
        if window["window_role"] == "pre_event":
            assert window["source_end_pts"] <= 28.78 + 1e-9
        elif window["window_role"] == "post_event":
            assert window["source_start_pts"] >= 31.8 - 1e-9
        else:
            assert start <= 290 and end > 310, "transition must contain the full marked range"


@pytest.mark.parametrize("duration, post_allowed", [(33.79, False), (33.8, True)])
def test_range_post_gate_measures_remaining_material_after_actual_upper_pts(duration, post_allowed):
    media = irregular_media(total=335, duration=duration)
    record = aligned.adapt_annotation(range_row(), media)
    accepted, excluded = aligned.plan_windows(record, media)
    # Upper marked frame is at 31.30 s. The first endpoint leaves 1.99 s after
    # its 0.5 s guard; the second leaves exactly the permitted 2.00 s.
    assert any(w["window_role"] == "post_event" for w in accepted) is post_allowed
    if not post_allowed:
        assert any(w["reason"] == "post_source_remaining_after_upper_guard_less_than_two_seconds"
                   for w in excluded)


def test_nonrecoverable_range_does_not_round_to_an_unverified_frame():
    with pytest.raises(aligned.AlignmentUncertain):
        aligned.adapt_annotation(range_row() | {"断裂时间范围_下界": "29.045"}, irregular_media())


def test_actual_irregular_pts_crop_keeps_the_annotated_frame_picture(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required for synthetic frame/PTS integration")
    tiles = np.random.default_rng(625).integers(20, 236, size=(24, 8, 8), dtype=np.uint8)
    pixels = tiles.repeat(8, axis=1).repeat(8, axis=2)
    source, output = tmp_path / "source.mp4", tmp_path / "cut.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray",
        "-s", "64x64", "-r", "10", "-i", "pipe:0", "-vf",
        "settb=1/1000,setpts=100*N+3*mod(N\\,3)", "-vsync", "0",
        "-enc_time_base", "1/1000", "-threads", "1", "-an", "-c:v", "libx264",
        "-crf", "18", "-pix_fmt", "yuv420p", str(source),
    ], input=pixels.tobytes(), check=True)

    def decoded_gray(path):
        raw = subprocess.check_output([
            "ffmpeg", "-v", "error", "-i", str(path), "-vsync", "0",
            "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
        ])
        return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 64, 64)

    source_frames = decoded_gray(source)
    media = aligned.probe_video(source)
    gaps = np.diff(media["timestamps"])
    assert gaps.max() - gaps.min() > .005, "fixture must retain nonuniform PTS"
    candidate = {"start_frame": 4, "end_frame": 20, "source_anchor_frames": [8, 9],
                 "roi_sha256": aligned.base.sha256_file(source)}
    result = aligned.crop_video(source, output, candidate, media, source_frames)
    output_frames = decoded_gray(output)
    assert len(output_frames) == 16
    assert result["frame_mapping"]["anchors"] == [
        {"source_frame": 8, "roi_frame": 8, "output_frame": 4},
        {"source_frame": 9, "roi_frame": 9, "output_frame": 5},
    ]
    # Independent whole-source MSE search confirms each known event picture,
    # rather than trusting the production frame_mapping field by itself.
    for source_index, output_index in [(8, 4), (9, 5)]:
        error = ((source_frames.astype(np.float64)
                  - output_frames[output_index].astype(np.float64)) ** 2).mean(axis=(1, 2))
        assert int(error.argmin()) == source_index
    expected_pts = np.asarray(media["timestamps"][4:20]) - media["timestamps"][4]
    assert result["media"]["timestamps"] == pytest.approx(expected_pts, abs=.001)
