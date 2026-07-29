#!/usr/bin/env python3
"""Fail when supported active surfaces contain unapproved legacy data roots."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.active_data_path_guard import (  # noqa: E402
    ActiveDataPathError,
    scan_active_data_paths,
)


def main() -> int:
    try:
        result = scan_active_data_paths(PROJECT_ROOT)
    except ActiveDataPathError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
