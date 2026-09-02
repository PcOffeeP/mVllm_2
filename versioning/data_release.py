"""数据 release 生命周期、release.yaml 管理与受控状态更新。

对应设计 §5.1、§5.6、§8、§10、D032。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from versioning.ids import InvalidIdentifier, parse_data_id
from versioning.state import (
    DataStatus,
    IllegalTransition,
    ReferenceNotAllowed,
    transition_data_status,
    validate_data_status_for_new_reference,
)

RELEASE_REQUIRED_FIELDS: tuple[str, ...] = (
    "version",
    "protocol",
    "state",
    "purpose",
    "training_allowed",
    "description",
    "sample_count",
    "source_batches",
    "splits",
    "status",
)

_HOLDOUT_REQUIRED_SUBDIRS = (
    "media",
    "evaluation_inputs",
    "sealed_ground_truth",
    "authorization",
)


class DataReleaseError(ValueError):
    """数据 release 域异常基类。"""


class ReleaseNotFound(DataReleaseError):
    """引用的版本不存在 / 未封存。"""


class ReleaseConflict(DataReleaseError):
    """同名正式对象已存在（二次 seal / 覆盖拒绝）。"""


class ImmutableReleaseError(DataReleaseError):
    """封存后 payload 失去只读性等不可变性破坏。"""


class ReleaseSchemaError(DataReleaseError):
    """release.yaml schema / 字段值 / 一致性校验失败。"""


class ReleaseLifecycle(StrEnum):
    """数据 release 生命周期状态。"""

    WORKING = "working"
    RELEASE_STAGING = "release_staging"
    SEALED = "sealed"


@dataclass(frozen=True)
class ReleaseMetadata:
    """解析后的 release.yaml 内容。"""

    version: str
    protocol: str
    state: str
    purpose: str
    training_allowed: bool
    description: str
    sample_count: int
    source_batches: tuple[str, ...]
    splits: Mapping[str, Mapping[str, int]]
    status: DataStatus
    replacement: str | None = None


def _release_dir(root: Path, version: str) -> Path:
    return root / "releases" / version


def _staging_dir(root: Path, version: str) -> Path:
    return root / "release_staging" / version


def _working_dir(root: Path, name: str) -> Path:
    return root / "working" / name


def lifecycle_state(root: Path, name: str) -> ReleaseLifecycle:
    """依据目录存在性判定生命周期状态。

    Raises:
        ReleaseNotFound: 三处皆无。
        DataReleaseError: 多处同时存在（布局损坏）。
    """
    in_working = _working_dir(root, name).is_dir()
    in_staging = _staging_dir(root, name).is_dir()
    in_releases = _release_dir(root, name).is_dir()

    count = sum((in_working, in_staging, in_releases))
    if count == 0:
        raise ReleaseNotFound(f"未找到 release: {name!r}")
    if count > 1:
        raise DataReleaseError(f"布局损坏，{name!r} 同时出现在多个生命周期位置")

    if in_working:
        return ReleaseLifecycle.WORKING
    if in_staging:
        return ReleaseLifecycle.RELEASE_STAGING
    return ReleaseLifecycle.SEALED


_PROTOCOL_SIDECAR = ".release_protocol"


def _extract_version_protocol(protocol: str) -> str:
    """从可能带命名空间的 protocol 标签中提取版本协议段（如 v4.1）。"""
    # 测试辅助函数会把 release.yaml 的 protocol 标签（如 tensile-vlm/v4.1）
    # 同时传入 stage_release；suggest_next_id 只接受 bare vX.Y，因此取最后一段。
    candidate = protocol.rsplit("/", 1)[-1]
    return candidate


def stage_release(
    root: Path, working_name: str, protocol: str, *, version: str
) -> str:
    """working -> release_staging，以显式 version 占号。

    Raises:
        IllegalTransition: working 目录不存在（已转出 / 逆转尝试）。
        InvalidIdentifier: version 或 protocol 非法 / 协议段不符。
        ReleaseConflict: releases/ 或 release_staging/ 同名已存在。
    """
    parsed = parse_data_id(version)
    full_id = str(parsed)

    version_protocol = _extract_version_protocol(protocol)
    if version_protocol != parsed.protocol:
        raise InvalidIdentifier(
            f"protocol 标签裸段 {version_protocol!r} 与版本协议段 {parsed.protocol!r} 不符"
        )

    target = _staging_dir(root, full_id)
    release_target = _release_dir(root, full_id)
    if target.exists() or release_target.exists():
        raise ReleaseConflict(f"release 已存在: {full_id!r}")

    working = _working_dir(root, working_name)
    if not working.is_dir():
        raise IllegalTransition(
            f"无法 stage，working 目录不存在: {working_name!r}"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    working.rename(target)

    # 保存原始 protocol 标签，供 seal_release 在 protocol=None 时作为默认值。
    (target / _PROTOCOL_SIDECAR).write_text(protocol, encoding="utf-8")

    return full_id


def _validate_release_identity_fields(
    version: str,
    protocol: str,
    state: str,
    purpose: str,
    training_allowed: bool,
    description: str,
    sample_count: int,
    source_batches: Sequence[str],
    splits: Mapping[str, Mapping[str, int]],
) -> None:
    """校验 release.yaml 中除 status/replacement 外的身份字段。"""
    if not isinstance(protocol, str) or not protocol:
        raise ReleaseSchemaError("protocol 必须是非空字符串")
    if state != "sealed":
        raise ReleaseSchemaError(f"封存态 release.yaml 的 state 必须为 sealed，得到 {state!r}")
    if purpose not in ("development", "holdout"):
        raise ReleaseSchemaError(f"非法 purpose: {purpose!r}")
    if not isinstance(training_allowed, bool):
        raise ReleaseSchemaError("training_allowed 必须为布尔值")
    if purpose == "holdout" and training_allowed:
        raise ReleaseSchemaError("holdout 的 training_allowed 必须为 false")
    if not isinstance(description, str) or not description:
        raise ReleaseSchemaError("description 必须是非空字符串")
    if not isinstance(sample_count, int) or sample_count < 0:
        raise ReleaseSchemaError("sample_count 必须是非负整数")
    if not isinstance(source_batches, Sequence) or isinstance(source_batches, (str, bytes)):
        raise ReleaseSchemaError("source_batches 必须是非空序列")
    if len(source_batches) == 0:
        raise ReleaseSchemaError("source_batches 不能为空")
    for batch in source_batches:
        if not isinstance(batch, str) or not batch:
            raise ReleaseSchemaError("source_batches 每项必须是非空字符串")

    if not isinstance(splits, Mapping):
        raise ReleaseSchemaError("splits 必须是映射")
    if len(splits) == 0:
        raise ReleaseSchemaError("splits 不能为空")
    for fold_name, fold in splits.items():
        if not isinstance(fold_name, str) or not fold_name:
            raise ReleaseSchemaError("splits 的 fold 名必须是非空字符串")
        if not isinstance(fold, Mapping):
            raise ReleaseSchemaError(f"splits[{fold_name!r}] 必须是映射")
        for key in ("train", "validation"):
            if key not in fold:
                raise ReleaseSchemaError(f"splits[{fold_name!r}] 缺少 {key}")
            value = fold[key]
            if not isinstance(value, int) or value < 0:
                raise ReleaseSchemaError(
                    f"splits[{fold_name!r}][{key!r}] 必须是非负整数"
                )


def _validate_replacement(replacement: str | None, version: str, status: DataStatus) -> None:
    """校验 replacement 规则。"""
    if replacement is None:
        return
    if status is not DataStatus.SUPERSEDED:
        raise ReleaseSchemaError("replacement 仅在 status 为 superseded 时允许")
    try:
        parsed = parse_data_id(replacement)
    except InvalidIdentifier as exc:
        raise ReleaseSchemaError(f"replacement 非法: {exc}") from exc
    if str(parsed) == version:
        raise ReleaseSchemaError("replacement 不能指向自身")


def parse_release_metadata(mapping: Mapping[str, Any]) -> ReleaseMetadata:
    """解析并校验 release.yaml 内容。

    Raises:
        ReleaseSchemaError: 任何 schema / 字段 / 一致性错误。
        InvalidIdentifier: version 非完整 data ID（测试通常通过 ReleaseSchemaError 捕获）。
    """
    for field in RELEASE_REQUIRED_FIELDS:
        if field not in mapping:
            raise ReleaseSchemaError(f"缺少必填字段: {field}")

    version = mapping["version"]
    try:
        parsed_version = parse_data_id(version)
    except InvalidIdentifier as exc:
        raise ReleaseSchemaError(f"version 非法: {exc}") from exc

    full_id = str(parsed_version)
    protocol = mapping["protocol"]
    state = mapping["state"]
    purpose = mapping["purpose"]
    training_allowed = mapping["training_allowed"]
    description = mapping["description"]
    sample_count = mapping["sample_count"]
    source_batches = mapping["source_batches"]
    splits = mapping["splits"]
    status_raw = mapping["status"]
    replacement = mapping.get("replacement")

    try:
        status = DataStatus(status_raw)
    except ValueError as exc:
        raise ReleaseSchemaError(f"非法 status: {status_raw!r}") from exc

    _validate_release_identity_fields(
        full_id,
        protocol,
        state,
        purpose,
        training_allowed,
        description,
        sample_count,
        source_batches,
        splits,
    )
    _validate_replacement(replacement, full_id, status)

    splits_tuple: dict[str, dict[str, int]] = {}
    for fold_name, fold in splits.items():
        splits_tuple[fold_name] = {key: int(fold[key]) for key in ("train", "validation")}

    return ReleaseMetadata(
        version=full_id,
        protocol=protocol,
        state=state,
        purpose=purpose,
        training_allowed=training_allowed,
        description=description,
        sample_count=int(sample_count),
        source_batches=tuple(str(batch) for batch in source_batches),
        splits=splits_tuple,
        status=status,
        replacement=replacement,
    )


def load_release_metadata(root: Path, version: str) -> ReleaseMetadata:
    """读 releases/<version>/release.yaml 并解析。

    Raises:
        ReleaseNotFound: 未封存。
        ReleaseSchemaError: 文件内容非法或与目录名不一致。
    """
    release_dir = _release_dir(root, version)
    yaml_path = release_dir / "release.yaml"
    if not yaml_path.is_file():
        raise ReleaseNotFound(f"版本未封存或不存在: {version!r}")

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReleaseSchemaError(f"无法读取 release.yaml: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ReleaseSchemaError("release.yaml 顶层必须是映射")

    meta = parse_release_metadata(raw)
    if meta.version != version:
        raise ReleaseSchemaError(
            f"release.yaml 中的 version {meta.version!r} 与目录 {version!r} 不一致"
        )
    return meta


def _write_release_yaml(release_dir: Path, data: dict[str, Any]) -> None:
    """写入 release.yaml，保持所有者写权限。"""
    yaml_path = release_dir / "release.yaml"
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def seal_release(
    root: Path,
    version: str,
    *,
    purpose: str,
    description: str,
    sample_count: int,
    source_batches: Sequence[str],
    splits: Mapping[str, Mapping[str, int]],
    training_allowed: bool | None = None,
    protocol: str | None = None,
) -> Path:
    """release_staging -> releases，写入 release.yaml 并封存 payload。

    Raises:
        InvalidIdentifier: version 非 data 完整 ID。
        ReleaseConflict: releases/<version> 已存在。
        IllegalTransition: staging 不存在且未封存。
        ReleaseSchemaError: 字段值违反 schema（含 holdout 显式 training_allowed=True）。
    """
    parsed_version = parse_data_id(version)
    full_id = str(parsed_version)

    release_dir = _release_dir(root, version)
    if release_dir.exists():
        raise ReleaseConflict(f"正式 release 已存在: {version!r}")

    staging = _staging_dir(root, version)
    if not staging.is_dir():
        raise IllegalTransition(f"无法 seal，staging 不存在: {version!r}")

    if purpose == "holdout":
        if training_allowed is True:
            raise ReleaseSchemaError("holdout 不允许 training_allowed=True")
        training_allowed = False
    else:
        if training_allowed is None:
            training_allowed = True

    if protocol is not None:
        resolved_protocol = protocol
    else:
        sidecar = staging / _PROTOCOL_SIDECAR
        if sidecar.is_file():
            resolved_protocol = sidecar.read_text(encoding="utf-8").strip()
        else:
            resolved_protocol = parsed_version.protocol

    # 预校验身份字段，避免移动后才发现字段非法。
    _validate_release_identity_fields(
        full_id,
        resolved_protocol,
        "sealed",
        purpose,
        training_allowed,
        description,
        sample_count,
        source_batches,
        splits,
    )

    # holdout 补齐隔离子目录（在 staging 内完成）。
    if purpose == "holdout":
        for subdir in _HOLDOUT_REQUIRED_SUBDIRS:
            (staging / subdir).mkdir(parents=True, exist_ok=True)
        # sealed_ground_truth 不得含任何 group/other 位。
        (staging / "sealed_ground_truth").chmod(0o700)

    # 写入 release.yaml（保持可写）与 README.md（保持可写）。
    release_data: dict[str, Any] = {
        "version": full_id,
        "protocol": resolved_protocol,
        "state": "sealed",
        "purpose": purpose,
        "training_allowed": training_allowed,
        "description": description,
        "sample_count": sample_count,
        "source_batches": list(source_batches),
        "splits": {
            fold: {"train": fold_splits["train"], "validation": fold_splits["validation"]}
            for fold, fold_splits in splits.items()
        },
        "status": DataStatus.ACTIVE.value,
    }
    _write_release_yaml(staging, release_data)

    readme_path = staging / "README.md"
    readme_path.write_text(
        f"# {full_id}\n\n{description}\n", encoding="utf-8"
    )

    # 删除 staging 中保存的 protocol 侧写，避免进入正式 payload。
    sidecar = staging / _PROTOCOL_SIDECAR
    if sidecar.is_file():
        sidecar.unlink()

    # 封存 payload：除 release.yaml / README.md / authorization/ 外去全部写位。
    _seal_payload(staging)

    # 全部准备就绪后再原子移动到 releases/；中途失败时 releases/ 不留半成品。
    # macOS 要求被重命名的目录本身可写，因此临时恢复 staging 的 owner 写位，
    # 移动完成后再去除 release_dir 的全部写位。
    staging.chmod(staging.stat().st_mode | 0o200)
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(release_dir)
    release_dir.chmod(release_dir.stat().st_mode & ~0o222)

    return release_dir


def _seal_payload(release_dir: Path) -> None:
    """递归去除 payload 写权限，保留受控更新通道。"""
    for child in release_dir.iterdir():
        name = child.name
        if name in ("release.yaml", "README.md", "authorization"):
            continue
        _remove_write_permissions(child)
    # release_dir 本身也去写位，防止在根下新增文件；
    # release.yaml/README.md 仍可通过自身写权限修改。
    current = release_dir.stat().st_mode
    release_dir.chmod(current & ~0o222)


def _remove_write_permissions(path: Path) -> None:
    """去除文件或目录的所有写权限位。"""
    current = path.stat().st_mode
    new_mode = current & ~0o222
    path.chmod(new_mode)
    if path.is_dir():
        for child in path.iterdir():
            _remove_write_permissions(child)


def update_release_status(
    root: Path,
    version: str,
    status: DataStatus | str,
    *,
    replacement: str | None = None,
) -> ReleaseMetadata:
    """sealed 后唯一受控修改通道：重写 release.yaml 的 status/replacement。

    Raises:
        ReleaseNotFound: 未封存。
        ReleaseSchemaError: status 非法或 replacement 规则违反。
        IllegalTransition: 状态转换非法。
    """
    try:
        current_status = DataStatus(status)
    except ValueError as exc:
        raise ReleaseSchemaError(f"非法 status: {status!r}") from exc

    meta = load_release_metadata(root, version)
    new_status = transition_data_status(meta.status, current_status)

    _validate_replacement(replacement, version, new_status)

    release_dir = _release_dir(root, version)
    yaml_path = release_dir / "release.yaml"
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReleaseSchemaError(f"无法读取 release.yaml: {exc}") from exc

    raw["status"] = new_status.value
    if replacement is not None:
        raw["replacement"] = replacement
    elif "replacement" in raw:
        del raw["replacement"]

    _write_release_yaml(release_dir, raw)

    return load_release_metadata(root, version)


def assert_payload_sealed(release_dir: Path) -> None:
    """验证 payload 是否仍保持只读。

    Raises:
        ImmutableReleaseError: payload 中存在任何写权限位。
    """
    if release_dir.stat().st_mode & 0o222:
        raise ImmutableReleaseError(
            f"release 根目录仍可写: {release_dir.name}"
        )
    for child in release_dir.rglob("*"):
        # release.yaml / README.md 与整个 authorization/ 目录树跳过。
        try:
            relative = child.relative_to(release_dir)
        except ValueError:
            continue
        parts = relative.parts
        if parts[0] in ("release.yaml", "README.md", "authorization"):
            continue
        if child.stat().st_mode & 0o222:
            raise ImmutableReleaseError(
                f"payload 条目仍可写: {relative.as_posix()}"
            )


def validate_training_reference(root: Path, version: str) -> None:
    """训练引用入口（fail-closed）。

    Raises:
        ReferenceNotAllowed: 任何不允许引用的情形。
    """
    try:
        meta = load_release_metadata(root, version)
    except Exception as exc:
        raise ReferenceNotAllowed(f"无法加载 release 元数据: {exc}") from exc

    try:
        validate_data_status_for_new_reference(meta.status)
    except ReferenceNotAllowed:
        raise

    if meta.purpose == "holdout" or meta.training_allowed is not True:
        raise ReferenceNotAllowed(
            f"版本 {version} 不是可训练 development release"
        )
