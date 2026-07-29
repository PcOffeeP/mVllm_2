#!/usr/bin/env python3
"""Validate reviewed v4.1 candidates and publish an immutable training release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.current_data import data_context_from_arg
from pipeline.v4_1_training_release import build_v4_1_training_release


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--materialized", type=Path, required=True)
    parser.add_argument("--media-manifest", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--split-snapshot", type=Path, required=True)
    parser.add_argument("--source-tree-sha256", required=True)
    parser.add_argument("--split-tree-sha256", required=True)
    parser.add_argument("--releases-dir", type=Path)
    args = parser.parse_args()

    paths = data_context_from_arg(PROJECT_ROOT, args.data_root)
    args.project_root = args.project_root or paths.root
    args.releases_dir = args.releases_dir or paths.training_releases
    args.releases_dir = paths.require_managed_output(
        args.releases_dir,
        paths.training_releases,
        label="training release output",
    )
    return args


def main() -> int:
    args = parse_args()
    release_dir, manifest = build_v4_1_training_release(
        project_root=args.project_root,
        materialized_path=args.materialized,
        media_manifest_path=args.media_manifest,
        queue_path=args.queue,
        decisions_path=args.decisions,
        contract_path=args.contract,
        splits_dir=args.split_snapshot,
        releases_dir=args.releases_dir,
        source_snapshot_id=args.source_snapshot.name,
        split_snapshot_id=args.split_snapshot.name,
        source_snapshot_dir=args.source_snapshot,
        expected_source_tree_hash=args.source_tree_sha256,
        expected_split_tree_hash=args.split_tree_sha256,
    )
    print(
        json.dumps(
            {
                "release_dir": str(release_dir),
                "release_id": manifest["release_id"],
                "status": manifest["status"],
                "counts": manifest["counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
