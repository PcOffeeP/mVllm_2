"""Lightweight video frame loader for MiniCPM-V inference.

Extracted from _decode_frame_range() and _frame_to_rgb() patterns
in pipeline/preprocessing/minicpm_preprocessor.py (L534-610),
stripped of AutoProcessor / frame_index_by_timestamp dependencies.

Frame pixels are regularized and temporal groups are left to the processor
exactly like the training/serving LlamaFactory MiniCPMVPlugin path.
"""

import av
import math
import numpy as np
from PIL import Image
from typing import List, Optional, Tuple

from .constants import TEMPORAL_FUSION_LEGACY, VIDEO_MAX_PIXELS, VIDEO_MIN_PIXELS


def load_video_frames(
    video_path: str,
    max_frames: int = 8,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    *,
    temporal_fusion: bool = TEMPORAL_FUSION_LEGACY,
    max_pixels: int = VIDEO_MAX_PIXELS,
    min_pixels: int = VIDEO_MIN_PIXELS,
) -> Tuple[List[Image.Image], Optional[List[List[int]]], List[float]]:
    """Load uniformly sampled RGB frames from a video file.

    Args:
        video_path: Path to video file.
        max_frames: Maximum number of frames to sample (default 8, matching
                    MiniCPM-V-4.5 8-frame contract).
        start_time: Start time in seconds.
        end_time: End time in seconds (default: video duration).
        temporal_fusion: Legacy switch. False (default) leaves temporal grouping
                    to the processor, which backfills -1 for every frame so each
                    frame becomes its own visual group — the training/serving
                    semantics. True restores the old single fused group.
        max_pixels: Per-frame upper pixel budget (training/serving default).
        min_pixels: Per-frame lower pixel budget (training/serving default).

    Returns:
        (frames, temporal_ids, timestamps):
          - frames: List[PIL.Image] in RGB mode, each regularized to
            [min_pixels, max_pixels] the same way the training/serving
            MiniCPMVPlugin preprocesses video frames.
          - temporal_ids: Optional[List[List[int]]]. None when temporal_fusion
            is off, so the processor backfills all -1 and every frame forms its
            own group (8 frames -> 8 groups). [[0] * n] when temporal_fusion is
            on, i.e. the legacy single fused group.
          - timestamps: List[float], the PTS timestamp (seconds) of each returned frame.
    """
    container = av.open(video_path, "r")
    try:
        stream = next(s for s in container.streams if s.type == "video")
        time_base = float(stream.time_base)

        # Determine duration
        if stream.duration is not None:
            duration = float(stream.duration * time_base)
        elif container.duration:
            duration = float(container.duration) / 1_000_000.0
        else:
            duration = 0.0

        end = min(end_time if end_time is not None else duration, duration)
        start = max(0.0, start_time)
        if end <= start:
            return [], ([[]] if temporal_fusion else None), []

        # Seek and decode
        seek_pts = int(max(0, start - 0.5) / time_base)
        container.seek(seek_pts, stream=stream)
        end_pts = int(end / time_base)

        all_frames: List[Image.Image] = []
        all_ts: List[float] = []

        for packet in container.demux(stream):
            for frame in packet.decode():
                if frame.pts is None:
                    continue
                if frame.pts > end_pts:
                    break
                ts = float(frame.pts * time_base)
                if start <= ts < end:
                    img = frame.to_image()
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    all_frames.append(img)
                    all_ts.append(ts)

        # Uniform downsampling aligned to LLaMA-Factory training path
        total = len(all_frames)
        n = max(1, min(int(duration * 2.0), max_frames, total))
        indices = np.linspace(0, total - 1, n).astype(np.int32).tolist()
        # Deduplicate while preserving order
        seen: set = set()
        unique_indices: List[int] = []
        for idx in indices:
            if idx not in seen:
                seen.add(idx)
                unique_indices.append(idx)
        sampled = [all_frames[i] for i in unique_indices]
        sampled_timestamps = [all_ts[i] for i in unique_indices]

        n = len(sampled)
        regularized = [
            _regularize_frame_pixels(frame, max_pixels, min_pixels) for frame in sampled
        ]
        temporal_ids: Optional[List[List[int]]] = [[0] * n] if temporal_fusion else None

        return regularized, temporal_ids, sampled_timestamps
    finally:
        container.close()


def _regularize_frame_pixels(image: Image.Image, max_pixels: int, min_pixels: int) -> Image.Image:
    """Regularize one frame to [min_pixels, max_pixels] like training/serving.

    Statement-for-statement identical to LlamaFactory
    ``MiniCPMVPlugin._preprocess_image``
    (LlamaFactory/src/llamafactory/data/mm_plugin.py:217-235).
    """
    if (image.width * image.height) > max_pixels:
        resize_factor = math.sqrt(max_pixels / (image.width * image.height))
        width, height = int(image.width * resize_factor), int(image.height * resize_factor)
        image = image.resize((width, height))

    if (image.width * image.height) < min_pixels:
        resize_factor = math.sqrt(min_pixels / (image.width * image.height))
        width, height = int(image.width * resize_factor), int(image.height * resize_factor)
        image = image.resize((width, height))

    if image.mode != "RGB":
        image = image.convert("RGB")

    return image
