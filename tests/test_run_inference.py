from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VALIDATION_DIR = ROOT / "finetune" / "validation"
sys.path.insert(0, str(VALIDATION_DIR))
sys.path.insert(0, str(ROOT))

import run_inference
from run_inference import _parse_confidence, _parse_pred_time_range


def test_parse_pred_time_range_rejects_nan_and_inf():
    assert _parse_pred_time_range({"time_range": [float("nan"), 10.0]}, 10.0) == [9.5, 10.5]
    assert _parse_pred_time_range({"time_range_sec": [0.0, float("inf")]}, 10.0) == [9.5, 10.5]
    assert _parse_pred_time_range({"time_interval": [float("-inf"), 5.0]}, 10.0) == [9.5, 10.5]
    assert _parse_pred_time_range({"time_range": [5.0, 15.0]}, 10.0) == [5.0, 15.0]
    assert _parse_pred_time_range({"time_range": [float("nan"), 1.0]}, None) is None


def test_parse_confidence_rejects_nan_and_inf():
    assert _parse_confidence({"confidence_score": float("nan")}) == (0.5, "中")
    assert _parse_confidence({"confidence_score": float("inf")}) == (0.5, "中")
    assert _parse_confidence({"confidence_score": float("-inf")}) == (0.5, "中")
    assert _parse_confidence({"confidence_score": "not-a-number"}) == (0.5, "中")
    assert _parse_confidence({"confidence_score": 0.85}) == (0.85, "高")
    assert _parse_confidence({"confidence_score": 1.5}) == (1.0, "高")
    assert _parse_confidence({"confidence_score": -0.3}) == (0.0, "低")
    assert _parse_confidence({"confidence_level": "低"}) == (0.3, "低")
    assert _parse_confidence({}) == (0.5, "中")
    assert _parse_confidence(None) == (0.5, "中")


def test_parse_confidence_output_is_json_serializable():
    score, level = _parse_confidence({"confidence_score": float("nan")})
    record = {"pred_confidence_score": score, "pred_confidence_level": level}
    dumped = json.dumps(record, allow_nan=False)
    parsed = json.loads(dumped)
    assert math.isfinite(parsed["pred_confidence_score"])


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
