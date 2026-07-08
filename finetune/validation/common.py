from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .config import (
    ALLOWED_TYPE_LABELS,
    DEFAULT_MODEL_DIRS,
    FRACTURE_CLASSES,
    GROUND_TRUTH_CSV,
    GROUND_TRUTH_JSON,
    LABEL_ALIASES,
    PROMPT_INSTRUCTION,
    PROMPT_PRESETS,
    SPLIT_DIR,
    STRICT_INTERVAL_PROMPT,
    SUPPORTED_FOLDS,
    SUPPORTED_SPLITS,
    SUPPORTED_TASKS,
    TEST_INPUTS_JSON,
    TEST_GROUND_TRUTH_JSON,
    TEST_SUBVIDEO_GROUND_TRUTH_JSON,
    TEST_SUBVIDEO_INPUTS_JSON,
    TIME_THRESHOLD_SEC,
    TRAINING_INTERVAL_PROMPT,
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
    """Resolve the effective prompt preset.

    time/type tasks are evaluated from the joint output schema, so both prompt
    presets use the same output contract.
    """
    validate_task(task)
    validate_prompt_preset(prompt_preset)
    return prompt_preset


def build_prompt(task: str, prompt_preset: str = "strict_interval") -> tuple[str, str]:
    """Build the prompt text for the given task.

    strict_interval is the evaluation prompt; training_interval matches the
    prompt text used during SFT data generation.
    """
    resolved_prompt_preset = resolve_prompt_preset(task, prompt_preset)
    if resolved_prompt_preset == "training_interval":
        return resolved_prompt_preset, TRAINING_INTERVAL_PROMPT
    task_prompt = STRICT_INTERVAL_PROMPT["joint"]
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


def load_test_subvideo_names() -> list[str]:
    if not TEST_SUBVIDEO_INPUTS_JSON.exists():
        raise FileNotFoundError(f"Test subvideo inputs not found: {TEST_SUBVIDEO_INPUTS_JSON}")
    inputs = json.loads(TEST_SUBVIDEO_INPUTS_JSON.read_text(encoding="utf-8"))
    return [f"{item['video_id']}.mp4" for item in inputs]


def load_fold_samples(fold: int, gt_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    videos = load_split_video_names(fold)
    missing = [name for name in videos if name not in gt_map]
    if missing:
        raise ValueError(f"Fold {fold} videos missing from GT: {missing}")
    samples = [dict(gt_map[name]) for name in videos]  # Copy to avoid mutating source
    # Derive gt_has_fracture from gt_type if not already present
    for s in samples:
        if s.get("gt_has_fracture") is None:
            gt_type = s.get("gt_type")
            if gt_type in FRACTURE_CLASSES:
                s["gt_has_fracture"] = True
            elif gt_type in ("未断裂", "未夹紧"):
                s["gt_has_fracture"] = False
            elif gt_type == "视频异常":
                s["gt_has_fracture"] = None
    return samples


def load_test_inputs(path: Path = TEST_INPUTS_JSON) -> list[dict[str, Any]]:
    """Load test video input metadata from test_inputs.json.

    Returns list of dicts with keys: id, video_id, video_path.
    """
    if not path.exists():
        raise FileNotFoundError(f"Test inputs not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_test_ground_truth(path: Path = TEST_GROUND_TRUTH_JSON) -> dict[str, dict[str, Any]]:
    """Load test ground truth from test_ground_truth.json.

    Returns {video_id: record} mapping.
    The test GT has fields:
      video_id, has_fracture, type, location, event_time, event_frame_original,
      is_abnormal, video_anomaly_kind, event_time_reliable, etc.

    Normalize to standard fields:
      - gt_has_fracture: bool or None
      - gt_type: normalized type string
      - gt_location: location string ("inside_gauge"/"outside_gauge"/"N_A"/None)
      - gt_time_sec: float or None
      - time_available: bool
    """
    if not path.exists():
        raise FileNotFoundError(f"Test ground truth not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, Any]] = {}
    for item in data:
        vid = item["video_id"]
        gt_type_raw = item.get("type")
        gt_type = normalize_ground_truth_label(gt_type_raw)
        event_time = item.get("event_time")
        # event_time could be a float (seconds) or a string like "视频异常" or "未断裂"
        gt_time_sec: float | None = None
        time_available = False
        if isinstance(event_time, (int, float)):
            gt_time_sec = float(event_time)
            time_available = True
        elif isinstance(event_time, str):
            try:
                gt_time_sec = float(event_time)
                time_available = True
            except (ValueError, TypeError):
                gt_time_sec = None
                time_available = False

        result[vid] = {
            "video_id": vid,
            "video_name": f"{vid}.mp4",
            "source_video_id": item.get("source_video_id"),
            "subvideo_id": item.get("subvideo_id"),
            "crop_type": item.get("crop_type"),
            # For 视频异常, fracture presence is canonically unknown → use None
            "gt_has_fracture": None if gt_type == "视频异常" else item.get("has_fracture"),
            "gt_fracture_between": item.get("fracture_between"),
            "gt_type": gt_type,
            "gt_location": item.get("location"),
            "gt_time_sec": gt_time_sec,
            "gt_time_raw": event_time,
            "time_available": time_available,
            "event_time_reliable": item.get("event_time_reliable", False),
            "is_abnormal": item.get("is_abnormal", False),
            "video_anomaly_kind": item.get("video_anomaly_kind"),
            "location_canonical": item.get("location_canonical"),
            "_source": "test_ground_truth",
        }
    return result


def load_test_split_samples(
    inputs_path: Path = TEST_INPUTS_JSON,
    ground_truth_path: Path = TEST_GROUND_TRUTH_JSON,
) -> list[dict[str, Any]]:
    """Load test split samples combining test_inputs.json and test_ground_truth.json.

    Returns list of sample dicts compatible with load_fold_samples() output.
    Each sample has: video_id, video_name, video_path, gt_*, etc.
    """
    test_inputs = load_test_inputs(inputs_path)
    test_gt = load_test_ground_truth(ground_truth_path)

    samples: list[dict[str, Any]] = []
    for inp in test_inputs:
        vid = inp["video_id"]
        if vid not in test_gt:
            raise ValueError(f"Test video {vid} has no ground truth entry")
        gt = test_gt[vid]
        samples.append({
            "video_id": vid,
            "video_name": Path(inp.get("video_path", f"data/01_videos/{vid}.mp4")).name,
            "video_path": inp.get("video_path", f"data/01_videos/{vid}.mp4"),
            "source_video_id": inp.get("source_video_id"),
            "subvideo_id": inp.get("subvideo_id"),
            "crop_type": inp.get("crop_type"),
            "frame_mapping": inp.get("frame_mapping"),
            "processor_fingerprint": inp.get("processor_fingerprint"),
            **gt,
        })
    return samples


def load_test_subvideo_split_samples() -> list[dict[str, Any]]:
    return load_test_split_samples(
        TEST_SUBVIDEO_INPUTS_JSON,
        TEST_SUBVIDEO_GROUND_TRUTH_JSON,
    )


def load_video_metadata() -> dict[str, dict[str, Any]]:
    """Load video metadata (total_frames, fps) from the annotation CSV.

    Returns {video_id: {"total_frames": int, "fps": float}}.
    """
    if not GROUND_TRUTH_CSV.exists():
        return {}
    with GROUND_TRUTH_CSV.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        result: dict[str, dict[str, Any]] = {}
        for row in reader:
            vid = str(row["id"]).strip()
            try:
                total_frames = int(row.get("视频总帧数", 0))
                fps = float(row.get("视频帧率", 30))
                if total_frames > 0 and fps > 0:
                    result[vid] = {"total_frames": total_frames, "fps": fps}
            except (ValueError, TypeError):
                pass
    return result


def generate_frame_mapping(total_frames: int, fps: float, max_frames: int = 8) -> list[dict[str, Any]]:
    """Generate uniform frame mapping matching MiniCPM processor sampling behavior.

    Returns list of {index, original_frame, timestamp} dicts.
    """
    frames: list[dict[str, Any]] = []
    n = min(max_frames, total_frames)
    step = total_frames / n if n > 0 else 0.0
    for i in range(n):
        frame_idx = min(int(i * step), total_frames - 1)
        timestamp = round(frame_idx / fps, 6) if fps > 0 else 0.0
        frames.append({
            "index": i,
            "original_frame": frame_idx,
            "timestamp": timestamp,
        })
    return frames


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


def _resolve_frame_indices_to_time_range(record: dict[str, Any]) -> tuple[float, float] | None:
    """将预测的帧索引（如 [2, 3]）通过预处理元数据中的帧时间戳，转换为秒级时间区间。

    record["pred_time_range"] 存储的是模型输出的 fracture_between 整数帧索引，
    record["preprocessing"]["frames"] 存储了每个采样帧的 index 和 timestamp。
    """
    pred_range = record.get("pred_time_range")
    if not isinstance(pred_range, (list, tuple)) or len(pred_range) != 2:
        return None
    start_idx, end_idx = pred_range
    if not (isinstance(start_idx, int) and isinstance(end_idx, int)):
        return None

    frames = record.get("preprocessing", {}).get("frames", [])
    if not frames:
        return None

    # 在 frames 列表中查找匹配的帧索引
    start_frame = next((f for f in frames if f.get("index") == start_idx), None)
    end_frame = next((f for f in frames if f.get("index") == end_idx), None)
    if start_frame is None or end_frame is None:
        return None

    start_ts = start_frame.get("timestamp")
    end_ts = end_frame.get("timestamp")
    if start_ts is None or end_ts is None:
        return None

    try:
        low = float(start_ts)
        high = float(end_ts)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(low) or not math.isfinite(high):
        return None
    if low > high:
        low, high = high, low
    return (low, high)


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
    # the video has a fracture. Use gt_has_fracture or gt_type in FRACTURE_CLASSES.
    fracture_records = []
    non_fracture_records = []
    for record in records:
        gt_type = record.get("gt_type")
        gt_has_fracture = record.get("gt_has_fracture")
        is_fracture = gt_type in FRACTURE_CLASSES
        if not is_fracture:
            non_fracture_records.append(record)
        else:
            fracture_records.append(record)

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
    class_count = len(labels)
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

    # false_positive_rate: GT non-fracture but pred is fracture
    fp_count = sum(
        1 for record in non_fracture_records
        if record.get("pred_type_norm") in FRACTURE_CLASSES
        or record.get("pred_has_fracture") is True
    )
    non_fracture_total = len(non_fracture_records)

    # false_negative_rate: GT fracture but pred is not fracture
    fn_count = sum(
        1 for record in fracture_records
        if record.get("pred_type_norm") not in FRACTURE_CLASSES
        or record.get("pred_has_fracture") is not True
    )
    fracture_total = len(fracture_records)

    summary: dict[str, Any] = {
        "total_count": len(records),
        "count": total,
        "accuracy": round(correct / total, 6) if total else 0.0,
        "macro_precision": round(macro_precision / class_count, 6),
        "macro_recall": round(macro_recall / class_count, 6),
        "macro_f1": round(macro_f1 / class_count, 6),
        "false_positive_count": fp_count,
        "false_positive_rate": round(fp_count / non_fracture_total, 6) if non_fracture_total else 0.0,
        "false_negative_count": fn_count,
        "false_negative_rate": round(fn_count / fracture_total, 6) if fracture_total else 0.0,
        "non_fracture_count": non_fracture_total,
        "fracture_count": fracture_total,
    }
    if total == 0:
        summary["macro_f1_note"] = (
            "No fracture-class gt_type records; "
            "macro-F1 is undefined and reported as 0."
        )

    for label in labels:
        row = {"gt_type": label}
        for pred_label in confusion_cols:
            row[pred_label] = confusion[(label, pred_label)]
        confusion_rows.append(row)

    return summary, per_class_rows, confusion_rows


def _is_valid_time_range(value: Any) -> bool:
    """Check if a value is a valid time range: length-2 list/tuple of finite numbers."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    try:
        low, high = float(value[0]), float(value[1])
        if not math.isfinite(low) or not math.isfinite(high):
            return False
    except (TypeError, ValueError):
        return False
    return True


def compute_interval_metrics(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compute interval-based time localization metrics.

    Returns (summary_dict, error_rows_list).

    Metrics computed:
    - interval_hit_rate: GT time falls within pred_time_range_sec
    - midpoint_mae: mean absolute error of pred_time_midpoint_sec vs gt_time_sec
    - midpoint_mse: mean squared error
    - within_1s/3s/5s: percentage of samples within N seconds of GT
    - unparseable_or_invalid_rate: samples with json_invalid, schema_invalid, or frame_mapping_missing

    Only samples with time_available=True and valid pred_time_midpoint_sec participate
    in time metrics. All samples participate in schema/invalid metrics.
    """
    total = len(records)
    # Only records with valid JSON and valid schema can contribute to time metrics
    valid_records = [r for r in records if r.get("json_valid") and r.get("schema_valid")]
    time_available = [r for r in valid_records if r.get("time_available")]
    has_midpoint = [r for r in time_available if r.get("pred_time_midpoint_sec") is not None]
    has_range = [r for r in time_available if _is_valid_time_range(r.get("pred_time_range_sec"))]

    # Schema/invalid stats
    json_invalid = sum(1 for r in records if not r.get("json_valid", False))
    schema_invalid = sum(1 for r in records if not r.get("schema_valid", True))
    frame_missing = sum(1 for r in records if r.get("failure_reason") == "frame_mapping_missing")
    # Deduplicate: count unique samples that fail ANY validity check
    invalid_ids = set()
    for r in records:
        vid = r.get("video_id", str(id(r)))
        if not r.get("json_valid", False) or not r.get("schema_valid", True) or r.get("failure_reason") == "frame_mapping_missing":
            invalid_ids.add(vid)
    unparseable = len(invalid_ids)

    # Midpoint errors
    errors_list = []
    sum_abs_error = 0.0
    sum_sq_error = 0.0
    within_1s = 0
    within_3s = 0
    within_5s = 0
    interval_hit = 0

    for r in has_midpoint:
        gt_time = r["gt_time_sec"]
        midpoint = r["pred_time_midpoint_sec"]
        error = abs(midpoint - gt_time)
        sum_abs_error += error
        sum_sq_error += error * error
        if error <= 1.0:
            within_1s += 1
        if error <= 3.0:
            within_3s += 1
        if error <= 5.0:
            within_5s += 1
        errors_list.append({
            "video_id": r.get("video_id"),
            "gt_time_sec": gt_time,
            "pred_midpoint_sec": midpoint,
            "abs_error_sec": round(error, 6),
        })

    for r in has_range:
        gt_time = r["gt_time_sec"]
        tr = r["pred_time_range_sec"]
        # Already validated by _is_valid_time_range filter, but use safe access
        if isinstance(tr, (list, tuple)) and len(tr) == 2:
            low, high = float(tr[0]), float(tr[1])
            if low <= gt_time <= high:
                interval_hit += 1

    m_count = len(has_midpoint) or 1
    ta_count = len(time_available) or 1

    summary: dict[str, Any] = {
        "total_samples": total,
        "time_available_count": len(time_available),
        "has_midpoint_count": len(has_midpoint),
        "has_range_count": len(has_range),
        "interval_hit_rate": round(interval_hit / ta_count, 6) if time_available else None,
        "midpoint_mae": round(sum_abs_error / m_count, 6) if has_midpoint else None,
        "midpoint_mse": round(sum_sq_error / m_count, 6) if has_midpoint else None,
        "within_1s": round(within_1s / ta_count, 6) if time_available else None,
        "within_3s": round(within_3s / ta_count, 6) if time_available else None,
        "within_5s": round(within_5s / ta_count, 6) if time_available else None,
        "json_invalid_count": json_invalid,
        "schema_invalid_count": schema_invalid,
        "frame_mapping_missing_count": frame_missing,
        "unparseable_or_invalid_count": unparseable,
        "unparseable_or_invalid_rate": round(unparseable / total, 6) if total else 0.0,
    }

    return summary, errors_list


def compute_joint_interval_metrics(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compute joint (interval + type) success metrics.

    joint_success = schema_valid AND:
      - has_fracture judgment correct (pred matches GT)
      - If GT is fracture class: type correct AND interval hit
      - If GT is non-fracture: prediction is valid AND no fracture_between produced

    Returns (summary_dict, failure_rows_list).
    """
    total = len(records)
    success_count = 0
    failure_rows: list[dict[str, Any]] = []

    fracture_samples = [r for r in records if r.get("gt_type") in FRACTURE_CLASSES]
    non_fracture_samples = [r for r in records if r.get("gt_type") not in FRACTURE_CLASSES]

    for r in records:
        if not r.get("schema_valid", False) or not r.get("json_valid", False):
            failure_rows.append({
                "video_id": r.get("video_id"),
                "gt_type": r.get("gt_type"),
                "failure_reason": "schema_invalid",
                "details": r.get("schema_errors", ""),
            })
            continue

        gt_type = r.get("gt_type")
        pred_type = r.get("pred_type_norm")
        gt_hf = r.get("gt_has_fracture")
        pred_hf = r.get("pred_has_fracture")

        # Has_fracture judgment
        hf_correct = (gt_hf == pred_hf)
        if not hf_correct:
            failure_rows.append({
                "video_id": r.get("video_id"),
                "gt_type": gt_type,
                "failure_reason": "has_fracture_mismatch",
                "details": f"GT has_fracture={gt_hf}, pred={pred_hf}",
            })
            continue

        if gt_type in FRACTURE_CLASSES:
            # Type correct
            type_correct = (pred_type == gt_type)
            if not type_correct:
                failure_rows.append({
                    "video_id": r.get("video_id"),
                    "gt_type": gt_type,
                    "failure_reason": "type_mismatch",
                    "details": f"GT type={gt_type}, pred={pred_type}",
                })
                continue

            # Interval hit (if time available)
            if r.get("time_available") and _is_valid_time_range(r.get("pred_time_range_sec")):
                gt_time = r["gt_time_sec"]
                tr = r["pred_time_range_sec"]
                low, high = float(tr[0]), float(tr[1])
                if low <= gt_time <= high:
                    success_count += 1
                else:
                    failure_rows.append({
                        "video_id": r.get("video_id"),
                        "gt_type": gt_type,
                        "failure_reason": "interval_miss",
                        "details": f"GT time={gt_time}s not in range=[{low}, {high}]",
                    })
            elif r.get("time_available"):
                # GT fracture with time_available, but no pred_time_range_sec -> failure
                reason = "frame_mapping_missing" if r.get("failure_reason") == "frame_mapping_missing" else "no_range"
                failure_rows.append({
                    "video_id": r.get("video_id"),
                    "gt_type": gt_type,
                    "failure_reason": reason,
                    "details": f"GT time={r.get('gt_time_sec')}s but no pred_time_range_sec (failure={r.get('failure_reason')})",
                })
                continue
            else:
                # Time NOT available in GT -> only type+has_fracture correctness matters
                success_count += 1
        else:
            # Non-fracture: should NOT have fracture_between
            pred_fb = r.get("pred_fracture_between")
            if pred_fb is not None:
                failure_rows.append({
                    "video_id": r.get("video_id"),
                    "gt_type": gt_type,
                    "failure_reason": "false_positive_fracture",
                    "details": f"Non-fracture GT but pred fracture_between={pred_fb}",
                })
            else:
                success_count += 1

    # Failure reason distribution
    failure_reasons = Counter(f["failure_reason"] for f in failure_rows)

    summary: dict[str, Any] = {
        "total_samples": total,
        "fracture_samples": len(fracture_samples),
        "non_fracture_samples": len(non_fracture_samples),
        "success_count": success_count,
        "joint_success_rate": round(success_count / total, 6) if total else 0.0,
        "failure_count": len(failure_rows),
        "failure_reasons": dict(failure_reasons),
    }

    return summary, failure_rows


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
    pred_range = _resolve_frame_indices_to_time_range(record)
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
    pred_range = _resolve_frame_indices_to_time_range(record)
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
    if task not in SUPPORTED_TASKS:
        raise ValueError(f"Unsupported task: {task}")


def validate_prompt_preset(prompt_preset: str) -> None:
    if prompt_preset not in PROMPT_PRESETS:
        raise ValueError(f"Unsupported prompt preset: {prompt_preset}")


def validate_interval_schema(payload: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """Validate a parsed JSON payload against the interval 5-field protocol.

    Returns (valid, errors_list).
    """
    errors: list[str] = []
    if payload is None:
        return False, ["payload is None"]

    # Check required fields exist
    required_fields = ["has_fracture", "fracture_between", "type", "location", "confidence"]
    for field in required_fields:
        if field not in payload:
            errors.append(f"missing field: {field}")

    if errors:
        return False, errors

    # Must have ONLY the five fields, no extras
    allowed_fields = {"has_fracture", "fracture_between", "type", "location", "confidence"}
    extra_fields = set(payload.keys()) - allowed_fields
    if extra_fields:
        errors.append(f"extra fields not allowed in interval protocol: {sorted(extra_fields)}")

    # has_fracture must be true, false, or null
    hf = payload.get("has_fracture")
    if hf not in (True, False, None):
        errors.append(f"has_fracture must be true/false/null, got {type(hf).__name__}: {hf!r}")

    # type validation
    pred_type = payload.get("type")
    if not isinstance(pred_type, str) or pred_type not in ALLOWED_TYPE_LABELS:
        errors.append(f"type not in allowed labels: {pred_type!r}")
    else:
        norm_type = normalize_prediction_label(pred_type)
    norm_type = normalize_prediction_label(payload.get("type"))

    # fracture_between type
    fb = payload.get("fracture_between")

    # location type
    loc = payload.get("location")

    # confidence must be numeric 0-1
    conf = payload.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        errors.append(f"confidence must be a number, got {type(conf).__name__}: {conf!r}")
    else:
        if conf < 0.0 or conf > 1.0:
            errors.append(f"confidence out of [0, 1] range: {conf}")

    # Legal combination rules
    if norm_type in FRACTURE_CLASSES:
        if hf is not True:
            errors.append(f"fracture type {norm_type!r} requires has_fracture=true, got {hf!r}")
        if not isinstance(fb, list) or len(fb) != 2:
            errors.append(f"fracture type {norm_type!r} requires fracture_between=[i, i+1], got {fb!r}")
        elif not all(isinstance(v, int) and not isinstance(v, bool) for v in fb):
            errors.append(f"fracture_between elements must be ints, got {fb!r}")
        elif fb[1] != fb[0] + 1:
            errors.append(f"fracture_between must be adjacent integers [i, i+1], got {fb!r}")
        elif fb[0] < 0 or fb[1] > 7:
            errors.append(f"fracture_between values out of range 0-7, got {fb!r}")
        if loc is not None and loc not in ("inside_gauge", "outside_gauge"):
            errors.append(f"fracture type {norm_type!r} requires location inside_gauge/outside_gauge or null, got {loc!r}")
    elif norm_type in ("未断裂", "未夹紧"):
        if hf is not False:
            errors.append(f"type {norm_type!r} requires has_fracture=false, got {hf!r}")
        if fb is not None:
            errors.append(f"type {norm_type!r} requires fracture_between=null, got {fb!r}")
        if loc is not None:
            errors.append(f"type {norm_type!r} requires location=null, got {loc!r}")
    elif norm_type == "视频异常":
        if hf is not None:
            errors.append(f"type 视频异常 requires has_fracture=null, got {hf!r}")
        if fb is not None:
            errors.append(f"type 视频异常 requires fracture_between=null, got {fb!r}")
        if loc is not None:
            errors.append(f"type 视频异常 requires location=null, got {loc!r}")

    return len(errors) == 0, errors


def dump_summary_with_overall(per_fold: dict[int, dict[str, Any]], overall: dict[str, Any]) -> dict[str, Any]:
    payload = {"per_fold": {str(key): value for key, value in sorted(per_fold.items())}, "overall": overall}
    return payload


def round_record_times(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("gt_time_sec", "pred_time_sec"):
        value = record.get(key)
        if isinstance(value, float) and math.isfinite(value):
            record[key] = round(value, 6)
    return record


def read_results_and_meta(results_paths: list[str], meta_paths: list[str]) -> list[dict]:
    """Read and join results + meta JSONL files by line order (same order written by run_inference).

    Args:
        results_paths: One or more results JSONL paths (prediction fields).
        meta_paths: One or more meta JSONL paths (GT, validation, experiment fields).
                    Must have the same count as results_paths, paired by index.

    Returns:
        List of merged records (results + meta) for all files combined.
    """
    if len(results_paths) != len(meta_paths):
        raise ValueError(
            f"results_paths ({len(results_paths)}) and meta_paths ({len(meta_paths)}) "
            f"must have the same count"
        )

    all_records = []
    for res_path, meta_path in zip(results_paths, meta_paths):
        with open(res_path, "r") as f:
            results_records = [json.loads(line) for line in f if line.strip()]
        with open(meta_path, "r") as f:
            meta_records = [json.loads(line) for line in f if line.strip()]

        if len(results_records) != len(meta_records):
            raise ValueError(
                f"Mismatched line count: {res_path} ({len(results_records)}) vs "
                f"{meta_path} ({len(meta_records)})"
            )

        for r, m in zip(results_records, meta_records):
            all_records.append({**r, **m})

    return all_records
