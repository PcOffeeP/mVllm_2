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


# M4 Test List: Registry-gated prepare with no weights/eval Run; immutable
# inputs; actual strict scorer/model-runtime dispatch; three fold bindings;
# runtime failure versus quality failure; authoritative export retry; no raw
# weight override or holdout bypass through the public CLI.
def _formal_eval_fixture(tmp_path, *, scope="cross_validation", kind="adapter"):
    from test_train_with_contract import _versioned_data_fixture
    from versioning.mlflow_train import (open_train_store, create_train_run,
        create_fold_run, end_fold_run, log_train_summary, transition_train_state)
    from versioning.registry import open_registry_store, register_model
    from mlflow.tracking import MlflowClient

    root, media, release, rows = _versioned_data_fixture(tmp_path)
    base = tmp_path / "base-model"
    base.mkdir()
    (base / "config.json").write_text("{}")
    store = open_train_store(root / "workspace/mlflow")
    parent = create_train_run(store, "train-v4.1-r1", data_version="data-v4.1-r2",
        prompt_version="prompt-v4.1-r1", git_commit="fixture", base_model=str(base), config={"fixture": True})
    client = MlflowClient(tracking_uri=store.tracking_uri)
    for fold in range(3):
        create_fold_run(store, "train-v4.1-r1", fold)
        end_fold_run(store, "train-v4.1-r1", fold, "FINISHED", metrics={"loss": 0.2})
        artifact = tmp_path / f"adapter{fold}"
        artifact.mkdir()
        (artifact / "adapter_config.json").write_text("{}")
        (artifact / "adapter_model.safetensors").write_bytes(b"fixture")
        client.log_artifacts(parent.run_id, str(artifact), artifact_path=f"fold{fold}/{kind}")
    log_train_summary(store, "train-v4.1-r1", {"loss_mean": 0.2})
    transition_train_state(store, "train-v4.1-r1", "completed")
    registry = open_registry_store(store.root, data_root=root / "data")
    model = register_model(registry, "model-v4.1-r1", train_id="train-v4.1-r1",
        source_scope=scope, deploy_target=None if scope == "cross_validation" else f"artifacts/fold0/{kind}",
        artifacts={f"fold{i}": {kind: f"artifacts/fold{i}/{kind}"} for i in (range(3) if scope == "cross_validation" else [0])})
    config = {"scope": scope, "split": "validation", "artifact_kind": kind,
        "scorer": "strict-v4.1", "sample_selection": "all", "quantization_bit": None, "aggregation": "pooled",
        "generation": {"do_sample": False, "num_beams": 1, "max_new_tokens": 256, "video_max_frames": 8},
        "thresholds": {"joint_correct_rate": 1.0}}
    return root, media, model, config


def _prepare_formal(tmp_path):
    root, media, model, config = _formal_eval_fixture(tmp_path)
    path = evaluation_cli.prepare_versioned_evaluation(root=root, eval_version="eval-v4.1-r1",
        model_version=model.model_id, model_version_number=model.version,
        data_version="data-v4.1-r2", config=config, git_commit="fixture", media_root=media)
    return root, media, model, path


def _fake_formal_runtime(monkeypatch, *, runtime_error=False, invalid_output=False):
    from types import SimpleNamespace
    calls = []
    def load(model_dir, **kwargs):
        calls.append((model_dir, kwargs))
        return object(), object()
    def infer(model, processor, video_path, prompt, **kwargs):
        assert Path(video_path).is_file()
        assert prompt == "frozen user"
        assert kwargs["system_prompt"] == "frozen system"
        if runtime_error:
            raise RuntimeError("fixture inference failure")
        import json
        return SimpleNamespace(raw_output="bad json" if invalid_output else json.dumps(_labels("未断裂"), ensure_ascii=False),
            sampled_timestamps=[0.0], generated_token_count=10, hit_token_limit=False)
    monkeypatch.setattr(evaluation_cli, "load_model", load)
    monkeypatch.setattr(evaluation_cli, "run_model_on_video_detailed", infer)
    monkeypatch.setattr(evaluation_cli, "current_data_paths", lambda *a: pytest.fail("legacy current data was consulted"))
    return calls


def test_formal_prepare_validates_registry_before_weights(tmp_path, monkeypatch):
    root, media, model, config = _formal_eval_fixture(tmp_path)
    monkeypatch.setattr(evaluation_cli, "load_model", lambda *a, **k: pytest.fail("prepare loaded weights"))
    import versioning.registry as registry
    monkeypatch.setattr(registry, "materialize_model", lambda *a, **k: pytest.fail("prepare materialized weights"))
    with pytest.raises(ValueError):
        evaluation_cli.prepare_versioned_evaluation(root=root, eval_version="eval-v4.1-r1",
            model_version=model.model_id, model_version_number=model.version + 1,
            data_version="data-v4.1-r2", config=config, git_commit="fixture", media_root=media)
    assert not (root / "workspace/evaluations/eval-v4.1-r1/input").exists()
    path = evaluation_cli.prepare_versioned_evaluation(root=root, eval_version="eval-v4.1-r1",
        model_version=model.model_id, model_version_number=model.version,
        data_version="data-v4.1-r2", config=config, git_commit="fixture", media_root=media)
    assert path.is_file()
    from versioning.mlflow_eval import get_eval_run, open_eval_store, EvalRecordNotFound
    with pytest.raises(EvalRecordNotFound):
        get_eval_run(open_eval_store(root / "workspace/mlflow"), "eval-v4.1-r1")


@pytest.mark.parametrize("invalid_output,expected_outcome", [(False, "passed"), (True, "failed")])
def test_formal_evaluation_actual_dispatch_and_quality_outcome(tmp_path, monkeypatch, invalid_output, expected_outcome):
    root, media, model, path = _prepare_formal(tmp_path)
    calls = _fake_formal_runtime(monkeypatch, invalid_output=invalid_output)
    result = evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert result.workflow_state == "completed"
    assert result.outcome == expected_outcome
    assert len(calls) == 3
    assert [Path(k["adapter_dir"]).parent.name for _, k in calls] == ["fold0", "fold1", "fold2"]
    assert set(result.folds) == {0, 1, 2}
    assert all(f.status == "FINISHED" and f.sample_count == 1 for f in result.folds.values())
    manifest = root / "records/evaluations/eval-v4.1-r1/manifest.yaml"
    assert manifest.is_file()
    assert result.metrics["joint_correct_rate"] == (0.0 if invalid_output else 1.0)


def test_formal_evaluation_runtime_failure_has_no_conclusion(tmp_path, monkeypatch):
    from versioning.mlflow_eval import get_eval_run, open_eval_store
    root, media, model, path = _prepare_formal(tmp_path)
    calls = _fake_formal_runtime(monkeypatch, runtime_error=True)
    with pytest.raises(RuntimeError, match="incomplete"):
        evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    result = get_eval_run(open_eval_store(root / "workspace/mlflow"), "eval-v4.1-r1")
    assert result.workflow_state == "failed"
    assert result.outcome is None
    assert result.folds[0].status == "FAILED"
    assert len(calls) == 1
    assert not (root / "records/evaluations/eval-v4.1-r1/manifest.yaml").exists()
    assert (root / "workspace/evaluations/eval-v4.1-r1/output/fold0/failures.jsonl").is_file()


def test_formal_evaluation_media_drift_stops_before_weights(tmp_path, monkeypatch):
    root, media, model, path = _prepare_formal(tmp_path)
    calls = _fake_formal_runtime(monkeypatch)
    next(media.rglob("*.mp4")).write_bytes(b"changed")
    with pytest.raises(ValueError, match="drift|frozen"):
        evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert not calls


def test_formal_evaluation_export_retries_without_inference(tmp_path, monkeypatch):
    import versioning.manifest as manifests
    root, media, model, path = _prepare_formal(tmp_path)
    calls = _fake_formal_runtime(monkeypatch)
    original = manifests._publish_immutable
    def fail_export(target, *args, **kwargs):
        if "records/evaluations" in str(target):
            raise OSError("export unavailable")
        return original(target, *args, **kwargs)
    monkeypatch.setattr(manifests, "_publish_immutable", fail_export)
    with pytest.raises(OSError, match="export unavailable"):
        evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    monkeypatch.setattr(manifests, "_publish_immutable", original)
    exported = evaluation_cli.export_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert exported.is_file()
    assert len(calls) == 3
    assert evaluation_cli.export_versioned_evaluation(root=root, eval_version="eval-v4.1-r1") == exported


def test_formal_cli_prepare_validate_run_export(tmp_path, monkeypatch, capsys):
    import json
    import yaml
    from versioning.cli import main
    root, media, model, config = _formal_eval_fixture(tmp_path)
    config_file = tmp_path / "eval-config.yaml"
    config_file.write_text(yaml.safe_dump(config))
    common = ["eval", "prepare", "eval-v4.1-r1", "--root", str(root),
        "--model-version", model.model_id, "--model-version-number", str(model.version),
        "--data-version", "data-v4.1-r2", "--config", str(config_file),
        "--git-commit", "fixture", "--media-root", str(media)]
    assert main(common) == 0
    assert main(["eval", "validate", "eval-v4.1-r1", "--root", str(root)]) == 0
    calls = _fake_formal_runtime(monkeypatch)
    assert main(["eval", "run", "eval-v4.1-r1", "--root", str(root)]) == 0
    assert main(["eval", "export", "eval-v4.1-r1", "--root", str(root)]) == 0
    assert len(calls) == 3
    assert main(["eval", "run", "eval-v4.1-r1", "--root", str(root), "--store", str(tmp_path / "another-store")]) != 0
    assert len(calls) == 3


def test_formal_cli_rejects_raw_model_directory(tmp_path, monkeypatch):
    from versioning.cli import main
    calls = _fake_formal_runtime(monkeypatch)
    assert main(["eval", "run", "eval-v4.1-r1", "--root", str(tmp_path), "--model-dir", "/raw/model"]) == 2
    assert calls == []


def test_formal_import_does_not_read_legacy_pointer():
    import subprocess
    script = '''
from pathlib import Path
original = Path.read_text
def guarded(path, *args, **kwargs):
    if path.name == "active_data_release.json":
        raise AssertionError("legacy pointer consulted")
    return original(path, *args, **kwargs)
Path.read_text = guarded
import finetune.eval_run
from finetune.release_validate import validate_versioned_training_release
'''
    result = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("change", [
    {"scope": "full"}, {"split": "test"}, {"sample_selection": "first_3"},
    {"thresholds": {}}, {"thresholds": {"made_up_metric": 0.5}},
    {"thresholds": {"joint_correct_rate": True}}, {"thresholds": {"joint_correct_rate": float("nan")}},
    {"generation": {"do_sample": True}}, {"model_dir": "/raw/model"},
])
def test_formal_config_rejects_unbound_policy(tmp_path, change):
    root, media, model, config = _formal_eval_fixture(tmp_path)
    config.update(change)
    with pytest.raises(ValueError):
        evaluation_cli.prepare_versioned_evaluation(root=root, eval_version="eval-v4.1-r1",
            model_version=model.model_id, model_version_number=model.version,
            data_version="data-v4.1-r2", config=config, git_commit="fixture", media_root=media)
    assert not (root / "workspace/evaluations/eval-v4.1-r1/input").exists()


def test_formal_holdout_refuses_before_dataset_or_weights(tmp_path, monkeypatch):
    from dataclasses import replace
    from versioning.data_release import load_release_metadata
    import versioning.data_release as releases
    import finetune.train_build_dataset as datasets
    root, media, model, config = _formal_eval_fixture(tmp_path)
    actual = load_release_metadata(root / "data", "data-v4.1-r2")
    monkeypatch.setattr(releases, "load_release_metadata", lambda *a: replace(actual, purpose="holdout"))
    monkeypatch.setattr(datasets, "build_versioned_datasets", lambda **k: pytest.fail("holdout contents read"))
    with pytest.raises(ValueError, match="holdout"):
        evaluation_cli.prepare_versioned_evaluation(root=root, eval_version="eval-v4.1-r1",
            model_version=model.model_id, model_version_number=model.version,
            data_version="data-v4.1-r2", config=config, git_commit="fixture", media_root=media)


def test_formal_config_tampering_stops_before_load(tmp_path, monkeypatch):
    root, media, model, path = _prepare_formal(tmp_path)
    path.chmod(0o644)
    path.write_bytes(path.read_bytes().replace(b'"joint_correct_rate": 1.0', b'"joint_correct_rate": 0.0'))
    path.chmod(0o444)
    calls = _fake_formal_runtime(monkeypatch)
    with pytest.raises(ValueError, match="digest drift"):
        evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert not calls


def test_formal_registry_drift_stops_before_materialization(tmp_path, monkeypatch):
    import versioning.registry as registry
    from mlflow.tracking import MlflowClient
    root, media, model, path = _prepare_formal(tmp_path)
    store = registry.open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    MlflowClient(tracking_uri=store.tracking_uri).set_model_version_tag("mVllm2", str(model.version), "record_validity", "invalid")
    monkeypatch.setattr(registry, "materialize_model", lambda *a: pytest.fail("invalid model materialized"))
    with pytest.raises(ValueError):
        evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")


def test_formal_export_uses_mlflow_and_rejects_artifact_drift(tmp_path, monkeypatch):
    from mlflow.tracking import MlflowClient
    from versioning.mlflow_eval import open_eval_store
    root, media, model, path = _prepare_formal(tmp_path)
    _fake_formal_runtime(monkeypatch)
    result = evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    local = root / "workspace/evaluations/eval-v4.1-r1/output/summary.json"
    local.write_text("local staging is not authoritative")
    assert evaluation_cli.export_versioned_evaluation(root=root, eval_version="eval-v4.1-r1").is_file()
    store = open_eval_store(root / "workspace/mlflow")
    client = MlflowClient(tracking_uri=store.tracking_uri)
    tampered = tmp_path / "summary.json"
    tampered.write_text('{}')
    client.log_artifact(result.run_id, str(tampered))
    with pytest.raises(ValueError, match="digest mismatch"):
        evaluation_cli.export_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")


def test_formal_cli_run_rejects_input_overrides(tmp_path, monkeypatch):
    from versioning.cli import main
    root, media, model, path = _prepare_formal(tmp_path)
    calls = _fake_formal_runtime(monkeypatch)
    assert main(["eval", "run", "eval-v4.1-r1", "--root", str(root), "--model-version", "model-v4.1-r99"]) == 2
    assert main(["eval", "run", "eval-v4.1-r1", "--root", str(root), "--outcome", "passed"]) == 2
    assert calls == []


@pytest.mark.parametrize("scope,kind", [("single_fold", "adapter"), ("cross_validation", "merged")])
def test_formal_other_registered_layouts_dispatch_correctly(tmp_path, monkeypatch, scope, kind):
    root, media, model, config = _formal_eval_fixture(tmp_path, scope=scope, kind=kind)
    evaluation_cli.prepare_versioned_evaluation(root=root, eval_version="eval-v4.1-r1",
        model_version=model.model_id, model_version_number=model.version,
        data_version="data-v4.1-r2", config=config, git_commit="fixture", media_root=media)
    calls = _fake_formal_runtime(monkeypatch)
    result = evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert result.outcome == "passed"
    assert len(calls) == (1 if scope == "single_fold" else 3)
    if kind == "merged":
        assert all(Path(path).name == "merged" and kwargs["adapter_dir"] is None for path, kwargs in calls)


def test_formal_mid_execution_media_drift_cannot_complete(tmp_path, monkeypatch):
    from versioning.mlflow_eval import open_eval_store, get_eval_run
    root, media, model, path = _prepare_formal(tmp_path)
    _fake_formal_runtime(monkeypatch)
    original = evaluation_cli.run_model_on_video_detailed
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(args[2]).write_bytes(b"mutated during inference")
        return result
    monkeypatch.setattr(evaluation_cli, "run_model_on_video_detailed", mutate)
    with pytest.raises(ValueError, match="drift"):
        evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    result = get_eval_run(open_eval_store(root / "workspace/mlflow"), "eval-v4.1-r1")
    assert result.workflow_state == "failed"
    assert result.outcome is None


def test_formal_mid_execution_base_drift_cannot_complete(tmp_path, monkeypatch):
    root, media, model, path = _prepare_formal(tmp_path)
    _fake_formal_runtime(monkeypatch)
    original = evaluation_cli.load_model
    def mutate(model_dir, **kwargs):
        result = original(model_dir, **kwargs)
        (Path(model_dir) / "config.json").write_text('{"changed": true}')
        return result
    monkeypatch.setattr(evaluation_cli, "load_model", mutate)
    with pytest.raises(ValueError, match="weights drifted"):
        evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert not (root / "records/evaluations/eval-v4.1-r1/manifest.yaml").exists()


@pytest.mark.parametrize("alias_kind", ["directory", "wrong_symlink"])
def test_formal_loader_alias_collision_rejects_before_loading(tmp_path, monkeypatch, alias_kind):
    root, media, model, path = _prepare_formal(tmp_path)
    collision = Path(model.base_model).with_name("base_model")
    if alias_kind == "directory":
        collision.mkdir()
    else:
        other = tmp_path / "other-model"
        other.mkdir()
        collision.symlink_to(other, target_is_directory=True)
    (collision / "config.json").write_text('{"other_model": true}')
    calls = _fake_formal_runtime(monkeypatch)
    with pytest.raises(ValueError, match="loader.*alias"):
        evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert calls == []


def test_formal_loader_correct_alias_preserves_identity(tmp_path, monkeypatch):
    root, media, model, path = _prepare_formal(tmp_path)
    alias = Path(model.base_model).with_name("base_model")
    alias.symlink_to(Path(model.base_model), target_is_directory=True)
    calls = _fake_formal_runtime(monkeypatch)
    result = evaluation_cli.execute_versioned_evaluation(root=root, eval_version="eval-v4.1-r1")
    assert result.outcome == "passed"
    assert all(Path(path).resolve() == Path(model.base_model).resolve() for path, _ in calls)


def test_formal_requires_explicit_aggregation_rule(tmp_path):
    root, media, model, config = _formal_eval_fixture(tmp_path)
    config.pop("aggregation", None)
    with pytest.raises(ValueError, match="config|aggregation"):
        evaluation_cli.prepare_versioned_evaluation(root=root, eval_version="eval-v4.1-r1",
            model_version=model.model_id, model_version_number=model.version,
            data_version="data-v4.1-r2", config=config, git_commit="fixture", media_root=media)
