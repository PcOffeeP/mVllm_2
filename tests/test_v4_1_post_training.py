from __future__ import annotations

import json

from finetune.run_v4_1_post_training import Fold, _evaluation_complete
from finetune.run_v4_1_visual_three_fold import (
    Fold as VisualFold,
    _evaluation_complete as visual_evaluation_complete,
)


def _write_result(fold: Fold, *, runtime_failures: int) -> None:
    fold.result_dir.mkdir(parents=True)
    (fold.result_dir / "evaluation_summary.json").write_text(
        json.dumps(
            {
                "sample_count": 1,
                "total_samples": 1,
                "runtime_failure_count": runtime_failures,
            }
        ),
        encoding="utf-8",
    )
    (fold.result_dir / "evaluation_records.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (fold.result_dir / "runtime_failures.csv").write_text(
        "candidate_id,video_path,runtime_error\n",
        encoding="utf-8",
    )


def test_evaluation_complete_rejects_runtime_failures(
    tmp_path,
    monkeypatch,
) -> None:
    fold = Fold(0)
    monkeypatch.setattr(
        Fold,
        "result_dir",
        property(lambda self: tmp_path / f"fold{self.index}"),
    )
    _write_result(fold, runtime_failures=1)

    assert _evaluation_complete(fold) is False


def test_evaluation_complete_accepts_matching_success(
    tmp_path,
    monkeypatch,
) -> None:
    fold = Fold(0)
    monkeypatch.setattr(
        Fold,
        "result_dir",
        property(lambda self: tmp_path / f"fold{self.index}"),
    )
    _write_result(fold, runtime_failures=0)

    assert _evaluation_complete(fold) is True


def test_visual_evaluation_complete_uses_per_fold_count(
    tmp_path,
    monkeypatch,
) -> None:
    fold = VisualFold(1)
    result_dir = tmp_path / "fold1"
    result_dir.mkdir()
    (result_dir / "evaluation_summary.json").write_text(
        json.dumps(
            {
                "sample_count": 445,
                "total_samples": 445,
                "runtime_failure_count": 0,
            }
        ),
        encoding="utf-8",
    )
    (result_dir / "evaluation_records.jsonl").write_text(
        "{}\n" * 445,
        encoding="utf-8",
    )
    (result_dir / "runtime_failures.csv").write_text(
        "candidate_id,video_path,runtime_error\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        VisualFold,
        "result_dir",
        property(lambda self: result_dir),
    )

    assert visual_evaluation_complete(fold) is True
