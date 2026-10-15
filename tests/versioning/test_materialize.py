"""B8 — 物化：注册模型 artifact 单向导出到 models/<model_id>/（含 manifest 链接）。

测评准入迁移说明：本文件的 strict fixture 仅模拟既有已绑定记录，不授予新准入。
新 finalize / alias / approve 的独立质量＋性能验收见 test_eval_admission_restore.py；
下列历史 B8 说明仅描述这些状态机和存储约束，不能替代新的准入条件。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
- §5.4（``workspace/models/materialized/model-v...`` 只是从权威 Registry 对象
  生成的本地部署副本，可以重新物化，不能反向修改 Registry 模型；模型内容、
  可读 model_id、数值 Model Version 与训练输入关系不可修改）、
- §7（每个物化目标必须携带机器生成的本地元数据，至少记录
  ``registered_model: mVllm2``、MLflow 数值 Model Version、可读 model_id 和
  对应 Git manifest）、
- §2.6 + D039（invalid 模型被下游拒绝；物化是下游入口，必须在线核对
  record_validity）、
- §2.11 + D036（offline_backup_scope 声明备份范围：导出元数据记录当前粘性
  范围，值域与单向升级规则见 test_registry.py）、
- §10（model 行下游规则：物化只接受 valid 的已注册模型）、
- §11.2（部分移动/不完整目标不能被读取：目标元数据与 Registry 分歧时
  fail-closed，拒绝覆盖导出）。

实现归属：本批契约把 materialize_model 一并钉在模块 ``versioning.registry``
（任务契约要点 4 属 registry.py 契约；测试拆分为 test_registry.py +
test_materialize.py 仅为可读性，二者共享同一实现模块）。

预期 production API（供 viber 对照实现，模块 ``versioning.registry``）::

    MATERIALIZED_METADATA_FILE: str = "materialized.yaml"
    MATERIALIZED_ARTIFACTS_DIR: str = "artifacts"

    def materialize_model(store: ModelRegistryStore, model_id: str,
                          models_root: Path) -> Path
        # 单向导出：把已注册模型的 Model Version artifacts 从 MLflow 导出到
        # models_root/<model_id>/，布局钉死为：
        #   models_root/<model_id>/
        #   ├── materialized.yaml    # 机器生成本地元数据（manifest 链接）
        #   └── artifacts/<run 内相对路径>/...   # 从 source（train 父 Run
        #       artifact 根）导出的 artifact 树，文件字节与 Run artifacts 一致
        # 校验顺序钉死：
        # 1) model_id 经 versioning.ids.parse_model_id 校验（缺省/None/latest/
        #    短前缀/跨类别/r0/前导零/非字符串/含引号注入样式 ->
        #    InvalidIdentifier）；
        # 2) 按 model_id tag 检索数值版本：不存在 -> RegistryModelNotFound
        #    （含重复 model_id tag 等读取 fail-closed，同 get_model 标准 ->
        #    IllegalRegistryRecord）；
        # 3) record_validity=invalid -> InvalidModelRecord（D039 在线核对，
        #    下游拒绝）；
        # 4) 目标一致性：models_root/<model_id>/materialized.yaml 已存在且
        #    其 model_id / mlflow_model_version 与 Registry 当前解析结果不同
        #    -> IllegalRegistryRecord（分歧目标拒绝覆盖导出，§11.2 不完整/
        #    过期目标不得被读取或续写；同 (model_id, 数值版本) 的既有目标
        #    允许幂等重导）；其他元数据漂移（offline_backup_scope 升级后的
        #    声明刷新）不视为分歧；
        # 5) 全部通过：创建缺失目录，导出 artifact 树（字节一致）并写入
        #    materialized.yaml（确定性内容，无时间戳：同 (model_id, 数值版本)
        #    + 同 tags 的两次导出字节相等）；返回
        #    models_root/<model_id>（Path）。
        # materialized.yaml 为 YAML mapping，键集合钉死为：
        #   registered_model: "mVllm2"
        #   mlflow_model_version: <int 数值版本>
        #   model_id / train_id / eval_id / data_version / prompt_version /
        #     git_commit: 与 Model Version tags 一致（值取自 train 父 Run）
        #   record_validity: "valid"（invalid 已在门 3) 拒绝）
        #   offline_backup_scope: <adapter|production_bundle|null（未写入）>
        #   manifest: "records/models/<model_id>/manifest.yaml"
        #     （§5.4 模型 manifest 的 Git 权威位置链接；本批不校验该文件
        #     存在性，model manifest 导出属 manifest.py 后续增量）
        # 方向性：物化只读 Registry，绝不回写 MLflow 对象（Registry/alias/
        # Run tags 在物化前后逐一不变）。

语义决策点（测试侧钉定，供实现对照）：
    1. 导出布局 = models_root/<model_id>/{materialized.yaml, artifacts/...}；
       artifact 树保持 train 父 Run artifact 根内的相对路径（source =
       train artifact_uri，见 test_registry.py 决策点 7）。
    2. "含 manifest 链接" 落为 materialized.yaml 的 manifest 字段（Git 权威
       路径 records/models/<model_id>/manifest.yaml，§5.4）；本批不复制、不
       校验该文件（model manifest 导出与字段验证属实施台账 B8 的
       test_manifest_model.py 增量，不在本任务允许创建的测试文件内）。
    3. "声明备份范围" 落为 materialized.yaml 的 offline_backup_scope 字段，
       记录当前粘性值（未写入为 null）；值域/单向升级由 registry 契约钉定
       （adapter/production_bundle，非五类名子集——见 test_registry.py
       决策点 2）。
    4. 分歧检测键 = (model_id, mlflow_model_version)；拒绝覆盖导出且不产生
       部分 artifacts/；同键幂等重导字节相等（无时间戳等非确定性字段）。
    5. §7 的 models/current 原子切换、service_mode 显式校验、alias-目标一致
       性与断链拒绝启动属实施台账 B8 materialize.py 服务物化增量，不在本批
       契约（任务要点 4 仅要求导出 + manifest 链接 + 备份范围声明）。
    6. 物化不要求模型已设置 alias 或 offline_backup_scope（导出是只读操作；
       备份范围前置只约束 alias 设置，见 registry 契约）。

测试环境：真实 MLflow 集成（非 mock）；train/eval/registry 三类 store 同根
共用同一 SQLite 单文件；模型 artifacts 经 client.log_artifact 真实写入 train
父 Run 后导出；models 目录与全部 store 均在 pytest ``tmp_path`` 内；不启动
服务、不加载真实模型权重、不连接任何正式 store。

当前 ``versioning/registry.py`` 尚不存在，本文件全部用例应为 RED
（collection error：ModuleNotFoundError / ImportError）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from pathlib import Path

import pytest
import yaml
from mlflow.tracking import MlflowClient
import versioning.materialize as materialize_module
import versioning.manifest as manifest_module

from versioning.data_release import seal_release, stage_release
from versioning.ids import InvalidIdentifier
from versioning.mlflow_eval import (
    EvalRecordStore,
    create_eval_fold_run,
    create_eval_run,
    end_eval_fold_run,
    log_eval_fold_metrics,
    log_eval_summary,
    open_eval_store,
    transition_eval_state,
)
from versioning.mlflow_train import (
    TrainRecordStore,
    TrainRunRecord,
    create_fold_run,
    create_train_run,
    end_fold_run,
    log_fold_metrics,
    log_train_summary,
    open_train_store,
    transition_train_state,
)
from versioning.manifest import (
    ManifestConflict,
    ManifestReferenceError,
    export_model_manifest,
    validate_model_manifest,
)
from versioning.materialize import materialize_current, validate_service_current
from versioning.registry import (
    ARTIFACTS_TAG,
    MATERIALIZED_ARTIFACTS_DIR,
    MATERIALIZED_METADATA_FILE,
    IllegalRegistryRecord,
    InvalidModelRecord,
    ModelRegistryStore,
    RegisteredModelRecord,
    RegistryModelNotFound,
    get_model,
    mark_model_invalid,
    materialize_model,
    open_registry_store,
    register_model,
    set_alias,
    set_offline_backup_scope,
)

MODEL_ID = "model-v4.1-r1"
OTHER_MODEL_ID = "model-v4.1-r2"
UNKNOWN_MODEL_ID = "model-v4.1-r9"
TRAIN_ID = "train-v4.1-r1"
EVAL_ID = "eval-v4.1-r1"
DATA_VERSION = "data-v4.1-r1"
PROMPT_VERSION = "prompt-v4.1-r1"
TRAIN_GIT_COMMIT = "a1b2c3d"
EVAL_GIT_COMMIT = "e5f6a7b"
BASE_MODEL = "MiniCPM-V-4.5"
CONFIG = "records/evaluations/config/eval-v4.1-contract.yaml"
MODEL_MANIFEST_LINK = f"records/models/{MODEL_ID}/manifest.yaml"

TRAIN_INPUTS: dict = {
    "data_version": DATA_VERSION,
    "prompt_version": PROMPT_VERSION,
    "git_commit": TRAIN_GIT_COMMIT,
    "base_model": BASE_MODEL,
    "config": {"epochs": 3, "lora_rank": 16},
}
TRAIN_FOLD_METRICS: dict = {"fold_f1": 0.8}
TRAIN_SUMMARY_METRICS: dict = {"cv_f1_mean": 0.8}
EVAL_FOLD_METRICS: dict = {"f1": 0.83}
EVAL_SUMMARY_METRICS: dict = {"f1": 0.83}
EVAL_FOLD_BINDINGS: dict = {
    "model_artifact": "artifacts/fold0/merged",
    "data_split": "validation/fold0",
    "sample_count": 8,
    "records": "folds/fold0/records.jsonl",
    "failures": "folds/fold0/failures.jsonl",
}

# 写入 train 父 Run 的真实 artifacts（相对 Run artifact 根的路径 -> 字节）。
ARTIFACT_FILES: dict[str, bytes] = {
    "fold0/adapter/adapter.bin": b"FAKE-ADAPTER-WEIGHTS",
    "fold0/adapter/config.json": b'{"lora_rank": 16}',
}

# materialized.yaml 的键集合（§7 本地元数据 + manifest 链接 + 备份范围声明）。
METADATA_KEYS = {
    "registered_model",
    "mlflow_model_version",
    "model_id",
    "train_id",
    "eval_id",
    "data_version",
    "prompt_version",
    "git_commit",
    "record_validity",
    "offline_backup_scope",
    "manifest",
}

# 非法 model_id：与 test_registry.py 同型（缺省/None/latest/短前缀/跨类别/
# r0/前导零/非字符串/空串）。
BAD_MODEL_IDS = [
    None,
    "latest",
    "model-v4.1",
    "train-v4.1-r1",
    "model-v4.1-r0",
    "model-v4.1-r01",
    7,
    "",
]


# —————————————————— fixtures 与 helpers ——————————————————


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """train/eval/registry 三类 store 共用的 MLflow 根（同根同 SQLite）。"""
    return tmp_path / "mlflow"


@pytest.fixture()
def registry(root: Path) -> ModelRegistryStore:
    return open_registry_store(root)


@pytest.fixture()
def train_store(root: Path) -> TrainRecordStore:
    return open_train_store(root)


@pytest.fixture()
def eval_store(root: Path) -> EvalRecordStore:
    return open_eval_store(root)


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    """已封存 development data-v4.1-r1 的 release 根（真实 data_release）。"""
    base = tmp_path / "data"
    (base / "working").mkdir(parents=True)
    (base / "release_staging").mkdir()
    (base / "releases").mkdir()
    working = base / "working" / "round-development"
    (working / "media").mkdir(parents=True)
    (working / "media" / "clip.mp4").write_bytes(b"\x00\x01")
    stage_release(base, "round-development", "v4.1", version=DATA_VERSION)
    seal_release(
        base,
        DATA_VERSION,
        purpose="development",
        description="物化导出测试正式数据",
        sample_count=2,
        source_batches=["batch-2026-07"],
        splits={"fold0": {"train": 1, "validation": 1}},
    )
    return base


@pytest.fixture()
def models_root(tmp_path: Path) -> Path:
    """临时 models 目录（尚不存在；materialize_model 负责创建）。"""
    return tmp_path / "models"


@pytest.fixture()
def golden(
    registry: ModelRegistryStore,
    train_store: TrainRecordStore,
    eval_store: EvalRecordStore,
    data_root: Path,
    tmp_path: Path,
) -> RegisteredModelRecord:
    """历史已绑定 strict 快照，含临时合成 artifacts；不执行新准入。"""
    train = _complete_training(train_store)
    register_model(registry, MODEL_ID, train_id=TRAIN_ID)
    _pass_eval(eval_store, data_root)
    _log_train_artifacts(registry, train.run_id, tmp_path)
    _client(registry).set_model_version_tag("mVllm2", "1", "eval_id", EVAL_ID)
    return get_model(registry, MODEL_ID)


def _client(
    store: ModelRegistryStore | TrainRecordStore | EvalRecordStore,
) -> MlflowClient:
    """raw MLflow 读写通道（真实集成：log artifacts / 读回对比）。"""
    return MlflowClient(tracking_uri=store.tracking_uri)


def _raw_model_versions(registry: ModelRegistryStore) -> list:
    return list(_client(registry).search_model_versions("name='mVllm2'"))


def _complete_training(
    train_store: TrainRecordStore, train_id: str = TRAIN_ID
) -> TrainRunRecord:
    """三折 FINISHED + 汇总 + completed（B6 合法完成路径）。"""
    inputs: dict = dict(TRAIN_INPUTS)
    create_train_run(train_store, train_id, **inputs)
    for fold in (0, 1, 2):
        create_fold_run(train_store, train_id, fold)
        log_fold_metrics(train_store, train_id, fold, TRAIN_FOLD_METRICS)
        end_fold_run(train_store, train_id, fold, "FINISHED")
    log_train_summary(train_store, train_id, TRAIN_SUMMARY_METRICS)
    return transition_train_state(train_store, train_id, "completed")


def _pass_eval(
    eval_store: EvalRecordStore, data_root: Path, *, eval_id: str = EVAL_ID
) -> None:
    """single_fold 正式测评 completed + outcome=passed（B7 合法路径）。"""
    create_eval_run(
        eval_store,
        eval_id,
        model_id=MODEL_ID,
        model_version_number=1,
        data_version=DATA_VERSION,
        config=CONFIG,
        git_commit=EVAL_GIT_COMMIT,
        scope="single_fold",
        split="validation/fold0",
        data_root=data_root,
    )
    create_eval_fold_run(eval_store, eval_id, 0, **EVAL_FOLD_BINDINGS)
    log_eval_fold_metrics(eval_store, eval_id, 0, EVAL_FOLD_METRICS)
    end_eval_fold_run(eval_store, eval_id, 0, "FINISHED")
    log_eval_summary(eval_store, eval_id, EVAL_SUMMARY_METRICS)
    transition_eval_state(eval_store, eval_id, "completed", outcome="passed")


def _log_train_artifacts(
    store: ModelRegistryStore | TrainRecordStore, run_id: str, tmp: Path
) -> None:
    """向 train 父 Run 真实写入 ARTIFACT_FILES（fold0/adapter/...）。"""
    client = _client(store)
    src = tmp / "train_artifacts"
    for rel, content in ARTIFACT_FILES.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        client.log_artifact(run_id, str(path), artifact_path=str(Path(rel).parent))


def _tree_digests(root: Path) -> dict[str, str]:
    """目标树内全部文件的 SHA-256（相对路径 -> 摘要），幂等性对比用。"""
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_divergent_metadata(
    target: Path, *, model_version: int = 999, model_id: str = MODEL_ID
) -> None:
    """预置一份形状完整但分歧键可控的既有 materialized.yaml（§11.2）。

    默认仅 mlflow_model_version 分歧（999）；model_id 分歧用例传另一合法
    模型 ID 并把数值版本对齐，以隔离分歧来源（manifest 链接随 model_id
    保持内部一致，非分歧检测键）。
    """
    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "registered_model": "mVllm2",
        "mlflow_model_version": model_version,
        "model_id": model_id,
        "train_id": TRAIN_ID,
        "eval_id": EVAL_ID,
        "data_version": DATA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "git_commit": TRAIN_GIT_COMMIT,
        "record_validity": "valid",
        "offline_backup_scope": None,
        "manifest": f"records/models/{model_id}/manifest.yaml",
    }
    (target / MATERIALIZED_METADATA_FILE).write_text(
        yaml.safe_dump(payload, sort_keys=True)
    )


def _registry_snapshot(registry: ModelRegistryStore) -> list[tuple]:
    """Registry 只读快照：每个数值版本的 (version, tags, aliases)。"""
    return sorted(
        (
            mv.version,
            tuple(sorted(mv.tags.items())),
            tuple(sorted(mv.aliases)),
        )
        for mv in _raw_model_versions(registry)
    )


# —————————————————— T7 物化导出 ——————————————————


class TestMaterializeModel:
    """materialize_model：黄金导出、备份范围声明、幂等、分歧/未知/invalid 拒绝、单向性。"""

    def test_materialization_constants_pinned(self) -> None:
        assert MATERIALIZED_METADATA_FILE == "materialized.yaml"
        assert MATERIALIZED_ARTIFACTS_DIR == "artifacts"

    def test_materialize_exports_artifacts_and_metadata(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        target = materialize_model(registry, MODEL_ID, models_root)

        # 返回目标目录 = models_root/<model_id>（路径解析后比较，防 symlink 差异）
        assert target.resolve() == (models_root / MODEL_ID).resolve()
        assert target.is_dir()

        # ——— materialized.yaml：键集合与全部字段值（§7 本地元数据 + §5.4 链接）———
        metadata_path = target / MATERIALIZED_METADATA_FILE
        assert metadata_path.is_file()
        payload = yaml.safe_load(metadata_path.read_text())
        assert set(payload) == METADATA_KEYS
        assert payload["registered_model"] == "mVllm2"
        assert payload["mlflow_model_version"] == 1
        assert payload["model_id"] == MODEL_ID
        assert payload["train_id"] == TRAIN_ID
        assert payload["eval_id"] == EVAL_ID
        assert payload["data_version"] == DATA_VERSION
        assert payload["prompt_version"] == PROMPT_VERSION
        assert payload["git_commit"] == TRAIN_GIT_COMMIT
        assert payload["record_validity"] == "valid"
        assert payload["offline_backup_scope"] is None
        assert payload["manifest"] == MODEL_MANIFEST_LINK

        # ——— artifacts/：从 train 父 Run artifact 根导出，字节一致 ———
        for rel, content in ARTIFACT_FILES.items():
            exported = target / MATERIALIZED_ARTIFACTS_DIR / rel
            assert exported.is_file(), f"缺失导出文件: {rel}"
            assert exported.read_bytes() == content

    def test_materialize_metadata_records_backup_scope(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        # 声明备份范围：导出元数据记录当前粘性 scope，升级后重导刷新
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        target = materialize_model(registry, MODEL_ID, models_root)
        payload = yaml.safe_load(
            (target / MATERIALIZED_METADATA_FILE).read_text()
        )
        assert payload["offline_backup_scope"] == "adapter"

        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        materialize_model(registry, MODEL_ID, models_root)
        payload = yaml.safe_load(
            (target / MATERIALIZED_METADATA_FILE).read_text()
        )
        assert payload["offline_backup_scope"] == "production_bundle"

    def test_materialize_idempotent_same_version(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        first = materialize_model(registry, MODEL_ID, models_root)
        digests = _tree_digests(first)

        # 同 (model_id, 数值版本) 幂等重导：不报错、字节相等（确定性内容）
        second = materialize_model(registry, MODEL_ID, models_root)
        assert second.resolve() == first.resolve()
        assert _tree_digests(second) == digests

    def test_materialize_rejects_divergent_existing_metadata(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        target = models_root / MODEL_ID
        _write_divergent_metadata(target, model_version=999)

        # §11.2：分歧/过期目标拒绝覆盖导出，不产生部分 artifacts/
        with pytest.raises(IllegalRegistryRecord):
            materialize_model(registry, MODEL_ID, models_root)
        assert (target / MATERIALIZED_METADATA_FILE).is_file()  # 既有元数据不动
        assert not (target / MATERIALIZED_ARTIFACTS_DIR).exists()

    def test_materialize_rejects_model_id_divergent_existing_metadata(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        # B8 P2 覆盖缺口回归：既有目标 materialized.yaml 的 model_id 与请求
        # 不一致（声称属于另一合法模型；数值版本对齐以隔离分歧来源，拒绝只
        # 能来自 model_id 分歧）-> IllegalRegistryRecord 拒绝覆盖导出：既有
        # 元数据字节原样保留、无部分 artifacts/；同一 Registry 对干净目标
        # 的正常导出不受影响。
        target = models_root / MODEL_ID
        _write_divergent_metadata(target, model_version=1, model_id=OTHER_MODEL_ID)
        metadata_path = target / MATERIALIZED_METADATA_FILE
        before_bytes = metadata_path.read_bytes()

        with pytest.raises(IllegalRegistryRecord):
            materialize_model(registry, MODEL_ID, models_root)

        # 拒覆：既有元数据字节不变（仍声称另一模型）
        assert metadata_path.read_bytes() == before_bytes
        payload = yaml.safe_load(metadata_path.read_text())
        assert payload["model_id"] == OTHER_MODEL_ID
        # 无部分 artifacts：分歧目标未被写入任何导出内容
        assert not (target / MATERIALIZED_ARTIFACTS_DIR).exists()

        # 正常路径不受影响：同一 Registry 对干净目标照常完整导出
        clean_target = materialize_model(registry, MODEL_ID, models_root / "fresh")
        for rel, content in ARTIFACT_FILES.items():
            assert (
                clean_target / MATERIALIZED_ARTIFACTS_DIR / rel
            ).read_bytes() == content

    def test_materialize_unknown_model_rejected(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        with pytest.raises(RegistryModelNotFound):
            materialize_model(registry, UNKNOWN_MODEL_ID, models_root)
        # fail-closed：不创建任何目标目录
        assert not models_root.exists()

    @pytest.mark.parametrize("bad_model_id", BAD_MODEL_IDS)
    def test_materialize_malformed_id_rejected(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
        bad_model_id,
    ) -> None:
        with pytest.raises(InvalidIdentifier):
            materialize_model(registry, bad_model_id, models_root)
        assert not models_root.exists()

    def test_materialize_invalid_model_rejected(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        # D039：物化是下游入口，invalid 在线拒绝，不产生半导出目标
        mark_model_invalid(registry, MODEL_ID)
        with pytest.raises(InvalidModelRecord):
            materialize_model(registry, MODEL_ID, models_root)
        assert not (models_root / MODEL_ID).exists()

    def test_materialize_is_read_only_wrt_registry(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        # §5.4：物化是单向导出——Registry（数值版本/tags/aliases）前后逐一不变
        before = _registry_snapshot(registry)
        materialize_model(registry, MODEL_ID, models_root)
        materialize_model(registry, MODEL_ID, models_root)  # 重导同样只读
        assert _registry_snapshot(registry) == before

        # 导出目录确已产生（证明只读断言不是空转）
        assert (models_root / MODEL_ID / MATERIALIZED_ARTIFACTS_DIR).is_dir()


class TestModelManifestAndCurrent:
    """B8 遗漏回归：严格 model manifest 与 alias 精确 current 缓存。"""

    def _publish_candidate(
        self,
        registry: ModelRegistryStore,
        records_root: Path,
    ) -> Path:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        target = records_root / "records" / "models" / MODEL_ID / "manifest.yaml"
        export_model_manifest(target, store=registry, model_id=MODEL_ID)
        # Simulate a pre-existing alias; strict evidence cannot create a new one.
        _client(registry).set_registered_model_alias("mVllm2", "candidate", "1")
        assert set_alias(registry, MODEL_ID, "candidate").version == 1
        return target

    def test_model_manifest_and_current_round_trip(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        records_root = models_root.parent
        manifest = self._publish_candidate(registry, records_root)
        parsed = validate_model_manifest(manifest.read_text(encoding="utf-8"))
        assert parsed["version"] == MODEL_ID
        assert parsed["mlflow_model_version"] == golden.version
        assert parsed["source_run_id"] == golden.run_id
        assert parsed["deploy_target"] == "artifacts/fold0/adapter"

        current = materialize_current(
            registry,
            alias="candidate",
            service_mode="development",
            models_root=models_root,
            records_root=records_root,
        )
        assert current.is_symlink()
        assert current.resolve().name == MODEL_ID
        validated = validate_service_current(
            registry,
            alias="candidate",
            service_mode="development",
            models_root=models_root,
            records_root=records_root,
        )
        assert validated.version == golden.version

    def test_missing_manifest_rejected_without_switching_old_current(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        # Simulate a pre-existing alias; strict evidence cannot create a new one.
        _client(registry).set_registered_model_alias("mVllm2", "candidate", "1")
        assert set_alias(registry, MODEL_ID, "candidate").version == 1
        old = models_root / "materialized" / "old-model"
        old.mkdir(parents=True)
        models_root.mkdir(parents=True, exist_ok=True)
        (models_root / "current").symlink_to(Path("materialized") / "old-model")

        with pytest.raises(ManifestReferenceError, match="缺少 model manifest"):
            materialize_current(
                registry,
                alias="candidate",
                service_mode="development",
                models_root=models_root,
                records_root=models_root.parent,
            )
        assert (models_root / "current").resolve() == old.resolve()

    def test_download_failure_preserves_old_current(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        records_root = models_root.parent
        self._publish_candidate(registry, records_root)
        old = models_root / "materialized" / "old-model"
        old.mkdir(parents=True)
        (models_root / "current").symlink_to(Path("materialized") / "old-model")

        def fail_download(*args, **kwargs):
            raise RuntimeError("injected download failure")

        monkeypatch.setattr(MlflowClient, "download_artifacts", fail_download)
        with pytest.raises(RuntimeError, match="download failure"):
            materialize_current(
                registry,
                alias="candidate",
                service_mode="development",
                models_root=models_root,
                records_root=records_root,
            )
        assert (models_root / "current").resolve() == old.resolve()
        assert not (models_root / "materialized" / MODEL_ID).exists()

    def test_missing_non_deploy_artifact_leaves_no_materialized_target(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        artifacts = {
            "fold0": {
                "adapter": "artifacts/fold0/adapter",
                "merged": "artifacts/fold0/merged",
            }
        }
        _client(registry).set_model_version_tag(
            "mVllm2", str(golden.version), ARTIFACTS_TAG, json.dumps(artifacts)
        )
        records_root = models_root.parent
        self._publish_candidate(registry, records_root)

        with pytest.raises(ManifestReferenceError, match="merged"):
            materialize_current(
                registry,
                alias="candidate",
                service_mode="development",
                models_root=models_root,
                records_root=records_root,
            )
        assert not (models_root / "materialized" / MODEL_ID).exists()
        assert not (models_root / "current").exists()

    def test_service_mode_and_manifest_mismatch_fail_closed(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
    ) -> None:
        records_root = models_root.parent
        manifest = self._publish_candidate(registry, records_root)
        with pytest.raises(ManifestReferenceError, match="production 模式"):
            materialize_current(
                registry,
                alias="candidate",
                service_mode="production",
                models_root=models_root,
                records_root=records_root,
            )

        payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        payload["mlflow_model_version"] = golden.version + 1
        manifest.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
        with pytest.raises(ManifestReferenceError, match="mlflow_model_version"):
            materialize_current(
                registry,
                alias="candidate",
                service_mode="development",
                models_root=models_root,
                records_root=records_root,
            )

    def test_post_switch_revalidation_failure_restores_old_current(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        records_root = models_root.parent
        self._publish_candidate(registry, records_root)
        old = models_root / "materialized" / "old-model"
        old.mkdir(parents=True)
        (models_root / "current").symlink_to(Path("materialized") / "old-model")

        def reject_after_switch(*args, **kwargs):
            raise ManifestReferenceError("injected final alias drift")

        monkeypatch.setattr(
            materialize_module, "validate_service_current", reject_after_switch
        )
        with pytest.raises(ManifestReferenceError, match="alias drift"):
            materialize_current(
                registry,
                alias="candidate",
                service_mode="development",
                models_root=models_root,
                records_root=records_root,
            )
        assert (models_root / "current").resolve() == old.resolve()

    def test_service_validation_rejects_external_manual_target(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        models_root: Path,
        tmp_path: Path,
    ) -> None:
        records_root = models_root.parent
        self._publish_candidate(registry, records_root)
        current = materialize_current(
            registry,
            alias="candidate",
            service_mode="development",
            models_root=models_root,
            records_root=records_root,
        )
        expected = current.resolve()
        external = tmp_path / "manually-selected"
        shutil.copytree(expected, external)
        current.unlink()
        current.symlink_to(external)

        with pytest.raises(ManifestReferenceError, match="精确指向"):
            validate_service_current(
                registry,
                alias="candidate",
                service_mode="development",
                models_root=models_root,
                records_root=records_root,
            )

    def test_concurrent_model_manifest_publish_is_immutable(
        self,
        registry: ModelRegistryStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        barrier = threading.Barrier(2)
        target = tmp_path / "manifest.yaml"
        outcomes: list[str] = []

        def fake_build(store, model_id):
            barrier.wait()
            return f"version: {model_id}\n"

        def publish(model_id: str) -> None:
            try:
                export_model_manifest(target, store=registry, model_id=model_id)
            except ManifestConflict:
                outcomes.append("conflict")
            else:
                outcomes.append("ok")

        monkeypatch.setattr(manifest_module, "build_model_manifest", fake_build)
        threads = [
            threading.Thread(target=publish, args=(MODEL_ID,)),
            threading.Thread(target=publish, args=(OTHER_MODEL_ID,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(outcomes) == ["conflict", "ok"]
        assert target.read_text(encoding="utf-8") in {
            f"version: {MODEL_ID}\n",
            f"version: {OTHER_MODEL_ID}\n",
        }


@pytest.fixture(autouse=True)
def record_policy_execution_evidence_double(monkeypatch):
    """Isolate the pre-migration record-policy scenarios from GPU execution proof.

    This module does not certify actual execution or promotion evidence. Unmocked
    evidence, drift and public service tests live in test_eval_run/test_train_with_contract.
    """
    monkeypatch.setattr("versioning.registry._validate_train_execution_artifacts", lambda *a: None)
    monkeypatch.setattr("versioning.registry._validate_eval_execution_artifacts", lambda *a: None)
    monkeypatch.setattr("versioning.registry._validate_model_artifact_evidence", lambda *a: None)
