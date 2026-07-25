"""Evaluate all three merged fold models on source-video and subvideo test sets."""

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

from finetune.validation.datasets import load_dataset


ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "finetune"
RUN_ID = "v2_0_0_1dab1e5e_20260719"
RELEASE_ID = "v2.0.0-1dab1e5e"
LOG_DIR = FINETUNE / "run_logs"
RESULT_ROOT = FINETUNE / "results" / "archive" / "v2" / RUN_ID / "three_fold_test"
STATE_PATH = LOG_DIR / f"three_fold_test_pipeline_{RUN_ID}.json"
PID_PATH = LOG_DIR / f"three_fold_test_pipeline_{RUN_ID}.pid"
DATASETS = ("test", "test_subvideos")
EXPECTED_COUNTS = {"test": 21, "test_subvideos": 431}


@dataclass(frozen=True)
class FoldModel:
    index: int

    @property
    def name(self) -> str:
        return f"fold{self.index}"

    @property
    def merged_dir(self) -> Path:
        run_name = f"sft_interval_v2_0_0_1dab1e5e_fold{self.index}_20260719"
        return (
            ROOT
            / "LlamaFactory"
            / "saves"
            / "minicpmv4_5"
            / "lora"
            / "archive"
            / "v2"
            / f"{run_name}_merged"
        )


FOLDS = tuple(FoldModel(index) for index in range(3))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate models, datasets, and resumability without running inference.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    preflight = _preflight()
    if args.validate_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0

    _claim_pid()
    _write_state("running", "preflight_completed", preflight=preflight)
    try:
        for dataset in DATASETS:
            for fold in FOLDS:
                _evaluate(fold, dataset)
            _aggregate(dataset)
        _write_combined_summary()
    except Exception as exc:
        _write_state("failed", "pipeline", error=f"{type(exc).__name__}: {exc}")
        raise
    _write_state("completed", "three_fold_test_aggregate")
    return 0


def _preflight() -> dict[str, Any]:
    active = _read_object(FINETUNE / "active_data_release.json")
    if active.get("release_id") != RELEASE_ID:
        raise RuntimeError(
            f"Expected active release {RELEASE_ID}, got {active.get('release_id')}"
        )

    model_status: dict[str, str] = {}
    for fold in FOLDS:
        if not _merged_complete(fold.merged_dir):
            raise RuntimeError(f"{fold.name}: incomplete merged model {fold.merged_dir}")
        model_status[fold.name] = str(fold.merged_dir)

    dataset_counts: dict[str, int] = {}
    for dataset in DATASETS:
        count = len(load_dataset(dataset))
        expected = EXPECTED_COUNTS[dataset]
        if count != expected:
            raise RuntimeError(f"{dataset}: expected {expected} samples, got {count}")
        dataset_counts[dataset] = count
        for fold in FOLDS:
            out_dir = _evaluation_dir(dataset, fold)
            if out_dir.exists() and not _evaluation_complete(out_dir, expected):
                raise RuntimeError(
                    f"Refusing to overwrite incomplete evaluation directory {out_dir}"
                )

    return {
        "release_id": RELEASE_ID,
        "models": model_status,
        "datasets": dataset_counts,
        "result_root": str(RESULT_ROOT),
    }


def _claim_pid() -> None:
    existing = _read_pid(PID_PATH)
    if existing is not None and existing != os.getpid() and _pid_running(existing):
        raise RuntimeError(f"test supervisor is already running with PID {existing}")
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")


def _evaluate(fold: FoldModel, dataset: str) -> None:
    out_dir = _evaluation_dir(dataset, fold)
    expected = EXPECTED_COUNTS[dataset]
    if _evaluation_complete(out_dir, expected):
        _write_state(
            "running",
            "evaluation_already_completed",
            dataset=dataset,
            fold=fold.name,
        )
        return
    if out_dir.exists():
        raise RuntimeError(f"Refusing to overwrite incomplete evaluation directory {out_dir}")

    _write_state(
        "running",
        "evaluation",
        dataset=dataset,
        fold=fold.name,
        total_samples=expected,
        model_dir=str(fold.merged_dir),
    )
    _run_logged(
        [
            sys.executable,
            "-m",
            "finetune.validation.run_evaluation",
            "--dataset",
            dataset,
            "--model-dir",
            str(fold.merged_dir),
            "--out-dir",
            str(out_dir),
        ],
        log_file=LOG_DIR / f"three_fold_test_{dataset}_{fold.name}_{RUN_ID}.log",
    )
    if not _evaluation_complete(out_dir, expected):
        raise RuntimeError(f"{dataset}/{fold.name}: evaluation artifacts are incomplete")


def _aggregate(dataset: str) -> None:
    output = RESULT_ROOT / dataset / "three_fold_summary.json"
    if output.is_file():
        return
    command = [sys.executable, "-m", "finetune.validation.aggregate_folds"]
    for fold in FOLDS:
        command.extend(["--fold", f"{fold.name}={_evaluation_dir(dataset, fold)}"])
    command.extend(["--out", str(output)])
    _write_state("running", "aggregate", dataset=dataset)
    _run_logged(
        command,
        log_file=LOG_DIR / f"three_fold_test_{dataset}_aggregate_{RUN_ID}.log",
    )
    if not output.is_file():
        raise RuntimeError(f"{dataset}: aggregate did not produce {output}")


def _write_combined_summary() -> None:
    output = RESULT_ROOT / "three_fold_test_summary.json"
    payload = {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "active_release_id": RELEASE_ID,
        "models": {fold.name: str(fold.merged_dir) for fold in FOLDS},
        "datasets": {
            dataset: _read_object(RESULT_ROOT / dataset / "three_fold_summary.json")
            for dataset in DATASETS
        },
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _evaluation_dir(dataset: str, fold: FoldModel) -> Path:
    return RESULT_ROOT / dataset / fold.name


def _run_logged(command: list[str], *, log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=_runtime_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with code {result.returncode}; inspect {log_file}"
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


def _merged_complete(path: Path) -> bool:
    return (
        (path / "config.json").is_file()
        and (path / "model.safetensors.index.json").is_file()
        and len(list(path.glob("model-*.safetensors"))) == 10
    )


def _evaluation_complete(path: Path, expected: int) -> bool:
    summary_path = path / "evaluation_summary.json"
    records_path = path / "evaluation_records.jsonl"
    failures_path = path / "runtime_failures.csv"
    if not all(item.is_file() for item in (summary_path, records_path, failures_path)):
        return False
    try:
        summary = _read_object(summary_path)
    except RuntimeError:
        return False
    return summary.get("metrics", {}).get("total_samples") == expected


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON value is not an object: {path}")
    return value


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
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
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
