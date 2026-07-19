from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from .run_evaluation import summarize


TASK_METRIC_KEYS = (
    "has_fracture_accuracy",
    "type_accuracy",
    "type_accuracy_positive",
    "location_accuracy",
    "location_accuracy_positive",
    "interval_exact_accuracy",
    "time_hit_rate",
    "joint_success_rate",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate three fold evaluation directories.")
    parser.add_argument(
        "--fold",
        action="append",
        required=True,
        metavar="NAME=DIR",
        help="Fold name and evaluation directory; pass exactly three times.",
    )
    parser.add_argument("--out", required=True, help="Output JSON path.")
    return parser.parse_args()


def aggregate_fold_results(folds: dict[str, Path]) -> dict[str, Any]:
    if len(folds) != 3:
        raise ValueError(f"Expected exactly three folds, got {len(folds)}")

    summaries: dict[str, dict[str, Any]] = {}
    all_records: list[dict[str, Any]] = []
    for name, directory in sorted(folds.items()):
        summary_path = directory / "evaluation_summary.json"
        records_path = directory / "evaluation_records.jsonl"
        summary = _read_object(summary_path)
        records = _read_jsonl(records_path)
        expected_total = summary.get("metrics", {}).get("total_samples")
        if expected_total != len(records):
            raise ValueError(
                f"{name}: summary total_samples={expected_total} but records={len(records)}"
            )
        summaries[name] = summary
        all_records.extend(records)

    release_ids = {summary.get("active_release_id") for summary in summaries.values()}
    prompt_hashes = {summary.get("system_prompt_hash") for summary in summaries.values()}
    if len(release_ids) != 1 or None in release_ids:
        raise ValueError(f"Fold results do not share one active_release_id: {release_ids}")
    if len(prompt_hashes) != 1 or None in prompt_hashes:
        raise ValueError(f"Fold results do not share one system_prompt_hash: {prompt_hashes}")

    per_fold = {
        name: {
            "dataset": summary.get("dataset"),
            "model_dir": summary.get("model_dir"),
            "metrics": summary.get("metrics"),
        }
        for name, summary in summaries.items()
    }
    return {
        "schema_version": "1.0",
        "active_release_id": next(iter(release_ids)),
        "system_prompt_hash": next(iter(prompt_hashes)),
        "fold_count": len(folds),
        "per_fold": per_fold,
        "macro_task_metrics": _macro_task_metrics(summaries),
        "pooled_metrics": summarize(all_records),
        "total_records": len(all_records),
        "notes": [
            "Macro metrics are unweighted means across folds with population standard deviation.",
            "Pooled metrics are recomputed from all per-sample records and retain invalid outputs in denominators.",
        ],
    }


def main() -> None:
    args = parse_args()
    folds = _parse_fold_args(args.fold)
    result = aggregate_fold_results(folds)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote three-fold aggregate to {output}")


def _parse_fold_args(values: list[str]) -> dict[str, Path]:
    folds: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Expected NAME=DIR, got {value!r}")
        name, raw_path = value.split("=", 1)
        name = name.strip()
        if not name or name in folds:
            raise ValueError(f"Invalid or duplicate fold name: {name!r}")
        folds[name] = Path(raw_path)
    return folds


def _macro_task_metrics(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in TASK_METRIC_KEYS:
        values = [
            metrics[key]
            for summary in summaries.values()
            if isinstance((metrics := summary.get("metrics", {}).get("task_metrics")), dict)
            and isinstance(metrics.get(key), (int, float))
        ]
        result[key] = {
            "folds_scored": len(values),
            "mean": round(statistics.fmean(values), 6) if values else None,
            "pstdev": round(statistics.pstdev(values), 6) if values else None,
        }
    return result


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            records.append(value)
    return records


if __name__ == "__main__":
    main()
