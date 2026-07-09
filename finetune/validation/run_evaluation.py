from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .constants import CORE_FIELDS, GENERATION_CONFIG, PROMPT_NAMES, SUPPORTED_DATASETS
from .datasets import EvalSample, load_dataset
from .model_runtime import load_model, run_model_on_video
from .prompts import get_prompt
from .schema import compare_prediction, parse_model_output, prediction_correct


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run direct 5-field model evaluation.")
    parser.add_argument("--dataset", required=True, choices=SUPPORTED_DATASETS)
    parser.add_argument("--model-dir", default=None, help="Finetuned/merged model directory. Required unless --predictions is used.")
    parser.add_argument("--prompt", required=True, choices=PROMPT_NAMES)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--video-root", default=None)
    parser.add_argument("--predictions", default=None, help="Existing JSONL with video_id and raw_output; skips model inference.")
    parser.add_argument("--max-samples", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.predictions is None and args.model_dir is None:
        raise ValueError("--model-dir is required when --predictions is not provided")

    video_root = Path(args.video_root) if args.video_root else None
    samples = load_dataset(args.dataset, video_root=video_root)
    if args.max_samples is not None:
        samples = samples[: args.max_samples]

    prompt_text = get_prompt(args.prompt)
    raw_outputs = _load_prediction_outputs(Path(args.predictions)) if args.predictions else None
    records: list[dict[str, Any]] = []

    processor = model = None
    if raw_outputs is None:
        processor, model = load_model(args.model_dir)

    for sample in samples:
        if raw_outputs is None:
            if not sample.video_path.exists():
                raw_output = ""
                runtime_error = f"video not found: {sample.video_path}"
            else:
                try:
                    raw_output = run_model_on_video(model, processor, sample.video_path, prompt_text)
                    runtime_error = None
                except Exception as exc:
                    raw_output = ""
                    runtime_error = f"{type(exc).__name__}: {exc}"
        else:
            raw_output = raw_outputs.get(sample.video_id, "")
            runtime_error = None if sample.video_id in raw_outputs else "prediction missing"

        records.append(evaluate_sample(sample, raw_output, runtime_error))

    write_outputs(
        out_dir=Path(args.out_dir),
        records=records,
        dataset=args.dataset,
        model_dir=args.model_dir,
        prompt=args.prompt,
        prompt_text=prompt_text,
        predictions=args.predictions,
    )


def evaluate_sample(sample: EvalSample, raw_output: str, runtime_error: str | None = None) -> dict[str, Any]:
    format_result = parse_model_output(raw_output)
    field_results = compare_prediction(format_result.payload, sample.target)
    field_correct = prediction_correct(field_results)
    return {
        "sample_id": sample.sample_id,
        "video_id": sample.video_id,
        "video_path": str(sample.video_path),
        "raw_output": raw_output,
        "runtime_error": runtime_error,
        "json_valid": format_result.json_valid,
        "schema_valid": format_result.schema_valid,
        "format_valid": format_result.format_valid,
        "schema_errors": format_result.errors,
        "payload": format_result.payload,
        "target": _jsonable_target(sample.target),
        "field_results": field_results,
        "prediction_correct": field_correct if format_result.format_valid and runtime_error is None else False,
        "metadata": sample.metadata,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    format_valid_count = sum(1 for record in records if record["format_valid"])
    runtime_error_count = sum(1 for record in records if record["runtime_error"])
    comparable_records = [record for record in records if record["format_valid"] and not record["runtime_error"]]
    prediction_correct_count = sum(1 for record in comparable_records if record["prediction_correct"] is True)
    field_summary = {}
    for field in CORE_FIELDS:
        checked = [
            record["field_results"][field]
            for record in comparable_records
            if record["field_results"][field]["status"] == "checked"
        ]
        correct = sum(1 for result in checked if result["correct"] is True)
        field_summary[field] = {
            "checked_count": len(checked),
            "correct_count": correct,
            "accuracy": _rate(correct, len(checked)),
        }
    return {
        "total_samples": total,
        "runtime_error_count": runtime_error_count,
        "format_valid_count": format_valid_count,
        "format_valid_rate": _rate(format_valid_count, total),
        "comparable_samples": len(comparable_records),
        "prediction_correct_count": prediction_correct_count,
        "prediction_correct_rate": _rate(prediction_correct_count, len(comparable_records)),
        "field_metrics": field_summary,
        "schema_error_counts": dict(_schema_error_counts(records)),
        "notes": [
            "confidence has no ground-truth label; it is counted correct when it is a numeric value in [0, 1].",
            "fields without ground truth are marked unavailable and excluded from that field accuracy.",
        ],
    }


def write_outputs(
    out_dir: Path,
    records: list[dict[str, Any]],
    dataset: str,
    model_dir: str | None,
    prompt: str,
    prompt_text: str,
    predictions: str | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "dataset": dataset,
        "model_dir": model_dir,
        "prompt": prompt,
        "prompt_text": prompt_text,
        "predictions": predictions,
        "generation_config": GENERATION_CONFIG,
        "metrics": summarize(records),
    }
    (out_dir / "evaluation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "evaluation_records.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    _write_failures_csv(out_dir / "failures.csv", records)
    print(f"Wrote evaluation to {out_dir}")
    print(f"  format_valid_rate={summary['metrics']['format_valid_rate']}")
    print(f"  prediction_correct_rate={summary['metrics']['prediction_correct_rate']}")


def _load_prediction_outputs(path: Path) -> dict[str, str]:
    outputs: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            video_id = record.get("video_id")
            if not video_id:
                raise ValueError(f"{path}:{line_no} has no video_id")
            if "raw_output" in record:
                outputs[video_id] = str(record["raw_output"])
            elif all(field in record for field in CORE_FIELDS):
                outputs[video_id] = json.dumps({field: record[field] for field in CORE_FIELDS}, ensure_ascii=False)
            else:
                raise ValueError(f"{path}:{line_no} has neither raw_output nor direct fields")
    return outputs


def _write_failures_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "video_id",
        "reason",
        "runtime_error",
        "format_valid",
        "prediction_correct",
        "schema_errors",
        "has_fracture_correct",
        "fracture_between_correct",
        "type_correct",
        "location_correct",
        "confidence_correct",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            if record["runtime_error"]:
                reason = "runtime_error"
            elif not record["format_valid"]:
                reason = "format_invalid"
            elif record["prediction_correct"] is not True:
                reason = "prediction_incorrect"
            else:
                continue
            row = {
                "video_id": record["video_id"],
                "reason": reason,
                "runtime_error": record["runtime_error"],
                "format_valid": record["format_valid"],
                "prediction_correct": record["prediction_correct"],
                "schema_errors": "; ".join(record["schema_errors"]),
            }
            for field in CORE_FIELDS:
                row[f"{field}_correct"] = record["field_results"][field]["correct"]
            writer.writerow(row)


def _schema_error_counts(records: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        for error in record["schema_errors"]:
            counts[error] += 1
    return counts


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 6) if total else None


def _jsonable_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (None if value.__class__.__name__ == "_Unavailable" else value)
        for key, value in target.items()
    }


if __name__ == "__main__":
    main()
