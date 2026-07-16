"""Integrated LLaMA-Factory API with exact MiniCPM preprocessing evidence.

The service runs ChatModel in the same process and wraps the actual
``video_processor`` instance used by inference. It therefore returns the frame
table and tensor digest from that request's real model input, not a replay by a
second processor.
"""

import argparse
import base64
import binascii
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from pipeline.llamafactory_contract import configure_loaded_processor
from pipeline.server_adapter import wrap_response


MAX_VIDEO_BYTES = 100 * 1024 * 1024
logger = logging.getLogger(__name__)


def _chat_model_args(model: str) -> dict[str, Any]:
    """Return the fixed LLaMA-Factory settings required by MiniCPM-V."""
    return {
        "model_name_or_path": model,
        "template": "minicpm_v",
        "infer_backend": "huggingface",
        "trust_remote_code": True,
    }


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


def _replace_video_url(payload: dict[str, Any], replacement: str) -> None:
    """Replace the single validated video URL in an OpenAI request payload."""
    replaced = 0
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "video_url":
                continue
            item["video_url"] = {"url": replacement}
            replaced += 1
    if replaced != 1:
        raise ValueError("request must contain exactly one video_url")


def _describe_mm_value(value: Any) -> str:
    """Return shape-only diagnostics for a multimodal processor value."""
    shape = getattr(value, "shape", None)
    if shape is not None:
        return f"{type(value).__name__}(shape={tuple(shape)})"
    if isinstance(value, list):
        first = value[0] if value else None
        first_shape = getattr(first, "shape", None)
        if first_shape is not None:
            return f"list(len={len(value)}, first_shape={tuple(first_shape)})"
        if isinstance(first, list):
            return f"list(len={len(value)}, first_list_len={len(first)})"
        return f"list(len={len(value)}, first_type={type(first).__name__})"
    return type(value).__name__


def _install_mm_shape_diagnostics(chat_model: Any, capture: Any) -> None:
    """Capture plugin frame indices and normalize pinned MiniCPM inputs."""
    plugin = chat_model.engine.template.mm_plugin
    original = plugin.get_mm_inputs
    original_get_video_sample_indices = plugin._get_video_sample_indices

    def wrapped_get_video_sample_indices(stream: Any, *args: Any, **kwargs: Any) -> list[int]:
        sample_indices = original_get_video_sample_indices(stream, *args, **kwargs)
        capture.record_selected_indices(list(sample_indices))
        return sample_indices

    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original(*args, **kwargs)
        skip_image_idx = result.get("skip_image_idx")
        if (
            isinstance(skip_image_idx, list)
            and skip_image_idx
            and all(isinstance(item, list) and not item for item in skip_image_idx)
        ):
            # LLaMA-Factory 4447137 indexes nested MiniCPM lists before
            # checking whether the inner list is empty. MiniCPM-V 4.5 also
            # rejects this unused generation kwarg, so omit it only when every
            # batch member has an empty skip list.
            result.pop("skip_image_idx")
        logger.info(
            "MiniCPM mm input shapes: %s",
            {key: _describe_mm_value(value) for key, value in result.items()},
        )
        return result

    plugin.get_mm_inputs = wrapped
    plugin._get_video_sample_indices = wrapped_get_video_sample_indices


def create_integrated_app(chat_model: Any, deployment_info: dict[str, Any]):
    """Create an API around the same ChatModel/processor that is captured."""
    os.environ["API_VERBOSE"] = "0"
    try:
        import asyncio
        from fastapi import FastAPI, HTTPException, Request
        from llamafactory.api.chat import create_chat_completion_response
        from llamafactory.api.common import SAFE_MEDIA_PATH
        from llamafactory.api.protocol import ChatCompletionRequest
    except ImportError as exc:  # pragma: no cover - training-machine dependency
        raise RuntimeError("LLaMA-Factory and fastapi are required for the integrated service") from exc

    processor = chat_model.engine.processor
    capture = configure_loaded_processor(processor, capture=True)
    assert capture is not None
    _install_mm_shape_diagnostics(chat_model, capture)
    processor_version = processor.__class__.__name__
    if deployment_info.get("processor_version") != processor_version:
        raise ValueError("deployment processor_version does not match the inference processor")
    if deployment_info.get("max_frames") != 8:
        raise ValueError("deployment max_frames must be 8")

    app = FastAPI(title="TensileAgent integrated MiniCPM service")
    inference_lock = asyncio.Lock()

    @app.post("/v1/chat/completions")
    async def chat_completions(raw_request: Request):
        api_key = os.getenv("API_KEY")
        if api_key and raw_request.headers.get("authorization") != f"Bearer {api_key}":
            raise HTTPException(status_code=401, detail="Invalid API key")
        temp_video_path: str | None = None
        try:
            # ChatCompletionRequest is imported inside this factory because the
            # local development machine does not install LLaMA-Factory. Parsing
            # explicitly also avoids FastAPI resolving that local annotation as
            # an incomplete forward reference on newer Pydantic releases.
            payload = await raw_request.json()
            media = _decode_mp4_data_url(_extract_video_data_url(payload))
            Path(SAFE_MEDIA_PATH).mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="tensile_",
                suffix=".mp4",
                dir=SAFE_MEDIA_PATH,
                delete=False,
            ) as temp_video:
                temp_video.write(media)
                temp_video_path = temp_video.name
            _replace_video_url(payload, temp_video_path)
            request = ChatCompletionRequest.model_validate(payload)
            if request.stream:
                raise HTTPException(status_code=400, detail="streaming is not supported by the evidence endpoint")
            async with inference_lock:
                capture.reset_capture(temp_video_path)
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
            logger.exception("MiniCPM request failed after media localization")
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if temp_video_path is not None:
                Path(temp_video_path).unlink(missing_ok=True)

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
    chat_model = ChatModel(_chat_model_args(args.model))
    app = create_integrated_app(chat_model, deployment_info)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
