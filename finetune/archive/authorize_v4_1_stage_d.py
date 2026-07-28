#!/usr/bin/env python3
"""Create a one-time Stage D authorization from an explicit user decision."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.v4_1_stage_d_runtime import (
    atomic_write,
    build_authorization,
    pretty_bytes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-manifest", type=Path, required=True)
    parser.add_argument("--authorized-by", required=True)
    parser.add_argument("--user-authorization-reference", required=True)
    parser.add_argument("--authorized-at")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    authorization = build_authorization(
        prepared_manifest_path=args.prepared_manifest,
        authorized_by=args.authorized_by,
        user_authorization_reference=args.user_authorization_reference,
        authorized_at=args.authorized_at,
    )
    output = args.output or (
        args.prepared_manifest.parent / "stage_d_authorization.json"
    )
    atomic_write(output, pretty_bytes(authorization), mode=0o600)
    print(
        json.dumps(
            {
                "authorization_id": authorization["authorization_id"],
                "authorization_path": str(output),
                "scope": authorization["scope"],
                "one_time": authorization["one_time"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
