"""Synthetic public-API handoff checks; no real media or model is involved.

The .mp4 files contain fixture bytes, not decodable video. This exercises
identity verification and persistence, not playback or visual label quality.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os

import pytest

from script.five_label_eval.score import InputError, read_json, read_jsonl, score
from script.subvideo_review.server import ReviewApp, ReviewError


LABELS = {
    "断裂状态": "发生断裂",
    "断裂模式": "韧性断裂",
    "断裂位置": "标距内",
    "异常情况": {"未夹紧": "否", "视频异常": "否", "爆炸性断裂": "否"},
    "断裂现象": {"伸长": "是", "颈缩": "是", "开裂": "否", "界面分离": "否", "断后脱夹": "否"},
}
IDENTITY_FIELDS = (
    "manifest_sha256", "candidate_id", "clip_sha256", "source_id", "source_type", "review_id",
)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


@pytest.fixture
def workspace(tmp_path):
    """Nine real and one virtual independent synthetic sources, never project data."""
    names = ("good", "unknown", "missing", "failed", "unprocessed", "draft", "question", "returned", "unreviewed", "virtual")
    generation = tmp_path / "data/sub_video"
    (generation / "videos").mkdir(parents=True)
    sources, candidates = [], []
    for name in names:
        source_bytes = ("synthetic source " + name).encode()
        source = tmp_path / "synthetic-sources" / f"{name}.mp4"
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(source_bytes)
        clip_bytes = ("synthetic clip " + name).encode()
        (generation / "videos" / f"{name}.mp4").write_bytes(clip_bytes)
        kind = "virtual" if name == "virtual" else "real"
        sources.append({"video_id": f"source-{name}", "source_type": kind,
                        "source_annotation": copy.deepcopy(LABELS),
                        "source_sha256": hashlib.sha256(source_bytes).hexdigest()})
        candidates.append({"candidate_id": name, "source_video_id": f"source-{name}",
                           "source_type": kind, "output_path": f"videos/{name}.mp4",
                           "output": {"sha256": hashlib.sha256(clip_bytes).hexdigest()}})
    manifest_path = generation / "manifest.json"
    write_json(manifest_path, {"schema": "synthetic-integration-fixture", "generation_batch_id": "batch-a",
                               "identity": {"scope": "development"}, "sources": sources, "candidates": candidates})
    write_json(tmp_path / "data/splits/three-fold/test.json", {"video_ids": []})
    for fold in range(3):
        write_json(tmp_path / f"data/splits/three-fold/fold_{fold}_train.json",
                   {"video_ids": [f"source-{name}" for name in names]})
        write_json(tmp_path / f"data/splits/three-fold/fold_{fold}_val.json", {"video_ids": []})
    return ReviewApp(tmp_path)


def save(app, name, labels=None, status="confirmed"):
    candidate = app.candidate(name)
    previous = app.review(name)["latest"]
    return app.save({"candidate_id": name, "manifest_sha256": app.manifest_sha256,
                     "clip_sha256": candidate["clip_sha256"], "review_status": status,
                     "labels": copy.deepcopy(LABELS if labels is None else labels),
                     "expected_review_id": previous["review_id"] if previous else None,
                     "reason": "synthetic fixture decision"})


def exported(app, *, all_revisions=False):
    path = app.root / "handoff" / "reviews.jsonl"
    path.parent.mkdir(exist_ok=True)
    path.write_text(app.export(all_revisions=all_revisions), encoding="utf-8")
    return read_jsonl(path)


def frozen_manifest(app, reviews):
    manifest = {"manifest_version": "synthetic-score-fixture/1",
                "samples": [{key: row[key] for key in IDENTITY_FIELDS} for row in reviews]}
    path = app.root / "handoff" / "score-manifest.json"
    write_json(path, manifest)
    return read_json(path)


def prediction(app, name, labels=None, status="success"):
    return {"candidate_id": name, "clip_sha256": app.candidate(name)["clip_sha256"],
            "run_id": "synthetic-run", "model_id": "synthetic-model", "prompt_id": "synthetic-prompt",
            "input_id": f"input-{name}", "request_id": f"request-{name}", "status": status,
            "raw_output": json.dumps(LABELS if labels is None else labels, ensure_ascii=False) if status == "success" else None}


def assert_ratio(metric, numerator, denominator):
    assert metric["numerator"] == numerator
    assert metric["denominator"] == denominator
    assert metric["value"] == (pytest.approx(numerator / denominator) if denominator else None)


def test_reference_labels_do_not_become_truth_and_raw_export_can_be_scored(workspace):
    app = workspace
    initial = app.bootstrap()["candidates"]
    assert all(row["review_status"] == "unreviewed" and row["review_id"] is None for row in initial)
    assert all("labels" not in row or row["labels"] == {} for row in initial)
    assert initial[0]["source_reference"] == LABELS  # Reference is deliberately nonempty.
    rows = exported(app)
    assert all(row["labels"] == {} for row in rows)
    result = score(frozen_manifest(app, rows), rows, [prediction(app, "good")])
    real = result["groups"]["real"]["full_clip"]
    assert real["review_status_counts"] == {"unreviewed": 9}
    assert_ratio(real["fields"]["断裂状态"]["accuracy"], 0, 0)
    assert real["fields"]["断裂状态"]["truth_counts"] == {"unlabeled": 9}


def test_persisted_confirmed_export_has_hand_calculated_separate_denominators(workspace):
    app = workspace
    for name in ("good", "missing", "failed", "unprocessed"):
        save(app, name)
    unknown = copy.deepcopy(LABELS)
    unknown["断裂现象"]["颈缩"] = "无法判断"
    save(app, "unknown", unknown)
    virtual = copy.deepcopy(LABELS)
    virtual["断裂现象"]["颈缩"] = "否"
    save(app, "virtual", virtual)
    for status in ("draft", "question", "returned"):
        save(app, status, status=status)  # Complete labels still are not confirmed truth.
    reopened = ReviewApp(app.root)
    rows = exported(reopened)
    manifest = frozen_manifest(reopened, rows)
    missing = copy.deepcopy(LABELS)
    del missing["断裂现象"]["颈缩"]
    predictions = [prediction(app, "good"), prediction(app, "unknown"),
                   prediction(app, "missing", missing), prediction(app, "failed", status="request_failed"),
                   prediction(app, "virtual")]
    result = score(manifest, rows, predictions)
    real = result["groups"]["real"]["full_clip"]
    assert real["clips"] == 9 and real["sources"] == 9
    assert real["request_status_counts"] == {"success": 3, "request_failed": 1, "unprocessed": 5}
    assert real["review_status_counts"] == {"confirmed": 5, "draft": 1, "question": 1, "returned": 1, "unreviewed": 1}
    neck = real["fields"]["断裂现象.颈缩"]
    assert neck["truth_counts"] == {"valid": 4, "unknown": 1, "unlabeled": 4}
    assert neck["prediction_counts"] == {"valid": 2, "missing": 1, "request_failed": 1, "unprocessed": 5}
    # Three attempted positive truths: correct, missing item, failed request.
    # Human unknown and unprocessed truths add no negative examples or attempts.
    assert_ratio(neck["accuracy"], 1, 3)
    assert_ratio(neck["recall"], 1, 3)
    assert (neck["TP"], neck["FN"], neck["FP"], neck["TN"]) == (1, 0, 0, 0)
    assert (neck["positive_attempted"], neck["negative_attempted"]) == (3, 0)
    assert neck["failures_or_uncertain_by_truth"] == {"是:missing": 1, "是:request_failed": 1}
    assert_ratio(real["fields"]["断裂状态"]["accuracy"], 3, 4)
    assert_ratio(real["all_five_correct_supplement"], 1, 3)
    virtual_metrics = result["groups"]["virtual"]["full_clip"]["fields"]["断裂现象.颈缩"]
    assert_ratio(virtual_metrics["accuracy"], 0, 1)
    assert virtual_metrics["FP"] == 1 and virtual_metrics["negative_attempted"] == 1
    assert_ratio(virtual_metrics["false_positive_rate_explicit_only"], 1, 1)
    # No actual-input review was supplied; a full-clip answer must not leak into it.
    actual = result["groups"]["real"]["actual_input"]
    assert_ratio(actual["fields"]["断裂状态"]["accuracy"], 0, 0)


@pytest.mark.parametrize("field", ["review_id", "clip_sha256", "manifest_sha256"])
def test_frozen_review_identity_mismatch_is_rejected(workspace, field):
    app = workspace
    save(app, "good")
    rows = [r for r in exported(app) if r["candidate_id"] == "good"]
    manifest = frozen_manifest(app, rows)
    manifest["samples"][0][field] = "another-review" if field == "review_id" else "0" * 64
    with pytest.raises(InputError):
        score(manifest, rows, [prediction(app, "good")])


def test_prediction_same_name_with_other_clip_digest_is_rejected(workspace):
    app = workspace
    save(app, "good")
    rows = [r for r in exported(app) if r["candidate_id"] == "good"]
    manifest = frozen_manifest(app, rows)
    wrong = prediction(app, "good")
    wrong["clip_sha256"] = "f" * 64
    with pytest.raises(InputError):
        score(manifest, rows, [wrong])


def test_new_revision_keeps_old_record_and_cannot_silently_replace_frozen_truth(workspace):
    app = workspace
    first = save(app, "good")
    old_rows = [r for r in exported(app) if r["candidate_id"] == "good"]
    manifest = frozen_manifest(app, old_rows)
    revised = copy.deepcopy(LABELS)
    revised["断裂位置"] = "夹持根部"
    second = save(app, "good", revised)
    assert second["review_id"] != first["review_id"]
    history = ReviewApp(app.root).review("good")["history"]
    assert history == [first, second]
    assert history[0]["labels"]["断裂位置"] == "标距内"
    latest_rows = [r for r in exported(app) if r["candidate_id"] == "good"]
    with pytest.raises(InputError):
        score(manifest, latest_rows, [prediction(app, "good")])
    old_result = score(manifest, old_rows, [prediction(app, "good")])
    assert_ratio(old_result["groups"]["real"]["full_clip"]["fields"]["断裂位置"]["accuracy"], 1, 1)
    # Explicit history export can reproduce the old locked truth after revision.
    history_result = score(manifest, exported(app, all_revisions=True), [prediction(app, "good")])
    assert history_result["samples"][0]["sample"]["review_id"] == first["review_id"]
    assert_ratio(history_result["groups"]["real"]["full_clip"]["fields"]["断裂位置"]["accuracy"], 1, 1)


@pytest.mark.parametrize("change", ["batch", "clip"])
def test_regenerated_candidate_does_not_inherit_confirmation(workspace, change):
    app = workspace
    first = save(app, "good")
    manifest = json.loads(app.manifest_path.read_text(encoding="utf-8"))
    if change == "batch":
        manifest["generation_batch_id"] = "batch-b"
    else:
        new_bytes = b"synthetic regenerated clip with same candidate name"
        (app.media_root / "videos/good.mp4").write_bytes(new_bytes)
        manifest["candidates"][0]["output"]["sha256"] = hashlib.sha256(new_bytes).hexdigest()
    write_json(app.manifest_path, manifest)
    with pytest.raises(ReviewError):
        app.export()  # A running app must not continue after its manifest changes.
    reopened = ReviewApp(app.root)
    review = reopened.review("good")
    assert review["latest"] is None and review["history"] == []
    assert review["isolated_history"] == [first]
    rows = exported(reopened)
    good = next(row for row in rows if row["candidate_id"] == "good")
    assert good["review_id"] is None and good["review_status"] == "unreviewed" and good["labels"] == {}
    result = score(frozen_manifest(reopened, rows), rows, [prediction(reopened, "good")])
    assert_ratio(result["groups"]["real"]["full_clip"]["fields"]["断裂状态"]["accuracy"], 0, 0)


def test_conflicting_model_output_keeps_raw_and_scores_individual_fields(workspace):
    app = workspace
    save(app, "good")
    rows = [r for r in exported(app) if r["candidate_id"] == "good"]
    conflicting = copy.deepcopy(LABELS)
    conflicting["断裂状态"] = "未断裂"  # Conflicts with the two non-'无' fields.
    pred = prediction(app, "good", conflicting)
    result = score(frozen_manifest(app, rows), rows, [pred])
    sample = result["samples"][0]
    assert sample["prediction"]["raw_output"] == pred["raw_output"]
    assert sample["extraction"]["conflicts"]
    metrics = result["groups"]["real"]["full_clip"]
    assert metrics["prediction_combination_conflicts"] == 1
    assert_ratio(metrics["fields"]["断裂状态"]["accuracy"], 0, 1)
    assert_ratio(metrics["fields"]["断裂位置"]["accuracy"], 1, 1)


def test_actual_input_review_is_bound_to_request_and_does_not_replace_full_clip_truth(workspace):
    app = workspace
    save(app, "good")
    rows = [r for r in exported(app) if r["candidate_id"] == "good"]
    manifest = frozen_manifest(app, rows)
    pred = prediction(app, "good")
    pred["input_review_id"] = "synthetic-input-review"
    fields = {key: {"label": value, "evidence": "sufficient"}
              for key, value in LABELS.items() if not isinstance(value, dict)}
    for group in ("异常情况", "断裂现象"):
        fields[group] = {key: {"label": value, "evidence": "sufficient"}
                         for key, value in LABELS[group].items()}
    fields["断裂状态"] = {"label": "无法确定", "evidence": "insufficient"}
    input_review = {key: pred[key] for key in ("candidate_id", "clip_sha256", "run_id", "model_id", "prompt_id", "input_id", "request_id", "input_review_id")}
    input_review.update(review_status="confirmed", fields=fields)
    result = score(manifest, rows, [pred], [input_review])
    group = result["groups"]["real"]
    assert_ratio(group["full_clip"]["fields"]["断裂状态"]["accuracy"], 1, 1)
    assert_ratio(group["actual_input"]["fields"]["断裂状态"]["accuracy"], 0, 1)
    diagnostic = group["actual_input"]["evidence_by_field"]["断裂状态"]["insufficient"]
    assert diagnostic["clips"] == 1 and diagnostic["sources"] == 1
    assert_ratio(diagnostic["metrics"]["accuracy"], 0, 1)
    # A valid input diagnosis of another request must not be reused implicitly.
    wrong_request = copy.deepcopy(input_review)
    wrong_request["request_id"] = "other-request"
    with pytest.raises(InputError):
        score(manifest, rows, [pred], [wrong_request])


def test_hash_read_does_not_treat_normal_access_time_update_as_media_replacement(workspace):
    app = workspace
    path = app.media_root / "videos/good.mp4"
    before = path.stat()
    # Reading a never-recently-accessed file may legitimately advance st_atime.
    # Neither the fixture bytes nor mtime changes before the public save call.
    os.utime(path, ns=(0, before.st_mtime_ns))
    saved = save(app, "good")
    assert saved["review_status"] == "confirmed"
    rows = [r for r in exported(app) if r["candidate_id"] == "good"]
    result = score(frozen_manifest(app, rows), rows, [prediction(app, "good")])
    assert_ratio(result["groups"]["real"]["full_clip"]["all_five_correct_supplement"], 1, 1)
