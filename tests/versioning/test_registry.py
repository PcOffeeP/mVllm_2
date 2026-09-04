"""B8 — MLflow Model Registry：唯一 mVllm2 + 晋级门 + alias 唯一路由 + offline_backup_scope。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
- §2.9 + D024/D037：项目只建一个稳定 Registered Model ``mVllm2``；每个
  ``model-v<协议>-r<N>`` 映射其中一个不可变数值 Model Version，以 ``model_id``
  tag 保存可读模型 ID；``candidate``/``production`` 两个可变别名是项目唯一
  逻辑路由，不承担不可变模型身份，切换别名不得改写原模型记录；普通
  checkpoint 不进入 Registry。
- §5.4：``model_id`` tag 在整个 Registered Model 中唯一；注册后不得把该
  数值版本改绑到另一个可读模型 ID；模型内容、可读 model_id、数值 Model
  Version 与训练输入关系不可修改；别名变化不回写模型实体（需要查看当前
  路由时以 MLflow 为准）。
- §2.6 + D039：``record_validity`` 权威位置含模型 Model Version tag，合法值
  仅 ``valid|invalid``；invalid 被下游（alias 门/批准/路由读取/物化）拒绝，
  不得通过改回 valid 复活旧事实；下游入口必须在线核对。
- §2.11 + D036：``offline_backup_scope`` 是粘性 Model Version tag；模型在
  首次设置 alias 之前必须写入该范围：进入 candidate 前设为 ``adapter``、
  进入 production 前设为 ``production_bundle``；范围只允许
  缺失→adapter→production_bundle 单向升级，不得因 alias 切走或一次备份
  完成而降级或清除。
- §5.4 + D040：train 门通过后先创建无 ``eval_id`` 的 staging Model Version；
  正式 eval 精确引用该数值版本，passed 后再单向绑定 ``eval_id``；两个活动
  alias 均拒绝未完成绑定的模型。
- §9 + §11.6：显式版本纪律——model_id/train_id 及 finalize 的 eval_id 必须显式给出并经
  ``versioning.ids`` 解析；同名冲突立即停止，不比较内容、不自动选择下一个
  编号。
- §13.1：``mVllm2`` 中 model_id 与数值 Model Version 一一对应，
  candidate/production alias 只能指向其中的有效版本。
- §11.4：train 门失败时不登记；eval 未通过时保留为无 alias 的 Registry
  staging 证据；已登记模型不得删除后以同一版本重试。

预期 production API（供 viber 对照实现，模块 ``versioning.registry``）::

    # ——— 模块常量（tag 键名/值域钉死；raw MLflow 读回按字面量断言）———
    REGISTERED_MODEL_NAME: str = "mVllm2"   # 唯一稳定 Registered Model（§2.9/D037）
    ALIASES: tuple[str, ...] = ("candidate", "production")  # 唯二别名，无其他
    BACKUP_SCOPES: tuple[str, ...] = ("adapter", "production_bundle")
    MODEL_ID_TAG: str = "model_id"
    TRAIN_ID_TAG: str = "train_id"
    EVAL_ID_TAG: str = "eval_id"
    DATA_VERSION_TAG: str = "data_version"
    PROMPT_VERSION_TAG: str = "prompt_version"
    GIT_COMMIT_TAG: str = "git_commit"
    RECORD_VALIDITY_TAG: str = "record_validity"
    OFFLINE_BACKUP_SCOPE_TAG: str = "offline_backup_scope"
    PRODUCTION_APPROVED_TAG: str = "production_approved"
    MATERIALIZED_METADATA_FILE: str = "materialized.yaml"   # test_materialize 钉
    MATERIALIZED_ARTIFACTS_DIR: str = "artifacts"           # test_materialize 钉

    # ——— 异常（基类 MLflowRegistryError(ValueError)；状态机违规委托
    #     versioning.state.IllegalTransition，直接传播或以其为基类均可）———
    class MLflowRegistryError(ValueError)
        # Registry 域异常基类
    class RegistryModelNotFound(MLflowRegistryError)
        # 指定 model 未注册 / alias 无目标 / 删除不存在的 alias
    class ModelVersionConflict(MLflowRegistryError)
        # 同一 model-v... 已注册（§8 只增不改 / §11.6 同名冲突立即停止）；
        # 冲突检测优先于一切晋级门，原数值版本一律不动
    class IllegalRegistryRecord(MLflowRegistryError)
        # 输入/结构违规：非法 alias 名、未知 offline_backup_scope 值、读取
        # fail-closed（绑定 tag 篡改/不可解析、model_id tag 重复、物化目标
        # 分歧——后者见 test_materialize.py）
    class PromotionGateRejected(MLflowRegistryError)
        # 晋级门 fail-closed：train 门、eval 门、eval 关联校验、alias 的
        # scope 前置、production 批准缺失、train/eval 门在线复验失败；
        # 拒绝时 Registry 对象一律不动（无半写状态）
    class InvalidModelRecord(MLflowRegistryError)
        # record_validity=invalid 的模型被下游校验拒绝（set_alias/approve/
        # get_model_by_alias/物化），invalid 优先于一切门条件（§2.6/§10）

    # ——— store 句柄（真实 MLflow：与 B6/B7 同根共用同一 SQLite 单文件）———
    @dataclass(frozen=True)
    class ModelRegistryStore
        root: Path                  # store 根目录
        tracking_uri: str           # sqlite:///<root>/mlflow.db
        artifact_location: str      # <root>/artifacts（本地目录）
        registered_model: str       # == REGISTERED_MODEL_NAME
        train_experiment_id: str    # mVllm2-training 实验（按名复用或新建）
        eval_experiment_id: str     # mVllm2-evaluation 实验（按名复用或新建）

    def open_registry_store(root: Path) -> ModelRegistryStore
        # 创建（缺失时）root 与 root/artifacts；tracking 指向
        # sqlite:///<root>/mlflow.db；按名复用/新建 mVllm2-training 与
        # mVllm2-evaluation 实验（与 open_train_store/open_eval_store 同根
        # 打开时必须复用同一 experiment_id，两个方向都成立）；确保
        # Registered Model mVllm2 存在（缺失则创建，重复打开幂等，全库唯一）；
        # 绝不启动服务、绝不连接 root 之外的任何 store；一切后续函数必须按
        # store 句柄寻址（不依赖全局 ambient tracking 状态，双 store 互不可见）。

    # ——— 注册记录快照（只读视图）———
    @dataclass(frozen=True)
    class RegisteredModelRecord
        model_id: str               # 可读模型 ID（model-v<协议>-r<N>）
        version: int                # MLflow 数值 Model Version（同 store 从 1 递增）
        registered_model: str       # "mVllm2"
        run_id: str                 # source train 父 Run MLflow ID
        train_id: str
        eval_id: str | None         # staging 时缺失；finalize 后不可改绑
        data_version: str           # 取自 train 父 Run（§5.4 训练输入）
        prompt_version: str         # 取自 train 父 Run
        git_commit: str             # 取自 train 父 Run
        record_validity: str        # "valid" | "invalid"
        offline_backup_scope: str | None   # None = 未写入
        production_approved: bool          # tag "production_approved"=="true" 时为 True
        aliases: tuple[str, ...]    # 当前指向该数值版本的别名，按字母序

    # ——— 两阶段登记：register 固定模型实体，finalize 绑定 passed eval ———
    def register_model(store, model_id: str, *,
                       train_id: str) -> RegisteredModelRecord
        # 1) model_id 经 versioning.ids.parse_model_id、train_id 经
        #    parse_train_id 校验（缺省/None/latest/短前缀/跨
        #    类别/r0/前导零/非字符串/含引号注入样式 -> InvalidIdentifier；
        #    模块不存在任何自动分配下一版本号的分支，§9/§11.6）；
        # 2) 同名冲突：mVllm2 下已有 model_id tag 相同的数值版本 ->
        #    ModelVersionConflict（立即停止，优先于一切门；原版本不动）；
        # 3) train 晋级门：在 train 实验按 train_id tag 检索父 Run 并执行
        #    B6 validate_train_for_promotion 等价校验（不存在/invalid/
        #    workflow_state 非 completed|archived/必需 fold 缺失或未
        #    FINISHED/无三折汇总 -> PromotionGateRejected）；
        # 4) 全部通过：create_model_version(mVllm2, source=train 父 Run 的
        #    artifact_uri, run_id=train 父 Run ID) 并写 tags：model_id/
        #    train_id/data_version/prompt_version/git_commit（值
        #    一律取自 train 快照）/record_validity="valid"；不写
        #    offline_backup_scope、production_approved tag（未声明即缺省）；
        #    不设置 eval_id/alias、不新建任何 Run；返回 staging 快照。

    def validate_model_for_evaluation(store, model_id: str,
                                      model_version_number: int) -> RegisteredModelRecord
        # 正式 eval 创建门：模型存在且 valid、数值版本精确匹配、来源 train
        # 在线晋级门仍通过；猜号、错号、缺失或 invalid 均 fail-closed。

    def finalize_model_evaluation(store, model_id: str, *,
                                  eval_id: str) -> RegisteredModelRecord
        # eval 必须 completed|archived、valid、outcome=passed，并同时匹配
        # model_id 与数值 Model Version；只写 eval_id，同一值幂等且禁止改绑。

    # ——— 读取（fail-closed）———
    def get_model(store, model_id: str) -> RegisteredModelRecord
        # 按 model_id tag 在 mVllm2 下检索数值版本：不存在 ->
        #    RegistryModelNotFound；多个数值版本声称同一 model_id（人工或
        #    异常操作）-> IllegalRegistryRecord；读取 fail-closed：
        #    model_id/train_id/data_version/prompt_version 必须经
        #    versioning.ids 对应解析器校验、git_commit 非空、
        #    eval_id 缺失或为合法完整 eval ID、
        #    record_validity ∈ {valid,invalid}、offline_backup_scope 缺失或
        #    ∈ BACKUP_SCOPES、production_approved 缺失或 == "true"（任何
        #    篡改 -> IllegalRegistryRecord）；返回审计快照（invalid 亦照实
        #    返回，不因 invalid 拒绝记录读取）。

    def get_model_by_alias(store, alias: str) -> RegisteredModelRecord
        # 路由读：alias 必须显式给出且 ∈ ALIASES（"latest"/"staging"/大小写
        #    变体/None/空串 -> IllegalRegistryRecord）；解析 alias 指向的
        #    精确数值版本：未设置 -> RegistryModelNotFound（不回退任何
        #    "最新"，禁止隐式最新语义）；目标版本按 get_model 同标准
        #    fail-closed 校验；目标 record_validity=invalid ->
        #    InvalidModelRecord（§13.1 alias 只能指向有效版本）。

    # ——— offline_backup_scope（§2.11/D36 单向粘性范围）———
    def set_offline_backup_scope(store, model_id: str,
                                 scope: str) -> RegisteredModelRecord
        # model 不存在 -> RegistryModelNotFound；scope 必须显式给出且 ∈
        #    BACKUP_SCOPES（None/空串/data/prompt/train/model/eval 等五类名
        #    或任意其他值 -> IllegalRegistryRecord）；升级只允许
        #    缺失→adapter→production_bundle，同值幂等；降级
        #    （production_bundle→adapter）-> versioning.state.IllegalTransition；
        #    只写 OFFLINE_BACKUP_SCOPE_TAG，不触碰其他 tags/alias/Run。

    # ——— 用户批准标记（production 前置）———
    def approve_model_for_production(store, model_id: str) -> RegisteredModelRecord
        # 校验顺序：model 不存在 -> RegistryModelNotFound；invalid ->
        #    InvalidModelRecord（优先）；train 门 + eval 质量门（outcome==
        #    passed）在线复验（同 register_model 3)-5)）失败 ->
        #    PromotionGateRejected；通过则写 PRODUCTION_APPROVED_TAG="true"
        #    （重复批准幂等）；不要求 scope 已升级、不设置 alias。

    # ——— alias 管理（唯一可变路由入口；模型实体不可变）———
    def set_alias(store, model_id: str, alias: str) -> RegisteredModelRecord
        # alias 必须显式给出且 ∈ ALIASES（"latest"/"Candidate"/"prod"/None/
        #    空串等 -> IllegalRegistryRecord，且不触碰 MLflow）；model 不
        #    存在 -> RegistryModelNotFound；record_validity=invalid ->
        #    InvalidModelRecord（优先于一切门）；scope 门（§2.11 首次设置
        #    alias 之前必须已写入粘性范围）：candidate 要求 scope ∈
        #    {adapter, production_bundle}、production 要求 scope ==
        #    production_bundle（缺失或不足 -> PromotionGateRejected）；
        #    两个 alias 都要求已 finalize 且 eval 质量门在线复验通过；
        #    alias=production 还要求 PRODUCTION_APPROVED_TAG=="true"；
        #    train 门在线复验（失败 -> PromotionGateRejected）；全部通过则
        #    set_registered_model_alias 绑定或显式切换（重复指向同目标幂等），
        #    不改写任何 Model Version tags；返回目标模型快照（aliases 更新）。

    def delete_alias(store, alias: str) -> RegisteredModelRecord
        # alias 必须显式给出且 ∈ ALIASES（其他 -> IllegalRegistryRecord）；
        #    alias 未设置 -> RegistryModelNotFound（fail-closed：MLflow 原生
        #    delete 对缺失 alias 静默成功，模块必须先行解析校验）；通过则
        #    删除并返回原目标模型快照（aliases 更新）；删除后解析该 alias
        #    一律 RegistryModelNotFound，不回退任何"最新"。

    # ——— 有效性（D039 更正策略；无复活入口）———
    def mark_model_invalid(store, model_id: str) -> RegisteredModelRecord
        # model 不存在 -> RegistryModelNotFound；record_validity valid→invalid
        #    或同值幂等（委托 versioning.state.transition_record_validity；
        #    不提供任何改回 valid 的入口）；只写 RECORD_VALIDITY_TAG，不触碰
        #    alias 与其他 tags。

    # ——— 物化（本批基础导出；完整契约见 test_materialize.py）———
    def materialize_model(store, model_id: str, models_root: Path) -> Path
        # 把已注册模型 artifact 从 Registry 单向导出到
        #    models_root/<model_id>/{artifacts/..., materialized.yaml}；
        #    下游语义：invalid -> InvalidModelRecord、不存在 ->
        #    RegistryModelNotFound、目标分歧 -> IllegalRegistryRecord。

语义决策点（测试侧钉定，供实现对照）：
    1. register_model 只执行 train 晋级门并创建 Registry staging 实体；
       正式 eval 精确引用该数值版本，finalize 再绑定 passed 结论；candidate
       与 production 都只指向已 finalize 的模型。
    2. offline_backup_scope 值域 = {"adapter", "production_bundle"}（权威
       设计 §2.11/D036 与实施台账 B8"缺失→adapter→production_bundle 单向
       升级"）。任务要点 4 括注的（data/prompt/train/model/eval 选择性
       子集）不是本 tag 的值域：五类记录按范围展开属 B9 备份消费方职责；
       测试以 BAD_SCOPES 显式拒绝全部五类名与组合串。
    3. 关联校验 = eval 父 Run 的 model_id 与 model_version_number 必须同时
       匹配被 finalize 模型的可读身份和实际数值版本；
       B7 eval Run 不记录 source_train，train↔eval 血缘不做机器交叉校验，
       权威绑定由模型 tags（train_id + eval_id）与 eval 的精确模型引用承担。
    4. 模型 tags 的 data_version/prompt_version/git_commit 一律取自 train
       父 Run（validate_train_for_promotion 快照），不取 eval（测试以
       TRAIN_GIT_COMMIT != EVAL_GIT_COMMIT 钉死来源）。
    5. §5.4 的 source_scope/deploy_target/三折组结构与 §7 的
       models/current、service_mode 不在本批契约（任务 tags 清单无此项，
       实施台账 B8 中 materialize.py 服务物化与 model manifest 属后续增量；
       materialize_model 仅做基础导出，见 test_materialize.py 决策点）。
    6. 读取分层：get_model 返回含 invalid 的审计快照（与 B6/B7 读路径
       一致），"读取 fail-closed"指 tag 结构校验（篡改/重复 model_id ->
       IllegalRegistryRecord）；get_model_by_alias 是路由读，拒绝 invalid
       目标（§13.1）。
    7. Model Version source = train 父 Run 的 artifact_uri（run artifact
       根，整树权威），run_id = train 父 Run ID；物化从该 source 导出。
    8. set_alias 幂等（重复指向同目标 OK）；delete_alias 对未设置 alias
       fail-closed；alias 删除/未设置后的解析不回退任何"最新"——禁止
       隐式最新语义的机器表达；注册不自动设置任何 alias。
    9. 状态机违规（scope 降级）委托 versioning.state.IllegalTransition；
       值域违规（未知 scope、非法 alias 名）为 IllegalRegistryRecord。
    10. approve 是用户批准标记（production_approved tag），不要求 scope 已
        升级；set_alias(production) 才同时校验 scope + 批准 + 质量门；
        approve 本身在线复验 train 门与 eval 质量门。
    11. alias 是唯一路由可变入口：模型实体（数值版本、run 绑定、source、
        六个绑定 tags）经全 alias 生命周期 raw 对比钉死不变；可变 tags 仅
        record_validity/offline_backup_scope/production_approved（各自经
        显式入口）。

测试环境：真实 MLflow 集成（非 mock）；train/eval/registry 三类 store 同根
共用同一 SQLite 单文件（B6/B7 既有模式，registry 按名复用二者实验）；全部
目录在 pytest ``tmp_path`` 内（SQLite + 本地 artifact store + data release），
不启动服务、不连接任何正式 store。

当前 ``versioning/registry.py`` 尚不存在，本文件全部用例应为 RED
（collection error：ModuleNotFoundError / ImportError）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mlflow.entities import ViewType
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from versioning.data_release import seal_release, stage_release
from versioning.ids import InvalidIdentifier
from versioning.mlflow_eval import (
    MODEL_ID_TAG as EVAL_MODEL_ID_TAG,
    EvalRecordStore,
    EvalRunRecord,
    IllegalEvalRecord,
    create_eval_fold_run,
    create_eval_run,
    end_eval_fold_run,
    get_eval_run,
    log_eval_fold_metrics,
    log_eval_summary,
    mark_eval_invalid,
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
    mark_train_invalid,
    open_train_store,
    transition_train_state,
)
from versioning.registry import (
    ALIASES,
    BACKUP_SCOPES,
    DATA_VERSION_TAG,
    EVAL_ID_TAG,
    GIT_COMMIT_TAG,
    MODEL_ID_TAG,
    OFFLINE_BACKUP_SCOPE_TAG,
    PROMPT_VERSION_TAG,
    PRODUCTION_APPROVED_TAG,
    RECORD_VALIDITY_TAG,
    REGISTERED_MODEL_NAME,
    TRAIN_ID_TAG,
    IllegalRegistryRecord,
    InvalidModelRecord,
    MLflowRegistryError,
    ModelRegistryStore,
    ModelVersionConflict,
    PromotionGateRejected,
    RegisteredModelRecord,
    RegistryModelNotFound,
    approve_model_for_production,
    delete_alias,
    finalize_model_evaluation,
    get_model,
    get_model_by_alias,
    mark_model_invalid,
    open_registry_store,
    register_model,
    set_alias,
    set_offline_backup_scope,
    validate_model_for_evaluation,
)
from versioning.state import IllegalTransition

MODEL_ID = "model-v4.1-r1"
OTHER_MODEL_ID = "model-v4.1-r2"
UNKNOWN_MODEL_ID = "model-v4.1-r9"
TRAIN_ID = "train-v4.1-r1"
OTHER_TRAIN_ID = "train-v4.1-r2"
UNKNOWN_TRAIN_ID = "train-v4.1-r9"
EVAL_ID = "eval-v4.1-r1"
OTHER_EVAL_ID = "eval-v4.1-r2"
UNKNOWN_EVAL_ID = "eval-v4.1-r9"
DATA_VERSION = "data-v4.1-r1"  # development 正式 release
PROMPT_VERSION = "prompt-v4.1-r1"
# train 与 eval 的 git_commit 故意取不同值：模型 tags 的来源必须唯一（train）
TRAIN_GIT_COMMIT = "a1b2c3d"
EVAL_GIT_COMMIT = "e5f6a7b"
BASE_MODEL = "MiniCPM-V-4.5"
CONFIG = "records/evaluations/config/eval-v4.1-contract.yaml"

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

# 实体中允许经显式入口变化的 tags；其余 tag 连同数值版本/run 绑定/source
# 一起视为不可变实体视图（全 alias 生命周期 raw 对比用）。
MUTABLE_MODEL_TAGS = ("record_validity", "offline_backup_scope", "production_approved")

# 非法 model_id：缺省/None、latest、短前缀、跨类别、r0、前导零、非字符串、空串。
BAD_MODEL_IDS = [
    None,
    "latest",
    "model-latest",
    "model-v4.1",
    "train-v4.1-r1",
    "data-v4.1-r1",
    "eval-v4.1-r1",
    "model-v4.1-r0",
    "model-v4.1-r01",
    7,
    "",
]

BAD_TRAIN_IDS = [
    None,
    "latest",
    "train-v4.1",
    "model-v4.1-r1",
    "train-v4.1-r0",
    "train-v4.1-r01",
    41,
    "",
]

BAD_EVAL_IDS = [
    "latest",
    "eval-v4.1",
    "model-v4.1-r1",
    "eval-v4.1-r0",
    "eval-v4.1-r01",
    41,
    "",
]

# 非法 alias：项目唯二别名 candidate/production；其余一律拒绝（含 raw MLflow
# 会接受的 "prod"/"Candidate"——域门必须先于 MLflow 拒绝）。
BAD_ALIASES = [
    None,
    "",
    "latest",
    "staging",
    "Candidate",
    "candidate ",
    "prod",
    "production_bundle",
    "candidate,production",
    1,
    True,
]

# 非法 offline_backup_scope：值域仅 adapter/production_bundle；五类名与任意
# 组合串（任务要点 4 括注的 data/prompt/train/model/eval 子集）不是值域。
BAD_SCOPES = [
    None,
    "",
    "data",
    "prompt",
    "train",
    "model",
    "eval",
    "data,prompt,train,model,eval",
    "adapter_bundle",
    "production",
    "ADAPTER",
    "Adapter",
    1,
    True,
]

# 典型单引号布尔注入串（P3 回归同型；读/写入口必须先 parse_model_id）。
MALFORMED_QUOTED_MODEL_IDS = [
    "model-v4.1-r1' OR '1'='1",
    "model-v4.1-r1'; --",
    "model-v'4.1'-r1",
    'model-v4.1-r1"',
    "model-v4.1-r1\n",
    None,
    41,
]

# 读取 fail-closed：绑定/值域 tag 的代表性篡改（raw set_model_version_tag
# 模拟人工或异常操作）。
TAMPERED_TAG_CASES = [
    ("eval_id", "junk-not-an-id"),
    ("train_id", "junk"),
    ("data_version", "junk"),
    ("prompt_version", "junk"),
    ("git_commit", ""),
    ("record_validity", "bogus"),
    ("offline_backup_scope", "data"),
    ("production_approved", "yes"),
]


# —————————————————— fixtures 与 helpers ——————————————————


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """train/eval/registry 三类 store 共用的 MLflow 根（同根同 SQLite）。"""
    return tmp_path / "mlflow"


@pytest.fixture()
def registry(root: Path) -> ModelRegistryStore:
    """每个用例独立 tmp_path registry store（SQLite + 本地 artifacts）。"""
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
        description="registry 晋级门测试正式数据",
        sample_count=2,
        source_batches=["batch-2026-07"],
        splits={"fold0": {"train": 1, "validation": 1}},
    )
    return base


@pytest.fixture()
def golden(
    registry: ModelRegistryStore,
    train_store: TrainRecordStore,
    eval_store: EvalRecordStore,
    data_root: Path,
) -> RegisteredModelRecord:
    """黄金晋级链上的已注册 model-v4.1-r1（version=1）。"""
    _complete_training(train_store)
    register_model(registry, MODEL_ID, train_id=TRAIN_ID)
    _pass_eval(eval_store, data_root)
    return finalize_model_evaluation(registry, MODEL_ID, eval_id=EVAL_ID)


def _client(
    store: ModelRegistryStore | TrainRecordStore | EvalRecordStore,
) -> MlflowClient:
    """raw MLflow 读回通道（真实集成断言；篡改模拟"人工或异常操作"）。"""
    return MlflowClient(tracking_uri=store.tracking_uri)


def _raw_model_version(registry: ModelRegistryStore, version: int | str):
    return _client(registry).get_model_version("mVllm2", str(version))


def _raw_model_versions(registry: ModelRegistryStore) -> list:
    return list(_client(registry).search_model_versions("name='mVllm2'"))


def _make_train(
    train_store: TrainRecordStore, train_id: str = TRAIN_ID, **overrides: object
) -> TrainRunRecord:
    inputs: dict = dict(TRAIN_INPUTS)
    inputs.update(overrides)
    return create_train_run(train_store, train_id, **inputs)


def _complete_training(
    train_store: TrainRecordStore, train_id: str = TRAIN_ID
) -> TrainRunRecord:
    """三折 FINISHED + 汇总 + completed（B6 合法完成路径）。"""
    _make_train(train_store, train_id)
    for fold in (0, 1, 2):
        create_fold_run(train_store, train_id, fold)
        log_fold_metrics(train_store, train_id, fold, TRAIN_FOLD_METRICS)
        end_fold_run(train_store, train_id, fold, "FINISHED")
    log_train_summary(train_store, train_id, TRAIN_SUMMARY_METRICS)
    return transition_train_state(train_store, train_id, "completed")


def _pass_eval(
    eval_store: EvalRecordStore,
    data_root: Path,
    *,
    eval_id: str = EVAL_ID,
    model_id: str = MODEL_ID,
    outcome: str = "passed",
    model_version_number: int | None = None,
) -> EvalRunRecord:
    """single_fold 正式测评 completed + 显式 outcome（B7 合法路径）。"""
    create_eval_run(
        eval_store,
        eval_id,
        model_id=model_id,
        model_version_number=(
            model_version_number
            if model_version_number is not None
            else (2 if model_id == OTHER_MODEL_ID else 1)
        ),
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
    return transition_eval_state(eval_store, eval_id, "completed", outcome=outcome)


def _register(
    registry: ModelRegistryStore,
    model_id: str = MODEL_ID,
    *,
    train_id: str = TRAIN_ID,
) -> RegisteredModelRecord:
    return register_model(registry, model_id, train_id=train_id)


def _golden_register(
    registry: ModelRegistryStore,
    train_store: TrainRecordStore,
    eval_store: EvalRecordStore,
    data_root: Path,
    *,
    model_id: str = MODEL_ID,
    train_id: str = TRAIN_ID,
    eval_id: str = EVAL_ID,
) -> RegisteredModelRecord:
    """完整黄金链：train completed → staging register → eval passed → finalize。"""
    _complete_training(train_store, train_id)
    staged = register_model(registry, model_id, train_id=train_id)
    _pass_eval(
        eval_store,
        data_root,
        eval_id=eval_id,
        model_id=model_id,
        model_version_number=staged.version,
    )
    return finalize_model_evaluation(registry, model_id, eval_id=eval_id)


def _stable_entity_view(entity) -> tuple:
    """实体不可变视图：数值版本、run 绑定、source 与除可变 tags 外的全部 tags。"""
    tags = {
        key: value
        for key, value in entity.tags.items()
        if key not in MUTABLE_MODEL_TAGS
    }
    return (entity.version, entity.run_id, entity.source, tuple(sorted(tags.items())))


# —————————————————— T1 store 句柄 ——————————————————


class TestRegistryStore:
    """open_registry_store：本地 SQLite、唯一 mVllm2、与 B6/B7 同根共存与隔离。"""

    def test_module_constants_pinned(self) -> None:
        assert REGISTERED_MODEL_NAME == "mVllm2"
        assert ALIASES == ("candidate", "production")
        assert BACKUP_SCOPES == ("adapter", "production_bundle")
        assert MODEL_ID_TAG == "model_id"
        assert TRAIN_ID_TAG == "train_id"
        assert EVAL_ID_TAG == "eval_id"
        assert DATA_VERSION_TAG == "data_version"
        assert PROMPT_VERSION_TAG == "prompt_version"
        assert GIT_COMMIT_TAG == "git_commit"
        assert RECORD_VALIDITY_TAG == "record_validity"
        assert OFFLINE_BACKUP_SCOPE_TAG == "offline_backup_scope"
        assert PRODUCTION_APPROVED_TAG == "production_approved"

    def test_open_store_creates_local_sqlite_artifacts_and_registered_model(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "mlflow"
        store = open_registry_store(root)

        assert isinstance(store, ModelRegistryStore)
        assert store.root.resolve() == root.resolve()
        assert store.tracking_uri.startswith("sqlite:///")
        assert store.tracking_uri.endswith("mlflow.db")
        assert str(root) in store.tracking_uri
        assert (root / "mlflow.db").is_file()
        assert (root / "artifacts").is_dir()
        assert (
            Path(store.artifact_location).resolve()
            == (root / "artifacts").resolve()
        )
        assert store.registered_model == "mVllm2"

        # 唯一稳定 Registered Model mVllm2 已创建（raw 读回）
        client = _client(store)
        assert client.get_registered_model("mVllm2").name == "mVllm2"
        # train/eval 实验就绪，且与句柄一致（可被 B6/B7 store 复用）
        train_exp = client.get_experiment_by_name("mVllm2-training")
        eval_exp = client.get_experiment_by_name("mVllm2-evaluation")
        assert train_exp is not None
        assert eval_exp is not None
        assert store.train_experiment_id == train_exp.experiment_id
        assert store.eval_experiment_id == eval_exp.experiment_id

    def test_open_store_idempotent_reuse(self, tmp_path: Path) -> None:
        root = tmp_path / "mlflow"
        first = open_registry_store(root)
        again = open_registry_store(root)

        assert again.tracking_uri == first.tracking_uri
        assert again.train_experiment_id == first.train_experiment_id
        assert again.eval_experiment_id == first.eval_experiment_id
        # 重复打开不产生第二个 Registered Model（§2.9 唯一 mVllm2）
        client = _client(first)
        assert [rm.name for rm in client.search_registered_models()] == ["mVllm2"]

    def test_store_coexists_with_train_and_eval_stores_in_one_sqlite(
        self, tmp_path: Path
    ) -> None:
        # 顺序一：B6/B7 先开，registry 按名复用同一实验
        root = tmp_path / "mlflow"
        train_store = open_train_store(root)
        eval_store = open_eval_store(root)
        store = open_registry_store(root)
        assert store.tracking_uri == train_store.tracking_uri == eval_store.tracking_uri
        assert store.train_experiment_id == train_store.experiment_id
        assert store.eval_experiment_id == eval_store.experiment_id

        # 顺序二：registry 先开，B6/B7 复用同一实验
        root2 = tmp_path / "mlflow2"
        store2 = open_registry_store(root2)
        train_store2 = open_train_store(root2)
        eval_store2 = open_eval_store(root2)
        assert train_store2.experiment_id == store2.train_experiment_id
        assert eval_store2.experiment_id == store2.eval_experiment_id

    def test_stores_are_isolated(
        self, tmp_path: Path, data_root: Path
    ) -> None:
        store_a = open_registry_store(tmp_path / "a")
        store_b = open_registry_store(tmp_path / "b")
        assert (tmp_path / "a" / "mlflow.db").is_file()
        assert (tmp_path / "b" / "mlflow.db").is_file()

        _golden_register(store_a, open_train_store(tmp_path / "a"),
                         open_eval_store(tmp_path / "a"), data_root)
        with pytest.raises(RegistryModelNotFound):
            get_model(store_b, MODEL_ID)

        # B 中独立构建同 ID 链不受 A 影响（不同 store，各自唯一；数值版本独立分配）
        record_b = _golden_register(
            store_b, open_train_store(tmp_path / "b"),
            open_eval_store(tmp_path / "b"), data_root
        )
        assert record_b.version == 1
        assert get_model(store_a, MODEL_ID).version == 1


# —————————————————— T2 注册晋级门（train 晋级 + eval passed）——————————————————


class TestRegisterModelGate:
    """register_model：显式三元组、六绑定 tags、门 fail-closed、同名冲突。"""

    def test_two_phase_registration_requires_passed_eval_before_candidate(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        _complete_training(train_store)
        staged = register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        assert staged.eval_id is None
        assert staged.version == 1
        assert validate_model_for_evaluation(registry, MODEL_ID, 1) == staged

        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        with pytest.raises(PromotionGateRejected):
            set_alias(registry, MODEL_ID, "candidate")

        _pass_eval(eval_store, data_root)
        finalized = finalize_model_evaluation(registry, MODEL_ID, eval_id=EVAL_ID)
        assert finalized.eval_id == EVAL_ID
        assert finalize_model_evaluation(registry, MODEL_ID, eval_id=EVAL_ID) == finalized
        assert set_alias(registry, MODEL_ID, "candidate").aliases == ("candidate",)

    def test_eval_reference_and_finalize_require_exact_numeric_version(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        _complete_training(train_store)
        register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        _complete_training(train_store, OTHER_TRAIN_ID)
        second = register_model(registry, OTHER_MODEL_ID, train_id=OTHER_TRAIN_ID)
        assert second.version == 2

        with pytest.raises(PromotionGateRejected):
            validate_model_for_evaluation(registry, OTHER_MODEL_ID, 1)
        with pytest.raises(IllegalEvalRecord):
            _pass_eval(
                eval_store,
                data_root,
                eval_id=OTHER_EVAL_ID,
                model_id=OTHER_MODEL_ID,
                model_version_number=1,
            )
        assert get_model(registry, OTHER_MODEL_ID).eval_id is None

    def test_register_golden_path_record_and_raw_binding(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        train_run = _client(registry).get_run(golden.run_id)

        # 快照：显式 model_id + train/eval 绑定 + train 输入 + 初始 valid
        assert isinstance(golden, RegisteredModelRecord)
        assert golden.model_id == MODEL_ID
        assert golden.version == 1
        assert golden.registered_model == "mVllm2"
        assert golden.run_id == train_run.info.run_id
        assert golden.train_id == TRAIN_ID
        assert golden.eval_id == EVAL_ID
        assert golden.data_version == DATA_VERSION
        assert golden.prompt_version == PROMPT_VERSION
        # git_commit 取自 train（EVAL_GIT_COMMIT 不同值以钉死来源）
        assert golden.git_commit == TRAIN_GIT_COMMIT
        assert golden.record_validity == "valid"
        assert golden.offline_backup_scope is None
        assert golden.production_approved is False
        assert golden.aliases == ()

        # raw MLflow 读回：数值版本绑定、source、六绑定 tags + validity
        mv = _raw_model_version(registry, 1)
        assert mv.name == "mVllm2"
        assert mv.version == 1  # MLflow 数值 Model Version（raw entity 为 int）
        assert mv.run_id == golden.run_id
        assert mv.source == train_run.info.artifact_uri
        assert mv.aliases == []
        assert mv.tags["model_id"] == MODEL_ID
        assert mv.tags["train_id"] == TRAIN_ID
        assert mv.tags["eval_id"] == EVAL_ID
        assert mv.tags["data_version"] == DATA_VERSION
        assert mv.tags["prompt_version"] == PROMPT_VERSION
        assert mv.tags["git_commit"] == TRAIN_GIT_COMMIT
        assert mv.tags["record_validity"] == "valid"
        # 未声明即缺省：scope/批准 tag 不写
        assert "offline_backup_scope" not in mv.tags
        assert "production_approved" not in mv.tags

    def test_register_creates_no_runs_and_no_alias(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
    ) -> None:
        client = _client(registry)
        # 注册不新建任何 Run（训练链 4 个、测评链 2 个保持不变）
        train_runs = list(
            client.search_runs(
                [train_store.experiment_id], run_view_type=ViewType.ALL, max_results=100
            )
        )
        eval_runs = list(
            client.search_runs(
                [eval_store.experiment_id], run_view_type=ViewType.ALL, max_results=100
            )
        )
        assert len(train_runs) == 4  # 父 Run + fold0/1/2
        assert len(eval_runs) == 2  # 父 Run + fold0

        # 注册不自动设置任何 alias（禁止隐式最新/隐式候选）
        for alias in ("candidate", "production"):
            with pytest.raises(MlflowException):
                client.get_model_version_by_alias("mVllm2", alias)
        with pytest.raises(RegistryModelNotFound):
            get_model_by_alias(registry, "candidate")

    def test_register_accepts_archived_train_and_archived_eval(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        # §10 completed|archived 均放行（train 与 eval 两侧同规则）
        _complete_training(train_store)
        register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        _pass_eval(eval_store, data_root)
        transition_train_state(train_store, TRAIN_ID, "archived")
        transition_eval_state(eval_store, EVAL_ID, "archived")

        record = finalize_model_evaluation(registry, MODEL_ID, eval_id=EVAL_ID)
        assert record.record_validity == "valid"
        assert record.version == 1

    def test_register_assigns_sequential_numeric_versions(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        first = _golden_register(registry, train_store, eval_store, data_root)
        second = _golden_register(
            registry,
            train_store,
            eval_store,
            data_root,
            model_id=OTHER_MODEL_ID,
            train_id=OTHER_TRAIN_ID,
            eval_id=OTHER_EVAL_ID,
        )
        assert first.version == 1
        assert second.version == 2
        # model_id 与数值 Model Version 一一对应（§13.1），可精确读回
        assert get_model(registry, MODEL_ID).version == 1
        assert get_model(registry, OTHER_MODEL_ID).version == 2
        assert len(_raw_model_versions(registry)) == 2

    @pytest.mark.parametrize("bad_model_id", BAD_MODEL_IDS)
    def test_register_rejects_malformed_model_id(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
        bad_model_id,
    ) -> None:
        _complete_training(train_store)
        with pytest.raises(InvalidIdentifier):
            register_model(registry, bad_model_id, train_id=TRAIN_ID)
        assert _raw_model_versions(registry) == []

    @pytest.mark.parametrize("bad_train_id", BAD_TRAIN_IDS)
    def test_register_rejects_malformed_train_id(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
        bad_train_id,
    ) -> None:
        _complete_training(train_store)
        with pytest.raises(InvalidIdentifier):
            register_model(registry, MODEL_ID, train_id=bad_train_id)
        assert _raw_model_versions(registry) == []

    @pytest.mark.parametrize("bad_eval_id", BAD_EVAL_IDS)
    def test_finalize_rejects_malformed_eval_id(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
        bad_eval_id,
    ) -> None:
        _complete_training(train_store)
        register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        _pass_eval(eval_store, data_root)
        with pytest.raises(InvalidIdentifier):
            finalize_model_evaluation(registry, MODEL_ID, eval_id=bad_eval_id)
        assert get_model(registry, MODEL_ID).eval_id is None

    @pytest.mark.parametrize("malformed", MALFORMED_QUOTED_MODEL_IDS)
    def test_register_and_get_reject_quoted_injection_ids(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        malformed,
    ) -> None:
        # P3 同型回归：读/写入口先 parse_model_id——不泄漏 MlflowException、
        # 不静默当作"不存在"，一律 InvalidIdentifier
        with pytest.raises(InvalidIdentifier):
            register_model(registry, malformed, train_id=TRAIN_ID)
        with pytest.raises(InvalidIdentifier):
            get_model(registry, malformed)

    def test_register_rejects_running_train(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        _make_train(train_store)  # 仅创建父 Run（running/RUNNING）
        with pytest.raises(PromotionGateRejected):
            _register(registry)
        assert _raw_model_versions(registry) == []

    @pytest.mark.parametrize(
        "state,run_status", [("partial", "KILLED"), ("failed", "FAILED")]
    )
    def test_register_rejects_partial_or_failed_train(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
        state: str,
        run_status: str,
    ) -> None:
        _make_train(train_store)
        transition_train_state(train_store, TRAIN_ID, state, run_status=run_status)
        with pytest.raises(PromotionGateRejected):
            _register(registry)
        assert _raw_model_versions(registry) == []

    def test_register_rejects_invalid_train(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        _complete_training(train_store)
        mark_train_invalid(train_store, TRAIN_ID)
        with pytest.raises(PromotionGateRejected):
            _register(registry)
        assert _raw_model_versions(registry) == []

    def test_register_rejects_completed_train_that_references_holdout(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        data_root: Path,
    ) -> None:
        holdout_version = "data-v4.1-r9"
        working = data_root / "working" / "round-holdout"
        working.mkdir(parents=True)
        (working / "clip.bin").write_bytes(b"holdout")
        stage_release(
            data_root, "round-holdout", "v4.1", version=holdout_version
        )
        seal_release(
            data_root,
            holdout_version,
            purpose="holdout",
            description="registry 训练引用反向测试",
            sample_count=1,
            source_batches=["fixture"],
            splits={"test": {"train": 0, "validation": 1}},
        )
        _make_train(train_store, data_version=holdout_version)
        for fold in (0, 1, 2):
            create_fold_run(train_store, TRAIN_ID, fold)
            log_fold_metrics(train_store, TRAIN_ID, fold, TRAIN_FOLD_METRICS)
            end_fold_run(train_store, TRAIN_ID, fold, "FINISHED")
        log_train_summary(train_store, TRAIN_ID, TRAIN_SUMMARY_METRICS)
        transition_train_state(train_store, TRAIN_ID, "completed")

        with pytest.raises(PromotionGateRejected, match="可训练 development"):
            register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        assert _raw_model_versions(registry) == []

    def test_register_rejects_missing_train(
        self,
        registry: ModelRegistryStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        with pytest.raises(PromotionGateRejected):
            register_model(registry, MODEL_ID, train_id=UNKNOWN_TRAIN_ID)
        assert _raw_model_versions(registry) == []

    def test_finalize_rejects_missing_eval(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        data_root: Path,
    ) -> None:
        _complete_training(train_store)
        register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        with pytest.raises(PromotionGateRejected):
            finalize_model_evaluation(registry, MODEL_ID, eval_id=UNKNOWN_EVAL_ID)
        assert get_model(registry, MODEL_ID).eval_id is None

    def test_register_rejects_running_eval(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        _complete_training(train_store)
        register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        create_eval_run(
            eval_store,
            EVAL_ID,
            model_id=MODEL_ID,
            model_version_number=1,
            data_version=DATA_VERSION,
            config=CONFIG,
            git_commit=EVAL_GIT_COMMIT,
            scope="single_fold",
            split="validation/fold0",
            data_root=data_root,
        )  # 仅创建（running/RUNNING）
        with pytest.raises(PromotionGateRejected):
            finalize_model_evaluation(registry, MODEL_ID, eval_id=EVAL_ID)
        assert get_model(registry, MODEL_ID).eval_id is None

    def test_register_rejects_failed_outcome_eval(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        # §5.5/§10：质量未达标的 outcome=failed 是有效证据，但不允许晋级
        _complete_training(train_store)
        register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        _pass_eval(eval_store, data_root, outcome="failed")
        with pytest.raises(PromotionGateRejected):
            finalize_model_evaluation(registry, MODEL_ID, eval_id=EVAL_ID)
        assert get_model(registry, MODEL_ID).eval_id is None

    def test_register_rejects_invalid_eval(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        _complete_training(train_store)
        register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        _pass_eval(eval_store, data_root)
        mark_eval_invalid(eval_store, EVAL_ID)
        with pytest.raises(PromotionGateRejected):
            finalize_model_evaluation(registry, MODEL_ID, eval_id=EVAL_ID)
        assert get_model(registry, MODEL_ID).eval_id is None

    def test_register_rejects_eval_for_other_model(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        # 关联校验：eval 的 model_id tag 指向另一个模型时不允许注册本模型
        _complete_training(train_store)
        register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        with pytest.raises(IllegalEvalRecord):
            _pass_eval(eval_store, data_root, model_id=OTHER_MODEL_ID)
        assert get_model(registry, MODEL_ID).eval_id is None

    def test_register_duplicate_model_id_conflicts_before_gates(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
    ) -> None:
        # §11.6 同名立即停止：冲突检测优先于 train 晋级门。
        with pytest.raises(ModelVersionConflict):
            register_model(registry, MODEL_ID, train_id=TRAIN_ID)
        # 原数值版本不动、不新增版本
        assert len(_raw_model_versions(registry)) == 1
        original = _raw_model_version(registry, 1)
        assert original.tags["model_id"] == MODEL_ID
        assert original.tags["eval_id"] == EVAL_ID


# —————————————————— T3 读取 fail-closed（model_id 唯一/不改绑）——————————————————


class TestModelReads:
    """get_model：精确检索、审计快照、篡改/重复 model_id 一律 fail-closed。"""

    def test_get_model_returns_stable_snapshot(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        first = get_model(registry, MODEL_ID)
        again = get_model(registry, MODEL_ID)
        assert first == again  # frozen dataclass 值相等
        assert first.model_id == MODEL_ID
        assert first.version == 1
        assert first.train_id == TRAIN_ID
        assert first.eval_id == EVAL_ID
        assert first.record_validity == "valid"

    def test_get_model_unknown_raises_not_found(
        self, registry: ModelRegistryStore
    ) -> None:
        with pytest.raises(RegistryModelNotFound):
            get_model(registry, UNKNOWN_MODEL_ID)

    @pytest.mark.parametrize("bad_model_id", BAD_MODEL_IDS)
    def test_get_model_malformed_id_raises_invalid_identifier(
        self, registry: ModelRegistryStore, bad_model_id
    ) -> None:
        with pytest.raises(InvalidIdentifier):
            get_model(registry, bad_model_id)

    def test_get_model_rejects_duplicate_model_id_tag(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
    ) -> None:
        # raw 绕过门伪造同 model_id 的第二数值版本（模拟人工/异常操作）；
        # 其余 tags 给全合法值，使唯一连例 = model_id 重复（§5.4 唯一性）
        artifact_uri = _client(registry).get_run(golden.run_id).info.artifact_uri
        _client(registry).create_model_version(
            "mVllm2",
            source=artifact_uri,
            run_id=golden.run_id,
            tags={
                "model_id": MODEL_ID,
                "train_id": TRAIN_ID,
                "eval_id": EVAL_ID,
                "data_version": DATA_VERSION,
                "prompt_version": PROMPT_VERSION,
                "git_commit": TRAIN_GIT_COMMIT,
                "record_validity": "valid",
            },
        )
        with pytest.raises(IllegalRegistryRecord):
            get_model(registry, MODEL_ID)

    @pytest.mark.parametrize("tag,junk", TAMPERED_TAG_CASES)
    def test_get_model_rejects_tampered_tags(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        tag: str,
        junk: str,
    ) -> None:
        # 读取 fail-closed：任何绑定/值域 tag 篡改（人工或异常操作）即拒绝
        _client(registry).set_model_version_tag("mVllm2", "1", tag, junk)
        with pytest.raises(IllegalRegistryRecord):
            get_model(registry, MODEL_ID)


# —————————————————— T4 record_validity（D039）——————————————————


class TestRecordValidity:
    """mark_model_invalid：单向、隔离；invalid 被全部下游拒绝且优先于门。"""

    def test_mark_invalid_sets_tag_idempotent_and_isolated(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")

        marked = mark_model_invalid(registry, MODEL_ID)
        assert marked.record_validity == "invalid"
        mv = _raw_model_version(registry, 1)
        assert mv.tags["record_validity"] == "invalid"
        # 只动 validity：alias 保留（路由收口在读取侧）、scope 保留、绑定不动
        assert sorted(mv.aliases) == ["candidate"]
        assert mv.tags["offline_backup_scope"] == "adapter"
        assert mv.tags["model_id"] == MODEL_ID
        assert mv.tags["train_id"] == TRAIN_ID

        # 同值幂等（B6/B7 同型）；模块不提供改回 valid 的入口
        again = mark_model_invalid(registry, MODEL_ID)
        assert again.record_validity == "invalid"

    def test_mark_unknown_model_raises_not_found(
        self, registry: ModelRegistryStore
    ) -> None:
        with pytest.raises(RegistryModelNotFound):
            mark_model_invalid(registry, UNKNOWN_MODEL_ID)

    def test_get_model_returns_invalid_snapshot_for_audit(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        mark_model_invalid(registry, MODEL_ID)
        record = get_model(registry, MODEL_ID)
        assert record.model_id == MODEL_ID
        assert record.record_validity == "invalid"

    def test_routing_read_rejects_invalid_target(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")
        mark_model_invalid(registry, MODEL_ID)
        # §13.1：alias 只能指向有效版本，路由读 fail-closed
        with pytest.raises(InvalidModelRecord):
            get_model_by_alias(registry, "candidate")

    def test_routing_read_rechecks_finalized_eval_online(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        eval_store: EvalRecordStore,
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")
        mark_eval_invalid(eval_store, EVAL_ID)
        with pytest.raises(PromotionGateRejected):
            get_model_by_alias(registry, "candidate")

    def test_alias_and_approve_reject_invalid_model(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        mark_model_invalid(registry, MODEL_ID)
        with pytest.raises(InvalidModelRecord):
            set_alias(registry, MODEL_ID, "candidate")
        with pytest.raises(InvalidModelRecord):
            approve_model_for_production(registry, MODEL_ID)

    def test_invalid_precedes_scope_gate(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        # invalid 优先于一切门条件（同 B6 纪律）：无 scope 也报 invalid 而非门拒绝
        mark_model_invalid(registry, MODEL_ID)
        with pytest.raises(InvalidModelRecord):
            set_alias(registry, MODEL_ID, "candidate")


# —————————————————— T5 offline_backup_scope（§2.11/D036 单向粘性）——————————————————


class TestOfflineBackupScope:
    """set_offline_backup_scope：值域、单向升级、幂等、跨 alias 粘性。"""

    def test_scope_upgrade_missing_adapter_production_bundle(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        assert golden.offline_backup_scope is None

        record = set_offline_backup_scope(registry, MODEL_ID, "adapter")
        assert record.offline_backup_scope == "adapter"
        assert _raw_model_version(registry, 1).tags["offline_backup_scope"] == "adapter"

        upgraded = set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        assert upgraded.offline_backup_scope == "production_bundle"
        assert (
            _raw_model_version(registry, 1).tags["offline_backup_scope"]
            == "production_bundle"
        )
        # 只写 scope tag，不触碰其他 tags
        mv = _raw_model_version(registry, 1)
        assert mv.tags["model_id"] == MODEL_ID
        assert mv.tags["record_validity"] == "valid"
        assert "production_approved" not in mv.tags

    def test_scope_same_value_idempotent(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        again = set_offline_backup_scope(registry, MODEL_ID, "adapter")
        assert again.offline_backup_scope == "adapter"
        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        same = set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        assert same.offline_backup_scope == "production_bundle"

    def test_scope_downgrade_rejected(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        # §2.11：不得降级（也不得清除）——委托状态机异常
        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        with pytest.raises(IllegalTransition):
            set_offline_backup_scope(registry, MODEL_ID, "adapter")
        assert (
            _raw_model_version(registry, 1).tags["offline_backup_scope"]
            == "production_bundle"
        )

    @pytest.mark.parametrize("bad_scope", BAD_SCOPES)
    def test_scope_unknown_values_rejected(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        bad_scope,
    ) -> None:
        # 值域仅 adapter/production_bundle：五类名/组合串/清除值一律拒绝
        with pytest.raises(IllegalRegistryRecord):
            set_offline_backup_scope(registry, MODEL_ID, bad_scope)
        assert "offline_backup_scope" not in _raw_model_version(registry, 1).tags

    def test_scope_unknown_model_raises_not_found(
        self, registry: ModelRegistryStore
    ) -> None:
        with pytest.raises(RegistryModelNotFound):
            set_offline_backup_scope(registry, UNKNOWN_MODEL_ID, "adapter")

    def test_scope_sticky_across_alias_switch_and_delete(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        # 粘性：alias 切走/删除后 scope 不得降级或清除（§2.11）
        _golden_register(registry, train_store, eval_store, data_root)
        _golden_register(
            registry,
            train_store,
            eval_store,
            data_root,
            model_id=OTHER_MODEL_ID,
            train_id=OTHER_TRAIN_ID,
            eval_id=OTHER_EVAL_ID,
        )
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")

        # 切走 candidate → 旧模型 scope 不变
        set_offline_backup_scope(registry, OTHER_MODEL_ID, "adapter")
        set_alias(registry, OTHER_MODEL_ID, "candidate")
        assert _raw_model_version(registry, 1).tags["offline_backup_scope"] == "adapter"

        # 删除 alias 后仍粘性
        delete_alias(registry, "candidate")
        assert _raw_model_version(registry, 1).tags["offline_backup_scope"] == "adapter"
        assert _raw_model_version(registry, 2).tags["offline_backup_scope"] == "adapter"


# —————————————————— T6 alias 管理（唯一可变路由入口）——————————————————


class TestAliasManagement:
    """set_alias/delete_alias/get_model_by_alias：显式绑定/切换/删除，无隐式最新。"""

    def test_candidate_full_path(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        record = set_alias(registry, MODEL_ID, "candidate")

        assert record.model_id == MODEL_ID
        assert record.aliases == ("candidate",)

        # 路由读解析到精确数值版本；raw alias 同一目标
        resolved = get_model_by_alias(registry, "candidate")
        assert resolved.model_id == MODEL_ID
        assert resolved.version == 1
        assert (
            _client(registry).get_model_version_by_alias("mVllm2", "candidate").version
            == 1
        )
        # 绑定 tags 原样（alias 不改写实体）
        mv = _raw_model_version(registry, 1)
        assert mv.tags["model_id"] == MODEL_ID
        assert mv.tags["offline_backup_scope"] == "adapter"

    def test_candidate_requires_scope_before_alias(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        # §2.11：先写 scope 再设 alias；缺失即门拒绝
        with pytest.raises(PromotionGateRejected):
            set_alias(registry, MODEL_ID, "candidate")
        # fail-closed：门拒绝后 alias 不落 Registry（无半写）
        with pytest.raises(MlflowException):
            _client(registry).get_model_version_by_alias("mVllm2", "candidate")

    def test_production_requires_production_bundle_scope(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        # scope 缺失
        with pytest.raises(PromotionGateRejected):
            set_alias(registry, MODEL_ID, "production")
        # scope=adapter 不足以进入 production（先升级 production_bundle）
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        with pytest.raises(PromotionGateRejected):
            set_alias(registry, MODEL_ID, "production")
        with pytest.raises(MlflowException):
            _client(registry).get_model_version_by_alias("mVllm2", "production")

    def test_production_requires_user_approval(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        with pytest.raises(PromotionGateRejected):
            set_alias(registry, MODEL_ID, "production")
        with pytest.raises(MlflowException):
            _client(registry).get_model_version_by_alias("mVllm2", "production")

    def test_production_full_path_with_candidate(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")
        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        approved = approve_model_for_production(registry, MODEL_ID)
        assert approved.production_approved is True

        record = set_alias(registry, MODEL_ID, "production")
        # 同一模型可同时持有两个别名（字母序）
        assert record.aliases == ("candidate", "production")
        assert get_model_by_alias(registry, "production").model_id == MODEL_ID
        assert (
            _client(registry).get_model_version_by_alias("mVllm2", "production").version
            == 1
        )

    def test_approve_sets_tag_gates_online_and_idempotent(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        eval_store: EvalRecordStore,
    ) -> None:
        approve_model_for_production(registry, MODEL_ID)
        assert _raw_model_version(registry, 1).tags["production_approved"] == "true"

        # 重复批准幂等
        approve_model_for_production(registry, MODEL_ID)
        assert _raw_model_version(registry, 1).tags["production_approved"] == "true"

        # 质量门在线复验（D039）：eval 失效后不得批准
        mark_eval_invalid(eval_store, EVAL_ID)
        with pytest.raises(PromotionGateRejected):
            approve_model_for_production(registry, MODEL_ID)

    def test_approve_rejects_tampered_eval_model_binding(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        eval_store: EvalRecordStore,
    ) -> None:
        # B8 P2 回归：approve 在线复验关联校验（D039 下游入口在线核对）——
        # raw 篡改 eval 父 Run 的 model_id tag 指向另一合法模型 ID（parse 可
        # 过、其余结构完整）后，批准必须 PromotionGateRejected 且无半写；
        # 篡改恢复后正常批准路径不受影响。
        eval_run_id = get_eval_run(eval_store, EVAL_ID).run_id
        client = _client(registry)

        client.set_tag(eval_run_id, EVAL_MODEL_ID_TAG, OTHER_MODEL_ID)
        # 篡改生效且 eval 记录本身仍可读（拒绝只能来自关联校验，非结构门）
        assert get_eval_run(eval_store, EVAL_ID).model_id == OTHER_MODEL_ID

        with pytest.raises(PromotionGateRejected):
            approve_model_for_production(registry, MODEL_ID)
        # fail-closed：拒绝时无半写（批准 tag 未落 Registry）
        assert PRODUCTION_APPROVED_TAG not in _raw_model_version(registry, 1).tags

        # 恢复原始 model_id 绑定后：正常批准路径不受篡改影响
        client.set_tag(eval_run_id, EVAL_MODEL_ID_TAG, MODEL_ID)
        approved = approve_model_for_production(registry, MODEL_ID)
        assert approved.production_approved is True
        assert _raw_model_version(registry, 1).tags[PRODUCTION_APPROVED_TAG] == "true"

    @pytest.mark.parametrize("bad_alias", BAD_ALIASES)
    def test_alias_value_domain_rejected_without_side_effects(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        bad_alias,
    ) -> None:
        # 域门先于 MLflow（raw MLflow 会接受 "prod"/"Candidate"）；不产生任何别名
        with pytest.raises(IllegalRegistryRecord):
            set_alias(registry, MODEL_ID, bad_alias)
        with pytest.raises(IllegalRegistryRecord):
            get_model_by_alias(registry, bad_alias)
        with pytest.raises(IllegalRegistryRecord):
            delete_alias(registry, bad_alias)
        assert _raw_model_version(registry, 1).aliases == []

    def test_alias_unknown_model_raises_not_found(
        self, registry: ModelRegistryStore
    ) -> None:
        with pytest.raises(RegistryModelNotFound):
            set_alias(registry, UNKNOWN_MODEL_ID, "candidate")

    def test_alias_switch_moves_route_without_mutating_entities(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        _golden_register(registry, train_store, eval_store, data_root)
        _golden_register(
            registry,
            train_store,
            eval_store,
            data_root,
            model_id=OTHER_MODEL_ID,
            train_id=OTHER_TRAIN_ID,
            eval_id=OTHER_EVAL_ID,
        )
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")
        before = _stable_entity_view(_raw_model_version(registry, 1))

        # 显式切换 candidate → 另一模型
        set_offline_backup_scope(registry, OTHER_MODEL_ID, "adapter")
        set_alias(registry, OTHER_MODEL_ID, "candidate")

        assert get_model_by_alias(registry, "candidate").model_id == OTHER_MODEL_ID
        # 旧模型实体逐字段不动（§5.4 别名变化不回写）
        assert _stable_entity_view(_raw_model_version(registry, 1)) == before
        record = get_model(registry, MODEL_ID)
        assert record.aliases == ()
        assert record.record_validity == "valid"

    def test_alias_same_target_idempotent(
        self, golden: RegisteredModelRecord, registry: ModelRegistryStore
    ) -> None:
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")
        again = set_alias(registry, MODEL_ID, "candidate")
        assert again.aliases == ("candidate",)
        assert get_model_by_alias(registry, "candidate").version == 1

    def test_delete_alias_explicit_and_no_implicit_latest(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        _golden_register(registry, train_store, eval_store, data_root)
        _golden_register(
            registry,
            train_store,
            eval_store,
            data_root,
            model_id=OTHER_MODEL_ID,
            train_id=OTHER_TRAIN_ID,
            eval_id=OTHER_EVAL_ID,
        )
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")

        affected = delete_alias(registry, "candidate")
        assert affected.model_id == MODEL_ID
        assert affected.aliases == ()

        # 删除后解析 fail-closed：即使 Registry 有两个已注册模型也不回退任何"最新"
        with pytest.raises(RegistryModelNotFound):
            get_model_by_alias(registry, "candidate")
        with pytest.raises(MlflowException):
            _client(registry).get_model_version_by_alias("mVllm2", "candidate")

        # 再删 fail-closed（MLflow 原生 delete 静默，模块必须先行解析校验）
        with pytest.raises(RegistryModelNotFound):
            delete_alias(registry, "candidate")

        # 实体不动
        mv = _raw_model_version(registry, 1)
        assert mv.tags["model_id"] == MODEL_ID
        assert mv.aliases == []

    def test_alias_gate_rechecks_train_online(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
    ) -> None:
        # D039：下游入口在线核对——train 注册后失效，candidate 门必须拒绝
        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        mark_train_invalid(train_store, TRAIN_ID)
        with pytest.raises(PromotionGateRejected):
            set_alias(registry, MODEL_ID, "candidate")
        with pytest.raises(MlflowException):
            _client(registry).get_model_version_by_alias("mVllm2", "candidate")

    def test_production_gate_rechecks_eval_online(
        self,
        golden: RegisteredModelRecord,
        registry: ModelRegistryStore,
        eval_store: EvalRecordStore,
    ) -> None:
        # 质量门在线复验：批准后 eval 失效，production 门必须拒绝
        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        approve_model_for_production(registry, MODEL_ID)
        mark_eval_invalid(eval_store, EVAL_ID)
        with pytest.raises(PromotionGateRejected):
            set_alias(registry, MODEL_ID, "production")
        with pytest.raises(MlflowException):
            _client(registry).get_model_version_by_alias("mVllm2", "production")

    def test_alias_lifecycle_never_rewrites_model_entity(
        self,
        registry: ModelRegistryStore,
        train_store: TrainRecordStore,
        eval_store: EvalRecordStore,
        data_root: Path,
    ) -> None:
        # 全 alias 生命周期（绑定/切换/删除/双别名/批准）后：数值版本数量、
        # 实体不可变视图逐一相等（alias 是唯一可变路由入口，§5.4/任务要点 3）
        _golden_register(registry, train_store, eval_store, data_root)
        _golden_register(
            registry,
            train_store,
            eval_store,
            data_root,
            model_id=OTHER_MODEL_ID,
            train_id=OTHER_TRAIN_ID,
            eval_id=OTHER_EVAL_ID,
        )
        v1_before = _stable_entity_view(_raw_model_version(registry, 1))
        v2_before = _stable_entity_view(_raw_model_version(registry, 2))

        set_offline_backup_scope(registry, MODEL_ID, "adapter")
        set_alias(registry, MODEL_ID, "candidate")
        set_offline_backup_scope(registry, OTHER_MODEL_ID, "adapter")
        set_alias(registry, OTHER_MODEL_ID, "candidate")  # 显式切换
        delete_alias(registry, "candidate")
        set_offline_backup_scope(registry, MODEL_ID, "production_bundle")
        approve_model_for_production(registry, MODEL_ID)
        set_alias(registry, MODEL_ID, "production")
        set_alias(registry, MODEL_ID, "candidate")
        delete_alias(registry, "production")
        delete_alias(registry, "candidate")

        assert len(_raw_model_versions(registry)) == 2
        assert _stable_entity_view(_raw_model_version(registry, 1)) == v1_before
        assert _stable_entity_view(_raw_model_version(registry, 2)) == v2_before

        # 可变 tags 仅按显式操作落位
        v1_tags = _raw_model_version(registry, 1).tags
        assert v1_tags["offline_backup_scope"] == "production_bundle"
        assert v1_tags["production_approved"] == "true"
        assert v1_tags["record_validity"] == "valid"
        assert _raw_model_version(registry, 2).tags["offline_backup_scope"] == "adapter"

        # 删除全部别名后，路由读 fail-closed
        for alias in ("candidate", "production"):
            with pytest.raises(RegistryModelNotFound):
                get_model_by_alias(registry, alias)
