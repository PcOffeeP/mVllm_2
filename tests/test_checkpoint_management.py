from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.checkpoint_management import (
    CheckpointManagementError,
    apply_plan,
    build_plan,
    load_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pipeline/checkpoint_policy.json"
# 已在训练机删除的微调 run：不得再作为 checkpoint 保护项残留。
DELETED_RUN_ID = "v4.1-prompt-concise-cv-v1-seed3411"
CURRENT_RELEASE_SOURCE_ADAPTER = (
    "workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter"
)
STALE_ARCHIVE_CLAIM = (
    "All other models are completed comparison or archive artifacts"
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


def test_policy_has_no_protected_entries_for_deleted_run() -> None:
    policy = load_policy(POLICY_PATH)

    dangling = [
        entry["adapter"]
        for entry in policy["protected_experiments"]
        if DELETED_RUN_ID in entry["adapter"]
    ]

    assert dangling == []


def test_policy_keeps_current_release_training_source_protected() -> None:
    policy = load_policy(POLICY_PATH)

    entries = [
        entry
        for entry in policy["protected_experiments"]
        if entry["adapter"] == CURRENT_RELEASE_SOURCE_ADAPTER
    ]

    assert len(entries) == 1
    assert entries[0]["reason"] == "current_release_training_source"
    assert entries[0]["retention"] == "all"


def test_policy_protected_entries_declare_reason_adapter_and_retain_all() -> None:
    policy = load_policy(POLICY_PATH)

    protected = policy["protected_experiments"]

    assert protected
    for entry in protected:
        assert {"reason", "adapter", "retention"} <= set(entry)
        assert entry["retention"] == "all"


def test_policy_notes_drop_stale_archive_claim() -> None:
    policy = load_policy(POLICY_PATH)

    notes = policy["notes"]

    assert all(STALE_ARCHIVE_CLAIM not in note for note in notes)
