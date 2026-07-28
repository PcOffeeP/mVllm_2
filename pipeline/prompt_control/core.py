"""Validation, publication, and runtime binding for immutable prompts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = Path(__file__).with_name("prompt_control.schema.json")
DEFAULT_REGISTRY_ROOT = ROOT / "pipeline" / "prompt_registry"
DEFAULT_CONTRACT_PATH = ROOT / "pipeline" / "contracts" / "tensile_vlm_v4_1.json"
PROMPT_SCHEMA_VERSION = "tensile-prompt-control/v1"
EXPERIMENT_SCHEMA_VERSION = "tensile-vlm-v4.1-experiment-contract/v1"
MODEL_BUNDLE_SCHEMA_VERSION = "tensile-vlm-v4.1-model-bundle/v1"
OUTPUT_FIELDS = [
    "clip_state",
    "fracture_mechanism",
    "fracture_site",
    "special_case",
]


class PromptControlError(ValueError):
    """Prompt identity, schema, or immutable artifact is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _pretty_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromptControlError(f"无法读取 {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PromptControlError(f"{label} 必须是对象: {path}")
    return value


def _read_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PromptControlError(f"无法读取 {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PromptControlError(f"{label} 必须是对象: {path}")
    return value


def _contract_hash(contract: Mapping[str, Any]) -> str:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    return _sha256_bytes(_canonical_bytes(normalized))


def _prompt_identity_payload(prompt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": prompt["schema_version"],
        "protocol_id": prompt["protocol_id"],
        "system_prompt": prompt["system_prompt"],
        "user_prompt": prompt["user_prompt"],
        "output_fields": prompt["output_fields"],
        "label_pools": prompt["label_pools"],
    }


def prompt_content_sha256(prompt: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_bytes(_prompt_identity_payload(prompt)))


def _expected_label_pools(contract: Mapping[str, Any]) -> dict[str, list[Any]]:
    schema = contract.get("model_output_schema")
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    if not isinstance(properties, Mapping):
        raise PromptControlError("V4.1 contract 缺少 model_output_schema.properties")
    pools: dict[str, list[Any]] = {}
    for field in OUTPUT_FIELDS:
        definition = properties.get(field)
        values = definition.get("enum") if isinstance(definition, Mapping) else None
        if not isinstance(values, list):
            raise PromptControlError(f"V4.1 contract 缺少 {field} enum")
        pools[field] = values
    return pools


def validate_active_prompt(
    source: Path,
    *,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict[str, Any]:
    """Validate the editable prompt and its exact V4.1 schema binding."""
    source = Path(source)
    prompt = _read_yaml(source, "active prompt")
    _read_json(Path(schema_path), "prompt control schema")
    required = {
        "schema_version",
        "protocol_id",
        "revision_id",
        "system_prompt",
        "user_prompt",
        "output_fields",
        "label_pools",
    }
    if set(prompt) != required:
        raise PromptControlError(
            f"active prompt 字段非法: expected={sorted(required)} actual={sorted(prompt)}"
        )
    if (
        prompt.get("schema_version") != PROMPT_SCHEMA_VERSION
        or prompt.get("protocol_id") != "tensile-vlm/v4.1"
        or not isinstance(prompt.get("revision_id"), str)
        or not 3 <= len(prompt["revision_id"]) <= 128
        or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for char in prompt["revision_id"]
        )
        or prompt["revision_id"][0] not in "abcdefghijklmnopqrstuvwxyz0123456789"
    ):
        raise PromptControlError("active prompt schema/protocol/revision_id 非法")
    if any(
        not isinstance(prompt.get(key), str) or not prompt[key].strip()
        for key in ("system_prompt", "user_prompt")
    ):
        raise PromptControlError("system_prompt 和 user_prompt 必须是非空字符串")
    if not isinstance(prompt.get("label_pools"), dict):
        raise PromptControlError("label_pools 必须是对象")
    if prompt["output_fields"] != OUTPUT_FIELDS:
        raise PromptControlError("output_fields 必须使用固定四字段顺序")
    contract = _read_json(Path(contract_path), "V4.1 contract")
    if (
        contract.get("contract_version") != prompt["protocol_id"]
        or contract.get("contract_hash") != _contract_hash(contract)
    ):
        raise PromptControlError("V4.1 contract 身份漂移")
    if prompt["label_pools"] != _expected_label_pools(contract):
        raise PromptControlError("label_pools 与 V4.1 contract schema 不一致")
    return prompt


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PromptControlError("无法解析发布代码 commit") from exc
    return result.stdout.strip()


def _manifest_payload(
    prompt: Mapping[str, Any],
    *,
    source: Path,
    prompt_yaml: bytes,
    generated_at: str,
    code_commit: str,
) -> dict[str, Any]:
    label_payload = {
        "output_fields": prompt["output_fields"],
        "label_pools": prompt["label_pools"],
    }
    try:
        source_path = str(source.relative_to(ROOT))
    except ValueError:
        source_path = str(source)
    return {
        "schema_version": "tensile-prompt-registry-manifest/v1",
        "prompt_schema_version": prompt["schema_version"],
        "protocol_id": prompt["protocol_id"],
        "revision_id": prompt["revision_id"],
        "prompt_content_sha256": prompt_content_sha256(prompt),
        "prompt_yaml_sha256": _sha256_bytes(prompt_yaml),
        "source_path": source_path,
        "source_sha256": sha256_file(source),
        "system_prompt_sha256": _sha256_bytes(prompt["system_prompt"].encode("utf-8")),
        "user_prompt_sha256": _sha256_bytes(prompt["user_prompt"].encode("utf-8")),
        "fields_and_labels_sha256": _sha256_bytes(_canonical_bytes(label_payload)),
        "publishing_code_commit": code_commit,
        "generated_at": generated_at,
        "immutable": True,
    }


def publish_prompt(
    source: Path,
    *,
    registry_root: Path = DEFAULT_REGISTRY_ROOT,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    now: datetime | None = None,
    code_commit: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Publish a validated prompt without allowing revision overwrite."""
    source = Path(source).resolve()
    prompt = validate_active_prompt(
        source,
        schema_path=Path(schema_path),
        contract_path=Path(contract_path),
    )
    prompt_yaml = source.read_bytes()
    target = Path(registry_root) / prompt["revision_id"]
    if target.exists():
        revision, manifest = load_prompt_revision(target)
        if (
            prompt_content_sha256(revision) != prompt_content_sha256(prompt)
            or revision != prompt
        ):
            raise PromptControlError(f"拒绝覆盖已有 Prompt revision: {target}")
        return target, manifest
    generated_at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    manifest = _manifest_payload(
        prompt,
        source=source,
        prompt_yaml=prompt_yaml,
        generated_at=generated_at,
        code_commit=code_commit or _git_commit(ROOT),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        (staging / "prompt.yaml").write_bytes(prompt_yaml)
        (staging / "manifest.json").write_text(
            _pretty_json(manifest),
            encoding="utf-8",
        )
        os.replace(staging, target)
    finally:
        if staging.exists():
            for child in staging.iterdir():
                child.unlink()
            staging.rmdir()
    return target, manifest


def load_prompt_revision(
    revision_dir: Path,
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and fully verify one immutable registry revision."""
    revision_dir = Path(revision_dir)
    prompt_path = revision_dir / "prompt.yaml"
    manifest_path = revision_dir / "manifest.json"
    prompt = validate_active_prompt(
        prompt_path,
        contract_path=Path(contract_path),
    )
    manifest = _read_json(manifest_path, "prompt manifest")
    expected = {
        "revision_id": prompt["revision_id"],
        "protocol_id": prompt["protocol_id"],
        "prompt_content_sha256": prompt_content_sha256(prompt),
        "prompt_yaml_sha256": sha256_file(prompt_path),
        "system_prompt_sha256": _sha256_bytes(prompt["system_prompt"].encode("utf-8")),
        "user_prompt_sha256": _sha256_bytes(prompt["user_prompt"].encode("utf-8")),
        "fields_and_labels_sha256": _sha256_bytes(
            _canonical_bytes(
                {
                    "output_fields": prompt["output_fields"],
                    "label_pools": prompt["label_pools"],
                }
            )
        ),
    }
    if (
        manifest.get("schema_version") != "tensile-prompt-registry-manifest/v1"
        or manifest.get("immutable") is not True
        or any(manifest.get(key) != value for key, value in expected.items())
    ):
        raise PromptControlError(f"Prompt revision manifest 身份漂移: {revision_dir}")
    return prompt, manifest


def build_experiment_contract(
    *,
    prompt_revision_dir: Path,
    release_identity: Mapping[str, Any],
    sampling_identity: Mapping[str, Any],
    generation: Mapping[str, Any],
    base_contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict[str, Any]:
    """Create a self-contained experiment contract with one prompt snapshot."""
    prompt, prompt_manifest = load_prompt_revision(
        prompt_revision_dir,
        contract_path=base_contract_path,
    )
    base_contract = _read_json(Path(base_contract_path), "V4.1 contract")
    if base_contract.get("contract_hash") != _contract_hash(base_contract):
        raise PromptControlError("V4.1 base contract 身份漂移")
    if dict(generation) != base_contract.get("analysis", {}).get("generation"):
        raise PromptControlError("generation 必须与 V4.1 contract 固定配置一致")
    required_release = ("release_id", "release_manifest_sha256")
    required_sampling = (
        "sampling_id",
        "sampling_manifest_sha256",
        "candidate_sequence_sha256",
    )
    if any(not release_identity.get(key) for key in required_release):
        raise PromptControlError("release identity 不完整")
    if any(not sampling_identity.get(key) for key in required_sampling):
        raise PromptControlError("sampling identity 不完整")
    snapshot = {
        "revision_id": prompt["revision_id"],
        "schema_version": prompt["schema_version"],
        "protocol_id": prompt["protocol_id"],
        "prompt_manifest_sha256": sha256_file(
            Path(prompt_revision_dir) / "manifest.json"
        ),
        "prompt_content_sha256": prompt_manifest["prompt_content_sha256"],
        "system_prompt": prompt["system_prompt"],
        "user_prompt": prompt["user_prompt"],
        "output_fields": prompt["output_fields"],
        "label_pools": prompt["label_pools"],
    }
    payload = {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "immutable": True,
        "base_contract_version": base_contract["contract_version"],
        "base_contract_hash": base_contract["contract_hash"],
        "release": dict(release_identity),
        "sampling": dict(sampling_identity),
        "prompt": snapshot,
        "generation": dict(generation),
    }
    payload["experiment_contract_sha256"] = _sha256_bytes(_canonical_bytes(payload))
    return payload


def load_experiment_contract(
    path: Path,
    *,
    base_contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict[str, Any]:
    """Verify a self-contained experiment contract and its prompt snapshot."""
    value = _read_json(Path(path), "experiment contract")
    declared = value.get("experiment_contract_sha256")
    normalized = dict(value)
    normalized.pop("experiment_contract_sha256", None)
    if (
        value.get("schema_version") != EXPERIMENT_SCHEMA_VERSION
        or value.get("immutable") is not True
        or declared != _sha256_bytes(_canonical_bytes(normalized))
    ):
        raise PromptControlError("experiment contract 自哈希或身份非法")
    base = _read_json(Path(base_contract_path), "V4.1 contract")
    if (
        base.get("contract_hash") != _contract_hash(base)
        or value.get("base_contract_version") != base.get("contract_version")
        or value.get("base_contract_hash") != base.get("contract_hash")
    ):
        raise PromptControlError("experiment contract 的 base contract 漂移")
    prompt = value.get("prompt")
    if not isinstance(prompt, Mapping):
        raise PromptControlError("experiment contract 缺少 Prompt snapshot")
    prompt_payload = {
        "schema_version": prompt.get("schema_version"),
        "protocol_id": prompt.get("protocol_id"),
        "revision_id": prompt.get("revision_id"),
        "system_prompt": prompt.get("system_prompt"),
        "user_prompt": prompt.get("user_prompt"),
        "output_fields": prompt.get("output_fields"),
        "label_pools": prompt.get("label_pools"),
    }
    if (
        prompt.get("prompt_content_sha256")
        != prompt_content_sha256(prompt_payload)
        or not _is_sha256(prompt.get("prompt_manifest_sha256"))
        or prompt_payload["output_fields"] != OUTPUT_FIELDS
        or prompt_payload["label_pools"] != _expected_label_pools(base)
    ):
        raise PromptControlError("experiment contract Prompt snapshot 漂移")
    release = value.get("release")
    sampling = value.get("sampling")
    if (
        not isinstance(release, Mapping)
        or not release.get("release_id")
        or not _is_sha256(release.get("release_manifest_sha256"))
        or not isinstance(sampling, Mapping)
        or not sampling.get("sampling_id")
        or not _is_sha256(sampling.get("sampling_manifest_sha256"))
        or not _is_sha256(sampling.get("candidate_sequence_sha256"))
        or value.get("generation") != base.get("analysis", {}).get("generation")
    ):
        raise PromptControlError("experiment contract 数据或 generation 身份漂移")
    return value


def validate_model_bundle_prompt(
    bundle_manifest: Mapping[str, Any],
    experiment_contract: Mapping[str, Any],
) -> None:
    """Fail closed unless a model/service bundle declares the exact prompt."""
    prompt = experiment_contract["prompt"]
    expected = {
        "experiment_contract_sha256": experiment_contract[
            "experiment_contract_sha256"
        ],
        "prompt_revision_id": prompt["revision_id"],
        "prompt_content_sha256": prompt["prompt_content_sha256"],
        "response_fields": OUTPUT_FIELDS,
    }
    if (
        bundle_manifest.get("schema_version") != MODEL_BUNDLE_SCHEMA_VERSION
        or any(bundle_manifest.get(key) != value for key, value in expected.items())
    ):
        raise PromptControlError("模型或服务 bundle 的 Prompt/schema 身份不匹配")


def build_model_messages(
    experiment_contract: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Build the fixed model request; user intent is deliberately absent."""
    prompt = experiment_contract["prompt"]
    return [
        {"role": "system", "content": str(prompt["system_prompt"])},
        {"role": "user", "content": f"<video>\n{prompt['user_prompt']}"},
    ]
