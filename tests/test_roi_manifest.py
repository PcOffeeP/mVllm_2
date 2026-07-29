import hashlib
import json
import os

import pytest

from pipeline.roi_manifest import (
    RoiManifestError,
    build_roi_manifest_bundle,
    write_roi_manifest_bundle,
)
from pipeline.data_rebuild import tree_inventory
from pipeline.scripts import roi_annotation_app as app


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _decision(video_id, video_path, *, status=app.STATUS_APPROVED):
    dragged_box = {"x": 148, "y": 162, "width": 222, "height": 296}
    return app.build_decision(
        video_id=video_id,
        video_path=video_path,
        mode=app.MODE_FIXED,
        review_status=status,
        margins={"top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
        source_width=456,
        source_height=670,
        reviewed_timestamps=[0.0, 1.0, 2.0],
        source_sha256=hashlib.sha256(video_path.read_bytes()).hexdigest(),
        source_video_reference=f"data/01_videos/{video_id}.mp4",
        visibility_checks={key: True for key in app.VISIBILITY_CHECK_KEYS},
        pixel_box_override=dragged_box,
    )


def _fixture(tmp_path):
    root = tmp_path
    videos_dir = root / "data/01_videos"
    videos_dir.mkdir(parents=True)
    video1 = videos_dir / "video_0001.mp4"
    video2 = videos_dir / "video_0002.mp4"
    video1.write_bytes(b"video-one")
    video2.write_bytes(b"video-two")
    metadata = _write(
        root / "data/07_metadata/video_meta.json",
        [
            {"video_id": "video_0001", "video_path": "data/01_videos/video_0001.mp4"},
            {"video_id": "video_0002", "video_path": "data/01_videos/video_0002.mp4"},
        ],
    )
    test_manifest = _write(
        root / "data/05_splits/test.json",
        {"video_ids": ["video_0002"], "count": 1},
    )
    decisions_path = root / "data/07_metadata/roi_decisions.json"
    app.save_roi_payload(
        decisions_path,
        {
            "video_0001": _decision("video_0001", video1),
            "video_0002": _decision("video_0002", video2),
        },
        metadata_path=metadata,
    )
    return {
        "decisions_path": decisions_path,
        "video_metadata_path": metadata,
        "test_manifest_path": test_manifest,
        "project_root": root,
        "generated_at": "2026-07-20T00:00:00+00:00",
    }


def test_freeze_splits_development_and_test(tmp_path):
    bundle = build_roi_manifest_bundle(**_fixture(tmp_path))
    assert bundle["development_roi.json"]["source_count"] == 1
    assert bundle["development_roi.json"]["decisions"][0]["source_video_id"] == "video_0001"
    assert bundle["test_roi_audit.json"]["source_count"] == 1
    assert bundle["test_roi_audit.json"]["decisions"][0]["source_video_id"] == "video_0002"
    assert bundle["manifest.json"]["split_guard"]["overlap_count"] == 0


def test_freeze_requires_complete_coverage(tmp_path):
    paths = _fixture(tmp_path)
    payload = json.loads(paths["decisions_path"].read_text(encoding="utf-8"))
    payload["decisions"].pop()
    _write(paths["decisions_path"], payload)
    with pytest.raises(RoiManifestError, match="缺少 1 条"):
        build_roi_manifest_bundle(**paths)


def test_freeze_requires_every_decision_approved(tmp_path):
    paths = _fixture(tmp_path)
    payload = json.loads(paths["decisions_path"].read_text(encoding="utf-8"))
    payload["decisions"][0]["review_status"] = app.STATUS_NEEDS_REVIEW
    _write(paths["decisions_path"], payload)
    with pytest.raises(RoiManifestError, match="尚未 approved"):
        build_roi_manifest_bundle(**paths)


def test_freeze_rejects_failed_visibility_check(tmp_path):
    paths = _fixture(tmp_path)
    payload = json.loads(paths["decisions_path"].read_text(encoding="utf-8"))
    payload["decisions"][0]["visibility_checks"]["location_judgable"] = False
    _write(paths["decisions_path"], payload)
    with pytest.raises(RoiManifestError, match="location_judgable"):
        build_roi_manifest_bundle(**paths)


def test_freeze_rejects_old_roi_policy(tmp_path):
    paths = _fixture(tmp_path)
    payload = json.loads(paths["decisions_path"].read_text(encoding="utf-8"))
    payload["decisions"][0]["roi_policy_version"] = "1.0"
    _write(paths["decisions_path"], payload)
    with pytest.raises(RoiManifestError, match="必须重新复审"):
        build_roi_manifest_bundle(**paths)


def test_freeze_rejects_non_three_by_four_fixed_box(tmp_path):
    paths = _fixture(tmp_path)
    payload = json.loads(paths["decisions_path"].read_text(encoding="utf-8"))
    decision = payload["decisions"][0]
    decision["pixel_box"]["width"] -= 2
    _write(paths["decisions_path"], payload)
    with pytest.raises(RoiManifestError, match="pixel_box"):
        build_roi_manifest_bundle(**paths)


def test_freeze_requires_fixed_roi_to_be_confirmed_by_drag_box(tmp_path):
    paths = _fixture(tmp_path)
    payload = json.loads(paths["decisions_path"].read_text(encoding="utf-8"))
    payload["decisions"][0]["interaction_mode"] = "legacy_margins"
    _write(paths["decisions_path"], payload)
    with pytest.raises(RoiManifestError, match="拖拽裁剪框"):
        build_roi_manifest_bundle(**paths)


def test_freeze_rejects_changed_source_content(tmp_path):
    paths = _fixture(tmp_path)
    source = tmp_path / "data/01_videos/video_0001.mp4"
    original_mtime = source.stat().st_mtime_ns
    source.write_bytes(b"changed--")
    os.utime(source, ns=(original_mtime, original_mtime))
    with pytest.raises(RoiManifestError, match="SHA-256"):
        build_roi_manifest_bundle(**paths)


def test_manifest_write_is_idempotent_and_non_overwriting(tmp_path):
    paths = _fixture(tmp_path / "inputs")
    bundle = build_roi_manifest_bundle(**paths)
    destination, created = write_roi_manifest_bundle(tmp_path / "out", bundle)
    assert created is True
    assert write_roi_manifest_bundle(tmp_path / "out", bundle) == (destination, False)
    changed = {**bundle, "validation_report.json": {"changed": True}}
    with pytest.raises(FileExistsError, match="拒绝覆盖"):
        write_roi_manifest_bundle(tmp_path / "out", changed)


def test_manifest_bundle_is_identical_across_clean_runs(tmp_path):
    paths = _fixture(tmp_path / "inputs")
    first = build_roi_manifest_bundle(
        **{**paths, "generated_at": "2026-07-20T00:00:00+00:00"}
    )
    second = build_roi_manifest_bundle(
        **{**paths, "generated_at": "2026-07-21T00:00:00+00:00"}
    )

    assert first == second
    first_dir, _ = write_roi_manifest_bundle(tmp_path / "run-a", first)
    second_dir, _ = write_roi_manifest_bundle(tmp_path / "run-b", second)
    assert (
        tree_inventory(first_dir)["tree_sha256"]
        == tree_inventory(second_dir)["tree_sha256"]
    )
