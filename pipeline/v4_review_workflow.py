"""Content-bound v4 review queue and resumable workspace helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.v3_review_workflow import (
    historical_context as v3_historical_context,
    load_reference_records,
    load_review_queue as load_v3_review_queue,
    sha256_file,
)
from pipeline.v4_labels import canonicalize_v4_labels, migrate_v3_labels
from pipeline.v4_review_decisions import (
    REVIEW_SCHEMA_VERSION,
    build_review_payload,
    canonical_json_bytes,
    save_review_payload,
    validate_review_payload,
)

QUEUE_SCHEMA_VERSION = "tensile-v4-review-queue/v1"
WORKSPACE_SCHEMA_VERSION = "tensile-review-workspace/v4"
MIGRATION_POLICY_VERSION = "v3-to-v4-fracture-site/v1"
TERMINAL_REVIEW_STATUSES = frozenset(
    {"approved", "corrected", "dropped", "needs_regenerate"}
)


class V4ReviewWorkflowError(ValueError):
    pass


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise V4ReviewWorkflowError(f"{label}不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise V4ReviewWorkflowError(f"{label}不是合法 JSON: {path}: {exc}") from exc


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _candidate_ids_sha256(candidate_ids: Iterable[str]) -> str:
    payload = json.dumps(
        list(candidate_ids), ensure_ascii=False, separators=(",", ":")
    ).encode()
    return _sha256_bytes(payload)


def _contract_identity(contract_path: Path) -> tuple[str, str]:
    contract = _load_json(contract_path, "v4 contract")
    if not isinstance(contract, Mapping) or contract.get("contract_version") != "tensile-vlm/v4":
        raise V4ReviewWorkflowError("v4 contract_version 不匹配")
    declared = contract.get("contract_hash")
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    actual = _sha256_bytes(
        json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    if declared != actual:
        raise V4ReviewWorkflowError("v4 contract_hash 自校验失败")
    return str(declared), sha256_file(contract_path)


def build_v4_review_queue(
    *,
    v3_queue_path: Path,
    v3_manifest_path: Path,
    project_root: Path,
    contract_path: Path,
) -> dict[str, Any]:
    """Derive a v4 label queue while reusing verified v3 media bytes."""
    v3_identity, candidates = load_v3_review_queue(
        v3_queue_path,
        manifest_path=v3_manifest_path,
        project_root=project_root,
    )
    contract_hash, contract_file_sha256 = _contract_identity(contract_path)
    migrated: list[dict[str, Any]] = []
    issue_count = 0
    for candidate in candidates:
        result = migrate_v3_labels(candidate["candidate_v3_labels"])
        issue_count += len(result.issues)
        migrated.append(
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_v4_labels": result.labels,
                "migration_issues": [
                    {
                        "field": item.field,
                        "code": item.code,
                        "message": item.message,
                    }
                    for item in result.issues
                ],
            }
        )
    seed = {
        "source_queue_sha256": v3_identity["queue_sha256"],
        "source_manifest_sha256": v3_identity["manifest_sha256"],
        "contract_hash": contract_hash,
        "migration_policy_version": MIGRATION_POLICY_VERSION,
        "candidates": migrated,
    }
    queue_id = f"v4-review-{_sha256_bytes(canonical_json_bytes(seed))[:12]}"
    return {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "queue_id": queue_id,
        "migration_policy_version": MIGRATION_POLICY_VERSION,
        "contract": {
            "path": str(Path(contract_path).resolve()),
            "contract_hash": contract_hash,
            "file_sha256": contract_file_sha256,
        },
        "source_v3": {
            "queue_path": str(Path(v3_queue_path).resolve()),
            "queue_sha256": v3_identity["queue_sha256"],
            "manifest_path": str(Path(v3_manifest_path).resolve()),
            "manifest_sha256": v3_identity["manifest_sha256"],
            "media_id": v3_identity["media_id"],
        },
        "candidate_count": len(migrated),
        "migration_issue_count": issue_count,
        "candidate_ids_sha256": _candidate_ids_sha256(
            item["candidate_id"] for item in migrated
        ),
        "candidates": migrated,
    }


def save_v4_review_queue(path: Path, payload: Mapping[str, Any]) -> bool:
    content = canonical_json_bytes(payload)
    path = Path(path)
    if path.exists():
        if path.read_bytes() == content:
            return False
        raise FileExistsError(f"拒绝覆盖已有 v4 队列: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return True


def load_review_queue(
    queue_path: Path,
    *,
    project_root: Path,
    candidate_ids: Iterable[str] | None = None,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    queue_path = Path(queue_path).resolve()
    queue = _load_json(queue_path, "v4 review queue")
    if not isinstance(queue, Mapping) or queue.get("schema_version") != QUEUE_SCHEMA_VERSION:
        raise V4ReviewWorkflowError(f"schema_version 必须是 {QUEUE_SCHEMA_VERSION}")
    if queue.get("migration_policy_version") != MIGRATION_POLICY_VERSION:
        raise V4ReviewWorkflowError("v4 迁移策略版本不匹配")
    source = queue.get("source_v3")
    contract = queue.get("contract")
    if not isinstance(source, Mapping) or not isinstance(contract, Mapping):
        raise V4ReviewWorkflowError("v4 队列缺少 source_v3 或 contract")
    contract_path = Path(str(contract.get("path")))
    contract_hash, contract_file_sha256 = _contract_identity(contract_path)
    if (
        contract.get("contract_hash") != contract_hash
        or contract.get("file_sha256") != contract_file_sha256
    ):
        raise V4ReviewWorkflowError("v4 队列绑定的契约已漂移")
    source_queue = Path(str(source.get("queue_path")))
    source_manifest = Path(str(source.get("manifest_path")))
    if (
        sha256_file(source_queue) != source.get("queue_sha256")
        or sha256_file(source_manifest) != source.get("manifest_sha256")
    ):
        raise V4ReviewWorkflowError("v4 队列绑定的 v3 媒体输入已漂移")
    v3_identity, v3_candidates = load_v3_review_queue(
        source_queue,
        manifest_path=source_manifest,
        project_root=project_root,
    )
    entries = queue.get("candidates")
    if not isinstance(entries, list) or len(entries) != len(v3_candidates):
        raise V4ReviewWorkflowError("v4 队列候选数量与 v3 媒体不一致")
    entry_index = {
        str(item.get("candidate_id")): item
        for item in entries
        if isinstance(item, Mapping)
    }
    if len(entry_index) != len(entries):
        raise V4ReviewWorkflowError("v4 队列 candidate_id 非法或重复")
    joined: list[dict[str, Any]] = []
    for candidate in v3_candidates:
        candidate_id = candidate["candidate_id"]
        entry = entry_index.get(candidate_id)
        if entry is None:
            raise V4ReviewWorkflowError(f"v4 队列缺少候选: {candidate_id}")
        expected = migrate_v3_labels(candidate["candidate_v3_labels"])
        labels = canonicalize_v4_labels(entry.get("candidate_v4_labels"))
        if labels != expected.labels:
            raise V4ReviewWorkflowError(f"{candidate_id}: v4 标签迁移结果漂移")
        joined.append(
            {
                **candidate,
                "candidate_v4_labels": labels,
                "migration_issues": list(entry.get("migration_issues") or []),
            }
        )
    all_ids = [item["candidate_id"] for item in joined]
    if queue.get("candidate_ids_sha256") != _candidate_ids_sha256(all_ids):
        raise V4ReviewWorkflowError("v4 candidate IDs 摘要不一致")
    requested = list(candidate_ids or [])
    if len(requested) != len(set(requested)):
        raise V4ReviewWorkflowError("candidate_ids 不能重复")
    index = {item["candidate_id"]: item for item in joined}
    missing = [item for item in requested if item not in index]
    if missing:
        raise V4ReviewWorkflowError(f"指定 candidate_id 不在队列中: {missing}")
    selected = [index[item] for item in requested] if requested else joined
    if limit is not None:
        if limit <= 0:
            raise V4ReviewWorkflowError("limit 必须大于 0")
        selected = selected[:limit]
    selected_ids = [item["candidate_id"] for item in selected]
    identity = {
        "queue_schema_version": QUEUE_SCHEMA_VERSION,
        "queue_id": queue["queue_id"],
        "queue_path": str(queue_path),
        "queue_sha256": sha256_file(queue_path),
        "contract_hash": contract_hash,
        "media_id": v3_identity["media_id"],
        "full_queue_count": len(joined),
        "full_candidate_ids_sha256": _candidate_ids_sha256(all_ids),
        "selected_candidate_ids": selected_ids,
        "selected_candidate_ids_sha256": _candidate_ids_sha256(selected_ids),
    }
    return identity, selected


def historical_context(
    candidate: Mapping[str, Any],
    reference_index: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]]]:
    _, reference_ids, records = v3_historical_context(candidate, reference_index)
    migrated = [
        migrate_v3_labels(record["candidate_v3_labels"]).labels
        for record in records
        if isinstance(record.get("candidate_v3_labels"), Mapping)
    ]
    suggestion = (
        migrated[0] if migrated and all(item == migrated[0] for item in migrated) else None
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
    migration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in TERMINAL_REVIEW_STATUSES:
        raise V4ReviewWorkflowError(f"非终态 review_status: {status}")
    proposed = canonicalize_v4_labels(candidate["candidate_v4_labels"])
    correction = (
        canonicalize_v4_labels(corrected_labels) if corrected_labels is not None else None
    )
    if status == "approved" and correction is not None:
        raise V4ReviewWorkflowError("approved 不能携带 corrected_labels")
    if status == "corrected" and (correction is None or correction == proposed):
        raise V4ReviewWorkflowError("corrected 必须提供与系统建议不同的合法标签")
    if status in {"dropped", "needs_regenerate"} and correction is not None:
        raise V4ReviewWorkflowError(f"{status} 不能携带 corrected_labels")
    if status in {"dropped", "needs_regenerate"} and not reviewer_notes.strip():
        raise V4ReviewWorkflowError(f"{status} 必须填写 reviewer_notes")
    record = {
        "clip_id": candidate["candidate_id"],
        "source_video": candidate["source_video"],
        "review_status": status,
        "system_proposed_labels": proposed,
        "historical_suggested_labels": (
            canonicalize_v4_labels(historical_suggested_labels)
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
            "actual_sampled_timestamps": list(candidate["_actual_sampled_timestamps"]),
            "migration": dict(migration) if migration is not None else None,
        },
    }
    return build_review_payload(
        [record], batch_id="single-record-validation", created_at="1970-01-01T00:00:00+00:00"
    )["decisions"][0]


def migrate_v3_decisions(
    v3_records: Iterable[Mapping[str, Any]],
    candidates: Iterable[Mapping[str, Any]],
    *,
    source_sha256: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Validate and migrate v3 decisions; ambiguous records stay out of the draft."""
    candidate_index = {item["candidate_id"]: item for item in candidates}
    migrated: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, str]] = []
    for raw in v3_records:
        clip_id = str(raw.get("clip_id") or "")
        candidate = candidate_index.get(clip_id)
        if candidate is None:
            conflicts.append({"clip_id": clip_id, "reason": "candidate_not_in_v4_queue"})
            continue
        try:
            if raw.get("evidence", {}).get("media_sha256") != candidate["video_sha256"]:
                raise ValueError("media_sha256 不一致")
            proposed_result = migrate_v3_labels(raw["system_proposed_labels"])
            if proposed_result.requires_review:
                raise ValueError("系统建议的断裂位置迁移不完整")
            if proposed_result.labels != candidate["candidate_v4_labels"]:
                raise ValueError("系统建议与 v4 队列不一致")
            historical_raw = raw.get("historical_suggested_labels")
            historical = (
                migrate_v3_labels(historical_raw).labels
                if historical_raw is not None
                else None
            )
            corrected_raw = raw.get("corrected_labels")
            corrected = (
                migrate_v3_labels(corrected_raw).labels
                if corrected_raw is not None
                else None
            )
            status = str(raw["review_status"])
            if status == "corrected" and corrected == proposed_result.labels:
                status = "approved"
                corrected = None
            elif status == "approved":
                corrected = None
            migrated[clip_id] = new_decision(
                candidate,
                status=status,
                corrected_labels=corrected,
                historical_suggested_labels=historical,
                historical_reference_ids=raw.get("evidence", {}).get(
                    "historical_reference_ids", []
                ),
                reviewer_notes=str(raw.get("reviewer_notes") or ""),
                reviewer_id=raw.get("reviewer_id"),
                reviewed_at=raw.get("reviewed_at"),
                migration={
                    "source_schema_version": "tensile-review-decision/v3",
                    "source_sha256": source_sha256,
                    "policy_version": MIGRATION_POLICY_VERSION,
                },
            )
        except (KeyError, TypeError, ValueError, V4ReviewWorkflowError) as exc:
            conflicts.append({"clip_id": clip_id, "reason": str(exc)})
    return migrated, conflicts


def _atomic_replace(path: Path, payload: Mapping[str, Any]) -> None:
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


def load_draft(path: Path, queue_identity: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not Path(path).exists():
        return {}
    payload = _load_json(path, "v4 审查草稿")
    if not isinstance(payload, Mapping) or payload.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise V4ReviewWorkflowError("v4 审查草稿 schema_version 不匹配")
    if payload.get("queue_identity") != dict(queue_identity):
        raise V4ReviewWorkflowError("拒绝加载属于其他队列或样本集合的 v4 草稿")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise V4ReviewWorkflowError("v4 审查草稿 decisions 必须是列表")
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
        raise V4ReviewWorkflowError("v4 草稿含重复或越界 candidate_id")
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
        raise V4ReviewWorkflowError("草稿含不属于当前选定队列的 candidate_id")
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
        existing = _load_json(path, "v4 审查草稿")
        if not isinstance(existing, Mapping) or existing.get("queue_identity") != dict(queue_identity):
            raise V4ReviewWorkflowError("拒绝覆盖属于其他队列的 v4 草稿")
    _atomic_replace(Path(path), payload)
    return payload


def freeze_completed_batch(
    output_root: Path,
    queue_identity: Mapping[str, Any],
    decisions: Mapping[str, Mapping[str, Any]],
) -> Path:
    expected_ids = list(queue_identity["selected_candidate_ids"])
    if set(decisions) != set(expected_ids):
        missing = [item for item in expected_ids if item not in decisions]
        raise V4ReviewWorkflowError(f"选定队列尚未完成，缺少 {len(missing)} 条终态决定")
    ordered = [dict(decisions[item]) for item in expected_ids]
    content_identity = {
        key: value
        for key, value in queue_identity.items()
        if key != "queue_path"
    }
    batch_hash = _sha256_bytes(
        canonical_json_bytes({"queue_identity": content_identity, "decisions": ordered})
    )
    batch_id = f"review-batch-{batch_hash[:12]}"
    payload = build_review_payload(
        ordered,
        batch_id=batch_id,
        created_at=max(str(item["reviewed_at"]) for item in ordered),
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
