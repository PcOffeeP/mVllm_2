"""Independent evaluation engineering on temporary synthetic stores only."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from finetune import eval_run as ev
from finetune.eval_holdout import (prepare_holdout_review, seal_holdout_review,
    score_holdout_evaluation)
from finetune.eval_review import (PROTOCOL, THRESHOLDS, REVIEW_RUNTIME, MODEL_DIGESTS,
    final_metrics, public_gates, gate_outcome, probe_review_isolation,
    validate_semantic_holdout_config, review_prompt_digest)
from finetune.eval_semantics import FIELDS, ENUMS, FOUR_STATES, rules_digest, content_digest, seal_judgment
from tests.test_eval_holdout import prepare_holdout, forbid_truth, LABELS
from versioning.cli import main
from versioning.mlflow_eval import get_eval_run, open_eval_store

MANUAL = 'Read explicit output fields; no tools, truth, videos or identity.'


class RawCounter:
    def __init__(self, count): self.count = count
    def render(self, model, messages):
        return {'prompt': 'synthetic rendered prompt', 'token_ids': list(range(self.count))}


def policy():
    actor = lambda identity, model: {'id': identity, 'model': model,
        'model_sha256': MODEL_DIGESTS[model], 'prompt_sha256': review_prompt_digest(hashlib.sha256(MANUAL.encode()).hexdigest())}
    return {'participants': [actor('first', 'qwen3.5:9b'), actor('second', 'ornith-1.5:9b')],
        'arbiter': actor('third-context', 'qwen3.5:9b'),
        'manual_sha256': hashlib.sha256(MANUAL.encode()).hexdigest(),
        'rules_sha256': rules_digest(), 'aggregation': 'unanimous-per-field',
        'retry_policy': {'runtime_failure_retries': 1, 'answer_selection': 'forbidden'}}


def runtime_config():
    return {'runtime_variant': {'dtype': 'bfloat16',
        'preprocessing_sha256': hashlib.sha256(Path('pipeline/preprocessing/minicpm_preprocessor.py').read_bytes()).hexdigest(),
        'llamafactory_version': 'synthetic', 'transformers_version': 'synthetic'},
        'device': {'runtime_device': 'cuda:0', 'gpu_count': 1}}


def prepare(tmp_path, monkeypatch, *, blind=False, aggregate_authorization=None, review_tokenizers=None):
    root, registry, truth, kwargs = prepare_holdout(tmp_path, monkeypatch, prepare=False)
    config = {**kwargs['config'], 'scorer': PROTOCOL, 'thresholds': dict(THRESHOLDS),
        'blind_policy': policy(), 'review_runtime': dict(REVIEW_RUNTIME), **runtime_config(),
        'source_groups': {sample: sample for sample in json.loads(truth.read_bytes())['labels']}}
    if review_tokenizers is not None:
        config['review_tokenizers'] = review_tokenizers
    if aggregate_authorization is not None:
        config['aggregate_authorization'] = aggregate_authorization
    # Replace only the throwaway helper's unexecuted strict authorization fixture.
    claim = truth.parent.parent / 'authorization/claim.yaml'
    claim.unlink()
    pre = {'eval_version': 'eval-v4.1-r2', 'model_version': kwargs['model_version'],
        'data_version': kwargs['data_version'], 'split': 'holdout',
        'rules': {k: v for k, v in config.items() if k != 'thresholds'},
        'thresholds': config['thresholds'], 'one_time': True, 'tuning_use': 'forbidden',
        'recovery': {'same_identity_only': True}}
    source = tmp_path / 'semantic-pre.yaml'; source.write_text(yaml.safe_dump(pre))
    assert main(['data', 'claim', '--root', str(root), '--version', kwargs['data_version'],
        '--eval-version', 'eval-v4.1-r2', '--model-version', kwargs['model_version'],
        '--split', 'holdout', '--pre-registration', str(source), '--executor', 'synthetic']) == 0
    kwargs.update(eval_version='eval-v4.1-r2', config=config,
        pre_registration=root / 'evaluations/staging/eval-v4.1-r2/authorization/pre_registration.yaml')
    monkeypatch.setattr(ev, 'load_model', lambda *a, **k: (SimpleNamespace(max_frames=8),
        SimpleNamespace(device='cuda:0', dtype='torch.bfloat16', is_loaded_in_4bit=False)))
    monkeypatch.setattr('finetune.eval_holdout._runtime_library_versions', lambda: {
        'llamafactory_version': 'synthetic', 'transformers_version': 'synthetic'})
    if blind:
        monkeypatch.setattr(ev, 'run_model_on_video_detailed', lambda *a, **k: SimpleNamespace(raw_output='expressed answer ' + a[2].stem))
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        ev.prepare_versioned_evaluation(**kwargs)
        ev.execute_versioned_evaluation(root=root, eval_version=kwargs['eval_version'])
    manual = tmp_path / 'manual.txt'; manual.write_text(MANUAL)
    return root, registry, truth, kwargs, manual


def import_reviews(root, tmp_path, *, failed=False):
    private = root / 'workspace/evaluations/eval-v4.1-r2/restricted'
    rows = json.loads((private / 'predictions.json').read_bytes())
    evidence = {}
    for row in rows:
        digest = hashlib.sha256(row['raw_output'].encode()).hexdigest()
        current = policy()
        initial = [seal_judgment(actor_id=actor['id'], raw_sha256=digest,
            policy_sha256=content_digest(current), fields={} if failed else LABELS,
            sequence=i, status='infrastructure_failure' if failed else 'completed')
            for i, actor in enumerate(current['participants'])]
        evidence[digest] = {'policy': current, 'initial': initial, 'sealed_at': 5,
            'access_scope': 'anonymous-raw-and-manual-only'}
    file = tmp_path / ('failed.json' if failed else 'reviews.json')
    file.write_text(json.dumps(evidence))
    return file


def test_actual_kernel_sandbox_denies_canaries():
    import platform
    if platform.system() != 'Darwin':
        pytest.skip('Mac sandbox adapter only; other platforms reject emission')
    receipt = probe_review_isolation()
    assert all(receipt['checks'].values())
    assert receipt['synthetic'] and not receipt['real_model_deployment_verified']


def test_final_gates_are_separate_and_missing_classes_fail():
    records = [{'candidate_id': 'synthetic', 'raw_output': json.dumps(LABELS),
                'target': LABELS, 'source_group': 'g'}]
    summary = final_metrics(records)
    gates = public_gates(summary)
    assert len(gates) == 12 and gate_outcome(gates) == 'failed'
    assert summary['metrics']['fracture_mechanism_macro_f1'] is None


def test_all_semantic_classes_can_pass_final_protocol():
    targets = [dict(LABELS, clip_state=s) for s in FOUR_STATES]
    targets += [dict(LABELS, clip_state='已断裂', fracture_mechanism=m,
                     fracture_site=ENUMS['fracture_site'][i % 3])
                for i, m in enumerate(ENUMS['fracture_mechanism'][:-1])]
    targets += [dict(LABELS, clip_state='无法判断', special_case=label)
                for label in ENUMS['special_case'][:-1]]
    records = [{'candidate_id': str(i), 'raw_output': json.dumps(target),
        'target': target, 'source_group': str(i)} for i, target in enumerate(targets)]
    assert gate_outcome(public_gates(final_metrics(records))) == 'passed'


def test_score_requires_judge_before_truth(tmp_path, monkeypatch):
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch)
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        with pytest.raises(ValueError, match='ordinary file'):
            score_holdout_evaluation(root=root, eval_version=kwargs['eval_version'], executor='synthetic')
    assert not (truth.parent.parent / 'authorization/consumed.yaml').exists()


def test_exposed_seal_score_recovery_no_truth_or_reinference(tmp_path, monkeypatch):
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch)
    version = kwargs['eval_version']
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        first = prepare_holdout_review(root=root, eval_version=version, manual=manual)
        assert first['phase'] == 'exposed'
        assert prepare_holdout_review(root=root, eval_version=version, manual=manual) == first
        empty = tmp_path / 'empty.json'; empty.write_text('{}')
        seal_holdout_review(root=root, eval_version=version, blind_reviews=empty)
    manifest = score_holdout_evaluation(root=root, eval_version=version, executor='synthetic')
    public = yaml.safe_load(manifest.read_text())
    assert public['scoring_protocol'] == PROTOCOL
    assert public['review_integrity']['synthetic'] is True
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        assert score_holdout_evaluation(root=root, eval_version=version, executor='synthetic') == manifest
        with pytest.raises(ValueError, match='consumed|exposed'):
            ev.execute_versioned_evaluation(root=root, eval_version=version)
    assert (truth.parent.parent / 'authorization/exposed.yaml').is_file()
    assert (truth.parent.parent / 'authorization/consumed.yaml').is_file()


def test_blind_attempt_failure_then_retry_remains_immutable(tmp_path, monkeypatch):
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch, blind=True)
    version = kwargs['eval_version']
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        prepare_holdout_review(root=root, eval_version=version, manual=manual)
        with pytest.raises(ev.EvaluationReviewPending):
            seal_holdout_review(root=root, eval_version=version, blind_reviews=import_reviews(root, tmp_path, failed=True))
        seal_holdout_review(root=root, eval_version=version, blind_reviews=import_reviews(root, tmp_path))
        changed = json.loads((tmp_path / 'reviews.json').read_bytes())
        for evidence in changed.values():
            for judgment in evidence['initial']:
                payload = {k: v for k, v in judgment.items() if k != 'sha256'}
                payload['fields'] = {}
                judgment.update(**payload, sha256=content_digest(payload))
        bad = tmp_path / 'changed.json'; bad.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match='completed blind judgment'):
            seal_holdout_review(root=root, eval_version=version, blind_reviews=bad)
    score_holdout_evaluation(root=root, eval_version=version, executor='synthetic')


def test_config_model_runtime_drift_rejected():
    config = {'scope': 'full', 'scorer': PROTOCOL, 'thresholds': THRESHOLDS,
        'review_runtime': REVIEW_RUNTIME, 'source_groups': {'synthetic': 'synthetic'}, 'blind_policy': policy(), **runtime_config()}
    validate_semantic_holdout_config(config)
    extended = json.loads(json.dumps(config))
    extended['blind_policy']['participants'].append({**extended['blind_policy']['participants'][0], 'id': 'fourth-context'})
    validate_semantic_holdout_config(extended)
    config['review_runtime'] = {**REVIEW_RUNTIME, 'endpoint': 'https://remote.invalid'}
    with pytest.raises(ValueError, match='local Ollama'):
        validate_semantic_holdout_config(config)


def test_synthetic_broker_runs_only_anonymous_fixed_context_and_retry(tmp_path, monkeypatch):
    from finetune.eval_holdout import run_holdout_review
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch, blind=True)
    class Broker:
        synthetic = True
        def __init__(self): self.calls = []
        def generate(self, request):
            self.calls.append(request)
            assert set(request) == {'model', 'stream', 'keep_alive', 'think', 'options', 'messages'}
            assert all(set(message) == {'role', 'content'} for message in request['messages'])
            assert request['messages'][0]['content'].endswith(MANUAL)
            data = json.loads(request['messages'][1]['content'])
            assert set(data) == {'raw_output', 'requested_fields'}
            if len(self.calls) == 1:
                raise RuntimeError('synthetic terminal infrastructure fault; backend stopped')
            return json.dumps(LABELS)
    broker = Broker()
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        prepare_holdout_review(root=root, eval_version=kwargs['eval_version'], manual=manual)
        result = run_holdout_review(root=root, eval_version=kwargs['eval_version'], broker=broker)
    assert result['phase'] == 'judge-sealed'
    assert len(broker.calls) == 9  # 4 raws x 2 initial contexts + one runtime retry
    private = root / 'workspace/evaluations/eval-v4.1-r2/restricted'
    judge = json.loads((private / 'judge.json').read_bytes())
    assert judge['audit']['infrastructure_failure_count'] == 1
    assert len(list((private / 'review_attempts').iterdir())) == 2
    assert (private / 'review_attempts').stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match='already started'):
        run_holdout_review(root=root, eval_version=kwargs['eval_version'], broker=broker)


def test_synthetic_broker_arbiter_seals_before_disclosure(tmp_path, monkeypatch):
    from finetune.eval_holdout import run_holdout_review
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch, blind=True)
    class Broker:
        synthetic = True
        def generate(self, request):
            if len(request['messages']) == 3:
                disclosure = json.loads(request['messages'][2]['content'])
                assert disclosure['disagreement_fields'] == ['clip_state']
                return json.dumps({'clip_state': '未断裂'})
            return json.dumps(dict(LABELS, clip_state='已断裂') if request['model'] == 'ornith-1.5:9b' else LABELS)
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        prepare_holdout_review(root=root, eval_version=kwargs['eval_version'], manual=manual)
        result = run_holdout_review(root=root, eval_version=kwargs['eval_version'], broker=Broker())
    assert result['phase'] == 'judge-sealed'
    private = root / 'workspace/evaluations/eval-v4.1-r2/restricted'
    for review in json.loads((private / 'judge.json').read_bytes())['reviews'].values():
        assert review['arbiter_independent']['sequence'] < review['disclosed_at'] < review['arbitration']['sequence']


def test_no_real_model_call_permitted_by_synthetic_isolation(tmp_path, monkeypatch):
    from finetune.eval_holdout import run_holdout_review
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch)
    prepare_holdout_review(root=root, eval_version=kwargs['eval_version'], manual=manual)
    with pytest.raises(ValueError, match='deployment/tokenizer not verified'):
        run_holdout_review(root=root, eval_version=kwargs['eval_version'], allow_real_model_calls=True)


def test_local_broker_fixed_transport_and_weight_digest(monkeypatch):
    import urllib.request
    from finetune.eval_review import LocalOllamaBroker
    calls = []
    class Response:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps(self.data).encode()
    class Opener:
        def open(self, target, *, timeout):
            url = target if isinstance(target, str) else target.full_url
            calls.append(url)
            assert 0 < timeout <= 120
            if url.endswith('/api/tags'):
                return Response({'models': [{'name': 'qwen3.5:9b', 'digest': MODEL_DIGESTS['qwen3.5:9b']}]})
            request = json.loads(target.data)
            assert request['options'] == {'num_ctx': 8192, 'num_predict': 512, 'temperature': 0}
            assert request['raw'] is True and request['prompt'] == 'synthetic rendered prompt' and 'messages' not in request
            return Response({'model': 'qwen3.5:9b', 'done': True, 'done_reason': 'stop', 'response': json.dumps(LABELS), 'prompt_eval_count': 10})
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: Opener())
    request = {'model': 'qwen3.5:9b', 'stream': False, 'keep_alive': 0, 'think': False,
        'options': {'num_ctx': 8192, 'num_predict': 512, 'temperature': 0},
        'messages': [{'role': 'system', 'content': MANUAL}, {'role': 'user', 'content': '{}'}]}
    with pytest.raises(ValueError, match='not authorized'):
        LocalOllamaBroker().generate(request)
    broker = LocalOllamaBroker(allow_real_model_calls=True, token_counter=RawCounter(10))
    assert json.loads(broker.generate(request)) == LABELS
    assert calls == ['http://127.0.0.1:11434/api/tags', 'http://127.0.0.1:11434/api/generate']
    with pytest.raises(ValueError, match='no truncation'):
        LocalOllamaBroker(allow_real_model_calls=True, token_counter=RawCounter(9000)).generate(request)


def test_restricted_aggregates_require_explicit_frozen_owner(tmp_path, monkeypatch):
    from finetune.eval_holdout import read_restricted_holdout_summary
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch)
    prepare_holdout_review(root=root, eval_version=kwargs['eval_version'], manual=manual)
    empty = tmp_path / 'empty.json'; empty.write_text('{}')
    seal_holdout_review(root=root, eval_version=kwargs['eval_version'], blind_reviews=empty)
    score_holdout_evaluation(root=root, eval_version=kwargs['eval_version'], executor='synthetic')
    with pytest.raises(ValueError, match='explicitly frozen acceptance-owner'):
        read_restricted_holdout_summary(root=root, eval_version=kwargs['eval_version'], actor='synthetic')


def test_reviewer_sandbox_failure_prevents_any_exposure(tmp_path, monkeypatch):
    import finetune.eval_review as review
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch)
    def unavailable(): raise ValueError('synthetic unsupported platform')
    monkeypatch.setattr(review, 'probe_review_isolation', unavailable)
    with pytest.raises(ValueError, match='unsupported platform'):
        prepare_holdout_review(root=root, eval_version=kwargs['eval_version'], manual=manual)
    assert not (truth.parent.parent / 'authorization/exposed.yaml').exists()


def test_explicit_owner_consumed_aggregate_view_is_not_per_sample(tmp_path, monkeypatch):
    import os
    from finetune.eval_holdout import read_restricted_holdout_summary
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch,
        aggregate_authorization={'actor': 'synthetic-owner', 'role': 'acceptance-owner', 'os_uid': os.geteuid()})
    version = kwargs['eval_version']
    prepare_holdout_review(root=root, eval_version=version, manual=manual)
    empty = tmp_path / 'empty.json'; empty.write_text('{}')
    seal_holdout_review(root=root, eval_version=version, blind_reviews=empty)
    with pytest.raises(ValueError):
        read_restricted_holdout_summary(root=root, eval_version=version, actor='synthetic-owner')
    score_holdout_evaluation(root=root, eval_version=version, executor='synthetic')
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        result = read_restricted_holdout_summary(root=root, eval_version=version, actor='synthetic-owner')
    serialized = json.dumps(result)
    assert 'raw_output' not in serialized and 'candidate_id' not in serialized and 'source_to_group' not in serialized
    assert result['tuning_use'] == 'forbidden'
    with pytest.raises(ValueError, match='acceptance-owner'):
        read_restricted_holdout_summary(root=root, eval_version=version, actor='synthetic')


def test_worker_request_mutation_rejected_before_truth(tmp_path, monkeypatch):
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch)
    version = kwargs['eval_version']
    prepare_holdout_review(root=root, eval_version=version, manual=manual)
    request = root / 'workspace/evaluations' / version / 'restricted/actor-requests-0.json'
    request.chmod(0o600); request.write_text('{}'); request.chmod(0o400)
    empty = tmp_path / 'empty.json'; empty.write_text('{}')
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        with pytest.raises(ValueError, match='worker receipt/request drift'):
            seal_holdout_review(root=root, eval_version=version, blind_reviews=empty)


def test_broker_timeout_unknown_backend_does_not_retry_or_switch(tmp_path, monkeypatch):
    from finetune.eval_holdout import run_holdout_review
    from finetune.eval_review import ReviewExecutionAmbiguous
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch, blind=True)
    class Broker:
        synthetic = True
        calls = 0
        def generate(self, request):
            self.calls += 1
            raise TimeoutError('synthetic request timeout; backend termination unknown')
    broker = Broker()
    prepare_holdout_review(root=root, eval_version=kwargs['eval_version'], manual=manual)
    with pytest.raises(ReviewExecutionAmbiguous, match='backend termination unknown'):
        run_holdout_review(root=root, eval_version=kwargs['eval_version'], broker=broker)
    assert broker.calls == 1
    private = root / 'workspace/evaluations' / kwargs['eval_version'] / 'restricted'
    assert (private / 'broker-started.json').is_file()
    assert len(list((private / 'broker_calls').glob('*-started.json'))) == 1
    assert not list((private / 'broker_calls').glob('*-sealed.json'))
    with pytest.raises(ValueError, match='already started'):
        run_holdout_review(root=root, eval_version=kwargs['eval_version'], broker=broker)
    assert broker.calls == 1


def test_local_transport_unknown_terminal_state_persistently_blocks_runtime(tmp_path, monkeypatch):
    import urllib.request
    from finetune.eval_review import LocalOllamaBroker, ReviewExecutionAmbiguous
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            return json.dumps({'models': [{'name': 'qwen3.5:9b', 'digest': MODEL_DIGESTS['qwen3.5:9b']}]}).encode()
    class Opener:
        def open(self, target, *, timeout):
            calls.append(target)
            if isinstance(target, str): return Response()
            raise TimeoutError('synthetic socket timeout after request sent')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: Opener())
    request = {'model': 'qwen3.5:9b', 'stream': False, 'keep_alive': 0, 'think': False,
        'options': {'num_ctx': 8192, 'num_predict': 512, 'temperature': 0},
        'messages': [{'role': 'system', 'content': MANUAL}, {'role': 'user', 'content': '{}'}]}
    broker = LocalOllamaBroker(allow_real_model_calls=True, token_counter=RawCounter(10),
        runtime_directory=tmp_path / 'runtime')
    with pytest.raises(ReviewExecutionAmbiguous, match='no verified terminal response'):
        broker.generate(request)
    assert len(calls) == 2
    assert (tmp_path / 'runtime/backend-ambiguous.json').stat().st_mode & 0o077 == 0
    with pytest.raises(ReviewExecutionAmbiguous, match='prior backend termination'):
        broker.generate(request)
    assert len(calls) == 2


def test_local_broker_runtime_leaf_symlink_rejected(tmp_path):
    from finetune.eval_review import LocalOllamaBroker
    target = tmp_path / 'other'; target.mkdir()
    link = tmp_path / 'runtime'; link.symlink_to(target, target_is_directory=True)
    broker = LocalOllamaBroker(allow_real_model_calls=True, token_counter=RawCounter(1), runtime_directory=link)
    with pytest.raises(ValueError, match='leaf cannot be a symlink'):
        broker.generate({})


def test_default_quality_loader_records_actual_runtime_without_real_loading(tmp_path, monkeypatch):
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch)
    private = root / 'workspace/evaluations' / kwargs['eval_version'] / 'restricted'
    inference = json.loads((private / 'inference.json').read_bytes())
    assert inference['runtime_attestation'] == {key: kwargs['config'][key] for key in ('device', 'runtime_variant', 'quantization_bit')}
    assert inference['runtime_observation']['loaded_runtime']['runtime_dtype'] == 'bfloat16'
    assert inference['runtime_observation']['generation'] == ev.FORMAL_GENERATION
    prepare_holdout_review(root=root, eval_version=kwargs['eval_version'], manual=manual)
    empty = tmp_path / 'empty-runtime.json'; empty.write_text('{}')
    seal_holdout_review(root=root, eval_version=kwargs['eval_version'], blind_reviews=empty)
    manifest = score_holdout_evaluation(root=root, eval_version=kwargs['eval_version'], executor='synthetic')
    evidence = json.loads(manifest.read_bytes())
    assert evidence['runtime_attestation'] == inference['runtime_attestation']
    assert evidence['runtime_observation'] == inference['runtime_observation']


@pytest.mark.parametrize('damage', ['dtype', 'device', 'frames', 'library'])
def test_quality_actual_runtime_drift_stops_before_inference(monkeypatch, damage):
    from finetune.eval_holdout import _collect_loaded_runtime
    config = {**runtime_config(), 'quantization_bit': None, 'generation': dict(ev.FORMAL_GENERATION)}
    model = SimpleNamespace(device='cuda:0', dtype='torch.bfloat16', is_loaded_in_4bit=False)
    processor = SimpleNamespace(max_frames=8)
    versions = {'llamafactory_version': 'synthetic', 'transformers_version': 'synthetic'}
    if damage == 'dtype': model.dtype = 'torch.float16'
    if damage == 'device': model.device = 'cuda:1'
    if damage == 'frames': processor.max_frames = 16
    if damage == 'library': versions['transformers_version'] = 'changed'
    monkeypatch.setattr('finetune.eval_holdout._runtime_library_versions', lambda: versions)
    with pytest.raises(ValueError):
        _collect_loaded_runtime(processor, model, {'config': config})


def test_quality_four_bit_compute_storage_are_actual_separate_evidence(monkeypatch):
    from finetune.eval_holdout import _collect_loaded_runtime
    from tests.test_eval_performance import quantized_stub
    config = {**runtime_config(), 'quantization_bit': 4, 'generation': dict(ev.FORMAL_GENERATION)}
    config['runtime_variant']['quantization'] = {'quant_type': 'nf4', 'double_quant': True,
        'compute_dtype': 'bfloat16', 'quant_storage': 'uint8',
        'skip_modules': ['resampler'], 'excluded_module_dtype': 'bfloat16'}
    monkeypatch.setattr('finetune.eval_holdout._runtime_library_versions', lambda: {
        'llamafactory_version': 'synthetic', 'transformers_version': 'synthetic'})
    evidence = _collect_loaded_runtime(SimpleNamespace(max_frames=8), quantized_stub(), {'config': config})
    assert evidence['runtime_attestation']['runtime_variant']['dtype'] == 'bfloat16'
    assert evidence['runtime_attestation']['runtime_variant']['quantization']['quant_storage'] == 'uint8'
    for damage in ({'storage': 'bfloat16'}, {'module_compute': 'float16'}, {'double': False}, {'quant_type': 'fp4'}, {'resampler_dtype': 'float32'}, {'resampler_quantized': True}):
        with pytest.raises(ValueError):
            _collect_loaded_runtime(SimpleNamespace(max_frames=8), quantized_stub(**damage), {'config': config})


def tokenizer_sources(tmp_path):
    import finetune.eval_review_deployment as provider
    sources = {}
    for index, model in enumerate(MODEL_DIGESTS):
        root = tmp_path / f'tokenizer-{index}'; root.mkdir()
        raw = b'{"synthetic_vocabulary": ["hello", "world"]}'
        (root / 'tokenizer.json').write_bytes(raw)
        sources[model] = {'path': str(root), 'upstream_source': 'synthetic/local-counter',
            'upstream_revision': 'synthetic-frozen-revision', 'model_sha256': MODEL_DIGESTS[model],
            'files': {'tokenizer.json': {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}},
            'libraries': {name: {'version': 'synthetic', 'code_sha256': 'a' * 64} for name in ('transformers', 'tokenizers')},
            'implementation_sha256': hashlib.sha256(Path(provider.__file__).read_bytes()).hexdigest(),
            'ollama_template_sha256': hashlib.sha256(b'synthetic-template').hexdigest()}
        spec = sources[model]
        basis = tmp_path / f'counter-basis-{index}.md'; basis.write_text('Synthetic independently reviewed tokenizer mapping fixture. No real mapping audit performed.')
        messages = [{'role': 'system', 'content': 'synthetic fixed manual'}, {'role': 'user', 'content': 'synthetic 中文 <special> answer'}]
        prompt = json.dumps(messages)
        audit = {'schema_version': 'tensile-reviewed-tokenizer-equivalence/v1', 'purpose': 'precall-context-budget',
            'reviewer': {'id': 'synthetic-independent-reviewer', 'role': 'independent-tokenizer-auditor'},
            'reviewed_at': '2026-10-15T00:00:00+00:00', 'review_source': 'synthetic local fixture; not a real audit',
            'binding': {'model': model, 'model_sha256': MODEL_DIGESTS[model],
                'upstream_source': spec['upstream_source'], 'upstream_revision': spec['upstream_revision'],
                'tokenizer_files': spec['files'], 'libraries': spec['libraries'],
                'provider_implementation_sha256': spec['implementation_sha256'],
                'format': 'hf-rendered-raw-generate-v1', 'enable_thinking': False, 'add_special_tokens': False,
                'special_token_behavior': {'add_bos_token': None, 'add_eos_token': None, 'special_tokens_map_sha256': content_digest({})}},
            'gguf_counter_source': {'method': 'independent-gguf-tokenizer', 'model_sha256': MODEL_DIGESTS[model],
                'implementation': {'name': 'synthetic-independent-counter', 'version': 'fixture', 'sha256': 'c' * 64}},
            'basis': [{'path': str(basis), 'sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'description': 'synthetic evidence only'}],
            'golden_cases': [{'id': 'synthetic-unicode-special', 'messages': messages,
                'rendered_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                'token_ids': list(range(len(prompt.encode())))}]}
        path = tmp_path / f'counter-audit-{index}.json'; path.write_text(json.dumps(audit))
        spec['tokenizer_equivalence_audit'] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return sources


def synthetic_metadata(route, payload=None):
    if route == '/api/tags':
        assert payload is None
        return {'models': [{'name': name, 'digest': digest} for name, digest in MODEL_DIGESTS.items()]}
    assert route == '/api/show' and set(payload) == {'model'} and payload['model'] in MODEL_DIGESTS
    return {'template': 'synthetic-template'}


class SyntheticTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, enable_thinking):
        assert not tokenize and add_generation_prompt and enable_thinking is False
        return json.dumps(messages)
    def encode(self, prompt, *, add_special_tokens):
        assert add_special_tokens is False
        return list(range(len(prompt.encode())))


def test_local_deployment_counter_fixture_is_synthetic_and_cannot_upgrade(tmp_path, monkeypatch):
    from finetune.eval_holdout import verify_holdout_review_deployment, run_holdout_review
    sources = tokenizer_sources(tmp_path)
    root, registry, truth, kwargs, manual = prepare(tmp_path, monkeypatch, review_tokenizers=sources)
    version = kwargs['eval_version']
    prepare_holdout_review(root=root, eval_version=version, manual=manual)
    with monkeypatch.context() as guard:
        forbid_truth(guard, truth)
        result = verify_holdout_review_deployment(root=root, eval_version=version, allow_local_metadata=True,
            transport=synthetic_metadata, tokenizer_factory=lambda spec: SyntheticTokenizer())
    assert result['synthetic'] and not result['real_model_deployment_verified']
    assert not result['model_inference_performed']
    with pytest.raises(ValueError, match='synthetic or uncommitted'):
        run_holdout_review(root=root, eval_version=version, allow_real_model_calls=True)
    receipt = root / 'workspace/evaluations' / version / 'restricted/review-deployment.json'
    receipt.chmod(0o600)
    fake = json.loads(receipt.read_bytes()); fake['synthetic'] = False; fake['real_model_deployment_verified'] = True
    fake['sha256'] = content_digest({key: item for key, item in fake.items() if key != 'sha256'})
    receipt.write_text(json.dumps(fake)); receipt.chmod(0o400)
    with pytest.raises(ValueError, match='synthetic or uncommitted'):
        run_holdout_review(root=root, eval_version=version, allow_real_model_calls=True)


def test_local_deployment_needs_explicit_sources_authorization_and_pinned_bytes(tmp_path):
    from finetune.eval_review_deployment import verify_local_deployment
    sources = tokenizer_sources(tmp_path)
    arguments = dict(sources=sources, binding={'synthetic': 'only'}, transport=synthetic_metadata,
        tokenizer_factory=lambda spec: SyntheticTokenizer())
    with pytest.raises(ValueError, match='explicit local metadata'):
        verify_local_deployment(**arguments)
    with pytest.raises(ValueError, match='explicit local tokenizer sources'):
        verify_local_deployment(**{**arguments, 'sources': None}, allow_local_metadata=True)
    first = next(iter(sources.values()))
    asset = Path(first['path']) / 'tokenizer.json'; asset.write_text('changed synthetic asset')
    with pytest.raises(ValueError, match='asset/provider implementation drift'):
        verify_local_deployment(**arguments, allow_local_metadata=True)


def test_local_deployment_fake_verified_flag_and_template_drift_refused(tmp_path):
    from finetune.eval_review_deployment import validate_tokenizer_sources, verify_local_deployment
    sources = tokenizer_sources(tmp_path)
    fake = json.loads(json.dumps(sources)); next(iter(fake.values()))['verified'] = True
    with pytest.raises(ValueError, match='complete provenance'):
        validate_tokenizer_sources(fake)
    def wrong_template(route, payload=None):
        return synthetic_metadata(route, payload) if route == '/api/tags' else {'template': 'changed'}
    with pytest.raises(ValueError, match='template drift'):
        verify_local_deployment(sources=sources, binding={'synthetic': 'only'}, allow_local_metadata=True,
            transport=wrong_template, tokenizer_factory=lambda spec: SyntheticTokenizer())


def test_same_content_different_template_cannot_underestimate_raw_prompt(tmp_path, monkeypatch):
    import urllib.request
    from finetune.eval_review import LocalOllamaBroker
    from finetune.eval_review_deployment import LocalTokenCounter
    class LongTemplate(SyntheticTokenizer):
        def apply_chat_template(self, messages, **kwargs):
            assert kwargs['enable_thinking'] is False
            return 'large model template prefix ' * 600 + json.dumps(messages)
    counter = LocalTokenCounter({'qwen3.5:9b': LongTemplate()})
    def forbidden(*a): pytest.fail('oversized rendered prompt must stop before any network request')
    monkeypatch.setattr(urllib.request, 'build_opener', forbidden)
    broker = LocalOllamaBroker(allow_real_model_calls=True, token_counter=counter,
        runtime_directory=tmp_path / 'runtime')
    request = {'model': 'qwen3.5:9b', 'stream': False, 'keep_alive': 0, 'think': False,
        'options': {'num_ctx': 8192, 'num_predict': 512, 'temperature': 0},
        'messages': [{'role': 'user', 'content': 'same tiny raw answer'}]}
    with pytest.raises(ValueError, match='no truncation'):
        broker.generate(request)
    request['prompt'] = 'caller raw bypass'
    with pytest.raises(ValueError, match='parameters/tools drift'):
        broker.generate(request)


def test_server_tokenization_or_model_drift_never_adopts_answer(tmp_path, monkeypatch):
    import urllib.request
    from finetune.eval_review import LocalOllamaBroker
    class Response:
        def __init__(self, result): self.result = result
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps(self.result).encode()
    class Opener:
        def open(self, target, **kwargs):
            if isinstance(target, str):
                return Response({'models': [{'name': 'qwen3.5:9b', 'digest': MODEL_DIGESTS['qwen3.5:9b']}]})
            body = json.loads(target.data)
            assert body['raw'] is True and body['prompt'] == 'synthetic rendered prompt'
            return Response({'model': 'qwen3.5:9b', 'done': True, 'done_reason': 'stop',
                'response': json.dumps(LABELS), 'prompt_eval_count': 1})
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: Opener())
    broker = LocalOllamaBroker(allow_real_model_calls=True, token_counter=RawCounter(10), runtime_directory=tmp_path / 'runtime')
    request = {'model': 'qwen3.5:9b', 'stream': False, 'keep_alive': 0, 'think': False,
        'options': {'num_ctx': 8192, 'num_predict': 512, 'temperature': 0},
        'messages': [{'role': 'user', 'content': 'synthetic answer'}]}
    with pytest.raises(ValueError, match='different model or tokenization'):
        broker.generate(request)


def test_default_counter_loader_is_local_only_and_rejects_library_drift(tmp_path, monkeypatch):
    import sys
    import finetune.eval_review_deployment as provider
    sources = tokenizer_sources(tmp_path)
    spec = next(iter(sources.values()))
    calls = []
    class LocalTokenizer(SyntheticTokenizer):
        __module__ = 'transformers.synthetic_fixture'
    class Loader:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls.append((path, kwargs)); return LocalTokenizer()
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(AutoTokenizer=Loader))
    monkeypatch.setattr(provider, 'installed_library_identity', lambda name: spec['libraries'][name])
    counter = provider._load_local_tokenizer(spec)
    assert counter.__class__.__module__.startswith('transformers.')
    assert calls == [(spec['path'], {'local_files_only': True, 'trust_remote_code': False})]
    monkeypatch.setattr(provider, 'installed_library_identity', lambda name: {'version': 'changed', 'code_sha256': 'a' * 64})
    with pytest.raises(ValueError, match='dependency bytes/version drift'):
        provider._load_local_tokenizer(spec)
    assert len(calls) == 1


def test_equivalence_audit_is_required_and_bound_to_real_model_assets(tmp_path):
    from finetune.eval_review_deployment import verify_local_deployment
    sources = tokenizer_sources(tmp_path)
    arguments = dict(binding={'synthetic': 'only'}, allow_local_metadata=True,
        transport=synthetic_metadata, tokenizer_factory=lambda spec: SyntheticTokenizer())
    missing = json.loads(json.dumps(sources)); next(iter(missing.values())).pop('tokenizer_equivalence_audit')
    with pytest.raises(ValueError, match='complete provenance'):
        verify_local_deployment(sources=missing, **arguments)
    spec = next(iter(sources.values()))
    path = Path(spec['tokenizer_equivalence_audit']['path'])
    audit = json.loads(path.read_bytes())
    audit['binding']['model_sha256'] = 'd' * 64
    path.write_text(json.dumps(audit))
    spec['tokenizer_equivalence_audit']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='mapping binding'):
        verify_local_deployment(sources=sources, **arguments)


def test_equivalence_boolean_or_wrong_golden_cases_cannot_authorize_counter(tmp_path):
    from finetune.eval_review_deployment import verify_local_deployment
    sources = tokenizer_sources(tmp_path)
    arguments = dict(binding={'synthetic': 'only'}, allow_local_metadata=True,
        transport=synthetic_metadata, tokenizer_factory=lambda spec: SyntheticTokenizer())
    spec = next(iter(sources.values())); path = Path(spec['tokenizer_equivalence_audit']['path'])
    original = json.loads(path.read_bytes())
    path.write_text(json.dumps({'equivalent': True}))
    spec['tokenizer_equivalence_audit']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='named independent reviewer'):
        verify_local_deployment(sources=sources, **arguments)
    original['golden_cases'][0]['token_ids'] = [0]
    path.write_text(json.dumps(original))
    spec['tokenizer_equivalence_audit']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='golden tokenization case mismatch'):
        verify_local_deployment(sources=sources, **arguments)


def test_prediction_exposure_rejects_unbound_digest_and_symlink_folder(tmp_path):
    from versioning.holdout import ClaimIdentity, create_claim, mark_claim_exposed
    identity = ClaimIdentity('eval-v4.1-r1', 'model-v4.1-r1', 'data-v4.1-r1', 'holdout')
    directory = tmp_path / identity.data_version / 'authorization'
    create_claim(directory, identity, 'synthetic', pre_registration_sha256='a' * 64)
    arguments = dict(pre_registration_sha256='a' * 64, input_sha256='b' * 64,
        predictions_sha256='c' * 64, package_sha256='d' * 64)
    with pytest.raises(ValueError, match='explicit full SHA256'):
        mark_claim_exposed(directory, identity, 'synthetic', **{**arguments, 'predictions_sha256': None})
    assert not (directory / 'exposed.yaml').exists()
    alias = tmp_path / 'alias'; alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match='symlinks'):
        mark_claim_exposed(alias, identity, 'synthetic', **arguments)
    assert not (directory / 'exposed.yaml').exists()


def test_judge_single_deadline_covers_metadata_and_generation(tmp_path, monkeypatch):
    import urllib.request
    import finetune.eval_review as review
    clock = [0.0]
    calls = []
    monkeypatch.setattr(review, '_review_monotonic', lambda: clock[0])
    class Response:
        def __init__(self, kind): self.kind = kind
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            clock[0] += 100 if self.kind == 'tags' else 25
            return json.dumps({'models': [{'name': 'qwen3.5:9b', 'digest': MODEL_DIGESTS['qwen3.5:9b']}]}
                if self.kind == 'tags' else {'model': 'qwen3.5:9b', 'done': True, 'done_reason': 'stop',
                    'response': json.dumps(LABELS), 'prompt_eval_count': 10}).encode()
    class Opener:
        def open(self, target, *, timeout):
            calls.append((target if isinstance(target, str) else target.full_url, timeout))
            return Response('tags' if isinstance(target, str) else 'generate')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: Opener())
    broker = review.LocalOllamaBroker(allow_real_model_calls=True, token_counter=RawCounter(10), runtime_directory=tmp_path / 'runtime')
    request = {'model': 'qwen3.5:9b', 'stream': False, 'keep_alive': 0, 'think': False,
        'options': {'num_ctx': 8192, 'num_predict': 512, 'temperature': 0},
        'messages': [{'role': 'user', 'content': 'synthetic answer'}]}
    with pytest.raises(review.ReviewExecutionAmbiguous, match='deadline|terminal response'):
        broker.generate(request)
    assert calls == [('http://127.0.0.1:11434/api/tags', 120),
                     ('http://127.0.0.1:11434/api/generate', 20)]
    assert (tmp_path / 'runtime/backend-ambiguous.json').is_file()
    with pytest.raises(review.ReviewExecutionAmbiguous, match='prior backend termination'):
        broker.generate(request)
    assert len(calls) == 2


def test_judge_wall_deadline_does_not_wait_for_dripping_response(tmp_path, monkeypatch):
    import threading
    import time
    import urllib.request
    import finetune.eval_review as review
    release = threading.Event()
    entered = threading.Event()
    calls = []
    class Opener:
        def open(self, target, *, timeout):
            calls.append(target)
            entered.set()
            release.wait(1)
            raise TimeoutError('synthetic slow metadata/body')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: Opener())
    monkeypatch.setitem(review.REVIEW_RUNTIME, 'timeout_seconds', .05)
    broker = review.LocalOllamaBroker(allow_real_model_calls=True, token_counter=RawCounter(10), runtime_directory=tmp_path / 'runtime')
    request = {'model': 'qwen3.5:9b', 'stream': False, 'keep_alive': 0, 'think': False,
        'options': {'num_ctx': 8192, 'num_predict': 512, 'temperature': 0},
        'messages': [{'role': 'user', 'content': 'synthetic answer'}]}
    started = time.monotonic()
    try:
        with pytest.raises(review.ReviewExecutionAmbiguous, match='whole judge deadline'):
            broker.generate(request)
        assert entered.is_set() and time.monotonic() - started < .5
        assert (tmp_path / 'runtime/backend-ambiguous.json').is_file()
        assert len(calls) == 1
    finally:
        release.set()
