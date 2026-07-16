import hashlib
import json

import pytest
import yaml

from pipeline.production_contract import CONTRACT_PATH, load_production_contract, production_contract_hash
from pipeline.server_adapter import wrap_response


def _processor_info() -> dict:
    return {
        "processor_version": "minicpmv4.5/0.1",
        "max_frames": 8,
        "model_version": "minicpm-v-4.5",
        "transformers_version": "4.test",
        "llamafactory_version": "test-rev",
        "base_model_version": "base-test",
        "artifact_version": "adapter-test",
        "config_fingerprint": "sha256:test",
        "runtime_device": "cuda:0",
        "runtime_dtype": "bfloat16",
        "contract_version": "tensile-vlm/v1",
        "prompt_contract_hash": production_contract_hash(),
    }


def test_prompt_library_production_section_matches_artifact():
    library = yaml.safe_load((CONTRACT_PATH.parents[1] / "prompt_library.yaml").read_text(encoding="utf-8"))
    production = library["production"]
    contract = load_production_contract()
    assert production["version"] == contract["contract_version"]
    for field in ("system_prompt", "user_prompt", "evidence_system_prompt", "evidence_user_prompt"):
        assert production[field].strip() == contract[field]


def test_contract_hash_is_file_sha256():
    assert production_contract_hash() == hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()


def test_server_adapter_emits_matching_contract_identity():
    wrapped = wrap_response(
        {"choices": []},
        [{"index": i, "timestamp": float(i)} for i in range(8)],
        _processor_info(),
    )
    deployment = wrapped["preprocessing"]["deployment_manifest"]
    assert deployment["contract_version"] == "tensile-vlm/v1"
    assert deployment["prompt_contract_hash"] == production_contract_hash()


def test_server_adapter_rejects_contract_drift():
    info = _processor_info()
    info["prompt_contract_hash"] = "0" * 64
    with pytest.raises(ValueError, match="prompt_contract_hash"):
        wrap_response(
            {"choices": []},
            [{"index": i, "timestamp": float(i)} for i in range(8)],
            info,
        )

