from __future__ import annotations

import json
from pathlib import Path

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
