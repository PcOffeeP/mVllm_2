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
    """根据采样帧与真实断裂帧计算 ``fracture_between``。

    规则优先级：
    1. 越界前段：``event_frame < originals[0]`` -> ``[0, 0]``。
    2. 越界末段：``event_frame >= originals[-1]`` -> ``[N-1, N-1]``。
    3. 恰好命中：``event_frame == originals[i]`` -> ``[i-1, i]``（``i > 0``），
       ``i == 0`` 时退化为 ``[0, 0]``。
    4. 正常区间：``originals[i] < event_frame < originals[i+1]`` -> ``[i, i+1]``。
    """
    if event_frame is None or not sampled_frames:
        return None
    originals = [f["original_frame"] for f in sampled_frames]
    n = len(originals)
    if event_frame < originals[0]:
        return [0, 0]
    if event_frame >= originals[-1]:
        return [n - 1, n - 1]
    # 先检查 exact-hit，再检查区间
    for i in range(n):
        if originals[i] == event_frame:
            if i == 0:
                return [0, 0]
            return [i - 1, i]
    for i in range(n - 1):
        if originals[i] < event_frame < originals[i + 1]:
            return [i, i + 1]
    return [n - 1, n - 1]


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


def build_focus_subvideos(rec: dict[str, Any], split_info: dict[str, Any]) -> list[dict[str, Any]]:
    """生成局部聚焦子视频。"""
    subvideos = []
    video_id = rec["video_id"]
    fps = rec["fps"]
    total_frames = rec["total_frames"]
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
            duration = end_time - start_time

            subvideo_id = f"{video_id}_focus_{window}s_{int(ratio * 100):02d}pct"
            subvideo_path = SUBVIDEO_DIR_DEFAULT / f"{subvideo_id}.mp4"
            crop_video(source_path, subvideo_path, start_time, end_time)

            sampled = compute_sampled_frames(
                start_time, end_time, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN
            )
            frame_dir = FRAME_DIR_DEFAULT / subvideo_id
            frame_files = extract_sampled_frames(subvideo_path, frame_dir, len(sampled), duration)
            actual_n = len(frame_files)
            if actual_n != len(sampled):
                sampled = compute_sampled_frames_with_n(
                    start_time, end_time, fps, total_frames, actual_n
                )
            frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

            subvideos.append(
                {
                    "subvideo_id": subvideo_id,
                    "source_video": video_id,
                    "video_path": str(Path(subvideo_path).relative_to(PROJECT_ROOT / "data")),
                    "frame_paths": frame_paths,
                    "start_time": round(start_time, 4),
                    "end_time": round(end_time, 4),
                    "start_frame": int(start_frame),
                    "end_frame": int(end_frame),
                    "duration": round(duration, 4),
                    "crop_type": f"focus_{window}s",
                    "event_position_ratio": ratio,
                    "has_fracture": True,
                    "has_fracture_canonical": True,
                    "fracture_between": compute_fracture_between(sampled, event_frame),
                    "type": rec["type"],
                    "location": rec.get("location_canonical", rec["location"]),
                    "location_canonical": rec.get("location_canonical", rec["location"]),
                    "source_type": rec["type"],
                    "source_location": rec["location"],
                    "fold": split_info.get("fold"),
                    "split": split_info.get("split"),
                    "fold_assignments": split_info.get("fold_assignments", []),
                }
            )
    return subvideos


def build_neg_before_after(rec: dict[str, Any], split_info: dict[str, Any]) -> list[dict[str, Any]]:
    subvideos = []
    video_id = rec["video_id"]
    fps = rec["fps"]
    total_frames = rec["total_frames"]
    duration = rec["duration"]
    event_frame = rec["event_frame_original"]
    event_time = rec["event_time"]
    if event_frame is None or event_time is None or fps is None or total_frames is None or duration is None:
        return subvideos

    source_path = Path(rec["video_path"])
    if not source_path.is_absolute():
        source_path = PROJECT_ROOT / source_path

    windows = [
        ("neg_before", event_time - NEG_BEFORE_DURATION, event_time - 1.0),
        ("neg_after", event_time + 1.0, event_time + NEG_AFTER_DURATION),
    ]
    for crop_type, start, end in windows:
        start = max(0.0, start)
        end = min(duration, end)
        if end - start < 0.5:
            continue
        start_frame = clamp(round(start * fps), 0, total_frames - 1)
        end_frame = clamp(round(end * fps), 0, total_frames - 1)
        if start_frame >= end_frame:
            continue
        start_time = start_frame / fps
        end_time = end_frame / fps
        clip_duration = end_time - start_time

        subvideo_id = f"{video_id}_{crop_type}"
        subvideo_path = SUBVIDEO_DIR_DEFAULT / f"{subvideo_id}.mp4"
        crop_video(source_path, subvideo_path, start_time, end_time)

        sampled = compute_sampled_frames(
            start_time, end_time, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN
        )
        frame_dir = FRAME_DIR_DEFAULT / subvideo_id
        frame_files = extract_sampled_frames(subvideo_path, frame_dir, len(sampled), clip_duration)
        actual_n = len(frame_files)
        if actual_n != len(sampled):
            sampled = compute_sampled_frames_with_n(
                start_time, end_time, fps, total_frames, actual_n
            )
        frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

        subvideos.append(
            {
                "subvideo_id": subvideo_id,
                "source_video": video_id,
                "video_path": str(Path(subvideo_path).relative_to(PROJECT_ROOT / "data")),
                "frame_paths": frame_paths,
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
                "location": "N/A",
                "location_canonical": "N/A",
                "source_type": rec["type"],
                "source_location": rec["location"],
                "fold": split_info.get("fold"),
                "split": split_info.get("split"),
                "fold_assignments": split_info.get("fold_assignments", []),
            }
        )
    return subvideos


def build_full_subvideo(rec: dict[str, Any], split_info: dict[str, Any]) -> dict[str, Any] | None:
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
    if "location_canonical" in rec:
        rec_location = rec["location_canonical"]
    else:
        rec_location = rec["location"]
        if rec.get("is_abnormal") and rec_location != "N/A":
            rec_location = "N/A"

    crop_type = "full_pos" if has_fracture else "full_neg"
    subvideo_id = f"{video_id}_full"
    subvideo_path = SUBVIDEO_DIR_DEFAULT / f"{subvideo_id}.mp4"
    copy_as_subvideo(source_path, subvideo_path)

    fps = rec.get("fps")
    total_frames = rec.get("total_frames")
    duration = rec.get("duration")
    start_time = 0.0
    start_frame = 0
    end_frame = (total_frames - 1) if total_frames else None
    # 使 end_time 与 end_frame 对齐，避免 duration 含末尾空帧间隔导致测试断言偏差
    end_time = (end_frame / fps) if total_frames and fps else duration
    if fps is None or total_frames is None or end_time is None:
        sampled: list[dict[str, Any]] = []
        frame_files: list[Path] = []
    else:
        sampled = compute_sampled_frames(
            start_time, end_time, fps, total_frames, VIDEO_FPS, VIDEO_MAXLEN
        )
        frame_dir = FRAME_DIR_DEFAULT / subvideo_id
        frame_files = extract_sampled_frames(subvideo_path, frame_dir, len(sampled), end_time)
        actual_n = len(frame_files)
        if actual_n != len(sampled):
            sampled = compute_sampled_frames_with_n(
                start_time, end_time, fps, total_frames, actual_n
            )
    frame_paths = [str(Path(f).relative_to(PROJECT_ROOT / "data")) for f in frame_files]

    event_frame = rec["event_frame_original"]
    fracture_between = compute_fracture_between(sampled, event_frame) if has_fracture else None

    return {
        "subvideo_id": subvideo_id,
        "source_video": video_id,
        "video_path": str(Path(subvideo_path).relative_to(PROJECT_ROOT / "data")),
        "frame_paths": frame_paths,
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
    elif not has_fracture:
        sub["fracture_between"] = None

    return sub


def build_subvideos_for_record(
    rec: dict[str, Any],
    split_info: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    full = build_full_subvideo(rec, split_info)
    if full is not None:
        results.append(full)

    # 异常样本/无断裂视频不生成局部聚焦和断裂前后负样本
    has_fracture_canonical = rec.get("has_fracture_canonical", rec.get("has_fracture", False))
    if rec.get("is_abnormal") or not has_fracture_canonical:
        return results

    # 数据一致性保护：has_fracture_canonical=True 但 type 不在 7 个断裂类中，仅保留全时长样本
    if rec["type"] not in FRACTURE_TYPES:
        return results

    results.extend(build_focus_subvideos(rec, split_info))
    results.extend(build_neg_before_after(rec, split_info))
    return results


def main():
    global FOCUS_WINDOWS, FOCUS_POSITIONS, VIDEO_FPS, VIDEO_MAXLEN
    parser = argparse.ArgumentParser(description="子视频生成器")
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
        "--fast",
        action="store_true",
        help="仅更新已有子视频元数据，避免重新编码/抽帧 mp4",
    )
    args = parser.parse_args()

    records = json.loads(args.video_meta.read_text(encoding="utf-8"))
    video_meta_dict = {r["video_id"]: r for r in records}
    split_mapping = load_splits(args.splits_dir)

    # 模块级常量运行时覆盖；后续函数调用读取新值
    FOCUS_WINDOWS = [int(w) if w == int(w) else w for w in args.focus_windows]
    FOCUS_POSITIONS = args.focus_positions
    VIDEO_FPS = args.video_fps
    VIDEO_MAXLEN = args.video_maxlen

    if args.fast and args.output_meta.exists():
        print(f"快速模式：读取已有元数据 {args.output_meta}")
        existing = json.loads(args.output_meta.read_text(encoding="utf-8"))
        all_subvideos: list[dict[str, Any]] = []
        for sub in existing:
            rec = video_meta_dict.get(sub.get("source_video"))
            if rec is None:
                all_subvideos.append(sub)
                continue
            updated = update_subvideo_metadata(sub, rec)
            all_subvideos.append(updated)
        print(f"快速模式：共更新 {len(all_subvideos)} 条子视频元数据")
    else:
        if args.fast:
            print("快速模式：未发现已有元数据，退回到完整生成")
        all_subvideos = []
        for rec in records:
            video_id = rec["video_id"]
            split_info = split_mapping.get(video_id, {"split": "unknown", "fold": "unknown"})
            subs = build_subvideos_for_record(rec, split_info)
            all_subvideos.extend(subs)
            print(f"{video_id}: 生成 {len(subs)} 个子视频")

    args.subvideo_dir.mkdir(parents=True, exist_ok=True)
    args.frame_dir.mkdir(parents=True, exist_ok=True)
    args.output_meta.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_meta, "w", encoding="utf-8") as f:
        json.dump(all_subvideos, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"完成：共 {len(all_subvideos)} 个子视频，元数据写入 {args.output_meta}")


if __name__ == "__main__":
    main()
