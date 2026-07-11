#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子视频标签复检。

校验每个保留样本的标签与 video_meta.json 中对应源视频/片段的治理后标注一致，
并校验 actual_frame_mapping 与帧目录中的实际帧文件一致。
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

SUBVIDEOS_META_DEFAULT = (
    _PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.reviewed.json"
)
VIDEO_META_DEFAULT = _PROJECT_ROOT / "data" / "07_metadata" / "video_meta.json"
OUTPUT_META_DEFAULT = (
    _PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.label_reviewed.json"
)
REPORT_DEFAULT = (
    _PROJECT_ROOT / "data" / "07_metadata" / "subvideo_label_review_report.json"
)
FRAME_DIR_DEFAULT = _PROJECT_ROOT / "data" / "04_frames"

FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
    "脆性断裂、齐根断裂",
}
VIDEO_ANOMALY_TYPE = "视频异常"


def _resolve_path(rel: str, project_root: Path) -> Path:
    """将元数据中的相对路径解析为绝对路径。"""
    if rel.startswith("data/"):
        return project_root / rel
    return project_root / "data" / rel


def _load_subvideos(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读取子视频元数据，支持 dict 与 list 两种顶层结构。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw.get("subvideos", []), raw
    return raw, {}


def _load_video_meta(path: Path) -> dict[str, Any]:
    """读取 video_meta.json 并返回 video_id 到记录的映射。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {r["video_id"]: r for r in raw}
    records = raw.get("videos") or raw.get("records", [])
    return {r["video_id"]: r for r in records}


def _event_frame(rec: dict[str, Any]) -> int | None:
    """返回有效事件帧；0 是合法帧号。"""
    effective = rec.get("event_frame_effective")
    if effective is not None:
        return effective
    return rec.get("event_frame_original")


def _is_mock_fingerprint(fp: Any) -> bool:
    if not isinstance(fp, str):
        return True
    lowered = fp.lower()
    return "mock" in lowered or "theoretical" in lowered or not fp.strip()


def _validate_positive_interval(
    sub: dict[str, Any],
    rec: dict[str, Any],
    *,
    reason_prefix: str,
) -> list[str]:
    errors = []
    event_frame = _event_frame(rec)
    if event_frame is None:
        errors.append(f"{reason_prefix}_missing_event_frame")
        return errors

    mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []
    if not mapping:
        errors.append(f"{reason_prefix}_missing_frame_mapping")
        return errors

    recomputed = subvideo_builder.compute_fracture_between(mapping, event_frame)
    stored = sub.get("fracture_between")
    if recomputed != stored:
        errors.append(
            f"{reason_prefix}_fracture_between_mismatch: stored={stored}, recomputed={recomputed}"
        )
    return errors


def _validate_media_contract(
    sub: dict[str, Any],
    frame_dir_root: Path,
    project_root: Path,
    warnings: list[str],
) -> list[str]:
    """校验媒体契约，返回失败原因列表。"""
    errors: list[str] = []
    subvideo_id = sub.get("subvideo_id", "<unknown>")
    mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []

    if not mapping:
        errors.append("empty_actual_frame_mapping")
        return errors

    if len(mapping) > 8:
        errors.append(f"frame_count_exceeds_8: {len(mapping)}")

    fingerprint = sub.get("processor_fingerprint")
    if not fingerprint:
        errors.append("missing_processor_fingerprint")
    elif _is_mock_fingerprint(fingerprint):
        errors.append(f"mock_or_theoretical_fingerprint: {fingerprint}")
    elif not sub.get("processor_info"):
        warnings.append("processor_info_missing")

    video_path_rel = sub.get("video_path", "")
    video_path = (
        _resolve_path(video_path_rel, project_root)
        if video_path_rel
        else project_root / "data" / "03_subvideos" / f"{subvideo_id}.mp4"
    )
    if not video_path.exists():
        errors.append(f"missing_video_file: {video_path_rel}")

    frame_dir = frame_dir_root / subvideo_id
    if not frame_dir.exists():
        errors.append(f"missing_frame_dir: {frame_dir.name}")
    else:
        if "frame_paths" not in sub:
            warnings.append("frame_paths_field_missing")
        frame_files = sorted(frame_dir.glob("frame_*.jpg"))
        if len(frame_files) != len(mapping):
            errors.append(
                f"frame_file_count_mismatch: mapping={len(mapping)}, files={len(frame_files)}"
            )

    return errors


def _validate_full_subvideo(
    sub: dict[str, Any],
    rec: dict[str, Any],
) -> list[str]:
    """校验全时长样本标签与源记录一致。"""
    errors: list[str] = []
    source_type = rec.get("type")
    sub_type = sub.get("type")
    sub_has = sub.get("has_fracture_canonical", sub.get("has_fracture"))
    rec_has = rec.get("has_fracture_canonical")
    sub_location = sub.get("location_canonical", sub.get("location"))
    rec_location = rec.get("location_canonical")

    if source_type == VIDEO_ANOMALY_TYPE:
        if sub_type != VIDEO_ANOMALY_TYPE:
            errors.append(f"anomaly_type_mismatch: sub={sub_type}, rec={source_type}")
        if rec_has is None:
            if sub_has is not None:
                errors.append(f"anomaly_has_fracture_should_be_null: sub={sub_has}")
        elif rec_has is True:
            if sub_has is not True:
                errors.append(f"anomaly_has_fracture_should_be_true: sub={sub_has}")
        if sub_location is not None:
            errors.append(f"anomaly_location_should_be_null: sub={sub_location}")
        if sub.get("fracture_between") is not None:
            errors.append("anomaly_fracture_between_should_be_null")
        return errors

    if source_type == "未夹紧":
        event_frame = _event_frame(rec)
        if event_frame is not None:
            # 带事件标注的未夹紧： governance 中视为正样本
            if sub_has is not True:
                errors.append(f"clamped_with_event_should_be_positive: sub={sub_has}")
            if sub_type != "未夹紧":
                errors.append(f"clamped_type_mismatch: sub={sub_type}")
            if sub.get("location") is not None or sub.get("location_canonical") is not None:
                errors.append("clamped_event_full_location_should_be_null")
            errors.extend(
                _validate_positive_interval(sub, rec, reason_prefix="clamped_event_full")
            )
        else:
            if sub_has is not False:
                errors.append(f"clamped_no_event_should_be_negative: sub={sub_has}")
            if sub_type != "未夹紧":
                errors.append(f"clamped_type_mismatch: sub={sub_type}")
            if sub.get("fracture_between") is not None:
                errors.append("clamped_no_event_fracture_between_should_be_null")
            if sub_location is not None:
                errors.append("clamped_location_should_be_null")
        return errors

    if source_type == "未断裂":
        if sub_has is not False:
            errors.append(f"negative_has_fracture_mismatch: sub={sub_has}")
        if sub_type != "未断裂":
            errors.append(f"negative_type_mismatch: sub={sub_type}, rec={source_type}")
        if sub.get("fracture_between") is not None:
            errors.append("negative_fracture_between_should_be_null")
        if sub_location is not None:
            errors.append("negative_location_should_be_null")
        return errors

    if source_type in FRACTURE_TYPES:
        if rec_has is not True:
            errors.append(f"source_not_fracture_in_metadata: rec_has={rec_has}")
        if sub_has is not True:
            errors.append(f"positive_has_fracture_mismatch: sub={sub_has}")
        if sub_type != source_type:
            errors.append(f"positive_type_mismatch: sub={sub_type}, rec={source_type}")
        if rec_location is not None and sub_location != rec_location:
            errors.append(
                f"positive_location_mismatch: sub={sub_location}, rec={rec_location}"
            )
        errors.extend(
            _validate_positive_interval(sub, rec, reason_prefix="full_positive")
        )
        return errors

    errors.append(f"unknown_source_type: {source_type}")
    return errors


def _validate_focus_subvideo(
    sub: dict[str, Any],
    rec: dict[str, Any],
) -> list[str]:
    """校验聚焦正样本标签与帧映射。"""
    errors: list[str] = []
    source_type = rec.get("type")
    event_frame = _event_frame(rec)

    if event_frame is None:
        errors.append("focus_requires_reliable_event_frame")
        return errors

    mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []
    if not mapping:
        errors.append("focus_requires_frame_mapping")
        return errors

    recomputed = subvideo_builder.compute_fracture_between(mapping, event_frame)
    stored = sub.get("fracture_between")

    if sub.get("has_fracture_canonical", sub.get("has_fracture")) is not True:
        errors.append("focus_should_be_positive")

    expected_type = source_type if source_type in FRACTURE_TYPES else sub.get("type")
    if sub.get("type") != expected_type:
        errors.append(f"focus_type_mismatch: sub={sub.get('type')}, expected={expected_type}")

    sub_location = sub.get("location_canonical", sub.get("location"))
    rec_location = rec.get("location_canonical")
    if rec_location is not None and sub_location != rec_location:
        errors.append(
            f"focus_location_mismatch: sub={sub_location}, rec={rec_location}"
        )

    if recomputed != stored:
        errors.append(
            f"fracture_between_mismatch: stored={stored}, recomputed={recomputed}"
        )

    return errors


def _validate_negative_subvideo(
    sub: dict[str, Any],
    rec: dict[str, Any],
) -> list[str]:
    """校验负样本标签字段。"""
    errors: list[str] = []

    if subvideo_builder._is_deprecated_post_event_negative(sub):
        errors.append("deprecated_post_event_negative")

    if sub.get("has_fracture_canonical", sub.get("has_fracture")) is not False:
        errors.append("negative_has_fracture_should_be_false")
    if sub.get("fracture_between") is not None:
        errors.append("negative_fracture_between_should_be_null")
    if sub.get("location") is not None or sub.get("location_canonical") is not None:
        errors.append("negative_location_should_be_null")
    if sub.get("type") != "未断裂":
        errors.append(f"negative_type_should_be_未断裂: sub={sub.get('type')}")
    return errors


def _validate_subvideo(
    sub: dict[str, Any],
    video_meta: dict[str, Any],
    frame_dir_root: Path,
    project_root: Path,
    warnings: list[str],
) -> dict[str, Any]:
    """单条子视频完整校验，返回包含 status 与 reasons 的字典。"""
    subvideo_id = sub.get("subvideo_id", "<unknown>")
    source_video = sub.get("source_video", "<unknown>")
    rec = video_meta.get(source_video)

    result: dict[str, Any] = {
        "subvideo_id": subvideo_id,
        "source_video": source_video,
        "status": "ok",
        "reasons": [],
    }

    if rec is None:
        result["status"] = "failed"
        result["reasons"].append("missing_source_video_meta")
        return result

    errors = _validate_media_contract(sub, frame_dir_root, project_root, warnings)
    if errors:
        result["status"] = "failed"
        result["reasons"].extend(errors)
        # 媒体契约失败时继续校验标签也没有意义，因为部分标签校验依赖 mapping。
        if "empty_actual_frame_mapping" in errors:
            return result

    crop_type = sub.get("crop_type", "")
    if crop_type.startswith("full"):
        errors = _validate_full_subvideo(sub, rec)
    elif crop_type.startswith("focus"):
        errors = _validate_focus_subvideo(sub, rec)
    elif crop_type.startswith("neg"):
        errors = _validate_negative_subvideo(sub, rec)
    else:
        errors = [f"unknown_crop_type: {crop_type}"]

    if errors:
        result["status"] = "failed"
        result["reasons"].extend(errors)

    return result


def review_subvideo_labels(
    subvideos_meta: Path,
    video_meta_path: Path,
    output_meta: Path,
    report_path: Path,
    frame_dir_root: Path = FRAME_DIR_DEFAULT,
    project_root: Path = _PROJECT_ROOT,
    write_invalid_output: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    执行标签复检。

    返回 (passed_results, failed_results)。
    若存在失败项，默认不写出 output_meta；指定 write_invalid_output=True 时
    仍会写出（包含失败原因标注，便于调试）。
    """
    subvideos, top_level = _load_subvideos(subvideos_meta)
    video_meta = _load_video_meta(video_meta_path)

    passed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    warnings: list[str] = []

    for sub in subvideos:
        result = _validate_subvideo(
            sub, video_meta, frame_dir_root, project_root, warnings
        )
        if result["status"] == "ok":
            passed.append(result)
        else:
            failed.append(result)

    status_counts: dict[str, int] = {"ok": len(passed), "failed": len(failed)}
    crop_counts: dict[str, int] = {}
    source_type_counts: dict[str, int] = {}
    for sub in subvideos:
        crop = sub.get("crop_type", "unknown")
        crop_counts[crop] = crop_counts.get(crop, 0) + 1
        stype = sub.get("source_type", sub.get("type", "unknown"))
        source_type_counts[stype] = source_type_counts.get(stype, 0) + 1

    report: dict[str, Any] = {
        "input_meta": str(subvideos_meta),
        "video_meta": str(video_meta_path),
        "output_meta": str(output_meta),
        "status_counts": status_counts,
        "crop_type_counts": crop_counts,
        "source_type_counts": source_type_counts,
        "warnings": warnings,
        "failed": failed,
        "passed_subvideo_ids": [r["subvideo_id"] for r in passed],
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if failed:
        if write_invalid_output:
            output_meta.parent.mkdir(parents=True, exist_ok=True)
            output_payload = dict(top_level)
            failures_by_id = {item["subvideo_id"]: item["reasons"] for item in failed}
            annotated_subvideos = []
            for sub in subvideos:
                annotated = dict(sub)
                reasons = failures_by_id.get(annotated.get("subvideo_id"))
                if reasons:
                    annotated["__review_failed_reasons"] = reasons
                annotated_subvideos.append(annotated)
            output_payload["subvideos"] = annotated_subvideos
            output_meta.write_text(
                json.dumps(output_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return passed, failed

    output_meta.parent.mkdir(parents=True, exist_ok=True)
    output_payload = dict(top_level)
    output_payload["subvideos"] = subvideos
    output_meta.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return passed, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="子视频标签复检")
    parser.add_argument(
        "--subvideos-meta",
        "--input-meta",
        dest="subvideos_meta",
        metavar="PATH",
        type=Path,
        default=SUBVIDEOS_META_DEFAULT,
        help="输入子视频元数据路径（默认：data/07_metadata/subvideos_meta.reviewed.json）",
    )
    parser.add_argument(
        "--video-meta",
        type=Path,
        default=VIDEO_META_DEFAULT,
        help="源视频元数据路径（默认：data/07_metadata/video_meta.json）",
    )
    parser.add_argument(
        "--output-meta",
        type=Path,
        default=OUTPUT_META_DEFAULT,
        help="输出复检后元数据路径（默认：data/07_metadata/subvideos_meta.label_reviewed.json）",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_DEFAULT,
        help="复检报告输出路径",
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
    parser.add_argument(
        "--write-invalid-output", "--write-invalid-report-only",
        dest="write_invalid_output",
        action="store_true",
        help="即使校验失败也写出 output_meta（用于调试）",
    )
    args = parser.parse_args()

    if not args.subvideos_meta.exists():
        print(f"错误：输入子视频元数据不存在: {args.subvideos_meta}", file=sys.stderr)
        return 2
    if not args.video_meta.exists():
        print(f"错误：输入视频元数据不存在: {args.video_meta}", file=sys.stderr)
        return 2

    passed, failed = review_subvideo_labels(
        subvideos_meta=args.subvideos_meta,
        video_meta_path=args.video_meta,
        output_meta=args.output_meta,
        report_path=args.report,
        frame_dir_root=args.frame_dir,
        project_root=args.project_root,
        write_invalid_output=args.write_invalid_output,
    )

    total = len(passed) + len(failed)
    print(f"复检完成: 通过 {len(passed)}/{total}, 失败 {len(failed)}/{total}")

    if failed:
        print("错误：标签/帧映射校验失败，未写出 .label_reviewed.json", file=sys.stderr)
        for item in failed:
            print(
                f"  - {item['subvideo_id']}: {item['reasons']}",
                file=sys.stderr,
            )
        print(f"报告: {args.report}")
        return 1

    print(f"写出: {args.output_meta}")
    print(f"报告: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
