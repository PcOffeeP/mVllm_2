"""B2 — workflow_state 状态机 / RunStatus 组合映射 / record_validity / data status。

对应设计 §5.3（合法转换图与固定组合表）、§10（record_validity 与 data status 语义）。

预期 production API（供 viber 对照实现，模块 `versioning.state`）::

    class StateMachineError(ValueError)             # 状态域异常基类
    class IllegalTransition(StateMachineError)      # 非法状态转换
    class IllegalStateCombination(StateMachineError)
                                                    # workflow_state 与原生 RunStatus 非法组合
    class ReferenceNotAllowed(StateMachineError)    # data status 语义门拒绝引用

    class WorkflowState(StrEnum): PREPARED/RUNNING/PARTIAL/FAILED/COMPLETED/ARCHIVED
        值分别为 "prepared"/"running"/"partial"/"failed"/"completed"/"archived"
    ALLOWED_WORKFLOW_TRANSITIONS: Mapping[WorkflowState, frozenset[WorkflowState]]
    can_transition(current: WorkflowState, target: WorkflowState) -> bool
    transition_workflow_state(current, target) -> WorkflowState   # 非法抛 IllegalTransition

    ALLOWED_RUN_STATUSES: Mapping[WorkflowState, frozenset[str | None]]
        prepared->{None}  running->{"RUNNING"}
        partial->{"FAILED","KILLED"}  failed->{"FAILED","KILLED"}
        completed->{"FINISHED"}  archived->{"FINISHED"}
    validate_workflow_run_status(workflow_state, run_status: str | None) -> None
        # 非法组合抛 IllegalStateCombination；workflow_state 接受枚举或其值字符串。

    class RecordValidity(StrEnum): VALID="valid" / INVALID="invalid"
    transition_record_validity(current, target) -> RecordValidity
        # valid->invalid 允许；同值幂等；invalid->valid 抛 IllegalTransition。

    class DataStatus(StrEnum): ACTIVE="active" / SUPERSEDED="superseded" / INVALID="invalid"
    ALLOWED_DATA_STATUS_TRANSITIONS: Mapping[DataStatus, frozenset[DataStatus]]
        active->{superseded, invalid}  superseded->{invalid}  invalid->{}（另允许同值幂等）
    transition_data_status(current, target) -> DataStatus   # 非法抛 IllegalTransition
    validate_data_status_for_new_reference(status) -> None
        # 仅 active 放行；其余抛 ReferenceNotAllowed
    validate_data_status_for_historical_restore(status) -> None
        # active/superseded 放行；invalid 抛 ReferenceNotAllowed

当前 `versioning` 包尚不存在，本文件全部用例应为 RED（ModuleNotFoundError）。
"""

from __future__ import annotations

import pytest

from versioning.state import (
    ALLOWED_DATA_STATUS_TRANSITIONS,
    ALLOWED_RUN_STATUSES,
    ALLOWED_WORKFLOW_TRANSITIONS,
    DataStatus,
    IllegalStateCombination,
    IllegalTransition,
    RecordValidity,
    ReferenceNotAllowed,
    WorkflowState,
    can_transition,
    transition_data_status,
    transition_record_validity,
    transition_workflow_state,
    validate_data_status_for_historical_restore,
    validate_data_status_for_new_reference,
    validate_workflow_run_status,
)

ALL_WORKFLOW_STATES = [
    WorkflowState.PREPARED,
    WorkflowState.RUNNING,
    WorkflowState.PARTIAL,
    WorkflowState.FAILED,
    WorkflowState.COMPLETED,
    WorkflowState.ARCHIVED,
]

# §5.3 状态流：prepared→running→completed→archived；running↔partial↔failed 只能经 running。
LEGAL_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.PREPARED: {WorkflowState.RUNNING},
    WorkflowState.RUNNING: {
        WorkflowState.COMPLETED,
        WorkflowState.PARTIAL,
        WorkflowState.FAILED,
    },
    WorkflowState.PARTIAL: {WorkflowState.RUNNING},
    WorkflowState.FAILED: {WorkflowState.RUNNING},
    WorkflowState.COMPLETED: {WorkflowState.ARCHIVED},
    WorkflowState.ARCHIVED: set(),
}

LEGAL_PAIRS = [(s, t) for s, targets in LEGAL_TRANSITIONS.items() for t in targets]
ILLEGAL_PAIRS = [
    (s, t) for s in ALL_WORKFLOW_STATES for t in ALL_WORKFLOW_STATES
    if t not in LEGAL_TRANSITIONS[s]
]

# §5.3 固定组合表。
LEGAL_RUN_STATUS_COMBOS = [
    (WorkflowState.PREPARED, None),
    (WorkflowState.RUNNING, "RUNNING"),
    (WorkflowState.PARTIAL, "FAILED"),
    (WorkflowState.PARTIAL, "KILLED"),
    (WorkflowState.FAILED, "FAILED"),
    (WorkflowState.FAILED, "KILLED"),
    (WorkflowState.COMPLETED, "FINISHED"),
    (WorkflowState.ARCHIVED, "FINISHED"),
]

CANDIDATE_RUN_STATUSES = [None, "RUNNING", "FINISHED", "FAILED", "KILLED", "SCHEDULED"]
ILLEGAL_RUN_STATUS_COMBOS = [
    (s, rs) for s in ALL_WORKFLOW_STATES for rs in CANDIDATE_RUN_STATUSES
    if (s, rs) not in LEGAL_RUN_STATUS_COMBOS
]


class TestWorkflowStateEnum:
    def test_values_match_design(self) -> None:
        assert {s.value for s in WorkflowState} == {
            "prepared",
            "running",
            "partial",
            "failed",
            "completed",
            "archived",
        }
        assert len(WorkflowState) == 6

    def test_transition_table_covers_every_state(self) -> None:
        assert set(ALLOWED_WORKFLOW_TRANSITIONS.keys()) == set(ALL_WORKFLOW_STATES)


class TestLegalWorkflowTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        LEGAL_PAIRS,
        ids=[f"{s.value}->{t.value}" for s, t in LEGAL_PAIRS],
    )
    def test_transition_allowed(self, current: WorkflowState, target: WorkflowState) -> None:
        assert transition_workflow_state(current, target) == target
        assert can_transition(current, target) is True


class TestIllegalWorkflowTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        ILLEGAL_PAIRS,
        ids=[f"{s.value}->{t.value}" for s, t in ILLEGAL_PAIRS],
    )
    def test_transition_rejected(self, current: WorkflowState, target: WorkflowState) -> None:
        with pytest.raises(IllegalTransition):
            transition_workflow_state(current, target)
        assert can_transition(current, target) is False

    def test_partial_cannot_jump_to_completed(self) -> None:
        # §5.3/§11.3：partial/failed 只能经受控恢复回 running，不得直接 completed。
        with pytest.raises(IllegalTransition):
            transition_workflow_state(WorkflowState.PARTIAL, WorkflowState.COMPLETED)

    def test_failed_cannot_jump_to_completed(self) -> None:
        with pytest.raises(IllegalTransition):
            transition_workflow_state(WorkflowState.FAILED, WorkflowState.COMPLETED)

    def test_completed_cannot_restart(self) -> None:
        # 已 completed/archived 的训练不得原地重跑（§5.3）。
        with pytest.raises(IllegalTransition):
            transition_workflow_state(WorkflowState.COMPLETED, WorkflowState.RUNNING)

    def test_archived_is_terminal(self) -> None:
        for target in ALL_WORKFLOW_STATES:
            with pytest.raises(IllegalTransition):
                transition_workflow_state(WorkflowState.ARCHIVED, target)


class TestRunStatusCombinationMapping:
    def test_mapping_covers_every_state(self) -> None:
        assert set(ALLOWED_RUN_STATUSES.keys()) == set(ALL_WORKFLOW_STATES)

    @pytest.mark.parametrize(
        ("state", "run_status"),
        LEGAL_RUN_STATUS_COMBOS,
        ids=[f"{s.value}+{rs}" for s, rs in LEGAL_RUN_STATUS_COMBOS],
    )
    def test_legal_combinations_accepted(
        self, state: WorkflowState, run_status: str | None
    ) -> None:
        validate_workflow_run_status(state, run_status)

    @pytest.mark.parametrize(
        ("state", "run_status"),
        ILLEGAL_RUN_STATUS_COMBOS,
        ids=[f"{s.value}+{rs}" for s, rs in ILLEGAL_RUN_STATUS_COMBOS],
    )
    def test_illegal_combinations_rejected(
        self, state: WorkflowState, run_status: str | None
    ) -> None:
        with pytest.raises(IllegalStateCombination):
            validate_workflow_run_status(state, run_status)

    def test_prepared_must_have_no_run(self) -> None:
        # prepared 表示 Run 创建前的本地冻结状态（D038）；任何原生状态都非法。
        for rs in ["RUNNING", "FINISHED", "FAILED", "KILLED"]:
            with pytest.raises(IllegalStateCombination):
                validate_workflow_run_status(WorkflowState.PREPARED, rs)

    def test_completed_and_archived_require_finished(self) -> None:
        for state in (WorkflowState.COMPLETED, WorkflowState.ARCHIVED):
            for rs in ["RUNNING", "FAILED", "KILLED", None]:
                with pytest.raises(IllegalStateCombination):
                    validate_workflow_run_status(state, rs)

    def test_unknown_run_status_rejected(self) -> None:
        with pytest.raises(IllegalStateCombination):
            validate_workflow_run_status(WorkflowState.RUNNING, "BOGUS")

    def test_workflow_state_value_string_accepted(self) -> None:
        # workflow_state 参数接受枚举值字符串，非法值按组合非法拒绝。
        validate_workflow_run_status("running", "RUNNING")
        with pytest.raises(IllegalStateCombination):
            validate_workflow_run_status("running", "FINISHED")


class TestWorkflowStringCoercion:
    """reviewer 修复的反向回归：can_transition/transition_workflow_state
    统一接受值字符串并 coerce，非法值抛领域异常而非 KeyError/TypeError。"""

    def test_can_transition_rejects_unknown_state_string(self) -> None:
        with pytest.raises(IllegalStateCombination):
            can_transition("bogus", "running")
        with pytest.raises(IllegalStateCombination):
            can_transition("running", "bogus")

    def test_transition_rejects_unknown_state_string(self) -> None:
        with pytest.raises(IllegalStateCombination):
            transition_workflow_state("bogus", "running")
        with pytest.raises(IllegalStateCombination):
            transition_workflow_state("running", "bogus")

    def test_illegal_string_transition_raises_illegal_transition(self) -> None:
        # 状态值合法但转换非法：与枚举路径同一条 IllegalTransition（§5.3）。
        with pytest.raises(IllegalTransition):
            transition_workflow_state("running", "archived")
        assert can_transition("running", "archived") is False

    def test_legal_string_transition_matches_enum_behavior(self) -> None:
        # 字符串与枚举入口结果一致：返回枚举单例而非裸字符串。
        result = transition_workflow_state("prepared", "running")
        assert result is WorkflowState.RUNNING
        assert can_transition("prepared", "running") is True

    @pytest.mark.parametrize(
        ("current", "target"),
        LEGAL_PAIRS + ILLEGAL_PAIRS,
        ids=[f"str:{s.value}->{t.value}" for s, t in LEGAL_PAIRS + ILLEGAL_PAIRS],
    )
    def test_string_inputs_parity_with_enum_inputs(
        self, current: WorkflowState, target: WorkflowState
    ) -> None:
        assert can_transition(current.value, target.value) is can_transition(
            current, target
        )


class TestRecordValidity:
    def test_enum_values(self) -> None:
        assert {v.value for v in RecordValidity} == {"valid", "invalid"}

    def test_valid_can_be_marked_invalid(self) -> None:
        assert (
            transition_record_validity(RecordValidity.VALID, RecordValidity.INVALID)
            == RecordValidity.INVALID
        )

    def test_same_value_is_idempotent_noop(self) -> None:
        assert (
            transition_record_validity(RecordValidity.VALID, RecordValidity.VALID)
            == RecordValidity.VALID
        )
        assert (
            transition_record_validity(RecordValidity.INVALID, RecordValidity.INVALID)
            == RecordValidity.INVALID
        )

    def test_invalid_cannot_be_revived(self) -> None:
        # §2.6/§10：不得通过改回 valid 复活旧事实。
        with pytest.raises(IllegalTransition):
            transition_record_validity(RecordValidity.INVALID, RecordValidity.VALID)


class TestDataStatus:
    def test_enum_values(self) -> None:
        assert {s.value for s in DataStatus} == {"active", "superseded", "invalid"}

    def test_transition_table_covers_every_status(self) -> None:
        assert set(ALLOWED_DATA_STATUS_TRANSITIONS.keys()) == set(DataStatus)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (DataStatus.ACTIVE, DataStatus.SUPERSEDED),
            (DataStatus.ACTIVE, DataStatus.INVALID),
            (DataStatus.SUPERSEDED, DataStatus.INVALID),
            (DataStatus.ACTIVE, DataStatus.ACTIVE),          # 幂等
            (DataStatus.SUPERSEDED, DataStatus.SUPERSEDED),  # 幂等
            (DataStatus.INVALID, DataStatus.INVALID),        # 幂等
        ],
    )
    def test_legal_transitions(self, current: DataStatus, target: DataStatus) -> None:
        assert transition_data_status(current, target) == target

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (DataStatus.SUPERSEDED, DataStatus.ACTIVE),   # 不得复活
            (DataStatus.INVALID, DataStatus.ACTIVE),      # 不得复活
            (DataStatus.INVALID, DataStatus.SUPERSEDED),  # 不得降级复活
        ],
    )
    def test_illegal_reverse_transitions(
        self, current: DataStatus, target: DataStatus
    ) -> None:
        with pytest.raises(IllegalTransition):
            transition_data_status(current, target)


class TestDataStatusReferenceSemantics:
    # §10 / D032：active 可新引用；superseded 仅历史恢复；invalid 禁止新引用。
    def test_active_allows_new_reference(self) -> None:
        validate_data_status_for_new_reference(DataStatus.ACTIVE)

    @pytest.mark.parametrize("status", [DataStatus.SUPERSEDED, DataStatus.INVALID])
    def test_non_active_rejects_new_reference(self, status: DataStatus) -> None:
        with pytest.raises(ReferenceNotAllowed):
            validate_data_status_for_new_reference(status)

    @pytest.mark.parametrize("status", [DataStatus.ACTIVE, DataStatus.SUPERSEDED])
    def test_historical_restore_allowed(self, status: DataStatus) -> None:
        validate_data_status_for_historical_restore(status)

    def test_invalid_rejects_historical_restore(self) -> None:
        # invalid 只保留历史证据，禁止训练、续跑和正式测评（§10）。
        with pytest.raises(ReferenceNotAllowed):
            validate_data_status_for_historical_restore(DataStatus.INVALID)
