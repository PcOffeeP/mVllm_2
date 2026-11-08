"""Canonical ROI organization uses adopted bytes, without encoding or data loss."""
from __future__ import annotations

import copy
import csv
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from script.roi import core


MEDIA = {"width": 640, "height": 480, "frame_rate": "25/1",
         "nominal_frame_rate": "25/1", "frame_count": 250,
         "metadata_frame_count": 250, "frame_count_basis": "metadata",
         "duration": 10., "rotation": 0, "pixel_format": "yuv420p"}
BOX = {"x": 30, "y": 10, "width": 300, "height": 400}


def by_id(manifest):
    return {row["video_id"]: row for row in manifest["videos"]}


@pytest.fixture
def adopted_work(tmp_path, monkeypatch):
    videos = tmp_path / "sources"
    videos.mkdir()
    ids = ("video_0001", "video_0002", "video_0093")
    for identifier in ids:
        (videos / f"{identifier}.mp4").write_bytes(f"current source {identifier}".encode())
    labels = tmp_path / "labels.csv"
    with labels.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "断裂位置", "标注备注"])
        writer.writeheader()
        writer.writerows({"id": key, "断裂位置": "标距内", "标注备注": f"original {key}"} for key in ids)
    work = core.Workspace(videos, tmp_path / "roi", labels=labels)
    calls = []

    def probe(path):
        path = Path(path)
        if path.parent == videos:
            return dict(MEDIA)
        if path.read_bytes().startswith(b"current short 0093 ROI"):
            return {**MEDIA, "width": 642, "height": 856}
        return {**MEDIA, "width": 300, "height": 400}

    def run(command, **kwargs):
        calls.append(command)
        if "-c:v" in command:
            pytest.fail("Organizing already-adopted ROI files must never encode them")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core, "probe_video", probe)
    monkeypatch.setattr(core, "decoded_frame_count", lambda path: 250)
    monkeypatch.setattr(core.subprocess, "run", run)
    source_rows = by_id(work.refresh())
    work.existing_media_dir.mkdir(parents=True)
    decisions, entries = [], []
    for identifier in ids:
        source_sha = source_rows[identifier]["source"]["sha256"]
        if identifier == "video_0093":
            source_sha = "0" * 64  # Historical long source is not the selected short source.
        candidate = work.existing_media_dir / f"{identifier}.mp4"
        candidate.write_bytes(f"old ROI pixels {identifier}".encode())
        decision = {"source_video_id": identifier, "source_sha256": source_sha,
                    "source_resolution": [640, 480], "source_rotation": 0,
                    "mode": "fixed_roi", "pixel_box": dict(BOX)}
        decisions.append(decision)
        entries.append({"source_video_id": identifier, "source_sha256": source_sha,
                        "output_sha256": core.sha256_file(candidate), "mode": "fixed_roi",
                        "pixel_box": dict(BOX), "input_resolution": [640, 480],
                        "output_resolution": [300, 400], "frame_count": 250,
                        "source_frame_count": 250, "duration": 10., "source_duration": 10.,
                        "nominal_frame_rate": "25/1", "source_nominal_frame_rate": "25/1",
                        "video_filter": "crop=300:400:30:10,setsar=1"})
    core.atomic_json(work.candidate_path, {"decisions": decisions})
    core.atomic_json(work.existing_manifest, {"videos": entries})
    legacy = by_id(work.refresh())
    assert legacy["video_0093"]["status"] == "needs_decision"

    # A selected-but-equivalent crop has an explicitly relinked old result,
    # like current video_0001. Preserve its existing draft and history.
    work.save_draft(legacy["video_0001"], {"mode": "fixed_roi", "pixel_box": dict(BOX),
                                         "pending_reason": "saved crop note"})
    work.save_decision(by_id(work.refresh())["video_0001"],
                       {"mode": "fixed_roi", "pixel_box": dict(BOX)})
    manifest = work.inventory()
    current = by_id(manifest)["video_0001"]
    current["output"] = copy.deepcopy(legacy["video_0001"]["output"])
    current["status"] = "success"
    current.setdefault("history", {})[current["recipe_hash"]] = {
        "output": copy.deepcopy(current["output"]), "output_review": None, "output_review_draft": None}
    core.atomic_json(work.manifest_path, manifest)

    short_output = tmp_path / "current-short-0093.mp4"
    short_output.write_bytes(b"current short 0093 ROI result")
    short_source = by_id(work.refresh())["video_0093"]["source"]
    work.import_generated("video_0093", short_output,
                          {"source_video_id": "video_0093", "source_sha256": short_source["sha256"],
                           "source_resolution": [640, 480], "source_rotation": 0,
                           "mode": "no_crop", "pixel_box": None}, core.sha256_file(short_output),
                          expected_source_sha256=short_source["sha256"], generated_on="synthetic training host")
    before = work.refresh()
    assert before["complete"] is True
    first = by_id(before)["video_0001"]
    state = work.label_review_state(first)
    work.save_label_review(first, {"断裂位置": "夹持根部"}, expected_revision=state["revision_id"])
    calls.clear()
    return work, calls


def original_bytes(work):
    paths = list(work.videos_dir.glob("*.mp4")) + list(work.existing_media_dir.glob("*.mp4"))
    paths += [work.labels, work.decisions_path, work.drafts_path, work.label_reviews_path,
              work.candidate_path, work.existing_manifest]
    return {path: path.read_bytes() for path in paths}


def test_organize_adopted_outputs_preserves_pixels_labels_history_and_refresh_identity(adopted_work):
    work, calls = adopted_work
    before = work.refresh()
    old = by_id(before)
    immutable = original_bytes(work)
    old_review = work.label_review_state(old["video_0001"])
    result = work.organize_videos()
    assert result["complete"] is True
    assert result["total"] == 3
    assert result["summary"] == {"success": 3}
    for identifier, row in by_id(result).items():
        target = work.output_dir / "videos" / f"{identifier}.mp4"
        assert row["output"]["path"] == str(target)
        assert target.read_bytes() == Path(old[identifier]["output"]["path"]).read_bytes()
        assert row["output"]["sha256"] == old[identifier]["output"]["sha256"]
        assert set(old[identifier].get("history", {})) <= set(row.get("history", {}))
        assert row["visual_review"] == old[identifier]["visual_review"]
    assert (work.output_dir / "videos/video_0093.mp4").read_bytes() != (work.existing_media_dir / "video_0093.mp4").read_bytes()
    assert not calls
    for path, value in immutable.items():
        assert path.read_bytes() == value
    reopened = core.Workspace(work.videos_dir, work.output_dir, labels=work.labels)
    for manifest in (work.refresh(), reopened.refresh(), reopened.organize_videos()):
        assert manifest["complete"] is True
        assert all(Path(row["output"]["path"]).parent == work.output_dir / "videos" for row in manifest["videos"])
    updated = reopened.label_review_state(by_id(reopened.inventory())["video_0001"])
    assert updated["revision_id"] == old_review["revision_id"]
    assert updated["values"]["断裂位置"] == "夹持根部"
    assert updated["history_count"] == old_review["history_count"]
    assert not calls


def test_conflicting_canonical_file_is_not_overwritten_or_published(adopted_work):
    work, calls = adopted_work
    target = work.output_dir / "videos/video_0093.mp4"
    target.parent.mkdir()
    target.write_bytes((work.existing_media_dir / "video_0093.mp4").read_bytes())
    before = core.load_json(work.manifest_path)
    with pytest.raises(core.RoiError):
        work.organize_videos()
    assert target.read_bytes() == (work.existing_media_dir / "video_0093.mp4").read_bytes()
    after = core.load_json(work.manifest_path)
    assert {r["video_id"]: r["output"]["path"] for r in after["videos"]} == {r["video_id"]: r["output"]["path"] for r in before["videos"]}
    assert not calls


@pytest.mark.parametrize("changed", ["source", "output", "missing"])
def test_changed_or_missing_input_prevents_partial_publication_and_can_be_retried(adopted_work, changed):
    work, calls = adopted_work
    before = core.load_json(work.manifest_path)
    row = by_id(before)["video_0002"]
    path = Path(row["source"]["path"] if changed == "source" else row["output"]["path"])
    original = path.read_bytes()
    if changed == "missing":
        path.unlink()
    else:
        path.write_bytes(b"changed identity")
    with pytest.raises(core.RoiError):
        work.organize_videos()
    after = core.load_json(work.manifest_path)
    assert {r["video_id"]: r["output"]["path"] for r in after["videos"]} == {r["video_id"]: r["output"]["path"] for r in before["videos"]}
    path.write_bytes(original)
    assert work.organize_videos()["complete"] is True
    assert not calls


def test_copy_failure_keeps_active_manifest_and_can_resume_verified_copies(adopted_work, monkeypatch):
    work, calls = adopted_work
    before = work.manifest_path.read_bytes()
    copyfile = core.shutil.copyfile
    count = 0

    def failing_copy(source, destination, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("synthetic interrupted copy")
        return copyfile(source, destination, *args, **kwargs)

    monkeypatch.setattr(core.shutil, "copyfile", failing_copy)
    with pytest.raises((core.RoiError, OSError)):
        work.organize_videos()
    assert work.manifest_path.read_bytes() == before
    existing = list((work.output_dir / "videos").glob("*.mp4"))
    assert existing
    first = existing[0]
    first_hash = core.sha256_file(first)
    monkeypatch.setattr(core.shutil, "copyfile", copyfile)
    result = work.organize_videos()
    assert result["complete"] is True
    assert core.sha256_file(first) == first_hash
    assert not calls


@pytest.mark.parametrize("changed", ["source", "output"])
def test_input_drift_during_copy_cannot_publish_the_old_identity(adopted_work, monkeypatch, changed):
    work, calls = adopted_work
    before = work.manifest_path.read_bytes()
    source = (work.videos_dir / "video_0002.mp4" if changed == "source" else work.existing_media_dir / "video_0002.mp4")
    original = source.read_bytes()
    copyfile = core.shutil.copyfile
    did_change = False

    def change_source_after_copy(src, dst, *args, **kwargs):
        nonlocal did_change
        result = copyfile(src, dst, *args, **kwargs)
        if not did_change:
            source.write_bytes(b"input changed during organization")
            did_change = True
        return result

    monkeypatch.setattr(core.shutil, "copyfile", change_source_after_copy)
    with pytest.raises(core.RoiError):
        work.organize_videos()
    assert work.manifest_path.read_bytes() == before
    source.write_bytes(original)
    monkeypatch.setattr(core.shutil, "copyfile", copyfile)
    assert work.organize_videos()["complete"] is True
    assert not calls


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_canonical_replacement_is_not_hidden_by_a_good_historical_copy(adopted_work, damage):
    work, _ = adopted_work
    result = work.organize_videos()
    row = by_id(result)["video_0002"]
    target = Path(row["output"]["path"])
    original = target.read_bytes()
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"unexpected canonical file replacement")
    reopened = core.Workspace(work.videos_dir, work.output_dir, labels=work.labels)
    for active in (work, work, reopened, reopened):
        after = active.refresh(verify_source_ids={"video_0002"})
        row = by_id(after)["video_0002"]
        assert row["status"] != "success"
        assert after["complete"] is False
        assert not row.get("output")
    assert (work.existing_media_dir / "video_0002.mp4").is_file()
    target.write_bytes(original)
    restored = reopened.refresh(verify_source_ids={"video_0002"})
    row = by_id(restored)["video_0002"]
    assert restored["complete"] is True
    assert row["output"]["path"] == str(target)
    assert row["output"]["sha256"] == core.sha256_file(target)


def test_a_new_crop_keeps_the_organized_output_as_a_historical_result(adopted_work):
    work, calls = adopted_work
    before = work.organize_videos()
    row = by_id(before)["video_0001"]
    target = Path(row["output"]["path"])
    original = target.read_bytes()
    old_key = row["recipe_hash"]
    work.save_decision(row, {"mode": "fixed_roi", "pixel_box": {**BOX, "x": 32}})
    changed = by_id(work.inventory())["video_0001"]
    assert changed["status"] == "ready"
    assert changed["history"][old_key]["output"]["path"] == str(target)
    assert target.read_bytes() == original
    assert not calls


def test_refresh_waits_for_organization_lock_and_cannot_restore_old_paths(adopted_work, monkeypatch):
    work, calls = adopted_work
    second = core.Workspace(work.videos_dir, work.output_dir, labels=work.labels)
    copying = threading.Event()
    release = threading.Event()
    refresh_started = threading.Event()
    refresh_finished = threading.Event()
    copyfile = core.shutil.copyfile
    blocked_once = False
    errors = []

    def blocked_copy(src, dst, *args, **kwargs):
        nonlocal blocked_once
        if not blocked_once:
            blocked_once = True
            copying.set()
            assert release.wait(5)
        return copyfile(src, dst, *args, **kwargs)

    monkeypatch.setattr(core.shutil, "copyfile", blocked_copy)

    def organize():
        try:
            work.organize_videos()
        except BaseException as exc:
            errors.append(exc)

    def refresh():
        refresh_started.set()
        try:
            second.refresh()
        except BaseException as exc:
            errors.append(exc)
        finally:
            refresh_finished.set()

    first_thread = threading.Thread(target=organize)
    second_thread = threading.Thread(target=refresh)
    first_thread.start()
    assert copying.wait(3)
    second_thread.start()
    try:
        assert refresh_started.wait(3)
        assert not refresh_finished.wait(.1)
    finally:
        release.set()
        first_thread.join(5)
        second_thread.join(5)
    assert not errors
    assert not first_thread.is_alive() and not second_thread.is_alive()
    result = second.inventory()
    assert result["complete"] is True
    assert all(Path(row["output"]["path"]).parent == work.output_dir / "videos" for row in result["videos"])
    assert not calls


@pytest.mark.parametrize("target_kind", ["folder", "file"])
def test_symbolic_link_targets_are_not_followed_or_used_for_publication(adopted_work, tmp_path, target_kind):
    work, calls = adopted_work
    folder = work.output_dir / "videos"
    outside = tmp_path / "outside"
    outside.mkdir()
    if target_kind == "folder":
        folder.symlink_to(outside, target_is_directory=True)
    else:
        folder.mkdir()
        protected = outside / "protected.mp4"
        protected.write_bytes(b"external file must survive")
        (folder / "video_0001.mp4").symlink_to(protected)
    before = work.manifest_path.read_bytes()
    with pytest.raises(core.RoiError):
        work.organize_videos()
    assert work.manifest_path.read_bytes() == before
    if target_kind == "folder":
        assert list(outside.iterdir()) == []
    else:
        assert protected.read_bytes() == b"external file must survive"
    assert not calls


def test_organization_cli_uses_current_output_manifest_and_reports_verified_directory(adopted_work, monkeypatch, capsys):
    import importlib.util
    import json
    import sys

    work, calls = adopted_work
    monkeypatch.setitem(sys.modules, "core", core)
    roi_spec = importlib.util.spec_from_file_location("roi", Path(core.__file__).with_name("roi.py"))
    roi_entry = importlib.util.module_from_spec(roi_spec)
    monkeypatch.setitem(sys.modules, "roi", roi_entry)
    roi_spec.loader.exec_module(roi_entry)
    spec = importlib.util.spec_from_file_location("organize_entry_for_test", Path(core.__file__).with_name("organize_videos.py"))
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    result = entry.main(["--project-root", str(work.output_dir.parent),
                         "--videos-dir", str(work.videos_dir), "--output-dir", str(work.output_dir),
                         "--labels", str(work.labels)])
    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total"] == 3
    assert report["complete"] is True
    assert report["videos_dir"] == str(work.output_dir / "videos")
    assert work.label_review_state(by_id(work.inventory())["video_0001"])["values"]["断裂位置"] == "夹持根部"
    assert not calls


def test_new_source_discovered_after_the_adopted_snapshot_requires_explicit_reconciliation(adopted_work):
    work, calls = adopted_work
    before = work.manifest_path.read_bytes()
    extra = work.videos_dir / "video_new.mp4"
    extra.write_bytes(b"new source was not part of adopted ROI snapshot")
    with pytest.raises(core.RoiError):
        work.organize_videos()
    assert work.manifest_path.read_bytes() == before
    assert not list((work.output_dir / "videos").glob("*.mp4"))
    assert not calls
