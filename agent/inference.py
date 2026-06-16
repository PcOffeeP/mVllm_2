"""Concrete inference client for the fine-tuned MiniCPM-V model.

The default implementation talks to an OpenAI-compatible LLaMA-Factory
endpoint.  It does **not** start the inference service automatically; callers
must either point ``base_url`` at a running server or supply a mock client for
testing.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Protocol, runtime_checkable

from agent.parser import ResultParser
from agent.prompts import SYSTEM_PROMPT

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    OpenAI = None


@runtime_checkable
class InferenceClient(Protocol):
    """Protocol for clients that call the fine-tuned MiniCPM-V model."""

    def infer(self, video_path: str, prompt: str) -> dict | None:
        """Run inference on ``video_path`` with ``prompt`` and return parsed JSON.

        Returns ``None`` when the model response cannot be parsed, per the
        contract in ``docs/model_agent_interface.md`` section 5.4.
        """
        ...


class LlamaFactoryInferenceClient:
    """OpenAI-compatible client for a running LLaMA-Factory inference endpoint.

    The client constructs a multi-modal message containing the system prompt,
    the user prompt with a ``<video>`` placeholder, and the local video file
    path.  The exact wire format follows LLaMA-Factory's OpenAI-compatible API
    conventions.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "EMPTY",
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.system_prompt = system_prompt
        if OpenAI is None:  # pragma: no cover - dependency guard
            raise ModuleNotFoundError(
                "LlamaFactoryInferenceClient requires the 'openai' package. "
                "Install it or use a mock InferenceClient for testing."
            )
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def infer(self, video_path: str, prompt: str) -> dict | None:
        """Call the model and return the parsed JSON output."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Inference video not found: {video_path}")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "video_url", "video_url": {"url": video_path}},
                ],
            },
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            max_tokens=512,
        )

        raw_text = response.choices[0].message.content or ""
        return ResultParser.parse(raw_text)


class MockInferenceClient:
    """Test-friendly inference client that returns a canned response.

    The ``response`` callable receives ``(video_path, prompt)`` and should
    return either a raw text string or a dict.  Dicts are returned as-is;
    strings are parsed by ``ResultParser``.  For strings, ``None`` is
    returned when the text cannot be parsed or does not satisfy the
    model-output schema.
    """

    def __init__(self, response: dict | str | Callable[..., Any]) -> None:
        self._response = response

    def infer(self, video_path: str, prompt: str) -> dict | None:
        if callable(self._response):
            raw = self._response(video_path, prompt)
        else:
            raw = self._response

        if isinstance(raw, dict):
            return raw

        return ResultParser.parse(raw)


def create_inference_client(config: dict[str, Any] | None = None) -> InferenceClient:
    """Factory for an ``InferenceClient`` from configuration.

    If ``INFERENCE_MOCK=1`` is set in the environment, a ``MockInferenceClient``
    returning a harmless negative result is created so that unit tests and
    offline development do not require a running inference server.
    """
    if os.getenv("INFERENCE_MOCK") == "1":
        return MockInferenceClient({
            "has_fracture": False,
            "fracture_between": None,
            "type": "未断裂",
            "location": "N/A",
            "confidence": 0.5,
        })

    cfg = config or {}
    backend_cfg = cfg.get("backend", {})
    model = backend_cfg.get("name", "minicpmv4_6")
    base_url = os.getenv("INFERENCE_BASE_URL", "http://localhost:8000/v1")
    api_key = os.getenv("INFERENCE_API_KEY", "EMPTY")
    return LlamaFactoryInferenceClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
