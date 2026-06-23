"""Video sampling abstractions and index/time conversion utilities.

Concrete implementations use ``ffmpeg``/``ffprobe`` via subprocess so that the
tool execution layer does not require ``cv2``.  For tests without a real video
file, callers can subclass ``VideoSampler`` / ``VideoClipBuilder`` or monkeypatch
``_probe_video`` / ``_run_ffmpeg``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Index / time conversion utilities
# ---------------------------------------------------------------------------
def frame_to_time(frame: int, fps: float) -> float:
    """Convert a 0-based frame index to seconds."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    return frame / fps


def time_to_frame(time_seconds: float, fps: float) -> int:
    """Convert seconds to a 0-based frame index using ``round``."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    return round(time_seconds * fps)


def _resolve_between_indices(fracture_between: list[int], num_frames: int) -> tuple[int, int]:
    """Validate and return ``(i, j)`` indices for ``fracture_between``."""
    if fracture_between is None or len(fracture_between) != 2:
        raise ValueError("fracture_between must be a two-element list")
    i, j = fracture_between
    if not (0 <= i < num_frames and 0 <= j < num_frames):
        raise ValueError("fracture_between indices are out of range")
    return i, j


def fracture_between_to_time_range(
    fracture_between: list[int],
    frames: list[dict[str, Any]],
) -> list[float]:
    """Map ``fracture_between = [i, j]`` to ``[frames[i].timestamp, frames[j].timestamp]``."""
    i, j = _resolve_between_indices(fracture_between, len(frames))
    return [frames[i]["timestamp"], frames[j]["timestamp"]]


def fracture_between_to_frame_range(
    fracture_between: list[int],
    frames: list[dict[str, Any]],
) -> list[int]:
    """Map ``fracture_between = [i, j]`` to ``[frames[i].original_frame, frames[j].original_frame]``."""
    i, j = _resolve_between_indices(fracture_between, len(frames))
    return [frames[i]["original_frame"], frames[j]["original_frame"]]


def is_boundary_sentinel(fracture_between: list[int] | None, num_frames: int) -> bool:
    """Return whether ``fracture_between`` is the left or right boundary sentinel.

    Left sentinel is ``[0, 0]``; right sentinel is ``[N - 1, N - 1]``.
    """
    if fracture_between is None or len(fracture_between) != 2 or num_frames < 1:
        return False
    i, j = fracture_between
    return (i == 0 and j == 0) or (i == num_frames - 1 and j == num_frames - 1)


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------
def _which_ffmpeg() -> str:
    """Return the ffmpeg executable path or raise if unavailable."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg executable not found. Install ffmpeg to use the concrete "
            "VideoSampler/VideoClipBuilder implementations."
        )
    return ffmpeg


def _which_ffprobe() -> str:
    """Return the ffprobe executable path or raise if unavailable."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError(
            "ffprobe executable not found. Install ffmpeg to use the concrete "
            "VideoSampler/VideoClipBuilder implementations."
        )
    return ffprobe


def _probe_video(video_path: str) -> dict[str, Any]:
    """Probe a video file and return fps, total_frames, duration and width/height."""
    ffprobe = _which_ffprobe()
    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,avg_frame_rate,nb_frames,duration,width,height",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout)

    streams = data.get("streams", [])
    fmt = data.get("format", {})
    if not streams:
        raise ValueError(f"No video stream found in {video_path}")
    stream = streams[0]

    fps = _parse_fps(stream.get("r_frame_rate") or stream.get("avg_frame_rate", "0/1"))
    duration = _parse_float(stream.get("duration") or fmt.get("duration"))
    total_frames = _parse_int(stream.get("nb_frames"))
    if total_frames is None and duration and fps:
        total_frames = round(duration * fps)

    return {
        "fps": fps,
        "total_frames": total_frames or 0,
        "duration": duration or 0.0,
        "width": _parse_int(stream.get("width")) or 0,
        "height": _parse_int(stream.get("height")) or 0,
    }


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_fps(fps_str: str) -> float:
    """Parse ffmpeg fps expressions like ``30000/1001``."""
    if not fps_str:
        return 0.0
    parts = fps_str.split("/")
    if len(parts) == 2:
        try:
            num, den = float(parts[0]), float(parts[1])
            return num / den if den else 0.0
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(fps_str)
    except (TypeError, ValueError):
        return 0.0


def _effective_num_frames(
    sample_range: list[float],
    video_fps: float,
    video_maxlen: int,
    total_frames_in_clip: int | None = None,
) -> int:
    """Compute the number of frames actually sampled in a clip.

    N = min(total_frames_in_clip, video_maxlen, max(1, floor(duration * video_fps)))
    """
    duration = sample_range[1] - sample_range[0]
    if duration <= 0:
        return 1
    by_fps = max(1, int(duration * video_fps))
    upper = min(by_fps, video_maxlen)
    if total_frames_in_clip is not None:
        upper = min(upper, total_frames_in_clip)
    return max(1, upper)


def _uniform_timestamps(start: float, end: float, n: int) -> list[float]:
    """Return ``n`` uniform timestamps in ``[start, end]`` (inclusive of both ends)."""
    if n <= 1:
        return [start]
    step = (end - start) / (n - 1)
    return [start + k * step for k in range(n)]


def _run_ffmpeg(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run ffmpeg with the given arguments."""
    ffmpeg = _which_ffmpeg()
    return subprocess.run([ffmpeg, *args], capture_output=True, text=True, check=check)


# ---------------------------------------------------------------------------
# Temporary clip result
# ---------------------------------------------------------------------------
@dataclass
class ClipBuildResult:
    """Path to a continuous temporary MP4 clip plus its frame manifest.

    The ``manifest`` maps each frame index inside the temporary clip back to
    the corresponding original video frame number and timestamp.  It is the
    authoritative source for translating model-output ``fracture_between``
    indices into original-video time ranges.
    """

    path: str
    manifest: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# VideoSampler
# ---------------------------------------------------------------------------
class VideoSampler(ABC):
    """Abstract video frame sampler used by the tool execution layer."""

    @abstractmethod
    def sample(
        self,
        video_path: str,
        sample_range: list[float],
        num_frames: int,
        video_fps: float = 8.0,
        strategy: str = "uniform",
    ) -> list[dict[str, Any]]:
        """Return a list of sampled frame descriptors.

        Each descriptor must contain ``input_index``, ``original_frame``,
        ``timestamp`` and ``frame_path`` keys.
        """
        ...


class UniformVideoSampler(VideoSampler):
    """Uniform frame sampler backed by ffmpeg.

    Saves extracted frames to ``cache_dir`` for debugging/audit.  If
    ``cache_dir`` is ``None``, frames are written to a temporary directory.

    .. note::
        This sampler is retained for backward compatibility.  The contract
        requires the inference clip to be a continuous crop of the source
        video; use ``FfmpegVideoClipBuilder.build_with_manifest`` for new
        code.
    """

    def __init__(self, cache_dir: str | None = None) -> None:
        self.cache_dir = cache_dir

    def sample(
        self,
        video_path: str,
        sample_range: list[float],
        num_frames: int,
        video_fps: float = 8.0,
        strategy: str = "uniform",
    ) -> list[dict[str, Any]]:
        if strategy == "adaptive":
            logger.warning(
                "adaptive sampling is not fully supported yet; falling back to uniform."
            )
            strategy = "uniform"
        if strategy != "uniform":
            raise ValueError(f"Unsupported sampling strategy: {strategy}")

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        probe = _probe_video(video_path)
        original_fps = probe["fps"] or video_fps
        duration = probe["duration"]

        start, end = sample_range
        start = max(0.0, start)
        end = min(end, duration) if duration else end
        if end < start:
            end = start

        # Number of frames in the source clip if we sampled at the original fps.
        clip_duration = end - start
        total_frames_in_clip = max(1, int(round(clip_duration * original_fps)))

        n = _effective_num_frames([start, end], video_fps, num_frames, total_frames_in_clip)
        timestamps = _uniform_timestamps(start, end, n)

        cache = Path(self.cache_dir) if self.cache_dir else Path("data/08_runtime/agent_frames")
        video_stem = Path(video_path).stem
        frame_dir = cache / f"{video_stem}_{start:.2f}_{end:.2f}"
        frame_dir.mkdir(parents=True, exist_ok=True)

        frames: list[dict[str, Any]] = []
        for idx, ts in enumerate(timestamps):
            original_frame = min(max(0, round(ts * original_fps)), probe["total_frames"] - 1)
            frame_path = frame_dir / f"frame_{idx:04d}_{original_frame:08d}.jpg"
            self._extract_frame(video_path, ts, str(frame_path))
            frames.append(
                {
                    "input_index": idx,
                    "original_frame": original_frame,
                    "timestamp": round(ts, 6),
                    "frame_path": str(frame_path),
                }
            )
        return frames

    def _extract_frame(self, video_path: str, timestamp: float, output_path: str) -> None:
        """Extract a single frame at ``timestamp`` using ffmpeg."""
        _run_ffmpeg(
            [
                "-y",
                "-ss", str(timestamp),
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "2",
                output_path,
            ]
        )


# Provide a default concrete sampler under the base name for convenience.
VideoSampler.register(UniformVideoSampler)


# ---------------------------------------------------------------------------
# VideoClipBuilder
# ---------------------------------------------------------------------------
class VideoClipBuilder(ABC):
    """Abstract builder for temporary inference ``.mp4`` clips."""

    @abstractmethod
    def build(
        self,
        source_video: str,
        sample_range: list[float],
        frames: list[dict[str, Any]],
        video_fps: float = 8.0,
        video_maxlen: int = 36,
        sampling_strategy: str = "uniform",
    ) -> str:
        """Return the path of the temporary clip sent to ``InferenceClient``."""
        ...


class FfmpegVideoClipBuilder(VideoClipBuilder):
    """Build continuous temporary inference clips by cropping the source video.

    The builder no longer pre-extracts frames or concatenates them at an
    artificial FPS.  Instead it directly crops the original video between
    ``sample_range[0]`` and ``sample_range[1]`` and preserves the original
    time axis.  A manifest is produced that maps every frame in the temporary
    clip back to the original video frame index and timestamp.

    For ``adaptive`` strategy the builder falls back to ``uniform`` because
    the contract only supports continuous cropping for this version.

    The ``frames`` argument of ``build`` is kept for backward compatibility
    but is intentionally ignored; the clip is derived solely from
    ``sample_range``.
    """

    def __init__(self, output_dir: str | None = None) -> None:
        self.output_dir = output_dir

    def build_with_manifest(
        self,
        source_video: str,
        sample_range: list[float],
        video_fps: float = 8.0,
        video_maxlen: int = 36,
        sampling_strategy: str = "uniform",
    ) -> ClipBuildResult:
        """Crop a continuous MP4 clip and return it with its frame manifest.

        ``video_fps`` and ``video_maxlen`` are accepted for interface
        compatibility but do not influence the crop; the temporary clip keeps
        the source video's time axis.
        """
        if sampling_strategy == "adaptive":
            logger.warning(
                "adaptive clip building is not fully supported yet; falling back to uniform."
            )
            sampling_strategy = "uniform"
        if sampling_strategy != "uniform":
            raise ValueError(f"Unsupported sampling strategy: {sampling_strategy}")

        if not os.path.exists(source_video):
            raise FileNotFoundError(f"Source video not found: {source_video}")

        probe = _probe_video(source_video)
        original_fps = probe["fps"] or video_fps
        duration = probe["duration"]

        # Explicit validation to avoid cryptic ffmpeg failures on degenerate ranges.
        if len(sample_range) != 2:
            raise ValueError("sample_range must be a two-element list [start, end]")
        start, end = sample_range
        if not (0 <= start < end <= duration):
            raise ValueError(
                f"Invalid sample_range [{start}, {end}]: expected "
                f"0 <= start < end <= video_duration ({duration})"
            )

        start = max(0.0, start)
        end = min(end, duration) if duration else end
        if end < start:
            end = start
        clip_duration = end - start

        out_dir = Path(self.output_dir) if self.output_dir else Path("data/08_runtime/agent_clips")
        out_dir.mkdir(parents=True, exist_ok=True)

        video_stem = Path(source_video).stem
        output_path = out_dir / f"{video_stem}_{start:.2f}_{end:.2f}.mp4"

        # Directly crop the continuous segment.  Do NOT pre-extract frames.
        _run_ffmpeg(
            [
                "-y",
                "-ss", str(start),
                "-i", source_video,
                "-t", str(clip_duration),
                "-an",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ]
        )

        # Probe the resulting clip to obtain its actual frame count and fps.
        temp_probe = _probe_video(str(output_path))
        temp_fps = temp_probe["fps"] or original_fps
        temp_total_frames = temp_probe["total_frames"] or 0
        if temp_total_frames <= 0 and temp_probe["duration"] and temp_fps:
            temp_total_frames = max(1, round(temp_probe["duration"] * temp_fps))

        # Build manifest: temp_index -> original_frame / timestamp.
        manifest: list[dict[str, Any]] = []
        for k in range(temp_total_frames):
            timestamp = start + k / temp_fps
            if timestamp > end + 1e-6:
                break
            original_frame = time_to_frame(timestamp, original_fps)
            manifest.append(
                {
                    "temp_index": k,
                    "original_frame": original_frame,
                    "timestamp": round(timestamp, 6),
                }
            )

        return ClipBuildResult(path=str(output_path), manifest=manifest)

    def build(
        self,
        source_video: str,
        sample_range: list[float],
        frames: list[dict[str, Any]],
        video_fps: float = 8.0,
        video_maxlen: int = 36,
        sampling_strategy: str = "uniform",
    ) -> str:
        """Return the path of the temporary clip.

        ``frames`` is accepted for backward compatibility but is ignored; the
        clip is derived directly from ``sample_range``.
        """
        result = self.build_with_manifest(
            source_video=source_video,
            sample_range=sample_range,
            video_fps=video_fps,
            video_maxlen=video_maxlen,
            sampling_strategy=sampling_strategy,
        )
        return result.path


VideoClipBuilder.register(FfmpegVideoClipBuilder)
