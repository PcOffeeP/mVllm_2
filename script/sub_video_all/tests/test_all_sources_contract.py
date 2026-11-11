"""All-source generation/reuse contracts; only tiny temporary synthetic media."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import shutil

import pytest

from script.sub_video import generate as old
from script.sub_video import verification
from script.sub_video.tests.test_generation_contract import annotation, digest, synthetic_project
from script.sub_video.tests.test_unclamped_contract import anchor_document


@pytest.fixture
def all_project(synthetic_project):
    root = synthetic_project
    ids = ["video_0001", "video_0003", "video_0004", "video_9999"]
    rows = [annotation(v, 断裂帧_前="29", 断裂帧_后="30", 断裂时间点="3") for v in ids]
    rows[1]["断裂模式"] = "无法确定"
    rows[1]["异常_视频异常"] = "是"
    rows[2].update(断裂状态="未断裂", 断裂模式="无", 断裂位置="无", 断裂帧_前="无", 断裂帧_后="无", 断裂时间点="无")
    with (root / "data/annotation-table-full.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    roi_path = root / "data/roi/manifest.json"
    existing = json.loads(roi_path.read_text())["videos"]
    template = next(r for r in existing if r["video_id"] == "video_0003")
    completed = []
    for video_id in ids:
        for relative in ("data/videos", "data/roi/videos"):
            target = root / relative / (video_id + ".mp4")
            if not target.exists(): shutil.copyfile(root / relative / "video_0003.mp4", target)
        record = copy.deepcopy(template); record["video_id"] = video_id
        completed.append(record)
    roi_path.write_text(json.dumps({"videos": completed}))
    anchor_document(root / "docs/subvideo-current-logic.md")
    return root


def new_generator():
    from script.sub_video_all import generate
    return generate


def assert_all_source_contract(manifest, root):
    sources = {s["video_id"]: s for s in manifest["sources"]}
    assert set(sources) == {"video_0001", "video_0003", "video_0004", "video_9999"}
    assert all(s["status"] == "planned" for s in sources.values())
    clips = manifest["candidates"]
    assert {c["source_video_id"] for c in clips} == set(sources)
    keys = [(c["source_video_id"], c["window_role"], c["start_frame"], c["end_frame"]) for c in clips]
    assert len(keys) == len(set(keys))
    assert len({c["output_path"] for c in clips}) == len(clips)
    for c in clips:
        assert c["status"] == "cropped"
        assert c["final_labels"] is None and c["manual_review"] == "required"
        assert c["review"]["status"] == "未审核"
        if c["source_video_id"] == "video_9999":
            assert set(c["folds"].values()) == {"test"}
        else:
            assert list(c["folds"].values()).count("val") == 1
            assert list(c["folds"].values()).count("train") == 2
        assert digest(root / c["output_path"]) == c["output"]["sha256"]
        assert c["output"]["frame_preserving_replay"]["status"] == verification.VERIFIED
        for a in c["output"]["frame_mapping"]["anchors"]:
            assert a["source_frame"] == a["roi_frame"]
            assert a["output_frame"] == a["source_frame"] - c["start_frame"]
    assert len(list((root / "videos").glob("*.mp4"))) == len(clips)


def test_all_sources_generated_once_with_test_kept_out_of_every_train(all_project):
    g = new_generator(); root = all_project
    csv_before = (root / "data/annotation-table-full.csv").read_bytes()
    split_before = {p.name: p.read_bytes() for p in (root / "data/splits/three-fold").glob("*.json")}
    result = g.run(root)
    assert_all_source_contract(result, root / "data/sub_video")
    assert result["published"] is False
    assert (root / "data/annotation-table-full.csv").read_bytes() == csv_before
    assert {p.name: p.read_bytes() for p in (root / "data/splits/three-fold").glob("*.json")} == split_before


def test_verified_fold_outputs_reused_without_recropping(all_project, monkeypatch):
    g = new_generator(); root = all_project
    donor_dir = root / "data/donor"
    donor = old.run(root, donor_dir, fold=0)
    done = {c["candidate_id"]: c for c in donor["candidates"]}
    original = old.crop_video
    calls = []
    def guarded_crop(roi, dest, candidate, *args, **kwargs):
        assert candidate["candidate_id"] not in done, "a verified existing candidate must not be encoded again"
        calls.append(candidate["candidate_id"])
        return original(roi, dest, candidate, *args, **kwargs)
    monkeypatch.setattr(old, "crop_video", guarded_crop)
    result = g.run(root, reuse_manifests=[donor_dir / "manifest.json"])
    assert_all_source_contract(result, root / "data/sub_video")
    assert calls
    for c in result["candidates"]:
        if c["candidate_id"] in done:
            assert c["output"]["sha256"] == done[c["candidate_id"]]["output"]["sha256"]
            assert (root / "data/sub_video" / c["output_path"]).read_bytes() == (donor_dir / c["output_path"]).read_bytes()


def test_repeated_donor_reference_does_not_duplicate_candidates(all_project):
    g = new_generator(); root = all_project; donor = root / "data/donor"
    old.run(root, donor, fold=0)
    result = g.run(root, reuse_manifests=[donor / "manifest.json", donor / "manifest.json"])
    assert_all_source_contract(result, root / "data/sub_video")


def test_overlapping_folds_share_one_output_per_candidate(all_project, monkeypatch):
    g = new_generator(); root = all_project
    a, b = root / "data/donor0", root / "data/donor1"
    first = old.run(root, a, fold=0); second = old.run(root, b, fold=1)
    shared = {c["candidate_id"] for c in first["candidates"]} & {c["candidate_id"] for c in second["candidates"]}
    assert shared
    completed = {c["candidate_id"] for m in (first, second) for c in m["candidates"]}
    original = old.crop_video
    def fresh_only(roi, dest, c, *args, **kwargs):
        if c["candidate_id"] in completed: pytest.fail("overlapping fold candidate was encoded again")
        return original(roi, dest, c, *args, **kwargs)
    monkeypatch.setattr(old, "crop_video", fresh_only)
    result = g.run(root, reuse_manifests=[b / "manifest.json", a / "manifest.json"])
    assert_all_source_contract(result, root / "data/sub_video")
    assert all(sum(c["candidate_id"] == cid for c in result["candidates"]) == 1 for cid in shared)


@pytest.mark.parametrize("damage", ["output", "clip_receipt", "candidate_range", "candidate_label", "source_receipt", "annotation", "live_roi", "live_csv", "live_anchor_document", "media_frames", "media_duration", "media_dimensions", "mapping_start", "mapping_output_start", "decoded_sequence"])
def test_damaged_donor_never_adopted_or_silently_regenerated(all_project, monkeypatch, damage):
    g = new_generator(); root = all_project; donor = root / "data/donor"
    record = old.run(root, donor, fold=0)
    path = donor / "manifest.json"; candidate = record["candidates"][0]
    if damage == "output":
        (donor / candidate["output_path"]).write_bytes(b"changed media")
    elif damage == "clip_receipt": candidate["output"]["frame_preserving_replay"]["output_sha256"] = "0" * 64
    elif damage == "candidate_range": candidate["start_frame"] += 1
    elif damage == "candidate_label": candidate["candidate_labels"]["断裂状态"] = "已断裂"
    elif damage == "source_receipt": record["sources"][0]["frame_preserving_replay"]["source_sha256"] = "0" * 64
    elif damage == "annotation": record["sources"][0]["source_annotation"]["断裂位置"] = "无法确定"
    elif damage == "media_frames": candidate["output"]["media"]["total_frames"] += 1
    elif damage == "media_duration": candidate["output"]["media"]["duration"] += 0.5
    elif damage == "media_dimensions": candidate["output"]["media"]["width"] += 2
    elif damage == "mapping_start": candidate["output"]["frame_mapping"]["source_start_frame"] += 1
    elif damage == "mapping_output_start": candidate["output"]["frame_mapping"]["output_start_frame"] = 1
    elif damage == "decoded_sequence":
        receipt = candidate["output"]["frame_preserving_replay"]
        receipt["decoded_RGB_PTS_sequence_sha256"] = "0" * 64
        receipt["receipt_sha256"] = verification._digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    elif damage == "live_roi": (root / "data/roi/videos" / (candidate["source_video_id"] + ".mp4")).write_bytes(b"changed ROI")
    elif damage == "live_csv":
        current = root / "data/annotation-table-full.csv"; current.write_bytes(current.read_bytes() + b"\n")
    elif damage == "live_anchor_document":
        current = root / "docs/subvideo-current-logic.md"; current.write_text(current.read_text() + "\nchanged\n")
    path.write_text(json.dumps(record))
    original_crop = old.crop_video
    def forbidden(roi, dest, planned, *args, **kwargs):
        if planned["candidate_id"] == candidate["candidate_id"]:
            pytest.fail("corrupted donor cannot silently be regenerated")
        return original_crop(roi, dest, planned, *args, **kwargs)
    monkeypatch.setattr(old, "crop_video", forbidden)
    try:
        g.run(root, reuse_manifests=[path])
    except Exception:
        pass  # Global refusal and per-source refusal are both safe outcomes.
    assert not (root / "data/sub_video" / candidate["output_path"]).exists()


def test_all_source_resume_rejects_changed_input(all_project):
    g = new_generator(); root = all_project
    g.run(root, plan_only=True)
    path = root / "data/annotation-table-full.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(Exception): g.run(root, resume=True)


def test_relocated_inputs_cannot_relabel_an_unresolvable_historical_proof(all_project, monkeypatch):
    g = new_generator(); root = all_project; donor = root / "data/donor"
    record = old.run(root, donor, fold=0)
    migrated = root.parent / "migrated"
    shutil.copytree(root, migrated)
    first = record["candidates"][0]
    (root / "data/videos" / (first["source_video_id"] + ".mp4")).unlink()
    def forbidden(*args, **kwargs): pytest.fail("missing historical input must not trigger unrequested regeneration")
    monkeypatch.setattr(old, "crop_video", forbidden)
    try: g.run(migrated, reuse_manifests=[donor / "manifest.json"])
    except Exception: pass
    assert not (migrated / "data/sub_video" / first["output_path"]).exists()


@pytest.mark.parametrize("damage", ["missing_test_annotation", "duplicate_test_annotation", "test_in_train"])
def test_input_coverage_and_split_integrity_include_test(all_project, damage):
    g = new_generator(); root = all_project
    if damage == "test_in_train":
        path = root / "data/splits/three-fold/fold_0_train.json"
        payload = json.loads(path.read_text()); payload["video_ids"].append("video_9999")
        path.write_text(json.dumps(payload))
    else:
        path = root / "data/annotation-table-full.csv"
        lines = path.read_text().splitlines(keepends=True)
        test_line = next(line for line in lines if line.startswith("video_9999,"))
        if damage == "missing_test_annotation": lines.remove(test_line)
        else: lines.append(test_line)
        path.write_text("".join(lines))
    with pytest.raises(Exception): g.load_inputs(root)


def test_relocated_audit_checks_sealed_frame_mapping_not_only_matching_unsealed_fields(all_project):
    g = new_generator(); root = all_project
    record = g.run(root)
    output = root / "data/sub_video"
    assert g.audit_outputs(root, output)["verified_outputs"] == len(record["candidates"])
    candidate = record["candidates"][0]
    candidate["start_frame"] += 1
    candidate["output"]["frame_mapping"]["source_start_frame"] += 1
    (output / "manifest.json").write_text(json.dumps(record))
    with pytest.raises(Exception): g.audit_outputs(root, output)


def test_unclamped_donor_preserves_document_anchor_without_recropping(all_project, monkeypatch):
    g = new_generator(); root = all_project
    path = root / "data/annotation-table-full.csv"
    with path.open() as f: rows = list(csv.DictReader(f))
    row = next(r for r in rows if r["id"] == "video_0003")
    row.update(异常_未夹紧="是", 异常_视频异常="否", 断裂状态="未断裂", 断裂模式="无", 断裂位置="无", 断裂帧_前="无", 断裂帧_后="无", 断裂时间点="无")
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    anchor_document(root / "docs/subvideo-current-logic.md", [(row["id"], 55, digest(root / "data/videos/video_0003.mp4"))])
    donor = root / "data/donor"; old.run(root, donor, fold=0)
    original = old.crop_video
    def fresh_only(roi, dest, candidate, *args, **kwargs):
        if candidate["source_video_id"] == row["id"]: pytest.fail("verified unclamped clip was regenerated")
        return original(roi, dest, candidate, *args, **kwargs)
    monkeypatch.setattr(old, "crop_video", fresh_only)
    result = g.run(root, reuse_manifests=[donor / "manifest.json"])
    actual = [c for c in result["candidates"] if c["source_video_id"] == row["id"]]
    assert len(actual) == 3
    assert {c["target_duration_seconds"] for c in actual} == {2, 3, 5}
    for c in actual:
        assert c["role"] == c["event_kind"] == "unclamped"
        assert c["source_anchor_frames"] == [55]
        assert c["candidate_labels"]["断裂模式"] == c["candidate_labels"]["断裂位置"] == "无"
        assert c["output"]["frame_mapping"]["anchors"] == [{"source_frame": 55, "roi_frame": 55, "output_frame": 55 - c["start_frame"]}]
