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

from pipeline.preprocessing import MiniCPMVideoPreprocessor  # noqa: E402
from pipeline.v3_candidate_media import (  # noqa: E402
    CandidateMediaError,
    load_media_plan,
    materialize_media_plan,
    require_tools,
)


DEFAULT_PLAN_ID = "candidate-plan-ce36b9226be5"
DEFAULT_CANDIDATE_PLAN = (
    PROJECT_ROOT / "data/07_metadata/v3/candidate_plans" / DEFAULT_PLAN_ID
)
DEFAULT_ROI_MEDIA = (
    PROJECT_ROOT
    / "data/03_roi_videos/roi-media-84ea2bd3a052"
)
DEFAULT_MODEL = PROJECT_ROOT / "models/minicpmv4_5"
DEFAULT_VIDEO_OUTPUT_ROOT = PROJECT_ROOT / "data/03_subvideos_roi"
DEFAULT_FRAME_OUTPUT_ROOT = PROJECT_ROOT / "data/04_frames_roi"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "data/07_metadata/v3/candidate_media_results"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从冻结 v3 候选计划生成版本化 MP4、真实 MiniCPM 抽帧和门禁结果"
    )
    parser.add_argument("--candidate-plan", type=Path, default=DEFAULT_CANDIDATE_PLAN)
    parser.add_argument("--roi-media", type=Path, default=DEFAULT_ROI_MEDIA)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument(
        "--scope",
        choices=("development", "test_audit", "all"),
        default="all",
    )
    parser.add_argument("--candidate-ids", nargs="+", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--video-output-root", type=Path, default=DEFAULT_VIDEO_OUTPUT_ROOT)
    parser.add_argument("--frame-output-root", type=Path, default=DEFAULT_FRAME_OUTPUT_ROOT)
    parser.add_argument("--result-root", type=Path, default=DEFAULT_RESULT_ROOT)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="验证输入、源媒体、处理器身份和输出身份，但不生成媒体",
    )
    return parser


def _is_subset(args: argparse.Namespace) -> bool:
    return args.scope != "all" or args.candidate_ids is not None or args.limit is not None


def _require_isolated_subset_outputs(args: argparse.Namespace) -> None:
    if not _is_subset(args):
        return
    defaults = {
        args.video_output_root.resolve() == DEFAULT_VIDEO_OUTPUT_ROOT.resolve(),
        args.frame_output_root.resolve() == DEFAULT_FRAME_OUTPUT_ROOT.resolve(),
        args.result_root.resolve() == DEFAULT_RESULT_ROOT.resolve(),
    }
    if True in defaults:
        raise CandidateMediaError(
            "子集/小样本生成必须同时指定隔离的 --video-output-root、"
            "--frame-output-root 和 --result-root"
        )


def main() -> int:
    args = build_parser().parse_args()
    try:
        require_tools()
        processor = MiniCPMVideoPreprocessor(
            model_path_or_name=str(args.model), max_frames=8
        )
        fingerprint = processor.fingerprint()
        scopes = (
            ("development", "test_audit")
            if args.scope == "all"
            else (args.scope,)
        )
        plan = load_media_plan(
            args.candidate_plan,
            args.roi_media,
            PROJECT_ROOT,
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
        _require_isolated_subset_outputs(args)
        destination = materialize_media_plan(
            plan,
            model_path=str(args.model),
            video_output_root=args.video_output_root,
            frame_output_root=args.frame_output_root,
            result_root=args.result_root,
            preprocessor=processor,
        )
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
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
