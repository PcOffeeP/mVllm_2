#!/usr/bin/env python3
"""Read-only dependency, CLI, media-tool and runtime-source checks; never load a model."""
from __future__ import annotations
import argparse
import importlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('mac', 'linux-gpu'), required=True)
    args = parser.parse_args()
    errors, versions = [], {}
    if sys.version_info[:2] != (3, 11):
        errors.append('Python 3.11 required')
    if sys.platform != ('darwin' if args.profile == 'mac' else 'linux'):
        errors.append('profile/platform mismatch')
    for tool in ('uv', 'ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            errors.append(f'missing prerequisite {tool}')
    for name in ('dvc', 'mlflow', 'av', 'pandas', 'streamlit', 'streamlit_cropper', 'cv2'):
        try:
            module = importlib.import_module(name)
            versions[name] = getattr(module, '__version__', 'imported')
        except Exception as exc:
            errors.append(f'{name}: {type(exc).__name__}: {exc}')
    if shutil.which('uv'):
        result = subprocess.run(['uv', 'pip', 'check', '--python', sys.executable], capture_output=True, text=True)
        if result.returncode:
            errors.append(result.stdout + result.stderr)
    result = subprocess.run([sys.executable, '-m', 'versioning', '--help'], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        errors.append('versioning CLI: ' + result.stderr)
    if args.profile == 'linux-gpu':
        try:
            import torch
            import llamafactory
            source = Path(llamafactory.__file__).resolve()
            if not source.is_relative_to((ROOT / 'LlamaFactory/src').resolve()):
                errors.append(f'wrong LlamaFactory source: {source}')
            if not torch.cuda.is_available():
                errors.append('CUDA unavailable (no model loaded)')
            versions.update(torch=torch.__version__, llamafactory=metadata.version('llamafactory'))
            # Import the project's actual tuner path, without invoking run_exp.
            sys.path.insert(0, str(ROOT))
            from finetune.train_with_contract import run_training
            from llamafactory.train.tuner import run_exp
        except Exception as exc:
            errors.append(f'GPU training imports: {type(exc).__name__}: {exc}')
    print(json.dumps({'profile': args.profile, 'python': sys.executable, 'versions': versions, 'errors': errors,
                      'model_loaded': False, 'training_started': False}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
