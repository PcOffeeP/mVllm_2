"""Pure field definitions for the ROI annotation review form.

Values come from the existing annotation row.  This module neither infers
labels nor normalizes legacy values, and it performs no file I/O.  In
particular, an empty cell remains distinct from ``否``, ``无`` and the unified
uncertainty label ``无法判断``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class FieldSpec:
    column: str
    label: str
    kind: str = "select"
    options: tuple[str, ...] = ()
    readonly: bool = False


@dataclass(frozen=True)
class FieldGroup:
    title: str
    fields: tuple[FieldSpec, ...]


_YES_NO_UNKNOWN = ("", "是", "否", "无法判断")

LABEL_GROUPS = (
    FieldGroup("断裂结论", (
        FieldSpec("断裂状态", "断裂状态", options=("", "未断裂", "发生断裂", "已断裂", "无法判断")),
        FieldSpec("断裂模式", "断裂模式", options=("", "脆性断裂", "韧性断裂", "半脆半韧断裂", "无法判断", "无")),
        FieldSpec("断裂位置", "断裂位置", options=("", "标距内", "标距外非根部", "夹持根部", "无法判断", "无")),
    )),
    FieldGroup("异常情况", (
        FieldSpec("异常_未夹紧", "未夹紧", options=_YES_NO_UNKNOWN),
        FieldSpec("异常_视频异常", "视频异常", options=_YES_NO_UNKNOWN),
        FieldSpec("异常_爆炸性断裂", "爆炸性断裂", options=_YES_NO_UNKNOWN),
    )),
    FieldGroup("断裂现象", (
        FieldSpec("现象_伸长", "伸长", options=_YES_NO_UNKNOWN),
        FieldSpec("现象_颈缩", "颈缩", options=_YES_NO_UNKNOWN),
        FieldSpec("现象_开裂", "开裂", options=_YES_NO_UNKNOWN),
        FieldSpec("现象_界面分离", "界面分离", options=_YES_NO_UNKNOWN),
        FieldSpec("现象_断后脱夹", "断后脱夹", options=_YES_NO_UNKNOWN),
    )),
    FieldGroup("关键帧与时间", (
        FieldSpec("断裂帧_前", "断裂前帧", kind="text"),
        FieldSpec("断裂帧_后", "断裂后帧", kind="text"),
        FieldSpec("断裂时间点", "发生时间（秒）", kind="text", readonly=True),
        FieldSpec("断裂时间范围_下界", "时间范围下界（秒）", kind="text", readonly=True),
        FieldSpec("断裂时间范围_上界", "时间范围上界（秒）", kind="text", readonly=True),
    )),
    FieldGroup("标注记录", (
        FieldSpec("标注状态", "标注状态", options=("", "已标注·有断裂", "已标注·无断裂", "未标注", "无法判读")),
        FieldSpec("标注备注", "备注", kind="textarea"),
    )),
)

LABEL_FIELDS = tuple(field for group in LABEL_GROUPS for field in group.fields)
FIELDS_BY_COLUMN = {field.column: field for field in LABEL_FIELDS}

_LEGACY_DISPLAY = {
    ("断裂状态", "无法确定"): "无法判断（原值：无法确定）",
    ("断裂模式", "无法确定"): "无法判断（原值：无法确定）",
    ("断裂位置", "无法确定"): "无法判断（原值：无法确定）",
    ("断裂模式", "无法识别"): "无法判断（原值：无法识别）",
}


def field_value(labels: Mapping[str, Any] | None, column: str) -> str:
    """Return the exact cell text; absent/None cells are displayed as blank.

    CSV values are strings.  Supporting numeric values here only makes the
    helper usable with in-memory rows; it does not interpret their meaning.
    """
    value = (labels or {}).get(column, "")
    return "" if value is None else str(value)


def options_for(field: FieldSpec, current_value: Any) -> tuple[str, ...]:
    """Include a nonstandard original value instead of replacing it.

    The returned option values are raw data values, not display labels.
    ``option_label`` supplies the human-readable text separately.
    """
    current = "" if current_value is None else str(current_value)
    return field.options if current in field.options else (*field.options, current)


def option_label(field: FieldSpec, value: Any) -> str:
    """Render blank/legacy options without changing their stored values."""
    raw = "" if value is None else str(value)
    if raw == "":
        return "未标注"
    if (field.column, raw) in _LEGACY_DISPLAY:
        return _LEGACY_DISPLAY[(field.column, raw)]
    return raw if raw in field.options else f"原值（待复核） · {raw}"


def values_from_labels(labels: Mapping[str, Any] | None) -> dict[str, str]:
    """Create a fresh per-video form value mapping, without mutating its row."""
    return {field.column: field_value(labels, field.column) for field in LABEL_FIELDS}


def extra_label_values(labels: Mapping[str, Any] | None) -> dict[str, str]:
    """Keep other original columns available for a supplementary information view."""
    return {
        column: field_value(labels, column)
        for column in (labels or {})
        if column not in FIELDS_BY_COLUMN and column not in {"id", "video_id", "video_path"}
    }
