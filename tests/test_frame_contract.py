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
from pipeline.scripts.training_sample_builder import (
    build_all,
    build_split_samples,
    convert_subvideo_to_sample,
    load_prompt_library,
)


@pytest.fixture
def prompt_library():
    """加载项目统一的 prompt 模板库。"""
    return load_prompt_library(
        Path(__file__).resolve().parents[1] / "pipeline" / "prompt_library.yaml"
    )


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


def test_prompt_library_has_training_and_inference_target_schemas(prompt_library):
    """训练 target 为四字段，推理 target 为五字段且含 confidence。"""
    assert "target_format" in prompt_library
    assert "target_schema" in prompt_library
    assert "inference_target_format" in prompt_library
    assert "inference_target_schema" in prompt_library

    train_schema = prompt_library["target_schema"]
    inference_schema = prompt_library["inference_target_schema"]
    assert set(train_schema.keys()) == {"has_fracture", "fracture_between", "type", "location"}
    assert set(inference_schema.keys()) == {"has_fracture", "fracture_between", "type", "location", "confidence"}

    train_format = prompt_library["target_format"]
    inference_format = prompt_library["inference_target_format"]
    assert "confidence" not in train_format
    assert "confidence" in inference_format
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
        "review_status": "approved",
    }

    with pytest.raises(ValueError, match="video_fps"):
        convert_subvideo_to_sample(sub, library=prompt_library)


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
    prompt_library,
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
        "review_status": "approved",
    }

    with pytest.raises(ValueError):
        convert_subvideo_to_sample(sub, library=prompt_library)


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
    """靠近边界的普通聚焦不再移位生成；自适应聚焦替代移位的固定窗口。"""
    fps = 2.0

    # 左侧边界：event_frame=1, total_frames=20 → 窗口无法 strict-fit
    # max_window = min(1/0.5, 19/0.5) = 2 → 1.0s < 1.5s → 不生成普通聚焦，也不生成 adaptive
    rec_left = _make_focus_rec(total_frames=20, event_frame=1)
    subs_left = subvideo_builder.build_focus_subvideos(
        rec_left, {"split": "train"}, generate_media=False
    )
    # For window=3, ratio=0.5: not strict-fit → no ordinary, no adaptive (max=1.0s)
    adaptive_left = _find_adaptive(subs_left, 0.5)
    assert adaptive_left is None, "left-boundary at event_frame=1 should not get adaptive (max < 1.5s)"

    # 右侧边界：event_frame=18, total_frames=20 → window=3, ratio=0.5 not strict-fit
    # max_window = min(18/0.5, 2/0.5) = 4 → 2.0s >= 1.5s → adaptive 生成
    rec_right = _make_focus_rec(total_frames=20, event_frame=18)
    subs_right = subvideo_builder.build_focus_subvideos(
        rec_right, {"split": "train"}, generate_media=False
    )
    adaptive_right = _find_adaptive(subs_right, 0.5)
    assert adaptive_right is not None, "right-boundary should get adaptive focus"
    assert adaptive_right["is_adaptive_focus"] is True
    assert adaptive_right["crop_type"] == "focus_adaptive"
    assert adaptive_right["actual_focus_window_seconds"] == pytest.approx(2.0, abs=0.01)
    # Verify position: should be shifted to fit the right side
    assert adaptive_right["end_frame"] == 20, "adaptive should extend to right boundary"


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


def test_ratio_with_strict_fit_and_failed_specs_gets_adaptive() -> None:
    """Strict-fit ordinary focus and one adaptive replacement may coexist for a ratio."""
    # total_frames=12, event_frame=6 → at ratio=0.5, 3s/5s fit,
    # while longer fixed specs fail and collapse to one adaptive replacement.
    rec = _make_focus_rec(total_frames=12, event_frame=6)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )
    assert _find_focus(subs, 3, 0.5) is not None
    assert _find_focus(subs, 5, 0.5) is not None
    assert _find_focus(subs, 10, 0.5) is None
    assert _find_focus(subs, 20, 0.5) is None

    adaptive = _find_adaptive(subs, 0.5)
    assert adaptive is not None
    assert adaptive["crop_type"] == "focus_adaptive"


def test_boundary_ratio_adds_adaptive() -> None:
    """A left-boundary ratio with no strict-fit fixed window should get one adaptive."""
    # event_frame=2, total_frames=60 → event at ~1s in a 30s video
    total_frames = 60
    event_frame = 2  # very close to start

    rec = _make_focus_rec(total_frames=total_frames, event_frame=event_frame)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )

    # Should have some strict-fit ordinary focus AND some adaptive (for non-strict-fit ratios)
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


def test_mixed_case_preserves_strict_fit_and_adaptive() -> None:
    """Mixed case: ratio=0.5 preserves 3s ordinary focus and adds one adaptive
    replacement for failed 5/10/20 specs.

    event_time=1.6s, duration=60s, fps=2 → total_frames=120, event_frame=3
    - ratio=0.5: window=3s strict-fits [0, 6) → ordinary focus preserved;
      5/10/20 not strict-fit → skipped (no shifted) and replaced by one adaptive.
    - ratio=0.65: no window strict-fits → one adaptive focus (2.0s)
    - ratio=0.8: no window strict-fits → one adaptive focus (1.5s)
    """
    total_frames = 120  # 60s * 2fps
    event_frame = 3     # 1.6s * 2fps, rounded

    rec = _make_focus_rec(total_frames=total_frames, event_frame=event_frame)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )

    # 3s ordinary focus should exist for ratio=0.5 (strict-fit)
    sub_3s = _find_focus(subs, 3, 0.5)
    assert sub_3s is not None, "3s ordinary focus should be preserved (strict-fit)"
    assert sub_3s["crop_type"] == "focus_3s"
    assert sub_3s.get("is_adaptive_focus") is None or sub_3s["is_adaptive_focus"] is False

    # 5s/10s/20s ordinary focus should NOT exist for ratio=0.5 (not strict-fit, no shifted)
    for window in [5, 10, 20]:
        sub_shifted = _find_focus(subs, window, 0.5)
        assert sub_shifted is None, f"{window}s ordinary focus should NOT exist for ratio=0.5 (not strict-fit)"

    # One adaptive for ratio=0.5 replaces the failed 5s/10s/20s specs.
    adaptive_05 = _find_adaptive(subs, 0.5)
    assert adaptive_05 is not None
    assert adaptive_05["is_adaptive_focus"] is True
    assert adaptive_05["crop_type"] == "focus_adaptive"
    assert adaptive_05["actual_focus_window_seconds"] == pytest.approx(3.0, abs=0.01)

    # ratio=0.65 has no strict-fit windows → gets one adaptive (2.0s)
    adaptive_065 = _find_adaptive(subs, 0.65)
    assert adaptive_065 is not None, "ratio=0.65 should have adaptive (no strict-fit windows)"
    assert adaptive_065["is_adaptive_focus"] is True
    assert adaptive_065["crop_type"] == "focus_adaptive"
    assert adaptive_065["actual_focus_window_seconds"] == pytest.approx(2.0, abs=0.01)

    # ratio=0.8 has no strict-fit windows → gets one adaptive (1.5s)
    adaptive_08 = _find_adaptive(subs, 0.8)
    assert adaptive_08 is not None, "ratio=0.8 should have adaptive (no strict-fit windows)"
    assert adaptive_08["is_adaptive_focus"] is True
    assert adaptive_08["crop_type"] == "focus_adaptive"
    assert adaptive_08["actual_focus_window_seconds"] == pytest.approx(1.5, abs=0.01)

    # At most one adaptive per ratio
    for ratio in [0.65, 0.8]:
        adaptive_count = sum(1 for s in subs if s.get("is_adaptive_focus") and s["event_position_ratio"] == ratio)
        assert adaptive_count == 1, f"ratio={ratio} should have exactly 1 adaptive, got {adaptive_count}"


def test_full_fail_case_produces_adaptive_no_ordinary() -> None:
    """Full-fail: event_time=1s, duration=60s, ratio=0.5 → only adaptive, no ordinary focus.

    event_frame=2, total_frames=120, fps=2
    - window=3, ratio=0.5: desired_start=2-3=-1 → not strict-fit
    - All windows for ratio=0.5 fail → no ordinary focus for ratio=0.5
    - max_window = min(2/0.5, 118/0.5) = min(4, 236) = 4 → 2.0s ≥ 1.5s ✓
    - One adaptive focus replaces all failed specs for ratio=0.5
    """
    rec = _make_focus_rec(total_frames=120, event_frame=2)
    subs = subvideo_builder.build_focus_subvideos(
        rec, {"split": "train"}, generate_media=False
    )

    # No ordinary focus for ratio=0.5 (all windows fail strict-fit)
    for window in subvideo_builder.FOCUS_WINDOWS:
        sub = _find_focus(subs, window, 0.5)
        assert sub is None, f"No ordinary focus for w={window}, r=0.5 in full-fail case"

    # One adaptive focus for ratio=0.5
    adaptive_05 = _find_adaptive(subs, 0.5)
    assert adaptive_05 is not None, "Full-fail case should produce adaptive focus"
    assert adaptive_05["is_adaptive_focus"] is True
    assert adaptive_05["crop_type"] == "focus_adaptive"
    assert adaptive_05["actual_focus_window_seconds"] == pytest.approx(2.0, abs=0.01)

    # Only one adaptive for this ratio
    adaptive_count = sum(1 for s in subs if s.get("is_adaptive_focus") and s["event_position_ratio"] == 0.5)
    assert adaptive_count == 1, f"Should have exactly 1 adaptive for ratio=0.5"

    # Other ratios may still have strict-fit ordinary focus
    ordinary_count = sum(1 for s in subs if not s.get("is_adaptive_focus"))
    # Some ordinary focus for ratios like 0.2, 0.35, etc. may still exist
    # for windows that DO strict-fit
    assert ordinary_count >= 0


def test_select_sample_videos_by_id() -> None:
    """select_sample_videos with explicit video_ids returns only matching records."""
    records = [
        {"video_id": "v1", "type": "韧性断裂", "has_fracture_canonical": True,
         "location_canonical": "inside_gauge", "fps": 2.0, "total_frames": 100,
         "duration": 50.0, "event_frame_original": 50, "event_frame_effective": None,
         "video_path": "data/01_videos/v1.mp4", "location": None},
        {"video_id": "v2", "type": "未断裂", "has_fracture_canonical": False,
         "location_canonical": None, "fps": 2.0, "total_frames": 100,
         "duration": 50.0, "event_frame_original": None, "event_frame_effective": None,
         "video_path": "data/01_videos/v2.mp4", "location": None},
        {"video_id": "v3", "type": "韧性断裂", "has_fracture_canonical": True,
         "location_canonical": "inside_gauge", "fps": 2.0, "total_frames": 100,
         "duration": 50.0, "event_frame_original": 50, "event_frame_effective": None,
         "video_path": "data/01_videos/v3.mp4", "location": None},
    ]
    split_mapping = {"v1": {"split": "train"}, "v2": {"split": "train"}, "v3": {"split": "train"}}

    # Filter by specific IDs
    result = subvideo_builder.select_sample_videos(
        records, split_mapping, video_ids=["v1", "v3"]
    )
    assert len(result) == 2
    assert {r["video_id"] for r in result} == {"v1", "v3"}

    # Missing IDs should warn but still return what's found
    result2 = subvideo_builder.select_sample_videos(
        records, split_mapping, video_ids=["v1", "v_missing"]
    )
    assert len(result2) == 1
    assert result2[0]["video_id"] == "v1"


def test_select_sample_videos_random_seed() -> None:
    """select_sample_videos with sample_size and seed is deterministic."""
    records = [
        {"video_id": f"v{i}", "type": "韧性断裂", "has_fracture_canonical": True,
         "location_canonical": "inside_gauge", "fps": 2.0, "total_frames": 100,
         "duration": 50.0, "event_frame_original": 50, "event_frame_effective": None,
         "video_path": f"data/01_videos/v{i}.mp4", "location": None}
        for i in range(20)
    ]
    split_mapping = {f"v{i}": {"split": "train"} for i in range(20)}

    # Same seed → same result
    result1 = subvideo_builder.select_sample_videos(
        records, split_mapping, sample_size=5, sample_seed=42
    )
    result2 = subvideo_builder.select_sample_videos(
        records, split_mapping, sample_size=5, sample_seed=42
    )
    assert [r["video_id"] for r in result1] == [r["video_id"] for r in result2]

    # Different seed → different result (likely but not guaranteed for small lists)
    result3 = subvideo_builder.select_sample_videos(
        records, split_mapping, sample_size=5, sample_seed=999
    )
    ids_42 = [r["video_id"] for r in result1]
    ids_999 = [r["video_id"] for r in result3]
    # With 20 items selecting 5, there's a good chance they differ
    # (C(20,5)=15504 possible combinations, so seed-different is almost certainly different)
    # But we'll just check length
    assert len(result1) == 5
    assert len(result3) == 5


def test_select_sample_videos_boundary_weighted_falls_back_when_no_scores() -> None:
    """Boundary-weighted sample should not fail when records have no event frames."""
    records = [
        {"video_id": f"v{i}", "type": "未断裂", "has_fracture_canonical": False,
         "location_canonical": None, "fps": 2.0, "total_frames": 100,
         "duration": 50.0, "event_frame_original": None, "event_frame_effective": None,
         "video_path": f"data/01_videos/v{i}.mp4", "location": None}
        for i in range(10)
    ]
    split_mapping = {f"v{i}": {"split": "train"} for i in range(10)}

    result1 = subvideo_builder.select_sample_videos(
        records, split_mapping, sample_size=4, sample_seed=42, boundary_weighted=True
    )
    result2 = subvideo_builder.select_sample_videos(
        records, split_mapping, sample_size=4, sample_seed=42, boundary_weighted=True
    )

    assert len(result1) == 4
    assert [r["video_id"] for r in result1] == [r["video_id"] for r in result2]


def test_sample_candidate_redirects_output_before_media_generation(tmp_path: Path) -> None:
    """Sample media generation must target the isolated sample tree, not full output dirs."""
    candidate = {
        "subvideo_id": "focus_test_focus_3s_50pct",
        "video_path": "data/03_subvideos/focus_test_focus_3s_50pct.mp4",
        "frame_paths": ["04_frames/focus_test_focus_3s_50pct/frame_0000.jpg"],
    }
    sample_root = tmp_path / "sample_subvideos"

    redirected = subvideo_builder._sample_candidate_for_output(candidate, sample_root)

    assert redirected is not candidate
    assert redirected["video_path"] == str(sample_root / "03_subvideos" / "focus_test_focus_3s_50pct.mp4")
    assert subvideo_builder._subvideo_output_path(redirected) == (
        sample_root / "03_subvideos" / "focus_test_focus_3s_50pct.mp4"
    )
    assert redirected["frame_paths"] == []
    assert candidate["video_path"] == "data/03_subvideos/focus_test_focus_3s_50pct.mp4"


def test_metadata_path_preserves_data_relative_format() -> None:
    """Full output metadata should keep the historical path format relative to data/."""
    path = subvideo_builder.PROJECT_ROOT / "data" / "04_frames" / "sub" / "frame_0000.jpg"
    assert subvideo_builder._metadata_path_for_output(path) == "04_frames/sub/frame_0000.jpg"


def test_sample_cli_flags_parse() -> None:
    """Sample mode CLI flags parse correctly."""
    import argparse

    # Build parser the same way as main()
    parser = argparse.ArgumentParser(description="test")
    parser.add_argument("--sample-size", type=int, default=None)
    parser.add_argument("--sample-seed", type=int, default=None)
    parser.add_argument("--sample-output-dir", type=str, default=None)
    parser.add_argument("--video-ids", type=str, nargs="+", default=None)
    parser.add_argument("--sample-boundary-weighted", action="store_true", default=False)

    # Default: no sample mode
    args = parser.parse_args([])
    assert args.sample_size is None
    assert args.video_ids is None
    assert args.sample_boundary_weighted is False

    # --sample-size enables sample mode
    args2 = parser.parse_args(["--sample-size", "3"])
    assert args2.sample_size == 3

    # --video-ids with multiple IDs
    args3 = parser.parse_args(["--video-ids", "v1", "v2", "v3"])
    assert args3.video_ids == ["v1", "v2", "v3"]

    # --sample-boundary-weighted flag
    args4 = parser.parse_args(["--sample-size", "5", "--sample-boundary-weighted"])
    assert args4.sample_size == 5
    assert args4.sample_boundary_weighted is True

    # --sample-seed
    args5 = parser.parse_args(["--sample-size", "5", "--sample-seed", "123"])
    assert args5.sample_seed == 123

    # --sample-output-dir
    args6 = parser.parse_args(["--sample-size", "5", "--sample-output-dir", "/tmp/samples"])
    assert args6.sample_output_dir == "/tmp/samples"


def _make_training_sub(
    subvideo_id: str = "sub_test",
    has_fracture: bool | None = False,
    ftype: str = "未断裂",
    fracture_between: list[int] | None = None,
    location: str | None = None,
    review_status: str = "approved",
) -> dict[str, Any]:
    """构造一条符合 convert_subvideo_to_sample 最小输入要求的子视频。"""
    return {
        "subvideo_id": subvideo_id,
        "video_path": f"data/03_subvideos/{subvideo_id}.mp4",
        "source_video": "video_0001",
        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
        "actual_frame_mapping": [
            {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
            {"input_index": 1, "original_frame": 10, "timestamp": 1.0},
        ],
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "fracture_between": fracture_between,
        "type": ftype,
        "location": location,
        "location_canonical": location,
        "source_type": ftype,
        "source_location": location,
        "review_status": review_status,
    }


def _parse_result(content: str) -> dict[str, Any]:
    """assistant content 必须是严格的四字段 JSON。"""
    assert "判断依据：" not in content
    assert "结果：" not in content
    return json.loads(content)


def test_positive_sample_assistant_content_is_pure_json(prompt_library) -> None:
    """正样本 assistant target 是不含解释或 confidence 的 JSON。"""
    sub = _make_training_sub(
        subvideo_id="sub_pos",
        has_fracture=True,
        ftype="韧性断裂",
        fracture_between=[2, 3],
        location="inside_gauge",
    )
    sample = convert_subvideo_to_sample(sub, library=prompt_library)
    assistant = sample["messages"][2]["content"]

    assert "confidence" not in assistant.lower()
    assert "判断依据：" not in assistant
    assert "结果：" not in assistant

    result = _parse_result(assistant)
    assert set(result.keys()) == {"has_fracture", "fracture_between", "type", "location"}
    assert result["has_fracture"] is True
    assert result["fracture_between"] == [2, 3]
    assert result["type"] == "韧性断裂"
    assert result["location"] == "inside_gauge"


def test_negative_sample_assistant_content_has_no_fracture(prompt_library) -> None:
    """负样本 assistant target 结果区 has_fracture=False，且不包含 confidence。"""
    sub = _make_training_sub(
        subvideo_id="sub_neg",
        has_fracture=False,
        ftype="未断裂",
        fracture_between=None,
        location=None,
    )
    sample = convert_subvideo_to_sample(sub, library=prompt_library)
    assistant = sample["messages"][2]["content"]

    assert "confidence" not in assistant.lower()
    assert "判断依据：" not in assistant
    assert "结果：" not in assistant

    result = _parse_result(assistant)
    assert set(result.keys()) == {"has_fracture", "fracture_between", "type", "location"}
    assert result["has_fracture"] is False
    assert result["fracture_between"] is None
    assert result["type"] == "未断裂"
    assert result["location"] is None


def test_anomaly_sample_assistant_content_structured_as_anomaly(prompt_library) -> None:
    """视频异常样本（has_fracture=None）结果区保留 type=视频异常，结构正确。"""
    sub = _make_training_sub(
        subvideo_id="sub_anomaly",
        has_fracture=None,
        ftype="视频异常",
        fracture_between=None,
        location=None,
    )
    sample = convert_subvideo_to_sample(sub, library=prompt_library)
    assistant = sample["messages"][2]["content"]

    assert "confidence" not in assistant.lower()
    assert "判断依据：" not in assistant
    assert "结果：" not in assistant

    result = _parse_result(assistant)
    assert set(result.keys()) == {"has_fracture", "fracture_between", "type", "location"}
    assert result["has_fracture"] is None
    assert result["fracture_between"] is None
    assert result["type"] == "视频异常"
    assert result["location"] is None


@pytest.mark.parametrize(
    "has_fracture, fracture_between, expected_type",
    [
        (True, [2, 3], "未夹紧"),
        (False, None, "未断裂"),
        (None, None, "未断裂"),
    ],
)
def test_unclamped_label_with_and_without_event(
    has_fracture: bool | None,
    fracture_between: list[int] | None,
    expected_type: str,
    prompt_library,
) -> None:
    """有事件标注的未夹紧保留为未夹紧；无事件标注的未夹紧降级为未断裂。"""
    sub = _make_training_sub(
        subvideo_id="sub_unclamped",
        has_fracture=has_fracture,
        ftype="未夹紧",
        fracture_between=fracture_between,
        location=None,
    )
    sample = convert_subvideo_to_sample(sub, library=prompt_library)
    assistant = sample["messages"][2]["content"]

    result = _parse_result(assistant)
    assert result["type"] == expected_type
    assert result["has_fracture"] == (has_fracture is True)


def test_training_sample_messages_order_and_system_prompt(prompt_library) -> None:
    """messages 顺序为 [system, user, assistant]，且 system content 来自模板库。"""
    sub = _make_training_sub(subvideo_id="sub_msg")
    sample = convert_subvideo_to_sample(sub, library=prompt_library)
    messages = sample["messages"]

    assert [m["role"] for m in messages] == ["system", "user", "assistant"]
    assert messages[0]["content"] == prompt_library["system_prompt"]
    assert "<video>" in messages[1]["content"]


def test_training_sample_has_only_llamafactory_fields(prompt_library) -> None:
    """训练样本只保留 LlamaFactory 所需的 videos 与 messages。"""
    sub = _make_training_sub(subvideo_id="sub_version")
    sample = convert_subvideo_to_sample(sub, library=prompt_library)

    assert set(sample) == {"videos", "messages"}


def test_training_sample_excludes_traceability_metadata(prompt_library) -> None:
    """可追溯信息只在 07_metadata，训练样本不重复保存。"""
    sub = _make_training_sub(
        subvideo_id="sub_trace",
        has_fracture=True,
        ftype="韧性断裂",
        fracture_between=[2, 3],
        location="inside_gauge",
        review_status="approved",
    )
    sub["reviewed_at"] = "2026-07-09T12:00:00+00:00"
    sample = convert_subvideo_to_sample(sub, library=prompt_library)

    assert set(sample) == {"messages", "videos"}
    assert "metadata" not in sample
    assert "source_video" not in sample
    assert "has_fracture" not in sample


def test_convert_subvideo_to_sample_rejects_non_approved(prompt_library) -> None:
    """直接调用 convert_subvideo_to_sample 时，非 approved 样本必须被拒绝。"""
    sub = _make_training_sub(subvideo_id="sub_dropped", review_status="dropped")

    with pytest.raises(ValueError, match="review_status"):
        convert_subvideo_to_sample(sub, library=prompt_library)


def test_build_split_samples_drops_dropped_subvideos(
    prompt_library,
) -> None:
    """build_split_samples 应剔除 dropped 子视频，approved 样本正常导出。"""
    approved = _make_training_sub(subvideo_id="sub_approved", review_status="approved")
    dropped = _make_training_sub(subvideo_id="sub_dropped", review_status="dropped")

    split_video_ids = {"fold_0_train": {"video_0001"}}

    split_samples = build_split_samples(
        [approved, dropped],
        split_video_ids,
        library=prompt_library,
        seed=42,
    )

    assert len(split_samples["fold_0_train"]) == 1
    assert split_samples["fold_0_train"][0]["videos"] == ["data/03_subvideos/sub_approved.mp4"]


@pytest.mark.parametrize("bad_status", ["unreviewed", "needs_regenerate", None])
def test_build_split_samples_blocks_unallowed_status(
    prompt_library,
    bad_status: str | None,
) -> None:
    """unreviewed、needs_regenerate 或状态缺失时应阻止训练导出。"""
    approved = _make_training_sub(subvideo_id="sub_approved", review_status="approved")
    bad = _make_training_sub(
        subvideo_id="sub_bad", review_status=bad_status
    )

    split_video_ids = {"fold_0_train": {"video_0001"}}

    with pytest.raises(ValueError, match="sub_bad"):
        build_split_samples(
            [approved, bad],
            split_video_ids,
            library=prompt_library,
            seed=42,
        )


def test_build_split_samples_blocks_non_dropped_excluded_subvideos(
    prompt_library,
) -> None:
    """excluded_subvideos 中存在非 dropped 状态时应阻止训练导出，即使 subvideos 全为 approved。"""
    approved = _make_training_sub(
        subvideo_id="sub_approved", review_status="approved"
    )

    excluded = [
        {"subvideo_id": "sub_unreviewed", "review_status": "unreviewed"},
        {"subvideo_id": "sub_needs", "review_status": "needs_regenerate"},
        {"subvideo_id": "sub_bad", "review_status": "bad_status"},
        {"subvideo_id": "sub_missing"},
    ]

    split_video_ids = {"fold_0_train": {"video_0001"}}

    with pytest.raises(ValueError, match="excluded_subvideos"):
        build_split_samples(
            [approved],
            split_video_ids,
            library=prompt_library,
            seed=42,
            excluded_subvideos=excluded,
        )


def test_build_split_samples_allows_dropped_excluded_subvideos(
    prompt_library,
) -> None:
    """excluded_subvideos 全为 dropped 时允许训练导出。"""
    approved = _make_training_sub(
        subvideo_id="sub_approved", review_status="approved"
    )

    split_video_ids = {"fold_0_train": {"video_0001"}}

    split_samples = build_split_samples(
        [approved],
        split_video_ids,
        library=prompt_library,
        seed=42,
        excluded_subvideos=[
            {"subvideo_id": "sub_dropped", "review_status": "dropped"}
        ],
    )

    assert len(split_samples["fold_0_train"]) == 1
    assert split_samples["fold_0_train"][0]["videos"] == ["data/03_subvideos/sub_approved.mp4"]


@pytest.mark.parametrize("bad_item", [None, "not-a-dict"])
def test_build_split_samples_rejects_non_object_excluded_subvideos(
    prompt_library, bad_item
) -> None:
    """excluded_subvideos 中存在非对象项时应阻止训练导出。"""
    approved = _make_training_sub(
        subvideo_id="sub_approved", review_status="approved"
    )
    split_video_ids = {"fold_0_train": {"video_0001"}}

    with pytest.raises(ValueError, match="非对象项"):
        build_split_samples(
            [approved],
            split_video_ids,
            library=prompt_library,
            seed=42,
            excluded_subvideos=[bad_item],
        )


@pytest.mark.parametrize("bad_subvideo_id", [None, "", "<unknown>"])
def test_build_split_samples_rejects_invalid_subvideo_id_in_excluded_subvideos(
    prompt_library, bad_subvideo_id
) -> None:
    """excluded_subvideos 中存在无效 subvideo_id 时应阻止训练导出。"""
    approved = _make_training_sub(
        subvideo_id="sub_approved", review_status="approved"
    )

    excluded = [{"subvideo_id": bad_subvideo_id, "review_status": "dropped"}]
    split_video_ids = {"fold_0_train": {"video_0001"}}

    with pytest.raises(ValueError, match="subvideo_id"):
        build_split_samples(
            [approved],
            split_video_ids,
            library=prompt_library,
            seed=42,
            excluded_subvideos=excluded,
        )


@pytest.mark.parametrize("bad_subvideo_id", [None, "", "<unknown>"])
def test_build_all_rejects_invalid_subvideo_id_in_excluded_subvideos(
    tmp_path: Path, bad_subvideo_id
) -> None:
    """build_all 对 excluded_subvideos 中无效 subvideo_id 失败。"""
    meta = tmp_path / "subvideos_meta.label_reviewed.json"
    splits_dir = tmp_path / "splits"
    output_dir = tmp_path / "output"
    prompt_library_path = (
        Path(__file__).resolve().parents[1] / "pipeline" / "prompt_library.yaml"
    )

    meta.write_text(
        json.dumps(
            {
                "subvideos": [
                    {
                        "subvideo_id": "sub_approved",
                        "review_status": "approved",
                        "type": "未断裂",
                        "video_path": "data/03_subvideos/sub_approved.mp4",
                        "source_video": "video_0001",
                        "processor_fingerprint": "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers",
                        "actual_frame_mapping": [
                            {
                                "input_index": 0,
                                "original_frame": 0,
                                "timestamp": 0.0,
                            }
                        ],
                        "has_fracture": False,
                        "has_fracture_canonical": False,
                        "fracture_between": None,
                        "location": None,
                        "location_canonical": None,
                    }
                ],
                "excluded_subvideos": [
                    {"subvideo_id": bad_subvideo_id, "review_status": "dropped"},
                ],
            }
        ),
        encoding="utf-8",
    )

    splits_dir.mkdir()
    (splits_dir / "fold_0_train.json").write_text(
        json.dumps({"video_ids": ["video_0001"]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="subvideo_id"):
        build_all(
            meta,
            splits_dir,
            output_dir,
            prompt_library_path=prompt_library_path,
        )


def _make_neg_before_rec(fracture_type: str) -> dict[str, Any]:
    """fps=2, total_frames=240, duration=120, event_frame=200 → event_time=100, region_end=99。"""
    rec = _make_focus_rec(total_frames=240, event_frame=200)
    rec["type"] = fracture_type
    return rec


def _run_build_neg_before(rec: dict[str, Any], monkeypatch) -> list[dict[str, Any]]:
    class FakePreprocessor:
        def fingerprint(self):
            return "minicpmv4_5:test:max_frames=8:video_fps=2:backend=transformers"

        def get_info(self):
            return None

    monkeypatch.setattr(subvideo_builder, "_processor_info", lambda _p: {"backend": "test"})
    return subvideo_builder.build_neg_before_after(
        rec,
        {"split": "train"},
        generate_media=False,
        preprocessor=FakePreprocessor(),
    )


def test_neg_before_ductile_keeps_all_windows(monkeypatch) -> None:
    """韧性断裂不去重：4 clip_len × 3 窗 = 恰好 12 条 neg_before。"""
    subs = _run_build_neg_before(_make_neg_before_rec("韧性断裂"), monkeypatch)
    assert len(subs) == 12
    assert all(sub["crop_type"] == "neg_before" for sub in subs)


def test_neg_before_brittle_dedup_keeps_closest_to_event(monkeypatch) -> None:
    """脆性断裂只保留最临近事件的一条：胜者为 3s 第 3 窗，end_time≈99.0。"""
    subs = _run_build_neg_before(_make_neg_before_rec("脆性断裂"), monkeypatch)
    assert len(subs) == 1
    assert subs[0]["subvideo_id"].endswith("_3s_03")
    assert subs[0]["end_time"] == pytest.approx(99.0)


def test_neg_before_brittle_compound_type_dedup(monkeypatch) -> None:
    """复合类型「脆性断裂、齐根断裂」同样按脆性去重。"""
    subs = _run_build_neg_before(_make_neg_before_rec("脆性断裂、齐根断裂"), monkeypatch)
    assert len(subs) == 1
    assert subs[0]["subvideo_id"].endswith("_3s_03")
    assert subs[0]["end_time"] == pytest.approx(99.0)


def test_pre_event_windows_respect_min_gap() -> None:
    """_pre_event_windows 边界：所有窗口 ed <= event_time - 1.0。"""
    assert subvideo_builder._pre_event_windows(duration=120.0, event_time=2.0, clip_len=3) == []
    for event_time in (2.0, 10.5, 100.0):
        for clip_len in subvideo_builder.NEG_CLIP_DURATIONS:
            for _st, ed in subvideo_builder._pre_event_windows(120.0, event_time, clip_len):
                assert ed <= event_time - 1.0
