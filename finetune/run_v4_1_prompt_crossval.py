#!/usr/bin/env python3
"""Run Fold0, Fold1, and Fold2 training sequentially and fail closed."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
FOLDS = (0, 1, 2)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _completed(output_dir: Path) -> bool:
    return (
        (output_dir / "adapter_config.json").is_file()
        and (output_dir / "trainer_state.json").is_file()
        and (output_dir / "train_results.json").is_file()
    )


def run(experiment_id: str, *, validate_only: bool = False) -> dict[str, Any]:
    config_dir = ROOT / "finetune/experiments" / experiment_id
    run_dir = ROOT / "workspace/runs" / experiment_id
    manifest = json.loads((config_dir / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("experiment_id") != experiment_id
        or manifest.get("status") != "prepared"
        or [item.get("fold") for item in manifest.get("folds") or []]
        != list(FOLDS)
    ):
        raise RuntimeError("crossval manifest 身份或 fold 列表非法")
    state_path = run_dir / "logs/crossval_state.json"
    state: dict[str, Any] = {
        "experiment_id": experiment_id,
        "status": "validated" if validate_only else "running",
        "updated_at": _now(),
        "folds": [],
    }
    for fold in FOLDS:
        config_path = config_dir / f"train_fold{fold}.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        output_dir = ROOT / str(config["output_dir"])
        if output_dir.exists() and not _completed(output_dir):
            raise RuntimeError(f"Fold{fold} output 已存在但不完整: {output_dir}")
        record = {
            "fold": fold,
            "config": str(config_path.relative_to(ROOT)),
            "output": str(output_dir.relative_to(ROOT)),
            "status": "already_completed" if _completed(output_dir) else "ready",
        }
        state["folds"].append(record)
        if validate_only or _completed(output_dir):
            continue
        record["status"] = "running"
        record["started_at"] = _now()
        state["updated_at"] = _now()
        _atomic_json(state_path, state)
        subprocess.run(
            [
                sys.executable,
                "finetune/train_with_contract.py",
                str(config_path.relative_to(ROOT)),
            ],
            cwd=ROOT,
            check=True,
        )
        if not _completed(output_dir):
            raise RuntimeError(f"Fold{fold} 训练进程返回但产物不完整")
        record["status"] = "completed"
        record["completed_at"] = _now()
        state["updated_at"] = _now()
        _atomic_json(state_path, state)
    if not validate_only:
        state["status"] = "completed"
        state["completed_at"] = _now()
        state["updated_at"] = _now()
        _atomic_json(state_path, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.experiment_id, validate_only=args.validate_only), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
