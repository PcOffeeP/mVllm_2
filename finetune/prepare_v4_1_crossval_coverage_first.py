#!/usr/bin/env python3
"""Prepare immutable, content-addressed V4.1 cross-validation identities."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.build_v4_1_crossval_coverage_first import build_fold
from finetune.v4_1_manifest_runtime import atomic_json, sha256_file


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--release-dir", type=Path, required=True)
    p.add_argument("--fold", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--validate-only", action="store_true")
    args = p.parse_args(argv)
    release_manifest = args.release_dir / "manifest/release_manifest.json"
    candidates_path = args.release_dir / "metadata/training_candidates.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))["candidates"]
    built = build_fold(candidates, args.fold, args.seed)
    report = {
        "release_id": json.loads(release_manifest.read_text())["release_id"],
        "release_manifest_sha256": sha256_file(release_manifest),
        **built["sampling_manifest"],
        "train_candidate_count": len(built["train"]),
        "validation_candidate_count": len(built["validation"]),
        "validate_only": args.validate_only,
    }
    if args.validate_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    identity = report["candidate_multiset_sha256"][:12]
    root = args.output_root / f"fold{args.fold}_seed{args.seed}_{identity}"
    root.mkdir(parents=True, exist_ok=False)
    atomic_json(root / "sampling_manifest.json", report, immutable=True)
    run_manifest = {
        "schema_version": "tensile-vlm-v4.1-crossval-run/v1",
        "immutable": True,
        "run_id": root.name,
        "repo_root": str(Path.cwd()),
        "state_path": str(root / "state.json"),
        "log_root": str(root / "logs"),
        "fold": args.fold,
        "seed": args.seed,
        "expected_global_step": 1125,
        "evaluation_expected_count": len(built["validation"]),
        "input_sha256": {"sampling_manifest.json": sha256_file(root / "sampling_manifest.json")},
        "commands": {},
    }
    atomic_json(root / "run_manifest.json", run_manifest, immutable=True)
    print(root / "run_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
