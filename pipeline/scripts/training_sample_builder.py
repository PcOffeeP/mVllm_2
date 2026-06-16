#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
训练样本构建器（新 interval 方案）

将 ``data/metadata/subvideos_meta.json`` 中的子视频元数据转换为
LLaMA-Factory ShareGPT 格式的多模态训练样本，并按 ``data/03_splits/``
中的 video_id 集合分组输出到 ``data/04_new_merged/``。
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

# 允许从项目根目录之外直接运行时导入 agent.prompts
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from agent.prompts import SYSTEM_PROMPT, build_user_prompt
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "无法导入 agent.prompts，请确保从项目根目录运行或 PYTHONPATH 包含项目根目录"
    ) from exc


SUBVIDEOS_META_DEFAULT = _PROJECT_ROOT / "data" / "metadata" / "subvideos_meta.json"
SPLITS_DIR_DEFAULT = _PROJECT_ROOT / "data" / "03_splits"
OUTPUT_DIR_DEFAULT = _PROJECT_ROOT / "data" / "04_new_merged"

VIDEO_FPS = 8.0
VIDEO_MAXLEN = 36

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
    # 保证输出顺序稳定
    return {name: mapping.get(name, set()) for name in SPLIT_NAMES}


def _normalize_subvideo_labels(sub: dict[str, Any]) -> dict[str, Any]:
    """治理标签冲突：优先使用上游子视频元数据中的 canonical 字段。

    - 若子视频元数据已包含 ``has_fracture_canonical`` / ``location_canonical``，
      直接沿用，保证 CSV 原始标签不被覆盖。
    - 否则按 ``is_abnormal`` / ``type`` 推导 canonical 值。
    - 保证 ``has_fracture_canonical=True`` 时 ``type`` 在 7 个断裂类中。
    """
    sub = dict(sub)
    ftype = sub.get("type", "")
    is_abnormal = sub.get("is_abnormal", False)

    if "has_fracture_canonical" in sub:
        has_fracture = bool(sub["has_fracture_canonical"])
    else:
        has_fracture = sub.get("has_fracture", False)
        if is_abnormal or ftype not in FRACTURE_TYPES:
            has_fracture = False

    if "location_canonical" in sub:
        location = sub["location_canonical"]
    else:
        location = sub.get("location", "N/A")
        if is_abnormal and location != "N/A":
            location = "N/A"

    sub["has_fracture"] = has_fracture
    sub["has_fracture_canonical"] = has_fracture
    sub["fracture_between"] = sub.get("fracture_between") if has_fracture else None
    sub["location"] = location
    sub["location_canonical"] = location

    if is_abnormal and ftype not in FRACTURE_TYPES:
        sub["source_type"] = ftype
        sub["source_location"] = "N/A"

    return sub


def compute_effective_frames(sub: dict[str, Any], video_fps: float, video_maxlen: int) -> int:
    """计算当前子视频在 LLaMA-Factory 默认 uniform 采样下的实际帧数。"""
    frames = sub.get("frame_paths") or []
    if frames:
        return len(frames)
    duration = sub.get("duration") or 0.0
    if duration <= 0:
        return 1
    n_by_fps = max(1, int(math.floor(duration * video_fps)))
    return min(n_by_fps, video_maxlen)


def build_assistant_content(sub: dict[str, Any]) -> str:
    """构造 assistant 输出的 JSON 字符串。"""
    has_fracture = sub["has_fracture_canonical"]
    output: dict[str, Any] = {
        "has_fracture": has_fracture,
        "fracture_between": (
            sub.get("fracture_between") if has_fracture else None
        ),
        "type": sub["type"],
        "location": sub["location_canonical"],
        "confidence": 1.0,
    }
    return json.dumps(output, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def convert_subvideo_to_sample(
    sub: dict[str, Any],
    video_fps: float,
    video_maxlen: int,
) -> dict[str, Any]:
    """将单条子视频元数据转换为 ShareGPT 训练样本。"""
    sub = _normalize_subvideo_labels(sub)
    start_time = sub.get("start_time", 0.0)
    end_time = sub.get("end_time", 0.0)
    effective_frames = compute_effective_frames(sub, video_fps, video_maxlen)

    user_prompt = build_user_prompt(
        sample_range=[start_time, end_time],
        num_frames=video_maxlen,
        video_fps=video_fps,
        effective_frames=effective_frames,
    )
    assistant_content = build_assistant_content(sub)

    sample: dict[str, Any] = {
        "id": sub["subvideo_id"],
        "videos": [sub["video_path"]],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": assistant_content},
        ],
        "has_fracture": sub["has_fracture_canonical"],
        "has_fracture_canonical": sub["has_fracture_canonical"],
        "fracture_between": (
            sub.get("fracture_between") if sub["has_fracture_canonical"] else None
        ),
        "type": sub["type"],
        "location": sub["location_canonical"],
        "location_canonical": sub["location_canonical"],
        "source_type": sub.get("source_type", sub["type"]),
        "source_location": sub.get("source_location", sub["location"]),
        "source_video": sub["source_video"],
        "start_frame": sub.get("start_frame"),
        "end_frame": sub.get("end_frame"),
    }
    return sample


def build_split_samples(
    subvideos: list[dict[str, Any]],
    split_video_ids: dict[str, set[str]],
    video_fps: float,
    video_maxlen: int,
) -> dict[str, list[dict[str, Any]]]:
    """按当前划分将子视频分组并转换为训练样本。"""
    by_split: dict[str, list[dict[str, Any]]] = {
        name: [] for name in split_video_ids
    }
    for sub in subvideos:
        src = sub["source_video"]
        for name, ids in split_video_ids.items():
            if src in ids:
                by_split[name].append(
                    convert_subvideo_to_sample(sub, video_fps, video_maxlen)
                )
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
        pos = sum(1 for s in samples if s.get("has_fracture_canonical", s["has_fracture"]))
        neg = len(samples) - pos
        total_pos += pos
        total_neg += neg

        source_dist = Counter(s["source_video"] for s in samples)
        type_dist = Counter(s["type"] for s in samples)
        source_type_dist = Counter(s["source_type"] for s in samples)

        split_meta[name] = {
            "sample_count": len(samples),
            "video_source_count": len(source_dist),
            "positive_samples": pos,
            "negative_samples": neg,
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


def build_all(
    subvideos_meta: Path,
    splits_dir: Path,
    output_dir: Path,
    video_fps: float,
    video_maxlen: int,
) -> dict[str, Any]:
    """核心构建入口：读取元数据、分组、写文件、返回统计信息。"""
    if not subvideos_meta.exists():
        raise FileNotFoundError(f"子视频元数据不存在: {subvideos_meta}")
    if not splits_dir.exists():
        raise FileNotFoundError(f"划分目录不存在: {splits_dir}")

    print(f"读取子视频元数据: {subvideos_meta}")
    subvideos = load_json(subvideos_meta)
    print(f"共 {len(subvideos)} 个子视频")

    print(f"加载划分文件: {splits_dir}")
    split_video_ids = load_split_video_ids(splits_dir)
    for name, ids in split_video_ids.items():
        print(f"  {name}: {len(ids)} 个原始视频")

    print("构建训练样本...")
    split_samples = build_split_samples(
        subvideos, split_video_ids, video_fps, video_maxlen
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, samples in split_samples.items():
        out_path = output_dir / f"{name}.json"
        write_json(out_path, samples)
        print(f"写入: {out_path} ({len(samples)} 条样本)")

    print("汇总样本统计信息...")
    samples_meta = compute_samples_meta(split_samples, split_video_ids)
    meta_path = output_dir / "samples_meta.json"
    write_json(meta_path, samples_meta)
    print(f"写入: {meta_path}")
    print("完成。")
    return samples_meta


def main() -> None:
    parser = argparse.ArgumentParser(description="新 interval 方案训练样本构建器")
    parser.add_argument(
        "--subvideos-meta", type=Path, default=SUBVIDEOS_META_DEFAULT
    )
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--video-fps", type=float, default=VIDEO_FPS)
    parser.add_argument("--video-maxlen", type=int, default=VIDEO_MAXLEN)
    args = parser.parse_args()

    build_all(
        subvideos_meta=args.subvideos_meta,
        splits_dir=args.splits_dir,
        output_dir=args.output_dir,
        video_fps=args.video_fps,
        video_maxlen=args.video_maxlen,
    )


if __name__ == "__main__":
    main()
