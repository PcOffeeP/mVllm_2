"""Unified rebuild acceptance and hostile resume checks, synthetic IO only."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from script.subvideo_generation.tests.rules_support import FRACTURE_ANCHOR_FIELDS
from script.subvideo_generation.tests.test_generation_contract import annotation, media
from .conftest import COVERAGE_IDS, RETIRED_COVERAGE_IDS, TEST_IDS, write_json


def read_manifest(root):
    return json.loads((root / "data/sub_video/manifest.json").read_text())


def test_empty_output_rebuilds_all_sources_once_and_preserves_each_fold(project):
    root, g, descriptions, encoded = project
    (root / "data/sub_video").mkdir()  # Empty output is a valid fresh target.
    input_paths = list((root / "data").rglob("*.json")) + [root / "data/annotation-table-full.csv",
                                                          root / "docs/subvideo-current-logic.md"]
    inputs = {str(p): p.read_bytes() for p in input_paths}
    m = g.run(root)
    assert m["complete"] is True and m["published"] is False
    assert len(m["sources"]) == len({s["video_id"] for s in m["sources"]}) == 110
    assert {c["source_video_id"] for c in m["candidates"]} == set(descriptions)
    assert len(encoded) == len(set(encoded)) == len(m["candidates"])
    assert len({c["output_path"] for c in m["candidates"]}) == len(encoded)
    assert {p.name for p in (root / "data/sub_video").iterdir()} <= {"videos", "manifest.json", "summary.json"}
    for c in m["candidates"]:
        assert c["scope"] == ("test" if c["source_video_id"] in TEST_IDS else "development")
        if c["source_video_id"] in TEST_IDS:
            assert c["folds"] == {"0": "test", "1": "test", "2": "test"}
        else:
            assert list(c["folds"].values()).count("val") == 1
            assert list(c["folds"].values()).count("train") == 2
        assert c["status"] == "cropped" and (root / "data/sub_video" / c["output_path"]).is_file()
        assert c["output"]["frame_preserving_replay"]["status"] == g.core.VERIFIED
        assert c["manual_review"] == "required" and c["final_labels"] is None
        assert c["review"]["status"] == "未审核" and c["labels_status"] == "unreviewed"
    assert all(p.read_bytes() == value for path, value in inputs.items() for p in [Path(path)])
    assert read_manifest(root) == m
    summary = json.loads((root / "data/sub_video/summary.json").read_text())
    assert summary["source_count"] == 110 and summary["complete"] is True
    assert g.audit_outputs(root, root / "data/sub_video")["verified_outputs"] == len(encoded)


def test_coverage_routes_keep_unknown_source_labels_and_start_from_them(project):
    root, g, _, _ = project
    m = g.run(root, plan_only=True)
    actual = {s["video_id"] for s in m["sources"] if s["strategy"] == "coverage"}
    # The fixture's coverage rows are the ones with no fracture anchor and an
    # undecidable 断裂状态; the route must follow those features, not the ids.
    assert actual == COVERAGE_IDS
    assert COVERAGE_IDS - RETIRED_COVERAGE_IDS and RETIRED_COVERAGE_IDS - COVERAGE_IDS, (
        "the fixture coverage set must differ from the retired id allowlist in both "
        "directions, otherwise this assertion cannot tell features from ids")
    seen = 0
    for c in m["candidates"]:
        if c["source_video_id"] not in COVERAGE_IDS:
            continue
        seen += 1
        source_labels = c["source_labels"]
        assert source_labels["断裂状态"] in ("无法判断", "无法确定", "未断裂"), (
            "source_labels must keep the wording the annotation actually used")
        if source_labels["断裂状态"] == "未断裂":
            expected = dict(source_labels, 断裂状态="未断裂", 断裂模式="无", 断裂位置="无")
        else:
            expected = dict(source_labels, 断裂状态="无法判断")
        assert c["candidate_labels"] == expected, (
            "a coverage candidate starts from the source's own 断裂状态 (无法确定 → 无法判断); "
            "an unbroken one records 无/无 for mode and location, an uncertain one keeps "
            "the source wording; nothing else may be rewritten")
        assert c["final_labels"] is None and c["labels_status"] == "unreviewed"
        assert c["manual_review"] == "required"
        assert c["event_kind"] == "none_unlocated" and c["source_anchor_frames"] == []
    assert seen, "the fixture must still produce coverage candidates"
    # The video-abnormal shape (video_0108): unbroken source, no anchor, 视频异常=是.
    abnormal_video = [c for c in m["candidates"] if c["source_video_id"] == "video_0108"]
    assert abnormal_video, (
        "an unanchored source whose video is flagged abnormal must be planned by the "
        "coverage route, not left pending by the event policy")
    assert all(c["source_labels"]["断裂状态"] == "未断裂" for c in abnormal_video)
    for c in abnormal_video:
        assert c["candidate_labels"]["断裂状态"] == "未断裂", (
            "video_0108 is 未断裂 in the source, so its candidate must start at 未断裂; "
            f"got {c['candidate_labels']['断裂状态']!r}")
        assert c["candidate_labels"]["断裂状态"] != "无法判断", (
            "an unbroken coverage source must not be relabelled 无法判断")
        assert c["candidate_labels"]["断裂模式"] == "无", (
            f"got {c['candidate_labels']['断裂模式']!r}")
        assert c["candidate_labels"]["断裂位置"] == "无", (
            f"got {c['candidate_labels']['断裂位置']!r}")
    # The retired rows also have to keep their source-mode wording initial values.
    uncertain = [c for c in m["candidates"]
                 if c["source_video_id"] in COVERAGE_IDS
                 and c["source_labels"]["断裂状态"] == "无法确定"]
    assert uncertain, "the fixture must still contain a 无法确定 coverage source"
    for c in uncertain:
        assert c["source_labels"]["异常情况"]["视频异常"] == "是"
        assert c["candidate_labels"]["断裂模式"] == "无法确定"
        assert c["candidate_labels"]["断裂位置"] == "无法确定"
    # A coverage source that was never on the retired list: 无法判断 + 无 in the source.
    never_listed = [c for c in m["candidates"] if c["source_video_id"] == "video_0003"]
    assert never_listed and all(
        c["source_labels"]["断裂状态"] == "无法判断" for c in never_listed)
    assert all(c["candidate_labels"]["断裂模式"] == "无" for c in never_listed), (
        "a source that says 无 keeps 无: only the uncertain state is rewritten")
    # A retired id is a plain unbroken source here (no abnormal-video flag), planned by
    # the event policy: the reverse control for the video-abnormal coverage branch.
    row = next(s for s in m["sources"] if s["video_id"] == "video_0107")
    assert row["strategy"] == "regular" and row["source_annotation"]["断裂状态"] == "未断裂"
    assert row["source_annotation"]["异常_视频异常"] != "是", (
        "video_0107 in this fixture is the control: 未断裂 *and* no video-abnormal flag, "
        "so it must stay on the event policy")
    one = [c for c in m["candidates"] if c["source_video_id"] == "video_0015"]
    assert [(c["start_frame"], c["end_frame"]) for c in one] == [(0, 200), (150, 350), (160, 360)]


@pytest.mark.parametrize("count,expected", [(5, [(0, 5)]), (190, [(0, 190)]), (200, [(0, 200)]),
    (210, [(0, 200), (10, 210)]), (350, [(0, 200), (150, 350)]),
    (360, [(0, 200), (150, 350), (160, 360)])])
def test_coverage_short_whole_stride_and_tail_through_unified_planner(project, count, expected):
    root, g, descriptions, _ = project
    descriptions["video_0015"] = dict(media(count=count, fps=10), time_base="1/1000000")
    rows, rois, folds, *_ = g.load_inputs(root)
    source, clips, _ = g._plan_source(root, "video_0015", rows["video_0015"], rois["video_0015"], folds["video_0015"], {})
    assert source["status"] == "planned"
    assert [(c["start_frame"], c["end_frame"]) for c in clips] == expected


def test_regular_event_and_0002_anchor_keep_approved_old_window_rules(project):
    root, g, descriptions, _ = project
    rows, rois, folds, *_ = g.load_inputs(root)
    descriptions["video_0001"] = dict(media(), time_base="1/1000000")
    row = annotation("video_0001")
    source, clips, _ = g._plan_source(root, "video_0001", row, rois["video_0001"], folds["video_0001"], {})
    assert source["strategy"] == "regular" and source["status"] == "planned"
    assert {c["window_role"] for c in clips} >= {"pre_event", "transition", "post_event"}
    for c in clips:
        if c["window_role"] == "pre_event": assert c["end_time"] <= 29.5 + 1e-8
        if c["window_role"] == "post_event": assert c["start_time"] >= 30.5 - 1e-8
        if c["window_role"] == "transition": assert c["start_frame"] < 300 < c["end_frame"]
    anchors = g.anchors.load_anchors(root / "docs/subvideo-current-logic.md")
    source, clips, excluded = g._plan_source(root, "video_0002", rows["video_0002"], rois["video_0002"], folds["video_0002"], anchors)
    assert source["strategy"] == "regular"
    assert {(c["start_frame"], c["end_frame"]) for c in clips} == {(134, 194), (104, 194), (44, 194)}
    assert all(c["role"] == "unclamped" and c["source_anchor_frames"] == [174] for c in clips)
    assert {w["target_duration_seconds"] for w in excluded} == {10, 20}


def test_0093_uses_presented_733_frames_and_does_not_force_an_event_window(project):
    root, g, _, _ = project
    rows, rois, folds, *_ = g.load_inputs(root)
    s, clips, _ = g._plan_source(root, "video_0093", rows["video_0093"], rois["video_0093"], folds["video_0093"], {})
    assert s["strategy"] == "0093" and s["status"] == "planned"
    assert clips and {c["role"] for c in clips} == {"pre"}
    assert all(c["source_anchor_frames"] == [727, 728] and c["end_frame"] <= 713 for c in clips)
    assert all(c["folds"] == {"0": "test", "1": "test", "2": "test"} for c in clips)


def test_route_follows_the_annotation_features_rather_than_the_source_id(project):
    """The old id allowlist is gone: one id routes differently by its own row."""
    root, g, _, _ = project
    rows, rois, folds, *_ = g.load_inputs(root)
    regular = rows["video_0001"]
    assert regular["断裂状态"] == "未断裂"
    assert all(regular.get(name) in (None, "", "无") for name in FRACTURE_ANCHOR_FIELDS)
    assert g.strategy_for("video_0001", regular) == "regular"

    unknown = dict(regular, 断裂状态="无法确定",
                   **{name: "无" for name in FRACTURE_ANCHOR_FIELDS})
    assert g.strategy_for("video_0001", unknown) == "coverage"

    source, clips, _ = g._plan_source(
        root, "video_0001", unknown, rois["video_0001"], folds["video_0001"], {})
    assert source["strategy"] == "coverage" and source["status"] == "planned", (
        source.get("reason"))
    assert [c["event_kind"] for c in clips] == ["none_unlocated"]

    anchored = dict(regular, 断裂状态="无法确定", 断裂帧_前="20", 断裂帧_后="21",
                    断裂时间点="2.1")
    assert g.strategy_for("video_0001", anchored) == "regular", (
        "a source with a usable anchor keeps the event policy whatever its status says")


def test_one_source_failure_is_persisted_and_cannot_masquerade_as_complete(project, monkeypatch):
    root, g, _, _ = project
    original = g.core.verify_source_replay
    def reject(raw, *args, **kwargs):
        if raw.stem == "video_0001": raise g.core.ReplayUncertain("injected missing frame evidence")
        return original(raw, *args, **kwargs)
    monkeypatch.setattr(g.core, "verify_source_replay", reject)
    m = g.run(root)
    assert len(m["sources"]) == 110 and m["complete"] is False
    assert not any(c["source_video_id"] == "video_0001" for c in m["candidates"])
    assert next(s for s in m["sources"] if s["video_id"] == "video_0001")["status"] != "planned"
    assert json.loads((root / "data/sub_video/summary.json").read_text())["complete"] is False


@pytest.mark.parametrize("failed_id,failure_status", [("video_0002", "pending"), ("video_0005", "failed")])
def test_resume_retries_only_transient_failed_source_and_preserves_completed_outputs(
        project, monkeypatch, failed_id, failure_status):
    root, g, _, encoded = project
    original = g.core.verify_source_replay
    replay_calls = []
    unavailable = True
    def temporary_failure(raw, *args, **kwargs):
        replay_calls.append(raw.stem)
        if raw.stem == failed_id and unavailable:
            if failure_status == "pending":
                raise g.core.ReplayUncertain("temporary source replay unavailable")
            raise OSError("temporary source read unavailable")
        return original(raw, *args, **kwargs)
    monkeypatch.setattr(g.core, "verify_source_replay", temporary_failure)
    first = g.run(root)
    failed = next(s for s in first["sources"] if s["video_id"] == failed_id)
    assert failed["status"] == failure_status and "temporary source" in failed["reason"]
    assert first["complete"] is False
    completed = {c["candidate_id"]: copy.deepcopy(c) for c in first["candidates"]}
    output_bytes = {c["output_path"]: (root / "data/sub_video" / c["output_path"]).read_bytes()
                    for c in first["candidates"]}
    before_encoded = list(encoded)
    replay_calls.clear()
    unavailable = False
    result = g.run(root, resume=True)
    assert result["complete"] is True
    assert replay_calls == [failed_id], "admitted sources must keep their existing replay proof"
    recovered = next(s for s in result["sources"] if s["video_id"] == failed_id)
    assert recovered["status"] == "planned" and not recovered.get("reason")
    added = [c for c in result["candidates"] if c["source_video_id"] == failed_id]
    assert added and all(c["status"] == "cropped" and c["folds"] == failed["folds"] for c in added)
    assert all(c["scope"] == ("test" if failed_id in TEST_IDS else "development") for c in added)
    assert encoded[:len(before_encoded)] == before_encoded
    assert set(encoded[len(before_encoded):]) == {c["candidate_id"] for c in added}
    assert len(encoded) == len(set(encoded))
    assert all(c == completed[c["candidate_id"]] for c in result["candidates"] if c["candidate_id"] in completed)
    assert all((root / "data/sub_video" / path).read_bytes() == value for path, value in output_bytes.items())
    assert [s["video_id"] for s in result["sources"]] == sorted(s["video_id"] for s in result["sources"])
    source_order = [c["source_video_id"] for c in result["candidates"]]
    assert source_order == sorted(source_order)
    excluded_order = [w["source_video_id"] for w in result["excluded_windows"]]
    assert excluded_order == sorted(excluded_order)
    assert g.audit_outputs(root, root / "data/sub_video")["verified_outputs"] == len(result["candidates"])


def test_resume_retries_persisting_source_failure_once_per_run_with_explicit_reason(project, monkeypatch):
    root, g, _, encoded = project
    original = g.core.verify_source_replay
    attempts = []
    def still_unavailable(raw, *args, **kwargs):
        if raw.stem == "video_0001":
            attempts.append(raw.stem)
            raise g.core.ReplayUncertain("temporary source replay still unavailable")
        return original(raw, *args, **kwargs)
    monkeypatch.setattr(g.core, "verify_source_replay", still_unavailable)
    g.run(root)
    before = list(encoded)
    for expected_attempts in (2, 3):
        result = g.run(root, resume=True)
        source = next(s for s in result["sources"] if s["video_id"] == "video_0001")
        assert source["status"] == "pending" and source["reason"] == "temporary source replay still unavailable"
        assert len(attempts) == expected_attempts
        assert result["complete"] is False and encoded == before
        assert not any(c["source_video_id"] == "video_0001" for c in result["candidates"])


def test_resume_checks_input_identity_before_retrying_failed_source(project, monkeypatch):
    root, g, _, encoded = project
    original = g.core.verify_source_replay
    def unavailable(raw, *args, **kwargs):
        if raw.stem == "video_0001": raise g.core.ReplayUncertain("temporary source failure")
        return original(raw, *args, **kwargs)
    monkeypatch.setattr(g.core, "verify_source_replay", unavailable)
    g.run(root)
    manifest_path = root / "data/sub_video/manifest.json"
    before_manifest, before_encoded = manifest_path.read_bytes(), list(encoded)
    annotation_path = root / "data/annotation-table-full.csv"
    annotation_path.write_bytes(annotation_path.read_bytes() + b"\n")
    def forbidden_replay(*args, **kwargs): pytest.fail("input identity must be checked before source retry")
    monkeypatch.setattr(g.core, "verify_source_replay", forbidden_replay)
    with pytest.raises(Exception): g.run(root, resume=True)
    assert manifest_path.read_bytes() == before_manifest and encoded == before_encoded


@pytest.mark.parametrize("attack", ["drop_source", "duplicate_source", "drop_candidate", "duplicate_candidate", "invent_candidate",
    "source_fold", "candidate_fold", "source_scope", "candidate_scope", "source_strategy",
    "range", "labels", "proof", "schema", "published"])
def test_resume_refuses_tampered_inventory_before_encoding(project, attack):
    root, g, _, encoded = project
    m = g.run(root, plan_only=True)
    test_source = next(s for s in m["sources"] if s["video_id"] == "video_0005")
    test_clip = next(c for c in m["candidates"] if c["source_video_id"] == "video_0005")
    if attack == "drop_source": m["sources"].pop()
    elif attack == "duplicate_source": m["sources"].append(copy.deepcopy(m["sources"][0]))
    elif attack == "drop_candidate": m["candidates"].pop()
    elif attack == "duplicate_candidate": m["candidates"].append(copy.deepcopy(m["candidates"][0]))
    elif attack == "invent_candidate":
        fake = copy.deepcopy(m["candidates"][0]); fake["candidate_id"] += "_invented"; m["candidates"].append(fake)
    elif attack == "source_fold": test_source["folds"] = dict.fromkeys(("0", "1", "2"), "train")
    elif attack == "candidate_fold": test_clip["folds"] = dict.fromkeys(("0", "1", "2"), "train")
    elif attack == "source_scope": test_source["scope"] = "development"
    elif attack == "candidate_scope": test_clip["scope"] = "development"
    elif attack == "source_strategy":
        # The stored route is downgraded to the event policy while the annotation
        # still says coverage: the plan must be replanned from the inputs, not trusted.
        assert test_source["strategy"] == "coverage"
        test_source["strategy"] = "regular"
    elif attack == "range": test_clip["start_frame"] += 1
    elif attack == "labels": test_clip["candidate_labels"] = {"断裂状态": "发生断裂"}
    elif attack == "proof": m["sources"][0]["frame_preserving_replay"]["source_sha256"] = "0" * 64
    elif attack == "schema": m["schema"] = "legacy-batch"
    elif attack == "published": m["published"] = True
    path = root / "data/sub_video/manifest.json"; write_json(path, m); before = path.read_bytes()
    with pytest.raises(Exception) as caught: g.run(root, resume=True)
    if attack == "source_strategy":
        assert isinstance(caught.value, g.base.PilotError) and "strategy" in str(caught.value), (
            "a tampered source route must be rejected by the replanned strategy check, "
            f"got {caught.value!r}")
    assert not encoded and path.read_bytes() == before


# Code identity is no longer part of the batch identity, so changing code can no
# longer reject a resume; that positive case lives in test_identity_ignores_code.py.
@pytest.mark.parametrize("change", ["annotation", "split", "roi_manifest", "anchor_document", "source", "roi"])
def test_resume_rejects_changed_live_input_before_writing(project, change):
    root, g, _, encoded = project
    g.run(root, plan_only=True)
    path = root / "data/sub_video/manifest.json"; before = path.read_bytes()
    paths = {"annotation": "data/annotation-table-full.csv", "split": "data/splits/three-fold/fold_0_train.json",
        "roi_manifest": "data/roi/manifest.json", "anchor_document": "docs/subvideo-current-logic.md",
        "source": "data/videos/video_0001.mp4", "roi": "data/roi/videos/video_0001.mp4"}
    target = root / paths[change]; target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(Exception): g.run(root, resume=True)
    assert path.read_bytes() == before and not encoded


def test_existing_outputs_and_old_batch_are_never_adopted(project):
    root, g, _, encoded = project
    target = root / "data/sub_video"
    write_json(target / "manifest.json", {"schema": "old-batch", "candidates": []})
    marker = target / "videos/previous.mp4"; marker.parent.mkdir(); marker.write_bytes(b"keep previous bytes")
    for resume in (False, True):
        with pytest.raises(Exception): g.run(root, resume=resume)
    assert marker.read_bytes() == b"keep previous bytes" and not encoded


@pytest.mark.parametrize("inventory", ["annotation", "ROI", "split"])
def test_duplicate_input_ids_are_rejected_without_output(project, inventory):
    root, g, _, encoded = project
    if inventory == "annotation":
        path = root / "data/annotation-table-full.csv"
        with path.open() as stream: lines = stream.readlines()
        path.write_text("".join(lines + [lines[1]]))
    else:
        path = root / ("data/roi/manifest.json" if inventory == "ROI" else "data/splits/three-fold/test.json")
        value = json.loads(path.read_text()); key = "videos" if inventory == "ROI" else "video_ids"
        value[key].append(copy.deepcopy(value[key][0])); write_json(path, value)
    with pytest.raises(Exception): g.run(root)
    assert not encoded


def test_plan_then_resume_encodes_each_output_once_and_complete_resume_is_idempotent(project):
    root, g, _, encoded = project
    planned = g.run(root, plan_only=True)
    assert planned["complete"] is False and not encoded
    final = g.run(root, resume=True)
    assert final["complete"] is True
    before = list(encoded)
    assert g.run(root, resume=True) == final
    assert encoded == before


def test_interruption_resumes_only_the_unfinished_candidates(project, monkeypatch):
    root, g, _, encoded = project
    original = g.legacy.crop_video
    interrupted = False
    def stop_after_one(*args, **kwargs):
        nonlocal interrupted
        if encoded and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("synthetic cancellation before next encoding")
        return original(*args, **kwargs)
    monkeypatch.setattr(g.legacy, "crop_video", stop_after_one)
    with pytest.raises(KeyboardInterrupt): g.run(root)
    persisted = read_manifest(root)
    completed = [c["candidate_id"] for c in persisted["candidates"] if c["status"] == "cropped"]
    assert completed == encoded and completed
    monkeypatch.setattr(g.legacy, "crop_video", original)
    result = g.run(root, resume=True)
    assert result["complete"] is True
    assert len(encoded) == len(set(encoded)) == len(result["candidates"])


def test_unknown_output_after_interruption_is_never_overwritten_or_adopted(project):
    root, g, _, encoded = project
    planned = g.run(root, plan_only=True)
    path = root / "data/sub_video" / planned["candidates"][0]["output_path"]
    path.write_bytes(b"unrecorded output from interrupted external process")
    before = path.read_bytes()
    with pytest.raises(Exception): g.run(root, resume=True)
    assert path.read_bytes() == before and not encoded


def test_readonly_audit_supports_copy_to_another_machine_without_rewriting_proofs(project, monkeypatch, tmp_path):
    root, g, _, _ = project
    original = g.run(root)
    relocated = tmp_path / "copied-project"
    shutil.copytree(root, relocated)
    root.rename(tmp_path / "unavailable-origin")  # Historical absolute paths cannot resolve on this host.
    # Simulate host-specific binary paths and version boundary. Audit must check
    # sealed historical evidence, rather than assert a new replay occurred here.
    def no_local_toolchain():
        raise g.core.ReplayUncertain("local host is not the production replay toolchain")
    monkeypatch.setattr(g.core, "_toolchain", no_local_toolchain)
    monkeypatch.setattr(g.special_verification, "_toolchain", no_local_toolchain)
    before = {str(p.relative_to(relocated)): p.read_bytes() for p in relocated.rglob("*") if p.is_file()}
    audit = g.audit_outputs(relocated, relocated / "data/sub_video", portable=True)
    assert audit["verified_outputs"] == len(original["candidates"])
    assert audit["published"] is False
    assert audit["validation_level"] == "byte_receipt_and_source_timeline_only"
    assert "no_current_output_RGB_PTS_decode" in audit["limitations"]
    assert "not_new_frame_replay" in audit["limitations"]
    assert "not_human_label_review" in audit["limitations"]
    assert before == {str(p.relative_to(relocated)): p.read_bytes() for p in relocated.rglob("*") if p.is_file()}
    with pytest.raises(Exception): g.run(relocated, resume=True)
    for relative in ("data/videos/video_0001.mp4", "data/roi/videos/video_0001.mp4",
                     "data/annotation-table-full.csv", "data/splits/three-fold/fold_0_train.json",
                     "docs/subvideo-current-logic.md", "data/sub_video/" + original["candidates"][0]["output_path"]):
        target = relocated / relative
        previous = target.read_bytes()
        target.write_bytes(previous + b"\nchanged copy\n")
        with pytest.raises(Exception): g.audit_outputs(relocated, relocated / "data/sub_video", portable=True)
        target.write_bytes(previous)


@pytest.mark.parametrize("damage", ["bytes", "clip_proof", "missing_proof", "mapping", "unreviewed"])
def test_audit_refuses_corrupt_completed_evidence(project, damage):
    root, g, _, _ = project
    m = g.run(root); c = m["candidates"][0]
    if damage == "bytes": (root / "data/sub_video" / c["output_path"]).write_bytes(b"corrupt output")
    elif damage == "clip_proof": c["output"]["frame_preserving_replay"]["decoded_frame_count"] += 1
    elif damage == "missing_proof": del c["output"]["frame_preserving_replay"]
    elif damage == "mapping": c["output"]["frame_mapping"]["output_start_frame"] = 1
    elif damage == "unreviewed": c["final_labels"] = {"断裂状态": "发生断裂"}
    write_json(root / "data/sub_video/manifest.json", m)
    with pytest.raises(Exception): g.audit_outputs(root, root / "data/sub_video")


def test_portable_audit_rejects_invented_output_media_without_altering_sealed_proof(project):
    root, g, _, _ = project
    original = g.run(root)
    manifest_path = root / "data/sub_video/manifest.json"
    candidate = original["candidates"][0]
    output_path = root / "data/sub_video" / candidate["output_path"]
    original_output = output_path.read_bytes()
    original_proof = copy.deepcopy(candidate["output"]["frame_preserving_replay"])
    for field, value in (("total_frames", 1), ("duration", 999.0), ("width", 2),
                         ("height", 2), ("fps", 99.0), ("time_base", "1/999")):
        manifest = copy.deepcopy(original)
        manifest["candidates"][0]["output"]["media"][field] = value
        write_json(manifest_path, manifest)
        with pytest.raises(Exception): g.audit_outputs(root, root / "data/sub_video", portable=True)
        assert output_path.read_bytes() == original_output
        persisted = read_manifest(root)
        assert persisted["candidates"][0]["output"]["frame_preserving_replay"] == original_proof
    write_json(manifest_path, original)
    assert g.audit_outputs(root, root / "data/sub_video", portable=True)["verified_outputs"] == len(original["candidates"])
