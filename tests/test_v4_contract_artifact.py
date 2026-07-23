import hashlib
import json
from pathlib import Path

from pipeline.v4_labels import (
    FRACTURE_SITES,
    V4_LABEL_FIELDS,
    fracture_site_severity,
)


CONTRACT_PATH = (
    Path(__file__).parents[1] / "pipeline" / "contracts" / "tensile_vlm_v4.json"
)
EXPECTED_HASH = "d25df900c0c5e0013e20d40fb01202939b465b3fb4ede4fdd8268d983c2c6481"


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _canonical_hash(contract: dict) -> str:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_v4_contract_identity_and_hash_are_fixed():
    contract = _load_contract()
    assert contract["contract_version"] == "tensile-vlm/v4"
    assert contract["contract_hash"] == _canonical_hash(contract) == EXPECTED_HASH


def test_v4_contract_is_four_field_and_has_three_exclusive_sites():
    contract = _load_contract()
    assert contract["model_output_fields"] == list(V4_LABEL_FIELDS)
    assert set(contract["fracture_sites"]) == FRACTURE_SITES
    assert "root_break" not in contract["model_output_fields"]
    assert "location" not in contract["model_output_fields"]
    assert contract["search_semantics"]["summary_fields"] == [
        "fracture_mechanism",
        "fracture_site",
    ]


def test_v4_contract_severity_projection_matches_helper():
    contract = _load_contract()
    expected = contract["fracture_site_severity"]
    assert fracture_site_severity("inside_gauge") == expected["inside_gauge"]
    assert fracture_site_severity("outside_gauge_non_root") == expected[
        "outside_gauge_non_root"
    ]
    assert fracture_site_severity("grip_root") == expected["grip_root"]
    assert fracture_site_severity(None) == expected["null"]


def test_v4_prompt_defines_business_distinctions_without_model_quality_label():
    contract = _load_contract()
    text = "\n".join(
        contract["analysis"][key]
        for key in ("system_prompt", "user_prompt", "retry_prompt")
    )
    assert "标距内断裂" in text
    assert "标距外但非夹具根部" in text
    assert "夹具根部齐根断裂" in text
    assert "root_break" not in text
