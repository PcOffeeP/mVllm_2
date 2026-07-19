from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from finetune import run_full_training_pipeline as pipeline


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _configure_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    finetune = root / "finetune"
    log_dir = finetune / "run_logs"
    result_root = finetune / "results" / pipeline.RUN_ID / "full_training"
    three_fold_summary = (
        finetune
        / "results"
        / pipeline.RUN_ID
        / "three_fold_full"
        / "three_fold_summary.json"
    )
    train_config = finetune / "config" / "full.yaml"
    merge_config = finetune / "config" / "merge.yaml"
    run_dir = root / "saves" / "full"
    merged_dir = root / "saves" / "full_merged"
    dataset_dir = finetune / "generated" / "full"
    release_dir = root / "release"

    _write_json(
        finetune / "active_data_release.json",
        {"release_id": pipeline.RELEASE_ID},
    )
    _write_json(
        log_dir / "three-fold-state.json",
        {
            "status": "completed",
            "stage": "three_fold_aggregate",
            "release_id": pipeline.RELEASE_ID,
        },
    )
    _write_json(
        three_fold_summary,
        {
            "active_release_id": pipeline.RELEASE_ID,
            "fold_count": 3,
            "total_records": 10,
            "pooled_metrics": {"task_metrics": {"joint_success_rate": 0.2}},
        },
    )
    train_config.parent.mkdir(parents=True, exist_ok=True)
    train_config.write_text("test: true\n", encoding="utf-8")
    merge_config.write_text("test: true\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python"
    python.touch()
    (bin_dir / "llamafactory-cli").touch()

    monkeypatch.setattr(pipeline, "ROOT", root)
    monkeypatch.setattr(pipeline, "FINETUNE", finetune)
    monkeypatch.setattr(pipeline, "LOG_DIR", log_dir)
    monkeypatch.setattr(pipeline, "RESULT_ROOT", result_root)
    monkeypatch.setattr(pipeline, "STATE_PATH", log_dir / "full-state.json")
    monkeypatch.setattr(
        pipeline, "THREE_FOLD_STATE_PATH", log_dir / "three-fold-state.json"
    )
    monkeypatch.setattr(pipeline, "THREE_FOLD_SUMMARY_PATH", three_fold_summary)
    monkeypatch.setattr(pipeline, "TRAIN_CONFIG", train_config)
    monkeypatch.setattr(pipeline, "MERGE_CONFIG", merge_config)
    monkeypatch.setattr(pipeline, "RUN_DIR", run_dir)
    monkeypatch.setattr(pipeline, "MERGED_DIR", merged_dir)
    monkeypatch.setattr(pipeline, "DATASET_DIR", dataset_dir)
    monkeypatch.setattr(pipeline, "RELEASE_DIR", release_dir)
    monkeypatch.setattr(pipeline.sys, "executable", str(python))


def test_preflight_requires_completed_three_fold_aggregate(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    _write_json(
        pipeline.THREE_FOLD_STATE_PATH,
        {
            "status": "running",
            "stage": "fold2_training",
            "release_id": pipeline.RELEASE_ID,
        },
    )

    with pytest.raises(RuntimeError, match="three-fold pipeline"):
        pipeline._preflight()


def test_preflight_accepts_completed_three_fold_and_pending_full_run(
    tmp_path, monkeypatch
):
    _configure_workspace(tmp_path, monkeypatch)

    result = pipeline._preflight()

    assert result["release_id"] == pipeline.RELEASE_ID
    assert result["three_fold_total_records"] == 10
    assert result["dataset"] == "not_generated"
    assert result["training"] == "pending"
    assert result["merge"] == "pending"


def test_verify_dataset_rejects_tampered_dataset(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    dataset = pipeline.DATASET_DIR / "full_train.json"
    registry = pipeline.DATASET_DIR / "dataset_info.json"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("[]\n", encoding="utf-8")
    registry.write_text(
        json.dumps({pipeline.FULL_DATASET_NAME: {"file_name": dataset.name}}),
        encoding="utf-8",
    )
    _write_json(
        pipeline.DATASET_DIR / "full_train.provenance.json",
        {
            "release_id": pipeline.RELEASE_ID,
            "unique_row_count": 1,
            "output": {
                "dataset": {
                    "path": dataset.name,
                    "sha256": "0" * 64,
                },
                "dataset_info": {
                    "path": registry.name,
                    "sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
                },
            },
        },
    )

    with pytest.raises(RuntimeError, match="dataset hash mismatch"):
        pipeline._verify_dataset()


def test_preflight_refuses_incomplete_existing_run(tmp_path, monkeypatch):
    _configure_workspace(tmp_path, monkeypatch)
    pipeline.RUN_DIR.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="incomplete full run"):
        pipeline._preflight()
