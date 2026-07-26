from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import finetune.run_v4_1_source_aware_3k as runner


def test_frozen_configs_match_stage_b_recipe() -> None:
    for seed in runner.SEEDS:
        path = runner.CONFIG_ROOT / f"train_seed{seed}.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        expected_dir = (
            runner.FINETUNE / str(config["dataset_dir"])
        ).resolve()

        runner._validate_config(
            seed,
            config,
            expected_dataset_dir=expected_dir,
        )


def test_training_complete_requires_exact_optimizer_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "adapter"
    root.mkdir()
    for name in (
        "train_results.json",
        "adapter_config.json",
        "adapter_model.safetensors",
    ):
        (root / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "adapter_dir", lambda seed: root)

    (root / "trainer_state.json").write_text(
        json.dumps({"global_step": 1124}),
        encoding="utf-8",
    )
    assert runner._training_complete(3407) is False

    (root / "trainer_state.json").write_text(
        json.dumps({"global_step": 1125}),
        encoding="utf-8",
    )
    assert runner._training_complete(3407) is True


def test_evaluation_complete_is_release_and_count_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "evaluation"
    root.mkdir()
    monkeypatch.setattr(runner, "result_dir", lambda seed: root)
    (root / "evaluation_records.jsonl").write_text(
        "{}\n" * runner.EXPECTED_VALIDATION_COUNT,
        encoding="utf-8",
    )
    (root / "runtime_failures.csv").write_text(
        "candidate_id,video_path,runtime_error\n",
        encoding="utf-8",
    )
    summary = {
        "release_id": runner.RELEASE_ID,
        "sample_count": runner.EXPECTED_VALIDATION_COUNT,
        "total_samples": runner.EXPECTED_VALIDATION_COUNT,
        "runtime_failure_count": 0,
    }
    (root / "evaluation_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    assert runner._evaluation_complete(3407) is True

    summary["release_id"] = "wrong"
    (root / "evaluation_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    assert runner._evaluation_complete(3407) is False
