#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit completed subvideo manual-review decisions before regeneration.

The script is deliberately read-only with respect to the source metadata.  It
creates a JSON report, a human-readable Markdown summary, and CSV queues for
the two items that must be checked before another generation round:

* each approved change to a key label (``has_fracture``, ``type``,
  ``location``), compared with the original video annotation; and
* every changed ``fracture_between`` interval, including the source event time
  and source-frame consistency check.

If the original ``subvideos_meta.json`` is available, pass it with
``--subvideos-meta``.  The script will then recompute a changed interval from
``actual_frame_mapping``.  Without that artifact it never claims that the
subvideo frame interval was verified; it emits an explicit blocking queue.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KEY_LABELS = ("has_fracture", "type", "location")
ALL_LABELS = (*KEY_LABELS, "fracture_between")
LEGAL_STATUSES = {"approved", "dropped", "needs_regenerate"}
FRACTURE_TYPES = {
    "韧性断裂", "脆性断裂", "界面脱粘", "齐根断裂", "爆炸性断裂",
    "半脆半韧断裂", "界面脱粘、齐根断裂", "脆性断裂、齐根断裂",
}
LEGAL_TYPES = FRACTURE_TYPES | {"未断裂", "未夹紧", "视频异常"}
LEGAL_LOCATIONS = {"inside_gauge", "outside_gauge", None}
VIDEO_ID_RE = re.compile(r"^(video_\d+)_")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_video_id(subvideo_id: str) -> str | None:
    match = VIDEO_ID_RE.match(subvideo_id)
    return match.group(1) if match else None


def _normalise_location(value: Any) -> Any:
    return None if value in {"", "N/A", "n/a"} else value


def _number(value: Any) -> float | None:
    if value in {None, "", "N/A", "n/a"}:
        return None
    try:
        return float(str(value).rstrip("s"))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _source_labels(csv_row: dict[str, str]) -> dict[str, Any]:
    raw_has = (csv_row.get("has_fracture") or "").strip().upper()
    return {
        "has_fracture": {"TRUE": True, "FALSE": False}.get(raw_has),
        "type": csv_row.get("断裂模式"),
        "location": _normalise_location(csv_row.get("断裂位置")),
        "event_time": _number(csv_row.get("断裂时间点")),
        "event_frame": _int_or_none(csv_row.get("断裂帧数")),
        "annotation_fps": _number(csv_row.get("视频帧率")),
        "duration": _number(csv_row.get("视频时长")),
        "total_frames": _int_or_none(csv_row.get("视频总帧数")),
    }


def _crop_family(subvideo_id: str) -> str:
    if subvideo_id.endswith("_full"):
        return "full"
    if "_focus_" in subvideo_id:
        return "focus"
    if "_neg_" in subvideo_id or "_negpos_" in subvideo_id or "_neg_pos_" in subvideo_id:
        return "negative"
    return "unknown"


def _compact_notes(note: str) -> str:
    note = "".join((note or "").split())
    if not note:
        return "none"
    if "原视频标记" in note and "未断裂" in note:
        return "source_marked_nonfracture"
    if "未包含断裂" in note or "断裂时刻发生在子视频" in note or "已经断裂" in note:
        return "event_not_visible"
    if "最后一帧" in note or "帧画面" in note:
        return "frame_quality_or_tail_artifact"
    return "other"


def _probe_average_fps(video_path: Path) -> float | None:
    """Return average FPS, not r_frame_rate (unsafe for VFR-style MP4s)."""
    if not video_path.exists():
        return None
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate,nb_frames,duration",
        "-of", "json", str(video_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        stream = (json.loads(result.stdout).get("streams") or [{}])[0]
        raw = stream.get("avg_frame_rate")
        if isinstance(raw, str) and "/" in raw:
            numerator, denominator = raw.split("/", 1)
            value = float(numerator) / float(denominator)
            return value if value > 0 else None
        return _number(raw)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def _subvideos_by_id(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    raw = _load_json(path)
    records = raw.get("subvideos", []) if isinstance(raw, dict) else raw
    return {record["subvideo_id"]: record for record in records if isinstance(record, dict) and record.get("subvideo_id")}


def _recompute_interval(subvideo: dict[str, Any], event_frame: int | None) -> list[int] | None:
    if event_frame is None:
        return None
    mapping = subvideo.get("actual_frame_mapping") or subvideo.get("sampled_frames") or []
    originals = [frame.get("original_frame") for frame in mapping if isinstance(frame, dict)]
    if len(originals) < 2 or any(value is None for value in originals):
        return None
    if event_frame <= originals[0] or event_frame > originals[-1]:
        return None
    for index in range(len(originals) - 1):
        if originals[index] < event_frame <= originals[index + 1]:
            return [index, index + 1]
    return None


def _interval_bounds(subvideo: dict[str, Any], interval: list[int] | None) -> dict[str, Any] | None:
    """Return the original-frame/time bracket represented by an interval."""
    if interval is None:
        return None
    mapping = subvideo.get("actual_frame_mapping") or subvideo.get("sampled_frames") or []
    try:
        left, right = mapping[interval[0]], mapping[interval[1]]
        return {
            "left_frame_exclusive": left["original_frame"],
            "right_frame_inclusive": right["original_frame"],
            "left_time_seconds": left.get("timestamp"),
            "right_time_seconds": right.get("timestamp"),
        }
    except (IndexError, KeyError, TypeError):
        return None


def _changed(decision: dict[str, Any], field: str) -> bool:
    corrected = decision.get("corrected_labels")
    if not isinstance(corrected, dict) or field not in corrected:
        return False
    return corrected[field] != (decision.get("original_labels") or {}).get(field)


def audit_review_decisions(
    decisions_path: Path,
    annotations_path: Path,
    video_meta_path: Path,
    output_dir: Path,
    subvideos_meta_path: Path | None = None,
) -> dict[str, Any]:
    raw = _load_json(decisions_path)
    decisions = raw.get("decisions", []) if isinstance(raw, dict) else []
    if not isinstance(decisions, list):
        raise ValueError("decisions must be a list")
    with annotations_path.open(encoding="utf-8", newline="") as handle:
        source_rows = {row["id"]: row for row in csv.DictReader(handle)}
    video_meta = {row["video_id"]: row for row in _load_json(video_meta_path)}
    subvideos = _subvideos_by_id(subvideos_meta_path)

    duplicate_ids = [item for item, count in Counter(d.get("subvideo_id") for d in decisions).items() if count > 1]
    invalid_statuses = [d.get("subvideo_id") for d in decisions if d.get("status") not in LEGAL_STATUSES]
    status_counts = Counter(d.get("status") for d in decisions)
    note_counts = Counter(_compact_notes(d.get("reviewer_notes", "")) for d in decisions)
    by_video: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in decisions:
        video_id = _source_video_id(str(decision.get("subvideo_id", "")))
        if video_id:
            by_video[video_id].append(decision)

    key_changes: list[dict[str, Any]] = []
    interval_changes: list[dict[str, Any]] = []
    changed_counts = Counter()
    source_conflict_video_ids: set[str] = set()
    invalid_corrected_values: list[dict[str, Any]] = []

    for decision in decisions:
        if decision.get("status") != "approved":
            continue
        subvideo_id = decision.get("subvideo_id", "")
        video_id = _source_video_id(subvideo_id)
        source = _source_labels(source_rows[video_id]) if video_id in source_rows else {}
        governed_source = video_meta.get(video_id, {})
        effective_event_frame = governed_source.get("event_frame_effective")
        if effective_event_frame is None:
            effective_event_frame = source.get("event_frame")
        source_event_verifiable = (
            effective_event_frame is not None
            and governed_source.get("event_time_reliable") is True
            and governed_source.get("has_fracture_canonical") is True
        )
        crop_family = _crop_family(subvideo_id)
        corrected = decision.get("corrected_labels") or {}
        original = decision.get("original_labels") or {}

        for field in KEY_LABELS:
            if not _changed(decision, field):
                continue
            changed_counts[field] += 1
            source_value = source.get(field)
            corrected_value = corrected.get(field)
            needs_source_confirmation = crop_family in {"full", "focus"} and corrected_value != source_value
            if needs_source_confirmation:
                source_conflict_video_ids.add(video_id)
            row = {
                "subvideo_id": subvideo_id,
                "source_video": video_id,
                "crop_family": crop_family,
                "field": field,
                "original_subvideo_value": original.get(field),
                "reviewed_value": corrected_value,
                "original_source_value": source_value,
                "needs_source_confirmation": needs_source_confirmation,
                "reviewer_notes": decision.get("reviewer_notes", ""),
            }
            key_changes.append(row)
            if ((field == "location" and corrected_value not in LEGAL_LOCATIONS)
                    or (field == "type" and corrected_value not in LEGAL_TYPES)):
                invalid_corrected_values.append({
                    **row,
                    "invalid_value_reason": (
                        "invalid_location" if field == "location" else "invalid_type"
                    ),
                })

        if _changed(decision, "fracture_between"):
            changed_counts["fracture_between"] += 1
            subvideo = subvideos.get(subvideo_id)
            recomputed = _recompute_interval(subvideo, effective_event_frame) if subvideo else None
            original_interval = original.get("fracture_between")
            reviewed_interval = corrected.get("fracture_between")
            if not subvideo:
                verification = "blocked_missing_subvideos_meta"
            elif not source_event_verifiable:
                verification = "unverifiable_source_event"
            elif recomputed == reviewed_interval:
                verification = "reviewed_matches_current_source_event"
            elif recomputed == original_interval:
                verification = "manual_override_conflicts_current_source_event"
            else:
                verification = "neither_interval_matches_current_source_event"
            interval_changes.append({
                "subvideo_id": subvideo_id,
                "source_video": video_id,
                "crop_family": crop_family,
                "original_interval": original_interval,
                "reviewed_interval": reviewed_interval,
                "source_event_time_seconds": governed_source.get("event_time", source.get("event_time")),
                "source_event_frame": effective_event_frame,
                "source_event_frame_origin": (
                    "video_meta.event_frame_effective"
                    if governed_source.get("event_frame_effective") is not None else "annotations.event_frame"
                ),
                "source_event_reliable": source_event_verifiable,
                "source_annotation_fps": source.get("annotation_fps"),
                "source_frame_time_seconds": (
                    source["event_frame"] / source["annotation_fps"]
                    if source.get("event_frame") is not None and source.get("annotation_fps") else None
                ),
                "recomputed_interval": recomputed,
                "original_interval_bounds": _interval_bounds(subvideo, original_interval) if subvideo else None,
                "reviewed_interval_bounds": _interval_bounds(subvideo, reviewed_interval) if subvideo else None,
                "verification": verification,
            })

    interval_source_queue: list[dict[str, Any]] = []
    grouped_intervals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in interval_changes:
        grouped_intervals[item["source_video"]].append(item)
    for video_id, rows in sorted(grouped_intervals.items()):
        reviewed_bounds = [item["reviewed_interval_bounds"] for item in rows if item["reviewed_interval_bounds"]]
        null_reviews = [item for item in rows if item["reviewed_interval"] is None]
        lower = max((item["left_frame_exclusive"] for item in reviewed_bounds), default=None)
        upper = min((item["right_frame_inclusive"] for item in reviewed_bounds), default=None)
        bounds_intersect = lower is not None and upper is not None and lower < upper
        if any(item["verification"] == "unverifiable_source_event" for item in rows):
            next_action = "recheck_original_video_presence_and_event_frame"
        elif null_reviews:
            next_action = "recheck_original_video_presence_and_event_frame"
        elif not bounds_intersect:
            next_action = "recheck_original_video_and_reconcile_inconsistent_manual_intervals"
        elif any(item["verification"] == "manual_override_conflicts_current_source_event" for item in rows):
            next_action = "reannotate_source_event_frame_within_manual_bracket_then_regenerate_affected_focus"
        else:
            next_action = "confirm_manual_source_label_change_before_accepting"
        interval_source_queue.append({
            "source_video": video_id,
            "changed_interval_count": len(rows),
            "manual_interval_count": len(reviewed_bounds),
            "manual_cleared_interval_count": len(null_reviews),
            "current_source_event_frame": rows[0]["source_event_frame"],
            "manual_event_frame_lower_exclusive": lower,
            "manual_event_frame_upper_inclusive": upper,
            "manual_brackets_intersect": bounds_intersect,
            "verification_counts": dict(Counter(item["verification"] for item in rows)),
            "next_action": next_action,
        })

    reviewed_ids = {str(decision.get("subvideo_id")) for decision in decisions}
    metadata_only = [subvideo for sid, subvideo in subvideos.items() if sid not in reviewed_ids]
    auto_approved_neg_before = [subvideo for subvideo in metadata_only if subvideo.get("crop_type") == "neg_before"]
    unexpected_unreviewed = [subvideo for subvideo in metadata_only if subvideo.get("crop_type") != "neg_before"]

    temporal_checks: list[dict[str, Any]] = []
    for video_id, row in source_rows.items():
        source = _source_labels(row)
        event_time, event_frame, fps = source["event_time"], source["event_frame"], source["annotation_fps"]
        if event_time is None or event_frame is None or not fps:
            continue
        frame_time = event_frame / fps
        delta = abs(event_time - frame_time)
        # One source-frame is the normal rounding tolerance; above that merits
        # original-video re-review, never an automatic correction.
        temporal_checks.append({
            "source_video": video_id,
            "event_time_seconds": event_time,
            "event_frame": event_frame,
            "annotation_fps": fps,
            "frame_time_seconds": frame_time,
            "absolute_delta_seconds": delta,
            "outside_one_frame_tolerance": delta > (1 / fps + 1e-9),
            "average_fps": _probe_average_fps(PROJECT_ROOT / str(video_meta.get(video_id, {}).get("video_path", ""))),
        })

    regenerate_by_video = []
    for video_id, rows in sorted(by_video.items()):
        needs = [row for row in rows if row.get("status") == "needs_regenerate"]
        if not needs:
            continue
        note_categories = sorted({_compact_notes(row.get("reviewer_notes", "")) for row in needs})
        regenerate_by_video.append({
            "source_video": video_id,
            "decision_count": len(rows),
            "needs_regenerate_count": len(needs),
            "needs_regenerate_ratio": round(len(needs) / len(rows), 4),
            "all_reviewed_subvideos_need_regeneration": len(needs) == len(rows),
            "reason_categories": note_categories,
            "must_recheck_original_event": "event_not_visible" in note_categories,
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "inputs": {
            "decisions": str(decisions_path), "annotations": str(annotations_path),
            "video_meta": str(video_meta_path), "subvideos_meta": str(subvideos_meta_path) if subvideos_meta_path else None,
        },
        "integrity": {
            "decision_count": len(decisions), "unique_subvideo_count": len({d.get("subvideo_id") for d in decisions}),
            "duplicate_subvideo_ids": duplicate_ids, "invalid_status_subvideo_ids": invalid_statuses,
            "metadata_subvideo_count": len(subvideos) if subvideos else None,
            "metadata_only_count": len(metadata_only) if subvideos else None,
            "auto_approved_neg_before_count": len(auto_approved_neg_before) if subvideos else None,
            "unexpected_unreviewed_subvideo_ids": [subvideo["subvideo_id"] for subvideo in unexpected_unreviewed],
        },
        "status_counts": dict(sorted(status_counts.items())),
        "note_category_counts": dict(sorted(note_counts.items())),
        "changed_field_counts": dict(sorted(changed_counts.items())),
        "key_label_changes": key_changes,
        "fracture_interval_changes": interval_changes,
        "fracture_interval_source_queue": interval_source_queue,
        "source_reannotation_required_video_ids": sorted(source_conflict_video_ids),
        "invalid_corrected_values": invalid_corrected_values,
        "regeneration_by_source_video": regenerate_by_video,
        "source_time_frame_checks": temporal_checks,
        "source_time_frame_recheck_video_ids": sorted(
            row["source_video"] for row in temporal_checks if row["outside_one_frame_tolerance"]
        ),
        "limitations": [
            "A changed subvideo interval can be recomputed only when subvideos_meta.json with actual_frame_mapping is supplied.",
            "This audit checks metadata consistency; visual confirmation of the fracture instant remains a human task on the original video.",
            "Average FPS is diagnostic only. The source annotation FPS remains the conversion basis unless the original video is re-annotated.",
        ],
    }
    (output_dir / "review_decision_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_csv(name: str, rows: list[dict[str, Any]]) -> None:
        path = output_dir / name
        fields = sorted({key for row in rows for key in row})
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    write_csv("review_key_label_change_queue.csv", key_changes)
    write_csv("review_fracture_interval_queue.csv", interval_changes)
    write_csv("review_fracture_interval_source_queue.csv", interval_source_queue)
    write_csv("review_regeneration_queue.csv", regenerate_by_video)
    write_csv("review_source_time_frame_queue.csv", temporal_checks)

    time_outliers = [item for item in temporal_checks if item["outside_one_frame_tolerance"]]
    markdown = [
        "# 人工审查决策审计报告", "",
        f"- 决策：{len(decisions)} 条；通过：{status_counts['approved']}；需重生成：{status_counts['needs_regenerate']}；丢弃：{status_counts['dropped']}。",
        f"- 关键标签变更：has_fracture {changed_counts['has_fracture']}，type {changed_counts['type']}，location {changed_counts['location']}。",
        f"- 断裂帧区间变更：{len(interval_changes)} 条；人工区间与当前源事件帧冲突：{sum(x['verification'] == 'manual_override_conflicts_current_source_event' for x in interval_changes)}；可验证且一致：{sum(x['verification'] == 'reviewed_matches_current_source_event' for x in interval_changes)}；源事件本身不可验证：{sum(x['verification'] == 'unverifiable_source_event' for x in interval_changes)}。",
        f"- full/focus 子视频中与原始视频标签冲突、需回查原标注的视频：{len(source_conflict_video_ids)} 个。", 
        f"- 原始事件时间与帧号换算相差超过一帧的视频：{len(time_outliers)} 个。",
        "", "## 必须人工处理", "",
        "1. 逐项处理 `review_key_label_change_queue.csv` 中 `needs_source_confirmation=true` 的记录；确认后更新原始 CSV 或撤销子视频修正。",
        "2. 处理 `review_fracture_interval_source_queue.csv`：它将人工区间还原为原始帧范围；先在原视频中确定精确首断帧，再更新源标注并重新生成受影响 focus 子视频。",
        "3. `review_regeneration_queue.csv` 中 `must_recheck_original_event=true` 的源视频，须先复核原视频断裂时刻/帧号，再重生成。",
        f"4. 已发现 {len(invalid_corrected_values)} 个非法修正值；不得进入 canonical 标签。",
        "", "## 自动化边界", "",
        "本报告只做可追溯的一致性核验，不从像素自动推断断裂时刻或类型。对于可变帧率风格 MP4，诊断必须使用 average FPS，不能用 r_frame_rate 直接换算。",
    ]
    (output_dir / "review_decision_audit.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="审计已完成的子视频人工审查决策")
    parser.add_argument("--decisions", type=Path, default=PROJECT_ROOT / "data/07_metadata/subvideo_train_review_decisions.json")
    parser.add_argument("--annotations", type=Path, default=PROJECT_ROOT / "data/02_annotations/all_videos_tag.csv")
    parser.add_argument("--video-meta", type=Path, default=PROJECT_ROOT / "data/07_metadata/video_meta.json")
    parser.add_argument("--subvideos-meta", type=Path, default=None, help="可选；提供后可重算 fracture_between")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/07_metadata/review_audit")
    args = parser.parse_args()
    report = audit_review_decisions(args.decisions, args.annotations, args.video_meta, args.output_dir, args.subvideos_meta)
    print(f"审计完成：{report['integrity']['decision_count']} 条决策，报告目录：{args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
