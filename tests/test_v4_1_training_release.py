from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pipeline.v4_1_review_decisions import build_review_payload, save_review_payload
from pipeline.v4_1_review_workflow import (
    build_v4_1_review_queue,
    load_review_queue,
    new_decision,
    save_v4_1_review_queue,
)
from pipeline.v4_1_training_release import (
    V4_1TrainingReleaseError,
    build_v4_1_training_release,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _labels(state: str) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": "韧性断裂" if state == "发生断裂" else None,
        "location": "inside_gauge" if state == "发生断裂" else None,
        "root_break": False if state == "发生断裂" else None,
        "special_case": None,
    }


def _candidate(
    root: Path,
    candidate_id: str,
    source_video: str,
    *,
    state: str,
    role: str,
    variant: str | None,
    disposition: str,
) -> dict[str, object]:
    video = root / "data/media" / f"{candidate_id}.mp4"
    frame = root / "data/frames" / candidate_id / "frame_0000.jpg"
    video.parent.mkdir(parents=True, exist_ok=True)
    frame.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(f"video:{candidate_id}".encode())
    frame.write_bytes(f"frame:{candidate_id}".encode())
    return {
        "candidate_id": candidate_id,
        "scope": "development",
        "source_video": source_video,
        "source_type": "韧性断裂",
        "source_location": "inside_gauge",
        "window_role": role,
        "window_variant": variant,
        "review_disposition": disposition,
        "candidate_v3_labels": _labels(state),
        "media_status": "materialized_gate_passed",
        "sampling_gate": {"status": "passed"},
        "video_path": str(video.relative_to(root)),
        "video_sha256": _sha(video),
        "frame_artifacts": [
            {
                "path": str(frame.relative_to(root)),
                "sha256": _sha(frame),
                "size_bytes": frame.stat().st_size,
            }
        ],
        "actual_frame_mapping": [
            {
                "input_index": 0,
                "original_frame": 1,
                "timestamp": 0.1,
                "clip_frame": 0,
                "clip_timestamp": 0.0,
            }
        ],
        "processor_fingerprint": "processor:test",
    }


def _fixture(tmp_path: Path) -> dict[str, Path]:
    contract = {
        "contract_version": "tensile-vlm/v4.1",
        "analysis": {
            "system_prompt": "system",
            "user_prompt": "user",
        },
    }
    contract["contract_hash"] = hashlib.sha256(
        json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    contract_path = tmp_path / "pipeline/contracts/tensile_vlm_v4_1.json"
    _write_json(contract_path, contract)

    candidates = [
        _candidate(
            tmp_path,
            "video_0001_transition",
            "video_0001",
            state="发生断裂",
            role="transition",
            variant=None,
            disposition="manual_required",
        ),
        _candidate(
            tmp_path,
            "video_0001_pre_front",
            "video_0001",
            state="未断裂",
            role="pre_event",
            variant="pre_event_front",
            disposition="automatic_validation",
        ),
        _candidate(
            tmp_path,
            "video_0002_pre_back",
            "video_0002",
            state="未断裂",
            role="pre_event",
            variant="pre_event_back",
            disposition="automatic_validation",
        ),
        _candidate(
            tmp_path,
            "video_0002_pre_front",
            "video_0002",
            state="未断裂",
            role="pre_event",
            variant="pre_event_front",
            disposition="automatic_validation",
        ),
    ]
    materialized = tmp_path / "data/results/development_materialized.json"
    _write_json(
        materialized,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "candidate-media-test",
            "scope": "development",
            "candidates": candidates,
        },
    )
    media_manifest = tmp_path / "data/results/manifest.json"
    _write_json(
        media_manifest,
        {
            "schema_version": "tensile-v3-candidate-media/v1",
            "media_id": "candidate-media-test",
            "artifacts": {
                materialized.name: {
                    "sha256": _sha(materialized),
                    "size_bytes": materialized.stat().st_size,
                }
            },
        },
    )

    queue_payload = build_v4_1_review_queue(
        materialized_path=materialized,
        manifest_path=media_manifest,
        project_root=tmp_path,
        contract_path=contract_path,
    )
    queue = tmp_path / "data/review_queue.json"
    save_v4_1_review_queue(queue, queue_payload)
    _, joined = load_review_queue(queue, project_root=tmp_path)
    decisions = [
        new_decision(
            candidate,
            status="approved",
            corrected_labels=None,
            historical_suggested_labels=None,
            historical_reference_ids=[],
            reviewer_notes="",
            reviewer_id="reviewer",
            reviewed_at="2026-07-23T00:00:00+00:00",
        )
        for candidate in joined
    ]
    decisions_path = tmp_path / "data/decisions.json"
    save_review_payload(
        decisions_path,
        build_review_payload(
            decisions,
            batch_id="review-batch-test",
            created_at="2026-07-23T00:00:00+00:00",
        ),
    )

    splits = tmp_path / "data/splits"
    for fold in range(3):
        train = ["video_0001"] if fold % 2 == 0 else ["video_0002"]
        val = ["video_0002"] if fold % 2 == 0 else ["video_0001"]
        _write_json(
            splits / f"fold_{fold}_train.json",
            {"video_ids": train},
        )
        _write_json(
            splits / f"fold_{fold}_val.json",
            {"video_ids": val},
        )
    _write_json(splits / "test.json", {"video_ids": ["video_0099"]})
    return {
        "project_root": tmp_path,
        "materialized": materialized,
        "media_manifest": media_manifest,
        "queue": queue,
        "decisions": decisions_path,
        "contract": contract_path,
        "splits": splits,
        "releases": tmp_path / "data/releases",
    }


def _build(paths: dict[str, Path]) -> tuple[Path, dict[str, object]]:
    return build_v4_1_training_release(
        project_root=paths["project_root"],
        materialized_path=paths["materialized"],
        media_manifest_path=paths["media_manifest"],
        queue_path=paths["queue"],
        decisions_path=paths["decisions"],
        contract_path=paths["contract"],
        splits_dir=paths["splits"],
        releases_dir=paths["releases"],
    )


def test_builds_deterministic_immutable_release(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    release_dir, manifest = _build(paths)

    assert manifest["status"] == "training_ready"
    assert manifest["label_semantics"] == "frame_window_authoritative"
    assert manifest["counts"]["published_candidates"] == 4
    assert manifest["counts"]["reviewed_candidates"] == 2
    assert manifest["counts"]["automatic_unreviewed_candidates"] == 2
    assert len(json.loads((release_dir / "datasets/train/fold_0.json").read_text())) == 2
    metadata = json.loads(
        (release_dir / "metadata/training_candidates.json").read_text()
    )
    assert metadata["candidate_count"] == 4
    assert {
        row["labels"]["clip_state"] for row in metadata["candidates"]
    } == {"未断裂", "发生断裂", "临界未断裂"}

    repeated_dir, repeated_manifest = _build(paths)
    assert repeated_dir == release_dir
    assert repeated_manifest == manifest


def test_rejects_non_negative_automatic_candidate(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    payload = json.loads(paths["materialized"].read_text())
    candidate = next(
        row
        for row in payload["candidates"]
        if row["candidate_id"] == "video_0001_pre_front"
    )
    candidate["candidate_v3_labels"] = {
        "clip_state": "无法判断",
        "fracture_mechanism": None,
        "location": None,
        "root_break": None,
        "special_case": None,
    }
    _write_json(paths["materialized"], payload)
    media_manifest = json.loads(paths["media_manifest"].read_text())
    media_manifest["artifacts"][paths["materialized"].name]["sha256"] = _sha(
        paths["materialized"]
    )
    _write_json(paths["media_manifest"], media_manifest)
    paths["queue"].unlink()
    save_v4_1_review_queue(
        paths["queue"],
        build_v4_1_review_queue(
            materialized_path=paths["materialized"],
            manifest_path=paths["media_manifest"],
            project_root=tmp_path,
            contract_path=paths["contract"],
        ),
    )

    with pytest.raises(
        V4_1TrainingReleaseError,
        match="未审自动候选不是普通未断裂",
    ):
        _build(paths)


def test_rejects_drifted_media(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    video = tmp_path / "data/media/video_0001_transition.mp4"
    video.write_bytes(b"drift")

    with pytest.raises(V4_1TrainingReleaseError, match="SHA-256 不一致"):
        _build(paths)
