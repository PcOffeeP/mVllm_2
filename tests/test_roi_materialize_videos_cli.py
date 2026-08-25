import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline import artifact_index, artifact_resolver
from pipeline.current_data import current_data_context
import roi_materialize_videos as cli


def _make_entry(artifact_id: str, step: str = "source") -> dict:
    return {
        "id": artifact_id,
        "created_at": artifact_index.utc_now(),
        "step": step,
        "inputs": {},
        "stats": {},
    }


def test_parser_defaults_are_none(tmp_path: Path) -> None:
    args = cli.build_parser().parse_args([])
    assert args.roi_manifest is None
    assert args.video_meta is None
    assert args.output_root is None


def test_resolve_inputs_uses_latest_artifacts(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    roi_dir = context.metadata_collection("roi_manifests")
    source_dir = context.metadata_collection("source_snapshots")
    roi_id = "roi-manifest-123456789abc"
    source_id = "source-snapshot-123456789abc"
    artifact_index.append_entry(roi_dir, _make_entry(roi_id, step="roi"))
    artifact_resolver.update_latest(roi_dir, roi_id)
    artifact_index.append_entry(source_dir, _make_entry(source_id))
    artifact_resolver.update_latest(source_dir, source_id)

    args = cli.build_parser().parse_args([])
    cli._resolve_inputs(args, context)

    assert args.roi_manifest == roi_dir / roi_id
    assert args.video_meta == source_dir / source_id / "video_meta.json"
    assert args.output_root == context.roi_videos


def test_resolve_inputs_accepts_prefix(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    roi_dir = context.metadata_collection("roi_manifests")
    source_dir = context.metadata_collection("source_snapshots")
    roi_id = "roi-manifest-123456789abc"
    source_id = "source-snapshot-123456789abc"
    artifact_index.append_entry(roi_dir, _make_entry(roi_id, step="roi"))
    artifact_index.append_entry(source_dir, _make_entry(source_id))

    args = cli.build_parser().parse_args([
        "--roi-manifest", "roi-manifest-123",
        "--video-meta", "source-snapshot-123",
    ])
    cli._resolve_inputs(args, context)

    assert args.roi_manifest == roi_dir / roi_id
    assert args.video_meta == source_dir / source_id / "video_meta.json"


def test_resolve_inputs_keeps_explicit_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    explicit_roi = project_root / "custom" / "roi_manifest"
    explicit_meta = project_root / "custom" / "video_meta.json"
    explicit_roi.mkdir(parents=True)
    explicit_meta.write_text("{}")

    args = cli.build_parser().parse_args([
        "--roi-manifest", str(explicit_roi),
        "--video-meta", str(explicit_meta),
    ])
    cli._resolve_inputs(args, context)

    assert args.roi_manifest == explicit_roi
    assert args.video_meta == explicit_meta


def test_resolve_inputs_fails_closed_when_latest_missing(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "repo"
    context = current_data_context(project_root)
    args = cli.build_parser().parse_args([])
    with pytest.raises(ValueError, match="LATEST|latest|显式"):
        cli._resolve_inputs(args, context)
