from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from .constants import PROMPT_NAMES

DEFAULT_PROMPT_LIBRARY_PATH = Path(__file__).resolve().parents[2] / "pipeline" / "prompt_library.yaml"

_LIBRARY_CACHE: dict[Path, dict[str, Any]] = {}


def _load_prompt_library(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Prompt library not found: {path}")
    with open(path, encoding="utf-8") as handle:
        library = yaml.safe_load(handle)
    if not isinstance(library, dict):
        raise ValueError(f"Prompt library {path} must contain a YAML mapping")
    for required_key in ("version", "system_prompt", "user_prompt_templates"):
        if required_key not in library:
            raise ValueError(f"Prompt library {path} missing required key: {required_key}")
    return library


def get_prompt_library(path: Path | str | None = None) -> dict[str, Any]:
    """加载并返回 prompt 模板库。同一路径会被缓存。"""
    resolved = Path(path) if path else DEFAULT_PROMPT_LIBRARY_PATH
    if resolved not in _LIBRARY_CACHE:
        _LIBRARY_CACHE[resolved] = _load_prompt_library(resolved)
    return _LIBRARY_CACHE[resolved]


def get_prompt_version(library: dict[str, Any] | None = None) -> str:
    """返回 prompt 模板库版本。"""
    lib = library or get_prompt_library()
    return str(lib.get("version", ""))


def get_system_prompt(library: dict[str, Any] | None = None) -> str:
    """返回模板库中的 system prompt。"""
    lib = library or get_prompt_library()
    return str(lib.get("system_prompt", "")).strip()


def get_system_prompt_hash(library: dict[str, Any] | None = None) -> str:
    """返回 system prompt 的 SHA-256 哈希（用于版本一致性检查）。"""
    return hashlib.sha256(get_system_prompt(library).encode("utf-8")).hexdigest()


def get_system_prompt_variant_ids(library: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Return IDs for experimental system prompts in the shared prompt library."""
    lib = library or get_prompt_library()
    variants = lib.get("system_prompt_variants", {}) or {}
    if not isinstance(variants, dict):
        raise ValueError("system_prompt_variants must be a mapping when present")
    return tuple(str(prompt_id) for prompt_id in variants)


def get_system_prompt_by_id(prompt_id: str, library: dict[str, Any] | None = None) -> str:
    """Return the training-default prompt or an explicit experimental variant."""
    if prompt_id == "training_default":
        return get_system_prompt(library)
    lib = library or get_prompt_library()
    variants = lib.get("system_prompt_variants", {}) or {}
    try:
        prompt = variants[prompt_id]
    except KeyError as exc:
        available = ("training_default", *get_system_prompt_variant_ids(lib))
        raise ValueError(f"Unknown system prompt ID {prompt_id!r}; available: {available}") from exc
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"System prompt variant {prompt_id!r} must be a non-empty string")
    return prompt.strip()


def get_user_prompt(template_index: int = 0, library: dict[str, Any] | None = None) -> str:
    """返回模板库中指定索引的 user prompt 模板。

    训练使用 <video> 占位符让 LLaMA-Factory 替换为视频 token；评估阶段模型
    runtime 已经单独传入图像，因此这里去掉占位符，仅保留语义等价的提问文本。
    """
    lib = library or get_prompt_library()
    templates = lib.get("user_prompt_templates", [])
    if not templates:
        raise ValueError("Prompt library has no user_prompt_templates")
    template = templates[template_index % len(templates)]
    prompt = str(template.get("prompt", ""))
    # 去掉 LLaMA-Factory 视频占位符；eval 的 model_runtime 自行拼接图像 tag。
    prompt = prompt.replace("<video>", "")
    return prompt.strip()


def get_inference_target_format(library: dict[str, Any] | None = None) -> str:
    """返回推理目标格式（五字段，含 confidence）的文本说明。"""
    lib = library or get_prompt_library()
    return str(lib.get("inference_target_format", "")).strip()


def get_inference_target_schema(library: dict[str, Any] | None = None) -> dict[str, Any]:
    """返回推理目标 schema（五字段，含 confidence）。"""
    lib = library or get_prompt_library()
    return lib.get("inference_target_schema", {}) or {}


def get_inference_user_prompt(template_index: int = 0, library: dict[str, Any] | None = None) -> str:
    """返回评估/推理使用的 user prompt，在训练问法基础上要求模型返回 confidence。"""
    base = get_user_prompt(template_index, library)
    target_format = get_inference_target_format(library)
    prompt = f"{base}\n\n请按以下格式输出，并在结果 JSON 中包含 confidence 字段（0-1，表示你对判断的置信度）："
    if target_format:
        prompt = f"{prompt}\n{target_format}"
    return prompt


def get_user_prompt_template_id(template_index: int = 0, library: dict[str, Any] | None = None) -> str:
    """返回指定索引 user prompt 模板的 template_id。"""
    lib = library or get_prompt_library()
    templates = lib.get("user_prompt_templates", [])
    if not templates:
        raise ValueError("Prompt library has no user_prompt_templates")
    template = templates[template_index % len(templates)]
    return str(template.get("template_id", ""))


def get_prompt(name: str) -> str:
    """向后兼容接口：'training' 对应含 confidence 的 inference user prompt。"""
    if name == "training":
        return get_inference_user_prompt(0)
    raise ValueError(f"Unsupported prompt: {name}. Expected one of {PROMPT_NAMES}.")
