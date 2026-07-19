"""Refresh base-model evaluation results for source videos and test subvideos."""

from __future__ import annotations

import argparse
import json
import os
import shutil
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
BASE_MODEL_DIR = ROOT / "models" / "minicpmv4_5"
LOG_DIR = FINETUNE / "run_logs"
STAGING_ROOT = LOG_DIR / f"base_test_refresh_{RUN_ID}"
STATE_PATH = LOG_DIR / f"base_test_pipeline_{RUN_ID}.json"
PID_PATH = LOG_DIR / f"base_test_pipeline_{RUN_ID}.pid"
REQUIRED_RESULT_FILES = (
    "evaluation_summary.json",
    "evaluation_records.jsonl",
    "runtime_failures.csv",
)


@dataclass(frozen=True)
class EvaluationTarget:
    dataset: str
    expected_samples: int
    result_dir: Path

    @property
    def staging_dir(self) -> Path:
        return STAGING_ROOT / self.dataset

    @property
    def log_file(self) -> Path:
        return LOG_DIR / f"base_test_{self.dataset}_{RUN_ID}.log"


TARGETS = (
    EvaluationTarget(
        dataset="test",
        expected_samples=21,
        result_dir=FINETUNE / "results" / "base_test_01" / "training",
    ),
    EvaluationTarget(
        dataset="test_subvideos",
        expected_samples=431,
        result_dir=FINETUNE / "results" / "base_test_sub_01" / "training",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the model, datasets, and update targets without inference.",
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
        for target in TARGETS:
            _evaluate_and_publish(target)
    except Exception as exc:
        _write_state("failed", "pipeline", error=f"{type(exc).__name__}: {exc}")
        raise
    _write_state("completed", "base_test_results_updated")
    return 0


def _preflight() -> dict[str, Any]:
    active = _read_object(FINETUNE / "active_data_release.json")
    if active.get("release_id") != RELEASE_ID:
        raise RuntimeError(
            f"Expected active release {RELEASE_ID}, got {active.get('release_id')}"
        )
    if not _model_complete(BASE_MODEL_DIR):
        raise RuntimeError(f"Incomplete base model: {BASE_MODEL_DIR}")

    datasets: dict[str, int] = {}
    targets: dict[str, str] = {}
    for target in TARGETS:
        count = len(load_dataset(target.dataset))
        if count != target.expected_samples:
            raise RuntimeError(
                f"{target.dataset}: expected {target.expected_samples} samples, got {count}"
            )
        datasets[target.dataset] = count
        targets[target.dataset] = str(target.result_dir)
        if target.staging_dir.exists() and not _evaluation_complete(
            target.staging_dir, target
        ):
            raise RuntimeError(
                f"Refusing to overwrite incomplete staging directory "
                f"{target.staging_dir}"
            )
    return {
        "release_id": RELEASE_ID,
        "base_model_dir": str(BASE_MODEL_DIR),
        "datasets": datasets,
        "targets": targets,
    }


def _evaluate_and_publish(target: EvaluationTarget) -> None:
    if _current_result_complete(target):
        _write_state(
            "running",
            "evaluation_already_updated",
            dataset=target.dataset,
        )
        return

    if not _evaluation_complete(target.staging_dir, target):
        if target.staging_dir.exists():
            raise RuntimeError(
                f"Refusing to overwrite incomplete staging directory "
                f"{target.staging_dir}"
            )
        _write_state(
            "running",
            "evaluation",
            dataset=target.dataset,
            total_samples=target.expected_samples,
            model_dir=str(BASE_MODEL_DIR),
            target_dir=str(target.result_dir),
        )
        _run_logged(
            [
                sys.executable,
                "-m",
                "finetune.validation.run_evaluation",
                "--dataset",
                target.dataset,
                "--model-dir",
                str(BASE_MODEL_DIR),
                "--out-dir",
                str(target.staging_dir),
            ],
            log_file=target.log_file,
        )
    if not _evaluation_complete(target.staging_dir, target):
        raise RuntimeError(
            f"{target.dataset}: staging evaluation artifacts are incomplete"
        )

    _write_state(
        "running",
        "publishing",
        dataset=target.dataset,
        target_dir=str(target.result_dir),
    )
    _publish_result(target)
    if not _current_result_complete(target):
        raise RuntimeError(f"{target.dataset}: published result validation failed")


def _publish_result(target: EvaluationTarget) -> None:
    target.result_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_RESULT_FILES:
        source = target.staging_dir / name
        destination = target.result_dir / name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(source, temporary)
        temporary.replace(destination)


def _current_result_complete(target: EvaluationTarget) -> bool:
    if not _evaluation_complete(target.result_dir, target):
        return False
    summary = _read_object(target.result_dir / "evaluation_summary.json")
    return (
        summary.get("active_release_id") == RELEASE_ID
        and summary.get("prompt_version") == "v2.1.0"
        and Path(str(summary.get("model_dir"))).resolve() == BASE_MODEL_DIR.resolve()
    )


def _evaluation_complete(path: Path, target: EvaluationTarget) -> bool:
    if not all((path / name).is_file() for name in REQUIRED_RESULT_FILES):
        return False
    try:
        summary = _read_object(path / "evaluation_summary.json")
    except RuntimeError:
        return False
    return (
        summary.get("dataset") == target.dataset
        and summary.get("metrics", {}).get("total_samples")
        == target.expected_samples
    )


def _model_complete(path: Path) -> bool:
    index_path = path / "model.safetensors.index.json"
    if not (path / "config.json").is_file() or not index_path.is_file():
        return False
    try:
        index = _read_object(index_path)
    except RuntimeError:
        return False
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict) or not weight_map:
        return False
    shards = set(weight_map.values())
    return bool(shards) and all(
        isinstance(name, str) and (path / name).is_file()
        for name in shards
    )


def _run_logged(command: list[str], *, log_file: Path) -> None:
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


def _claim_pid() -> None:
    existing = _read_pid(PID_PATH)
    if existing is not None and existing != os.getpid() and _pid_running(existing):
        raise RuntimeError(f"base-test supervisor is already running with PID {existing}")
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")


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
