"""Label edits belong to an explicit ROI review, with provenance and no CSV writes."""
from __future__ import annotations

import csv
import threading
from pathlib import Path

import pytest

from script.roi import core


SOURCE_MEDIA = {"width": 640, "height": 480, "frame_rate": "25/1",
                "nominal_frame_rate": "25/1", "frame_count": 250,
                "metadata_frame_count": 250, "frame_count_basis": "metadata",
                "duration": 10., "rotation": 0, "pixel_format": "yuv420p"}


@pytest.fixture
def label_workspace(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir()
    for identifier in ("video_a", "video_b"):
        (videos / f"{identifier}.mp4").write_bytes(f"source-{identifier}".encode())
    labels = tmp_path / "labels.csv"
    label_rows = [
        {"id": "video_a", "断裂状态": "发生断裂", "断裂模式": "韧性断裂", "断裂位置": "标距内",
         "异常_未夹紧": "否", "现象_颈缩": "是", "标注备注": "原A"},
        {"id": "video_b", "断裂状态": "未断裂", "断裂模式": "无", "断裂位置": "无",
         "异常_未夹紧": "无法判断", "现象_颈缩": "", "标注备注": "原B"},
    ]
    with labels.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(label_rows[0]))
        writer.writeheader()
        writer.writerows(label_rows)

    def probe(path):
        if Path(path).parent == videos:
            return dict(SOURCE_MEDIA)
        return {**SOURCE_MEDIA, "width": 300, "height": 400}

    monkeypatch.setattr(core, "probe_video", probe)
    work = core.Workspace(videos, tmp_path / "roi", labels=labels)
    initial = work.refresh()
    decisions, entries = [], []
    work.existing_media_dir.mkdir(parents=True)
    for row in initial["videos"]:
        identifier = row["video_id"]
        candidate = work.existing_media_dir / f"{identifier}.mp4"
        candidate.write_bytes(f"output-{identifier}".encode())
        box = {"x": 30, "y": 10, "width": 300, "height": 400}
        decisions.append({"source_video_id": identifier, "source_sha256": row["source"]["sha256"],
                          "source_resolution": [640, 480], "source_rotation": 0,
                          "mode": "fixed_roi", "pixel_box": box})
        entries.append({"source_video_id": identifier, "source_sha256": row["source"]["sha256"],
                        "output_sha256": core.sha256_file(candidate), "mode": "fixed_roi",
                        "pixel_box": box, "output_resolution": [300, 400],
                        "frame_count": 250, "source_frame_count": 250, "duration": 10.,
                        "source_duration": 10., "nominal_frame_rate": "25/1",
                        "source_nominal_frame_rate": "25/1", "video_filter": "crop=300:400:30:10,setsar=1"})
    core.atomic_json(work.candidate_path, {"decisions": decisions})
    core.atomic_json(work.existing_manifest, {"videos": entries})
    result = work.refresh()
    assert result["complete"] is True
    return work, labels


def rows(work):
    return {row["video_id"]: row for row in work.refresh()["videos"]}


def save(work, row, values):
    state = work.label_review_state(row)
    return work.save_label_review(row, values, expected_revision=state["revision_id"])


def test_explicit_edit_saves_only_changed_values_and_keeps_original_csv_byte_for_byte(label_workspace):
    work, labels = label_workspace
    before = labels.read_bytes()
    row = rows(work)["video_a"]
    initial = work.label_review_state(row)
    assert initial["status"] == "unmodified"
    assert initial["values"]["断裂位置"] == "标距内"
    save(work, row, {"断裂位置": "夹持根部"})
    updated = work.label_review_state(rows(work)["video_a"])
    assert updated["status"] == "saved"
    assert updated["values"]["断裂位置"] == "夹持根部"
    assert updated["values"]["断裂模式"] == "韧性断裂"
    assert updated["changes"] == {"断裂位置": "夹持根部"}
    assert initial["revision_id"] is None
    assert isinstance(updated["revision_id"], str) and updated["revision_id"]
    assert labels.read_bytes() == before
    assert not rows(work)["video_a"].get("output_review")


def test_saved_roi_labels_reload_for_only_the_matching_video(label_workspace):
    work, labels = label_workspace
    save(work, rows(work)["video_a"], {"标注备注": "ROI中看到根部细节", "现象_颈缩": "无法判断"})
    reopened = core.Workspace(work.videos_dir, work.output_dir, labels=labels)
    selected = rows(reopened)
    a = reopened.label_review_state(selected["video_a"])
    b = reopened.label_review_state(selected["video_b"])
    assert a["status"] == "saved"
    assert a["values"]["标注备注"] == "ROI中看到根部细节"
    assert a["values"]["现象_颈缩"] == "无法判断"
    assert b["status"] == "unmodified"
    assert b["values"]["标注备注"] == "原B"
    assert b["values"]["现象_颈缩"] == ""


def test_editing_an_annotation_cell_does_not_apply_a_review_for_the_old_source_row(label_workspace):
    work, labels = label_workspace
    save(work, rows(work)["video_a"], {"断裂位置": "夹持根部"})
    old_review = (work.output_dir / "label_reviews.json").read_bytes()
    labels.write_text(labels.read_text(encoding="utf-8").replace("韧性断裂", "脆性断裂"), encoding="utf-8")
    state = work.label_review_state(rows(work)["video_a"])
    assert state["status"] == "stale"
    assert state["values"]["断裂位置"] == "标距内"
    assert state["values"]["断裂模式"] == "脆性断裂"
    assert state["history_count"] >= 1
    assert (work.output_dir / "label_reviews.json").read_bytes() == old_review


@pytest.mark.parametrize("changed", ["source", "output"])
def test_replaced_media_never_receives_labels_reviewed_for_other_bytes(label_workspace, changed):
    work, labels = label_workspace
    original = rows(work)["video_a"]
    save(work, original, {"断裂位置": "夹持根部"})
    before_csv = labels.read_bytes()
    path = Path(original["source"]["path"] if changed == "source" else original["output"]["path"])
    path.write_bytes(b"different media with otherwise similar properties")
    current = work.refresh(verify_source_ids={"video_a"})
    row = next(row for row in current["videos"] if row["video_id"] == "video_a")
    state = work.label_review_state(row)
    assert state["status"] in {"stale", "unavailable"}
    assert state["values"]["断裂位置"] == "标距内"
    assert state["history_count"] >= 1
    assert labels.read_bytes() == before_csv
    with pytest.raises(core.RoiError):
        work.save_label_review(original, {"断裂位置": "标距外非根部"}, expected_revision=None)


def test_an_older_browser_revision_cannot_silently_overwrite_newer_edits(label_workspace):
    work, labels = label_workspace
    first = rows(work)["video_a"]
    old_revision = work.label_review_state(first)["revision_id"]
    other = core.Workspace(work.videos_dir, work.output_dir, labels=labels)
    second = rows(other)["video_a"]
    other.save_label_review(second, {"断裂位置": "夹持根部"}, expected_revision=old_revision)
    with pytest.raises(core.RoiError):
        work.save_label_review(first, {"断裂位置": "标距外非根部"}, expected_revision=old_revision)
    state = work.label_review_state(rows(work)["video_a"])
    assert state["values"]["断裂位置"] == "夹持根部"
    assert state["revision_id"] is not None
    assert state["revision_id"] != old_revision


def test_saving_unchanged_original_values_does_not_invent_a_review(label_workspace):
    work, _ = label_workspace
    row = rows(work)["video_a"]
    state = work.label_review_state(row)
    work.save_label_review(row, state["values"], expected_revision=state["revision_id"])
    reloaded = work.label_review_state(rows(work)["video_a"])
    assert reloaded["status"] == "unmodified"
    assert reloaded["changes"] == {}


@pytest.mark.parametrize("values", [{"断裂位置": "不在现有规则中的位置"}, {"断裂时间点": "5.5"}, {"材料类型": "塑料"}])
def test_invalid_or_source_only_edits_do_not_write_a_review(label_workspace, values):
    work, labels = label_workspace
    before = labels.read_bytes()
    with pytest.raises(core.RoiError):
        work.save_label_review(rows(work)["video_a"], values, expected_revision=None)
    assert not (work.output_dir / "label_reviews.json").exists()
    assert labels.read_bytes() == before


def test_returning_an_edited_label_to_the_original_keeps_both_revisions(label_workspace):
    work, labels = label_workspace
    before = labels.read_bytes()
    original = rows(work)["video_a"]
    save(work, original, {"断裂位置": "夹持根部"})
    edited = work.label_review_state(rows(work)["video_a"])
    work.save_label_review(rows(work)["video_a"], {"断裂位置": "标距内"}, expected_revision=edited["revision_id"])
    restored = work.label_review_state(rows(work)["video_a"])
    assert restored["values"]["断裂位置"] == "标距内"
    assert restored["changes"] == {}
    assert restored["history_count"] == 2
    assert restored["revision_id"] != edited["revision_id"]
    assert labels.read_bytes() == before


def test_two_simultaneous_sessions_cannot_both_save_the_same_revision(label_workspace):
    work, labels = label_workspace
    second = core.Workspace(work.videos_dir, work.output_dir, labels=labels)
    first_row = rows(work)["video_a"]
    second_row = rows(second)["video_a"]
    gate = threading.Barrier(2)
    results = []

    def attempt(instance, row, value):
        gate.wait(timeout=5)
        try:
            instance.save_label_review(row, {"断裂位置": value}, expected_revision=None)
            results.append("saved")
        except core.RoiError:
            results.append("rejected")

    threads = [threading.Thread(target=attempt, args=(work, first_row, "夹持根部")),
               threading.Thread(target=attempt, args=(second, second_row, "标距外非根部"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(results) == ["rejected", "saved"]
    assert work.label_review_state(rows(work)["video_a"])["history_count"] == 1
