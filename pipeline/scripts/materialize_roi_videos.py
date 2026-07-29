#!/usr/bin/env python3
"""Generate ROI-normalized source videos from a frozen ROI manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.roi_media import (  # noqa: E402
    RoiMediaError,
    load_generation_plan,
    materialize_plan,
    require_tools,
)
from pipeline.current_data import data_context_from_arg  # noqa: E402
from pipeline.roi_manifest import ROI_MANIFEST_SCHEMA_VERSION  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从冻结 ROI 清单生成保持原时间轴的 3:4 源视频"
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--roi-manifest", type=Path)
    parser.add_argument("--video-meta", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--video-ids", nargs="+", default=None)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只校验输入并打印生成计划，不调用 ffmpeg",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    context = data_context_from_arg(PROJECT_ROOT, args.data_root)
    args.roi_manifest = args.roi_manifest or (
        context.metadata_artifact_path(
            "roi_manifests",
            "roi-manifest-01be8c1ebb2d",
            expected_schema=ROI_MANIFEST_SCHEMA_VERSION,
        )
    )
    args.video_meta = args.video_meta or context.metadata / "video_meta.json"
    args.output_root = args.output_root or context.roi_videos
    args.output_root = context.require_managed_output(
        args.output_root,
        context.roi_videos,
        label="ROI media output",
    )
    try:
        plan = load_generation_plan(
            args.roi_manifest,
            args.video_meta,
            context.root,
            selected_video_ids=args.video_ids,
        )
        summary = {
            "roi_media_id": plan["media_id"],
            "roi_manifest_id": plan["identity"]["roi_manifest_id"],
            "source_count": plan["source_count"],
            "scope": "full" if plan["full_scope"] else "selected",
            "workers": args.workers,
            "check_only": args.check_only,
        }
        if args.check_only:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        require_tools()
        destination = materialize_plan(plan, args.output_root, workers=args.workers)
        summary["destination"] = str(destination)
        summary["created_or_reused"] = True
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except RoiMediaError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
