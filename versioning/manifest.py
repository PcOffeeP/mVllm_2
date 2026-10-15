"""B7b — 四段聚合 manifest：data/prompt/train/eval 单向导出证据文件与发布门。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from versioning.data_release import (
    ImmutableReleaseError,
    ReleaseNotFound,
    ReleaseSchemaError,
    assert_payload_sealed,
    load_release_metadata,
)
from versioning.ids import (
    InvalidIdentifier,
    parse_data_id,
    parse_eval_id,
    parse_model_id,
    parse_prompt_id,
    parse_train_id,
)
from versioning.mlflow_train import (
    IllegalTrainRecord,
    IncompleteTrainRecord,
    InvalidTrainRecord,
    TrainRecordNotFound,
    TrainRecordStore,
    get_train_run,
)
from versioning.state import StateMachineError
from versioning.prompts import PromptNotFound, PromptSchemaError, load_prompt
from versioning.registry import ModelRegistryStore, RegisteredModelRecord, get_model

MANIFEST_VERSION: str = "1"

_ALLOWED_DATA_STATUS = {"active", "superseded"}
_ALLOWED_TRAIN_STATE = {"completed", "archived"}
_ALLOWED_EVAL_SCOPE = {"single_fold", "cross_validation", "full"}
_ALLOWED_EVAL_OUTCOME = {"passed", "failed"}
_REQUIRED_FOLDS = {0, 1, 2}


class ManifestError(ValueError):
    """manifest 域异常基类。"""


class ManifestReferenceError(ManifestError):
    """引用门失败：记录不存在、未封存、未完成、链路不一致或 eval 视图非法。"""


class ManifestSchemaError(ManifestError):
    """校验函数拒绝：schema、字段、值域或跨段一致性非法。"""


class ManifestConflict(ManifestError):
    """export_manifest 目标已存在且字节不同于本次 payload。"""


def _publish_immutable(target: Path, payload: bytes, *, label: str) -> Path:
    """以排他硬链接发布不可变文件；并发同内容幂等、异内容冲突。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with temp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, target)
        except FileExistsError:
            try:
                existing = target.read_bytes()
            except Exception as exc:
                raise ManifestConflict(f"目标 {target} 已存在但无法读取: {exc}") from exc
            if existing != payload:
                raise ManifestConflict(f"目标 {target} 已存在且{label}内容不同")
        return target
    finally:
        temp.unlink(missing_ok=True)


_MODEL_MANIFEST_KEYS = {
    "version", "protocol", "state", "record_validity", "registered_model",
    "mlflow_model_version", "source_run_id", "source_training", "source_scope",
    "base_model", "data_version", "prompt_version", "artifacts", "deploy_target",
}


@dataclass(frozen=True)
class DataRecordRef:
    """已冻结 data release 引用。"""

    root: Path
    version: str


@dataclass(frozen=True)
class PromptRecordRef:
    """已冻结 prompt 文件引用。"""

    root: Path
    version: str


@dataclass(frozen=True)
class TrainRecordRef:
    """已冻结训练记录引用。"""

    store: TrainRecordStore
    train_id: str


@dataclass(frozen=True)
class EvalRecordRef:
    """已冻结 eval 视图值对象。"""

    eval_id: str
    model_version: str
    source_train: str
    data_version: str
    scope: str
    folds: tuple[int, ...]
    outcome: str
    result_refs: Mapping[str, str]
    record_validity: str


def _parse_all_ids(
    data: DataRecordRef,
    prompt: PromptRecordRef,
    train: TrainRecordRef,
    eval_ref: EvalRecordRef,
) -> None:
    """七处 ID 字段全部先行解析，非法时直接传播 InvalidIdentifier。"""
    parse_data_id(data.version)
    parse_prompt_id(prompt.version)
    parse_train_id(train.train_id)
    parse_eval_id(eval_ref.eval_id)
    parse_model_id(eval_ref.model_version)
    parse_train_id(eval_ref.source_train)
    parse_data_id(eval_ref.data_version)


def _data_gate(data: DataRecordRef) -> tuple[Any, Path]:
    """data release 存在性、训练链语义与封存只读门。"""
    try:
        meta = load_release_metadata(data.root, data.version)
    except (ReleaseNotFound, ReleaseSchemaError, ImmutableReleaseError) as exc:
        raise ManifestReferenceError(f"data 引用非法: {exc}") from exc

    if meta.purpose != "development":
        raise ManifestReferenceError(
            f"data purpose 必须为 development，得到 {meta.purpose!r}"
        )
    if meta.training_allowed is not True:
        raise ManifestReferenceError("data training_allowed 必须为真")
    if meta.status.value not in _ALLOWED_DATA_STATUS:
        raise ManifestReferenceError(
            f"data status 不合法: {meta.status.value!r}"
        )

    release_dir = data.root / "releases" / data.version
    try:
        assert_payload_sealed(release_dir)
    except ImmutableReleaseError as exc:
        raise ManifestReferenceError(f"data payload 未封存: {exc}") from exc

    return meta, release_dir


def _prompt_gate(prompt: PromptRecordRef) -> Any:
    """prompt 存在性与 schema 门。"""
    try:
        return load_prompt(prompt.root, prompt.version)
    except (PromptNotFound, PromptSchemaError) as exc:
        raise ManifestReferenceError(f"prompt 引用非法: {exc}") from exc


def _train_gate(train: TrainRecordRef) -> Any:
    """train 存在性、有效性与完成门。"""
    try:
        record = get_train_run(train.store, train.train_id)
    except (
        TrainRecordNotFound,
        IncompleteTrainRecord,
        InvalidTrainRecord,
        IllegalTrainRecord,
        StateMachineError,
        KeyError,
        ValueError,
    ) as exc:
        raise ManifestReferenceError(f"train 引用非法: {exc}") from exc

    if record.record_validity != "valid":
        raise ManifestReferenceError(
            f"train record_validity 必须为 valid，得到 {record.record_validity!r}"
        )
    if record.workflow_state not in _ALLOWED_TRAIN_STATE:
        raise ManifestReferenceError(
            f"train workflow_state 不合法: {record.workflow_state!r}"
        )
    return record


def _validate_eval_view(eval_ref: EvalRecordRef, train_id: str) -> None:
    """eval 冻结视图值域与链路一致性。"""
    if eval_ref.record_validity != "valid":
        raise ManifestReferenceError(
            f"eval record_validity 必须为 valid，得到 {eval_ref.record_validity!r}"
        )
    if eval_ref.scope not in _ALLOWED_EVAL_SCOPE:
        raise ManifestReferenceError(f"eval scope 不合法: {eval_ref.scope!r}")

    if not isinstance(eval_ref.folds, (tuple, list)):
        raise ManifestReferenceError("eval folds 必须是序列")

    seen: set[int] = set()
    fold_values: list[int] = []
    for fold in eval_ref.folds:
        if isinstance(fold, bool) or not isinstance(fold, int):
            raise ManifestReferenceError(f"eval fold 必须为整数: {fold!r}")
        if fold not in _REQUIRED_FOLDS:
            raise ManifestReferenceError(f"eval fold 越界: {fold!r}")
        if fold in seen:
            raise ManifestReferenceError(f"eval fold 重复: {fold!r}")
        seen.add(fold)
        fold_values.append(fold)

    if eval_ref.scope == "cross_validation" and set(fold_values) != _REQUIRED_FOLDS:
        raise ManifestReferenceError(
            "cross_validation 必须覆盖全部三折"
        )
    if eval_ref.scope == "single_fold" and len(fold_values) != 1:
        raise ManifestReferenceError(
            "single_fold 必须恰有一个 fold"
        )
    if eval_ref.scope == "full" and fold_values:
        raise ManifestReferenceError("full 模式下 folds 必须为空")

    if eval_ref.outcome not in _ALLOWED_EVAL_OUTCOME:
        raise ManifestReferenceError(f"eval outcome 不合法: {eval_ref.outcome!r}")

    if not isinstance(eval_ref.result_refs, Mapping) or not eval_ref.result_refs:
        raise ManifestReferenceError("eval result_refs 必须为非空映射")
    for key, value in eval_ref.result_refs.items():
        if not isinstance(key, str) or not key:
            raise ManifestReferenceError("eval result_refs 键必须为非空字符串")
        if not isinstance(value, str) or not value:
            raise ManifestReferenceError("eval result_refs 值必须为非空字符串")

    if eval_ref.source_train != train_id:
        raise ManifestReferenceError(
            f"eval source_train {eval_ref.source_train!r} 与 train {train_id!r} 不一致"
        )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def build_manifest(
    *,
    data: DataRecordRef,
    prompt: PromptRecordRef,
    train: TrainRecordRef,
    eval: EvalRecordRef,
) -> str:
    """四段聚合并确定性序列化为 canonical JSON 文本。"""
    _parse_all_ids(data, prompt, train, eval)

    meta, release_dir = _data_gate(data)
    prompt_def = _prompt_gate(prompt)
    train_record = _train_gate(train)

    if train_record.data_version != data.version:
        raise ManifestReferenceError(
            f"train data_version {train_record.data_version!r} 与 data {data.version!r} 不一致"
        )
    if train_record.prompt_version != prompt.version:
        raise ManifestReferenceError(
            f"train prompt_version {train_record.prompt_version!r} 与 prompt {prompt.version!r} 不一致"
        )

    _validate_eval_view(eval, train_record.train_id)

    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "data": {
            "version": meta.version,
            "source_batches": list(meta.source_batches),
            "release_digest": _sha256_file(release_dir / "release.yaml"),
            "seal_evidence": "release.yaml",
        },
        "prompt": {
            "version": prompt_def.version,
            "source_hash": _sha256_file(prompt.root / "records" / "prompts" / f"{prompt.version}.yaml"),
            "variables": list(prompt_def.output_fields),
        },
        "train": {
            "train_id": train_record.train_id,
            "folds": sorted(train_record.folds.keys()),
            "state": train_record.workflow_state,
            "run_id": train_record.run_id,
        },
        "eval": {
            "eval_id": eval.eval_id,
            "model_version": eval.model_version,
            "source_train": eval.source_train,
            "data_version": eval.data_version,
            "scope": eval.scope,
            "folds": sorted(eval.folds),
            "outcome": eval.outcome,
            "result_refs": dict(eval.result_refs),
        },
    }

    return _canonical_json(manifest)


def _require_dict(value: Any, message: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise ManifestSchemaError(message)
    return value


def _is_lowercase_hex(value: str, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    return re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value) is not None


def _validate_folds_sequence(folds: Any, scope: str, context: str) -> list[int]:
    if not isinstance(folds, list):
        raise ManifestSchemaError(f"{context}.folds 必须是列表")

    seen: set[int] = set()
    result: list[int] = []
    for item in folds:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ManifestSchemaError(f"{context}.folds 元素必须为整数")
        if item not in _REQUIRED_FOLDS:
            raise ManifestSchemaError(f"{context}.folds 元素越界: {item}")
        if item in seen:
            raise ManifestSchemaError(f"{context}.folds 元素重复: {item}")
        seen.add(item)
        result.append(item)

    if result != sorted(result):
        raise ManifestSchemaError(f"{context}.folds 必须升序")

    if scope == "cross_validation" and set(result) != _REQUIRED_FOLDS:
        raise ManifestSchemaError(
            f"{context}.folds 与 cross_validation 不匹配"
        )
    if scope == "single_fold" and len(result) != 1:
        raise ManifestSchemaError(
            f"{context}.folds 与 single_fold 不匹配"
        )
    if scope == "full" and result:
        raise ManifestSchemaError(
            f"{context}.folds 与 full 不匹配"
        )

    return result


def validate_manifest(payload: str) -> dict[str, Any]:
    """严格校验 manifest JSON 文本；通过则返回解析后的 mapping。"""
    if not isinstance(payload, str):
        raise ManifestSchemaError("payload 必须是字符串")

    try:
        obj = json.loads(payload)
    except Exception as exc:
        raise ManifestSchemaError(f"非法 JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ManifestSchemaError("payload 顶层必须是对象")

    if set(obj) != {"manifest_version", "data", "prompt", "train", "eval"}:
        raise ManifestSchemaError("顶层键集合非法")

    if obj.get("manifest_version") != "1":
        raise ManifestSchemaError("manifest_version 必须为 '1'")

    data = _require_dict(obj.get("data"), "data 段必须是对象")
    prompt = _require_dict(obj.get("prompt"), "prompt 段必须是对象")
    train = _require_dict(obj.get("train"), "train 段必须是对象")
    eval_seg = _require_dict(obj.get("eval"), "eval 段必须是对象")

    if set(data) != {"version", "source_batches", "release_digest", "seal_evidence"}:
        raise ManifestSchemaError("data 段键集合非法")
    if set(prompt) != {"version", "source_hash", "variables"}:
        raise ManifestSchemaError("prompt 段键集合非法")
    if set(train) != {"train_id", "folds", "state", "run_id"}:
        raise ManifestSchemaError("train 段键集合非法")
    if set(eval_seg) != {
        "eval_id",
        "model_version",
        "source_train",
        "data_version",
        "scope",
        "folds",
        "outcome",
        "result_refs",
    }:
        raise ManifestSchemaError("eval 段键集合非法")

    # ID 值域
    id_checks = [
        (data.get("version"), parse_data_id, "data.version"),
        (prompt.get("version"), parse_prompt_id, "prompt.version"),
        (train.get("train_id"), parse_train_id, "train.train_id"),
        (eval_seg.get("eval_id"), parse_eval_id, "eval.eval_id"),
        (eval_seg.get("model_version"), parse_model_id, "eval.model_version"),
        (eval_seg.get("source_train"), parse_train_id, "eval.source_train"),
        (eval_seg.get("data_version"), parse_data_id, "eval.data_version"),
    ]
    for raw_value, parser, label in id_checks:
        try:
            parser(raw_value)
        except InvalidIdentifier as exc:
            raise ManifestSchemaError(f"{label} 非法: {exc}") from exc

    # data 段值域
    source_batches = data.get("source_batches")
    if not isinstance(source_batches, list) or not source_batches:
        raise ManifestSchemaError("data.source_batches 必须为非空列表")
    for batch in source_batches:
        if not isinstance(batch, str) or not batch:
            raise ManifestSchemaError("data.source_batches 元素必须为非空字符串")

    if not _is_lowercase_hex(data.get("release_digest"), 64):
        raise ManifestSchemaError("data.release_digest 必须是 64 位小写十六进制")
    if data.get("seal_evidence") != "release.yaml":
        raise ManifestSchemaError("data.seal_evidence 必须为 'release.yaml'")

    # prompt 段值域
    if not _is_lowercase_hex(prompt.get("source_hash"), 64):
        raise ManifestSchemaError("prompt.source_hash 必须是 64 位小写十六进制")

    variables = prompt.get("variables")
    if not isinstance(variables, list) or not variables:
        raise ManifestSchemaError("prompt.variables 必须为非空列表")
    seen_vars: set[str] = set()
    for variable in variables:
        if not isinstance(variable, str) or not variable:
            raise ManifestSchemaError("prompt.variables 元素必须为非空字符串")
        if variable in seen_vars:
            raise ManifestSchemaError(f"prompt.variables 重复: {variable}")
        seen_vars.add(variable)

    # train 段值域
    train_folds = train.get("folds")
    if not isinstance(train_folds, list) or train_folds != [0, 1, 2]:
        raise ManifestSchemaError("train.folds 必须为 [0, 1, 2]")
    if train.get("state") not in _ALLOWED_TRAIN_STATE:
        raise ManifestSchemaError("train.state 不合法")
    run_id = train.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ManifestSchemaError("train.run_id 必须为非空字符串")

    # eval 段值域
    eval_scope = eval_seg.get("scope")
    if eval_scope not in _ALLOWED_EVAL_SCOPE:
        raise ManifestSchemaError("eval.scope 不合法")
    _validate_folds_sequence(eval_seg.get("folds"), eval_scope, "eval")

    if eval_seg.get("outcome") not in _ALLOWED_EVAL_OUTCOME:
        raise ManifestSchemaError("eval.outcome 不合法")

    result_refs = eval_seg.get("result_refs")
    if not isinstance(result_refs, dict) or not result_refs:
        raise ManifestSchemaError("eval.result_refs 必须为非空对象")
    for key, value in result_refs.items():
        if not isinstance(key, str) or not key:
            raise ManifestSchemaError("eval.result_refs 键必须为非空字符串")
        if not isinstance(value, str) or not value:
            raise ManifestSchemaError("eval.result_refs 值必须为非空字符串")

    # 跨段一致性
    if eval_seg.get("source_train") != train.get("train_id"):
        raise ManifestSchemaError("eval.source_train 与 train.train_id 不一致")

    return obj


def export_manifest(
    target: Path,
    *,
    data: DataRecordRef,
    prompt: PromptRecordRef,
    train: TrainRecordRef,
    eval: EvalRecordRef,
) -> Path:
    """单向导出落盘：幂等重导或冲突拒绝，不反向修改任何源对象。"""
    payload = build_manifest(data=data, prompt=prompt, train=train, eval=eval)
    payload_bytes = payload.encode("utf-8")

    return _publish_immutable(target, payload_bytes, label="内容与本次 manifest ")


def _model_manifest_mapping(record: RegisteredModelRecord) -> dict[str, Any]:
    """从 Registry 权威快照构造确定性 model manifest。"""
    protocol = parse_model_id(record.model_id).protocol
    return {
        "version": record.model_id,
        "protocol": f"tensile-vlm/{protocol.removeprefix('v')}",
        "state": "sealed",
        "record_validity": record.record_validity,
        "registered_model": record.registered_model,
        "mlflow_model_version": record.version,
        "source_run_id": record.run_id,
        "source_training": record.train_id,
        "source_scope": record.source_scope,
        "base_model": record.base_model,
        "data_version": record.data_version,
        "prompt_version": record.prompt_version,
        "artifacts": record.artifacts,
        "deploy_target": record.deploy_target,
        **({"source_kind": record.source_kind, "source_evidence": record.source_evidence}
           if getattr(record, "source_kind", "trained") == "base" or getattr(record, "source_evidence", None) else {}),
    }


def validate_model_manifest(payload: str) -> dict[str, Any]:
    """严格校验 model manifest 的 schema、值域和部署目标唯一性。"""
    if not isinstance(payload, str):
        raise ManifestSchemaError("model manifest payload 必须是字符串")
    try:
        obj = yaml.safe_load(payload)
    except Exception as exc:
        raise ManifestSchemaError(f"model manifest YAML 非法: {exc}") from exc
    if not isinstance(obj, dict) or set(obj) not in (_MODEL_MANIFEST_KEYS, _MODEL_MANIFEST_KEYS | {"source_kind", "source_evidence"}):
        raise ManifestSchemaError("model manifest 顶层键集合非法")
    source_kind = obj.get("source_kind", "trained")
    if source_kind not in {"base", "trained"}:
        raise ManifestSchemaError("source_kind 必须是 base 或 trained")
    if "source_evidence" in obj and (not isinstance(obj["source_evidence"], dict) or not obj["source_evidence"]):
        raise ManifestSchemaError("source_evidence 必须是非空 mapping")
    if source_kind == "base" and (obj["source_scope"] != "base" or any(obj[key] is not None for key in ("source_training", "data_version", "prompt_version"))):
        raise ManifestSchemaError("base source must not invent training/data/Prompt references")
    if source_kind == "trained" and obj["source_scope"] == "base":
        raise ManifestSchemaError("trained source cannot claim base scope")
    try:
        parsed = parse_model_id(obj["version"])
        if source_kind == "trained":
            parse_train_id(obj["source_training"])
            parse_data_id(obj["data_version"])
            parse_prompt_id(obj["prompt_version"])
    except (InvalidIdentifier, KeyError) as exc:
        raise ManifestSchemaError(f"model manifest 身份非法: {exc}") from exc
    if obj["protocol"] != f"tensile-vlm/{parsed.protocol.removeprefix('v')}":
        raise ManifestSchemaError("model manifest protocol 与 version 不一致")
    if obj["state"] != "sealed" or obj["record_validity"] not in {"valid", "invalid"}:
        raise ManifestSchemaError("model manifest state/record_validity 非法")
    if obj["registered_model"] != "mVllm2":
        raise ManifestSchemaError("model manifest registered_model 非法")
    if isinstance(obj["mlflow_model_version"], bool) or not isinstance(obj["mlflow_model_version"], int) or obj["mlflow_model_version"] < 1:
        raise ManifestSchemaError("mlflow_model_version 必须是正整数")
    for key in ("source_run_id", "base_model"):
        if not isinstance(obj[key], str) or not obj[key]:
            raise ManifestSchemaError(f"{key} 必须是非空字符串")
    scope = obj["source_scope"]
    artifacts = obj["artifacts"]
    if scope not in {*_ALLOWED_EVAL_SCOPE, "base", "diagnostic_fold"} or not isinstance(artifacts, dict):
        raise ManifestSchemaError("source_scope/artifacts 非法")
    if scope == "diagnostic_fold":
        fold = obj.get("source_evidence", {}).get("fold")
        if type(fold) is not int or fold not in (0, 1, 2):
            raise ManifestSchemaError("diagnostic source requires actual fold evidence")
        expected = {f"fold{fold}"}
    else:
        expected = {"single_fold": {"fold0"}, "cross_validation": {"fold0", "fold1", "fold2"}, "full": {"full"}, "base": {"base"}}[scope]
    if set(artifacts) != expected:
        raise ManifestSchemaError("artifacts 与 source_scope 不一致")
    paths: set[str] = set()
    for name, entries in artifacts.items():
        if not isinstance(entries, dict) or not entries:
            raise ManifestSchemaError(f"artifacts.{name} 必须是非空 mapping")
        for path in entries.values():
            parts = Path(path).parts if isinstance(path, str) else ()
            if (
                not isinstance(path, str)
                or not path
                or Path(path).is_absolute()
                or ".." in parts
                or "." in parts
                or len(parts) < 3
                or parts[0] != "artifacts"
                or parts[1] != name
            ):
                raise ManifestSchemaError("artifact 路径必须是安全相对路径")
            paths.add(path)
    deploy_target = obj["deploy_target"]
    if scope in {"cross_validation", "base", "diagnostic_fold"}:
        if deploy_target is not None:
            raise ManifestSchemaError("non-serving model source deploy_target 必须为 null")
    elif not isinstance(deploy_target, str) or deploy_target not in paths:
        raise ManifestSchemaError("deploy_target 必须唯一引用 artifacts 路径")
    return obj


def build_model_manifest(store: ModelRegistryStore, model_id: str) -> str:
    """从真实 Registry Model Version 单向构造 model manifest YAML。"""
    from versioning.registry import _run_model_train_gate, _run_eval_gate, PromotionGateRejected
    record = get_model(store, model_id)
    _run_model_train_gate(store, record)
    if record.eval_id is not None:
        evaluated = _run_eval_gate(store, record.eval_id, require_passed=True)
        if evaluated.model_id != record.model_id or evaluated.model_version_number != record.version:
            raise PromotionGateRejected("model manifest evaluation binding differs")
    obj = _model_manifest_mapping(record)
    payload = yaml.safe_dump(obj, sort_keys=True, allow_unicode=True)
    validate_model_manifest(payload)
    return payload


def export_model_manifest(
    target: Path, *, store: ModelRegistryStore, model_id: str
) -> Path:
    """幂等导出 model manifest；既有内容不同则拒绝覆盖。"""
    payload = build_model_manifest(store, model_id).encode("utf-8")
    return _publish_immutable(target, payload, label="model manifest ")
