#!/usr/bin/env python3
"""Freeze the Stage D run preparation without authorizing sealed inference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.v4_1_stage_d_runtime import (
    build_preparation,
    freeze_preparation,
    pretty_bytes,
    sha256_bytes,
)
from pipeline.current_data import current_data_paths

FINETUNE = ROOT / "finetune"
MODEL_DIR = (
    ROOT
    / "LlamaFactory/saves/minicpmv4_5/lora/"
    "sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_"
    "2a84e8b6cfc3_seed3407_merged"
)
MODEL_AGGREGATE_SHA256 = (
    "1f75e4f91db487273588c1e1c8bf867b20acdfc565c191d914915b366c4c1b1c"
)


def parse_args() -> argparse.Namespace:
    paths = current_data_paths(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=(
            paths.root
            / "sealed_test_releases/v4.1-sealed-test-5546b8bf1ec3"
        ),
    )
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    parser.add_argument(
        "--stage-b-acceptance",
        type=Path,
        default=(
            FINETUNE
            / "results/v4_1_stage_b_intermediate_acceptances/"
            "stage-b-intermediate-8e1fdb09f8e6/"
            "intermediate_model_acceptance.json"
        ),
    )
    parser.add_argument(
        "--deployment-summary",
        type=Path,
        default=(
            ROOT
            / "docs/results/v4_1_stage_e_pre_acceptance/"
            "deployment_summary.json"
        ),
    )
    parser.add_argument("--agent-acceptance-summary", type=Path, required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=FINETUNE / "results/v4_1_stage_d_runs",
    )
    parser.add_argument(
        "--preparations-root",
        type=Path,
        default=FINETUNE / "results/v4_1_stage_d_preparations",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preparation = build_preparation(
        project_root=ROOT,
        release_dir=args.release_dir,
        model_dir=args.model_dir,
        model_aggregate_sha256=MODEL_AGGREGATE_SHA256,
        stage_b_acceptance_path=args.stage_b_acceptance,
        deployment_summary_path=args.deployment_summary,
        agent_acceptance_summary_path=args.agent_acceptance_summary,
        contract_path=args.contract,
        runner_path=FINETUNE / "run_v4_1_stage_d.py",
        evaluator_path=FINETUNE / "run_v4_1_evaluation.py",
        model_runtime_path=FINETUNE / "validation/model_runtime.py",
        scoring_runtime_path=FINETUNE / "v4_1_runtime.py",
        output_root=args.output_root,
    )
    path = (
        args.preparations_root
        / preparation["preparation_id"]
        / "prepared_run_manifest.json"
    )
    if not args.validate_only:
        freeze_preparation(path, preparation)
    print(
        json.dumps(
            {
                "mode": "validate-only" if args.validate_only else "frozen",
                "preparation_id": preparation["preparation_id"],
                "prepared_manifest": str(path),
                "prepared_manifest_content_sha256": sha256_bytes(
                    pretty_bytes(preparation)
                ),
                "status": preparation["status"],
                "sample_count": preparation["sealed_test"]["sample_count"],
                "authorization": preparation["authorization"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
