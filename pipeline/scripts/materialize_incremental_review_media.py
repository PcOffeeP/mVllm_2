#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Materialize only selected incremental-review media in a versioned directory.

Run this on the training computer.  It never writes ``data/03_subvideos`` or
``data/04_frames`` and never changes the historical queue or decisions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.scripts import subvideo_builder as builder


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _same_ratio(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) < 1e-8
    except (TypeError, ValueError):
        return False


def _match_candidate(old: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match a regenerated candidate to an old queue record.

    Adaptive focus IDs include their calculated duration and can legitimately
    change after an event-frame correction, so they fall back to crop type and
    event-position ratio.
    """
    old_id = old["subvideo_id"]
    for candidate in candidates:
        if candidate.get("subvideo_id") == old_id:
            return candidate
    same_crop = [item for item in candidates if item.get("crop_type") == old.get("crop_type")]
    ratio_matches = [item for item in same_crop if _same_ratio(item.get("event_position_ratio"), old.get("event_position_ratio"))]
    if len(ratio_matches) == 1:
        return ratio_matches[0]
    if old.get("crop_type", "").startswith("full") and len(same_crop) == 1:
        return same_crop[0]
    return None


def materialize_incremental_review_media(
    queue_path: Path,
    video_meta_path: Path,
    output_root: Path,
    output_metadata: Path,
    report_path: Path,
    model: str,
    reasons: set[str] | None = None,
    skip_healthcheck: bool = False,
) -> dict[str, Any]:
    queue_payload = _load(queue_path)
    queue_info = queue_payload.get("incremental_review_queue", {})
    queue_subvideos = queue_payload.get("subvideos", [])
    if not isinstance(queue_info, dict) or not isinstance(queue_subvideos, list):
        raise ValueError("输入不是有效的增量复审队列 metadata")
    records = {record["video_id"]: record for record in _load(video_meta_path)}

    requested = []
    for subvideo in queue_subvideos:
        review = subvideo.get("incremental_review") or {}
        row_reasons = set(review.get("reasons") or [])
        if reasons is None or row_reasons & reasons:
            requested.append(subvideo)

    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for subvideo in requested:
        by_source[str(subvideo.get("source_video"))].append(subvideo)

    output_root = output_root.resolve()
    video_dir = output_root / "03_subvideos"
    frame_dir = output_root / "04_frames"
    video_dir.mkdir(parents=True, exist_ok=True)
    frame_dir.mkdir(parents=True, exist_ok=True)

    preprocessor = builder._create_preprocessor("minicpm", builder.VIDEO_MAXLEN, model)
    if not skip_healthcheck and not preprocessor.healthcheck():
        info = preprocessor.get_info()
        raise RuntimeError(f"预处理器健康检查失败: {info.name} ({info.backend})")

    old_video_dir, old_frame_dir = builder.SUBVIDEO_DIR_DEFAULT, builder.FRAME_DIR_DEFAULT
    builder.SUBVIDEO_DIR_DEFAULT, builder.FRAME_DIR_DEFAULT = video_dir, frame_dir
    generated: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        for source_video, old_records in sorted(by_source.items()):
            record = records.get(source_video)
            if record is None:
                for old in old_records:
                    failures.append({"subvideo_id": old["subvideo_id"], "reason": "source_video_not_in_video_meta"})
                continue
            split_info = {
                "split": old_records[0].get("split"),
                "fold": old_records[0].get("fold"),
                "fold_assignments": old_records[0].get("fold_assignments", []),
            }
            candidates = builder.build_subvideos_for_record(
                record, split_info, generate_media=False, extract_frames=False, preprocessor=preprocessor
            )
            for old in old_records:
                candidate = _match_candidate(old, candidates)
                if candidate is None:
                    failures.append({"subvideo_id": old["subvideo_id"], "reason": "no_matching_candidate_after_source_update"})
                    continue
                target = builder._sample_candidate_for_output(candidate, output_root)
                try:
                    materialized = builder._generate_media_for_candidate(
                        target, record, frame_dir, extract_frames=True, preprocessor=preprocessor
                    )
                except Exception as exc:
                    failures.append({"subvideo_id": old["subvideo_id"], "reason": f"media_generation_failed: {exc}"})
                    continue
                generated_media_id = materialized["subvideo_id"]
                materialized["subvideo_id"] = old["subvideo_id"]
                materialized["incremental_review"] = dict(old.get("incremental_review") or {})
                materialized["incremental_review"]["generated_media_subvideo_id"] = generated_media_id
                materialized["incremental_review"]["media_root"] = str(output_root)
                generated.append(materialized)
    finally:
        builder.SUBVIDEO_DIR_DEFAULT, builder.FRAME_DIR_DEFAULT = old_video_dir, old_frame_dir

    output_payload = {
        "incremental_review_queue": {
            **queue_info,
            "materialized_from_queue": str(queue_path),
            "media_root": str(output_root),
            "generated_count": len(generated),
            "failure_count": len(failures),
        },
        "subvideos": generated,
    }
    output_metadata.parent.mkdir(parents=True, exist_ok=True)
    output_metadata.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"generated": [item["subvideo_id"] for item in generated], "failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"requested": len(requested), "generated": len(generated), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="仅生成增量复审队列的媒体与帧图")
    parser.add_argument("--round", required=True, help="本轮标识，如 round_01；多轮流程必须显式指定")
    parser.add_argument("--queue", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--video-meta", type=Path, default=PROJECT_ROOT / "data/07_metadata/video_meta.json")
    parser.add_argument("--output-root", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--output-metadata", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--report", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--model", default="models/minicpmv4_5")
    parser.add_argument("--reasons", nargs="+", default=["baseline_needs_regenerate"], help="默认只生成 needs_regenerate；传入 approved_interval_conflict 可扩展")
    parser.add_argument("--skip-healthcheck", action="store_true")
    args = parser.parse_args()
    metadata_round_dir = PROJECT_ROOT / "data/07_metadata/incremental_review" / args.round
    media_round_dir = PROJECT_ROOT / "data/08_incremental_review" / args.round
    summary = materialize_incremental_review_media(
        queue_path=args.queue or metadata_round_dir / "incremental_review_queue_metadata.json",
        video_meta_path=args.video_meta,
        output_root=args.output_root or media_round_dir,
        output_metadata=args.output_metadata or metadata_round_dir / f"incremental_review_{args.round}_metadata.json",
        report_path=args.report or metadata_round_dir / f"incremental_review_{args.round}_report.json",
        model=args.model,
        reasons=set(args.reasons) if args.reasons else None,
        skip_healthcheck=args.skip_healthcheck,
    )
    print(f"增量媒体生成完成: 请求 {summary['requested']}，成功 {summary['generated']}，失败 {len(summary['failures'])}")
    return 0 if not summary["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
