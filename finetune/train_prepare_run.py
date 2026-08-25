#!/usr/bin/env python3
"""Prepare one semantic project-local V4.1 Prompt experiment."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.train_build_source_aware_dataset import (  # noqa: E402
    SourceAware3kError,
    _pretty_bytes,
    _sha256_bytes,
)
from pipeline.prompt_control import load_experiment_contract  # noqa: E402
from pipeline.prompt_control.core import sha256_file  # noqa: E402
from pipeline.project_workspace import (  # noqa: E402
    CURRENT_EXPERIMENT_ID,
    experiment_workspace_paths,
    validate_experiment_id,
)

FINETUNE = ROOT / "finetune"
DEFAULT_BASELINE_ROOT = (
    FINETUNE
    / "MiniCPM/config/active/v4_1_source_aware_3k_coverage_first"
)
SEED = 3411
ALLOWED_TRAIN_CHANGES = {
    "dataset",
    "eval_dataset",
    "dataset_dir",
    "media_dir",
    "model_name_or_path",
    "output_dir",
}
ALLOWED_MERGE_CHANGES = {
    "adapter_name_or_path",
    "export_dir",
    "model_name_or_path",
}


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


def _repo_relative(path: Path, project_root: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(project_root).resolve()))
    except ValueError as exc:
        raise SourceAware3kError(f"路径不属于当前项目: {path}") from exc


def _validate_input(
    input_dir: Path,
    experiment_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    input_dir = Path(input_dir).resolve()
    summary = _read_json(input_dir / "summary.json", "fixed Prompt input summary")
    experiment = load_experiment_contract(input_dir / "experiment_contract.json")
    if (
        summary.get("schema_version")
        != "tensile-vlm-v4.1-fixed-prompt-dataset-summary/v1"
        or summary.get("status") != "ready"
        or summary.get("immutable") is not True
        or summary.get("experiment_id") != experiment_id
        or summary.get("experiment_contract_sha256")
        != experiment.get("experiment_contract_sha256")
        or summary.get("train_row_count") != 3000
        or not isinstance(summary.get("validation_row_count"), int)
        or summary["validation_row_count"] <= 0
    ):
        raise SourceAware3kError("fixed Prompt input 身份、行数或状态非法")
    entries = summary.get("files")
    if not isinstance(entries, list):
        raise SourceAware3kError("fixed Prompt input files 缺失")
    required = {
        "dataset_info.json",
        "datasets/seed_3411.json",
        "datasets/fold_0_validation.json",
        "experiment_contract.json",
    }
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            raise SourceAware3kError("fixed Prompt input file entry 非法")
        relative = entry["path"]
        path = (input_dir / relative).resolve()
        if relative in seen or not path.is_relative_to(input_dir):
            raise SourceAware3kError("fixed Prompt input 包含重复或越界路径")
        seen.add(relative)
        if (
            not path.is_file()
            or path.stat().st_size != entry.get("size_bytes")
            or sha256_file(path) != entry.get("sha256")
        ):
            raise SourceAware3kError(f"fixed Prompt input 文件漂移: {path}")
    if not required <= seen:
        raise SourceAware3kError("fixed Prompt input 缺少受管文件")
    return summary, experiment


def _write_experiment_directory(
    target: Path,
    files: Mapping[str, bytes],
) -> None:
    if target.exists():
        for relative, content in files.items():
            path = target / relative
            if not path.is_file() or path.read_bytes() != content:
                raise SourceAware3kError(f"拒绝覆盖已有语义实验配置: {target}")
        unexpected = {
            str(path.relative_to(target))
            for path in target.rglob("*")
            if path.is_file()
        } - set(files)
        if unexpected:
            raise SourceAware3kError(
                f"语义实验目录包含未声明文件: {sorted(unexpected)}"
            )
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        for relative, content in files.items():
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        os.replace(staging, target)
    finally:
        if staging.exists():
            for path in sorted(staging.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging.rmdir()


def prepare_fixed_prompt_run(
    *,
    input_dir: Path,
    experiment_id: str = CURRENT_EXPERIMENT_ID,
    baseline_config_root: Path = DEFAULT_BASELINE_ROOT,
    project_root: Path = ROOT,
    training_code_commit: str | None = None,
    purpose: str = "验证简化决策指令是否降低标签偏置",
    baseline: str = "v4.1-coverage-first-seed3411",
    change_summary: str = "只保留视频证据、四字段标签池和 JSON 输出要求",
    early_stopping_steps: int | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Freeze semantic configs without changing model hyperparameters."""
    experiment_id = validate_experiment_id(experiment_id)
    project_root = Path(project_root).resolve()
    paths = experiment_workspace_paths(project_root, experiment_id)
    input_dir = Path(input_dir).resolve()
    if input_dir != paths.input.resolve():
        raise SourceAware3kError(
            f"input 目录必须与 experiment ID 一致: {paths.input}"
        )
    summary, experiment = _validate_input(input_dir, experiment_id)
    baseline_config_root = Path(baseline_config_root)
    baseline_train_path = baseline_config_root / f"train_seed{SEED}.yaml"
    baseline_merge_path = baseline_config_root / f"merge_seed{SEED}.yaml"
    baseline_train = _read_yaml(baseline_train_path, "baseline train config")
    baseline_merge = _read_yaml(baseline_merge_path, "baseline merge config")
    train = {
        **baseline_train,
        "model_name_or_path": "models/minicpm_v_4_5",
        "dataset": "tensile_v4_1_fixed_full_fields_seed3411",
        "eval_dataset": "tensile_v4_1_fixed_full_fields_fold0_val",
        "dataset_dir": _repo_relative(paths.input, project_root),
        "media_dir": "workspace/data",
        "output_dir": _repo_relative(paths.adapter, project_root),
    }
    if early_stopping_steps is not None:
        if early_stopping_steps <= 0:
            raise SourceAware3kError("early_stopping_steps 必须为正整数")
        train["early_stopping_steps"] = early_stopping_steps
    merge = {
        **baseline_merge,
        "model_name_or_path": "models/minicpm_v_4_5",
        "adapter_name_or_path": _repo_relative(paths.adapter, project_root),
        "export_dir": _repo_relative(paths.merged, project_root),
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
    allowed_train_changes = set(ALLOWED_TRAIN_CHANGES)
    if early_stopping_steps is not None:
        allowed_train_changes.add("early_stopping_steps")
    if train_differences != allowed_train_changes:
        raise SourceAware3kError(
            f"训练配置变化超出受控范围: {sorted(train_differences)}"
        )
    if merge_differences != ALLOWED_MERGE_CHANGES:
        raise SourceAware3kError(
            f"合并配置变化超出受控范围: {sorted(merge_differences)}"
        )
    expected_steps = math.ceil(
        int(summary["train_row_count"])
        / int(train["gradient_accumulation_steps"])
    ) * int(train["num_train_epochs"])
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
    experiment_path = input_dir / "experiment_contract.json"
    manifest = {
        "schema_version": "tensile-vlm-v4.1-semantic-experiment/v1",
        "immutable": True,
        "experiment_id": experiment_id,
        "status": "prepared",
        "seed": SEED,
        "paths": {
            "input": _repo_relative(paths.input, project_root),
            "adapter": _repo_relative(paths.adapter, project_root),
            "merged": _repo_relative(paths.merged, project_root),
            "evaluation": _repo_relative(paths.evaluation, project_root),
            "logs": _repo_relative(paths.logs, project_root),
        },
        "dataset_registry_sha256": sha256_file(input_dir / "dataset_info.json"),
        "training_json_sha256": sha256_file(
            input_dir / "datasets/seed_3411.json"
        ),
        "validation_json_sha256": sha256_file(
            input_dir / "datasets/fold_0_validation.json"
        ),
        "input_identity_sha256": summary["input_identity_sha256"],
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
        "early_stopping_steps": early_stopping_steps,
        "resolved_train_config": train,
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
            "evaluate": [
                sys.executable,
                "-m",
                "finetune.eval_run",
                "--fold",
                "0",
                "--release-id",
                str(experiment["release"]["release_id"]),
                "--model-dir",
                _repo_relative(paths.merged, project_root),
                "--out-dir",
                _repo_relative(paths.evaluation, project_root),
                "--experiment-contract",
                _repo_relative(experiment_path, project_root),
            ],
        },
        "environment": {
            "WANDB_MODE": "offline",
            "DOWNSAMPLE_MODE": "4x",
            "DISABLE_VERSION_CHECK": "1",
            "PYTHONPATH": (
                f"{project_root / 'LlamaFactory/src'}:{project_root}"
            ),
        },
    }
    semantic = {
        "id": experiment_id,
        "status": "prepared",
        "purpose": purpose,
        "baseline": baseline,
        "change": {
            "type": "prompt",
            "summary": change_summary,
        },
        "data_release": experiment["release"]["release_id"],
        "seed": SEED,
        "prompt_revision": experiment["prompt"]["revision_id"],
    }
    files = {
        "experiment.yaml": yaml.safe_dump(
            semantic,
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8"),
        "train.yaml": train_bytes,
        "merge.yaml": merge_bytes,
        "manifest.json": _pretty_bytes(manifest),
    }
    _write_experiment_directory(paths.git_dir, files)
    return paths.git_dir, manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", default=CURRENT_EXPERIMENT_ID)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument(
        "--baseline-config-root",
        type=Path,
        default=DEFAULT_BASELINE_ROOT,
    )
    parser.add_argument(
        "--purpose",
        default="验证简化决策指令是否降低标签偏置",
    )
    parser.add_argument(
        "--baseline",
        default="v4.1-coverage-first-seed3411",
    )
    parser.add_argument(
        "--change-summary",
        default="只保留视频证据、四字段标签池和 JSON 输出要求",
    )
    parser.add_argument("--early-stopping-steps", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = experiment_workspace_paths(ROOT, args.experiment_id)
    output, manifest = prepare_fixed_prompt_run(
        input_dir=args.input_dir or paths.input,
        experiment_id=args.experiment_id,
        baseline_config_root=args.baseline_config_root,
        purpose=args.purpose,
        baseline=args.baseline,
        change_summary=args.change_summary,
        early_stopping_steps=args.early_stopping_steps,
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
