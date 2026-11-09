"""Read-only, experimental native-picture evidence for ambiguous frame anchors.

This module never changes aligned.py admission, source/candidate status or media.
Native/local metrics are measurements for review and independent calibration;
they are not a new truth label or automatic generation decision.
"""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
import hashlib
from pathlib import Path
import subprocess
import tempfile

import numpy as np

try:
    from . import aligned, pilot as base
except ImportError:
    import aligned
    import pilot as base

SCHEMA = "tensile-anchor-evidence/1"


def _gray_image(image) -> np.ndarray:
    value = np.asarray(image)
    if value.ndim != 2 or not value.size:
        raise ValueError("native evidence requires a nonempty grayscale H×W image")
    if not np.isfinite(value).all() or value.min() < 0 or value.max() > 255:
        raise ValueError("grayscale samples must be finite and in [0, 255]")
    return value.astype(np.float32)


def _area_thumbnail(image: np.ndarray, size: int = aligned.FEATURE_SIZE) -> np.ndarray:
    """Defined area-bin pooling for array experiments, not an FFmpeg replica."""
    def weights(length: int) -> np.ndarray:
        edges = np.linspace(0, length, size + 1)
        starts = np.arange(length)
        overlaps = np.maximum(0, np.minimum(edges[1:, None], starts + 1)
                              - np.maximum(edges[:-1, None], starts))
        return overlaps / (length / size)
    return np.rint(weights(image.shape[0]) @ image @ weights(image.shape[1]).T).astype(np.uint8)


def _tiles(shape: tuple[int, int], tile_size: int) -> list[dict]:
    if type(tile_size) is not int or tile_size <= 0:
        raise ValueError("tile_size must be a positive integer")
    h, w = shape
    return [{"index": index, "top": y, "left": x,
             "height": min(tile_size, h - y), "width": min(tile_size, w - x)}
            for index, (y, x) in enumerate((y, x) for y in range(0, h, tile_size)
                                                       for x in range(0, w, tile_size))]


def _local_metrics(expected: np.ndarray, actual: np.ndarray, tiles: list[dict]) -> dict:
    error = np.abs(expected - actual)
    per_tile, edge_per_tile = [], []
    for tile in tiles:
        y, x, h, w = (tile[k] for k in ("top", "left", "height", "width"))
        a, b = expected[y:y+h, x:x+w], actual[y:y+h, x:x+w]
        per_tile.append(float(error[y:y+h, x:x+w].mean()))
        horizontal = np.abs(np.diff(a, axis=1) - np.diff(b, axis=1))
        vertical = np.abs(np.diff(a, axis=0) - np.diff(b, axis=0))
        count = horizontal.size + vertical.size
        edge_per_tile.append(float((horizontal.sum() + vertical.sum()) / count) if count else None)
    edges = [x for x in edge_per_tile if x is not None]
    return {"native_mae": float(error.mean()), "native_max_pixel_error": float(error.max()),
            "tile_mae": per_tile, "tile_max_mae": max(per_tile),
            "tile_gradient_mae": edge_per_tile,
            "tile_max_gradient_mae": max(edges) if edges else None}


def _analyze_frames(expected_anchor, actual_frames: Iterable, anchor_index: int, *,
                    tile_size: int, coarse_expected_anchor=None, coarse_actual_frames=None,
                    coarse_implementation: str) -> dict:
    expected = _gray_image(expected_anchor)
    if type(anchor_index) is not int or anchor_index < 0:
        raise ValueError("anchor_index must be a nonnegative integer")
    tiles = _tiles(expected.shape, tile_size)
    coarse_expected = (_area_thumbnail(expected) if coarse_expected_anchor is None
                       else _gray_image(coarse_expected_anchor))
    rows = []
    for index, value in enumerate(actual_frames):
        actual = _gray_image(value)
        if actual.shape != expected.shape:
            raise ValueError("native geometry mismatch; no automatic resizing or registration")
        if coarse_actual_frames is not None and index >= len(coarse_actual_frames):
            raise ValueError("coarse and native decoded frame counts differ")
        coarse = (_area_thumbnail(actual) if coarse_actual_frames is None
                  else _gray_image(coarse_actual_frames[index]))
        if coarse.shape != coarse_expected.shape:
            raise ValueError("coarse evidence shape mismatch")
        coarse_mae = float(np.abs(coarse_expected.astype(np.float32) - coarse.astype(np.float32)).mean())
        rows.append({"frame_index": index, "claimed_same_index": index == anchor_index,
                     "coarse_mae": coarse_mae,
                     "within_current_coarse_error_envelope": coarse_mae <= aligned.MAX_MEAN_PIXEL_ERROR,
                     **_local_metrics(expected, actual, tiles)})
    if not rows or anchor_index >= len(rows):
        raise ValueError("claimed anchor is outside the decoded sequence")
    if coarse_actual_frames is not None and len(coarse_actual_frames) != len(rows):
        raise ValueError("coarse and native decoded frame counts differ")
    alternatives = [r["frame_index"] for r in rows if not r["claimed_same_index"]
                    and r["within_current_coarse_error_envelope"]]
    return {"schema": SCHEMA, "analysis_status": "evidence_only_pending",
            "automatic_generation_allowed": False, "changes_production_state": False,
            "claimed_anchor_index": anchor_index, "searched_frame_count": len(rows),
            "native_shape": list(expected.shape), "tile_size": tile_size, "tiles": tiles,
            "expected_anchor_float32_sha256": hashlib.sha256(expected.astype("<f4").tobytes()).hexdigest(),
            "coarse_feature_size": list(coarse_expected.shape),
            "coarse_implementation": coarse_implementation,
            "current_coarse_error_envelope": aligned.MAX_MEAN_PIXEL_ERROR,
            "competing_frames_within_current_coarse_envelope": alternatives,
            "frames": rows,
            "native_detail_warning": ("native_picture_smaller_than_coarse_feature_no_added_resolution"
                                      if min(expected.shape) < aligned.FEATURE_SIZE else None),
            "limitations": ["local_metrics_are_not_calibrated_admission_thresholds",
                            "temporal_context_must_not_override_an_ambiguous_central_picture",
                            "lossy_or_static_pictures_can_remain_unresolvable",
                            "all_alternatives_retained_no_automatic_best_match_selection"]}


def analyze_anchor(expected_anchor, actual_frames, anchor_index: int, *, tile_size: int = 16,
                   coarse_expected_anchor=None, coarse_actual_frames=None) -> dict:
    """Pure-array evidence; the caller supplies the known spatial transformation.

    `frames` retains every decoded index, including the claimed match. Each row
    contains whole/native/tile/gradient measurements. No score grants admission.
    Pass existing aligned.py coarse features to preserve its exact coarse values;
    without them a named area-bin proxy is computed only for synthetic analysis.
    """
    if (coarse_expected_anchor is None) != (coarse_actual_frames is None):
        raise ValueError("provide both coarse inputs, or neither")
    return _analyze_frames(expected_anchor, actual_frames, anchor_index, tile_size=tile_size,
                           coarse_expected_anchor=coarse_expected_anchor,
                           coarse_actual_frames=coarse_actual_frames,
                           coarse_implementation=("supplied_aligned_features" if coarse_expected_anchor is not None
                                                  else "numpy_area_bins_proxy_not_production_recheck"))


def _native_command(path: Path, video_filter: str) -> list[str]:
    return ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "2", "-noautorotate", "-i", str(path),
            "-map", "0:v:0", "-vf", video_filter, "-vsync", "0", "-threads", "2",
            "-f", "rawvideo", "-pix_fmt", "gray", "-"]


def _read_native_anchor(path: Path, transform: str, index: int, width: int, height: int):
    command = _native_command(path, f"{transform},select=eq(n\\,{index}),format=gray")
    # Stop after the selected frame. The selected source is never re-encoded.
    command[-1:-1] = ["-frames:v", "1"]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode or len(result.stdout) != width * height:
        raise base.PilotError("native source anchor decode failed or spatial shape mismatched")
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(height, width)


def _native_frames(path: Path, width: int, height: int):
    if type(width) is not int or type(height) is not int or min(width, height) <= 0:
        raise ValueError("native decoded frame dimensions must be positive integers")
    # FFmpeg can emit more stderr than a pipe can hold before yielding any raw
    # picture. A temporary sink avoids blocking its stdout producer; retain only
    # a bounded diagnostic tail in the resulting exception.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(_native_command(path, "format=gray"), stdout=subprocess.PIPE,
                                   stderr=errors)
        frame_bytes = width * height
        try:
            assert process.stdout is not None
            while True:
                data = bytearray()
                while len(data) < frame_bytes:
                    chunk = process.stdout.read(frame_bytes - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
                if not data:
                    break
                if len(data) != frame_bytes:
                    raise base.PilotError("incomplete native decoded ROI frame")
                yield np.frombuffer(data, dtype=np.uint8).reshape(height, width)
            if process.wait() != 0:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 4096))
                tail = errors.read().decode(errors="replace")
                raise base.PilotError("native ROI frame decode failed: " + tail)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdout is not None:
                process.stdout.close()


def analyze_project_anchor(project_root: Path, video_id: str, anchor_index: int, *, tile_size: int = 16) -> dict:
    """Read-only development anchor evidence, without writing files or statuses."""
    root = Path(project_root).resolve()
    rows, roi_rows, _, input_hashes = base.load_inputs(root)
    if video_id not in rows:
        raise base.PilotError("analysis requires a development ID")
    if video_id in aligned.HELD_IDS:
        raise base.PilotError("special_video_reserved_for_later_discussion")
    roi = roi_rows[video_id]
    source_path = root / "data/videos" / (video_id + ".mp4")
    roi_path = root / "data/roi/videos" / (video_id + ".mp4")
    source_sha, roi_sha = base.sha256_file(source_path), base.sha256_file(roi_path)
    if (source_sha != roi["source"]["sha256"] or roi_sha != roi["output"]["sha256"]
        or roi.get("decision", {}).get("source_sha256") != source_sha):
        raise base.PilotError("analysis source/ROI/decision identity mismatch")
    media = aligned.probe_video(roi_path)
    if type(anchor_index) is not int or not 0 <= anchor_index < media["total_frames"]:
        raise base.PilotError("anchor outside decoded ROI sequence")
    transform = aligned.source_roi_filter(roi)
    width, height = media["width"], media["height"]
    expected = _read_native_anchor(source_path, transform, anchor_index, width, height)
    coarse_source = aligned._features(source_path, f"{transform},select=eq(n\\,{anchor_index})")
    coarse_roi = aligned._features(roi_path)
    if len(coarse_source) != 1 or len(coarse_roi) != media["total_frames"]:
        raise base.PilotError("coarse/native decoded frame coverage mismatch")
    with closing(_native_frames(roi_path, width, height)) as frames:
        result = _analyze_frames(expected, frames, anchor_index,
                                 tile_size=tile_size, coarse_expected_anchor=coarse_source[0],
                                 coarse_actual_frames=coarse_roi,
                                 coarse_implementation="existing_aligned_ffmpeg_64px_features")
    if result["searched_frame_count"] != media["total_frames"]:
        raise base.PilotError("native/PTS decoded frame coverage mismatch")
    if base.sha256_file(source_path) != source_sha or base.sha256_file(roi_path) != roi_sha:
        raise base.PilotError("analysis media changed during read")
    for relative, expected_hash in input_hashes.items():
        if base.sha256_file(root / relative) != expected_hash:
            raise base.PilotError("analysis metadata changed during read")
    result["identity"] = {"video_id": video_id, "source_sha256": source_sha,
                          "roi_sha256": roi_sha, "inputs": input_hashes,
                          "analysis_code_sha256": base.sha256_file(Path(__file__)),
                          "aligned_code_sha256": base.sha256_file(Path(aligned.__file__)),
                          "source_frame_index_is_a_claim_not_a_verified_mapping": True,
                          "source_ROI_effective_transform": transform}
    return result
