"""Queue-bound, resumable workflow helpers for v3 human review."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.v3_labels import canonicalize_v3_labels
from pipeline.v3_review_decisions import (
    REVIEW_SCHEMA_VERSION,
    build_review_payload,
    canonical_json_bytes,
    save_review_payload,
    validate_review_payload,
)

MEDIA_SCHEMA_VERSION = "tensile-v3-candidate-media/v1"
WORKSPACE_SCHEMA_VERSION = "tensile-review-workspace/v3"
MANUAL_REVIEW_STATES = frozenset({"发生断裂", "已断裂"})
TERMINAL_REVIEW_STATUSES = frozenset(
    {"approved", "corrected", "dropped", "needs_regenerate"}
)


class V3ReviewWorkflowError(ValueError):
    """The review queue, draft, or frozen batch is unsafe to consume."""


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise V3ReviewWorkflowError(f"{label}不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise V3ReviewWorkflowError(f"{label}不是合法 JSON: {path}: {exc}") from exc


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V3ReviewWorkflowError(f"{field} 必须是非空字符串")
    return value.strip()


def _resolve_path(value: Any, project_root: Path, field: str) -> Path:
    path = Path(_nonempty(value, field))
    return path if path.is_absolute() else project_root / path


def _candidate_ids_sha256(candidate_ids: Iterable[str]) -> str:
    encoded = json.dumps(
        list(candidate_ids), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _validate_candidate_identity(candidate: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    candidate_id = _nonempty(candidate.get("candidate_id"), "candidate_id")
    _nonempty(candidate.get("source_video"), f"{candidate_id}.source_video")
    if candidate.get("scope") != "development":
        raise V3ReviewWorkflowError(f"{candidate_id}: scope 必须是 development")
    if candidate.get("review_disposition") != "manual_required":
        raise V3ReviewWorkflowError(
            f"{candidate_id}: review_disposition 必须是 manual_required"
        )
    try:
        labels = canonicalize_v3_labels(candidate.get("candidate_v3_labels"))
    except (TypeError, ValueError) as exc:
        raise V3ReviewWorkflowError(f"{candidate_id}: v3 标签非法: {exc}") from exc
    if labels["clip_state"] not in MANUAL_REVIEW_STATES:
        raise V3ReviewWorkflowError(
            f"{candidate_id}: 非人工复检状态 {labels['clip_state']}"
        )
    return candidate_id, labels


def _validate_selected_media(
    candidate: Mapping[str, Any], project_root: Path
) -> dict[str, Any]:
    candidate_id, labels = _validate_candidate_identity(candidate)
    video_path = _resolve_path(candidate.get("video_path"), project_root, "video_path")
    expected_video_sha256 = _nonempty(
        candidate.get("video_sha256"), f"{candidate_id}.video_sha256"
    )
    if not video_path.is_file():
        raise V3ReviewWorkflowError(f"{candidate_id}: 视频不存在: {video_path}")
    if sha256_file(video_path) != expected_video_sha256:
        raise V3ReviewWorkflowError(f"{candidate_id}: 视频 SHA-256 不一致")

    mapping = candidate.get("actual_frame_mapping")
    if not isinstance(mapping, list) or not mapping:
        raise V3ReviewWorkflowError(
            f"{candidate_id}: actual_frame_mapping 必须是非空列表"
        )
    timestamps: list[float] = []
    for index, item in enumerate(mapping):
        if not isinstance(item, Mapping):
            raise V3ReviewWorkflowError(
                f"{candidate_id}: 第 {index} 个帧映射不是对象"
            )
        timestamp = item.get("timestamp")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise V3ReviewWorkflowError(
                f"{candidate_id}: 第 {index} 个 timestamp 非法"
            )
        timestamps.append(float(timestamp))

    frame_artifacts = candidate.get("frame_artifacts")
    if not isinstance(frame_artifacts, list) or not frame_artifacts:
        raise V3ReviewWorkflowError(
            f"{candidate_id}: frame_artifacts 必须是非空列表"
        )
    frames: list[dict[str, str]] = []
    for index, artifact in enumerate(frame_artifacts):
        if not isinstance(artifact, Mapping):
            raise V3ReviewWorkflowError(
                f"{candidate_id}: 第 {index} 个帧 artifact 不是对象"
            )
        frame_path = _resolve_path(
            artifact.get("path"),
            project_root,
            f"{candidate_id}.frame_artifacts[{index}].path",
        )
        expected = _nonempty(
            artifact.get("sha256"),
            f"{candidate_id}.frame_artifacts[{index}].sha256",
        )
        if not frame_path.is_file() or sha256_file(frame_path) != expected:
            raise V3ReviewWorkflowError(
                f"{candidate_id}: 帧图缺失或 SHA-256 不一致: {frame_path}"
            )
        frames.append({"path": str(frame_path), "sha256": expected})

    return {
        **candidate,
        "candidate_v3_labels": labels,
        "_resolved_video_path": str(video_path),
        "_resolved_frames": frames,
        "_actual_sampled_timestamps": timestamps,
    }


def load_review_queue(
    queue_path: Path,
    *,
    manifest_path: Path,
    project_root: Path,
    candidate_ids: Iterable[str] | None = None,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Bind a manual-review queue to its manifest and selected media bytes."""
    queue_path = Path(queue_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    project_root = Path(project_root).resolve()
    queue = _load_json(queue_path, "review queue")
    manifest = _load_json(manifest_path, "candidate media manifest")
    if not isinstance(queue, Mapping) or not isinstance(manifest, Mapping):
        raise V3ReviewWorkflowError("review queue 与 manifest 都必须是对象")
    if queue.get("schema_version") != MEDIA_SCHEMA_VERSION:
        raise V3ReviewWorkflowError(
            f"review queue schema_version 必须是 {MEDIA_SCHEMA_VERSION}"
        )
    if manifest.get("schema_version") != MEDIA_SCHEMA_VERSION:
        raise V3ReviewWorkflowError(
            f"manifest schema_version 必须是 {MEDIA_SCHEMA_VERSION}"
        )
    media_id = _nonempty(queue.get("media_id"), "media_id")
    if manifest.get("media_id") != media_id or manifest.get("media_generated") is not True:
        raise V3ReviewWorkflowError("review queue 与完整媒体 manifest 身份不一致")
    if queue.get("scope") != "development":
        raise V3ReviewWorkflowError("review queue scope 必须是 development")
    artifact = (manifest.get("artifacts") or {}).get(queue_path.name)
    if not isinstance(artifact, Mapping) or artifact.get("sha256") != sha256_file(
        queue_path
    ):
        raise V3ReviewWorkflowError("review queue SHA-256 未被 manifest 正确绑定")

    candidates = queue.get("candidates")
    if not isinstance(candidates, list):
        raise V3ReviewWorkflowError("review queue candidates 必须是列表")
    if (manifest.get("counts") or {}).get("development_manual_review") != len(
        candidates
    ):
        raise V3ReviewWorkflowError("review queue 数量与 manifest 不一致")

    raw_index: dict[str, Mapping[str, Any]] = {}
    full_ids: list[str] = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            raise V3ReviewWorkflowError("review queue candidates 中存在非对象项")
        candidate_id, _ = _validate_candidate_identity(raw)
        if candidate_id in raw_index:
            raise V3ReviewWorkflowError(
                f"review queue candidate_id 重复: {candidate_id}"
            )
        raw_index[candidate_id] = raw
        full_ids.append(candidate_id)

    requested = list(candidate_ids or [])
    if len(requested) != len(set(requested)):
        raise V3ReviewWorkflowError("candidate_ids 不能重复")
    missing = [item for item in requested if item not in raw_index]
    if missing:
        raise V3ReviewWorkflowError(f"指定 candidate_id 不在队列中: {missing}")
    selected_raw = [raw_index[item] for item in requested] if requested else candidates
    if limit is not None:
        if limit <= 0:
            raise V3ReviewWorkflowError("limit 必须大于 0")
        selected_raw = selected_raw[:limit]
    if not selected_raw:
        raise V3ReviewWorkflowError("选定复检队列不能为空")

    selected = [
        _validate_selected_media(item, project_root) for item in selected_raw
    ]
    selected_ids = [item["candidate_id"] for item in selected]
    identity = {
        "media_schema_version": MEDIA_SCHEMA_VERSION,
        "media_id": media_id,
        "queue_path": str(queue_path),
        "queue_sha256": sha256_file(queue_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "full_queue_count": len(candidates),
        "full_candidate_ids_sha256": _candidate_ids_sha256(full_ids),
        "selected_candidate_ids": selected_ids,
        "selected_candidate_ids_sha256": _candidate_ids_sha256(selected_ids),
    }
    return identity, selected


def load_reference_records(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = _load_json(Path(path), "历史审查参考")
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(records, list):
        raise V3ReviewWorkflowError("历史审查参考缺少 records 列表")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise V3ReviewWorkflowError("历史审查参考 records 中存在非对象项")
        reference_id = _nonempty(
            record.get("reference_record_id"), "reference_record_id"
        )
        if reference_id in result:
            raise V3ReviewWorkflowError(f"历史参考 ID 重复: {reference_id}")
        result[reference_id] = dict(record)
    return result


def historical_context(
    candidate: Mapping[str, Any],
    reference_index: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
    match = candidate.get("reference_match")
    reference_ids: list[str] = []
    if isinstance(match, Mapping):
        if isinstance(match.get("reference_ids"), list):
            reference_ids.extend(
                item for item in match["reference_ids"] if isinstance(item, str)
            )
        if isinstance(match.get("references"), list):
            reference_ids.extend(
                item["reference_id"]
                for item in match["references"]
                if isinstance(item, Mapping)
                and isinstance(item.get("reference_id"), str)
            )
    records = [
        dict(reference_index[item])
        for item in reference_ids
        if item in reference_index
    ]
    labels = [
        canonicalize_v3_labels(record["candidate_v3_labels"])
        for record in records
        if isinstance(record.get("candidate_v3_labels"), Mapping)
    ]
    suggestion = (
        labels[0] if labels and all(item == labels[0] for item in labels) else None
    )
    return suggestion, reference_ids, records


def new_decision(
    candidate: Mapping[str, Any],
    *,
    status: str,
    corrected_labels: Mapping[str, Any] | None,
    historical_suggested_labels: Mapping[str, Any] | None,
    historical_reference_ids: Iterable[str],
    reviewer_notes: str,
    reviewer_id: str | None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    if status not in TERMINAL_REVIEW_STATUSES:
        raise V3ReviewWorkflowError(f"非终态 review_status: {status}")
    proposed = canonicalize_v3_labels(candidate["candidate_v3_labels"])
    correction = (
        canonicalize_v3_labels(corrected_labels)
        if corrected_labels is not None
        else None
    )
    if status == "approved" and correction is not None:
        raise V3ReviewWorkflowError("approved 不能携带 corrected_labels")
    if status == "corrected" and (correction is None or correction == proposed):
        raise V3ReviewWorkflowError("corrected 必须提供与系统建议不同的合法标签")
    if status in {"dropped", "needs_regenerate"} and correction is not None:
        raise V3ReviewWorkflowError(f"{status} 不能携带 corrected_labels")
    if status in {"dropped", "needs_regenerate"} and not reviewer_notes.strip():
        raise V3ReviewWorkflowError(f"{status} 必须填写 reviewer_notes")

    record = {
        "clip_id": candidate["candidate_id"],
        "source_video": candidate["source_video"],
        "review_status": status,
        "system_proposed_labels": proposed,
        "historical_suggested_labels": (
            canonicalize_v3_labels(historical_suggested_labels)
            if historical_suggested_labels is not None
            else None
        ),
        "corrected_labels": correction,
        "reviewer_notes": reviewer_notes,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc).isoformat(),
        "reviewer_id": reviewer_id,
        "evidence": {
            "media_sha256": candidate["video_sha256"],
            "historical_reference_ids": list(historical_reference_ids),
            "actual_sampled_timestamps": list(
                candidate["_actual_sampled_timestamps"]
            ),
        },
    }
    return build_review_payload(
        [record],
        batch_id="single-record-validation",
        created_at="1970-01-01T00:00:00+00:00",
    )["decisions"][0]


def _atomic_replace(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json_bytes(payload)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_name = handle.name
        os.replace(temp_name, path)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()


def load_draft(
    path: Path, queue_identity: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    if not Path(path).exists():
        return {}
    payload = _load_json(Path(path), "v3 审查草稿")
    if not isinstance(payload, Mapping):
        raise V3ReviewWorkflowError("v3 审查草稿必须是对象")
    if payload.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise V3ReviewWorkflowError("v3 审查草稿 schema_version 不匹配")
    if payload.get("queue_identity") != dict(queue_identity):
        raise V3ReviewWorkflowError("拒绝加载属于其他队列或样本集合的审查草稿")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise V3ReviewWorkflowError("v3 审查草稿 decisions 必须是列表")
    validate_review_payload(
        {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "label_schema_version": payload.get("label_schema_version"),
            "batch_id": "draft-validation",
            "created_at": payload.get("updated_at"),
            "decisions": decisions,
        }
    )
    allowed = set(queue_identity["selected_candidate_ids"])
    result = {record["clip_id"]: dict(record) for record in decisions}
    if len(result) != len(decisions) or not set(result).issubset(allowed):
        raise V3ReviewWorkflowError("v3 审查草稿含重复或越界 candidate_id")
    return result


def save_draft(
    path: Path,
    queue_identity: Mapping[str, Any],
    decisions: Mapping[str, Mapping[str, Any]],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    allowed_ids = list(queue_identity["selected_candidate_ids"])
    if not set(decisions).issubset(set(allowed_ids)):
        raise V3ReviewWorkflowError("草稿含不属于当前选定队列的 candidate_id")
    ordered = [dict(decisions[item]) for item in allowed_ids if item in decisions]
    review_payload = build_review_payload(
        ordered,
        batch_id="draft-validation",
        created_at=updated_at or datetime.now(timezone.utc).isoformat(),
    )
    payload = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "label_schema_version": review_payload["label_schema_version"],
        "queue_identity": dict(queue_identity),
        "updated_at": review_payload["created_at"],
        "reviewed_count": len(ordered),
        "remaining_count": len(allowed_ids) - len(ordered),
        "decisions": review_payload["decisions"],
    }
    if Path(path).exists():
        existing = _load_json(Path(path), "v3 审查草稿")
        if (
            not isinstance(existing, Mapping)
            or existing.get("queue_identity") != dict(queue_identity)
        ):
            raise V3ReviewWorkflowError(
                "拒绝覆盖属于其他队列或样本集合的审查草稿"
            )
    _atomic_replace(Path(path), payload)
    return payload


def freeze_completed_batch(
    output_root: Path,
    queue_identity: Mapping[str, Any],
    decisions: Mapping[str, Mapping[str, Any]],
    *,
    created_at: str | None = None,
) -> Path:
    expected_ids = list(queue_identity["selected_candidate_ids"])
    if set(decisions) != set(expected_ids):
        missing = [item for item in expected_ids if item not in decisions]
        raise V3ReviewWorkflowError(
            f"选定队列尚未完成，缺少 {len(missing)} 条终态决定"
        )
    ordered = [dict(decisions[item]) for item in expected_ids]
    content_identity = {
        key: value
        for key, value in queue_identity.items()
        if key not in {"queue_path", "manifest_path"}
    }
    seed = {"queue_identity": content_identity, "decisions": ordered}
    batch_hash = _sha256_bytes(canonical_json_bytes(seed))
    batch_id = f"review-batch-{batch_hash[:12]}"
    stable_created_at = created_at or max(
        str(item["reviewed_at"]) for item in ordered
    )
    payload = build_review_payload(
        ordered, batch_id=batch_id, created_at=stable_created_at
    )
    batch_dir = Path(output_root) / batch_id
    decisions_path = batch_dir / "decisions.json"
    save_review_payload(decisions_path, payload)
    summary = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "batch_id": batch_id,
        "queue_identity": content_identity,
        "decision_count": len(ordered),
        "status_counts": dict(
            sorted(Counter(item["review_status"] for item in ordered).items())
        ),
        "artifacts": {"decisions.json": {"sha256": sha256_file(decisions_path)}},
    }
    summary_path = batch_dir / "summary.json"
    if summary_path.exists():
        if _load_json(summary_path, "既有审查摘要") != summary:
            raise FileExistsError(f"拒绝覆盖已有审查摘要: {summary_path}")
    else:
        _atomic_replace(summary_path, summary)
    return batch_dir
