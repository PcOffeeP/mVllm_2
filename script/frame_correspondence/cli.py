"""CLI entrypoint for DEC-005 frame-correspondence evidence extraction."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .evidence import count_candidate_runs, extract_evidence_bundle
from .loader import (
    filter_records,
    load_input_records,
    load_roi_manifest,
    load_subvideo_manifest,
)
from .schema import EvidenceError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m script.frame_correspondence",
        description=(
            "DEC-005 standalone frame-correspondence evidence extraction CLI. "
            "Consumes five-label-input-record/3 JSONL and writes per-run manual visual "
            "evidence manifests and optional same-moment PNGs outside Git."
        ),
    )
    parser.add_argument(
        "--input-records",
        required=True,
        help="Path to five-label-input-record/3 JSONL file.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory OUTSIDE the Git repository for evidence_manifest.json, index.md, and PNGs.",
    )
    parser.add_argument(
        "--clip-id",
        action="append",
        dest="clip_ids",
        help="Filter to specific candidate_id / clip_id (repeatable).",
    )
    parser.add_argument(
        "--run-id",
        action="append",
        dest="run_ids",
        help="Filter to specific run_id when present in input records (repeatable).",
    )
    parser.add_argument(
        "--subvideo-manifest",
        help="Optional subvideo manifest.json for binding clip_identity and batch audit_tier/limitations.",
    )
    parser.add_argument(
        "--roi-manifest",
        help="Optional ROI manifest.json for binding ROI metadata.",
    )
    parser.add_argument(
        "--media-root",
        help="Optional root directory to locate L0/L1/L2/L3 media files when paths are relative or relocated.",
    )
    parser.add_argument(
        "--l3-frames-dir",
        help="Optional directory holding pre-extracted L3 model-input PNGs (<dir>/<candidate_id>/<image>).",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--extract-images",
        action="store_true",
        help="Extract L0/L1/L2 frames and copy L3 images when available (default mode).",
    )
    mode_group.add_argument(
        "--metadata-only",
        action="store_true",
        help="Resolve four-layer metadata, digests, and proof boundaries without decoding videos or copying PNGs.",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "ffmpeg", "opencv"),
        default="auto",
        help="Video decoding backend when extracting images (default: auto).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    mode = "metadata_only" if args.metadata_only else "extract_images"

    try:
        input_path = Path(args.input_records)
        records = load_input_records(input_path)
        all_run_counts = count_candidate_runs(records)
        selected = filter_records(records, clip_ids=args.clip_ids, run_ids=args.run_ids)

        sv_manifest = load_subvideo_manifest(args.subvideo_manifest) if args.subvideo_manifest else None
        roi_manifest = load_roi_manifest(args.roi_manifest) if args.roi_manifest else None
        media_root = Path(args.media_root) if args.media_root else None
        l3_frames_dir = Path(args.l3_frames_dir) if args.l3_frames_dir else None

        run_index = extract_evidence_bundle(
            selected,
            output_dir=Path(args.output_dir),
            mode=mode,
            backend=args.backend,
            subvideo_manifest=sv_manifest,
            roi_manifest=roi_manifest,
            media_root=media_root,
            l3_frames_dir=l3_frames_dir,
            input_records_dir=input_path.parent,
            candidate_run_counts=all_run_counts,
        )
    except (EvidenceError, OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    total_extracted = sum(e["extraction_summary"]["extracted_count"] for e in run_index["entries"])
    total_copied = sum(e["extraction_summary"]["copied_count"] for e in run_index["entries"])
    total_skipped = sum(e["extraction_summary"]["skipped_count"] for e in run_index["entries"])
    print(
        f"Wrote DEC-005 evidence ({run_index['schema']}): "
        f"{run_index['records_processed']} record(s) under {run_index['output_dir']} "
        f"[mode={mode}, extracted={total_extracted}, copied={total_copied}, skipped={total_skipped}; "
        f"proof_strength={run_index['proof_strength']}, replaces_full_receipt=false]"
    )
    return 0
