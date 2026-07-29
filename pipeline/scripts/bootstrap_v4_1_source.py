#!/usr/bin/env python3
"""Validate V4.1 source inputs and create an isolated source snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.current_data import (  # noqa: E402
    current_data_context,
    data_context_for_root,
)
from pipeline.source_bootstrap import (  # noqa: E402
    DEFAULT_EXPECTED_COUNT,
    SourceBootstrapError,
    build_source_snapshot,
    materialize_source_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-data-root",
        type=Path,
        default=PROJECT_ROOT / "workspace/data",
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=DEFAULT_EXPECTED_COUNT)
    parser.add_argument("--check-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    current = current_data_context(PROJECT_ROOT)
    source_root = args.source_data_root
    if not source_root.is_absolute():
        source_root = PROJECT_ROOT / source_root
    if source_root.resolve() != current.root:
        print("错误: source-data-root 必须是当前 workspace/data", file=sys.stderr)
        return 2
    try:
        rebuild = data_context_for_root(PROJECT_ROOT, args.data_root)
        bundle = build_source_snapshot(
            current,
            rebuild,
            expected_count=args.expected_count,
        )
        result = {
            "status": "passed",
            "check_only": args.check_only,
            "source_snapshot_id": bundle["snapshot_id"],
            "identity_sha256": bundle["identity_sha256"],
            "validation": bundle["validation"],
            "split_counts": {
                name: len(ids) for name, ids in bundle["splits"].items()
            },
        }
        if not args.check_only:
            result["destination"] = str(materialize_source_snapshot(bundle))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except SourceBootstrapError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
