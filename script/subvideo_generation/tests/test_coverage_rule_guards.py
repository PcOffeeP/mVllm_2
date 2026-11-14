"""Guards for the coverage route: it is decided by annotation features, not by ids.

Three separate contracts live here, because each of them can regress on its own:

* the orchestrator no longer carries a ``video_id`` allowlist for coverage;
* the routing decision needs the source annotation row (no default fallback that
  would silently route a source on its id alone);
* the "has no fracture anchor" test uses the same emptiness rule as the legacy
  planner (``_present``: anything but ``None``/``""``/``"无"`` is a value), so the
  two places cannot drift into disagreeing about a blank anchor.
"""
from __future__ import annotations

import inspect

import pytest

from script.subvideo_generation._legacy.core import generate as legacy_generate
from script.subvideo_generation.tests.rules_support import (
    FRACTURE_ANCHOR_FIELDS, generate_module, rules_module)
from script.subvideo_generation.tests.test_generation_contract import annotation
from .conftest import COVERAGE_IDS, RETIRED_COVERAGE_IDS


def coverage_criterion():
    rules = rules_module()
    criterion = getattr(rules, "is_coverage_source", None)
    assert callable(criterion), (
        "rules.is_coverage_source(row) must be the single anchor/status test the "
        "coverage route uses; there is no id list to fall back to")
    return criterion


def test_the_orchestrator_no_longer_carries_a_coverage_id_allowlist():
    generate, rules = generate_module(), rules_module()

    assert not hasattr(generate, "COVERAGE_IDS"), (
        "generate.COVERAGE_IDS must be gone: coverage is a data criterion, not a list")
    assert "COVERAGE_IDS" not in inspect.getsource(generate), (
        "no module-level coverage id list may survive anywhere in the orchestrator, "
        "including the load_inputs() inventory assertion")
    assert "coverage_ids" not in rules.FIELDS, (
        f"rules.FIELDS must describe the criterion, got {sorted(rules.FIELDS)}")
    assert "coverage_ids" not in rules.registry(), (
        f"registry() must not publish an id list, got {sorted(rules.registry())}")


def test_the_strategy_dispatch_requires_the_source_annotation_row():
    generate = generate_module()
    parameters = list(inspect.signature(generate.strategy_for).parameters.values())

    assert len(parameters) == 2, (
        "strategy_for(video_id, row) must take the annotation row, got "
        f"{[p.name for p in parameters]}")
    assert parameters[1].default is inspect.Parameter.empty, (
        "the annotation row must be required: a default would let a caller route a "
        "source by its id alone")

    with pytest.raises(TypeError) as caught:
        generate.strategy_for("video_0001")

    assert parameters[1].name in str(caught.value), (
        f"the missing annotation row must be the reported argument, got: {caught.value}")


@pytest.mark.parametrize("value", [None, "", "无", "299", 0, "0"],
                         ids=["None", "empty-string", "无", "299", "0-int", "0-string"])
def test_the_anchor_test_matches_the_legacy_presence_rule(value):
    """``rules`` and ``_legacy.core`` must agree on every boundary value."""
    row = annotation("video_0001", 断裂状态="无法判断",
                     **{name: "无" for name in FRACTURE_ANCHOR_FIELDS})
    row["断裂帧_前"] = value

    legacy_has_anchor = any(legacy_generate._present(row.get(name))
                            for name in FRACTURE_ANCHOR_FIELDS)
    criterion_says_coverage = coverage_criterion()(row)

    assert bool(criterion_says_coverage) is (not legacy_has_anchor), (
        f"anchor value {value!r}: the criterion says coverage={criterion_says_coverage!r} "
        f"while _legacy.core.generate._present treats the row as "
        f"{'anchored' if legacy_has_anchor else 'unanchored'}")


def test_the_fixture_coverage_set_is_not_the_retired_id_allowlist():
    """A fixture that reproduced the old list could not tell a feature route from ids."""
    assert COVERAGE_IDS - RETIRED_COVERAGE_IDS, (
        "the fixture must route at least one source that was never on the retired "
        "allowlist to coverage, otherwise reverting to the id list stays green")
    assert RETIRED_COVERAGE_IDS - COVERAGE_IDS, (
        "the fixture must leave at least one retired id on the event policy, otherwise "
        "reverting to the id list stays green")


def test_unclamped_source_keeps_its_blanks_instead_of_the_coverage_state():
    """Recorded current behaviour: the 异常_未夹紧 branch runs after the state is set.

    Corresponds to the exception note in ``docs/subvideo-current-logic.md``: a source
    that is both unclamped and undecidable keeps 断裂状态=无法判断 but has its
    断裂模式/断裂位置 zeroed to 无 by the older unclamped branch, which wins over the
    coverage initial values.
    """
    row = annotation("video_0003", 断裂状态="无法判断", 断裂模式="脆性断裂",
                     断裂位置="标距内", 异常_未夹紧="是",
                     **{name: "无" for name in FRACTURE_ANCHOR_FIELDS})
    assert coverage_criterion()(row) is True, "the row must be a coverage source"

    labels = legacy_generate.candidate_labels(row, "coverage")

    assert labels["断裂状态"] == "无法判断", (
        "the unified uncertain state is what a coverage candidate starts from")
    assert labels["断裂模式"] == "无" and labels["断裂位置"] == "无", (
        "the unclamped branch zeroes 断裂模式/断裂位置 even for a coverage candidate; "
        f"got {labels['断裂模式']!r}/{labels['断裂位置']!r}")


def test_blank_source_labels_pass_through_a_coverage_candidate():
    """Only the uncertain state is filled in; a blank is not an invitation to write 无."""
    row = annotation("video_0003", 断裂状态="无法判断", 断裂模式="", 断裂位置="",
                     **{name: "无" for name in FRACTURE_ANCHOR_FIELDS})
    assert coverage_criterion()(row) is True, "the row must be a coverage source"

    labels = legacy_generate.candidate_labels(row, "coverage")

    assert labels["断裂模式"] == "" and labels["断裂位置"] == "", (
        "blank source labels must survive verbatim; got "
        f"{labels['断裂模式']!r}/{labels['断裂位置']!r}")


def test_routing_follows_the_annotation_features_rather_than_a_fixed_id(project):
    """Perturbing one regular source row must move it to coverage and plan it."""
    root, g, _, _ = project
    rows, rois, folds, *_ = g.load_inputs(root)
    regular = rows["video_0001"]
    assert regular["断裂状态"] == "未断裂"
    assert g.strategy_for("video_0001", regular) == "regular"

    perturbed = dict(regular, 断裂状态="无法判断",
                     **{name: "无" for name in FRACTURE_ANCHOR_FIELDS})

    assert g.strategy_for("video_0001", perturbed) == "coverage", (
        "an unanchored uncertain source must route to coverage whatever its id is")

    source, clips, excluded = g._plan_source(
        root, "video_0001", perturbed, rois["video_0001"], folds["video_0001"], {})

    assert source["strategy"] == "coverage"
    assert source["status"] == "planned", source.get("reason")
    assert [(c["start_frame"], c["end_frame"]) for c in clips] == [(0, 60)]
    assert {c["role"] for c in clips} == {"coverage"}
    assert {c["event_kind"] for c in clips} == {"none_unlocated"}
    assert all(c["candidate_labels"]["断裂状态"] == "无法判断" for c in clips), (
        "a perturbed coverage source must get the same label initial values")
    assert excluded == []
