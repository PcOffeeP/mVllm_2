"""Model-independent bridge for the existing trusted display receipt contract.

The embedding instrument owns upload and actual display observation. Calling a
callback here is a statement by that instrument, never proof of a DOM render.
No transport, signer, key storage, UI, or network connection is supplied here.
"""
from __future__ import annotations

import copy
import re
import secrets
import time
from urllib.parse import quote

from finetune.eval_semantics import extract_semantics
from versioning.performance import digest
from versioning.performance_receipts import (
    make_backend_receipt, make_display_receipt, output_digest, validate_policy,
    verify_display_receipt, verify_document,
)


class PerformanceClientBridge:
    """Serial requests using one non-resetting client monotonic clock.

    ``transport(method, path, *, headers, json)`` must return the decoded JSON
    response and raise on HTTP/connection errors. ``signer(payload)`` returns the
    existing signed document envelope. Both are injected by the deployment.
    Upload requests themselves belong to the embedding client, which must attach
    ``request_headers`` and call ``upload_complete`` from its upload event.
    """

    def __init__(self, plan, *, session_token, signer, transport=None,
                 monotonic_ns=time.monotonic_ns):
        self._plan = copy.deepcopy(plan)
        self._policy = validate_policy(self._plan["config"].get("client_attestation_policy"),
                                       session_id=self._plan["config"]["session_id"])
        if not isinstance(session_token, str) or not session_token or "\n" in session_token or "\r" in session_token:
            raise ValueError("explicit performance session token required")
        if not callable(signer) or not callable(monotonic_ns) or (transport is not None and not callable(transport)):
            raise ValueError("injected signer/clock/transport must be callable")
        self._token, self._signer, self._transport = session_token, signer, transport
        self._clock, self._last_ns = monotonic_ns, None
        self._requests = {}
        self._active = None
        self._finished = None

    def _tick(self):
        value = self._clock()
        if type(value) is not int or value < 0 or (self._last_ns is not None and value < self._last_ns):
            raise ValueError("client clock must supply non-resetting integer monotonic nanoseconds")
        self._last_ns = value
        return value

    def _request(self, request_id):
        if request_id not in self._requests:
            raise ValueError("unknown original client request")
        return self._requests[request_id]

    def begin_request(self, media_id, *, request_id=None, warmup=False):
        """Allocate identity before upload; this does not start the stopwatch."""
        if self._finished is not None or self._active is not None:
            raise ValueError("performance bridge is finished or has an unfinished serial request")
        if media_id not in {m["media_id"] for m in self._plan["media_allowlist"]}:
            raise ValueError("media outside frozen development allowlist")
        identity = secrets.token_hex(16) if request_id is None else request_id
        if not isinstance(identity, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", identity) is None:
            raise ValueError("stable URL-safe request ID required")
        if identity in self._requests:
            raise ValueError("original request already exists; retry with its existing headers")
        if type(warmup) is not bool:
            raise ValueError("warmup must be boolean")
        frozen_warmups = self._plan["config"]["policies"]["warmup"]["request_ids"]
        if warmup != (identity in frozen_warmups):
            raise ValueError("warmup differs from frozen request IDs")
        self._requests[identity] = {"request_id": identity, "media_id": media_id,
            "upload_nonce": secrets.token_hex(32), "warmup": warmup,
            "upload_complete_monotonic_ns": None, "display_complete_monotonic_ns": None,
            "raw_output": None, "backend_receipt": None, "receipt": None,
            "submitted": False, "failed": False, "attempt_count": 0, "failures": []}
        self._active = identity
        return identity

    def request_headers(self, request_id):
        """Return fresh headers with the same original identity on every retry."""
        request = self._request(request_id)
        return {"x-performance-session": self._token,
                "x-performance-request-id": request_id,
                "x-performance-upload-nonce": request["upload_nonce"],
                "x-performance-warmup": str(request["warmup"]).lower()}

    def upload_complete(self, request_id):
        """Called only by the client upload-complete event, never an HTTP response.

        Every upload attempt is counted, but retries retain the original start.
        """
        request = self._request(request_id)
        if self._active != request_id or request["receipt"] is not None:
            raise ValueError("upload event requires the active original request")
        request["attempt_count"] += 1
        if request["upload_complete_monotonic_ns"] is None:
            request["upload_complete_monotonic_ns"] = self._tick()
        return request["upload_complete_monotonic_ns"]

    def record_failure(self, request_id, *, terminal=False):
        """Retain client failures in the denominator; terminal failures end a slot.

        A terminal client observation is not a server failure attestation. The
        server still decides whether finish is allowed for its own request ledger.
        """
        if type(terminal) is not bool:
            raise ValueError("terminal must be boolean")
        request = self._request(request_id)
        if terminal:
            if self._active != request_id or request["receipt"] is not None:
                raise ValueError("terminal failure requires an undisplayed active request")
            self._tick()
            request["failed"] = True
            self._active = None
        request["failures"].append("client_failure")

    def _send(self, request_id, method, path, body=None):
        request = self._request(request_id) if request_id is not None else None
        try:
            if self._transport is None:
                raise ValueError("explicit transport required; bridge never opens a network connection")
            headers = self.request_headers(request_id) if request is not None else {"x-performance-session": self._token}
            return self._transport(method, path, headers=headers, json=copy.deepcopy(body))
        except Exception:
            if request is not None:
                request["failures"].append("transport_failure")
            raise

    def receive_output(self, request_id, raw_output):
        """Fetch and bind a signed backend receipt after receiving complete raw text."""
        request = self._request(request_id)
        if request["upload_complete_monotonic_ns"] is None or request["failed"]:
            raise ValueError("original client upload event required before backend receipt")
        if not isinstance(raw_output, str):
            raise ValueError("complete raw output string required")
        output_digest(self._plan, raw_output)
        if request["backend_receipt"] is not None:
            if request["raw_output"] != raw_output:
                raise ValueError("first backend raw output is locked")
            return copy.deepcopy(request["backend_receipt"])
        backend = self._send(request_id, "GET", "/v1/performance/backend-receipt/" + quote(request_id, safe=""))
        value = verify_document(backend, self._policy["server_public_key"])
        expected = make_backend_receipt(self._plan, request_id=request_id, media_id=request["media_id"],
            upload_at=value.get("upload_at"), backend_at=value.get("backend_at"), raw_output=raw_output,
            upload_nonce=request["upload_nonce"], synthetic=value.get("synthetic"), nonce=value.get("challenge"))
        if value != expected:
            raise ValueError("backend receipt original plan/session/request/media/nonce/output binding differs")
        request["backend_receipt"], request["raw_output"] = copy.deepcopy(backend), raw_output
        return copy.deepcopy(backend)

    def display_complete(self, request_id, *, raw_output, displayed_fields):
        """External display observer confirms full raw text AND automatic fields.

        The observer must call this after actual rendering. The bridge checks its
        statement and signs the existing contract; it cannot inspect a browser.
        """
        request = self._request(request_id)
        if request["backend_receipt"] is None or request["failed"]:
            raise ValueError("verified backend output required before display callback")
        if raw_output != request["raw_output"] or type(raw_output) is not str:
            raise ValueError("displayed raw output differs from original backend output")
        fields = extract_semantics(raw_output, rules=self._plan["semantic_rules"])["fields"]
        # Comparing canonical digests also rejects bool/int equality and NaN.
        if type(displayed_fields) is not dict or digest(displayed_fields) != digest(fields):
            raise ValueError("display callback must confirm all complete automatic fields exactly")
        if request["receipt"] is not None:
            return copy.deepcopy(request["receipt"])
        if self._active != request_id:
            raise ValueError("display callback requires the active serial request")
        if request["display_complete_monotonic_ns"] is None:
            request["display_complete_monotonic_ns"] = self._tick()
        payload = make_display_receipt(self._plan, request["backend_receipt"],
            upload_complete_monotonic_ns=request["upload_complete_monotonic_ns"],
            display_complete_monotonic_ns=request["display_complete_monotonic_ns"])
        try:
            receipt = self._signer(copy.deepcopy(payload))
            if digest(verify_document(receipt, self._policy["client_public_key"])) != digest(payload):
                raise ValueError("signer changed the frozen display payload")
            backend = request["backend_receipt"]["payload"]
            verify_display_receipt(self._plan, receipt, backend_receipt=request["backend_receipt"],
                request={"request_id": request_id, "media_id": request["media_id"],
                         "upload_at": backend["upload_at"], "backend_at": backend["backend_at"],
                         "raw_output": raw_output, "upload_nonce": request["upload_nonce"]})
        except Exception:
            request["failures"].append("signing_or_receipt_failure")
            raise
        request["receipt"] = copy.deepcopy(receipt)
        self._active = None
        return copy.deepcopy(receipt)

    def submit_receipt(self, request_id):
        request = self._request(request_id)
        if request["receipt"] is None:
            raise ValueError("explicit complete display callback required before receipt POST")
        result = self._send(request_id, "POST", "/v1/performance/display-receipt", {"receipt": request["receipt"]})
        request["submitted"] = True
        return copy.deepcopy(result)

    def finish(self):
        if self._finished is not None:
            return copy.deepcopy(self._finished)
        if any(not (r["submitted"] or r["failed"]) for r in self._requests.values()):
            raise ValueError("cannot finish with unsubmitted or unfinished client requests")
        result = self._send(None, "POST", "/v1/performance/finish", {})
        if type(result) is not dict or set(result) != {"finished"} or result["finished"] is not True:
            raise ValueError("server did not confirm clean performance finish")
        self._finished = copy.deepcopy(result)
        return copy.deepcopy(result)

    def snapshot(self):
        """Diagnostic client ledger, never formal performance/DOM evidence."""
        return {"request_count": len(self._requests), "finished": self._finished is not None,
                "requests": copy.deepcopy(self._requests), "dom_render_verified": False}
