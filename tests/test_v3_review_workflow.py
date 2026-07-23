import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.scripts.review_v3_candidates_app import (
    filter_candidate_ids,
    next_unreviewed_id,
    review_counts,
)
from pipeline.v3_review_decisions import validate_review_payload
from pipeline.v3_review_workflow import (
    V3ReviewWorkflowError,
    freeze_completed_batch,
    load_draft,
    load_review_queue,
    new_decision,
    save_draft,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _labels(state="发生断裂"):
    if state == "未断裂":
        return {
            "clip_state": state,
            "fracture_mechanism": None,
            "root_break": None,
            "location": None,
            "special_case": None,
        }
    return {
        "clip_state": state,
        "fracture_mechanism": "韧性断裂",
        "root_break": False,
        "location": "inside_gauge",
        "special_case": None,
    }


def _fixture(tmp_path: Path):
    video = tmp_path / "data/videos/c1.mp4"
    frame = tmp_path / "data/frames/c1/frame_0000.jpg"
    video.parent.mkdir(parents=True)
    frame.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    frame.write_bytes(b"frame")
    candidate = {
        "candidate_id": "c1",
        "source_video": "video_0001",
        "scope": "development",
        "review_disposition": "manual_required",
        "candidate_v3_labels": _labels(),
        "video_path": str(video.relative_to(tmp_path)),
        "video_sha256": _sha(video),
        "frame_artifacts": [
            {"path": str(frame.relative_to(tmp_path)), "sha256": _sha(frame)}
        ],
        "actual_frame_mapping": [
            {"input_index": 0, "clip_frame": 0, "timestamp": 1.0}
        ],
        "start_time": 1.0,
        "end_time": 3.0,
        "window_role": "transition",
        "reference_match": {"kind": "none", "reference_ids": []},
    }
    queue_path = tmp_path / "results/review_queue.json"
    queue = {
        "schema_version": "tensile-v3-candidate-media/v1",
        "media_id": "candidate-media-test",
        "scope": "development",
        "candidates": [candidate],
    }
    _write(queue_path, queue)
    manifest_path = tmp_path / "results/manifest.json"
    manifest = {
        "schema_version": "tensile-v3-candidate-media/v1",
        "media_id": "candidate-media-test",
        "media_generated": True,
        "counts": {"development_manual_review": 1},
        "artifacts": {"review_queue.json": {"sha256": _sha(queue_path)}},
    }
    _write(manifest_path, manifest)
    return queue_path, manifest_path, video


def test_queue_binds_manifest_candidate_media_and_sample_subset(tmp_path):
    queue_path, manifest_path, _ = _fixture(tmp_path)
    identity, candidates = load_review_queue(
        queue_path,
        manifest_path=manifest_path,
        project_root=tmp_path,
        limit=1,
    )
    assert identity["media_id"] == "candidate-media-test"
    assert identity["full_queue_count"] == 1
    assert identity["selected_candidate_ids"] == ["c1"]
    assert candidates[0]["_actual_sampled_timestamps"] == [1.0]


def test_queue_rejects_manifest_or_media_drift(tmp_path):
    queue_path, manifest_path, video = _fixture(tmp_path)
    video.write_bytes(b"drift")
    with pytest.raises(V3ReviewWorkflowError, match="视频 SHA-256"):
        load_review_queue(
            queue_path, manifest_path=manifest_path, project_root=tmp_path
        )


def test_queue_rejects_non_manual_state_before_sample_selection(tmp_path):
    queue_path, manifest_path, _ = _fixture(tmp_path)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["candidates"][0]["candidate_v3_labels"] = _labels("未断裂")
    _write(queue_path, queue)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["review_queue.json"]["sha256"] = _sha(queue_path)
    _write(manifest_path, manifest)
    with pytest.raises(V3ReviewWorkflowError, match="非人工复检状态"):
        load_review_queue(
            queue_path, manifest_path=manifest_path, project_root=tmp_path
        )


def test_draft_is_resumable_and_refuses_other_queue(tmp_path):
    queue_path, manifest_path, _ = _fixture(tmp_path)
    identity, candidates = load_review_queue(
        queue_path, manifest_path=manifest_path, project_root=tmp_path
    )
    record = new_decision(
        candidates[0],
        status="approved",
        corrected_labels=None,
        historical_suggested_labels=None,
        historical_reference_ids=[],
        reviewer_notes="checked",
        reviewer_id="reviewer-a",
        reviewed_at="2026-07-23T00:00:00+00:00",
    )
    draft = tmp_path / "draft.json"
    saved = save_draft(
        draft,
        identity,
        {"c1": record},
        updated_at="2026-07-23T00:00:00+00:00",
    )
    assert saved["reviewed_count"] == 1
    assert load_draft(draft, identity) == {"c1": record}

    other = {**identity, "media_id": "candidate-media-other"}
    with pytest.raises(V3ReviewWorkflowError, match="其他队列"):
        load_draft(draft, other)
    with pytest.raises(V3ReviewWorkflowError, match="其他队列"):
        save_draft(draft, other, {})


def test_freeze_requires_completion_and_is_content_addressed(tmp_path):
    queue_path, manifest_path, _ = _fixture(tmp_path)
    identity, candidates = load_review_queue(
        queue_path, manifest_path=manifest_path, project_root=tmp_path
    )
    with pytest.raises(V3ReviewWorkflowError, match="尚未完成"):
        freeze_completed_batch(tmp_path / "frozen", identity, {})
    record = new_decision(
        candidates[0],
        status="approved",
        corrected_labels=None,
        historical_suggested_labels=None,
        historical_reference_ids=[],
        reviewer_notes="checked",
        reviewer_id="reviewer-a",
        reviewed_at="2026-07-23T00:00:00+00:00",
    )
    batch = freeze_completed_batch(
        tmp_path / "frozen", identity, {"c1": record}
    )
    payload = json.loads(
        (batch / "decisions.json").read_text(encoding="utf-8")
    )
    validate_review_payload(payload)
    assert batch.name.startswith("review-batch-")
    assert json.loads(
        (batch / "summary.json").read_text(encoding="utf-8")
    )["decision_count"] == 1
    assert (
        freeze_completed_batch(
            tmp_path / "frozen", identity, {"c1": record}
        )
        == batch
    )
    relocated_identity = {
        **identity,
        "queue_path": "/relocated/review_queue.json",
        "manifest_path": "/relocated/manifest.json",
    }
    assert (
        freeze_completed_batch(
            tmp_path / "frozen", relocated_identity, {"c1": record}
        )
        == batch
    )


def test_corrected_must_differ_and_drop_requires_notes(tmp_path):
    queue_path, manifest_path, _ = _fixture(tmp_path)
    _, candidates = load_review_queue(
        queue_path, manifest_path=manifest_path, project_root=tmp_path
    )
    with pytest.raises(V3ReviewWorkflowError, match="不同"):
        new_decision(
            candidates[0],
            status="corrected",
            corrected_labels=_labels(),
            historical_suggested_labels=None,
            historical_reference_ids=[],
            reviewer_notes="",
            reviewer_id=None,
        )
    with pytest.raises(V3ReviewWorkflowError, match="reviewer_notes"):
        new_decision(
            candidates[0],
            status="dropped",
            corrected_labels=None,
            historical_suggested_labels=None,
            historical_reference_ids=[],
            reviewer_notes="",
            reviewer_id=None,
        )


def test_streamlit_entrypoint_bootstraps_project_imports_from_other_cwd(tmp_path):
    script = (
        Path(__file__).resolve().parents[1]
        / "pipeline/scripts/review_v3_candidates_app.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "v3 候选媒体人工复检 UI" in result.stdout


def test_workbench_filters_candidates_and_counts_terminal_statuses():
    candidates = [
        {"candidate_id": "c1", "source_video": "video_0001"},
        {"candidate_id": "c2", "source_video": "video_0001"},
        {"candidate_id": "c3", "source_video": "video_0002"},
    ]
    decisions = {
        "c1": {"review_status": "approved"},
        "c3": {"review_status": "needs_regenerate"},
    }
    assert review_counts(["c1", "c2", "c3"], decisions) == {
        "total": 3,
        "reviewed": 2,
        "remaining": 1,
        "approved": 1,
        "corrected": 0,
        "dropped": 0,
        "needs_regenerate": 1,
    }
    assert filter_candidate_ids(
        candidates,
        decisions,
        status_filter="未审核",
        source_filter=None,
        search="",
    ) == ["c2"]
    assert filter_candidate_ids(
        candidates,
        decisions,
        status_filter="全部",
        source_filter="video_0001",
        search="C",
    ) == ["c1", "c2"]
    assert filter_candidate_ids(
        candidates,
        decisions,
        status_filter="需重新生成",
        source_filter=None,
        search="video_0002",
    ) == ["c3"]


def test_workbench_next_unreviewed_wraps_after_current_candidate():
    candidate_ids = ["c1", "c2", "c3", "c4"]
    decisions = {
        "c1": {"review_status": "approved"},
        "c3": {"review_status": "approved"},
    }
    assert next_unreviewed_id(candidate_ids, decisions, after_id="c2") == "c4"
    decisions["c4"] = {"review_status": "approved"}
    assert next_unreviewed_id(candidate_ids, decisions, after_id="c4") == "c2"
    decisions["c2"] = {"review_status": "approved"}
    assert next_unreviewed_id(candidate_ids, decisions, after_id="c4") is None
