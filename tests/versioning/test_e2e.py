"""数据 CLI 生命周期及拒绝合成训练；实际模型闭环见 test_eval_run。"""

from __future__ import annotations

from pathlib import Path

import yaml

from test_data_pipeline import (
    pinned_inputs, source_inputs, roi_inputs, media_inputs, media_runtime,
    _review_return, _source_probe,
)
from versioning.cli import main


def _run(*args: str) -> None:
    assert main(list(args)) == 0


def _yaml(path: Path, value: object) -> Path:
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")
    return path


def test_data_cli_lifecycle_cannot_create_synthetic_training(tmp_path: Path, media_inputs, media_runtime, monkeypatch) -> None:
    from pipeline import source_bootstrap
    monkeypatch.setattr(source_bootstrap, 'probe_video', _source_probe)
    inputs, _, root, _ = media_inputs
    store = root / "workspace" / "mlflow"
    batch = "batch-001"
    common = ("--root", str(root), "--batch", batch, "--inputs", str(inputs))
    for stage in ("source", "roi", "subvideo", "review_export"):
        _run("data", stage, *common)
    review = tmp_path / 'review.json'
    _review_return(root / 'data/working' / batch / 'review_export', review)
    _run("data", "review_import", *common, "--results", str(review))
    _run("data", "release", *common, "--version", "data-v4.1-r1")
    _run("data", "release_validate", *common, "--version", "data-v4.1-r1")

    definition = _yaml(
        root / "prompt.yaml",
        {
            "system_prompt": "Inspect the material.",
            "user_prompt": "Classify this clip.",
            "output_fields": ["state"],
        },
    )
    _run(
        "prompt",
        "create",
        "--root",
        str(root),
        "--version",
        "prompt-v4.1-r1",
        "--protocol",
        "v4.1",
        "--definition",
        str(definition),
    )
    _run(
        "prompt",
        "freeze",
        "--root",
        str(root),
        "--version",
        "prompt-v4.1-r1",
        "--train-version",
        "train-v4.1-r1",
    )

    # A data/Prompt publication is not training evidence. The former synthetic
    # completed/passed chain must stop before creating any training store.
    assert main(["train", "create", "train-v4.1-r1", "--root", str(root),
        "--data-version", "data-v4.1-r1", "--prompt-version", "prompt-v4.1-r1",
        "--git-commit", "fixture", "--base-model", "missing", "--config", "missing.yaml"]) == 2
    assert not store.exists()
