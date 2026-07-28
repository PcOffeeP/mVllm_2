#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.v4_1_manifest_runtime import monitor


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--run-manifest", type=Path, required=True)
    args = p.parse_args(argv)
    print(json.dumps(monitor(args.run_manifest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
