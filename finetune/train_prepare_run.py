#!/usr/bin/env python3
"""Prepare one semantic project-local V4.1 Prompt experiment."""

from __future__ import annotations

import sys


def main() -> int:
    message = (
        "此历史训练/评测 CLI 已停用。请使用 python -m versioning train "
        "prepare / validate / run / export，显式指定 --root 和完整版本身份。"
        "参数与冻结输入说明见 versioning/SCRIPTS.md；不接受旧 YAML 或裸模型路径直接启动。"
    )
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


import argparse
import json
import math
import os
import subprocess
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


def _training_configs(training: Mapping) -> dict:
    scope = training.get("scope", "cross_validation")
    if scope == "full" and not training.get("folds") and isinstance(training.get("full"), dict):
        return {"full": training["full"]}
    if scope == "cross_validation" and set(training.get("folds", {})) == {"fold0", "fold1", "fold2"} and "full" not in training:
        return training["folds"]
    raise ValueError("frozen training scope/configuration mismatch")


def _validate_full_config(config: Mapping) -> None:
    # Independent acceptance data never selects a training checkpoint. Keep
    # the complete development set, with a user-frozen training schedule.
    forbidden = {"eval_dataset": (None, ""), "val_size": (None, 0),
        "do_eval": (None, False), "do_predict": (None, False),
        "eval_strategy": (None, "no"), "evaluation_strategy": (None, "no"),
        "load_best_model_at_end": (None, False), "early_stopping_steps": (None,),
        "max_samples": (None,)}
    if any(config.get(key) not in allowed for key, allowed in forbidden.items()):
        raise ValueError("full training forbids evaluation, implicit validation splits and sample truncation")


def prepare_versioned_run(*, root: Path, train_version: str, data_version: str,
                          prompt_version: str, media_root: Path, fold_configs: Mapping,
                          git_commit: str, environment: Mapping,
                          inputs_path: Path | None = None, scope: str = "cross_validation") -> Path:
    """Freeze a complete scoped invocation without creating MLflow Runs."""
    import fcntl
    from finetune.train_build_dataset import build_versioned_datasets
    from versioning.ids import parse_train_id, parse_data_id, parse_prompt_id
    from versioning.prompts import prompt_path

    protocols = {parse_train_id(train_version).protocol, parse_data_id(data_version).protocol,
                 parse_prompt_id(prompt_version).protocol}
    if len(protocols) != 1:
        raise ValueError("training input protocols differ")
    if not isinstance(git_commit, str) or not git_commit.strip():
        raise ValueError("git_commit is required")
    if not isinstance(environment, Mapping) or not environment:
        raise ValueError("environment versions are required")
    if scope not in {"cross_validation", "full"}:
        raise ValueError("unsupported training scope")
    required = {"full"} if scope == "full" else {"fold0", "fold1", "fold2"}
    if not isinstance(fold_configs, Mapping) or set(fold_configs) != required:
        raise ValueError(f"explicit {sorted(required)} configs are required")
    root = Path(root).absolute()
    run = root / "workspace/runs" / train_version
    target = run / "input"
    if any(path.is_symlink() for path in (target, *target.parents)):
        raise ValueError("training paths must not contain symlinks")
    files, binding = build_versioned_datasets(root=root, data_version=data_version,
        prompt_version=prompt_version, media_root=media_root, inputs_path=inputs_path, scope=scope)
    configs = {}
    for fold, source in fold_configs.items():
        if not isinstance(source, Mapping) or not source:
            raise ValueError("fold config must be a non-empty mapping")
        config = dict(source)
        if scope == "full":
            _validate_full_config(config)
        if config.get("tokenized_path") is not None:
            raise ValueError("tokenized_path may bypass frozen fold/Prompt inputs")
        model = config.get("model_name_or_path")
        if not isinstance(model, str) or not Path(model).is_absolute() or not Path(model).is_dir():
            raise ValueError("explicit existing base model directory is required")
        config.update(dataset=f"tensile_v4_1_{fold}_train", eval_dataset=None if scope == "full" else f"tensile_v4_1_{fold}_val",
            dataset_dir=str(target), media_dir=binding["media_root"], output_dir=str(run / fold / "adapter"))
        configs[fold] = config
    base_models = {config["model_name_or_path"] for config in configs.values()}
    if len(base_models) != 1:
        raise ValueError("all folds must bind the same base model")
    from versioning.registry import _artifact_tree
    base_model_files = _artifact_tree(Path(next(iter(base_models))))
    training = {"version": train_version, **binding, "git_commit": git_commit,
        "base_model_files": base_model_files,
        "base_model": next(iter(base_models)),
        **({"scope": "full", "folds": {}, "full": configs["full"]} if scope == "full" else {"folds": configs}),
        "data_inputs": str(Path(inputs_path).absolute()) if inputs_path is not None else None}
    files.update({"training.yaml": yaml.safe_dump(training, allow_unicode=True, sort_keys=True).encode(),
        "environment.yaml": yaml.safe_dump(dict(environment), allow_unicode=True, sort_keys=True).encode(),
        "data-version.txt": (data_version + "\n").encode(),
        "prompt.yaml": prompt_path(root, prompt_version).read_bytes()})
    inventory = {name: {"sha256": _sha256_bytes(content), "size": len(content)} for name, content in files.items()}
    files["input-manifest.json"] = _pretty_bytes(inventory)
    run.mkdir(parents=True, exist_ok=True)
    with (run / ".prepare.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if target.exists():
            if {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()} != set(files):
                raise ValueError("existing frozen input file set differs")
            for name, content in files.items():
                if (target / name).is_symlink() or (target / name).read_bytes() != content:
                    raise ValueError("existing frozen input differs")
            return target
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=run) as temporary:
            staging = Path(temporary) / "input"
            staging.mkdir()
            for name, content in files.items():
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                destination.chmod(0o444)
            os.rename(staging, target)
    return target


def verify_versioned_run(*, root: Path, train_version: str, for_execution: bool = True) -> dict[str, Any]:
    """Read and recheck all frozen bytes and their live upstream bindings."""
    from finetune.train_build_dataset import build_versioned_datasets
    from versioning.ids import parse_train_id
    from versioning.prompts import verify_frozen_prompt
    parse_train_id(train_version)
    root = Path(root).absolute()
    target = root / "workspace/runs" / train_version / "input"
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("frozen input paths must not contain symlinks")
    inventory = _read_json(target / "input-manifest.json", "frozen input manifest")
    if any(p.is_symlink() for p in target.rglob("*")):
        raise ValueError("frozen input contains a symlink")
    actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
    if actual != set(inventory) | {"input-manifest.json"}:
        raise ValueError("frozen input file set differs")
    for name, expected in inventory.items():
        path = target / name
        if (Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink()
                or not isinstance(expected, dict) or path.stat().st_mode & 0o222
                or sha256_file(path) != expected.get("sha256") or path.stat().st_size != expected.get("size")):
            raise ValueError(f"frozen input drift: {name}")
    training = _read_yaml(target / "training.yaml", "frozen training")
    if training.get("version") != train_version:
        raise ValueError("frozen train identity mismatch")
    configs = _training_configs(training)
    scope = training.get("scope", "cross_validation")
    for fold, config in configs.items():
        if scope == "full":
            _validate_full_config(config)
        if config.get("tokenized_path") is not None:
            raise ValueError("tokenized_path may bypass frozen fold/Prompt inputs")
        expected = {"dataset": f"tensile_v4_1_{fold}_train", "eval_dataset": None if scope == "full" else f"tensile_v4_1_{fold}_val",
                    "dataset_dir": str(target), "media_dir": training["media_root"],
                    "output_dir": str(target.parent / fold / "adapter"),
                    "model_name_or_path": training["base_model"]}
        if any(config.get(key) != value for key, value in expected.items()):
            raise ValueError("frozen fold routing mismatch")
    if not isinstance(training.get("base_model_files"), dict) or not training["base_model_files"]:
        raise ValueError("frozen training base model inventory is missing")
    if not for_execution:
        return training
    from versioning.registry import _artifact_tree
    if _artifact_tree(Path(training["base_model"])) != training["base_model_files"]:
        raise ValueError("frozen training base model drifted")
    verify_frozen_prompt(root, training["prompt_version"], train_version)
    files, binding = build_versioned_datasets(root=root, data_version=training["data_version"],
        prompt_version=training["prompt_version"], media_root=Path(training["media_root"]),
        inputs_path=Path(training["data_inputs"]) if training["data_inputs"] is not None else None, scope=scope)
    if any(training.get(key) != value for key, value in binding.items()):
        raise ValueError("frozen data binding mismatch")
    if any((target / name).read_bytes() != content for name, content in files.items()):
        raise ValueError("frozen datasets differ from declared release/Prompt")
    return training


def execute_versioned_run(*, root: Path, train_version: str):
    """Execute three frozen folds through the real tuner and MLflow events."""
    import fcntl
    from mlflow.tracking import MlflowClient
    from finetune.train_with_contract import run_training
    from versioning.mlflow_train import (open_train_store, create_train_run, execute_fold_run,
        log_train_summary, transition_train_state)
    root = Path(root).absolute()
    training = verify_versioned_run(root=root, train_version=train_version)
    run = root / "workspace/runs" / train_version
    with (run / ".execution.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("training version is already executing") from exc
        training = verify_versioned_run(root=root, train_version=train_version)
        configs = _training_configs(training)
        scope = training.get("scope", "cross_validation")
        for config in configs.values():
            if Path(config["output_dir"]).exists():
                raise ValueError("existing training output requires explicit recovery")
        params = {fold: json.dumps(config, ensure_ascii=False, sort_keys=True, allow_nan=False)
                  for fold, config in configs.items()}
        from mlflow.utils.validation import MAX_PARAM_VAL_LENGTH
        if any(len(value) > MAX_PARAM_VAL_LENGTH for value in params.values()):
            raise ValueError("frozen config exceeds MLflow parameter limit")
        store = open_train_store(root / "workspace/mlflow")
        parent = create_train_run(store, train_version, data_version=training["data_version"],
            prompt_version=training["prompt_version"], git_commit=training["git_commit"],
            base_model=training["base_model"], config=params, scope=scope)
        client = MlflowClient(tracking_uri=store.tracking_uri)
        metrics = []
        try:
            client.log_artifacts(parent.run_id, str(run / "input"), artifact_path="input")
            for name, config in configs.items():
                verify_versioned_run(root=root, train_version=train_version)
                def executor(actual_config):
                    run_training(actual_config)
                    verify_versioned_run(root=root, train_version=train_version)
                    return _read_json(Path(actual_config["output_dir"]) / "train_results.json", "actual train results")
                if scope == "full":
                    from copy import deepcopy
                    from versioning.mlflow_train import _validate_metrics
                    result = _validate_metrics(executor(deepcopy(config)))
                    if not all(math.isfinite(value) for value in result.values()):
                        raise ValueError("executor metrics must be finite")
                    metrics.append(result)
                else:
                    child = execute_fold_run(store, train_version, int(name[-1]), config, executor=executor)
                    client.set_tag(child.run_id, "output_artifact", f"runs:/{parent.run_id}/{name}/adapter")
                    metrics.append(child.metrics)
                client.log_artifacts(parent.run_id, config["output_dir"], artifact_path=f"{name}/adapter")
            common = set.intersection(*(set(item) for item in metrics))
            if not common:
                raise ValueError("no common actual metrics for training summary")
            summary = metrics[0] if scope == "full" else {
                f"{key}_mean": sum(item[key] for item in metrics) / 3 for key in common}
            log_train_summary(store, train_version, summary)
            # Freeze evidence only after the actual tuner returned every fold and
            # the uploaded weights/results match their recorded metrics.
            from versioning.registry import _training_execution_snapshot
            from versioning.mlflow_train import get_train_run
            snapshot = _training_execution_snapshot(store, get_train_run(store, train_version))
            proof = run / "training-evidence.json"
            proof.write_bytes(_pretty_bytes(snapshot))
            client.log_artifact(parent.run_id, str(proof))
            client.log_param(parent.run_id, "sha256_training_evidence", sha256_file(proof))
            parent = transition_train_state(store, train_version, "completed")
        except BaseException as exc:
            from versioning.mlflow_train import get_train_run
            try:
                if get_train_run(store, train_version).workflow_state == "running":
                    transition_train_state(store, train_version, "failed", run_status="FAILED")
            except Exception as tracking_error:
                exc.add_note(f"Failed to persist training failure: {tracking_error}")
            raise
        export_versioned_run(root=root, train_version=train_version)
        return parent


def export_versioned_run(*, root: Path, train_version: str) -> Path:
    """Recover an interrupted immutable export from the same completed Run."""
    from versioning.ids import parse_train_id
    from versioning.manifest import _publish_immutable
    from versioning.mlflow_train import open_train_store, validate_train_for_promotion
    root = Path(root).absolute()
    training = verify_versioned_run(root=root, train_version=train_version, for_execution=False)
    store = open_train_store(root / "workspace/mlflow")
    parent = validate_train_for_promotion(store, train_version)
    from versioning.registry import _validate_train_execution_artifacts
    _validate_train_execution_artifacts(store, parent, require_all_outputs=True)
    for key in ("data_version", "prompt_version", "git_commit", "base_model"):
        if getattr(parent, key) != training[key]:
            raise ValueError("frozen input differs from completed Run")
    if parent.scope != training.get("scope", "cross_validation"):
        raise ValueError("frozen scope differs from completed Run")
    for fold, config in _training_configs(training).items():
        if parent.config.get(fold) != json.dumps(config, ensure_ascii=False, sort_keys=True, allow_nan=False):
            raise ValueError("frozen fold config differs from completed Run")
    document = {"version": train_version, "protocol": "tensile-vlm/" + parse_train_id(train_version).protocol,
        "record_validity": parent.record_validity, "data_version": parent.data_version,
        "prompt_version": parent.prompt_version, "folds": list(parent.folds),
        **({"scope": "full"} if parent.scope == "full" else {}),
        "base_model": parent.base_model, "run_id": parent.run_id,
        "metrics": dict(parent.metrics), "git_commit": parent.git_commit}
    return _publish_immutable(root / "records/training" / train_version / "manifest.yaml",
        yaml.safe_dump(document, sort_keys=True, allow_unicode=True).encode(), label="training manifest")


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


def _legacy_main() -> int:
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
