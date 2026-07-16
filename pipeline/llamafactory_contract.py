"""Project-side LLaMA-Factory processor contract integration.

This module patches loaded processors without modifying the LLaMA-Factory
submodule and can wrap the service's *actual* video_processor invocation to
capture the selected frames and a digest of the tensor consumed by the model.
"""

from __future__ import annotations

import hashlib
import io
import logging
import tempfile
from pathlib import Path
from typing import Any

import av

from pipeline.preprocessing.minicpm_preprocessor import (
    FrameMapping,
    MiniCPMVideoPreprocessor,
    configure_processor_max_frames,
)


logger = logging.getLogger(__name__)


def tensor_digest(value: Any) -> str:
    tensor = value.detach().cpu().contiguous()
    return hashlib.sha256(tensor.view(dtype=__import__("torch").uint8).numpy().tobytes()).hexdigest()


class CapturingVideoProcessor:
    """Delegate to the real processor and capture its exact batch output."""

    def __init__(self, processor: Any, *, owner_processor: Any | None = None) -> None:
        self._processor = processor
        self._owner_processor = owner_processor or processor
        self._source_path: str | None = None
        self._capturing = False
        self.last_capture: dict[str, Any] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._processor, name)

    def __call__(self, videos: Any, *args: Any, **kwargs: Any) -> Any:
        result = self._processor(videos, *args, **kwargs)
        if self._capturing:
            return result
        try:
            self._capturing = True
            self.last_capture = self._capture(videos, result)
        except (TypeError, ValueError, RuntimeError, OSError):
            # Calls with already-decoded PIL frames are used internally by the
            # adapter for matching; only path/BytesIO service inputs are captured.
            logger.exception("Failed to capture actual MiniCPM processor output")
        finally:
            self._capturing = False
        return result

    def reset_capture(self, source_path: str | None = None) -> None:
        self.last_capture = None
        self._source_path = source_path

    def _capture(self, videos: Any, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(videos, list) or len(videos) != 1:
            raise ValueError("contract service accepts exactly one video")
        media = videos[0]
        with tempfile.TemporaryDirectory(prefix="minicpm_actual_capture_") as temp_dir:
            path = Path(temp_dir) / "request.mp4"
            if self._source_path is not None:
                path.write_bytes(Path(self._source_path).read_bytes())
            elif isinstance(media, (str, Path)):
                path.write_bytes(Path(media).read_bytes())
            elif isinstance(media, io.BytesIO):
                path.write_bytes(media.getvalue())
            else:
                raise TypeError("capture requires a path or BytesIO video")

            pixel_values = result.get("pixel_values_videos")
            if pixel_values is None:
                pixel_values = result.get("pixel_values")
            if isinstance(pixel_values, list):
                torch = __import__("torch")
                if pixel_values and isinstance(pixel_values[0], list):
                    pixel_values = torch.stack([torch.stack(value) for value in pixel_values])
                elif pixel_values and isinstance(pixel_values[0], torch.Tensor):
                    pixel_values = torch.stack(pixel_values)
            if pixel_values is None or not hasattr(pixel_values, "shape"):
                raise RuntimeError("actual processor output lacks stackable pixel values")
            shape = tuple(pixel_values.shape)
            if len(shape) < 2 or shape[0] != 1:
                raise RuntimeError(f"unsupported video tensor shape: {shape}")
            selected = pixel_values[0]
            n = int(selected.shape[0])
            if not 1 <= n <= 8:
                raise RuntimeError("actual processor selected outside 1..8 frames")

            matcher = object.__new__(MiniCPMVideoPreprocessor)
            matcher._video_processor = self._processor
            matcher._processor = self._owner_processor
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
            if isinstance(media, list) and len(media) == n:
                frames = self._match_actual_input_frames(media, decoded, indices, timestamps)
            else:
                frames = matcher._match_processor_frames(decoded, indices, timestamps, selected, n)

        return {
            "frames": [
                {"index": frame.input_index, "original_frame": frame.original_frame, "timestamp": frame.timestamp}
                for frame in frames
            ],
            "tensor_digest": tensor_digest(pixel_values),
            "tensor_shape": list(shape),
        }

    @staticmethod
    def _match_actual_input_frames(
        actual_frames: list[Any],
        decoded_frames: list[Any],
        decoded_indices: list[int],
        decoded_timestamps: list[float],
    ) -> list[FrameMapping]:
        """Match the exact PIL frames passed to image_processor back to the MP4."""
        import numpy as np

        results: list[FrameMapping] = []
        used: set[int] = set()
        for input_index, actual in enumerate(actual_frames):
            actual_array = np.asarray(actual.convert("RGB"), dtype=np.int16)
            best_match = -1
            best_diff = float("inf")
            for decoded_index, decoded in enumerate(decoded_frames):
                if decoded_index in used:
                    continue
                decoded_rgb = decoded.convert("RGB")
                if decoded_rgb.size != actual.size:
                    # Mirror BasePlugin._preprocess_image: the selected frame
                    # is resized with PIL's default resampler before the actual
                    # MiniCPM image_processor sees it.
                    decoded_rgb = decoded_rgb.resize(actual.size)
                decoded_array = np.asarray(decoded_rgb, dtype=np.int16)
                diff = float(np.abs(actual_array - decoded_array).mean())
                if diff < best_diff:
                    best_diff = diff
                    best_match = decoded_index
            if best_match < 0 or best_diff > 1.0:
                raise RuntimeError(
                    f"actual processor frame {input_index} could not be matched exactly"
                )
            used.add(best_match)
            results.append(
                FrameMapping(
                    input_index=input_index,
                    original_frame=decoded_indices[best_match],
                    timestamp=decoded_timestamps[best_match],
                )
            )
        return results


def configure_loaded_processor(processor: Any, *, capture: bool = False) -> CapturingVideoProcessor | None:
    """Set the actual child limit to 8 and optionally install exact capture."""
    video_processor = configure_processor_max_frames(processor)
    if not capture:
        return None
    image_processor = getattr(processor, "image_processor", None)
    if processor.__class__.__name__ == "MiniCPMVProcessor" and image_processor is not None:
        # MiniCPM-V 4.5 can expose a video_processor attribute, but the
        # LLaMA-Factory MiniCPMVPlugin at the pinned commit processes decoded
        # video frames through image_processor.
        wrapper = CapturingVideoProcessor(image_processor, owner_processor=processor)
        processor.image_processor = wrapper
    else:
        wrapper = CapturingVideoProcessor(video_processor, owner_processor=processor)
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
