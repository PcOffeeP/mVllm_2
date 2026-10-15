"""Frozen performance-only authority and loopback adapter session.

Measurement authority never grants a service alias or quality conclusion.  All
clock, model-loader and adapter dependencies are injectable for offline tests.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import math
import secrets
import time
from pathlib import Path
from typing import Any

from versioning.ids import parse_eval_id, parse_model_id, parse_data_id, parse_prompt_id

SCHEMA = "tensile-vlm/v4.1-performance-evaluation"
PROTOCOL = "performance-v1"
_CLOCK_EPOCH = time.time()
_CLOCK_MONOTONIC = time.monotonic()


def measurement_time():
    """Epoch-correlated monotonic clock; wall-clock adjustments cannot reset deadlines."""
    return _CLOCK_EPOCH + time.monotonic() - _CLOCK_MONOTONIC

POLICIES = {"media_strata", "cache", "repetition", "retry", "warmup", "cold_start", "client_instrumentation"}


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("performance input must be an ordinary file without symlinks")
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value <= 0):
        raise ValueError(f"{name} must be a finite {'positive' if positive else 'nonnegative'} number")
    return value


def validate_media_metadata(metadata):
    if not isinstance(metadata, dict) or set(metadata) != {"duration", "size_bytes", "container", "codec", "bit_depth", "width", "height", "fps"}:
        raise ValueError("complete performance media metadata required")
    for name in ("duration", "size_bytes", "width", "height", "fps"):
        number(metadata[name], name, positive=True)
    if (metadata["duration"] > 60 or metadata["size_bytes"] > 100 * 1024**2
            or metadata["container"] != "mp4" or metadata["codec"] != "h264"
            or type(metadata["bit_depth"]) is not int or metadata["bit_depth"] != 8
            or max(metadata["width"], metadata["height"]) > 1920
            or min(metadata["width"], metadata["height"]) > 1080 or metadata["fps"] > 60):
        raise ValueError("media exceeds frozen performance support specification")
    return metadata


def probe_media(path):
    """Read-only ffprobe, never inference; callers may inject a synthetic probe."""
    import subprocess
    from fractions import Fraction
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=codec_name,pix_fmt,width,height,avg_frame_rate:format=duration,format_name", "-of", "json", str(path)],
        check=True, capture_output=True, text=True)
    value = json.loads(result.stdout)
    stream = value["streams"][0]
    # These explicitly enumerated ffmpeg pixel formats are 8-bit. Unknown
    # formats fail closed instead of inferring depth from a missing field.
    pixel = stream["pix_fmt"]
    if pixel not in {"yuv420p", "yuv422p", "yuv444p", "yuvj420p", "yuvj422p", "yuvj444p", "nv12"}:
        raise ValueError("performance media requires a verified 8-bit pixel format")
    return validate_media_metadata({"duration": float(value["format"]["duration"]),
        "size_bytes": Path(path).stat().st_size, "container": "mp4" if "mp4" in value["format"]["format_name"].split(",") else value["format"]["format_name"],
        "codec": stream["codec_name"], "bit_depth": 8, "width": stream["width"], "height": stream["height"],
        "fps": float(Fraction(stream["avg_frame_rate"]))})


def validate_performance_plan(plan, *, store=None, now=None, executor=None, session_id=None, live_media=False, probe=None):
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA or plan.get("purpose") != "performance" or plan.get("protocol") != PROTOCOL:
        raise ValueError("not a performance-only frozen plan")
    protocols = {parse_eval_id(plan["eval_version"]).protocol, parse_model_id(plan["model"]["model_id"]).protocol,
        parse_data_id(plan["data_version"]).protocol, parse_prompt_id(plan["prompt"]["version"]).protocol}
    if protocols != {"v4.1"} or type(plan["model"]["version"]) is not int or plan["model"]["version"] < 1:
        raise ValueError("complete v4.1 identities and exact positive Registry numeric version required")
    from finetune.eval_semantics import rules_digest
    rules_digest(plan["semantic_rules"])
    c = plan["config"]
    if c.get("scope") != "single_fold" or c.get("split") != "validation" or type(c.get("fold")) is not int or c["fold"] not in (0, 1, 2):
        raise ValueError("performance uses an explicitly selected development validation fold")
    if c.get("artifact_kind") not in {"model", "adapter", "merged"}:
        raise ValueError("performance artifact kind required")
    for name in ("generation", "runtime_variant", "device"):
        if not isinstance(c.get(name), dict) or not c[name]:
            raise ValueError(f"frozen {name} required")
    variant = c["runtime_variant"]
    if not {"dtype", "preprocessing_sha256", "llamafactory_version", "transformers_version"} <= set(variant) or any(
            not isinstance(variant[k], str) or not variant[k].strip() or variant[k].lower() == "unknown"
            for k in ("dtype", "preprocessing_sha256", "llamafactory_version", "transformers_version")):
        raise ValueError("freeze actual dtype/preprocessing/library versions before performance")
    if c.get("quantization_bit") == 4:
        quant = variant.get("quantization")
        if (not isinstance(quant, dict) or set(quant) != {"quant_type", "double_quant", "compute_dtype", "quant_storage", "skip_modules", "excluded_module_dtype"}
                or quant["quant_type"] != "nf4" or quant["double_quant"] is not True
                or quant["compute_dtype"] != variant["dtype"] or not isinstance(quant["quant_storage"], str)
                or quant["skip_modules"] != ["resampler"] or quant["excluded_module_dtype"] != "bfloat16"):
            raise ValueError("explicit complete frozen 4-bit compute/storage variant required")
    if c.get("client_attestation_policy") is not None:
        from versioning.performance_receipts import validate_policy, server_source_digest
        policy = validate_policy(c["client_attestation_policy"], session_id=c.get("session_id"))
        if policy["server_source_sha256"] != server_source_digest():
            raise ValueError("trusted performance receiver/server source digest drift")
    for name in ("executor", "session_id"):
        if not isinstance(c.get(name), str) or not c[name].strip():
            raise ValueError(f"frozen {name} required")
    if c.get("phase") not in {"preflight", "formal"}:
        raise ValueError("phase must be preflight or formal")
    budget = number(c.get("budget_gpu_hours"), "GPU-hour budget", positive=True)
    if budget > (1 if c["phase"] == "preflight" else 20):
        raise ValueError("GPU-hour budget exceeds confirmed cap")
    number(c.get("issued_at"), "issued_at")
    number(c.get("expires_at"), "expires_at")
    if c["expires_at"] <= c["issued_at"]:
        raise ValueError("positive session TTL required")
    if now is not None and not c["issued_at"] <= number(now, "now") < c["expires_at"]:
        raise ValueError("performance session is not active or TTL expired")
    if executor is not None and executor != c["executor"] or session_id is not None and session_id != c["session_id"]:
        raise ValueError("performance executor/session authorization mismatch")
    if not isinstance(c.get("policies"), dict) or set(c["policies"]) != POLICIES or any(not v for v in c["policies"].values()):
        raise ValueError("freeze media strata/cache/repetition/retry/warmup/cold-start/client policies before execution")
    warmup = c["policies"]["warmup"]
    if (not isinstance(warmup, dict) or set(warmup) != {"request_ids"} or not isinstance(warmup["request_ids"], list)
            or any(not isinstance(key,str) or not key for key in warmup["request_ids"])
            or len(set(warmup["request_ids"])) != len(warmup["request_ids"])):
        raise ValueError("warmup must freeze explicit unique request_ids before execution")
    growth = c.get("resource_growth_policy")
    if not isinstance(growth, dict) or set(growth) != {"algorithm", "metric", "window_seconds", "min_samples", "max_growth_bytes"}:
        raise ValueError("an explicit pre-execution resource-growth policy is required")
    if growth["algorithm"] != "window-net-growth":
        raise ValueError("unsupported frozen resource growth algorithm")
    if growth["metric"] not in {"vram_bytes", "rss_bytes"} or type(growth["min_samples"]) is not int or growth["min_samples"] < 2:
        raise ValueError("invalid frozen resource-growth metric/sample count")
    number(growth["window_seconds"], "growth window", positive=True)
    number(growth["max_growth_bytes"], "growth threshold")
    media = plan.get("media_allowlist")
    if not isinstance(media, list) or not media or len({m["media_id"] for m in media}) != len(media):
        raise ValueError("nonempty unique development media allowlist required")
    for m in media:
        if set(m) != {"media_id", "path", "sha256", "metadata"} or len(m["sha256"]) != 64:
            raise ValueError("media requires a frozen identity and actual byte digest")
        validate_media_metadata(m["metadata"])
        if live_media and (file_digest(m["path"]) != m["sha256"] or (probe or probe_media)(Path(m["path"])) != m["metadata"]):
            raise ValueError("performance allowlisted media byte/specification drift")
    if store is not None:
        from versioning.registry import validate_model_for_evaluation
        from finetune.eval_run import _model_binding
        actual = validate_model_for_evaluation(store, plan["model"]["model_id"], plan["model"]["version"])
        if _model_binding(actual) != plan["model"]:
            raise ValueError("performance registered source/weight/configuration drift")
    return copy.deepcopy(plan)


def performance_binding(plan):
    return {"model": plan["model"], "prompt": plan["prompt"], "data_version": plan["data_version"],
        **{key: plan["config"][key] for key in ("generation", "quantization_bit", "runtime_variant", "device", "artifact_kind")}}


def _dtype_name(value):
    return str(value).removeprefix("torch.")


def validate_loaded_runtime(model, config):
    """Attest actual compute precision separately from quantized storage dtype.

    Merely setting an argument or observing model.dtype is not 4-bit proof.
    All loaded quantized modules must agree with the frozen compute dtype.
    """
    device = str(model.device)
    expected_device = config["device"]["runtime_device"]
    expected_dtype = config["runtime_variant"]["dtype"]
    four_bit = bool(getattr(model, "is_loaded_in_4bit", False))
    if device != expected_device or four_bit != (config["quantization_bit"] == 4):
        raise ValueError("loaded runtime device/quantization differs from frozen variant")
    if not four_bit:
        if _dtype_name(model.dtype) != expected_dtype:
            raise ValueError("loaded runtime dtype differs from frozen variant")
        return {"runtime_device": device, "runtime_dtype": expected_dtype, "quantization_bit": None, "quantization": None}
    expected = config["runtime_variant"].get("quantization")
    required = {"quant_type", "double_quant", "compute_dtype", "quant_storage", "skip_modules", "excluded_module_dtype"}
    if (not isinstance(expected, dict) or set(expected) != required or expected["quant_type"] != "nf4"
            or expected["double_quant"] is not True or expected["compute_dtype"] != expected_dtype
            or expected["skip_modules"] != ["resampler"] or expected["excluded_module_dtype"] != "bfloat16"):
        raise ValueError("freeze complete NF4/double-quant/compute/storage variant for 4-bit loading")
    quant = getattr(getattr(model, "config", None), "quantization_config", None)
    if quant is None:
        quant = getattr(model, "quantization_config", None)
    if hasattr(quant, "to_dict"):
        quant = quant.to_dict()
    if not isinstance(quant, dict):
        raise ValueError("actual loaded 4-bit quantization metadata is missing")
    actual = {"quant_type": quant.get("bnb_4bit_quant_type"), "double_quant": quant.get("bnb_4bit_use_double_quant"),
        "compute_dtype": _dtype_name(quant.get("bnb_4bit_compute_dtype")),
        "quant_storage": _dtype_name(quant.get("bnb_4bit_quant_storage"))}
    if actual != {key: expected[key] for key in actual}:
        raise ValueError("actual loaded NF4/double-quant/compute/storage metadata differs")
    modules = []
    excluded_quantized = False
    for name, module in model.named_modules():
        weight = getattr(module, "weight", None)
        if ((module.__class__.__name__ == "Linear4bit" and module.__class__.__module__.startswith("bitsandbytes."))
                or (weight is not None and weight.__class__.__name__ == "Params4bit" and hasattr(module, "compute_dtype"))):
            modules.append(module)
            if "resampler" in name.split("."):
                excluded_quantized = True
    if not modules or any(_dtype_name(getattr(module, "compute_dtype", None)) != expected_dtype for module in modules):
        raise ValueError("actual quantized module compute_dtype is missing or inconsistent")
    resampler_parameters = [param for name,param in model.named_parameters() if "resampler" in name.split(".")]
    if (excluded_quantized or not resampler_parameters or any(param.__class__.__name__ == "Params4bit"
            or _dtype_name(param.dtype) != expected["excluded_module_dtype"] for param in resampler_parameters)):
        raise ValueError("actual resampler must remain unquantized with frozen bfloat16 parameters")
    actual.update(skip_modules=["resampler"], excluded_module_dtype=expected["excluded_module_dtype"])
    return {"runtime_device": device, "runtime_dtype": expected_dtype, "quantization_bit": 4, "quantization": actual}


class ObservedPerformanceRuntime:
    """Observe real non-stream achat exceptions before the adapter redacts them."""
    def __init__(self, runtime, observer):
        self._runtime, self._observer = runtime, observer

    def __getattr__(self, name):
        return getattr(self._runtime, name)

    async def achat(self, *args, **kwargs):
        try:
            return await self._runtime.achat(*args, **kwargs)
        except BaseException as exc:
            name = type(exc).__name__
            message = str(exc).lower()
            if isinstance(exc, MemoryError) or name == "OutOfMemoryError" or "out of memory" in message:
                kind = "oom"
            elif not isinstance(exc, Exception):
                kind = "crash"
            else:
                kind = "error"
            self._observer(kind)
            raise


class ControlledPerformanceSession:
    """Authorize before loading, reuse integrated adapter, never touch aliases.

    ``loader`` must return (chat_model, startup_config). It is supplied by the
    authorized training-machine launcher; this module never selects bare model
    paths. A fresh Registry and frozen-input recheck precede each request.
    """
    def __init__(self, plan, *, store, executor, session_id, loader, revalidate, clock=measurement_time,
                 adapter_factory=None, host="127.0.0.1", server_signing_key=None):
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("controlled performance endpoint must bind loopback")
        self.plan = copy.deepcopy(plan)
        self.store, self.executor, self.session_id = store, executor, session_id
        self.loader, self.revalidate, self.clock = loader, revalidate, clock
        self.adapter_factory, self.host = adapter_factory, host
        self.token = secrets.token_urlsafe(32)
        self.server = None
        self.server_signing_key = server_signing_key
        self.backend_receipts = {}
        self.inflight_requests = set()
        self.ambiguous_runtime = False
        self.clean_finish_requested = False
        self.synthetic_runtime = type(loader) is not RegistryPerformanceLoader or adapter_factory is not None
        policy = self.plan["config"].get("client_attestation_policy")
        if policy is not None:
            from versioning.performance_receipts import public_key_hex, load_server_signing_key
            if self.server_signing_key is None:
                import os
                key_path = os.environ.get("PERFORMANCE_SERVER_SIGNING_KEY_FILE")
                if not key_path:
                    raise ValueError("trusted display requires an explicitly supplied server signing key file")
                self.server_signing_key = load_server_signing_key(key_path, policy)
            if public_key_hex(self.server_signing_key) != policy["server_public_key"]:
                raise ValueError("server signing key differs from frozen performance session")
        self.closed = False
        self.started_at = clock()
        self.recorder = None
        import contextvars
        self.active_request = contextvars.ContextVar("performance-request", default=None)
        import threading
        self.resource_lock = threading.Lock()
        self.gpu_count = plan["config"]["device"].get("gpu_count")
        if type(self.gpu_count) is not int or self.gpu_count < 1:
            raise ValueError("explicit positive device.gpu_count required")

    def authorize(self, token):
        if self.closed or not isinstance(token, str) or not secrets.compare_digest(token, self.token):
            raise ValueError("invalid or closed performance session")
        if self.recorder is not None and self.recorder.stop_reason:
            raise ValueError("performance session stopped; no further requests permitted")
        validate_performance_plan(self.plan, store=self.store, now=self.clock(), executor=self.executor, session_id=self.session_id)
        if max(0, self.clock() - self.started_at) * self.gpu_count >= self.plan["config"]["budget_gpu_hours"] * 3600:
            if self.inflight_requests:
                self.block_ambiguous_runtime("runtime_budget_ambiguous")
            else:
                if self.recorder is not None:
                    self.recorder.stop_reason = "gpu_budget_exhausted"
                self.close()
            raise ValueError("performance GPU-hour budget exhausted")
        if self.revalidate() != digest(self.plan):
            raise ValueError("live frozen-input verifier did not return the exact authorized plan digest")

    def block_ambiguous_runtime(self, reason):
        self.ambiguous_runtime = True
        if self.recorder is not None:
            self.recorder.stop_reason = reason
            if self.recorder.runtime_collector is not None:
                self.recorder.runtime_collector["clean_session_end"] = False
        if self.server is not None:
            self.server.should_exit = True

    def sample_resources(self):
        with self.resource_lock:
            return self._sample_resources()

    def _sample_resources(self):
        """Measure this process only; failure is retained as missing evidence."""
        import os
        import subprocess
        import psutil
        result = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=10)
        vram_mib = 0
        matched = False
        for line in result.stdout.splitlines():
            pid, used = line.split(",")
            if int(pid.strip()) == os.getpid():
                matched = True
                vram_mib += int(used.strip())
        if not matched:
            raise ValueError("nvidia-smi did not identify this inference process")
        at = self.clock()
        self.recorder.resource(at, vram_bytes=vram_mib * 1024**2,
            rss_bytes=psutil.Process(os.getpid()).memory_info().rss,
            gpu_seconds=max(0, at - self.started_at) * self.gpu_count)

    def backend_receipt(self, request_id):
        from versioning.performance_receipts import make_backend_receipt, sign_document
        if self.server_signing_key is None or self.recorder is None or request_id not in self.recorder.requests:
            raise ValueError("trusted backend receipt is unavailable")
        if request_id not in self.backend_receipts:
            r = self.recorder.requests[request_id]
            if r["backend"] is None or r["failed"]:
                raise ValueError("trusted backend receipt requires a complete automatic successful output")
            payload = make_backend_receipt(self.plan, request_id=request_id, media_id=r["media_id"],
                upload_at=r["upload"], backend_at=r["backend"], raw_output=r["raw_output"],
                upload_nonce=r["upload_nonce"], synthetic=self.recorder.synthetic, nonce=secrets.token_hex(32))
            self.backend_receipts[request_id] = sign_document(payload, self.server_signing_key)
        return copy.deepcopy(self.backend_receipts[request_id])

    def accept_display_receipt(self, receipt):
        from versioning.performance_receipts import verify_display_receipt, validate_client_clock_sequence
        self.authorize(self.token)
        request_id = receipt.get("payload", {}).get("request_id")
        if self.recorder is None or request_id not in self.recorder.requests:
            raise ValueError("display receipt has no original authorized request")
        backend = self.backend_receipt(request_id)
        r = self.recorder.requests[request_id]
        checked = verify_display_receipt(self.plan, receipt, backend_receipt=backend,
            request={"request_id": request_id, "media_id": r["media_id"], "upload_at": r["upload"],
                "backend_at": r["backend"], "raw_output": r["raw_output"], "upload_nonce": r["upload_nonce"]})
        if checked["synthetic"] != self.recorder.synthetic:
            raise ValueError("trusted display cannot change synthetic runtime provenance")
        sequence = [(r["upload"], checked)]
        for other_id, other in self.recorder.display_receipts.items():
            if other_id == request_id:
                continue
            original = self.recorder.requests[other_id]
            previous = verify_display_receipt(self.plan, other["client_receipt"], backend_receipt=other["backend_receipt"],
                request={"request_id":other_id,"media_id":original["media_id"],"upload_at":original["upload"],
                    "backend_at":original["backend"],"raw_output":original["raw_output"],"upload_nonce":original["upload_nonce"]})
            sequence.append((original["upload"],previous))
        validate_client_clock_sequence(sequence)
        adopted = {"backend_receipt": backend, "client_receipt": copy.deepcopy(receipt)}
        if request_id in self.recorder.display_receipts:
            if self.recorder.display_receipts[request_id] != adopted:
                raise ValueError("first signed display receipt is locked; no replacement or clock reset")
            return checked
        self.recorder.event(request_id, "display_complete", checked["display_at"], warmup=r["warmup"])
        self.recorder.display_receipts[request_id] = adopted
        return checked

    def create_app(self):
        try:
            return self._create_app()
        except BaseException:
            self.close()
            raise

    def _create_app(self):
        self.authorize(self.token)  # no model loading before all authority checks
        from pipeline.v4_1_production_contract import load_v4_1_production_contract
        contract = load_v4_1_production_contract()
        from pipeline.model_registry import bind_service_contract, _service_prompt_digest
        prompt = {"protocol": "tensile-vlm/v4.1", **self.plan["prompt"]}
        contract = bind_service_contract(contract, {"prompt": prompt,
            "prompt_version": prompt["version"], "prompt_sha256": _service_prompt_digest(prompt),
            "model_version": self.plan["model"]["model_id"]})
        actual_generation = {k: v for k, v in contract["analysis"]["generation"].items() if k != "temperature"}
        actual_generation["video_max_frames"] = contract["video"]["max_frames"]
        if self.plan["config"]["generation"] != actual_generation:
            raise ValueError("frozen generation differs from actual integrated adapter generation")
        self.authorize(self.token)
        cold_start_started_at = self.clock()
        chat_model, startup, receipt = self.loader(copy.deepcopy(self.plan))
        if receipt != performance_binding(self.plan):
            raise ValueError("loaded runtime receipt differs from frozen source/Prompt/generation/variant/device")
        if startup.get("model_version") != self.plan["model"]["model_id"]:
            raise ValueError("loaded startup model identity differs from Registry authority")
        factory = self.adapter_factory
        if factory is None:
            from pipeline.server_proxy import create_integrated_app
            factory = create_integrated_app
        from finetune.eval_performance import PerformanceRecorder
        self.recorder = PerformanceRecorder(self.plan, synthetic=self.synthetic_runtime)
        self.recorder.runtime_collector = {"schema_version": "tensile.performance-runtime-collector/v1",
            "qualified": not self.synthetic_runtime, "runtime_binding_sha256": digest(performance_binding(self.plan)),
            "observes_achat_exceptions": True, "clean_session_end": False}
        def observe(kind):
            request_id = self.active_request.get()
            if request_id in self.recorder.requests:
                self.recorder.event(request_id, kind, self.clock(), warmup=self.recorder.requests[request_id]["warmup"])
        chat_model = ObservedPerformanceRuntime(chat_model, observe)
        adapter = factory(chat_model, startup, contract=contract, service_binding={"purpose": "performance", "session_id": self.session_id,
            "model_id": self.plan["model"]["model_id"], "model_version_number": self.plan["model"]["version"]})
        session = self
        self.recorder.set_lifecycle(cold_start_started_at=cold_start_started_at, ready_at=self.clock())
        try:
            self.sample_resources()
        except Exception:
            self.recorder.stop_reason = "resource_collection_failed"

        async def controlled(scope, receive, send):
            if scope["type"] != "http":
                return await adapter(scope, receive, send)
            request_id = None
            request_warmup = False
            try:
                headers = dict(scope.get("headers", []))
                session.authorize(headers.get(b"x-performance-session", b"").decode())
                warmup_header = headers.get(b"x-performance-warmup", b"false")
                if warmup_header not in {b"true", b"false"}:
                    raise ValueError("explicit warmup header must be true or false")
                request_warmup = warmup_header == b"true"
                body = b""
                while True:
                    message = await receive()
                    if message.get("type") == "http.disconnect":
                        raise ValueError("upload interrupted")
                    body += message.get("body", b"")
                    if len(body) > 140 * 1024**2:
                        raise ValueError("performance upload exceeds support size")
                    if not message.get("more_body", False):
                        break
                upload_arrival = session.clock()
                path = scope.get("path", "")
                async def receipt_response(value):
                    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": canonical(value)})
                if scope.get("method") == "GET" and path.startswith("/v1/performance/backend-receipt/"):
                    return await receipt_response(session.backend_receipt(path.removeprefix("/v1/performance/backend-receipt/")))
                if scope.get("method") == "POST" and path == "/v1/performance/finish":
                    if json.loads(body or b"{}") != {} or session.inflight_requests or session.ambiguous_runtime:
                        raise ValueError("cannot finish a session with ambiguous or running model requests")
                    if any(not r["failed"] and (r["backend"] is None or key not in session.recorder.display_receipts)
                            for key,r in session.recorder.requests.items()):
                        raise ValueError("cannot finish before automatic requests have signed display receipts")
                    session.clean_finish_requested = True
                    if session.server is not None:
                        session.server.should_exit = True
                    return await receipt_response({"finished": True})
                if scope.get("method") == "POST" and path == "/v1/performance/display-receipt":
                    document = json.loads(body)
                    if not isinstance(document, dict) or set(document) != {"receipt"}:
                        raise ValueError("signed display receipt envelope required")
                    return await receipt_response(session.accept_display_receipt(document["receipt"]))
                if scope.get("method") == "POST":
                    from pipeline.server_proxy import _extract_video_data_url, _decode_mp4_data_url
                    payload = json.loads(body)
                    media = _decode_mp4_data_url(_extract_video_data_url(payload))
                    if hashlib.sha256(media).hexdigest() not in {m["sha256"] for m in session.plan["media_allowlist"]}:
                        raise ValueError("media outside development allowlist")
                    from pipeline.server_proxy import _request_mode
                    if _request_mode(payload, contract) != "analysis":
                        raise ValueError("performance only accepts analysis requests")
                    if payload.get("model") != session.plan["model"]["model_id"]:
                        raise ValueError("performance model override forbidden")
                    request_id = headers.get(b"x-performance-request-id", b"").decode()
                    if not request_id:
                        raise ValueError("stable performance request ID required across retries")
                    media_id = next(m["media_id"] for m in session.plan["media_allowlist"] if m["sha256"] == hashlib.sha256(media).hexdigest())
                    upload_nonce = headers.get(b"x-performance-upload-nonce", b"").decode() or None
                    if request_id in session.recorder.requests:
                        session.recorder.event(request_id, "retry", session.clock(), media_id=media_id, warmup=request_warmup, upload_nonce=upload_nonce)
                    else:
                        session.recorder.event(request_id, "uploaded", upload_arrival, media_id=media_id, warmup=request_warmup, upload_nonce=upload_nonce)
                    session.recorder.event(request_id, "queued", session.clock(), warmup=request_warmup)
                    generation = session.plan["config"]["generation"]
                    if any(k in payload and payload[k] != v for k, v in generation.items()):
                        raise ValueError("generation drift")
                    # The integrated adapter fixes Prompt/generation itself.
                    # Freeze those exact constants at launcher verification.
                replayed = False
                async def replay():
                    nonlocal replayed
                    if replayed:
                        return {"type": "http.disconnect"}
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                import asyncio
                session.authorize(headers.get(b"x-performance-session", b"").decode())
                upload_completed = session.recorder.requests[request_id]["upload"] if request_id else session.clock()
                budget_remaining = session.plan["config"]["budget_gpu_hours"] * 3600 / session.gpu_count - (session.clock() - session.started_at)
                timeout = min(600 - (session.clock() - upload_completed), session.plan["config"]["expires_at"] - session.clock(), budget_remaining)
                if timeout <= 0:
                    raise ValueError("performance budget/TTL expired")
                # Absolute upload-complete timeout spans all adapter retries.
                captured = bytearray()
                outgoing = []
                status = 200
                async def capture_send(message):
                    nonlocal status
                    if message["type"] == "http.response.start":
                        status = message["status"]
                    if message["type"] == "http.response.body":
                        captured.extend(message.get("body", b""))
                    outgoing.append(message)
                if request_id:
                    session.recorder.event(request_id, "inference", session.clock(), warmup=request_warmup)
                active_token = session.active_request.set(request_id)
                session.inflight_requests.add(request_id)
                try:
                    await asyncio.wait_for(adapter(scope, replay, capture_send), timeout=timeout)
                finally:
                    session.active_request.reset(active_token)
                    session.inflight_requests.discard(request_id)
                if request_id:
                    if status != 200:
                        session.recorder.event(request_id, "error", session.clock(), warmup=request_warmup)
                    else:
                        from finetune.eval_semantics import extract_semantics
                        raw = json.loads(captured)["choices"][0]["message"]["content"]
                        semantic = extract_semantics(raw, rules=session.plan["semantic_rules"])
                        parser = semantic["branch"] if semantic["branch"] in {"strict", "rule"} and not semantic["missing_fields"] else "unreadable"
                        session.recorder.event(request_id, "auto_parse", session.clock(), parser=parser, raw_output=raw, warmup=request_warmup)
                        if parser in {"strict", "rule"}:
                            session.recorder.event(request_id, "backend_complete", session.clock(), warmup=request_warmup)
                        else:
                            session.recorder.event(request_id, "error", session.clock(), warmup=request_warmup)
                    try:
                        session.sample_resources()
                    except Exception:
                        # Missing collector/driver access is an evidence gap,
                        # never silently replaced with zero VRAM/RSS.
                        session.recorder.stop_reason = "resource_collection_failed"
                if session.clock() - upload_completed > 600:
                    raise ValueError("absolute backend timeout exceeded")
                for message in outgoing:
                    await send(message)
                return None
            except (ValueError, KeyError, TypeError, TimeoutError) as exc:
                if isinstance(exc, TimeoutError):
                    # wait_for may cancel only the coroutine while a CUDA or
                    # to_thread worker continues. Never start another model
                    # request until an owned worker's terminal state is proven.
                    session.block_ambiguous_runtime("runtime_timeout_ambiguous")
                if request_id in session.recorder.requests:
                    session.recorder.event(request_id, "timeout" if isinstance(exc, TimeoutError) else "error", session.clock(), warmup=session.recorder.requests[request_id]["warmup"])
                await send({"type": "http.response.start", "status": 403, "headers": []})
                await send({"type": "http.response.body", "body": b"Invalid performance authority or frozen request"})
        return controlled

    def serve(self, *, port):
        """Run only this session's server; no process search/kill or service edits."""
        import uvicorn
        self.authorize(self.token)
        import threading
        stop = threading.Event()
        self.server = uvicorn.Server(uvicorn.Config(self.create_app(), host=self.host, port=port, log_level="warning"))
        interval = self.plan["config"]["resource_growth_policy"]["window_seconds"] / (self.plan["config"]["resource_growth_policy"]["min_samples"] - 1)
        def monitor():
            next_sample = self.clock() + interval
            while not stop.wait(min(1, interval)):
                try:
                    self.authorize(self.token)
                    if self.clock() >= next_sample:
                        self.sample_resources()
                        next_sample = self.clock() + interval
                except Exception:
                    if self.recorder is not None and not self.recorder.stop_reason:
                        self.recorder.stop_reason = "session_closed"
                    self.server.should_exit = True
                    return
        watcher = threading.Thread(target=monitor, name="performance-session-ttl", daemon=True)
        watcher.start()
        try:
            self.server.run()
            if self.recorder is not None and self.recorder.runtime_collector is not None:
                self.recorder.runtime_collector["clean_session_end"] = bool(self.clean_finish_requested and not self.recorder.stop_reason and not self.ambiguous_runtime and not self.inflight_requests)
        finally:
            stop.set()
            watcher.join(timeout=2)
            try:
                self.sample_resources()
            except Exception:
                if self.recorder is not None:
                    self.recorder.stop_reason = "resource_collection_failed"
            self.close()

    def export_events(self, destination):
        if self.recorder is None:
            raise ValueError("session has not started")
        from versioning.manifest import _publish_immutable
        if not self.closed:
            try:
                self.sample_resources()
            except Exception:
                self.recorder.stop_reason = "resource_collection_failed"
        observed_until = max([self.started_at, *[e["at"] for e in self.recorder.events], *[r["at"] for r in self.recorder.resources]])
        value = self.recorder.evidence(observed_until=observed_until)
        if self.server_signing_key is not None:
            from versioning.performance_receipts import seal_server_evidence
            core = {k:v for k,v in value.items() if k != "server_attestation"}
            self.recorder.server_attestation = seal_server_evidence(self.plan, core, self.server_signing_key)
            value = self.recorder.evidence(observed_until=observed_until)
        return _publish_immutable(Path(destination), canonical(value), label="controlled performance events")

    def close(self):
        self.closed = True
        if self.server is not None:
            self.server.should_exit = True
        close_loader = getattr(self.loader, "close", None)
        if close_loader is not None and not self.ambiguous_runtime:
            close_loader()


class RegistryPerformanceLoader:
    """Actual LLaMA-Factory loader using fresh Registry-controlled bytes only."""
    def __init__(self, store):
        self.store = store
        self.cache = None
        self.runtime = None

    def __call__(self, plan):
        try:
            return self._load(plan)
        except BaseException:
            self.close()
            raise

    def _load(self, plan):
        import importlib.metadata
        import tempfile
        from versioning.registry import (validate_model_for_evaluation, materialize_model,
            validate_materialized_artifacts, _artifact_tree, _complete_base_inventory)
        from pipeline.server_proxy import _chat_model_args
        # The checked source gate accepts base/diagnostic/full before quality or
        # performance passes. It never resolves service aliases.
        record = validate_model_for_evaluation(self.store, plan["model"]["model_id"], plan["model"]["version"])
        self.cache = tempfile.TemporaryDirectory(prefix="tensile-performance-")
        materialized = materialize_model(self.store, record.model_id, Path(self.cache.name))
        validate_materialized_artifacts(record, materialized)
        key = "base" if record.source_kind == "base" else (f"fold{record.source_evidence['fold']}" if record.source_scope == "diagnostic_fold" else "full")
        kind = plan["config"]["artifact_kind"]
        artifact = materialized / record.artifacts[key][kind]
        adapter = artifact if kind == "adapter" else None
        base = Path(record.base_model) if adapter else artifact
        before = {"base": _complete_base_inventory(base), "adapter": _artifact_tree(adapter) if adapter else None}
        actual_versions = {name: importlib.metadata.version(name) for name in ("llamafactory", "transformers")}
        if any(actual_versions[name] != plan["config"]["runtime_variant"][name + "_version"] for name in actual_versions):
            raise ValueError("actual performance runtime library versions differ from frozen variant")
        args = _chat_model_args(str(base))
        if adapter:
            args["adapter_name_or_path"] = str(adapter)
        config = plan["config"]
        args.update(infer_dtype=config["runtime_variant"]["dtype"], device_map=config["device"]["runtime_device"])
        if config["quantization_bit"] is not None:
            args["quantization_bit"] = config["quantization_bit"]
            args["double_quantization"] = config["runtime_variant"]["quantization"]["double_quant"]
            args["quantization_type"] = config["runtime_variant"]["quantization"]["quant_type"]
        # Imports/loading occur only after Registry authority and byte checks.
        from llamafactory.chat import ChatModel
        runtime = ChatModel(args)
        self.runtime = runtime
        validate_model_for_evaluation(self.store, record.model_id, record.version)
        validate_materialized_artifacts(record, materialized)
        after = {"base": _complete_base_inventory(base), "adapter": _artifact_tree(adapter) if adapter else None}
        if before != after:
            raise ValueError("performance weights changed during actual loading")
        actual_model = runtime.engine.model
        attestation = validate_loaded_runtime(actual_model, config)
        actual_device, actual_dtype = attestation["runtime_device"], attestation["runtime_dtype"]
        startup = {"max_frames": config["generation"]["video_max_frames"], "model_version": record.model_id,
            "adapter_version": record.model_id, "base_model_version": record.base_model,
            "processor_version": runtime.engine.processor.__class__.__name__,
            "llamafactory_version": importlib.metadata.version("llamafactory"),
            "transformers_version": importlib.metadata.version("transformers"),
            "config_fingerprint": digest(performance_binding(plan)), "runtime_device": actual_device, "runtime_dtype": actual_dtype}
        return runtime, startup, performance_binding(plan)

    def close(self):
        if self.runtime is not None:
            engine = getattr(self.runtime, "engine", None)
            if engine is not None:
                engine.model = None
        self.runtime = None
        if self.cache is not None:
            self.cache.cleanup()
            self.cache = None


def open_performance_session(*, root, eval_version, executor, session_id, clock=measurement_time, loader=None, adapter_factory=None, server_signing_key=None):
    """Explicit future-authorized runtime entry; never invoked by event import."""
    from finetune.eval_performance import verify_performance_evaluation
    from versioning.registry import open_registry_store
    value = verify_performance_evaluation(root=root, eval_version=eval_version)
    store = open_registry_store(Path(root) / "workspace/mlflow", data_root=Path(root) / "data")
    def revalidate():
        return digest(verify_performance_evaluation(root=root, eval_version=eval_version))
    return ControlledPerformanceSession(value, store=store, executor=executor, session_id=session_id,
        loader=loader or RegistryPerformanceLoader(store), revalidate=revalidate, clock=clock, adapter_factory=adapter_factory, server_signing_key=server_signing_key)


def run_performance_session(*, root, eval_version, executor, session_id, port, evidence_path):
    """Explicit controlled runtime launch; writes a private local capability.

    This action must only be invoked under applicable real-runtime authority.
    Offline ``performance_run`` imports events and never calls this function.
    """
    import os
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("explicit valid loopback port required")
    session = open_performance_session(root=root, eval_version=eval_version, executor=executor, session_id=session_id)
    evidence_path = Path(evidence_path)
    # Refuse collisions before any model loading or existing-service effects.
    if evidence_path.exists():
        raise ValueError("performance evidence output already exists")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    capability = evidence_path.with_suffix(".session.json")
    fd = os.open(capability, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical({"purpose": "performance", "endpoint": f"http://127.0.0.1:{port}",
            "executor": executor, "session_id": session_id, "token": session.token,
            "expires_at": session.plan["config"]["expires_at"], "plan_sha256": digest(session.plan)}))
    try:
        session.serve(port=port)
    finally:
        try:
            if session.recorder is not None:
                session.export_events(evidence_path)
        finally:
            session.close()
            capability.unlink(missing_ok=True)
    return evidence_path
