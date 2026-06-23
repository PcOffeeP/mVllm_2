from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent.inference import (
    DEFAULT_MAX_REQUEST_SIZE,
    InferenceResult,
    LlamaFactoryInferenceClient,
    MockInferenceClient,
    _encode_video_to_data_url,
    _is_mp4_file,
    _redact_data_url,
    create_inference_client,
)
from agent.sampling import ClipBuildResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_FAKE_MP4_HEADER = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp41"


def _write_fake_mp4(path: Path, content: bytes = b"video-bytes") -> None:
    """Write a minimal ISO-BMFF ``ftyp`` box so MIME validation passes."""
    path.write_bytes(_FAKE_MP4_HEADER + content)


# ---------------------------------------------------------------------------
# MockInferenceClient
# ---------------------------------------------------------------------------
def test_mock_inference_client_returns_dict():
    client = MockInferenceClient({
        "has_fracture": True,
        "fracture_between": [17, 18],
        "type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": 0.92,
    })
    result = client.infer("any.mp4", "prompt")
    assert result.ok
    assert result.model_output is not None
    assert result.model_output["has_fracture"] is True
    assert result.model_output["type"] == "韧性断裂"


def test_mock_inference_client_parses_json_string():
    client = MockInferenceClient(
        '{"has_fracture": false, "fracture_between": null, "type": "未断裂", '
        '"location": null, "confidence": 0.6}'
    )
    result = client.infer("any.mp4", "prompt")
    assert result.ok
    assert result.model_output is not None
    assert result.model_output["has_fracture"] is False
    assert result.model_output["location"] is None
    assert result.model_output["confidence"] == pytest.approx(0.6)


def test_mock_inference_client_callable_response():
    def responder(video_input: str, prompt: str) -> dict:
        assert isinstance(video_input, str)
        return {
            "has_fracture": True,
            "fracture_between": [0, 1],
            "type": "脆性断裂",
            "location": "outside_gauge",
            "confidence": 0.8,
        }

    client = MockInferenceClient(responder)
    result = client.infer("clip.mp4", "analyze")
    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "脆性断裂"


def test_mock_inference_client_accepts_clip_build_result():
    clip = ClipBuildResult(path="/tmp/clip.mp4", manifest=[{"temp_index": 0}])

    def responder(video_input, prompt: str) -> dict:
        assert isinstance(video_input, ClipBuildResult)
        return {
            "has_fracture": False,
            "fracture_between": None,
            "type": "未断裂",
            "location": None,
            "confidence": 0.7,
        }

    client = MockInferenceClient(responder)
    result = client.infer(clip, "prompt")
    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "未断裂"


def test_mock_inference_client_invalid_response_returns_failure():
    client = MockInferenceClient("not valid json")
    result = client.infer("any.mp4", "prompt")
    assert not result.ok
    assert result.model_output is None
    assert result.error is not None
    assert result.attempts == 1


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def test_create_inference_client_mock_mode():
    with patch.dict("os.environ", {"INFERENCE_MOCK": "1"}):
        client = create_inference_client({})
        result = client.infer("any.mp4", "prompt")
        assert result.ok
        assert result.model_output is not None
        assert result.model_output["has_fracture"] is False
        assert result.model_output["type"] == "未断裂"
        assert result.model_output["location"] is None


# ---------------------------------------------------------------------------
# LlamaFactoryInferenceClient validation
# ---------------------------------------------------------------------------
def test_llama_factory_inference_client_missing_video():
    with patch("agent.inference.OpenAI"):
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(FileNotFoundError):
            client.infer("/nonexistent.mp4", "prompt")


def test_llama_factory_inference_client_rejects_non_mp4_extension(tmp_path: Path):
    with patch("agent.inference.OpenAI"):
        video = tmp_path / "fake.txt"
        video.write_text("content")
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(ValueError, match="Invalid or non-MP4"):
            client.infer(str(video), "prompt")


def test_llama_factory_inference_client_rejects_bad_mp4_signature(tmp_path: Path):
    with patch("agent.inference.OpenAI"):
        video = tmp_path / "fake.mp4"
        video.write_text("not a real mp4")
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(ValueError, match="Invalid or non-MP4"):
            client.infer(str(video), "prompt")


def test_llama_factory_inference_client_accepts_valid_mp4_signature(tmp_path: Path):
    video = tmp_path / "valid.mp4"
    _write_fake_mp4(video)
    assert _is_mp4_file(str(video)) is True


def test_llama_factory_inference_client_payload_too_large(tmp_path: Path):
    with patch("agent.inference.OpenAI"):
        video = tmp_path / "big.mp4"
        _write_fake_mp4(video, b"x" * 200)
        client = LlamaFactoryInferenceClient(
            model="minicpm-test", max_request_size=10
        )
        with pytest.raises(RuntimeError, match="exceeds"):
            client.infer(str(video), "prompt")


# ---------------------------------------------------------------------------
# Base64 request format
# ---------------------------------------------------------------------------
def test_llama_factory_inference_client_sends_base64(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    raw_content = b"video content"
    _write_fake_mp4(video, raw_content)

    captured: dict[str, Any] = {}

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        captured["model"] = model
        captured["messages"] = messages
        captured["extra_body"] = extra_body
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            '{"has_fracture": true, "fracture_between": [2, 3], '
            '"type": "韧性断裂", "location": "inside_gauge", "confidence": 0.95}'
        )
        return mock_completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze this")

    assert result.ok
    assert result.model_output is not None
    assert result.model_output["has_fracture"] is True
    assert result.model_output["confidence"] == pytest.approx(0.95)
    assert captured["model"] == "minicpm-test"

    # Message ordering: system first, then user with video_url before text.
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][1]["role"] == "user"
    user_content = captured["messages"][1]["content"]
    assert user_content[0]["type"] == "video_url"
    assert user_content[1]["type"] == "text"
    assert user_content[1]["text"] == "analyze this"

    url = user_content[0]["video_url"]["url"]
    assert url.startswith("data:video/mp4;base64,")
    encoded = url.split(",", 1)[1]
    assert base64.b64decode(encoded) == _FAKE_MP4_HEADER + raw_content
    assert captured["extra_body"] is None


def test_llama_factory_inference_client_clip_build_result_sends_manifest(
    tmp_path: Path,
):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    manifest = [{"temp_index": 0, "original_frame": 10, "timestamp": 1.0}]

    captured: dict[str, Any] = {}

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        captured["extra_body"] = extra_body
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            '{"has_fracture": false, "fracture_between": null, '
            '"type": "未断裂", "location": null, "confidence": 0.8}'
        )
        return mock_completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        clip = ClipBuildResult(path=str(video), manifest=manifest)
        result = client.infer(clip, "prompt")

    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "未断裂"
    assert captured["extra_body"] == {"preprocessing": {"temp_video_manifest": manifest}}


# ---------------------------------------------------------------------------
# Transport retry
# ---------------------------------------------------------------------------
def test_llama_factory_inference_client_transport_retry(tmp_path: Path, monkeypatch):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    class FakeRetryableError(Exception):
        status_code = 503

    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = (
        '{"has_fracture": false, "fracture_between": null, '
        '"type": "未断裂", "location": null, "confidence": 0.8}'
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        FakeRetryableError("server error"),
        mock_completion,
    ]

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "prompt")

    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "未断裂"
    assert mock_client.chat.completions.create.call_count == 2


def test_llama_factory_inference_client_exhausts_retries(tmp_path: Path, monkeypatch):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    class FakeRetryableError(Exception):
        status_code = 502

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        FakeRetryableError("err1"),
        FakeRetryableError("err2"),
        FakeRetryableError("err3"),
    ]

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(FakeRetryableError, match="err3"):
            client.infer(str(video), "prompt")

    # Initial attempt + 2 retries = 3 calls.
    assert mock_client.chat.completions.create.call_count == 3


def test_llama_factory_inference_client_non_retryable_error(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)

    class FakeAuthError(Exception):
        status_code = 401

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = FakeAuthError("unauthorized")

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(FakeAuthError, match="unauthorized"):
            client.infer(str(video), "prompt")

    assert mock_client.chat.completions.create.call_count == 1


# ---------------------------------------------------------------------------
# Model-output correction retries
# ---------------------------------------------------------------------------
def test_llama_factory_inference_client_correction_then_success(
    tmp_path: Path, monkeypatch
):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    calls: list[list[dict[str, Any]]] = []

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        calls.append(messages)
        completion = MagicMock()
        completion.choices = [MagicMock()]
        if len(calls) == 1:
            completion.choices[0].message.content = "not valid json"
        else:
            completion.choices[0].message.content = (
                '{"has_fracture": false, "fracture_between": null, '
                '"type": "未断裂", "location": null, "confidence": 0.7}'
            )
        return completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze")

    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "未断裂"
    assert result.attempts == 2
    assert len(calls) == 2
    # The original system prompt and video-bearing user message are preserved.
    assert calls[1][0]["role"] == "system"
    assert calls[1][1]["role"] == "user"
    assert any(item.get("type") == "video_url" for item in calls[1][1]["content"])
    # The correction turn appends the parser error details.
    assert calls[1][-1]["role"] == "user"
    assert "invalid_json" in calls[1][-1]["content"]


def test_llama_factory_inference_client_correction_exhausted(
    tmp_path: Path, monkeypatch
):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    def make_completion(content: str):
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = content
        return completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        make_completion("not valid json"),
        make_completion("{\"has_fracture\": true}"),
        make_completion("{\"unexpected\": 1}"),
    ]

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze")

    assert not result.ok
    assert result.model_output is None
    assert result.error is not None
    assert result.error.code == "invalid_model_output"
    assert result.attempts == 3
    assert mock_client.chat.completions.create.call_count == 3


# ---------------------------------------------------------------------------
# Sensitive information redaction
# ---------------------------------------------------------------------------
def test_redact_data_url():
    url = "data:video/mp4;base64," + "A" * 200
    redacted = _redact_data_url(url, max_plain=8)
    assert redacted.startswith("data:video/mp4;base64,AAAAAAAA")
    assert "[REDACTED:" in redacted
    assert "A" * 190 not in redacted


def test_logs_do_not_contain_full_base64(tmp_path: Path, caplog):
    video = tmp_path / "clip.mp4"
    secret = b"secret video bytes " * 10
    _write_fake_mp4(video, secret)
    data_url = _encode_video_to_data_url(str(video))

    with caplog.at_level(logging.INFO, logger="agent.inference"):
        logger = logging.getLogger("agent.inference")
        logger.info("payload preview: %s", _redact_data_url(data_url))

    assert data_url not in caplog.text
    assert base64.b64encode(secret).decode("ascii") not in caplog.text
    assert "[REDACTED:" in caplog.text


def test_client_repr_does_not_leak_api_key():
    with patch("agent.inference.OpenAI"):
        client = LlamaFactoryInferenceClient(
            model="m", api_key="super-secret-key"
        )
        representation = repr(client)
        assert "super-secret-key" not in representation
        assert "***REDACTED***" in representation


# ---------------------------------------------------------------------------
# Default constants sanity checks
# ---------------------------------------------------------------------------
def test_default_request_size_is_32_mib():
    assert DEFAULT_MAX_REQUEST_SIZE == 32 * 1024 * 1024
