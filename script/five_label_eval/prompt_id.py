"""Content-addressed Prompt identity so one scoring batch pins the exact Prompt bytes."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

PROMPT_ID_PREFIX = "prompt@sha256:"


def prompt_id_for_bytes(data: bytes) -> str:
    return PROMPT_ID_PREFIX + hashlib.sha256(data).hexdigest()


def load_prompt(path) -> tuple[str, str]:
    """Return the Prompt text unchanged (no strip) plus its identity."""
    data = Path(path).read_bytes()
    return data.decode("utf-8"), prompt_id_for_bytes(data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Prompt text file whose identity is computed")
    parser.add_argument("--verify", required=True, help="Expected Prompt ID recorded for the run")
    args = parser.parse_args(argv)
    try:
        _, actual = load_prompt(args.file)
    except (OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if actual != args.verify:
        print(f"ERROR: prompt ID mismatch; actual id is {actual}", file=sys.stderr)
        return 1
    print(actual)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
