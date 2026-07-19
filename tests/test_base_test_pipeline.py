from __future__ import annotations

import json
from pathlib import Path

from finetune import run_base_test_pipeline as pipeline


def _write_result(
    path: Path,
    target: pipeline.EvaluationTarget,
    model_dir: Path,
    *,
    prompt_version: str = "v2.1.0",
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "evaluation_summary.json").write_text(
        json.dumps(
            {
                "active_release_id": pipeline.RELEASE_ID,
                "dataset": target.dataset,
                "model_dir": str(model_dir),
                "prompt_version": prompt_version,
                "metrics": {"total_samples": target.expected_samples},
            }
        ),
        encoding="utf-8",
    )
    (path / "evaluation_records.jsonl").write_text("{}\n", encoding="utf-8")
    (path / "runtime_failures.csv").write_text(
        "video_id,runtime_error,video_path\n",
        encoding="utf-8",
    )


def test_model_complete_requires_all_ten_shards(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "weight_map": {
                    f"layer.{index}": f"model-{index:05d}-of-00010.safetensors"
                    for index in range(1, 11)
                }
            }
        ),
        encoding="utf-8",
    )
    for index in range(1, 10):
        (model / f"model-{index:05d}-of-00010.safetensors").touch()

    assert pipeline._model_complete(model) is False

    (model / "model-00010-of-00010.safetensors").touch()
    assert pipeline._model_complete(model) is True


def test_publish_result_replaces_only_required_files(tmp_path: Path) -> None:
    target = pipeline.EvaluationTarget(
        dataset="test",
        expected_samples=21,
        result_dir=tmp_path / "published",
    )
    staging = tmp_path / "staging"
    _write_result(staging, target, tmp_path / "model")
    target.result_dir.mkdir()
    (target.result_dir / "keep.txt").write_text("keep", encoding="utf-8")

    original_staging_root = pipeline.STAGING_ROOT
    try:
        pipeline.STAGING_ROOT = tmp_path
        target = pipeline.EvaluationTarget(
            dataset="staging",
            expected_samples=21,
            result_dir=target.result_dir,
        )
        pipeline._publish_result(target)
    finally:
        pipeline.STAGING_ROOT = original_staging_root

    assert (target.result_dir / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert all(
        (target.result_dir / name).is_file()
        for name in pipeline.REQUIRED_RESULT_FILES
    )
    assert not list(target.result_dir.glob("*.tmp"))


def test_current_result_requires_current_prompt_and_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model = tmp_path / "model"
    target = pipeline.EvaluationTarget(
        dataset="test",
        expected_samples=21,
        result_dir=tmp_path / "result",
    )
    monkeypatch.setattr(pipeline, "BASE_MODEL_DIR", model)
    _write_result(target.result_dir, target, model)

    assert pipeline._current_result_complete(target) is True

    _write_result(target.result_dir, target, model, prompt_version="old")
    assert pipeline._current_result_complete(target) is False
