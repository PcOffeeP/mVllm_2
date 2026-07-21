"""Build immutable v3 reference evidence from the reviewed v2 artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from pipeline.v3_labels import (
    LABEL_SCHEMA_VERSION,
    SOURCE_FRACTURE,
    SOURCE_NO_FRACTURE,
    SOURCE_UNCLAMPED,
    SOURCE_VIDEO_ABNORMAL,
    derive_clip_state,
    map_legacy_fracture_type,
)

REFERENCE_SCHEMA_VERSION = "tensile-review-reference/v1"
USABLE_REVIEW_STATUSES = frozenset({"approved", "corrected"})
EXCLUDED_REVIEW_STATUSES = frozenset({"dropped", "needs_regenerate", "needs_review", "unreviewed"})


def load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"文件不存在: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"无法解析 JSON: {path} ({exc})") from exc


def sha256_file(path: Path) -> str:
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


def _relative_path(path: Path, project_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def _records(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get(key, [])
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{key} 必须是对象列表")
    return payload


def _decision_index(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("审查决策顶层必须是对象")
    decisions = payload.get("decisions", [])
    if isinstance(decisions, dict):
        items = [(key, value) for key, value in decisions.items()]
    elif isinstance(decisions, list):
        items = [(item.get("subvideo_id"), item) for item in decisions]
    else:
        raise ValueError("decisions 必须是对象或列表")
    result: dict[str, dict[str, Any]] = {}
    for clip_id, decision in items:
        if not isinstance(clip_id, str) or not clip_id or not isinstance(decision, dict):
            raise ValueError("存在无效审查决策记录")
        if clip_id in result:
            raise ValueError(f"重复 subvideo_id: {clip_id}")
        result[clip_id] = decision
    return result


def _metadata_index(payload: Any) -> dict[str, dict[str, Any]]:
    rows = _records(payload, "subvideos")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        clip_id = row.get("subvideo_id")
        if not isinstance(clip_id, str) or not clip_id:
            raise ValueError("metadata 中存在无效 subvideo_id")
        if clip_id in result:
            raise ValueError(f"metadata 中重复 subvideo_id: {clip_id}")
        result[clip_id] = row
    return result


def _source_video_id(clip_id: str, row: Mapping[str, Any] | None) -> str | None:
    if row is not None:
        source = row.get("source_video")
        if isinstance(source, str) and source:
            return source
    parts = clip_id.split("_")
    if len(parts) >= 2 and parts[0] == "video":
        return "_".join(parts[:2])
    return None


def _legacy_snapshot(row: Mapping[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    return {
        "has_fracture": row.get("has_fracture_canonical", row.get("has_fracture")),
        "type": row.get("type_canonical") or row.get("type"),
        "location": row.get("location_canonical", row.get("location")),
        "fracture_between": row.get("fracture_between"),
    }


def _effective_legacy_labels(
    decision: Mapping[str, Any] | None, row: Mapping[str, Any] | None
) -> tuple[dict[str, Any], str]:
    decision = decision or {}
    corrected = decision.get("corrected_labels")
    if isinstance(corrected, dict) and corrected:
        return dict(corrected), "corrected_labels"
    original = decision.get("original_labels")
    if isinstance(original, dict) and original:
        return dict(original), "original_labels"
    return _legacy_snapshot(row), "label_reviewed_metadata"


def _source_kind(source: Mapping[str, Any]) -> tuple[str, str | None]:
    source_type = source.get("type_canonical") or source.get("type")
    if source_type == "未夹紧":
        return SOURCE_UNCLAMPED, "未夹紧"
    if source_type == "视频异常" or source.get("is_abnormal") is True:
        return SOURCE_VIDEO_ABNORMAL, "视频异常"
    has_fracture = source.get("has_fracture_canonical")
    if has_fracture is None:
        has_fracture = source.get("has_fracture")
    if has_fracture is True:
        return SOURCE_FRACTURE, None
    if has_fracture is False:
        return SOURCE_NO_FRACTURE, None
    return SOURCE_VIDEO_ABNORMAL, "视频异常"


def _timestamps(row: Mapping[str, Any] | None) -> list[Any]:
    row = row or {}
    mapping = row.get("actual_frame_mapping") or row.get("sampled_frames") or []
    if not isinstance(mapping, list):
        return []
    return [item.get("timestamp") for item in mapping if isinstance(item, dict)]


def _event_time(source: Mapping[str, Any]) -> Any:
    return source.get("event_time_effective") or source.get("event_time")


def _candidate_v3(
    legacy: Mapping[str, Any],
    row: Mapping[str, Any] | None,
    source: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    kind, special_case = _source_kind(source)
    state = derive_clip_state(kind, _event_time(source), _timestamps(row))
    mapping = map_legacy_fracture_type(
        legacy.get("type") or source.get("type_canonical") or source.get("type")
    )
    location = legacy.get("location")
    if location not in {"inside_gauge", "outside_gauge"}:
        location = source.get("location_canonical")
    if location not in {"inside_gauge", "outside_gauge"}:
        location = None

    visible_fracture = state.clip_state in {"发生断裂", "已断裂"}
    labels = {
        "clip_state": state.clip_state,
        "fracture_mechanism": mapping.fracture_mechanism if visible_fracture else None,
        "root_break": mapping.root_break if visible_fracture else None,
        "location": location if visible_fracture else None,
        "special_case": special_case,
    }
    provenance = {
        "clip_state_reason": state.reason,
        "guard_seconds": state.guard_seconds,
        "event_time": state.event_time,
        "legacy_type_matched": mapping.matched,
        "legacy_type_source_value": mapping.source_value,
    }
    return labels, provenance


def _record(
    clip_id: str,
    decision: Mapping[str, Any] | None,
    row: Mapping[str, Any] | None,
    source: Mapping[str, Any],
    scope: str,
) -> dict[str, Any]:
    source_id = _source_video_id(clip_id, row)
    assert source_id is not None
    decision = decision or {}
    status = decision.get("status") or (row or {}).get("review_status") or "unreviewed"
    legacy, label_source = _effective_legacy_labels(decision, row)
    candidate, provenance = _candidate_v3(legacy, row, source)
    mapping = (row or {}).get("actual_frame_mapping") or (row or {}).get("sampled_frames") or []
    return {
        "reference_record_id": f"{scope}:{clip_id}",
        "scope": scope,
        "subvideo_id": clip_id,
        "source_video": source_id,
        "review_status": status,
        "reviewed_at": decision.get("reviewed_at") or (row or {}).get("reviewed_at"),
        "reviewer_notes": decision.get("reviewer_notes") or (row or {}).get("reviewer_notes") or "",
        "original_labels": decision.get("original_labels"),
        "corrected_labels": decision.get("corrected_labels"),
        "effective_legacy_labels": legacy,
        "effective_label_source": label_source,
        "candidate_v3_labels": candidate,
        "candidate_v3_provenance": provenance,
        "time_range": {
            "start_time": (row or {}).get("start_time"),
            "end_time": (row or {}).get("end_time"),
            "start_frame": (row or {}).get("start_frame"),
            "end_frame": (row or {}).get("end_frame"),
        },
        "actual_frame_mapping": mapping,
        "source_metadata_file": decision.get("source_metadata_file"),
    }


def _consensus(records: Iterable[dict[str, Any]], sources: Mapping[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["review_status"] in USABLE_REVIEW_STATUSES:
            grouped[record["source_video"]].append(record)

    result: list[dict[str, Any]] = []
    for source_id in sorted(sources):
        source_records = grouped.get(source_id, [])
        field_values: dict[str, list[Any]] = defaultdict(list)
        supporting_ids: list[str] = []
        for record in source_records:
            legacy = record["effective_legacy_labels"]
            mapping = map_legacy_fracture_type(legacy.get("type"))
            if mapping.matched:
                if mapping.fracture_mechanism is not None:
                    field_values["fracture_mechanism"].append(mapping.fracture_mechanism)
                if mapping.root_break is not None:
                    field_values["root_break"].append(mapping.root_break)
            location = legacy.get("location")
            if location in {"inside_gauge", "outside_gauge"}:
                field_values["location"].append(location)
            supporting_ids.append(record["reference_record_id"])

        _, special_case = _source_kind(sources[source_id])
        consensus: dict[str, Any] = {"special_case": special_case}
        conflicts: dict[str, list[Any]] = {}
        for field in ("fracture_mechanism", "root_break", "location"):
            values = set(field_values[field])
            if len(values) == 1:
                consensus[field] = next(iter(values))
            else:
                consensus[field] = None
                if len(values) > 1:
                    conflicts[field] = sorted(values, key=str)
        result.append(
            {
                "source_video": source_id,
                "consensus_status": "conflict" if conflicts else ("available" if source_records else "unavailable"),
                "consensus": consensus,
                "conflicts": conflicts,
                "supporting_reference_ids": supporting_ids,
            }
        )
    return result


def _scope_artifact(
    scope: str,
    decisions_payload: Any,
    metadata_payload: Any,
    sources: Mapping[str, dict[str, Any]],
    allowed_source_ids: set[str],
) -> dict[str, Any]:
    decisions = _decision_index(decisions_payload)
    metadata = _metadata_index(metadata_payload)
    clip_ids = sorted(set(decisions) | set(metadata))
    records: list[dict[str, Any]] = []
    for clip_id in clip_ids:
        row = metadata.get(clip_id)
        source_id = _source_video_id(clip_id, row)
        if source_id is None:
            raise ValueError(f"无法从 {clip_id} 确定 source_video")
        if source_id not in allowed_source_ids:
            raise ValueError(f"{scope} 输入包含越界源视频: {source_id}")
        source = sources.get(source_id)
        if source is None:
            raise ValueError(f"video_meta 缺少源视频: {source_id}")
        records.append(_record(clip_id, decisions.get(clip_id), row, source, scope))

    scope_sources = {key: sources[key] for key in sorted(allowed_source_ids)}
    status_counts = Counter(record["review_status"] for record in records)
    return {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "scope": scope,
        "source_inventory": sorted(allowed_source_ids),
        "records": records,
        "source_consensus": _consensus(records, scope_sources),
        "statistics": {
            "source_count": len(allowed_source_ids),
            "covered_source_count": len({record["source_video"] for record in records}),
            "record_count": len(records),
            "review_status_counts": dict(sorted(status_counts.items())),
        },
    }


def _filter_scope_payloads(
    decisions_payload: Any,
    metadata_payload: Any,
    selected_source_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    decisions = _decision_index(decisions_payload)
    metadata = _metadata_index(metadata_payload)
    filtered_decisions: list[dict[str, Any]] = []
    filtered_metadata: list[dict[str, Any]] = []
    for clip_id, decision in decisions.items():
        if _source_video_id(clip_id, metadata.get(clip_id)) in selected_source_ids:
            filtered_decisions.append(decision)
    for clip_id, row in metadata.items():
        if _source_video_id(clip_id, row) in selected_source_ids:
            filtered_metadata.append(row)
    return {"decisions": filtered_decisions}, {"subvideos": filtered_metadata}


def build_reference_bundle(
    *,
    train_review_decisions_path: Path,
    train_reviewed_metadata_path: Path,
    test_review_decisions_path: Path,
    test_reviewed_metadata_path: Path,
    video_metadata_path: Path,
    test_manifest_path: Path,
    project_root: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    paths = {
        "train_review_decisions": Path(train_review_decisions_path),
        "train_reviewed_metadata": Path(train_reviewed_metadata_path),
        "test_review_decisions": Path(test_review_decisions_path),
        "test_reviewed_metadata": Path(test_reviewed_metadata_path),
        "video_metadata": Path(video_metadata_path),
        "test_manifest": Path(test_manifest_path),
    }
    inputs = [
        {
            "role": role,
            "path": _relative_path(path, project_root),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for role, path in sorted(paths.items())
    ]

    video_rows = _records(load_json(paths["video_metadata"]), "videos")
    sources = {row.get("video_id"): row for row in video_rows}
    if None in sources or len(sources) != len(video_rows):
        raise ValueError("video_meta 中存在缺失或重复 video_id")
    manifest = load_json(paths["test_manifest"])
    if not isinstance(manifest, dict) or not isinstance(manifest.get("video_ids"), list):
        raise ValueError("test manifest 必须包含 video_ids 列表")
    test_ids = set(manifest["video_ids"])
    all_ids = set(sources)
    unknown_test_ids = test_ids - all_ids
    if unknown_test_ids:
        raise ValueError(f"test manifest 含未知源视频: {sorted(unknown_test_ids)}")
    development_ids = all_ids - test_ids
    if development_ids & test_ids:
        raise ValueError("开发集和测试集存在交集")

    train_decisions_payload = load_json(paths["train_review_decisions"])
    train_metadata_payload = load_json(paths["train_reviewed_metadata"])
    development_decisions, development_metadata = _filter_scope_payloads(
        train_decisions_payload, train_metadata_payload, development_ids
    )
    quarantined_decisions, quarantined_metadata = _filter_scope_payloads(
        train_decisions_payload, train_metadata_payload, test_ids
    )
    quarantined_source_ids = {
        _source_video_id(clip_id, row)
        for clip_id, row in _metadata_index(quarantined_metadata).items()
    } | {
        _source_video_id(clip_id, _metadata_index(quarantined_metadata).get(clip_id))
        for clip_id in _decision_index(quarantined_decisions)
    }
    quarantined_source_ids.discard(None)

    development = _scope_artifact(
        "development",
        development_decisions,
        development_metadata,
        sources,
        development_ids,
    )
    quarantined = _scope_artifact(
        "quarantined_cross_split",
        quarantined_decisions,
        quarantined_metadata,
        sources,
        set(quarantined_source_ids),
    )
    test_audit = _scope_artifact(
        "test_audit",
        load_json(paths["test_review_decisions"]),
        load_json(paths["test_reviewed_metadata"]),
        sources,
        test_ids,
    )
    conflicts = {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "development": [
            row for row in development["source_consensus"] if row["consensus_status"] == "conflict"
        ],
        "test_audit": [
            row for row in test_audit["source_consensus"] if row["consensus_status"] == "conflict"
        ],
        "quarantined_cross_split": [
            row for row in quarantined["source_consensus"] if row["consensus_status"] == "conflict"
        ],
    }
    identity = {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "inputs": inputs,
        "development_source_ids": sorted(development_ids),
        "test_source_ids": sorted(test_ids),
    }
    reference_id = f"review-ref-{_content_hash(identity)[:12]}"
    for artifact in (development, test_audit, quarantined, conflicts):
        artifact["reference_id"] = reference_id

    report = {
        "reference_id": reference_id,
        "development": development["statistics"],
        "test_audit": test_audit["statistics"],
        "quarantined_cross_split": quarantined["statistics"],
        "quarantined_source_ids": quarantined["source_inventory"],
        "development_conflict_count": len(conflicts["development"]),
        "development_conflict_source_ids": [
            row["source_video"] for row in conflicts["development"]
        ],
        "test_conflict_count": len(conflicts["test_audit"]),
        "test_conflict_source_ids": [
            row["source_video"] for row in conflicts["test_audit"]
        ],
        "quarantined_conflict_count": len(conflicts["quarantined_cross_split"]),
    }
    artifacts = {
        "development_reference.json": development,
        "test_reference_audit.json": test_audit,
        "quarantined_cross_split.json": quarantined,
        "conflicts.json": conflicts,
        "build_report.json": report,
    }
    manifest_payload = {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "reference_id": reference_id,
        "inputs": inputs,
        "split_guard": {
            "test_manifest_sha256": sha256_file(paths["test_manifest"]),
            "development_source_count": len(development_ids),
            "test_source_count": len(test_ids),
            "overlap_count": 0,
            "quarantined_source_count": quarantined["statistics"]["covered_source_count"],
            "quarantined_record_count": quarantined["statistics"]["record_count"],
        },
        "artifacts": {
            name: {"sha256": _content_hash(payload)}
            for name, payload in sorted(artifacts.items())
        },
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
    }
    return {"manifest.json": manifest_payload, **artifacts}


def write_reference_bundle(output_root: Path, bundle: Mapping[str, Any]) -> tuple[Path, bool]:
    manifest = bundle.get("manifest.json")
    if not isinstance(manifest, Mapping):
        raise ValueError("bundle 缺少 manifest.json")
    reference_id = manifest.get("reference_id")
    if not isinstance(reference_id, str) or not reference_id.startswith("review-ref-"):
        raise ValueError("无效 reference_id")
    destination = Path(output_root) / reference_id
    if destination.exists():
        for name, payload in bundle.items():
            path = destination / name
            if not path.exists():
                raise FileExistsError(f"拒绝覆盖已有参考批次: {destination}")
            if name == "manifest.json":
                existing = load_json(path)
                existing_without_time = dict(existing)
                requested_without_time = dict(payload)
                existing_without_time.pop("generated_at", None)
                requested_without_time.pop("generated_at", None)
                identical = existing_without_time == requested_without_time
            else:
                identical = path.read_bytes() == _canonical_bytes(payload)
            if not identical:
                raise FileExistsError(f"拒绝覆盖已有参考批次: {destination}")
        return destination, False

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{reference_id}.", dir=destination.parent))
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
