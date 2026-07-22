import hashlib
import json
from pathlib import Path

import pytest

from pipeline.roi_media import (
    RoiMediaError,
    VideoProbe,
    _exact_pad_dimensions,
    build_ffmpeg_command,
    filter_for_decision,
    load_generation_plan,
    validate_existing_bundle,
    validate_temporal_contract,
)


def _canonical_bytes(payload):
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(payload))
    return path


def test_fixed_roi_filter_uses_authoritative_pixel_box():
    decision = {
        "source_video_id": "video_0001",
        "mode": "fixed_roi",
        "source_resolution": [456, 670],
        "pixel_box": {"x": 148, "y": 162, "width": 222, "height": 296},
    }
    video_filter, resolution = filter_for_decision(decision)
    assert video_filter == "crop=222:296:148:162,setsar=1"
    assert resolution == (222, 296)


@pytest.mark.parametrize(
    ("source", "expected"),
    [((456, 670), (504, 672)), ((924, 946), (924, 1232)), ((680, 650), (684, 912))],
)
def test_no_crop_padding_is_smallest_even_exact_three_by_four(source, expected):
    assert _exact_pad_dimensions(*source) == expected
    assert expected[0] * 4 == expected[1] * 3
    assert expected[0] % 2 == 0 and expected[1] % 2 == 0


def test_no_crop_filter_centers_source_without_scaling():
    decision = {
        "source_video_id": "video_0008",
        "mode": "no_crop",
        "source_resolution": [924, 946],
        "pixel_box": {"x": 0, "y": 0, "width": 924, "height": 946},
    }
    video_filter, resolution = filter_for_decision(decision)
    assert video_filter == "pad=924:1232:0:143:color=black,setsar=1"
    assert resolution == (924, 1232)


def test_ffmpeg_command_preserves_timing_contract():
    decision = {
        "source_video_id": "video_0001",
        "mode": "fixed_roi",
        "source_resolution": [456, 670],
        "pixel_box": {"x": 148, "y": 162, "width": 222, "height": 296},
    }
    command = build_ffmpeg_command(Path("in.mp4"), Path("out.mp4"), decision)
    assert command[0] == "ffmpeg"
    assert command[command.index("-vsync") + 1] == "0"
    assert command[command.index("-vf") + 1] == "crop=222:296:148:162,setsar=1"
    assert command[-1] == "out.mp4"


def test_temporal_contract_rejects_frame_count_change():
    source = VideoProbe(456, 670, "25/1", "25/1", 100, 4.0)
    output = VideoProbe(222, 296, "25/1", "25/1", 99, 4.0)
    with pytest.raises(RoiMediaError, match="帧数发生变化"):
        validate_temporal_contract(source, output, (222, 296))


def test_temporal_contract_accepts_equivalent_frame_rate_rationals():
    source = VideoProbe(456, 670, "25/1", "25/1", 100, 4.0)
    output = VideoProbe(222, 296, "50/2", "50/2", 100, 4.0)
    validate_temporal_contract(source, output, (222, 296))


def test_temporal_contract_accepts_mp4_timebase_rounding():
    source = VideoProbe(456, 670, "30/1", "30/1", 18857, 628.5667)
    output = VideoProbe(222, 296, "56570000/1885617", "30/1", 18857, 628.5667)
    validate_temporal_contract(source, output, (222, 296))


def test_temporal_contract_accepts_small_vfr_to_cfr_average_shift():
    source = VideoProbe(576, 1072, "16875/562", "30/1", 180, 5.994633)
    output = VideoProbe(804, 1072, "30/1", "30/1", 180, 6.0)
    validate_temporal_contract(source, output, (804, 1072))


def test_temporal_contract_rejects_material_frame_rate_change():
    source = VideoProbe(456, 670, "30/1", "30/1", 100, 4.0)
    output = VideoProbe(222, 296, "25/1", "25/1", 100, 4.0)
    with pytest.raises(RoiMediaError, match="标称帧率发生变化"):
        validate_temporal_contract(source, output, (222, 296))


def test_load_generation_plan_verifies_frozen_inputs(tmp_path: Path):
    project = tmp_path
    source = project / "data/01_videos/video_0001.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    video_meta = [{"video_id": "video_0001", "video_path": "data/01_videos/video_0001.mp4"}]
    video_meta_path = _write(project / "data/07_metadata/video_meta.json", video_meta)
    decisions = {
        "decisions": [
            {
                "source_video_id": "video_0001",
                "source_video_path": "data/01_videos/video_0001.mp4",
                "source_sha256": source_hash,
                "mode": "fixed_roi",
                "source_resolution": [456, 670],
                "pixel_box": {"x": 148, "y": 162, "width": 222, "height": 296},
            }
        ]
    }
    roi_dir = project / "roi-manifest-test"
    decisions_path = _write(roi_dir / "roi_decisions.frozen.json", decisions)
    manifest = {
        "roi_manifest_id": "roi-manifest-test",
        "inputs": {"video_metadata_sha256": hashlib.sha256(video_meta_path.read_bytes()).hexdigest()},
        "artifacts": {
            "roi_decisions.frozen.json": {
                "sha256": hashlib.sha256(decisions_path.read_bytes()).hexdigest()
            }
        },
    }
    _write(roi_dir / "manifest.json", manifest)

    plan = load_generation_plan(roi_dir, video_meta_path, project)

    assert plan["source_count"] == 1
    assert plan["full_scope"] is True
    assert plan["rows"][0]["output_resolution"] == (222, 296)


def test_filter_rejects_missing_geometry():
    with pytest.raises(RoiMediaError, match="source_resolution"):
        filter_for_decision({"source_video_id": "x", "mode": "fixed_roi"})


def test_existing_bundle_is_hash_verified_before_reuse(tmp_path: Path):
    destination = tmp_path / "data/03_roi_videos/roi-media-test"
    video = destination / "videos/video_0001.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"roi-video")
    metadata = destination / "video_meta.roi.json"
    report = destination / "validation_report.json"
    metadata.write_bytes(b"[]\n")
    report.write_bytes(b"{}\n")
    identity = {"roi_manifest_id": "roi-manifest-test"}
    manifest = {
        "identity": identity,
        "videos": [
            {
                "source_video_id": "video_0001",
                "output_path": str(video.relative_to(tmp_path)),
                "output_size_bytes": video.stat().st_size,
                "output_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            }
        ],
        "artifacts": {
            "video_meta.roi.json": {
                "sha256": hashlib.sha256(metadata.read_bytes()).hexdigest()
            },
            "validation_report.json": {
                "sha256": hashlib.sha256(report.read_bytes()).hexdigest()
            },
        },
    }
    _write(destination / "manifest.json", manifest)
    plan = {
        "identity": identity,
        "rows": [{"video_id": "video_0001"}],
        "project_root": str(tmp_path),
    }

    validate_existing_bundle(destination, plan)
    video.write_bytes(b"tampered")
    with pytest.raises(RoiMediaError, match="大小发生变化"):
        validate_existing_bundle(destination, plan)
