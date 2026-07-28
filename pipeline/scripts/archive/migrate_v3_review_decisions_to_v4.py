#!/usr/bin/env python3
"""Migrate a validated v3 review draft into a queue-bound v4 draft."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.v3_review_decisions import validate_review_payload as validate_v3_payload
from pipeline.v4_review_workflow import (
    load_review_queue,
    migrate_v3_decisions,
    save_draft,
    sha256_file,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v3-draft", type=Path, required=True)
    parser.add_argument("--v4-queue", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.v3_draft.read_text(encoding="utf-8"))
    decisions = source.get("decisions")
    validate_v3_payload(
        {
            "schema_version": "tensile-review-decision/v3",
            "label_schema_version": source.get("label_schema_version"),
            "batch_id": "migration-validation",
            "created_at": source.get("updated_at"),
            "decisions": decisions,
        }
    )
    identity, candidates = load_review_queue(
        args.v4_queue, project_root=args.project_root
    )
    migrated, conflicts = migrate_v3_decisions(
        decisions,
        candidates,
        source_sha256=sha256_file(args.v3_draft),
    )
    if conflicts:
        report = args.output.with_name("migration_conflicts.json")
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(conflicts, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise SystemExit(f"迁移存在 {len(conflicts)} 条冲突: {report}")
    payload = save_draft(args.output, identity, migrated)
    print(
        json.dumps(
            {
                "migrated_count": payload["reviewed_count"],
                "remaining_count": payload["remaining_count"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
