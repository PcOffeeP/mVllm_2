"""B10 临时环境中的完整可读版本血缘闭环。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from mlflow.tracking import MlflowClient

from versioning.backup import verify_backup
from versioning.cli import main
from versioning.manifest import validate_manifest
from versioning.mlflow_train import get_train_run, open_train_store
from versioning.registry import get_model_by_alias, open_registry_store


def _run(*args: str) -> None:
    assert main(list(args)) == 0


def _yaml(path: Path, value: object) -> Path:
    path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")
    return path


def test_full_fixture_lifecycle_through_unified_cli(tmp_path: Path) -> None:
    root = tmp_path / "project"
    store = root / "workspace" / "mlflow"
    batch = "batch-e2e"
    raw = root / "data" / "raw" / batch
    raw.mkdir(parents=True)
    (raw / "sample.mp4").write_bytes(b"fixture-video")

    common = ("--root", str(root), "--batch", batch)
    for stage in ("source", "roi", "subvideo", "review_export"):
        _run("data", stage, *common)

    subvideo_path = (
        root / "data" / "working" / batch / "subvideo" / "subvideo_manifest.json"
    )
    subvideo = json.loads(subvideo_path.read_text(encoding="utf-8"))
    review = _yaml(
        root / "review.yaml",
        {
            "batch": batch,
            "approved": True,
            "content_sha256": hashlib.sha256(subvideo_path.read_bytes()).hexdigest(),
            "decisions": [
                {"clip_id": item["clip_id"], "verdict": "accept"}
                for item in subvideo["clips"]
            ],
        },
    )
    _run("data", "review_import", *common, "--results", str(review))
    _run(
        "data",
        "release",
        *common,
        "--version",
        "data-v4.1-r1",
        "--protocol",
        "v4.1",
    )
    _run("data", "release_validate", "--root", str(root), "--version", "data-v4.1-r1")

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

    config = _yaml(root / "train-config.yaml", {"epochs": 1})
    metrics = _yaml(root / "metrics.yaml", {"score": 1.0})
    train_base = (
        "--root",
        str(root),
        "--store",
        str(store),
    )
    _run(
        "train",
        "create",
        "train-v4.1-r1",
        *train_base,
        "--data-version",
        "data-v4.1-r1",
        "--prompt-version",
        "prompt-v4.1-r1",
        "--git-commit",
        "fixture-commit",
        "--base-model",
        "fixture-base",
        "--config",
        str(config),
    )
    for fold in range(3):
        _run("train", "fold-start", "train-v4.1-r1", *train_base, "--fold", str(fold))
        _run(
            "train",
            "fold-end",
            "train-v4.1-r1",
            *train_base,
            "--fold",
            str(fold),
            "--metrics",
            str(metrics),
        )
    _run("train", "summary", "train-v4.1-r1", *train_base, "--metrics", str(metrics))
    _run("train", "complete", "train-v4.1-r1", *train_base)
    adapter = root / "adapter.bin"
    merged = root / "model.bin"
    adapter.write_bytes(b"fixture-adapter")
    merged.write_bytes(b"fixture-merged")
    train_store = open_train_store(store)
    train_record = get_train_run(train_store, "train-v4.1-r1")
    artifact_client = MlflowClient(tracking_uri=train_store.tracking_uri)
    artifact_client.log_artifact(
        train_record.run_id, str(adapter), artifact_path="fold0/adapter"
    )
    artifact_client.log_artifact(
        train_record.run_id, str(merged), artifact_path="fold0/merged"
    )

    model_artifacts = _yaml(
        root / "model-artifacts.yaml",
        {
            "fold0": {
                "adapter": "artifacts/fold0/adapter",
                "merged": "artifacts/fold0/merged",
            }
        },
    )

    model_base = ("--root", str(root), "--store", str(store))
    _run(
        "model",
        "register",
        "model-v4.1-r1",
        *model_base,
        "--train-version",
        "train-v4.1-r1",
        "--source-scope",
        "single_fold",
        "--artifacts",
        str(model_artifacts),
        "--deploy-target",
        "artifacts/fold0/merged",
    )
    bad_artifacts = _yaml(
        root / "bad-model-artifacts.yaml",
        {"fold0": {"merged": "."}},
    )
    assert main([
        "model", "register", "model-v4.1-r2", *model_base,
        "--train-version", "train-v4.1-r1",
        "--source-scope", "single_fold",
        "--artifacts", str(bad_artifacts),
        "--deploy-target", ".",
    ]) == 1
    assert len(MlflowClient(tracking_uri=train_store.tracking_uri).search_model_versions(
        "name='mVllm2'"
    )) == 1

    eval_base = ("--root", str(root), "--store", str(store))
    _run(
        "eval",
        "create",
        "eval-v4.1-r1",
        *eval_base,
        "--model-version",
        "model-v4.1-r1",
        "--model-version-number",
        "1",
        "--data-version",
        "data-v4.1-r1",
        "--config",
        "eval.yaml",
        "--git-commit",
        "fixture-commit",
        "--scope",
        "single_fold",
        "--split",
        "validation/fold0",
    )
    for fold in (0,):
        _run(
            "eval",
            "fold-start",
            "eval-v4.1-r1",
            *eval_base,
            "--fold",
            str(fold),
            "--model-artifact",
            f"artifacts/fold{fold}",
            "--data-split",
            f"fold{fold}",
            "--sample-count",
            "1",
            "--records",
            f"records/fold{fold}.jsonl",
            "--failures",
            f"failures/fold{fold}.jsonl",
        )
        _run(
            "eval",
            "fold-end",
            "eval-v4.1-r1",
            *eval_base,
            "--fold",
            str(fold),
            "--metrics",
            str(metrics),
        )
    _run("eval", "summary", "eval-v4.1-r1", *eval_base, "--metrics", str(metrics))
    _run("eval", "complete", "eval-v4.1-r1", *eval_base, "--outcome", "passed")

    _run(
        "model",
        "finalize",
        "model-v4.1-r1",
        *model_base,
        "--eval-version",
        "eval-v4.1-r1",
    )
    _run(
        "model",
        "scope",
        "model-v4.1-r1",
        *model_base,
        "--backup-scope",
        "adapter",
    )
    model_manifest = root / "records" / "models" / "model-v4.1-r1" / "manifest.yaml"
    _run(
        "model", "manifest", "model-v4.1-r1", *model_base,
        "--target", str(model_manifest),
    )
    _run("model", "alias", "model-v4.1-r1", *model_base, "--alias", "candidate")
    _run(
        "model", "current", *model_base,
        "--alias", "candidate", "--service-mode", "development",
    )
    assert get_model_by_alias(open_registry_store(store), "candidate").model_id == "model-v4.1-r1"
    assert (root / "workspace" / "models" / "current").resolve().name == "model-v4.1-r1"

    result_refs = _yaml(root / "result-refs.yaml", {"summary": "results/summary.json"})
    manifest = root / "records" / "evaluations" / "eval-v4.1-r1" / "manifest.yaml"
    _run(
        "eval",
        "manifest",
        "eval-v4.1-r1",
        *eval_base,
        "--source-train",
        "train-v4.1-r1",
        "--prompt-version",
        "prompt-v4.1-r1",
        "--result-refs",
        str(result_refs),
        "--target",
        str(manifest),
    )
    assert validate_manifest(manifest.read_text(encoding="utf-8"))["eval"]["outcome"] == "passed"

    backup_root = root / "offline-backup"
    _run(
        "backup",
        "create",
        "--root",
        str(root),
        "--store",
        str(store),
        "--backup-root",
        str(backup_root),
    )
    _run("backup", "verify", "--root", str(root), "--backup-root", str(backup_root))
    assert {entry.object_id for entry in verify_backup(backup_root).objects} == {
        "data-v4.1-r1",
        "prompt-v4.1-r1",
        "model-v4.1-r1",
        "mlflow-store",
    }
