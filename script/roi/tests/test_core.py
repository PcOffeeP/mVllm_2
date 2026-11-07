"""ROI behavior checks using temporary synthetic bytes; no project media is read."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from script.roi import core


SOURCE_MEDIA = {
    "width": 640, "height": 480, "frame_rate": "25/1",
    "nominal_frame_rate": "25/1", "frame_count": 250,
    "duration": 10.0, "rotation": 0, "pixel_format": "yuv420p",
}


def legacy_profile():
    return {"video_codec": "libx264", "preset": "fast", "crf": 23,
            "pixel_format": "yuv420p", "audio": "dropped", "frame_sync": "vsync_0_passthrough"}


def checked_review():
    return {
        "items": {key: {"result": "judgable", "cause": "source", "note": ""}
                  for key in core.EVIDENCE_ITEMS},
        "checked_intervals": [[0, 10]], "confirmed": True,
    }


def fixed_decision():
    return {
        "mode": "fixed_roi", "pixel_box": {"x": 30, "y": 10, "width": 300, "height": 400},
        "source_review": checked_review(),
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "new.mp4").write_bytes(b"synthetic source video")
    calls = []

    def probe(path):
        if Path(path).parent == videos:
            return dict(SOURCE_MEDIA)
        return {**SOURCE_MEDIA, "width": 300, "height": 400}

    def run(command, **kwargs):
        calls.append(command)
        if "-c:v" in command:
            Path(command[-1]).write_bytes(b"synthetic generated output")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(core, "probe_video", probe)
    monkeypatch.setattr(core.subprocess, "run", run)
    return core.Workspace(videos, tmp_path / "roi"), calls


def ready_workspace(workspace):
    ws, calls = workspace
    row = ws.refresh()["videos"][0]
    ws.save_decision(row, fixed_decision())
    assert ws.inventory()["videos"][0]["status"] == "ready"
    return ws, calls


def test_new_video_without_any_decision_is_pending_not_a_failure(workspace):
    ws, calls = workspace
    before = (ws.videos_dir / "new.mp4").read_bytes()
    manifest = ws.refresh()
    assert manifest["total"] == 1
    assert manifest["summary"] == {"needs_decision": 1}
    assert manifest["complete"] is False
    assert manifest["videos"][0]["status"] == "needs_decision"
    assert not ws.decisions_path.exists()
    assert not calls
    assert (ws.videos_dir / "new.mp4").read_bytes() == before


def test_legacy_approval_does_not_supply_current_evidence_review(workspace):
    ws, _ = workspace
    source = ws.refresh()["videos"][0]["source"]
    legacy = {**fixed_decision(), "source_video_id": "new",
              "source_sha256": source["sha256"], "source_resolution": [640, 480],
              "status": "approved", "policy_version": "1.2",
              "visibility_checks": {"location_judgable": True, "root_break_judgable": True}}
    legacy.pop("source_review")
    core.atomic_json(ws.candidate_path, {"decisions": [legacy]})
    manifest = ws.refresh()
    assert manifest["videos"][0]["status"] == "needs_review"
    assert manifest["complete"] is False
    with pytest.raises(core.RoiError):
        ws.generate("new")
    assert not list((ws.output_dir / "media").rglob("*.mp4"))


def test_wrong_source_identity_cannot_generate_even_with_valid_review(workspace):
    ws, _ = workspace
    decision = {**fixed_decision(), "source_video_id": "new", "source_sha256": "0" * 64,
                "source_resolution": [640, 480], "rule_version": core.RULE_VERSION}
    core.atomic_json(ws.candidate_path, {"decisions": [decision]})
    assert ws.refresh()["videos"][0]["status"] == "needs_review"
    with pytest.raises(core.RoiError, match="身份"):
        ws.generate("new")


def test_generated_media_requires_separate_output_review_and_binds_it_to_bytes(workspace):
    ws, _ = ready_workspace(workspace)
    ws.generate("new")
    manifest = ws.inventory()
    row = manifest["videos"][0]
    assert row["status"] == "needs_output_review"
    assert manifest["complete"] is False
    assert "output_review" not in row or row["output_review"] is None

    ws.save_output_review("new", checked_review())
    manifest = ws.inventory()
    row = manifest["videos"][0]
    assert row["status"] == "success"
    assert manifest["complete"] is True
    assert row["output_review"]["output_sha256"] == row["output"]["sha256"]
    Path(row["output"]["path"]).write_bytes(b"different output bytes")
    invalidated = ws.inventory()
    assert invalidated["complete"] is False
    assert invalidated["videos"][0]["status"] != "success"


def test_changed_recipe_does_not_inherit_output_approval(workspace):
    ws, _ = ready_workspace(workspace)
    ws.generate("new")
    ws.save_output_review("new", checked_review())
    approved = ws.inventory()["videos"][0]
    ws.save_decision(approved, {"mode": "no_crop", "source_review": checked_review()})
    changed = ws.inventory()
    assert changed["videos"][0]["status"] == "ready"
    assert changed["videos"][0]["recipe_hash"] != approved["recipe_hash"]
    assert changed["complete"] is False


def test_source_change_between_view_and_save_cannot_be_silently_rebound(workspace):
    ws, _ = workspace
    row = ws.refresh()["videos"][0]
    (ws.videos_dir / "new.mp4").write_bytes(b"source changed after inspection")
    with pytest.raises(core.RoiError, match="发生变化"):
        ws.save_decision(row, fixed_decision())
    assert not ws.decisions_path.exists()


def test_orphan_output_is_never_overwritten_or_adopted_by_filename(workspace):
    ws, calls = ready_workspace(workspace)
    row = ws.inventory()["videos"][0]
    orphan = ws.output_dir / "media" / "new" / (row["recipe_hash"] + ".mp4")
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"untracked output must survive")
    with pytest.raises(core.RoiError, match="已存在"):
        ws.generate("new")
    assert orphan.read_bytes() == b"untracked output must survive"
    assert not calls
    assert ws.inventory()["complete"] is False


def test_one_unreadable_video_does_not_hide_other_pending_videos(workspace, monkeypatch):
    ws, _ = workspace
    (ws.videos_dir / "bad.mp4").write_bytes(b"broken synthetic input")
    original = core.probe_video

    def probe(path):
        if Path(path).stem == "bad":
            raise core.RoiError("synthetic decoder failure")
        return original(path)

    monkeypatch.setattr(core, "probe_video", probe)
    manifest = ws.refresh()
    states = {row["video_id"]: row["status"] for row in manifest["videos"]}
    assert states == {"bad": "failed", "new": "needs_decision"}
    assert manifest["total"] == 2
    assert manifest["summary"] == {"failed": 1, "needs_decision": 1}
    assert manifest["complete"] is False


def test_duplicate_source_id_is_explicit_failure(workspace):
    ws, _ = workspace
    (ws.videos_dir / "new.mov").write_bytes(b"different source with same ID")
    manifest = ws.refresh()
    assert manifest["total"] == 1
    assert manifest["videos"][0]["status"] == "failed"
    assert len(manifest["videos"][0]["paths"]) == 2
    assert manifest["complete"] is False


def test_output_directory_cannot_be_nested_in_sources(tmp_path):
    source = tmp_path / "videos"
    with pytest.raises(core.RoiError):
        core.Workspace(source, source / "derived")


@pytest.mark.parametrize("width,height,expected", [(640, 480, (642, 856)), (641, 479, (642, 856)), (300, 400, (300, 400))])
def test_no_crop_preserves_source_extent_in_smallest_even_exact_canvas(width, height, expected):
    assert core.exact_pad_dimensions(width, height) == expected
    geometry = core.geometry({"mode": "no_crop", "source_resolution": [width, height]})
    assert tuple(geometry["output_resolution"]) == expected
    assert all(value == 0 for value in geometry["crop_pixels"].values())
    padding = geometry["pad_pixels"]
    assert width + padding["left"] + padding["right"] == expected[0]
    assert height + padding["top"] + padding["bottom"] == expected[1]
    assert abs(padding["left"] - padding["right"]) <= 1
    assert abs(padding["top"] - padding["bottom"]) <= 1


def test_fixed_crop_records_all_removed_margins_and_rejects_illegal_geometry():
    decision = {**fixed_decision(), "source_resolution": [640, 480]}
    geometry = core.geometry(decision)
    assert geometry["output_resolution"] == [300, 400]
    assert geometry["crop_pixels"] == {"top": 10, "bottom": 70, "left": 30, "right": 310}
    assert all(value == 0 for value in geometry["pad_pixels"].values())
    for box in ({"x": 500, "y": 10, "width": 300, "height": 400},
                {"x": 0, "y": 0, "width": 301, "height": 400},
                {"x": 0, "y": 0, "width": 300, "height": 398}):
        with pytest.raises(core.RoiError):
            core.geometry({**decision, "pixel_box": box})


def test_review_distinguishes_source_limits_from_processing_loss_and_unchecked():
    review = checked_review()
    review["items"]["mode"] = {"result": "insufficient", "cause": "source", "note": "原画面被遮挡"}
    assert core.review_errors(review, 10) == []
    for cause in ("processing", "unknown"):
        review["items"]["mode"]["cause"] = cause
        assert core.review_errors(review, 10)
    review["items"]["mode"] = {"result": "not_applicable", "note": ""}
    assert core.review_errors(review, 10)
    review["items"]["mode"] = {"result": "unchecked"}
    assert core.review_errors(review, 10)


def test_review_must_record_actual_valid_viewing_positions():
    review = checked_review()
    for intervals in ([], [[-1, 0]], [[0, 11]], [[3, 2]], [[0, float("nan")]]):
        review["checked_intervals"] = intervals
        assert core.review_errors(review, 10)


def test_matching_historical_output_is_reused_but_still_needs_output_review(workspace):
    ws, calls = ready_workspace(workspace)
    row = ws.inventory()["videos"][0]
    ws.existing_media_dir.mkdir(parents=True)
    candidate = ws.existing_media_dir / "new.mp4"
    candidate.write_bytes(b"synthetic historical output")
    core.atomic_json(ws.existing_manifest, {"encoding_profile": legacy_profile(), "videos": [{
        "source_video_id": "new", "source_sha256": row["source"]["sha256"],
        "output_sha256": core.sha256_file(candidate), "mode": "fixed_roi",
        "pixel_box": fixed_decision()["pixel_box"],
    }]})
    ws.generate("new")
    imported = ws.inventory()["videos"][0]
    assert imported["output"]["origin"] == "imported"
    assert Path(imported["output"]["path"]).read_bytes() == candidate.read_bytes()
    assert imported["status"] == "needs_output_review"
    assert ws.inventory()["complete"] is False
    assert not any("-c:v" in command for command in calls)


def test_historical_output_with_wrong_digest_is_not_reused(workspace):
    ws, calls = ready_workspace(workspace)
    row = ws.inventory()["videos"][0]
    ws.existing_media_dir.mkdir(parents=True)
    candidate = ws.existing_media_dir / "new.mp4"
    candidate.write_bytes(b"historical output with unexpected bytes")
    core.atomic_json(ws.existing_manifest, {"encoding_profile": legacy_profile(), "videos": [{
        "source_video_id": "new", "source_sha256": row["source"]["sha256"],
        "output_sha256": "0" * 64, "mode": "fixed_roi",
        "pixel_box": fixed_decision()["pixel_box"],
    }]})
    ws.generate("new")
    generated = ws.inventory()["videos"][0]
    assert generated["output"]["origin"] == "generated"
    assert Path(generated["output"]["path"]).read_bytes() != candidate.read_bytes()
    assert any("-c:v" in command for command in calls)


def test_optional_label_csv_uses_the_projects_lowercase_id_column(workspace):
    ws, _ = workspace
    labels = ws.videos_dir.parent / "labels.csv"
    labels.write_text("id,断裂状态,断裂模式\nnew,未断裂,无\n", encoding="utf-8")
    before = labels.read_bytes()
    ws.labels = labels
    manifest = ws.refresh()
    assert manifest["videos"][0]["labels"]["断裂状态"] == "未断裂"
    assert labels.read_bytes() == before


@pytest.mark.parametrize("flag,expected_exit", [("--scan", 0), ("--batch", 2)])
def test_unattended_entry_preserves_missing_decisions_instead_of_crashing(workspace, monkeypatch, capsys, flag, expected_exit):
    import importlib.util
    import sys

    ws, calls = workspace
    monkeypatch.setitem(sys.modules, "core", core)
    spec = importlib.util.spec_from_file_location("roi_entry_for_tests", Path(core.__file__).with_name("roi.py"))
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    result = entry.main(["--videos-dir", str(ws.videos_dir), "--output-dir", str(ws.output_dir), flag])
    assert result == expected_exit
    summary = json.loads(capsys.readouterr().out)
    assert summary["summary"] == {"needs_decision": 1}
    assert summary["complete"] is False
    assert not calls
    assert json.loads(ws.manifest_path.read_text())["total"] == 1


@pytest.mark.parametrize("change", [
    {"width": 302}, {"frame_count": 249}, {"nominal_frame_rate": "26/1"},
    {"duration": 10.046}, {"rotation": 90},
])
def test_media_acceptance_rejects_geometry_timing_or_direction_changes(change):
    source = dict(SOURCE_MEDIA)
    output = {**source, "width": 300, "height": 400, **change}
    with pytest.raises(core.RoiError):
        core.validate_media(source, output, [300, 400])


def test_media_acceptance_respects_documented_tolerance_without_false_success_claim():
    source = dict(SOURCE_MEDIA)
    output = {**source, "width": 300, "height": 400,
              "duration": 10.044, "nominal_frame_rate": "2500002/100000"}
    assert core.validate_media(source, output, [300, 400]) is None


def install_legacy(ws, row, *, profile=None, video_filter=None):
    ws.existing_media_dir.mkdir(parents=True, exist_ok=True)
    candidate = ws.existing_media_dir / "new.mp4"
    candidate.write_bytes(b"synthetic historical output")
    entry = {
        "source_video_id": "new", "source_sha256": row["source"]["sha256"],
        "output_sha256": core.sha256_file(candidate), "mode": "fixed_roi",
        "pixel_box": row["decision"]["pixel_box"],
    }
    if video_filter is not None:
        entry["video_filter"] = video_filter
    value = {"videos": [entry]}
    if profile is not None:
        value["encoding_profile"] = profile
    core.atomic_json(ws.existing_manifest, value)


@pytest.mark.parametrize("profile", [None, {**legacy_profile(), "crf": 18},
                                     {**legacy_profile(), "audio": "kept"}])
def test_missing_or_incompatible_legacy_encoding_is_regenerated(workspace, profile):
    ws, calls = ready_workspace(workspace)
    install_legacy(ws, ws.inventory()["videos"][0], profile=profile)
    ws.generate("new")
    assert ws.inventory()["videos"][0]["output"]["origin"] == "generated"
    assert any("-c:v" in command for command in calls)


@pytest.mark.parametrize("pixel_format,x,y,explicit_exact,expected", [
    ("yuv420p", 30, 10, False, "imported"),
    ("yuv420p", 31, 11, False, "generated"),
    ("yuv420p", 31, 11, True, "imported"),
    ("yuv411p", 2, 10, False, "generated"),
    ("unknown", 30, 10, False, "generated"),
    ("yuv422p", 30, 11, False, "imported"),
    ("yuv444p", 31, 11, False, "imported"),
])
def test_legacy_crop_compatibility_uses_source_chroma_grid(workspace, monkeypatch, pixel_format, x, y, explicit_exact, expected):
    ws, calls = workspace
    original = core.probe_video

    def probe(path):
        return {**original(path), "pixel_format": pixel_format}

    monkeypatch.setattr(core, "probe_video", probe)
    row = ws.refresh()["videos"][0]
    decision = fixed_decision()
    decision["pixel_box"].update(x=x, y=y)
    ws.save_decision(row, decision)
    row = ws.inventory()["videos"][0]
    install_legacy(ws, row, profile=legacy_profile(),
                   video_filter=f"crop=300:400:{x}:{y}:exact=1,setsar=1" if explicit_exact else None)
    ws.generate("new")
    assert ws.inventory()["videos"][0]["output"]["origin"] == expected
    assert any("-c:v" in command for command in calls) == (expected == "generated")


def test_switching_a_to_b_to_a_restores_recorded_output_and_approval(workspace):
    ws, _ = ready_workspace(workspace)
    ws.generate("new")
    ws.save_output_review("new", checked_review())
    a = ws.inventory()["videos"][0]
    decision_b = fixed_decision()
    decision_b["pixel_box"]["x"] = 32
    ws.save_decision(a, decision_b)
    ws.generate("new")
    ws.save_output_review("new", checked_review())
    b = ws.inventory()["videos"][0]
    assert b["recipe_hash"] != a["recipe_hash"]
    assert Path(a["output"]["path"]).is_file()

    ws.save_decision(b, fixed_decision())
    restored = ws.inventory()["videos"][0]
    assert restored["status"] == "success"
    assert restored["output"] == a["output"]
    assert restored["output_review"] == a["output_review"]
    assert {a["recipe_hash"], b["recipe_hash"]} <= set(restored["history"])
    assert ws.generate("new")["status"] == "success"

    Path(restored["output"]["path"]).write_bytes(b"tampered restored output")
    invalidated = ws.refresh(verify_source_ids={"new"})
    assert invalidated["complete"] is False
    assert invalidated["videos"][0]["status"] != "success"
    with pytest.raises(core.RoiError, match="已存在"):
        ws.generate("new")


def test_source_and_output_drafts_survive_reload_without_granting_approval(workspace):
    ws, _ = workspace
    row = ws.refresh()["videos"][0]
    draft = fixed_decision()
    draft["source_review"]["items"]["mode"]["result"] = "unchecked"
    draft["pending_reason"] = "明天继续检查"
    ws.save_draft(row, draft)
    reloaded = core.Workspace(ws.videos_dir, ws.output_dir)
    pending = reloaded.inventory()["videos"][0]
    assert pending["status"] == "needs_review"
    assert pending["draft"]["pending_reason"] == "明天继续检查"
    with pytest.raises(core.RoiError):
        reloaded.generate("new")
    reloaded.save_decision(pending, fixed_decision())
    assert "draft" not in reloaded.inventory()["videos"][0]
    reloaded.generate("new")
    reloaded.save_output_review("new", checked_review())
    output_draft = checked_review()
    output_draft["items"]["location"]["result"] = "unchecked"
    output_draft["pending_reason"] = "需要再检查夹具"
    reloaded.save_output_draft("new", output_draft)
    again = core.Workspace(ws.videos_dir, ws.output_dir)
    row = again.inventory()["videos"][0]
    assert row["status"] == "needs_output_review"
    assert row["output_review_draft"]["pending_reason"] == "需要再检查夹具"
    assert again.inventory()["complete"] is False
    again.save_output_review("new", checked_review())
    assert again.inventory()["complete"] is True
    assert "output_review_draft" not in again.inventory()["videos"][0]


@pytest.mark.parametrize("obstruction", ["draft", "split_conflict"])
def test_generation_failure_does_not_bypass_new_review_or_split_obstruction(workspace, monkeypatch, obstruction):
    ws, calls = ready_workspace(workspace)
    original = core.subprocess.run

    def failed(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stdout="", stderr="synthetic encode failure")

    monkeypatch.setattr(core.subprocess, "run", failed)
    with pytest.raises(core.RoiError, match="ffmpeg"):
        ws.generate("new")
    failed_row = ws.inventory()["videos"][0]
    assert failed_row["status"] == "failed"
    assert failed_row["generation_error"]
    if obstruction == "draft":
        draft = fixed_decision()
        draft["source_review"]["items"]["state"]["result"] = "unchecked"
        ws.save_draft(failed_row, draft)
        expected = "needs_review"
    else:
        directory = ws.output_dir.parent / "splits"
        directory.mkdir()
        core.atomic_json(directory / "fold_0_train.json", {"video_ids": ["new"]})
        core.atomic_json(directory / "fold_0_val.json", {"video_ids": ["new"]})
        ws.splits_dir = directory
        expected = "needs_verification"
    assert ws.inventory()["videos"][0]["status"] == expected
    before = len(calls)
    with pytest.raises(core.RoiError):
        ws.generate("new")
    assert len(calls) == before

    if obstruction == "draft":
        ws.save_decision(ws.inventory()["videos"][0], fixed_decision())
    else:
        (ws.splits_dir / "fold_0_val.json").unlink()
    monkeypatch.setattr(core.subprocess, "run", original)
    ws.generate("new")
    assert ws.inventory()["videos"][0]["status"] == "needs_output_review"


def test_invalid_fold_filename_is_a_friendly_input_error(tmp_path):
    core.atomic_json(tmp_path / "fold_bad_train.json", {"video_ids": ["new"]})
    with pytest.raises(core.RoiError, match="文件名无效"):
        core.load_splits(tmp_path)


def test_split_roles_are_recorded_without_filtering_source_inventory(workspace):
    ws, _ = workspace
    (ws.videos_dir / "heldout.mp4").write_bytes(b"synthetic heldout video")
    directory = ws.output_dir.parent / "splits"
    directory.mkdir()
    core.atomic_json(directory / "fold_0_train.json", {"video_ids": ["new"]})
    core.atomic_json(directory / "test.json", {"video_ids": ["heldout"]})
    ws.splits_dir = directory
    manifest = ws.refresh()
    rows = {row["video_id"]: row for row in manifest["videos"]}
    assert set(rows) == {"new", "heldout"}
    assert rows["new"]["split"]["partition"] == "development"
    assert rows["new"]["split"]["folds"] == {"0": "train"}
    assert rows["heldout"]["split"]["partition"] == "test"
    assert len(manifest["split_input"]["files"]) == 2


def test_concurrent_refresh_cannot_enter_manifest_write_while_generation_holds_lock(workspace, monkeypatch):
    from threading import Event, Thread

    ws, _ = ready_workspace(workspace)
    encode_entered, release_encode = Event(), Event()
    refresh_started, refresh_finished = Event(), Event()
    errors = []
    original = core.subprocess.run

    def blocked_encode(command, **kwargs):
        if "-c:v" in command:
            encode_entered.set()
            if not release_encode.wait(3):
                raise AssertionError("test did not release synthetic encode")
        return original(command, **kwargs)

    monkeypatch.setattr(core.subprocess, "run", blocked_encode)

    def generate():
        try:
            ws.generate("new")
        except Exception as exc:
            errors.append(exc)

    def refresh():
        refresh_started.set()
        try:
            ws.refresh()
        except Exception as exc:
            errors.append(exc)
        finally:
            refresh_finished.set()

    generation_thread = Thread(target=generate)
    generation_thread.start()
    assert encode_entered.wait(3)
    refresh_thread = Thread(target=refresh)
    refresh_thread.start()
    try:
        assert refresh_started.wait(3)
        assert not refresh_finished.wait(0.1)
    finally:
        release_encode.set()
        generation_thread.join(3)
        refresh_thread.join(3)
    assert not generation_thread.is_alive()
    assert not refresh_thread.is_alive()
    assert errors == []
    assert ws.inventory()["videos"][0]["status"] == "needs_output_review"
