from __future__ import annotations

import json
from pathlib import Path

import pytest

from finetune.validation.aggregate_folds import aggregate_fold_results
from finetune.validation.run_evaluation import evaluate_sample, summarize
from finetune.validation.datasets import EvalSample


# ground_truth 必须带合法区间：若目标与预测两侧的 fracture_between 同时缺失，
# 该类样本在新判分语义下不计 joint 正确（2026-10-18 修复），无法作为正样本使用。
def _record(name: str, correct: bool) -> dict:
    sample = EvalSample(
        sample_id=name,
        video_id=name,
        video_path=Path(f"/tmp/{name}.mp4"),
        metadata={
            "ground_truth": {
                "has_fracture": True,
                "fracture_between": [1, 2],
                "type": "韧性断裂",
                "location": "inside_gauge",
            }
        },
    )
    raw = (
        '{"has_fracture":true,"fracture_between":[1,2],"type":"韧性断裂","location":"inside_gauge"}'
        if correct
        else '{"has_fracture":false,"fracture_between":null,"type":"未断裂","location":null}'
    )
    return evaluate_sample(sample, raw)


def _write_fold(directory: Path, fold: int, records: list[dict], release: str = "release-1") -> None:
    directory.mkdir()
    summary = {
        "active_release_id": release,
        "dataset": f"fold_{fold}_val",
        "model_dir": f"/models/fold{fold}",
        "system_prompt_hash": "prompt-hash",
        "metrics": summarize(records),
    }
    (directory / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False),
        encoding="utf-8",
    )
    (directory / "evaluation_records.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_aggregate_fold_results_reports_macro_and_pooled_metrics(tmp_path):
    folds = {}
    for fold, correct in enumerate((True, True, False)):
        directory = tmp_path / f"fold{fold}"
        _write_fold(directory, fold, [_record(f"sample-{fold}", correct)])
        folds[f"fold{fold}"] = directory

    result = aggregate_fold_results(folds)

    assert result["active_release_id"] == "release-1"
    assert result["fold_count"] == 3
    assert result["total_records"] == 3
    assert result["macro_task_metrics"]["has_fracture_accuracy"] == {
        "folds_scored": 3,
        "mean": 0.666667,
        "pstdev": 0.471405,
    }
    assert result["pooled_metrics"]["task_metrics"]["joint_success_rate"] == 0.666667


def test_aggregate_fold_results_rejects_release_mismatch(tmp_path):
    folds = {}
    for fold in range(3):
        directory = tmp_path / f"fold{fold}"
        _write_fold(
            directory,
            fold,
            [_record(f"sample-{fold}", True)],
            release=f"release-{fold}",
        )
        folds[f"fold{fold}"] = directory

    with pytest.raises(ValueError, match="active_release_id"):
        aggregate_fold_results(folds)
