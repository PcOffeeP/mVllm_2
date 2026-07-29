"""Resolve semantic metadata artifacts with read-only legacy fallback."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pipeline.current_data import DataContext, METADATA_COLLECTIONS
from pipeline.source_bootstrap import canonical_bytes, sha256_file


class MetadataArtifactError(ValueError):
    """A metadata artifact is missing, malformed, or conflicts with a peer."""


@dataclass(frozen=True)
class CollectionSpec:
    manifest_name: str
    identity_field: str
    extra_files: tuple[str, ...] = ()


COLLECTION_REGISTRY: dict[str, CollectionSpec] = {
    "source_snapshots": CollectionSpec(
        "source_manifest.json",
        "source_snapshot_id",
    ),
    "split_snapshots": CollectionSpec(
        "split_manifest.json",
        "split_snapshot_id",
    ),
    "roi_manifests": CollectionSpec("manifest.json", "roi_manifest_id"),
    "candidate_plans": CollectionSpec("manifest.json", "plan_id"),
    "candidate_media_results": CollectionSpec(
        "manifest.json",
        "media_id",
        ("identity.json",),
    ),
    "review_reference": CollectionSpec("manifest.json", "reference_id"),
    "review_queues": CollectionSpec("review_queue.json", "queue_id"),
    "review_decisions": CollectionSpec("summary.json", "batch_id"),
}

if set(COLLECTION_REGISTRY) != set(METADATA_COLLECTIONS):
    raise RuntimeError("metadata collection registry 不完整")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataArtifactError(f"{label} 无法读取: {path}") from exc
    if not isinstance(payload, dict):
        raise MetadataArtifactError(f"{label} 必须是 JSON object")
    return payload


def _tree_inventory(
    root: Path,
    *,
    managed_root: Path | None = None,
) -> dict[str, Any]:
    if managed_root is not None:
        managed_root = Path(managed_root)
        try:
            relative = root.relative_to(managed_root)
        except ValueError as exc:
            raise MetadataArtifactError("artifact 逃逸 managed root") from exc
        cursor = managed_root
        for part in relative.parts:
            if cursor.is_symlink():
                raise MetadataArtifactError(
                    f"artifact 路径祖先包含 symlink: {cursor}"
                )
            cursor = cursor / part
        if cursor.is_symlink():
            raise MetadataArtifactError(
                f"artifact 路径祖先包含 symlink: {cursor}"
            )
        try:
            root.resolve().relative_to(managed_root.resolve())
        except ValueError as exc:
            raise MetadataArtifactError(
                "artifact resolve 后逃逸 managed root"
            ) from exc
    if root.is_symlink() or not root.is_dir():
        raise MetadataArtifactError(f"artifact 必须是物理目录: {root}")
    items: list[dict[str, Any]] = []
    for path in sorted(
        root.rglob("*"),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise MetadataArtifactError(f"artifact 包含 symlink: {path}")
        if path.is_dir():
            items.append({"path": relative, "type": "directory"})
            continue
        if not path.is_file() or path.stat().st_nlink != 1:
            raise MetadataArtifactError(
                f"artifact 包含 hardlink 或特殊文件: {path}"
            )
        items.append(
            {
                "path": relative,
                "type": "file",
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "items": items,
        "tree_sha256": hashlib.sha256(canonical_bytes(items)).hexdigest(),
    }


def _declared_files(
    spec: CollectionSpec,
    manifest: Mapping[str, Any],
) -> dict[str, str | None]:
    if spec.manifest_name == "review_queue.json":
        return {spec.manifest_name: None}
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise MetadataArtifactError("artifact manifest 缺少 artifacts inventory")
    result: dict[str, str | None] = {spec.manifest_name: None}
    for relative, record in artifacts.items():
        candidate = Path(str(relative))
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or not candidate.parts
            or not isinstance(record, Mapping)
            or not isinstance(record.get("sha256"), str)
        ):
            raise MetadataArtifactError("artifact inventory 含非法记录")
        result[candidate.as_posix()] = str(record["sha256"])
    for relative in spec.extra_files:
        result[relative] = None
    return result


def validate_metadata_artifact(
    path: Path,
    *,
    collection: str,
    artifact_id: str,
    expected_schema: str,
    expected_tree_hash: str | None = None,
    managed_root: Path | None = None,
) -> dict[str, Any]:
    if collection not in COLLECTION_REGISTRY:
        raise MetadataArtifactError(f"未知 metadata collection: {collection}")
    path = Path(path)
    if path.name != artifact_id:
        raise MetadataArtifactError("artifact 目录名与请求 identity 不一致")
    spec = COLLECTION_REGISTRY[collection]
    inventory = _tree_inventory(path, managed_root=managed_root)
    manifest = _load_object(path / spec.manifest_name, "artifact manifest")
    if manifest.get(spec.identity_field) != artifact_id:
        raise MetadataArtifactError("artifact manifest identity 不匹配")
    if manifest.get("schema_version") != expected_schema:
        raise MetadataArtifactError("artifact schema_version 不匹配")
    if collection == "source_snapshots":
        identity = manifest.get("identity")
        if not isinstance(identity, Mapping):
            raise MetadataArtifactError("source snapshot 缺少 identity")
        digest = hashlib.sha256(canonical_bytes(identity)).hexdigest()
        if (
            manifest.get("identity_sha256") != digest
            or artifact_id != f"source-snapshot-{digest[:12]}"
        ):
            raise MetadataArtifactError("source snapshot content ID 漂移")
    elif collection == "split_snapshots":
        seed = {
            key: value
            for key, value in manifest.items()
            if key not in {"split_snapshot_id", "identity_sha256"}
        }
        digest = hashlib.sha256(canonical_bytes(seed)).hexdigest()
        if (
            manifest.get("identity_sha256") != digest
            or artifact_id != f"split-snapshot-{digest[:12]}"
        ):
            raise MetadataArtifactError("split snapshot content ID 漂移")
    elif collection == "roi_manifests":
        digest = hashlib.sha256(
            canonical_bytes(manifest.get("inputs"))
        ).hexdigest()
        if artifact_id != f"roi-manifest-{digest[:12]}":
            raise MetadataArtifactError("ROI manifest content ID 漂移")
    elif collection == "candidate_plans":
        digest = hashlib.sha256(
            canonical_bytes(manifest.get("identity"))
        ).hexdigest()
        if artifact_id != f"candidate-plan-{digest[:12]}":
            raise MetadataArtifactError("candidate plan content ID 漂移")
    elif collection == "candidate_media_results":
        digest = hashlib.sha256(
            canonical_bytes(manifest.get("identity"))
        ).hexdigest()
        if artifact_id != f"candidate-media-{digest[:12]}":
            raise MetadataArtifactError("candidate media content ID 漂移")
    elif collection == "review_queues":
        source_media = manifest.get("source_media")
        contract = manifest.get("contract")
        candidates = manifest.get("candidates")
        if (
            not isinstance(source_media, Mapping)
            or not isinstance(contract, Mapping)
            or not isinstance(candidates, list)
        ):
            raise MetadataArtifactError("review queue identity 输入缺失")
        seed = {
            "source_materialized_sha256": source_media.get(
                "materialized_sha256"
            ),
            "source_manifest_sha256": source_media.get("manifest_sha256"),
            "contract_hash": contract.get("contract_hash"),
            "migration_policy_version": manifest.get(
                "migration_policy_version"
            ),
            "candidates": candidates,
        }
        digest = hashlib.sha256(canonical_bytes(seed)).hexdigest()
        if artifact_id != f"v4-1-review-{digest[:12]}":
            raise MetadataArtifactError("review queue content ID 漂移")
    declared = _declared_files(spec, manifest)
    actual_files = {
        item["path"]
        for item in inventory["items"]
        if item["type"] == "file"
    }
    declared_directories = {
        parent.as_posix()
        for relative in declared
        for parent in Path(relative).parents
        if parent.as_posix() != "."
    }
    actual_directories = {
        item["path"]
        for item in inventory["items"]
        if item["type"] == "directory"
    }
    if actual_files != set(declared) or actual_directories != declared_directories:
        raise MetadataArtifactError("artifact exact file inventory 漂移")
    for relative, expected_hash in declared.items():
        if expected_hash is not None and sha256_file(path / relative) != expected_hash:
            raise MetadataArtifactError(f"artifact payload SHA-256 漂移: {relative}")
    if collection == "review_reference":
        development = _load_object(
            path / "development_reference.json",
            "development review reference",
        )
        test_audit = _load_object(
            path / "test_reference_audit.json",
            "test review reference",
        )
        identity = {
            "schema_version": manifest.get("schema_version"),
            "inputs": manifest.get("inputs"),
            "development_source_ids": sorted(
                development.get("source_inventory") or []
            ),
            "test_source_ids": sorted(
                test_audit.get("source_inventory") or []
            ),
        }
        digest = hashlib.sha256(canonical_bytes(identity)).hexdigest()
        if artifact_id != f"review-ref-{digest[:12]}":
            raise MetadataArtifactError("review reference content ID 漂移")
    if collection == "review_decisions":
        decisions = _load_object(path / "decisions.json", "review decisions")
        queue_identity = manifest.get("queue_identity")
        records = decisions.get("decisions")
        if not isinstance(queue_identity, Mapping) or not isinstance(records, list):
            raise MetadataArtifactError("review decisions identity 输入缺失")
        digest = hashlib.sha256(
            canonical_bytes(
                {
                    "queue_identity": queue_identity,
                    "decisions": records,
                }
            )
        ).hexdigest()
        if artifact_id != f"review-batch-{digest[:12]}":
            raise MetadataArtifactError("review decisions content ID 漂移")
    if (
        expected_tree_hash is not None
        and inventory["tree_sha256"] != expected_tree_hash
    ):
        raise MetadataArtifactError("artifact tree SHA-256 与外部锚点不一致")
    return {
        "path": path,
        "manifest": manifest,
        "tree_sha256": inventory["tree_sha256"],
    }


def resolve_metadata_artifact(
    context: DataContext,
    *,
    collection: str,
    artifact_id: str,
    expected_schema: str,
    expected_tree_hash: str | None = None,
) -> Path:
    roots = context.metadata_read_roots(collection)
    for root in roots:
        try:
            relative = root.relative_to(context.root)
        except ValueError as exc:
            raise MetadataArtifactError(
                f"metadata collection 逃逸 data root: {root}"
            ) from exc
        cursor = context.root
        for part in relative.parts:
            if cursor.is_symlink():
                raise MetadataArtifactError(
                    f"metadata collection 祖先包含 symlink: {cursor}"
                )
            cursor = cursor / part
        if cursor.is_symlink():
            raise MetadataArtifactError(
                f"metadata collection 祖先包含 symlink: {cursor}"
            )
        try:
            root.resolve().relative_to(context.root.resolve())
        except ValueError as exc:
            raise MetadataArtifactError(
                f"metadata collection resolve 后逃逸 data root: {root}"
            ) from exc
    candidates = [root / artifact_id for root in roots]
    present = [path for path in candidates if path.exists() or path.is_symlink()]
    if not present:
        raise MetadataArtifactError(
            f"metadata artifact 不存在: {collection}/{artifact_id}"
        )
    validated = [
        validate_metadata_artifact(
            path,
            collection=collection,
            artifact_id=artifact_id,
            expected_schema=expected_schema,
            expected_tree_hash=expected_tree_hash,
            managed_root=path.parent,
        )
        for path in present
    ]
    if len(validated) == 2 and (
        validated[0]["tree_sha256"] != validated[1]["tree_sha256"]
    ):
        raise MetadataArtifactError(
            f"新旧 metadata artifact 同 ID 内容冲突: {collection}/{artifact_id}"
        )
    semantic = candidates[0]
    return semantic if semantic in present else present[0]


def metadata_artifact_ids(context: DataContext, collection: str) -> list[str]:
    ids: set[str] = set()
    for root in context.metadata_read_roots(collection):
        if root.is_dir() and not root.is_symlink():
            ids.update(
                path.name
                for path in root.iterdir()
                if path.is_dir() and not path.is_symlink()
            )
    return sorted(ids)
