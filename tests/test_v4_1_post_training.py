from __future__ import annotations

import json

from finetune.run_v4_1_post_training import Fold, _evaluation_complete


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
