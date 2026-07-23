#!/usr/bin/env python3
"""Build the v4.1 observed plus incipient review queue from existing media."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.v4_1_review_workflow import (
    build_v4_1_review_queue,
    save_v4_1_review_queue,
)
from pipeline.current_data import current_data_paths


def main() -> None:
    paths = current_data_paths(PROJECT_ROOT)
    parser = argparse.ArgumentParser()
    parser.add_argument("--materialized", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=paths.compatibility_workspace,
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=PROJECT_ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=paths.metadata / "v4_1/review_queues",
    )
    args = parser.parse_args()
    payload = build_v4_1_review_queue(
        materialized_path=args.materialized,
        manifest_path=args.manifest,
        project_root=args.project_root,
        contract_path=args.contract,
    )
    output = args.output_root / payload["queue_id"] / "review_queue.json"
    save_v4_1_review_queue(output, payload)
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


if __name__ == "__main__":
    main()
