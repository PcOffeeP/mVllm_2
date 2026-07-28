#!/usr/bin/env python3
"""Prepare three sequential prompt-controlled V4.1 training folds."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.build_v4_1_prompt_crossval_dataset import (  # noqa: E402
    DEFAULT_EXPERIMENT_ID,
    FOLDS,
    ROWS_PER_FOLD,
    TRAINING_SEED,
)
from finetune.build_v4_1_source_aware_3k import (  # noqa: E402
    SourceAware3kError,
    _pretty_bytes,
    _sha256_bytes,
)
from finetune.prepare_v4_1_fixed_prompt_run import (  # noqa: E402
    DEFAULT_BASELINE_ROOT,
    _read_yaml,
    _write_experiment_directory,
)
from pipeline.prompt_control import load_experiment_contract  # noqa: E402
from pipeline.prompt_control.core import sha256_file  # noqa: E402
from pipeline.project_workspace import validate_experiment_id  # noqa: E402

NUM_TRAIN_EPOCHS = 2
EVAL_STEPS = 25
SAVE_STEPS = 25
EARLY_STOPPING_STEPS = 3


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError as exc:
        raise SourceAware3kError(f"路径不属于项目: {path}") from exc


def _read_summary(input_dir: Path, experiment_id: str) -> dict[str, Any]:
    try:
        value = json.loads((input_dir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAware3kError(f"无法读取 crossval input summary: {exc}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version")
        != "tensile-vlm-v4.1-prompt-crossval-summary/v1"
        or value.get("status") != "ready"
        or value.get("immutable") is not True
        or value.get("experiment_id") != experiment_id
        or [item.get("fold") for item in value.get("folds") or []]
        != list(FOLDS)
    ):
        raise SourceAware3kError("crossval input summary 身份或 fold 列表非法")
    for entry in value.get("files") or []:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise SourceAware3kError("crossval input file entry 非法")
        path = input_dir / entry["path"]
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("size_bytes")
            or sha256_file(path) != entry.get("sha256")
        ):
            raise SourceAware3kError(f"crossval input 文件漂移: {path}")
    return value


def prepare_prompt_crossval_run(
    *,
    input_dir: Path,
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    baseline_config_root: Path = DEFAULT_BASELINE_ROOT,
    project_root: Path = ROOT,
    training_code_commit: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    experiment_id = validate_experiment_id(experiment_id)
    project_root = Path(project_root).resolve()
    input_dir = Path(input_dir).resolve()
    expected_input = project_root / "workspace/runs" / experiment_id / "input"
    if input_dir != expected_input:
        raise SourceAware3kError(f"input 目录与 experiment ID 不一致: {expected_input}")
    summary = _read_summary(input_dir, experiment_id)
    contract_path = input_dir / "experiment_contract.json"
    experiment = load_experiment_contract(contract_path)
    baseline_train = _read_yaml(
        Path(baseline_config_root) / f"train_seed{TRAINING_SEED}.yaml",
        "baseline train config",
    )
    baseline_merge = _read_yaml(
        Path(baseline_config_root) / f"merge_seed{TRAINING_SEED}.yaml",
        "baseline merge config",
    )
    git_dir = project_root / "finetune/experiments" / experiment_id
    run_dir = project_root / "workspace/runs" / experiment_id
    files: dict[str, bytes] = {}
    fold_records: list[dict[str, Any]] = []
    for fold in FOLDS:
        adapter = run_dir / f"fold{fold}/adapter"
        merged = run_dir / f"fold{fold}/merged"
        evaluation = run_dir / f"fold{fold}/evaluation"
        train = {
            **baseline_train,
            "model_name_or_path": "models/minicpm_v_4_5",
            "dataset": f"tensile_v4_1_prompt_cv_fold{fold}_train",
            "eval_dataset": f"tensile_v4_1_prompt_cv_fold{fold}_val",
            "dataset_dir": _relative(input_dir, project_root),
            "media_dir": "workspace/data",
            "output_dir": _relative(adapter, project_root),
            "save_steps": SAVE_STEPS,
            "eval_steps": EVAL_STEPS,
            "num_train_epochs": NUM_TRAIN_EPOCHS,
            "early_stopping_steps": EARLY_STOPPING_STEPS,
        }
        merge = {
            **baseline_merge,
            "model_name_or_path": "models/minicpm_v_4_5",
            "adapter_name_or_path": _relative(adapter, project_root),
            "export_dir": _relative(merged, project_root),
        }
        expected_steps = math.ceil(
            ROWS_PER_FOLD / int(train["gradient_accumulation_steps"])
        ) * NUM_TRAIN_EPOCHS
        if (
            train.get("seed") != TRAINING_SEED
            or expected_steps != 750
            or train.get("learning_rate") != baseline_train.get("learning_rate")
            or train.get("lora_dropout") != 0.25
            or train.get("weight_decay") != 0.2
        ):
            raise SourceAware3kError("crossval 训练超参数或 optimizer step 非预期")
        train_bytes = yaml.safe_dump(
            train, allow_unicode=True, sort_keys=False
        ).encode("utf-8")
        merge_bytes = yaml.safe_dump(
            merge, allow_unicode=True, sort_keys=False
        ).encode("utf-8")
        files[f"train_fold{fold}.yaml"] = train_bytes
        files[f"merge_fold{fold}.yaml"] = merge_bytes
        fold_records.append(
            {
                "fold": fold,
                "train_config": {
                    "path": f"train_fold{fold}.yaml",
                    "sha256": _sha256_bytes(train_bytes),
                },
                "merge_config": {
                    "path": f"merge_fold{fold}.yaml",
                    "sha256": _sha256_bytes(merge_bytes),
                },
                "paths": {
                    "adapter": _relative(adapter, project_root),
                    "merged": _relative(merged, project_root),
                    "evaluation": _relative(evaluation, project_root),
                },
                "expected_max_optimizer_steps": expected_steps,
            }
        )

    manifest = {
        "schema_version": "tensile-vlm-v4.1-prompt-crossval-run/v1",
        "immutable": True,
        "experiment_id": experiment_id,
        "status": "prepared",
        "training_code_commit": training_code_commit or _git_commit(),
        "release": experiment["release"],
        "sampling": experiment["sampling"],
        "prompt": {
            "revision_id": experiment["prompt"]["revision_id"],
            "prompt_content_sha256": experiment["prompt"][
                "prompt_content_sha256"
            ],
            "prompt_manifest_sha256": experiment["prompt"][
                "prompt_manifest_sha256"
            ],
        },
        "input_identity_sha256": summary["input_identity_sha256"],
        "experiment_contract_file_sha256": sha256_file(contract_path),
        "experiment_contract_sha256": experiment[
            "experiment_contract_sha256"
        ],
        "overfit_controls": {
            "num_train_epochs": NUM_TRAIN_EPOCHS,
            "eval_steps": EVAL_STEPS,
            "save_steps": SAVE_STEPS,
            "early_stopping_patience": EARLY_STOPPING_STEPS,
            "metric_for_best_model": "eval_loss",
            "load_best_model_at_end": True,
            "unchanged_learning_rate": baseline_train["learning_rate"],
            "unchanged_lora_dropout": baseline_train["lora_dropout"],
            "unchanged_weight_decay": baseline_train["weight_decay"],
        },
        "folds": fold_records,
        "command": [
            sys.executable,
            "finetune/run_v4_1_prompt_crossval.py",
            "--experiment-id",
            experiment_id,
        ],
    }
    files["experiment.yaml"] = yaml.safe_dump(
        {
            "id": experiment_id,
            "status": "prepared",
            "purpose": "用精简 Prompt 和抗过拟合训练日程完成三折训练",
            "baseline": "v4.1-coverage-first-seed3411",
            "change": {
                "type": "prompt_and_training_schedule",
                "summary": "三折固定数据；2 epoch 上限；25-step 验证；patience=3",
            },
            "data_release": experiment["release"]["release_id"],
            "seed": TRAINING_SEED,
            "prompt_revision": experiment["prompt"]["revision_id"],
        },
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")
    files["manifest.json"] = _pretty_bytes(manifest)
    _write_experiment_directory(git_dir, files)
    return git_dir, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", default=DEFAULT_EXPERIMENT_ID)
    parser.add_argument("--input-dir", type=Path)
    args = parser.parse_args()
    input_dir = args.input_dir or (
        ROOT / "workspace/runs" / args.experiment_id / "input"
    )
    output, manifest = prepare_prompt_crossval_run(
        input_dir=input_dir,
        experiment_id=args.experiment_id,
    )
    print(json.dumps({"config_dir": str(output), **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
