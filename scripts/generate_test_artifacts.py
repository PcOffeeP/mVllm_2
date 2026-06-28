#!/usr/bin/env python3
"""生成 test split 的测试输入与 ground truth 文件，供基座模型独立测试使用。

读取 data/05_splits/test.json + data/07_metadata/video_meta.json，
输出 data/06_merged/test_inputs.json 与 test_ground_truth.json（标准 JSON 数组格式）。
完全独立于 subvideos_meta.json，不依赖子视频生成管线。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META_DIR = ROOT / "data" / "07_metadata"
SPLITS_DIR = ROOT / "data" / "05_splits"
MERGED_DIR = ROOT / "data" / "06_merged"

# test_ground_truth.json 所需字段（直取，零额外计算）
GROUND_TRUTH_FIELDS = [
    "video_id",
    "has_fracture",
    "has_fracture_canonical",
    "is_abnormal",
    "is_abnormal_canonical",
    "video_anomaly_kind",
    "event_time_reliable",
    "event_frame_original",
    "event_time",
    "type",
    "location",
    "location_canonical",
]

# test_inputs.json 所需字段
INPUT_FIELDS = ["id", "video_id", "video_path"]


def main() -> int:
    # ── 输入文件存在性检查 ──────────────────────────────────────────
    test_split_path = SPLITS_DIR / "test.json"
    video_meta_path = META_DIR / "video_meta.json"

    missing = []
    if not test_split_path.exists():
        missing.append(str(test_split_path))
    if not video_meta_path.exists():
        missing.append(str(video_meta_path))
    if missing:
        print(f"ERROR: 缺失必要输入文件: {', '.join(missing)}", file=sys.stderr)
        print(f"请确保项目结构完整，上述文件存在于 data/ 目录下。", file=sys.stderr)
        return 1

    # ── 加载数据 ────────────────────────────────────────────────────
    with test_split_path.open(encoding="utf-8") as f:
        test_split: dict = json.load(f)
    video_ids: list[str] = test_split.get("video_ids", [])

    with video_meta_path.open(encoding="utf-8") as f:
        video_meta_list: list[dict] = json.load(f)

    # 建立 video_id → 记录 的快速索引
    meta_index: dict[str, dict] = {rec["video_id"]: rec for rec in video_meta_list}

    # ── 逐条生成 test_inputs ────────────────────────────────────────
    test_inputs: list[dict] = []
    for vid in video_ids:
        rec = meta_index.get(vid)
        if rec is None:
            print(
                f"WARNING: video_id={vid} 在 video_meta.json 中不存在，跳过",
                file=sys.stderr,
            )
            continue
        test_inputs.append(
            {
                "id": vid,
                "video_id": vid,
                "video_path": rec.get("video_path", f"data/01_videos/{vid}.mp4"),
            }
        )

    # ── 逐条生成 test_ground_truth ──────────────────────────────────
    test_ground_truth: list[dict] = []
    for vid in video_ids:
        rec = meta_index.get(vid)
        if rec is None:
            continue
        test_ground_truth.append(
            {field: rec.get(field) for field in GROUND_TRUTH_FIELDS}
        )

    # ── 输出目录确保存在 ────────────────────────────────────────────
    MERGED_DIR.mkdir(parents=True, exist_ok=True)

    # ── 写出 test_inputs.json（标准 JSON 数组）─────────────────────
    inputs_path = MERGED_DIR / "test_inputs.json"
    with inputs_path.open("w", encoding="utf-8") as f:
        json.dump(test_inputs, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(test_inputs)} records → {inputs_path}")

    # ── 写出 test_ground_truth.json（标准 JSON 数组）───────────────
    gt_path = MERGED_DIR / "test_ground_truth.json"
    with gt_path.open("w", encoding="utf-8") as f:
        json.dump(test_ground_truth, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(test_ground_truth)} records → {gt_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
