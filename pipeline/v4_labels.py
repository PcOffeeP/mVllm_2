"""Pure label contract helpers for the visual-only tensile VLM v4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pipeline.v3_labels import (
    CLIP_STATES,
    FRACTURE_MECHANISMS,
    SPECIAL_CASES,
    validate_v3_labels,
)

LABEL_SCHEMA_VERSION = "tensile-label/v4"

V4_LABEL_FIELDS = (
    "clip_state",
    "fracture_mechanism",
    "fracture_site",
    "special_case",
)

FRACTURE_SITES = frozenset(
    {"inside_gauge", "outside_gauge_non_root", "grip_root"}
)


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
class V3MigrationResult:
    labels: dict[str, Any]
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def requires_review(self) -> bool:
        return bool(self.issues)


def validate_v4_labels(labels: Mapping[str, Any] | Any) -> ValidationResult:
    """Validate exact fields, enums, and v4 cross-field rules."""
    issues: list[ValidationIssue] = []
    if not isinstance(labels, Mapping):
        return ValidationResult(
            (ValidationIssue("$", "not_object", "标签必须是 JSON 对象"),)
        )

    actual = set(labels)
    expected = set(V4_LABEL_FIELDS)
    for field in sorted(expected - actual):
        issues.append(ValidationIssue(field, "missing_field", "缺少字段"))
    for field in sorted(actual - expected):
        issues.append(ValidationIssue(field, "extra_field", "不允许额外字段"))
    if actual != expected:
        return ValidationResult(tuple(issues))

    clip_state = labels["clip_state"]
    mechanism = labels["fracture_mechanism"]
    fracture_site = labels["fracture_site"]
    special_case = labels["special_case"]

    if clip_state not in CLIP_STATES:
        issues.append(
            ValidationIssue("clip_state", "invalid_enum", f"必须是 {sorted(CLIP_STATES)} 之一")
        )
    if mechanism is not None and mechanism not in FRACTURE_MECHANISMS:
        issues.append(
            ValidationIssue(
                "fracture_mechanism",
                "invalid_enum",
                f"必须是 {sorted(FRACTURE_MECHANISMS)} 之一或 null",
            )
        )
    if fracture_site is not None and fracture_site not in FRACTURE_SITES:
        issues.append(
            ValidationIssue(
                "fracture_site",
                "invalid_enum",
                f"必须是 {sorted(FRACTURE_SITES)} 之一或 null",
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

    if clip_state == "未断裂":
        for field, value in (
            ("fracture_mechanism", mechanism),
            ("fracture_site", fracture_site),
            ("special_case", special_case),
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
            ("fracture_site", fracture_site),
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


def canonicalize_v4_labels(labels: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_v4_labels(labels)
    result.raise_for_errors()
    return {field: labels[field] for field in V4_LABEL_FIELDS}


def migrate_v3_labels(labels: Mapping[str, Any]) -> V3MigrationResult:
    """Map a valid v3 label object without guessing incomplete site evidence."""
    validation = validate_v3_labels(labels)
    validation.raise_for_errors()
    root_break = labels["root_break"]
    location = labels["location"]
    issues: list[ValidationIssue] = []

    if root_break is False and location == "inside_gauge":
        fracture_site = "inside_gauge"
    elif root_break is False and location == "outside_gauge":
        fracture_site = "outside_gauge_non_root"
    elif root_break is True and location == "outside_gauge":
        fracture_site = "grip_root"
    elif root_break is None and location is None:
        fracture_site = None
    elif root_break is True and location == "inside_gauge":
        raise ValueError("v3 root_break=true 与 location=inside_gauge 冲突")
    else:
        fracture_site = None
        issues.append(
            ValidationIssue(
                "fracture_site",
                "incomplete_v3_site",
                "v3 齐根与位置证据不完整，未猜测 v4 断裂部位",
            )
        )

    migrated = canonicalize_v4_labels(
        {
            "clip_state": labels["clip_state"],
            "fracture_mechanism": labels["fracture_mechanism"],
            "fracture_site": fracture_site,
            "special_case": labels["special_case"],
        }
    )
    return V3MigrationResult(migrated, tuple(issues))


def fracture_site_severity(fracture_site: str | None) -> str:
    mapping = {
        "inside_gauge": "acceptable",
        "outside_gauge_non_root": "unfavorable",
        "grip_root": "severe_unfavorable",
        None: "unavailable",
    }
    if fracture_site not in mapping:
        raise ValueError(f"未知 fracture_site: {fracture_site}")
    return mapping[fracture_site]
