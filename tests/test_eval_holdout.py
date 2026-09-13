"""Full holdout end-to-end on synthetic bytes, with truth-read tripwires."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tests.test_full_training import full_model
from tests.versioning.test_cli_holdout import _release
from finetune import eval_run as ev
from finetune.eval_holdout import score_holdout_evaluation
from versioning.cli import main
from versioning.mlflow_eval import get_eval_run, open_eval_store

LABELS = {'clip_state': '未断裂', 'fracture_mechanism': None, 'fracture_site': None, 'special_case': None}


def prepare_holdout(tmp_path, monkeypatch, *, prepare=True):
    root, registry, model = full_model(tmp_path, monkeypatch)
    _release(root, 'data-v4.1-r3', 'holdout')
    release = root / 'data/releases/data-v4.1-r3'
    for name in ('media', 'evaluation_inputs', 'sealed_ground_truth'):
        (release / name).chmod(0o700)
    (release / 'media/video_9999_clip.mp4').write_bytes(b'synthetic independent media')
    manifest = {'schema_version': 'tensile-holdout-media/v1', 'data_version': 'data-v4.1-r3',
        'split': 'holdout', 'development_data_version': 'data-v4.1-r2',
        'development_source_isolation_verified': True, 'test_split_binding_verified': True,
        'samples': [{'candidate_id': 'video_9999_clip', 'source_video': 'video_9999', 'video_path': 'video_9999_clip.mp4'}]}
    (release / 'evaluation_inputs/manifest.json').write_text(json.dumps(manifest))
    truth = release / 'sealed_ground_truth/labels.json'
    truth.write_text(json.dumps({'schema_version': 'tensile-holdout-truth/v1', 'data_version': 'data-v4.1-r3',
        'split': 'holdout', 'labels': {'video_9999_clip': LABELS}}))
    truth.chmod(0o400)
    config = {'scope': 'full', 'split': 'holdout', 'artifact_kind': 'adapter', 'scorer': 'strict-v4.1',
        'sample_selection': 'all', 'quantization_bit': None, 'generation': ev.FORMAL_GENERATION,
        'thresholds': {'joint_correct_rate': 1.0}, 'aggregation': 'pooled'}
    pre = {'eval_version': 'eval-v4.1-r1', 'model_version': model.model_id, 'data_version': 'data-v4.1-r3',
        'split': 'holdout', 'rules': {k: v for k, v in config.items() if k != 'thresholds'},
        'thresholds': config['thresholds'], 'one_time': True, 'tuning_use': 'forbidden', 'recovery': {'same_identity_only': True}}
    source = tmp_path / 'pre-registration.yaml'; source.write_text(yaml.safe_dump(pre))
    assert main(['data', 'claim', '--root', str(root), '--version', 'data-v4.1-r3',
        '--eval-version', 'eval-v4.1-r1', '--model-version', model.model_id, '--split', 'holdout',
        '--pre-registration', str(source), '--executor', 'synthetic']) == 0
    frozen = root / 'evaluations/staging/eval-v4.1-r1/authorization/pre_registration.yaml'
    kwargs = dict(root=root, eval_version='eval-v4.1-r1', model_version=model.model_id,
        model_version_number=model.version, data_version='data-v4.1-r3', config=config,
        git_commit='synthetic', media_root=release / 'media', pre_registration=frozen, executor='synthetic')
    if prepare:
        ev.prepare_versioned_evaluation(**kwargs)
    monkeypatch.setattr(ev, 'load_model', lambda *a, **k: (object(), object()))
    monkeypatch.setattr(ev, 'run_model_on_video_detailed', lambda *a, **k: SimpleNamespace(raw_output=json.dumps(LABELS)))
    return root, registry, truth, kwargs


def forbid_truth(monkeypatch, truth):
    old_bytes, old_text = Path.read_bytes, Path.read_text
    def read_bytes(path):
        if path.resolve() == truth.resolve():
            pytest.fail('truth was read outside authorized score')
        return old_bytes(path)
    def read_text(path, *a, **k):
        if path.resolve() == truth.resolve():
            pytest.fail('truth was read outside authorized score')
        return old_text(path, *a, **k)
    monkeypatch.setattr(Path, 'read_bytes', read_bytes)
    monkeypatch.setattr(Path, 'read_text', read_text)


def test_media_inference_then_score_and_aggregate_only_export(tmp_path, monkeypatch):
    root, registry, truth, kwargs = prepare_holdout(tmp_path, monkeypatch, prepare=False)
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        ev.prepare_versioned_evaluation(**kwargs)
        ev.verify_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
        result = ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
        assert result['phase'] == 'inferred' and result['truth_accessed'] is False
    record = get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1')
    assert record.workflow_state == 'running' and not record.folds
    assert not (truth.parent.parent / 'authorization/consumed.yaml').exists()
    manifest = score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
    record = get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1')
    assert record.workflow_state == 'completed' and record.outcome == 'passed' and not record.folds
    from versioning.registry import _run_artifact_root
    public = _run_artifact_root(registry, record.run_id)
    for path in public.rglob('*'):
        if path.is_file():
            contents = path.read_text()
            assert 'raw_output' not in contents and '"target"' not in contents
            assert 'scored-records' not in contents and 'sealed_ground_truth' not in contents
    assert set(json.loads(manifest.read_bytes())['artifacts']) == {'summary.json', 'execution.json'}
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        assert ev.export_versioned_evaluation(root=root, eval_version='eval-v4.1-r1') == manifest
        ev.validate_evaluation_execution_artifacts(store=registry, record=record)
        # Recovery of an already scored/consumed Run does not reopen truth.
        assert score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic') == manifest
        with pytest.raises(ValueError, match='consumed'):
            ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')


@pytest.mark.parametrize('change', ['thresholds', 'identity', 'source', 'label'])
def test_prepare_refuses_inconsistent_holdout_before_truth_access(tmp_path, monkeypatch, change):
    root, _, truth, kwargs = prepare_holdout(tmp_path, monkeypatch, prepare=False)
    if change == 'thresholds':
        kwargs['config'] = {**kwargs['config'], 'thresholds': {'joint_correct_rate': 0.5}}
    elif change == 'identity':
        kwargs['executor'] = 'somebody-else'
    else:
        path = truth.parent.parent / 'evaluation_inputs/manifest.json'
        value = json.loads(path.read_bytes())
        if change == 'source':
            value['samples'][0]['source_video'] = 'video_0000'
        else:
            value['samples'][0]['target'] = LABELS
        path.write_text(json.dumps(value))
    forbid_truth(monkeypatch, truth)
    with pytest.raises(ValueError):
        ev.prepare_versioned_evaluation(**kwargs)
    assert not (root / 'workspace/evaluations/eval-v4.1-r1/input').exists()


def test_wrong_scoring_executor_or_drift_does_not_read_truth(tmp_path, monkeypatch):
    root, registry, truth, _ = prepare_holdout(tmp_path, monkeypatch)
    ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    forbid_truth(monkeypatch, truth)
    with pytest.raises(ValueError, match='executor'):
        score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='wrong')
    from finetune.eval_run import _formal_workspace
    predictions = _formal_workspace(root, 'eval-v4.1-r1') / 'restricted/predictions.json'
    predictions.chmod(0o600); predictions.write_text('[]'); predictions.chmod(0o400)
    with pytest.raises(ValueError, match='drifted'):
        score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')


def test_scoring_failure_is_recorded_and_same_run_can_resume_without_reinference(tmp_path, monkeypatch):
    root, registry, truth, _ = prepare_holdout(tmp_path, monkeypatch)
    ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    original = ev.score_v4_1_prediction
    monkeypatch.setattr(ev, 'score_v4_1_prediction', lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic scoring interruption')))
    with pytest.raises(RuntimeError, match='scoring interruption'):
        score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
    assert get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1').workflow_state == 'failed'
    assert not (truth.parent.parent / 'authorization/consumed.yaml').exists()
    monkeypatch.setattr(ev, 'score_v4_1_prediction', original)
    monkeypatch.setattr(ev, 'load_model', lambda *a, **k: pytest.fail('score must never reload the model'))
    score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
    assert get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1').outcome == 'passed'


def test_consumed_completion_interrupt_recovers_without_truth_or_inference(tmp_path, monkeypatch):
    root, registry, truth, _ = prepare_holdout(tmp_path, monkeypatch)
    ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    from mlflow.tracking import MlflowClient
    terminate = MlflowClient.set_terminated
    def fail(self, run_id, *a, **k):
        raise OSError('synthetic completion interruption')
    monkeypatch.setattr(MlflowClient, 'set_terminated', fail)
    with pytest.raises(OSError, match='completion interruption'):
        score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
    assert (truth.parent.parent / 'authorization/consumed.yaml').exists()
    monkeypatch.setattr(MlflowClient, 'set_terminated', terminate)
    forbid_truth(monkeypatch, truth)
    monkeypatch.setattr(ev, 'load_model', lambda *a, **k: pytest.fail('completed evaluation must not rerun inference'))
    score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
    assert get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1').run_status == 'FINISHED'


def test_cli_full_holdout_pipeline_and_quality_failure(tmp_path, monkeypatch, capsys):
    root, registry, truth, kwargs = prepare_holdout(tmp_path, monkeypatch, prepare=False)
    config = tmp_path / 'evaluation.yaml'; config.write_text(yaml.safe_dump(kwargs['config']))
    args = ['--root', str(root)]
    assert main(['eval', 'prepare', 'eval-v4.1-r1', *args, '--model-version', 'model-v4.1-r1',
        '--model-version-number', '1', '--data-version', 'data-v4.1-r3', '--config', str(config),
        '--git-commit', 'synthetic', '--media-root', str(kwargs['media_root']), '--executor', 'synthetic',
        '--pre-registration', str(kwargs['pre_registration'])]) == 0
    monkeypatch.setattr(ev, 'run_model_on_video_detailed', lambda *a, **k: SimpleNamespace(raw_output='invalid prediction'))
    assert main(['eval', 'run', 'eval-v4.1-r1', *args]) == 0
    assert main(['eval', 'score', 'eval-v4.1-r1', *args]) == 2
    assert main(['eval', 'score', 'eval-v4.1-r1', *args, '--executor', 'synthetic']) == 0
    record = get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1')
    assert record.workflow_state == 'completed' and record.outcome == 'failed'
    assert (truth.parent.parent / 'authorization/consumed.yaml').exists()
    assert 'invalid prediction' not in capsys.readouterr().out


@pytest.mark.parametrize('relative', ['authorization/claim.yaml', 'authorization/consumed.yaml', 'release.yaml'])
def test_prepare_rejects_metadata_links_before_opening_truth(tmp_path, monkeypatch, relative):
    root, _, truth, kwargs = prepare_holdout(tmp_path, monkeypatch, prepare=False)
    target = truth.parent.parent / relative
    target.parent.chmod(0o700)
    if target.exists():
        target.unlink()
    target.symlink_to(truth)
    forbid_truth(monkeypatch, truth)
    with pytest.raises(ValueError, match='ordinary'):
        ev.prepare_versioned_evaluation(**kwargs)
    assert not (root / 'workspace/evaluations/eval-v4.1-r1/input').exists()


def test_forged_scoring_receipt_cannot_skip_actual_scoring(tmp_path, monkeypatch):
    from finetune.eval_holdout import _digest
    root, registry, truth, _ = prepare_holdout(tmp_path, monkeypatch)
    monkeypatch.setattr(ev, 'run_model_on_video_detailed', lambda *a, **k: SimpleNamespace(raw_output='invalid'))
    ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    value = ev.verify_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    private = ev._formal_workspace(root, 'eval-v4.1-r1') / 'restricted'
    inference = json.loads((private / 'inference.json').read_bytes())
    receipt = {'schema_version': 'tensile-holdout-score/v1', 'run_id': inference['run_id'],
        'input_sha256': _digest(value), 'pre_registration_sha256': value['authorization']['pre_registration_sha256'],
        'inference_sha256': ev._sha256(private / 'inference.json'), 'weights': inference['weights'],
        'summary': {'input_sha256': _digest(value), 'sample_count': 1, 'outcome': 'passed',
            'metrics': {key: 1.0 for key in ev.FORMAL_METRICS}}}
    path = private / 'scoring.json'; path.write_bytes(ev._formal_bytes(receipt)); path.chmod(0o400)
    forbid_truth(monkeypatch, truth)
    with pytest.raises(ValueError, match='ordinary'):
        score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
    record = get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1')
    assert record.workflow_state == 'failed' and record.outcome is None
    assert not (truth.parent.parent / 'authorization/consumed.yaml').exists()
    from versioning.registry import finalize_model_evaluation
    with pytest.raises(ValueError):
        finalize_model_evaluation(registry, 'model-v4.1-r1', eval_id='eval-v4.1-r1')


@pytest.mark.parametrize('tamper', [False, True])
def test_private_scoring_commit_interruption_revalidates_actual_rows(tmp_path, monkeypatch, tamper):
    from mlflow.tracking import MlflowClient
    root, registry, truth, _ = prepare_holdout(tmp_path, monkeypatch)
    ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    original = MlflowClient.log_param
    def fail(self, run_id, key, value, *a, **k):
        if key == 'sha256_holdout_scoring':
            raise OSError('synthetic scoring commitment interruption')
        return original(self, run_id, key, value, *a, **k)
    monkeypatch.setattr(MlflowClient, 'log_param', fail)
    with pytest.raises(OSError, match='commitment interruption'):
        score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
    monkeypatch.setattr(MlflowClient, 'log_param', original)
    if tamper:
        path = ev._formal_workspace(root, 'eval-v4.1-r1') / 'restricted/scored-records.json'
        rows = json.loads(path.read_bytes()); rows[0]['scores'] = {}
        path.chmod(0o600); path.write_text(json.dumps(rows)); path.chmod(0o400)
    if tamper:
        with pytest.raises(ValueError, match='per-sample'):
            score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
        assert not (truth.parent.parent / 'authorization/consumed.yaml').exists()
    else:
        score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
        assert get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1').outcome == 'passed'


def test_forged_complete_private_stage_cannot_replace_authorized_truth(tmp_path, monkeypatch):
    from finetune.eval_holdout import _digest, _save
    root, registry, truth, _ = prepare_holdout(tmp_path, monkeypatch)
    actual = json.loads(truth.read_bytes())
    actual['labels']['video_9999_clip'] = {**LABELS, 'clip_state': '发生断裂'}
    truth.chmod(0o600); truth.write_text(json.dumps(actual)); truth.chmod(0o400)
    ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    value = ev.verify_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')
    private = ev._formal_workspace(root, 'eval-v4.1-r1') / 'restricted'
    inference = json.loads((private / 'inference.json').read_bytes())
    prediction = json.loads((private / 'predictions.json').read_bytes())[0]
    record = {**value['samples'][0], **prediction, 'target': LABELS, 'prediction': LABELS,
        'strict_valid': True, 'parse_error': None, 'runtime_error': None,
        'scores': ev.score_v4_1_prediction(LABELS, LABELS)}
    fake_truth = {**actual, 'labels': {'video_9999_clip': LABELS}}
    _save(private / 'truth-access.json', {'run_id': inference['run_id'], 'input_sha256': _digest(value),
        'executor': 'synthetic', 'pre_registration_sha256': value['authorization']['pre_registration_sha256']}, private=True)
    _save(private / 'truth-snapshot.json', fake_truth, private=True)
    _save(private / 'scored-records.json', [record], private=True)
    metrics = ev.summarize_records([record])['metrics']
    _save(private / 'scoring.json', {'schema_version': 'tensile-holdout-score/v1', 'run_id': inference['run_id'],
        'input_sha256': _digest(value), 'pre_registration_sha256': value['authorization']['pre_registration_sha256'],
        'inference_sha256': ev._sha256(private / 'inference.json'), 'weights': inference['weights'],
        'summary': {'input_sha256': _digest(value), 'sample_count': 1, 'outcome': 'passed',
            'metrics': {key: metrics[key] for key in ev.FORMAL_METRICS}}}, private=True)
    with pytest.raises(ValueError, match='authorized source'):
        score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='synthetic')
    assert not (truth.parent.parent / 'authorization/consumed.yaml').exists()
    assert get_eval_run(open_eval_store(registry.root), 'eval-v4.1-r1').outcome is None
