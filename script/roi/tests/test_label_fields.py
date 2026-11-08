"""The review form must display the annotation's values without relabelling it."""
from copy import deepcopy

import pytest

from script.roi import label_fields as fields


def test_review_form_contains_every_visual_label_and_recorded_anchor():
    columns = {field.column for field in fields.LABEL_FIELDS}
    assert {"断裂状态", "断裂模式", "断裂位置",
            "异常_未夹紧", "异常_视频异常", "异常_爆炸性断裂",
            "现象_伸长", "现象_颈缩", "现象_开裂", "现象_界面分离", "现象_断后脱夹",
            "断裂帧_前", "断裂帧_后", "断裂时间点", "断裂时间范围_下界", "断裂时间范围_上界",
            "标注状态", "标注备注"} <= columns
    assert len(columns) == len(fields.LABEL_FIELDS)


@pytest.mark.parametrize("value", ["", "是", "否", "无法判断", "无", "旧表自定义值", " 含空白原值 "])
def test_annotation_values_are_preserved_verbatim_instead_of_becoming_defaults(value):
    field = fields.FIELDS_BY_COLUMN["异常_未夹紧"]
    row = {field.column: value}
    before = deepcopy(row)
    actual = fields.values_from_labels(row)
    assert actual[field.column] == value
    assert value in fields.options_for(field, actual[field.column])
    assert row == before
    if value == "":
        assert fields.option_label(field, value) == "未标注"
        assert actual[field.column] != "否"


@pytest.mark.parametrize("column,value", [("断裂状态", "无法判断"), ("断裂模式", "无法识别")])
def test_legacy_uncertainty_is_displayed_with_its_original_value(column, value):
    field = fields.FIELDS_BY_COLUMN[column]
    assert fields.field_value({column: value}, column) == value
    assert value in fields.options_for(field, value)
    assert value in fields.option_label(field, value)


def test_values_for_another_video_are_independent_and_do_not_leak_previous_labels():
    first = fields.values_from_labels({"断裂状态": "发生断裂", "异常_未夹紧": "否", "断裂帧_后": "0"})
    second = fields.values_from_labels({"断裂状态": "未断裂", "异常_未夹紧": "无法判断", "断裂帧_后": "无"})
    assert first["断裂状态"] == "发生断裂"
    assert second["断裂状态"] == "未断裂"
    assert first["异常_未夹紧"] == "否"
    assert second["异常_未夹紧"] == "无法判断"
    assert first["断裂帧_后"] == "0"
    assert second["断裂帧_后"] == "无"
    second["断裂状态"] = "已断裂"
    assert first["断裂状态"] == "发生断裂"


def test_missing_cells_stay_unannotated_and_extra_source_information_remains_available():
    row = {"id": "video_0001", "video_path": "data/videos/video_0001.mp4",
           "材料类型": "金属", "断裂模式": None, "断裂帧_后": 0}
    assert fields.field_value(row, "断裂状态") == ""
    assert fields.field_value(row, "断裂模式") == ""
    assert fields.field_value(row, "断裂帧_后") == "0"
    assert fields.extra_label_values(row) == {"材料类型": "金属"}


def test_known_options_match_the_annotation_tool_and_keep_absence_distinct():
    assert set(fields.FIELDS_BY_COLUMN["断裂状态"].options) == {"", "未断裂", "发生断裂", "已断裂", "无法确定"}
    assert set(fields.FIELDS_BY_COLUMN["断裂模式"].options) == {"", "脆性断裂", "韧性断裂", "半脆半韧断裂", "无法确定", "无"}
    assert set(fields.FIELDS_BY_COLUMN["断裂位置"].options) == {"", "标距内", "标距外非根部", "夹持根部", "无法确定", "无"}
    for column in ("异常_未夹紧", "异常_视频异常", "异常_爆炸性断裂", "现象_伸长", "现象_颈缩", "现象_开裂", "现象_界面分离", "现象_断后脱夹"):
        assert set(fields.FIELDS_BY_COLUMN[column].options) == {"", "是", "否", "无法判断"}
