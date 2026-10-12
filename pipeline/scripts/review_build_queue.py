#!/usr/bin/env python3
"""Build the v4.1 observed plus incipient review queue from existing media."""

from __future__ import annotations

import sys


def main() -> int:
    message = (
        "此历史数据辅助 CLI 已停用。请使用 python -m versioning data <stage>，"
        "显式指定 --root、--inputs、--batch；发布时另需完整 --version。"
        "ROI和候选媒体使用roi/subvideo阶段，审查包使用review_export；"
        "历史Phase2对象按已确认mapping迁移，不重建或重新审批。"
        "操作说明见 docs/data-workflow.md。"
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

from pipeline import artifact_resolver
from pipeline.v4_1_review_workflow import (
    append_review_queue_index,
    build_v4_1_review_queue,
    save_v4_1_review_queue,
)
from pipeline.current_data import data_context_from_arg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--materialized", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
    )
    return parser


def _resolve_inputs(args: argparse.Namespace, context) -> None:
    args.project_root = args.project_root or context.root
    args.materialized = artifact_resolver.resolve_cli_artifact_path(
        context.metadata_collection("candidate_media_results"),
        args.materialized,
        artifact_subpath="development_materialized.json",
    )
    args.manifest = artifact_resolver.resolve_cli_artifact_path(
        context.metadata_collection("candidate_media_results"),
        args.manifest,
        artifact_subpath="manifest.json",
    )
    if args.output_root is None:
        args.output_root = context.metadata_collection("review_queues")


def _legacy_main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    context = data_context_from_arg(PROJECT_ROOT, args.data_root)
    _resolve_inputs(args, context)
    args.output_root = context.require_managed_output(
        args.output_root,
        context.metadata_collection("review_queues"),
        label="review queue output",
    )
    payload = build_v4_1_review_queue(
        materialized_path=args.materialized,
        manifest_path=args.manifest,
        project_root=args.project_root,
        contract_path=args.contract,
    )
    output = args.output_root / payload["queue_id"] / "review_queue.json"
    save_v4_1_review_queue(output, payload)
    append_review_queue_index(args.output_root, payload)
    print(
        json.dumps(
            {
                "queue_id": payload["queue_id"],
                "candidate_count": payload["candidate_count"],
                "observed_count": payload["observed_count"],
                "incipient_count": payload["incipient_count"],
                "output": str(output.resolve()),
            },
            ensure_ascii=False,
        )
    )
