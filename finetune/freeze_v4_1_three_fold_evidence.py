#!/usr/bin/env python3
"""Freeze hashes of the light-weight three-fold evidence."""

import argparse
import json
from pathlib import Path

from finetune.v4_1_manifest_runtime import atomic_json, sha256_file


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args(argv)
    files = {name: sha256_file(args.output_dir / name) for name in ("three_fold_integrity.json", "three_fold_aggregate.json")}
    atomic_json(args.output_dir / "three_fold_evidence_manifest.json", {"immutable": True, "schema_version": "tensile-vlm-v4.1-three-fold-evidence/v1", "files": files}, immutable=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
