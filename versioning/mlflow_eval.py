"""B7a — MLflow 测评记录：eval-v 独立父 Run + 三种 scope + fold 绑定 + holdout 鉴权。

对应设计 docs/plans/2026-09-01-readable-version-control-design.md：
§2.8 + D023（独立父 Run）、§5.5（三种 scope 与 fold 绑定纪律）、
§5.6（holdout 鉴权）、§2.6（record_validity / SQLite + 本地 artifacts）、
§5.3 + D038（workflow_state ↔ RunStatus 固定组合）、§10（eval 结论门）。
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from mlflow.entities import ViewType
from mlflow.tracking import MlflowClient

from versioning.data_release import load_release_metadata, validate_training_reference
from versioning.holdout import (
    ClaimIdentity,
    ClaimNotFound,
    HoldoutError,
    acquire_claim,
    load_claim,
    load_pre_registration,
    mark_claim_consumed,
    validate_holdout_layout,
    validate_claim_consumed,
)
from versioning.ids import parse_data_id, parse_eval_id, parse_model_id
from versioning.mlflow_train import (
    TrainRecordStore,
    validate_train_for_promotion,
)
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


DEFAULT_EVAL_EXPERIMENT: str = "mVllm2-evaluation"
REQUIRED_FOLDS: tuple[int, ...] = (0, 1, 2)
SCOPES: tuple[str, ...] = ("single_fold", "cross_validation", "full")
OUTCOMES: tuple[str, ...] = ("passed", "failed")

EVAL_ID_TAG: str = "eval_id"
WORKFLOW_STATE_TAG: str = "workflow_state"
RECORD_VALIDITY_TAG: str = "record_validity"
MODEL_ID_TAG: str = "model_id"
MODEL_VERSION_NUMBER_TAG: str = "model_version_number"
DATA_VERSION_TAG: str = "data_version"
CONFIG_TAG: str = "config"
GIT_COMMIT_TAG: str = "git_commit"
SCOPE_TAG: str = "scope"
SPLIT_TAG: str = "split"
OUTCOME_TAG: str = "outcome"
SUMMARY_COMPLETE_TAG: str = "summary_complete"
AGGREGATE_FOLDS_TAG: str = "aggregate_folds"
FOLD_TAG: str = "fold"
MODEL_ARTIFACT_TAG: str = "model_artifact"
DATA_SPLIT_TAG: str = "data_split"
SAMPLE_COUNT_TAG: str = "sample_count"
RECORDS_TAG: str = "records"
FAILURES_TAG: str = "failures"
PRE_REGISTRATION_PATH_TAG: str = "pre_registration_path"
PRE_REGISTRATION_SHA256_TAG: str = "pre_registration_sha256"
HOLDOUT_AUTHORIZATION_DIR_TAG: str = "holdout_authorization_dir"
HOLDOUT_EXECUTOR_TAG: str = "holdout_executor"
REGISTERED_MODEL_NAME: str = "mVllm2"


class MLflowEvalError(ValueError):
    """测评记录域异常基类。"""


class EvalRecordNotFound(MLflowEvalError):
    """指定 eval 记录或其 fold 子 Run 在本 store 中不存在。"""


class EvalRunConflict(MLflowEvalError):
    """同一 eval-v... 已存在父 Run，或同父 Run 下同 fold 子 Run 已存在。"""


class IllegalEvalRecord(MLflowEvalError):
    """记录构造/操作输入非法或结构违规。"""


class IncompleteEvalRecord(MLflowEvalError):
    """completed / 结论门拒绝。"""


class InvalidEvalRecord(MLflowEvalError):
    """record_validity=invalid 的测评记录被下游校验拒绝。"""


class HoldoutAuthorizationError(MLflowEvalError):
    """holdout 鉴权 fail-closed。"""


@dataclass(frozen=True)
class EvalRecordStore:
    """测评记录 store 句柄（SQLite + 本地 artifacts）。"""

    root: Path
    tracking_uri: str
    experiment_id: str
    artifact_location: str


@dataclass(frozen=True)
class EvalFoldRecord:
    """fold 子 Run 只读快照。"""

    eval_id: str
    fold: int
    run_id: str
    parent_run_id: str
    run_name: str
    status: str
    model_artifact: str
    data_split: str
    sample_count: int
    records: str
    failures: str
    metrics: Mapping[str, float]


@dataclass(frozen=True)
class EvalRunRecord:
    """eval 父 Run 只读快照。"""

    eval_id: str
    run_id: str
    experiment_id: str
    run_name: str
    workflow_state: str
    run_status: str
    record_validity: str
    model_id: str
    model_version_number: int
    data_version: str
    config: str
    git_commit: str
    scope: str
    split: str | None
    outcome: str | None
    metrics: Mapping[str, float]
    folds: Mapping[int, EvalFoldRecord]
    pre_registration_path: str | None
    pre_registration_sha256: str | None
    holdout_authorization_dir: str | None
    holdout_executor: str | None


def _client(store: EvalRecordStore) -> MlflowClient:
    """按 store 句柄构造独立 MLflow Client，不依赖全局 tracking 状态。"""
    return MlflowClient(tracking_uri=store.tracking_uri)


def _validate_non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise IllegalEvalRecord(f"{name} 必须是非空字符串: {value!r}")
    return value


def _is_metric_value(value: Any) -> bool:
    """metrics 只允许 int/float，显式拒绝 bool。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_metrics(metrics: Any) -> dict[str, float]:
    if not isinstance(metrics, Mapping) or not metrics:
        raise IllegalEvalRecord("metrics 必须是非空 Mapping")
    result: dict[str, float] = {}
    for key, value in metrics.items():
        if not isinstance(key, str) or not key:
            raise IllegalEvalRecord(f"metrics 键必须是非空字符串: {key!r}")
        if not _is_metric_value(value):
            raise IllegalEvalRecord(f"metrics 值必须是 int/float: {value!r}")
        result[key] = float(value)
    return result


def _validate_model_version_number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IllegalEvalRecord(f"model_version_number 必须是 ≥1 整数: {value!r}")
    if value < 1:
        raise IllegalEvalRecord(f"model_version_number 必须 ≥1: {value!r}")
    return value


def _validate_sample_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IllegalEvalRecord(f"sample_count 必须是非负整数: {value!r}")
    if value < 0:
        raise IllegalEvalRecord(f"sample_count 必须 ≥0: {value!r}")
    return value


def _validate_fold(fold: Any) -> int:
    if isinstance(fold, bool) or not isinstance(fold, int):
        raise IllegalEvalRecord(f"fold 必须是整数: {fold!r}")
    if fold not in REQUIRED_FOLDS:
        raise IllegalEvalRecord(f"fold 编号非法: {fold!r}")
    return fold


def _parse_fold_tag(tag_value: str) -> int:
    if not isinstance(tag_value, str) or not tag_value.startswith("fold"):
        raise IllegalEvalRecord(f"非法 fold tag 值: {tag_value!r}")
    try:
        number = int(tag_value.removeprefix("fold"))
    except ValueError as exc:
        raise IllegalEvalRecord(f"无法解析 fold tag: {tag_value!r}") from exc
    if number not in REQUIRED_FOLDS:
        raise IllegalEvalRecord(f"fold tag 编号越界: {tag_value!r}")
    return number


def _parent_run_id_from_child(run: Any) -> str:
    return run.data.tags.get("mlflow.parentRunId", "")


def open_eval_store(
    root: Path, *, experiment_name: str = DEFAULT_EVAL_EXPERIMENT
) -> EvalRecordStore:
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

    return EvalRecordStore(
        root=root,
        tracking_uri=tracking_uri,
        experiment_id=experiment_id,
        artifact_location=str(artifact_path.resolve()),
    )


def _search_parent(client: MlflowClient, experiment_id: str, eval_id: str) -> Any:
    parse_eval_id(eval_id)
    runs = client.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"tags.{EVAL_ID_TAG} = '{eval_id}'",
        run_view_type=ViewType.ALL,
        max_results=1,
    )
    if not runs:
        raise EvalRecordNotFound(f"未找到 eval: {eval_id}")
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


def _validate_aggregate_folds_tag(value: str) -> None:
    """校验 aggregate_folds 每项为 fold<N>（N ∈ REQUIRED_FOLDS）。"""
    if not value:
        raise IllegalEvalRecord("aggregate_folds 不能为空")
    for item in value.split(","):
        item = item.strip()
        if not item:
            raise IllegalEvalRecord("aggregate_folds 含空项")
        _parse_fold_tag(item)


def _validate_parent_tags(
    run: Any, *, allow_completed_running_recovery: bool = False
) -> None:
    """读取 fail-closed：校验父 Run 组合与各类 tag 值域/可解析性。"""
    tags = run.data.tags
    if not (
        allow_completed_running_recovery
        and tags.get(WORKFLOW_STATE_TAG) == WorkflowState.COMPLETED.value
        and run.info.status == "RUNNING"
    ):
        validate_workflow_run_status(tags.get(WORKFLOW_STATE_TAG), run.info.status)

    validity = tags.get(RECORD_VALIDITY_TAG)
    if validity not in (RecordValidity.VALID.value, RecordValidity.INVALID.value):
        raise IllegalEvalRecord(f"父 Run record_validity 非法: {validity!r}")

    scope = tags.get(SCOPE_TAG)
    if scope not in SCOPES:
        raise IllegalEvalRecord(f"父 Run scope 非法: {scope!r}")

    model_id = tags.get(MODEL_ID_TAG)
    try:
        parse_model_id(model_id)
    except Exception as exc:
        raise IllegalEvalRecord(f"父 Run model_id 非法: {model_id!r}") from exc

    model_version_number = tags.get(MODEL_VERSION_NUMBER_TAG)
    try:
        _validate_model_version_number(int(model_version_number))
    except Exception as exc:
        raise IllegalEvalRecord(
            f"父 Run model_version_number 非法: {model_version_number!r}"
        ) from exc

    data_version = tags.get(DATA_VERSION_TAG)
    try:
        parse_data_id(data_version)
    except Exception as exc:
        raise IllegalEvalRecord(f"父 Run data_version 非法: {data_version!r}") from exc

    _validate_non_empty_string(tags.get(CONFIG_TAG), "config")
    _validate_non_empty_string(tags.get(GIT_COMMIT_TAG), "git_commit")

    if scope in ("single_fold", "full"):
        _validate_non_empty_string(tags.get(SPLIT_TAG), "split")

    outcome = tags.get(OUTCOME_TAG)
    if outcome is not None and outcome not in OUTCOMES:
        raise IllegalEvalRecord(f"父 Run outcome 非法: {outcome!r}")

    aggregate_folds = tags.get(AGGREGATE_FOLDS_TAG)
    if aggregate_folds is not None:
        if scope != "cross_validation":
            raise IllegalEvalRecord("aggregate_folds 仅允许出现在 cross_validation")
        _validate_aggregate_folds_tag(aggregate_folds)

    prereg_path = tags.get(PRE_REGISTRATION_PATH_TAG)
    prereg_sha256 = tags.get(PRE_REGISTRATION_SHA256_TAG)
    authorization_dir = tags.get(HOLDOUT_AUTHORIZATION_DIR_TAG)
    executor = tags.get(HOLDOUT_EXECUTOR_TAG)
    holdout_values = (prereg_path, prereg_sha256, authorization_dir, executor)
    if any(value is None for value in holdout_values) and any(
        value is not None for value in holdout_values
    ):
        raise IllegalEvalRecord("holdout 预注册、摘要、授权目录与 executor 必须同时存在或缺失")
    if prereg_path is not None:
        _validate_non_empty_string(prereg_path, "pre_registration_path")
        if len(prereg_sha256) != 64:
            raise IllegalEvalRecord("pre_registration_sha256 必须是 64 位十六进制摘要")
        try:
            int(prereg_sha256, 16)
        except ValueError as exc:
            raise IllegalEvalRecord(
                "pre_registration_sha256 必须是 64 位十六进制摘要"
            ) from exc
        _validate_non_empty_string(authorization_dir, "holdout_authorization_dir")
        _validate_non_empty_string(executor, "holdout_executor")


def _validate_child_tags(run: Any) -> None:
    """校验子 Run 绑定 tags 齐全且 well-formed。"""
    tags = run.data.tags
    _validate_non_empty_string(tags.get(MODEL_ARTIFACT_TAG), "model_artifact")
    _validate_non_empty_string(tags.get(DATA_SPLIT_TAG), "data_split")
    _validate_non_empty_string(tags.get(RECORDS_TAG), "records")
    _validate_non_empty_string(tags.get(FAILURES_TAG), "failures")

    sample_count = tags.get(SAMPLE_COUNT_TAG)
    try:
        _validate_sample_count(int(sample_count))
    except Exception as exc:
        raise IllegalEvalRecord(
            f"子 Run sample_count 非法: {sample_count!r}"
        ) from exc


def _build_fold_record(eval_id: str, run: Any) -> EvalFoldRecord:
    tags = run.data.tags
    fold = _parse_fold_tag(tags.get(FOLD_TAG, ""))
    _validate_child_tags(run)
    return EvalFoldRecord(
        eval_id=eval_id,
        fold=fold,
        run_id=run.info.run_id,
        parent_run_id=_parent_run_id_from_child(run),
        run_name=run.info.run_name or tags.get("mlflow.runName", ""),
        status=run.info.status,
        model_artifact=tags[MODEL_ARTIFACT_TAG],
        data_split=tags[DATA_SPLIT_TAG],
        sample_count=int(tags[SAMPLE_COUNT_TAG]),
        records=tags[RECORDS_TAG],
        failures=tags[FAILURES_TAG],
        metrics=dict(run.data.metrics),
    )


def _build_folds(
    client: MlflowClient, experiment_id: str, parent_run_id: str, eval_id: str
) -> dict[int, EvalFoldRecord]:
    children = _search_children(client, experiment_id, parent_run_id)
    records: list[EvalFoldRecord] = []
    seen: set[int] = set()
    for child in children:
        record = _build_fold_record(eval_id, child)
        if record.fold in seen:
            raise IllegalEvalRecord(f"重复 fold: {record.fold}")
        seen.add(record.fold)
        records.append(record)
    records.sort(key=lambda r: r.fold)
    return {r.fold: r for r in records}


def _build_eval_record(store: EvalRecordStore, run: Any) -> EvalRunRecord:
    _validate_parent_tags(run)
    client = _client(store)
    tags = run.data.tags
    eval_id = tags[EVAL_ID_TAG]
    scope = tags[SCOPE_TAG]
    folds = _build_folds(client, store.experiment_id, run.info.run_id, eval_id)
    _validate_scope_folds_count(scope, folds)

    return EvalRunRecord(
        eval_id=eval_id,
        run_id=run.info.run_id,
        experiment_id=run.info.experiment_id,
        run_name=run.info.run_name or tags.get("mlflow.runName", ""),
        workflow_state=tags[WORKFLOW_STATE_TAG],
        run_status=run.info.status,
        record_validity=tags[RECORD_VALIDITY_TAG],
        model_id=tags[MODEL_ID_TAG],
        model_version_number=int(tags[MODEL_VERSION_NUMBER_TAG]),
        data_version=tags[DATA_VERSION_TAG],
        config=tags[CONFIG_TAG],
        git_commit=tags[GIT_COMMIT_TAG],
        scope=scope,
        split=tags.get(SPLIT_TAG),
        outcome=tags.get(OUTCOME_TAG),
        metrics=dict(run.data.metrics),
        folds=folds,
        pre_registration_path=tags.get(PRE_REGISTRATION_PATH_TAG),
        pre_registration_sha256=tags.get(PRE_REGISTRATION_SHA256_TAG),
        holdout_authorization_dir=tags.get(HOLDOUT_AUTHORIZATION_DIR_TAG),
        holdout_executor=tags.get(HOLDOUT_EXECUTOR_TAG),
    )


def _validate_scope_folds_count(scope: str, folds: Mapping[int, Any]) -> None:
    """读取层校验 fold 数量不超过 scope 上限。"""
    count = len(folds)
    if scope == "full" and count != 0:
        raise IllegalEvalRecord("full scope 不得有 fold 子 Run")
    if scope == "single_fold" and count > 1:
        raise IllegalEvalRecord("single_fold scope 最多一个 fold 子 Run")
    if scope == "cross_validation" and count > 3:
        raise IllegalEvalRecord("cross_validation scope 最多三个 fold 子 Run")


def _authorize_holdout(
    data_root: Path,
    data_version: str,
    eval_id: str,
    model_id: str,
    split: str | None,
    pre_registration: Path | None,
    executor: str | None,
) -> tuple[str, str, str, str]:
    """holdout 数据鉴权：claim + pre_registration 校验。"""
    if not split:
        raise HoldoutAuthorizationError("holdout 测评必须声明 split")
    if pre_registration is None:
        raise HoldoutAuthorizationError("holdout 测评必须提供 pre_registration")
    if executor is None or not isinstance(executor, str) or not executor:
        raise HoldoutAuthorizationError("holdout 测评必须提供 executor")

    try:
        prereg_path = Path(pre_registration).resolve()
        pre = load_pre_registration(prereg_path)
    except HoldoutError as exc:
        raise HoldoutAuthorizationError(f"预注册校验失败: {exc}") from exc

    if pre.eval_version != eval_id:
        raise HoldoutAuthorizationError("pre_registration eval_version 不一致")
    if pre.model_version != model_id:
        raise HoldoutAuthorizationError("pre_registration model_version 不一致")
    if pre.data_version != data_version:
        raise HoldoutAuthorizationError("pre_registration data_version 不一致")
    if pre.split != split:
        raise HoldoutAuthorizationError("pre_registration split 不一致")

    authorization_dir = Path(data_root) / "releases" / data_version / "authorization"
    try:
        claim = load_claim(authorization_dir)
    except ClaimNotFound as exc:
        raise HoldoutAuthorizationError(f"未找到 claim: {exc}") from exc
    except HoldoutError as exc:
        raise HoldoutAuthorizationError(f"claim 校验失败: {exc}") from exc

    expected = ClaimIdentity(
        eval_version=eval_id,
        model_version=model_id,
        data_version=data_version,
        split=split,
    )
    if claim.identity != expected or claim.executor != executor:
        raise HoldoutAuthorizationError("claim 四元组或 executor 不一致")

    prereg_sha256 = hashlib.sha256(prereg_path.read_bytes()).hexdigest()
    if claim.pre_registration_sha256 != prereg_sha256:
        raise HoldoutAuthorizationError("claim 绑定的 pre_registration 摘要不一致")

    consumed_path = authorization_dir / "consumed.yaml"
    if consumed_path.exists():
        raise HoldoutAuthorizationError("claim 已消费")
    return str(prereg_path), prereg_sha256, str(authorization_dir.resolve()), executor


def _validate_registry_reference(
    client: MlflowClient,
    store: EvalRecordStore,
    data_root: Path,
    model_id: str,
    model_version_number: int,
) -> None:
    """正式 eval 必须引用在线仍满足 train/data 门的完整 Registry 版本。"""
    try:
        version = client.get_model_version(
            REGISTERED_MODEL_NAME, str(model_version_number)
        )
    except Exception as exc:
        raise IllegalEvalRecord(
            f"Registry 中不存在 {REGISTERED_MODEL_NAME} version={model_version_number}"
        ) from exc
    if version.tags.get(MODEL_ID_TAG) != model_id:
        raise IllegalEvalRecord("Registry 数值 Model Version 与 model_id 不匹配")
    if version.tags.get(RECORD_VALIDITY_TAG) != RecordValidity.VALID.value:
        raise IllegalEvalRecord("Registry Model Version 无效或缺少有效性标记")
    if version.tags.get("source_kind") == "base" or version.tags.get("source_scope") == "diagnostic_fold":
        from versioning.registry import open_registry_store, validate_model_for_evaluation
        try:
            validate_model_for_evaluation(open_registry_store(store.root, data_root=data_root),
                model_id, model_version_number)
        except Exception as exc:
            raise IllegalEvalRecord(f"Registry frozen source rejected: {exc}") from exc
        return
    required_tags = ("train_id", DATA_VERSION_TAG, "prompt_version", GIT_COMMIT_TAG)
    if any(not version.tags.get(key) for key in required_tags):
        raise IllegalEvalRecord("Registry Model Version 缺少训练来源绑定")
    matches = [
        item
        for item in client.search_model_versions(f"name='{REGISTERED_MODEL_NAME}'")
        if item.tags.get(MODEL_ID_TAG) == model_id
    ]
    if len(matches) != 1 or int(matches[0].version) != model_version_number:
        raise IllegalEvalRecord("model_id 在 Registry 中缺失、重复或数值版本不一致")
    experiment = client.get_experiment_by_name("mVllm2-training")
    if experiment is None:
        raise IllegalEvalRecord("Registry 引用的训练实验不存在")
    train_store = TrainRecordStore(
        root=store.root,
        tracking_uri=store.tracking_uri,
        experiment_id=experiment.experiment_id,
        artifact_location=store.artifact_location,
    )
    try:
        train = validate_train_for_promotion(train_store, version.tags["train_id"])
        validate_training_reference(data_root, train.data_version)
    except Exception as exc:
        raise IllegalEvalRecord(f"Registry 训练来源门拒绝: {exc}") from exc
    if (
        train.data_version != version.tags[DATA_VERSION_TAG]
        or train.prompt_version != version.tags["prompt_version"]
        or train.git_commit != version.tags[GIT_COMMIT_TAG]
        or train.run_id != version.run_id
    ):
        raise IllegalEvalRecord("Registry Model Version 与训练来源绑定不一致")


def create_eval_run(
    store: EvalRecordStore,
    eval_id: str,
    *,
    model_id: str,
    model_version_number: int,
    data_version: str,
    config: str,
    git_commit: str,
    scope: str,
    split: str | None = None,
    data_root: Path,
    pre_registration: Path | None = None,
    executor: str | None = None,
) -> EvalRunRecord:
    """创建 eval-v 父 Run；创建即 running/RUNNING/valid。"""
    parse_eval_id(eval_id)
    parse_model_id(model_id)
    parse_data_id(data_version)
    model_version_number = _validate_model_version_number(model_version_number)
    config = _validate_non_empty_string(config, "config")
    git_commit = _validate_non_empty_string(git_commit, "git_commit")
    if scope not in SCOPES:
        raise IllegalEvalRecord(f"非法 scope: {scope!r}")

    if scope in ("single_fold", "full"):
        split = _validate_non_empty_string(split, "split")

    try:
        meta = load_release_metadata(Path(data_root), data_version)
    except Exception as exc:
        raise IllegalEvalRecord(f"无法加载 data release: {exc}") from exc

    prereg_binding: tuple[str, str] | None = None
    if meta.purpose == "holdout":
        try:
            validate_holdout_layout(Path(data_root) / "releases" / data_version)
        except HoldoutError as exc:
            raise HoldoutAuthorizationError(f"holdout 布局校验失败: {exc}") from exc
        prereg_binding = _authorize_holdout(
            data_root,
            data_version,
            eval_id,
            model_id,
            split,
            pre_registration,
            executor,
        )

    client = _client(store)
    _validate_registry_reference(
        client, store, Path(data_root), model_id, model_version_number
    )

    try:
        _search_parent(client, store.experiment_id, eval_id)
    except EvalRecordNotFound:
        pass
    else:
        raise EvalRunConflict(f"eval {eval_id} 已存在")

    tags: dict[str, str] = {
        EVAL_ID_TAG: eval_id,
        WORKFLOW_STATE_TAG: WorkflowState.RUNNING.value,
        RECORD_VALIDITY_TAG: RecordValidity.VALID.value,
        MODEL_ID_TAG: model_id,
        MODEL_VERSION_NUMBER_TAG: str(model_version_number),
        DATA_VERSION_TAG: data_version,
        CONFIG_TAG: config,
        GIT_COMMIT_TAG: git_commit,
        SCOPE_TAG: scope,
    }
    if split is not None:
        tags[SPLIT_TAG] = split
    if prereg_binding is not None:
        tags[PRE_REGISTRATION_PATH_TAG] = prereg_binding[0]
        tags[PRE_REGISTRATION_SHA256_TAG] = prereg_binding[1]
        tags[HOLDOUT_AUTHORIZATION_DIR_TAG] = prereg_binding[2]
        tags[HOLDOUT_EXECUTOR_TAG] = prereg_binding[3]

    run = client.create_run(
        experiment_id=store.experiment_id,
        run_name=eval_id,
        tags=tags,
    )
    return _build_eval_record(store, client.get_run(run.info.run_id))


def get_eval_run(store: EvalRecordStore, eval_id: str) -> EvalRunRecord:
    """按 eval_id tag 检索父 Run 快照；不存在或组合非法则抛域异常。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, eval_id)
    return _build_eval_record(store, run)


def list_eval_fold_runs(store: EvalRecordStore, eval_id: str) -> tuple[EvalFoldRecord, ...]:
    """返回该 eval 的全部子 Run，按 fold 编号升序；观测校验与 get_eval_run 对齐。"""
    client = _client(store)
    parent = _search_parent(client, store.experiment_id, eval_id)
    record = _build_eval_record(store, parent)
    return tuple(record.folds.values())


def _find_child(
    client: MlflowClient, store: EvalRecordStore, eval_id: str, fold: int
) -> Any:
    parent = _search_parent(client, store.experiment_id, eval_id)
    children = _search_children(client, store.experiment_id, parent.info.run_id)
    for child in children:
        if _parse_fold_tag(child.data.tags.get(FOLD_TAG, "")) == fold:
            return child
    raise EvalRecordNotFound(f"未找到 fold {fold}")


def create_eval_fold_run(
    store: EvalRecordStore,
    eval_id: str,
    fold: int,
    *,
    model_artifact: str,
    data_split: str,
    sample_count: int,
    records: str,
    failures: str,
) -> EvalFoldRecord:
    """在 running 父 Run 下创建嵌套 fold 子 Run（RUNNING）。"""
    run_id = _start_eval_fold_run(
        store, eval_id, fold, model_artifact=model_artifact,
        data_split=data_split, sample_count=sample_count,
        records=records, failures=failures,
    )
    return _build_fold_record(eval_id, _client(store).get_run(run_id))


def _start_eval_fold_run(
    store: EvalRecordStore,
    eval_id: str,
    fold: int,
    *,
    model_artifact: str,
    data_split: str,
    sample_count: int,
    records: str,
    failures: str,
) -> str:
    """Return the owned child ID without a fallible post-creation read."""
    fold = _validate_fold(fold)
    model_artifact = _validate_non_empty_string(model_artifact, "model_artifact")
    data_split = _validate_non_empty_string(data_split, "data_split")
    sample_count = _validate_sample_count(sample_count)
    records = _validate_non_empty_string(records, "records")
    failures = _validate_non_empty_string(failures, "failures")

    client = _client(store)
    parent = _search_parent(client, store.experiment_id, eval_id)
    parent_record = _build_eval_record(store, parent)
    if parent_record.workflow_state != WorkflowState.RUNNING.value:
        raise IllegalEvalRecord(
            f"父 Run 状态为 {parent_record.workflow_state}，无法新建 fold"
        )

    if parent_record.scope == "full":
        raise IllegalEvalRecord("full scope 不允许 fold 绑定")

    existing = _search_children(client, store.experiment_id, parent.info.run_id)
    existing_folds: set[int] = set()
    for child in existing:
        existing_folds.add(_parse_fold_tag(child.data.tags.get(FOLD_TAG, "")))

    if fold in existing_folds:
        raise EvalRunConflict(f"fold {fold} 已存在")

    if parent_record.scope == "single_fold" and existing_folds:
        raise IllegalEvalRecord("single_fold 已存在其他 fold 绑定")

    fold_name = f"fold{fold}"
    tags = {
        FOLD_TAG: fold_name,
        "mlflow.parentRunId": parent.info.run_id,
        "mlflow.runName": fold_name,
        MODEL_ARTIFACT_TAG: model_artifact,
        DATA_SPLIT_TAG: data_split,
        SAMPLE_COUNT_TAG: str(sample_count),
        RECORDS_TAG: records,
        FAILURES_TAG: failures,
    }
    child = client.create_run(
        experiment_id=store.experiment_id,
        run_name=fold_name,
        tags=tags,
    )
    return child.info.run_id


def log_eval_fold_metrics(
    store: EvalRecordStore,
    eval_id: str,
    fold: int,
    metrics: Mapping[str, float],
) -> EvalFoldRecord:
    """指标写指定 fold 子 Run；返回最新快照。"""
    fold = _validate_fold(fold)
    metrics_f = _validate_metrics(metrics)
    client = _client(store)
    child = _find_child(client, store, eval_id, fold)
    for key, value in metrics_f.items():
        client.log_metric(child.info.run_id, key, value)
    return _build_fold_record(eval_id, client.get_run(child.info.run_id))


def end_eval_fold_run(
    store: EvalRecordStore,
    eval_id: str,
    fold: int,
    run_status: str,
    *,
    metrics: Mapping[str, float] | None = None,
) -> EvalFoldRecord:
    """终转 fold 子 Run；仅 RUNNING 可终转。"""
    fold = _validate_fold(fold)
    if run_status not in {"FINISHED", "FAILED", "KILLED"}:
        raise IllegalEvalRecord(f"非法 fold 终态: {run_status!r}")

    client = _client(store)
    child = _find_child(client, store, eval_id, fold)
    if child.info.status != "RUNNING":
        raise IllegalEvalRecord(f"fold {fold} 状态 {child.info.status} 不可终转")

    if metrics is not None:
        metrics_f = _validate_metrics(metrics)
        for key, value in metrics_f.items():
            client.log_metric(child.info.run_id, key, value)
    client.set_terminated(child.info.run_id, status=run_status)
    return _build_fold_record(eval_id, client.get_run(child.info.run_id))


def execute_eval_fold_run(
    store: EvalRecordStore,
    eval_id: str,
    fold: int,
    *,
    model_artifact: str,
    data_split: str,
    sample_count: int,
    records: str,
    failures: str,
    executor: Callable[[], Mapping[str, float]],
) -> EvalFoldRecord:
    """Record one actual evaluation invocation under an existing parent.

    This event adapter does not resolve weights or authorize data access. The
    caller must freeze and validate inputs, acquire any required holdout claim,
    and supply an executor that rejects incomplete execution and persists its
    outputs before returning metrics. Success finishes only this fold; quality
    thresholds, aggregation and the parent's outcome belong to orchestration.
    """
    parse_eval_id(eval_id)
    _validate_fold(fold)
    if not callable(executor):
        raise IllegalEvalRecord("executor must be callable")
    parent = get_eval_run(store, eval_id)
    if parent.record_validity != RecordValidity.VALID.value:
        raise InvalidEvalRecord(f"eval {eval_id} is invalid")
    # Rejected inputs and conflicts must not terminate another invocation.
    child_id = _start_eval_fold_run(
        store, eval_id, fold, model_artifact=model_artifact,
        data_split=data_split, sample_count=sample_count,
        records=records, failures=failures,
    )
    try:
        _build_fold_record(eval_id, _client(store).get_run(child_id))
        metrics = _validate_metrics(executor())
        if not all(math.isfinite(value) for value in metrics.values()):
            raise IllegalEvalRecord("executor metrics must be finite")
        return end_eval_fold_run(store, eval_id, fold, "FINISHED", metrics=metrics)
    except BaseException as exc:
        status = "KILLED" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "FAILED"
        # Attempt both records independently: a child tracking failure must not
        # prevent the parent failure from being persisted when still possible.
        try:
            current = get_eval_run(store, eval_id)
            if current.folds[fold].status == "RUNNING":
                end_eval_fold_run(store, eval_id, fold, status)
        except Exception as tracking_error:
            exc.add_note(f"Failed to persist evaluation fold failure: {tracking_error}")
        try:
            transition_eval_state(store, eval_id, "failed", run_status="FAILED")
        except Exception as tracking_error:
            exc.add_note(f"Failed to persist evaluation parent failure: {tracking_error}")
        raise


def resume_eval_fold_run(store: EvalRecordStore, eval_id: str, fold: int) -> EvalFoldRecord:
    """受控恢复：FAILED/KILLED 子 Run 经原 Run ID 恢复 RUNNING。"""
    fold = _validate_fold(fold)
    client = _client(store)
    child = _find_child(client, store, eval_id, fold)
    if child.info.status not in {"FAILED", "KILLED"}:
        raise IllegalEvalRecord(f"fold {fold} 状态 {child.info.status} 不可恢复")
    client.update_run(child.info.run_id, status="RUNNING")
    return _build_fold_record(eval_id, client.get_run(child.info.run_id))


def _check_completion_gate(
    client: MlflowClient, store: EvalRecordStore, parent_run_id: str, scope: str
) -> None:
    """completed / 结论门：scope 完整性校验。"""
    parent = client.get_run(parent_run_id)
    tags = parent.data.tags

    if SUMMARY_COMPLETE_TAG not in tags:
        raise IncompleteEvalRecord("缺少 summary_complete")

    children = _search_children(client, store.experiment_id, parent_run_id)
    child_by_fold: dict[int, Any] = {}
    for child in children:
        child_by_fold[_parse_fold_tag(child.data.tags.get(FOLD_TAG, ""))] = child

    if scope == "cross_validation":
        for fold in REQUIRED_FOLDS:
            if fold not in child_by_fold:
                raise IncompleteEvalRecord(f"缺失 fold {fold}")
            if child_by_fold[fold].info.status != "FINISHED":
                raise IncompleteEvalRecord(f"fold {fold} 未 FINISHED")
        aggregate_folds = tags.get(AGGREGATE_FOLDS_TAG)
        if aggregate_folds is None:
            raise IncompleteEvalRecord("缺少 aggregate_folds")
        expected = ",".join(f"fold{fold}" for fold in REQUIRED_FOLDS)
        if aggregate_folds != expected:
            raise IncompleteEvalRecord("aggregate_folds 与三折集合不一致")
    elif scope == "single_fold":
        if len(child_by_fold) != 1:
            raise IncompleteEvalRecord("single_fold 必须恰好有一个 fold")
        only = next(iter(child_by_fold.values()))
        if only.info.status != "FINISHED":
            raise IncompleteEvalRecord("single_fold 的 fold 未 FINISHED")
    elif scope == "full":
        if child_by_fold:
            raise IncompleteEvalRecord("full scope 不得有 fold 子 Run")


def log_eval_summary(
    store: EvalRecordStore, eval_id: str, metrics: Mapping[str, float]
) -> EvalRunRecord:
    """single/full：逐项写父 Run metrics 并置 summary_complete="true"。"""
    metrics_f = _validate_metrics(metrics)
    client = _client(store)
    run = _search_parent(client, store.experiment_id, eval_id)
    record = _build_eval_record(store, run)
    if record.workflow_state != WorkflowState.RUNNING.value:
        raise IllegalEvalRecord("父 Run 非 running，无法写入 summary")
    if record.scope == "cross_validation":
        raise IllegalEvalRecord("cross_validation 使用 log_eval_aggregate")

    for key, value in metrics_f.items():
        client.log_metric(run.info.run_id, key, value)
    client.set_tag(run.info.run_id, SUMMARY_COMPLETE_TAG, "true")
    return _build_eval_record(store, client.get_run(run.info.run_id))


def log_eval_aggregate(
    store: EvalRecordStore,
    eval_id: str,
    metrics: Mapping[str, float],
    *,
    folds: tuple[int, ...],
) -> EvalRunRecord:
    """cross_validation：聚合输入 fold 集合必须与既有子 Run fold 集合完全一致。"""
    metrics_f = _validate_metrics(metrics)
    client = _client(store)
    run = _search_parent(client, store.experiment_id, eval_id)
    record = _build_eval_record(store, run)
    if record.workflow_state != WorkflowState.RUNNING.value:
        raise IllegalEvalRecord("父 Run 非 running，无法写入 aggregate")
    if record.scope != "cross_validation":
        raise IllegalEvalRecord("aggregate 仅用于 cross_validation")

    provided = set(folds)
    if not provided:
        raise IllegalEvalRecord("聚合 fold 集合不能为空")
    if len(folds) != len(provided):
        raise IllegalEvalRecord("聚合 fold 集合含重复项")

    observed = set(record.folds.keys())
    if observed != provided:
        raise IllegalEvalRecord(
            f"聚合输入 fold 集合 {sorted(provided)} 与观测集合 {sorted(observed)} 不一致"
        )

    for key, value in metrics_f.items():
        client.log_metric(run.info.run_id, key, value)
    aggregate_value = ",".join(f"fold{fold}" for fold in sorted(folds))
    client.set_tag(run.info.run_id, AGGREGATE_FOLDS_TAG, aggregate_value)
    client.set_tag(run.info.run_id, SUMMARY_COMPLETE_TAG, "true")
    return _build_eval_record(store, client.get_run(run.info.run_id))


def _consume_holdout_for_completion(
    run: Any,
    *,
    pre_registration: Path | None,
    executor: str | None,
) -> None:
    """在 MLflow 完成状态写入前验证并发布 holdout 一次性消费标记。"""
    tags = run.data.tags
    stored_path = tags.get(PRE_REGISTRATION_PATH_TAG)
    stored_digest = tags.get(PRE_REGISTRATION_SHA256_TAG)
    authorization_value = tags.get(HOLDOUT_AUTHORIZATION_DIR_TAG)
    stored_executor = tags.get(HOLDOUT_EXECUTOR_TAG)

    if stored_path is None:
        if pre_registration is not None or executor is not None:
            raise IllegalEvalRecord("非 holdout eval 不接受 pre_registration/executor")
        return

    if pre_registration is None or executor is None:
        raise IllegalEvalRecord("holdout eval complete 必须提供 pre_registration 与 executor")
    if executor is not None and executor != stored_executor:
        raise IllegalEvalRecord("executor 与 eval 创建时冻结值不一致")

    try:
        actual_digest = hashlib.sha256(Path(pre_registration).read_bytes()).hexdigest()
    except Exception as exc:
        raise IllegalEvalRecord(f"无法复验 pre_registration: {exc}") from exc
    if actual_digest != stored_digest:
        raise IllegalEvalRecord("pre_registration 内容与 eval 创建时冻结摘要不一致")

    identity = ClaimIdentity(
        eval_version=tags[EVAL_ID_TAG],
        model_version=tags[MODEL_ID_TAG],
        data_version=tags[DATA_VERSION_TAG],
        split=tags.get(SPLIT_TAG, ""),
    )
    authorization_dir = Path(authorization_value)
    consumed_path = authorization_dir / "consumed.yaml"
    if consumed_path.exists():
        validate_claim_consumed(
            authorization_dir,
            identity,
            stored_executor,
            pre_registration_sha256=stored_digest,
        )
        return
    acquire_claim(
        authorization_dir,
        identity,
        stored_executor,
        pre_registration_sha256=stored_digest,
    )
    mark_claim_consumed(
        authorization_dir,
        identity,
        stored_executor,
        pre_registration_sha256=stored_digest,
    )


def transition_eval_state(
    store: EvalRecordStore,
    eval_id: str,
    target: WorkflowState | str,
    *,
    run_status: str | None = None,
    outcome: str | None = None,
    pre_registration: Path | None = None,
    executor: str | None = None,
) -> EvalRunRecord:
    """转换 eval 状态；completed 同时提交 holdout 消费并可恢复半提交。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, eval_id)
    requested_state = WorkflowState(target)

    raw_state = run.data.tags.get(WORKFLOW_STATE_TAG)
    raw_outcome = run.data.tags.get(OUTCOME_TAG)

    # completed 按 outcome → workflow_state → RunStatus 提交。只要 outcome
    # 已经落盘，就已跨过第一个提交点：结论必须锁定，异结论重试在任何后续
    # 写入或 holdout 消费前拒绝；同结论则从当前提交点继续恢复。
    if (
        requested_state == WorkflowState.COMPLETED
        and raw_outcome is not None
        and raw_state in {
            WorkflowState.RUNNING.value,
            WorkflowState.COMPLETED.value,
        }
        and run.info.status in {"RUNNING", "FINISHED"}
    ):
        if outcome is None or outcome not in OUTCOMES:
            raise IllegalEvalRecord(f"completed 必须显式 outcome ∈ {OUTCOMES}: {outcome!r}")
        if raw_outcome not in OUTCOMES:
            raise IllegalEvalRecord(f"父 Run outcome 非法: {raw_outcome!r}")
        if raw_outcome != outcome:
            raise IllegalEvalRecord("已提交 eval 的 outcome 不得改写")
        _validate_parent_tags(
            run,
            allow_completed_running_recovery=(
                raw_state == WorkflowState.COMPLETED.value
                and run.info.status == "RUNNING"
            ),
        )
        _check_completion_gate(
            client, store, run.info.run_id, run.data.tags[SCOPE_TAG]
        )
        _consume_holdout_for_completion(
            run,
            pre_registration=pre_registration,
            executor=executor,
        )
        if raw_state == WorkflowState.RUNNING.value:
            client.set_tag(
                run.info.run_id, WORKFLOW_STATE_TAG, WorkflowState.COMPLETED.value
            )
        if run.info.status == "RUNNING":
            client.set_terminated(run.info.run_id, status="FINISHED")
        return _build_eval_record(store, client.get_run(run.info.run_id))

    if (
        requested_state == WorkflowState.COMPLETED
        and raw_state == WorkflowState.COMPLETED.value
        and run.info.status in {"RUNNING", "FINISHED"}
    ):
        if outcome is None or outcome not in OUTCOMES:
            raise IllegalEvalRecord(f"completed 必须显式 outcome ∈ {OUTCOMES}: {outcome!r}")
        _validate_parent_tags(run, allow_completed_running_recovery=True)

        # completed 写入采用 outcome → workflow_state → RunStatus。若上次在
        # workflow_state 后中断，raw Run 会是 completed/RUNNING；若服务端已
        # 提交 FINISHED 但客户端丢失响应，则重试会看到 completed/FINISHED。
        # 两种情形都只在结论和 holdout 消费凭据完全一致时幂等恢复。
        _check_completion_gate(
            client, store, run.info.run_id, run.data.tags[SCOPE_TAG]
        )
        _consume_holdout_for_completion(
            run,
            pre_registration=pre_registration,
            executor=executor,
        )
        if raw_outcome not in (None, outcome):
            raise IllegalEvalRecord("已完成 eval 的 outcome 不得改写")
        if raw_outcome is None:
            client.set_tag(run.info.run_id, OUTCOME_TAG, outcome)
        if run.info.status == "RUNNING":
            client.set_terminated(run.info.run_id, status="FINISHED")
        return _build_eval_record(store, client.get_run(run.info.run_id))

    record = _build_eval_record(store, run)
    current_state = WorkflowState(record.workflow_state)
    target_state = transition_workflow_state(current_state, requested_state)

    if target_state == WorkflowState.COMPLETED:
        if outcome is None or outcome not in OUTCOMES:
            raise IllegalEvalRecord(f"completed 必须显式 outcome ∈ {OUTCOMES}: {outcome!r}")
    elif outcome is not None:
        raise IllegalEvalRecord("仅 completed 转换可携带 outcome")

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
        _check_completion_gate(client, store, run.info.run_id, record.scope)
        _consume_holdout_for_completion(
            run,
            pre_registration=pre_registration,
            executor=executor,
        )

    if target_state == WorkflowState.COMPLETED:
        client.set_tag(run.info.run_id, OUTCOME_TAG, outcome)
    client.set_tag(run.info.run_id, WORKFLOW_STATE_TAG, target_state.value)

    if target_state == WorkflowState.RUNNING:
        client.update_run(run.info.run_id, status=target_status)
    else:
        client.set_terminated(run.info.run_id, status=target_status)

    updated = client.get_run(run.info.run_id)
    return _build_eval_record(store, updated)


def validate_eval_for_completion(
    store: EvalRecordStore,
    eval_id: str,
    *,
    outcome: str,
) -> EvalRunRecord:
    """无副作用预检 completed 转换，供跨 MLflow/claim 提交流程使用。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, eval_id)
    record = _build_eval_record(store, run)
    transition_workflow_state(WorkflowState(record.workflow_state), WorkflowState.COMPLETED)
    if outcome not in OUTCOMES:
        raise IllegalEvalRecord(f"completed 必须显式 outcome ∈ {OUTCOMES}: {outcome!r}")
    _check_completion_gate(client, store, run.info.run_id, record.scope)
    return record


def mark_eval_invalid(store: EvalRecordStore, eval_id: str) -> EvalRunRecord:
    """父 Run record_validity 转至 invalid；不提供复活入口。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, eval_id)
    record = _build_eval_record(store, run)
    current_validity = RecordValidity(record.record_validity)
    transition_record_validity(current_validity, RecordValidity.INVALID)
    client.set_tag(run.info.run_id, RECORD_VALIDITY_TAG, RecordValidity.INVALID.value)
    return _build_eval_record(store, client.get_run(run.info.run_id))


def validate_eval_for_conclusion(store: EvalRecordStore, eval_id: str) -> EvalRunRecord:
    """§10 eval 行下游门：只校验、不实现结论消费。"""
    client = _client(store)
    run = _search_parent(client, store.experiment_id, eval_id)

    raw_validity = run.data.tags.get(RECORD_VALIDITY_TAG)
    if raw_validity == RecordValidity.INVALID.value:
        raise InvalidEvalRecord(f"eval {eval_id} 已标记为 invalid")

    record = _build_eval_record(store, run)
    if record.workflow_state not in {
        WorkflowState.COMPLETED.value,
        WorkflowState.ARCHIVED.value,
    }:
        raise IncompleteEvalRecord(
            f"workflow_state 为 {record.workflow_state}，未满足 completed/archived"
        )

    _check_completion_gate(client, store, run.info.run_id, record.scope)

    if OUTCOME_TAG not in run.data.tags:
        raise IncompleteEvalRecord("缺少 outcome")

    return record
