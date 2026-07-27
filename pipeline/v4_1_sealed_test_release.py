"""Build an immutable, access-restricted V4.1 sealed-test release."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_labels import canonicalize_v4_1_labels
from pipeline.v4_1_review_decisions import (
    normalize_review_record,
    validate_review_payload,
)
from pipeline.v4_1_review_workflow import (
    PHASE2_QUEUE_SCHEMA_VERSION,
    load_review_queue,
)
from pipeline.v4_1_training_release import (
    RELEASE_SCHEMA_VERSION,
    V4_1TrainingReleaseError,
    _canonical_bytes,
    _contract_identity,
    _pretty_bytes,
    _read_json,
    _sha256_bytes,
    _write_release,
)

SEALED_TEST_RELEASE_SCHEMA_VERSION = "tensile-sealed-test-release/v1"
SEALED_GROUND_TRUTH_SCHEMA_VERSION = "tensile-sealed-ground-truth/v1"
SEALED_QUALITY_SCHEMA_VERSION = "tensile-sealed-test-quality/v1"
READY_STATUS = "ready_for_one_time_evaluation"
ADMITTED_STATUSES = frozenset({"approved", "corrected"})
EXCLUDED_STATUSES = frozenset({"dropped", "needs_regenerate"})


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V4_1TrainingReleaseError(f"{label}必须是对象")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise V4_1TrainingReleaseError(f"{label}必须是列表")
    return value


def _load_frozen_review_batch(
    *,
    decisions_path: Path,
    queue_identity: Mapping[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[Mapping[str, Any], list[dict[str, Any]], Mapping[str, Any]]:
    payload = _require_mapping(
        _read_json(decisions_path, "sealed review decisions"),
        "sealed review decisions",
    )
    try:
        validate_review_payload(payload)
    except ValueError as exc:
        raise V4_1TrainingReleaseError(f"sealed review decisions 非法: {exc}") from exc
    decisions = [dict(row) for row in payload["decisions"]]
    candidate_ids = [str(row["candidate_id"]) for row in candidates]
    if [row.get("clip_id") for row in decisions] != candidate_ids:
        raise V4_1TrainingReleaseError("sealed review decisions 未按完整队列顺序覆盖")

    candidate_index = {str(row["candidate_id"]): row for row in candidates}
    normalized: list[dict[str, Any]] = []
    for raw in decisions:
        decision = normalize_review_record(raw)
        candidate = candidate_index[str(decision["clip_id"])]
        evidence = _require_mapping(decision.get("evidence"), "decision.evidence")
        if (
            decision["source_video"] != candidate.get("source_video")
            or decision["system_proposed_labels"]
            != candidate.get("candidate_v4_labels")
            or evidence.get("media_sha256") != candidate.get("video_sha256")
            or evidence.get("actual_sampled_timestamps")
            != candidate.get("_actual_sampled_timestamps")
            or not isinstance(decision.get("reviewer_id"), str)
            or not str(decision["reviewer_id"]).strip()
            or not isinstance(decision.get("reviewed_at"), str)
            or not str(decision["reviewed_at"]).strip()
        ):
            raise V4_1TrainingReleaseError(
                f"{decision['clip_id']}: 人工决定与队列媒体或审核身份不一致"
            )
        status = str(decision["review_status"])
        if status in ADMITTED_STATUSES:
            if decision["effective_labels"] is None:
                raise V4_1TrainingReleaseError(
                    f"{decision['clip_id']}: 有效人工决定缺少最终标签"
                )
            decision["effective_labels"] = canonicalize_v4_1_labels(
                decision["effective_labels"]
            )
        elif status in EXCLUDED_STATUSES:
            if decision["effective_labels"] is not None:
                raise V4_1TrainingReleaseError(
                    f"{decision['clip_id']}: 排除决定不得携带最终标签"
                )
        else:
            raise V4_1TrainingReleaseError(
                f"{decision['clip_id']}: 非终态或未知 review_status"
            )
        normalized.append(decision)

    summary_path = Path(decisions_path).with_name("summary.json")
    summary = _require_mapping(
        _read_json(summary_path, "sealed review summary"),
        "sealed review summary",
    )
    expected_identity = {
        key: value for key, value in queue_identity.items() if key != "queue_path"
    }
    status_counts = dict(
        sorted(Counter(row["review_status"] for row in normalized).items())
    )
    if (
        summary.get("batch_id") != payload.get("batch_id")
        or summary.get("decision_count") != len(normalized)
        or summary.get("queue_identity") != expected_identity
        or summary.get("status_counts") != status_counts
        or (
            (_require_mapping(summary.get("artifacts"), "summary.artifacts")).get(
                "decisions.json"
            )
            or {}
        ).get("sha256")
        != sha256_file(decisions_path)
    ):
        raise V4_1TrainingReleaseError("sealed review summary 与队列或决定不一致")
    if not str(payload.get("batch_id") or "").startswith("review-batch-"):
        raise V4_1TrainingReleaseError("sealed review batch_id 不是冻结身份")
    return payload, normalized, summary


def _development_sources(release_manifest_path: Path) -> tuple[set[str], str]:
    manifest_path = Path(release_manifest_path).resolve()
    manifest = _require_mapping(
        _read_json(manifest_path, "development release manifest"),
        "development release manifest",
    )
    if (
        manifest.get("schema_version") != RELEASE_SCHEMA_VERSION
        or manifest.get("immutable") is not True
        or manifest.get("status") != "training_ready"
    ):
        raise V4_1TrainingReleaseError("development release 身份或状态非法")
    release_dir = manifest_path.parent.parent
    file_entries = [
        _require_mapping(row, "development release file")
        for row in _require_list(manifest.get("files"), "development release files")
    ]
    metadata_entry = next(
        (
            row
            for row in file_entries
            if row.get("path") == "metadata/training_candidates.json"
        ),
        None,
    )
    if metadata_entry is None:
        raise V4_1TrainingReleaseError(
            "development release 缺少 training_candidates.json"
        )
    metadata_path = release_dir / "metadata/training_candidates.json"
    if (
        not metadata_path.is_file()
        or metadata_path.stat().st_size != metadata_entry.get("size_bytes")
        or sha256_file(metadata_path) != metadata_entry.get("sha256")
    ):
        raise V4_1TrainingReleaseError("development training candidates 漂移")
    metadata = _require_mapping(
        _read_json(metadata_path, "development training candidates"),
        "development training candidates",
    )
    candidates = [
        _require_mapping(row, "development candidate")
        for row in _require_list(metadata.get("candidates"), "development candidates")
    ]
    sources = {str(row.get("source_video") or "") for row in candidates}
    if "" in sources:
        raise V4_1TrainingReleaseError("development candidate 缺少 source_video")
    return sources, sha256_file(manifest_path)


def _load_test_split(test_split_path: Path) -> tuple[set[str], str]:
    payload = _require_mapping(
        _read_json(test_split_path, "test split"),
        "test split",
    )
    ids = _require_list(payload.get("video_ids"), "test split video_ids")
    if (
        not all(isinstance(item, str) and item for item in ids)
        or len(ids) != len(set(ids))
    ):
        raise V4_1TrainingReleaseError("test split video_ids 非法或重复")
    return set(ids), sha256_file(test_split_path)


def _restrict_release_permissions(release_dir: Path) -> None:
    for path in sorted(release_dir.rglob("*")):
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    os.chmod(release_dir, 0o700)


def build_v4_1_sealed_test_release(
    *,
    project_root: Path,
    queue_path: Path,
    decisions_path: Path,
    contract_path: Path,
    development_release_manifest_path: Path,
    test_split_path: Path,
    releases_dir: Path,
    validate_only: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Validate and optionally publish one immutable sealed-test release."""
    project_root = Path(project_root).resolve()
    contract, contract_file_sha256 = _contract_identity(contract_path)
    queue_identity, raw_candidates = load_review_queue(
        queue_path,
        project_root=project_root,
    )
    candidates = [dict(row) for row in raw_candidates]
    if (
        queue_identity.get("queue_schema_version") != PHASE2_QUEUE_SCHEMA_VERSION
        or queue_identity.get("review_scope") != "sealed_test"
        or queue_identity.get("labels_are_truth") is not False
        or queue_identity.get("contract_hash") != contract.get("contract_hash")
    ):
        raise V4_1TrainingReleaseError(
            "输入队列不是当前契约绑定的 sealed_test 非真值提示队列"
        )
    decisions, normalized, summary = _load_frozen_review_batch(
        decisions_path=decisions_path,
        queue_identity=queue_identity,
        candidates=candidates,
    )
    development_sources, development_manifest_sha256 = _development_sources(
        development_release_manifest_path
    )
    test_split_sources, test_split_sha256 = _load_test_split(test_split_path)
    queue_sources = {str(row["source_video"]) for row in candidates}
    if queue_sources & development_sources:
        raise V4_1TrainingReleaseError("sealed test 与 development source 重叠")
    if not queue_sources <= test_split_sources:
        raise V4_1TrainingReleaseError("sealed test candidate 存在 test split 外来源")

    candidate_index = {str(row["candidate_id"]): row for row in candidates}
    admitted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for decision in normalized:
        candidate = candidate_index[str(decision["clip_id"])]
        common = {
            "candidate_id": decision["clip_id"],
            "source_video": decision["source_video"],
            "review_status": decision["review_status"],
            "reviewer_id": decision["reviewer_id"],
            "reviewed_at": decision["reviewed_at"],
        }
        if decision["review_status"] in EXCLUDED_STATUSES:
            excluded.append(common)
            continue
        admitted.append(
            {
                **common,
                "video_path": candidate["video_path"],
                "video_sha256": candidate["video_sha256"],
                "frames": candidate["frame_artifacts"],
                "actual_sampled_timestamps": candidate[
                    "_actual_sampled_timestamps"
                ],
                "processor_fingerprint": candidate.get("processor_fingerprint"),
                "effective_frame_signature": candidate.get(
                    "effective_frame_signature"
                ),
                "labels": decision["effective_labels"],
            }
        )
    admitted_sources = {str(row["source_video"]) for row in admitted}
    if admitted and admitted_sources != queue_sources:
        raise V4_1TrainingReleaseError(
            "人工排除导致 sealed test 独立 source 覆盖不完整"
        )

    status_counts = dict(
        sorted(Counter(row["review_status"] for row in normalized).items())
    )
    records_seed = {
        "admitted": admitted,
        "excluded": excluded,
    }
    release_seed = {
        "schema_version": SEALED_TEST_RELEASE_SCHEMA_VERSION,
        "contract_hash": contract["contract_hash"],
        "contract_file_sha256": contract_file_sha256,
        "queue_sha256": queue_identity["queue_sha256"],
        "decisions_sha256": sha256_file(decisions_path),
        "summary_sha256": sha256_file(Path(decisions_path).with_name("summary.json")),
        "development_release_manifest_sha256": development_manifest_sha256,
        "test_split_sha256": test_split_sha256,
        "records_sha256": _sha256_bytes(_canonical_bytes(records_seed)),
    }
    release_id = (
        "v4.1-sealed-test-"
        f"{_sha256_bytes(_canonical_bytes(release_seed))[:12]}"
    )
    ground_truth = {
        "schema_version": SEALED_GROUND_TRUTH_SCHEMA_VERSION,
        "release_id": release_id,
        "access_policy": "aggregate_only_until_stage_g_complete",
        "candidate_count": len(admitted),
        "excluded_count": len(excluded),
        "source_count": len(admitted_sources),
        "candidates": admitted,
        "excluded": excluded,
    }
    quality = {
        "schema_version": SEALED_QUALITY_SCHEMA_VERSION,
        "release_id": release_id,
        "status": "passed",
        "counts": {
            "review_queue_candidates": len(candidates),
            "admitted_candidates": len(admitted),
            "excluded_candidates": len(excluded),
            "queue_sources": len(queue_sources),
            "admitted_sources": len(admitted_sources),
            "test_split_sources_without_candidates": len(
                test_split_sources - queue_sources
            ),
            "review_statuses": status_counts,
        },
        "checks": {
            "current_contract_bound": True,
            "queue_scope_is_sealed_test": True,
            "automatic_labels_are_not_truth": True,
            "review_batch_frozen_and_complete": True,
            "review_summary_content_bound": True,
            "media_and_frame_hashes_verified": True,
            "development_sources_disjoint": True,
            "test_sources_declared_by_split": True,
            "admitted_sources_complete": True,
            "semantic_labels_not_emitted_to_stdout": True,
        },
    }
    files = {
        "metadata/sealed_ground_truth.json": _pretty_bytes(ground_truth),
        "reports/quality_report.json": _pretty_bytes(quality),
    }
    file_manifest = [
        {
            "path": relative,
            "size_bytes": len(content),
            "sha256": _sha256_bytes(content),
            "access": "restricted" if relative.startswith("metadata/") else "summary",
        }
        for relative, content in sorted(files.items())
    ]
    manifest = {
        "schema_version": SEALED_TEST_RELEASE_SCHEMA_VERSION,
        "release_id": release_id,
        "status": READY_STATUS,
        "immutable": True,
        "sealed": True,
        "contract_version": contract["contract_version"],
        "contract_hash": contract["contract_hash"],
        "source_queue_id": queue_identity["queue_id"],
        "source_review_batch_id": decisions["batch_id"],
        "source_media_id": queue_identity["media_id"],
        "source_audit_id": queue_identity["audit_id"],
        "counts": quality["counts"],
        "access_policy": {
            "ground_truth": "restricted",
            "pre_stage_g_outputs": "aggregate_pass_fail_and_integrity_only",
            "tuning_use": "forbidden",
            "one_time_evaluation_authorized": False,
        },
        "provenance": release_seed,
        "files": file_manifest,
    }
    release_dir = Path(releases_dir) / release_id
    if not validate_only:
        _write_release(release_dir, files, manifest)
        _restrict_release_permissions(release_dir)
    return release_dir, manifest
