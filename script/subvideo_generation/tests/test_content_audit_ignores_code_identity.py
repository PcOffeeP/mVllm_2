"""R6: content audit judges bytes on disk, not the identity of the code or rules."""
from __future__ import annotations

from script.subvideo_generation.tests.rules_support import audit_content, generate_module, make_batch


def _batch(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    output, candidates = make_batch(root, legacy=False)
    return root, output, candidates


def _scramble_code_hashes(monkeypatch):
    g = generate_module()
    monkeypatch.setattr(g, "code_identity", lambda: {"invented.py": "1" * 64})
    monkeypatch.setattr(g.coverage.inputs, "orchestration_code", lambda: {"invented": "2" * 64})
    monkeypatch.setattr(g.core, "_code", lambda: {"invented.py": "3" * 64})
    monkeypatch.setattr(g.special_verification, "_code", lambda: {"invented.py": "4" * 64})


def test_content_audit_ignores_current_code_hashes(tmp_path, monkeypatch):
    root, output, candidates = _batch(tmp_path)
    _scramble_code_hashes(monkeypatch)

    result = audit_content()(root, output)

    assert result["ok"] is True, "content audit must not compare code hashes"
    assert result["legacy_batch"] is False
    assert result["rules_unverifiable"] is False
    assert result["candidates"] == len(candidates)
    assert result["checked"] == len(candidates)
    assert result["missing"] == [] and result["mismatched"] == []


def test_content_audit_still_reports_missing_and_unrecorded_clips(tmp_path, monkeypatch):
    root, output, candidates = _batch(tmp_path)
    _scramble_code_hashes(monkeypatch)
    (output / candidates[1]["output_path"]).unlink()
    (output / "videos" / "stray.mp4").write_bytes(b"not part of the batch")

    result = audit_content()(root, output)

    assert result["ok"] is False, "missing and unrecorded clips must fail the content audit"
    assert candidates[1]["candidate_id"] in result["missing"]
