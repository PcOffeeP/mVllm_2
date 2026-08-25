import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline import artifact_index, artifact_resolver
from pipeline.current_data import current_data_context
import subvideo_materialize_media as cli


def _make_entry(artifact_id: str, step: str = "candidate_plan") -> dict:
    return {
        "id": artifact_id,
        "created_at": artifact_index.utc_now(),
        "step": step,
        "inputs": {},
        "stats": {},
    }


def test_parser_defaults_are_none(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args([])
    assert args.candidate_plan is None
    assert args.roi_media is None


def test_resolve_inputs_uses_latest(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    plans_dir = context.metadata_collection("candidate_plans")
    roi_videos_dir = context.roi_videos
    plan_id = "candidate-plan-123456789abc"
    roi_media_id = "roi-media-123456789abc"
    artifact_index.append_entry(plans_dir, _make_entry(plan_id))
    artifact_resolver.update_latest(plans_dir, plan_id)
    artifact_index.append_entry(roi_videos_dir, _make_entry(roi_media_id, step="roi"))
    artifact_resolver.update_latest(roi_videos_dir, roi_media_id)

    args = cli.build_parser().parse_args([])
    cli._resolve_inputs(args, context)

    assert args.candidate_plan == plans_dir / plan_id
    assert args.roi_media == roi_videos_dir / roi_media_id


def test_resolve_inputs_accepts_prefix(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    plans_dir = context.metadata_collection("candidate_plans")
    roi_videos_dir = context.roi_videos
    plan_id = "candidate-plan-123456789abc"
    roi_media_id = "roi-media-123456789abc"
    artifact_index.append_entry(plans_dir, _make_entry(plan_id))
    artifact_index.append_entry(roi_videos_dir, _make_entry(roi_media_id, step="roi"))

    args = cli.build_parser().parse_args([
        "--candidate-plan", "candidate-plan-123",
        "--roi-media", "roi-media-123",
    ])
    cli._resolve_inputs(args, context)

    assert args.candidate_plan == plans_dir / plan_id
    assert args.roi_media == roi_videos_dir / roi_media_id


def test_resolve_inputs_keeps_explicit_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    explicit_plan = project_root / "custom" / "plan"
    explicit_roi = project_root / "custom" / "roi"
    explicit_plan.mkdir(parents=True)
    explicit_roi.mkdir(parents=True)

    args = cli.build_parser().parse_args([
        "--candidate-plan", str(explicit_plan),
        "--roi-media", str(explicit_roi),
    ])
    cli._resolve_inputs(args, context)

    assert args.candidate_plan == explicit_plan
    assert args.roi_media == explicit_roi


def test_resolve_inputs_fails_closed_when_latest_missing(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    args = cli.build_parser().parse_args([])
    with pytest.raises(ValueError, match="LATEST|latest|显式"):
        cli._resolve_inputs(args, context)
