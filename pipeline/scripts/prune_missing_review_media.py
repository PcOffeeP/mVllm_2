#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据人工删除的子视频/帧图片反向剔除 metadata 条目。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUBVIDEOS_META_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.json"
OUTPUT_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.pruned.json"
REPORT_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "missing_review_media_prune.jsonl"


def _load_payload(path: Path) -> tuple[Any, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        subvideos = payload.get("subvideos", [])
    else:
        subvideos = payload
    if not isinstance(subvideos, list):
        raise RuntimeError(f"{path}: subvideos must be a list")
    return payload, subvideos


def _resolve_data_path(path: str) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw
    if path.startswith("data/"):
        return PROJECT_ROOT / path
    return PROJECT_ROOT / "data" / path


def _missing_media_reasons(sub: dict[str, Any], *, require_frames: bool) -> list[str]:
    reasons: list[str] = []

    video_path = sub.get("video_path")
    if isinstance(video_path, str) and video_path:
        resolved_video = _resolve_data_path(video_path)
        if "data/03_subvideos/" in str(resolved_video) and not resolved_video.exists():
            reasons.append("missing_subvideo_file")

    frame_paths = sub.get("frame_paths") or []
    if require_frames and not frame_paths:
        reasons.append("missing_frame_paths")
    for frame_path in frame_paths:
        if not _resolve_data_path(str(frame_path)).exists():
            reasons.append("missing_frame_file")
            break

    return reasons


def _filter_subvideos(
    subvideos: list[dict[str, Any]],
    *,
    require_frames: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for sub in subvideos:
        reasons = _missing_media_reasons(sub, require_frames=require_frames)
        if reasons:
            removed.append(
                {
                    "subvideo_id": sub.get("subvideo_id"),
                    "source_video": sub.get("source_video"),
                    "reason": "missing_review_media",
                    "details": reasons,
                }
            )
        else:
            kept.append(sub)
    return kept, removed


def _write_payload(payload: Any, kept: list[dict[str, Any]], removed: list[dict[str, Any]], output: Path) -> None:
    if isinstance(payload, dict):
        new_payload = dict(payload)
        removed_ids = {item["subvideo_id"] for item in removed}
        new_payload["subvideos"] = kept
        if isinstance(new_payload.get("candidates"), list):
            new_payload["candidates"] = [
                sub for sub in new_payload["candidates"]
                if sub.get("subvideo_id") not in removed_ids
            ]
        existing_exclusions = new_payload.get("exclusions", [])
        if not isinstance(existing_exclusions, list):
            existing_exclusions = []
        new_payload["exclusions"] = existing_exclusions + removed
    else:
        new_payload = kept

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(new_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_report(removed: list[dict[str, Any]], report: Path) -> None:
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", encoding="utf-8") as f:
        for item in removed:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="按缺失子视频/帧图片剔除 metadata")
    parser.add_argument("--input-meta", type=Path, default=SUBVIDEOS_META_DEFAULT)
    parser.add_argument("--output-meta", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    parser.add_argument(
        "--require-frames",
        action="store_true",
        help="没有 frame_paths 的条目也视为缺失媒体",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="直接覆盖 --input-meta；默认写到 --output-meta",
    )
    args = parser.parse_args()

    payload, subvideos = _load_payload(args.input_meta)
    kept, removed = _filter_subvideos(subvideos, require_frames=args.require_frames)
    output = args.input_meta if args.in_place else args.output_meta
    _write_payload(payload, kept, removed, output)
    _write_report(removed, args.report)

    print(f"输入子视频: {len(subvideos)}")
    print(f"剔除子视频: {len(removed)}")
    print(f"保留子视频: {len(kept)}")
    print(f"输出文件: {output}")
    print(f"剔除报告: {args.report}")


if __name__ == "__main__":
    main()
