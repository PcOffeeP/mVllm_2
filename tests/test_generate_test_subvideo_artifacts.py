import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import generate_test_subvideo_artifacts as gen


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _prepare(tmp: Path) -> Path:
    meta_dir = tmp / "07_metadata"
    merged_dir = tmp / "06_merged"
    splits_dir = tmp / "05_splits"
    meta_dir.mkdir(parents=True)
    merged_dir.mkdir(parents=True)
    splits_dir.mkdir(parents=True)

    video_meta = [
        {"video_id": "v1", "event_time": 1.5, "video_anomaly_kind": None, "event_frame_original": 3},
        {"video_id": "v2", "event_time": None, "video_anomaly_kind": None, "event_frame_original": None},
        {"video_id": "v3", "event_time": 2.0, "video_anomaly_kind": None, "event_frame_original": 4},
    ]
    _write_json(meta_dir / "video_meta.json", video_meta)
    _write_json(splits_dir / "test.json", {"video_ids": ["v1", "v2", "v3"]})
    return meta_dir


def _run_cli(tmp: Path, argv: list[str]) -> tuple[list, list, dict]:
    merged_dir = tmp / "06_merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = tmp / "test_subvideos_meta.json"
    argv.extend(["--manifest", str(manifest_path), "--merged-dir", str(merged_dir)])

    old_root = gen.ROOT
    gen.ROOT = tmp
    try:
        with patch.object(sys, "argv", ["generate_test_subvideo_artifacts.py"] + argv):
            rc = gen.main()
    finally:
        gen.ROOT = old_root

    assert rc == 0
    inputs = json.loads((merged_dir / "test_subvideo_inputs.json").read_text())
    gt = json.loads((merged_dir / "test_subvideo_ground_truth.json").read_text())
    manifest = json.loads(manifest_path.read_text())
    return inputs, gt, manifest


def test_label_reviewed_strict_blocks_unreviewed():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        meta_dir = _prepare(tmp)
        metadata = {
            "subvideos": [
                {
                    "subvideo_id": "sv1",
                    "source_video": "v1",
                    "video_path": "data/03_subvideos/sv1.mp4",
                    "type": "韧性断裂",
                    "has_fracture": True,
                    "has_fracture_canonical": True,
                    "review_status": "approved",
                    "reviewer_notes": "looks good",
                },
                {
                    "subvideo_id": "sv2",
                    "source_video": "v2",
                    "video_path": "data/03_subvideos/sv2.mp4",
                    "type": "未断裂",
                    "has_fracture": False,
                    "review_status": "dropped",
                    "reviewer_notes": "bad crop",
                },
                {
                    "subvideo_id": "sv3",
                    "source_video": "v3",
                    "video_path": "data/03_subvideos/sv3.mp4",
                    "type": "脆性断裂",
                    "has_fracture": True,
                    "review_status": "unreviewed",
                },
            ]
        }
        _write_json(meta_dir / "test_subvideos_meta.label_reviewed.json", metadata)

        argv = [
            "--metadata", str(meta_dir / "test_subvideos_meta.label_reviewed.json"),
            "--video-meta", str(meta_dir / "video_meta.json"),
            "--splits-dir", str(tmp / "05_splits"),
            "--skip-healthcheck",
            "--metadata-only",
            "--strict",
        ]
        with pytest.raises(RuntimeError, match="sv3: unreviewed"):
            _run_cli(tmp, argv)


def test_label_reviewed_non_strict_exports_only_approved():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        meta_dir = _prepare(tmp)
        metadata = {
            "subvideos": [
                {
                    "subvideo_id": "sv1",
                    "source_video": "v1",
                    "video_path": "data/03_subvideos/sv1.mp4",
                    "type": "韧性断裂",
                    "has_fracture": True,
                    "has_fracture_canonical": True,
                    "review_status": "approved",
                    "reviewer_notes": "looks good",
                },
                {
                    "subvideo_id": "sv2",
                    "source_video": "v2",
                    "video_path": "data/03_subvideos/sv2.mp4",
                    "type": "未断裂",
                    "has_fracture": False,
                    "review_status": "dropped",
                    "reviewer_notes": "bad crop",
                },
                {
                    "subvideo_id": "sv3",
                    "source_video": "v3",
                    "video_path": "data/03_subvideos/sv3.mp4",
                    "type": "脆性断裂",
                    "has_fracture": True,
                    "review_status": "unreviewed",
                },
            ]
        }
        _write_json(meta_dir / "test_subvideos_meta.label_reviewed.json", metadata)

        argv = [
            "--metadata", str(meta_dir / "test_subvideos_meta.label_reviewed.json"),
            "--video-meta", str(meta_dir / "video_meta.json"),
            "--splits-dir", str(tmp / "05_splits"),
            "--skip-healthcheck",
            "--metadata-only",
            "--no-strict",
        ]
        inputs, gt, manifest = _run_cli(tmp, argv)
        assert len(inputs) == 1
        assert inputs[0]["subvideo_id"] == "sv1"
        assert len(gt) == 1
        assert gt[0]["subvideo_id"] == "sv1"
        assert gt[0]["review_status"] == "approved"
        assert gt[0]["reviewer_notes"] == "looks good"
        assert manifest["exported_count"] == 1
        assert manifest["review_filter_applied"] is True


def test_needs_regenerate_blocks_strict():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        meta_dir = _prepare(tmp)
        metadata = {
            "subvideos": [
                {
                    "subvideo_id": "sv1",
                    "source_video": "v1",
                    "video_path": "data/03_subvideos/sv1.mp4",
                    "type": "韧性断裂",
                    "has_fracture": True,
                    "review_status": "approved",
                },
                {
                    "subvideo_id": "sv2",
                    "source_video": "v2",
                    "video_path": "data/03_subvideos/sv2.mp4",
                    "type": "未断裂",
                    "has_fracture": False,
                    "review_status": "needs_regenerate",
                },
            ]
        }
        _write_json(meta_dir / "test_subvideos_meta.label_reviewed.json", metadata)

        argv = [
            "--metadata", str(meta_dir / "test_subvideos_meta.label_reviewed.json"),
            "--video-meta", str(meta_dir / "video_meta.json"),
            "--splits-dir", str(tmp / "05_splits"),
            "--skip-healthcheck",
            "--metadata-only",
            "--strict",
        ]
        with pytest.raises(RuntimeError, match="sv2: needs_regenerate"):
            _run_cli(tmp, argv)


def test_explicit_missing_metadata_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        meta_dir = _prepare(tmp)
        argv = [
            "--metadata", str(meta_dir / "nonexistent.json"),
            "--video-meta", str(meta_dir / "video_meta.json"),
            "--splits-dir", str(tmp / "05_splits"),
            "--skip-healthcheck",
            "--metadata-only",
            "--strict",
        ]
        with pytest.raises(FileNotFoundError, match="Requested metadata file does not exist"):
            _run_cli(tmp, argv)


def test_raw_metadata_non_strict_passthrough():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        meta_dir = _prepare(tmp)
        metadata = {
            "subvideos": [
                {
                    "subvideo_id": "sv1",
                    "source_video": "v1",
                    "video_path": "data/03_subvideos/sv1.mp4",
                    "type": "韧性断裂",
                    "has_fracture": True,
                    "has_fracture_canonical": True,
                },
                {
                    "subvideo_id": "sv2",
                    "source_video": "v2",
                    "video_path": "data/03_subvideos/sv2.mp4",
                    "type": "未断裂",
                    "has_fracture": False,
                },
            ]
        }
        _write_json(meta_dir / "test_subvideos_meta.json", metadata)

        argv = [
            "--metadata", str(meta_dir / "test_subvideos_meta.json"),
            "--video-meta", str(meta_dir / "video_meta.json"),
            "--splits-dir", str(tmp / "05_splits"),
            "--skip-healthcheck",
            "--metadata-only",
            "--no-strict",
        ]
        inputs, gt, manifest = _run_cli(tmp, argv)
        assert len(inputs) == 2
        assert len(gt) == 2
        assert "review_status" not in gt[0]
        assert manifest["review_filter_applied"] is False


def test_raw_metadata_strict_blocks():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        meta_dir = _prepare(tmp)
        metadata = {
            "subvideos": [
                {
                    "subvideo_id": "sv1",
                    "source_video": "v1",
                    "video_path": "data/03_subvideos/sv1.mp4",
                    "type": "韧性断裂",
                    "has_fracture": True,
                    "has_fracture_canonical": True,
                },
            ]
        }
        _write_json(meta_dir / "test_subvideos_meta.json", metadata)

        argv = [
            "--metadata", str(meta_dir / "test_subvideos_meta.json"),
            "--video-meta", str(meta_dir / "video_meta.json"),
            "--splits-dir", str(tmp / "05_splits"),
            "--skip-healthcheck",
            "--metadata-only",
            "--strict",
        ]
        with pytest.raises(RuntimeError, match="Input metadata has no review_status"):
            _run_cli(tmp, argv)


def test_default_strict_missing_reviewed_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        meta_dir = _prepare(tmp)
        raw = {"subvideos": [{"subvideo_id": "sv_raw", "source_video": "v1", "video_path": "x.mp4", "type": "韧性断裂", "has_fracture": True}]}
        _write_json(meta_dir / "test_subvideos_meta.json", raw)

        gen.RAW_META_DEFAULT = meta_dir / "test_subvideos_meta.json"
        gen.LABEL_REVIEWED_META = meta_dir / "test_subvideos_meta.label_reviewed.json"

        argv = [
            "--video-meta", str(meta_dir / "video_meta.json"),
            "--splits-dir", str(tmp / "05_splits"),
            "--skip-healthcheck",
            "--metadata-only",
            "--strict",
        ]
        with pytest.raises(FileNotFoundError, match="Reviewed metadata file not found"):
            _run_cli(tmp, argv)


def test_default_prefers_label_reviewed():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        meta_dir = _prepare(tmp)
        raw = {"subvideos": [{"subvideo_id": "sv_raw", "source_video": "v1", "video_path": "x.mp4", "type": "韧性断裂", "has_fracture": True}]}
        reviewed = {"subvideos": [{"subvideo_id": "sv_reviewed", "source_video": "v1", "video_path": "x.mp4", "type": "韧性断裂", "has_fracture": True, "review_status": "approved"}]}
        _write_json(meta_dir / "test_subvideos_meta.json", raw)
        _write_json(meta_dir / "test_subvideos_meta.label_reviewed.json", reviewed)

        gen.RAW_META_DEFAULT = meta_dir / "test_subvideos_meta.json"
        gen.LABEL_REVIEWED_META = meta_dir / "test_subvideos_meta.label_reviewed.json"

        argv = [
            "--video-meta", str(meta_dir / "video_meta.json"),
            "--splits-dir", str(tmp / "05_splits"),
            "--skip-healthcheck",
            "--metadata-only",
            "--strict",
        ]
        inputs, gt, manifest = _run_cli(tmp, argv)
        assert len(inputs) == 1
        assert inputs[0]["subvideo_id"] == "sv_reviewed"
