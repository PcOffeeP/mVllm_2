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

from pipeline.data_roots import (
    load_config,
    resolve_data_home,
    validate_workspace,
    version_root,
    workspace_root,
)
from pipeline.v4_1_training_release import build_v4_1_training_release

DATA_ROOT_CONFIG = PROJECT_ROOT / "config/data_roots.json"
CONTRACT_VERSION = "tensile-vlm/v4.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--materialized", type=Path)
    parser.add_argument("--media-manifest", type=Path)
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument(
        "--contract",
        type=Path,
        default=PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    parser.add_argument("--splits-dir", type=Path)
    parser.add_argument("--releases-dir", type=Path)
    args = parser.parse_args()

    data_config = load_config(DATA_ROOT_CONFIG)
    data_home = resolve_data_home(
        data_config,
        project_root=PROJECT_ROOT,
        override=args.data_home,
    )
    versioned_root = version_root(
        data_config,
        CONTRACT_VERSION,
        data_home=data_home,
    )
    active_workspace = workspace_root(
        data_config,
        CONTRACT_VERSION,
        data_home=data_home,
    )
    media_root = (
        active_workspace
        / "data/07_metadata/v3/candidate_media_results/candidate-media-8de972530561"
    )
    review_root = (
        active_workspace
        / "data/07_metadata/v4_1/review_decisions/v4-1-review-4a449c8d1193"
    )
    args.data_home = data_home
    args.project_root = args.project_root or active_workspace
    args.materialized = args.materialized or media_root / "development_materialized.json"
    args.media_manifest = args.media_manifest or media_root / "manifest.json"
    args.queue = args.queue or (
        active_workspace
        / "data/07_metadata/v4_1/review_queues/"
        "v4-1-review-4a449c8d1193/review_queue.json"
    )
    args.decisions = args.decisions or (
        review_root / "review-batch-9043bbe4c286/decisions.json"
    )
    args.splits_dir = args.splits_dir or active_workspace / "data/05_splits"
    args.releases_dir = args.releases_dir or versioned_root / "releases"
    return args


def main() -> int:
    args = parse_args()
    data_config = load_config(DATA_ROOT_CONFIG)
    validate_workspace(
        data_config,
        CONTRACT_VERSION,
        data_home=args.data_home,
    )
    release_dir, manifest = build_v4_1_training_release(
        project_root=args.project_root,
        materialized_path=args.materialized,
        media_manifest_path=args.media_manifest,
        queue_path=args.queue,
        decisions_path=args.decisions,
        contract_path=args.contract,
        splits_dir=args.splits_dir,
        releases_dir=args.releases_dir,
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
