from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from config import (
    ALLOWED_TYPE_LABELS,
    BASELINE_PROMPTS,
    DEFAULT_MODEL_DIRS,
    FEWSHOT_EXAMPLES,
    GROUND_TRUTH_JSON,
    LABEL_ALIASES,
    PROMPT_INSTRUCTION,
    PROMPT_PRESETS,
    SPLIT_DIR,
    STRICT_PROMPTS,
    SUPPORTED_FOLDS,
    TIME_THRESHOLD_SEC,
)


STRICT_SECONDS_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s\s*$", re.IGNORECASE)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_seconds(value: Any) -> float | None:
    if value is None:
        return None
    match = STRICT_SECONDS_PATTERN.match(str(value))
    if match is None:
        return None
    return float(match.group(1))


def normalize_ground_truth_label(value: Any) -> str | None:
    if value is None:
        return None
    label = str(value).strip()
    if not label:
        return None
    return LABEL_ALIASES.get(label, label)


def normalize_prediction_label(value: Any) -> str | None:
    if value is None:
        return None
    label = str(value).strip()
    if not label:
        return None
    return label if label in ALLOWED_TYPE_LABELS else None


# Backward-compatible alias for GT normalization.
normalize_label = normalize_ground_truth_label


def sanitize_response_text(text: Any) -> str:
    content = str(text or "").strip()
    content = content.replace("```json", "").replace("```JSON", "").replace("```", "").strip()
    return content


def parse_response_payload(text: Any) -> tuple[bool, dict[str, Any] | None]:
    content = sanitize_response_text(text)
    if not content:
        return False, None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False, None
    if not isinstance(payload, dict):
        return False, None
    return True, payload


def resolve_prompt_preset(task: str, prompt_preset: str) -> str:
    validate_task(task)
    validate_prompt_preset(prompt_preset)
    if prompt_preset == "fewshot" and task == "time":
        return "strict"
    return prompt_preset


def build_prompt(task: str, prompt_preset: str = "strict") -> tuple[str, str]:
    resolved_prompt_preset = resolve_prompt_preset(task, prompt_preset)
    if resolved_prompt_preset == "baseline":
        task_prompt = BASELINE_PROMPTS[task]
    else:
        task_prompt = STRICT_PROMPTS[task]
        if resolved_prompt_preset == "fewshot":
            task_prompt = f"{task_prompt}\n{FEWSHOT_EXAMPLES[task]}"
    return resolved_prompt_preset, f"{PROMPT_INSTRUCTION}\n{task_prompt}"


def get_default_model_dir(fold: int) -> str:
    return DEFAULT_MODEL_DIRS[fold]


def load_ground_truth(path: Path = GROUND_TRUTH_JSON) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["video_name"]: item for item in data}


def load_split_video_names(fold: int) -> list[str]:
    split_path = SPLIT_DIR / f"stratified_3_fold_{fold}.json"
    split = json.loads(split_path.read_text(encoding="utf-8"))
    names = [Path(item).name for item in split["val"]]
    # Normalize: strip legacy prefixes so config.py can prepend VIDEO_DIR uniformly
    names = [n.replace("Video\\all_videos\\", "").replace("Video/all_videos/", "").replace("videos/", "") for n in names]
    return names


def load_fold_samples(fold: int, gt_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    videos = load_split_video_names(fold)
    missing = [name for name in videos if name not in gt_map]
    if missing:
        raise ValueError(f"Fold {fold} videos missing from GT: {missing}")
    return [gt_map[name] for name in videos]


def read_jsonl(paths: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path_str in paths:
        path = Path(path_str)
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def write_json(path: Path, payload: Any) -> None:
    ensure_parent_dir(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def compute_type_metrics(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    labels = sorted({record["gt_type"] for record in records})
    pred_labels = sorted({record.get("pred_type_norm") for record in records if record.get("pred_type_norm")})
    confusion_cols = labels + [label for label in pred_labels if label not in labels]
    if "__INVALID__" not in confusion_cols:
        confusion_cols.append("__INVALID__")

    total = len(records)
    correct = 0
    per_class_rows: list[dict[str, Any]] = []
    confusion_rows: list[dict[str, Any]] = []

    confusion = {(gt_label, pred_label): 0 for gt_label in labels for pred_label in confusion_cols}
    for record in records:
        gt_label = record["gt_type"]
        pred_label = record.get("pred_type_norm") or "__INVALID__"
        if pred_label not in confusion_cols:
            pred_label = "__INVALID__"
        confusion[(gt_label, pred_label)] += 1
        if gt_label == pred_label:
            correct += 1

    macro_precision = 0.0
    macro_recall = 0.0
    macro_f1 = 0.0
    for label in labels:
        tp = sum(1 for record in records if record["gt_type"] == label and record.get("pred_type_norm") == label)
        fp = sum(1 for record in records if record["gt_type"] != label and record.get("pred_type_norm") == label)
        fn = sum(1 for record in records if record["gt_type"] == label and record.get("pred_type_norm") != label)
        support = sum(1 for record in records if record["gt_type"] == label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        macro_precision += precision
        macro_recall += recall
        macro_f1 += f1
        per_class_rows.append(
            {
                "label": label,
                "support": support,
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "f1": round(f1, 6),
            }
        )

    class_count = len(labels) or 1
    summary = {
        "count": total,
        "accuracy": round(correct / total, 6) if total else 0.0,
        "macro_precision": round(macro_precision / class_count, 6),
        "macro_recall": round(macro_recall / class_count, 6),
        "macro_f1": round(macro_f1 / class_count, 6),
    }

    for label in labels:
        row = {"gt_type": label}
        for pred_label in confusion_cols:
            row[pred_label] = confusion[(label, pred_label)]
        confusion_rows.append(row)

    return summary, per_class_rows, confusion_rows


def init_time_aggregator() -> dict[str, Any]:
    return {
        "count": 0,
        "applicable_count": 0,
        "excluded_no_gt_time": 0,
        "parseable_prediction_count": 0,
        "time_unparseable_count": 0,
        "sum_abs_error": 0.0,
        "sum_squared_error": 0.0,
        "hit_at_2s_count": 0,
        "excluded_labels": Counter(),
    }


def update_time_aggregator(agg: dict[str, Any], record: dict[str, Any], threshold: float = TIME_THRESHOLD_SEC) -> None:
    agg["count"] += 1
    if not record["time_available"]:
        agg["excluded_no_gt_time"] += 1
        agg["excluded_labels"][record["gt_type"]] += 1
        return

    agg["applicable_count"] += 1
    pred_time = record.get("pred_time_sec")
    if pred_time is None:
        agg["time_unparseable_count"] += 1
        return

    agg["parseable_prediction_count"] += 1
    error = abs(pred_time - record["gt_time_sec"])
    agg["sum_abs_error"] += error
    agg["sum_squared_error"] += error * error
    if error < threshold:
        agg["hit_at_2s_count"] += 1


def finalize_time_aggregator(agg: dict[str, Any]) -> dict[str, Any]:
    applicable = agg["applicable_count"] or 1
    parseable = agg["parseable_prediction_count"] or 1
    return {
        "count": agg["count"],
        "applicable_count": agg["applicable_count"],
        "excluded_no_gt_time": agg["excluded_no_gt_time"],
        "excluded_labels": dict(agg["excluded_labels"]),
        "parseable_prediction_count": agg["parseable_prediction_count"],
        "time_unparseable_count": agg["time_unparseable_count"],
        "mae": round(agg["sum_abs_error"] / parseable, 6) if agg["parseable_prediction_count"] else None,
        "mse": round(agg["sum_squared_error"] / parseable, 6) if agg["parseable_prediction_count"] else None,
        "hit_at_2s": round(agg["hit_at_2s_count"] / applicable, 6) if agg["applicable_count"] else None,
        "time_unparseable_ratio": round(agg["time_unparseable_count"] / applicable, 6) if agg["applicable_count"] else None,
    }


def init_joint_aggregator() -> dict[str, Any]:
    return {
        "count": 0,
        "applicable_count": 0,
        "excluded_no_gt_time": 0,
        "json_valid_count": 0,
        "time_within_threshold_count": 0,
        "type_correct_count": 0,
        "joint_success_count": 0,
        "failure_reasons": Counter(),
    }


def update_joint_aggregator(agg: dict[str, Any], record: dict[str, Any], threshold: float = TIME_THRESHOLD_SEC) -> None:
    agg["count"] += 1
    if not record["time_available"]:
        agg["excluded_no_gt_time"] += 1
        return

    agg["applicable_count"] += 1
    if record["json_valid"]:
        agg["json_valid_count"] += 1

    pred_time = record.get("pred_time_sec")
    time_ok = pred_time is not None and abs(pred_time - record["gt_time_sec"]) < threshold
    type_ok = record.get("pred_type_norm") == record["gt_type"]
    if time_ok:
        agg["time_within_threshold_count"] += 1
    if type_ok:
        agg["type_correct_count"] += 1
    if record["json_valid"] and time_ok and type_ok:
        agg["joint_success_count"] += 1
    elif record.get("failure_reason"):
        agg["failure_reasons"][record["failure_reason"]] += 1


def finalize_joint_aggregator(agg: dict[str, Any]) -> dict[str, Any]:
    applicable = agg["applicable_count"] or 1
    return {
        "count": agg["count"],
        "applicable_count": agg["applicable_count"],
        "excluded_no_gt_time": agg["excluded_no_gt_time"],
        "json_valid_count": agg["json_valid_count"],
        "time_within_threshold_count": agg["time_within_threshold_count"],
        "type_correct_count": agg["type_correct_count"],
        "joint_success_count": agg["joint_success_count"],
        "joint_success_rate": round(agg["joint_success_count"] / applicable, 6) if agg["applicable_count"] else None,
        "failure_reasons": dict(agg["failure_reasons"]),
    }


def infer_failure_reason(record: dict[str, Any], task: str, threshold: float = TIME_THRESHOLD_SEC) -> str | None:
    if record.get("failure_reason") == "video_load_failed":
        return "video_load_failed"
    if not record["json_valid"]:
        return "json_invalid"

    if task == "time":
        if record["time_available"] and record.get("pred_time_sec") is None:
            return "time_unparseable"
        if record["time_available"] and record.get("pred_time_sec") is not None:
            if abs(record["pred_time_sec"] - record["gt_time_sec"]) >= threshold:
                return "time_threshold_exceeded"
        return None

    if task == "type":
        if record.get("pred_type_raw") and record.get("pred_type_norm") is None:
            return "type_unmapped"
        if record.get("pred_type_norm") != record["gt_type"]:
            return "type_mismatch"
        return None

    if record["time_available"] and record.get("pred_time_sec") is None:
        return "time_unparseable"
    if record.get("pred_type_raw") and record.get("pred_type_norm") is None:
        return "type_unmapped"
    if record["time_available"] and record.get("pred_time_sec") is not None:
        if abs(record["pred_time_sec"] - record["gt_time_sec"]) >= threshold:
            return "time_threshold_exceeded"
    if record.get("pred_type_norm") != record["gt_type"]:
        return "type_mismatch"
    return None


def validate_fold(fold: int) -> None:
    if fold not in SUPPORTED_FOLDS:
        raise ValueError(f"Unsupported fold: {fold}")


def validate_task(task: str) -> None:
    if task not in BASELINE_PROMPTS:
        raise ValueError(f"Unsupported task: {task}")


def validate_prompt_preset(prompt_preset: str) -> None:
    if prompt_preset not in PROMPT_PRESETS:
        raise ValueError(f"Unsupported prompt preset: {prompt_preset}")


def dump_summary_with_overall(per_fold: dict[int, dict[str, Any]], overall: dict[str, Any]) -> dict[str, Any]:
    payload = {"per_fold": {str(key): value for key, value in sorted(per_fold.items())}, "overall": overall}
    return payload


def round_record_times(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("gt_time_sec", "pred_time_sec"):
        value = record.get(key)
        if isinstance(value, float) and math.isfinite(value):
            record[key] = round(value, 6)
    return record
