from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.scripts.archive import merge_incremental_review_decisions as merge
from pipeline.scripts.archive import materialize_incremental_review_media as materialize
from pipeline.scripts.archive import append_incremental_failure_drops as failure_drops
from pipeline.scripts.archive import prepare_incremental_review_queue as queue
from pipeline.scripts.archive import review_subvideos_app as app


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _subvideo(sid: str, source: str = "video_0001") -> dict:
    return {
        "subvideo_id": sid,
        "source_video": source,
        "crop_type": "focus_3s",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "fracture_between": [1, 2],
        "actual_frame_mapping": [
            {"original_frame": 0}, {"original_frame": 10}, {"original_frame": 20},
        ],
    }


def _decision(sid: str, status: str, interval: list[int] | None = [1, 2]) -> dict:
    return {
        "subvideo_id": sid,
        "status": status,
        "original_labels": {"fracture_between": [1, 2]},
        "corrected_labels": {"fracture_between": interval} if status == "approved" else None,
        "reviewer_notes": "baseline",
    }


def test_queue_selects_needs_regenerate_without_mutating_baseline(tmp_path: Path):
    metadata = tmp_path / "meta.json"
    decisions = tmp_path / "decisions.json"
    video_meta = tmp_path / "video_meta.json"
    queue_meta = tmp_path / "queue.json"
    queue_csv = tmp_path / "queue.csv"
    _write(metadata, {"subvideos": [_subvideo("sv_keep"), _subvideo("sv_regen")]})
    _write(decisions, {"decisions": [_decision("sv_keep", "approved"), _decision("sv_regen", "needs_regenerate")]})
    _write(video_meta, [{"video_id": "video_0001", "event_frame_effective": 15}])

    summary = queue.prepare_incremental_review_queue(metadata, decisions, video_meta, queue_meta, queue_csv)

    assert summary["queue_count"] == 1
    payload = json.loads(queue_meta.read_text(encoding="utf-8"))
    assert payload["incremental_review_queue"]["queue_ids"] == ["sv_regen"]
    assert payload["subvideos"][0]["incremental_review"]["baseline_status"] == "needs_regenerate"
    assert len(json.loads(decisions.read_text(encoding="utf-8"))["decisions"]) == 2


def test_merge_replaces_regenerate_but_rejects_approved_without_flag(tmp_path: Path):
    baseline = tmp_path / "baseline.json"
    queue_meta = tmp_path / "queue.json"
    delta = tmp_path / "delta.json"
    output = tmp_path / "final.json"
    _write(baseline, {"decisions": [_decision("sv_regen", "needs_regenerate"), _decision("sv_ok", "approved")]})
    _write(queue_meta, {"incremental_review_queue": {"queue_ids": ["sv_regen", "sv_ok"], "input_sha256": {"baseline_decisions": merge._sha256(baseline)}}})
    _write(delta, {"decision_mode": "incremental_delta", "decisions": [{**_decision("sv_regen", "approved"), "reviewer_notes": "regenerated media reviewed"}]})

    summary = merge.merge_incremental_review_decisions(baseline, delta, queue_meta, output)
    assert summary == {"total": 2, "replaced": 1}
    merged = json.loads(output.read_text(encoding="utf-8"))["decisions"]
    assert merged[0]["status"] == "approved"

    _write(delta, {"decision_mode": "incremental_delta", "decisions": [{**_decision("sv_ok", "dropped"), "reviewer_notes": "confirmed unusable"}]})
    with pytest.raises(ValueError, match="不允许覆盖历史 approved"):
        merge.merge_incremental_review_decisions(baseline, delta, queue_meta, output)


def test_incremental_ui_keeps_only_queue_delta_records(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(app.st, "session_state", {})
    output = tmp_path / "delta.json"
    _write(output, {"decision_mode": "incremental_delta", "decisions": [_decision("not_in_queue", "approved")]})
    sub = _subvideo("sv_queue")
    sub["incremental_review"] = {"baseline_decision": _decision("sv_queue", "needs_regenerate")}

    decisions = app._init_decisions([sub], output, incremental_delta=True)

    assert list(decisions) == ["sv_queue"]
    assert decisions["sv_queue"]["baseline_decision"]["status"] == "needs_regenerate"


def test_materializer_matches_adaptive_candidate_after_duration_rename():
    old = {"subvideo_id": "video_0001_focus_2.00s_50pct_adaptive", "crop_type": "focus_adaptive", "event_position_ratio": 0.5}
    candidate = {"subvideo_id": "video_0001_focus_3.00s_50pct_adaptive", "crop_type": "focus_adaptive", "event_position_ratio": 0.5}

    assert materialize._match_candidate(old, [candidate]) == candidate


def test_append_failure_drops_only_allows_baseline_regenerate(tmp_path: Path):
    baseline = tmp_path / "baseline.json"
    queue_meta = tmp_path / "queue.json"
    delta = tmp_path / "delta.json"
    report = tmp_path / "report.json"
    output = tmp_path / "resolved_delta.json"
    _write(baseline, {"decisions": [_decision("sv_regen", "needs_regenerate")]})
    _write(queue_meta, {"incremental_review_queue": {"queue_ids": ["sv_regen"]}})
    _write(delta, {"decision_mode": "incremental_delta", "queue_ids": [], "decisions": []})
    _write(report, {"failures": [{"subvideo_id": "sv_regen", "reason": "no_matching_candidate_after_source_update"}]})

    summary = failure_drops.append_failure_drops(baseline, delta, queue_meta, report, output, "operator decision")

    assert summary == {"total": 1, "added_dropped": 1}
    result = json.loads(output.read_text(encoding="utf-8"))
    record = result["decisions"][0]
    assert record["status"] == "dropped"
    assert "operator decision" in record["reviewer_notes"]
    assert result["reviewed_ids"] == []
    assert result["unreviewed_ids"] == []
    assert result["failure_drop_append"]["failure_dropped_ids"] == ["sv_regen"]
