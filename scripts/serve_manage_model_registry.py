#!/usr/bin/env python3
"""Inspect and validate the project-local model artifact registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.model_registry import resolve_service_model  # noqa: E402


def _inventory(root: Path) -> dict[str, Any]:
    base = (root / "models/minicpmv4_5").resolve()
    roots = [
        root / "models",
        root / "workspace",
        root / "LlamaFactory",
        root / "finetune",
    ]
    merged: set[Path] = set()
    adapter_roots: set[Path] = set()
    checkpoints: set[Path] = set()
    for scan_root in roots:
        if not scan_root.is_dir():
            continue
        for index in scan_root.rglob("model.safetensors.index.json"):
            model_dir = index.parent.resolve()
            if model_dir != base:
                merged.add(model_dir)
        for adapter in scan_root.rglob("adapter_model.safetensors"):
            parent = adapter.parent.resolve()
            if parent.name.startswith("checkpoint-"):
                checkpoints.add(parent)
            else:
                adapter_roots.add(parent)
    return {
        "schema_version": "tensile-model-registry/inventory/v1",
        "base_models": [str(base)] if base.is_dir() else [],
        "merged_models": [str(path) for path in sorted(merged)],
        "adapter_roots": [str(path) for path in sorted(adapter_roots)],
        "checkpoints": [str(path) for path in sorted(checkpoints)],
        "counts": {
            "base_models": 1 if base.is_dir() else 0,
            "merged_models": len(merged),
            "adapter_roots": len(adapter_roots),
            "checkpoints": len(checkpoints),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory", help="Historical inventory only; does not qualify models")
    for command in ("validate", "resolve-current"):
        route = subparsers.add_parser(command)
        route.add_argument("--alias", choices=("candidate", "production"), required=True)
        route.add_argument("--service-mode", choices=("development", "production"), required=True)
    args = parser.parse_args()
    if args.command == "inventory":
        value = _inventory(args.root)
    else:
        value = resolve_service_model(args.root, alias=args.alias, service_mode=args.service_mode)
        value = {**value, "passed": True, "runtime_verified": False}
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
