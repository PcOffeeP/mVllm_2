from __future__ import annotations

import json
import sys

from finetune.validation.datasets import EvalSample
from finetune.validation.run_evaluation import evaluate_sample, main
from finetune.validation.schema import parse_model_output, unavailable


def test_schema_accepts_only_the_five_field_protocol():
    result = parse_model_output(
        json.dumps(
            {
                "has_fracture": True,
                "fracture_between": [1, 2],
                "type": "脆性断裂",
                "location": "outside_gauge",
                "confidence": 0.9,
            },
            ensure_ascii=False,
        )
    )

    assert result.format_valid is True
    assert result.payload["type"] == "脆性断裂"

    invalid = parse_model_output(
        json.dumps(
            {
                "has_fracture": True,
                "fracture_between": [1, 3],
                "type": "脆性断裂",
                "location": "试样中部",
                "confidence": 1.2,
                "extra": "not allowed",
            },
            ensure_ascii=False,
        )
    )

    assert invalid.json_valid is True
    assert invalid.schema_valid is False
    assert any("extra fields" in error for error in invalid.errors)
    assert any("fracture_between" in error for error in invalid.errors)


def test_evaluate_sample_reports_format_and_field_correctness():
    sample = EvalSample(
        sample_id="sample_1",
        video_id="sample_1",
        video_path="/tmp/sample_1.mp4",
        target={
            "has_fracture": True,
            "fracture_between": [1, 2],
            "type": "脆性断裂",
            "location": "outside_gauge",
            "confidence": unavailable(),
        },
        metadata={},
    )

    record = evaluate_sample(
        sample,
        json.dumps(
            {
                "has_fracture": True,
                "fracture_between": [1, 2],
                "type": "韧性断裂",
                "location": "outside_gauge",
                "confidence": 0.8,
            },
            ensure_ascii=False,
        ),
    )

    assert record["format_valid"] is True
    assert record["field_results"]["has_fracture"]["correct"] is True
    assert record["field_results"]["type"]["correct"] is False
    assert record["field_results"]["confidence"]["expected"] == "number in [0, 1]"
    assert record["prediction_correct"] is False


def test_run_evaluation_prediction_file_mode(tmp_path, monkeypatch):
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "video_id": "video_0005_full",
                        "raw_output": json.dumps(
                            {
                                "has_fracture": None,
                                "fracture_between": None,
                                "type": "视频异常",
                                "location": None,
                                "confidence": 0.7,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "video_id": "video_0008_full",
                        "raw_output": json.dumps(
                            {
                                "has_fracture": True,
                                "fracture_between": [6, 7],
                                "type": "脆性断裂",
                                "location": "outside_gauge",
                                "confidence": 0.9,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "eval"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evaluation",
            "--dataset",
            "test_subvideos",
            "--predictions",
            str(predictions),
            "--prompt",
            "training",
            "--out-dir",
            str(out_dir),
            "--max-samples",
            "2",
        ],
    )

    main()

    summary = json.loads((out_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["total_samples"] == 2
    assert summary["metrics"]["format_valid_rate"] == 1.0
    assert summary["metrics"]["prediction_correct_rate"] == 1.0
    assert (out_dir / "evaluation_records.jsonl").exists()
    assert (out_dir / "failures.csv").exists()
