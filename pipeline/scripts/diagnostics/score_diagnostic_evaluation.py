# 迁入说明
# 来源：codeup/diagnostics/data-visual-audit @ bcdf4f36
# 原始提交日期：2026-07-19
# 迁入日期：2026-10-18
# 迁入原因：保留 2026-07 诊断结论与负面证据：has_fracture recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
# 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置可能已失效；正文数字与结论保持原样未改，请按历史证据阅读，不要当作当前状态。
# 失效路径（正文引用、当前仓库不存在）：无
# 未随迁：无（本文件不读写 finetune/results/diagnostics/ 下的数据）

#!/usr/bin/env python3
"""Score diagnostic evaluation JSONL with task-level and source-level metrics."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


CORE_FIELDS = ("has_fracture", "fracture_between", "type", "location")
LEGAL_TYPES = {
    "未断裂",
    "视频异常",
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
    "脆性断裂、齐根断裂",
    "未夹紧",
}
LEGAL_LOCATIONS = {None, "inside_gauge", "outside_gauge"}
FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
    "脆性断裂、齐根断裂",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a diagnostic evaluation JSONL.")
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-manifest", type=Path)
    return parser.parse_args()


def extract_json(raw_output: Any) -> tuple[dict[str, Any] | None, str | None]:
    text = str(raw_output or "").strip()
    if not text:
        return None, "empty_output"
    if "结果：" in text:
        text = text.split("结果：", 1)[1].strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None, "json_not_found"
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            return None, f"json_decode_error:{exc.msg}"
    if not isinstance(value, dict):
        return None, "json_not_object"
    return value, None


def schema_valid(value: dict[str, Any] | None) -> bool:
    if value is None or any(field not in value for field in CORE_FIELDS):
        return False
    if value["has_fracture"] not in (True, False, None):
        return False
    interval = value["fracture_between"]
    if interval is not None and not (
        isinstance(interval, list)
        and len(interval) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in interval)
    ):
        return False
    if not isinstance(value["type"], str):
        return False
    if value["location"] is not None and not isinstance(value["location"], str):
        return False
    return True


def legal_combination(value: dict[str, Any] | None) -> bool:
    if not schema_valid(value):
        return False
    assert value is not None
    if value["type"] not in LEGAL_TYPES or value["location"] not in LEGAL_LOCATIONS:
        return False
    if value["has_fracture"] is True:
        interval = value["fracture_between"]
        adjacent = (
            isinstance(interval, list)
            and 0 <= interval[0] < interval[1] <= 7
            and interval[1] == interval[0] + 1
        )
        if value["type"] in FRACTURE_TYPES:
            return adjacent and value["location"] in LEGAL_LOCATIONS
        if value["type"] == "未夹紧":
            return adjacent and value["location"] is None
        if value["type"] == "视频异常":
            return interval is None and value["location"] is None
        return False
    if value["has_fracture"] is False:
        return (
            value["fracture_between"] is None
            and value["type"] in {"未断裂", "未夹紧"}
            and value["location"] is None
        )
    return (
        value["fracture_between"] is None
        and value["type"] == "视频异常"
        and value["location"] is None
    )


def safe_div(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None and not math.isnan(value) else None


def f1_for_label(y_true: list[Any], y_pred: list[Any], label: Any) -> float | None:
    tp = sum(t == label and p == label for t, p in zip(y_true, y_pred, strict=True))
    fp = sum(t != label and p == label for t, p in zip(y_true, y_pred, strict=True))
    fn = sum(t == label and p != label for t, p in zip(y_true, y_pred, strict=True))
    return safe_div(2 * tp, 2 * tp + fp + fn)


def macro_f1(
    y_true: list[Any],
    y_pred: list[Any],
    labels: Iterable[Any] | None = None,
) -> float | None:
    selected = list(labels) if labels is not None else sorted(set(y_true), key=str)
    scores = [f1_for_label(y_true, y_pred, label) for label in selected]
    valid = [score for score in scores if score is not None]
    return safe_div(sum(valid), len(valid))


def accuracy(y_true: list[Any], y_pred: list[Any]) -> float | None:
    return safe_div(sum(t == p for t, p in zip(y_true, y_pred, strict=True)), len(y_true))


def source_id(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") or {}
    explicit = metadata.get("source_video_id")
    if explicit:
        return str(explicit)
    match = re.match(r"(video_\d+)", str(record.get("video_id", "")))
    return match.group(1) if match else "unknown"


def ground_truth(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") or {}
    value = metadata.get("ground_truth") or metadata.get("assistant_json")
    if not isinstance(value, dict):
        raise ValueError(f"record {record.get('video_id')} has no ground_truth dictionary")
    return value


def main() -> None:
    args = parse_args()
    records = [
        json.loads(line)
        for line in args.records.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    scored: list[dict[str, Any]] = []
    for record in records:
        parsed, parse_error = extract_json(record.get("raw_output"))
        gt = ground_truth(record)
        scored.append(
            {
                "sample_id": record.get("sample_id"),
                "video_id": record.get("video_id"),
                "source_video_id": source_id(record),
                "ground_truth": gt,
                "prediction": parsed,
                "parse_error": parse_error,
                "runtime_error": record.get("runtime_error"),
                "json_valid": parsed is not None,
                "schema_valid": schema_valid(parsed),
                "legal_combination_valid": legal_combination(parsed),
            }
        )

    gt_hf = [item["ground_truth"].get("has_fracture") for item in scored]
    pr_hf = [
        item["prediction"].get("has_fracture") if item["prediction"] else "__invalid__"
        for item in scored
    ]
    positive_indices = [index for index, value in enumerate(gt_hf) if value is True]
    valid_positive = [
        index for index in positive_indices if scored[index]["prediction"] is not None
    ]

    tp = sum(gt_hf[i] is True and pr_hf[i] is True for i in range(len(scored)))
    fp = sum(gt_hf[i] is not True and pr_hf[i] is True for i in range(len(scored)))
    fn = sum(gt_hf[i] is True and pr_hf[i] is not True for i in range(len(scored)))
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    binary_f1 = (
        safe_div(2 * precision * recall, precision + recall)
        if precision is not None and recall is not None
        else None
    )

    gt_type = [scored[i]["ground_truth"].get("type") for i in positive_indices]
    pr_type = [
        (scored[i]["prediction"] or {}).get("type", "__invalid__")
        for i in positive_indices
    ]
    gt_location = [scored[i]["ground_truth"].get("location") for i in positive_indices]
    pr_location = [
        (scored[i]["prediction"] or {}).get("location", "__invalid__")
        for i in positive_indices
    ]

    interval_exact = 0
    interval_pm1 = 0
    positive_joint = 0
    for index in positive_indices:
        gt = scored[index]["ground_truth"]
        pred = scored[index]["prediction"] or {}
        gt_interval = gt.get("fracture_between")
        pred_interval = pred.get("fracture_between")
        exact = pred_interval == gt_interval
        pm1 = (
            isinstance(gt_interval, list)
            and isinstance(pred_interval, list)
            and len(gt_interval) == len(pred_interval) == 2
            and abs(pred_interval[0] - gt_interval[0]) <= 1
            and abs(pred_interval[1] - gt_interval[1]) <= 1
        )
        interval_exact += exact
        interval_pm1 += pm1
        positive_joint += (
            pred.get("has_fracture") is True
            and exact
            and pred.get("type") == gt.get("type")
            and pred.get("location") == gt.get("location")
        )

    by_source: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(scored):
        by_source[item["source_video_id"]].append(index)
    source_f1: dict[str, float | None] = {}
    source_accuracy: dict[str, float | None] = {}
    for source, indices in sorted(by_source.items()):
        source_true = [gt_hf[index] for index in indices]
        source_pred = [pr_hf[index] for index in indices]
        labels = sorted(set(source_true), key=str)
        source_f1[source] = rounded(macro_f1(source_true, source_pred, labels))
        source_accuracy[source] = rounded(accuracy(source_true, source_pred))

    valid_source_f1 = [value for value in source_f1.values() if value is not None]
    source_macro = safe_div(sum(valid_source_f1), len(valid_source_f1))
    clip_macro = macro_f1(gt_hf, pr_hf, sorted(set(gt_hf), key=str))

    metrics = {
        "total_samples": len(scored),
        "source_count": len(by_source),
        "runtime_error_count": sum(bool(item["runtime_error"]) for item in scored),
        "json_valid_rate": rounded(
            safe_div(sum(item["json_valid"] for item in scored), len(scored))
        ),
        "schema_valid_rate": rounded(
            safe_div(sum(item["schema_valid"] for item in scored), len(scored))
        ),
        "legal_combination_rate": rounded(
            safe_div(sum(item["legal_combination_valid"] for item in scored), len(scored))
        ),
        "prediction_has_fracture_distribution": dict(Counter(map(str, pr_hf))),
        "has_fracture": {
            "accuracy": rounded(accuracy(gt_hf, pr_hf)),
            "precision": rounded(precision),
            "recall": rounded(recall),
            "f1": rounded(binary_f1),
            "clip_macro_f1": rounded(clip_macro),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        },
        "positive_only": {
            "sample_count": len(positive_indices),
            "valid_prediction_count": len(valid_positive),
            "type_macro_f1": rounded(macro_f1(gt_type, pr_type)),
            "type_accuracy": rounded(accuracy(gt_type, pr_type)),
            "location_accuracy": rounded(accuracy(gt_location, pr_location)),
            "interval_exact_rate": rounded(safe_div(interval_exact, len(positive_indices))),
            "interval_pm1_rate": rounded(safe_div(interval_pm1, len(positive_indices))),
            "joint_success_rate": rounded(safe_div(positive_joint, len(positive_indices))),
        },
        "source_level": {
            "definition": (
                "Per-source macro-F1 over labels present in that source, then unweighted "
                "mean across sources. Invalid outputs count as incorrect predictions."
            ),
            "source_macro_has_fracture_f1": rounded(source_macro),
            "clip_macro_has_fracture_f1": rounded(clip_macro),
            "source_macro_minus_clip_macro_pp": rounded(
                (source_macro - clip_macro) * 100
                if source_macro is not None and clip_macro is not None
                else None
            ),
            "per_source_f1": source_f1,
            "per_source_accuracy": source_accuracy,
        },
    }
    output = {
        "records_path": str(args.records.resolve()),
        "model_manifest": (
            json.loads(args.model_manifest.read_text(encoding="utf-8"))
            if args.model_manifest
            else None
        ),
        "metric_definitions": {
            "positive_only": "Metrics are conditioned on ground-truth has_fracture=true.",
            "interval_pm1": "Both predicted interval endpoints differ from ground truth by at most 1.",
            "positive_joint_success": "has_fracture, exact interval, type, and location all match.",
        },
        "metrics": metrics,
        "failures": [
            item
            for item in scored
            if item["runtime_error"]
            or not item["legal_combination_valid"]
            or item["prediction"] != item["ground_truth"]
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
