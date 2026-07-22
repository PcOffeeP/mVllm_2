"""Validate and freeze manually reviewed source-video ROI decisions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from pipeline.scripts.roi_annotation_app import (
    MODE_FIXED,
    MODE_NO_CROP,
    ROI_POLICY_VERSION,
    SCHEMA_VERSION,
    STATUS_APPROVED,
    TARGET_ASPECT_HEIGHT,
    TARGET_ASPECT_RATIO,
    TARGET_ASPECT_WIDTH,
    VISIBILITY_CHECK_KEYS,
    _normalized_from_pixel_box,
    normalized_box,
    pixel_box,
    source_state,
)

ROI_MANIFEST_SCHEMA_VERSION = "tensile-roi-manifest/v1"


class RoiManifestError(ValueError):
    """ROI decisions cannot be safely frozen."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RoiManifestError(f"文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RoiManifestError(f"JSON 无法解析: {path}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _content_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _records(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get(key, [])
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise RoiManifestError(f"{key} 必须是对象列表")
    return payload


def _video_index(payload: Any) -> dict[str, dict[str, Any]]:
    rows = _records(payload, "videos")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        video_id = row.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise RoiManifestError("视频 metadata 存在无效 video_id")
        if video_id in result:
            raise RoiManifestError(f"视频 metadata 存在重复 video_id: {video_id}")
        result[video_id] = row
    return result


def _decision_index(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        raise RoiManifestError("ROI 文件必须是包含 decisions 列表的对象")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RoiManifestError(f"ROI schema_version 必须是 {SCHEMA_VERSION}")
    if payload.get("roi_policy_version") != ROI_POLICY_VERSION:
        raise RoiManifestError(f"roi_policy_version 必须是 {ROI_POLICY_VERSION}")
    result: dict[str, dict[str, Any]] = {}
    for decision in payload["decisions"]:
        if not isinstance(decision, dict):
            raise RoiManifestError("ROI decisions 中存在非对象记录")
        video_id = decision.get("source_video_id")
        if not isinstance(video_id, str) or not video_id:
            raise RoiManifestError("ROI decision 缺少有效 source_video_id")
        if video_id in result:
            raise RoiManifestError(f"ROI decisions 存在重复视频: {video_id}")
        result[video_id] = decision
    return result


def _resolve_source_path(
    decision: Mapping[str, Any],
    video: Mapping[str, Any],
    project_root: Path,
) -> Path:
    raw = (
        decision.get("source_video_path")
        or video.get("video_path")
        or f"data/01_videos/{video['video_id']}.mp4"
    )
    path = Path(str(raw))
    return path if path.is_absolute() else project_root / path


def _validate_decision(
    decision: Mapping[str, Any],
    video: Mapping[str, Any],
    project_root: Path,
    *,
    verify_source_hash: bool,
) -> dict[str, Any]:
    video_id = video["video_id"]
    if decision.get("review_status") != STATUS_APPROVED:
        raise RoiManifestError(f"{video_id}: ROI 尚未 approved")
    if decision.get("roi_policy_version") != ROI_POLICY_VERSION:
        raise RoiManifestError(
            f"{video_id}: ROI 策略版本不是 {ROI_POLICY_VERSION}，必须重新复审"
        )
    if decision.get("target_aspect_ratio") != TARGET_ASPECT_RATIO:
        raise RoiManifestError(f"{video_id}: target_aspect_ratio 必须是 {TARGET_ASPECT_RATIO}")
    mode = decision.get("mode")
    if mode not in {MODE_FIXED, MODE_NO_CROP}:
        raise RoiManifestError(f"{video_id}: 非法 ROI mode")
    margins = decision.get("margins")
    if not isinstance(margins, Mapping):
        raise RoiManifestError(f"{video_id}: 缺少 margins")
    try:
        normalized_box(margins)
    except ValueError as exc:
        raise RoiManifestError(f"{video_id}: {exc}") from exc
    if mode == MODE_FIXED and all(value == 0.0 for value in margins.values()):
        raise RoiManifestError(f"{video_id}: fixed_roi 不能使用全零边距")
    if mode == MODE_NO_CROP and any(value != 0.0 for value in margins.values()):
        raise RoiManifestError(f"{video_id}: no_crop 必须使用全零边距")

    resolution = decision.get("source_resolution")
    if (
        not isinstance(resolution, list)
        or len(resolution) != 2
        or any(type(value) is not int or value < 2 for value in resolution)
    ):
        raise RoiManifestError(f"{video_id}: source_resolution 无效")
    expected_pixel = pixel_box(margins, resolution[0], resolution[1])
    expected_normalized = _normalized_from_pixel_box(
        expected_pixel, resolution[0], resolution[1]
    )
    if decision.get("normalized_box") != expected_normalized:
        raise RoiManifestError(f"{video_id}: normalized_box 与 margins 不一致")
    if decision.get("pixel_box") != expected_pixel:
        raise RoiManifestError(f"{video_id}: pixel_box 与 margins/source_resolution 不一致")
    if mode == MODE_FIXED:
        if decision.get("interaction_mode") != "drag_box":
            raise RoiManifestError(f"{video_id}: fixed_roi 必须由拖拽裁剪框确认")
        if decision.get("aspect_ratio_strategy") != "crop_exact":
            raise RoiManifestError(f"{video_id}: fixed_roi 必须使用 crop_exact")
        if (
            expected_pixel["width"] * TARGET_ASPECT_HEIGHT
            != expected_pixel["height"] * TARGET_ASPECT_WIDTH
        ):
            raise RoiManifestError(f"{video_id}: fixed_roi 像素框不是精确 {TARGET_ASPECT_RATIO}")
    else:
        if decision.get("interaction_mode") != "no_crop":
            raise RoiManifestError(f"{video_id}: no_crop 的 interaction_mode 无效")
        if decision.get("aspect_ratio_strategy") != "pad_to_target":
            raise RoiManifestError(f"{video_id}: no_crop 必须使用 pad_to_target")

    timestamps = decision.get("reviewed_timestamps")
    if not isinstance(timestamps, list) or not timestamps:
        raise RoiManifestError(f"{video_id}: 缺少已检查的关键时间点")
    visibility = decision.get("visibility_checks")
    if not isinstance(visibility, Mapping):
        raise RoiManifestError(f"{video_id}: 缺少 visibility_checks")
    missing_visibility = [
        key for key in VISIBILITY_CHECK_KEYS if visibility.get(key) is not True
    ]
    if missing_visibility:
        raise RoiManifestError(
            f"{video_id}: 可见性检查未全部通过: {', '.join(missing_visibility)}"
        )

    source_path = _resolve_source_path(decision, video, project_root)
    if not source_path.is_file():
        raise RoiManifestError(f"{video_id}: 源视频不存在: {source_path}")
    current_state = source_state(source_path)
    if decision.get("source_size_bytes") != current_state["source_size_bytes"]:
        raise RoiManifestError(f"{video_id}: 源视频大小已变化")
    if decision.get("source_mtime_ns") != current_state["source_mtime_ns"]:
        raise RoiManifestError(f"{video_id}: 源视频修改时间已变化")
    recorded_hash = decision.get("source_sha256")
    if not isinstance(recorded_hash, str) or len(recorded_hash) != 64:
        raise RoiManifestError(f"{video_id}: source_sha256 无效")
    if verify_source_hash and _sha256_file(source_path) != recorded_hash:
        raise RoiManifestError(f"{video_id}: 源视频 SHA-256 已变化")
    return {
        "source_video_id": video_id,
        "source_video_path": str(decision.get("source_video_path")),
        "source_sha256": recorded_hash,
        "mode": mode,
        "pixel_box": expected_pixel,
        "visibility_checks": {
            key: visibility[key] for key in VISIBILITY_CHECK_KEYS
        },
    }


def build_roi_manifest_bundle(
    *,
    decisions_path: Path,
    video_metadata_path: Path,
    test_manifest_path: Path,
    project_root: Path,
    generated_at: str | None = None,
    verify_source_hashes: bool = True,
) -> dict[str, Any]:
    decisions_payload = _load_json(decisions_path)
    videos = _video_index(_load_json(video_metadata_path))
    decisions = _decision_index(decisions_payload)
    test_manifest = _load_json(test_manifest_path)
    if not isinstance(test_manifest, dict) or not isinstance(
        test_manifest.get("video_ids"), list
    ):
        raise RoiManifestError("test manifest 必须包含 video_ids 列表")
    test_ids = set(test_manifest["video_ids"])
    all_ids = set(videos)
    if test_ids - all_ids:
        raise RoiManifestError(f"test manifest 包含未知视频: {sorted(test_ids - all_ids)}")
    missing = all_ids - set(decisions)
    extra = set(decisions) - all_ids
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"缺少 {len(missing)} 条: {sorted(missing)[:10]}")
        if extra:
            parts.append(f"多出 {len(extra)} 条: {sorted(extra)[:10]}")
        raise RoiManifestError("ROI 决定未完整覆盖视频清单；" + "；".join(parts))

    validation_rows = [
        _validate_decision(
            decisions[video_id],
            videos[video_id],
            project_root,
            verify_source_hash=verify_source_hashes,
        )
        for video_id in sorted(all_ids)
    ]
    development_ids = all_ids - test_ids
    development_decisions = [
        decisions[video_id] for video_id in sorted(development_ids)
    ]
    test_decisions = [decisions[video_id] for video_id in sorted(test_ids)]
    identity = {
        "schema_version": ROI_MANIFEST_SCHEMA_VERSION,
        "roi_policy_version": ROI_POLICY_VERSION,
        "decisions_sha256": _sha256_file(decisions_path),
        "video_metadata_sha256": _sha256_file(video_metadata_path),
        "test_manifest_sha256": _sha256_file(test_manifest_path),
        "source_sha256": {
            row["source_video_id"]: row["source_sha256"] for row in validation_rows
        },
    }
    manifest_id = f"roi-manifest-{_content_hash(identity)[:12]}"
    frozen = {
        **decisions_payload,
        "frozen_schema_version": ROI_MANIFEST_SCHEMA_VERSION,
        "roi_manifest_id": manifest_id,
    }
    development = {
        "schema_version": ROI_MANIFEST_SCHEMA_VERSION,
        "roi_manifest_id": manifest_id,
        "scope": "development",
        "source_count": len(development_ids),
        "decisions": development_decisions,
    }
    test_audit = {
        "schema_version": ROI_MANIFEST_SCHEMA_VERSION,
        "roi_manifest_id": manifest_id,
        "scope": "test_audit",
        "source_count": len(test_ids),
        "decisions": test_decisions,
    }
    mode_counts = Counter(row["mode"] for row in validation_rows)
    report = {
        "roi_manifest_id": manifest_id,
        "total_source_count": len(all_ids),
        "development_source_count": len(development_ids),
        "test_source_count": len(test_ids),
        "approved_count": len(validation_rows),
        "mode_counts": dict(sorted(mode_counts.items())),
        "source_hashes_verified": verify_source_hashes,
    }
    artifacts = {
        "roi_decisions.frozen.json": frozen,
        "development_roi.json": development,
        "test_roi_audit.json": test_audit,
        "validation_report.json": report,
    }
    manifest = {
        "schema_version": ROI_MANIFEST_SCHEMA_VERSION,
        "roi_manifest_id": manifest_id,
        "roi_policy_version": ROI_POLICY_VERSION,
        "inputs": identity,
        "split_guard": {
            "development_source_count": len(development_ids),
            "test_source_count": len(test_ids),
            "overlap_count": 0,
        },
        "artifacts": {
            name: {"sha256": _content_hash(payload)}
            for name, payload in sorted(artifacts.items())
        },
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }
    return {"manifest.json": manifest, **artifacts}


def write_roi_manifest_bundle(
    output_root: Path, bundle: Mapping[str, Any]
) -> tuple[Path, bool]:
    manifest = bundle.get("manifest.json")
    if not isinstance(manifest, Mapping):
        raise RoiManifestError("bundle 缺少 manifest.json")
    manifest_id = manifest.get("roi_manifest_id")
    if not isinstance(manifest_id, str) or not manifest_id.startswith("roi-manifest-"):
        raise RoiManifestError("roi_manifest_id 无效")
    destination = Path(output_root) / manifest_id
    if destination.exists():
        for name, payload in bundle.items():
            path = destination / name
            if not path.exists():
                raise FileExistsError(f"拒绝覆盖已有 ROI manifest: {destination}")
            if name == "manifest.json":
                existing = _load_json(path)
                existing_without_time = dict(existing)
                requested_without_time = dict(payload)
                existing_without_time.pop("generated_at", None)
                requested_without_time.pop("generated_at", None)
                identical = existing_without_time == requested_without_time
            else:
                identical = path.read_bytes() == _canonical_bytes(payload)
            if not identical:
                raise FileExistsError(f"拒绝覆盖已有 ROI manifest: {destination}")
        return destination, False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{manifest_id}.", dir=destination.parent))
    try:
        for name, payload in bundle.items():
            (temp_dir / name).write_bytes(_canonical_bytes(payload))
        os.replace(temp_dir, destination)
    finally:
        if temp_dir.exists():
            for child in temp_dir.iterdir():
                child.unlink()
            temp_dir.rmdir()
    return destination, True
