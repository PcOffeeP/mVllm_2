"""Ed25519 contract for a separately deployed trusted display instrument.

Public verification policy is frozen in the performance plan. Private keys are
supplied at runtime, never embedded in plans, manifests or repository artifacts.
A valid signature proves the configured trust root's statement, not installation
of a client instrument; that deployment remains an external execution concern.
"""
from __future__ import annotations

import copy
import hashlib
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from versioning.performance import canonical, digest, number

CLOCK = "client-monotonic-ns-upload-complete-to-render-v1"
POLICY_SCHEMA = "tensile.performance-display-policy/v1"


def _hex(value, size, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{" + str(size * 2) + r"}", value):
        raise ValueError(f"invalid {name}")
    return value


def validate_policy(policy, *, session_id):
    keys = {"schema_version", "client_id", "client_source_sha256", "instrumentation_sha256", "server_source_sha256",
        "client_public_key", "server_public_key", "session_id", "clock_protocol"}
    if not isinstance(policy, dict) or set(policy) != keys or policy["schema_version"] != POLICY_SCHEMA:
        raise ValueError("complete frozen trusted display attestation policy required")
    if (not isinstance(policy["client_id"], str) or not policy["client_id"].strip()
            or policy["session_id"] != session_id or policy["clock_protocol"] != CLOCK):
        raise ValueError("trusted display client/session/clock binding differs")
    for key in ("client_source_sha256", "instrumentation_sha256", "server_source_sha256"):
        _hex(policy[key], 32, key)
    for key in ("client_public_key", "server_public_key"):
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(_hex(policy[key], 32, key)))
    if policy["client_public_key"] == policy["server_public_key"]:
        raise ValueError("trusted client and server signing authorities must be distinct")
    return copy.deepcopy(policy)


def public_key_hex(private_key):
    return private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def sign_document(payload, private_key):
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Ed25519 private signing key required")
    return {"payload": copy.deepcopy(payload), "signature": private_key.sign(canonical(payload)).hex()}


def verify_document(document, public_key):
    if not isinstance(document, dict) or set(document) != {"payload", "signature"} or not isinstance(document["payload"], dict):
        raise ValueError("signed receipt envelope required")
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(_hex(public_key, 32, "verification key")))
        key.verify(bytes.fromhex(_hex(document["signature"], 64, "signature")), canonical(document["payload"]))
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise ValueError("trusted display signature verification failed") from exc
    return copy.deepcopy(document["payload"])


def output_digest(plan, raw_output):
    from finetune.eval_semantics import extract_semantics
    from finetune.v4_1_runtime import parse_v4_1_output
    import json
    semantics = extract_semantics(raw_output, rules=plan["semantic_rules"])
    if semantics["branch"] not in {"strict", "rule"} or semantics["missing_fields"]:
        raise ValueError("trusted display requires complete automatic strict/rule output")
    parse_v4_1_output(json.dumps(semantics["fields"]))
    return digest({"raw_sha256": hashlib.sha256(raw_output.encode()).hexdigest(), "fields": semantics["fields"]})


def make_backend_receipt(plan, *, request_id, media_id, upload_at, backend_at, raw_output, upload_nonce, synthetic, nonce):
    """Build server claim from its actual recorder; sign with the session key."""
    for name, value in (("upload_at", upload_at), ("backend_at", backend_at)):
        number(value, name)
    if backend_at < upload_at or type(synthetic) is not bool:
        raise ValueError("invalid backend receipt lifecycle")
    _hex(nonce, 32, "server challenge")
    _hex(upload_nonce, 32, "original client upload nonce")
    return {"schema_version": "tensile.performance-backend-receipt/v1", "plan_sha256": digest(plan),
        "session_id": plan["config"]["session_id"], "request_id": request_id, "media_id": media_id,
        "upload_at": upload_at, "backend_at": backend_at, "output_sha256": output_digest(plan, raw_output),
        "upload_nonce": upload_nonce, "challenge": nonce, "synthetic": synthetic}


def verify_display_receipt(plan, receipt, *, request, backend_receipt):
    """Verify signatures and exact original request/output, never caller booleans."""
    policy = validate_policy(plan["config"].get("client_attestation_policy"), session_id=plan["config"]["session_id"])
    backend = verify_document(backend_receipt, policy["server_public_key"])
    required_backend = {"schema_version", "plan_sha256", "session_id", "request_id", "media_id", "upload_at", "backend_at",
        "output_sha256", "upload_nonce", "challenge", "synthetic"}
    if (set(backend) != required_backend or backend["schema_version"] != "tensile.performance-backend-receipt/v1"
            or backend["plan_sha256"] != digest(plan) or backend["session_id"] != policy["session_id"]
            or backend["request_id"] != request["request_id"] or backend["media_id"] != request["media_id"]
            or backend["upload_at"] != request["upload_at"] or backend["backend_at"] != request["backend_at"]
            or backend["output_sha256"] != output_digest(plan, request["raw_output"])
            or backend["upload_nonce"] != request["upload_nonce"] or type(backend["synthetic"]) is not bool):
        raise ValueError("trusted backend receipt original request/output binding differs")
    _hex(backend["challenge"], 32, "backend challenge")
    value = verify_document(receipt, policy["client_public_key"])
    keys = {"schema_version", "plan_sha256", "session_id", "request_id", "client_id", "client_source_sha256",
        "instrumentation_sha256", "clock_protocol", "backend_receipt_sha256", "output_sha256", "upload_nonce",
        "upload_complete_monotonic_ns", "display_complete_monotonic_ns", "synthetic"}
    if (set(value) != keys or value["schema_version"] != "tensile.performance-display-receipt/v1"
            or value["plan_sha256"] != digest(plan) or value["session_id"] != policy["session_id"]
            or value["request_id"] != backend["request_id"] or value["backend_receipt_sha256"] != digest(backend_receipt)
            or value["output_sha256"] != backend["output_sha256"] or value["upload_nonce"] != backend["upload_nonce"]
            or any(value[key] != policy[key] for key in ("client_id", "client_source_sha256", "instrumentation_sha256", "clock_protocol"))
            or type(value["synthetic"]) is not bool or value["synthetic"] != backend["synthetic"]):
        raise ValueError("trusted display receipt client/source/session/output binding differs")
    start, end = value["upload_complete_monotonic_ns"], value["display_complete_monotonic_ns"]
    if type(start) is not int or type(end) is not int or start < 0 or end < start:
        raise ValueError("trusted display requires non-resetting monotonic nanosecond timestamps")
    elapsed = (end - start) / 1_000_000_000
    if elapsed < backend["backend_at"] - backend["upload_at"]:
        raise ValueError("trusted display clock contradicts the original backend duration")
    return {"elapsed_seconds": elapsed, "display_at": backend["upload_at"] + elapsed,
        "upload_complete_monotonic_ns": start, "display_complete_monotonic_ns": end,
        "synthetic": value["synthetic"], "backend_receipt_sha256": digest(backend_receipt), "client_receipt_sha256": digest(receipt)}


def seal_server_evidence(plan, evidence, private_key):
    policy = validate_policy(plan["config"].get("client_attestation_policy"), session_id=plan["config"]["session_id"])
    if public_key_hex(private_key) != policy["server_public_key"]:
        raise ValueError("server signing key differs from frozen performance authority")
    return sign_document({"schema_version": "tensile.performance-server-ledger/v1", "plan_sha256": digest(plan),
        "session_id": policy["session_id"], "server_source_sha256": policy["server_source_sha256"],
        "evidence_sha256": digest(evidence), "synthetic": evidence["synthetic"]}, private_key)


def verify_server_evidence(plan, evidence, signature):
    policy = validate_policy(plan["config"].get("client_attestation_policy"), session_id=plan["config"]["session_id"])
    claim = verify_document(signature, policy["server_public_key"])
    expected = {"schema_version": "tensile.performance-server-ledger/v1", "plan_sha256": digest(plan),
        "session_id": policy["session_id"], "server_source_sha256": policy["server_source_sha256"],
        "evidence_sha256": digest(evidence), "synthetic": evidence["synthetic"]}
    if claim != expected:
        raise ValueError("trusted server event/resource ledger binding differs")
    return True


def server_source_digest():
    """Digest the actual receiver/server implementation, excluding policy/key data."""
    from pathlib import Path
    from versioning.performance import file_digest
    root = Path(__file__).resolve().parents[1]
    paths = ("versioning/performance.py", "versioning/performance_receipts.py", "finetune/eval_performance.py",
        "pipeline/server_proxy.py", "pipeline/server_adapter.py", "pipeline/llamafactory_contract.py")
    return digest({path: file_digest(root / path) for path in paths})


def make_display_receipt(plan, backend_receipt, *, upload_complete_monotonic_ns, display_complete_monotonic_ns):
    """Client-side unsigned payload contract; the trusted instrument signs it."""
    policy = validate_policy(plan["config"].get("client_attestation_policy"), session_id=plan["config"]["session_id"])
    backend = verify_document(backend_receipt, policy["server_public_key"])
    return {"schema_version": "tensile.performance-display-receipt/v1", "plan_sha256": digest(plan),
        "session_id": policy["session_id"], "request_id": backend["request_id"],
        **{k: policy[k] for k in ("client_id", "client_source_sha256", "instrumentation_sha256", "clock_protocol")},
        "backend_receipt_sha256": digest(backend_receipt), "output_sha256": backend["output_sha256"],
        "upload_nonce": backend["upload_nonce"], "upload_complete_monotonic_ns": upload_complete_monotonic_ns,
        "display_complete_monotonic_ns": display_complete_monotonic_ns, "synthetic": backend["synthetic"]}


def load_server_signing_key(path, policy):
    """Read an explicit private 0600/0400 key file; never put its bytes in evidence."""
    from pathlib import Path
    from versioning.performance import file_digest
    path = Path(path)
    file_digest(path)
    if path.stat().st_mode & 0o077:
        raise ValueError("performance signing key file must be private to its owner")
    raw = path.read_bytes()
    try:
        if raw.startswith(b"-----BEGIN"):
            key = serialization.load_pem_private_key(raw, password=None)
        else:
            key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw.decode().strip()))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError("invalid performance Ed25519 signing key file") from exc
    if not isinstance(key, Ed25519PrivateKey) or public_key_hex(key) != policy["server_public_key"]:
        raise ValueError("performance signing key does not match frozen server public key")
    return key


def validate_client_clock_sequence(receipts):
    """One frozen client clock must remain ordered across serial requests."""
    ordered = sorted(receipts, key=lambda row: row[0])
    for (_, before), (_, after) in zip(ordered, ordered[1:]):
        if before["display_complete_monotonic_ns"] > after["upload_complete_monotonic_ns"]:
            raise ValueError("trusted client monotonic clock reset or overlapped serial requests")
    return True
