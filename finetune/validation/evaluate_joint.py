from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    dump_summary_with_overall,
    finalize_joint_aggregator,
    init_joint_aggregator,
    read_jsonl,
    update_joint_aggregator,
    write_csv,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate joint task usability results.")
    parser.add_argument("--inputs", nargs="+", required=True, help="Input JSONL files.")
    parser.add_argument("--out-dir", required=True, help="Directory for evaluation artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = read_jsonl(args.inputs)

    by_fold: dict[int, list[dict[str, object]]] = {}
    for record in records:
        by_fold.setdefault(int(record["fold"]), []).append(record)

    per_fold = {}
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
        per_fold[fold] = finalize_joint_aggregator(fold_agg)

    out_dir = Path(args.out_dir)
    write_json(out_dir / "joint_metrics.json", dump_summary_with_overall(per_fold, finalize_joint_aggregator(overall_agg)))
    write_csv(
        out_dir / "joint_failures.csv",
        ["fold", "video_id", "gt_type", "time_available", "failure_reason"],
        failure_rows,
    )
    print(f"Wrote joint evaluation artifacts to {out_dir}")


if __name__ == "__main__":
    main()
