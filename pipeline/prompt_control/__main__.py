"""CLI for validating and publishing immutable Prompt revisions."""

from __future__ import annotations

import sys


def main() -> int:
    message = (
        "旧 Prompt validate/publish CLI 已停用。请使用 python -m versioning prompt "
        "create/show/freeze/verify，显式指定 --root 和完整 --version。"
        "既有Prompt迁移使用 python -m versioning migration 与已确认mapping；"
        "定义格式和完整参数见 versioning/SCRIPTS.md。"
    )
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


import argparse
import json
from pathlib import Path

from .core import publish_prompt, validate_active_prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "publish"):
        item = subparsers.add_parser(command)
        item.add_argument("--source", type=Path, required=True)
    publish = subparsers.choices["publish"]
    publish.add_argument("--registry-root", type=Path)
    return parser.parse_args()


def _legacy_main() -> int:
    args = parse_args()
    if args.command == "validate":
        prompt = validate_active_prompt(args.source)
        result = {
            "status": "valid",
            "revision_id": prompt["revision_id"],
            "protocol_id": prompt["protocol_id"],
        }
    else:
        kwargs = {}
        if args.registry_root is not None:
            kwargs["registry_root"] = args.registry_root
        target, manifest = publish_prompt(args.source, **kwargs)
        result = {
            "status": "published",
            "revision_dir": str(target),
            "revision_id": manifest["revision_id"],
            "prompt_content_sha256": manifest["prompt_content_sha256"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
