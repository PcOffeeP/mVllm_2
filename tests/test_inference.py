from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.inference import LlamaFactoryInferenceClient, MockInferenceClient, create_inference_client


def test_mock_inference_client_returns_dict():
    client = MockInferenceClient({
        "has_fracture": True,
        "fracture_between": [17, 18],
        "type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": 0.92,
    })
    result = client.infer("any.mp4", "prompt")
    assert result["has_fracture"] is True
    assert result["type"] == "韧性断裂"


def test_mock_inference_client_parses_json_string():
    client = MockInferenceClient(
        '{"has_fracture": false, "fracture_between": null, "type": "未断裂", "location": null, "confidence": 0.6}'
    )
    result = client.infer("any.mp4", "prompt")
    assert result["has_fracture"] is False
    assert result["location"] is None
    assert result["confidence"] == pytest.approx(0.6)


def test_mock_inference_client_callable_response():
    def responder(video_path: str, prompt: str):
        return {"has_fracture": True, "fracture_between": [0, 1], "type": "脆性断裂", "location": "outside_gauge", "confidence": 0.8}

    client = MockInferenceClient(responder)
    result = client.infer("clip.mp4", "analyze")
    assert result["type"] == "脆性断裂"


def test_mock_inference_client_invalid_response_returns_none():
    client = MockInferenceClient("not valid json")
    result = client.infer("any.mp4", "prompt")
    assert result is None


def test_create_inference_client_mock_mode():
    with patch.dict("os.environ", {"INFERENCE_MOCK": "1"}):
        client = create_inference_client({})
        result = client.infer("any.mp4", "prompt")
        assert result["has_fracture"] is False
        assert result["type"] == "未断裂"
        assert result["location"] is None


def test_llama_factory_inference_client_missing_video():
    with patch("agent.inference.OpenAI"):
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(FileNotFoundError):
            client.infer("/nonexistent.mp4", "prompt")


def test_llama_factory_inference_client_parses_response(tmp_path):
    video = tmp_path / "fake.mp4"
    video.write_text("not a real video but exists")

    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = '{"has_fracture": true, "fracture_between": [2, 3], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.95}'

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_completion

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "prompt")

    assert result["has_fracture"] is True
    assert result["confidence"] == pytest.approx(0.95)
    mock_client.chat.completions.create.assert_called_once()
