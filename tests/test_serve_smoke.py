import base64

import pytest

from pipeline.production_contract import load_production_contract, production_contract_hash
from pipeline.scripts.serve_smoke import (
    build_analysis_payload,
    validate_analysis_response,
    validate_preflight,
)


def test_build_analysis_payload_uses_canonical_prompts_and_one_mp4():
    contract = load_production_contract()
    payload = build_analysis_payload(b"video-bytes", contract)

    assert payload["stream"] is False
    assert len(payload["messages"]) == 2
    assert payload["messages"][0] == {
        "role": "system",
        "content": contract["analysis"]["system_prompt"],
    }
    content = payload["messages"][1]["content"]
    assert content[1] == {"type": "text", "text": contract["analysis"]["user_prompt"]}
    encoded = content[0]["video_url"]["url"].removeprefix("data:video/mp4;base64,")
    assert base64.b64decode(encoded) == b"video-bytes"


def test_build_analysis_payload_rejects_empty_video():
    with pytest.raises(ValueError, match="must not be empty"):
        build_analysis_payload(b"", load_production_contract())


def test_validate_preflight_requires_local_contract_identity():
    contract = load_production_contract()
    valid = {
        "contract_version": contract["contract_version"],
        "contract_hash": production_contract_hash(),
        "deployment_manifest": {
            "contract_version": contract["contract_version"],
            "contract_hash": production_contract_hash(),
        },
    }
    validate_preflight(valid)

    valid["contract_hash"] = "drift"
    with pytest.raises(RuntimeError, match="contract_hash"):
        validate_preflight(valid)


def test_validate_analysis_response_requires_evidence_and_identity():
    response = {
        "choices": [{"message": {"content": "{}"}}],
        "preprocessing": {
            "frames": [{"index": 0, "timestamp": 0.0}],
            "deployment_manifest": {"contract_hash": production_contract_hash()},
        },
    }
    validate_analysis_response(response)

    response["preprocessing"]["frames"] = []
    with pytest.raises(RuntimeError, match="frame table"):
        validate_analysis_response(response)
