import pytest

from pipeline.v4_1_labels import (
    canonicalize_v4_1_labels,
    incipient_labels,
    validate_v4_1_labels,
)


def label(state="未断裂", mechanism=None, site=None, special=None):
    return {
        "clip_state": state,
        "fracture_mechanism": mechanism,
        "fracture_site": site,
        "special_case": special,
    }


def test_stable_negative_still_requires_null_fields():
    assert validate_v4_1_labels(label()).valid
    assert not validate_v4_1_labels(label(site="inside_gauge")).valid


def test_incipient_ductile_allows_independent_predictions():
    assert canonicalize_v4_1_labels(
        label("临界未断裂", "韧性断裂", "inside_gauge")
    )["fracture_site"] == "inside_gauge"
    assert validate_v4_1_labels(label("临界未断裂", None, None)).valid


def test_incipient_rejects_non_ductile_and_special_case():
    with pytest.raises(ValueError, match="韧性"):
        canonicalize_v4_1_labels(label("临界未断裂", "脆性断裂"))
    assert not validate_v4_1_labels(
        label("临界未断裂", special="视频异常")
    ).valid


def test_incipient_location_proposal_maps_known_source_location():
    assert incipient_labels("inside_gauge")["fracture_site"] == "inside_gauge"
    assert (
        incipient_labels("outside_gauge")["fracture_site"]
        == "outside_gauge_non_root"
    )
    assert incipient_labels(None)["fracture_site"] is None
