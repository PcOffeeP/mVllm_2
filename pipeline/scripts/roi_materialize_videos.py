#!/usr/bin/env python3
"""Generate ROI-normalized source videos from a frozen ROI manifest."""

from __future__ import annotations

import sys


def main() -> int:
    message = (
        "此历史数据辅助 CLI 已停用。请使用 python -m versioning data <stage>，"
        "显式指定 --root、--inputs、--batch；发布时另需完整 --version。"
        "ROI和候选媒体使用roi/subvideo阶段，审查包使用review_export；"
        "历史Phase2对象按已确认mapping迁移，不重建或重新审批。"
        "操作说明见 docs/DATA_PROCESSING_RUNBOOK.md 第10节。"
    )
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


import argparse
import json
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
from pipeline import artifact_resolver
from pipeline.current_data import data_context_from_arg  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从冻结 ROI 清单生成保持原时间轴的 3:4 源视频"
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--roi-manifest", type=Path, default=None)
    parser.add_argument("--video-meta", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--video-ids", nargs="+", default=None)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只校验输入并打印生成计划，不调用 ffmpeg",
    )
    return parser


def _resolve_inputs(args: argparse.Namespace, context) -> None:
    args.roi_manifest = artifact_resolver.resolve_cli_artifact_path(
        context.metadata_collection("roi_manifests"),
        args.roi_manifest,
    )
    args.video_meta = artifact_resolver.resolve_cli_artifact_path(
        context.metadata_collection("source_snapshots"),
        args.video_meta,
        artifact_subpath="video_meta.json",
    )
    if args.output_root is None:
        args.output_root = context.roi_videos


def _legacy_main() -> int:
    args = build_parser().parse_args()
    context = data_context_from_arg(PROJECT_ROOT, args.data_root)
    _resolve_inputs(args, context)
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
