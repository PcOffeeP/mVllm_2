#!/usr/bin/env python3
"""Report Stage B training progress and an ETA-based next check interval."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.run_v4_1_source_aware_3k import (
    LOG_ROOT,
    SEEDS,
    adapter_dir,
)

EXPECTED_STEPS = 1125
FIRST_RELIABLE_STEP = 50
LOG_STALE_SECONDS = 10 * 60


class StageBMonitorError(ValueError):
    """The training progress evidence is invalid or internally inconsistent."""


def _duration_seconds(value: Any) -> int:
    if not isinstance(value, str):
        raise StageBMonitorError(f"时间字段不是字符串: {value!r}")
    parts = value.split(":")
    if len(parts) != 3:
        raise StageBMonitorError(f"时间字段格式非法: {value!r}")
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError as exc:
        raise StageBMonitorError(f"时间字段格式非法: {value!r}") from exc
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        raise StageBMonitorError(f"时间字段范围非法: {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise StageBMonitorError(f"无法读取训练日志 {path}: {exc}") from exc
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StageBMonitorError(f"{path}:{line_no}: 非法 JSONL") from exc
        if not isinstance(row, dict):
            raise StageBMonitorError(f"{path}:{line_no}: 训练日志行不是对象")
        rows.append(row)
    if not rows:
        raise StageBMonitorError(f"训练日志为空: {path}")
    return rows


def _pid_alive(pid: Any) -> bool | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _orchestrator_status() -> dict[str, Any]:
    state_path = LOG_ROOT / "state.json"
    if not state_path.is_file():
        return {"state_path": str(state_path), "state": None, "pid_alive": None}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageBMonitorError(f"运行状态非法: {state_path}: {exc}") from exc
    if not isinstance(state, Mapping):
        raise StageBMonitorError(f"运行状态不是对象: {state_path}")
    return {
        "state_path": str(state_path),
        "state": dict(state),
        "pid_alive": _pid_alive(state.get("orchestrator_pid")),
    }


def _complete(seed: int) -> bool:
    root = adapter_dir(seed)
    state_path = root / "trainer_state.json"
    required = (
        root / "train_results.json",
        root / "adapter_config.json",
        root / "adapter_model.safetensors",
    )
    if not state_path.is_file() or not all(path.is_file() for path in required):
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(state, Mapping) and state.get("global_step") == EXPECTED_STEPS


def monitor(seed: int, *, now: datetime | None = None) -> dict[str, Any]:
    if seed not in SEEDS:
        raise StageBMonitorError(f"不支持的 seed: {seed}")
    now = now or datetime.now().astimezone()
    root = adapter_dir(seed)
    trainer_log = root / "trainer_log.jsonl"
    orchestrator = _orchestrator_status()
    if _complete(seed):
        return {
            "schema_version": "tensile-vlm-v4.1-source-aware-3k-monitor/v1",
            "seed": seed,
            "status": "complete",
            "current_steps": EXPECTED_STEPS,
            "total_steps": EXPECTED_STEPS,
            "progress": 1.0,
            "eta_reliable": True,
            "estimated_completion_at": None,
            "suggested_check_after_seconds": 0,
            "orchestrator": orchestrator,
        }
    if not trainer_log.is_file():
        return {
            "schema_version": "tensile-vlm-v4.1-source-aware-3k-monitor/v1",
            "seed": seed,
            "status": "not_started",
            "current_steps": 0,
            "total_steps": EXPECTED_STEPS,
            "progress": 0.0,
            "eta_reliable": False,
            "estimated_completion_at": None,
            "suggested_check_after_seconds": 15 * 60,
            "orchestrator": orchestrator,
        }
    rows = _read_jsonl(trainer_log)
    latest = rows[-1]
    current = latest.get("current_steps")
    total = latest.get("total_steps")
    if (
        not isinstance(current, int)
        or current <= 0
        or total != EXPECTED_STEPS
        or current > EXPECTED_STEPS
    ):
        raise StageBMonitorError("trainer_log steps 非法或与 1125 漂移")
    elapsed = _duration_seconds(latest.get("elapsed_time"))
    remaining = _duration_seconds(latest.get("remaining_time"))
    first_eval = next(
        (
            row
            for row in rows
            if row.get("current_steps") == FIRST_RELIABLE_STEP
            and isinstance(row.get("eval_loss"), (int, float))
        ),
        None,
    )
    log_age = max(0.0, now.timestamp() - trainer_log.stat().st_mtime)
    running = orchestrator["pid_alive"] is True
    stale = running and log_age > LOG_STALE_SECONDS
    eta_reliable = first_eval is not None
    if eta_reliable:
        estimated_completion = now + timedelta(seconds=remaining)
        suggested = min(
            4 * 3600,
            max(15 * 60, math.ceil(remaining * 0.85)),
        )
        status = "running"
    else:
        seconds_per_step = elapsed / current
        seconds_to_first_eval = (
            max(0, FIRST_RELIABLE_STEP - current) * seconds_per_step
            + 4 * 60
        )
        estimated_completion = None
        suggested = min(
            30 * 60,
            max(5 * 60, math.ceil(seconds_to_first_eval)),
        )
        status = "warming_up"
    if stale:
        status = "stale"
        suggested = 5 * 60
    return {
        "schema_version": "tensile-vlm-v4.1-source-aware-3k-monitor/v1",
        "seed": seed,
        "status": status,
        "current_steps": current,
        "total_steps": total,
        "progress": round(current / total, 6),
        "epoch": latest.get("epoch"),
        "loss": latest.get("loss"),
        "eval_loss": latest.get("eval_loss"),
        "elapsed_seconds": elapsed,
        "reported_remaining_seconds": remaining,
        "eta_reliable": eta_reliable,
        "first_50_step_eval": first_eval,
        "estimated_completion_at": (
            estimated_completion.isoformat(timespec="seconds")
            if estimated_completion is not None
            else None
        ),
        "suggested_check_after_seconds": suggested,
        "trainer_log": str(trainer_log),
        "trainer_log_age_seconds": round(log_age, 3),
        "stale_threshold_seconds": LOG_STALE_SECONDS,
        "orchestrator": orchestrator,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, choices=SEEDS, required=True)
    return parser.parse_args()


def main() -> int:
    report = monitor(parse_args().seed)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "stale" else 0


if __name__ == "__main__":
    raise SystemExit(main())
