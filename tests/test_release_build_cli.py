import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline import artifact_index, artifact_resolver
from pipeline.current_data import current_data_context
import release_build as cli


def _make_entry(artifact_id: str, step: str = "source") -> dict:
    return {
        "id": artifact_id,
        "created_at": artifact_index.utc_now(),
        "step": step,
        "inputs": {},
        "stats": {},
    }


def _write_snapshot_tree(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "manifest.json").write_text("{}")


def test_parser_defaults_are_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "repo"
    monkeypatch.setattr(cli, "PROJECT_ROOT", project_root)
    args = cli.build_parser().parse_args([
        "--materialized", str(tmp_path / "materialized.json"),
        "--media-manifest", str(tmp_path / "manifest.json"),
        "--queue", str(tmp_path / "queue.json"),
        "--decisions", str(tmp_path / "decisions.json"),
    ])
    assert args.source_snapshot is None
    assert args.split_snapshot is None
    assert args.source_tree_sha256 is None
    assert args.split_tree_sha256 is None


def test_parse_args_resolves_latest_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "repo"
    monkeypatch.setattr(cli, "PROJECT_ROOT", project_root)
    context = current_data_context(project_root)
    source_dir = context.metadata_collection("source_snapshots")
    split_dir = context.metadata_collection("split_snapshots")
    source_id = "source-snapshot-123456789abc"
    split_id = "split-snapshot-123456789abc"
    artifact_index.append_entry(source_dir, _make_entry(source_id))
    artifact_resolver.update_latest(source_dir, source_id)
    artifact_index.append_entry(split_dir, _make_entry(split_id))
    artifact_resolver.update_latest(split_dir, split_id)
    _write_snapshot_tree(source_dir / source_id)
    _write_snapshot_tree(split_dir / split_id)

    args = cli.parse_args([
        "--materialized", str(tmp_path / "materialized.json"),
        "--media-manifest", str(tmp_path / "manifest.json"),
        "--queue", str(tmp_path / "queue.json"),
        "--decisions", str(tmp_path / "decisions.json"),
    ])

    assert args.source_snapshot == source_dir / source_id
    assert args.split_snapshot == split_dir / split_id
    assert isinstance(args.source_tree_sha256, str)
    assert isinstance(args.split_tree_sha256, str)


def test_parse_args_accepts_snapshot_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "repo"
    monkeypatch.setattr(cli, "PROJECT_ROOT", project_root)
    context = current_data_context(project_root)
    source_dir = context.metadata_collection("source_snapshots")
    split_dir = context.metadata_collection("split_snapshots")
    source_id = "source-snapshot-123456789abc"
    split_id = "split-snapshot-123456789abc"
    artifact_index.append_entry(source_dir, _make_entry(source_id))
    artifact_index.append_entry(split_dir, _make_entry(split_id))
    _write_snapshot_tree(source_dir / source_id)
    _write_snapshot_tree(split_dir / split_id)

    args = cli.parse_args([
        "--materialized", str(tmp_path / "materialized.json"),
        "--media-manifest", str(tmp_path / "manifest.json"),
        "--queue", str(tmp_path / "queue.json"),
        "--decisions", str(tmp_path / "decisions.json"),
        "--source-snapshot", "source-snapshot-123",
        "--split-snapshot", "split-snapshot-123",
    ])

    assert args.source_snapshot == source_dir / source_id
    assert args.split_snapshot == split_dir / split_id


def test_parse_args_uses_explicit_tree_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "repo"
    monkeypatch.setattr(cli, "PROJECT_ROOT", project_root)
    context = current_data_context(project_root)
    source_dir = context.metadata_collection("source_snapshots")
    split_dir = context.metadata_collection("split_snapshots")
    source_id = "source-snapshot-123456789abc"
    split_id = "split-snapshot-123456789abc"
    artifact_index.append_entry(source_dir, _make_entry(source_id))
    artifact_resolver.update_latest(source_dir, source_id)
    artifact_index.append_entry(split_dir, _make_entry(split_id))
    artifact_resolver.update_latest(split_dir, split_id)
    _write_snapshot_tree(source_dir / source_id)
    _write_snapshot_tree(split_dir / split_id)

    args = cli.parse_args([
        "--materialized", str(tmp_path / "materialized.json"),
        "--media-manifest", str(tmp_path / "manifest.json"),
        "--queue", str(tmp_path / "queue.json"),
        "--decisions", str(tmp_path / "decisions.json"),
        "--source-tree-sha256", "abc123",
        "--split-tree-sha256", "def456",
    ])

    assert args.source_tree_sha256 == "abc123"
    assert args.split_tree_sha256 == "def456"


def test_parse_args_fails_closed_when_latest_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "repo"
    monkeypatch.setattr(cli, "PROJECT_ROOT", project_root)
    current_data_context(project_root)

    with pytest.raises(ValueError, match="LATEST|latest|显式"):
        cli.parse_args([
            "--materialized", str(tmp_path / "materialized.json"),
            "--media-manifest", str(tmp_path / "manifest.json"),
            "--queue", str(tmp_path / "queue.json"),
            "--decisions", str(tmp_path / "decisions.json"),
        ])
