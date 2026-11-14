"""R1: the rule registry is the single, complete record of the generation rules.

The field list is hard-coded here on purpose: adding a rule to ``rules.py``
without registering it (or dropping one) must fail this test, not silently
change the batch digest.
"""
from __future__ import annotations

import json
import re

from script.subvideo_generation._legacy.core import generate as legacy_generate
from script.subvideo_generation._legacy.coverage import generate as coverage
from script.subvideo_generation._legacy.special import verification as special_verification
from script.subvideo_generation.pilot import aligned, geometry
from script.subvideo_generation import virtual
from script.subvideo_generation.tests.rules_support import generate_module, rules_module
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
    "coverage_ids",
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

# The 17 approved coverage sources, restated independently of the implementation.
EXPECTED_COVERAGE_IDS = {
    "video_" + suffix for suffix in (
        "0005", "0015", "0021", "0034", "0036", "0042", "0049", "0050",
        "0054", "0056", "0058", "0064", "0078", "0087", "0094", "0096", "0107")}


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
    coverage_ids = registry["coverage_ids"]
    assert isinstance(coverage_ids, tuple), (
        f"coverage_ids must be an ordered tuple, got {type(coverage_ids).__name__}")
    assert len(coverage_ids) == len(set(coverage_ids)) == 17
    assert set(coverage_ids) == EXPECTED_COVERAGE_IDS
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
    assert registry["coverage_ids"] == tuple(coverage.DEFAULT_IDS)
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

    assert generate.strategy_for("video_0001") == "0093", (
        "the special source must be resolved through the rule value")
    assert generate.strategy_for("video_0093") == "regular"


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
