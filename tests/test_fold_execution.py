"""Synthetic trainer integration: no model training or test data consumption."""
import json
from pathlib import Path

import pytest

from finetune.train_prepare_run import execute_versioned_run
from tests.test_train_with_contract import _prepare_versioned_fixture
from versioning.mlflow_train import get_train_run, open_train_store


@pytest.fixture
def staged(tmp_path, monkeypatch):
    root, _, _, _ = _prepare_versioned_fixture(tmp_path)
    calls = []
    def tuner(config):
        calls.append(config['seed'] - 3411)
        output = Path(config['output_dir'])
        output.mkdir(parents=True)
        (output / 'adapter_config.json').write_text('{}')
        (output / 'adapter_model.safetensors').write_bytes(b'synthetic adapter')
        (output / 'train_results.json').write_text(json.dumps({'train_loss': 0.25}))
    monkeypatch.setattr('finetune.train_with_contract.run_training', tuner)
    return root, calls


def run(root, fold=None):
    return execute_versioned_run(root=root, train_version='train-v4.1-r1', fold=fold)


def test_three_invocations_share_parent_and_complete_only_after_all_folds(staged):
    root, calls = staged
    first = run(root, 2)
    assert first.workflow_state == 'partial' and set(first.folds) == {2}
    assert not (root / 'records/training/train-v4.1-r1/manifest.yaml').exists()
    assert run(root, 2).run_id == first.run_id
    assert calls == [2]
    second = run(root, 0)
    assert second.workflow_state == 'partial' and second.run_id == first.run_id
    last = run(root, 1)
    assert last.workflow_state == 'completed' and last.run_id == first.run_id
    assert calls == [2, 0, 1]
    assert run(root, 0).workflow_state == 'completed'
    assert calls == [2, 0, 1]
    assert (root / 'records/training/train-v4.1-r1/manifest.yaml').is_file()


def test_group_resumes_only_missing_folds(staged):
    root, calls = staged
    run(root, 1)
    assert run(root).workflow_state == 'completed'
    assert calls == [1, 0, 2]


@pytest.mark.parametrize('damage', ['local', 'uploaded', 'receipt', 'child', 'residual'])
def test_reuse_rejects_corruption_before_any_new_trainer_call(staged, damage):
    from mlflow.tracking import MlflowClient
    from versioning.registry import _run_artifact_root
    root, calls = staged
    parent = run(root, 0)
    store = open_train_store(root / 'workspace/mlflow')
    client = MlflowClient(tracking_uri=store.tracking_uri)
    remote = _run_artifact_root(store, parent.run_id)
    local = root / 'workspace/runs/train-v4.1-r1'
    if damage == 'local':
        (local / 'fold0/adapter/adapter_model.safetensors').write_bytes(b'changed')
    elif damage == 'uploaded':
        (remote / 'fold0/adapter/adapter_model.safetensors').write_bytes(b'changed')
    elif damage == 'receipt':
        (remote / 'fold0/execution-evidence.json').write_text('{}')
    elif damage == 'child':
        client.log_metric(parent.folds[0].run_id, 'train_loss', 99)
    else:
        (local / 'fold1/adapter').mkdir(parents=True)
    with pytest.raises(ValueError):
        run(root, 1)
    assert calls == [0]
    assert get_train_run(store, 'train-v4.1-r1').workflow_state == 'partial'


def test_failure_cannot_be_automatically_retried(staged, monkeypatch):
    root, calls = staged
    run(root, 0)
    def fail(config):
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr('finetune.train_with_contract.run_training', fail)
    with pytest.raises(RuntimeError, match='synthetic failure'):
        run(root, 1)
    with pytest.raises(ValueError, match='explicit recovery'):
        run(root, 2)
    assert calls == [0]


def test_same_train_lock_rejects_concurrent_execution(staged):
    import fcntl
    root, calls = staged
    with (root / 'workspace/runs/train-v4.1-r1/.execution.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='already executing'):
            run(root, 1)
    assert calls == []


@pytest.mark.parametrize('fold', [-1, 3, True, '0'])
def test_invalid_selection_does_not_start_training(staged, fold):
    root, calls = staged
    with pytest.raises(ValueError, match='fold must'):
        run(root, fold)
    assert calls == []


def test_partial_cannot_export_or_promote(staged):
    from finetune.train_prepare_run import export_versioned_run
    from versioning.mlflow_train import IncompleteTrainRecord, validate_train_for_promotion
    root, calls = staged
    run(root, 0)
    with pytest.raises(IncompleteTrainRecord):
        export_versioned_run(root=root, train_version='train-v4.1-r1')
    with pytest.raises(IncompleteTrainRecord):
        validate_train_for_promotion(open_train_store(root / 'workspace/mlflow'), 'train-v4.1-r1')
    assert calls == [0]


def test_both_output_copies_cannot_be_changed_to_bypass_receipt(staged):
    from versioning.registry import _run_artifact_root
    root, calls = staged
    parent = run(root, 0)
    uploaded = _run_artifact_root(open_train_store(root / 'workspace/mlflow'), parent.run_id)
    for base in (uploaded, root / 'workspace/runs/train-v4.1-r1'):
        (base / 'fold0/adapter/adapter_model.safetensors').write_bytes(b'same changed bytes')
    with pytest.raises(ValueError, match='evidence differs'):
        run(root, 1)
    assert calls == [0]


@pytest.mark.parametrize('residual', ['receipt', 'uploaded_receipt', 'duplicate_child'])
def test_residual_evidence_and_duplicate_children_reject_before_trainer(staged, residual):
    from mlflow.tracking import MlflowClient
    root, calls = staged
    parent = run(root, 0)
    if residual in ('receipt', 'uploaded_receipt'):
        from versioning.registry import _run_artifact_root
        path = (root / 'workspace/runs/train-v4.1-r1/fold1' if residual == 'receipt'
                else _run_artifact_root(open_train_store(root / 'workspace/mlflow'), parent.run_id) / 'fold1')
        path.mkdir()
        (path / 'execution-evidence.json').write_text('{}')
    else:
        store = open_train_store(root / 'workspace/mlflow')
        client = MlflowClient(tracking_uri=store.tracking_uri)
        duplicate = client.create_run(store.experiment_id,
            tags={'mlflow.parentRunId': parent.run_id, 'fold': 'fold0'})
        client.set_terminated(duplicate.info.run_id, status='FAILED')
    with pytest.raises(ValueError):
        run(root, 1)
    assert calls == [0]



def test_partial_with_premature_summary_rejects_before_trainer(staged):
    from mlflow.tracking import MlflowClient
    root, calls = staged
    parent = run(root, 0)
    store = open_train_store(root / 'workspace/mlflow')
    MlflowClient(tracking_uri=store.tracking_uri).log_metric(parent.run_id, 'train_loss_mean', 0.25)
    with pytest.raises(ValueError, match='partial training requires explicit recovery'):
        run(root, 1)
    assert calls == [0]
