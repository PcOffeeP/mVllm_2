"""Build a global INDEX.md overview from per-collection artifact indexes."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipeline import artifact_index

COLLECTIONS: tuple[tuple[str, Path], ...] = (
    ("source_snapshots", Path("derived/metadata/source_snapshots")),
    ("split_snapshots", Path("derived/metadata/split_snapshots")),
    ("roi_manifests", Path("derived/metadata/roi_manifests")),
    ("roi_videos", Path("derived/roi_videos")),
    ("candidate_plans", Path("derived/metadata/candidate_plans")),
    ("candidate_media_results", Path("derived/metadata/candidate_media_results")),
    ("subvideos", Path("derived/subvideos")),
    ("frames", Path("derived/frames")),
    ("review_queues", Path("derived/metadata/review_queues")),
    ("review_decisions", Path("derived/metadata/review_decisions")),
    ("training_releases", Path("releases")),
)


def _format_mapping(value: dict[str, Any]) -> str:
    if not value:
        return "-"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _collect_rows(data_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for collection_name, relative in COLLECTIONS:
        collection_dir = data_root / relative
        index_path = collection_dir / artifact_index.INDEX_FILENAME
        if not index_path.is_file():
            warnings.append(f"跳过无 index.json 的产物集合: {collection_name}")
            continue
        try:
            entries = artifact_index.read_index(collection_dir)
        except (ValueError, TypeError, OSError) as exc:
            warnings.append(f"读取 {collection_name} 索引失败: {exc}")
            continue
        for entry in entries:
            rows.append(
                {
                    "step": entry["step"],
                    "id": entry["id"],
                    "created_at": entry["created_at"],
                    "stats": entry["stats"],
                    "inputs": entry["inputs"],
                }
            )
    rows.sort(key=lambda row: row["created_at"])
    return rows, warnings


def _render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# 产物索引\n",
        "",
        "| 步骤 | ID | 时间 | 关键统计 | 上游 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['step']} | {row['id']} | {row['created_at']} | "
            f"{_format_mapping(row['stats'])} | {_format_mapping(row['inputs'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_index(data_root: Path) -> tuple[Path, list[str]]:
    rows, warnings = _collect_rows(data_root)
    content = _render_markdown(rows)
    output = data_root / "INDEX.md"
    output.write_text(content, encoding="utf-8")
    return output, warnings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="生成显式历史数据根的INDEX.md审计总览；不注册新版本。"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="显式历史数据根目录（必须存在）",
    )
    args = parser.parse_args(argv)

    data_root = args.data_root.resolve()
    if not data_root.is_dir():
        parser.error("--data-root 必须是现存目录")

    output, warnings = build_index(data_root)
    for warning in warnings:
        print(warning, file=sys.stderr)
    print(f"已生成产物索引: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
