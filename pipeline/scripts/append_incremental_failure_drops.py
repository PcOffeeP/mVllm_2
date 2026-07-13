#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append explicit dropped decisions for selected incremental media failures."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_failure_drops(
    baseline_path: Path,
    delta_path: Path,
    queue_path: Path,
    report_path: Path,
    output_path: Path,
    note: str,
) -> dict[str, int]:
    baseline = {item["subvideo_id"]: item for item in _load(baseline_path)["decisions"]}
    queue_ids = set(_load(queue_path)["incremental_review_queue"]["queue_ids"])
    delta_payload = _load(delta_path)
    if delta_payload.get("decision_mode") != "incremental_delta":
        raise ValueError("delta 必须是 incremental_delta 文件")
    decisions = {item["subvideo_id"]: item for item in delta_payload.get("decisions", [])}
    failures = _load(report_path).get("failures", [])
    failure_ids: set[str] = set()
    added = 0
    for failure in failures:
        sid = failure.get("subvideo_id")
        if not isinstance(sid, str) or sid not in queue_ids:
            raise ValueError(f"失败报告含非队列 ID: {sid}")
        if sid in decisions:
            raise ValueError(f"失败样本已存在 delta 决策: {sid}")
        old = baseline.get(sid)
        if old is None or old.get("status") != "needs_regenerate":
            raise ValueError(f"{sid}: 只能把 baseline needs_regenerate 标为 dropped")
        decisions[sid] = {
            "subvideo_id": sid,
            "status": "dropped",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer_notes": f"{note}; generation_failure={failure.get('reason')}",
            "corrected_labels": None,
            "original_labels": old.get("original_labels"),
            "baseline_decision": old,
        }
        failure_ids.add(sid)
        added += 1
    output = dict(delta_payload)
    output["decisions"] = [decisions[sid] for sid in sorted(decisions)]
    materialized_ids = set(output.get("materialized_queue_ids") or output.get("queue_ids") or [])
    reviewed_ids = set(decisions) - failure_ids
    output["materialized_queue_ids"] = sorted(materialized_ids)
    output["reviewed_ids"] = sorted(reviewed_ids)
    output["unreviewed_ids"] = sorted(materialized_ids - reviewed_ids)
    output["failure_drop_append"] = {
        "added": added,
        "failure_dropped_ids": sorted(failure_ids),
        "report": str(report_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"total": len(decisions), "added_dropped": added}


def main() -> int:
    parser = argparse.ArgumentParser(description="将增量生成失败样本显式追加为 dropped delta")
    parser.add_argument("--round", required=True, help="本轮标识，如 round_01；多轮流程必须显式指定")
    parser.add_argument("--baseline", type=Path, default=PROJECT_ROOT / "data/07_metadata/review_decisions/subvideo_train_review_decisions.json")
    parser.add_argument("--delta", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--queue", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--report", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--output", type=Path, default=None, help="默认按 --round 推导")
    parser.add_argument("--note", default="用户决定：源事件更新后无法形成可审查候选，剔除旧样本")
    args = parser.parse_args()
    round_dir = PROJECT_ROOT / "data/07_metadata/incremental_review" / args.round
    summary = append_failure_drops(
        baseline_path=args.baseline,
        delta_path=args.delta or round_dir / "incremental_review_delta_decisions.json",
        queue_path=args.queue or round_dir / "incremental_review_queue_metadata.json",
        report_path=args.report or round_dir / f"incremental_review_{args.round}_report.json",
        output_path=args.output or round_dir / "incremental_review_delta_decisions_resolved.json",
        note=args.note,
    )
    print(f"写出 delta: {summary['total']} 条，新增 dropped {summary['added_dropped']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
