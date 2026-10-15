"""Integrated MiniCPM service for the pinned ``tensile-vlm/v2`` contract."""

from __future__ import annotations

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
from pipeline.output_normalizer import normalize_structured_output, validate_structured_output
from pipeline.production_contract import load_production_contract
from pipeline.server_adapter import wrap_response
from pipeline.v4_1_labels import canonicalize_v4_1_labels
from pipeline.v4_1_production_contract import load_v4_1_production_contract


MAX_VIDEO_BYTES = 100 * 1024 * 1024
STARTUP_FIELDS = {
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
logger = logging.getLogger(__name__)


def _chat_model_args(model: str) -> dict[str, Any]:
    return {
        "model_name_or_path": model,
        "template": "minicpm_v",
        "infer_backend": "huggingface",
        "trust_remote_code": True,
        "do_sample": False,
        "num_beams": 1,
        "temperature": 0.0,
        "max_new_tokens": 256,
    }


def _validate_startup_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or set(config) != STARTUP_FIELDS:
        raise ValueError("deployment startup config must contain exactly the required 10 fields")
    if config.get("max_frames") != 8 or isinstance(config.get("max_frames"), bool):
        raise ValueError("deployment max_frames must be exactly 8")
    invalid = sorted(
        key
        for key in STARTUP_FIELDS - {"max_frames"}
        if not isinstance(config.get(key), str)
        or not config[key].strip()
        or config[key].strip().lower() == "unknown"
        or config[key].startswith("REPLACE_")
    )
    if invalid:
        raise ValueError("deployment startup config has invalid fields: " + ", ".join(invalid))
    return dict(config)


def _deployment_snapshot(
    config: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> dict[str, str]:
    contract = contract or load_production_contract()
    contract_hash = str(contract["contract_hash"])
    return {
        key: str(config[key])
        for key in sorted(STARTUP_FIELDS - {"max_frames"})
    } | {
        "contract_version": str(contract["contract_version"]),
        "contract_hash": contract_hash,
    }


def _extract_video_data_url(payload: dict[str, Any]) -> str:
    matches: list[str] = []
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
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
    replaced = 0
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "video_url":
                continue
            item["video_url"] = {"url": replacement}
            replaced += 1
    if replaced != 1:
        raise ValueError("request must contain exactly one video_url")


def _request_mode(payload: dict[str, Any], contract: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise ValueError("request must contain exactly one system and one user message")
    system, user = messages
    if not isinstance(system, dict) or set(system) != {"role", "content"}:
        raise ValueError("system message is invalid")
    if system.get("role") != "system" or not isinstance(system.get("content"), str):
        raise ValueError("system message is invalid")
    if not isinstance(user, dict) or set(user) != {"role", "content"} or user.get("role") != "user":
        raise ValueError("user message is invalid")
    content = user.get("content")
    if not isinstance(content, list) or len(content) != 2:
        raise ValueError("user message must contain one video and one fixed text item")
    videos = [item for item in content if isinstance(item, dict) and item.get("type") == "video_url"]
    texts = [item for item in content if isinstance(item, dict) and item.get("type") == "text"]
    if len(videos) != 1 or len(texts) != 1 or set(texts[0]) != {"type", "text"}:
        raise ValueError("user message must contain one video and one fixed text item")
    system_text = system["content"]
    user_text = texts[0].get("text")
    for mode in ("analysis", "evidence"):
        section = contract[mode]
        if system_text == section["system_prompt"] and user_text == section["user_prompt"]:
            return mode
    raise ValueError("request prompts do not match the production contract")


def _fixed_payload(
    payload: dict[str, Any],
    mode: str,
    contract: dict[str, Any],
    video_path: str,
    previous_output: str | None = None,
) -> dict[str, Any]:
    section = contract[mode]
    user_content = [
        {"type": "video_url", "video_url": {"url": video_path}},
        {"type": "text", "text": section["user_prompt"]},
    ]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": section["system_prompt"]},
        {"role": "user", "content": user_content},
    ]
    if previous_output is not None:
        messages.extend(
            [
                {"role": "assistant", "content": previous_output},
                {"role": "user", "content": section["retry_prompt"]},
            ]
        )
    generation = section["generation"]
    return {
        "model": payload.get("model"),
        "messages": messages,
        "stream": False,
        "do_sample": generation["do_sample"],
        "temperature": generation["temperature"],
        "max_tokens": generation["max_new_tokens"],
    }


def _assistant_content(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        return ""
    return str(getattr(choices[0].message, "content", "") or "")


def _analysis_output_valid(
    content: str,
    frame_count: int = 8,
    *,
    contract_version: str = "tensile-vlm/v2",
) -> bool:
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    if contract_version == "tensile-vlm/v4.1":
        try:
            canonicalize_v4_1_labels(raw)
        except (TypeError, ValueError):
            return False
        return True
    if contract_version != "tensile-vlm/v2":
        return False
    if not isinstance(raw, dict) or set(raw) != {
        "has_fracture",
        "fracture_between",
        "type",
        "location",
    }:
        return False
    normalized, repairs = normalize_structured_output(raw, frame_count)
    return not repairs and raw == normalized and validate_structured_output(normalized, frame_count)


def _describe_mm_value(value: Any) -> str:
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
            result.pop("skip_image_idx")
        logger.info(
            "MiniCPM mm input shapes: %s",
            {key: _describe_mm_value(value) for key, value in result.items()},
        )
        return result

    plugin.get_mm_inputs = wrapped
    plugin._get_video_sample_indices = wrapped_get_video_sample_indices


def create_integrated_app(
    chat_model: Any,
    startup_config: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
    service_binding: dict[str, Any] | None = None,
):
    os.environ["API_VERBOSE"] = "0"
    try:
        import asyncio
        from fastapi import FastAPI, HTTPException, Request
        from llamafactory.api.chat import create_chat_completion_response
        from llamafactory.api.common import SAFE_MEDIA_PATH
        from llamafactory.api.protocol import ChatCompletionRequest
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("LLaMA-Factory and fastapi are required for the integrated service") from exc

    config = _validate_startup_config(startup_config)
    contract = contract or load_production_contract()
    deployment = _deployment_snapshot(config, contract)
    public_binding = {key: value for key, value in (service_binding or {}).items()
                      if key not in {"model_path", "adapter_path", "base_model_version"}}
    processor = chat_model.engine.processor
    capture = configure_loaded_processor(processor, capture=True)
    assert capture is not None
    _install_mm_shape_diagnostics(chat_model, capture)
    if config["processor_version"] != processor.__class__.__name__:
        raise ValueError("deployment processor_version does not match the inference processor")

    app = FastAPI(title="TensileAgent integrated MiniCPM service")
    inference_lock = asyncio.Lock()

    def authorize(raw_request: Request) -> None:
        api_key = os.getenv("API_KEY")
        if api_key and raw_request.headers.get("authorization") != f"Bearer {api_key}":
            raise HTTPException(status_code=401, detail="Invalid API key")

    async def contract_preflight(raw_request):
        authorize(raw_request)
        return {
            "contract_version": contract["contract_version"],
            "contract_hash": contract["contract_hash"],
            "deployment_manifest": dict(deployment),
            "model_registry": dict(public_binding),
            "capabilities": {"analysis": True, "evidence": True},
        }

    async def chat_completions(raw_request):
        authorize(raw_request)
        temp_video_path: str | None = None
        try:
            payload = await raw_request.json()
            if not isinstance(payload, dict) or payload.get("stream") not in (None, False):
                raise ValueError("streaming is not supported")
            mode = _request_mode(payload, contract)
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

            response: Any = None
            actual: dict[str, Any] | None = None
            previous_output: str | None = None
            max_attempts = 3 if mode == "analysis" else 1
            async with inference_lock:
                for _attempt in range(max_attempts):
                    request_payload = _fixed_payload(
                        payload,
                        mode,
                        contract,
                        temp_video_path,
                        previous_output=previous_output,
                    )
                    request = ChatCompletionRequest.model_validate(request_payload)
                    capture.reset_capture(temp_video_path)
                    response = await create_chat_completion_response(request, chat_model)
                    actual = capture.last_capture
                    content = _assistant_content(response)
                    if mode == "evidence" or _analysis_output_valid(
                        content,
                        contract_version=str(contract["contract_version"]),
                    ):
                        break
                    previous_output = content
            if response is None or actual is None:
                raise RuntimeError("inference processor evidence was not captured")
            frames = [
                {"index": frame["index"], "timestamp": frame["timestamp"]}
                for frame in actual["frames"]
            ]
            wrapped = wrap_response(
                response.model_dump(mode="json"),
                frames,
                deployment,
                contract=contract,
            )
            wrapped["preprocessing"]["tensor_digest"] = actual["tensor_digest"]
            wrapped["preprocessing"]["tensor_shape"] = actual["tensor_shape"]
            wrapped["preprocessing"]["model_registry"] = dict(public_binding)
            return wrapped
        except HTTPException:
            raise
        except ValueError as exc:
            logger.warning("Rejected MiniCPM request: %s", type(exc).__name__)
            raise HTTPException(status_code=422, detail="Invalid tensile inference request") from exc
        except Exception as exc:
            logger.error("MiniCPM request failed: %s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="Tensile inference failed") from exc
        finally:
            if temp_video_path is not None:
                Path(temp_video_path).unlink(missing_ok=True)

    # ``Request`` is imported lazily inside this factory. With postponed
    # annotations, older FastAPI versions cannot resolve a local ``Request``
    # symbol while registering a decorated route and treat it as a query
    # parameter instead. Attach the concrete runtime annotation before route
    # registration so both old and new FastAPI releases inject the request.
    contract_preflight.__annotations__["raw_request"] = Request
    chat_completions.__annotations__["raw_request"] = Request
    app.add_api_route("/v1/tensile/contract", contract_preflight, methods=["GET"])
    app.add_api_route("/v1/chat/completions", chat_completions, methods=["POST"])

    return app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Integrated MiniCPM tensile VLM service")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--alias", choices=("candidate", "production"), required=True)
    parser.add_argument("--service-mode", choices=("development", "production"), required=True)
    parser.add_argument("--deployment-manifest", type=Path, required=True)
    parser.add_argument(
        "--contract-version",
        choices=("tensile-vlm/v2", "tensile-vlm/v4.1"),
        required=True,
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    from pipeline.model_registry import resolve_service_model, bind_service_contract
    from versioning.ids import parse_model_id
    binding = resolve_service_model(args.root, alias=args.alias, service_mode=args.service_mode)
    if "tensile-vlm/" + parse_model_id(binding["model_version"]).protocol != args.contract_version:
        raise ValueError("registered model protocol does not match the service contract")
    os.environ["API_VERBOSE"] = "0"
    startup_config = json.loads(args.deployment_manifest.read_text(encoding="utf-8"))
    _validate_startup_config(startup_config)
    for field, expected in {"model_version": binding["model_version"],
        "adapter_version": binding["model_version"], "base_model_version": binding["base_model_version"],
        "config_fingerprint": binding["fingerprint"]}.items():
        if startup_config[field] != expected:
            raise ValueError(f"deployment {field} does not match qualified Registry binding")
    contract = (
        load_v4_1_production_contract()
        if args.contract_version == "tensile-vlm/v4.1"
        else load_production_contract()
    )
    contract = bind_service_contract(contract, binding)
    try:
        import uvicorn
        from llamafactory.chat import ChatModel
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("LLaMA-Factory and uvicorn are required") from exc
    model_args = _chat_model_args(binding["model_path"])
    if binding.get("evaluation_runtime") is not None:
        runtime = binding["evaluation_runtime"]
        model_args.update({key: runtime["generation"][key] for key in ("do_sample", "num_beams", "max_new_tokens")})
        if runtime["generation"]["video_max_frames"] != 8:
            raise ValueError("service frame configuration differs from qualified performance")
        if runtime["quantization_bit"] is not None:
            model_args["quantization_bit"] = runtime["quantization_bit"]
            model_args.update(double_quantization=runtime["runtime_variant"]["quantization"]["double_quant"],
                quantization_type=runtime["runtime_variant"]["quantization"]["quant_type"])
        model_args.update(infer_dtype=runtime["runtime_variant"]["dtype"],
            device_map=runtime["device"]["runtime_device"])
        if (startup_config["runtime_device"] != runtime["device"]["runtime_device"] or
            startup_config["runtime_dtype"] != runtime["runtime_variant"]["dtype"]):
            raise ValueError("service runtime device differs from qualified performance")
    if binding["adapter_path"] is not None:
        model_args["adapter_name_or_path"] = binding["adapter_path"]
    chat_model = ChatModel(model_args)
    if binding.get("evaluation_runtime") is not None:
        actual = chat_model.engine.model
        runtime = binding["evaluation_runtime"]
        from versioning.performance import validate_loaded_runtime
        validate_loaded_runtime(actual, runtime)
    if resolve_service_model(args.root, alias=args.alias, service_mode=args.service_mode) != binding:
        raise ValueError("Registry or model content changed while loading")
    app = create_integrated_app(chat_model, startup_config, contract=contract, service_binding=binding)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
