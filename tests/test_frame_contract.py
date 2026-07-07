from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.preprocessing.adapter import FrameMapping
from pipeline.preprocessing.minicpm_preprocessor import (
    MiniCPMVideoPreprocessor,
    _resolve_model_path,
)
from pipeline.scripts import subvideo_builder
from pipeline.scripts.training_sample_builder import convert_subvideo_to_sample


def test_llamafactory_sampling_positions_match_floor_fps_contract() -> None:
    assert MiniCPMVideoPreprocessor._llamafactory_sample_positions(
        total_frames=90,
        duration=2.16,
        video_fps=2.0,
        video_maxlen=8,
    ) == [0, 29, 59, 89]
    assert MiniCPMVideoPreprocessor._llamafactory_sample_positions(
        total_frames=120,
        duration=5.0,
        video_fps=2.0,
        video_maxlen=8,
    ) == [0, 17, 34, 51, 68, 85, 102, 119]


def test_minicpm_sample_uses_image_processor_video_path(monkeypatch) -> None:
    class PixelValues:
        shape = (1, 3, 3, 4, 4)

    class ImageProcessor:
        def __init__(self) -> None:
            self.calls = []

        def __call__(self, videos, **kwargs):
            self.calls.append((videos, kwargs))
            return {"pixel_values": PixelValues()}

    class Processor:
        def __init__(self) -> None:
            self.image_processor = ImageProcessor()

        def __call__(self, *_args, **_kwargs):
            raise AssertionError("top-level processor path must not be used")

    processor = Processor()
    preprocessor = MiniCPMVideoPreprocessor("models/minicpmv4_5", processor=processor)
    frames = [object(), object(), object()]

    monkeypatch.setattr(
        MiniCPMVideoPreprocessor,
        "_decode_frame_range",
        lambda *_args, **_kwargs: (frames, [10, 20, 30], [1.0, 2.0, 3.0]),
    )

    mapping = preprocessor._sample_with_processor(
        None, None, 0.0, 2.0, 3, {}
    )

    assert [m.original_frame for m in mapping] == [10, 20, 30]
    assert processor.image_processor.calls == [
        (
            [frames],
            {"do_pad": True, "max_slice_nums": 2, "return_tensors": "pt"},
        )
    ]


def test_preprocessor_sample_fails_closed_without_pyav_fallback() -> None:
    class BrokenPreprocessor:
        def sample(self, *_args, **_kwargs):
            raise RuntimeError("processor unavailable")

    with pytest.raises(RuntimeError, match="processor unavailable"):
        subvideo_builder._preprocessor_sample(
            BrokenPreprocessor(), Path("missing.mp4"), 0.0, 1.0
        )


def test_model_path_resolver_accepts_minicpm_directory_alias(tmp_path: Path) -> None:
    model_dir = tmp_path / "models" / "minicpmv4_5"
    model_dir.mkdir(parents=True)

    requested = tmp_path / "models" / "minicpm-v-4.5"

    assert Path(_resolve_model_path(str(requested))) == model_dir


def test_extract_sampled_frames_exports_exact_mapping(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"placeholder")
    output_dir = tmp_path / "frames"
    output_dir.mkdir()
    (output_dir / "frame_9999.jpg").write_bytes(b"stale")

    commands = []

    def fake_ffmpeg(cmd):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"jpg")

    monkeypatch.setattr(subvideo_builder, "_run_ffmpeg_checked", fake_ffmpeg)

    frames = subvideo_builder.extract_sampled_frames(
        video,
        output_dir,
        [
            {"input_index": 0, "clip_frame": 3, "original_frame": 103},
            {"input_index": 1, "original_frame": 9},
        ],
    )

    assert [path.name for path in frames] == ["frame_0000.jpg", "frame_0001.jpg"]
    assert sorted(path.name for path in output_dir.glob("frame_*.jpg")) == [
        "frame_0000.jpg",
        "frame_0001.jpg",
    ]
    assert commands[0][commands[0].index("-vf") + 1] == "select=eq(n\\,3)"
    assert commands[1][commands[1].index("-vf") + 1] == "select=eq(n\\,9)"
    assert all("fps=" not in arg for cmd in commands for arg in cmd)


def test_generate_media_fills_mapping_from_preprocessor(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    clip = tmp_path / "clip.mp4"
    source.write_bytes(b"placeholder")

    class ContractPreprocessor:
        def sample(self, video_path: str, start_time: float, end_time: float):
            assert Path(video_path) == clip
            assert start_time == 0.0
            assert end_time == 2.2
            return [
                FrameMapping(input_index=0, original_frame=0, timestamp=0.066),
                FrameMapping(input_index=1, original_frame=10, timestamp=1.166),
            ]

        def fingerprint(self) -> str:
            return "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers"

        def get_info(self):
            return None

    monkeypatch.setattr(subvideo_builder, "crop_video", lambda *_args, **_kwargs: clip.write_bytes(b"clip"))
    monkeypatch.setattr(subvideo_builder, "_video_duration", lambda path: 2.2 if path == clip else 99.0)
    monkeypatch.setattr(subvideo_builder, "_source_video_path", lambda _rec: source)
    monkeypatch.setattr(subvideo_builder, "_subvideo_output_path", lambda _sub: clip)
    monkeypatch.setattr(subvideo_builder, "_processor_info", lambda _preprocessor: {"backend": "test"})

    sub = {
        "subvideo_id": "video_0001_neg",
        "video_path": "data/03_subvideos/video_0001_neg.mp4",
        "crop_type": "neg_before",
        "start_time": 5.0,
        "end_time": 7.0,
        "start_frame": 150,
        "end_frame": 210,
        "duration": 2.0,
        "has_fracture": False,
        "has_fracture_canonical": False,
        "type": "未断裂",
        "fracture_between": None,
    }
    result = subvideo_builder._generate_media_for_candidate(
        sub,
        {"video_id": "video_0001"},
        tmp_path,
        extract_frames=False,
        preprocessor=ContractPreprocessor(),
    )

    assert result["actual_frame_mapping"] == [
        {
            "input_index": 0,
            "original_frame": 150,
            "timestamp": 5.0,
            "clip_frame": 0,
            "clip_timestamp": 0.066,
        },
        {
            "input_index": 1,
            "original_frame": 160,
            "timestamp": 6.1,
            "clip_frame": 10,
            "clip_timestamp": 1.166,
        },
    ]
    assert result["processor_fingerprint"].startswith("minicpmv4_5:test")


def test_training_sample_builder_rejects_legacy_minicpm_fingerprint() -> None:
    sub = {
        "subvideo_id": "legacy",
        "video_path": "data/01_videos/video_0001.mp4",
        "source_video": "video_0001",
        "processor_fingerprint": "minicpmv4_5:models/minicpm-v-4.5:max_frames=8:backend=transformers",
        "actual_frame_mapping": [
            {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
            {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
        ],
        "has_fracture": False,
        "has_fracture_canonical": False,
        "fracture_between": None,
        "type": "未断裂",
        "location": None,
        "location_canonical": None,
        "source_type": "未断裂",
        "source_location": None,
    }

    with pytest.raises(ValueError, match="video_fps"):
        convert_subvideo_to_sample(sub)


@pytest.mark.parametrize(
    "fingerprint",
    [
        "minicpm:video_fps=2",
        "minicpmv4_5:test:max_frames=16:video_fps=2:backend=transformers",
        "minicpmv4_5:test:max_frames=8:video_fps=1:backend=transformers",
        "minicpmv4_5:test:max_frames=8:video_fps=2:backend=no-transformers",
    ],
)
def test_training_sample_builder_rejects_incomplete_or_wrong_minicpm_fingerprint(
    fingerprint: str,
) -> None:
    sub = {
        "subvideo_id": "bad-fingerprint",
        "video_path": "data/01_videos/video_0001.mp4",
        "source_video": "video_0001",
        "processor_fingerprint": fingerprint,
        "actual_frame_mapping": [
            {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
            {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
        ],
        "has_fracture": False,
        "has_fracture_canonical": False,
        "fracture_between": None,
        "type": "未断裂",
        "location": None,
        "location_canonical": None,
        "source_type": "未断裂",
        "source_location": None,
    }

    with pytest.raises(ValueError):
        convert_subvideo_to_sample(sub)


def test_default_extract_frames_is_true() -> None:
    import argparse

    # 通过 argparse BooleanOptionalAction 的解析行为验证默认值
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract-frames", action=argparse.BooleanOptionalAction, default=True)
    assert parser.parse_args([]).extract_frames is True
    assert parser.parse_args(["--no-extract-frames"]).extract_frames is False
    assert parser.parse_args(["--extract-frames"]).extract_frames is True


def test_subvideo_builder_internal_defaults_extract_frames_true() -> None:
    import inspect

    sigs = [
        subvideo_builder.build_focus_subvideos,
        subvideo_builder.build_neg_before_after,
        subvideo_builder.build_non_fracture_clips,
        subvideo_builder.build_full_subvideo,
        subvideo_builder.build_subvideos_for_record,
        subvideo_builder._generate_media_for_candidate,
    ]
    for fn in sigs:
        sig = inspect.signature(fn)
        default = sig.parameters["extract_frames"].default
        assert default is True, f"{fn.__name__} default extract_frames={default}"


def test_full_subvideo_materialized_to_03_subvideos(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "data" / "01_videos" / "video_0001.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")

    copied = []
    def fake_copy(input_path: Path, output_path: Path) -> None:
        copied.append((input_path, output_path))
        output_path.write_bytes(source.read_bytes())

    monkeypatch.setattr(subvideo_builder, "copy_as_subvideo", fake_copy)
    monkeypatch.setattr(subvideo_builder, "extract_sampled_frames", lambda *args, **kwargs: [])

    class FakePreprocessor:
        def fingerprint(self):
            return "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers"
        def get_info(self):
            return None
        def sample(self, video_path: str, start_time: float, end_time: float):
            return [
                FrameMapping(input_index=0, original_frame=0, timestamp=0.0),
            ]

    monkeypatch.setattr(subvideo_builder, "_video_duration", lambda _path: 10.0)
    monkeypatch.setattr(subvideo_builder, "_processor_info", lambda _preprocessor: {"backend": "test"})
    monkeypatch.setattr(
        subvideo_builder,
        "_source_video_path",
        lambda _rec: tmp_path / "data" / "01_videos" / "video_0001.mp4",
    )

    rec = {
        "video_id": "video_0001",
        "video_path": "data/01_videos/video_0001.mp4",
        "type": "未断裂",
        "has_fracture_canonical": False,
        "location": None,
        "location_canonical": None,
        "fps": 2.0,
        "total_frames": 20,
        "duration": 10.0,
        "event_frame_original": None,
        "event_frame_effective": None,
    }
    sub = subvideo_builder.build_full_subvideo(
        rec,
        {"split": "train", "fold": "fold_0_train"},
        generate_media=True,
        extract_frames=True,
        preprocessor=FakePreprocessor(),
    )

    assert sub is not None
    assert sub["video_path"].startswith("03_subvideos/") or sub["video_path"].startswith("data/03_subvideos/")
    assert not sub["video_path"].startswith("data/01_videos/")
    assert len(copied) == 1
    assert copied[0][1].name == "video_0001_full.mp4"


def test_label_review_contract_detects_frame_count_mismatch(tmp_path: Path, monkeypatch) -> None:
    from pipeline.scripts.review_subvideo_labels import review_subvideo_labels

    subvideo_id = "contract_check"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True)
    # 映射声明 2 帧，但目录下只有 1 帧
    (frame_dir / "frame_0000.jpg").write_bytes(b"jpg")

    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "full_pos",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "actual_frame_mapping": [
            {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
            {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
        ],
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }
    meta_path.write_text(json.dumps({"subvideos": [sub]}), encoding="utf-8")
    video_meta_path.write_text(json.dumps([{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": "inside_gauge",
    }]), encoding="utf-8")

    passed, failed = review_subvideo_labels(
        meta_path,
        video_meta_path,
        out_path,
        report_path,
        frame_dir_root=tmp_path / "data" / "04_frames",
        project_root=tmp_path,
    )

    assert len(failed) == 1
    assert any("frame_file_count_mismatch" in r for r in failed[0]["reasons"])
    assert not out_path.exists()


def test_label_review_fails_empty_actual_frame_mapping(tmp_path: Path) -> None:
    from pipeline.scripts.review_subvideo_labels import review_subvideo_labels

    subvideo_id = "empty_mapping"
    data_dir = tmp_path / "data"
    mp4 = data_dir / "03_subvideos" / f"{subvideo_id}.mp4"
    frame_dir = data_dir / "04_frames" / subvideo_id
    mp4.parent.mkdir(parents=True, exist_ok=True)
    mp4.write_bytes(b"mp4")
    frame_dir.mkdir(parents=True, exist_ok=True)
    (frame_dir / "frame_0000.jpg").write_bytes(b"jpg")

    meta_path = tmp_path / "subvideos_meta.reviewed.json"
    out_path = tmp_path / "subvideos_meta.label_reviewed.json"
    report_path = tmp_path / "report.json"
    video_meta_path = tmp_path / "video_meta.json"

    sub = {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "crop_type": "full_pos",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "actual_frame_mapping": [],
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
    }
    meta_path.write_text(json.dumps({"subvideos": [sub]}), encoding="utf-8")
    video_meta_path.write_text(json.dumps([{
        "video_id": "video_0001",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location_canonical": "inside_gauge",
    }]), encoding="utf-8")

    passed, failed = review_subvideo_labels(
        meta_path,
        video_meta_path,
        out_path,
        report_path,
        frame_dir_root=tmp_path / "data" / "04_frames",
        project_root=tmp_path,
    )

    assert len(failed) == 1
    assert any("empty_actual_frame_mapping" in r for r in failed[0]["reasons"])
    assert not out_path.exists()


def _make_focus_rec(
    total_frames: int,
    event_frame: int,
    video_id: str = "focus_test",
) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "video_path": "data/01_videos/focus_test.mp4",
        "type": "韧性断裂",
        "has_fracture_canonical": True,
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "fps": 2.0,
        "total_frames": total_frames,
        "duration": total_frames / 2.0,
        "event_frame_original": event_frame,
        "event_frame_effective": None,
    }


def _find_focus(subvideos: list[dict[str, Any]], window: int, ratio: float) -> dict[str, Any] | None:
    subvideo_id = f"focus_test_focus_{window}s_{int(ratio * 100):02d}pct"
    for sub in subvideos:
        if sub["subvideo_id"] == subvideo_id:
            return sub
    return None


def test_focus_window_expands_toward_opposite_side() -> None:
    """靠近边界时，窗口应优先向对侧扩展并保持目标长度。"""
    fps = 2.0
    window = 3
    expected_length = round(window * fps)  # 6 frames

    # 左侧越界：事件靠近开头，应向右侧扩展。
    rec_left = _make_focus_rec(total_frames=20, event_frame=1)
    subs_left = subvideo_builder.build_focus_subvideos(
        rec_left, {"split": "train"}, generate_media=False
    )
    sub_left = _find_focus(subs_left, window, 0.5)
    assert sub_left is not None
    assert sub_left["end_frame"] - sub_left["start_frame"] == expected_length
    assert sub_left["start_frame"] == 0
    assert sub_left["end_frame"] == expected_length

    # 右侧越界：事件靠近末尾，应向左侧扩展。
    rec_right = _make_focus_rec(total_frames=20, event_frame=18)
    subs_right = subvideo_builder.build_focus_subvideos(
        rec_right, {"split": "train"}, generate_media=False
    )
    sub_right = _find_focus(subs_right, window, 0.5)
    assert sub_right is not None
    assert sub_right["end_frame"] - sub_right["start_frame"] == expected_length
    assert sub_right["end_frame"] == 20
    assert sub_right["start_frame"] == 20 - expected_length


def test_focus_window_drops_when_both_sides_insufficient() -> None:
    """视频剩余空间不足以容纳完整窗口时，普通 focus 候选应被丢弃。
    自适应 focus 若满足最小窗口仍可生成。"""
    rec = _make_focus_rec(total_frames=5, event_frame=2)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    ordinary = [s for s in subs if not s.get("is_adaptive_focus")]
    assert ordinary == [], "Ordinary focus should not fit in 5-frame video"


def test_focus_event_position_matches_intended_ratio() -> None:
    """生成子视频的事件相对位置与预设 ratio 的偏差在允许误差内。"""
    rec = _make_focus_rec(total_frames=100, event_frame=50)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    assert len(subs) == len(subvideo_builder.FOCUS_WINDOWS) * len(
        subvideo_builder.FOCUS_POSITIONS
    )
    for sub in subs:
        start = sub["start_frame"]
        end = sub["end_frame"]
        event = rec["event_frame_original"]
        actual_ratio = (event - start) / (end - start)
        intended_ratio = sub["event_position_ratio"]
        assert actual_ratio == pytest.approx(intended_ratio, abs=0.06)


def test_focus_3s_always_has_6_frames() -> None:
    """所有 3 秒 focus 子视频的帧数恒为 6 帧（fps=2.0）。"""
    rec = _make_focus_rec(total_frames=100, event_frame=50)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    focus_3s = [sub for sub in subs if sub["crop_type"] == "focus_3s"]
    assert len(focus_3s) == len(subvideo_builder.FOCUS_POSITIONS)
    for sub in focus_3s:
        assert sub["end_frame"] - sub["start_frame"] == 6


def test_focus_window_exactly_fits_video_length() -> None:
    """total_frames == window * fps 的居中事件应生成完整窗口 [0, total_frames)，不被丢弃。"""
    fps = 2.0
    window = 3
    total_frames = 6
    event_frame = 3
    expected_length = round(window * fps)  # 6 frames

    rec = _make_focus_rec(total_frames=total_frames, event_frame=event_frame)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    sub = _find_focus(subs, window, 0.5)
    assert sub is not None
    assert sub["start_frame"] == 0
    assert sub["end_frame"] == total_frames
    assert sub["end_frame"] - sub["start_frame"] == expected_length


def _find_adaptive(subvideos: list[dict[str, Any]], ratio: float) -> dict[str, Any] | None:
    """Find an adaptive focus subvideo for the given ratio."""
    for sub in subvideos:
        if sub.get("is_adaptive_focus") and sub["event_position_ratio"] == ratio:
            return sub
    return None


def test_ordinary_focus_crop_type_and_id_unchanged() -> None:
    """Ordinary focus subvideo_id and crop_type must remain unchanged."""
    rec = _make_focus_rec(total_frames=100, event_frame=50)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    for window in subvideo_builder.FOCUS_WINDOWS:
        for ratio in subvideo_builder.FOCUS_POSITIONS:
            sub = _find_focus(subs, window, ratio)
            assert sub is not None, f"Missing ordinary focus for w={window} r={ratio}"
            assert sub["subvideo_id"] == f"focus_test_focus_{window}s_{int(ratio * 100):02d}pct"
            assert sub["crop_type"] == f"focus_{window}s"
            assert sub.get("is_adaptive_focus") is None or sub["is_adaptive_focus"] is False


def test_centered_event_no_adaptive() -> None:
    """A well-centered event with strict-fit windows should NOT generate adaptive candidates."""
    rec = _make_focus_rec(total_frames=100, event_frame=50)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    adaptive_subs = [s for s in subs if s.get("is_adaptive_focus")]
    assert adaptive_subs == [], f"Unexpected adaptive focus: {[s['subvideo_id'] for s in adaptive_subs]}"


def test_ratio_with_strict_fit_skips_adaptive() -> None:
    """A ratio that has at least one strict-fit fixed window should not get an adaptive candidate."""
    # total_frames=12, event_frame=6 → at ratio=0.5, 3s(6 frames) fits exactly in [0, 12)
    rec = _make_focus_rec(total_frames=12, event_frame=6)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    # ratio=0.5 should have strict-fit (3s window fits exactly)
    adaptive = _find_adaptive(subs, 0.5)
    assert adaptive is None, f"ratio=0.5 should not get adaptive when strict-fit exists"


def test_boundary_ratio_adds_adaptive() -> None:
    """A left-boundary ratio with no strict-fit fixed window should get one adaptive."""
    # event_frame=2, total_frames=60 → event at ~1s in a 30s video
    total_frames = 60
    event_frame = 2  # very close to start

    rec = _make_focus_rec(total_frames=total_frames, event_frame=event_frame)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )

    # Should have some ordinary focus (with shift) AND some adaptive
    ordinary = [s for s in subs if not s.get("is_adaptive_focus")]
    assert len(ordinary) > 0

    # At least one ratio should have no strict-fit, producing adaptive
    # ratio=0.5: event_frame=2, round(3*0.5*2)=3 → desired_start=-1 < 0 → no strict-fit
    # max_window_frames = min(2/0.5, 58/0.5) = min(4, 116) = 4 → 2.0s >= 1.5s ✓
    adaptive_05 = _find_adaptive(subs, 0.5)
    assert adaptive_05 is not None, "ratio=0.5 should have adaptive for left-boundary event"

    # Verify adaptive metadata
    assert adaptive_05["is_adaptive_focus"] is True
    assert adaptive_05["crop_type"] == "focus_adaptive"
    assert "actual_focus_window_seconds" in adaptive_05
    assert adaptive_05["actual_focus_window_seconds"] > 0
    assert "_adaptive" in adaptive_05["subvideo_id"]


def test_extreme_boundary_no_adaptive() -> None:
    """Event extremely close to boundary with max_window < min_adaptive should NOT get adaptive."""
    # event_frame=1, total_frames=60 → event at ~0.5s in a 30s video
    # For ratio=0.5: max_window_frames = min(1/0.5, 59/0.5) = min(2, 118) = 2 → 1.0s < 1.5s
    rec = _make_focus_rec(total_frames=60, event_frame=1)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    adaptive = _find_adaptive(subs, 0.5)
    assert adaptive is None, "ratio=0.5 at extreme left boundary should NOT have adaptive"


def test_adaptive_metadata_fields_present() -> None:
    """Adaptive focus subvideos must include is_adaptive_focus, actual_focus_window_seconds, and event_position_ratio."""
    rec = _make_focus_rec(total_frames=60, event_frame=2)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    adaptive_subs = [s for s in subs if s.get("is_adaptive_focus")]
    assert len(adaptive_subs) > 0, "Expected at least one adaptive focus"

    for sub in adaptive_subs:
        assert sub.get("is_adaptive_focus") is True
        assert "actual_focus_window_seconds" in sub
        assert isinstance(sub["actual_focus_window_seconds"], (int, float))
        assert sub["actual_focus_window_seconds"] > 0
        assert "event_position_ratio" in sub
        assert sub["event_position_ratio"] in subvideo_builder.FOCUS_POSITIONS
        assert sub["crop_type"] == "focus_adaptive"
        assert "_adaptive" in sub["subvideo_id"]


def test_adaptive_ratio_frame_quantized_tolerance() -> None:
    """Adaptive focus event_position_ratio should be within frame-quantized tolerance."""
    rec = _make_focus_rec(total_frames=60, event_frame=2)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    adaptive_subs = [s for s in subs if s.get("is_adaptive_focus")]

    for sub in adaptive_subs:
        start = sub["start_frame"]
        end = sub["end_frame"]
        event = rec["event_frame_original"]
        actual_ratio = (event - start) / (end - start)
        intended_ratio = sub["event_position_ratio"]

        # Frame-quantized tolerance: at most 1 frame offset in either direction
        # Max error = (1/2) / window_frames * 2 = 1/window_frames
        # Use a generous tolerance that accounts for small adaptive windows
        window_frames = end - start
        max_frame_error = 1.0 / window_frames if window_frames > 0 else 1.0
        assert actual_ratio == pytest.approx(intended_ratio, abs=max(max_frame_error, 0.05))


def test_at_most_one_adaptive_per_ratio() -> None:
    """No ratio should have more than one adaptive focus candidate."""
    rec = _make_focus_rec(total_frames=60, event_frame=2)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    adaptive_subs = [s for s in subs if s.get("is_adaptive_focus")]
    ratios_seen = set()
    for sub in adaptive_subs:
        r = sub["event_position_ratio"]
        assert r not in ratios_seen, f"Duplicate adaptive focus for ratio {r}"
        ratios_seen.add(r)


def test_adaptive_generates_when_ordinary_focus_empty() -> None:
    """A video too short for any ordinary fixed-window focus should still get adaptive candidates."""
    # fps=2, total_frames=4 (2s), event_frame=2 (centered)
    # Ordinary focus min window=3s=6 frames > 4 frames → no ordinary focus fits
    # Adaptive: max_window_frames = min(2/0.5, 2/0.5) = 4 → 2.0s >= 1.5s → generates
    rec = _make_focus_rec(total_frames=4, event_frame=2)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )

    ordinary = [s for s in subs if not s.get("is_adaptive_focus")]
    adaptive = [s for s in subs if s.get("is_adaptive_focus")]

    # No ordinary focus should fit in a 4-frame (2s) video
    assert len(ordinary) == 0, f"Expected 0 ordinary focus, got {len(ordinary)}"

    # Centered event at ratio=0.5 should produce one adaptive candidate
    assert len(adaptive) >= 1, "Expected at least one adaptive focus"
    adaptive_05 = _find_adaptive(subs, 0.5)
    assert adaptive_05 is not None, "ratio=0.5 should have adaptive"
    assert adaptive_05["crop_type"] == "focus_adaptive"
    assert adaptive_05["actual_focus_window_seconds"] == pytest.approx(2.0, abs=0.01)
    assert "_adaptive" in adaptive_05["subvideo_id"]

    # Verify ratio is roughly correct (frame-quantized)
    start = adaptive_05["start_frame"]
    end = adaptive_05["end_frame"]
    actual_ratio = (rec["event_frame_original"] - start) / (end - start)
    assert actual_ratio == pytest.approx(0.5, abs=0.06)
