"""B2 — 五类可读身份解析 / 校验 / next 版本建议（设计 §3.1、§3.3、§11.6）。

预期 production API（供 viber 对照实现，模块 `versioning.ids`）::

    KINDS: tuple[str, ...]                      # ("data", "prompt", "train", "model", "eval")
    class InvalidIdentifier(ValueError)         # 一切非法 ID / 类别 / 协议的唯一异常类型
    @dataclass(frozen=True)
    class ParsedVersionId:
        kind: str                               # 五类之一
        protocol: str                           # 含前导 v，如 "v4.1"
        revision: int                           # >= 1
        __str__ -> 规范完整 ID，如 "data-v4.1-r1"
    parse_version_id(value: str) -> ParsedVersionId
    parse_data_id / parse_prompt_id / parse_train_id /
    parse_model_id / parse_eval_id(value: str) -> ParsedVersionId   # 额外校验类别
    is_valid_version_id(value: object) -> bool
    build_version_id(kind: str, protocol: str, revision: int) -> str
    suggest_next_id(kind: str, protocol: str,
                    existing: Iterable[str]) -> str
        # 只统计同 kind 且同 protocol 的既有严格合法 ID，返回 max(rN)+1 的完整 ID；
        # existing 中解析失败的条目必须忽略；空集合返回 r1。

当前 `versioning` 包尚不存在，本文件全部用例应为 RED（ModuleNotFoundError）。
"""

from __future__ import annotations

import pytest

from versioning.ids import (
    KINDS,
    InvalidIdentifier,
    ParsedVersionId,
    build_version_id,
    is_valid_version_id,
    parse_data_id,
    parse_eval_id,
    parse_model_id,
    parse_prompt_id,
    parse_train_id,
    parse_version_id,
    suggest_next_id,
)

KIND_PARSERS = {
    "data": parse_data_id,
    "prompt": parse_prompt_id,
    "train": parse_train_id,
    "model": parse_model_id,
    "eval": parse_eval_id,
}

# (kind, 完整 ID, 期望 protocol, 期望 revision)；协议段含点号（v4.1）与多位数字。
VALID_EXAMPLES = [
    ("data", "data-v4.1-r1", "v4.1", 1),
    ("prompt", "prompt-v4.1-r2", "v4.1", 2),
    ("train", "train-v4.1-r1", "v4.1", 1),
    ("model", "model-v4.1-r1", "v4.1", 1),
    ("eval", "eval-v4.1-r3", "v4.1", 3),
    ("data", "data-v4.1-r12", "v4.1", 12),
    ("model", "model-v4.10-r7", "v4.10", 7),
    ("train", "train-v5-r2", "v5", 2),
]

# 全部必须被 InvalidIdentifier 拒绝的输入（§3.1 后缀禁令、§3.3 显式选择纪律）。
INVALID_EXAMPLES = [
    # 错误类别前缀
    "dataset-v4.1-r1",
    "prompts-v4.1-r1",
    "training-v4.1-r1",
    # 缺 rN / rN 非法
    "data-v4.1",
    "data-v4.1-r",
    "data-v4.1-r0",
    "data-v4.1-r-1",
    "data-v4.1-rx",
    "data-v4.1-r1.5",
    "data-v4.1-r01",  # 前导零破坏规范形式
    # 缺协议 / 协议格式非法
    "data-r1",
    "data-v-r1",
    "data-v4.-r1",
    "data-v4.1.-r1",
    "data-4.1-r1",
    # 禁止后缀：final/new/fixed/latest/日期/seed/fold/checkpoint/自由文本
    "data-v4.1-r1-final",
    "data-v4.1-r1-new",
    "data-v4.1-r1-fixed",
    "data-v4.1-r1-latest",
    "data-v4.1-r1-2026-09-01",
    "data-v4.1-r1-seed1",
    "data-v4.1-r1-fold0",
    "data-v4.1-r1-checkpoint",
    "data-v4.1-r1-better",
    "prompt-v4.1-r2-draft",
    # 隐式 latest / 短前缀 / 模糊匹配一律拒绝（§3.3）
    "latest",
    "LATEST",
    "data-latest",
    "data-v4.1-latest",
    "data-v4",
    "data-v4.1-",
    # 大小写与空白必须严格
    "DATA-v4.1-r1",
    "Data-v4.1-r1",
    "data-V4.1-r1",
    " data-v4.1-r1",
    "data-v4.1-r1 ",
    "data-v4.1 -r1",
    "",
]


class TestKindsConstant:
    def test_kinds_are_exactly_the_five_families(self) -> None:
        assert tuple(KINDS) == ("data", "prompt", "train", "model", "eval")


class TestParseValidIds:
    @pytest.mark.parametrize(
        ("kind", "value", "protocol", "revision"),
        VALID_EXAMPLES,
        ids=[v for _, v, _, _ in VALID_EXAMPLES],
    )
    def test_generic_parser_accepts_valid_id(
        self, kind: str, value: str, protocol: str, revision: int
    ) -> None:
        parsed = parse_version_id(value)
        assert isinstance(parsed, ParsedVersionId)
        assert parsed.kind == kind
        assert parsed.protocol == protocol
        assert parsed.revision == revision
        assert str(parsed) == value

    @pytest.mark.parametrize(
        ("kind", "value", "protocol", "revision"),
        VALID_EXAMPLES,
        ids=[v for _, v, _, _ in VALID_EXAMPLES],
    )
    def test_kind_specific_parser_accepts_own_kind(
        self, kind: str, value: str, protocol: str, revision: int
    ) -> None:
        parsed = KIND_PARSERS[kind](value)
        assert parsed.kind == kind
        assert parsed.protocol == protocol
        assert parsed.revision == revision
        assert str(parsed) == value


class TestParseRejectsInvalidIds:
    @pytest.mark.parametrize("value", INVALID_EXAMPLES)
    def test_generic_parser_rejects(self, value: str) -> None:
        with pytest.raises(InvalidIdentifier):
            parse_version_id(value)

    @pytest.mark.parametrize("value", INVALID_EXAMPLES)
    def test_kind_parser_rejects(self, value: str) -> None:
        # 即便类别前缀碰巧正确（如 data-v4.1-r1-final），也必须拒绝。
        with pytest.raises(InvalidIdentifier):
            parse_data_id(value)

    @pytest.mark.parametrize("value", [None, 42, 4.1, b"data-v4.1-r1", ["data-v4.1-r1"]])
    def test_non_string_input_rejected(self, value: object) -> None:
        # None / 空以外的非字符串不得被隐式选择或静默吞掉（§3.3）。
        with pytest.raises(InvalidIdentifier):
            parse_version_id(value)  # type: ignore[arg-type]

    def test_empty_and_none_rejected_by_kind_parser(self) -> None:
        with pytest.raises(InvalidIdentifier):
            parse_prompt_id("")
        with pytest.raises(InvalidIdentifier):
            parse_prompt_id(None)  # type: ignore[arg-type]


class TestKindSpecificParsersRejectOtherKinds:
    @pytest.mark.parametrize(
        ("parser_kind", "other_kind"),
        [(k, o) for k in KIND_PARSERS for o in KIND_PARSERS if o != k],
    )
    def test_wrong_kind_rejected(self, parser_kind: str, other_kind: str) -> None:
        # 合法但属于其他对象族的完整 ID，也不得被本族解析器接受。
        value = f"{other_kind}-v4.1-r1"
        with pytest.raises(InvalidIdentifier):
            KIND_PARSERS[parser_kind](value)


class TestIsValidVersionId:
    @pytest.mark.parametrize(
        "value", [v for _, v, _, _ in VALID_EXAMPLES]
    )
    def test_valid(self, value: str) -> None:
        assert is_valid_version_id(value) is True

    @pytest.mark.parametrize("value", INVALID_EXAMPLES)
    def test_invalid(self, value: str) -> None:
        assert is_valid_version_id(value) is False

    @pytest.mark.parametrize("value", [None, 0, 42, b"data-v4.1-r1"])
    def test_non_string(self, value: object) -> None:
        assert is_valid_version_id(value) is False


class TestBuildVersionId:
    def test_builds_canonical_id(self) -> None:
        assert build_version_id("data", "v4.1", 3) == "data-v4.1-r3"
        assert build_version_id("eval", "v5", 10) == "eval-v5-r10"

    @pytest.mark.parametrize(
        ("kind", "protocol", "revision"),
        [
            ("dataset", "v4.1", 1),   # 非法类别
            ("data", "4.1", 1),       # 缺 v 前缀
            ("data", "v4.", 1),       # 协议格式非法
            ("data", "v4.1", 0),      # r0 非法
            ("data", "v4.1", -2),     # 负数非法
        ],
    )
    def test_invalid_components_rejected(
        self, kind: str, protocol: str, revision: int
    ) -> None:
        with pytest.raises(InvalidIdentifier):
            build_version_id(kind, protocol, revision)


class TestTrailingNewlineAndTypeGuards:
    """reviewer 修复的反向回归：\\Z 锚点拒绝尾随换行、bool 不得冒充 revision。"""

    def test_parse_rejects_trailing_newline(self) -> None:
        # $ 锚点会放行尾随换行，\Z 必须拒绝（§3.1 严格规范形式）。
        with pytest.raises(InvalidIdentifier):
            parse_version_id("data-v4.1-r1\n")

    def test_is_valid_rejects_trailing_newline(self) -> None:
        assert is_valid_version_id("data-v4.1-r1\n") is False

    def test_build_rejects_protocol_with_trailing_newline(self) -> None:
        # 组件级校验必须与整串解析同样严格，不得构造出不可解析的 ID。
        with pytest.raises(InvalidIdentifier):
            build_version_id("data", "v4.1\n", 1)

    def test_build_rejects_bool_revision(self) -> None:
        # bool 是 int 子类，但 True/False 不是合法 revision 序号，必须显式排除。
        with pytest.raises(InvalidIdentifier):
            build_version_id("data", "v4.1", True)
        with pytest.raises(InvalidIdentifier):
            build_version_id("data", "v4.1", False)


class TestSuggestNextId:
    def test_empty_existing_starts_at_r1(self) -> None:
        assert suggest_next_id("data", "v4.1", []) == "data-v4.1-r1"

    def test_increments_within_same_family(self) -> None:
        existing = ["data-v4.1-r1", "data-v4.1-r2"]
        assert suggest_next_id("data", "v4.1", existing) == "data-v4.1-r3"

    def test_families_increment_independently(self) -> None:
        # §3.1：五类 rN 各自独立递增，不跨族对齐。
        existing = [
            "data-v4.1-r1",
            "model-v4.1-r9",
            "train-v4.1-r7",
            "prompt-v4.1-r2",
        ]
        assert suggest_next_id("data", "v4.1", existing) == "data-v4.1-r2"
        assert suggest_next_id("model", "v4.1", existing) == "model-v4.1-r10"
        assert suggest_next_id("train", "v4.1", existing) == "train-v4.1-r8"
        assert suggest_next_id("eval", "v4.1", existing) == "eval-v4.1-r1"

    def test_other_protocol_within_same_family_ignored(self) -> None:
        # 建议值只依据同族同协议的既有集合；其他协议的 rN 不参与。
        existing = ["data-v4.2-r9", "data-v4.1-r1"]
        assert suggest_next_id("data", "v4.1", existing) == "data-v4.1-r2"
        assert suggest_next_id("data", "v4.2", existing) == "data-v4.2-r10"

    def test_malformed_entries_in_existing_ignored(self) -> None:
        existing = ["data-v4.1-r1", "junk", "data-v4.1-r0", "data-v4.1-r1-final"]
        assert suggest_next_id("data", "v4.1", existing) == "data-v4.1-r2"

    def test_invalid_kind_rejected(self) -> None:
        with pytest.raises(InvalidIdentifier):
            suggest_next_id("dataset", "v4.1", [])

    def test_invalid_protocol_rejected(self) -> None:
        with pytest.raises(InvalidIdentifier):
            suggest_next_id("data", "4.1", [])
        with pytest.raises(InvalidIdentifier):
            suggest_next_id("data", "v4.", [])

    def test_result_is_strictly_parseable(self) -> None:
        suggested = suggest_next_id("model", "v4.1", ["model-v4.1-r3"])
        parsed = parse_model_id(suggested)
        assert parsed.revision == 4
