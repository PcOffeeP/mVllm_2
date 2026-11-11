"""Strict, independently reproducible frame-preserving media evidence.

No similarity threshold is relaxed. Source replay accepts only the recorded
static spatial pipeline under FFmpeg/FFprobe 4.4.2, exact existing ROI bytes and
complete decoded RGB/PTS equality. Clip replay uses absolute `select` indices
independently from production `trim`, with annotation/guard checks and exact bytes.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from script.subvideo_pilot import pilot as base
from script.sub_video import anchors as anchor_records

SOURCE_SCHEMA = "tensile-sub-video-source-replay/2"
CLIP_SCHEMA = "tensile-sub-video-clip-replay/2"
VERIFIED = "verified_frame_preserving_replay"


class ReplayUncertain(base.SkipSource):
    def __init__(self, reason: str, details: dict | None = None):
        super().__init__(reason)
        self.details = details or {}


def _digest(value) -> str:
    return hashlib.sha256(base.canonical_bytes(value)).hexdigest()


def _code() -> dict:
    package = Path(__file__).resolve().parent
    paths = sorted(package.glob("*.py")) + sorted((package.parent / "subvideo_pilot").glob("*.py"))
    return {str(p.relative_to(package.parent)): base.sha256_file(p) for p in paths}


def _checked(command: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode or result.stderr.strip():
        raise ReplayUncertain("replay_command_failed", {"command": command, "returncode": result.returncode,
                                                       "stderr_tail": result.stderr[-4096:]})
    return result


def _toolchain() -> dict:
    result = {}
    for name in ("ffmpeg", "ffprobe"):
        executable = shutil.which(name)
        if not executable:
            raise ReplayUncertain("replay_tool_missing:" + name)
        version = subprocess.run([executable, "-version"], capture_output=True, text=True, check=False)
        line = version.stdout.splitlines()[0] if version.stdout else ""
        if version.returncode or not re.match(rf"^{name} version 4\.4\.2(?:[-\s]|$)", line):
            raise ReplayUncertain("replay_requires_verified_ffmpeg_ffprobe_4_4_2", {"tool": name, "version": line})
        result[name] = {"path": str(Path(executable).resolve()), "version": version.stdout,
                        "binary_sha256": base.sha256_file(Path(executable).resolve())}
    return result


def _stream_info(path: Path) -> dict:
    command = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    try:
        data = json.loads(_checked(command).stdout)
        videos = [s for s in data["streams"] if s.get("codec_type") == "video"]
        if len(videos) != 1 or videos[0].get("disposition", {}).get("attached_pic", 0):
            raise ReplayUncertain("replay_requires_one_non_cover_video_stream")
        stream = videos[0]
        rotations = [stream.get("tags", {}).get("rotate", 0)]
        for side in stream.get("side_data_list", []):
            if "rotation" in side:
                rotations.append(side["rotation"])
            elif "display matrix" in str(side.get("side_data_type", "")).lower():
                raise ReplayUncertain("replay_display_matrix_rotation_unreadable")
        if any(not math.isfinite(float(v)) or float(v) % 360 for v in rotations):
            raise ReplayUncertain("replay_requires_zero_rotation")
        width, height = int(stream["width"]), int(stream["height"])
        if min(width, height) <= 0:
            raise ValueError
        duration = float(stream.get("duration") or data["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return {"stream_index": int(stream["index"]), "width": width, "height": height,
                "pixel_format": stream["pix_fmt"], "time_base": stream["time_base"],
                "duration": duration, "rotation": 0, "stream_selection": "0:v:0",
                "metadata_frame_count": (int(stream["nb_frames"]) if stream.get("nb_frames") not in (None, "N/A") else None)}
    except ReplayUncertain:
        raise
    except (KeyError, ValueError, TypeError) as exc:
        raise ReplayUncertain("replay_stream_metadata_invalid") from exc


def _decode_rgb(path: Path, info: dict) -> dict:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-err_detect", "explode",
               "-noautorotate", "-i", str(path), "-map", "0:v:0", "-vsync", "0", "-enc_time_base", "-1",
               "-c:v", "rawvideo", "-pix_fmt", "rgb24", "-f", "framehash", "-hash", "sha256", "-"]
    text = _checked(command).stdout
    time_base = None
    rows = []
    for line in text.splitlines():
        if line.startswith("#tb 0:"):
            time_base = Fraction(line.split(":", 1)[1].strip())
        elif line and not line.startswith("#"):
            fields = [x.strip() for x in line.split(",")]
            if len(fields) != 6 or fields[0] != "0" or not re.fullmatch(r"[0-9a-f]{64}", fields[5]):
                raise ReplayUncertain("replay_complete_framehash_parse_failed")
            try:
                dts, pts, duration, size = map(int, fields[1:5])
            except ValueError as exc:
                raise ReplayUncertain("replay_complete_framehash_parse_failed") from exc
            if size != info["width"] * info["height"] * 3 or duration <= 0:
                raise ReplayUncertain("replay_decoded_RGB_size_or_duration_invalid")
            rows.append({"dts": dts, "pts": pts, "duration": duration, "size": size, "sha256": fields[5]})
    if time_base is None or time_base <= 0 or len(rows) < 2:
        raise ReplayUncertain("replay_incomplete_RGB_decode")
    if info.get("metadata_frame_count") is not None and len(rows) != info["metadata_frame_count"]:
        raise ReplayUncertain("replay_decoded_metadata_frame_count_mismatch")
    times = [Fraction(row["pts"]) * time_base for row in rows]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ReplayUncertain("replay_non_monotonic_decoded_PTS")
    normalized = [t - times[0] for t in times]
    decoded_end = normalized[-1] + rows[-1]["duration"] * time_base
    usable_end = min(Fraction(str(info["duration"])), decoded_end)
    return {"command": command, "frame_count": len(rows), "time_base": str(time_base),
            "frames": rows, "normalized_pts": [str(t) for t in normalized],
            "usable_end": str(usable_end), "frame_sequence_sha256": _digest(rows)}


def _grid(pixel_format: str) -> tuple[int, int]:
    match = re.fullmatch(r"(?:yuv|yuva|yuvj)(420|422|444|411|410)p(?:\d+(?:le|be))?", pixel_format)
    if match:
        return {"420": (2, 2), "422": (2, 1), "444": (1, 1), "411": (4, 1), "410": (4, 4)}[match[1]]
    if pixel_format in {"gray", "gray8", "rgb24", "bgr24", "rgba", "bgra", "gbrp"}:
        return 1, 1
    raise ReplayUncertain("replay_source_chroma_grid_unknown")


def source_command(source: Path, reference: Path, roi_record: dict, source_info: dict) -> list[str]:
    """Validate the exact recorded static filter, preserving its original bytes."""
    encoding = roi_record.get("output", {}).get("encoding", {})
    required = {"video_codec": "libx264", "preset": "fast", "crf": 23,
                "pixel_format": "yuv420p", "audio": "dropped", "frame_sync": "vsync_0_passthrough"}
    if any(encoding.get(k) != v for k, v in required.items()):
        raise ReplayUncertain("replay_encoding_profile_not_verified")
    geometry = roi_record.get("output", {}).get("geometry", {})
    video_filter = geometry.get("filter", "")
    crop = re.fullmatch(r"crop=(\d+):(\d+):(\d+):(\d+)(:exact=1)?,setsar=1", video_filter)
    pad = re.fullmatch(r"pad=(\d+):(\d+):(\d+):(\d+):color=black,setsar=1", video_filter)
    if not crop and not pad:
        raise ReplayUncertain("replay_filter_not_static_spatial_whitelist")
    decision = roi_record.get("decision", {})
    if decision.get("source_resolution") != [source_info["width"], source_info["height"]]:
        raise ReplayUncertain("replay_decision_source_dimensions_mismatch")
    gx, gy = _grid(source_info["pixel_format"])
    if crop:
        w, h, x, y = map(int, crop.groups()[:4])
        if decision.get("mode") != "fixed_roi" or decision.get("pixel_box") != {"x": x, "y": y, "width": w, "height": h}:
            raise ReplayUncertain("replay_filter_differs_from_bound_decision")
        if min(w, h) <= 0 or x + w > source_info["width"] or y + h > source_info["height"]:
            raise ReplayUncertain("replay_crop_outside_source")
        if crop.group(5):
            gx = gy = 1
        w, h, x, y = w // gx * gx, h // gy * gy, x // gx * gx, y // gy * gy
        effective = {"x": x, "y": y, "width": w, "height": h}
        pads = dict.fromkeys(("left", "right", "top", "bottom"), 0)
    else:
        w, h, x, y = map(int, pad.groups())
        if decision.get("mode") != "no_crop":
            raise ReplayUncertain("replay_pad_differs_from_bound_decision")
        x, y = x // gx * gx, y // gy * gy
        if x + source_info["width"] > w or y + source_info["height"] > h:
            raise ReplayUncertain("replay_pad_cannot_contain_source")
        effective = {"x": 0, "y": 0, "width": source_info["width"], "height": source_info["height"]}
        pads = {"left": x, "right": w - x - source_info["width"],
                "top": y, "bottom": h - y - source_info["height"]}
    if (geometry.get("effective_pixel_box") != effective or geometry.get("pad_pixels") != pads
        or geometry.get("output_resolution") != [w, h]):
        raise ReplayUncertain("replay_effective_geometry_not_verified")
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source),
            "-map", "0:v:0", "-vf", video_filter, "-vsync", "0", "-c:v", "libx264", "-preset", "fast",
            "-crf", "23", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(reference)]


def _seal(receipt: dict) -> dict:
    return dict(receipt, receipt_sha256=_digest(receipt))


def _compact_decode(decoded: dict) -> dict:
    # Whole sequences are compared in memory; persistent receipts retain their
    # ordered digest plus the real PTS needed for independent window validation.
    return {key: value for key, value in decoded.items() if key != "frames"}


def _validate_phenomenon_anchor(anchor: dict | None, annotation: dict | None, source_sha: str, count: int) -> dict | None:
    if annotation is None or annotation.get("异常_未夹紧") != "是":
        if anchor is not None:
            raise ReplayUncertain("phenomenon_anchor_requires_unclamped_source")
        return None
    try:
        if not isinstance(anchor, dict):
            raise ValueError
        path = Path(anchor["document_path"])
        if not path.is_absolute() or base.sha256_file(path) != anchor.get("document_sha256"):
            raise ValueError
        expected = anchor_records.load_anchors(path).get(annotation["id"])
        if (anchor != expected or anchor["source_sha256"] != source_sha
            or type(anchor["source_frame"]) is not int or not 0 <= anchor["source_frame"] < count):
            raise ValueError
        return dict(anchor)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ReplayUncertain("unclamped_phenomenon_anchor_not_bound_to_current_source_and_document") from exc


def verify_source_replay(source_path: Path, roi_path: Path, roi_record: dict, *, source_annotation: dict | None = None,
                         phenomenon_anchor: dict | None = None) -> dict:
    source_path, roi_path = Path(source_path).resolve(), Path(roi_path).resolve()
    roi_record = json.loads(base.canonical_bytes(roi_record))
    source_annotation = json.loads(base.canonical_bytes(source_annotation)) if source_annotation is not None else None
    phenomenon_anchor = json.loads(base.canonical_bytes(phenomenon_anchor)) if phenomenon_anchor is not None else None
    toolchain, code = _toolchain(), _code()
    source_sha, roi_sha = base.sha256_file(source_path), base.sha256_file(roi_path)
    decision_hash = _digest(roi_record.get("decision", {}))
    if (roi_record.get("decision", {}).get("source_video_id", roi_record.get("video_id")) != roi_record.get("video_id")
        or (source_annotation is not None and source_annotation.get("id") != roi_record.get("video_id"))):
        raise ReplayUncertain("replay_bound_source_ID_mismatch")
    if (source_sha != roi_record.get("source", {}).get("sha256")
        or roi_sha != roi_record.get("output", {}).get("sha256")
        or roi_record.get("decision", {}).get("source_sha256") != source_sha):
        raise ReplayUncertain("replay_source_ROI_decision_identity_mismatch")
    source_info, roi_info = _stream_info(source_path), _stream_info(roi_path)
    source_decode = _decode_rgb(source_path, source_info)
    roi_decode = _decode_rgb(roi_path, roi_info)
    bound_anchor = _validate_phenomenon_anchor(phenomenon_anchor, source_annotation, source_sha, source_decode["frame_count"])
    with tempfile.TemporaryDirectory(prefix="tensile-source-replay-") as temporary:
        reference = Path(temporary) / "reference.mp4"
        command = source_command(source_path, reference, roi_record, source_info)
        _checked(command)
        reference_sha = base.sha256_file(reference)
        if reference_sha != roi_sha:
            raise ReplayUncertain("source_replay_exact_file_SHA_mismatch", {"reference_sha256": reference_sha, "ROI_sha256": roi_sha})
        reference_info = _stream_info(reference)
        reference_decode = _decode_rgb(reference, reference_info)
        if (source_decode["frame_count"] != roi_decode["frame_count"]
            or roi_decode["frame_count"] != reference_decode["frame_count"]
            or reference_info != roi_info
            or reference_decode["time_base"] != roi_decode["time_base"]
            or reference_decode["frames"] != roi_decode["frames"]):
            raise ReplayUncertain("source_replay_full_RGB_PTS_sequence_mismatch")
    if (base.sha256_file(source_path) != source_sha or base.sha256_file(roi_path) != roi_sha
        or _digest(roi_record.get("decision", {})) != decision_hash or _toolchain() != toolchain or _code() != code):
        raise ReplayUncertain("source_replay_identity_changed_during_check")
    if _validate_phenomenon_anchor(bound_anchor, source_annotation, source_sha, source_decode["frame_count"]) != bound_anchor:
        raise ReplayUncertain("phenomenon_anchor_changed_during_source_replay")
    return _seal({"schema": SOURCE_SCHEMA, "status": VERIFIED, "proof_type": "exact_static_spatial_pipeline_replay",
                  "source_path": str(source_path), "roi_path": str(roi_path),
                  "source_sha256": source_sha, "roi_sha256": roi_sha, "decision_sha256": decision_hash,
                  "roi_record_sha256": _digest(roi_record),
                  "video_id": roi_record.get("video_id"), "toolchain": toolchain, "code": code,
                  "command": command, "reference_sha256": reference_sha,
                  "source_info": source_info, "roi_info": roi_info,
                  "source_decode": _compact_decode(source_decode), "roi_decode": _compact_decode(roi_decode),
                  "reference_RGB_PTS_sequence_sha256": reference_decode["frame_sequence_sha256"],
                  "source_annotation": source_annotation,
                  "source_annotation_sha256": _digest(source_annotation) if source_annotation is not None else None,
                  "phenomenon_anchor": bound_anchor,
                  "phenomenon_anchor_sha256": _digest(bound_anchor) if bound_anchor is not None else None,
                  "mapping": "source_frame_i_to_ROI_frame_i_by_verified_frame_preserving_pipeline",
                  "limitations": ["not_visual_uniqueness", "not_human_review", "not_final_label_validation"]})


def clip_reference_command(roi: Path, reference: Path, start: int, end: int) -> list[str]:
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise ReplayUncertain("clip_replay_invalid_absolute_frame_range")
    video_filter = f"select=between(n\\,{start}\\,{end-1}),setpts=PTS-STARTPTS"
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-noautorotate", "-i", str(roi),
            "-map", "0:v:0", "-vf", video_filter, "-vsync", "0", "-enc_time_base", "-1", "-threads", "2",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-an",
            "-movflags", "+faststart", str(reference)]


def _annotation_bounds(annotation: dict, source_decode: dict, phenomenon_anchor: dict | None = None) -> tuple[str, list[int]]:
    count = source_decode["frame_count"]
    def frame(value):
        try:
            number = float(value)
            if not math.isfinite(number) or number != int(number) or not 0 <= number < count:
                raise ValueError
            return int(number)
        except (ValueError, TypeError):
            return None
    # Temporal observations are independent of mode, location and anomaly labels.
    if annotation.get("异常_未夹紧") == "是":
        value = phenomenon_anchor.get("source_frame") if isinstance(phenomenon_anchor, dict) else None
        if type(value) is not int or not 0 <= value < count:
            raise ReplayUncertain("unclamped_phenomenon_anchor_missing_or_invalid")
        return "unclamped", [value]
    before, after = frame(annotation.get("断裂帧_前")), frame(annotation.get("断裂帧_后"))
    has_range = any(annotation.get(k) not in (None, "", "无") for k in ("断裂时间范围_下界", "断裂时间范围_上界"))
    has_point = annotation.get("断裂时间点") not in (None, "", "无")
    has_frames = any(annotation.get(k) not in (None, "", "无") for k in ("断裂帧_前", "断裂帧_后"))
    if annotation.get("断裂状态") == "未断裂" and (has_range or has_point or has_frames):
        raise ReplayUncertain("clip_replay_negative_annotation_conflict")
    if before is None and after is None and not has_range and not has_point:
        if has_frames:
            raise ReplayUncertain("clip_replay_invalid_annotated_frames")
        if annotation.get("异常_视频异常") == "是" or annotation.get("断裂状态") != "未断裂":
            raise ReplayUncertain("clip_replay_no_usable_event_or_negative_annotation")
        return "none", []
    if before is not None and after is not None:
        if after != before + 1:
            raise ReplayUncertain("clip_replay_precise_event_frames_not_adjacent")
        return "exact", [before, after]
    try:
        fps = float(annotation["视频帧率"])
        values = [float(annotation[k]) * fps for k in ("断裂时间范围_下界", "断裂时间范围_上界")]
        indices = [round(v) for v in values]
        if (not math.isfinite(fps) or fps <= 0 or any(not math.isfinite(v) for v in values)
            or any(abs(v-i) > .001 for v, i in zip(values, indices))
            or not 0 <= indices[0] < indices[1] < count):
            raise ValueError
        return "range", indices
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        raise ReplayUncertain("clip_replay_range_annotation_not_recoverable") from exc


def _validate_window(candidate: dict, source_proof: dict) -> dict:
    annotation = source_proof.get("source_annotation")
    if not isinstance(annotation, dict) or _digest(annotation) != source_proof.get("source_annotation_sha256"):
        raise ReplayUncertain("clip_replay_requires_bound_current_annotation")
    if annotation.get("id") != candidate.get("source_video_id") or annotation.get("id") != source_proof.get("video_id"):
        raise ReplayUncertain("clip_replay_annotation_source_ID_mismatch")
    phenomenon_anchor = source_proof.get("phenomenon_anchor")
    if phenomenon_anchor is not None:
        if _digest(phenomenon_anchor) != source_proof.get("phenomenon_anchor_sha256"):
            raise ReplayUncertain("clip_replay_phenomenon_anchor_identity_mismatch")
    _validate_phenomenon_anchor(phenomenon_anchor, annotation, source_proof["source_sha256"], source_proof["source_decode"]["frame_count"])
    kind, anchors = _annotation_bounds(annotation, source_proof["source_decode"], phenomenon_anchor)
    start, end = candidate.get("start_frame"), candidate.get("end_frame")
    count = source_proof["source_decode"]["frame_count"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= count:
        raise ReplayUncertain("clip_replay_invalid_absolute_frame_range")
    if candidate.get("source_frame_range") != [start, end] or candidate.get("source_anchor_frames") != anchors or candidate.get("event_kind") != kind:
        raise ReplayUncertain("clip_replay_recorded_frame_binding_mismatch")
    source_pts = [Fraction(t) for t in source_proof["source_decode"]["normalized_pts"]]
    usable_end = Fraction(source_proof["source_decode"]["usable_end"])
    end_pts = source_pts[end] if end < count else usable_end
    quantization = max(Fraction(1, 1000000), Fraction(source_proof["source_decode"]["time_base"]))
    derived_times = {"source_start_pts": source_pts[start], "start_time": source_pts[start],
                     "source_end_pts": end_pts, "end_time": end_pts,
                     "source_duration": end_pts - source_pts[start], "duration": end_pts - source_pts[start]}
    for name, expected in derived_times.items():
        if name in candidate:
            try:
                if abs(Fraction(str(candidate[name])) - expected) > quantization:
                    raise ValueError
            except (ValueError, TypeError, ZeroDivisionError) as exc:
                raise ReplayUncertain("clip_replay_recorded_source_time_mapping_mismatch") from exc
    role = candidate.get("window_role")
    epsilon = Fraction(1, 1000000000)
    if end_pts - source_pts[start] < 1 - epsilon:
        raise ReplayUncertain("clip_replay_window_shorter_than_existing_one_second_minimum")
    if kind == "unclamped":
        if role != "unclamped" or candidate.get("phenomenon_anchor") != phenomenon_anchor:
            raise ReplayUncertain("clip_replay_unclamped_role_or_anchor_binding_mismatch")
        event = anchors[0]
        try:
            target = Fraction(str(candidate["target_duration_seconds"]))
            if target not in (2, 3, 5, 10, 20) or usable_end < target - epsilon:
                raise ValueError
            ideal_start = source_pts[event] - target / 2
            desired_start = max(Fraction(0), min(ideal_start, usable_end - target))
            desired_end = desired_start + target
            boundaries = source_pts + [usable_end]
            start_distance = min(abs(t-desired_start) for t in boundaries)
            end_distance = min(abs(t-desired_end) for t in boundaries)
            if (not start <= event < end
                or abs(source_pts[start]-desired_start) > start_distance + quantization
                or abs(end_pts-desired_end) > end_distance + quantization):
                raise ValueError
            shifted = ideal_start != desired_start
            if candidate.get("position_policy") != ("shift_to_source_boundary" if shifted else "centered"):
                raise ValueError
            expected_ratio = (source_pts[event]-source_pts[start])/(end_pts-source_pts[start])
            if abs(Fraction(str(candidate["event_position_ratio"]))-expected_ratio) > Fraction(1, 1000000):
                raise ValueError
        except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
            raise ReplayUncertain("clip_replay_unclamped_window_not_centered_or_boundary_shifted") from exc
    elif kind == "none":
        if role != "stable_negative":
            raise ReplayUncertain("clip_replay_negative_role_mismatch")
    else:
        lower, upper = anchors
        lower_guard = upper if kind == "exact" else lower
        if role == "pre_event":
            if end_pts > source_pts[lower_guard] - Fraction(1, 2) + epsilon:
                raise ReplayUncertain("clip_replay_pre_window_crosses_annotation_guard")
        elif role == "post_event":
            if (source_pts[start] < source_pts[upper] + Fraction(1, 2) - epsilon
                or usable_end - source_pts[upper] - Fraction(1, 2) < 2 - epsilon):
                raise ReplayUncertain("clip_replay_post_guard_or_remaining_material_failed")
        elif role == "transition":
            if not ((start < upper < end) if kind == "exact" else (start <= lower and end > upper)):
                raise ReplayUncertain("clip_replay_transition_does_not_cover_annotation_bounds")
        else:
            raise ReplayUncertain("clip_replay_unknown_window_role")
    return {"annotation_sha256": source_proof["source_annotation_sha256"], "event_kind": kind,
            "phenomenon_anchor_sha256": source_proof.get("phenomenon_anchor_sha256"),
            "source_anchor_frames": anchors, "source_frame_range": [start, end],
            "guard_seconds": None if kind == "unclamped" else .5,
            "post_remaining_seconds": None if kind == "unclamped" else 2.0, "source_start_pts": str(source_pts[start]),
            "source_end_pts": str(end_pts)}


def validate_source_receipt(source_proof: dict, roi_path: Path, candidate: dict) -> dict:
    """Recheck live media/code/annotation pins before any clip encoding."""
    roi_path = Path(roi_path).resolve()
    if not isinstance(source_proof, dict):
        raise ReplayUncertain("clip_replay_source_receipt_not_current_or_complete")
    receipt = dict(source_proof)
    receipt_hash = receipt.pop("receipt_sha256", None)
    if (source_proof.get("schema") != SOURCE_SCHEMA or source_proof.get("status") != VERIFIED
        or receipt_hash != _digest(receipt) or source_proof.get("code") != _code()
        or source_proof.get("toolchain") != _toolchain()):
        raise ReplayUncertain("clip_replay_source_receipt_not_current_or_complete")
    source_path = Path(source_proof["source_path"])
    source_sha, roi_sha = source_proof["source_sha256"], source_proof["roi_sha256"]
    if (candidate.get("source_sha256") != source_sha or candidate.get("roi_sha256") != roi_sha
        or base.sha256_file(source_path) != source_sha or base.sha256_file(roi_path) != roi_sha):
        raise ReplayUncertain("clip_replay_input_identity_mismatch")
    return _validate_window(candidate, source_proof)


def verify_clip_replay(roi_path: Path, output_path: Path, candidate: dict, roi_media: dict, source_proof: dict) -> dict:
    roi_path, output_path = Path(roi_path).resolve(), Path(output_path).resolve()
    candidate_hash = _digest(candidate)
    window = validate_source_receipt(source_proof, roi_path, candidate)
    receipt_hash = source_proof["receipt_sha256"]
    source_path = Path(source_proof["source_path"])
    source_sha, roi_sha = source_proof["source_sha256"], source_proof["roi_sha256"]
    start, end = window["source_frame_range"]
    actual_info = _stream_info(output_path)
    actual_decode = _decode_rgb(output_path, actual_info)
    actual_sha = base.sha256_file(output_path)
    with tempfile.TemporaryDirectory(prefix="tensile-clip-replay-") as temporary:
        reference = Path(temporary) / "reference.mp4"
        command = clip_reference_command(roi_path, reference, start, end)
        _checked(command)
        if base.sha256_file(reference) != actual_sha:
            raise ReplayUncertain("clip_replay_exact_file_SHA_mismatch")
        ref_info = _stream_info(reference)
        ref_decode = _decode_rgb(reference, ref_info)
        expected_roi_pts = [Fraction(t) for t in source_proof["roi_decode"]["normalized_pts"]][start:end]
        expected_roi_pts = [t - expected_roi_pts[0] for t in expected_roi_pts]
        actual_pts = [Fraction(t) for t in actual_decode["normalized_pts"]]
        if (actual_info != ref_info or actual_decode["frame_count"] != end - start
            or actual_decode["time_base"] != ref_decode["time_base"]
            or actual_decode["frames"] != ref_decode["frames"] or actual_pts != expected_roi_pts
            or [actual_info["width"], actual_info["height"]] != [roi_media["width"], roi_media["height"]]):
            raise ReplayUncertain("clip_replay_complete_RGB_PTS_or_frame_count_mismatch")
    if (base.sha256_file(source_path) != source_sha or base.sha256_file(roi_path) != roi_sha
        or base.sha256_file(output_path) != actual_sha or source_proof.get("toolchain") != _toolchain()
        or source_proof.get("code") != _code() or _digest(candidate) != candidate_hash
        or _digest({k: v for k, v in source_proof.items() if k != "receipt_sha256"}) != receipt_hash):
        raise ReplayUncertain("clip_replay_identity_changed_during_check")
    _validate_phenomenon_anchor(source_proof.get("phenomenon_anchor"), source_proof.get("source_annotation"),
                               source_sha, source_proof["source_decode"]["frame_count"])
    return _seal({"schema": CLIP_SCHEMA, "status": VERIFIED,
                  "proof_type": "independent_absolute_select_replay_of_trim_output",
                  "source_receipt_sha256": receipt_hash, "source_sha256": source_sha, "roi_sha256": roi_sha,
                  "output_sha256": actual_sha, "toolchain": source_proof["toolchain"], "code": source_proof["code"],
                  "command": command, "window": window, "decoded_frame_count": actual_decode["frame_count"],
                  "decoded_RGB_PTS_sequence_sha256": actual_decode["frame_sequence_sha256"],
                  "anchors": [{"source_frame": i, "roi_frame": i, "output_frame": i-start}
                              for i in window["source_anchor_frames"] if start <= i < end],
                  "limitations": ["not_visual_uniqueness", "not_human_review", "not_final_label_validation"]})
