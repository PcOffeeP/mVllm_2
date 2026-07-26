#!/usr/bin/env python3
"""Validate any immutable V4.1 release through the finetuning runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finetune.v4_1_runtime import RELEASE_ID, validate_release

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", default=RELEASE_ID)
    parser.add_argument("--verify-media", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_release(
        ROOT,
        release_id=args.release_id,
        verify_media=args.verify_media,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
