"""Summarize one LLaMA-Factory training run without modifying its artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


ERROR_PATTERNS = re.compile(
    r"(Traceback \(most recent call last\)|CUDA out of memory|RuntimeError:|ValueError:)",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--pid-file")
    parser.add_argument("--tail-lines", type=int, default=30)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def latest_trainer_state(run_dir: Path) -> tuple[dict[str, Any], Path | None]:
    """Read the final state or the newest valid numbered checkpoint state."""
    final_path = run_dir / "trainer_state.json"
    final_state = read_json(final_path)
    if final_state is not None:
        return final_state, final_path

    checkpoints: list[tuple[int, Path]] = []
    try:
        children = list(run_dir.iterdir())
    except OSError:
        return {}, None
    for child in children:
        match = re.fullmatch(r"checkpoint-(\d+)", child.name)
        if match is not None and child.is_dir():
            checkpoints.append((int(match.group(1)), child / "trainer_state.json"))
    for _step, path in sorted(checkpoints, reverse=True):
        state = read_json(path)
        if state is not None:
            return state, path
    return {}, None


def read_pid(path: Path | None) -> int | None:
    if path is None or not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def process_is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def tail(path: Path, line_count: int) -> list[str]:
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_count:]
    except OSError:
        return []


def gpu_snapshot() -> list[dict[str, str]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return []
    keys = ["index", "name", "memory_used_mib", "memory_total_mib", "utilization_percent", "temperature_c"]
    return [
        dict(zip(keys, (part.strip() for part in line.split(",")), strict=True))
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)
    log_file = Path(args.log_file)
    pid_file = Path(args.pid_file) if args.pid_file else None
    pid = read_pid(pid_file)
    running = process_is_running(pid)
    trainer_state, trainer_state_path = latest_trainer_state(run_dir)
    train_results = read_json(run_dir / "train_results.json")
    eval_results = read_json(run_dir / "eval_results.json")
    log_tail = tail(log_file, args.tail_lines)
    has_error = bool(ERROR_PATTERNS.search("\n".join(log_tail)))
    adapter_present = any(
        (run_dir / name).is_file()
        for name in ("adapter_model.safetensors", "adapter_model.bin")
    )

    if running:
        status = "running"
    elif train_results is not None and adapter_present:
        status = "completed"
    elif has_error:
        status = "failed"
    elif pid is None and not run_dir.exists():
        status = "not_started"
    else:
        status = "stopped_or_incomplete"

    log_history = trainer_state.get("log_history")
    latest_history = log_history[-5:] if isinstance(log_history, list) else []
    summary = {
        "status": status,
        "pid": pid,
        "process_running": running,
        "run_dir": str(run_dir),
        "log_file": str(log_file),
        "trainer_state_path": (
            str(trainer_state_path) if trainer_state_path is not None else None
        ),
        "global_step": trainer_state.get("global_step"),
        "max_steps": trainer_state.get("max_steps"),
        "epoch": trainer_state.get("epoch"),
        "best_metric": trainer_state.get("best_metric"),
        "best_model_checkpoint": trainer_state.get("best_model_checkpoint"),
        "latest_history": latest_history,
        "train_results": train_results,
        "eval_results": eval_results,
        "adapter_present": adapter_present,
        "gpu": gpu_snapshot(),
        "log_tail": log_tail,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
