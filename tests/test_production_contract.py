import hashlib
import json
from fractions import Fraction

import pytest
import yaml

from pipeline.production_contract import CONTRACT_PATH, load_production_contract, production_contract_hash
from pipeline.server_adapter import wrap_response
from pipeline.server_proxy import _chat_model_args, _replace_video_url
from pipeline.llamafactory_contract import CapturingVideoProcessor


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


def test_server_proxy_enables_minicpm_remote_code():
    args = _chat_model_args("/models/minicpm")
    assert args["model_name_or_path"] == "/models/minicpm"
    assert args["template"] == "minicpm_v"
    assert args["infer_backend"] == "huggingface"
    assert args["trust_remote_code"] is True


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
