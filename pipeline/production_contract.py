"""Load and fingerprint the pinned, self-contained production contract."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path(__file__).with_name("contracts") / "tensile_vlm_v2.json"
PROMPT_LIBRARY_PATH = Path(__file__).with_name("prompt_library.yaml")
CONTRACT_VERSION = "tensile-vlm/v2"
EXPECTED_CONTRACT_HASH = "d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102"

MODEL_OUTPUT_FIELDS = [
    "has_fracture",
    "fracture_between",
    "type",
    "location",
]
FRACTURE_TYPES = [
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
    "脆性断裂、齐根断裂",
]


def canonical_contract_bytes(contract: dict[str, Any]) -> bytes:
    """Serialize contract deterministically while excluding its own hash."""
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_generation(section: Any, name: str) -> None:
    if not isinstance(section, dict):
        raise RuntimeError(f"production contract {name} must be an object")
    generation = section.get("generation")
    if generation != {
        "do_sample": False,
        "num_beams": 1,
        "temperature": 0.0,
        "max_new_tokens": 256,
    }:
        raise RuntimeError(f"production contract {name}.generation is not pinned")


@lru_cache(maxsize=1)
def load_production_contract() -> dict[str, Any]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    required = {
        "contract_version",
        "contract_hash",
        "model_output_fields",
        "model_output_schema",
        "fracture_types",
        "other_types",
        "anomaly_types",
        "locations",
        "analysis",
        "evidence",
        "video",
        "validation_rules",
    }
    if set(contract) != required:
        missing = sorted(required - contract.keys())
        extra = sorted(contract.keys() - required)
        raise RuntimeError(f"production contract fields differ: missing={missing} extra={extra}")
    if contract["contract_version"] != CONTRACT_VERSION:
        raise RuntimeError("unsupported production contract version")
    if contract["model_output_fields"] != MODEL_OUTPUT_FIELDS:
        raise RuntimeError("production contract must use the trained four-field order")
    if contract["fracture_types"] != FRACTURE_TYPES:
        raise RuntimeError("production fracture types do not match the trained enum")
    if contract["other_types"] != ["未断裂", "未夹紧"]:
        raise RuntimeError("production non-fracture types do not match the trained enum")
    if contract["anomaly_types"] != ["视频异常"]:
        raise RuntimeError("production anomaly types must contain only 视频异常")
    if contract["locations"] != ["inside_gauge", "outside_gauge"]:
        raise RuntimeError("production locations do not match the trained enum")
    analysis = contract["analysis"]
    evidence = contract["evidence"]
    if not isinstance(analysis, dict) or not all(
        isinstance(analysis.get(key), str) and analysis[key].strip()
        for key in ("system_prompt", "user_prompt", "retry_prompt")
    ):
        raise RuntimeError("production analysis prompts must be non-empty")
    if not isinstance(evidence, dict) or not all(
        isinstance(evidence.get(key), str) and evidence[key].strip()
        for key in ("system_prompt", "user_prompt")
    ):
        raise RuntimeError("production evidence prompts must be non-empty")
    _require_generation(analysis, "analysis")
    _require_generation(evidence, "evidence")
    video = contract["video"]
    if not isinstance(video, dict) or video.get("max_frames") != 8:
        raise RuntimeError("production video.max_frames must be 8")
    if video.get("allowed_media_types") != ["video/mp4"]:
        raise RuntimeError("production video media type must be video/mp4")
    actual_hash = hashlib.sha256(canonical_contract_bytes(contract)).hexdigest()
    if contract["contract_hash"] != actual_hash:
        raise RuntimeError(
            f"production contract self hash mismatch: artifact={contract['contract_hash']} actual={actual_hash}"
        )
    if actual_hash != EXPECTED_CONTRACT_HASH:
        raise RuntimeError(
            f"production contract fixed hash mismatch: expected={EXPECTED_CONTRACT_HASH} actual={actual_hash}"
        )
    return contract


def production_contract_hash() -> str:
    return str(load_production_contract()["contract_hash"])


if __name__ == "__main__":
    contract = load_production_contract()
    print(
        json.dumps(
            {
                "contract_version": contract["contract_version"],
                "contract_hash": production_contract_hash(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
