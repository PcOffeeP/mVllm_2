#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare an immutable, queue-only metadata package for incremental review.

The script never changes baseline decisions, media, source labels, or splits.
It produces a small metadata file for the review UI and a CSV manifest that can
be taken to the training computer where queue media is materialized.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATUS_APPROVED = "approved"
STATUS_NEEDS_REGENERATE = "needs_regenerate"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _subvideos(payload: Any) -> list[dict[str, Any]]:
    records = payload.get("subvideos", []) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("metadata 的 subvideos 必须是列表")
    return records


def _decisions_by_id(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    payload = _load_json(path)
    records = payload.get("decisions", []) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("decisions 必须是列表")
    mapping: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("subvideo_id"), str):
            raise ValueError("决策记录缺少 subvideo_id")
        sid = record["subvideo_id"]
        if sid in mapping:
            raise ValueError(f"重复决策 subvideo_id: {sid}")
        mapping[sid] = record
    return records, mapping


def _event_frame(video: dict[str, Any]) -> int | None:
    value = video.get("event_frame_effective")
    if value is None:
        value = video.get("event_frame_original")
    return value if isinstance(value, int) else None


def _compute_interval(subvideo: dict[str, Any], event_frame: int | None) -> list[int] | None:
    mapping = subvideo.get("actual_frame_mapping") or subvideo.get("sampled_frames") or []
    originals = [frame.get("original_frame") for frame in mapping if isinstance(frame, dict)]
    if event_frame is None or len(originals) < 2 or any(value is None for value in originals):
        return None
    if event_frame <= originals[0] or event_frame > originals[-1]:
        return None
    for index in range(len(originals) - 1):
        if originals[index] < event_frame <= originals[index + 1]:
            return [index, index + 1]
    return None


def prepare_incremental_review_queue(
    metadata_path: Path,
    decisions_path: Path,
    video_meta_path: Path,
    output_metadata: Path,
    output_csv: Path,
    include_approved_interval_conflicts: bool = False,
) -> dict[str, Any]:
    metadata_payload = _load_json(metadata_path)
    subvideos = _subvideos(metadata_payload)
    _, decisions = _decisions_by_id(decisions_path)
    video_meta = {record["video_id"]: record for record in _load_json(video_meta_path)}
    by_id = {record.get("subvideo_id"): record for record in subvideos if isinstance(record, dict)}

    selected: dict[str, list[str]] = {}
    for sid, decision in decisions.items():
        if decision.get("status") == STATUS_NEEDS_REGENERATE:
            selected.setdefault(sid, []).append("baseline_needs_regenerate")

        if not include_approved_interval_conflicts or decision.get("status") != STATUS_APPROVED:
            continue
        corrected = decision.get("corrected_labels") or {}
        original = decision.get("original_labels") or {}
        if corrected.get("fracture_between") == original.get("fracture_between"):
            continue
        subvideo = by_id.get(sid)
        if not isinstance(subvideo, dict):
            raise ValueError(f"决策引用的子视频不在 metadata 中: {sid}")
        source = video_meta.get(subvideo.get("source_video"), {})
        if _compute_interval(subvideo, _event_frame(source)) != corrected.get("fracture_between"):
            selected.setdefault(sid, []).append("approved_interval_conflict")

    queue_subvideos: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    for sid in sorted(selected):
        subvideo = by_id.get(sid)
        if not isinstance(subvideo, dict):
            raise ValueError(f"复审队列 ID 不在 metadata 中: {sid}")
        baseline = decisions[sid]
        record = dict(subvideo)
        record["incremental_review"] = {
            "reasons": selected[sid],
            "baseline_decision": baseline,
            "baseline_status": baseline.get("status"),
        }
        queue_subvideos.append(record)
        csv_rows.append({
            "subvideo_id": sid,
            "source_video": subvideo.get("source_video"),
            "crop_type": subvideo.get("crop_type"),
            "baseline_status": baseline.get("status"),
            "queue_reasons": ";".join(selected[sid]),
            "video_path": subvideo.get("video_path"),
            "frame_count": len(subvideo.get("actual_frame_mapping") or subvideo.get("sampled_frames") or []),
        })

    queue_payload = {
        "incremental_review_queue": {
            "schema_version": 1,
            "queue_ids": sorted(selected),
            "selection_counts": dict(Counter(reason for reasons in selected.values() for reason in reasons)),
            "input_sha256": {
                "metadata": _sha256(metadata_path),
                "baseline_decisions": _sha256(decisions_path),
                "video_meta": _sha256(video_meta_path),
            },
            "include_approved_interval_conflicts": include_approved_interval_conflicts,
            "media_contract": "Queue media must be generated on the training computer into a versioned directory before UI review.",
        },
        "subvideos": queue_subvideos,
    }
    output_metadata.parent.mkdir(parents=True, exist_ok=True)
    output_metadata.write_text(json.dumps(queue_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]) if csv_rows else ["subvideo_id"])
        writer.writeheader()
        writer.writerows(csv_rows)
    return {"queue_count": len(queue_subvideos), "selection_counts": queue_payload["incremental_review_queue"]["selection_counts"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成不覆盖历史决策的增量复审队列")
    parser.add_argument("--round", required=True, help="本轮标识，如 round_01；多轮流程必须显式指定")
    parser.add_argument("--metadata", type=Path, default=PROJECT_ROOT / "data/07_metadata/subvideos_meta.json")
    parser.add_argument("--decisions", type=Path, default=PROJECT_ROOT / "data/07_metadata/review_decisions/subvideo_train_review_decisions.json")
    parser.add_argument("--video-meta", type=Path, default=PROJECT_ROOT / "data/07_metadata/video_meta.json")
    parser.add_argument("--output-metadata", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--output-csv", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--include-approved-interval-conflicts", action="store_true")
    args = parser.parse_args()
    round_dir = PROJECT_ROOT / "data/07_metadata/incremental_review" / args.round
    summary = prepare_incremental_review_queue(
        metadata_path=args.metadata,
        decisions_path=args.decisions,
        video_meta_path=args.video_meta,
        output_metadata=args.output_metadata or round_dir / "incremental_review_queue_metadata.json",
        output_csv=args.output_csv or round_dir / "incremental_review_queue.csv",
        include_approved_interval_conflicts=args.include_approved_interval_conflicts,
    )
    print(f"写出增量复审队列: {summary['queue_count']} 条; {summary['selection_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
