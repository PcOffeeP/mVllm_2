"""Server-side adapter for LLaMA-Factory OpenAI-compatible endpoint.

This module injects ``preprocessing`` metadata into the standard OpenAI
response so that the Agent client can map model ``fracture_between`` indices
back to original video timestamps.

Deployment
----------
Copy or symlink ``pipeline/server_adapter.py`` to the LLaMA-Factory training
machine and register ``wrap_response`` as a custom response post-processor.

**Installation steps on the training machine (LLaMA-Factory host):**

1.  Copy this file into the LLaMA-Factory project directory::

        scp pipeline/server_adapter.py user@training-host:~/LLaMA-Factory/

2.  In the LLaMA-Factory API server code (e.g. ``api_server.py`` or a custom
    middleware hook), import and call ``wrap_response`` **after** the model
    processor has run but **before** the response is sent to the client::

        from server_adapter import wrap_response

        # Inside the chat completion handler:
        raw = completion.model_dump()          # dict serialisation
        frames = processor.get_frames()         # [{index, timestamp}, ...]
        info = {
            "processor_version": "minicpmv4.6/0.1",
            "max_frames": 8,
        }
        response = wrap_response(raw, frames, info)

    The returned ``response`` dict is JSON-serialisable and includes a
    top-level ``preprocessing`` key that the Agent client will parse.

3.  Verify by inspecting a sample response for the ``preprocessing`` field::

        curl -s http://localhost:8000/v1/chat/completions ... \\
          | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('preprocessing'))"

**Contract notes**
- ``preprocessing`` is an **internal** extension. It never enters the model
  prompt, the five-field JSON output, the decision-model context, or the
  public result.
- When ``preprocessing`` is absent the Agent degrades gracefully (uses local
  manifest mapping) but marks the round as potentially unreliable.
"""

from __future__ import annotations

import uuid
from typing import Any


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
        The actual frames selected by the MiniCPM-V 4.6 video processor.
        Each entry **must** contain ``index`` (int, 0-based frame index in
        the processor output) and ``timestamp`` (float, seconds in the
        source video).
    processor_info:
        Must contain at least ``processor_version`` (str, a semver or
        build-identifier for the frame-sampling logic) and ``max_frames``
        (int, the configured maximum frame count, **must** be 8 for the
        current MiniCPM-V 4.6 contract).

    Returns
    -------
    A shallow copy of ``raw_response`` with a ``preprocessing`` key injected
    at the top level.  The original response dict is not mutated.
    """
    frames = [
        {
            "index": f["index"],
            "timestamp": f["timestamp"],
        }
        for f in video_frames
    ]

    preprocessing: dict[str, Any] = {
        "request_id": str(uuid.uuid4()),
        "processor_version": processor_info.get("processor_version", "unknown"),
        "max_frames": processor_info.get("max_frames", 8),
        "frames": frames,
    }

    wrapped = dict(raw_response)
    wrapped["preprocessing"] = preprocessing
    return wrapped
