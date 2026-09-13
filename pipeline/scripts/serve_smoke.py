"""Run a real HTTP smoke test against the tensile-vlm/v2 service."""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pipeline.model_registry import resolve_service_model, bind_service_contract
from pipeline.production_contract import load_production_contract, production_contract_hash
from pipeline.v4_1_production_contract import load_v4_1_production_contract


def build_analysis_payload(video_bytes: bytes, contract: dict[str, Any]) -> dict[str, Any]:
    if not video_bytes:
        raise ValueError("video must not be empty")
    video_url = "data:video/mp4;base64," + base64.b64encode(video_bytes).decode("ascii")
    return {
        "model": "tensile-vlm",
        "messages": [
            {"role": "system", "content": contract["analysis"]["system_prompt"]},
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": video_url}},
                    {"type": "text", "text": contract["analysis"]["user_prompt"]},
                ],
            },
        ],
        "stream": False,
    }


def _request_json(
    url: str,
    *,
    api_key: str | None,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = "POST"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"service request failed: {exc.reason}") from exc
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError("service response must be a JSON object")
    return parsed


def validate_preflight(
    preflight: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> None:
    contract = contract or load_production_contract()
    expected_hash = str(contract["contract_hash"])
    if preflight.get("contract_version") != contract["contract_version"]:
        raise RuntimeError("preflight contract_version does not match the local artifact")
    if preflight.get("contract_hash") != expected_hash:
        raise RuntimeError("preflight contract_hash does not match the local artifact")
    deployment = preflight.get("deployment_manifest")
    if not isinstance(deployment, dict):
        raise RuntimeError("preflight deployment_manifest is missing")
    if deployment.get("contract_version") != contract["contract_version"]:
        raise RuntimeError("deployment contract_version does not match")
    if deployment.get("contract_hash") != expected_hash:
        raise RuntimeError("deployment contract_hash does not match")


def validate_analysis_response(
    response: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> None:
    contract = contract or load_production_contract()
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("analysis response has no choices")
    preprocessing = response.get("preprocessing")
    if not isinstance(preprocessing, dict):
        raise RuntimeError("analysis response has no preprocessing evidence")
    frames = preprocessing.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= 8:
        raise RuntimeError("analysis response has an invalid frame table")
    deployment = preprocessing.get("deployment_manifest")
    if (
        not isinstance(deployment, dict)
        or deployment.get("contract_hash") != contract["contract_hash"]
    ):
        raise RuntimeError("analysis response deployment identity drifted")


def validate_service_binding(payload: dict[str, Any], binding: dict[str, Any]) -> None:
    expected = {key: value for key, value in binding.items()
                if key not in {"model_path", "adapter_path", "base_model_version"}}
    deployment = payload.get("deployment_manifest", {})
    if (payload.get("model_registry") != expected
            or deployment.get("model_version") != binding["model_version"]
            or deployment.get("config_fingerprint") != binding["fingerprint"]):
        raise RuntimeError("service Registry binding differs from the selected alias")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--alias", choices=("candidate", "production"), required=True)
    parser.add_argument("--service-mode", choices=("development", "production"), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--api-key-env", default="API_KEY")
    parser.add_argument(
        "--contract-version",
        choices=("tensile-vlm/v2", "tensile-vlm/v4.1"),
        required=True,
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    binding = resolve_service_model(args.root, alias=args.alias, service_mode=args.service_mode)
    if not args.video.is_file():
        raise SystemExit(f"video does not exist: {args.video}")
    base_url = args.base_url.rstrip("/")
    api_key = os.getenv(args.api_key_env) or None
    contract = (
        load_v4_1_production_contract()
        if args.contract_version == "tensile-vlm/v4.1"
        else load_production_contract()
    )

    contract = bind_service_contract(contract, binding)

    preflight = _request_json(
        f"{base_url}/v1/tensile/contract",
        api_key=api_key,
        timeout=args.timeout,
    )
    validate_preflight(preflight, contract)
    validate_service_binding(preflight, binding)
    if resolve_service_model(args.root, alias=args.alias, service_mode=args.service_mode) != binding:
        raise RuntimeError("service Registry binding changed before inference")
    response = _request_json(
        f"{base_url}/v1/chat/completions",
        api_key=api_key,
        payload=build_analysis_payload(args.video.read_bytes(), contract),
        timeout=args.timeout,
    )
    validate_analysis_response(response, contract)
    validate_service_binding(response["preprocessing"], binding)
    if resolve_service_model(args.root, alias=args.alias, service_mode=args.service_mode) != binding:
        raise RuntimeError("service Registry binding changed during inference")

    summary = {
        "preflight": {
            "contract_version": preflight["contract_version"],
            "contract_hash": preflight["contract_hash"],
            "deployment_manifest": preflight["deployment_manifest"],
        },
        "analysis": {
            "content": response["choices"][0]["message"]["content"],
            "request_id": response["preprocessing"].get("request_id"),
            "frames": response["preprocessing"]["frames"],
            "tensor_digest": response["preprocessing"].get("tensor_digest"),
            "tensor_shape": response["preprocessing"].get("tensor_shape"),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
