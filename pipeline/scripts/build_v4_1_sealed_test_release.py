#!/usr/bin/env python3
"""Preflight or publish the immutable V4.1 sealed-test release."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.current_data import current_data_paths
from pipeline.data_roots import load_config, validate_workspace
from pipeline.v4_1_sealed_test_release import (
    build_v4_1_sealed_test_release,
)

DATA_ROOT_CONFIG = PROJECT_ROOT / "config/data_roots.json"
CONTRACT_VERSION = "tensile-vlm/v4.1"
QUEUE_ID = "v4-1-phase2-sealed_test-4f66487a6315"
BATCH_ID = "review-batch-6a8d94bd7675"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument(
        "--contract",
        type=Path,
        default=PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    parser.add_argument("--development-release-manifest", type=Path)
    parser.add_argument("--test-split", type=Path)
    parser.add_argument("--releases-dir", type=Path)
    args = parser.parse_args()

    paths = current_data_paths(PROJECT_ROOT, data_home=args.data_home)
    args.data_home = paths.root.parent
    args.project_root = args.project_root or paths.compatibility_workspace
    args.queue = args.queue or (
        paths.metadata / f"v4_1/review_queues/{QUEUE_ID}/review_queue.json"
    )
    args.decisions = args.decisions or (
        paths.metadata
        / f"v4_1/review_decisions/{QUEUE_ID}/{BATCH_ID}/decisions.json"
    )
    args.development_release_manifest = (
        args.development_release_manifest
        or paths.training_releases
        / "v4.1.0-ecb5aeb9657c/manifest/release_manifest.json"
    )
    args.test_split = args.test_split or paths.splits / "test.json"
    args.releases_dir = args.releases_dir or paths.root / "sealed_test_releases"
    return args


def main() -> int:
    args = parse_args()
    validate_workspace(
        load_config(DATA_ROOT_CONFIG),
        CONTRACT_VERSION,
        data_home=args.data_home,
    )
    release_dir, manifest = build_v4_1_sealed_test_release(
        project_root=args.project_root,
        queue_path=args.queue,
        decisions_path=args.decisions,
        contract_path=args.contract,
        development_release_manifest_path=args.development_release_manifest,
        test_split_path=args.test_split,
        releases_dir=args.releases_dir,
        validate_only=args.validate_only,
    )
    print(
        json.dumps(
            {
                "mode": "validate-only" if args.validate_only else "published",
                "release_dir": str(release_dir),
                "release_id": manifest["release_id"],
                "status": manifest["status"],
                "source_queue_id": manifest["source_queue_id"],
                "source_review_batch_id": manifest["source_review_batch_id"],
                "counts": manifest["counts"],
                "one_time_evaluation_authorized": manifest["access_policy"][
                    "one_time_evaluation_authorized"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
