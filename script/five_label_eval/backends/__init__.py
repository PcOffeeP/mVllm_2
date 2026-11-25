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


def normalize_result(result: InferenceResult) -> InferenceResult:
    """Enforce the strict single-JSON output contract: no unwrapping, null on non-success."""
    status = result.status
    if status not in VALID_BACKEND_STATUSES:
        return InferenceResult(
            status="request_failed",
            raw_output=None,
            latency_seconds=result.latency_seconds,
            error_detail=f"backend returned invalid status {status!r}",
            reasoning_content=result.reasoning_content,
            extra_meta=dict(result.extra_meta),
        )
    if status != "success":
        return InferenceResult(
            status=status,
            raw_output=None,
            latency_seconds=result.latency_seconds,
            error_detail=result.error_detail,
            reasoning_content=result.reasoning_content,
            extra_meta=dict(result.extra_meta),
        )
    if not isinstance(result.raw_output, str) or result.raw_output == "":
        return InferenceResult(
            status="request_failed",
            raw_output=None,
            latency_seconds=result.latency_seconds,
            error_detail=result.error_detail or "model returned empty or non-string content",
            reasoning_content=result.reasoning_content,
            extra_meta=dict(result.extra_meta),
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
            extra_meta=dict(result.extra_meta),
        )
    reasoning = result.reasoning_content
    if isinstance(reasoning, str):
        try:
            reasoning.encode("utf-8")
        except UnicodeEncodeError:
            reasoning = reasoning.encode("utf-8", errors="replace").decode("utf-8")
            return InferenceResult(
                status=result.status,
                raw_output=result.raw_output,
                latency_seconds=result.latency_seconds,
                error_detail=result.error_detail,
                reasoning_content=reasoning,
                extra_meta=dict(result.extra_meta),
            )
    return result
