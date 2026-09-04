"""可读版本控制统一 CLI。

所有正式对象都由调用方显式给出完整版本 ID；CLI 只编排既有领域模块，
不猜测 ``latest``、不自动分配修订号，也不连接本项目之外的环境。
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from versioning.backup import create_backup, restore_backup, verify_backup
from versioning.data_pipeline import run_stage
from versioning.data_release import load_release_metadata, validate_training_reference
from versioning.holdout import (
    ClaimIdentity,
    acquire_claim,
    freeze_pre_registration,
    load_pre_registration,
    validate_holdout_layout,
)
from versioning.manifest import (
    DataRecordRef,
    EvalRecordRef,
    PromptRecordRef,
    TrainRecordRef,
    export_manifest,
    export_model_manifest,
)
from versioning.materialize import materialize_current, validate_service_current
from versioning.mlflow_eval import (
    create_eval_fold_run,
    create_eval_run,
    end_eval_fold_run,
    get_eval_run,
    log_eval_aggregate,
    log_eval_summary,
    open_eval_store,
    transition_eval_state,
    validate_eval_for_conclusion,
)
from versioning.mlflow_train import (
    create_fold_run,
    create_train_run,
    end_fold_run,
    get_train_run,
    log_train_summary,
    open_train_store,
    transition_train_state,
)
from versioning.prompts import (
    create_prompt,
    freeze_prompt,
    load_prompt,
    verify_frozen_prompt,
)
from versioning.registry import (
    approve_model_for_production,
    finalize_model_evaluation,
    get_model,
    materialize_model,
    open_registry_store,
    register_model,
    set_alias,
    set_offline_backup_scope,
    validate_model_for_evaluation,
)
from versioning.state import IllegalStateCombination


class CLIUsageError(ValueError):
    """命令行参数组合不完整或不合法。"""


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, default=Path("."), help="项目根目录（默认当前目录）"
    )


def _add_store(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        type=Path,
        default=None,
        help="MLflow store 根目录（默认 <root>/workspace/mlflow）",
    )


def _store_path(args: argparse.Namespace) -> Path:
    return args.store if args.store is not None else args.root / "workspace" / "mlflow"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="versioning", description="mVllm2 可读版本控制统一入口"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    data = commands.add_parser("data", help="运行数据 pipeline 或管理 holdout claim")
    data.add_argument("action", help="七阶段名称，或 claim")
    _add_root(data)
    data.add_argument("--batch", default="batch-001", help="数据批次名")
    data.add_argument("--version", help="显式完整 data 版本")
    data.add_argument("--protocol", default="v4.1", help="release 协议标签")
    data.add_argument("--purpose", default="development", help="release 数据用途")
    data.add_argument("--results", type=Path, help="review_import 审查结果 YAML")
    data.add_argument("--pre-registration", type=Path, help="claim 对应的预注册 YAML")
    data.add_argument("--eval-version", help="claim 绑定的完整 eval 版本")
    data.add_argument("--model-version", help="claim 绑定的完整 model 版本")
    data.add_argument("--split", help="claim 绑定的数据 split")
    data.add_argument("--executor", help="claim 绑定的一次执行身份")

    prompt = commands.add_parser("prompt", help="注册、冻结或校验 Prompt")
    prompt.add_argument("action", choices=("create", "freeze", "verify", "show"))
    _add_root(prompt)
    prompt.add_argument("--version", help="显式完整 prompt 版本")
    prompt.add_argument("--protocol", help="Prompt 协议段，例如 v4.1")
    prompt.add_argument("--definition", type=Path, help="Prompt 定义 YAML")
    prompt.add_argument("--train-version", help="显式完整 train 版本")

    train = commands.add_parser("train", help="创建和推进训练记录")
    train.add_argument(
        "action",
        choices=("create", "fold-start", "fold-end", "summary", "complete", "show"),
    )
    train.add_argument("train_version", help="显式完整 train 版本")
    _add_root(train)
    _add_store(train)
    train.add_argument("--data-version", help="显式完整 data 版本")
    train.add_argument("--prompt-version", help="显式完整 prompt 版本")
    train.add_argument("--git-commit", help="实际 Git commit")
    train.add_argument("--base-model", help="基础模型身份")
    train.add_argument("--config", type=Path, help="训练配置 YAML mapping")
    train.add_argument("--fold", type=int, help="fold 编号")
    train.add_argument("--params", type=Path, help="fold 参数 YAML mapping")
    train.add_argument("--metrics", type=Path, help="指标 YAML mapping")
    train.add_argument("--run-status", default="FINISHED", help="fold 终态")

    evaluate = commands.add_parser("eval", help="创建、推进或导出测评记录")
    evaluate.add_argument(
        "action",
        choices=(
            "create",
            "fold-start",
            "fold-end",
            "aggregate",
            "summary",
            "complete",
            "show",
            "manifest",
        ),
    )
    evaluate.add_argument("eval_version", help="显式完整 eval 版本")
    _add_root(evaluate)
    _add_store(evaluate)
    evaluate.add_argument("--model-version", help="显式完整 model 版本")
    evaluate.add_argument(
        "--model-version-number", type=int, help="MLflow 数值 Model Version"
    )
    evaluate.add_argument("--data-version", help="显式完整 data 版本")
    evaluate.add_argument("--config", help="测评配置引用")
    evaluate.add_argument("--git-commit", help="实际 Git commit")
    evaluate.add_argument(
        "--scope", choices=("single_fold", "cross_validation", "full")
    )
    evaluate.add_argument("--split", help="single_fold/full 或 holdout split")
    evaluate.add_argument("--pre-registration", type=Path, help="holdout 预注册 YAML")
    evaluate.add_argument("--executor", help="holdout claim 执行身份")
    evaluate.add_argument("--fold", type=int, help="fold 编号")
    evaluate.add_argument("--model-artifact", help="fold 模型 artifact 引用")
    evaluate.add_argument("--data-split", help="fold 数据 split")
    evaluate.add_argument("--sample-count", type=int, help="fold 样本数")
    evaluate.add_argument("--records", help="fold 结果记录引用")
    evaluate.add_argument("--failures", help="fold 失败记录引用")
    evaluate.add_argument("--metrics", type=Path, help="指标 YAML mapping")
    evaluate.add_argument("--folds", help="聚合 fold，逗号分隔，例如 0,1,2")
    evaluate.add_argument("--run-status", default="FINISHED", help="fold 终态")
    evaluate.add_argument("--outcome", choices=("passed", "failed"))
    evaluate.add_argument("--source-train", help="manifest 来源 train 版本")
    evaluate.add_argument("--prompt-version", help="manifest 使用的 prompt 版本")
    evaluate.add_argument("--result-refs", type=Path, help="manifest 结果引用 YAML")
    evaluate.add_argument("--target", type=Path, help="manifest 输出路径")

    model = commands.add_parser("model", help="注册、晋级、路由或物化模型")
    model.add_argument(
        "action",
        choices=(
            "register",
            "finalize",
            "scope",
            "approve",
            "alias",
            "materialize",
            "manifest",
            "current",
            "validate-current",
            "show",
        ),
    )
    model.add_argument("model_version", nargs="?", help="显式完整 model 版本")
    _add_root(model)
    _add_store(model)
    model.add_argument("--train-version", help="来源 train 版本")
    model.add_argument("--eval-version", help="关联 eval 版本")
    model.add_argument("--backup-scope", choices=("adapter", "production_bundle"))
    model.add_argument("--alias", choices=("candidate", "production"))
    model.add_argument("--models-root", type=Path, help="物化目标根目录")
    model.add_argument(
        "--source-scope", choices=("single_fold", "cross_validation", "full")
    )
    model.add_argument("--artifacts", type=Path, help="模型 artifacts YAML mapping")
    model.add_argument("--deploy-target", help="唯一部署 artifact 路径")
    model.add_argument("--target", type=Path, help="model manifest 输出路径")
    model.add_argument("--records-root", type=Path, help="Git records 所在项目根")
    model.add_argument(
        "--service-mode", choices=("development", "production")
    )

    backup = commands.add_parser("backup", help="创建、校验或恢复离线备份")
    backup.add_argument("action", choices=("create", "verify", "restore"))
    _add_root(backup)
    _add_store(backup)
    backup.add_argument("--backup-root", type=Path, required=True, help="备份根目录")
    backup.add_argument("--data-root", type=Path, help="data 根目录")
    backup.add_argument("--prompts-root", type=Path, help="Prompt 项目根目录")
    backup.add_argument("--models-root", type=Path, help="物化模型根目录")
    backup.add_argument("--mlflow-root", type=Path, help="恢复目标 MLflow 根目录")
    return parser


def _required(args: argparse.Namespace, *names: str) -> None:
    missing = [name.replace("_", "-") for name in names if getattr(args, name) is None]
    if missing:
        raise CLIUsageError(
            "缺少必填参数: " + ", ".join(f"--{name}" for name in missing)
        )


def _load_mapping(
    path: Path | None, label: str, *, allow_empty: bool = False
) -> dict[str, Any]:
    if path is None:
        raise CLIUsageError(f"缺少必填参数: --{label.replace('_', '-')}")
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"无法读取 {label} YAML: {exc}") from exc
    if not isinstance(raw, Mapping) or (not raw and not allow_empty):
        qualifier = "可为空" if allow_empty else "非空"
        raise ValueError(f"{label} YAML 必须是{qualifier} mapping")
    return dict(raw)


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _emit(value: Any) -> None:
    print(json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True))


def _required_mapping_fields(mapping: Mapping[str, Any], *names: str) -> None:
    missing = [name for name in names if name not in mapping]
    if missing:
        raise CLIUsageError("定义缺少字段: " + ", ".join(missing))


def _sha256_file(path: Path) -> tuple[Path, str]:
    resolved = Path(path).resolve()
    try:
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except Exception as exc:
        raise ValueError(f"无法读取文件并计算摘要 {resolved}: {exc}") from exc
    return resolved, digest


def _handle_data(args: argparse.Namespace) -> Any:
    if args.action == "claim":
        _required(
            args,
            "version",
            "eval_version",
            "model_version",
            "split",
            "executor",
            "pre_registration",
        )
        meta = load_release_metadata(args.root / "data", args.version)
        if meta.purpose != "holdout":
            raise ValueError("data claim 只允许 purpose=holdout 的 release")
        validate_holdout_layout(
            args.root / "data" / "releases" / args.version
        )
        identity = ClaimIdentity(
            eval_version=args.eval_version,
            model_version=args.model_version,
            data_version=args.version,
            split=args.split,
        )
        frozen_pre_registration = freeze_pre_registration(
            args.pre_registration, args.root / "evaluations", args.eval_version
        )
        pre = load_pre_registration(frozen_pre_registration)
        if (
            pre.eval_version,
            pre.model_version,
            pre.data_version,
            pre.split,
        ) != (
            identity.eval_version,
            identity.model_version,
            identity.data_version,
            identity.split,
        ):
            raise ValueError("pre_registration 与 claim 身份不一致")
        _, preregistration_sha256 = _sha256_file(frozen_pre_registration)
        return acquire_claim(
            args.root / "data" / "releases" / args.version / "authorization",
            identity,
            args.executor,
            pre_registration_sha256=preregistration_sha256,
        )

    kwargs: dict[str, Any] = {}
    if args.action == "release_validate":
        _required(args, "version")
    if args.action != "release_validate":
        kwargs["batch"] = args.batch
    if args.action == "release":
        _required(args, "version")
        kwargs.update(version=args.version, protocol=args.protocol, purpose=args.purpose)
    elif args.action == "release_validate":
        kwargs["version"] = args.version
    if args.action == "review_import" and args.results is not None:
        kwargs["results_path"] = args.results
    return run_stage(args.root, args.action, **kwargs)


def _handle_prompt(args: argparse.Namespace) -> Any:
    _required(args, "version")
    if args.action == "create":
        _required(args, "protocol", "definition")
        definition = _load_mapping(args.definition, "definition")
        _required_mapping_fields(definition, "system_prompt", "user_prompt", "output_fields")
        return {
            "version": create_prompt(
                args.root,
                args.protocol,
                version=args.version,
                system_prompt=definition["system_prompt"],
                user_prompt=definition["user_prompt"],
                output_fields=definition["output_fields"],
                protocol_label=definition.get("protocol_label"),
            )
        }
    if args.action == "show":
        return load_prompt(args.root, args.version)
    _required(args, "train_version")
    if args.action == "freeze":
        return {"path": freeze_prompt(args.root, args.version, args.train_version)}
    verify_frozen_prompt(args.root, args.version, args.train_version)
    return {"verified": True}


def _handle_train(args: argparse.Namespace) -> Any:
    if args.action == "create":
        _required(
            args,
            "data_version",
            "prompt_version",
            "git_commit",
            "base_model",
            "config",
        )
        validate_training_reference(args.root / "data", args.data_version)
        verify_frozen_prompt(args.root, args.prompt_version, args.train_version)
        config = _load_mapping(args.config, "config")
        store = open_train_store(_store_path(args))
        return create_train_run(
            store,
            args.train_version,
            data_version=args.data_version,
            prompt_version=args.prompt_version,
            git_commit=args.git_commit,
            base_model=args.base_model,
            config=config,
        )

    params: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    if args.action == "fold-start":
        _required(args, "fold")
        params = (
            _load_mapping(args.params, "params", allow_empty=True) if args.params else None
        )
    elif args.action == "fold-end":
        _required(args, "fold")
        metrics = _load_mapping(args.metrics, "metrics") if args.metrics else None
    elif args.action == "summary":
        metrics = _load_mapping(args.metrics, "metrics")

    store = open_train_store(_store_path(args))
    if args.action == "show":
        return get_train_run(store, args.train_version)
    if args.action == "fold-start":
        return create_fold_run(store, args.train_version, args.fold, params=params)
    if args.action == "fold-end":
        return end_fold_run(
            store, args.train_version, args.fold, args.run_status, metrics=metrics
        )
    if args.action == "summary":
        return log_train_summary(store, args.train_version, metrics)
    return transition_train_state(store, args.train_version, "completed")


def _parse_folds(value: str | None) -> tuple[int, ...]:
    if value is None:
        raise CLIUsageError("缺少必填参数: --folds")
    try:
        return tuple(int(item) for item in value.split(",") if item != "")
    except ValueError as exc:
        raise CLIUsageError("--folds 必须是逗号分隔的整数") from exc


def _handle_eval(args: argparse.Namespace) -> Any:
    if args.action == "create":
        _required(
            args,
            "model_version",
            "model_version_number",
            "data_version",
            "config",
            "git_commit",
            "scope",
        )
        meta = load_release_metadata(args.root / "data", args.data_version)
        pre_registration = args.pre_registration
        if meta.purpose == "holdout":
            _required(args, "pre_registration", "executor")
            validate_holdout_layout(
                args.root / "data" / "releases" / args.data_version
            )
            pre_registration = freeze_pre_registration(
                args.pre_registration, args.root / "evaluations", args.eval_version
            )
        validate_model_for_evaluation(
            open_registry_store(_store_path(args), data_root=args.root / "data"),
            args.model_version,
            args.model_version_number,
        )
        store = open_eval_store(_store_path(args))
        return create_eval_run(
            store,
            args.eval_version,
            model_id=args.model_version,
            model_version_number=args.model_version_number,
            data_version=args.data_version,
            config=args.config,
            git_commit=args.git_commit,
            scope=args.scope,
            split=args.split,
            data_root=args.root / "data",
            pre_registration=pre_registration,
            executor=args.executor,
        )
    metrics: dict[str, Any] | None = None
    folds: tuple[int, ...] | None = None
    result_refs: dict[str, Any] | None = None
    if args.action == "manifest":
        _required(args, "source_train", "prompt_version", "result_refs", "target")
        result_refs = _load_mapping(args.result_refs, "result_refs")
    elif args.action == "fold-start":
        _required(
            args,
            "fold",
            "model_artifact",
            "data_split",
            "sample_count",
            "records",
            "failures",
        )
    elif args.action == "fold-end":
        _required(args, "fold")
        metrics = _load_mapping(args.metrics, "metrics") if args.metrics else None
    elif args.action == "aggregate":
        metrics = _load_mapping(args.metrics, "metrics")
        folds = _parse_folds(args.folds)
    elif args.action == "summary":
        metrics = _load_mapping(args.metrics, "metrics")
    elif args.action == "complete":
        _required(args, "outcome")

    store = open_eval_store(_store_path(args))
    if args.action == "show":
        return get_eval_run(store, args.eval_version)
    if args.action == "fold-start":
        return create_eval_fold_run(
            store,
            args.eval_version,
            args.fold,
            model_artifact=args.model_artifact,
            data_split=args.data_split,
            sample_count=args.sample_count,
            records=args.records,
            failures=args.failures,
        )
    if args.action == "fold-end":
        return end_eval_fold_run(
            store, args.eval_version, args.fold, args.run_status, metrics=metrics
        )
    if args.action == "aggregate":
        return log_eval_aggregate(store, args.eval_version, metrics, folds=folds)
    if args.action == "summary":
        return log_eval_summary(store, args.eval_version, metrics)
    if args.action == "complete":
        try:
            current = get_eval_run(store, args.eval_version)
        except IllegalStateCombination:
            # transition_eval_state 能识别并修复自身的 completed/RUNNING 半提交。
            current = None
        if current is not None and current.pre_registration_path is not None:
            _required(args, "pre_registration", "executor")
        pre_registration = args.pre_registration
        if pre_registration is not None:
            pre_registration = freeze_pre_registration(
                pre_registration, args.root / "evaluations", args.eval_version
            )
        return transition_eval_state(
            store,
            args.eval_version,
            "completed",
            outcome=args.outcome,
            pre_registration=pre_registration,
            executor=args.executor,
        )

    record = validate_eval_for_conclusion(store, args.eval_version)
    registry_store = open_registry_store(
        _store_path(args), data_root=args.root / "data"
    )
    model_record = validate_model_for_evaluation(
        registry_store, record.model_id, record.model_version_number
    )
    if model_record.eval_id != record.eval_id:
        raise CLIUsageError("manifest 导出要求模型已 finalize 到当前 eval")
    if model_record.train_id != args.source_train:
        raise CLIUsageError(
            f"source_train {args.source_train!r} 与模型来源 {model_record.train_id!r} 不一致"
        )
    train_store = open_train_store(_store_path(args))
    train_record = get_train_run(train_store, args.source_train)
    return {
        "path": export_manifest(
            args.target,
            data=DataRecordRef(args.root / "data", train_record.data_version),
            prompt=PromptRecordRef(args.root, args.prompt_version),
            train=TrainRecordRef(train_store, args.source_train),
            eval=EvalRecordRef(
                eval_id=record.eval_id,
                model_version=record.model_id,
                source_train=args.source_train,
                data_version=record.data_version,
                scope=record.scope,
                folds=tuple(record.folds),
                outcome=record.outcome or "",
                result_refs=result_refs,
                record_validity=record.record_validity,
            ),
        )
    }


def _handle_model(args: argparse.Namespace) -> Any:
    if args.action not in {"current", "validate-current"} and args.model_version is None:
        raise CLIUsageError("缺少显式完整 model 版本")
    if args.action == "register":
        _required(args, "train_version", "source_scope", "artifacts")
        if args.source_scope != "cross_validation":
            _required(args, "deploy_target")
        elif args.deploy_target is not None:
            raise CLIUsageError("cross_validation 不接受 --deploy-target")
    elif args.action == "finalize":
        _required(args, "eval_version")
    elif args.action == "scope":
        _required(args, "backup_scope")
    elif args.action == "alias":
        _required(args, "alias")
    elif args.action == "manifest":
        _required(args, "target")
    elif args.action in {"current", "validate-current"}:
        _required(args, "alias", "service_mode")
    store = open_registry_store(_store_path(args), data_root=args.root / "data")
    if args.action == "register":
        return register_model(
            store,
            args.model_version,
            train_id=args.train_version,
            source_scope=args.source_scope,
            artifacts=_load_mapping(args.artifacts, "artifacts"),
            deploy_target=args.deploy_target,
        )
    if args.action == "finalize":
        return finalize_model_evaluation(
            store, args.model_version, eval_id=args.eval_version
        )
    if args.action == "scope":
        return set_offline_backup_scope(store, args.model_version, args.backup_scope)
    if args.action == "approve":
        return approve_model_for_production(store, args.model_version)
    if args.action == "alias":
        return set_alias(store, args.model_version, args.alias)
    if args.action == "materialize":
        target_root = (
            args.models_root
            or args.root / "workspace" / "models" / "materialized"
        )
        return {"path": materialize_model(store, args.model_version, target_root)}
    if args.action == "manifest":
        return {
            "path": export_model_manifest(
                args.target, store=store, model_id=args.model_version
            )
        }
    if args.action in {"current", "validate-current"}:
        models_root = args.models_root or args.root / "workspace" / "models"
        records_root = args.records_root or args.root
        if args.action == "current":
            return {
                "path": materialize_current(
                    store,
                    alias=args.alias,
                    service_mode=args.service_mode,
                    models_root=models_root,
                    records_root=records_root,
                )
            }
        return validate_service_current(
            store,
            alias=args.alias,
            service_mode=args.service_mode,
            models_root=models_root,
            records_root=records_root,
        )
    return get_model(store, args.model_version)


def _handle_backup(args: argparse.Namespace) -> Any:
    data_root = args.data_root or args.root / "data"
    prompts_root = args.prompts_root or args.root
    models_root = (
        args.models_root or args.root / "workspace" / "models" / "materialized"
    )
    if args.action == "verify":
        return verify_backup(args.backup_root)
    if args.action == "restore":
        _required(args, "mlflow_root")
        restore_backup(
            args.backup_root,
            data_root=data_root,
            prompts_root=prompts_root,
            models_root=models_root,
            mlflow_root=args.mlflow_root,
        )
        return {"restored": True}
    return create_backup(
        open_registry_store(_store_path(args), data_root=data_root),
        data_root=data_root,
        prompts_root=prompts_root,
        models_root=models_root,
        backup_root=args.backup_root,
    )


_HANDLERS = {
    "data": _handle_data,
    "prompt": _handle_prompt,
    "train": _handle_train,
    "eval": _handle_eval,
    "model": _handle_model,
    "backup": _handle_backup,
}


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口；成功输出确定性 JSON，领域错误返回 1，用法错误返回 2。"""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        result = _HANDLERS[args.command](args)
    except CLIUsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _emit(result)
    return 0
