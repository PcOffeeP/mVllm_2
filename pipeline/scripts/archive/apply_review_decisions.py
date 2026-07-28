#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将人工审查决策应用到子视频 metadata，生成 ``subvideos_meta.reviewed.json``。

用途：
    作为审查 UI 的下游步骤，读取 UI 输出的审查决策文件，把 approved/dropped
    等状态写入子视频 metadata，并在 approved 时把修正后的标签覆盖到当前标签。

最终训练导出注意：
    最终用于训练样本导出的 metadata 必须使用 ``--strict``（默认开启）。
    ``--no-strict`` 仅用于中间检查或调试，不应作为训练输入，因为可能包含未审查、
    needs_regenerate 或非法状态样本。

典型流程：
    subvideos_meta.json
    + subvideo_train_review_decisions.json
    -> apply_review_decisions.py
    -> subvideos_meta.reviewed.json
    -> apply_label_corrections.py
    -> subvideos_meta.label_reviewed.json

运行示例：
    python pipeline/scripts/archive/apply_review_decisions.py \
        --metadata data/07_metadata/subvideos_meta.json \
        --decisions data/07_metadata/review_decisions/subvideo_train_review_decisions.json

    # 非严格模式（允许未审查/needs_regenerate 通过）
    python pipeline/scripts/archive/apply_review_decisions.py \
        --metadata data/07_metadata/subvideos_meta.json \
        --decisions data/07_metadata/review_decisions/subvideo_train_review_decisions.json \
        --no-strict
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
METADATA_DEFAULT = PROJECT_ROOT / "data/07_metadata/subvideos_meta.json"
FINAL_DECISIONS_DEFAULT = PROJECT_ROOT / "data/07_metadata/subvideo_train_review_decisions_final.json"
REVIEWED_META_DEFAULT = PROJECT_ROOT / "data/07_metadata/subvideos_meta.reviewed.json"
VIDEO_META_DEFAULT = PROJECT_ROOT / "data/07_metadata/video_meta.json"

STATUS_APPROVED = "approved"
STATUS_DROPPED = "dropped"
STATUS_NEEDS_REGENERATE = "needs_regenerate"
STATUS_UNREVIEWED = "unreviewed"
LEGAL_STATUSES = {STATUS_APPROVED, STATUS_DROPPED, STATUS_NEEDS_REGENERATE}

LABEL_FIELDS = {"has_fracture", "type", "location", "fracture_between"}


def _load_json(path: Path) -> Any:
    """读取 JSON 文件，失败时抛出清晰的错误。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"无法解析 JSON: {path} ({exc})") from exc
    except OSError as exc:
        raise OSError(f"读取文件失败: {path} ({exc})") from exc


def _load_subvideos(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读取子视频 metadata，支持顶层 dict（含 subvideos 字段）或 list。"""
    raw = _load_json(path)
    if isinstance(raw, dict):
        subvideos = raw.get("subvideos", [])
        if not isinstance(subvideos, list):
            raise ValueError(f"{path}: 顶层 'subvideos' 必须是列表")
        return subvideos, raw
    if isinstance(raw, list):
        return raw, {}
    raise ValueError(f"{path}: metadata 必须是 dict 或 list")


def _load_decisions(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """读取审查决策文件，返回 (subvideo_id -> decision, 原始 payload)。"""
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: 决策文件必须是 dict")

    decisions_data = raw.get("decisions", [])
    if not isinstance(decisions_data, (list, dict)):
        raise ValueError(f"{path}: 'decisions' 必须是 list 或 dict")

    mapping: dict[str, dict[str, Any]] = {}
    if isinstance(decisions_data, list):
        for rec in decisions_data:
            if not isinstance(rec, dict):
                raise ValueError(f"{path}: decisions 列表中的元素必须是 dict")
            sid = rec.get("subvideo_id")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"{path}: 决策记录缺少有效的 subvideo_id")
            mapping[sid] = rec
    elif isinstance(decisions_data, dict):
        for sid, rec in decisions_data.items():
            if not isinstance(rec, dict):
                raise ValueError(f"{path}: decisions[{sid}] 必须是 dict")
            if not isinstance(sid, str) or not sid:
                raise ValueError(f"{path}: decisions 的 key 必须是有效的子视频 ID")
            mapping[sid] = rec

    return mapping, raw


def _derive_output_path(metadata_path: Path, output_override: Path | None) -> Path:
    """默认输出为 ``<metadata>.reviewed.json``。"""
    if output_override is not None:
        return output_override
    return metadata_path.parent / f"{metadata_path.stem}.reviewed.json"


def _snapshot_labels(sub: dict[str, Any]) -> dict[str, Any]:
    """提取当前 metadata 中的自动生成标签快照。"""
    return {
        "has_fracture": sub.get("has_fracture_canonical", sub.get("has_fracture")),
        "type": sub.get("type"),
        "location": sub.get("location_canonical", sub.get("location")),
        "fracture_between": sub.get("fracture_between"),
    }


def _apply_corrected_labels(sub: dict[str, Any], corrected_labels: dict[str, Any]) -> None:
    """把 corrected_labels 覆盖到子视频标签字段，同时同步 canonical 字段。"""
    if not corrected_labels:
        return

    has_fracture = corrected_labels.get("has_fracture")
    if "has_fracture" in corrected_labels:
        sub["has_fracture"] = has_fracture
        sub["has_fracture_canonical"] = has_fracture

    ftype = corrected_labels.get("type")
    if "type" in corrected_labels:
        sub["type"] = ftype
        sub["type_canonical"] = ftype

    location = corrected_labels.get("location")
    if "location" in corrected_labels:
        sub["location"] = location
        sub["location_canonical"] = location

    fracture_between = corrected_labels.get("fracture_between")
    if "fracture_between" in corrected_labels:
        sub["fracture_between"] = fracture_between


def _validate_decision(decision: dict[str, Any]) -> str | None:
    """检查单条决策记录是否合法；返回错误信息或 None。"""
    if "status" not in decision:
        return "缺少 status 字段"
    status = decision["status"]
    if status is None:
        return "status 不能为 None"
    if not isinstance(status, str):
        return f"status 必须是字符串，得到 {type(status).__name__}"
    if status not in LEGAL_STATUSES:
        return f"status 必须是 {sorted(LEGAL_STATUSES)} 之一，得到 '{status}'"
    return None


def _effective_labels(decision: dict[str, Any]) -> dict[str, Any]:
    return decision.get("corrected_labels") or decision.get("original_labels") or {}


def _initial_labels(decision: dict[str, Any]) -> dict[str, Any]:
    """Return labels before the baseline or incremental review changed them."""
    baseline = decision.get("baseline_decision")
    return _effective_labels(baseline) if isinstance(baseline, dict) else (decision.get("original_labels") or {})


def _edited_fracture_interval(decision: dict[str, Any]) -> bool:
    return _initial_labels(decision).get("fracture_between") != _effective_labels(decision).get("fracture_between")


def _source_video_id(subvideo_id: str) -> str | None:
    parts = subvideo_id.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 and parts[0] == "video" else None


def _load_mapping_overrides(paths: list[Path]) -> dict[str, tuple[dict[str, Any], str]]:
    """Load actual mappings from selected incremental rounds; last round wins."""
    result: dict[str, tuple[dict[str, Any], str]] = {}
    for path in paths:
        raw = _load_json(path)
        records = raw.get("subvideos", []) if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            raise ValueError(f"{path}: subvideos 必须是列表")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"{path}: subvideos 中存在非对象记录")
            sid = record.get("subvideo_id")
            if isinstance(sid, str) and sid:
                result[sid] = (record, str(path))
    return result


def _interval_bracket(mapping_record: dict[str, Any], interval: Any) -> dict[str, Any] | None:
    if not isinstance(interval, list) or len(interval) != 2 or not all(isinstance(index, int) for index in interval):
        return None
    mapping = mapping_record.get("actual_frame_mapping") or mapping_record.get("sampled_frames") or []
    try:
        left, right = mapping[interval[0]], mapping[interval[1]]
        left_frame, right_frame = left["original_frame"], right["original_frame"]
    except (IndexError, KeyError, TypeError):
        return None
    if not isinstance(left_frame, int) or not isinstance(right_frame, int):
        return None
    return {
        "left_frame_exclusive": left_frame,
        "right_frame_inclusive": right_frame,
        "left_time_seconds": left.get("timestamp"),
        "right_time_seconds": right.get("timestamp"),
    }


def _verify_edited_interval(
    sub: dict[str, Any],
    decision: dict[str, Any],
    source_meta: dict[str, dict[str, Any]],
    mapping_overrides: dict[str, tuple[dict[str, Any], str]],
) -> dict[str, Any] | None:
    """Return rejection evidence, or None when an edited interval is verified."""
    if decision.get("status") != STATUS_APPROVED or not _edited_fracture_interval(decision):
        return None
    sid = decision["subvideo_id"]
    source_id = sub.get("source_video") or _source_video_id(sid)
    reviewed_interval = _effective_labels(decision).get("fracture_between")
    trace: dict[str, Any] = {
        "original_interval": _initial_labels(decision).get("fracture_between"),
        "reviewed_interval": reviewed_interval,
        "source_video": source_id,
    }
    if reviewed_interval is None:
        trace["reason"] = "missing_reviewed_interval"
        return trace
    mapping_record, mapping_source = mapping_overrides.get(sid, (sub, "current_metadata"))
    bracket = _interval_bracket(mapping_record, reviewed_interval)
    trace["mapping_source"] = mapping_source
    trace["reviewed_interval_source_bracket"] = bracket
    if bracket is None:
        trace["reason"] = "invalid_reviewed_interval_or_mapping"
        return trace
    source = source_meta.get(source_id)
    if not source or source.get("has_fracture_canonical") is not True or source.get("event_time_reliable") is not True:
        trace["reason"] = "unverifiable_source_event"
        return trace
    event_frame = source.get("event_frame_effective")
    trace["source_event_frame"] = event_frame
    if not isinstance(event_frame, int):
        trace["reason"] = "missing_source_event_frame"
        return trace
    if bracket["left_frame_exclusive"] < event_frame <= bracket["right_frame_inclusive"]:
        return None
    trace["reason"] = "reviewed_interval_conflicts_source_event"
    return trace


def _apply_decision(
    sub: dict[str, Any],
    decision: dict[str, Any] | None,
    strict: bool,
) -> dict[str, Any] | None:
    """将决策应用到单条子视频记录；返回 blocker（若被阻塞）或 None。"""
    sid = sub.get("subvideo_id", "<unknown>")

    # 断裂前生成的负样本不需要人工审查决策，但仍须在 reviewed metadata
    # 中具有 approved 状态，以满足后续训练导出的统一前置条件。
    if sub.get("crop_type") == "neg_before":
        sub["review_status"] = STATUS_APPROVED
        sub["reviewed_at"] = None
        sub["reviewer_notes"] = "系统默认通过断裂前(neg_before)子视频，无需人工审查"
        sub["original_labels"] = _snapshot_labels(sub)
        return None

    if decision is None:
        if strict:
            return {
                "subvideo_id": sid,
                "reason": "未审查（不存在审查决策记录）",
            }
        sub["review_status"] = STATUS_UNREVIEWED
        sub["reviewed_at"] = None
        sub["reviewer_notes"] = ""
        sub["original_labels"] = _snapshot_labels(sub)
        return None

    validation_error = _validate_decision(decision)
    if validation_error is not None:
        if strict:
            return {
                "subvideo_id": sid,
                "reason": f"非法决策状态: {validation_error}",
            }
        # 非 strict 模式下作为非法状态标记，避免静默吞掉错误
        sub["review_status"] = f"invalid_status({decision.get('status')})"
        sub["reviewed_at"] = decision.get("reviewed_at")
        sub["reviewer_notes"] = decision.get("reviewer_notes", "")
        sub["original_labels"] = decision.get("original_labels") or _snapshot_labels(sub)
        return None

    status = decision["status"]
    reviewed_at = decision.get("reviewed_at")
    reviewer_notes = decision.get("reviewer_notes", "")
    original_labels = decision.get("original_labels") or _snapshot_labels(sub)
    corrected_labels = decision.get("corrected_labels")

    sub["review_status"] = status
    sub["reviewed_at"] = reviewed_at
    sub["reviewer_notes"] = reviewer_notes
    sub["original_labels"] = original_labels

    if status == STATUS_APPROVED:
        if corrected_labels is not None:
            _apply_corrected_labels(sub, corrected_labels)
    elif status == STATUS_DROPPED:
        # 保留原始标签，不应用 corrected_labels
        pass
    elif status == STATUS_NEEDS_REGENERATE:
        if strict:
            return {
                "subvideo_id": sid,
                "reason": f"status={STATUS_NEEDS_REGENERATE}（需要重新生成）",
            }

    return None


def apply_review_decisions(
    metadata_path: Path,
    decisions_path: Path,
    output_path: Path,
    strict: bool = True,
    interval_verification_video_meta_path: Path | None = None,
    interval_mapping_override_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """应用审查决策并写出 reviewed metadata，返回汇总信息。"""
    if not metadata_path.exists():
        raise FileNotFoundError(f"输入 metadata 不存在: {metadata_path}")
    if not decisions_path.exists():
        raise FileNotFoundError(f"决策文件不存在: {decisions_path}")

    subvideos, top_level = _load_subvideos(metadata_path)
    decisions_by_id, decisions_payload = _load_decisions(decisions_path)
    if interval_verification_video_meta_path is None:
        source_meta: dict[str, dict[str, Any]] = {}
        mapping_overrides: dict[str, tuple[dict[str, Any], str]] = {}
    else:
        raw_source_meta = _load_json(interval_verification_video_meta_path)
        if not isinstance(raw_source_meta, list):
            raise ValueError(f"{interval_verification_video_meta_path}: video meta 必须是列表")
        source_meta = {
            row["video_id"]: row for row in raw_source_meta
            if isinstance(row, dict) and isinstance(row.get("video_id"), str)
        }
        mapping_overrides = _load_mapping_overrides(interval_mapping_override_paths or [])

    blockers: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {
        STATUS_APPROVED: 0,
        STATUS_DROPPED: 0,
        STATUS_NEEDS_REGENERATE: 0,
        STATUS_UNREVIEWED: 0,
    }
    interval_filter_counts = {"retained": 0, "dropped": 0}

    for sub in subvideos:
        if not isinstance(sub, dict):
            raise ValueError(f"{metadata_path}: subvideos 列表中存在非 dict 元素")
        sid = sub.get("subvideo_id")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"{metadata_path}: 子视频记录缺少有效的 subvideo_id")

        decision = decisions_by_id.get(sid)
        blocker = _apply_decision(sub, decision, strict=strict)
        if blocker is None and interval_verification_video_meta_path is not None and decision is not None:
            rejection = _verify_edited_interval(sub, decision, source_meta, mapping_overrides)
            if rejection is not None:
                sub["review_status"] = STATUS_DROPPED
                sub["interval_verification"] = rejection
                interval_filter_counts["dropped"] += 1
            elif decision.get("status") == STATUS_APPROVED and _edited_fracture_interval(decision):
                interval_filter_counts["retained"] += 1
        if blocker is not None:
            blockers.append(blocker)
        else:
            status = sub.get("review_status", STATUS_UNREVIEWED)
            status_counts[status] = status_counts.get(status, 0) + 1

    if strict and blockers:
        raise RuntimeError(
            f"严格模式（--strict）下存在 {len(blockers)} 条未处理样本，\n"
            + json.dumps(blockers, ensure_ascii=False, indent=2)
        )

    output_payload = dict(top_level)
    output_payload["subvideos"] = subvideos
    output_payload["review_decisions"] = decisions_payload
    output_payload["review_applied_at"] = datetime.now(timezone.utc).isoformat()
    output_payload["review_applied_by"] = "apply_review_decisions.py"
    if interval_verification_video_meta_path is not None:
        output_payload["interval_verification"] = {
            "rule": "edited fracture_between must bracket the reliable source event frame",
            "video_meta": str(interval_verification_video_meta_path),
            "mapping_overrides": [str(path) for path in interval_mapping_override_paths or []],
            **interval_filter_counts,
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    return {
        "output_path": str(output_path),
        "total": len(subvideos),
        "status_counts": status_counts,
        "blockers": blockers,
        "interval_verification": interval_filter_counts if interval_verification_video_meta_path is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="应用最终人工决策并验证修改过的断裂区间",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s

  # 有重生成媒体时，明确选择对应轮次的实际映射
  %(prog)s --interval-mapping-override \\
      data/07_metadata/incremental_review/round_01/incremental_review_round_01_metadata.json
        """.strip(),
    )
    parser.add_argument("--metadata", type=Path, default=METADATA_DEFAULT,
                        help="默认：data/07_metadata/subvideos_meta.json")
    parser.add_argument("--decisions", type=Path, default=FINAL_DECISIONS_DEFAULT,
                        help="默认：data/07_metadata/subvideo_train_review_decisions_final.json")
    parser.add_argument("--output", type=Path, default=REVIEWED_META_DEFAULT,
                        help="默认：data/07_metadata/subvideos_meta.reviewed.json")
    parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True,
                        help="最终训练必须保持 strict（默认开启）。")
    parser.add_argument("--interval-verification-video-meta", type=Path, default=VIDEO_META_DEFAULT,
                        help="可靠源事件帧 metadata（默认：data/07_metadata/video_meta.json）。")
    parser.add_argument("--interval-mapping-override", type=Path, action="append", default=[],
                        help="需选择的增量轮次实际映射 metadata；可重复传入，后传入优先。")
    args = parser.parse_args()

    try:
        summary = apply_review_decisions(
            metadata_path=args.metadata,
            decisions_path=args.decisions,
            output_path=args.output,
            strict=args.strict,
            interval_verification_video_meta_path=args.interval_verification_video_meta,
            interval_mapping_override_paths=args.interval_mapping_override,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(f"写出: {summary['output_path']}")
    print(f"总计: {summary['total']} 条子视频")
    for status, count in summary["status_counts"].items():
        print(f"  {status}: {count}")
    if summary["interval_verification"] is not None:
        check = summary["interval_verification"]
        print(f"  修改区间验证：保留 {check['retained']}，转 dropped {check['dropped']}")
    if summary["blockers"]:
        print(f"警告: {len(summary['blockers'])} 条样本处于阻塞状态（非 strict 模式已放行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
