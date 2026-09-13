#!/usr/bin/env python3
"""Install a locked project profile into a new, explicitly selected environment."""
from __future__ import annotations
import argparse
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def preflight(profile: str, target: Path, python: str, root: Path = ROOT):
    expected = 'darwin' if profile == 'mac' else 'linux'
    if sys.platform != expected:
        raise ValueError(f'{profile} requires {expected}, got {sys.platform}')
    if not target.is_absolute() or target.exists() or target.is_symlink():
        raise ValueError('--env must be an absolute, nonexistent directory')
    if target.resolve() != target:
        raise ValueError('--env must not traverse symlinks or contain ..')
    for tool in ('uv', 'git', 'ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            raise ValueError(f'missing prerequisite: {tool}; install it separately')
    python_path = shutil.which(python)
    if not python_path:
        raise ValueError('an existing Python 3.11 executable is required')
    version = subprocess.check_output([python_path, '-c', 'import sys; print("%s.%s" % sys.version_info[:2])'], text=True).strip()
    if version != '3.11':
        raise ValueError(f'Python 3.11 required, got {version}')
    if profile == 'linux-gpu':
        if platform.machine() != 'x86_64':
            raise ValueError('linux-gpu lock requires x86_64')
        sub = root / 'LlamaFactory'
        expected_head = subprocess.check_output(['git', '-C', str(root), 'ls-tree', 'HEAD', 'LlamaFactory'], text=True).split()
        if len(expected_head) < 3 or expected_head[0] != '160000':
            raise ValueError('missing pinned LlamaFactory submodule')
        actual = subprocess.check_output(['git', '-C', str(sub), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(sub), 'status', '--porcelain'], text=True).strip()
        if actual != expected_head[2] or dirty:
            raise ValueError('LlamaFactory must match the clean pinned submodule; initialize it separately')
        if not shutil.which('nvidia-smi'):
            raise ValueError('NVIDIA driver required; install it separately')
        run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'])
    lock = root / ('uv.lock' if profile == 'mac' else 'requirements-linux-gpu.lock')
    if not lock.is_file():
        raise ValueError(f'missing lock file: {lock.name}')
    return python_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('mac', 'linux-gpu'), required=True)
    parser.add_argument('--env', type=Path, required=True)
    parser.add_argument('--python', required=True, help='existing Python 3.11 executable')
    args = parser.parse_args()
    try:
        python = preflight(args.profile, args.env, args.python)
        # uv's pip.target/config can override --python and mutate another environment.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('UV_', 'PIP_', 'PYTHON')) and k != 'VIRTUAL_ENV'}
        env.update(UV_PYTHON_DOWNLOADS='never', PYTHONNOUSERSITE='1',
                   UV_PROJECT_ENVIRONMENT=str(args.env))
        if args.profile == 'mac':
            run(['uv', '--no-config', 'sync', '--locked', '--python', python], cwd=ROOT, env=env)
        else:
            run(['uv', '--no-config', 'venv', '--python', python, args.env], cwd=ROOT, env=env)
            run(['uv', '--no-config', 'pip', 'sync', '--python', args.env / 'bin/python', 'requirements-linux-gpu.lock'], cwd=ROOT, env=env)
        run([args.env / 'bin/python', '-I', ROOT / 'scripts/source_validate_environment.py', '--profile', args.profile], cwd=ROOT, env=env)
    except (ValueError, subprocess.CalledProcessError, OSError) as exc:
        print(f'deployment failed: {exc}\nAny partially created environment is retained; no existing environment was selected for update.', file=sys.stderr)
        return 1
    print(f'Deployment verified: {args.env}. No model training or inference was performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
