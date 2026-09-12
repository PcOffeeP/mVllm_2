"""Prompt 版本注册、不可变性与训练 input 冻结副本。

对应设计 §5.2、§3.1、§3.3、§5.3、§7、§8。
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from versioning.ids import (
    InvalidIdentifier,
    parse_prompt_id,
    parse_train_id,
)

_TMP_WRITE_COUNTER = itertools.count(1)

PROMPT_REQUIRED_FIELDS: tuple[str, ...] = (
    "version",
    "protocol",
    "system_prompt",
    "user_prompt",
    "output_fields",
)


class PromptError(ValueError):
    """Prompt 域异常基类。"""


class PromptNotFound(PromptError):
    """引用的正式 prompt 文件不存在。"""


class PromptConflict(PromptError):
    """同名正式对象已存在或冻结目标已存在；拒绝，原对象不动。"""


class PromptSchemaError(PromptError):
    """prompt 文件 schema / 字段值 / version 字段与文件名一致性校验失败。"""


class FrozenPromptMismatch(PromptError):
    """冻结副本缺失、损坏或与正式版本结构化不一致。"""


@dataclass(frozen=True)
class PromptDefinition:
    """解析后的 prompt 定义。

    Attributes:
        version: 完整 prompt ID，例如 ``prompt-v4.1-r1``。
        protocol: 文件 protocol 标签，非空字符串。
        system_prompt: 非空字符串。
        user_prompt: 非空字符串。
        output_fields: 非空且不重复的字段名元组。
    """

    version: str
    protocol: str
    system_prompt: str
    user_prompt: str
    output_fields: tuple[str, ...]


def prompt_path(root: Path, version: str) -> Path:
    """构造正式 prompt 文件路径。

    ``version`` 必须经 ``parse_prompt_id`` 校验为完整 prompt ID；
    返回 ``root/records/prompts/<version>.yaml``，不要求文件存在。

    Raises:
        InvalidIdentifier: ``version`` 不是完整 prompt ID。
    """
    parse_prompt_id(version)
    return root / "records" / "prompts" / f"{version}.yaml"


def _train_prompt_path(root: Path, train_version: str) -> Path:
    """构造训练冻结 prompt 副本路径。"""
    return root / "workspace" / "runs" / train_version / "input" / "prompt.yaml"


def _validate_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PromptSchemaError(f"字段 {field!r} 必须是非空字符串: {value!r}")
    return value


def _validate_output_fields(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PromptSchemaError(
            f"output_fields 必须是序列: {value!r}"
        )
    if len(value) == 0:
        raise PromptSchemaError("output_fields 不能为空序列")
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise PromptSchemaError(
                f"output_fields 元素必须是非空字符串: {item!r}"
            )
        if item in seen:
            raise PromptSchemaError(f"output_fields 包含重复元素: {item!r}")
        seen.add(item)
        result.append(item)
    return tuple(result)


def parse_prompt_definition(mapping: Mapping[Any, Any]) -> PromptDefinition:
    """校验并解析 prompt 定义 mapping。

    缺必填字段、字段值非法或 version 字段非完整 prompt ID 时，
    抛出 ``PromptSchemaError``。
    """
    if not isinstance(mapping, Mapping):
        raise PromptSchemaError("输入必须是 mapping 类型")

    for field in PROMPT_REQUIRED_FIELDS:
        if field not in mapping:
            raise PromptSchemaError(f"缺少必填字段: {field}")

    version = mapping["version"]
    try:
        parse_prompt_id(version)
    except InvalidIdentifier as exc:
        raise PromptSchemaError(f"非法 version 字段: {exc}") from exc

    protocol = _validate_non_empty_string(mapping["protocol"], "protocol")
    system_prompt = _validate_non_empty_string(
        mapping["system_prompt"], "system_prompt"
    )
    user_prompt = _validate_non_empty_string(
        mapping["user_prompt"], "user_prompt"
    )
    output_fields = _validate_output_fields(mapping["output_fields"])

    return PromptDefinition(
        version=version,
        protocol=protocol,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output_fields=output_fields,
    )


def _validate_protocol_segment(protocol: str) -> None:
    """校验协议段是否合法，复用 ``parse_prompt_id`` 的协议规则。

    构造完整 prompt ID 并解析，非法时抛出 ``InvalidIdentifier``。
    """
    probe = f"prompt-{protocol}-r1"
    parse_prompt_id(probe)


def create_prompt(
    root: Path,
    protocol: str,
    *,
    system_prompt: str,
    user_prompt: str,
    output_fields: Sequence[str],
    protocol_label: str | None = None,
    version: str | None = None,
) -> str:
    """注册新正式 prompt 版本并写入 ``records/prompts/<version>.yaml``。

    返回完整版本 ID。重复 ID 或 schema 非法时拒绝，不产生任何文件。

    Raises:
        InvalidIdentifier: ``protocol`` 或显式 ``version`` 非法，或协议段不一致。
        PromptConflict: 目标文件已存在。
        PromptSchemaError: 字段 schema 非法。
    """
    _validate_protocol_segment(protocol)

    if version is None:
        raise InvalidIdentifier(
            "version 必填且须为显式完整 prompt ID；"
            "缺省或显式 None 均不被允许。"
            "可通过 versioning.ids.suggest_next_id 获取建议值后显式传入。"
        )

    parsed = parse_prompt_id(version)
    if parsed.protocol != protocol:
        raise InvalidIdentifier(
            f"显式 version 协议段 {parsed.protocol!r} 与 protocol {protocol!r} 不一致"
        )

    target = prompt_path(root, version)

    if target.exists():
        raise PromptConflict(f"prompt 已存在: {version}")

    content = {
        "version": version,
        "protocol": protocol if protocol_label is None else protocol_label,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "output_fields": list(output_fields),
    }

    # fail-closed: schema 校验通过后才写文件、占用序号
    parse_prompt_definition(content)

    target.parent.mkdir(parents=True, exist_ok=True)
    # 同目录临时文件完整写入后排他发布，目标冲突时保留先到达的版本。写入
    # 中途失败（中断 / IO 错误）时删除临时文件并原样向上抛 —— 目标
    # 路径不留半写入正式对象，重跑不被残骸阻塞。临时文件名不含目标
    # 身份前缀（以 "." 开头），不触发 records/ 下同身份冲突扫描。
    tmp = target.parent / (
        f".create-prompt-{os.getpid()}-{next(_TMP_WRITE_COUNTER)}.tmp"
    )
    try:
        tmp.write_text(
            yaml.safe_dump(content, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        try:
            os.link(tmp, target)
        except FileExistsError as exc:
            raise PromptConflict(f"prompt 已存在: {version}") from exc
    finally:
        tmp.unlink(missing_ok=True)

    return version


def load_prompt(root: Path, version: str) -> PromptDefinition:
    """读取正式 prompt 文件并完整校验。

    只接受完整 prompt ID；文件不存在、version 字段与文件名不一致
    或 schema 非法时均拒绝。

    Raises:
        InvalidIdentifier: ``version`` 不是完整 prompt ID。
        PromptNotFound: 文件不存在。
        PromptSchemaError: schema 非法或 version 字段与文件名不一致。
    """
    parse_prompt_id(version)
    path = prompt_path(root, version)

    if not path.is_file():
        raise PromptNotFound(f"prompt 不存在: {version}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PromptSchemaError(f"无法解析 YAML: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise PromptSchemaError("prompt 文件顶层必须是 mapping")

    if raw.get("version") != version:
        raise PromptSchemaError(
            f"文件 version 字段 {raw.get('version')!r} 与文件名 {version!r} 不一致"
        )

    return parse_prompt_definition(raw)


def freeze_prompt(
    root: Path, prompt_version: str, train_version: str
) -> Path:
    """把正式 prompt 逐字节复制到训练目录冻结副本。

    来源 prompt ID 由副本内 ``version`` 字段记录。目标已存在时拒绝。

    Raises:
        InvalidIdentifier: ``prompt_version`` 或 ``train_version`` 非法。
        PromptNotFound: 正式 prompt 不存在。
        PromptSchemaError: 正式 prompt 文件 schema 非法。
        PromptConflict: 冻结目标已存在。
    """
    parse_prompt_id(prompt_version)
    parse_train_id(train_version)

    # 先按 load_prompt 语义校验来源（含存在性与 schema）
    source_path = prompt_path(root, prompt_version)
    load_prompt(root, prompt_version)

    target = _train_prompt_path(root, train_version)
    if target.exists():
        raise PromptConflict(f"冻结副本已存在: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / (
        f".freeze-prompt-{os.getpid()}-{next(_TMP_WRITE_COUNTER)}.tmp"
    )
    try:
        tmp.write_bytes(source_path.read_bytes())
        try:
            os.link(tmp, target)
        except FileExistsError as exc:
            raise PromptConflict(f"冻结副本已存在: {target}") from exc
    finally:
        tmp.unlink(missing_ok=True)

    return target


def verify_frozen_prompt(
    root: Path, prompt_version: str, train_version: str
) -> None:
    """校验训练冻结副本与正式 prompt 结构化一致。

    顺序：双 ID 校验 -> 正式侧 load_prompt 语义 -> 副本结构化比较。

    Raises:
        InvalidIdentifier: ID 非法。
        PromptNotFound: 正式 prompt 不存在（先于副本缺失检查）。
        PromptSchemaError: 正式 prompt schema 非法。
        FrozenPromptMismatch: 副本缺失、损坏或与正式版本不一致。
    """
    parse_prompt_id(prompt_version)
    parse_train_id(train_version)

    formal = load_prompt(root, prompt_version)

    target = _train_prompt_path(root, train_version)
    if not target.is_file():
        raise FrozenPromptMismatch(f"冻结副本缺失: {target}")

    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FrozenPromptMismatch(f"无法解析冻结副本 YAML: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise FrozenPromptMismatch("冻结副本顶层必须是 mapping")

    try:
        frozen = parse_prompt_definition(raw)
    except PromptSchemaError as exc:
        raise FrozenPromptMismatch(f"冻结副本 schema 非法: {exc}") from exc

    if frozen != formal:
        raise FrozenPromptMismatch("冻结副本与正式 prompt 结构化不一致")
