"""holdout 安全：隔离布局、预注册与一次性 claim。

对应设计 §5.1、§5.6、§8。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from versioning.ids import (
    parse_data_id,
    parse_eval_id,
    parse_model_id,
)

PRE_REGISTRATION_REQUIRED_FIELDS: tuple[str, ...] = (
    "eval_version",
    "model_version",
    "data_version",
    "split",
    "rules",
    "thresholds",
    "one_time",
    "tuning_use",
    "recovery",
)


class HoldoutError(ValueError):
    """holdout 域异常基类。"""


class HoldoutStructureError(HoldoutError):
    """目录契约 / 权限隔离校验失败。"""


class PreRegistrationError(HoldoutError):
    """pre_registration.yaml 结构校验失败。"""


class ClaimError(HoldoutError):
    """claim 域异常基类（含解析失败 fail-closed）。"""


class ClaimNotFound(ClaimError):
    """引用的 claim 不存在。"""


class ClaimExistsError(ClaimError):
    """claim.yaml 已存在，拒绝重写/覆盖。"""


class ClaimConflictError(ClaimError):
    """四元组 / 执行身份 / 所属 data 版本不一致。"""


class ClaimConsumedError(ClaimError):
    """claim 已消费，不得再当可用授权 / 重复消费。"""


@dataclass(frozen=True)
class ClaimIdentity:
    """claim 四元组身份。

    本 dataclass 不做校验；合法性在 create/acquire/mark 入口校验。
    """

    eval_version: str
    model_version: str
    data_version: str
    split: str


@dataclass(frozen=True)
class HoldoutClaim:
    """holdout 一次性授权 claim。"""

    identity: ClaimIdentity
    executor: str


@dataclass(frozen=True)
class PreRegistration:
    """holdout 正式测评预注册内容。"""

    eval_version: str
    model_version: str
    data_version: str
    split: str
    rules: Any
    thresholds: Any
    one_time: bool
    tuning_use: str
    recovery: Any


def validate_holdout_layout(release_dir: Path) -> None:
    """校验 holdout 隔离布局。

    Raises:
        HoldoutStructureError: 目录缺失、权限越界或真值混入常规 payload。
    """
    required = ("media", "evaluation_inputs", "sealed_ground_truth", "authorization")
    for name in required:
        subdir = release_dir / name
        if not subdir.is_dir():
            raise HoldoutStructureError(f"缺少必要子目录: {name}")

    ground_truth = release_dir / "sealed_ground_truth"
    mode = ground_truth.stat().st_mode
    # 不得含任何 group/other 位。
    if mode & 0o077:
        raise HoldoutStructureError(
            f"sealed_ground_truth 权限含 group/other 位: {oct(mode)}"
        )

    # 真值不得混入 media/ 或 evaluation_inputs/（任何层级）。
    for name in ("media", "evaluation_inputs"):
        subdir = release_dir / name
        if subdir.is_dir():
            for leaked in subdir.rglob("sealed_ground_truth"):
                raise HoldoutStructureError(
                    f"真值条目不得出现在 {name}/ 下"
                )


def _validate_full_id(parser, value: str, field: str) -> None:
    try:
        parser(value)
    except Exception as exc:
        raise PreRegistrationError(
            f"{field} 非法: {exc}"
        ) from exc


def parse_pre_registration(mapping: Mapping[str, Any]) -> PreRegistration:
    """解析并校验 pre_registration.yaml 内容。

    Raises:
        PreRegistrationError: 任何结构 / 字段 / ID 错误。
    """
    for field in PRE_REGISTRATION_REQUIRED_FIELDS:
        if field not in mapping:
            raise PreRegistrationError(f"缺少必填字段: {field}")

    eval_version = mapping["eval_version"]
    model_version = mapping["model_version"]
    data_version = mapping["data_version"]
    split = mapping["split"]

    _validate_full_id(parse_eval_id, eval_version, "eval_version")
    _validate_full_id(parse_model_id, model_version, "model_version")
    _validate_full_id(parse_data_id, data_version, "data_version")

    if not isinstance(split, str) or not split:
        raise PreRegistrationError("split 必须是非空字符串")

    one_time = mapping["one_time"]
    if one_time is not True:
        raise PreRegistrationError("one_time 必须为 True")

    tuning_use = mapping["tuning_use"]
    if tuning_use != "forbidden":
        raise PreRegistrationError("tuning_use 必须为 forbidden")

    return PreRegistration(
        eval_version=eval_version,
        model_version=model_version,
        data_version=data_version,
        split=split,
        rules=mapping["rules"],
        thresholds=mapping["thresholds"],
        one_time=True,
        tuning_use="forbidden",
        recovery=mapping["recovery"],
    )


def load_pre_registration(path: Path) -> PreRegistration:
    """读取 pre_registration.yaml。

    Raises:
        PreRegistrationError: 文件不存在或内容非法。
    """
    if not path.is_file():
        raise PreRegistrationError(f"文件不存在: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PreRegistrationError(f"无法读取预注册文件: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise PreRegistrationError("pre_registration.yaml 顶层必须是映射")

    return parse_pre_registration(raw)


def _validate_claim_identity(identity: ClaimIdentity) -> None:
    """校验 claim 四元组均为合法完整 ID。"""
    try:
        parse_eval_id(identity.eval_version)
        parse_model_id(identity.model_version)
        parse_data_id(identity.data_version)
    except Exception as exc:
        raise ClaimError(f"identity 组件非法: {exc}") from exc

    if not isinstance(identity.split, str) or not identity.split:
        raise ClaimError("split 必须是非空字符串")


def _claim_to_dict(identity: ClaimIdentity, executor: str) -> dict[str, Any]:
    return {
        "identity": {
            "eval_version": identity.eval_version,
            "model_version": identity.model_version,
            "data_version": identity.data_version,
            "split": identity.split,
        },
        "executor": executor,
    }


def _load_claim_dict(authorization_dir: Path) -> dict[str, Any]:
    """读取 claim.yaml 为原始字典；失败抛 ClaimError（fail-closed）。"""
    claim_path = authorization_dir / "claim.yaml"
    try:
        raw = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ClaimError(f"无法解析 claim.yaml: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ClaimError("claim.yaml 顶层必须是映射")
    return raw


def _dict_to_claim(raw: Mapping[str, Any]) -> HoldoutClaim:
    """把字典转换为 HoldoutClaim。"""
    try:
        identity_raw = raw["identity"]
        identity = ClaimIdentity(
            eval_version=identity_raw["eval_version"],
            model_version=identity_raw["model_version"],
            data_version=identity_raw["data_version"],
            split=identity_raw["split"],
        )
        executor = raw["executor"]
    except Exception as exc:
        raise ClaimError(f"claim.yaml 内容结构非法: {exc}") from exc

    _validate_claim_identity(identity)
    if not isinstance(executor, str) or not executor:
        raise ClaimError("executor 必须是非空字符串")

    return HoldoutClaim(identity=identity, executor=executor)


def _expected_data_version(authorization_dir: Path) -> str:
    """authorization_dir 父目录即为 data 版本目录名。"""
    return authorization_dir.parent.name


def create_claim(
    authorization_dir: Path, identity: ClaimIdentity, executor: str
) -> Path:
    """原子创建 claim.yaml，去写位。

    Raises:
        ClaimExistsError: claim.yaml 已存在。
        ClaimConflictError: identity.data_version 与所在 release 不一致。
        ClaimError: identity 组件非法或 executor 为空/非字符串。
    """
    _validate_claim_identity(identity)
    if not isinstance(executor, str) or not executor:
        raise ClaimError("executor 必须是非空字符串")

    expected_data = _expected_data_version(authorization_dir)
    if identity.data_version != expected_data:
        raise ClaimConflictError(
            f"claim 的 data_version {identity.data_version!r} 与 release {expected_data!r} 不一致"
        )

    authorization_dir.mkdir(parents=True, exist_ok=True)
    claim_path = authorization_dir / "claim.yaml"

    fd = -1
    try:
        fd = os.open(
            str(claim_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o444,
        )
        data_bytes = yaml.safe_dump(
            _claim_to_dict(identity, executor)
        ).encode("utf-8")
        os.write(fd, data_bytes)
    except FileExistsError as exc:
        raise ClaimExistsError(
            f"claim.yaml 已存在: {claim_path}"
        ) from exc
    finally:
        if fd >= 0:
            os.close(fd)

    return claim_path


def load_claim(authorization_dir: Path) -> HoldoutClaim:
    """读取 claim.yaml。

    Raises:
        ClaimNotFound: claim.yaml 不存在。
        ClaimError: 内容不可解析。
    """
    claim_path = authorization_dir / "claim.yaml"
    if not claim_path.is_file():
        raise ClaimNotFound(f"claim.yaml 不存在: {authorization_dir}")

    raw = _load_claim_dict(authorization_dir)
    return _dict_to_claim(raw)


def _claims_match(
    stored: HoldoutClaim, identity: ClaimIdentity, executor: str
) -> bool:
    return stored.identity == identity and stored.executor == executor


def acquire_claim(
    authorization_dir: Path, identity: ClaimIdentity, executor: str
) -> HoldoutClaim:
    """首次模型调用前的全局一次性授权入口。

    Raises:
        ClaimConflictError: 四元组 / executor 不一致。
        ClaimConsumedError: 已消费。
        ClaimError: identity 非法或已有 claim 损坏。
    """
    _validate_claim_identity(identity)
    if not isinstance(executor, str) or not executor:
        raise ClaimError("executor 必须是非空字符串")

    claim_path = authorization_dir / "claim.yaml"

    if not claim_path.is_file():
        create_claim(authorization_dir, identity, executor)
        return HoldoutClaim(identity=identity, executor=executor)

    try:
        stored = load_claim(authorization_dir)
    except ClaimError:
        # 已存在但不可解析：fail-closed，拒绝当作可恢复。
        raise

    if not _claims_match(stored, identity, executor):
        raise ClaimConflictError(
            "claim 身份/执行者与既有 claim 不一致"
        )

    consumed_path = authorization_dir / "consumed.yaml"
    if consumed_path.exists():
        raise ClaimConsumedError("claim 已被消费")

    return stored


def mark_claim_consumed(
    authorization_dir: Path, identity: ClaimIdentity, executor: str
) -> Path:
    """正式 eval 完成后登记一次性消费状态。

    Raises:
        ClaimNotFound: claim.yaml 不存在。
        ClaimConflictError: 四元组 / executor 不一致。
        ClaimConsumedError: 已存在 consumed.yaml。
    """
    _validate_claim_identity(identity)
    if not isinstance(executor, str) or not executor:
        raise ClaimError("executor 必须是非空字符串")

    stored = load_claim(authorization_dir)

    if not _claims_match(stored, identity, executor):
        raise ClaimConflictError(
            "claim 身份/执行者与既有 claim 不一致"
        )

    consumed_path = authorization_dir / "consumed.yaml"
    if consumed_path.exists():
        raise ClaimConsumedError("claim 已被消费，不得重复消费")

    consumed_path.write_text(
        yaml.safe_dump(
            {
                "identity": {
                    "eval_version": identity.eval_version,
                    "model_version": identity.model_version,
                    "data_version": identity.data_version,
                    "split": identity.split,
                },
                "executor": executor,
            }
        ),
        encoding="utf-8",
    )
    # 消费标记同样只读。
    consumed_path.chmod(0o444)

    return consumed_path
