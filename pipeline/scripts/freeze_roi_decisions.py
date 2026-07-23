#!/usr/bin/env python3
"""Validate all manual ROI decisions and freeze an immutable manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.roi_manifest import build_roi_manifest_bundle, write_roi_manifest_bundle
from pipeline.current_data import current_data_paths


def build_parser() -> argparse.ArgumentParser:
    paths = current_data_paths(PROJECT_ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decisions",
        type=Path,
        default=paths.metadata / "roi_decisions.json",
    )
    parser.add_argument(
        "--video-metadata",
        type=Path,
        default=paths.metadata / "video_meta.json",
    )
    parser.add_argument(
        "--test-manifest",
        type=Path,
        default=paths.splits / "test.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=paths.metadata / "v3/roi_manifests",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只校验和显示摘要，不写冻结目录",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paths = current_data_paths(PROJECT_ROOT)
    bundle = build_roi_manifest_bundle(
        decisions_path=args.decisions,
        video_metadata_path=args.video_metadata,
        test_manifest_path=args.test_manifest,
        project_root=paths.compatibility_workspace,
    )
    report = {**bundle["validation_report.json"], "check_only": args.check_only}
    if not args.check_only:
        destination, created = write_roi_manifest_bundle(args.output_root, bundle)
        report["destination"] = str(destination)
        report["created"] = created
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
