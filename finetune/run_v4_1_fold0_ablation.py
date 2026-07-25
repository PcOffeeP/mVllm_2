"""Run fold0 visual/data ablations, merge models, and compare inference."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from finetune.build_v4_1_visual_data_experiment import (
    EXPERIMENT_NAME,
    validate_adapter_coverage,
    validate_experiment_config,
)
from finetune.v4_1_runtime import validate_release

ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "finetune"
CONFIG_DIR = FINETUNE / "MiniCPM/config/experiments/v4_1"
SAVE_ROOT = ROOT / "LlamaFactory/saves/minicpmv4_5/lora/experiments/v4_1"
RESULT_ROOT = (
    FINETUNE
    / "results/v4_1_0_760050fad303_20260723/fold0_ablation"
)
LOG_ROOT = FINETUNE / "run_logs/v4_1_fold0_ablation"
STATE_PATH = LOG_ROOT / "state.json"
BASELINE_SUMMARY = (
    FINETUNE
    / "results/v4_1_0_760050fad303_20260723/"
    "three_fold_validation/fold0/evaluation_summary.json"
)


@dataclass(frozen=True)
class Variant:
    name: str
    run_name: str
    train_config_name: str
    merge_config_name: str
    visual: bool
    augmented: bool

    @property
    def train_config(self) -> Path:
        return CONFIG_DIR / self.train_config_name

    @property
    def merge_config(self) -> Path:
        return CONFIG_DIR / self.merge_config_name

    @property
    def adapter_dir(self) -> Path:
        return SAVE_ROOT / self.run_name

    @property
    def merged_dir(self) -> Path:
        return SAVE_ROOT / f"{self.run_name}_merged"

    @property
    def result_dir(self) -> Path:
        return RESULT_ROOT / self.name


VARIANTS = (
    Variant(
        name="visual_only",
        run_name=(
            "sft_tensile_v4_1_0_760050fad303_20260723_fold0_visual"
        ),
        train_config_name="train_v4_1_fold0_visual.yaml",
        merge_config_name="merge_v4_1_fold0_visual.yaml",
        visual=True,
        augmented=False,
    ),
    Variant(
        name="augmented_language",
        run_name=(
            f"sft_tensile_{EXPERIMENT_NAME}_20260723_fold0_language"
        ),
        train_config_name="train_v4_1_fold0_augmented_language.yaml",
        merge_config_name="merge_v4_1_fold0_augmented_language.yaml",
        visual=False,
        augmented=True,
    ),
    Variant(
        name="augmented_visual",
        run_name=(
            f"sft_tensile_{EXPERIMENT_NAME}_20260723_fold0_visual"
        ),
        train_config_name="train_v4_1_fold0_augmented_visual.yaml",
        merge_config_name="merge_v4_1_fold0_augmented_visual.yaml",
        visual=True,
        augmented=True,
    ),
)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取 JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON 不是对象: {path}")
    return value


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
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "tensile-v4.1-fold0-ablation/v1",
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


def _run_logged(command: list[str], log_path: Path, *, cwd: Path = ROOT) -> None:
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


def _training_complete(variant: Variant) -> bool:
    return (
        (variant.adapter_dir / "trainer_state.json").is_file()
        and (variant.adapter_dir / "train_results.json").is_file()
        and (variant.adapter_dir / "adapter_config.json").is_file()
        and any(
            (variant.adapter_dir / name).is_file()
            for name in ("adapter_model.safetensors", "adapter_model.bin")
        )
    )


def _merged_complete(variant: Variant) -> bool:
    return (
        (variant.merged_dir / "config.json").is_file()
        and (variant.merged_dir / "tokenizer_config.json").is_file()
        and any(variant.merged_dir.glob("model*.safetensors"))
    )


def _evaluation_complete(variant: Variant) -> bool:
    summary_path = variant.result_dir / "evaluation_summary.json"
    records_path = variant.result_dir / "evaluation_records.jsonl"
    if not summary_path.is_file() or not records_path.is_file():
        return False
    try:
        summary = _read_object(summary_path)
        record_count = sum(
            bool(line.strip())
            for line in records_path.read_text(encoding="utf-8").splitlines()
        )
    except OSError:
        return False
    return (
        summary.get("total_samples") == 425
        and summary.get("sample_count") == 425
        and summary.get("runtime_failure_count") == 0
        and record_count == 425
    )


def _preflight(variants: tuple[Variant, ...]) -> dict[str, Any]:
    release = validate_release(ROOT, verify_media=True)
    cli = Path(sys.executable).with_name("llamafactory-cli")
    if not cli.is_file():
        raise RuntimeError(f"llamafactory-cli 不存在: {cli}")
    if not BASELINE_SUMMARY.is_file():
        raise RuntimeError(f"fold0 基线评估不存在: {BASELINE_SUMMARY}")
    rows = []
    for variant in variants:
        validate_experiment_config(
            variant.train_config,
            visual=variant.visual,
            augmented=variant.augmented,
        )
        if not variant.merge_config.is_file():
            raise RuntimeError(f"合并配置不存在: {variant.merge_config}")
        if variant.adapter_dir.exists() and not _training_complete(variant):
            raise RuntimeError(f"拒绝接管不完整训练目录: {variant.adapter_dir}")
        if variant.merged_dir.exists() and not _merged_complete(variant):
            raise RuntimeError(f"拒绝接管不完整合并目录: {variant.merged_dir}")
        rows.append(
            {
                "variant": variant.name,
                "training": (
                    "complete" if _training_complete(variant) else "pending"
                ),
                "merge": (
                    "complete" if _merged_complete(variant) else "pending"
                ),
                "evaluation": (
                    "complete" if _evaluation_complete(variant) else "pending"
                ),
            }
        )
    return {
        "release": release,
        "llamafactory_cli": str(cli),
        "variants": rows,
    }


def _prepare_augmented_data() -> None:
    _write_state("running", "preparing_augmented_data")
    _run_logged(
        [
            sys.executable,
            "-m",
            "finetune.build_v4_1_visual_data_experiment",
        ],
        LOG_ROOT / "prepare_augmented_data.log",
    )


def _train(variant: Variant) -> None:
    if _training_complete(variant):
        validate_adapter_coverage(
            variant.adapter_dir,
            visual=variant.visual,
        )
        return
    _write_state("running", f"{variant.name}_training")
    _run_logged(
        [
            str(Path(sys.executable).with_name("llamafactory-cli")),
            "train",
            str(variant.train_config.relative_to(FINETUNE)),
        ],
        LOG_ROOT / f"{variant.name}_train.log",
        cwd=FINETUNE,
    )
    if not _training_complete(variant):
        raise RuntimeError(f"{variant.name}: 训练产物不完整")
    validate_adapter_coverage(
        variant.adapter_dir,
        visual=variant.visual,
    )


def _merge(variant: Variant) -> None:
    if _merged_complete(variant):
        return
    _write_state("running", f"{variant.name}_merging")
    _run_logged(
        [
            str(Path(sys.executable).with_name("llamafactory-cli")),
            "export",
            str(variant.merge_config.relative_to(FINETUNE)),
        ],
        LOG_ROOT / f"{variant.name}_merge.log",
        cwd=FINETUNE,
    )
    if not _merged_complete(variant):
        raise RuntimeError(f"{variant.name}: 合并产物不完整")


def _evaluate(variant: Variant) -> None:
    if _evaluation_complete(variant):
        return
    _write_state("running", f"{variant.name}_evaluating")
    _run_logged(
        [
            sys.executable,
            "-m",
            "finetune.run_v4_1_evaluation",
            "--fold",
            "0",
            "--model-dir",
            str(variant.merged_dir),
            "--out-dir",
            str(variant.result_dir),
        ],
        LOG_ROOT / f"{variant.name}_evaluate.log",
    )
    if not _evaluation_complete(variant):
        raise RuntimeError(f"{variant.name}: 评估产物不完整或存在运行异常")


def _state_recalls(summary: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    confusion = summary.get("clip_state_confusion")
    if not isinstance(confusion, Mapping):
        return result
    for state, raw_counts in confusion.items():
        if not isinstance(raw_counts, Mapping):
            continue
        counts = Counter(
            {str(key): int(value) for key, value in raw_counts.items()}
        )
        total = sum(counts.values())
        result[str(state)] = (
            round(counts[str(state)] / total, 6) if total else 0.0
        )
    return result


def _write_comparison(variants: tuple[Variant, ...]) -> Path:
    baseline = _read_object(BASELINE_SUMMARY)
    rows: list[dict[str, Any]] = []
    all_items = [("baseline", baseline)]
    for variant in variants:
        all_items.append(
            (
                variant.name,
                _read_object(
                    variant.result_dir / "evaluation_summary.json"
                ),
            )
        )
    for name, summary in all_items:
        metrics = summary.get("metrics")
        if not isinstance(metrics, Mapping):
            raise RuntimeError(f"{name}: metrics 缺失")
        prediction_distribution = summary.get(
            "prediction_clip_state_distribution"
        )
        rows.append(
            {
                "variant": name,
                "sample_count": summary["total_samples"],
                "runtime_failure_count": summary["runtime_failure_count"],
                "contract_valid_rate": metrics["contract_valid_rate"],
                "joint_correct_rate": metrics["joint_correct_rate"],
                "clip_state_correct_rate": metrics[
                    "clip_state_correct_rate"
                ],
                "state_recalls": _state_recalls(summary),
                "prediction_clip_state_distribution": (
                    prediction_distribution
                    if isinstance(prediction_distribution, Mapping)
                    else {}
                ),
            }
        )
    payload = {
        "schema_version": "tensile-v4.1-fold0-ablation-comparison/v1",
        "base_release_id": "v4.1.0-760050fad303",
        "experimental_data": {
            "name": EXPERIMENT_NAME,
            "human_reviewed": False,
            "production_eligible": False,
        },
        "results": rows,
    }
    path = RESULT_ROOT / "comparison_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=tuple(item.name for item in VARIANTS),
        default=[item.name for item in VARIANTS],
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_names = set(args.variants)
    selected = tuple(
        item for item in VARIANTS if item.name in selected_names
    )
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    preflight = _preflight(selected)
    if args.validate_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 0
    try:
        if any(item.augmented for item in selected):
            _prepare_augmented_data()
        for variant in selected:
            _train(variant)
            _merge(variant)
            _evaluate(variant)
        comparison = _write_comparison(selected)
    except Exception as exc:
        _write_state(
            "failed",
            "fold0_ablation",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    _write_state(
        "completed",
        "fold0_ablation_complete",
        comparison_summary=str(comparison),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
