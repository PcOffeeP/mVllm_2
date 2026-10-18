"""Prompt 副本一致性门：Git 跟踪 checkout 副本 vs store 正式副本。

背景：正式 Prompt 的单一正式位置是 ``<store根>/records/prompts/<version>.yaml``，
但在本机开发流程里同一份 ``records/prompts/<version>.yaml`` 也由 Git 跟踪。
两侧字节一旦分叉，训练冻结副本与评测 Prompt 就会来自不同事实：冻结与取
Prompt 都必须先确认两侧逐字节一致，不一致就拒绝，而不是自行猜测哪一侧权威。

预期 production API（供 coder 对照实现，模块 ``versioning.prompts``）::

    class PromptCheckoutDrift(PromptError)
        # 比对出口：store 副本与 checkout 副本字节不一致，或 checkout 副本
        # 无法定位/缺失。消息须含两侧绝对路径、两侧完整 sha256 hex、两侧
        # 字节数，以及一句可操作提示（确认哪一侧权威 / 如何更新 / 可用
        # --prompt-checkout-root 显式指定 checkout 根）。

    def verify_prompt_checkout_copy(
        root: Path, version: str, *, checkout_root: Path | None = None
    ) -> None
        # 比对 <store根>/records/prompts/<version>.yaml 与
        # <checkout根>/records/prompts/<version>.yaml 的 sha256 与字节长度；
        # 一致返回 None；不一致抛 PromptCheckoutDrift。
        # checkout_root=None 时由 store 根推导：root.parent 下
        # records/prompts/<version>.yaml 存在即视为 checkout 根；
        # 推导不出或该文件缺失 -> PromptCheckoutDrift（消息含
        # --prompt-checkout-root 提示）；store 侧文件缺失 -> PromptNotFound。

    prepare_versioned_run(..., prompt_checkout_root: Path | None = None)
    _formal_input(..., prompt_checkout_root: Path | None = None)
    prepare_versioned_evaluation(..., prompt_checkout_root=None)  # 透传给 _formal_input

    入口语义：在冻结 Prompt / 取 Prompt 之前执行上述校验；不一致时抛
    PromptCheckoutDrift 且不产生任何冻结或评测产物。CLI 侧
    ``train prepare`` 增 ``--prompt-checkout-root`` 并原样透传。

本文件覆盖该门及其各入口接入的回归用例：生产代码已实现，用例应全绿。断言口径说明：

- 错误消息只钉死「必须包含」的确定性证据（两侧绝对路径、两侧完整 sha256、
  两侧字节数、``--prompt-checkout-root`` 这一提示开关），不钉死自由措辞；
- 路径断言容忍 macOS ``/var`` 与 ``/private/var`` 软链两种等价文本形式；
- 字节数以「该数值作为独立数字片段出现」判定，模板自由（``1234 字节`` /
  ``size=1234`` 均可）；
- 已知未覆盖：``version`` 非法（InvalidIdentifier）分支、评测入口在
  registry/checkpoint 之前还是之后校验的顺序（训练模型的 prompt_version
  取自 registry 记录，二者顺序需 coder 明确后另行钉死）。
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest
import yaml

# tests/ 下的共享夹具模块（test_train_with_contract、test_eval_run）按仓库既有
# 方式跨文件复用；显式把 tests/ 加入 sys.path，避免依赖 pytest 的收集顺序。
_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

STORE_PROMPT_VERSION = "prompt-v4.1-r1"
TRAIN_VERSION = "train-v4.1-r1"
DATA_VERSION = "data-v4.1-r2"
EVAL_VERSION = "eval-v4.1-r1"

# 显式控制 Prompt 正文，使两侧字节数与 sha256 都是可区分的可辨识值。
PROMPT_DEFINITION = {
    "system_prompt": "冻结系统提示词完整正文，用于 checkout 一致性校验",
    "user_prompt": "冻结用户提示词完整正文，用于 checkout 一致性校验",
    "output_fields": [
        "clip_state",
        "fracture_mechanism",
        "fracture_site",
        "special_case",
    ],
}


# --------------------------------------------------------------------------- #
# 夹具与断言辅助
# --------------------------------------------------------------------------- #


def _store_fixture(tmp_path: Path):
    """构造 store 根/媒体根，并注册 store 侧正式 Prompt 副本。"""
    from test_train_with_contract import _versioned_data_fixture

    return _versioned_data_fixture(
        tmp_path, prompt_definition=dict(PROMPT_DEFINITION)
    )


def _store_copy(root: Path) -> Path:
    from versioning.prompts import prompt_path

    return prompt_path(root, STORE_PROMPT_VERSION)


def _checkout_copy(checkout_root: Path) -> Path:
    from versioning.prompts import prompt_path

    return prompt_path(checkout_root, STORE_PROMPT_VERSION)


def _write_checkout(
    checkout_root: Path, store_copy: Path, *, content: bytes | None = None
) -> Path:
    """在 checkout 根写入 records/prompts 副本；content 为 None 时与 store 一致。"""
    path = _checkout_copy(checkout_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(store_copy.read_bytes() if content is None else content)
    return path


def _drifted_bytes(path: Path) -> bytes:
    """返回仍为合法 YAML、但与 path 当前字节不同的内容。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["user_prompt"] = f"{data['user_prompt']}（checkout 侧已被本地编辑）"
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8")


def _scratch_checkout_bytes(tmp_path: Path) -> bytes:
    """用真实 create_prompt 序列化出与夹具 store 副本逐字节相同的副本内容。

    评测夹具内部会自行注册 store 副本，因此需要在它之前先准备好一份内容一致的
    checkout 副本；直接复用 create_prompt（同一实现、同一输入）保证字节一致，
    不在测试里复刻序列化格式。
    """
    from versioning.prompts import create_prompt, prompt_path

    scratch = tmp_path / "_scratch-prompt"
    create_prompt(
        scratch, "v4.1", version=STORE_PROMPT_VERSION, **PROMPT_DEFINITION
    )
    return prompt_path(scratch, STORE_PROMPT_VERSION).read_bytes()


def _fold_configs(tmp_path: Path) -> dict:
    model = tmp_path / "model"
    model.mkdir(parents=True, exist_ok=True)
    (model / "model.safetensors").write_bytes(b"synthetic base")
    return {
        f"fold{i}": {"seed": 3411 + i, "model_name_or_path": str(model)}
        for i in range(3)
    }


def _prepare(root: Path, media: Path, configs: dict, **kwargs):
    from finetune.train_prepare_run import prepare_versioned_run

    return prepare_versioned_run(
        root=root,
        train_version=TRAIN_VERSION,
        data_version=DATA_VERSION,
        prompt_version=STORE_PROMPT_VERSION,
        media_root=media,
        fold_configs=configs,
        git_commit="fixture",
        environment={"python": "fixture"},
        **kwargs,
    )


def _path_forms(path: Path) -> tuple[str, ...]:
    """同一路径的可接受文本形式（macOS /var 与 /private/var 互为软链）。"""
    return tuple({str(path), str(path.absolute()), str(path.resolve())})


def _assert_message_reports(message: str, *paths: Path) -> None:
    """断言消息同时给出每个路径的绝对路径、完整 sha256 hex 与字节数。"""
    for path in paths:
        assert any(form in message for form in _path_forms(path)), (
            f"错误消息缺少路径 {path}: {message}"
        )
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest in message, f"错误消息缺少完整 sha256 {digest}: {message}"
    for path in paths:
        size = path.stat().st_size
        assert re.search(rf"(?<!\d){size}(?!\d)", message), (
            f"错误消息缺少字节数 {size}: {message}"
        )


# --------------------------------------------------------------------------- #
# 1. 两侧一致：校验通过，训练冻结仍取 store 副本字节
# --------------------------------------------------------------------------- #


def test_matching_checkout_copy_passes_verification_and_freezing(
    tmp_path: Path,
) -> None:
    """两侧字节一致时校验通过，train prepare 也正常完成且冻结 store 副本字节。

    ``verify_prompt_checkout_copy`` 返回 None（默认由 store 根推导 checkout
    根）；随后 ``prepare_versioned_run`` 必须正常完成，冻结后的
    ``input/prompt.yaml`` 与 store 副本逐字节相同——证明新增的门没有把
    Prompt 选源从 store 改成 checkout。
    """
    from versioning.prompts import verify_prompt_checkout_copy

    root, media, _release, _rows = _store_fixture(tmp_path)
    store_copy = _store_copy(root)
    checkout_copy = _write_checkout(root.parent, store_copy)
    assert checkout_copy.read_bytes() == store_copy.read_bytes()

    assert verify_prompt_checkout_copy(root, STORE_PROMPT_VERSION) is None

    frozen = _prepare(root, media, _fold_configs(tmp_path))

    prompt_yaml = frozen / "prompt.yaml"
    assert prompt_yaml.is_file()
    assert prompt_yaml.read_bytes() == store_copy.read_bytes()


# --------------------------------------------------------------------------- #
# 2. 两侧不一致：拒绝，并给出两侧证据；入口不产生冻结产物
# --------------------------------------------------------------------------- #


def test_drifted_checkout_copy_reports_both_paths_digests_and_sizes(
    tmp_path: Path,
) -> None:
    """checkout 副本被改动一个字节以上时拒绝，并给出两侧路径、sha256 与字节数。"""
    from versioning.prompts import PromptCheckoutDrift, verify_prompt_checkout_copy

    root, _media, _release, _rows = _store_fixture(tmp_path)
    store_copy = _store_copy(root)
    checkout_copy = _write_checkout(
        root.parent, store_copy, content=_drifted_bytes(store_copy)
    )
    store_digest = hashlib.sha256(store_copy.read_bytes()).hexdigest()
    checkout_digest = hashlib.sha256(checkout_copy.read_bytes()).hexdigest()
    assert store_digest != checkout_digest

    with pytest.raises(PromptCheckoutDrift) as excinfo:
        verify_prompt_checkout_copy(root, STORE_PROMPT_VERSION)

    _assert_message_reports(str(excinfo.value), store_copy, checkout_copy)
    assert "--prompt-checkout-root" in str(excinfo.value)


def test_train_prepare_rejects_drifted_checkout_before_freezing(
    tmp_path: Path,
) -> None:
    """副本漂移时 train prepare 抛 PromptCheckoutDrift，且不产生任何冻结产物。"""
    from versioning.prompts import PromptCheckoutDrift

    root, media, _release, _rows = _store_fixture(tmp_path)
    store_copy = _store_copy(root)
    _write_checkout(root.parent, store_copy, content=_drifted_bytes(store_copy))

    with pytest.raises(PromptCheckoutDrift):
        _prepare(root, media, _fold_configs(tmp_path))

    assert not (root / "workspace/runs").exists()


# --------------------------------------------------------------------------- #
# 3. checkout 副本缺失：拒绝并提示显式传参
# --------------------------------------------------------------------------- #


def test_missing_checkout_copy_rejected_with_explicit_root_hint(
    tmp_path: Path,
) -> None:
    """store 侧存在、checkout 侧缺失时拒绝，并提示可用 --prompt-checkout-root。"""
    from versioning.prompts import PromptCheckoutDrift, verify_prompt_checkout_copy

    root, _media, _release, _rows = _store_fixture(tmp_path)
    assert _store_copy(root).is_file()
    assert not _checkout_copy(root.parent).exists()

    with pytest.raises(PromptCheckoutDrift) as excinfo:
        verify_prompt_checkout_copy(root, STORE_PROMPT_VERSION)

    assert "--prompt-checkout-root" in str(excinfo.value)


def test_train_prepare_rejects_missing_checkout_without_frozen_input(
    tmp_path: Path,
) -> None:
    """checkout 副本缺失时 train prepare 拒绝且不产生冻结产物。"""
    from versioning.prompts import PromptCheckoutDrift

    root, media, _release, _rows = _store_fixture(tmp_path)

    with pytest.raises(PromptCheckoutDrift):
        _prepare(root, media, _fold_configs(tmp_path))

    assert not (root / "workspace/runs").exists()


def test_missing_store_prompt_raises_prompt_not_found(tmp_path: Path) -> None:
    """store 侧副本缺失走既有 PromptNotFound，而不是副本漂移异常。"""
    from versioning.prompts import PromptNotFound, verify_prompt_checkout_copy

    root, _media, _release, _rows = _store_fixture(tmp_path)
    store_copy = _store_copy(root)
    _write_checkout(root.parent, store_copy)
    store_copy.unlink()

    with pytest.raises(PromptNotFound):
        verify_prompt_checkout_copy(root, STORE_PROMPT_VERSION)


# --------------------------------------------------------------------------- #
# 4. 显式 checkout 根：按传入值比对，不忽略参数
# --------------------------------------------------------------------------- #


def test_explicit_checkout_root_selects_consistent_third_copy(
    tmp_path: Path,
) -> None:
    """显式指向第三方一致副本时通过，即使默认推导位置不存在。"""
    from versioning.prompts import verify_prompt_checkout_copy

    root, media, _release, _rows = _store_fixture(tmp_path)
    store_copy = _store_copy(root)
    elsewhere = tmp_path / "elsewhere-checkout"
    third = _write_checkout(elsewhere, store_copy)
    assert third.read_bytes() == store_copy.read_bytes()
    assert not _checkout_copy(root.parent).exists()

    assert (
        verify_prompt_checkout_copy(
            root, STORE_PROMPT_VERSION, checkout_root=elsewhere
        )
        is None
    )
    frozen = _prepare(root, media, _fold_configs(tmp_path), prompt_checkout_root=elsewhere)
    assert (frozen / "prompt.yaml").read_bytes() == store_copy.read_bytes()


def test_explicit_checkout_root_reports_drifted_third_copy_evidence(
    tmp_path: Path,
) -> None:
    """显式指向不一致的第三方副本时拒绝，证据指向这份显式路径而非默认位置。"""
    from versioning.prompts import PromptCheckoutDrift, verify_prompt_checkout_copy

    root, _media, _release, _rows = _store_fixture(tmp_path)
    store_copy = _store_copy(root)
    elsewhere = tmp_path / "elsewhere-drifted"
    third = _write_checkout(
        elsewhere, store_copy, content=_drifted_bytes(store_copy)
    )

    with pytest.raises(PromptCheckoutDrift) as excinfo:
        verify_prompt_checkout_copy(
            root, STORE_PROMPT_VERSION, checkout_root=elsewhere
        )

    message = str(excinfo.value)
    _assert_message_reports(message, store_copy, third)
    assert "--prompt-checkout-root" in message


# --------------------------------------------------------------------------- #
# 5. 评测入口同构拒绝
# --------------------------------------------------------------------------- #


def test_eval_prepare_rejects_drifted_checkout_before_producing_input(
    tmp_path: Path,
) -> None:
    """评测 prepare 因 Prompt 副本漂移失败，且不产生评测冻结输入。

    评测入口要求 model registry 已注册模型（``validate_model_for_evaluation``
    先于取 Prompt），因此这里复用既有正式评测夹具：先以一致的 checkout 副本
    完成训练与注册，再把 checkout 副本改脏，验证拒绝来自 Prompt 副本一致性门。
    """
    from test_eval_run import _formal_eval_fixture

    from finetune.eval_run import prepare_versioned_evaluation
    from versioning.prompts import PromptCheckoutDrift

    # 评测夹具内部会先跑 train prepare（同样受这道门约束），因此先备好一份
    # 与 store 副本逐字节一致的 checkout 副本，再在夹具完成后把它改脏。
    checkout_copy = _checkout_copy(tmp_path)
    checkout_copy.parent.mkdir(parents=True, exist_ok=True)
    checkout_copy.write_bytes(_scratch_checkout_bytes(tmp_path))
    root, media, model, config = _formal_eval_fixture(
        tmp_path, prompt_definition=dict(PROMPT_DEFINITION)
    )
    store_copy = _store_copy(root)
    assert checkout_copy.read_bytes() == store_copy.read_bytes()
    checkout_copy.write_bytes(_drifted_bytes(store_copy))

    with pytest.raises(PromptCheckoutDrift):
        prepare_versioned_evaluation(
            root=root,
            eval_version=EVAL_VERSION,
            model_version=model.model_id,
            model_version_number=model.version,
            data_version=DATA_VERSION,
            config=config,
            git_commit="fixture",
            media_root=media,
        )

    assert not (root / "workspace/evaluations" / EVAL_VERSION / "input").exists()


# --------------------------------------------------------------------------- #
# 6. CLI 透传
# --------------------------------------------------------------------------- #


def test_train_prepare_cli_forwards_prompt_checkout_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`train prepare --prompt-checkout-root` 解析后原样透传给 prepare_versioned_run。

    端到端跑一次真实 CLI prepare 需要完整数据 release、媒体与基础模型夹具；
    此处按仓库既有 CLI 习惯（tests/versioning/test_cli.py）只钉死「参数被解析
    并原样透传」，实际拒绝行为已由上面的入口用例覆盖。
    """
    from finetune import train_prepare_run
    from versioning.cli import main

    seen: dict = {}
    config = tmp_path / "folds.yaml"
    config.write_text(yaml.safe_dump({f"fold{i}": {"seed": i} for i in range(3)}))
    environment = tmp_path / "environment.yaml"
    environment.write_text("python: fixture\n")
    elsewhere = tmp_path / "elsewhere-checkout"

    def prepare(**kwargs):
        seen.update(kwargs)
        return tmp_path / "input"

    monkeypatch.setattr(train_prepare_run, "prepare_versioned_run", prepare)

    assert (
        main(
            [
                "train",
                "prepare",
                TRAIN_VERSION,
                "--root",
                str(tmp_path),
                "--data-version",
                DATA_VERSION,
                "--prompt-version",
                STORE_PROMPT_VERSION,
                "--config",
                str(config),
                "--environment",
                str(environment),
                "--git-commit",
                "commit",
                "--media-root",
                str(tmp_path / "media"),
                "--prompt-checkout-root",
                str(elsewhere),
            ]
        )
        == 0
    )
    assert seen["prompt_checkout_root"] == elsewhere


# --------------------------------------------------------------------------- #
# 7. 同文件自比、holdout 透传与 eval run/score 逃生口
# --------------------------------------------------------------------------- #


def test_checkout_root_resolving_to_store_copy_is_rejected(tmp_path: Path) -> None:
    """checkout 根解析到 store 副本同一文件时拒绝：自比无法提供比对证据。

    直接传 store 根，或传一个解析后仍指回 store 根的别名，都会让两侧指向同一
    文件；此时 sha256 必然相等，门若放行就退化成永远通过，因此必须拒绝并说明
    两侧是同一文件。
    """
    from versioning.prompts import PromptCheckoutDrift, verify_prompt_checkout_copy

    root, _media, _release, _rows = _store_fixture(tmp_path)
    store_copy = _store_copy(root)
    alias = tmp_path / "alias-store"
    alias.symlink_to(root, target_is_directory=True)

    for checkout_root in (root, alias):
        with pytest.raises(PromptCheckoutDrift) as excinfo:
            verify_prompt_checkout_copy(
                root, STORE_PROMPT_VERSION, checkout_root=checkout_root
            )
        message = str(excinfo.value)
        assert "同一文件" in message
        assert "--prompt-checkout-root" in message
        assert any(form in message for form in _path_forms(store_copy))

    assert store_copy.is_file()
    assert not (root / "workspace/runs").exists()


def test_holdout_prepare_rejects_drifted_checkout_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """full holdout prepare 同样在取 Prompt 之前拒绝不一致的 checkout 副本。

    复用既有 holdout 合成夹具（``test_eval_holdout.prepare_holdout``）：训练与
    data claim 完成后把 checkout 副本改脏，再调用 prepare。holdout 原有的
    「训练 Prompt 与 store 正式副本一致」判定不变，这里验证的是新增的额外一层。
    """
    from test_eval_holdout import prepare_holdout

    from finetune import eval_run as evaluation
    from versioning.prompts import PromptCheckoutDrift

    root, _registry, _truth, kwargs = prepare_holdout(
        tmp_path, monkeypatch, prepare=False
    )
    store_copy = _store_copy(root)
    checkout_copy = _checkout_copy(root.parent)
    assert checkout_copy.read_bytes() == store_copy.read_bytes()
    checkout_copy.write_bytes(_drifted_bytes(store_copy))

    with pytest.raises(PromptCheckoutDrift):
        evaluation.prepare_versioned_evaluation(**kwargs)

    assert not (root / "workspace/evaluations" / EVAL_VERSION / "input").exists()


def test_formal_input_forwards_checkout_root_to_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_formal_input`` 的 holdout 分支把 prompt_checkout_root 转发给 build_holdout_input。

    真实拒绝行为已由上面的 holdout prepare 用例覆盖；此处只钉死「显式参数不被
    静默丢弃」——full 分支直接返回 build_holdout_input 的结果，若忘转发，显式
    checkout 根在 holdout 路径上会失效。
    """
    from finetune import eval_holdout
    from finetune.eval_run import _formal_input

    seen: dict = {}

    def build(**kwargs):
        seen.update(kwargs)
        return {"scope": "full"}

    monkeypatch.setattr(eval_holdout, "build_holdout_input", build)
    elsewhere = tmp_path / "elsewhere-checkout"
    config = {"scope": "full", "split": "holdout", "artifact_kind": "adapter"}

    assert (
        _formal_input(
            root=tmp_path,
            eval_version=EVAL_VERSION,
            model_version="model-v4.1-r1",
            model_version_number=3,
            data_version="data-v4.1-r3",
            config=config,
            git_commit="fixture",
            media_root=tmp_path / "media",
            prompt_checkout_root=elsewhere,
        )
        == {"scope": "full"}
    )
    assert seen["prompt_checkout_root"] == elsewhere
    assert seen["config"] is config


def test_eval_run_and_score_accept_prompt_checkout_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``eval run`` / ``eval score`` 接受该参数并原样透传。

    真实 checkout 根不是 ``<store 根>/..`` 时，用户只能靠这个显式参数；此前
    CLI 一律拒绝非 prepare/validate 传参，会形成「按错误提示传参却被 CLI 拒绝」
    的操作死路。
    """
    from finetune import eval_run as evaluation
    from versioning.cli import main

    seen: dict = {}
    monkeypatch.setattr(
        evaluation,
        "execute_versioned_evaluation",
        lambda **kwargs: seen.update(run=kwargs) or {"phase": "fixture"},
    )
    monkeypatch.setattr(
        evaluation,
        "resume_versioned_evaluation",
        lambda **kwargs: seen.update(score=kwargs) or tmp_path / "manifest.yaml",
    )
    elsewhere = tmp_path / "elsewhere-checkout"
    reviews = tmp_path / "reviews.json"
    reviews.write_text("{}", encoding="utf-8")

    assert (
        main(
            [
                "eval",
                "run",
                EVAL_VERSION,
                "--root",
                str(tmp_path),
                "--prompt-checkout-root",
                str(elsewhere),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "eval",
                "score",
                EVAL_VERSION,
                "--root",
                str(tmp_path),
                "--blind-reviews",
                str(reviews),
                "--prompt-checkout-root",
                str(elsewhere),
            ]
        )
        == 0
    )
    assert seen["run"]["prompt_checkout_root"] == elsewhere
    assert seen["score"]["prompt_checkout_root"] == elsewhere


def test_execute_and_resume_forward_checkout_root_to_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``execute`` / ``resume`` 内部每次 live 校验都带上显式 checkout 根。

    CLI 转发只到入口函数；这里钉死入口函数到 ``verify_versioned_evaluation``
    的第二段透传，否则参数到了入口也会被后续内部校验丢掉、照样形成死路。
    """
    from finetune import eval_run as evaluation

    seen: list = []

    def verify(**kwargs):
        seen.append(kwargs)
        raise RuntimeError("stop after first live verification")

    monkeypatch.setattr(evaluation, "verify_versioned_evaluation", verify)
    elsewhere = tmp_path / "elsewhere-checkout"

    with pytest.raises(RuntimeError, match="stop after first live verification"):
        evaluation.execute_versioned_evaluation(
            root=tmp_path, eval_version=EVAL_VERSION, prompt_checkout_root=elsewhere
        )
    with pytest.raises(RuntimeError, match="stop after first live verification"):
        evaluation.resume_versioned_evaluation(
            root=tmp_path,
            eval_version=EVAL_VERSION,
            blind_reviews=tmp_path / "reviews.json",
            prompt_checkout_root=elsewhere,
        )
    assert [entry["prompt_checkout_root"] for entry in seen] == [elsewhere, elsewhere]


# --------------------------------------------------------------------------- #
# 8. CLI 动作白名单：只有 prepare（eval 另加 validate/run/score）放行该参数
# --------------------------------------------------------------------------- #

# train 侧：准备阶段之后一律使用冻结输入，非 prepare 动作带该参数必须拒绝。
TRAIN_FROZEN_INPUT_ACTIONS = ("validate", "run")

# eval 侧：只对 prepare/validate/run/score 放行；其余动作的拒绝证据是
# ``actual evaluation accepts frozen inputs only``。
EVAL_FROZEN_INPUT_ONLY_ACTIONS = (
    "export",
    "compare",
    "review_prepare",
    "review_seal",
    "review_run",
    "review_verify",
    "restricted_summary",
)


def _allowed_required_flags(action: str, tmp_path: Path) -> list[str]:
    """该动作本身允许、且自身必填的参数；其余必填项由拒绝分支先兜住。"""
    policy = {
        "compare": ["--baseline-eval-version", "eval-v4.1-r2"],
        "review_prepare": ["--manual", str(tmp_path / "manual.md")],
        "review_seal": ["--blind-reviews", str(tmp_path / "blind-reviews.json")],
        "restricted_summary": ["--actor", "fixture-actor"],
    }
    return policy.get(action, [])


def test_train_non_prepare_cli_actions_reject_prompt_checkout_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """train 的 validate/run 带 ``--prompt-checkout-root`` 时被拒绝且不写任何冻结输入。

    该参数只在 ``train prepare`` 有意义；后续动作读取的是已冻结的 ``input/``，
    因此 CLI 必须在任何校验/执行动作之前 fail-closed，不能把参数静默丢弃后
    继续跑（那会让用户以为显式 checkout 根生效了）。
    """
    from versioning.cli import main

    elsewhere = tmp_path / "elsewhere-checkout"
    for action in TRAIN_FROZEN_INPUT_ACTIONS:
        root = tmp_path / f"project-{action}"
        argv = [
            "train",
            action,
            TRAIN_VERSION,
            "--root",
            str(root),
            "--prompt-checkout-root",
            str(elsewhere),
        ]

        assert main(argv) == 2, f"train {action} 应返回用法错误退出码 2: {argv}"
        message = capsys.readouterr().err
        assert "仅适用于 train prepare" in message, (
            f"train {action} 缺少稳定拒绝文案: {message!r}"
        )
        assert not (root / "workspace" / "runs").exists(), (
            f"train {action} 被拒绝前不应产生 run 目录"
        )
        assert not list(root.glob("**/input")), (
            f"train {action} 被拒绝前不应产生任何 input 冻结目录"
        )


def test_eval_frozen_input_only_actions_reject_prompt_checkout_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """eval 的 export/compare/review_*/restricted_summary 带该参数时一律被拒绝。

    这七个动作只接受 prepare 冻结过的输入，显式 checkout 根必须在 prepare 阶段
    用掉；若 CLI 放行，参数会被静默忽略，形成「按错误提示传参却不报错」的死路。
    每个动作补齐自身的必填参数（``--manual`` / ``--blind-reviews`` / ``--actor``
    等），确保命中的是 ``prompt_checkout_root`` 被拒那条语句，而不是必填校验。
    """
    from versioning.cli import main

    elsewhere = tmp_path / "elsewhere-checkout"
    for action in EVAL_FROZEN_INPUT_ONLY_ACTIONS:
        root = tmp_path / f"eval-project-{action}"
        argv = [
            "eval",
            action,
            EVAL_VERSION,
            "--root",
            str(root),
            *_allowed_required_flags(action, tmp_path),
            "--prompt-checkout-root",
            str(elsewhere),
        ]

        assert main(argv) == 2, f"eval {action} 应返回用法错误退出码 2: {argv}"
        message = capsys.readouterr().err
        assert "frozen inputs only" in message, (
            f"eval {action} 缺少稳定拒绝文案: {message!r}"
        )
        assert not list(root.glob("**/input")), (
            f"eval {action} 被拒绝前不应产生任何 input 冻结目录"
        )
