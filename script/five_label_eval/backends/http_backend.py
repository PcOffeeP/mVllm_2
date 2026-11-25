"""OpenAI-compatible ``POST /v1/chat/completions`` HTTP inference backend.

Sends ordered L3 PNG frames as ``data:image/png;base64,...`` image URLs plus the
verbatim prompt text (no stripping, no ``<answer>`` unwrapping, no candidate ID
or filesystem path leakage). Enforces a true cancellable end-to-end wall-clock
deadline covering connection, trickling headers, and trickling response bodies.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..score import InputError
from . import InferenceRequest, InferenceResult, normalize_result, sanitize_base_url


class _WallClockTimeout(Exception):
    """Internal sentinel raised when the end-to-end request deadline expires."""


def _resolve_completions_url(endpoint: str) -> str:
    cleaned = endpoint.strip() if isinstance(endpoint, str) else ""
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise InputError(f"http endpoint must start with http:// or https://, got {endpoint!r}")
    parts = urlsplit(cleaned)
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        new_path = path
    elif path.endswith("/v1"):
        new_path = f"{path}/chat/completions"
    else:
        new_path = f"{path}/v1/chat/completions"
    return urlunsplit((parts.scheme, parts.netloc, new_path, "", ""))


def _encode_png_bytes_data_url(raw: bytes) -> str:
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _encode_png_data_url(path: Path) -> str:
    return _encode_png_bytes_data_url(path.read_bytes())


class HttpBackend:
    """Thin OpenAI-compatible HTTP backend testable offline via MockTransport or loopback."""

    backend_name = "http"

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        api_model_name: str | None = None,
        api_key_env: str | None = None,
        timeout_seconds: float = 600.0,
        temperature: float = 0.0,
        max_tokens: int = 512,
        seed: int | None = None,
        max_pixels: int | None = None,
        sampling_policy: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not isinstance(model_id, str) or not model_id.strip():
            raise InputError("http backend requires a non-empty model_id")
        if model_id.strip() == "fake":
            raise InputError("http backend refuses --model-id fake")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise InputError(f"timeout_seconds must be positive, got {timeout_seconds!r}")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise InputError(f"max_tokens must be a positive integer, got {max_tokens!r}")
        if max_pixels is not None and (isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels <= 0):
            raise InputError(f"max_pixels must be a positive integer when set, got {max_pixels!r}")

        self.endpoint = endpoint.strip()
        self.completions_url = _resolve_completions_url(self.endpoint)
        self.model_id = model_id
        self.api_model_name = (api_model_name or model_id).strip()
        self.api_key_env = api_key_env.strip() if isinstance(api_key_env, str) and api_key_env.strip() else None
        self._api_key: str | None = None
        if self.api_key_env is not None:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise InputError(f"API key env var {self.api_key_env!r} is not set or empty")
            self._api_key = key

        self.timeout_seconds = float(timeout_seconds)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.seed = seed
        self.max_pixels = max_pixels
        self.sampling_policy = dict(sampling_policy) if isinstance(sampling_policy, dict) else None
        self.extra_body = dict(extra_body) if isinstance(extra_body, dict) else None

        self._transport = transport
        self._external_client = client

    def run_identity(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model_id": self.model_id,
            "api_model_name": self.api_model_name,
            "base_url": sanitize_base_url(self.endpoint),
            "completions_url": sanitize_base_url(self.completions_url),
            "api_key_env": self.api_key_env,
            "max_pixels": self.max_pixels,
            "sampling_policy": self.sampling_policy,
            "timeout_seconds": self.timeout_seconds,
            "decode_config": {
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "seed": self.seed,
            },
            "output_unwrapping": "none",
        }

    def build_payload(self, request: InferenceRequest) -> dict[str, Any]:
        """Build an OpenAI-compatible multimodal chat payload with zero metadata leakage."""
        if request.frame_bytes is not None:
            image_urls = [_encode_png_bytes_data_url(raw) for raw in request.frame_bytes]
        else:
            image_urls = [_encode_png_data_url(path) for path in request.frame_paths]
        content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": url}}
            for url in image_urls
        ]
        # Preserve prompt text verbatim (no strip).
        content.append({"type": "text", "text": request.prompt_text})

        decode = request.decode_config or {}
        payload: dict[str, Any] = {
            "model": self.api_model_name,
            "messages": [{"role": "user", "content": content}],
            "temperature": decode.get("temperature", self.temperature),
            "max_tokens": decode.get("max_tokens", self.max_tokens),
        }
        seed = decode.get("seed", self.seed)
        if seed is not None:
            payload["seed"] = seed
        if self.max_pixels is not None:
            # Forward max_pixels to OpenAI-compatible vLLM/SGLang servers so the
            # recorded run_identity pixel budget is actively sent in the request.
            payload["mm_processor_kwargs"] = {"max_pixels": self.max_pixels}
        if self.extra_body:
            payload.update(self.extra_body)
        return payload

    def _execute_with_wall_clock_deadline(
        self,
        request_url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        """Execute streaming POST under a true cancellable wall-clock deadline.

        Even if a server trickles response header bytes or chunked body bytes faster than
        per-read timeouts, the wall-clock deadline fires on time, closes the active
        client/connection to abort the in-flight socket, and raises ``_WallClockTimeout``.
        """
        deadline = time.monotonic() + timeout
        cancel_event = threading.Event()
        outcome: dict[str, Any] = {}
        active_client = (
            self._external_client
            if self._external_client is not None
            else httpx.Client(transport=self._transport, trust_env=False)
        )
        owns_client = self._external_client is None
        active_response: list[httpx.Response] = []

        def _worker() -> None:
            try:
                with active_client.stream(
                    "POST",
                    request_url,
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(timeout),
                ) as response:
                    active_response.append(response)
                    if cancel_event.is_set() or time.monotonic() > deadline:
                        raise _WallClockTimeout("request exceeded wall-clock deadline after headers")
                    chunks: list[bytes] = []
                    for chunk in response.iter_bytes():
                        if cancel_event.is_set() or time.monotonic() > deadline:
                            raise _WallClockTimeout("request exceeded wall-clock deadline while reading body")
                        chunks.append(chunk)
                    outcome["result"] = (response.status_code, b"".join(chunks))
            except BaseException as exc:  # noqa: BLE001
                outcome["error"] = exc
            finally:
                if owns_client:
                    try:
                        active_client.close()
                    except Exception:  # noqa: BLE001
                        pass

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        worker.join(timeout=timeout)
        if worker.is_alive():
            cancel_event.set()
            # Actively abort the in-flight stream/connection so the peer sees cancellation.
            if active_response:
                try:
                    active_response[0].close()
                except Exception:  # noqa: BLE001
                    pass
            if owns_client:
                try:
                    active_client.close()
                except Exception:  # noqa: BLE001
                    pass
            raise _WallClockTimeout(f"request exceeded wall-clock deadline of {timeout:.3f}s")

        if "error" in outcome:
            raise outcome["error"]
        if "result" not in outcome:
            raise _WallClockTimeout(f"request terminated without result within {timeout:.3f}s")
        return outcome["result"]

    def infer_one(self, request: InferenceRequest) -> InferenceResult:
        started = time.monotonic()
        timeout = float(request.timeout_seconds if request.timeout_seconds is not None else self.timeout_seconds)
        try:
            payload = self.build_payload(request)
        except OSError as exc:
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=time.monotonic() - started,
                error_detail=f"failed to read L3 frame image: {exc}",
            )

        headers = {"Content-Type": "application/json"}
        request_url = self.completions_url
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
            # Strip any embedded URL userinfo so httpx does not overwrite Bearer auth with Basic auth.
            request_url = sanitize_base_url(self.completions_url)

        try:
            status_code, body_bytes = self._execute_with_wall_clock_deadline(
                request_url, payload, headers, timeout
            )
        except (_WallClockTimeout, httpx.TimeoutException) as exc:
            return InferenceResult(
                status="timeout",
                raw_output=None,
                latency_seconds=time.monotonic() - started,
                error_detail=f"timeout after {time.monotonic() - started:.3f}s: {exc}",
            )
        except (httpx.HTTPError, OSError) as exc:
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=time.monotonic() - started,
                error_detail=f"transport error: {exc}",
            )

        elapsed = time.monotonic() - started
        if not 200 <= status_code < 300:
            preview = body_bytes.decode("utf-8", errors="replace")[:300]
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=elapsed,
                error_detail=f"HTTP {status_code}: {preview}",
                extra_meta={"http_status": status_code},
            )

        try:
            data = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=elapsed,
                error_detail=f"invalid JSON response: {exc}",
            )

        if not isinstance(data, dict):
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=elapsed,
                error_detail="response JSON top-level is not an object",
            )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=elapsed,
                error_detail="response JSON missing non-empty choices[0]",
            )
        message = choices[0].get("message")
        if not isinstance(message, dict):
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=elapsed,
                error_detail="response JSON choices[0].message is not an object",
            )

        content = message.get("content")
        reasoning_content = message.get("reasoning_content")
        if not isinstance(reasoning_content, str):
            reasoning_content = None

        # Strict single-JSON contract: NEVER strip fences or unwrap <answer> tags.
        if not isinstance(content, str) or content == "":
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=elapsed,
                error_detail="response choices[0].message.content is empty or non-string",
                reasoning_content=reasoning_content,
            )

        extra_meta: dict[str, Any] = {}
        if isinstance(data.get("usage"), dict):
            extra_meta["usage"] = data["usage"]
        if isinstance(choices[0].get("finish_reason"), str):
            extra_meta["finish_reason"] = choices[0]["finish_reason"]

        return normalize_result(
            InferenceResult(
                status="success",
                raw_output=content,
                latency_seconds=elapsed,
                reasoning_content=reasoning_content,
                extra_meta=extra_meta,
            )
        )

    def close(self) -> None:
        return None
