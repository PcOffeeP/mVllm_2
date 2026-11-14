"""Virtual-mode batch identity: rules fingerprint instead of code hashes.

``--videos-dir`` batches must be judged by the same four fields as the official
batch (``schema`` / ``input_mode`` / ``inputs`` / ``rules.digest``). Moving code,
renaming a module or editing a comment must not invalidate a batch; changing the
window rules or the input bytes must.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from script.subvideo_generation.tests.rules_support import (
    digest_of, load, pilot_module, run_cli, write_json)
from script.subvideo_generation.tests.test_videos_dir_mode import encode_window_source


VIRTUAL_MODULE = "script.subvideo_generation.virtual"
VIRTUAL_SCHEMA = "tensile-virtual-sub-video/1"


def virtual_module():
    return load(VIRTUAL_MODULE)


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg required for the virtual identity contract")
    directory = tmp_path_factory.mktemp("virtual-identity-media") / "videos"
    directory.mkdir(parents=True)
    encode_window_source(directory / "short_03s.mp4", 3)
    return directory


def test_virtual_resume_survives_a_code_side_change(videos, tmp_path, monkeypatch):
    """A batch stays resumable after the code changes; only rules + inputs decide."""
    virtual = virtual_module()
    pilot = load("script.subvideo_generation.pilot.pilot")
    project = tmp_path / "project"
    project.mkdir()
    output = project / "batch"
    first = virtual.run(project, videos, output)
    assert first["complete"] is True
    real_sha256 = pilot.sha256_file

    # "The code changed": every source-file hash now reports different bytes, and
    # the information-only identity block is junk. Neither may decide identity.
    monkeypatch.setattr(
        pilot, "sha256_file",
        lambda path: "0" * 64 if Path(path).suffix == ".py" else real_sha256(path))
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["identity"]["info"] = {"code_version": "deadbee", "toolchain": {"ffmpeg": "8.1.1"}}
    write_json(manifest_path, manifest)

    resumed = virtual.run(project, videos, output, resume=True)

    assert resumed["complete"] is True, "a code-side change must not block resuming a virtual batch"
    assert {"code", "strategy"} & set(resumed["identity"]) == set(), (
        "the virtual identity must carry no code hashes and no ad-hoc strategy block, got "
        f"{sorted(resumed['identity'])}")


def _legacy_virtual_batch(project, videos):
    """Reproduce a pre-change virtual batch: identity with code+strategy, no rules."""
    output = project / "legacy_batch"
    video = videos / "short_03s.mp4"
    source_sha = digest_of(video)
    (output / "videos").mkdir(parents=True)
    name = "short_03s_window_01"
    clip = output / "videos" / f"{name}.mp4"
    clip.write_bytes(b"synthetic legacy virtual clip")
    candidate = {"candidate_id": name, "filename": f"{name}.mp4",
                 "output_path": f"videos/{name}.mp4", "source_video_id": "short_03s",
                 "role": "window", "sequence": 1, "start_frame": 0, "end_frame": 30,
                 "start_seconds": 0.0, "end_seconds": 3.0, "status": "cropped",
                 "output_sha256": digest_of(clip)}
    write_json(output / "manifest.json", {
        "schema": VIRTUAL_SCHEMA, "input_mode": "videos_dir", "for_training": False,
        "published": False, "plan_only": False,
        "identity": {"schema": VIRTUAL_SCHEMA, "input_mode": "videos_dir",
                     "videos": {"short_03s.mp4": source_sha},
                     "strategy": {"window_seconds": 20, "step_seconds": 15, "role": "window"},
                     "code": {"virtual.py": "1" * 64}},
        "sources": [{"video_id": "short_03s", "source_path": str(video),
                     "source_sha256": source_sha, "status": "cropped"}],
        "candidates": [candidate], "complete": True})
    write_json(output / "summary.json", {
        "source_count": 1, "source_status": {"cropped": 1},
        "candidate_count": 1, "candidate_status": {"cropped": 1},
        "complete": True, "for_training": False, "published": False,
        "input_mode": "videos_dir"})
    return output, [candidate]


def test_legacy_virtual_batch_content_audit_and_resume_refusal(tmp_path, videos):
    project = tmp_path / "project"
    project.mkdir()
    output, candidates = _legacy_virtual_batch(project, videos)

    audit = run_cli("--project-root", project, "--audit-only", "--output-dir", output)

    assert audit.returncode == 0, (
        "a legacy virtual batch must be auditable by content alone, got "
        f"rc={audit.returncode} stderr={audit.stderr!r}")
    payload = json.loads(audit.stdout)
    assert payload["status"] == "content_audit"
    assert payload["batch_schema"] == VIRTUAL_SCHEMA
    assert payload["legacy_batch"] is True, "an identity without a rules digest is a legacy batch"
    assert payload["rules_unverifiable"] is True
    assert payload["ok"] is True
    assert payload["checked"] == len(candidates)

    before = (output / "manifest.json").read_bytes()
    with pytest.raises(pilot_module().PilotError) as caught:
        virtual_module().run(project, videos, output, resume=True)

    assert "legacy batch has no rules digest" in str(caught.value), (
        f"a legacy virtual batch must be refused with an actionable reason, got: {caught.value}")
    assert (output / "manifest.json").read_bytes() == before
