from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from finetune.train_build_source_aware_dataset import (
    COVERAGE_FIRST_POLICY_VERSION,
    HARD_NEGATIVES_PER_EPOCH,
    ROWS_PER_EPOCH,
    SIGNATURE_COUNT_CAP,
    SOURCE_COUNT_CAP,
    SourceAware3kError,
    build_source_aware_3k,
)
from pipeline.v3_review_workflow import sha256_file


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _labels(state: str) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": (
            "韧性断裂" if state in {"临界未断裂", "发生断裂", "已断裂"} else None
        ),
        "fracture_site": (
            "inside_gauge"
            if state in {"临界未断裂", "发生断裂", "已断裂"}
            else None
        ),
        "special_case": None,
    }


def _dataset_row(video_path: str, labels: dict[str, object]) -> dict[str, object]:
    return {
        "videos": [video_path],
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "<video>\nuser"},
            {
                "role": "assistant",
                "content": json.dumps(
                    labels,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
    }


def _release(tmp_path: Path, *, source_count: int = 25) -> Path:
    release = tmp_path / "release"
    states = (
        ["未断裂"] * 300
        + ["发生断裂"] * 300
        + ["已断裂"] * 250
        + ["临界未断裂"] * 150
    )
    candidates = []
    training_rows = []
    for index, state in enumerate(states):
        candidate_id = f"candidate-{index:04d}"
        video_path = f"data/media/{candidate_id}.mp4"
        labels = _labels(state)
        candidates.append(
            {
                "candidate_id": candidate_id,
                "source_video": f"video_{index % source_count:04d}",
                "video_path": video_path,
                "video_sha256": hashlib.sha256(candidate_id.encode()).hexdigest(),
                "effective_frame_signature": hashlib.sha256(
                    f"signature:{candidate_id}".encode()
                ).hexdigest(),
                "labels": labels,
            }
        )
        training_rows.append(_dataset_row(video_path, labels))
    validation_rows = [_dataset_row("data/media/validation.mp4", _labels("未断裂"))]
    metadata = {
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    registry = {"placeholder": {"file_name": "placeholder.json"}}
    managed = {
        "metadata/training_candidates.json": metadata,
        "datasets/train/fold_0.json": training_rows,
        "datasets/validation/fold_0.json": validation_rows,
        "dataset_info.json": registry,
    }
    for relative, payload in managed.items():
        _write_json(release / relative, payload)
    files = []
    for relative in sorted(managed):
        path = release / relative
        files.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    _write_json(
        release / "manifest/release_manifest.json",
        {
            "schema_version": "tensile-training-release/v4.1",
            "release_id": "release-test",
            "status": "training_ready",
            "immutable": True,
            "contract_version": "tensile-vlm/v4.1",
            "contract_hash": "contract-test",
            "counts": {
                "published_candidates": len(candidates),
                "splits": {
                    "fold_0_train": len(training_rows),
                    "fold_0_val": len(validation_rows),
                },
            },
            "files": files,
        },
    )
    return release


def test_builds_deterministic_two_seed_source_aware_manifests(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path)
    output_root = tmp_path / "sampling"

    predicted, predicted_summary = build_source_aware_3k(
        release_dir=release,
        media_root=tmp_path,
        output_root=output_root,
        seeds=(3407, 3411),
        validate_only=True,
    )
    assert not predicted.exists()
    assert predicted_summary["expected_optimizer_steps_per_seed"] == 1125
    assert predicted_summary["total_exposures_per_seed"] == 9000

    output, summary = build_source_aware_3k(
        release_dir=release,
        media_root=tmp_path,
        output_root=output_root,
        seeds=(3407, 3411),
    )
    assert output == predicted
    assert summary == predicted_summary
    manifest = json.loads((output / "sampling_manifest.json").read_text())
    assert len(manifest["plans"]) == 2
    for plan in manifest["plans"]:
        assert len(plan["candidate_sequence"]) == ROWS_PER_EPOCH
        assert plan["state_counts"]["未断裂"] == HARD_NEGATIVES_PER_EPOCH
        assert plan["max_source_count"] <= SOURCE_COUNT_CAP
        assert plan["max_source_share"] <= 0.05
        assert plan["max_signature_count"] <= SIGNATURE_COUNT_CAP
    assert (
        manifest["plans"][0]["candidate_sequence"]
        != manifest["plans"][1]["candidate_sequence"]
    )

    repeated, repeated_summary = build_source_aware_3k(
        release_dir=release,
        media_root=tmp_path,
        output_root=output_root,
        seeds=(3407, 3411),
        validate_only=True,
    )
    assert repeated == output
    assert repeated_summary == summary


def test_fails_when_source_cap_cannot_supply_3000_rows(tmp_path: Path) -> None:
    release = _release(tmp_path, source_count=10)

    with pytest.raises(SourceAware3kError, match="容量不足"):
        build_source_aware_3k(
            release_dir=release,
            media_root=tmp_path,
            output_root=tmp_path / "sampling",
            seeds=(3407,),
            validate_only=True,
        )


def test_builds_coverage_first_revision_without_overwriting_v1(
    tmp_path: Path,
) -> None:
    release = _release(tmp_path)
    output_root = tmp_path / "sampling"
    original, _ = build_source_aware_3k(
        release_dir=release,
        media_root=tmp_path,
        output_root=output_root,
        seeds=(3407, 3411),
    )

    coverage_first, summary = build_source_aware_3k(
        release_dir=release,
        media_root=tmp_path,
        output_root=output_root,
        seeds=(3407, 3411),
        policy_version=COVERAGE_FIRST_POLICY_VERSION,
        coverage_first=True,
    )

    assert coverage_first != original
    assert original.is_dir()
    manifest = json.loads(
        (coverage_first / "sampling_manifest.json").read_text()
    )
    assert manifest["policy_version"] == COVERAGE_FIRST_POLICY_VERSION
    assert (
        manifest["policy"]["other_state_policy"]
        == "coverage_first_fixed_multiset"
    )
    assert (
        manifest["plans"][0]["coverage_first"][
            "canonical_multiset_sha256"
        ]
        == manifest["plans"][1]["coverage_first"][
            "canonical_multiset_sha256"
        ]
    )
    for plan in manifest["plans"]:
        assert plan["state_counts"] == {
            "临界未断裂": 450,
            "发生断裂": 900,
            "已断裂": 750,
            "未断裂": 900,
        }
        assert plan["max_source_count"] <= SOURCE_COUNT_CAP
        assert plan["max_signature_count"] <= SIGNATURE_COUNT_CAP
    assert all(
        item["state_counts"]
        == {
            "临界未断裂": 450,
            "发生断裂": 900,
            "已断裂": 750,
            "未断裂": 900,
        }
        for item in summary["plans"]
    )
