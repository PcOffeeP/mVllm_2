import hashlib
import json
import sys
import types
from fractions import Fraction

import pytest
import yaml

from pipeline.production_contract import (
    CONTRACT_PATH,
    EXPECTED_CONTRACT_HASH,
    PROMPT_LIBRARY_PATH,
    canonical_contract_bytes,
    load_production_contract,
    production_contract_hash,
)
from pipeline.server_adapter import DEPLOYMENT_FIELDS, wrap_response
from pipeline.server_proxy import (
    _analysis_output_valid,
    _chat_model_args,
    _deployment_snapshot,
    _replace_video_url,
    _request_mode,
    _validate_startup_config,
    create_integrated_app,
)
from pipeline.llamafactory_contract import CapturingVideoProcessor


def _startup_config() -> dict:
    return {
        "processor_version": "minicpmv4.5/0.1",
        "max_frames": 8,
        "model_version": "minicpm-v-4.5",
        "transformers_version": "4.test",
        "llamafactory_version": "test-rev",
        "base_model_version": "base-test",
        "adapter_version": "adapter-test",
        "config_fingerprint": "sha256:test",
        "runtime_device": "cuda:0",
        "runtime_dtype": "bfloat16",
    }


def test_production_contract_reads_the_two_canonical_prompts():
    library = yaml.safe_load(PROMPT_LIBRARY_PATH.read_text(encoding="utf-8"))
    contract = load_production_contract()
    assert library["system_prompt"].strip() == contract["analysis"]["system_prompt"]
    assert library["user_prompt"].strip() == contract["analysis"]["user_prompt"]
    assert contract["anomaly_types"] == ["视频异常"]
    assert contract["contract_hash"] == EXPECTED_CONTRACT_HASH
    assert "production" not in library
    assert "experiments" not in library
    assert "test" not in library


def test_contract_hash_is_canonical_and_fixed():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    digest = hashlib.sha256(canonical_contract_bytes(contract)).hexdigest()
    assert production_contract_hash() == digest == EXPECTED_CONTRACT_HASH


def test_server_adapter_emits_matching_contract_identity():
    wrapped = wrap_response(
        {"choices": []},
        [{"index": i, "timestamp": float(i)} for i in range(8)],
        _deployment_snapshot(_startup_config()),
    )
    deployment = wrapped["preprocessing"]["deployment_manifest"]
    assert set(deployment) == DEPLOYMENT_FIELDS
    assert deployment["contract_version"] == "tensile-vlm/v2"
    assert deployment["contract_hash"] == production_contract_hash()


def test_server_adapter_rejects_contract_drift():
    info = _deployment_snapshot(_startup_config())
    info["contract_hash"] = "0" * 64
    with pytest.raises(ValueError, match="contract_hash"):
        wrap_response(
            {"choices": []},
            [{"index": i, "timestamp": float(i)} for i in range(8)],
            info,
        )


def test_startup_config_is_exact_and_contract_identity_is_injected():
    config = _validate_startup_config(_startup_config())
    assert set(config) == {
        "max_frames",
        "model_version",
        "adapter_version",
        "base_model_version",
        "processor_version",
        "llamafactory_version",
        "transformers_version",
        "config_fingerprint",
        "runtime_device",
        "runtime_dtype",
    }
    deployment = _deployment_snapshot(config)
    assert set(deployment) == DEPLOYMENT_FIELDS
    assert deployment["contract_hash"] == EXPECTED_CONTRACT_HASH


def test_startup_config_rejects_contract_override_and_placeholders():
    config = _startup_config()
    config["contract_hash"] = "forged"
    with pytest.raises(ValueError, match="exactly"):
        _validate_startup_config(config)
    config = _startup_config()
    config["adapter_version"] = "REPLACE_ME"
    with pytest.raises(ValueError, match="invalid"):
        _validate_startup_config(config)


def test_server_proxy_enables_minicpm_remote_code():
    args = _chat_model_args("/models/minicpm")
    assert args["model_name_or_path"] == "/models/minicpm"
    assert args["template"] == "minicpm_v"
    assert args["infer_backend"] == "huggingface"
    assert args["trust_remote_code"] is True
    assert args["do_sample"] is False
    assert args["num_beams"] == 1
    assert args["temperature"] == 0.0
    assert args["max_new_tokens"] == 256


def test_server_proxy_replaces_only_video_url():
    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,AAAA"}},
                {"type": "text", "text": "keep me"},
            ],
        }],
    }
    _replace_video_url(payload, "/safe/request.mp4")
    assert payload["messages"][0]["content"] == [
        {"type": "video_url", "video_url": {"url": "/safe/request.mp4"}},
        {"type": "text", "text": "keep me"},
    ]


def test_server_proxy_rejects_multiple_video_urls():
    payload = {
        "messages": [{
            "content": [
                {"type": "video_url", "video_url": {"url": "first"}},
                {"type": "video_url", "video_url": {"url": "second"}},
            ],
        }],
    }
    with pytest.raises(ValueError, match="exactly one video_url"):
        _replace_video_url(payload, "/safe/request.mp4")


def test_request_mode_only_accepts_fixed_analysis_or_evidence_prompts():
    contract = load_production_contract()
    payload = {
        "messages": [
            {"role": "system", "content": contract["analysis"]["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,AAAA"}},
                    {"type": "text", "text": contract["analysis"]["user_prompt"]},
                ],
            },
        ]
    }
    assert _request_mode(payload, contract) == "analysis"
    payload["messages"][1]["content"][1]["text"] = "override"
    with pytest.raises(ValueError, match="prompts"):
        _request_mode(payload, contract)


def test_analysis_output_validation_is_strict_and_anomaly_compatible():
    assert _analysis_output_valid(
        '{"has_fracture":null,"fracture_between":null,"type":"视频异常","location":null}'
    )
    assert not _analysis_output_valid(
        '{"has_fracture":null,"fracture_between":null,"type":null,"location":null}'
    )
    assert not _analysis_output_valid(
        '{"has_fracture":false,"fracture_between":null,"type":null,"location":null}'
    )


def test_integrated_app_preflight_and_server_owned_retry(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    contract = load_production_contract()
    calls = []

    class FakeRequestModel:
        @classmethod
        def model_validate(cls, payload):
            calls.append(payload)
            return payload

    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]
            self._content = content

        def model_dump(self, mode="json"):
            del mode
            return {
                "id": "chatcmpl-test",
                "choices": [{"message": {"role": "assistant", "content": self._content}}],
            }

    responses = iter(
        [
            FakeResponse("not-json"),
            FakeResponse(
                '{"has_fracture":null,"fracture_between":null,'
                '"type":"视频异常","location":null}'
            ),
        ]
    )

    async def fake_create_chat_completion_response(request, chat_model):
        del request, chat_model
        return next(responses)

    chat_module = types.ModuleType("llamafactory.api.chat")
    chat_module.create_chat_completion_response = fake_create_chat_completion_response
    common_module = types.ModuleType("llamafactory.api.common")
    common_module.SAFE_MEDIA_PATH = str(tmp_path)
    protocol_module = types.ModuleType("llamafactory.api.protocol")
    protocol_module.ChatCompletionRequest = FakeRequestModel
    monkeypatch.setitem(sys.modules, "llamafactory.api.chat", chat_module)
    monkeypatch.setitem(sys.modules, "llamafactory.api.common", common_module)
    monkeypatch.setitem(sys.modules, "llamafactory.api.protocol", protocol_module)

    class FakeCapture:
        def __init__(self):
            self.last_capture = None

        def record_selected_indices(self, indices):
            del indices

        def reset_capture(self, video_path):
            del video_path
            self.last_capture = {
                "frames": [
                    {"index": 0, "timestamp": 0.0},
                    {"index": 1, "timestamp": 1.0},
                ],
                "tensor_digest": "sha256:test",
                "tensor_shape": [1, 2],
            }

    class FakePlugin:
        def get_mm_inputs(self, *args, **kwargs):
            del args, kwargs
            return {}

        def _get_video_sample_indices(self, stream, *args, **kwargs):
            del stream, args, kwargs
            return [0, 1]

    MiniCPMVProcessor = type("MiniCPMVProcessor", (), {})
    capture = FakeCapture()
    monkeypatch.setattr(
        "pipeline.server_proxy.configure_loaded_processor",
        lambda processor, capture=True: globals_capture if capture else None,
    )
    globals_capture = capture
    engine = types.SimpleNamespace(
        processor=MiniCPMVProcessor(),
        template=types.SimpleNamespace(mm_plugin=FakePlugin()),
    )
    chat_model = types.SimpleNamespace(engine=engine)
    config = _startup_config()
    config["processor_version"] = "MiniCPMVProcessor"
    app = create_integrated_app(chat_model, config)

    client = TestClient(app)
    preflight = client.get("/v1/tensile/contract")
    assert preflight.status_code == 200
    preflight_body = preflight.json()
    assert preflight_body["contract_hash"] == EXPECTED_CONTRACT_HASH
    assert preflight_body["capabilities"] == {"analysis": True, "evidence": True}

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "full-merged",
            "messages": [
                {"role": "system", "content": contract["analysis"]["system_prompt"]},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {"url": "data:video/mp4;base64,AAAA"},
                        },
                        {"type": "text", "text": contract["analysis"]["user_prompt"]},
                    ],
                },
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["preprocessing"]["deployment_manifest"] == preflight_body["deployment_manifest"]
    assert len(calls) == 2
    assert len(calls[0]["messages"]) == 2
    assert calls[0]["do_sample"] is False
    assert calls[0]["temperature"] == 0.0
    assert calls[0]["max_tokens"] == 256
    assert calls[1]["messages"][-1] == {
        "role": "user",
        "content": contract["analysis"]["retry_prompt"],
    }


def test_capture_uses_selected_indices_not_frame_similarity(monkeypatch):
    class Frame:
        def __init__(self, pts):
            self.pts = pts

    class Stream:
        type = "video"
        time_base = Fraction(1, 30)
        average_rate = Fraction(30, 1)

    class Container:
        streams = [Stream()]

        def decode(self, _stream):
            # The frames intentionally carry no image data: selection evidence
            # must come from the plugin's indices, not visual similarity.
            return iter([Frame(index) for index in range(6)])

        def close(self):
            pass

    monkeypatch.setattr("pipeline.llamafactory_contract.av.open", lambda *_args, **_kwargs: Container())
    capture = CapturingVideoProcessor(object())
    capture.record_frame_selection("ignored.mp4", [0, 2, 5])

    assert [frame.original_frame for frame in capture._selected_frames] == [0, 2, 5]
    assert [frame.timestamp for frame in capture._selected_frames] == pytest.approx([0.0, 2 / 30, 5 / 30])
