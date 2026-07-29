"""Materialize immutable ROI-normalized source videos from a frozen ROI manifest."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.current_data import resolve_data_artifact

ROI_MEDIA_SCHEMA_VERSION = "tensile-roi-media/v1"
ENCODING_PROFILE = {
    "video_codec": "libx264",
    "preset": "fast",
    "crf": 23,
    "pixel_format": "yuv420p",
    "audio": "dropped",
    "frame_sync": "vsync_0_passthrough",
    "pad_color": "black",
}


class RoiMediaError(RuntimeError):
    """ROI media cannot be safely planned, generated, or validated."""


@dataclass(frozen=True)
class VideoProbe:
    width: int
    height: int
    frame_rate: str
    nominal_frame_rate: str
    frame_count: int
    duration: float


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


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RoiMediaError(f"文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RoiMediaError(f"JSON 无法解析: {path}: {exc}") from exc


def _exact_pad_dimensions(width: int, height: int) -> tuple[int, int]:
    """Return the smallest even exact-3:4 canvas that contains the source."""
    if width < 2 or height < 2:
        raise RoiMediaError("源分辨率必须至少为 2×2")
    scale = max(math.ceil(width / 3), math.ceil(height / 4))
    scale += scale % 2
    return 3 * scale, 4 * scale


def filter_for_decision(decision: Mapping[str, Any]) -> tuple[str, tuple[int, int]]:
    mode = decision.get("mode")
    resolution = decision.get("source_resolution")
    if (
        not isinstance(resolution, list)
        or len(resolution) != 2
        or any(type(value) is not int or value < 2 for value in resolution)
    ):
        raise RoiMediaError(f"{decision.get('source_video_id')}: source_resolution 无效")
    source_width, source_height = resolution

    if mode == "fixed_roi":
        box = decision.get("pixel_box")
        if not isinstance(box, Mapping):
            raise RoiMediaError(f"{decision.get('source_video_id')}: 缺少 pixel_box")
        try:
            x, y = int(box["x"]), int(box["y"])
            width, height = int(box["width"]), int(box["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RoiMediaError(f"{decision.get('source_video_id')}: pixel_box 无效") from exc
        if (
            x < 0
            or y < 0
            or width < 2
            or height < 2
            or x + width > source_width
            or y + height > source_height
        ):
            raise RoiMediaError(f"{decision.get('source_video_id')}: pixel_box 越界")
        if width * 4 != height * 3 or width % 2 or height % 2:
            raise RoiMediaError(
                f"{decision.get('source_video_id')}: fixed_roi 必须是偶数像素精确 3:4"
            )
        return f"crop={width}:{height}:{x}:{y},setsar=1", (width, height)

    if mode == "no_crop":
        target_width, target_height = _exact_pad_dimensions(
            source_width, source_height
        )
        x = (target_width - source_width) // 2
        y = (target_height - source_height) // 2
        return (
            f"pad={target_width}:{target_height}:{x}:{y}:color=black,setsar=1",
            (target_width, target_height),
        )
    raise RoiMediaError(f"{decision.get('source_video_id')}: ROI mode 无效: {mode}")


def build_ffmpeg_command(
    source_path: Path,
    output_path: Path,
    decision: Mapping[str, Any],
) -> list[str]:
    video_filter, _ = filter_for_decision(decision)
    return [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_path),
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
        str(output_path),
    ]


def probe_video(path: Path) -> VideoProbe:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_frames",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate,nb_read_frames,nb_frames,duration:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RoiMediaError(f"ffprobe 失败: {path}: {(result.stderr or '').strip()}")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        frame_count = int(stream.get("nb_read_frames") or stream.get("nb_frames"))
        duration = float(stream.get("duration") or payload["format"]["duration"])
        return VideoProbe(
            width=int(stream["width"]),
            height=int(stream["height"]),
            frame_rate=str(stream["avg_frame_rate"]),
            nominal_frame_rate=str(stream["r_frame_rate"]),
            frame_count=frame_count,
            duration=duration,
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RoiMediaError(f"ffprobe 返回缺少必要字段: {path}") from exc


def validate_temporal_contract(
    source: VideoProbe,
    output: VideoProbe,
    expected_resolution: tuple[int, int],
) -> None:
    if (output.width, output.height) != expected_resolution:
        raise RoiMediaError(
            f"输出分辨率错误: {(output.width, output.height)} != {expected_resolution}"
        )
    if output.frame_count != source.frame_count:
        raise RoiMediaError(
            f"输出帧数发生变化: {output.frame_count} != {source.frame_count}"
        )
    try:
        source_rate = float(Fraction(source.nominal_frame_rate))
        output_rate = float(Fraction(output.nominal_frame_rate))
        same_frame_rate = math.isclose(
            source_rate, output_rate, rel_tol=1e-6, abs_tol=1e-9
        )
    except (TypeError, ValueError, ZeroDivisionError):
        same_frame_rate = output.nominal_frame_rate == source.nominal_frame_rate
        source_rate = source.frame_count / source.duration
    if not same_frame_rate:
        raise RoiMediaError(
            "输出标称帧率发生变化: "
            f"{output.nominal_frame_rate} != {source.nominal_frame_rate}"
        )
    tolerance = max(0.02, 1.0 / max(source_rate, 1.0) + 0.005)
    if abs(output.duration - source.duration) > tolerance:
        raise RoiMediaError(
            f"输出时长发生变化: {output.duration:.6f} != {source.duration:.6f}"
        )


def load_generation_plan(
    roi_manifest_dir: Path,
    video_metadata_path: Path,
    project_root: Path,
    *,
    selected_video_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    roi_manifest_dir = roi_manifest_dir.resolve()
    manifest_path = roi_manifest_dir / "manifest.json"
    decisions_path = roi_manifest_dir / "roi_decisions.frozen.json"
    manifest = _load_json(manifest_path)
    decisions_payload = _load_json(decisions_path)
    videos_payload = _load_json(video_metadata_path)
    if not isinstance(manifest, dict) or not isinstance(decisions_payload, dict):
        raise RoiMediaError("ROI manifest 格式无效")
    if not isinstance(videos_payload, list):
        raise RoiMediaError("video_meta 必须是对象列表")

    expected_decisions_hash = (
        manifest.get("artifacts", {})
        .get("roi_decisions.frozen.json", {})
        .get("sha256")
    )
    if _sha256_file(decisions_path) != expected_decisions_hash:
        raise RoiMediaError("冻结 ROI decisions 哈希与 manifest 不一致")
    expected_metadata_hash = manifest.get("inputs", {}).get("video_metadata_sha256")
    if _sha256_file(video_metadata_path) != expected_metadata_hash:
        raise RoiMediaError("video_meta 哈希与冻结 ROI manifest 不一致")

    videos = {
        row.get("video_id"): row
        for row in videos_payload
        if isinstance(row, dict) and isinstance(row.get("video_id"), str)
    }
    raw_decisions = decisions_payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise RoiMediaError("冻结 ROI decisions 缺少 decisions 列表")
    decisions = {
        row.get("source_video_id"): row
        for row in raw_decisions
        if isinstance(row, dict) and isinstance(row.get("source_video_id"), str)
    }
    if set(videos) != set(decisions):
        raise RoiMediaError("video_meta 与冻结 ROI decisions 覆盖范围不一致")

    selected = set(selected_video_ids or decisions)
    unknown = selected - set(decisions)
    if unknown:
        raise RoiMediaError(f"指定了未知 video_id: {sorted(unknown)}")
    rows: list[dict[str, Any]] = []
    for video_id in sorted(selected):
        decision = decisions[video_id]
        video = videos[video_id]
        source_path = resolve_data_artifact(
            str(decision.get("source_video_path") or video.get("video_path")),
            project_root,
        )
        if not source_path.is_file():
            raise RoiMediaError(f"{video_id}: 源视频不存在: {source_path}")
        if _sha256_file(source_path) != decision.get("source_sha256"):
            raise RoiMediaError(f"{video_id}: 源视频 SHA-256 与冻结决定不一致")
        video_filter, output_resolution = filter_for_decision(decision)
        rows.append(
            {
                "video_id": video_id,
                "video": video,
                "decision": decision,
                "source_path": source_path,
                "video_filter": video_filter,
                "output_resolution": output_resolution,
            }
        )

    identity = {
        "schema_version": ROI_MEDIA_SCHEMA_VERSION,
        "roi_manifest_id": manifest.get("roi_manifest_id"),
        "roi_manifest_sha256": _sha256_file(manifest_path),
        "encoding_profile": ENCODING_PROFILE,
        "selected_video_ids": sorted(selected),
    }
    media_id = f"roi-media-{hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:12]}"
    return {
        "media_id": media_id,
        "identity": identity,
        "rows": rows,
        "source_count": len(rows),
        "full_scope": len(rows) == len(decisions),
        "project_root": str(project_root.resolve()),
    }


def _materialize_one(row: Mapping[str, Any], destination: Path) -> dict[str, Any]:
    video_id = str(row["video_id"])
    source_path = Path(row["source_path"])
    output_path = destination / "videos" / f"{video_id}.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_probe = probe_video(source_path)
    expected_source = tuple(row["decision"]["source_resolution"])
    if (source_probe.width, source_probe.height) != expected_source:
        raise RoiMediaError(
            f"{video_id}: 实际源分辨率与冻结决定不一致: "
            f"{(source_probe.width, source_probe.height)} != {expected_source}"
        )

    if output_path.exists():
        output_probe = probe_video(output_path)
        validate_temporal_contract(
            source_probe, output_probe, tuple(row["output_resolution"])
        )
        reused = True
    else:
        temporary = output_path.with_name(
            f".{output_path.stem}.{os.getpid()}.partial{output_path.suffix}"
        )
        command = build_ffmpeg_command(source_path, temporary, row["decision"])
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RoiMediaError(
                    f"{video_id}: ffmpeg 失败: {(result.stderr or '').strip()}"
                )
            output_probe = probe_video(temporary)
            validate_temporal_contract(
                source_probe, output_probe, tuple(row["output_resolution"])
            )
            os.replace(temporary, output_path)
        finally:
            temporary.unlink(missing_ok=True)
        reused = False

    return {
        "source_video_id": video_id,
        "source_video_path": str(row["decision"].get("source_video_path")),
        "source_sha256": row["decision"]["source_sha256"],
        "mode": row["decision"]["mode"],
        "pixel_box": row["decision"]["pixel_box"],
        "input_resolution": list(expected_source),
        "output_resolution": [output_probe.width, output_probe.height],
        "source_frame_rate": source_probe.frame_rate,
        "source_nominal_frame_rate": source_probe.nominal_frame_rate,
        "source_frame_count": source_probe.frame_count,
        "source_duration": source_probe.duration,
        "frame_rate": output_probe.frame_rate,
        "nominal_frame_rate": output_probe.nominal_frame_rate,
        "frame_count": output_probe.frame_count,
        "duration": output_probe.duration,
        "video_filter": row["video_filter"],
        "output_path": str(output_path),
        "output_sha256": _sha256_file(output_path),
        "output_size_bytes": output_path.stat().st_size,
        "reused_existing": reused,
    }


def validate_existing_bundle(destination: Path, plan: Mapping[str, Any]) -> None:
    """Verify an already finalized bundle before treating a rerun as idempotent."""
    manifest = _load_json(destination / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("identity") != plan.get("identity"):
        raise RoiMediaError(f"拒绝复用身份不一致的既有产物: {destination}")
    videos = manifest.get("videos")
    if not isinstance(videos, list):
        raise RoiMediaError(f"既有 ROI media manifest 缺少 videos: {destination}")
    expected_ids = {str(row["video_id"]) for row in plan["rows"]}
    actual_ids = {str(row.get("source_video_id")) for row in videos if isinstance(row, dict)}
    if actual_ids != expected_ids or len(videos) != len(expected_ids):
        raise RoiMediaError("既有 ROI media manifest 覆盖范围不一致")

    project_root = Path(str(plan["project_root"])).resolve()
    for record in videos:
        raw_path = Path(str(record.get("output_path")))
        output_path = raw_path if raw_path.is_absolute() else project_root / raw_path
        if not output_path.is_file():
            raise RoiMediaError(f"既有 ROI 视频缺失: {output_path}")
        if output_path.stat().st_size != record.get("output_size_bytes"):
            raise RoiMediaError(f"既有 ROI 视频大小发生变化: {output_path}")
        if _sha256_file(output_path) != record.get("output_sha256"):
            raise RoiMediaError(f"既有 ROI 视频 SHA-256 发生变化: {output_path}")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise RoiMediaError("既有 ROI media manifest 缺少 artifacts")
    for name in ("video_meta.roi.json", "validation_report.json"):
        path = destination / name
        expected_hash = (artifacts.get(name) or {}).get("sha256")
        if not path.is_file() or _sha256_file(path) != expected_hash:
            raise RoiMediaError(f"既有 ROI media artifact 哈希无效: {name}")


def materialize_plan(
    plan: Mapping[str, Any],
    output_root: Path,
    *,
    workers: int = 2,
) -> Path:
    if workers < 1:
        raise RoiMediaError("workers 必须至少为 1")
    destination = output_root / str(plan["media_id"])
    final_manifest = destination / "manifest.json"
    if final_manifest.exists():
        validate_existing_bundle(destination, plan)
        return destination
    destination.mkdir(parents=True, exist_ok=True)

    generated: dict[str, dict[str, Any]] = {}
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {}
    try:
        futures = {
            executor.submit(_materialize_one, row, destination): row["video_id"]
            for row in plan["rows"]
        }
        for future in as_completed(futures):
            video_id = str(futures[future])
            try:
                generated[video_id] = future.result()
            except Exception as exc:
                for pending in futures:
                    pending.cancel()
                raise RoiMediaError(f"{video_id}: ROI 视频物化失败: {exc}") from exc
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    derived_metadata: list[dict[str, Any]] = []
    project_root = Path(str(plan["project_root"])).resolve()
    for row in plan["rows"]:
        video_id = str(row["video_id"])
        artifact = generated[video_id]
        absolute_output = Path(str(artifact["output_path"])).resolve()
        try:
            portable_output = str(absolute_output.relative_to(project_root))
        except ValueError:
            portable_output = str(absolute_output)
        artifact["output_path"] = portable_output
        derived = dict(row["video"])
        derived["original_video_path"] = derived.get("video_path")
        derived["video_path"] = portable_output
        derived["width"], derived["height"] = artifact["output_resolution"]
        derived["roi_provenance"] = {
            "roi_media_id": plan["media_id"],
            "roi_manifest_id": plan["identity"]["roi_manifest_id"],
            "mode": artifact["mode"],
            "pixel_box": artifact["pixel_box"],
            "output_sha256": artifact["output_sha256"],
        }
        derived_metadata.append(derived)

    metadata_path = destination / "video_meta.roi.json"
    metadata_path.write_bytes(_canonical_bytes(derived_metadata))
    artifacts = [generated[key] for key in sorted(generated)]
    report = {
        "schema_version": ROI_MEDIA_SCHEMA_VERSION,
        "roi_media_id": plan["media_id"],
        "source_count": len(artifacts),
        "fixed_roi_count": sum(row["mode"] == "fixed_roi" for row in artifacts),
        "no_crop_count": sum(row["mode"] == "no_crop" for row in artifacts),
        "all_source_hashes_verified": True,
        "all_temporal_contracts_verified": True,
    }
    report_path = destination / "validation_report.json"
    report_path.write_bytes(_canonical_bytes(report))
    manifest = {
        "schema_version": ROI_MEDIA_SCHEMA_VERSION,
        "roi_media_id": plan["media_id"],
        "identity": plan["identity"],
        "scope": "full" if plan["full_scope"] else "selected",
        "source_count": plan["source_count"],
        "encoding_profile": ENCODING_PROFILE,
        "videos": artifacts,
        "artifacts": {
            "video_meta.roi.json": {"sha256": _sha256_file(metadata_path)},
            "validation_report.json": {"sha256": _sha256_file(report_path)},
        },
    }
    temporary_manifest = destination / ".manifest.json.partial"
    temporary_manifest.write_bytes(_canonical_bytes(manifest))
    os.replace(temporary_manifest, final_manifest)
    return destination


def require_tools() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        raise RoiMediaError("缺少媒体工具: " + ", ".join(missing))
