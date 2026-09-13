"""Synthetic test-branch processing and review; no real test data accessed."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from versioning import data_pipeline as dp
from versioning import holdout_pipeline as hp
from tests.versioning.test_data_pipeline import (
    pinned_inputs, source_inputs, roi_inputs, media_inputs, media_runtime,
    _save_pinned, _source_probe, _review_return,
)
from tests.versioning.test_cli_holdout import _release


@pytest.fixture
def test_branch(media_inputs, media_runtime, tmp_path, monkeypatch):
    path, doc, project, rewrite = media_inputs
    split = json.loads((project / doc['split']['path']).read_text())
    split['splits'] = {name: (['video_0001'] if name == 'test' else []) for name in split['splits']}
    rewrite(doc['split'], json.dumps(split).encode())
    media = json.loads((project / doc['media']['config']['path']).read_text())
    for key, ids in [('development_reference', []), ('test_reference', ['video_0001'])]:
        ref = json.loads((project / media[key]['path']).read_text())
        ref['source_inventory'] = ids
        rewrite(media[key], json.dumps(ref).encode())
    rewrite(doc['media']['config'], json.dumps(media).encode()); _save_pinned(path, doc)
    root = tmp_path / 'store'
    _release(root, 'data-v4.1-r2', 'development')
    train = root / 'data/releases/data-v4.1-r2'
    train.chmod(0o700); (train / 'payload').mkdir(mode=0o700)
    (train / 'payload/metadata').mkdir()
    (train / 'payload/metadata/training_candidates.json').write_text(json.dumps({
        'version': 'data-v4.1-r2', 'candidates': [{'source_video': 'video_0002'}]}))
    config = {'schema': 'tensile-data/holdout-build/v1', 'batch': 'batch-001',
        'inputs_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'development_data_version': 'data-v4.1-r2',
        'development_release_sha256': hashlib.sha256((train / 'release.yaml').read_bytes()).hexdigest()}
    for field, source in [('development_sources', 'video_0002'), ('used_test_sources', 'video_0003')]:
        file = project / (field + '.json')
        file.write_text(json.dumps({'schema': 'tensile-data/source-isolation/v1', 'scope': field,
            'sources': {source: hashlib.sha256(source.encode()).hexdigest()}, 'reviewer_id': 'fixture',
            'reviewed_at': '2026-09-13T12:00:00+08:00', 'reference': 'synthetic source audit'}))
        config[field] = {'path': file.name, 'size_bytes': file.stat().st_size,
                         'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
    config_path = project / 'test-config.json'; config_path.write_text(json.dumps(config))
    original = dp.run_input_source
    monkeypatch.setattr(dp, 'run_input_source', lambda root, **kw: original(root, **kw, probe=_source_probe))
    def run(stage, **kw):
        return hp.run_holdout_stage(root, stage, inputs_path=path, batch='batch-001', config_path=config_path, **kw)
    return root, path, config_path, run


def reviewed_test(test_branch, tmp_path):
    root, path, config, run = test_branch
    for stage in ('source', 'roi', 'subvideo'):
        run(stage)
    package = run('review_export').outputs[0]
    result = tmp_path / 'review.json'; _review_return(package, result); result.chmod(0o600)
    run('review_import', results_path=result)
    return run, package, result


def test_seven_stages_and_idempotent_publish(test_branch, tmp_path):
    root, path, config, run = test_branch
    run, package, result = reviewed_test(test_branch, tmp_path)
    queue = json.loads((package / 'review_queue.json').read_text())
    assert set(queue['candidate_inventory']) == {r['candidate_id'] for r in queue['candidates']}
    assert all(r['scope'] == 'test_audit' for r in queue['candidates'])
    output = run('release', version='data-v4.1-r3').outputs[0]
    assert hp.validate_public_build(output)
    assert run('release_validate', version='data-v4.1-r3').report['passed']
    original = hp._inventory(output)
    run('release', version='data-v4.1-r3')
    assert hp._inventory(output) == original
    assert not list((output / 'authorization').iterdir())
    for file in (output / 'sealed_ground_truth').rglob('*'):
        assert file.stat().st_mode & 0o077 == 0
    assert all('clip_state' not in p.read_text() for p in (output / 'evaluation_inputs').rglob('*.json'))
    assert (root / 'data/test_working').stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('overlap', ['identity', 'content'])
def test_source_overlap_refused_before_working_write(test_branch, overlap):
    root, path, config_path, run = test_branch
    config = json.loads(config_path.read_text())
    file = config_path.parent / config['used_test_sources']['path']; doc = json.loads(file.read_text())
    inputs = dp.load_data_inputs(path, batch='batch-001')
    doc['sources'] = ({'video_0001': 'a'*64} if overlap == 'identity' else {'video_0003': inputs.videos[0].file.sha256})
    file.write_text(json.dumps(doc)); config['used_test_sources'].update(size_bytes=file.stat().st_size, sha256=dp._sha256_file(file))
    config_path.write_text(json.dumps(config))
    with pytest.raises(dp.StageInputError, match='重叠'):
        run('source')
    assert not (root / 'data/test_working').exists()


def test_missing_review_and_public_result_rejected(test_branch, tmp_path):
    root, _, _, run = test_branch
    for stage in ('source', 'roi', 'subvideo'):
        run(stage)
    package = run('review_export').outputs[0]
    result = tmp_path / 'review.json'; payload = _review_return(package, result)
    result.chmod(0o644)
    with pytest.raises(dp.ReviewGateError, match='owner-only'):
        run('review_import', results_path=result)
    result.chmod(0o600); payload['review']['decisions'].pop(); result.write_text(json.dumps(payload))
    with pytest.raises(dp.ReviewGateError):
        run('review_import', results_path=result)
    assert not (root / 'data/releases/data-v4.1-r3').exists()


def test_public_validation_does_not_open_truth(test_branch, tmp_path, monkeypatch):
    run, _, _ = reviewed_test(test_branch, tmp_path)
    output = run('release', version='data-v4.1-r3').outputs[0]
    old = dp._read_pinned_document
    def guarded(ref):
        assert 'sealed_ground_truth' not in ref.path.parts
        return old(ref)
    monkeypatch.setattr(dp, '_read_pinned_document', guarded)
    assert hp.validate_public_build(output)
    file = output / 'media' / next(iter(hp._inventory(output)['media']))
    file.chmod(0o600); file.write_bytes(b'drift')
    with pytest.raises(dp.StageInputError, match='漂移'):
        hp.validate_public_build(output)


def test_built_release_feeds_final_model_test(test_branch, tmp_path, monkeypatch):
    """Build actual branch output, then claim/infer/score using synthetic model."""
    from tests import test_full_training as ft
    from tests.test_train_with_contract import _versioned_data_fixture
    from versioning.data_release import seal_payload
    from versioning.migration import _release_content_digest
    from pipeline.v4_1_review_workflow import new_decision
    from pipeline.v4_1_review_decisions import build_review_payload
    from finetune import eval_run as ev
    from finetune.eval_holdout import score_holdout_evaluation
    from finetune.holdout_metrics import THRESHOLDS, FOUR_STATES
    from versioning.cli import main
    from types import SimpleNamespace
    def model_data(directory):
        root, media, release, rows = _versioned_data_fixture(directory)
        for folder in (release, *release.rglob('*')):
            if folder.is_dir(): folder.chmod(0o700)
        for file in (release / 'datasets').rglob('*.json'):
            file.chmod(0o600); file.write_text(file.read_text().replace('video_000', 'video_100'))
        for file in media.rglob('*.mp4'):
            file.rename(file.with_name(file.name.replace('video_000', 'video_100')))
        (release / 'payload/metadata').mkdir(parents=True)
        (release / 'payload/metadata/training_candidates.json').write_text(json.dumps({
            'version': 'data-v4.1-r2', 'candidates': [{'source_video': f'video_100{i}'} for i in range(3)]}))
        seal_payload(release)
        receipt = root / 'migration_receipts/data-v4.1-r2.receipt.yaml'
        value = yaml.safe_load(receipt.read_text()); value['target_release_digest'] = _release_content_digest(release)
        receipt.write_text(yaml.safe_dump(value))
        return root, media, release, rows
    monkeypatch.setattr(ft, '_versioned_data_fixture', model_data)
    model_tmp = tmp_path / 'final-model'; model_tmp.mkdir()
    root, registry, model = ft.full_model(model_tmp, monkeypatch)
    _, inputs, config_path, _ = test_branch
    config = json.loads(config_path.read_text())
    file = config_path.parent / config['development_sources']['path']
    inv = json.loads(file.read_text()); inv['sources'] = {f'video_100{i}': hashlib.sha256(str(i).encode()).hexdigest() for i in range(3)}
    file.write_text(json.dumps(inv)); config['development_sources'].update(size_bytes=file.stat().st_size, sha256=dp._sha256_file(file))
    config['development_release_sha256'] = dp._sha256_file(root / 'data/releases/data-v4.1-r2/release.yaml')
    config_path.write_text(json.dumps(config))
    def run(stage, **kw):
        return hp.run_holdout_stage(root, stage, inputs_path=inputs, batch='batch-001', config_path=config_path, **kw)
    for stage in ('source', 'roi', 'subvideo'): run(stage)
    package = run('review_export').outputs[0]
    queue = json.loads((package / 'review_queue.json').read_text())
    assert len(queue['candidates']) >= 4
    decisions = []
    for i, row in enumerate(queue['candidates']):
        labels = {'clip_state': FOUR_STATES[i % 4], 'fracture_mechanism': None, 'fracture_site': None, 'special_case': None}
        decisions.append(new_decision(row, status='approved' if labels == row['candidate_v4_labels'] else 'corrected',
            corrected_labels=None if labels == row['candidate_v4_labels'] else labels,
            historical_suggested_labels=None, historical_reference_ids=[], reviewer_notes='synthetic annotation',
            reviewer_id='fixture', reviewed_at='2026-09-13T12:00:00+08:00'))
    result = tmp_path / 'final-review.json'
    result.write_text(json.dumps({'schema': 'tensile-data/review-return/v1', 'batch': 'batch-001',
        'inputs_sha256': queue['inputs_sha256'], 'export_sha256': dp._sha256_file(package / 'stage_manifest.json'),
        'review': build_review_payload(decisions, batch_id='batch-001', created_at='2026-09-13T12:00:00+08:00')}))
    result.chmod(0o600); run('review_import', results_path=result)
    release = run('release', version='data-v4.1-r3').outputs[0]
    assert not list((release / 'authorization').iterdir())
    cfg = {'scope': 'full', 'split': 'holdout', 'artifact_kind': 'adapter', 'scorer': 'strict-v4.1',
        'sample_selection': 'all', 'quantization_bit': None, 'generation': ev.FORMAL_GENERATION,
        'thresholds': dict(THRESHOLDS), 'aggregation': 'pooled'}
    pre = {'eval_version': 'eval-v4.1-r1', 'model_version': model.model_id, 'data_version': 'data-v4.1-r3',
        'split': 'holdout', 'rules': {k:v for k,v in cfg.items() if k != 'thresholds'}, 'thresholds': cfg['thresholds'],
        'one_time': True, 'tuning_use': 'forbidden', 'recovery': {'same_identity_only': True}}
    pre_path = tmp_path / 'pre.yaml'; pre_path.write_text(yaml.safe_dump(pre))
    assert main(['data', 'claim', '--root', str(root), '--version', 'data-v4.1-r3', '--eval-version', 'eval-v4.1-r1',
        '--model-version', model.model_id, '--split', 'holdout', '--pre-registration', str(pre_path), '--executor', 'fixture']) == 0
    targets = {r['clip_id']: r['effective_labels'] for r in decisions}
    monkeypatch.setattr(ev, 'load_model', lambda *a, **kw: (object(), object()))
    monkeypatch.setattr(ev, 'run_model_on_video_detailed', lambda *a, **kw: SimpleNamespace(raw_output=json.dumps(targets[a[2].stem])))
    from tests.test_eval_holdout import forbid_truth
    with monkeypatch.context() as guard:
        forbid_truth(guard, release / 'sealed_ground_truth/labels.json')
        ev.prepare_versioned_evaluation(root=root, eval_version='eval-v4.1-r1', model_version=model.model_id,
            model_version_number=model.version, data_version='data-v4.1-r3', config=cfg, git_commit='synthetic',
            media_root=release / 'media', executor='fixture',
            pre_registration=root / 'evaluations/staging/eval-v4.1-r1/authorization/pre_registration.yaml')
        assert ev.execute_versioned_evaluation(root=root, eval_version='eval-v4.1-r1')['phase'] == 'inferred'
    assert score_holdout_evaluation(root=root, eval_version='eval-v4.1-r1', executor='fixture').exists()


def test_publish_resumes_only_sealing_tail(test_branch, tmp_path, monkeypatch):
    run, _, _ = reviewed_test(test_branch, tmp_path)
    original = Path.chmod
    hit = []
    def interrupt(path, mode, **kwargs):
        if path.name == 'data-v4.1-r3' and path.parent.name == 'releases' and not hit:
            hit.append(True)
            raise OSError('injected final chmod failure')
        return original(path, mode, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'chmod', interrupt)
        with pytest.raises(OSError, match='injected'):
            run('release', version='data-v4.1-r3')
    assert hit
    assert run('release', version='data-v4.1-r3').report['passed']


def test_cli_routes_seven_test_stages(test_branch, tmp_path, capsys):
    from versioning.cli import main
    root, inputs, config, _ = test_branch
    base = ['--purpose', 'holdout', '--test-config', str(config), '--root', str(root), '--inputs', str(inputs), '--batch', 'batch-001']
    for stage in ('source', 'roi', 'subvideo', 'review_export'):
        assert main(['data', stage, *base]) == 0
    package = root / 'data/test_working/batch-001/data/working/batch-001/review_export'
    result = tmp_path / 'cli-review.json'; _review_return(package, result); result.chmod(0o600)
    assert main(['data', 'review_import', *base, '--results', str(result)]) == 0
    for stage in ('release', 'release_validate'):
        assert main(['data', stage, *base, '--version', 'data-v4.1-r3']) == 0
    assert 'clip_state' not in capsys.readouterr().out


def test_validation_does_not_create_workspace(test_branch, tmp_path, monkeypatch):
    run, _, _ = reviewed_test(test_branch, tmp_path)
    run('release', version='data-v4.1-r3')
    monkeypatch.setattr(hp, '_workspace', lambda *args: pytest.fail('read-only validation created workspace'))
    assert run('release_validate', version='data-v4.1-r3').report['passed']


def test_new_test_scope_ui_requires_private_output(test_branch, tmp_path):
    run, package, _ = reviewed_test(test_branch, tmp_path)
    identity, candidates, references = dp.load_input_review_package(package)
    assert not references and len(candidates) == len(identity['selected_candidate_ids'])
    public = tmp_path / 'public'; public.mkdir(mode=0o755)
    with pytest.raises(dp.ReviewGateError, match='owner-only'):
        dp.save_input_review_draft(public / 'draft.json', identity, {})
    private = tmp_path / 'private'
    draft = dp.save_input_review_draft(private / 'draft.json', identity, {})
    assert private.stat().st_mode & 0o077 == 0 and draft.stat().st_mode & 0o077 == 0
