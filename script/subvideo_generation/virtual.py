#!/usr/bin/env python3
"""Cut reviewable windows from every source video found in one directory.

This mode is deliberately independent from the 110-source project batch: it reads
only top-level ``*.mp4`` files of the given directory, never opens ``data/``,
assigns no fold membership, and produces an unpublished batch that must not be
used for training or evaluation. Media probing, frame-accurate trimming, whole
output decoding, atomic record writes and the run lock are reused from
``script.subvideo_generation.pilot``.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from script.subvideo_generation.pilot import aligned
from script.subvideo_generation.pilot import pilot as base

SCHEMA = "tensile-virtual-sub-video/1"
INPUT_MODE = "videos_dir"
ROLE = "window"
WINDOW_SECONDS = 20
STEP_SECONDS = 15

# One unreadable or unwritable source must fail that source only, never the batch.
SOURCE_ERRORS = (base.PilotError, OSError, ValueError, KeyError, TypeError)


class VirtualError(base.PilotError):
    """The videos-directory input cannot be used as requested."""


def scan_videos_dir(videos_dir) -> list[Path]:
    """Collect top-level ``*.mp4`` files in name order; ignore everything else."""
    directory = Path(videos_dir)
    if not directory.exists():
        raise VirtualError("videos dir not found: " + str(directory))
    if not directory.is_dir():
        raise VirtualError("videos dir is not a directory: " + str(directory))
    found = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.suffix != ".mp4":
            # Non-video files and ordinary subdirectories are not input candidates.
            continue
        if entry.is_symlink():
            raise VirtualError("videos dir contains symlink: " + entry.name)
        if not entry.is_file():
            raise VirtualError("videos dir contains non-regular entry: " + entry.name)
        found.append(entry)
    if not found:
        raise VirtualError("videos dir contains no mp4 files: " + str(directory))
    return found


def plan_virtual_windows(media: dict) -> list[dict]:
    """Split one source video into review windows.

    暂定：20s 窗 / 15s 步长，role=window，待用户确认后可替换。

    This is the only policy point for virtual windows: ``run`` must call it and
    must not compute window boundaries itself. Only ``duration``, ``fps`` and
    ``total_frames`` are read. A clip shorter than one window still yields one
    window covering the whole clip (never zero, never padded), and any remainder
    after the last full window becomes a tail window ending exactly at the end of
    the material instead of being silently dropped.
    """
    duration = float(media["duration"])
    fps = float(media["fps"])
    total_frames = int(media["total_frames"])
    if not duration > 0 or not fps > 0 or total_frames < 1:
        raise VirtualError("unusable source duration, rate or frame count")

    def frame(seconds: float) -> int:
        return min(int(round(seconds * fps)), total_frames)

    windows: list[dict] = []
    start = 0.0
    while start + WINDOW_SECONDS <= duration + 1e-9:
        windows.append({"start_seconds": start, "end_seconds": start + WINDOW_SECONDS,
                        "start_frame": frame(start), "end_frame": frame(start + WINDOW_SECONDS)})
        start += STEP_SECONDS
    last_end = windows[-1]["end_seconds"] if windows else 0.0
    if not windows or duration - last_end > 1e-9:
        # The remaining material is kept as one tail window rather than dropped.
        tail_start = start if windows else 0.0
        windows.append({"start_seconds": tail_start, "end_seconds": duration,
                        "start_frame": frame(tail_start), "end_frame": total_frames})
    for sequence, window in enumerate(windows, 1):
        if window["end_frame"] <= window["start_frame"]:
            raise VirtualError("virtual window has no frames: " + str(sequence))
        window["sequence"] = sequence
        window["role"] = ROLE
    return windows


def _safe_output(root: Path, requested) -> Path:
    """Reject outputs that would overwrite inputs, source code, or the official batch."""
    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        raise VirtualError("output directory must not be a symlink")
    output = candidate.resolve()
    official = (root / "data/sub_video").resolve()
    if output == official or official in output.parents:
        raise VirtualError("output must not be the official batch directory: " + str(official))
    project_data = (root / "data").resolve()
    if output == project_data or project_data in output.parents:
        raise VirtualError("virtual output must not be written under the project data directory")
    protected = [root / name for name in ("data/videos", "data/roi", "data/splits", "data/source",
        "data/annotation", "data/annotation-table-full.csv", "script", "docs", ".git")]
    protected += [p.resolve() for p in protected]
    if output == root or any(output == p or p in output.parents or output in p.parents for p in protected):
        raise VirtualError("virtual output overlaps protected inputs or source code")
    return output


def _reject_inside_videos_dir(output: Path, videos_dir: Path) -> None:
    """The scanned input directory must stay read-only, including its subtree."""
    if output == videos_dir or videos_dir in output.parents:
        raise VirtualError("output must not be inside the videos dir: " + str(videos_dir))


def summarize(manifest: dict) -> dict:
    candidates, sources = manifest["candidates"], manifest["sources"]
    return {"schema": SCHEMA, "input_mode": INPUT_MODE,
            "source_count": len(sources),
            "source_status": dict(Counter(s["status"] for s in sources)),
            "candidate_count": len(candidates),
            "candidate_status": dict(Counter(c["status"] for c in candidates)),
            "roles": dict(Counter(c["role"] for c in candidates)),
            "complete": manifest["complete"], "for_training": False, "published": False,
            "manual_review": "required_for_every_publishable_clip"}


def _identity(hashes: dict) -> dict:
    """Pin the readable inputs, the window policy and the probe/crop pipeline used."""
    module = Path(__file__).resolve()
    script = module.parents[1]
    pipeline = {"subvideo_generation/virtual.py": module,
                "subvideo_generation/pilot/pilot.py": script / "subvideo_generation/pilot/pilot.py",
                "subvideo_generation/pilot/aligned.py": script / "subvideo_generation/pilot/aligned.py"}
    code = {name: base.sha256_file(path) for name, path in pipeline.items()}
    return {"schema": SCHEMA, "input_mode": INPUT_MODE,
            "videos": dict(hashes),
            "strategy": {"window_seconds": WINDOW_SECONDS, "step_seconds": STEP_SECONDS,
                         "role": ROLE},
            "code": code}


def _candidate_records(path: Path, source_sha256: str, windows: list[dict]) -> list[dict]:
    entries = []
    for window in windows:
        name = f"{path.stem}_window_{window['sequence']:02d}.mp4"
        entries.append({"candidate_id": f"{path.stem}_window_{window['sequence']:02d}",
                        "filename": name, "output_path": "videos/" + name,
                        "source_video_id": path.stem, "role": window["role"],
                        "sequence": window["sequence"],
                        "start_frame": window["start_frame"], "end_frame": window["end_frame"],
                        "start_seconds": window["start_seconds"], "end_seconds": window["end_seconds"],
                        "source_sha256": source_sha256, "status": "planned"})
    return entries


def _plan_source(path: Path, source_sha256: str) -> tuple[dict, list[dict]]:
    """Probe one source and let the single policy point plan its windows."""
    media = aligned.probe_video(path)
    windows = plan_virtual_windows(media)          # the single policy point
    return media, _candidate_records(path, source_sha256, windows)


def _encode(output: Path, source: dict, entries: list[dict], media: dict, path: Path, save, *,
            plan_only: bool) -> None:
    """Encode this source's unfinished windows, then publish its real status."""
    for candidate in entries:
        if plan_only or candidate["status"] == "cropped":
            continue
        destination = output / candidate["output_path"]
        try:
            result = base.crop_video(path, destination,
                                     dict(candidate, roi_sha256=candidate["source_sha256"]), media)
            if not destination.is_file() or destination.is_symlink():
                # Defence in depth: never record "cropped" for a clip that is not on disk.
                raise VirtualError("encoded clip is missing or unsafe: " + candidate["candidate_id"])
            candidate.update(status="cropped", output_sha256=result["sha256"],
                             output_frames=result["media"]["total_frames"])
            candidate.pop("reason", None)
        except SOURCE_ERRORS as exc:
            candidate.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
    failures = [candidate for candidate in entries if candidate["status"] == "failed"]
    if failures:
        source.update(status="failed",
                      reason="; ".join(f"{c['candidate_id']}: {c.get('reason', c['status'])}"
                                       for c in failures))
    elif entries and all(candidate["status"] == "cropped" for candidate in entries):
        source["status"] = "cropped"
        source.pop("reason", None)
    else:
        # Only plan_only may leave a window unencoded. Reaching here without any
        # window at all is a bug: a source must never be published as "planned"
        # with a made-up reason.
        if not entries:
            raise VirtualError("source planned no windows: " + source["video_id"])
        if not plan_only:
            raise VirtualError("windows left unencoded outside plan_only: " + source["video_id"])
        source.update(status="planned", reason="plan_only: windows planned, no clip encoded")
    save()


def _validate_existing(output: Path, manifest: dict) -> None:
    """Reject a batch whose finished clips are not the recorded ones.

    Unfinished candidates are allowed: ``--resume`` exists to complete them.
    """
    if manifest.get("schema") != SCHEMA or manifest.get("input_mode") != INPUT_MODE:
        raise VirtualError("virtual resume batch schema or input mode differs")
    videos_dir = output / "videos"
    if videos_dir.is_symlink() or not videos_dir.is_dir():
        raise VirtualError("virtual output videos directory is missing or unsafe")
    recorded = set()
    for candidate in manifest["candidates"]:
        if candidate.get("status") != "cropped":
            continue
        path = output / candidate["output_path"]
        if path.is_symlink() or not path.is_file():
            raise VirtualError("virtual resume clip missing: " + candidate["candidate_id"])
        if base.sha256_file(path) != candidate.get("output_sha256"):
            raise VirtualError("virtual resume clip bytes changed: " + candidate["candidate_id"])
        recorded.add(candidate["output_path"])
    on_disk = {str(path.relative_to(output)) for path in videos_dir.iterdir()}
    if on_disk != recorded:
        raise VirtualError("virtual resume output holds missing or unrecorded files")


def _complete(manifest: dict) -> bool:
    return (bool(manifest["sources"])
            and all(source["status"] == "cropped" for source in manifest["sources"])
            and all(candidate["status"] == "cropped" for candidate in manifest["candidates"]))


def run(project_root, videos_dir, output_dir, *, plan_only: bool = False, resume: bool = False) -> dict:
    """Build (or resume) one unpublished videos-directory batch.

    The batch identity pins the readable source bytes and the probe/crop pipeline,
    so a source that becomes readable (or whose bytes change) makes the identity
    differ: such a batch cannot be resumed, it has to be rebuilt in a new output
    directory.
    """
    root = Path(project_root).resolve()
    output = _safe_output(root, output_dir)
    inputs = Path(videos_dir).resolve()
    videos = scan_videos_dir(inputs)
    _reject_inside_videos_dir(output, inputs)
    hashes, hash_errors = {}, {}
    for path in videos:
        # One unreadable file must not take the batch down with it.
        try:
            hashes[path.name] = base.sha256_file(path)
        except SOURCE_ERRORS as exc:
            hash_errors[path.name] = f"{type(exc).__name__}: {exc}"
    identity = _identity(hashes)
    with base._run_lock(output):
        if output.exists() and any(output.iterdir()):
            if not resume:
                raise VirtualError("nonempty output exists; choose an empty directory or explicit --resume")
            manifest = base._load(output / "manifest.json")
            if manifest.get("identity") != identity:
                raise VirtualError("virtual resume metadata identity differs")
            _validate_existing(output, manifest)
            resuming = True
        else:
            if resume:
                raise VirtualError("cannot resume a missing or empty virtual output")
            output.mkdir(parents=True, exist_ok=True)
            (output / "videos").mkdir(exist_ok=True)
            manifest = {"schema": SCHEMA, "input_mode": INPUT_MODE, "for_training": False,
                        "published": False, "identity": identity, "sources": [],
                        "candidates": [], "complete": False, "plan_only": bool(plan_only)}
            resuming = False

        def save():
            base._atomic_json(output / "manifest.json", manifest)
            base._atomic_json(output / "summary.json", summarize(manifest))

        save()
        if resuming:
            for source in manifest["sources"]:
                entries = [c for c in manifest["candidates"]
                           if c["source_video_id"] == source["video_id"]]
                path = Path(source["source_path"])
                try:
                    if not entries:
                        source_sha256 = hashes.get(path.name)
                        if source_sha256 is None:
                            raise VirtualError("source is still unreadable: " + path.name)
                        source["source_sha256"] = source_sha256
                        media, entries = _plan_source(path, source_sha256)
                        manifest["candidates"].extend(entries)
                    elif all(c["status"] == "cropped" for c in entries):
                        source["status"] = "cropped"
                        source.pop("reason", None)
                        continue
                    else:
                        media = aligned.probe_video(path)
                except SOURCE_ERRORS as exc:
                    source.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
                    save()
                    continue
                source.update(total_frames=media["total_frames"], fps=media["fps"],
                              duration=media["duration"])
                _encode(output, source, entries, media, path, save, plan_only=plan_only)
        else:
            for path in videos:
                source = {"video_id": path.stem, "source_path": str(path)}
                manifest["sources"].append(source)
                if path.name in hash_errors:
                    source.update(status="failed", reason=hash_errors[path.name])
                    save()
                    continue
                source["source_sha256"] = hashes[path.name]
                try:
                    media, entries = _plan_source(path, hashes[path.name])
                except SOURCE_ERRORS as exc:
                    source.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
                    save()
                    continue
                source.update(total_frames=media["total_frames"], fps=media["fps"],
                              duration=media["duration"])
                manifest["candidates"].extend(entries)
                _encode(output, source, entries, media, path, save, plan_only=plan_only)
        manifest["complete"] = _complete(manifest)
        # Report what this run asked for: only --plan-only makes a batch plan-only.
        manifest["plan_only"] = bool(plan_only)
        save()
        return manifest
