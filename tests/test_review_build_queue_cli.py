import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline import artifact_index, artifact_resolver
from pipeline.current_data import current_data_context
import review_build_queue as cli


def _make_entry(artifact_id: str, step: str = "candidate_media") -> dict:
    return {
        "id": artifact_id,
        "created_at": artifact_index.utc_now(),
        "step": step,
        "inputs": {},
        "stats": {},
    }


def test_parser_defaults_are_none(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args([])
    assert args.materialized is None
    assert args.manifest is None


def test_resolve_inputs_uses_latest(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    results_dir = context.metadata_collection("candidate_media_results")
    media_id = "candidate-media-123456789abc"
    artifact_index.append_entry(results_dir, _make_entry(media_id))
    artifact_resolver.update_latest(results_dir, media_id)

    args = cli.build_parser().parse_args([])
    cli._resolve_inputs(args, context)

    assert args.materialized == results_dir / media_id / "development_materialized.json"
    assert args.manifest == results_dir / media_id / "manifest.json"


def test_resolve_inputs_accepts_prefix(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    results_dir = context.metadata_collection("candidate_media_results")
    media_id = "candidate-media-123456789abc"
    artifact_index.append_entry(results_dir, _make_entry(media_id))

    args = cli.build_parser().parse_args([
        "--materialized", "candidate-media-123",
        "--manifest", "candidate-media-123",
    ])
    cli._resolve_inputs(args, context)

    assert args.materialized == results_dir / media_id / "development_materialized.json"
    assert args.manifest == results_dir / media_id / "manifest.json"


def test_resolve_inputs_keeps_explicit_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    explicit_materialized = project_root / "custom" / "development_materialized.json"
    explicit_manifest = project_root / "custom" / "manifest.json"
    explicit_materialized.parent.mkdir(parents=True)
    explicit_materialized.write_text("{}")
    explicit_manifest.write_text("{}")

    args = cli.build_parser().parse_args([
        "--materialized", str(explicit_materialized),
        "--manifest", str(explicit_manifest),
    ])
    cli._resolve_inputs(args, context)

    assert args.materialized == explicit_materialized
    assert args.manifest == explicit_manifest


def test_resolve_inputs_fails_closed_when_latest_missing(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    args = cli.build_parser().parse_args([])
    with pytest.raises(ValueError, match="LATEST|latest|显式"):
        cli._resolve_inputs(args, context)
