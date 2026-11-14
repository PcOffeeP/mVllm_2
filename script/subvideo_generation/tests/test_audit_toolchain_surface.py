"""F2/F6: the toolchain verdict and the content-only verdict must be visible.

A batch produced by an unpinned FFmpeg must be distinguishable at the top level
of ``audit_outputs()`` and of the official ``summarize()``; a content audit must
say out loud that it verified bytes only, while keeping the legacy ``ok`` flag.
"""
from __future__ import annotations

import pytest

from script.subvideo_generation.tests.rules_support import audit_content, generate_module, make_batch


DEGRADED_TOOLCHAIN = {
    "degraded": True,
    "equivalent_to_verified_toolchain": False,
    "ffmpeg": {"path": "/opt/homebrew/bin/ffmpeg", "version": "ffmpeg version 8.1.1 Copyright (c) test",
               "binary_sha256": "a" * 64},
    "ffprobe": {"path": "/opt/homebrew/bin/ffprobe", "version": "ffprobe version 8.1.1 Copyright (c) test",
                "binary_sha256": "b" * 64},
}
VERIFIED_MARKERS = {"degraded", "equivalent_to_verified_toolchain", "ffmpeg", "ffprobe"}


def _report_degraded_toolchain(monkeypatch):
    """Make every toolchain reporter say "local FFmpeg 8.1.1", not the pinned 4.4.2."""
    g = generate_module()
    monkeypatch.setattr(g.core, "_toolchain", lambda: dict(DEGRADED_TOOLCHAIN))
    monkeypatch.setattr(g.special_verification, "_toolchain", lambda: dict(DEGRADED_TOOLCHAIN))
    if hasattr(g, "_toolchain_info"):
        monkeypatch.setattr(g, "_toolchain_info", lambda: dict(DEGRADED_TOOLCHAIN))
    return g


def test_audit_outputs_surfaces_the_degraded_toolchain(project, monkeypatch):
    root, g, descriptions, encoded = project
    g = _report_degraded_toolchain(monkeypatch)
    manifest = g.run(root, verification="full")  # built while the degraded toolchain is the reported one
    assert manifest["complete"] is True

    audit = g.audit_outputs(root, root / "data/sub_video")

    assert "toolchain" in audit, f"audit_outputs must report the toolchain, got {sorted(audit)}"
    toolchain = audit["toolchain"]
    assert VERIFIED_MARKERS <= set(toolchain), (
        f"the toolchain block must carry the degradation markers, got {sorted(toolchain)}")
    assert toolchain["degraded"] is True
    assert toolchain["equivalent_to_verified_toolchain"] is False
    assert toolchain["ffmpeg"]["version"].startswith("ffmpeg version")
    assert toolchain["ffprobe"]["version"].startswith("ffprobe version")
    assert "not_pinned_toolchain" in audit["limitations"], (
        f"a degraded audit must say so in limitations, got {audit['limitations']}")


def test_official_summary_reports_the_toolchain(project, monkeypatch):
    root, g, descriptions, encoded = project
    g = _report_degraded_toolchain(monkeypatch)
    manifest = g.run(root, plan_only=True, verification="full")

    summary = g.summarize(manifest)

    assert "toolchain" in summary, f"the official summary must report the toolchain, got {sorted(summary)}"
    assert summary["toolchain"]["degraded"] is True
    assert summary["toolchain"]["equivalent_to_verified_toolchain"] is False


def test_content_audit_declares_a_content_only_verdict(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    output, candidates = make_batch(root, legacy=False)

    result = audit_content()(root, output)

    assert result["verdict"] == "content_only", (
        "a content audit must not read as a fully verified batch")
    assert result["ok"] is True, "the existing ok flag must stay"
    assert result["checked"] == len(candidates)
