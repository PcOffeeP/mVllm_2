from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.checkpoint_management import (
    CheckpointManagementError,
    apply_plan,
    build_plan,
)


def _experiment(root: Path, name: str, *, best: int | None) -> Path:
    parent = root / f"workspace/runs/{name}"
    adapter = parent / "adapter"
    merged = parent / "merged"
    adapter.mkdir(parents=True)
    merged.mkdir()
    chosen = best or 20
    (adapter / "adapter_model.safetensors").write_bytes(f"weight-{chosen}".encode())
    (adapter / "trainer_state.json").write_text(
        json.dumps(
            {
                "best_model_checkpoint": (
                    f"/old/checkpoint-{best}" if best is not None else None
                )
            }
        ),
        encoding="utf-8",
    )
    for step in (10, 20):
        checkpoint = adapter / f"checkpoint-{step}"
        checkpoint.mkdir()
        (checkpoint / "adapter_model.safetensors").write_bytes(
            f"weight-{step}".encode()
        )
        (checkpoint / "optimizer.pt").write_bytes(b"optimizer")
    return adapter


def test_plan_keeps_all_checkpoints_for_protected_experiments(tmp_path: Path) -> None:
    current = _experiment(tmp_path, "current", best=10)
    _experiment(tmp_path, "old", best=10)
    policy = {
        "schema_version": "tensile-checkpoint-policy/v1",
        "protected_experiments": [
            {
                "reason": "current_release_training_source",
                "adapter": str(current.relative_to(tmp_path)),
                "retention": "all",
            }
        ],
    }

    plan = build_plan(tmp_path, policy)

    assert plan["summary"]["checkpoint_count"] == 4
    assert plan["summary"]["keep_count"] == 2
    assert plan["summary"]["delete_count"] == 2


def test_apply_requires_exact_confirmation_and_detects_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = _experiment(tmp_path, "current", best=10)
    policy = {
        "schema_version": "tensile-checkpoint-policy/v1",
        "protected_experiments": [],
    }
    plan = build_plan(tmp_path, policy)
    monkeypatch.setattr(
        "pipeline.checkpoint_management._assert_no_training_process", lambda: None
    )

    with pytest.raises(CheckpointManagementError, match="确认字符串"):
        apply_plan(tmp_path, plan, "yes")

    target = tmp_path / plan["actions"][0]["path"] / "optimizer.pt"
    target.write_bytes(b"changed")
    with pytest.raises(CheckpointManagementError, match="发生变化"):
        apply_plan(tmp_path, plan, "DELETE-2-CHECKPOINTS")
