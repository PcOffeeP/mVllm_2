"""Materialize v3 candidate clips and exact MiniCPM frame mappings safely."""

from __future__ import annotations

import hashlib
import functools
import json
import math
import os
import shutil
import subprocess
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline import artifact_index, artifact_resolver
from pipeline.current_data import resolve_data_artifact
from pipeline.data_roots import (
    DataRootError,
    resolve_workspace_artifact,
    workspace_portable_path,
)
from pipeline.preprocessing import MiniCPMVideoPreprocessor, VideoPreprocessor
from pipeline.roi_media import VideoProbe, probe_video


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEDIA_SCHEMA_VERSION = "tensile-v3-candidate-media/v1"
GATE_VERSION = "v3-actual-sampling-gate/1.0"
ENCODING_PROFILE = {
    "video_codec": "libx264",
    "preset": "fast",
    "crf": 23,
    "pixel_format": "yuv420p",
    "audio": "dropped",
    "selection": "source_frame_interval_half_open",
    "timeline": "source_nominal_cfr_from_frame_ordinal",
}
MANUAL_REVIEW_STATES = frozenset({"发生断裂", "已断裂"})
EVENT_GUARD_SECONDS = 0.5


class CandidateMediaError(RuntimeError):
    """Candidate media cannot be generated without violating an invariant."""


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _content_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CandidateMediaError(f"文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CandidateMediaError(f"JSON 无法解析: {path}: {exc}") from exc


def _require_artifact_hash(manifest: Mapping[str, Any], name: str, path: Path) -> None:
    expected = ((manifest.get("artifacts") or {}).get(name) or {}).get("sha256")
    if not isinstance(expected, str) or _sha256_file(path) != expected:
        raise CandidateMediaError(f"artifact SHA-256 不一致: {name}")


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        temporary.write_bytes(_canonical_bytes(payload))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _resolve_project_path(path_value: Any, project_root: Path) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise CandidateMediaError(f"无效项目路径: {path_value}")
    return resolve_data_artifact(path_value, project_root)


def _event_time(record: Mapping[str, Any]) -> float | None:
    for key in ("event_time_effective", "event_time"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        result = float(value)
        if math.isfinite(result):
            return result
    return None


def require_tools() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise CandidateMediaError(f"缺少媒体工具: {missing}")


def load_media_plan(
    candidate_plan_dir: Path,
    roi_media_dir: Path,
    project_root: Path,
    *,
    processor_fingerprint: str,
    scopes: Iterable[str] = ("development", "test_audit"),
    candidate_ids: Iterable[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    candidate_plan_dir = candidate_plan_dir.resolve()
    roi_media_dir = roi_media_dir.resolve()
    project_root = project_root.resolve()
    plan_manifest_path = candidate_plan_dir / "manifest.json"
    plan_manifest = _load_json(plan_manifest_path)
    if not isinstance(plan_manifest, dict):
        raise CandidateMediaError("候选计划 manifest 格式无效")
    plan_id = plan_manifest.get("plan_id")
    if not isinstance(plan_id, str) or candidate_plan_dir.name != plan_id:
        raise CandidateMediaError("候选计划目录与 plan_id 不一致")
    if plan_manifest.get("media_generated") is not False:
        raise CandidateMediaError("候选计划必须处于 media_generated=false")

    scope_names = tuple(dict.fromkeys(scopes))
    allowed_scopes = {"development", "test_audit"}
    if not scope_names or set(scope_names) - allowed_scopes:
        raise CandidateMediaError(f"非法 scope: {scope_names}")
    artifact_by_scope = {
        "development": "development_candidates.json",
        "test_audit": "test_candidate_audit.json",
    }
    candidates: list[dict[str, Any]] = []
    for scope in scope_names:
        name = artifact_by_scope[scope]
        path = candidate_plan_dir / name
        _require_artifact_hash(plan_manifest, name, path)
        payload = _load_json(path)
        if not isinstance(payload, dict) or payload.get("scope") != scope:
            raise CandidateMediaError(f"{name}: scope 无效")
        rows = payload.get("candidates")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise CandidateMediaError(f"{name}: candidates 格式无效")
        candidates.extend(dict(row) for row in rows)

    ids = [row.get("candidate_id") for row in candidates]
    if any(not isinstance(value, str) or not value for value in ids):
        raise CandidateMediaError("候选存在无效 candidate_id")
    if len(ids) != len(set(ids)):
        raise CandidateMediaError("候选 candidate_id 重复")
    selected_ids = set(candidate_ids or ids)
    unknown_ids = selected_ids - set(ids)
    if unknown_ids:
        raise CandidateMediaError(f"指定了未知 candidate_id: {sorted(unknown_ids)[:5]}")
    selected = [row for row in candidates if row["candidate_id"] in selected_ids]
    if limit is not None:
        if limit < 1:
            raise CandidateMediaError("limit 必须为正整数")
        selected = selected[:limit]

    roi_manifest_path = roi_media_dir / "manifest.json"
    roi_metadata_path = roi_media_dir / "video_meta.roi.json"
    roi_manifest = _load_json(roi_manifest_path)
    roi_metadata = _load_json(roi_metadata_path)
    if not isinstance(roi_manifest, dict) or not isinstance(roi_metadata, list):
        raise CandidateMediaError("ROI media 输入格式无效")
    _require_artifact_hash(roi_manifest, "video_meta.roi.json", roi_metadata_path)
    roi_media_id = roi_manifest.get("roi_media_id")
    expected_roi_id = ((plan_manifest.get("identity") or {}).get("inputs") or {}).get(
        "roi_media_id"
    )
    if roi_media_id != expected_roi_id:
        raise CandidateMediaError("候选计划与 ROI media ID 不一致")
    records = {
        row.get("video_id"): row
        for row in roi_metadata
        if isinstance(row, dict) and isinstance(row.get("video_id"), str)
    }
    roi_videos = {
        row.get("source_video_id"): row
        for row in (roi_manifest.get("videos") or [])
        if isinstance(row, dict) and isinstance(row.get("source_video_id"), str)
    }
    source_cache: dict[str, dict[str, Any]] = {}
    for candidate in selected:
        video_id = candidate.get("source_video")
        if video_id not in records or video_id not in roi_videos:
            raise CandidateMediaError(f"{candidate.get('candidate_id')}: ROI 源记录缺失")
        source_path = _resolve_project_path(candidate.get("source_video_path"), project_root)
        if not source_path.is_file():
            raise CandidateMediaError(f"{video_id}: ROI 源视频不存在: {source_path}")
        expected_hash = (candidate.get("roi_provenance") or {}).get("output_sha256")
        manifest_hash = roi_videos[video_id].get("output_sha256")
        if expected_hash != manifest_hash:
            raise CandidateMediaError(f"{video_id}: ROI provenance hash 不一致")
        source_cache[video_id] = {
            "path": source_path,
            "expected_sha256": expected_hash,
            "record": records[video_id],
            "manifest_record": roi_videos[video_id],
        }
    for video_id, source in source_cache.items():
        if _sha256_file(source["path"]) != source["expected_sha256"]:
            raise CandidateMediaError(f"{video_id}: ROI 源视频 SHA-256 不一致")
        source["probe"] = probe_video(source["path"])

    identity = {
        "schema_version": MEDIA_SCHEMA_VERSION,
        "candidate_plan_id": plan_id,
        "candidate_plan_manifest_sha256": _sha256_file(plan_manifest_path),
        "roi_media_id": roi_media_id,
        "roi_media_manifest_sha256": _sha256_file(roi_manifest_path),
        "processor_fingerprint": processor_fingerprint,
        "encoding_profile": ENCODING_PROFILE,
        "gate_version": GATE_VERSION,
        "event_guard_seconds": EVENT_GUARD_SECONDS,
        "scopes": list(scope_names),
        "candidate_ids_sha256": _content_hash(sorted(row["candidate_id"] for row in selected)),
        "candidate_count": len(selected),
    }
    media_id = f"candidate-media-{_content_hash(identity)[:12]}"
    return {
        "media_id": media_id,
        "identity": identity,
        "candidate_plan_id": plan_id,
        "candidates": selected,
        "sources": source_cache,
        "full_scope": len(selected) == len(candidates),
        "project_root": str(project_root),
    }


def build_crop_command(
    source: Path,
    output: Path,
    candidate: Mapping[str, Any],
    nominal_frame_rate: str,
) -> list[str]:
    start_frame = int(candidate["start_frame"])
    end_frame = int(candidate["end_frame"])
    if start_frame < 0 or end_frame <= start_frame:
        raise CandidateMediaError(f"{candidate.get('candidate_id')}: 非法帧区间")
    try:
        rate = Fraction(nominal_frame_rate)
    except (ValueError, ZeroDivisionError) as exc:
        raise CandidateMediaError("ROI 源视频标称帧率无效") from exc
    if rate <= 0:
        raise CandidateMediaError("ROI 源视频标称帧率必须为正数")
    video_filter = (
        f"trim=start_frame={start_frame}:end_frame={end_frame},"
        f"setpts=N*{rate.denominator}/({rate.numerator}*TB)"
    )
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-vf",
        video_filter,
        "-vsync",
        "0",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-movflags",
        "+faststart",
        str(output),
    ]


def _run_checked(command: list[str], context: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CandidateMediaError(f"{context}: {(result.stderr or '').strip()}")


def _validate_clip_probe(
    source_probe: VideoProbe, clip_probe: VideoProbe, candidate: Mapping[str, Any]
) -> None:
    expected_frames = int(candidate["end_frame"]) - int(candidate["start_frame"])
    if clip_probe.frame_count != expected_frames:
        raise CandidateMediaError(
            f"输出帧数错误: {clip_probe.frame_count} != {expected_frames}"
        )
    if (clip_probe.width, clip_probe.height) != (source_probe.width, source_probe.height):
        raise CandidateMediaError("输出分辨率与 ROI 源视频不一致")
    try:
        source_fps = float(Fraction(source_probe.nominal_frame_rate))
        clip_fps = float(Fraction(clip_probe.nominal_frame_rate))
    except (ValueError, ZeroDivisionError) as exc:
        raise CandidateMediaError("媒体标称帧率无效") from exc
    if not math.isclose(source_fps, clip_fps, rel_tol=1e-7, abs_tol=1e-9):
        raise CandidateMediaError("输出标称帧率与 ROI 源视频不一致")
    # ROI sources can be mildly VFR: frame count is authoritative, while the
    # stream/container duration may differ by one or two nominal frame periods.
    expected_duration = float(candidate["duration"])
    tolerance = max(0.08, 2.5 / source_fps)
    if abs(clip_probe.duration - expected_duration) > tolerance:
        raise CandidateMediaError(
            f"输出时长错误: {clip_probe.duration:.6f} != {expected_duration:.6f}"
        )


def _sample_mapping(
    preprocessor: VideoPreprocessor,
    clip_path: Path,
    candidate: Mapping[str, Any],
    clip_duration: float,
    source_path: Path,
    nominal_frame_rate: str,
) -> list[dict[str, Any]]:
    try:
        nominal_fps = float(Fraction(nominal_frame_rate))
    except (ValueError, ZeroDivisionError) as exc:
        raise CandidateMediaError("子视频标称帧率无效") from exc
    clip_timestamps = _source_frame_timestamps(str(clip_path))
    tolerance = max(1e-4, 0.01 / nominal_fps)
    if any(
        abs(timestamp - index / nominal_fps) > tolerance
        for index, timestamp in enumerate(clip_timestamps)
    ):
        raise CandidateMediaError(
            f"{candidate.get('candidate_id')}: 子视频 PTS 不符合标称 CFR 时间轴"
        )
    mappings = preprocessor.sample(str(clip_path), 0.0, clip_duration)
    source_timestamps = _source_frame_timestamps(str(source_path))
    result: list[dict[str, Any]] = []
    for mapping in mappings:
        clip_frame = int(mapping.original_frame)
        clip_timestamp = float(mapping.timestamp)
        original_frame = int(candidate["start_frame"]) + clip_frame
        if original_frame < 0 or original_frame >= len(source_timestamps):
            raise CandidateMediaError(
                f"{candidate.get('candidate_id')}: 实际抽帧映射越过 ROI 源帧范围"
            )
        result.append(
            {
                "input_index": int(mapping.input_index),
                "clip_frame": clip_frame,
                "clip_timestamp": round(clip_timestamp, 4),
                "original_frame": original_frame,
                "timestamp": round(source_timestamps[original_frame], 4),
            }
        )
    return result


@functools.lru_cache(maxsize=200)
def _source_frame_timestamps(video_path: str) -> tuple[float, ...]:
    import av

    container = av.open(video_path, "r")
    try:
        stream = next(item for item in container.streams if item.type == "video")
        timestamps: list[float] = []
        for frame in container.decode(stream):
            if frame.pts is None:
                raise CandidateMediaError(f"ROI 源视频帧缺少 PTS: {video_path}")
            timestamps.append(float(frame.pts * stream.time_base))
    finally:
        container.close()
    if not timestamps or timestamps != sorted(timestamps):
        raise CandidateMediaError(f"ROI 源视频 PTS 无效: {video_path}")
    return tuple(timestamps)


def validate_actual_sampling_gate(
    candidate: Mapping[str, Any],
    mapping: list[Mapping[str, Any]],
    source_record: Mapping[str, Any],
) -> tuple[bool, str]:
    if not mapping:
        return False, "empty_actual_frame_mapping"
    indices = [item.get("input_index") for item in mapping]
    frames = [item.get("clip_frame") for item in mapping]
    timestamps = [item.get("timestamp") for item in mapping]
    if indices != list(range(len(mapping))):
        return False, "non_contiguous_input_indices"
    if not all(isinstance(value, int) for value in frames) or frames != sorted(set(frames)):
        return False, "non_monotonic_or_duplicate_clip_frames"
    if not all(isinstance(value, (int, float)) for value in timestamps):
        return False, "invalid_sample_timestamps"
    numeric_times = [float(value) for value in timestamps]
    if numeric_times != sorted(numeric_times):
        return False, "non_monotonic_sample_timestamps"

    state = (candidate.get("candidate_v3_labels") or {}).get("clip_state")
    event = _event_time(source_record)
    if state == "发生断裂":
        if event is None:
            return False, "missing_event_time"
        if not any(value < event for value in numeric_times):
            return False, "transition_missing_pre_event_sample"
        if not any(value >= event for value in numeric_times):
            return False, "transition_missing_post_event_sample"
    elif state == "未断裂" and event is not None and source_record.get("has_fracture_canonical") is True:
        if any(value > event - EVENT_GUARD_SECONDS for value in numeric_times):
            return False, "pre_event_sample_crosses_guard"
    elif state == "已断裂":
        if event is None:
            return False, "missing_event_time"
        if any(value < event + EVENT_GUARD_SECONDS for value in numeric_times):
            return False, "post_event_sample_crosses_guard"
    elif state != "未断裂":
        return False, "unsupported_clip_state"
    return True, "passed"


def _export_frames(clip_path: Path, output_dir: Path, mapping: list[Mapping[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    for item in mapping:
        index = int(item["input_index"])
        clip_frame = int(item["clip_frame"])
        output_path = output_dir / f"frame_{index:04d}.jpg"
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(clip_path),
            "-vf",
            f"select=eq(n\\,{clip_frame})",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
        _run_checked(command, f"抽帧失败 {output_path.name}")
        if not output_path.is_file():
            raise CandidateMediaError(f"抽帧输出不存在: {output_path}")


def _frame_artifacts(
    frame_dir: Path,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "path": (
                _portable(path, project_root)
                if project_root is not None
                else str(path)
            ),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(frame_dir.glob("frame_*.jpg"))
    ]


def _portable(path: Path, project_root: Path) -> str:
    try:
        return workspace_portable_path(path, project_root)
    except DataRootError as exc:
        raise CandidateMediaError(f"输出路径不属于当前数据 workspace: {path}") from exc


def _process_candidate(
    candidate: Mapping[str, Any],
    source: Mapping[str, Any],
    preprocessor: VideoPreprocessor,
    video_root: Path,
    frame_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    candidate_id = str(candidate["candidate_id"])
    final_video = video_root / "videos" / f"{candidate_id}.mp4"
    final_frames = frame_root / candidate_id
    final_video.parent.mkdir(parents=True, exist_ok=True)
    video_tmp = final_video.with_name(f".{candidate_id}.{os.getpid()}.partial.mp4")
    frames_tmp = final_frames.with_name(f".{candidate_id}.{os.getpid()}.partial")
    source_path = Path(source["path"])
    source_probe = source.get("probe")
    if not isinstance(source_probe, VideoProbe):
        source_probe = probe_video(source_path)
    reused_video = final_video.exists()
    reused_frames = final_frames.exists()
    try:
        work_video = final_video
        if not reused_video:
            _run_checked(
                build_crop_command(
                    source_path,
                    video_tmp,
                    candidate,
                    source_probe.nominal_frame_rate,
                ),
                f"{candidate_id}: ffmpeg 裁剪失败",
            )
            work_video = video_tmp
        clip_probe = probe_video(work_video)
        _validate_clip_probe(source_probe, clip_probe, candidate)
        mapping = _sample_mapping(
            preprocessor,
            work_video,
            candidate,
            clip_probe.duration,
            source_path,
            source_probe.nominal_frame_rate,
        )
        passed, reason = validate_actual_sampling_gate(
            candidate, mapping, source["record"]
        )
        if not passed:
            return {
                "candidate_id": candidate_id,
                "source_video": candidate["source_video"],
                "scope": candidate["scope"],
                "status": "excluded_by_sampling_gate",
                "reason": reason,
                "actual_frame_mapping": mapping,
            }

        _export_frames(work_video, frames_tmp, mapping)
        new_frame_artifacts = _frame_artifacts(frames_tmp)
        if reused_frames:
            existing = _frame_artifacts(final_frames)
            if [item["sha256"] for item in existing] != [
                item["sha256"] for item in new_frame_artifacts
            ]:
                raise CandidateMediaError(f"{candidate_id}: 既有帧图与重算结果不一致")
        else:
            os.replace(frames_tmp, final_frames)
        if not reused_video:
            os.replace(video_tmp, final_video)

        result = dict(candidate)
        result.update(
            {
                "media_status": "materialized_gate_passed",
                "video_path": _portable(final_video, project_root),
                "frame_dir": _portable(final_frames, project_root),
                "actual_frame_mapping": mapping,
                "processor_fingerprint": preprocessor.fingerprint(),
                "sampling_gate": {"version": GATE_VERSION, "status": "passed"},
                "video_sha256": _sha256_file(final_video),
                "video_size_bytes": final_video.stat().st_size,
                "frame_artifacts": _frame_artifacts(
                    final_frames,
                    project_root,
                ),
                "reused_existing_video": reused_video,
                "reused_existing_frames": reused_frames,
            }
        )
        return {
            "candidate_id": candidate_id,
            "source_video": candidate["source_video"],
            "scope": candidate["scope"],
            "status": "passed",
            "candidate": result,
        }
    finally:
        video_tmp.unlink(missing_ok=True)
        if frames_tmp.exists():
            shutil.rmtree(frames_tmp)


def _validate_or_create_identity(result_dir: Path, identity: Mapping[str, Any]) -> None:
    identity_path = result_dir / "identity.json"
    if identity_path.exists():
        existing = _load_json(identity_path)
        if existing != identity:
            raise CandidateMediaError(f"既有媒体结果身份不一致: {result_dir}")
        return
    if result_dir.exists() and any(result_dir.iterdir()):
        raise CandidateMediaError(f"拒绝接管非空且无身份的结果目录: {result_dir}")
    result_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(identity_path, identity)


def _validate_receipt_media(
    receipt: Mapping[str, Any], project_root: Path
) -> bool:
    if receipt.get("status") != "passed":
        return True
    candidate = receipt.get("candidate")
    if not isinstance(candidate, Mapping):
        return False
    video_path = _resolve_project_path(candidate.get("video_path"), project_root)
    frame_dir = _resolve_project_path(candidate.get("frame_dir"), project_root)
    if not video_path.is_file() or _sha256_file(video_path) != candidate.get("video_sha256"):
        return False
    expected_frames = candidate.get("frame_artifacts")
    if not isinstance(expected_frames, list) or not frame_dir.is_dir():
        return False
    actual = _frame_artifacts(frame_dir)
    return [item["sha256"] for item in actual] == [
        item.get("sha256") for item in expected_frames if isinstance(item, Mapping)
    ]


def _validate_complete_result(
    result_dir: Path, manifest: Mapping[str, Any], plan: Mapping[str, Any]
) -> None:
    if manifest.get("identity") != plan["identity"] or manifest.get("media_generated") is not True:
        raise CandidateMediaError("既有完整媒体 manifest 身份或状态不一致")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise CandidateMediaError("既有完整媒体 manifest 缺少 artifacts")
    for name, metadata in artifacts.items():
        path = result_dir / str(name)
        if not path.is_file() or _sha256_file(path) != (metadata or {}).get("sha256"):
            raise CandidateMediaError(f"既有完整媒体 artifact 漂移: {name}")
    receipts_dir = result_dir / "receipts"
    receipts = sorted(receipts_dir.glob("*.json")) if receipts_dir.is_dir() else []
    if len(receipts) != len(plan["candidates"]):
        raise CandidateMediaError("既有完整媒体 receipt 数量与计划不一致")
    for path in receipts:
        receipt = _load_json(path)
        if not isinstance(receipt, Mapping) or not _validate_receipt_media(
            receipt, Path(plan["project_root"])
        ):
            raise CandidateMediaError(f"既有完整媒体或 receipt 漂移: {path.name}")


def _append_candidate_media_index(
    result_root: Path, manifest: Mapping[str, Any]
) -> None:
    artifact_index.append_entry(
        result_root,
        {
            "id": manifest["media_id"],
            "created_at": artifact_index.utc_now(),
            "step": "candidate_media",
            "inputs": {
                "candidate_plan_id": manifest["identity"]["candidate_plan_id"],
            },
            "stats": manifest.get("counts", {}),
            "note": "v3 candidate media result",
        },
    )


def _artifact_counts(
    root: Path, plan_id: str
) -> dict[str, int]:
    video_dir = root / plan_id / "videos"
    video_count = len(list(video_dir.glob("*.mp4"))) if video_dir.is_dir() else 0
    frame_dir = root / plan_id
    frame_count = (
        len(list(frame_dir.rglob("frame_*.jpg"))) if frame_dir.is_dir() else 0
    )
    return {"video_count": video_count, "frame_count": frame_count}


def _append_subvideo_index(
    subvideo_root: Path, manifest: Mapping[str, Any]
) -> None:
    plan_id = str(manifest["identity"]["candidate_plan_id"])
    counts = _artifact_counts(subvideo_root, plan_id)
    artifact_index.append_entry(
        subvideo_root,
        {
            "id": plan_id,
            "created_at": artifact_index.utc_now(),
            "step": "subvideo",
            "inputs": {
                "candidate_plan_id": plan_id,
                "media_id": manifest["media_id"],
                "roi_media_id": manifest["identity"].get("roi_media_id"),
            },
            "stats": {**manifest.get("counts", {}), **counts},
            "note": "v3 candidate subvideos",
        },
    )
    artifact_resolver.update_latest(subvideo_root, plan_id)


def _append_frame_index(
    frame_root: Path, manifest: Mapping[str, Any]
) -> None:
    plan_id = str(manifest["identity"]["candidate_plan_id"])
    counts = _artifact_counts(frame_root, plan_id)
    artifact_index.append_entry(
        frame_root,
        {
            "id": plan_id,
            "created_at": artifact_index.utc_now(),
            "step": "frame",
            "inputs": {
                "candidate_plan_id": plan_id,
                "media_id": manifest["media_id"],
                "roi_media_id": manifest["identity"].get("roi_media_id"),
            },
            "stats": {**manifest.get("counts", {}), **counts},
            "note": "v3 candidate frames",
        },
    )
    artifact_resolver.update_latest(frame_root, plan_id)


def materialize_media_plan(
    plan: Mapping[str, Any],
    *,
    model_path: str,
    video_output_root: Path,
    frame_output_root: Path,
    result_root: Path,
    preprocessor: VideoPreprocessor | None = None,
) -> Path:
    require_tools()
    project_root = Path(plan["project_root"])
    result_dir = result_root / str(plan["media_id"])
    _validate_or_create_identity(result_dir, plan["identity"])
    if (result_dir / "manifest.json").exists():
        manifest = _load_json(result_dir / "manifest.json")
        if not isinstance(manifest, dict):
            raise CandidateMediaError("既有完整媒体 manifest 格式无效")
        _validate_complete_result(result_dir, manifest, plan)
        _append_candidate_media_index(result_root, manifest)
        artifact_resolver.update_latest(result_root, manifest["media_id"])
        _append_subvideo_index(video_output_root, manifest)
        _append_frame_index(frame_output_root, manifest)
        return result_dir

    processor = preprocessor or MiniCPMVideoPreprocessor(
        model_path_or_name=model_path, max_frames=8
    )
    if processor.fingerprint() != plan["identity"]["processor_fingerprint"]:
        raise CandidateMediaError("实际 processor fingerprint 与媒体计划不一致")
    plan_id = str(plan["candidate_plan_id"])
    video_root = video_output_root / plan_id
    frame_root = frame_output_root / plan_id
    receipts_dir = result_dir / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipts: list[dict[str, Any]] = []
    for candidate in plan["candidates"]:
        receipt_path = receipts_dir / f"{candidate['candidate_id']}.json"
        if receipt_path.exists():
            receipt = _load_json(receipt_path)
            if not isinstance(receipt, dict) or not _validate_receipt_media(
                receipt, project_root
            ):
                raise CandidateMediaError(f"既有 receipt 或媒体漂移: {receipt_path}")
        else:
            source = plan["sources"][candidate["source_video"]]
            receipt = _process_candidate(
                candidate,
                source,
                processor,
                video_root,
                frame_root,
                project_root,
            )
            _atomic_write(receipt_path, receipt)
        receipts.append(receipt)

    passed = [item["candidate"] for item in receipts if item.get("status") == "passed"]
    excluded = [item for item in receipts if item.get("status") != "passed"]
    if len(passed) + len(excluded) != len(plan["candidates"]):
        raise CandidateMediaError("媒体结果数量与计划不一致")
    development = [item for item in passed if item["scope"] == "development"]
    test_audit = [item for item in passed if item["scope"] == "test_audit"]
    review_queue = [
        item
        for item in development
        if item["candidate_v3_labels"]["clip_state"] in MANUAL_REVIEW_STATES
    ]
    payloads = {
        "development_materialized.json": {
            "schema_version": MEDIA_SCHEMA_VERSION,
            "media_id": plan["media_id"],
            "scope": "development",
            "candidates": development,
        },
        "test_materialized_audit.json": {
            "schema_version": MEDIA_SCHEMA_VERSION,
            "media_id": plan["media_id"],
            "scope": "test_audit",
            "candidates": test_audit,
        },
        "review_queue.json": {
            "schema_version": MEDIA_SCHEMA_VERSION,
            "media_id": plan["media_id"],
            "scope": "development",
            "candidates": review_queue,
        },
        "generation_report.json": {
            "schema_version": MEDIA_SCHEMA_VERSION,
            "media_id": plan["media_id"],
            "planned_count": len(plan["candidates"]),
            "passed_count": len(passed),
            "excluded_count": len(excluded),
            "status_counts": dict(sorted(Counter(item["status"] for item in receipts).items())),
            "exclusion_reason_counts": dict(
                sorted(Counter(str(item.get("reason")) for item in excluded).items())
            ),
            "excluded": excluded,
        },
    }
    for name, payload in payloads.items():
        _atomic_write(result_dir / name, payload)
    artifacts = {
        name: {"sha256": _sha256_file(result_dir / name)} for name in sorted(payloads)
    }
    manifest = {
        "schema_version": MEDIA_SCHEMA_VERSION,
        "media_id": plan["media_id"],
        "identity": plan["identity"],
        "full_scope": plan["full_scope"],
        "counts": {
            "planned": len(plan["candidates"]),
            "passed": len(passed),
            "excluded": len(excluded),
            "development_passed": len(development),
            "test_audit_passed": len(test_audit),
            "development_manual_review": len(review_queue),
        },
        "video_root": _portable(video_root, project_root),
        "frame_root": _portable(frame_root, project_root),
        "artifacts": artifacts,
        "media_generated": True,
    }
    _atomic_write(result_dir / "manifest.json", manifest)
    _append_candidate_media_index(result_root, manifest)
    artifact_resolver.update_latest(result_root, manifest["media_id"])
    _append_subvideo_index(video_output_root, manifest)
    _append_frame_index(frame_output_root, manifest)
    return result_dir
