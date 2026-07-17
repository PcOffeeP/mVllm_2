from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROMPT_LIBRARY_PATH = Path(__file__).resolve().parents[2] / "pipeline" / "prompt_library.yaml"

_LIBRARY_CACHE: dict[Path, dict[str, Any]] = {}


def _load_prompt_library(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Prompt library not found: {path}")
    with open(path, encoding="utf-8") as handle:
        library = yaml.safe_load(handle)
    if not isinstance(library, dict):
        raise ValueError(f"Prompt library {path} must contain a YAML mapping")
    for required_key in ("version", "system_prompt", "user_prompt", "target_schema"):
        if required_key not in library:
            raise ValueError(f"Prompt library {path} missing required key: {required_key}")
    return library


def get_prompt_library(path: Path | str | None = None) -> dict[str, Any]:
    """Load the canonical two-prompt configuration."""
    resolved = Path(path) if path else DEFAULT_PROMPT_LIBRARY_PATH
    if resolved not in _LIBRARY_CACHE:
        _LIBRARY_CACHE[resolved] = _load_prompt_library(resolved)
    return _LIBRARY_CACHE[resolved]


def get_prompt_version(library: dict[str, Any] | None = None) -> str:
    lib = library or get_prompt_library()
    return str(lib.get("version", ""))


def get_system_prompt(library: dict[str, Any] | None = None) -> str:
    lib = library or get_prompt_library()
    return _required_prompt(lib, "system_prompt")


def get_system_prompt_hash(library: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(get_system_prompt(library).encode("utf-8")).hexdigest()


def get_user_prompt(
    library: dict[str, Any] | None = None,
    *,
    include_video_placeholder: bool = False,
) -> str:
    """Return the single user prompt used by training, evaluation, and production.

    LLaMA-Factory training needs the ``<video>`` placeholder. The evaluation
    runtime supplies image inputs separately, so its text prompt omits it.
    """
    lib = library or get_prompt_library()
    prompt = _required_prompt(lib, "user_prompt")
    return f"<video>\n{prompt}" if include_video_placeholder else prompt


def get_user_prompt_hash(library: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(get_user_prompt(library).encode("utf-8")).hexdigest()


def get_target_schema(library: dict[str, Any] | None = None) -> dict[str, Any]:
    lib = library or get_prompt_library()
    return lib.get("target_schema", {}) or {}


def _required_prompt(library: dict[str, Any], key: str) -> str:
    value = library.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Prompt library {key} must be a non-empty string")
    return value.strip()
