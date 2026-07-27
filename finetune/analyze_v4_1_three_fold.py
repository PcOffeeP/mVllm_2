#!/usr/bin/env python3
"""Aggregate three identity-bound fold summaries without quality gating."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def analyze(summaries: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    folds = [int(x["fold"]) for x in summaries]
    sources = [set(x["validation_sources"]) for x in summaries]
    same_identity = len({(x["release_id"], x["contract_version"], x["prompt_sha256"], x["recipe_sha256"]) for x in summaries}) == 1
    disjoint = all(not (sources[i] & sources[j]) for i in range(3) for j in range(i + 1, 3))
    complete = folds == [0, 1, 2] and same_identity and disjoint and all(x["runtime_failures"] == 0 and x["evaluation_count"] == x["evaluation_expected_count"] and x["artifact_integrity"] for x in summaries)
    integrity = {"schema_version": "tensile-vlm-v4.1-three-fold-integrity/v1", "overall": complete, "same_identity": same_identity, "validation_sources_disjoint": disjoint}
    metric_names = sorted(set.intersection(*(set(x["metrics"]) for x in summaries)))
    metrics = {}
    for name in metric_names:
        values = [float(x["metrics"][name]) for x in summaries]
        metrics[name] = {"mean": statistics.fmean(values), "stddev": statistics.pstdev(values), "min": min(values), "max": max(values), "mode": "record_only"}
    return integrity, {"schema_version": "tensile-vlm-v4.1-three-fold-aggregate/v1", "folds": summaries, "metrics": metrics, "absolute_performance_mode": "record_only"}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--fold-summary", type=Path, action="append", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args(argv)
    if len(args.fold_summary) != 3:
        p.error("exactly three --fold-summary values are required")
    values = sorted((json.loads(x.read_text()) for x in args.fold_summary), key=lambda x: x["fold"])
    integrity, aggregate = analyze(values)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("three_fold_integrity.json", integrity), ("three_fold_aggregate.json", aggregate)):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0 if integrity["overall"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
