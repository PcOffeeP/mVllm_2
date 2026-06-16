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
    FRACTURE_CLASSES,
    GROUND_TRUTH_CSV,
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


def _load_ground_truth_csv(csv_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            video_id = str(row["id"]).strip()
            gt_time_raw = row["断裂时间点"].strip() if row.get("断裂时间点") else None
            gt_time_raw = gt_time_raw or None
            records.append(
                {
                    "video_id": video_id,
                    "video_name": f"{video_id}.mp4",
                    "gt_time_raw": gt_time_raw,
                    "gt_time_sec": parse_seconds(gt_time_raw),
                    "time_available": gt_time_raw is not None and parse_seconds(gt_time_raw) is not None,
                    "gt_type": normalize_ground_truth_label(row.get("断裂模式")),
                    "material": row.get("材料类型") or None,
                    "clarity": row.get("清晰度") or None,
                }
            )
    return records


def load_ground_truth(path: Path = GROUND_TRUTH_JSON) -> dict[str, dict[str, Any]]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    elif GROUND_TRUTH_CSV.exists():
        data = _load_ground_truth_csv(GROUND_TRUTH_CSV)
    else:
        raise FileNotFoundError(f"Ground truth JSON or CSV not found: {path}, {GROUND_TRUTH_CSV}")
    return {item["video_name"]: item for item in data}


def load_split_video_names(fold: int) -> list[str]:
    validate_fold(fold)
    new_path = SPLIT_DIR / f"fold_{fold}_val.json"
    if new_path.exists():
        split = json.loads(new_path.read_text(encoding="utf-8"))
        return [f"{video_id}.mp4" for video_id in split.get("video_ids", [])]

    # 保留对旧 stratified split 文件的最小兼容
    old_path = SPLIT_DIR / f"stratified_3_fold_{fold}.json"
    if old_path.exists():
        split = json.loads(old_path.read_text(encoding="utf-8"))
        names = [Path(item).name for item in split["val"]]
        # Normalize: strip legacy prefixes so config.py can prepend VIDEO_DIR uniformly
        names = [n.replace("Video\\all_videos\\", "").replace("Video/all_videos/", "").replace("videos/", "") for n in names]
        return names

    raise FileNotFoundError(f"Split file not found for fold {fold}: tried {new_path} and {old_path}")


def load_test_video_names() -> list[str]:
    split_path = SPLIT_DIR / "test.json"
    if not split_path.exists():
        raise FileNotFoundError(f"Test split file not found: {split_path}")
    split = json.loads(split_path.read_text(encoding="utf-8"))
    return [f"{video_id}.mp4" for video_id in split.get("video_ids", [])]


def load_fold_samples(fold: int, gt_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    videos = load_split_video_names(fold)
    missing = [name for name in videos if name not in gt_map]
    if missing:
        raise ValueError(f"Fold {fold} videos missing from GT: {missing}")
    return [gt_map[name] for name in videos]


def parse_time_range(value: Any) -> tuple[float, float] | None:
    """解析 time_range 为 (low, high)，非法或为空时返回 None。"""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            low = float(value[0])
            high = float(value[1])
        except (TypeError, ValueError):
            return None
        if not math.isfinite(low) or not math.isfinite(high):
            return None
        if low > high:
            low, high = high, low
        return (low, high)
    return None


def time_range_contains_gt(time_range: tuple[float, float] | None, gt_time: float | None) -> bool:
    if time_range is None or gt_time is None:
        return False
    return time_range[0] <= gt_time <= time_range[1]


_CONFIDENCE_LEVEL_SCORE = {"高": 0.9, "中": 0.6, "低": 0.3, "不可信": 0.25}


def _extract_confidence(record: dict[str, Any]) -> tuple[float | None, str | None]:
    """从记录中提取 confidence score 或 level；返回 (score, level)。"""
    score = record.get("pred_confidence_score")
    if score is None:
        score = record.get("confidence_score")
    if score is None:
        score = record.get("final_confidence")
    if score is not None:
        try:
            score = float(score)
            if math.isnan(score) or math.isinf(score):
                return None, None
            score = max(0.0, min(1.0, score))
            return score, None
        except (TypeError, ValueError):
            pass
    level = record.get("pred_confidence_level")
    if level is None:
        level = record.get("confidence_level")
    if level is not None:
        level = str(level).strip()
        if level in _CONFIDENCE_LEVEL_SCORE:
            return _CONFIDENCE_LEVEL_SCORE[level], level
    return None, None


def _confidence_bucket(score: float) -> str | None:
    """将 0~1 的 confidence score 分桶为 0.0-0.1, 0.1-0.2, ..., 0.9-1.0。

    非有限值（NaN / inf）不会被归入任何桶。
    """
    if not math.isfinite(score):
        return None
    score = max(0.0, min(1.0, float(score)))
    bucket = min(int(score * 10), 9)
    return f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}"


def _update_confidence_bucket(
    buckets: dict[str, Any],
    record: dict[str, Any],
    pred_range: tuple[float, float] | None,
    gt_time: float,
) -> None:
    score, level = _extract_confidence(record)
    if score is None and level is None:
        return

    bucket_key: str | None = None
    avg_confidence: float | None = None
    if score is not None:
        bucket_key = _confidence_bucket(score)
        avg_confidence = score
    else:
        bucket_key = level
        avg_confidence = _CONFIDENCE_LEVEL_SCORE[level]

    if bucket_key is None or avg_confidence is None:
        return

    bucket = buckets.setdefault(
        bucket_key,
        {
            "count": 0,
            "sum_confidence": 0.0,
            "range_hit_count": 0,
            "within_1s_count": 0,
            "within_3s_count": 0,
            "within_5s_count": 0,
        },
    )
    bucket["count"] += 1
    bucket["sum_confidence"] += avg_confidence
    if time_range_contains_gt(pred_range, gt_time):
        bucket["range_hit_count"] += 1
    pred_time = record.get("pred_time_sec")
    if pred_time is not None:
        error = abs(pred_time - gt_time)
        for threshold in (1.0, 3.0, 5.0):
            if error <= threshold:
                bucket[f"within_{int(threshold)}s_count"] += 1


def _finalize_confidence_buckets(buckets: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, bucket in buckets.items():
        count = bucket["count"]
        rows.append(
            {
                "bucket": key,
                "count": count,
                "avg_confidence": round(bucket["sum_confidence"] / count, 6) if count else None,
                "range_hit_rate": round(bucket["range_hit_count"] / count, 6) if count else None,
                "within_1s_rate": round(bucket["within_1s_count"] / count, 6) if count else None,
                "within_3s_rate": round(bucket["within_3s_count"] / count, 6) if count else None,
                "within_5s_rate": round(bucket["within_5s_count"] / count, 6) if count else None,
            }
        )

    def _sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
        key = row["bucket"]
        if key in _CONFIDENCE_LEVEL_SCORE:
            return (1, _CONFIDENCE_LEVEL_SCORE[key], "")
        try:
            return (0, float(key.split("-")[0]), "")
        except ValueError:
            return (2, 0.0, key)

    rows.sort(key=_sort_key)
    return rows


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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    ensure_parent_dir(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def compute_type_metrics(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    # ``type`` macro-F1 is only defined on samples where the ground truth says
    # the video has a fracture and the type is one of the seven fracture classes.
    # All other samples (``has_fracture = false`` or non-fracture ``gt_type``)
    # are tracked separately via a failure rate and must not enter macro-F1.
    fracture_records = [
        record
        for record in records
        if record.get("has_fracture") is True and record.get("gt_type") in FRACTURE_CLASSES
    ]
    non_fracture_records = [
        record
        for record in records
        if not (record.get("has_fracture") is True and record.get("gt_type") in FRACTURE_CLASSES)
    ]

    labels = sorted(FRACTURE_CLASSES)
    pred_labels = sorted(
        {record.get("pred_type_norm") for record in fracture_records if record.get("pred_type_norm")}
    )
    confusion_cols = labels + [label for label in pred_labels if label not in labels]
    if "__INVALID__" not in confusion_cols:
        confusion_cols.append("__INVALID__")

    total = len(fracture_records)
    correct = 0
    per_class_rows: list[dict[str, Any]] = []
    confusion_rows: list[dict[str, Any]] = []

    confusion = {(gt_label, pred_label): 0 for gt_label in labels for pred_label in confusion_cols}
    for record in fracture_records:
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
        tp = sum(
            1
            for record in fracture_records
            if record["gt_type"] == label and record.get("pred_type_norm") == label
        )
        fp = sum(
            1
            for record in fracture_records
            if record["gt_type"] != label and record.get("pred_type_norm") == label
        )
        fn = sum(
            1
            for record in fracture_records
            if record["gt_type"] == label and record.get("pred_type_norm") != label
        )
        support = sum(1 for record in fracture_records if record["gt_type"] == label)
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
    type_failure_count = sum(
        1 for record in non_fracture_records if record.get("pred_type_norm") in FRACTURE_CLASSES
    )
    type_non_fracture_count = len(non_fracture_records)
    summary: dict[str, Any] = {
        "total_count": len(records),
        "count": total,
        "accuracy": round(correct / total, 6) if total else 0.0,
        "macro_precision": round(macro_precision / class_count, 6),
        "macro_recall": round(macro_recall / class_count, 6),
        "macro_f1": round(macro_f1 / class_count, 6),
        "type_failure_count": type_failure_count,
        "type_failure_rate": round(
            type_failure_count / type_non_fracture_count, 6
        ) if type_non_fracture_count else 0.0,
        "type_non_fracture_count": type_non_fracture_count,
    }
    if total == 0:
        summary["macro_f1_note"] = (
            "No has_fracture=true records with fracture-class gt_type; "
            "macro-F1 is undefined and reported as 0."
        )

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
        "time_range_hit_count": 0,
        "within_1s_count": 0,
        "within_3s_count": 0,
        "within_5s_count": 0,
        "confidence_buckets": {},
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
    pred_range = parse_time_range(record.get("pred_time_range"))
    if pred_time is None:
        agg["time_unparseable_count"] += 1
        return

    agg["parseable_prediction_count"] += 1
    error = abs(pred_time - record["gt_time_sec"])
    agg["sum_abs_error"] += error
    agg["sum_squared_error"] += error * error
    if error < threshold:
        agg["hit_at_2s_count"] += 1
    for thr in (1.0, 3.0, 5.0):
        if error <= thr:
            agg[f"within_{int(thr)}s_count"] += 1
    if time_range_contains_gt(pred_range, record["gt_time_sec"]):
        agg["time_range_hit_count"] += 1
    _update_confidence_bucket(agg["confidence_buckets"], record, pred_range, record["gt_time_sec"])


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
        "time_range_hit": round(agg["time_range_hit_count"] / applicable, 6) if agg["applicable_count"] else None,
        "within_1s": round(agg["within_1s_count"] / applicable, 6) if agg["applicable_count"] else None,
        "within_3s": round(agg["within_3s_count"] / applicable, 6) if agg["applicable_count"] else None,
        "within_5s": round(agg["within_5s_count"] / applicable, 6) if agg["applicable_count"] else None,
        "time_unparseable_ratio": round(agg["time_unparseable_count"] / applicable, 6) if agg["applicable_count"] else None,
        "confidence_buckets": _finalize_confidence_buckets(agg["confidence_buckets"]),
    }


def init_joint_aggregator() -> dict[str, Any]:
    return {
        "count": 0,
        "applicable_count": 0,
        "excluded_no_gt_time": 0,
        "json_valid_count": 0,
        "time_within_threshold_count": 0,
        "time_range_hit_count": 0,
        "within_1s_count": 0,
        "within_3s_count": 0,
        "within_5s_count": 0,
        "type_correct_count": 0,
        "joint_success_count": 0,
        "failure_reasons": Counter(),
        "confidence_buckets": {},
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
    pred_range = parse_time_range(record.get("pred_time_range"))
    error = abs(pred_time - record["gt_time_sec"]) if pred_time is not None else None
    time_ok = error is not None and error < threshold
    type_ok = record.get("pred_type_norm") == record["gt_type"]
    if time_ok:
        agg["time_within_threshold_count"] += 1
    if error is not None:
        for thr in (1.0, 3.0, 5.0):
            if error <= thr:
                agg[f"within_{int(thr)}s_count"] += 1
    if time_range_contains_gt(pred_range, record["gt_time_sec"]):
        agg["time_range_hit_count"] += 1
    if type_ok:
        agg["type_correct_count"] += 1
    if record["json_valid"] and time_ok and type_ok:
        agg["joint_success_count"] += 1
    elif record.get("failure_reason"):
        agg["failure_reasons"][record["failure_reason"]] += 1

    if pred_time is not None:
        _update_confidence_bucket(agg["confidence_buckets"], record, pred_range, record["gt_time_sec"])


def finalize_joint_aggregator(agg: dict[str, Any]) -> dict[str, Any]:
    applicable = agg["applicable_count"] or 1
    return {
        "count": agg["count"],
        "applicable_count": agg["applicable_count"],
        "excluded_no_gt_time": agg["excluded_no_gt_time"],
        "json_valid_count": agg["json_valid_count"],
        "time_within_threshold_count": agg["time_within_threshold_count"],
        "time_range_hit": round(agg["time_range_hit_count"] / applicable, 6) if agg["applicable_count"] else None,
        "within_1s": round(agg["within_1s_count"] / applicable, 6) if agg["applicable_count"] else None,
        "within_3s": round(agg["within_3s_count"] / applicable, 6) if agg["applicable_count"] else None,
        "within_5s": round(agg["within_5s_count"] / applicable, 6) if agg["applicable_count"] else None,
        "type_correct_count": agg["type_correct_count"],
        "joint_success_count": agg["joint_success_count"],
        "joint_success_rate": round(agg["joint_success_count"] / applicable, 6) if agg["applicable_count"] else None,
        "failure_reasons": dict(agg["failure_reasons"]),
        "confidence_buckets": _finalize_confidence_buckets(agg["confidence_buckets"]),
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
