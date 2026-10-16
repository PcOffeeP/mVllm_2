"""Public synthetic text/bytes and ephemeral keys only; no model or test data."""
import asyncio
import base64
from copy import deepcopy
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from test_eval_performance import RAW, plan, receipt_policy
from versioning.performance import ControlledPerformanceSession, digest, performance_binding
from versioning.performance_client import PerformanceClientBridge
from versioning.performance_receipts import sign_document, verify_display_receipt


class SyntheticHarness:
    def __init__(self, monkeypatch):
        self.client_key, self.server_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        self.plan = plan()
        self.plan["config"]["client_attestation_policy"] = receipt_policy(self.plan, self.client_key, self.server_key)
        self.client_ns, self.server_seconds = 10_000_000_000, 1
        self.calls = []
        monkeypatch.setattr("versioning.registry.validate_model_for_evaluation", lambda *a: None)
        monkeypatch.setattr("finetune.eval_run._model_binding", lambda value: self.plan["model"])
        monkeypatch.setattr(ControlledPerformanceSession, "sample_resources", lambda self: None)

        async def adapter(scope, receive, send):
            await receive()
            self.server_seconds += 1
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": json.dumps({"choices": [{"message": {"content": RAW}}]}).encode()})

        self.session = ControlledPerformanceSession(self.plan, store=object(), executor="fixture",
            session_id="fixture-session", loader=lambda p: (object(), {"model_version": p["model"]["model_id"]}, performance_binding(p)),
            revalidate=lambda: digest(self.plan), clock=lambda: self.server_seconds,
            adapter_factory=lambda *a, **kw: adapter, server_signing_key=self.server_key)
        self.app = self.session.create_app()
        self.bridge = PerformanceClientBridge(self.plan, session_token=self.session.token,
            signer=lambda p: sign_document(p, self.client_key), transport=self.transport,
            monotonic_ns=lambda: self.client_ns)

    def transport(self, method, path, *, headers, json=None):
        self.calls.append((method, path, deepcopy(headers), deepcopy(json)))

        async def invoke():
            sent = []
            async def receive():
                return {"type": "http.request", "body": __import__("json").dumps(json).encode() if json is not None else b""}
            async def send(message):
                sent.append(message)
            await self.app({"type": "http", "method": method, "path": path,
                            "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}, receive, send)
            if sent[0]["status"] != 200:
                raise ValueError("synthetic HTTP request rejected")
            return __import__("json").loads(b"".join(row.get("body", b"") for row in sent))

        return asyncio.run(invoke())

    def upload(self, request_id="one"):
        request_id = self.bridge.begin_request("fixture-media", request_id=request_id)
        self.bridge.upload_complete(request_id)
        payload = {"model": self.plan["model"]["model_id"], "messages": [
            {"role": "system", "content": self.plan["prompt"]["system_prompt"]},
            {"role": "user", "content": [
                {"type": "video_url", "video_url": {"url": "data:video/mp4;base64," + base64.b64encode(b"media").decode()}},
                {"type": "text", "text": self.plan["prompt"]["user_prompt"]}]}]}
        self.transport("POST", "/v1/chat/completions", headers=self.bridge.request_headers(request_id), json=payload)
        return request_id

    def ready(self):
        request_id = self.upload()
        self.bridge.receive_output(request_id, RAW)
        self.client_ns += 2_000_000_000
        return request_id

    def display(self, request_id="one"):
        return self.bridge.display_complete(request_id, raw_output=RAW, displayed_fields=json.loads(RAW))


@pytest.fixture
def h(monkeypatch):
    return SyntheticHarness(monkeypatch)


def test_synthetic_asgi_upload_to_signed_display_and_finish(h):
    identity = h.ready()
    assert h.bridge.snapshot()["requests"][identity]["receipt"] is None
    assert not h.session.recorder.display_receipts
    receipt = h.display(identity)
    backend = h.session.backend_receipt(identity)
    request = h.session.recorder.requests[identity]
    verified = verify_display_receipt(h.plan, receipt, backend_receipt=backend,
        request={"request_id": identity, "media_id": request["media_id"], "upload_at": request["upload"],
                 "backend_at": request["backend"], "upload_nonce": request["upload_nonce"], "raw_output": RAW})
    assert verified["elapsed_seconds"] == 2 and verified["synthetic"] is True
    h.bridge.submit_receipt(identity)
    h.bridge.submit_receipt(identity)
    assert h.bridge.finish() == {"finished": True}
    assert h.bridge.finish() == {"finished": True}
    posts = [call for call in h.calls if call[1] == "/v1/performance/display-receipt"]
    assert posts[0][3] == posts[1][3] == {"receipt": receipt}
    assert h.calls[-1][1:] == ("/v1/performance/finish", {"x-performance-session": h.session.token}, {})
    assert len(h.session.recorder.display_receipts) == 1
    report = h.session.recorder.report(observed_until=3)
    assert report["synthetic"] is True and report["outcome"] == "synthetic"
    assert not report["e2e_verified"]
    assert h.bridge.snapshot()["dom_render_verified"] is False


def test_upload_event_only_start_and_retry_preserves_original(h):
    identity = h.bridge.begin_request("fixture-media")
    headers = h.bridge.request_headers(identity)
    assert len(headers["x-performance-upload-nonce"]) == 64
    assert h.bridge.snapshot()["requests"][identity]["upload_complete_monotonic_ns"] is None
    with pytest.raises(ValueError, match="upload event"):
        h.bridge.receive_output(identity, RAW)
    assert not h.calls
    h.bridge.upload_complete(identity)
    h.client_ns += 500
    h.bridge.upload_complete(identity)
    assert h.bridge.request_headers(identity) == headers
    row = h.bridge.snapshot()["requests"][identity]
    assert row["upload_complete_monotonic_ns"] == 10_000_000_000 and row["attempt_count"] == 2
    assert h.bridge.snapshot()["request_count"] == 1


@pytest.mark.parametrize("damage", ["signature", "plan_sha256", "session_id", "request_id", "media_id", "upload_nonce", "output_sha256", "schema_version", "extra", "synthetic", "challenge"])
def test_backend_tampering_or_signed_binding_drift_rejected(h, damage):
    identity = h.upload()
    backend = h.session.backend_receipt(identity)
    if damage == "signature":
        backend["signature"] = "00" * 64
    else:
        value = backend["payload"]
        value[damage] = False if damage == "synthetic" else "drift"
        if damage == "synthetic":
            value[damage] = "false"
        backend = sign_document(value, h.server_key)
    h.bridge._transport = lambda *a, **kw: backend
    with pytest.raises((ValueError, TypeError)):
        h.bridge.receive_output(identity, RAW)
    assert h.bridge.snapshot()["requests"][identity]["backend_receipt"] is None


def test_valid_but_different_raw_bytes_rejected(h):
    identity = h.upload()
    with pytest.raises(ValueError, match="binding differs"):
        h.bridge.receive_output(identity, RAW + " ")
    h.bridge.receive_output(identity, RAW)
    with pytest.raises(ValueError, match="locked"):
        h.bridge.receive_output(identity, RAW + " ")


def test_early_display_and_missing_automatic_fields_rejected(h):
    identity = h.bridge.begin_request("fixture-media")
    with pytest.raises(ValueError, match="verified backend"):
        h.display(identity)
    with pytest.raises(ValueError, match="display callback"):
        h.bridge.submit_receipt(identity)
    assert not h.calls


@pytest.mark.parametrize("fields", [{"clip_state": "未断裂"}, {}, {"clip_state": True}, {"clip_state": float("nan")},
                                   {"clip_state": "未断裂", "fracture_mechanism": None, "fracture_site": None, "special_case": False}])
def test_incomplete_or_wrong_display_fields_rejected(h, fields):
    identity = h.ready()
    with pytest.raises(ValueError):
        h.bridge.display_complete(identity, raw_output=RAW, displayed_fields=fields)
    assert h.bridge.snapshot()["requests"][identity]["receipt"] is None


def test_missing_fields_in_raw_cannot_get_receipt(h):
    identity = h.upload()
    with pytest.raises(ValueError, match="complete automatic"):
        h.bridge.receive_output(identity, '{"clip_state":"未断裂"}')


@pytest.mark.parametrize("clock_value", [True, 1.2, float("nan"), -1])
@pytest.mark.parametrize("event", ["upload", "display"])
def test_clock_requires_nonnegative_integer_ns(h, clock_value, event):
    identity = h.bridge.begin_request("fixture-media") if event == "upload" else h.ready()
    h.client_ns = clock_value
    with pytest.raises(ValueError, match="monotonic nanoseconds"):
        h.bridge.upload_complete(identity) if event == "upload" else h.display(identity)


def test_serial_clock_cannot_reset_between_requests(h):
    identity = h.ready()
    h.display(identity)
    h.bridge.submit_receipt(identity)
    other = h.bridge.begin_request("fixture-media", request_id="two")
    h.client_ns = 11_000_000_000
    with pytest.raises(ValueError, match="non-resetting"):
        h.bridge.upload_complete(other)
    assert h.bridge.snapshot()["request_count"] == 2


def test_display_must_include_backend_duration(h):
    identity = h.upload()
    h.bridge.receive_output(identity, RAW)
    with pytest.raises(ValueError, match="contradicts"):
        h.display(identity)


def test_first_display_receipt_and_request_snapshots_are_locked(h):
    identity = h.ready()
    receipt = h.display(identity)
    h.client_ns += 5_000_000_000
    assert h.display(identity) == receipt
    receipt["payload"]["request_id"] = "changed"
    snapshot = h.bridge.snapshot()
    snapshot["requests"][identity]["upload_nonce"] = "changed"
    h.plan["config"]["client_attestation_policy"]["client_id"] = "changed"
    assert h.display(identity)["payload"]["request_id"] == identity
    with pytest.raises(ValueError, match="raw output differs"):
        h.bridge.display_complete(identity, raw_output=RAW + " ", displayed_fields=json.loads(RAW))


@pytest.mark.parametrize("failure_at", ["backend", "submit"])
def test_transport_failure_preserves_identity_attempts_receipt_and_denominator(h, failure_at):
    identity = h.upload() if failure_at == "backend" else h.ready()
    if failure_at == "submit":
        first_receipt = h.display(identity)
    headers = h.bridge.request_headers(identity)
    transport = h.bridge._transport
    def fail(*a, **kw):
        raise ConnectionError("synthetic disconnected")
    h.bridge._transport = fail
    with pytest.raises(ConnectionError):
        h.bridge.receive_output(identity, RAW) if failure_at == "backend" else h.bridge.submit_receipt(identity)
    h.bridge._transport = transport
    if failure_at == "backend":
        h.bridge.upload_complete(identity)
        h.bridge.receive_output(identity, RAW)
        assert h.bridge.snapshot()["requests"][identity]["attempt_count"] == 2
    else:
        h.bridge.submit_receipt(identity)
        assert h.display(identity) == first_receipt
    assert h.bridge.request_headers(identity) == headers
    row = h.bridge.snapshot()["requests"][identity]
    assert row["failures"] == ["transport_failure"]
    assert row["upload_complete_monotonic_ns"] == 10_000_000_000
    assert h.bridge.snapshot()["request_count"] == 1


@pytest.mark.parametrize("damage", ["signature", "payload", "exception"])
def test_signer_failure_keeps_first_display_timestamp_and_denominator(h, damage):
    identity = h.ready()
    original_signer = h.bridge._signer
    def bad_signer(payload):
        if damage == "exception":
            raise RuntimeError("synthetic signer unavailable")
        signed = original_signer(payload)
        if damage == "signature":
            signed["signature"] = "00" * 64
        else:
            payload["request_id"] = "drift"
            signed = original_signer(payload)
        return signed
    h.bridge._signer = bad_signer
    with pytest.raises((ValueError, RuntimeError)):
        h.display(identity)
    h.client_ns += 5_000_000_000
    h.bridge._signer = original_signer
    receipt = h.display(identity)
    assert receipt["payload"]["display_complete_monotonic_ns"] == 12_000_000_000
    assert h.bridge.snapshot()["request_count"] == 1
    assert h.bridge.snapshot()["requests"][identity]["failures"] == ["signing_or_receipt_failure"]


def test_terminal_client_failure_retained_but_cannot_override_server_finish(h):
    identity = h.upload()
    h.bridge.record_failure(identity, terminal=True)
    assert h.bridge.snapshot()["requests"][identity]["failed"] is True
    assert h.bridge.snapshot()["request_count"] == 1
    with pytest.raises(ValueError, match="HTTP request rejected"):
        h.bridge.finish()
    assert not h.session.clean_finish_requested


def test_no_default_network_transport(h):
    bridge = PerformanceClientBridge(h.plan, session_token="synthetic-token", signer=lambda p: sign_document(p, h.client_key))
    identity = bridge.begin_request("fixture-media")
    bridge.upload_complete(identity)
    with pytest.raises(ValueError, match="explicit transport"):
        bridge.receive_output(identity, RAW)
    assert bridge.snapshot()["request_count"] == 1
    assert not h.calls


def test_plan_policy_and_header_snapshots_cannot_drift_after_init(h):
    original = deepcopy(h.plan)
    caller_plan = deepcopy(h.plan)
    h.bridge = PerformanceClientBridge(caller_plan, session_token=h.session.token,
        signer=lambda p: sign_document(p, h.client_key), transport=h.transport, monotonic_ns=lambda: h.client_ns)
    identity = h.upload()
    # Mutating the caller's plan does not change either frozen bridge or server.
    caller_plan["config"]["client_attestation_policy"]["client_id"] = "caller-mutated"
    caller_plan["semantic_rules"] = {}
    headers = h.bridge.request_headers(identity)
    headers["x-performance-upload-nonce"] = "caller-mutated"
    h.bridge.receive_output(identity, RAW)
    h.client_ns += 2_000_000_000
    receipt = h.display(identity)
    assert receipt["payload"]["plan_sha256"] == digest(original)
    assert receipt["payload"]["client_id"] == original["config"]["client_attestation_policy"]["client_id"]
    assert h.bridge.request_headers(identity)["x-performance-upload-nonce"] != "caller-mutated"


@pytest.mark.parametrize("identity", ["a/b", "a?b", "a#b", "a\nb", "", True])
def test_request_id_cannot_change_receipt_route(h, identity):
    with pytest.raises(ValueError, match="URL-safe"):
        h.bridge.begin_request("fixture-media", request_id=identity)
    assert h.bridge.snapshot()["request_count"] == 0


def test_finish_requires_completed_receipt_and_strict_server_confirmation(h):
    identity = h.ready()
    with pytest.raises(ValueError, match="unsubmitted"):
        h.bridge.finish()
    h.display(identity)
    with pytest.raises(ValueError, match="unsubmitted"):
        h.bridge.finish()
    h.bridge.submit_receipt(identity)
    h.bridge._transport = lambda *a, **kw: {"finished": 1}
    with pytest.raises(ValueError, match="did not confirm"):
        h.bridge.finish()
    assert not h.bridge.snapshot()["finished"]
