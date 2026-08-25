"""Lightweight binding assertions for subvideo_build_plan defaults."""

from pathlib import Path

import pytest

from pipeline import artifact_index, artifact_resolver
from pipeline.current_data import current_data_context
from pipeline.scripts import subvideo_build_plan as cli
from pipeline.v3_candidate_plan import materialize_candidate_plan


def _make_entry(artifact_id: str, step: str = "roi") -> dict:
    return {
        "id": artifact_id,
        "created_at": artifact_index.utc_now(),
        "step": step,
        "inputs": {},
        "stats": {},
    }


def test_parser_defaults_are_none():
    parser = cli.build_parser()
    args = parser.parse_args([])
    assert args.roi_media_dir is None
    assert args.output_root is None


def test_default_roi_media_dir_resolves_latest(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    roi_videos_dir = context.roi_videos
    roi_media_id = "roi-media-123456789abc"
    artifact_index.append_entry(roi_videos_dir, _make_entry(roi_media_id))
    artifact_resolver.update_latest(roi_videos_dir, roi_media_id)

    parser = cli.build_parser()
    args = parser.parse_args(["--review-reference-dir", str(tmp_path)])
    cli._resolve_inputs(args, context)

    assert args.roi_media_dir == roi_videos_dir / roi_media_id


def test_default_output_root_is_candidate_plans(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    roi_videos_dir = context.roi_videos
    roi_media_id = "roi-media-123456789abc"
    artifact_index.append_entry(roi_videos_dir, _make_entry(roi_media_id))
    artifact_resolver.update_latest(roi_videos_dir, roi_media_id)

    parser = cli.build_parser()
    args = parser.parse_args(["--review-reference-dir", str(tmp_path)])
    cli._resolve_inputs(args, context)

    assert args.output_root == context.metadata_collection("candidate_plans")


def test_roi_media_prefix_resolves(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    roi_videos_dir = context.roi_videos
    roi_media_id = "roi-media-123456789abc"
    artifact_index.append_entry(roi_videos_dir, _make_entry(roi_media_id))

    parser = cli.build_parser()
    args = parser.parse_args([
        "--roi-media-dir", "roi-media-123",
        "--review-reference-dir", str(tmp_path),
    ])
    cli._resolve_inputs(args, context)

    assert args.roi_media_dir == roi_videos_dir / roi_media_id


def test_materialize_candidate_plan_appends_index_and_latest(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "candidate_plans"
    plan = {
        "plan_id": "candidate-plan-testindex001",
        "identity": {
            "inputs": {
                "roi_media_id": "roi-media-test",
                "review_reference_id": "review-ref-test",
            },
        },
        "input_paths": {},
        "development_candidates": [],
        "development_skipped_sources": [],
        "test_candidate_audit": [],
        "test_skipped_sources": [],
        "needs_review": [],
        "statistics": {},
    }
    destination = materialize_candidate_plan(plan, output_root)
    assert destination.name == plan["plan_id"]

    index = artifact_index.read_index(output_root)
    assert [entry["id"] for entry in index] == [plan["plan_id"]]
    latest = (output_root / artifact_resolver.LATEST_FILENAME).read_text(
        encoding="utf-8"
    ).strip()
    assert latest == plan["plan_id"]

    # Idempotent rerun keeps the same latest/index state.
    materialize_candidate_plan(plan, output_root)
    assert (
        output_root / artifact_resolver.LATEST_FILENAME
    ).read_text(encoding="utf-8").strip() == plan["plan_id"]
    assert len(artifact_index.read_index(output_root)) == 1


def test_roi_media_latest_missing_fails_closed(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)

    parser = cli.build_parser()
    args = parser.parse_args([])
    with pytest.raises(ValueError, match="LATEST|latest|显式"):
        cli._resolve_inputs(args, context)


