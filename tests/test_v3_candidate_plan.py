import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from pipeline.scripts import build_v3_candidate_plan as cli
from pipeline.v3_candidate_plan import (
    CandidatePlanError,
    build_candidate_plan,
    load_plan_inputs,
    materialize_candidate_plan,
)


PROJECT_ROOT = Path(__file__).parents[1]


def _real_inputs() -> dict:
    return load_plan_inputs(
        cli.DEFAULT_ROI_MEDIA_DIR,
        cli.DEFAULT_REVIEW_REFERENCE_DIR,
        cli.DEFAULT_CONTRACT,
    )


def test_real_lightweight_inputs_produce_frozen_split_safe_plan():
    plan = build_candidate_plan(_real_inputs())
    assert plan["plan_id"] == "candidate-plan-00a346cdbdb4"
    assert len(plan["development_candidates"]) == 869
    assert len(plan["test_candidate_audit"]) == 214
    assert len(plan["needs_review"]) == 750

    development_sources = {
        item["source_video"] for item in plan["development_candidates"]
    }
    test_sources = {item["source_video"] for item in plan["test_candidate_audit"]}
    assert len(development_sources) == 89
    assert len(test_sources) == 21
    assert development_sources.isdisjoint(test_sources)
    assert all(
        item["media_status"] == "planned_not_materialized"
        for item in plan["development_candidates"] + plan["test_candidate_audit"]
    )
    assert all(not Path(path).is_absolute() for path in plan["input_paths"].values())


def test_brittle_pre_event_and_all_post_event_caps_are_enforced():
    plan = build_candidate_plan(_real_inputs())
    all_candidates = plan["development_candidates"] + plan["test_candidate_audit"]
    brittle_pre = Counter(
        item["source_video"]
        for item in all_candidates
        if item["source_type"] == "脆性断裂"
        and item["window_role"] == "pre_event"
    )
    post_event = Counter(
        item["source_video"]
        for item in all_candidates
        if item["window_role"] == "post_event"
    )
    assert brittle_pre
    assert max(brittle_pre.values()) <= 3
    assert post_event
    assert max(post_event.values()) <= 2


def test_reference_matching_never_auto_approves_partial_overlap():
    plan = build_candidate_plan(_real_inputs())
    all_candidates = plan["development_candidates"] + plan["test_candidate_audit"]
    match_counts = Counter(item["reference_match"]["kind"] for item in all_candidates)
    assert match_counts["exact"] == 159
    assert match_counts["partial_overlap"] > 0
    for item in all_candidates:
        if item["reference_match"]["kind"] != "exact":
            assert item["review_disposition"] == "needs_review"


def test_materialization_writes_only_immutable_metadata(tmp_path: Path):
    plan = build_candidate_plan(_real_inputs())
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
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["media_generated"] is False
    assert materialize_candidate_plan(plan, output_root) == destination

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
            "build_v3_candidate_plan.py",
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


def test_every_source_contribution_is_reported_separately_by_scope():
    plan = build_candidate_plan(_real_inputs())
    statistics = plan["statistics"]
    assert statistics["development"]["source_inventory_count"] == 89
    assert statistics["test_audit"]["source_inventory_count"] == 21
    assert statistics["development"]["sources_without_candidates"] == []
    assert statistics["test_audit"]["sources_without_candidates"] == []

    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in plan["development_candidates"]:
        grouped[item["source_video"]].append(item)
    reported = statistics["development"]["per_source_contribution"]["counts"]
    assert reported == {key: len(value) for key, value in sorted(grouped.items())}
