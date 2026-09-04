"""B10 holdout 在 data/train/eval CLI 的反向与消费路径。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from versioning.cli import main
from versioning.data_release import seal_release, stage_release
from versioning.mlflow_eval import EvalRecordNotFound, get_eval_run, open_eval_store
from versioning.mlflow_train import (
    create_fold_run,
    create_train_run,
    end_fold_run,
    log_train_summary,
    open_train_store,
    transition_train_state,
)
from versioning.registry import open_registry_store, register_model


def _release(root: Path, version: str, purpose: str) -> None:
    working = root / "data" / "working" / version
    working.mkdir(parents=True)
    (working / "payload.txt").write_text("fixture", encoding="utf-8")
    stage_release(root / "data", version, "v4.1", version=version)
    seal_release(
        root / "data",
        version,
        purpose=purpose,
        description="fixture",
        sample_count=1,
        source_batches=["fixture"],
        splits={"holdout": {"train": 0, "validation": 1}},
    )


def _register_staging_model(root: Path, store_path: Path, model_id: str) -> None:
    train_id = "train-v4.1-r9"
    if not (root / "data" / "releases" / "data-v4.1-r9").exists():
        _release(root, "data-v4.1-r9", "development")
    store = open_train_store(store_path)
    create_train_run(
        store,
        train_id,
        data_version="data-v4.1-r9",
        prompt_version="prompt-v4.1-r9",
        git_commit="fixture",
        base_model="fixture",
        config={"epochs": 1},
    )
    for fold in range(3):
        create_fold_run(store, train_id, fold)
        end_fold_run(store, train_id, fold, "FINISHED", metrics={"score": 1.0})
    log_train_summary(store, train_id, {"score": 1.0})
    transition_train_state(store, train_id, "completed")
    register_model(
        open_registry_store(store_path, data_root=root / "data"),
        model_id,
        train_id=train_id,
    )


def test_train_cli_rejects_holdout_before_creating_store(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _release(root, "data-v4.1-r2", "holdout")
    config = root / "config.yaml"
    config.write_text("epochs: 1\n", encoding="utf-8")

    assert main(
        [
            "train",
            "create",
            "train-v4.1-r2",
            "--root",
            str(root),
            "--data-version",
            "data-v4.1-r2",
            "--prompt-version",
            "prompt-v4.1-r2",
            "--git-commit",
            "fixture",
            "--base-model",
            "fixture",
            "--config",
            str(config),
        ]
    ) == 1
    assert not (root / "workspace" / "mlflow").exists()


def test_holdout_eval_requires_claim_and_preregistration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    store_path = root / "workspace" / "mlflow"
    version = "data-v4.1-r3"
    eval_id = "eval-v4.1-r3"
    model_id = "model-v4.1-r3"
    executor = "fixture-executor"
    _release(root, version, "holdout")
    _register_staging_model(root, store_path, model_id)

    create_args = [
        "eval",
        "create",
        eval_id,
        "--root",
        str(root),
        "--store",
        str(store_path),
        "--model-version",
        model_id,
        "--model-version-number",
        "1",
        "--data-version",
        version,
        "--config",
        "eval.yaml",
        "--git-commit",
        "fixture",
        "--scope",
        "full",
        "--split",
        "holdout",
    ]
    assert main(create_args) == 2
    assert "缺少必填参数" in capsys.readouterr().err
    with pytest.raises(EvalRecordNotFound):
        get_eval_run(open_eval_store(store_path), eval_id)

    claim_args = [
        "data",
        "claim",
        "--root",
        str(root),
        "--version",
        version,
        "--eval-version",
        eval_id,
        "--model-version",
        model_id,
        "--split",
        "holdout",
        "--executor",
        executor,
    ]
    assert main(claim_args) == 2
    assert not (
        root / "data" / "releases" / version / "authorization" / "claim.yaml"
    ).exists()

    preregistration = root / "pre_registration.yaml"
    preregistration.write_text(
        yaml.safe_dump(
            {
                "eval_version": eval_id,
                "model_version": model_id,
                "data_version": version,
                "split": "holdout",
                "rules": {"metric": "score"},
                "thresholds": {"score": 0.5},
                "one_time": True,
                "tuning_use": "forbidden",
                "recovery": {"same_identity_only": True},
            }
        ),
        encoding="utf-8",
    )
    assert main(
        [
            *claim_args,
            "--pre-registration",
            str(preregistration),
        ]
    ) == 0
    claim = yaml.safe_load(
        (
            root
            / "data"
            / "releases"
            / version
            / "authorization"
            / "claim.yaml"
        ).read_text(encoding="utf-8")
    )
    assert len(claim["pre_registration_sha256"]) == 64

    authorized = [
        *create_args,
        "--pre-registration",
        str(preregistration),
        "--executor",
        executor,
    ]
    ground_truth = root / "data" / "releases" / version / "sealed_ground_truth"
    ground_truth.chmod(0o755)
    assert main(authorized) == 1
    with pytest.raises(EvalRecordNotFound):
        get_eval_run(open_eval_store(store_path), eval_id)
    ground_truth.chmod(0o700)
    assert main(authorized) == 0

    metrics = root / "metrics.yaml"
    metrics.write_text("score: 1.0\n", encoding="utf-8")
    common = ["--root", str(root), "--store", str(store_path)]
    assert main(["eval", "summary", eval_id, *common, "--metrics", str(metrics)]) == 0
    complete_args = [
        "eval",
        "complete",
        eval_id,
        *common,
        "--outcome",
        "passed",
        "--pre-registration",
        str(preregistration),
        "--executor",
        executor,
    ]
    original_preregistration = preregistration.read_bytes()
    preregistration.write_text(
        preregistration.read_text(encoding="utf-8").replace("0.5", "0.9"),
        encoding="utf-8",
    )
    assert main(complete_args) == 1
    assert get_eval_run(open_eval_store(store_path), eval_id).workflow_state == "running"
    consumed = (
        root / "data" / "releases" / version / "authorization" / "consumed.yaml"
    )
    assert not consumed.exists()

    preregistration.write_bytes(original_preregistration)

    def fail_consumption(*args, **kwargs):
        raise OSError("injected consumed.yaml write failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            "versioning.mlflow_eval.mark_claim_consumed", fail_consumption
        )
        assert main(complete_args) == 1
    assert get_eval_run(open_eval_store(store_path), eval_id).workflow_state == "running"
    assert not consumed.exists()

    assert main(complete_args) == 0
    assert consumed.is_file()
