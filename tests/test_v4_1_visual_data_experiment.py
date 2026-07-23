from __future__ import annotations

import json
from pathlib import Path

import pytest

from finetune.build_v4_1_visual_data_experiment import (
    ROOT,
    VisualDataExperimentError,
    build_experimental_dataset,
    build_experimental_plan,
    validate_adapter_coverage,
    validate_experiment_config,
)


def _roi_record(video_id: str = "video_0001") -> dict[str, object]:
    return {
        "video_id": video_id,
        "duration": 20.0,
        "event_time": 10.0,
        "event_time_reliable": True,
        "has_fracture_canonical": True,
        "fps": 30.0,
        "total_frames": 600,
        "type": "韧性断裂",
        "location_canonical": "inside_gauge",
        "video_path": f"data/03_roi_videos/roi/videos/{video_id}.mp4",
        "is_abnormal_canonical": False,
        "roi_provenance": {"output_sha256": "a" * 64},
    }


def _training_row(video: str, state: str = "未断裂") -> dict[str, object]:
    target = {
        "clip_state": state,
        "fracture_mechanism": None,
        "fracture_site": None,
        "special_case": None,
    }
    return {
        "videos": [video],
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "<video>\nprompt"},
            {
                "role": "assistant",
                "content": json.dumps(target, ensure_ascii=False),
            },
        ],
    }


def test_plan_adds_only_fold0_fracture_views() -> None:
    plan = build_experimental_plan(
        roi_records=[_roi_record(), _roi_record("video_0002")],
        fold0_train_sources={"video_0001"},
        existing_intervals=set(),
        identity_inputs={"roi_media_id": "roi-media-test"},
        input_paths={},
    )

    candidates = plan["development_candidates"]
    assert candidates
    assert {item["source_video"] for item in candidates} == {"video_0001"}
    assert {
        item["candidate_v3_labels"]["clip_state"] for item in candidates
    } == {"发生断裂", "已断裂"}
    assert all(
        item["review_disposition"] == "experimental_auto_label"
        for item in candidates
    )
    assert plan["test_candidate_audit"] == []


def test_plan_excludes_existing_frame_interval() -> None:
    initial = build_experimental_plan(
        roi_records=[_roi_record()],
        fold0_train_sources={"video_0001"},
        existing_intervals=set(),
        identity_inputs={"roi_media_id": "roi-media-test"},
        input_paths={},
    )
    first = initial["development_candidates"][0]
    existing = {
        (
            first["source_video"],
            first["start_frame"],
            first["end_frame"],
        )
    }
    rebuilt = build_experimental_plan(
        roi_records=[_roi_record()],
        fold0_train_sources={"video_0001"},
        existing_intervals=existing,
        identity_inputs={"roi_media_id": "roi-media-test"},
        input_paths={},
    )

    intervals = {
        (item["source_video"], item["start_frame"], item["end_frame"])
        for item in rebuilt["development_candidates"]
    }
    assert existing.isdisjoint(intervals)


def test_dataset_deduplicates_actual_frame_views(tmp_path: Path) -> None:
    base_release = tmp_path / "release"
    (base_release / "datasets/train").mkdir(parents=True)
    (base_release / "datasets/validation").mkdir(parents=True)
    base_train = [_training_row("data/base_train.mp4")]
    base_val = [_training_row("data/base_val.mp4")]
    (base_release / "datasets/train/fold_0.json").write_text(
        json.dumps(base_train),
        encoding="utf-8",
    )
    (base_release / "datasets/validation/fold_0.json").write_text(
        json.dumps(base_val),
        encoding="utf-8",
    )
    base_materialized = tmp_path / "base.json"
    base_materialized.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "base",
                        "source_video": "video_0001",
                        "actual_frame_mapping": [
                            {"original_frame": 1},
                            {"original_frame": 2},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    v3_labels = {
        "clip_state": "发生断裂",
        "fracture_mechanism": "韧性断裂",
        "root_break": False,
        "location": "inside_gauge",
        "special_case": None,
    }
    experimental = tmp_path / "experimental.json"
    experimental.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "duplicate",
                        "source_video": "video_0001",
                        "video_path": "data/duplicate.mp4",
                        "video_sha256": "a" * 64,
                        "actual_frame_mapping": [
                            {"original_frame": 1},
                            {"original_frame": 2},
                        ],
                        "candidate_v3_labels": v3_labels,
                    },
                    {
                        "candidate_id": "new",
                        "source_video": "video_0001",
                        "video_path": "data/new.mp4",
                        "video_sha256": "b" * 64,
                        "actual_frame_mapping": [
                            {"original_frame": 3},
                            {"original_frame": 4},
                        ],
                        "candidate_v3_labels": v3_labels,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    files, manifest = build_experimental_dataset(
        base_release=base_release,
        base_materialized_path=base_materialized,
        experimental_materialized_path=experimental,
        contract_path=ROOT / "pipeline/contracts/tensile_vlm_v4_1.json",
    )

    train = json.loads(files["datasets/train/fold_0.json"])
    assert len(train) == 2
    assert manifest["counts"]["experimental_unique_accepted"] == 1
    assert manifest["counts"]["experimental_duplicate_frame_views"] == 1
    assert manifest["human_reviewed"] is False


@pytest.mark.parametrize(
    ("name", "visual", "augmented"),
    [
        ("train_v4_1_fold0_visual.yaml", True, False),
        ("train_v4_1_fold0_augmented_language.yaml", False, True),
        ("train_v4_1_fold0_augmented_visual.yaml", True, True),
    ],
)
def test_committed_experiment_configs(
    name: str,
    visual: bool,
    augmented: bool,
) -> None:
    config = (
        ROOT / "finetune/MiniCPM/config" / name
    )
    validate_experiment_config(
        config,
        visual=visual,
        augmented=augmented,
    )


def test_adapter_coverage_requires_visual_and_resampler(
    tmp_path: Path,
) -> None:
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text(
        json.dumps(
            {
                "target_modules": ["llm.q_proj", "vpm.attn.qkv"],
                "modules_to_save": ["resampler"],
            }
        ),
        encoding="utf-8",
    )
    result = validate_adapter_coverage(adapter, visual=True)
    assert result["visual_target_module_count"] == 1
    assert result["resampler_saved"] is True

    (adapter / "adapter_config.json").write_text(
        json.dumps(
            {
                "target_modules": ["llm.q_proj"],
                "modules_to_save": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(VisualDataExperimentError, match="vpm"):
        validate_adapter_coverage(adapter, visual=True)
