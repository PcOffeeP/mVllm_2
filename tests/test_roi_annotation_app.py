from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_source_state_change_invalidates_existing_decision(tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"version-one")
    decision = app.source_state(video)
    assert app.source_state_matches(decision, video)

    video.write_bytes(b"version-two-is-longer")

    assert not app.source_state_matches(decision, video)
