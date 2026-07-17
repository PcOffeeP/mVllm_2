#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
筛选人工审查后的子视频 metadata 中的 neg_before 样本。

规则（仅处理 review_status == "approved" 且 crop_type == "neg_before" 的记录，
其余记录全部原样保留）：
- source_type 属于 {"脆性断裂", "脆性断裂、齐根断裂"}：按 source_video 分组，每组只保留最临近事件的一条
  （end_time 最大优先，并列时 start_time 最大优先）。
- source_type == "韧性断裂"：全部保留。
- 其他 source_type（界面脱粘、齐根断裂等）：全部保留。

输出与输入结构一致：保留顶层其他字段，仅替换 ``subvideos`` 列表。

使用示例：
    python pipeline/scripts/filter_reviewed_neg_before.py
    python -m pipeline.scripts.filter_reviewed_neg_before

    # 额外输出被丢弃子视频的报告
    python pipeline/scripts/filter_reviewed_neg_before.py \
        --output-report data/07_metadata/filter_neg_before_dropped_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_META_DEFAULT = (
    PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.label_reviewed.json"
)
OUTPUT_META_DEFAULT = (
    PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.filtered_neg_before.json"
)

BRITTLE_DEDUP_TYPES = {"脆性断裂", "脆性断裂、齐根断裂"}
REPORT_FIELDS = ("subvideo_id", "source_video", "source_type", "start_time", "end_time")


def _is_brittle_neg_before(sub: dict[str, Any]) -> bool:
    """是否为需要按源视频去重的脆性断裂 neg_before 记录。"""
    return (
        sub.get("review_status") == "approved"
        and sub.get("crop_type") == "neg_before"
        and sub.get("source_type") in BRITTLE_DEDUP_TYPES
    )


def _find_brittle_missing_source_video(
    subvideos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """返回 source_video 缺失或为空的脆性断裂 neg_before 记录（无法按源视频分组去重）。"""
    return [
        sub
        for sub in subvideos
        if _is_brittle_neg_before(sub) and not sub.get("source_video")
    ]


def filter_subvideos(
    subvideos: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按筛选规则拆分记录，返回 (kept, dropped)，两者均保持输入中的相对顺序。"""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sub in subvideos:
        if _is_brittle_neg_before(sub):
            groups[sub.get("source_video", "")].append(sub)

    winner_ids: set[int] = set()
    for group in groups.values():
        winner = max(
            group,
            key=lambda s: (
                float(s.get("end_time") or 0.0),
                float(s.get("start_time") or 0.0),
            ),
        )
        winner_ids.add(id(winner))

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for sub in subvideos:
        if _is_brittle_neg_before(sub) and id(sub) not in winner_ids:
            dropped.append(sub)
        else:
            kept.append(sub)
    return kept, dropped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="筛选人工审查后的 neg_before 子视频：脆性断裂每个源视频只保留最临近事件的一条",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s

  # 指定输入/输出，并输出被丢弃子视频的报告
  %(prog)s --input-meta data/07_metadata/subvideos_meta.label_reviewed.json \\
           --output-meta data/07_metadata/subvideos_meta.filtered_neg_before.json \\
           --output-report data/07_metadata/filter_neg_before_dropped_report.json
        """.strip(),
    )
    parser.add_argument(
        "--input-meta",
        type=Path,
        default=INPUT_META_DEFAULT,
        help="输入子视频元数据路径（默认：data/07_metadata/subvideos_meta.label_reviewed.json）",
    )
    parser.add_argument(
        "--output-meta",
        type=Path,
        default=OUTPUT_META_DEFAULT,
        help="输出筛选后元数据路径（默认：data/07_metadata/subvideos_meta.filtered_neg_before.json）",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=None,
        help="可选：被丢弃子视频的报告 JSON 输出路径（含 subvideo_id、source_video、"
        "source_type、start_time、end_time）",
    )
    args = parser.parse_args()

    if not args.input_meta.exists():
        print(f"错误：输入元数据不存在: {args.input_meta}", file=sys.stderr)
        return 2

    metadata = json.loads(args.input_meta.read_text(encoding="utf-8"))
    subvideos = metadata.get("subvideos", [])

    missing_source = _find_brittle_missing_source_video(subvideos)
    if missing_source:
        print(
            "错误：存在缺失 source_video 的脆性断裂 neg_before 记录，无法按源视频分组去重：",
            file=sys.stderr,
        )
        for sub in missing_source:
            print(f"  - {sub.get('subvideo_id')}", file=sys.stderr)
        return 2

    kept, dropped = filter_subvideos(subvideos)

    output_metadata = dict(metadata)
    output_metadata["subvideos"] = kept

    args.output_meta.parent.mkdir(parents=True, exist_ok=True)
    args.output_meta.write_text(
        json.dumps(output_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.output_report is not None:
        report = [
            {field: sub.get(field) for field in REPORT_FIELDS} for sub in dropped
        ]
        args.output_report.parent.mkdir(parents=True, exist_ok=True)
        args.output_report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    drop_by_source_type = Counter(sub.get("source_type") for sub in dropped)

    print(f"输入: {len(subvideos)} 条")
    print(f"保留: {len(kept)} 条")
    print(f"丢弃: {len(dropped)} 条")
    print("丢弃分布 (by source_type):")
    for source_type, count in sorted(
        drop_by_source_type.items(), key=lambda kv: (-kv[1], str(kv[0]))
    ):
        print(f"  - {source_type}: {count}")
    print(f"写出: {args.output_meta}")
    if args.output_report is not None:
        print(f"报告: {args.output_report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
