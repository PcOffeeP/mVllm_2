"""Run the gated full-data train, merge, and final evaluation pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from finetune.prepare_full_training_dataset import (
    FULL_DATASET_NAME,
    write_full_dataset,
)


ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "finetune"
RUN_ID = "v2_0_0_1dab1e5e_20260719"
RELEASE_ID = "v2.0.0-1dab1e5e"
LOG_DIR = FINETUNE / "run_logs"
RESULT_ROOT = FINETUNE / "results" / RUN_ID / "full_training"
STATE_PATH = LOG_DIR / f"full_training_pipeline_{RUN_ID}.json"
THREE_FOLD_STATE_PATH = LOG_DIR / f"three_fold_pipeline_{RUN_ID}.json"
THREE_FOLD_SUMMARY_PATH = (
    FINETUNE
    / "results"
    / RUN_ID
    / "three_fold_full"
    / "three_fold_summary.json"
)
RELEASE_DIR = ROOT / "data" / "08_training_ready" / RELEASE_ID
DATASET_DIR = FINETUNE / "generated" / "full_training" / RUN_ID
TRAIN_CONFIG = FINETUNE / "MiniCPM" / "config" / "train_full.yaml"
MERGE_CONFIG = FINETUNE / "MiniCPM" / "config" / "merge_full.yaml"
RUN_DIR = (
    ROOT
    / "LlamaFactory"
    / "saves"
    / "minicpmv4_5"
    / "lora"
    / f"sft_interval_v2_0_0_1dab1e5e_full_20260719"
)
MERGED_DIR = RUN_DIR.with_name(f"{RUN_DIR.name}_merged")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the three-fold gate, configs, and resumability only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    preflight = _preflight()
    if args.validate_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0

    _write_state("running", "prepare_full_dataset")
    try:
        _prepare_or_verify_dataset()
        _train()
        _merge()
        for dataset in ("test", "test_subvideos"):
            _evaluate(dataset)
    except Exception as exc:
        _write_state("failed", "pipeline", error=f"{type(exc).__name__}: {exc}")
        raise
    _write_state("completed", "final_evaluation")
    return 0


def _preflight() -> dict[str, Any]:
    active = _read_object(FINETUNE / "active_data_release.json")
    if active.get("release_id") != RELEASE_ID:
        raise RuntimeError(f"Expected release {RELEASE_ID}, got {active.get('release_id')}")

    three_fold_state = _read_object(THREE_FOLD_STATE_PATH)
    if (
        three_fold_state.get("status") != "completed"
        or three_fold_state.get("stage") != "three_fold_aggregate"
        or three_fold_state.get("release_id") != RELEASE_ID
    ):
        raise RuntimeError("three-fold pipeline has not completed its aggregate stage")

    summary = _read_object(THREE_FOLD_SUMMARY_PATH)
    if summary.get("active_release_id") != RELEASE_ID:
        raise RuntimeError("three-fold summary does not match the active release")
    if summary.get("fold_count") != 3 or summary.get("total_records", 0) <= 0:
        raise RuntimeError("three-fold summary is incomplete")
    if not isinstance(summary.get("pooled_metrics", {}).get("task_metrics"), dict):
        raise RuntimeError("three-fold summary has no pooled task metrics")

    missing = [str(path) for path in (TRAIN_CONFIG, MERGE_CONFIG) if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing full-training configs: {missing}")
    cli = Path(sys.executable).with_name("llamafactory-cli")
    if not cli.is_file():
        raise RuntimeError(f"Missing LLaMA-Factory CLI beside Python: {cli}")

    if RUN_DIR.exists() and not _training_complete():
        raise RuntimeError(f"refusing to overwrite incomplete full run directory {RUN_DIR}")
    if MERGED_DIR.exists() and not _merged_complete():
        raise RuntimeError(f"refusing to overwrite incomplete merge directory {MERGED_DIR}")
    for dataset in ("test", "test_subvideos"):
        out_dir = RESULT_ROOT / dataset
        if out_dir.exists() and not _evaluation_complete(out_dir):
            raise RuntimeError(f"refusing to overwrite incomplete evaluation directory {out_dir}")

    dataset_status = (
        _verify_dataset()["unique_row_count"]
        if DATASET_DIR.exists()
        else "not_generated"
    )
    return {
        "release_id": RELEASE_ID,
        "three_fold_total_records": summary["total_records"],
        "dataset": dataset_status,
        "training": "complete" if _training_complete() else "pending",
        "merge": "complete" if _merged_complete() else "pending",
        "result_root": str(RESULT_ROOT),
    }


def _prepare_or_verify_dataset() -> dict[str, Any]:
    if DATASET_DIR.exists():
        return _verify_dataset()
    write_full_dataset(RELEASE_DIR, DATASET_DIR)
    return _verify_dataset()


def _verify_dataset() -> dict[str, Any]:
    provenance = _read_object(DATASET_DIR / "full_train.provenance.json")
    if provenance.get("release_id") != RELEASE_ID:
        raise RuntimeError("full dataset provenance does not match the active release")
    output = provenance.get("output")
    if not isinstance(output, dict):
        raise RuntimeError("full dataset provenance has no output hashes")
    for key in ("dataset", "dataset_info"):
        item = output.get(key)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise RuntimeError(f"full dataset provenance has invalid {key} entry")
        path = DATASET_DIR / item["path"]
        if not path.is_file() or _sha256_file(path) != item.get("sha256"):
            raise RuntimeError(f"full dataset {key} hash mismatch")
    registry = _read_object(DATASET_DIR / "dataset_info.json")
    if FULL_DATASET_NAME not in registry:
        raise RuntimeError(f"full dataset registry has no {FULL_DATASET_NAME}")
    unique_rows = provenance.get("unique_row_count")
    if not isinstance(unique_rows, int) or unique_rows <= 0:
        raise RuntimeError("full dataset provenance has no positive unique row count")
    return provenance


def _train() -> None:
    if _training_complete():
        _write_state("running", "training_already_completed")
        return
    if RUN_DIR.exists():
        raise RuntimeError(f"refusing to overwrite incomplete full run directory {RUN_DIR}")
    _write_state("running", "training")
    _run_logged(
        [sys.executable, "train_with_contract.py", str(TRAIN_CONFIG.relative_to(FINETUNE))],
        cwd=FINETUNE,
        log_file=LOG_DIR / f"full_{RUN_ID}.log",
    )
    if not _training_complete():
        raise RuntimeError("full training exited successfully but required artifacts are incomplete")


def _merge() -> None:
    if not _training_complete():
        raise RuntimeError("full training artifacts are incomplete")
    if _merged_complete():
        _write_state("running", "merge_already_completed")
        return
    if MERGED_DIR.exists():
        raise RuntimeError(f"refusing to overwrite incomplete merge directory {MERGED_DIR}")
    _write_state("running", "merge")
    _run_logged(
        [
            str(Path(sys.executable).with_name("llamafactory-cli")),
            "export",
            str(MERGE_CONFIG.relative_to(FINETUNE)),
        ],
        cwd=FINETUNE,
        log_file=LOG_DIR / f"full_{RUN_ID}_merge.log",
    )
    if not _merged_complete():
        raise RuntimeError("full merge exited successfully but model artifacts are incomplete")


def _evaluate(dataset: str) -> None:
    out_dir = RESULT_ROOT / dataset
    if _evaluation_complete(out_dir):
        _write_state("running", "evaluation_already_completed", dataset=dataset)
        return
    if out_dir.exists():
        raise RuntimeError(f"refusing to overwrite incomplete evaluation directory {out_dir}")
    _write_state("running", "evaluation", dataset=dataset)
    _run_logged(
        [
            sys.executable,
            "-m",
            "finetune.validation.run_evaluation",
            "--dataset",
            dataset,
            "--model-dir",
            str(MERGED_DIR),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        log_file=LOG_DIR / f"full_{dataset}_{RUN_ID}.log",
    )
    if not _evaluation_complete(out_dir):
        raise RuntimeError(f"final evaluation did not produce complete artifacts in {out_dir}")


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
            f"command failed with code {result.returncode}; inspect {log_file}"
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


def _training_complete() -> bool:
    return (
        (RUN_DIR / "trainer_state.json").is_file()
        and (RUN_DIR / "train_results.json").is_file()
        and any(
            (RUN_DIR / name).is_file()
            for name in ("adapter_model.safetensors", "adapter_model.bin")
        )
    )


def _merged_complete() -> bool:
    return (MERGED_DIR / "config.json").is_file() and any(
        MERGED_DIR.glob("model*.safetensors")
    )


def _evaluation_complete(path: Path) -> bool:
    return (
        (path / "evaluation_summary.json").is_file()
        and (path / "evaluation_records.jsonl").is_file()
        and (path / "runtime_failures.csv").is_file()
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON value is not an object: {path}")
    return value


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
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(STATE_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
