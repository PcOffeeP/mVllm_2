"""Pure label contract helpers for the visual-only tensile VLM v3.

This module intentionally has no dependency on the v2 production contract.
It validates proposed/reviewed labels and derives a *candidate* clip state
from source timing evidence.  Human review remains the final authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping

LABEL_SCHEMA_VERSION = "tensile-label/v3"

V3_LABEL_FIELDS = (
    "clip_state",
    "fracture_mechanism",
    "root_break",
    "location",
    "special_case",
)

CLIP_STATES = frozenset({"未断裂", "发生断裂", "已断裂", "无法判断"})
FRACTURE_MECHANISMS = frozenset(
    {"韧性断裂", "脆性断裂", "界面脱粘", "爆炸性断裂", "半脆半韧断裂"}
)
LOCATIONS = frozenset({"inside_gauge", "outside_gauge"})
SPECIAL_CASES = frozenset({"未夹紧", "视频异常"})

SOURCE_FRACTURE = "fracture"
SOURCE_NO_FRACTURE = "no_fracture"
SOURCE_UNCLAMPED = "unclamped"
SOURCE_VIDEO_ABNORMAL = "video_abnormal"
SOURCE_KINDS = frozenset(
    {
        SOURCE_FRACTURE,
        SOURCE_NO_FRACTURE,
        SOURCE_UNCLAMPED,
        SOURCE_VIDEO_ABNORMAL,
    }
)

_LEGACY_TYPE_MAP: dict[str, tuple[str | None, bool | None]] = {
    "韧性": ("韧性断裂", False),
    "韧性断裂": ("韧性断裂", False),
    "脆性": ("脆性断裂", False),
    "脆性断裂": ("脆性断裂", False),
    "界面脱粘": ("界面脱粘", False),
    "齐根": (None, True),
    "齐根断裂": (None, True),
    "爆炸性": ("爆炸性断裂", False),
    "爆炸性断裂": ("爆炸性断裂", False),
    "半脆半韧": ("半脆半韧断裂", False),
    "半脆半韧断裂": ("半脆半韧断裂", False),
    "界面脱粘、齐根": ("界面脱粘", True),
    "界面脱粘、齐根断裂": ("界面脱粘", True),
    "脆性、齐根": ("脆性断裂", True),
    "脆性、齐根断裂": ("脆性断裂", True),
}


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues

    def raise_for_errors(self) -> None:
        if self.issues:
            details = "; ".join(f"{item.field}: {item.message}" for item in self.issues)
            raise ValueError(f"非法 {LABEL_SCHEMA_VERSION} 标签: {details}")


@dataclass(frozen=True)
class LegacyMappingResult:
    fracture_mechanism: str | None
    root_break: bool | None
    matched: bool
    source_value: str | None


@dataclass(frozen=True)
class ClipStateResult:
    clip_state: str
    reason: str
    event_time: float | None
    guard_seconds: float
    sampled_timestamps: tuple[float, ...]


def map_legacy_fracture_type(value: Any) -> LegacyMappingResult:
    """Map a legacy combined fracture type without inventing a match."""
    if not isinstance(value, str):
        return LegacyMappingResult(None, None, False, value if value is None else str(value))
    normalized = value.strip()
    mapped = _LEGACY_TYPE_MAP.get(normalized)
    if mapped is None:
        return LegacyMappingResult(None, None, False, normalized)
    return LegacyMappingResult(mapped[0], mapped[1], True, normalized)


def validate_v3_labels(labels: Mapping[str, Any] | Any) -> ValidationResult:
    """Validate exact fields, enums, strict booleans, and cross-field rules."""
    issues: list[ValidationIssue] = []
    if not isinstance(labels, Mapping):
        return ValidationResult(
            (ValidationIssue("$", "not_object", "标签必须是 JSON 对象"),)
        )

    actual = set(labels)
    expected = set(V3_LABEL_FIELDS)
    for field in sorted(expected - actual):
        issues.append(ValidationIssue(field, "missing_field", "缺少字段"))
    for field in sorted(actual - expected):
        issues.append(ValidationIssue(field, "extra_field", "不允许额外字段"))
    if actual != expected:
        return ValidationResult(tuple(issues))

    clip_state = labels["clip_state"]
    mechanism = labels["fracture_mechanism"]
    root_break = labels["root_break"]
    location = labels["location"]
    special_case = labels["special_case"]

    if clip_state not in CLIP_STATES:
        issues.append(
            ValidationIssue(
                "clip_state",
                "invalid_enum",
                f"必须是 {sorted(CLIP_STATES)} 之一",
            )
        )
    if mechanism is not None and mechanism not in FRACTURE_MECHANISMS:
        issues.append(
            ValidationIssue(
                "fracture_mechanism",
                "invalid_enum",
                f"必须是 {sorted(FRACTURE_MECHANISMS)} 之一或 null",
            )
        )
    if root_break is not None and type(root_break) is not bool:
        issues.append(
            ValidationIssue("root_break", "invalid_type", "必须是布尔值或 null")
        )
    if location is not None and location not in LOCATIONS:
        issues.append(
            ValidationIssue(
                "location",
                "invalid_enum",
                f"必须是 {sorted(LOCATIONS)} 之一或 null",
            )
        )
    if special_case is not None and special_case not in SPECIAL_CASES:
        issues.append(
            ValidationIssue(
                "special_case",
                "invalid_enum",
                f"必须是 {sorted(SPECIAL_CASES)} 之一或 null",
            )
        )

    # Cross-field checks only run when the controlling enum is valid.
    if clip_state == "未断裂":
        for field, value in (
            ("fracture_mechanism", mechanism),
            ("root_break", root_break),
            ("location", location),
        ):
            if value is not None:
                issues.append(
                    ValidationIssue(
                        field,
                        "fracture_info_on_negative",
                        "未断裂片段不能携带片段级断裂信息",
                    )
                )
    if special_case in SPECIAL_CASES:
        if clip_state != "无法判断":
            issues.append(
                ValidationIssue(
                    "clip_state",
                    "special_case_requires_unknown",
                    "特殊情况的片段状态必须为“无法判断”",
                )
            )
        for field, value in (
            ("fracture_mechanism", mechanism),
            ("root_break", root_break),
            ("location", location),
        ):
            if value is not None:
                issues.append(
                    ValidationIssue(
                        field,
                        "fracture_info_on_special_case",
                        "特殊情况不能自动携带片段级断裂信息",
                    )
                )

    return ValidationResult(tuple(issues))


def canonicalize_v3_labels(labels: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return fields in the stable contract order."""
    result = validate_v3_labels(labels)
    result.raise_for_errors()
    return {field: labels[field] for field in V3_LABEL_FIELDS}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


def _timestamps(values: Iterable[Any]) -> tuple[float, ...] | None:
    try:
        result = tuple(_finite_number(value) for value in values)
    except TypeError:
        return None
    if not result or any(value is None for value in result):
        return None
    return tuple(value for value in result if value is not None)


def derive_clip_state(
    source_kind: str,
    event_time: Any,
    sampled_timestamps: Iterable[Any],
    guard_seconds: float = 0.5,
) -> ClipStateResult:
    """Derive a candidate state from decoded-frame timestamps.

    The safety band applies to stable pre/post clips. A transition clip must
    contain at least one sample strictly before T and one sample at/after T.
    """
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"未知 source_kind: {source_kind!r}")
    guard = _finite_number(guard_seconds)
    if guard is None or guard < 0:
        raise ValueError("guard_seconds 必须是非负有限数")
    timestamps = _timestamps(sampled_timestamps)
    if timestamps is None:
        return ClipStateResult("无法判断", "invalid_or_empty_timestamps", None, guard, ())

    if source_kind == SOURCE_UNCLAMPED:
        return ClipStateResult("无法判断", "unclamped_source", None, guard, timestamps)
    if source_kind == SOURCE_VIDEO_ABNORMAL:
        return ClipStateResult("无法判断", "video_abnormal_source", None, guard, timestamps)
    if source_kind == SOURCE_NO_FRACTURE:
        return ClipStateResult("未断裂", "normal_no_fracture_source", None, guard, timestamps)

    event = _finite_number(event_time)
    if event is None:
        return ClipStateResult(
            "无法判断", "missing_or_invalid_event_time", None, guard, timestamps
        )
    if all(timestamp <= event - guard for timestamp in timestamps):
        return ClipStateResult("未断裂", "all_samples_before_safety_band", event, guard, timestamps)
    if all(timestamp >= event + guard for timestamp in timestamps):
        return ClipStateResult("已断裂", "all_samples_after_safety_band", event, guard, timestamps)
    if any(timestamp < event for timestamp in timestamps) and any(
        timestamp >= event for timestamp in timestamps
    ):
        return ClipStateResult("发生断裂", "samples_bracket_event", event, guard, timestamps)
    return ClipStateResult("无法判断", "samples_inside_event_safety_band", event, guard, timestamps)

