#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人工审核后清洗子视频元数据。

主要规则：
- 读取 ``subvideos_meta.label_reviewed.json`` 中的 ``review_status``。
- ``approved`` 样本进入 ``subvideos_meta.pruned.json``。
- ``dropped`` 样本被剔除，默认不物理删除媒体文件。
- ``needs_regenerate`` / ``unreviewed`` 视为阻塞；默认 ``--strict`` 报错，
  ``--no-strict`` 仅警告并继续剔除阻塞样本。
- 旧版无 ``review_status`` 的 metadata 仍按媒体文件存在性过滤，保持向后兼容。

使用示例：
    python pipeline/scripts/prune_reviewed_subvideos.py

    # 显式指定输入/输出，并删除 dropped 样本的媒体文件
    python pipeline/scripts/prune_reviewed_subvideos.py \
        --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json \
        --output-meta data/07_metadata/subvideos_meta.pruned.json \
        --delete-media

    # 非严格模式：允许未审查/needs_regenerate 通过（仅警告）
    python pipeline/scripts/prune_reviewed_subvideos.py --no-strict
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SUBVIDEOS_META_DEFAULT = (
    PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.label_reviewed.json"
)
OUTPUT_META_DEFAULT = (
    PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.pruned.json"
)
REPORT_DEFAULT = (
    PROJECT_ROOT / "data" / "07_metadata" / "prune_reviewed_subvideos_report.json"
)
FRAME_DIR_DEFAULT = PROJECT_ROOT / "data" / "04_frames"

STATUS_APPROVED = "approved"
STATUS_DROPPED = "dropped"
STATUS_NEEDS_REGENERATE = "needs_regenerate"
STATUS_UNREVIEWED = "unreviewed"


def _resolve_path(rel: str, project_root: Path) -> Path:
    """将元数据中的相对路径解析为绝对路径。"""
    if rel.startswith("data/"):
        return project_root / rel
    return project_root / "data" / rel


def _video_file_valid(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _load_subvideos(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读取子视频元数据，支持 dict 与 list 两种顶层结构。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw.get("subvideos", []), raw
    return raw, {}


def _resolve_video_path(
    sub: dict[str, Any], project_root: Path
) -> tuple[Path, str]:
    """解析子视频 mp4 的绝对路径与相对路径。"""
    subvideo_id = sub.get("subvideo_id", "<unknown>")
    video_path_rel = sub.get("video_path", "")
    if video_path_rel:
        video_path = _resolve_path(video_path_rel, project_root)
    else:
        video_path_rel = f"data/03_subvideos/{subvideo_id}.mp4"
        video_path = project_root / video_path_rel
    return video_path, video_path_rel


def _classify_by_media(
    sub: dict[str, Any],
    frame_dir_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    """对单条无 review_status 的子视频记录按媒体存在性分类。"""
    subvideo_id = sub.get("subvideo_id", "<unknown>")
    source_video = sub.get("source_video", "<unknown>")
    video_path, video_path_rel = _resolve_video_path(sub, project_root)
    frame_dir = frame_dir_root / subvideo_id

    video_file_exists = video_path.exists()
    video_file_valid = _video_file_valid(video_path)
    frame_dir_exists = frame_dir.is_dir() and any(frame_dir.iterdir())

    if video_file_valid and frame_dir_exists:
        status = "kept"
        reason = "both_present"
    elif not video_file_exists and not frame_dir_exists:
        status = "dropped"
        reason = "both_missing"
    elif not video_file_exists:
        status = "dropped"
        reason = "missing_video_review_deleted"
    elif not frame_dir_exists:
        status = "dropped"
        reason = "missing_frames_review_deleted"
    elif not video_file_valid:
        status = "inconsistent"
        reason = "invalid_video"
    else:
        status = "inconsistent"
        reason = "unknown_media_state"

    return {
        "subvideo_id": subvideo_id,
        "source_video": source_video,
        "video_path": video_path_rel,
        "frame_dir": str(frame_dir.relative_to(project_root)),
        "video_exists": video_file_exists,
        "video_valid": video_file_valid,
        "frame_dir_exists": frame_dir_exists,
        "status": status,
        "reason": reason,
        "review_status": None,
    }


def _classify_by_review_status(
    sub: dict[str, Any],
    frame_dir_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    """对单条有 review_status 的子视频记录按审查状态分类。"""
    subvideo_id = sub.get("subvideo_id", "<unknown>")
    source_video = sub.get("source_video", "<unknown>")
    video_path, video_path_rel = _resolve_video_path(sub, project_root)
    frame_dir = frame_dir_root / subvideo_id

    review_status = sub.get("review_status")

    if review_status == STATUS_APPROVED:
        status = "kept"
        reason = "review_approved"
    elif review_status == STATUS_DROPPED:
        status = "dropped"
        reason = "review_dropped"
    elif review_status == STATUS_NEEDS_REGENERATE:
        status = "blocked"
        reason = "review_needs_regenerate"
    elif review_status == STATUS_UNREVIEWED:
        status = "blocked"
        reason = "review_unreviewed"
    elif review_status is None:
        status = "blocked"
        reason = "review_status_none"
    else:
        status = "blocked"
        reason = f"unknown_review_status({review_status})"

    return {
        "subvideo_id": subvideo_id,
        "source_video": source_video,
        "video_path": video_path_rel,
        "frame_dir": str(frame_dir.relative_to(project_root)),
        "video_exists": video_path.exists(),
        "video_valid": _video_file_valid(video_path),
        "frame_dir_exists": frame_dir.is_dir() and any(frame_dir.iterdir()),
        "status": status,
        "reason": reason,
        "review_status": review_status,
    }


def _classify_entry(
    sub: dict[str, Any],
    frame_dir_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    """对单条子视频记录分类：优先使用 review_status，否则回退媒体存在性。"""
    if "review_status" in sub:
        return _classify_by_review_status(sub, frame_dir_root, project_root)
    return _classify_by_media(sub, frame_dir_root, project_root)


def _delete_media(classification: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """物理删除 dropped 样本关联的媒体文件，并返回删除结果。"""
    video_path = project_root / classification["video_path"]
    frame_dir = project_root / classification["frame_dir"]
    deleted: dict[str, bool] = {"video": False, "frame_dir": False}
    try:
        if video_path.exists():
            video_path.unlink()
            deleted["video"] = True
    except OSError:
        pass
    try:
        if frame_dir.exists():
            shutil.rmtree(frame_dir)
            deleted["frame_dir"] = True
    except OSError:
        pass
    return deleted


def prune_reviewed_subvideos(
    subvideos_meta: Path,
    output_meta: Path,
    report_path: Path,
    frame_dir_root: Path = FRAME_DIR_DEFAULT,
    project_root: Path = PROJECT_ROOT,
    allow_partial_report: bool = False,
    delete_media: bool = False,
    strict: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    执行人工审核后的 metadata 清洗。

    返回 (kept_entries, dropped_entries, blocked_or_inconsistent_entries)。
    - ``blocked_or_inconsistent`` 包含 ``needs_regenerate`` / ``unreviewed`` / 非法
      review_status 以及旧版媒体不一致项。
    - 默认 strict=True：存在阻塞项时不写出 output_meta。
    - ``allow_partial_report=True`` 仍对旧版媒体不一致数据生效。
    """
    subvideos, top_level = _load_subvideos(subvideos_meta)

    classifications: list[dict[str, Any]] = []
    for sub in subvideos:
        classifications.append(
            _classify_entry(sub, frame_dir_root, project_root)
        )

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    inconsistent: list[dict[str, Any]] = []
    kept_indices: list[int] = []

    for idx, cls in enumerate(classifications):
        status = cls["status"]
        if status == "kept":
            kept.append(subvideos[idx])
            kept_indices.append(idx)
        elif status == "dropped":
            dropped.append(cls)
        elif status == "blocked":
            blocked.append(cls)
        else:
            inconsistent.append(cls)

    should_write_output = (not blocked or not strict) and (
        not inconsistent or allow_partial_report
    )

    # 按需删除 dropped 样本的媒体文件；仅在流程可以继续时执行，避免在阻塞/不一致
    # 状态下误删数据。
    deleted_records: list[dict[str, Any]] = []
    if delete_media and should_write_output:
        for cls in dropped:
            deleted = _delete_media(cls, project_root)
            deleted_records.append(
                {
                    "subvideo_id": cls["subvideo_id"],
                    "deleted": deleted,
                }
            )

    status_counts: dict[str, int] = {
        "kept": len(kept),
        "dropped": len(dropped),
        "blocked": len(blocked),
        "inconsistent": len(inconsistent),
    }

    report: dict[str, Any] = {
        "input_meta": str(subvideos_meta),
        "output_meta": str(output_meta),
        "strict": strict,
        "delete_media": delete_media,
        "total_entries": len(subvideos),
        "status_counts": status_counts,
        "dropped": dropped,
        "blocked": blocked,
        "inconsistent": inconsistent,
        "kept_subvideo_ids": [sub.get("subvideo_id") for sub in kept],
    }
    if deleted_records:
        report["deleted_media"] = deleted_records

    output_meta.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    should_write_output = (not blocked or not strict) and (
        not inconsistent or allow_partial_report
    )
    if should_write_output:
        output_payload = dict(top_level)
        output_payload["subvideos"] = kept
        output_payload["pruned_at"] = _utc_now()
        output_payload["pruned_by"] = "prune_reviewed_subvideos.py"
        output_payload["strict"] = strict
        output_meta.write_text(
            json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 为保持与旧版调用者的签名兼容，返回 (kept, dropped, blocked_or_inconsistent)，
    # 其中第三项包含审查阻塞项与旧版媒体不一致项。报告里二者仍分别列出。
    blocked_or_inconsistent = blocked + inconsistent

    return kept, dropped, blocked_or_inconsistent


def _utc_now() -> str:
    """返回当前 UTC 时间 ISO 8601 字符串。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="人工审核后清洗子视频元数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s

  # 删除 dropped 样本的媒体文件
  %(prog)s --delete-media

  # 非严格模式：未审查/needs_regenerate 仅警告不阻塞
  %(prog)s --no-strict
        """.strip(),
    )
    parser.add_argument(
        "--subvideos-meta",
        "--input-meta",
        dest="subvideos_meta",
        metavar="PATH",
        type=Path,
        default=SUBVIDEOS_META_DEFAULT,
        help="输入子视频元数据路径（默认：data/07_metadata/subvideos_meta.label_reviewed.json）",
    )
    parser.add_argument(
        "--output-meta",
        type=Path,
        default=OUTPUT_META_DEFAULT,
        help="输出清洗后元数据路径（默认：data/07_metadata/subvideos_meta.pruned.json）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_DEFAULT,
        help="清洗报告输出路径",
    )
    parser.add_argument(
        "--frame-dir",
        type=Path,
        default=FRAME_DIR_DEFAULT,
        help="帧目录根路径（默认：data/04_frames）",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="项目根目录，用于解析相对路径",
    )
    parser.add_argument(
        "--allow-partial-report",
        action="store_true",
        help="存在不一致样本时仍写出仅含 kept 条目的 output_meta",
    )
    parser.add_argument(
        "--delete-media",
        action="store_true",
        help="物理删除 dropped 样本的 mp4 与采样帧目录（默认不删除）",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="严格模式：存在 needs_regenerate/unreviewed/非法 review_status 时退出（默认开启）",
    )
    args = parser.parse_args()

    if not args.subvideos_meta.exists():
        print(f"错误：输入元数据不存在: {args.subvideos_meta}", file=sys.stderr)
        return 2

    kept, dropped, blocked_or_inconsistent = prune_reviewed_subvideos(
        subvideos_meta=args.subvideos_meta,
        output_meta=args.output_meta,
        report_path=args.report,
        frame_dir_root=args.frame_dir,
        project_root=args.project_root,
        allow_partial_report=args.allow_partial_report,
        delete_media=args.delete_media,
        strict=args.strict,
    )

    total = len(kept) + len(dropped) + len(blocked_or_inconsistent)
    print(
        f"扫描 {total} 条样本: 保留 {len(kept)}, 剔除 {len(dropped)}, 阻塞/不一致 {len(blocked_or_inconsistent)}"
    )

    if blocked_or_inconsistent:
        if args.strict:
            print(
                "错误：存在阻塞或不一致样本，必须先完成审查、重新生成或修复媒体",
                file=sys.stderr,
            )
            for item in blocked_or_inconsistent:
                print(
                    f"  - {item['subvideo_id']}: {item['reason']} "
                    f"(review_status={item['review_status']})",
                    file=sys.stderr,
                )
            return 1
        print(
            f"警告：{len(blocked_or_inconsistent)} 条样本处于阻塞/不一致状态（--no-strict 已放行）",
            file=sys.stderr,
        )
        for item in blocked_or_inconsistent:
            print(
                f"  - {item['subvideo_id']}: {item['reason']} "
                f"(review_status={item['review_status']})",
                file=sys.stderr,
            )

    if dropped and args.delete_media:
        print(f"已删除 {len(dropped)} 条 dropped 样本的媒体文件")

    print(f"写出: {args.output_meta}")
    print(f"报告: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
