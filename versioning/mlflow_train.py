"""B6 — MLflow 训练记录：train-v 父 Run + 三折嵌套子 Run + workflow_state 状态映射。

对应设计 docs/plans/2026-09-01-readable-version-control-design.md：
§2.6（MLflow 是训练事实唯一权威；workflow_state/record_validity tags；SQLite
单文件 + 本地 artifact store；不得启动服务、不得连接正式 store）、
§2.7 + D022（一个 ``train-v<协议>-r<N>`` = 一个父 Run；fold0/1/2 为嵌套子 Run，
不分配独立版本；父 Run 记三折共用输入；三折汇总写父 Run；任一必需 fold 未
完成时父 Run 不得 completed）、§5.3 + D038（workflow_state ↔ MLflow 原生
RunStatus 固定组合表；状态流 prepared→running→completed→archived、
running↔partial↔failed；父 Run 进入 completed 的门 = 全部必需 fold FINISHED +
汇总完整）、§10（train 行下游规则：模型晋级只接受 valid + FINISHED +
completed|archived + 所有子 Run 完整）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from mlflow.entities import ViewType
from mlflow.tracking import MlflowClient

from versioning.ids import parse_data_id, parse_prompt_id, parse_train_id
from versioning.state import (
    ALLOWED_RUN_STATUSES,
    IllegalStateCombination,
    IllegalTransition,
    RecordValidity,
    WorkflowState,
    transition_record_validity,
    transition_workflow_state,
    validate_workflow_run_status,
)


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
FOLD_TAG: str = "fold"


class MLflowTrainError(ValueError):
    """训练记录域异常基类。"""


class TrainRecordNotFound(MLflowTrainError):
    """指定 train 记录或其 fold 子 Run 在本 store 中不存在。"""


class TrainRunConflict(MLflowTrainError):
    """同一 train-v... 已存在父 Run，或同父 Run 下同 fold 子 Run 已存在。"""


class IllegalTrainRecord(MLflowTrainError):
    """记录构造/操作输入非法或前置条件不满足。"""


class IncompleteTrainRecord(MLflowTrainError):
    """completed 晋级门拒绝：必需 fold 缺失/未 FINISHED、汇总不完整等。"""


class InvalidTrainRecord(MLflowTrainError):
    """record_validity=invalid 的训练记录被下游校验拒绝。"""


@dataclass(frozen=True)
class TrainRecordStore:
    """训练记录 store 句柄（SQLite + 本地 artifacts）。"""

    root: Path
    tracking_uri: str
    experiment_id: str
    artifact_location: str


@dataclass(frozen=True)
class FoldRunRecord:
    """fold 子 Run 只读快照。"""

    train_id: str
    fold: int
    run_id: str
    parent_run_id: str
    run_name: str
    status: str
    metrics: Mapping[str, float]
    params: Mapping[str, str]


@dataclass(frozen=True)
class TrainRunRecord:
    """train 父 Run 只读快照。"""

    train_id: str
    run_id: str
    experiment_id: str
    run_name: str
    workflow_state: str
    run_status: str
    record_validity: str
    data_version: str
    prompt_version: str
    git_commit: str
    base_model: str
    config: Mapping[str, str]
    metrics: Mapping[str, float]
    folds: Mapping[int, FoldRunRecord]


def _client(store: TrainRecordStore) -> MlflowClient:
    """按 store 句柄构造独立 MLflow Client，不依赖全局 tracking 状态。"""
    return MlflowClient(tracking_uri=store.tracking_uri)


def _validate_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise IllegalTrainRecord(f"{name} 必须是非空字符串: {value!r}")
    return value


def _is_config_value(value: Any) -> bool:
    """config / fold params 允许 str/int/float/bool（bool 为 int 子类，单独放行）。"""
    if isinstance(value, bool):
        return True
    return isinstance(value, (str, int, float))


def _is_metric_value(value: Any) -> bool:
    """metrics 只允许 int/float，显式拒绝 bool。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_config(config: Any) -> dict[str, str]:
    if not isinstance(config, Mapping):
        raise IllegalTrainRecord(f"config 必须是 Mapping: {config!r}")
    result: dict[str, str] = {}
    for key, value in config.items():
        if not isinstance(key, str) or not key:
            raise IllegalTrainRecord(f"config 键必须是非空字符串: {key!r}")
        if not _is_config_value(value):
            raise IllegalTrainRecord(f"config 值必须是 str/int/float/bool: {value!r}")
        result[key] = str(value)
    return result


def _validate_params(params: Any) -> dict[str, str]:
    if params is None:
        return {}
    if not isinstance(params, Mapping):
        raise IllegalTrainRecord(f"params 必须是 Mapping: {params!r}")
    result: dict[str, str] = {}
    for key, value in params.items():
        if not isinstance(key, str) or not key:
            raise IllegalTrainRecord(f"params 键必须是非空字符串: {key!r}")
        if not _is_config_value(value):
            raise IllegalTrainRecord(f"params 值必须是 str/int/float/bool: {value!r}")
        result[key] = str(value)
    return result


def _validate_metrics(metrics: Any) -> dict[str, float]:
    if not isinstance(metrics, Mapping) or not metrics:
        raise IllegalTrainRecord("metrics 必须是非空 Mapping")
    result: dict[str, float] = {}
    for key, value in metrics.items():
        if not isinstance(key, str) or not key:
            raise IllegalTrainRecord(f"metrics 键必须是非空字符串: {key!r}")
        if not _is_metric_value(value):
            raise IllegalTrainRecord(f"metrics 值必须是 int/float: {value!r}")
        result[key] = float(value)
    return result


def _validate_fold(fold: Any) -> int:
    if isinstance(fold, bool) or not isinstance(fold, int):
        raise IllegalTrainRecord(f"fold 必须是整数: {fold!r}")
    if fold not in REQUIRED_FOLDS:
        raise IllegalTrainRecord(f"fold 编号非法: {fold!r}")
    return fold


def _parent_run_id_from_child(run: Any) -> str:
    return run.data.tags.get("mlflow.parentRunId", "")


def _fold_from_child(run: Any) -> int:
    fold_tag = run.data.tags.get(FOLD_TAG, "")
    return int(fold_tag.removeprefix("fold"))


def open_train_store(
    root: Path, *, experiment_name: str = DEFAULT_TRAIN_EXPERIMENT
) -> TrainRecordStore:
    """创建（缺失时）本地 SQLite + artifact store，并按名复用/新建实验。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    artifact_path = root / "artifacts"
    artifact_path.mkdir(parents=True, exist_ok=True)
    tracking_uri = f"sqlite:///{root.resolve().as_posix()}/mlflow.db"

    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        experiment_id = client.create_experiment(
            name=experiment_name,
            artifact_location=str(artifact_path.resolve()),
        )
    else:
        experiment_id = experiment.experiment_id

    return TrainRecordStore(
        root=root,
        tracking_uri=tracking_uri,
        experiment_id=experiment_id,
        artifact_location=str(artifact_path.resolve()),
    )


def _search_parent(client: MlflowClient, experiment_id: str, train_id: str) -> Any:
    parse_train_id(train_id)
    runs = client.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.{TRAIN_ID_TAG} = '{train_id}'",
        run_view_type=ViewType.ALL,
        max_results=1,
    )
    if not runs:
        raise TrainRecordNotFound(f"未找到 train: {train_id}")
    return runs[0]


def _search_children(
    client: MlflowClient, experiment_id: str, parent_run_id: str
) -> list[Any]:
    return client.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.mlflow.parentRunId = '{parent_run_id}'",
        run_view_type=ViewType.ALL,
        max_results=100,
    )


def _validate_parent_tags(run: Any) -> None:
    """读取 fail-closed：校验 workflow_state/run_status 组合与 record_validity 值域。"""
    tags = run.data.tags
    validate_workflow_run_status(tags.get(WORKFLOW_STATE_TAG), run.info.status)
    validity = tags.get(RECORD_VALIDITY_TAG)
    if validity not in (RecordValidity.VALID.value, RecordValidity.INVALID.value):
        raise IllegalTrainRecord(f"父 Run record_validity 非法: {validity!r}")


def _build_fold_record(train_id: str, run: Any) -> FoldRunRecord:
    return FoldRunRecord(
        train_id=train_id,
        fold=_fold_from_child(run),
        run_id=run.info.run_id,
        parent_run_id=_parent_run_id_from_child(run),
        run_name=run.info.run_name or run.data.tags.get("mlflow.runName", ""),
        status=run.info.status,
        metrics=dict(run.data.metrics),
        params=dict(run.data.params),
    )


def _build_folds(
    client: MlflowClient, experiment_id: str, parent_run_id: str, train_id: str
) -> dict[int, FoldRunRecord]:
    children = _search_children(client, experiment_id, parent_run_id)
    records = [_build_fold_record(train_id, child) for child in children]
    records.sort(key=lambda r: r.fold)
    return {r.fold: r for r in records}


def _build_train_record(store: TrainRecordStore, run: Any) -> TrainRunRecord:
    _validate_parent_tags(run)
    client = _client(store)
    tags = run.data.tags
    train_id = tags[TRAIN_ID_TAG]
    return TrainRunRecord(
        train_id=train_id,
        run_id=run.info.run_id,
        experiment_id=run.info.experiment_id,
        run_name=run.info.run_name or tags.get("mlflow.runName", ""),
        workflow_state=tags[WORKFLOW_STATE_TAG],
        run_status=run.info.status,
        record_validity=tags[RECORD_VALIDITY_TAG],
        data_version=tags[DATA_VERSION_TAG],
        prompt_version=tags[PROMPT_VERSION_TAG],
        git_commit=tags[GIT_COMMIT_TAG],
        base_model=tags[BASE_MODEL_TAG],
        config=dict(run.data.params),
        metrics=dict(run.data.metrics),
        folds=_build_folds(client, store.experiment_id, run.info.run_id, train_id),
    )


def create_train_run(
    store: TrainRecordStore,
    train_id: str,
    *,
    data_version: str,
    prompt_version: str,
    git_commit: str,
    base_model: str,
    config: Mapping,
) -> TrainRunRecord:
    """创建 train-v 父 Run；创建即 running/RUNNING/valid。"""
    parse_train_id(train_id)
    parse_data_id(data_version)
    parse_prompt_id(prompt_version)
    _validate_non_empty_string(git_commit, "git_commit")
    _validate_non_empty_string(base_model, "base_model")
    config_str = _validate_config(config)

    client = _client(store)
    try:
        _search_parent(client, store.experiment_id, train_id)
    except TrainRecordNotFound:
        pass
    else:
        raise TrainRunConflict(f"train {train_id} 已存在")

    tags = {
        TRAIN_ID_TAG: train_id,
        WORKFLOW_STATE_TAG: WorkflowState.RUNNING.value,
        DATA_VERSION_TAG: data_version,
        PROMPT_VERSION_TAG: prompt_version,
        GIT_COMMIT_TAG: git_commit,
        BASE_MODEL_TAG: base_model,
        RECORD_VALIDITY_TAG: RecordValidity.VALID.value,
    }
    run = client.create_run(
        experiment_id=store.experiment_id,
        run_name=train_id,
        tags=tags,
    )
    for key, value in config_str.items():
        client.log_param(run.info.run_id, key, value)
    return _build_train_record(store, client.get_run(run.info.run_id))


def get_train_run(store: TrainRecordStore, train_id: str) -> TrainRunRecord:
    """按 train_id tag 检索父 Run 快照；不存在或组合非法则抛域异常。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, train_id)
    return _build_train_record(store, run)


def list_fold_runs(
    store: TrainRecordStore, train_id: str
) -> tuple[FoldRunRecord, ...]:
    """返回该 train 的全部子 Run，按 fold 编号升序。"""
    client = _client(store)
    parent = _search_parent(client, store.experiment_id, train_id)
    children = _search_children(client, store.experiment_id, parent.info.run_id)
    records = [_build_fold_record(train_id, child) for child in children]
    records.sort(key=lambda r: r.fold)
    return tuple(records)


def create_fold_run(
    store: TrainRecordStore,
    train_id: str,
    fold: int,
    *,
    params: Mapping | None = None,
) -> FoldRunRecord:
    """在 running 父 Run 下创建嵌套 fold 子 Run（RUNNING）。"""
    fold = _validate_fold(fold)
    params_str = _validate_params(params)

    client = _client(store)
    parent = _search_parent(client, store.experiment_id, train_id)
    parent_record = _build_train_record(store, parent)
    if parent_record.workflow_state != WorkflowState.RUNNING.value:
        raise IllegalTrainRecord(
            f"父 Run 状态为 {parent_record.workflow_state}，无法新建 fold"
        )

    existing = _search_children(client, store.experiment_id, parent.info.run_id)
    for child in existing:
        if _fold_from_child(child) == fold:
            raise TrainRunConflict(f"fold {fold} 已存在")

    fold_name = f"fold{fold}"
    tags = {
        FOLD_TAG: fold_name,
        "mlflow.parentRunId": parent.info.run_id,
        "mlflow.runName": fold_name,
    }
    child = client.create_run(
        experiment_id=store.experiment_id,
        run_name=fold_name,
        tags=tags,
    )
    for key, value in params_str.items():
        client.log_param(child.info.run_id, key, value)
    return _build_fold_record(train_id, client.get_run(child.info.run_id))


def _find_child(
    client: MlflowClient, store: TrainRecordStore, train_id: str, fold: int
) -> Any:
    parent = _search_parent(client, store.experiment_id, train_id)
    children = _search_children(client, store.experiment_id, parent.info.run_id)
    for child in children:
        if _fold_from_child(child) == fold:
            return child
    raise TrainRecordNotFound(f"未找到 fold {fold}")


def log_fold_metrics(
    store: TrainRecordStore,
    train_id: str,
    fold: int,
    metrics: Mapping[str, float],
) -> FoldRunRecord:
    """指标写指定 fold 子 Run；返回最新快照。"""
    fold = _validate_fold(fold)
    metrics_f = _validate_metrics(metrics)
    client = _client(store)
    child = _find_child(client, store, train_id, fold)
    for key, value in metrics_f.items():
        client.log_metric(child.info.run_id, key, value)
    return _build_fold_record(train_id, client.get_run(child.info.run_id))


def end_fold_run(
    store: TrainRecordStore,
    train_id: str,
    fold: int,
    run_status: str,
    *,
    metrics: Mapping[str, float] | None = None,
) -> FoldRunRecord:
    """终转 fold 子 Run；仅 RUNNING 可终转。"""
    fold = _validate_fold(fold)
    if run_status not in {"FINISHED", "FAILED", "KILLED"}:
        raise IllegalTrainRecord(f"非法 fold 终态: {run_status!r}")

    client = _client(store)
    child = _find_child(client, store, train_id, fold)
    if child.info.status != "RUNNING":
        raise IllegalTrainRecord(f"fold {fold} 状态 {child.info.status} 不可终转")

    if metrics is not None:
        metrics_f = _validate_metrics(metrics)
        for key, value in metrics_f.items():
            client.log_metric(child.info.run_id, key, value)
    client.set_terminated(child.info.run_id, status=run_status)
    return _build_fold_record(train_id, client.get_run(child.info.run_id))


def resume_fold_run(store: TrainRecordStore, train_id: str, fold: int) -> FoldRunRecord:
    """受控恢复：FAILED/KILLED 子 Run 经原 Run ID 恢复 RUNNING。"""
    fold = _validate_fold(fold)
    client = _client(store)
    child = _find_child(client, store, train_id, fold)
    if child.info.status not in {"FAILED", "KILLED"}:
        raise IllegalTrainRecord(f"fold {fold} 状态 {child.info.status} 不可恢复")
    client.update_run(child.info.run_id, status="RUNNING")
    return _build_fold_record(train_id, client.get_run(child.info.run_id))


def _check_completion_gate(
    client: MlflowClient, store: TrainRecordStore, parent_run_id: str
) -> None:
    """completed / 晋级门：全部 REQUIRED_FOLDS 子 Run FINISHED + summary_complete tag。"""
    children = _search_children(client, store.experiment_id, parent_run_id)
    child_by_fold: dict[int, Any] = {}
    for child in children:
        child_by_fold[_fold_from_child(child)] = child
    for fold in REQUIRED_FOLDS:
        if fold not in child_by_fold:
            raise IncompleteTrainRecord(f"缺失 fold {fold}")
        if child_by_fold[fold].info.status != "FINISHED":
            raise IncompleteTrainRecord(f"fold {fold} 未 FINISHED")
    parent = client.get_run(parent_run_id)
    if SUMMARY_COMPLETE_TAG not in parent.data.tags:
        raise IncompleteTrainRecord("缺少三折汇总")


def transition_train_state(
    store: TrainRecordStore,
    train_id: str,
    target: WorkflowState | str,
    *,
    run_status: str | None = None,
) -> TrainRunRecord:
    """父 Run workflow_state 与原生 RunStatus 一起转换；completed 需过晋级门。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, train_id)
    record = _build_train_record(store, run)
    current_state = WorkflowState(record.workflow_state)
    target_state = transition_workflow_state(current_state, target)

    if run_status is None:
        if target_state == WorkflowState.RUNNING:
            target_status = "RUNNING"
        elif target_state in (WorkflowState.COMPLETED, WorkflowState.ARCHIVED):
            target_status = "FINISHED"
        else:
            raise IllegalStateCombination(
                f"目标状态 {target_state.value} 必须显式指定 run_status"
            )
    else:
        allowed = ALLOWED_RUN_STATUSES[target_state]
        if run_status not in allowed:
            raise IllegalStateCombination(
                f"目标状态 {target_state.value} 不接受 run_status={run_status!r}"
            )
        target_status = run_status

    if target_state == WorkflowState.COMPLETED:
        _check_completion_gate(client, store, run.info.run_id)

    if target_state == WorkflowState.RUNNING:
        client.set_tag(run.info.run_id, WORKFLOW_STATE_TAG, target_state.value)
        client.update_run(run.info.run_id, status=target_status)
    elif target_state in (WorkflowState.COMPLETED, WorkflowState.ARCHIVED):
        client.set_tag(run.info.run_id, WORKFLOW_STATE_TAG, target_state.value)
        client.set_terminated(run.info.run_id, status=target_status)
    else:  # PARTIAL / FAILED
        client.set_tag(run.info.run_id, WORKFLOW_STATE_TAG, target_state.value)
        client.set_terminated(run.info.run_id, status=target_status)

    updated = client.get_run(run.info.run_id)
    return _build_train_record(store, updated)


def log_train_summary(
    store: TrainRecordStore,
    train_id: str,
    metrics: Mapping[str, float],
) -> TrainRunRecord:
    """三折汇总指标写父 Run，并标记 summary_complete="true"。"""
    metrics_f = _validate_metrics(metrics)
    client = _client(store)
    run = _search_parent(client, store.experiment_id, train_id)
    for key, value in metrics_f.items():
        client.log_metric(run.info.run_id, key, value)
    client.set_tag(run.info.run_id, SUMMARY_COMPLETE_TAG, "true")
    return _build_train_record(store, client.get_run(run.info.run_id))


def mark_train_invalid(store: TrainRecordStore, train_id: str) -> TrainRunRecord:
    """父 Run record_validity 转至 invalid；不提供复活入口。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, train_id)
    record = _build_train_record(store, run)
    current_validity = RecordValidity(record.record_validity)
    transition_record_validity(current_validity, RecordValidity.INVALID)
    client.set_tag(run.info.run_id, RECORD_VALIDITY_TAG, RecordValidity.INVALID.value)
    return _build_train_record(store, client.get_run(run.info.run_id))


def validate_train_for_promotion(
    store: TrainRecordStore, train_id: str
) -> TrainRunRecord:
    """§10 train 行下游门：存在性→invalid 优先→completed/archived→folds 完整→汇总。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, train_id)
    raw_validity = run.data.tags.get(RECORD_VALIDITY_TAG)
    if raw_validity == RecordValidity.INVALID.value:
        raise InvalidTrainRecord(f"train {train_id} 已标记为 invalid")
    record = _build_train_record(store, run)
    if record.workflow_state not in {
        WorkflowState.COMPLETED.value,
        WorkflowState.ARCHIVED.value,
    }:
        raise IncompleteTrainRecord(
            f"workflow_state 为 {record.workflow_state}，未满足 completed/archived"
        )
    _check_completion_gate(client, store, run.info.run_id)
    return record
