from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.preprocessing import (
    FrameMapping,
    MiniCPMVideoPreprocessor,
    MockVideoPreprocessor,
    ProcessorInfo,
    VideoPreprocessor,
)


def _make_test_video(path: Path, duration: float, fps: float = 30.0) -> None:
    """生成纯色测试视频，时长和帧率固定。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s=64x64:d={duration}:r={fps}",
        "-pix_fmt", "yuv420p",
        "-an",
        str(path),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


@pytest.fixture
def short_video(tmp_path: Path) -> Path:
    video = tmp_path / "short_5s_30fps.mp4"
    _make_test_video(video, duration=5.0, fps=30.0)
    return video


@pytest.fixture
def long_video(tmp_path: Path) -> Path:
    video = tmp_path / "long_35s_30fps.mp4"
    _make_test_video(video, duration=35.0, fps=30.0)
    return video


# ---------------------------------------------------------------------------
# 抽象类接口
# ---------------------------------------------------------------------------


def test_video_preprocessor_is_abstract():
    """VideoPreprocessor 不能直接实例化，必须实现抽象方法。"""
    with pytest.raises(TypeError):
        VideoPreprocessor()


def test_video_preprocessor_interface_shape():
    """确认抽象类声明的接口方法存在且签名正确。"""
    required_methods = {"get_info", "healthcheck", "sample", "fingerprint"}
    assert required_methods.issubset({m for m in dir(VideoPreprocessor) if not m.startswith("_")})


# ---------------------------------------------------------------------------
# mock 预处理器
# ---------------------------------------------------------------------------


def test_mock_healthcheck_passes_when_ffmpeg_available():
    preprocessor = MockVideoPreprocessor()
    ok = preprocessor.healthcheck()
    # 当前 CI/本地 ffmpeg 通常可用；如不可用，测试显式失败以提示环境。
    assert ok is True


def test_mock_info_fields():
    info = MockVideoPreprocessor().get_info()
    assert info.name == "mock-ffmpeg-uniform"
    assert info.max_frames == 8
    assert info.backend == "ffmpeg"
    assert isinstance(info.version, str)


def test_mock_sample_outputs_at_most_eight_frames(short_video: Path):
    preprocessor = MockVideoPreprocessor()
    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    assert len(frames) <= 8
    assert all(isinstance(f, FrameMapping) for f in frames)


def test_mock_sample_outputs_monotonic_frames_and_timestamps(short_video: Path):
    preprocessor = MockVideoPreprocessor()
    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    original_frames = [f.original_frame for f in frames]
    timestamps = [f.timestamp for f in frames]
    assert original_frames == sorted(original_frames)
    assert timestamps == sorted(timestamps)
    assert len(set(original_frames)) == len(original_frames)


def test_mock_sample_input_index_is_sequential(short_video: Path):
    frames = MockVideoPreprocessor().sample(str(short_video), start_time=0.0, end_time=5.0)
    assert [f.input_index for f in frames] == list(range(len(frames)))


@pytest.mark.parametrize(
    ("start", "end", "expected_max"),
    [
        (0.0, 1.0, 8),  # 1s 区间帧数 >= 8，应取 8 帧
        (0.0, 3.0, 8),  # 3s 区间
        (0.0, 10.0, 8),  # 10s 区间
        (0.0, 30.0, 8),  # 30s 区间
    ],
)
def test_mock_sample_short_intervals_up_to_eight_frames(
    long_video: Path, start: float, end: float, expected_max: int
):
    frames = MockVideoPreprocessor().sample(str(long_video), start_time=start, end_time=end)
    assert len(frames) <= expected_max
    if (end - start) >= 8 / 30.0:
        assert len(frames) == expected_max


def test_mock_sample_full_video(long_video: Path):
    frames = MockVideoPreprocessor().sample(str(long_video), start_time=0.0, end_time=35.0)
    assert len(frames) == 8
    assert frames[0].original_frame == 0
    assert frames[-1].original_frame >= 30 * 35 - 2  # 允许 ±1 帧舍入


def test_mock_sample_very_short_interval_returns_fewer_than_eight(short_video: Path):
    # 0.1s 区间约 3 帧，应返回 <=3 帧
    frames = MockVideoPreprocessor().sample(str(short_video), start_time=1.0, end_time=1.1)
    assert 1 <= len(frames) <= 3


def test_mock_sample_invalid_interval_raises(short_video: Path):
    preprocessor = MockVideoPreprocessor()
    with pytest.raises(ValueError):
        preprocessor.sample(str(short_video), start_time=2.0, end_time=2.0)
    with pytest.raises(ValueError):
        preprocessor.sample(str(short_video), start_time=-1.0, end_time=2.0)


def test_mock_fingerprint_is_nonempty():
    fp = MockVideoPreprocessor().fingerprint()
    assert isinstance(fp, str) and fp
    assert "mock-ffmpeg-uniform" in fp


# ---------------------------------------------------------------------------
# minicpm 模板接口
# ---------------------------------------------------------------------------


def test_minicpm_info_fields():
    preprocessor = MiniCPMVideoPreprocessor(model_path_or_name="openbmb/MiniCPM-V-2_6")
    info = preprocessor.get_info()
    assert isinstance(info, ProcessorInfo)
    assert info.name == "minicpm-v-4.6"
    assert info.max_frames == 8


def test_minicpm_healthcheck_requires_max_frames_eight():
    ok_default = MiniCPMVideoPreprocessor("test").healthcheck()
    ok_wrong = MiniCPMVideoPreprocessor("test", max_frames=16).healthcheck()
    assert isinstance(ok_default, bool)
    # 本地无 transformers 时 ok_default 为 False；训练机为 True。
    # 关键校验：max_frames 不为 8 时必须失败。
    assert ok_wrong is False


def test_minicpm_sample_at_most_eight_frames(short_video: Path):
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    assert len(frames) <= 8
    assert all(isinstance(f, FrameMapping) for f in frames)


def test_minicpm_sample_monotonic_frames_and_timestamps(short_video: Path):
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    original_frames = [f.original_frame for f in frames]
    timestamps = [f.timestamp for f in frames]
    assert original_frames == sorted(original_frames)
    assert timestamps == sorted(timestamps)
    assert len(set(original_frames)) == len(original_frames)


def test_minicpm_sample_input_index_is_sequential(short_video: Path):
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    assert [f.input_index for f in frames] == list(range(len(frames)))


def test_minicpm_sample_full_video_returns_eight_frames(long_video: Path):
    """35s @ 30fps 应均匀取 8 帧。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(long_video), start_time=0.0, end_time=35.0)
    assert len(frames) == 8
    assert frames[0].original_frame == 0
    assert frames[-1].original_frame >= 30 * 35 - 2  # 接近最后一帧


def test_minicpm_sample_short_interval_returns_fewer_than_eight(short_video: Path):
    """0.1s 区间约 3 帧，应返回 <=3 帧。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(short_video), start_time=1.0, end_time=1.1)
    assert 1 <= len(frames) <= 3


def test_minicpm_sample_clamps_negative_start_time(short_video: Path):
    """start_time < 0 应截断为 0，不抛异常。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(short_video), start_time=-1.0, end_time=2.0)
    assert len(frames) <= 8
    assert frames[0].timestamp >= 0.0


def test_minicpm_sample_clamps_end_time_exceeding_duration(short_video: Path):
    """end_time > duration 应截断为 duration。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=999.0)
    assert len(frames) <= 8
    assert frames[-1].timestamp <= 5.0


def test_minicpm_sample_empty_interval_returns_empty(short_video: Path):
    """end_time <= start_time 应返回空列表。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(short_video), start_time=2.0, end_time=2.0)
    assert frames == []
    frames2 = preprocessor.sample(str(short_video), start_time=3.0, end_time=2.0)
    assert frames2 == []


def test_minicpm_fingerprint_is_stable():
    p1 = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    p2 = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    assert p1.fingerprint() == p2.fingerprint()


# ---------------------------------------------------------------------------
# minicpm processor 集成路径（mock）
# ---------------------------------------------------------------------------


def test_minicpm_processor_get_info_class_name():
    """processor 已加载时 get_info().version 返回 processor 类名。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    # 直接设置处理器已加载状态
    preprocessor._processor_loaded = True
    preprocessor._processor = object()  # 任意对象
    preprocessor._video_processor = object()

    info = preprocessor.get_info()
    assert info.version == type(preprocessor._processor).__name__
    assert info.backend == "transformers"


def test_minicpm_processor_sample_calls_video_processor(short_video: Path):
    """processor 路径下 sample() 调用 video_processor 并根据输出帧数返回。"""
    from unittest.mock import MagicMock

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    mock_vp = MagicMock()
    mock_vp.return_value = {"pixel_values_videos": MagicMock()}
    mock_vp.return_value["pixel_values_videos"].shape = (4, 3, 224, 224)

    preprocessor._video_processor = mock_vp
    preprocessor._processor = MagicMock()
    preprocessor._processor_loaded = True

    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)

    # video_processor 应被调用
    mock_vp.assert_called_once()
    _, kwargs = mock_vp.call_args
    assert kwargs.get("return_tensors") == "pt"

    # 应返回 4 帧（匹配 pixel_values_videos.shape[0]）
    assert len(frames) == 4
    assert all(isinstance(f, FrameMapping) for f in frames)


def test_minicpm_processor_sample_fallback_on_processor_error(short_video: Path):
    """processor 调用异常时优雅 fallback 到 pyav 计算。"""
    from unittest.mock import MagicMock

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    mock_vp = MagicMock(side_effect=RuntimeError("Mock processor error"))

    preprocessor._video_processor = mock_vp
    preprocessor._processor = MagicMock()
    preprocessor._processor_loaded = True

    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    assert 1 <= len(frames) <= 8


def test_minicpm_processor_sample_fallback_on_missing_pixel_values(short_video: Path):
    """video_processor 输出不含 pixel_values_videos 时 fallback。"""
    from unittest.mock import MagicMock

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    mock_vp = MagicMock()
    mock_vp.return_value = {"some_other_key": "data"}

    preprocessor._video_processor = mock_vp
    preprocessor._processor = MagicMock()
    preprocessor._processor_loaded = True

    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    assert 1 <= len(frames) <= 8


def test_minicpm_processor_sample_decoded_frames_passed_to_processor(short_video: Path):
    """video_processor 接收到的帧列表是解码后的 RGB 图像（PIL Image 或 ndarray）。"""
    import numpy as np
    from unittest.mock import MagicMock

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    mock_vp = MagicMock()
    mock_vp.return_value = {"pixel_values_videos": MagicMock()}
    mock_vp.return_value["pixel_values_videos"].shape = (4, 3, 224, 224)

    preprocessor._video_processor = mock_vp
    preprocessor._processor = MagicMock()
    preprocessor._processor_loaded = True

    preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)

    args, _ = mock_vp.call_args
    assert len(args) >= 1
    passed_videos = args[0]
    assert isinstance(passed_videos, list)
    assert len(passed_videos) == 1  # 单个视频
    # 内部应为 PIL Image 或 ndarray（取决于 Pillow 是否可用）
    for f in passed_videos[0]:
        if hasattr(f, "mode"):  # PIL Image
            assert f.mode == "RGB"
        else:  # ndarray
            assert isinstance(f, np.ndarray)
            assert f.shape[-1] == 3
            assert f.dtype == np.uint8


def test_minicpm_processor_get_info_fallback_when_not_loaded():
    """processor 未加载时 get_info() 使用 model_path 作为 version。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    assert preprocessor._processor_loaded is False

    info = preprocessor.get_info()
    assert info.version == "openbmb/MiniCPM-V-2_6"
    assert info.backend in ("transformers-not-installed", "transformers-fallback")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
