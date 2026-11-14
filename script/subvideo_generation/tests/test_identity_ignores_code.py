"""R2: batch identity must be built from rules + inputs, never from code hashes.

A batch must stay resumable after the code changes (a comment, a refactor, a
different commit). Only ``schema`` / ``input_mode`` / ``inputs`` / ``rules.digest``
may decide equality; the ``info`` block is informative only.
"""
from __future__ import annotations

import json

from script.subvideo_generation.tests.rules_support import rules_module, write_json


IDENTITY_KEYS = {"schema", "input_mode", "inputs", "rules", "info"}


def test_identity_has_the_documented_shape(project):
    root, g, descriptions, encoded = project

    manifest = g.run(root, plan_only=True)

    identity = manifest["identity"]
    assert set(identity) == IDENTITY_KEYS, (
        f"identity must be {{{', '.join(sorted(IDENTITY_KEYS))}}}, got {sorted(identity)}")
    assert {"code", "loader_code"} & set(identity) == set(), (
        "code hashes must no longer be part of the batch identity")
    assert identity["rules"]["digest"] == rules_module().digest()
    assert set(identity["rules"]) >= {"digest", "fields"}
    assert identity["inputs"], "identity must still pin the input inventory"


def test_resume_succeeds_when_every_code_hash_entry_changed(project, monkeypatch):
    root, g, descriptions, encoded = project
    g.run(root, plan_only=True)
    monkeypatch.setattr(g, "code_identity", lambda: {"invented.py": "1" * 64})
    monkeypatch.setattr(g.coverage.inputs, "orchestration_code", lambda: {"invented": "2" * 64})
    monkeypatch.setattr(g.core, "_code", lambda: {"invented.py": "3" * 64})
    monkeypatch.setattr(g.special_verification, "_code", lambda: {"invented.py": "4" * 64})

    resumed = g.run(root, resume=True)

    assert resumed["complete"] is True, "a code change must not block resuming a valid batch"
    assert len(encoded) == len(resumed["candidates"]), "resume must finish the planned windows"
    assert {"code", "loader_code"} & set(resumed["identity"]) == set()


def test_resume_ignores_the_information_only_info_block(project):
    root, g, descriptions, encoded = project
    g.run(root, plan_only=True)
    manifest_path = root / "data/sub_video/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["identity"]["info"] = {"code_version": "deadbee", "toolchain": {"ffmpeg": "8.1.1"}}
    write_json(manifest_path, manifest)

    resumed = g.run(root, resume=True)

    assert resumed["complete"] is True, "info (code_version/toolchain) must not decide identity"
    assert len(encoded) == len(resumed["candidates"])
