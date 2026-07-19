from __future__ import annotations

import json
import sys
from pathlib import Path

from pipeline.scripts import freeze_data_version


def test_freeze_cli_defaults_to_label_reviewed_meta(tmp_path, monkeypatch):
    """Patch 5: CLI 默认使用 label-reviewed 子视频元数据。"""
    captured: dict[str, object] = {}

    def spy_run_freeze(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "version": "2.0.0",
            "code": {"commit": "abc123"},
            "config": {"combined_sha256": "cfg"},
            "environment": {},
            "processor": {"dominant": "fp"},
            "input_video_manifest": {"count": 1},
            "split_manifest": {"count": 1},
            "sample_manifest": {"count": 1},
            "statistics": {"summary": {}},
            "disk_usage_bytes": {},
        }

    monkeypatch.setattr(freeze_data_version, "run_freeze", spy_run_freeze)
    monkeypatch.setattr(sys, "argv", ["freeze_data_version.py"])

    rc = freeze_data_version.main()

    assert rc == 0
    assert str(captured.get("subvideos_meta_path")).endswith(
        "subvideos_meta.label_reviewed.json"
    )


def test_run_freeze_accepts_provided_reviewed_meta(tmp_path):
    """Patch 5: run_freeze 可正常处理传入的 reviewed meta 路径。"""
    merged = tmp_path / "data" / "06_merged"
    merged.mkdir(parents=True)
    splits = tmp_path / "data" / "05_splits"
    splits.mkdir(parents=True)
    subvideo_dir = tmp_path / "data" / "03_subvideos"
    subvideo_dir.mkdir(parents=True)
    meta_dir = tmp_path / "data" / "07_metadata"
    meta_dir.mkdir(parents=True)

    video_meta = meta_dir / "video_meta.json"
    video_meta.write_text(json.dumps([{"video_id": "v1"}]), encoding="utf-8")
    reviewed_meta = meta_dir / "subvideos_meta.label_reviewed.json"
    reviewed_meta.write_text(json.dumps({"subvideos": []}), encoding="utf-8")
    lock_path = tmp_path / "data_version_lock.json"

    lock = freeze_data_version.run_freeze(
        merged_dir=merged,
        subvideos_meta_path=reviewed_meta,
        video_meta_path=video_meta,
        splits_dir=splits,
        subvideo_dir=subvideo_dir,
        lock_path=lock_path,
        config_files=[],
        project_root=tmp_path,
    )

    assert lock["version"] == "2.0.0"
    assert lock_path.exists()


def test_sample_manifest_ignores_stale_subvideo_eval_artifacts(tmp_path):
    merged = tmp_path / "data" / "06_merged"
    merged.mkdir(parents=True)
    for name in (
        "fold_0_train.json",
        "samples_meta.json",
        "test_inputs.json",
        "test_subvideo_inputs.json",
        "test_subvideo_ground_truth.json",
    ):
        (merged / name).write_text("[]", encoding="utf-8")

    manifest = freeze_data_version._collect_sample_manifest_sha256(merged)

    assert manifest["count"] == 3
    assert manifest["files"] == [
        "fold_0_train.json",
        "samples_meta.json",
        "test_inputs.json",
    ]


def test_processor_fingerprints_ignore_subvideo_eval_artifacts(tmp_path):
    merged = tmp_path / "data" / "06_merged"
    merged.mkdir(parents=True)
    (merged / "test_subvideo_inputs.json").write_text(
        json.dumps([{"processor_fingerprint": "stale:absolute-path"}]),
        encoding="utf-8",
    )
    reviewed_meta = tmp_path / "reviewed.json"
    reviewed_meta.write_text(
        json.dumps({"subvideos": [{"processor_fingerprint": "current:relative-path"}]}),
        encoding="utf-8",
    )

    result = freeze_data_version._collect_processor_fingerprints(
        merged, reviewed_meta
    )

    assert result["fingerprints"] == {"current:relative-path": 1}
