"""The single registry of approved generation rules, and its digest.

A batch records this registry instead of hashing source files. Moving a module,
renaming a package or editing a comment must not invalidate a batch, while a
changed window policy, guard length, coverage criterion or special-source rule
must: those values are the rules, the file layout is not.

Values are read from the code that actually applies them (not restated here),
except the few approved literals this module owns: the official window geometry
and the special-source anchors, which the dispatch and the receipt builder take
from here so the number exists once.
"""
from __future__ import annotations

import hashlib
import json

# Official batch window geometry (DF-027): 20 s windows every 15 s.
WINDOW_SECONDS = 20
STEP_SECONDS = 15

# Coverage route: the same 20 s / 15 s sliding grid, kept as its own rule value
# because DF-028 pins it independently of the official event windows.
COVERAGE_WINDOW_SECONDS = 20
COVERAGE_STEP_SECONDS = 15

# The five source-annotation columns that can carry one fracture event anchor.
COVERAGE_ANCHOR_FIELDS = ("断裂帧_前", "断裂帧_后", "断裂时间点",
                          "断裂时间范围_下界", "断裂时间范围_上界")

# The source states that mean "this annotation cannot decide the fracture time".
COVERAGE_UNCERTAIN_STATES = ("无法判断", "无法确定")

# The coverage route is a data criterion over the source annotation, never an id
# list: a source with no usable anchor and an undecidable state gets the sliding
# coverage windows instead of event windows.
COVERAGE_RULE = "断裂状态 in {无法判断, 无法确定} 且 断裂帧/断裂时间/断裂时间范围锚点全为空"


def _present(value) -> bool:
    """Whether a source cell carries a value.

    Mirror of ``_legacy/core/generate.py:_present``; the legacy module must stay
    independent of this one, so the two copies are pinned equal by the contract
    tests instead of being shared.
    """
    return value not in (None, "", "无")


def has_fracture_anchor(row: dict) -> bool:
    """Whether the row carries any of the five fracture event anchors."""
    return any(_present(row.get(name)) for name in COVERAGE_ANCHOR_FIELDS)


def is_coverage_source(row: dict) -> bool:
    """The coverage route, decided from the annotation row alone.

    No usable fracture anchor *and* a source state that could not be decided.
    Any other source, including an unbroken one, keeps the event policy.
    """
    return (not has_fracture_anchor(row)
            and row.get("断裂状态") in COVERAGE_UNCERTAIN_STATES)


# video_0093 is the one source whose presentation frames were approved by hand.
SPECIAL_VIDEO_ID = "video_0093"
SPECIAL_FIXED_TEST_FOLDS = True
SPECIAL_ANCHOR_FRAMES = (727, 728)

# The clip-name suffixes candidate ids are built from. Declared once; the
# 110-source namer reads this mapping instead of keeping its own copy.
ROLE_NAMES = {"pre_event": "pre", "transition": "fracture", "post_event": "post",
              "stable_negative": "no_fracture", "unclamped": "unclamped"}

# How a source is routed to one of the three approved generators.
STRATEGY_RULE = {
    "special": "video_id == special_video_id",
    "coverage": COVERAGE_RULE,
    "default": "regular",
}

FIELDS = (
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


def registry() -> dict:
    """Read every approved rule value from the code that applies it.

    The imports are delayed on purpose: ``generate`` and ``virtual`` import this
    module at import time, so importing them at module scope would be circular.
    """
    from script.subvideo_generation import generate, virtual
    from script.subvideo_generation._legacy.special import verification as special_verification
    from script.subvideo_generation.pilot import aligned, geometry

    return {
        "schema": generate.SCHEMA,
        "source_count": generate.SOURCE_COUNT,
        "window_seconds": WINDOW_SECONDS,
        "step_seconds": STEP_SECONDS,
        "guard_seconds": aligned.GUARD_SECONDS,
        "post_remaining_seconds": aligned.POST_REMAINING_SECONDS,
        "event_guard_seconds": geometry.EVENT_GUARD_SECONDS,
        "target_durations": list(geometry.TARGET_DURATIONS),
        "event_positions": list(geometry.EVENT_POSITIONS),
        "min_candidate_seconds": geometry.MIN_CANDIDATE_SECONDS,
        "role_caps": {"transition": geometry.TRANSITION_CAP,
                      "brittle_pre_event": geometry.BRITTLE_PRE_EVENT_CAP,
                      "ductile_pre_event": geometry.DUCTILE_PRE_EVENT_CAP,
                      "other_pre_event": geometry.OTHER_PRE_EVENT_CAP,
                      "post_event": geometry.POST_EVENT_CAP,
                      "normal_negative": geometry.NORMAL_NEGATIVE_CAP},
        "role_names": _jsonable(ROLE_NAMES),
        "coverage_rule": STRATEGY_RULE["coverage"],
        "coverage_window_seconds": COVERAGE_WINDOW_SECONDS,
        "coverage_step_seconds": COVERAGE_STEP_SECONDS,
        "special_video_id": SPECIAL_VIDEO_ID,
        "special_fixed_test_folds": SPECIAL_FIXED_TEST_FOLDS,
        "special_anchor_frames": list(SPECIAL_ANCHOR_FRAMES),
        "special_presented_frames": special_verification.ACTUAL_FRAME_COUNT,
        "special_declared_frames": special_verification.HEADER_FRAME_COUNT,
        "special_discarded_preroll": special_verification.PREROLL_FRAMES,
        "strategy_rule": dict(STRATEGY_RULE),
        "virtual_schema": virtual.SCHEMA,
        "virtual_window_seconds": virtual.WINDOW_SECONDS,
        "virtual_step_seconds": virtual.STEP_SECONDS,
        "virtual_role": virtual.ROLE,
    }


def digest() -> str:
    """sha256 of the registry: the only rule fingerprint a batch identity needs.

    Deliberately uncached: the digest must follow the registry that is live in
    this process, including a registry replaced by a contract test.
    """
    payload = json.dumps(registry(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def rules() -> dict:
    """The rule fingerprint plus the values it was computed from."""
    return {"digest": digest(), "fields": registry()}


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def stored_rules() -> dict:
    """The same fingerprint in the JSON form a manifest can hold.

    JSON has no tuple, so any ordered value the registry exposes as one is
    converted to a list here; a manifest written with the raw registry would
    otherwise not read back equal to the dict it was produced from.
    """
    return {"digest": digest(), "fields": _jsonable(registry())}
