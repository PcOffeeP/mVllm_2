"""Convert the sub-video manifest into an identity-only five-label scoring manifest.

Only identity and digests are copied; no label, review or media byte is inferred.
Samples are explicitly ``source_type: "real"`` and that decision is printed, because the
source manifest has no ``source_type`` field.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

from .exclusions import DevExclusions, load_candidate_selection, load_dev_exclusions
from .score import InputError, decode_file, prepare, require_text

SOURCE_TYPE = "real"
CONVERSION_SCHEMA = "five-label-manifest-conversion/1"
SHA256 = re.compile(r"[a-f0-9]{64}")
SOURCE_ID = re.compile(r"video_\d+")


def _candidates(manifest_obj):
    rows = manifest_obj.get("candidates") if isinstance(manifest_obj, dict) else None
    if not isinstance(rows, list):
        raise InputError("source manifest must contain candidates array")
    by_id = {}
    for row in rows:
        if not isinstance(row, dict):
            raise InputError("source manifest candidate must be object")
        require_text(row, "candidate_id", "source manifest candidate")
        if row["candidate_id"] in by_id:
            raise InputError(f"duplicate candidate_id in source manifest: {row['candidate_id']}")
        by_id[row["candidate_id"]] = row
    return by_id


def source_type_rationale(manifest_obj) -> str:
    """Explain the source_type decision; refuse to silently assume real data."""
    _candidates(manifest_obj)
    rows = manifest_obj["candidates"]
    bad = sorted({str(row.get("source_video_id")) for row in rows
                  if not isinstance(row.get("source_video_id"), str)
                  or not SOURCE_ID.fullmatch(row["source_video_id"])})
    if bad:
        raise InputError(f"cannot assert source_type={SOURCE_TYPE}: unexpected source_video_id "
                         rf"{bad[:5]}; expected ^video_\d+$")
    return (f"清单无 source_type 字段；{len(rows)} 条候选的 source_video_id 全部匹配 "
            rf"^video_\d+$，为真实源，故 source_type={SOURCE_TYPE}。判定只依据来源标识形态。")


def convert(manifest_obj, manifest_bytes, candidate_ids=None, limit=None, manifest_version=None,
            *, exclusions: DevExclusions | None = None, enforce_exclusions: bool = True) -> dict:
    by_id = _candidates(manifest_obj)
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
        raise InputError("limit must be a positive integer")
    active_exclusions = (
        (exclusions if exclusions is not None else load_dev_exclusions())
        if enforce_exclusions else None
    )
    filtered_count = 0
    selected = list(by_id)
    if candidate_ids is not None:
        if not isinstance(candidate_ids, list) or not candidate_ids:
            raise InputError("candidate_ids must be a nonempty list")
        for cid in candidate_ids:
            require_text({"candidate_id": cid}, "candidate_id", "candidate_ids")
        duplicated = sorted(cid for cid, count in Counter(candidate_ids).items() if count > 1)
        if duplicated:
            raise InputError(f"duplicate candidate_id in candidate_ids: {duplicated}")
        missing = [cid for cid in candidate_ids if cid not in by_id]
        if missing:
            raise InputError(f"candidate_id not found in source manifest: {missing}")
        if active_exclusions is not None:
            active_exclusions.assert_no_excluded(
                [by_id[cid] for cid in candidate_ids],
                context="manifest_convert candidate_ids",
            )
        selected = list(candidate_ids)
    elif active_exclusions is not None:
        kept, removed = active_exclusions.filter_candidates([by_id[cid] for cid in selected])
        filtered_count = len(removed)
        selected = [row["candidate_id"] for row in kept]
    if limit is not None:
        selected = selected[:limit]
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    version = manifest_version if manifest_version is not None else f"manifest@sha256:{digest}"
    require_text({"manifest_version": version}, "manifest_version", "converted manifest")
    samples = []
    for cid in selected:
        output = by_id[cid].get("output")
        clip = output.get("sha256") if isinstance(output, dict) else None
        if not isinstance(clip, str) or not SHA256.fullmatch(clip):
            raise InputError(f"{cid}: output.sha256 must be lowercase SHA256")
        require_text(by_id[cid], "source_video_id", cid)
        samples.append({"manifest_sha256": digest, "candidate_id": cid, "clip_sha256": clip,
                        "source_id": by_id[cid]["source_video_id"], "source_type": SOURCE_TYPE,
                        "review_id": None})
    result = {"manifest_version": version, "samples": samples,
              "source_type_decision": {"source_type": SOURCE_TYPE, "candidate_count": len(by_id),
                                       "schema": CONVERSION_SCHEMA, "source_schema": manifest_obj.get("schema"),
                                       "rationale": source_type_rationale(manifest_obj)}}
    if active_exclusions is not None:
        result["dev_exclusions"] = active_exclusions.metadata(filtered_count=filtered_count)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Source sub-video manifest JSON")
    parser.add_argument("--output", required=True, help="New scoring manifest JSON; never overwrites")
    parser.add_argument("--candidate-ids", help="JSON array or frozen eval-subset JSON of candidate IDs in the wanted order")
    parser.add_argument("--limit", type=int, help="Keep only the first N selected candidates")
    parser.add_argument("--manifest-version", help="Batch identity; defaults to the manifest digest")
    parser.add_argument("--exclusions", help="DEC-007 dev-exclusions JSON; defaults to data/splits/dev-exclusions.json")
    parser.add_argument("--allow-excluded", action="store_true", help="Disable DEC-007 exclusion guard (forensic use only)")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.input).read_bytes()
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        ids = Path(args.candidate_ids) if args.candidate_ids else None
        selection = load_candidate_selection(ids) if ids else None
        if selection is not None:
            selection.assert_manifest_sha256(raw_sha256, context="manifest_convert")
        candidate_ids = selection.candidate_ids if selection is not None else None
        exclusions = None if args.allow_excluded else load_dev_exclusions(args.exclusions)
        draft = convert(decode_file(raw.decode("utf-8"), args.input), raw, candidate_ids=candidate_ids,
                        limit=args.limit, manifest_version=args.manifest_version,
                        exclusions=exclusions, enforce_exclusions=not args.allow_excluded)
        draft["input_files"] = {"source_manifest": {"path": args.input, "sha256": raw_sha256}}
        with Path(args.output).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
        prepare(draft, [], [], exclusions=exclusions, enforce_exclusions=not args.allow_excluded)  # Scorer-side validation of the written draft.
        print(f"Wrote {args.output}; samples={len(draft['samples'])}; version={draft['manifest_version']}")
        print(draft["source_type_decision"]["rationale"])
        return 0
    except (InputError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
