#!/usr/bin/env python3
"""Prepare full-development train and merge configs without starting training."""

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

from finetune.build_v4_1_full_development_dataset import (  # noqa: E402
    DEFAULT_EXPERIMENT_ID,
    PARENT_CROSSVAL_EXPERIMENT_ID,
    ROWS_PER_EPOCH,
    TRAINING_SEED,
)
from finetune.build_v4_1_source_aware_3k import (  # noqa: E402
    SourceAware3kError,
    _pretty_bytes,
    _sha256_bytes,
)
from finetune.prepare_v4_1_fixed_prompt_run import (  # noqa: E402
    _read_yaml,
    _write_experiment_directory,
)
from pipeline.prompt_control import load_experiment_contract  # noqa: E402
from pipeline.prompt_control.core import sha256_file  # noqa: E402
from pipeline.project_workspace import validate_experiment_id  # noqa: E402

PARENT_CONFIG_ROOT = (
    ROOT / "finetune/experiments" / PARENT_CROSSVAL_EXPERIMENT_ID
)
NUM_TRAIN_EPOCHS = 2
EXPECTED_OPTIMIZER_STEPS = 750


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
        summary = json.loads((input_dir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAware3kError(f"无法读取 full-development summary: {exc}") from exc
    if (
        not isinstance(summary, dict)
        or summary.get("schema_version")
        != "tensile-vlm-v4.1-full-development-summary/v2"
        or summary.get("status") != "ready"
        or summary.get("immutable") is not True
        or summary.get("experiment_id") != experiment_id
        or summary.get("parent_crossval_experiment_id")
        != PARENT_CROSSVAL_EXPERIMENT_ID
        or summary.get("rows_per_epoch") != ROWS_PER_EPOCH
        or summary.get("unique_coverage_rate") != 1.0
    ):
        raise SourceAware3kError("full-development summary 身份或覆盖证明非法")
    for entry in summary.get("files") or []:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise SourceAware3kError("full-development file entry 非法")
        path = input_dir / entry["path"]
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("size_bytes")
            or sha256_file(path) != entry.get("sha256")
        ):
            raise SourceAware3kError(f"full-development input 文件漂移: {path}")
    return summary


def prepare_full_development_run(
    *,
    input_dir: Path,
    experiment_id: str = DEFAULT_EXPERIMENT_ID,
    parent_config_root: Path = PARENT_CONFIG_ROOT,
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
    experiment = load_experiment_contract(input_dir / "experiment_contract.json")
    parent_config_root = Path(parent_config_root)
    parent_train = _read_yaml(parent_config_root / "train_fold0.yaml", "parent train config")
    parent_merge = _read_yaml(parent_config_root / "merge_fold0.yaml", "parent merge config")

    run_dir = project_root / "workspace/runs" / experiment_id
    adapter = run_dir / "adapter"
    merged = run_dir / "merged"
    logs = run_dir / "logs"
    train = {
        **parent_train,
        "dataset": "tensile_v4_1_prompt_full_development",
        "dataset_dir": _relative(input_dir, project_root),
        "output_dir": _relative(adapter, project_root),
        "do_eval": False,
        "eval_strategy": "no",
        "load_best_model_at_end": False,
        "num_train_epochs": NUM_TRAIN_EPOCHS,
    }
    for field in (
        "eval_dataset",
        "eval_steps",
        "metric_for_best_model",
        "greater_is_better",
        "early_stopping_steps",
        "per_device_eval_batch_size",
    ):
        train.pop(field, None)
    merge = {
        **parent_merge,
        "adapter_name_or_path": _relative(adapter, project_root),
        "export_dir": _relative(merged, project_root),
    }
    expected_steps = math.ceil(
        ROWS_PER_EPOCH / int(train["gradient_accumulation_steps"])
    ) * NUM_TRAIN_EPOCHS
    pinned = {
        "seed": TRAINING_SEED,
        "learning_rate": 5e-6,
        "lora_rank": 8,
        "lora_alpha": 16,
        "lora_dropout": 0.25,
        "weight_decay": 0.2,
        "gradient_accumulation_steps": 8,
        "freeze_vision_tower": False,
        "freeze_multi_modal_projector": False,
        "additional_target": "resampler",
    }
    drift = {
        field: {"expected": expected, "actual": train.get(field)}
        for field, expected in pinned.items()
        if train.get(field) != expected
    }
    if expected_steps != EXPECTED_OPTIMIZER_STEPS or drift:
        raise SourceAware3kError(
            f"full-development 训练 recipe 漂移: steps={expected_steps}, drift={drift}"
        )
    if train.get("do_eval") is not False or train.get("load_best_model_at_end") is not False:
        raise SourceAware3kError("full-development 禁止 validation/best-checkpoint 选择")

    train_bytes = yaml.safe_dump(
        train, allow_unicode=True, sort_keys=False
    ).encode("utf-8")
    merge_bytes = yaml.safe_dump(
        merge, allow_unicode=True, sort_keys=False
    ).encode("utf-8")
    git_dir = project_root / "finetune/experiments" / experiment_id
    manifest = {
        "schema_version": "tensile-vlm-v4.1-full-development-run/v2",
        "immutable": True,
        "experiment_id": experiment_id,
        "status": "prepared",
        "parent_crossval_experiment_id": PARENT_CROSSVAL_EXPERIMENT_ID,
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
        "experiment_contract_file_sha256": sha256_file(
            input_dir / "experiment_contract.json"
        ),
        "experiment_contract_sha256": experiment[
            "experiment_contract_sha256"
        ],
        "dataset": {
            "rows_per_epoch": ROWS_PER_EPOCH,
            "published_candidate_count": summary["published_candidate_count"],
            "unique_coverage_rate": summary["unique_coverage_rate"],
            "repeat_count": summary["repeat_count"],
        },
        "recipe": {
            "seed": TRAINING_SEED,
            "num_train_epochs": NUM_TRAIN_EPOCHS,
            "expected_optimizer_steps": expected_steps,
            "validation_enabled": False,
            "early_stopping_enabled": False,
            "checkpoint_selection": "final_step_750",
            **pinned,
        },
        "paths": {
            "input": _relative(input_dir, project_root),
            "adapter": _relative(adapter, project_root),
            "merged": _relative(merged, project_root),
            "logs": _relative(logs, project_root),
        },
        "train_config": {
            "path": "train.yaml",
            "sha256": _sha256_bytes(train_bytes),
        },
        "merge_config": {
            "path": "merge.yaml",
            "sha256": _sha256_bytes(merge_bytes),
        },
        "commands": {
            "train": [
                sys.executable,
                "finetune/train_with_contract.py",
                f"finetune/experiments/{experiment_id}/train.yaml",
            ],
            "merge": [
                "llamafactory-cli",
                "export",
                f"finetune/experiments/{experiment_id}/merge.yaml",
            ],
        },
    }
    semantic = {
        "id": experiment_id,
        "status": "prepared",
        "purpose": "使用三折确认的 Prompt 与训练 recipe 训练全量 development LoRA",
        "baseline": PARENT_CROSSVAL_EXPERIMENT_ID,
        "change": {
            "type": "training_scope",
            "summary": "从三折切换为全量 development；无 validation；固定最终 step750",
        },
        "data_release": experiment["release"]["release_id"],
        "seed": TRAINING_SEED,
        "prompt_revision": experiment["prompt"]["revision_id"],
    }
    files = {
        "experiment.yaml": yaml.safe_dump(
            semantic, allow_unicode=True, sort_keys=False
        ).encode("utf-8"),
        "train.yaml": train_bytes,
        "merge.yaml": merge_bytes,
        "manifest.json": _pretty_bytes(manifest),
    }
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
    output, manifest = prepare_full_development_run(
        input_dir=input_dir,
        experiment_id=args.experiment_id,
    )
    print(json.dumps({"config_dir": str(output), **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
