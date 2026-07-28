from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.scripts.archive.publish_training_release import (
    ReleaseError,
    activate_release,
    derive_release_id,
    publish_release,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _combined_sha256(paths: list[Path]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(paths):
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _sources(tmp_path: Path) -> dict[str, Path]:
    merged = tmp_path / "data" / "06_merged"
    metadata = tmp_path / "data" / "07_metadata"
    sample_names = [
        "fold_0_train.json",
        "fold_0_val.json",
        "fold_1_train.json",
        "fold_1_val.json",
        "fold_2_train.json",
        "fold_2_val.json",
        "samples_meta.json",
        "test_inputs.json",
    ]
    for name in sample_names:
        _write_json(merged / name, [{"source": name}])
    _write_json(merged / "test_ground_truth.json", [{"video_id": "video_1"}])

    training_metadata = metadata / "subvideos_meta.filtered.label_reviewed.json"
    quality_report = metadata / "quality_check_report.json"
    version_lock = metadata / "data_version_lock.json"
    _write_json(training_metadata, {"subvideos": [], "excluded_subvideos": []})
    _write_json(
        quality_report,
        {
            "summary": {
                "merged_dir": str(merged),
                "subvideos_meta": str(training_metadata),
                "error_count": 0,
                "warning_count": 0,
            }
        },
    )
    _write_json(
        version_lock,
        {
            "version": "2.0.0",
            "sample_manifest": {
                "files": sample_names,
                "sha256": _combined_sha256([merged / name for name in sample_names]),
            },
        },
    )
    return {
        "merged": merged,
        "training_metadata": training_metadata,
        "quality_report": quality_report,
        "version_lock": version_lock,
        "releases": tmp_path / "data" / "08_training_ready",
    }


def test_derive_release_id_is_deterministic() -> None:
    assert (
        derive_release_id(
            {
                "version": "2.0.0",
                "sample_manifest": {"sha256": "12345678abcdef"},
            }
        )
        == "v2.0.0-12345678"
    )


def test_publish_release_categorizes_and_hashes_files(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    release_dir, manifest = publish_release(
        merged_dir=source["merged"],
        training_metadata=source["training_metadata"],
        quality_report=source["quality_report"],
        version_lock=source["version_lock"],
        releases_dir=source["releases"],
        project_root=tmp_path,
    )

    assert release_dir.name.startswith("v2.0.0-")
    assert (release_dir / "datasets/train/fold_0.json").is_file()
    assert (release_dir / "datasets/validation/fold_2.json").is_file()
    assert (release_dir / "datasets/evaluation/source_videos/inputs.json").is_file()
    assert (release_dir / "metadata/training_subvideos.json").is_file()
    assert (release_dir / "reports/quality_check.json").is_file()
    stored_manifest = json.loads(
        (release_dir / "manifest/release_manifest.json").read_text(encoding="utf-8")
    )
    assert stored_manifest == manifest
    for item in manifest["files"]:
        released_file = release_dir / item["path"]
        assert hashlib.sha256(released_file.read_bytes()).hexdigest() == item["sha256"]


def test_publish_release_rejects_failed_quality_report(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    _write_json(
        source["quality_report"],
        {
            "summary": {
                "merged_dir": str(source["merged"]),
                "subvideos_meta": str(source["training_metadata"]),
                "error_count": 1,
                "warning_count": 0,
            }
        },
    )

    with pytest.raises(ReleaseError, match="error_count=1"):
        publish_release(
            merged_dir=source["merged"],
            training_metadata=source["training_metadata"],
            quality_report=source["quality_report"],
            version_lock=source["version_lock"],
            releases_dir=source["releases"],
            project_root=tmp_path,
        )


def test_publish_release_rejects_incomplete_evaluation_pair(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    (source["merged"] / "test_ground_truth.json").unlink()

    with pytest.raises(ReleaseError, match="evaluation group 'source_videos' is incomplete"):
        publish_release(
            merged_dir=source["merged"],
            training_metadata=source["training_metadata"],
            quality_report=source["quality_report"],
            version_lock=source["version_lock"],
            releases_dir=source["releases"],
            project_root=tmp_path,
        )


def test_publish_release_rejects_changed_frozen_sample(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    _write_json(source["merged"] / "fold_0_train.json", [{"changed": True}])

    with pytest.raises(ReleaseError, match="no longer matches"):
        publish_release(
            merged_dir=source["merged"],
            training_metadata=source["training_metadata"],
            quality_report=source["quality_report"],
            version_lock=source["version_lock"],
            releases_dir=source["releases"],
            project_root=tmp_path,
        )


def test_publish_release_never_overwrites_existing_release(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    arguments = {
        "merged_dir": source["merged"],
        "training_metadata": source["training_metadata"],
        "quality_report": source["quality_report"],
        "version_lock": source["version_lock"],
        "releases_dir": source["releases"],
        "project_root": tmp_path,
    }
    publish_release(**arguments)

    with pytest.raises(ReleaseError, match="will not be overwritten"):
        publish_release(**arguments)


def test_activate_release_updates_training_consumers(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    release_dir, _manifest = publish_release(
        merged_dir=source["merged"],
        training_metadata=source["training_metadata"],
        quality_report=source["quality_report"],
        version_lock=source["version_lock"],
        releases_dir=source["releases"],
        project_root=tmp_path,
    )
    registry = {
        f"tensile_video_interval_fold{fold}_{split}": {}
        for fold in range(3)
        for split in ("train", "val")
    }
    _write_json(tmp_path / "finetune" / "dataset_info.json", registry)

    activate_release(release_dir, project_root=tmp_path)

    active = json.loads(
        (tmp_path / "finetune" / "active_data_release.json").read_text(encoding="utf-8")
    )
    updated_registry = json.loads(
        (tmp_path / "finetune" / "dataset_info.json").read_text(encoding="utf-8")
    )
    assert active["release_id"] == release_dir.name
    assert active["release_dir"].startswith("data/08_training_ready/")
    assert updated_registry["tensile_video_interval_fold0_train"]["file_name"].endswith(
        "/datasets/train/fold_0.json"
    )
    assert updated_registry["tensile_video_interval_fold2_val"]["file_name"].endswith(
        "/datasets/validation/fold_2.json"
    )
