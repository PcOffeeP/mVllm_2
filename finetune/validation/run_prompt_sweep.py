"""Run a paired prompt sweep for a single MiniCPM-V model.

The sweep deliberately reuses the six training user prompts from
``pipeline/prompt_library.yaml``.  It does *not* use the inference prompt in
``prompts.get_inference_user_prompt`` because that prompt adds a fifth
``confidence`` field and two demonstrations, neither of which is part of the
training output contract.

Every selected video is evaluated with every selected prompt condition.  This
is a paired comparison: prompt quality is therefore not confounded with video
difficulty or label prevalence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.scripts.quality_check import TARGET_SCHEMA_KEYS, _matches_legal_combination

from .constants import GENERATION_CONFIG, SUPPORTED_DATASETS, VIDEO_MAX_FRAMES
from .datasets import EvalSample, load_dataset
from .model_runtime import load_model, run_model_on_video
from .prompts import (
    DEFAULT_PROMPT_LIBRARY_PATH,
    get_prompt_library,
    get_prompt_version,
    get_system_prompt,
    get_system_prompt_hash,
    get_user_prompt,
    get_user_prompt_template_id,
)


VARIANT_TRAINING_QUESTION = "training_question"
VARIANT_FOUR_FIELD = "four_field"
SUPPORTED_VARIANTS = (VARIANT_TRAINING_QUESTION, VARIANT_FOUR_FIELD)

# This is intentionally a constraint only, not a few-shot example.  The
# four-field order matches build_assistant_content() in training_sample_builder.
FOUR_FIELD_CONSTRAINT = """只输出一个 JSON 对象，且只能包含以下四个字段：
{"has_fracture":...,"fracture_between":...,"type":...,"location":...}
不要输出解释、示例、Markdown 或其他字段。"""

# Kept solely as a diagnostic for the previously observed inference collapse.
KNOWN_NEGATIVE_DEMONSTRATION = (
    '{"has_fracture":false,"fracture_between":null,"type":"未断裂",'
    '"location":null,"confidence":0.9}'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run every selected training prompt against every selected video (paired prompt sweep)."
    )
    parser.add_argument("--dataset", required=True, choices=SUPPORTED_DATASETS)
    parser.add_argument("--model-dir", required=True, help="Base-model directory to load directly.")
    parser.add_argument("--out-dir", required=True, help="New directory for prompt-sweep outputs.")
    parser.add_argument("--video-root", default=None)
    parser.add_argument(
        "--template-indices",
        default="all",
        help="Comma-separated indices from the existing training prompt library, or 'all' (default).",
    )
    parser.add_argument(
        "--variants",
        default=f"{VARIANT_TRAINING_QUESTION},{VARIANT_FOUR_FIELD}",
        help="Comma-separated variants: training_question, four_field.",
    )
    parser.add_argument("--max-samples", type=int, default=None, help="Optional smoke-test cap applied before the sweep.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Append only missing (sample_id, prompt_id) pairs to an existing evaluation_records.jsonl.",
    )
    return parser.parse_args()


def parse_template_indices(value: str, template_count: int) -> list[int]:
    if value.strip().lower() == "all":
        return list(range(template_count))
    try:
        indices = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError("--template-indices must be 'all' or comma-separated integers") from exc
    if not indices:
        raise ValueError("--template-indices selected no templates")
    invalid = [index for index in indices if index < 0 or index >= template_count]
    if invalid:
        raise ValueError(f"--template-indices out of range 0..{template_count - 1}: {invalid}")
    return list(dict.fromkeys(indices))


def parse_variants(value: str) -> list[str]:
    variants = [item.strip() for item in value.split(",") if item.strip()]
    if not variants:
        raise ValueError("--variants selected no variants")
    invalid = [variant for variant in variants if variant not in SUPPORTED_VARIANTS]
    if invalid:
        raise ValueError(f"Unsupported variants {invalid}; expected one of {SUPPORTED_VARIANTS}")
    return list(dict.fromkeys(variants))


def build_prompt_conditions(
    library: dict[str, Any], template_indices: list[int], variants: list[str]
) -> list[dict[str, str | int]]:
    """Build conditions from the training prompt library without its examples."""
    conditions: list[dict[str, str | int]] = []
    for template_index in template_indices:
        template_id = get_user_prompt_template_id(template_index, library)
        training_question = get_user_prompt(template_index, library)
        for variant in variants:
            prompt_text = training_question
            if variant == VARIANT_FOUR_FIELD:
                prompt_text = f"{training_question}\n\n{FOUR_FIELD_CONSTRAINT}"
            prompt_id = f"{template_id}__{variant}"
            conditions.append(
                {
                    "prompt_id": prompt_id,
                    "template_index": template_index,
                    "template_id": template_id,
                    "variant": variant,
                    "prompt_text": prompt_text,
                    "prompt_hash": _sha256(prompt_text),
                }
            )
    return conditions


def inspect_four_field_output(raw_output: str) -> dict[str, Any]:
    """Strictly inspect the four-field output contract used for SFT targets."""
    cleaned = str(raw_output or "").strip()
    result: dict[str, Any] = {
        "json_valid": False,
        "schema_valid": False,
        "legal_combination_valid": False,
        "parsed_output": None,
        "parse_error": None,
    }
    if not cleaned:
        result["parse_error"] = "empty_output"
        return result
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        result["parse_error"] = f"JSONDecodeError: {exc.msg}"
        return result
    result["json_valid"] = True
    if not isinstance(parsed, dict):
        result["parse_error"] = "JSON value is not an object"
        return result
    result["parsed_output"] = parsed
    if set(parsed) != TARGET_SCHEMA_KEYS:
        result["parse_error"] = f"schema keys must be {sorted(TARGET_SCHEMA_KEYS)}"
        return result
    result["schema_valid"] = True
    result["legal_combination_valid"] = bool(_matches_legal_combination(parsed))
    if not result["legal_combination_valid"]:
        result["parse_error"] = "illegal four-field value combination"
    return result


def evaluate_record(sample: EvalSample, condition: dict[str, str | int], raw_output: str, runtime_error: str | None) -> dict[str, Any]:
    inspection = inspect_four_field_output(raw_output)
    return {
        "sample_id": sample.sample_id,
        "video_id": sample.video_id,
        "video_path": str(sample.video_path),
        "source_video_id": sample.metadata.get("source_video_id"),
        "subvideo_id": sample.metadata.get("subvideo_id"),
        "ground_truth": sample.metadata.get("ground_truth"),
        "prompt_id": condition["prompt_id"],
        "template_index": condition["template_index"],
        "template_id": condition["template_id"],
        "variant": condition["variant"],
        "prompt_text": condition["prompt_text"],
        "prompt_hash": condition["prompt_hash"],
        "raw_output": raw_output,
        "runtime_error": runtime_error,
        "raw_output_non_empty": bool(str(raw_output or "").strip()),
        "copied_known_negative_demonstration": str(raw_output or "").strip() == KNOWN_NEGATIVE_DEMONSTRATION,
        **inspection,
    }


def summarize_condition(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    outputs = [str(record["raw_output"] or "").strip() for record in records]
    non_empty_outputs = [output for output in outputs if output]
    frequencies = Counter(non_empty_outputs)
    most_common_output, most_common_count = frequencies.most_common(1)[0] if frequencies else (None, 0)
    class_metrics = _classification_metrics(records)
    return {
        "total_samples": total,
        "runtime_error_count": sum(bool(record["runtime_error"]) for record in records),
        "non_empty_output_rate": _rate(len(non_empty_outputs), total),
        "json_valid_rate": _rate(sum(bool(record["json_valid"]) for record in records), total),
        "schema_valid_rate": _rate(sum(bool(record["schema_valid"]) for record in records), total),
        "legal_combination_valid_rate": _rate(sum(bool(record["legal_combination_valid"]) for record in records), total),
        "copied_known_negative_demonstration_rate": _rate(
            sum(bool(record["copied_known_negative_demonstration"]) for record in records), total
        ),
        "unique_non_empty_output_count": len(frequencies),
        "most_common_output": most_common_output,
        "most_common_output_rate": _rate(most_common_count, total),
        **class_metrics,
    }


def _classification_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return has_fracture metrics, treating malformed output as an incorrect prediction."""
    evaluable = [
        record
        for record in records
        if isinstance(record.get("ground_truth"), dict)
        and isinstance(record["ground_truth"].get("has_fracture"), bool)
    ]
    common_metrics = _field_metrics(records)
    if not evaluable:
        return {
            "has_fracture_evaluable_count": 0,
            "has_fracture_accuracy": None,
            "has_fracture_precision": None,
            "has_fracture_recall": None,
            "has_fracture_f1": None,
            "predicted_positive_rate": None,
            **common_metrics,
        }

    true_positive = false_positive = false_negative = correct = predicted_positive = 0
    for record in evaluable:
        gt_positive = record["ground_truth"]["has_fracture"] is True
        parsed = record.get("parsed_output")
        pred_positive = isinstance(parsed, dict) and parsed.get("has_fracture") is True
        pred_matches = isinstance(parsed, dict) and parsed.get("has_fracture") == gt_positive
        predicted_positive += int(pred_positive)
        correct += int(pred_matches)
        true_positive += int(gt_positive and pred_positive)
        false_positive += int(not gt_positive and pred_positive)
        false_negative += int(gt_positive and not pred_positive)

    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = _ratio(2 * true_positive, 2 * true_positive + false_positive + false_negative)
    return {
        "has_fracture_evaluable_count": len(evaluable),
        "has_fracture_accuracy": _rate(correct, len(evaluable)),
        "has_fracture_precision": precision,
        "has_fracture_recall": recall,
        "has_fracture_f1": f1,
        "predicted_positive_rate": _rate(predicted_positive, len(evaluable)),
        **common_metrics,
    }


def _field_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score the remaining target fields only where ground truth is meaningful.

    A missing prediction is deliberately counted as incorrect.  A positive
    original video with no recorded interval is not an interval/joint target,
    because its absent interval means unavailable evidence rather than a null
    answer requirement.
    """

    type_records = [
        record
        for record in records
        if isinstance(record.get("ground_truth"), dict)
        and isinstance(record["ground_truth"].get("type"), str)
        and record["ground_truth"]["type"] != "视频异常"
    ]
    location_records = [
        record
        for record in records
        if isinstance(record.get("ground_truth"), dict)
        and record["ground_truth"].get("location") in {"inside_gauge", "outside_gauge"}
    ]
    interval_records = [
        record
        for record in records
        if isinstance(record.get("ground_truth"), dict)
        and isinstance(record["ground_truth"].get("fracture_between"), list)
    ]
    joint_records = [
        record
        for record in records
        if _joint_target_is_evaluable(record.get("ground_truth"))
    ]
    return {
        "type_evaluable_count": len(type_records),
        "type_accuracy": _field_accuracy(type_records, "type"),
        "location_evaluable_count": len(location_records),
        "location_accuracy": _field_accuracy(location_records, "location"),
        "fracture_between_evaluable_count": len(interval_records),
        "fracture_between_exact_match_rate": _field_accuracy(interval_records, "fracture_between"),
        "joint_evaluable_count": len(joint_records),
        "joint_success_rate": _joint_accuracy(joint_records),
    }


def _field_accuracy(records: list[dict[str, Any]], field: str) -> float | None:
    correct = sum(
        isinstance(record.get("parsed_output"), dict)
        and record["parsed_output"].get(field) == record["ground_truth"].get(field)
        for record in records
    )
    return _rate(correct, len(records))


def _joint_target_is_evaluable(ground_truth: Any) -> bool:
    if not isinstance(ground_truth, dict) or not isinstance(ground_truth.get("has_fracture"), bool):
        return False
    if not isinstance(ground_truth.get("type"), str):
        return False
    if ground_truth["has_fracture"] is True and not isinstance(ground_truth.get("fracture_between"), list):
        return False
    return True


def _joint_accuracy(records: list[dict[str, Any]]) -> float | None:
    correct = 0
    for record in records:
        parsed = record.get("parsed_output")
        ground_truth = record["ground_truth"]
        if not isinstance(parsed, dict):
            continue
        fields = ("has_fracture", "fracture_between", "type", "location")
        correct += int(all(parsed.get(field) == ground_truth.get(field) for field in fields))
    return _rate(correct, len(records))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_existing_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not valid JSONL: {exc}") from exc
    return records


def _validate_resumable_records(
    records: list[dict[str, Any]], conditions: list[dict[str, str | int]], model_dir: str
) -> None:
    """Prevent a resume from silently combining different prompt or model runs."""
    expected_hashes = {str(condition["prompt_id"]): str(condition["prompt_hash"]) for condition in conditions}
    for index, record in enumerate(records, start=1):
        prompt_id = str(record.get("prompt_id"))
        if prompt_id not in expected_hashes:
            raise ValueError(f"Cannot resume: record {index} has prompt_id outside this sweep: {prompt_id}")
        if record.get("prompt_hash") != expected_hashes[prompt_id]:
            raise ValueError(f"Cannot resume: record {index} has a different prompt hash for {prompt_id}")
        if record.get("model_dir") not in {None, model_dir}:
            raise ValueError(f"Cannot resume: record {index} was created for another model_dir")


def _write_summary(
    path: Path,
    records: list[dict[str, Any]],
    conditions: list[dict[str, str | int]],
    args: argparse.Namespace,
    library: dict[str, Any],
    system_prompt: str,
) -> None:
    by_prompt: dict[str, list[dict[str, Any]]] = {str(condition["prompt_id"]): [] for condition in conditions}
    for record in records:
        prompt_id = str(record.get("prompt_id", ""))
        if prompt_id in by_prompt:
            by_prompt[prompt_id].append(record)
    condition_summaries = []
    for condition in conditions:
        prompt_id = str(condition["prompt_id"])
        condition_summaries.append({**condition, "metrics": summarize_condition(by_prompt[prompt_id])})
    summary = {
        "dataset": args.dataset,
        "model_dir": args.model_dir,
        "prompt_library_path": str(DEFAULT_PROMPT_LIBRARY_PATH),
        "prompt_version": get_prompt_version(library),
        "system_prompt": system_prompt,
        "system_prompt_hash": get_system_prompt_hash(library),
        "generation_config": GENERATION_CONFIG,
        "video_max_frames": VIDEO_MAX_FRAMES,
        "paired_design": True,
        "sample_count": len({str(record["sample_id"]) for record in records}),
        "record_count": len(records),
        "conditions": condition_summaries,
        "notes": [
            "Every selected video is evaluated once per condition; do not compare prompt conditions using disjoint video groups.",
            "training_question is diagnostic only. four_field is the candidate protocol for later model comparisons.",
            "Video-abnormal ground truth (has_fracture=null) is excluded from has_fracture classification metrics.",
            "For test_subvideos, aggregate or bootstrap by source_video_id before treating differences as independent evidence.",
        ],
    }
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    records_path = out_dir / "evaluation_records.jsonl"
    summary_path = out_dir / "prompt_sweep_summary.json"
    if records_path.exists() and not args.resume:
        raise FileExistsError(f"{records_path} already exists; use a new --out-dir or pass --resume")

    library = get_prompt_library()
    template_indices = parse_template_indices(args.template_indices, len(library["user_prompt_templates"]))
    variants = parse_variants(args.variants)
    conditions = build_prompt_conditions(library, template_indices, variants)
    system_prompt = get_system_prompt(library)
    samples = load_dataset(args.dataset, video_root=Path(args.video_root) if args.video_root else None)
    if args.max_samples is not None:
        samples = samples[: args.max_samples]

    existing_records = _load_existing_records(records_path) if args.resume else []
    _validate_resumable_records(existing_records, conditions, args.model_dir)
    completed_pairs = {
        (str(record.get("sample_id")), str(record.get("prompt_id"))) for record in existing_records
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    processor, model = load_model(args.model_dir)

    records = list(existing_records)
    with records_path.open("a" if args.resume else "w", encoding="utf-8") as handle:
        for condition in conditions:
            for sample in samples:
                pair = (sample.sample_id, str(condition["prompt_id"]))
                if pair in completed_pairs:
                    continue
                if not sample.video_path.exists():
                    raw_output = ""
                    runtime_error = f"video not found: {sample.video_path}"
                else:
                    try:
                        raw_output = run_model_on_video(
                            model, processor, sample.video_path, str(condition["prompt_text"]), system_prompt=system_prompt
                        )
                        runtime_error = None
                    except Exception as exc:
                        raw_output = ""
                        runtime_error = f"{type(exc).__name__}: {exc}"
                record = evaluate_record(sample, condition, raw_output, runtime_error)
                record["model_dir"] = args.model_dir
                record["system_prompt_hash"] = get_system_prompt_hash(library)
                records.append(record)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()

    _write_summary(summary_path, records, conditions, args, library, system_prompt)
    print(f"Wrote paired prompt sweep to {out_dir}")
    print(f"  samples={len(samples)} conditions={len(conditions)} records={len(records)}")


if __name__ == "__main__":
    main()
