from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import finetune.monitor_v4_1_source_aware_3k as monitor


def _write_log(root: Path, rows: list[dict]) -> None:
    root.mkdir(parents=True)
    (root / "trainer_log.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _row(
    step: int,
    elapsed: str,
    remaining: str,
    *,
    eval_loss: float | None = None,
) -> dict:
    row = {
        "current_steps": step,
        "total_steps": 1125,
        "elapsed_time": elapsed,
        "remaining_time": remaining,
        "epoch": step / 375,
        "loss": 0.1,
    }
    if eval_loss is not None:
        row["eval_loss"] = eval_loss
    return row


def test_warmup_schedules_check_near_first_eval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "seed"
    _write_log(root, [_row(10, "0:01:50", "3:24:15")])
    monkeypatch.setattr(monitor, "adapter_dir", lambda seed: root)
    monkeypatch.setattr(
        monitor,
        "_orchestrator_status",
        lambda: {"state": {}, "pid_alive": True},
    )
    now = datetime.fromtimestamp(
        (root / "trainer_log.jsonl").stat().st_mtime,
        tz=timezone.utc,
    )

    report = monitor.monitor(3407, now=now)

    assert report["status"] == "warming_up"
    assert report["eta_reliable"] is False
    assert 5 * 60 <= report["suggested_check_after_seconds"] <= 30 * 60


def test_first_eval_makes_eta_reliable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "seed"
    _write_log(
        root,
        [
            _row(50, "0:09:10", "3:17:05"),
            _row(50, "0:12:35", "4:14:20", eval_loss=0.2),
        ],
    )
    monkeypatch.setattr(monitor, "adapter_dir", lambda seed: root)
    monkeypatch.setattr(
        monitor,
        "_orchestrator_status",
        lambda: {"state": {}, "pid_alive": True},
    )
    now = datetime.fromtimestamp(
        (root / "trainer_log.jsonl").stat().st_mtime,
        tz=timezone.utc,
    )

    report = monitor.monitor(3407, now=now)

    assert report["status"] == "running"
    assert report["eta_reliable"] is True
    assert report["reported_remaining_seconds"] == 4 * 3600 + 14 * 60 + 20
    assert report["estimated_completion_at"] is not None


def test_complete_requires_final_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "seed"
    root.mkdir()
    for name in (
        "train_results.json",
        "adapter_config.json",
        "adapter_model.safetensors",
    ):
        (root / name).write_text("{}", encoding="utf-8")
    (root / "trainer_state.json").write_text(
        json.dumps({"global_step": 1125}),
        encoding="utf-8",
    )
    monkeypatch.setattr(monitor, "adapter_dir", lambda seed: root)
    monkeypatch.setattr(
        monitor,
        "_orchestrator_status",
        lambda: {"state": {}, "pid_alive": False},
    )

    report = monitor.monitor(3407)

    assert report["status"] == "complete"
    assert report["current_steps"] == 1125
