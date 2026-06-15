from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    dump_summary_with_overall,
    finalize_time_aggregator,
    init_time_aggregator,
    read_jsonl,
    update_time_aggregator,
    write_csv,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate time-localization results.")
    parser.add_argument("--inputs", nargs="+", required=True, help="Input JSONL files.")
    parser.add_argument("--out-dir", required=True, help="Directory for evaluation artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = read_jsonl(args.inputs)
    per_fold: dict[int, dict[str, object]] = {}
    overall_agg = init_time_aggregator()
    error_rows = []
    excluded_rows = []

    by_fold: dict[int, list[dict[str, object]]] = {}
    for record in records:
        by_fold.setdefault(int(record["fold"]), []).append(record)

    for fold, fold_records in sorted(by_fold.items()):
        fold_agg = init_time_aggregator()
        for record in fold_records:
            update_time_aggregator(fold_agg, record)
            update_time_aggregator(overall_agg, record)
            if not record["time_available"]:
                excluded_rows.append(
                    {
                        "fold": fold,
                        "video_id": record["video_id"],
                        "gt_type": record["gt_type"],
                        "failure_reason": record.get("failure_reason"),
                    }
                )
                continue
            if record.get("pred_time_sec") is not None:
                error_rows.append(
                    {
                        "fold": fold,
                        "video_id": record["video_id"],
                        "gt_time_sec": record["gt_time_sec"],
                        "pred_time_sec": record["pred_time_sec"],
                        "abs_error_sec": round(abs(record["pred_time_sec"] - record["gt_time_sec"]), 6),
                    }
                )
        per_fold[fold] = finalize_time_aggregator(fold_agg)

    out_dir = Path(args.out_dir)
    write_json(out_dir / "time_metrics.json", dump_summary_with_overall(per_fold, finalize_time_aggregator(overall_agg)))
    write_csv(
        out_dir / "time_errors.csv",
        ["fold", "video_id", "gt_time_sec", "pred_time_sec", "abs_error_sec"],
        error_rows,
    )
    write_csv(
        out_dir / "time_excluded_samples.csv",
        ["fold", "video_id", "gt_type", "failure_reason"],
        excluded_rows,
    )
    print(f"Wrote time evaluation artifacts to {out_dir}")


if __name__ == "__main__":
    main()
