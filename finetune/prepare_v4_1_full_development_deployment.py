#!/usr/bin/env python3
"""Freeze a non-production full-development model component identity."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.v4_1_manifest_runtime import atomic_json, sha256_file


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--merged-model", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--base-model-identity", required=True)
    p.add_argument("--adapter-manifest", type=Path, required=True)
    args = p.parse_args(argv)
    files = {str(x.relative_to(args.merged_model)): {"size_bytes": x.stat().st_size, "sha256": sha256_file(x)} for x in sorted(args.merged_model.rglob("*")) if x.is_file()}
    payload = {"immutable": True, "schema_version": "tensile-vlm/v4.1-full-development-model-component/v1", "capability": "full_development_model", "base_model_identity": args.base_model_identity, "adapter_manifest_sha256": sha256_file(args.adapter_manifest), "files": files}
    forbidden = {"production_passed", "independent_test_passed", "quality_final"}
    if forbidden & set(payload):
        raise RuntimeError("forbidden capability claim")
    atomic_json(args.output, payload, immutable=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
