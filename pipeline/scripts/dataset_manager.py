#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型微调数据管道：数据集管理器（新 interval 方案）

功能：
1. 读取 CSV 标注，提取 event_frame_original、location、type 等字段。
2. 使用 ffprobe 提取每个视频的 fps、总帧数、时长，输出 video_meta.json。
3. 0-based 帧号校验：抽样核对 event_frame_original，输出 frame_index_validation.json。
4. 按 type + location 分层划分：留出 20% test，训练集内 3-fold，输出 split JSON。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CSV_PATH_DEFAULT = PROJECT_ROOT / "data" / "02_annotations" / "all_videos_tag.csv"
VIDEO_DIR_DEFAULT = PROJECT_ROOT / "data" / "01_videos"
METADATA_DIR_DEFAULT = PROJECT_ROOT / "data" / "metadata"
SPLITS_DIR_DEFAULT = PROJECT_ROOT / "data" / "03_splits"

FRACTURE_TYPES = [
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
]

NON_FRACTURE_TYPES = ["未断裂", "未夹紧", "视频异常"]


def _ffprobe(video_path: Path) -> dict[str, Any]:
    """使用 ffprobe 提取视频元信息，失败时返回空字典。"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,nb_frames,duration",
        "-of", "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=60
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        stream = (data.get("streams") or [{}])[0]
        fps = _parse_frame_rate(stream.get("r_frame_rate", ""))
        duration = _to_float(stream.get("duration"))
        nb_frames = _to_int(stream.get("nb_frames"))
        if nb_frames is None and duration and fps:
            nb_frames = int(round(duration * fps))
        return {"fps": fps, "duration": duration, "total_frames": nb_frames}
    except Exception:
        return {}


def _parse_frame_rate(value: str) -> float | None:
    if not value:
        return None
    value = value.strip()
    result = None
    if "/" in value:
        try:
            num, den = value.split("/")
            result = float(num) / float(den)
        except Exception:
            return None
    else:
        try:
            result = float(value)
        except Exception:
            return None
    return result if math.isfinite(result) else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except Exception:
        return None
    return result if math.isfinite(result) else None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def _parse_event_time(raw: Any) -> float | str | None:
    """CSV 断裂时间点：可解析为数字时返回秒数，否则保留原字符串或 null。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"nan", "nat"}:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return text


def _parse_event_frame(raw: Any) -> int | None:
    """CSV 断裂帧数：可解析为整数时返回，否则 null。"""
    return _to_int(raw)


def _parse_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if pd.isna(raw):
        return False
    text = str(raw).strip().lower()
    return text in {"true", "1", "yes", "是"}


def _clean_location(raw: Any) -> str | None:
    """CSV 原始 location：保留空值/缺失为 'N/A'，与 CSV 口径一致。"""
    if raw is None or pd.isna(raw):
        return "N/A"
    text = str(raw).strip()
    if text.lower() in {"nan", "nat", ""}:
        return "N/A"
    return text


def _clean_type(raw: Any) -> str:
    if raw is None or pd.isna(raw):
        return "未知"
    return str(raw).strip()


def load_annotations(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    required = {"id", "video_path", "断裂模式", "断裂位置", "断裂帧数", "has_fracture", "is_abnormal"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV 缺少必要列: {missing}")
    return df


def build_video_meta(
    df: pd.DataFrame,
    video_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """构建 video_meta 列表并返回警告信息。"""
    records = []
    warnings: list[str] = []

    for _, row in df.iterrows():
        video_id = str(row["id"]).strip()
        csv_path_str = str(row["video_path"]).strip() if not pd.isna(row["video_path"]) else f"data/01_videos/{video_id}.mp4"
        video_path = video_dir / f"{video_id}.mp4"

        ffprobe_info = _ffprobe(video_path) if video_path.exists() else {}
        if not ffprobe_info:
            warnings.append(f"{video_id}: ffprobe 失败或视频缺失，使用 CSV 值")

        fps = ffprobe_info.get("fps") or _to_float(row.get("视频帧率")) or 30.0
        duration = ffprobe_info.get("duration") or _to_float(row.get("视频时长"))
        total_frames = ffprobe_info.get("total_frames") or _to_int(row.get("视频总帧数"))
        if duration is None and total_frames is not None and fps is not None:
            duration = total_frames / fps
        if total_frames is None and duration is not None and fps is not None:
            total_frames = int(round(duration * fps))
        if duration is None:
            duration = 0.0

        event_time = _parse_event_time(row.get("断裂时间点"))
        event_frame_original = _parse_event_frame(row.get("断裂帧数"))
        fracture_type = _clean_type(row.get("断裂模式"))
        location = _clean_location(row.get("断裂位置"))
        has_fracture = _parse_bool(row.get("has_fracture"))
        is_abnormal = _parse_bool(row.get("is_abnormal"))
        material_type = str(row.get("材料类型", "")).strip() if not pd.isna(row.get("材料类型")) else "其他"
        resolution = str(row.get("清晰度", "")).strip() if not pd.isna(row.get("清晰度")) else "未知"

        # 治理异常/正样本冲突：CSV 原始字段只读，写入派生 canonical 字段供下游使用
        has_fracture_canonical = has_fracture
        location_canonical = location
        is_label_conflict = False
        governance_reasons: list[str] = []

        if is_abnormal:
            if has_fracture:
                reason = (
                    f"{video_id}: is_abnormal=True 但 has_fracture=True，"
                    "按设计文档降级为 has_fracture_canonical=False"
                )
                warnings.append(reason)
                governance_reasons.append(reason)
                has_fracture_canonical = False
                is_label_conflict = True
            if location != "N/A":
                reason = (
                    f"{video_id}: is_abnormal=True，location 强制设为 location_canonical=None"
                )
                warnings.append(reason)
                governance_reasons.append(reason)
                location_canonical = None
                is_label_conflict = True
        elif has_fracture and fracture_type not in FRACTURE_TYPES:
            reason = (
                f"{video_id}: has_fracture=True 但 type={fracture_type} 不在 7 个断裂类中，"
                "降级为 has_fracture_canonical=False"
            )
            warnings.append(reason)
            governance_reasons.append(reason)
            has_fracture_canonical = False
            is_label_conflict = True

        # 一致性校验：has_fracture=true 但 type 为非断裂类（CSV 原值保留，仅记录冲突）
        if has_fracture and fracture_type in NON_FRACTURE_TYPES:
            reason = (
                f"{video_id}: has_fracture=True 但 type={fracture_type}，"
                "标记为数据一致性错误"
            )
            warnings.append(reason)
            governance_reasons.append(reason)
            is_label_conflict = True

        # 非断裂/异常样本的 canonical location 统一为 null；断裂样本只保留有效位置
        if has_fracture_canonical:
            if location in ("inside_gauge", "outside_gauge"):
                location_canonical = location
            else:
                location_canonical = None
        else:
            location_canonical = None

        record = {
            "video_id": video_id,
            "video_path": csv_path_str,
            "fps": fps,
            "total_frames": total_frames,
            "duration": duration,
            "event_time": event_time,
            "event_frame_original": event_frame_original,
            "type": fracture_type,
            "location": location,
            "material_type": material_type,
            "resolution": resolution,
            "has_fracture": has_fracture,
            "is_abnormal": is_abnormal,
            "has_fracture_canonical": has_fracture_canonical,
            "location_canonical": location_canonical,
            "is_label_conflict": is_label_conflict,
            "label_governance_reason": governance_reasons,
        }
        records.append(record)

    return records, warnings


def _compute_strata(
    records: list[dict[str, Any]],
) -> tuple[dict[str, str], str]:
    """为每个 video_id 计算仅用于划分的 strata key，并在过于稀疏时降级。

    返回 (video_id -> strata key, decision)，其中 decision 用于记录当前采用的
    分层策略："type_location_rare_merged" 或 "type_only"。
    """
    raw_counts: Counter[str] = Counter()
    raw_keys: dict[str, str] = {}

    for rec in records:
        loc = rec.get("location_canonical", rec["location"])
        ftype = rec["type"]
        if loc is None or loc == "N/A":
            key = "N/A"
        else:
            key = f"{ftype}@@{loc}"
        raw_keys[rec["video_id"]] = key
        raw_counts[key] += 1

    # 合并稀有 type+location 组合
    merged_counts: Counter[str] = Counter()
    merged_keys: dict[str, str] = {}
    for rec in records:
        key = raw_keys[rec["video_id"]]
        if key != "N/A" and raw_counts[key] <= 2:
            loc = rec.get("location_canonical", rec["location"])
            key = f"rare_fracture@@{loc}"
        merged_keys[rec["video_id"]] = key
        merged_counts[key] += 1

    # 若合并后仍存在非 N/A 层样本数 <=2，降级为仅按 type 分层
    needs_fallback = any(
        count <= 2 and key != "N/A" for key, count in merged_counts.items()
    )
    if needs_fallback:
        final_keys: dict[str, str] = {}
        for rec in records:
            if rec.get("location_canonical", rec["location"]) in (None, "N/A"):
                final_keys[rec["video_id"]] = "N/A"
            else:
                final_keys[rec["video_id"]] = rec["type"]
        return final_keys, "type_only"

    return merged_keys, "type_location_rare_merged"


def _is_canonical_fracture(rec: dict[str, Any]) -> bool:
    """判断记录是否属于可用于训练的确认断裂样本。"""
    if rec.get("is_abnormal"):
        return False
    if not rec.get("has_fracture_canonical", rec.get("has_fracture", False)):
        return False
    return rec.get("type") in FRACTURE_TYPES


def compute_rare_pool(records: list[dict[str, Any]]) -> list[str]:
    """识别稀有断裂类别（视频数 <=2）并返回其 video_id 列表。"""
    type_counts: Counter[str] = Counter()
    type_ids: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        if _is_canonical_fracture(rec):
            ftype = rec["type"]
            type_counts[ftype] += 1
            type_ids[ftype].append(rec["video_id"])

    rare_pool: list[str] = []
    for ftype, count in type_counts.items():
        if count <= 2:
            rare_pool.extend(type_ids[ftype])
    return sorted(rare_pool)


def stratified_split(
    records: list[dict[str, Any]],
    test_ratio: float = 0.2,
    n_folds: int = 3,
    seed: int = 42,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """
    确定性视频级划分：
    1. 稀有断裂类别（<=2 视频）强制加入每个 fold 的训练集，不进验证/测试。
    2. 剩余视频按约 test_ratio 划出冻结测试集。
    3. 剩余视频做 n_folds 分层划分；每个 fold 训练集 = 其他 folds + 稀有池。
    同一原视频只会出现在一个集合中。
    返回 (split_map, decision_log)。
    """
    import random

    random.seed(seed)

    rare_pool = compute_rare_pool(records)
    rare_set = set(rare_pool)
    remaining_records = [r for r in records if r["video_id"] not in rare_set]

    # 对非稀有视频按 type 分层划分测试集与 fold
    strata, decision = _compute_strata(remaining_records)
    strata_groups: dict[str, list[str]] = defaultdict(list)
    for rec in remaining_records:
        strata_groups[strata[rec["video_id"]]].append(rec["video_id"])

    test_ids: list[str] = []
    pool_ids: list[str] = []

    for stratum, ids in strata_groups.items():
        ids = ids.copy()
        random.shuffle(ids)
        n_test = max(1, int(round(len(ids) * test_ratio))) if len(ids) >= 2 else 0
        # 保证剩余样本至少能分 n_folds 份
        while len(ids) - n_test < n_folds and n_test > 0:
            n_test -= 1
        test_ids.extend(ids[:n_test])
        pool_ids.extend(ids[n_test:])

    # 对非测试、非稀有视频再按 strata 分 fold
    pool_records = [r for r in records if r["video_id"] in set(pool_ids)]
    pool_strata, pool_decision = _compute_strata(pool_records)
    rem_groups: dict[str, list[str]] = defaultdict(list)
    for rec in pool_records:
        rem_groups[pool_strata[rec["video_id"]]].append(rec["video_id"])

    folds: list[list[str]] = [[] for _ in range(n_folds)]
    for stratum, ids in rem_groups.items():
        ids = ids.copy()
        random.shuffle(ids)
        chunk_size = math.ceil(len(ids) / n_folds)
        for i in range(n_folds):
            folds[i].extend(ids[i * chunk_size : (i + 1) * chunk_size])

    result: dict[str, list[str]] = {"test": sorted(test_ids)}
    for i in range(n_folds):
        val_ids = folds[i]
        train_ids: list[str] = []
        for j in range(n_folds):
            if j != i:
                train_ids.extend(folds[j])
        # 稀有池强制加入每个 fold 训练集
        train_ids.extend(rare_pool)
        result[f"fold_{i}_train"] = sorted(set(train_ids))
        result[f"fold_{i}_val"] = sorted(val_ids)

    decision_log: dict[str, Any] = {
        "method": "stratified_split_with_rare_pool",
        "test_ratio": test_ratio,
        "n_folds": n_folds,
        "seed": seed,
        "rare_pool": rare_pool,
        "rare_pool_size": len(rare_pool),
        "overall_strata_decision": decision,
        "overall_strata_counts": dict(Counter(strata.values()).most_common()),
        "pool_strata_decision": pool_decision,
        "pool_strata_counts": dict(Counter(pool_strata.values()).most_common()),
    }
    return result, decision_log


def build_inventory_report(
    records: list[dict[str, Any]],
    splits: dict[str, list[str]],
    decision_log: dict[str, Any],
) -> dict[str, Any]:
    """生成权威库存报告，覆盖 110 个视频、canonical 分组、稀有池与划分统计。"""
    categories: dict[str, list[str]] = {
        "confirmed_fracture": [],
        "confirmed_no_fracture": [],
        "not_clamped": [],
        "video_anomaly": [],
    }
    location_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()

    for rec in records:
        vid = rec["video_id"]
        ftype = rec["type"]
        is_canonical = _is_canonical_fracture(rec)

        type_counts[ftype] += 1
        loc = rec.get("location_canonical") or rec.get("location")
        if loc:
            location_counts[loc] += 1

        if is_canonical:
            categories["confirmed_fracture"].append(vid)
        elif ftype == "未夹紧":
            categories["not_clamped"].append(vid)
        elif ftype == "视频异常" or rec.get("is_abnormal"):
            categories["video_anomaly"].append(vid)
        else:
            categories["confirmed_no_fracture"].append(vid)

    split_counts = {name: len(ids) for name, ids in splits.items()}
    split_type_distribution: dict[str, dict[str, int]] = {}
    by_id = {r["video_id"]: r for r in records}
    for name, ids in splits.items():
        split_type_distribution[name] = dict(
            Counter(by_id[vid]["type"] for vid in ids if vid in by_id).most_common()
        )

    return {
        "total_videos": len(records),
        "categories": {k: sorted(v) for k, v in categories.items()},
        "category_counts": {k: len(v) for k, v in categories.items()},
        "type_counts": dict(type_counts.most_common()),
        "location_counts": dict(location_counts.most_common()),
        "rare_pool": decision_log.get("rare_pool", []),
        "splits": split_counts,
        "split_type_distribution": split_type_distribution,
        "decision_log": decision_log,
    }


def validate_frames(
    records: list[dict[str, Any]],
    video_dir: Path,
    n_samples: int = 8,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """
    0-based 帧号校验：抽样有 event_frame_original 的视频，交叉核对时间/帧号一致性。
    返回校验记录列表，包含修正偏移量建议（目前默认 0）。
    """
    import random

    candidates = [r for r in records if r["event_frame_original"] is not None]
    if not candidates:
        return []

    random.seed(seed)
    samples = candidates if len(candidates) <= n_samples else random.sample(candidates, n_samples)
    validations = []

    for rec in samples:
        video_id = rec["video_id"]
        fps = rec["fps"]
        total_frames = rec["total_frames"]
        duration = rec["duration"]
        event_frame = rec["event_frame_original"]
        event_time = rec["event_time"]

        video_path = video_dir / f"{video_id}.mp4"
        extracted_path: str | None = None
        if video_path.exists():
            out_dir = METADATA_DIR_DEFAULT / "validation_frames"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = event_frame / fps if fps else 0.0
            extracted_path = str(out_dir / f"{video_id}_frame_{event_frame:06d}.jpg")
            _extract_frame(video_path, ts, Path(extracted_path))

        # 交叉校验：event_time 与 event_frame / fps 的差异
        time_diff: float | None = None
        if isinstance(event_time, (int, float)) and fps:
            time_diff = abs(event_time - event_frame / fps)

        # 边界检查
        in_bounds = True
        if total_frames is not None:
            in_bounds = 0 <= event_frame < total_frames

        # 默认 0-based 结论：CSV 权威，仅当时间差异 >1s 或越界时提示
        conclusion = "0-based"
        suggested_offset = 0
        if not in_bounds:
            conclusion = "out_of_bounds"
        elif time_diff is not None and time_diff > 1.0:
            conclusion = "time_mismatch"

        validations.append(
            {
                "video_id": video_id,
                "event_frame_original": event_frame,
                "event_time_csv": event_time,
                "fps": fps,
                "total_frames": total_frames,
                "duration": duration,
                "validation_method": "ffprobe_duration_crosscheck" if video_path.exists() else "csv_only",
                "extracted_frame_path": extracted_path,
                "time_diff_seconds": time_diff,
                "in_bounds": in_bounds,
                "conclusion": conclusion,
                "suggested_offset": suggested_offset,
            }
        )

    return validations


def _extract_frame(video_path: Path, timestamp: float, output_path: Path) -> None:
    """使用 ffmpeg 抽取单帧图片。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    subprocess.run(cmd, capture_output=True, check=False)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description="新 interval 方案数据集管理器")
    parser.add_argument("--csv", type=Path, default=CSV_PATH_DEFAULT)
    parser.add_argument("--video-dir", type=Path, default=VIDEO_DIR_DEFAULT)
    parser.add_argument("--metadata-dir", type=Path, default=METADATA_DIR_DEFAULT)
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR_DEFAULT)
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument("--n-folds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--validation-samples", type=int, default=8)
    args = parser.parse_args()

    if not args.csv.exists():
        raise FileNotFoundError(f"CSV 不存在: {args.csv}")

    print(f"读取标注: {args.csv}")
    df = load_annotations(args.csv)
    print(f"共 {len(df)} 条标注")

    print("提取视频元信息...")
    records, warnings = build_video_meta(df, args.video_dir)
    for w in warnings:
        print(f"  警告: {w}")

    video_meta_path = args.metadata_dir / "video_meta.json"
    write_json(video_meta_path, records)
    print(f"写入: {video_meta_path} ({len(records)} 条)")

    print("0-based 帧号校验...")
    validations = validate_frames(records, args.video_dir, n_samples=args.validation_samples, seed=args.seed)
    validation_path = args.metadata_dir / "frame_index_validation.json"
    write_json(validation_path, validations)
    print(f"写入: {validation_path} ({len(validations)} 条抽样)")

    print(
        f"分层划分: test_ratio={args.test_ratio}, n_folds={args.n_folds}, seed={args.seed}"
    )
    splits, decision_log = stratified_split(
        records, test_ratio=args.test_ratio, n_folds=args.n_folds, seed=args.seed
    )

    args.splits_dir.mkdir(parents=True, exist_ok=True)
    for name, ids in splits.items():
        split_path = args.splits_dir / f"{name}.json"
        split_label = "test"
        if name.startswith("fold_"):
            split_label = "val" if name.endswith("_val") else "train"
        data = {
            "split": split_label,
            "video_ids": ids,
            "count": len(ids),
            "method": "stratified_type_location_with_rare_pool",
            "test_ratio": args.test_ratio if "test" in name else None,
            "fold": int(name.split("_")[1]) if name.startswith("fold_") else None,
            "rare_pool_included": name.startswith("fold_") and name.endswith("_train"),
            "strata_decision": decision_log.get("overall_strata_decision"),
        }
        write_json(split_path, data)
        print(f"写入: {split_path} ({len(ids)} 条)")

    decision_path = args.metadata_dir / "stratified_split_decision_log.json"
    write_json(decision_path, decision_log)
    print(f"写入分层决策日志: {decision_path}")

    print("生成库存报告...")
    inventory_report = build_inventory_report(records, splits, decision_log)
    inventory_path = args.metadata_dir / "inventory_report.json"
    write_json(inventory_path, inventory_report)
    print(f"写入库存报告: {inventory_path}")

    print("完成。")


if __name__ == "__main__":
    main()
