from __future__ import annotations

import argparse
from pathlib import Path

from common import compute_type_metrics, dump_summary_with_overall, read_jsonl, write_csv, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate fracture-type classification results.")
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
    overall_summary, overall_per_class, overall_confusion = compute_type_metrics(records)
    for fold, fold_records in sorted(by_fold.items()):
        fold_summary, _, _ = compute_type_metrics(fold_records)
        per_fold[fold] = fold_summary

    out_dir = Path(args.out_dir)
    write_json(out_dir / "type_metrics.json", dump_summary_with_overall(per_fold, overall_summary))
    write_csv(out_dir / "type_per_class.csv", ["label", "support", "precision", "recall", "f1"], overall_per_class)
    confusion_fields = list(overall_confusion[0].keys()) if overall_confusion else ["gt_type"]
    write_csv(out_dir / "type_confusion_matrix.csv", confusion_fields, overall_confusion)
    print(f"Wrote type evaluation artifacts to {out_dir}")


if __name__ == "__main__":
    main()
