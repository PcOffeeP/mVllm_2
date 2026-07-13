#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safely merge an incremental-review delta into immutable baseline decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGAL_STATUSES = {"approved", "dropped", "needs_regenerate"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decision_list(payload: Any) -> list[dict[str, Any]]:
    records = payload.get("decisions", []) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("决策文件必须含 decisions 列表")
    return records


def merge_incremental_review_decisions(
    baseline_path: Path,
    delta_path: Path,
    queue_path: Path,
    output_path: Path,
    allow_approved_supersede: bool = False,
) -> dict[str, int]:
    queue = _load(queue_path)
    queue_info = queue.get("incremental_review_queue", {}) if isinstance(queue, dict) else {}
    queue_ids = set(queue_info.get("queue_ids", []))
    if not queue_ids:
        raise ValueError("队列缺少 queue_ids")
    expected_hash = (queue_info.get("input_sha256") or {}).get("baseline_decisions")
    if expected_hash and _sha256(baseline_path) != expected_hash:
        raise ValueError("baseline 决策哈希与复审队列不一致；请重新生成队列")

    baseline = _decision_list(_load(baseline_path))
    delta_payload = _load(delta_path)
    if isinstance(delta_payload, dict) and delta_payload.get("decision_mode") != "incremental_delta":
        raise ValueError("delta 文件不是 incremental_delta 模式输出")
    delta = _decision_list(delta_payload)
    base_by_id = {record.get("subvideo_id"): record for record in baseline}
    if len(base_by_id) != len(baseline):
        raise ValueError("baseline 存在重复或缺失 subvideo_id")

    replacement: dict[str, dict[str, Any]] = {}
    for record in delta:
        sid = record.get("subvideo_id")
        if not isinstance(sid, str) or sid not in queue_ids:
            raise ValueError(f"delta 包含非队列 subvideo_id: {sid}")
        if sid in replacement:
            raise ValueError(f"delta 存在重复 subvideo_id: {sid}")
        if record.get("status") not in LEGAL_STATUSES:
            raise ValueError(f"{sid}: delta status 非法或未完成")
        old = base_by_id.get(sid)
        if old is None:
            raise ValueError(f"{sid}: 不在 baseline 决策中")
        if old.get("status") == "approved" and not allow_approved_supersede:
            raise ValueError(f"{sid}: 不允许覆盖历史 approved；请显式传入 --allow-approved-supersede")
        if old.get("status") == "approved" and not str(record.get("reviewer_notes", "")).strip():
            raise ValueError(f"{sid}: 覆盖 approved 必须填写 reviewer_notes")
        replacement[sid] = record

    merged = [replacement.get(record["subvideo_id"], record) for record in baseline]
    payload = {
        "decisions": merged,
        "incremental_merge": {
            "baseline_sha256": _sha256(baseline_path),
            "queue_sha256": _sha256(queue_path),
            "delta_sha256": _sha256(delta_path),
            "replaced_count": len(replacement),
            "allow_approved_supersede": allow_approved_supersede,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"total": len(merged), "replaced": len(replacement)}


def main() -> int:
    parser = argparse.ArgumentParser(description="安全合并增量复审 delta 决策")
    parser.add_argument("--baseline", type=Path, default=PROJECT_ROOT / "data/07_metadata/review_decisions/subvideo_train_review_decisions.json")
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/07_metadata/subvideo_train_review_decisions_final.json")
    parser.add_argument("--allow-approved-supersede", action="store_true")
    args = parser.parse_args()
    summary = merge_incremental_review_decisions(
        baseline_path=args.baseline,
        delta_path=args.delta,
        queue_path=args.queue,
        output_path=args.output,
        allow_approved_supersede=args.allow_approved_supersede,
    )
    print(f"写出合并决策: {summary['total']} 条，替换 {summary['replaced']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
