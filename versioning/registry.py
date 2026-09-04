"""B8 — MLflow Model Registry：唯一 mVllm2、晋级门、alias 路由与物化导出。

对应设计 §2.9、§2.11、§5.4、§6、§7、§9、§10、§11.6、§13.1。
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import threading
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
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
SOURCE_SCOPES: tuple[str, ...] = ("single_fold", "cross_validation", "full")

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
    train_id: str
    eval_id: str | None
    data_version: str
    prompt_version: str
    git_commit: str
    base_model: str
    source_scope: str
    artifacts: dict[str, dict[str, str]]
    deploy_target: str | None
    record_validity: str
    offline_backup_scope: str | None
    production_approved: bool
    aliases: tuple[str, ...]


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
    return MlflowClient(tracking_uri=store.tracking_uri)


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
    }[source_scope]
    if set(normalized) != expected:
        raise IllegalRegistryRecord(
            f"artifacts scope {sorted(normalized)} 与 source_scope={source_scope!r} 不一致"
        )
    all_paths = {path for entries in normalized.values() for path in entries.values()}
    if source_scope == "cross_validation":
        if deploy_target is not None:
            raise IllegalRegistryRecord("cross_validation 的 deploy_target 必须为 null")
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

    train_id = tags.get(TRAIN_ID_TAG)
    try:
        parse_train_id(train_id)
    except Exception as exc:
        raise IllegalRegistryRecord(f"train_id tag 非法: {train_id!r}") from exc

    eval_id = tags.get(EVAL_ID_TAG)
    if eval_id is not None:
        try:
            parse_eval_id(eval_id)
        except Exception as exc:
            raise IllegalRegistryRecord(f"eval_id tag 非法: {eval_id!r}") from exc

    data_version = tags.get(DATA_VERSION_TAG)
    try:
        parse_data_id(data_version)
    except Exception as exc:
        raise IllegalRegistryRecord(f"data_version tag 非法: {data_version!r}") from exc

    prompt_version = tags.get(PROMPT_VERSION_TAG)
    try:
        parse_prompt_id(prompt_version)
    except Exception as exc:
        raise IllegalRegistryRecord(f"prompt_version tag 非法: {prompt_version!r}") from exc

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
        train_id=tags[TRAIN_ID_TAG],
        eval_id=tags.get(EVAL_ID_TAG),
        data_version=tags[DATA_VERSION_TAG],
        prompt_version=tags[PROMPT_VERSION_TAG],
        git_commit=tags[GIT_COMMIT_TAG],
        base_model=tags[BASE_MODEL_TAG],
        source_scope=tags[SOURCE_SCOPE_TAG],
        artifacts=json.loads(tags[ARTIFACTS_TAG]),
        deploy_target=tags.get(DEPLOY_TARGET_TAG),
        record_validity=tags[RECORD_VALIDITY_TAG],
        offline_backup_scope=tags.get(OFFLINE_BACKUP_SCOPE_TAG),
        production_approved=tags.get(PRODUCTION_APPROVED_TAG) == "true",
        aliases=tuple(aliases),
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
    _run_train_gate(store, record.train_id)
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
    _run_train_gate(store, record.train_id)
    eval_record = _run_eval_gate(store, record.eval_id, require_passed=True)
    if (
        eval_record.model_id != record.model_id
        or eval_record.model_version_number != record.version
    ):
        raise PromotionGateRejected("alias 目标的 eval 与模型身份或数值版本不一致")
    return record


def _run_train_gate(store: ModelRegistryStore, train_id: str) -> Any:
    """train 晋级门；成功返回记录，失败包装为 PromotionGateRejected。"""
    try:
        record = validate_train_for_promotion(_train_store(store), train_id)
        validate_training_reference(store.data_root, record.data_version)
        return record
    except (
        TrainRecordNotFound,
        InvalidTrainRecord,
        IncompleteTrainRecord,
        IllegalTrainRecord,
        ValueError,
    ) as exc:
        raise PromotionGateRejected(f"train 晋级门拒绝: {exc}") from exc


def _run_eval_gate(store: ModelRegistryStore, eval_id: str, *, require_passed: bool) -> Any:
    """eval 结论门；成功返回记录，失败包装为 PromotionGateRejected。"""
    try:
        record = validate_eval_for_conclusion(_eval_store(store), eval_id)
    except (
        EvalRecordNotFound,
        InvalidEvalRecord,
        IncompleteEvalRecord,
        IllegalEvalRecord,
        ValueError,
    ) as exc:
        raise PromotionGateRejected(f"eval 结论门拒绝: {exc}") from exc

    if require_passed and record.outcome != "passed":
        raise PromotionGateRejected(
            f"eval {eval_id} outcome={record.outcome!r}，未通过"
        )
    return record


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
        run = client.get_run(train_record.run_id)
        tags = {
            MODEL_ID_TAG: model_id,
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
        if record.record_validity == RecordValidity.INVALID.value:
            raise InvalidModelRecord(f"model {model_id} 已 invalid")
        if record.eval_id is not None and record.eval_id != eval_id:
            raise ModelVersionConflict(
                f"model {model_id} 已绑定 eval {record.eval_id}，不得改绑 {eval_id}"
            )

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
        if record.eval_id == eval_id:
            return record

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

    if record.record_validity == RecordValidity.INVALID.value:
        raise InvalidModelRecord(f"model {model_id} 已 invalid")

    train_id = record.train_id
    eval_id = record.eval_id
    if eval_id is None:
        raise PromotionGateRejected(f"model {model_id} 尚未绑定通过的正式 eval")

    _run_train_gate(store, train_id)
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
        return record

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
    _run_train_gate(store, record.train_id)
    eval_record = _run_eval_gate(store, record.eval_id, require_passed=True)
    if (
        eval_record.model_id != record.model_id
        or eval_record.model_version_number != record.version
    ):
        raise PromotionGateRejected("eval 与模型可读身份或数值版本绑定不一致")

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
        "data_version": record.data_version,
        "prompt_version": record.prompt_version,
        "git_commit": record.git_commit,
        "record_validity": record.record_validity,
        "offline_backup_scope": record.offline_backup_scope,
        "manifest": f"records/models/{record.model_id}/manifest.yaml",
    }


def validate_materialized_artifacts(
    record: RegisteredModelRecord, materialized_root: Path
) -> None:
    """逐项验证 Registry 声明的 artifact 在物化根中真实存在且有内容。"""
    root = Path(materialized_root).resolve()
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
