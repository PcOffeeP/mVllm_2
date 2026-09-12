"""B9 — 离线备份 catalog 与恢复：源集合枚举、确定性 catalog、原子维护、修复与恢复。

对应设计 docs/plans/2026-09-01-readable-version-control-design.md：
§2.2、§2.10、§2.11、D036、§13.1。
"""

from __future__ import annotations

import datetime
import ctypes
import errno
import sys
import hashlib
import os
import re
import shlex
import subprocess
import tarfile
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

import yaml
from mlflow.tracking import MlflowClient

from versioning.data_release import seal_payload
from versioning.ids import parse_data_id
from versioning.manifest import ManifestError, validate_model_manifest
from versioning.mlflow_eval import get_eval_run, open_eval_store
from versioning.prompts import prompt_path
from versioning.registry import (
    MODEL_ID_TAG,
    OFFLINE_BACKUP_SCOPE_TAG,
    REGISTERED_MODEL_NAME,
    ModelRegistryStore,
    get_model,
    registry_snapshot_lock,
    validate_materialized_artifacts,
)

BACKUP_CATALOG_FILENAME: str = "backup_catalog.yaml"
BACKUP_CATALOG_SNAPSHOT_FILENAME: str = "backup_catalog.yaml.prev"
BACKUP_CATALOG_VERSION: int = 1
MLFLOW_STORE_OBJECT_ID: str = "mlflow-store"

OBJECT_TYPE_DATA_RELEASE: str = "data_release"
OBJECT_TYPE_PROMPT: str = "prompt"
OBJECT_TYPE_MODEL: str = "model"
OBJECT_TYPE_MLFLOW_STORE: str = "mlflow_store"

SCOPE_DATA_RELEASE: str = "data"
SCOPE_PROMPT: str = "prompt"
SCOPE_MLFLOW_STORE: str = "mlflow_store"

BACKUP_DIR_DATA: str = "data"
BACKUP_DIR_PROMPTS: str = "prompts"
BACKUP_DIR_MODELS: str = "models"
BACKUP_DIR_MLFLOW: str = "mlflow"

OBJECT_KEYS: frozenset[str] = frozenset(
    {
        "object_id",
        "object_type",
        "scope",
        "source",
        "backed_up_at",
        "verified",
        "byte_size",
        "sha256",
        "files",
    }
)
FILE_KEYS: frozenset[str] = frozenset({"path", "byte_size", "sha256"})


class BackupError(ValueError):
    """备份域异常基类。"""


class BackupSourceSetError(BackupError):
    """源集合枚举 fail-closed。"""


class CatalogSchemaError(BackupError):
    """catalog 不可读 / schema 非法。"""


class BackupIntegrityError(BackupError):
    """篡改 / 缺失 / 额外对象。"""


class RestoreTargetConflict(BackupError):
    """恢复目标已存在，拒绝覆盖。"""


@dataclass(frozen=True)
class BackupSource:
    object_id: str
    object_type: str
    scope: str
    source: Path
    include_paths: tuple[str, ...] | None = None
    manifest_source: Path | None = None


@dataclass(frozen=True)
class BackupFileEntry:
    path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class BackupObjectEntry:
    object_id: str
    object_type: str
    scope: str
    source: str
    backed_up_at: str
    verified: bool
    byte_size: int
    sha256: str
    files: tuple[BackupFileEntry, ...]


@dataclass(frozen=True)
class BackupCatalog:
    objects: tuple[BackupObjectEntry, ...]


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    """分块读取计算 SHA-256，避免大文件 OOM。"""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _compute_object_sha256(files: tuple[BackupFileEntry, ...]) -> str:
    """对象级确定性摘要：按文件 path/size/sha256 拼接后 sha256。"""
    hasher = hashlib.sha256()
    for entry in files:
        hasher.update(f"{entry.path}\n{entry.byte_size}\n{entry.sha256}\n".encode())
    return hasher.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _client(store: ModelRegistryStore) -> MlflowClient:
    return MlflowClient(tracking_uri=store.tracking_uri)


def _run_artifact_root(store: ModelRegistryStore, artifact_uri: str) -> Path:
    """把本地 MLflow artifact URI 解析为 store 内受控目录。"""
    parsed = urlparse(artifact_uri)
    if parsed.scheme not in {"", "file"}:
        raise BackupSourceSetError(f"离线备份不接受远程 artifact URI: {artifact_uri}")
    raw = unquote(parsed.path) if parsed.scheme == "file" else artifact_uri
    artifact_root = Path(raw).resolve()
    store_root = store.root.resolve()
    if store_root not in artifact_root.parents:
        raise BackupSourceSetError("MLflow artifact URI 越出受控 store 根")
    return artifact_root


def _tree_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _tree_digests(root: Path) -> dict[str, str]:
    """返回树内全部文件的相对 POSIX 路径 → SHA-256 映射。"""
    return {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _make_writable(path: Path) -> None:
    """递归补用户写位，仅处理只读条目；不改动已可写文件。

    备份副本维护时需临时可写，但恢复后须与源封存态同构：
    已可写文件（如 release.yaml 的 0o644）不得被提升为 0o666，
    因此仅对缺用户写位的条目补 0o200。
    """
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        try:
            mode = child.stat().st_mode
            if not mode & 0o200:
                os.chmod(child, mode | 0o200)
        except OSError:
            pass
    try:
        mode = path.stat().st_mode
        if not mode & 0o200:
            os.chmod(path, mode | 0o200)
    except OSError:
        pass


def _copy_tree_preserve(src: Path, dst: Path) -> None:
    """逐字节复制目录树并保留权限；目标已存在时先移除再复制。"""
    if dst.exists():
        _make_writable(dst)
        shutil.rmtree(dst)
    shutil.copytree(src, dst, copy_function=shutil.copy2)


def _copy_tree_atomic_replace(src: Path, dst: Path) -> None:
    """把 src 复制到 dst 旁的临时目录，校验后原子替换 dst；失败保留原 dst。"""
    pid = os.getpid()
    temp = dst.parent / f".tmp.{dst.name}.{pid}"
    old = dst.parent / f".old.{dst.name}.{pid}"
    try:
        if temp.exists():
            _make_writable(temp)
            shutil.rmtree(temp)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, temp, copy_function=shutil.copy2)
        _make_writable(temp)
        if _tree_digests(src) != _tree_digests(temp):
            raise BackupIntegrityError("临时复制与源不一致")
        if dst.exists():
            _make_writable(dst)
            _make_writable(dst.parent)
            os.replace(dst, old)
            try:
                os.replace(temp, dst)
            except Exception:
                if not dst.exists() and old.exists():
                    try:
                        os.replace(old, dst)
                    except OSError:
                        # 回滚也失败：old 是唯一健康副本，严禁删除。
                        pass
                raise
            else:
                # 仅成功路径清理 old；失败路径保留 old 作为健康副本。
                if old.exists():
                    _make_writable(old)
                    shutil.rmtree(old)
        else:
            _make_writable(temp)
            os.replace(temp, dst)
    finally:
        if temp.exists():
            _make_writable(temp)
            shutil.rmtree(temp)


def _selected_tree_digests(source: BackupSource) -> dict[str, str]:
    """返回源对象实际应进入备份的白名单文件摘要。"""
    result = _tree_digests(source.source) if source.include_paths is None else {}
    if source.include_paths is not None:
        for relative in source.include_paths:
            selected = source.source / relative
            if selected.is_file():
                result[relative] = _sha256_file(selected)
            elif selected.is_dir():
                for path in sorted(selected.rglob("*")):
                    if path.is_file():
                        result[path.relative_to(source.source).as_posix()] = _sha256_file(path)
            else:
                raise BackupSourceSetError(f"备份白名单路径缺失: {relative}")
    if source.manifest_source is not None:
        if not source.manifest_source.is_file():
            raise BackupSourceSetError("模型 manifest 备份源缺失")
        result["manifest.yaml"] = _sha256_file(source.manifest_source)
    return result


def _copy_selected_tree_atomic_replace(source: BackupSource, dst: Path) -> None:
    """只复制对象白名单，并在完整校验后原子替换目标。"""
    if source.include_paths is None:
        _copy_tree_atomic_replace(source.source, dst)
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".tmp.{dst.name}.", dir=dst.parent))
    old = dst.parent / f".old.{dst.name}.{os.getpid()}"
    try:
        for relative in source.include_paths:
            src = source.source / relative
            target = temp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, target, copy_function=shutil.copy2)
            elif src.is_file():
                shutil.copy2(src, target)
            else:
                raise BackupSourceSetError(f"备份白名单路径缺失: {relative}")
        if source.manifest_source is not None:
            shutil.copy2(source.manifest_source, temp / "manifest.yaml")
        if _selected_tree_digests(source) != _tree_digests(temp):
            raise BackupIntegrityError("模型范围白名单复制与源不一致")
        if dst.exists():
            _make_writable(dst)
            if old.exists():
                _make_writable(old)
                shutil.rmtree(old)
            os.replace(dst, old)
            try:
                os.replace(temp, dst)
            except Exception:
                if not dst.exists() and old.exists():
                    os.replace(old, dst)
                raise
            else:
                _make_writable(old)
                shutil.rmtree(old)
        else:
            os.replace(temp, dst)
    finally:
        if temp.exists():
            _make_writable(temp)
            shutil.rmtree(temp)


def _copy_file_preserve(src: Path, dst: Path) -> None:
    """逐字节复制文件；需要时让父目录可写。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.parent.exists() and not os.access(dst.parent, os.W_OK):
        _make_writable(dst.parent)
    if dst.exists():
        _make_writable(dst)
    shutil.copy2(src, dst)



def _enumerate_data_releases(data_root: Path) -> list[BackupSource]:
    releases_dir = Path(data_root) / "releases"
    sources: list[BackupSource] = []
    if not releases_dir.is_dir():
        return sources
    for path in sorted(releases_dir.iterdir()):
        if not path.is_dir():
            raise BackupSourceSetError(
                f"releases 目录包含非法非目录条目: {path.name!r}"
            )
        version = path.name
        try:
            parse_data_id(version)
        except Exception as exc:
            raise BackupSourceSetError(
                f"releases 目录 {version!r} 不是合法 data ID"
            ) from exc
        sources.append(
            BackupSource(
                object_id=version,
                object_type=OBJECT_TYPE_DATA_RELEASE,
                scope=SCOPE_DATA_RELEASE,
                source=path,
            )
        )
    return sources


def _enumerate_scoped_models(
    store: ModelRegistryStore, models_root: Path, prompts_root: Path
) -> tuple[list[BackupSource], set[str], set[str]]:
    """返回作用域模型、prompt 版本与 MLflow 文件白名单。"""
    client = _client(store)
    models_root = Path(models_root)
    prompts_root = Path(prompts_root)

    scoped_versions = []
    for version in client.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'"):
        scope = version.tags.get(OFFLINE_BACKUP_SCOPE_TAG)
        if scope:
            scoped_versions.append(version)

    model_sources: list[BackupSource] = []
    prompt_versions: set[str] = set()
    mlflow_paths: set[str] = {"mlflow.db"}

    for version in scoped_versions:
        model_id = version.tags.get(MODEL_ID_TAG)
        if not model_id:
            raise BackupSourceSetError("Registry 数值版本缺少 model_id tag")
        try:
            record = get_model(store, model_id)
        except Exception as exc:
            raise BackupSourceSetError(
                f"无法读取模型 {model_id!r} 记录"
            ) from exc

        materialized_dir = models_root / model_id
        metadata_path = materialized_dir / "materialized.yaml"
        if not metadata_path.is_file():
            raise BackupSourceSetError(
                f"作用域模型 {model_id!r} 未物化: {materialized_dir}"
            )

        try:
            metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise BackupSourceSetError(
                f"无法解析 {metadata_path}"
            ) from exc
        if not isinstance(metadata, dict):
            raise BackupSourceSetError(f"{metadata_path} 顶层不是 mapping")

        if metadata.get("model_id") != model_id:
            raise BackupSourceSetError(
                f"物化声明 model_id {metadata.get('model_id')!r} 与 Registry {model_id!r} 分歧"
            )
        if metadata.get("offline_backup_scope") != record.offline_backup_scope:
            raise BackupSourceSetError(
                f"物化声明 offline_backup_scope {metadata.get('offline_backup_scope')!r} "
                f"与 Registry tag {record.offline_backup_scope!r} 分歧"
            )

        manifest_ref = metadata.get("manifest")
        if (
            not isinstance(manifest_ref, str)
            or not manifest_ref
            or Path(manifest_ref).is_absolute()
            or ".." in Path(manifest_ref).parts
        ):
            raise BackupSourceSetError("物化模型的 manifest 引用必须是安全相对路径")
        manifest_path = prompts_root / manifest_ref
        if not manifest_path.is_file():
            raise BackupSourceSetError(
                f"作用域模型 {model_id!r} 的 manifest 缺失: {manifest_path}"
            )
        try:
            manifest = validate_model_manifest(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ManifestError) as exc:
            raise BackupSourceSetError(
                f"作用域模型 {model_id!r} 的 manifest 非法"
            ) from exc
        expected_manifest = {
            "version": record.model_id,
            "mlflow_model_version": record.version,
            "source_run_id": record.run_id,
            "source_training": record.train_id,
            "source_scope": record.source_scope,
            "artifacts": record.artifacts,
            "deploy_target": record.deploy_target,
        }
        for key, value in expected_manifest.items():
            if manifest.get(key) != value:
                raise BackupSourceSetError(
                    f"作用域模型 {model_id!r} 的 manifest.{key} 与 Registry 分歧"
                )
        try:
            validate_materialized_artifacts(record, materialized_dir)
        except Exception as exc:
            raise BackupSourceSetError(
                f"作用域模型 {model_id!r} 的声明 artifact 缺失或非法"
            ) from exc

        prompt_version = record.prompt_version
        prompt_file = prompt_path(prompts_root, prompt_version)
        if not prompt_file.is_file():
            raise BackupSourceSetError(
                f"作用域模型 {model_id!r} 引用的 prompt {prompt_version!r} 缺失: {prompt_file}"
            )

        selected_artifacts = {
            path
            for entries in record.artifacts.values()
            for kind, path in entries.items()
            if record.offline_backup_scope == "production_bundle" or kind == "adapter"
        }
        if record.offline_backup_scope == "adapter" and not selected_artifacts:
            raise BackupSourceSetError(
                f"作用域模型 {model_id!r} 未声明可供 adapter 备份的 adapter artifact"
            )

        train_run = client.get_run(record.run_id)
        train_artifact_root = _run_artifact_root(store, train_run.info.artifact_uri)
        for declared in selected_artifacts:
            relative_in_run = Path(*Path(declared).parts[1:])
            selected_source = train_artifact_root / relative_in_run
            if not selected_source.exists():
                raise BackupSourceSetError(
                    f"模型 {model_id!r} 的 MLflow 声明 artifact 缺失: {declared}"
                )
            mlflow_paths.add(
                selected_source.resolve().relative_to(store.root.resolve()).as_posix()
            )

        # 正式 eval 的文件证据按该模型精确绑定的父/子 Run 纳入；指标与 tags
        # 保存在同批 SQLite。未绑定 eval 的 adapter 仍可备份训练产物。
        if record.eval_id is not None:
            evaluation = get_eval_run(open_eval_store(store.root), record.eval_id)
            eval_run_ids = {evaluation.run_id, *(fold.run_id for fold in evaluation.folds.values())}
            for run_id in eval_run_ids:
                eval_artifact_root = _run_artifact_root(
                    store, client.get_run(run_id).info.artifact_uri
                )
                if eval_artifact_root.exists() and any(
                    path.is_file() for path in eval_artifact_root.rglob("*")
                ):
                    mlflow_paths.add(
                        eval_artifact_root.relative_to(store.root.resolve()).as_posix()
                    )

        model_sources.append(
            BackupSource(
                object_id=model_id,
                object_type=OBJECT_TYPE_MODEL,
                scope=record.offline_backup_scope,
                source=materialized_dir,
                include_paths=tuple(sorted({"materialized.yaml", *selected_artifacts})),
                manifest_source=manifest_path,
            )
        )
        prompt_versions.add(prompt_version)

    return model_sources, prompt_versions, mlflow_paths


def enumerate_backup_sources(
    store: ModelRegistryStore,
    *,
    data_root: Path,
    prompts_root: Path,
    models_root: Path,
) -> tuple[BackupSource, ...]:
    """枚举全部备份源：正式 release + 作用域模型 + 引用 prompt + 恰一个 MLflow store。"""
    data_root = Path(data_root)
    prompts_root = Path(prompts_root)
    models_root = Path(models_root)

    sources: list[BackupSource] = []
    sources.extend(_enumerate_data_releases(data_root))

    model_sources, prompt_versions, mlflow_paths = _enumerate_scoped_models(
        store, models_root, prompts_root
    )
    sources.extend(model_sources)

    for prompt_version in sorted(prompt_versions):
        sources.append(
            BackupSource(
                object_id=prompt_version,
                object_type=OBJECT_TYPE_PROMPT,
                scope=SCOPE_PROMPT,
                source=prompt_path(prompts_root, prompt_version),
            )
        )

    sources.append(
        BackupSource(
            object_id=MLFLOW_STORE_OBJECT_ID,
            object_type=OBJECT_TYPE_MLFLOW_STORE,
            scope=SCOPE_MLFLOW_STORE,
            source=Path(store.root),
            include_paths=tuple(sorted(mlflow_paths)),
        )
    )

    sources.sort(key=lambda s: s.object_id)
    return tuple(sources)


def _build_file_entries(directory: Path, prefix: str) -> tuple[BackupFileEntry, ...]:
    """扫描目录，返回按相对 path 排序的 BackupFileEntry 元组。"""
    entries: list[BackupFileEntry] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(directory).as_posix()
        full_path = f"{prefix}/{rel}" if prefix else rel
        entries.append(
            BackupFileEntry(
                path=full_path,
                byte_size=path.stat().st_size,
                sha256=_sha256_file(path),
            )
        )
    entries.sort(key=lambda e: e.path)
    return tuple(entries)


def _backup_object(source: BackupSource, backup_root: Path) -> BackupObjectEntry:
    """把单个源对象复制到备份根并构造 catalog 条目；已存在时原子替换。"""
    backup_root = Path(backup_root)
    now = _now_iso()

    if source.object_type == OBJECT_TYPE_DATA_RELEASE:
        dst = backup_root / BACKUP_DIR_DATA / source.object_id
        _copy_tree_atomic_replace(source.source, dst)
        prefix = f"{BACKUP_DIR_DATA}/{source.object_id}"
        files = _build_file_entries(dst, prefix)
    elif source.object_type == OBJECT_TYPE_PROMPT:
        dst_dir = backup_root / BACKUP_DIR_PROMPTS
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"{source.object_id}.yaml"
        tmp = dst.with_name(f".{dst.name}.tmp")
        _copy_file_preserve(source.source, tmp)
        if _sha256_file(tmp) != _sha256_file(source.source):
            tmp.unlink(missing_ok=True)
            raise BackupIntegrityError("prompt 临时复制校验失败")
        os.replace(tmp, dst)
        files = (
            BackupFileEntry(
                path=f"{BACKUP_DIR_PROMPTS}/{source.object_id}.yaml",
                byte_size=dst.stat().st_size,
                sha256=_sha256_file(dst),
            ),
        )
    elif source.object_type == OBJECT_TYPE_MODEL:
        dst = backup_root / BACKUP_DIR_MODELS / source.object_id
        _copy_selected_tree_atomic_replace(source, dst)
        prefix = f"{BACKUP_DIR_MODELS}/{source.object_id}"
        files = _build_file_entries(dst, prefix)
    elif source.object_type == OBJECT_TYPE_MLFLOW_STORE:
        dst = backup_root / BACKUP_DIR_MLFLOW
        _copy_selected_tree_atomic_replace(source, dst)
        files = _build_file_entries(dst, BACKUP_DIR_MLFLOW)
    else:
        raise BackupError(f"未知对象类型: {source.object_type!r}")

    byte_size = sum(f.byte_size for f in files)
    return BackupObjectEntry(
        object_id=source.object_id,
        object_type=source.object_type,
        scope=source.scope,
        source=str(source.source.resolve()),
        backed_up_at=now,
        verified=True,
        byte_size=byte_size,
        sha256=_compute_object_sha256(files),
        files=files,
    )


def _load_yaml_catalog(path: Path) -> Any:
    """读取 YAML；任何读取异常都视为 schema 错误。"""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CatalogSchemaError(f"无法读取 catalog: {exc}") from exc


def _validate_raw_file(raw: Mapping[str, Any]) -> None:
    if set(raw) != FILE_KEYS:
        raise CatalogSchemaError(f"文件条目键非法: {set(raw)}")
    if not isinstance(raw.get("path"), str) or not raw["path"]:
        raise CatalogSchemaError("文件 path 必须是非空字符串")
    if not isinstance(raw.get("byte_size"), int) or raw["byte_size"] < 0:
        raise CatalogSchemaError("文件 byte_size 必须是非负整数")
    if not _is_sha256(raw.get("sha256")):
        raise CatalogSchemaError("文件 sha256 非法")


def _validate_raw_object(raw: Mapping[str, Any]) -> None:
    if set(raw) != OBJECT_KEYS:
        raise CatalogSchemaError(f"对象键非法: {set(raw)}")
    for key in ("object_id", "object_type", "scope", "source", "backed_up_at"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise CatalogSchemaError(f"对象 {key} 必须是非空字符串")
    if not isinstance(raw.get("verified"), bool):
        raise CatalogSchemaError("对象 verified 必须是布尔值")
    if not isinstance(raw.get("byte_size"), int) or raw["byte_size"] < 0:
        raise CatalogSchemaError("对象 byte_size 必须是非负整数")
    if not _is_sha256(raw.get("sha256")):
        raise CatalogSchemaError("对象 sha256 非法")
    files = raw.get("files")
    if not isinstance(files, list) or not files:
        raise CatalogSchemaError("对象 files 必须是非空列表")
    for raw_file in files:
        if not isinstance(raw_file, dict):
            raise CatalogSchemaError("file 条目必须是 mapping")
        _validate_raw_file(raw_file)
    try:
        datetime.datetime.fromisoformat(raw["backed_up_at"])
    except ValueError as exc:
        raise CatalogSchemaError("backed_up_at 无法解析为 ISO-8601") from exc


def _raw_to_object_entry(raw: Mapping[str, Any]) -> BackupObjectEntry:
    files = tuple(
        BackupFileEntry(
            path=str(f["path"]),
            byte_size=int(f["byte_size"]),
            sha256=str(f["sha256"]),
        )
        for f in raw["files"]
    )
    return BackupObjectEntry(
        object_id=str(raw["object_id"]),
        object_type=str(raw["object_type"]),
        scope=str(raw["scope"]),
        source=str(raw["source"]),
        backed_up_at=str(raw["backed_up_at"]),
        verified=bool(raw["verified"]),
        byte_size=int(raw["byte_size"]),
        sha256=str(raw["sha256"]),
        files=files,
    )


def load_backup_catalog(backup_root: Path) -> BackupCatalog:
    """仅做 schema 校验并解析 catalog。"""
    backup_root = Path(backup_root)
    catalog_path = backup_root / BACKUP_CATALOG_FILENAME
    if not catalog_path.is_file():
        raise CatalogSchemaError(f"catalog 不存在: {catalog_path}")

    raw = _load_yaml_catalog(catalog_path)
    if not isinstance(raw, dict):
        raise CatalogSchemaError("catalog 顶层必须是 mapping")
    if set(raw) != {"catalog_version", "objects"}:
        raise CatalogSchemaError(
            f"catalog 顶层键非法: {set(raw)}"
        )
    if raw.get("catalog_version") != BACKUP_CATALOG_VERSION:
        raise CatalogSchemaError(
            f"catalog_version 必须为 {BACKUP_CATALOG_VERSION}"
        )
    objects = raw.get("objects")
    if not isinstance(objects, list):
        raise CatalogSchemaError("objects 必须是列表")

    entries: list[BackupObjectEntry] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for obj in objects:
        if not isinstance(obj, dict):
            raise CatalogSchemaError("对象必须是 mapping")
        _validate_raw_object(obj)
        object_id = obj["object_id"]
        if object_id in seen_ids:
            raise CatalogSchemaError(f"重复 object_id: {object_id!r}")
        seen_ids.add(object_id)
        for raw_file in obj["files"]:
            path = raw_file["path"]
            if path in seen_paths:
                raise CatalogSchemaError(f"重复文件 path: {path!r}")
            seen_paths.add(path)
        entries.append(_raw_to_object_entry(obj))

    entries.sort(key=lambda e: e.object_id)
    return BackupCatalog(objects=tuple(entries))


def _catalog_to_mapping(catalog: BackupCatalog) -> dict[str, Any]:
    return {
        "catalog_version": BACKUP_CATALOG_VERSION,
        "objects": [
            {
                "object_id": entry.object_id,
                "object_type": entry.object_type,
                "scope": entry.scope,
                "source": entry.source,
                "backed_up_at": entry.backed_up_at,
                "verified": entry.verified,
                "byte_size": entry.byte_size,
                "sha256": entry.sha256,
                "files": [
                    {
                        "path": f.path,
                        "byte_size": f.byte_size,
                        "sha256": f.sha256,
                    }
                    for f in entry.files
                ],
            }
            for entry in catalog.objects
        ],
    }


def _write_catalog_atomic(
    backup_root: Path, catalog: BackupCatalog, old_catalog_path: Path | None
) -> None:
    """原子写入 catalog：临时文件校验通过后替换，并保留上一份可读快照。"""
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    catalog_path = backup_root / BACKUP_CATALOG_FILENAME
    snapshot_path = backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME

    payload = _catalog_to_mapping(catalog)
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    bytes_data = text.encode("utf-8")

    # 临时文件写在备份根内，rename 不跨文件系统。
    fd, temp_path = tempfile.mkstemp(
        dir=backup_root, prefix=".backup_catalog.yaml.tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(bytes_data)

        # 复验临时文件可读且与内存 catalog 等值
        loaded = yaml.safe_load(Path(temp_path).read_text(encoding="utf-8"))
        if loaded != payload:
            raise BackupIntegrityError("catalog 临时文件与内存表示不一致")

        if old_catalog_path is not None and old_catalog_path.is_file():
            shutil.copy2(old_catalog_path, snapshot_path)

        os.replace(temp_path, catalog_path)
    finally:
        if Path(temp_path).exists():
            try:
                Path(temp_path).unlink()
            except OSError:
                pass


def _find_existing_entry(
    catalog: BackupCatalog | None, object_id: str
) -> BackupObjectEntry | None:
    if catalog is None:
        return None
    for entry in catalog.objects:
        if entry.object_id == object_id:
            return entry
    return None


def _build_object_entry(
    source: BackupSource,
    files: tuple[BackupFileEntry, ...],
    backed_up_at: str,
) -> BackupObjectEntry:
    """由文件条目构造 BackupObjectEntry。"""
    byte_size = sum(f.byte_size for f in files)
    return BackupObjectEntry(
        object_id=source.object_id,
        object_type=source.object_type,
        scope=source.scope,
        source=str(source.source.resolve()),
        backed_up_at=backed_up_at,
        verified=True,
        byte_size=byte_size,
        sha256=_compute_object_sha256(files),
        files=files,
    )


def _prompt_entry(dst: Path, source: BackupSource) -> BackupObjectEntry:
    """由已落盘的 prompt 文件构造条目。"""
    rel = f"{BACKUP_DIR_PROMPTS}/{source.object_id}.yaml"
    files = (
        BackupFileEntry(
            path=rel,
            byte_size=dst.stat().st_size,
            sha256=_sha256_file(dst),
        ),
    )
    return _build_object_entry(source, files, _now_iso())


def _entry_files_match_disk(
    backup_root: Path, entry: BackupObjectEntry
) -> bool:
    """catalog 声明的逐文件 size/sha256 与备份根盘上实际一致。"""
    for file_entry in entry.files:
        path = backup_root / file_entry.path
        if not path.is_file():
            return False
        if path.stat().st_size != file_entry.byte_size:
            return False
        if _sha256_file(path) != file_entry.sha256:
            return False
    return True


def _repair_or_copy(
    source: BackupSource,
    backup_root: Path,
    existing_entry: BackupObjectEntry | None,
) -> BackupObjectEntry:
    """根据现有 catalog 修复差异对象：一致则复用，不一致则 temp + 原子替换。"""
    backup_root = Path(backup_root)

    if source.object_type == OBJECT_TYPE_DATA_RELEASE:
        dst = backup_root / BACKUP_DIR_DATA / source.object_id
        prefix = f"{BACKUP_DIR_DATA}/{source.object_id}"
    elif source.object_type == OBJECT_TYPE_PROMPT:
        dst = backup_root / BACKUP_DIR_PROMPTS / f"{source.object_id}.yaml"
        prefix = BACKUP_DIR_PROMPTS
    elif source.object_type == OBJECT_TYPE_MODEL:
        dst = backup_root / BACKUP_DIR_MODELS / source.object_id
        prefix = f"{BACKUP_DIR_MODELS}/{source.object_id}"
    elif source.object_type == OBJECT_TYPE_MLFLOW_STORE:
        dst = backup_root / BACKUP_DIR_MLFLOW
        prefix = BACKUP_DIR_MLFLOW
    else:
        raise BackupError(f"未知对象类型: {source.object_type!r}")

    if existing_entry is None:
        return _backup_object(source, backup_root)

    # 一致性判断：健康对象不触发重拷（mtime/inode 不变）。
    # catalog 条目须与盘上文件一致，防篡改 catalog 被盲目复用。
    if source.object_type == OBJECT_TYPE_PROMPT:
        if (
            dst.is_file()
            and _sha256_file(dst) == _sha256_file(source.source)
            and _entry_files_match_disk(backup_root, existing_entry)
        ):
            return _build_object_entry(
                source, existing_entry.files, existing_entry.backed_up_at
            )
    else:
        if (
            dst.exists()
            and _selected_tree_digests(source) == _tree_digests(dst)
            and _entry_files_match_disk(backup_root, existing_entry)
        ):
            return _build_object_entry(
                source, existing_entry.files, existing_entry.backed_up_at
            )

    # 需要修复：整对象复制到临时目录、校验、原子替换目标。
    try:
        if source.object_type == OBJECT_TYPE_PROMPT:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.tmp")
            _copy_file_preserve(source.source, tmp)
            if _sha256_file(tmp) != _sha256_file(source.source):
                tmp.unlink(missing_ok=True)
                raise BackupIntegrityError("prompt 临时复制校验失败")
            os.replace(tmp, dst)
            return _prompt_entry(dst, source)
        _copy_selected_tree_atomic_replace(source, dst)
    except Exception as exc:
        raise BackupIntegrityError(
            f"修复对象 {source.object_id!r} 失败: {exc}"
        ) from exc

    files = _build_file_entries(dst, prefix)
    return _build_object_entry(source, files, _now_iso())


def _verify_object_files(
    backup_root: Path, entry: BackupObjectEntry
) -> None:
    """逐文件核对存在性、大小、sha256；MLflow SQLite 额外检查可查询性。"""
    for file_entry in entry.files:
        path = backup_root / file_entry.path
        if not path.is_file():
            raise BackupIntegrityError(f"文件缺失: {file_entry.path}")
        actual_size = path.stat().st_size
        if actual_size != file_entry.byte_size:
            raise BackupIntegrityError(
                f"文件大小不符 {file_entry.path}: "
                f"期望 {file_entry.byte_size}, 实际 {actual_size}"
            )
        actual_sha = _sha256_file(path)
        if actual_sha != file_entry.sha256:
            raise BackupIntegrityError(
                f"文件 sha256 不符 {file_entry.path}"
            )

    if entry.object_type == OBJECT_TYPE_MLFLOW_STORE:
        db_path = backup_root / BACKUP_DIR_MLFLOW / "mlflow.db"
        if not db_path.is_file():
            raise BackupIntegrityError("mlflow.db 缺失")
        try:
            connection = sqlite3.connect(db_path)
            try:
                result = connection.execute("PRAGMA integrity_check").fetchone()
                if result is None or result[0] != "ok":
                    raise BackupIntegrityError("mlflow.db PRAGMA integrity_check 失败")
                # runs 表必须可查（不要求非空）。
                connection.execute("SELECT count(*) FROM runs").fetchone()
            finally:
                connection.close()
        except BackupIntegrityError:
            raise
        except Exception as exc:
            raise BackupIntegrityError(f"mlflow.db 无法查询: {exc}") from exc


def _verify_no_extra_files(
    backup_root: Path,
    catalog: BackupCatalog,
    allow_prev: bool,
) -> None:
    """核对备份根实际文件集合与 catalog 声明精确一致。"""
    expected: set[str] = {BACKUP_CATALOG_FILENAME}
    if allow_prev:
        expected.add(BACKUP_CATALOG_SNAPSHOT_FILENAME)
    for entry in catalog.objects:
        expected.update(file_entry.path for file_entry in entry.files)

    actual = _tree_files(backup_root)
    extra = actual - expected
    missing = expected - actual
    if extra:
        raise BackupIntegrityError(f"备份根存在额外文件: {extra}")
    if missing:
        raise BackupIntegrityError(f"备份根缺失文件: {missing}")


def verify_backup(backup_root: Path) -> BackupCatalog:
    """load + 逐文件核对 + 额外对象核对。"""
    backup_root = Path(backup_root)
    catalog = load_backup_catalog(backup_root)
    for entry in catalog.objects:
        _verify_object_files(backup_root, entry)
    allow_prev = (backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME).is_file()
    _verify_no_extra_files(backup_root, catalog, allow_prev)
    return catalog


def _create_backup_locked(
    store: ModelRegistryStore,
    *,
    data_root: Path,
    prompts_root: Path,
    models_root: Path,
    backup_root: Path,
) -> BackupCatalog:
    """真实复制、复验修复、原子 catalog 写入；失败不改写盘上 catalog。"""
    backup_root = Path(backup_root)
    # 先完整校验源集合，避免源无效时创建空备份目录。
    sources = enumerate_backup_sources(
        store,
        data_root=data_root,
        prompts_root=prompts_root,
        models_root=models_root,
    )
    backup_root.mkdir(parents=True, exist_ok=True)

    old_catalog: BackupCatalog | None = None
    old_catalog_path = backup_root / BACKUP_CATALOG_FILENAME
    if old_catalog_path.is_file():
        try:
            old_catalog = load_backup_catalog(backup_root)
        except CatalogSchemaError:
            old_catalog = None

    # 修复/复制全部对象；按源集合顺序保证确定性。
    new_entries: list[BackupObjectEntry] = []
    for source in sources:
        existing = _find_existing_entry(old_catalog, source.object_id)
        entry = _repair_or_copy(source, backup_root, existing)
        new_entries.append(entry)

    new_entries.sort(key=lambda e: e.object_id)
    new_catalog = BackupCatalog(objects=tuple(new_entries))

    # catalog 落盘前完成全部对象校验（含 SQLite PRAGMA integrity_check）。
    for entry in new_entries:
        _verify_object_files(backup_root, entry)

    # 预检查额外对象： catalog 与 .prev 均视为合法；temp 文件已存在则也排除。
    expected_final: set[str] = {BACKUP_CATALOG_FILENAME}
    snapshot_exists = (backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME).is_file()
    if old_catalog_path.is_file() or snapshot_exists:
        expected_final.add(BACKUP_CATALOG_SNAPSHOT_FILENAME)
    for entry in new_entries:
        expected_final.update(f.path for f in entry.files)

    actual = _tree_files(backup_root)
    extra = actual - expected_final
    if extra:
        raise BackupIntegrityError(f"备份根存在额外文件: {extra}")

    # 写入 catalog（原子替换 + 快照）
    _write_catalog_atomic(backup_root, new_catalog, old_catalog_path)

    # 写入后再校验一次，确保盘状态与 catalog 一致。
    verify_backup(backup_root)
    return new_catalog


def create_backup(
    store: ModelRegistryStore,
    *,
    data_root: Path,
    prompts_root: Path,
    models_root: Path,
    backup_root: Path,
) -> BackupCatalog:
    """在 Registry 一致性快照锁内完成枚举、复制、复验与 catalog 发布。"""
    with registry_snapshot_lock(store):
        return _create_backup_locked(
            store,
            data_root=data_root,
            prompts_root=prompts_root,
            models_root=models_root,
            backup_root=backup_root,
        )


def _target_exists_for_object(
    entry: BackupObjectEntry,
    *,
    data_root: Path,
    prompts_root: Path,
    models_root: Path,
    mlflow_root: Path,
) -> bool:
    if entry.object_type == OBJECT_TYPE_DATA_RELEASE:
        return (Path(data_root) / "releases" / entry.object_id).exists()
    if entry.object_type == OBJECT_TYPE_PROMPT:
        return prompt_path(prompts_root, entry.object_id).exists()
    if entry.object_type == OBJECT_TYPE_MODEL:
        return (
            (Path(models_root) / entry.object_id).exists()
            or (
                Path(prompts_root)
                / "records"
                / "models"
                / entry.object_id
                / "manifest.yaml"
            ).exists()
        )
    if entry.object_type == OBJECT_TYPE_MLFLOW_STORE:
        root = Path(mlflow_root)
        return root.exists() and any(root.iterdir())
    return False


def _restore_object(
    entry: BackupObjectEntry,
    backup_root: Path,
    *,
    data_root: Path,
    prompts_root: Path,
    models_root: Path,
    mlflow_root: Path,
) -> None:
    backup_root = Path(backup_root)
    if entry.object_type == OBJECT_TYPE_DATA_RELEASE:
        src = backup_root / BACKUP_DIR_DATA / entry.object_id
        dst = Path(data_root) / "releases" / entry.object_id
        _copy_tree_preserve(src, dst)
        # 备份副本在维护时被补过写位；恢复后必须重放封存权限，
        # 与 versioning.data_release.seal_payload 的只读语义保持一致。
        seal_payload(dst)
    elif entry.object_type == OBJECT_TYPE_PROMPT:
        src = backup_root / BACKUP_DIR_PROMPTS / f"{entry.object_id}.yaml"
        dst = prompt_path(prompts_root, entry.object_id)
        _copy_file_preserve(src, dst)
    elif entry.object_type == OBJECT_TYPE_MODEL:
        src = backup_root / BACKUP_DIR_MODELS / entry.object_id
        dst = Path(models_root) / entry.object_id
        _copy_tree_preserve(src, dst)
        bundled_manifest = dst / "manifest.yaml"
        manifest_target = (
            Path(prompts_root)
            / "records"
            / "models"
            / entry.object_id
            / "manifest.yaml"
        )
        _copy_file_preserve(bundled_manifest, manifest_target)
        bundled_manifest.unlink()
    elif entry.object_type == OBJECT_TYPE_MLFLOW_STORE:
        src = backup_root / BACKUP_DIR_MLFLOW
        dst = Path(mlflow_root)
        if dst.exists():
            _make_writable(dst)
            shutil.rmtree(dst)
        shutil.copytree(src, dst, copy_function=shutil.copy2)
    else:
        raise BackupError(f"未知对象类型: {entry.object_type!r}")


def restore_backup(
    backup_root: Path,
    *,
    data_root: Path,
    prompts_root: Path,
    models_root: Path,
    mlflow_root: Path,
) -> None:
    """先完整校验，再按对象类型恢复到四根显式目标；失败零副作用。"""
    backup_root = Path(backup_root)
    catalog = verify_backup(backup_root)

    for entry in catalog.objects:
        if _target_exists_for_object(
            entry,
            data_root=data_root,
            prompts_root=prompts_root,
            models_root=models_root,
            mlflow_root=mlflow_root,
        ):
            raise RestoreTargetConflict(
                f"恢复目标已存在: {entry.object_id!r}"
            )

    for entry in catalog.objects:
        _restore_object(
            entry,
            backup_root,
            data_root=data_root,
            prompts_root=prompts_root,
            models_root=models_root,
            mlflow_root=mlflow_root,
        )


def _receive_backup_tree(ssh_host: str, source_root: Path, destination: Path) -> None:
    """Stream an explicit remote snapshot; never extract links or special files."""
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
               ssh_host, shlex.join(["tar", "-C", str(source_root), "-cf", "-", "."])]
    # stderr goes to disk so a verbose remote cannot deadlock a full stderr pipe.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        try:
            assert process.stdout is not None
            seen = set()
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts:
                        raise BackupIntegrityError("unsafe path in backup transport")
                    if str(path) == "." and member.isdir():
                        continue
                    if str(path) in seen or not (member.isfile() or member.isdir()):
                        raise BackupIntegrityError("duplicate or non-regular backup transport entry")
                    seen.add(str(path))
                    target = destination.joinpath(*path.parts)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        stream = archive.extractfile(member)
                        if stream is None:
                            raise BackupIntegrityError("missing backup transport content")
                        with stream, target.open("xb") as output:
                            shutil.copyfileobj(stream, output, 1024 * 1024)
            # Drain tar padding before waiting; otherwise a full pipe can block ssh.
            while process.stdout.read(1024 * 1024):
                pass
            if process.wait() != 0:
                errors.seek(0)
                raise BackupError("backup SSH transfer failed: " +
                                  errors.read(4096).decode("utf-8", errors="replace"))
        except BaseException as exc:
            if process.poll() is None:
                process.kill()
            process.wait()
            if isinstance(exc, tarfile.TarError):
                raise BackupIntegrityError("invalid or truncated backup archive") from exc
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()


def transfer_backup(*, ssh_host: str, source_backup_root: Path,
                    backup_root: Path, catalog_sha256: str) -> BackupCatalog:
    """Receive a pinned snapshot into a new directory, publishing only after verification.

    The source is an already-created backup, not the live MLflow store.
    No source files or existing destination are modified; a failed transfer can
    be retried with the same pinned catalog and a still-absent destination.
    """
    if not isinstance(ssh_host, str) or not re.fullmatch(
            r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*", ssh_host):
        raise BackupError("explicit SSH host or user@host is required")
    source = Path(source_backup_root)
    target = Path(backup_root)
    if not source.is_absolute() or not target.is_absolute() or not _is_sha256(catalog_sha256):
        raise BackupError("absolute source/destination and catalog SHA256 are required")
    if not target.parent.is_dir() or target.name in {"", ".", ".."}:
        raise BackupError("backup destination parent must already exist")
    lock = target.with_name("." + target.name + ".transfer-lock")
    # Serialize publishers without replacing an existing lock or destination.
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        if target.exists() or target.is_symlink():
            raise RestoreTargetConflict("backup transfer destination already exists")
        with tempfile.TemporaryDirectory(prefix="." + target.name + ".transfer-",
                                         dir=target.parent) as temporary:
            staging = Path(temporary)
            _receive_backup_tree(ssh_host, source, staging)
            if any(path.is_symlink() for path in staging.rglob("*")):
                raise BackupIntegrityError("backup transfer contains a symlink")
            if _sha256_file(staging / BACKUP_CATALOG_FILENAME) != catalog_sha256:
                raise BackupIntegrityError("backup catalog differs from the pinned SHA256")
            catalog = verify_backup(staging)
            if not all(entry.verified for entry in catalog.objects):
                raise BackupIntegrityError("backup contains unverified objects")
            if target.exists() or target.is_symlink():
                raise RestoreTargetConflict("backup transfer destination appeared during transfer")
            _publish_backup_directory(staging, target)
            return catalog
    finally:
        os.close(fd)
        lock.unlink()


def _publish_backup_directory(source: Path, target: Path) -> None:
    """Atomic no-replace publication on the project's Mac and Linux hosts."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = getattr(library, "renamex_np", None)
        if rename is None:
            raise BackupError("atomic no-replace rename is unavailable")
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(source), os.fsencode(target), 0x4)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename = getattr(library, "renameat2", None)
        if rename is None:
            raise BackupError("atomic no-replace rename is unavailable")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        arguments = (-100, os.fsencode(source), -100, os.fsencode(target), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise BackupError("atomic no-replace publication requires Mac or Linux")
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise RestoreTargetConflict("backup destination appeared during publication")
        raise OSError(error, os.strerror(error), str(target))
