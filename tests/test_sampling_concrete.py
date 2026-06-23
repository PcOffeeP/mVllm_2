from __future__ import annotations

import os
import subprocess

import pytest

from agent.sampling import (
    ClipBuildResult,
    FfmpegVideoClipBuilder,
    UniformVideoSampler,
    _effective_num_frames,
    _parse_fps,
    _probe_video,
    _uniform_timestamps,
)


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory):
    """Create a small 10s 30fps synthetic video via ffmpeg."""
    path = tmp_path_factory.mktemp("videos") / "synthetic_10s_30fps.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=size=320x240:rate=30:duration=10",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return str(path)


def test_probe_video(synthetic_video):
    probe = _probe_video(synthetic_video)
    assert probe["fps"] == pytest.approx(30.0, abs=0.1)
    assert probe["duration"] == pytest.approx(10.0, abs=0.2)
    assert probe["total_frames"] == pytest.approx(300, abs=5)


def test_uniform_timestamps():
    ts = _uniform_timestamps(0.0, 10.0, 5)
    assert ts == [0.0, 2.5, 5.0, 7.5, 10.0]


def test_parse_fps_fraction():
    assert _parse_fps("30000/1001") == pytest.approx(29.97, abs=0.01)


def test_effective_num_frames():
    # N = min(total_frames_in_clip, video_maxlen, floor(duration * video_fps))
    assert _effective_num_frames([0.0, 10.0], 8.0, 36, 300) == 36  # capped by video_maxlen
    assert _effective_num_frames([0.0, 100.0], 8.0, 36, 3000) == 36  # capped by video_maxlen
    assert _effective_num_frames([0.0, 10.0], 8.0, 100, 300) == 80  # capped by duration*fps
    assert _effective_num_frames([0.0, 0.1], 8.0, 36, 3) == 1


def test_uniform_video_sampler(synthetic_video, tmp_path):
    sampler = UniformVideoSampler(cache_dir=str(tmp_path / "frames"))
    frames = sampler.sample(
        video_path=synthetic_video,
        sample_range=[2.0, 4.0],
        num_frames=8,
        video_fps=4.0,
        strategy="uniform",
    )
    assert len(frames) == 8
    assert frames[0]["timestamp"] == pytest.approx(2.0, abs=0.01)
    assert frames[-1]["timestamp"] == pytest.approx(4.0, abs=0.01)
    for i, f in enumerate(frames):
        assert f["input_index"] == i
        assert f["original_frame"] == pytest.approx(round(f["timestamp"] * 30.0), abs=1)
        assert f["frame_path"]


def test_adaptive_strategy_falls_back_to_uniform(synthetic_video, tmp_path):
    sampler = UniformVideoSampler(cache_dir=str(tmp_path / "frames"))
    frames = sampler.sample(
        video_path=synthetic_video,
        sample_range=[1.0, 3.0],
        num_frames=4,
        video_fps=2.0,
        strategy="adaptive",
    )
    assert len(frames) == 4
    assert frames[0]["timestamp"] == pytest.approx(1.0, abs=0.01)
    assert frames[-1]["timestamp"] == pytest.approx(3.0, abs=0.01)


def test_ffmpeg_clip_builder_crops_continuously(synthetic_video, tmp_path):
    """The builder must crop a continuous segment, not pre-extract frames."""
    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    clip_path = builder.build(
        source_video=synthetic_video,
        sample_range=[2.0, 4.0],
        frames=[],  # frames are ignored in the new implementation
        video_fps=4.0,
        video_maxlen=8,
        sampling_strategy="uniform",
    )
    assert clip_path.endswith(".mp4")
    probe = _probe_video(clip_path)
    # The clip preserves the source time axis: 2 seconds at 30 fps = 60 frames.
    assert probe["total_frames"] == pytest.approx(60, abs=2)
    assert probe["duration"] == pytest.approx(2.0, abs=0.2)
    assert probe["fps"] == pytest.approx(30.0, abs=0.5)


def test_ffmpeg_clip_builder_with_manifest(synthetic_video, tmp_path):
    """build_with_manifest returns a ClipBuildResult with a valid frame manifest."""
    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    result = builder.build_with_manifest(
        source_video=synthetic_video,
        sample_range=[2.0, 4.0],
        video_fps=4.0,
        video_maxlen=8,
        sampling_strategy="uniform",
    )
    assert isinstance(result, ClipBuildResult)
    assert result.path.endswith(".mp4")
    assert os.path.exists(result.path)

    manifest = result.manifest
    # 2 seconds of 30 fps video -> 60 frames (allow tiny container variance).
    assert len(manifest) == pytest.approx(60, abs=2)
    assert manifest[0]["temp_index"] == 0
    assert manifest[0]["timestamp"] == pytest.approx(2.0, abs=0.02)
    assert manifest[0]["original_frame"] == pytest.approx(60, abs=1)
    assert manifest[-1]["timestamp"] < 4.0 + 0.1
    # Manifest indices must be contiguous and monotonic.
    for i, entry in enumerate(manifest):
        assert entry["temp_index"] == i
        assert entry["original_frame"] == pytest.approx(
            round(entry["timestamp"] * 30.0), abs=1
        )


def test_ffmpeg_clip_builder_ignores_legacy_frames(synthetic_video, tmp_path):
    """Legacy ``frames`` must not influence the continuous crop."""
    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    frames = [
        {"input_index": 0, "original_frame": 60, "timestamp": 2.0, "frame_path": "frame_0.jpg"},
        {"input_index": 1, "original_frame": 90, "timestamp": 3.0, "frame_path": "frame_1.jpg"},
        {"input_index": 2, "original_frame": 120, "timestamp": 4.0, "frame_path": "frame_2.jpg"},
    ]
    clip_path = builder.build(
        source_video=synthetic_video,
        sample_range=[2.0, 4.0],
        frames=frames,
        video_fps=4.0,
        video_maxlen=8,
        sampling_strategy="uniform",
    )
    probe = _probe_video(clip_path)
    # A 2-second continuous crop at 30 fps has ~60 frames, not 3.
    assert probe["total_frames"] == pytest.approx(60, abs=2)


@pytest.mark.parametrize(
    "sample_range, expected_substring",
    [
        ([5.0, 5.0], "0 <= start < end"),  # zero-length range
        ([-1.0, 3.0], "0 <= start"),  # negative start
        ([5.0, 15.0], "end <= video_duration"),  # end beyond video duration
        ([7.0, 3.0], "start < end"),  # inverted range
        ([1.0], "two-element list"),  # malformed range
    ],
)
def test_ffmpeg_clip_builder_rejects_invalid_sample_range(
    synthetic_video, tmp_path, sample_range, expected_substring
):
    """Degenerate or out-of-bounds sample_range must raise a clear ValueError."""
    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    with pytest.raises(ValueError, match=expected_substring):
        builder.build_with_manifest(
            source_video=synthetic_video,
            sample_range=sample_range,
            video_fps=4.0,
            video_maxlen=8,
        )
