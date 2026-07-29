"""Content-bound v4.1 review queue and resumable workspace helpers."""

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
    sha256_file,
)
from pipeline.v4_1_labels import (
    canonicalize_v4_1_labels,
    incipient_labels,
    migrate_v3_to_v4_1_labels,
    migrate_v4_labels,
)
from pipeline.data_roots import (
    DataRootError,
    resolve_workspace_artifact,
    workspace_portable_path,
)
from pipeline.v4_1_review_decisions import (
    REVIEW_SCHEMA_VERSION,
    build_review_payload,
    canonical_json_bytes,
    save_review_payload,
    validate_review_payload,
)

QUEUE_SCHEMA_VERSION = "tensile-v4.1-review-queue/v1"
PHASE2_QUEUE_SCHEMA_VERSION = "tensile-v4.1-phase2-review-queue/v1"
WORKSPACE_SCHEMA_VERSION = "tensile-review-workspace/v4.1"
MIGRATION_POLICY_VERSION = "v4-to-v4.1-incipient/v1"
PHASE2_REVIEW_POLICY_VERSION = "effective-view-human-review/v1"
EFFECTIVE_VIEW_AUDIT_SCHEMA_VERSION = "tensile-vlm-v4.1-effective-view-audit/v1"
MATERIALIZED_SCHEMA_VERSION = "tensile-v3-candidate-media/v1"
TERMINAL_REVIEW_STATUSES = frozenset(
    {"approved", "corrected", "dropped", "needs_regenerate"}
)
CODE_ROOT = Path(__file__).resolve().parents[1]


class V4_1ReviewWorkflowError(ValueError):
    pass


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise V4_1ReviewWorkflowError(f"{label}不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise V4_1ReviewWorkflowError(f"{label}不是合法 JSON: {path}: {exc}") from exc


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _candidate_ids_sha256(candidate_ids: Iterable[str]) -> str:
    payload = json.dumps(
        list(candidate_ids), ensure_ascii=False, separators=(",", ":")
    ).encode()
    return _sha256_bytes(payload)


def _contract_identity(contract_path: Path) -> tuple[str, str]:
    contract = _load_json(contract_path, "v4.1 contract")
    if not isinstance(contract, Mapping) or contract.get("contract_version") != "tensile-vlm/v4.1":
        raise V4_1ReviewWorkflowError("v4.1 contract_version 不匹配")
    declared = contract.get("contract_hash")
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    actual = _sha256_bytes(
        json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )
    if declared != actual:
        raise V4_1ReviewWorkflowError("v4.1 contract_hash 自校验失败")
    return str(declared), sha256_file(contract_path)


def _resolve_path(value: Any, project_root: Path) -> Path:
    return resolve_workspace_artifact(str(value), project_root)


def _resolve_contract_path(
    value: Any,
    project_root: Path | None = None,
) -> Path:
    """Resolve a contract recorded on this or another project checkout."""
    path = Path(str(value))
    if path.is_absolute() and path.is_file():
        return path
    if not path.is_absolute() and project_root is not None:
        candidate = Path(project_root) / path
        if candidate.is_file():
            return candidate
    if path.is_file():
        return path
    parts = path.parts
    if "pipeline" in parts:
        suffix = Path(*parts[parts.index("pipeline") :])
        candidate = CODE_ROOT / suffix
        if candidate.is_file():
            return candidate
    if not path.is_absolute():
        candidate = CODE_ROOT / path
        if candidate.is_file():
            return candidate
    return path


def _portable_identity_path(path: Path, data_root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(Path(data_root).resolve())
    except ValueError:
        try:
            return resolved.relative_to(CODE_ROOT).as_posix()
        except ValueError as exc:
            raise V4_1ReviewWorkflowError(
                f"路径无法转换为稳定身份: {path}"
            ) from exc
    semantic_root = Path(data_root).name == "data" and (
        Path(data_root).parent.name == "workspace"
        or Path(data_root).parent.parent.name == "data-rebuild"
    )
    if semantic_root and (
        not relative.parts
        or relative.parts[0] not in {"source", "derived", "releases"}
    ):
        raise V4_1ReviewWorkflowError(f"路径不是受管语义路径: {path}")
    return relative.as_posix()


def _validate_media(candidate: Mapping[str, Any], project_root: Path) -> dict[str, Any]:
    candidate_id = str(candidate.get("candidate_id") or "")
    if not candidate_id:
        raise V4_1ReviewWorkflowError("candidate_id 不能为空")
    video_path = _resolve_path(candidate.get("video_path"), project_root)
    if not video_path.is_file() or sha256_file(video_path) != candidate.get("video_sha256"):
        raise V4_1ReviewWorkflowError(f"{candidate_id}: 视频缺失或 SHA-256 不一致")
    mapping = candidate.get("actual_frame_mapping")
    artifacts = candidate.get("frame_artifacts")
    if not isinstance(mapping, list) or not mapping:
        raise V4_1ReviewWorkflowError(f"{candidate_id}: 实际帧映射为空")
    if not isinstance(artifacts, list) or not artifacts:
        raise V4_1ReviewWorkflowError(f"{candidate_id}: 帧图 artifact 为空")
    timestamps: list[float] = []
    for item in mapping:
        value = item.get("timestamp") if isinstance(item, Mapping) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise V4_1ReviewWorkflowError(f"{candidate_id}: 帧时间戳非法")
        timestamps.append(float(value))
    frames: list[dict[str, str]] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise V4_1ReviewWorkflowError(f"{candidate_id}: 帧图 artifact 非法")
        path = _resolve_path(artifact.get("path"), project_root)
        expected = artifact.get("sha256")
        if not path.is_file() or sha256_file(path) != expected:
            raise V4_1ReviewWorkflowError(f"{candidate_id}: 帧图缺失或 SHA-256 不一致")
        frames.append({"path": str(path), "sha256": str(expected)})
    return {
        **candidate,
        "_resolved_video_path": str(video_path),
        "_resolved_frames": frames,
        "_actual_sampled_timestamps": timestamps,
    }


def _source_payload(
    materialized_path: Path, manifest_path: Path
) -> tuple[Mapping[str, Any], Mapping[str, Any], list[Mapping[str, Any]]]:
    payload = _load_json(materialized_path, "development materialized")
    manifest = _load_json(manifest_path, "candidate media manifest")
    if (
        not isinstance(payload, Mapping)
        or not isinstance(manifest, Mapping)
        or payload.get("schema_version") != MATERIALIZED_SCHEMA_VERSION
        or manifest.get("schema_version") != MATERIALIZED_SCHEMA_VERSION
    ):
        raise V4_1ReviewWorkflowError("完整媒体清单 schema_version 不匹配")
    artifact = (manifest.get("artifacts") or {}).get(Path(materialized_path).name)
    if not isinstance(artifact, Mapping) or artifact.get("sha256") != sha256_file(
        materialized_path
    ):
        raise V4_1ReviewWorkflowError("完整媒体清单未被 manifest 正确绑定")
    if payload.get("media_id") != manifest.get("media_id"):
        raise V4_1ReviewWorkflowError("完整媒体清单与 manifest 身份不一致")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise V4_1ReviewWorkflowError("development materialized 缺少 candidates")
    return payload, manifest, candidates


def _is_incipient_candidate(candidate: Mapping[str, Any]) -> bool:
    return (
        candidate.get("window_role") == "pre_event"
        and candidate.get("window_variant") == "pre_event_back"
        and candidate.get("source_type") == "韧性断裂"
    )


def _proposal(candidate: Mapping[str, Any]) -> dict[str, Any] | None:
    labels = candidate.get("candidate_v3_labels")
    state = labels.get("clip_state") if isinstance(labels, Mapping) else None
    if state in {"发生断裂", "已断裂"}:
        return migrate_v3_to_v4_1_labels(labels)
    if _is_incipient_candidate(candidate):
        return incipient_labels(candidate.get("source_location"))
    return None


def build_v4_1_review_queue(
    *,
    materialized_path: Path,
    manifest_path: Path,
    project_root: Path,
    contract_path: Path,
) -> dict[str, Any]:
    """Select observed-fracture and incipient candidates from existing media."""
    payload, manifest, all_candidates = _source_payload(
        Path(materialized_path), Path(manifest_path)
    )
    candidates = [
        candidate for candidate in all_candidates if _proposal(candidate) is not None
    ]
    contract_hash, contract_file_sha256 = _contract_identity(contract_path)
    migrated: list[dict[str, Any]] = []
    for candidate in candidates:
        migrated.append(
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_v4_labels": _proposal(candidate),
                "candidate_kind": (
                    "incipient_ductile" if _is_incipient_candidate(candidate) else "observed"
                ),
            }
        )
    seed = {
        "source_materialized_sha256": sha256_file(materialized_path),
        "source_manifest_sha256": sha256_file(manifest_path),
        "contract_hash": contract_hash,
        "migration_policy_version": MIGRATION_POLICY_VERSION,
        "candidates": migrated,
    }
    queue_id = f"v4-1-review-{_sha256_bytes(canonical_json_bytes(seed))[:12]}"
    return {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "queue_id": queue_id,
        "migration_policy_version": MIGRATION_POLICY_VERSION,
        "contract": {
            "path": _portable_identity_path(contract_path, project_root),
            "contract_hash": contract_hash,
            "file_sha256": contract_file_sha256,
        },
        "source_media": {
            "materialized_path": _portable_identity_path(
                materialized_path, project_root
            ),
            "materialized_sha256": sha256_file(materialized_path),
            "manifest_path": _portable_identity_path(
                manifest_path, project_root
            ),
            "manifest_sha256": sha256_file(manifest_path),
            "media_id": payload["media_id"],
        },
        "candidate_count": len(migrated),
        "observed_count": sum(item["candidate_kind"] == "observed" for item in migrated),
        "incipient_count": sum(
            item["candidate_kind"] == "incipient_ductile" for item in migrated
        ),
        "candidate_ids_sha256": _candidate_ids_sha256(
            item["candidate_id"] for item in migrated
        ),
        "candidates": migrated,
    }


def save_v4_1_review_queue(path: Path, payload: Mapping[str, Any]) -> bool:
    content = canonical_json_bytes(payload)
    path = Path(path)
    if path.exists():
        if path.read_bytes() == content:
            return False
        raise FileExistsError(f"拒绝覆盖已有 v4.1 队列: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return True


def _materialized_candidates(path: Path) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    payload = _load_json(path, "materialized candidates")
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != MATERIALIZED_SCHEMA_VERSION
    ):
        raise V4_1ReviewWorkflowError("materialized candidates schema_version 不匹配")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not all(
        isinstance(item, Mapping) for item in candidates
    ):
        raise V4_1ReviewWorkflowError("materialized candidates 缺少 candidates")
    candidate_ids = [item.get("candidate_id") for item in candidates]
    if any(not isinstance(item, str) or not item for item in candidate_ids):
        raise V4_1ReviewWorkflowError("materialized candidates 包含非法 candidate_id")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise V4_1ReviewWorkflowError("materialized candidates candidate_id 重复")
    return payload, candidates


def _phase2_scope_input_name(scope: str) -> str:
    names = {
        "development": "experimental_materialized",
        "sealed_test": "test_materialized",
    }
    try:
        return names[scope]
    except KeyError as exc:
        raise V4_1ReviewWorkflowError(
            f"phase2 review scope 非法: {scope!r}"
        ) from exc


def _portable_binding_path(path: Path, project_root: Path) -> str:
    try:
        return workspace_portable_path(path, project_root)
    except DataRootError:
        return str(Path(path).resolve())


def _phase2_audit_scope(
    audit: Mapping[str, Any],
    *,
    scope: str,
) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
    if audit.get("schema_version") != EFFECTIVE_VIEW_AUDIT_SCHEMA_VERSION:
        raise V4_1ReviewWorkflowError("有效视图审计 schema_version 不匹配")
    completion = audit.get("completion")
    leakage = audit.get("leakage")
    identity = audit.get("identity")
    if (
        not isinstance(completion, Mapping)
        or completion.get("ready_for_human_review") is not True
        or completion.get("creates_training_release") is not False
    ):
        raise V4_1ReviewWorkflowError("有效视图审计尚未达到人工审查门槛")
    if not isinstance(leakage, Mapping) or leakage.get("passed") is not True:
        raise V4_1ReviewWorkflowError("有效视图审计的开发/测试隔离未通过")
    policy = identity.get("policy") if isinstance(identity, Mapping) else None
    if (
        not isinstance(policy, Mapping)
        or policy.get("automatic_labels_are_truth") is not False
        or policy.get("v3_test_labels_are_truth") is not False
    ):
        raise V4_1ReviewWorkflowError("有效视图审计未声明历史标签仅作提示")
    queues = audit.get("review_queues")
    rows = queues.get(scope) if isinstance(queues, Mapping) else None
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise V4_1ReviewWorkflowError(f"有效视图审计缺少 {scope} 审查候选")
    inputs = audit.get("inputs")
    source = (
        inputs.get(_phase2_scope_input_name(scope))
        if isinstance(inputs, Mapping)
        else None
    )
    if not isinstance(source, Mapping):
        raise V4_1ReviewWorkflowError(f"有效视图审计缺少 {scope} 媒体输入")
    return rows, source


def build_phase2_review_queue(
    *,
    audit_manifest_path: Path,
    scope: str,
    project_root: Path,
    contract_path: Path,
) -> dict[str, Any]:
    """Build one isolated human-review queue from the frozen Phase 1 audit."""
    audit_manifest_path = Path(audit_manifest_path).resolve()
    audit = _load_json(audit_manifest_path, "有效视图审计 manifest")
    if not isinstance(audit, Mapping):
        raise V4_1ReviewWorkflowError("有效视图审计 manifest 必须是对象")
    audit_rows, source = _phase2_audit_scope(audit, scope=scope)
    materialized_path = _resolve_path(source.get("path"), project_root)
    materialized_sha256 = sha256_file(materialized_path)
    if materialized_sha256 != source.get("sha256"):
        raise V4_1ReviewWorkflowError(f"{scope} materialized 输入已漂移")
    _, materialized = _materialized_candidates(materialized_path)
    materialized_index = {
        str(item["candidate_id"]): item for item in materialized
    }
    entries: list[dict[str, Any]] = []
    for row in audit_rows:
        candidate_id = str(row.get("candidate_id") or "")
        source_candidate = materialized_index.get(candidate_id)
        if source_candidate is None:
            raise V4_1ReviewWorkflowError(
                f"{scope} 审计候选不存在于 materialized 输入: {candidate_id}"
            )
        labels = canonicalize_v4_1_labels(row.get("labels"))
        if row.get("review_scope") != scope or row.get("truth_status") != "unreviewed":
            raise V4_1ReviewWorkflowError(
                f"{candidate_id}: 审计候选 scope 或 truth_status 非法"
            )
        if (
            row.get("source_video") != source_candidate.get("source_video")
            or row.get("video_sha256") != source_candidate.get("video_sha256")
            or row.get("actual_frame_mapping")
            != source_candidate.get("actual_frame_mapping")
        ):
            raise V4_1ReviewWorkflowError(f"{candidate_id}: 审计候选媒体绑定漂移")
        entries.append(
            {
                "candidate_id": candidate_id,
                "candidate_v4_labels": labels,
                "candidate_kind": "phase2_audit_candidate",
                "review_scope": scope,
                "labels_are_truth": False,
                "effective_frame_signature": row.get(
                    "effective_frame_signature"
                ),
            }
        )
    contract_hash, contract_file_sha256 = _contract_identity(contract_path)
    seed = {
        "audit_manifest_sha256": sha256_file(audit_manifest_path),
        "audit_id": audit.get("audit_id"),
        "scope": scope,
        "materialized_sha256": materialized_sha256,
        "contract_hash": contract_hash,
        "review_policy_version": PHASE2_REVIEW_POLICY_VERSION,
        "candidate_ids": [item["candidate_id"] for item in entries],
    }
    queue_id = f"v4-1-phase2-{scope}-{_sha256_bytes(canonical_json_bytes(seed))[:12]}"
    return {
        "schema_version": PHASE2_QUEUE_SCHEMA_VERSION,
        "queue_id": queue_id,
        "review_policy_version": PHASE2_REVIEW_POLICY_VERSION,
        "review_scope": scope,
        "labels_are_truth": False,
        "contract": {
            "path": str(Path(contract_path).resolve()),
            "contract_hash": contract_hash,
            "file_sha256": contract_file_sha256,
        },
        "source_audit": {
            "path": _portable_binding_path(audit_manifest_path, project_root),
            "sha256": sha256_file(audit_manifest_path),
            "audit_id": audit.get("audit_id"),
        },
        "source_media": {
            "materialized_path": _portable_binding_path(
                materialized_path, project_root
            ),
            "materialized_sha256": materialized_sha256,
            "media_id": _load_json(
                materialized_path, "materialized candidates"
            ).get("media_id"),
        },
        "candidate_count": len(entries),
        "candidate_ids_sha256": _candidate_ids_sha256(
            item["candidate_id"] for item in entries
        ),
        "candidates": entries,
    }


def _select_review_candidates(
    joined: list[dict[str, Any]],
    *,
    candidate_ids: Iterable[str] | None,
    limit: int | None,
) -> tuple[list[dict[str, Any]], list[str], str]:
    all_ids = [item["candidate_id"] for item in joined]
    requested = list(candidate_ids or [])
    if len(requested) != len(set(requested)):
        raise V4_1ReviewWorkflowError("candidate_ids 不能重复")
    index = {item["candidate_id"]: item for item in joined}
    missing = [item for item in requested if item not in index]
    if missing:
        raise V4_1ReviewWorkflowError(f"指定 candidate_id 不在队列中: {missing}")
    selected = [index[item] for item in requested] if requested else joined
    if limit is not None:
        if limit <= 0:
            raise V4_1ReviewWorkflowError("limit 必须大于 0")
        selected = selected[:limit]
    selected_ids = [item["candidate_id"] for item in selected]
    return selected, selected_ids, _candidate_ids_sha256(all_ids)


def _load_phase2_review_queue(
    queue_path: Path,
    queue: Mapping[str, Any],
    *,
    project_root: Path,
    candidate_ids: Iterable[str] | None,
    limit: int | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if queue.get("review_policy_version") != PHASE2_REVIEW_POLICY_VERSION:
        raise V4_1ReviewWorkflowError("phase2 人工审查策略版本不匹配")
    scope = str(queue.get("review_scope") or "")
    _phase2_scope_input_name(scope)
    if queue.get("labels_are_truth") is not False:
        raise V4_1ReviewWorkflowError("phase2 队列必须声明历史标签不是真值")
    contract = queue.get("contract")
    source_audit = queue.get("source_audit")
    source_media = queue.get("source_media")
    if not all(
        isinstance(item, Mapping)
        for item in (contract, source_audit, source_media)
    ):
        raise V4_1ReviewWorkflowError("phase2 队列缺少 contract、audit 或 media 绑定")
    contract_path = _resolve_contract_path(
        contract.get("path"),
        project_root,
    )
    contract_hash, contract_file_sha256 = _contract_identity(contract_path)
    if (
        contract.get("contract_hash") != contract_hash
        or contract.get("file_sha256") != contract_file_sha256
    ):
        raise V4_1ReviewWorkflowError("phase2 队列绑定的契约已漂移")
    audit_path = _resolve_path(source_audit.get("path"), project_root)
    if sha256_file(audit_path) != source_audit.get("sha256"):
        raise V4_1ReviewWorkflowError("phase2 队列绑定的审计 manifest 已漂移")
    audit = _load_json(audit_path, "有效视图审计 manifest")
    if not isinstance(audit, Mapping) or audit.get("audit_id") != source_audit.get(
        "audit_id"
    ):
        raise V4_1ReviewWorkflowError("phase2 队列 audit_id 不匹配")
    audit_rows, audit_source = _phase2_audit_scope(audit, scope=scope)
    materialized_path = _resolve_path(
        source_media.get("materialized_path"), project_root
    )
    materialized_sha256 = sha256_file(materialized_path)
    if (
        materialized_sha256 != source_media.get("materialized_sha256")
        or materialized_sha256 != audit_source.get("sha256")
    ):
        raise V4_1ReviewWorkflowError("phase2 队列 materialized 输入已漂移")
    payload, materialized = _materialized_candidates(materialized_path)
    materialized_index = {
        str(item["candidate_id"]): item for item in materialized
    }
    entries = queue.get("candidates")
    if not isinstance(entries, list) or len(entries) != len(audit_rows):
        raise V4_1ReviewWorkflowError("phase2 队列候选数量与审计清单不一致")
    entry_index = {
        str(item.get("candidate_id")): item
        for item in entries
        if isinstance(item, Mapping)
    }
    if len(entry_index) != len(entries):
        raise V4_1ReviewWorkflowError("phase2 队列 candidate_id 非法或重复")
    joined: list[dict[str, Any]] = []
    for row in audit_rows:
        candidate_id = str(row.get("candidate_id") or "")
        entry = entry_index.get(candidate_id)
        source_candidate = materialized_index.get(candidate_id)
        if entry is None or source_candidate is None:
            raise V4_1ReviewWorkflowError(
                f"phase2 队列缺少审计候选: {candidate_id}"
            )
        labels = canonicalize_v4_1_labels(row.get("labels"))
        if (
            canonicalize_v4_1_labels(entry.get("candidate_v4_labels")) != labels
            or entry.get("review_scope") != scope
            or entry.get("labels_are_truth") is not False
        ):
            raise V4_1ReviewWorkflowError(f"{candidate_id}: phase2 标签提示或 scope 漂移")
        if (
            row.get("source_video") != source_candidate.get("source_video")
            or row.get("video_sha256") != source_candidate.get("video_sha256")
            or row.get("actual_frame_mapping")
            != source_candidate.get("actual_frame_mapping")
        ):
            raise V4_1ReviewWorkflowError(f"{candidate_id}: phase2 媒体绑定漂移")
        joined.append(
            {
                **_validate_media(source_candidate, project_root),
                "candidate_v4_labels": labels,
                "candidate_kind": "phase2_audit_candidate",
                "review_scope": scope,
                "labels_are_truth": False,
                "effective_frame_signature": row.get(
                    "effective_frame_signature"
                ),
            }
        )
    all_ids = [item["candidate_id"] for item in joined]
    all_ids_sha256 = _candidate_ids_sha256(all_ids)
    if queue.get("candidate_ids_sha256") != all_ids_sha256:
        raise V4_1ReviewWorkflowError("phase2 candidate IDs 摘要不一致")
    selected, selected_ids, _ = _select_review_candidates(
        joined,
        candidate_ids=candidate_ids,
        limit=limit,
    )
    identity = {
        "queue_schema_version": PHASE2_QUEUE_SCHEMA_VERSION,
        "queue_id": queue["queue_id"],
        "queue_path": str(queue_path),
        "queue_sha256": sha256_file(queue_path),
        "contract_hash": contract_hash,
        "media_id": payload.get("media_id"),
        "audit_id": audit["audit_id"],
        "review_scope": scope,
        "labels_are_truth": False,
        "full_queue_count": len(joined),
        "full_candidate_ids_sha256": all_ids_sha256,
        "selected_candidate_ids": selected_ids,
        "selected_candidate_ids_sha256": _candidate_ids_sha256(selected_ids),
    }
    return identity, selected


def load_review_queue(
    queue_path: Path,
    *,
    project_root: Path,
    candidate_ids: Iterable[str] | None = None,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    queue_path = Path(queue_path).resolve()
    queue = _load_json(queue_path, "v4.1 review queue")
    if (
        isinstance(queue, Mapping)
        and queue.get("schema_version") == PHASE2_QUEUE_SCHEMA_VERSION
    ):
        return _load_phase2_review_queue(
            queue_path,
            queue,
            project_root=project_root,
            candidate_ids=candidate_ids,
            limit=limit,
        )
    if not isinstance(queue, Mapping) or queue.get("schema_version") != QUEUE_SCHEMA_VERSION:
        raise V4_1ReviewWorkflowError(f"schema_version 必须是 {QUEUE_SCHEMA_VERSION}")
    if queue.get("migration_policy_version") != MIGRATION_POLICY_VERSION:
        raise V4_1ReviewWorkflowError("v4.1 迁移策略版本不匹配")
    source = queue.get("source_media")
    contract = queue.get("contract")
    if not isinstance(source, Mapping) or not isinstance(contract, Mapping):
        raise V4_1ReviewWorkflowError("v4.1 队列缺少 source_media 或 contract")
    contract_path = _resolve_contract_path(
        contract.get("path"),
        project_root,
    )
    contract_hash, contract_file_sha256 = _contract_identity(contract_path)
    if (
        contract.get("contract_hash") != contract_hash
        or contract.get("file_sha256") != contract_file_sha256
    ):
        raise V4_1ReviewWorkflowError("v4.1 队列绑定的契约已漂移")
    source_materialized = _resolve_path(source.get("materialized_path"), project_root)
    source_manifest = _resolve_path(source.get("manifest_path"), project_root)
    if (
        sha256_file(source_materialized) != source.get("materialized_sha256")
        or sha256_file(source_manifest) != source.get("manifest_sha256")
    ):
        raise V4_1ReviewWorkflowError("v4.1 队列绑定的 v3 媒体输入已漂移")
    payload, _, all_candidates = _source_payload(source_materialized, source_manifest)
    raw_candidates = [
        candidate for candidate in all_candidates if _proposal(candidate) is not None
    ]
    entries = queue.get("candidates")
    if not isinstance(entries, list) or len(entries) != len(raw_candidates):
        raise V4_1ReviewWorkflowError("v4.1 队列候选数量与 v3 媒体不一致")
    entry_index = {
        str(item.get("candidate_id")): item
        for item in entries
        if isinstance(item, Mapping)
    }
    if len(entry_index) != len(entries):
        raise V4_1ReviewWorkflowError("v4.1 队列 candidate_id 非法或重复")
    joined: list[dict[str, Any]] = []
    for candidate in raw_candidates:
        candidate_id = candidate["candidate_id"]
        entry = entry_index.get(candidate_id)
        if entry is None:
            raise V4_1ReviewWorkflowError(f"v4.1 队列缺少候选: {candidate_id}")
        expected = _proposal(candidate)
        labels = canonicalize_v4_1_labels(entry.get("candidate_v4_labels"))
        if labels != expected:
            raise V4_1ReviewWorkflowError(f"{candidate_id}: v4.1 标签迁移结果漂移")
        joined.append(
            {
                **_validate_media(candidate, project_root),
                "candidate_v4_labels": labels,
                "candidate_kind": entry.get("candidate_kind"),
            }
        )
    all_ids = [item["candidate_id"] for item in joined]
    if queue.get("candidate_ids_sha256") != _candidate_ids_sha256(all_ids):
        raise V4_1ReviewWorkflowError("v4 candidate IDs 摘要不一致")
    requested = list(candidate_ids or [])
    if len(requested) != len(set(requested)):
        raise V4_1ReviewWorkflowError("candidate_ids 不能重复")
    index = {item["candidate_id"]: item for item in joined}
    missing = [item for item in requested if item not in index]
    if missing:
        raise V4_1ReviewWorkflowError(f"指定 candidate_id 不在队列中: {missing}")
    selected = [index[item] for item in requested] if requested else joined
    if limit is not None:
        if limit <= 0:
            raise V4_1ReviewWorkflowError("limit 必须大于 0")
        selected = selected[:limit]
    selected_ids = [item["candidate_id"] for item in selected]
    identity = {
        "queue_schema_version": QUEUE_SCHEMA_VERSION,
        "queue_id": queue["queue_id"],
        "queue_path": str(queue_path),
        "queue_sha256": sha256_file(queue_path),
        "contract_hash": contract_hash,
        "media_id": payload["media_id"],
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
    if candidate.get("candidate_kind") == "incipient_ductile":
        return None, [], []
    _, reference_ids, records = v3_historical_context(candidate, reference_index)
    migrated = [
        migrate_v3_to_v4_1_labels(record["candidate_v3_labels"])
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
        raise V4_1ReviewWorkflowError(f"非终态 review_status: {status}")
    proposed = canonicalize_v4_1_labels(candidate["candidate_v4_labels"])
    correction = (
        canonicalize_v4_1_labels(corrected_labels) if corrected_labels is not None else None
    )
    if status == "approved" and correction is not None:
        raise V4_1ReviewWorkflowError("approved 不能携带 corrected_labels")
    if status == "corrected" and (correction is None or correction == proposed):
        raise V4_1ReviewWorkflowError("corrected 必须提供与系统建议不同的合法标签")
    if status in {"dropped", "needs_regenerate"} and correction is not None:
        raise V4_1ReviewWorkflowError(f"{status} 不能携带 corrected_labels")
    if status in {"dropped", "needs_regenerate"} and not reviewer_notes.strip():
        raise V4_1ReviewWorkflowError(f"{status} 必须填写 reviewer_notes")
    record = {
        "clip_id": candidate["candidate_id"],
        "source_video": candidate["source_video"],
        "review_status": status,
        "system_proposed_labels": proposed,
        "historical_suggested_labels": (
            canonicalize_v4_1_labels(historical_suggested_labels)
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


def migrate_v4_decisions(
    v4_records: Iterable[Mapping[str, Any]],
    candidates: Iterable[Mapping[str, Any]],
    *,
    source_sha256: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Validate and migrate existing v4 decisions into the expanded queue."""
    candidate_index = {item["candidate_id"]: item for item in candidates}
    migrated: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, str]] = []
    for raw in v4_records:
        clip_id = str(raw.get("clip_id") or "")
        candidate = candidate_index.get(clip_id)
        if candidate is None:
            conflicts.append({"clip_id": clip_id, "reason": "candidate_not_in_v4_queue"})
            continue
        try:
            if raw.get("evidence", {}).get("media_sha256") != candidate["video_sha256"]:
                raise ValueError("media_sha256 不一致")
            proposed = migrate_v4_labels(raw["system_proposed_labels"])
            if proposed != candidate["candidate_v4_labels"]:
                raise ValueError("系统建议与 v4.1 队列不一致")
            historical_raw = raw.get("historical_suggested_labels")
            historical = (
                migrate_v4_labels(historical_raw)
                if historical_raw is not None
                else None
            )
            corrected_raw = raw.get("corrected_labels")
            corrected = (
                migrate_v4_labels(corrected_raw)
                if corrected_raw is not None
                else None
            )
            status = str(raw["review_status"])
            if status == "corrected" and corrected == proposed:
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
                    "source_schema_version": "tensile-review-decision/v4",
                    "source_sha256": source_sha256,
                    "policy_version": MIGRATION_POLICY_VERSION,
                },
            )
        except (KeyError, TypeError, ValueError, V4_1ReviewWorkflowError) as exc:
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
    payload = _load_json(path, "v4.1 审查草稿")
    if not isinstance(payload, Mapping) or payload.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise V4_1ReviewWorkflowError("v4.1 审查草稿 schema_version 不匹配")
    if payload.get("queue_identity") != dict(queue_identity):
        raise V4_1ReviewWorkflowError("拒绝加载属于其他队列或样本集合的 v4.1 草稿")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise V4_1ReviewWorkflowError("v4.1 审查草稿 decisions 必须是列表")
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
        raise V4_1ReviewWorkflowError("v4.1 草稿含重复或越界 candidate_id")
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
        raise V4_1ReviewWorkflowError("草稿含不属于当前选定队列的 candidate_id")
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
        existing = _load_json(path, "v4.1 审查草稿")
        if not isinstance(existing, Mapping) or existing.get("queue_identity") != dict(queue_identity):
            raise V4_1ReviewWorkflowError("拒绝覆盖属于其他队列的 v4.1 草稿")
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
        raise V4_1ReviewWorkflowError(f"选定队列尚未完成，缺少 {len(missing)} 条终态决定")
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
