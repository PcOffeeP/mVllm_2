"""Synthetic full-data execution; no GPU or real development/holdout access."""
import json
from pathlib import Path

import pytest
import yaml

from tests.test_train_with_contract import _versioned_data_fixture
from finetune.train_prepare_run import prepare_versioned_run, execute_versioned_run, verify_versioned_run
from versioning.mlflow_train import open_train_store, get_train_run, create_fold_run
from versioning.registry import open_registry_store, register_model


def prepare_full(tmp_path, **overrides):
    root, media, release, rows = _versioned_data_fixture(tmp_path)
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'model.safetensors').write_bytes(b'synthetic base')
    config = {'model_name_or_path': str(base), 'seed': 3411, 'do_train': True,
              'learning_rate': 0.0001, 'num_train_epochs': 2, **overrides}
    path = prepare_versioned_run(root=root, train_version='train-v4.1-r1',
        data_version='data-v4.1-r2', prompt_version='prompt-v4.1-r1', media_root=media,
        fold_configs={'full': config}, scope='full', git_commit='synthetic', environment={'python': 'fixture'})
    return root, path


@pytest.mark.parametrize('scope', ['cross_validation', 'full'])
@pytest.mark.parametrize('external_input', ['adapter_name_or_path', 'resume_from_checkpoint'])
def test_unfrozen_external_weights_fail_before_training_freeze(tmp_path, scope, external_input):
    root, media, _, _ = _versioned_data_fixture(tmp_path)
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'model.safetensors').write_bytes(b'base')
    external = tmp_path / 'external-weights'
    external.mkdir()
    (external / 'adapter_model.safetensors').write_bytes(b'initial')
    value = [str(external)] if external_input == 'adapter_name_or_path' else str(external)
    config = {'model_name_or_path': str(base), external_input: value}
    configs = {'full': config} if scope == 'full' else {f'fold{i}': config for i in range(3)}
    with pytest.raises(ValueError, match=external_input):
        prepare_versioned_run(root=root, train_version='train-v4.1-r1',
            data_version='data-v4.1-r2', prompt_version='prompt-v4.1-r1', media_root=media,
            fold_configs=configs, scope=scope, git_commit='synthetic', environment={'python': 'fixture'})
    assert not (root / 'workspace/runs/train-v4.1-r1/input').exists()
    assert not (root / 'workspace/mlflow').exists()


@pytest.mark.parametrize('scope,external_input', [
    ('full', 'adapter_name_or_path'), ('cross_validation', 'resume_from_checkpoint')])
def test_old_frozen_external_weights_cannot_execute(tmp_path, monkeypatch, scope, external_input):
    from finetune import train_prepare_run as preparation
    root, media, _, _ = _versioned_data_fixture(tmp_path)
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'model.safetensors').write_bytes(b'base')
    external = tmp_path / 'external-weights'
    external.mkdir()
    weights = external / 'adapter_model.safetensors'
    weights.write_bytes(b'original')
    value = [str(external)] if external_input == 'adapter_name_or_path' else str(external)
    config = {'model_name_or_path': str(base), external_input: value}
    configs = {'full': config} if scope == 'full' else {f'fold{i}': config for i in range(3)}
    with monkeypatch.context() as old_gate:
        old_gate.setattr(preparation, '_reject_unfrozen_training_inputs', lambda config: None)
        preparation.prepare_versioned_run(root=root, train_version='train-v4.1-r1',
            data_version='data-v4.1-r2', prompt_version='prompt-v4.1-r1', media_root=media,
            fold_configs=configs, scope=scope, git_commit='synthetic', environment={'python': 'fixture'})
    weights.write_bytes(b'changed after freeze')
    with pytest.raises(ValueError, match=external_input):
        preparation.verify_versioned_run(root=root, train_version='train-v4.1-r1', for_execution=False)
    with pytest.raises(ValueError, match=external_input):
        preparation.execute_versioned_run(root=root, train_version='train-v4.1-r1')
    assert not (root / 'workspace/mlflow').exists()


def test_old_completed_run_with_unfrozen_adapter_cannot_register_model(tmp_path, monkeypatch):
    from finetune import train_prepare_run as preparation
    from versioning.registry import PromotionGateRejected, RegistryModelNotFound, get_model
    external = tmp_path / 'external-weights'
    external.mkdir()
    (external / 'adapter_model.safetensors').write_bytes(b'old adapter')
    with monkeypatch.context() as old_gate:
        old_gate.setattr(preparation, '_reject_unfrozen_training_inputs', lambda config: None)
        root, _ = prepare_full(tmp_path, adapter_name_or_path=[str(external)])
        old_gate.setattr('finetune.train_with_contract.run_training', fake_tuner)
        completed = execute_versioned_run(root=root, train_version='train-v4.1-r1')
    assert completed.workflow_state == 'completed'
    store = open_registry_store(root / 'workspace/mlflow', data_root=root / 'data')
    with pytest.raises(PromotionGateRejected, match='adapter_name_or_path'):
        register_model(store, 'model-v4.1-r1', train_id='train-v4.1-r1', source_scope='full',
            artifacts={'full': {'adapter': 'artifacts/full/adapter'}},
            deploy_target='artifacts/full/adapter')
    with pytest.raises(RegistryModelNotFound):
        get_model(store, 'model-v4.1-r1')


def fake_tuner(config):
    output = Path(config['output_dir'])
    output.mkdir(parents=True)
    (output / 'train_results.json').write_text(json.dumps({'train_loss': 0.25}))
    (output / 'adapter_config.json').write_text('{}')
    (output / 'adapter_model.safetensors').write_bytes(b'synthetic full adapter')


def full_model(tmp_path, monkeypatch):
    root, path = prepare_full(tmp_path)
    monkeypatch.setattr('finetune.train_with_contract.run_training', fake_tuner)
    execute_versioned_run(root=root, train_version='train-v4.1-r1')
    store = open_registry_store(root / 'workspace/mlflow', data_root=root / 'data')
    model = register_model(store, 'model-v4.1-r1', train_id='train-v4.1-r1',
        source_scope='full', artifacts={'full': {'adapter': 'artifacts/full/adapter'}},
        deploy_target='artifacts/full/adapter')
    return root, store, model


def test_full_freezes_unique_development_members_and_executes_once(tmp_path, monkeypatch):
    root, path = prepare_full(tmp_path)
    training = verify_versioned_run(root=root, train_version='train-v4.1-r1')
    assert training['scope'] == 'full' and training['folds'] == {}
    rows = json.loads((path / 'datasets/train/full.json').read_bytes())
    assert len(rows) == len({row['videos'][0] for row in rows}) == 3
    assert training['full']['eval_dataset'] is None
    assert training['full']['dataset'] == 'tensile_v4_1_full_train'
    calls = []
    def tuner(config):
        calls.append(config)
        fake_tuner(config)
    monkeypatch.setattr('finetune.train_with_contract.run_training', tuner)
    result = execute_versioned_run(root=root, train_version='train-v4.1-r1')
    assert len(calls) == 1
    assert result.scope == 'full' and not result.folds
    assert result.metrics == {'train_loss': 0.25}
    manifest = yaml.safe_load((root / 'records/training/train-v4.1-r1/manifest.yaml').read_text())
    assert manifest['scope'] == 'full' and manifest['folds'] == []
    with pytest.raises(ValueError):
        execute_versioned_run(root=root, train_version='train-v4.1-r1')
    assert len(calls) == 1


@pytest.mark.parametrize('config', [{'eval_dataset': 'holdout'}, {'val_size': 0.1},
    {'do_eval': True}, {'eval_strategy': 'steps'}, {'max_samples': 1}, {'load_best_model_at_end': True}])
def test_full_rejects_validation_or_subset_before_freezing(tmp_path, config):
    with pytest.raises(ValueError, match='full training forbids'):
        prepare_full(tmp_path, **config)
    assert not (tmp_path / 'store/workspace/runs').exists()


def test_full_model_registration_checks_actual_scope_and_weight_evidence(tmp_path, monkeypatch):
    root, store, model = full_model(tmp_path, monkeypatch)
    assert model.source_scope == 'full'
    with pytest.raises(ValueError, match='scope'):
        register_model(store, 'model-v4.1-r2', train_id='train-v4.1-r1',
            source_scope='single_fold', artifacts={'fold0': {'adapter': 'artifacts/fold0/adapter'}},
            deploy_target='artifacts/fold0/adapter')
    from versioning.registry import validate_model_for_evaluation, _run_artifact_root
    validate_model_for_evaluation(store, model.model_id, model.version)
    artifact = _run_artifact_root(store, model.run_id) / 'full/adapter/adapter_model.safetensors'
    artifact.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='evidence'):
        validate_model_for_evaluation(store, model.model_id, model.version)


def test_full_failure_never_completes_or_creates_children(tmp_path, monkeypatch):
    root, path = prepare_full(tmp_path)
    def fail(config):
        raise RuntimeError('synthetic tuner failure')
    monkeypatch.setattr('finetune.train_with_contract.run_training', fail)
    with pytest.raises(RuntimeError, match='tuner failure'):
        execute_versioned_run(root=root, train_version='train-v4.1-r1')
    record = get_train_run(open_train_store(root / 'workspace/mlflow'), 'train-v4.1-r1')
    assert record.workflow_state == 'failed' and record.folds == {}
    with pytest.raises(ValueError, match='full training'):
        create_fold_run(open_train_store(root / 'workspace/mlflow'), 'train-v4.1-r1', 0)


@pytest.mark.parametrize('tampered', [False, True])
def test_full_completion_retry_only_accepts_complete_evidence(tmp_path, monkeypatch, tampered):
    from mlflow.tracking import MlflowClient
    from versioning.mlflow_train import transition_train_state
    root, store, model = full_model(tmp_path, monkeypatch)
    client = MlflowClient(tracking_uri=store.tracking_uri)
    client.update_run(model.run_id, status='RUNNING')
    if tampered:
        from versioning.registry import _run_artifact_root
        (_run_artifact_root(store, model.run_id) / 'full/adapter/adapter_model.safetensors').write_bytes(b'drift')
        with pytest.raises(ValueError, match='evidence'):
            transition_train_state(open_train_store(store.root), 'train-v4.1-r1', 'completed')
        assert client.get_run(model.run_id).info.status == 'RUNNING'
    else:
        result = transition_train_state(open_train_store(store.root), 'train-v4.1-r1', 'completed')
        assert result.run_status == 'FINISHED'


def test_old_three_fold_export_remains_byte_identical(tmp_path, monkeypatch):
    from tests.test_train_with_contract import _prepare_versioned_fixture
    from finetune.train_prepare_run import export_versioned_run
    root, _, _, _ = _prepare_versioned_fixture(tmp_path)
    monkeypatch.setattr('finetune.train_with_contract.run_training', fake_tuner)
    execute_versioned_run(root=root, train_version='train-v4.1-r1')
    path = root / 'records/training/train-v4.1-r1/manifest.yaml'
    before = path.read_bytes()
    assert 'scope' not in yaml.safe_load(before)
    assert export_versioned_run(root=root, train_version='train-v4.1-r1').read_bytes() == before
