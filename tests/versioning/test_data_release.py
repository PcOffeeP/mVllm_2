"""B3 — 数据 working→release_staging→sealed 生命周期、release.yaml 管理与受控状态更新。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
§5.1（数据版本结构与 release.yaml 字段）、§8（封存机制与不可覆盖规则）、
§10（data status 语义与下游使用规则，决策表 D032）、§11.2（封存失败 fail-closed）。

预期 production API（供 viber 对照实现，模块 ``versioning.data_release``）::

    RELEASE_REQUIRED_FIELDS: tuple[str, ...]
        # 恰好为 ("version", "protocol", "state", "purpose", "training_allowed",
        #          "description", "sample_count", "source_batches", "splits", "status")

    class DataReleaseError(ValueError)        # 数据 release 域异常基类
    class ReleaseNotFound(DataReleaseError)   # 引用的版本不存在 / 未封存
    class ReleaseConflict(DataReleaseError)   # 同名正式对象已存在（二次 seal / 覆盖拒绝）
    class ImmutableReleaseError(DataReleaseError)
        # 封存后 payload 失去只读性等不可变性破坏（验证工具入口）
    class ReleaseSchemaError(DataReleaseError)
        # release.yaml schema / 字段值 / 一致性校验失败（含 holdout 必须
        # training_allowed: false 的不变量、replacement 使用规则）

    class ReleaseLifecycle(StrEnum)
        # WORKING = "working" / RELEASE_STAGING = "release_staging" / SEALED = "sealed"

    @dataclass(frozen=True)
    class ReleaseMetadata
        # version: str                完整 data ID，如 "data-v4.1-r1"
        # protocol: str               release.yaml 的 protocol 标签（非空字符串）
        # state: str                  封存态 release.yaml 恒为 "sealed"
        # purpose: str                "development" | "holdout"
        # training_allowed: bool
        # description: str
        # sample_count: int           # >= 0
        # source_batches: tuple[str, ...]   # 非空
        # splits: Mapping[str, Mapping[str, int]]  # 每折含 train/validation 非负整数
        # status: versioning.state.DataStatus
        # replacement: str | None     # 仅 status == superseded 时允许出现

    def lifecycle_state(root: Path, name: str) -> ReleaseLifecycle
        # 依据 root/working、root/release_staging、root/releases 下的目录存在性判定；
        # 三处皆无 -> ReleaseNotFound；多处同时存在（布局损坏）-> DataReleaseError。

    def stage_release(root: Path, working_name: str, protocol: str) -> str
        # working/<working_name> -> release_staging/<version>（移动，working 目录消失）。
        # version = versioning.ids.suggest_next_id("data", protocol,
        #     existing=releases/ 与 release_staging/ 下既有目录名)；
        # staging 与 sealed 共同占用序号，不同 protocol 独立计数。
        # working/<working_name> 不存在（含已转出、逆转尝试）-> versioning.state.IllegalTransition
        # protocol 非法 -> versioning.ids.InvalidIdentifier

    def seal_release(root: Path, version: str, *, purpose: str, description: str,
                     sample_count: int, source_batches: Sequence[str],
                     splits: Mapping[str, Mapping[str, int]],
                     training_allowed: bool | None = None,
                     protocol: str | None = None) -> Path
        # release_staging/<version> -> releases/<version>，写 release.yaml
        # （state: sealed, status: active 及上述身份字段），返回正式目录路径。
        # version 校验优先于生命周期检查：非 data 完整 ID -> InvalidIdentifier。
        # releases/<version> 已存在 -> ReleaseConflict（同 ID 二次 seal 拒绝，原对象不动）。
        # staging 不存在且未封存 -> IllegalTransition（working→sealed 跳跃 / 未知版本拒绝）。
        # purpose == "holdout"：training_allowed 必须为 False（None 时自动取 False），
        #   显式 True -> ReleaseSchemaError；并补齐 holdout 子目录
        #   （media/ evaluation_inputs/ sealed_ground_truth/ authorization/），
        #   sealed_ground_truth 权限不含任何 group/other 位。
        # purpose == "development"：training_allowed None 时默认 True。
        # 封存后：payload 文件与目录去除所有写权限；release.yaml 与 README.md 保持
        #   所有者可写（Git 受控更新通道）；holdout 的 authorization/ 目录保留
        #   所有者可写（供一次性原子创建 claim.yaml），其中不预置任何文件。
        # protocol 为 None 时取 version 的协议段（如 "v4.1"）。

    def parse_release_metadata(mapping: Mapping) -> ReleaseMetadata
        # 缺必填字段 / 字段值非法 / version 非完整 data ID / purpose 或 status 非法 /
        # holdout 但 training_allowed 为真 / replacement 在非 superseded 下出现 /
        # replacement 非法或为自身 -> ReleaseSchemaError。

    def load_release_metadata(root: Path, version: str) -> ReleaseMetadata
        # 读 releases/<version>/release.yaml 并 parse；release.yaml 中 version 字段
        # 必须等于目录名 version，不一致 -> ReleaseSchemaError；
        # 未封存（无 releases/<version>）-> ReleaseNotFound。

    def update_release_status(root: Path, version: str,
                              status: DataStatus | str, *,
                              replacement: str | None = None) -> ReleaseMetadata
        # sealed 后唯一受控修改通道：仅重写 release.yaml 的 status（及可选 replacement），
        # 其余身份字段逐值保持不变。转换规则复用
        # versioning.state.transition_data_status（非法转换 -> IllegalTransition，
        # 同值幂等允许）。status 接受枚举或其值字符串；非法值 -> ReleaseSchemaError。
        # replacement 规则同 parse_release_metadata。未封存 -> ReleaseNotFound。
        # 返回更新后的 ReleaseMetadata。

    def assert_payload_sealed(release_dir: Path) -> None
        # 验证工具入口：payload（除 release.yaml / README.md / authorization/ 外）
        # 任一文件或目录带任何写权限位 -> ImmutableReleaseError；全部只读则不返回。

    def validate_training_reference(root: Path, version: str) -> None
        # 训练引用入口（fail-closed，复用 versioning.state.ReferenceNotAllowed）：
        # 版本不存在 / 未封存 / release.yaml 不可读或非法 -> ReferenceNotAllowed；
        # status != active -> ReferenceNotAllowed（语义同
        # validate_data_status_for_new_reference，D032）；
        # purpose == holdout 或 training_allowed 非 True -> ReferenceNotAllowed；
        # 仅 active 且 training_allowed 的 development release 放行（不抛异常）。

当前 ``versioning.data_release`` 尚不存在，本文件全部用例应为 RED（ModuleNotFoundError）。
所有用例只在 pytest ``tmp_path`` 下构造目录，不触碰 workspace/ 真实数据。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from versioning.data_release import (
    RELEASE_REQUIRED_FIELDS,
    DataReleaseError,
    ImmutableReleaseError,
    ReleaseConflict,
    ReleaseLifecycle,
    ReleaseMetadata,
    ReleaseNotFound,
    ReleaseSchemaError,
    assert_payload_sealed,
    lifecycle_state,
    load_release_metadata,
    parse_release_metadata,
    seal_release,
    stage_release,
    update_release_status,
    validate_training_reference,
)
from versioning.ids import InvalidIdentifier
from versioning.state import (
    DataStatus,
    IllegalTransition,
    ReferenceNotAllowed,
)

REQUIRED_FIELD_NAMES = frozenset(
    {
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
    }
)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    base = tmp_path / "data"
    (base / "working").mkdir(parents=True)
    (base / "release_staging").mkdir()
    (base / "releases").mkdir()
    return base


def _make_working(root: Path, name: str) -> Path:
    working = root / "working" / name
    (working / "datasets").mkdir(parents=True)
    (working / "datasets" / "labels.jsonl").write_text(
        '{"id": 1}\n', encoding="utf-8"
    )
    (working / "media").mkdir()
    (working / "media" / "clip.mp4").write_bytes(b"\x00\x01")
    return working


def _seal_kwargs(**overrides: object) -> dict:
    kwargs: dict = {
        "purpose": "development",
        "description": "第二轮人工审查后的正式训练数据",
        "sample_count": 2,
        "source_batches": ["batch-2026-07"],
        "splits": {"fold0": {"train": 1, "validation": 1}},
    }
    kwargs.update(overrides)
    return kwargs


def _seal_development(
    root: Path, working_name: str = "round-001", protocol: str = "v4.1", **overrides: object
) -> tuple[str, Path]:
    _make_working(root, working_name)
    version = stage_release(root, working_name, protocol)
    release_dir = seal_release(root, version, **_seal_kwargs(**overrides))
    return version, release_dir


def _valid_release_dict(**overrides: object) -> dict:
    data: dict = {
        "version": "data-v4.1-r1",
        "protocol": "tensile-vlm/v4.1",
        "state": "sealed",
        "purpose": "development",
        "training_allowed": True,
        "description": "第二轮人工审查后的正式训练数据",
        "sample_count": 1678,
        "source_batches": ["batch-2026-07"],
        "splits": {"fold0": {"train": 1253, "validation": 425}},
        "status": "active",
    }
    data.update(overrides)
    return data


class TestLifecycle:
    def test_working_to_staging_to_sealed_happy_path(self, root: Path) -> None:
        working = _make_working(root, "round-001")
        assert lifecycle_state(root, "round-001") is ReleaseLifecycle.WORKING

        version = stage_release(root, "round-001", "v4.1")
        assert version == "data-v4.1-r1"
        assert not working.exists()
        assert (root / "release_staging" / version).is_dir()
        assert lifecycle_state(root, version) is ReleaseLifecycle.RELEASE_STAGING

        release_dir = seal_release(root, version, **_seal_kwargs())
        assert release_dir == root / "releases" / version
        assert release_dir.is_dir()
        assert not (root / "release_staging" / version).exists()
        assert lifecycle_state(root, version) is ReleaseLifecycle.SEALED

    def test_lifecycle_state_unknown_name_rejected(self, root: Path) -> None:
        with pytest.raises(ReleaseNotFound):
            lifecycle_state(root, "data-v4.1-r99")

    def test_lifecycle_state_ambiguous_layout_rejected(self, root: Path) -> None:
        _make_working(root, "round-dup")
        (root / "release_staging" / "round-dup").mkdir(parents=True)
        with pytest.raises(DataReleaseError) as excinfo:
            lifecycle_state(root, "round-dup")
        assert not isinstance(excinfo.value, ReleaseNotFound)

    def test_restaging_after_stage_rejected(self, root: Path) -> None:
        _make_working(root, "round-001")
        stage_release(root, "round-001", "v4.1")
        # 已离开 working 态，重复 / 逆转 stage 拒绝
        with pytest.raises(IllegalTransition):
            stage_release(root, "round-001", "v4.1")
        assert (
            lifecycle_state(root, "data-v4.1-r1") is ReleaseLifecycle.RELEASE_STAGING
        )

    def test_seal_without_staging_rejected(self, root: Path) -> None:
        _make_working(root, "round-001")
        # working → sealed 跳跃拒绝：必须先经 release_staging
        with pytest.raises(IllegalTransition):
            seal_release(root, "data-v4.1-r1", **_seal_kwargs())
        assert lifecycle_state(root, "round-001") is ReleaseLifecycle.WORKING
        assert not (root / "releases" / "data-v4.1-r1").exists()

    def test_seal_unknown_version_rejected(self, root: Path) -> None:
        with pytest.raises(IllegalTransition):
            seal_release(root, "data-v4.1-r1", **_seal_kwargs())

    def test_stage_invalid_protocol_rejected(self, root: Path) -> None:
        _make_working(root, "round-001")
        with pytest.raises(InvalidIdentifier):
            stage_release(root, "round-001", "banana")


class TestSeal:
    def test_revision_increments_within_same_protocol(self, root: Path) -> None:
        _make_working(root, "round-001")
        v1 = stage_release(root, "round-001", "v4.1")
        assert v1 == "data-v4.1-r1"
        seal_release(root, v1, **_seal_kwargs())

        _make_working(root, "round-002")
        v2 = stage_release(root, "round-002", "v4.1")
        assert v2 == "data-v4.1-r2"

        # staging 中尚未封存的版本同样占用序号
        _make_working(root, "round-003")
        v3 = stage_release(root, "round-003", "v4.1")
        assert v3 == "data-v4.1-r3"

    def test_revision_counted_independently_per_protocol(self, root: Path) -> None:
        _make_working(root, "round-001")
        v1 = stage_release(root, "round-001", "v4.1")
        seal_release(root, v1, **_seal_kwargs())

        _make_working(root, "round-002")
        assert stage_release(root, "round-002", "v5") == "data-v5-r1"

    def test_seal_writes_release_yaml_identity_and_initial_status(
        self, root: Path
    ) -> None:
        version, release_dir = _seal_development(root)
        meta = load_release_metadata(root, version)
        assert isinstance(meta, ReleaseMetadata)
        assert meta.version == version
        assert meta.state == "sealed"
        assert meta.purpose == "development"
        assert meta.training_allowed is True
        assert meta.status is DataStatus.ACTIVE
        assert meta.replacement is None
        assert meta.description == "第二轮人工审查后的正式训练数据"
        assert meta.sample_count == 2
        assert tuple(meta.source_batches) == ("batch-2026-07",)
        assert meta.splits["fold0"]["train"] == 1
        assert meta.splits["fold0"]["validation"] == 1
        assert (release_dir / "release.yaml").is_file()

    def test_seal_protocol_label_default_and_explicit(self, root: Path) -> None:
        v1, _ = _seal_development(root, "round-001")
        assert load_release_metadata(root, v1).protocol == "v4.1"

        v2, _ = _seal_development(
            root, "round-002", protocol="tensile-vlm/v4.1"
        )
        assert load_release_metadata(root, v2).protocol == "tensile-vlm/v4.1"

    def test_double_seal_same_id_rejected(self, root: Path) -> None:
        version, release_dir = _seal_development(root)
        with pytest.raises(ReleaseConflict):
            seal_release(root, version, **_seal_kwargs())
        # 原对象未被覆盖或损坏
        assert (release_dir / "datasets" / "labels.jsonl").read_text(
            encoding="utf-8"
        ) == '{"id": 1}\n'
        assert load_release_metadata(root, version).status is DataStatus.ACTIVE

    def test_seal_rejects_non_data_or_malformed_version(self, root: Path) -> None:
        _make_working(root, "round-001")
        stage_release(root, "round-001", "v4.1")
        with pytest.raises(InvalidIdentifier):
            seal_release(root, "model-v4.1-r1", **_seal_kwargs())
        with pytest.raises(InvalidIdentifier):
            seal_release(root, "not-a-version", **_seal_kwargs())

    def test_seal_failure_leaves_no_partial_release_and_is_retryable(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # P2-2 回归：封存步骤中途失败时 releases/ 不留半成品目录，
        # staging 保持完好，且解除故障后重试 seal 可成功封存。
        _make_working(root, "round-001")
        version = stage_release(root, "round-001", "v4.1")
        staging = root / "release_staging" / version
        release_dir = root / "releases" / version

        def boom(path: Path) -> None:
            raise OSError("模拟封存中途失败")

        with monkeypatch.context() as m:
            m.setattr("versioning.data_release._seal_payload", boom)
            with pytest.raises(OSError, match="模拟封存中途失败"):
                seal_release(root, version, **_seal_kwargs())

        # 失败路径：releases/ 无残留，staging 完好，生命周期仍为 staging
        assert not release_dir.exists()
        assert staging.is_dir()
        assert lifecycle_state(root, version) is ReleaseLifecycle.RELEASE_STAGING

        # 故障解除后重试：seal 成功且 payload 真正封存
        result = seal_release(root, version, **_seal_kwargs())
        assert result == release_dir
        assert release_dir.is_dir()
        assert not staging.exists()
        assert lifecycle_state(root, version) is ReleaseLifecycle.SEALED
        assert_payload_sealed(release_dir)


class TestReleaseSchema:
    def test_required_fields_constant(self) -> None:
        assert set(RELEASE_REQUIRED_FIELDS) == REQUIRED_FIELD_NAMES

    def test_valid_mapping_accepted(self) -> None:
        meta = parse_release_metadata(_valid_release_dict())
        assert meta.version == "data-v4.1-r1"
        assert meta.protocol == "tensile-vlm/v4.1"
        assert meta.status is DataStatus.ACTIVE
        assert meta.replacement is None

    @pytest.mark.parametrize("field", sorted(REQUIRED_FIELD_NAMES))
    def test_missing_required_field_rejected(self, field: str) -> None:
        data = _valid_release_dict()
        del data[field]
        with pytest.raises(ReleaseSchemaError):
            parse_release_metadata(data)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("version", "data-v4.1"),  # 缺 revision 段
            ("version", "model-v4.1-r1"),  # 非 data 类别
            ("version", "data-v4.1-r0"),  # revision 从 1 开始
            ("protocol", ""),
            ("state", "working"),  # 封存 release.yaml 恒为 sealed
            ("purpose", "staging"),
            ("training_allowed", 1),  # 必须布尔
            ("training_allowed", "true"),
            ("description", ""),
            ("sample_count", -1),
            ("sample_count", "1678"),
            ("source_batches", []),
            ("source_batches", "batch-2026-07"),  # 必须是序列
            ("splits", {}),
            ("splits", {"fold0": {"train": 1}}),  # 缺 validation
            ("splits", {"fold0": {"train": "1", "validation": 2}}),
            ("status", "archived"),
        ],
    )
    def test_invalid_field_value_rejected(self, field: str, value: object) -> None:
        with pytest.raises(ReleaseSchemaError):
            parse_release_metadata(_valid_release_dict(**{field: value}))

    def test_holdout_with_training_allowed_true_rejected(self) -> None:
        with pytest.raises(ReleaseSchemaError):
            parse_release_metadata(
                _valid_release_dict(purpose="holdout", training_allowed=True)
            )

    def test_holdout_with_training_allowed_false_accepted(self) -> None:
        meta = parse_release_metadata(
            _valid_release_dict(purpose="holdout", training_allowed=False)
        )
        assert meta.purpose == "holdout"
        assert meta.training_allowed is False

    def test_replacement_requires_superseded_status(self) -> None:
        with pytest.raises(ReleaseSchemaError):
            parse_release_metadata(
                _valid_release_dict(status="active", replacement="data-v4.1-r2")
            )
        meta = parse_release_metadata(
            _valid_release_dict(status="superseded", replacement="data-v4.1-r2")
        )
        assert meta.status is DataStatus.SUPERSEDED
        assert meta.replacement == "data-v4.1-r2"

    def test_replacement_must_be_other_valid_data_id(self) -> None:
        with pytest.raises(ReleaseSchemaError):
            parse_release_metadata(
                _valid_release_dict(status="superseded", replacement="junk")
            )
        with pytest.raises(ReleaseSchemaError):
            parse_release_metadata(
                _valid_release_dict(
                    status="superseded", replacement="data-v4.1-r1"  # 自替代
                )
            )

    def test_load_rejects_version_mismatch_with_directory(self, root: Path) -> None:
        version, release_dir = _seal_development(root)
        yaml_path = release_dir / "release.yaml"
        text = yaml_path.read_text(encoding="utf-8")
        yaml_path.write_text(
            text.replace(f"version: {version}", "version: data-v4.1-r99"),
            encoding="utf-8",
        )
        with pytest.raises(ReleaseSchemaError):
            load_release_metadata(root, version)

    def test_load_rejects_invalid_status_on_disk(self, root: Path) -> None:
        version, release_dir = _seal_development(root)
        yaml_path = release_dir / "release.yaml"
        text = yaml_path.read_text(encoding="utf-8")
        yaml_path.write_text(
            text.replace("status: active", "status: retired"), encoding="utf-8"
        )
        with pytest.raises(ReleaseSchemaError):
            load_release_metadata(root, version)

    def test_load_unsealed_version_rejected(self, root: Path) -> None:
        _make_working(root, "round-001")
        version = stage_release(root, "round-001", "v4.1")
        with pytest.raises(ReleaseNotFound):
            load_release_metadata(root, version)


class TestControlledStatusUpdate:
    IDENTITY_FIELDS = (
        "version",
        "protocol",
        "state",
        "purpose",
        "training_allowed",
        "description",
        "sample_count",
    )

    def test_active_to_superseded_with_replacement(self, root: Path) -> None:
        version, _ = _seal_development(root)
        before = load_release_metadata(root, version)

        meta = update_release_status(
            root, version, "superseded", replacement="data-v4.1-r2"
        )
        assert meta.status is DataStatus.SUPERSEDED
        assert meta.replacement == "data-v4.1-r2"

        reloaded = load_release_metadata(root, version)
        assert reloaded.status is DataStatus.SUPERSEDED
        assert reloaded.replacement == "data-v4.1-r2"
        # 身份字段逐值不变：仅 status / replacement 允许受控变化
        for field in self.IDENTITY_FIELDS:
            assert getattr(reloaded, field) == getattr(before, field), field
        assert tuple(reloaded.source_batches) == tuple(before.source_batches)
        assert reloaded.splits == before.splits

    def test_active_to_invalid_allowed(self, root: Path) -> None:
        version, _ = _seal_development(root)
        meta = update_release_status(root, version, DataStatus.INVALID)
        assert meta.status is DataStatus.INVALID
        assert load_release_metadata(root, version).status is DataStatus.INVALID

    def test_superseded_to_active_rejected(self, root: Path) -> None:
        version, _ = _seal_development(root)
        update_release_status(root, version, "superseded")
        with pytest.raises(IllegalTransition):
            update_release_status(root, version, "active")
        assert (
            load_release_metadata(root, version).status is DataStatus.SUPERSEDED
        )

    def test_invalid_is_terminal(self, root: Path) -> None:
        version, _ = _seal_development(root)
        update_release_status(root, version, "invalid")
        with pytest.raises(IllegalTransition):
            update_release_status(root, version, "active")
        with pytest.raises(IllegalTransition):
            update_release_status(root, version, "superseded")
        assert load_release_metadata(root, version).status is DataStatus.INVALID

    def test_same_status_idempotent(self, root: Path) -> None:
        version, _ = _seal_development(root)
        meta = update_release_status(root, version, "active")
        assert meta.status is DataStatus.ACTIVE
        assert meta.replacement is None

    def test_replacement_only_allowed_when_superseded(self, root: Path) -> None:
        version, _ = _seal_development(root)
        with pytest.raises(ReleaseSchemaError):
            update_release_status(root, version, "active", replacement="data-v4.1-r2")
        with pytest.raises(ReleaseSchemaError):
            update_release_status(root, version, "invalid", replacement="data-v4.1-r2")

    def test_replacement_must_be_valid_other_data_id(self, root: Path) -> None:
        version, _ = _seal_development(root)
        with pytest.raises(ReleaseSchemaError):
            update_release_status(root, version, "superseded", replacement="junk")
        with pytest.raises(ReleaseSchemaError):
            update_release_status(root, version, "superseded", replacement=version)
        assert load_release_metadata(root, version).status is DataStatus.ACTIVE

    def test_invalid_status_value_rejected(self, root: Path) -> None:
        version, _ = _seal_development(root)
        with pytest.raises(ReleaseSchemaError):
            update_release_status(root, version, "archived")

    def test_unsealed_or_unknown_version_rejected(self, root: Path) -> None:
        _make_working(root, "round-001")
        staged = stage_release(root, "round-001", "v4.1")
        with pytest.raises(ReleaseNotFound):
            update_release_status(root, staged, "invalid")
        with pytest.raises(ReleaseNotFound):
            update_release_status(root, "data-v4.1-r99", "invalid")


class TestSealedImmutability:
    def test_payload_file_not_writable(self, root: Path) -> None:
        _, release_dir = _seal_development(root)
        payload = release_dir / "datasets" / "labels.jsonl"
        with pytest.raises(PermissionError):
            payload.write_text("tampered\n", encoding="utf-8")

    def test_payload_file_not_deletable(self, root: Path) -> None:
        _, release_dir = _seal_development(root)
        with pytest.raises(PermissionError):
            (release_dir / "datasets" / "labels.jsonl").unlink()

    def test_no_new_entries_in_payload_dirs(self, root: Path) -> None:
        _, release_dir = _seal_development(root)
        with pytest.raises(PermissionError):
            (release_dir / "datasets" / "evil.jsonl").write_text(
                "x", encoding="utf-8"
            )

    def test_no_new_entries_at_release_root(self, root: Path) -> None:
        _, release_dir = _seal_development(root)
        with pytest.raises(PermissionError):
            (release_dir / "evil.txt").write_text("x", encoding="utf-8")

    def test_release_yaml_remains_controllably_writable(self, root: Path) -> None:
        version, _ = _seal_development(root)
        # 受控更新通道仍可用（Git 留痕的 status 修改）
        update_release_status(root, version, "invalid")
        assert load_release_metadata(root, version).status is DataStatus.INVALID

    def test_assert_payload_sealed_passes_after_seal(self, root: Path) -> None:
        _, release_dir = _seal_development(root)
        assert_payload_sealed(release_dir)

    def test_assert_payload_sealed_detects_writable_payload_file(
        self, root: Path
    ) -> None:
        _, release_dir = _seal_development(root)
        os.chmod(release_dir / "datasets" / "labels.jsonl", 0o644)
        with pytest.raises(ImmutableReleaseError):
            assert_payload_sealed(release_dir)

    def test_assert_payload_sealed_detects_writable_payload_dir(
        self, root: Path
    ) -> None:
        _, release_dir = _seal_development(root)
        os.chmod(release_dir / "datasets", 0o755)
        with pytest.raises(ImmutableReleaseError):
            assert_payload_sealed(release_dir)

    def test_assert_payload_sealed_detects_writable_release_root(
        self, root: Path
    ) -> None:
        # P2-1 回归：release 根目录自身的写位也必须纳入检查，
        # 否则攻击者可在根下新增 payload 条目而不被检出。
        _, release_dir = _seal_development(root)
        os.chmod(release_dir, release_dir.stat().st_mode | 0o200)
        with pytest.raises(ImmutableReleaseError):
            assert_payload_sealed(release_dir)


class TestTrainingReferenceGate:
    def test_active_development_release_accepted(self, root: Path) -> None:
        version, _ = _seal_development(root)
        validate_training_reference(root, version)

    def test_superseded_release_rejected(self, root: Path) -> None:
        version, _ = _seal_development(root)
        update_release_status(root, version, "superseded")
        with pytest.raises(ReferenceNotAllowed):
            validate_training_reference(root, version)

    def test_invalid_release_rejected(self, root: Path) -> None:
        version, _ = _seal_development(root)
        update_release_status(root, version, "invalid")
        with pytest.raises(ReferenceNotAllowed):
            validate_training_reference(root, version)

    def test_unknown_version_rejected(self, root: Path) -> None:
        with pytest.raises(ReferenceNotAllowed):
            validate_training_reference(root, "data-v4.1-r99")

    def test_unsealed_staging_rejected(self, root: Path) -> None:
        _make_working(root, "round-001")
        version = stage_release(root, "round-001", "v4.1")
        with pytest.raises(ReferenceNotAllowed):
            validate_training_reference(root, version)
