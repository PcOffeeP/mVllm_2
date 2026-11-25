"""Shared inference backend protocol, request/result dataclasses, and helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

VALID_BACKEND_STATUSES = ("success", "request_failed", "timeout")


@dataclass(frozen=True)
class InferenceRequest:
    """One candidate's model-input payload handed to a backend."""

    candidate_id: str
    record: dict[str, Any]
    frame_paths: tuple[Path, ...]
    frame_pts_seconds: tuple[float, ...]
    prompt_text: str
    timeout_seconds: float = 600.0
    decode_config: dict[str, Any] = field(default_factory=dict)
    frame_bytes: tuple[bytes, ...] | None = None


@dataclass(frozen=True)
class InferenceResult:
    """Normalized backend outcome aligned with ``docs/eval/output-contract.md``."""

    status: str
    raw_output: str | None
    latency_seconds: float
    error_detail: str | None = None
    reasoning_content: str | None = None
    extra_meta: dict[str, Any] = field(default_factory=dict)


class InferenceBackend(Protocol):
    """Minimal pluggable backend interface shared by fake, http, and transformers."""

    backend_name: str

    def run_identity(self) -> dict[str, Any]:
        """Return JSON-serializable run identity metadata for this backend."""

    def infer_one(self, request: InferenceRequest) -> InferenceResult:
        """Run one inference call and return a normalized ``InferenceResult``."""

    def close(self) -> None:
        """Release any held resources (HTTP pools, etc.)."""


def sanitize_base_url(url: str) -> str:
    """Strip credentials, query string, and fragment from a URL for safe metadata logging."""
    parts = urlsplit(url.strip())
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{parts.port}" if parts.port is not None else host
    return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))


def _sanitize_utf8_text(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        return value.encode("utf-8", errors="replace").decode("utf-8")


def _sanitize_utf8_obj(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_utf8_text(value)
    if isinstance(value, dict):
        return {
            (_sanitize_utf8_text(k) if isinstance(k, str) else k): _sanitize_utf8_obj(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_utf8_obj(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize_utf8_obj(v) for v in value]
    return value


def normalize_result(result: InferenceResult) -> InferenceResult:
    """Enforce the strict single-JSON output contract: no unwrapping, null on non-success."""
    status = result.status
    safe_error = _sanitize_utf8_text(result.error_detail)
    safe_reasoning = _sanitize_utf8_text(result.reasoning_content)
    safe_extra = _sanitize_utf8_obj(dict(result.extra_meta))

    if status not in VALID_BACKEND_STATUSES:
        return InferenceResult(
            status="request_failed",
            raw_output=None,
            latency_seconds=result.latency_seconds,
            error_detail=_sanitize_utf8_text(f"backend returned invalid status {status!r}"),
            reasoning_content=safe_reasoning,
            extra_meta=safe_extra,
        )
    if status != "success":
        return InferenceResult(
            status=status,
            raw_output=None,
            latency_seconds=result.latency_seconds,
            error_detail=safe_error,
            reasoning_content=safe_reasoning,
            extra_meta=safe_extra,
        )
    if not isinstance(result.raw_output, str) or result.raw_output == "":
        return InferenceResult(
            status="request_failed",
            raw_output=None,
            latency_seconds=result.latency_seconds,
            error_detail=safe_error or "model returned empty or non-string content",
            reasoning_content=safe_reasoning,
            extra_meta=safe_extra,
        )
    try:
        result.raw_output.encode("utf-8")
    except UnicodeEncodeError:
        return InferenceResult(
            status="request_failed",
            raw_output=None,
            latency_seconds=result.latency_seconds,
            error_detail="model returned invalid UTF-8 string (unpaired surrogate)",
            reasoning_content=None,
            extra_meta=safe_extra,
        )
    return InferenceResult(
        status=result.status,
        raw_output=result.raw_output,
        latency_seconds=result.latency_seconds,
        error_detail=safe_error,
        reasoning_content=safe_reasoning,
        extra_meta=safe_extra,
    )
