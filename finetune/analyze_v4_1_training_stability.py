#!/usr/bin/env python3
"""Identity-bound V4.1 dual-seed stability analysis.

The analyzer deliberately separates run integrity, relative stability, and
record-only absolute performance. It never reads sealed-test data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


class StabilityError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_records(path: Path) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            candidate_id = item.get("candidate_id") or item.get("id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise StabilityError(f"{path}:{line_no}: missing candidate_id")
            if candidate_id in records:
                raise StabilityError(f"{path}:{line_no}: duplicate candidate_id")
            records[candidate_id] = item
    if not records:
        raise StabilityError(f"{path}: no evaluation records")
    return records


def _metric(record: Mapping[str, Any], name: str) -> float | None:
    metrics = record.get("metrics")
    value = metrics.get(name) if isinstance(metrics, Mapping) else record.get(name)
    if value is None:
        return None
    return float(value)


def _prediction(record: Mapping[str, Any]) -> bool:
    for key in ("predicted_has_fracture", "has_fracture_prediction", "prediction"):
        value = record.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, Mapping) and isinstance(value.get("has_fracture"), bool):
            return bool(value["has_fracture"])
        if isinstance(value, Mapping) and isinstance(value.get("clip_state"), str):
            return value["clip_state"] in {"发生断裂", "已断裂"}
    raise StabilityError("record missing boolean fracture prediction")


def _target(record: Mapping[str, Any]) -> bool:
    value = record.get("target")
    if isinstance(value, Mapping):
        if isinstance(value.get("has_fracture"), bool):
            return bool(value["has_fracture"])
        if isinstance(value.get("clip_state"), str):
            return value["clip_state"] in {"发生断裂", "已断裂"}
    raise StabilityError("record missing target fracture state")


def _aggregate_metrics(records: Mapping[str, Mapping[str, Any]]) -> dict[str, float | None]:
    """Calculate the pre-registered binary metrics from strict eval records."""
    # Synthetic unit fixtures may provide already-computed scalar metrics.
    if all("target" not in record for record in records.values()):
        names = ("fracture_recall", "non_fracture_recall", "fracture_f1", "macro_f1", "strict_valid_rate")
        return {
            name: (
                sum(values) / len(values)
                if (values := [v for record in records.values() if (v := _metric(record, name)) is not None])
                else None
            )
            for name in names
        }
    tp = tn = fp = fn = 0
    strict_valid = 0
    for record in records.values():
        target, predicted = _target(record), _prediction(record)
        strict_valid += bool(record.get("strict_valid"))
        if target and predicted:
            tp += 1
        elif target:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    fracture_recall = tp / (tp + fn) if tp + fn else None
    non_fracture_recall = tn / (tn + fp) if tn + fp else None
    fracture_f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    non_fracture_f1 = 2 * tn / (2 * tn + fp + fn) if 2 * tn + fp + fn else None
    macro_f1 = (
        (fracture_f1 + non_fracture_f1) / 2
        if fracture_f1 is not None and non_fracture_f1 is not None
        else None
    )
    return {
        "fracture_recall": fracture_recall,
        "non_fracture_recall": non_fracture_recall,
        "fracture_f1": fracture_f1,
        "macro_f1": macro_f1,
        "strict_valid_rate": strict_valid / len(records),
    }


def compare_pair(
    left_path: Path,
    right_path: Path,
    policy: Mapping[str, Any],
    *,
    left_seed: int,
    right_seed: int,
    runtime_failures: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    left, right = _read_records(left_path), _read_records(right_path)
    if set(left) != set(right):
        raise StabilityError("candidate sets differ")
    failures = runtime_failures or {}
    integrity = failures.get(left_seed, 0) == failures.get(right_seed, 0) == 0
    left_metrics, right_metrics = _aggregate_metrics(left), _aggregate_metrics(right)
    metric_gates: dict[str, Any] = {}
    all_available = True
    all_pass = True
    for name, limit in policy["relative_limits_percentage_points"].items():
        lv, rv = left_metrics.get(name), right_metrics.get(name)
        available = lv is not None and rv is not None
        item: dict[str, Any] = {"available": available, "limit_percentage_points": limit}
        if available:
            lmean, rmean = float(lv), float(rv)
            delta = abs(lmean - rmean) * 100
            item.update(left=lmean, right=rmean, delta_percentage_points=delta, passed=delta <= float(limit) + 1e-12)
            all_pass = all_pass and bool(item["passed"])
        else:
            item["reason"] = "zero_or_missing_denominator"
            all_available = False
        metric_gates[name] = item
    disagreements = sum(_prediction(left[c]) != _prediction(right[c]) for c in left)
    disagreement_rate = disagreements / len(left)
    disagreement_pass = disagreement_rate <= float(policy["max_prediction_disagreement_rate"])
    overall = integrity and all_available and all_pass and disagreement_pass
    return {
        "schema_version": "tensile-vlm-v4.1-relative-stability-gate/v1",
        "pair": [left_seed, right_seed],
        "run_integrity": integrity,
        "candidate_count": len(left),
        "metric_gates": metric_gates,
        "prediction_disagreement_rate": disagreement_rate,
        "prediction_disagreement_limit": policy["max_prediction_disagreement_rate"],
        "prediction_disagreement_passed": disagreement_pass,
        "overall": overall,
        "input_sha256": {str(left_seed): sha256_file(left_path), str(right_seed): sha256_file(right_path)},
    }


def final_disposition(primary: Mapping[str, Any], fallback_pairs: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    if not primary.get("run_integrity"):
        return {"status": "integrity_blocked", "continue_to_crossval": False}
    if primary.get("overall"):
        return {"status": "primary_pass", "continue_to_crossval": True, "training_stability_not_established": False}
    fallback_pairs = fallback_pairs or []
    if any(not pair.get("run_integrity") for pair in fallback_pairs):
        return {"status": "integrity_blocked", "continue_to_crossval": False}
    passing = [pair for pair in fallback_pairs if pair.get("overall")]
    if passing:
        stable = set(passing[0]["pair"])
        return {
            "status": "fallback_pass_with_outlier",
            "continue_to_crossval": True,
            "training_stability_not_established": False,
            "outlier_seed": next(seed for seed in (3407, 3411, 3413) if seed not in stable),
        }
    if fallback_pairs:
        return {
            "status": "stability_unresolved_record_only",
            "continue_to_crossval": True,
            "training_stability_not_established": True,
        }
    return {"status": "fallback_required", "continue_to_crossval": False}


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seed3407-records", type=Path, required=True)
    p.add_argument("--seed3411-records", type=Path, required=True)
    p.add_argument("--seed3413-records", type=Path)
    p.add_argument("--policy", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--scorer-identity", required=True)
    args = p.parse_args(argv)
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    primary = compare_pair(args.seed3407_records, args.seed3411_records, policy, left_seed=3407, right_seed=3411)
    fallbacks: list[dict[str, Any]] = []
    if args.seed3413_records:
        fallbacks = [
            compare_pair(args.seed3407_records, args.seed3413_records, policy, left_seed=3407, right_seed=3413),
            compare_pair(args.seed3411_records, args.seed3413_records, policy, left_seed=3411, right_seed=3413),
        ]
    disposition = final_disposition(primary, fallbacks)
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    common = {"generated_at": generated, "policy_sha256": sha256_file(args.policy), "scorer_identity": args.scorer_identity}
    _write(args.output_dir / "primary_stability_comparison.json", {**primary, **common})
    _write(args.output_dir / "relative_stability_gate.json", {**primary, **common})
    _write(args.output_dir / "fallback_stability_comparison.json", {"pairs": fallbacks, **common})
    _write(args.output_dir / "final_stability_disposition.json", {**disposition, **common})
    _write(args.output_dir / "paired_prediction_comparison.json", {"candidate_count": primary["candidate_count"], "prediction_disagreement_rate": primary["prediction_disagreement_rate"], **common})
    _write(args.output_dir / "absolute_performance_snapshot.json", {"mode": "record_only", "historical_reference": {"fracture_recall": 0.5}, **common})
    with (args.output_dir / "dual_seed_stability_timeline.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"event": "stability_disposition_frozen", "disposition": disposition, **common}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
