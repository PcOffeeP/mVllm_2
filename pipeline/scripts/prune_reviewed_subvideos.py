#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人工审核后清洗子视频元数据。

规则：
- mp4 与帧目录都存在：保留。
- mp4 与帧目录都缺失：视为人工删除，从 metadata 中剔除。
- 只缺 mp4 或只缺帧目录：不一致状态，非零退出并报告。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SUBVIDEOS_META_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.json"
OUTPUT_META_DEFAULT = (
    PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.reviewed.json"
)
REPORT_DEFAULT = (
    PROJECT_ROOT / "data" / "07_metadata" / "manual_review_prune_report.json"
)
FRAME_DIR_DEFAULT = PROJECT_ROOT / "data" / "04_frames"


def _resolve_path(rel: str, project_root: Path) -> Path:
    """将元数据中的相对路径解析为绝对路径。"""
    if rel.startswith("data/"):
        return project_root / rel
    return project_root / "data" / rel


def _video_file_valid(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _load_subvideos(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读取子视频元数据，支持 dict 与 list 两种顶层结构。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw.get("subvideos", []), raw
    return raw, {}


def _classify_entry(
    sub: dict[str, Any],
    frame_dir_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    """对单条子视频记录做存在性分类。"""
    subvideo_id = sub.get("subvideo_id", "<unknown>")
    source_video = sub.get("source_video", "<unknown>")
    video_path_rel = sub.get("video_path", "")
    video_path = (
        _resolve_path(video_path_rel, project_root)
        if video_path_rel
        else project_root / "data" / "03_subvideos" / f"{subvideo_id}.mp4"
    )
    frame_dir = frame_dir_root / subvideo_id

    video_file_exists = video_path.exists()
    video_file_valid = _video_file_valid(video_path)
    frame_dir_exists = frame_dir.is_dir() and any(frame_dir.iterdir())

    if video_file_valid and frame_dir_exists:
        status = "kept"
        reason = "both_present"
    elif not video_file_valid and not video_file_exists and not frame_dir_exists:
        status = "dropped"
        reason = "both_missing"
    elif not video_file_valid:
        status = "inconsistent"
        reason = "invalid_video" if video_file_exists else "missing_video"
    else:
        status = "inconsistent"
        reason = "missing_frames"

    return {
        "subvideo_id": subvideo_id,
        "source_video": source_video,
        "video_path": video_path_rel,
        "frame_dir": str(frame_dir.relative_to(project_root)),
        "video_exists": video_file_exists,
        "video_valid": video_file_valid,
        "frame_dir_exists": frame_dir_exists,
        "status": status,
        "reason": reason,
    }


def prune_reviewed_subvideos(
    subvideos_meta: Path,
    output_meta: Path,
    report_path: Path,
    frame_dir_root: Path = FRAME_DIR_DEFAULT,
    project_root: Path = PROJECT_ROOT,
    allow_partial_report: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    执行人工审核后的 metadata 清洗。

    返回 (kept_entries, dropped_entries, inconsistent_entries)。
    若存在 inconsistent 条目，默认不写出 output_meta；指定
    allow_partial_report=True 时仅写出 kept 条目。
    """
    subvideos, top_level = _load_subvideos(subvideos_meta)

    classifications: list[dict[str, Any]] = []
    for sub in subvideos:
        classifications.append(
            _classify_entry(sub, frame_dir_root, project_root)
        )

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    inconsistent: list[dict[str, Any]] = []
    kept_indices: list[int] = []

    for idx, cls in enumerate(classifications):
        if cls["status"] == "kept":
            kept.append(subvideos[idx])
            kept_indices.append(idx)
        elif cls["status"] == "dropped":
            dropped.append(cls)
        else:
            inconsistent.append(cls)

    report: dict[str, Any] = {
        "input_meta": str(subvideos_meta),
        "output_meta": str(output_meta),
        "total_entries": len(subvideos),
        "kept_count": len(kept),
        "dropped_count": len(dropped),
        "inconsistent_count": len(inconsistent),
        "dropped": dropped,
        "inconsistent": inconsistent,
        "kept_subvideo_ids": [sub.get("subvideo_id") for sub in kept],
    }

    output_meta.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if inconsistent:
        # 不一致状态下默认不写出 reviewed metadata，避免下游误用。
        # 显式开启 --allow-partial-report 时，仅写出保留的条目供人工复核。
        if allow_partial_report:
            output_payload = dict(top_level)
            output_payload["subvideos"] = kept
            output_meta.write_text(
                json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return kept, dropped, inconsistent

    output_payload = dict(top_level)
    output_payload["subvideos"] = kept
    output_meta.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return kept, dropped, inconsistent


def main() -> int:
    parser = argparse.ArgumentParser(description="人工审核后清洗子视频元数据")
    parser.add_argument(
        "--subvideos-meta",
        "--input-meta",
        dest="subvideos_meta",
        metavar="PATH",
        type=Path,
        default=SUBVIDEOS_META_DEFAULT,
        help="输入子视频元数据路径（默认：data/07_metadata/subvideos_meta.json）",
    )
    parser.add_argument(
        "--output-meta",
        type=Path,
        default=OUTPUT_META_DEFAULT,
        help="输出清洗后元数据路径（默认：data/07_metadata/subvideos_meta.reviewed.json）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_DEFAULT,
        help="清洗报告输出路径",
    )
    parser.add_argument(
        "--frame-dir",
        type=Path,
        default=FRAME_DIR_DEFAULT,
        help="帧目录根路径（默认：data/04_frames）",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="项目根目录，用于解析相对路径",
    )
    parser.add_argument(
        "--allow-partial-report",
        action="store_true",
        help="存在不一致样本时仍写出仅含 kept 条目的 output_meta",
    )
    args = parser.parse_args()

    if not args.subvideos_meta.exists():
        print(f"错误：输入元数据不存在: {args.subvideos_meta}", file=sys.stderr)
        return 2

    kept, dropped, inconsistent = prune_reviewed_subvideos(
        subvideos_meta=args.subvideos_meta,
        output_meta=args.output_meta,
        report_path=args.report,
        frame_dir_root=args.frame_dir,
        project_root=args.project_root,
        allow_partial_report=args.allow_partial_report,
    )

    print(
        f"扫描 {len(kept) + len(dropped) + len(inconsistent)} 条样本: "
        f"保留 {len(kept)}, 删除 {len(dropped)}, 不一致 {len(inconsistent)}"
    )

    if inconsistent:
        print("错误：发现不一致样本，必须先运行 repair_review_media.py 修复", file=sys.stderr)
        for item in inconsistent:
            print(
                f"  - {item['subvideo_id']}: {item['reason']} "
                f"(video={item['video_exists']}, frames={item['frame_dir_exists']})",
                file=sys.stderr,
            )
        return 1

    print(f"写出: {args.output_meta}")
    print(f"报告: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
