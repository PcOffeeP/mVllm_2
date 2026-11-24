"""Pluggable frame extractors for L0/L1/L2 video decoding and L3 image binding."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
from typing import Protocol

from .schema import FrameExtractionResult

FALLBACK_TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
SHOWINFO_RE = re.compile(r"\] n:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:(-?\d+(?:\.\d+)?)")


def sha256_file(path: Path) -> str | None:
    """Compute lowercase SHA-256 hex digest of an existing regular file."""
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_ffmpeg() -> str | None:
    """Locate ffmpeg on PATH or standard macOS/Linux fallback directories."""
    for candidate in filter(
        None,
        (shutil.which("ffmpeg"),) + tuple(str(Path(d) / "ffmpeg") for d in FALLBACK_TOOL_DIRS),
    ):
        if Path(candidate).is_file():
            return candidate
    return None


class FrameExtractor(Protocol):
    """Protocol for extracting a single decoded video frame or copying an L3 input image."""

    def extract_video_frame(
        self,
        video_path: Path,
        frame_index: int,
        output_path: Path,
    ) -> FrameExtractionResult: ...

    def copy_l3_image(
        self,
        source_image_path: Path,
        output_path: Path,
    ) -> FrameExtractionResult: ...


class MetadataOnlyExtractor:
    """Extractor that never decodes videos or copies PNG files."""

    def extract_video_frame(
        self,
        video_path: Path,
        frame_index: int,
        output_path: Path,
    ) -> FrameExtractionResult:
        return FrameExtractionResult(status="metadata_only", backend="metadata_only")

    def copy_l3_image(
        self,
        source_image_path: Path,
        output_path: Path,
    ) -> FrameExtractionResult:
        return FrameExtractionResult(status="metadata_only", backend="metadata_only")


def _copy_l3_image_impl(source_image_path: Path, output_path: Path, backend: str) -> FrameExtractionResult:
    if not source_image_path.is_file():
        return FrameExtractionResult(
            status="skipped",
            backend=backend,
            skip_reason=f"l3_image_missing: {source_image_path}",
        )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_image_path, output_path)
    except OSError as exc:
        return FrameExtractionResult(
            status="skipped",
            backend=backend,
            skip_reason=f"l3_copy_failed: {exc}",
        )
    return FrameExtractionResult(
        status="copied",
        output_path=output_path,
        image_sha256=sha256_file(output_path),
        backend=backend,
    )


class FfmpegFrameExtractor:
    """Decode exact 0-based frame n via ffmpeg select=eq(n,frame_index),showinfo."""

    def __init__(self, ffmpeg_bin: str | None = None) -> None:
        self.ffmpeg_bin = ffmpeg_bin if ffmpeg_bin is not None else find_ffmpeg()

    def available(self) -> bool:
        return bool(self.ffmpeg_bin and Path(self.ffmpeg_bin).is_file())

    def extract_video_frame(
        self,
        video_path: Path,
        frame_index: int,
        output_path: Path,
    ) -> FrameExtractionResult:
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            return FrameExtractionResult(
                status="skipped",
                backend="ffmpeg",
                skip_reason=f"invalid_frame_index: {frame_index!r}",
            )
        if not video_path.is_file():
            return FrameExtractionResult(
                status="skipped",
                backend="ffmpeg",
                skip_reason=f"media_file_missing: {video_path}",
            )
        if not self.available():
            return FrameExtractionResult(
                status="skipped",
                backend="ffmpeg",
                skip_reason="ffmpeg_not_available",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.ffmpeg_bin),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "info",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"select=eq(n\\,{frame_index}),showinfo",
            "-vsync",
            "0",
            "-frames:v",
            "1",
            str(output_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except OSError as exc:
            return FrameExtractionResult(
                status="skipped",
                backend="ffmpeg",
                skip_reason=f"ffmpeg_exec_error: {exc}",
            )
        if result.returncode != 0 or not output_path.is_file():
            detail = (result.stderr or "").strip()[-240:] or "ffmpeg wrote no output frame"
            return FrameExtractionResult(
                status="skipped",
                backend="ffmpeg",
                skip_reason=f"ffmpeg_decode_failed: {detail}",
            )
        pts_seconds = None
        for line in result.stderr.splitlines():
            match = SHOWINFO_RE.search(line)
            if match:
                pts_seconds = float(match.group(3))
                break
        return FrameExtractionResult(
            status="extracted",
            output_path=output_path,
            pts_seconds=pts_seconds,
            image_sha256=sha256_file(output_path),
            backend="ffmpeg",
        )

    def copy_l3_image(
        self,
        source_image_path: Path,
        output_path: Path,
    ) -> FrameExtractionResult:
        return _copy_l3_image_impl(source_image_path, output_path, backend="ffmpeg")


class OpenCVFrameExtractor:
    """Sequential-decode fallback using cv2.VideoCapture (never uses random seek)."""

    def available(self) -> bool:
        try:
            import cv2  # noqa: F401
        except ImportError:
            return False
        return True

    def extract_video_frame(
        self,
        video_path: Path,
        frame_index: int,
        output_path: Path,
    ) -> FrameExtractionResult:
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            return FrameExtractionResult(
                status="skipped",
                backend="opencv",
                skip_reason=f"invalid_frame_index: {frame_index!r}",
            )
        if not video_path.is_file():
            return FrameExtractionResult(
                status="skipped",
                backend="opencv",
                skip_reason=f"media_file_missing: {video_path}",
            )
        try:
            import cv2
        except ImportError:
            return FrameExtractionResult(
                status="skipped",
                backend="opencv",
                skip_reason="opencv_not_available",
            )
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            cap.release()
            return FrameExtractionResult(
                status="skipped",
                backend="opencv",
                skip_reason=f"opencv_open_failed: {video_path}",
            )
        try:
            for _ in range(frame_index):
                if not cap.grab():
                    return FrameExtractionResult(
                        status="skipped",
                        backend="opencv",
                        skip_reason=f"opencv_eof_before_frame_{frame_index}",
                    )
            ok, image = cap.read()
            if not ok or image is None:
                return FrameExtractionResult(
                    status="skipped",
                    backend="opencv",
                    skip_reason=f"opencv_read_failed_at_frame_{frame_index}",
                )
            pos_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
            pts_seconds = round(float(pos_msec) / 1000.0, 6) if pos_msec is not None and pos_msec >= 0 else None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(output_path), image) or not output_path.is_file():
                return FrameExtractionResult(
                    status="skipped",
                    backend="opencv",
                    skip_reason=f"opencv_write_failed: {output_path}",
                )
            return FrameExtractionResult(
                status="extracted",
                output_path=output_path,
                pts_seconds=pts_seconds,
                image_sha256=sha256_file(output_path),
                backend="opencv",
            )
        finally:
            cap.release()

    def copy_l3_image(
        self,
        source_image_path: Path,
        output_path: Path,
    ) -> FrameExtractionResult:
        return _copy_l3_image_impl(source_image_path, output_path, backend="opencv")


class AutoFrameExtractor:
    """Prefer ffmpeg; fall back to OpenCV if ffmpeg is unavailable."""

    def __init__(
        self,
        ffmpeg_extractor: FfmpegFrameExtractor | None = None,
        opencv_extractor: OpenCVFrameExtractor | None = None,
    ) -> None:
        self._ffmpeg = ffmpeg_extractor or FfmpegFrameExtractor()
        self._opencv = opencv_extractor or OpenCVFrameExtractor()

    def _delegate(self) -> FrameExtractor | None:
        if self._ffmpeg.available():
            return self._ffmpeg
        if self._opencv.available():
            return self._opencv
        return None

    def extract_video_frame(
        self,
        video_path: Path,
        frame_index: int,
        output_path: Path,
    ) -> FrameExtractionResult:
        if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
            return FrameExtractionResult(
                status="skipped",
                backend="auto",
                skip_reason=f"invalid_frame_index: {frame_index!r}",
            )
        if not video_path.is_file():
            return FrameExtractionResult(
                status="skipped",
                backend="auto",
                skip_reason=f"media_file_missing: {video_path}",
            )
        delegate = self._delegate()
        if delegate is None:
            return FrameExtractionResult(
                status="skipped",
                backend="auto",
                skip_reason="no_frame_extractor_backend_available",
            )
        return delegate.extract_video_frame(video_path, frame_index, output_path)

    def copy_l3_image(
        self,
        source_image_path: Path,
        output_path: Path,
    ) -> FrameExtractionResult:
        return _copy_l3_image_impl(source_image_path, output_path, backend="auto")


def build_extractor(mode: str, backend: str = "auto") -> FrameExtractor:
    """Factory returning a FrameExtractor for the chosen CLI mode and backend."""
    if mode == "metadata_only":
        return MetadataOnlyExtractor()
    if backend == "ffmpeg":
        return FfmpegFrameExtractor()
    if backend == "opencv":
        return OpenCVFrameExtractor()
    if backend == "auto":
        return AutoFrameExtractor()
    raise ValueError(f"unsupported backend: {backend!r}")


def resolve_layer_media_path(
    recorded_path: str | None,
    *,
    layer: str,
    media_root: Path | None = None,
) -> Path | None:
    """Resolve an L0/L1/L2 video path from the recorded path and optional media_root."""
    if not recorded_path or not isinstance(recorded_path, str):
        return None
    raw = Path(recorded_path)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
        if media_root is not None:
            basename = raw.name
            layer_subdirs = {
                "l0": ("videos", "data/videos", ""),
                "l1": ("roi/videos", "data/roi/videos", ""),
                "l2": ("sub_video/videos", "data/sub_video/videos", ""),
            }
            for sub in layer_subdirs.get(layer, ("",)):
                candidates.append(media_root / sub / basename if sub else media_root / basename)
    else:
        if media_root is not None:
            candidates.append(media_root / raw)
            basename = raw.name
            layer_subdirs = {
                "l0": ("videos", "data/videos", ""),
                "l1": ("roi/videos", "data/roi/videos", ""),
                "l2": ("sub_video/videos", "data/sub_video/videos", ""),
            }
            for sub in layer_subdirs.get(layer, ("",)):
                candidates.append(media_root / sub / basename if sub else media_root / basename)
        candidates.append(raw)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0] if candidates else None


def resolve_l3_image_path(
    image_name: str | None,
    *,
    candidate_id: str,
    l3_frames_dir: Path | None = None,
    input_records_dir: Path | None = None,
    media_root: Path | None = None,
) -> Path | None:
    """Resolve the pre-extracted L3 model-input PNG path without ever substituting L2."""
    if not image_name or not isinstance(image_name, str):
        return None
    raw = Path(image_name)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        if ".." in raw.parts:
            return None
        search_bases: list[tuple[Path, Path]] = []
        if l3_frames_dir is not None:
            search_bases.append((l3_frames_dir, l3_frames_dir / candidate_id / raw))
            search_bases.append((l3_frames_dir, l3_frames_dir / raw))
        if input_records_dir is not None:
            search_bases.append((input_records_dir, input_records_dir / candidate_id / raw))
            search_bases.append((input_records_dir, input_records_dir / raw))
        if media_root is not None:
            search_bases.append((media_root, media_root / candidate_id / raw))
            search_bases.append((media_root, media_root / "frames" / candidate_id / raw))
        for base, candidate in search_bases:
            resolved_base = base.resolve()
            resolved_cand = candidate.resolve()
            if resolved_cand.is_relative_to(resolved_base):
                candidates.append(resolved_cand)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0] if candidates else None
