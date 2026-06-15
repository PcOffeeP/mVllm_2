"""Video sampling abstractions and index/time conversion utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


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
