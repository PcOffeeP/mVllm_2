#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子视频生成器

按设计文档生成 7 类子视频：
- 全时长正/负样本
- 局部聚焦 3s/10s/30s（5 个位置比例）
- 断裂前/后负样本
- 无断裂视频（全时长负样本）

主产物：data/02_subvideos/*.mp4
帧图缓存：data/03_frames/{subvideo_id}/frame_*.jpg
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

VIDEO_META_DEFAULT = PROJECT_ROOT / "data" / "metadata" / "video_meta.json"
SPLITS_DIR_DEFAULT = PROJECT_ROOT / "data" / "03_splits"
SUBVIDEO_DIR_DEFAULT = PROJECT_ROOT / "data" / "02_subvideos"
FRAME_DIR_DEFAULT = PROJECT_ROOT / "data" / "03_frames"
SUBVIDEOS_META_DEFAULT = PROJECT_ROOT / "data" / "metadata" / "subvideos_meta.json"

FOCUS_WINDOWS = [3, 10, 30]
FOCUS_POSITIONS = [0.2, 0.35, 0.5, 0.65, 0.8]
NEG_BEFORE_DURATION = 5
NEG_AFTER_DURATION = 5
VIDEO_FPS = 8.0
VIDEO_MAXLEN = 36

FRACTURE_TYPES = [
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
]

NON_FRACTURE_TYPES = ["未断裂", "未夹紧", "视频异常"]

# 全局排除记录，用于汇总非法窗口/边界哨兵
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
        if total_frames is None and duration and fps:
            total_frames = int(round(duration * fps))
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
    """仅读取新 interval 方案划分文件，返回 video_id 到 split/fold 的映射。

    识别 ``fold_*_{train,val}.json`` 与 ``test.json``，忽略旧基线文件。
    每个视频可能属于多个 fold 划分，因此额外返回 ``fold_assignments`` 列表。
    """
    import re

    mapping: dict[str, dict[str, Any]] = {}
    assignments: dict[str, set[str]] = defaultdict(set)

    pattern = re.compile(r"^(fold_\d+_(?:train|val)|test)$")
    for path in sorted(splits_dir.glob("*.json")):
        if not pattern.match(path.stem):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        split_name = data.get("split")
        if split_name is None:
            # 从文件名推断 split 标签
            if path.stem == "test":
                split_name = "test"
            elif path.stem.endswith("_val"):
                split_name = "val"
            else:
                split_name = "train"
        for vid in data.get("video_ids", []):
            assignments[vid].add(path.stem)
            # 以当前文件作为最新 fold 信息（后续文件按字母序覆盖）
            mapping[vid] = {"split": split_name, "fold": path.stem}

    # 补充完整 fold 归属列表，并选择更稳定的 primary split/fold
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


def compute_n_sampled_frames(duration: float, total_frames: int, video_fps: float, video_maxlen: int) -> int:
    if duration <= 0 or total_frames <= 0:
        return 0
    n_by_fps = max(1, int(math.floor(duration * video_fps)))
    return min(total_frames, video_maxlen, n_by_fps)


def compute_sampled_frames_with_n(
    start_time: float,
    end_time: float,
    source_fps: float,
    source_total_frames: int,
    n: int,
) -> list[dict[str, Any]]:
    """按给定帧数 n 在 [start_time, end_time] 内均匀采样帧映射。"""
    if n <= 0:
        return []
    duration = end_time - start_time
    if duration <= 0:
        return []

    frames = []
    for k in range(n):
        if n == 1:
            t = start_time
        else:
            t = start_time + k * duration / (n - 1)
        original_frame = clamp(round(t * source_fps), 0, source_total_frames - 1)
        frames.append(
            {
                "input_index": k,
                "original_frame": original_frame,
                "timestamp": round(t, 4),
            }
        )
    return frames


def compute_sampled_frames(
    start_time: float,
    end_time: float,
    source_fps: float,
    source_total_frames: int,
    video_fps: float,
    video_maxlen: int,
) -> list[dict[str, Any]]:
    """按 LLaMA-Factory uniform 采样规则计算采样帧映射。"""
    duration = end_time - start_time
    if duration <= 0:
        return []
    total_frames_in_clip = max(1, int(round(duration * source_fps)))
    n = compute_n_sampled_frames(duration, total_frames_in_clip, video_fps, video_maxlen)
    return compute_sampled_frames_with_n(start_time, end_time, source_fps, source_total_frames, n)


def compute_fracture_between(
    sampled_frames: list[dict[str, Any]], event_frame: int | None
) -> list[int] | None:
    """根据采样帧与真实断裂帧计算严格相邻的 ``fracture_between``。

    只接受 ``[i, i+1]``，且满足 ``sampled_frame[i] < event_frame <= sampled_frame[i+1]``。
    边界哨兵 ``[0,0]`` / ``[N-1,N-1]`` 以及无法包围事件帧的情况返回 ``None``，
    由调用方调整窗口或排除该片段。
    """
    if event_frame is None or not sampled_frames:
        return None
    originals = [f["original_frame"] for f in sampled_frames]
    n = len(originals)
    # 事件帧必须严格位于第一帧之后、最后一帧之前或等于最后一帧
    if event_frame <= originals[0] or event_frame > originals[-1]:
        return None
    # 恰好命中采样帧：使用左侧相邻区间 [i-1, i]（要求 i > 0 且前帧严格小于事件）
    for i in range(n):
        if originals[i] == event_frame:
            if i > 0 and originals[i - 1] < event_frame:
                return [i - 1, i]
            return None
    # 正常区间
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


def _try_adjust_focus_window(
    event_frame: int,
    window: float,
    ratio: float,
    fps: float,
    total_frames: int,
    duration: float,
) -> tuple[float, float] | None:
    """当默认聚焦窗口无法产生合法相邻 fracture_between 时，尝试小幅平移/扩展窗口。"""
    start_frame = event_frame - round(window * ratio * fps)
    end_frame = event_frame + round(window * (1 - ratio) * fps)

    # 尝试最多 ±5 帧的左右平移
    for offset in range(-5, 6):
        if offset == 0:
            continue
        sf = clamp(start_frame + offset, 0, total_frames - 1)
        ef = clamp(end_frame + offset, 0, total_frames - 1)
        if sf >= ef:
            continue
        st, et = sf / fps, ef / fps
        sampled = compute_sampled_frames(st, et, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN)
        if compute_fracture_between(sampled, event_frame) is not None:
            return st, et

    # 尝试以 0.5 倍步长扩展窗口（保持事件帧在中心方向）
    for scale in (1.25, 1.5, 2.0):
        sf = clamp(event_frame - round(window * ratio * scale * fps), 0, total_frames - 1)
        ef = clamp(event_frame + round(window * (1 - ratio) * scale * fps), 0, total_frames - 1)
        if sf >= ef:
            continue
        st, et = sf / fps, ef / fps
        sampled = compute_sampled_frames(st, et, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN)
        if compute_fracture_between(sampled, event_frame) is not None:
            return st, et
    return None


def build_focus_subvideos(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """生成局部聚焦子视频候选。默认生成媒体文件；candidate 阶段可关闭。"""
    subvideos = []
    video_id = rec["video_id"]
    fps = rec["fps"]
    total_frames = rec["total_frames"]
    duration = rec.get("duration") or 0.0
    event_frame = rec["event_frame_original"]
    if event_frame is None or fps is None or total_frames is None:
        return subvideos

    source_path = Path(rec["video_path"])
    if not source_path.is_absolute():
        source_path = PROJECT_ROOT / source_path

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

            sampled = compute_sampled_frames(
                start_time, end_time, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN
            )
            fracture_between = compute_fracture_between(sampled, event_frame)

            # 非法时先尝试调整窗口
            if fracture_between is None:
                adjusted = _try_adjust_focus_window(
                    event_frame, window, ratio, fps, total_frames, duration
                )
                if adjusted is not None:
                    start_time, end_time = adjusted
                    start_frame = clamp(round(start_time * fps), 0, total_frames - 1)
                    end_frame = clamp(round(end_time * fps), 0, total_frames - 1)
                    sampled = compute_sampled_frames(
                        start_time, end_time, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN
                    )
                    fracture_between = compute_fracture_between(sampled, event_frame)
                else:
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

            clip_duration = end_time - start_time
            subvideo_id = f"{video_id}_focus_{window}s_{int(ratio * 100):02d}pct"
            subvideo_path = SUBVIDEO_DIR_DEFAULT / f"{subvideo_id}.mp4"
            frame_paths: list[str] = []
            gen_this = generate_media and (selected_ids is None or subvideo_id in selected_ids)

            if gen_this:
                crop_video(source_path, subvideo_path, start_time, end_time)
                if extract_frames:
                    frame_dir = FRAME_DIR_DEFAULT / subvideo_id
                    frame_files = extract_sampled_frames(
                        subvideo_path, frame_dir, len(sampled), clip_duration
                    )
                    actual_n = len(frame_files)
                    if actual_n != len(sampled):
                        sampled = compute_sampled_frames_with_n(
                            start_time, end_time, fps, total_frames, actual_n
                        )
                        fracture_between = compute_fracture_between(sampled, event_frame)
                    frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

            loc = rec.get("location_canonical", rec["location"])
            subvideos.append(
                {
                    "subvideo_id": subvideo_id,
                    "source_video": video_id,
                    "video_path": str(Path(subvideo_path).relative_to(PROJECT_ROOT / "data")),
                    "frame_paths": frame_paths,
                    "sampled_frames": sampled,
                    "start_time": round(start_time, 4),
                    "end_time": round(end_time, 4),
                    "start_frame": int(start_frame),
                    "end_frame": int(end_frame),
                    "duration": round(clip_duration, 4),
                    "crop_type": f"focus_{window}s",
                    "event_position_ratio": ratio,
                    "has_fracture": True,
                    "has_fracture_canonical": True,
                    "fracture_between": fracture_between,
                    "type": rec["type"],
                    "location": loc,
                    "location_canonical": loc,
                    "source_type": rec["type"],
                    "source_location": rec["location"],
                    "fold": split_info.get("fold"),
                    "split": split_info.get("split"),
                    "fold_assignments": split_info.get("fold_assignments", []),
                }
            )
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
    selected_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """构造一个子视频候选元数据，并在需要时生成媒体文件。"""
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
    clip_duration = end_time - start_time

    subvideo_path = SUBVIDEO_DIR_DEFAULT / f"{subvideo_id}.mp4"
    frame_paths: list[str] = []

    source_path = Path(rec["video_path"])
    if not source_path.is_absolute():
        source_path = PROJECT_ROOT / source_path

    sampled = compute_sampled_frames(
        start_time, end_time, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN
    )

    gen_this = generate_media and (selected_ids is None or subvideo_id in selected_ids)
    if gen_this:
        crop_video(source_path, subvideo_path, start_time, end_time)
        if extract_frames:
            frame_dir = FRAME_DIR_DEFAULT / subvideo_id
            frame_files = extract_sampled_frames(
                subvideo_path, frame_dir, len(sampled), clip_duration
            )
            actual_n = len(frame_files)
            if actual_n != len(sampled):
                sampled = compute_sampled_frames_with_n(
                    start_time, end_time, fps, total_frames, actual_n
                )
            frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

    return {
        "subvideo_id": subvideo_id,
        "source_video": video_id,
        "video_path": str(Path(subvideo_path).relative_to(PROJECT_ROOT / "data")),
        "frame_paths": frame_paths,
        "sampled_frames": sampled,
        "start_time": round(start_time, 4),
        "end_time": round(end_time, 4),
        "start_frame": int(start_frame),
        "end_frame": int(end_frame),
        "duration": round(clip_duration, 4),
        "crop_type": crop_type,
        "event_position_ratio": None,
        "has_fracture": False,
        "has_fracture_canonical": False,
        "fracture_between": None,
        "type": "未断裂",
        "location": None,
        "location_canonical": None,
        "source_type": rec["type"],
        "source_location": rec["location"],
        "fold": split_info.get("fold"),
        "split": split_info.get("split"),
        "fold_assignments": split_info.get("fold_assignments", []),
    }


def _safe_zone_windows(
    duration: float, event_time: float, min_gap: float = 2.0, clip_len: float = 10.0, max_clips: int = 8
) -> list[tuple[float, float]]:
    """在事件两侧 ≥min_gap 的安全区生成最多 max_clips 条等距 10s 窗口。"""
    windows: list[tuple[float, float]] = []
    regions = [
        (0.0, max(0.0, event_time - min_gap)),
        (min(duration, event_time + min_gap), duration),
    ]
    for region_start, region_end in regions:
        available = region_end - region_start
        if available < clip_len:
            continue
        n = min(max_clips, max(1, int(available // clip_len)))
        # 在可用区内均匀放置 n 个 clip_len 窗口
        step = (available - clip_len) / max(1, n - 1) if n > 1 else 0.0
        for k in range(n):
            st = region_start + k * step
            ed = min(st + clip_len, region_end)
            if ed - st >= clip_len * 0.8:
                windows.append((st, ed))
    # 如果两侧总数超过上限，按长度比例截断
    if len(windows) > max_clips:
        windows = windows[:max_clips]
    return windows


def build_neg_before_after(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """为断裂视频生成干净负片段：安全区 10s 片段 + 断裂前后 5s 片段，每源上限 10 条。"""
    subvideos: list[dict[str, Any]] = []
    video_id = rec["video_id"]
    fps = rec["fps"]
    total_frames = rec["total_frames"]
    duration = rec.get("duration")
    event_frame = rec["event_frame_original"]
    event_time = rec["event_time"]
    if event_frame is None or event_time is None or fps is None or total_frames is None or duration is None:
        return subvideos

    # 断裂前后 5s 负片段（距事件各 1s 缓冲）
    near_windows = [
        ("neg_before", max(0.0, event_time - NEG_BEFORE_DURATION), event_time - 1.0),
        ("neg_after", event_time + 1.0, min(duration, event_time + NEG_AFTER_DURATION)),
    ]
    near_candidates: list[tuple[str, float, float, str]] = []
    for crop_type, st, ed in near_windows:
        if ed - st >= 0.5:
            near_candidates.append((crop_type, st, ed, f"{video_id}_{crop_type}"))

    # 安全区 10s 负片段
    safe_windows = _safe_zone_windows(duration, event_time)
    safe_candidates: list[tuple[str, float, float, str]] = []
    for idx, (st, ed) in enumerate(safe_windows, start=1):
        safe_candidates.append(("neg_safe", st, ed, f"{video_id}_neg_safe_{idx:02d}"))

    # 合计每源上限 10 条：优先保留前后片段，再保留安全区
    all_candidates = near_candidates + safe_candidates
    if len(all_candidates) > 10:
        all_candidates = all_candidates[:10]

    for crop_type, st, ed, subvideo_id in all_candidates:
        sub = _build_clip_candidate(
            rec, split_info, crop_type, st, ed, subvideo_id, generate_media, extract_frames, selected_ids
        )
        if sub is not None:
            subvideos.append(sub)
    return subvideos


def build_non_fracture_clips(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """为确认未断裂视频在 20/35/50/65/80% 位置生成 10s 负片段。"""
    subvideos: list[dict[str, Any]] = []
    video_id = rec["video_id"]
    duration = rec.get("duration")
    fps = rec.get("fps")
    total_frames = rec.get("total_frames")
    if duration is None or fps is None or total_frames is None:
        return subvideos

    clip_len = 10.0
    positions = [0.20, 0.35, 0.50, 0.65, 0.80]
    for idx, pos in enumerate(positions, start=1):
        center = duration * pos
        st = max(0.0, center - clip_len / 2)
        ed = min(duration, st + clip_len)
        if ed - st < clip_len * 0.8:
            continue
        subvideo_id = f"{video_id}_neg_pos_{idx:02d}"
        sub = _build_clip_candidate(
            rec, split_info, "neg_position", st, ed, subvideo_id, generate_media, extract_frames, selected_ids
        )
        if sub is not None:
            sub["type"] = "未断裂"
            sub["source_type"] = rec["type"]
            subvideos.append(sub)
    return subvideos


def build_not_clamped_clips(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """为未夹紧视频生成 3 条高重叠长片段（0-60%、20-80%、40-100%）。"""
    subvideos: list[dict[str, Any]] = []
    video_id = rec["video_id"]
    duration = rec.get("duration")
    fps = rec.get("fps")
    total_frames = rec.get("total_frames")
    if duration is None or fps is None or total_frames is None:
        return subvideos

    ranges = [(0.0, 0.60), (0.20, 0.80), (0.40, 1.0)]
    for idx, (r0, r1) in enumerate(ranges, start=1):
        st = duration * r0
        ed = duration * r1
        if ed - st < 1.0:
            continue
        subvideo_id = f"{video_id}_notclamped_{idx:02d}"
        sub = _build_clip_candidate(
            rec, split_info, "not_clamped_long", st, ed, subvideo_id, generate_media, extract_frames, selected_ids
        )
        if sub is not None:
            sub["type"] = "未夹紧"
            sub["source_type"] = rec["type"]
            subvideos.append(sub)
    return subvideos


def build_full_subvideo(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
) -> dict[str, Any] | None:
    """生成全时长样本元数据。

    全时长样本不复制视频文件，``video_path`` 直接指向 ``data/01_videos/{id}.mp4``。
    """
    video_id = rec["video_id"]
    source_path = Path(rec["video_path"])
    if not source_path.is_absolute():
        source_path = PROJECT_ROOT / source_path
    if not source_path.exists():
        return None

    # 治理异常/正样本冲突：优先使用 video_meta 输出的 canonical 字段；
    # 兼容旧 metadata 时，按原始字段推导 canonical。
    if "has_fracture_canonical" in rec:
        has_fracture = rec["has_fracture_canonical"]
    else:
        has_fracture = rec["has_fracture"]
        if rec.get("is_abnormal"):
            has_fracture = False
        elif has_fracture and rec["type"] not in FRACTURE_TYPES:
            has_fracture = False

    rec_type = rec["type"]
    # canonical location：断裂样本仅保留有效位置，其余全部为 null
    if has_fracture:
        rec_location = rec.get("location_canonical") or rec.get("location")
        if rec_location not in ("inside_gauge", "outside_gauge"):
            rec_location = None
    else:
        rec_location = None

    crop_type = "full_pos" if has_fracture else "full_neg"
    subvideo_id = f"{video_id}_full"
    original_video_path = Path("data") / "01_videos" / f"{video_id}.mp4"

    fps = rec.get("fps")
    total_frames = rec.get("total_frames")
    duration = rec.get("duration")
    start_time = 0.0
    start_frame = 0
    end_frame = (total_frames - 1) if total_frames else None
    # 使 end_time 与 end_frame 对齐，避免 duration 含末尾空帧间隔导致测试断言偏差
    end_time = (end_frame / fps) if total_frames and fps else duration
    frame_paths: list[str] = []
    sampled: list[dict[str, Any]] = []

    if fps is not None and total_frames is not None and end_time is not None:
        sampled = compute_sampled_frames(
            start_time, end_time, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN
        )
        if extract_frames and generate_media:
            # 全时长样本只在明确要求抽帧时才抽取审计帧
            frame_dir = FRAME_DIR_DEFAULT / subvideo_id
            frame_files = extract_sampled_frames(source_path, frame_dir, len(sampled), end_time)
            actual_n = len(frame_files)
            if actual_n != len(sampled):
                sampled = compute_sampled_frames_with_n(
                    start_time, end_time, fps, total_frames, actual_n
                )
            frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

    event_frame = rec["event_frame_original"]
    fracture_between = compute_fracture_between(sampled, event_frame) if has_fracture else None

    # 全时长正样本同样必须满足严格相邻；若无法满足则记录并排除
    if has_fracture and fracture_between is None:
        EXCLUSIONS.append(
            {
                "subvideo_id": subvideo_id,
                "source_video": video_id,
                "reason": "全时长正样本无法生成严格相邻的 fracture_between",
                "event_frame": event_frame,
            }
        )
        return None

    return {
        "subvideo_id": subvideo_id,
        "source_video": video_id,
        "video_path": str(original_video_path),
        "frame_paths": frame_paths,
        "sampled_frames": sampled,
        "start_time": 0.0,
        "end_time": round(end_time, 4) if end_time else None,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration": round(end_time, 4) if end_time else None,
        "crop_type": crop_type,
        "event_position_ratio": None,
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "is_abnormal": rec.get("is_abnormal", False),
        "fracture_between": fracture_between,
        "type": rec_type,
        "location": rec_location,
        "location_canonical": rec_location,
        "source_type": rec["type"],
        "source_location": rec["location"],
        "fold": split_info.get("fold"),
        "split": split_info.get("split"),
        "fold_assignments": split_info.get("fold_assignments", []),
    }


def update_subvideo_metadata(sub: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    """基于现有 mp4/frame 文件重新计算派生元数据（快速模式，不重编码）。"""
    sub = dict(sub)
    fps = rec.get("fps")
    total_frames = rec.get("total_frames")
    event_frame = rec.get("event_frame_original")

    # 修正 full 视频 end_time/end_frame/duration 的一致性
    if sub.get("crop_type") in ("full_pos", "full_neg") and total_frames and fps:
        sub["end_frame"] = int(total_frames - 1)
        sub["end_time"] = round(sub["end_frame"] / fps, 4)
        sub["duration"] = sub["end_time"]

    frame_paths = sub.get("frame_paths") or []
    n = len(frame_paths)
    has_fracture = sub.get("has_fracture_canonical", sub.get("has_fracture", False))

    if n > 0 and fps and total_frames:
        sampled = compute_sampled_frames_with_n(
            sub.get("start_time", 0.0),
            sub.get("end_time", 0.0),
            fps,
            total_frames,
            n,
        )
        if has_fracture and event_frame is not None:
            sub["fracture_between"] = compute_fracture_between(sampled, event_frame)
        else:
            sub["fracture_between"] = None
    elif fps and total_frames:
        # 无审计帧时，用 start_frame/end_frame 反推精确时间再计算理论采样帧，
        # 避免复用已四舍五入的 start_time/end_time 导致 fracture_between 漂移。
        exact_start = sub.get("start_frame", 0) / fps
        exact_end = sub.get("end_frame", 0) / fps
        sampled = compute_sampled_frames(
            exact_start,
            exact_end,
            fps,
            total_frames,
            VIDEO_FPS,
            VIDEO_MAXLEN,
        )
        if has_fracture and event_frame is not None:
            sub["fracture_between"] = compute_fracture_between(sampled, event_frame)
        else:
            sub["fracture_between"] = None
    elif not has_fracture:
        sub["fracture_between"] = None
        sampled = []
    else:
        sampled = []

    sub["sampled_frames"] = sampled
    return sub


def build_subvideos_for_record(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    generate_media: bool = True,
    extract_frames: bool = False,
    selected_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """为单个视频生成候选子视频列表。若提供 selected_ids，则只为选中 ID 生成媒体文件。"""
    results: list[dict[str, Any]] = []
    video_id = rec["video_id"]
    full_id = f"{video_id}_full"
    gen_full = generate_media and (selected_ids is None or full_id in selected_ids)

    full = build_full_subvideo(rec, split_info, gen_full, extract_frames)
    if full is not None:
        if selected_ids is None or full_id in selected_ids:
            results.append(full)

    has_fracture_canonical = rec.get(
        "has_fracture_canonical", rec.get("has_fracture", False)
    )
    rec_type = rec["type"]

    # 视频异常只保留全时长样本
    if rec.get("is_abnormal"):
        return results

    # 非断裂视频生成对应负片段
    if not has_fracture_canonical or rec_type not in FRACTURE_TYPES:
        if rec_type == "未断裂":
            results.extend(build_non_fracture_clips(rec, split_info, generate_media, extract_frames, selected_ids))
        elif rec_type == "未夹紧":
            results.extend(build_not_clamped_clips(rec, split_info, generate_media, extract_frames, selected_ids))
        return results

    # 确认断裂视频：全时长 + 聚焦 + 干净负片段
    results.extend(build_focus_subvideos(rec, split_info, generate_media, extract_frames, selected_ids))
    results.extend(build_neg_before_after(rec, split_info, generate_media, extract_frames, selected_ids))
    return results


def load_split_definitions(splits_dir: Path) -> dict[str, set[str]]:
    """读取划分文件，返回 split_name -> video_id 集合。"""
    import re

    split_defs: dict[str, set[str]] = {}
    pattern = re.compile(r"^(fold_\d+_(?:train|val)|test)$")
    for path in sorted(splits_dir.glob("*.json")):
        if not pattern.match(path.stem):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        split_defs[path.stem] = set(data.get("video_ids", []))
    return split_defs


def _select_train_candidates(
    all_candidates: list[dict[str, Any]],
    split_defs: dict[str, set[str]],
    n_folds: int = 3,
    seed: int = 42,
) -> None:
    """按正:负 1:1~2:1 为每个 fold 训练集选择样本，并在候选元数据上标记 selected_splits。"""
    import random

    random.seed(seed)

    # 初始化 selected_splits：非 test 的所属 split 默认全选
    for cand in all_candidates:
        assignments = set(cand.get("fold_assignments", []))
        cand["selected_splits"] = sorted(assignments - {"test"})

    def _sample_with_priority(
        cands: list[dict[str, Any]], target: int
    ) -> set[str]:
        """优先保留全时长样本，再从片段中随机采样至目标数量。"""
        if target >= len(cands):
            return {c["subvideo_id"] for c in cands}
        full_ids = {c["subvideo_id"] for c in cands if c.get("crop_type", "").startswith("full")}
        other = [c for c in cands if c["subvideo_id"] not in full_ids]
        need = max(0, target - len(full_ids))
        selected_other = set()
        if need > 0 and other:
            selected_other = {c["subvideo_id"] for c in random.sample(other, min(need, len(other)))}
        # 如果全时长数量已超过目标，则只能随机采样全时长
        if len(full_ids) > target:
            return set(random.sample(sorted(full_ids), target))
        return full_ids | selected_other

    for i in range(n_folds):
        train_name = f"fold_{i}_train"
        train_ids = split_defs.get(train_name, set())
        train_cands = [c for c in all_candidates if c.get("source_video") in train_ids]
        pos = [c for c in train_cands if c.get("has_fracture_canonical", c.get("has_fracture", False))]
        neg = [c for c in train_cands if not c.get("has_fracture_canonical", c.get("has_fracture", False))]

        pos_n = len(pos)
        neg_n = len(neg)

        # 目标：保持正:负在 1:1 ~ 2:1
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


def main():
    global FOCUS_WINDOWS, FOCUS_POSITIONS, VIDEO_FPS, VIDEO_MAXLEN
    parser = argparse.ArgumentParser(description="子视频生成器（先选后生成）")
    parser.add_argument("--video-meta", type=Path, default=VIDEO_META_DEFAULT)
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR_DEFAULT)
    parser.add_argument("--subvideo-dir", type=Path, default=SUBVIDEO_DIR_DEFAULT)
    parser.add_argument("--frame-dir", type=Path, default=FRAME_DIR_DEFAULT)
    parser.add_argument("--output-meta", type=Path, default=SUBVIDEOS_META_DEFAULT)
    parser.add_argument("--focus-windows", type=float, nargs="+", default=FOCUS_WINDOWS)
    parser.add_argument("--focus-positions", type=float, nargs="+", default=FOCUS_POSITIONS)
    parser.add_argument("--video-fps", type=float, default=VIDEO_FPS)
    parser.add_argument("--video-maxlen", type=int, default=VIDEO_MAXLEN)
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
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    records = json.loads(args.video_meta.read_text(encoding="utf-8"))
    video_meta_dict = {r["video_id"]: r for r in records}
    split_mapping = load_splits(args.splits_dir)
    split_defs = load_split_definitions(args.splits_dir)

    # 模块级常量运行时覆盖；后续函数调用读取新值
    FOCUS_WINDOWS = [int(w) if w == int(w) else w for w in args.focus_windows]
    FOCUS_POSITIONS = args.focus_positions
    VIDEO_FPS = args.video_fps
    VIDEO_MAXLEN = args.video_maxlen

    if args.fast and args.output_meta.exists():
        print(f"快速模式：读取已有元数据 {args.output_meta}")
        existing = json.loads(args.output_meta.read_text(encoding="utf-8"))
        # 兼容旧版列表格式与新版对象格式
        if isinstance(existing, dict):
            existing_subs = existing.get("subvideos", [])
            existing_exclusions = existing.get("exclusions", [])
        else:
            existing_subs = existing
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
        print(f"快速模式：共更新 {len(all_subvideos)} 条子视频元数据")
    else:
        if args.fast:
            print("快速模式：未发现已有元数据，退回到完整生成")

        EXCLUSIONS.clear()

        # 阶段 1：先生成候选清单（不生成媒体）
        print("阶段 1：生成候选子视频清单...")
        all_candidates: list[dict[str, Any]] = []
        for rec in records:
            video_id = rec["video_id"]
            split_info = split_mapping.get(video_id, {"split": "unknown", "fold": "unknown"})
            # 测试集视频不生成子视频
            if split_info.get("split") == "test":
                continue
            subs = build_subvideos_for_record(rec, split_info, generate_media=False, extract_frames=False)
            all_candidates.extend(subs)
        print(f"候选子视频：{len(all_candidates)} 条")

        # 阶段 2：训练集正负样本选择
        print("阶段 2：训练集候选选择...")
        _select_train_candidates(all_candidates, split_defs, n_folds=3, seed=args.seed)
        selected_count = sum(1 for c in all_candidates if c.get("selected_splits"))
        print(f"选中子视频：{selected_count} 条")

        # 阶段 3：只为选中的候选生成媒体文件
        print("阶段 3：生成选中子视频媒体...")
        selected_ids = {c["subvideo_id"] for c in all_candidates if c.get("selected_splits")}
        generated_by_id: dict[str, dict[str, Any]] = {}
        for rec in records:
            video_id = rec["video_id"]
            if not any(c["source_video"] == video_id for c in all_candidates):
                continue
            split_info = split_mapping.get(video_id, {"split": "unknown", "fold": "unknown"})
            subs = build_subvideos_for_record(
                rec, split_info, generate_media=True, extract_frames=args.extract_frames,
                selected_ids=selected_ids,
            )
            for sub in subs:
                generated_by_id[sub["subvideo_id"]] = sub

        all_subvideos = [generated_by_id[c["subvideo_id"]] for c in all_candidates if c["subvideo_id"] in generated_by_id]
        # 保留 selected_splits 标记
        for sub in all_subvideos:
            cand = next(c for c in all_candidates if c["subvideo_id"] == sub["subvideo_id"])
            sub["selected_splits"] = cand.get("selected_splits", [])
        print(f"实际生成媒体：{len(all_subvideos)} 条")

        if EXCLUSIONS:
            exclusions_path = args.output_meta.parent / "subvideo_exclusions.json"
            with open(exclusions_path, "w", encoding="utf-8") as f:
                json.dump(EXCLUSIONS, f, ensure_ascii=False, indent=2, allow_nan=False)
            print(f"记录排除片段：{exclusions_path} ({len(EXCLUSIONS)} 条)")

    args.subvideo_dir.mkdir(parents=True, exist_ok=True)
    args.frame_dir.mkdir(parents=True, exist_ok=True)
    args.output_meta.parent.mkdir(parents=True, exist_ok=True)

    # 汇总排除原因统计
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
        "exclusions": EXCLUSIONS,
        "exclusion_stats": exclusion_stats,
    }
    with open(args.output_meta, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"完成：共 {len(all_subvideos)} 个子视频，元数据写入 {args.output_meta}")


if __name__ == "__main__":
    main()
