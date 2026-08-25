#!/usr/bin/env python3
"""Materialize v3 candidate MP4s, sampled frames, and review metadata."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import artifact_resolver
from pipeline.preprocessing import MiniCPMVideoPreprocessor  # noqa: E402
from pipeline.current_data import data_context_from_arg  # noqa: E402
from pipeline.v3_candidate_media import (  # noqa: E402
    CandidateMediaError,
    load_media_plan,
    materialize_media_plan,
    require_tools,
)


DEFAULT_MODEL = PROJECT_ROOT / "models/minicpmv4_5"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从冻结 v3 候选计划生成版本化 MP4、真实 MiniCPM 抽帧和门禁结果"
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--candidate-plan", type=Path, default=None)
    parser.add_argument("--roi-media", type=Path, default=None)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument(
        "--scope",
        choices=("development", "test_audit", "all"),
        default="all",
    )
    parser.add_argument("--candidate-ids", nargs="+", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--video-output-root", type=Path)
    parser.add_argument("--frame-output-root", type=Path)
    parser.add_argument("--result-root", type=Path)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="验证输入、源媒体、处理器身份和输出身份，但不生成媒体",
    )
    return parser


def _resolve_inputs(args: argparse.Namespace, context) -> None:
    args.candidate_plan = artifact_resolver.resolve_cli_artifact_path(
        context.metadata_collection("candidate_plans"),
        args.candidate_plan,
    )
    args.roi_media = artifact_resolver.resolve_cli_artifact_path(
        context.roi_videos,
        args.roi_media,
    )


def _is_subset(args: argparse.Namespace) -> bool:
    return args.scope != "all" or args.candidate_ids is not None or args.limit is not None


def _require_isolated_subset_outputs(args: argparse.Namespace) -> None:
    if not _is_subset(args):
        return
    if any(
        value is None
        for value in (
            args.video_output_root,
            args.frame_output_root,
            args.result_root,
        )
    ):
        raise CandidateMediaError(
            "子集/小样本生成必须同时指定隔离的 --video-output-root、"
            "--frame-output-root 和 --result-root"
        )


def main() -> int:
    args = build_parser().parse_args()
    try:
        _require_isolated_subset_outputs(args)
        context = data_context_from_arg(PROJECT_ROOT, args.data_root)
        _resolve_inputs(args, context)
        args.video_output_root = args.video_output_root or context.subvideos
        args.frame_output_root = args.frame_output_root or context.frames
        args.result_root = args.result_root or (
            context.metadata_collection("candidate_media_results")
        )
        args.video_output_root = context.require_managed_output(
            args.video_output_root,
            context.subvideos,
            label="candidate video output",
        )
        args.frame_output_root = context.require_managed_output(
            args.frame_output_root,
            context.frames,
            label="candidate frame output",
        )
        args.result_root = context.require_managed_output(
            args.result_root,
            context.metadata_collection("candidate_media_results"),
            label="candidate metadata output",
        )
        require_tools()
        processor = MiniCPMVideoPreprocessor(
            model_path_or_name=str(args.model),
            max_frames=8,
            eager_load=not args.check_only,
        )
        fingerprint = processor.fingerprint(
            backend_override=(
                "transformers-loaded" if args.check_only else None
            )
        )
        scopes = (
            ("development", "test_audit")
            if args.scope == "all"
            else (args.scope,)
        )
        plan = load_media_plan(
            args.candidate_plan,
            args.roi_media,
            context.root,
            processor_fingerprint=fingerprint,
            scopes=scopes,
            candidate_ids=args.candidate_ids,
            limit=args.limit,
        )
        summary = {
            "media_id": plan["media_id"],
            "candidate_plan_id": plan["candidate_plan_id"],
            "candidate_count": len(plan["candidates"]),
            "full_scope": plan["full_scope"],
            "processor_fingerprint": fingerprint,
            "check_only": args.check_only,
        }
        if args.check_only:
            print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        destination = materialize_media_plan(
            plan,
            model_path=str(args.model),
            video_output_root=args.video_output_root,
            frame_output_root=args.frame_output_root,
            result_root=args.result_root,
            preprocessor=processor,
        )
        manifest = json.loads(
            (destination / "manifest.json").read_text(encoding="utf-8")
        )
        summary["destination"] = str(destination)
        summary["counts"] = manifest["counts"]
        summary["media_generated"] = True
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except CandidateMediaError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
