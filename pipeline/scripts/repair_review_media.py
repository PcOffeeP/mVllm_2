#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复人工审核后的不一致媒体状态。

检测并修复：
- mp4 或帧目录任一缺失：视为人工审核删除，不再重新生成。
- mp4 文件存在但为空且帧目录仍存在：尝试根据源视频重新生成。

无法修复的情况写入报告，但不 fatal。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.scripts import subvideo_builder

SUBVIDEOS_META_DEFAULT = _PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.json"
VIDEO_META_DEFAULT = _PROJECT_ROOT / "data" / "07_metadata" / "video_meta.json"
REPORT_DEFAULT = (
    _PROJECT_ROOT / "data" / "07_metadata" / "manual_review_repair_report.json"
)
FRAME_DIR_DEFAULT = _PROJECT_ROOT / "data" / "04_frames"


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


def _source_video_path(
    sub: dict[str, Any],
    video_meta: dict[str, Any] | None,
    project_root: Path,
) -> Path | None:
    """解析源视频绝对路径。"""
    source_video = sub.get("source_video")
    if source_video and video_meta:
        rec = video_meta.get(source_video)
        if rec:
            raw = rec.get("video_path") or f"data/01_videos/{source_video}.mp4"
            return _resolve_path(raw, project_root)
    if source_video:
        return project_root / "data" / "01_videos" / f"{source_video}.mp4"
    return None


def _classify_entry(
    sub: dict[str, Any],
    frame_dir_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    subvideo_id = sub.get("subvideo_id", "<unknown>")
    video_path_rel = sub.get("video_path", "")
    video_path = (
        _resolve_path(video_path_rel, project_root)
        if video_path_rel
        else project_root / "data" / "03_subvideos" / f"{subvideo_id}.mp4"
    )
    frame_dir = frame_dir_root / subvideo_id

    video_file_exists = video_path.exists()
    video_file_valid = _video_file_valid(video_path)
    frame_dir_exists = frame_dir.is_dir() and any(frame_dir.iterdir())

    if video_file_valid and frame_dir_exists:
        status = "ok"
        reason = "both_present"
    elif not video_file_exists and not frame_dir_exists:
        status = "review_deleted"
        reason = "both_missing"
    elif not video_file_exists:
        status = "review_deleted"
        reason = "missing_video_review_deleted"
    elif not frame_dir_exists:
        status = "review_deleted"
        reason = "missing_frames_review_deleted"
    elif not video_file_valid:
        status = "invalid_video"
        reason = "invalid_video"
    else:
        status = "unknown_media_state"
        reason = "unknown_media_state"

    return {
        "subvideo_id": subvideo_id,
        "video_path": str(video_path),
        "frame_dir": str(frame_dir),
        "status": status,
        "reason": reason,
        "video_exists": video_file_exists,
        "video_valid": video_file_valid,
        "frame_dir_exists": frame_dir_exists,
    }


def _repair_missing_frames(
    sub: dict[str, Any],
    frame_dir_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    """根据现有 mp4 与 actual_frame_mapping 重新抽帧。"""
    subvideo_id = sub["subvideo_id"]
    video_path_rel = sub.get("video_path", "")
    video_path = (
        _resolve_path(video_path_rel, project_root)
        if video_path_rel
        else project_root / "data" / "03_subvideos" / f"{subvideo_id}.mp4"
    )
    frame_dir = frame_dir_root / subvideo_id
    mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []

    if not mapping:
        return {
            "subvideo_id": subvideo_id,
            "repaired": False,
            "reason": "missing_frame_mapping",
        }

    try:
        frame_files = subvideo_builder.extract_sampled_frames(
            video_path, frame_dir, mapping
        )
        rel_paths = [
            str(Path(f).relative_to(project_root / "data")) for f in frame_files
        ]
        sub["frame_paths"] = rel_paths
        return {
            "subvideo_id": subvideo_id,
            "repaired": True,
            "reason": "regenerated_frames",
            "frame_count": len(frame_files),
        }
    except Exception as exc:
        return {
            "subvideo_id": subvideo_id,
            "repaired": False,
            "reason": f"frame_extraction_failed: {exc}",
        }


def _ensure_media_created(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"output video not created: {path}")
    if path.stat().st_size == 0:
        raise RuntimeError(f"output video is empty: {path}")


def _repair_missing_video(
    sub: dict[str, Any],
    video_meta: dict[str, Any] | None,
    project_root: Path,
) -> dict[str, Any]:
    """根据源视频与起止时间重新生成 mp4。"""
    subvideo_id = sub["subvideo_id"]
    source_path = _source_video_path(sub, video_meta, project_root)
    if source_path is None or not source_path.exists():
        return {
            "subvideo_id": subvideo_id,
            "repaired": False,
            "reason": "missing_source_video",
        }

    output_path = project_root / "data" / "03_subvideos" / f"{subvideo_id}.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop_type = sub.get("crop_type", "")

    try:
        if crop_type.startswith("full"):
            subvideo_builder.copy_as_subvideo(source_path, output_path)
        else:
            start_time = float(sub.get("start_time", 0.0))
            end_time = float(sub.get("end_time", 0.0))
            if end_time <= start_time:
                raise RuntimeError(f"invalid clip range: {start_time} -> {end_time}")
            subvideo_builder.crop_video(source_path, output_path, start_time, end_time)

        _ensure_media_created(output_path)

        rel = str(output_path.relative_to(project_root / "data"))
        sub["video_path"] = rel
        return {
            "subvideo_id": subvideo_id,
            "repaired": True,
            "reason": "regenerated_video",
            "video_path": rel,
        }
    except Exception as exc:
        return {
            "subvideo_id": subvideo_id,
            "repaired": False,
            "reason": f"video_generation_failed: {exc}",
        }


def repair_review_media(
    subvideos_meta: Path,
    output_meta: Path,
    report_path: Path,
    video_meta_path: Path | None = None,
    frame_dir_root: Path = FRAME_DIR_DEFAULT,
    project_root: Path = _PROJECT_ROOT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    修复不一致媒体状态。

    返回 ( repaired_subvideos, failed_repairs )。
    """
    subvideos, top_level = _load_subvideos(subvideos_meta)

    video_meta: dict[str, Any] | None = None
    if video_meta_path and video_meta_path.exists():
        raw_video_meta = json.loads(video_meta_path.read_text(encoding="utf-8"))
        if isinstance(raw_video_meta, list):
            video_meta = {r["video_id"]: r for r in raw_video_meta}
        elif isinstance(raw_video_meta, dict):
            records = raw_video_meta.get("videos") or raw_video_meta.get("records", [])
            video_meta = {r["video_id"]: r for r in records}

    repaired: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    skipped_deleted: list[dict[str, Any]] = []
    ok_count = 0

    for sub in subvideos:
        cls = _classify_entry(sub, frame_dir_root, project_root)
        status = cls["status"]
        if status == "ok":
            ok_count += 1
            continue
        if status == "review_deleted":
            skipped_deleted.append(
                {
                    "subvideo_id": cls["subvideo_id"],
                    "repaired": False,
                    "reason": cls["reason"],
                }
            )
            continue

        if status == "missing_frames":
            result = _repair_missing_frames(sub, frame_dir_root, project_root)
        else:  # invalid_video / legacy missing_video
            result = _repair_missing_video(sub, video_meta, project_root)

        if result["repaired"]:
            repaired.append(result)
        else:
            failed.append(result)

    report: dict[str, Any] = {
        "input_meta": str(subvideos_meta),
        "output_meta": str(output_meta),
        "video_meta": str(video_meta_path) if video_meta_path else None,
        "ok_count": ok_count,
        "repaired_count": len(repaired),
        "skipped_deleted_count": len(skipped_deleted),
        "failed_count": len(failed),
        "repaired": repaired,
        "skipped_deleted": skipped_deleted,
        "failed": failed,
    }

    output_meta.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    output_payload = dict(top_level)
    output_payload["subvideos"] = subvideos
    output_meta.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return repaired, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="修复人工审核后的不一致媒体状态")
    parser.add_argument(
        "--subvideos-meta",
        "--input-meta",
        dest="subvideos_meta",
        metavar="PATH",
        type=Path,
        default=SUBVIDEOS_META_DEFAULT,
        help="输入子视频元数据路径（默认：data/07_metadata/subvideos_meta.json）",
    )
    parser.add_argument(
        "--output-meta",
        type=Path,
        default=None,
        help="输出修复后元数据路径（默认：data/07_metadata/subvideos_meta.repaired.json）",
    )
    parser.add_argument(
        "--video-meta",
        type=Path,
        default=VIDEO_META_DEFAULT,
        help="源视频元数据路径（默认：data/07_metadata/video_meta.json）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_DEFAULT,
        help="修复报告输出路径",
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
        default=_PROJECT_ROOT,
        help="项目根目录，用于解析相对路径",
    )
    args = parser.parse_args()

    if not args.subvideos_meta.exists():
        print(f"错误：输入元数据不存在: {args.subvideos_meta}", file=sys.stderr)
        return 2

    output_meta = args.output_meta or (
        args.project_root / "data" / "07_metadata" / "subvideos_meta.repaired.json"
    )

    repaired, failed = repair_review_media(
        subvideos_meta=args.subvideos_meta,
        output_meta=output_meta,
        report_path=args.report,
        video_meta_path=args.video_meta,
        frame_dir_root=args.frame_dir,
        project_root=args.project_root,
    )
    report_data = json.loads(args.report.read_text(encoding="utf-8"))
    skipped_deleted = report_data.get("skipped_deleted", [])

    print(
        f"修复完成: 成功 {len(repaired)} 条, "
        f"跳过人工删除 {len(skipped_deleted)} 条, 失败 {len(failed)} 条"
    )
    for item in repaired:
        print(f"  已修复 {item['subvideo_id']}: {item['reason']}")
    for item in skipped_deleted:
        print(f"  跳过 {item['subvideo_id']}: {item['reason']}")
    for item in failed:
        print(f"  失败 {item['subvideo_id']}: {item['reason']}", file=sys.stderr)

    print(f"写出: {output_meta}")
    print(f"报告: {args.report}")

    if failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
