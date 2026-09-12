from __future__ import annotations

import sys

from finetune.train_with_contract import LLAMAFACTORY_SRC, ROOT


def test_training_entrypoint_prefers_current_repository_llamafactory() -> None:
    assert LLAMAFACTORY_SRC == ROOT / "LlamaFactory/src"
    assert sys.path.index(str(LLAMAFACTORY_SRC)) < sys.path.index(str(ROOT))


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


def test_cli_rejects_duplicate_yaml_keys_before_execution(monkeypatch, tmp_path):
    import pytest
    from finetune import train_with_contract as entry

    path = tmp_path / "training.yaml"
    path.write_text("seed: 3411\nseed: 42\n")
    events = _fake_training_modules(monkeypatch, lambda config: events.append("tuner"))
    monkeypatch.setattr(sys, "argv", ["train_with_contract.py", str(path)])
    with pytest.raises(ValueError, match="duplicate"):
        entry.main()
    assert events == []
