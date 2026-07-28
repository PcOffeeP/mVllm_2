"""CLI for validating and publishing immutable Prompt revisions."""

from __future__ import annotations

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


def main() -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
