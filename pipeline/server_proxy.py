"""Integrated LLaMA-Factory API with exact MiniCPM preprocessing evidence.

The service runs ChatModel in the same process and wraps the actual
``video_processor`` instance used by inference. It therefore returns the frame
table and tensor digest from that request's real model input, not a replay by a
second processor.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
from typing import Any

from pipeline.llamafactory_contract import configure_loaded_processor
from pipeline.server_adapter import wrap_response


MAX_VIDEO_BYTES = 100 * 1024 * 1024


def _extract_video_data_url(payload: dict[str, Any]) -> str:
    matches: list[str] = []
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        for item in message.get("content", []):
            if not isinstance(item, dict) or item.get("type") != "video_url":
                continue
            video_url = item.get("video_url")
            if isinstance(video_url, dict) and isinstance(video_url.get("url"), str):
                matches.append(video_url["url"])
    if len(matches) != 1:
        raise ValueError("request must contain exactly one video_url")
    return matches[0]


def _decode_mp4_data_url(data_url: str) -> bytes:
    prefix = "data:video/mp4;base64,"
    if not data_url.startswith(prefix):
        raise ValueError("video_url must be data:video/mp4;base64")
    try:
        media = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("video_url contains invalid base64") from exc
    if not media or len(media) > MAX_VIDEO_BYTES:
        raise ValueError("decoded video size is outside the allowed range")
    return media


def create_integrated_app(chat_model: Any, deployment_info: dict[str, Any]):
    """Create an API around the same ChatModel/processor that is captured."""
    os.environ["API_VERBOSE"] = "0"
    try:
        import asyncio
        from fastapi import FastAPI, HTTPException, Request
        from llamafactory.api.chat import create_chat_completion_response
        from llamafactory.api.protocol import ChatCompletionRequest
    except ImportError as exc:  # pragma: no cover - training-machine dependency
        raise RuntimeError("LLaMA-Factory and fastapi are required for the integrated service") from exc

    processor = chat_model.engine.processor
    capture = configure_loaded_processor(processor, capture=True)
    assert capture is not None
    processor_version = processor.__class__.__name__
    if deployment_info.get("processor_version") != processor_version:
        raise ValueError("deployment processor_version does not match the inference processor")
    if deployment_info.get("max_frames") != 8:
        raise ValueError("deployment max_frames must be 8")

    app = FastAPI(title="TensileAgent integrated MiniCPM service")
    inference_lock = asyncio.Lock()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: ChatCompletionRequest, raw_request: Request):
        api_key = os.getenv("API_KEY")
        if api_key and raw_request.headers.get("authorization") != f"Bearer {api_key}":
            raise HTTPException(status_code=401, detail="Invalid API key")
        if request.stream:
            raise HTTPException(status_code=400, detail="streaming is not supported by the evidence endpoint")
        try:
            async with inference_lock:
                capture.reset_capture()
                response = await create_chat_completion_response(request, chat_model)
                actual = capture.last_capture
            if actual is None:
                raise RuntimeError("actual inference video_processor call was not captured")
            frames = [
                {"index": frame["index"], "timestamp": frame["timestamp"]}
                for frame in actual["frames"]
            ]
            wrapped = wrap_response(response.model_dump(mode="json"), frames, deployment_info)
            wrapped["preprocessing"]["tensor_digest"] = actual["tensor_digest"]
            wrapped["preprocessing"]["tensor_shape"] = actual["tensor_shape"]
            return wrapped
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Integrated MiniCPM evidence service")
    parser.add_argument("--model", required=True)
    parser.add_argument("--deployment-manifest", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    # LLaMA-Factory defaults to logging the full request, including Base64.
    # The evidence service makes redaction the non-optional default.
    os.environ["API_VERBOSE"] = "0"
    deployment_info = json.loads(args.deployment_manifest.read_text(encoding="utf-8"))
    if any(str(value).startswith("REPLACE_") for value in deployment_info.values()):
        raise ValueError("deployment manifest still contains REPLACE_ placeholders")
    try:
        import uvicorn
        from llamafactory.chat import ChatModel
    except ImportError as exc:  # pragma: no cover - training-machine dependency
        raise RuntimeError("LLaMA-Factory and uvicorn are required") from exc
    chat_model = ChatModel({
        "model_name_or_path": args.model,
        "template": "minicpm_v",
        "infer_backend": "huggingface",
    })
    app = create_integrated_app(chat_model, deployment_info)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
