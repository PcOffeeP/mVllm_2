from __future__ import annotations

import json
from pathlib import Path

from finetune.archive.freeze_v4_1_evidence import _invalid_analysis, _summarize_records


def _record(
    candidate_id: str,
    target: str,
    predicted: str | None,
    *,
    raw_output: str = "",
    parse_error: str | None = None,
) -> dict[str, object]:
    prediction = (
        {
            "clip_state": predicted,
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": None,
        }
        if predicted is not None
        else None
    )
    return {
        "candidate_id": candidate_id,
        "source_video": candidate_id.split("_candidate")[0],
        "target": {
            "clip_state": target,
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": None,
        },
        "prediction": prediction,
        "strict_valid": prediction is not None,
        "runtime_error": None,
        "parse_error": parse_error,
        "raw_output": raw_output,
        "generated_token_count": 12,
        "hit_token_limit": False,
    }


def test_summarizes_fold0_macro_recall() -> None:
    records = [
        _record("video_0001_candidate1", "未断裂", "未断裂"),
        _record("video_0002_candidate1", "临界未断裂", "临界未断裂"),
        _record("video_0003_candidate1", "发生断裂", "未断裂"),
        _record("video_0004_candidate1", "已断裂", None),
    ]

    summary = _summarize_records(records)

    assert summary["sample_count"] == 4
    assert summary["strict_invalid_count"] == 1
    assert summary["fracture_three_state_macro_recall"] == 0.333333
    assert summary["four_observed_state_macro_recall"] == 0.5
    assert summary["clip_state_class_metrics"]["已断裂"]["recall"] == 0.0
    assert summary["target_special_case_distribution"] == {"None": 4}


def test_attributes_missing_special_case_without_auto_repair() -> None:
    invalid = _record(
        "video_0001_candidate1",
        "临界未断裂",
        None,
        raw_output=(
            '{"clip_state":"临界未断裂","fracture_mechanism":"韧性断裂",'
            '"fracture_site":"inside_gauge"}'
        ),
        parse_error="special_case: 缺少字段",
    )

    analysis = _invalid_analysis([invalid])

    assert analysis["strict_invalid_count"] == 1
    assert analysis["missing_special_case_field_count"] == 1
    assert analysis["hit_token_limit_count"] == 0
    assert analysis["runtime_failure_count"] == 0
    assert "Do not auto-fill" in analysis["policy"]


def test_json_reports_remain_utf8_serializable(tmp_path: Path) -> None:
    report = _summarize_records(
        [_record("video_0001_candidate1", "发生断裂", "发生断裂")]
    )
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert json.loads(path.read_text(encoding="utf-8")) == report
