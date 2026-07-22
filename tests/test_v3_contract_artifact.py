import hashlib
import json
from pathlib import Path

from pipeline.v3_labels import (
    CLIP_STATES,
    FRACTURE_MECHANISMS,
    LOCATIONS,
    SPECIAL_CASES,
    V3_LABEL_FIELDS,
    validate_v3_labels,
)


CONTRACT_PATH = (
    Path(__file__).parents[1] / "pipeline" / "contracts" / "tensile_vlm_v3.json"
)
EXPECTED_HASH = "3f9f8217774cb4947fc4e19e41a5fe14b8a5ea30c8e84ed4f664abddd9de04f0"


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _canonical_hash(contract: dict) -> str:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_v3_contract_identity_and_hash_are_fixed():
    contract = _load_contract()
    assert contract["contract_version"] == "tensile-vlm/v3"
    assert contract["contract_hash"] == _canonical_hash(contract) == EXPECTED_HASH


def test_v3_contract_matches_label_helper_and_search_boundary():
    contract = _load_contract()
    assert contract["model_output_fields"] == list(V3_LABEL_FIELDS)
    assert set(contract["clip_states"]) == CLIP_STATES
    assert set(contract["fracture_mechanisms"]) == FRACTURE_MECHANISMS
    assert set(contract["locations"]) == LOCATIONS
    assert set(contract["special_cases"]) == SPECIAL_CASES
    assert contract["search_semantics"]["direction_field"] == "clip_state"
    assert contract["search_semantics"]["summary_fields"] == [
        "fracture_mechanism",
        "root_break",
        "location",
    ]


def test_v3_contract_prompt_drops_local_frame_localization():
    contract = _load_contract()
    analysis_text = "\n".join(
        contract["analysis"][key]
        for key in ("system_prompt", "user_prompt", "retry_prompt")
    )
    assert "clip_state" in analysis_text
    assert "fracture_between" not in analysis_text
    assert "has_fracture" not in analysis_text


def test_v3_contract_examples_follow_cross_field_rules():
    assert validate_v3_labels(
        {
            "clip_state": "未断裂",
            "fracture_mechanism": None,
            "root_break": None,
            "location": None,
            "special_case": None,
        }
    ).valid
    assert validate_v3_labels(
        {
            "clip_state": "无法判断",
            "fracture_mechanism": None,
            "root_break": None,
            "location": None,
            "special_case": "视频异常",
        }
    ).valid
    assert not validate_v3_labels(
        {
            "clip_state": "未断裂",
            "fracture_mechanism": "脆性断裂",
            "root_break": None,
            "location": None,
            "special_case": None,
        }
    ).valid
