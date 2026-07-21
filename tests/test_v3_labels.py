import pytest

from pipeline.v3_labels import (
    LABEL_SCHEMA_VERSION,
    SOURCE_FRACTURE,
    SOURCE_NO_FRACTURE,
    SOURCE_UNCLAMPED,
    SOURCE_VIDEO_ABNORMAL,
    canonicalize_v3_labels,
    derive_clip_state,
    map_legacy_fracture_type,
    validate_v3_labels,
)


@pytest.mark.parametrize(
    ("old_type", "mechanism", "root_break"),
    [
        ("韧性断裂", "韧性断裂", False),
        ("脆性断裂", "脆性断裂", False),
        ("界面脱粘", "界面脱粘", False),
        ("齐根断裂", None, True),
        ("爆炸性断裂", "爆炸性断裂", False),
        ("半脆半韧断裂", "半脆半韧断裂", False),
        ("界面脱粘、齐根断裂", "界面脱粘", True),
        ("脆性、齐根断裂", "脆性断裂", True),
    ],
)
def test_maps_legacy_types(old_type, mechanism, root_break):
    result = map_legacy_fracture_type(old_type)
    assert result.matched is True
    assert result.fracture_mechanism == mechanism
    assert result.root_break is root_break


def test_unknown_legacy_type_is_not_invented():
    result = map_legacy_fracture_type("其他")
    assert result.matched is False
    assert result.fracture_mechanism is None
    assert result.root_break is None


def test_canonicalizes_exact_five_fields_in_contract_order():
    labels = {
        "location": "inside_gauge",
        "clip_state": "发生断裂",
        "special_case": None,
        "root_break": True,
        "fracture_mechanism": "界面脱粘",
    }
    assert LABEL_SCHEMA_VERSION == "tensile-label/v3"
    assert list(canonicalize_v3_labels(labels)) == [
        "clip_state",
        "fracture_mechanism",
        "root_break",
        "location",
        "special_case",
    ]


@pytest.mark.parametrize(
    "labels",
    [
        {
            "clip_state": "未断裂",
            "fracture_mechanism": None,
            "root_break": None,
            "location": None,
            "special_case": None,
        },
        {
            "clip_state": "已断裂",
            "fracture_mechanism": "脆性断裂",
            "root_break": False,
            "location": "outside_gauge",
            "special_case": None,
        },
        {
            "clip_state": "无法判断",
            "fracture_mechanism": None,
            "root_break": None,
            "location": None,
            "special_case": "视频异常",
        },
    ],
)
def test_accepts_legal_labels(labels):
    assert validate_v3_labels(labels).valid


def test_rejects_old_transition_name():
    labels = {
        "clip_state": "断裂发生中",
        "fracture_mechanism": None,
        "root_break": None,
        "location": None,
        "special_case": None,
    }
    result = validate_v3_labels(labels)
    assert not result.valid
    assert any(issue.field == "clip_state" for issue in result.issues)


@pytest.mark.parametrize("value", [0, 1, "true"])
def test_rejects_non_boolean_root_break(value):
    labels = {
        "clip_state": "发生断裂",
        "fracture_mechanism": "韧性断裂",
        "root_break": value,
        "location": "inside_gauge",
        "special_case": None,
    }
    assert not validate_v3_labels(labels).valid


def test_rejects_missing_and_extra_fields():
    result = validate_v3_labels(
        {
            "clip_state": "未断裂",
            "fracture_mechanism": None,
            "root_break": None,
            "location": None,
            "extra": 1,
        }
    )
    assert {issue.code for issue in result.issues} == {"missing_field", "extra_field"}


def test_negative_cannot_carry_fracture_information():
    result = validate_v3_labels(
        {
            "clip_state": "未断裂",
            "fracture_mechanism": "脆性断裂",
            "root_break": False,
            "location": "inside_gauge",
            "special_case": None,
        }
    )
    assert not result.valid
    assert sum(issue.code == "fracture_info_on_negative" for issue in result.issues) == 3


def test_special_case_requires_unknown_state_and_null_fracture_fields():
    result = validate_v3_labels(
        {
            "clip_state": "未断裂",
            "fracture_mechanism": None,
            "root_break": None,
            "location": None,
            "special_case": "未夹紧",
        }
    )
    assert not result.valid
    assert any(issue.code == "special_case_requires_unknown" for issue in result.issues)


def test_derives_stable_pre_event_with_half_second_guard():
    result = derive_clip_state(SOURCE_FRACTURE, 10.0, [1.0, 9.5])
    assert result.clip_state == "未断裂"


def test_derives_stable_post_event_with_half_second_guard():
    result = derive_clip_state(SOURCE_FRACTURE, 10.0, [10.5, 12.0])
    assert result.clip_state == "已断裂"


def test_derives_transition_with_one_sample_on_each_side():
    result = derive_clip_state(SOURCE_FRACTURE, 10.0, [9.9, 10.0])
    assert result.clip_state == "发生断裂"


def test_ambiguous_single_side_inside_guard_is_unknown():
    result = derive_clip_state(SOURCE_FRACTURE, 10.0, [9.6, 9.9])
    assert result.clip_state == "无法判断"


def test_normal_no_fracture_source_is_negative():
    result = derive_clip_state(SOURCE_NO_FRACTURE, None, [0.0, 5.0])
    assert result.clip_state == "未断裂"


@pytest.mark.parametrize("source_kind", [SOURCE_UNCLAMPED, SOURCE_VIDEO_ABNORMAL])
def test_special_sources_are_not_negative(source_kind):
    result = derive_clip_state(source_kind, None, [0.0, 5.0])
    assert result.clip_state == "无法判断"


@pytest.mark.parametrize("timestamps", [[], [float("nan")], ["1.0"]])
def test_invalid_timestamps_are_unknown(timestamps):
    result = derive_clip_state(SOURCE_FRACTURE, 10.0, timestamps)
    assert result.clip_state == "无法判断"


def test_invalid_guard_is_rejected():
    with pytest.raises(ValueError, match="guard_seconds"):
        derive_clip_state(SOURCE_FRACTURE, 10.0, [9.0, 11.0], -0.1)
