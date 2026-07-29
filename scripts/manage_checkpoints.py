#!/usr/bin/env python3
"""Plan or apply the checkpoint retention policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.checkpoint_management import apply_plan, build_plan, load_policy  # noqa: E402


def _write_or_print(value: dict, output: Path | None) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        print(encoded, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
        print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "pipeline/checkpoint_policy.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--output", type=Path)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--plan", type=Path, required=True)
    apply_parser.add_argument("--confirm", required=True)
    apply_parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if args.command == "plan":
        value = build_plan(ROOT, load_policy(args.policy))
        _write_or_print(value, args.output)
        return 0
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    value = apply_plan(ROOT, plan, args.confirm)
    _write_or_print(value, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
