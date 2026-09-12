from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import artifact_index, artifact_resolver
from pipeline.scripts import roi_annotation_app as app


def _all_visible():
    return {key: True for key in app.VISIBILITY_CHECK_KEYS}


def test_normalize_margins_and_box():
    margins = {"top": 0.1, "right": 0.2, "bottom": 0.15, "left": 0.05}

    assert app.normalize_margins(margins) == margins
    assert app.normalized_box(margins) == {
        "x": 0.05,
        "y": 0.1,
        "width": 0.75,
        "height": 0.75,
    }


@pytest.mark.parametrize(
    "margins, message",
    [
        ({"top": -0.1}, r"\[0, 1\)"),
        ({"left": 0.5, "right": 0.5}, "左右"),
        ({"top": 0.6, "bottom": 0.4}, "上下"),
    ],
)
def test_normalize_margins_rejects_invalid_geometry(margins, message):
    with pytest.raises(app.RoiValidationError, match=message):
        app.normalize_margins(margins)


def test_pixel_box_is_in_bounds_with_even_dimensions():
    result = app.pixel_box(
        {"top": 0.101, "right": 0.199, "bottom": 0.103, "left": 0.203},
        457,
        671,
    )

    assert result["width"] % 2 == 0
    assert result["height"] % 2 == 0
    assert result["x"] >= 0 and result["y"] >= 0
    assert result["x"] + result["width"] <= 457
    assert result["y"] + result["height"] <= 671


def test_aspect_locked_geometry_expands_to_exact_three_by_four():
    requested = {"top": 0.05, "right": 0.165, "bottom": 0.1, "left": 0.28}

    margins, normalized, box = app.aspect_locked_geometry(requested, 456, 670)

    assert box["width"] * 4 == box["height"] * 3
    assert box["width"] % 2 == 0 and box["height"] % 2 == 0
    assert box["width"] >= app.pixel_box(requested, 456, 670)["width"]
    assert box["height"] >= app.pixel_box(requested, 456, 670)["height"]
    assert normalized["width"] == round(box["width"] / 456, 6)
    assert app.pixel_box(margins, 456, 670) == box


def test_normalize_drag_box_returns_exact_even_three_by_four_pixels():
    result = app.normalize_drag_box(
        {"left": 23.7, "top": 30.2, "width": 431.5, "height": 575.8},
        456,
        670,
    )

    assert result["width"] * 4 == result["height"] * 3
    assert result["width"] % 2 == 0 and result["height"] % 2 == 0
    assert result["x"] >= 0 and result["y"] >= 0
    assert result["x"] + result["width"] <= 456
    assert result["y"] + result["height"] <= 670


def test_initial_drag_box_expands_legacy_non_ratio_box():
    existing = {
        "pixel_box": {"x": 128, "y": 34, "width": 252, "height": 570},
        "margins": {"top": 0.05, "right": 0.165, "bottom": 0.1, "left": 0.28},
        "roi_policy_version": "1.0",
    }

    result = app.initial_drag_box(existing, 456, 670)

    assert result == {"x": 24, "y": 31, "width": 432, "height": 576}


def test_audit_timestamps_include_boundaries_and_event_neighborhood():
    timestamps = app.audit_timestamps(40.0, event_time=30.0)

    assert timestamps[:2] == [0.0, 10.0]
    assert 29.8 in timestamps
    assert 30.0 in timestamps
    assert 30.2 in timestamps
    assert timestamps[-1] < 40.0


def test_build_no_crop_decision_uses_full_frame(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")

    decision = app.build_decision(
        video_id="video_0001",
        video_path=video,
        mode=app.MODE_NO_CROP,
        review_status=app.STATUS_APPROVED,
        margins={"top": 0.2, "right": 0.2, "bottom": 0.2, "left": 0.2},
        source_width=456,
        source_height=670,
        reviewed_timestamps=[0.0, 20.0],
        source_sha256="a" * 64,
        reviewer_notes="不适合裁剪",
        source_video_reference="data/01_videos/video_0001.mp4",
        visibility_checks=_all_visible(),
    )

    assert decision["margins"] == {key: 0.0 for key in app.MARGIN_KEYS}
    assert decision["normalized_box"] == {
        "x": 0.0,
        "y": 0.0,
        "width": 1.0,
        "height": 1.0,
    }
    assert decision["pixel_box"] == {"x": 0, "y": 0, "width": 456, "height": 670}
    assert decision["reviewer_notes"] == "不适合裁剪"
    assert decision["source_video_path"] == "data/01_videos/video_0001.mp4"
    assert decision["visibility_checks"] == _all_visible()
    assert decision["target_aspect_ratio"] == "3:4"
    assert decision["aspect_ratio_strategy"] == "pad_to_target"


def test_fixed_roi_decision_saves_effective_three_by_four_box(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")
    requested = {"top": 0.05, "right": 0.165, "bottom": 0.1, "left": 0.28}

    decision = app.build_decision(
        video_id="video_0001",
        video_path=video,
        mode=app.MODE_FIXED,
        review_status=app.STATUS_APPROVED,
        margins=requested,
        source_width=456,
        source_height=670,
        reviewed_timestamps=[0.0, 20.0],
        source_sha256="f" * 64,
        visibility_checks=_all_visible(),
    )

    assert decision["requested_margins"] == requested
    assert decision["pixel_box"]["width"] * 4 == decision["pixel_box"]["height"] * 3
    assert decision["target_aspect_ratio"] == "3:4"
    assert decision["aspect_ratio_strategy"] == "crop_exact"
    assert decision["roi_policy_version"] == "1.2"


def test_drag_box_is_the_authoritative_saved_geometry(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")
    dragged = {"x": 24, "y": 31, "width": 432, "height": 576}
    margins = app._margins_from_pixel_box(dragged, 456, 670)

    decision = app.build_decision(
        video_id="video_0001",
        video_path=video,
        mode=app.MODE_FIXED,
        review_status=app.STATUS_APPROVED,
        margins=margins,
        pixel_box_override=dragged,
        source_width=456,
        source_height=670,
        reviewed_timestamps=[0.0, 20.0],
        source_sha256="1" * 64,
        visibility_checks=_all_visible(),
    )

    assert decision["pixel_box"] == dragged
    assert decision["interaction_mode"] == "drag_box"
    assert decision["requested_margins"] == decision["margins"]


def test_old_policy_decision_is_counted_as_outdated():
    videos = [{"video_id": "video_0001"}]
    decisions = {
        "video_0001": {
            "source_video_id": "video_0001",
            "review_status": app.STATUS_APPROVED,
            "roi_policy_version": "1.0",
        }
    }

    counts = app._decision_counts(videos, decisions)

    assert counts["approved"] == 0
    assert counts["outdated_policy"] == 1


def test_fixed_roi_cannot_be_all_zero(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")

    with pytest.raises(app.RoiValidationError, match="no_crop"):
        app.build_decision(
            video_id="video_0001",
            video_path=video,
            mode=app.MODE_FIXED,
            review_status=app.STATUS_APPROVED,
            margins={key: 0.0 for key in app.MARGIN_KEYS},
            source_width=456,
            source_height=670,
            reviewed_timestamps=[0.0],
            source_sha256="b" * 64,
        )


def test_needs_review_can_preserve_empty_reviewed_timestamps(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")

    decision = app.build_decision(
        video_id="video_0001",
        video_path=video,
        mode=app.MODE_FIXED,
        review_status=app.STATUS_NEEDS_REVIEW,
        margins={"top": 0.1, "right": 0.0, "bottom": 0.0, "left": 0.0},
        source_width=456,
        source_height=670,
        reviewed_timestamps=[],
        source_sha256="c" * 64,
    )

    assert decision["reviewed_timestamps"] == []


def test_approved_decision_requires_reviewed_timestamps(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")

    with pytest.raises(app.RoiValidationError, match="关键时间点"):
        app.build_decision(
            video_id="video_0001",
            video_path=video,
            mode=app.MODE_NO_CROP,
            review_status=app.STATUS_APPROVED,
            margins={key: 0.0 for key in app.MARGIN_KEYS},
            source_width=456,
            source_height=670,
            reviewed_timestamps=[],
            source_sha256="d" * 64,
            visibility_checks=_all_visible(),
        )


def test_approved_decision_requires_all_visibility_checks(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")
    checks = _all_visible()
    checks["root_break_judgable"] = False

    with pytest.raises(app.RoiValidationError, match="root_break_judgable"):
        app.build_decision(
            video_id="video_0001",
            video_path=video,
            mode=app.MODE_NO_CROP,
            review_status=app.STATUS_APPROVED,
            margins={key: 0.0 for key in app.MARGIN_KEYS},
            source_width=456,
            source_height=670,
            reviewed_timestamps=[0.0, 20.0],
            source_sha256="e" * 64,
            visibility_checks=checks,
        )


def test_save_payload_preserves_multiple_decisions_atomically(tmp_path: Path):
    output = tmp_path / "roi.json"
    metadata = tmp_path / "video_meta.json"
    decisions = {
        "video_0002": {"source_video_id": "video_0002", "mode": app.MODE_NO_CROP},
        "video_0001": {"source_video_id": "video_0001", "mode": app.MODE_FIXED},
    }

    app.save_roi_payload(output, decisions, metadata_path=metadata)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == app.SCHEMA_VERSION
    assert payload["decision_count"] == 2
    assert [item["source_video_id"] for item in payload["decisions"]] == [
        "video_0001",
        "video_0002",
    ]
    assert list(tmp_path.glob("*.tmp")) == []


# --- TODO #10: _parse_args 默认 --metadata 必须解析 source_snapshots LATEST ---


def _staging_app_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path]:
    """构造 workspace/data-staging/run10/data 上下文并隔离 app.PROJECT_ROOT。

    返回 (data_root, source_snapshots collection_dir)。
    """
    project_root = tmp_path / "proj"
    data_root = project_root / "workspace" / "data-staging" / "run10" / "data"
    collection = data_root / "derived" / "metadata" / "source_snapshots"
    collection.mkdir(parents=True)
    monkeypatch.setattr(app, "PROJECT_ROOT", project_root)
    return data_root, collection


def _add_source_snapshot(collection: Path, artifact_id: str) -> None:
    artifact_dir = collection / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "video_meta.json").write_text("[]", encoding="utf-8")
    artifact_index.append_entry(
        collection,
        {
            "id": artifact_id,
            "created_at": artifact_index.utc_now(),
            "step": "source",
            "inputs": {},
            "stats": {},
        },
    )


def test_parse_args_default_metadata_resolves_source_snapshots_latest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """TODO #10-A: 未显式 --metadata 时解析 LATEST 的 video_meta.json。"""
    data_root, collection = _staging_app_context(monkeypatch, tmp_path)
    artifact_id = "source-abcdef123456"
    _add_source_snapshot(collection, artifact_id)
    artifact_resolver.update_latest(collection, artifact_id)

    args = app._legacy_parse_args(["--data-root", str(data_root)])

    assert args.metadata == collection / artifact_id / "video_meta.json"
    # 失效遗留路径不得再作为默认
    assert args.metadata != data_root / "derived" / "metadata" / "video_meta.json"


def test_parse_args_explicit_metadata_path_passes_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """TODO #10-B①: 显式文件路径原样透传（既有行为 characterization 基线）。"""
    data_root, _ = _staging_app_context(monkeypatch, tmp_path)
    explicit = tmp_path / "custom" / "video_meta.json"
    explicit.parent.mkdir(parents=True)
    explicit.write_text("[]", encoding="utf-8")

    args = app._legacy_parse_args(
        ["--data-root", str(data_root), "--metadata", str(explicit)]
    )

    assert args.metadata == explicit


def test_parse_args_metadata_snapshot_id_prefix_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """TODO #10-B②: --metadata <快照 ID 短前缀> 解析到其 video_meta.json。"""
    data_root, collection = _staging_app_context(monkeypatch, tmp_path)
    artifact_id = "source-abcdef123456"
    _add_source_snapshot(collection, artifact_id)

    args = app._legacy_parse_args(
        ["--data-root", str(data_root), "--metadata", "abcdef"]
    )

    assert args.metadata == collection / artifact_id / "video_meta.json"


def test_parse_args_without_latest_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """TODO #10-B③: 集合无 LATEST 时 fail-closed，不静默回退旧路径。"""
    data_root, collection = _staging_app_context(monkeypatch, tmp_path)
    _add_source_snapshot(collection, "source-abcdef123456")

    with pytest.raises(ValueError, match="LATEST"):
        app._legacy_parse_args(["--data-root", str(data_root)])


def test_parse_args_ambiguous_metadata_prefix_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """TODO #10-B③: ID 前缀歧义时报错，不静默取第一个。"""
    data_root, collection = _staging_app_context(monkeypatch, tmp_path)
    _add_source_snapshot(collection, "source-abcdef111111")
    _add_source_snapshot(collection, "source-abcdef222222")

    with pytest.raises(ValueError, match="多义"):
        app._legacy_parse_args(
            ["--data-root", str(data_root), "--metadata", "abcdef"]
        )


def test_source_state_change_invalidates_existing_decision(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"version-one")
    decision = app.source_state(video)
    assert app.source_state_matches(decision, video)

    video.write_bytes(b"version-two-is-longer")

    assert not app.source_state_matches(decision, video)


@pytest.mark.parametrize("missing", ["--metadata", "--output", "--project-root"])
def test_explicit_roi_entry_rejects_missing_paths(tmp_path, monkeypatch, missing):
    monkeypatch.setattr(app, "data_context_from_arg", lambda *a: pytest.fail("legacy root selected"))
    values = {"--metadata": tmp_path / "video_meta.json", "--output": tmp_path / "roi.json", "--project-root": tmp_path}
    values["--metadata"].write_text("[]")
    argv = [item for key, value in values.items() if key != missing for item in (key, str(value))]
    with pytest.raises(SystemExit) as exc:
        app._parse_args(argv)
    assert exc.value.code == 2


def test_explicit_roi_entry_never_resolves_legacy_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "data_context_from_arg", lambda *a: pytest.fail("legacy root selected"))
    monkeypatch.setattr(app.artifact_resolver, "resolve_cli_artifact_path", lambda *a, **kw: pytest.fail("legacy identity selected"))
    metadata = tmp_path / "video_meta.json"
    metadata.write_text("[]")
    args = app._parse_args(["--metadata", str(metadata), "--output", str(tmp_path / "roi.json"), "--project-root", str(tmp_path)])
    assert args.metadata == metadata
    assert args.output == tmp_path / "roi.json"
    assert args.project_root == tmp_path


def test_roi_import_does_not_select_current_data():
    import subprocess
    import sys
    code = "import pipeline.current_data as current; current.current_data_paths = lambda *a: (_ for _ in ()).throw(AssertionError('import selected current data')); import pipeline.scripts.roi_annotation_app"
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", ["missing_metadata", "missing_root", "overwrite_input"])
def test_explicit_roi_entry_rejects_invalid_paths(tmp_path, case):
    metadata = tmp_path / "video_meta.json"
    metadata.write_text("[]")
    output = metadata if case == "overwrite_input" else tmp_path / "roi.json"
    root = tmp_path / "absent" if case == "missing_root" else tmp_path
    if case == "missing_metadata":
        metadata = tmp_path / "source-prefix"
    with pytest.raises(SystemExit) as exc:
        app._parse_args(["--metadata", str(metadata), "--output", str(output), "--project-root", str(root)])
    assert exc.value.code == 2
    assert (tmp_path / "video_meta.json").read_text() == "[]"
