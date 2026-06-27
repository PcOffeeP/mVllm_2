from __future__ import annotations

import argparse
import json
from pathlib import Path

from .common import (
    compute_type_metrics,
    dump_summary_with_overall,
    load_split_video_names,
    load_test_video_names,
    read_jsonl,
    read_results_and_meta,
    write_csv,
    write_json,
)
from .config import SPLIT_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate fracture-type classification results.")
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

    per_fold = {}
    overall_summary, overall_per_class, overall_confusion = compute_type_metrics(records)
    for fold, fold_records in sorted(by_fold.items()):
        fold_summary, _, _ = compute_type_metrics(fold_records)
        per_fold[fold] = fold_summary

    out_dir = Path(args.out_dir)
    write_json(out_dir / "type_metrics.json", dump_summary_with_overall(per_fold, overall_summary))
    write_csv(out_dir / "type_per_class.csv", ["label", "support", "precision", "recall", "f1"], overall_per_class)
    confusion_fields = list(overall_confusion[0].keys()) if overall_confusion else ["gt_type"]
    write_csv(out_dir / "type_confusion_matrix.csv", confusion_fields, overall_confusion)

    # NEW: output invalid schema samples
    invalid_schema_rows = []
    for r in records:
        if not r.get("schema_valid", True) or not r.get("json_valid", False):
            invalid_schema_rows.append({
                "video_id": r.get("video_id"),
                "json_valid": r.get("json_valid", False),
                "schema_valid": r.get("schema_valid", False),
                "schema_errors": r.get("schema_errors", ""),
                "gt_type": r.get("gt_type"),
                "pred_type_norm": r.get("pred_type_norm"),
            })
    if invalid_schema_rows:
        write_csv(
            out_dir / "invalid_schema.csv",
            ["video_id", "json_valid", "schema_valid", "schema_errors", "gt_type", "pred_type_norm"],
            invalid_schema_rows,
        )
    print(f"Wrote type evaluation artifacts to {out_dir}")
    print(f"  accuracy={overall_summary.get('accuracy')}, macro_f1={overall_summary.get('macro_f1')}, "
          f"false_positive_rate={overall_summary.get('false_positive_rate')}")


if __name__ == "__main__":
    main()
