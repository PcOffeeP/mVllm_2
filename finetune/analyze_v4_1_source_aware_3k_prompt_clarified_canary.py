#!/usr/bin/env python3
"""Gate one prompt-clarified canary before spending on the second seed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.v4_1_source_aware_3k_prompt_clarified import configure_runner

configure_runner()

import finetune.analyze_v4_1_source_aware_3k as analysis  # noqa: E402


def analyze_canary(
    *,
    seed: int,
    baseline_path: Path,
    records_path: Path,
) -> dict[str, Any]:
    if seed not in analysis.SEEDS:
        raise analysis.StageBGateError(f"不支持的 seed: {seed}")
    baseline_records = analysis._read_records(baseline_path)
    records = analysis._read_records(records_path)
    if {
        str(record["candidate_id"]) for record in baseline_records
    } != {str(record["candidate_id"]) for record in records}:
        raise analysis.StageBGateError(
            f"seed{seed}: 与旧正式 fold0 candidate 集不一致"
        )
    metrics = analysis.summarize(records)
    absolute_gates = analysis._absolute_gate_results(metrics)
    loso = analysis._loso_analysis(baseline_records, records)
    passed = (
        all(bool(item["passed"]) for item in absolute_gates.values())
        and bool(loso["passed"])
    )
    return {
        "schema_version": (
            "tensile-vlm-v4.1-source-aware-3k-canary-gates/v1"
        ),
        "run_id": analysis.RUN_ID,
        "release_id": analysis.RELEASE_ID,
        "seed": seed,
        "baseline": {
            "run_id": analysis.BASELINE_RUN_ID,
            "records_path": str(baseline_path.resolve()),
            "records_sha256": analysis._sha256(baseline_path),
            "metrics": analysis.summarize(baseline_records),
        },
        "records_path": str(records_path.resolve()),
        "records_sha256": analysis._sha256(records_path),
        "metrics": metrics,
        "absolute_gates": absolute_gates,
        "source_error_analysis": analysis._source_error_analysis(records),
        "leave_one_source_out": loso,
        "passed": passed,
        "next_action": (
            "start_second_seed"
            if passed
            else "freeze_failure_and_continue_development_only_attribution"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, choices=analysis.SEEDS, default=3407)
    parser.add_argument(
        "--baseline-records",
        type=Path,
        default=analysis.BASELINE_ROOT / "evaluation_records.jsonl",
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=(
            analysis.RESULT_ROOT
            / "seed3407/fold0/evaluation_records.jsonl"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=analysis.RESULT_ROOT / "seed3407_canary_gate_report.json",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = analyze_canary(
        seed=args.seed,
        baseline_path=args.baseline_records,
        records_path=args.records,
    )
    if not args.validate_only:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
