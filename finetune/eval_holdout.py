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

SOURCES = ('finetune/holdout_metrics.py', 'finetune/eval_holdout.py', 'finetune/eval_run.py', 'finetune/v4_1_runtime.py',
    'pipeline/v4_1_labels.py', 'finetune/validation/model_runtime.py',
    'finetune/validation/constants.py', 'finetune/validation/video_loader.py',
    'pipeline/preprocessing/minicpm_preprocessor.py')
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
                        pre_registration=None, executor=None):
    from versioning.ids import parse_eval_id, parse_model_id, parse_data_id
    from versioning.data_release import load_release_metadata
    from versioning.holdout import validate_holdout_layout
    from versioning.registry import open_registry_store, validate_model_for_evaluation, _run_artifact_root
    from versioning.prompts import load_prompt, parse_prompt_definition
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
    prompt = parse_prompt_definition(yaml.safe_load((training_root / 'prompt.yaml').read_text()))
    if prompt != load_prompt(root, model.prompt_version):
        raise ValueError('holdout model training Prompt drifted')
    contract, _ = ev._load_contract()
    from finetune.validation.constants import GENERATION_CONFIG, VIDEO_MAX_FRAMES
    if {**GENERATION_CONFIG, 'video_max_frames': VIDEO_MAX_FRAMES} != ev.FORMAL_GENERATION:
        raise ValueError('holdout generation implementation drifted')
    return {**value, 'model': ev._model_binding(model), 'git_commit': git_commit,
        'inputs_path': None, 'media_root': str(Path(media_root).absolute()),
        'data_binding': {'release_sha256': ev._sha256(release / 'release.yaml'),
            'manifest_sha256': ev._sha256(manifest_path), 'media': media}, 'folds': [], 'samples': samples,
        'prompt': {'version': prompt.version, 'system_prompt': prompt.system_prompt,
            'user_prompt': prompt.user_prompt, 'output_fields': list(prompt.output_fields)},
        'contract_hash': contract['contract_hash'], 'metric_definitions': METRIC_DEFINITIONS,
        'implementation_sha256': {name: ev._sha256(ev.ROOT / name) for name in SOURCES}}


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
        for sample in value['samples']:
            result = ev.run_model_on_video_detailed(model, processor,
                Path(value['media_root']) / sample['video_path'], value['prompt']['user_prompt'],
                system_prompt=value['prompt']['system_prompt'])
            predictions.append({'candidate_id': sample['candidate_id'], 'raw_output': result.raw_output})
    finally:
        del processor, model
        import gc
        gc.collect()
    return predictions


def execute_holdout_inference(*, root, eval_version):
    from mlflow.tracking import MlflowClient
    from versioning.registry import open_registry_store, materialize_model
    from versioning.mlflow_eval import open_eval_store, create_eval_run, transition_eval_state
    root = Path(root).absolute()
    value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version)
    workspace = ev._formal_workspace(root, eval_version)
    with _lock(workspace):
        value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version)
        prereg = _authorization(root, value)
        private = _private(workspace)
        if any(private.iterdir()):
            raise ValueError('existing holdout inference requires same-run scoring/recovery, never reinference')
        store = open_eval_store(root / 'workspace/mlflow')
        parent = create_eval_run(store, eval_version, model_id=value['model']['model_id'],
            model_version_number=value['model']['version'], data_version=value['data_version'],
            config=f'sha256:{_digest(value)}', git_commit=value['git_commit'], scope='full',
            split=value['config']['split'], data_root=root / 'data', pre_registration=prereg,
            executor=value['authorization']['executor'])
        client = MlflowClient(tracking_uri=store.tracking_uri)
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
                ev.verify_versioned_evaluation(root=root, eval_version=eval_version)
                predictions = _infer(value, base, adapter)
                ev.verify_versioned_evaluation(root=root, eval_version=eval_version)
                if ev._weight_inventory(base) != weights['model_files'] or (adapter and ev._weight_inventory(adapter) != weights['adapter_files']):
                    raise ValueError('holdout loaded weights drifted')
            _save(private / 'predictions.json', predictions, private=True)
            receipt = {'run_id': parent.run_id, 'input_sha256': _digest(value),
                'predictions_sha256': ev._sha256(private / 'predictions.json'), 'weights': weights}
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
        if (set(prediction) != {'candidate_id', 'raw_output'} or prediction['candidate_id'] != sample['candidate_id']
            or not isinstance(prediction['raw_output'], str)):
            raise ValueError('holdout actual prediction identity mismatch')
        target = truth['labels'][sample['candidate_id']]
        if not validate_v4_1_labels(target).valid:
            raise ValueError('holdout actual truth contract mismatch')
        parsed, error = None, None
        try:
            parsed = ev.parse_v4_1_output(prediction['raw_output'])
        except ev.V4_1FinetuneError as exc:
            error = str(exc)
        expected.append({**sample, 'target': target, **prediction, 'prediction': parsed,
            'strict_valid': parsed is not None, 'parse_error': error, 'runtime_error': None,
            'scores': ev.score_v4_1_prediction(target, parsed)})
    if _json(private / 'scored-records.json', private=True) != expected:
        raise ValueError('holdout actual per-sample scoring mismatch')
    actual_metrics = restricted_metrics(expected)
    if _json(private / 'metrics.json', private=True) != actual_metrics:
        raise ValueError('holdout private metric evidence mismatch')
    metrics = public_gates(actual_metrics, value['config']['thresholds'])
    outcome = gate_outcome(metrics)
    if receipt['summary'] != {'sample_count': len(expected), 'metrics': metrics,
        'outcome': outcome, 'input_sha256': _digest(value)}:
        raise ValueError('holdout actual aggregate scoring mismatch')


def score_holdout_evaluation(*, root, eval_version, executor):
    from mlflow.tracking import MlflowClient
    from versioning.mlflow_eval import open_eval_store, log_eval_summary, transition_eval_state
    from pipeline.v4_1_labels import validate_v4_1_labels
    root = Path(root).absolute()
    workspace = ev._formal_workspace(root, eval_version)
    value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version)
    if value['config']['scope'] != 'full' or executor != value['authorization']['executor']:
        raise ValueError('holdout scoring executor mismatch')
    with _lock(workspace):
        value = ev.verify_versioned_evaluation(root=root, eval_version=eval_version)
        prereg = _authorization(root, value, allow_consumed=True)
        private = _private(workspace)
        inference = _json(private / 'inference.json', private=True)
        store = open_eval_store(root / 'workspace/mlflow')
        client = MlflowClient(tracking_uri=store.tracking_uri)
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
                    or any(not isinstance(p, dict) or set(p) != {'candidate_id', 'raw_output'} or not isinstance(p['raw_output'], str)
                        or p['candidate_id'] != s['candidate_id'] for p, s in zip(predictions, value['samples']))):
                    raise ValueError('holdout predictions do not cover the frozen media input')
                # Durable access record is published before any truth bytes are read.
                _save(private / 'truth-access.json', {'run_id': run.info.run_id, 'input_sha256': _digest(value),
                    'executor': executor, 'pre_registration_sha256': value['authorization']['pre_registration_sha256']}, private=True)
                truth_path = root / 'data/releases' / value['data_version'] / 'sealed_ground_truth/labels.json'
                truth = _json(truth_path, private=True)
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
                        parsed = ev.parse_v4_1_output(prediction['raw_output'])
                    except ev.V4_1FinetuneError as exc:
                        error = str(exc)
                    records.append({**sample, 'target': target, **prediction, 'prediction': parsed,
                        'strict_valid': parsed is not None, 'parse_error': error, 'runtime_error': None,
                        'scores': ev.score_v4_1_prediction(target, parsed)})
                actual_metrics = restricted_metrics(records)
                metrics = public_gates(actual_metrics, value['config']['thresholds'])
                outcome = gate_outcome(metrics)
                _save(private / 'metrics.json', actual_metrics, private=True)
                public = {'sample_count': len(records), 'metrics': metrics, 'outcome': outcome,
                    'input_sha256': _digest(value)}
                _save(private / 'scored-records.json', records, private=True)
                _save(receipt_path, {'schema_version': 'tensile-holdout-score/v1', 'run_id': run.info.run_id,
                    'input_sha256': _digest(value), 'pre_registration_sha256': value['authorization']['pre_registration_sha256'],
                    'inference_sha256': ev._sha256(private / 'inference.json'),
                    'summary': public, 'weights': inference['weights']}, private=True)
                # No truth bytes, hashes, predictions or per-sample scores are public.
            receipt = _json(receipt_path, private=True)
            if (receipt['run_id'] != run.info.run_id or receipt['input_sha256'] != _digest(value)
                or receipt['pre_registration_sha256'] != value['authorization']['pre_registration_sha256']
                or receipt['inference_sha256'] != ev._sha256(private / 'inference.json')
                or receipt['weights'] != inference['weights']):
                raise ValueError('holdout scoring receipt binding mismatch')
            if (set(receipt) != {'schema_version', 'run_id', 'input_sha256', 'pre_registration_sha256',
                'inference_sha256', 'summary', 'weights'} or receipt['schema_version'] != 'tensile-holdout-score/v1'):
                raise ValueError('holdout scoring receipt schema mismatch')
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
                if _json(source_truth, private=True) != _json(private / 'truth-snapshot.json', private=True):
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
    from mlflow.tracking import MlflowClient
    from versioning.registry import _artifact_tree, _run_artifact_root, get_model
    from versioning.holdout import ClaimIdentity, validate_claim_consumed
    client = MlflowClient(tracking_uri=store.tracking_uri)
    if set(_artifact_tree(artifact_root)) != PUBLIC_FILES:
        raise ValueError('holdout public artifacts must contain only inputs and aggregate evidence')
    _check_run(client, record.run_id, value)
    if record.folds or value['folds'] or ev._formal_config(value['config']) != value['config']:
        raise ValueError('holdout full evaluation must have no fold children')
    if set(value['implementation_sha256']) != set(SOURCES) or any(ev._sha256(ev.ROOT / name) != value['implementation_sha256'][name] for name in SOURCES):
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
        or set(receipt) != {'schema_version', 'run_id', 'input_sha256', 'pre_registration_sha256', 'inference_sha256', 'summary', 'weights'}
        or receipt['schema_version'] != 'tensile-holdout-score/v1' or receipt['run_id'] != record.run_id
        or receipt['input_sha256'] != _digest(value) or summary['input_sha256'] != _digest(value)
        or receipt['summary'] != summary or summary['sample_count'] != len(value['samples'])
        or receipt['pre_registration_sha256'] != value['authorization']['pre_registration_sha256']
        or receipt['inference_sha256'] != params.get('sha256_holdout_inference')
        or value['metric_definitions'] != METRIC_DEFINITIONS
        or summary['metrics'] != dict(record.metrics)):
        raise ValueError('holdout aggregate execution evidence mismatch')
    outcome = gate_outcome(summary['metrics'])
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
        'outcome': record.outcome, 'run_id': record.run_id, 'input_sha256': _digest(value),
        'metrics': summary['metrics'], 'artifacts': {name: {'uri': f'runs:/{record.run_id}/{name}',
            'sha256': params[f'sha256_{name}']} for name in ('summary.json', 'execution.json')}}
