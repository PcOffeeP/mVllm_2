#!/usr/bin/env python3
"""Preflight or freeze the V4.1 source-aware 3k sampling datasets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.build_v4_1_source_aware_3k import (
    COVERAGE_FIRST_POLICY_VERSION,
    DEFAULT_SEEDS,
    build_source_aware_3k,
)
from pipeline.current_data import current_data_paths

RELEASE_ID = "v4.1.0-ecb5aeb9657c"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--verify-media", action="store_true")
    parser.add_argument("--release-id", default=RELEASE_ID)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    parser.add_argument(
        "--coverage-first",
        action="store_true",
        help=(
            "Use the development-only Stage B coverage-first revision with a "
            "shared candidate multiset and seed-specific ordering."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = current_data_paths(ROOT)
    output_root = args.output_root or (
        paths.metadata / "v4_1/source_aware_3k"
    )
    output_dir, summary = build_source_aware_3k(
        release_dir=paths.training_releases / args.release_id,
        media_root=paths.compatibility_workspace,
        output_root=output_root,
        seeds=args.seeds,
        verify_media=args.verify_media,
        validate_only=args.validate_only,
        policy_version=(
            COVERAGE_FIRST_POLICY_VERSION
            if args.coverage_first
            else "source-aware-3k/1.0"
        ),
        coverage_first=args.coverage_first,
    )
    print(
        json.dumps(
            {
                "mode": "validate-only" if args.validate_only else "frozen",
                "output_dir": str(output_dir),
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
