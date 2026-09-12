"""holdout claim 隔离及公共手工状态写入不能消费授权。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from versioning.cli import main
from versioning.data_release import seal_release, stage_release
from versioning.mlflow_eval import EvalRecordNotFound, get_eval_run, open_eval_store



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
    ) == 2
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
    assert "实际执行器" in capsys.readouterr().err
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
    # An authorized holdout claim is not evidence of actual evaluation. The
    # retired manual writer cannot create a Run or consume that claim.
    assert main(authorized) == 2
    assert "实际执行器" in capsys.readouterr().err
    assert main(["eval", "complete", eval_id, "--root", str(root),
                 "--outcome", "passed", "--pre-registration", str(preregistration),
                 "--executor", executor]) == 2
    consumed = root / "data/releases" / version / "authorization/consumed.yaml"
    assert not consumed.exists()
    with pytest.raises(EvalRecordNotFound):
        get_eval_run(open_eval_store(store_path), eval_id)
