"""Run the isolated V4.1 three-fold LoRA training sequence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from finetune.v4_1_runtime import (
    RELEASE_ID,
    validate_release,
    validate_training_config,
)

ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "finetune"
RUN_ID = "v4_1_0_760050fad303_20260723"
LOG_DIR = FINETUNE / "run_logs"
STATE_PATH = LOG_DIR / f"three_fold_training_{RUN_ID}.json"


@dataclass(frozen=True)
class Fold:
    index: int

    @property
    def run_name(self) -> str:
        return f"sft_tensile_{RUN_ID}_fold{self.index}"

    @property
    def run_dir(self) -> Path:
        return ROOT / "LlamaFactory/saves/minicpmv4_5/lora" / self.run_name

    @property
    def config_path(self) -> Path:
        return FINETUNE / f"MiniCPM/config/train_v4_1_fold{self.index}.yaml"

    @property
    def log_path(self) -> Path:
        return LOG_DIR / f"{self.run_name}.log"


FOLDS = tuple(Fold(index) for index in range(3))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate release, media, configs, GPU CLI, and output isolation.",
    )
    return parser.parse_args()


def _training_complete(fold: Fold) -> bool:
    return (
        (fold.run_dir / "trainer_state.json").is_file()
        and (fold.run_dir / "train_results.json").is_file()
        and any(
            (fold.run_dir / name).is_file()
            for name in ("adapter_model.safetensors", "adapter_model.bin")
        )
    )


def _preflight() -> dict[str, Any]:
    release = validate_release(ROOT, verify_media=True)
    configs = []
    for fold in FOLDS:
        config = validate_training_config(
            fold.config_path,
            fold=fold.index,
            project_root=ROOT,
        )
        if fold.run_dir.exists() and not _training_complete(fold):
            raise RuntimeError(
                f"fold{fold.index}: 拒绝覆盖不完整训练目录 {fold.run_dir}"
            )
        configs.append(
            {
                "fold": fold.index,
                "dataset": config["dataset"],
                "eval_dataset": config["eval_dataset"],
                "output_dir": str(fold.run_dir),
                "status": "complete" if _training_complete(fold) else "pending",
            }
        )
    cli = Path(sys.executable).with_name("llamafactory-cli")
    if not cli.is_file():
        raise RuntimeError(f"当前 Python 环境缺少 llamafactory-cli: {cli}")
    return {
        "release": release,
        "python": sys.executable,
        "llamafactory_cli": str(cli),
        "folds": configs,
    }


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "WANDB_MODE": "offline",
            "DOWNSAMPLE_MODE": "4x",
            "DISABLE_VERSION_CHECK": "1",
            "PYTHONPATH": f"{ROOT / 'LlamaFactory/src'}:{ROOT}",
        }
    )
    return env


def _write_state(status: str, stage: str, **extra: Any) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "tensile-v4.1-three-fold-training/v1",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "orchestrator_pid": os.getpid(),
        "status": status,
        "stage": stage,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **extra,
    }
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


def _train(fold: Fold) -> None:
    if _training_complete(fold):
        _write_state("running", f"fold{fold.index}_already_complete")
        return
    if fold.run_dir.exists():
        raise RuntimeError(f"拒绝覆盖不完整训练目录: {fold.run_dir}")
    _write_state("running", f"fold{fold.index}_starting")
    with fold.log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "train_with_contract.py",
                str(fold.config_path.relative_to(FINETUNE)),
            ],
            cwd=FINETUNE,
            env=_runtime_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        _write_state(
            "running",
            f"fold{fold.index}_training",
            child_pid=process.pid,
            log_path=str(fold.log_path),
        )
        return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(
            f"fold{fold.index} 训练退出码 {return_code}，请查看 {fold.log_path}"
        )
    if not _training_complete(fold):
        raise RuntimeError(f"fold{fold.index} 训练结束但必要产物不完整")
    _write_state("running", f"fold{fold.index}_complete")


def main() -> int:
    args = parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    preflight = _preflight()
    if args.validate_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0
    try:
        for fold in FOLDS:
            _train(fold)
    except Exception as exc:
        _write_state(
            "failed",
            "training",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    _write_state("completed", "three_folds_complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

