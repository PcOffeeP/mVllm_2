from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from .constants import CORE_FIELDS, GENERATION_CONFIG, SUPPORTED_DATASETS, VIDEO_MAX_FRAMES
from .datasets import EvalSample, load_dataset
from .model_runtime import load_model, run_model_on_video
from pipeline.output_normalizer import normalize_structured_output, validate_structured_output
from .prompts import (
    DEFAULT_PROMPT_LIBRARY_PATH,
    get_prompt_library,
    get_prompt_version,
    get_system_prompt,
    get_system_prompt_hash,
    get_target_schema,
    get_user_prompt,
)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run direct 4-field model evaluation.")
    parser.add_argument("--dataset", required=True, choices=SUPPORTED_DATASETS)
    parser.add_argument("--model-dir", default=None, help="Finetuned/merged model directory. Required unless --predictions is used.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--video-root", default=None)
    parser.add_argument("--predictions", default=None, help="Existing JSONL with video_id and raw_output; skips model inference.")
    parser.add_argument("--max-samples", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.predictions is None and args.model_dir is None:
        raise ValueError("--model-dir is required when --predictions is not provided")

    library = get_prompt_library()
    prompt_version = get_prompt_version(library)
    system_prompt = get_system_prompt(library)
    system_prompt_hash = get_system_prompt_hash(library)
    prompt_text = get_user_prompt(library)
    target_schema = get_target_schema(library)
    prompt_library_path = str(DEFAULT_PROMPT_LIBRARY_PATH)

    video_root = Path(args.video_root) if args.video_root else None
    samples = load_dataset(args.dataset, video_root=video_root)
    if args.max_samples is not None:
        samples = samples[: args.max_samples]

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
                    raw_output = run_model_on_video(model, processor, sample.video_path, prompt_text, system_prompt=system_prompt)
                    runtime_error = None
                except Exception as exc:
                    raw_output = ""
                    runtime_error = f"{type(exc).__name__}: {exc}"
        else:
            raw_output = raw_outputs.get(sample.video_id, "")
            runtime_error = None if sample.video_id in raw_outputs else "prediction missing"

        records.append(
            evaluate_sample(
                sample,
                raw_output,
                runtime_error,
                prompt_version=prompt_version,
                target_schema=target_schema,
            )
        )

    write_outputs(
        out_dir=Path(args.out_dir),
        records=records,
        dataset=args.dataset,
        model_dir=args.model_dir,
        prompt="training",
        prompt_text=prompt_text,
        predictions=args.predictions,
        prompt_version=prompt_version,
        prompt_library_path=prompt_library_path,
        system_prompt=system_prompt,
        system_prompt_hash=system_prompt_hash,
        target_schema=target_schema,
    )


def evaluate_sample(
    sample: EvalSample,
    raw_output: str,
    runtime_error: str | None = None,
    prompt_version: str | None = None,
    target_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned_output = str(raw_output or "").strip()
    parsed_output = None
    normalized_output = None
    repair_flags: list[str] = []
    parse_error = None
    if cleaned_output:
        try:
            candidate = json.loads(cleaned_output)
            if not isinstance(candidate, dict):
                parse_error = "JSON value is not an object"
            else:
                parsed_output = candidate
                normalized_output, repair_flags = normalize_structured_output(
                    candidate,
                    VIDEO_MAX_FRAMES,
                )
        except json.JSONDecodeError as exc:
            parse_error = f"JSONDecodeError: {exc.msg}"
    return {
        "sample_id": sample.sample_id,
        "video_id": sample.video_id,
        "video_path": str(sample.video_path),
        "raw_output": raw_output,
        "runtime_error": runtime_error,
        "raw_output_non_empty": bool(cleaned_output),
        "json_valid": parsed_output is not None,
        "parsed_output": parsed_output,
        "normalized_output": normalized_output,
        "normalization_repairs": repair_flags,
        "normalized_valid": (
            validate_structured_output(normalized_output, VIDEO_MAX_FRAMES)
            if normalized_output is not None
            else False
        ),
        "parse_error": parse_error,
        "prompt_version": prompt_version,
        "target_schema": target_schema,
        "metadata": sample.metadata,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    runtime_error_count = sum(1 for record in records if record["runtime_error"])
    raw_output_count = sum(1 for record in records if record["raw_output_non_empty"])
    json_valid_count = sum(1 for record in records if record.get("json_valid"))
    normalized_valid_count = sum(1 for record in records if record.get("normalized_valid"))
    repaired_count = sum(1 for record in records if record.get("normalization_repairs"))
    return {
        "total_samples": total,
        "runtime_error_count": runtime_error_count,
        "raw_output_count": raw_output_count,
        "raw_output_rate": _rate(raw_output_count, total),
        "empty_output_count": total - raw_output_count,
        "json_valid_count": json_valid_count,
        "json_valid_rate": _rate(json_valid_count, total),
        "normalized_valid_count": normalized_valid_count,
        "normalized_valid_rate": _rate(normalized_valid_count, total),
        "repaired_count": repaired_count,
        "repair_rate": _rate(repaired_count, total),
        "notes": [
            "Raw protocol compliance and normalized output are recorded separately.",
            "Ground-truth metadata is included as reference context for task-metric analysis.",
        ],
    }


def write_outputs(
    out_dir: Path,
    records: list[dict[str, Any]],
    dataset: str,
    model_dir: str | None,
    prompt: str,
    prompt_text: str,
    predictions: str | None = None,
    prompt_version: str | None = None,
    prompt_library_path: str | None = None,
    system_prompt: str | None = None,
    system_prompt_hash: str | None = None,
    target_schema: dict[str, Any] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "dataset": dataset,
        "model_dir": model_dir,
        "prompt": prompt,
        "prompt_text": prompt_text,
        "prompt_version": prompt_version,
        "prompt_library_path": prompt_library_path,
        "system_prompt": system_prompt,
        "system_prompt_hash": system_prompt_hash,
        "target_schema": target_schema,
        "predictions": predictions,
        "generation_config": GENERATION_CONFIG,
        "metrics": summarize(records),
    }
    (out_dir / "evaluation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "evaluation_records.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    _write_runtime_failures_csv(out_dir / "runtime_failures.csv", records)
    print(f"Wrote evaluation to {out_dir}")
    print(f"  raw_output_rate={summary['metrics']['raw_output_rate']}")
    print(f"  runtime_error_count={summary['metrics']['runtime_error_count']}")


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


def _write_runtime_failures_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "video_id",
        "runtime_error",
        "video_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            if not record["runtime_error"]:
                continue
            writer.writerow(
                {
                    "video_id": record["video_id"],
                    "runtime_error": record["runtime_error"],
                    "video_path": record["video_path"],
                }
            )


def _rate(count: int, total: int) -> float | None:
    return round(count / total, 6) if total else None


if __name__ == "__main__":
    main()
