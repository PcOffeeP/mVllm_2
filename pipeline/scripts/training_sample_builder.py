#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
训练样本构建器（五字段契约）

将 ``data/07_metadata/subvideos_meta.json`` 中的子视频元数据转换为
LLaMA-Factory ShareGPT 格式的多模态训练样本，并按 ``data/05_splits/``
中的 video_id 集合分组输出到 ``data/06_merged/``。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


SUBVIDEOS_META_DEFAULT = _PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.json"
VIDEO_META_DEFAULT = _PROJECT_ROOT / "data" / "07_metadata" / "video_meta.json"
SPLITS_DIR_DEFAULT = _PROJECT_ROOT / "data" / "05_splits"
OUTPUT_DIR_DEFAULT = _PROJECT_ROOT / "data" / "06_merged"


FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
}

SPLIT_NAMES = [
    "fold_0_train",
    "fold_0_val",
    "fold_1_train",
    "fold_1_val",
    "fold_2_train",
    "fold_2_val",
    "test",
]


def load_json(path: Path) -> Any:
    """读取 JSON 文件。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    """写入 JSON 文件，必要时创建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)


def load_split_video_ids(splits_dir: Path) -> dict[str, set[str]]:
    """
    加载所有划分文件，返回 ``{split_name: set(video_id), ...}``。

    仅识别 ``fold_*_{train,val}.json`` 与 ``test.json``。
    """
    mapping: dict[str, set[str]] = {}
    for path in sorted(splits_dir.glob("*.json")):
        if path.stem not in SPLIT_NAMES:
            continue
        data = load_json(path)
        mapping[path.stem] = set(data.get("video_ids", []))
    return {name: mapping.get(name, set()) for name in SPLIT_NAMES}


def _normalize_video_path(video_path: str) -> str:
    """规范化视频路径。

    - 以 ``data/`` 开头的相对路径保持原样。
    - 绝对路径（以 ``/`` 开头）保持原样。
    - 其它相对路径视为 ``data/`` 下的子目录，补全 ``data/`` 前缀。
    """
    if not isinstance(video_path, str):
        return video_path
    if video_path.startswith("data/") or video_path.startswith("/"):
        return video_path
    return f"data/{video_path}"


def _normalize_subvideo_labels(sub: dict[str, Any]) -> dict[str, Any]:
    """治理标签冲突：优先使用上游子视频元数据中的 canonical 字段。

    - 若子视频元数据已包含 ``has_fracture_canonical`` / ``location_canonical``，
      直接沿用，保证 CSV 原始标签不被覆盖。
    - 保证 ``has_fracture_canonical=True`` 时 ``type`` 在 7 个断裂类中或视频异常时间不可靠。
    """
    sub = dict(sub)
    ftype = sub.get("type", "")
    source_type = sub.get("source_type", ftype)
    source_location = sub.get("source_location")
    is_abnormal = sub.get("is_abnormal", False)

    has_fracture_canonical = sub.get("has_fracture_canonical")
    canonical_explicitly_null = "has_fracture_canonical" in sub and sub["has_fracture_canonical"] is None
    if has_fracture_canonical is None and not canonical_explicitly_null:
        has_fracture_canonical = sub.get("has_fracture", False)
        if is_abnormal or ftype not in FRACTURE_TYPES:
            has_fracture_canonical = False

    # 视频异常保留原 type；断裂样本仅保留有效位置
    if has_fracture_canonical is True:
        if ftype in FRACTURE_TYPES:
            location = sub.get("location_canonical") or sub.get("location")
            if location not in ("inside_gauge", "outside_gauge"):
                location = None
            fracture_between = sub.get("fracture_between")
        elif ftype == "视频异常":
            location = None
            fracture_between = None
        else:
            # 不一致：降级为负样本
            has_fracture_canonical = False
            location = None
            fracture_between = None
    else:
        location = None
        fracture_between = None

    sub["has_fracture"] = has_fracture_canonical
    sub["has_fracture_canonical"] = has_fracture_canonical
    sub["fracture_between"] = fracture_between
    sub["location"] = location
    sub["location_canonical"] = location
    sub["source_type"] = source_type
    sub["source_location"] = source_location

    return sub


def compute_effective_frames(sub: dict[str, Any]) -> int:
    """Read actual processor frame count; never derive it from duration/FPS."""
    mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []
    if not mapping:
        raise ValueError("missing actual processor frame mapping")
    if len(mapping) > 8:
        raise ValueError("actual processor frame count violates max_frames=8")
    return len(mapping)


def build_assistant_content(sub: dict[str, Any]) -> str:
    """构造 assistant 输出的 JSON 字符串，严格五字段。"""
    has_fracture = sub["has_fracture_canonical"]
    output: dict[str, Any] = {
        "has_fracture": has_fracture,
        "fracture_between": sub.get("fracture_between") if has_fracture is True else None,
        "type": sub["type"],
        "location": sub["location_canonical"],
        "confidence": 1.0,
    }
    return json.dumps(output, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _build_actual_frame_mapping(sub: dict[str, Any]) -> list[dict[str, Any]]:
    """构建 actual_frame_mapping；优先使用子视频元数据中的 actual_frame_mapping。"""
    mapping = sub.get("actual_frame_mapping")
    if mapping is not None:
        return [
            {
                "input_index": frame.get("input_index"),
                "original_frame": frame.get("original_frame"),
                "timestamp": frame.get("timestamp"),
            }
            for frame in mapping
        ]
    sampled = sub.get("sampled_frames") or []
    return [
        {
            "input_index": frame.get("input_index"),
            "original_frame": frame.get("original_frame"),
            "timestamp": frame.get("timestamp"),
        }
        for frame in sampled
    ]


def convert_subvideo_to_sample(
    sub: dict[str, Any],
) -> dict[str, Any]:
    """将单条子视频元数据转换为 ShareGPT 训练样本。"""
    sub = _normalize_subvideo_labels(sub)
    processor_fingerprint = sub.get("processor_fingerprint")
    if not isinstance(processor_fingerprint, str) or not processor_fingerprint.strip():
        raise ValueError(f"{sub.get('subvideo_id')}: missing processor_fingerprint")
    lowered_fingerprint = processor_fingerprint.lower()
    if "mock" in lowered_fingerprint or "theoretical" in lowered_fingerprint:
        raise ValueError(
            f"{sub.get('subvideo_id')}: diagnostic processor fingerprint is forbidden"
        )
    start_time = sub.get("start_time", 0.0)
    end_time = sub.get("end_time", 0.0)
    effective_frames = compute_effective_frames(sub)

    user_content = (
        "<video>\n请分析这段拉伸试验视频，判断是否存在断裂。"
        "视频将被处理为最多 8 帧，请判断断裂发生在哪两帧之间。"
        "按 JSON 格式输出：has_fracture、fracture_between、type、location、confidence。"
    )
    assistant_content = build_assistant_content(sub)

    sample: dict[str, Any] = {
        "id": sub["subvideo_id"],
        "videos": [_normalize_video_path(sub["video_path"])],
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ],
        "has_fracture": sub["has_fracture_canonical"],
        "has_fracture_canonical": sub["has_fracture_canonical"],
        "fracture_between": sub.get("fracture_between"),
        "type": sub["type"],
        "location": sub["location_canonical"],
        "location_canonical": sub["location_canonical"],
        "source_type": sub.get("source_type", sub["type"]),
        "source_location": sub.get("source_location", sub["location"]),
        "source_video": sub["source_video"],
        "start_frame": sub.get("start_frame"),
        "end_frame": sub.get("end_frame"),
        "actual_frame_mapping": _build_actual_frame_mapping(sub),
        "processor_fingerprint": processor_fingerprint,
        "selection_reason": sub.get("selection_reason"),
        "exclusion_reason": sub.get("exclusion_reason"),
    }
    return sample


def _sample_with_priority(
    items: list[dict[str, Any]], target: int, seed: int
) -> list[dict[str, Any]]:
    """优先保留全时长样本，再从片段中随机采样至目标数量。"""
    import random

    random.seed(seed)
    if target >= len(items):
        return items
    full = [it for it in items if str(it.get("id", "")).endswith("_full")]
    other = [it for it in items if not str(it.get("id", "")).endswith("_full")]
    need = max(0, target - len(full))
    selected_other = []
    if need > 0 and other:
        selected_other = random.sample(other, min(need, len(other)))
    if len(full) > target:
        return random.sample(full, target)
    return full + selected_other


def _balance_train_samples(
    samples: list[dict[str, Any]],
    seed: int = 42,
) -> list[dict[str, Any]]:
    """训练集正负样本平衡：正:负处于 1:1 ~ 2:1。"""

    def _is_pos(s: dict[str, Any]) -> bool:
        hf = s.get("has_fracture_canonical", s["has_fracture"])
        return hf is True and s.get("type") in FRACTURE_TYPES

    pos = [s for s in samples if _is_pos(s)]
    neg = [s for s in samples if not _is_pos(s)]
    pos_n = len(pos)
    neg_n = len(neg)
    if pos_n == 0:
        return samples
    if neg_n == 0:
        return pos

    target_pos = min(pos_n, 2 * neg_n)
    target_neg = min(neg_n, target_pos)

    selected_pos = _sample_with_priority(pos, target_pos, seed)
    selected_neg = _sample_with_priority(neg, target_neg, seed)
    return selected_pos + selected_neg


def build_split_samples(
    subvideos: list[dict[str, Any]],
    split_video_ids: dict[str, set[str]],
    seed: int = 42,
) -> dict[str, list[dict[str, Any]]]:
    """按当前划分将子视频分组并转换为训练样本（训练集做正负平衡，验证集保持完整）。"""
    by_split: dict[str, list[dict[str, Any]]] = {
        name: [] for name in split_video_ids if name != "test"
    }
    for sub in subvideos:
        src = sub["source_video"]
        selected_splits = set(sub.get("selected_splits", []))
        for name, ids in split_video_ids.items():
            if name == "test":
                continue
            if src not in ids:
                continue
            if selected_splits and name not in selected_splits:
                continue
            by_split[name].append(
                convert_subvideo_to_sample(sub)
            )

    for name in by_split:
        if name.endswith("_train"):
            by_split[name] = _balance_train_samples(by_split[name], seed=seed)
    return by_split


def _counter_to_dict(counter: Counter[Any], top_k: int | None = None) -> dict[str, int]:
    """将 Counter 转为可 JSON 序列化的字典，可选只保留 Top-K。"""
    items = counter.most_common(top_k) if top_k else counter.most_common()
    return {str(k): int(v) for k, v in items}


def compute_samples_meta(
    split_samples: dict[str, list[dict[str, Any]]],
    split_video_ids: dict[str, set[str]],
) -> dict[str, Any]:
    """汇总每个 fold 的样本数、正负样本分布、视频来源分布等统计信息。"""
    split_meta: dict[str, Any] = {}
    total_pos = 0
    total_neg = 0

    for name, samples in split_samples.items():
        pos = sum(
            1 for s in samples
            if s.get("has_fracture_canonical", s["has_fracture"]) is True and s["type"] in FRACTURE_TYPES
        )
        neg = len(samples) - pos
        total_pos += pos
        total_neg += neg

        source_dist = Counter(s["source_video"] for s in samples)
        type_dist = Counter(s["type"] for s in samples)
        source_type_dist = Counter(s["source_type"] for s in samples)

        pos_ratio = round(pos / len(samples), 4) if samples else 0.0
        neg_ratio = round(neg / len(samples), 4) if samples else 0.0
        split_meta[name] = {
            "sample_count": len(samples),
            "video_source_count": len(source_dist),
            "positive_samples": pos,
            "negative_samples": neg,
            "positive_ratio": pos_ratio,
            "negative_ratio": neg_ratio,
            "source_distribution": _counter_to_dict(source_dist, top_k=20),
            "type_distribution": _counter_to_dict(type_dist),
            "source_type_distribution": _counter_to_dict(source_type_dist),
        }

    all_source_ids = set()
    for samples in split_samples.values():
        all_source_ids.update(s["source_video"] for s in samples)

    return {
        "total_samples": total_pos + total_neg,
        "total_video_sources": len(all_source_ids),
        "total_positive": total_pos,
        "total_negative": total_neg,
        "splits": split_meta,
        "split_video_counts": {
            name: len(ids) for name, ids in split_video_ids.items()
        },
    }


def _build_test_artifacts(
    video_meta: list[dict[str, Any]],
    test_video_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """构造测试输入清单与真值 JSON。"""
    by_id = {r["video_id"]: r for r in video_meta}
    inputs: list[dict[str, Any]] = []
    ground_truth: list[dict[str, Any]] = []
    for vid in sorted(test_video_ids):
        rec = by_id.get(vid, {})
        video_path = _normalize_video_path(
            rec.get("video_path") or f"data/01_videos/{vid}.mp4"
        )
        inputs.append(
            {
                "id": vid,
                "video_id": vid,
                "video_path": video_path,
            }
        )
        ground_truth.append(
            {
                "video_id": vid,
                "has_fracture": rec.get("has_fracture"),
                "has_fracture_canonical": rec.get("has_fracture_canonical"),
                "is_abnormal": rec.get("is_abnormal"),
                "is_abnormal_canonical": rec.get("is_abnormal_canonical"),
                "video_anomaly_kind": rec.get("video_anomaly_kind"),
                "event_time_reliable": rec.get("event_time_reliable"),
                "event_frame_original": rec.get("event_frame_original"),
                "event_time": rec.get("event_time"),
                "type": rec.get("type"),
                "location": rec.get("location"),
                "location_canonical": rec.get("location_canonical"),
            }
        )
    return inputs, ground_truth


def build_all(
    subvideos_meta: Path,
    splits_dir: Path,
    output_dir: Path,
    video_meta_path: Path | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """核心构建入口：读取元数据、分组、写文件、返回统计信息。"""
    if not subvideos_meta.exists():
        raise FileNotFoundError(f"子视频元数据不存在: {subvideos_meta}")
    if not splits_dir.exists():
        raise FileNotFoundError(f"划分目录不存在: {splits_dir}")

    print(f"读取子视频元数据: {subvideos_meta}")
    raw_subvideos = load_json(subvideos_meta)
    if isinstance(raw_subvideos, dict):
        subvideos = raw_subvideos.get("subvideos", [])
    else:
        subvideos = raw_subvideos
    print(f"共 {len(subvideos)} 个子视频")

    print(f"加载划分文件: {splits_dir}")
    split_video_ids = load_split_video_ids(splits_dir)
    for name, ids in split_video_ids.items():
        print(f"  {name}: {len(ids)} 个原始视频")

    print("构建训练样本...")
    split_samples = build_split_samples(subvideos, split_video_ids, seed=seed)

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, samples in split_samples.items():
        out_path = output_dir / f"{name}.json"
        clean_samples = [
            {k: v for k, v in s.items() if k in ("messages", "videos")}
            for s in samples
        ]
        write_json(out_path, clean_samples)
        print(f"写入: {out_path} ({len(samples)} 条样本)")

    test_ids = split_video_ids.get("test", set())
    if test_ids:
        vm_path = video_meta_path or VIDEO_META_DEFAULT
        if vm_path.exists():
            video_meta = load_json(vm_path)
            test_inputs, test_ground_truth = _build_test_artifacts(video_meta, test_ids)
            write_json(output_dir / "test_inputs.json", test_inputs)
            write_json(output_dir / "test_ground_truth.json", test_ground_truth)
            print(
                f"写入测试清单: {output_dir / 'test_inputs.json'} "
                f"({len(test_inputs)} 条), "
                f"真值: {output_dir / 'test_ground_truth.json'}"
            )
        else:
            print(f"警告：未找到 video_meta，跳过测试清单生成: {vm_path}")

    print("汇总样本统计信息...")
    samples_meta = compute_samples_meta(split_samples, split_video_ids)
    meta_path = output_dir / "samples_meta.json"
    write_json(meta_path, samples_meta)
    print(f"写入: {meta_path}")
    print("完成。")
    return samples_meta


def main() -> None:
    parser = argparse.ArgumentParser(description="五字段契约训练样本构建器")
    parser.add_argument(
        "--subvideos-meta", type=Path, default=SUBVIDEOS_META_DEFAULT
    )
    parser.add_argument("--video-meta", type=Path, default=VIDEO_META_DEFAULT)
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    build_all(
        subvideos_meta=args.subvideos_meta,
        splits_dir=args.splits_dir,
        output_dir=args.output_dir,
        video_meta_path=args.video_meta,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
