#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源视频固定 ROI 人工标注工具。

MVP 只写 ROI 决定文件，不生成裁剪媒体，也不修改现有训练数据。

运行：
    streamlit run pipeline/scripts/roi_annotation_app.py -- \
      --metadata workspace/data/derived/metadata/video_meta.json \
      --output workspace/data/derived/metadata/roi_decisions.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import streamlit as st
from PIL import Image, ImageDraw
try:
    from streamlit_cropper import st_cropper
except ModuleNotFoundError:  # Core pipeline validation must not depend on the UI plugin.
    st_cropper = None

from pipeline.current_data import (
    current_data_paths,
    data_context_from_arg,
    resolve_data_artifact,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURRENT_DATA = current_data_paths(PROJECT_ROOT)
VIDEO_META_DEFAULT = CURRENT_DATA.metadata / "video_meta.json"
OUTPUT_DEFAULT = CURRENT_DATA.metadata / "roi_decisions.json"

SCHEMA_VERSION = "1.0"
ROI_POLICY_VERSION = "1.2"
LEGACY_ROI_POLICY_VERSIONS = {"1.0", "1.1"}
TARGET_ASPECT_WIDTH = 3
TARGET_ASPECT_HEIGHT = 4
TARGET_ASPECT_RATIO = "3:4"
MODE_FIXED = "fixed_roi"
MODE_NO_CROP = "no_crop"
VALID_MODES = {MODE_FIXED, MODE_NO_CROP}
STATUS_APPROVED = "approved"
STATUS_NEEDS_REVIEW = "needs_review"
VALID_STATUSES = {STATUS_APPROVED, STATUS_NEEDS_REVIEW}
MARGIN_KEYS = ("top", "right", "bottom", "left")
VISIBILITY_CHECK_KEYS = (
    "upper_grip_visible",
    "lower_grip_visible",
    "full_specimen_visible",
    "location_judgable",
    "root_break_judgable",
)


class RoiValidationError(ValueError):
    """ROI 数据或几何参数不合法。"""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--" in raw:
        raw = raw[raw.index("--") + 1 :]
    parser = argparse.ArgumentParser(description="源视频固定 ROI 人工标注工具")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--project-root", type=Path)
    args = parser.parse_args(raw)
    context = data_context_from_arg(PROJECT_ROOT, args.data_root)
    args.metadata = args.metadata or context.metadata / "video_meta.json"
    args.output = args.output or context.metadata / "roi_decisions.json"
    args.project_root = args.project_root or context.root
    return args


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_video_metadata(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RoiValidationError(f"视频 metadata 不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RoiValidationError(f"视频 metadata 不是合法 JSON: {path}: {exc}") from exc

    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict) and isinstance(raw.get("videos"), list):
        records = raw["videos"]
    else:
        raise RoiValidationError("视频 metadata 必须是数组或包含 videos 数组的对象")

    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise RoiValidationError(f"视频 metadata 第 {index} 项不是对象")
        video_id = record.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise RoiValidationError(f"视频 metadata 第 {index} 项缺少有效 video_id")
        if video_id in seen:
            raise RoiValidationError(f"视频 metadata 存在重复 video_id: {video_id}")
        seen.add(video_id)
        result.append(dict(record))
    return result


def resolve_video_path(record: Mapping[str, Any], project_root: Path) -> Path:
    raw = record.get("video_path") or (
        f"source/videos/{record['video_id']}.mp4"
    )
    return resolve_data_artifact(str(raw), project_root)


def load_roi_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "roi_policy_version": ROI_POLICY_VERSION,
            "decisions": [],
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RoiValidationError(f"ROI 决定文件不是合法 JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("decisions"), list):
        raise RoiValidationError("ROI 决定文件必须是包含 decisions 数组的对象")
    policy_version = raw.get("roi_policy_version")
    if policy_version not in {ROI_POLICY_VERSION, *LEGACY_ROI_POLICY_VERSIONS}:
        raise RoiValidationError(f"不支持的 roi_policy_version: {policy_version}")
    decision_ids: set[str] = set()
    for record in raw["decisions"]:
        if not isinstance(record, dict):
            raise RoiValidationError("ROI decisions 中存在非对象项")
        video_id = record.get("source_video_id")
        if not isinstance(video_id, str) or not video_id:
            raise RoiValidationError("ROI decision 缺少有效 source_video_id")
        if video_id in decision_ids:
            raise RoiValidationError(f"ROI decisions 存在重复视频: {video_id}")
        decision_ids.add(video_id)
    return raw


def decisions_by_id(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(record["source_video_id"]): dict(record)
        for record in payload.get("decisions", [])
    }


def save_roi_payload(
    path: Path,
    decisions: Mapping[str, Mapping[str, Any]],
    *,
    metadata_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [dict(decisions[key]) for key in sorted(decisions)]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "roi_policy_version": ROI_POLICY_VERSION,
        "source_metadata_file": str(metadata_path),
        "generated_at": utc_now(),
        "decision_count": len(ordered),
        "decisions": ordered,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False
    ).encode("utf-8")
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def normalize_margins(margins: Mapping[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key in MARGIN_KEYS:
        try:
            value = float(margins.get(key, 0.0))
        except (TypeError, ValueError) as exc:
            raise RoiValidationError(f"{key} 裁剪比例不是数字") from exc
        if not math.isfinite(value) or not 0.0 <= value < 1.0:
            raise RoiValidationError(f"{key} 裁剪比例必须在 [0, 1) 内")
        normalized[key] = round(value, 6)
    if normalized["left"] + normalized["right"] >= 0.98:
        raise RoiValidationError("左右裁剪比例之和必须小于 98%")
    if normalized["top"] + normalized["bottom"] >= 0.98:
        raise RoiValidationError("上下裁剪比例之和必须小于 98%")
    return normalized


def normalized_box(margins: Mapping[str, Any]) -> dict[str, float]:
    values = normalize_margins(margins)
    return {
        "x": values["left"],
        "y": values["top"],
        "width": round(1.0 - values["left"] - values["right"], 6),
        "height": round(1.0 - values["top"] - values["bottom"], 6),
    }


def pixel_box(
    margins: Mapping[str, Any], source_width: int, source_height: int
) -> dict[str, int]:
    if source_width < 2 or source_height < 2:
        raise RoiValidationError("源视频分辨率必须至少为 2x2")
    box = normalized_box(margins)
    x = min(source_width - 2, max(0, int(round(box["x"] * source_width))))
    y = min(source_height - 2, max(0, int(round(box["y"] * source_height))))
    width = min(source_width - x, max(2, int(round(box["width"] * source_width))))
    height = min(source_height - y, max(2, int(round(box["height"] * source_height))))

    # H.264/yuv420p 常要求偶数宽高。位置可以为奇数，宽高规整后仍保持在画面内。
    width -= width % 2
    height -= height % 2
    if width < 2 or height < 2:
        raise RoiValidationError("裁剪后的像素区域过小")
    return {"x": x, "y": y, "width": width, "height": height}


def _margins_from_pixel_box(
    box: Mapping[str, int], source_width: int, source_height: int
) -> dict[str, float]:
    return {
        "top": round(int(box["y"]) / source_height, 6),
        "right": round(
            (source_width - int(box["x"]) - int(box["width"])) / source_width,
            6,
        ),
        "bottom": round(
            (source_height - int(box["y"]) - int(box["height"])) / source_height,
            6,
        ),
        "left": round(int(box["x"]) / source_width, 6),
    }


def _normalized_from_pixel_box(
    box: Mapping[str, int], source_width: int, source_height: int
) -> dict[str, float]:
    return {
        "x": round(int(box["x"]) / source_width, 6),
        "y": round(int(box["y"]) / source_height, 6),
        "width": round(int(box["width"]) / source_width, 6),
        "height": round(int(box["height"]) / source_height, 6),
    }


def normalize_drag_box(
    box: Mapping[str, Any], source_width: int, source_height: int
) -> dict[str, int]:
    """Convert cropper coordinates to an in-bounds even-pixel exact 3:4 box."""
    try:
        left = float(box["left"] if "left" in box else box["x"])
        top = float(box["top"] if "top" in box else box["y"])
        width = float(box["width"])
        height = float(box["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RoiValidationError("拖拽裁剪框坐标无效") from exc
    if not all(math.isfinite(value) for value in (left, top, width, height)):
        raise RoiValidationError("拖拽裁剪框坐标必须是有限数")
    if width <= 0 or height <= 0:
        raise RoiValidationError("拖拽裁剪框宽高必须为正数")

    left = min(source_width, max(0.0, left))
    top = min(source_height, max(0.0, top))
    width = min(width, source_width - left)
    height = min(height, source_height - top)
    scale = math.floor(
        min(width / TARGET_ASPECT_WIDTH, height / TARGET_ASPECT_HEIGHT)
    )
    scale -= scale % 2
    if scale < 2:
        raise RoiValidationError("拖拽裁剪框过小，无法形成偶数像素 3:4 ROI")
    target_width = TARGET_ASPECT_WIDTH * scale
    target_height = TARGET_ASPECT_HEIGHT * scale
    center_x = left + width / 2.0
    center_y = top + height / 2.0
    x = min(
        source_width - target_width,
        max(0, round(center_x - target_width / 2.0)),
    )
    y = min(
        source_height - target_height,
        max(0, round(center_y - target_height / 2.0)),
    )
    return {"x": x, "y": y, "width": target_width, "height": target_height}


def initial_drag_box(
    existing: Mapping[str, Any] | None,
    source_width: int,
    source_height: int,
) -> dict[str, int]:
    """Return an existing ROI or a centered largest 3:4 box for the cropper."""
    existing = existing or {}
    saved = existing.get("pixel_box")
    if isinstance(saved, Mapping):
        try:
            saved_width = int(saved["width"])
            saved_height = int(saved["height"])
            if (
                saved_width * TARGET_ASPECT_HEIGHT
                == saved_height * TARGET_ASPECT_WIDTH
            ):
                return normalize_drag_box(saved, source_width, source_height)
        except (KeyError, TypeError, ValueError, RoiValidationError):
            pass
    margins = existing.get("margins")
    if not isinstance(margins, Mapping):
        margins = {key: 0.0 for key in MARGIN_KEYS}
    return aspect_locked_geometry(margins, source_width, source_height)[2]


def aspect_locked_geometry(
    margins: Mapping[str, Any], source_width: int, source_height: int
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Expand the requested ROI to an exact even-pixel 3:4 box when possible.

    Expansion is preferred so the user's requested specimen/grip region remains
    inside the effective ROI. If the source bounds make expansion impossible,
    the largest in-bounds 3:4 box is used around the requested center.
    """
    requested = pixel_box(margins, source_width, source_height)
    max_scale = min(
        source_width // TARGET_ASPECT_WIDTH,
        source_height // TARGET_ASPECT_HEIGHT,
    )
    max_scale -= max_scale % 2
    if max_scale < 2:
        raise RoiValidationError("源视频分辨率无法容纳偶数像素的 3:4 ROI")

    needed = math.ceil(
        max(
            requested["width"] / TARGET_ASPECT_WIDTH,
            requested["height"] / TARGET_ASPECT_HEIGHT,
        )
    )
    needed += needed % 2
    scale = min(needed, max_scale)
    target_width = TARGET_ASPECT_WIDTH * scale
    target_height = TARGET_ASPECT_HEIGHT * scale

    center_x = requested["x"] + requested["width"] / 2.0
    center_y = requested["y"] + requested["height"] / 2.0
    x = min(source_width - target_width, max(0, round(center_x - target_width / 2)))
    y = min(source_height - target_height, max(0, round(center_y - target_height / 2)))
    box = {"x": x, "y": y, "width": target_width, "height": target_height}
    effective_margins = _margins_from_pixel_box(box, source_width, source_height)
    normalized = _normalized_from_pixel_box(box, source_width, source_height)
    if Fraction(target_width, target_height) != Fraction(
        TARGET_ASPECT_WIDTH, TARGET_ASPECT_HEIGHT
    ):
        raise RoiValidationError("内部错误: ROI 未锁定为 3:4")
    return effective_margins, normalized, box


def audit_timestamps(duration: float, event_time: float | None = None) -> list[float]:
    if not math.isfinite(duration) or duration <= 0:
        return [0.0]
    last = max(0.0, duration - min(0.05, duration / 100.0))
    candidates = [0.0, duration * 0.25, duration * 0.5, duration * 0.75, last]
    if event_time is not None and math.isfinite(event_time):
        for offset in (-0.2, 0.0, 0.2):
            candidates.append(min(last, max(0.0, event_time + offset)))
    return sorted({round(value, 3) for value in candidates})


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def source_state(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "source_size_bytes": int(stat.st_size),
        "source_mtime_ns": int(stat.st_mtime_ns),
    }


def source_state_matches(decision: Mapping[str, Any], path: Path) -> bool:
    try:
        current = source_state(path)
    except FileNotFoundError:
        return False
    return (
        decision.get("source_size_bytes") == current["source_size_bytes"]
        and decision.get("source_mtime_ns") == current["source_mtime_ns"]
    )


def build_decision(
    *,
    video_id: str,
    video_path: Path,
    mode: str,
    review_status: str,
    margins: Mapping[str, Any],
    source_width: int,
    source_height: int,
    reviewed_timestamps: list[float],
    source_sha256: str,
    reviewer_notes: str = "",
    source_video_reference: str | None = None,
    visibility_checks: Mapping[str, Any] | None = None,
    pixel_box_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in VALID_MODES:
        raise RoiValidationError(f"非法 ROI mode: {mode}")
    if review_status not in VALID_STATUSES:
        raise RoiValidationError(f"非法 review_status: {review_status}")
    requested_margins = normalize_margins(margins)
    if mode == MODE_FIXED and all(value == 0.0 for value in requested_margins.values()):
        raise RoiValidationError("fixed_roi 至少需要裁剪一个方向；全画面请使用 no_crop")
    if mode == MODE_NO_CROP:
        effective_margins = {key: 0.0 for key in MARGIN_KEYS}
        effective_normalized_box = normalized_box(effective_margins)
        effective_pixel_box = pixel_box(
            effective_margins, source_width, source_height
        )
        aspect_ratio_strategy = "pad_to_target"
    else:
        if pixel_box_override is not None:
            effective_pixel_box = normalize_drag_box(
                pixel_box_override, source_width, source_height
            )
            effective_margins = _margins_from_pixel_box(
                effective_pixel_box, source_width, source_height
            )
            effective_normalized_box = _normalized_from_pixel_box(
                effective_pixel_box, source_width, source_height
            )
            requested_margins = dict(effective_margins)
        else:
            (
                effective_margins,
                effective_normalized_box,
                effective_pixel_box,
            ) = aspect_locked_geometry(margins, source_width, source_height)
        aspect_ratio_strategy = "crop_exact"
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in source_sha256)
    ):
        raise RoiValidationError("source_sha256 必须是 64 位十六进制摘要")
    normalized_timestamps = sorted(
        {round(float(value), 3) for value in reviewed_timestamps}
    )
    if review_status == STATUS_APPROVED and not normalized_timestamps:
        raise RoiValidationError("approved 决定必须包含已检查的关键时间点")
    visibility = {
        key: bool((visibility_checks or {}).get(key, False))
        for key in VISIBILITY_CHECK_KEYS
    }
    if review_status == STATUS_APPROVED and not all(visibility.values()):
        missing = [key for key, checked in visibility.items() if not checked]
        raise RoiValidationError(
            "approved 决定必须确认全部可见性检查: " + ", ".join(missing)
        )
    state = source_state(video_path)
    return {
        "source_video_id": video_id,
        "source_video_path": source_video_reference or str(video_path),
        "mode": mode,
        "review_status": review_status,
        "requested_margins": requested_margins,
        "margins": effective_margins,
        "normalized_box": effective_normalized_box,
        "pixel_box": effective_pixel_box,
        "target_aspect_ratio": TARGET_ASPECT_RATIO,
        "aspect_ratio_strategy": aspect_ratio_strategy,
        "interaction_mode": (
            "no_crop"
            if mode == MODE_NO_CROP
            else "drag_box"
            if pixel_box_override is not None
            else "legacy_margins"
        ),
        "source_resolution": [source_width, source_height],
        "source_sha256": source_sha256,
        **state,
        "reviewed_timestamps": normalized_timestamps,
        "visibility_checks": visibility,
        "roi_policy_version": ROI_POLICY_VERSION,
        "reviewed_at": utc_now(),
        "reviewer_notes": reviewer_notes.strip(),
    }


def probe_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,nb_frames,duration:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"无法运行 ffprobe: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "ffprobe 失败").strip())
    try:
        payload = json.loads(result.stdout)
        stream = (payload.get("streams") or [])[0]
        duration = stream.get("duration") or (payload.get("format") or {}).get("duration")
        width = int(stream["width"])
        height = int(stream["height"])
        duration_value = float(duration)
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("ffprobe 未返回有效的视频分辨率或时长") from exc
    if width < 2 or height < 2 or not math.isfinite(duration_value) or duration_value <= 0:
        raise RuntimeError("视频分辨率或时长无效")
    return {
        "width": width,
        "height": height,
        "duration": duration_value,
        "nb_frames": stream.get("nb_frames"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
    }


def extract_frame(path: Path, timestamp: float) -> Image.Image:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{max(0.0, timestamp):.6f}",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, check=False, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"无法运行 ffmpeg: {exc}") from exc
    if result.returncode != 0 or not result.stdout:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr or f"无法在 {timestamp:.3f}s 抽取视频帧")
    try:
        with Image.open(io.BytesIO(result.stdout)) as image:
            return image.convert("RGB")
    except Exception as exc:
        raise RuntimeError("FFmpeg 输出的帧图片无法解析") from exc


@st.cache_data(show_spinner=False)
def _probe_video_cached(path: str, mtime_ns: int) -> dict[str, Any]:
    del mtime_ns
    return probe_video(Path(path))


@st.cache_data(show_spinner=False, max_entries=160)
def _extract_frame_cached(path: str, mtime_ns: int, timestamp: float) -> Image.Image:
    del mtime_ns
    return extract_frame(Path(path), timestamp)


def draw_roi(image: Image.Image, box: Mapping[str, int]) -> Image.Image:
    rendered = image.copy()
    draw = ImageDraw.Draw(rendered)
    x = int(box["x"])
    y = int(box["y"])
    right = x + int(box["width"]) - 1
    bottom = y + int(box["height"]) - 1
    line_width = max(2, round(min(image.size) / 180))
    draw.rectangle((x, y, right, bottom), outline="#ff2d2d", width=line_width)
    return rendered


def crop_image(image: Image.Image, box: Mapping[str, int]) -> Image.Image:
    x = int(box["x"])
    y = int(box["y"])
    return image.crop((x, y, x + int(box["width"]), y + int(box["height"])))


def _decision_counts(
    videos: list[dict[str, Any]], decisions: Mapping[str, Mapping[str, Any]]
) -> dict[str, int]:
    video_ids = {record["video_id"] for record in videos}
    relevant = [record for key, record in decisions.items() if key in video_ids]
    return {
        "total": len(videos),
        "approved": sum(
            record.get("review_status") == STATUS_APPROVED
            and record.get("roi_policy_version") == ROI_POLICY_VERSION
            for record in relevant
        ),
        "needs_review": sum(
            record.get("review_status") == STATUS_NEEDS_REVIEW
            and record.get("roi_policy_version") == ROI_POLICY_VERSION
            for record in relevant
        ),
        "outdated_policy": sum(
            record.get("roi_policy_version") != ROI_POLICY_VERSION
            for record in relevant
        ),
        "unreviewed": len(videos) - len(relevant),
    }


def _format_video_option(
    record: Mapping[str, Any], decisions: Mapping[str, Mapping[str, Any]]
) -> str:
    video_id = str(record["video_id"])
    decision = decisions.get(video_id)
    if decision is None:
        prefix = "❓"
    elif decision.get("roi_policy_version") != ROI_POLICY_VERSION:
        prefix = "🔁"
    elif decision.get("review_status") == STATUS_APPROVED:
        prefix = "✅"
    else:
        prefix = "🟡"
    label = record.get("type") or "未标注"
    return f"{prefix} {video_id} | {label}"


def _render_audit_previews(
    *,
    video_path: Path,
    mtime_ns: int,
    timestamps: list[float],
    box: Mapping[str, int],
) -> None:
    columns = st.columns(min(4, max(1, len(timestamps))))
    for index, timestamp in enumerate(timestamps):
        with columns[index % len(columns)]:
            try:
                frame = _extract_frame_cached(
                    str(video_path), mtime_ns, float(timestamp)
                )
                st.image(
                    crop_image(frame, box),
                    caption=f"{timestamp:.2f}s",
                    width="stretch",
                )
            except RuntimeError as exc:
                st.error(f"{timestamp:.2f}s: {exc}")


def main() -> None:
    if st_cropper is None:
        raise RuntimeError(
            "ROI 标注 UI 需要可选依赖 streamlit-cropper；"
            "核心重建与校验不需要该依赖"
        )
    args = _parse_args()
    metadata_path = args.metadata.resolve()
    output_path = args.output.resolve()
    project_root = args.project_root.resolve()

    st.set_page_config(page_title="源视频 ROI 标注", layout="wide")
    st.title("源视频固定 ROI 标注")
    st.caption("MVP 只保存裁剪决定，不生成或覆盖任何训练视频。")

    try:
        videos = load_video_metadata(metadata_path)
        payload = load_roi_payload(output_path)
    except RoiValidationError as exc:
        st.error(str(exc))
        st.stop()
    decisions = decisions_by_id(payload)
    by_id = {record["video_id"]: record for record in videos}
    counts = _decision_counts(videos, decisions)
    st.write(
        f"总数 {counts['total']} · 未审查 {counts['unreviewed']} · "
        f"✅ approved {counts['approved']} · 🟡 needs_review {counts['needs_review']} · "
        f"🔁 旧策略待复审 {counts['outdated_policy']}"
    )

    left, center, right = st.columns([1.1, 2.2, 1.5])
    with left:
        st.subheader("源视频")
        state_filter = st.multiselect(
            "状态",
            ["unreviewed", STATUS_APPROVED, STATUS_NEEDS_REVIEW, "outdated_policy"],
            default=["unreviewed", STATUS_APPROVED, STATUS_NEEDS_REVIEW, "outdated_policy"],
        )
        search = st.text_input("搜索 video_id / 类型").strip().lower()
        filtered: list[dict[str, Any]] = []
        for record in videos:
            video_id = record["video_id"]
            decision = decisions.get(video_id)
            state = (
                "unreviewed" if decision is None else str(decision.get("review_status"))
            )
            if decision is not None and decision.get("roi_policy_version") != ROI_POLICY_VERSION:
                state = "outdated_policy"
            if state not in state_filter:
                continue
            haystack = f"{video_id} {record.get('type', '')}".lower()
            if search and search not in haystack:
                continue
            filtered.append(record)
        if not filtered:
            st.info("没有符合筛选条件的视频。")
            return
        selected_id = st.selectbox(
            "选择视频",
            [record["video_id"] for record in filtered],
            format_func=lambda value: _format_video_option(by_id[value], decisions),
        )

    selected = by_id[selected_id]
    video_path = resolve_video_path(selected, project_root)
    existing = decisions.get(selected_id, {})

    if not video_path.exists():
        with center:
            st.error(f"视频不存在: {video_path}")
        return

    state = source_state(video_path)
    mtime_ns = state["source_mtime_ns"]
    try:
        info = _probe_video_cached(str(video_path), mtime_ns)
    except RuntimeError as exc:
        with center:
            st.error(f"无法读取视频: {exc}")
        return

    if existing and not source_state_matches(existing, video_path):
        st.warning("源视频大小或修改时间与已保存决定不一致，请重新检查并保存。")
    if existing and existing.get("roi_policy_version") != ROI_POLICY_VERSION:
        st.warning(
            f"该视频使用旧 ROI 策略 {existing.get('roi_policy_version')}；"
            f"当前策略 {ROI_POLICY_VERSION} 要求直接拖拽固定 {TARGET_ASPECT_RATIO} 红框，"
            "并以红框画面作为最终裁剪结果，必须重新检查并保存。"
        )

    duration = float(info["duration"])
    width = int(info["width"])
    height = int(info["height"])
    existing_visibility = existing.get("visibility_checks") or {}

    with center:
        st.subheader(selected_id)
        with st.expander("原始视频播放", expanded=False):
            st.video(str(video_path))
        timestamp = st.slider(
            "抽帧时间（可拖动）",
            min_value=0.0,
            max_value=max(0.0, duration - 0.01),
            value=min(
                max(0.0, float(selected.get("event_time") or duration * 0.5)),
                max(0.0, duration - 0.01),
            ),
            step=0.05,
            key=f"time_{selected_id}",
        )

    with right:
        st.subheader("裁剪决定")
        mode_options = [MODE_FIXED, MODE_NO_CROP]
        existing_mode = existing.get("mode")
        mode = st.radio(
            "模式",
            mode_options,
            index=mode_options.index(existing_mode)
            if existing_mode in mode_options
            else 0,
            format_func=lambda value: "固定 ROI" if value == MODE_FIXED else "不裁剪",
            key=f"mode_{selected_id}",
        )
        if mode == MODE_FIXED:
            st.caption("在中间画面上直接拖动或缩放红框；框的比例锁定为 3:4。")
        else:
            st.caption("保留完整画面，后续生成媒体时 padding 到 3:4。")

        status_options = [STATUS_APPROVED, STATUS_NEEDS_REVIEW]
        existing_status = existing.get("review_status")
        if existing and existing.get("roi_policy_version") != ROI_POLICY_VERSION:
            existing_status = STATUS_NEEDS_REVIEW
        review_status = st.selectbox(
            "审核状态",
            status_options,
            index=status_options.index(existing_status)
            if existing_status in status_options
            else 0,
            key=f"status_{selected_id}",
        )
        notes = st.text_area(
            "备注",
            value=str(existing.get("reviewer_notes") or ""),
            key=f"notes_{selected_id}",
        )
        st.markdown("**裁剪后信息保留检查**")
        visibility_labels = {
            "upper_grip_visible": "上夹具清晰可见",
            "lower_grip_visible": "下夹具清晰可见",
            "full_specimen_visible": "完整试样清晰可见",
            "location_judgable": "仍可判断标距内/外位置",
            "root_break_judgable": "仍可判断是否齐根断裂",
        }
        visibility_checks = {
            key: st.checkbox(
                label,
                value=bool(existing_visibility.get(key, False)),
                key=f"visibility_{key}_{selected_id}",
            )
            for key, label in visibility_labels.items()
        }

    try:
        current_frame = _extract_frame_cached(
            str(video_path), mtime_ns, round(float(timestamp), 3)
        )
    except (RoiValidationError, RuntimeError) as exc:
        with center:
            st.error(str(exc))
        return

    with center:
        if mode == MODE_FIXED:
            default_box = initial_drag_box(existing, width, height)
            st.markdown("**拖拽裁剪框（固定 3:4）**")
            st.caption("拖动红框可平移，拖动边角可等比缩放；红框中的画面就是最终 ROI。")
            raw_box = st_cropper(
                current_frame,
                realtime_update=True,
                default_coords=(
                    default_box["x"],
                    default_box["x"] + default_box["width"],
                    default_box["y"],
                    default_box["y"] + default_box["height"],
                ),
                box_color="#ff2d2d",
                aspect_ratio=(TARGET_ASPECT_WIDTH, TARGET_ASPECT_HEIGHT),
                return_type="box",
                key=f"roi_cropper_{selected_id}",
                should_resize_image=True,
                stroke_width=3,
            )
            active_box = normalize_drag_box(raw_box, width, height)
            effective_margins = _margins_from_pixel_box(active_box, width, height)
        else:
            effective_margins = {key: 0.0 for key in MARGIN_KEYS}
            active_box = pixel_box(effective_margins, width, height)
            st.info("当前为不裁剪模式，下方预览使用全画面。")

        with st.expander("当前帧 ROI 对照预览", expanded=False):
            preview_left, preview_right = st.columns(2)
            with preview_left:
                st.image(
                    draw_roi(current_frame, active_box),
                    caption=f"原图 + ROI · {timestamp:.2f}s",
                    width="stretch",
                )
            with preview_right:
                st.image(
                    crop_image(current_frame, active_box),
                    caption=(
                        f"ROI 预览 · {active_box['width']}×{active_box['height']} px"
                    ),
                    width="stretch",
                )

        review_times = audit_timestamps(duration, selected.get("event_time"))
        with st.expander("关键时刻 ROI 预览", expanded=False):
            st.caption("包含开头、25%、50%、75%、结尾，以及可靠事件时间附近。")
            _render_audit_previews(
                video_path=video_path,
                mtime_ns=mtime_ns,
                timestamps=review_times,
                box=active_box,
            )

    with right:
        st.write(
            f"源分辨率：`{width}×{height}`  \n"
            f"输出框：`x={active_box['x']}, y={active_box['y']}, "
            f"w={active_box['width']}, h={active_box['height']}`  \n"
            f"目标比例：`{TARGET_ASPECT_RATIO}` · "
            f"策略：`{'crop_exact' if mode == MODE_FIXED else 'pad_to_target'}`"
        )
        if mode == MODE_FIXED:
            st.caption("上述输出框是拖拽红框换算后的原始视频像素坐标。")
        reviewed = st.checkbox(
            "我已检查关键时刻预览",
            value=bool(existing.get("reviewed_timestamps")),
            key=f"reviewed_{selected_id}",
        )
        if st.button("保存当前决定", type="primary", width="stretch"):
            try:
                if review_status == STATUS_APPROVED and not reviewed:
                    raise RoiValidationError("保存 approved 前必须检查关键时刻预览")
                with st.spinner("计算源视频哈希并保存…"):
                    digest = sha256_file(video_path)
                    decision = build_decision(
                        video_id=selected_id,
                        video_path=video_path,
                        mode=mode,
                        review_status=review_status,
                        margins=effective_margins,
                        source_width=width,
                        source_height=height,
                        reviewed_timestamps=review_times if reviewed else [],
                        source_sha256=digest,
                        reviewer_notes=notes,
                        source_video_reference=str(
                            selected.get("video_path")
                            or f"source/videos/{selected_id}.mp4"
                        ),
                        visibility_checks=visibility_checks,
                        pixel_box_override=active_box if mode == MODE_FIXED else None,
                    )
                    decisions[selected_id] = decision
                    save_roi_payload(
                        output_path, decisions, metadata_path=metadata_path
                    )
            except (OSError, RoiValidationError) as exc:
                st.error(f"保存失败: {exc}")
            else:
                st.success(f"已保存: {output_path}")
                st.rerun()

        with st.expander("源视频信息"):
            st.json(
                {
                    "video_path": str(video_path),
                    "duration": duration,
                    "resolution": [width, height],
                    "event_time": selected.get("event_time"),
                    "type": selected.get("type"),
                    "location": selected.get("location_canonical")
                    or selected.get("location"),
                    "existing_decision": existing or None,
                }
            )


if __name__ == "__main__":
    main()
