"""Merge all V4.1 fold adapters and run full validation inference."""

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

from finetune.v4_1_runtime import RELEASE_ID, validate_release

ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "finetune"
RUN_ID = "v4_1_0_760050fad303_20260723"
LOG_DIR = FINETUNE / "run_logs"
RESULT_ROOT = FINETUNE / "results" / RUN_ID / "three_fold_validation"
STATE_PATH = LOG_DIR / f"post_training_{RUN_ID}.json"


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
    def merged_dir(self) -> Path:
        return self.run_dir.with_name(f"{self.run_name}_merged")

    @property
    def merge_config(self) -> Path:
        return FINETUNE / f"MiniCPM/config/merge_v4_1_fold{self.index}.yaml"

    @property
    def result_dir(self) -> Path:
        return RESULT_ROOT / f"fold{self.index}"


FOLDS = tuple(Fold(index) for index in range(3))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--max-samples",
        type=int,
        help="Optional smoke-test limit applied independently to each fold.",
    )
    return parser.parse_args()


def _has_adapter(path: Path) -> bool:
    return any(
        (path / name).is_file()
        for name in ("adapter_model.safetensors", "adapter_model.bin")
    )


def _training_complete(fold: Fold) -> bool:
    return (
        (fold.run_dir / "trainer_state.json").is_file()
        and (fold.run_dir / "train_results.json").is_file()
        and _has_adapter(fold.run_dir)
    )


def _merged_complete(fold: Fold) -> bool:
    return (
        (fold.merged_dir / "config.json").is_file()
        and (fold.merged_dir / "tokenizer_config.json").is_file()
        and any(fold.merged_dir.glob("model*.safetensors"))
    )


def _evaluation_complete(fold: Fold) -> bool:
    summary_path = fold.result_dir / "evaluation_summary.json"
    records_path = fold.result_dir / "evaluation_records.jsonl"
    failures_path = fold.result_dir / "runtime_failures.csv"
    if not all(path.is_file() for path in (summary_path, records_path, failures_path)):
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        record_count = sum(
            bool(line.strip())
            for line in records_path.read_text(encoding="utf-8").splitlines()
        )
    except (OSError, json.JSONDecodeError):
        return False
    total = summary.get("total_samples") if isinstance(summary, dict) else None
    return (
        isinstance(total, int)
        and total > 0
        and summary.get("sample_count") == total
        and summary.get("runtime_failure_count") == 0
        and record_count == total
    )


def _preflight(max_samples: int | None) -> dict[str, Any]:
    if max_samples is not None and max_samples <= 0:
        raise ValueError("--max-samples must be positive")
    release = validate_release(ROOT, verify_media=True)
    cli = Path(sys.executable).with_name("llamafactory-cli")
    if not cli.is_file():
        raise RuntimeError(f"llamafactory-cli 不存在: {cli}")
    folds = []
    for fold in FOLDS:
        if not _training_complete(fold):
            raise RuntimeError(f"fold{fold.index}: 训练产物不完整")
        if not fold.merge_config.is_file():
            raise RuntimeError(f"fold{fold.index}: 合并配置不存在")
        if fold.merged_dir.exists() and not _merged_complete(fold):
            raise RuntimeError(f"fold{fold.index}: 不完整合并目录已存在")
        if fold.result_dir.exists() and not _evaluation_complete(fold):
            identity = fold.result_dir / "run_identity.json"
            records = fold.result_dir / "evaluation_records.jsonl"
            if not identity.is_file() or not records.is_file():
                raise RuntimeError(f"fold{fold.index}: 不可恢复的评测目录已存在")
        folds.append(
            {
                "fold": fold.index,
                "training": "complete",
                "merge": "complete" if _merged_complete(fold) else "pending",
                "evaluation": (
                    "complete" if _evaluation_complete(fold) else "pending_or_resumable"
                ),
            }
        )
    return {
        "release": release,
        "llamafactory_cli": str(cli),
        "max_samples": max_samples,
        "folds": folds,
        "result_root": str(RESULT_ROOT),
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
        "schema_version": "tensile-v4.1-post-training/v1",
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


def _run_logged(command: list[str], log_path: Path, *, cwd: Path = ROOT) -> None:
    with log_path.open("w", encoding="utf-8") as log:
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
            f"命令退出码 {result.returncode}，请查看 {log_path}"
        )


def _merge(fold: Fold) -> None:
    if _merged_complete(fold):
        _write_state("running", f"fold{fold.index}_merge_already_complete")
        return
    if fold.merged_dir.exists():
        raise RuntimeError(f"拒绝覆盖不完整合并目录: {fold.merged_dir}")
    _write_state("running", f"fold{fold.index}_merging")
    _run_logged(
        [
            str(Path(sys.executable).with_name("llamafactory-cli")),
            "export",
            str(fold.merge_config.relative_to(FINETUNE)),
        ],
        LOG_DIR / f"merge_{fold.run_name}.log",
        cwd=FINETUNE,
    )
    if not _merged_complete(fold):
        raise RuntimeError(f"fold{fold.index}: 合并命令成功但模型产物不完整")


def _evaluate(fold: Fold, max_samples: int | None) -> None:
    if _evaluation_complete(fold):
        _write_state("running", f"fold{fold.index}_evaluation_already_complete")
        return
    _write_state(
        "running",
        f"fold{fold.index}_evaluating",
        result_dir=str(fold.result_dir),
    )
    command = [
        sys.executable,
        "-m",
        "finetune.run_v4_1_evaluation",
        "--fold",
        str(fold.index),
        "--model-dir",
        str(fold.merged_dir),
        "--out-dir",
        str(fold.result_dir),
    ]
    if max_samples is not None:
        command.extend(["--max-samples", str(max_samples)])
    _run_logged(
        command,
        LOG_DIR / f"evaluate_{fold.run_name}.log",
    )
    if not _evaluation_complete(fold):
        raise RuntimeError(f"fold{fold.index}: 评测产物不完整")


def main() -> int:
    args = parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    preflight = _preflight(args.max_samples)
    if args.validate_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0
    try:
        for fold in FOLDS:
            _merge(fold)
        for fold in FOLDS:
            _evaluate(fold, args.max_samples)
    except Exception as exc:
        _write_state(
            "failed",
            "post_training",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    _write_state("completed", "three_fold_validation_complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
