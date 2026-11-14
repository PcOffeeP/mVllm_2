#!/usr/bin/env python3
"""Development-only first cuts: reused old windows, stricter admission, manual review required."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from fractions import Fraction
import shutil
import subprocess
import tempfile
from collections import Counter
from contextlib import contextmanager
from typing import Any

try:
    from . import geometry
except ImportError:
    import geometry

SCHEMA = "tensile-initial-subvideo-cut"
SOURCE_COMMIT = "2c272ce3548c917bbfa96fe474858f9bf1998893"
POST_REMAINING_SECONDS = 2.0


class PilotError(RuntimeError):
    pass


class SkipSource(PilotError):
    """The input does not meet the initial-cut admission conditions."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _atomic_json(path: Path, value: Any) -> None:
    fd, name = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical_bytes(value)); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _checked(command: list[str]) -> subprocess.CompletedProcess:
    p = subprocess.run(command, capture_output=True, text=True, check=False)
    if p.returncode:
        raise PilotError((p.stderr or "media command failed")[-3000:].strip())
    return p


def probe_video(path: Path) -> dict:
    """Decode timestamps/counts; require CFR before reusing frame-to-time geometry."""
    p = _checked(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
                  "-show_format", "-show_frames", "-show_entries",
                  "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration:"
                  "format=duration:frame=best_effort_timestamp_time", "-of", "json", str(path)])
    data = json.loads(p.stdout)
    streams = data.get("streams", [])
    if len(streams) != 1:
        raise SkipSource("unsupported_video_stream")
    stream = streams[0]
    try:
        rate = Fraction(stream["r_frame_rate"])
        if rate <= 0:
            raise ValueError
        timestamps = [float(f["best_effort_timestamp_time"]) for f in data["frames"]]
        if len(timestamps) < 2 or not all(math.isfinite(t) for t in timestamps):
            raise ValueError
        first = timestamps[0]
        normalized = [t - first for t in timestamps]
        tolerance = max(0.00002, (1 / float(rate)) / 1000)
        if any(abs(t - i / float(rate)) > tolerance for i, t in enumerate(normalized)):
            raise SkipSource("variable_or_unreliable_frame_timestamps")
        duration = float(stream.get("duration", data.get("format", {}).get("duration")))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        if abs(duration - len(timestamps) / float(rate)) > max(0.08, 2.5 / float(rate)):
            raise SkipSource("duration_frame_count_mismatch")
        return {"width": int(stream["width"]), "height": int(stream["height"]),
                "fps": float(rate), "nominal_frame_rate": str(rate), "total_frames": len(timestamps),
                "duration": duration, "timestamp_origin": first,
                "timestamp_sha256": hashlib.sha256(canonical_bytes(normalized)).hexdigest(),
                "timestamp_validation": "all_decoded_frame_timestamps_match_constant_nominal_rate",
                "timestamp_tolerance_seconds": tolerance}
    except SkipSource:
        raise
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise SkipSource("unusable_video_metadata_or_timestamps") from exc


def _number(text: Any) -> float | None:
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def adapt_annotation(row: dict, media: dict) -> dict:
    """Only explicit supported current observations feed old geometry; no final labels."""
    for field in ("异常_未夹紧", "异常_视频异常", "异常_爆炸性断裂"):
        if row.get(field) not in {"是", "否"}:
            raise SkipSource("uncertain_anomaly_annotation:" + field)
    if row["异常_未夹紧"] == "是":
        raise SkipSource("unclamped")
    if row["异常_视频异常"] == "是":
        raise SkipSource("video_abnormal")
    state = row.get("断裂状态")
    if state not in {"发生断裂", "未断裂"}:
        raise SkipSource("unsupported_or_uncertain_source_state")
    record = {"video_id": row["id"], "duration": media["duration"], "fps": media["fps"],
              "total_frames": media["total_frames"], "has_fracture_canonical": state == "发生断裂",
              "is_abnormal_canonical": False, "location_canonical": None}
    if state == "未断裂":
        if any(row.get(f) not in {"无", ""} for f in ("断裂时间点", "断裂帧_前", "断裂帧_后")):
            raise SkipSource("negative_source_has_event_evidence_conflict")
        if row["异常_爆炸性断裂"] != "否":
            raise SkipSource("negative_source_has_explosive_conflict")
        return dict(record, type="未断裂", event_time=None, event_time_reliable=False)
    mechanism = row.get("断裂模式")
    mapping = geometry.map_legacy_fracture_type(mechanism)
    if not mapping.matched:
        raise SkipSource("fracture_mechanism_not_supported_by_old_geometry")
    if row["异常_爆炸性断裂"] == "是" and mechanism != "爆炸性断裂":
        raise SkipSource("explosive_annotation_requires_new_rule")
    event = _number(row.get("断裂时间点"))
    after = _number(row.get("断裂帧_后"))
    before = _number(row.get("断裂帧_前"))
    if event is None or after is None or before is None:
        raise SkipSource("missing_precise_event_or_frame_boundary")
    if after != int(after) or before != int(before) or not (0 <= before < after < media["total_frames"]):
        raise SkipSource("invalid_or_one_sided_event_frames")
    # The current authoritative observation is the first separated frame.
    # A wider uncertainty interval is deliberately not converted into a point.
    if int(after) - int(before) != 1:
        raise SkipSource("non_adjacent_event_frame_boundary")
    frame_event = int(after) / media["fps"]
    if abs(event - frame_event) > max(0.0001, 0.05 / media["fps"]):
        raise SkipSource("event_time_disagrees_with_authoritative_frame")
    if not 0 < event < media["duration"]:
        raise SkipSource("event_outside_usable_video")
    return dict(record, type=mechanism, event_time=frame_event, event_time_reliable=True,
                event_time_input=event, event_frame=int(after))


def plan_windows(record: dict) -> tuple[list[dict], list[dict]]:
    windows = geometry._raw_candidates_for_source(record, references=())
    accepted, excluded = [], []
    # Container/stream duration may extend beyond the last decoded frame. Only
    # the intersection of reported duration and decoded frame coverage is usable.
    decoded_end = record["total_frames"] / record["fps"]
    usable_end = min(record["duration"], decoded_end)
    for window in windows:
        if (window["window_role"] == "post_event"
                and usable_end - record["event_time"] - geometry.EVENT_GUARD_SECONDS
                < POST_REMAINING_SECONDS - 1e-9):
            excluded.append({**window, "reason": "post_source_remaining_after_guard_less_than_two_seconds"})
        else:
            accepted.append(window)
    return accepted, excluded


def load_inputs(project_root: Path) -> tuple[dict, dict, dict, dict]:
    splits_dir = project_root / "data/splits/three-fold"
    filenames = ["test.json"] + [f"fold_{i}_{part}.json" for i in range(3) for part in ("train", "val")]
    payloads, hashes = {}, {}
    for name in filenames:
        path = splits_dir / name; payload = _load(path); values = payload.get("video_ids")
        if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values):
            raise PilotError("invalid member list: " + name)
        if len(values) != len(set(values)) or any(not v.startswith("video_") or not v[6:].isdigit() for v in values):
            raise PilotError("duplicate or unsafe ID: " + name)
        payloads[name] = set(values); hashes[str(path.relative_to(project_root))] = sha256_file(path)
    test = payloads["test.json"]; dev = payloads["fold_0_train.json"] | payloads["fold_0_val.json"]
    for i in range(3):
        train, val = payloads[f"fold_{i}_train.json"], payloads[f"fold_{i}_val.json"]
        if train & val or train | val != dev or (train | val) & test:
            raise PilotError("split conflict")
    vals = [payloads[f"fold_{i}_val.json"] for i in range(3)]
    if sum(map(len, vals)) != len(dev) or set.union(*vals) != dev:
        raise PilotError("validation rotation conflict")
    annotations = project_root / "data/annotation-table-full.csv"
    rows = {}
    with annotations.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            video_id = row.get("id")
            if video_id not in dev:
                continue  # Never interpret test annotation values or access its media.
            if video_id in rows:
                raise PilotError("duplicate development annotation")
            rows[video_id] = row
    if set(rows) != dev:
        raise PilotError("development annotation coverage mismatch")
    roi_path = project_root / "data/roi/manifest.json"; roi = _load(roi_path)
    roi_rows = {}
    for row in roi["videos"]:
        if row.get("video_id") not in dev:
            continue
        if row["video_id"] in roi_rows:
            raise PilotError("duplicate development ROI record")
        roi_rows[row["video_id"]] = row
    if set(roi_rows) != dev:
        raise PilotError("development ROI coverage mismatch")
    for path in (annotations, roi_path):
        hashes[str(path.relative_to(project_root))] = sha256_file(path)
    folds = {v: {str(i): "val" if v in vals[i] else "train" for i in range(3)} for v in dev}
    return rows, roi_rows, folds, hashes


def build_crop_command(source: Path, output: Path, candidate: dict, rate_text: str) -> list[str]:
    rate = Fraction(rate_text)
    video_filter = (f"trim=start_frame={candidate['start_frame']}:end_frame={candidate['end_frame']},"
                    f"setpts=N*{rate.denominator}/({rate.numerator}*TB)")
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-i", str(source),
            "-map", "0:v:0", "-vf", video_filter, "-vsync", "0", "-threads", "2", "-c:v", "libx264",
            "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(output)]


def crop_video(source: Path, output: Path, candidate: dict, media: dict) -> dict:
    fd, temporary = tempfile.mkstemp(prefix=".cut-", suffix=".mp4", dir=output.parent)
    os.close(fd); Path(temporary).unlink()  # -n also protects the temporary output.
    try:
        _checked(build_crop_command(source, Path(temporary), candidate, media["nominal_frame_rate"]))
        probe = probe_video(Path(temporary))
        expected = candidate["end_frame"] - candidate["start_frame"]
        if probe["total_frames"] != expected:
            raise PilotError("output_frame_count_mismatch")
        if (probe["width"], probe["height"]) != (media["width"], media["height"]):
            raise PilotError("output_resolution_mismatch")
        if Fraction(probe["nominal_frame_rate"]) != Fraction(media["nominal_frame_rate"]):
            raise PilotError("output_rate_mismatch")
        if abs(probe["duration"] - expected / media["fps"]) > max(0.08, 2.5 / media["fps"]):
            raise PilotError("output_duration_mismatch")
        _checked(["ffmpeg", "-v", "error", "-nostdin", "-threads", "2", "-i", temporary, "-f", "null", "-"])
        digest = sha256_file(Path(temporary))
        if sha256_file(source) != candidate["roi_sha256"]:
            raise PilotError("ROI_changed_during_crop")
        # link is atomic and refuses replacement even if another writer creates output.
        os.link(temporary, output)
        return {"sha256": digest, "media": probe, "full_decode": "passed"}
    finally:
        Path(temporary).unlink(missing_ok=True)


def summarize(manifest: dict) -> dict:
    candidates = manifest["candidates"]; sources = manifest["sources"]
    counts = Counter(c["status"] for c in candidates)
    return {"scope": "development", "source_count": len(sources),
            "source_status": dict(Counter(s["status"] for s in sources)),
            "source_skip_reasons": dict(Counter(s["reason"] for s in sources if s.get("reason"))),
            "candidate_count": len(candidates), "candidate_status": dict(counts),
            "window_roles": dict(Counter(c["window_role"] for c in candidates)),
            "duration_seconds": {"minimum": min((c["duration"] for c in candidates), default=None),
                                 "maximum": max((c["duration"] for c in candidates), default=None),
                                 "total": round(sum(c["duration"] for c in candidates), 4)},
            "excluded_windows": len(manifest["excluded_windows"]),
            "media_generated": counts.get("cropped", 0), "manual_review": "required_for_every_publishable_clip",
            "published": False, "model_sampling_gate": "not_run"}


@contextmanager
def _run_lock(output: Path):
    name = hashlib.sha256(str(output).encode()).hexdigest()
    with (Path(tempfile.gettempdir()) / ("tensile-initial-cut-" + name + ".lock")).open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PilotError("another process is using this output") from exc
        yield


def run(project_root: Path, output_dir: Path, *, plan_only: bool = False, resume: bool = False) -> dict:
    project_root = Path(project_root).resolve(); output_dir = Path(output_dir).resolve()
    if any(shutil.which(t) is None for t in ("ffmpeg", "ffprobe")):
        raise PilotError("ffmpeg and ffprobe must be on PATH")
    rows, roi_rows, folds, hashes = load_inputs(project_root)
    code_dir = Path(__file__).resolve().parent
    code_hashes = {p.name: sha256_file(p) for p in sorted(code_dir.glob("*.py"))}
    identity = {"inputs": hashes, "code": code_hashes, "scope": "development",
                "geometry_source_commit": SOURCE_COMMIT,
                "reference_policy": "empty_reference_old_geometry_deterministic_fallback_shifts_0_and_1",
                "post_remaining_seconds": POST_REMAINING_SECONDS}
    with _run_lock(output_dir):
        if output_dir.exists():
            if not resume:
                raise PilotError("output already exists; use a new directory or explicit --resume")
            manifest = _load(output_dir / "manifest.json")
            if manifest["identity"] != identity:
                raise PilotError("resume input or code identity differs")
        else:
            if resume:
                raise PilotError("cannot resume a missing directory")
            output_dir.mkdir(parents=True)
            manifest = {"schema": SCHEMA, "identity": identity, "sources": [], "candidates": [],
                        "excluded_windows": [], "published": False, "complete": False,
                        "five_category_labels": "not_assigned_pending_clip_review",
                        "legacy_labels": "geometry_aid_only_not_current_labels",
                        "model_sampling_gate": "not_run", "plan_only": plan_only}
        (output_dir / "videos").mkdir(exist_ok=True)
        prior_sources = {s["video_id"]: s for s in manifest["sources"]}
        def save():
            _atomic_json(output_dir / "manifest.json", manifest)
            _atomic_json(output_dir / "summary.json", summarize(manifest))
        save()
        for video_id in sorted(rows):
            if video_id in prior_sources:
                continue
            roi = roi_rows[video_id]; row = rows[video_id]
            source = {"video_id": video_id, "folds": folds[video_id], "source_annotation": row,
                      "status": "checking"}
            try:
                if roi.get("status") != "success":
                    raise SkipSource("ROI_not_available")
                raw = project_root / "data/videos" / (video_id + ".mp4")
                media_path = project_root / "data/roi/videos" / (video_id + ".mp4")
                # Resolve canonical current paths, not absolute legacy paths in the ROI record.
                source_sha, roi_sha = sha256_file(raw), sha256_file(media_path)
                if source_sha != roi["source"]["sha256"] or roi_sha != roi["output"]["sha256"]:
                    raise SkipSource("source_or_ROI_sha256_mismatch")
                if roi.get("decision", {}).get("source_sha256") != source_sha:
                    raise SkipSource("ROI_decision_source_identity_mismatch")
                source.update(source_sha256=source_sha, roi_sha256=roi_sha,
                              source_path=raw.relative_to(project_root).as_posix(),
                              roi_path=media_path.relative_to(project_root).as_posix())
                raw_probe, media = probe_video(raw), probe_video(media_path)
                if (raw_probe["total_frames"] != media["total_frames"]
                    or raw_probe["nominal_frame_rate"] != media["nominal_frame_rate"]):
                    raise SkipSource("source_ROI_frame_identity_mismatch")
                source.update(source_media=raw_probe, roi_media=media)
                record = adapt_annotation(row, media); source["geometry_input"] = record
                windows, excluded = plan_windows(record)
                manifest["excluded_windows"].extend({"source_video_id": video_id, **w} for w in excluded)
                if not windows:
                    raise SkipSource("no_window_meets_old_geometry_and_strict_checks")
                for w in windows:
                    cid = f"{video_id}_{w['window_role']}_f{w['start_frame']:06d}-{w['end_frame']:06d}"
                    candidate = {k: v for k, v in w.items() if k != "candidate_v3_labels"}
                    candidate.update(candidate_id=cid, source_video_id=video_id, scope="development",
                                     source_sha256=source_sha, roi_sha256=roi_sha, folds=folds[video_id],
                                     legacy_geometry_labels=w["candidate_v3_labels"],
                                     manual_review="required", labels_status="unassigned", status="planned",
                                     output_path=f"videos/{cid}.mp4")
                    manifest["candidates"].append(candidate)
                source["status"] = "planned"
            except (SkipSource, FileNotFoundError) as exc:
                source.update(status="skipped", reason=str(exc))
            except (PilotError, ValueError, KeyError, TypeError) as exc:
                source.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
            manifest["sources"].append(source); save()
        # Recheck every admitted source before media generation/resume; no stale pin reuse.
        admitted = {s["video_id"]: s for s in manifest["sources"] if s["status"] == "planned"}
        for video_id, source in admitted.items():
            if (sha256_file(project_root / source["source_path"]) != source["source_sha256"]
                or sha256_file(project_root / source["roi_path"]) != source["roi_sha256"]):
                raise PilotError("source identity changed after plan: " + video_id)
        if not plan_only:
            for candidate in manifest["candidates"]:
                output = output_dir / candidate["output_path"]
                if candidate["status"] == "cropped":
                    if not output.is_file() or sha256_file(output) != candidate["output"]["sha256"]:
                        raise PilotError("recorded output missing or changed; no overwrite: " + candidate["candidate_id"])
                    continue
                if output.exists():
                    raise PilotError("unrecorded output already exists; no overwrite: " + str(output))
                source = admitted[candidate["source_video_id"]]
                try:
                    if sha256_file(project_root / source["roi_path"]) != source["roi_sha256"]:
                        raise PilotError("ROI_changed_before_crop")
                    candidate["output"] = crop_video(project_root / source["roi_path"], output,
                                                       candidate, source["roi_media"])
                    if sha256_file(project_root / source["roi_path"]) != source["roi_sha256"]:
                        output.unlink(missing_ok=True)  # This run just created this exact output.
                        candidate.pop("output", None)
                        raise PilotError("ROI_changed_during_crop")
                    candidate["status"] = "cropped"
                    candidate.pop("error", None)
                except (PilotError, OSError, ValueError) as exc:
                    candidate.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                save()
        for source in admitted.values():
            if (sha256_file(project_root / source["source_path"]) != source["source_sha256"]
                or sha256_file(project_root / source["roi_path"]) != source["roi_sha256"]):
                raise PilotError("media identity changed during run: " + source["video_id"])
        # Inputs cannot silently change while a long run is in progress.
        for relative, expected in hashes.items():
            if sha256_file(project_root / relative) != expected:
                raise PilotError("input changed during run: " + relative)
        manifest["plan_only"] = plan_only
        manifest["complete"] = (all(c["status"] == "cropped" for c in manifest["candidates"])
                                and not any(s["status"] == "failed" for s in manifest["sources"])
                                and not plan_only)
        save()
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args.project_root, args.output_dir, plan_only=args.plan_only, resume=args.resume)
    except (PilotError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(summarize(result), ensure_ascii=False, indent=2))
    return 0 if args.plan_only or result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
