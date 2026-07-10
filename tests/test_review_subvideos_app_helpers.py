"""Tests for review_subvideos_app helper functions.

These tests focus on the risk-level calculation logic used by the review UI.
They do not require a running Streamlit app.
"""

from __future__ import annotations

from pipeline.scripts import review_subvideos_app as app


def _make_subvideo(
    *,
    subvideo_id: str = "sv1",
    crop_type: str = "full_pos",
    has_fracture: bool | None = True,
    has_fracture_canonical: bool | None = True,
    sub_type: str = "韧性断裂",
    source_type: str = "韧性断裂",
    is_abnormal: bool = False,
    fracture_between: list[int] | None = None,
    mapping: list[dict] | None = None,
) -> dict:
    """Build a minimal subvideo metadata dict for risk tests."""
    if mapping is None:
        mapping = [
            {"input_index": i, "original_frame": i * 10, "timestamp": float(i)}
            for i in range(8)
        ]
    return {
        "subvideo_id": subvideo_id,
        "source_video": "video_0001",
        "crop_type": crop_type,
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture_canonical,
        "type": sub_type,
        "source_type": source_type,
        "is_abnormal": is_abnormal,
        "fracture_between": fracture_between,
        "actual_frame_mapping": mapping,
    }


def test_risk_high_for_abnormal_video():
    sub = _make_subvideo(is_abnormal=True, has_fracture_canonical=None)
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_HIGH
    assert any("is_abnormal" in r for r in reasons)


def test_risk_high_for_anomaly_type():
    sub = _make_subvideo(
        crop_type="full_anomaly_presence_unknown",
        sub_type="视频异常",
        source_type="视频异常",
        has_fracture=None,
        has_fracture_canonical=None,
    )
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_HIGH
    assert any("视频异常" in r for r in reasons)


def test_risk_high_for_canonical_none():
    sub = _make_subvideo(has_fracture_canonical=None)
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_HIGH
    assert any("None" in r for r in reasons)


def test_risk_high_for_label_conflict():
    sub = _make_subvideo(has_fracture=True, has_fracture_canonical=False)
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_HIGH
    assert any("不一致" in r for r in reasons)


def test_risk_high_for_full_video_source_conflict():
    sub = _make_subvideo(
        crop_type="full_neg",
        has_fracture=False,
        has_fracture_canonical=False,
        sub_type="未断裂",
        source_type="韧性断裂",
    )
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_HIGH
    assert any("源视频类型" in r for r in reasons)


def test_risk_medium_for_unclamped_with_fracture():
    sub = _make_subvideo(sub_type="未夹紧", source_type="未夹紧")
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_MEDIUM
    assert any("未夹紧" in r for r in reasons)


def test_risk_medium_for_missing_fracture_between():
    sub = _make_subvideo(fracture_between=None)
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_MEDIUM
    assert any("缺少 fracture_between" in r for r in reasons)


def test_risk_medium_for_start_boundary():
    sub = _make_subvideo(fracture_between=[0, 1])
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_MEDIUM
    assert any("起始边界" in r for r in reasons)


def test_risk_medium_for_end_boundary():
    sub = _make_subvideo(fracture_between=[6, 7])
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_MEDIUM
    assert any("结束边界" in r for r in reasons)


def test_risk_low_for_normal_positive():
    sub = _make_subvideo(fracture_between=[3, 4])
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_LOW
    assert reasons == ["标签与类型一致，未见明显异常"]


def test_risk_low_for_normal_negative():
    sub = _make_subvideo(
        crop_type="neg_before",
        has_fracture=False,
        has_fracture_canonical=False,
        sub_type="未断裂",
        source_type="韧性断裂",
        fracture_between=None,
    )
    risk, reasons = app.compute_subvideo_risk(sub)
    assert risk == app.RISK_LOW


def test_format_option_includes_risk():
    sub = _make_subvideo(subvideo_id="sv_high", is_abnormal=True, has_fracture_canonical=None)
    decisions = {"sv_high": {"status": None}}
    text = app._format_option(sub, decisions)
    assert app.RISK_LABELS[app.RISK_HIGH] in text
    assert "sv_high" in text


def test_format_option_includes_status():
    sub = _make_subvideo(subvideo_id="sv_approved", fracture_between=[3, 4])
    decisions = {"sv_approved": {"status": app.STATUS_APPROVED}}
    text = app._format_option(sub, decisions)
    assert app.STATUS_EMOJI[app.STATUS_APPROVED] in text or app.STATUS_LABELS[app.STATUS_APPROVED] in text
    assert app.RISK_LABELS[app.RISK_LOW] in text
