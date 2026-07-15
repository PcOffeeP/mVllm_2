from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from .constants import CORE_FIELDS, GENERATION_CONFIG, SUPPORTED_DATASETS
from .datasets import EvalSample, load_dataset
from .model_runtime import load_model, run_model_on_video
from .prompts import (
    DEFAULT_PROMPT_LIBRARY_PATH,
    get_inference_target_schema,
    get_inference_user_prompt,
    get_prompt_library,
    get_prompt_version,
    get_system_prompt,
    get_user_prompt_template_count,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run direct 5-field model evaluation.")
    parser.add_argument("--dataset", required=True, choices=SUPPORTED_DATASETS)
    parser.add_argument("--model-dir", default=None, help="Finetuned/merged model directory. Required unless --predictions is used.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--video-root", default=None)
    parser.add_argument("--predictions", default=None, help="Existing JSONL with video_id and raw_output; skips model inference.")
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument(
        "--user-prompt-seed",
        type=int,
        default=42,
        help="Random seed for per-sample user prompt template selection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.predictions is None and args.model_dir is None:
        raise ValueError("--model-dir is required when --predictions is not provided")

    library = get_prompt_library()
    prompt_version = get_prompt_version(library)
    system_prompt = get_system_prompt(library)
    inference_target_schema = get_inference_target_schema(library)
    prompt_library_path = str(DEFAULT_PROMPT_LIBRARY_PATH)

    rng = random.Random(args.user_prompt_seed)
    template_count = get_user_prompt_template_count(library)

    video_root = Path(args.video_root) if args.video_root else None
    samples = load_dataset(args.dataset, video_root=video_root)
    if args.max_samples is not None:
        samples = samples[: args.max_samples]

    raw_outputs = _load_prediction_outputs(Path(args.predictions)) if args.predictions else None
    records: list[dict[str, Any]] = []

    processor = model = None
    if raw_outputs is None:
        processor, model = load_model(args.model_dir)

    summary_prompt_text = None
    for sample in samples:
        user_prompt_template_index = rng.randrange(template_count)
        prompt_text = get_inference_user_prompt(user_prompt_template_index, library)
        if summary_prompt_text is None:
            summary_prompt_text = prompt_text

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
                target_schema=inference_target_schema,
            )
        )

    summary_prompt_text = summary_prompt_text or get_inference_user_prompt(0, library)

    write_outputs(
        out_dir=Path(args.out_dir),
        records=records,
        dataset=args.dataset,
        model_dir=args.model_dir,
        prompt="training",
        prompt_text=summary_prompt_text,
        predictions=args.predictions,
        prompt_version=prompt_version,
        prompt_library_path=prompt_library_path,
        system_prompt=system_prompt,
        system_prompt_hash=hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        target_schema=inference_target_schema,
    )


def evaluate_sample(
    sample: EvalSample,
    raw_output: str,
    runtime_error: str | None = None,
    prompt_version: str | None = None,
    target_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned_output = str(raw_output or "").strip()
    return {
        "sample_id": sample.sample_id,
        "video_id": sample.video_id,
        "video_path": str(sample.video_path),
        "raw_output": raw_output,
        "runtime_error": runtime_error,
        "raw_output_non_empty": bool(cleaned_output),
        "has_result_section": "结果：" in cleaned_output,
        "prompt_version": prompt_version,
        "target_schema": target_schema,
        "metadata": sample.metadata,
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    runtime_error_count = sum(1 for record in records if record["runtime_error"])
    raw_output_count = sum(1 for record in records if record["raw_output_non_empty"])
    has_result_section_count = sum(1 for record in records if record.get("has_result_section"))
    return {
        "total_samples": total,
        "runtime_error_count": runtime_error_count,
        "raw_output_count": raw_output_count,
        "raw_output_rate": _rate(raw_output_count, total),
        "empty_output_count": total - raw_output_count,
        "has_result_section_count": has_result_section_count,
        "has_result_section_rate": _rate(has_result_section_count, total),
        "notes": [
            "No automatic JSON/schema extraction is performed. Judge prompt quality from raw_output in evaluation_records.jsonl.",
            "Ground-truth metadata is included only as reference context for manual inspection.",
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
