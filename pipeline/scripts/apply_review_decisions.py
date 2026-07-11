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
    python pipeline/scripts/apply_review_decisions.py \
        --metadata data/07_metadata/subvideos_meta.json \
        --decisions data/07_metadata/subvideo_train_review_decisions.json

    # 非严格模式（允许未审查/needs_regenerate 通过）
    python pipeline/scripts/apply_review_decisions.py \
        --metadata data/07_metadata/subvideos_meta.json \
        --decisions data/07_metadata/subvideo_train_review_decisions.json \
        --no-strict
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

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
) -> dict[str, Any]:
    """应用审查决策并写出 reviewed metadata，返回汇总信息。"""
    if not metadata_path.exists():
        raise FileNotFoundError(f"输入 metadata 不存在: {metadata_path}")
    if not decisions_path.exists():
        raise FileNotFoundError(f"决策文件不存在: {decisions_path}")

    subvideos, top_level = _load_subvideos(metadata_path)
    decisions_by_id, decisions_payload = _load_decisions(decisions_path)

    blockers: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {
        STATUS_APPROVED: 0,
        STATUS_DROPPED: 0,
        STATUS_NEEDS_REGENERATE: 0,
        STATUS_UNREVIEWED: 0,
    }

    for sub in subvideos:
        if not isinstance(sub, dict):
            raise ValueError(f"{metadata_path}: subvideos 列表中存在非 dict 元素")
        sid = sub.get("subvideo_id")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"{metadata_path}: 子视频记录缺少有效的 subvideo_id")

        decision = decisions_by_id.get(sid)
        blocker = _apply_decision(sub, decision, strict=strict)
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
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将人工审查决策应用到子视频 metadata",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --metadata data/07_metadata/subvideos_meta.json \\
      --decisions data/07_metadata/subvideo_train_review_decisions.json

  # 允许未审查/needs_regenerate 通过（不推荐用于正式导出）
  %(prog)s --metadata data/07_metadata/subvideos_meta.json \\
      --decisions data/07_metadata/subvideo_train_review_decisions.json --no-strict
        """.strip(),
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="原始子视频 metadata 文件路径（如 data/07_metadata/subvideos_meta.json）。",
    )
    parser.add_argument(
        "--decisions",
        type=Path,
        required=True,
        help="审查决策文件路径（如 data/07_metadata/subvideo_train_review_decisions.json）。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出文件路径（默认：<metadata>.reviewed.json）。",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="严格模式：存在未审查或 needs_regenerate/非法状态样本时退出（默认开启）。"
             "最终训练导出必须保持开启；--no-strict 仅用于中间检查。",
    )
    args = parser.parse_args()

    output_path = _derive_output_path(args.metadata, args.output)

    try:
        summary = apply_review_decisions(
            metadata_path=args.metadata,
            decisions_path=args.decisions,
            output_path=output_path,
            strict=args.strict,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(f"写出: {summary['output_path']}")
    print(f"总计: {summary['total']} 条子视频")
    for status, count in summary["status_counts"].items():
        print(f"  {status}: {count}")
    if summary["blockers"]:
        print(f"警告: {len(summary['blockers'])} 条样本处于阻塞状态（非 strict 模式已放行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
