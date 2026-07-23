#!/usr/bin/env python3
"""Build an immutable v4 review queue from verified v3 candidate media."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.v4_review_workflow import build_v4_review_queue, save_v4_review_queue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v3-queue", type=Path, required=True)
    parser.add_argument("--v3-manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--contract",
        type=Path,
        default=PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v4.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data/07_metadata/v4/review_queues",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = build_v4_review_queue(
        v3_queue_path=args.v3_queue,
        v3_manifest_path=args.v3_manifest,
        project_root=args.project_root,
        contract_path=args.contract,
    )
    output = args.output_root / payload["queue_id"] / "review_queue.json"
    if not args.check:
        save_v4_review_queue(output, payload)
    print(
        json.dumps(
            {
                "queue_id": payload["queue_id"],
                "candidate_count": payload["candidate_count"],
                "migration_issue_count": payload["migration_issue_count"],
                "output": str(output.resolve()),
                "written": not args.check,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
