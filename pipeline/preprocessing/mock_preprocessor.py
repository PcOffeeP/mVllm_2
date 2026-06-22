from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline.preprocessing.adapter import FrameMapping, ProcessorInfo, VideoPreprocessor


class MockVideoPreprocessor(VideoPreprocessor):
    """基于 ffmpeg 的 mock 预处理器，输出格式与真实接口一致。

    该实现仅用于本地结构验证，明确标注为 fallback，不应替代真实
    MiniCPM-V 4.6 视频处理器。
    """

    NAME = "mock-ffmpeg-uniform"
    VERSION = "0.1.0"
    BACKEND = "ffmpeg"

    def __init__(self, max_frames: int = 8) -> None:
        if max_frames <= 0:
            raise ValueError("max_frames 必须为正整数")
        self._max_frames = max_frames

    # ------------------------------------------------------------------
    # VideoPreprocessor 接口
    # ------------------------------------------------------------------

    def get_info(self) -> ProcessorInfo:
        return ProcessorInfo(
            name=self.NAME,
            version=self.VERSION,
            max_frames=self._max_frames,
            backend=self.BACKEND,
        )

    def healthcheck(self) -> bool:
        return _ffmpeg_available() and _ffprobe_available()

    def sample(
        self, video_path: str, start_time: float, end_time: float
    ) -> list[FrameMapping]:
        if start_time < 0:
            raise ValueError("start_time 必须 >= 0")
        if end_time <= start_time:
            raise ValueError("end_time 必须 > start_time")

        video_path = Path(video_path)
        if not video_path.is_file():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        fps, total_frames, duration = _probe_video(str(video_path))
        end_time = min(end_time, duration)
        if end_time <= start_time:
            raise ValueError(f"采样区间无效: [{start_time}, {end_time}]")

        indices = _uniform_indices(
            start_time, end_time, fps, total_frames, self._max_frames
        )

        # 使用 ffmpeg 实际抽取这些帧，以验证帧号可用；输出写入临时目录。
        with tempfile.TemporaryDirectory(prefix="mock_preprocessor_") as tmpdir:
            _extract_frames(str(video_path), indices, tmpdir)

        return [
            FrameMapping(
                input_index=i,
                original_frame=frame_idx,
                timestamp=frame_idx / fps,
            )
            for i, frame_idx in enumerate(indices)
        ]

    def fingerprint(self) -> str:
        ffmpeg_version = _run_command(["ffmpeg", "-version"], check=False)
        first_line = ffmpeg_version.splitlines()[0] if ffmpeg_version else "unknown"
        return (
            f"{self.NAME}:{self.VERSION}:max_frames={self._max_frames}:"
            f"ffmpeg={first_line.strip().replace(' ', '_')}"
        )


# ---------------------------------------------------------------------------
# ffmpeg 辅助函数
# ---------------------------------------------------------------------------


def _run_command(cmd: list[str], check: bool = True) -> str:
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=check,
            timeout=60,
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"命令失败: {' '.join(cmd)}\n{exc.stderr}"
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到可执行文件: {cmd[0]}") from exc


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _probe_video(video_path: str) -> tuple[float, int, float]:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,nb_frames,duration",
        "-of", "json",
        video_path,
    ]
    stdout = _run_command(cmd)
    data = json.loads(stdout)
    stream = data.get("streams", [{}])[0]

    fps = _parse_fps(stream.get("r_frame_rate", ""))
    if fps is None or fps <= 0:
        raise RuntimeError(f"无法解析视频 FPS: {video_path}")

    duration = stream.get("duration")
    if duration is None:
        duration = _probe_duration(video_path)
    duration = float(duration)

    nb_frames = stream.get("nb_frames")
    if nb_frames is None or nb_frames == "N/A":
        total_frames = int(round(duration * fps))
    else:
        total_frames = int(nb_frames)

    return fps, total_frames, duration


def _probe_duration(video_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    stdout = _run_command(cmd).strip()
    try:
        return float(stdout)
    except ValueError as exc:
        raise RuntimeError(f"无法解析视频时长: {stdout}") from exc


def _parse_fps(rate: str) -> float | None:
    if not rate:
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            return float(num) / float(den)
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return None


def _uniform_indices(
    start_time: float,
    end_time: float,
    fps: float,
    total_frames: int,
    max_frames: int,
) -> list[int]:
    """在 [start_time, end_time] 区间内均匀选择最多 max_frames 个原始帧号。"""
    start_frame = max(0, int(round(start_time * fps)))
    end_frame = min(total_frames, int(round(end_time * fps)))
    if end_frame <= start_frame:
        # 区间极短，至少包含起始帧
        end_frame = min(total_frames, start_frame + 1)

    frame_count = end_frame - start_frame
    n = min(max_frames, max(1, frame_count))

    if n == 1:
        return [start_frame]

    step = (frame_count - 1) / (n - 1)
    indices = [start_frame + int(round(i * step)) for i in range(n)]
    # 去重并保持单调
    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen and idx < total_frames:
            seen.add(idx)
            unique.append(idx)
    # 若去重后数量不足，则重新用整数步长填充
    while len(unique) < n and unique[-1] + 1 < total_frames:
        unique.append(unique[-1] + 1)
    return unique[:max_frames]


def _extract_frames(video_path: str, indices: list[int], output_dir: str) -> None:
    if not indices:
        return
    select_expr = "+".join(f"eq(n\\,{idx})" for idx in indices)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", f"select={select_expr}",
        "-vsync", "vfr",
        "-q:v", "2",
        os.path.join(output_dir, "frame_%04d.jpg"),
    ]
    _run_command(cmd)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.preprocessing.mock_preprocessor",
        description="Mock ffmpeg 视频预处理器 CLI",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="检查 ffmpeg/ffprobe 是否可用",
    )
    parser.add_argument(
        "--sample",
        nargs=3,
        metavar=("VIDEO", "START", "END"),
        help="对视频区间采样，输出 JSON 帧映射",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    preprocessor = MockVideoPreprocessor()

    if args.healthcheck:
        ok = preprocessor.healthcheck()
        info = preprocessor.get_info()
        print(json.dumps({
            "ok": ok,
            "info": {
                "name": info.name,
                "version": info.version,
                "max_frames": info.max_frames,
                "backend": info.backend,
            },
            "fingerprint": preprocessor.fingerprint(),
        }, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    if args.sample:
        video_path, start, end = args.sample
        frames = preprocessor.sample(video_path, float(start), float(end))
        print(json.dumps(
            [{
                "input_index": f.input_index,
                "original_frame": f.original_frame,
                "timestamp": f.timestamp,
            } for f in frames],
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    _build_argparser().print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
