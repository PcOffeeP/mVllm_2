#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子视频生成器（先选后生成）

阶段 1：为每个训练/验证视频生成候选子视频清单（不生成媒体）。
阶段 2：按训练集正:负 1:1~2:1 选择样本。
阶段 3：只生成被选中的子视频到 data/03_subvideos/。

候选策略：
- 确认断裂且时间可靠：完整视频 + 3s/10s/30s × 5 位置。
- 确认未断裂：完整视频 + 3s/10s/30s 前/中/后固定位置负样本。
- 未夹紧：仅完整视频。
- 视频异常：仅完整视频。
- 断裂前负样本：与事件保持 ≥1s 安全间隔。
- 少量断裂后困难负样本：所有采样帧晚于事件。

默认不抽帧；抽帧仅在 --extract-frames 时进行。
测试集视频不生成子视频。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.preprocessing import (
    MiniCPMVideoPreprocessor,
    VideoPreprocessor,
)

VIDEO_META_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "video_meta.json"
SPLITS_DIR_DEFAULT = PROJECT_ROOT / "data" / "05_splits"
SUBVIDEO_DIR_DEFAULT = PROJECT_ROOT / "data" / "03_subvideos"
FRAME_DIR_DEFAULT = PROJECT_ROOT / "data" / "04_frames"
SUBVIDEOS_META_DEFAULT = PROJECT_ROOT / "data" / "07_metadata" / "subvideos_meta.json"

FOCUS_WINDOWS = [3, 5, 10, 20]
FOCUS_POSITIONS = [0.2, 0.35, 0.5, 0.65, 0.8]
NEG_CLIP_DURATIONS = [3, 5, 10, 20]
NEG_BEFORE_DURATION = 5
NEG_AFTER_DURATION = 5
VIDEO_MAXLEN = 8

FRACTURE_TYPES = [
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
]

NON_FRACTURE_TYPES = ["未断裂", "未夹紧"]
VIDEO_ANOMALY_TYPE = "视频异常"

EXCLUSIONS: list[dict[str, Any]] = []


def _ffprobe(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,nb_frames,duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
        if result.returncode != 0:
            return {}
        stream = (json.loads(result.stdout).get("streams") or [{}])[0]
        fps_raw = stream.get("r_frame_rate", "")
        fps = _parse_fps(fps_raw)
        duration = _to_float(stream.get("duration"))
        total_frames = _to_int(stream.get("nb_frames"))
        return {"fps": fps, "duration": duration, "total_frames": total_frames}
    except Exception:
        return {}


def _parse_fps(value: str) -> float | None:
    if not value:
        return None
    value = value.strip()
    result = None
    if "/" in value:
        try:
            a, b = value.split("/")
            result = float(a) / float(b)
        except Exception:
            return None
    else:
        try:
            result = float(value)
        except Exception:
            return None
    return result if math.isfinite(result) else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except Exception:
        return None
    return result if math.isfinite(result) else None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except Exception:
        return None


def load_splits(splits_dir: Path) -> dict[str, dict[str, Any]]:
    """仅读取 v2 划分文件，返回 video_id 到 split/fold 的映射。"""
    mapping: dict[str, dict[str, Any]] = {}
    assignments: dict[str, set[str]] = defaultdict(set)

    pattern = re.compile(r"^(fold_\d+_(?:train|val)|test)$")
    for path in sorted(splits_dir.glob("*.json")):
        if not pattern.match(path.stem):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        split_name = data.get("split")
        if split_name is None:
            if path.stem == "test":
                split_name = "test"
            elif path.stem.endswith("_val"):
                split_name = "val"
            else:
                split_name = "train"
        for vid in data.get("video_ids", []):
            assignments[vid].add(path.stem)
            mapping[vid] = {"split": split_name, "fold": path.stem}

    for vid, stems in assignments.items():
        sorted_stems = sorted(stems)
        if "test" in stems:
            primary_split = "test"
            primary_fold = "test"
        else:
            val_stems = [s for s in sorted_stems if s.endswith("_val")]
            if val_stems:
                primary_fold = val_stems[0]
                primary_split = "val"
            else:
                primary_fold = sorted_stems[0]
                primary_split = "train" if primary_fold.endswith("_train") else primary_fold
        mapping[vid] = {
            "split": primary_split,
            "fold": primary_fold,
            "fold_assignments": sorted_stems,
        }

    return mapping


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def compute_fracture_between(
    sampled_frames: list[dict[str, Any]], event_frame: int | None
) -> list[int] | None:
    """根据采样帧与真实断裂帧计算严格相邻的 fracture_between [i, i+1]。"""
    if event_frame is None or not sampled_frames:
        return None
    originals = [f["original_frame"] for f in sampled_frames]
    n = len(originals)
    if event_frame <= originals[0] or event_frame > originals[-1]:
        return None
    for i in range(n):
        if originals[i] == event_frame:
            if i > 0 and originals[i - 1] < event_frame:
                return [i - 1, i]
            return None
    for i in range(n - 1):
        if originals[i] < event_frame < originals[i + 1]:
            return [i, i + 1]
    return None


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(args, capture_output=True, check=False)


def crop_video(input_path: Path, output_path: Path, start: float, end: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(input_path),
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        "-an",
        "-avoid_negative_ts", "make_zero",
        str(output_path),
    ]
    _run_ffmpeg(cmd)


def copy_as_subvideo(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(input_path), str(output_path))


def extract_sampled_frames(subvideo_path: Path, output_dir: Path, n: int, duration: float) -> list[Path]:
    """使用 ffmpeg 的 fps filter 一次抽取与子视频时长对应的 N 帧。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    if n <= 0:
        return []
    if n == 1:
        cmd = [
            "ffmpeg", "-y", "-i", str(subvideo_path),
            "-vf", "select='eq(n,0)'",
            "-vframes", "1",
            "-q:v", "2",
            str(output_dir / "frame_%04d.jpg"),
        ]
    else:
        fps_val = (n - 1) / duration
        cmd = [
            "ffmpeg", "-y", "-i", str(subvideo_path),
            "-vf", f"fps={fps_val}:start_time=0",
            "-vframes", str(n),
            "-q:v", "2",
            "-start_number", "0",
            str(output_dir / "frame_%04d.jpg"),
        ]
    _run_ffmpeg(cmd)
    return sorted(output_dir.glob("frame_*.jpg"))


def _source_video_path(rec: dict[str, Any]) -> Path:
    source_path = Path(rec["video_path"])
    if not source_path.is_absolute():
        source_path = PROJECT_ROOT / source_path
    return source_path


def _create_preprocessor(name: str, max_frames: int, model_path: str) -> VideoPreprocessor:
    """根据 CLI 选择构造预处理器实例。"""
    if name == "minicpm":
        return MiniCPMVideoPreprocessor(
            model_path_or_name=model_path, max_frames=max_frames
        )
    raise ValueError(f"未知预处理器: {name}")


def _processor_info(preprocessor: VideoPreprocessor | None) -> dict[str, Any] | None:
    """将预处理器 get_info() 转为可序列化字典。"""
    if preprocessor is None:
        return None
    info = preprocessor.get_info()
    return {
        "name": info.name,
        "version": info.version,
        "max_frames": info.max_frames,
        "backend": info.backend,
    }


def _preprocessor_sample(
    preprocessor: VideoPreprocessor | None,
    video_path: Path,
    start_time: float,
    end_time: float,
) -> list[dict[str, Any]]:
    """调用预处理器 sample 并转换为可序列化的帧映射字典列表。"""
    if preprocessor is None:
        return []
    mappings = preprocessor.sample(str(video_path), float(start_time), float(end_time))
    return [
        {
            "input_index": m.input_index,
            "original_frame": m.original_frame,
            "timestamp": round(m.timestamp, 4),
        }
        for m in mappings
    ]


def _try_adjust_window_with_preprocessor(
    preprocessor: VideoPreprocessor,
    video_path: Path,
    event_frame: int,
    start_time: float,
    end_time: float,
    duration: float | None,
) -> tuple[list[dict[str, Any]], float, float] | None:
    """当默认窗口无法产生合法 fracture_between 时，尝试 ±1s 调整。"""
    candidates = [
        (start_time - 1.0, end_time + 1.0),
        (start_time - 1.0, end_time),
        (start_time, end_time + 1.0),
        (start_time + 1.0, end_time - 1.0),
        (start_time + 1.0, end_time),
        (start_time, end_time - 1.0),
        (start_time - 1.0, end_time - 1.0),
        (start_time + 1.0, end_time + 1.0),
    ]
    seen: set[tuple[float, float]] = set()
    for st, et in candidates:
        st = max(0.0, st)
        if duration is not None:
            et = min(duration, et)
        if et <= st:
            continue
        key = (round(st, 4), round(et, 4))
        if key in seen:
            continue
        seen.add(key)
        try:
            mapping = _preprocessor_sample(preprocessor, video_path, st, et)
        except Exception:
            continue
        if compute_fracture_between(mapping, event_frame) is not None:
            return mapping, st, et
    return None


def _base_subvideo_dict(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    subvideo_id: str,
    subvideo_path: Path,
    crop_type: str,
    start_time: float,
    end_time: float,
    start_frame: int,
    end_frame: int,
    sampled: list[dict[str, Any]],
    has_fracture: bool | None,
    ftype: str,
    location: str | None,
    fracture_between: list[int] | None,
    selection_reason: str | None = None,
) -> dict[str, Any]:
    if subvideo_path.is_absolute():
        try:
            video_path_str = str(subvideo_path.relative_to(PROJECT_ROOT / "data"))
        except ValueError:
            video_path_str = str(subvideo_path)
    else:
        video_path_str = str(subvideo_path)
    return {
        "subvideo_id": subvideo_id,
        "source_video": rec["video_id"],
        "video_path": video_path_str,
        "frame_paths": [],
        "sampled_frames": sampled,
        "actual_frame_mapping": None,
        "processor_fingerprint": None,
        "processor_info": None,
        "start_time": round(start_time, 4),
        "end_time": round(end_time, 4),
        "start_frame": int(start_frame),
        "end_frame": int(end_frame),
        "duration": round(end_time - start_time, 4),
        "crop_type": crop_type,
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "fracture_between": fracture_between,
        "type": ftype,
        "location": location,
        "location_canonical": location,
        "source_type": rec["type"],
        "source_location": rec["location"],
        "fold": split_info.get("fold"),
        "split": split_info.get("split"),
        "fold_assignments": split_info.get("fold_assignments", []),
        "selection_reason": selection_reason,
        "exclusion_reason": None,
    }


def build_focus_subvideos(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
    preprocessor: VideoPreprocessor | None = None,
) -> list[dict[str, Any]]:
    """为确认断裂且时间可靠的视频生成局部聚焦子视频候选。"""
    subvideos = []
    video_id = rec["video_id"]
    fps = rec["fps"]
    total_frames = rec["total_frames"]
    duration = rec.get("duration") or 0.0
    event_frame = rec["event_frame_original"]
    if event_frame is None or fps is None or total_frames is None:
        return subvideos

    source_path = _source_video_path(rec)
    loc = rec.get("location_canonical")
    fingerprint = preprocessor.fingerprint() if preprocessor is not None else None
    info = _processor_info(preprocessor)

    for window in FOCUS_WINDOWS:
        for ratio in FOCUS_POSITIONS:
            start_frame = event_frame - round(window * ratio * fps)
            end_frame = event_frame + round(window * (1 - ratio) * fps)
            start_frame = clamp(start_frame, 0, total_frames - 1)
            end_frame = clamp(end_frame, 0, total_frames - 1)
            if start_frame >= end_frame:
                continue
            start_time = start_frame / fps
            end_time = end_frame / fps

            if preprocessor is not None:
                if generate_media:
                    try:
                        sampled = _preprocessor_sample(preprocessor, source_path, start_time, end_time)
                    except Exception as exc:
                        EXCLUSIONS.append(
                            {
                                "subvideo_id": f"{video_id}_focus_{window}s_{int(ratio * 100):02d}pct",
                                "source_video": video_id,
                                "reason": f"预处理器采样失败: {exc}",
                                "event_frame": event_frame,
                                "window": window,
                                "ratio": ratio,
                            }
                        )
                        continue
                else:
                    sampled = []
            else:
                raise RuntimeError("正式数据构建必须提供真实视频预处理器")
            fracture_between = compute_fracture_between(sampled, event_frame)

            if fracture_between is None and preprocessor is not None and generate_media:
                adjusted = _try_adjust_window_with_preprocessor(
                    preprocessor, source_path, event_frame, start_time, end_time, duration
                )
                if adjusted is not None:
                    sampled, start_time, end_time = adjusted
                    start_frame = clamp(round(start_time * fps), 0, total_frames - 1)
                    end_frame = clamp(round(end_time * fps), 0, total_frames - 1)
                    fracture_between = compute_fracture_between(sampled, event_frame)

            if generate_media and fracture_between is None:
                EXCLUSIONS.append(
                    {
                        "subvideo_id": f"{video_id}_focus_{window}s_{int(ratio * 100):02d}pct",
                        "source_video": video_id,
                        "reason": "无法生成严格相邻的 fracture_between",
                        "event_frame": event_frame,
                        "window": window,
                        "ratio": ratio,
                    }
                )
                continue

            subvideo_id = f"{video_id}_focus_{window}s_{int(ratio * 100):02d}pct"
            subvideo_path = SUBVIDEO_DIR_DEFAULT / f"{subvideo_id}.mp4"
            gen_this = generate_media and (selected_ids is None or subvideo_id in selected_ids)
            frame_paths: list[str] = []

            if gen_this:
                crop_video(source_path, subvideo_path, start_time, end_time)
                if extract_frames:
                    frame_dir = FRAME_DIR_DEFAULT / subvideo_id
                    frame_files = extract_sampled_frames(
                        subvideo_path, frame_dir, len(sampled), end_time - start_time
                    )
                    frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

            sub = _base_subvideo_dict(
                rec, split_info, subvideo_id, subvideo_path,
                crop_type=f"focus_{window}s",
                start_time=start_time, end_time=end_time,
                start_frame=start_frame, end_frame=end_frame,
                sampled=sampled,
                has_fracture=True,
                ftype=rec["type"],
                location=loc,
                fracture_between=fracture_between,
                selection_reason="focus_positive",
            )
            sub["event_position_ratio"] = ratio
            sub["frame_paths"] = frame_paths
            sub["actual_frame_mapping"] = sampled
            sub["processor_fingerprint"] = fingerprint
            sub["processor_info"] = info
            subvideos.append(sub)
    return subvideos


def _build_clip_candidate(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    crop_type: str,
    start_time: float,
    end_time: float,
    subvideo_id: str,
    generate_media: bool,
    extract_frames: bool,
    selected_ids: set[str] | None,
    selection_reason: str | None = None,
    preprocessor: VideoPreprocessor | None = None,
) -> dict[str, Any] | None:
    """构造一个负样本候选元数据，并在需要时生成媒体文件。"""
    video_id = rec["video_id"]
    fps = rec["fps"]
    total_frames = rec["total_frames"]
    if fps is None or total_frames is None:
        return None

    start_frame = clamp(round(start_time * fps), 0, total_frames - 1)
    end_frame = clamp(round(end_time * fps), 0, total_frames - 1)
    if start_frame >= end_frame:
        return None
    start_time = start_frame / fps
    end_time = end_frame / fps

    source_path = _source_video_path(rec)
    subvideo_path = SUBVIDEO_DIR_DEFAULT / f"{subvideo_id}.mp4"
    frame_paths: list[str] = []
    fingerprint = preprocessor.fingerprint() if preprocessor is not None else None
    info = _processor_info(preprocessor)

    if preprocessor is not None:
        if generate_media:
            try:
                sampled = _preprocessor_sample(preprocessor, source_path, start_time, end_time)
            except Exception as exc:
                EXCLUSIONS.append(
                    {
                        "subvideo_id": subvideo_id,
                        "source_video": video_id,
                        "reason": f"预处理器采样失败: {exc}",
                        "crop_type": crop_type,
                    }
                )
                return None
        else:
            sampled = []
    else:
        raise RuntimeError("正式数据构建必须提供真实视频预处理器")

    gen_this = generate_media and (selected_ids is None or subvideo_id in selected_ids)
    if gen_this:
        crop_video(source_path, subvideo_path, start_time, end_time)
        if extract_frames:
            frame_dir = FRAME_DIR_DEFAULT / subvideo_id
            frame_files = extract_sampled_frames(
                subvideo_path, frame_dir, len(sampled), end_time - start_time
            )
            frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

    sub = _base_subvideo_dict(
        rec, split_info, subvideo_id, subvideo_path,
        crop_type=crop_type,
        start_time=start_time, end_time=end_time,
        start_frame=start_frame, end_frame=end_frame,
        sampled=sampled,
        has_fracture=False,
        ftype="未断裂",
        location=None,
        fracture_between=None,
        selection_reason=selection_reason or crop_type,
    )
    sub["frame_paths"] = frame_paths
    sub["actual_frame_mapping"] = sampled
    sub["processor_fingerprint"] = fingerprint
    sub["processor_info"] = info
    return sub


def _pre_event_windows(
    duration: float,
    event_time: float,
    clip_len: float,
    min_gap: float = 1.0,
) -> list[tuple[float, float]]:
    """生成结束时间不晚于 event_time - min_gap 的固定长度前事件窗口。"""
    region_end = event_time - min_gap
    if region_end <= 0 or region_end < clip_len:
        return []
    # 前/中/后：在 [0, region_end - clip_len] 内取前、中、后三个位置
    max_start = region_end - clip_len
    positions = [0.0, max_start / 2, max_start]
    windows = []
    for st in positions:
        ed = min(st + clip_len, region_end)
        st = max(0.0, ed - clip_len)
        if ed - st >= clip_len * 0.8:
            windows.append((st, ed))
    # 去重并保持顺序
    seen = set()
    unique = []
    for w in windows:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique


def _post_event_windows(
    duration: float,
    event_time: float,
    clip_len: float,
    min_gap: float = 1.0,
) -> list[tuple[float, float]]:
    """生成起始时间不早于 event_time + min_gap 的后事件困难负样本窗口。"""
    region_start = event_time + min_gap
    if region_start >= duration or duration - region_start < clip_len * 0.8:
        return []
    available = duration - region_start
    n = min(2, max(1, int(available // clip_len)))
    step = (available - clip_len) / max(1, n - 1) if n > 1 else 0.0
    windows = []
    for k in range(n):
        st = region_start + k * step
        ed = min(st + clip_len, duration)
        st = max(region_start, ed - clip_len)
        if ed - st >= clip_len * 0.8:
            windows.append((st, ed))
    return windows


def build_neg_before_after(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
    preprocessor: VideoPreprocessor | None = None,
) -> list[dict[str, Any]]:
    """为断裂视频生成断裂前负样本（≥1s 安全间隔）与少量断裂后困难负样本。"""
    subvideos: list[dict[str, Any]] = []
    video_id = rec["video_id"]
    fps = rec["fps"]
    total_frames = rec["total_frames"]
    duration = rec.get("duration")
    event_time = rec["event_time"]
    if event_time is None or fps is None or total_frames is None or duration is None:
        return subvideos

    candidates: list[tuple[str, float, float, str, str]] = []

    # 断裂前负样本：3s/10s/30s 前/中/后位置，与事件保持 ≥1s 间隔
    for clip_len in NEG_CLIP_DURATIONS:
        for idx, (st, ed) in enumerate(_pre_event_windows(duration, event_time, clip_len), start=1):
            subvideo_id = f"{video_id}_neg_before_{int(clip_len)}s_{idx:02d}"
            candidates.append(("neg_before", st, ed, subvideo_id, "pre_event_negative"))

    # 少量断裂后困难负样本：所有采样帧晚于事件
    for clip_len in [3, 5]:
        for idx, (st, ed) in enumerate(_post_event_windows(duration, event_time, clip_len), start=1):
            subvideo_id = f"{video_id}_neg_after_{int(clip_len)}s_{idx:02d}"
            candidates.append(("neg_after", st, ed, subvideo_id, "post_event_hard_negative"))

    # 每源上限 12 条：优先保留前后近事件窗口
    if len(candidates) > 12:
        candidates = candidates[:12]

    for crop_type, st, ed, subvideo_id, reason in candidates:
        sub = _build_clip_candidate(
            rec, split_info, crop_type, st, ed, subvideo_id,
            generate_media, extract_frames, selected_ids, selection_reason=reason,
            preprocessor=preprocessor,
        )
        if sub is not None:
            subvideos.append(sub)
    return subvideos


def _fixed_position_windows(duration: float, clip_len: float) -> list[tuple[float, float]]:
    """前/中/后三个固定位置窗口。"""
    if duration < clip_len * 0.8:
        return []
    centers = [clip_len / 2, duration / 2, duration - clip_len / 2]
    windows = []
    for center in centers:
        st = max(0.0, center - clip_len / 2)
        ed = min(duration, st + clip_len)
        st = max(0.0, ed - clip_len)
        windows.append((st, ed))
    return windows


def build_non_fracture_clips(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
    preprocessor: VideoPreprocessor | None = None,
) -> list[dict[str, Any]]:
    """为确认未断裂视频生成 3s/10s/30s 前/中/后固定位置负样本。"""
    subvideos: list[dict[str, Any]] = []
    video_id = rec["video_id"]
    duration = rec.get("duration")
    fps = rec.get("fps")
    total_frames = rec.get("total_frames")
    if duration is None or fps is None or total_frames is None:
        return subvideos

    candidates: list[tuple[float, float, str]] = []
    for clip_len in NEG_CLIP_DURATIONS:
        for idx, (st, ed) in enumerate(_fixed_position_windows(duration, clip_len), start=1):
            subvideo_id = f"{video_id}_neg_pos_{int(clip_len)}s_{idx:02d}"
            candidates.append((st, ed, subvideo_id))

    for st, ed, subvideo_id in candidates:
        sub = _build_clip_candidate(
            rec, split_info, "neg_position", st, ed, subvideo_id,
            generate_media, extract_frames, selected_ids, selection_reason="fixed_negative",
            preprocessor=preprocessor,
        )
        if sub is not None:
            subvideos.append(sub)
    return subvideos


def build_full_subvideo(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    preprocessor: VideoPreprocessor | None = None,
) -> dict[str, Any] | None:
    """生成全时长样本元数据；不复制视频文件，video_path 指向源视频。"""
    video_id = rec["video_id"]
    source_path = _source_video_path(rec)
    if not source_path.exists():
        return None

    has_fracture_canonical = rec.get("has_fracture_canonical")
    rec_type = rec["type"]
    fracture_between: list[int] | None = None

    # 视频异常全时长样本保留其特有语义
    if rec_type == VIDEO_ANOMALY_TYPE:
        if has_fracture_canonical is True:
            # 确认断裂但时间不可靠
            crop_type = "full_anomaly_time_unknown"
            ftype = VIDEO_ANOMALY_TYPE
            loc = None
            fracture_between = None
        else:
            # 是否断裂不确定
            crop_type = "full_anomaly_presence_unknown"
            ftype = VIDEO_ANOMALY_TYPE
            loc = None
            fracture_between = None
    elif rec_type == "未夹紧":
        crop_type = "full_not_clamped"
        ftype = "未夹紧"
        loc = None
        fracture_between = None
    elif has_fracture_canonical is True:
        crop_type = "full_pos"
        ftype = rec_type
        loc = rec.get("location_canonical")
        if loc not in ("inside_gauge", "outside_gauge"):
            loc = None
    else:
        crop_type = "full_neg"
        ftype = "未断裂" if rec_type == "未断裂" else "未断裂"
        loc = None
        fracture_between = None

    subvideo_id = f"{video_id}_full"
    original_video_path = Path("data") / "01_videos" / f"{video_id}.mp4"

    fps = rec.get("fps")
    total_frames = rec.get("total_frames")
    duration = rec.get("duration")
    start_time = 0.0
    start_frame = 0
    end_frame = (total_frames - 1) if total_frames else None
    end_time = (end_frame / fps) if total_frames and fps else duration
    frame_paths: list[str] = []
    sampled: list[dict[str, Any]] = []
    fingerprint = preprocessor.fingerprint() if preprocessor is not None else None
    info = _processor_info(preprocessor)

    if fps is not None and total_frames is not None and end_time is not None:
        if preprocessor is not None:
            if generate_media:
                try:
                    sampled = _preprocessor_sample(preprocessor, source_path, start_time, end_time)
                except Exception as exc:
                    EXCLUSIONS.append(
                        {
                            "subvideo_id": subvideo_id,
                            "source_video": video_id,
                            "reason": f"预处理器采样失败: {exc}",
                        }
                    )
                    return None
            else:
                sampled = []
        else:
            raise RuntimeError("正式数据构建必须提供真实视频预处理器")
        if extract_frames and generate_media:
            frame_dir = FRAME_DIR_DEFAULT / subvideo_id
            frame_files = extract_sampled_frames(source_path, frame_dir, len(sampled), end_time)
            frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

    event_frame = rec["event_frame_original"]
    if fracture_between is None and has_fracture_canonical is True and rec_type in FRACTURE_TYPES:
        fracture_between = compute_fracture_between(sampled, event_frame)
        if fracture_between is None and preprocessor is not None and generate_media:
            adjusted = _try_adjust_window_with_preprocessor(
                preprocessor, source_path, event_frame, start_time, end_time, duration
            )
            if adjusted is not None:
                sampled, start_time, end_time = adjusted
                if fps is not None:
                    start_frame = clamp(round(start_time * fps), 0, total_frames - 1)
                    end_frame = clamp(round(end_time * fps), 0, total_frames - 1)
                fracture_between = compute_fracture_between(sampled, event_frame)
        if generate_media and fracture_between is None:
            EXCLUSIONS.append(
                {
                    "subvideo_id": subvideo_id,
                    "source_video": video_id,
                    "reason": "全时长正样本无法生成严格相邻的 fracture_between",
                    "event_frame": event_frame,
                }
            )
            return None

    sub = _base_subvideo_dict(
        rec, split_info, subvideo_id, original_video_path,
        crop_type=crop_type,
        start_time=start_time, end_time=end_time or 0.0,
        start_frame=start_frame, end_frame=end_frame or 0,
        sampled=sampled,
        has_fracture=has_fracture_canonical,
        ftype=ftype,
        location=loc,
        fracture_between=fracture_between,
        selection_reason="full_video",
    )
    sub["frame_paths"] = frame_paths
    sub["actual_frame_mapping"] = sampled
    sub["processor_fingerprint"] = fingerprint
    sub["processor_info"] = info
    return sub


def update_subvideo_metadata(sub: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    """基于现有 mp4/frame 文件重新计算派生元数据（快速模式，不重编码）。"""
    sub = dict(sub)
    fps = rec.get("fps")
    total_frames = rec.get("total_frames")
    event_frame = rec.get("event_frame_original")

    if sub.get("crop_type").startswith("full") and total_frames and fps:
        sub["end_frame"] = int(total_frames - 1)
        sub["end_time"] = round(sub["end_frame"] / fps, 4)
        sub["duration"] = sub["end_time"]

    has_fracture = sub.get("has_fracture_canonical", sub.get("has_fracture"))
    sampled = sub.get("actual_frame_mapping") or sub.get("sampled_frames")
    if not sampled:
        raise RuntimeError("快速模式缺少真实处理器帧映射，拒绝按 FPS 重新推算")
    if has_fracture is True and event_frame is not None:
        sub["fracture_between"] = compute_fracture_between(sampled, event_frame)
    else:
        sub["fracture_between"] = None

    sub["sampled_frames"] = sampled
    return sub


def build_subvideos_for_record(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
    preprocessor: VideoPreprocessor | None = None,
) -> list[dict[str, Any]]:
    """为单个视频生成候选子视频列表；测试集视频不生成。"""
    if split_info.get("split") == "test":
        return []

    results: list[dict[str, Any]] = []
    video_id = rec["video_id"]
    full_id = f"{video_id}_full"
    gen_full = generate_media and (selected_ids is None or full_id in selected_ids)

    full = build_full_subvideo(rec, split_info, gen_full, extract_frames, preprocessor)
    if full is not None:
        if selected_ids is None or full_id in selected_ids:
            results.append(full)

    rec_type = rec["type"]
    has_fracture_canonical = rec.get("has_fracture_canonical")

    # 未夹紧与视频异常只保留完整视频
    if rec_type in ("未夹紧", VIDEO_ANOMALY_TYPE):
        return results

    # 确认未断裂：完整视频 + 固定位置负样本
    if rec_type == "未断裂" or has_fracture_canonical is False:
        results.extend(build_non_fracture_clips(rec, split_info, generate_media, extract_frames, selected_ids, preprocessor))
        return results

    # 确认断裂且时间可靠：完整视频 + 聚焦 + 断裂前/后负样本
    if has_fracture_canonical is True and rec_type in FRACTURE_TYPES:
        results.extend(build_focus_subvideos(rec, split_info, generate_media, extract_frames, selected_ids, preprocessor))
        results.extend(build_neg_before_after(rec, split_info, generate_media, extract_frames, selected_ids, preprocessor))

    return results


def load_split_definitions(splits_dir: Path) -> dict[str, set[str]]:
    """读取划分文件，返回 split_name -> video_id 集合。"""
    split_defs: dict[str, set[str]] = {}
    pattern = re.compile(r"^(fold_\d+_(?:train|val)|test)$")
    for path in sorted(splits_dir.glob("*.json")):
        if not pattern.match(path.stem):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        split_defs[path.stem] = set(data.get("video_ids", []))
    return split_defs


def _sample_with_priority(
    cands: list[dict[str, Any]], target: int
) -> set[str]:
    """优先保留全时长样本，再从片段中随机采样至目标数量。"""
    import random

    if target >= len(cands):
        return {c["subvideo_id"] for c in cands}
    full_ids = {c["subvideo_id"] for c in cands if c.get("crop_type", "").startswith("full")}
    other = [c for c in cands if c["subvideo_id"] not in full_ids]
    need = max(0, target - len(full_ids))
    selected_other = set()
    if need > 0 and other:
        selected_other = {c["subvideo_id"] for c in random.sample(other, min(need, len(other)))}
    if len(full_ids) > target:
        return set(random.sample(sorted(full_ids), target))
    return full_ids | selected_other


def _select_train_candidates(
    all_candidates: list[dict[str, Any]],
    split_defs: dict[str, set[str]],
    n_folds: int = 3,
    seed: int = 42,
) -> None:
    """按正:负 1:1~2:1 为每个 fold 训练集选择样本，并在候选元数据上标记 selected_splits。"""
    import random

    random.seed(seed)

    for cand in all_candidates:
        assignments = set(cand.get("fold_assignments", []))
        cand["selected_splits"] = sorted(assignments - {"test"})

    for i in range(n_folds):
        train_name = f"fold_{i}_train"
        train_ids = split_defs.get(train_name, set())
        train_cands = [c for c in all_candidates if c.get("source_video") in train_ids]

        def _is_pos(c: dict[str, Any]) -> bool:
            hf = c.get("has_fracture_canonical", c.get("has_fracture"))
            return hf is True and c.get("type") in FRACTURE_TYPES

        pos = [c for c in train_cands if _is_pos(c)]
        neg = [c for c in train_cands if not _is_pos(c)]

        pos_n = len(pos)
        neg_n = len(neg)

        if neg_n == 0:
            target_pos = pos_n
            target_neg = 0
        else:
            target_pos = min(pos_n, 2 * neg_n)
            target_neg = min(neg_n, target_pos)

        selected_pos = _sample_with_priority(pos, target_pos)
        selected_neg = _sample_with_priority(neg, target_neg)

        for c in train_cands:
            if c["subvideo_id"] not in selected_pos and c["subvideo_id"] not in selected_neg:
                splits = list(c["selected_splits"])
                if train_name in splits:
                    splits.remove(train_name)
                c["selected_splits"] = splits


def _subvideo_output_path(sub: dict[str, Any]) -> Path:
    """由子视频元数据中的相对路径解析出绝对输出路径。"""
    rel = sub["video_path"]
    if rel.startswith("data/"):
        return PROJECT_ROOT / rel
    return PROJECT_ROOT / "data" / rel


def _generate_media_for_candidate(
    sub: dict[str, Any],
    rec: dict[str, Any],
    frame_dir: Path,
    extract_frames: bool = False,
) -> dict[str, Any]:
    """根据已生成的候选元数据，仅生成 mp4/帧图媒体文件。"""
    source_path = _source_video_path(rec)
    subvideo_path = _subvideo_output_path(sub)
    crop_type = sub["crop_type"]

    if not crop_type.startswith("full"):
        crop_video(source_path, subvideo_path, sub["start_time"], sub["end_time"])

    if extract_frames:
        mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []
        n = len(mapping)
        if n > 0:
            frame_dir_out = frame_dir / sub["subvideo_id"]
            src_for_frames = source_path if crop_type.startswith("full") else subvideo_path
            frame_files = extract_sampled_frames(
                src_for_frames, frame_dir_out, n, sub["duration"]
            )
            sub["frame_paths"] = [
                str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files
            ]
    return sub


def main():
    global FOCUS_WINDOWS, FOCUS_POSITIONS, VIDEO_MAXLEN, NEG_CLIP_DURATIONS
    parser = argparse.ArgumentParser(description="子视频生成器（先选后生成）")
    parser.add_argument("--video-meta", type=Path, default=VIDEO_META_DEFAULT)
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR_DEFAULT)
    parser.add_argument("--subvideo-dir", type=Path, default=SUBVIDEO_DIR_DEFAULT)
    parser.add_argument("--frame-dir", type=Path, default=FRAME_DIR_DEFAULT)
    parser.add_argument("--output-meta", type=Path, default=SUBVIDEOS_META_DEFAULT)
    parser.add_argument("--focus-windows", type=float, nargs="+", default=FOCUS_WINDOWS)
    parser.add_argument("--focus-positions", type=float, nargs="+", default=FOCUS_POSITIONS)
    parser.add_argument("--neg-clip-durations", type=float, nargs="+", default=NEG_CLIP_DURATIONS)
    parser.add_argument(
        "--preprocessor",
        choices=["minicpm"],
        default="minicpm",
        help="正式数据构建固定使用 MiniCPM 实际处理器选帧",
    )
    parser.add_argument(
        "--model",
        default=str(PROJECT_ROOT / "models" / "minicpm-v-4.5"),
        help="MiniCPM-V 4.5 模型目录；须与训练和校准使用同一版本",
    )
    parser.add_argument(
        "--extract-frames",
        action="store_true",
        help="为子视频抽取采样帧图（默认不抽帧）",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="仅更新已有子视频元数据，避免重新编码/抽帧 mp4",
    )
    parser.add_argument(
        "--skip-healthcheck",
        action="store_true",
        help="跳过预处理器健康检查（处理器加载成功后直接开始构建子视频）",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    records = json.loads(args.video_meta.read_text(encoding="utf-8"))
    video_meta_dict = {r["video_id"]: r for r in records}
    split_mapping = load_splits(args.splits_dir)
    split_defs = load_split_definitions(args.splits_dir)

    FOCUS_WINDOWS = [int(w) if w == int(w) else w for w in args.focus_windows]
    FOCUS_POSITIONS = args.focus_positions
    NEG_CLIP_DURATIONS = [int(w) if w == int(w) else w for w in args.neg_clip_durations]
    VIDEO_MAXLEN = 8

    preprocessor = _create_preprocessor(args.preprocessor, VIDEO_MAXLEN, args.model)
    if not args.skip_healthcheck:
        if not preprocessor.healthcheck():
            info = preprocessor.get_info()
            raise RuntimeError(f"预处理器健康检查失败: {info.name} ({info.backend})")
    else:
        print("跳过预处理器健康检查")
    print(f"使用预处理器: {preprocessor.get_info().name}, fingerprint={preprocessor.fingerprint()}")

    if args.fast and args.output_meta.exists():
        print(f"快速模式：读取已有元数据 {args.output_meta}")
        existing = json.loads(args.output_meta.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            existing_subs = existing.get("subvideos", [])
            existing_candidates = existing.get("candidates", existing_subs)
            existing_exclusions = existing.get("exclusions", [])
        else:
            existing_subs = existing
            existing_candidates = existing
            existing_exclusions = []
        all_subvideos: list[dict[str, Any]] = []
        for sub in existing_subs:
            rec = video_meta_dict.get(sub.get("source_video"))
            if rec is None:
                all_subvideos.append(sub)
                continue
            updated = update_subvideo_metadata(sub, rec)
            all_subvideos.append(updated)
        EXCLUSIONS.extend(existing_exclusions)
        all_candidates = existing_candidates
        print(f"快速模式：共更新 {len(all_subvideos)} 条子视频元数据")
    else:
        if args.fast:
            print("快速模式：未发现已有元数据，退回到完整生成")

        EXCLUSIONS.clear()

        print("阶段 1：生成候选子视频清单...")
        all_candidates: list[dict[str, Any]] = []
        for rec in records:
            video_id = rec["video_id"]
            split_info = split_mapping.get(video_id, {"split": "unknown", "fold": "unknown"})
            if split_info.get("split") == "test":
                print(f"  跳过 {video_id}（测试集）")
                continue
            print(f"  处理 {video_id}（{split_info.get('split')}）...")
            subs = build_subvideos_for_record(
                rec, split_info, generate_media=False, extract_frames=False, preprocessor=preprocessor
            )
            all_candidates.extend(subs)
        print(f"候选子视频：{len(all_candidates)} 条")

        print("阶段 2：训练集候选选择...")
        _select_train_candidates(all_candidates, split_defs, n_folds=3, seed=args.seed)
        selected_count = sum(1 for c in all_candidates if c.get("selected_splits"))
        print(f"选中子视频：{selected_count} 条")

        print("阶段 3：生成选中子视频媒体...")
        selected_ids = {c["subvideo_id"] for c in all_candidates if c.get("selected_splits")}
        total = len(selected_ids)
        print(f"  计划生成 {total} 个选中子视频")

        generated_by_id: dict[str, dict[str, Any]] = {}
        completed = 0
        for cand in all_candidates:
            if cand["subvideo_id"] not in selected_ids:
                continue
            rec = video_meta_dict.get(cand["source_video"])
            if rec is None:
                continue
            completed += 1
            crop_type = cand.get("crop_type", "?")
            start = cand.get("start_time", 0)
            end = cand.get("end_time", 0)
            print(f"  [{completed}/{total}] {cand['subvideo_id']} ({crop_type}, {start:.1f}s→{end:.1f}s)...")
            sub = _generate_media_for_candidate(
                cand, rec, args.frame_dir, extract_frames=args.extract_frames
            )
            generated_by_id[sub["subvideo_id"]] = sub

        all_subvideos = [generated_by_id[c["subvideo_id"]] for c in all_candidates if c["subvideo_id"] in generated_by_id]
        print(f"实际生成媒体：{len(all_subvideos)} 条")

    args.subvideo_dir.mkdir(parents=True, exist_ok=True)
    args.frame_dir.mkdir(parents=True, exist_ok=True)
    args.output_meta.parent.mkdir(parents=True, exist_ok=True)

    if args.seed is None:
        raise ValueError("--seed must be set for reproducibility")

    exclusion_stats: dict[str, Any] = {
        "total_exclusions": len(EXCLUSIONS),
        "reason_distribution": {},
        "source_distribution": {},
    }
    if EXCLUSIONS:
        reason_counter: defaultdict[str, int] = defaultdict(int)
        source_counter: defaultdict[str, int] = defaultdict(int)
        for exc in EXCLUSIONS:
            reason_counter[exc.get("reason", "unknown")] += 1
            source_counter[exc.get("source_video", "unknown")] += 1
        exclusion_stats["reason_distribution"] = dict(reason_counter)
        exclusion_stats["source_distribution"] = dict(source_counter)

    output_payload: dict[str, Any] = {
        "subvideos": all_subvideos,
        "candidates": all_candidates,
        "exclusions": EXCLUSIONS,
        "exclusion_stats": exclusion_stats,
        "preprocessor_fingerprint": preprocessor.fingerprint(),
        "seed": args.seed,
    }
    with open(args.output_meta, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"完成：共 {len(all_subvideos)} 个子视频，元数据写入 {args.output_meta}")


if __name__ == "__main__":
    main()
