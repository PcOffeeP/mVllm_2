"""Abstract protocol for the model inference client."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class InferenceClient(Protocol):
    """Protocol for clients that call the fine-tuned MiniCPM-V model."""

    def infer(self, video_path: str, prompt: str) -> dict:
        """Run inference on ``video_path`` with ``prompt`` and return parsed JSON."""
        ...
