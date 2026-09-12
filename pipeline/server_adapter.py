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
    explicit root, alias, service mode and a Registry-bound deployment manifest.

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


DEPLOYMENT_FIELDS = {
    "model_version",
    "adapter_version",
    "base_model_version",
    "processor_version",
    "llamafactory_version",
    "transformers_version",
    "config_fingerprint",
    "runtime_device",
    "runtime_dtype",
    "contract_version",
    "contract_hash",
}


def wrap_response(
    raw_response: dict[str, Any],
    video_frames: list[dict[str, Any]],
    deployment_snapshot: dict[str, Any],
    *,
    contract: dict[str, Any] | None = None,
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
    deployment_snapshot:
        The frozen, complete 11-field public deployment identity.

    Returns
    -------
    A shallow copy of ``raw_response`` with a ``preprocessing`` key injected
    at the top level.  The original response dict is not mutated.
    """
    if not isinstance(raw_response, dict):
        raise TypeError("raw_response must be a dict")
    if not isinstance(deployment_snapshot, dict) or set(deployment_snapshot) != DEPLOYMENT_FIELDS:
        raise ValueError("deployment_snapshot must contain exactly the public 11 fields")
    invalid_deployment = sorted(
        key
        for key in DEPLOYMENT_FIELDS
        if not isinstance(deployment_snapshot.get(key), str)
        or not deployment_snapshot[key].strip()
        or deployment_snapshot[key].strip().lower() == "unknown"
        or deployment_snapshot[key].startswith("REPLACE_")
    )
    if invalid_deployment:
        raise ValueError("deployment_snapshot has invalid fields: " + ", ".join(invalid_deployment))
    contract = contract or load_production_contract()
    if deployment_snapshot["contract_version"] != contract["contract_version"]:
        raise ValueError("contract_version does not match the production contract")
    expected_hash = (
        production_contract_hash()
        if contract["contract_version"] == "tensile-vlm/v2"
        else contract.get("contract_hash")
    )
    if deployment_snapshot["contract_hash"] != expected_hash:
        raise ValueError("contract_hash does not match the production contract")
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
        "processor_version": deployment_snapshot["processor_version"],
        "max_frames": 8,
        "frames": frames,
        "deployment_manifest": dict(deployment_snapshot),
    }

    wrapped = dict(raw_response)
    wrapped["preprocessing"] = preprocessing
    return wrapped
