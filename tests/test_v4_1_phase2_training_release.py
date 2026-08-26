from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline import artifact_index, artifact_resolver
from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_phase2_training_release import (
    build_v4_1_phase2_training_release,
)
from pipeline.v4_1_review_routing import (
    EXISTING_HUMAN_SCHEMA_VERSION,
    HISTORICAL_SCHEMA_VERSION,
    MANUAL_SELECTION_SCHEMA_VERSION,
    ROUTING_POLICY_VERSION,
    ROUTING_SCHEMA_VERSION,
)
from pipeline.v4_1_review_workflow import (
    build_phase2_review_queue,
    freeze_completed_batch,
    load_review_queue,
    new_decision,
    save_v4_1_review_queue,
)
from pipeline.v4_1_training_release import (
    RELEASE_SCHEMA_VERSION,
    TRAINING_CANDIDATES_SCHEMA_VERSION,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _candidate_ids_sha256(candidate_ids: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(
            candidate_ids,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _labels(state: str) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": None,
        "fracture_site": None,
        "special_case": None,
    }


def _media_candidate(
    root: Path,
    candidate_id: str,
    source_video: str,
) -> dict[str, object]:
    video = root / "media" / f"{candidate_id}.mp4"
    frame = root / "frames" / candidate_id / "frame_0000.jpg"
    video.parent.mkdir(parents=True, exist_ok=True)
    frame.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(f"video:{candidate_id}".encode())
    frame.write_bytes(f"frame:{candidate_id}".encode())
    return {
        "candidate_id": candidate_id,
        "scope": "development",
        "source_video": source_video,
        "window_role": "transition",
        "review_disposition": "experimental_auto_label",
        "candidate_v3_labels": {
            "clip_state": "未断裂",
            "fracture_mechanism": None,
            "location": None,
            "root_break": None,
            "special_case": None,
        },
        "media_status": "materialized_gate_passed",
        "sampling_gate": {"status": "passed"},
        "video_path": str(video.relative_to(root)),
        "video_sha256": sha256_file(video),
        "frame_artifacts": [
            {
                "path": str(frame.relative_to(root)),
                "sha256": sha256_file(frame),
                "size_bytes": frame.stat().st_size,
            }
        ],
        "actual_frame_mapping": [
            {
                "input_index": 0,
                "original_frame": 10,
                "timestamp": 1.0,
                "clip_frame": 0,
                "clip_timestamp": 0.0,
            }
        ],
        "processor_fingerprint": "processor:test",
    }


def _audit_row(
    candidate: dict[str, object],
    *,
    pool: str,
    human_reviewed: bool,
) -> dict[str, object]:
    signature = hashlib.sha256(str(candidate["candidate_id"]).encode()).hexdigest()
    return {
        "candidate_id": candidate["candidate_id"],
        "review_scope": "development",
        "truth_status": "human_reviewed" if human_reviewed else "unreviewed",
        "human_reviewed": human_reviewed,
        "pool": pool,
        "source_video": candidate["source_video"],
        "video_sha256": candidate["video_sha256"],
        "actual_frame_mapping": candidate["actual_frame_mapping"],
        "effective_frame_signature": signature,
        "effective_frame_start": 10,
        "effective_frame_end": 10,
        "labels": _labels("未断裂"),
    }


def _base_release(
    tmp_path: Path,
    candidate: dict[str, object],
    contract: dict[str, object],
) -> Path:
    release = tmp_path / "releases/base-release"
    metadata = {
        "schema_version": TRAINING_CANDIDATES_SCHEMA_VERSION,
        "contract_version": "tensile-vlm/v4.1",
        "contract_hash": contract["contract_hash"],
        "media_id": "base-media",
        "queue_id": "base-queue",
        "review_batch_id": "base-batch",
        "candidate_count": 1,
        "excluded_count": 0,
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "source_video": candidate["source_video"],
                "video_path": candidate["video_path"],
                "video_sha256": candidate["video_sha256"],
                "frames": [
                    {
                        "path": candidate["frame_artifacts"][0]["path"],
                        "sha256": candidate["frame_artifacts"][0]["sha256"],
                    }
                ],
                "actual_sampled_timestamps": [1.0],
                "processor_fingerprint": "processor:test",
                "labels": _labels("未断裂"),
                "label_source": "human_review",
                "review_status": "approved",
                "review_batch_id": "base-batch",
            }
        ],
        "excluded": [],
    }
    metadata_path = release / "metadata/training_candidates.json"
    _write_json(metadata_path, metadata)
    manifest = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "release_id": "base-release",
        "status": "training_ready",
        "immutable": True,
        "contract_version": "tensile-vlm/v4.1",
        "contract_hash": contract["contract_hash"],
        "counts": {
            "reviewed_candidates": 1,
        },
        "files": [
            {
                "path": "metadata/training_candidates.json",
                "size_bytes": metadata_path.stat().st_size,
                "sha256": sha256_file(metadata_path),
            }
        ],
    }
    _write_json(release / "manifest/release_manifest.json", manifest)
    return release


def _fixture(tmp_path: Path) -> dict[str, Path]:
    contract_path = Path("pipeline/contracts/tensile_vlm_v4_1.json").resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    base_candidate = _media_candidate(tmp_path, "base-1", "video_0001")
    phase2_candidates = [
        _media_candidate(tmp_path, "phase2-existing", "video_0002"),
        _media_candidate(tmp_path, "phase2-historical", "video_0003"),
        _media_candidate(tmp_path, "phase2-manual", "video_0004"),
    ]
    base_release = _base_release(tmp_path, base_candidate, contract)

    materialized = tmp_path / "metadata/phase2/development_materialized.json"
    _write_json(
        materialized,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "phase2-media",
            "scope": "development",
            "candidates": phase2_candidates,
        },
    )
    media_manifest = tmp_path / "metadata/phase2/manifest.json"
    _write_json(
        media_manifest,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "phase2-media",
            "artifacts": {
                materialized.name: {
                    "sha256": sha256_file(materialized),
                    "size_bytes": materialized.stat().st_size,
                }
            },
        },
    )
    base_audit_row = _audit_row(
        base_candidate,
        pool="released",
        human_reviewed=True,
    )
    phase2_audit_rows = [
        _audit_row(candidate, pool="automatic_candidate", human_reviewed=False)
        for candidate in phase2_candidates
    ]
    audit = tmp_path / "metadata/audit_manifest.json"
    _write_json(
        audit,
        {
            "schema_version": "tensile-vlm-v4.1-effective-view-audit/v1",
            "audit_id": "effective-view-audit-test",
            "identity": {
                "policy": {
                    "automatic_labels_are_truth": False,
                    "v3_test_labels_are_truth": False,
                }
            },
            "inputs": {
                "release_manifest": {
                    "path": str(base_release / "manifest/release_manifest.json"),
                    "sha256": sha256_file(
                        base_release / "manifest/release_manifest.json"
                    ),
                },
                "training_candidates": {
                    "path": str(base_release / "metadata/training_candidates.json"),
                    "sha256": sha256_file(
                        base_release / "metadata/training_candidates.json"
                    ),
                },
                "experimental_materialized": {
                    "path": str(materialized),
                    "sha256": sha256_file(materialized),
                },
            },
            "completion": {
                "ready_for_human_review": True,
                "all_candidates_have_effective_frame_signatures": True,
                "fold_and_test_leakage_check_passed": True,
                "creates_training_release": False,
            },
            "leakage": {
                "passed": True,
                "development_test_source_overlap": [],
                "development_test_signature_overlap": [],
                "fold_source_isolation": {"passed": True},
            },
            "coverage": {
                "automatic_candidate": {
                    "candidate_count": 3,
                    "duplicate_exact_signature_count": 0,
                    "unique_effective_frame_signatures": 3,
                }
            },
            "source_cap_violations": {"automatic_candidate": {}},
            "near_duplicate_clusters": [],
            "inventory": [base_audit_row, *phase2_audit_rows],
            "review_queues": {"development": phase2_audit_rows},
        },
    )
    queue_payload = build_phase2_review_queue(
        audit_manifest_path=audit,
        scope="development",
        project_root=tmp_path,
        contract_path=contract_path,
    )
    queue = tmp_path / "metadata/review_queue.json"
    save_v4_1_review_queue(queue, queue_payload)
    queue_identity, joined = load_review_queue(queue, project_root=tmp_path)
    joined_index = {row["candidate_id"]: row for row in joined}

    existing_decision = new_decision(
        joined_index["phase2-existing"],
        status="approved",
        corrected_labels=None,
        historical_suggested_labels=None,
        historical_reference_ids=[],
        reviewer_notes="",
        reviewer_id="reviewer",
        reviewed_at="2026-07-26T00:00:00+00:00",
    )
    manual_decision = new_decision(
        joined_index["phase2-manual"],
        status="approved",
        corrected_labels=None,
        historical_suggested_labels=None,
        historical_reference_ids=[],
        reviewer_notes="",
        reviewer_id="reviewer",
        reviewed_at="2026-07-26T00:00:01+00:00",
    )
    manual_identity, _ = load_review_queue(
        queue,
        project_root=tmp_path,
        candidate_ids=["phase2-manual"],
    )
    manual_batch_dir = freeze_completed_batch(
        tmp_path / "metadata/manual-review",
        manual_identity,
        {"phase2-manual": manual_decision},
    )

    route_dir = tmp_path / "metadata/route"
    existing_payload = {
        "schema_version": EXISTING_HUMAN_SCHEMA_VERSION,
        "routing_id": "history-review-route-test",
        "record_count": 1,
        "records": [existing_decision],
    }
    historical_route = {
        "candidate_id": "phase2-historical",
        "source_video": "video_0003",
        "semantic_window_role": "transition",
        "disposition": "historical_consensus",
        "reason": "approved_source_role_consensus_matches_current_hint",
        "labels": _labels("未断裂"),
        "historical_reference_ids": ["base-history-1"],
    }
    historical_payload = {
        "schema_version": HISTORICAL_SCHEMA_VERSION,
        "routing_id": "history-review-route-test",
        "policy_version": ROUTING_POLICY_VERSION,
        "record_count": 1,
        "records": [historical_route],
    }
    manual_selection = {
        "schema_version": MANUAL_SELECTION_SCHEMA_VERSION,
        "routing_id": "history-review-route-test",
        "queue_id": queue_identity["queue_id"],
        "queue_sha256": queue_identity["queue_sha256"],
        "candidate_count": 1,
        "candidate_ids_sha256": _candidate_ids_sha256(["phase2-manual"]),
        "candidate_ids": ["phase2-manual"],
    }
    _write_json(route_dir / "existing_human_decisions.json", existing_payload)
    _write_json(route_dir / "historical_consensus.json", historical_payload)
    _write_json(route_dir / "manual_candidate_ids.json", manual_selection)
    routes = [
        {
            "candidate_id": "phase2-existing",
            "source_video": "video_0002",
            "semantic_window_role": "transition",
            "disposition": "existing_human",
            "reason": "current_human_decision_exists",
            "labels": _labels("未断裂"),
            "historical_reference_ids": [],
        },
        historical_route,
        {
            "candidate_id": "phase2-manual",
            "source_video": "video_0004",
            "semantic_window_role": "transition",
            "disposition": "manual_review",
            "reason": "no_previous_source_history",
            "labels": None,
            "historical_reference_ids": [],
        },
    ]
    routing = {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "routing_id": "history-review-route-test",
        "policy_version": ROUTING_POLICY_VERSION,
        "source_queue": {
            "queue_id": queue_identity["queue_id"],
            "sha256": queue_identity["queue_sha256"],
            "candidate_count": 3,
        },
        "previous_review_batch": {"batch_id": "review-batch-base"},
        "counts": {
            "existing_human": 1,
            "historical_consensus": 1,
            "manual_review": 1,
            "total": 3,
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
        "routes": routes,
    }
    routing_path = route_dir / "routing_manifest.json"
    _write_json(routing_path, routing)

    splits = tmp_path / "splits"
    for fold in range(3):
        _write_json(
            splits / f"fold_{fold}_train.json",
            {"video_ids": [f"video_{index:04d}" for index in range(1, 5)]},
        )
        _write_json(splits / f"fold_{fold}_val.json", {"video_ids": []})
    _write_json(splits / "test.json", {"video_ids": ["video_0099"]})
    return {
        "project_root": tmp_path,
        "base_release": base_release,
        "materialized": materialized,
        "media_manifest": media_manifest,
        "queue": queue,
        "routing": routing_path,
        "manual_decisions": manual_batch_dir / "decisions.json",
        "audit": audit,
        "contract": contract_path,
        "splits": splits,
        "releases": tmp_path / "new-releases",
    }


def _build(paths: dict[str, Path], *, validate_only: bool) -> tuple[Path, dict]:
    return build_v4_1_phase2_training_release(
        project_root=paths["project_root"],
        base_release_dir=paths["base_release"],
        materialized_path=paths["materialized"],
        media_manifest_path=paths["media_manifest"],
        queue_path=paths["queue"],
        routing_manifest_path=paths["routing"],
        manual_decisions_path=paths["manual_decisions"],
        audit_path=paths["audit"],
        contract_path=paths["contract"],
        splits_dir=paths["splits"],
        releases_dir=paths["releases"],
        validate_only=validate_only,
    )


def test_phase2_preflight_and_publish_are_deterministic(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    predicted_dir, predicted_manifest = _build(paths, validate_only=True)

    assert not predicted_dir.exists()
    assert predicted_manifest["counts"]["published_candidates"] == 4
    assert predicted_manifest["counts"]["historical_consensus_candidates"] == 1
    assert predicted_manifest["counts"]["phase2_excluded_candidates"] == 0

    release_dir, manifest = _build(paths, validate_only=False)
    assert release_dir == predicted_dir
    assert manifest == predicted_manifest
    combined = json.loads(
        (release_dir / "metadata/combined_review_decisions.json").read_text()
    )
    assert combined["counts"] == {
        "existing_human": 1,
        "historical_consensus": 1,
        "manual_review": 1,
        "review_status": {"approved": 2},
    }
    metadata = json.loads(
        (release_dir / "metadata/training_candidates.json").read_text()
    )
    assert metadata["candidate_count"] == 4
    assert all(row.get("effective_frame_signature") for row in metadata["candidates"])

    index = artifact_index.read_index(paths["releases"])
    assert len(index) == 1
    assert index[0]["id"] == manifest["release_id"]
    assert index[0]["step"] == "release"
    assert index[0]["inputs"]["queue_id"] == manifest["source_queue_id"]
    assert index[0]["inputs"]["review_batch_id"] == manifest["source_review_batch_id"]
    assert index[0]["inputs"]["media_id"] == manifest["source_media_id"]
    assert (
        paths["releases"] / artifact_resolver.LATEST_FILENAME
    ).read_text(encoding="utf-8").strip() == manifest["release_id"]

    # Idempotent rerun keeps the same index state.
    _, same_manifest = _build(paths, validate_only=False)
    assert same_manifest == manifest
    assert len(artifact_index.read_index(paths["releases"])) == 1
