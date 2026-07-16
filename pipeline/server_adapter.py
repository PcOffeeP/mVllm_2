"""Server-side adapter for LLaMA-Factory OpenAI-compatible endpoint.

This module injects ``preprocessing`` metadata into the standard OpenAI
response so that the Agent client can map model ``fracture_between`` indices
back to original video timestamps.

Deployment
----------
Run ``pipeline.server_proxy`` as the integrated LLaMA-Factory endpoint. It
wraps the actual child ``video_processor`` used by ChatModel and calls
``wrap_response`` with that invocation's frame table and tensor evidence.

**Installation steps on the training machine (LLaMA-Factory host):**

1.  Install the project and editable LLaMA-Factory dependencies.
2.  Start ``python3 -m pipeline.server_proxy`` with the exact MiniCPM-V 4.5
    merged model path and a completed deployment manifest.

    The returned ``response`` dict is JSON-serialisable and includes a
    top-level ``preprocessing`` key that the Agent client will parse.

3.  Verify the proxy endpoint response contains ``preprocessing``::

        curl -s http://localhost:8000/v1/chat/completions ... \\
          | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('preprocessing'))"

**Contract notes**
- ``preprocessing`` is an **internal** extension. It never enters the model
  prompt, the four-field JSON output, the decision-model context, or the
  public result.
- ``preprocessing`` 缺失或无效时 Agent 必须 fail closed，不能用本地均匀
  采样或理论 FPS 猜测替代。
"""

from __future__ import annotations

import uuid
import math
from typing import Any

from pipeline.production_contract import load_production_contract, production_contract_hash


def wrap_response(
    raw_response: dict[str, Any],
    video_frames: list[dict[str, Any]],
    processor_info: dict[str, Any],
) -> dict[str, Any]:
    """Inject a ``preprocessing`` metadata block into an OpenAI-compatible
    ``ChatCompletion`` response.

    Parameters
    ----------
    raw_response:
        The dict-serialised OpenAI ``ChatCompletion`` response produced by
        LLaMA-Factory's ``/v1/chat/completions`` endpoint.  This is typically
        obtained via ``completion.model_dump()`` on the server side.
    video_frames:
        The actual frames selected by the MiniCPM-V 4.5 video processor.
        Each entry **must** contain ``index`` (int, 0-based frame index in
        the processor output) and ``timestamp`` (float, seconds in the
        source video).
    processor_info:
        Must contain ``processor_version``, ``max_frames=8`` and the complete
        deployment-manifest fields shown in the module deployment example.

    Returns
    -------
    A shallow copy of ``raw_response`` with a ``preprocessing`` key injected
    at the top level.  The original response dict is not mutated.
    """
    if not isinstance(raw_response, dict):
        raise TypeError("raw_response must be a dict")
    version = processor_info.get("processor_version")
    if not isinstance(version, str) or not version.strip() or version.lower() == "unknown":
        raise ValueError("processor_version is required and must not be unknown")
    if processor_info.get("max_frames") != 8:
        raise ValueError("max_frames must be exactly 8")
    deployment_keys = {
        "model_version",
        "transformers_version",
        "llamafactory_version",
        "base_model_version",
        "artifact_version",
        "config_fingerprint",
        "runtime_device",
        "runtime_dtype",
        "contract_version",
        "prompt_contract_hash",
    }
    missing_deployment = sorted(
        key
        for key in deployment_keys
        if not isinstance(processor_info.get(key), str) or not processor_info[key].strip()
    )
    if missing_deployment:
        raise ValueError(
            "processor_info missing deployment fields: " + ", ".join(missing_deployment)
        )
    contract = load_production_contract()
    if processor_info["contract_version"] != contract["contract_version"]:
        raise ValueError("contract_version does not match the production contract")
    if processor_info["prompt_contract_hash"] != production_contract_hash():
        raise ValueError("prompt_contract_hash does not match the production contract")
    if not isinstance(video_frames, list) or not 1 <= len(video_frames) <= 8:
        raise ValueError("video_frames must contain between 1 and 8 actual frames")

    frames: list[dict[str, Any]] = []
    previous_timestamp: float | None = None
    for expected_index, frame in enumerate(video_frames):
        if not isinstance(frame, dict) or frame.get("index") != expected_index:
            raise ValueError("frame indices must be consecutive and start at 0")
        timestamp = frame.get("timestamp")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)
        ):
            raise ValueError("frame timestamps must be finite JSON numbers")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError("frame timestamps must be strictly increasing")
        frames.append({"index": expected_index, "timestamp": float(timestamp)})
        previous_timestamp = float(timestamp)

    preprocessing: dict[str, Any] = {
        "request_id": str(uuid.uuid4()),
        "processor_version": version,
        "max_frames": 8,
        "frames": frames,
        "deployment_manifest": {
            key: processor_info[key] for key in sorted(deployment_keys)
        },
    }

    wrapped = dict(raw_response)
    wrapped["preprocessing"] = preprocessing
    return wrapped
