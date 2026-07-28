#!/usr/bin/env python3
"""Migrate a validated v4 draft into a queue-bound v4.1 draft."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.v4_1_review_workflow import (
    load_review_queue,
    migrate_v4_decisions,
    save_draft,
    sha256_file,
)
from pipeline.v4_review_decisions import validate_review_payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v4-draft", type=Path, required=True)
    parser.add_argument("--v4-1-queue", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.v4_draft.read_text(encoding="utf-8"))
    decisions = source.get("decisions")
    validate_review_payload(
        {
            "schema_version": "tensile-review-decision/v4",
            "label_schema_version": source.get("label_schema_version"),
            "batch_id": "migration-validation",
            "created_at": source.get("updated_at"),
            "decisions": decisions,
        }
    )
    identity, candidates = load_review_queue(
        args.v4_1_queue, project_root=args.project_root
    )
    migrated, conflicts = migrate_v4_decisions(
        decisions, candidates, source_sha256=sha256_file(args.v4_draft)
    )
    if conflicts:
        raise SystemExit(json.dumps(conflicts, ensure_ascii=False, indent=2))
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
