#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频数据集管理器
功能：
1. split: 从 CSV 标注读取视频列表和材料类型，生成 K-Fold 训练/验证集划分
   - stratified_3_fold: 按材料类型分层，3折，每折 train/val
   - kfold_5_fold: 常规 5 折交叉验证，train/test
"""

import os
import json
import argparse
import random
from pathlib import Path
from collections import defaultdict

# ===================== 常量 =====================
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CSV_PATH_DEFAULT = PROJECT_ROOT / "data" / "02_annotations" / "all_videos_tag.csv"
OUTPUT_DIR_DEFAULT = PROJECT_ROOT / "data" / "03_splits"

# 材料类型归一化：将 CSV 中的子类归入四大类
MATERIAL_NORMALIZE = {
    "金属": "金属",
    "高分子": "高分子",
    "复材": "复材",
}


def normalize_material(raw: str) -> str:
    """将 CSV 中的材料类型归一化到 金属/高分子/复材/其他"""
    if raw in MATERIAL_NORMALIZE:
        return MATERIAL_NORMALIZE[raw]
    return "其他"


def load_videos_from_csv(csv_path: Path) -> dict[str, list[str]]:
    """
    从 CSV 读取视频列表和材料类型，返回 {材料类型: [video_id列表]}
    video_id 格式: video_0001 (无扩展名)
    """
    import pandas as pd

    df = pd.read_csv(csv_path)

    grouped = defaultdict(list)
    for _, row in df.iterrows():
        video_id = row["id"]
        material_raw = row["材料类型"] if not pd.isna(row["材料类型"]) else "其他"
        if not pd.isna(video_id):
            material = normalize_material(str(material_raw).strip())
            grouped[material].append(str(video_id).strip())

    return dict(grouped)


def generate_stratified_3_fold(
    video_dict: dict[str, list[str]],
    output_dir: Path,
    shuffle: bool = True,
    seed: int = 42,
) -> list[Path]:
    """
    生成按材料类型分层的 3 折划分，每折含 train/val。

    Args:
        video_dict: {材料类型: [video_id列表]}
        output_dir: 输出目录
        shuffle: 是否随机打乱
        seed: 随机种子

    Returns:
        生成的划分文件路径列表
    """
    k = 3
    output_dir.mkdir(parents=True, exist_ok=True)

    if shuffle:
        random.seed(seed)
        for cat in video_dict:
            random.shuffle(video_dict[cat])

    split_files = []

    for fold in range(k):
        train_set = []
        val_set = []

        for cat, videos in video_dict.items():
            if not videos:
                continue
            n = len(videos)
            fold_size = n // k
            val_start = fold * fold_size
            val_end = (fold + 1) * fold_size if fold < k - 1 else n

            val_set.extend(videos[val_start:val_end])
            train_set.extend(videos[:val_start] + videos[val_end:])

        # 统一路径格式: video_XXXX.mp4
        train_paths = [f"{vid}.mp4" for vid in train_set]
        val_paths = [f"{vid}.mp4" for vid in val_set]

        split_data = {
            "method": "stratified_3_fold",
            "k": k,
            "fold": fold,
            "train": sorted(train_paths),
            "val": sorted(val_paths),
            "train_count": len(train_paths),
            "val_count": len(val_paths),
        }

        split_path = output_dir / f"stratified_3_fold_{fold}.json"
        with open(split_path, "w", encoding="utf-8") as f:
            json.dump(split_data, f, ensure_ascii=False, indent=2)

        print(
            f"生成: stratified_3_fold_{fold}.json "
            f"(train: {len(train_paths)}, val: {len(val_paths)})"
        )
        split_files.append(split_path)

    return split_files


def generate_kfold_5_fold(
    video_dict: dict[str, list[str]],
    output_dir: Path,
    shuffle: bool = True,
    seed: int = 42,
) -> list[Path]:
    """
    生成常规 5 折交叉验证划分，每折含 train/test。

    Args:
        video_dict: {材料类型: [video_id列表]}
        output_dir: 输出目录
        shuffle: 是否随机打乱
        seed: 随机种子

    Returns:
        生成的划分文件路径列表
    """
    k = 5
    output_dir.mkdir(parents=True, exist_ok=True)

    # 将所有视频合并为一个列表
    all_videos = []
    for videos in video_dict.values():
        all_videos.extend(videos)

    if shuffle:
        random.seed(seed)
        random.shuffle(all_videos)

    split_files = []
    n = len(all_videos)

    for fold in range(k):
        fold_size = n // k
        test_start = fold * fold_size
        test_end = (fold + 1) * fold_size if fold < k - 1 else n

        test_set = all_videos[test_start:test_end]
        train_set = all_videos[:test_start] + all_videos[test_end:]

        # 统一路径格式: video_XXXX.mp4
        train_paths = sorted([f"{vid}.mp4" for vid in train_set])
        test_paths = sorted([f"{vid}.mp4" for vid in test_set])

        split_data = {
            "method": "kfold_5_fold",
            "k": k,
            "fold": fold,
            "train": train_paths,
            "test": test_paths,
            "train_count": len(train_paths),
            "test_count": len(test_paths),
        }

        split_path = output_dir / f"kfold_5_fold_{fold}.json"
        with open(split_path, "w", encoding="utf-8") as f:
            json.dump(split_data, f, ensure_ascii=False, indent=2)

        print(
            f"生成: kfold_5_fold_{fold}.json "
            f"(train: {len(train_paths)}, test: {len(test_paths)})"
        )
        split_files.append(split_path)

    return split_files


def main():
    parser = argparse.ArgumentParser(description="视频数据集K折划分工具")
    parser.add_argument(
        "--csv",
        type=Path,
        default=CSV_PATH_DEFAULT,
        help="标注 CSV 文件路径（默认: data/02_annotations/all_videos_tag.csv）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR_DEFAULT,
        help="输出目录（默认: data/03_splits/）",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="随机种子（默认: 42）"
    )
    parser.add_argument(
        "--no-stratified",
        action="store_true",
        help="跳过 stratified_3_fold 生成",
    )
    parser.add_argument(
        "--no-kfold",
        action="store_true",
        help="跳过 kfold_5_fold 生成",
    )
    # 保留旧接口兼容
    parser.add_argument(
        "--video-dir",
        type=Path,
        default=None,
        help="（已废弃）请使用 --csv 指定标注文件",
    )

    args = parser.parse_args()

    if not args.csv.exists():
        print(f"错误: 标注文件不存在: {args.csv}")
        return

    print(f"从 CSV 读取视频列表: {args.csv}")
    video_dict = load_videos_from_csv(args.csv)

    total = sum(len(v) for v in video_dict.values())
    print(f"共找到 {total} 个视频，材料类型分布:")
    for cat, videos in sorted(video_dict.items()):
        print(f"  - {cat}: {len(videos)} 个")

    print()

    if not args.no_stratified:
        print("=== 生成 stratified_3_fold（按材料类型分层，3折）===")
        generate_stratified_3_fold(
            video_dict, args.output_dir, seed=args.seed
        )
        print()

    if not args.no_kfold:
        print("=== 生成 kfold_5_fold（常规 5 折交叉验证）===")
        generate_kfold_5_fold(
            video_dict, args.output_dir, seed=args.seed
        )
        print()

    print("所有 split 文件已生成完毕。")


if __name__ == "__main__":
    main()
