from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
VALIDATION_DIR = ROOT / "finetune" / "validation"
sys.path.insert(0, str(VALIDATION_DIR))
sys.path.insert(0, str(ROOT))

import run_inference
from run_inference import VIDEO_MAX_FRAMES, _parse_confidence, _parse_pred_time_range


# ---------------------------------------------------------------------------
# _parse_pred_time_range
# ---------------------------------------------------------------------------

def test_parse_pred_time_range_new_protocol_positive():
    """New-protocol interval [17, 18] maps to seconds under uniform sampling."""
    payload = {"has_fracture": True, "fracture_between": [17, 18]}
    duration = 500.0
    result = _parse_pred_time_range(payload, duration_sec=duration, max_num_frames=36)
    # step = 500 / 35 = 14.285714...
    assert result == [pytest.approx(242.857143, abs=1e-6), pytest.approx(257.142857, abs=1e-6)]


def test_parse_pred_time_range_new_protocol_negative():
    """Negative sample with has_fracture=false yields no time range."""
    payload = {"has_fracture": False, "fracture_between": None}
    assert _parse_pred_time_range(payload, duration_sec=500.0) is None


def test_parse_pred_time_range_old_protocol_compatibility():
    """Legacy interval fields are still parsed when new protocol is absent."""
    assert _parse_pred_time_range({"time_range": [5.0, 15.0]}) == [5.0, 15.0]
    assert _parse_pred_time_range({"time_range_sec": [6.0, 16.0]}) == [6.0, 16.0]
    assert _parse_pred_time_range({"time_interval": [7.0, 17.0]}) == [7.0, 17.0]


def test_parse_pred_time_range_boundary_sentinels():
    """Left and right boundary sentinels produce zero-width intervals."""
    duration = 100.0
    max_frames = 11  # step = 100 / 10 = 10.0
    assert _parse_pred_time_range(
        {"has_fracture": True, "fracture_between": [0, 0]},
        duration_sec=duration,
        max_num_frames=max_frames,
    ) == [0.0, 0.0]
    assert _parse_pred_time_range(
        {"has_fracture": True, "fracture_between": [max_frames - 1, max_frames - 1]},
        duration_sec=duration,
        max_num_frames=max_frames,
    ) == [duration, duration]


def test_parse_pred_time_range_rejects_invalid_fracture_between():
    """Invalid indices fall back to legacy fields or None."""
    duration = 100.0
    # Out of bounds.
    assert _parse_pred_time_range(
        {"has_fracture": True, "fracture_between": [VIDEO_MAX_FRAMES, VIDEO_MAX_FRAMES + 1]},
        duration_sec=duration,
    ) is None
    # Wrong spacing (not adjacent and not sentinel).
    assert _parse_pred_time_range(
        {"has_fracture": True, "fracture_between": [1, 3]},
        duration_sec=duration,
    ) is None
    # Wrong length.
    assert _parse_pred_time_range(
        {"has_fracture": True, "fracture_between": [1]},
        duration_sec=duration,
    ) is None


def test_parse_pred_time_range_rejects_nan_and_inf():
    """Non-finite legacy range endpoints are rejected; no ±0.5s placeholder."""
    assert _parse_pred_time_range({"time_range": [float("nan"), 10.0]}) is None
    assert _parse_pred_time_range({"time_range_sec": [0.0, float("inf")]}) is None
    assert _parse_pred_time_range({"time_interval": [float("-inf"), 5.0]}) is None
    assert _parse_pred_time_range({"time_range": [5.0, 15.0]}) == [5.0, 15.0]
    assert _parse_pred_time_range({"time_range": [float("nan"), 1.0]}) is None


def test_parse_pred_time_range_rejects_non_boundary_zero_width():
    """A zero-width interval [k, k] is only accepted at the boundaries."""
    duration = 100.0
    max_frames = 11
    # Non-boundary zero-width must be rejected.
    assert _parse_pred_time_range(
        {"has_fracture": True, "fracture_between": [3, 3]},
        duration_sec=duration,
        max_num_frames=max_frames,
    ) is None
    # Adjacent frames remain valid.
    assert _parse_pred_time_range(
        {"has_fracture": True, "fracture_between": [3, 4]},
        duration_sec=duration,
        max_num_frames=max_frames,
    ) == [30.0, 40.0]


def test_parse_pred_time_range_rejects_missing_fracture_between():
    """New protocol with has_fracture=True but no fracture_between returns None."""
    assert _parse_pred_time_range(
        {"has_fracture": True},
        duration_sec=500.0,
    ) is None
    assert _parse_pred_time_range(
        {"has_fracture": True, "fracture_between": None},
        duration_sec=500.0,
    ) is None


def test_parse_pred_time_range_new_protocol_requires_duration():
    """New protocol intervals require a valid duration; None yields None."""
    payload = {"has_fracture": True, "fracture_between": [0, 1]}
    assert _parse_pred_time_range(payload, duration_sec=None) is None


# ---------------------------------------------------------------------------
# _parse_confidence
# ---------------------------------------------------------------------------

def test_parse_confidence_rejects_nan_and_inf(caplog: pytest.LogCaptureFixture):
    """NaN/inf confidence values trigger a warning and fall back to 0.5."""
    with caplog.at_level("WARNING", logger="run_inference"):
        assert _parse_confidence({"confidence_score": float("nan")}) == (0.5, "低")
        assert _parse_confidence({"confidence_score": float("inf")}) == (0.5, "低")
        assert _parse_confidence({"confidence_score": float("-inf")}) == (0.5, "低")
    assert sum("not finite" in rec.message for rec in caplog.records) == 3


def test_parse_confidence_out_of_bounds_triggers_warning(caplog: pytest.LogCaptureFixture):
    """Finite out-of-range confidence values are clipped with a warning."""
    with caplog.at_level("WARNING", logger="run_inference"):
        assert _parse_confidence({"confidence": 1.5}) == (1.0, "高")
        assert _parse_confidence({"confidence": -0.3}) == (0.0, "不可信")
    assert sum("out of [0, 1]" in rec.message for rec in caplog.records) == 2


def test_parse_confidence_four_level_mapping():
    """Four-level confidence grading matches the contract boundaries."""
    assert _parse_confidence({"confidence": 0.95}) == (0.95, "高")
    assert _parse_confidence({"confidence": 0.90}) == (0.9, "高")
    assert _parse_confidence({"confidence": 0.85}) == (0.85, "中")
    assert _parse_confidence({"confidence": 0.70}) == (0.7, "中")
    assert _parse_confidence({"confidence": 0.60}) == (0.6, "低")
    assert _parse_confidence({"confidence": 0.50}) == (0.5, "低")
    assert _parse_confidence({"confidence": 0.49}) == (0.49, "不可信")
    assert _parse_confidence({"confidence": 0.0}) == (0.0, "不可信")


def test_parse_confidence_new_protocol_priority():
    """New protocol ``confidence`` key is preferred over legacy fields."""
    assert _parse_confidence({"confidence": 0.92, "confidence_score": 0.3}) == (0.92, "高")


def test_parse_confidence_string_fallback():
    """Legacy string confidence levels map to canonical scores and graded."""
    assert _parse_confidence({"confidence_level": "高"}) == (0.9, "高")
    assert _parse_confidence({"confidence_level": "中"}) == (0.6, "低")
    assert _parse_confidence({"confidence_level": "低"}) == (0.3, "不可信")
    assert _parse_confidence({"confidence_level": "不可信"}) == (0.25, "不可信")


def test_parse_confidence_unparseable_string_falls_back():
    """Unparseable string values fall back silently to the default score."""
    assert _parse_confidence({"confidence_score": "not-a-number"}) == (0.5, "低")


def test_parse_confidence_output_is_json_serializable():
    score, level = _parse_confidence({"confidence_score": float("nan")})
    record = {"pred_confidence_score": score, "pred_confidence_level": level}
    dumped = json.dumps(record, allow_nan=False)
    parsed = json.loads(dumped)
    assert math.isfinite(parsed["pred_confidence_score"])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_writes_jsonl_with_allow_nan_false(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import json as json_module

    captured_kwargs: dict[str, Any] = {}
    original_dumps = json_module.dumps

    def capturing_dumps(obj: Any, **kwargs: Any) -> str:
        captured_kwargs["kwargs"] = kwargs
        return original_dumps(obj, **kwargs)

    monkeypatch.setattr(json_module, "dumps", capturing_dumps)

    sample = {
        "video_id": "v001",
        "video_name": "v001.mp4",
        "gt_time_sec": 10.0,
        "gt_type": "韧性断裂",
        "time_available": True,
        "material": None,
        "clarity": None,
    }

    monkeypatch.setattr(run_inference, "load_ground_truth", lambda path: {sample["video_name"]: sample})
    monkeypatch.setattr(run_inference, "load_fold_samples", lambda fold, gt_map: [sample])
    monkeypatch.setattr(run_inference, "load_model", lambda model_dir: (None, None))
    monkeypatch.setattr(
        run_inference,
        "run_single_inference",
        lambda model, processor, video_path, prompt: '{"time": "10.0s", "type": "韧性断裂"}',
    )

    (tmp_path / "v001.mp4").write_text("fake", encoding="utf-8")
    output_path = tmp_path / "out.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_inference",
            "--task",
            "time",
            "--fold",
            "0",
            "--output",
            str(output_path),
            "--video-root",
            str(tmp_path),
            "--model-dir",
            str(tmp_path / "model"),
        ],
    )

    run_inference.main()
    assert captured_kwargs["kwargs"].get("allow_nan") is False
    assert output_path.exists()
    lines = [line for line in output_path.read_text(encoding="utf-8").strip().split("\n") if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["video_id"] == "v001"
    assert math.isfinite(record["pred_confidence_score"])
    assert record["pred_has_fracture"] is True
    assert record["pred_location"] is None


def test_main_new_protocol_records_has_fracture_and_location(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    sample = {
        "video_id": "v002",
        "video_name": "v002.mp4",
        "gt_time_sec": 250.0,
        "gt_type": "韧性断裂",
        "time_available": True,
        "material": None,
        "clarity": None,
    }

    monkeypatch.setattr(run_inference, "load_ground_truth", lambda path: {sample["video_name"]: sample})
    monkeypatch.setattr(run_inference, "load_fold_samples", lambda fold, gt_map: [sample])
    monkeypatch.setattr(run_inference, "load_model", lambda model_dir: (None, None))
    monkeypatch.setattr(
        run_inference,
        "run_single_inference",
        lambda model, processor, video_path, prompt: (
            '{"has_fracture": true, "fracture_between": [17, 18], '
            '"type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92}'
        ),
    )
    monkeypatch.setattr(run_inference, "_get_video_duration", lambda video_path: 500.0)

    (tmp_path / "v002.mp4").write_text("fake", encoding="utf-8")
    output_path = tmp_path / "out.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_inference",
            "--task",
            "joint",
            "--fold",
            "0",
            "--output",
            str(output_path),
            "--video-root",
            str(tmp_path),
            "--model-dir",
            str(tmp_path / "model"),
        ],
    )

    run_inference.main()
    assert output_path.exists()
    lines = [line for line in output_path.read_text(encoding="utf-8").strip().split("\n") if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["pred_has_fracture"] is True
    assert record["pred_location"] == "inside_gauge"
    assert record["pred_confidence_level"] == "高"
    assert record["pred_time_range"] is not None


def test_main_old_protocol_non_fracture_type(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Old-protocol payload with type=未断裂 should set pred_has_fracture=False."""
    sample = {
        "video_id": "v003",
        "video_name": "v003.mp4",
        "gt_time_sec": 10.0,
        "gt_type": "未断裂",
        "time_available": True,
        "material": None,
        "clarity": None,
    }

    monkeypatch.setattr(run_inference, "load_ground_truth", lambda path: {sample["video_name"]: sample})
    monkeypatch.setattr(run_inference, "load_fold_samples", lambda fold, gt_map: [sample])
    monkeypatch.setattr(run_inference, "load_model", lambda model_dir: (None, None))
    monkeypatch.setattr(
        run_inference,
        "run_single_inference",
        lambda model, processor, video_path, prompt: '{"time": "10.0s", "type": "未断裂"}',
    )

    (tmp_path / "v003.mp4").write_text("fake", encoding="utf-8")
    output_path = tmp_path / "out.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_inference",
            "--task",
            "time",
            "--fold",
            "0",
            "--output",
            str(output_path),
            "--video-root",
            str(tmp_path),
            "--model-dir",
            str(tmp_path / "model"),
        ],
    )

    run_inference.main()
    assert output_path.exists()
    lines = [line for line in output_path.read_text(encoding="utf-8").strip().split("\n") if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["pred_has_fracture"] is False
    assert record["pred_location"] is None
