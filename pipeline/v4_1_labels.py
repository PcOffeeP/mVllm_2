"""Label contract helpers for tensile VLM v4.1 incipient fracture semantics."""

from __future__ import annotations

from typing import Any, Mapping

from pipeline.v3_labels import FRACTURE_MECHANISMS, SPECIAL_CASES
from pipeline.v4_labels import (
    FRACTURE_SITES,
    V4_LABEL_FIELDS,
    ValidationIssue,
    ValidationResult,
    migrate_v3_labels,
)

LABEL_SCHEMA_VERSION = "tensile-label/v4.1"
V4_1_LABEL_FIELDS = V4_LABEL_FIELDS
CLIP_STATES = frozenset(
    {"未断裂", "临界未断裂", "发生断裂", "已断裂", "无法判断"}
)


def validate_v4_1_labels(labels: Mapping[str, Any] | Any) -> ValidationResult:
    issues: list[ValidationIssue] = []
    if not isinstance(labels, Mapping):
        return ValidationResult(
            (ValidationIssue("$", "not_object", "标签必须是 JSON 对象"),)
        )
    actual, expected = set(labels), set(V4_1_LABEL_FIELDS)
    for field in sorted(expected - actual):
        issues.append(ValidationIssue(field, "missing_field", "缺少字段"))
    for field in sorted(actual - expected):
        issues.append(ValidationIssue(field, "extra_field", "不允许额外字段"))
    if actual != expected:
        return ValidationResult(tuple(issues))

    state = labels["clip_state"]
    mechanism = labels["fracture_mechanism"]
    site = labels["fracture_site"]
    special = labels["special_case"]
    if state not in CLIP_STATES:
        issues.append(ValidationIssue("clip_state", "invalid_enum", "非法片段状态"))
    if mechanism is not None and mechanism not in FRACTURE_MECHANISMS:
        issues.append(ValidationIssue("fracture_mechanism", "invalid_enum", "非法断裂机制"))
    if site is not None and site not in FRACTURE_SITES:
        issues.append(ValidationIssue("fracture_site", "invalid_enum", "非法断裂位置"))
    if special is not None and special not in SPECIAL_CASES:
        issues.append(ValidationIssue("special_case", "invalid_enum", "非法特殊情况"))

    if state == "未断裂":
        for field in ("fracture_mechanism", "fracture_site", "special_case"):
            if labels[field] is not None:
                issues.append(
                    ValidationIssue(
                        field,
                        "info_on_stable_negative",
                        "普通未断裂片段的附加字段必须为 null",
                    )
                )
    if state == "临界未断裂":
        if mechanism not in {None, "韧性断裂"}:
            issues.append(
                ValidationIssue(
                    "fracture_mechanism",
                    "non_ductile_incipient",
                    "临界未断裂目前只允许韧性断裂或 null",
                )
            )
        if special is not None:
            issues.append(
                ValidationIssue(
                    "special_case",
                    "special_on_incipient",
                    "临界未断裂不能同时是特殊情况",
                )
            )
    if special in SPECIAL_CASES:
        if state != "无法判断":
            issues.append(
                ValidationIssue(
                    "clip_state",
                    "special_case_requires_unknown",
                    "特殊情况的片段状态必须为“无法判断”",
                )
            )
        for field in ("fracture_mechanism", "fracture_site"):
            if labels[field] is not None:
                issues.append(
                    ValidationIssue(
                        field,
                        "fracture_info_on_special_case",
                        "特殊情况不能携带断裂汇总信息",
                    )
                )
    return ValidationResult(tuple(issues))


def canonicalize_v4_1_labels(labels: Mapping[str, Any]) -> dict[str, Any]:
    result = validate_v4_1_labels(labels)
    result.raise_for_errors()
    return {field: labels[field] for field in V4_1_LABEL_FIELDS}


def migrate_v4_labels(labels: Mapping[str, Any]) -> dict[str, Any]:
    """Existing v4 labels are a strict subset of v4.1."""
    return canonicalize_v4_1_labels(labels)


def migrate_v3_to_v4_1_labels(labels: Mapping[str, Any]) -> dict[str, Any]:
    return canonicalize_v4_1_labels(migrate_v3_labels(labels).labels)


def incipient_labels(source_location: Any) -> dict[str, Any]:
    site = (
        source_location
        if source_location == "inside_gauge"
        else "outside_gauge_non_root"
        if source_location == "outside_gauge"
        else None
    )
    return canonicalize_v4_1_labels(
        {
            "clip_state": "临界未断裂",
            "fracture_mechanism": "韧性断裂",
            "fracture_site": site,
            "special_case": None,
        }
    )
