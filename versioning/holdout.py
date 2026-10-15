"""holdout 安全：隔离布局、预注册与一次性 claim。

对应设计 §5.1、§5.6、§8。
"""

from __future__ import annotations

import os
import tempfile
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
    pre_registration_sha256: str | None = None


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


def _validate_pre_registration_sha256(value: str | None) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) != 64:
        raise ClaimError("pre_registration_sha256 必须是 64 位十六进制摘要")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ClaimError("pre_registration_sha256 必须是 64 位十六进制摘要") from exc


def _claim_to_dict(
    identity: ClaimIdentity,
    executor: str,
    pre_registration_sha256: str | None,
) -> dict[str, Any]:
    payload = {
        "identity": {
            "eval_version": identity.eval_version,
            "model_version": identity.model_version,
            "data_version": identity.data_version,
            "split": identity.split,
        },
        "executor": executor,
    }
    if pre_registration_sha256 is not None:
        payload["pre_registration_sha256"] = pre_registration_sha256
    return payload


def _publish_read_only_exclusive(target: Path, payload: bytes) -> None:
    """完整落盘后独占发布只读文件；失败不暴露半写最终路径。"""
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
        os.link(temporary_path, target)
    finally:
        if fd >= 0:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)


def freeze_pre_registration(
    source: Path, evaluations_root: Path, eval_version: str
) -> Path:
    """把预注册原子冻结到 evaluations/staging/<eval>/authorization/。"""
    parse_eval_id(eval_version)
    source = Path(source)
    try:
        payload = source.read_bytes()
    except Exception as exc:
        raise PreRegistrationError(f"无法读取 pre_registration: {source}") from exc
    parsed = load_pre_registration(source)
    if parsed.eval_version != eval_version:
        raise PreRegistrationError("pre_registration eval_version 与目标不一致")

    target = (
        Path(evaluations_root)
        / "staging"
        / eval_version
        / "authorization"
        / "pre_registration.yaml"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() == payload:
            return target
        raise PreRegistrationError(f"已冻结预注册内容冲突: {target}")
    try:
        _publish_read_only_exclusive(target, payload)
    except FileExistsError:
        if target.read_bytes() == payload:
            return target
        raise PreRegistrationError(f"已冻结预注册内容冲突: {target}")
    return target


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

    pre_registration_sha256 = raw.get("pre_registration_sha256")
    _validate_pre_registration_sha256(pre_registration_sha256)
    return HoldoutClaim(
        identity=identity,
        executor=executor,
        pre_registration_sha256=pre_registration_sha256,
    )


def _expected_data_version(authorization_dir: Path) -> str:
    """authorization_dir 父目录即为 data 版本目录名。"""
    return authorization_dir.parent.name


def create_claim(
    authorization_dir: Path,
    identity: ClaimIdentity,
    executor: str,
    *,
    pre_registration_sha256: str | None = None,
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
    _validate_pre_registration_sha256(pre_registration_sha256)

    expected_data = _expected_data_version(authorization_dir)
    if identity.data_version != expected_data:
        raise ClaimConflictError(
            f"claim 的 data_version {identity.data_version!r} 与 release {expected_data!r} 不一致"
        )

    authorization_dir.mkdir(parents=True, exist_ok=True)
    claim_path = authorization_dir / "claim.yaml"

    try:
        _publish_read_only_exclusive(
            claim_path,
            yaml.safe_dump(
                _claim_to_dict(identity, executor, pre_registration_sha256)
            ).encode("utf-8"),
        )
    except FileExistsError as exc:
        raise ClaimExistsError(
            f"claim.yaml 已存在: {claim_path}"
        ) from exc

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
    stored: HoldoutClaim,
    identity: ClaimIdentity,
    executor: str,
    pre_registration_sha256: str | None,
) -> bool:
    return (
        stored.identity == identity
        and stored.executor == executor
        and stored.pre_registration_sha256 == pre_registration_sha256
    )


def acquire_claim(
    authorization_dir: Path,
    identity: ClaimIdentity,
    executor: str,
    *,
    pre_registration_sha256: str | None = None,
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
    _validate_pre_registration_sha256(pre_registration_sha256)

    claim_path = authorization_dir / "claim.yaml"

    if not claim_path.is_file():
        create_claim(
            authorization_dir,
            identity,
            executor,
            pre_registration_sha256=pre_registration_sha256,
        )
        return HoldoutClaim(
            identity=identity,
            executor=executor,
            pre_registration_sha256=pre_registration_sha256,
        )

    try:
        stored = load_claim(authorization_dir)
    except ClaimError:
        # 已存在但不可解析：fail-closed，拒绝当作可恢复。
        raise

    if not _claims_match(stored, identity, executor, pre_registration_sha256):
        raise ClaimConflictError(
            "claim 身份/执行者与既有 claim 不一致"
        )

    consumed_path = authorization_dir / "consumed.yaml"
    if consumed_path.exists():
        raise ClaimConsumedError("claim 已被消费")

    return stored


def mark_claim_consumed(
    authorization_dir: Path,
    identity: ClaimIdentity,
    executor: str,
    *,
    pre_registration_sha256: str | None = None,
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
    _validate_pre_registration_sha256(pre_registration_sha256)

    stored = load_claim(authorization_dir)

    if not _claims_match(stored, identity, executor, pre_registration_sha256):
        raise ClaimConflictError(
            "claim 身份/执行者与既有 claim 不一致"
        )

    consumed_path = authorization_dir / "consumed.yaml"
    if consumed_path.exists():
        raise ClaimConsumedError("claim 已被消费，不得重复消费")

    payload = yaml.safe_dump(
        {
            "identity": {
                "eval_version": identity.eval_version,
                "model_version": identity.model_version,
                "data_version": identity.data_version,
                "split": identity.split,
            },
            "executor": executor,
            **(
                {"pre_registration_sha256": pre_registration_sha256}
                if pre_registration_sha256 is not None
                else {}
            ),
        }
    ).encode("utf-8")

    # 同目录临时 inode 完整落盘后再以 hard-link 的独占语义发布：写入中断
    # 不会暴露半截 consumed.yaml，并发完成也不能覆盖已有消费标记。
    try:
        _publish_read_only_exclusive(consumed_path, payload)
    except FileExistsError as exc:
        raise ClaimConsumedError("claim 已被消费，不得重复消费") from exc

    return consumed_path


def validate_claim_consumed(
    authorization_dir: Path,
    identity: ClaimIdentity,
    executor: str,
    *,
    pre_registration_sha256: str | None = None,
) -> Path:
    """校验 consumed.yaml 与不可变 claim 完全一致，不修改任何文件。"""
    _validate_claim_identity(identity)
    if not isinstance(executor, str) or not executor:
        raise ClaimError("executor 必须是非空字符串")
    _validate_pre_registration_sha256(pre_registration_sha256)

    stored = load_claim(authorization_dir)
    if not _claims_match(stored, identity, executor, pre_registration_sha256):
        raise ClaimConflictError("claim 身份/执行者/预注册摘要不一致")

    consumed_path = authorization_dir / "consumed.yaml"
    if not consumed_path.is_file():
        raise ClaimNotFound(f"consumed.yaml 不存在: {authorization_dir}")
    try:
        raw = yaml.safe_load(consumed_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ClaimError(f"无法解析 consumed.yaml: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ClaimError("consumed.yaml 顶层必须是映射")
    consumed = _dict_to_claim(raw)
    if not _claims_match(consumed, identity, executor, pre_registration_sha256):
        raise ClaimConflictError("consumed.yaml 与 claim 身份不一致")
    return consumed_path


def mark_claim_exposed(authorization_dir: Path, identity: ClaimIdentity, executor: str,
                       *, pre_registration_sha256: str, input_sha256: str,
                       predictions_sha256: str, package_sha256: str) -> Path:
    """Irreversible exposure fact, independent of score/consumed.

    An identical resend may recover; a new input/raw/package can never replace the
    original. Publish this fact BEFORE making any anonymous package available.
    """
    authorization_dir = Path(authorization_dir)
    if any(path.is_symlink() for path in (authorization_dir, *authorization_dir.parents)):
        raise ClaimConflictError('prediction exposure authorization cannot contain symlinks')
    if identity.data_version != _expected_data_version(authorization_dir):
        raise ClaimConflictError('prediction exposure must belong to the claimed data release')
    claim = load_claim(authorization_dir)
    if not _claims_match(claim, identity, executor, pre_registration_sha256):
        raise ClaimConflictError('prediction exposure claim binding mismatch')
    for value in (pre_registration_sha256, input_sha256, predictions_sha256, package_sha256):
        if value is None:
            raise ClaimError('prediction exposure requires explicit full SHA256 bindings')
        _validate_pre_registration_sha256(value)
    payload = {**_claim_to_dict(identity, executor, pre_registration_sha256),
        'schema_version': 'tensile-holdout-exposure/v1', 'input_sha256': input_sha256,
        'predictions_sha256': predictions_sha256, 'package_sha256': package_sha256}
    target = Path(authorization_dir) / 'exposed.yaml'
    encoded = yaml.safe_dump(payload).encode('utf-8')
    if target.exists():
        if target.is_symlink() or target.read_bytes() != encoded:
            raise ClaimConflictError('prediction exposure binding drift; only identical recovery allowed')
        return target
    if (Path(authorization_dir) / 'consumed.yaml').exists():
        raise ClaimConsumedError('consumed claim cannot create a new prediction exposure')
    try:
        _publish_read_only_exclusive(target, encoded)
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != encoded:
            raise ClaimConflictError('concurrent prediction exposure binding drift')
    return target
