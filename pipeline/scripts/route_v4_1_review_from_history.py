#!/usr/bin/env python3
"""Build one manual-only V4.1 review route from a frozen previous batch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.current_data import current_data_paths
from pipeline.v4_1_review_routing import build_history_review_route


def main() -> None:
    paths = current_data_paths(PROJECT_ROOT)
    parser = argparse.ArgumentParser(
        description="以上一轮冻结人工审查为基准分流 V4.1 当前候选"
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--previous-decisions", type=Path, required=True)
    parser.add_argument("--current-draft", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=paths.compatibility_workspace,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=paths.metadata / "v4_1/review_routes",
    )
    parser.add_argument(
        "--review-decisions-root",
        type=Path,
        default=paths.metadata / "v4_1/review_decisions",
    )
    args = parser.parse_args()
    route_dir, manifest = build_history_review_route(
        queue_path=args.queue,
        previous_decisions_path=args.previous_decisions,
        current_draft_path=args.current_draft,
        project_root=args.project_root,
        output_root=args.output_root,
        review_decisions_root=args.review_decisions_root,
    )
    print(
        json.dumps(
            {
                "routing_id": manifest["routing_id"],
                "counts": manifest["counts"],
                "output": str(route_dir.resolve()),
                "manual_draft": manifest["manual_review"]["draft_path"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
