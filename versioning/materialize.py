"""Registry alias 到 ``workspace/models/current`` 的原子物化与启动校验。"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import uuid
import fcntl
from contextlib import contextmanager
from pathlib import Path

import yaml
from mlflow.tracking import MlflowClient

from versioning.manifest import ManifestReferenceError, validate_model_manifest
from versioning.registry import (
    MATERIALIZED_ARTIFACTS_DIR,
    MATERIALIZED_METADATA_FILE,
    ModelRegistryStore,
    RegisteredModelRecord,
    get_model_by_alias,
    validate_materialized_artifacts,
)


SERVICE_MODES = ("development", "production")
_CURRENT_LOCKS_GUARD = threading.Lock()
_CURRENT_LOCKS: dict[str, threading.RLock] = {}


@contextmanager
def _current_write_lock(models_root: Path):
    lock_path = Path(models_root) / ".current.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(lock_path.resolve())
    with _CURRENT_LOCKS_GUARD:
        local_lock = _CURRENT_LOCKS.setdefault(key, threading.RLock())
    with local_lock:
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validate_route(service_mode: str, alias: str) -> None:
    if service_mode not in SERVICE_MODES:
        raise ManifestReferenceError("service_mode 必须显式为 development 或 production")
    if alias not in {"candidate", "production"}:
        raise ManifestReferenceError("model_alias 必须显式为 candidate 或 production")
    if service_mode == "production" and alias != "production":
        raise ManifestReferenceError("production 模式只接受 production alias")


def _load_matching_manifest(records_root: Path, record: RegisteredModelRecord) -> tuple[Path, dict]:
    path = Path(records_root) / "records" / "models" / record.model_id / "manifest.yaml"
    if not path.is_file():
        raise ManifestReferenceError(f"缺少 model manifest: {path}")
    obj = validate_model_manifest(path.read_text(encoding="utf-8"))
    expected = {
        "version": record.model_id,
        "mlflow_model_version": record.version,
        "source_run_id": record.run_id,
        "source_training": record.train_id,
        "source_scope": record.source_scope,
        "deploy_target": record.deploy_target,
    }
    for key, value in expected.items():
        if obj.get(key) != value:
            raise ManifestReferenceError(f"model manifest {key} 与 Registry 不一致")
    if obj.get("artifacts") != record.artifacts:
        raise ManifestReferenceError("model manifest artifacts 与 Registry 不一致")
    return path, obj


def _metadata(record: RegisteredModelRecord, manifest: Path, records_root: Path) -> dict:
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
        "source_scope": record.source_scope,
        "artifacts": record.artifacts,
        "deploy_target": record.deploy_target,
        "manifest": str(manifest.relative_to(Path(records_root))),
    }


def _validate_materialized_target(
    target: Path,
    *,
    record: RegisteredModelRecord,
    manifest: Path,
    records_root: Path,
) -> None:
    metadata_path = target / MATERIALIZED_METADATA_FILE
    if not metadata_path.is_file():
        raise ManifestReferenceError("物化目标缺少 materialized.yaml")
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    if metadata != _metadata(record, manifest, records_root):
        raise ManifestReferenceError("物化目标元数据与 alias 精确目标不一致")
    try:
        validate_materialized_artifacts(record, target)
    except Exception as exc:
        raise ManifestReferenceError(f"物化目标 artifact 校验失败: {exc}") from exc


def _materialize_current_locked(
    store: ModelRegistryStore,
    *,
    alias: str,
    service_mode: str,
    models_root: Path,
    records_root: Path,
) -> Path:
    """完整下载并校验 alias 精确目标后，原子切换 ``models/current``。"""
    _validate_route(service_mode, alias)
    record = get_model_by_alias(store, alias)
    if record.deploy_target is None:
        raise ManifestReferenceError("alias 目标没有唯一 deploy_target")
    manifest, _ = _load_matching_manifest(records_root, record)

    models_root = Path(models_root)
    materialized_root = models_root / "materialized"
    materialized_root.mkdir(parents=True, exist_ok=True)
    target = materialized_root / record.model_id
    if target.exists():
        _validate_materialized_target(
            target,
            record=record,
            manifest=manifest,
            records_root=records_root,
        )
    else:
        temp = Path(tempfile.mkdtemp(prefix=f".{record.model_id}.", dir=materialized_root))
        try:
            client = MlflowClient(tracking_uri=store.tracking_uri)
            source = Path(client.download_artifacts(run_id=record.run_id, path=""))
            shutil.copytree(source, temp / MATERIALIZED_ARTIFACTS_DIR, dirs_exist_ok=True)
            deploy_path = temp / record.deploy_target
            if not deploy_path.exists():
                raise ManifestReferenceError(
                    f"下载产物缺少 deploy_target: {record.deploy_target}"
                )
            (temp / MATERIALIZED_METADATA_FILE).write_text(
                yaml.safe_dump(_metadata(record, manifest, records_root), sort_keys=True, allow_unicode=True),
                encoding="utf-8",
            )
            # 只有完整 metadata、全部声明 artifact 与 deploy_target 都通过时，
            # 才把临时目录发布为可复用的物化目标。
            _validate_materialized_target(
                temp,
                record=record,
                manifest=manifest,
                records_root=records_root,
            )
            os.replace(temp, target)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise

    _validate_materialized_target(
        target,
        record=record,
        manifest=manifest,
        records_root=records_root,
    )

    current = models_root / "current"
    if current.exists() and not current.is_symlink():
        raise ManifestReferenceError("models/current 存在且不是受控符号链接")
    link_tmp = models_root / f".current.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    if link_tmp.exists() or link_tmp.is_symlink():
        link_tmp.unlink()
    link_tmp.symlink_to(Path("materialized") / record.model_id)
    old_target = os.readlink(current) if current.is_symlink() else None
    os.replace(link_tmp, current)
    try:
        validate_service_current(
            store,
            alias=alias,
            service_mode=service_mode,
            models_root=models_root,
            records_root=records_root,
        )
    except Exception:
        if old_target is None:
            current.unlink(missing_ok=True)
        else:
            rollback = models_root / f".current.rollback.{uuid.uuid4().hex}.tmp"
            rollback.symlink_to(old_target)
            os.replace(rollback, current)
        raise
    return current


def materialize_current(
    store: ModelRegistryStore,
    *,
    alias: str,
    service_mode: str,
    models_root: Path,
    records_root: Path,
) -> Path:
    """串行物化并保证末次在线复验失败时恢复旧 current。"""
    with _current_write_lock(models_root):
        return _materialize_current_locked(
            store,
            alias=alias,
            service_mode=service_mode,
            models_root=models_root,
            records_root=records_root,
        )


def validate_service_current(
    store: ModelRegistryStore,
    *,
    alias: str,
    service_mode: str,
    models_root: Path,
    records_root: Path,
) -> RegisteredModelRecord:
    """服务启动前在线复验 alias、current、manifest 与唯一部署目标。"""
    _validate_route(service_mode, alias)
    record = get_model_by_alias(store, alias)
    manifest, _ = _load_matching_manifest(records_root, record)
    current = Path(models_root) / "current"
    if not current.is_symlink() or not current.exists():
        raise ManifestReferenceError("models/current 缺失或断链")
    models_root_resolved = Path(models_root).resolve()
    expected = (models_root_resolved / "materialized" / record.model_id).resolve()
    target = current.resolve()
    if models_root_resolved not in expected.parents or target != expected:
        raise ManifestReferenceError(
            "models/current 未精确指向 alias 对应的受控 materialized 目标"
        )
    _validate_materialized_target(
        expected,
        record=record,
        manifest=manifest,
        records_root=records_root,
    )
    return record
