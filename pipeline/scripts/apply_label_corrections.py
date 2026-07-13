#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将审查后的修正标签正式覆盖为子视频标签，生成 ``subvideos_meta.label_reviewed.json``。

用途：
    作为 ``apply_review_decisions.py`` 的下游步骤，读取 ``subvideos_meta.reviewed.json``，
    对 ``approved`` 样本把 ``corrected_labels`` 正式覆盖到子视频标签字段，
    输出可供 ``training_sample_builder.py`` 直接使用的最终 metadata。

典型流程：
    subvideos_meta.json
    -> apply_review_decisions.py
    -> subvideos_meta.reviewed.json
    -> apply_label_corrections.py
    -> subvideos_meta.label_reviewed.json
    -> training_sample_builder.py

运行示例：
    python pipeline/scripts/apply_label_corrections.py \
        --metadata data/07_metadata/subvideos_meta.reviewed.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

REVIEWED_META_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.reviewed.json"
LABEL_REVIEWED_META_DEFAULT = (
    PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.label_reviewed.json"
)

STATUS_APPROVED = "approved"
STATUS_DROPPED = "dropped"


def _is_valid_subvideo_id(sid: Any) -> bool:
    """subvideo_id 必须是长度大于 0 的字符串，且不能是占位符。"""
    return isinstance(sid, str) and bool(sid) and sid != "<unknown>"


def _validate_excluded_subvideos(excluded_subvideos: list[dict[str, Any]]) -> None:
    """在写出 label_reviewed metadata 前检查 excluded_subvideos 每一项都是对象且 review_status == dropped。

    非对象、缺失 subvideo_id/review_status、subvideo_id 无效、或 review_status 不是 dropped 都直接失败，
    并列出所有问题项及其原因，避免非法记录被静默忽略。
    """
    errors: list[str] = []
    for rec in excluded_subvideos:
        if not isinstance(rec, dict):
            errors.append(f"非对象项: {rec!r}")
            continue
        sid = rec.get("subvideo_id", "<unknown>")
        if "subvideo_id" not in rec:
            errors.append(f"缺少 subvideo_id: {rec!r}")
        elif not _is_valid_subvideo_id(sid):
            errors.append(
                f"{sid!r}: subvideo_id 无效，必须是长度大于 0 的字符串且不能为 <unknown>"
            )
        if "review_status" not in rec:
            errors.append(f"{sid}: 缺少 review_status")
        elif rec["review_status"] != STATUS_DROPPED:
            errors.append(
                f"{sid}: review_status={rec['review_status']!r} 不是 dropped"
            )

    if errors:
        details = "; ".join(errors)
        raise ValueError(
            f"label_reviewed 导出被阻塞：excluded_subvideos 中存在 {len(errors)} 条非法记录：{details}"
        )


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


def _derive_output_path(metadata_path: Path, output_override: Path | None) -> Path:
    """默认输出为 ``subvideos_meta.label_reviewed.json``。"""
    if output_override is not None:
        return output_override
    if metadata_path.name == "subvideos_meta.reviewed.json":
        return metadata_path.parent / "subvideos_meta.label_reviewed.json"
    return metadata_path.parent / f"{metadata_path.stem}.label_reviewed.json"


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


def _find_corrected_labels(
    sub: dict[str, Any], decisions_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """从子视频 metadata 或 review_decisions 中查找 corrected_labels。"""
    # 优先使用 metadata 中已经写入的 corrected_labels（若存在）
    if "corrected_labels" in sub:
        return sub["corrected_labels"]

    sid = sub.get("subvideo_id")
    if not isinstance(sid, str) or not sid:
        return None

    decision = decisions_by_id.get(sid)
    if not isinstance(decision, dict):
        return None

    return decision.get("corrected_labels")


def apply_label_corrections(
    metadata_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """应用修正标签并写出 label_reviewed metadata。"""
    if not metadata_path.exists():
        raise FileNotFoundError(f"输入 metadata 不存在: {metadata_path}")

    subvideos, top_level = _load_subvideos(metadata_path)

    # 从顶层 review_decisions 构建 decision 映射，方便查找 corrected_labels
    decisions_payload = top_level.get("review_decisions", {})
    decisions_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(decisions_payload, dict):
        raw_decisions = decisions_payload.get("decisions", [])
    else:
        raw_decisions = []
    if isinstance(raw_decisions, list):
        for rec in raw_decisions:
            if isinstance(rec, dict) and isinstance(rec.get("subvideo_id"), str):
                decisions_by_id[rec["subvideo_id"]] = rec

    approved_subvideos: list[dict[str, Any]] = []
    excluded_subvideos: list[dict[str, Any]] = []
    validation_errors: list[str] = []
    corrected_count = 0
    skipped_count = 0

    for sub in subvideos:
        if not isinstance(sub, dict):
            raise ValueError(f"{metadata_path}: subvideos 列表中存在非 dict 元素")
        sid = sub.get("subvideo_id")
        review_status = sub.get("review_status")
        if review_status != STATUS_APPROVED:
            if not _is_valid_subvideo_id(sid):
                validation_errors.append(
                    f"{sid!r}: subvideo_id 无效，无法生成合法的 excluded_subvideos"
                )
                continue
            excluded_subvideos.append({
                "subvideo_id": sid,
                "review_status": review_status,
                "reason": "not_approved",
                **({"interval_verification": sub["interval_verification"]}
                   if isinstance(sub.get("interval_verification"), dict) else {}),
            })
            skipped_count += 1
            continue

        corrected_labels = _find_corrected_labels(sub, decisions_by_id)
        if corrected_labels is not None:
            _apply_corrected_labels(sub, corrected_labels)
            corrected_count += 1
        else:
            skipped_count += 1

        # 对 approved 样本强制同步 canonical 字段，确保 downstream 治理逻辑一致
        ftype = sub.get("type")
        if "type" in sub:
            sub["type_canonical"] = ftype
        has_fracture = sub.get("has_fracture")
        if has_fracture is not None:
            sub["has_fracture_canonical"] = has_fracture
        location = sub.get("location")
        if "location" in sub:
            sub["location_canonical"] = location

        approved_subvideos.append(sub)

    if validation_errors:
        details = "; ".join(validation_errors)
        raise ValueError(
            f"label_reviewed 导出被阻塞：发现 {len(validation_errors)} 条子视频无法生成合法的 excluded_subvideos：{details}"
        )

    _validate_excluded_subvideos(excluded_subvideos)

    output_payload = dict(top_level)
    output_payload["subvideos"] = approved_subvideos
    output_payload["excluded_subvideos"] = excluded_subvideos
    output_payload["label_reviewed_at"] = datetime.now(timezone.utc).isoformat()
    output_payload["label_reviewed_by"] = "apply_label_corrections.py"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    return {
        "output_path": str(output_path),
        "total": len(subvideos),
        "approved_output": len(approved_subvideos),
        "corrected": corrected_count,
        "skipped": skipped_count,
        "excluded": len(excluded_subvideos),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将修正标签正式覆盖为子视频标签",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --metadata data/07_metadata/subvideos_meta.reviewed.json

  # 指定输出路径
  %(prog)s --metadata data/07_metadata/subvideos_meta.reviewed.json \\
      --output data/07_metadata/subvideos_meta.label_reviewed.json
        """.strip(),
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=REVIEWED_META_DEFAULT,
        help="reviewed metadata 路径（默认：data/07_metadata/subvideos_meta.reviewed.json）。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出文件路径（默认：data/07_metadata/subvideos_meta.label_reviewed.json）。",
    )
    args = parser.parse_args()

    output_path = _derive_output_path(args.metadata, args.output)

    try:
        summary = apply_label_corrections(
            metadata_path=args.metadata,
            output_path=output_path,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(f"写出: {summary['output_path']}")
    print(f"总计: {summary['total']} 条子视频")
    print(f"  已覆盖修正标签: {summary['corrected']}")
    print(f"  跳过（非 approved 或无 corrected_labels）: {summary['skipped']}")
    print(f"  输出 approved 样本: {summary['approved_output']}")
    print(f"  排除非 approved 样本: {summary['excluded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
