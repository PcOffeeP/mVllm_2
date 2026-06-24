"""Project-side LLaMA-Factory processor contract integration.

This module patches loaded processors without modifying the LLaMA-Factory
submodule and can wrap the service's *actual* video_processor invocation to
capture the selected frames and a digest of the tensor consumed by the model.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path
from typing import Any

import av

from pipeline.preprocessing.minicpm_preprocessor import (
    MiniCPMVideoPreprocessor,
    configure_processor_max_frames,
)


def tensor_digest(value: Any) -> str:
    tensor = value.detach().cpu().contiguous()
    return hashlib.sha256(tensor.view(dtype=__import__("torch").uint8).numpy().tobytes()).hexdigest()


class CapturingVideoProcessor:
    """Delegate to the real processor and capture its exact batch output."""

    def __init__(self, processor: Any) -> None:
        self._processor = processor
        self.last_capture: dict[str, Any] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._processor, name)

    def __call__(self, videos: Any, *args: Any, **kwargs: Any) -> Any:
        result = self._processor(videos, *args, **kwargs)
        try:
            self.last_capture = self._capture(videos, result)
        except (TypeError, ValueError, RuntimeError, OSError):
            # Calls with already-decoded PIL frames are used internally by the
            # adapter for matching; only path/BytesIO service inputs are captured.
            pass
        return result

    def reset_capture(self) -> None:
        self.last_capture = None

    def _capture(self, videos: Any, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(videos, list) or len(videos) != 1:
            raise ValueError("contract service accepts exactly one video")
        media = videos[0]
        with tempfile.TemporaryDirectory(prefix="minicpm_actual_capture_") as temp_dir:
            path = Path(temp_dir) / "request.mp4"
            if isinstance(media, (str, Path)):
                path.write_bytes(Path(media).read_bytes())
            elif isinstance(media, io.BytesIO):
                path.write_bytes(media.getvalue())
            else:
                raise TypeError("capture requires a path or BytesIO video")

            pixel_values = result.get("pixel_values_videos")
            if pixel_values is None:
                raise RuntimeError("actual processor output lacks pixel_values_videos")
            shape = tuple(pixel_values.shape)
            if len(shape) == 5:
                selected = pixel_values[0]
            elif len(shape) == 4:
                selected = pixel_values
            else:
                raise RuntimeError(f"unsupported video tensor shape: {shape}")
            n = int(selected.shape[0])
            if not 1 <= n <= 8:
                raise RuntimeError("actual processor selected outside 1..8 frames")

            matcher = object.__new__(MiniCPMVideoPreprocessor)
            matcher._video_processor = self._processor
            matcher._max_frames = 8
            frame_index_map = matcher._actual_frame_index_map(str(path))
            container = av.open(str(path), "r")
            try:
                stream = next(item for item in container.streams if item.type == "video")
                duration = (
                    float(stream.duration * stream.time_base)
                    if stream.duration is not None
                    else float(container.duration or 0) / 1_000_000.0
                )
                decoded, indices, timestamps = matcher._decode_frame_range(
                    container, stream, 0.0, duration, len(frame_index_map), frame_index_map
                )
            finally:
                container.close()
            frames = matcher._match_processor_frames(decoded, indices, timestamps, selected, n)

        return {
            "frames": [
                {"index": frame.input_index, "original_frame": frame.original_frame, "timestamp": frame.timestamp}
                for frame in frames
            ],
            "tensor_digest": tensor_digest(pixel_values),
            "tensor_shape": list(shape),
        }


def configure_loaded_processor(processor: Any, *, capture: bool = False) -> CapturingVideoProcessor | None:
    """Set the actual child limit to 8 and optionally install exact capture."""
    video_processor = configure_processor_max_frames(processor)
    if not capture:
        return None
    wrapper = CapturingVideoProcessor(video_processor)
    processor.video_processor = wrapper
    return wrapper


def install_training_processor_contract() -> None:
    """Patch LLaMA-Factory's loader so every training process configures the child processor."""
    from llamafactory.model import loader

    if getattr(loader.patch_processor, "_tensile_contract", False):
        return
    original = loader.patch_processor

    def patched(processor: Any, tokenizer: Any, model_args: Any) -> None:
        original(processor, tokenizer, model_args)
        configure_loaded_processor(processor)

    patched._tensile_contract = True  # type: ignore[attr-defined]
    loader.patch_processor = patched
