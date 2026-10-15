"""B8 — MLflow Model Registry：唯一 mVllm2、晋级门、alias 路由与物化导出。

对应设计 §2.9、§2.11、§5.4、§6、§7、§9、§10、§11.6、§13.1。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import threading
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from versioning.data_release import validate_training_reference
from versioning.ids import (
    parse_data_id,
    parse_eval_id,
    parse_model_id,
    parse_prompt_id,
    parse_train_id,
)
from versioning.mlflow_eval import (
    EvalRecordNotFound,
    EvalRecordStore,
    IllegalEvalRecord,
    IncompleteEvalRecord,
    InvalidEvalRecord,
    get_eval_run,
    open_eval_store,
    validate_eval_for_conclusion,
)
from versioning.mlflow_train import (
    IllegalTrainRecord,
    IncompleteTrainRecord,
    InvalidTrainRecord,
    TrainRecordNotFound,
    TrainRecordStore,
    get_train_run,
    open_train_store,
    validate_train_for_promotion,
)
from versioning.state import IllegalTransition, RecordValidity, transition_record_validity


REGISTERED_MODEL_NAME: str = "mVllm2"
ALIASES: tuple[str, ...] = ("candidate", "production")
BACKUP_SCOPES: tuple[str, ...] = ("adapter", "production_bundle")

MODEL_ID_TAG: str = "model_id"
TRAIN_ID_TAG: str = "train_id"
EVAL_ID_TAG: str = "eval_id"
DATA_VERSION_TAG: str = "data_version"
PROMPT_VERSION_TAG: str = "prompt_version"
GIT_COMMIT_TAG: str = "git_commit"
RECORD_VALIDITY_TAG: str = "record_validity"
OFFLINE_BACKUP_SCOPE_TAG: str = "offline_backup_scope"
PRODUCTION_APPROVED_TAG: str = "production_approved"
SOURCE_SCOPE_TAG: str = "source_scope"
ARTIFACTS_TAG: str = "artifacts"
DEPLOY_TARGET_TAG: str = "deploy_target"
BASE_MODEL_TAG: str = "base_model"
SOURCE_SCOPES: tuple[str, ...] = ("single_fold", "cross_validation", "full", "base", "diagnostic_fold")
SOURCE_KIND_TAG = "source_kind"
SOURCE_EVIDENCE_TAG = "source_evidence"

MATERIALIZED_METADATA_FILE: str = "materialized.yaml"
MATERIALIZED_ARTIFACTS_DIR: str = "artifacts"

TRAIN_EXPERIMENT_NAME: str = "mVllm2-training"
EVAL_EXPERIMENT_NAME: str = "mVllm2-evaluation"
REGISTRY_LOCK_FILE: str = ".registry.lock"
_LOCAL_LOCKS_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, threading.RLock] = {}


class MLflowRegistryError(ValueError):
    """Registry 域异常基类。"""


class RegistryModelNotFound(MLflowRegistryError):
    """指定 model 未注册 / alias 无目标 / 删除不存在的 alias。"""


class ModelVersionConflict(MLflowRegistryError):
    """同一 model-v... 已注册；冲突检测优先于一切晋级门。"""


class IllegalRegistryRecord(MLflowRegistryError):
    """输入/结构违规：非法 alias 名、未知 scope 值、读取 fail-closed。"""


class PromotionGateRejected(MLflowRegistryError):
    """晋级门 fail-closed：train 门、eval 门、scope 前置、批准缺失等。"""


class InvalidModelRecord(MLflowRegistryError):
    """record_validity=invalid 的模型被下游校验拒绝。"""


@dataclass(frozen=True)
class ModelRegistryStore:
    """Registry store 句柄（与 B6/B7 同根共用同一 SQLite）。"""

    root: Path
    tracking_uri: str
    artifact_location: str
    registered_model: str
    train_experiment_id: str
    eval_experiment_id: str
    data_root: Path


@dataclass(frozen=True)
class RegisteredModelRecord:
    """注册模型记录只读快照。"""

    model_id: str
    version: int
    registered_model: str
    run_id: str
    train_id: str | None
    eval_id: str | None
    data_version: str | None
    prompt_version: str | None
    git_commit: str
    base_model: str
    source_scope: str
    artifacts: dict[str, dict[str, str]]
    deploy_target: str | None
    record_validity: str
    offline_backup_scope: str | None
    production_approved: bool
    aliases: tuple[str, ...]
    source_kind: str = "trained"
    source_evidence: dict[str, Any] = field(default_factory=dict)
    performance_eval_id: str | None = None


@contextmanager
def _registry_write_lock(store: ModelRegistryStore):
    """串行化 Registry 的读改写事务，阻止同 ID 重复创建或绑定覆盖。"""
    lock_path = store.root / REGISTRY_LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(lock_path.resolve())
    with _LOCAL_LOCKS_GUARD:
        local_lock = _LOCAL_LOCKS.setdefault(key, threading.RLock())
    with local_lock:
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def registry_snapshot_lock(store: ModelRegistryStore):
    """冻结 Registry 写入，供需要跨多文件的一致性只读快照使用。"""
    with _registry_write_lock(store):
        yield


def _client(store: ModelRegistryStore | TrainRecordStore | EvalRecordStore) -> MlflowClient:
    """按 store 句柄构造独立 MLflow Client。"""
    from versioning.backup import scoped_mlflow_client
    return scoped_mlflow_client(tracking_uri=store.tracking_uri)


def _train_store(store: ModelRegistryStore) -> TrainRecordStore:
    return TrainRecordStore(
        root=store.root,
        tracking_uri=store.tracking_uri,
        experiment_id=store.train_experiment_id,
        artifact_location=store.artifact_location,
    )


def _eval_store(store: ModelRegistryStore) -> EvalRecordStore:
    return EvalRecordStore(
        root=store.root,
        tracking_uri=store.tracking_uri,
        experiment_id=store.eval_experiment_id,
        artifact_location=store.artifact_location,
    )


def _validate_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise IllegalRegistryRecord(f"{name} 必须是非空字符串: {value!r}")
    return value


def _validate_model_layout(
    source_scope: Any,
    artifacts: Any,
    deploy_target: Any,
) -> tuple[str, dict[str, dict[str, str]], str | None]:
    """校验模型产物范围；只有唯一部署目标的单折/full 模型可路由。"""
    if source_scope not in SOURCE_SCOPES:
        raise IllegalRegistryRecord(f"source_scope 非法: {source_scope!r}")
    if not isinstance(artifacts, dict) or not artifacts:
        raise IllegalRegistryRecord("artifacts 必须是非空 mapping")
    normalized: dict[str, dict[str, str]] = {}
    for scope_name, entries in artifacts.items():
        if not isinstance(scope_name, str) or not scope_name:
            raise IllegalRegistryRecord("artifacts scope 必须是非空字符串")
        if not isinstance(entries, dict) or not entries:
            raise IllegalRegistryRecord(f"artifacts.{scope_name} 必须是非空 mapping")
        normalized[scope_name] = {}
        for kind, path in entries.items():
            if not isinstance(kind, str) or not kind or not isinstance(path, str) or not path:
                raise IllegalRegistryRecord("artifact 名称和路径必须是非空字符串")
            parts = Path(path).parts
            if (
                Path(path).is_absolute()
                or ".." in parts
                or "." in parts
                or len(parts) < 3
                or parts[0] != "artifacts"
                or parts[1] != scope_name
            ):
                raise IllegalRegistryRecord(
                    "artifact 路径必须位于 "
                    f"artifacts/{scope_name}/... 且为规范安全相对路径: {path!r}"
                )
            normalized[scope_name][kind] = path

    expected = {
        "single_fold": {"fold0"},
        "cross_validation": {"fold0", "fold1", "fold2"},
        "full": {"full"},
        "base": {"base"},
        "diagnostic_fold": set(normalized),
    }[source_scope]
    if source_scope == "diagnostic_fold" and (
        len(normalized) != 1 or next(iter(normalized)) not in {"fold0", "fold1", "fold2"}
    ):
        raise IllegalRegistryRecord("diagnostic_fold requires exactly one actual fold")
    if set(normalized) != expected:
        raise IllegalRegistryRecord(
            f"artifacts scope {sorted(normalized)} 与 source_scope={source_scope!r} 不一致"
        )
    all_paths = {path for entries in normalized.values() for path in entries.values()}
    if source_scope in {"cross_validation", "base", "diagnostic_fold"}:
        if deploy_target is not None:
            raise IllegalRegistryRecord(f"{source_scope} 的 deploy_target 必须为 null")
        return source_scope, normalized, None
    if not isinstance(deploy_target, str) or not deploy_target:
        raise IllegalRegistryRecord(f"{source_scope} 必须有唯一 deploy_target")
    if deploy_target not in all_paths:
        raise IllegalRegistryRecord("deploy_target 必须精确引用 artifacts 中的一个路径")
    return source_scope, normalized, deploy_target


def _search_registered_model(client: MlflowClient) -> Any:
    """确保 Registered Model 存在；缺失则创建。"""
    try:
        return client.get_registered_model(REGISTERED_MODEL_NAME)
    except MlflowException:
        return client.create_registered_model(REGISTERED_MODEL_NAME)


def _search_experiment(client: MlflowClient, name: str) -> str:
    """按名复用/新建实验，返回 experiment_id。"""
    experiment = client.get_experiment_by_name(name)
    if experiment is None:
        return client.create_experiment(
            name=name,
            artifact_location=str(Path(Path(client.tracking_uri.replace("sqlite:///", "")).parent / "artifacts").resolve()),
        )
    return experiment.experiment_id


def open_registry_store(
    root: Path, *, data_root: Path | None = None
) -> ModelRegistryStore:
    """创建（缺失时）本地 SQLite + artifact store，复用/新建 mVllm2-training/mVllm2-evaluation 实验与 mVllm2 Registered Model。"""
    root = Path(root)
    if data_root is None:
        if root.name == "mlflow" and root.parent.name == "workspace":
            data_root = root.parent.parent / "data"
        else:
            data_root = root.parent / "data"
    root.mkdir(parents=True, exist_ok=True)
    artifact_path = root / "artifacts"
    artifact_path.mkdir(parents=True, exist_ok=True)
    tracking_uri = f"sqlite:///{root.resolve().as_posix()}/mlflow.db"

    client = MlflowClient(tracking_uri=tracking_uri)
    _search_registered_model(client)

    train_experiment_id = _search_experiment(client, TRAIN_EXPERIMENT_NAME)
    eval_experiment_id = _search_experiment(client, EVAL_EXPERIMENT_NAME)

    return ModelRegistryStore(
        root=root,
        tracking_uri=tracking_uri,
        artifact_location=str(artifact_path.resolve()),
        registered_model=REGISTERED_MODEL_NAME,
        train_experiment_id=train_experiment_id,
        eval_experiment_id=eval_experiment_id,
        data_root=Path(data_root),
    )


def _raw_model_versions(client: MlflowClient) -> list[Any]:
    return list(client.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'"))


def _fetch_version_by_model_id(client: MlflowClient, model_id: str) -> Any:
    """按 model_id tag 检索数值版本；不存在/重复均抛域异常。"""
    matches = [
        mv for mv in _raw_model_versions(client)
        if mv.tags.get(MODEL_ID_TAG) == model_id
    ]
    if not matches:
        raise RegistryModelNotFound(f"未找到 model: {model_id}")
    if len(matches) > 1:
        raise IllegalRegistryRecord(f"model_id {model_id} 对应多个数值版本")
    return matches[0]


def _validate_model_version_tags(version: Any, *, expected_model_id: str | None = None) -> None:
    """读取 fail-closed：校验全部绑定 tag 的值域与可解析性。"""
    tags = version.tags

    model_id = tags.get(MODEL_ID_TAG)
    try:
        parse_model_id(model_id)
    except Exception as exc:
        raise IllegalRegistryRecord(f"model_id tag 非法: {model_id!r}") from exc
    if expected_model_id is not None and model_id != expected_model_id:
        raise IllegalRegistryRecord(
            f"model_id tag {model_id!r} 与请求 {expected_model_id!r} 不一致"
        )

    source_kind = tags.get(SOURCE_KIND_TAG, "trained")
    if source_kind not in {"base", "trained"}:
        raise IllegalRegistryRecord("source_kind must be base or trained")
    if source_kind == "base":
        if any(key in tags for key in (TRAIN_ID_TAG, DATA_VERSION_TAG, PROMPT_VERSION_TAG)):
            raise IllegalRegistryRecord("base source must not contain fabricated training references")
        if tags.get(SOURCE_SCOPE_TAG) != "base":
            raise IllegalRegistryRecord("base source scope differs")
    else:
        train_id = tags.get(TRAIN_ID_TAG)
        try:
            parse_train_id(train_id)
        except Exception as exc:
            raise IllegalRegistryRecord(f"train_id tag 非法: {train_id!r}") from exc
        if tags.get(SOURCE_SCOPE_TAG) == "base":
            raise IllegalRegistryRecord("trained source cannot use base scope")

    eval_id = tags.get(EVAL_ID_TAG)
    if eval_id is not None:
        try:
            parse_eval_id(eval_id)
        except Exception as exc:
            raise IllegalRegistryRecord(f"eval_id tag 非法: {eval_id!r}") from exc
    if tags.get("performance_eval_id") is not None:
        try:
            parse_eval_id(tags["performance_eval_id"])
        except Exception as exc:
            raise IllegalRegistryRecord("performance_eval_id tag 非法") from exc

    if source_kind == "trained":
        try:
            parse_data_id(tags.get(DATA_VERSION_TAG))
            parse_prompt_id(tags.get(PROMPT_VERSION_TAG))
        except Exception as exc:
            raise IllegalRegistryRecord("trained data_version/prompt_version tag 非法") from exc
    if source_kind == "base" or tags.get(SOURCE_SCOPE_TAG) == "diagnostic_fold":
        try:
            evidence = json.loads(tags[SOURCE_EVIDENCE_TAG])
            if not isinstance(evidence, dict) or evidence.get("schema") != "tensile-model-source/v1":
                raise ValueError("source evidence schema differs")
        except (KeyError, ValueError, TypeError) as exc:
            raise IllegalRegistryRecord("source evidence is missing or malformed") from exc

    _validate_non_empty_string(tags.get(GIT_COMMIT_TAG), "git_commit")
    _validate_non_empty_string(tags.get(BASE_MODEL_TAG), "base_model")

    try:
        artifacts = json.loads(tags.get(ARTIFACTS_TAG, ""))
    except Exception as exc:
        raise IllegalRegistryRecord("artifacts tag 不是合法 JSON") from exc
    _validate_model_layout(
        tags.get(SOURCE_SCOPE_TAG), artifacts, tags.get(DEPLOY_TARGET_TAG)
    )

    record_validity = tags.get(RECORD_VALIDITY_TAG)
    if record_validity not in (RecordValidity.VALID.value, RecordValidity.INVALID.value):
        raise IllegalRegistryRecord(f"record_validity tag 非法: {record_validity!r}")

    offline_backup_scope = tags.get(OFFLINE_BACKUP_SCOPE_TAG)
    if offline_backup_scope is not None and offline_backup_scope not in BACKUP_SCOPES:
        raise IllegalRegistryRecord(
            f"offline_backup_scope tag 非法: {offline_backup_scope!r}"
        )

    production_approved = tags.get(PRODUCTION_APPROVED_TAG)
    if production_approved is not None and production_approved != "true":
        raise IllegalRegistryRecord(
            f"production_approved tag 非法: {production_approved!r}"
        )


def _build_record(version: Any) -> RegisteredModelRecord:
    """由已通过校验的 MLflow ModelVersion 构造快照。"""
    tags = version.tags
    aliases = sorted(alias for alias in version.aliases if alias in ALIASES)
    return RegisteredModelRecord(
        model_id=tags[MODEL_ID_TAG],
        version=int(version.version),
        registered_model=version.name,
        run_id=version.run_id,
        train_id=tags.get(TRAIN_ID_TAG),
        eval_id=tags.get(EVAL_ID_TAG),
        data_version=tags.get(DATA_VERSION_TAG),
        prompt_version=tags.get(PROMPT_VERSION_TAG),
        git_commit=tags[GIT_COMMIT_TAG],
        base_model=tags[BASE_MODEL_TAG],
        source_scope=tags[SOURCE_SCOPE_TAG],
        artifacts=json.loads(tags[ARTIFACTS_TAG]),
        deploy_target=tags.get(DEPLOY_TARGET_TAG),
        record_validity=tags[RECORD_VALIDITY_TAG],
        offline_backup_scope=tags.get(OFFLINE_BACKUP_SCOPE_TAG),
        production_approved=tags.get(PRODUCTION_APPROVED_TAG) == "true",
        aliases=tuple(aliases),
        source_kind=tags.get(SOURCE_KIND_TAG, "trained"),
        source_evidence=json.loads(tags.get(SOURCE_EVIDENCE_TAG, "{}")),
        performance_eval_id=tags.get("performance_eval_id"),
    )


def _get_model_version(store: ModelRegistryStore, model_id: str) -> Any:
    """get_model 内部：检索 + fail-closed 校验。"""
    parse_model_id(model_id)
    client = _client(store)
    version = _fetch_version_by_model_id(client, model_id)
    _validate_model_version_tags(version, expected_model_id=model_id)
    return version


def get_model(store: ModelRegistryStore, model_id: str) -> RegisteredModelRecord:
    """按 model_id 检索审计快照；invalid 亦返回。"""
    version = _get_model_version(store, model_id)
    return _build_record(version)


def validate_model_for_evaluation(
    store: ModelRegistryStore,
    model_id: str,
    model_version_number: int,
) -> RegisteredModelRecord:
    """正式 eval 创建门：模型存在、有效、数值版本精确匹配且训练记录仍合格。"""
    if not isinstance(model_version_number, int) or isinstance(model_version_number, bool):
        raise IllegalRegistryRecord("model_version_number 必须是正整数")
    record = get_model(store, model_id)
    if record.record_validity == RecordValidity.INVALID.value:
        raise InvalidModelRecord(f"model {model_id} 已 invalid")
    if record.version != model_version_number:
        raise PromotionGateRejected(
            f"model {model_id} 的数值版本是 {record.version}，不是 {model_version_number}"
        )
    _run_model_train_gate(store, record)
    return record


def _resolve_alias(client: MlflowClient, alias: str) -> Any:
    """解析 alias 到 ModelVersion；未设置 -> RegistryModelNotFound。"""
    try:
        return client.get_model_version_by_alias(REGISTERED_MODEL_NAME, alias)
    except MlflowException as exc:
        raise RegistryModelNotFound(f"alias {alias!r} 未设置") from exc


def _validate_alias(alias: Any) -> str:
    """alias 值域门；非法值一律不触碰 MLflow。"""
    if not isinstance(alias, str) or alias not in set(ALIASES):
        raise IllegalRegistryRecord(f"非法 alias: {alias!r}")
    return alias


def get_model_by_alias(store: ModelRegistryStore, alias: str) -> RegisteredModelRecord:
    """按 alias 路由读取；拒绝 invalid 目标，禁止隐式最新。"""
    alias = _validate_alias(alias)
    client = _client(store)
    version = _resolve_alias(client, alias)
    _validate_model_version_tags(version)
    record = _build_record(version)
    if record.record_validity == RecordValidity.INVALID.value:
        raise InvalidModelRecord(f"alias {alias!r} 指向 invalid 模型")
    _reject_development_only_source(record)
    if record.eval_id is None:
        raise PromotionGateRejected(f"alias {alias!r} 指向未 finalize 模型")
    if record.deploy_target is None or record.source_scope == "cross_validation":
        raise PromotionGateRejected(
            f"alias {alias!r} 指向没有唯一 deploy_target 的模型"
        )
    if alias == "candidate" and record.offline_backup_scope not in {
        "adapter",
        "production_bundle",
    }:
        raise PromotionGateRejected("candidate alias 目标缺少有效备份范围")
    if alias == "production" and (
        record.offline_backup_scope != "production_bundle"
        or not record.production_approved
    ):
        raise PromotionGateRejected("production alias 目标缺少范围或批准")
    _run_model_train_gate(store, record)
    eval_record = _run_eval_gate(store, record.eval_id, require_passed=True)
    if (
        eval_record.model_id != record.model_id
        or eval_record.model_version_number != record.version
    ):
        raise PromotionGateRejected("alias 目标的 eval 与模型身份或数值版本不一致")
    _validate_new_service_admission(store, record, eval_record)
    return record


def _artifact_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_tree(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_dir() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('execution evidence directory is missing or linked')
    result = {}
    for file in sorted(path.rglob('*')):
        if file.is_symlink() or not (file.is_dir() or file.is_file()):
            raise ValueError('execution evidence must contain regular files only')
        if file.is_file():
            result[file.relative_to(path).as_posix()] = {
                'size': file.stat().st_size, 'sha256': _artifact_digest(file)}
    if not result:
        raise ValueError('execution evidence directory is empty')
    return result


def _run_artifact_root(store: Any, run_id: str) -> Path:
    # This project uses a local MLflow artifact store. Do not let an altered URI
    # turn a gate into a network download or read outside that explicit store.
    from urllib.parse import urlparse, unquote
    uri = _client(store).get_run(run_id).info.artifact_uri
    parsed = urlparse(uri)
    if parsed.scheme not in ('', 'file') or parsed.netloc:
        raise ValueError('execution evidence must use the local artifact store')
    path = Path(unquote(parsed.path))
    if not path.is_absolute() or ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('execution evidence artifact root is not an ordinary absolute path')
    path.relative_to(Path(store.artifact_location).resolve())
    if not path.is_dir():
        raise ValueError('execution evidence artifact root is missing')
    return path


def _training_execution_snapshot(store: Any, record: Any, *, recorded_outputs: Any = None) -> dict[str, Any]:
    """Bind actual frozen input and all three adapter outputs, without changing Run state."""
    root = _run_artifact_root(store, record.run_id)
    inputs = root / 'input'
    tree = _artifact_tree(inputs)
    manifest = json.loads((inputs / 'input-manifest.json').read_bytes())
    if not isinstance(manifest, dict) or set(tree) != set(manifest) | {'input-manifest.json'}:
        raise ValueError('execution evidence frozen input file set differs')
    if any(tree[name] != expected for name, expected in manifest.items()):
        raise ValueError('execution evidence frozen input digest differs')
    training = yaml.safe_load((inputs / 'training.yaml').read_text())
    if training.get('version') != record.train_id or any(
        training.get(key) != getattr(record, key)
        for key in ('data_version', 'prompt_version', 'git_commit', 'base_model')
    ):
        raise ValueError('execution evidence training binding differs')
    from versioning.prompts import parse_prompt_definition
    prompt = parse_prompt_definition(yaml.safe_load((inputs / 'prompt.yaml').read_text()))
    if prompt.version != record.prompt_version or (inputs / 'data-version.txt').read_text().strip() != record.data_version:
        raise ValueError('execution evidence data/Prompt binding differs')
    from finetune.train_prepare_run import (_training_configs, _validate_full_config,
                                           _reject_unfrozen_training_inputs)
    configs = _training_configs(training)
    scope = training.get('scope', 'cross_validation')
    if scope != record.scope:
        raise ValueError('execution evidence training scope differs')
    if scope == 'full':
        if record.folds:
            raise ValueError('full execution evidence must have no fold children')
        _validate_full_config(configs['full'])
    elif set(record.folds) != {0, 1, 2}:
        raise ValueError('execution evidence requires three actual folds')
    outputs, metrics = {}, []
    for name, config in configs.items():
        _reject_unfrozen_training_inputs(config)
        actual_metrics = record.metrics if scope == 'full' else record.folds[int(name[-1])].metrics
        if record.config.get(name) != json.dumps(config, ensure_ascii=False, sort_keys=True, allow_nan=False):
            raise ValueError('execution evidence fold configuration differs')
        output = root / name / 'adapter'
        files = _artifact_tree(output) if recorded_outputs is None else recorded_outputs[name]
        if not isinstance(files, dict) or any(
            not isinstance(key, str) or Path(key).is_absolute() or '..' in Path(key).parts
            or not isinstance(spec, dict) or set(spec) != {'size', 'sha256'}
            or type(spec['size']) is not int or spec['size'] < 0
            or not isinstance(spec['sha256'], str) or len(spec['sha256']) != 64
            or any(c not in '0123456789abcdef' for c in spec['sha256'])
            for key, spec in files.items()
        ):
            raise ValueError('execution evidence artifact inventory is malformed')
        weights = [key for key in ('adapter_model.safetensors', 'adapter_model.bin')
                   if files.get(key, {}).get('size', 0) > 0]
        if not weights or 'adapter_config.json' not in files or 'train_results.json' not in files:
            raise ValueError('execution evidence requires adapter weights, configuration and actual results')
        if recorded_outputs is None:
            if not isinstance(json.loads((output / 'adapter_config.json').read_bytes()), dict):
                raise ValueError('execution evidence adapter configuration is malformed')
            result = json.loads((output / 'train_results.json').read_bytes())
        else:
            result = actual_metrics
        if result != actual_metrics:
            raise ValueError('execution evidence actual fold metrics differ')
        metrics.append(result)
        outputs[name] = files
    common = set.intersection(*(set(item) for item in metrics))
    summary = metrics[0] if scope == 'full' else {f'{key}_mean': sum(item[key] for item in metrics) / 3 for key in common}
    if not summary or summary != record.metrics:
        raise ValueError('execution evidence actual training summary differs')
    return {'schema': 'tensile-training-execution/v1', 'run_id': record.run_id,
            'train_version': record.train_id, 'input': tree, 'outputs': outputs,
            'fold_metrics': dict(zip(configs, metrics))}


def _validate_train_execution_artifacts(store: Any, record: Any, *, require_all_outputs: bool = False) -> None:
    root = _run_artifact_root(store, record.run_id)
    proof = root / 'training-evidence.json'
    if not proof.is_file() or proof.is_symlink():
        raise ValueError('training execution evidence is missing')
    expected = _client(store).get_run(record.run_id).data.params.get('sha256_training_evidence')
    if not expected or _artifact_digest(proof) != expected:
        raise ValueError('training execution evidence digest differs')
    evidence = json.loads(proof.read_bytes())
    if evidence != _training_execution_snapshot(store, record,
        recorded_outputs=None if require_all_outputs else evidence['outputs']):
        raise ValueError('training execution evidence artifacts drifted')


def _validate_eval_execution_artifacts(store: Any, record: Any) -> dict[str, Any]:
    from finetune.eval_run import validate_evaluation_execution_artifacts
    return validate_evaluation_execution_artifacts(store=store, record=record)


def _validate_model_artifact_evidence(store: Any, train: Any, artifacts: Any) -> None:
    root = _run_artifact_root(store, train.run_id)
    evidence = json.loads((root / 'training-evidence.json').read_bytes())
    if any('adapter' in entries for entries in artifacts.values()):
        training = yaml.safe_load((root / 'input/training.yaml').read_text())
        if _artifact_tree(Path(train.base_model)) != training.get('base_model_files'):
            raise ValueError('execution evidence training base model drifted')
    covered = {f'{fold}/adapter/{name}': spec
               for fold, files in evidence['outputs'].items() for name, spec in files.items()}
    for entries in artifacts.values():
        for declared in entries.values():
            relative = declared.removeprefix('artifacts/')
            files = _artifact_tree(root / relative)
            prefix = relative + '/'
            expected = {name[len(prefix):]: spec for name, spec in covered.items()
                        if name.startswith(prefix)}
            if files != expected:
                raise ValueError('model artifact is not covered by training execution evidence')


def _complete_base_inventory(path: Path) -> dict[str, dict[str, Any]]:
    """Freeze complete local inference bytes; a directory name is not provenance."""
    files = _artifact_tree(path)
    required = {"config.json", "tokenizer_config.json"}
    if not required <= files.keys():
        raise ValueError("base model requires configuration and tokenizer configuration")
    if not any(name in files for name in ("tokenizer.json", "tokenizer.model", "vocab.json")):
        raise ValueError("base model tokenizer bytes are missing")
    if not any(name in files for name in ("preprocessor_config.json", "processor_config.json")):
        raise ValueError("base model processor configuration is missing")
    for name in required | ({"preprocessor_config.json", "processor_config.json"} & files.keys()):
        if not isinstance(json.loads((path / name).read_bytes()), dict):
            raise ValueError("base model configuration must be a mapping")
    weights = {name for name in ("model.safetensors", "pytorch_model.bin") if files.get(name, {}).get("size", 0) > 0}
    for index in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
        if index not in files:
            continue
        mapping = json.loads((path / index).read_bytes()).get("weight_map")
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("base model weight index is malformed")
        shards = set(mapping.values())
        if any(not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts
               or files.get(name, {}).get("size", 0) <= 0 for name in shards):
            raise ValueError("base model weight shard is missing")
        weights.update(shards)
    if not weights:
        raise ValueError("base model complete weight bytes are missing")
    return files


def _base_provenance(path: Path, upstream_source: str, upstream_revision: str) -> dict[str, Any]:
    """Check available local metadata; never claim network verification from a caller string."""
    config = json.loads((path / "config.json").read_bytes())
    source = config.get("_name_or_path")
    revision = config.get("_commit_hash")
    if source is not None and source not in {upstream_source, str(path)}:
        raise ValueError("base configuration upstream source differs")
    if revision is not None and revision != upstream_revision:
        raise ValueError("base configuration upstream revision differs")
    metadata_verified = source == upstream_source and revision == upstream_revision
    if path.parent.name == "snapshots" and path.parent.parent.name.startswith("models--"):
        cache_source = path.parent.parent.name.removeprefix("models--").replace("--", "/")
        if cache_source != upstream_source or path.name != upstream_revision:
            raise ValueError("base Hugging Face snapshot provenance differs")
        metadata_verified = True
    proof = path / "source-provenance.json"
    if proof.exists():
        provenance = json.loads(proof.read_bytes())
        if (not isinstance(provenance, dict) or provenance.get("schema") != "tensile-base-provenance/v1"
                or provenance.get("upstream_source") != upstream_source
                or provenance.get("upstream_revision") != upstream_revision
                or not isinstance(provenance.get("verified_by"), str) or not provenance["verified_by"].strip()):
            raise ValueError("base local provenance file is malformed or inconsistent")
        return {"method": "local_provenance", "provenance": provenance}
    if not metadata_verified:
        raise ValueError("base source is unknown: require consistent local metadata or source-provenance.json")
    return {"method": "local_metadata", "upstream_source": upstream_source, "upstream_revision": upstream_revision}


def _source_identity(model: Any) -> dict[str, Any]:
    return {key: getattr(model, key) for key in ("model_id", "train_id", "data_version",
            "prompt_version", "git_commit", "base_model", "source_scope", "source_kind", "artifacts")}


def _reject_development_only_source(model: Any) -> None:
    if model.source_kind == "base" or model.source_scope == "diagnostic_fold":
        raise PromotionGateRejected("base and diagnostic models are restricted to development evaluation/performance")


def _diagnostic_parent_evidence(store: Any, parent: Any, fold: int) -> tuple[dict, dict, dict]:
    """Read only the chosen FINISHED child and shared input; never promote its parent."""
    if parent.record_validity != "valid" or parent.scope != "cross_validation":
        raise ValueError("diagnostic source training is invalid or not cross-validation")
    child = parent.folds.get(fold)
    if child is None or child.status != "FINISHED":
        raise ValueError("diagnostic source requires a FINISHED fold")
    root = _run_artifact_root(store, parent.run_id)
    inputs = _artifact_tree(root / "input")
    manifest = json.loads((root / "input/input-manifest.json").read_bytes())
    if set(inputs) != set(manifest) | {"input-manifest.json"} or any(inputs[n] != v for n, v in manifest.items()):
        raise ValueError("diagnostic shared input inventory differs")
    training = yaml.safe_load((root / "input/training.yaml").read_text())
    if training.get("version") != parent.train_id or any(training.get(key) != getattr(parent, key)
            for key in ("data_version", "prompt_version", "git_commit", "base_model")):
        raise ValueError("diagnostic shared training binding differs")
    from finetune.train_prepare_run import _training_configs, _reject_unfrozen_training_inputs
    config = _training_configs(training)[f"fold{fold}"]
    _reject_unfrozen_training_inputs(config)
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, allow_nan=False)
    actual_child = _client(store).get_run(child.run_id)
    if (parent.config.get(f"fold{fold}") != encoded
            or actual_child.data.params.get("training_config_json") != encoded
            or actual_child.data.tags.get("output_artifact") != f"runs:/{parent.run_id}/fold{fold}/adapter"):
        raise ValueError("diagnostic fold configuration binding differs")
    proof = root / f"fold{fold}/execution-evidence.json"
    expected = actual_child.data.params.get("sha256_fold_evidence")
    if proof.is_symlink() or not proof.is_file() or not expected or _artifact_digest(proof) != expected:
        raise ValueError("diagnostic fold receipt is missing or drifted")
    receipt = json.loads(proof.read_bytes())
    if (receipt.get("schema") != "tensile-training-fold-execution/v1"
            or receipt.get("train_version") != parent.train_id or receipt.get("run_id") != parent.run_id
            or receipt.get("child_run_id") != child.run_id or receipt.get("fold") != fold
            or receipt.get("input") != inputs or receipt.get("metrics") != dict(child.metrics)):
        raise ValueError("diagnostic fold receipt binding differs")
    validate_training_reference(store.data_root, parent.data_version)
    base = _complete_base_inventory(Path(parent.base_model))
    if base != training.get("base_model_files"):
        raise ValueError("diagnostic base model drifted")
    return receipt, training, base


def _validate_frozen_model_source(store: Any, model: Any) -> Any:
    root = _run_artifact_root(store, model.run_id)
    proof = root / "model-source.json"
    run = _client(store).get_run(model.run_id)
    if (run.info.status != "FINISHED" or run.data.tags.get("record_validity") != "valid"
            or run.data.tags.get("model_source_id") != model.model_id):
        raise ValueError("model snapshot source Run is invalid or unfinished")
    if proof.is_symlink() or not proof.is_file() or _artifact_digest(proof) != run.data.params.get("sha256_model_source"):
        raise ValueError("model source receipt is missing or drifted")
    evidence = json.loads(proof.read_bytes())
    if evidence != model.source_evidence or evidence.get("identity") != _source_identity(model):
        raise ValueError("model source identity differs from frozen receipt")
    expected_files = {prefix + "/" + name: spec for prefix, files in evidence["snapshot"].items()
                      for name, spec in files.items()}
    actual = _artifact_tree(root)
    actual.pop("model-source.json", None)
    if actual != expected_files:
        raise ValueError("model source snapshot bytes drifted")
    if model.source_kind == "base":
        if _base_provenance(Path(evidence["source_path"]), evidence["upstream_source"], evidence["upstream_revision"]) != evidence["provenance"]:
            raise ValueError("base model provenance drifted")
        if _complete_base_inventory(Path(evidence["source_path"])) != evidence["base_files"]:
            raise ValueError("base model source bytes drifted")
        if evidence["snapshot"] != {"base/model": evidence["base_files"]}:
            raise ValueError("base snapshot differs from source")
        return None
    parent = get_train_run(_train_store(store), model.train_id)
    receipt, training, base = _diagnostic_parent_evidence(store, parent, evidence["fold"])
    if (parent.run_id != evidence["parent_run_id"] or receipt != evidence["fold_receipt"]
            or base != evidence["base_files"] or training != evidence["training"]):
        raise ValueError("diagnostic source binding drifted")
    for key in ("data_version", "prompt_version", "git_commit", "base_model"):
        if getattr(parent, key) != getattr(model, key):
            raise ValueError("diagnostic model training references differ")
    prefix = f"fold{evidence['fold']}/adapter"
    if evidence["snapshot"] != {prefix: receipt["output"]}:
        raise ValueError("diagnostic snapshot differs from fold receipt")
    state = json.loads((root / prefix / "trainer_state.json").read_bytes())
    if type(state.get("global_step")) is not int or state["global_step"] <= 0 or state["global_step"] != evidence["checkpoint_step"]:
        raise ValueError("diagnostic checkpoint step differs")
    return parent


def _register_frozen_source(store: Any, model_id: str, *, tags: dict, evidence: dict,
                            source: Path, prefix: str) -> RegisteredModelRecord:
    """Called under Registry lock; freeze actual bytes before exposing a ModelVersion."""
    client = _client(store)
    try:
        _fetch_version_by_model_id(client, model_id)
    except RegistryModelNotFound:
        pass
    else:
        raise ModelVersionConflict(f"model {model_id} 已存在")
    run = client.create_run(store.train_experiment_id, tags={"model_source_id": model_id,
                            "record_validity": "valid"}, run_name=f"{model_id}-source")
    try:
        client.log_artifacts(run.info.run_id, str(source), artifact_path=prefix)
        snapshot_root = _run_artifact_root(store, run.info.run_id)
        if _artifact_tree(snapshot_root / prefix) != evidence["snapshot"][prefix]:
            raise ValueError("model snapshot differs from source bytes")
        proof = snapshot_root / "model-source.json"
        proof.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        client.log_param(run.info.run_id, "sha256_model_source", _artifact_digest(proof))
        client.set_terminated(run.info.run_id, status="FINISHED")
        tags[SOURCE_EVIDENCE_TAG] = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        version = client.create_model_version(name=REGISTERED_MODEL_NAME, source=run.info.artifact_uri,
                                              run_id=run.info.run_id, tags=tags)
        return _build_record(version)
    except BaseException:
        client.set_tag(run.info.run_id, "record_validity", "invalid")
        client.set_terminated(run.info.run_id, status="FAILED")
        raise


def _assert_source_model_id_unused(store: Any, model_id: str) -> None:
    try:
        _fetch_version_by_model_id(_client(store), model_id)
    except RegistryModelNotFound:
        return
    raise ModelVersionConflict(f"model {model_id} 已存在")


def register_base_model(store: ModelRegistryStore, model_id: str, *, model_path: Path,
                        upstream_source: str, upstream_revision: str, git_commit: str) -> RegisteredModelRecord:
    """Register a fixed base source without inventing a training Run, data or Prompt."""
    parse_model_id(model_id)
    with _registry_write_lock(store):
        _assert_source_model_id_unused(store, model_id)
    for value, name in ((upstream_source, "upstream_source"), (upstream_revision, "upstream_revision"), (git_commit, "git_commit")):
        _validate_non_empty_string(value, name)
    if upstream_revision.lower() in {"main", "master", "latest", "head"}:
        raise IllegalRegistryRecord("upstream_revision must identify a fixed revision")
    path = Path(model_path).absolute()
    files = _complete_base_inventory(path)
    provenance = _base_provenance(path, upstream_source, upstream_revision)
    artifacts = {"base": {"model": "artifacts/base/model"}}
    identity = {"model_id": model_id, "train_id": None, "data_version": None, "prompt_version": None,
                "git_commit": git_commit, "base_model": str(path), "source_scope": "base",
                "source_kind": "base", "artifacts": artifacts}
    evidence = {"schema": "tensile-model-source/v1", "identity": identity, "source_path": str(path),
                "upstream_source": upstream_source, "upstream_revision": upstream_revision,
                "provenance": provenance, "base_files": files, "snapshot": {"base/model": files}}
    tags = {MODEL_ID_TAG: model_id, SOURCE_KIND_TAG: "base", SOURCE_SCOPE_TAG: "base",
            GIT_COMMIT_TAG: git_commit, BASE_MODEL_TAG: str(path), RECORD_VALIDITY_TAG: "valid",
            ARTIFACTS_TAG: json.dumps(artifacts, sort_keys=True)}
    with _registry_write_lock(store):
        return _register_frozen_source(store, model_id, tags=tags, evidence=evidence, source=path, prefix="base/model")


def register_completed_fold_model(store: ModelRegistryStore, model_id: str, *, train_id: str,
                                  fold: int) -> RegisteredModelRecord:
    """Snapshot an actually FINISHED fold; leave its parent training state untouched."""
    parse_model_id(model_id)
    parse_train_id(train_id)
    if type(fold) is not int or fold not in (0, 1, 2):
        raise IllegalRegistryRecord("fold must be 0, 1 or 2")
    with _registry_write_lock(store):
        _assert_source_model_id_unused(store, model_id)
        parent = get_train_run(_train_store(store), train_id)
        receipt, training, base = _diagnostic_parent_evidence(store, parent, fold)
        source = _run_artifact_root(store, parent.run_id) / f"fold{fold}/adapter"
        if _artifact_tree(source) != receipt["output"]:
            raise ValueError("completed fold output differs from receipt")
        if "trainer_state.json" not in receipt["output"]:
            raise ValueError("completed fold requires receipt-covered checkpoint step evidence")
        state = json.loads((source / "trainer_state.json").read_bytes())
        if type(state.get("global_step")) is not int or state["global_step"] <= 0:
            raise ValueError("completed fold requires actual checkpoint step evidence")
        prefix = f"fold{fold}/adapter"
        artifacts = {f"fold{fold}": {"adapter": f"artifacts/{prefix}"}}
        identity = {"model_id": model_id, "train_id": train_id, "data_version": parent.data_version,
                    "prompt_version": parent.prompt_version, "git_commit": parent.git_commit,
                    "base_model": parent.base_model, "source_kind": "trained", "source_scope": "diagnostic_fold",
                    "artifacts": artifacts}
        evidence = {"schema": "tensile-model-source/v1", "identity": identity,
                    "parent_run_id": parent.run_id, "fold": fold, "checkpoint_step": state["global_step"],
                    "fold_receipt": receipt, "training": training, "base_files": base,
                    "snapshot": {prefix: receipt["output"]}}
        tags = {key: value for key, value in identity.items() if key != "artifacts"}
        tags[ARTIFACTS_TAG] = json.dumps(artifacts, sort_keys=True)
        tags[RECORD_VALIDITY_TAG] = "valid"
        return _register_frozen_source(store, model_id, tags=tags, evidence=evidence, source=source, prefix=prefix)


def _run_model_train_gate(store: ModelRegistryStore, model: Any) -> Any:
    if model.source_kind == "base" or model.source_scope == "diagnostic_fold":
        try:
            return _validate_frozen_model_source(store, model)
        except (ValueError, OSError, KeyError, TypeError, MlflowException) as exc:
            raise PromotionGateRejected(f"model source evidence rejected: {exc}") from exc
    train = _run_train_gate(store, model.train_id)
    if any(getattr(train, key) != getattr(model, key)
           for key in ('run_id', 'data_version', 'prompt_version', 'git_commit', 'base_model')):
        raise PromotionGateRejected('model binding differs from actual source training')
    if (train.scope == "full") != (model.source_scope == "full"):
        raise PromotionGateRejected("model source scope differs from actual training")
    try:
        _validate_model_artifact_evidence(store, train, model.artifacts)
    except (ValueError, OSError, KeyError, TypeError, MlflowException) as exc:
        raise PromotionGateRejected(f'model execution evidence rejected: {exc}') from exc
    return train


def _run_train_gate(store: ModelRegistryStore, train_id: str) -> Any:
    """train 晋级门；成功返回记录，失败包装为 PromotionGateRejected。"""
    try:
        record = validate_train_for_promotion(_train_store(store), train_id)
        validate_training_reference(store.data_root, record.data_version)
        _validate_train_execution_artifacts(store, record)
        return record
    except (
        TrainRecordNotFound,
        InvalidTrainRecord,
        IncompleteTrainRecord,
        IllegalTrainRecord,
        ValueError, OSError, KeyError, TypeError, AttributeError, MlflowException,
    ) as exc:
        raise PromotionGateRejected(f"train 晋级门拒绝: {exc}") from exc


def _run_eval_gate(store: ModelRegistryStore, eval_id: str, *, require_passed: bool, purpose: str = "quality") -> Any:
    """eval 结论门；成功返回记录，失败包装为 PromotionGateRejected。"""
    try:
        record = validate_eval_for_conclusion(_eval_store(store), eval_id)
        execution = _validate_eval_execution_artifacts(store, record)
        if execution is None:
            if (getattr(record, "purpose", "legacy") != "legacy" or
                    getattr(record, "protocol", "strict-v4.1") != "strict-v4.1"):
                raise IllegalEvalRecord("new evaluation purpose requires complete execution evidence")
            # Historical validators exposed only a successful read, not a
            # new-protocol evidence mapping. This cannot pass new-write gates.
            execution = {}
    except (
        EvalRecordNotFound,
        InvalidEvalRecord,
        IncompleteEvalRecord,
        IllegalEvalRecord,
        ValueError, OSError, KeyError, TypeError, AttributeError, MlflowException,
    ) as exc:
        raise PromotionGateRejected(f"eval 结论门拒绝: {exc}") from exc

    if require_passed and record.outcome != "passed":
        raise PromotionGateRejected(
            f"eval {eval_id} outcome={record.outcome!r}，未通过"
        )
    actual_purpose = getattr(record, "purpose", "legacy")
    if purpose == "performance":
        if actual_purpose != "performance" or getattr(record, "protocol", None) != "performance-v1":
            raise PromotionGateRejected("performance requires its own purpose/protocol evidence")
    else:
        protocol = getattr(record, "protocol", "strict-v4.1")
        # A/B semantic records predate purpose tags; inspect the validated
        # execution too so deleting tags cannot turn development into quality.
        actual_protocol = execution.get("scoring_protocol", protocol)
        if actual_purpose == "performance" or protocol == "performance-v1":
            raise PromotionGateRejected("performance evidence cannot substitute for quality")
        if actual_protocol == "semantic-v4.1" or protocol == "semantic-v4.1":
            raise PromotionGateRejected("development semantic evidence cannot substitute for independent quality")
        if actual_protocol == "semantic-holdout-v4.1":
            if actual_purpose != "quality" or protocol != actual_protocol or record.scope != "full":
                raise PromotionGateRejected("semantic quality purpose/protocol binding differs")
            if require_passed:
                integrity = execution.get("review_integrity", {})
                if (integrity.get("synthetic") is not False or
                    integrity.get("technical_isolation_verified") is not True or
                    integrity.get("real_model_deployment_verified") is not True):
                    raise PromotionGateRejected("semantic quality requires real verified independent review evidence")
        elif actual_protocol != "strict-v4.1":
            raise PromotionGateRejected("unsupported quality scoring protocol")
    return record


def _evaluation_input(store: ModelRegistryStore, evaluation: Any) -> dict:
    return json.loads((_run_artifact_root(store, evaluation.run_id) / "input/evaluation.yaml").read_bytes())


def _validate_new_service_admission(store: ModelRegistryStore, model: Any, quality: Any) -> None:
    """Old frozen strict approvals retain their meaning; new semantic service gates are joint."""
    protocol = getattr(quality, "protocol", "strict-v4.1")
    if protocol == "strict-v4.1":
        return
    if protocol != "semantic-holdout-v4.1":
        raise PromotionGateRejected("unsupported service quality protocol")
    if getattr(quality, "purpose", None) != "quality" or quality.scope != "full" or model.source_scope != "full":
        raise PromotionGateRejected("semantic service admission requires full independent quality evidence")
    if not getattr(model, "performance_eval_id", None):
        raise PromotionGateRejected("semantic service admission requires bound performance evidence")
    performance = _run_eval_gate(store, model.performance_eval_id, require_passed=True, purpose="performance")
    _validate_performance_pair(store, model, performance, quality)


def _validate_performance_pair(store: ModelRegistryStore, model: Any, performance: Any, quality: Any = None) -> None:
    if performance.model_id != model.model_id or performance.model_version_number != model.version:
        raise PromotionGateRejected("performance model identity or numeric version differs")
    from finetune.eval_run import validate_evaluation_execution_artifacts
    evidence = validate_evaluation_execution_artifacts(store=store, record=performance)
    if evidence.get("synthetic") is not False or evidence.get("e2e_verified") is not True or evidence.get("outcome") != "passed":
        raise PromotionGateRejected("performance requires real verified client display E2E evidence")
    if quality is None:
        return
    if quality.model_id != model.model_id or quality.model_version_number != model.version:
        raise PromotionGateRejected("quality model identity or numeric version differs")
    quality_input, performance_input = _evaluation_input(store, quality), _evaluation_input(store, performance)
    quality_evidence = validate_evaluation_execution_artifacts(store=store, record=quality)
    attestation = quality_evidence.get("runtime_attestation")
    performance_config = performance_input["config"]
    if (not isinstance(attestation, dict) or
        attestation != {key: performance_config[key] for key in ("runtime_variant", "device", "quantization_bit")}):
        raise PromotionGateRejected("quality/performance actual runtime attestation is missing or differs")
    for field in ("model", "prompt"):
        if quality_input.get(field) != performance_input.get(field) or not quality_input.get(field):
            raise PromotionGateRejected(f"quality/performance {field} binding differs")
    for field in ("generation", "quantization_bit", "artifact_kind"):
        if quality_input["config"].get(field) != performance_input["config"].get(field):
            raise PromotionGateRejected(f"quality/performance {field} binding differs")
    # Frames/preprocessing are code-frozen, not a caller's descriptive variant label.
    frame_sources = {"finetune/validation/video_loader.py", "pipeline/preprocessing/minicpm_preprocessor.py"}
    for source in frame_sources:
        expected = quality_input.get("implementation_sha256", {}).get(source)
        if not expected or performance_input.get("implementation_sha256", {}).get(source) != expected:
            raise PromotionGateRejected("quality/performance frame preprocessing binding differs")


def _require_new_quality_protocol(quality: Any) -> None:
    if getattr(quality, "purpose", None) != "quality" or getattr(quality, "protocol", None) != "semantic-holdout-v4.1":
        raise PromotionGateRejected("new admission requires semantic-holdout quality plus independent performance; historical strict is read-only")


def bind_model_performance(store: ModelRegistryStore, model_id: str, *, eval_id: str) -> RegisteredModelRecord:
    """Bind independent real performance proof without granting an alias or production approval."""
    parse_model_id(model_id)
    parse_eval_id(eval_id)
    with _registry_write_lock(store):
        client = _client(store)
        version = _fetch_version_by_model_id(client, model_id)
        _validate_model_version_tags(version, expected_model_id=model_id)
        model = _build_record(version)
        _reject_development_only_source(model)
        if model.record_validity != "valid":
            raise InvalidModelRecord("invalid model cannot bind performance")
        if model.performance_eval_id not in (None, eval_id):
            raise ModelVersionConflict("performance evidence cannot be rebound")
        _run_model_train_gate(store, model)
        performance = _run_eval_gate(store, eval_id, require_passed=True, purpose="performance")
        quality = _run_eval_gate(store, model.eval_id, require_passed=True) if model.eval_id else None
        if quality is not None and getattr(quality, "protocol", None) != "semantic-holdout-v4.1":
            raise PromotionGateRejected("legacy quality cannot acquire new semantic admission through performance binding")
        _validate_performance_pair(store, model, performance, quality)
        client.set_model_version_tag(REGISTERED_MODEL_NAME, str(model.version), "performance_eval_id", eval_id)
        return _build_record(client.get_model_version(REGISTERED_MODEL_NAME, str(model.version)))


def register_model(
    store: ModelRegistryStore,
    model_id: str,
    *,
    train_id: str,
    source_scope: str = "single_fold",
    artifacts: dict[str, dict[str, str]] | None = None,
    deploy_target: str | None = "artifacts/fold0/adapter",
) -> RegisteredModelRecord:
    """登记 staging 模型，先得到供正式 eval 精确引用的数值版本。"""
    parse_model_id(model_id)
    if source_scope in {"base", "diagnostic_fold"}:
        raise IllegalRegistryRecord("use the explicit base/completed-fold registration entry point")
    parse_train_id(train_id)
    if artifacts is None:
        artifacts = {
            "fold0": {
                "adapter": "artifacts/fold0/adapter",
            }
        }
    source_scope, artifacts, deploy_target = _validate_model_layout(
        source_scope, artifacts, deploy_target
    )

    with _registry_write_lock(store):
        client = _client(store)

        # 同名检查与创建必须在同一进程间锁内，MLflow tag 本身没有唯一约束。
        try:
            _fetch_version_by_model_id(client, model_id)
        except RegistryModelNotFound:
            pass
        else:
            raise ModelVersionConflict(f"model {model_id} 已存在")

        train_record = _run_train_gate(store, train_id)
        if (train_record.scope == "full") != (source_scope == "full"):
            raise PromotionGateRejected("model source scope differs from actual training")
        try:
            _validate_model_artifact_evidence(store, train_record, artifacts)
        except (ValueError, OSError, KeyError, TypeError, MlflowException) as exc:
            raise PromotionGateRejected(f"model execution evidence rejected: {exc}") from exc
        run = client.get_run(train_record.run_id)
        tags = {
            MODEL_ID_TAG: model_id,
            SOURCE_KIND_TAG: "trained",
            TRAIN_ID_TAG: train_record.train_id,
            DATA_VERSION_TAG: train_record.data_version,
            PROMPT_VERSION_TAG: train_record.prompt_version,
            GIT_COMMIT_TAG: train_record.git_commit,
            BASE_MODEL_TAG: train_record.base_model,
            SOURCE_SCOPE_TAG: source_scope,
            ARTIFACTS_TAG: json.dumps(artifacts, sort_keys=True, separators=(",", ":")),
            RECORD_VALIDITY_TAG: RecordValidity.VALID.value,
        }
        if deploy_target is not None:
            tags[DEPLOY_TARGET_TAG] = deploy_target
        version = client.create_model_version(
            name=REGISTERED_MODEL_NAME,
            source=run.info.artifact_uri,
            run_id=train_record.run_id,
            tags=tags,
        )
        return _build_record(version)


def finalize_model_evaluation(
    store: ModelRegistryStore,
    model_id: str,
    *,
    eval_id: str,
) -> RegisteredModelRecord:
    """把已通过且精确引用该数值 Model Version 的 eval 绑定到 staging 模型。"""
    parse_model_id(model_id)
    parse_eval_id(eval_id)

    with _registry_write_lock(store):
        client = _client(store)
        version = _fetch_version_by_model_id(client, model_id)
        _validate_model_version_tags(version, expected_model_id=model_id)
        record = _build_record(version)
        _reject_development_only_source(record)
        if record.record_validity == RecordValidity.INVALID.value:
            raise InvalidModelRecord(f"model {model_id} 已 invalid")
        if record.eval_id is not None and record.eval_id != eval_id:
            raise ModelVersionConflict(
                f"model {model_id} 已绑定 eval {record.eval_id}，不得改绑 {eval_id}"
            )

        _run_model_train_gate(store, record)
        eval_record = _run_eval_gate(store, eval_id, require_passed=True)
        if eval_record.model_id != model_id:
            raise PromotionGateRejected(
                f"eval model_id {eval_record.model_id!r} 与 model {model_id!r} 不一致"
            )
        if eval_record.model_version_number != record.version:
            raise PromotionGateRejected(
                "eval 引用的 MLflow 数值 Model Version "
                f"{eval_record.model_version_number} 与实际版本 {record.version} 不一致"
            )
        if getattr(eval_record, "protocol", "strict-v4.1") == "semantic-holdout-v4.1":
            if record.source_scope != "full" or eval_record.scope != "full" or eval_record.purpose != "quality":
                raise PromotionGateRejected("semantic quality requires a full model and independent full evaluation")
            if record.performance_eval_id:
                performance = _run_eval_gate(store, record.performance_eval_id, require_passed=True, purpose="performance")
                _validate_performance_pair(store, record, performance, eval_record)
        if record.eval_id == eval_id:
            return record
        _require_new_quality_protocol(eval_record)
        _validate_new_service_admission(store, record, eval_record)

        client.set_model_version_tag(
            REGISTERED_MODEL_NAME, str(record.version), EVAL_ID_TAG, eval_id
        )
        updated = client.get_model_version(REGISTERED_MODEL_NAME, str(record.version))
        return _build_record(updated)


def set_offline_backup_scope(
    store: ModelRegistryStore,
    model_id: str,
    scope: str,
) -> RegisteredModelRecord:
    """单向粘性升级 offline_backup_scope。"""
    parse_model_id(model_id)
    if not isinstance(scope, str) or scope not in set(BACKUP_SCOPES):
        raise IllegalRegistryRecord(f"非法 offline_backup_scope: {scope!r}")

    with _registry_write_lock(store):
        client = _client(store)
        version = _fetch_version_by_model_id(client, model_id)
        _validate_model_version_tags(version, expected_model_id=model_id)

        current = version.tags.get(OFFLINE_BACKUP_SCOPE_TAG)
        if current == scope:
            return _build_record(version)

        if current is None and scope in {"adapter", "production_bundle"}:
            pass
        elif current == "adapter" and scope == "production_bundle":
            pass
        else:
            raise IllegalTransition(
                f"非法 offline_backup_scope 转换: {current!r} -> {scope!r}"
            )

        client.set_model_version_tag(
            REGISTERED_MODEL_NAME, str(version.version), OFFLINE_BACKUP_SCOPE_TAG, scope
        )
        updated = client.get_model_version(REGISTERED_MODEL_NAME, str(version.version))
        return _build_record(updated)


def _approve_model_for_production_locked(
    store: ModelRegistryStore,
    model_id: str,
) -> RegisteredModelRecord:
    """用户批准标记；在线复验 train + eval passed。"""
    parse_model_id(model_id)

    client = _client(store)
    version = _fetch_version_by_model_id(client, model_id)
    _validate_model_version_tags(version, expected_model_id=model_id)
    record = _build_record(version)
    _reject_development_only_source(record)

    if record.record_validity == RecordValidity.INVALID.value:
        raise InvalidModelRecord(f"model {model_id} 已 invalid")

    train_id = record.train_id
    eval_id = record.eval_id
    if eval_id is None:
        raise PromotionGateRejected(f"model {model_id} 尚未绑定通过的正式 eval")

    _run_model_train_gate(store, record)
    eval_record = _run_eval_gate(store, eval_id, require_passed=True)

    # 关联校验：eval.model_id == 被批准 model_id
    if eval_record.model_id != model_id:
        raise PromotionGateRejected(
            f"eval model_id {eval_record.model_id!r} 与批准 model_id {model_id!r} 不一致"
        )
    if eval_record.model_version_number != record.version:
        raise PromotionGateRejected(
            "eval 引用的 MLflow 数值 Model Version 与被批准模型不一致"
        )

    if record.production_approved:
        _validate_new_service_admission(store, record, eval_record)
        return record
    _require_new_quality_protocol(eval_record)
    _validate_new_service_admission(store, record, eval_record)

    client.set_model_version_tag(
        REGISTERED_MODEL_NAME, str(record.version), PRODUCTION_APPROVED_TAG, "true"
    )
    updated = client.get_model_version(REGISTERED_MODEL_NAME, str(record.version))
    return _build_record(updated)


def approve_model_for_production(
    store: ModelRegistryStore,
    model_id: str,
) -> RegisteredModelRecord:
    """串行批准，避免与 invalid、scope 或 alias 更新交错。"""
    with _registry_write_lock(store):
        return _approve_model_for_production_locked(store, model_id)


def _set_alias_locked(
    store: ModelRegistryStore,
    model_id: str,
    alias: str,
) -> RegisteredModelRecord:
    """设置 candidate/production alias；唯一可变路由入口。"""
    alias = _validate_alias(alias)
    parse_model_id(model_id)

    client = _client(store)
    version = _fetch_version_by_model_id(client, model_id)
    _validate_model_version_tags(version, expected_model_id=model_id)
    record = _build_record(version)
    _reject_development_only_source(record)

    if record.record_validity == RecordValidity.INVALID.value:
        raise InvalidModelRecord(f"model {model_id} 已 invalid")
    if record.deploy_target is None or record.source_scope == "cross_validation":
        raise PromotionGateRejected(
            f"{alias} alias 只接受具有唯一 deploy_target 的单折或 full 模型"
        )

    # scope 前置门
    scope = record.offline_backup_scope
    if alias == "candidate":
        if scope not in {"adapter", "production_bundle"}:
            raise PromotionGateRejected(
                f"candidate alias 要求 scope 已设置，当前 {scope!r}"
            )
    elif alias == "production":
        if scope != "production_bundle":
            raise PromotionGateRejected(
                f"production alias 要求 scope=production_bundle，当前 {scope!r}"
            )
        if not record.production_approved:
            raise PromotionGateRejected(
                "production alias 要求已批准"
            )

    if record.eval_id is None:
        raise PromotionGateRejected(
            f"{alias} alias 要求模型已绑定通过的正式 eval"
        )

    # train / eval 门在线复验
    _run_model_train_gate(store, record)
    eval_record = _run_eval_gate(store, record.eval_id, require_passed=True)
    if (
        eval_record.model_id != record.model_id
        or eval_record.model_version_number != record.version
    ):
        raise PromotionGateRejected("eval 与模型可读身份或数值版本绑定不一致")
    _validate_new_service_admission(store, record, eval_record)
    try:
        existing_alias = _resolve_alias(client, alias)
        same_alias = int(existing_alias.version) == record.version
    except RegistryModelNotFound:
        same_alias = False
    if not same_alias:
        _require_new_quality_protocol(eval_record)

    client.set_registered_model_alias(
        REGISTERED_MODEL_NAME, alias, str(record.version)
    )
    updated = client.get_model_version(REGISTERED_MODEL_NAME, str(record.version))
    return _build_record(updated)


def set_alias(
    store: ModelRegistryStore,
    model_id: str,
    alias: str,
) -> RegisteredModelRecord:
    """串行更新 alias，使全部在线门与最终路由写入成为同一临界区。"""
    with _registry_write_lock(store):
        return _set_alias_locked(store, model_id, alias)


def _delete_alias_locked(
    store: ModelRegistryStore, alias: str
) -> RegisteredModelRecord:
    """删除 alias；未设置 fail-closed。"""
    alias = _validate_alias(alias)

    client = _client(store)
    try:
        version = client.get_model_version_by_alias(REGISTERED_MODEL_NAME, alias)
    except MlflowException as exc:
        raise RegistryModelNotFound(f"alias {alias!r} 未设置") from exc

    _validate_model_version_tags(version)
    record = _build_record(version)

    client.delete_registered_model_alias(REGISTERED_MODEL_NAME, alias)
    return RegisteredModelRecord(
        **{**record.__dict__, "aliases": tuple(a for a in record.aliases if a != alias)}
    )


def delete_alias(store: ModelRegistryStore, alias: str) -> RegisteredModelRecord:
    """串行删除 alias，避免与设置、批准或 invalid 更新交错。"""
    with _registry_write_lock(store):
        return _delete_alias_locked(store, alias)


def _mark_model_invalid_locked(
    store: ModelRegistryStore,
    model_id: str,
) -> RegisteredModelRecord:
    """模型 record_validity 转至 invalid；不提供复活入口。"""
    parse_model_id(model_id)

    client = _client(store)
    version = _fetch_version_by_model_id(client, model_id)
    _validate_model_version_tags(version, expected_model_id=model_id)

    current = RecordValidity(version.tags.get(RECORD_VALIDITY_TAG, RecordValidity.VALID.value))
    transition_record_validity(current, RecordValidity.INVALID)

    client.set_model_version_tag(
        REGISTERED_MODEL_NAME, str(version.version), RECORD_VALIDITY_TAG, RecordValidity.INVALID.value
    )
    updated = client.get_model_version(REGISTERED_MODEL_NAME, str(version.version))
    return _build_record(updated)


def mark_model_invalid(
    store: ModelRegistryStore,
    model_id: str,
) -> RegisteredModelRecord:
    """串行置 invalid，确保 alias/批准门不会与有效性变更交错。"""
    with _registry_write_lock(store):
        return _mark_model_invalid_locked(store, model_id)


def _build_materialized_payload(record: RegisteredModelRecord) -> dict[str, Any]:
    """构造 materialized.yaml 的确定性 mapping。"""
    return {
        "registered_model": record.registered_model,
        "mlflow_model_version": record.version,
        "model_id": record.model_id,
        "train_id": record.train_id,
        "eval_id": record.eval_id,
        **({"performance_eval_id": record.performance_eval_id} if record.performance_eval_id else {}),
        "data_version": record.data_version,
        "prompt_version": record.prompt_version,
        "git_commit": record.git_commit,
        "record_validity": record.record_validity,
        "offline_backup_scope": record.offline_backup_scope,
        "manifest": f"records/models/{record.model_id}/manifest.yaml",
        **({"source_kind": record.source_kind, "source_evidence": record.source_evidence}
           if record.source_evidence else {}),
    }


def validate_materialized_artifacts(
    record: RegisteredModelRecord, materialized_root: Path
) -> None:
    """逐项验证 Registry 声明的 artifact 在物化根中真实存在且有内容。"""
    root = Path(materialized_root).resolve()
    if record.source_evidence:
        for prefix, files in record.source_evidence["snapshot"].items():
            if _artifact_tree(root / "artifacts" / prefix) != files:
                raise IllegalRegistryRecord("materialized model source bytes drifted")
    for entries in record.artifacts.values():
        for declared in entries.values():
            target = (root / declared).resolve()
            if root not in target.parents:
                raise IllegalRegistryRecord(f"artifact 路径越出物化根: {declared!r}")
            if not target.exists():
                raise IllegalRegistryRecord(f"声明 artifact 不存在: {declared}")
            if target.is_dir() and not any(path.is_file() for path in target.rglob("*")):
                raise IllegalRegistryRecord(f"声明 artifact 目录为空: {declared}")

    if record.deploy_target is not None:
        deploy = (root / record.deploy_target).resolve()
        if root not in deploy.parents or not deploy.exists():
            raise IllegalRegistryRecord(
                f"deploy_target 不存在或越出物化根: {record.deploy_target}"
            )
        if deploy.is_dir() and not any(path.is_file() for path in deploy.rglob("*")):
            raise IllegalRegistryRecord(f"deploy_target 目录为空: {record.deploy_target}")


def materialize_model(
    store: ModelRegistryStore,
    model_id: str,
    models_root: Path,
) -> Path:
    """把已注册模型 artifact 单向导出到 models/<model_id>/。"""
    parse_model_id(model_id)

    client = _client(store)
    version = _get_model_version(store, model_id)
    record = _build_record(version)

    if record.record_validity == RecordValidity.INVALID.value:
        raise InvalidModelRecord(f"model {model_id} 已 invalid，禁止物化")

    _run_model_train_gate(store, record)

    target = Path(models_root) / model_id
    metadata_path = target / MATERIALIZED_METADATA_FILE

    if metadata_path.is_file():
        try:
            existing = yaml.safe_load(metadata_path.read_text())
        except Exception as exc:
            raise IllegalRegistryRecord(f"无法解析既有 materialized.yaml: {exc}") from exc
        if not isinstance(existing, dict):
            raise IllegalRegistryRecord("既有 materialized.yaml 不是 mapping")
        if existing.get("model_id") != record.model_id:
            raise IllegalRegistryRecord("既有目标 model_id 与 Registry 分歧")
        if existing.get("mlflow_model_version") != record.version:
            raise IllegalRegistryRecord("既有目标 mlflow_model_version 与 Registry 分歧")

    payload_bytes = yaml.safe_dump(
        _build_materialized_payload(record), sort_keys=True, allow_unicode=True
    ).encode("utf-8")

    models_root = Path(models_root)
    models_root.mkdir(parents=True, exist_ok=True)
    artifact_src = Path(client.download_artifacts(run_id=record.run_id, path=""))
    staging = Path(tempfile.mkdtemp(prefix=f".{model_id}.", dir=models_root))
    try:
        artifact_dst = staging / MATERIALIZED_ARTIFACTS_DIR
        if artifact_src.exists():
            shutil.copytree(artifact_src, artifact_dst, dirs_exist_ok=True)
        else:
            artifact_dst.mkdir(parents=True, exist_ok=True)
        (staging / MATERIALIZED_METADATA_FILE).write_bytes(payload_bytes)
        validate_materialized_artifacts(record, staging)

        if target.exists():
            shutil.copytree(artifact_dst, target / MATERIALIZED_ARTIFACTS_DIR, dirs_exist_ok=True)
            metadata_path.write_bytes(payload_bytes)
        else:
            os.replace(staging, target)
            staging = Path()
    finally:
        if staging != Path():
            shutil.rmtree(staging, ignore_errors=True)
    return target
