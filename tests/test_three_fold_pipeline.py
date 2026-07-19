from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from finetune import run_three_fold_pipeline as pipeline


def _configure_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    finetune = root / "finetune"
    log_dir = finetune / "run_logs"
    result_root = finetune / "results" / pipeline.RUN_ID
    finetune.mkdir(parents=True)
    log_dir.mkdir()
    result_root.mkdir(parents=True)
    (finetune / "active_data_release.json").write_text(
        json.dumps({"release_id": pipeline.RELEASE_ID}),
        encoding="utf-8",
    )
    for fold in pipeline.FOLDS:
        for relative in (fold.training_config, fold.merge_config):
            path = finetune / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test: true\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python"
    python.touch()
    (bin_dir / "llamafactory-cli").touch()
    monkeypatch.setattr(pipeline, "ROOT", root)
    monkeypatch.setattr(pipeline, "FINETUNE", finetune)
    monkeypatch.setattr(pipeline, "LOG_DIR", log_dir)
    monkeypatch.setattr(pipeline, "RESULT_ROOT", result_root)
    monkeypatch.setattr(pipeline, "STATE_PATH", log_dir / "state.json")
    monkeypatch.setattr(pipeline.sys, "executable", str(python))


def _complete_training(fold: pipeline.Fold) -> None:
    fold.run_dir.mkdir(parents=True)
    for name in ("trainer_state.json", "train_results.json", "eval_results.json"):
        (fold.run_dir / name).write_text("{}", encoding="utf-8")
    (fold.run_dir / "adapter_model.safetensors").touch()


def test_preflight_accepts_running_fold0_and_clean_future_folds(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    pipeline.FOLDS[0].pid_file.write_text(str(os.getpid()), encoding="utf-8")

    result = pipeline._preflight()

    assert result["release_id"] == pipeline.RELEASE_ID
    assert result["fold0"] == f"running_pid={os.getpid()}"
    assert result["folds"] == ["fold0", "fold1", "fold2"]


def test_preflight_accepts_completed_fold0(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    _complete_training(pipeline.FOLDS[0])

    result = pipeline._preflight()

    assert result["fold0"] == "complete"


def test_preflight_rejects_incomplete_future_run_directory(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    _complete_training(pipeline.FOLDS[0])
    pipeline.FOLDS[1].run_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="incomplete run directory"):
        pipeline._preflight()
