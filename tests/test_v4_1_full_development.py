from __future__ import annotations

import json
from pathlib import Path

import yaml

from finetune import build_v4_1_full_development_dataset as full
from finetune import build_v4_1_prompt_crossval_dataset as crossval
from finetune import prepare_v4_1_full_development_run as prepare
from pipeline.prompt_control.core import sha256_file

ROOT = Path(__file__).resolve().parents[1]
PROMPT_REVISION = ROOT / "pipeline/prompt_registry/v4.1-concise-evidence-json-v2"
PARENT_CONFIG = (
    ROOT
    / "finetune/experiments"
    / full.PARENT_CROSSVAL_EXPERIMENT_ID
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _labels(state: str) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": None if state == "未断裂" else "韧性断裂",
        "fracture_site": None if state == "未断裂" else "inside_gauge",
        "special_case": None,
    }


def _row(video: str, state: str) -> dict[str, object]:
    return {
        "videos": [video],
        "messages": [
            {"role": "system", "content": "old system"},
            {"role": "user", "content": "<video>\nold user"},
            {
                "role": "assistant",
                "content": json.dumps(_labels(state), ensure_ascii=False),
            },
        ],
    }


def _release(tmp_path: Path) -> Path:
    root = tmp_path / "release"
    candidates = []
    rows = []
    states = ("未断裂", "临界未断裂", "发生断裂")
    for index in range(9):
        state = states[index % len(states)]
        video = f"source/videos/{index}.mp4"
        rows.append(_row(video, state))
        candidates.append(
            {
                "candidate_id": f"candidate-{index}",
                "video_path": video,
                "source_video": f"source-{index}",
                "effective_frame_signature": f"signature-{index}",
                "labels": _labels(state),
            }
        )
    _write_json(
        root / "metadata/training_candidates.json",
        {"candidates": candidates},
    )
    validation_indexes = {
        0: {0, 1, 2},
        1: {3, 4, 5},
        2: {6, 7, 8},
    }
    for fold in crossval.FOLDS:
        validation = validation_indexes[fold]
        _write_json(
            root / f"datasets/train/fold_{fold}.json",
            [row for index, row in enumerate(rows) if index not in validation],
        )
        _write_json(
            root / f"datasets/validation/fold_{fold}.json",
            [row for index, row in enumerate(rows) if index in validation],
        )
    managed = [
        "metadata/training_candidates.json",
        *(
            f"datasets/{split}/fold_{fold}.json"
            for fold in crossval.FOLDS
            for split in ("train", "validation")
        ),
    ]
    _write_json(
        root / "manifest/release_manifest.json",
        {
            "release_id": "release-test",
            "immutable": True,
            "files": [
                {
                    "path": relative,
                    "size_bytes": (root / relative).stat().st_size,
                    "sha256": sha256_file(root / relative),
                }
                for relative in managed
            ],
        },
    )
    return root


def _build(tmp_path: Path, monkeypatch) -> tuple[Path, dict[str, object]]:
    monkeypatch.setattr(full, "ROWS_PER_EPOCH", 12)
    return full.build_full_development_dataset(
        release_dir=_release(tmp_path),
        prompt_revision_dir=PROMPT_REVISION,
        output_root=tmp_path / "workspace/runs",
        experiment_id=full.DEFAULT_EXPERIMENT_ID,
        project_root=tmp_path,
    )


def test_builds_full_release_coverage_with_balanced_repeats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output, summary = _build(tmp_path, monkeypatch)
    rows = json.loads(
        (output / "datasets/full_development.json").read_text(encoding="utf-8")
    )
    sampling = json.loads(
        (output / "sampling_manifest.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (output / "dataset_info.json").read_text(encoding="utf-8")
    )

    assert len(rows) == 12
    assert summary["published_candidate_count"] == 9
    assert summary["unique_coverage_rate"] == 1.0
    assert summary["repeat_count"] == 3
    assert sampling["candidate_ids"] == [
        f"candidate-{index}" for index in range(9)
    ]
    assert sampling["fold_union_proof"]["union_matches_release"] is True
    assert sampling["fold_union_proof"]["missing_candidate_ids"] == []
    assert sampling["fold_union_proof"]["extra_candidate_ids"] == []
    assert sampling["sealed_or_held_out_inputs_read"] is False
    assert len(sampling["source_counts"]) == 9
    assert len(sampling["signature_counts"]) == 9
    assert set(registry) == {"tensile_v4_1_prompt_full_development"}
    assert {
        Path(row["videos"][0]).name for row in rows
    } == {f"{index}.mp4" for index in range(9)}
    assert all(
        row["messages"][0]["content"].startswith("仅依据当前视频")
        and '禁止字符串 "null"' in row["messages"][0]["content"]
        for row in rows
    )


def test_validate_only_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    output, first = _build(tmp_path, monkeypatch)
    second_output, second = full.build_full_development_dataset(
        release_dir=tmp_path / "release",
        prompt_revision_dir=PROMPT_REVISION,
        output_root=tmp_path / "workspace/runs",
        experiment_id=full.DEFAULT_EXPERIMENT_ID,
        project_root=tmp_path,
        validate_only=True,
    )
    assert second_output == output
    assert second == first


def test_prepares_two_epoch_run_without_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_dir, _ = _build(tmp_path, monkeypatch)
    monkeypatch.setattr(prepare, "ROWS_PER_EPOCH", 12)
    monkeypatch.setattr(prepare, "EXPECTED_OPTIMIZER_STEPS", 4)
    config_dir, manifest = prepare.prepare_full_development_run(
        input_dir=input_dir,
        experiment_id=full.DEFAULT_EXPERIMENT_ID,
        parent_config_root=PARENT_CONFIG,
        project_root=tmp_path,
        training_code_commit="test-commit",
    )
    train = yaml.safe_load((config_dir / "train.yaml").read_text(encoding="utf-8"))
    merge = yaml.safe_load((config_dir / "merge.yaml").read_text(encoding="utf-8"))

    assert manifest["recipe"]["expected_optimizer_steps"] == 4
    assert manifest["recipe"]["validation_enabled"] is False
    assert manifest["recipe"]["early_stopping_enabled"] is False
    assert train["dataset"] == "tensile_v4_1_prompt_full_development"
    assert train["num_train_epochs"] == 2
    assert train["do_eval"] is False
    assert train["eval_strategy"] == "no"
    assert train["load_best_model_at_end"] is False
    assert "eval_dataset" not in train
    assert "early_stopping_steps" not in train
    assert full.DEFAULT_EXPERIMENT_ID in train["output_dir"]
    assert full.DEFAULT_EXPERIMENT_ID in merge["adapter_name_or_path"]
    assert sha256_file(config_dir / "train.yaml") == manifest["train_config"]["sha256"]
