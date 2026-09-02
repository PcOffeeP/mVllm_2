"""workflow_state / RunStatus / record_validity / data status 状态机。

对应设计 §5.3、§10：严格约束训练工作流状态转换、MLflow 原生 RunStatus 合法组合、
记录有效性与数据生命周期状态的流向。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Mapping


class StateMachineError(ValueError):
    """状态域异常基类。"""


class IllegalTransition(StateMachineError):
    """非法状态转换。"""


class IllegalStateCombination(StateMachineError):
    """``workflow_state`` 与原生 ``RunStatus`` 的非法组合。"""


class ReferenceNotAllowed(StateMachineError):
    """数据状态语义门拒绝引用。"""


class WorkflowState(StrEnum):
    """训练工作流状态（项目语义，与 MLflow 原生 RunStatus 组合使用）。"""

    PREPARED = "prepared"
    RUNNING = "running"
    PARTIAL = "partial"
    FAILED = "failed"
    COMPLETED = "completed"
    ARCHIVED = "archived"


ALLOWED_WORKFLOW_TRANSITIONS: Mapping[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.PREPARED: frozenset({WorkflowState.RUNNING}),
    WorkflowState.RUNNING: frozenset(
        {WorkflowState.COMPLETED, WorkflowState.PARTIAL, WorkflowState.FAILED}
    ),
    WorkflowState.PARTIAL: frozenset({WorkflowState.RUNNING}),
    WorkflowState.FAILED: frozenset({WorkflowState.RUNNING}),
    WorkflowState.COMPLETED: frozenset({WorkflowState.ARCHIVED}),
    WorkflowState.ARCHIVED: frozenset(),
}


def _coerce_workflow_state(state: WorkflowState | str) -> WorkflowState:
    if isinstance(state, WorkflowState):
        return state
    try:
        return WorkflowState(state)
    except ValueError as exc:
        raise IllegalStateCombination(f"非法 workflow_state: {state!r}") from exc


def can_transition(current: WorkflowState | str, target: WorkflowState | str) -> bool:
    """判断 ``current -> target`` 是否为合法工作流转换（自环非法）。

    Args:
        current: 项目工作流状态枚举或其值字符串。
        target: 项目工作流状态枚举或其值字符串。

    Raises:
        IllegalStateCombination: ``current`` 或 ``target`` 为非法状态值。
    """
    state_current = _coerce_workflow_state(current)
    state_target = _coerce_workflow_state(target)
    return state_target in ALLOWED_WORKFLOW_TRANSITIONS[state_current]


def transition_workflow_state(
    current: WorkflowState | str, target: WorkflowState | str
) -> WorkflowState:
    """执行工作流状态转换，非法转换抛 ``IllegalTransition``。

    与 ``can_transition`` 语义一致：自环视为非法；同时接受枚举或其值字符串。

    Args:
        current: 项目工作流状态枚举或其值字符串。
        target: 项目工作流状态枚举或其值字符串。

    Raises:
        IllegalStateCombination: ``current`` 或 ``target`` 为非法状态值。
        IllegalTransition: ``current -> target`` 不在允许表中。
    """
    state_current = _coerce_workflow_state(current)
    state_target = _coerce_workflow_state(target)
    if not can_transition(state_current, state_target):
        raise IllegalTransition(
            f"非法工作流转换: {state_current.value} -> {state_target.value}"
        )
    return state_target


ALLOWED_RUN_STATUSES: Mapping[WorkflowState, frozenset[str | None]] = {
    WorkflowState.PREPARED: frozenset({None}),
    WorkflowState.RUNNING: frozenset({"RUNNING"}),
    WorkflowState.PARTIAL: frozenset({"FAILED", "KILLED"}),
    WorkflowState.FAILED: frozenset({"FAILED", "KILLED"}),
    WorkflowState.COMPLETED: frozenset({"FINISHED"}),
    WorkflowState.ARCHIVED: frozenset({"FINISHED"}),
}


def validate_workflow_run_status(
    workflow_state: WorkflowState | str, run_status: str | None
) -> None:
    """校验 ``workflow_state`` 与 MLflow 原生 ``RunStatus`` 的固定组合。

    Args:
        workflow_state: 项目工作流状态枚举或其值字符串。
        run_status: MLflow 原生 RunStatus 字符串，``prepared`` 对应 ``None``。

    Raises:
        IllegalStateCombination: 组合不在设计 §5.3 固定表中。
    """
    state = _coerce_workflow_state(workflow_state)
    allowed = ALLOWED_RUN_STATUSES.get(state, frozenset())
    if run_status not in allowed:
        raise IllegalStateCombination(
            f"非法组合: workflow_state={state.value}, run_status={run_status!r}"
        )


class RecordValidity(StrEnum):
    """训练/模型/测评记录的正式有效性。"""

    VALID = "valid"
    INVALID = "invalid"


def transition_record_validity(
    current: RecordValidity, target: RecordValidity
) -> RecordValidity:
    """转移记录有效性。

    - ``valid -> invalid`` 允许；
    - 同值幂等；
    - ``invalid -> valid`` 拒绝（不得复活旧事实）。
    """
    if current == target:
        return target
    if current == RecordValidity.VALID and target == RecordValidity.INVALID:
        return RecordValidity.INVALID
    raise IllegalTransition(
        f"非法有效性转换: {current.value} -> {target.value}"
    )


class DataStatus(StrEnum):
    """数据 release 生命周期状态。"""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


ALLOWED_DATA_STATUS_TRANSITIONS: Mapping[DataStatus, frozenset[DataStatus]] = {
    DataStatus.ACTIVE: frozenset({DataStatus.SUPERSEDED, DataStatus.INVALID}),
    DataStatus.SUPERSEDED: frozenset({DataStatus.INVALID}),
    DataStatus.INVALID: frozenset(),
}


def transition_data_status(current: DataStatus, target: DataStatus) -> DataStatus:
    """转移数据生命周期状态。

    - ``active -> superseded/invalid`` 允许；
    - ``superseded -> invalid`` 允许；
    - 同值幂等；
    - ``superseded -> active``、``invalid -> *`` 拒绝。
    """
    if current == target:
        return target
    if target in ALLOWED_DATA_STATUS_TRANSITIONS[current]:
        return target
    raise IllegalTransition(
        f"非法数据状态转换: {current.value} -> {target.value}"
    )


def validate_data_status_for_new_reference(status: DataStatus) -> None:
    """仅 ``active`` 数据允许创建新引用。"""
    if status is not DataStatus.ACTIVE:
        raise ReferenceNotAllowed(
            f"状态为 {status.value} 的数据不允许新引用"
        )


def validate_data_status_for_historical_restore(status: DataStatus) -> None:
    """``active`` 与 ``superseded`` 允许历史恢复，``invalid`` 拒绝。"""
    if status is DataStatus.INVALID:
        raise ReferenceNotAllowed(
            f"状态为 {status.value} 的数据禁止历史恢复"
        )
