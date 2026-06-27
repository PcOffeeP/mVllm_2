"""Lightweight video frame loader for MiniCPM-V inference.

Extracted from _decode_frame_range() and _frame_to_rgb() patterns
in pipeline/preprocessing/minicpm_preprocessor.py (L534-610),
stripped of AutoProcessor / frame_index_by_timestamp dependencies.
"""

import av
import numpy as np
from PIL import Image
from typing import List, Optional, Tuple


def load_video_frames(
    video_path: str,
    max_frames: int = 8,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
) -> Tuple[List[Image.Image], List[List[int]], List[float]]:
    """Load uniformly sampled RGB frames from a video file.

    Args:
        video_path: Path to video file.
        max_frames: Maximum number of frames to sample (default 8, matching
                    MiniCPM-V-4.5 8-frame contract).
        start_time: Start time in seconds.
        end_time: End time in seconds (default: video duration).

    Returns:
        (frames, temporal_ids, timestamps):
          - frames: List[PIL.Image] in RGB mode.
          - temporal_ids: List[List[int]], all frames in the same temporal group.
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
            return [], [[]], []

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
        temporal_ids: List[List[int]] = [[0] * n] if n > 0 else [[]]

        return sampled, temporal_ids, sampled_timestamps
    finally:
        container.close()
