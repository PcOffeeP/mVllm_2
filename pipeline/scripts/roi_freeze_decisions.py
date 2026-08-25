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

from pipeline import artifact_resolver
from pipeline.roi_manifest import build_roi_manifest_bundle, write_roi_manifest_bundle
from pipeline.current_data import data_context_from_arg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument(
        "--decisions",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--video-metadata",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--test-manifest",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只校验和显示摘要，不写冻结目录",
    )
    return parser


def _resolve_inputs(args: argparse.Namespace, context) -> None:
    if args.decisions is None:
        args.decisions = context.metadata / "roi_decisions.json"
    args.video_metadata = artifact_resolver.resolve_cli_artifact_path(
        context.metadata_collection("source_snapshots"),
        args.video_metadata,
        artifact_subpath="video_meta.json",
    )
    args.test_manifest = artifact_resolver.resolve_cli_artifact_path(
        context.metadata_collection("split_snapshots"),
        args.test_manifest,
        artifact_subpath="test.json",
    )
    if args.output_root is None:
        args.output_root = context.metadata_collection("roi_manifests")


def main() -> int:
    args = build_parser().parse_args()
    context = data_context_from_arg(PROJECT_ROOT, args.data_root)
    _resolve_inputs(args, context)
    args.output_root = context.require_managed_output(
        args.output_root,
        context.metadata_collection("roi_manifests"),
        label="ROI manifest output",
    )
    bundle = build_roi_manifest_bundle(
        decisions_path=args.decisions,
        video_metadata_path=args.video_metadata,
        test_manifest_path=args.test_manifest,
        project_root=context.root,
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
