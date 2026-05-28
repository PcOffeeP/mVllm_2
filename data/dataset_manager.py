#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频数据集管理器
功能：
1. split: 生成K-Fold训练/验证集划分
"""

import os
import json
import argparse
from pathlib import Path
from typing import List
import random


def generate_kfold_splits(video_dir: Path, k: int = 3, output_dir: Path = None, 
                          shuffle: bool = True, seed: int = 42) -> List[Path]:
    """
    生成分层K折交叉验证的划分文件
    确保每一折都包含所有类别（预设的四大类或子文件夹）的数据
    
    Args:
        video_dir: 视频目录
        k: K值（折数）
        output_dir: 输出目录（默认为video_dir/splits）
        shuffle: 是否随机打乱
        seed: 随机种子
    
    Returns:
        生成的划分文件路径列表
    """
    if output_dir is None:
        output_dir = video_dir / "splits"
    
    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)
    
    categories = ['Comp', 'Mat', 'Poly', 'Other']
    video_dict = {cat: [] for cat in categories}
    
    total_videos = 0
    for cat in categories:
        cat_dir = video_dir / cat
        if cat_dir.exists() and cat_dir.is_dir():
            videos = sorted([os.path.relpath(str(f.absolute()), video_dir / cat) for f in cat_dir.glob("**/*.mp4")])
            video_dict[cat] = videos
            total_videos += len(videos)
            
    if total_videos == 0:
        # 后备方案：如果不包含指定的四大类，则当做无类别进行划分
        video_files = sorted([os.path.relpath(str(f.absolute()), video_dir) for f in video_dir.glob("**/*.mp4")])
        if len(video_files) == 0:
            raise ValueError(f"在 {video_dir} 未找到视频文件")
        print(f"警告：未找到预期的四大类文件夹，回退到普通K折划分。找到 {len(video_files)} 个视频文件")
        video_dict = {"all": video_files}
    else:
        print(f"一共找到 {total_videos} 个视频文件，分布如下：")
        for cat, videos in video_dict.items():
            print(f"  - {cat}: {len(videos)} 个")
    
    if shuffle:
        random.seed(seed)
        for cat in video_dict:
            random.shuffle(video_dict[cat])
    
    split_files = []
    
    for i in range(k):
        train_set = []
        val_set = []
        
        for cat, videos in video_dict.items():
            if not videos:
                continue
            # 计算该类别的验证集索引范围
            fold_size = len(videos) // k
            val_start = i * fold_size
            val_end = (i + 1) * fold_size if i < k - 1 else len(videos)
            
            val_set.extend(videos[val_start:val_end])
            train_set.extend(videos[:val_start] + videos[val_end:])
            
        # 保存划分文件
        split_data = {
            "method": f"stratified_{k}_fold",
            "k": k,
            "fold": i,
            "train": train_set,
            "val": val_set,
            "train_count": len(train_set),
            "val_count": len(val_set)
        }
        
        split_filename = f"stratified_{k}_fold_{i}.json"
        split_path = output_dir / split_filename
        
        with open(split_path, 'w', encoding='utf-8') as f:
            json.dump(split_data, f, ensure_ascii=False, indent=2)
        
        print(f"生成: {split_filename} (训练集: {len(train_set)}, 验证集: {len(val_set)})")
        split_files.append(split_path)
    
    return split_files


def main():
    parser = argparse.ArgumentParser(description="视频数据集K折划分工具")
    parser.add_argument('--video-dir', type=Path, default=Path(__file__).parent,
                        help='视频目录（默认为当前脚本所在目录）')
    parser.add_argument('--k', type=int, default=3, help='K折数（默认: 3）')
    parser.add_argument('--output-dir', type=Path, default=None,
                        help='输出目录（默认为video_dir/splits）')
    parser.add_argument('--seed', type=int, default=42, help='随机种子（默认: 42）')
    
    args = parser.parse_args()
    
    generate_kfold_splits(
        video_dir=args.video_dir, 
        k=args.k, 
        output_dir=args.output_dir, 
        seed=args.seed
    )


if __name__ == '__main__':
    main()
