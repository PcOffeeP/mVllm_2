from __future__ import annotations

import sys

from finetune.train_with_contract import LLAMAFACTORY_SRC, ROOT


def test_training_entrypoint_prefers_current_repository_llamafactory() -> None:
    import subprocess

    assert LLAMAFACTORY_SRC == ROOT / "LlamaFactory/src"
    # Collection of unrelated tests may edit this process's sys.path. Import
    # the public adapter in a fresh process to check its own path setup.
    code = (
        "import sys; from finetune.train_with_contract import LLAMAFACTORY_SRC, ROOT; "
        "assert sys.path.index(str(LLAMAFACTORY_SRC)) < sys.path.index(str(ROOT))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# M4a Test List: in-memory frozen config reaches the real tuner unchanged;
# malformed config fails before processor/model imports; injected tuner errors
# propagate; mutable tuner arguments cannot mutate the caller's frozen input.

def _fake_training_modules(monkeypatch, run_exp, *, source=None):
    import types
    import finetune.train_with_contract as entry

    events = []
    monkeypatch.setattr(entry, "install_training_processor_contract", lambda: events.append("contract"))
    monkeypatch.setitem(sys.modules, "llamafactory", types.SimpleNamespace(
        __file__=str(source or LLAMAFACTORY_SRC / "llamafactory/__init__.py")
    ))
    monkeypatch.setitem(sys.modules, "llamafactory.train.tuner", types.SimpleNamespace(run_exp=run_exp))
    return events


def test_run_training_uses_supplied_config_and_installs_contract(monkeypatch):
    from finetune import train_with_contract as entry

    received = []
    events = _fake_training_modules(monkeypatch, lambda config: received.append(config))
    config = {"model_name_or_path": "/explicit/model", "seed": 3411,
              "lora_target": ["q_proj", "v_proj"], "do_train": True}
    entry.run_training(config)
    assert received == [config]
    assert events == ["contract"]


def test_run_training_does_not_mutate_frozen_input(monkeypatch):
    from finetune import train_with_contract as entry

    config = {"lora_target": ["q_proj"]}
    _fake_training_modules(monkeypatch, lambda actual: actual["lora_target"].append("v_proj"))
    entry.run_training(config)
    assert config == {"lora_target": ["q_proj"]}


def test_run_training_propagates_execution_failure(monkeypatch):
    import pytest
    from finetune import train_with_contract as entry

    def fail(config):
        raise RuntimeError("controlled executor failure")
    _fake_training_modules(monkeypatch, fail)
    with pytest.raises(RuntimeError, match="controlled executor failure"):
        entry.run_training({"seed": 3411})


def test_run_training_rejects_wrong_llamafactory_before_tuner(monkeypatch, tmp_path):
    import pytest
    from finetune import train_with_contract as entry

    received = []
    _fake_training_modules(monkeypatch, lambda config: received.append(config), source=tmp_path / "__init__.py")
    with pytest.raises(RuntimeError, match="source drifted"):
        entry.run_training({"seed": 3411})
    assert received == []


def test_run_training_rejects_invalid_mapping_before_processor(monkeypatch):
    import pytest
    from finetune import train_with_contract as entry

    events = _fake_training_modules(monkeypatch, lambda config: events.append("tuner"))
    for invalid in (None, [], {}, {1: "value"}, {"": "value"}):
        with pytest.raises(ValueError, match="training config"):
            entry.run_training(invalid)
    assert events == []


def test_legacy_yaml_parser_rejects_duplicate_keys_before_execution(monkeypatch, tmp_path):
    import pytest
    from finetune import train_with_contract as entry

    path = tmp_path / "training.yaml"
    path.write_text("seed: 3411\nseed: 42\n")
    events = _fake_training_modules(monkeypatch, lambda config: events.append("tuner"))
    monkeypatch.setattr(sys, "argv", ["train_with_contract.py", str(path)])
    with pytest.raises(ValueError, match="duplicate"):
        entry._legacy_main()
    assert events == []


def _mirror_prompt_checkout(root, *, version="prompt-v4.1-r1"):
    """在 <store 根>/../records/prompts 写入与 store 副本逐字节一致的 checkout 副本。

    训练冻结与评测取 Prompt 都会先要求两侧字节一致，因此真正跑 prepare 或
    prepare_versioned_evaluation 的夹具必须先建立这份副本。
    """
    from versioning.prompts import prompt_path

    checkout = prompt_path(root.parent, version)
    checkout.parent.mkdir(parents=True, exist_ok=True)
    checkout.write_bytes(prompt_path(root, version).read_bytes())
    return checkout


def _versioned_data_fixture(tmp_path, *, prompt_definition=None):
    import json
    import yaml
    from versioning.data_release import seal_payload
    from versioning.migration import _release_content_digest
    from versioning.prompts import create_prompt

    root = tmp_path / "store"
    media = tmp_path / "original/workspace/data"
    release = root / "data/releases/data-v4.1-r2"
    payload = release
    labels = {"clip_state": "未断裂", "fracture_mechanism": None,
              "fracture_site": None, "special_case": None}
    rows = []
    for fold in range(3):
        path = media / f"derived/subvideos/video_{fold:04d}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"isolated media fixture")
        rows.append({"videos": [f"data/03_subvideos/video_{fold:04d}.mp4"], "messages": [
            {"role": "system", "content": "old system"},
            {"role": "user", "content": "<video>\nold user"},
            {"role": "assistant", "content": json.dumps(labels, ensure_ascii=False)}]})
    for fold in range(3):
        for split in ("train", "validation"):
            path = payload / f"datasets/{split}/fold_{fold}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            chosen = [row for i, row in enumerate(rows) if (i == fold) == (split == "validation")]
            path.write_text(json.dumps(chosen, ensure_ascii=False))
    (release / "release.yaml").write_text(yaml.safe_dump({
        "version": "data-v4.1-r2", "protocol": "tensile-vlm/v4.1", "state": "sealed",
        "purpose": "development", "training_allowed": True, "status": "active",
        "description": "isolated fixture", "sample_count": 3, "source_batches": ["fixture"],
        "splits": {f"fold_{i}": {"train": 2, "validation": 1} for i in range(3)}}))
    seal_payload(release)
    receipt = root / "migration_receipts/data-v4.1-r2.receipt.yaml"
    receipt.parent.mkdir()
    receipt.write_text(yaml.safe_dump({"target_identity": "data-v4.1-r2",
        "target_path": "data/releases/data-v4.1-r2/release.yaml", "status": "committed",
        "target_release_digest": _release_content_digest(release)}))
    definition = prompt_definition or {"system_prompt": "frozen system", "user_prompt": "frozen user", "output_fields": list(labels)}
    create_prompt(root, "v4.1", version="prompt-v4.1-r1", **definition)
    return root, media, release, rows


def test_versioned_datasets_keep_each_fold_members_and_labels(tmp_path):
    import json
    from finetune.train_build_dataset import build_versioned_datasets

    root, media, release, original = _versioned_data_fixture(tmp_path)
    files, binding = build_versioned_datasets(root=root, data_version="data-v4.1-r2",
        prompt_version="prompt-v4.1-r1", media_root=media)
    assert binding["media_root"] == str(media)
    for fold in range(3):
        for split in ("train", "validation"):
            rows = json.loads(files[f"datasets/{split}/fold_{fold}.json"])
            source = json.loads((release / f"datasets/{split}/fold_{fold}.json").read_text())
            assert len(rows) == len(source)
            for row, old in zip(rows, source):
                assert row["messages"][2] == old["messages"][2]
                assert row["messages"][0]["content"] == "frozen system"
                assert row["messages"][1]["content"] == "<video>\nfrozen user"
                assert (media / row["videos"][0]).is_file()
    assert not (root / "workspace/runs").exists()


def test_versioned_datasets_reject_wrong_external_media_root(tmp_path):
    import pytest
    from finetune.train_build_dataset import build_versioned_datasets

    root, media, release, original = _versioned_data_fixture(tmp_path)
    wrong = root / "workspace/data"
    wrong.mkdir(parents=True)
    with pytest.raises(ValueError, match="media"):
        build_versioned_datasets(root=root, data_version="data-v4.1-r2",
            prompt_version="prompt-v4.1-r1", media_root=wrong)


def test_versioned_datasets_reject_payload_drift(tmp_path):
    import pytest
    from finetune.train_build_dataset import build_versioned_datasets

    root, media, release, original = _versioned_data_fixture(tmp_path)
    path = release / "datasets/train/fold_0.json"
    path.chmod(0o644)
    path.write_text("[]")
    path.chmod(0o444)
    with pytest.raises(ValueError, match="receipt"):
        build_versioned_datasets(root=root, data_version="data-v4.1-r2",
            prompt_version="prompt-v4.1-r1", media_root=media)


def _prepare_versioned_fixture(tmp_path):
    from finetune.train_prepare_run import prepare_versioned_run
    root, media, release, rows = _versioned_data_fixture(tmp_path)
    _mirror_prompt_checkout(root)
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.safetensors").write_bytes(b"synthetic base")
    configs = {f"fold{i}": {"seed": 3411 + i, "model_name_or_path": str(model),
        "learning_rate": 0.0001, "do_train": True} for i in range(3)}
    prepared = prepare_versioned_run(root=root, train_version="train-v4.1-r1",
        data_version="data-v4.1-r2", prompt_version="prompt-v4.1-r1",
        media_root=media, fold_configs=configs, git_commit="test-commit",
        environment={"python": "fixture"})
    return root, media, release, prepared


def test_versioned_prepare_freezes_three_folds_without_creating_run(tmp_path):
    import yaml
    root, media, release, prepared = _prepare_versioned_fixture(tmp_path)
    training = yaml.safe_load((prepared / "training.yaml").read_text())
    assert not (root / "workspace/mlflow").exists()
    for fold in range(3):
        config = training["folds"][f"fold{fold}"]
        assert config["seed"] == 3411 + fold
        assert config["dataset"] == f"tensile_v4_1_fold{fold}_train"
        assert config["eval_dataset"] == f"tensile_v4_1_fold{fold}_val"
        assert config["media_dir"] == str(media)
    assert (prepared / "prompt.yaml").is_file()
    assert all(not p.stat().st_mode & 0o222 for p in prepared.rglob("*") if p.is_file())


def test_versioned_execution_calls_real_adapter_and_records_all_folds(tmp_path, monkeypatch):
    import json
    from finetune import train_with_contract
    from finetune.train_prepare_run import execute_versioned_run
    from versioning.mlflow_train import get_train_run, open_train_store

    root, media, release, prepared = _prepare_versioned_fixture(tmp_path)
    calls = []
    def tuner(config):
        calls.append(config)
        output = Path(config["output_dir"])
        output.mkdir(parents=True)
        (output / "train_results.json").write_text(json.dumps({"train_loss": 0.25}))
        (output / "adapter_config.json").write_text("{}")
        (output / "adapter_model.safetensors").write_bytes(b"synthetic adapter")
    from pathlib import Path
    monkeypatch.setattr(train_with_contract, "run_training", tuner)
    result = execute_versioned_run(root=root, train_version="train-v4.1-r1")
    assert [c["seed"] for c in calls] == [3411, 3412, 3413]
    assert result.workflow_state == "completed"
    assert all(f.status == "FINISHED" for f in result.folds.values())
    assert (root / "records/training/train-v4.1-r1/manifest.yaml").is_file()


def test_versioned_execution_rejects_frozen_input_tampering_before_run(tmp_path, monkeypatch):
    import pytest
    from finetune import train_with_contract
    from finetune.train_prepare_run import execute_versioned_run

    root, media, release, prepared = _prepare_versioned_fixture(tmp_path)
    path = prepared / "training.yaml"
    path.chmod(0o644)
    path.write_text(path.read_text().replace("3411", "9999"))
    path.chmod(0o444)
    calls = []
    monkeypatch.setattr(train_with_contract, "run_training", lambda config: calls.append(config))
    with pytest.raises(ValueError, match="frozen"):
        execute_versioned_run(root=root, train_version="train-v4.1-r1")
    assert calls == []
    assert not (root / "workspace/mlflow").exists()


def test_versioned_prepare_rejects_tokenized_cache(tmp_path):
    import pytest
    from finetune.train_prepare_run import prepare_versioned_run
    root, media, release, rows = _versioned_data_fixture(tmp_path)
    _mirror_prompt_checkout(root)
    configs = {f"fold{i}": {"model_name_or_path": str(tmp_path), "tokenized_path": str(tmp_path / "cache")} for i in range(3)}
    with pytest.raises(ValueError, match="tokenized_path"):
        prepare_versioned_run(root=root, train_version="train-v4.1-r1", data_version="data-v4.1-r2",
            prompt_version="prompt-v4.1-r1", media_root=media, fold_configs=configs,
            git_commit="fixture", environment={"python": "fixture"})
    assert not (root / "workspace/runs/train-v4.1-r1/input").exists()


def test_versioned_validate_rejects_changed_media_bytes(tmp_path):
    import pytest
    from finetune.train_prepare_run import verify_versioned_run
    root, media, release, prepared = _prepare_versioned_fixture(tmp_path)
    next(media.rglob("*.mp4")).write_bytes(b"changed media")
    with pytest.raises(ValueError, match="frozen"):
        verify_versioned_run(root=root, train_version="train-v4.1-r1")


def test_completed_training_can_recover_failed_export_without_execution(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    import pytest
    import versioning.manifest as manifests
    from finetune import train_with_contract
    from finetune import train_prepare_run as preparation
    root, media, release, prepared = _prepare_versioned_fixture(tmp_path)
    calls = []
    def tuner(config):
        calls.append(config)
        output = Path(config["output_dir"])
        output.mkdir(parents=True)
        (output / "train_results.json").write_text(json.dumps({"train_loss": 0.25}))
        (output / "adapter_config.json").write_text("{}")
        (output / "adapter_model.safetensors").write_bytes(b"synthetic adapter")
    monkeypatch.setattr(train_with_contract, "run_training", tuner)
    original = manifests._publish_immutable
    def fail_export(*args, **kwargs):
        if kwargs.get("label") == "training manifest":
            raise OSError("export unavailable")
        return original(*args, **kwargs)
    monkeypatch.setattr(manifests, "_publish_immutable", fail_export)
    with pytest.raises(OSError, match="export unavailable"):
        preparation.execute_versioned_run(root=root, train_version="train-v4.1-r1")
    monkeypatch.setattr(manifests, "_publish_immutable", original)
    path = preparation.export_versioned_run(root=root, train_version="train-v4.1-r1")
    assert path.is_file()
    assert len(calls) == 3


# M7b: public legacy launchers must reject before imports or raw path selection.
import pytest


@pytest.mark.parametrize("module", ["train_build_dataset", "train_prepare_run", "train_with_contract", "eval_run"])
def test_retired_training_cli_rejects_before_legacy_dispatch(module, monkeypatch, capsys):
    import importlib
    entry = importlib.import_module("finetune." + module)

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy dispatch reached")

    for name in ("parse_args", "run_training", "current_data_paths", "_load_active_release_id"):
        if hasattr(entry, name):
            monkeypatch.setattr(entry, name, forbidden)
    monkeypatch.setattr(sys, "argv", [module, "--legacy", "/must-not-read"])
    assert entry.main() == 2
    assert "python -m versioning" in capsys.readouterr().err


@pytest.mark.parametrize("module", ["train_build_dataset", "train_prepare_run", "train_with_contract", "eval_run"])
def test_retired_training_cli_runs_without_site_packages(module, tmp_path):
    import subprocess
    for prefix in ([sys.executable, "-S", str(ROOT / "finetune" / (module + ".py"))],
                   [sys.executable, "-S", "-m", "finetune." + module]):
        for arguments, expected in (([], 2), (["--legacy"], 2),
                                    (["--model-dir", str(tmp_path / "model"), "--out-dir", str(tmp_path / "output")], 2),
                                    ([str(tmp_path / "training.yaml")], 2),
                                    (["--help"], 0), (["-h"], 0)):
            result = subprocess.run(prefix + arguments, cwd=ROOT, text=True, capture_output=True)
            assert result.returncode == expected, result.stderr
            assert "python -m versioning" in result.stdout + result.stderr
            assert not (tmp_path / "output").exists()


def test_registry_rejects_completed_train_without_execution_evidence(tmp_path):
    import pytest
    from versioning.mlflow_train import (open_train_store, create_train_run, create_fold_run,
        end_fold_run, log_train_summary, transition_train_state)
    from versioning.registry import open_registry_store, register_model, PromotionGateRejected
    from mlflow.tracking import MlflowClient
    root, media, release, rows = _versioned_data_fixture(tmp_path)
    store = open_train_store(root / 'workspace/mlflow')
    create_train_run(store, 'train-v4.1-r1', data_version='data-v4.1-r2',
        prompt_version='prompt-v4.1-r1', git_commit='unexecuted', base_model='missing', config={'epochs': 1})
    for fold in range(3):
        create_fold_run(store, 'train-v4.1-r1', fold)
        end_fold_run(store, 'train-v4.1-r1', fold, 'FINISHED', metrics={'loss': 0.1})
    log_train_summary(store, 'train-v4.1-r1', {'loss_mean': 0.1})
    transition_train_state(store, 'train-v4.1-r1', 'completed')
    registry = open_registry_store(store.root, data_root=root / 'data')
    with pytest.raises(PromotionGateRejected, match='evidence|证据'):
        register_model(registry, 'model-v4.1-r1', train_id='train-v4.1-r1')
    assert not MlflowClient(tracking_uri=store.tracking_uri).search_model_versions("name='mVllm2'")


def test_training_base_drift_before_run_creates_no_run(tmp_path, monkeypatch):
    import pytest
    from finetune.train_prepare_run import execute_versioned_run
    root, _, _, _ = _prepare_versioned_fixture(tmp_path)
    (tmp_path / "model/model.safetensors").write_bytes(b"different base")
    calls = []
    monkeypatch.setattr("finetune.train_with_contract.run_training", lambda config: calls.append(config))
    with pytest.raises(ValueError, match="base model"):
        execute_versioned_run(root=root, train_version="train-v4.1-r1")
    assert calls == []
    assert not (root / "workspace/mlflow").exists()


def test_training_base_drift_during_fold_marks_run_failed(tmp_path, monkeypatch):
    import pytest
    from finetune.train_prepare_run import execute_versioned_run
    from versioning.mlflow_train import open_train_store, get_train_run
    root, _, _, _ = _prepare_versioned_fixture(tmp_path)
    calls = []
    def tuner(config):
        calls.append(config)
        (tmp_path / "model/model.safetensors").write_bytes(b"different base")
    monkeypatch.setattr("finetune.train_with_contract.run_training", tuner)
    with pytest.raises(ValueError, match="base model"):
        execute_versioned_run(root=root, train_version="train-v4.1-r1")
    record = get_train_run(open_train_store(root / "workspace/mlflow"), "train-v4.1-r1")
    assert record.workflow_state == "failed"
    assert len(calls) == 1
    assert not (root / "records/training/train-v4.1-r1/manifest.yaml").exists()
