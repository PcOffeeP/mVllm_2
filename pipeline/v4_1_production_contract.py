"""Load and fingerprint the promoted V4.1 pre-acceptance contract."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path(__file__).with_name("contracts") / "tensile_vlm_v4_1.json"
CONTRACT_VERSION = "tensile-vlm/v4.1"
EXPECTED_CONTRACT_HASH = (
    "3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab"
)


def canonical_contract_bytes(contract: dict[str, Any]) -> bytes:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _require_generation(section: Any, name: str) -> None:
    if not isinstance(section, dict) or section.get("generation") != {
        "do_sample": False,
        "num_beams": 1,
        "temperature": 0.0,
        "max_new_tokens": 256,
    }:
        raise RuntimeError(f"V4.1 contract {name}.generation is not pinned")


@lru_cache(maxsize=1)
def load_v4_1_production_contract() -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise RuntimeError("unsupported V4.1 production contract version")
    if contract.get("model_output_fields") != [
        "clip_state",
        "fracture_mechanism",
        "fracture_site",
        "special_case",
    ]:
        raise RuntimeError("V4.1 production contract field order drifted")
    for name in ("analysis", "evidence"):
        section = contract.get(name)
        if not isinstance(section, dict) or not all(
            isinstance(section.get(key), str) and section[key].strip()
            for key in (
                ("system_prompt", "user_prompt", "retry_prompt")
                if name == "analysis"
                else ("system_prompt", "user_prompt")
            )
        ):
            raise RuntimeError(f"V4.1 contract {name} prompts are invalid")
        _require_generation(section, name)
    video = contract.get("video")
    if (
        not isinstance(video, dict)
        or video.get("max_frames") != 8
        or video.get("allowed_media_types") != ["video/mp4"]
    ):
        raise RuntimeError("V4.1 production video contract drifted")
    actual_hash = hashlib.sha256(canonical_contract_bytes(contract)).hexdigest()
    if contract.get("contract_hash") != actual_hash:
        raise RuntimeError("V4.1 production contract self hash mismatch")
    if actual_hash != EXPECTED_CONTRACT_HASH:
        raise RuntimeError("V4.1 production contract fixed hash mismatch")
    return contract


def v4_1_production_contract_hash() -> str:
    return str(load_v4_1_production_contract()["contract_hash"])
