"""Model-source provenance tests use synthetic bytes, without loading any model."""
import json
from pathlib import Path

import pytest
from mlflow.tracking import MlflowClient

from versioning.registry import (
    PromotionGateRejected, IllegalRegistryRecord, get_model, open_registry_store,
    register_base_model, register_completed_fold_model, validate_model_for_evaluation,
    approve_model_for_production, finalize_model_evaluation, set_alias, materialize_model,
    _run_artifact_root,
)


def base_files(path):
    path.mkdir(exist_ok=True)
    for name in ('config.json', 'tokenizer_config.json', 'tokenizer.json', 'preprocessor_config.json'):
        (path / name).write_text('{}')
    (path / 'model.safetensors').write_bytes(b'synthetic base weights')
    return path


@pytest.fixture
def base_model(tmp_path):
    path = base_files(tmp_path / 'base')
    (path / 'source-provenance.json').write_text(json.dumps({
        'schema': 'tensile-base-provenance/v1', 'upstream_source': 'org/fixed-model',
        'upstream_revision': 'fixed-revision-123', 'verified_by': 'synthetic fixture'}))
    store = open_registry_store(tmp_path / 'mlflow')
    record = register_base_model(store, 'model-v4.1-r1', model_path=path,
        upstream_source='org/fixed-model', upstream_revision='fixed-revision-123', git_commit='fixture')
    return store, record, path


def test_base_has_no_fabricated_training_and_materializes(base_model, tmp_path):
    store, record, path = base_model
    assert record.train_id is record.data_version is record.prompt_version is None
    assert record.source_kind == 'base' and record.deploy_target is None
    assert validate_model_for_evaluation(store, record.model_id, record.version) == record
    target = materialize_model(store, record.model_id, tmp_path / 'models')
    assert (target / 'artifacts/base/model/model.safetensors').read_bytes() == (path / 'model.safetensors').read_bytes()
    assert not MlflowClient(tracking_uri=store.tracking_uri).search_runs([store.train_experiment_id], "tags.train_id = 'train-v4.1-r1'")


@pytest.mark.parametrize('damage', ['source', 'snapshot', 'tag', 'invalid_source_run'])
def test_base_drift_rejected(base_model, damage):
    store, record, path = base_model
    client = MlflowClient(tracking_uri=store.tracking_uri)
    if damage == 'source':
        (path / 'tokenizer.json').write_text('{"changed":true}')
    elif damage == 'snapshot':
        (_run_artifact_root(store, record.run_id) / 'base/model/model.safetensors').write_bytes(b'changed')
    elif damage == 'tag':
        client.set_model_version_tag('mVllm2', str(record.version), 'train_id', 'train-v4.1-r1')
    else:
        client.set_tag(record.run_id, 'record_validity', 'invalid')
    with pytest.raises((PromotionGateRejected, IllegalRegistryRecord)):
        validate_model_for_evaluation(store, record.model_id, record.version)


@pytest.mark.parametrize('missing', ['config.json', 'tokenizer.json', 'preprocessor_config.json', 'model.safetensors'])
def test_base_rejects_incomplete_source(tmp_path, missing):
    path = base_files(tmp_path / 'base')
    (path / missing).unlink()
    store = open_registry_store(tmp_path / 'mlflow')
    with pytest.raises(ValueError):
        register_base_model(store, 'model-v4.1-r1', model_path=path,
            upstream_source='org/base', upstream_revision='revision-123', git_commit='fixture')
    assert not MlflowClient(tracking_uri=store.tracking_uri).search_model_versions("name='mVllm2'")


@pytest.mark.parametrize('damage', ['missing', 'config_source', 'config_revision', 'provenance_revision', 'mutable_revision', 'missing_shard'])
def test_base_requires_locally_consistent_provenance(tmp_path, damage):
    path = base_files(tmp_path / 'base')
    if damage != 'missing':
        (path / 'source-provenance.json').write_text(json.dumps({
            'schema': 'tensile-base-provenance/v1', 'upstream_source': 'org/base',
            'upstream_revision': 'wrong' if damage == 'provenance_revision' else 'revision-123',
            'verified_by': 'synthetic fixture'}))
    if damage in {'config_source', 'config_revision'}:
        (path / 'config.json').write_text(json.dumps({
            '_name_or_path': 'other/base' if damage == 'config_source' else 'org/base',
            '_commit_hash': 'other-revision' if damage == 'config_revision' else 'revision-123'}))
    if damage == 'missing_shard':
        (path / 'model.safetensors.index.json').write_text('{"weight_map":{"a":"missing.safetensors"}}')
    store = open_registry_store(tmp_path / 'mlflow')
    with pytest.raises(ValueError):
        register_base_model(store, 'model-v4.1-r1', model_path=path, upstream_source='org/base',
            upstream_revision='main' if damage == 'mutable_revision' else 'revision-123', git_commit='fixture')


@pytest.mark.parametrize('argv', [
    ['--source-kind', 'base', '--source-scope', 'base', '--train-version', 'train-v4.1-r1'],
    ['--source-kind', 'trained', '--source-scope', 'base'],
    ['--source-kind', 'trained', '--source-scope', 'diagnostic_fold', '--train-version', 'train-v4.1-r1'],
    ['--source-kind', 'trained', '--source-scope', 'diagnostic_fold', '--train-version', 'train-v4.1-r1', '--fold', '0', '--deploy-target', 'artifacts/fold0/adapter'],
])
def test_source_cli_rejects_ambiguous_branches_before_store_creation(tmp_path, argv):
    from versioning.cli import main
    assert main(['model', 'register', 'model-v4.1-r1', '--root', str(tmp_path), *argv]) == 2
    assert not (tmp_path / 'workspace/mlflow').exists()


@pytest.fixture
def diagnostic_model(tmp_path, monkeypatch):
    from tests.test_train_with_contract import _versioned_data_fixture
    from finetune.train_prepare_run import prepare_versioned_run, execute_versioned_run
    root, media, _, _ = _versioned_data_fixture(tmp_path)
    path = base_files(tmp_path / 'base')
    configs = {f'fold{i}': {'seed': 3411 + i, 'model_name_or_path': str(path),
               'learning_rate': 0.0001, 'do_train': True} for i in range(3)}
    prepare_versioned_run(root=root, train_version='train-v4.1-r1', data_version='data-v4.1-r2',
        prompt_version='prompt-v4.1-r1', media_root=media, fold_configs=configs,
        git_commit='fixture', environment={'python': 'fixture'})
    def tuner(config):
        output = Path(config['output_dir'])
        output.mkdir(parents=True)
        (output / 'adapter_config.json').write_text('{}')
        (output / 'adapter_model.safetensors').write_bytes(b'synthetic adapter')
        (output / 'train_results.json').write_text('{"train_loss":0.25}')
        (output / 'trainer_state.json').write_text('{"global_step":42}')
    monkeypatch.setattr('finetune.train_with_contract.run_training', tuner)
    parent = execute_versioned_run(root=root, train_version='train-v4.1-r1', fold=2)
    store = open_registry_store(root / 'workspace/mlflow', data_root=root / 'data')
    record = register_completed_fold_model(store, 'model-v4.1-r1', train_id=parent.train_id, fold=2)
    return store, record, parent, root


def test_completed_fold_preserves_partial_parent_and_real_fold(diagnostic_model, tmp_path):
    from versioning.mlflow_train import get_train_run, open_train_store
    store, record, parent, root = diagnostic_model
    actual = get_train_run(open_train_store(store.root), parent.train_id)
    assert actual.workflow_state == 'partial' and actual.run_id == parent.run_id
    assert set(actual.folds) == {2} and record.run_id != parent.run_id
    assert record.source_evidence['checkpoint_step'] == 42
    assert record.source_evidence['fold'] == 2
    assert record.artifacts == {'fold2': {'adapter': 'artifacts/fold2/adapter'}}
    assert validate_model_for_evaluation(store, record.model_id, record.version) == record
    assert (materialize_model(store, record.model_id, tmp_path / 'models') / 'artifacts/fold2/adapter/trainer_state.json').is_file()
    with pytest.raises(ValueError, match='FINISHED'):
        register_completed_fold_model(store, 'model-v4.1-r2', train_id=parent.train_id, fold=1)


def test_other_fold_failure_keeps_finished_snapshot_usable(diagnostic_model):
    from versioning.mlflow_train import open_train_store, transition_train_state, create_fold_run, end_fold_run
    store, record, parent, _ = diagnostic_model
    train_store = open_train_store(store.root)
    transition_train_state(train_store, parent.train_id, 'running')
    create_fold_run(train_store, parent.train_id, 1)
    end_fold_run(train_store, parent.train_id, 1, 'FAILED')
    transition_train_state(train_store, parent.train_id, 'failed', run_status='FAILED')
    assert validate_model_for_evaluation(store, record.model_id, record.version) == record


@pytest.mark.parametrize('damage', ['base', 'input', 'receipt', 'snapshot', 'invalid_parent'])
def test_diagnostic_source_drift_rejected(diagnostic_model, damage):
    from versioning.mlflow_train import open_train_store, mark_train_invalid
    store, record, parent, root = diagnostic_model
    if damage == 'base':
        (Path(parent.base_model) / 'tokenizer.json').write_text('{"changed":true}')
    elif damage == 'input':
        path = _run_artifact_root(store, parent.run_id) / 'input/prompt.yaml'
        path.chmod(0o644)
        path.write_text('changed')
    elif damage == 'receipt':
        (_run_artifact_root(store, parent.run_id) / 'fold2/execution-evidence.json').write_text('{}')
    elif damage == 'snapshot':
        (_run_artifact_root(store, record.run_id) / 'fold2/adapter/adapter_model.safetensors').write_bytes(b'changed')
    else:
        mark_train_invalid(open_train_store(store.root), parent.train_id)
    with pytest.raises(PromotionGateRejected):
        validate_model_for_evaluation(store, record.model_id, record.version)
    assert get_model(store, record.model_id).model_id == record.model_id


@pytest.mark.parametrize('fixture', ['base_model', 'diagnostic_model'])
def test_development_sources_never_finalize_or_route(request, fixture):
    store, record, *_ = request.getfixturevalue(fixture)
    for call in (lambda: finalize_model_evaluation(store, record.model_id, eval_id='eval-v4.1-r1'),
                 lambda: set_alias(store, record.model_id, 'candidate'),
                 lambda: set_alias(store, record.model_id, 'production'),
                 lambda: approve_model_for_production(store, record.model_id)):
        with pytest.raises(PromotionGateRejected, match='restricted'):
            call()


@pytest.mark.parametrize('fixture', ['base_model', 'diagnostic_model'])
def test_source_backup_restore_preserves_snapshot_and_external_base_dependency(request, fixture, tmp_path):
    from versioning.backup import create_backup, restore_backup
    from versioning.manifest import export_model_manifest
    from versioning.registry import set_offline_backup_scope
    store, record, *rest = request.getfixturevalue(fixture)
    project = rest[-1] if fixture == 'diagnostic_model' else tmp_path / 'project'
    data_root = store.data_root
    data_root.mkdir(exist_ok=True)
    set_offline_backup_scope(store, record.model_id, 'production_bundle' if fixture == 'base_model' else 'adapter')
    export_model_manifest(project / f'records/models/{record.model_id}/manifest.yaml', store=store, model_id=record.model_id)
    materialize_model(store, record.model_id, project / 'models')
    backup = tmp_path / 'backup'
    create_backup(store, data_root=data_root, prompts_root=project, models_root=project / 'models', backup_root=backup)
    restored = tmp_path / 'restored'
    restore_backup(backup, data_root=restored / 'data', prompts_root=restored,
                   models_root=restored / 'models', mlflow_root=restored / 'workspace/mlflow')
    restored_store = open_registry_store(restored / 'workspace/mlflow', data_root=restored / 'data')
    actual = validate_model_for_evaluation(restored_store, record.model_id, record.version)
    assert actual.source_evidence == record.source_evidence
    assert actual.base_model == record.base_model
    assert (_run_artifact_root(restored_store, actual.run_id) / 'model-source.json').is_file()
    base_path = Path(actual.base_model) / 'model.safetensors'
    base_path.write_bytes(b'external source changed')
    with pytest.raises(PromotionGateRejected):
        validate_model_for_evaluation(restored_store, record.model_id, record.version)
