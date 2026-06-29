#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""筛选需要人工复核的尾部污染子视频。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUBVIDEOS_META_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.json"
AUDIT_OUTPUT_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "tail_contamination_audit.jsonl"
REVIEW_PACK_DEFAULT = PROJECT_ROOT / "data" / "08_review" / "tail_contamination"


def _load_subvideos(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        subvideos = payload.get("subvideos", [])
    else:
        subvideos = payload
    if not isinstance(subvideos, list):
        raise RuntimeError(f"{path}: subvideos must be a list")
    return subvideos


def _is_positive(sub: dict[str, Any]) -> bool:
    return sub.get("has_fracture_canonical", sub.get("has_fracture")) is True


def _is_tail_between(sub: dict[str, Any], mapping_len: int, tail_slots: int) -> bool:
    fracture_between = sub.get("fracture_between")
    if not isinstance(fracture_between, list) or len(fracture_between) != 2:
        return False
    try:
        left = int(fracture_between[0])
        right = int(fracture_between[1])
    except Exception:
        return False
    return right >= max(0, mapping_len - tail_slots) and right == left + 1


def _tail_ratio(sub: dict[str, Any], mapping: list[dict[str, Any]]) -> float | None:
    if not mapping:
        return None
    last_frame = mapping[-1].get("original_frame")
    end_frame = sub.get("end_frame")
    start_frame = sub.get("start_frame", 0)
    if last_frame is None or end_frame is None:
        return None
    try:
        denom = max(1, int(end_frame) - int(start_frame))
        return (int(last_frame) - int(start_frame)) / denom
    except Exception:
        return None


def _frame_path(path: str) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw
    if path.startswith("data/"):
        return PROJECT_ROOT / path
    return PROJECT_ROOT / "data" / path


def _copy_review_frames(sub: dict[str, Any], review_root: Path, tail_frame_count: int) -> list[str]:
    frame_paths = sub.get("frame_paths") or []
    if not frame_paths:
        return []

    output_dir = review_root / sub["subvideo_id"]
    output_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for rel in frame_paths[-tail_frame_count:]:
        src = _frame_path(str(rel))
        if not src.exists():
            continue
        dst = output_dir / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst.relative_to(PROJECT_ROOT)))

    meta_path = output_dir / "meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "subvideo_id": sub.get("subvideo_id"),
                "source_video": sub.get("source_video"),
                "video_path": sub.get("video_path"),
                "fracture_between": sub.get("fracture_between"),
                "actual_frame_mapping": sub.get("actual_frame_mapping"),
                "frame_paths": sub.get("frame_paths"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return copied


def audit_subvideo(
    sub: dict[str, Any],
    *,
    tail_slots: int,
) -> dict[str, Any] | None:
    if not _is_positive(sub):
        return None
    mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []
    if not isinstance(mapping, list) or not mapping:
        return None

    reasons: list[str] = []
    mapping_len = len(mapping)
    if _is_tail_between(sub, mapping_len, tail_slots):
        reasons.append("fracture_between_at_tail")

    ratio = _tail_ratio(sub, mapping)
    if not reasons:
        return None
    crop_type = str(sub.get("crop_type", ""))
    if crop_type.startswith("full"):
        reasons.append("full_video_positive")

    return {
        "decision": "review",
        "subvideo_id": sub.get("subvideo_id"),
        "source_video": sub.get("source_video"),
        "video_path": sub.get("video_path"),
        "crop_type": sub.get("crop_type"),
        "has_fracture_canonical": sub.get("has_fracture_canonical", sub.get("has_fracture")),
        "fracture_between": sub.get("fracture_between"),
        "mapping_len": mapping_len,
        "tail_ratio": round(ratio, 4) if ratio is not None else None,
        "risk_reasons": reasons,
        "frame_paths": sub.get("frame_paths") or [],
        "review_note": "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="筛选尾部污染高风险子视频")
    parser.add_argument("--input-meta", type=Path, default=SUBVIDEOS_META_DEFAULT)
    parser.add_argument("--output", type=Path, default=AUDIT_OUTPUT_DEFAULT)
    parser.add_argument("--review-pack", type=Path, default=REVIEW_PACK_DEFAULT)
    parser.add_argument("--tail-slots", type=int, default=2)
    parser.add_argument("--tail-frame-count", type=int, default=3)
    parser.add_argument(
        "--no-review-pack",
        action="store_true",
        help="只输出 jsonl 清单，不复制末尾图片",
    )
    args = parser.parse_args()

    subvideos = _load_subvideos(args.input_meta)
    findings: list[dict[str, Any]] = []
    for sub in subvideos:
        finding = audit_subvideo(
            sub,
            tail_slots=args.tail_slots,
        )
        if finding is None:
            continue
        if not args.no_review_pack:
            finding["review_frame_paths"] = _copy_review_frames(
                sub, args.review_pack, args.tail_frame_count
            )
        findings.append(finding)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for finding in findings:
            f.write(json.dumps(finding, ensure_ascii=False) + "\n")

    print(f"输入子视频: {len(subvideos)}")
    print(f"需要复核: {len(findings)}")
    print(f"审查清单: {args.output}")
    if not args.no_review_pack:
        print(f"图片复核包: {args.review_pack}")


if __name__ == "__main__":
    main()
