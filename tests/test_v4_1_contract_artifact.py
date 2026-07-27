import hashlib
import json
from pathlib import Path

from pipeline.v4_1_labels import CLIP_STATES, V4_1_LABEL_FIELDS


PATH = Path(__file__).parents[1] / "pipeline/contracts/tensile_vlm_v4_1.json"
EXPECTED_HASH = "3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab"


def test_v4_1_contract_hash_and_fields():
    contract = json.loads(PATH.read_text())
    normalized = dict(contract)
    normalized.pop("contract_hash")
    actual = hashlib.sha256(
        json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    assert contract["contract_version"] == "tensile-vlm/v4.1"
    assert contract["contract_hash"] == actual == EXPECTED_HASH
    assert contract["model_output_fields"] == list(V4_1_LABEL_FIELDS)
    assert set(contract["clip_states"]) == CLIP_STATES


def test_v4_1_contract_marks_incipient_summary_as_prospective():
    contract = json.loads(PATH.read_text())
    assert (
        contract["search_semantics"]["临界未断裂"]
        == "fracture_event_is_after_clip_with_visible_precursors"
    )
    assert (
        contract["search_semantics"]["summary_evidence_phase"]["临界未断裂"]
        == "prospective"
    )
    assert "临界未断裂" in contract["analysis"]["user_prompt"]
    assert "仍连续但已出现明显局部颈缩" in contract["analysis"]["user_prompt"]


def test_v4_1_contract_promotes_temporal_enum_clarification():
    contract = json.loads(PATH.read_text())
    analysis = contract["analysis"]
    assert "按时间顺序判断试样连续性" in analysis["user_prompt"]
    assert "必须严格使用下列枚举原词" in analysis["system_prompt"]
    assert "沿界面断裂" in analysis["user_prompt"]
    assert "严格使用指定枚举原词" in analysis["retry_prompt"]
