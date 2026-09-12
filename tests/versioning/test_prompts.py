"""B5 — Prompt 版本注册、不可变性与训练 input 冻结副本。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
§5.2（Prompt 版本结构与 records/prompts 单一正式位置、字段 schema）、
§3.1（prompt 属五类可读身份，复用 versioning.ids 规则）、
§3.3（版本关系显式记录，禁止 latest/短前缀/隐式解析）、
§5.3（训练 input/ 冻结结构）与 §7（显式选择、缺参 fail-closed）、
§8（同名正式对象只增不改，发现同名必须停止）、
§9（双机版本分配：创建版本时调用方必须显式给出完整版本号，系统可以
建议下一个 rN，但不能静默决定）、§11.6（版本冲突：工具不得自动选择
下一个编号，由使用者核对现有版本后明确指定新编号）。

预期 production API（供 viber 对照实现，模块 ``versioning.prompts``）::

    PROMPT_REQUIRED_FIELDS: tuple[str, ...]
        # 恰好为 ("version", "protocol", "system_prompt", "user_prompt",
        #          "output_fields")

    class PromptError(ValueError)               # prompt 域异常基类
    class PromptNotFound(PromptError)           # 引用的正式 prompt 文件不存在
    class PromptConflict(PromptError)
        # 同 ID 正式文件已存在（重复注册）或冻结目标已存在（重复冻结）；
        # 拒绝，原对象不动
    class PromptSchemaError(PromptError)
        # prompt 文件 schema / 字段值 / version 字段与文件名一致性校验失败
        # （篡改破坏不变量的 fail-closed 出口）
    class FrozenPromptMismatch(PromptError)
        # 冻结副本缺失、损坏或与正式版本结构化不一致（篡改检测出口）

    @dataclass(frozen=True)
    class PromptDefinition
        # version: str                  完整 prompt ID，如 "prompt-v4.1-r1"
        # protocol: str                 文件 protocol 标签，非空字符串
        # system_prompt: str            非空字符串
        # user_prompt: str              非空字符串
        # output_fields: tuple[str, ...]  非空序列，元素为非空且不重复的字符串

    def prompt_path(root: Path, version: str) -> Path
        # version 必须经 versioning.ids.parse_prompt_id 校验
        # （latest / 短前缀 / None / 其他类别 -> InvalidIdentifier）；
        # 返回 root/records/prompts/<version>.yaml，不要求文件存在。

    def parse_prompt_definition(mapping: Mapping) -> PromptDefinition
        # 缺必填字段 / 字段值非法（version 非完整 prompt ID、protocol 空或非字符串、
        # system_prompt/user_prompt 空或非字符串、output_fields 为空序列 / 非序列 /
        # 含空或非字符串元素 / 含重复元素）-> PromptSchemaError。

    def create_prompt(root: Path, protocol: str, *, system_prompt: str,
                      user_prompt: str, output_fields: Sequence[str],
                      protocol_label: str | None = None,
                      version: str | None = None) -> str
        # 注册新正式 prompt 版本并写入 records/prompts/<version>.yaml
        # （必要时创建目录），返回完整版本 ID。
        # version 合同为必填（显式版本纪律，设计 §9/§11.6）：调用方必须
        #   显式给出完整版本号；缺省（不传）与显式 None 完全等价，均立即
        #   抛 InvalidIdentifier，不产生任何文件、不占用序号。签名保留
        #   ``version: str | None = None`` 只是为了让“缺省”与 None 走同一
        #   fail-closed 出口（而不是 TypeError）；绝不允许把 None 解释为
        #   “帮我分配下一个”。系统不存在任何自动分配分支。
        # “下一个 rN”的两段式用法：调用方先收集 records/prompts 下既有
        #   正式文件名（单一正式位置，§5.2），调用既有建议函数
        #   versioning.ids.suggest_next_id("prompt", protocol, existing=...)
        #   取建议值（该函数合同不变：纯建议，不注册、不占用序号，同族
        #   同协议内取 max+1，不同协议独立计数），核对后显式传给 version；
        #   调用方核对后也可以另选其他显式版本号，决定权始终在调用方。
        # protocol 为 ID 协议段（如 "v4.1"），非法 -> InvalidIdentifier。
        # version 必须为完整 prompt ID 且协议段 == protocol
        #   （否则 InvalidIdentifier）；目标文件已存在 -> PromptConflict
        #   （不可变：拒绝，原文件逐字节不动）。
        # 全部字段先经 parse_prompt_definition 语义校验，非法 -> PromptSchemaError
        #   且不产生任何文件、不占用序号（fail-closed at registration）。
        # protocol_label=None 时文件 protocol 字段取 protocol 本身。

    def load_prompt(root: Path, version: str) -> PromptDefinition
        # 唯一读取入口，只接受完整 prompt ID
        #   （latest / 短前缀 / None -> InvalidIdentifier）；
        # 文件不存在 -> PromptNotFound；
        # 文件 version 字段与文件名不一致或 schema 非法 -> PromptSchemaError
        #   （篡改 fail-closed，绝不返回未校验内容）。

    def freeze_prompt(root: Path, prompt_version: str, train_version: str) -> Path
        # 训练准备冻结：把 records/prompts/<prompt_version>.yaml 逐字节复制到
        #   root/workspace/runs/<train_version>/input/prompt.yaml，
        #   来源 prompt ID 由副本内 version 字段记录，返回目标路径。
        # prompt_version / train_version 先各自经 parse_prompt_id / parse_train_id
        #   校验（latest / 短前缀 / None / 类别不符 -> InvalidIdentifier）；
        # 正式文件不存在 -> PromptNotFound；源文件 load 校验失败 -> PromptSchemaError
        #   （篡改 fail-closed，不产生任何副本、不创建 workspace 残留目录）；
        # 冻结目标已存在 -> PromptConflict
        #   （钉死语义：重复冻结拒绝而非幂等覆盖，原副本逐字节不动，对齐 §8
        #   “发现同名必须停止，不自动复用、补写、覆盖或删除”）。
        # 同一 prompt 版本允许冻结进多个不同 train 目录（§5.2 版本可复用，
        #   但每个训练目录持有自身完整冻结副本）。

    def verify_frozen_prompt(root: Path, prompt_version: str,
                             train_version: str) -> None
        # 一致性校验入口（YAML 结构化比较，不生成或保存身份哈希，对齐 §5.2）：
        # 两边 ID 先校验（-> InvalidIdentifier）；正式侧按 load_prompt 语义
        #   fail-closed；副本缺失 / 非合法 YAML / schema 非法 /
        #   与正式版本结构化不一致 -> FrozenPromptMismatch；一致则不返回。

    本模块不提供任何“当前 prompt”隐式解析入口：公开 API 命名中不出现
    current/latest 语义；任何获取 prompt 的路径必须显式传完整 ID。

B5 契约修订（显式版本纪律）：本文件初版在 ``versioning.prompts`` 尚不存在时
编写（当时全部用例 RED）；production 落地后曾 93 例全绿，但 reviewer 指出
create_prompt 对 version=None 静默调用 suggest_next_id 自动分配版本，违反
设计 §9/§11.6（“创建版本时调用方必须显式给出完整版本号；系统可以建议
下一个 rN，但不能静默决定”）。本次修订把 version 钉为必填（缺省/None ->
InvalidIdentifier），原自动分配用例全部改写为“建议 -> 显式传入”两段式，
递增、跨协议独立计数、冲突拒绝、原文件不动等语义断言全部保留。
production 未同步修复时，显式纪律用例为有效 RED（create_prompt 仍静默
接受 version=None；失效集合 = TestExplicitVersionDiscipline 3 例 +
test_explicit_version_malformed_rejected 的 None 参数化 1 例），
其余用例保持 GREEN。
所有用例只在 pytest ``tmp_path`` 下模拟仓库根，不触碰真实 records/ 与 workspace/。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import versioning.prompts as prompts_module
from versioning.ids import InvalidIdentifier, suggest_next_id
from versioning.prompts import (
    PROMPT_REQUIRED_FIELDS,
    FrozenPromptMismatch,
    PromptConflict,
    PromptDefinition,
    PromptError,
    PromptNotFound,
    PromptSchemaError,
    create_prompt,
    freeze_prompt,
    load_prompt,
    parse_prompt_definition,
    prompt_path,
    verify_frozen_prompt,
)

REQUIRED_FIELD_NAMES = frozenset(
    {"version", "protocol", "system_prompt", "user_prompt", "output_fields"}
)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """模拟仓库根目录。"""
    return tmp_path


def _content(**overrides: object) -> dict:
    data: dict = {
        "system_prompt": "系统提示词完整正文",
        "user_prompt": "用户提示词完整正文",
        "output_fields": ["clip_state", "fracture_mechanism"],
    }
    data.update(overrides)
    return data


def _existing_prompt_versions(root: Path) -> list[str]:
    """调用方视角收集 records/prompts 下既有正式 prompt ID（§5.2 单一正式位置）。"""
    prompts_dir = root / "records" / "prompts"
    if not prompts_dir.is_dir():
        return []
    return [path.stem for path in prompts_dir.glob("*.yaml")]


def _suggest_next_prompt(root: Path, protocol: str) -> str:
    """两段式第一步：取“下一个 rN”建议值（纯建议，不注册、不占用序号）。"""
    return suggest_next_id(
        "prompt", protocol, existing=_existing_prompt_versions(root)
    )


def _register_next(root: Path, protocol: str, **content: object) -> str:
    """两段式注册：先建议取值，核对后显式传给 create_prompt（设计 §9/§11.6）。"""
    version = _suggest_next_prompt(root, protocol)
    return create_prompt(root, protocol, version=version, **content)


def _register_v41_r1(root: Path) -> str:
    return _register_next(root, "v4.1", **_content())


def _assert_no_prompt_files(root: Path) -> None:
    """断言 records/prompts 下不存在任何正式 prompt 文件。"""
    prompts_dir = root / "records" / "prompts"
    leftovers = list(prompts_dir.glob("*.yaml")) if prompts_dir.is_dir() else []
    assert leftovers == []


def _valid_prompt_dict(**overrides: object) -> dict:
    data: dict = {
        "version": "prompt-v4.1-r1",
        "protocol": "tensile-vlm/v4.1",
        "system_prompt": "系统提示词完整正文",
        "user_prompt": "用户提示词完整正文",
        "output_fields": ["clip_state", "fracture_mechanism"],
    }
    data.update(overrides)
    return data


def _rewrite_prompt_file(root: Path, prompt_id: str, **overrides: object) -> None:
    # prompt_id 定位目标文件；overrides 覆写文件内字段（含 version 字段本身）。
    path = root / "records" / "prompts" / f"{prompt_id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(overrides)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


class TestCreatePrompt:
    def test_create_happy_path_writes_records_prompts(self, root: Path) -> None:
        version = _register_v41_r1(root)
        assert version == "prompt-v4.1-r1"

        formal = root / "records" / "prompts" / f"{version}.yaml"
        assert formal.is_file()

        loaded = load_prompt(root, version)
        assert isinstance(loaded, PromptDefinition)
        assert loaded.version == version
        assert loaded.protocol == "v4.1"
        assert loaded.system_prompt == "系统提示词完整正文"
        assert loaded.user_prompt == "用户提示词完整正文"
        assert tuple(loaded.output_fields) == ("clip_state", "fracture_mechanism")

    @pytest.mark.parametrize("protocol", ["banana", "4.1", "v4.1-r1", ""])
    def test_create_invalid_protocol_rejected(
        self, root: Path, protocol: str
    ) -> None:
        # 显式传合法 version，使拒绝可归因于 protocol 非法；version 缺省
        # 本身即拒绝（见 TestExplicitVersionDiscipline）。无论 protocol
        # 校验与 version 协议段一致性校验的先后，均抛 InvalidIdentifier。
        with pytest.raises(InvalidIdentifier):
            create_prompt(root, protocol, version="prompt-v4.1-r1", **_content())

    def test_revision_increments_within_same_protocol(self, root: Path) -> None:
        # 递增语义保留，但决定权交还调用方：每步先取建议值，核对后显式传入
        first = _suggest_next_prompt(root, "v4.1")
        assert first == "prompt-v4.1-r1"
        assert create_prompt(root, "v4.1", version=first, **_content()) == first

        second = _suggest_next_prompt(root, "v4.1")
        assert second == "prompt-v4.1-r2"
        assert (
            create_prompt(
                root, "v4.1", version=second, **_content(system_prompt="另一份正文")
            )
            == second
        )

        third = _suggest_next_prompt(root, "v4.1")
        assert third == "prompt-v4.1-r3"
        assert create_prompt(root, "v4.1", version=third, **_content()) == third

    def test_revision_counted_independently_per_protocol(self, root: Path) -> None:
        # 两段式注册：建议值同族同协议内递增，跨协议独立计数
        assert _register_next(root, "v4.1", **_content()) == "prompt-v4.1-r1"
        assert _register_next(root, "v5", **_content()) == "prompt-v5-r1"
        assert _register_next(root, "v4.10", **_content()) == "prompt-v4.10-r1"

    def test_protocol_label_default_and_explicit(self, root: Path) -> None:
        v1 = _register_next(root, "v4.1", **_content())
        assert load_prompt(root, v1).protocol == "v4.1"

        v2 = _register_next(
            root, "v4.1", protocol_label="tensile-vlm/v4.1", **_content()
        )
        assert load_prompt(root, v2).protocol == "tensile-vlm/v4.1"

    def test_explicit_version_registered(self, root: Path) -> None:
        version = create_prompt(root, "v4.1", version="prompt-v4.1-r2", **_content())
        assert version == "prompt-v4.1-r2"
        assert (root / "records" / "prompts" / "prompt-v4.1-r2.yaml").is_file()
        # 显式占用后，建议值取 max+1（跳过已注册序号），仍由调用方显式传入
        suggested = _suggest_next_prompt(root, "v4.1")
        assert suggested == "prompt-v4.1-r3"
        registered = create_prompt(root, "v4.1", version=suggested, **_content())
        assert registered == "prompt-v4.1-r3"

    def test_explicit_version_protocol_mismatch_rejected(self, root: Path) -> None:
        with pytest.raises(InvalidIdentifier):
            create_prompt(root, "v4.1", version="prompt-v5-r1", **_content())

    @pytest.mark.parametrize(
        "bad_version",
        # 显式给出但非法的 version：非完整 ID、latest、跨类别、r0、非字符串；
        # None 同样是非法 version（与缺省等价拒绝，见
        # TestExplicitVersionDiscipline；此处一并钉死异常类型）。
        ["prompt-v4.1", "latest", "data-v4.1-r1", "prompt-v4.1-r0", 41, None],
    )
    def test_explicit_version_malformed_rejected(
        self, root: Path, bad_version: object
    ) -> None:
        with pytest.raises(InvalidIdentifier):
            create_prompt(root, "v4.1", version=bad_version, **_content())

    def test_duplicate_id_rejected_and_original_untouched(self, root: Path) -> None:
        version = _register_v41_r1(root)
        formal = root / "records" / "prompts" / f"{version}.yaml"
        before = formal.read_bytes()

        with pytest.raises(PromptConflict):
            create_prompt(
                root,
                "v4.1",
                version=version,
                **_content(system_prompt="被覆盖的恶意正文"),
            )

        # 不可变：原文件逐字节不动，加载结果不变
        assert formal.read_bytes() == before
        assert load_prompt(root, version).system_prompt == "系统提示词完整正文"

    @pytest.mark.parametrize(
        "bad_content",
        [
            {"system_prompt": ""},
            {"user_prompt": ""},
            {"output_fields": []},
            {"output_fields": ["clip_state", "clip_state"]},
        ],
    )
    def test_create_invalid_content_writes_nothing(
        self, root: Path, bad_content: dict
    ) -> None:
        suggested = _suggest_next_prompt(root, "v4.1")
        assert suggested == "prompt-v4.1-r1"
        with pytest.raises(PromptSchemaError):
            create_prompt(root, "v4.1", version=suggested, **_content(**bad_content))

        _assert_no_prompt_files(root)

        # 失败不占用序号：随后两段式注册仍得 r1
        assert _register_next(root, "v4.1", **_content()) == "prompt-v4.1-r1"


class TestExplicitVersionDiscipline:
    """B5 契约修订：version 必填，杜绝静默自动分配（设计 §9/§11.6）。

    设计 §9：“创建版本时调用方必须显式给出完整版本号。系统可以建议
    下一个 rN，但不能静默决定。”§11.6：“工具不得……自动选择下一个编号；
    由使用者核对现有版本后明确指定新编号。”因此缺省与显式 None 均立即
    拒绝（InvalidIdentifier，与既有“显式 version 非法”同一异常类型），
    “下一个 rN”只能由调用方经 suggest_next_id 建议后显式传入。
    """

    def test_missing_version_kwarg_rejected_writes_nothing(
        self, root: Path
    ) -> None:
        # 缺省（不传 version）：立即拒绝，不得静默分配下一个 rN
        with pytest.raises(InvalidIdentifier):
            create_prompt(root, "v4.1", **_content())
        _assert_no_prompt_files(root)

    def test_explicit_none_version_rejected_writes_nothing(
        self, root: Path
    ) -> None:
        # 显式 None：与缺省完全等价，不存在自动分配分支
        with pytest.raises(InvalidIdentifier):
            create_prompt(root, "v4.1", version=None, **_content())
        _assert_no_prompt_files(root)

    def test_rejection_does_not_consume_revision(self, root: Path) -> None:
        # 拒绝不占用序号：随后两段式注册仍从 r1 起
        with pytest.raises(InvalidIdentifier):
            create_prompt(root, "v4.1", version=None, **_content())
        assert _register_next(root, "v4.1", **_content()) == "prompt-v4.1-r1"

    def test_suggest_then_explicit_two_step_registration(
        self, root: Path
    ) -> None:
        # 两段式用法：调用方收集既有版本 -> suggest_next_id 取建议值 ->
        # 核对后显式传给 create_prompt -> 注册成功，且可用完整 ID 读回。
        existing = _existing_prompt_versions(root)
        assert existing == []
        suggested = suggest_next_id("prompt", "v4.1", existing=existing)
        assert suggested == "prompt-v4.1-r1"

        # 建议是纯建议：不写文件、不占用序号，重复建议结果不变
        _assert_no_prompt_files(root)
        assert _suggest_next_prompt(root, "v4.1") == suggested

        registered = create_prompt(root, "v4.1", version=suggested, **_content())
        assert registered == suggested
        assert load_prompt(root, registered).version == suggested
        assert _existing_prompt_versions(root) == [suggested]

    def test_caller_may_override_suggestion(self, root: Path) -> None:
        # 决定权在调用方：核对建议后可以另选其他显式版本号，建议值不注册
        suggested = _suggest_next_prompt(root, "v4.1")
        assert suggested == "prompt-v4.1-r1"

        chosen = create_prompt(
            root, "v4.1", version="prompt-v4.1-r3", **_content()
        )
        assert chosen == "prompt-v4.1-r3"
        assert _existing_prompt_versions(root) == ["prompt-v4.1-r3"]

        # 建议取 max+1 而非首个空闲号（与既有 suggest_next_id 合同一致）
        assert _suggest_next_prompt(root, "v4.1") == "prompt-v4.1-r4"


class TestPromptSchema:
    def test_required_fields_constant(self) -> None:
        assert set(PROMPT_REQUIRED_FIELDS) == REQUIRED_FIELD_NAMES

    def test_valid_mapping_accepted(self) -> None:
        meta = parse_prompt_definition(_valid_prompt_dict())
        assert meta.version == "prompt-v4.1-r1"
        assert meta.protocol == "tensile-vlm/v4.1"
        assert tuple(meta.output_fields) == ("clip_state", "fracture_mechanism")

    @pytest.mark.parametrize("field", sorted(REQUIRED_FIELD_NAMES))
    def test_missing_required_field_rejected(self, field: str) -> None:
        data = _valid_prompt_dict()
        del data[field]
        with pytest.raises(PromptSchemaError):
            parse_prompt_definition(data)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("version", "prompt-v4.1"),  # 缺 revision 段
            ("version", "data-v4.1-r1"),  # 非 prompt 类别
            ("version", "prompt-v4.1-r0"),  # revision 从 1 开始
            ("version", "latest"),
            ("version", 41),
            ("protocol", ""),
            ("protocol", 41),
            ("system_prompt", ""),
            ("system_prompt", None),
            ("system_prompt", 123),
            ("user_prompt", ""),
            ("user_prompt", None),
            ("output_fields", []),
            ("output_fields", "clip_state"),  # 必须是序列
            ("output_fields", [""]),
            ("output_fields", [1]),
            ("output_fields", ["clip_state", "clip_state"]),  # 重复字段
        ],
    )
    def test_invalid_field_value_rejected(self, field: str, value: object) -> None:
        with pytest.raises(PromptSchemaError):
            parse_prompt_definition(_valid_prompt_dict(**{field: value}))


class TestLoadPrompt:
    def test_load_round_trip(self, root: Path) -> None:
        version = _register_next(
            root, "v4.1", protocol_label="tensile-vlm/v4.1", **_content()
        )
        loaded = load_prompt(root, version)
        assert loaded.version == version
        assert loaded.protocol == "tensile-vlm/v4.1"
        assert loaded.system_prompt == "系统提示词完整正文"

    def test_load_unknown_version_rejected(self, root: Path) -> None:
        _register_v41_r1(root)
        with pytest.raises(PromptNotFound):
            load_prompt(root, "prompt-v4.1-r99")

    @pytest.mark.parametrize(
        "bad_version",
        ["latest", "prompt-v4.1", "prompt-v4.1-r", "r1", "", None, 41],
    )
    def test_load_requires_full_prompt_id(
        self, root: Path, bad_version: object
    ) -> None:
        _register_v41_r1(root)
        with pytest.raises(InvalidIdentifier):
            load_prompt(root, bad_version)

    def test_load_other_kind_rejected(self, root: Path) -> None:
        _register_v41_r1(root)
        with pytest.raises(InvalidIdentifier):
            load_prompt(root, "data-v4.1-r1")

    def test_load_detects_version_field_filename_mismatch(self, root: Path) -> None:
        # 篡改路径 fail-closed：文件内 version 与正式文件名不一致必须拒绝
        version = _register_v41_r1(root)
        _rewrite_prompt_file(root, version, version="prompt-v4.1-r99")
        with pytest.raises(PromptSchemaError):
            load_prompt(root, version)

    def test_load_detects_schema_broken_file(self, root: Path) -> None:
        version = _register_v41_r1(root)
        _rewrite_prompt_file(root, version, system_prompt="")
        with pytest.raises(PromptSchemaError):
            load_prompt(root, version)


class TestFreezePrompt:
    def test_freeze_happy_path_byte_identical_and_records_source(
        self, root: Path
    ) -> None:
        version = _register_v41_r1(root)
        target = freeze_prompt(root, version, "train-v4.1-r1")

        expected = (
            root / "workspace" / "runs" / "train-v4.1-r1" / "input" / "prompt.yaml"
        )
        assert target == expected
        assert target.is_file()

        formal = root / "records" / "prompts" / f"{version}.yaml"
        # 冻结副本与正式版本逐字节一致
        assert target.read_bytes() == formal.read_bytes()
        # 来源 prompt ID 由副本内 version 字段记录
        copied = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert copied["version"] == version

    def test_freeze_then_verify_passes(self, root: Path) -> None:
        version = _register_v41_r1(root)
        freeze_prompt(root, version, "train-v4.1-r1")
        verify_frozen_prompt(root, version, "train-v4.1-r1")  # 不抛异常即通过

    @pytest.mark.parametrize(
        "bad_train",
        ["latest", "train-v4.1", "train-v4.1-r0", "prompt-v4.1-r1", "", None, 7],
    )
    def test_freeze_invalid_train_id_rejected(
        self, root: Path, bad_train: object
    ) -> None:
        version = _register_v41_r1(root)
        with pytest.raises(InvalidIdentifier):
            freeze_prompt(root, version, bad_train)

    @pytest.mark.parametrize(
        "bad_prompt",
        ["latest", "prompt-v4.1", "prompt-v4.1-r0", "train-v4.1-r1", "", None],
    )
    def test_freeze_invalid_prompt_id_rejected(
        self, root: Path, bad_prompt: object
    ) -> None:
        with pytest.raises(InvalidIdentifier):
            freeze_prompt(root, bad_prompt, "train-v4.1-r1")

    def test_freeze_unknown_prompt_rejected_and_no_side_effects(
        self, root: Path
    ) -> None:
        with pytest.raises(PromptNotFound):
            freeze_prompt(root, "prompt-v4.1-r99", "train-v4.1-r1")
        # fail-closed：不创建训练目录或 input 残留
        assert not (root / "workspace").exists()

    def test_repeat_freeze_same_train_rejected_and_copy_untouched(
        self, root: Path
    ) -> None:
        # 钉死语义：重复冻结同一 train 目录拒绝（非幂等覆盖）
        version = _register_v41_r1(root)
        target = freeze_prompt(root, version, "train-v4.1-r1")
        before = target.read_bytes()

        with pytest.raises(PromptConflict):
            freeze_prompt(root, version, "train-v4.1-r1")

        assert target.read_bytes() == before

    def test_same_prompt_reusable_across_trains(self, root: Path) -> None:
        version = _register_v41_r1(root)
        t1 = freeze_prompt(root, version, "train-v4.1-r1")
        t2 = freeze_prompt(root, version, "train-v4.1-r2")
        assert t1 != t2
        assert t1.is_file() and t2.is_file()
        assert t1.read_bytes() == t2.read_bytes()
        verify_frozen_prompt(root, version, "train-v4.1-r1")
        verify_frozen_prompt(root, version, "train-v4.1-r2")

    def test_freeze_schema_broken_source_rejected_without_copy(
        self, root: Path
    ) -> None:
        # 篡改路径 fail-closed：源文件被破坏时不得冻结出任何副本
        version = _register_v41_r1(root)
        _rewrite_prompt_file(root, version, user_prompt="")

        with pytest.raises(PromptSchemaError):
            freeze_prompt(root, version, "train-v4.1-r1")

        assert not (
            root / "workspace" / "runs" / "train-v4.1-r1" / "input" / "prompt.yaml"
        ).exists()


class TestFrozenIntegrity:
    def test_verify_detects_tampered_source_after_freeze(self, root: Path) -> None:
        # 一致性校验：冻结后正式文件内容被改（schema 仍合法），结构化比较必须发现
        version = _register_v41_r1(root)
        freeze_prompt(root, version, "train-v4.1-r1")
        _rewrite_prompt_file(root, version, system_prompt="被篡改的正文")

        with pytest.raises(FrozenPromptMismatch):
            verify_frozen_prompt(root, version, "train-v4.1-r1")

    def test_verify_detects_tampered_frozen_copy(self, root: Path) -> None:
        version = _register_v41_r1(root)
        target = freeze_prompt(root, version, "train-v4.1-r1")
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        data["output_fields"] = ["evil_field"]
        target.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        with pytest.raises(FrozenPromptMismatch):
            verify_frozen_prompt(root, version, "train-v4.1-r1")

    def test_verify_missing_frozen_copy_rejected(self, root: Path) -> None:
        version = _register_v41_r1(root)
        with pytest.raises(FrozenPromptMismatch):
            verify_frozen_prompt(root, version, "train-v4.1-r1")

    def test_verify_fail_closed_when_source_schema_broken(self, root: Path) -> None:
        version = _register_v41_r1(root)
        freeze_prompt(root, version, "train-v4.1-r1")
        _rewrite_prompt_file(root, version, output_fields=[])

        with pytest.raises(PromptSchemaError):
            verify_frozen_prompt(root, version, "train-v4.1-r1")

    @pytest.mark.parametrize("bad_train", ["latest", "train-v4.1", None])
    def test_verify_invalid_train_id_rejected(
        self, root: Path, bad_train: object
    ) -> None:
        version = _register_v41_r1(root)
        freeze_prompt(root, version, "train-v4.1-r1")
        with pytest.raises(InvalidIdentifier):
            verify_frozen_prompt(root, version, bad_train)

    @pytest.mark.parametrize("bad_prompt", ["latest", "prompt-v4.1", None])
    def test_verify_invalid_prompt_id_rejected(
        self, root: Path, bad_prompt: object
    ) -> None:
        version = _register_v41_r1(root)
        freeze_prompt(root, version, "train-v4.1-r1")
        with pytest.raises(InvalidIdentifier):
            verify_frozen_prompt(root, bad_prompt, "train-v4.1-r1")

    def test_verify_unknown_prompt_rejected(self, root: Path) -> None:
        # 正式侧按 load_prompt 语义 fail-closed：不存在的 prompt 拒绝校验，
        # 且先于副本缺失检查（副本同样不存在时应报 PromptNotFound）
        with pytest.raises(PromptNotFound):
            verify_frozen_prompt(root, "prompt-v4.1-r99", "train-v4.1-r1")


class TestResolutionDiscipline:
    def test_no_implicit_current_or_latest_prompt_api(self) -> None:
        # 禁止扫描历史目录猜测“当前” Prompt：模块公开 API 不得出现
        # current/latest 语义的隐式解析入口。
        public_names = [
            name for name in dir(prompts_module) if not name.startswith("_")
        ]
        offenders = [
            name
            for name in public_names
            if "current" in name.lower() or "latest" in name.lower()
        ]
        assert offenders == []

    def test_single_formal_location_contract(self, root: Path) -> None:
        # 正式 Prompt 唯一位置：records/prompts/<version>.yaml
        version = _register_v41_r1(root)
        assert (
            prompt_path(root, version)
            == root / "records" / "prompts" / f"{version}.yaml"
        )

    @pytest.mark.parametrize("bad_version", ["latest", "prompt-v4.1", "data-v4.1-r1"])
    def test_prompt_path_requires_full_prompt_id(
        self, root: Path, bad_version: object
    ) -> None:
        with pytest.raises(InvalidIdentifier):
            prompt_path(root, bad_version)

    def test_prompt_path_does_not_require_existing_file(self, root: Path) -> None:
        # prompt_path 只做 ID 校验与路径构造，不要求文件已存在
        path = prompt_path(root, "prompt-v9.9-r1")
        assert path == root / "records" / "prompts" / "prompt-v9.9-r1.yaml"
        assert not path.exists()

    def test_error_hierarchy(self) -> None:
        # 域异常均继承 PromptError，且 PromptError 是 ValueError
        # （与 versioning.data_release / versioning.state 风格一致）
        for exc in (
            PromptNotFound,
            PromptConflict,
            PromptSchemaError,
            FrozenPromptMismatch,
        ):
            assert issubclass(exc, PromptError)
        assert issubclass(PromptError, ValueError)

@pytest.mark.parametrize('operation', ['create', 'freeze'])
def test_concurrent_prompt_publication_has_one_winner(tmp_path, monkeypatch, operation):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    target = (tmp_path / 'records/prompts/prompt-v4.1-r1.yaml' if operation == 'create'
              else tmp_path / 'workspace/runs/train-v4.1-r1/input/prompt.yaml')
    if operation == 'freeze':
        for revision in (1, 2):
            create_prompt(tmp_path, 'v4.1', version=f'prompt-v4.1-r{revision}',
                          system_prompt=f'system {revision}', user_prompt='user', output_fields=['x'])
    barrier = threading.Barrier(2)
    original_exists = Path.exists
    def synchronized_exists(path):
        result = original_exists(path)
        if path == target and not result:
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(Path, 'exists', synchronized_exists)
    def publish(revision):
        try:
            if operation == 'create':
                create_prompt(tmp_path, 'v4.1', version='prompt-v4.1-r1',
                              system_prompt=f'system {revision}', user_prompt='user', output_fields=['x'])
            else:
                freeze_prompt(tmp_path, f'prompt-v4.1-r{revision}', 'train-v4.1-r1')
            return ('published', revision)
        except PromptConflict:
            return ('conflict', revision)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, (1, 2)))
    assert sorted(status for status, _ in outcomes) == ['conflict', 'published']
    winner = next(revision for status, revision in outcomes if status == 'published')
    assert yaml.safe_load(target.read_text())['system_prompt'] == f'system {winner}'
    assert not list(target.parent.glob('.*.tmp'))
