"""Model artifact identities, registry manifests, and current-model resolution."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

MODEL_SCHEMA_VERSION = "tensile-model-registry/model/v1"
CURRENT_SCHEMA_VERSION = "tensile-model-registry/current/v1"
MODEL_NAME_PATTERN = re.compile(
    r"^(?P<protocol>v[0-9]+\.[0-9]+)-"
    r"(?P<core>[a-z0-9]+(?:-[a-z0-9]+)*)-"
    r"(?P<scope>fold[0-9]+|full)-r(?P<round>[1-9][0-9]*)$"
)
LIFECYCLE_STATUSES = {
    "experiment",
    "evaluated",
    "accepted",
    "current",
    "rejected",
    "superseded",
    "archived",
    "missing",
}
MODEL_METADATA_NAMES = {
    "adapter_config.json",
    "all_results.json",
    "chat_template.jinja",
    "config.json",
    "eval_results.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "preprocessor_config.json",
    "processor_config.json",
    "tokenizer_config.json",
    "train_results.json",
    "trainer_state.json",
}


class ModelRegistryError(ValueError):
    """A model registry identity or artifact is invalid."""


@dataclass(frozen=True)
class ModelName:
    value: str
    protocol_version: str
    core_purpose: str
    training_scope: str
    round: int


def parse_model_name(value: str) -> ModelName:
    if not isinstance(value, str):
        raise ModelRegistryError("model_name 必须是字符串")
    match = MODEL_NAME_PATTERN.fullmatch(value)
    if match is None:
        raise ModelRegistryError(
            "model_name 必须符合 "
            "<protocol>-<core-purpose>-<foldN|full>-r<round>"
        )
    return ModelName(
        value=value,
        protocol_version=match.group("protocol"),
        core_purpose=match.group("core"),
        training_scope=match.group("scope"),
        round=int(match.group("round")),
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelRegistryError(f"无法读取模型注册表 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ModelRegistryError(f"模型注册表必须是对象: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_identity(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_dir():
        raise ModelRegistryError(f"模型目录不存在: {path}")
    selected = [
        child
        for child in sorted(path.iterdir())
        if child.is_file()
        and (
            child.name in MODEL_METADATA_NAMES
            or child.suffix == ".safetensors"
        )
    ]
    if not selected or not any(
        child.suffix == ".safetensors" for child in selected
    ):
        raise ModelRegistryError(f"模型目录缺少 safetensors: {path}")
    files = {
        child.name: {
            "size_bytes": child.stat().st_size,
            "sha256": _sha256(child),
        }
        for child in selected
    }
    aggregate = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "path": str(path.resolve()),
        "files": files,
        "aggregate_sha256": aggregate,
    }


def _validate_artifact(
    name: str,
    value: Any,
    *,
    project_root: Path | None,
    require_artifacts: bool,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelRegistryError(f"artifacts.{name} 必须是对象")
    managed_path = value.get("managed_path")
    frozen_path = value.get("path_at_freeze")
    aggregate = value.get("aggregate_sha256")
    if (
        not isinstance(managed_path, str)
        or not managed_path.startswith("workspace/models/")
    ):
        raise ModelRegistryError(
            f"artifacts.{name}.managed_path 必须位于 workspace/models/"
        )
    if not isinstance(frozen_path, str) or not Path(frozen_path).is_absolute():
        raise ModelRegistryError(
            f"artifacts.{name}.path_at_freeze 必须是绝对路径"
        )
    if (
        not isinstance(aggregate, str)
        or re.fullmatch(r"[0-9a-f]{64}", aggregate) is None
    ):
        raise ModelRegistryError(
            f"artifacts.{name}.aggregate_sha256 必须是 SHA-256"
        )
    if require_artifacts:
        if project_root is None:
            raise ModelRegistryError("校验物理模型时必须提供 project_root")
        path = (Path(project_root).resolve() / managed_path).resolve()
        workspace = (Path(project_root).resolve() / "workspace/models").resolve()
        if path != workspace and workspace not in path.parents:
            raise ModelRegistryError(f"受管路径逃逸 workspace/models: {path}")
        if not path.is_dir():
            raise ModelRegistryError(f"受管模型目录不存在: {path}")
    return dict(value)


def validate_model_manifest(
    value: Mapping[str, Any],
    *,
    project_root: Path | None = None,
    require_artifacts: bool = False,
) -> dict[str, Any]:
    if value.get("schema_version") != MODEL_SCHEMA_VERSION:
        raise ModelRegistryError(
            f"schema_version 必须是 {MODEL_SCHEMA_VERSION}"
        )
    parsed = parse_model_name(value.get("model_name"))
    expected = {
        "protocol_version": parsed.protocol_version,
        "core_purpose": parsed.core_purpose,
        "training_scope": parsed.training_scope,
        "round": parsed.round,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise ModelRegistryError(
                f"{field} 与 model_name 不一致: "
                f"expected={expected_value!r}, actual={value.get(field)!r}"
            )
    status = value.get("lifecycle_status")
    if status not in LIFECYCLE_STATUSES:
        raise ModelRegistryError(f"非法 lifecycle_status: {status!r}")
    contract = value.get("contract")
    if (
        not isinstance(contract, Mapping)
        or contract.get("version") != "tensile-vlm/v4.1"
        or re.fullmatch(r"[0-9a-f]{64}", str(contract.get("sha256") or ""))
        is None
    ):
        raise ModelRegistryError("contract 身份非法")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != {
        "adapter",
        "merged",
    }:
        raise ModelRegistryError("artifacts 必须且只能包含 adapter、merged")
    normalized = dict(value)
    normalized["artifacts"] = {
        name: _validate_artifact(
            name,
            artifacts[name],
            project_root=project_root,
            require_artifacts=require_artifacts,
        )
        for name in ("adapter", "merged")
    }
    return normalized


def load_model_manifest(
    path: Path,
    *,
    project_root: Path | None = None,
    require_artifacts: bool = False,
) -> dict[str, Any]:
    return validate_model_manifest(
        _read_json(path),
        project_root=project_root,
        require_artifacts=require_artifacts,
    )


def load_current_model(
    project_root: Path,
    *,
    require_artifacts: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_root = Path(project_root).resolve()
    registry_root = project_root / "pipeline/model_registry"
    current = _read_json(registry_root / "current.json")
    if current.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise ModelRegistryError(
            f"current schema_version 必须是 {CURRENT_SCHEMA_VERSION}"
        )
    model_name = current.get("model_name")
    parse_model_name(model_name)
    manifest_path = registry_root / "releases" / f"{model_name}.json"
    manifest = load_model_manifest(
        manifest_path,
        project_root=project_root,
        require_artifacts=require_artifacts,
    )
    if manifest["model_name"] != model_name:
        raise ModelRegistryError("current 与 release manifest 模型身份不一致")
    if manifest["lifecycle_status"] != "current":
        raise ModelRegistryError("current 模型 lifecycle_status 必须是 current")
    if current.get("manifest_path") != str(
        manifest_path.relative_to(project_root)
    ):
        raise ModelRegistryError("current manifest_path 不一致")
    if current.get("aggregate_sha256") != manifest["artifacts"]["merged"][
        "aggregate_sha256"
    ]:
        raise ModelRegistryError("current merged aggregate hash 不一致")
    return current, manifest


def resolve_current_artifact(project_root: Path, artifact: str = "merged") -> Path:
    if artifact not in {"adapter", "merged"}:
        raise ModelRegistryError(f"不支持的模型 artifact: {artifact}")
    _, manifest = load_current_model(project_root, require_artifacts=True)
    return (
        Path(project_root).resolve()
        / manifest["artifacts"][artifact]["managed_path"]
    ).resolve()


def verify_current_artifacts(project_root: Path) -> dict[str, Any]:
    current, manifest = load_current_model(
        project_root,
        require_artifacts=True,
    )
    identities = {}
    for name in ("adapter", "merged"):
        path = (
            Path(project_root).resolve()
            / manifest["artifacts"][name]["managed_path"]
        )
        identity = artifact_identity(path)
        expected = manifest["artifacts"][name]["aggregate_sha256"]
        if identity["aggregate_sha256"] != expected:
            raise ModelRegistryError(
                f"{name} aggregate hash 不一致: "
                f"expected={expected}, actual={identity['aggregate_sha256']}"
            )
        identities[name] = identity
    return {
        "schema_version": "tensile-model-registry/verification/v1",
        "model_name": current["model_name"],
        "artifacts": identities,
        "passed": True,
    }


def _service_files(path: Path) -> dict[str, str]:
    """Fingerprint a concrete directory; reject links instead of following them."""
    if not path.is_absolute() or not path.is_dir() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ModelRegistryError("service artifact must be a concrete absolute directory")
    files = {}
    for file in sorted(path.rglob("*")):
        if file.is_symlink():
            raise ModelRegistryError("service artifact contains a symlink")
        if file.is_file():
            files[file.relative_to(path).as_posix()] = _sha256(file)
    if not files:
        raise ModelRegistryError("service artifact is empty")
    return files


def _service_prompt(root: Path, store: Any, record: Any) -> dict[str, Any]:
    """Compare the inputs already checked by the training/evaluation gates.

    The current definition is checked for drift; it is not the source of the
    service input. Ordinary artifact paths and their digests are validated by
    validate_service_current before and after this snapshot.
    """
    import yaml
    from dataclasses import asdict
    from versioning.prompts import load_prompt, parse_prompt_definition, prompt_path
    from versioning.registry import _run_artifact_root, _eval_store
    from versioning.mlflow_eval import get_eval_run

    training = _run_artifact_root(store, record.run_id) / "input/prompt.yaml"
    frozen = parse_prompt_definition(yaml.safe_load(training.read_text()))
    current_path = prompt_path(root, record.prompt_version)
    if any(path.is_symlink() for path in (current_path, *current_path.parents)):
        raise ModelRegistryError("service Prompt must be an ordinary file")
    if frozen.version != record.prompt_version or load_prompt(root, record.prompt_version) != frozen:
        raise ModelRegistryError("current Prompt differs from frozen training Prompt")
    evaluation = get_eval_run(_eval_store(store), record.eval_id)
    evaluated = json.loads((_run_artifact_root(store, evaluation.run_id) / "input/evaluation.yaml").read_bytes())
    prompt = {**asdict(frozen), "output_fields": list(frozen.output_fields)}
    if evaluated.get("prompt") != {key: prompt[key] for key in ("version", "system_prompt", "user_prompt", "output_fields")}:
        raise ModelRegistryError("evaluated Prompt differs from frozen training Prompt")
    return prompt


def _service_prompt_digest(prompt: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(prompt, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def bind_service_contract(contract: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Derive analysis inputs from a verified model binding, retaining output policy."""
    from copy import deepcopy
    from versioning.ids import parse_model_id
    from versioning.prompts import parse_prompt_definition
    from pipeline.production_contract import canonical_contract_bytes

    prompt = binding["prompt"]
    parsed = parse_prompt_definition(prompt)
    if (parsed.version != binding["prompt_version"]
        or _service_prompt_digest(prompt) != binding["prompt_sha256"]
        or contract["contract_version"] != "tensile-vlm/" + parse_model_id(binding["model_version"]).protocol
        or list(parsed.output_fields) != contract["model_output_fields"]):
        raise ModelRegistryError("service Prompt binding or output contract differs")
    result = deepcopy(contract)
    result["analysis"].update(system_prompt=parsed.system_prompt, user_prompt=parsed.user_prompt)
    result["contract_hash"] = hashlib.sha256(canonical_contract_bytes(result)).hexdigest()
    return result


def resolve_service_model(root: Path, *, alias: str, service_mode: str) -> dict[str, Any]:
    """Resolve the actual service exclusively through the qualified Registry.

    Legacy manifest/current functions in this module remain historical readers.
    This entry neither scans for models nor materializes or repairs a cache.
    """
    import tempfile
    from mlflow.tracking import MlflowClient
    from versioning.materialize import validate_service_current, _validate_route
    from versioning.registry import open_registry_store
    _validate_route(service_mode, alias)
    root = Path(root).absolute()
    store = open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    record = validate_service_current(store, alias=alias, service_mode=service_mode,
        models_root=root / "workspace/models", records_root=root)
    prompt = _service_prompt(root, store, record)
    target = root / "workspace/models/materialized" / record.model_id
    client = MlflowClient(tracking_uri=store.tracking_uri)
    inventory = {}
    with tempfile.TemporaryDirectory(prefix="service-artifacts-") as temp:
        for entries in record.artifacts.values():
            for declared in entries.values():
                cached = _service_files(target / declared)
                source = Path(client.download_artifacts(record.run_id, declared.removeprefix("artifacts/"), str(Path(temp).resolve())))
                if cached != _service_files(source):
                    raise ModelRegistryError("materialized artifact content differs from the registered source")
                inventory[declared] = cached
    selected = [(kind, path) for entries in record.artifacts.values() for kind, path in entries.items()
                if path == record.deploy_target]
    if len(selected) != 1 or selected[0][0] not in {"adapter", "merged"}:
        raise ModelRegistryError("service requires one explicit adapter or merged deployment target")
    kind, declared = selected[0]
    adapter = target / declared if kind == "adapter" else None
    model_path = Path(record.base_model) if adapter else target / declared
    inventory["base_model"] = _service_files(model_path)
    # Detect Registry/current changes during content verification.
    if validate_service_current(store, alias=alias, service_mode=service_mode,
        models_root=root / "workspace/models", records_root=root) != record:
        raise ModelRegistryError("service Registry binding changed during validation")
    if _service_prompt(root, store, record) != prompt:
        raise ModelRegistryError("service Prompt changed during validation")
    identity = {"model_version": record.model_id, "model_version_number": record.version,
        "alias": alias, "service_mode": service_mode, "train_version": record.train_id,
        "eval_version": record.eval_id, "data_version": record.data_version,
        "prompt_version": record.prompt_version, "base_model_version": record.base_model,
        "deploy_target": declared, "prompt": prompt, "prompt_sha256": _service_prompt_digest(prompt)}
    digest = hashlib.sha256(json.dumps({"identity": identity, "files": inventory},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**identity, "fingerprint": digest, "model_path": str(model_path),
            "adapter_path": str(adapter) if adapter else None}
