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

    # --- has_fracture=None: all fields forced None ---------------------------

    def test_null_all_fields_forced_none(self) -> None:
        raw = {
            "has_fracture": None,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        normalized, repairs = normalize_structured_output(raw, FRAME_COUNT)
        assert normalized["has_fracture"] is None
        assert normalized["fracture_between"] is None
        assert normalized["type"] is None
        assert normalized["location"] is None
        assert len(repairs) > 0

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
            "type": None,
            "location": None,
        }
        assert validate_structured_output(d, FRAME_COUNT) is True

    def test_missing_key_returns_false(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            # missing "location"
        }
        assert validate_structured_output(d, FRAME_COUNT) is False

    @pytest.mark.parametrize("missing_key", ["has_fracture", "fracture_between", "type", "location"])
    def test_missing_any_required_key_returns_false(self, missing_key: str) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [2, 3],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        del d[missing_key]
        assert validate_structured_output(d, FRAME_COUNT) is False

    def test_has_fracture_none_with_non_none_type_returns_false(self) -> None:
        d = {
            "has_fracture": None,
            "fracture_between": None,
            "type": "韧性断裂",
            "location": None,
        }
        assert validate_structured_output(d, FRAME_COUNT) is False

    def test_invalid_interval_returns_false(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": [7, 8],
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
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

    def test_true_fracture_between_only_returns_true(self) -> None:
        d = {
            "has_fracture": True,
            "fracture_between": None,
            "type": "韧性断裂",
            "location": "inside_gauge",
        }
        assert needs_retry(d) is True

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
