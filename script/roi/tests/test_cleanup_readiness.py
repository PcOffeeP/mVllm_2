"""Cleanup preparation must preserve adopted ROI identity and user records."""
from __future__ import annotations

from pathlib import Path

import copy

import pytest

from script.roi import core
from script.roi.tests.test_organize_videos import adopted_work, by_id


def user_record_bytes(work):
    paths = [work.labels, work.decisions_path, work.drafts_path,
             work.label_reviews_path, work.candidate_path, work.existing_manifest]
    return {path: path.read_bytes() for path in paths}


def test_canonical_outputs_survive_duplicate_media_removal_and_reopen(adopted_work):
    work, calls = adopted_work
    organized = work.organize_videos()
    records = user_record_bytes(work)
    original_rois = {row["video_id"]: Path(row["output"]["path"]).read_bytes()
                     for row in organized["videos"]}
    legacy_0093 = (work.existing_media_dir / "video_0093.mp4").read_bytes()
    for row in organized["videos"]:
        if row["video_id"] != "video_0093":
            (work.existing_media_dir / (row["video_id"] + ".mp4")).unlink()
        old_path = row["output"].get("organized_from")
        if old_path and Path(old_path).is_file() and row["video_id"] == "video_0093":
            Path(old_path).unlink()

    reopened = core.Workspace(work.videos_dir, work.output_dir, labels=work.labels)
    for active in (work, reopened, reopened):
        result = active.refresh(verify_source_ids=set(original_rois))
        assert result["complete"] is True
        assert result["summary"] == {"success": 3}
        for row in result["videos"]:
            expected = work.organized_videos_dir / (row["video_id"] + ".mp4")
            assert row["output"]["path"] == str(expected)
            assert expected.read_bytes() == original_rois[row["video_id"]]
    assert (work.existing_media_dir / "video_0093.mp4").read_bytes() == legacy_0093
    for path, before in records.items():
        assert path.read_bytes() == before
    assert reopened.label_review_state(by_id(result)["video_0001"])["values"]["断裂位置"] == "夹持根部"
    assert not calls


def test_canonical_current_0093_cannot_be_replaced_by_old_same_named_roi(adopted_work):
    work, calls = adopted_work
    organized = work.organize_videos()
    records = user_record_bytes(work)
    row = by_id(organized)["video_0093"]
    canonical = Path(row["output"]["path"])
    old_long_result = (work.existing_media_dir / "video_0093.mp4").read_bytes()
    canonical.write_bytes(old_long_result)

    for active in (work, core.Workspace(work.videos_dir, work.output_dir, labels=work.labels)):
        result = active.refresh(verify_source_ids={"video_0093"})
        current = by_id(result)["video_0093"]
        assert current["status"] != "success"
        assert not current.get("output")
        assert result["complete"] is False
    assert canonical.read_bytes() == old_long_result
    for path, before in records.items():
        assert path.read_bytes() == before
    assert not calls


def test_missing_manifest_does_not_adopt_current_0093_from_filename(adopted_work):
    work, calls = adopted_work
    organized = work.organize_videos()
    records = user_record_bytes(work)
    canonical = Path(by_id(organized)["video_0093"]["output"]["path"])
    original = canonical.read_bytes()
    work.manifest_path.unlink()

    result = core.Workspace(work.videos_dir, work.output_dir, labels=work.labels).inventory()
    current = by_id(result)["video_0093"]
    assert current["status"] != "success"
    assert not current.get("output")
    assert result["complete"] is False
    assert canonical.read_bytes() == original
    for path, before in records.items():
        assert path.read_bytes() == before
    assert not calls


def workspace_bytes(work):
    paths = list(work.output_dir.rglob("*")) + list(work.videos_dir.glob("*.mp4")) + [work.labels]
    return {path: path.read_bytes() for path in paths if path.is_file()}


def test_cleanup_preview_is_read_only_and_keeps_the_distinct_historical_0093(adopted_work):
    work, calls = adopted_work
    organized = work.organize_videos()
    before = workspace_bytes(work)

    report = work.prepare_cleanup()

    assert report["applied"] is False
    assert report["complete"] is True
    assert report["total"] == 3
    duplicates = {Path(item["path"]): item for item in report["duplicate_media"]}
    assert work.existing_media_dir / "video_0001.mp4" in duplicates
    assert work.existing_media_dir / "video_0002.mp4" in duplicates
    old_long = work.existing_media_dir / "video_0093.mp4"
    assert old_long not in duplicates
    assert old_long in {Path(item["path"]) for item in report["retained_media"]}
    current_short_original = Path(by_id(organized)["video_0093"]["output"]["organized_from"])
    assert current_short_original in duplicates
    assert any(item["video_id"] == "video_0001" for item in report["reference_updates"])
    assert workspace_bytes(work) == before
    assert not calls


def test_applying_cleanup_preparation_rebinds_matching_history_and_never_deletes_media(adopted_work):
    work, calls = adopted_work
    organized = work.organize_videos()
    records = user_record_bytes(work)
    files = {path: value for path, value in workspace_bytes(work).items() if path.suffix == ".mp4"}
    prior = by_id(organized)["video_0001"]
    canonical = work.organized_videos_dir / "video_0001.mp4"
    original = work.existing_media_dir / "video_0001.mp4"
    old_keys = [key for key, entry in prior["history"].items()
                if entry.get("output", {}).get("path") == str(original)]
    assert old_keys
    review = work.label_review_state(prior)

    report = work.prepare_cleanup(apply=True)

    assert report["applied"] is True
    current = by_id(core.load_json(work.manifest_path))["video_0001"]
    for key in old_keys:
        output = current["history"][key]["output"]
        assert output["path"] == str(canonical)
        assert output["sha256"] == prior["output"]["sha256"]
        assert {"path": str(original), "sha256": output["sha256"],
                "role": "historical_provenance"} in output["historical_locations"]
    for path, value in files.items():
        assert path.read_bytes() == value
    for path, value in records.items():
        assert path.read_bytes() == value
    refreshed = work.refresh()
    assert refreshed["complete"] is True
    after_review = work.label_review_state(by_id(refreshed)["video_0001"])
    assert after_review["revision_id"] == review["revision_id"]
    assert after_review["values"] == review["values"]
    repeated = work.prepare_cleanup(apply=True)
    assert repeated["reference_updates"] == []
    assert not calls


def test_same_hash_history_with_different_geometry_cannot_be_rebound(adopted_work):
    work, calls = adopted_work
    work.organize_videos()
    manifest = core.load_json(work.manifest_path)
    row = by_id(manifest)["video_0001"]
    original = work.existing_media_dir / "video_0001.mp4"
    history = next(entry for entry in row["history"].values()
                   if entry.get("output", {}).get("path") == str(original))
    history["output"]["geometry"] = copy.deepcopy(history["output"]["geometry"])
    history["output"]["geometry"]["effective_pixel_box"]["x"] += 2
    core.atomic_json(work.manifest_path, manifest)
    before = workspace_bytes(work)

    with pytest.raises(core.RoiError):
        work.prepare_cleanup(apply=True)

    assert workspace_bytes(work) == before
    assert not calls


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_cleanup_cannot_publish_when_canonical_media_is_unverified(adopted_work, damage):
    work, calls = adopted_work
    work.organize_videos()
    target = work.organized_videos_dir / "video_0002.mp4"
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"changed canonical pixels")
    before = workspace_bytes(work)

    with pytest.raises(core.RoiError):
        work.prepare_cleanup(apply=True)

    assert workspace_bytes(work) == before
    assert not calls


@pytest.mark.parametrize("lost_evidence", ["manifest", "selected_output_history", "legacy_sha", "source"])
def test_cleanup_fails_closed_when_correspondence_evidence_is_lost(adopted_work, lost_evidence):
    work, calls = adopted_work
    work.organize_videos()
    if lost_evidence == "manifest":
        work.manifest_path.unlink()
    elif lost_evidence == "selected_output_history":
        manifest = core.load_json(work.manifest_path)
        current = by_id(manifest)["video_0093"]
        current.pop("output", None)
        current.pop("history", None)
        core.atomic_json(work.manifest_path, manifest)
    elif lost_evidence == "legacy_sha":
        # A canonical filename and valid-looking media cannot replace the
        # frozen output identity once its original duplicate has gone away.
        (work.existing_media_dir / "video_0002.mp4").unlink()
        legacy = core.load_json(work.existing_manifest)
        entry = next(row for row in legacy["videos"] if row["source_video_id"] == "video_0002")
        entry.pop("output_sha256")
        core.atomic_json(work.existing_manifest, legacy)
    else:
        (work.videos_dir / "video_0001.mp4").write_bytes(b"a different source recording")
    before = workspace_bytes(work)

    with pytest.raises(core.RoiError):
        work.prepare_cleanup(apply=True)

    assert workspace_bytes(work) == before
    assert not calls
