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


@pytest.fixture
def doctor_fixture(tmp_path, monkeypatch):
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location('doctor', PATH.with_name('source_validate_environment.py'))
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    monkeypatch.setattr(doctor, 'ROOT', tmp_path)
    (tmp_path / 'uv.lock').write_text('[[package]]\nname="pandas"\nversion="2.3.3"\n')
    (tmp_path / 'pyproject.toml').write_text('[project]\ndependencies=["pandas==2.3.3"]\n[dependency-groups]\ndev=[]\n')
    (tmp_path / 'requirements-linux-gpu.lock').write_text('pandas==2.3.3\n')
    monkeypatch.setattr(doctor.os, 'execve', lambda *a: None)
    monkeypatch.setattr(sys, 'argv', ['doctor', '--profile', 'mac'])
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(doctor.shutil, 'which', lambda n: '/synthetic/' + n)
    monkeypatch.setattr(doctor.importlib, 'import_module', lambda n: SimpleNamespace(__version__='mock'))
    monkeypatch.setattr(doctor.metadata, 'version', lambda n: '2.3.3')
    monkeypatch.setattr(doctor.metadata, 'distributions', lambda: [SimpleNamespace(metadata={'Name':'pandas'}, version='2.3.3')])
    monkeypatch.setattr(doctor.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='', stderr=''))
    return doctor


def test_doctor_lock_drift_is_not_compatibility_pass(doctor_fixture, monkeypatch, capsys):
    doctor = doctor_fixture
    assert doctor.main() == 0
    capsys.readouterr()
    monkeypatch.setattr(doctor.metadata, 'version', lambda n: '2.2.3')
    assert doctor.main() == 1
    assert 'pandas violates project requirement' in capsys.readouterr().out


def test_doctor_executes_media_tools(doctor_fixture, monkeypatch, capsys):
    from types import SimpleNamespace
    assert doctor_fixture.main() == 0
    capsys.readouterr()
    monkeypatch.setattr(doctor_fixture.subprocess, 'run', lambda a, **k: SimpleNamespace(returncode=int(a[0]=='ffmpeg'), stdout='', stderr='broken'))
    assert doctor_fixture.main() == 1
    assert 'ffmpeg cannot execute' in capsys.readouterr().out


def test_doctor_rechecks_git_identity(doctor_fixture, monkeypatch, capsys):
    from types import SimpleNamespace
    doctor = doctor_fixture
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(sys, 'argv', ['doctor', '--profile', 'linux-gpu'])
    monkeypatch.setattr(doctor.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(__version__='mock', cuda=SimpleNamespace(is_available=lambda:True)))
    monkeypatch.setitem(sys.modules, 'llamafactory', SimpleNamespace(__file__=str(doctor.ROOT / 'LlamaFactory/src/llamafactory/__init__.py')))
    monkeypatch.setitem(sys.modules, 'finetune.train_with_contract', SimpleNamespace(run_training=lambda:None))
    monkeypatch.setitem(sys.modules, 'llamafactory.train.tuner', SimpleNamespace(run_exp=lambda:None))
    def git(args, **kwargs):
        if 'ls-tree' in args: return '160000 commit ' + 'a'*40 + '\tLlamaFactory\n'
        if 'rev-parse' in args: return 'a'*40+'\n'
        return ''
    monkeypatch.setattr(doctor.subprocess, 'check_output', git)
    assert doctor.main() == 0
    capsys.readouterr()
    monkeypatch.setattr(doctor.subprocess, 'check_output', lambda a, **k: ' M tuner.py' if 'status' in a else git(a))
    assert doctor.main() == 1
    assert 'differs from clean pinned submodule' in capsys.readouterr().out
