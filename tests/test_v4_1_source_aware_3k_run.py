from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import finetune.run_v4_1_source_aware_3k as runner
from pipeline.current_data import current_data_paths


def test_frozen_configs_match_stage_b_recipe() -> None:
    for seed in runner.SEEDS:
        path = runner.CONFIG_ROOT / f"train_seed{seed}.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        config["media_dir"] = os.path.relpath(
            current_data_paths(runner.ROOT).root,
            runner.FINETUNE,
        )
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


def test_disk_preflight_accounts_for_pending_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_training_complete", lambda seed: seed == 3407)
    monkeypatch.setattr(runner, "_merged_complete", lambda seed: False)
    expected = (
        runner.ESTIMATED_ADAPTER_BYTES
        + 2 * runner.ESTIMATED_MERGED_BYTES
        + runner.DISK_RESERVE_BYTES
    )
    monkeypatch.setattr(
        runner.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(
            total=500 * 1024**3,
            used=100 * 1024**3,
            free=expected,
        ),
    )

    result = runner._disk_preflight()

    assert result["required_bytes"] == expected
    assert result["pending_adapter_count"] == 1
    assert result["pending_merged_count"] == 2


def test_disk_preflight_fails_before_launch_when_capacity_is_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_training_complete", lambda seed: False)
    monkeypatch.setattr(runner, "_merged_complete", lambda seed: False)
    monkeypatch.setattr(
        runner.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=100, used=90, free=10),
    )

    with pytest.raises(runner.SourceAware3kRunError, match="容量不足"):
        runner._disk_preflight()


def test_training_code_commit_is_frozen_in_run_manifest() -> None:
    payload = json.loads(runner.RUN_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert payload["training_code_commit"] == runner.TRAINING_CODE_COMMIT
    assert runner.TRAINING_CODE_COMMIT == (
        "f6ba152121d394141ddddaf73926e3a9c065d0a8"
    )
    assert payload["launch_run_manifest_sha256"] == (
        runner.LAUNCH_RUN_MANIFEST_SHA256
    )
    runner._validate_launch_manifest_blob()


def test_immutable_training_manifest_refuses_drift(tmp_path: Path) -> None:
    path = tmp_path / "training_run_manifest.json"
    runner._write_immutable_json(path, {"seed": 3407})
    runner._write_immutable_json(path, {"seed": 3407})

    with pytest.raises(runner.SourceAware3kRunError, match="拒绝覆盖"):
        runner._write_immutable_json(path, {"seed": 3411})
