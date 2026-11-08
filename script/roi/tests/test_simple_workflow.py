"""User-facing ROI reuse: existing labels and a glance-only visual workflow."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from script.roi import core


MEDIA = {"width": 640, "height": 480, "frame_rate": "25/1",
         "nominal_frame_rate": "25/1", "frame_count": 250,
         "metadata_frame_count": 250, "frame_count_basis": "metadata",
         "duration": 10., "rotation": 0, "pixel_format": "yuv420p"}


@pytest.fixture
def simple_work(tmp_path, monkeypatch):
    source = tmp_path / "videos/video_0093.mp4"
    source.parent.mkdir()
    source.write_bytes(b"current Zhang Ting source")
    work = core.Workspace(source.parent, tmp_path / "roi")
    calls = []

    def probe(path):
        if Path(path).parent == source.parent:
            return dict(MEDIA)
        return {**MEDIA, "width": 300, "height": 400}

    def run(command, **kwargs):
        calls.append(command)
        if "-c:v" in command:
            Path(command[-1]).write_bytes(b"newly generated ROI")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core, "probe_video", probe)
    monkeypatch.setattr(core, "decoded_frame_count", lambda path: 250)
    monkeypatch.setattr(core.subprocess, "run", run)
    return work, calls


def install_legacy(work, *, source_hash=None, output_hash=None, x=31, y=11,
                   pixel_format="yuv420p"):
    row = work.refresh()["videos"][0]
    candidate = work.existing_media_dir / "video_0093.mp4"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"old encoded ROI pixels must not change")
    decision = {"source_video_id": "video_0093", "source_sha256": source_hash or row["source"]["sha256"],
                "source_resolution": [640, 480], "source_rotation": 0,
                "mode": "fixed_roi", "pixel_box": {"x": x, "y": y, "width": 300, "height": 400},
                "review_status": "approved", "visibility_checks": {"upper_grip_visible": True}}
    core.atomic_json(work.candidate_path, {"decisions": [decision]})
    core.atomic_json(work.existing_manifest, {
        "encoding_profile": {"video_codec": "libx264", "preset": "fast", "crf": 23,
                             "pixel_format": "yuv420p", "audio": "dropped", "frame_sync": "vsync_0_passthrough"},
        "videos": [{"source_video_id": "video_0093", "source_sha256": decision["source_sha256"],
                    "output_sha256": output_hash or core.sha256_file(candidate), "mode": "fixed_roi",
                    "pixel_box": decision["pixel_box"], "input_resolution": [640, 480],
                    "output_resolution": [300, 400], "frame_count": 250, "source_frame_count": 250,
                    "duration": 10., "source_duration": 10., "nominal_frame_rate": "25/1",
                    "source_nominal_frame_rate": "25/1", "video_filter": f"crop=300:400:{x}:{y},setsar=1"}]})
    return candidate, decision


def assert_no_fabricated_review(row):
    assert not row.get("output_review")
    assert not row.get("decision", {}).get("source_review")
    assert row["visual_review"] == {"required": False, "status": "not_recorded"}


def test_existing_odd_legacy_pixels_become_available_without_any_review_click(simple_work):
    work, calls = simple_work
    candidate, _ = install_legacy(work)
    before = candidate.read_bytes()
    result = work.refresh()
    row = result["videos"][0]
    assert row["status"] == "success"
    assert result["complete"] is True
    assert row["output"]["origin"] == "preserved_legacy"
    assert Path(row["output"]["path"]).read_bytes() == before
    assert candidate.read_bytes() == before
    assert not calls  # The old output is retained, not re-encoded for exact=1.
    assert_no_fabricated_review(row)
    geometry = row["output"]["geometry"]
    assert geometry["requested_pixel_box"] == {"x": 31, "y": 11, "width": 300, "height": 400}
    assert geometry["effective_pixel_box"] == {"x": 30, "y": 10, "width": 300, "height": 400}
    assert geometry["geometry_status"] == "verified_from_filter_and_source_format"


@pytest.mark.parametrize("mismatch", ["source", "output"])
def test_nonmatching_old_media_cannot_replace_the_current_zhang_ting_source(simple_work, mismatch):
    work, calls = simple_work
    options = {"source_hash": "0" * 64} if mismatch == "source" else {"output_hash": "0" * 64}
    candidate, _ = install_legacy(work, **options)
    before = candidate.read_bytes()
    result = work.refresh()
    row = result["videos"][0]
    assert row["status"] != "success"
    assert not row.get("output")
    assert result["complete"] is False
    assert not calls
    assert candidate.read_bytes() == before


def test_new_video_only_needs_a_crop_decision_and_does_not_invent_human_review(simple_work):
    work, calls = simple_work
    row = work.refresh()["videos"][0]
    work.save_decision(row, {"mode": "fixed_roi", "pixel_box": {"x": 31, "y": 11, "width": 300, "height": 400}})
    assert work.inventory()["videos"][0]["status"] == "ready"
    work.generate("video_0093")
    result = work.inventory()
    row = result["videos"][0]
    assert row["status"] == "success"
    assert result["complete"] is True
    assert any("-c:v" in command for command in calls)
    assert_no_fabricated_review(row)


def test_existing_labels_are_displayed_without_being_rewritten_or_reconfirmed(simple_work):
    work, calls = simple_work
    labels = work.output_dir.parent / "labels.csv"
    labels.write_text("id,断裂状态,异常_未夹紧,现象_颈缩\nvideo_0093,发生断裂,否,是\n", encoding="utf-8")
    original = labels.read_bytes()
    work.labels = labels
    install_legacy(work)
    result = work.refresh()
    row = result["videos"][0]
    assert row["status"] == "success"
    assert row["labels"]["断裂状态"] == "发生断裂"
    assert row["labels"]["异常_未夹紧"] == "否"
    assert row["labels"]["现象_颈缩"] == "是"
    assert labels.read_bytes() == original
    assert not calls


def test_unknown_old_geometry_can_be_retained_without_claiming_an_exact_box(simple_work, monkeypatch):
    work, calls = simple_work
    original_probe = core.probe_video

    def unknown_source_format(path):
        result = original_probe(path)
        if Path(path).parent == work.videos_dir:
            result["pixel_format"] = "unknown"
        return result

    monkeypatch.setattr(core, "probe_video", unknown_source_format)
    candidate, _ = install_legacy(work)
    row = work.refresh()["videos"][0]
    assert row["status"] == "success"
    assert row["output"]["sha256"] == core.sha256_file(candidate)
    geometry = row["output"]["geometry"]
    assert geometry["geometry_status"] == "uncertain"
    assert geometry["effective_pixel_box"] is None
    assert geometry["crop_pixels"] is None
    assert not calls
    assert_no_fabricated_review(row)


def test_preserved_output_byte_change_is_not_silently_accepted(simple_work):
    work, _ = simple_work
    candidate, _ = install_legacy(work)
    before = work.refresh()["videos"][0]
    assert before["status"] == "success"
    candidate.write_bytes(b"unexpected replacement of legacy crop")
    after = work.refresh(verify_source_ids={"video_0093"})
    assert after["complete"] is False
    assert after["videos"][0]["status"] != "success"
    assert not after["videos"][0].get("output")


@pytest.mark.parametrize("profile", [None, {"video_codec": "libx264", "crf": 18, "audio": "kept"}])
def test_preserving_old_bytes_records_their_own_encoding_without_imposing_new_defaults(simple_work, profile):
    work, calls = simple_work
    candidate, _ = install_legacy(work)
    manifest = core.load_json(work.existing_manifest)
    if profile is None:
        manifest.pop("encoding_profile")
    else:
        manifest["encoding_profile"] = profile
    core.atomic_json(work.existing_manifest, manifest)
    row = work.refresh()["videos"][0]
    assert row["status"] == "success"
    assert row["output"]["origin"] == "preserved_legacy"
    assert row["output"]["encoding"] == (profile or {})
    assert row["output"]["sha256"] == core.sha256_file(candidate)
    assert not calls


def test_preserved_legacy_roi_survives_source_temporarily_moving_away_and_back(simple_work):
    work, _ = simple_work
    candidate, _ = install_legacy(work)
    initial = work.refresh()["videos"][0]
    source = Path(initial["source"]["path"])
    moved = source.with_suffix(".temporarily_absent")
    source.rename(moved)
    missing = work.refresh()
    assert missing["total"] == 1
    assert missing["complete"] is False
    assert missing["videos"][0]["status"] == "failed"
    assert missing["videos"][0]["output"] == initial["output"]
    moved.rename(source)
    restored = work.refresh()
    assert restored["complete"] is True
    assert restored["videos"][0]["output"]["sha256"] == core.sha256_file(candidate)
    assert restored["videos"][0]["visual_review"]["status"] == "not_recorded"


def test_self_consistent_old_manifest_cannot_approve_a_half_length_roi(simple_work, monkeypatch):
    work, _ = simple_work
    install_legacy(work)
    manifest = core.load_json(work.existing_manifest)
    manifest["videos"][0].update(duration=5., frame_count=125)
    core.atomic_json(work.existing_manifest, manifest)
    original_probe = core.probe_video

    def half_length_output(path):
        media = original_probe(path)
        if Path(path).parent == work.existing_media_dir:
            media.update(duration=5., frame_count=125, metadata_frame_count=125)
        return media

    monkeypatch.setattr(core, "probe_video", half_length_output)
    result = work.refresh()
    assert result["complete"] is False
    row = result["videos"][0]
    assert row["status"] != "success"
    assert not row.get("output")
    assert row["reason"]


def test_saving_crop_and_generating_keeps_the_existing_draft_reason_traceable(simple_work):
    work, _ = simple_work
    original = work.refresh()["videos"][0]
    draft = {"mode": "fixed_roi", "pixel_box": {"x": 31, "y": 11, "width": 300, "height": 400},
             "pending_reason": "下一次检查断裂后是否出画"}
    work.save_draft(original, draft)
    selected = work.refresh()["videos"][0]
    work.save_decision(selected, {"mode": draft["mode"], "pixel_box": draft["pixel_box"]})
    work.generate("video_0093")
    result = work.refresh()
    row = result["videos"][0]
    assert result["complete"] is True
    assert row["decision"]["prior_draft"]["pending_reason"] == draft["pending_reason"]
    assert row["decision"]["pending_reason"] == draft["pending_reason"]
    stored_draft = core.load_json(work.drafts_path)["video_0093"]
    assert stored_draft["pending_reason"] == draft["pending_reason"]
    assert stored_draft["saved_as_decision_at"]
    assert_no_fabricated_review(row)


def install_nominal_rate_compatibility_case(work, monkeypatch, *, output_nominal="30/1", change=None):
    original_probe = core.probe_video
    change = change or {}

    def version_different_probe(path):
        media = original_probe(path)
        media.update(frame_count=300, metadata_frame_count=300, duration=10., frame_rate="30/1")
        if Path(path).parent == work.videos_dir:
            media.update(nominal_frame_rate="60/1", frame_rate="29999/1000")
            media.update(change.get("source", {}))
        else:
            media.update(nominal_frame_rate=output_nominal)
            media.update(change.get("output", {}))
        return media

    monkeypatch.setattr(core, "probe_video", version_different_probe)
    candidate, _ = install_legacy(work)
    manifest = core.load_json(work.existing_manifest)
    manifest["videos"][0].update(frame_count=300, source_frame_count=300, nominal_frame_rate="30/1",
                                  source_nominal_frame_rate="30/1", frame_rate="30/1", source_frame_rate="29999/1000")
    core.atomic_json(work.existing_manifest, manifest)
    return candidate


def test_legacy_probe_version_nominal_rate_difference_preserves_bytes_with_a_warning(simple_work, monkeypatch):
    work, calls = simple_work
    candidate = install_nominal_rate_compatibility_case(work, monkeypatch)
    original_hash = core.sha256_file(candidate)
    result = work.refresh()
    row = result["videos"][0]
    assert result["complete"] is True, row.get("reason")
    assert row["status"] == "success"
    assert row["output"]["origin"] == "preserved_legacy"
    assert row["output"]["sha256"] == original_hash == core.sha256_file(candidate)
    assert not calls
    assert row["output"]["validation"]["full_decode"] == "not_performed"
    # A metadata compatibility decision must never silently imply frame-time equivalence.
    compatibility = row["output"]["validation"]["nominal_frame_rate"]
    assert compatibility["status"] == "metadata_disagreement"
    assert compatibility["source_current"] == "60/1"
    assert compatibility["source_recorded"] == "30/1"
    assert compatibility["output_current"] == compatibility["output_recorded"] == "30/1"
    assert compatibility["note"]
    assert row["output"]["validation"]["frame_timestamps"] == "not_compared"
    assert_no_fabricated_review(row)


@pytest.mark.parametrize("change", [
    {"source": {"duration": 20.}},
    {"source": {"frame_count": 600, "metadata_frame_count": 600}},
    {"source": {"frame_rate": "60/1"}},
    {"source": {"frame_count": None, "metadata_frame_count": None}},
])
def test_legacy_nominal_rate_fallback_does_not_hide_real_timing_or_missing_evidence(simple_work, monkeypatch, change):
    work, _ = simple_work
    candidate = install_nominal_rate_compatibility_case(work, monkeypatch, change=change)
    original_hash = core.sha256_file(candidate)
    result = work.refresh()
    assert result["complete"] is False
    row = result["videos"][0]
    assert row["status"] != "success"
    assert not row.get("output")
    assert row["reason"]
    assert core.sha256_file(candidate) == original_hash


def test_new_generated_media_does_not_use_the_legacy_nominal_rate_exception():
    source = {**MEDIA, "nominal_frame_rate": "60/1", "frame_rate": "30/1", "frame_count": 300}
    output = {**source, "nominal_frame_rate": "30/1", "width": 300, "height": 400}
    with pytest.raises(core.RoiError, match="标称帧率"):
        core.validate_media(source, output, [300, 400])


def test_legacy_output_probe_difference_from_its_own_record_is_still_rejected(simple_work, monkeypatch):
    work, _ = simple_work
    install_nominal_rate_compatibility_case(work, monkeypatch, output_nominal="60/1")
    result = work.refresh()
    assert result["complete"] is False
    assert result["videos"][0]["status"] != "success"
    assert not result["videos"][0].get("output")
