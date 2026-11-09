#!/usr/bin/env python3
"""Development-only cuts with decoded-frame correspondence and real PTS mappings."""
from __future__ import annotations

import argparse
import bisect
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
from typing import Any

try:
    from . import geometry, pilot as base
except ImportError:
    import geometry
    import pilot as base

SCHEMA = "tensile-frame-aligned-subvideo-cut/1"
HELD_IDS = frozenset({"video_0002", "video_0015", "video_0050"})
GUARD_SECONDS = 0.5
POST_REMAINING_SECONDS = 2.0
FEATURE_SIZE = 64
# Conservative compression tolerances. Passing these checks is machine evidence,
# not a substitute for final human clip review; ambiguous anchors remain pending.
MAX_MEAN_PIXEL_ERROR = 5.0
MIN_ANCHOR_MARGIN = 0.15


class AlignmentUncertain(base.SkipSource):
    def __init__(self, reason: str, details: dict | None = None):
        super().__init__(reason)
        self.details = details or {}


def probe_video(path: Path) -> dict:
    """Read actual decoded presentation timestamps; do not impose a CFR grid."""
    data = json.loads(base._checked([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
        "-show_format", "-show_frames", "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,duration,time_base:"
        "stream_tags=rotate:stream_side_data=rotation:format=duration:"
        "frame=best_effort_timestamp_time,pkt_duration_time", "-of", "json", str(path),
    ]).stdout)
    try:
        if len(data["streams"]) != 1:
            raise ValueError("one video stream required")
        stream = data["streams"][0]
        rate = Fraction(stream["r_frame_rate"])
        times = [float(f["best_effort_timestamp_time"]) for f in data["frames"]]
        if rate <= 0 or len(times) < 2 or not all(math.isfinite(t) for t in times):
            raise ValueError("invalid frame timestamps")
        if any(b <= a for a, b in zip(times, times[1:])):
            raise AlignmentUncertain("missing_or_non_increasing_frame_timestamps")
        rotation = float(stream.get("tags", {}).get("rotate", 0))
        for side in stream.get("side_data_list", []):
            if "rotation" in side:
                rotation = float(side["rotation"])
        if rotation % 360:
            raise AlignmentUncertain("unsupported_rotation_for_frame_correspondence")
        origin = times[0]
        timestamps = [t - origin for t in times]
        last_duration = base._number(data["frames"][-1].get("pkt_duration_time"))
        # The final PTS itself is a conservative usable endpoint if its duration
        # is unavailable; never invent extra post-event material from nominal FPS.
        decoded_end = timestamps[-1] + (last_duration if last_duration and last_duration > 0 else 0)
        reported = base._number(stream.get("duration") or data.get("format", {}).get("duration"))
        usable_end = min(decoded_end, reported) if reported and reported > 0 else decoded_end
        return {"width": int(stream["width"]), "height": int(stream["height"]),
                "fps": float(rate), "nominal_frame_rate": str(rate), "total_frames": len(times),
                "time_base": stream.get("time_base", "1/1000000"),
                "duration": usable_end, "reported_duration": reported,
                "timestamp_origin": origin, "timestamps": timestamps,
                "timestamp_sha256": hashlib.sha256(base.canonical_bytes(timestamps)).hexdigest(),
                "timestamp_validation": "decoded_monotonic_pts_no_constant_rate_grid",
                "final_frame_duration": last_duration, "rotation": rotation % 360}
    except AlignmentUncertain:
        raise
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise AlignmentUncertain("unusable_video_metadata_or_timestamps") from exc


def _integer_frame(value: Any, total: int) -> int | None:
    number = base._number(value)
    if number is None or number != int(number) or not 0 <= number < total:
        return None
    return int(number)


def _range_frame(seconds: Any, label_fps: Any, total: int) -> int:
    value, rate = base._number(seconds), base._number(label_fps)
    if value is None or rate is None or rate <= 0:
        raise AlignmentUncertain("range_boundary_requires_recorded_annotation_fps")
    raw = value * rate
    frame = round(raw)
    # CSV decimal roundoff only, not a temporal matching tolerance.
    if abs(raw - frame) > 0.001 or not 0 <= frame < total:
        raise AlignmentUncertain("range_boundary_not_recoverable_as_source_frame")
    return frame


def adapt_annotation(row: dict, media: dict) -> dict:
    """Keep exact source frame anchors; range seconds recover recorded source frames."""
    if row.get("id") in HELD_IDS:
        raise AlignmentUncertain("special_video_reserved_for_later_discussion")
    for name in ("异常_未夹紧", "异常_视频异常", "异常_爆炸性断裂"):
        if row.get(name) not in {"是", "否"}:
            raise AlignmentUncertain("uncertain_anomaly_annotation:" + name)
    if row["异常_未夹紧"] == "是":
        raise AlignmentUncertain("unclamped_requires_separate_rule")
    if row["异常_视频异常"] == "是":
        raise AlignmentUncertain("video_abnormal")
    state = row.get("断裂状态")
    if state not in {"发生断裂", "未断裂"}:
        raise AlignmentUncertain("unsupported_or_uncertain_source_state")
    record = {"video_id": row["id"], "fps": media["fps"],
              "total_frames": media["total_frames"],
              # Old geometry selects frame intervals on this explicitly virtual
              # frame-index axis. All guards and final durations use actual PTS.
              "duration": media["total_frames"] / media["fps"],
              "has_fracture_canonical": state == "发生断裂",
              "is_abnormal_canonical": False, "location_canonical": None}
    if state == "未断裂":
        if any(row.get(f) not in {"无", ""} for f in ("断裂时间点", "断裂帧_前", "断裂帧_后")):
            raise AlignmentUncertain("negative_source_has_event_evidence_conflict")
        if row["异常_爆炸性断裂"] != "否":
            raise AlignmentUncertain("negative_source_has_explosive_conflict")
        return dict(record, type="未断裂", event_kind="none", event_time=None, event_time_reliable=False,
                    anchor_frames=[])
    mechanism = row.get("断裂模式")
    if not geometry.map_legacy_fracture_type(mechanism).matched:
        raise AlignmentUncertain("fracture_mechanism_not_supported_by_window_geometry")
    if row["异常_爆炸性断裂"] == "是" and mechanism != "爆炸性断裂":
        raise AlignmentUncertain("explosive_annotation_requires_new_rule")
    total = media["total_frames"]
    before = _integer_frame(row.get("断裂帧_前"), total)
    after = _integer_frame(row.get("断裂帧_后"), total)
    if before is not None and after is not None:
        if after != before + 1:
            raise AlignmentUncertain("non_adjacent_precise_event_frames")
        return dict(record, type=mechanism, event_kind="exact", event_frame=after,
                    lower_frame=before, upper_frame=after, anchor_frames=[before, after],
                    event_time=after / media["fps"], event_time_reliable=True,
                    annotation_event_time=row.get("断裂时间点"),
                    source_event_pts=media["timestamps"][after])
    lower = _range_frame(row.get("断裂时间范围_下界"), row.get("视频帧率"), total)
    upper = _range_frame(row.get("断裂时间范围_上界"), row.get("视频帧率"), total)
    if lower >= upper:
        raise AlignmentUncertain("invalid_event_range")
    return dict(record, type=mechanism, event_kind="range", lower_frame=lower, upper_frame=upper,
                anchor_frames=[lower, upper], event_time=lower / media["fps"], event_time_reliable=True,
                annotation_range={"lower": row["断裂时间范围_下界"], "upper": row["断裂时间范围_上界"],
                                  "fps": row["视频帧率"]},
                source_event_range_pts=[media["timestamps"][lower], media["timestamps"][upper]])


def plan_windows(record: dict, source_media: dict | None = None) -> tuple[list[dict], list[dict]]:
    times = (source_media or {}).get("timestamps") or [i / record["fps"] for i in range(record["total_frames"])]
    usable_end = (source_media or {}).get("duration", record["duration"])
    def boundary(index: int) -> float:
        return times[index] if index < len(times) else usable_end
    if record["event_kind"] == "none":
        raw = geometry._raw_candidates_for_source(record, references=())
    else:
        lower, upper = record["lower_frame"], record["upper_frame"]
        # Pick pre windows relative to lower bound, post windows relative to upper;
        # transition templates remain old deterministic templates, retaining only
        # intervals that contain both observed bounds. Never manufacture a midpoint.
        geometry_lower = record["event_frame"] if record["event_kind"] == "exact" else lower
        low_record = dict(record, event_time=geometry_lower / record["fps"])
        high_record = dict(record, event_time=upper / record["fps"])
        low_windows = geometry._raw_candidates_for_source(low_record, references=())
        high_windows = geometry._raw_candidates_for_source(high_record, references=())
        raw = [w for w in low_windows if w["window_role"] in {"pre_event", "transition"}]
        raw += [w for w in high_windows if w["window_role"] == "post_event"]
        # Regenerate post partitions from the real-PTS guard boundary, rather than
        # letting a non-CFR nominal frame conversion cut before upper+0.5 seconds.
        post_index = bisect.bisect_left(times, times[upper] + GUARD_SECONDS)
        raw = [w for w in raw if w["window_role"] != "post_event"]
        for w in geometry._post_event_windows(record, post_index / record["fps"]):
            raw.append({**w, "window_role": "post_event", "target_duration_seconds": w["duration"],
                        "event_position_ratio": None, "duration_policy": "adaptive",
                        "candidate_v3_labels": geometry._candidate_labels(high_record, "已断裂")})
    accepted, excluded = [], []
    seen = set()
    for window in raw:
        start, end = window["start_frame"], window["end_frame"]
        reason = None
        if record["event_kind"] != "none":
            low, high = record["lower_frame"], record["upper_frame"]
            role = window["window_role"]
            guard_lower = record["event_frame"] if record["event_kind"] == "exact" else low
            if role == "pre_event" and boundary(end) > times[guard_lower] - GUARD_SECONDS + 1e-9:
                reason = "pre_window_crosses_lower_pts_guard"
            if role == "post_event":
                if times[start] < times[high] + GUARD_SECONDS - 1e-9:
                    reason = "post_window_crosses_upper_pts_guard"
                elif usable_end - times[high] - GUARD_SECONDS < POST_REMAINING_SECONDS - 1e-9:
                    reason = "post_source_remaining_after_upper_guard_less_than_two_seconds"
            if role == "transition":
                covers_event = (start < record["event_frame"] < end if record["event_kind"] == "exact"
                                else start <= low and end > high)
                if not covers_event:
                    reason = "transition_does_not_cover_complete_event_bounds"
        actual_duration = boundary(end) - times[start]
        if actual_duration < geometry.MIN_CANDIDATE_SECONDS - 1e-6:
            reason = reason or "actual_clip_shorter_than_existing_one_second_minimum"
        value = dict(window, geometry_time_range=[window["start_time"], window["end_time"]],
                     start_time=times[start], end_time=boundary(end), duration=actual_duration,
                     source_start_pts=times[start], source_end_pts=boundary(end),
                     source_duration=actual_duration, source_frame_range=[start, end],
                     event_kind=record["event_kind"])
        if reason:
            excluded.append(dict(value, reason=reason)); continue
        key = (start, end, value["window_role"])
        if key not in seen:
            seen.add(key); accepted.append(value)
    return accepted, excluded


def compare_sequences(expected_frames, actual_frames, anchor_indices) -> dict:
    """Check same-index picture consistency and reject ambiguous anchor matches."""
    import numpy as np
    expected = np.asarray(expected_frames)
    actual = np.asarray(actual_frames)
    if expected.shape != actual.shape or expected.ndim not in {3, 4} or len(expected) < 2:
        raise AlignmentUncertain("decoded_picture_sequence_shape_mismatch")
    expected16, actual16 = expected.astype(np.int16), actual.astype(np.int16)
    diagonal = np.abs(expected16 - actual16).reshape(len(expected), -1).mean(axis=1)
    if float(diagonal.max()) > MAX_MEAN_PIXEL_ERROR:
        raise AlignmentUncertain("same_index_picture_error_exceeds_compression_tolerance",
                                 {"worst_frame": int(diagonal.argmax()),
                                  "max_mean_pixel_error": float(diagonal.max()),
                                  "compression_tolerance": MAX_MEAN_PIXEL_ERROR})
    details = []
    for index in sorted(set(anchor_indices)):
        if not 0 <= index < len(expected):
            raise AlignmentUncertain("anchor_outside_decoded_sequence")
        # Full-sequence alternatives are essential: a distant repeated or
        # exchanged picture can invalidate the anchor even if ±2 looks unique.
        errors = np.abs(actual16 - expected16[index]).reshape(len(actual), -1).mean(axis=1)
        errors[index] = np.inf
        nearest = int(errors.argmin())
        margin = float(errors[nearest]) - float(diagonal[index])
        # A smaller error at the claimed index is insufficient: lossy encoding
        # can perturb the real, displaced picture more than a similar neighbour.
        # Any other frame inside the same admitted compression-error envelope
        # remains a plausible origin and must make the anchor ambiguous.
        compatible_alternatives = int((errors <= MAX_MEAN_PIXEL_ERROR).sum())
        if compatible_alternatives or margin < MIN_ANCHOR_MARGIN:
            closest = [int(j) for j in np.argsort(errors)[:min(5, len(actual)-1)]]
            raise AlignmentUncertain("ambiguous_or_shifted_anchor_picture",
                                     {"anchor_frame": index, "mean_pixel_error": float(diagonal[index]),
                                      "nearest_alternative_margin": margin,
                                      "compatible_alternative_count": compatible_alternatives,
                                      "compression_tolerance": MAX_MEAN_PIXEL_ERROR,
                                      "minimum_anchor_margin": MIN_ANCHOR_MARGIN,
                                      "searched_frames": len(actual),
                                      "closest_alternatives": [{"frame": j, "error": float(errors[j])} for j in closest]})
        details.append({"index": index, "mean_pixel_error": float(diagonal[index]),
                        "nearest_alternative_frame": nearest,
                        "nearest_alternative_margin": margin, "searched_frames": len(actual),
                        "compatible_alternative_count": compatible_alternatives})
    return {"status": "same_index_sequence_consistent_anchors_unique",
            "decoded_frames": len(expected), "max_mean_pixel_error": float(diagonal.max()),
            "mean_pixel_error": float(diagonal.mean()), "anchors": details,
            "feature_size": FEATURE_SIZE, "compression_tolerance": MAX_MEAN_PIXEL_ERROR,
            "minimum_anchor_margin": MIN_ANCHOR_MARGIN,
            "limitation": "machine_picture_evidence_final_clip_visual_review_still_required"}


def _features(path: Path, video_filter: str = ""):
    import numpy as np
    filters = ([video_filter] if video_filter else []) + [f"scale={FEATURE_SIZE}:{FEATURE_SIZE}:flags=area", "format=gray"]
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-noautorotate", "-i", str(path),
                        "-map", "0:v:0", "-vf", ",".join(filters), "-vsync", "0", "-threads", "2",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=False)
    if p.returncode:
        raise AlignmentUncertain("picture_decode_failed:" + p.stderr.decode(errors="replace")[-300:])
    size = FEATURE_SIZE ** 2
    if len(p.stdout) % size:
        raise AlignmentUncertain("incomplete_decoded_picture")
    return np.frombuffer(p.stdout, dtype=np.uint8).reshape(-1, FEATURE_SIZE, FEATURE_SIZE)


def source_roi_filter(roi: dict) -> str:
    geometry_value = roi.get("output", {}).get("geometry", {})
    if geometry_value.get("geometry_status") not in {"verified_from_filter_and_source_format", "exact"}:
        raise AlignmentUncertain("ROI_spatial_geometry_not_verified")
    box = geometry_value.get("effective_pixel_box")
    pad = geometry_value.get("pad_pixels")
    if not isinstance(box, dict) or not isinstance(pad, dict):
        raise AlignmentUncertain("ROI_spatial_geometry_missing")
    values = [box.get(k) for k in ("x", "y", "width", "height")] + [pad.get(k) for k in ("left", "right", "top", "bottom")]
    if any(type(x) is not int or x < 0 for x in values) or min(box["width"], box["height"]) <= 0:
        raise AlignmentUncertain("ROI_spatial_geometry_invalid")
    width = box["width"] + pad["left"] + pad["right"]
    height = box["height"] + pad["top"] + pad["bottom"]
    return (f"crop={box['width']}:{box['height']}:{box['x']}:{box['y']}:exact=1,"
            f"format=yuv444p,pad={width}:{height}:{pad['left']}:{pad['top']}:color=black,setsar=1")


def build_crop_command(source: Path, output: Path, candidate: dict) -> list[str]:
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-noautorotate", "-i", str(source),
            "-map", "0:v:0", "-vf",
            f"trim=start_frame={candidate['start_frame']}:end_frame={candidate['end_frame']},setpts=PTS-STARTPTS",
            "-vsync", "0", "-enc_time_base", "-1", "-threads", "2", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(output)]


def crop_video(source: Path, output: Path, candidate: dict, roi_media: dict, roi_features) -> dict:
    fd, name = tempfile.mkstemp(prefix=".aligned-cut-", suffix=".mp4", dir=output.parent)
    os.close(fd); Path(name).unlink()
    try:
        base._checked(build_crop_command(source, Path(name), candidate))
        media = probe_video(Path(name))
        start, end = candidate["start_frame"], candidate["end_frame"]
        if media["total_frames"] != end - start or (media["width"], media["height"]) != (roi_media["width"], roi_media["height"]):
            raise AlignmentUncertain("output_frame_count_or_resolution_mismatch")
        if media["duration"] < geometry.MIN_CANDIDATE_SECONDS - 1e-6:
            raise AlignmentUncertain("output_shorter_than_existing_one_second_minimum")
        expected_pts = [t - roi_media["timestamps"][start] for t in roi_media["timestamps"][start:end]]
        pts_error = max(abs(a - b) for a, b in zip(media["timestamps"], expected_pts))
        # Permit timestamp quantization at the two files' actual time bases;
        # this is independent of the picture/frame-index correspondence gate.
        pts_tolerance = max(0.000001, 2 * (float(Fraction(media["time_base"]))
                                        + float(Fraction(roi_media.get("time_base", "1/1000000")))) )
        if pts_error > pts_tolerance:
            raise AlignmentUncertain("output_presentation_timestamps_changed")
        anchors = [0, end - start - 1] + [i - start for i in candidate["source_anchor_frames"] if start <= i < end]
        picture = compare_sequences(roi_features[start:end], _features(Path(name)), anchors)
        if base.sha256_file(source) != candidate["roi_sha256"]:
            raise base.PilotError("ROI_changed_during_crop")
        digest = base.sha256_file(Path(name))
        os.link(name, output)
        return {"sha256": digest, "media": media, "picture_correspondence": picture,
                "timestamp_mapping": {"max_error_seconds": pts_error,
                                      "quantization_tolerance_seconds": pts_tolerance},
                "full_decode": "passed", "frame_mapping": {"roi_start_frame": start, "output_start_frame": 0,
                "anchors": [{"source_frame": i, "roi_frame": i, "output_frame": i - start}
                            for i in candidate["source_anchor_frames"] if start <= i < end]}}
    finally:
        Path(name).unlink(missing_ok=True)


def summarize(manifest: dict) -> dict:
    return {"scope": "development", "source_count": len(manifest["sources"]),
            "source_status": dict(Counter(s["status"] for s in manifest["sources"])),
            "source_reasons": dict(Counter(s["reason"] for s in manifest["sources"] if s.get("reason"))),
            "candidate_count": len(manifest["candidates"]),
            "candidate_status": dict(Counter(c["status"] for c in manifest["candidates"])),
            "window_roles": dict(Counter(c["window_role"] for c in manifest["candidates"])),
            "excluded_windows": len(manifest["excluded_windows"]), "published": False,
            "manual_review": "required_for_every_publishable_clip", "model_sampling_gate": "not_run"}


def run(project_root: Path, output_dir: Path, *, plan_only=False, resume=False) -> dict:
    root, output = Path(project_root).resolve(), Path(output_dir).resolve()
    if any(shutil.which(t) is None for t in ("ffmpeg", "ffprobe")):
        raise base.PilotError("ffmpeg and ffprobe must be on PATH")
    rows, rois, folds, hashes = base.load_inputs(root)
    identity = {"inputs": hashes, "scope": "development", "schema": SCHEMA,
                "code": {p.name: base.sha256_file(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                "held_ids": sorted(HELD_IDS), "guard_seconds": GUARD_SECONDS,
                "post_remaining_seconds": POST_REMAINING_SECONDS,
                "timestamp_policy": "real_decoded_pts_frame_indices_authoritative"}
    with base._run_lock(output):
        if output.exists():
            if not resume:
                raise base.PilotError("output already exists; use a new directory or explicit --resume")
            manifest = base._load(output / "manifest.json")
            if manifest["identity"] != identity:
                raise base.PilotError("resume input or code identity differs")
        else:
            if resume:
                raise base.PilotError("cannot resume a missing directory")
            output.mkdir(parents=True)
            manifest = {"schema": SCHEMA, "identity": identity, "sources": [], "candidates": [],
                        "excluded_windows": [], "complete": False, "published": False,
                        "five_category_labels": "not_assigned_pending_clip_review", "model_sampling_gate": "not_run"}
        (output / "videos").mkdir(exist_ok=True)
        def save():
            base._atomic_json(output / "manifest.json", manifest)
            base._atomic_json(output / "summary.json", summarize(manifest))
        save()
        known = {s["video_id"] for s in manifest["sources"]}
        for video_id in sorted(rows):
            if video_id in known:
                continue
            source = {"video_id": video_id, "folds": folds[video_id], "source_annotation": rows[video_id]}
            if video_id in HELD_IDS:
                source.update(status="held", reason="special_video_reserved_for_later_discussion")
                manifest["sources"].append(source); save(); continue
            try:
                roi = rois[video_id]
                if roi.get("status") != "success":
                    raise AlignmentUncertain("ROI_not_available")
                raw = root / "data/videos" / (video_id + ".mp4")
                roi_path = root / "data/roi/videos" / (video_id + ".mp4")
                raw_sha, roi_sha = base.sha256_file(raw), base.sha256_file(roi_path)
                if raw_sha != roi["source"]["sha256"] or roi_sha != roi["output"]["sha256"]:
                    raise AlignmentUncertain("source_or_ROI_sha256_mismatch")
                if roi.get("decision", {}).get("source_sha256") != raw_sha:
                    raise AlignmentUncertain("ROI_decision_source_identity_mismatch")
                source.update(source_path=raw.relative_to(root).as_posix(),
                              roi_path=roi_path.relative_to(root).as_posix(),
                              source_sha256=raw_sha, roi_sha256=roi_sha)
                source["checking_stage"] = "source_media"
                raw_media = probe_video(raw)
                source["source_media"] = raw_media
                source["checking_stage"] = "ROI_media"
                roi_media = probe_video(roi_path)
                source["roi_media"] = roi_media
                source["checking_stage"] = "annotation_and_picture_correspondence"
                if raw_media["total_frames"] != roi_media["total_frames"]:
                    raise AlignmentUncertain("source_ROI_decoded_frame_count_mismatch")
                spatial = roi.get("output", {}).get("geometry", {})
                box, pad = spatial.get("effective_pixel_box", {}), spatial.get("pad_pixels", {})
                if (box.get("x", -1) + box.get("width", -1) > raw_media["width"]
                    or box.get("y", -1) + box.get("height", -1) > raw_media["height"]
                    or [box.get("width", 0) + pad.get("left", 0) + pad.get("right", 0),
                        box.get("height", 0) + pad.get("top", 0) + pad.get("bottom", 0)]
                    != [roi_media["width"], roi_media["height"]]):
                    raise AlignmentUncertain("ROI_spatial_dimensions_do_not_match_media")
                record = adapt_annotation(rows[video_id], raw_media)
                source["geometry_input"] = record
                windows, excluded = plan_windows(record, raw_media)
                expected = _features(raw, source_roi_filter(roi)); actual = _features(roi_path)
                evidence = compare_sequences(expected, actual, record["anchor_frames"] or [0, len(expected)//2, len(expected)-1])
                source.update(status="planned", source_path=raw.relative_to(root).as_posix(),
                              roi_path=roi_path.relative_to(root).as_posix(), source_sha256=raw_sha, roi_sha256=roi_sha,
                              source_media=raw_media, roi_media=roi_media, geometry_input=record,
                              picture_correspondence=evidence)
                source.pop("checking_stage", None)
                manifest["excluded_windows"].extend(dict(w, source_video_id=video_id) for w in excluded)
                for w in windows:
                    cid = f"{video_id}_{w['window_role']}_f{w['start_frame']:06d}-{w['end_frame']:06d}"
                    candidate = {k: v for k, v in w.items() if k != "candidate_v3_labels"}
                    candidate.update(candidate_id=cid, source_video_id=video_id, scope="development",
                                     source_sha256=raw_sha, roi_sha256=roi_sha, folds=folds[video_id],
                                     source_anchor_frames=record["anchor_frames"],
                                     manual_review="required", labels_status="unassigned", status="planned",
                                     output_path=f"videos/{cid}.mp4")
                    manifest["candidates"].append(candidate)
                if not windows:
                    source.update(status="pending", reason="no_window_passes_actual_pts_bounds")
            except (AlignmentUncertain, FileNotFoundError) as exc:
                source.update(status="pending", reason=str(exc))
                if isinstance(exc, AlignmentUncertain) and exc.details:
                    source["alignment_issue"] = exc.details
            except (base.PilotError, ValueError, KeyError, TypeError) as exc:
                source.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
            manifest["sources"].append(source); save()
        admitted = {s["video_id"]: s for s in manifest["sources"] if s["status"] == "planned"}
        for s in admitted.values():
            if base.sha256_file(root/s["source_path"]) != s["source_sha256"] or base.sha256_file(root/s["roi_path"]) != s["roi_sha256"]:
                raise base.PilotError("source_identity_changed_after_plan")
        if not plan_only:
            cache = {}
            for candidate in manifest["candidates"]:
                dest = output / candidate["output_path"]
                if candidate["status"] == "cropped":
                    if not dest.is_file() or base.sha256_file(dest) != candidate["output"]["sha256"]:
                        raise base.PilotError("recorded_output_missing_or_changed")
                    continue
                if dest.exists():
                    raise base.PilotError("unrecorded_output_exists_no_overwrite")
                s = admitted[candidate["source_video_id"]]
                try:
                    if base.sha256_file(root/s["roi_path"]) != s["roi_sha256"]:
                        raise base.PilotError("ROI_changed_before_crop")
                    if s["video_id"] not in cache:
                        cache.clear()  # Candidates are source-grouped; keep one decoded sequence.
                        cache[s["video_id"]] = _features(root/s["roi_path"])
                    result = crop_video(root/s["roi_path"], dest, candidate, s["roi_media"], cache[s["video_id"]])
                    if (base.sha256_file(root/s["roi_path"]) != s["roi_sha256"]
                        or base.sha256_file(root/s["source_path"]) != s["source_sha256"]):
                        dest.unlink(missing_ok=True)  # Only this run's newly linked file.
                        raise base.PilotError("media_changed_during_crop")
                    candidate.update(output=result, status="cropped"); candidate.pop("reason", None)
                except AlignmentUncertain as exc:
                    candidate.update(status="pending", reason=str(exc))
                    if exc.details:
                        candidate["alignment_issue"] = exc.details
                except (base.PilotError, OSError, ValueError) as exc:
                    candidate.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
                save()
        for s in admitted.values():
            if base.sha256_file(root/s["source_path"]) != s["source_sha256"] or base.sha256_file(root/s["roi_path"]) != s["roi_sha256"]:
                raise base.PilotError("media_identity_changed_during_run")
        for relative, expected in hashes.items():
            if base.sha256_file(root/relative) != expected:
                raise base.PilotError("metadata_input_changed_during_run")
        manifest["plan_only"] = plan_only
        manifest["complete"] = not plan_only and not any(s["status"] in {"failed", "pending"} for s in manifest["sources"]) and all(c["status"] == "cropped" for c in manifest["candidates"])
        save()
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args.project_root, args.output_dir, plan_only=args.plan_only, resume=args.resume)
    except (base.PilotError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(summarize(result), ensure_ascii=False, indent=2))
    return 0 if args.plan_only or result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
