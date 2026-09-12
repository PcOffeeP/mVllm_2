"""M3 explicit DVC graph, fail-closed CLI and real DVC storage checks.

Media computation uses the same controlled fixture as the adapter tests. DVC itself
runs as a real subprocess: graph parsing/commit, stale detection, read-only validation,
and local remote push/pull. This does not claim real MiniCPM or training-machine proof.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from test_data_pipeline import (
    pinned_inputs, source_inputs, roi_inputs, media_inputs, media_runtime,
    _review_return, _source_probe,
)
from versioning import data_pipeline as dp
from versioning.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def dvc(root, *args):
    return subprocess.run([sys.executable, '-m', 'dvc', *args], cwd=root, capture_output=True,
                          text=True, env={**os.environ, 'DVC_NO_ANALYTICS': '1'})


@pytest.fixture()
def dvc_inputs(media_inputs, media_runtime, tmp_path, monkeypatch):
    from pipeline import source_bootstrap
    monkeypatch.setattr(source_bootstrap, 'probe_video', _source_probe)
    root = tmp_path / 'store'; root.mkdir()
    proc = dvc(root, 'init', '--no-scm'); assert proc.returncode == 0, proc.stderr
    inputs = media_inputs[0]
    results = tmp_path / 'returned.json'
    common = ['--root', str(root), '--batch', 'batch-001', '--inputs', str(inputs)]
    assert main(['data', 'dvc-config', *common, '--version', 'data-v4.1-r1', '--results', str(results)]) == 0
    return root, inputs, results, common


@pytest.mark.parametrize('stage', dp.STAGES)
def test_unconfigured_repository_template_has_no_implicit_choices(stage):
    template = yaml.safe_load((REPO_ROOT / 'dvc.yaml').read_text())
    assert list(template['stages']) == list(dp.STAGES)
    assert template['stages'][stage]['cmd'] == '${pipeline.' + stage + '.cmd}'
    assert yaml.safe_load((REPO_ROOT / 'params.yaml').read_text()) == {'pipeline': {}}


@pytest.mark.parametrize('argv', [[], ['data'], ['data', 'latest'], ['data', 'train'],
    ['data', 'source'], ['data', 'release'], ['data', 'release_validate']])
def test_missing_or_invalid_cli_is_fail_closed(tmp_path, monkeypatch, argv):
    monkeypatch.chdir(tmp_path)
    assert main(argv) != 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('field', ['root', 'inputs', 'batch', 'version', 'results'])
def test_configuration_requires_all_explicit_choices(tmp_path, field):
    args = {'root': str(tmp_path), 'inputs': str(tmp_path / 'input.yaml'), 'batch': 'batch-001',
            'version': 'data-v4.1-r1', 'results': str(tmp_path / 'returned.json')}
    del args[field]
    assert main(['data', 'dvc-config', *[v for k, value in args.items() for v in ('--'+k, value)]]) == 2


def test_generated_graph_and_missing_review_gate(dvc_inputs):
    root, inputs, results, common = dvc_inputs
    params = yaml.safe_load((root / 'params.yaml').read_text())['pipeline']
    for index, stage in enumerate(dp.STAGES):
        assert '--inputs' in params[stage]['cmd'] and str(inputs) in params[stage]['cmd']
        assert str(root) in params[stage]['cmd']
        if index:
            assert str(root / 'data/working/batch-001' / dp.STAGES[index-1]) in params[stage]['deps']
    assert str(results) in params['review_import']['deps']
    assert str(results) not in params['review_export']['deps']
    assert params['release']['outs'] == [{str(root / 'data/working/batch-001/release'): {'persist': True}}]
    assert params['release_validate']['outs'] == []
    for stage in ('source', 'roi', 'subvideo', 'review_export'):
        assert main(['data', stage, *common]) == 0
    proc = dvc(root, 'commit', '--force', 'review_export'); assert proc.returncode == 0, proc.stderr
    proc = dvc(root, 'repro', '--single-item', 'review_import')
    assert proc.returncode != 0
    assert not (root / 'data/working/batch-001/review_import').exists()
    assert not (root / 'data/releases').exists()


def finish_pipeline(root, results, common):
    for stage in ('source', 'roi', 'subvideo', 'review_export'):
        assert main(['data', stage, *common]) == 0
    _review_return(root / 'data/working/batch-001/review_export', results)
    assert main(['data', 'review_import', *common, '--results', str(results)]) == 0
    assert main(['data', 'release', *common, '--version', 'data-v4.1-r1']) == 0
    assert main(['data', 'release_validate', *common, '--version', 'data-v4.1-r1']) == 0


def test_real_dvc_detects_stale_and_never_overwrites_existing_stage(dvc_inputs, media_inputs):
    root, inputs, results, common = dvc_inputs
    finish_pipeline(root, results, common)
    proc = dvc(root, 'commit', '--force', 'dvc.yaml'); assert proc.returncode == 0, proc.stderr
    proc = dvc(root, 'repro', '--single-item', 'release_validate'); assert proc.returncode == 0, proc.stderr
    source = root / 'data/working/batch-001/source'
    original = (source / 'stage_manifest.json').read_bytes()
    video = media_inputs[2] / 'videos/video_0001.mp4'
    video.write_bytes(b'input changed')
    proc = dvc(root, 'status', '--json'); assert proc.returncode == 0, proc.stderr
    assert 'source' in json.loads(proc.stdout)
    assert (source / 'stage_manifest.json').read_bytes() == original
    proc = dvc(root, 'repro', '--single-item', 'source')
    assert proc.returncode != 0
    assert (source / 'stage_manifest.json').read_bytes() == original


def test_real_dvc_payload_push_pull_preserves_metadata(dvc_inputs, tmp_path):
    root, inputs, results, common = dvc_inputs
    finish_pipeline(root, results, common)
    release = root / 'data/releases/data-v4.1-r1'
    payload = release / 'payload'
    before = dp._stage_inventory(payload, exclude_manifest=False)
    metadata = (release / 'release.yaml').read_bytes()
    pointer = release / 'payload.dvc'
    assert pointer.is_file()
    assert 'release.yaml' not in pointer.read_text()
    remote = tmp_path / 'remote'
    # DVC's config writer rejects non-ASCII absolute URLs on Linux.
    remote_url = os.path.relpath(remote, root)
    proc = dvc(root, 'remote', 'add', '-d', 'fixture', remote_url); assert proc.returncode == 0, proc.stderr
    proc = dvc(root, 'push', str(pointer)); assert proc.returncode == 0, proc.stderr
    dp._restore_write_bits(payload); release.chmod(0o700); shutil.rmtree(payload)
    shutil.rmtree(root / '.dvc/cache')
    proc = dvc(root, 'pull', str(pointer)); assert proc.returncode == 0, proc.stderr
    dp._strip_write_bits(payload); release.chmod(0o500)
    assert dp._stage_inventory(payload, exclude_manifest=False) == before
    assert (release / 'release.yaml').read_bytes() == metadata
    assert main(['data', 'release_validate', *common, '--version', 'data-v4.1-r1']) == 0
