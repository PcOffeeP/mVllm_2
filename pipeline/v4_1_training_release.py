"""Build an immutable tensile-vlm/v4.1 training-data release.

The release is intentionally separate from the legacy v2 ``06_merged`` flow.
It consumes the content-bound v4.1 review batch plus the complete, already
materialized development candidate set.  Human decisions override candidate
labels; only untouched ``automatic_validation`` negatives may bypass review.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_labels import (
    V4_1_LABEL_FIELDS,
    canonicalize_v4_1_labels,
    migrate_v3_to_v4_1_labels,
)
from pipeline.v4_1_review_decisions import validate_review_payload
from pipeline.v4_1_review_workflow import (
    MATERIALIZED_SCHEMA_VERSION,
    QUEUE_SCHEMA_VERSION,
    load_review_queue,
)

RELEASE_SCHEMA_VERSION = "tensile-training-release/v4.1"
QUALITY_SCHEMA_VERSION = "tensile-training-quality/v4.1"
TRAINING_CANDIDATES_SCHEMA_VERSION = "tensile-training-candidates/v4.1"
DATA_VERSION = "4.1.0"
SPLIT_NAMES = tuple(
    f"fold_{fold}_{split}"
    for fold in range(3)
    for split in ("train", "val")
)


class V4_1TrainingReleaseError(ValueError):
    """Raised when reviewed inputs cannot form a safe v4.1 release."""


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise V4_1TrainingReleaseError(f"{label}不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise V4_1TrainingReleaseError(f"{label}不是合法 JSON: {path}: {exc}") from exc


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _contract_identity(contract_path: Path) -> tuple[dict[str, Any], str]:
    contract = _read_json(contract_path, "v4.1 contract")
    if not isinstance(contract, dict) or contract.get("contract_version") != "tensile-vlm/v4.1":
        raise V4_1TrainingReleaseError("contract_version 必须是 tensile-vlm/v4.1")
    declared = contract.get("contract_hash")
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    actual = _sha256_bytes(_canonical_bytes(normalized).rstrip(b"\n"))
    if declared != actual:
        raise V4_1TrainingReleaseError("v4.1 contract_hash 自校验失败")
    return contract, sha256_file(contract_path)


def _relative_media_path(value: Any, project_root: Path, candidate_id: str) -> str:
    if not isinstance(value, str) or not value:
        raise V4_1TrainingReleaseError(f"{candidate_id}: video_path 不能为空")
    path = Path(value)
    resolved = path if path.is_absolute() else project_root / path
    try:
        return str(resolved.resolve().relative_to(project_root.resolve()))
    except ValueError as exc:
        raise V4_1TrainingReleaseError(
            f"{candidate_id}: 媒体必须位于项目目录内: {resolved}"
        ) from exc


def _verify_artifact(path_value: Any, expected_sha: Any, project_root: Path, label: str) -> Path:
    path = Path(str(path_value))
    resolved = path if path.is_absolute() else project_root / path
    if not resolved.is_file():
        raise V4_1TrainingReleaseError(f"{label}不存在: {resolved}")
    actual = sha256_file(resolved)
    if actual != expected_sha:
        raise V4_1TrainingReleaseError(
            f"{label} SHA-256 不一致: expected={expected_sha}, actual={actual}"
        )
    return resolved


def _load_materialized(
    materialized_path: Path,
    media_manifest_path: Path,
    project_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = _read_json(materialized_path, "development materialized")
    manifest = _read_json(media_manifest_path, "candidate media manifest")
    if (
        not isinstance(payload, dict)
        or not isinstance(manifest, dict)
        or payload.get("schema_version") != MATERIALIZED_SCHEMA_VERSION
        or manifest.get("schema_version") != MATERIALIZED_SCHEMA_VERSION
    ):
        raise V4_1TrainingReleaseError("candidate media schema_version 不匹配")
    artifact = (manifest.get("artifacts") or {}).get(materialized_path.name)
    if not isinstance(artifact, Mapping) or artifact.get("sha256") != sha256_file(
        materialized_path
    ):
        raise V4_1TrainingReleaseError("media manifest 未绑定 development materialized")
    if payload.get("media_id") != manifest.get("media_id"):
        raise V4_1TrainingReleaseError("materialized 与 media manifest 身份不一致")
    raw = payload.get("candidates")
    if not isinstance(raw, list) or not raw:
        raise V4_1TrainingReleaseError("development materialized candidates 为空")

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise V4_1TrainingReleaseError("materialized candidate 必须是对象")
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in seen:
            raise V4_1TrainingReleaseError(f"candidate_id 非法或重复: {candidate_id!r}")
        seen.add(candidate_id)
        if item.get("scope") != "development":
            raise V4_1TrainingReleaseError(f"{candidate_id}: scope 不是 development")
        if item.get("media_status") != "materialized_gate_passed":
            raise V4_1TrainingReleaseError(f"{candidate_id}: media gate 未通过")
        if (item.get("sampling_gate") or {}).get("status") != "passed":
            raise V4_1TrainingReleaseError(f"{candidate_id}: sampling gate 未通过")
        video = _verify_artifact(
            item.get("video_path"),
            item.get("video_sha256"),
            project_root,
            f"{candidate_id} video",
        )
        frames = item.get("frame_artifacts")
        mapping = item.get("actual_frame_mapping")
        if not isinstance(frames, list) or not frames:
            raise V4_1TrainingReleaseError(f"{candidate_id}: frame_artifacts 为空")
        if not isinstance(mapping, list) or len(mapping) != len(frames):
            raise V4_1TrainingReleaseError(f"{candidate_id}: 帧映射与帧图数量不一致")
        verified_frames: list[dict[str, Any]] = []
        timestamps: list[float] = []
        for index, (frame, mapped) in enumerate(zip(frames, mapping, strict=True)):
            if not isinstance(frame, Mapping) or not isinstance(mapped, Mapping):
                raise V4_1TrainingReleaseError(f"{candidate_id}: 帧证据格式非法")
            frame_path = _verify_artifact(
                frame.get("path"),
                frame.get("sha256"),
                project_root,
                f"{candidate_id} frame[{index}]",
            )
            timestamp = mapped.get("timestamp")
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise V4_1TrainingReleaseError(f"{candidate_id}: 帧时间戳非法")
            timestamps.append(float(timestamp))
            verified_frames.append(
                {
                    "path": str(frame_path.resolve().relative_to(project_root.resolve())),
                    "sha256": frame["sha256"],
                }
            )
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise V4_1TrainingReleaseError(f"{candidate_id}: 帧时间戳必须严格递增")
        candidates.append(
            {
                **item,
                "_release_video_path": str(video.resolve().relative_to(project_root.resolve())),
                "_release_frames": verified_frames,
                "_sampled_timestamps": timestamps,
            }
        )
    return manifest, candidates


def _load_splits(splits_dir: Path) -> tuple[dict[str, set[str]], dict[str, str]]:
    splits: dict[str, set[str]] = {}
    hashes: dict[str, str] = {}
    for name in SPLIT_NAMES:
        path = splits_dir / f"{name}.json"
        payload = _read_json(path, name)
        ids = payload.get("video_ids") if isinstance(payload, Mapping) else None
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise V4_1TrainingReleaseError(f"{name}: video_ids 非法")
        if len(ids) != len(set(ids)):
            raise V4_1TrainingReleaseError(f"{name}: video_ids 重复")
        splits[name] = set(ids)
        hashes[path.name] = sha256_file(path)
    test_path = splits_dir / "test.json"
    test_payload = _read_json(test_path, "test split")
    test_ids = (
        set(test_payload.get("video_ids", []))
        if isinstance(test_payload, Mapping)
        else set()
    )
    hashes[test_path.name] = sha256_file(test_path)
    for fold in range(3):
        train = splits[f"fold_{fold}_train"]
        val = splits[f"fold_{fold}_val"]
        if train & val:
            raise V4_1TrainingReleaseError(f"fold_{fold}: train/val 源视频重叠")
        if (train | val) & test_ids:
            raise V4_1TrainingReleaseError(f"fold_{fold}: development 与 test 源视频重叠")
    return splits, hashes


def _dataset_row(candidate: Mapping[str, Any], labels: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    analysis = contract.get("analysis")
    if not isinstance(analysis, Mapping):
        raise V4_1TrainingReleaseError("contract.analysis 缺失")
    system_prompt = analysis.get("system_prompt")
    user_prompt = analysis.get("user_prompt")
    if not isinstance(system_prompt, str) or not isinstance(user_prompt, str):
        raise V4_1TrainingReleaseError("contract analysis prompt 缺失")
    target = {field: labels[field] for field in V4_1_LABEL_FIELDS}
    return {
        "videos": [candidate["_release_video_path"]],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"<video>\n{user_prompt}"},
            {
                "role": "assistant",
                "content": json.dumps(
                    target,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            },
        ],
    }


def _registry() -> dict[str, Any]:
    common = {
        "formatting": "sharegpt",
        "columns": {"messages": "messages", "videos": "videos"},
        "tags": {
            "role_tag": "role",
            "content_tag": "content",
            "user_tag": "user",
            "assistant_tag": "assistant",
            "observation_tag": "observation",
            "function_tag": "function_call",
            "system_tag": "system",
        },
    }
    result: dict[str, Any] = {}
    for fold in range(3):
        for split, directory in (("train", "train"), ("val", "validation")):
            result[f"tensile_v4_1_fold{fold}_{split}"] = {
                **common,
                "file_name": f"datasets/{directory}/fold_{fold}.json",
            }
    return result


def _distribution(rows: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(
        "null" if (row.get("labels") or {}).get(field) is None else str((row.get("labels") or {}).get(field))
        for row in rows
    )
    return dict(sorted(counts.items()))


def _write_release(
    release_dir: Path,
    files: Mapping[str, bytes],
    manifest: Mapping[str, Any],
) -> None:
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    if release_dir.exists():
        stored = _read_json(
            release_dir / "manifest" / "release_manifest.json",
            "existing release manifest",
        )
        if stored != manifest:
            raise V4_1TrainingReleaseError(f"拒绝覆盖已有发布: {release_dir}")
        for relative, content in files.items():
            path = release_dir / relative
            if not path.is_file() or path.read_bytes() != content:
                raise V4_1TrainingReleaseError(f"已有发布文件漂移: {path}")
        return

    staging = Path(
        tempfile.mkdtemp(prefix=f".{release_dir.name}.", dir=release_dir.parent)
    )
    try:
        for relative, content in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        manifest_path = staging / "manifest" / "release_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(_pretty_bytes(manifest))
        os.replace(staging, release_dir)
    finally:
        if staging.exists():
            for path in sorted(staging.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging.rmdir()


def build_v4_1_training_release(
    *,
    project_root: Path,
    materialized_path: Path,
    media_manifest_path: Path,
    queue_path: Path,
    decisions_path: Path,
    contract_path: Path,
    splits_dir: Path,
    releases_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    """Validate all inputs and publish one deterministic immutable release."""
    project_root = Path(project_root).resolve()
    contract, contract_file_sha256 = _contract_identity(contract_path)
    media_manifest, candidates = _load_materialized(
        materialized_path, media_manifest_path, project_root
    )
    queue_identity, reviewed_candidates = load_review_queue(
        queue_path,
        project_root=project_root,
    )
    reviewed_index = {item["candidate_id"]: item for item in reviewed_candidates}

    decisions = _read_json(decisions_path, "frozen v4.1 decisions")
    if not isinstance(decisions, dict):
        raise V4_1TrainingReleaseError("冻结决定必须是对象")
    try:
        validate_review_payload(decisions)
    except ValueError as exc:
        raise V4_1TrainingReleaseError(f"冻结决定校验失败: {exc}") from exc
    records = decisions["decisions"]
    decision_index = {item["clip_id"]: item for item in records}
    if set(decision_index) != set(reviewed_index):
        missing = sorted(set(reviewed_index) - set(decision_index))
        extra = sorted(set(decision_index) - set(reviewed_index))
        raise V4_1TrainingReleaseError(
            f"冻结决定未完整覆盖审查队列: missing={missing[:5]}, extra={extra[:5]}"
        )

    candidate_index = {item["candidate_id"]: item for item in candidates}
    finalized: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for candidate_id, candidate in candidate_index.items():
        decision = decision_index.get(candidate_id)
        if decision is not None:
            if decision.get("source_video") != candidate.get("source_video"):
                raise V4_1TrainingReleaseError(f"{candidate_id}: source_video 绑定漂移")
            if (decision.get("evidence") or {}).get("media_sha256") != candidate.get(
                "video_sha256"
            ):
                raise V4_1TrainingReleaseError(f"{candidate_id}: decision media SHA 漂移")
            if decision.get("system_proposed_labels") != reviewed_index[candidate_id].get(
                "candidate_v4_labels"
            ):
                raise V4_1TrainingReleaseError(f"{candidate_id}: 系统建议与队列漂移")
            status = decision["review_status"]
            if status in {"dropped", "needs_regenerate"}:
                excluded.append(
                    {
                        "candidate_id": candidate_id,
                        "source_video": candidate["source_video"],
                        "review_status": status,
                        "reviewer_notes": decision.get("reviewer_notes") or "",
                    }
                )
                continue
            labels = canonicalize_v4_1_labels(decision["effective_labels"])
            label_source = "human_review"
            review_status = status
        else:
            if candidate.get("review_disposition") != "automatic_validation":
                raise V4_1TrainingReleaseError(
                    f"{candidate_id}: manual_required 候选缺少人工决定"
                )
            try:
                labels = migrate_v3_to_v4_1_labels(
                    candidate.get("candidate_v3_labels")
                )
            except (TypeError, ValueError) as exc:
                raise V4_1TrainingReleaseError(
                    f"{candidate_id}: 自动候选标签非法: {exc}"
                ) from exc
            if labels != {
                "clip_state": "未断裂",
                "fracture_mechanism": None,
                "fracture_site": None,
                "special_case": None,
            }:
                raise V4_1TrainingReleaseError(
                    f"{candidate_id}: 未审自动候选不是普通未断裂"
                )
            label_source = "automatic_validation"
            review_status = None

        finalized.append(
            {
                "candidate_id": candidate_id,
                "source_video": candidate["source_video"],
                "video_path": candidate["_release_video_path"],
                "video_sha256": candidate["video_sha256"],
                "frames": candidate["_release_frames"],
                "actual_sampled_timestamps": candidate["_sampled_timestamps"],
                "processor_fingerprint": candidate.get("processor_fingerprint"),
                "labels": labels,
                "label_source": label_source,
                "review_status": review_status,
                "review_batch_id": decisions["batch_id"] if decision is not None else None,
            }
        )

    splits, split_hashes = _load_splits(splits_dir)
    development_sources = {row["source_video"] for row in finalized}
    for fold in range(3):
        assigned = splits[f"fold_{fold}_train"] | splits[f"fold_{fold}_val"]
        if development_sources - assigned:
            raise V4_1TrainingReleaseError(
                f"fold_{fold}: 存在未分配 development 源视频: "
                f"{sorted(development_sources - assigned)[:5]}"
            )

    candidate_rows = {
        "schema_version": TRAINING_CANDIDATES_SCHEMA_VERSION,
        "contract_version": contract["contract_version"],
        "contract_hash": contract["contract_hash"],
        "media_id": media_manifest["media_id"],
        "queue_id": queue_identity["queue_id"],
        "review_batch_id": decisions["batch_id"],
        "candidate_count": len(finalized),
        "excluded_count": len(excluded),
        "candidates": finalized,
        "excluded": excluded,
    }
    files: dict[str, bytes] = {
        "metadata/training_candidates.json": _pretty_bytes(candidate_rows),
        "dataset_info.json": _pretty_bytes(_registry()),
    }
    split_counts: dict[str, int] = {}
    for fold in range(3):
        for split, directory in (("train", "train"), ("val", "validation")):
            name = f"fold_{fold}_{split}"
            source_ids = splits[name]
            selected = [
                row
                for row in finalized
                if row["source_video"] in source_ids
            ]
            dataset = [
                _dataset_row(candidate_index[row["candidate_id"]], row["labels"], contract)
                for row in selected
            ]
            split_counts[name] = len(dataset)
            files[f"datasets/{directory}/fold_{fold}.json"] = _pretty_bytes(dataset)

    quality = {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "status": "passed",
        "error_count": 0,
        "warning_count": 0,
        "counts": {
            "materialized_candidates": len(candidates),
            "reviewed_candidates": len(records),
            "automatic_unreviewed_candidates": sum(
                row["label_source"] == "automatic_validation" for row in finalized
            ),
            "published_candidates": len(finalized),
            "excluded_candidates": len(excluded),
            "human_approved": sum(
                row["review_status"] == "approved" for row in finalized
            ),
            "human_corrected": sum(
                row["review_status"] == "corrected" for row in finalized
            ),
            "splits": split_counts,
        },
        "distributions": {
            field: _distribution(finalized, field) for field in V4_1_LABEL_FIELDS
        },
        "checks": {
            "contract_bound": True,
            "media_manifest_bound": True,
            "all_media_hashes_verified": True,
            "review_queue_fully_decided": True,
            "only_stable_negatives_auto_admitted": True,
            "source_level_split_isolation": True,
            "frame_window_labels_are_authoritative": True,
        },
    }
    files["reports/quality_report.json"] = _pretty_bytes(quality)

    seed = {
        "data_version": DATA_VERSION,
        "contract_hash": contract["contract_hash"],
        "contract_file_sha256": contract_file_sha256,
        "materialized_sha256": sha256_file(materialized_path),
        "media_manifest_sha256": sha256_file(media_manifest_path),
        "queue_sha256": sha256_file(queue_path),
        "decisions_sha256": sha256_file(decisions_path),
        "split_hashes": split_hashes,
        "training_candidates_sha256": _sha256_bytes(
            files["metadata/training_candidates.json"]
        ),
    }
    release_digest = _sha256_bytes(_canonical_bytes(seed))[:12]
    release_id = f"v{DATA_VERSION}-{release_digest}"
    file_manifest = [
        {
            "path": relative,
            "size_bytes": len(content),
            "sha256": _sha256_bytes(content),
        }
        for relative, content in sorted(files.items())
    ]
    manifest = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "release_id": release_id,
        "status": "training_ready",
        "immutable": True,
        "contract_version": contract["contract_version"],
        "contract_hash": contract["contract_hash"],
        "label_semantics": "frame_window_authoritative",
        "source_review_batch_id": decisions["batch_id"],
        "source_queue_id": queue_identity["queue_id"],
        "source_media_id": media_manifest["media_id"],
        "counts": quality["counts"],
        "provenance": seed,
        "files": file_manifest,
    }
    release_dir = Path(releases_dir) / release_id
    _write_release(release_dir, files, manifest)
    return release_dir, manifest
