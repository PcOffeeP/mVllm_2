"""Explicit media-only full inference and separately authorized holdout scoring.

Public MLflow evidence contains inputs and aggregates only. Predictions, truth
access records and per-sample scores stay in the owner's private workspace.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from finetune import eval_run as ev
from finetune.holdout_metrics import METRIC_DEFINITIONS, restricted_metrics, public_gates, gate_outcome

SOURCES = ('versioning/holdout_pipeline.py', 'finetune/holdout_metrics.py', 'finetune/eval_holdout.py', 'finetune/eval_run.py', 'finetune/v4_1_runtime.py',
    'pipeline/v4_1_labels.py', 'finetune/validation/model_runtime.py',
    'finetune/validation/constants.py', 'finetune/validation/video_loader.py',
    'pipeline/preprocessing/minicpm_preprocessor.py')
SEMANTIC_SOURCES = (*SOURCES, 'finetune/eval_semantics.py', 'finetune/eval_review.py', 'versioning/holdout.py', 'versioning/performance.py', 'finetune/eval_review_deployment.py')

def _semantic(value):
    return value['config']['scorer'] == 'semantic-holdout-v4.1'

def _sources(value):
    return SEMANTIC_SOURCES if _semantic(value) else SOURCES

def _metric_definitions(value):
    if _semantic(value):
        from finetune.eval_review import METRIC_DEFINITIONS as definitions
        return definitions
    return METRIC_DEFINITIONS

def _public_metrics(value, actual):
    if _semantic(value):
        from finetune.eval_review import public_gates as gates
        return gates(actual)
    return public_gates(actual, value['config']['thresholds'])

def _outcome(value, gates):
    if _semantic(value):
        from finetune.eval_review import gate_outcome as outcome
        return outcome(gates)
    return gate_outcome(gates)

PUBLIC_FILES = {'input/evaluation.yaml', 'evaluation.yaml', 'summary.json', 'execution.json'}


def _digest(value):
    return hashlib.sha256(ev._formal_bytes(value)).hexdigest()


def _ordinary(path, *, private=False):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('holdout input must be an ordinary file')
    if private and path.stat().st_mode & 0o077:
        raise ValueError('holdout private file permissions must be owner-only')
    return path


def _json(path, *, private=False):
    return json.loads(_ordinary(path, private=private).read_bytes())


def _save(path, value, *, private=False):
    path = Path(path)
    if private:
        chain = []
        for parent in path.parents:
            chain.append(parent)
            if parent.name == 'restricted':
                break
        else:
            raise ValueError('private holdout evidence must remain in restricted workspace')
        for parent in reversed(chain):
            if parent.is_symlink():
                raise ValueError('private holdout evidence directory cannot be a symlink')
            parent.mkdir(mode=0o700, exist_ok=True)
            if parent.stat().st_mode & 0o077:
                raise ValueError('private holdout evidence directories must be owner-only')
    from versioning.manifest import _publish_immutable
    _publish_immutable(path, ev._formal_bytes(value), label='holdout execution evidence')
    if private:
        path.chmod(0o400)


def _authorization(root, value, *, allow_consumed=False):
    from versioning.holdout import ClaimIdentity, load_claim, load_pre_registration, validate_claim_consumed
    identity = ClaimIdentity(value['eval_version'], value['model']['model_id'], value['data_version'], value['config']['split'])
    prereg = Path(root) / 'evaluations/staging' / identity.eval_version / 'authorization/pre_registration.yaml'
    pre = load_pre_registration(_ordinary(prereg))
    actual = (pre.eval_version, pre.model_version, pre.data_version, pre.split)
    expected = (identity.eval_version, identity.model_version, identity.data_version, identity.split)
    if actual != expected or ev._sha256(prereg) != value['authorization']['pre_registration_sha256']:
        raise ValueError('holdout pre-registration identity/digest mismatch')
    if pre.rules != {k: v for k, v in value['config'].items() if k != 'thresholds'} or pre.thresholds != value['config']['thresholds']:
        raise ValueError('holdout pre-registration rules/thresholds differ from actual configuration')
    if pre.recovery != {'same_identity_only': True}:
        raise ValueError('holdout recovery must explicitly require same_identity_only')
    folder = Path(root) / 'data/releases' / identity.data_version / 'authorization'
    _ordinary(folder / 'claim.yaml')
    claim = load_claim(folder)
    if (claim.identity != identity or claim.executor != value['authorization']['executor']
            or claim.pre_registration_sha256 != value['authorization']['pre_registration_sha256']):
        raise ValueError('holdout claim binding mismatch')
    if (folder / 'consumed.yaml').exists():
        _ordinary(folder / 'consumed.yaml')
        if not allow_consumed:
            raise ValueError('holdout claim already consumed')
        validate_claim_consumed(folder, identity, claim.executor,
            pre_registration_sha256=claim.pre_registration_sha256)
    return prereg


def build_holdout_input(*, root, eval_version, model_version, model_version_number,
                        data_version, config, git_commit, media_root, inputs_path=None,
                        pre_registration=None, executor=None, prompt_checkout_root=None):
    from versioning.ids import parse_eval_id, parse_model_id, parse_data_id
    from versioning.data_release import load_release_metadata
    from versioning.holdout import validate_holdout_layout
    from versioning.registry import open_registry_store, validate_model_for_evaluation, _run_artifact_root
    from versioning.prompts import load_prompt, parse_prompt_definition, verify_prompt_checkout_copy
    import yaml
    root = Path(root).absolute()
    if {parse_eval_id(eval_version).protocol, parse_model_id(model_version).protocol,
        parse_data_id(data_version).protocol} != {'v4.1'}:
        raise ValueError('holdout identities must use v4.1')
    config = ev._formal_config(config)
    if config['scope'] != 'full' or config['split'] == 'validation' or inputs_path is not None:
        raise ValueError('full holdout requires an independent split and the release media manifest')
    if not isinstance(git_commit, str) or not git_commit.strip() or not isinstance(executor, str) or not executor.strip():
        raise ValueError('holdout git_commit and executor are required')
    frozen_pre = root / 'evaluations/staging' / eval_version / 'authorization/pre_registration.yaml'
    if pre_registration is None or Path(pre_registration).absolute() != frozen_pre:
        raise ValueError('first freeze pre-registration with data claim, then provide that frozen path')
    value = {'schema_version': 'tensile-vlm/v4.1-holdout-evaluation', 'eval_version': eval_version,
        'model': {'model_id': model_version}, 'data_version': data_version, 'config': config,
        'authorization': {'executor': executor, 'pre_registration_sha256': ev._sha256(_ordinary(frozen_pre))}}
    _authorization(root, value, allow_consumed=True)
    release = root / 'data/releases' / data_version
    _ordinary(release / 'release.yaml')
    meta = load_release_metadata(root / 'data', data_version)
    if meta.purpose != 'holdout' or meta.training_allowed or meta.status.value != 'active':
        raise ValueError('full independent acceptance requires an active non-training holdout release')
    validate_holdout_layout(release)  # Only directory metadata, never labels.
    if Path(media_root).absolute() != release / 'media':
        raise ValueError('holdout media_root must be the release media directory')
    registry = open_registry_store(root / 'workspace/mlflow', data_root=root / 'data')
    model = validate_model_for_evaluation(registry, model_version, model_version_number)
    if model.source_scope != 'full' or model.deploy_target != model.artifacts['full'].get(config['artifact_kind']):
        raise ValueError('full holdout must evaluate the full model deploy_target')
    from versioning.holdout_pipeline import validate_public_build
    build_sha256 = validate_public_build(release)
    build_receipt = _json(release / 'build_receipt.json')
    train_release = root / 'data/releases' / model.data_version / 'release.yaml'
    if build_receipt['binding']['development_release_sha256'] != ev._sha256(_ordinary(train_release)):
        raise ValueError('test build train release binding drifted')
    manifest_path = release / 'evaluation_inputs/manifest.json'
    manifest = _json(manifest_path)
    fields = {'schema_version', 'data_version', 'split', 'development_data_version',
        'development_source_isolation_verified', 'test_split_binding_verified', 'samples'}
    if (set(manifest) != fields or manifest['schema_version'] != 'tensile-holdout-media/v1'
        or manifest['data_version'] != data_version or manifest['split'] != config['split']
        or manifest['development_data_version'] != model.data_version
        or manifest['development_source_isolation_verified'] is not True
        or manifest['test_split_binding_verified'] is not True):
        raise ValueError('holdout media manifest binding/isolation mismatch')
    training_root = _run_artifact_root(registry, model.run_id) / 'input'
    training = yaml.safe_load((training_root / 'training.yaml').read_text())
    development_sources = set()
    for video in training['media']:
        match = re.match(r'(video_\d+)(?:_|$)', Path(video).stem)
        if match is None:
            raise ValueError('development media source identity is not verifiable')
        development_sources.add(match.group(1))
    samples, seen, seen_paths, media = manifest['samples'], set(), set(), {}
    if not isinstance(samples, list) or not samples or len(samples) != meta.sample_count:
        raise ValueError('holdout sample count mismatch')
    for row in samples:
        if not isinstance(row, dict) or set(row) != {'candidate_id', 'source_video', 'video_path'}:
            raise ValueError('holdout inference accepts media identities only, no targets')
        if any(not isinstance(v, str) or not v for v in row.values()):
            raise ValueError('holdout media identity must be explicit')
        path = Path(row['video_path'])
        match = re.match(r'(video_\d+)(?:_|$)', path.stem)
        if (path.is_absolute() or '..' in path.parts or path.as_posix() != row['video_path']
            or row['candidate_id'] != path.stem or match is None or match.group(1) != row['source_video']
            or row['source_video'] in development_sources or row['candidate_id'] in seen or path in seen_paths):
            raise ValueError('holdout media source isolation, identity or path mismatch')
        seen.add(row['candidate_id']); seen_paths.add(path)
        file = _ordinary(Path(media_root) / path)
        media[row['video_path']] = {'size': file.stat().st_size, 'sha256': ev._sha256(file)}
    # Prompt 的 store 副本与 Git checkout 副本必须逐字节一致；取 Prompt 之前
    # 先校验，与训练冻结、评测 prepare 同构。这里只是额外一层，下方「训练
    # Prompt 与 store 正式副本一致」的判定保持不变。
    verify_prompt_checkout_copy(root, model.prompt_version, checkout_root=prompt_checkout_root)
    prompt = parse_prompt_definition(yaml.safe_load((training_root / 'prompt.yaml').read_text()))
    if prompt != load_prompt(root, model.prompt_version):
        raise ValueError('holdout model training Prompt drifted')
    contract, _ = ev._load_contract()
    from finetune.validation.constants import GENERATION_CONFIG, VIDEO_MAX_FRAMES
    if {**GENERATION_CONFIG, 'video_max_frames': VIDEO_MAX_FRAMES} != ev.FORMAL_GENERATION:
        raise ValueError('holdout generation implementation drifted')
    return {**value, 'model': ev._model_binding(model), 'git_commit': git_commit,
        'inputs_path': None, 'media_root': str(Path(media_root).absolute()),
        'data_binding': {'build_receipt_sha256': build_sha256, 'release_sha256': ev._sha256(release / 'release.yaml'),
            'manifest_sha256': ev._sha256(manifest_path), 'media': media}, 'folds': [], 'samples': samples,
        'prompt': {'version': prompt.version, 'system_prompt': prompt.system_prompt,
            'user_prompt': prompt.user_prompt, 'output_fields': list(prompt.output_fields)},
        'contract_hash': contract['contract_hash'], 'metric_definitions': _metric_definitions(value),
        **_semantic_input(value, samples),
        'implementation_sha256': {name: ev._sha256(ev.ROOT / name) for name in _sources(value)}}



def _read_frozen_truth(path, value):
    raw = _ordinary(path, private=True).read_bytes()
    import hashlib
    receipt_bytes = _ordinary(path.parent.parent / 'build_receipt.json').read_bytes()
    if hashlib.sha256(receipt_bytes).hexdigest() != value['data_binding']['build_receipt_sha256']:
        raise ValueError('test build receipt drifted before authorized scoring')
    pin = json.loads(receipt_bytes)['inventory']['sealed_ground_truth']['labels.json']
    if len(raw) != pin['size_bytes'] or hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('authorized source truth drifted from frozen build receipt')
    return json.loads(raw)

def _private(workspace):
    private = workspace / 'restricted'
    if any(p.is_symlink() for p in (private, *private.parents)):
        raise ValueError('holdout private workspace contains symlinks')
    private.mkdir(mode=0o700, exist_ok=True)
    if private.stat().st_mode & 0o077:
        raise ValueError('holdout private workspace must be owner-only')
    return private


def _lock(workspace):
    handle = (workspace / '.execution.lock').open('a+b')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        handle.close()
        raise ValueError('holdout evaluation is already executing')
    return handle


def _infer(value, model_dir, adapter_dir):
    # No target, label path or scoring callback is passed into inference.
    selected = ev._checked_loader_path(model_dir)
    adapter = ev._checked_loader_path(adapter_dir) if adapter_dir else None
    processor, model = ev.load_model(selected, quantization_bit=value['config']['quantization_bit'], adapter_dir=adapter)
    predictions = []
    try:
        runtime_evidence = _collect_loaded_runtime(processor, model, value) if _semantic(value) else None
        for sample in value['samples']:
            try:
                result = ev.run_model_on_video_detailed(model, processor,
                    Path(value['media_root']) / sample['video_path'], value['prompt']['user_prompt'],
                    system_prompt=value['prompt']['system_prompt'])
                predictions.append({'candidate_id': sample['candidate_id'], 'raw_output': result.raw_output,
                    **({'runtime_error': None} if _semantic(value) else {})})
            except Exception as exc:
                if not _semantic(value):
                    raise
                predictions.append({'candidate_id': sample['candidate_id'], 'raw_output': None,
                                    'runtime_error': type(exc).__name__ + ': ' + str(exc)})
    finally:
        del processor, model
        import gc
        gc.collect()
    return {'predictions': predictions, **runtime_evidence} if _semantic(value) else predictions


def execute_holdout_inference(*, root, eval_version, prompt_checkout_root=None):
    from versioning.backup import scoped_mlflow_client
    from versioning.registry import open_registry_store, materialize_model
    from versioning.mlflow_eval import open_eval_store, create_eval_run, transition_eval_state
    root = Path(root).absolute()
    value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version,
        prompt_checkout_root=prompt_checkout_root)
    workspace = ev._formal_workspace(root, eval_version)
    with _lock(workspace):
        value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version,
            prompt_checkout_root=prompt_checkout_root)
        prereg = _authorization(root, value)
        if (root / 'data/releases' / value['data_version'] / 'authorization/exposed.yaml').exists():
            raise ValueError('holdout predictions already exposed; reinference forbidden')
        private = _private(workspace)
        if any(private.iterdir()):
            raise ValueError('existing holdout inference requires same-run scoring/recovery, never reinference')
        store = open_eval_store(root / 'workspace/mlflow')
        parent = create_eval_run(store, eval_version, model_id=value['model']['model_id'],
            model_version_number=value['model']['version'], data_version=value['data_version'],
            config=f'sha256:{_digest(value)}', git_commit=value['git_commit'], scope='full',
            split=value['config']['split'], data_root=root / 'data', pre_registration=prereg,
            executor=value['authorization']['executor'],
            **({'purpose': 'quality', 'protocol': 'semantic-holdout-v4.1'} if _semantic(value) else {}))
        client = scoped_mlflow_client(tracking_uri=store.tracking_uri)
        try:
            client.log_artifact(parent.run_id, str(workspace / 'input/evaluation.yaml'), artifact_path='input')
            registry = open_registry_store(store.root, data_root=root / 'data')
            with tempfile.TemporaryDirectory(prefix='.weights-', dir=workspace) as cache:
                materialized = materialize_model(registry, value['model']['model_id'], Path(cache))
                declared = value['model']['artifacts']['full'][value['config']['artifact_kind']]
                artifact = materialized / declared
                adapter = artifact if value['config']['artifact_kind'] == 'adapter' else None
                base = Path(value['model']['base_model']) if adapter else artifact
                weights = {'model_artifact': declared, 'model_files': ev._weight_inventory(base),
                    'adapter_files': ev._weight_inventory(adapter) if adapter else None}
                _save(private / 'started.json', {'run_id': parent.run_id, 'input_sha256': _digest(value) }, private=True)
                # Fresh live checks immediately before loading, and after return.
                ev.verify_versioned_evaluation(root=root, eval_version=eval_version,
                    prompt_checkout_root=prompt_checkout_root)
                inference_value = {**value, 'media_root': str(ev._restored_evaluation_media_root(root, value))}
                inferred = _infer(inference_value, base, adapter)
                if _semantic(value):
                    if not isinstance(inferred, dict) or set(inferred) != {'predictions', 'runtime_attestation', 'runtime_observation'}:
                        raise ValueError('semantic inference must provide actual loaded runtime attestation')
                    predictions = inferred['predictions']
                    runtime_evidence = {k: inferred[k] for k in ('runtime_attestation', 'runtime_observation')}
                    _validate_runtime_evidence(value, runtime_evidence)
                else:
                    predictions, runtime_evidence = inferred, {}
                ev.verify_versioned_evaluation(root=root, eval_version=eval_version,
                    prompt_checkout_root=prompt_checkout_root)
                if ev._weight_inventory(base) != weights['model_files'] or (adapter and ev._weight_inventory(adapter) != weights['adapter_files']):
                    raise ValueError('holdout loaded weights drifted')
            _save(private / 'predictions.json', predictions, private=True)
            receipt = {'run_id': parent.run_id, 'input_sha256': _digest(value),
                'predictions_sha256': ev._sha256(private / 'predictions.json'), 'weights': weights, **runtime_evidence}
            _save(private / 'inference.json', receipt, private=True)
            client.log_param(parent.run_id, 'sha256_holdout_inference', ev._sha256(private / 'inference.json'))
            return {'run_id': parent.run_id, 'phase': 'inferred', 'next_action': 'eval score', 'truth_accessed': False}
        except BaseException as exc:
            try:
                transition_eval_state(store, eval_version, 'failed', run_status='FAILED')
            except Exception as tracking_error:
                exc.add_note(f'holdout tracking failure: {tracking_error}')
            raise


def _check_run(client, run_id, value):
    run = client.get_run(run_id)
    expected = {'eval_id': value['eval_version'], 'model_id': value['model']['model_id'],
        'model_version_number': str(value['model']['version']), 'data_version': value['data_version'],
        'config': f'sha256:{_digest(value)}', 'git_commit': value['git_commit'], 'scope': 'full',
        'split': value['config']['split'], 'record_validity': 'valid'}
    if any(run.data.tags.get(k) != v for k, v in expected.items()):
        raise ValueError('holdout Run binding mismatch')
    return run


def _verify_private_scoring(private, value, inference, receipt):
    """Establish a scoring commitment from complete actual stage evidence.

    A bare summary file is never a recovery authority. The inference commitment
    pins predictions; replay the strict scorer against the private truth snapshot
    and compare every saved row before committing its public aggregate.
    """
    from pipeline.v4_1_labels import validate_v4_1_labels
    access = _json(private / 'truth-access.json', private=True)
    if access != {'run_id': inference['run_id'], 'input_sha256': _digest(value),
        'executor': value['authorization']['executor'],
        'pre_registration_sha256': value['authorization']['pre_registration_sha256']}:
        raise ValueError('holdout actual truth access evidence mismatch')
    truth = _json(private / 'truth-snapshot.json', private=True)
    if (set(truth) != {'schema_version', 'data_version', 'split', 'labels'}
        or truth['schema_version'] != 'tensile-holdout-truth/v1' or truth['data_version'] != value['data_version']
        or truth['split'] != value['config']['split'] or not isinstance(truth['labels'], dict)
        or set(truth['labels']) != {s['candidate_id'] for s in value['samples']}):
        raise ValueError('holdout actual truth snapshot mismatch')
    predictions = _json(private / 'predictions.json', private=True)
    if (not isinstance(predictions, list) or len(predictions) != len(value['samples'])
        or ev._sha256(private / 'predictions.json') != inference['predictions_sha256']):
        raise ValueError('holdout actual predictions mismatch')
    expected = []
    for sample, prediction in zip(value['samples'], predictions, strict=True):
        if (not _valid_prediction(value, prediction) or prediction['candidate_id'] != sample['candidate_id']
            ):
            raise ValueError('holdout actual prediction identity mismatch')
        target = truth['labels'][sample['candidate_id']]
        if not validate_v4_1_labels(target).valid:
            raise ValueError('holdout actual truth contract mismatch')
        parsed, error = None, None
        try:
            parsed = ev.parse_v4_1_output(prediction['raw_output']) if prediction['raw_output'] is not None else None
        except ev.V4_1FinetuneError as exc:
            error = str(exc)
        expected.append({**sample, 'target': target, **prediction, 'prediction': parsed,
            'strict_valid': parsed is not None, 'parse_error': error, 'runtime_error': prediction.get('runtime_error'),
            'scores': ev.score_v4_1_prediction(target, parsed)})
    actual_metrics = _score_records(private, value, inference, expected)
    if _json(private / 'scored-records.json', private=True) != expected:
        raise ValueError('holdout actual per-sample scoring mismatch')
    if _json(private / 'metrics.json', private=True) != actual_metrics:
        raise ValueError('holdout private metric evidence mismatch')
    metrics = _public_metrics(value, actual_metrics)
    outcome = _outcome(value, metrics)
    if receipt['summary'] != {'sample_count': len(expected), 'metrics': metrics,
        'outcome': outcome, 'input_sha256': _digest(value)}:
        raise ValueError('holdout actual aggregate scoring mismatch')


def score_holdout_evaluation(*, root, eval_version, executor, prompt_checkout_root=None):
    from versioning.backup import scoped_mlflow_client
    from versioning.mlflow_eval import open_eval_store, log_eval_summary, transition_eval_state
    from pipeline.v4_1_labels import validate_v4_1_labels
    root = Path(root).absolute()
    workspace = ev._formal_workspace(root, eval_version)
    value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version,
        prompt_checkout_root=prompt_checkout_root)
    if value['config']['scope'] != 'full' or executor != value['authorization']['executor']:
        raise ValueError('holdout scoring executor mismatch')
    with _lock(workspace):
        value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version,
            prompt_checkout_root=prompt_checkout_root)
        prereg = _authorization(root, value, allow_consumed=True)
        private = _private(workspace)
        inference = _json(private / 'inference.json', private=True)
        store = open_eval_store(root / 'workspace/mlflow')
        client = scoped_mlflow_client(tracking_uri=store.tracking_uri)
        run = _check_run(client, inference['run_id'], value)
        if (inference['input_sha256'] != _digest(value)
            or ev._sha256(private / 'inference.json') != run.data.params.get('sha256_holdout_inference')
            or ev._sha256(_ordinary(private / 'predictions.json', private=True)) != inference['predictions_sha256']):
            raise ValueError('holdout inference evidence drifted')
        try:
            receipt_path = private / 'scoring.json'
            if run.data.tags.get('workflow_state') == 'failed' and run.info.status == 'FAILED':
                # Exact claim, frozen input and completed inference were checked above.
                transition_eval_state(store, eval_version, 'running')
                run = _check_run(client, inference['run_id'], value)
            if not receipt_path.exists():
                _authorization(root, value)  # A consumed claim can only recover an existing scored receipt.
                if run.data.tags.get('workflow_state') != 'running' or run.info.status != 'RUNNING':
                    raise ValueError('holdout scoring requires the original running inference Run')
                predictions = _json(private / 'predictions.json', private=True)
                if (not isinstance(predictions, list) or len(predictions) != len(value['samples'])
                    or any(not isinstance(p, dict) or not _valid_prediction(value, p)
                        or p['candidate_id'] != s['candidate_id'] for p, s in zip(predictions, value['samples']))):
                    raise ValueError('holdout predictions do not cover the frozen media input')
                if _semantic(value):
                    _verified_judge(private, value, inference)
                # Durable access record is published before any truth bytes are read.
                _save(private / 'truth-access.json', {'run_id': run.info.run_id, 'input_sha256': _digest(value),
                    'executor': executor, 'pre_registration_sha256': value['authorization']['pre_registration_sha256']}, private=True)
                truth_path = root / 'data/releases' / value['data_version'] / 'sealed_ground_truth/labels.json'
                truth = _read_frozen_truth(truth_path, value)
                _save(private / 'truth-snapshot.json', truth, private=True)
                if (not isinstance(truth, dict) or set(truth) != {'schema_version', 'data_version', 'split', 'labels'}
                    or truth['schema_version'] != 'tensile-holdout-truth/v1' or truth['data_version'] != value['data_version']
                    or truth['split'] != value['config']['split'] or not isinstance(truth['labels'], dict)
                    or set(truth['labels']) != {s['candidate_id'] for s in value['samples']}):
                    raise ValueError('holdout truth binding/coverage mismatch')
                records = []
                for sample, prediction in zip(value['samples'], predictions, strict=True):
                    target = truth['labels'][sample['candidate_id']]
                    if not validate_v4_1_labels(target).valid:
                        raise ValueError('holdout truth labels violate the frozen contract')
                    parsed, error = None, None
                    try:
                        parsed = ev.parse_v4_1_output(prediction['raw_output']) if prediction['raw_output'] is not None else None
                    except ev.V4_1FinetuneError as exc:
                        error = str(exc)
                    records.append({**sample, 'target': target, **prediction, 'prediction': parsed,
                        'strict_valid': parsed is not None, 'parse_error': error, 'runtime_error': prediction.get('runtime_error'),
                        'scores': ev.score_v4_1_prediction(target, parsed)})
                actual_metrics = _score_records(private, value, inference, records)
                metrics = _public_metrics(value, actual_metrics)
                outcome = _outcome(value, metrics)
                _save(private / 'metrics.json', actual_metrics, private=True)
                public = {'sample_count': len(records), 'metrics': metrics, 'outcome': outcome,
                    'input_sha256': _digest(value)}
                _save(private / 'scored-records.json', records, private=True)
                _save(receipt_path, {'schema_version': 'tensile-holdout-score/v1', 'run_id': run.info.run_id,
                    'input_sha256': _digest(value), 'pre_registration_sha256': value['authorization']['pre_registration_sha256'],
                    'inference_sha256': ev._sha256(private / 'inference.json'),
                    'summary': public, 'weights': inference['weights'], **_review_integrity(private, value, inference)}, private=True)
                # No truth bytes, hashes, predictions or per-sample scores are public.
            receipt = _json(receipt_path, private=True)
            if (receipt['run_id'] != run.info.run_id or receipt['input_sha256'] != _digest(value)
                or receipt['pre_registration_sha256'] != value['authorization']['pre_registration_sha256']
                or receipt['inference_sha256'] != ev._sha256(private / 'inference.json')
                or receipt['weights'] != inference['weights']):
                raise ValueError('holdout scoring receipt binding mismatch')
            if (set(receipt) != {'schema_version', 'run_id', 'input_sha256', 'pre_registration_sha256',
                'inference_sha256', 'summary', 'weights'} | ({'review_integrity', 'runtime_attestation', 'runtime_observation'} if _semantic(value) else set()) or receipt['schema_version'] != 'tensile-holdout-score/v1'):
                raise ValueError('holdout scoring receipt schema mismatch')
            if _semantic(value) and any(receipt.get(key) != item for key, item in _review_integrity(private, value, inference).items()):
                raise ValueError('holdout scoring review/runtime integrity drift')
            commitment = run.data.params.get('sha256_holdout_scoring')
            if commitment is None:
                # Including recovery after private write but before MLflow commit.
                # This must happen before trusting or publishing any aggregate.
                _authorization(root, value)
                _verify_private_scoring(private, value, inference, receipt)
                source_truth = root / 'data/releases' / value['data_version'] / 'sealed_ground_truth/labels.json'
                # An uncommitted private directory is not an authority: compare
                # it with the authorized original source before establishing the
                # one-time public scoring commitment. Consumed recovery never
                # enters this branch.
                if _read_frozen_truth(source_truth, value) != _json(private / 'truth-snapshot.json', private=True):
                    raise ValueError('holdout uncommitted truth snapshot differs from authorized source')
                commitment = ev._sha256(receipt_path)
                client.log_param(run.info.run_id, 'sha256_holdout_scoring', commitment)
                if client.get_run(run.info.run_id).data.params.get('sha256_holdout_scoring') != commitment:
                    raise ValueError('holdout scoring commitment readback mismatch')
            if commitment != ev._sha256(receipt_path):
                raise ValueError('holdout scoring commitment drifted')
            output = workspace / 'output'
            output.mkdir(exist_ok=True)
            _save(output / 'evaluation.yaml', {**value, 'weights': {'full': inference['weights']}})
            _save(output / 'summary.json', receipt['summary'])
            _save(output / 'execution.json', receipt)
            for name in ('evaluation.yaml', 'summary.json', 'execution.json'):
                client.log_artifact(run.info.run_id, str(output / name))
                client.log_param(run.info.run_id, f'sha256_{name}', ev._sha256(output / name))
            if run.data.tags.get('outcome') is None:
                log_eval_summary(store, eval_version, receipt['summary']['metrics'])
            elif dict(run.data.metrics) != receipt['summary']['metrics']:
                raise ValueError('holdout completed summary drifted')
            transition_eval_state(store, eval_version, 'completed', outcome=receipt['summary']['outcome'],
                pre_registration=prereg, executor=executor)
            return ev.export_versioned_evaluation(root=root, eval_version=eval_version)
        except BaseException as exc:
            try:
                current = client.get_run(inference['run_id'])
                if current.data.tags.get('workflow_state') == 'running' and current.data.tags.get('outcome') is None:
                    transition_eval_state(store, eval_version, 'failed', run_status='FAILED')
            except Exception as tracking_error:
                exc.add_note(f'holdout scoring failure could not be recorded: {tracking_error}')
            raise


def validate_holdout_execution(*, store, record, value, artifact_root):
    from versioning.backup import scoped_mlflow_client
    from versioning.registry import _artifact_tree, _run_artifact_root, get_model
    from versioning.holdout import ClaimIdentity, validate_claim_consumed
    client = scoped_mlflow_client(tracking_uri=store.tracking_uri)
    if set(_artifact_tree(artifact_root)) != PUBLIC_FILES:
        raise ValueError('holdout public artifacts must contain only inputs and aggregate evidence')
    _check_run(client, record.run_id, value)
    if record.folds or value['folds'] or ev._formal_config(value['config']) != value['config']:
        raise ValueError('holdout full evaluation must have no fold children')
    if set(value['implementation_sha256']) != set(_sources(value)) or any(not ev._implementation_matches(value, name, value['implementation_sha256'][name]) for name in _sources(value)):
        raise ValueError('holdout scorer implementation drifted')
    params = client.get_run(record.run_id).data.params
    if params.get('sha256_holdout_scoring') != ev._sha256(artifact_root / 'execution.json'):
        raise ValueError('holdout actual scoring commitment is missing or drifted')
    for name in ('evaluation.yaml', 'summary.json', 'execution.json'):
        if ev._sha256(artifact_root / name) != params.get(f'sha256_{name}'):
            raise ValueError('holdout public evidence digest mismatch')
    evaluation = _json(artifact_root / 'evaluation.yaml')
    summary = _json(artifact_root / 'summary.json')
    receipt = _json(artifact_root / 'execution.json')
    if (evaluation != {**value, 'weights': {'full': receipt['weights']}}
        or set(summary) != {'sample_count', 'metrics', 'outcome', 'input_sha256'}
        or set(receipt) != {'schema_version', 'run_id', 'input_sha256', 'pre_registration_sha256', 'inference_sha256', 'summary', 'weights'} | ({'review_integrity', 'runtime_attestation', 'runtime_observation'} if _semantic(value) else set())
        or receipt['schema_version'] != 'tensile-holdout-score/v1' or receipt['run_id'] != record.run_id
        or receipt['input_sha256'] != _digest(value) or summary['input_sha256'] != _digest(value)
        or receipt['summary'] != summary or summary['sample_count'] != len(value['samples'])
        or receipt['pre_registration_sha256'] != value['authorization']['pre_registration_sha256']
        or receipt['inference_sha256'] != params.get('sha256_holdout_inference')
        or value['metric_definitions'] != _metric_definitions(value)
        or summary['metrics'] != dict(record.metrics)):
        raise ValueError('holdout aggregate execution evidence mismatch')
    if _semantic(value):
        _validate_runtime_evidence(value, receipt)
        integrity = receipt.get('review_integrity')
        if (not isinstance(integrity, dict) or set(integrity) != {'technical_isolation_verified', 'synthetic', 'real_model_deployment_verified', 'judge_sha256', 'exposed_sha256'}
            or any(type(integrity[k]) is not bool for k in ('technical_isolation_verified', 'synthetic', 'real_model_deployment_verified'))
            or not integrity['technical_isolation_verified']
            or any(not isinstance(integrity[k], str) or not re.fullmatch(r'[0-9a-f]{64}', integrity[k]) for k in ('judge_sha256', 'exposed_sha256'))):
            raise ValueError('holdout public review integrity schema invalid')
    outcome = _outcome(value, summary['metrics'])
    if record.outcome != outcome or summary['outcome'] != outcome:
        raise ValueError('holdout aggregate outcome mismatch')
    model = get_model(store, record.model_id)
    if ev._model_binding(model) != value['model'] or model.source_scope != 'full':
        raise ValueError('holdout registered model binding mismatch')
    used = receipt['weights']; kind = value['config']['artifact_kind']
    declared = model.artifacts['full'][kind]
    if used['model_artifact'] != declared or model.deploy_target != declared:
        raise ValueError('holdout evaluated deploy_target mismatch')
    files = _artifact_tree(_run_artifact_root(store, model.run_id) / declared.removeprefix('artifacts/'))
    if (kind == 'adapter' and (files != used['adapter_files'] or _artifact_tree(Path(model.base_model)) != used['model_files'])) or (kind == 'merged' and (files != used['model_files'] or used['adapter_files'] is not None)):
        raise ValueError('holdout evaluated weights drifted')
    authorization = Path(store.data_root) / 'releases' / value['data_version'] / 'authorization'
    _ordinary(authorization / 'consumed.yaml')
    validate_claim_consumed(authorization, ClaimIdentity(record.eval_id, record.model_id, record.data_version, record.split),
        value['authorization']['executor'], pre_registration_sha256=value['authorization']['pre_registration_sha256'])
    return {'version': record.eval_id, 'protocol': 'tensile-vlm/v4.1', 'state': 'sealed',
        'record_validity': record.record_validity, 'model_version': record.model_id,
        'mlflow_model_version': record.model_version_number, 'data_version': record.data_version,
        'split': record.split, 'model_scope': 'full', 'sample_count': summary['sample_count'],
        **({'scoring_protocol': 'semantic-holdout-v4.1',
            'semantic_rules_sha256': value['semantic_rules_sha256'],
            'blind_policy_sha256': value['blind_policy_sha256'],
            'review_integrity': receipt['review_integrity'],
            'runtime_attestation': receipt['runtime_attestation'],
            'runtime_observation': receipt['runtime_observation']} if _semantic(value) else {}),
        'outcome': record.outcome, 'run_id': record.run_id, 'input_sha256': _digest(value),
        'metrics': summary['metrics'], 'artifacts': {name: {'uri': f'runs:/{record.run_id}/{name}',
            'sha256': params[f'sha256_{name}']} for name in ('summary.json', 'execution.json')}}


def _semantic_input(value, samples):
    if not _semantic(value):
        return {}
    from finetune.eval_review import validate_semantic_holdout_config
    from finetune.eval_semantics import default_rules, rules_digest, freeze_blind_policy
    validate_semantic_holdout_config(value['config'])
    if set(value['config']['source_groups']) != {s['candidate_id'] for s in samples}:
        raise ValueError('holdout source groups must exactly cover every frozen media sample')
    source_groups = value['config']['source_groups']
    # A source video is indivisible, and specimen/group may merge several sources.
    sources = {}
    for sample in samples:
        group = source_groups[sample['candidate_id']]
        if sources.setdefault(sample['source_video'], group) != group:
            raise ValueError('holdout source video cannot cross bootstrap groups')
    return {'scoring_protocol': 'semantic-holdout-v4.1', 'semantic_rules': default_rules(),
        'semantic_rules_sha256': rules_digest(),
        'blind_policy_sha256': freeze_blind_policy(value['config']['blind_policy'])['sha256']}


def _review_context(root, eval_version):
    from versioning.backup import scoped_mlflow_client
    from versioning.mlflow_eval import open_eval_store
    value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version)
    if not _semantic(value):
        raise ValueError('independent review requires semantic-holdout-v4.1')
    _authorization(root, value, allow_consumed=True)
    private = _private(ev._formal_workspace(root, eval_version))
    inference = _json(private / 'inference.json', private=True)
    store = open_eval_store(Path(root) / 'workspace/mlflow')
    client = scoped_mlflow_client(tracking_uri=store.tracking_uri)
    run = _check_run(client, inference['run_id'], value)
    if (inference['input_sha256'] != _digest(value)
        or ev._sha256(private / 'inference.json') != run.data.params.get('sha256_holdout_inference')
        or ev._sha256(_ordinary(private / 'predictions.json', private=True)) != inference['predictions_sha256']):
        raise ValueError('holdout raw inference drift before review')
    if _semantic(value):
        _validate_runtime_evidence(value, inference)
    return value, private, inference, client


def prepare_holdout_review(*, root, eval_version, manual):
    """Prepare local anonymous package after real kernel canary probes.

    This entry does not call a model. Probes and any imported judgments in this
    engineering adapter remain synthetic evidence; production is blocked.
    """
    from finetune.eval_semantics import build_blind_package, extract_semantics
    from finetune.eval_review import probe_review_isolation, _profile, prepare_isolated_actor_requests
    from versioning.holdout import ClaimIdentity, mark_claim_exposed
    root = Path(root).absolute()
    workspace = ev._formal_workspace(root, eval_version)
    with _lock(workspace):
        value, private, inference, client = _review_context(root, eval_version)
        predictions = _json(private / 'predictions.json', private=True)
        if ([p.get('candidate_id') for p in predictions] != [s['candidate_id'] for s in value['samples']]
            or any(not _valid_prediction(value, p) for p in predictions)):
            raise ValueError('review requires complete frozen raw predictions')
        pending = _anonymous_pending(private, predictions, create=True)
        package, mapping = build_blind_package(pending, manual=_ordinary(manual).read_text(),
                                              policy=value['config']['blind_policy'])
        # The only receipt source is the actual deny-by-default subprocess probe.
        isolation = probe_review_isolation()
        package_path = private / 'anonymous-review.json'
        actors = [*value['config']['blind_policy']['participants'], value['config']['blind_policy']['arbiter']]
        isolation['contexts'] = {actor['id']: {
            'package_sha256': package['sha256'],
            'profile_sha256': hashlib.sha256(_profile(package_path, private / f"actor-requests-{index}.json").encode()).hexdigest()}
            for index, actor in enumerate(actors)}
        # Isolation receipt must be identical on same-content recovery; do not add timestamps.
        isolation['sha256'] = _digest({k: v for k, v in isolation.items() if k != 'sha256'})
        exposure = {'input_sha256': _digest(value), 'inference_sha256': ev._sha256(private / 'inference.json'),
            'predictions_sha256': inference['predictions_sha256'], 'package_sha256': package['sha256'],
            'blind_policy_sha256': value['blind_policy_sha256'], 'isolation': isolation,
            'anonymization_sha256': ev._sha256(private / 'review-anonymization.json')}
        identity = ClaimIdentity(eval_version, value['model']['model_id'], value['data_version'], value['config']['split'])
        authorization = root / 'data/releases' / value['data_version'] / 'authorization'
        mark_claim_exposed(authorization, identity, value['authorization']['executor'],
            pre_registration_sha256=value['authorization']['pre_registration_sha256'],
            input_sha256=_digest(value), predictions_sha256=inference['predictions_sha256'], package_sha256=package['sha256'])
        _save(private / 'exposure.json', exposure, private=True)
        client.log_param(inference['run_id'], 'sha256_holdout_exposure', ev._sha256(private / 'exposure.json'))
        _save(private / 'anonymous-mapping.json', mapping, private=True)
        # This is the first package publication. Exposure is already durable.
        _save(package_path, package, private=True)
        for index, actor in enumerate(actors):
            request_path = private / f'actor-requests-{index}.json'
            receipt_path = private / f'actor-worker-{index}.json'
            if not request_path.exists():
                receipt = prepare_isolated_actor_requests(package=package_path, output=request_path,
                    actor_id=actor['id'], policy=value['config']['blind_policy'])
                _save(receipt_path, receipt, private=True)
            receipt = _json(receipt_path, private=True)
            if receipt['result_sha256'] != ev._sha256(_ordinary(request_path, private=True)):
                raise ValueError('isolated actor request drift')
            client.log_param(inference['run_id'], f'sha256_holdout_worker_{index}', ev._sha256(receipt_path))
        return {'phase': 'exposed', 'package': str(package_path), 'synthetic': True,
                'real_model_deployment_verified': False, 'truth_accessed': False}


def _verified_exposure(private, value, inference):
    from finetune.eval_semantics import build_blind_package
    exposure = _json(private / 'exposure.json', private=True)
    package = _json(private / 'anonymous-review.json', private=True)
    payload = {k: v for k, v in package.items() if k != 'sha256'}
    from finetune.eval_semantics import content_digest, extract_semantics
    pending = _anonymous_pending(private, _json(private / 'predictions.json', private=True))
    rebuilt, mapping = build_blind_package(pending, manual=package['manual'], policy=value['config']['blind_policy'])
    isolation = exposure['isolation']
    if (package != rebuilt or mapping != _json(private / 'anonymous-mapping.json', private=True)
        or package['sha256'] != content_digest(payload)
        or exposure['input_sha256'] != _digest(value)
        or exposure['inference_sha256'] != ev._sha256(private / 'inference.json')
        or exposure['predictions_sha256'] != inference['predictions_sha256']
        or exposure['package_sha256'] != package['sha256']
        or exposure['blind_policy_sha256'] != value['blind_policy_sha256']
        or exposure['anonymization_sha256'] != ev._sha256(private / 'review-anonymization.json')
        or isolation.get('adapter_sha256') != ev._sha256(ev.ROOT / 'finetune/eval_review.py')
        or not isolation['technical_isolation_verified'] or not all(isolation['checks'].values())
        or isolation['sha256'] != _digest({k: v for k, v in isolation.items() if k != 'sha256'})):
        raise ValueError('anonymous review exposure integrity drift')
    from finetune.eval_review import _profile, _worker_executable
    from versioning.backup import scoped_mlflow_client
    from versioning.mlflow_eval import open_eval_store
    params = scoped_mlflow_client(tracking_uri=open_eval_store(private.parents[3] / 'workspace/mlflow').tracking_uri).get_run(inference['run_id']).data.params
    actors = [*value['config']['blind_policy']['participants'], value['config']['blind_policy']['arbiter']]
    for index, actor in enumerate(actors):
        receipt_path = private / f'actor-worker-{index}.json'
        request_path = private / f'actor-requests-{index}.json'
        receipt = _json(receipt_path, private=True)
        from versioning.backup import restored_review_profile_paths
        profile_package, profile_output = restored_review_profile_paths(private.parents[3], value,
            package=private / 'anonymous-review.json', output=request_path)
        expected_profile_sha256 = hashlib.sha256(_profile(profile_package, profile_output).encode()).hexdigest()
        if (params.get(f'sha256_holdout_worker_{index}') != ev._sha256(receipt_path)
            or receipt['actor_id'] != actor['id']
            or receipt['package_sha256'] != ev._sha256(private / 'anonymous-review.json')
            or receipt['policy_sha256'] != value['blind_policy_sha256']
            or receipt['result_sha256'] != ev._sha256(_ordinary(request_path, private=True))
            or receipt['profile_sha256'] != expected_profile_sha256
            or receipt['profile_sha256'] != isolation['contexts'][actor['id']]['profile_sha256']
            or receipt['executable_sha256'] != ev._sha256(_worker_executable())):
            raise ValueError('isolated actor worker receipt/request drift')
    return exposure


def seal_holdout_review(*, root, eval_version, blind_reviews):
    """Durably seal all judge attempts before any truth access; no inference."""
    from finetune.eval_semantics import extract_semantics
    root = Path(root).absolute()
    with _lock(ev._formal_workspace(root, eval_version)):
        value, private, inference, client = _review_context(root, eval_version)
        _verified_exposure(private, value, inference)
        reviews = _json(blind_reviews)
        if not isinstance(reviews, dict):
            raise ValueError('review import requires anonymous raw digest keyed evidence')
        predictions = _json(private / 'predictions.json', private=True)
        pending = {hashlib.sha256(p['raw_output'].encode()).hexdigest(): p['raw_output'] for p in predictions
                   if not extract_semantics(p['raw_output'], runtime_error=p.get('runtime_error'))['review_complete']}
        if set(reviews) != set(pending):
            raise ValueError('independent review must exactly cover pending frozen raw digests')
        complete = True
        for digest, raw in pending.items():
            evidence = reviews[digest]
            if evidence.get('policy') != value['config']['blind_policy']:
                raise ValueError('independent judge policy drift')
            # Human answers need a separate approved identity/permission adapter.
            if evidence.get('human') is not None:
                raise ValueError('human review is not authorized by this local adapter')
            complete &= extract_semantics(raw, blind_review=evidence)['review_complete']
        params = client.get_run(inference['run_id']).data.params
        renamed = {k.replace('sha256_holdout_review_attempt_', 'sha256_review_attempt_'): v
                   for k, v in params.items() if k.startswith('sha256_holdout_review_attempt_')}
        attempts, _ = ev._read_review_attempts(private, renamed, pending=reviews)
        repeat = bool(attempts and attempts[-1] == reviews)
        proposed = attempts if repeat else [*attempts, reviews]
        audit = ev._review_attempt_audit(proposed)
        if not repeat:
            attempt_path = private / 'review_attempts' / f'{len(proposed):04d}.json'
            _save(attempt_path, reviews, private=True)
            client.log_param(inference['run_id'], f'sha256_holdout_review_attempt_{len(proposed):04d}', ev._sha256(attempt_path))
        if not complete:
            raise ev.EvaluationReviewPending('independent judge attempt retained; only frozen infrastructure retry allowed')
        execution_proof = _review_execution_proof(private, value, inference, reviews, client)
        judge = {'input_sha256': _digest(value), 'inference_sha256': ev._sha256(private / 'inference.json'),
            'exposure_sha256': ev._sha256(private / 'exposure.json'), 'reviews': reviews, 'audit': audit,
            'execution_proof': execution_proof}
        _save(private / 'judge.json', judge, private=True)
        client.log_param(inference['run_id'], 'sha256_holdout_judge', ev._sha256(private / 'judge.json'))
        return {'phase': 'judge-sealed', 'truth_accessed': False, 'synthetic': execution_proof is None}


def _verified_judge(private, value, inference):
    _validate_runtime_evidence(value, inference)
    from versioning.backup import scoped_mlflow_client
    from versioning.mlflow_eval import open_eval_store
    exposure = _verified_exposure(private, value, inference)
    judge = _json(private / 'judge.json', private=True)
    root = private.parents[3]
    store = open_eval_store(root / 'workspace/mlflow')
    params = scoped_mlflow_client(tracking_uri=store.tracking_uri).get_run(inference['run_id']).data.params
    if (judge['input_sha256'] != _digest(value)
        or judge['inference_sha256'] != ev._sha256(private / 'inference.json')
        or judge['exposure_sha256'] != ev._sha256(private / 'exposure.json')
        or params.get('sha256_holdout_judge') != ev._sha256(private / 'judge.json')
        or params.get('sha256_holdout_exposure') != judge['exposure_sha256']):
        raise ValueError('holdout judge seal must precede truth access and remain bound')
    renamed = {k.replace('sha256_holdout_review_attempt_', 'sha256_review_attempt_'): v
               for k, v in params.items() if k.startswith('sha256_holdout_review_attempt_')}
    attempts, _ = ev._read_review_attempts(private, renamed)
    if not attempts or attempts[-1] != judge['reviews'] or ev._review_attempt_audit(attempts) != judge['audit']:
        raise ValueError('holdout judge attempt chain drift')
    import yaml
    exposed = root / 'data/releases' / value['data_version'] / 'authorization/exposed.yaml'
    registered = yaml.safe_load(_ordinary(exposed).read_bytes())
    if (registered['input_sha256'] != _digest(value) or registered['predictions_sha256'] != inference['predictions_sha256']
        or registered['package_sha256'] != exposure['package_sha256']):
        raise ValueError('irreversible prediction exposure record drift')
    proof = _review_execution_proof(private, value, inference, judge['reviews'],
        scoped_mlflow_client(tracking_uri=store.tracking_uri))
    if judge.get('execution_proof') != proof:
        raise ValueError('sealed judge execution provenance drift')
    return judge


def _score_records(private, value, inference, records):
    if not _semantic(value):
        return restricted_metrics(records)
    from finetune.eval_semantics import extract_semantics
    from finetune.eval_review import final_metrics
    judge = _verified_judge(private, value, inference)
    for row in records:
        digest = hashlib.sha256((row['raw_output'] or '').encode()).hexdigest()
        evidence = judge['reviews'].get(digest)
        if evidence is not None:
            row['blind_review'] = evidence
        row['source_group'] = value['config']['source_groups'][row['candidate_id']]
        row['semantics'] = extract_semantics(row['raw_output'], runtime_error=row['runtime_error'],
            rules=value['semantic_rules'], blind_review=evidence)
    return final_metrics(records)


def _review_integrity(private, value, inference):
    if not _semantic(value):
        return {}
    judge = _verified_judge(private, value, inference)
    exposure = _json(private / 'exposure.json', private=True)
    actual_execution = judge.get('execution_proof') is not None
    return {'review_integrity': {'technical_isolation_verified': exposure['isolation']['technical_isolation_verified'],
        'synthetic': not actual_execution,
        'real_model_deployment_verified': actual_execution,
        'judge_sha256': ev._sha256(private / 'judge.json'),
        'exposed_sha256': ev._sha256(private / 'exposure.json')},
        **_validated_runtime_evidence(value, inference)}


def _valid_prediction(value, prediction):
    if not isinstance(prediction, dict):
        return False
    if not _semantic(value):
        return set(prediction) == {'candidate_id', 'raw_output'} and isinstance(prediction['raw_output'], str)
    return (set(prediction) == {'candidate_id', 'raw_output', 'runtime_error'}
        and (isinstance(prediction['raw_output'], str) or prediction['raw_output'] is None)
        and (prediction['runtime_error'] is None or isinstance(prediction['runtime_error'], str))
        and (isinstance(prediction['raw_output'], str) or bool(prediction['runtime_error'])))


def read_restricted_holdout_summary(*, root, eval_version, actor):
    """Owner-only consumed aggregate view; never return raw, GT or per-sample rows."""
    root = Path(root).absolute()
    value, private, inference, client = _review_context(root, eval_version)
    authorization = value['config'].get('aggregate_authorization')
    if (not isinstance(authorization, dict)
        or authorization != {'actor': actor, 'role': 'acceptance-owner', 'os_uid': os.geteuid()}
        or private.stat().st_uid != os.geteuid()):
        raise ValueError('restricted aggregate requires an explicitly frozen acceptance-owner actor/OS identity')
    executor = value['authorization']['executor']
    from versioning.holdout import ClaimIdentity, validate_claim_consumed
    validate_claim_consumed(root / 'data/releases' / value['data_version'] / 'authorization',
        ClaimIdentity(eval_version, value['model']['model_id'], value['data_version'], value['config']['split']),
        executor, pre_registration_sha256=value['authorization']['pre_registration_sha256'])
    receipt = _json(private / 'scoring.json', private=True)
    params = client.get_run(inference['run_id']).data.params
    if params.get('sha256_holdout_scoring') != ev._sha256(private / 'scoring.json'):
        raise ValueError('restricted report requires a committed score')
    _verify_private_scoring(private, value, inference, receipt)
    summary = _json(private / 'metrics.json', private=True)
    support = {key: value for key, value in summary['support'].items()
               if key in ('total', 'clip_state', 'fracture_mechanism', 'fracture_site',
                          'special_case', 'independent_group_count', 'missing_group_mapping')}
    return {'scoring_protocol': value['scoring_protocol'], 'eval_version': eval_version,
        'tuning_use': 'forbidden', 'metrics': summary['metrics'], 'support': support,
        'diagnostics': summary['diagnostics'], 'confidence_intervals': summary['confidence_intervals']}


def run_holdout_review(*, root, eval_version, allow_real_model_calls=False, broker=None):
    """Controlled local broker path. Default invocation cannot call a real model.

    A started run never silently reruns after interruption: saved immutable
    attempt/worker evidence is imported through review_seal under the same identity.
    """
    from finetune.eval_review import LocalOllamaBroker, run_review_broker
    root = Path(root).absolute()
    workspace = ev._formal_workspace(root, eval_version)
    with _lock(workspace):
        value, private, inference, client = _review_context(root, eval_version)
        _verified_exposure(private, value, inference)
        from versioning.backup import restored_review_profile_paths
        historic_package, _ = restored_review_profile_paths(root, value,
            package=private / 'anonymous-review.json', output=private / 'actor-requests-0.json')
        if historic_package != private / 'anonymous-review.json':
            raise ValueError('restored exposed review may only import existing seals/score; new execution needs a fresh verified environment receipt')
        if broker is None:
            if not allow_real_model_calls:
                raise ValueError('real local judge deployment/tokenizer not verified or execution not authorized; no model call permitted')
            broker = _verified_local_broker(root, value, private, inference, client)
        elif not getattr(broker, 'synthetic', False):
            raise ValueError('caller-supplied real broker is not a verified frozen local provider')
        marker = private / 'broker-started.json'
        if marker.exists():
            raise ValueError('broker already started; recover sealed attempts without repeating judgments')
        _save(marker, {'input_sha256': _digest(value), 'inference_sha256': ev._sha256(private / 'inference.json'),
            'exposure_sha256': ev._sha256(private / 'exposure.json'), 'synthetic': bool(broker.synthetic),
            **({'deployment_sha256': ev._sha256(private / 'review-deployment.json')} if not broker.synthetic else {})}, private=True)
        client.log_param(inference['run_id'], 'sha256_holdout_broker_started', ev._sha256(marker))
        actors = [*value['config']['blind_policy']['participants'], value['config']['blind_policy']['arbiter']]
        requests = {actor['id']: private / f'actor-requests-{index}.json' for index, actor in enumerate(actors)}
        def commit(name, payload):
            path = private / name
            _save(path, payload, private=True)
            key = name.replace('/', '_').replace('.', '_')
            client.log_param(inference['run_id'], 'sha256_holdout_' + key, ev._sha256(path))
        attempts = run_review_broker(package=private / 'anonymous-review.json', actor_requests=requests,
            policy=value['config']['blind_policy'], broker=broker,
            on_started=lambda payload: commit(f"broker_calls/{payload['sequence']:04d}-started.json", payload),
            on_judgment=lambda payload: commit(f"broker_calls/{payload['sequence']:04d}-sealed.json", payload),
            on_attempt=lambda index, payload: commit(f'broker_attempts/{index:04d}.json', payload))
    result = None
    for index in range(1, len(attempts) + 1):
        try:
            result = seal_holdout_review(root=root, eval_version=eval_version,
                blind_reviews=private / 'broker_attempts' / f'{index:04d}.json')
        except ev.EvaluationReviewPending:
            result = {'phase': 'review-incomplete', 'synthetic': True, 'truth_accessed': False}
    return result


def _anonymous_pending(private, predictions, *, create=False):
    """A private frozen nonce prevents public manifest order revealing the map."""
    import hmac
    from finetune.eval_semantics import extract_semantics
    path = private / 'review-anonymization.json'
    if create and not path.exists():
        _save(path, {'nonce': os.urandom(32).hex()}, private=True)
    value = _json(path, private=True)
    if set(value) != {'nonce'} or not isinstance(value['nonce'], str) or not re.fullmatch('[0-9a-f]{64}', value['nonce']):
        raise ValueError('review anonymization nonce drift')
    pending = [row for row in predictions if not extract_semantics(row['raw_output'],
        runtime_error=row.get('runtime_error'))['review_complete']]
    key = bytes.fromhex(value['nonce'])
    pending.sort(key=lambda row: hmac.new(key, row['candidate_id'].encode(), hashlib.sha256).digest())
    return {row['candidate_id']: row['raw_output'] for row in pending}


def _runtime_library_versions():
    from importlib.metadata import version
    return {name + '_version': version(name) for name in ('llamafactory', 'transformers')}


def _collect_loaded_runtime(processor, model, value):
    """Read actual loaded model/runtime properties; never load or infer a model here."""
    from versioning.performance import validate_loaded_runtime
    from finetune.validation.constants import GENERATION_CONFIG, VIDEO_MAX_FRAMES
    config = value['config']
    actual = validate_loaded_runtime(model, config)
    versions = _runtime_library_versions()
    variant = {'dtype': actual['runtime_dtype'], **versions,
        'preprocessing_sha256': ev._sha256(ev.ROOT / 'pipeline/preprocessing/minicpm_preprocessor.py')}
    if actual['quantization_bit'] == 4:
        variant['quantization'] = actual['quantization']
    mapping = getattr(model, 'hf_device_map', None)
    actual_devices = {actual['runtime_device']}
    if mapping:
        actual_devices = {f'cuda:{item}' if type(item) is int else str(item) for item in mapping.values()}
    if not actual_devices or any(not item.startswith('cuda:') or not item[5:].isdigit() for item in actual_devices):
        raise ValueError('loaded quality GPU placement cannot be attested')
    frames = {}
    for name, target in (('processor', processor), ('image_processor', getattr(processor, 'image_processor', None)),
                         ('video_processor', getattr(processor, 'video_processor', None)), ('processor_config', getattr(processor, 'config', None))):
        if target is not None:
            for attribute in ('max_frames', 'video_maxlen'):
                observed = getattr(target, attribute, None)
                if observed is not None:
                    if type(observed) is not int or observed != VIDEO_MAX_FRAMES:
                        raise ValueError('loaded processor frame limit differs from frozen quality runtime')
                    frames[name + '.' + attribute] = observed
    evidence = {'runtime_attestation': {'runtime_variant': variant,
        'device': {'runtime_device': actual['runtime_device'], 'gpu_count': len(actual_devices)},
        'quantization_bit': actual['quantization_bit']},
        'runtime_observation': {'loaded_runtime': actual,
            'generation': {**GENERATION_CONFIG, 'video_max_frames': VIDEO_MAX_FRAMES},
            'frame_loader_limit': VIDEO_MAX_FRAMES, 'processor_frame_limits': frames,
            'processor_class': processor.__class__.__module__ + '.' + processor.__class__.__name__,
            'model_devices': sorted(actual_devices)}}
    _validate_runtime_evidence(value, evidence)
    return evidence


def _validate_runtime_evidence(value, evidence):
    config = value['config']
    expected = {key: config[key] for key in ('runtime_variant', 'device', 'quantization_bit')}
    observation = evidence.get('runtime_observation')
    if evidence.get('runtime_attestation') != expected or not isinstance(observation, dict):
        raise ValueError('quality actual runtime attestation differs from frozen delivery variant')
    variant = expected['runtime_variant']
    loaded = {'runtime_device': config['device']['runtime_device'], 'runtime_dtype': variant['dtype'],
        'quantization_bit': config['quantization_bit'], 'quantization': variant.get('quantization')}
    if (set(observation) != {'loaded_runtime', 'generation', 'frame_loader_limit', 'processor_frame_limits', 'processor_class', 'model_devices'}
        or observation['loaded_runtime'] != loaded or observation['generation'] != config['generation']
        or observation['frame_loader_limit'] != config['generation']['video_max_frames']
        or not isinstance(observation['processor_frame_limits'], dict)
        or any(type(number) is not int or number != observation['frame_loader_limit'] for number in observation['processor_frame_limits'].values())
        or not isinstance(observation['processor_class'], str) or not observation['processor_class']
        or not isinstance(observation['model_devices'], list) or len(set(observation['model_devices'])) != config['device']['gpu_count']
        or config['device']['runtime_device'] not in observation['model_devices']):
        raise ValueError('quality loaded runtime/frame/generation observation drift')
    return evidence


def _validated_runtime_evidence(value, inference):
    _validate_runtime_evidence(value, inference)
    return {key: inference[key] for key in ('runtime_attestation', 'runtime_observation')}


def _review_deployment_binding(value, private, inference):
    return {'input_sha256': _digest(value), 'inference_sha256': ev._sha256(private / 'inference.json'),
        'package_sha256': ev._sha256(private / 'anonymous-review.json'),
        'exposure_sha256': ev._sha256(private / 'exposure.json'),
        'blind_policy_sha256': value['blind_policy_sha256'],
        'worker_receipts': [ev._sha256(private / f'actor-worker-{index}.json')
            for index in range(len(value['config']['blind_policy']['participants']) + 1)]}


def verify_holdout_review_deployment(*, root, eval_version, allow_local_metadata=False,
                                     transport=None, tokenizer_factory=None):
    """Verify explicitly frozen local deployment without sending raw or inference.

    Injected providers always yield synthetic evidence. The default provider uses
    approved loopback metadata, complete local tokenizer bytes and locked package
    implementations, with local_files_only=True and trust_remote_code=False.
    """
    from finetune.eval_review_deployment import verify_local_deployment
    from versioning.backup import restored_review_profile_paths
    root = Path(root).absolute()
    with _lock(ev._formal_workspace(root, eval_version)):
        value, private, inference, client = _review_context(root, eval_version)
        _verified_exposure(private, value, inference)
        original, _ = restored_review_profile_paths(root, value,
            package=private / 'anonymous-review.json', output=private / 'actor-requests-0.json')
        if original != private / 'anonymous-review.json':
            raise ValueError('a restored exposed environment needs a new execution environment registration')
        sources = value['config'].get('review_tokenizers')
        evidence, _ = verify_local_deployment(sources=sources,
            binding=_review_deployment_binding(value, private, inference),
            allow_local_metadata=allow_local_metadata, transport=transport, tokenizer_factory=tokenizer_factory)
        path = private / 'review-deployment.json'
        _save(path, evidence, private=True)
        client.log_param(inference['run_id'], 'sha256_holdout_deployment', ev._sha256(path))
        return {'phase': 'deployment-verified', 'synthetic': evidence['synthetic'],
            'real_model_deployment_verified': evidence['real_model_deployment_verified'],
            'truth_accessed': False, 'model_inference_performed': False}


def _verified_local_broker(root, value, private, inference, client):
    from finetune.eval_review import LocalOllamaBroker
    from finetune.eval_review_deployment import verify_local_deployment
    path = private / 'review-deployment.json'
    if not path.exists():
        raise ValueError('real local judge deployment/tokenizer not verified; no model call permitted')
    saved = _json(path, private=True)
    params = client.get_run(inference['run_id']).data.params
    if (params.get('sha256_holdout_deployment') != ev._sha256(path)
        or saved.get('synthetic') is not False or saved.get('real_model_deployment_verified') is not True):
        raise ValueError('synthetic or uncommitted deployment evidence cannot authorize real judging')
    actual, counter = verify_local_deployment(sources=value['config'].get('review_tokenizers'),
        binding=_review_deployment_binding(value, private, inference), allow_local_metadata=True)
    if actual != saved:
        raise ValueError('real local deployment assets/model/profile differ from frozen verified receipt')
    return LocalOllamaBroker(allow_real_model_calls=True, token_counter=counter)


def _review_execution_proof(private, value, inference, reviews, client):
    marker_path = private / 'broker-started.json'
    if not marker_path.exists():
        return None
    marker = _json(marker_path, private=True)
    if marker.get('synthetic') is not False:
        return None
    params = client.get_run(inference['run_id']).data.params
    deployment_path = private / 'review-deployment.json'
    deployment = _json(deployment_path, private=True)
    if (params.get('sha256_holdout_broker_started') != ev._sha256(marker_path)
        or params.get('sha256_holdout_deployment') != ev._sha256(deployment_path)
        or marker.get('deployment_sha256') != ev._sha256(deployment_path)
        or marker.get('input_sha256') != _digest(value)
        or marker.get('inference_sha256') != ev._sha256(private / 'inference.json')
        or marker.get('exposure_sha256') != ev._sha256(private / 'exposure.json')
        or deployment.get('synthetic') is not False or deployment.get('real_model_deployment_verified') is not True
        or deployment.get('binding') != _review_deployment_binding(value, private, inference)):
        raise ValueError('actual local judge execution/deployment commitment drift')
    digest = _digest(reviews)
    attempts = [key for key in params if key.startswith('sha256_holdout_broker_attempts_') and params[key] == digest]
    if not attempts:
        raise ValueError('real judge answers must originate from a committed controlled broker attempt')
    return {'broker_started_sha256': ev._sha256(marker_path), 'deployment_sha256': ev._sha256(deployment_path),
            'broker_attempt_sha256': digest}
