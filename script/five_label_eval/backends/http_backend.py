"""OpenAI-compatible ``POST /v1/chat/completions`` HTTP inference backend.

Sends ordered L3 PNG frames as ``data:image/png;base64,...`` image URLs plus the
verbatim prompt text (no stripping, no ``<answer>`` unwrapping, no candidate ID
or filesystem path leakage). Enforces a true cancellable end-to-end wall-clock
deadline covering connection, trickling headers, and trickling response bodies.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..score import InputError
from . import InferenceRequest, InferenceResult, normalize_result, sanitize_base_url

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class _WallClockTimeout(Exception):
    """Internal sentinel raised when the end-to-end request deadline expires."""


class _ResponseTooLargeError(Exception):
    """Internal sentinel raised when an HTTP response exceeds MAX_RESPONSE_BYTES."""


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    lowered = host.strip().lower().rstrip(".")
    if lowered == "localhost":
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def _resolve_completions_url(endpoint: str) -> str:
    cleaned = endpoint.strip() if isinstance(endpoint, str) else ""
    try:
        parts = urlsplit(cleaned)
        scheme = parts.scheme.lower()
        host = parts.hostname
        _ = parts.port
    except ValueError:
        raise InputError("http endpoint is not a valid http:// or https:// URL") from None
    if scheme not in ("http", "https") or not host:
        safe_hint = sanitize_base_url(cleaned) if cleaned else "<empty>"
        raise InputError(
            f"http endpoint must be a valid http:// or https:// URL with hostname "
            f"(got scheme={scheme or '<none>'!r}, target={safe_hint!r})"
        )
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        new_path = path
    elif path.endswith("/v1"):
        new_path = f"{path}/chat/completions"
    else:
        new_path = f"{path}/v1/chat/completions"
    return urlunsplit((scheme, parts.netloc, new_path, "", ""))


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
            if any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
                raise InputError(
                    f"API key in env var {self.api_key_env!r} contains illegal whitespace or control characters"
                )
            self._api_key = key

        parsed_endpoint = urlsplit(self.completions_url)
        has_credentials = self._api_key is not None or parsed_endpoint.username is not None or parsed_endpoint.password is not None
        if parsed_endpoint.scheme == "http" and has_credentials and not _is_loopback_host(parsed_endpoint.hostname):
            raise InputError(
                "refusing to send authentication credentials over plaintext http:// to a non-loopback host; use https://"
            )

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

        For real network requests (no injected sync ``MockTransport``/``Client``), runs an
        async ``httpx.AsyncClient`` request wrapped in ``asyncio.wait_for(..., timeout)`` so
        DNS resolution, connection, upload, trickling headers, and trickling body are all
        cancelled cleanly on deadline expiry and the socket is closed immediately.
        """
        if self._external_client is not None or self._transport is not None:
            deadline = time.monotonic() + timeout
            client = (
                self._external_client
                if self._external_client is not None
                else httpx.Client(transport=self._transport, trust_env=False)
            )
            owns = self._external_client is None
            try:
                with client.stream(
                    "POST",
                    request_url,
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(timeout),
                ) as response:
                    if time.monotonic() > deadline:
                        raise _WallClockTimeout("request exceeded wall-clock deadline after headers")
                    chunks: list[bytes] = []
                    total_bytes = 0
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline:
                            raise _WallClockTimeout("request exceeded wall-clock deadline while reading body")
                        total_bytes += len(chunk)
                        if total_bytes > MAX_RESPONSE_BYTES:
                            raise _ResponseTooLargeError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
                        chunks.append(chunk)
                    return response.status_code, b"".join(chunks)
            finally:
                if owns:
                    client.close()

        # Pre-resolve non-IP hostnames inside a plain daemon thread (outside asyncio's
        # default ThreadPoolExecutor) so a stalled getaddrinfo() never blocks Python
        # process exit at atexit after the wall-clock deadline expires.
        started_mono = time.monotonic()
        url_parts = urlsplit(request_url)
        host = url_parts.hostname
        if host and not _is_loopback_host(host):
            try:
                ipaddress.ip_address(host)
                needs_dns = False
            except ValueError:
                needs_dns = True
            if needs_dns:
                port = url_parts.port or (443 if url_parts.scheme == "https" else 80)
                dns_err: list[BaseException] = []

                def _resolve_dns() -> None:
                    try:
                        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                    except BaseException as exc:  # noqa: BLE001
                        dns_err.append(exc)

                dns_thread = threading.Thread(target=_resolve_dns, daemon=True)
                dns_thread.start()
                dns_thread.join(timeout=timeout)
                if dns_thread.is_alive():
                    raise _WallClockTimeout(f"request exceeded wall-clock deadline of {timeout:.3f}s")
                if dns_err:
                    raise dns_err[0]

        remaining = timeout - (time.monotonic() - started_mono)
        if remaining <= 0:
            raise _WallClockTimeout(f"request exceeded wall-clock deadline of {timeout:.3f}s")

        async def _async_post() -> tuple[int, bytes]:
            async with httpx.AsyncClient(trust_env=False) as client:
                async with client.stream(
                    "POST",
                    request_url,
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(remaining),
                ) as response:
                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > MAX_RESPONSE_BYTES:
                            raise _ResponseTooLargeError(f"response exceeded {MAX_RESPONSE_BYTES} bytes")
                        chunks.append(chunk)
                    return response.status_code, b"".join(chunks)

        result_box: list[tuple[int, bytes]] = []
        error_box: list[BaseException] = []

        def _worker() -> None:
            try:
                result_box.append(asyncio.run(asyncio.wait_for(_async_post(), timeout=remaining)))
            except BaseException as exc:  # noqa: BLE001
                error_box.append(exc)

        worker = threading.Thread(target=_worker, daemon=True)
        worker.start()
        worker.join(timeout=remaining + 0.05)
        if worker.is_alive():
            raise _WallClockTimeout(f"request exceeded wall-clock deadline of {timeout:.3f}s")
        if error_box:
            exc = error_box[0]
            if isinstance(exc, asyncio.TimeoutError):
                raise _WallClockTimeout(f"request exceeded wall-clock deadline of {timeout:.3f}s") from exc
            raise exc
        return result_box[0]

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
        except (_ResponseTooLargeError, httpx.HTTPError, OSError) as exc:
            # Record only the safe exception class name to prevent header/credential echo in metadata.
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=time.monotonic() - started,
                error_detail=f"transport error: {type(exc).__name__}",
            )

        elapsed = time.monotonic() - started
        if not 200 <= status_code < 300:
            # Never persist raw HTTP error bodies in metadata to prevent credential echo leakage.
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=elapsed,
                error_detail=f"HTTP {status_code} ({len(body_bytes)} bytes; body omitted)",
                extra_meta={"http_status": status_code},
            )

        try:
            data = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            return InferenceResult(
                status="request_failed",
                raw_output=None,
                latency_seconds=elapsed,
                error_detail=f"invalid JSON response: {type(exc).__name__}",
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
        raw_usage = data.get("usage")
        if isinstance(raw_usage, dict):
            safe_usage = {
                k: v
                for k, v in raw_usage.items()
                if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
            }
            if safe_usage:
                extra_meta["usage"] = safe_usage
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
