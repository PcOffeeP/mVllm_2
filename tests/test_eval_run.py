from __future__ import annotations

import sys
from pathlib import Path

import pytest

import finetune.eval_run as evaluation_cli
from finetune.eval_run import (
    evaluation_succeeded,
    load_validation_samples,
    parse_args,
    summarize_records,
)
from finetune.v4_1_runtime import release_dir, score_v4_1_prediction


def _labels(
    state: str,
    mechanism: str | None = None,
    site: str | None = None,
) -> dict[str, object]:
    return {
        "clip_state": state,
        "fracture_mechanism": mechanism,
        "fracture_site": site,
        "special_case": None,
    }


def _record(
    target: dict[str, object],
    prediction: dict[str, object] | None,
    *,
    runtime_error: str | None = None,
) -> dict[str, object]:
    return {
        "target": target,
        "prediction": prediction,
        "strict_valid": prediction is not None,
        "runtime_error": runtime_error,
        "scores": score_v4_1_prediction(target, prediction),
    }


def test_loads_committed_fold_validation_sets() -> None:
    if not release_dir(Path(__file__).resolve().parents[1]).is_dir():
        pytest.skip("project-local V4.1 workspace data is not present")
    assert len(load_validation_samples(0)) == 425
    assert len(load_validation_samples(1)) == 445
    assert len(load_validation_samples(2)) == 346


def test_cli_accepts_explicit_release_contract_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_run.py",
            "--fold",
            "0",
            "--model-dir",
            "model",
            "--out-dir",
            "out",
            "--expected-contract-hash",
            "new-contract-hash",
        ],
    )

    assert parse_args().expected_contract_hash == "new-contract-hash"


def test_main_forwards_release_contract_hash_before_model_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_run.py",
            "--fold",
            "0",
            "--model-dir",
            "model",
            "--out-dir",
            "out",
            "--release-id",
            "rebuilt-release",
            "--expected-contract-hash",
            "new-contract-hash",
        ],
    )
    captured: dict[str, object] = {}

    def validate_release(*args: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(evaluation_cli, "validate_release", validate_release)
    monkeypatch.setattr(
        evaluation_cli,
        "_load_contract",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("stop-before-model")),
    )

    with pytest.raises(RuntimeError, match="stop-before-model"):
        evaluation_cli.main()

    assert captured == {
        "verify_media": True,
        "release_id": "rebuilt-release",
        "expected_contract_hash": "new-contract-hash",
        "expected_schema_version": None,
    }


def test_summarizes_strict_metrics_and_confusion() -> None:
    fracture = _labels("发生断裂", "韧性断裂", "inside_gauge")
    stable = _labels("未断裂")
    records = [
        _record(fracture, fracture),
        _record(stable, fracture),
        _record(fracture, None, runtime_error="boom"),
    ]

    summary = summarize_records(records)

    assert summary["total_samples"] == 3
    assert summary["runtime_failure_count"] == 1
    assert summary["strict_valid_rate"] == 0.666667
    assert summary["metrics"]["joint_correct_rate"] == 0.333333
    assert summary["clip_state_confusion"]["发生断裂"]["发生断裂"] == 1
    assert summary["clip_state_confusion"]["发生断裂"]["__invalid__"] == 1
    assert summary["clip_state_confusion"]["未断裂"]["发生断裂"] == 1
    assert evaluation_succeeded(summary) is False


def test_evaluation_succeeds_when_inference_has_no_runtime_failures() -> None:
    stable = _labels("未断裂")
    summary = summarize_records([_record(stable, None)])

    assert summary["strict_valid_rate"] == 0.0
    assert evaluation_succeeded(summary) is True
