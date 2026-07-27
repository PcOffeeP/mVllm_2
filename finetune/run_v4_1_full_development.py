#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from finetune.v4_1_manifest_runtime import launch_singleton


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--run-manifest", type=Path, required=True)
    p.add_argument("--phase", choices=("train", "merge"), required=True)
    args = p.parse_args(argv)
    print(json.dumps(launch_singleton(args.run_manifest, args.phase), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
