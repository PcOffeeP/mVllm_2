import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline import artifact_index, artifact_resolver
from pipeline.current_data import current_data_context
import roi_freeze_decisions as cli


def _make_entry(artifact_id: str, step: str = "source") -> dict:
    return {
        "id": artifact_id,
        "created_at": artifact_index.utc_now(),
        "step": step,
        "inputs": {},
        "stats": {},
    }


def test_parser_defaults_are_none():
    args = cli.build_parser().parse_args([])
    assert args.decisions is None
    assert args.video_metadata is None
    assert args.test_manifest is None
    assert args.output_root is None
    assert args.check_only is False


def test_parser_accepts_check_only():
    assert cli.build_parser().parse_args(["--check-only"]).check_only is True


def test_resolve_inputs_uses_latest_snapshots(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    source_dir = context.metadata_collection("source_snapshots")
    split_dir = context.metadata_collection("split_snapshots")
    source_id = "source-snapshot-123456789abc"
    split_id = "split-snapshot-123456789abc"
    artifact_index.append_entry(source_dir, _make_entry(source_id))
    artifact_resolver.update_latest(source_dir, source_id)
    artifact_index.append_entry(split_dir, _make_entry(split_id, step="source"))
    artifact_resolver.update_latest(split_dir, split_id)

    args = cli.build_parser().parse_args([])
    cli._resolve_inputs(args, context)

    assert args.video_metadata == source_dir / source_id / "video_meta.json"
    assert args.test_manifest == split_dir / split_id / "test.json"


def test_resolve_inputs_accepts_artifact_prefix(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    source_dir = context.metadata_collection("source_snapshots")
    split_dir = context.metadata_collection("split_snapshots")
    source_id = "source-snapshot-123456789abc"
    split_id = "split-snapshot-123456789abc"
    artifact_index.append_entry(source_dir, _make_entry(source_id))
    artifact_index.append_entry(split_dir, _make_entry(split_id, step="source"))

    args = cli.build_parser().parse_args([
        "--video-metadata", "source-snapshot-123",
        "--test-manifest", "split-snapshot-123",
    ])
    cli._resolve_inputs(args, context)

    assert args.video_metadata == source_dir / source_id / "video_meta.json"
    assert args.test_manifest == split_dir / split_id / "test.json"


def test_resolve_inputs_keeps_explicit_path(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    explicit_video = project_root / "custom" / "video_meta.json"
    explicit_test = project_root / "custom" / "test.json"
    explicit_video.parent.mkdir(parents=True)
    explicit_video.write_text("{}")
    explicit_test.write_text("{}")

    args = cli.build_parser().parse_args([
        "--video-metadata", str(explicit_video),
        "--test-manifest", str(explicit_test),
    ])
    cli._resolve_inputs(args, context)

    assert args.video_metadata == explicit_video
    assert args.test_manifest == explicit_test


def test_resolve_inputs_fails_closed_when_latest_missing(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    args = cli.build_parser().parse_args([])
    with pytest.raises(ValueError, match="LATEST|latest|显式"):
        cli._resolve_inputs(args, context)
