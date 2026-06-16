from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    dump_summary_with_overall,
    finalize_joint_aggregator,
    init_joint_aggregator,
    load_split_video_names,
    load_test_video_names,
    read_jsonl,
    update_joint_aggregator,
    write_csv,
    write_json,
)
from config import SPLIT_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate joint task usability results.")
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

    by_fold: dict[str, list[dict[str, object]]] = {}
    for record in records:
        fold_key = args.split if args.split else str(record["fold"])
        by_fold.setdefault(fold_key, []).append(record)

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
