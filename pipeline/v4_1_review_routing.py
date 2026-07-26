"""Route a V4.1 review queue using one frozen previous review batch."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.data_roots import DataRootError, workspace_portable_path
from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_labels import canonicalize_v4_1_labels
from pipeline.v4_1_review_decisions import (
    canonical_json_bytes,
    validate_review_payload,
)
from pipeline.v4_1_review_workflow import (
    load_draft,
    load_review_queue,
    save_draft,
)

ROUTING_SCHEMA_VERSION = "tensile-vlm-v4.1-history-review-routing/v1"
HISTORICAL_SCHEMA_VERSION = "tensile-vlm-v4.1-historical-consensus/v1"
EXISTING_HUMAN_SCHEMA_VERSION = "tensile-vlm-v4.1-existing-human-review/v1"
MANUAL_SELECTION_SCHEMA_VERSION = "tensile-vlm-v4.1-manual-review-selection/v1"
ROUTING_POLICY_VERSION = "history-review-routing/1.0"
MANUAL_DISPOSITION = "manual_review"
HISTORICAL_DISPOSITION = "historical_consensus"
EXISTING_DISPOSITION = "existing_human"


class ReviewRoutingError(ValueError):
    """The current queue cannot be safely routed from review history."""


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReviewRoutingError(f"{label}不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewRoutingError(f"{label}不是合法 JSON: {path}: {exc}") from exc


def _content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _candidate_ids_sha256(candidate_ids: Iterable[str]) -> str:
    payload = json.dumps(
        list(candidate_ids), ensure_ascii=False, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _portable_path(path: Path, project_root: Path) -> str:
    try:
        return workspace_portable_path(path, project_root)
    except DataRootError:
        return str(Path(path).resolve())


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> bool:
    content = canonical_json_bytes(payload)
    path = Path(path)
    if path.exists():
        if path.read_bytes() == content:
            return False
        raise FileExistsError(f"拒绝覆盖已有历史审查分流制品: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = handle.name
        os.replace(temporary, path)
        return True
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def semantic_window_role(value: Mapping[str, Any] | str) -> str | None:
    """Normalize the role used to compare current and historical candidates."""
    if isinstance(value, Mapping):
        explicit = value.get("window_role")
        if explicit in {"transition", "post_event", "pre_event"}:
            return str(explicit)
        candidate_id = str(value.get("candidate_id") or value.get("clip_id") or "")
    else:
        candidate_id = str(value)
    if "_transition_" in candidate_id:
        return "transition"
    if "_post_event_" in candidate_id or "_v3_post_" in candidate_id:
        return "post_event"
    if "_pre_event_" in candidate_id or "_v3_pre_" in candidate_id:
        return "pre_event"
    return None


def _canonical_label_key(labels: Mapping[str, Any]) -> str:
    return json.dumps(
        canonicalize_v4_1_labels(labels),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def route_review_candidates(
    candidates: Iterable[Mapping[str, Any]],
    previous_decisions: Iterable[Mapping[str, Any]],
    current_decisions: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Apply the fixed, fail-closed history routing rules."""
    candidate_rows = [dict(item) for item in candidates]
    candidate_ids = [str(item.get("candidate_id") or "") for item in candidate_rows]
    if any(not item for item in candidate_ids) or len(candidate_ids) != len(
        set(candidate_ids)
    ):
        raise ReviewRoutingError("当前队列 candidate_id 非法或重复")
    previous_rows = [dict(item) for item in previous_decisions]
    previous_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in previous_rows:
        source = str(record.get("source_video") or "")
        if not source:
            raise ReviewRoutingError("上一轮决定缺少 source_video")
        previous_by_source[source].append(record)
    current = {str(key): dict(value) for key, value in (current_decisions or {}).items()}
    unknown_current = sorted(set(current) - set(candidate_ids))
    if unknown_current:
        raise ReviewRoutingError(
            f"当前草稿包含队列外候选: {unknown_current[:5]}"
        )

    risky_sources = {
        source
        for source, records in previous_by_source.items()
        if any(record.get("review_status") != "approved" for record in records)
    }
    consensus: dict[tuple[str, str], tuple[dict[str, Any], list[str]]] = {}
    for source, records in previous_by_source.items():
        by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            if record.get("review_status") != "approved":
                continue
            role = semantic_window_role(str(record.get("clip_id") or ""))
            if role is not None:
                by_role[role].append(record)
        for role, role_records in by_role.items():
            labels_by_key = {
                _canonical_label_key(record["effective_labels"]): record[
                    "effective_labels"
                ]
                for record in role_records
                if isinstance(record.get("effective_labels"), Mapping)
            }
            if len(labels_by_key) == 1:
                only = canonicalize_v4_1_labels(next(iter(labels_by_key.values())))
                consensus[(source, role)] = (
                    only,
                    sorted(str(record["clip_id"]) for record in role_records),
                )

    routed: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        candidate_id = str(candidate["candidate_id"])
        source = str(candidate.get("source_video") or "")
        proposed = canonicalize_v4_1_labels(candidate.get("candidate_v4_labels"))
        base = {
            "candidate_id": candidate_id,
            "source_video": source,
            "semantic_window_role": semantic_window_role(candidate),
        }
        if candidate_id in current:
            routed.append(
                {
                    **base,
                    "disposition": EXISTING_DISPOSITION,
                    "reason": "current_human_decision_exists",
                    "labels": current[candidate_id].get("effective_labels"),
                    "historical_reference_ids": [],
                }
            )
            continue
        if source not in previous_by_source:
            routed.append(
                {
                    **base,
                    "disposition": MANUAL_DISPOSITION,
                    "reason": "no_previous_source_history",
                    "labels": None,
                    "historical_reference_ids": [],
                }
            )
            continue
        if source in risky_sources:
            statuses = sorted(
                {str(item.get("review_status")) for item in previous_by_source[source]}
            )
            routed.append(
                {
                    **base,
                    "disposition": MANUAL_DISPOSITION,
                    "reason": "previous_source_has_non_approved_status",
                    "previous_statuses": statuses,
                    "labels": None,
                    "historical_reference_ids": [],
                }
            )
            continue
        role = semantic_window_role(candidate)
        if role is None:
            routed.append(
                {
                    **base,
                    "disposition": MANUAL_DISPOSITION,
                    "reason": "unknown_semantic_window_role",
                    "labels": None,
                    "historical_reference_ids": [],
                }
            )
            continue
        role_consensus = consensus.get((source, role))
        if role_consensus is None:
            routed.append(
                {
                    **base,
                    "disposition": MANUAL_DISPOSITION,
                    "reason": "no_unique_role_consensus",
                    "labels": None,
                    "historical_reference_ids": [],
                }
            )
            continue
        historical_labels, reference_ids = role_consensus
        if historical_labels != proposed:
            routed.append(
                {
                    **base,
                    "disposition": MANUAL_DISPOSITION,
                    "reason": "historical_consensus_disagrees_with_current_hint",
                    "labels": None,
                    "historical_labels": historical_labels,
                    "current_hint_labels": proposed,
                    "historical_reference_ids": reference_ids,
                }
            )
            continue
        routed.append(
            {
                **base,
                "disposition": HISTORICAL_DISPOSITION,
                "reason": "approved_source_role_consensus_matches_current_hint",
                "labels": historical_labels,
                "historical_reference_ids": reference_ids,
            }
        )
    return routed


def _validate_previous_batch(
    path: Path,
    *,
    expected_contract_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    payload = _load_json(path, "上一轮冻结 review batch")
    if not isinstance(payload, Mapping):
        raise ReviewRoutingError("上一轮冻结 review batch 必须是对象")
    try:
        validate_review_payload(payload)
    except ValueError as exc:
        raise ReviewRoutingError(f"上一轮 review batch 非法: {exc}") from exc
    if not str(payload.get("batch_id") or "").startswith("review-batch-"):
        raise ReviewRoutingError("上一轮 review batch 未使用冻结 batch_id")
    summary_path = Path(path).with_name("summary.json")
    summary = _load_json(summary_path, "上一轮冻结 review summary")
    if not isinstance(summary, Mapping):
        raise ReviewRoutingError("上一轮冻结 review summary 必须是对象")
    queue_identity = summary.get("queue_identity")
    artifacts = summary.get("artifacts")
    decisions_artifact = (
        artifacts.get("decisions.json") if isinstance(artifacts, Mapping) else None
    )
    if (
        summary.get("batch_id") != payload.get("batch_id")
        or summary.get("decision_count") != len(payload["decisions"])
        or not isinstance(queue_identity, Mapping)
        or queue_identity.get("contract_hash") != expected_contract_hash
        or not isinstance(decisions_artifact, Mapping)
        or decisions_artifact.get("sha256") != sha256_file(path)
    ):
        raise ReviewRoutingError("上一轮 review summary 与决定、契约或数量不匹配")
    return dict(payload), dict(summary), summary_path


def build_history_review_route(
    *,
    queue_path: Path,
    previous_decisions_path: Path,
    project_root: Path,
    output_root: Path,
    review_decisions_root: Path,
    current_draft_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create immutable routing artifacts and a resumable manual-only draft."""
    queue_path = Path(queue_path).resolve()
    previous_decisions_path = Path(previous_decisions_path).resolve()
    full_identity, candidates = load_review_queue(
        queue_path,
        project_root=project_root,
    )
    previous, _previous_summary, previous_summary_path = _validate_previous_batch(
        previous_decisions_path,
        expected_contract_hash=str(full_identity["contract_hash"]),
    )
    current_decisions: dict[str, dict[str, Any]] = {}
    current_draft_sha256: str | None = None
    if current_draft_path is not None:
        if not Path(current_draft_path).is_file():
            raise ReviewRoutingError(
                f"当前审查草稿不存在: {current_draft_path}"
            )
        current_draft_path = Path(current_draft_path).resolve()
        current_decisions = load_draft(current_draft_path, full_identity)
        current_draft_sha256 = sha256_file(current_draft_path)
    routed = route_review_candidates(
        candidates,
        previous["decisions"],
        current_decisions,
    )
    manual_ids = [
        item["candidate_id"]
        for item in routed
        if item["disposition"] == MANUAL_DISPOSITION
    ]
    historical_records = [
        item for item in routed if item["disposition"] == HISTORICAL_DISPOSITION
    ]
    existing_ids = [
        item["candidate_id"]
        for item in routed
        if item["disposition"] == EXISTING_DISPOSITION
    ]
    existing_records = [
        current_decisions[candidate_id] for candidate_id in existing_ids
    ]
    seed = {
        "policy_version": ROUTING_POLICY_VERSION,
        "queue_sha256": sha256_file(queue_path),
        "previous_decisions_sha256": sha256_file(previous_decisions_path),
        "previous_summary_sha256": sha256_file(previous_summary_path),
        "current_draft_sha256": current_draft_sha256,
        "routes": routed,
    }
    routing_id = f"history-review-route-{_content_hash(seed)[:12]}"
    route_dir = Path(output_root) / routing_id
    manual_selection = {
        "schema_version": MANUAL_SELECTION_SCHEMA_VERSION,
        "routing_id": routing_id,
        "queue_id": full_identity["queue_id"],
        "queue_sha256": full_identity["queue_sha256"],
        "candidate_count": len(manual_ids),
        "candidate_ids_sha256": _candidate_ids_sha256(manual_ids),
        "candidate_ids": manual_ids,
    }
    historical = {
        "schema_version": HISTORICAL_SCHEMA_VERSION,
        "routing_id": routing_id,
        "policy_version": ROUTING_POLICY_VERSION,
        "record_count": len(historical_records),
        "records": historical_records,
    }
    existing = {
        "schema_version": EXISTING_HUMAN_SCHEMA_VERSION,
        "routing_id": routing_id,
        "record_count": len(existing_records),
        "records": existing_records,
    }
    _write_immutable_json(route_dir / "manual_candidate_ids.json", manual_selection)
    _write_immutable_json(route_dir / "historical_consensus.json", historical)
    _write_immutable_json(route_dir / "existing_human_decisions.json", existing)

    if manual_ids:
        manual_identity, _ = load_review_queue(
            queue_path,
            project_root=project_root,
            candidate_ids=manual_ids,
        )
    else:
        manual_identity = {
            **full_identity,
            "selected_candidate_ids": [],
            "selected_candidate_ids_sha256": _candidate_ids_sha256([]),
        }
    manual_workspace = (
        Path(review_decisions_root)
        / full_identity["queue_id"]
        / f"workspace-{manual_identity['selected_candidate_ids_sha256'][:12]}"
    )
    manual_draft_path = manual_workspace / "draft.json"
    migrated = {
        candidate_id: current_decisions[candidate_id]
        for candidate_id in manual_ids
        if candidate_id in current_decisions
    }
    if manual_draft_path.exists():
        load_draft(manual_draft_path, manual_identity)
    else:
        save_draft(manual_draft_path, manual_identity, migrated)

    counts = Counter(item["disposition"] for item in routed)
    manifest = {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "routing_id": routing_id,
        "policy_version": ROUTING_POLICY_VERSION,
        "source_queue": {
            "path": _portable_path(queue_path, project_root),
            "queue_id": full_identity["queue_id"],
            "sha256": full_identity["queue_sha256"],
            "candidate_count": full_identity["full_queue_count"],
        },
        "previous_review_batch": {
            "path": _portable_path(previous_decisions_path, project_root),
            "batch_id": previous["batch_id"],
            "sha256": sha256_file(previous_decisions_path),
            "summary_path": _portable_path(previous_summary_path, project_root),
            "summary_sha256": sha256_file(previous_summary_path),
        },
        "current_draft": {
            "path": (
                _portable_path(Path(current_draft_path), project_root)
                if current_draft_path is not None
                else None
            ),
            "sha256": current_draft_sha256,
        },
        "counts": {
            EXISTING_DISPOSITION: counts[EXISTING_DISPOSITION],
            HISTORICAL_DISPOSITION: counts[HISTORICAL_DISPOSITION],
            MANUAL_DISPOSITION: counts[MANUAL_DISPOSITION],
            "total": len(routed),
        },
        "artifacts": {
            "existing_human_decisions.json": sha256_file(
                route_dir / "existing_human_decisions.json"
            ),
            "historical_consensus.json": sha256_file(
                route_dir / "historical_consensus.json"
            ),
            "manual_candidate_ids.json": sha256_file(
                route_dir / "manual_candidate_ids.json"
            ),
        },
        "manual_review": {
            "candidate_ids_sha256": manual_identity[
                "selected_candidate_ids_sha256"
            ],
            "draft_path": _portable_path(manual_draft_path, project_root),
            "draft_candidate_count": len(manual_ids),
            "migrated_current_decision_count": len(migrated),
        },
        "routes": routed,
    }
    _write_immutable_json(route_dir / "routing_manifest.json", manifest)
    return route_dir, manifest


def load_manual_candidate_ids(
    routing_manifest_path: Path,
    *,
    queue_path: Path,
) -> list[str]:
    """Validate a routing manifest and return its manual-only candidate IDs."""
    routing_manifest_path = Path(routing_manifest_path).resolve()
    manifest = _load_json(routing_manifest_path, "历史审查 routing manifest")
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema_version") != ROUTING_SCHEMA_VERSION
        or manifest.get("policy_version") != ROUTING_POLICY_VERSION
    ):
        raise ReviewRoutingError("历史审查 routing manifest schema_version 不匹配")
    source = manifest.get("source_queue")
    artifacts = manifest.get("artifacts")
    if not isinstance(source, Mapping) or not isinstance(artifacts, Mapping):
        raise ReviewRoutingError("历史审查 routing manifest 缺少身份绑定")
    queue_path = Path(queue_path).resolve()
    if sha256_file(queue_path) != source.get("sha256"):
        raise ReviewRoutingError("人工子队列绑定的完整队列已漂移")
    selection_path = routing_manifest_path.parent / "manual_candidate_ids.json"
    if sha256_file(selection_path) != artifacts.get("manual_candidate_ids.json"):
        raise ReviewRoutingError("manual_candidate_ids.json 已漂移")
    selection = _load_json(selection_path, "人工候选清单")
    if (
        not isinstance(selection, Mapping)
        or selection.get("schema_version") != MANUAL_SELECTION_SCHEMA_VERSION
        or selection.get("routing_id") != manifest.get("routing_id")
        or selection.get("queue_sha256") != source.get("sha256")
        or selection.get("queue_id") != source.get("queue_id")
    ):
        raise ReviewRoutingError("人工候选清单身份不匹配")
    candidate_ids = selection.get("candidate_ids")
    if not isinstance(candidate_ids, list) or not all(
        isinstance(item, str) and item for item in candidate_ids
    ):
        raise ReviewRoutingError("人工候选清单 candidate_ids 非法")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ReviewRoutingError("人工候选清单 candidate_id 重复")
    if selection.get("candidate_count") != len(candidate_ids):
        raise ReviewRoutingError("人工候选清单 candidate_count 不一致")
    if selection.get("candidate_ids_sha256") != _candidate_ids_sha256(candidate_ids):
        raise ReviewRoutingError("人工候选清单摘要不一致")
    return list(candidate_ids)
