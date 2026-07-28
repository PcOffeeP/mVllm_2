#!/usr/bin/env python3
"""Historical external-root utility; active V4.1 uses ``workspace/data``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.data_roots import (
    initialize_root,
    initialize_workspace,
    load_config,
    resolve_data_home,
    validate_root,
    validate_workspace,
)

DEFAULT_CONFIG = PROJECT_ROOT / "config/data_roots.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "check", "workspace"))
    parser.add_argument(
        "--contract",
        choices=("tensile-vlm/v2", "tensile-vlm/v4.1", "all"),
        default="all",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-home", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    data_home = resolve_data_home(
        config,
        project_root=PROJECT_ROOT,
        override=args.data_home,
    )
    contracts = (
        tuple(config["profiles"])
        if args.contract == "all"
        else (args.contract,)
    )
    results = []
    for contract_version in contracts:
        if args.action == "init":
            initialize_root(
                config,
                contract_version,
                data_home=data_home,
            )
        elif args.action == "workspace":
            initialize_workspace(
                config,
                contract_version,
                data_home=data_home,
            )
        result = validate_root(
            config,
            contract_version,
            data_home=data_home,
        )
        if args.action == "workspace":
            result["workspace"] = validate_workspace(
                config,
                contract_version,
                data_home=data_home,
            )
        results.append(result)
    print(
        json.dumps(
            {"data_home": str(data_home), "profiles": results},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
