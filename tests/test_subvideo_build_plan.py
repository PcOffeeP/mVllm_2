import copy
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from pipeline.scripts import subvideo_build_plan as cli
from pipeline.v3_candidate_plan import (
    EVENT_GUARD_SECONDS,
    EVENT_POSITIONS,
    TARGET_DURATIONS,
    CandidatePlanError,
    build_candidate_plan,
    load_plan_inputs,
    materialize_candidate_plan,
)
from pipeline.v3_labels import map_legacy_fracture_type

EXPECTED_ROI_MEDIA_DIR = cli.CURRENT_DATA.roi_videos / "roi-media-84ea2bd3a052"

pytestmark = pytest.mark.skipif(
    not EXPECTED_ROI_MEDIA_DIR.is_dir(),
    reason="requires migrated project-local lightweight V3 fixtures",
)


def _real_inputs() -> dict:
    return load_plan_inputs(
        EXPECTED_ROI_MEDIA_DIR,
        cli.DEFAULT_REVIEW_REFERENCE_DIR,
        cli.DEFAULT_CONTRACT,
    )


def _real_plan() -> tuple[dict, dict]:
    inputs = _real_inputs()
    return inputs, build_candidate_plan(inputs)


def _all_candidates(plan: dict) -> list[dict]:
    return plan["development_candidates"] + plan["test_candidate_audit"]


def _event_time(record: dict) -> float:
    value = record.get("event_time_effective", record.get("event_time"))
    assert isinstance(value, (int, float))
    return float(value)


def test_real_lightweight_inputs_produce_deterministic_split_safe_plan():
    inputs, plan = _real_plan()
    repeated = build_candidate_plan(inputs)
    assert repeated == plan
    assert plan["plan_id"] == "candidate-plan-ce36b9226be5"
    assert len(plan["development_candidates"]) == 1285
    assert len(plan["test_candidate_audit"]) == 332
    assert len(plan["needs_review"]) == 598

    development_sources = {
        item["source_video"] for item in plan["development_candidates"]
    }
    test_sources = {item["source_video"] for item in plan["test_candidate_audit"]}
    development_skipped = {
        item["source_video"] for item in plan["development_skipped_sources"]
    }
    test_skipped = {item["source_video"] for item in plan["test_skipped_sources"]}
    assert development_sources.isdisjoint(test_sources)
    assert development_sources | development_skipped == inputs["development_ids"]
    assert test_sources | test_skipped == inputs["test_ids"]
    assert development_sources.isdisjoint(development_skipped)
    assert test_sources.isdisjoint(test_skipped)
    assert all(
        item["media_status"] == "planned_not_materialized"
        for item in _all_candidates(plan)
    )
    assert all(not Path(path).is_absolute() for path in plan["input_paths"].values())


def test_transition_candidates_use_two_balanced_rounds_and_one_adaptive_maximum():
    _, plan = _real_plan()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in _all_candidates(plan):
        if item["window_role"] == "transition":
            grouped[item["source_video"]].append(item)
    assert grouped

    complete_source_seen = False
    for items in grouped.values():
        assert len(items) <= 10
        assert sum(item["duration_policy"] == "adaptive" for item in items) <= 1
        pairs = [
            (item["target_duration_seconds"], item["event_position_ratio"])
            for item in items
        ]
        assert len(pairs) == len(set(pairs))
        assert {item[0] for item in pairs} <= set(TARGET_DURATIONS)
        assert {item[1] for item in pairs} <= set(EVENT_POSITIONS)
        assert max(Counter(item[0] for item in pairs).values()) <= 2
        assert max(Counter(item[1] for item in pairs).values()) <= 2
        if len(items) == 10:
            complete_source_seen = True
            assert set(Counter(item[0] for item in pairs).values()) == {2}
            assert set(Counter(item[1] for item in pairs).values()) == {2}
    assert complete_source_seen


def test_pre_event_strategies_caps_and_safe_end_are_enforced():
    inputs, plan = _real_plan()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in _all_candidates(plan):
        if item["window_role"] == "pre_event":
            grouped[item["source_video"]].append(item)
    assert grouped

    strategies_seen: set[str] = set()
    for video_id, items in grouped.items():
        record = inputs["records"][video_id]
        event = _event_time(record)
        assert all(float(item["end_time"]) <= event - EVENT_GUARD_SECONDS for item in items)
        mapping = map_legacy_fracture_type(record.get("type"))
        mechanism = mapping.fracture_mechanism
        if mechanism in {"脆性断裂", "爆炸性断裂"}:
            strategies_seen.add("abrupt")
            assert len(items) <= 3
            assert all(item["window_variant"] == "abrupt_end_aligned" for item in items)
            assert len({item["end_frame"] for item in items}) == 1
        elif mechanism in {"韧性断裂", "半脆半韧断裂"}:
            strategies_seen.add("process")
            assert len(items) <= 15
            assert max(Counter(item["target_duration_seconds"] for item in items).values()) <= 3
            assert {item["window_variant"] for item in items} <= {
                "pre_event_front",
                "pre_event_middle",
                "pre_event_back",
            }
        else:
            strategies_seen.add("other")
            assert len(items) <= 4
            assert all(item["window_variant"] == "other_end_aligned" for item in items)
            assert len({item["end_frame"] for item in items}) == 1
    assert {"abrupt", "process", "other"} <= strategies_seen


def test_post_event_uses_full_tail_and_contiguous_halves_or_thirds():
    inputs, plan = _real_plan()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in _all_candidates(plan):
        if item["window_role"] == "post_event":
            grouped[item["source_video"]].append(item)
    assert grouped

    for video_id, items in grouped.items():
        assert len(items) <= 4
        event = _event_time(inputs["records"][video_id])
        assert all(float(item["start_time"]) >= event + EVENT_GUARD_SECONDS for item in items)
        full = [item for item in items if item["window_variant"] == "post_event_full"]
        assert len(full) == 1
        parts = sorted(
            (item for item in items if item["window_variant"] != "post_event_full"),
            key=lambda item: item["start_frame"],
        )
        expected_parts = 3 if full[0]["duration"] >= 6.0 else 2 if full[0]["duration"] >= 3.0 else 0
        assert len(parts) == expected_parts
        if parts:
            assert parts[0]["start_frame"] == full[0]["start_frame"]
            assert parts[-1]["end_frame"] == full[0]["end_frame"]
            assert all(
                left["end_frame"] == right["start_frame"]
                for left, right in zip(parts, parts[1:])
            )
            assert all(item["duration"] >= 1.0 for item in parts)


def test_normal_sources_have_five_standard_rotated_windows_and_no_manual_review():
    inputs, plan = _real_plan()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in _all_candidates(plan):
        if inputs["records"][item["source_video"]].get("has_fracture_canonical") is False:
            grouped[item["source_video"]].append(item)
    assert grouped
    for items in grouped.values():
        assert len(items) <= 5
        assert len({item["target_duration_seconds"] for item in items}) == len(items)
        assert all(item["window_role"] == "stable_negative" for item in items)
        assert all(item["review_disposition"] == "automatic_validation" for item in items)
        assert all(item["target_duration_seconds"] in TARGET_DURATIONS for item in items)


def test_unknown_state_sources_are_skipped_without_candidates():
    inputs, plan = _real_plan()
    all_candidates = _all_candidates(plan)
    skipped = plan["development_skipped_sources"] + plan["test_skipped_sources"]
    assert skipped
    skipped_ids = {item["source_video"] for item in skipped}
    assert skipped_ids.isdisjoint({item["source_video"] for item in all_candidates})
    assert all(item["candidate_v3_labels"]["clip_state"] != "无法判断" for item in all_candidates)
    assert {item["skip_reason"] for item in skipped} <= {
        "unclamped",
        "video_abnormal",
        "missing_reliable_event_time",
        "state_not_derivable",
    }
    assert skipped_ids <= set(inputs["records"])


def test_historical_matches_never_bypass_required_manual_review():
    _, plan = _real_plan()
    all_candidates = _all_candidates(plan)
    exact_manual = [
        item
        for item in all_candidates
        if item["reference_match"]["kind"] == "exact"
        and item["review_disposition"] == "manual_required"
    ]
    assert exact_manual
    for item in all_candidates:
        state = item["candidate_v3_labels"]["clip_state"]
        expected = "manual_required" if state in {"发生断裂", "已断裂"} else "automatic_validation"
        assert item["review_disposition"] == expected
    assert plan["needs_review"] == [
        item
        for item in plan["development_candidates"]
        if item["candidate_v3_labels"]["clip_state"] in {"发生断裂", "已断裂"}
    ]


def test_materialization_writes_only_immutable_metadata(tmp_path: Path):
    _, plan = _real_plan()
    output_root = tmp_path / "candidate_plans"
    destination = materialize_candidate_plan(plan, output_root)
    assert destination.name == plan["plan_id"]
    assert sorted(path.name for path in destination.iterdir()) == [
        "development_candidates.json",
        "manifest.json",
        "needs_review.json",
        "statistics.json",
        "test_candidate_audit.json",
    ]
    assert not list(tmp_path.rglob("*.mp4"))
    assert not list(tmp_path.rglob("*.jpg"))
    development = json.loads(
        (destination / "development_candidates.json").read_text(encoding="utf-8")
    )
    assert development["skipped_sources"] == plan["development_skipped_sources"]
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["media_generated"] is False
    assert materialize_candidate_plan(plan, output_root) == destination

    recomputed_drift = copy.deepcopy(plan)
    recomputed_drift["development_candidates"][0]["window_variant"] = "unexpected_drift"
    with pytest.raises(CandidatePlanError, match="artifact 漂移"):
        materialize_candidate_plan(recomputed_drift, output_root)

    (destination / "statistics.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(CandidatePlanError, match="artifact 漂移"):
        materialize_candidate_plan(plan, output_root)


def test_dry_run_cli_does_not_create_output_directory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
):
    output_root = tmp_path / "must_not_exist"
    monkeypatch.setattr(
        "sys.argv",
        [
            "subvideo_build_plan.py",
            "--dry-run",
            "--output-root",
            str(output_root),
        ],
    )
    cli.main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["dry_run"] is True
    assert summary["media_generated"] is False
    assert not output_root.exists()


def test_every_source_contribution_and_skip_is_reported_by_scope():
    inputs, plan = _real_plan()
    for scope, candidates_key, skipped_key, inventory_key in (
        ("development", "development_candidates", "development_skipped_sources", "development_ids"),
        ("test_audit", "test_candidate_audit", "test_skipped_sources", "test_ids"),
    ):
        statistics = plan["statistics"][scope]
        grouped = Counter(item["source_video"] for item in plan[candidates_key])
        assert statistics["source_inventory_count"] == len(inputs[inventory_key])
        assert statistics["per_source_contribution"]["counts"] == dict(sorted(grouped.items()))
        assert statistics["skipped_source_count"] == len(plan[skipped_key])
        assert statistics["sources_without_candidates"] == sorted(
            item["source_video"] for item in plan[skipped_key]
        )
