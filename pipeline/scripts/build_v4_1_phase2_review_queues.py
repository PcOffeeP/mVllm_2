#!/usr/bin/env python3
"""Build isolated development and sealed-test review queues from Phase 1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.current_data import current_data_paths
from pipeline.v4_1_review_workflow import (
    build_phase2_review_queue,
    save_v4_1_review_queue,
)


def main() -> None:
    paths = current_data_paths(PROJECT_ROOT)
    parser = argparse.ArgumentParser(
        description="从阶段 1 有效视图审计生成隔离的 V4.1 人工审查队列"
    )
    parser.add_argument("--audit-manifest", type=Path, required=True)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=paths.root,
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

    outputs: dict[str, dict[str, object]] = {}
    for scope in ("development", "sealed_test"):
        payload = build_phase2_review_queue(
            audit_manifest_path=args.audit_manifest,
            scope=scope,
            project_root=args.project_root,
            contract_path=args.contract,
        )
        output = args.output_root / payload["queue_id"] / "review_queue.json"
        save_v4_1_review_queue(output, payload)
        outputs[scope] = {
            "queue_id": payload["queue_id"],
            "candidate_count": payload["candidate_count"],
            "labels_are_truth": payload["labels_are_truth"],
            "output": str(output.resolve()),
        }
    print(json.dumps(outputs, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
