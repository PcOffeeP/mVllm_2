#!/usr/bin/env python3
"""Launch one manifest-bound cross-validation phase."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.v4_1_manifest_runtime import launch_singleton


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--run-manifest", type=Path, required=True)
    p.add_argument("--fold", type=int, choices=(0, 1, 2), required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--phase", choices=("train", "merge", "evaluate"), required=True)
    args = p.parse_args(argv)
    manifest = json.loads(args.run_manifest.read_text())
    if manifest.get("fold") != args.fold or manifest.get("seed") != args.seed:
        p.error("CLI identity does not match immutable run manifest")
    print(json.dumps(launch_singleton(args.run_manifest, args.phase), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
