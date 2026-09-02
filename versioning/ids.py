"""五类可读版本身份解析、校验与构造。

对应设计 §3.1、§3.3、§11.6：只接受 ``data/prompt/train/model/eval`` 五族的完整
``<kind>-v<协议>-r<N>`` 标识，拒绝 latest、短前缀、后缀与隐式选择。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

KINDS: tuple[str, ...] = ("data", "prompt", "train", "model", "eval")

_KIND_SET = set(KINDS)

# 协议段：v 前缀 + 主版本号，可选 .次版本号；例如 v4.1、v4.10、v5。
# 使用 \Z 而非 $，禁止尾随换行等额外字符。
_PROTOCOL_RE = re.compile(r"^v\d+(?:\.\d+)?\Z")

# 完整 ID：kind-protocol-rN，revision 从 1 开始且无前导零。
_VERSION_ID_RE = re.compile(
    r"^(data|prompt|train|model|eval)-(v\d+(?:\.\d+)?)-r([1-9]\d*)\Z"
)


class InvalidIdentifier(ValueError):
    """非法的版本标识、类别或协议。"""


@dataclass(frozen=True)
class ParsedVersionId:
    """解析后的可读版本身份。

    Attributes:
        kind: 五类对象族之一（data/prompt/train/model/eval）。
        protocol: 协议段，含前导 ``v``，例如 ``v4.1``。
        revision: 从 1 开始的整数版本序号。
    """

    kind: str
    protocol: str
    revision: int

    def __str__(self) -> str:
        return f"{self.kind}-{self.protocol}-r{self.revision}"


def _validate_protocol(protocol: str) -> None:
    if not isinstance(protocol, str) or not _PROTOCOL_RE.match(protocol):
        raise InvalidIdentifier(f"非法协议段: {protocol!r}")


def _validate_kind(kind: str) -> None:
    if kind not in _KIND_SET:
        raise InvalidIdentifier(f"非法类别: {kind!r}")


def parse_version_id(value: object) -> ParsedVersionId:
    """解析任意合法的五类完整版本 ID。

    Raises:
        InvalidIdentifier: 输入非字符串、格式非法或类别不在五族之内。
    """
    if not isinstance(value, str):
        raise InvalidIdentifier(f"版本 ID 必须是字符串: {value!r}")

    match = _VERSION_ID_RE.match(value)
    if not match:
        raise InvalidIdentifier(f"非法版本 ID: {value!r}")

    return ParsedVersionId(
        kind=match.group(1),
        protocol=match.group(2),
        revision=int(match.group(3)),
    )


def _make_kind_parser(expected_kind: str):
    def _parse(value: str) -> ParsedVersionId:
        parsed = parse_version_id(value)
        if parsed.kind != expected_kind:
            raise InvalidIdentifier(
                f"期望 {expected_kind} 类别，得到 {parsed.kind}: {value!r}"
            )
        return parsed

    return _parse


parse_data_id = _make_kind_parser("data")
parse_prompt_id = _make_kind_parser("prompt")
parse_train_id = _make_kind_parser("train")
parse_model_id = _make_kind_parser("model")
parse_eval_id = _make_kind_parser("eval")


def is_valid_version_id(value: object) -> bool:
    """判断 ``value`` 是否为合法完整版本 ID；非字符串返回 ``False``，不抛异常。"""
    if not isinstance(value, str):
        return False
    try:
        parse_version_id(value)
    except InvalidIdentifier:
        return False
    return True


def build_version_id(kind: str, protocol: str, revision: int) -> str:
    """按组件构造规范完整 ID。

    Raises:
        InvalidIdentifier: 类别、协议或 revision 任一组件非法。
    """
    _validate_kind(kind)
    _validate_protocol(protocol)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise InvalidIdentifier(f"revision 必须是大于等于 1 的整数: {revision!r}")

    return f"{kind}-{protocol}-r{revision}"


def suggest_next_id(kind: str, protocol: str, existing: Iterable[str]) -> str:
    """在同 kind 且同 protocol 的既有合法 ID 中建议下一个 rN。

    ``existing`` 中解析失败或跨 kind/protocol 的条目会被忽略；空集合返回 ``r1``。

    Raises:
        InvalidIdentifier: ``kind`` 或 ``protocol`` 本身非法。
    """
    _validate_kind(kind)
    _validate_protocol(protocol)

    max_revision = 0
    for item in existing:
        try:
            parsed = parse_version_id(item)
        except InvalidIdentifier:
            continue
        if parsed.kind == kind and parsed.protocol == protocol:
            if parsed.revision > max_revision:
                max_revision = parsed.revision

    return f"{kind}-{protocol}-r{max_revision + 1}"
