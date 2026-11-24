"""Pluggable frame extractors for L0/L1/L2 video decoding and L3 image binding."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Protocol

from .schema import FrameExtractionResult

FALLBACK_TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
SHOWINFO_RE = re.compile(r"\] n:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:(-?\d+(?:\.\d+)?)")
SHA256_RE = re.compile(r"[a-f0-9]{64}")


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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=".tmp_l3_"))
    tmp_file = tmp_dir / "frame.png"
    try:
        shutil.copyfile(source_image_path, tmp_file)
        if not tmp_file.is_file() or tmp_file.stat().st_size == 0:
            return FrameExtractionResult(
                status="skipped",
                backend=backend,
                skip_reason=f"l3_copy_empty: {source_image_path}",
            )
        digest = sha256_file(tmp_file)
        os.replace(tmp_file, output_path)
    except OSError as exc:
        return FrameExtractionResult(
            status="skipped",
            backend=backend,
            skip_reason=f"l3_copy_failed: {exc}",
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return FrameExtractionResult(
        status="copied",
        output_path=output_path,
        image_sha256=digest,
        backend=backend,
    )


class FfmpegFrameExtractor:
    """Decode exact 0-based frame n via ffmpeg select=eq(n,frame_index),showinfo.

    Writes into a fresh per-call temporary directory first so a pre-existing stale PNG at
    ``output_path`` can never be mistaken for freshly decoded output.
    """

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
        tmp_dir = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=".tmp_ffmpeg_"))
        tmp_file = tmp_dir / "frame.png"
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
            str(tmp_file),
        ]
        try:
            try:
                result = subprocess.run(command, capture_output=True, text=True)
            except OSError as exc:
                return FrameExtractionResult(
                    status="skipped",
                    backend="ffmpeg",
                    skip_reason=f"ffmpeg_exec_error: {exc}",
                )
            if result.returncode != 0 or not tmp_file.is_file() or tmp_file.stat().st_size == 0:
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
            digest = sha256_file(tmp_file)
            os.replace(tmp_file, output_path)
            return FrameExtractionResult(
                status="extracted",
                output_path=output_path,
                pts_seconds=pts_seconds,
                image_sha256=digest,
                backend="ffmpeg",
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

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
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(dir=output_path.parent, prefix=".tmp_opencv_"))
        tmp_file = tmp_dir / "frame.png"
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
            if not cv2.imwrite(str(tmp_file), image) or not tmp_file.is_file() or tmp_file.stat().st_size == 0:
                return FrameExtractionResult(
                    status="skipped",
                    backend="opencv",
                    skip_reason=f"opencv_write_failed: {output_path}",
                )
            digest = sha256_file(tmp_file)
            os.replace(tmp_file, output_path)
            return FrameExtractionResult(
                status="extracted",
                output_path=output_path,
                pts_seconds=pts_seconds,
                image_sha256=digest,
                backend="opencv",
            )
        finally:
            cap.release()
            shutil.rmtree(tmp_dir, ignore_errors=True)

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


@dataclass(frozen=True)
class L3ImageResolution:
    """Resolved L3 model-input image path with explicit run-binding provenance."""

    path: Path | None
    binding_basis: str
    skip_reason: str | None = None
    observed_sha256: str | None = None


def _safe_run_dir_tokens(
    *,
    run_id: str | None,
    input_id: str | None,
    run_slug: str | None,
) -> list[str]:
    """Build safe single-segment directory tokens for run-scoped L3 lookup."""
    tokens: list[str] = []
    raw_candidates: list[str] = []
    if isinstance(run_id, str) and run_id.strip():
        raw_candidates.append(run_id.strip())
    if isinstance(run_slug, str) and run_slug.strip():
        raw_candidates.append(run_slug.strip())
    if isinstance(input_id, str) and input_id.strip():
        raw_candidates.append(input_id.strip())
        if input_id.startswith("input@sha256:"):
            hex_part = input_id.split(":", 1)[1].strip()
            if hex_part:
                raw_candidates.append(hex_part)
                raw_candidates.append(f"input_{hex_part[:12]}")
                raw_candidates.append(f"input__{hex_part[:12]}")
    for token in raw_candidates:
        if "/" in token or "\\" in token or token in (".", "..") or ".." in Path(token).parts:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _checked_candidate(base: Path, candidate: Path) -> Path | None:
    resolved_base = base.resolve()
    resolved_cand = candidate.resolve()
    if resolved_cand.is_relative_to(resolved_base):
        return resolved_cand
    return None


def resolve_l3_image(
    image_name: str | None,
    *,
    candidate_id: str,
    run_id: str | None = None,
    input_id: str | None = None,
    run_slug: str | None = None,
    expected_sha256: str | None = None,
    allow_unscoped_shared_fallback: bool = True,
    l3_frames_dir: Path | None = None,
    input_records_dir: Path | None = None,
    media_root: Path | None = None,
) -> L3ImageResolution:
    """Resolve the pre-extracted L3 model-input PNG with run-level binding guarantees.

    Priority:
    1. Run-scoped directory matches (``<base>/<run_token>/<candidate_id>/<image>`` or
       ``<base>/<candidate_id>/<run_token>/<image>``).
    2. If ``expected_sha256`` is declared on the frame, a shared-directory file is accepted
       ONLY when its observed SHA-256 matches ``expected_sha256``.
    3. Unscoped shared fallback (``<base>/<candidate_id>/<image>``) is ONLY permitted when
       ``allow_unscoped_shared_fallback`` is True (no cross-run ambiguity for this candidate).
       Otherwise, returns an explicit skip reason rather than attributing a shared PNG to
       multiple runs.
    """
    if not image_name or not isinstance(image_name, str):
        return L3ImageResolution(
            path=None,
            binding_basis="unbound_skipped",
            skip_reason="l3_image_name_missing_no_l2_substitution",
        )
    valid_expected = (
        expected_sha256
        if isinstance(expected_sha256, str) and SHA256_RE.fullmatch(expected_sha256)
        else None
    )
    raw = Path(image_name)

    if raw.is_absolute():
        if not raw.is_file():
            return L3ImageResolution(
                path=None,
                binding_basis="unbound_skipped",
                skip_reason=f"l3_image_not_found_no_l2_substitution: {raw}",
            )
        obs = sha256_file(raw)
        if valid_expected is not None:
            if obs != valid_expected:
                return L3ImageResolution(
                    path=None,
                    binding_basis="unbound_skipped",
                    skip_reason=f"l3_image_sha256_mismatch: observed={obs} != expected={valid_expected}",
                    observed_sha256=obs,
                )
            return L3ImageResolution(path=raw, binding_basis="frame_sha256_verified", observed_sha256=obs)
        if not allow_unscoped_shared_fallback:
            return L3ImageResolution(
                path=None,
                binding_basis="unbound_skipped",
                skip_reason=f"l3_image_ambiguous_across_runs_no_run_binding: {raw}",
                observed_sha256=obs,
            )
        return L3ImageResolution(path=raw, binding_basis="absolute_path_single_run", observed_sha256=obs)

    if ".." in raw.parts:
        return L3ImageResolution(
            path=None,
            binding_basis="unbound_skipped",
            skip_reason=f"l3_image_path_traversal_rejected: {image_name}",
        )

    bases: list[Path] = [b for b in (l3_frames_dir, input_records_dir, media_root) if b is not None]
    run_tokens = _safe_run_dir_tokens(run_id=run_id, input_id=input_id, run_slug=run_slug)

    # 1. Run-scoped paths first
    run_scoped_candidates: list[Path] = []
    for base in bases:
        for token in run_tokens:
            for cand in (
                base / token / candidate_id / raw,
                base / candidate_id / token / raw,
                base / "frames" / token / candidate_id / raw,
            ):
                checked = _checked_candidate(base, cand)
                if checked is not None and checked not in run_scoped_candidates:
                    run_scoped_candidates.append(checked)

    for cand in run_scoped_candidates:
        if cand.is_file():
            obs = sha256_file(cand)
            if valid_expected is not None and obs != valid_expected:
                return L3ImageResolution(
                    path=None,
                    binding_basis="unbound_skipped",
                    skip_reason=f"l3_image_sha256_mismatch: observed={obs} != expected={valid_expected}",
                    observed_sha256=obs,
                )
            basis = "frame_sha256_verified" if valid_expected is not None else "run_scoped_directory"
            return L3ImageResolution(path=cand, binding_basis=basis, observed_sha256=obs)

    # 2. Shared candidate-level paths (only when SHA-256 verified or unambiguous single run)
    shared_candidates: list[Path] = []
    for base in bases:
        for cand in (
            base / candidate_id / raw,
            base / "frames" / candidate_id / raw,
            base / raw,
        ):
            checked = _checked_candidate(base, cand)
            if checked is not None and checked not in shared_candidates:
                shared_candidates.append(checked)

    existing_shared = [cand for cand in shared_candidates if cand.is_file()]
    if existing_shared:
        if valid_expected is not None:
            for cand in existing_shared:
                obs = sha256_file(cand)
                if obs == valid_expected:
                    return L3ImageResolution(
                        path=cand,
                        binding_basis="frame_sha256_verified",
                        observed_sha256=obs,
                    )
            return L3ImageResolution(
                path=None,
                binding_basis="unbound_skipped",
                skip_reason=f"l3_image_sha256_mismatch_no_matching_file_for_expected={valid_expected}",
            )
        if not allow_unscoped_shared_fallback:
            return L3ImageResolution(
                path=None,
                binding_basis="unbound_skipped",
                skip_reason=(
                    f"l3_image_ambiguous_across_runs_no_run_binding: shared file "
                    f"{existing_shared[0]} cannot be attributed to run_id={run_id!r} / input_id={input_id!r}"
                ),
            )
        chosen = existing_shared[0]
        return L3ImageResolution(
            path=chosen,
            binding_basis="single_run_candidate_directory",
            observed_sha256=sha256_file(chosen),
        )

    return L3ImageResolution(
        path=None,
        binding_basis="unbound_skipped",
        skip_reason=f"l3_image_not_found_no_l2_substitution: {image_name}",
    )


def resolve_l3_image_path(
    image_name: str | None,
    *,
    candidate_id: str,
    run_id: str | None = None,
    input_id: str | None = None,
    run_slug: str | None = None,
    expected_sha256: str | None = None,
    allow_unscoped_shared_fallback: bool = True,
    l3_frames_dir: Path | None = None,
    input_records_dir: Path | None = None,
    media_root: Path | None = None,
) -> Path | None:
    """Convenience wrapper returning only the resolved L3 Path (or None)."""
    return resolve_l3_image(
        image_name,
        candidate_id=candidate_id,
        run_id=run_id,
        input_id=input_id,
        run_slug=run_slug,
        expected_sha256=expected_sha256,
        allow_unscoped_shared_fallback=allow_unscoped_shared_fallback,
        l3_frames_dir=l3_frames_dir,
        input_records_dir=input_records_dir,
        media_root=media_root,
    ).path
