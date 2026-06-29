#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据人工复核决策剔除尾部污染子视频。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUBVIDEOS_META_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.json"
DECISIONS_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "tail_contamination_audit.jsonl"
OUTPUT_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.cleaned.json"


DROP_DECISIONS = {"drop", "remove", "bad", "exclude"}
DROP_SOURCE_DECISIONS = {"drop_source", "remove_source", "exclude_source"}


def _load_payload(path: Path) -> tuple[Any, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        subvideos = payload.get("subvideos", [])
    else:
        subvideos = payload
    if not isinstance(subvideos, list):
        raise RuntimeError(f"{path}: subvideos must be a list")
    return payload, subvideos


def _load_decisions(path: Path) -> tuple[set[str], set[str]]:
    drop_subvideos: set[str] = set()
    drop_sources: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            decision = str(item.get("decision", "")).strip().lower()
            subvideo_id = item.get("subvideo_id")
            source_video = item.get("source_video")
            if decision in DROP_DECISIONS:
                if not subvideo_id:
                    raise RuntimeError(f"{path}:{line_no}: drop decision missing subvideo_id")
                drop_subvideos.add(str(subvideo_id))
            elif decision in DROP_SOURCE_DECISIONS:
                if not source_video:
                    raise RuntimeError(f"{path}:{line_no}: drop_source decision missing source_video")
                drop_sources.add(str(source_video))
    return drop_subvideos, drop_sources


def _filter_subvideos(
    subvideos: list[dict[str, Any]],
    *,
    drop_subvideos: set[str],
    drop_sources: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for sub in subvideos:
        subvideo_id = str(sub.get("subvideo_id", ""))
        source_video = str(sub.get("source_video", ""))
        reason = None
        if subvideo_id in drop_subvideos:
            reason = "tail_review_drop_subvideo"
        elif source_video in drop_sources:
            reason = "tail_review_drop_source"

        if reason is None:
            kept.append(sub)
        else:
            removed.append(
                {
                    "subvideo_id": sub.get("subvideo_id"),
                    "source_video": sub.get("source_video"),
                    "reason": reason,
                }
            )
    return kept, removed


def _write_payload(payload: Any, subvideos: list[dict[str, Any]], removed: list[dict[str, Any]], output: Path) -> None:
    if isinstance(payload, dict):
        new_payload = dict(payload)
        new_payload["subvideos"] = subvideos
        if isinstance(new_payload.get("candidates"), list):
            removed_ids = {item["subvideo_id"] for item in removed}
            removed_sources = {
                item["source_video"]
                for item in removed
                if item["reason"] == "tail_review_drop_source"
            }
            new_payload["candidates"] = [
                sub for sub in new_payload["candidates"]
                if sub.get("subvideo_id") not in removed_ids
                and sub.get("source_video") not in removed_sources
            ]
        existing_exclusions = new_payload.get("exclusions", [])
        if not isinstance(existing_exclusions, list):
            existing_exclusions = []
        new_payload["exclusions"] = existing_exclusions + removed
    else:
        new_payload = subvideos

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="应用尾部污染人工复核决策")
    parser.add_argument("--input-meta", type=Path, default=SUBVIDEOS_META_DEFAULT)
    parser.add_argument("--decisions", type=Path, default=DECISIONS_DEFAULT)
    parser.add_argument("--output-meta", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="直接覆盖 --input-meta；默认写到 --output-meta",
    )
    args = parser.parse_args()

    payload, subvideos = _load_payload(args.input_meta)
    drop_subvideos, drop_sources = _load_decisions(args.decisions)
    kept, removed = _filter_subvideos(
        subvideos,
        drop_subvideos=drop_subvideos,
        drop_sources=drop_sources,
    )

    output = args.input_meta if args.in_place else args.output_meta
    _write_payload(payload, kept, removed, output)

    print(f"输入子视频: {len(subvideos)}")
    print(f"剔除子视频: {len(removed)}")
    print(f"保留子视频: {len(kept)}")
    print(f"drop subvideo_id: {len(drop_subvideos)}")
    print(f"drop source_video: {len(drop_sources)}")
    print(f"输出文件: {output}")


if __name__ == "__main__":
    main()
