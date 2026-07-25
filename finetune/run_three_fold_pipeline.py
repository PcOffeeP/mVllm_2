"""Run the release-pinned three-fold train, merge, and evaluation pipeline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "finetune"
RUN_ID = "v2_0_0_1dab1e5e_20260719"
RELEASE_ID = "v2.0.0-1dab1e5e"
LOG_DIR = FINETUNE / "run_logs"
RESULT_ROOT = FINETUNE / "results" / "archive" / "v2" / RUN_ID
STATE_PATH = LOG_DIR / f"three_fold_pipeline_{RUN_ID}.json"


@dataclass(frozen=True)
class Fold:
    index: int

    @property
    def name(self) -> str:
        return f"fold{self.index}"

    @property
    def run_name(self) -> str:
        return f"sft_interval_v2_0_0_1dab1e5e_fold{self.index}_20260719"

    @property
    def run_dir(self) -> Path:
        return (
            ROOT
            / "LlamaFactory"
            / "saves"
            / "minicpmv4_5"
            / "lora"
            / "archive"
            / "v2"
            / self.run_name
        )

    @property
    def merged_dir(self) -> Path:
        return self.run_dir.with_name(f"{self.run_name}_merged")

    @property
    def training_config(self) -> str:
        return f"MiniCPM/config/archive/v2/train_fold{self.index}.yaml"

    @property
    def merge_config(self) -> str:
        return f"MiniCPM/config/archive/v2/merge_fold{self.index}.yaml"

    @property
    def log_file(self) -> Path:
        return LOG_DIR / f"{self.name}_{RUN_ID}.log"

    @property
    def pid_file(self) -> Path:
        return LOG_DIR / f"{self.name}_{RUN_ID}.pid"


FOLDS = tuple(Fold(index) for index in range(3))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=60,
        help="Polling interval while attached to an existing training process.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate release, configs, tools, and resumability without starting work.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.poll_seconds < 5:
        raise ValueError("--poll-seconds must be at least 5")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    preflight = _preflight()
    if args.validate_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0
    _write_state("running", "attach_fold0")
    try:
        _attach_or_accept_completed(FOLDS[0], args.poll_seconds)
        _merge(FOLDS[0])
        _evaluate(
            FOLDS[0],
            dataset="fold_0_val",
            out_dir=RESULT_ROOT / "fold0_initial" / "fold_0_val_30",
            max_samples=30,
        )
        _evaluate(
            FOLDS[0],
            dataset="test",
            out_dir=RESULT_ROOT / "fold0_initial" / "test_5",
            max_samples=5,
        )

        for fold in FOLDS[1:]:
            _train(fold)
            _merge(fold)

        full_dirs: dict[str, Path] = {}
        for fold in FOLDS:
            out_dir = RESULT_ROOT / "three_fold_full" / fold.name
            _evaluate(fold, dataset=f"fold_{fold.index}_val", out_dir=out_dir)
            full_dirs[fold.name] = out_dir
        _aggregate(full_dirs)
    except Exception as exc:
        _write_state("failed", "pipeline", error=f"{type(exc).__name__}: {exc}")
        raise
    _write_state("completed", "three_fold_aggregate")
    return 0


def _preflight() -> dict[str, Any]:
    active = json.loads((FINETUNE / "active_data_release.json").read_text(encoding="utf-8"))
    if active.get("release_id") != RELEASE_ID:
        raise RuntimeError(f"Expected release {RELEASE_ID}, got {active.get('release_id')}")
    missing_configs = [
        str(path)
        for fold in FOLDS
        for path in (
            FINETUNE / fold.training_config,
            FINETUNE / fold.merge_config,
        )
        if not path.is_file()
    ]
    if missing_configs:
        raise RuntimeError(f"Missing pipeline configs: {missing_configs}")
    cli = Path(sys.executable).with_name("llamafactory-cli")
    if not cli.is_file():
        raise RuntimeError(f"Missing LLaMA-Factory CLI beside Python: {cli}")
    fold0_pid = _read_pid(FOLDS[0].pid_file)
    if not _training_complete(FOLDS[0]) and (
        fold0_pid is None or not _pid_running(fold0_pid)
    ):
        raise RuntimeError("fold0 is neither complete nor attached to a running PID")
    for fold in FOLDS[1:]:
        if fold.run_dir.exists() and not _training_complete(fold):
            raise RuntimeError(f"{fold.name}: incomplete run directory already exists: {fold.run_dir}")
    return {
        "release_id": RELEASE_ID,
        "python": sys.executable,
        "llamafactory_cli": str(cli),
        "fold0": "complete" if _training_complete(FOLDS[0]) else f"running_pid={fold0_pid}",
        "folds": [fold.name for fold in FOLDS],
        "result_root": str(RESULT_ROOT),
    }


def _attach_or_accept_completed(fold: Fold, poll_seconds: int) -> None:
    if _training_complete(fold):
        _write_state("running", f"{fold.name}_training_already_completed")
        return
    pid = _read_pid(fold.pid_file)
    if pid is None or not _pid_running(pid):
        raise RuntimeError(f"{fold.name}: training is incomplete and PID is not running")
    _write_state("running", f"{fold.name}_training_attached", pid=pid)
    while _pid_running(pid):
        time.sleep(poll_seconds)
    _require_training_complete(fold)
    _write_state("running", f"{fold.name}_training_completed")


def _train(fold: Fold) -> None:
    if _training_complete(fold):
        _write_state("running", f"{fold.name}_training_already_completed")
        return
    if fold.run_dir.exists():
        raise RuntimeError(f"{fold.name}: refusing to overwrite incomplete run directory {fold.run_dir}")
    _write_state("running", f"{fold.name}_training_starting")
    with fold.log_file.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "train_with_contract.py", fold.training_config],
            cwd=FINETUNE,
            env=_runtime_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        fold.pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
        _write_state("running", f"{fold.name}_training", pid=process.pid)
        return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"{fold.name}: training exited with code {return_code}")
    _require_training_complete(fold)
    _write_state("running", f"{fold.name}_training_completed")


def _merge(fold: Fold) -> None:
    _require_training_complete(fold)
    if _merged_complete(fold.merged_dir):
        _write_state("running", f"{fold.name}_merge_already_completed")
        return
    if fold.merged_dir.exists():
        raise RuntimeError(f"{fold.name}: refusing to overwrite incomplete merge directory {fold.merged_dir}")
    _write_state("running", f"{fold.name}_merge")
    command = [str(Path(sys.executable).with_name("llamafactory-cli")), "export", fold.merge_config]
    _run_logged(command, cwd=FINETUNE, log_file=LOG_DIR / f"{fold.name}_{RUN_ID}_merge.log")
    if not _merged_complete(fold.merged_dir):
        raise RuntimeError(f"{fold.name}: merge command succeeded but model artifacts are incomplete")


def _evaluate(
    fold: Fold,
    *,
    dataset: str,
    out_dir: Path,
    max_samples: int | None = None,
) -> None:
    if _evaluation_complete(out_dir):
        _write_state("running", f"{fold.name}_evaluation_already_completed", dataset=dataset)
        return
    if out_dir.exists():
        raise RuntimeError(f"Refusing to overwrite incomplete evaluation directory {out_dir}")
    _write_state("running", f"{fold.name}_evaluation", dataset=dataset)
    command = [
        sys.executable,
        "-m",
        "finetune.validation.run_evaluation",
        "--dataset",
        dataset,
        "--model-dir",
        str(fold.merged_dir),
        "--out-dir",
        str(out_dir),
    ]
    if max_samples is not None:
        command.extend(["--max-samples", str(max_samples)])
    _run_logged(
        command,
        cwd=ROOT,
        log_file=LOG_DIR / f"{fold.name}_{dataset}_{max_samples or 'full'}_{RUN_ID}.log",
    )
    if not _evaluation_complete(out_dir):
        raise RuntimeError(f"{fold.name}: evaluation did not produce complete artifacts in {out_dir}")


def _aggregate(folds: dict[str, Path]) -> None:
    output = RESULT_ROOT / "three_fold_full" / "three_fold_summary.json"
    if output.is_file():
        _write_state("running", "aggregate_already_completed")
        return
    command = [sys.executable, "-m", "finetune.validation.aggregate_folds"]
    for name, directory in sorted(folds.items()):
        command.extend(["--fold", f"{name}={directory}"])
    command.extend(["--out", str(output)])
    _write_state("running", "three_fold_aggregate")
    _run_logged(command, cwd=ROOT, log_file=LOG_DIR / f"three_fold_aggregate_{RUN_ID}.log")


def _run_logged(command: list[str], *, cwd: Path, log_file: Path) -> None:
    with log_file.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_runtime_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with code {result.returncode}; inspect {log_file}: {' '.join(command)}"
        )


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "WANDB_MODE": "offline",
            "DOWNSAMPLE_MODE": "4x",
            "DISABLE_VERSION_CHECK": "1",
            "PYTHONPATH": f"{ROOT / 'LlamaFactory' / 'src'}:{ROOT}",
        }
    )
    return env


def _training_complete(fold: Fold) -> bool:
    return (
        (fold.run_dir / "trainer_state.json").is_file()
        and (fold.run_dir / "train_results.json").is_file()
        and (fold.run_dir / "eval_results.json").is_file()
        and _has_adapter(fold.run_dir)
    )


def _require_training_complete(fold: Fold) -> None:
    if not _training_complete(fold):
        raise RuntimeError(f"{fold.name}: required trainer state/results/adapter artifacts are incomplete")


def _merged_complete(path: Path) -> bool:
    return (path / "config.json").is_file() and any(path.glob("model*.safetensors"))


def _evaluation_complete(path: Path) -> bool:
    return (
        (path / "evaluation_summary.json").is_file()
        and (path / "evaluation_records.jsonl").is_file()
        and (path / "runtime_failures.csv").is_file()
    )


def _has_adapter(path: Path) -> bool:
    return any((path / name).is_file() for name in ("adapter_model.safetensors", "adapter_model.bin"))


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _write_state(status: str, stage: str, **extra: Any) -> None:
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "status": status,
        "stage": stage,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **extra,
    }
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
