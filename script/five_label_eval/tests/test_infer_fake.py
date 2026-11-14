"""Red-phase tests for the frozen `infer` contract with the fake backend.

The fake backend must stay pure: no HTTP, no model weights, no media reads.
Records and manifests here are synthetic JSON values built in-memory.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

import pytest

from script.five_label_eval.frames import RECORD_SCHEMA
from script.five_label_eval.infer import CATEGORY_ORDER, fake_raw_output, plan_predictions
from script.five_label_eval.score import IDENTITY, MULTIS, SINGLES, InputError, extract

CATEGORIES = ("complete", "missing_fields", "invalid_literal", "conflict",
              "fenced", "request_failed", "timeout")
LABEL_KEYS = {"断裂状态", "断裂模式", "断裂位置", "异常情况", "断裂现象"}
RUN_ID = "run-1"
PROMPT_ID = "prompt@sha256:" + "a" * 64
PREDICTION_KEYS = {"candidate_id", "clip_sha256", "run_id", "model_id", "prompt_id",
                   "input_id", "request_id", "status", "raw_output"}
# Leaf field names are written out as literals on purpose: expectations here must not be
# derived from the scorer's own field tables, otherwise a scorer change stays invisible.
LEAF_FIELDS = ("断裂状态", "断裂模式", "断裂位置",
               "异常情况.未夹紧", "异常情况.视频异常", "异常情况.爆炸性断裂",
               "断裂现象.伸长", "断裂现象.颈缩", "断裂现象.开裂",
               "断裂现象.界面分离", "断裂现象.断后脱夹")
# Prompt-side expectations are spelled out as literals for the same reason as LEAF_FIELDS:
# building them from `score.py` would compare the scorer with itself and hide changes.
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "five_label_v1.txt"
PROMPT_SINGLE_VALUES = {
    "断裂状态": ["未断裂", "发生断裂", "已断裂", "无法判断"],
    "断裂模式": ["脆性断裂", "韧性断裂", "半脆半韧断裂", "无法判断", "无"],
    "断裂位置": ["标距内", "标距外非根部", "夹持根部", "无法判断", "无"],
}
PROMPT_MULTI_ITEMS = {
    "异常情况": ["未夹紧", "视频异常", "爆炸性断裂"],
    "断裂现象": ["伸长", "颈缩", "开裂", "界面分离", "断后脱夹"],
}
# Four hard output requirements; each string must appear verbatim in the prompt.
PROMPT_HARD_REQUIREMENTS = ("只输出一个 JSON 对象", "不要 Markdown 代码围栏",
                            "不得省略任何字段或子项", "不得用空列表表示")


def sample(index):
    """One manifest sample carrying exactly the frozen identity fields."""
    fields = {
        "manifest_sha256": "b" * 64,
        "candidate_id": f"c{index:02d}",
        "clip_sha256": f"{index + 1:064x}",
        "source_id": "video_0001",
        "source_type": "real",
    }
    return {**{key: fields[key] for key in IDENTITY}, "review_id": None}


def manifest_of(count):
    return {"manifest_version": "test/1", "samples": [sample(i) for i in range(count)]}


def record(index):
    return {
        "record_schema": RECORD_SCHEMA,
        "candidate_id": f"c{index:02d}",
        "clip_sha256": f"{index + 1:064x}",
        "manifest_sha256": "b" * 64,
        "input_id": f"input-c{index:02d}",
        "media": {"width": 320, "height": 240, "fps": 30.0, "total_frames": 60},
        # 此块仅作记录结构示例，不参与断言，也不被 infer 读取（plan_predictions 不看 frames）。
        "frames": [{"display_order": 0, "clip_frame_index": 0, "roi_frame_index": 973,
                    "original_source_frame_index": 973,
                    "frame_index_mapping": {
                        "source_to_media": {"kind": "manifest_replay", "offset": 973, "reason": None},
                        "media_to_clip": {"kind": "ffmpeg_select_nth_decoded_frame", "offset": None},
                        "roi_to_source": {"kind": "offset", "offset": 0,
                                          "method": "source_replay_mapping", "reason": None}}}],
    }


def rows_for(count=7, **kwargs):
    records = [record(i) for i in range(count)]
    kwargs.setdefault("model_id", "fake")
    return plan_predictions(records, manifest_of(count), RUN_ID, PROMPT_ID, **kwargs)


def labels_of(raw):
    obj = json.loads(raw)
    assert isinstance(obj, dict)
    return obj


def fenced_body(raw):
    match = re.search(r"```json\s*(\{.*\})\s*```", raw, re.S)
    assert match, raw
    return match.group(1)


def test_category_order_should_match_frozen_contract():
    assert tuple(CATEGORY_ORDER) == CATEGORIES


@pytest.mark.parametrize("index,expected", [
    (0, "success"),
    (1, "success"),
    (2, "success"),
    (3, "success"),
    (4, "success"),
    (5, "request_failed"),
    (6, "timeout"),
])
def test_plan_predictions_should_rotate_category_status_in_input_order(index, expected):
    rows = rows_for()

    assert rows[index]["status"] == expected


def test_plan_predictions_should_keep_record_order_and_one_row_per_record():
    rows = rows_for()

    assert [row["candidate_id"] for row in rows] == [f"c{i:02d}" for i in range(7)]
    assert len({row["candidate_id"] for row in rows}) == len(rows)


def test_plan_predictions_should_emit_all_required_prediction_keys():
    rows = rows_for()

    for row in rows:
        assert set(row) >= PREDICTION_KEYS


def test_plan_predictions_should_use_one_run_model_prompt_triple_for_the_batch():
    rows = rows_for()

    assert {(row["run_id"], row["model_id"], row["prompt_id"]) for row in rows} == {
        (RUN_ID, "fake", PROMPT_ID)}


def test_plan_predictions_should_bind_request_id_to_run_and_candidate():
    rows = rows_for()

    assert [row["request_id"] for row in rows] == [f"{RUN_ID}/{row['candidate_id']}" for row in rows]


def test_plan_predictions_should_carry_record_digest_and_input_id():
    records = [record(i) for i in range(7)]

    rows = plan_predictions(records, manifest_of(7), RUN_ID, PROMPT_ID, model_id="fake")

    assert [row["clip_sha256"] for row in rows] == [rec["clip_sha256"] for rec in records]
    assert [row["input_id"] for row in rows] == [rec["input_id"] for rec in records]


def test_plan_predictions_should_cover_each_category_exactly_once():
    rows = rows_for()

    assert tuple(row["status"] for row in rows) == (
        "success", "success", "success", "success", "success", "request_failed", "timeout")
    assert [row["status"] for row in rows if row["raw_output"] is None] == ["request_failed", "timeout"]


def test_plan_predictions_should_emit_complete_legal_json_for_first_row():
    obj = labels_of(rows_for()[0]["raw_output"])

    assert set(obj) == LABEL_KEYS
    assert obj["断裂状态"] in SINGLES["断裂状态"]
    assert obj["断裂模式"] in SINGLES["断裂模式"]
    assert obj["断裂位置"] in SINGLES["断裂位置"]
    assert set(obj["异常情况"]) == set(MULTIS["异常情况"])
    assert set(obj["断裂现象"]) == set(MULTIS["断裂现象"])


def test_plan_predictions_should_omit_fields_for_missing_fields_row():
    raw = rows_for()[1]["raw_output"]
    obj = labels_of(raw)

    assert "断裂位置" not in obj
    assert "开裂" not in obj["断裂现象"]


def test_plan_predictions_should_emit_invalid_literal_for_third_row():
    obj = labels_of(rows_for()[2]["raw_output"])

    assert obj["断裂状态"] == "部分断裂"
    assert obj["断裂状态"] not in SINGLES["断裂状态"]


def test_plan_predictions_should_emit_cross_field_conflict_for_fourth_row():
    obj = labels_of(rows_for()[3]["raw_output"])

    assert obj["断裂状态"] == "未断裂"
    assert obj["断裂模式"] == "韧性断裂"
    assert obj["断裂位置"] == "无"


def test_plan_predictions_should_fence_complete_json_for_fenced_row():
    raw = rows_for()[4]["raw_output"]

    assert raw.lstrip().startswith("```")
    assert "json" in raw.lstrip().splitlines()[0]
    assert raw.rstrip().endswith("```")
    assert set(labels_of(fenced_body(raw))) == LABEL_KEYS


def test_plan_predictions_should_reject_clip_digest_mismatch():
    records = [record(0), record(1)]
    records[1]["clip_sha256"] = "f" * 64

    with pytest.raises(InputError):
        plan_predictions(records, manifest_of(2), RUN_ID, PROMPT_ID, model_id="fake")


def test_plan_predictions_should_reject_manifest_digest_mismatch():
    records = [record(0), record(1)]
    records[1]["manifest_sha256"] = "c" * 64

    with pytest.raises(InputError) as excinfo:
        plan_predictions(records, manifest_of(2), RUN_ID, PROMPT_ID, model_id="fake")

    message = str(excinfo.value)
    assert "c01" in message
    assert "c" * 64 in message


def test_plan_predictions_should_reject_unknown_record_schema():
    records = [record(0)]
    records[0]["record_schema"] = "five-label-input-record/0"

    with pytest.raises(InputError) as excinfo:
        plan_predictions(records, manifest_of(1), RUN_ID, PROMPT_ID, model_id="fake")

    message = str(excinfo.value)
    assert "record_schema" in message
    # 不写死版本号：报错必须点名**当前**期望 schema（oracle 用 frames.RECORD_SCHEMA，随升版跟随）。
    assert RECORD_SCHEMA in message


def test_plan_predictions_should_reject_candidate_absent_from_manifest():
    records = [record(0)]

    with pytest.raises(InputError):
        plan_predictions(records, {"manifest_version": "test/1", "samples": []},
                         RUN_ID, PROMPT_ID, model_id="fake")


def test_plan_predictions_should_not_mutate_inputs():
    records = [record(i) for i in range(7)]
    original_records = copy.deepcopy(records)
    manifest = manifest_of(7)
    original_manifest = copy.deepcopy(manifest)

    plan_predictions(records, manifest, RUN_ID, PROMPT_ID, model_id="fake")

    assert records == original_records
    assert manifest == original_manifest


def test_fake_raw_output_should_emit_full_legal_labels_when_complete():
    obj = labels_of(fake_raw_output("complete"))

    assert set(obj) == LABEL_KEYS
    assert obj["断裂状态"] in SINGLES["断裂状态"]
    assert obj["断裂模式"] in SINGLES["断裂模式"]
    assert obj["断裂位置"] in SINGLES["断裂位置"]
    assert set(obj["异常情况"]) == set(MULTIS["异常情况"])
    assert set(obj["断裂现象"]) == set(MULTIS["断裂现象"])


def test_fake_raw_output_should_drop_label_position_and_crack_when_missing_fields():
    obj = labels_of(fake_raw_output("missing_fields"))

    assert "断裂位置" not in obj
    assert "开裂" not in obj["断裂现象"]


def test_fake_raw_output_should_emit_out_of_vocabulary_status_when_invalid_literal():
    obj = labels_of(fake_raw_output("invalid_literal"))

    assert obj["断裂状态"] == "部分断裂"
    assert obj["断裂状态"] not in SINGLES["断裂状态"]


def test_fake_raw_output_should_emit_conflicting_status_and_mode():
    obj = labels_of(fake_raw_output("conflict"))

    assert obj["断裂状态"] == "未断裂"
    assert obj["断裂模式"] == "韧性断裂"


def leaf_statuses(extraction):
    return {field: cell["status"] for field, cell in extraction["fields"].items()}


def leaves_with(**overrides):
    return {**{field: "valid" for field in LEAF_FIELDS}, **overrides}


def verdict_complete(extraction):
    assert extraction["strict_format_valid"] is True
    assert leaf_statuses(extraction) == leaves_with()
    assert extraction["conflicts"] == []


def verdict_missing_fields(extraction):
    assert extraction["strict_format_valid"] is False
    assert leaf_statuses(extraction) == leaves_with(**{"断裂位置": "missing",
                                                       "断裂现象.开裂": "missing"})


def verdict_invalid_literal(extraction):
    assert extraction["strict_format_valid"] is False
    assert leaf_statuses(extraction) == leaves_with(**{"断裂状态": "invalid"})
    assert extraction["fields"]["断裂状态"]["value"] == "部分断裂"


def verdict_conflict(extraction):
    assert leaf_statuses(extraction) == leaves_with()
    assert [c for c in extraction["conflicts"] if "断裂模式" in c] != [], extraction["conflicts"]


def verdict_fenced(extraction):
    assert extraction["strict_format_valid"] is False
    assert "surrounding_text_or_fence" in extraction["issues"]
    assert leaf_statuses(extraction) == leaves_with()


@pytest.mark.parametrize("category,verdict", [
    ("complete", verdict_complete),
    ("missing_fields", verdict_missing_fields),
    ("invalid_literal", verdict_invalid_literal),
    ("conflict", verdict_conflict),
    ("fenced", verdict_fenced),
])
def test_fake_raw_output_should_reach_expected_scorer_verdict(category, verdict):
    """Route every answering fake category through the real scorer parser.

    ``request_failed`` / ``timeout`` carry no text, so they never reach ``extract``;
    the parser's view of them is covered by the ``None`` group.
    """
    raw = fake_raw_output(category)
    assert isinstance(raw, str)

    extraction = extract(raw)

    verdict(extraction)


def test_fake_raw_output_should_wrap_parsable_json_in_fence_when_fenced():
    raw = fake_raw_output("fenced")

    assert raw.lstrip().startswith("```")
    assert "json" in raw.lstrip().splitlines()[0]
    assert raw.rstrip().endswith("```")
    assert set(labels_of(fenced_body(raw))) == LABEL_KEYS


@pytest.mark.parametrize("category", ["request_failed", "timeout"])
def test_fake_raw_output_should_return_none_when_request_did_not_answer(category):
    assert fake_raw_output(category) is None


def prompt_text():
    """Read the shipped prompt; a missing/unreadable file must fail, never skip."""
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        pytest.fail(f"prompt 文本不可读：{PROMPT_PATH}（{exc}）")


def prompt_single_values(text):
    """Parse the `- 字段：值、值、…` bullet lines into ``{field: [value, …]}``."""
    found = {}
    for match in re.finditer(r"^-\s*(?P<field>[^：:\s]+)：(?P<values>.+)$", text, re.M):
        field = match.group("field").strip()
        if field not in PROMPT_SINGLE_VALUES:
            continue
        if field in found:
            pytest.fail(f"prompt 里单值字段「{field}」出现多于一次，权威取值列表无法确定")
        found[field] = [value.strip() for value in match.group("values").split("、") if value.strip()]
    if missing := [field for field in PROMPT_SINGLE_VALUES if field not in found]:
        pytest.fail(f"prompt 缺少单值取值行：{missing}（已匹配到的字段：{sorted(found)}）")
    return found


def prompt_multi_items(text, group):
    """Parse one `「组名」包含N项…：子项、子项。` sentence into its item names."""
    match = re.search(rf"「{re.escape(group)}」包含[^：:\n]*：(?P<items>[^。\n]+)。", text)
    if match is None:
        pytest.fail(f"prompt 里找不到多选组「{group}」的子项列表")
    items = [item.strip() for item in match.group("items").split("、") if item.strip()]
    if not items:
        pytest.fail(f"prompt 里多选组「{group}」的子项列表为空")
    return items


def test_prompt_literals_should_match_scorer_vocabulary():
    """Bind the prompt text to the scorer's vocabulary and to the required output format."""
    text = prompt_text()

    singles = prompt_single_values(text)
    multis = {group: prompt_multi_items(text, group) for group in PROMPT_MULTI_ITEMS}

    # Prompt == literal expectation == scorer table, same values in the same order.
    for field, expected in PROMPT_SINGLE_VALUES.items():
        assert singles[field] == expected, f"prompt「{field}」取值与字面量期望不一致：{singles[field]}"
        assert singles[field] == list(SINGLES[field]), f"prompt「{field}」取值与 score.SINGLES 不一致：{singles[field]}"
        assert "无法判断" in singles[field], f"prompt「{field}」缺少单值不确定值「无法判断」"
        assert "无法确定" not in singles[field], f"prompt「{field}」不应再出现历史字面量「无法确定」"
    for group, expected in PROMPT_MULTI_ITEMS.items():
        assert multis[group] == expected, f"prompt「{group}」子项与字面量期望不一致：{multis[group]}"
        assert multis[group] == list(MULTIS[group]), f"prompt「{group}」子项与 score.MULTIS 不一致：{multis[group]}"
    for token in ("是", "否", "无法判断"):
        assert token in text, f"prompt 缺少多选取值字面量：{token}"

    # The JSON template must survive the scorer as a complete, legal example.
    template = re.search(r"^\{.*\}$", text, re.M)
    assert template is not None, "prompt 里找不到单行 JSON 模板"
    extraction = extract(template.group(0))
    assert extraction["strict_format_valid"] is True, extraction["issues"]
    assert extraction["conflicts"] == []
    assert len(extraction["fields"]) == len(LEAF_FIELDS)
    assert {field: cell["status"] for field, cell in extraction["fields"].items()} == leaves_with()

    for requirement in PROMPT_HARD_REQUIREMENTS:
        assert requirement in text, f"prompt 缺少硬要求表述：{requirement}"
