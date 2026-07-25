from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pipeline.v3_review_workflow import sha256_file
from pipeline.v4_1_review_workflow import (
    V4_1ReviewWorkflowError,
    build_phase2_review_queue,
    load_review_queue,
    save_v4_1_review_queue,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _materialized_candidate(
    root: Path,
    candidate_id: str,
    source_video: str,
) -> dict[str, object]:
    video = root / f"{candidate_id}.mp4"
    frame = root / f"{candidate_id}.jpg"
    video.write_bytes(f"video:{candidate_id}".encode())
    frame.write_bytes(f"frame:{candidate_id}".encode())
    return {
        "candidate_id": candidate_id,
        "source_video": source_video,
        "video_path": str(video),
        "video_sha256": sha256_file(video),
        "actual_frame_mapping": [
            {
                "input_index": 0,
                "original_frame": 10,
                "timestamp": 1.0,
            }
        ],
        "frame_artifacts": [
            {
                "path": str(frame),
                "sha256": sha256_file(frame),
                "size_bytes": frame.stat().st_size,
            }
        ],
    }


def _audit_row(
    candidate: dict[str, object],
    *,
    scope: str,
    state: str,
) -> dict[str, object]:
    signature = hashlib.sha256(
        f"{candidate['source_video']}:10".encode()
    ).hexdigest()
    return {
        "candidate_id": candidate["candidate_id"],
        "review_scope": scope,
        "truth_status": "unreviewed",
        "source_video": candidate["source_video"],
        "video_sha256": candidate["video_sha256"],
        "actual_frame_mapping": candidate["actual_frame_mapping"],
        "effective_frame_signature": signature,
        "labels": {
            "clip_state": state,
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": None,
        },
    }


def _phase2_inputs(tmp_path: Path) -> tuple[Path, Path]:
    development = _materialized_candidate(tmp_path, "dev-1", "video_0001")
    sealed_test = _materialized_candidate(tmp_path, "test-1", "video_0099")
    development_path = tmp_path / "development_materialized.json"
    test_path = tmp_path / "test_materialized.json"
    _write_json(
        development_path,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "development-media",
            "candidates": [development],
        },
    )
    _write_json(
        test_path,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "sealed-test-media",
            "candidates": [sealed_test],
        },
    )
    audit_path = tmp_path / "audit_manifest.json"
    _write_json(
        audit_path,
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
                "experimental_materialized": {
                    "path": str(development_path),
                    "sha256": sha256_file(development_path),
                },
                "test_materialized": {
                    "path": str(test_path),
                    "sha256": sha256_file(test_path),
                },
            },
            "leakage": {"passed": True},
            "review_queues": {
                "development": [
                    _audit_row(development, scope="development", state="发生断裂")
                ],
                "sealed_test": [
                    _audit_row(sealed_test, scope="sealed_test", state="未断裂")
                ],
            },
            "completion": {
                "ready_for_human_review": True,
                "creates_training_release": False,
            },
        },
    )
    contract_path = Path("pipeline/contracts/tensile_vlm_v4_1.json").resolve()
    return audit_path, contract_path


def test_phase2_builds_isolated_queues_and_keeps_hints_non_truth(
    tmp_path: Path,
) -> None:
    audit_path, contract_path = _phase2_inputs(tmp_path)
    development = build_phase2_review_queue(
        audit_manifest_path=audit_path,
        scope="development",
        project_root=tmp_path,
        contract_path=contract_path,
    )
    sealed_test = build_phase2_review_queue(
        audit_manifest_path=audit_path,
        scope="sealed_test",
        project_root=tmp_path,
        contract_path=contract_path,
    )

    assert development["queue_id"] != sealed_test["queue_id"]
    assert development["review_scope"] == "development"
    assert sealed_test["review_scope"] == "sealed_test"
    assert development["labels_are_truth"] is False
    assert sealed_test["labels_are_truth"] is False
    assert [item["candidate_id"] for item in development["candidates"]] == ["dev-1"]
    assert [item["candidate_id"] for item in sealed_test["candidates"]] == ["test-1"]


def test_phase2_loader_keeps_unbroken_sealed_test_candidate(
    tmp_path: Path,
) -> None:
    audit_path, contract_path = _phase2_inputs(tmp_path)
    queue = build_phase2_review_queue(
        audit_manifest_path=audit_path,
        scope="sealed_test",
        project_root=tmp_path,
        contract_path=contract_path,
    )
    queue_path = tmp_path / "review_queue.json"
    save_v4_1_review_queue(queue_path, queue)

    identity, candidates = load_review_queue(
        queue_path,
        project_root=tmp_path,
    )

    assert identity["review_scope"] == "sealed_test"
    assert identity["labels_are_truth"] is False
    assert identity["full_queue_count"] == 1
    assert candidates[0]["candidate_v4_labels"]["clip_state"] == "未断裂"
    assert candidates[0]["labels_are_truth"] is False


def test_phase2_loader_rejects_audit_manifest_drift(tmp_path: Path) -> None:
    audit_path, contract_path = _phase2_inputs(tmp_path)
    queue = build_phase2_review_queue(
        audit_manifest_path=audit_path,
        scope="development",
        project_root=tmp_path,
        contract_path=contract_path,
    )
    queue_path = tmp_path / "review_queue.json"
    save_v4_1_review_queue(queue_path, queue)
    audit_path.write_text(audit_path.read_text() + "\n", encoding="utf-8")

    with pytest.raises(V4_1ReviewWorkflowError, match="审计 manifest 已漂移"):
        load_review_queue(queue_path, project_root=tmp_path)
