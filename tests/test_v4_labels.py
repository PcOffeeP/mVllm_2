import pytest

from pipeline.v4_labels import (
    canonicalize_v4_labels,
    fracture_site_severity,
    migrate_v3_labels,
    validate_v4_labels,
)


def v3_labels(root_break=False, location="inside_gauge"):
    return {
        "clip_state": "发生断裂",
        "fracture_mechanism": "韧性断裂",
        "root_break": root_break,
        "location": location,
        "special_case": None,
    }


@pytest.mark.parametrize(
    ("root_break", "location", "expected"),
    [
        (False, "inside_gauge", "inside_gauge"),
        (False, "outside_gauge", "outside_gauge_non_root"),
        (True, "outside_gauge", "grip_root"),
        (None, None, None),
    ],
)
def test_migrate_v3_complete_site_combinations(root_break, location, expected):
    result = migrate_v3_labels(v3_labels(root_break, location))
    assert result.labels["fracture_site"] == expected
    assert not result.requires_review


def test_migrate_v3_conflicting_site_fails():
    with pytest.raises(ValueError, match="冲突"):
        migrate_v3_labels(v3_labels(True, "inside_gauge"))


def test_migrate_v3_incomplete_site_is_null_and_flagged():
    result = migrate_v3_labels(v3_labels(None, "outside_gauge"))
    assert result.labels["fracture_site"] is None
    assert result.requires_review


def test_v4_rejects_old_fields_and_negative_fracture_data():
    old = v3_labels()
    assert not validate_v4_labels(old).valid
    negative = {
        "clip_state": "未断裂",
        "fracture_mechanism": None,
        "fracture_site": "inside_gauge",
        "special_case": None,
    }
    with pytest.raises(ValueError, match="未断裂"):
        canonicalize_v4_labels(negative)


def test_special_case_requires_unknown_and_null_summary():
    labels = {
        "clip_state": "无法判断",
        "fracture_mechanism": None,
        "fracture_site": None,
        "special_case": "视频异常",
    }
    assert canonicalize_v4_labels(labels) == labels


@pytest.mark.parametrize(
    ("site", "severity"),
    [
        ("inside_gauge", "acceptable"),
        ("outside_gauge_non_root", "unfavorable"),
        ("grip_root", "severe_unfavorable"),
        (None, "unavailable"),
    ],
)
def test_fracture_site_severity(site, severity):
    assert fracture_site_severity(site) == severity
