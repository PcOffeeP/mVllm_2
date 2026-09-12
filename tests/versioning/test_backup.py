"""B9 — 离线备份 catalog 与恢复：源集合枚举、确定性 catalog、原子维护、修复与恢复（测试先行）。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
- §2.2（离线备份边界：正式数据与重要模型进移动硬盘，可重建对象不进）；
- §2.10（adapter / production_bundle 的备份内容边界）；
- §2.11 + D036（备份范围由 offline_backup_scope 粘性 tag 决定；源集合由机器
  计算 = 全部正式数据 + 带范围 tag 的模型；catalog 存在一行不能证明备份存在；
  每次连接复验全部既有对象；catalog 临时文件校验通过后原子替换并保留上一份
  可读快照；catalog 损坏必须能从硬盘对象目录 + 源集合重新扫描生成；MLflow
  SQLite 一致性快照；备份成功不删源；恢复演练只到明确临时目录、不覆盖正式
  产物、不改训练机正式对象）；
- §13.1（备份源集合覆盖全部正式数据与所有带 scope 的模型；candidate→
  production 只升级备份范围；catalog 仅在复制与校验完成后原子写入
  ``verified: true``；备份成功不触发源文件删除；SQLite 快照与 artifact store
  联合恢复后可查询父子 Run、指标、Model Version、alias 和 artifact）。

实现归属：实施台账 B9 的 ``versioning/backup.py``。本批为测试先行：契约由本
文件钉定，``versioning/backup.py`` 尚不存在，全部用例应为 RED
（collection error：ModuleNotFoundError / ImportError）。

预期 API（供实现对照，模块 ``versioning/backup.py``）::

    BACKUP_CATALOG_FILENAME: str = "backup_catalog.yaml"
    BACKUP_CATALOG_SNAPSHOT_FILENAME: str = "backup_catalog.yaml.prev"
    BACKUP_CATALOG_VERSION: int = 1
    MLFLOW_STORE_OBJECT_ID: str = "mlflow-store"

    OBJECT_TYPE_DATA_RELEASE / OBJECT_TYPE_PROMPT / OBJECT_TYPE_MODEL /
        OBJECT_TYPE_MLFLOW_STORE = "data_release" / "prompt" / "model" /
        "mlflow_store"
    SCOPE_DATA_RELEASE / SCOPE_PROMPT / SCOPE_MLFLOW_STORE =
        "data" / "prompt" / "mlflow_store"
        # 模型对象的 scope 复用 registry 的 "adapter" / "production_bundle" 值
    BACKUP_DIR_DATA / BACKUP_DIR_PROMPTS / BACKUP_DIR_MODELS /
        BACKUP_DIR_MLFLOW = "data" / "prompts" / "models" / "mlflow"
        # 备份根内固定子目录布局（catalog 损坏后的硬盘重扫描需要固定布局）：
        #   <backup_root>/data/<data_version>/...      ← release 目录整树
        #   <backup_root>/prompts/<prompt_version>.yaml ← 正式 prompt 文件
        #   <backup_root>/models/<model_id>/...         ← 物化目录整树
        #   <backup_root>/mlflow/...                    ← MLflow store 根整树
        #   <backup_root>/backup_catalog.yaml（+ .prev 上一份可读快照）

    class BackupError(ValueError): ...                 # 备份域异常基类
    class BackupSourceSetError(BackupError): ...      # 源集合枚举 fail-closed
    class CatalogSchemaError(BackupError): ...        # catalog 不可读/schema 非法
    class BackupIntegrityError(BackupError): ...      # 篡改/缺失/额外对象
    class RestoreTargetConflict(BackupError): ...     # 恢复目标已存在，拒绝覆盖

    @dataclass(frozen=True)
    class BackupSource:
        object_id: str; object_type: str; scope: str; source: Path

    @dataclass(frozen=True)
    class BackupFileEntry:
        path: str        # 相对 backup_root 的 POSIX 路径
        byte_size: int
        sha256: str      # sha256(文件字节)，64 位小写 hex

    @dataclass(frozen=True)
    class BackupObjectEntry:
        object_id: str; object_type: str; scope: str
        source: str          # 来源绝对路径（str(Path)）
        backed_up_at: str    # ISO-8601，可 datetime.fromisoformat 解析
        verified: bool      # 仅在复制 + 校验完成后才为 True
        byte_size: int      # == sum(files[].byte_size)
        sha256: str         # 对象级摘要（确定性；算法不钉死）
        files: tuple[BackupFileEntry, ...]   # 按 path 排序

    @dataclass(frozen=True)
    class BackupCatalog:
        objects: tuple[BackupObjectEntry, ...]   # 按 object_id 排序

    def enumerate_backup_sources(store, *, data_root, prompts_root,
                                 models_root) -> tuple[BackupSource, ...]
        # 源集合 = data_root/releases/ 下全部正式数据 + 带 offline_backup_scope
        # tag 的模型（历史最高范围，与当前 alias 无关）+ 作用域模型引用的
        # prompt 版本 + 恰一个 MLflow store 对象（source = store.root）。
        # fail-closed：作用域模型未物化 / 引用 prompt 文件缺失 / 物化
        # materialized.yaml 的 offline_backup_scope 与 Registry tag 分歧
        # → BackupSourceSetError（不静默跳过）。

    def create_backup(store, *, data_root, prompts_root, models_root,
                      backup_root) -> BackupCatalog
        # 真实文件级复制到固定布局；复验 catalog 全部既有对象，完整性失败
        #（篡改/缺失）项从源重复制修复；额外对象（catalog 外文件）一律
        # fail-closed、绝不静默删除；catalog 临时文件校验通过后原子替换并
        # 保留上一份可读快照；全程不修改源对象、不删除源；失败运行不改变
        # 盘上既有 catalog；返回与盘上 YAML 等值的 BackupCatalog。

    def load_backup_catalog(backup_root) -> BackupCatalog
        # 仅做 schema 校验并解析；垃圾字节 / 非 mapping / 对象或文件缺字段
        # → CatalogSchemaError。

    def verify_backup(backup_root) -> BackupCatalog
        # load + 逐文件核对（存在 / byte_size / sha256 复算）+ 额外对象核对
        #（backup_root 实际文件集合 == catalog 文件 + catalog + 可选 .prev）；
        # 任一不符 → BackupIntegrityError。catalog 存在但文件缺失/被篡改
        # 不得判通过（D036）。

    def restore_backup(backup_root, *, data_root, prompts_root, models_root,
                       mlflow_root) -> None
        # 恢复前先完整执行 verify_backup 级校验，失败零副作用（目标目录不得
        # 被创建）；校验通过后按对象类型恢复到四个显式目标根：
        #   data_release → data_root/releases/<version>/
        #   prompt       → prompts_root/records/prompts/<version>.yaml
        #   model        → models_root/<model_id>/
        #   mlflow_store → mlflow_root/（store 根整树）
        # 恢复产物与源同构（含 release payload 只读封存态）；恢复不修改
        # backup_root 与 catalog；目标已存在 → RestoreTargetConflict
        #（不覆盖既有正式产物）；恢复完成后可用既有模块重新打开并读取。

catalog YAML schema（backup_catalog.yaml，原子替换目标）::

    catalog_version: 1
    objects:
      - object_id / object_type / scope / source / backed_up_at / verified /
        byte_size / sha256 / files: [{path, byte_size, sha256}, ...]

语义决策点（测试侧钉定，供实现对照）：
    1. 源集合四类对象 = 全部正式数据（releases/ 下每个封存目录）、带
       offline_backup_scope tag 的模型、作用域模型引用的 prompt 版本（完整
       身份资料）、恰一个 MLflow store。未被引用、或只被未设范围模型引用的
       prompt 不进入源集合；working/ 中未封存数据不进入源集合。
    2. 模型备份源钉定为物化目录 models/<model_id>/（materialize_model 产物）；
       未物化的作用域模型 fail-closed。adapter 只复制 materialized.yaml、严格
       model manifest 与声明 adapter；production_bundle 复制声明 adapter+merged。
       manifest 随 model catalog 明确入备并恢复到 Git 工作区原相对路径。
    3. 历史最高范围：直接消费 registry 的 offline_backup_scope tag（B8 已钉定
       单向粘性升级）；枚举 / catalog / 修复一律按 tag 决定范围，不依据当前
       alias 反推历史角色；scope 升级后未重新物化（物化声明与 tag 分歧）时
       fail-closed，重物化后按新范围重备份。
    4. 确定性 catalog：对象按 object_id、文件按 path 排序；文件 sha256 ==
       sha256(文件字节)、byte_size 精确；对象级 sha256 只钉确定性（同源两次
       备份相同）与 64 位小写 hex，不钉具体树摘要算法；backed_up_at 是唯一
       允许随运行变化的字段（确定性比较一律剔除它）。
    5. SQLite 一致性快照机制不钉死（raw copy 或 sqlite3 backup API 均可）；
       钉结果：备份的 mlflow.db 必须是可查询的有效 SQLite
       （PRAGMA integrity_check == ok、runs 表可查），允许与源文件字节不同；
       MLflow artifact store 仅复制作用域模型按范围声明的训练 artifact 与其已
       绑定正式 eval artifact，adapter 对应 train run 不得夹带 merged。
    6. 修复语义：catalog 条目对应文件被篡改/缺失时，verify/restore 一律
       fail-closed；下一次 create_backup 把完整性失败对象从源重复制修复
       （D036 修复/重备份集合）。额外对象（catalog 与源集合之外的文件）
       在 verify/restore/create_backup 一律 fail-closed，绝不静默删除。
    7. catalog 损坏：load/verify/restore fail-closed（CatalogSchemaError）；
       create_backup 不被损坏 catalog 阻断，按源集合 + 硬盘对象目录重新扫描
       生成（不能因 catalog 无法读取就假定无需备份）。
    8. 恢复目标四根显式传入（显式选择纪律）；MLflow store 的 artifact URI
       在 SQLite 内按创建时的绝对路径记录，故 artifact 级自愈验证按
       “删除原目录 + 恢复到原绝对路径”的灾难恢复语义演练；非 MLflow 对象
       另行验证异地恢复后同样可用既有模块重开。
    9. 单向性：备份生成不修改任何源对象（含源 SQLite 文件字节，备份成功
       也不删源）；恢复零副作用——backup_root 文件树与 catalog 字节前后
       不变；verified 仅在复制与校验完成后随 catalog 原子写入，失败运行
       不得改变盘上既有 catalog。

B9 修复回归批（viber 修复复验，新增用例见文件尾部 T7–T10）：
    P1 — create_backup 在 catalog 落盘前对全部对象做完整性校验（含备份
    mlflow.db 的 SQLite PRAGMA integrity_check）；校验失败抛
    BackupIntegrityError，且不产生（首次）/不改写（既有）盘上 catalog。
    P2 — 二次备份时健康对象不重拷（零复制调用、payload 文件 inode/mtime
    不变、catalog 条目原样复用）；篡改单文件后仅该对象整树重拷修复。
    P3 — 空 MLflow store 可备份可恢复；load_backup_catalog 拒绝重复
    object_id；releases/ 下非目录条目（与非法 data ID 目录名）fail-closed；
    restore 在异地恢复时重放 release payload 只读封存位（seal_payload，
    原私有名 _seal_payload）。

测试环境：真实 MLflow 集成（非 mock）；train/eval/registry 三类 store 同根
共用同一 SQLite 单文件；release 目录、prompt 文件、物化目录与备份根全部位
于 pytest ``tmp_path``；文件级真实复制；不启动服务、不连接网络、不接触真
实移动硬盘。

T1–T6 为 B9 首批契约用例（已 GREEN：``versioning/backup.py`` 已实现）；
T7–T10 为 B9 修复回归批（P1/P2/P3 复验），全部用例应保持 GREEN。
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import os
import shutil
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
from mlflow.tracking import MlflowClient

import versioning.backup as backup_module
from versioning.backup import (
    BACKUP_CATALOG_FILENAME,
    BACKUP_CATALOG_SNAPSHOT_FILENAME,
    BACKUP_CATALOG_VERSION,
    BACKUP_DIR_DATA,
    BACKUP_DIR_MLFLOW,
    BACKUP_DIR_MODELS,
    BACKUP_DIR_PROMPTS,
    MLFLOW_STORE_OBJECT_ID,
    OBJECT_TYPE_DATA_RELEASE,
    OBJECT_TYPE_MLFLOW_STORE,
    OBJECT_TYPE_MODEL,
    OBJECT_TYPE_PROMPT,
    SCOPE_DATA_RELEASE,
    SCOPE_MLFLOW_STORE,
    SCOPE_PROMPT,
    BackupCatalog,
    BackupError,
    BackupFileEntry,
    BackupIntegrityError,
    BackupObjectEntry,
    BackupSource,
    BackupSourceSetError,
    CatalogSchemaError,
    RestoreTargetConflict,
    create_backup,
    enumerate_backup_sources,
    load_backup_catalog,
    restore_backup,
    verify_backup,
)
from versioning.data_release import (
    assert_payload_sealed,
    load_release_metadata,
    seal_release,
    stage_release,
)
from versioning.mlflow_eval import (
    EvalRecordStore,
    create_eval_fold_run,
    create_eval_run,
    end_eval_fold_run,
    get_eval_run,
    log_eval_fold_metrics,
    log_eval_summary,
    open_eval_store,
    transition_eval_state,
)
from versioning.mlflow_train import (
    TrainRecordStore,
    create_fold_run,
    create_train_run,
    end_fold_run,
    get_train_run,
    log_fold_metrics,
    log_train_summary,
    open_train_store,
    transition_train_state,
)
from versioning.manifest import export_model_manifest, validate_model_manifest
from versioning.materialize import materialize_current, validate_service_current
from versioning.prompts import create_prompt, load_prompt, prompt_path
from versioning.registry import (
    MATERIALIZED_METADATA_FILE,
    ModelRegistryStore,
    approve_model_for_production,
    finalize_model_evaluation,
    get_model,
    get_model_by_alias,
    materialize_model,
    open_registry_store,
    register_model,
    set_alias,
    set_offline_backup_scope,
)

# —————————————————— 测试世界常量 ——————————————————

DATA_VERSION = "data-v4.1-r1"
EXTRA_DATA_VERSION = "data-v4.1-r2"
THIRD_DATA_VERSION = "data-v4.1-r3"

MODEL_ID = "model-v4.1-r1"  # scope=adapter，candidate alias
BUNDLED_MODEL_ID = "model-v4.1-r2"  # scope=production_bundle，无 alias
UNSCOPED_MODEL_ID = "model-v4.1-r3"  # 未设 scope tag（不进源集合）

PROMPT_VERSION = "prompt-v4.1-r1"  # 被两个作用域模型引用 → 备份
UNREFERENCED_PROMPT_VERSION = "prompt-v4.1-r2"  # 无人引用 → 不备份
UNSCOPED_PROMPT_VERSION = "prompt-v4.1-r3"  # 只被未设范围模型引用 → 不备份

TRAIN_ID = "train-v4.1-r1"
BUNDLED_TRAIN_ID = "train-v4.1-r2"
UNSCOPED_TRAIN_ID = "train-v4.1-r3"
EVAL_ID = "eval-v4.1-r1"
BUNDLED_EVAL_ID = "eval-v4.1-r2"
UNSCOPED_EVAL_ID = "eval-v4.1-r3"

TRAIN_GIT_COMMIT = "a1b2c3d"
EVAL_GIT_COMMIT = "e5f6a7b"
BASE_MODEL = "MiniCPM-V-4.5"
CONFIG = "records/evaluations/config/eval-v4.1-contract.yaml"

SYSTEM_PROMPT = "你是严肃的视觉问答助手。"
USER_PROMPT = "请回答图中问题。"
OUTPUT_FIELDS = ("answer",)

TRAIN_INPUTS_TEMPLATE: dict = {
    "data_version": DATA_VERSION,
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

# 写入 train 父 Run 的真实 artifacts（fold0/adapter + fold0/merged）。
ARTIFACT_FILES: dict[str, bytes] = {
    "fold0/adapter/adapter.bin": b"FAKE-ADAPTER-WEIGHTS",
    "fold0/adapter/config.json": b'{"lora_rank": 16}',
    "fold0/merged/merged.bin": b"FAKE-MERGED-WEIGHTS",
}

# 黄金世界的源集合对象 ID（§2.11：全部正式数据 + 作用域模型 + 其 prompt
# + 恰一个 MLflow store）。
EXPECTED_OBJECT_IDS = frozenset(
    {
        DATA_VERSION,
        EXTRA_DATA_VERSION,
        MODEL_ID,
        BUNDLED_MODEL_ID,
        MLFLOW_STORE_OBJECT_ID,
        PROMPT_VERSION,
    }
)

# backup_catalog.yaml 的对象/文件键集合（schema 钉定）。
OBJECT_KEYS = {
    "object_id",
    "object_type",
    "scope",
    "source",
    "backed_up_at",
    "verified",
    "byte_size",
    "sha256",
    "files",
}
FILE_KEYS = {"path", "byte_size", "sha256"}


# —————————————————— fixtures 与 helpers ——————————————————


@dataclass(frozen=True)
class World:
    """备份测试黄金世界的四个根（全部位于 tmp_path 内）。"""

    mlflow_root: Path
    data_root: Path
    prompts_root: Path
    models_root: Path


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
    """已封存两个 development release 的 release 根（真实 data_release）。"""
    base = tmp_path / "data"
    (base / "working").mkdir(parents=True)
    (base / "release_staging").mkdir()
    (base / "releases").mkdir()
    _seal_release(base, DATA_VERSION, round_name="round-a", description="备份契约 r1")
    _seal_release(base, EXTRA_DATA_VERSION, round_name="round-b", description="备份契约 r2")
    return base


@pytest.fixture()
def models_root(tmp_path: Path) -> Path:
    """临时 models 根（尚不存在；materialize_model 负责创建）。"""
    return tmp_path / "models"


@pytest.fixture()
def backup_root(tmp_path: Path) -> Path:
    """模拟移动硬盘挂载点（尚不存在；create_backup 负责创建）。"""
    return tmp_path / "drive"


@pytest.fixture()
def world(
    registry: ModelRegistryStore,
    train_store: TrainRecordStore,
    eval_store: EvalRecordStore,
    data_root: Path,
    models_root: Path,
    tmp_path: Path,
) -> World:
    """黄金世界：3 prompt / 3 train / 3 eval / 3 注册模型 + 作用域 + 物化。

    模型角色：r1=adapter+candidate；r2=production_bundle+无 alias；
    r3=未设 scope（连同其引用 prompt 一起验证“不进源集合”）。
    """
    prompts_root = tmp_path
    for version in (PROMPT_VERSION, UNREFERENCED_PROMPT_VERSION, UNSCOPED_PROMPT_VERSION):
        _create_prompt_version(prompts_root, version)

    train1 = _train_chain(train_store, TRAIN_ID, PROMPT_VERSION)
    model_artifacts = {
        "fold0": {
            "adapter": "artifacts/fold0/adapter",
            "merged": "artifacts/fold0/merged",
        }
    }
    register_model(registry, MODEL_ID, train_id=TRAIN_ID)
    _eval_chain(eval_store, data_root, EVAL_ID, MODEL_ID, model_version_number=1)
    finalize_model_evaluation(registry, MODEL_ID, eval_id=EVAL_ID)

    train2 = _train_chain(train_store, BUNDLED_TRAIN_ID, PROMPT_VERSION)
    register_model(
        registry,
        BUNDLED_MODEL_ID,
        train_id=BUNDLED_TRAIN_ID,
        artifacts=model_artifacts,
        deploy_target="artifacts/fold0/merged",
    )
    _eval_chain(eval_store, data_root, BUNDLED_EVAL_ID, BUNDLED_MODEL_ID, model_version_number=2)
    finalize_model_evaluation(registry, BUNDLED_MODEL_ID, eval_id=BUNDLED_EVAL_ID)

    _train_chain(train_store, UNSCOPED_TRAIN_ID, UNSCOPED_PROMPT_VERSION)
    register_model(registry, UNSCOPED_MODEL_ID, train_id=UNSCOPED_TRAIN_ID)
    _eval_chain(eval_store, data_root, UNSCOPED_EVAL_ID, UNSCOPED_MODEL_ID, model_version_number=3)
    finalize_model_evaluation(registry, UNSCOPED_MODEL_ID, eval_id=UNSCOPED_EVAL_ID)

    # 粘性备份范围（B8 前移状态）：r1→adapter，r2→production_bundle；r3 不设。
    set_offline_backup_scope(registry, MODEL_ID, "adapter")
    set_offline_backup_scope(registry, BUNDLED_MODEL_ID, "production_bundle")
    set_alias(registry, MODEL_ID, "candidate")

    # 作用域模型的真实 artifacts + 物化（模型备份源）。
    _log_train_artifacts(registry, train1.run_id, tmp_path)
    _log_train_artifacts(registry, train2.run_id, tmp_path)
    materialize_model(registry, MODEL_ID, models_root)
    materialize_model(registry, BUNDLED_MODEL_ID, models_root)
    export_model_manifest(
        prompts_root / "records" / "models" / MODEL_ID / "manifest.yaml",
        store=registry,
        model_id=MODEL_ID,
    )
    export_model_manifest(
        prompts_root / "records" / "models" / BUNDLED_MODEL_ID / "manifest.yaml",
        store=registry,
        model_id=BUNDLED_MODEL_ID,
    )

    return World(
        mlflow_root=registry.root,
        data_root=data_root,
        prompts_root=prompts_root,
        models_root=models_root,
    )


def _create_prompt_version(prompts_root: Path, version: str) -> None:
    create_prompt(
        prompts_root,
        "v4.1",
        version=version,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_PROMPT,
        output_fields=OUTPUT_FIELDS,
    )


def _seal_release(data_root: Path, version: str, *, round_name: str, description: str) -> None:
    """working → staging → releases：封存一个 development release。"""
    working = data_root / "working" / round_name
    (working / "media").mkdir(parents=True)
    (working / "media" / "clip.mp4").write_bytes(b"\x00\x01")
    stage_release(data_root, round_name, "v4.1", version=version)
    seal_release(
        data_root,
        version,
        purpose="development",
        description=description,
        sample_count=2,
        source_batches=["batch-2026-07"],
        splits={"fold0": {"train": 1, "validation": 1}},
    )


def _train_chain(train_store: TrainRecordStore, train_id: str, prompt_version: str):
    """三折 FINISHED + 汇总 + completed（B6 合法完成路径）。"""
    inputs: dict = dict(TRAIN_INPUTS_TEMPLATE)
    inputs["prompt_version"] = prompt_version
    create_train_run(train_store, train_id, **inputs)
    for fold in (0, 1, 2):
        create_fold_run(train_store, train_id, fold)
        log_fold_metrics(train_store, train_id, fold, TRAIN_FOLD_METRICS)
        end_fold_run(train_store, train_id, fold, "FINISHED")
    log_train_summary(train_store, train_id, TRAIN_SUMMARY_METRICS)
    return transition_train_state(train_store, train_id, "completed")


def _eval_chain(
    eval_store: EvalRecordStore,
    data_root: Path,
    eval_id: str,
    model_id: str,
    *,
    model_version_number: int,
):
    """single_fold 正式测评 completed + outcome=passed（B7 合法路径）。"""
    create_eval_run(
        eval_store,
        eval_id,
        model_id=model_id,
        model_version_number=model_version_number,
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
    return transition_eval_state(eval_store, eval_id, "completed", outcome="passed")


def _log_train_artifacts(store: ModelRegistryStore, run_id: str, tmp: Path) -> None:
    """向 train 父 Run 真实写入 ARTIFACT_FILES。"""
    client = MlflowClient(tracking_uri=store.tracking_uri)
    src = tmp / "train_artifacts"
    for rel, content in ARTIFACT_FILES.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        client.log_artifact(run_id, str(path), artifact_path=str(Path(rel).parent))


def _raw_aliases(registry: ModelRegistryStore, version: int) -> list[str]:
    """raw MLflow 数值版本的别名列表。

    get_model 快照不回填 aliases（search_model_versions 行为，
    test_registry.py 同型钉定），故直接读 raw 数值版本实体。
    """
    client = MlflowClient(tracking_uri=registry.tracking_uri)
    model_version = client.get_model_version(
        registry.registered_model, str(version)
    )
    return sorted(model_version.aliases)


def _source_args(world: World) -> dict:
    return {
        "data_root": world.data_root,
        "prompts_root": world.prompts_root,
        "models_root": world.models_root,
    }


def _backup_args(world: World, backup_root: Path) -> dict:
    args = _source_args(world)
    args["backup_root"] = backup_root
    return args


def _expected_source_map(world: World) -> dict[str, tuple[str, str, Path]]:
    """黄金世界源集合的 (object_type, scope, source) 权威映射。"""
    return {
        DATA_VERSION: (
            OBJECT_TYPE_DATA_RELEASE,
            SCOPE_DATA_RELEASE,
            world.data_root / "releases" / DATA_VERSION,
        ),
        EXTRA_DATA_VERSION: (
            OBJECT_TYPE_DATA_RELEASE,
            SCOPE_DATA_RELEASE,
            world.data_root / "releases" / EXTRA_DATA_VERSION,
        ),
        MODEL_ID: (OBJECT_TYPE_MODEL, "adapter", world.models_root / MODEL_ID),
        BUNDLED_MODEL_ID: (
            OBJECT_TYPE_MODEL,
            "production_bundle",
            world.models_root / BUNDLED_MODEL_ID,
        ),
        MLFLOW_STORE_OBJECT_ID: (OBJECT_TYPE_MLFLOW_STORE, SCOPE_MLFLOW_STORE, world.mlflow_root),
        PROMPT_VERSION: (
            OBJECT_TYPE_PROMPT,
            SCOPE_PROMPT,
            prompt_path(world.prompts_root, PROMPT_VERSION),
        ),
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _tree_digests(root: Path) -> dict[str, str]:
    """树内全部文件的 SHA-256（相对 POSIX 路径 -> 摘要）。"""
    return {
        path.relative_to(root).as_posix(): _sha256_bytes(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _tree_files(root: Path) -> set[str]:
    """树内全部文件的相对 POSIX 路径集合。"""
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _stable_entry(entry: BackupObjectEntry) -> tuple:
    """剔除 backed_up_at 后的确定性 catalog 条目（决策点 4）。"""
    return (
        entry.object_id,
        entry.object_type,
        entry.scope,
        entry.source,
        entry.verified,
        entry.byte_size,
        entry.sha256,
        tuple(entry.files),
    )


def _stable_entries(catalog: BackupCatalog) -> tuple[tuple, ...]:
    return tuple(_stable_entry(entry) for entry in catalog.objects)


def _entry(catalog: BackupCatalog, object_id: str) -> BackupObjectEntry:
    matches = [entry for entry in catalog.objects if entry.object_id == object_id]
    assert len(matches) == 1, f"catalog 中 {object_id!r} 应恰有一行: {matches}"
    return matches[0]


def _expected_backup_files(backup_root: Path, catalog: BackupCatalog) -> set[str]:
    """backup_root 应存在的精确文件集合：catalog 文件 + catalog + 可选 .prev。"""
    expected = {BACKUP_CATALOG_FILENAME}
    if (backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME).is_file():
        expected.add(BACKUP_CATALOG_SNAPSHOT_FILENAME)
    for entry in catalog.objects:
        expected.update(file_entry.path for file_entry in entry.files)
    return expected


def _object_rel(entry: BackupObjectEntry, backup_rel: str) -> str:
    """把 backup_root 相对文件路径换算为对象源目录内的相对路径。"""
    if entry.object_type == OBJECT_TYPE_PROMPT:
        return Path(backup_rel).name
    prefix_by_type = {
        OBJECT_TYPE_DATA_RELEASE: BACKUP_DIR_DATA,
        OBJECT_TYPE_MODEL: BACKUP_DIR_MODELS,
        OBJECT_TYPE_MLFLOW_STORE: BACKUP_DIR_MLFLOW,
    }
    assert entry.object_type in prefix_by_type, entry.object_type
    object_prefix = f"{prefix_by_type[entry.object_type]}/{entry.object_id}"
    if entry.object_type == OBJECT_TYPE_MLFLOW_STORE:
        object_prefix = BACKUP_DIR_MLFLOW
    assert backup_rel.startswith(f"{object_prefix}/"), backup_rel
    return backup_rel[len(object_prefix) + 1:]


def _assert_backup_bytes_match_source(backup_root: Path, entry: BackupObjectEntry) -> None:
    """真实复制校验：备份对象与源对象逐字节一致（mlflow.db 见决策点 5）。"""
    if entry.object_type == OBJECT_TYPE_DATA_RELEASE:
        expected = _tree_digests(Path(entry.source))
        actual = _tree_digests(backup_root / BACKUP_DIR_DATA / entry.object_id)
        assert actual == expected
    elif entry.object_type == OBJECT_TYPE_PROMPT:
        backup_file = backup_root / BACKUP_DIR_PROMPTS / f"{entry.object_id}.yaml"
        assert backup_file.read_bytes() == Path(entry.source).read_bytes()
    elif entry.object_type == OBJECT_TYPE_MODEL:
        metadata = yaml.safe_load(
            (Path(entry.source) / MATERIALIZED_METADATA_FILE).read_text(encoding="utf-8")
        )
        for file_entry in entry.files:
            relative = _object_rel(entry, file_entry.path)
            if relative == "manifest.yaml":
                source_file = Path(entry.source).parent.parent / metadata["manifest"]
            else:
                source_file = Path(entry.source) / relative
            assert source_file.is_file()
            assert _sha256_bytes(source_file.read_bytes()) == file_entry.sha256
    elif entry.object_type == OBJECT_TYPE_MLFLOW_STORE:
        source_files = _tree_digests(Path(entry.source))
        backup_files = _tree_digests(backup_root / BACKUP_DIR_MLFLOW)
        assert set(backup_files) <= set(source_files)
        assert "mlflow.db" in backup_files
        for rel, sha in backup_files.items():
            if rel == "mlflow.db":
                continue  # 一致性快照允许字节不同，有效性由 SQLite 查询钉定
            assert source_files[rel] == sha, rel
        connection = sqlite3.connect(backup_root / BACKUP_DIR_MLFLOW / "mlflow.db")
        try:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] > 0
        finally:
            connection.close()
    else:  # pragma: no cover - 值域由 schema 校验钉定
        raise AssertionError(f"未知对象类型: {entry.object_type!r}")


def _make_writable(path: Path) -> None:
    """给单个文件补写位（封存 payload / 保模式副本可能只读）。"""
    os.chmod(path, path.stat().st_mode | 0o200)


def _make_writable_dir(path: Path) -> None:
    """给目录补 owner 写+执行位（在只读目录内增删文件用）。"""
    os.chmod(path, path.stat().st_mode | 0o300)


def _force_writable(path: Path) -> None:
    """递归补写位后置空（rmtree 只读 release 树用）。"""
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        os.chmod(child, child.stat().st_mode | 0o222)
    os.chmod(path, path.stat().st_mode | 0o222)


def _assert_sqlite_readable(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] > 0
    finally:
        connection.close()


def _assert_sqlite_valid_zero_runs(db_path: Path) -> None:
    """空 store 快照钉定：可查询的有效 SQLite，runs 表存在但为空。"""
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    finally:
        connection.close()


def _payload_stats(
    backup_root: Path, catalog: BackupCatalog
) -> dict[str, dict[str, tuple[int, int]]]:
    """object_id -> {catalog 相对路径: (st_ino, st_mtime_ns)}。

    用于钉定“健康对象不被重拷”：重拷必然产生新 inode（临时树在旧目录仍
    占位时创建），因此 inode/mtime 不变 ⇔ 未重拷。
    """
    stats: dict[str, dict[str, tuple[int, int]]] = {}
    for entry in catalog.objects:
        per_object: dict[str, tuple[int, int]] = {}
        for file_entry in entry.files:
            stat = (Path(backup_root) / file_entry.path).stat()
            per_object[file_entry.path] = (stat.st_ino, stat.st_mtime_ns)
        stats[entry.object_id] = per_object
    return stats


def _install_copy_spies(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Path]]
) -> None:
    """记录全部真实复制调用的目标路径（树复制 + 单文件复制）。"""
    original_tree = backup_module._copy_tree_atomic_replace
    original_selected_tree = backup_module._copy_selected_tree_atomic_replace
    original_file = backup_module._copy_file_preserve

    def tree_spy(src: Path, dst: Path) -> None:
        calls["tree"].append(Path(dst))
        original_tree(src, dst)

    def file_spy(src: Path, dst: Path) -> None:
        calls["file"].append(Path(dst))
        original_file(src, dst)

    def selected_tree_spy(source: BackupSource, dst: Path) -> None:
        calls["tree"].append(Path(dst))
        original_selected_tree(source, dst)

    monkeypatch.setattr(backup_module, "_copy_tree_atomic_replace", tree_spy)
    monkeypatch.setattr(
        backup_module, "_copy_selected_tree_atomic_replace", selected_tree_spy
    )
    monkeypatch.setattr(backup_module, "_copy_file_preserve", file_spy)


def _install_mlflow_copy_corruption(
    monkeypatch: pytest.MonkeyPatch, backup_root: Path
) -> None:
    """真实复制完成后摧毁备份副本 mlflow.db 的 SQLite 头，模拟备份介质位腐。

    钩子包在 _copy_tree_atomic_replace 外层：复制与临时副本校验照常成功，
    仅备份盘上的 mlflow.db 头 16 字节（"SQLite format 3\\0" 魔数）被清零，
    大小不变、sha 与 catalog 条目自洽 → 只有落盘前的 SQLite PRAGMA
    integrity_check / 可查询性校验能拒绝它。
    """
    original_tree = backup_module._copy_selected_tree_atomic_replace
    mlflow_dst = Path(backup_root) / BACKUP_DIR_MLFLOW

    def corrupting_copy(source: BackupSource, dst: Path) -> None:
        original_tree(source, dst)
        if Path(dst) == mlflow_dst:
            db_path = mlflow_dst / "mlflow.db"
            _make_writable(db_path)
            data = bytearray(db_path.read_bytes())
            data[:16] = b"\x00" * 16
            db_path.write_bytes(bytes(data))

    monkeypatch.setattr(
        backup_module, "_copy_selected_tree_atomic_replace", corrupting_copy
    )


# —————————————————— T1 契约常量 ——————————————————


class TestBackupContract:
    """模块契约：常量、异常层级与 backup_catalog.yaml 顶层 schema 钉定。"""

    def test_contract_constants_pinned(self) -> None:
        assert BACKUP_CATALOG_FILENAME == "backup_catalog.yaml"
        assert BACKUP_CATALOG_SNAPSHOT_FILENAME == "backup_catalog.yaml.prev"
        assert BACKUP_CATALOG_VERSION == 1
        assert MLFLOW_STORE_OBJECT_ID == "mlflow-store"
        assert (
            OBJECT_TYPE_DATA_RELEASE,
            OBJECT_TYPE_PROMPT,
            OBJECT_TYPE_MODEL,
            OBJECT_TYPE_MLFLOW_STORE,
        ) == ("data_release", "prompt", "model", "mlflow_store")
        assert (
            SCOPE_DATA_RELEASE,
            SCOPE_PROMPT,
            SCOPE_MLFLOW_STORE,
        ) == ("data", "prompt", "mlflow_store")
        assert (
            BACKUP_DIR_DATA,
            BACKUP_DIR_PROMPTS,
            BACKUP_DIR_MODELS,
            BACKUP_DIR_MLFLOW,
        ) == ("data", "prompts", "models", "mlflow")
        # 异常层级：全部备份域异常共用 BackupError（ValueError 子类）
        assert issubclass(BackupError, ValueError)
        for exc in (
            BackupSourceSetError,
            CatalogSchemaError,
            BackupIntegrityError,
            RestoreTargetConflict,
        ):
            assert issubclass(exc, BackupError)


# —————————————————— T2 源集合枚举 ——————————————————


class TestEnumerateBackupSources:
    """enumerate_backup_sources：全部正式数据 + 作用域模型 + 其 prompt + MLflow store。"""

    def test_enumerate_full_source_set(
        self, world: World, registry: ModelRegistryStore
    ) -> None:
        sources = enumerate_backup_sources(registry, **_source_args(world))

        assert isinstance(sources, tuple)
        ids = [source.object_id for source in sources]
        assert set(ids) == set(EXPECTED_OBJECT_IDS)
        assert len(sources) == len(EXPECTED_OBJECT_IDS)

        expected = _expected_source_map(world)
        for source in sources:
            object_type, scope, source_path = expected[source.object_id]
            assert source.object_type == object_type, source.object_id
            assert source.scope == scope, source.object_id
            assert isinstance(source.source, Path), source.object_id
            assert source.source == source_path, source.object_id

    def test_enumerate_excludes_unscoped_unreferenced_and_working(
        self, world: World, registry: ModelRegistryStore
    ) -> None:
        ids = {source.object_id for source in enumerate_backup_sources(registry, **_source_args(world))}

        # 未设 offline_backup_scope 的模型不进源集合（§2.11：范围 tag 决定）
        assert UNSCOPED_MODEL_ID not in ids
        # 无人引用的 prompt 不进源集合
        assert UNREFERENCED_PROMPT_VERSION not in ids
        # 只被未设范围模型引用的 prompt 不进源集合（身份资料随作用域走）
        assert UNSCOPED_PROMPT_VERSION not in ids

        # working 中未封存数据不进源集合（§2.2：可重建对象不备份）
        scratch = world.data_root / "working" / "round-scratch"
        (scratch / "media").mkdir(parents=True)
        (scratch / "media" / "clip.mp4").write_bytes(b"\x00\x02")
        again = enumerate_backup_sources(registry, **_source_args(world))
        assert {source.object_id for source in again} == ids

    def test_enumerate_is_deterministic(
        self, world: World, registry: ModelRegistryStore
    ) -> None:
        first = enumerate_backup_sources(registry, **_source_args(world))
        second = enumerate_backup_sources(registry, **_source_args(world))
        assert first == second
        ids = [source.object_id for source in first]
        assert ids == sorted(ids)

    def test_enumerate_scope_tag_drives_not_alias(
        self, world: World, registry: ModelRegistryStore
    ) -> None:
        args = _source_args(world)
        before = enumerate_backup_sources(registry, **args)

        # 前提：r1 持有 candidate；r2 无任何 alias 也按 tag 进源集合
        assert _raw_aliases(registry, 1) == ["candidate"]
        assert _raw_aliases(registry, 2) == []

        # candidate 切到另一模型：r1 失去 alias，但历史最高范围不降级、
        # 不退出源集合（§2.11：不得依据当前 alias 反推历史角色）
        set_alias(registry, BUNDLED_MODEL_ID, "candidate")
        assert _raw_aliases(registry, 1) == []
        assert _raw_aliases(registry, 2) == ["candidate"]

        after = enumerate_backup_sources(registry, **args)
        assert after == before

    def test_enumerate_missing_source_fail_closed(
        self, world: World, registry: ModelRegistryStore
    ) -> None:
        args = _source_args(world)

        # 作用域模型未物化：源集合 fail-closed，不静默跳过
        shutil.rmtree(world.models_root / MODEL_ID)
        with pytest.raises(BackupSourceSetError):
            enumerate_backup_sources(registry, **args)

        # 重新物化后恢复
        materialize_model(registry, MODEL_ID, world.models_root)
        enumerate_backup_sources(registry, **args)

        # 作用域模型引用的 prompt（完整身份资料）缺失同样 fail-closed
        prompt_file = prompt_path(world.prompts_root, PROMPT_VERSION)
        prompt_file.unlink()
        with pytest.raises(BackupSourceSetError):
            enumerate_backup_sources(registry, **args)

        # 身份资料补齐后恢复，prompt 回到源集合
        _create_prompt_version(world.prompts_root, PROMPT_VERSION)
        sources = enumerate_backup_sources(registry, **args)
        assert PROMPT_VERSION in {source.object_id for source in sources}

    def test_enumerate_stale_materialized_scope_fail_closed(
        self, world: World, registry: ModelRegistryStore
    ) -> None:
        args = _source_args(world)

        # scope 升级后未重新物化：物化声明的 offline_backup_scope 与
        # Registry tag 分歧 → 身份资料对应关系校验 fail-closed
        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        with pytest.raises(BackupSourceSetError):
            enumerate_backup_sources(registry, **args)

        # 重物化刷新声明后，按历史最高范围进入源集合
        materialize_model(registry, MODEL_ID, world.models_root)
        sources = enumerate_backup_sources(registry, **args)
        model_source = next(
            source for source in sources if source.object_id == MODEL_ID
        )
        assert model_source.scope == "production_bundle"

    def test_enumerate_rejects_dangling_model_manifest(
        self, world: World, registry: ModelRegistryStore
    ) -> None:
        manifest = (
            world.prompts_root / "records" / "models" / MODEL_ID / "manifest.yaml"
        )
        manifest.unlink()
        with pytest.raises(BackupSourceSetError, match="manifest 缺失"):
            enumerate_backup_sources(registry, **_source_args(world))


# —————————————————— T3 备份生成与 catalog ——————————————————


class TestCreateBackup:
    """create_backup：真实复制、确定性 catalog、原子替换 + 上一份快照、单向性。"""

    def test_missing_declared_model_artifact_is_zero_side_effect_failure(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        shutil.rmtree(
            world.models_root / MODEL_ID / "artifacts" / "fold0" / "adapter"
        )
        with pytest.raises(BackupSourceSetError, match="声明 artifact"):
            create_backup(registry, **_backup_args(world, backup_root))
        assert not backup_root.exists()

    def test_scope_upgrade_cannot_interleave_with_registry_snapshot(
        self,
        world: World,
        registry: ModelRegistryStore,
        backup_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = backup_module._repair_or_copy
        upgrade_errors: list[Exception] = []
        upgrade_thread: threading.Thread | None = None

        def upgrade() -> None:
            try:
                set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
            except Exception as exc:  # pragma: no cover - 断言负责暴露线程异常
                upgrade_errors.append(exc)

        def intercept(source, root, existing):
            nonlocal upgrade_thread
            if source.object_id == MLFLOW_STORE_OBJECT_ID:
                upgrade_thread = threading.Thread(target=upgrade)
                upgrade_thread.start()
                upgrade_thread.join(timeout=0.2)
                assert upgrade_thread.is_alive(), "scope 写入绕过了备份快照锁"
            return original(source, root, existing)

        monkeypatch.setattr(backup_module, "_repair_or_copy", intercept)
        catalog = create_backup(registry, **_backup_args(world, backup_root))
        assert upgrade_thread is not None
        upgrade_thread.join(timeout=5)
        assert not upgrade_thread.is_alive()
        assert upgrade_errors == []
        assert _entry(catalog, MODEL_ID).scope == "adapter"

        connection = sqlite3.connect(backup_root / BACKUP_DIR_MLFLOW / "mlflow.db")
        try:
            scopes = {
                row[0]
                for row in connection.execute(
                    "SELECT value FROM model_version_tags "
                    "WHERE key = 'offline_backup_scope'"
                )
            }
        finally:
            connection.close()
        assert scopes == {"adapter", "production_bundle"}

    def test_create_backup_copies_objects_and_builds_catalog(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        catalog = create_backup(registry, **_backup_args(world, backup_root))

        ids = [entry.object_id for entry in catalog.objects]
        assert set(ids) == set(EXPECTED_OBJECT_IDS)
        assert ids == sorted(ids)  # 对象清单确定性排序

        for entry in catalog.objects:
            assert entry.verified is True, entry.object_id
            assert entry.byte_size == sum(
                file_entry.byte_size for file_entry in entry.files
            )
            paths = [file_entry.path for file_entry in entry.files]
            assert paths == sorted(paths)  # 文件清单确定性排序
            assert len(paths) > 0
            for file_entry in entry.files:
                backup_file = backup_root / file_entry.path
                assert backup_file.is_file(), file_entry.path
                assert backup_file.stat().st_size == file_entry.byte_size
                # SHA-256 可在盘上复算（§2.11 机器完整性校验）
                assert _sha256_bytes(backup_file.read_bytes()) == file_entry.sha256
            # 真实复制：备份对象与源对象逐字节一致（决策点 2/5）
            _assert_backup_bytes_match_source(backup_root, entry)

        # 备份范围按历史最高 scope tag
        assert _entry(catalog, MODEL_ID).scope == "adapter"
        assert _entry(catalog, BUNDLED_MODEL_ID).scope == "production_bundle"
        adapter_paths = {file.path for file in _entry(catalog, MODEL_ID).files}
        bundled_paths = {
            file.path for file in _entry(catalog, BUNDLED_MODEL_ID).files
        }
        assert not any("/merged/" in path for path in adapter_paths)
        assert any("/adapter/" in path for path in adapter_paths)
        assert any("/merged/" in path for path in bundled_paths)

        client = MlflowClient(tracking_uri=registry.tracking_uri)
        adapter_run_id = get_train_run(open_train_store(registry.root), TRAIN_ID).run_id
        bundled_run_id = get_train_run(
            open_train_store(registry.root), BUNDLED_TRAIN_ID
        ).run_id
        adapter_artifact_root = Path(
            client.get_run(adapter_run_id).info.artifact_uri.removeprefix("file://")
        )
        bundled_artifact_root = Path(
            client.get_run(bundled_run_id).info.artifact_uri.removeprefix("file://")
        )
        adapter_merged = (
            adapter_artifact_root / "fold0" / "merged"
        ).relative_to(registry.root)
        bundled_merged = (
            bundled_artifact_root / "fold0" / "merged"
        ).relative_to(registry.root)
        assert not (backup_root / BACKUP_DIR_MLFLOW / adapter_merged).exists()
        assert (backup_root / BACKUP_DIR_MLFLOW / bundled_merged).is_dir()
        assert _entry(catalog, DATA_VERSION).scope == SCOPE_DATA_RELEASE
        assert _entry(catalog, PROMPT_VERSION).scope == SCOPE_PROMPT
        assert _entry(catalog, MLFLOW_STORE_OBJECT_ID).scope == SCOPE_MLFLOW_STORE

        # MLflow SQLite 一致性快照：可查询的有效 SQLite（决策点 5）
        _assert_sqlite_readable(backup_root / BACKUP_DIR_MLFLOW / "mlflow.db")

        # 盘上文件集合精确等于 catalog 声明（首次备份，无 .prev、无残留）
        assert _tree_files(backup_root) == _expected_backup_files(backup_root, catalog)

    def test_create_backup_catalog_yaml_schema(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        created = create_backup(registry, **_backup_args(world, backup_root))

        payload = yaml.safe_load(
            (backup_root / BACKUP_CATALOG_FILENAME).read_text(encoding="utf-8")
        )
        assert set(payload) == {"catalog_version", "objects"}
        assert payload["catalog_version"] == BACKUP_CATALOG_VERSION
        objects = payload["objects"]
        assert isinstance(objects, list)
        assert len(objects) == len(EXPECTED_OBJECT_IDS)

        assert [raw["object_id"] for raw in objects] == sorted(
            raw["object_id"] for raw in objects
        )
        for raw in objects:
            assert set(raw) == OBJECT_KEYS
            assert raw["verified"] is True
            assert isinstance(raw["source"], str) and raw["source"]
            # 备份时间可解析（§2.11 catalog 至少记录对象 ID/类型/来源/时间/范围/verified）
            datetime.datetime.fromisoformat(raw["backed_up_at"])
            assert isinstance(raw["files"], list) and raw["files"]
            assert raw["byte_size"] == sum(
                raw_file["byte_size"] for raw_file in raw["files"]
            )
            assert _is_sha256(raw["sha256"])
            file_paths = [raw_file["path"] for raw_file in raw["files"]]
            assert file_paths == sorted(file_paths)
            for raw_file in raw["files"]:
                assert set(raw_file) == FILE_KEYS
                assert _is_sha256(raw_file["sha256"])

        # source 字段 = 来源绝对路径字符串
        by_id = {raw["object_id"]: raw for raw in objects}
        assert by_id[DATA_VERSION]["source"] == str(
            world.data_root / "releases" / DATA_VERSION
        )
        assert by_id[PROMPT_VERSION]["source"] == str(
            prompt_path(world.prompts_root, PROMPT_VERSION)
        )
        assert by_id[MODEL_ID]["source"] == str(world.models_root / MODEL_ID)
        assert by_id[MLFLOW_STORE_OBJECT_ID]["source"] == str(world.mlflow_root)

        # load_backup_catalog 与 create_backup 返回值等值（往返一致）
        assert load_backup_catalog(backup_root) == created

    def test_create_backup_deterministic_catalog(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        first = create_backup(registry, **_backup_args(world, backup_root))
        second = create_backup(registry, **_backup_args(world, backup_root))

        # 决策点 4：对象清单/字节数/SHA-256 确定；仅 backed_up_at 允许变化
        assert _stable_entries(second) == _stable_entries(first)
        assert _stable_entries(load_backup_catalog(backup_root)) == _stable_entries(first)

    def test_create_backup_preserves_sources(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        before = {
            "data": _tree_digests(world.data_root),
            "prompts": _tree_digests(world.prompts_root / "records"),
            "models": _tree_digests(world.models_root),
            "artifacts": _tree_digests(world.mlflow_root / "artifacts"),
            "mlflow_db": _sha256_bytes((world.mlflow_root / "mlflow.db").read_bytes()),
        }

        create_backup(registry, **_backup_args(world, backup_root))

        # 单向性：备份生成不修改源对象（含源 SQLite 字节），成功也不删源
        assert _tree_digests(world.data_root) == before["data"]
        assert _tree_digests(world.prompts_root / "records") == before["prompts"]
        assert _tree_digests(world.models_root) == before["models"]
        assert _tree_digests(world.mlflow_root / "artifacts") == before["artifacts"]
        assert (
            _sha256_bytes((world.mlflow_root / "mlflow.db").read_bytes())
            == before["mlflow_db"]
        )
        assert load_release_metadata(world.data_root, DATA_VERSION).version == DATA_VERSION
        assert load_prompt(world.prompts_root, PROMPT_VERSION).version == PROMPT_VERSION
        assert get_model(registry, MODEL_ID).model_id == MODEL_ID

    def test_create_backup_atomic_replace_with_prev_snapshot(
        self,
        world: World,
        registry: ModelRegistryStore,
        backup_root: Path,
        data_root: Path,
    ) -> None:
        first = create_backup(registry, **_backup_args(world, backup_root))
        first_catalog_bytes = (backup_root / BACKUP_CATALOG_FILENAME).read_bytes()
        assert not (backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME).exists()

        # 世界演进：新增第三个正式 release → 下次运行进入待备份集合
        _seal_release(
            data_root,
            THIRD_DATA_VERSION,
            round_name="round-c",
            description="原子替换测试第三正式版本",
        )

        second = create_backup(registry, **_backup_args(world, backup_root))
        assert set(EXPECTED_OBJECT_IDS | {THIRD_DATA_VERSION}) == {
            entry.object_id for entry in second.objects
        }
        assert _entry(second, THIRD_DATA_VERSION).byte_size > 0

        # catalog 临时文件校验通过后原子替换，并保留上一份可读快照（原文）
        snapshot = backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME
        assert snapshot.is_file()
        assert snapshot.read_bytes() == first_catalog_bytes
        snapshot_payload = yaml.safe_load(snapshot.read_text(encoding="utf-8"))
        assert set(snapshot_payload) == {"catalog_version", "objects"}
        assert {raw["object_id"] for raw in snapshot_payload["objects"]} == set(
            EXPECTED_OBJECT_IDS
        )
        assert (backup_root / BACKUP_CATALOG_FILENAME).read_bytes() != first_catalog_bytes

        # 每次运行复验全部既有对象：新 catalog 下整盘复验通过
        assert verify_backup(backup_root)
        for entry in second.objects:
            _assert_backup_bytes_match_source(backup_root, entry)

        # 无临时文件残留：盘上文件集合与 catalog + 快照精确一致
        assert _tree_files(backup_root) == _expected_backup_files(backup_root, second)

    def test_create_backup_failure_leaves_catalog_unchanged(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        create_backup(registry, **_backup_args(world, backup_root))
        catalog_bytes = (backup_root / BACKUP_CATALOG_FILENAME).read_bytes()
        files_before = _tree_files(backup_root)

        # 世界失效：作用域模型物化目录被删 → 源集合枚举 fail-closed
        shutil.rmtree(world.models_root / BUNDLED_MODEL_ID)
        with pytest.raises(BackupSourceSetError):
            create_backup(registry, **_backup_args(world, backup_root))

        # 失败运行不得改写盘上既有 catalog，也不留任何半成品
        assert (backup_root / BACKUP_CATALOG_FILENAME).read_bytes() == catalog_bytes
        assert _tree_files(backup_root) == files_before


# —————————————————— T4 一致性校验 fail-closed ——————————————————


class TestVerifyBackup:
    """verify/restore 的完整性门：篡改/缺失/额外对象、损坏 catalog 均拒绝。"""

    def test_verify_backup_positive(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        created = create_backup(registry, **_backup_args(world, backup_root))

        verified = verify_backup(backup_root)

        assert isinstance(verified, BackupCatalog)
        assert _stable_entries(verified) == _stable_entries(created)
        assert all(entry.verified is True for entry in verified.objects)

    @pytest.mark.parametrize(
        "corruption",
        ["tamper", "missing", "extra_top", "extra_deep"],
    )
    def test_integrity_violations_fail_closed(
        self,
        world: World,
        registry: ModelRegistryStore,
        backup_root: Path,
        tmp_path: Path,
        corruption: str,
    ) -> None:
        catalog = create_backup(registry, **_backup_args(world, backup_root))
        entry = _entry(catalog, MODEL_ID)
        victim = backup_root / entry.files[0].path

        if corruption == "tamper":
            _make_writable(victim)
            victim.write_bytes(b"TAMPERED-BY-ATTACK")
        elif corruption == "missing":
            victim.unlink()
        elif corruption == "extra_top":
            (backup_root / "rogue.bin").write_bytes(b"rogue")
        else:  # extra_deep：catalog 外文件混进对象目录
            parent = victim.parent
            _make_writable_dir(parent)
            (parent / "sneaky.bin").write_bytes(b"rogue")

        # D036：catalog 存在一行不能证明备份存在；篡改/缺失/额外对象一律拒绝
        with pytest.raises(BackupIntegrityError):
            verify_backup(backup_root)

        # 恢复同样先校验：失败零副作用（目标目录不得被创建）
        fresh = tmp_path / "fresh"
        with pytest.raises(BackupIntegrityError):
            restore_backup(
                backup_root,
                data_root=fresh / "data",
                prompts_root=fresh,
                models_root=fresh / "models",
                mlflow_root=fresh / "mlflow",
            )
        assert not fresh.exists()

    def test_corrupt_catalog_fail_closed_but_rebuildable(
        self,
        world: World,
        registry: ModelRegistryStore,
        backup_root: Path,
        tmp_path: Path,
    ) -> None:
        created = create_backup(registry, **_backup_args(world, backup_root))
        catalog_file = backup_root / BACKUP_CATALOG_FILENAME
        original_bytes = catalog_file.read_bytes()

        # 1) 非 YAML 垃圾：读取/校验/恢复 fail-closed
        catalog_file.write_bytes(b"::: not a backup catalog :::")
        with pytest.raises(CatalogSchemaError):
            load_backup_catalog(backup_root)
        with pytest.raises(CatalogSchemaError):
            verify_backup(backup_root)
        fresh = tmp_path / "fresh"
        with pytest.raises(CatalogSchemaError):
            restore_backup(
                backup_root,
                data_root=fresh / "data",
                prompts_root=fresh,
                models_root=fresh / "models",
                mlflow_root=fresh / "mlflow",
            )
        assert not fresh.exists()

        # 2) YAML 但 schema 非法（对象缺 sha256）：同样 fail-closed
        payload = yaml.safe_load(original_bytes)
        del payload["objects"][0]["sha256"]
        catalog_file.write_text(yaml.safe_dump(payload), encoding="utf-8")
        with pytest.raises(CatalogSchemaError):
            load_backup_catalog(backup_root)

        # 3) catalog 损坏不阻断备份：按源集合 + 硬盘对象目录重新扫描生成
        rebuilt = create_backup(registry, **_backup_args(world, backup_root))
        assert _stable_entries(rebuilt) == _stable_entries(created)
        assert verify_backup(backup_root)


# —————————————————— T5 修复与范围升级重备份 ——————————————————


class TestRepairAndScopeUpgrade:
    """下一次备份修复完整性失败项；scope 升级按历史最高范围重备份。"""

    def test_next_backup_repairs_tampered_file(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        first = create_backup(registry, **_backup_args(world, backup_root))
        entry = _entry(first, MODEL_ID)
        file_entry = entry.files[0]
        victim = backup_root / file_entry.path
        source_file = Path(entry.source) / _object_rel(entry, file_entry.path)
        expected = source_file.read_bytes()

        _make_writable(victim)
        victim.write_bytes(b"CORRUPTED")
        with pytest.raises(BackupIntegrityError):
            verify_backup(backup_root)

        # D036：完整性失败项进入修复/重备份集合，从源重复制
        second = create_backup(registry, **_backup_args(world, backup_root))
        assert victim.read_bytes() == expected
        assert verify_backup(backup_root)
        assert _stable_entries(second) == _stable_entries(first)

    def test_next_backup_repairs_missing_file(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        first = create_backup(registry, **_backup_args(world, backup_root))
        entry = _entry(first, MODEL_ID)
        file_entry = entry.files[0]
        victim = backup_root / file_entry.path
        source_file = Path(entry.source) / _object_rel(entry, file_entry.path)
        expected = source_file.read_bytes()

        victim.unlink()
        with pytest.raises(BackupIntegrityError):
            verify_backup(backup_root)

        second = create_backup(registry, **_backup_args(world, backup_root))
        assert victim.is_file()
        assert victim.read_bytes() == expected
        assert verify_backup(backup_root)
        assert _stable_entries(second) == _stable_entries(first)

    def test_scope_upgrade_rebackup_at_highest_scope(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        first = create_backup(registry, **_backup_args(world, backup_root))
        assert _entry(first, MODEL_ID).scope == "adapter"

        # 范围升级但未重物化：身份资料与 Registry 分歧 → fail-closed
        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        with pytest.raises(BackupSourceSetError):
            create_backup(registry, **_backup_args(world, backup_root))

        # 重物化刷新声明后重备份：catalog 按历史最高范围记录，盘上同步
        materialize_model(registry, MODEL_ID, world.models_root)
        second = create_backup(registry, **_backup_args(world, backup_root))
        assert _entry(second, MODEL_ID).scope == "production_bundle"
        backup_metadata = yaml.safe_load(
            (
                backup_root
                / BACKUP_DIR_MODELS
                / MODEL_ID
                / MATERIALIZED_METADATA_FILE
            ).read_text(encoding="utf-8")
        )
        assert backup_metadata["offline_backup_scope"] == "production_bundle"
        assert verify_backup(backup_root)

        # 上一份可读快照保留升级前（adapter）的 catalog 声明
        snapshot_payload = yaml.safe_load(
            (backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME).read_text(
                encoding="utf-8"
            )
        )
        snapshot_entry = next(
            raw
            for raw in snapshot_payload["objects"]
            if raw["object_id"] == MODEL_ID
        )
        assert snapshot_entry["scope"] == "adapter"

    def test_extra_file_not_silently_removed(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        create_backup(registry, **_backup_args(world, backup_root))

        rogue = backup_root / "uninvited.bin"
        rogue.write_bytes(b"stray")

        # 额外对象：fail-closed，绝不静默删除盘上文件
        with pytest.raises(BackupIntegrityError):
            create_backup(registry, **_backup_args(world, backup_root))
        assert rogue.read_bytes() == b"stray"


# —————————————————— T6 恢复与自愈 ——————————————————


class TestRestoreBackup:
    """restore_backup：灾难恢复后可用既有模块重开；零副作用；拒绝覆盖。"""

    def test_restore_disaster_recovery_reopens_everything(
        self, world: World, registry: ModelRegistryStore, backup_root: Path, tmp_path: Path
    ) -> None:
        # 恢复前把 r2 升为 production（alias 路由纳入备份/恢复验证）
        approve_model_for_production(registry, BUNDLED_MODEL_ID)
        set_alias(registry, BUNDLED_MODEL_ID, "production")

        catalog = create_backup(registry, **_backup_args(world, backup_root))
        assert set(EXPECTED_OBJECT_IDS) == {
            entry.object_id for entry in catalog.objects
        }

        # 灾难前快照：字节级期望 + train 父 Run ID（artifact 自愈验证用）
        release_digests = _tree_digests(world.data_root / "releases" / DATA_VERSION)
        model_digests = {
            path: digest
            for path, digest in _tree_digests(
                backup_root / BACKUP_DIR_MODELS / MODEL_ID
            ).items()
            if path != "manifest.yaml"
        }
        artifact_digests = _tree_digests(backup_root / BACKUP_DIR_MLFLOW / "artifacts")
        prompt_bytes = prompt_path(world.prompts_root, PROMPT_VERSION).read_bytes()
        train_run_id = get_train_run(
            open_train_store(world.mlflow_root), TRAIN_ID
        ).run_id

        # 灾难：删除训练机侧全部正式对象（只读 release 树先补写位）
        for target in (
            world.mlflow_root,
            world.data_root,
            world.models_root,
            tmp_path / "records",
        ):
            _force_writable(target)
            shutil.rmtree(target)
        assert not (world.data_root / "releases" / DATA_VERSION).exists()
        assert not (world.mlflow_root / "mlflow.db").exists()
        assert not prompt_path(world.prompts_root, PROMPT_VERSION).exists()

        # 恢复到原绝对路径（决策点 8：SQLite 内 artifact URI 为绝对路径）
        restore_backup(
            backup_root,
            data_root=world.data_root,
            prompts_root=world.prompts_root,
            models_root=world.models_root,
            mlflow_root=world.mlflow_root,
        )

        # ——— data：release 可重开，封存态与字节同构 ———
        meta = load_release_metadata(world.data_root, DATA_VERSION)
        assert meta.purpose == "development"
        assert meta.sample_count == 2
        assert (
            load_release_metadata(world.data_root, EXTRA_DATA_VERSION).version
            == EXTRA_DATA_VERSION
        )
        assert_payload_sealed(world.data_root / "releases" / DATA_VERSION)
        assert (
            _tree_digests(world.data_root / "releases" / DATA_VERSION)
            == release_digests
        )

        # ——— prompt：可重开；catalog 外对象不被恢复 ———
        restored_prompt = load_prompt(world.prompts_root, PROMPT_VERSION)
        assert restored_prompt.version == PROMPT_VERSION
        assert restored_prompt.system_prompt == SYSTEM_PROMPT
        assert (
            prompt_path(world.prompts_root, PROMPT_VERSION).read_bytes()
            == prompt_bytes
        )
        assert not prompt_path(
            world.prompts_root, UNREFERENCED_PROMPT_VERSION
        ).exists()
        assert not prompt_path(world.prompts_root, UNSCOPED_PROMPT_VERSION).exists()

        # ——— model：物化目录同构，备份范围声明保留 ———
        assert _tree_digests(world.models_root / MODEL_ID) == model_digests
        metadata = yaml.safe_load(
            (world.models_root / MODEL_ID / MATERIALIZED_METADATA_FILE).read_text(
                encoding="utf-8"
            )
        )
        assert metadata["model_id"] == MODEL_ID
        assert metadata["offline_backup_scope"] == "adapter"
        assert not (world.models_root / UNSCOPED_MODEL_ID).exists()
        restored_manifest = (
            world.prompts_root / "records" / "models" / MODEL_ID / "manifest.yaml"
        )
        assert validate_model_manifest(restored_manifest.read_text(encoding="utf-8"))[
            "version"
        ] == MODEL_ID

        # ——— MLflow store：SQLite + artifact 联合恢复，全部既有模块可重开 ———
        restored_registry = open_registry_store(world.mlflow_root)
        record = get_model(restored_registry, MODEL_ID)
        assert record.train_id == TRAIN_ID
        assert record.offline_backup_scope == "adapter"
        assert get_model_by_alias(restored_registry, "candidate").model_id == MODEL_ID
        assert (
            get_model_by_alias(restored_registry, "production").model_id
            == BUNDLED_MODEL_ID
        )
        materialize_current(
            restored_registry,
            alias="candidate",
            service_mode="development",
            models_root=world.models_root,
            records_root=world.prompts_root,
        )
        assert validate_service_current(
            restored_registry,
            alias="candidate",
            service_mode="development",
            models_root=world.models_root,
            records_root=world.prompts_root,
        ).model_id == MODEL_ID

        # 父子 Run 与指标：train completed、三折 FINISHED、指标可查
        train = get_train_run(open_train_store(world.mlflow_root), TRAIN_ID)
        assert train.workflow_state == "completed"
        assert train.metrics["cv_f1_mean"] == 0.8
        assert set(train.folds) == {0, 1, 2}
        assert all(fold.status == "FINISHED" for fold in train.folds.values())
        assert all(
            fold.parent_run_id == train.run_id for fold in train.folds.values()
        )

        # 正式测评记录与结论可查
        evaluation = get_eval_run(open_eval_store(world.mlflow_root), EVAL_ID)
        assert evaluation.outcome == "passed"

        # artifact store 联合恢复：可列举、可下载、字节一致
        assert (
            _tree_digests(world.mlflow_root / "artifacts") == artifact_digests
        )
        client = MlflowClient(tracking_uri=restored_registry.tracking_uri)
        listed = {item.path for item in client.list_artifacts(train_run_id)}
        assert "fold0" in listed
        downloaded = Path(
            client.download_artifacts(
                run_id=train_run_id, path="fold0/adapter/adapter.bin"
            )
        )
        assert downloaded.read_bytes() == ARTIFACT_FILES["fold0/adapter/adapter.bin"]

        # SQLite 快照恢复后是可查询的有效数据库
        _assert_sqlite_readable(world.mlflow_root / "mlflow.db")

    def test_restore_refuses_existing_targets(
        self, world: World, registry: ModelRegistryStore, backup_root: Path, tmp_path: Path
    ) -> None:
        create_backup(registry, **_backup_args(world, backup_root))

        fresh = tmp_path / "fresh"
        args = {
            "data_root": fresh / "data",
            "prompts_root": fresh,
            "models_root": fresh / "models",
            "mlflow_root": fresh / "mlflow",
        }
        restore_backup(backup_root, **args)

        # 恢复目标已存在：拒绝覆盖既有产物（§2.11 不覆盖正式产物）
        before = _tree_digests(fresh)
        with pytest.raises(RestoreTargetConflict):
            restore_backup(backup_root, **args)
        assert _tree_digests(fresh) == before

    def test_restore_does_not_modify_backup_or_catalog(
        self, world: World, registry: ModelRegistryStore, backup_root: Path, tmp_path: Path
    ) -> None:
        create_backup(registry, **_backup_args(world, backup_root))
        catalog_file = backup_root / BACKUP_CATALOG_FILENAME
        before_catalog = catalog_file.read_bytes()
        before_digests = _tree_digests(backup_root)

        fresh = tmp_path / "fresh2"
        restore_backup(
            backup_root,
            data_root=fresh / "data",
            prompts_root=fresh,
            models_root=fresh / "models",
            mlflow_root=fresh / "mlflow",
        )

        # 单向性：恢复不修改 catalog，也不改写备份盘任何文件
        assert catalog_file.read_bytes() == before_catalog
        assert _tree_digests(backup_root) == before_digests

        # 异地恢复的非 MLflow 对象同样可用既有模块重开（决策点 8）
        assert (
            load_release_metadata(fresh / "data", DATA_VERSION).version
            == DATA_VERSION
        )
        assert load_prompt(fresh, PROMPT_VERSION).version == PROMPT_VERSION
        relocated_metadata = yaml.safe_load(
            (fresh / "models" / MODEL_ID / MATERIALIZED_METADATA_FILE).read_text(
                encoding="utf-8"
            )
        )
        assert relocated_metadata["model_id"] == MODEL_ID
        assert relocated_metadata["offline_backup_scope"] == "adapter"


# —————————————————— T7 B9 修复回归：catalog 落盘前校验门（P1） ——————————————————


class TestCatalogWriteGate:
    """P1 回归：落盘前全量校验（含 SQLite integrity_check）失败 → 不写 catalog。

    场景注入：真实复制完成后、catalog 落盘前，备份盘上的 mlflow.db 出现
    位腐（SQLite 头魔数清零，大小不变、与 catalog 条目自洽）——只有
    create_backup 落盘前的全量校验能拦住它；拦截失败不得改写盘上 catalog。
    """

    def test_verification_failure_first_run_writes_no_catalog(
        self,
        world: World,
        registry: ModelRegistryStore,
        backup_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install_mlflow_copy_corruption(monkeypatch, backup_root)

        # 复制成功但落盘前校验失败：抛 BackupIntegrityError
        with pytest.raises(BackupIntegrityError):
            create_backup(registry, **_backup_args(world, backup_root))

        # 首次备份不得产生 catalog（含快照），也不留任何临时文件残留
        assert not (backup_root / BACKUP_CATALOG_FILENAME).exists()
        assert not (backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME).exists()
        assert [
            name for name in os.listdir(backup_root) if name.startswith(".")
        ] == []

    def test_verification_failure_second_run_keeps_catalog(
        self,
        world: World,
        registry: ModelRegistryStore,
        backup_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first = create_backup(registry, **_backup_args(world, backup_root))
        catalog_bytes = (backup_root / BACKUP_CATALOG_FILENAME).read_bytes()
        assert not (backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME).exists()

        # 世界演进：candidate alias 移到另一作用域模型 → 源 SQLite 字节变化，
        # 下次运行 mlflow-store 走真实重拷（修复路径），随后被注入位腐。
        # 源集合不变：范围由 scope tag 决定，与当前 alias 无关。
        set_alias(registry, BUNDLED_MODEL_ID, "candidate")

        _install_mlflow_copy_corruption(monkeypatch, backup_root)
        with pytest.raises(BackupIntegrityError):
            create_backup(registry, **_backup_args(world, backup_root))

        # 失败运行不改写盘上既有 catalog：字节不变、快照不产生、仍可解析
        assert (backup_root / BACKUP_CATALOG_FILENAME).read_bytes() == catalog_bytes
        assert not (backup_root / BACKUP_CATALOG_SNAPSHOT_FILENAME).exists()
        assert load_backup_catalog(backup_root) == first
        assert [
            name for name in os.listdir(backup_root) if name.startswith(".")
        ] == []


# —————————————————— T8 B9 修复回归：差分修复不重拷（P2） ——————————————————


class TestDifferentialRepair:
    """P2 回归：二次备份健康对象不重拷；篡改单文件后仅该对象被重拷。

    判定证据双保险：复制调用 spy（零调用 ⇔ 未重拷）+ payload 文件
    inode/mtime（重拷必然换 inode：临时树在旧目录仍占位时创建）。
    """

    def test_healthy_objects_not_recopied_on_second_backup(
        self,
        world: World,
        registry: ModelRegistryStore,
        backup_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first = create_backup(registry, **_backup_args(world, backup_root))
        stats_before = _payload_stats(backup_root, first)

        calls: dict[str, list[Path]] = {"tree": [], "file": []}
        _install_copy_spies(monkeypatch, calls)
        second = create_backup(registry, **_backup_args(world, backup_root))

        # 健康对象不重拷：零树复制、零文件复制调用
        assert calls["tree"] == []
        assert calls["file"] == []
        # 盘上每个 payload 文件的 inode 与 mtime 均不变
        assert _payload_stats(backup_root, second) == stats_before
        # 复用既有条目：catalog（含 backed_up_at）与上次运行完全一致
        assert second == first
        assert load_backup_catalog(backup_root) == first
        assert verify_backup(backup_root)

    def test_single_file_tamper_recopies_only_that_object(
        self,
        world: World,
        registry: ModelRegistryStore,
        backup_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first = create_backup(registry, **_backup_args(world, backup_root))
        stats_before = _payload_stats(backup_root, first)

        # 篡改 MODEL_ID 备份目录中的单个文件（位腐）
        entry = _entry(first, MODEL_ID)
        victim = backup_root / entry.files[0].path
        _make_writable(victim)
        victim.write_bytes(b"BIT-ROT")
        with pytest.raises(BackupIntegrityError):
            verify_backup(backup_root)

        calls: dict[str, list[Path]] = {"tree": [], "file": []}
        _install_copy_spies(monkeypatch, calls)
        second = create_backup(registry, **_backup_args(world, backup_root))

        # 仅被篡改对象被整树重拷：恰一次树复制，目标是该对象的备份目录
        assert calls["tree"] == [backup_root / BACKUP_DIR_MODELS / MODEL_ID]
        assert calls["file"] == []
        # 其余健康对象的 payload 文件 inode/mtime 全部不变
        stats_after = _payload_stats(backup_root, second)
        for object_id in (
            DATA_VERSION,
            EXTRA_DATA_VERSION,
            BUNDLED_MODEL_ID,
            MLFLOW_STORE_OBJECT_ID,
            PROMPT_VERSION,
        ):
            assert stats_after[object_id] == stats_before[object_id], object_id
        # 被修复对象：全部文件被真实重拷（inode 必变），字节恢复与源一致
        assert set(stats_after[MODEL_ID]) == set(stats_before[MODEL_ID])
        for rel, (ino, _mtime) in stats_before[MODEL_ID].items():
            assert stats_after[MODEL_ID][rel][0] != ino, rel
        repaired = _entry(second, MODEL_ID)
        _assert_backup_bytes_match_source(backup_root, repaired)
        assert not any("/merged/" in file.path for file in repaired.files)
        assert verify_backup(backup_root)

        # 修复对象条目时间戳刷新；健康对象条目原样复用（backed_up_at 不变）
        assert _stable_entries(second) == _stable_entries(first)
        assert (
            _entry(second, MODEL_ID).backed_up_at
            != _entry(first, MODEL_ID).backed_up_at
        )
        for object_id in (DATA_VERSION, EXTRA_DATA_VERSION, BUNDLED_MODEL_ID):
            assert (
                _entry(second, object_id).backed_up_at
                == _entry(first, object_id).backed_up_at
            ), object_id


# —————————————————— T9 B9 修复回归：恢复重放封存只读位 ——————————————————


class TestRestoreSealReplay:
    """P3 回归：restore 必须重放 release payload 只读封存位（seal_payload）。

    灾难恢复（恢复到原绝对路径）的封存断言已由
    ``TestRestoreBackup.test_restore_disaster_recovery_reopens_everything``
    覆盖；本类补钉异地恢复：备份维护会给备份副本整树补写位
    （_make_writable），因此恢复产物的只读态只能来自 restore 主动重放，
    而不是副本权限碰巧保留。
    """

    def test_restore_replays_sealed_payload_in_fresh_roots(
        self, world: World, registry: ModelRegistryStore, backup_root: Path, tmp_path: Path
    ) -> None:
        create_backup(registry, **_backup_args(world, backup_root))

        fresh = tmp_path / "fresh-seal"
        restore_backup(
            backup_root,
            data_root=fresh / "data",
            prompts_root=fresh,
            models_root=fresh / "models",
            mlflow_root=fresh / "mlflow",
        )

        # 恢复出的 release payload 处于封存只读态，且仍可正常读取
        assert_payload_sealed(fresh / "data" / "releases" / DATA_VERSION)
        assert_payload_sealed(fresh / "data" / "releases" / EXTRA_DATA_VERSION)
        assert (
            load_release_metadata(fresh / "data", DATA_VERSION).version == DATA_VERSION
        )
        assert (
            load_release_metadata(fresh / "data", EXTRA_DATA_VERSION).version
            == EXTRA_DATA_VERSION
        )


# —————————————————— T10 B9 修复回归：源集合与 catalog 边界（P3） ——————————————————


class TestBackupEdgeCaseRegressions:
    """P3 回归：空 MLflow store、重复 object_id、releases/ 非目录条目。"""

    def test_empty_mlflow_store_is_backupable_and_restorable(
        self, registry: ModelRegistryStore, data_root: Path, tmp_path: Path
    ) -> None:
        """空 store（仅 schema 初始化，零 Run/零模型）可备份、可整体恢复。"""
        backup_root = tmp_path / "drive"
        catalog = create_backup(
            registry,
            data_root=data_root,
            prompts_root=tmp_path / "prompts-root",
            models_root=tmp_path / "models",
            backup_root=backup_root,
        )

        # 源集合 = 全部正式数据 + 恰一个（空）MLflow store
        assert {entry.object_id for entry in catalog.objects} == {
            DATA_VERSION,
            EXTRA_DATA_VERSION,
            MLFLOW_STORE_OBJECT_ID,
        }
        assert verify_backup(backup_root)
        # 空快照是可查询的有效 SQLite（runs 表存在且为空）
        _assert_sqlite_valid_zero_runs(backup_root / BACKUP_DIR_MLFLOW / "mlflow.db")

        # 整体恢复到全新四根：release 封存、空 store 可重开可查询
        fresh = tmp_path / "fresh-empty"
        restore_backup(
            backup_root,
            data_root=fresh / "data",
            prompts_root=fresh,
            models_root=fresh / "models",
            mlflow_root=fresh / "mlflow",
        )
        assert_payload_sealed(fresh / "data" / "releases" / DATA_VERSION)
        _assert_sqlite_valid_zero_runs(fresh / "mlflow" / "mlflow.db")
        reopened = open_registry_store(fresh / "mlflow")
        assert list(
            MlflowClient(tracking_uri=reopened.tracking_uri).search_model_versions(
                f"name='{reopened.registered_model}'"
            )
        ) == []

    def test_load_catalog_rejects_duplicate_object_id(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        create_backup(registry, **_backup_args(world, backup_root))

        # 手工构造重复 object_id 的 catalog（其余 schema 合法）
        catalog_path = backup_root / BACKUP_CATALOG_FILENAME
        payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        payload["objects"].append(copy.deepcopy(payload["objects"][0]))
        catalog_path.write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )

        # load / verify 均 fail-closed，绝不静默去重或取后者
        with pytest.raises(CatalogSchemaError, match="重复 object_id"):
            load_backup_catalog(backup_root)
        with pytest.raises(CatalogSchemaError):
            verify_backup(backup_root)

    def test_releases_non_directory_entry_fail_closed(
        self, world: World, registry: ModelRegistryStore, backup_root: Path
    ) -> None:
        create_backup(registry, **_backup_args(world, backup_root))
        catalog_bytes = (backup_root / BACKUP_CATALOG_FILENAME).read_bytes()

        # releases/ 下混入非目录条目：枚举与备份均 fail-closed
        rogue = world.data_root / "releases" / "rogue.txt"
        rogue.write_text("not a release directory", encoding="utf-8")
        with pytest.raises(BackupSourceSetError):
            enumerate_backup_sources(registry, **_source_args(world))
        with pytest.raises(BackupSourceSetError):
            create_backup(registry, **_backup_args(world, backup_root))
        # 失败运行不改写盘上 catalog
        assert (backup_root / BACKUP_CATALOG_FILENAME).read_bytes() == catalog_bytes

        # 同门：releases/ 下目录名不是合法 data ID 也 fail-closed
        rogue.unlink()
        (world.data_root / "releases" / "not-a-data-id").mkdir()
        with pytest.raises(BackupSourceSetError):
            enumerate_backup_sources(registry, **_source_args(world))
        with pytest.raises(BackupSourceSetError):
            create_backup(registry, **_backup_args(world, backup_root))
        assert (backup_root / BACKUP_CATALOG_FILENAME).read_bytes() == catalog_bytes


class TestBackupTransfer:
    def test_transfer_publishes_verified_snapshot(self, world, registry, backup_root, tmp_path, monkeypatch):
        import versioning.backup as api
        source = tmp_path / "source-snapshot"
        expected = create_backup(registry, **_backup_args(world, source))
        digest = hashlib.sha256((source / BACKUP_CATALOG_FILENAME).read_bytes()).hexdigest()
        def transport(host, source_root, destination):
            assert host == "fixture-host"
            shutil.copytree(source_root, destination, dirs_exist_ok=True)
        monkeypatch.setattr(api, "_receive_backup_tree", transport, raising=False)
        actual = api.transfer_backup(ssh_host="fixture-host", source_backup_root=source,
            backup_root=backup_root, catalog_sha256=digest)
        assert actual == expected
        assert verify_backup(backup_root) == expected
        assert (source / BACKUP_CATALOG_FILENAME).is_file()

    @pytest.mark.parametrize("fault", ["interrupted", "hash", "content", "existing"])
    def test_transfer_failure_does_not_publish(self, world, registry, backup_root, tmp_path, monkeypatch, fault):
        import versioning.backup as api
        source = tmp_path / "source-snapshot"
        create_backup(registry, **_backup_args(world, source))
        digest = hashlib.sha256((source / BACKUP_CATALOG_FILENAME).read_bytes()).hexdigest()
        if fault == "existing":
            backup_root.mkdir()
            (backup_root / "keep").write_text("untouched")
        def transport(host, source_root, destination):
            shutil.copytree(source_root, destination, dirs_exist_ok=True)
            if fault == "interrupted":
                raise OSError("interrupted transfer")
            if fault == "content":
                catalog = load_backup_catalog(destination)
                (destination / catalog.objects[0].files[0].path).write_bytes(b"bad bytes")
        monkeypatch.setattr(api, "_receive_backup_tree", transport, raising=False)
        with pytest.raises((ValueError, OSError)):
            api.transfer_backup(ssh_host="fixture-host", source_backup_root=source,
                backup_root=backup_root, catalog_sha256="0" * 64 if fault == "hash" else digest)
        if fault == "existing":
            assert (backup_root / "keep").read_text() == "untouched"
        else:
            assert not backup_root.exists()
        assert not list(tmp_path.glob(".drive.transfer-*"))
        assert verify_backup(source)


@pytest.mark.parametrize("entry_kind", ["symlink", "hardlink", "escape", "absolute", "duplicate", "fifo"])
def test_backup_transport_rejects_unsafe_archive(tmp_path, monkeypatch, entry_kind):
    import io
    import tarfile
    import versioning.backup as api
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("../escape" if entry_kind == "escape" else
                               "/absolute" if entry_kind == "absolute" else "file")
        info.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                     "fifo": tarfile.FIFOTYPE}.get(entry_kind, tarfile.REGTYPE)
        info.linkname = "/outside"
        archive.addfile(info)
        if entry_kind == "duplicate":
            archive.addfile(info)
    class Process:
        stdout = io.BytesIO(buffer.getvalue())
        def poll(self): return 0
        def wait(self): return 0
    monkeypatch.setattr(api.subprocess, "Popen", lambda *args, **kwargs: Process())
    destination = tmp_path / "received"
    destination.mkdir()
    with pytest.raises(BackupIntegrityError):
        api._receive_backup_tree("host", Path("/snapshot"), destination)
    assert not (tmp_path / "escape").exists()


def test_backup_transport_checks_ssh_exit_and_quotes_source(tmp_path, monkeypatch):
    import io, tarfile, shlex
    import versioning.backup as api
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w"):
        pass
    class Process:
        stdout = io.BytesIO(buffer.getvalue())
        def poll(self): return 1
        def wait(self): return 1
    commands = []
    def launch(command, **kwargs):
        commands.append(command)
        return Process()
    monkeypatch.setattr(api.subprocess, "Popen", launch)
    source = Path("/snapshot with ' quote; $(command)")
    with pytest.raises(BackupError, match="SSH"):
        api._receive_backup_tree("host", source, tmp_path)
    assert shlex.split(commands[0][-1]) == ["tar", "-C", str(source), "-cf", "-", "."]


@pytest.mark.parametrize("host,source,digest", [
    ("-oProxyCommand=bad", "/source", "a" * 64),
    ("host;bad", "/source", "a" * 64),
    ("host", "relative", "a" * 64),
    ("host", "/source", "bad"),
])
def test_backup_transfer_requires_explicit_safe_inputs(tmp_path, host, source, digest):
    from versioning.backup import transfer_backup
    target = tmp_path / "received"
    with pytest.raises(BackupError):
        transfer_backup(ssh_host=host, source_backup_root=Path(source),
                        backup_root=target, catalog_sha256=digest)
    assert not target.exists()


def test_backup_transport_reports_truncated_stream(tmp_path, monkeypatch):
    import io
    import versioning.backup as api
    class Process:
        stdout = io.BytesIO(b"truncated tar stream")
        def poll(self): return 1
        def wait(self): return 1
    monkeypatch.setattr(api.subprocess, "Popen", lambda *args, **kwargs: Process())
    with pytest.raises(BackupIntegrityError, match="archive"):
        api._receive_backup_tree("host", Path("/snapshot"), tmp_path)


def test_transfer_does_not_replace_directory_created_at_publication(world, registry, backup_root, tmp_path, monkeypatch):
    import versioning.backup as api
    source = tmp_path / "source-snapshot"
    create_backup(registry, **_backup_args(world, source))
    digest = hashlib.sha256((source / BACKUP_CATALOG_FILENAME).read_bytes()).hexdigest()
    monkeypatch.setattr(api, "_receive_backup_tree",
                        lambda host, src, dst: shutil.copytree(src, dst, dirs_exist_ok=True))
    publish = api._publish_backup_directory
    created = []
    def race(src, dst):
        dst.mkdir()
        created.append(dst.stat().st_ino)
        publish(src, dst)
    monkeypatch.setattr(api, "_publish_backup_directory", race)
    with pytest.raises((RestoreTargetConflict, FileExistsError)):
        api.transfer_backup(ssh_host="host", source_backup_root=source,
                            backup_root=backup_root, catalog_sha256=digest)
    assert backup_root.stat().st_ino == created[0]
    assert list(backup_root.iterdir()) == []
    assert not list(tmp_path.glob(".drive.transfer-*"))


@pytest.fixture(autouse=True)
def record_policy_execution_evidence_double(monkeypatch):
    """Isolate the pre-migration record-policy scenarios from GPU execution proof.

    This module does not certify actual execution or promotion evidence. Unmocked
    evidence, drift and public service tests live in test_eval_run/test_train_with_contract.
    """
    monkeypatch.setattr("versioning.registry._validate_train_execution_artifacts", lambda *a: None)
    monkeypatch.setattr("versioning.registry._validate_eval_execution_artifacts", lambda *a: None)
    monkeypatch.setattr("versioning.registry._validate_model_artifact_evidence", lambda *a: None)
