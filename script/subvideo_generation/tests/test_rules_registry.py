"""R1: the rule registry is the single, complete record of the generation rules.

The field list is hard-coded here on purpose: adding a rule to ``rules.py``
without registering it (or dropping one) must fail this test, not silently
change the batch digest.
"""
from __future__ import annotations

import json
import re

import pytest

from script.subvideo_generation._legacy.core import generate as legacy_generate
from script.subvideo_generation._legacy.special import verification as special_verification
from script.subvideo_generation.pilot import aligned, geometry
from script.subvideo_generation import virtual
from script.subvideo_generation.tests.rules_support import (
    EMPTY_ANNOTATION_VALUES, FRACTURE_ANCHOR_FIELDS, generate_module, rules_module)
from script.subvideo_generation.tests.test_generation_contract import annotation


EXPECTED_FIELDS = (
    "schema",
    "source_count",
    "window_seconds",
    "step_seconds",
    "guard_seconds",
    "post_remaining_seconds",
    "event_guard_seconds",
    "target_durations",
    "event_positions",
    "min_candidate_seconds",
    "role_caps",
    "role_names",
    "coverage_rule",
    "coverage_label_rule",
    "coverage_window_seconds",
    "coverage_step_seconds",
    "special_video_id",
    "special_fixed_test_folds",
    "special_anchor_frames",
    "special_presented_frames",
    "special_declared_frames",
    "special_discarded_preroll",
    "strategy_rule",
    "virtual_schema",
    "virtual_window_seconds",
    "virtual_step_seconds",
    "virtual_role",
)

# Each role cap the planner applies, mapped to the geometry constant that owns it.
CAP_CONSTANTS = {
    "transition": "TRANSITION_CAP",
    "brittle_pre_event": "BRITTLE_PRE_EVENT_CAP",
    "ductile_pre_event": "DUCTILE_PRE_EVENT_CAP",
    "other_pre_event": "OTHER_PRE_EVENT_CAP",
    "post_event": "POST_EVENT_CAP",
    "normal_negative": "NORMAL_NEGATIVE_CAP",
}

# The clip-name suffixes the candidate ids are built from (unchanged behaviour).
EXPECTED_ROLE_NAMES = {
    "pre_event": "pre",
    "transition": "fracture",
    "post_event": "post",
    "stable_negative": "no_fracture",
    "unclamped": "unclamped",
}

# The words the coverage criterion must accept as "the source says we cannot decide".
UNCERTAIN_SOURCE_STATES = ("无法判断", "无法确定")

# The second coverage feature: an unanchored source whose *video* is flagged abnormal
# carries no usable fracture anchor either, so it cannot be cut with event windows.
ABNORMAL_VIDEO_VALUE = "是"
ABNORMAL_VIDEO_OTHER_VALUES = ("否", "", None, "无法判断")


def coverage_criterion():
    """The pure rule that decides the coverage route from one annotation row."""
    rules = rules_module()
    criterion = getattr(rules, "is_coverage_source", None)
    assert callable(criterion), (
        "rules.is_coverage_source(row) must decide the coverage route from the source "
        "annotation alone; the coverage route is no longer a video_id allowlist")
    return criterion


def source_row(status, **overrides):
    """One annotation row with every fracture anchor explicitly cleared."""
    row = annotation("video_0001", 断裂状态=status)
    row.update({name: "无" for name in FRACTURE_ANCHOR_FIELDS})
    row.update(overrides)
    return row


# A row whose 断裂状态 column is *absent*, not blank: ``_source_labels`` reads it with a
# ``""`` default, so the approved initial-label rule has to pass that blank through instead
# of inventing 无法判断 for a source that never claimed to be undecidable.
MISSING_SOURCE_STATE = object()

# The one shape with an absent state column. Mode/location stay populated on purpose: that
# is what shows the rule does not zero them just because the state is missing (only the
# unbroken state and 异常_未夹紧=是 zero them).
MISSING_SOURCE_STATE_CHANGES = {"断裂状态": MISSING_SOURCE_STATE, "断裂模式": "脆性断裂",
                               "断裂位置": "标距内"}

# The source shapes on which the two implementations of the approved initial-label rule
# must say the same thing: one on the producer side
# (``_legacy.core.generate.candidate_labels(row, "coverage")``) and one on the rules side
# (``rules.coverage_candidate_labels``). The list deliberately covers the branches of that
# rule: the unbroken state, the legacy uncertain wording, blank labels, an absent state
# column, the unclamped anomaly (which also zeroes mode/location) and the abnormal-video
# flag.
COVERAGE_LABEL_SHAPES = (
    ("unbroken + abnormal video",
     {"断裂状态": "未断裂", "断裂模式": "无", "断裂位置": "无", "异常_视频异常": "是"}),
    ("legacy uncertain state",
     {"断裂状态": "无法确定", "断裂模式": "无法确定", "断裂位置": "无法确定"}),
    ("blank source labels", {"断裂状态": "无法判断", "断裂模式": "", "断裂位置": ""}),
    ("unclamped undecidable",
     {"断裂状态": "无法判断", "断裂模式": "脆性断裂", "断裂位置": "标距内",
      "异常_未夹紧": "是"}),
    ("unbroken + unclamped + abnormal video",
     {"断裂状态": "未断裂", "异常_未夹紧": "是", "异常_视频异常": "是"}),
    ("unclamped undecidable + abnormal video",
     {"断裂状态": "无法判断", "异常_未夹紧": "是", "异常_视频异常": "是"}),
    ("missing source state", MISSING_SOURCE_STATE_CHANGES),
)


def label_shape_row(changes):
    """The annotation row of one ``COVERAGE_LABEL_SHAPES`` entry.

    ``MISSING_SOURCE_STATE`` builds a row whose 断裂状态 key is deleted outright; every other
    shape simply sets the column as given.
    """
    state = changes.get("断裂状态", "")
    fields = {name: value for name, value in changes.items() if name != "断裂状态"}
    row = source_row("" if state is MISSING_SOURCE_STATE else state, **fields)
    if state is MISSING_SOURCE_STATE:
        del row["断裂状态"]
    return row


def describe_label_difference(actual, expected):
    """One readable line per differing label field, so a failure names the field."""
    fields = sorted(set(actual) | set(expected))
    return [f"{field}: rules-side={actual.get(field)!r} producer={expected.get(field)!r}"
            for field in fields if actual.get(field) != expected.get(field)]


COVERAGE_CASES = (
    ("no anchor + 无法判断", source_row("无法判断"), True),
    ("no anchor + 无法确定", source_row("无法确定"), True),
    ("no anchor + 未断裂", source_row("未断裂"), False),
    ("no anchor + 发生断裂", source_row("发生断裂"), False),
    ("no anchor + 已断裂", source_row("已断裂"), False),
    ("no anchor + empty 断裂状态", source_row(""), False),
    ("no anchor + 无法识别", source_row("无法识别"), False),
    ("exact frames + 无法判断", source_row("无法判断", 断裂帧_前="299", 断裂帧_后="300"), False),
    ("time point + 无法确定", source_row("无法确定", 断裂时间点="30"), False),
    ("frame range + 无法判断",
     source_row("无法判断", 断裂时间范围_下界="29", 断裂时间范围_上界="31"), False),
    ("partial range + 无法判断", source_row("无法判断", 断裂时间范围_下界="29"), False),
    ("empty strings + 无法判断",
     source_row("无法判断", **{name: "" for name in FRACTURE_ANCHOR_FIELDS}), True),
    ("None + 无法确定",
     source_row("无法确定", **{name: None for name in FRACTURE_ANCHOR_FIELDS}), True),
    ("mixed 无/''/None + 无法判断",
     source_row("无法判断", 断裂帧_前="无", 断裂帧_后="", 断裂时间点=None,
                断裂时间范围_下界="无", 断裂时间范围_上界=None), True),
    ("anchors + 未断裂 conflict", source_row("未断裂", 断裂帧_前="299", 断裂帧_后="300"), False),
    # The 异常_视频异常 branch: no anchor + abnormal video is coverage whatever the
    # 断裂状态 says (video_0107 is 未断裂 and still cannot be cut by event windows).
    ("no anchor + 未断裂 + 视频异常=是", source_row("未断裂", 异常_视频异常="是"), True),
    ("no anchor + 发生断裂 + 视频异常=是", source_row("发生断裂", 异常_视频异常="是"), True),
    ("no anchor + empty 断裂状态 + 视频异常=是",
     source_row("", 异常_视频异常="是"), True),
    # A video abnormality is not a coverage feature on its own: an anchor wins.
    ("exact frames + 视频异常=是",
     source_row("未断裂", 断裂帧_前="299", 断裂帧_后="300", 异常_视频异常="是"), False),
    ("exact frames + 无法判断 + 视频异常=是",
     source_row("无法判断", 断裂帧_前="299", 断裂帧_后="300", 异常_视频异常="是"), False),
    ("time point + 视频异常=是",
     source_row("未断裂", 断裂时间点="30", 异常_视频异常="是"), False),
    # The existing status branch does not depend on the video flag.
    ("no anchor + 无法判断 + 视频异常=否",
     source_row("无法判断", 异常_视频异常="否"), True),
    ("no anchor + 未断裂 + 视频异常=否",
     source_row("未断裂", 异常_视频异常="否"), False),
)


def jsonable(value):
    """JSON form of a rule value (tuples become lists), for cross-checks."""
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def test_registry_covers_exactly_the_declared_fields():
    rules = rules_module()

    assert len(rules.FIELDS) == len(set(rules.FIELDS)) == len(EXPECTED_FIELDS), (
        "rules.FIELDS must list every rule exactly once")
    assert set(rules.FIELDS) == set(EXPECTED_FIELDS), (
        "rules.FIELDS drifted from the contract: "
        f"missing={sorted(set(EXPECTED_FIELDS) - set(rules.FIELDS))} "
        f"unexpected={sorted(set(rules.FIELDS) - set(EXPECTED_FIELDS))}")
    assert set(rules.registry()) == set(EXPECTED_FIELDS), (
        "registry() must expose one value per declared field, got "
        f"{sorted(rules.registry())}")


def test_digest_is_a_stable_sha256_of_the_registry():
    rules = rules_module()

    first, second = rules.digest(), rules.digest()

    assert isinstance(first, str) and re.fullmatch(r"[0-9a-f]{64}", first), (
        f"digest() must be a 64 character lowercase hex string, got {first!r}")
    assert first == second, "digest() must be stable inside one process"
    assert set(rules.rules()) == {"digest", "fields"}
    assert rules.rules()["digest"] == first
    assert rules.rules()["fields"] == rules.registry()


def test_registry_values_match_the_approved_generation_rules():
    registry = rules_module().registry()

    assert registry["source_count"] == 110
    assert registry["window_seconds"] == 20
    assert registry["step_seconds"] == 15
    assert registry["guard_seconds"] == 0.5
    assert registry["post_remaining_seconds"] == 2.0
    assert registry["event_guard_seconds"] == 0.5, (
        "the guard the official planner actually applies must be a rule")
    assert registry["target_durations"] == [2.0, 3.0, 5.0, 10.0, 20.0], (
        "the candidate target durations must be a rule, in order")
    assert registry["event_positions"] == [0.20, 0.35, 0.50, 0.65, 0.80], (
        "the event positions the planner samples must be a rule, in order")
    assert registry["min_candidate_seconds"] == 1.0, (
        "the minimum candidate length the planner enforces must be a rule")
    coverage_rule = registry["coverage_rule"]
    assert isinstance(coverage_rule, str) and coverage_rule.strip(), (
        "coverage_rule must be a readable criterion string, not an id list")
    assert "video_" not in coverage_rule, (
        f"the coverage criterion must not name any video_id: {coverage_rule!r}")
    assert "断裂状态" in coverage_rule, (
        f"the coverage criterion must state the column it reads: {coverage_rule!r}")
    for state in UNCERTAIN_SOURCE_STATES:
        assert state in coverage_rule, (
            f"the coverage criterion must accept {state} explicitly: {coverage_rule!r}")
    assert any(token in coverage_rule for token in ("锚点", "断裂帧", "断裂时间", "断裂时刻")), (
        f"the coverage criterion must say it needs no fracture anchor: {coverage_rule!r}")
    assert "视频异常" in coverage_rule, (
        "the coverage criterion must name the video-abnormal flag it now also accepts: "
        f"{coverage_rule!r}")
    assert registry["strategy_rule"]["coverage"] == coverage_rule, (
        "the dispatch rule and the registered criterion must be one value")
    label_rule = registry["coverage_label_rule"]
    assert isinstance(label_rule, str) and label_rule.strip(), (
        "coverage_label_rule must be a readable statement of where a coverage candidate's "
        f"initial labels come from, got {label_rule!r}")
    assert label_rule == rules_module().COVERAGE_LABEL_RULE, (
        "registry()['coverage_label_rule'] must be rules.COVERAGE_LABEL_RULE itself")
    assert registry["coverage_window_seconds"] == 20
    assert registry["coverage_step_seconds"] == 15
    assert registry["special_video_id"] == "video_0093"
    assert registry["special_fixed_test_folds"] is True
    assert registry["special_anchor_frames"] == [727, 728]
    assert registry["special_presented_frames"] == 733
    assert registry["special_declared_frames"] == 771
    assert registry["special_discarded_preroll"] == 38
    assert registry["virtual_role"] == "window"
    assert json.dumps(registry), "every rule value must be JSON serializable"
    assert registry["strategy_rule"], "strategy_rule must describe the strategy dispatch"
    assert json.dumps(registry["strategy_rule"])


def test_registry_agrees_with_the_constants_the_code_actually_uses():
    """Guard against rules.py restating a value the generators stopped using."""
    registry = rules_module().registry()

    assert registry["virtual_schema"] == virtual.SCHEMA
    assert registry["virtual_window_seconds"] == virtual.WINDOW_SECONDS
    assert registry["virtual_step_seconds"] == virtual.STEP_SECONDS
    assert registry["virtual_role"] == virtual.ROLE
    assert registry["coverage_rule"] == rules_module().STRATEGY_RULE["coverage"], (
        "registry()['coverage_rule'] must be the registered dispatch rule")
    assert "coverage_ids" not in registry, (
        "the coverage route must not be described by a video_id allowlist")
    assert registry["guard_seconds"] == aligned.GUARD_SECONDS
    assert registry["post_remaining_seconds"] == aligned.POST_REMAINING_SECONDS
    assert registry["event_guard_seconds"] == geometry.EVENT_GUARD_SECONDS, (
        "event_guard_seconds must read the guard the official planner uses")
    assert registry["target_durations"] == list(geometry.TARGET_DURATIONS)
    assert registry["event_positions"] == list(geometry.EVENT_POSITIONS), (
        "event_positions must read the positions the planner samples")
    assert registry["min_candidate_seconds"] == geometry.MIN_CANDIDATE_SECONDS
    role_caps = registry["role_caps"]
    assert set(role_caps) == set(CAP_CONSTANTS), (
        f"role_caps must expose one cap per role, got {sorted(role_caps)}")
    for role, constant in CAP_CONSTANTS.items():
        assert role_caps[role] == getattr(geometry, constant), (
            f"role_caps[{role!r}] must read geometry.{constant}")
    role_names = registry["role_names"]
    assert role_names == EXPECTED_ROLE_NAMES, (
        "role_names must be the approved candidate-name suffixes")
    if getattr(legacy_generate, "ROLE_NAMES", None) is not None:
        assert role_names == jsonable(legacy_generate.ROLE_NAMES), (
            "role_names must match the mapping the candidate namer uses")
    assert registry["coverage_window_seconds"] == getattr(
        rules_module(), "COVERAGE_WINDOW_SECONDS", registry["coverage_window_seconds"])
    assert registry["coverage_step_seconds"] == getattr(
        rules_module(), "COVERAGE_STEP_SECONDS", registry["coverage_step_seconds"])
    assert registry["window_seconds"] in geometry.TARGET_DURATIONS, (
        "the regular window length must stay one of the approved target durations")
    assert registry["special_presented_frames"] == special_verification.ACTUAL_FRAME_COUNT
    assert registry["special_declared_frames"] == special_verification.HEADER_FRAME_COUNT
    assert registry["special_discarded_preroll"] == special_verification.PREROLL_FRAMES


def test_digest_reacts_to_the_event_guard_the_official_planner_applies(monkeypatch):
    """A guard change moves the produced windows, so it must move the fingerprint."""
    rules = rules_module()
    baseline = rules.digest()

    monkeypatch.setattr(geometry, "EVENT_GUARD_SECONDS", 0.9)

    assert geometry.EVENT_GUARD_SECONDS == 0.9
    assert rules.digest() != baseline, (
        "changing geometry.EVENT_GUARD_SECONDS must change the rules digest; "
        "the registry is not reading the guard the planner applies")


def test_digest_reacts_to_the_target_durations(monkeypatch):
    rules = rules_module()
    baseline = rules.digest()

    monkeypatch.setattr(geometry, "TARGET_DURATIONS", (2.0, 3.0))

    assert rules.digest() != baseline, (
        "changing geometry.TARGET_DURATIONS must change the rules digest")


def test_strategy_dispatch_follows_the_registered_special_source(monkeypatch):
    """``video_0093`` must be a rule value, not a literal inside the dispatcher."""
    rules = rules_module()
    generate = generate_module()
    monkeypatch.setattr(rules, "SPECIAL_VIDEO_ID", "video_0001")
    if hasattr(generate, "SPECIAL_VIDEO_ID"):
        monkeypatch.setattr(generate, "SPECIAL_VIDEO_ID", "video_0001")

    regular_row = annotation("video_0001")
    assert generate.strategy_for("video_0001", regular_row) == "0093", (
        "the special source must be resolved through the rule value")
    assert generate.strategy_for("video_0093", regular_row) == "regular"


@pytest.mark.parametrize("row,expected", [(row, expected) for _, row, expected in COVERAGE_CASES],
                         ids=[case for case, _, _ in COVERAGE_CASES])
def test_coverage_criterion_reads_only_the_source_annotation(row, expected):
    criterion = coverage_criterion()
    snapshot = dict(row)

    verdict = criterion(row)

    assert bool(verdict) is expected, f"got {verdict!r}"
    assert row == snapshot, "the criterion must not rewrite the annotation"


def test_coverage_criterion_ignores_the_video_id():
    criterion = coverage_criterion()
    row = source_row("无法判断")

    verdicts = [bool(criterion(dict(row, id=key))) for key in ("video_0001", "video_0107")]

    assert verdicts == [True, True], (
        "the same annotation features must route the same way whatever the id is")


@pytest.mark.parametrize("empty", EMPTY_ANNOTATION_VALUES,
                         ids=["None", "empty-string", "无"])
def test_every_empty_annotation_value_means_no_anchor(empty):
    """The emptiness rule is part of the criterion: all five columns × every blank spelling."""
    row = source_row("无法判断", **{name: empty for name in FRACTURE_ANCHOR_FIELDS})

    verdict = coverage_criterion()(row)

    assert verdict is True, (
        f"a row whose five anchor columns are all {empty!r} carries no anchor and must "
        "route to coverage")


def test_coverage_anchor_fields_are_the_five_fracture_anchor_columns():
    """The criterion's column set is a contract, not an incidental tuple."""
    rules = rules_module()

    assert len(rules.COVERAGE_ANCHOR_FIELDS) == len(set(rules.COVERAGE_ANCHOR_FIELDS)) == 5, (
        "COVERAGE_ANCHOR_FIELDS must list five distinct columns, got "
        f"{rules.COVERAGE_ANCHOR_FIELDS!r}")
    assert set(rules.COVERAGE_ANCHOR_FIELDS) == set(FRACTURE_ANCHOR_FIELDS), (
        "the columns that make a source ineligible for coverage must be the five "
        "fracture anchor columns: "
        f"missing={sorted(set(FRACTURE_ANCHOR_FIELDS) - set(rules.COVERAGE_ANCHOR_FIELDS))} "
        f"unexpected={sorted(set(rules.COVERAGE_ANCHOR_FIELDS) - set(FRACTURE_ANCHOR_FIELDS))}")


@pytest.mark.parametrize("anchored", FRACTURE_ANCHOR_FIELDS, ids=list(FRACTURE_ANCHOR_FIELDS))
def test_any_single_present_anchor_keeps_the_event_policy(anchored):
    """Dropping one anchor column from the criterion must fail on that column alone."""
    rules = rules_module()
    row = source_row("无法判断")
    row[anchored] = "300"

    assert rules.has_fracture_anchor(row) is True, (
        f"{anchored} must count as a fracture anchor")
    verdict = coverage_criterion()(row)

    assert verdict is False, (
        f"only {anchored} carries a value, so the source has an anchor and must keep "
        "the event policy; 断裂状态=无法判断 alone does not route to coverage")


def test_all_five_anchors_empty_stays_coverage():
    """Control for the per-column guard: the same row with no anchor at all."""
    row = source_row("无法判断")

    verdict = coverage_criterion()(row)

    assert verdict is True, (
        "no anchor + 无法判断 is exactly the coverage route, otherwise the per-column "
        "guard could pass for the wrong reason")


@pytest.mark.parametrize("value,expected",
                         [(ABNORMAL_VIDEO_VALUE, True)]
                         + [(other, False) for other in ABNORMAL_VIDEO_OTHER_VALUES],
                         ids=["是", "否", "empty-string", "None", "无法判断"])
def test_only_the_abnormal_video_flag_yes_triggers_the_second_branch(value, expected):
    """Only "是" in 异常_视频异常 is a coverage feature; the other spellings are not.

    断裂状态 is 未断裂 here, so the status branch cannot fire: the verdict can only come
    from the video flag.
    """
    row = source_row("未断裂", 异常_视频异常=value)

    verdict = coverage_criterion()(row)

    assert bool(verdict) is expected, (
        f"异常_视频异常={value!r} with no anchor and 断裂状态=未断裂: only "
        f"{ABNORMAL_VIDEO_VALUE!r} routes to coverage, got {verdict!r}")


def test_a_row_without_the_abnormal_video_column_keeps_the_event_policy():
    """A missing column is not "是": the criterion must read it through a default."""
    row = source_row("未断裂")
    del row["异常_视频异常"]

    verdict = coverage_criterion()(row)

    assert bool(verdict) is False, f"got {verdict!r}"


def test_registry_reads_the_coverage_rule_from_the_strategy_table(monkeypatch):
    """``coverage_rule`` must be the dispatch string, not a second literal."""
    rules = rules_module()
    patched = "断裂状态 in {无法判断, 无法确定} and no 断裂帧/断裂时间 anchor"

    monkeypatch.setitem(rules.STRATEGY_RULE, "coverage", patched)
    registry = rules.registry()

    assert registry["coverage_rule"] == patched, (
        "registry() must read the coverage criterion from STRATEGY_RULE")
    assert registry["strategy_rule"]["coverage"] == registry["coverage_rule"]


def test_digest_reacts_to_the_coverage_criterion(monkeypatch):
    rules = rules_module()
    baseline = rules.digest()

    monkeypatch.setitem(rules.STRATEGY_RULE, "coverage", "video_id in coverage_ids")

    assert rules.registry()["coverage_rule"] == "video_id in coverage_ids"
    assert rules.digest() != baseline, (
        "a changed coverage criterion must change the rules digest")


def test_digest_reacts_to_the_coverage_label_rule(monkeypatch):
    """The initial label rule decides what a coverage candidate records, so it is a rule."""
    rules = rules_module()
    baseline = rules.digest()

    monkeypatch.setattr(rules, "COVERAGE_LABEL_RULE", rules.COVERAGE_LABEL_RULE + "（候选初值取空）")

    assert rules.registry()["coverage_label_rule"] == rules.COVERAGE_LABEL_RULE
    assert rules.digest() != baseline, (
        "changing rules.COVERAGE_LABEL_RULE must change the rules digest; the registry is "
        "not reading the label rule the coverage branch applies")


def test_digest_reacts_to_the_event_positions(monkeypatch):
    """Sampling different event positions changes the candidate set."""
    rules = rules_module()
    baseline = rules.digest()

    monkeypatch.setattr(geometry, "EVENT_POSITIONS", (0.5,))

    assert rules.digest() != baseline, (
        "changing geometry.EVENT_POSITIONS must change the rules digest")


def test_digest_reacts_to_the_minimum_candidate_seconds(monkeypatch):
    rules = rules_module()
    baseline = rules.digest()

    monkeypatch.setattr(geometry, "MIN_CANDIDATE_SECONDS", 2.5)

    assert rules.digest() != baseline, (
        "changing geometry.MIN_CANDIDATE_SECONDS must change the rules digest")


def test_digest_reacts_to_the_role_caps(monkeypatch):
    rules = rules_module()
    baseline = rules.digest()

    monkeypatch.setattr(geometry, "DUCTILE_PRE_EVENT_CAP", 99)

    assert geometry.DUCTILE_PRE_EVENT_CAP == 99
    assert rules.digest() != baseline, (
        "changing a role cap must change the rules digest; the registry is not "
        "reading the caps the planner applies")


@pytest.mark.parametrize("status,expected", [
    ("未断裂", "未断裂"),
    ("无法判断", "无法判断"),
    ("无法确定", "无法判断"),
    ("发生断裂", "发生断裂"),
], ids=["unbroken", "undecidable", "legacy-undecidable", "fractured"])
def test_coverage_label_state_comes_from_the_source_annotation(status, expected):
    """A coverage candidate starts from the source's own 断裂状态, not from a fixed word."""
    rules = rules_module()
    row = source_row(status)
    snapshot = dict(row)

    state = rules.coverage_label_state(row)

    assert state == expected, f"断裂状态={status!r} must start the candidate at {expected!r}"
    assert row == snapshot, "the initial-label rule must not rewrite the annotation"


def test_coverage_label_state_is_blank_when_the_source_has_no_state():
    row = source_row("未断裂")
    del row["断裂状态"]

    state = rules_module().coverage_label_state(row)

    assert state == "", f"a missing source state must stay empty, got {state!r}"


def test_coverage_candidate_labels_take_the_source_state():
    """An unbroken coverage source keeps 未断裂 and has mode/location zeroed to 无."""
    rules = rules_module()
    row = source_row("未断裂", 断裂模式="无", 断裂位置="无", 异常_视频异常="是")
    labels = {"断裂状态": "无法判断", "断裂模式": "无法确定", "断裂位置": "无法确定"}

    returned = rules.coverage_candidate_labels(labels, row)

    assert returned is labels, (
        "coverage_candidate_labels must rewrite the candidate labels dict it is given")
    assert labels["断裂状态"] == "未断裂", (
        f"the source says 未断裂, so the candidate starts there; got {labels['断裂状态']!r}")
    assert labels["断裂状态"] != "无法判断", (
        "an unbroken source must not be relabelled with the unified uncertain state")
    assert labels["断裂模式"] == "无" and labels["断裂位置"] == "无", (
        "an unbroken candidate must record 无/无, got "
        f"{labels['断裂模式']!r}/{labels['断裂位置']!r}")


def test_an_uncertain_coverage_candidate_keeps_its_source_mode_and_location():
    """Only the 未断裂 case zeroes mode/location; an uncertain source keeps its wording."""
    rules = rules_module()
    row = source_row("无法确定", 断裂模式="无法确定", 断裂位置="无法确定")

    labels = rules.coverage_candidate_labels(legacy_generate.candidate_labels(row, "coverage"), row)

    assert labels["断裂状态"] == "无法判断", (
        f"无法确定 is unified to 无法判断 for the candidate, got {labels['断裂状态']!r}")
    assert labels["断裂模式"] == "无法确定" and labels["断裂位置"] == "无法确定", (
        "an uncertain candidate keeps the source wording instead of being zeroed, got "
        f"{labels['断裂模式']!r}/{labels['断裂位置']!r}")


@pytest.mark.parametrize("shape,changes", COVERAGE_LABEL_SHAPES,
                         ids=[shape for shape, _ in COVERAGE_LABEL_SHAPES])
def test_coverage_candidate_labels_agree_with_the_producer(shape, changes):
    """The two implementations of the initial-label rule must not disagree.

    Why this expectation is not circular (not a copy of the rule side's code): The
    expected value comes from ``_legacy.core.generate.candidate_labels(row, "coverage")``,
    a second, independent implementation of the same approved rule (both read
    ``rules.COVERAGE_LABEL_RULE``, and the unified entry stacks the rule side on the
    producer). Comparing the two therefore catches a change to either one; a copy of the
    rule side's own code could not.

    What it guards: stacking ``rules.coverage_candidate_labels`` on the producer's output
    must change nothing, and applying it twice must not change anything either. The
    producer already recorded the approved initial values, so any extra rewrite here would
    silently relabel a candidate that the manifest audit later compares against these
    very values.
    """
    rules = rules_module()
    row = label_shape_row(changes)
    produced = legacy_generate.candidate_labels(row, "coverage")

    stacked = rules.coverage_candidate_labels(dict(produced), row)

    differences = describe_label_difference(stacked, produced)
    assert not differences, (
        f"{shape}: the rule side rewrote the producer's coverage labels: "
        + "; ".join(differences))
    assert list(stacked) == list(produced), (
        "the rule side must keep the producer's label keys (and their order), got "
        f"{list(stacked)!r} instead of {list(produced)!r}")

    twice = rules.coverage_candidate_labels(dict(stacked), row)
    assert describe_label_difference(twice, produced) == [], (
        f"{shape}: applying the rule side twice must give the same labels, got "
        f"{describe_label_difference(twice, produced)}")


@pytest.mark.parametrize("shape,changes", COVERAGE_LABEL_SHAPES,
                         ids=[shape for shape, _ in COVERAGE_LABEL_SHAPES])
def test_coverage_candidate_labels_match_the_producer_from_the_same_starting_point(shape, changes):
    """The rule side must derive the same labels the producer does, from the same input.

    ``candidate_labels`` starts from ``_source_labels(row)``; feeding the rule side that
    same starting point is the only way to compare the *rules* rather than the producer
    with itself (stacking on the producer's own output is a no-op and cannot see a branch
    the rule side is missing).

    Why this expectation is not circular (not a copy of the rule side's code): the expected labels are the producer's, an
    independent implementation, not a copy of the rule side. The unclamped shapes below
    are the regression this test exists for: the producer zeroes 断裂模式/断裂位置 for any
    source with 异常_未夹紧=是, and a rule side that only looks at 未断裂 keeps the source's
    brittle-break wording instead - which is what a coverage candidate must never record.
    """
    rules = rules_module()
    row = label_shape_row(changes)
    expected = legacy_generate.candidate_labels(row, "coverage")
    raw = legacy_generate._source_labels(row)

    actual = rules.coverage_candidate_labels(dict(raw), row)

    differences = describe_label_difference(actual, expected)
    assert not differences, (
        f"{shape}: rules.coverage_candidate_labels disagrees with the producer "
        f"_legacy.core.generate.candidate_labels(row, 'coverage'): " + "; ".join(differences))


def test_the_coverage_label_rule_text_states_the_values_it_produces():
    """``COVERAGE_LABEL_RULE`` is a registered, documented invalidation condition.

    The text is the only place that states which initial values a coverage candidate
    carries, so it must name all three the rule can produce, otherwise the code and the
    documentation no longer point at the same rule: 未断裂 (an unbroken source keeps its
    own state), 无 (the mode/location such a candidate records) and 无法判断 (the unified
    wording an undecidable source is normalised to).
    """
    rules = rules_module()

    text = rules.COVERAGE_LABEL_RULE

    assert isinstance(text, str) and text.strip(), (
        f"COVERAGE_LABEL_RULE must be a readable rule string, got {text!r}")
    # 未夹紧 is in the set because the approved rule zeroes mode/location for "未断裂" *or*
    # for 异常_未夹紧=是; a text that names only the first condition describes half the rule.
    for token in ("未断裂", "无", "无法判断", "未夹紧"):
        assert token in text, (
            f"the registered label rule must name {token!r}, otherwise text and behaviour "
            f"no longer describe the same rule: {text!r}")


def test_a_missing_source_state_is_passed_through_as_a_blank_label():
    """A row with no 断裂状态 column must not be labelled 无法判断 by the rule side.

    ``coverage_label_state`` passes a missing state through as "" (only the two legacy
    undecidable spellings are unified), and the initial-label rule must preserve that: an
    absent state says nothing about decidability, so inventing 无法判断 would claim the
    source is undecidable. Expectations are written out explicitly here ("" and the source
    mode/location untouched); the shape is also compared field by field with the producer
    by the two agreement tests above.
    """
    rules = rules_module()
    row = label_shape_row(MISSING_SOURCE_STATE_CHANGES)
    assert "断裂状态" not in row, "the shape must build a row without the 断裂状态 column"

    produced = legacy_generate.candidate_labels(row, "coverage")
    actual = rules.coverage_candidate_labels(dict(legacy_generate._source_labels(row)), row)

    assert produced["断裂状态"] == "", (
        f"the producer reads a missing state as blank, got {produced['断裂状态']!r}")
    assert actual["断裂状态"] == "", (
        "a missing source state must stay blank, not become 无法判断 (the source never said "
        f"it was undecidable), got {actual['断裂状态']!r}")
    assert actual["断裂模式"] == "脆性断裂" and actual["断裂位置"] == "标距内", (
        "a missing state is neither 未断裂 nor 异常_未夹紧=是, so mode/location must survive "
        f"verbatim, got {actual['断裂模式']!r}/{actual['断裂位置']!r}")


MINIMAL_WINDOWS = [
    {"window_role": "pre_event", "start_frame": 0, "end_frame": 200,
     "start_time": 0.0, "end_time": 20.0},
    {"window_role": "transition", "start_frame": 150, "end_frame": 350,
     "start_time": 15.0, "end_time": 35.0},
    {"window_role": "post_event", "start_frame": 300, "end_frame": 500,
     "start_time": 30.0, "end_time": 50.0},
]
MINIMAL_FOLDS = {"0": "train", "1": "val", "2": "train"}


def test_candidate_naming_reads_the_registered_role_names(monkeypatch):
    """Changing the registered role names must change candidate ids and paths."""
    rules = rules_module()
    monkeypatch.setattr(rules, "ROLE_NAMES", dict(EXPECTED_ROLE_NAMES, pre_event="before"))

    candidates = legacy_generate._name_candidates(
        MINIMAL_WINDOWS, annotation("video_0001"), MINIMAL_FOLDS, "a" * 64, "b" * 64)

    assert [candidate["role"] for candidate in candidates] == ["before", "fracture", "post"]
    assert candidates[0]["candidate_id"] == "video_0001_before_01", (
        "the candidate id must be built from rules.ROLE_NAMES")
    assert candidates[0]["output_path"] == "videos/video_0001_before_01.mp4"
