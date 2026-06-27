from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import (
    compute_joint_interval_metrics,
    dump_summary_with_overall,
    finalize_joint_aggregator,
    init_joint_aggregator,
    load_split_video_names,
    load_test_video_names,
    read_jsonl,
    read_results_and_meta,
    update_joint_aggregator,
    write_csv,
    write_json,
)
from .config import SPLIT_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate joint task usability results.")
    parser.add_argument("--inputs", nargs="+", required=True, help="Input JSONL files.")
    parser.add_argument("--meta", nargs="+", required=True,
                        help="Path(s) to meta JSONL file(s), paired with --inputs")
    parser.add_argument("--out-dir", required=True, help="Directory for evaluation artifacts.")
    parser.add_argument(
        "--split",
        default=None,
        help="Split name to filter records (e.g., 'test', 'fold_0_val'). "
             "When given, only video_ids in the split are evaluated.",
    )
    return parser.parse_args()


def _load_split_video_ids(split: str) -> set[str]:
    """Load video_id set from a named split; supports 'test' and 'fold_N_val'."""
    if split == "test":
        names = load_test_video_names()
    elif split.startswith("fold_") and split.endswith("_val"):
        fold = int(split.split("_")[1])
        names = load_split_video_names(fold)
    else:
        split_path = SPLIT_DIR / f"{split}.json"
        split_data = json.loads(split_path.read_text(encoding="utf-8"))
        names = [f"{video_id}.mp4" for video_id in split_data.get("video_ids", [])]
    return {Path(name).stem for name in names}


def main() -> None:
    args = parse_args()
    records = read_results_and_meta(args.inputs, args.meta)
    if args.split:
        split_ids = _load_split_video_ids(args.split)
        records = [r for r in records if r["video_id"] in split_ids]

    if not records:
        raise ValueError(f"No records found after filtering split={args.split}. Input files: {args.inputs}")

    by_fold: dict[str, list[dict[str, object]]] = {}
    for record in records:
        fold_key = args.split if args.split else str(record.get("fold", "unknown"))
        by_fold.setdefault(fold_key, []).append(record)

    # Legacy joint aggregator (backward compat)
    per_fold_legacy = {}
    overall_agg = init_joint_aggregator()
    failure_rows = []
    for fold, fold_records in sorted(by_fold.items()):
        fold_agg = init_joint_aggregator()
        for record in fold_records:
            update_joint_aggregator(fold_agg, record)
            update_joint_aggregator(overall_agg, record)
            if record.get("failure_reason"):
                failure_rows.append(
                    {
                        "fold": fold,
                        "video_id": record["video_id"],
                        "gt_type": record["gt_type"],
                        "time_available": record["time_available"],
                        "failure_reason": record["failure_reason"],
                    }
                )
        fold_legacy = finalize_joint_aggregator(fold_agg)
        # Compute per-fold interval joint metrics too
        fold_joint_interval, _ = compute_joint_interval_metrics(fold_records)
        per_fold_legacy[fold] = {
            "joint_interval_metrics": fold_joint_interval,
            "deprecated_legacy_metrics": fold_legacy,
        }
    
    overall_legacy = finalize_joint_aggregator(overall_agg)
    
    # NEW: interval-based joint metrics
    joint_interval_summary, joint_interval_failures = compute_joint_interval_metrics(records)
    
    # Merge both into the output
    merged_overall = {
        "joint_interval_metrics": joint_interval_summary,
        "deprecated_legacy_metrics": overall_legacy,
        "_note": "'deprecated_legacy_metrics' uses the old time-threshold-based joint aggregator. "
                  "For interval 5-field protocol evaluations, use 'joint_interval_metrics' as the primary metric source.",
    }

    out_dir = Path(args.out_dir)
    write_json(out_dir / "joint_metrics.json", dump_summary_with_overall(per_fold_legacy, merged_overall))
    write_csv(
        out_dir / "joint_failures.csv",
        ["fold", "video_id", "gt_type", "time_available", "failure_reason"],
        failure_rows,
    )
    
    # NEW: joint interval failure detail
    if joint_interval_failures:
        write_csv(
            out_dir / "joint_interval_failures.csv",
            ["video_id", "gt_type", "failure_reason", "details"],
            joint_interval_failures,
        )
    
    # NEW: invalid schema output
    invalid_schema_rows = []
    for r in records:
        if not r.get("schema_valid", True) or not r.get("json_valid", False):
            invalid_schema_rows.append({
                "video_id": r.get("video_id"),
                "json_valid": r.get("json_valid", False),
                "schema_valid": r.get("schema_valid", False),
                "schema_errors": r.get("schema_errors", ""),
                "gt_type": r.get("gt_type"),
            })
    if invalid_schema_rows:
        write_csv(
            out_dir / "invalid_schema.csv",
            ["video_id", "json_valid", "schema_valid", "schema_errors", "gt_type"],
            invalid_schema_rows,
        )
    
    print(f"Wrote joint evaluation artifacts to {out_dir}")
    print(f"  legacy joint_success_rate={overall_legacy.get('joint_success_rate')}")
    print(f"  interval joint_success_rate={joint_interval_summary.get('joint_success_rate')}")
    print(f"  failure_reasons={joint_interval_summary.get('failure_reasons')}")


if __name__ == "__main__":
    main()
