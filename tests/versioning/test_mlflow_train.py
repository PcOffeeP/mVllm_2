"""B6 — MLflow 训练记录：train-v 父 Run + 三折嵌套子 Run + workflow_state 状态映射。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
§2.6（MLflow 是训练事实唯一权威；workflow_state/record_validity tags；SQLite
单文件 + 本地 artifact store；不得启动服务、不得连接正式 store）、
§2.7 + D022（一个 ``train-v<协议>-r<N>`` = 一个父 Run；fold0/1/2 为嵌套子 Run，
不分配独立版本；父 Run 记三折共用输入；三折汇总写父 Run；任一必需 fold 未
完成时父 Run 不得 completed）、§5.3 + D038（prepared=无 Run；workflow_state ↔
MLflow 原生 RunStatus 固定组合表；状态流 prepared→running→completed→archived、
running↔partial↔failed；partial/failed 只能受控恢复回 running；父 Run 进入
completed 的门 = 全部必需 fold FINISHED + 汇总完整）、§10（train 行下游规则：
模型晋级只接受 record_validity:valid、原生 FINISHED、项目 completed|archived
且所有子 Run 完整的父 Run；invalid 必须被下游拒绝）、§9/§11.6（显式版本纪律：
train_id 必须显式给出，模块不存在自动分配分支）、§8（同名只增不改）。

预期 production API（供 viber 对照实现，模块 ``versioning.mlflow_train``）::

    # ——— 模块常量（tag 键名钉死；raw MLflow 读回按字面量断言）———
    DEFAULT_TRAIN_EXPERIMENT: str = "mVllm2-training"
    REQUIRED_FOLDS: tuple[int, ...] = (0, 1, 2)
    TRAIN_ID_TAG: str = "train_id"
    WORKFLOW_STATE_TAG: str = "workflow_state"
    DATA_VERSION_TAG: str = "data_version"
    PROMPT_VERSION_TAG: str = "prompt_version"
    GIT_COMMIT_TAG: str = "git_commit"
    BASE_MODEL_TAG: str = "base_model"
    RECORD_VALIDITY_TAG: str = "record_validity"
    SUMMARY_COMPLETE_TAG: str = "summary_complete"
    FOLD_TAG: str = "fold"                    # 子 Run tag 值 "fold0"/"fold1"/"fold2"

    # ——— 异常（基类 MLflowTrainError(ValueError)；状态域异常委托 versioning.state）———
    class MLflowTrainError(ValueError)
        # 训练记录域异常基类
    class TrainRecordNotFound(MLflowTrainError)
        # 指定 train 记录或其 fold 子 Run 在本 store 中不存在
    class TrainRunConflict(MLflowTrainError)
        # 同一 train-v... 已存在父 Run（§8 只增不改 / §11.6 同名冲突），
        # 或同父 Run 下同 fold 子 Run 已存在；冲突拒绝，原 Run 一律不动
    class IllegalTrainRecord(MLflowTrainError)
        # 记录构造/操作输入非法或前置条件不满足：共同输入缺失/非法、
        # fold 编号非法、终态 fold 重复终转/恢复、非 running 父 Run 新建 fold、
        # 非法终转状态字符串、空/非法指标等
    class IncompleteTrainRecord(MLflowTrainError)
        # completed 晋级门拒绝：必需 fold 缺失/未 FINISHED、汇总不完整、
        # 或 workflow_state 未达 completed|archived
    class InvalidTrainRecord(MLflowTrainError)
        # record_validity=invalid 的训练记录被下游校验拒绝（§2.6/§10，
        # 不得通过改回 valid 复活旧事实）

    状态转换与组合失败必须抛 ``versioning.state.IllegalTransition`` /
    ``IllegalStateCombination``（直接传播，或以其为基类的子类均可）。

    # ——— store 句柄（真实 MLflow：SQLite 单文件 + 本地 artifact store）———
    @dataclass(frozen=True)
    class TrainRecordStore
        root: Path                 # store 根目录
        tracking_uri: str           # sqlite:///<root>/mlflow.db
        experiment_id: str         # 训练实验 ID（字符串）
        artifact_location: str     # <root>/artifacts（本地目录）

    def open_train_store(root: Path, *,
                         experiment_name: str = DEFAULT_TRAIN_EXPERIMENT
                         ) -> TrainRecordStore
        # 创建（缺失时）root 与 root/artifacts 目录；tracking 指向
        # sqlite:///<root>/mlflow.db；创建或按名复用实验并绑定本地
        # artifact_location；绝不启动服务、绝不连接 root 之外的任何 store；
        # 一切后续函数必须按 store 句柄寻址（不得依赖全局 ambient tracking
        # 状态，双 store 互不可见）。

    # ——— 记录快照（只读视图）———
    @dataclass(frozen=True)
    class FoldRunRecord
        train_id: str
        fold: int
        run_id: str
        parent_run_id: str               # 父 Run MLflow ID（嵌套关联）
        run_name: str                    # "fold<N>"
        status: str                      # 原生 RunStatus：RUNNING/FINISHED/FAILED/KILLED
        metrics: Mapping[str, float]     # 最新值
        params: Mapping[str, str]

    @dataclass(frozen=True)
    class TrainRunRecord
        train_id: str
        run_id: str
        experiment_id: str
        run_name: str                    # == train_id
        workflow_state: str              # 项目工作流状态值
        run_status: str                  # 原生 RunStatus 字符串
        record_validity: str             # "valid" | "invalid"
        data_version: str
        prompt_version: str
        git_commit: str
        base_model: str
        config: Mapping[str, str]              # 冻结训练配置（值一律 str 化）
        metrics: Mapping[str, float]           # 三折汇总指标（父 Run）最新值
        folds: Mapping[int, FoldRunRecord]     # 既有 fold 子 Run，按编号索引

    # ——— 父 Run ———
    def create_train_run(store, train_id: str, *, data_version: str,
                         prompt_version: str, git_commit: str, base_model: str,
                         config: Mapping) -> TrainRunRecord
        # 一个 train-v<协议>-r<N> = 一个父 Run（D022）：
        # - train_id 必须显式给出并经 versioning.ids.parse_train_id 校验：
        #   缺省/None/latest/短前缀/跨类别/r0/前导零/非字符串 -> InvalidIdentifier；
        #   模块不存在任何自动分配下一版本号的分支（§9/§11.6 显式版本纪律）；
        # - data_version / prompt_version 必须分别是经 versioning.ids
        #   parse_data_id / parse_prompt_id 校验通过的完整 ID（§3.3 显式记录）；
        # - git_commit、base_model 必须是非空字符串，否则 IllegalTrainRecord；
        # - config 必填且为 Mapping（缺省/None -> IllegalTrainRecord），键为
        #   非空字符串，值 str/int/float/bool（None 与容器 -> IllegalTrainRecord），
        #   逐项写父 Run params（值 str 化）；
        # Run 创建即执行开始（D038：prepared=无 Run；模块不提供以 prepared
        # 状态创建 Run 的入口）：父 Run 原生 RUNNING、workflow_state=running、
        # record_validity=valid；父 Run tags：train_id / workflow_state /
        # data_version / prompt_version / git_commit / base_model /
        # record_validity；父 Run run_name == train_id。

    def get_train_run(store, train_id: str) -> TrainRunRecord
        # 按 train_id tag 在 store 实验内检索父 Run；不存在 ->
        # TrainRecordNotFound；读取 fail-closed（D038"拒绝人工或异常操作产生
        # 的非法组合"）：workflow_state 与原生状态组合必须经
        # versioning.state.validate_workflow_run_status 校验（非法/垃圾值 ->
        # IllegalStateCombination）；record_validity tag 必须为 valid|invalid
        # （其他 -> IllegalTrainRecord）。

    def list_fold_runs(store, train_id: str) -> tuple[FoldRunRecord, ...]
        # 该 train 的全部子 Run，按 fold 编号升序；train 不存在 ->
        # TrainRecordNotFound。

    # ——— fold 子 Run（fold0/1/2 嵌套子 Run，不分配独立 train-v 版本）———
    def create_fold_run(store, train_id: str, fold: int, *,
                        params: Mapping | None = None) -> FoldRunRecord
        # train 不存在 -> TrainRecordNotFound；父 Run workflow_state 非
        # running -> IllegalTrainRecord（completed/archived 不得原地重跑，§5.3）；
        # fold 必须是 REQUIRED_FOLDS 内的真 int（bool、字符串、float、越界 ->
        # IllegalTrainRecord）；同父 Run 下该 fold 子 Run 已存在 ->
        # TrainRunConflict（标识无重复，原 Run 不动）；
        # 子 Run 原生 RUNNING；tags：fold="fold<N>"、mlflow.runName="fold<N>"、
        # 系统 tag mlflow.parentRunId=父 Run ID（嵌套关联）；子 Run 不写
        # workflow_state / record_validity（项目状态与有效性权威在父 Run）；
        # params 逐项写入子 Run params。

    def log_fold_metrics(store, train_id: str, fold: int,
                         metrics: Mapping[str, float]) -> FoldRunRecord
        # 指标写该 fold 子 Run：非空 Mapping，键非空字符串，值 int/float
        # （bool/None/容器 -> IllegalTrainRecord）；train 或 fold 子 Run
        # 不存在 -> TrainRecordNotFound；返回最新快照（多批取最新值）。

    def end_fold_run(store, train_id: str, fold: int, run_status: str, *,
                     metrics: Mapping[str, float] | None = None) -> FoldRunRecord
        # 子 Run 终转：run_status 必须显式为 "FINISHED"/"FAILED"/"KILLED"
        # （其他 -> IllegalTrainRecord）；仅 RUNNING 子 Run 可终转（已终态 ->
        # IllegalTrainRecord）；可选 metrics 先写后终；train 或 fold 子 Run
        # 不存在 -> TrainRecordNotFound。

    def resume_fold_run(store, train_id: str, fold: int) -> FoldRunRecord
        # 受控恢复（§11.3）：仅 FAILED/KILLED 子 Run 恢复为 RUNNING，原 Run ID
        # 不变（不得新建子 Run 顶替）；FINISHED 不得恢复、RUNNING 无需恢复
        # -> IllegalTrainRecord。

    # ——— 父 Run 状态转换（workflow_state 与原生状态一起转换）———
    def transition_train_state(store, train_id: str,
                               target: WorkflowState | str, *,
                               run_status: str | None = None) -> TrainRunRecord
        # 校验顺序钉死：
        # 1) 读取并校验当前组合（篡改 -> IllegalStateCombination）；
        # 2) versioning.state.transition_workflow_state(current, target)：
        #    非法转换（含自环、partial/failed->completed、目标 prepared、
        #    completed->running、archived->* 等）-> IllegalTransition；
        # 3) 目标原生状态按 §5.3 固定表确定并经 validate_workflow_run_status
        #    校验：running->RUNNING、completed/archived->FINISHED（run_status
        #    缺省取默认，显式给其他值 -> IllegalStateCombination）；
        #    partial/failed 必须显式 run_status="FAILED"|"KILLED"（缺省或
        #    其他值 -> IllegalStateCombination）；
        # 4) target=completed 时执行晋级门：全部 REQUIRED_FOLDS 子 Run 原生
        #    FINISHED + 父 Run 已有三折汇总（summary_complete tag），任一
        #    不满足 -> IncompleteTrainRecord（§2.7/§5.3）；
        # 5) 原生状态与 tag 一起写回（partial/failed -> FAILED/KILLED 终转；
        #    completed/archived -> FINISHED；受控恢复 partial/failed->running
        #    时原生状态恢复 RUNNING，原 Run ID 不变，D038/§11.3）；
        # 6) 写回后组合再次经 validate_workflow_run_status 校验（原子维护）。

    # ——— 汇总与有效性 ———
    def log_train_summary(store, train_id: str,
                         metrics: Mapping[str, float]) -> TrainRunRecord
        # 三折汇总指标写父 Run（§2.7）：非空 Mapping，键非空字符串，值
        # int/float（bool/None/容器 -> IllegalTrainRecord）；逐项写父 Run
        # metrics，并设置父 Run tag summary_complete="true"；train 不存在 ->
        # TrainRecordNotFound。

    def mark_train_invalid(store, train_id: str) -> TrainRunRecord
        # 更正策略（§2.6）：父 Run tag record_validity -> invalid，经
        # versioning.state.transition_record_validity（valid->invalid 允许、
        # 同值幂等、invalid->valid 拒绝）；模块不提供任何改回 valid 的入口。

    def validate_train_for_promotion(store, train_id: str) -> TrainRunRecord
        # §10 train 行下游门（B6 只校验、不实现晋级）：
        # 1) train 不存在 -> TrainRecordNotFound；
        # 2) record_validity=invalid -> InvalidTrainRecord（先于一切门条件）；
        # 3) 当前组合非法 -> IllegalStateCombination；
        # 4) workflow_state 非 completed|archived -> IncompleteTrainRecord；
        # 5) 任一 REQUIRED_FOLDS 子 Run 缺失或非 FINISHED ->
        #    IncompleteTrainRecord；
        # 6) 父 Run 无三折汇总（无 summary_complete tag）->
        #    IncompleteTrainRecord；全部通过返回 TrainRunRecord
        #    （completed 与 archived 均放行，§10）。

语义决策点（测试侧钉定，供实现对照）：
    1. 共同输入编码：data_version/prompt_version/git_commit/base_model 为父 Run
       tags；完整训练配置逐项写父 Run params（MLflow 原生参数概念，§2.5
       “MLflow 记录实际参数”）；返回快照 config 值一律 str 化。
    2. data_version/prompt_version 在 create 时做完整 ID 校验（§3.3 显式记录、
       不自动猜测），但 B6 不做文件系统存在性/冻结一致性检查（属 B5 职责）。
    3. §2.7 的“环境信息”不入本批契约（任务契约五项共同输入），留待后续批次。
    4. Run 创建即 running/RUNNING；模块无任何以 prepared 创建 Run 的入口。
    5. 子 Run 不携带 workflow_state/record_validity tags（权威在父 Run）。
    6. “汇总完整”以 log_train_summary 设置的 summary_complete tag 表达，
       晋级门据此判定。
    7. fold 恢复 = FAILED/KILLED 子 Run 经原 Run ID 恢复 RUNNING，不新建子 Run。

测试环境：真实 MLflow 集成（非 mock）；全部 store 在 pytest ``tmp_path`` 内
（SQLite + 本地 artifact store），不启动服务、不连接任何正式 store。

当前 ``versioning/mlflow_train.py`` 尚不存在，本文件全部用例应为 RED
（collection error：ModuleNotFoundError / ImportError）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from versioning.mlflow_train import (
    DEFAULT_TRAIN_EXPERIMENT,
    REQUIRED_FOLDS,
    FoldRunRecord,
    IllegalTrainRecord,
    IncompleteTrainRecord,
    InvalidTrainRecord,
    MLflowTrainError,
    TrainRecordNotFound,
    TrainRecordStore,
    TrainRunConflict,
    TrainRunRecord,
    create_fold_run,
    create_train_run,
    end_fold_run,
    get_train_run,
    list_fold_runs,
    log_fold_metrics,
    log_train_summary,
    mark_train_invalid,
    open_train_store,
    resume_fold_run,
    transition_train_state,
    validate_train_for_promotion,
)

from versioning import mlflow_train
from versioning.ids import InvalidIdentifier
from versioning.state import (
    ALLOWED_RUN_STATUSES,
    IllegalStateCombination,
    IllegalTransition,
    RecordValidity,
    WorkflowState,
)

TRAIN_ID = "train-v4.1-r1"
OTHER_TRAIN_ID = "train-v4.1-r2"
UNKNOWN_ID = "train-v4.1-r9"
GIT_COMMIT = "a1b2c3d"
BASE_MODEL = "MiniCPM-V-4.5"

COMMON_INPUTS: dict = {
    "data_version": "data-v4.1-r1",
    "prompt_version": "prompt-v4.1-r1",
    "git_commit": GIT_COMMIT,
    "base_model": BASE_MODEL,
    "config": {"epochs": 3, "lora_rank": 16, "seed": 42, "learning_rate": 1e-4},
}
CONFIG_AS_STR = {
    "epochs": "3",
    "lora_rank": "16",
    "seed": "42",
    "learning_rate": "0.0001",
}

FOLD_METRICS = {
    0: {"fold_f1": 0.81, "fold_loss": 0.42},
    1: {"fold_f1": 0.79, "fold_loss": 0.45},
    2: {"fold_f1": 0.80, "fold_loss": 0.44},
}
SUMMARY_METRICS = {"cv_f1_mean": 0.8, "cv_f1_std": 0.01}

# 非法 fold 编号：越界、负数、字符串、bool（True 是 int 子类，须显式拒绝）、
# None、float（与 ids.py 的 bool/类型纪律一致）。
BAD_FOLDS = [3, -1, "0", True, False, None, 2.0]

# 非法 train_id：缺省/None、latest、短前缀、跨类别、r0、前导零、非字符串、空串。
BAD_TRAIN_IDS = [
    None,
    "latest",
    "train-latest",
    "train-v4.1",
    "model-v4.1-r1",
    "data-v4.1-r1",
    "train-v4.1-r0",
    "train-v4.1-r01",
    41,
    "",
]

# 典型单引号布尔注入串（P3 回归的代表性畸形输入）。
INJECTION_TRAIN_ID = "train-v4.1-r1' OR '1'='1"

# P3 回归（B6 复审）：含引号/注入样式的畸形 train_id。修复前读路径入口
# 不校验 train_id 即拼进 MLflow filter_string：单引号族在 MLflow 查询解析器
# 抛 MlflowException（域校验泄漏为底层异常）；双引号/尾随换行族被静默当作
# "不存在"（TrainRecordNotFound，与未知合法 ID 混淆）；非字符串同理。修复后
# 读路径入口先 parse_train_id，一律 InvalidIdentifier。
MALFORMED_QUOTED_TRAIN_IDS = [
    INJECTION_TRAIN_ID,    # 单引号布尔注入（修复前 -> MlflowException）
    "train-v4.1-r1'; --",  # 单引号 + SQL 注释（修复前 -> MlflowException）
    "train-v'4.1'-r1",    # 协议段内嵌单引号（修复前 -> MlflowException）
    'train-v4.1-r1"',     # 双引号（修复前 -> 静默 TrainRecordNotFound）
    "train-v4.1-r1\n",    # 尾随换行（修复前 -> 静默 TrainRecordNotFound）
    None,                  # 非字符串（修复前 -> TrainRecordNotFound）
    41,                    # 非字符串（修复前 -> TrainRecordNotFound）
]


# —————————————————— fixtures 与 helpers ——————————————————


@pytest.fixture()
def store(tmp_path: Path) -> TrainRecordStore:
    """每个用例独立 tmp_path store（SQLite + 本地 artifacts，真实 MLflow）。"""
    return open_train_store(tmp_path)


@pytest.fixture()
def record(store: TrainRecordStore) -> TrainRunRecord:
    """已创建的 train-v4.1-r1 父 Run（running/RUNNING）。"""
    return _create(store)


def _create(
    store: TrainRecordStore, train_id: str = TRAIN_ID, **overrides: object
) -> TrainRunRecord:
    inputs: dict = dict(COMMON_INPUTS)
    inputs.update(overrides)
    return create_train_run(store, train_id, **inputs)


def _client(store: TrainRecordStore) -> MlflowClient:
    """raw MLflow 读回通道（真实集成断言；篡改模拟"人工或异常操作"）。"""
    return MlflowClient(tracking_uri=store.tracking_uri)


def _raw_run(store: TrainRecordStore, run_id: str):
    return _client(store).get_run(run_id)


def _children(store: TrainRecordStore, parent_run_id: str) -> list:
    """按 §2.7 的嵌套子 Run 查询方式（parentRunId tag filter）取子 Run。"""
    return list(
        _client(store).search_runs(
            [store.experiment_id],
            filter_string=f"tags.mlflow.parentRunId = '{parent_run_id}'",
            max_results=100,
        )
    )


def _parents(store: TrainRecordStore, train_id: str) -> list:
    return list(
        _client(store).search_runs(
            [store.experiment_id],
            filter_string=f"tags.train_id = '{train_id}'",
            max_results=100,
        )
    )


def _all_runs(store: TrainRecordStore) -> list:
    """store 实验内全部 Run（“无 Run 产生”断言用）。"""
    return list(_client(store).search_runs([store.experiment_id], max_results=100))


def _finish_all_folds(store: TrainRecordStore, train_id: str = TRAIN_ID) -> None:
    """三折全部建 Run、写指标并 FINISHED（不写汇总、不动父 Run 状态）。"""
    for fold in REQUIRED_FOLDS:
        create_fold_run(store, train_id, fold)
        log_fold_metrics(store, train_id, fold, FOLD_METRICS[fold])
        end_fold_run(store, train_id, fold, "FINISHED")


def _complete_training(
    store: TrainRecordStore, train_id: str = TRAIN_ID
) -> TrainRunRecord:
    """三折 FINISHED + 汇总 + completed（合法完成路径）。"""
    _finish_all_folds(store, train_id)
    log_train_summary(store, train_id, SUMMARY_METRICS)
    return transition_train_state(store, train_id, "completed")


def _prepare_state(store: TrainRecordStore, state: str) -> TrainRunRecord:
    """把 train-v4.1-r1 置于指定 workflow_state（合法路径抵达）。"""
    record = _create(store)
    if state == "running":
        return record
    if state in ("partial", "failed"):
        return transition_train_state(
            store,
            TRAIN_ID,
            state,
            run_status="FAILED" if state == "failed" else "KILLED",
        )
    completed = _complete_training(store)
    if state == "archived":
        return transition_train_state(store, TRAIN_ID, "archived")
    return completed


def _assert_combo_legal(record: TrainRunRecord) -> None:
    """快照组合必须落在 §5.3 固定表内（委托 versioning.state 的表）。"""
    allowed = ALLOWED_RUN_STATUSES[WorkflowState(record.workflow_state)]
    assert record.run_status in allowed


# —————————————————— T1 store 句柄 ——————————————————


class TestTrainRecordStore:
    def test_open_store_uses_local_sqlite_and_artifacts(self, tmp_path: Path) -> None:
        store = open_train_store(tmp_path)
        assert isinstance(store, TrainRecordStore)
        assert store.root.resolve() == tmp_path.resolve()
        assert store.tracking_uri.startswith("sqlite:///")
        assert store.tracking_uri.endswith("mlflow.db")
        assert str(tmp_path) in store.tracking_uri
        assert (tmp_path / "mlflow.db").is_file()
        assert (tmp_path / "artifacts").is_dir()
        assert (
            Path(store.artifact_location).resolve()
            == (tmp_path / "artifacts").resolve()
        )

        experiment = _client(store).get_experiment(store.experiment_id)
        assert Path(experiment.artifact_location).resolve() == (
            (tmp_path / "artifacts").resolve()
        )

    def test_experiment_reused_by_name_and_new_name_creates_new(
        self, tmp_path: Path
    ) -> None:
        first = open_train_store(tmp_path)
        again = open_train_store(tmp_path)
        assert again.experiment_id == first.experiment_id

        other = open_train_store(tmp_path, experiment_name="other-experiment")
        assert other.experiment_id != first.experiment_id

    def test_stores_are_isolated(self, tmp_path: Path) -> None:
        # §2.6 不连正式 store；模块必须按 store 句柄寻址，双 store 互不可见
        store_a = open_train_store(tmp_path / "a")
        store_b = open_train_store(tmp_path / "b")
        assert (tmp_path / "a" / "mlflow.db").is_file()
        assert (tmp_path / "b" / "mlflow.db").is_file()

        _create(store_a)
        with pytest.raises(TrainRecordNotFound):
            get_train_run(store_b, TRAIN_ID)
        # B 中创建同 ID 不受 A 影响（不同 store，各自唯一）
        _create(store_b)

    def test_module_constants_pinned(self) -> None:
        assert DEFAULT_TRAIN_EXPERIMENT == "mVllm2-training"
        assert REQUIRED_FOLDS == (0, 1, 2)
        for name in (
            "TRAIN_ID_TAG",
            "WORKFLOW_STATE_TAG",
            "DATA_VERSION_TAG",
            "PROMPT_VERSION_TAG",
            "GIT_COMMIT_TAG",
            "BASE_MODEL_TAG",
            "RECORD_VALIDITY_TAG",
            "SUMMARY_COMPLETE_TAG",
            "FOLD_TAG",
        ):
            assert isinstance(getattr(mlflow_train, name), str)


# —————————————————— T2 父 Run 创建 ——————————————————


class TestCreateTrainRun:
    def test_create_records_explicit_id_common_inputs_and_tags(
        self, store: TrainRecordStore
    ) -> None:
        record = _create(store)

        # 返回快照：显式 ID + 共同输入 + 初始 running/RUNNING/valid（D038）
        assert isinstance(record, TrainRunRecord)
        assert record.train_id == TRAIN_ID
        assert record.run_name == TRAIN_ID
        assert record.experiment_id == store.experiment_id
        assert record.workflow_state == "running"
        assert record.run_status == "RUNNING"
        assert record.record_validity == "valid"
        assert record.data_version == "data-v4.1-r1"
        assert record.prompt_version == "prompt-v4.1-r1"
        assert record.git_commit == GIT_COMMIT
        assert record.base_model == BASE_MODEL
        assert dict(record.config) == CONFIG_AS_STR
        assert record.folds == {}
        assert dict(record.metrics) == {}
        _assert_combo_legal(record)

        # raw MLflow 读回：tags / params / 原生状态 / run_name（§2.7 共同输入）
        raw = _raw_run(store, record.run_id)
        assert raw.info.status == "RUNNING"
        assert raw.info.experiment_id == store.experiment_id
        assert raw.data.tags["train_id"] == TRAIN_ID
        assert raw.data.tags["workflow_state"] == "running"
        assert raw.data.tags["data_version"] == "data-v4.1-r1"
        assert raw.data.tags["prompt_version"] == "prompt-v4.1-r1"
        assert raw.data.tags["git_commit"] == GIT_COMMIT
        assert raw.data.tags["base_model"] == BASE_MODEL
        assert raw.data.tags["record_validity"] == "valid"
        assert raw.data.tags["mlflow.runName"] == TRAIN_ID
        assert dict(raw.data.params) == CONFIG_AS_STR

    def test_multiple_train_ids_coexist_in_one_store(
        self, store: TrainRecordStore
    ) -> None:
        _create(store, TRAIN_ID)
        _create(store, OTHER_TRAIN_ID)

        assert get_train_run(store, TRAIN_ID).train_id == TRAIN_ID
        assert get_train_run(store, OTHER_TRAIN_ID).train_id == OTHER_TRAIN_ID
        assert len(_parents(store, TRAIN_ID)) == 1
        assert len(_parents(store, OTHER_TRAIN_ID)) == 1

    @pytest.mark.parametrize("bad_train_id", BAD_TRAIN_IDS)
    def test_missing_or_illegal_train_id_rejected(
        self, store: TrainRecordStore, bad_train_id: object
    ) -> None:
        # 显式版本纪律（§9/§11.6）：缺省/None 与非法一律 InvalidIdentifier，
        # 不自动分配、不静默纠正；无 Run 产生。
        with pytest.raises(InvalidIdentifier):
            _create(store, bad_train_id)
        assert _all_runs(store) == []

    @pytest.mark.parametrize(
        "field,bad_value",
        [
            ("data_version", None),
            ("data_version", "latest"),
            ("data_version", "data-v4.1-r0"),
            ("data_version", "prompt-v4.1-r1"),
            ("prompt_version", None),
            ("prompt_version", "prompt-v4.1"),
            ("prompt_version", "data-v4.1-r1"),
            ("git_commit", None),
            ("git_commit", ""),
            ("base_model", None),
            ("base_model", ""),
        ],
    )
    def test_illegal_common_inputs_rejected(
        self, store: TrainRecordStore, field: str, bad_value: object
    ) -> None:
        with pytest.raises((InvalidIdentifier, IllegalTrainRecord)):
            _create(store, **{field: bad_value})
        assert _all_runs(store) == []

    @pytest.mark.parametrize(
        "bad_config",
        [
            None,
            "epochs=3",
            {"": "v"},
            {"epochs": None},
            {"layers": [1, 2]},
            {"opts": {"seed": 1}},
        ],
    )
    def test_illegal_config_rejected(
        self, store: TrainRecordStore, bad_config: object
    ) -> None:
        # 完整训练配置必填（缺省 None 拒绝），键值约束 fail-closed。
        with pytest.raises(IllegalTrainRecord):
            _create(store, config=bad_config)
        assert _all_runs(store) == []

    def test_duplicate_train_id_conflict_and_original_untouched(
        self, store: TrainRecordStore
    ) -> None:
        first = _create(store)

        with pytest.raises(TrainRunConflict):
            _create(store, TRAIN_ID)

        # §8 只增不改：原父 Run 唯一且内容不动
        assert len(_parents(store, TRAIN_ID)) == 1
        raw = _raw_run(store, first.run_id)
        assert raw.info.status == "RUNNING"
        assert raw.data.tags["workflow_state"] == "running"
        assert get_train_run(store, TRAIN_ID).run_id == first.run_id

    def test_domain_errors_share_base_class(self) -> None:
        # 域异常统一挂 MLflowTrainError(ValueError)，便于上游兜底
        for exc in (
            TrainRecordNotFound,
            TrainRunConflict,
            IllegalTrainRecord,
            IncompleteTrainRecord,
            InvalidTrainRecord,
        ):
            assert issubclass(exc, MLflowTrainError)
            assert issubclass(exc, ValueError)


# —————————————————— T3 fold 子 Run ——————————————————


class TestFoldRuns:
    def test_three_folds_are_nested_children_with_unique_identity(
        self, store: TrainRecordStore, record: TrainRunRecord
    ) -> None:
        fold_records = [
            create_fold_run(store, TRAIN_ID, fold, params={"split_seed": 100 + fold})
            for fold in REQUIRED_FOLDS
        ]

        assert [f.fold for f in fold_records] == [0, 1, 2]
        # 缺省无 fold 时 folds 为空；创建后观察集合完整
        assert set(record.folds) == set()
        assert set(get_train_run(store, TRAIN_ID).folds) == {0, 1, 2}

        for fold_record in fold_records:
            assert isinstance(fold_record, FoldRunRecord)
            assert fold_record.train_id == TRAIN_ID
            assert fold_record.parent_run_id == record.run_id
            assert fold_record.run_name == f"fold{fold_record.fold}"
            assert fold_record.status == "RUNNING"
            assert dict(fold_record.metrics) == {}
            assert dict(fold_record.params) == {
                "split_seed": str(100 + fold_record.fold)
            }

            # raw 读回：嵌套关联（mlflow.parentRunId）、fold 标识、原生 RUNNING、
            # 不携带 workflow_state/record_validity（权威在父 Run）
            raw = _raw_run(store, fold_record.run_id)
            assert raw.info.status == "RUNNING"
            assert raw.data.tags["mlflow.parentRunId"] == record.run_id
            assert raw.data.tags["fold"] == f"fold{fold_record.fold}"
            assert raw.data.tags["mlflow.runName"] == f"fold{fold_record.fold}"
            assert "workflow_state" not in raw.data.tags
            assert "record_validity" not in raw.data.tags
            assert dict(raw.data.params) == {"split_seed": str(100 + fold_record.fold)}

        # §2.7 查子 Run 方式按 parentRunId filter 应恰好命中三折
        children = _children(store, record.run_id)
        assert {child.data.tags["fold"] for child in children} == {
            "fold0",
            "fold1",
            "fold2",
        }
        assert len(children) == 3

    def test_fold_metrics_recorded_on_child_run(self, store: TrainRecordStore) -> None:
        _create(store)
        create_fold_run(store, TRAIN_ID, 0)
        log_fold_metrics(store, TRAIN_ID, 0, FOLD_METRICS[0])

        fold_record = list_fold_runs(store, TRAIN_ID)[0]
        assert dict(fold_record.metrics) == FOLD_METRICS[0]
        assert _raw_run(store, fold_record.run_id).data.metrics == FOLD_METRICS[0]

        # 多批指标取最新值（MLflow 语义），且不落在父 Run 上
        log_fold_metrics(store, TRAIN_ID, 0, {"fold_f1": 0.83})
        fold_record = list_fold_runs(store, TRAIN_ID)[0]
        assert fold_record.metrics["fold_f1"] == 0.83
        assert fold_record.metrics["fold_loss"] == FOLD_METRICS[0]["fold_loss"]

    @pytest.mark.parametrize("bad_fold", BAD_FOLDS)
    def test_illegal_fold_number_rejected(
        self, store: TrainRecordStore, bad_fold: object
    ) -> None:
        _create(store)
        with pytest.raises(IllegalTrainRecord):
            create_fold_run(store, TRAIN_ID, bad_fold)
        assert get_train_run(store, TRAIN_ID).folds == {}

    def test_duplicate_fold_rejected_and_original_untouched(
        self, store: TrainRecordStore
    ) -> None:
        _create(store)
        first = create_fold_run(store, TRAIN_ID, 0)

        with pytest.raises(TrainRunConflict):
            create_fold_run(store, TRAIN_ID, 0)

        # 标识无重复：fold0 子 Run 仍唯一、原状态不动
        fold0_children = [
            child
            for child in _children(store, first.parent_run_id)
            if child.data.tags.get("fold") == "fold0"
        ]
        assert len(fold0_children) == 1
        assert fold0_children[0].info.run_id == first.run_id
        assert _raw_run(store, first.run_id).info.status == "RUNNING"

    def test_missing_folds_observed_in_snapshot(self, store: TrainRecordStore) -> None:
        # 缺 fold 检测：只建 fold0/fold2，快照如实反映缺口
        _create(store)
        create_fold_run(store, TRAIN_ID, 0)
        create_fold_run(store, TRAIN_ID, 2)

        folds = get_train_run(store, TRAIN_ID).folds
        assert set(folds) == {0, 2}
        ordered = list_fold_runs(store, TRAIN_ID)
        assert [f.fold for f in ordered] == [0, 2]

        with pytest.raises(TrainRecordNotFound):
            # fold1 子 Run 不存在（不是 fold 集合的一部分）
            log_fold_metrics(store, TRAIN_ID, 1, FOLD_METRICS[1])

    def test_fold_creation_requires_running_parent(
        self, store: TrainRecordStore
    ) -> None:
        record = _create(store)
        transition_train_state(store, TRAIN_ID, "partial", run_status="KILLED")
        with pytest.raises(IllegalTrainRecord):
            create_fold_run(store, TRAIN_ID, 0)
        assert get_train_run(store, TRAIN_ID).folds == {}

        # completed 父 Run 也不得原地重跑（§5.3）
        transition_train_state(store, TRAIN_ID, "running")
        _complete_training(store)
        with pytest.raises(IllegalTrainRecord):
            create_fold_run(store, TRAIN_ID, 0)
        assert set(get_train_run(store, TRAIN_ID).folds) == {0, 1, 2}
        assert record.run_id == get_train_run(store, TRAIN_ID).run_id

    def test_end_fold_run_explicit_status(self, store: TrainRecordStore) -> None:
        _create(store)
        create_fold_run(store, TRAIN_ID, 0)
        ended = end_fold_run(store, TRAIN_ID, 0, "FINISHED", metrics={"final_f1": 0.9})

        assert ended.status == "FINISHED"
        assert ended.metrics == {"final_f1": 0.9}
        assert _raw_run(store, ended.run_id).info.status == "FINISHED"
        assert _raw_run(store, ended.run_id).data.metrics["final_f1"] == 0.9

    def test_end_fold_run_rejects_illegal_status_and_terminal_rerun(
        self, store: TrainRecordStore
    ) -> None:
        _create(store)
        create_fold_run(store, TRAIN_ID, 0)

        for bad_status in ("RUNNING", "SCHEDULED", "bogus", ""):
            with pytest.raises(IllegalTrainRecord):
                end_fold_run(store, TRAIN_ID, 0, bad_status)

        end_fold_run(store, TRAIN_ID, 0, "FINISHED")
        # 已终态子 Run 不得重复终转（含换终态）
        with pytest.raises(IllegalTrainRecord):
            end_fold_run(store, TRAIN_ID, 0, "FINISHED")
        with pytest.raises(IllegalTrainRecord):
            end_fold_run(store, TRAIN_ID, 0, "FAILED")
        assert (
            _raw_run(store, list_fold_runs(store, TRAIN_ID)[0].run_id).info.status
            == "FINISHED"
        )

    def test_end_fold_run_failed_and_killed(self, store: TrainRecordStore) -> None:
        _create(store)
        create_fold_run(store, TRAIN_ID, 0)
        create_fold_run(store, TRAIN_ID, 1)

        failed = end_fold_run(store, TRAIN_ID, 0, "FAILED")
        killed = end_fold_run(store, TRAIN_ID, 1, "KILLED")
        assert failed.status == "FAILED"
        assert killed.status == "KILLED"
        assert _raw_run(store, failed.run_id).info.status == "FAILED"
        assert _raw_run(store, killed.run_id).info.status == "KILLED"

    def test_resume_fold_run_controlled_recovery(self, store: TrainRecordStore) -> None:
        # 受控恢复：FAILED/KILLED 子 Run 经原 Run ID 恢复 RUNNING（§11.3）
        _create(store)
        crashed = create_fold_run(store, TRAIN_ID, 0)
        end_fold_run(store, TRAIN_ID, 0, "FAILED")
        killed = create_fold_run(store, TRAIN_ID, 1)
        end_fold_run(store, TRAIN_ID, 1, "KILLED")
        fresh = create_fold_run(store, TRAIN_ID, 2)

        resumed = resume_fold_run(store, TRAIN_ID, 0)
        assert resumed.run_id == crashed.run_id
        assert resumed.status == "RUNNING"
        assert _raw_run(store, crashed.run_id).info.status == "RUNNING"
        assert resumed.fold == 0

        resumed_killed = resume_fold_run(store, TRAIN_ID, 1)
        assert resumed_killed.run_id == killed.run_id
        assert resumed_killed.status == "RUNNING"

        # FINISHED 不得恢复；RUNNING 无需恢复
        end_fold_run(store, TRAIN_ID, 0, "FINISHED")
        with pytest.raises(IllegalTrainRecord):
            resume_fold_run(store, TRAIN_ID, 0)
        with pytest.raises(IllegalTrainRecord):
            resume_fold_run(store, TRAIN_ID, 2)
        assert _raw_run(store, fresh.run_id).info.status == "RUNNING"

    @pytest.mark.parametrize(
        "operation",
        [
            lambda store: get_train_run(store, UNKNOWN_ID),
            lambda store: list_fold_runs(store, UNKNOWN_ID),
            lambda store: create_fold_run(store, UNKNOWN_ID, 0),
            lambda store: log_fold_metrics(store, UNKNOWN_ID, 0, FOLD_METRICS[0]),
            lambda store: end_fold_run(store, UNKNOWN_ID, 0, "FINISHED"),
            lambda store: resume_fold_run(store, UNKNOWN_ID, 0),
            lambda store: transition_train_state(
                store, UNKNOWN_ID, "failed", run_status="FAILED"
            ),
            lambda store: log_train_summary(store, UNKNOWN_ID, SUMMARY_METRICS),
            lambda store: mark_train_invalid(store, UNKNOWN_ID),
            lambda store: validate_train_for_promotion(store, UNKNOWN_ID),
        ],
    )
    def test_unknown_train_operations_raise_not_found(
        self, store: TrainRecordStore, operation
    ) -> None:
        _create(store)  # store 可用但目标 train 不存在
        with pytest.raises(TrainRecordNotFound):
            operation(store)


# —————————————————— T4 状态组合校验 ——————————————————


class TestStateCombination:
    def test_combo_stays_in_fixed_table_along_lifecycle(
        self, store: TrainRecordStore
    ) -> None:
        # 全图行走：running→partial→running→failed→running→completed→archived，
        # 每步组合都落在 §5.3 固定表（委托 versioning.state 的表做判定）
        record = _create(store)
        _assert_combo_legal(record)

        partial = transition_train_state(
            store, TRAIN_ID, "partial", run_status="KILLED"
        )
        assert (partial.workflow_state, partial.run_status) == ("partial", "KILLED")
        _assert_combo_legal(partial)

        recovered = transition_train_state(store, TRAIN_ID, "running")
        assert (recovered.workflow_state, recovered.run_status) == (
            "running",
            "RUNNING",
        )
        _assert_combo_legal(recovered)

        failed = transition_train_state(store, TRAIN_ID, "failed", run_status="FAILED")
        assert (failed.workflow_state, failed.run_status) == ("failed", "FAILED")
        _assert_combo_legal(failed)

        transition_train_state(store, TRAIN_ID, "running")
        completed = _complete_training(store)
        assert (completed.workflow_state, completed.run_status) == (
            "completed",
            "FINISHED",
        )
        _assert_combo_legal(completed)

        archived = transition_train_state(store, TRAIN_ID, "archived")
        assert (archived.workflow_state, archived.run_status) == (
            "archived",
            "FINISHED",
        )
        _assert_combo_legal(archived)

    @pytest.mark.parametrize(
        "target,run_status",
        [
            ("partial", None),
            ("partial", "RUNNING"),
            ("partial", "FINISHED"),
            ("failed", None),
            ("failed", "FINISHED"),
            ("completed", "RUNNING"),
            ("archived", "FAILED"),
            ("running", "FINISHED"),
        ],
    )
    def test_illegal_target_status_combination_rejected(
        self, store: TrainRecordStore, target: str, run_status: str | None
    ) -> None:
        # 目标 workflow_state 与显式 run_status（或缺省的歧义）组合违反
        # §5.3 固定表 -> IllegalStateCombination（委托 versioning.state）
        record = _create(store)
        if target == "archived":
            _finish_all_folds(store)
            log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)
            transition_train_state(store, TRAIN_ID, "completed")
        elif target == "running":
            transition_train_state(store, TRAIN_ID, "partial", run_status="KILLED")
        elif target in ("completed",):
            pass  # 从 running 出发，门/组合校验在终态写回前拒绝

        with pytest.raises(IllegalStateCombination):
            transition_train_state(store, TRAIN_ID, target, run_status=run_status)

        # fail-closed：原状态组合不变
        after = get_train_run(store, TRAIN_ID)
        _assert_combo_legal(after)
        assert after.run_id == record.run_id

    def test_tampered_state_tag_rejected_on_read(self, store: TrainRecordStore) -> None:
        # D038：实现必须拒绝人工或异常操作产生的非法组合
        record = _create(store)  # running/RUNNING
        _client(store).set_tag(record.run_id, "workflow_state", "completed")

        with pytest.raises(IllegalStateCombination):
            get_train_run(store, TRAIN_ID)
        with pytest.raises(IllegalStateCombination):
            transition_train_state(store, TRAIN_ID, "partial", run_status="FAILED")
        with pytest.raises(IllegalStateCombination):
            validate_train_for_promotion(store, TRAIN_ID)

    def test_garbage_state_tag_rejected_on_read(self, store: TrainRecordStore) -> None:
        record = _create(store)
        _client(store).set_tag(record.run_id, "workflow_state", "paused")
        with pytest.raises(IllegalStateCombination):
            get_train_run(store, TRAIN_ID)

    def test_tampered_validity_tag_rejected_on_read(
        self, store: TrainRecordStore
    ) -> None:
        # §2.6：record_validity 合法值仅 valid|invalid
        record = _create(store)
        _client(store).set_tag(record.run_id, "record_validity", "maybe")
        with pytest.raises(IllegalTrainRecord):
            get_train_run(store, TRAIN_ID)


# —————————————————— T5 状态转换 ——————————————————


class TestWorkflowTransitions:
    def test_controlled_recovery_returns_same_run_to_running(
        self, store: TrainRecordStore
    ) -> None:
        # partial/failed 只能受控恢复回 running（§5.3/§11.3）：原生状态与
        # workflow_state 一起恢复，原 Run ID 不变
        record = _create(store)

        partial = transition_train_state(
            store, TRAIN_ID, "partial", run_status="KILLED"
        )
        assert (partial.workflow_state, partial.run_status) == ("partial", "KILLED")
        assert _raw_run(store, record.run_id).info.status == "KILLED"

        recovered = transition_train_state(store, TRAIN_ID, "running")
        assert recovered.run_id == record.run_id
        assert (recovered.workflow_state, recovered.run_status) == (
            "running",
            "RUNNING",
        )
        assert _raw_run(store, record.run_id).info.status == "RUNNING"

    def test_recovery_from_failed_same_run(self, store: TrainRecordStore) -> None:
        record = _create(store)
        failed = transition_train_state(store, TRAIN_ID, "failed", run_status="FAILED")
        assert (failed.workflow_state, failed.run_status) == ("failed", "FAILED")

        recovered = transition_train_state(store, TRAIN_ID, "running")
        assert recovered.run_id == record.run_id
        assert (recovered.workflow_state, recovered.run_status) == (
            "running",
            "RUNNING",
        )

    def test_partial_then_failed_needs_running_in_between(
        self, store: TrainRecordStore
    ) -> None:
        record = _create(store)
        transition_train_state(store, TRAIN_ID, "partial", run_status="KILLED")
        # partial→failed 非法（必须经 running）
        with pytest.raises(IllegalTransition):
            transition_train_state(store, TRAIN_ID, "failed", run_status="FAILED")
        assert get_train_run(store, TRAIN_ID).workflow_state == "partial"

        transition_train_state(store, TRAIN_ID, "running")
        failed = transition_train_state(store, TRAIN_ID, "failed", run_status="FAILED")
        assert failed.workflow_state == "failed"
        assert failed.run_id == record.run_id

    def test_completed_to_archived(self, store: TrainRecordStore) -> None:
        record = _create(store)
        _complete_training(store)
        archived = transition_train_state(store, TRAIN_ID, "archived")
        assert archived.workflow_state == "archived"
        assert archived.run_status == "FINISHED"
        assert archived.run_id == record.run_id

    @pytest.mark.parametrize(
        "source,target",
        [
            ("partial", "completed"),
            ("failed", "completed"),
            ("completed", "running"),
            ("completed", "partial"),
            ("completed", "completed"),  # 自环
            ("archived", "completed"),
            ("archived", "running"),
            ("running", "prepared"),  # prepared=无 Run，不存在回退入口
            ("running", "running"),  # 自环
            ("partial", "partial"),  # 自环
            ("failed", "partial"),
        ],
    )
    def test_illegal_transitions_rejected(
        self, store: TrainRecordStore, source: str, target: str
    ) -> None:
        record = _prepare_state(store, source)
        assert record.workflow_state == source

        with pytest.raises(IllegalTransition):
            transition_train_state(store, TRAIN_ID, target)

        # 拒绝后状态不变
        after = get_train_run(store, TRAIN_ID)
        assert after.workflow_state == source
        assert after.run_id == record.run_id

    def test_transition_accepts_workflow_state_enum(
        self, store: TrainRecordStore
    ) -> None:
        # 委托 versioning.state：枚举与值字符串等价
        _create(store)
        partial = transition_train_state(
            store, TRAIN_ID, WorkflowState.PARTIAL, run_status="FAILED"
        )
        assert partial.workflow_state == "partial"
        recovered = transition_train_state(store, TRAIN_ID, WorkflowState.RUNNING)
        assert recovered.workflow_state == "running"


# —————————————————— T6 completed 晋级门 ——————————————————


class TestCompletionGate:
    def test_full_folds_and_summary_allow_completed(
        self, store: TrainRecordStore
    ) -> None:
        record = _create(store)
        completed = _complete_training(store)

        assert completed.workflow_state == "completed"
        assert completed.run_status == "FINISHED"
        assert completed.run_id == record.run_id
        # 全部必需 fold 原生 FINISHED
        for fold_record in completed.folds.values():
            assert fold_record.status == "FINISHED"
            assert _raw_run(store, fold_record.run_id).info.status == "FINISHED"

        validated = validate_train_for_promotion(store, TRAIN_ID)
        assert validated.run_id == record.run_id

    def test_missing_fold_blocks_completed_then_passes_after_fill(
        self, store: TrainRecordStore
    ) -> None:
        _create(store)
        for fold in (0, 1):
            create_fold_run(store, TRAIN_ID, fold)
            log_fold_metrics(store, TRAIN_ID, fold, FOLD_METRICS[fold])
            end_fold_run(store, TRAIN_ID, fold, "FINISHED")
        log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)

        # fold2 缺失：拒绝进入 completed，也拒绝晋级门
        with pytest.raises(IncompleteTrainRecord):
            transition_train_state(store, TRAIN_ID, "completed")
        with pytest.raises(IncompleteTrainRecord):
            validate_train_for_promotion(store, TRAIN_ID)
        assert get_train_run(store, TRAIN_ID).workflow_state == "running"

        # 补齐后通过
        create_fold_run(store, TRAIN_ID, 2)
        log_fold_metrics(store, TRAIN_ID, 2, FOLD_METRICS[2])
        end_fold_run(store, TRAIN_ID, 2, "FINISHED")
        completed = transition_train_state(store, TRAIN_ID, "completed")
        assert completed.workflow_state == "completed"

    @pytest.mark.parametrize("bad_status", ["FAILED", "KILLED"])
    def test_failed_fold_blocks_completed(
        self, store: TrainRecordStore, bad_status: str
    ) -> None:
        _create(store)
        for fold in REQUIRED_FOLDS:
            create_fold_run(store, TRAIN_ID, fold)
            end_fold_run(store, TRAIN_ID, fold, bad_status if fold == 1 else "FINISHED")
        log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)

        with pytest.raises(IncompleteTrainRecord):
            transition_train_state(store, TRAIN_ID, "completed")
        with pytest.raises(IncompleteTrainRecord):
            validate_train_for_promotion(store, TRAIN_ID)
        assert get_train_run(store, TRAIN_ID).workflow_state == "running"

    def test_running_fold_blocks_completed(self, store: TrainRecordStore) -> None:
        # fold 未终转（RUNNING）同样不完整
        _create(store)
        for fold in REQUIRED_FOLDS:
            create_fold_run(store, TRAIN_ID, fold)
        log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)

        with pytest.raises(IncompleteTrainRecord):
            transition_train_state(store, TRAIN_ID, "completed")

    def test_missing_summary_blocks_completed(self, store: TrainRecordStore) -> None:
        # 三折全 FINISHED 但无三折汇总（§2.7）：不得 completed，也不得晋级
        _create(store)
        _finish_all_folds(store)

        with pytest.raises(IncompleteTrainRecord):
            transition_train_state(store, TRAIN_ID, "completed")
        with pytest.raises(IncompleteTrainRecord):
            validate_train_for_promotion(store, TRAIN_ID)

        log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)
        completed = transition_train_state(store, TRAIN_ID, "completed")
        assert completed.workflow_state == "completed"

    def test_non_completed_state_blocked_at_gate(self, store: TrainRecordStore) -> None:
        # §10：workflow_state 非 completed|archived 一律拒绝（即使三折齐全）
        _create(store)
        _finish_all_folds(store)
        log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)

        with pytest.raises(IncompleteTrainRecord):
            validate_train_for_promotion(store, TRAIN_ID)

        transition_train_state(store, TRAIN_ID, "partial", run_status="FAILED")
        with pytest.raises(IncompleteTrainRecord):
            validate_train_for_promotion(store, TRAIN_ID)

    def test_archived_passes_promotion_gate(self, store: TrainRecordStore) -> None:
        # §10 晋级条件接受 completed|archived
        _create(store)
        _complete_training(store)
        transition_train_state(store, TRAIN_ID, "archived")

        validated = validate_train_for_promotion(store, TRAIN_ID)
        assert validated.workflow_state == "archived"
        assert validated.run_status == "FINISHED"

    def test_tampered_terminal_combo_blocked_at_gate(
        self, store: TrainRecordStore
    ) -> None:
        # completed tag + RUNNING 原生（篡改）→ 组合非法，晋级门 fail-closed
        record = _create(store)
        _complete_training(store)
        _client(store).update_run(record.run_id, status="RUNNING")

        with pytest.raises(IllegalStateCombination):
            validate_train_for_promotion(store, TRAIN_ID)


# —————————————————— T7 record_validity ——————————————————


class TestRecordValidity:
    def test_mark_invalid_sets_tag_and_is_idempotent(
        self, store: TrainRecordStore
    ) -> None:
        record = _create(store)
        assert record.record_validity == "valid"

        marked = mark_train_invalid(store, TRAIN_ID)
        assert marked.record_validity == "invalid"
        assert marked.run_id == record.run_id
        assert _raw_run(store, record.run_id).data.tags["record_validity"] == "invalid"

        # 同值幂等（transition_record_validity 语义），原生状态不被触碰
        again = mark_train_invalid(store, TRAIN_ID)
        assert again.record_validity == "invalid"
        assert again.run_status == "RUNNING"
        assert _raw_run(store, record.run_id).info.status == "RUNNING"

    def test_invalid_record_rejected_by_downstream_gate(
        self, store: TrainRecordStore
    ) -> None:
        # §2.6/§10：record_validity=invalid 的父 Run 被下游校验拒绝
        _create(store)
        _complete_training(store)
        mark_train_invalid(store, TRAIN_ID)

        with pytest.raises(InvalidTrainRecord):
            validate_train_for_promotion(store, TRAIN_ID)

    def test_invalid_check_precedes_gate_conditions(
        self, store: TrainRecordStore
    ) -> None:
        # validity 优先于 fold 完整性：running 且零 fold + invalid →
        # InvalidTrainRecord（而非 IncompleteTrainRecord）
        _create(store)
        mark_train_invalid(store, TRAIN_ID)

        with pytest.raises(InvalidTrainRecord):
            validate_train_for_promotion(store, TRAIN_ID)

    def test_validity_enum_alignment(self, store: TrainRecordStore) -> None:
        # 与 versioning.state.RecordValidity 值域对齐（valid|invalid）
        _create(store)
        record = get_train_run(store, TRAIN_ID)
        assert record.record_validity == RecordValidity.VALID.value
        marked = mark_train_invalid(store, TRAIN_ID)
        assert marked.record_validity == RecordValidity.INVALID.value

    @pytest.mark.parametrize(
        "tampered_state",
        ["completed", "partial", "failed", "archived", "prepared"],
    )
    def test_invalid_precedes_illegal_state_combination(
        self, store: TrainRecordStore, tampered_state: str
    ) -> None:
        # P2-1 回归（B6 复审）：§10 顺序钉死——record_validity=invalid 的
        # 判定必须先于 workflow_state/run_status 组合校验。修复前先构造快照
        # （组合校验随 _validate_parent_tags 先行），被篡改的 invalid 记录会
        # 以 IllegalStateCombination 冒名拒绝，invalid 事实被“洗白”为组合
        # 错误；修复后必须抛 InvalidTrainRecord。对照组（valid + 同样篡改 ->
        # IllegalStateCombination）由 test_tampered_state_tag_rejected_on_read
        # 覆盖，二者合成 §10 的完整优先级矩阵。
        record = _create(store)  # running/RUNNING/valid
        mark_train_invalid(store, TRAIN_ID)
        # 原生状态仍 RUNNING：篡改后的 workflow_state 与之构成 §5.3 非法组合
        assert _raw_run(store, record.run_id).info.status == "RUNNING"
        _client(store).set_tag(record.run_id, "workflow_state", tampered_state)

        with pytest.raises(InvalidTrainRecord) as excinfo:
            validate_train_for_promotion(store, TRAIN_ID)

        # 必须是 InvalidTrainRecord，而非修复前的 IllegalStateCombination
        assert not isinstance(excinfo.value, IllegalStateCombination)
        # fail-closed：校验只读，不修复也不掩盖被篡改的事实
        raw = _raw_run(store, record.run_id)
        assert raw.data.tags["record_validity"] == "invalid"
        assert raw.data.tags["workflow_state"] == tampered_state
        assert raw.info.status == "RUNNING"


# —————————————————— T8 三折汇总写父 Run ——————————————————


class TestTrainSummary:
    def test_summary_metrics_written_to_parent_run(
        self, store: TrainRecordStore
    ) -> None:
        record = _create(store)
        summarized = log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)

        assert dict(summarized.metrics) == SUMMARY_METRICS
        assert summarized.run_id == record.run_id

        raw = _raw_run(store, record.run_id)
        assert dict(raw.data.metrics) == SUMMARY_METRICS
        assert raw.data.tags["summary_complete"] == "true"

    def test_fold_metrics_stay_on_children_not_parent(
        self, store: TrainRecordStore
    ) -> None:
        # 汇总在父 Run；fold 过程指标只落在各自子 Run（§2.7）
        record = _create(store)
        _finish_all_folds(store)
        log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)

        parent_metrics = dict(_raw_run(store, record.run_id).data.metrics)
        assert set(parent_metrics) == set(SUMMARY_METRICS)

        for fold, fold_record in get_train_run(store, TRAIN_ID).folds.items():
            child_metrics = dict(_raw_run(store, fold_record.run_id).data.metrics)
            assert child_metrics == FOLD_METRICS[fold]
            assert set(child_metrics).isdisjoint(set(SUMMARY_METRICS))

    @pytest.mark.parametrize(
        "bad_metrics",
        [
            {},
            {"": 0.5},
            {"f1": None},
            {"f1": True},
            {"f1": "0.9"},
            {"f1": [0.9]},
        ],
    )
    def test_illegal_summary_rejected(
        self, store: TrainRecordStore, bad_metrics: dict
    ) -> None:
        _create(store)
        with pytest.raises(IllegalTrainRecord):
            log_train_summary(store, TRAIN_ID, bad_metrics)
        assert (
            dict(_raw_run(store, get_train_run(store, TRAIN_ID).run_id).data.metrics)
            == {}
        )

    @pytest.mark.parametrize(
        "bad_metrics",
        [
            {},
            {"f1": None},
            {"f1": True},
        ],
    )
    def test_illegal_fold_metrics_rejected(
        self, store: TrainRecordStore, bad_metrics: dict
    ) -> None:
        _create(store)
        create_fold_run(store, TRAIN_ID, 0)
        with pytest.raises(IllegalTrainRecord):
            log_fold_metrics(store, TRAIN_ID, 0, bad_metrics)


# —————————————————— T9 全链路 ——————————————————


class TestFullTrainingLifecycle:
    def test_create_to_archived_end_to_end(self, store: TrainRecordStore) -> None:
        record = _create(store)
        seen_run_ids = {record.run_id}
        fold_run_ids: dict[int, str] = {}

        for fold in REQUIRED_FOLDS:
            fold_record = create_fold_run(
                store, TRAIN_ID, fold, params={"split_seed": 100 + fold}
            )
            fold_run_ids[fold] = fold_record.run_id
            log_fold_metrics(store, TRAIN_ID, fold, FOLD_METRICS[fold])
            end_fold_run(store, TRAIN_ID, fold, "FINISHED")

        log_train_summary(store, TRAIN_ID, SUMMARY_METRICS)
        completed = transition_train_state(store, TRAIN_ID, "completed")
        seen_run_ids.add(completed.run_id)

        # D038/§11.3：全程原 Run ID 不变（受控恢复语义的静态面）
        assert seen_run_ids == {record.run_id}

        # raw 全量断言：父 FINISHED、tags 完整、三折嵌套且各自 FINISHED
        raw_parent = _raw_run(store, record.run_id)
        assert raw_parent.info.status == "FINISHED"
        assert raw_parent.data.tags["train_id"] == TRAIN_ID
        assert raw_parent.data.tags["workflow_state"] == "completed"
        assert raw_parent.data.tags["data_version"] == "data-v4.1-r1"
        assert raw_parent.data.tags["prompt_version"] == "prompt-v4.1-r1"
        assert raw_parent.data.tags["git_commit"] == GIT_COMMIT
        assert raw_parent.data.tags["base_model"] == BASE_MODEL
        assert raw_parent.data.tags["record_validity"] == "valid"
        assert raw_parent.data.tags["summary_complete"] == "true"
        assert dict(raw_parent.data.params) == CONFIG_AS_STR
        assert dict(raw_parent.data.metrics) == SUMMARY_METRICS

        children = _children(store, record.run_id)
        assert len(children) == 3
        for child in children:
            fold = int(child.data.tags["fold"].removeprefix("fold"))
            assert child.info.run_id == fold_run_ids[fold]
            assert child.info.status == "FINISHED"
            assert dict(child.data.metrics) == FOLD_METRICS[fold]
            assert child.data.tags["mlflow.parentRunId"] == record.run_id

        # 晋级门通过；archived 后仍通过（§10 completed|archived）
        assert validate_train_for_promotion(store, TRAIN_ID).run_id == record.run_id
        archived = transition_train_state(store, TRAIN_ID, "archived")
        assert archived.workflow_state == "archived"
        assert (
            validate_train_for_promotion(store, TRAIN_ID).workflow_state == "archived"
        )
    def test_recovery_flow_completes_after_controlled_resume(
        self, store: TrainRecordStore
    ) -> None:
        # §5.3/§11.3 中断恢复全流程：失败 → partial → 受控恢复 running →
        # fold 受控恢复 → 全折 FINISHED → 汇总 → completed（不得跳步）
        record = _create(store)
        create_fold_run(store, TRAIN_ID, 0)
        log_fold_metrics(store, TRAIN_ID, 0, FOLD_METRICS[0])
        end_fold_run(store, TRAIN_ID, 0, "FINISHED")

        crashed = create_fold_run(store, TRAIN_ID, 1)
        log_fold_metrics(store, TRAIN_ID, 1, FOLD_METRICS[1])
        end_fold_run(store, TRAIN_ID, 1, "FAILED")

        partial = transition_train_state(
            store, TRAIN_ID, "partial", run_status="FAILED"
        )
        assert (partial.workflow_state, partial.run_status) == ("partial", "FAILED")

        # partial/failed → completed 直接拒绝
        with pytest.raises(IllegalTransition):
            transition_train_state(store, TRAIN_ID, "completed")

        # 受控恢复：父 Run 与崩溃 fold 各自经原 Run ID 恢复 RUNNING
        running = transition_train_state(store, TRAIN_ID, "running")
        assert running.run_id == record.run_id
        resumed = resume_fold_run(store, TRAIN_ID, 1)
        assert resumed.run_id == crashed.run_id
        log_fold_metrics(store, TRAIN_ID, 1, {"fold_f1": 0.82, "fold_loss": 0.43})
        end_fold_run(store, TRAIN_ID, 1, "FINISHED")

        fold2 = create_fold_run(store, TRAIN_ID, 2)
        log_fold_metrics(store, TRAIN_ID, 2, FOLD_METRICS[2])
        end_fold_run(store, TRAIN_ID, 2, "FINISHED")

        log_train_summary(store, TRAIN_ID, {"cv_f1_mean": 0.81, "cv_f1_std": 0.012})
        completed = transition_train_state(store, TRAIN_ID, "completed")
        assert (completed.workflow_state, completed.run_status) == (
            "completed",
            "FINISHED",
        )

        # 崩溃折的恢复执行产生了新一批指标值（最新值生效）
        fold_records = get_train_run(store, TRAIN_ID).folds
        assert fold_records[1].metrics == {"fold_f1": 0.82, "fold_loss": 0.43}
        assert (
            validate_train_for_promotion(store, TRAIN_ID).workflow_state == "completed"
        )
        assert fold_records[2].run_id == fold2.run_id


# —————————————————— T10 读路径 train_id 入口校验（P3 回归）——————————————————


class TestReadPathTrainIdValidation:
    """P3 回归（B6 复审）：读路径入口的 train_id 校验。

    修复前 ``_search_parent`` 不校验 train_id 即拼 MLflow filter_string：
    含单引号的注入串在 MLflow 查询解析器抛 ``MlflowException``（域校验
    泄漏为底层异常）；双引号/尾随换行/非字符串则被静默当作“不存在”
    （``TrainRecordNotFound``，与未知合法 ID 混淆）。修复后读路径入口先
    ``parse_train_id``：畸形 ID 一律 ``InvalidIdentifier``（§3.1/§9 显式
    版本纪律 + D038 fail-closed），绝不 ``MlflowException``，也绝不与
    ``TrainRecordNotFound`` 混淆。
    """

    @pytest.mark.parametrize(
        "operation",
        [
            lambda store: get_train_run(store, INJECTION_TRAIN_ID),
            lambda store: list_fold_runs(store, INJECTION_TRAIN_ID),
            lambda store: create_fold_run(store, INJECTION_TRAIN_ID, 0),
            lambda store: log_fold_metrics(
                store, INJECTION_TRAIN_ID, 0, FOLD_METRICS[0]
            ),
            lambda store: end_fold_run(store, INJECTION_TRAIN_ID, 0, "FINISHED"),
            lambda store: resume_fold_run(store, INJECTION_TRAIN_ID, 0),
            lambda store: transition_train_state(
                store, INJECTION_TRAIN_ID, "partial", run_status="FAILED"
            ),
            lambda store: log_train_summary(
                store, INJECTION_TRAIN_ID, SUMMARY_METRICS
            ),
            lambda store: mark_train_invalid(store, INJECTION_TRAIN_ID),
            lambda store: validate_train_for_promotion(store, INJECTION_TRAIN_ID),
        ],
    )
    def test_injection_id_rejected_by_every_read_entry(
        self, store: TrainRecordStore, operation
    ) -> None:
        # store 内已有合法记录：畸形 ID 不得与“不存在”混淆，也不得泄漏为
        # MLflow 查询异常（修复前的两种症状）
        _create(store)
        with pytest.raises(InvalidIdentifier) as excinfo:
            operation(store)

        assert not isinstance(excinfo.value, MlflowException)
        assert not isinstance(excinfo.value, TrainRecordNotFound)
        # fail-closed：拒绝发生在任何写入之前，既有事实原样（无新 Run/fold）
        assert get_train_run(store, TRAIN_ID).folds == {}
        assert len(_parents(store, TRAIN_ID)) == 1
        assert len(_all_runs(store)) == 1

    @pytest.mark.parametrize("malformed_id", MALFORMED_QUOTED_TRAIN_IDS)
    def test_malformed_shapes_rejected_by_get_train_run(
        self, store: TrainRecordStore, malformed_id: object
    ) -> None:
        _create(store)
        with pytest.raises(InvalidIdentifier) as excinfo:
            get_train_run(store, malformed_id)

        assert not isinstance(excinfo.value, MlflowException)
        assert not isinstance(excinfo.value, TrainRecordNotFound)
        # 既有合法记录不受畸形读影响
        assert get_train_run(store, TRAIN_ID).train_id == TRAIN_ID
