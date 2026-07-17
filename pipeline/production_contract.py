"""Authoritative production Prompt contract helpers."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONTRACT_PATH = Path(__file__).with_name("contracts") / "tensile_vlm_v1.json"
PROMPT_LIBRARY_PATH = Path(__file__).with_name("prompt_library.yaml")


@lru_cache(maxsize=1)
def load_production_contract() -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    prompt_library = yaml.safe_load(PROMPT_LIBRARY_PATH.read_text(encoding="utf-8"))
    if not isinstance(prompt_library, dict):
        raise RuntimeError("prompt library must be a YAML mapping")
    if contract.get("contract_version") != "tensile-vlm/v1":
        raise RuntimeError("unsupported production contract version")
    if contract.get("model_output_fields") != [
        "has_fracture",
        "fracture_between",
        "type",
        "location",
    ]:
        raise RuntimeError("production contract must use the trained four-field order")
    prompts = {}
    for key in ("system_prompt", "user_prompt"):
        value = prompt_library.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"prompt library {key} must be a non-empty string")
        prompts[key] = value.strip()
    return {**contract, **prompts}


def production_contract_hash() -> str:
    digest = hashlib.sha256()
    digest.update(CONTRACT_PATH.read_bytes())
    digest.update(b"\0")
    digest.update(PROMPT_LIBRARY_PATH.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    contract = load_production_contract()
    print(json.dumps({
        "contract_version": contract["contract_version"],
        "prompt_contract_hash": production_contract_hash(),
    }, ensure_ascii=False, indent=2))
