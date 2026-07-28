#!/usr/bin/env python3
"""Prepare immutable seed3411 configs for one fixed-Prompt dataset bundle."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.build_v4_1_source_aware_3k import (  # noqa: E402
    SourceAware3kError,
    _pretty_bytes,
    _sha256_bytes,
    _write_immutable_directory,
)
from pipeline.prompt_control import load_experiment_contract  # noqa: E402
from pipeline.prompt_control.core import sha256_file  # noqa: E402

FINETUNE = ROOT / "finetune"
DEFAULT_BASELINE_ROOT = (
    FINETUNE
    / "MiniCPM/config/active/v4_1_source_aware_3k_coverage_first"
)
DEFAULT_CONFIG_PARENT = FINETUNE / "MiniCPM/config/active"
SEED = 3411
ALLOWED_TRAIN_CHANGES = {"dataset", "eval_dataset", "dataset_dir", "output_dir"}
ALLOWED_MERGE_CHANGES = {"adapter_name_or_path", "export_dir"}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAware3kError(f"无法读取 {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceAware3kError(f"{label} 必须是对象")
    return value


def _read_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceAware3kError(f"无法读取 {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceAware3kError(f"{label} 必须是对象")
    return value


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _relative_to_finetune(path: Path) -> str:
    return os.path.relpath(Path(path).resolve(), FINETUNE)


def _validate_bundle(bundle_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle_dir = Path(bundle_dir).resolve()
    summary = _read_json(bundle_dir / "summary.json", "fixed Prompt bundle summary")
    experiment = load_experiment_contract(bundle_dir / "experiment_contract.json")
    if (
        summary.get("schema_version")
        != "tensile-vlm-v4.1-fixed-prompt-dataset-summary/v1"
        or summary.get("status") != "ready"
        or summary.get("immutable") is not True
        or summary.get("experiment_contract_sha256")
        != experiment.get("experiment_contract_sha256")
        or summary.get("train_row_count") != 3000
        or not isinstance(summary.get("validation_row_count"), int)
        or summary["validation_row_count"] <= 0
    ):
        raise SourceAware3kError("fixed Prompt bundle 身份、行数或状态非法")
    entries = summary.get("files")
    if not isinstance(entries, list):
        raise SourceAware3kError("fixed Prompt bundle files 缺失")
    required = {
        "dataset_info.json",
        "datasets/seed_3411.json",
        "datasets/fold_0_validation.json",
        "experiment_contract.json",
    }
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise SourceAware3kError("fixed Prompt bundle file entry 非法")
        relative = entry["path"]
        path = (bundle_dir / relative).resolve()
        if relative in seen or not path.is_relative_to(bundle_dir):
            raise SourceAware3kError("fixed Prompt bundle 包含重复或越界路径")
        seen.add(relative)
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("size_bytes")
            or sha256_file(path) != entry.get("sha256")
        ):
            raise SourceAware3kError(f"fixed Prompt bundle 文件漂移: {path}")
    if not required <= seen:
        raise SourceAware3kError("fixed Prompt bundle 缺少受管文件")
    return summary, experiment


def prepare_fixed_prompt_run(
    *,
    bundle_dir: Path,
    baseline_config_root: Path = DEFAULT_BASELINE_ROOT,
    config_parent: Path = DEFAULT_CONFIG_PARENT,
    adapter_dir: Path | None = None,
    merged_dir: Path | None = None,
    training_code_commit: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Freeze train/merge configs and a manifest without changing hyperparameters."""
    bundle_dir = Path(bundle_dir).resolve()
    summary, experiment = _validate_bundle(bundle_dir)
    baseline_config_root = Path(baseline_config_root)
    baseline_train_path = baseline_config_root / f"train_seed{SEED}.yaml"
    baseline_merge_path = baseline_config_root / f"merge_seed{SEED}.yaml"
    baseline_train = _read_yaml(baseline_train_path, "baseline train config")
    baseline_merge = _read_yaml(baseline_merge_path, "baseline merge config")
    bundle_id = str(summary["bundle_id"])
    run_id = f"v4_1_fixed_prompt_{bundle_id.removeprefix('v4.1-fixed-prompt-')}_seed3411"
    adapter_dir = (
        Path(adapter_dir)
        if adapter_dir is not None
        else ROOT
        / "LlamaFactory/saves/minicpmv4_5/lora"
        / f"sft_tensile_{run_id}"
    )
    merged_dir = (
        Path(merged_dir)
        if merged_dir is not None
        else adapter_dir.with_name(f"{adapter_dir.name}_merged")
    )
    train = {
        **baseline_train,
        "dataset": "tensile_v4_1_fixed_full_fields_seed3411",
        "eval_dataset": "tensile_v4_1_fixed_full_fields_fold0_val",
        "dataset_dir": _relative_to_finetune(bundle_dir),
        "output_dir": _relative_to_finetune(adapter_dir),
    }
    merge = {
        **baseline_merge,
        "adapter_name_or_path": _relative_to_finetune(adapter_dir),
        "export_dir": _relative_to_finetune(merged_dir),
    }
    train_differences = {
        key
        for key in set(train) | set(baseline_train)
        if train.get(key) != baseline_train.get(key)
    }
    merge_differences = {
        key
        for key in set(merge) | set(baseline_merge)
        if merge.get(key) != baseline_merge.get(key)
    }
    if train_differences != ALLOWED_TRAIN_CHANGES:
        raise SourceAware3kError(
            f"训练配置变化超出受控范围: {sorted(train_differences)}"
        )
    if merge_differences != ALLOWED_MERGE_CHANGES:
        raise SourceAware3kError(
            f"合并配置变化超出受控范围: {sorted(merge_differences)}"
        )
    rows = int(summary["train_row_count"])
    accumulation = int(train["gradient_accumulation_steps"])
    epochs = int(train["num_train_epochs"])
    expected_steps = math.ceil(rows / accumulation) * epochs
    if train.get("seed") != SEED or expected_steps != 1125:
        raise SourceAware3kError("seed 或 optimizer steps 漂移")
    train_bytes = yaml.safe_dump(
        train,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")
    merge_bytes = yaml.safe_dump(
        merge,
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")
    experiment_path = bundle_dir / "experiment_contract.json"
    output = Path(config_parent) / run_id
    result_dir = FINETUNE / "results" / run_id / "seed3411/fold0"
    manifest = {
        "schema_version": "tensile-vlm-v4.1-fixed-prompt-run/v1",
        "immutable": True,
        "run_id": run_id,
        "seed": SEED,
        "bundle_id": bundle_id,
        "dataset_bundle_path": str(bundle_dir),
        "dataset_registry_sha256": sha256_file(bundle_dir / "dataset_info.json"),
        "training_json_sha256": sha256_file(
            bundle_dir / "datasets/seed_3411.json"
        ),
        "validation_json_sha256": sha256_file(
            bundle_dir / "datasets/fold_0_validation.json"
        ),
        "experiment_contract_path": str(experiment_path),
        "experiment_contract_file_sha256": sha256_file(experiment_path),
        "experiment_contract_sha256": experiment["experiment_contract_sha256"],
        "release": experiment["release"],
        "sampling": experiment["sampling"],
        "prompt": {
            "revision_id": experiment["prompt"]["revision_id"],
            "prompt_manifest_sha256": experiment["prompt"][
                "prompt_manifest_sha256"
            ],
            "prompt_content_sha256": experiment["prompt"][
                "prompt_content_sha256"
            ],
        },
        "base_model_identity": {
            "configured_path": train["model_name_or_path"],
        },
        "training_code_commit": training_code_commit or _git_commit(),
        "expected_optimizer_steps": expected_steps,
        "resolved_train_config": train,
        "train_config": {
            "path": f"train_seed{SEED}.yaml",
            "sha256": _sha256_bytes(train_bytes),
        },
        "merge_config": {
            "path": f"merge_seed{SEED}.yaml",
            "sha256": _sha256_bytes(merge_bytes),
        },
        "adapter_dir": str(adapter_dir.resolve()),
        "merged_dir": str(merged_dir.resolve()),
        "evaluation": {
            "fold": 0,
            "expected_samples": summary["validation_row_count"],
            "experiment_contract": str(experiment_path),
        },
        "commands": {
            "train": [
                sys.executable,
                str(FINETUNE / "train_with_contract.py"),
                str(output / f"train_seed{SEED}.yaml"),
            ],
            "merge": [
                "llamafactory-cli",
                "export",
                str(output / f"merge_seed{SEED}.yaml"),
            ],
            "evaluate": [
                sys.executable,
                "-m",
                "finetune.run_v4_1_evaluation",
                "--fold",
                "0",
                "--release-id",
                str(experiment["release"]["release_id"]),
                "--model-dir",
                str(merged_dir.resolve()),
                "--out-dir",
                str(result_dir),
                "--experiment-contract",
                str(experiment_path),
            ],
        },
        "environment": {
            "WANDB_MODE": "offline",
            "DOWNSAMPLE_MODE": "4x",
            "DISABLE_VERSION_CHECK": "1",
            "PYTHONPATH": f"{ROOT / 'LlamaFactory/src'}:{ROOT}",
        },
    }
    files = {
        f"train_seed{SEED}.yaml": train_bytes,
        f"merge_seed{SEED}.yaml": merge_bytes,
        "run_manifest.json": _pretty_bytes(manifest),
    }
    _write_immutable_directory(output, files=files, summary=manifest)
    return output, manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument(
        "--baseline-config-root",
        type=Path,
        default=DEFAULT_BASELINE_ROOT,
    )
    parser.add_argument("--config-parent", type=Path, default=DEFAULT_CONFIG_PARENT)
    parser.add_argument("--adapter-dir", type=Path)
    parser.add_argument("--merged-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output, manifest = prepare_fixed_prompt_run(
        bundle_dir=args.bundle_dir,
        baseline_config_root=args.baseline_config_root,
        config_parent=args.config_parent,
        adapter_dir=args.adapter_dir,
        merged_dir=args.merged_dir,
    )
    print(
        json.dumps(
            {"config_dir": str(output), **manifest},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
