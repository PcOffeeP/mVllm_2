from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from pipeline.current_data import current_data_context
from pipeline.metadata_artifacts import (
    MetadataArtifactError,
    metadata_artifact_ids,
    resolve_metadata_artifact,
    validate_metadata_artifact,
)
from pipeline.source_bootstrap import canonical_bytes


SCHEMA = "tensile-v4.1-review-queue/v1"
QUEUE_SEED = {
    "source_materialized_sha256": "materialized",
    "source_manifest_sha256": "manifest",
    "contract_hash": "contract",
    "migration_policy_version": "policy",
    "candidates": [],
}
QUEUE_ID = (
    "v4-1-review-"
    + hashlib.sha256(canonical_bytes(QUEUE_SEED)).hexdigest()[:12]
)


def _queue(root: Path, *, marker: str = "same") -> Path:
    directory = root / QUEUE_ID
    directory.mkdir(parents=True)
    (directory / "review_queue.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA,
                "queue_id": QUEUE_ID,
                "marker": marker,
                "migration_policy_version": "policy",
                "contract": {"contract_hash": "contract"},
                "source_media": {
                    "materialized_sha256": "materialized",
                    "manifest_sha256": "manifest",
                },
                "candidates": [],
            }
        )
    )
    return directory


def test_semantic_metadata_wins_when_legacy_copy_is_identical(
    tmp_path: Path,
) -> None:
    context = current_data_context(tmp_path)
    semantic = _queue(context.metadata_collection("review_queues"))
    _queue(context.legacy_metadata_collection("review_queues"))

    resolved = resolve_metadata_artifact(
        context,
        collection="review_queues",
        artifact_id=QUEUE_ID,
        expected_schema=SCHEMA,
    )

    assert resolved == semantic
    assert metadata_artifact_ids(context, "review_queues") == [QUEUE_ID]


def test_metadata_conflict_and_malformed_semantic_copy_fail_closed(
    tmp_path: Path,
) -> None:
    context = current_data_context(tmp_path)
    semantic = _queue(
        context.metadata_collection("review_queues"),
        marker="new",
    )
    _queue(
        context.legacy_metadata_collection("review_queues"),
        marker="old",
    )

    with pytest.raises(MetadataArtifactError, match="内容冲突"):
        resolve_metadata_artifact(
            context,
            collection="review_queues",
            artifact_id=QUEUE_ID,
            expected_schema=SCHEMA,
        )

    (semantic / "review_queue.json").write_text("{}")
    with pytest.raises(MetadataArtifactError, match="identity"):
        resolve_metadata_artifact(
            context,
            collection="review_queues",
            artifact_id=QUEUE_ID,
            expected_schema=SCHEMA,
        )


def test_metadata_exact_inventory_rejects_extra_or_missing_file(
    tmp_path: Path,
) -> None:
    context = current_data_context(tmp_path)
    directory = _queue(context.metadata_collection("review_queues"))
    (directory / "extra.json").write_text("{}")

    with pytest.raises(MetadataArtifactError, match="exact file inventory"):
        resolve_metadata_artifact(
            context,
            collection="review_queues",
            artifact_id=QUEUE_ID,
            expected_schema=SCHEMA,
        )
    (directory / "extra.json").unlink()
    (directory / "review_queue.json").unlink()
    with pytest.raises(MetadataArtifactError):
        resolve_metadata_artifact(
            context,
            collection="review_queues",
            artifact_id=QUEUE_ID,
            expected_schema=SCHEMA,
        )


def test_metadata_resolver_rejects_symlinked_collection_parent(
    tmp_path: Path,
) -> None:
    context = current_data_context(tmp_path)
    outside = tmp_path / "outside"
    _queue(outside)
    collection = context.metadata_collection("review_queues")
    collection.parent.mkdir(parents=True)
    collection.symlink_to(outside, target_is_directory=True)

    with pytest.raises(MetadataArtifactError, match="symlink"):
        resolve_metadata_artifact(
            context,
            collection="review_queues",
            artifact_id=QUEUE_ID,
            expected_schema=SCHEMA,
        )


def test_artifact_validator_limits_symlink_checks_to_managed_boundary(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real/managed"
    _queue(real)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "real", target_is_directory=True)
    lexical_managed = alias / "managed"

    result = validate_metadata_artifact(
        lexical_managed / QUEUE_ID,
        collection="review_queues",
        artifact_id=QUEUE_ID,
        expected_schema=SCHEMA,
        managed_root=lexical_managed,
    )

    assert result["manifest"]["queue_id"] == QUEUE_ID
