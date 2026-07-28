#!/usr/bin/env python3
"""Gate both Stage B seeds and produce source-level/LOSO error evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finetune.archive.run_v4_1_source_aware_3k import (
    EXPECTED_VALIDATION_COUNT,
    RELEASE_ID,
    RESULT_ROOT,
    RUN_ID,
    SEEDS,
)

BASELINE_RUN_ID = "v4_1_0_760050fad303_20260724_visual"
BASELINE_ROOT = (
    ROOT
    / "finetune/results"
    / BASELINE_RUN_ID
    / "three_fold_validation/fold0"
)
FRACTURE_STATES = ("临界未断裂", "发生断裂", "已断裂")
FOUR_STATES = (*FRACTURE_STATES, "未断裂")
PRIMARY_IMPROVEMENT_METRICS = (
    "fracture_three_state_macro_recall",
    "four_state_macro_recall",
    "已断裂_recall",
)
ABSOLUTE_GATES = {
    "fracture_three_state_macro_recall": 0.3272,
    "four_state_macro_recall": 0.4382,
    "已断裂_recall": 0.2015,
    "未断裂_recall": 0.7510,
    "joint_correct_rate": 0.4112,
    "strict_valid_rate": 1.0,
    "runtime_failure_count": 0,
}
MIN_LOSO_IMPROVEMENT_RETENTION = 0.5


class StageBGateError(ValueError):
    """Stage B record evidence is missing, inconsistent, or fails a gate."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise StageBGateError(f"无法读取逐样本记录 {path}: {exc}") from exc
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StageBGateError(f"{path}:{line_no}: 非法 JSONL") from exc
        candidate_id = record.get("candidate_id")
        source = record.get("source_video")
        target = record.get("target")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in seen
            or not isinstance(source, str)
            or not source
            or not isinstance(target, Mapping)
            or target.get("clip_state") not in FOUR_STATES
        ):
            raise StageBGateError(f"{path}:{line_no}: 记录身份或标签非法")
        seen.add(candidate_id)
        records.append(record)
    if len(records) != EXPECTED_VALIDATION_COUNT:
        raise StageBGateError(
            f"{path}: 应有 {EXPECTED_VALIDATION_COUNT} 条，实际 {len(records)}"
        )
    return records


def _recall(
    records: Iterable[Mapping[str, Any]],
    state: str,
) -> float | None:
    selected = [
        record
        for record in records
        if record["target"]["clip_state"] == state
    ]
    if not selected:
        return None
    correct = sum(
        isinstance(record.get("prediction"), Mapping)
        and record["prediction"].get("clip_state") == state
        for record in selected
    )
    return correct / len(selected)


def summarize(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    recalls = {state: _recall(records, state) for state in FOUR_STATES}
    if any(value is None for value in recalls.values()):
        raise StageBGateError("评测子集没有覆盖全部四个状态，无法计算固定宏召回")
    fracture_macro = sum(float(recalls[state]) for state in FRACTURE_STATES) / 3
    four_macro = sum(float(recalls[state]) for state in FOUR_STATES) / 4
    strict_valid = sum(record.get("strict_valid") is True for record in records)
    runtime_failures = sum(bool(record.get("runtime_error")) for record in records)
    joint = sum(
        bool((record.get("scores") or {}).get("joint_correct"))
        for record in records
    )
    return {
        "sample_count": len(records),
        "clip_state_recall": {
            state: round(float(recalls[state]), 6) for state in FOUR_STATES
        },
        "fracture_three_state_macro_recall": round(fracture_macro, 6),
        "four_state_macro_recall": round(four_macro, 6),
        "已断裂_recall": round(float(recalls["已断裂"]), 6),
        "未断裂_recall": round(float(recalls["未断裂"]), 6),
        "joint_correct_rate": round(joint / len(records), 6),
        "strict_valid_rate": round(strict_valid / len(records), 6),
        "runtime_failure_count": runtime_failures,
    }


def _primary_improvement(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    deltas = {
        name: round(float(candidate[name]) - float(baseline[name]), 6)
        for name in PRIMARY_IMPROVEMENT_METRICS
    }
    return {
        "definition": "arithmetic_mean_pp_delta_of_primary_recall_metrics",
        "metrics": list(PRIMARY_IMPROVEMENT_METRICS),
        "deltas": deltas,
        "aggregate": round(sum(deltas.values()) / len(deltas), 6),
    }


def _source_error_analysis(
    records: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["source_video"])].append(record)
    rows = []
    for source, source_records in sorted(grouped.items()):
        targets = Counter(
            str(record["target"]["clip_state"]) for record in source_records
        )
        predictions = Counter(
            str(record["prediction"]["clip_state"])
            if isinstance(record.get("prediction"), Mapping)
            else "__invalid__"
            for record in source_records
        )
        state_errors = sum(
            not isinstance(record.get("prediction"), Mapping)
            or record["prediction"].get("clip_state")
            != record["target"]["clip_state"]
            for record in source_records
        )
        joint_errors = sum(
            not bool((record.get("scores") or {}).get("joint_correct"))
            for record in source_records
        )
        rows.append(
            {
                "source_video": source,
                "sample_count": len(source_records),
                "target_distribution": dict(sorted(targets.items())),
                "prediction_distribution": dict(sorted(predictions.items())),
                "clip_state_error_count": state_errors,
                "joint_error_count": joint_errors,
                "strict_invalid_count": sum(
                    record.get("strict_valid") is not True
                    for record in source_records
                ),
                "runtime_failure_count": sum(
                    bool(record.get("runtime_error"))
                    for record in source_records
                ),
            }
        )
    return rows


def _absolute_gate_results(summary: Mapping[str, Any]) -> dict[str, Any]:
    results = {}
    for name, threshold in ABSOLUTE_GATES.items():
        value = summary[name]
        if name == "runtime_failure_count":
            passed = int(value) == int(threshold)
            comparison = "equals"
        else:
            passed = float(value) >= float(threshold)
            comparison = "at_least"
        results[name] = {
            "value": value,
            "comparison": comparison,
            "threshold": threshold,
            "passed": passed,
        }
    return results


def _loso_analysis(
    baseline_records: list[Mapping[str, Any]],
    seed_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    sources = sorted({str(record["source_video"]) for record in baseline_records})
    baseline_full = summarize(baseline_records)
    seed_full = summarize(seed_records)
    full_improvement = _primary_improvement(seed_full, baseline_full)
    full_aggregate = float(full_improvement["aggregate"])
    if full_aggregate <= 0:
        return {
            "full_improvement": full_improvement,
            "minimum_retention": None,
            "required_minimum_retention": MIN_LOSO_IMPROVEMENT_RETENTION,
            "passed": False,
            "reason": "full_primary_aggregate_improvement_not_positive",
            "sources": [],
        }
    rows = []
    for source in sources:
        baseline_subset = [
            record
            for record in baseline_records
            if record["source_video"] != source
        ]
        seed_subset = [
            record for record in seed_records if record["source_video"] != source
        ]
        if {
            str(record["candidate_id"]) for record in baseline_subset
        } != {str(record["candidate_id"]) for record in seed_subset}:
            raise StageBGateError(f"LOSO {source}: baseline/seed candidate 集不一致")
        baseline_summary = summarize(baseline_subset)
        seed_summary = summarize(seed_subset)
        improvement = _primary_improvement(seed_summary, baseline_summary)
        retention = float(improvement["aggregate"]) / full_aggregate
        rows.append(
            {
                "removed_source": source,
                "remaining_sample_count": len(seed_subset),
                "improvement": improvement,
                "retention": round(retention, 6),
                "passed": retention >= MIN_LOSO_IMPROVEMENT_RETENTION,
            }
        )
    minimum = min(float(row["retention"]) for row in rows)
    return {
        "full_improvement": full_improvement,
        "minimum_retention": round(minimum, 6),
        "required_minimum_retention": MIN_LOSO_IMPROVEMENT_RETENTION,
        "passed": all(bool(row["passed"]) for row in rows),
        "sources": rows,
    }


def analyze(
    *,
    baseline_path: Path,
    seed_paths: Mapping[int, Path],
) -> dict[str, Any]:
    baseline_records = _read_records(baseline_path)
    baseline_ids = {str(record["candidate_id"]) for record in baseline_records}
    baseline_summary = summarize(baseline_records)
    seed_reports = []
    for seed in SEEDS:
        path = seed_paths[seed]
        records = _read_records(path)
        if {str(record["candidate_id"]) for record in records} != baseline_ids:
            raise StageBGateError(
                f"seed{seed}: 与旧正式 fold0 candidate 集不一致"
            )
        summary = summarize(records)
        gates = _absolute_gate_results(summary)
        loso = _loso_analysis(baseline_records, records)
        seed_reports.append(
            {
                "seed": seed,
                "records_path": str(path.resolve()),
                "records_sha256": _sha256(path),
                "metrics": summary,
                "absolute_gates": gates,
                "source_error_analysis": _source_error_analysis(records),
                "leave_one_source_out": loso,
                "passed": (
                    all(bool(item["passed"]) for item in gates.values())
                    and bool(loso["passed"])
                ),
            }
        )
    mean_metrics = {
        name: round(
            sum(float(report["metrics"][name]) for report in seed_reports)
            / len(seed_reports),
            6,
        )
        for name in (
            "fracture_three_state_macro_recall",
            "four_state_macro_recall",
            "已断裂_recall",
            "未断裂_recall",
            "joint_correct_rate",
            "strict_valid_rate",
        )
    }
    return {
        "schema_version": "tensile-vlm-v4.1-source-aware-3k-gates/v1",
        "run_id": RUN_ID,
        "release_id": RELEASE_ID,
        "baseline": {
            "run_id": BASELINE_RUN_ID,
            "records_path": str(baseline_path.resolve()),
            "records_sha256": _sha256(baseline_path),
            "metrics": baseline_summary,
        },
        "gate_policy": {
            "absolute_gates": ABSOLUTE_GATES,
            "primary_improvement_metrics": list(PRIMARY_IMPROVEMENT_METRICS),
            "primary_aggregate_definition": (
                "arithmetic mean of candidate-minus-baseline deltas for "
                "fracture three-state macro recall, four-state macro recall, "
                "and 已断裂 recall"
            ),
            "minimum_loso_improvement_retention": (
                MIN_LOSO_IMPROVEMENT_RETENTION
            ),
            "both_seeds_must_pass": True,
        },
        "seeds": seed_reports,
        "two_seed_mean_metrics": mean_metrics,
        "passed": all(bool(report["passed"]) for report in seed_reports),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-records",
        type=Path,
        default=BASELINE_ROOT / "evaluation_records.jsonl",
    )
    parser.add_argument(
        "--seed3407-records",
        type=Path,
        default=RESULT_ROOT / "seed3407/fold0/evaluation_records.jsonl",
    )
    parser.add_argument(
        "--seed3411-records",
        type=Path,
        default=RESULT_ROOT / "seed3411/fold0/evaluation_records.jsonl",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=RESULT_ROOT / "stage_b_gate_report.json",
    )
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = analyze(
        baseline_path=args.baseline_records,
        seed_paths={
            3407: args.seed3407_records,
            3411: args.seed3411_records,
        },
    )
    if not args.validate_only:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
