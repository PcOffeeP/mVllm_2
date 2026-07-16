"""Authoritative production Prompt contract helpers."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path(__file__).with_name("contracts") / "tensile_vlm_v1.json"


@lru_cache(maxsize=1)
def load_production_contract() -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("contract_version") != "tensile-vlm/v1":
        raise RuntimeError("unsupported production contract version")
    if contract.get("model_output_fields") != [
        "has_fracture",
        "fracture_between",
        "type",
        "location",
    ]:
        raise RuntimeError("production contract must use the trained four-field order")
    return contract


def production_contract_hash() -> str:
    return hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()


if __name__ == "__main__":
    contract = load_production_contract()
    print(json.dumps({
        "contract_version": contract["contract_version"],
        "prompt_contract_hash": production_contract_hash(),
    }, ensure_ascii=False, indent=2))
