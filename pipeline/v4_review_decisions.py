"""Versioned, append-safe storage contract for v4 human review decisions."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.v4_labels import (
    LABEL_SCHEMA_VERSION,
    canonicalize_v4_labels,
    validate_v4_labels,
)

REVIEW_SCHEMA_VERSION = "tensile-review-decision/v4"
REVIEW_STATUSES = frozenset(
    {"approved", "corrected", "dropped", "needs_regenerate", "needs_review"}
)
FINAL_STATUSES = frozenset({"approved", "corrected"})


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _optional_labels(value: Any, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} 必须是对象或 null")
    result = validate_v4_labels(value)
    result.raise_for_errors()
    return canonicalize_v4_labels(value)


def effective_labels(record: Mapping[str, Any]) -> dict[str, Any] | None:
    status = record.get("review_status")
    if status not in FINAL_STATUSES:
        return None
    if status == "corrected":
        labels = record.get("corrected_labels")
        if labels is None:
            raise ValueError("review_status=corrected 时必须提供 corrected_labels")
        return canonicalize_v4_labels(labels)
    if record.get("corrected_labels") is not None:
        raise ValueError("review_status=approved 时 corrected_labels 必须为 null")
    proposed = record.get("system_proposed_labels")
    if proposed is None:
        raise ValueError("review_status=approved 时必须提供 system_proposed_labels")
    return canonicalize_v4_labels(proposed)


def normalize_review_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("审查记录必须是对象")
    clip_id = _nonempty_string(record.get("clip_id"), "clip_id")
    source_video = _nonempty_string(record.get("source_video"), "source_video")
    status = record.get("review_status")
    if status not in REVIEW_STATUSES:
        raise ValueError(f"review_status 必须是 {sorted(REVIEW_STATUSES)} 之一")
    system_labels = _optional_labels(
        record.get("system_proposed_labels"), "system_proposed_labels"
    )
    historical_labels = _optional_labels(
        record.get("historical_suggested_labels"), "historical_suggested_labels"
    )
    corrected_labels = _optional_labels(record.get("corrected_labels"), "corrected_labels")
    candidate = {
        **record,
        "review_status": status,
        "system_proposed_labels": system_labels,
        "historical_suggested_labels": historical_labels,
        "corrected_labels": corrected_labels,
    }
    final_labels = effective_labels(candidate)
    reviewed_at = record.get("reviewed_at")
    if status in FINAL_STATUSES and not isinstance(reviewed_at, str):
        raise ValueError("最终审查记录必须提供 reviewed_at")
    evidence = record.get("evidence", {})
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence 必须是对象")
    historical_ids = evidence.get("historical_reference_ids", [])
    timestamps = evidence.get("actual_sampled_timestamps", [])
    if not isinstance(historical_ids, list) or not all(
        isinstance(item, str) for item in historical_ids
    ):
        raise ValueError("historical_reference_ids 必须是字符串列表")
    if not isinstance(timestamps, list):
        raise ValueError("actual_sampled_timestamps 必须是列表")
    migration = evidence.get("migration")
    if migration is not None and not isinstance(migration, Mapping):
        raise ValueError("evidence.migration 必须是对象或 null")
    return {
        "clip_id": clip_id,
        "source_video": source_video,
        "review_status": status,
        "system_proposed_labels": system_labels,
        "historical_suggested_labels": historical_labels,
        "corrected_labels": corrected_labels,
        "effective_labels": final_labels,
        "reviewer_notes": str(record.get("reviewer_notes") or ""),
        "reviewed_at": reviewed_at,
        "reviewer_id": record.get("reviewer_id"),
        "evidence": {
            "media_sha256": evidence.get("media_sha256"),
            "historical_reference_ids": list(historical_ids),
            "actual_sampled_timestamps": list(timestamps),
            "migration": dict(migration) if migration is not None else None,
        },
    }


def build_review_payload(
    records: Iterable[Mapping[str, Any]], *, batch_id: str, created_at: str | None = None
) -> dict[str, Any]:
    normalized = [normalize_review_record(record) for record in records]
    clip_ids = [record["clip_id"] for record in normalized]
    if len(clip_ids) != len(set(clip_ids)):
        raise ValueError("同一审查批次中 clip_id 不能重复")
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "batch_id": _nonempty_string(batch_id, "batch_id"),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "decisions": normalized,
    }


def validate_review_payload(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError("审查 payload 必须是对象")
    if payload.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise ValueError(f"schema_version 必须是 {REVIEW_SCHEMA_VERSION}")
    if payload.get("label_schema_version") != LABEL_SCHEMA_VERSION:
        raise ValueError(f"label_schema_version 必须是 {LABEL_SCHEMA_VERSION}")
    _nonempty_string(payload.get("batch_id"), "batch_id")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("decisions 必须是列表")
    normalized = [normalize_review_record(record) for record in decisions]
    if normalized != decisions:
        raise ValueError("decisions 不是规范化的 v4 审查记录")
    clip_ids = [record["clip_id"] for record in normalized]
    if len(clip_ids) != len(set(clip_ids)):
        raise ValueError("同一审查批次中 clip_id 不能重复")


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def save_review_payload(path: Path, payload: Mapping[str, Any]) -> bool:
    validate_review_payload(payload)
    content = canonical_json_bytes(payload)
    path = Path(path)
    if path.exists():
        if path.read_bytes() == content:
            return False
        raise FileExistsError(f"拒绝覆盖已有审查批次: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
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
        if temp_name is not None and Path(temp_name).exists():
            Path(temp_name).unlink()
    return True
