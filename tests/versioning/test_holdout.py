"""B3 — holdout 安全：training_allowed 强制、真值隔离结构、预注册与一次性 claim。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
§5.1（purpose: holdout 与目录隔离）、§5.6（holdout 正式测评授权与一次性 claim）、
§8（claim.yaml 创建后只读、不自动复用/覆盖）、§10（holdout 不得被训练引用）。

预期 production API（供 viber 对照实现，模块 ``versioning.holdout``）::

    PRE_REGISTRATION_REQUIRED_FIELDS: tuple[str, ...]
        # 恰好为 ("eval_version", "model_version", "data_version", "split",
        #          "rules", "thresholds", "one_time", "tuning_use", "recovery")

    class HoldoutError(ValueError)            # holdout 域异常基类
    class HoldoutStructureError(HoldoutError) # 目录契约 / 权限隔离校验失败
    class PreRegistrationError(HoldoutError)  # pre_registration.yaml 结构校验失败
    class ClaimError(HoldoutError)            # claim 域异常基类（含解析失败 fail-closed）
    class ClaimNotFound(ClaimError)           # 引用的 claim 不存在
    class ClaimExistsError(ClaimError)        # claim.yaml 已存在，拒绝重写/覆盖
    class ClaimConflictError(ClaimError)      # 四元组 / 执行身份 / 所属 data 版本不一致
    class ClaimConsumedError(ClaimError)      # claim 已消费，不得再当可用授权 / 重复消费

    @dataclass(frozen=True)
    class ClaimIdentity
        # eval_version: str   完整 eval ID
        # model_version: str  完整 model ID
        # data_version: str   完整 data ID（holdout 版本）
        # split: str          非空字符串
        # 本 dataclass 不做校验；合法性在 create/acquire/mark 时校验，
        # 任一组件非法 -> ClaimError。

    @dataclass(frozen=True)
    class HoldoutClaim
        # identity: ClaimIdentity
        # executor: str       一次执行身份（不透明字符串）

    @dataclass(frozen=True)
    class PreRegistration
        # eval_version / model_version / data_version / split: str
        # rules / thresholds / recovery: 原值（存在性校验，类型不限）
        # one_time: bool      必须为 True
        # tuning_use: str     必须为 "forbidden"

    def validate_holdout_layout(release_dir: Path) -> None
        # 目录契约：media/ evaluation_inputs/ sealed_ground_truth/ authorization/
        #   四个子目录必须存在（缺任一 -> HoldoutStructureError）；
        # sealed_ground_truth/ 权限位不得含任何 group/other 位（如 0o750/0o705 拒绝）；
        # media/ 与 evaluation_inputs/ 内不得出现名为 sealed_ground_truth 的条目
        #   （真值不得混入常规 payload）。

    def parse_pre_registration(mapping: Mapping) -> PreRegistration
        # 缺必填字段 / eval/model/data 非对应类别完整 ID / split 空或非字符串 /
        # one_time 非 True / tuning_use != "forbidden" -> PreRegistrationError。
    def load_pre_registration(path: Path) -> PreRegistration
        # 文件不存在或内容非法 -> PreRegistrationError（fail-closed）。

    def create_claim(authorization_dir: Path, identity: ClaimIdentity,
                     executor: str) -> Path
        # 在 authorization/ 中原子创建 claim.yaml（O_EXCL 语义）：
        # 已存在（无论内容是否可解析）-> ClaimExistsError，绝不重写；
        # identity.data_version 必须等于 authorization_dir 父目录名，
        #   不一致 -> ClaimConflictError；
        # identity 组件非法 -> ClaimError；
        # 创建成功后 claim.yaml 对所有用户去写权限（只读）。

    def acquire_claim(authorization_dir: Path, identity: ClaimIdentity,
                      executor: str) -> HoldoutClaim
        # 首次模型调用前的全局一次性授权入口：
        # claim.yaml 不存在 -> 等价 create_claim 后返回新 claim；
        # 已存在：内容不可解析 -> ClaimError（fail-closed，不得当作可恢复）；
        #   四元组或 executor 任一不同 -> ClaimConflictError，原文件不动、
        #   不创建第二个 claim；
        #   全部一致但已有 consumed.yaml -> ClaimConsumedError
        #   （已消费 claim 不得再当可用授权）；
        #   全部一致且未消费 -> 返回既有 claim（同身份恢复，不改写文件）。

    def load_claim(authorization_dir: Path) -> HoldoutClaim
        # claim.yaml 不存在 -> ClaimNotFound；内容非法 -> ClaimError。

    def mark_claim_consumed(authorization_dir: Path, identity: ClaimIdentity,
                            executor: str) -> Path
        # 正式 eval 完成后登记一次性消费状态（authorization/consumed.yaml，
        # 不修改 claim.yaml 本体）：
        # claim.yaml 不存在 -> ClaimNotFound；
        # 四元组 / executor 不一致 -> ClaimConflictError；
        # consumed.yaml 已存在 -> ClaimConsumedError（重复消费拒绝）；
        # 成功 -> 返回 marker 文件路径。

当前 ``versioning.holdout`` 尚不存在，本文件全部用例应为 RED（ModuleNotFoundError）。
所有用例只在 pytest ``tmp_path`` 下构造目录，不触碰 workspace/ 真实数据与真实真值。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from versioning.data_release import (
    ReleaseSchemaError,
    load_release_metadata,
    seal_release,
    stage_release,
    validate_training_reference,
)
from versioning.holdout import (
    PRE_REGISTRATION_REQUIRED_FIELDS,
    ClaimConflictError,
    ClaimConsumedError,
    ClaimError,
    ClaimExistsError,
    ClaimIdentity,
    ClaimNotFound,
    HoldoutStructureError,
    PreRegistrationError,
    acquire_claim,
    create_claim,
    load_claim,
    load_pre_registration,
    mark_claim_consumed,
    parse_pre_registration,
    validate_holdout_layout,
)
from versioning.state import ReferenceNotAllowed

PRE_REGISTRATION_FIELDS = frozenset(
    {
        "eval_version",
        "model_version",
        "data_version",
        "split",
        "rules",
        "thresholds",
        "one_time",
        "tuning_use",
        "recovery",
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
    (working / "media").mkdir(parents=True)
    (working / "media" / "clip.mp4").write_bytes(b"\x00\x01")
    return working


def _seal_kwargs(**overrides: object) -> dict:
    kwargs: dict = {
        "purpose": "development",
        "description": "holdout 独立验收数据",
        "sample_count": 2,
        "source_batches": ["batch-2026-07"],
        "splits": {"test": {"train": 0, "validation": 2}},
    }
    kwargs.update(overrides)
    return kwargs


def _seal_holdout(root: Path, working_name: str = "round-holdout") -> tuple[str, Path]:
    # 显式版本纪律（§9/§11.6）：stage_release 不再自动分配，核对后显式指定 r1
    _make_working(root, working_name)
    version = stage_release(root, working_name, "v4.1", version="data-v4.1-r1")
    release_dir = seal_release(root, version, **_seal_kwargs(purpose="holdout"))
    return version, release_dir


def _make_layout(base: Path, *, ground_truth_mode: int = 0o700) -> Path:
    release_dir = base / "data-v4.1-r9"
    for name in ("media", "evaluation_inputs", "authorization"):
        (release_dir / name).mkdir(parents=True)
    ground_truth = release_dir / "sealed_ground_truth"
    ground_truth.mkdir()
    ground_truth.chmod(ground_truth_mode)
    return release_dir


def _make_authorization_dir(base: Path, data_version: str = "data-v4.1-r9") -> Path:
    authorization = base / data_version / "authorization"
    authorization.mkdir(parents=True)
    return authorization


def _identity(data_version: str = "data-v4.1-r9") -> ClaimIdentity:
    return ClaimIdentity(
        eval_version="eval-v4.1-r1",
        model_version="model-v4.1-r2",
        data_version=data_version,
        split="test",
    )


def _valid_pre_registration_dict(**overrides: object) -> dict:
    data: dict = {
        "eval_version": "eval-v4.1-r1",
        "model_version": "model-v4.1-r2",
        "data_version": "data-v4.1-r9",
        "split": "test",
        "rules": "docs/eval-rules.md 冻结文本",
        "thresholds": {"accuracy": 0.9},
        "one_time": True,
        "tuning_use": "forbidden",
        "recovery": {"resume_requires": ["identity", "executor"]},
    }
    data.update(overrides)
    return data


class TestHoldoutTrainingGate:
    def test_seal_holdout_defaults_training_disallowed(self, root: Path) -> None:
        version, _ = _seal_holdout(root)
        meta = load_release_metadata(root, version)
        assert meta.purpose == "holdout"
        assert meta.training_allowed is False

    def test_seal_holdout_with_training_allowed_true_rejected(
        self, root: Path
    ) -> None:
        _make_working(root, "round-holdout")
        # 显式版本纪律（§9/§11.6）：显式指定目标版本 r1
        version = stage_release(root, "round-holdout", "v4.1", version="data-v4.1-r1")
        with pytest.raises(ReleaseSchemaError):
            seal_release(
                root,
                version,
                **_seal_kwargs(purpose="holdout", training_allowed=True),
            )

    def test_training_reference_gate_rejects_active_holdout(self, root: Path) -> None:
        version, _ = _seal_holdout(root)
        # holdout 即使 status 为 active 也不得被训练引用（fail-closed）
        with pytest.raises(ReferenceNotAllowed):
            validate_training_reference(root, version)

    def test_seal_holdout_produces_isolated_layout(self, root: Path) -> None:
        _, release_dir = _seal_holdout(root)
        validate_holdout_layout(release_dir)
        # 常规 payload 已封存只读
        with pytest.raises(PermissionError):
            (release_dir / "media" / "clip.mp4").write_bytes(b"\x02")

    def test_authorization_dir_writable_for_one_time_claim(self, root: Path) -> None:
        version, release_dir = _seal_holdout(root)
        # 封存后 authorization/ 仍允许一次性原子创建 claim
        claim = acquire_claim(
            release_dir / "authorization", _identity(version), "runner-A"
        )
        assert claim.executor == "runner-A"
        assert claim.identity.data_version == version


class TestHoldoutLayout:
    def test_valid_layout_accepted(self, tmp_path: Path) -> None:
        release_dir = _make_layout(tmp_path)
        validate_holdout_layout(release_dir)

    @pytest.mark.parametrize(
        "missing",
        ["media", "evaluation_inputs", "sealed_ground_truth", "authorization"],
    )
    def test_missing_required_dir_rejected(
        self, tmp_path: Path, missing: str
    ) -> None:
        release_dir = _make_layout(tmp_path)
        shutil.rmtree(release_dir / missing)
        with pytest.raises(HoldoutStructureError):
            validate_holdout_layout(release_dir)

    @pytest.mark.parametrize("mode", [0o755, 0o750, 0o705, 0o077])
    def test_ground_truth_accessible_beyond_owner_rejected(
        self, tmp_path: Path, mode: int
    ) -> None:
        release_dir = _make_layout(tmp_path, ground_truth_mode=0o700)
        os.chmod(release_dir / "sealed_ground_truth", mode)
        with pytest.raises(HoldoutStructureError):
            validate_holdout_layout(release_dir)

    def test_ground_truth_must_not_leak_into_regular_payload(
        self, tmp_path: Path
    ) -> None:
        release_dir = _make_layout(tmp_path)
        (release_dir / "media" / "sealed_ground_truth").mkdir()
        with pytest.raises(HoldoutStructureError):
            validate_holdout_layout(release_dir)

    @pytest.mark.parametrize("leak_dir", ["media", "evaluation_inputs"])
    def test_nested_ground_truth_leak_rejected(
        self, tmp_path: Path, leak_dir: str
    ) -> None:
        # P3-1 回归：真值泄漏检测必须递归，任意嵌套层级下出现名为
        # sealed_ground_truth 的条目均拒绝，而非仅检查第一层。
        release_dir = _make_layout(tmp_path)
        nested = release_dir / leak_dir / "subdir" / "sealed_ground_truth"
        nested.mkdir(parents=True)
        (nested / "answers.jsonl").write_text("{}", encoding="utf-8")
        with pytest.raises(HoldoutStructureError):
            validate_holdout_layout(release_dir)


class TestPreRegistration:
    def test_required_fields_constant(self) -> None:
        assert set(PRE_REGISTRATION_REQUIRED_FIELDS) == PRE_REGISTRATION_FIELDS

    def test_valid_pre_registration_accepted(self) -> None:
        pre = parse_pre_registration(_valid_pre_registration_dict())
        assert pre.eval_version == "eval-v4.1-r1"
        assert pre.model_version == "model-v4.1-r2"
        assert pre.data_version == "data-v4.1-r9"
        assert pre.split == "test"
        assert pre.one_time is True
        assert pre.tuning_use == "forbidden"

    @pytest.mark.parametrize("field", sorted(PRE_REGISTRATION_FIELDS))
    def test_missing_required_field_rejected(self, field: str) -> None:
        data = _valid_pre_registration_dict()
        del data[field]
        with pytest.raises(PreRegistrationError):
            parse_pre_registration(data)

    def test_one_time_must_be_true(self) -> None:
        with pytest.raises(PreRegistrationError):
            parse_pre_registration(_valid_pre_registration_dict(one_time=False))

    def test_tuning_use_must_be_forbidden(self) -> None:
        with pytest.raises(PreRegistrationError):
            parse_pre_registration(_valid_pre_registration_dict(tuning_use="allowed"))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("eval_version", "eval-latest"),
            ("eval_version", "data-v4.1-r9"),  # 类别不符
            ("model_version", "m"),
            ("model_version", "eval-v4.1-r1"),
            ("data_version", "data-v4.1"),  # 缺 revision
        ],
    )
    def test_version_fields_must_be_full_readable_ids(
        self, field: str, value: str
    ) -> None:
        with pytest.raises(PreRegistrationError):
            parse_pre_registration(_valid_pre_registration_dict(**{field: value}))

    def test_split_must_be_non_empty_string(self) -> None:
        with pytest.raises(PreRegistrationError):
            parse_pre_registration(_valid_pre_registration_dict(split=""))
        with pytest.raises(PreRegistrationError):
            parse_pre_registration(_valid_pre_registration_dict(split=3))

    def test_load_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "pre_registration.yaml"
        path.write_text(
            yaml.safe_dump(_valid_pre_registration_dict()), encoding="utf-8"
        )
        pre = load_pre_registration(path)
        assert pre.eval_version == "eval-v4.1-r1"

    def test_load_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PreRegistrationError):
            load_pre_registration(tmp_path / "pre_registration.yaml")


class TestOneTimeClaim:
    def test_create_claim_succeeds_and_file_is_readonly(
        self, tmp_path: Path
    ) -> None:
        authorization = _make_authorization_dir(tmp_path)
        identity = _identity()

        claim = acquire_claim(authorization, identity, "runner-A")
        assert claim.identity == identity
        assert claim.executor == "runner-A"

        claim_path = authorization / "claim.yaml"
        assert claim_path.is_file()
        assert claim_path.stat().st_mode & 0o222 == 0
        with pytest.raises(PermissionError):
            claim_path.write_text("tampered", encoding="utf-8")

    def test_resume_with_same_identity_and_executor_allowed(
        self, tmp_path: Path
    ) -> None:
        authorization = _make_authorization_dir(tmp_path)
        acquire_claim(authorization, _identity(), "runner-A")
        before = (authorization / "claim.yaml").read_bytes()

        claim = acquire_claim(authorization, _identity(), "runner-A")
        assert claim.identity == _identity()
        assert claim.executor == "runner-A"
        # 同身份恢复是读取，不改写 claim 文件
        assert (authorization / "claim.yaml").read_bytes() == before

    def test_resume_with_different_executor_rejected(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        acquire_claim(authorization, _identity(), "runner-A")
        before = (authorization / "claim.yaml").read_bytes()

        with pytest.raises(ClaimConflictError):
            acquire_claim(authorization, _identity(), "runner-B")
        assert (authorization / "claim.yaml").read_bytes() == before

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("eval_version", "eval-v4.1-r2"),
            ("model_version", "model-v4.1-r3"),
            ("split", "validation"),
        ],
    )
    def test_resume_with_different_quadruple_rejected(
        self, tmp_path: Path, field: str, value: str
    ) -> None:
        authorization = _make_authorization_dir(tmp_path)
        acquire_claim(authorization, _identity(), "runner-A")
        before = (authorization / "claim.yaml").read_bytes()

        other = replace(_identity(), **{field: value})
        with pytest.raises(ClaimConflictError):
            acquire_claim(authorization, other, "runner-A")
        # 原 claim 未被覆盖，且未创建第二个授权文件
        assert (authorization / "claim.yaml").read_bytes() == before
        assert sorted(p.name for p in authorization.iterdir()) == ["claim.yaml"]

    def test_claim_data_version_must_match_enclosing_release(
        self, tmp_path: Path
    ) -> None:
        authorization = _make_authorization_dir(tmp_path, "data-v4.1-r9")
        with pytest.raises(ClaimConflictError):
            acquire_claim(authorization, _identity("data-v4.1-r8"), "runner-A")
        assert not (authorization / "claim.yaml").exists()

    def test_strict_create_refuses_overwrite(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        create_claim(authorization, _identity(), "runner-A")
        before = (authorization / "claim.yaml").read_bytes()

        with pytest.raises(ClaimExistsError):
            create_claim(authorization, _identity(), "runner-A")
        assert (authorization / "claim.yaml").read_bytes() == before

    @pytest.mark.parametrize("executor", ["", 123, None])
    def test_direct_create_claim_rejects_invalid_executor_without_side_effect(
        self, tmp_path: Path, executor: object
    ) -> None:
        # B3 复审回归：直调 create_claim（绕过 acquire_claim 入口校验）时
        # 同样必须校验 executor；非法 executor -> ClaimError，
        # 且 authorization/ 下不得落盘 claim.yaml / consumed.yaml 任何文件。
        authorization = _make_authorization_dir(tmp_path)
        with pytest.raises(ClaimError):
            create_claim(authorization, _identity(), executor)  # type: ignore[arg-type]
        assert not (authorization / "claim.yaml").exists()
        assert not (authorization / "consumed.yaml").exists()
        assert sorted(p.name for p in authorization.iterdir()) == []

        # 合法直调仍正常落盘
        claim_path = create_claim(authorization, _identity(), "runner-A")
        assert claim_path.is_file()

    def test_malformed_identity_rejected(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        bad = ClaimIdentity(
            eval_version="junk",
            model_version="model-v4.1-r2",
            data_version="data-v4.1-r9",
            split="test",
        )
        with pytest.raises(ClaimError):
            acquire_claim(authorization, bad, "runner-A")
        assert not (authorization / "claim.yaml").exists()

    def test_load_claim_missing_rejected(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        with pytest.raises(ClaimNotFound):
            load_claim(authorization)

    def test_consumed_claim_no_longer_usable(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        acquire_claim(authorization, _identity(), "runner-A")
        claim_before = (authorization / "claim.yaml").read_bytes()

        marker = mark_claim_consumed(authorization, _identity(), "runner-A")
        assert marker.name == "consumed.yaml"
        assert marker.is_file()
        # 消费登记不修改 claim 本体
        assert (authorization / "claim.yaml").read_bytes() == claim_before

        with pytest.raises(ClaimConsumedError):
            acquire_claim(authorization, _identity(), "runner-A")

    def test_double_consume_rejected(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        acquire_claim(authorization, _identity(), "runner-A")
        mark_claim_consumed(authorization, _identity(), "runner-A")
        with pytest.raises(ClaimConsumedError):
            mark_claim_consumed(authorization, _identity(), "runner-A")

    def test_consume_with_mismatched_identity_rejected(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        acquire_claim(authorization, _identity(), "runner-A")

        with pytest.raises(ClaimConflictError):
            mark_claim_consumed(
                authorization, replace(_identity(), split="validation"), "runner-A"
            )
        with pytest.raises(ClaimConflictError):
            mark_claim_consumed(authorization, _identity(), "runner-B")
        assert not (authorization / "consumed.yaml").exists()

    def test_consume_without_claim_rejected(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        with pytest.raises(ClaimNotFound):
            mark_claim_consumed(authorization, _identity(), "runner-A")

    def test_corrupted_claim_is_fail_closed(self, tmp_path: Path) -> None:
        authorization = _make_authorization_dir(tmp_path)
        (authorization / "claim.yaml").write_text(
            "%%% not a claim %%%", encoding="utf-8"
        )

        with pytest.raises(ClaimError):
            acquire_claim(authorization, _identity(), "runner-A")
        # 已存在即拒绝重写，即使内容不可解析
        with pytest.raises(ClaimExistsError):
            create_claim(authorization, _identity(), "runner-A")
        assert (authorization / "claim.yaml").read_text(
            encoding="utf-8"
        ) == "%%% not a claim %%%"

    def test_on_disk_claim_with_invalid_identity_rejected_everywhere(
        self, tmp_path: Path
    ) -> None:
        # P2-3 回归：手工落盘的 identity 非法 claim.yaml（eval_version="junk"）
        # 在 load / acquire / mark 三条路径均 fail-closed，不得被静默采信。
        authorization = _make_authorization_dir(tmp_path)
        bad_claim = {
            "identity": {
                "eval_version": "junk",
                "model_version": "model-v4.1-r2",
                "data_version": "data-v4.1-r9",
                "split": "test",
            },
            "executor": "runner-A",
        }
        (authorization / "claim.yaml").write_text(
            yaml.safe_dump(bad_claim), encoding="utf-8"
        )

        with pytest.raises(ClaimError):
            load_claim(authorization)
        with pytest.raises(ClaimError):
            acquire_claim(authorization, _identity(), "runner-A")
        with pytest.raises(ClaimError):
            mark_claim_consumed(authorization, _identity(), "runner-A")
        # 拒绝路径不得产生消费标记
        assert not (authorization / "consumed.yaml").exists()

    @pytest.mark.parametrize("executor", [123, None, ""])
    def test_non_string_or_empty_executor_rejected(
        self, tmp_path: Path, executor: object
    ) -> None:
        # P2-3 回归：executor 必须是非空字符串；acquire 与 mark 入口一致拒绝。
        authorization = _make_authorization_dir(tmp_path)
        with pytest.raises(ClaimError):
            acquire_claim(authorization, _identity(), executor)  # type: ignore[arg-type]
        # 拒绝发生在创建前，不得留下 claim.yaml
        assert not (authorization / "claim.yaml").exists()

        acquire_claim(authorization, _identity(), "runner-A")
        with pytest.raises(ClaimError):
            mark_claim_consumed(authorization, _identity(), executor)  # type: ignore[arg-type]
        assert not (authorization / "consumed.yaml").exists()
