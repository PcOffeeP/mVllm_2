from __future__ import annotations

from pipeline.server_proxy import _analysis_output_valid, _deployment_snapshot
from pipeline.v4_1_production_contract import (
    EXPECTED_CONTRACT_HASH,
    load_v4_1_production_contract,
    v4_1_production_contract_hash,
)


def _startup_config() -> dict:
    return {
        "processor_version": "MiniCPMVProcessor",
        "max_frames": 8,
        "model_version": "intermediate-model",
        "transformers_version": "4.test",
        "llamafactory_version": "test-rev",
        "base_model_version": "base-test",
        "adapter_version": "stage-b-intermediate",
        "config_fingerprint": "sha256:test",
        "runtime_device": "cuda:0",
        "runtime_dtype": "bfloat16",
    }


def test_v4_1_service_contract_is_promoted_and_self_hashed() -> None:
    contract = load_v4_1_production_contract()
    assert contract["contract_version"] == "tensile-vlm/v4.1"
    assert contract["contract_hash"] == EXPECTED_CONTRACT_HASH
    assert v4_1_production_contract_hash() == EXPECTED_CONTRACT_HASH
    assert "按时间顺序判断试样连续性" in contract["analysis"]["user_prompt"]


def test_v4_1_deployment_snapshot_uses_selected_contract() -> None:
    contract = load_v4_1_production_contract()
    deployment = _deployment_snapshot(_startup_config(), contract)
    assert deployment["contract_version"] == "tensile-vlm/v4.1"
    assert deployment["contract_hash"] == EXPECTED_CONTRACT_HASH


def test_v4_1_output_validation_is_strict() -> None:
    valid = (
        '{"clip_state":"未断裂","fracture_mechanism":null,'
        '"fracture_site":null,"special_case":null}'
    )
    invalid_synonym = (
        '{"clip_state":"已断裂","fracture_mechanism":"沿界面断裂",'
        '"fracture_site":"grip_root","special_case":null}'
    )
    assert _analysis_output_valid(
        valid, contract_version="tensile-vlm/v4.1"
    )
    assert not _analysis_output_valid(
        invalid_synonym, contract_version="tensile-vlm/v4.1"
    )
