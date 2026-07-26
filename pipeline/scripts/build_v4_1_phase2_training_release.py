#!/usr/bin/env python3
"""Preflight or publish the immutable V4.1 Phase 2 development release."""

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
from pipeline.v4_1_phase2_training_release import (
    build_v4_1_phase2_training_release,
)

DATA_ROOT_CONFIG = PROJECT_ROOT / "config/data_roots.json"
CONTRACT_VERSION = "tensile-vlm/v4.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--base-release-dir", type=Path)
    parser.add_argument("--materialized", type=Path)
    parser.add_argument("--media-manifest", type=Path)
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--routing-manifest", type=Path)
    parser.add_argument("--manual-decisions", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument(
        "--contract",
        type=Path,
        default=PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    parser.add_argument("--splits-dir", type=Path)
    parser.add_argument("--releases-dir", type=Path)
    args = parser.parse_args()

    paths = current_data_paths(PROJECT_ROOT, data_home=args.data_home)
    args.data_home = paths.root.parent
    args.project_root = args.project_root or paths.compatibility_workspace
    args.base_release_dir = args.base_release_dir or (
        paths.training_releases / "v4.1.0-760050fad303"
    )
    media_root = (
        paths.metadata
        / "v4_1/experiments/candidate_media_results/candidate-media-b442478052cd"
    )
    args.materialized = args.materialized or media_root / "development_materialized.json"
    args.media_manifest = args.media_manifest or media_root / "manifest.json"
    args.queue = args.queue or (
        paths.metadata
        / "v4_1/review_queues/v4-1-phase2-development-dc453f01fb23/review_queue.json"
    )
    args.routing_manifest = args.routing_manifest or (
        paths.metadata
        / "v4_1/review_routes/history-review-route-0b2c1c78a832/routing_manifest.json"
    )
    args.manual_decisions = args.manual_decisions or (
        paths.metadata
        / "v4_1/review_decisions/v4-1-phase2-development-dc453f01fb23/"
        "review-batch-7a7222b947da/decisions.json"
    )
    args.audit = args.audit or (
        paths.metadata / "v4_1/effective_view_audits/phase1_verified/audit_manifest.json"
    )
    args.splits_dir = args.splits_dir or paths.splits
    args.releases_dir = args.releases_dir or paths.training_releases
    return args


def main() -> int:
    args = parse_args()
    validate_workspace(
        load_config(DATA_ROOT_CONFIG),
        CONTRACT_VERSION,
        data_home=args.data_home,
    )
    release_dir, manifest = build_v4_1_phase2_training_release(
        project_root=args.project_root,
        base_release_dir=args.base_release_dir,
        materialized_path=args.materialized,
        media_manifest_path=args.media_manifest,
        queue_path=args.queue,
        routing_manifest_path=args.routing_manifest,
        manual_decisions_path=args.manual_decisions,
        audit_path=args.audit,
        contract_path=args.contract,
        splits_dir=args.splits_dir,
        releases_dir=args.releases_dir,
        validate_only=args.validate_only,
    )
    print(
        json.dumps(
            {
                "mode": "validate-only" if args.validate_only else "published",
                "release_dir": str(release_dir),
                "release_id": manifest["release_id"],
                "combined_review_id": manifest["combined_review_id"],
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
