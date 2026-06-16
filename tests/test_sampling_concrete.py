from __future__ import annotations

import subprocess

import pytest

from agent.sampling import (
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


def test_ffmpeg_clip_builder_matches_frame_count(synthetic_video, tmp_path):
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
    assert clip_path.endswith(".mp4")
    probe = _probe_video(clip_path)
    # The clip contains exactly len(frames) frames played at video_fps.
    assert probe["total_frames"] == len(frames)
    assert probe["duration"] == pytest.approx(len(frames) / 4.0, abs=0.5)
