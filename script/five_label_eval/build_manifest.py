"""Copy explicitly selected review identities into a new, unfrozen manifest draft."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from .exclusions import DevExclusions, load_candidate_selection, load_dev_exclusions
from .score import IDENTITY, InputError, decode_file, prepare, require_text, validate_identity

DRAFT_VERSION = "five-label-manifest-draft/1"


def build_draft(reviews, candidate_ids, manifest_version, *, exclusions: DevExclusions | None = None,
                enforce_exclusions: bool = True):
    """Use one supplied current row per candidate; never choose a review revision."""
    require_text({"manifest_version": manifest_version}, "manifest_version", "draft")
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise InputError("candidate IDs must be a nonempty JSON array")
    for cid in candidate_ids:
        require_text({"candidate_id": cid}, "candidate_id", "candidate IDs")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise InputError("duplicate candidate ID in explicit selection")
    by_id = {}
    for row in reviews:
        if not isinstance(row, dict):
            raise InputError("review export row must be object")
        validate_identity(row, "review export")
        cid = row["candidate_id"]
        if cid in by_id:
            raise InputError(f"duplicate candidate ID in review export: {cid}; supply current decisions, not revision history")
        by_id[cid] = row
    missing = [cid for cid in candidate_ids if cid not in by_id]
    if missing:
        raise InputError(f"selected candidate IDs missing from review export: {missing}")
    active_exclusions = None
    if enforce_exclusions:
        active_exclusions = exclusions if exclusions is not None else load_dev_exclusions()
        active_exclusions.assert_no_excluded([by_id[cid] for cid in candidate_ids], context="build_manifest candidate_ids")
    samples = []
    for cid in candidate_ids:
        row = by_id[cid]
        # A missing review_id cannot be inferred as an unreviewed placeholder.
        if "review_id" not in row:
            raise InputError(f"{cid}: review export missing review_id")
        samples.append({**{key: row[key] for key in IDENTITY}, "review_id": row["review_id"],
                        "review_status": row.get("review_status")})
    draft = {"manifest_version": manifest_version, "draft_schema": DRAFT_VERSION,
             "draft_status": "identity_snapshot_not_frozen", "samples": samples}
    # Reuse scorer identity/state validation; no prediction, media or model is used.
    prepare(draft, reviews, [], exclusions=active_exclusions, enforce_exclusions=enforce_exclusions)
    counts = dict(Counter(s["review_status"] for s in samples))
    not_confirmed = [{"candidate_id": s["candidate_id"], "review_status": s["review_status"],
                      "review_id": s["review_id"]} for s in samples if s["review_status"] != "confirmed"]
    draft["review_status_counts"] = counts
    draft["not_confirmed"] = not_confirmed
    draft["notice"] = ("测评清单草稿／身份快照，尚未正式冻结；未确认项目不构成已审核真值。"
                       "候选选择、test／虚拟数据使用与正式测评仍需对应授权。")
    return draft


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", required=True, help="Current-decisions JSONL export, one row per candidate")
    parser.add_argument("--candidate-ids", required=True, help="JSON array or frozen eval-subset JSON of selected candidate IDs")
    parser.add_argument("--manifest-version", required=True, help="User-specified manifest identity")
    parser.add_argument("--output", required=True, help="New JSON file; never overwrites")
    parser.add_argument("--exclusions", help="DEC-007 dev-exclusions JSON; defaults to data/splits/dev-exclusions.json")
    parser.add_argument("--allow-excluded", action="store_true", help="Disable DEC-007 exclusion guard (forensic use only)")
    args = parser.parse_args(argv)
    try:
        export_bytes = Path(args.reviews).read_bytes()
        ids_bytes = Path(args.candidate_ids).read_bytes()
        reviews = []
        for number, line in enumerate(export_bytes.decode("utf-8").splitlines(), 1):
            if line.strip():
                row = decode_file(line, f"{args.reviews}:{number}")
                if not isinstance(row, dict):
                    raise InputError(f"{args.reviews}:{number}: expected review object")
                reviews.append(row)
        selection = load_candidate_selection(args.candidate_ids)
        candidate_ids = selection.candidate_ids
        exclusions = None if args.allow_excluded else load_dev_exclusions(args.exclusions)
        draft = build_draft(reviews, candidate_ids, args.manifest_version,
                            exclusions=exclusions, enforce_exclusions=not args.allow_excluded)
        for sample in draft["samples"]:
            selection.assert_manifest_sha256(
                sample["manifest_sha256"],
                context=f"build_manifest:{sample['candidate_id']}",
            )
        draft["input_files"] = {
            "reviews": {"path": args.reviews, "sha256": hashlib.sha256(export_bytes).hexdigest()},
            "candidate_ids": {"path": args.candidate_ids, "sha256": hashlib.sha256(ids_bytes).hexdigest()},
        }
        serialized = json.dumps(draft, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with Path(args.output).open("x", encoding="utf-8") as stream:
            stream.write(serialized)
        print(f"Wrote draft {args.output}; samples={len(draft['samples'])}; review_status_counts={json.dumps(draft['review_status_counts'], ensure_ascii=False)}")
        print(draft["notice"])
        for row in draft["not_confirmed"]:
            print(f"NOT CONFIRMED: {row['candidate_id']} / {row['review_status']} / review_id={row['review_id']}")
        return 0
    except (InputError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
