#!/usr/bin/env python3
"""Build the immutable v3 historical-review reference bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.review_evidence import build_reference_bundle, write_reference_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--train-review-decisions",
        type=Path,
        default=PROJECT_ROOT / "data/07_metadata/subvideo_train_review_decisions_final.json",
    )
    parser.add_argument(
        "--train-reviewed-metadata",
        type=Path,
        default=PROJECT_ROOT / "data/07_metadata/subvideos_meta.label_reviewed.json",
    )
    parser.add_argument(
        "--test-review-decisions",
        type=Path,
        default=PROJECT_ROOT / "data/07_metadata/subvideo_test_review_decisions.json",
    )
    parser.add_argument(
        "--test-reviewed-metadata",
        type=Path,
        default=PROJECT_ROOT / "data/07_metadata/test_subvideos_meta.label_reviewed.json",
    )
    parser.add_argument(
        "--video-metadata",
        type=Path,
        default=PROJECT_ROOT / "data/07_metadata/video_meta.json",
    )
    parser.add_argument(
        "--test-manifest",
        type=Path,
        default=PROJECT_ROOT / "data/05_splits/test.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data/07_metadata/v3/review_reference",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    bundle = build_reference_bundle(
        train_review_decisions_path=args.train_review_decisions,
        train_reviewed_metadata_path=args.train_reviewed_metadata,
        test_review_decisions_path=args.test_review_decisions,
        test_reviewed_metadata_path=args.test_reviewed_metadata,
        video_metadata_path=args.video_metadata,
        test_manifest_path=args.test_manifest,
        project_root=PROJECT_ROOT,
    )
    report = {
        **bundle["build_report.json"],
        "dry_run": args.dry_run,
        "output_root": str(args.output_root),
    }
    if not args.dry_run:
        destination, created = write_reference_bundle(args.output_root, bundle)
        report["destination"] = str(destination)
        report["created"] = created
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
