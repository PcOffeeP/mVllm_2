"""R5: batches written before the rules registry existed.

Such a batch cannot prove which rules produced it, so a strict replay audit is
impossible — but its *content* (clips versus recorded hashes) is still checkable,
and resuming it must be refused with an explicit reason.
"""
from __future__ import annotations

import json

import pytest

from script.subvideo_generation.tests.rules_support import (
    audit_content, make_batch, pilot_module, run_cli, generate_module)


def _legacy_batch(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    output, candidates = make_batch(root, legacy=True)
    return root, output, candidates


def test_content_audit_accepts_a_legacy_batch_without_rules(tmp_path):
    root, output, candidates = _legacy_batch(tmp_path)
    audit = audit_content()

    result = audit(root, output)

    assert result["status"] == "content_audit"
    assert result["batch_schema"] == "tensile-unified-sub-video/1"
    assert result["legacy_batch"] is True, "an identity without a rules digest is a legacy batch"
    assert result["rules_unverifiable"] is True
    assert result["candidates"] == len(candidates)
    assert result["checked"] == len(candidates)
    assert result["missing"] == [] and result["mismatched"] == []
    assert result["ok"] is True, "a legacy batch must not fail merely for lacking a rules digest"


def test_content_audit_detects_a_tampered_legacy_clip(tmp_path):
    root, output, candidates = _legacy_batch(tmp_path)
    victim = output / candidates[0]["output_path"]
    victim.write_bytes(b"rewritten outside the batch")
    audit = audit_content()

    result = audit(root, output)

    assert result["ok"] is False
    assert result["mismatched"], "a clip whose bytes no longer match the record must be reported"
    assert candidates[0]["candidate_id"] in result["mismatched"]


def test_cli_audit_only_reports_a_legacy_content_audit(tmp_path):
    root, output, candidates = _legacy_batch(tmp_path)

    result = run_cli("--project-root", root, "--audit-only", "--output-dir", output)

    assert result.returncode == 0, (
        "a legacy batch must be auditable by content alone, got "
        f"rc={result.returncode} stderr={result.stderr!r}")
    payload = json.loads(result.stdout)
    assert payload["legacy_batch"] is True
    assert payload["rules_unverifiable"] is True
    assert payload["ok"] is True
    assert payload["checked"] == len(candidates)


def test_resume_refuses_a_legacy_batch(tmp_path):
    root, output, candidates = _legacy_batch(tmp_path)
    generate = generate_module()
    before = (output / "manifest.json").read_bytes()

    with pytest.raises(pilot_module().PilotError) as caught:
        generate.run(root, resume=True)

    assert "legacy batch has no rules digest" in str(caught.value), (
        f"a legacy batch must be refused with an actionable reason, got: {caught.value}")
    assert (output / "manifest.json").read_bytes() == before
