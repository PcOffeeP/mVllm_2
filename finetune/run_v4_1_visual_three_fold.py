"""Train, merge, and evaluate the formal V4.1 visual-LoRA three-fold run."""

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

from finetune.build_v4_1_visual_data_experiment import (
    validate_adapter_coverage,
)
from finetune.v4_1_runtime import (
    RELEASE_ID,
    validate_release,
    validate_training_config,
)

ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "finetune"
CONFIG_ROOT = FINETUNE / "MiniCPM/config/active/v4_1_visual"
SAVE_ROOT = ROOT / "LlamaFactory/saves/minicpmv4_5/lora"
RUN_ID = "v4_1_0_760050fad303_20260724_visual"
LOG_ROOT = FINETUNE / "run_logs" / RUN_ID
RESULT_ROOT = FINETUNE / "results" / RUN_ID / "three_fold_validation"
STATE_PATH = LOG_ROOT / "state.json"


@dataclass(frozen=True)
class Fold:
    index: int

    @property
    def run_name(self) -> str:
        return f"sft_tensile_{RUN_ID}_fold{self.index}"

    @property
    def adapter_dir(self) -> Path:
        return SAVE_ROOT / self.run_name

    @property
    def merged_dir(self) -> Path:
        return SAVE_ROOT / f"{self.run_name}_merged"

    @property
    def train_config(self) -> Path:
        return CONFIG_ROOT / f"train_v4_1_visual_fold{self.index}.yaml"

    @property
    def merge_config(self) -> Path:
        return CONFIG_ROOT / f"merge_v4_1_visual_fold{self.index}.yaml"

    @property
    def result_dir(self) -> Path:
        return RESULT_ROOT / f"fold{self.index}"


FOLDS = tuple(Fold(index) for index in range(3))
EXPECTED_EVALUATION_COUNTS = {0: 425, 1: 445, 2: 346}


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
    env.pop("PYTORCH_CUDA_ALLOC_CONF", None)
    return env


def _write_state(status: str, stage: str, **extra: Any) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "tensile-v4.1-visual-three-fold/v1",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "status": status,
        "stage": stage,
        "orchestrator_pid": os.getpid(),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **extra,
    }
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


def _training_complete(fold: Fold) -> bool:
    return (
        (fold.adapter_dir / "trainer_state.json").is_file()
        and (fold.adapter_dir / "train_results.json").is_file()
        and (fold.adapter_dir / "adapter_config.json").is_file()
        and (fold.adapter_dir / "adapter_model.safetensors").is_file()
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
    if not all(
        path.is_file()
        for path in (summary_path, records_path, failures_path)
    ):
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        records = sum(
            bool(line.strip())
            for line in records_path.read_text(encoding="utf-8").splitlines()
        )
    except (OSError, json.JSONDecodeError):
        return False
    expected = EXPECTED_EVALUATION_COUNTS[fold.index]
    return (
        summary.get("sample_count") == expected
        and summary.get("total_samples") == expected
        and summary.get("runtime_failure_count") == 0
        and records == expected
    )


def _validate_visual_config(fold: Fold) -> dict[str, Any]:
    config = validate_training_config(
        fold.train_config,
        fold=fold.index,
        project_root=ROOT,
    )
    expected = {
        "lora_target": "all",
        "lora_rank": 8,
        "lora_alpha": 16,
        "lora_dropout": 0.25,
        "additional_target": "resampler",
        "freeze_vision_tower": False,
        "freeze_multi_modal_projector": False,
        "quantization_bit": 4,
        "quantization_method": "bnb",
        "double_quantization": True,
        "upcast_layernorm": True,
        "optim": "adamw_torch",
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 8,
        "learning_rate": 0.000005,
        "num_train_epochs": 3,
    }
    for field, value in expected.items():
        if config.get(field) != value:
            raise RuntimeError(
                f"{fold.train_config.name}: {field} 应为 {value!r}"
            )
    configured_output = (FINETUNE / str(config["output_dir"])).resolve()
    if configured_output != fold.adapter_dir.resolve():
        raise RuntimeError(
            f"{fold.train_config.name}: output_dir 与运行身份不一致"
        )
    return config


def _preflight() -> dict[str, Any]:
    release = validate_release(ROOT, verify_media=True)
    cli = Path(sys.executable).with_name("llamafactory-cli")
    if not cli.is_file():
        raise RuntimeError(f"llamafactory-cli 不存在: {cli}")
    rows = []
    for fold in FOLDS:
        config = _validate_visual_config(fold)
        if not fold.merge_config.is_file():
            raise RuntimeError(f"合并配置不存在: {fold.merge_config}")
        if fold.adapter_dir.exists() and not _training_complete(fold):
            raise RuntimeError(f"拒绝接管不完整训练目录: {fold.adapter_dir}")
        if fold.merged_dir.exists() and not _merged_complete(fold):
            raise RuntimeError(f"拒绝接管不完整合并目录: {fold.merged_dir}")
        rows.append(
            {
                "fold": fold.index,
                "dataset": config["dataset"],
                "training": (
                    "complete" if _training_complete(fold) else "pending"
                ),
                "merge": "complete" if _merged_complete(fold) else "pending",
                "evaluation": (
                    "complete" if _evaluation_complete(fold) else "pending"
                ),
            }
        )
    return {"release": release, "run_id": RUN_ID, "folds": rows}


def _run_logged(command: list[str], log_path: Path, *, cwd: Path) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=_runtime_env(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"命令退出码 {result.returncode}，请查看 {log_path}"
        )


def _train(fold: Fold) -> None:
    if not _training_complete(fold):
        _write_state("running", f"fold{fold.index}_training")
        _run_logged(
            [
                sys.executable,
                "train_with_contract.py",
                str(fold.train_config.relative_to(FINETUNE)),
            ],
            LOG_ROOT / f"fold{fold.index}_train.log",
            cwd=FINETUNE,
        )
    if not _training_complete(fold):
        raise RuntimeError(f"fold{fold.index}: 训练产物不完整")
    coverage = validate_adapter_coverage(fold.adapter_dir, visual=True)
    _write_state(
        "running",
        f"fold{fold.index}_training_complete",
        adapter_coverage=coverage,
    )


def _merge(fold: Fold) -> None:
    if _merged_complete(fold):
        return
    _write_state("running", f"fold{fold.index}_merging")
    _run_logged(
        [
            str(Path(sys.executable).with_name("llamafactory-cli")),
            "export",
            str(fold.merge_config.relative_to(FINETUNE)),
        ],
        LOG_ROOT / f"fold{fold.index}_merge.log",
        cwd=FINETUNE,
    )
    if not _merged_complete(fold):
        raise RuntimeError(f"fold{fold.index}: 合并产物不完整")


def _evaluate(fold: Fold) -> None:
    if _evaluation_complete(fold):
        return
    _write_state("running", f"fold{fold.index}_evaluating")
    _run_logged(
        [
            sys.executable,
            "-m",
            "finetune.run_v4_1_evaluation",
            "--fold",
            str(fold.index),
            "--model-dir",
            str(fold.merged_dir),
            "--out-dir",
            str(fold.result_dir),
        ],
        LOG_ROOT / f"fold{fold.index}_evaluate.log",
        cwd=ROOT,
    )
    if not _evaluation_complete(fold):
        raise RuntimeError(f"fold{fold.index}: 评测产物不完整")


def _write_summary() -> Path:
    rows = []
    for fold in FOLDS:
        summary = json.loads(
            (fold.result_dir / "evaluation_summary.json").read_text(
                encoding="utf-8"
            )
        )
        rows.append(
            {
                "fold": fold.index,
                "sample_count": summary["sample_count"],
                "metrics": summary["metrics"],
                "target_clip_state_distribution": summary[
                    "target_clip_state_distribution"
                ],
                "prediction_clip_state_distribution": summary[
                    "prediction_clip_state_distribution"
                ],
                "clip_state_confusion": summary["clip_state_confusion"],
            }
        )
    total = sum(row["sample_count"] for row in rows)
    metric_names = tuple(rows[0]["metrics"])
    weighted = {
        name: round(
            sum(
                row["metrics"][name] * row["sample_count"] for row in rows
            )
            / total,
            6,
        )
        for name in metric_names
        if name != "total"
    }
    output = RESULT_ROOT / "three_fold_summary.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": "tensile-v4.1-visual-three-fold-summary/v1",
                "run_id": RUN_ID,
                "release_id": RELEASE_ID,
                "inference_precision": "merged_bf16",
                "fold_count": 3,
                "total_samples": total,
                "weighted_metrics": weighted,
                "folds": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    preflight = _preflight()
    if args.validate_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0
    try:
        for fold in FOLDS:
            _train(fold)
            _merge(fold)
            _evaluate(fold)
        summary = _write_summary()
    except Exception as exc:
        _write_state(
            "failed",
            "visual_three_fold",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    _write_state(
        "completed",
        "visual_three_fold_complete",
        summary=str(summary),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
