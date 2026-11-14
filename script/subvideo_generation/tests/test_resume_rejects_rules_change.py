"""R3: a different generation rule set is a different batch."""
from __future__ import annotations

import pytest

from script.subvideo_generation.tests.rules_support import rules_module


def _drift(rules, monkeypatch, **changes):
    """Change one rule value and make sure the digest really moved."""
    drifted = dict(rules.registry(), **changes)
    monkeypatch.setattr(rules, "registry", lambda: drifted)
    if hasattr(rules.digest, "cache_clear"):
        rules.digest.cache_clear()
    return drifted


def test_resume_refuses_a_changed_window_policy(project, monkeypatch):
    root, g, descriptions, encoded = project
    manifest = g.run(root, plan_only=True)
    assert "rules" in manifest["identity"], (
        "identity must record the rules registry as {digest, fields}")
    recorded = manifest["identity"]["rules"]["digest"]
    rules = rules_module()
    drifted = _drift(rules, monkeypatch, window_seconds=25)

    assert rules.registry() == drifted
    assert rules.digest() != recorded, (
        "the patched registry must produce a different digest, otherwise the "
        "identity cannot record the rule set at all")
    manifest_path = root / "data/sub_video/manifest.json"
    before = manifest_path.read_bytes()

    with pytest.raises(g.base.PilotError) as caught:
        g.run(root, resume=True)

    assert "rules digest differs" in str(caught.value), (
        f"a changed rule set must be named explicitly, got: {caught.value}")
    assert manifest_path.read_bytes() == before, "a refused resume must not rewrite the batch"
    assert not encoded, "a refused resume must not encode anything"


def test_resume_refuses_a_changed_coverage_criterion(project, monkeypatch):
    """The criterion string alone decides which sources get which windows."""
    root, g, descriptions, encoded = project
    manifest = g.run(root, plan_only=True)
    recorded = manifest["identity"]["rules"]["digest"]
    rules = rules_module()
    patched = "video_id in coverage_ids"

    monkeypatch.setitem(rules.STRATEGY_RULE, "coverage", patched)

    assert rules.registry()["coverage_rule"] == patched
    assert rules.digest() != recorded, (
        "the identity digest must follow the criterion the registry publishes")
    manifest_path = root / "data/sub_video/manifest.json"
    before = manifest_path.read_bytes()

    with pytest.raises(g.base.PilotError) as caught:
        g.run(root, resume=True)

    assert "rules digest differs" in str(caught.value), (
        f"a changed coverage criterion must be named explicitly, got: {caught.value}")
    assert manifest_path.read_bytes() == before, "a refused resume must not rewrite the batch"
    assert not encoded, "a refused resume must not encode anything"


def test_resume_refuses_a_changed_special_rule(project, monkeypatch):
    root, g, descriptions, encoded = project
    manifest = g.run(root, plan_only=True)
    assert "rules" in manifest["identity"], (
        "identity must record the rules registry as {digest, fields}")
    recorded = manifest["identity"]["rules"]["digest"]
    rules = rules_module()
    _drift(rules, monkeypatch, special_anchor_frames=[727, 729])

    assert rules.digest() != recorded

    with pytest.raises(g.base.PilotError) as caught:
        g.run(root, resume=True)

    assert "rules digest differs" in str(caught.value)
    assert not encoded
