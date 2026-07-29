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
from pipeline.current_data import data_context_from_arg


def build_parser() -> argparse.ArgumentParser:
    current = data_context_from_arg(PROJECT_ROOT, None)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument(
        "--decisions",
        type=Path,
        default=current.metadata / "roi_decisions.json",
    )
    parser.add_argument(
        "--video-metadata",
        type=Path,
        default=current.metadata / "video_meta.json",
    )
    parser.add_argument(
        "--test-manifest",
        type=Path,
        default=current.splits / "test.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=current.metadata_collection("roi_manifests"),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只校验和显示摘要，不写冻结目录",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paths = data_context_from_arg(PROJECT_ROOT, args.data_root)
    current = data_context_from_arg(PROJECT_ROOT, None)
    if args.data_root is not None:
        if args.decisions == current.metadata / "roi_decisions.json":
            args.decisions = paths.metadata / "roi_decisions.json"
        if args.video_metadata == current.metadata / "video_meta.json":
            args.video_metadata = paths.metadata / "video_meta.json"
        if args.test_manifest == current.splits / "test.json":
            args.test_manifest = paths.splits / "test.json"
        if args.output_root == current.metadata_collection("roi_manifests"):
            args.output_root = paths.metadata_collection("roi_manifests")
    args.output_root = paths.require_managed_output(
        args.output_root,
        paths.metadata_collection("roi_manifests"),
        label="ROI manifest output",
    )
    bundle = build_roi_manifest_bundle(
        decisions_path=args.decisions,
        video_metadata_path=args.video_metadata,
        test_manifest_path=args.test_manifest,
        project_root=paths.root,
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
