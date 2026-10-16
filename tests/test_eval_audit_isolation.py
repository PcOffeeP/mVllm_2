"""Synthetic preflight controls and genuine Mac kernel/request-builder coverage."""
import json
from pathlib import Path
import platform
import stat
import subprocess
import sys

import pytest

from finetune import eval_audit_isolation as audit, eval_review as review, eval_semantics as semantics


def forbidden(*args, **kwargs):
    pytest.fail("operation must not execute")


def probe_receipt():
    value = {"adapter": "mac-sandbox-exec-v1",
        "checks": {name: True for name in audit.PROBE_CHECKS},
        "adapter_sha256": "a" * 64, "technical_isolation_verified": True,
        "synthetic": True, "real_model_deployment_verified": False}
    return {**value, "sha256": semantics.content_digest(value)}


def reseal(value):
    value["sha256"] = semantics.content_digest({k: v for k, v in value.items() if k != "sha256"})
    return value


@pytest.mark.parametrize("arguments", [[], ["--help"]])
def test_default_and_help_do_not_execute(arguments, monkeypatch, capsys):
    monkeypatch.setattr(audit, "run_preflight", forbidden)
    if arguments:
        with pytest.raises(SystemExit) as exc:
            audit.main(arguments)
        assert exc.value.code == 0
    else:
        assert audit.main(arguments) == 0
    assert "--run-probes" in capsys.readouterr().out


def test_import_and_default_cli_do_not_import_review_or_network():
    code = '''import socket,sys
def forbidden(*a,**k): raise AssertionError("network attempted")
socket.socket=forbidden
from finetune import eval_audit_isolation as audit
assert "finetune.eval_review" not in sys.modules
assert audit.main([])==0
assert "finetune.eval_review" not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("arguments", [["--output", "unused.json"],
    ["--run-probes", "false"], ["--verified", "true"], ["--technical-isolation-verified"]])
def test_cli_rejects_claims_and_output_without_explicit_execution(arguments, monkeypatch):
    monkeypatch.setattr(audit, "run_preflight", forbidden)
    with pytest.raises(SystemExit) as exc:
        audit.main(arguments)
    assert exc.value.code == 2


@pytest.mark.parametrize("mutation", ["failed", "missing", "extra", "integer_true",
    "real_deployment", "not_synthetic", "not_technical", "source_drift", "seal_drift"])
def test_probe_evidence_fails_closed(mutation):
    value = probe_receipt()
    if mutation == "failed":
        value["checks"]["network_denied"] = False
    elif mutation == "missing":
        value["checks"].pop("credential_denied")
    elif mutation == "extra":
        value["checks"]["caller_true"] = True
    elif mutation == "integer_true":
        value["checks"]["truth_denied"] = 1
    elif mutation == "real_deployment":
        value["real_model_deployment_verified"] = True
    elif mutation == "not_synthetic":
        value["synthetic"] = False
    elif mutation == "not_technical":
        value["technical_isolation_verified"] = 1
    elif mutation == "source_drift":
        value["adapter_sha256"] = "b" * 64
    if mutation != "seal_drift":
        reseal(value)
    else:
        value["sha256"] = "c" * 64
    with pytest.raises(ValueError):
        audit._validate_probe(value, semantics, {"sources": {"review_adapter": {"sha256": "a" * 64}}})


@pytest.mark.parametrize("error", [ValueError("probe failure"), OSError("sandbox unavailable"),
    subprocess.TimeoutExpired("synthetic worker", 15)])
def test_failure_exits_nonzero_without_stdout_or_report(tmp_path, monkeypatch, capsys, error):
    def fail(**kwargs):
        raise error
    monkeypatch.setattr(audit, "run_preflight", fail)
    output = tmp_path / "must-not-exist.json"
    assert audit.main(["--run-probes", "--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "no success report emitted" in captured.err
    assert not output.exists()


def test_probe_failure_does_not_start_actor_workers(monkeypatch):
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(audit, "_bindings", lambda *args: {"sources": {"review_adapter": {"sha256": "a" * 64}}})
    monkeypatch.setattr(review, "probe_review_isolation", lambda: reseal({**probe_receipt(), "synthetic": False}))
    monkeypatch.setattr(audit, "_actor_requests", forbidden)
    with pytest.raises(ValueError, match="current synthetic adapter"):
        audit.run_preflight(command=["synthetic"])


def test_source_drift_during_preflight_is_rejected(monkeypatch):
    monkeypatch.setattr(audit.platform, "system", lambda: "Darwin")
    bindings = {"sources": {"review_adapter": {"sha256": "a" * 64}}}
    snapshots = iter([bindings, {"changed": True}])
    monkeypatch.setattr(audit, "_bindings", lambda *args: next(snapshots))
    monkeypatch.setattr(review, "probe_review_isolation", probe_receipt)
    monkeypatch.setattr(audit, "_actor_requests", lambda *args: {})
    with pytest.raises(ValueError, match="binding changed"):
        audit.run_preflight(command=["synthetic"])


def test_unsupported_platform_refuses_before_workers(monkeypatch):
    monkeypatch.setattr(audit.platform, "system", lambda: "Linux")
    monkeypatch.setattr(review, "probe_review_isolation", forbidden)
    with pytest.raises(ValueError, match="unavailable"):
        audit.run_preflight(command=["synthetic"])


def test_malformed_actor_result_stops_preflight(monkeypatch):
    def bad_request(**kwargs):
        kwargs["output"].write_text("{}")
        kwargs["output"].chmod(0o400)
        return {}
    monkeypatch.setattr(review, "prepare_isolated_actor_requests", bad_request)
    monkeypatch.setattr(review.LocalOllamaBroker, "generate", forbidden)
    with pytest.raises(ValueError, match="request or receipt mismatch"):
        audit._actor_requests(review, semantics)


def test_output_is_exclusive_regular_and_0600(tmp_path):
    output = tmp_path / "new.json"
    audit.write_output(output, {"synthetic": True})
    assert json.loads(output.read_bytes()) == {"synthetic": True}
    assert stat.S_ISREG(output.stat().st_mode)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        audit.write_output(output, {"bad": True})
    assert json.loads(output.read_bytes()) == {"synthetic": True}


@pytest.mark.parametrize("target_exists", [True, False])
def test_output_symlink_rejected_without_touching_target(tmp_path, target_exists):
    target = tmp_path / "target.json"
    if target_exists:
        target.write_text("original")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(OSError):
        audit.write_output(link, {})
    assert link.is_symlink()
    assert target.read_text() == "original" if target_exists else not target.exists()


def test_parent_symlink_and_parent_traversal_rejected(tmp_path):
    directory = tmp_path / "ordinary"
    directory.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(OSError):
        audit.write_output(link / "new.json", {})
    with pytest.raises(ValueError, match="parent traversal"):
        audit.write_output(directory / ".." / "new.json", {})
    assert list(directory.iterdir()) == []


def test_stdout_mode_emits_only_report(monkeypatch, capsys):
    monkeypatch.setattr(audit, "run_preflight", lambda **kwargs: {"synthetic": True})
    assert audit.main(["--run-probes"]) == 0
    assert json.loads(capsys.readouterr().out) == {"synthetic": True}


@pytest.mark.skipif(platform.system() != "Darwin", reason="actual Mac kernel sandbox only")
def test_actual_kernel_canaries_and_three_anonymous_actor_workers(monkeypatch):
    monkeypatch.setattr(review.LocalOllamaBroker, "generate", forbidden)
    report = audit.run_preflight(command=[sys.executable, "-m", "finetune.eval_audit_isolation", "--run-probes"])
    assert report["synthetic_preflight_passed"] is True
    assert report["synthetic"] is True
    assert report["real_model_deployment_verified"] is False
    assert report["ready_for_real_review"] is False
    assert report["admission_proof"] is False
    assert set(report["probe"]["checks"]) == audit.PROBE_CHECKS
    assert all(value is True for value in report["probe"]["checks"].values())
    request_report = report["actor_request_preflight"]
    assert request_report["broker_called"] is False and request_report["judgments_generated"] is False
    actors = request_report["actors"]
    assert [value["receipt"]["actor_id"] for value in actors] == [
        "synthetic-first", "synthetic-second", "synthetic-third-context"]
    assert all(value["request_count"] == 2 and all(value["checks"].values()) for value in actors)
    assert report["sha256"] == semantics.content_digest({k: v for k, v in report.items() if k != "sha256"})
    assert report["bindings"]["sources"]["review_adapter"]["sha256"] == audit._sha(Path(review.__file__).read_bytes())
