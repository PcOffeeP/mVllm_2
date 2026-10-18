"""Tests for pipeline.output_normalizer.

Covers normalize_structured_output, validate_structured_output, and needs_retry.
"""

from __future__ import annotations

import pytest

from pipeline.output_normalizer import (
    normalize_structured_output,
    needs_retry,
    validate_structured_output,
)

FRAME_COUNT = 8

# ---------------------------------------------------------------------------
# normalize_structured_output
# ---------------------------------------------------------------------------


class TestNormalizeStructuredOutput:
    """Cover all normalization rules and value coercions."""

    # --- has_fracture=True: valid values pass through ------------------------

    def test_true_valid_fields_preserved(self) -> None:
        # 旧 v2 记录兼容：raw 里显式带 fracture_between 时行为与移除前一致。
        raw = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["has_fracture"] is True
        assert normalized["fracture_between"] == [2, 3]
        assert normalized["type"] == "韧性断裂"
        assert normalized["location"] == "inside_gauge"
        assert repairs == []

    # --- fracture_between 已不在 v4.1 契约内：raw 无该键时不得凭空产出 ----

    def test_true_raw_without_fracture_between_key_omits_it(self) -> None:
        """v4.1 raw 不含 fracture_between 时，normalized 不得补出该键。"""
        raw = {
            "has_fracture": True,
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert "fracture_between" not in normalized
        assert not any("fracture_between" in r for r in repairs)
        assert normalized["has_fracture"] is True
        assert normalized["type"] == "韧性断裂"
        assert normalized["location"] == "inside_gauge"
        assert repairs == []

    def test_false_raw_without_fracture_between_key_omits_it(self) -> None:
        """has_fracture=False 且 raw 无该键时：缺键且不产生任何 repair。"""
        raw = {
            "has_fracture": False,
            "type": "未断裂",
            "location": None,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert "fracture_between" not in normalized
        assert not any("fracture_between" in r for r in repairs)
        assert repairs == []

    # --- has_fracture=True: None secondary fields stay None ------------------

    def test_true_none_secondary_fields_kept(self) -> None:
        raw = {
            "has_fracture": True,
            "fracture_between": None,
            "type": None,
            "location": None,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["has_fracture"] is True
        assert normalized["fracture_between"] is None
        assert normalized["type"] is None
        assert normalized["location"] is None
        assert repairs == []

    # --- has_fracture=True: invalid type string set to None -----------------

    def test_true_invalid_type_set_to_none(self) -> None:
        raw = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "不存在的类型",
            "location": "inside_gauge",
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["type"] is None
        assert any("type" in r for r in repairs)

    @pytest.mark.parametrize("bad_value", [["韧性断裂"], {"value": "韧性断裂"}])
    def test_true_non_scalar_type_and_location_are_repaired(self, bad_value) -> None:
        raw = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": bad_value,
            "location": bad_value,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["type"] is None
        assert normalized["location"] is None
        assert any("type" in repair for repair in repairs)
        assert any("location" in repair for repair in repairs)

    def test_false_non_scalar_type_is_repaired(self) -> None:
        normalized, repairs = normalize_structured_output(
            {
                "has_fracture": False,
                "fracture_between": None,
                "type": ["未断裂"],
                "location": None,
            },
            FRAME_COUNT,
        )
        assert normalized["type"] == "未断裂"
        assert any("type" in repair for repair in repairs)

    # --- has_fracture=True: out-of-range fracture_between set to None -------

    @pytest.mark.parametrize(
        "bad_interval",
        [
            [-1, 0],
            [7, 8],
            [0, 2],
            [3, 3],
            [2.0, 3.0],
        ],
    )
    def test_true_invalid_fracture_between_set_to_none(self, bad_interval) -> None:
        # 旧 v2 记录兼容：显式带该键时仍按 [i, i+1] 校验并丢弃非法值。
        raw = {
            "has_fracture": True,
            "fracture_between": bad_interval,
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["fracture_between"] is None
        assert any("fracture_between" in r for r in repairs)

    # --- has_fracture=False: type="未断裂" unchanged -------------------------

    def test_false_type_weiduan_unchanged(self) -> None:
        raw = {
            "has_fracture": False,
            "fracture_between": None,
            "type": "未断裂",
            "location": None,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["type"] == "未断裂"
        assert normalized["fracture_between"] is None
        assert normalized["location"] is None
        assert repairs == []

    # --- has_fracture=False: type="未夹紧" unchanged -------------------------

    def test_false_type_weijiajin_unchanged(self) -> None:
        raw = {
            "has_fracture": False,
            "fracture_between": None,
            "type": "未夹紧",
            "location": None,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["type"] == "未夹紧"
        assert repairs == []

    # --- has_fracture=False: fracture type downgraded to "未断裂" ------------

    def test_false_fracture_type_downgraded(self) -> None:
        raw = {
            "has_fracture": False,
            "fracture_between": None,
            "type": "韧性断裂",
            "location": None,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["type"] == "未断裂"
        assert any("未断裂" in r for r in repairs)

    # --- has_fracture=False: non-None fracture_between/location forced None --

    def test_false_extra_fields_forced_none(self) -> None:
        raw = {
            "has_fracture": False,
            "fracture_between": [2, 3],
            "type": "未断裂",
            "location": "inside_gauge",
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["fracture_between"] is None
        assert normalized["location"] is None
        assert any("fracture_between" in r for r in repairs)
        assert any("location" in r for r in repairs)

    # --- has_fracture=None: anomaly type is canonical ------------------------

    def test_null_fields_use_video_anomaly(self) -> None:
        raw = {
            "has_fracture": None,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["has_fracture"] is None
        assert normalized["fracture_between"] is None
        assert normalized["type"] == "视频异常"
        assert normalized["location"] is None
        assert len(repairs) > 0

    def test_null_video_anomaly_is_preserved(self) -> None:
        normalized, repairs = normalize_structured_output(
            {
                "has_fracture": None,
                "fracture_between": None,
                "type": "视频异常",
                "location": None,
            },
            FRAME_COUNT,
        )
        assert normalized == {
            "has_fracture": None,
            "fracture_between": None,
            "type": "视频异常",
            "location": None,
        }
        assert repairs == []

    # --- String interval coercion -------------------------------------------

    def test_string_interval_parsed(self) -> None:
        raw = {
            "has_fracture": True,
            "fracture_between": "[1, 2]",
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["fracture_between"] == [1, 2]
        assert any("string_interval" in r for r in repairs)

    # --- String boolean coercion --------------------------------------------

    @pytest.mark.parametrize(
        ("raw_val", "expected"),
        [
            ("true", True),
            ("false", False),
            ("null", None),
            ("True", True),
            ("False", False),
            ("None", None),
            ("  true  ", True),
            ("", None),
        ],
    )
    def test_string_has_fracture_coerced(self, raw_val, expected) -> None:
        raw = {
            "has_fracture": raw_val,
            "fracture_between": None,
            "type": None,
            "location": None,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["has_fracture"] is expected
        assert any("string coerced" in r for r in repairs)

    # --- Numeric boolean coercion -------------------------------------------

    @pytest.mark.parametrize(
        ("raw_val", "expected"),
        [
            (1, True),
            (0, False),
        ],
    )
    def test_numeric_has_fracture_coerced(self, raw_val, expected) -> None:
        raw = {
            "has_fracture": raw_val,
            "fracture_between": None,
            "type": None,
            "location": None,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["has_fracture"] is expected
        assert any("numeric coerced" in r for r in repairs)

    # --- repair_flags correctness -------------------------------------------

    def test_repair_flags_recorded_per_repair(self) -> None:
        """Multiple issues in one call produce multiple repair flags."""
        raw = {
            "has_fracture": 1,
            "fracture_between": "[5, 6]",
            "type": "不存在的类型",
            "location": None,
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        # 3 repairs: numeric coerced, string interval converted, invalid type
        assert len(repairs) >= 3
        assert normalized["has_fracture"] is True
        assert normalized["fracture_between"] == [5, 6]
        assert normalized["type"] is None


# ---------------------------------------------------------------------------
# validate_structured_output
# ---------------------------------------------------------------------------


class TestValidateStructuredOutput:
    """Cover validity checks on already-normalized dicts."""

    def test_valid_true_returns_true(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        assert validate_structured_output(d, FRAME_COUNT) is True

    def test_valid_false_returns_true(self) -> None:
        d = {
            "has_fracture": False,
            "fracture_between": None,
            "type": "未断裂",
            "location": None,
        }
        assert validate_structured_output(d, FRAME_COUNT) is True

    def test_valid_null_returns_true(self) -> None:
        d = {
            "has_fracture": None,
            "fracture_between": None,
            "type": "视频异常",
            "location": None,
        }
        assert validate_structured_output(d, FRAME_COUNT) is True

    def test_null_without_video_anomaly_returns_false(self) -> None:
        d = {
            "has_fracture": None,
            "fracture_between": None,
            "type": None,
            "location": None,
        }
        assert validate_structured_output(d, FRAME_COUNT) is False

    def test_missing_key_returns_false(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            # missing "location"
        }
        assert validate_structured_output(d, FRAME_COUNT) is False

    @pytest.mark.parametrize("missing_key", ["has_fracture", "type", "location"])
    def test_missing_any_required_key_returns_false(self, missing_key: str) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        del d[missing_key]
        assert validate_structured_output(d, FRAME_COUNT) is False

    def test_missing_fracture_between_is_tolerated_returns_true(self) -> None:
        """v4.1 契约已无 fracture_between：缺该键必须视为合法。"""
        d = {
            "has_fracture": True,
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        assert validate_structured_output(d, FRAME_COUNT) is True

    def test_has_fracture_none_with_non_none_type_returns_false(self) -> None:
        d = {
            "has_fracture": None,
            "fracture_between": None,
            "type": "韧性断裂",
            "location": None,
        }
        assert validate_structured_output(d, FRAME_COUNT) is False

    def test_invalid_interval_returns_false(self) -> None:
        # 旧 v2 记录兼容：显式带该键且区间非法时仍必须被校验。
        d = {
            "has_fracture": True,
            "fracture_between": [7, 8],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        assert validate_structured_output(d, FRAME_COUNT) is False

    @pytest.mark.parametrize("field", ["type", "location"])
    def test_non_scalar_membership_field_returns_false(self, field: str) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        d[field] = ["unexpected"]
        assert validate_structured_output(d, FRAME_COUNT) is False


# ---------------------------------------------------------------------------
# needs_retry
# ---------------------------------------------------------------------------


class TestNeedsRetry:
    """Cover retry logic for incomplete fracture predictions."""

    def test_true_all_secondary_none_returns_true(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": None,
            "type": None,
            "location": None,
        }
        assert needs_retry(d) is True

    def test_true_missing_fracture_between_alone_does_not_trigger_retry(self) -> None:
        # fracture_between 已不在 retry 判据内：仅该字段为 None 不再触发重试。
        d = {
            "has_fracture": True,
            "fracture_between": None,
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        assert needs_retry(d) is False

    def test_true_type_only_none_returns_true(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": None,
            "location": "inside_gauge",
        }
        assert needs_retry(d) is True

    def test_true_location_only_none_returns_true(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": None,
        }
        assert needs_retry(d) is True

    def test_true_all_secondary_present_returns_false(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        assert needs_retry(d) is False

    def test_false_returns_false(self) -> None:
        d = {
            "has_fracture": False,
            "fracture_between": None,
            "type": "未断裂",
            "location": None,
        }
        assert needs_retry(d) is False

    def test_null_returns_false(self) -> None:
        d = {
            "has_fracture": None,
            "fracture_between": None,
            "type": None,
            "location": None,
        }
        assert needs_retry(d) is False
