from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    dump_summary_with_overall,
    finalize_time_aggregator,
    init_time_aggregator,
    load_split_video_names,
    load_test_video_names,
    read_jsonl,
    update_time_aggregator,
    write_csv,
    write_json,
)
from config import SPLIT_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate time-localization results.")
    parser.add_argument("--inputs", nargs="+", required=True, help="Input JSONL files.")
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
    records = read_jsonl(args.inputs)
    if args.split:
        split_ids = _load_split_video_ids(args.split)
        records = [r for r in records if r["video_id"] in split_ids]

    per_fold: dict[str, dict[str, object]] = {}
    overall_agg = init_time_aggregator()
    error_rows = []
    excluded_rows = []
    bucket_rows = []

    by_fold: dict[str, list[dict[str, object]]] = {}
    for record in records:
        fold_key = args.split if args.split else str(record["fold"])
        by_fold.setdefault(fold_key, []).append(record)

    for fold_key, fold_records in sorted(by_fold.items()):
        fold_agg = init_time_aggregator()
        for record in fold_records:
            update_time_aggregator(fold_agg, record)
            update_time_aggregator(overall_agg, record)
            if not record["time_available"]:
                excluded_rows.append(
                    {
                        "fold": fold_key,
                        "video_id": record["video_id"],
                        "gt_type": record["gt_type"],
                        "failure_reason": record.get("failure_reason"),
                    }
                )
                continue
            if record.get("pred_time_sec") is not None:
                error_rows.append(
                    {
                        "fold": fold_key,
                        "video_id": record["video_id"],
                        "gt_time_sec": record["gt_time_sec"],
                        "pred_time_sec": record["pred_time_sec"],
                        "abs_error_sec": round(abs(record["pred_time_sec"] - record["gt_time_sec"]), 6),
                    }
                )
        fold_metrics = finalize_time_aggregator(fold_agg)
        per_fold[fold_key] = fold_metrics
        for bucket in fold_metrics["confidence_buckets"]:
            bucket_rows.append({"fold": fold_key, **bucket})

    overall_metrics = finalize_time_aggregator(overall_agg)

    out_dir = Path(args.out_dir)
    write_json(out_dir / "time_metrics.json", dump_summary_with_overall(per_fold, overall_metrics))
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
    if bucket_rows:
        write_csv(
            out_dir / "time_confidence_buckets.csv",
            ["fold", "bucket", "count", "avg_confidence", "range_hit_rate", "within_1s_rate", "within_3s_rate", "within_5s_rate"],
            bucket_rows,
        )
    print(f"Wrote time evaluation artifacts to {out_dir}")


if __name__ == "__main__":
    main()
