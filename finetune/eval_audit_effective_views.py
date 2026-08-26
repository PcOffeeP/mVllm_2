"""Audit V4.1 effective frame views and build isolated review candidates.

The audit is read-only with respect to releases and media.  It writes lightweight
manifests only; automatic or V3 labels remain review hints and are never promoted
to training truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from finetune.v4_1_runtime import RELEASE_ID
from pipeline.current_data import current_data_paths
from pipeline.v4_1_labels import (
    V4_1_LABEL_FIELDS,
    canonicalize_v4_1_labels,
    migrate_v3_to_v4_1_labels,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCHEMA_VERSION = "tensile-vlm-v4.1-effective-view-audit/v1"
POLICY_VERSION = "effective-view-policy/1.0"
DEFAULT_NEAR_DUPLICATE_IOU = 0.80
DEFAULT_MAX_SOURCE_SHARE = 0.10
SOURCE_PATTERN = re.compile(r"(video_\d+)")


class EffectiveViewAuditError(RuntimeError):
    """The effective-view audit cannot be completed reproducibly."""


def _canonical_bytes(value: Any) -> bytes:
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


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EffectiveViewAuditError(f"无法读取 {label}: {path}: {exc}") from exc


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        temporary.write_bytes(_canonical_bytes(value))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _candidate_rows(payload: Any, label: str) -> list[dict[str, Any]]:
    rows = payload.get("candidates") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise EffectiveViewAuditError(f"{label} 缺少 candidates 列表")
    result = [dict(row) for row in rows]
    ids = [row.get("candidate_id") for row in result]
    if any(not isinstance(value, str) or not value for value in ids):
        raise EffectiveViewAuditError(f"{label} 包含无效 candidate_id")
    if len(ids) != len(set(ids)):
        raise EffectiveViewAuditError(f"{label} candidate_id 重复")
    return result


def _resolve_media_path(path_value: Any, media_root: Path) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise EffectiveViewAuditError(f"无效媒体路径: {path_value!r}")
    path = Path(path_value)
    return path if path.is_absolute() else media_root / path


def verify_materialized_media(
    candidates: Iterable[Mapping[str, Any]],
    *,
    media_root: Path,
) -> dict[str, Any]:
    """Verify candidate videos and sampled frame artifacts against frozen hashes."""
    verified_candidates = 0
    verified_frames = 0
    failures: list[dict[str, str]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "<unknown>")
        try:
            video_path = _resolve_media_path(candidate.get("video_path"), media_root)
            if (
                not video_path.is_file()
                or _sha256_file(video_path) != candidate.get("video_sha256")
            ):
                raise EffectiveViewAuditError("video_missing_or_hash_mismatch")
            artifacts = candidate.get("frame_artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                raise EffectiveViewAuditError("frame_artifacts_missing")
            for artifact in artifacts:
                if not isinstance(artifact, Mapping):
                    raise EffectiveViewAuditError("frame_artifact_invalid")
                frame_path = _resolve_media_path(artifact.get("path"), media_root)
                if (
                    not frame_path.is_file()
                    or frame_path.stat().st_size != artifact.get("size_bytes")
                    or _sha256_file(frame_path) != artifact.get("sha256")
                ):
                    raise EffectiveViewAuditError(
                        f"frame_missing_or_hash_mismatch:{frame_path}"
                    )
                verified_frames += 1
            verified_candidates += 1
        except EffectiveViewAuditError as exc:
            failures.append({"candidate_id": candidate_id, "reason": str(exc)})
    return {
        "candidate_count": verified_candidates + len(failures),
        "verified_candidate_count": verified_candidates,
        "verified_frame_count": verified_frames,
        "failure_count": len(failures),
        "failures": failures,
        "passed": not failures,
    }


def effective_frame_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact source-aware identity of frames consumed by the model."""
    candidate_id = str(candidate.get("candidate_id") or "<unknown>")
    source = candidate.get("source_video")
    mapping = candidate.get("actual_frame_mapping")
    if not isinstance(source, str) or not source:
        raise EffectiveViewAuditError(f"{candidate_id}: source_video 缺失")
    if not isinstance(mapping, list) or not mapping:
        raise EffectiveViewAuditError(f"{candidate_id}: actual_frame_mapping 缺失")
    try:
        frames = tuple(int(item["original_frame"]) for item in mapping)
    except (KeyError, TypeError, ValueError) as exc:
        raise EffectiveViewAuditError(
            f"{candidate_id}: actual_frame_mapping 非法"
        ) from exc
    if list(frames) != sorted(set(frames)):
        raise EffectiveViewAuditError(
            f"{candidate_id}: original_frame 必须严格递增且不重复"
        )
    payload = {"source_video": source, "original_frames": list(frames)}
    return {
        **payload,
        "effective_frame_signature": _content_hash(payload),
        "effective_frame_start": frames[0],
        "effective_frame_end": frames[-1],
        "effective_frame_count": len(frames),
    }


def _labels(candidate: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    value = candidate.get("labels")
    if isinstance(value, Mapping):
        return canonicalize_v4_1_labels(value), "v4.1_release_truth"
    value = candidate.get("candidate_v3_labels")
    if isinstance(value, Mapping):
        return migrate_v3_to_v4_1_labels(value), "v3_unreviewed_hint"
    return None, "missing"


def _combination(labels: Mapping[str, Any] | None) -> str:
    if labels is None:
        return "<unlabeled>"
    return "|".join(
        "<null>" if labels[field] is None else str(labels[field])
        for field in ("clip_state", "fracture_mechanism", "fracture_site")
    )


def _inventory_record(
    candidate: Mapping[str, Any],
    *,
    pool: str,
    review_scope: str,
    truth_status: str,
) -> dict[str, Any]:
    labels, label_role = _labels(candidate)
    identity = effective_frame_identity(candidate)
    return {
        "candidate_id": candidate["candidate_id"],
        "pool": pool,
        "review_scope": review_scope,
        "truth_status": truth_status,
        "source_video": identity["source_video"],
        "video_path": candidate.get("video_path")
        or candidate.get("planned_video_path"),
        "video_sha256": candidate.get("video_sha256"),
        "start_frame": candidate.get("start_frame"),
        "end_frame": candidate.get("end_frame"),
        "actual_frame_mapping": candidate["actual_frame_mapping"],
        **{
            key: identity[key]
            for key in (
                "effective_frame_signature",
                "effective_frame_start",
                "effective_frame_end",
                "effective_frame_count",
            )
        },
        "labels": labels,
        "label_role": label_role,
        "combination": _combination(labels),
        "human_reviewed": truth_status == "released_truth",
    }


def _interval_iou(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    left_start = int(left["effective_frame_start"])
    left_end = int(left["effective_frame_end"])
    right_start = int(right["effective_frame_start"])
    right_end = int(right["effective_frame_end"])
    intersection = max(0, min(left_end, right_end) - max(left_start, right_start) + 1)
    union = max(left_end, right_end) - min(left_start, right_start) + 1
    return intersection / union if union else 0.0


def near_duplicate_clusters(
    records: Iterable[Mapping[str, Any]],
    *,
    threshold: float = DEFAULT_NEAR_DUPLICATE_IOU,
) -> list[dict[str, Any]]:
    """Cluster same-source views whose effective-frame envelopes overlap."""
    if not 0.0 < threshold <= 1.0:
        raise EffectiveViewAuditError("近重复 IoU 阈值必须位于 (0, 1]")
    rows = sorted(
        (dict(row) for row in records),
        key=lambda row: (str(row["source_video"]), str(row["candidate_id"])),
    )
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    by_source: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        by_source[str(row["source_video"])].append(index)
    for indices in by_source.values():
        for offset, left in enumerate(indices):
            for right in indices[offset + 1 :]:
                if (
                    rows[left]["effective_frame_signature"]
                    == rows[right]["effective_frame_signature"]
                    or _interval_iou(rows[left], rows[right]) >= threshold
                ):
                    union(left, right)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[find(index)].append(row)
    clusters: list[dict[str, Any]] = []
    for members in grouped.values():
        if len(members) < 2:
            continue
        member_ids = sorted(str(item["candidate_id"]) for item in members)
        pools = sorted({str(item["pool"]) for item in members})
        clusters.append(
            {
                "cluster_id": f"near-duplicate-{_content_hash(member_ids)[:12]}",
                "source_video": members[0]["source_video"],
                "candidate_ids": member_ids,
                "pools": pools,
                "member_count": len(member_ids),
                "cross_pool": len(pools) > 1,
            }
        )
    return sorted(clusters, key=lambda item: item["cluster_id"])


def _coverage(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    sources = Counter(str(row["source_video"]) for row in records)
    signatures = Counter(str(row["effective_frame_signature"]) for row in records)
    states = Counter(
        str((row.get("labels") or {}).get("clip_state", "<unlabeled>"))
        for row in records
    )
    combinations = Counter(str(row["combination"]) for row in records)
    special = Counter(
        "<null>"
        if (row.get("labels") or {}).get("special_case") is None
        else str((row.get("labels") or {}).get("special_case"))
        for row in records
    )
    total = len(records)
    top_source = sources.most_common(1)
    return {
        "candidate_count": total,
        "source_count": len(sources),
        "unique_effective_frame_signatures": len(signatures),
        "duplicate_exact_signature_count": sum(value - 1 for value in signatures.values()),
        "clip_state_counts": dict(sorted(states.items())),
        "special_case_counts": dict(sorted(special.items())),
        "combination_counts": dict(sorted(combinations.items())),
        "per_source_contribution": dict(sorted(sources.items())),
        "largest_source": top_source[0][0] if top_source else None,
        "largest_source_count": top_source[0][1] if top_source else 0,
        "largest_source_share": round(top_source[0][1] / total, 6)
        if top_source and total
        else 0.0,
    }


def _source_from_training_row(row: Mapping[str, Any], context: str) -> str:
    videos = row.get("videos")
    if not isinstance(videos, list) or len(videos) != 1:
        raise EffectiveViewAuditError(f"{context}: videos 必须恰有一个路径")
    match = SOURCE_PATTERN.search(str(videos[0]))
    if match is None:
        raise EffectiveViewAuditError(f"{context}: 无法解析 source_video")
    return match.group(1)


def audit_fold_source_isolation(release_dir: Path) -> dict[str, Any]:
    folds: dict[str, Any] = {}
    all_sources: set[str] = set()
    violations: list[dict[str, Any]] = []
    for fold in range(3):
        split_sources: dict[str, set[str]] = {}
        for split in ("train", "validation"):
            path = release_dir / f"datasets/{split}/fold_{fold}.json"
            rows = _load_json(path, f"fold {fold} {split}")
            if not isinstance(rows, list):
                raise EffectiveViewAuditError(f"{path}: 数据集必须是列表")
            split_sources[split] = {
                _source_from_training_row(row, f"{path}:{index}")
                for index, row in enumerate(rows)
                if isinstance(row, Mapping)
            }
        overlap = sorted(split_sources["train"] & split_sources["validation"])
        if overlap:
            violations.append({"fold": fold, "overlapping_sources": overlap})
        all_sources.update(split_sources["train"])
        all_sources.update(split_sources["validation"])
        folds[f"fold_{fold}"] = {
            "train_source_count": len(split_sources["train"]),
            "validation_source_count": len(split_sources["validation"]),
            "overlapping_sources": overlap,
        }
    return {
        "folds": folds,
        "development_sources": sorted(all_sources),
        "violation_count": len(violations),
        "violations": violations,
        "passed": not violations,
    }


def build_audit(
    *,
    release_dir: Path,
    base_materialized_path: Path,
    experimental_materialized_path: Path,
    test_materialized_path: Path | None = None,
    test_plan_path: Path | None = None,
    media_root: Path | None = None,
    near_duplicate_iou: float = DEFAULT_NEAR_DUPLICATE_IOU,
    max_source_share: float = DEFAULT_MAX_SOURCE_SHARE,
) -> dict[str, Any]:
    """Build the complete lightweight Phase 1 audit payload."""
    if not 0.0 < max_source_share <= 1.0:
        raise EffectiveViewAuditError("单源贡献上限必须位于 (0, 1]")
    training_path = release_dir / "metadata/training_candidates.json"
    release_manifest_path = release_dir / "manifest/release_manifest.json"
    release_manifest = _load_json(release_manifest_path, "release manifest")
    if not isinstance(release_manifest, Mapping):
        raise EffectiveViewAuditError("release manifest 必须是对象")
    if release_manifest.get("release_id") != RELEASE_ID:
        raise EffectiveViewAuditError(
            f"只允许审计冻结发布 {RELEASE_ID}"
        )
    released = _candidate_rows(
        _load_json(training_path, "training candidates"),
        "training candidates",
    )
    base_materialized = _candidate_rows(
        _load_json(base_materialized_path, "base materialized"),
        "base materialized",
    )
    experimental = _candidate_rows(
        _load_json(experimental_materialized_path, "experimental materialized"),
        "experimental materialized",
    )
    base_by_id = {row["candidate_id"]: row for row in base_materialized}
    inventory: list[dict[str, Any]] = []
    missing_release_mappings: list[str] = []
    for row in released:
        materialized = base_by_id.get(row["candidate_id"])
        if materialized is None:
            missing_release_mappings.append(row["candidate_id"])
            continue
        combined = dict(materialized)
        combined["labels"] = row["labels"]
        combined["video_path"] = row.get("video_path", materialized.get("video_path"))
        combined["video_sha256"] = row.get(
            "video_sha256", materialized.get("video_sha256")
        )
        inventory.append(
            _inventory_record(
                combined,
                pool="released",
                review_scope="development",
                truth_status="released_truth",
            )
        )
    if missing_release_mappings:
        raise EffectiveViewAuditError(
            "正式发布候选无法关联真实抽帧: "
            + ", ".join(sorted(missing_release_mappings)[:5])
        )
    inventory.extend(
        _inventory_record(
            row,
            pool="automatic_candidate",
            review_scope="development",
            truth_status="unreviewed",
        )
        for row in experimental
    )

    planned_test: list[dict[str, Any]] = []
    test_skipped_sources: list[dict[str, Any]] = []
    if test_plan_path is not None:
        test_plan_payload = _load_json(test_plan_path, "test candidate plan")
        planned_test = _candidate_rows(
            test_plan_payload,
            "test candidate plan",
        )
        skipped = (
            test_plan_payload.get("skipped_sources")
            if isinstance(test_plan_payload, Mapping)
            else None
        )
        if skipped is not None:
            if not isinstance(skipped, list) or not all(
                isinstance(row, Mapping) for row in skipped
            ):
                raise EffectiveViewAuditError(
                    "test candidate plan skipped_sources 非法"
                )
            test_skipped_sources = [dict(row) for row in skipped]
    materialized_test: list[dict[str, Any]] = []
    if test_materialized_path is not None:
        materialized_test = _candidate_rows(
            _load_json(test_materialized_path, "test materialized"),
            "test materialized",
        )
        inventory.extend(
            _inventory_record(
                row,
                pool="test_candidate",
                review_scope="sealed_test",
                truth_status="unreviewed",
            )
            for row in materialized_test
        )

    by_pool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in inventory:
        by_pool[row["pool"]].append(row)
    coverage = {
        pool: _coverage(rows)
        for pool, rows in sorted(by_pool.items())
    }
    source_cap_violations = {
        pool: {
            source: count
            for source, count in report["per_source_contribution"].items()
            if report["candidate_count"]
            and count / report["candidate_count"] > max_source_share
        }
        for pool, report in coverage.items()
    }
    duplicates = near_duplicate_clusters(
        inventory,
        threshold=near_duplicate_iou,
    )
    automatic_ids = {
        str(row["candidate_id"])
        for row in by_pool.get("automatic_candidate", [])
    }
    automatic_near_released: set[str] = set()
    for cluster in duplicates:
        if "released" in cluster["pools"]:
            automatic_near_released.update(
                set(cluster["candidate_ids"]) & automatic_ids
            )
    automatic_independent = automatic_ids - automatic_near_released
    fold_isolation = audit_fold_source_isolation(release_dir)
    development_sources = set(fold_isolation["development_sources"])
    test_sources = {
        str(row["source_video"]) for row in materialized_test or planned_test
    }
    cross_scope_sources = sorted(development_sources & test_sources)
    released_signatures = {
        row["effective_frame_signature"]
        for row in by_pool.get("released", [])
    }
    test_signatures = {
        row["effective_frame_signature"]
        for row in by_pool.get("test_candidate", [])
    }
    cross_scope_signatures = sorted(released_signatures & test_signatures)
    unable_judgment = {
        "evidence_insufficient_no_special_case": [],
        "未夹紧": [],
        "视频异常": [],
    }
    unable_judgment_pending_sources: dict[str, set[str]] = {
        key: set() for key in unable_judgment
    }
    for row in inventory:
        labels = row.get("labels") or {}
        if labels.get("clip_state") != "无法判断":
            continue
        special = labels.get("special_case")
        key = (
            "evidence_insufficient_no_special_case"
            if special is None
            else str(special)
        )
        if key in unable_judgment:
            unable_judgment[key].append(row["candidate_id"])
    for skipped in test_skipped_sources:
        special = skipped.get("special_case")
        key = str(special) if special is not None else ""
        source = skipped.get("source_video")
        if key in unable_judgment_pending_sources and isinstance(source, str):
            unable_judgment_pending_sources[key].add(source)

    review_development = [
        row for row in inventory if row["pool"] == "automatic_candidate"
    ]
    review_test = [
        row for row in inventory if row["pool"] == "test_candidate"
    ]
    missing_test_ids = sorted(
        {row["candidate_id"] for row in planned_test}
        - {row["candidate_id"] for row in materialized_test}
    )
    test_media_integrity = (
        verify_materialized_media(materialized_test, media_root=media_root)
        if media_root is not None and materialized_test
        else {
            "candidate_count": len(materialized_test),
            "verified_candidate_count": 0,
            "verified_frame_count": 0,
            "failure_count": 0,
            "failures": [],
            "passed": not materialized_test,
            "status": "not_requested" if materialized_test else "no_media",
        }
    )
    inputs = {
        "release_manifest": {
            "path": str(release_manifest_path),
            "sha256": _sha256_file(release_manifest_path),
        },
        "training_candidates": {
            "path": str(training_path),
            "sha256": _sha256_file(training_path),
        },
        "base_materialized": {
            "path": str(base_materialized_path),
            "sha256": _sha256_file(base_materialized_path),
        },
        "experimental_materialized": {
            "path": str(experimental_materialized_path),
            "sha256": _sha256_file(experimental_materialized_path),
        },
    }
    for name, path in (
        ("test_plan", test_plan_path),
        ("test_materialized", test_materialized_path),
    ):
        if path is not None:
            inputs[name] = {"path": str(path), "sha256": _sha256_file(path)}
    audit_identity = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "release_id": RELEASE_ID,
        "policy": {
            "version": POLICY_VERSION,
            "near_duplicate_effective_frame_envelope_iou": near_duplicate_iou,
            "max_source_share": max_source_share,
            "automatic_labels_are_truth": False,
            "v3_test_labels_are_truth": False,
        },
        "input_hashes": {
            name: metadata["sha256"] for name, metadata in sorted(inputs.items())
        },
    }
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audit_id": f"effective-view-audit-{_content_hash(audit_identity)[:12]}",
        "identity": audit_identity,
        "inputs": inputs,
        "inventory": sorted(
            inventory,
            key=lambda row: (row["review_scope"], row["pool"], row["candidate_id"]),
        ),
        "coverage": coverage,
        "near_duplicate_clusters": duplicates,
        "independent_evidence": {
            "automatic_candidate_count": len(automatic_ids),
            "automatic_near_released_count": len(automatic_near_released),
            "automatic_independent_count": len(automatic_independent),
            "automatic_independent_candidate_ids": sorted(automatic_independent),
        },
        "source_cap_violations": source_cap_violations,
        "leakage": {
            "fold_source_isolation": fold_isolation,
            "development_test_source_overlap": cross_scope_sources,
            "development_test_signature_overlap": cross_scope_signatures,
            "passed": (
                fold_isolation["passed"]
                and not cross_scope_sources
                and not cross_scope_signatures
            ),
        },
        "review_queues": {
            "development": review_development,
            "sealed_test": review_test,
        },
        "test_candidate_status": {
            "planned_count": len(planned_test),
            "materialized_count": len(materialized_test),
            "planned_source_count": len(
                {str(row["source_video"]) for row in planned_test}
            ),
            "skipped_source_count": len(test_skipped_sources),
            "source_inventory_count": len(
                {str(row["source_video"]) for row in planned_test}
                | {
                    str(row.get("source_video"))
                    for row in test_skipped_sources
                    if row.get("source_video")
                }
            ),
            "skipped_sources": test_skipped_sources,
            "missing_actual_sampling_count": len(missing_test_ids),
            "missing_actual_sampling_candidate_ids": missing_test_ids,
            "media_integrity": test_media_integrity,
        },
        "unable_judgment_coverage": {
            key: {
                "candidate_count": len(candidate_ids),
                "candidate_ids": sorted(candidate_ids),
                "unique_effective_view_count": len(candidate_ids),
                "effective_source_count": len(
                    {
                        str(row["source_video"])
                        for row in inventory
                        if row["candidate_id"] in candidate_ids
                    }
                ),
                "available_unmaterialized_source_count": len(
                    unable_judgment_pending_sources[key]
                ),
                "available_unmaterialized_sources": sorted(
                    unable_judgment_pending_sources[key]
                ),
                "status": (
                    "covered"
                    if candidate_ids
                    else "source_available_needs_candidate_generation"
                    if unable_judgment_pending_sources[key]
                    else "unvalidated_capability"
                ),
            }
            for key, candidate_ids in unable_judgment.items()
        },
        "completion": {
            "all_candidates_have_effective_frame_signatures": not missing_test_ids,
            "fold_and_test_leakage_check_passed": (
                fold_isolation["passed"] and not cross_scope_sources
            ),
            "review_queue_count": len(review_development) + len(review_test),
            "ready_for_human_review": (
                not missing_test_ids
                and not cross_scope_sources
                and test_media_integrity["passed"]
            ),
            "test_media_integrity_passed": test_media_integrity["passed"],
            "creates_training_release": False,
        },
    }


def write_audit(output_dir: Path, audit: Mapping[str, Any]) -> Path:
    """Write deterministic lightweight audit artifacts."""
    output_dir = Path(output_dir)
    payloads = {
        "coverage_report.json": {
            "schema_version": audit["schema_version"],
            "audit_id": audit["audit_id"],
            "coverage": audit["coverage"],
            "source_cap_violations": audit["source_cap_violations"],
            "unable_judgment_coverage": audit["unable_judgment_coverage"],
            "independent_evidence": audit["independent_evidence"],
        },
        "leakage_report.json": {
            "schema_version": audit["schema_version"],
            "audit_id": audit["audit_id"],
            "leakage": audit["leakage"],
            "near_duplicate_clusters": audit["near_duplicate_clusters"],
        },
        "development_review_candidates.json": {
            "schema_version": audit["schema_version"],
            "audit_id": audit["audit_id"],
            "scope": "development",
            "labels_are_truth": False,
            "candidates": audit["review_queues"]["development"],
        },
        "sealed_test_review_candidates.json": {
            "schema_version": audit["schema_version"],
            "audit_id": audit["audit_id"],
            "scope": "sealed_test",
            "labels_are_truth": False,
            "candidates": audit["review_queues"]["sealed_test"],
        },
        "unable_judgment_pool.json": {
            "schema_version": audit["schema_version"],
            "audit_id": audit["audit_id"],
            "scope": "development_and_sealed_test_candidates",
            "coverage": audit["unable_judgment_coverage"],
        },
        "audit_manifest.json": dict(audit),
    }
    for name, payload in payloads.items():
        _atomic_write(output_dir / name, payload)
    artifact_hashes = {
        name: _sha256_file(output_dir / name) for name in sorted(payloads)
    }
    index = {
        "schema_version": audit["schema_version"],
        "audit_id": audit["audit_id"],
        "artifacts": artifact_hashes,
        "completion": audit["completion"],
    }
    _atomic_write(output_dir / "manifest.json", index)
    return output_dir


def _default_audit_paths() -> dict[str, Path]:
    paths = current_data_paths(ROOT)
    return {
        "release_dir": paths.training_releases / RELEASE_ID,
        "base_materialized": (
            paths.metadata
            / "v3/candidate_media_results/candidate-media-8de972530561"
            / "development_materialized.json"
        ),
        "experimental_materialized": (
            paths.metadata
            / "v4_1/experiments/candidate_media_results/candidate-media-b442478052cd"
            / "development_materialized.json"
        ),
        "test_plan": (
            paths.metadata
            / "v3/candidate_plans/candidate-plan-ce36b9226be5"
            / "test_candidate_audit.json"
        ),
        "media_root": paths.root,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="审计 V4.1 正式发布、自动候选和密封测试候选的有效视觉证据"
    )
    parser.add_argument("--release-dir", type=Path, default=None)
    parser.add_argument("--base-materialized", type=Path, default=None)
    parser.add_argument(
        "--experimental-materialized",
        type=Path,
        default=None,
    )
    parser.add_argument("--test-plan", type=Path, default=None)
    parser.add_argument("--test-materialized", type=Path, default=None)
    parser.add_argument(
        "--media-root",
        type=Path,
        default=None,
        help="相对媒体路径的根目录；提供后校验测试候选视频与帧哈希",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--near-duplicate-iou",
        type=float,
        default=DEFAULT_NEAR_DUPLICATE_IOU,
    )
    parser.add_argument(
        "--max-source-share",
        type=float,
        default=DEFAULT_MAX_SOURCE_SHARE,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    defaults = _default_audit_paths()
    release_dir = args.release_dir or defaults["release_dir"]
    base_materialized = args.base_materialized or defaults["base_materialized"]
    experimental_materialized = (
        args.experimental_materialized or defaults["experimental_materialized"]
    )
    test_plan = args.test_plan or defaults["test_plan"]
    media_root = args.media_root or defaults["media_root"]
    try:
        audit = build_audit(
            release_dir=release_dir,
            base_materialized_path=base_materialized,
            experimental_materialized_path=experimental_materialized,
            test_materialized_path=args.test_materialized,
            test_plan_path=test_plan,
            media_root=media_root,
            near_duplicate_iou=args.near_duplicate_iou,
            max_source_share=args.max_source_share,
        )
        destination = write_audit(args.output_dir, audit)
        print(
            json.dumps(
                {
                    "audit_id": audit["audit_id"],
                    "destination": str(destination),
                    "coverage": audit["coverage"],
                    "test_candidate_status": audit["test_candidate_status"],
                    "completion": audit["completion"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except EffectiveViewAuditError as exc:
        print(f"错误: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
