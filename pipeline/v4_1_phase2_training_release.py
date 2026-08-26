"""Build the immutable V4.1 Phase 2 development release.

This publisher preserves the original V4.1 release and appends only candidates
whose Phase 2 disposition is independently auditable as one of:

* an existing current-round human decision;
* a frozen historical consensus record; or
* a decision from the frozen manual-only review batch.

The resulting release also carries effective-frame signatures so downstream
source-aware sampling can enforce per-view repetition limits.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from pipeline.data_roots import resolve_workspace_artifact
from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_labels import V4_1_LABEL_FIELDS, canonicalize_v4_1_labels
from pipeline.v4_1_review_decisions import (
    normalize_review_record,
    validate_review_payload,
)
from pipeline.v4_1_review_routing import (
    EXISTING_DISPOSITION,
    EXISTING_HUMAN_SCHEMA_VERSION,
    HISTORICAL_DISPOSITION,
    HISTORICAL_SCHEMA_VERSION,
    MANUAL_DISPOSITION,
    ROUTING_POLICY_VERSION,
    ROUTING_SCHEMA_VERSION,
    load_manual_candidate_ids,
)
from pipeline.v4_1_review_workflow import (
    EFFECTIVE_VIEW_AUDIT_SCHEMA_VERSION,
    PHASE2_QUEUE_SCHEMA_VERSION,
    TERMINAL_REVIEW_STATUSES,
    load_review_queue,
)
from pipeline.v4_1_training_release import (
    DATA_VERSION,
    QUALITY_SCHEMA_VERSION,
    RELEASE_SCHEMA_VERSION,
    TRAINING_CANDIDATES_SCHEMA_VERSION,
    V4_1TrainingReleaseError,
    _canonical_bytes,
    _contract_identity,
    _dataset_row,
    _distribution,
    _load_materialized,
    _load_splits,
    _pretty_bytes,
    _read_json,
    _registry,
    _sha256_bytes,
    _write_release,
)

COMBINED_REVIEW_SCHEMA_VERSION = "tensile-vlm-v4.1-combined-review/v1"
DELTA_REPORT_SCHEMA_VERSION = "tensile-training-delta/v4.1"


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V4_1TrainingReleaseError(f"{label}必须是对象")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise V4_1TrainingReleaseError(f"{label}必须是列表")
    return value


def _verified_release_file(
    release_dir: Path,
    entry: Mapping[str, Any],
) -> Path:
    relative = entry.get("path")
    if not isinstance(relative, str) or not relative:
        raise V4_1TrainingReleaseError("基础发布 files.path 非法")
    release_root = release_dir.resolve()
    path = (release_root / relative).resolve()
    if not path.is_relative_to(release_root):
        raise V4_1TrainingReleaseError(f"基础发布文件越界: {relative}")
    if not path.is_file():
        raise V4_1TrainingReleaseError(f"基础发布文件不存在: {path}")
    if path.stat().st_size != entry.get("size_bytes"):
        raise V4_1TrainingReleaseError(f"基础发布文件大小漂移: {path}")
    if sha256_file(path) != entry.get("sha256"):
        raise V4_1TrainingReleaseError(f"基础发布文件 SHA-256 漂移: {path}")
    return path


def _verify_media_row(row: Mapping[str, Any], project_root: Path) -> None:
    candidate_id = str(row.get("candidate_id") or "")
    video = resolve_workspace_artifact(str(row.get("video_path")), project_root)
    if not video.is_file() or sha256_file(video) != row.get("video_sha256"):
        raise V4_1TrainingReleaseError(f"{candidate_id}: 基础发布视频缺失或哈希漂移")
    frames = _require_list(row.get("frames"), f"{candidate_id}.frames")
    if not frames:
        raise V4_1TrainingReleaseError(f"{candidate_id}: 基础发布帧证据为空")
    for index, item in enumerate(frames):
        frame = _require_mapping(item, f"{candidate_id}.frames[{index}]")
        path = resolve_workspace_artifact(str(frame.get("path")), project_root)
        if not path.is_file() or sha256_file(path) != frame.get("sha256"):
            raise V4_1TrainingReleaseError(
                f"{candidate_id}: 基础发布帧[{index}]缺失或哈希漂移"
            )


def _load_base_release(
    *,
    release_dir: Path,
    project_root: Path,
    contract_hash: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    release_dir = Path(release_dir).resolve()
    manifest_path = release_dir / "manifest/release_manifest.json"
    manifest_sha256 = sha256_file(manifest_path)
    manifest = _require_mapping(
        _read_json(manifest_path, "基础发布 manifest"),
        "基础发布 manifest",
    )
    if (
        manifest.get("schema_version") != RELEASE_SCHEMA_VERSION
        or manifest.get("status") != "training_ready"
        or manifest.get("immutable") is not True
        or manifest.get("contract_version") != "tensile-vlm/v4.1"
        or manifest.get("contract_hash") != contract_hash
    ):
        raise V4_1TrainingReleaseError("基础发布身份或状态不满足增量发布要求")
    files = _require_list(manifest.get("files"), "基础发布 files")
    file_index: dict[str, Mapping[str, Any]] = {}
    for raw in files:
        entry = _require_mapping(raw, "基础发布 file entry")
        path = str(entry.get("path") or "")
        if not path or path in file_index:
            raise V4_1TrainingReleaseError("基础发布 files 包含空路径或重复路径")
        file_index[path] = entry
        _verified_release_file(release_dir, entry)
    metadata_entry = file_index.get("metadata/training_candidates.json")
    if metadata_entry is None:
        raise V4_1TrainingReleaseError("基础发布缺少 training_candidates.json")
    metadata_path = release_dir / "metadata/training_candidates.json"
    metadata_sha256 = sha256_file(metadata_path)
    metadata = _require_mapping(
        _read_json(metadata_path, "基础发布 training candidates"),
        "基础发布 training candidates",
    )
    if (
        metadata.get("schema_version") != TRAINING_CANDIDATES_SCHEMA_VERSION
        or metadata.get("contract_hash") != contract_hash
    ):
        raise V4_1TrainingReleaseError("基础发布 training candidates 身份不匹配")
    candidates_raw = _require_list(metadata.get("candidates"), "基础发布 candidates")
    excluded_raw = _require_list(metadata.get("excluded"), "基础发布 excluded")
    candidates = [dict(_require_mapping(row, "基础发布 candidate")) for row in candidates_raw]
    excluded = [dict(_require_mapping(row, "基础发布 excluded row")) for row in excluded_raw]
    candidate_ids = [str(row.get("candidate_id") or "") for row in candidates]
    excluded_ids = [str(row.get("candidate_id") or "") for row in excluded]
    if (
        any(not item for item in candidate_ids + excluded_ids)
        or len(candidate_ids) != len(set(candidate_ids))
        or len(excluded_ids) != len(set(excluded_ids))
        or set(candidate_ids) & set(excluded_ids)
        or metadata.get("candidate_count") != len(candidates)
        or metadata.get("excluded_count") != len(excluded)
    ):
        raise V4_1TrainingReleaseError("基础发布 candidate/excluded 身份或数量非法")
    for row in candidates:
        row["labels"] = canonicalize_v4_1_labels(row.get("labels"))
        _verify_media_row(row, project_root)
    return dict(manifest), candidates, excluded, manifest_sha256, metadata_sha256


def _load_json_artifact(
    path: Path,
    *,
    expected_sha256: Any,
    label: str,
) -> Mapping[str, Any]:
    if sha256_file(path) != expected_sha256:
        raise V4_1TrainingReleaseError(f"{label} SHA-256 漂移")
    return _require_mapping(_read_json(path, label), label)


def _validate_review_record(
    record: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    try:
        normalized = normalize_review_record(record)
    except ValueError as exc:
        raise V4_1TrainingReleaseError(f"{label}非法: {exc}") from exc
    if normalized != dict(record):
        raise V4_1TrainingReleaseError(f"{label}不是规范化人工决定")
    candidate_id = str(candidate["candidate_id"])
    if (
        record.get("clip_id") != candidate_id
        or record.get("source_video") != candidate.get("source_video")
        or (record.get("evidence") or {}).get("media_sha256")
        != candidate.get("video_sha256")
        or record.get("system_proposed_labels")
        != candidate.get("candidate_v4_labels")
        or record.get("review_status") not in TERMINAL_REVIEW_STATUSES
    ):
        raise V4_1TrainingReleaseError(f"{label}与候选媒体、提示或终态绑定不一致")
    return normalized


def _load_combined_review(
    *,
    project_root: Path,
    queue_path: Path,
    routing_manifest_path: Path,
    manual_decisions_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    queue_identity, candidates = load_review_queue(
        queue_path,
        project_root=project_root,
    )
    if (
        queue_identity.get("queue_schema_version") != PHASE2_QUEUE_SCHEMA_VERSION
        or queue_identity.get("review_scope") != "development"
        or queue_identity.get("labels_are_truth") is not False
    ):
        raise V4_1TrainingReleaseError("阶段 2 队列不是 development 非真值提示队列")
    candidate_index = {str(row["candidate_id"]): row for row in candidates}
    queue_ids = list(candidate_index)

    routing = _require_mapping(
        _read_json(routing_manifest_path, "routing manifest"),
        "routing manifest",
    )
    source_queue = _require_mapping(routing.get("source_queue"), "routing.source_queue")
    artifact_hashes = _require_mapping(routing.get("artifacts"), "routing.artifacts")
    if (
        routing.get("schema_version") != ROUTING_SCHEMA_VERSION
        or routing.get("policy_version") != ROUTING_POLICY_VERSION
        or source_queue.get("queue_id") != queue_identity["queue_id"]
        or source_queue.get("sha256") != queue_identity["queue_sha256"]
        or source_queue.get("candidate_count") != len(queue_ids)
    ):
        raise V4_1TrainingReleaseError("routing manifest 与完整 development 队列不匹配")
    route_rows = [
        dict(_require_mapping(row, "routing route"))
        for row in _require_list(routing.get("routes"), "routing.routes")
    ]
    route_index = {str(row.get("candidate_id") or ""): row for row in route_rows}
    if len(route_index) != len(route_rows) or list(route_index) != queue_ids:
        raise V4_1TrainingReleaseError("routing routes 未按队列顺序唯一完整覆盖")

    route_dir = Path(routing_manifest_path).resolve().parent
    existing_payload = _load_json_artifact(
        route_dir / "existing_human_decisions.json",
        expected_sha256=artifact_hashes.get("existing_human_decisions.json"),
        label="existing human decisions",
    )
    historical_payload = _load_json_artifact(
        route_dir / "historical_consensus.json",
        expected_sha256=artifact_hashes.get("historical_consensus.json"),
        label="historical consensus",
    )
    manual_ids = load_manual_candidate_ids(
        routing_manifest_path,
        queue_path=queue_path,
    )
    existing_rows = [
        dict(_require_mapping(row, "existing human record"))
        for row in _require_list(existing_payload.get("records"), "existing records")
    ]
    historical_rows = [
        dict(_require_mapping(row, "historical record"))
        for row in _require_list(historical_payload.get("records"), "historical records")
    ]
    if (
        existing_payload.get("schema_version") != EXISTING_HUMAN_SCHEMA_VERSION
        or historical_payload.get("schema_version") != HISTORICAL_SCHEMA_VERSION
        or existing_payload.get("routing_id") != routing.get("routing_id")
        or historical_payload.get("routing_id") != routing.get("routing_id")
        or existing_payload.get("record_count") != len(existing_rows)
        or historical_payload.get("record_count") != len(historical_rows)
    ):
        raise V4_1TrainingReleaseError("routing 子制品身份或数量不匹配")

    existing_ids = [
        row["candidate_id"]
        for row in route_rows
        if row.get("disposition") == EXISTING_DISPOSITION
    ]
    historical_ids = [
        row["candidate_id"]
        for row in route_rows
        if row.get("disposition") == HISTORICAL_DISPOSITION
    ]
    routed_manual_ids = [
        row["candidate_id"]
        for row in route_rows
        if row.get("disposition") == MANUAL_DISPOSITION
    ]
    if (
        [row.get("clip_id") for row in existing_rows] != existing_ids
        or [row.get("candidate_id") for row in historical_rows] != historical_ids
        or routed_manual_ids != manual_ids
        or set(existing_ids) & set(historical_ids)
        or set(existing_ids) & set(manual_ids)
        or set(historical_ids) & set(manual_ids)
        or set(existing_ids) | set(historical_ids) | set(manual_ids) != set(queue_ids)
    ):
        raise V4_1TrainingReleaseError("三类 review disposition 未互斥完整覆盖队列")

    manual_payload = _require_mapping(
        _read_json(manual_decisions_path, "manual frozen decisions"),
        "manual frozen decisions",
    )
    try:
        validate_review_payload(manual_payload)
    except ValueError as exc:
        raise V4_1TrainingReleaseError(f"manual frozen decisions 非法: {exc}") from exc
    manual_rows = [dict(row) for row in manual_payload["decisions"]]
    if [row.get("clip_id") for row in manual_rows] != manual_ids:
        raise V4_1TrainingReleaseError("manual frozen decisions 未按选择清单完整覆盖")
    manual_summary_path = Path(manual_decisions_path).with_name("summary.json")
    manual_summary = _require_mapping(
        _read_json(manual_summary_path, "manual frozen summary"),
        "manual frozen summary",
    )
    selected_identity, _ = load_review_queue(
        queue_path,
        project_root=project_root,
        candidate_ids=manual_ids,
    )
    expected_summary_identity = {
        key: value for key, value in selected_identity.items() if key != "queue_path"
    }
    status_counts = dict(
        sorted(Counter(row["review_status"] for row in manual_rows).items())
    )
    if (
        manual_summary.get("batch_id") != manual_payload.get("batch_id")
        or manual_summary.get("decision_count") != len(manual_rows)
        or manual_summary.get("queue_identity") != expected_summary_identity
        or manual_summary.get("status_counts") != status_counts
        or (
            (manual_summary.get("artifacts") or {}).get("decisions.json") or {}
        ).get("sha256")
        != sha256_file(manual_decisions_path)
    ):
        raise V4_1TrainingReleaseError("manual frozen summary 与决定或选择身份不一致")

    existing_index = {str(row["clip_id"]): row for row in existing_rows}
    historical_index = {str(row["candidate_id"]): row for row in historical_rows}
    manual_index = {str(row["clip_id"]): row for row in manual_rows}
    combined_records: list[dict[str, Any]] = []
    effective: dict[str, dict[str, Any]] = {}
    for candidate_id in queue_ids:
        candidate = candidate_index[candidate_id]
        route = route_index[candidate_id]
        disposition = route.get("disposition")
        status: str | None = None
        labels: dict[str, Any] | None
        provenance: dict[str, Any]
        if disposition == EXISTING_DISPOSITION:
            decision = _validate_review_record(
                existing_index[candidate_id],
                candidate=candidate,
                label=f"{candidate_id} existing human decision",
            )
            status = str(decision["review_status"])
            labels = decision.get("effective_labels")
            if route.get("labels") != labels:
                raise V4_1TrainingReleaseError(
                    f"{candidate_id}: existing route labels 与人工决定不一致"
                )
            provenance = {
                "kind": "current_human",
                "artifact": "existing_human_decisions.json",
            }
        elif disposition == HISTORICAL_DISPOSITION:
            historical = historical_index[candidate_id]
            if historical != route:
                raise V4_1TrainingReleaseError(
                    f"{candidate_id}: historical artifact 与 route 不一致"
                )
            labels = canonicalize_v4_1_labels(historical.get("labels"))
            references = historical.get("historical_reference_ids")
            if (
                labels != candidate.get("candidate_v4_labels")
                or not isinstance(references, list)
                or not references
                or not all(isinstance(item, str) and item for item in references)
            ):
                raise V4_1TrainingReleaseError(
                    f"{candidate_id}: historical consensus 标签或引用非法"
                )
            provenance = {
                "kind": "historical_consensus",
                "previous_review_batch_id": (
                    routing.get("previous_review_batch") or {}
                ).get("batch_id"),
                "historical_reference_ids": list(references),
            }
        elif disposition == MANUAL_DISPOSITION:
            decision = _validate_review_record(
                manual_index[candidate_id],
                candidate=candidate,
                label=f"{candidate_id} manual decision",
            )
            status = str(decision["review_status"])
            labels = decision.get("effective_labels")
            provenance = {
                "kind": "current_human",
                "review_batch_id": manual_payload["batch_id"],
            }
        else:
            raise V4_1TrainingReleaseError(
                f"{candidate_id}: 未知 routing disposition: {disposition!r}"
            )
        excluded = status in {"dropped", "needs_regenerate"}
        if excluded:
            labels = None
        elif labels is None:
            raise V4_1TrainingReleaseError(f"{candidate_id}: 有效候选缺少最终标签")
        else:
            labels = canonicalize_v4_1_labels(labels)
        combined = {
            "candidate_id": candidate_id,
            "source_video": candidate["source_video"],
            "disposition": disposition,
            "review_status": status,
            "effective_labels": labels,
            "excluded": excluded,
            "video_sha256": candidate["video_sha256"],
            "effective_frame_signature": candidate.get("effective_frame_signature"),
            "provenance": provenance,
        }
        combined_records.append(combined)
        effective[candidate_id] = combined

    counts = Counter(row["disposition"] for row in combined_records)
    status_counts = Counter(
        str(row["review_status"])
        for row in combined_records
        if row["review_status"] is not None
    )
    seed = {
        "queue_sha256": queue_identity["queue_sha256"],
        "routing_manifest_sha256": sha256_file(routing_manifest_path),
        "manual_decisions_sha256": sha256_file(manual_decisions_path),
        "manual_summary_sha256": sha256_file(manual_summary_path),
        "records": combined_records,
    }
    combined_id = f"combined-review-decisions-{_sha256_bytes(_canonical_bytes(seed))[:12]}"
    manifest = {
        "schema_version": COMBINED_REVIEW_SCHEMA_VERSION,
        "combined_id": combined_id,
        "contract_hash": queue_identity["contract_hash"],
        "queue_id": queue_identity["queue_id"],
        "routing_id": routing["routing_id"],
        "manual_review_batch_id": manual_payload["batch_id"],
        "candidate_count": len(combined_records),
        "admitted_count": sum(not row["excluded"] for row in combined_records),
        "excluded_count": sum(row["excluded"] for row in combined_records),
        "counts": {
            EXISTING_DISPOSITION: counts[EXISTING_DISPOSITION],
            HISTORICAL_DISPOSITION: counts[HISTORICAL_DISPOSITION],
            MANUAL_DISPOSITION: counts[MANUAL_DISPOSITION],
            "review_status": dict(sorted(status_counts.items())),
        },
        "inputs": {
            "queue_sha256": queue_identity["queue_sha256"],
            "routing_manifest_sha256": sha256_file(routing_manifest_path),
            "existing_human_decisions_sha256": artifact_hashes[
                "existing_human_decisions.json"
            ],
            "historical_consensus_sha256": artifact_hashes[
                "historical_consensus.json"
            ],
            "manual_candidate_ids_sha256": artifact_hashes[
                "manual_candidate_ids.json"
            ],
            "manual_decisions_sha256": sha256_file(manual_decisions_path),
            "manual_summary_sha256": sha256_file(manual_summary_path),
        },
        "records": combined_records,
    }
    identities = {
        "queue_identity": queue_identity,
        "routing_id": routing["routing_id"],
        "manual_batch_id": manual_payload["batch_id"],
        "manual_summary_path": manual_summary_path,
    }
    return manifest, effective, identities


def _validate_audit(
    *,
    audit_path: Path,
    base_manifest_sha256: str,
    base_candidates_sha256: str,
    materialized_path: Path,
    queue_identity: Mapping[str, Any],
    base_rows: list[dict[str, Any]],
    phase2_candidates: list[dict[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    audit = _require_mapping(
        _read_json(audit_path, "effective view audit"),
        "effective view audit",
    )
    completion = _require_mapping(audit.get("completion"), "audit.completion")
    leakage = _require_mapping(audit.get("leakage"), "audit.leakage")
    identity = _require_mapping(audit.get("identity"), "audit.identity")
    inputs = _require_mapping(audit.get("inputs"), "audit.inputs")
    policy = _require_mapping(identity.get("policy"), "audit.identity.policy")
    if (
        audit.get("schema_version") != EFFECTIVE_VIEW_AUDIT_SCHEMA_VERSION
        or audit.get("audit_id") != queue_identity.get("audit_id")
        or completion.get("ready_for_human_review") is not True
        or completion.get("all_candidates_have_effective_frame_signatures") is not True
        or completion.get("fold_and_test_leakage_check_passed") is not True
        or completion.get("creates_training_release") is not False
        or leakage.get("passed") is not True
        or leakage.get("development_test_source_overlap") != []
        or leakage.get("development_test_signature_overlap") != []
        or (_require_mapping(leakage.get("fold_source_isolation"), "fold isolation")).get(
            "passed"
        )
        is not True
        or policy.get("automatic_labels_are_truth") is not False
        or policy.get("v3_test_labels_are_truth") is not False
    ):
        raise V4_1TrainingReleaseError("有效视图审计未满足发布隔离门")
    expected_inputs = {
        "release_manifest": base_manifest_sha256,
        "training_candidates": base_candidates_sha256,
        "experimental_materialized": sha256_file(materialized_path),
    }
    for key, expected in expected_inputs.items():
        binding = _require_mapping(inputs.get(key), f"audit.inputs.{key}")
        if binding.get("sha256") != expected:
            raise V4_1TrainingReleaseError(f"有效视图审计输入 {key} 与发布输入漂移")
    coverage = _require_mapping(audit.get("coverage"), "audit.coverage")
    automatic = _require_mapping(
        coverage.get("automatic_candidate"),
        "audit.coverage.automatic_candidate",
    )
    if (
        automatic.get("candidate_count") != len(phase2_candidates)
        or automatic.get("duplicate_exact_signature_count") != 0
        or automatic.get("unique_effective_frame_signatures") != len(phase2_candidates)
    ):
        raise V4_1TrainingReleaseError("阶段 2 候选有效帧签名不唯一或数量漂移")
    caps = _require_mapping(audit.get("source_cap_violations"), "source cap violations")
    if caps.get("automatic_candidate") != {}:
        raise V4_1TrainingReleaseError("阶段 2 候选存在 source cap 违规")

    inventory = [
        _require_mapping(row, "audit inventory row")
        for row in _require_list(audit.get("inventory"), "audit.inventory")
    ]
    inventory_index = {str(row.get("candidate_id") or ""): row for row in inventory}
    if len(inventory_index) != len(inventory):
        raise V4_1TrainingReleaseError("audit inventory candidate_id 非法或重复")
    base_ids = {str(row["candidate_id"]) for row in base_rows}
    phase2_ids = {str(row["candidate_id"]) for row in phase2_candidates}
    if base_ids & phase2_ids:
        raise V4_1TrainingReleaseError("基础发布与阶段 2 candidate_id 重叠")
    if not base_ids | phase2_ids <= set(inventory_index):
        raise V4_1TrainingReleaseError("audit inventory 未覆盖全部 development 候选")

    signatures: dict[str, Mapping[str, Any]] = {}
    phase2_index = {str(row["candidate_id"]): row for row in phase2_candidates}
    for candidate_id in base_ids | phase2_ids:
        audited = inventory_index[candidate_id]
        signature = audited.get("effective_frame_signature")
        if not isinstance(signature, str) or len(signature) != 64:
            raise V4_1TrainingReleaseError(f"{candidate_id}: 有效帧签名非法")
        expected = (
            next(row for row in base_rows if row["candidate_id"] == candidate_id)
            if candidate_id in base_ids
            else phase2_index[candidate_id]
        )
        if (
            audited.get("source_video") != expected.get("source_video")
            or audited.get("video_sha256") != expected.get("video_sha256")
        ):
            raise V4_1TrainingReleaseError(f"{candidate_id}: audit 媒体或来源绑定漂移")
        signatures[candidate_id] = audited

    for cluster_raw in _require_list(
        audit.get("near_duplicate_clusters"),
        "audit.near_duplicate_clusters",
    ):
        cluster = _require_mapping(cluster_raw, "near duplicate cluster")
        member_ids = _require_list(cluster.get("candidate_ids"), "cluster candidate_ids")
        member_sources = {
            inventory_index[str(candidate_id)].get("source_video")
            for candidate_id in member_ids
            if str(candidate_id) in inventory_index
        }
        if len(member_sources) > 1:
            raise V4_1TrainingReleaseError(
                f"{cluster.get('cluster_id')}: 近重复视图跨 source"
            )
    return signatures


def _dataset_from_row(
    row: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    return _dataset_row(
        {"_release_video_path": row["video_path"]},
        row["labels"],
        contract,
    )


def build_v4_1_phase2_training_release(
    *,
    project_root: Path,
    base_release_dir: Path,
    materialized_path: Path,
    media_manifest_path: Path,
    queue_path: Path,
    routing_manifest_path: Path,
    manual_decisions_path: Path,
    audit_path: Path,
    contract_path: Path,
    splits_dir: Path,
    releases_dir: Path,
    validate_only: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Validate and optionally publish the immutable Phase 2 development release."""
    project_root = Path(project_root).resolve()
    contract, contract_file_sha256 = _contract_identity(contract_path)
    (
        base_manifest,
        base_rows,
        base_excluded,
        base_manifest_sha256,
        base_candidates_sha256,
    ) = _load_base_release(
        release_dir=base_release_dir,
        project_root=project_root,
        contract_hash=contract["contract_hash"],
    )
    media_manifest, phase2_candidates = _load_materialized(
        materialized_path,
        media_manifest_path,
        project_root,
    )
    combined_review, combined_index, review_identities = _load_combined_review(
        project_root=project_root,
        queue_path=queue_path,
        routing_manifest_path=routing_manifest_path,
        manual_decisions_path=manual_decisions_path,
    )
    queue_identity = review_identities["queue_identity"]
    if (
        queue_identity.get("media_id") != media_manifest.get("media_id")
        or set(combined_index)
        != {str(row["candidate_id"]) for row in phase2_candidates}
    ):
        raise V4_1TrainingReleaseError("review queue 与阶段 2 materialized 媒体不一致")
    audit_rows = _validate_audit(
        audit_path=audit_path,
        base_manifest_sha256=base_manifest_sha256,
        base_candidates_sha256=base_candidates_sha256,
        materialized_path=materialized_path,
        queue_identity=queue_identity,
        base_rows=base_rows,
        phase2_candidates=phase2_candidates,
    )
    for row in base_rows:
        audited = audit_rows[str(row["candidate_id"])]
        row["effective_frame_signature"] = audited["effective_frame_signature"]
        row["effective_frame_start"] = audited.get("effective_frame_start")
        row["effective_frame_end"] = audited.get("effective_frame_end")

    incremental_rows: list[dict[str, Any]] = []
    incremental_excluded: list[dict[str, Any]] = []
    for candidate in phase2_candidates:
        candidate_id = str(candidate["candidate_id"])
        decision = combined_index[candidate_id]
        audited = audit_rows[candidate_id]
        if decision["effective_frame_signature"] != audited["effective_frame_signature"]:
            raise V4_1TrainingReleaseError(f"{candidate_id}: queue 与 audit 帧签名漂移")
        if decision["excluded"]:
            incremental_excluded.append(
                {
                    "candidate_id": candidate_id,
                    "source_video": candidate["source_video"],
                    "review_status": decision["review_status"],
                    "review_disposition": decision["disposition"],
                }
            )
            continue
        incremental_rows.append(
            {
                "candidate_id": candidate_id,
                "source_video": candidate["source_video"],
                "video_path": candidate["_release_video_path"],
                "video_sha256": candidate["video_sha256"],
                "frames": candidate["_release_frames"],
                "actual_sampled_timestamps": candidate["_sampled_timestamps"],
                "processor_fingerprint": candidate.get("processor_fingerprint"),
                "effective_frame_signature": audited["effective_frame_signature"],
                "effective_frame_start": audited.get("effective_frame_start"),
                "effective_frame_end": audited.get("effective_frame_end"),
                "labels": canonicalize_v4_1_labels(decision["effective_labels"]),
                "label_source": (
                    "historical_consensus"
                    if decision["disposition"] == HISTORICAL_DISPOSITION
                    else "current_human_review"
                ),
                "review_disposition": decision["disposition"],
                "review_status": decision["review_status"],
                "review_batch_id": (
                    review_identities["manual_batch_id"]
                    if decision["disposition"] == MANUAL_DISPOSITION
                    else None
                ),
                "label_provenance": decision["provenance"],
            }
        )

    finalized = base_rows + incremental_rows
    excluded = base_excluded + incremental_excluded
    candidate_ids = [str(row["candidate_id"]) for row in finalized]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise V4_1TrainingReleaseError("最终 development candidate_id 重复")
    splits, split_hashes = _load_splits(splits_dir)
    development_sources = {str(row["source_video"]) for row in finalized}
    for fold in range(3):
        assigned = splits[f"fold_{fold}_train"] | splits[f"fold_{fold}_val"]
        if development_sources - assigned:
            raise V4_1TrainingReleaseError(
                f"fold_{fold}: 存在未分配 development 源视频"
            )

    candidate_rows = {
        "schema_version": TRAINING_CANDIDATES_SCHEMA_VERSION,
        "contract_version": contract["contract_version"],
        "contract_hash": contract["contract_hash"],
        "media_id": media_manifest["media_id"],
        "queue_id": queue_identity["queue_id"],
        "review_batch_id": review_identities["manual_batch_id"],
        "base_release_id": base_manifest["release_id"],
        "combined_review_id": combined_review["combined_id"],
        "candidate_count": len(finalized),
        "excluded_count": len(excluded),
        "candidates": finalized,
        "excluded": excluded,
    }
    files: dict[str, bytes] = {
        "metadata/training_candidates.json": _pretty_bytes(candidate_rows),
        "metadata/combined_review_decisions.json": _pretty_bytes(combined_review),
        "dataset_info.json": _pretty_bytes(_registry()),
    }
    split_counts: dict[str, int] = {}
    for fold in range(3):
        for split, directory in (("train", "train"), ("val", "validation")):
            name = f"fold_{fold}_{split}"
            selected = [
                row for row in finalized if row["source_video"] in splits[name]
            ]
            split_counts[name] = len(selected)
            files[f"datasets/{directory}/fold_{fold}.json"] = _pretty_bytes(
                [_dataset_from_row(row, contract) for row in selected]
            )

    provenance_counts = Counter(str(row.get("label_source")) for row in finalized)
    review_status_counts = Counter(
        str(row.get("review_status"))
        for row in finalized
        if row.get("review_status") is not None
    )
    delta = {
        "schema_version": DELTA_REPORT_SCHEMA_VERSION,
        "base_release_id": base_manifest["release_id"],
        "base_release_manifest_sha256": base_manifest_sha256,
        "base_published_candidates": len(base_rows),
        "phase2_review_candidates": len(phase2_candidates),
        "phase2_admitted_candidates": len(incremental_rows),
        "phase2_excluded_candidates": len(incremental_excluded),
        "final_published_candidates": len(finalized),
        "candidate_id_overlap": [],
        "phase2_excluded": incremental_excluded,
        "phase2_dispositions": combined_review["counts"],
        "label_distributions": {
            "base": {
                field: _distribution(base_rows, field) for field in V4_1_LABEL_FIELDS
            },
            "incremental": {
                field: _distribution(incremental_rows, field)
                for field in V4_1_LABEL_FIELDS
            },
            "final": {
                field: _distribution(finalized, field) for field in V4_1_LABEL_FIELDS
            },
        },
    }
    files["reports/delta_report.json"] = _pretty_bytes(delta)
    quality = {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "status": "passed",
        "error_count": 0,
        "warning_count": 0,
        "counts": {
            "base_published_candidates": len(base_rows),
            "materialized_candidates": len(phase2_candidates),
            "reviewed_candidates": (
                int(base_manifest["counts"]["reviewed_candidates"])
                + combined_review["counts"][EXISTING_DISPOSITION]
                + combined_review["counts"][MANUAL_DISPOSITION]
            ),
            "automatic_unreviewed_candidates": provenance_counts[
                "automatic_validation"
            ],
            "historical_consensus_candidates": provenance_counts[
                "historical_consensus"
            ],
            "published_candidates": len(finalized),
            "excluded_candidates": len(excluded),
            "phase2_excluded_candidates": len(incremental_excluded),
            "human_approved": review_status_counts["approved"],
            "human_corrected": review_status_counts["corrected"],
            "splits": split_counts,
        },
        "distributions": {
            field: _distribution(finalized, field) for field in V4_1_LABEL_FIELDS
        },
        "checks": {
            "base_release_verified_immutable": True,
            "contract_bound": True,
            "media_manifest_bound": True,
            "all_media_hashes_verified": True,
            "review_dispositions_mutually_exclusive_and_complete": True,
            "historical_consensus_not_counted_as_current_human": True,
            "phase2_queue_fully_decided": True,
            "effective_frame_signatures_unique_in_phase2": True,
            "source_and_near_duplicate_split_isolation": True,
            "development_sealed_test_source_isolation": True,
            "frame_window_labels_are_authoritative": True,
        },
    }
    files["reports/quality_report.json"] = _pretty_bytes(quality)

    seed = {
        "data_version": DATA_VERSION,
        "contract_hash": contract["contract_hash"],
        "contract_file_sha256": contract_file_sha256,
        "base_release_id": base_manifest["release_id"],
        "base_release_manifest_sha256": base_manifest_sha256,
        "base_training_candidates_sha256": base_candidates_sha256,
        "audit_sha256": sha256_file(audit_path),
        "materialized_sha256": sha256_file(materialized_path),
        "media_manifest_sha256": sha256_file(media_manifest_path),
        "queue_sha256": queue_identity["queue_sha256"],
        "routing_manifest_sha256": sha256_file(routing_manifest_path),
        "manual_decisions_sha256": sha256_file(manual_decisions_path),
        "combined_review_sha256": _sha256_bytes(
            files["metadata/combined_review_decisions.json"]
        ),
        "split_hashes": split_hashes,
        "training_candidates_sha256": _sha256_bytes(
            files["metadata/training_candidates.json"]
        ),
    }
    release_id = f"v{DATA_VERSION}-{_sha256_bytes(_canonical_bytes(seed))[:12]}"
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
        "base_release_id": base_manifest["release_id"],
        "combined_review_id": combined_review["combined_id"],
        "source_review_batch_id": review_identities["manual_batch_id"],
        "source_queue_id": queue_identity["queue_id"],
        "source_media_id": media_manifest["media_id"],
        "counts": quality["counts"],
        "provenance": seed,
        "files": file_manifest,
    }
    release_dir = Path(releases_dir) / release_id
    if not validate_only:
        _write_release(release_dir, files, manifest, collection_dir=releases_dir)
        if sha256_file(Path(base_release_dir) / "manifest/release_manifest.json") != base_manifest_sha256:
            raise V4_1TrainingReleaseError("增量发布期间基础发布 manifest 发生漂移")
    return release_dir, manifest
