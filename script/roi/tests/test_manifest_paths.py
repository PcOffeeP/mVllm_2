"""Manifest path portability for ROI records.

Every case builds its own synthetic tree under ``tmp_path``; no real media in
``data/`` is read and no real ``data/roi/`` record is written.  The cases pin
the contract of ``core.resolve_manifest_path`` and
``core.Workspace.media_path``: relocating records written by another worktree,
repeated ``data``/``script``/``docs`` suffix positions, ambiguity between
several existing candidates (never guessed), ``..`` escapes, and
``project_root`` being an explicit argument.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from script.roi import core


SOURCE_MEDIA = {
    "width": 640, "height": 480, "frame_rate": "25/1",
    "nominal_frame_rate": "25/1", "frame_count": 250,
    "metadata_frame_count": 250, "frame_count_basis": "metadata",
    "duration": 10.0, "rotation": 0, "pixel_format": "yuv420p",
}

# An absolute root that never exists and is not this project; it stands in for
# the paths recorded by a manifest written in another worktree or machine.
FOREIGN_ROOT = Path("/nonexistent-elsewhere/previous-worktree")

# A missing source must be reported explicitly, never swallowed silently.
ERROR_WORDS = ("发生变化", "缺失", "不存在", "找不到")


def fixed_decision():
    return {
        "mode": "fixed_roi", "pixel_box": {"x": 30, "y": 10, "width": 300, "height": 400},
    }


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def foreign_recorded(*parts: str) -> str:
    return str(FOREIGN_ROOT.joinpath(*parts))


def project_with_source(tmp_path):
    """Project root whose inner ``data/videos/x.mp4`` is the real file."""
    project = tmp_path / "project"
    target = project / "data" / "videos" / "x.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"synthetic source bytes")
    return project, target


def assert_reported_missing(excinfo, recorded: str):
    message = str(excinfo.value)
    assert recorded in message, message
    assert any(word in message for word in ERROR_WORDS), message


def test_existing_absolute_path_is_used_unchanged(tmp_path):
    project, target = project_with_source(tmp_path)

    resolved, note = core.resolve_manifest_path(str(target), project)

    assert resolved == target
    assert note is None
    assert resolved.read_bytes() == b"synthetic source bytes"


def test_missing_absolute_path_is_relocated_under_the_given_project_root(tmp_path):
    project, target = project_with_source(tmp_path)
    recorded = foreign_recorded("data", "videos", "x.mp4")

    resolved, note = core.resolve_manifest_path(recorded, project)

    assert resolved == target
    assert Path(resolved).resolve().is_relative_to(project.resolve())
    assert isinstance(note, str) and note.strip()
    assert recorded in note
    assert str(target) in note
    assert resolved.read_bytes() == target.read_bytes() == b"synthetic source bytes"


@pytest.mark.parametrize("first_segment", ["data", "script", "docs"])
def test_relocation_recognises_data_script_and_docs_suffixes(tmp_path, first_segment):
    project = tmp_path / "project"
    target = project / first_segment / "videos" / "x.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"synthetic relocated bytes")
    recorded = foreign_recorded(first_segment, "videos", "x.mp4")

    resolved, note = core.resolve_manifest_path(recorded, project)

    assert resolved == target
    assert isinstance(note, str) and recorded in note and str(target) in note
    assert resolved.read_bytes() == b"synthetic relocated bytes"


def test_workspace_media_path_appends_the_relocation_note_in_memory(tmp_path):
    project, target = project_with_source(tmp_path)
    recorded = foreign_recorded("data", "videos", "x.mp4")
    workspace = core.Workspace(project / "data" / "videos", tmp_path / "roi", project_root=project)
    assert workspace.path_notes == []

    resolved = workspace.media_path(recorded)

    expected_note = core.resolve_manifest_path(recorded, project)[1]
    assert resolved == target
    assert workspace.path_notes == [expected_note]
    assert recorded in workspace.path_notes[0]
    assert str(target) in workspace.path_notes[0]


def test_missing_in_both_locations_reports_the_recorded_path(tmp_path):
    project = tmp_path / "project"
    (project / "data" / "videos").mkdir(parents=True)
    recorded = foreign_recorded("data", "videos", "gone.mp4")

    with pytest.raises(core.RoiError) as excinfo:
        core.resolve_manifest_path(recorded, project)

    assert_reported_missing(excinfo, recorded)


def test_recorded_relative_path_is_used_as_recorded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "data" / "videos" / "x.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"relative synthetic bytes")
    recorded = "data/videos/x.mp4"

    resolved, note = core.resolve_manifest_path(recorded, tmp_path)

    assert Path(resolved) == Path(recorded)
    assert note is None
    assert Path(resolved).read_bytes() == b"relative synthetic bytes"


def test_relocated_source_is_still_hash_checked_before_saving_a_decision(tmp_path, monkeypatch):
    project, target = project_with_source(tmp_path)
    monkeypatch.setattr(core, "probe_video", lambda path: dict(SOURCE_MEDIA))
    workspace = core.Workspace(project / "data" / "videos", tmp_path / "roi", project_root=project)
    expected_bytes = b"bytes the manifest recorded for x.mp4"
    row = {"video_id": "x", "labels": {},
           "source": {"path": foreign_recorded("data", "videos", "x.mp4"),
                      "sha256": sha256_bytes(expected_bytes), "media": dict(SOURCE_MEDIA)}}

    target.write_bytes(b"different bytes on disk after relocation")
    with pytest.raises(core.RoiError, match="发生变化"):
        workspace.save_decision(row, fixed_decision())
    assert not workspace.decisions_path.exists()

    target.write_bytes(expected_bytes)
    workspace.save_decision(row, fixed_decision())

    saved = json.loads(workspace.decisions_path.read_text(encoding="utf-8"))["decisions"]
    assert [entry["source_video_id"] for entry in saved] == ["x"]
    assert saved[0]["source_sha256"] == row["source"]["sha256"]


def test_reading_and_resolving_leaves_manifest_and_decisions_byte_identical(tmp_path, monkeypatch):
    project = tmp_path / "project"
    videos = project / "data" / "videos"
    videos.mkdir(parents=True)
    target = videos / "x.mp4"
    target.write_bytes(b"synthetic source bytes")
    monkeypatch.setattr(core, "probe_video", lambda path: dict(SOURCE_MEDIA))
    workspace = core.Workspace(videos, tmp_path / "roi", project_root=project)
    recorded = foreign_recorded("data", "videos", "x.mp4")
    digest = sha256_bytes(b"synthetic source bytes")
    core.atomic_json(workspace.manifest_path, {
        "schema": core.SCHEMA,
        "videos": [{"video_id": "x", "source_path": recorded,
                    "source": {"path": recorded, "sha256": digest,
                               "stat": {"size": target.stat().st_size,
                                        "mtime_ns": target.stat().st_mtime_ns},
                               "media": dict(SOURCE_MEDIA)}}],
    })
    core.atomic_json(workspace.decisions_path, {
        "schema": core.SCHEMA, "rule_version": core.RULE_VERSION,
        "decisions": [{"source_video_id": "x", "source_sha256": digest,
                       "source_resolution": [640, 480],
                       "mode": "fixed_roi",
                       "pixel_box": fixed_decision()["pixel_box"]}],
    })
    manifest_bytes = workspace.manifest_path.read_bytes()
    decisions_bytes = workspace.decisions_path.read_bytes()

    manifest = workspace.inventory()
    resolved = workspace.media_path(recorded)
    core.resolve_manifest_path(recorded, project)

    assert [row["video_id"] for row in manifest["videos"]] == ["x"]
    assert resolved == target
    assert workspace.manifest_path.read_bytes() == manifest_bytes
    assert workspace.decisions_path.read_bytes() == decisions_bytes


def test_project_root_none_disables_the_suffix_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nearby = tmp_path / "data" / "videos" / "x.mp4"
    nearby.parent.mkdir(parents=True)
    nearby.write_bytes(b"cwd copy that must not be guessed")
    recorded = foreign_recorded("data", "videos", "x.mp4")
    workspace = core.Workspace(tmp_path / "videos_dir", tmp_path / "roi")

    assert workspace.project_root is None
    assert nearby.is_file()
    with pytest.raises(core.RoiError) as function_error:
        core.resolve_manifest_path(recorded, None)
    assert_reported_missing(function_error, recorded)
    with pytest.raises(core.RoiError) as workspace_error:
        workspace.media_path(recorded)
    assert_reported_missing(workspace_error, recorded)
    assert workspace.path_notes == []


def test_unknown_suffix_outside_the_known_roots_is_never_guessed(tmp_path):
    project = tmp_path / "project"
    outside = project / "other" / "x.mp4"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"file outside data/script/docs")
    recorded = foreign_recorded("other", "x.mp4")

    with pytest.raises(core.RoiError) as excinfo:
        core.resolve_manifest_path(recorded, project)

    assert_reported_missing(excinfo, recorded)
    assert outside.is_file()


def test_required_false_returns_the_recorded_path_without_a_note(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    recorded = foreign_recorded("media", "x.mp4")

    resolved, note = core.resolve_manifest_path(recorded, project, what="ROI 输出", required=False)

    assert Path(resolved) == Path(recorded)
    assert note is None


# --- repeated known segments, ambiguity and ``..`` escapes -----------------
#
# A record may name a path that repeats a known project directory, e.g.
# ``.../data/old-worktree/data/videos/x.mp4`` written by another worktree.
# Every such position is a candidate; the resolver must count *existing*
# candidates and never pick one of several existing files on its own.

REPEATED_ROOT = Path("/nonexistent-probe")
RECORDED_WITH_REPEATED_DATA = str(
    REPEATED_ROOT.joinpath("data", "old-worktree", "data", "videos", "x.mp4")
)
# ``project/data/../../outside.txt`` normalises to a file outside the project
# root, so this suffix must never be joined onto the project root.
RECORDED_WITH_DOTDOT_ESCAPE = "/nonexistent-probe/data/../../outside.txt"


def project_with_repeated_data_candidate(tmp_path):
    """Project whose inner ``data/videos/x.mp4`` is the real recorded source."""
    project = tmp_path / "project"
    real = project / "data" / "videos" / "x.mp4"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"real source bytes")
    return project, real


def decoy_for_repeated_data(project):
    """Outer candidate ``data/old-worktree/data/videos/x.mp4`` built by a worktree."""
    return project / "data" / "old-worktree" / "data" / "videos" / "x.mp4"


def test_inner_known_segment_is_used_when_only_it_exists_under_the_project_root(tmp_path):
    project, real = project_with_repeated_data_candidate(tmp_path)
    decoy = decoy_for_repeated_data(project)
    assert not decoy.exists()

    resolved, note = core.resolve_manifest_path(RECORDED_WITH_REPEATED_DATA, project)

    assert Path(resolved) == real
    assert Path(resolved).resolve().is_relative_to(project.resolve())
    assert Path(resolved).read_bytes() == real.read_bytes() == b"real source bytes"
    assert isinstance(note, str) and note.strip()
    assert RECORDED_WITH_REPEATED_DATA in note
    assert str(real) in note


def test_two_existing_candidates_are_ambiguous_and_never_guessed(tmp_path):
    project, real = project_with_repeated_data_candidate(tmp_path)
    decoy = decoy_for_repeated_data(project)
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b"decoy bytes, not the recorded source")
    resolved = None

    with pytest.raises(core.RoiError) as excinfo:
        resolved, note = core.resolve_manifest_path(RECORDED_WITH_REPEATED_DATA, project)

    message = str(excinfo.value)
    assert "多个候选" in message, message
    assert RECORDED_WITH_REPEATED_DATA in message, message
    assert resolved is None, f"歧义不得返回任何候选（尤其不是诱饵 {decoy}）：{resolved}"
    assert str(decoy) not in message, message
    assert real.read_bytes() == b"real source bytes"
    assert decoy.read_bytes() == b"decoy bytes, not the recorded source"


def test_dotdot_suffix_escaping_the_project_root_is_rejected(tmp_path):
    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"a real file outside the project root")
    resolved = None

    with pytest.raises(core.RoiError) as excinfo:
        resolved, note = core.resolve_manifest_path(RECORDED_WITH_DOTDOT_ESCAPE, project)

    message = str(excinfo.value)
    assert RECORDED_WITH_DOTDOT_ESCAPE in message, message
    assert ".." in message or "非法" in message, message
    assert str(outside) not in message, message
    assert resolved is None, f"逃逸到项目根之外的路径不得返回：{resolved}"
    assert outside.read_bytes() == b"a real file outside the project root"


def test_relocated_path_is_always_inside_the_project_root(tmp_path):
    project = tmp_path / "project"
    target = project / "data" / "deep" / "nested" / "videos" / "x.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"nested synthetic bytes")
    recorded = foreign_recorded("data", "deep", "nested", "videos", "x.mp4")

    resolved, note = core.resolve_manifest_path(recorded, project)

    assert Path(resolved) == target
    assert Path(resolved).resolve().is_relative_to(project.resolve())
    assert Path(resolved).read_bytes() == b"nested synthetic bytes"
    assert isinstance(note, str) and note.strip()


def test_project_root_must_be_passed_explicitly():
    function_parameter = inspect.signature(core.resolve_manifest_path).parameters["project_root"]
    workspace_parameter = inspect.signature(core.Workspace.__init__).parameters["project_root"]

    assert function_parameter.default is inspect.Parameter.empty
    assert workspace_parameter.default is None


def test_required_false_treats_ambiguity_as_unresolved(tmp_path):
    project, real = project_with_repeated_data_candidate(tmp_path)
    decoy = decoy_for_repeated_data(project)
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b"decoy bytes, not the recorded source")

    resolved, note = core.resolve_manifest_path(
        RECORDED_WITH_REPEATED_DATA, project, what="ROI 输出", required=False
    )

    assert Path(resolved) == Path(RECORDED_WITH_REPEATED_DATA)
    assert note is None
    assert Path(resolved) not in {real, decoy}


def test_required_false_returns_the_recorded_dotdot_path_without_a_note(tmp_path):
    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"a real file outside the project root")

    resolved, note = core.resolve_manifest_path(
        RECORDED_WITH_DOTDOT_ESCAPE, project, what="ROI 输出", required=False
    )

    assert Path(resolved) == Path(RECORDED_WITH_DOTDOT_ESCAPE)
    assert note is None
    assert Path(resolved) != outside
