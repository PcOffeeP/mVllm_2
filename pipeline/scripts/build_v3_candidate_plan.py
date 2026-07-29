#!/usr/bin/env python3
"""Build a v3 candidate metadata plan without materializing media."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.v3_candidate_plan import (
    build_candidate_plan,
    load_plan_inputs,
    materialize_candidate_plan,
)
from pipeline.current_data import current_data_context, data_context_from_arg
from pipeline.review_evidence import REFERENCE_SCHEMA_VERSION


CURRENT_DATA = current_data_context(PROJECT_ROOT)
DEFAULT_ROI_MEDIA_DIR = (
    CURRENT_DATA.metadata
    / "v3/roi_media_results/roi-media-84ea2bd3a052"
)
DEFAULT_REVIEW_REFERENCE_DIR = (
    CURRENT_DATA.legacy_metadata_collection("review_reference")
    / "review-ref-7cd2e73a1cd1"
)
DEFAULT_CONTRACT = PROJECT_ROOT / "pipeline" / "contracts" / "tensile_vlm_v3.json"
DEFAULT_OUTPUT_ROOT = CURRENT_DATA.metadata_collection("candidate_plans")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成 v3 子视频候选计划和统计；不会生成 MP4 或帧图"
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--roi-media-dir", type=Path)
    parser.add_argument("--review-reference-dir", type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只计算并打印计划身份与统计，不创建任何输出目录",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    context = data_context_from_arg(PROJECT_ROOT, args.data_root)
    args.roi_media_dir = args.roi_media_dir or (
        context.metadata
        / "v3/roi_media_results/roi-media-84ea2bd3a052"
    )
    args.review_reference_dir = args.review_reference_dir or (
        context.metadata_artifact_path(
            "review_reference",
            "review-ref-7cd2e73a1cd1",
            expected_schema=REFERENCE_SCHEMA_VERSION,
        )
    )
    args.output_root = (
        args.output_root or context.metadata_collection("candidate_plans")
    )
    args.output_root = context.require_managed_output(
        args.output_root,
        context.metadata_collection("candidate_plans"),
        label="candidate plan output",
    )
    inputs = load_plan_inputs(
        args.roi_media_dir,
        args.review_reference_dir,
        args.contract,
        data_root=context.root,
    )
    plan = build_candidate_plan(inputs)
    summary = {
        "plan_id": plan["plan_id"],
        "dry_run": args.dry_run,
        "development_candidate_count": len(plan["development_candidates"]),
        "test_candidate_audit_count": len(plan["test_candidate_audit"]),
        "development_needs_review_count": len(plan["needs_review"]),
        "statistics": plan["statistics"],
        "media_generated": False,
    }
    if not args.dry_run:
        destination = materialize_candidate_plan(plan, args.output_root)
        summary["output_dir"] = str(destination)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
