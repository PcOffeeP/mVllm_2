"""Safety boundaries for deployment orchestration, independent of installed packages."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

PATH = Path(__file__).resolve().parents[1] / 'scripts/source_prepare_environment.py'
spec = importlib.util.spec_from_file_location('deploy', PATH)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def test_existing_environment_is_never_selected(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.sys, 'platform', 'darwin')
    with pytest.raises(ValueError, match='nonexistent'):
        deploy.preflight('mac', tmp_path, 'python')


def test_symlink_parent_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.sys, 'platform', 'darwin')
    (tmp_path / 'link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlinks'):
        deploy.preflight('mac', tmp_path / 'link' / 'new', 'python')


def test_wrong_platform_before_any_process(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.sys, 'platform', 'darwin')
    monkeypatch.setattr(deploy.subprocess, 'check_output', lambda *a, **k: pytest.fail('must not run'))
    with pytest.raises(ValueError, match='requires linux'):
        deploy.preflight('linux-gpu', tmp_path / 'new', 'python')


def test_missing_tool_does_not_create_target(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.sys, 'platform', 'darwin')
    monkeypatch.setattr(deploy.shutil, 'which', lambda n: None if n == 'ffprobe' else '/bin/' + n)
    target = tmp_path / 'new'
    with pytest.raises(ValueError, match='ffprobe'):
        deploy.preflight('mac', target, 'python')
    assert not target.exists()


def test_installer_failure_preserves_partial_environment(tmp_path, monkeypatch):
    target = tmp_path / 'new'
    monkeypatch.setattr(sys, 'argv', ['deploy', '--profile', 'mac', '--env', str(target), '--python', 'python'])
    monkeypatch.setattr(deploy, 'preflight', lambda *a: '/python3.11')
    def fail(args, **kwargs):
        target.mkdir()
        (target / 'diagnostic').write_text('keep')
        raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(deploy, 'run', fail)
    assert deploy.main() == 1
    assert (target / 'diagnostic').read_text() == 'keep'


def test_failed_doctor_never_reports_success(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['deploy', '--profile', 'mac', '--env', str(tmp_path / 'new'), '--python', 'python'])
    monkeypatch.setattr(deploy, 'preflight', lambda *a: '/python3.11')
    calls = []
    def fake(args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(deploy, 'run', fake)
    assert deploy.main() == 1
    assert len(calls) == 2


def test_ambient_uv_target_cannot_redirect_install(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['deploy', '--profile', 'mac', '--env', str(tmp_path / 'new'), '--python', 'python'])
    monkeypatch.setattr(deploy, 'preflight', lambda *a: '/python3.11')
    for name in ('UV_CONFIG_FILE', 'UV_PROJECT', 'UV_WORKING_DIRECTORY', 'UV_TARGET', 'PIP_TARGET', 'PYTHONPATH', 'PYTHONHOME'):
        monkeypatch.setenv(name, '/existing/environment')
    calls = []
    monkeypatch.setattr(deploy, 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    assert deploy.main() == 0
    assert calls[0][0][:3] == ['uv', '--no-config', 'sync']
    env = calls[0][1]['env']
    assert not any(k in env for k in ('UV_CONFIG_FILE', 'UV_PROJECT', 'UV_WORKING_DIRECTORY', 'UV_TARGET', 'PIP_TARGET', 'PYTHONPATH', 'PYTHONHOME'))
    assert calls[1][0][1] == '-I'
