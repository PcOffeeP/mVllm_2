"""The copied legacy UI must not bring its whole-file writer into current data."""
from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pytest

from script.roi import core


@pytest.fixture
def bridge_workspace(tmp_path, monkeypatch):
    # Like the supported script/Streamlit entry, expose sibling ROI modules.
    monkeypatch.syspath_prepend(str(Path(core.__file__).parent))
    videos = tmp_path / "data/videos"
    videos.mkdir(parents=True)
    annotations = [
        {"id": "video_a", "video_path": "data/videos/video_a.mp4", "材料类型": "金属",
         "断裂状态": "发生断裂", "断裂模式": "韧性断裂", "断裂位置": "标距内",
         "断裂时间点": "0.9", "标注备注": "A 原标注"},
        {"id": "video_0093", "video_path": "data/videos/video_0093.mp4", "材料类型": "聚合物",
         "断裂状态": "未断裂", "断裂模式": "无", "断裂位置": "无",
         "断裂时间点": "无", "标注备注": "当前短版"},
    ]
    labels = tmp_path / "data/annotation-table-full.csv"
    with labels.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(annotations[0]))
        writer.writeheader()
        writer.writerows(annotations)
    for record in annotations:
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=64x48:rate=10:duration=1", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", str(videos / f"{record['id']}.mp4"),
        ], check=True, capture_output=True)
    work = core.Workspace(videos, tmp_path / "data/roi", labels=labels)
    for row in work.refresh()["videos"]:
        work.save_decision(row, {"mode": "no_crop"})
        work.generate(row["video_id"])
    return work, labels, tmp_path


def make_bridge(work, root):
    from script.roi.legacy_bridge import LegacyBridge
    return LegacyBridge(work, root)


def rows(work):
    return {row["video_id"]: row for row in work.inventory()["videos"]}


def legacy_decision(row, *, x=2, note="仅保存新框"):
    return {
        "source_video_id": row["video_id"],
        "source_video_path": row["source"]["path"],
        "source_sha256": row["source"]["sha256"],
        "source_resolution": [64, 48],
        "mode": "fixed_roi",
        "pixel_box": {"x": x, "y": 2, "width": 30, "height": 40},
        "review_status": "approved",
        "visibility_checks": {key: False for key in core.EVIDENCE_ITEMS},
        "reviewer_notes": note,
    }


def test_legacy_metadata_is_bound_to_current_source_and_current_annotations(bridge_workspace):
    work, labels, root = bridge_workspace
    before = labels.read_bytes()
    bridge = make_bridge(work, root)
    snapshot = bridge.refresh()
    metadata = {item["video_id"]: item for item in snapshot["videos"]}
    assert set(metadata) == {"video_a", "video_0093"}
    assert Path(metadata["video_a"]["video_path"]).resolve() == (work.videos_dir / "video_a.mp4").resolve()
    assert metadata["video_a"]["type"] == "金属"
    assert metadata["video_a"]["event_time"] == pytest.approx(0.9)
    assert metadata["video_0093"].get("event_time") is None
    assert bridge.row("video_0093")["source"]["sha256"] == core.sha256_file(work.videos_dir / "video_0093.mp4")
    assert labels.read_bytes() == before


def test_legacy_save_updates_only_current_decision_without_generating_or_overwriting_existing_media(bridge_workspace):
    work, labels, root = bridge_workspace
    bridge = make_bridge(work, root)
    bridge.refresh()
    original = rows(work)
    before_labels = labels.read_bytes()
    before_decisions = core.load_decisions(work.decisions_path)
    old_output = Path(original["video_a"]["output"]["path"])
    old_output_bytes = old_output.read_bytes()
    old_source_bytes = (work.videos_dir / "video_a.mp4").read_bytes()

    bridge.save_current_decision("video_a", legacy_decision(original["video_a"]))

    saved = core.load_decisions(work.decisions_path)
    assert set(saved) == set(before_decisions)
    assert saved["video_0093"] == before_decisions["video_0093"]
    assert saved["video_a"]["pixel_box"] == {"x": 2, "y": 2, "width": 30, "height": 40}
    assert saved["video_a"]["pending_reason"] == "仅保存新框"
    assert "source_review" not in saved["video_a"]
    assert "review_status" not in saved["video_a"]
    current = rows(work)["video_a"]
    assert current["status"] == "ready"
    assert not work.inventory()["complete"]
    assert old_output.read_bytes() == old_output_bytes
    assert (work.videos_dir / "video_a.mp4").read_bytes() == old_source_bytes
    assert labels.read_bytes() == before_labels


@pytest.mark.parametrize("field,value", [
    ("source_sha256", "0" * 64),
    ("source_video_id", "video_a"),
    ("source_resolution", [640, 480]),
    ("source_rotation", 90),
])
def test_old_other_source_decision_cannot_be_rebound_to_current_video(bridge_workspace, field, value):
    work, _, root = bridge_workspace
    bridge = make_bridge(work, root)
    bridge.refresh()
    row = bridge.row("video_0093")
    decision = legacy_decision(row)
    decision[field] = value
    original = work.decisions_path.read_bytes()
    with pytest.raises((core.RoiError, ValueError)):
        bridge.save_current_decision("video_0093", decision)
    assert work.decisions_path.read_bytes() == original


def test_bridge_label_edits_are_saved_separately_with_revision_and_original_csv_unchanged(bridge_workspace):
    work, labels, root = bridge_workspace
    bridge = make_bridge(work, root)
    bridge.refresh()
    before = labels.read_bytes()
    decisions_before = work.decisions_path.read_bytes()
    state = bridge.label_state("video_a")
    bridge.save_labels("video_a", {"断裂位置": "夹持根部"}, expected_revision=state["revision_id"])
    updated = bridge.label_state("video_a")
    assert updated["values"]["断裂位置"] == "夹持根部"
    assert bridge.label_state("video_0093")["values"]["断裂位置"] == "无"
    assert labels.read_bytes() == before
    assert work.decisions_path.read_bytes() == decisions_before
    assert (work.output_dir / "label_reviews.json").is_file()
    assert not rows(work)["video_a"].get("output_review")
    with pytest.raises(core.RoiError):
        bridge.save_labels("video_a", {"断裂模式": "脆性断裂"}, expected_revision=state["revision_id"])


def test_saving_after_source_change_is_rejected_and_preserves_existing_decisions(bridge_workspace):
    work, _, root = bridge_workspace
    bridge = make_bridge(work, root)
    bridge.refresh()
    decision = legacy_decision(bridge.row("video_a"))
    before = work.decisions_path.read_bytes()
    (work.videos_dir / "video_a.mp4").write_bytes(b"replaced after the legacy page loaded")
    with pytest.raises((core.RoiError, ValueError)):
        bridge.save_current_decision("video_a", decision)
    assert work.decisions_path.read_bytes() == before
