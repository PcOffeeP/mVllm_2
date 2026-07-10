#!/usr/bin/env python3
"""Generate subvideo-based test artifacts for inference.

This script integrates with the review UI workflow:

1. It reads subvideo metadata (default: ``test_subvideos_meta.label_reviewed.json``
   if it exists, otherwise ``test_subvideos_meta.json``).
2. Use ``--metadata`` to explicitly point to another metadata file.
3. In ``--strict`` mode (default), it blocks on ``unreviewed`` or
   ``needs_regenerate`` samples and only exports ``approved`` samples.
4. ``dropped`` samples are excluded from evaluation inputs and ground truth.
5. In ``--strict`` mode (default), the input metadata must already contain
   ``review_status`` fields produced by the review UI. If no review status is
   present, the script exits with an error. In ``--no-strict`` mode, metadata
   without reviews is allowed as a compatibility fallback and all subvideos are
   exported with a warning.
6. When review information is present, ``review_status`` and
   ``reviewer_notes`` are preserved in the ground truth file for
   downstream evaluation analysis.

If the chosen metadata file does not exist, the script falls back to
regenerating subvideos from ``video_meta.json`` (legacy behavior) and
writes the metadata to ``--manifest``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.scripts import subvideo_builder as builder

VIDEO_META_DEFAULT = ROOT / "data" / "07_metadata" / "video_meta.json"
SPLITS_DIR_DEFAULT = ROOT / "data" / "05_splits"
MERGED_DIR_DEFAULT = ROOT / "data" / "06_merged"
MANIFEST_DEFAULT = ROOT / "data" / "07_metadata" / "test_subvideos_meta.json"
LABEL_REVIEWED_META = ROOT / "data" / "07_metadata" / "test_subvideos_meta.label_reviewed.json"
RAW_META_DEFAULT = ROOT / "data" / "07_metadata" / "test_subvideos_meta.json"


STATUS_APPROVED = "approved"
STATUS_DROPPED = "dropped"
STATUS_NEEDS_REGENERATE = "needs_regenerate"
STATUS_UNREVIEWED = "unreviewed"


def _default_metadata_path(strict: bool) -> Path:
    """Return the default metadata path.

    In strict mode, only the label-reviewed metadata is acceptable; if it is
    missing, the caller must raise rather than silently fall back to raw
    metadata. In non-strict mode, fall back to the raw metadata when the
    reviewed file does not exist.
    """
    if LABEL_REVIEWED_META.exists():
        return LABEL_REVIEWED_META
    if not strict:
        return RAW_META_DEFAULT
    return LABEL_REVIEWED_META


def _load_subvideos_from_metadata(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read subvideo metadata; supports a top-level dict or a plain list."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw.get("subvideos", []), raw
    return raw, {}


def _metadata_has_reviews(subvideos: list[dict[str, Any]]) -> bool:
    """Return True if any subvideo record carries a review_status field."""
    return any("review_status" in sub for sub in subvideos)


def _filter_subvideos_by_review(
    subvideos: list[dict[str, Any]],
    strict: bool,
) -> list[dict[str, Any]]:
    """Keep only approved subvideos; drop dropped ones.

    In strict mode, the input metadata must already contain review_status
    fields from the UI review workflow. If no review status is present at all,
    the script raises. Any sample whose review_status is not ``approved`` or
    ``dropped`` (e.g. ``unreviewed`` or ``needs_regenerate``) also raises.

    In non-strict mode, metadata without reviews is allowed as a compatibility
    fallback and all subvideos are exported with a warning. Non-approved samples
    are skipped with a warning rather than blocking.
    """
    if not _metadata_has_reviews(subvideos):
        if strict:
            raise RuntimeError(
                "Input metadata has no review_status. In strict mode, all test "
                "subvideos must be reviewed through the UI before export. "
                "Run the review UI first, or use --no-strict for debugging only."
            )
        print(
            "Warning: input metadata has no review_status; exporting all subvideos "
            "because --no-strict is set.",
            file=sys.stderr,
        )
        return subvideos

    approved: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []

    for sub in subvideos:
        status = sub.get("review_status")
        sid = sub.get("subvideo_id", "<unknown>")
        if status == STATUS_APPROVED:
            approved.append(sub)
        elif status == STATUS_DROPPED:
            continue
        else:
            skipped.append((sid, status or "unreviewed"))

    if strict and skipped:
        raise RuntimeError(
            f"--strict mode: {len(skipped)} subvideo(s) are not approved/dropped:\n"
            + "\n".join(f"  {sid}: {status}" for sid, status in skipped)
        )

    if skipped:
        print(
            f"Warning: skipping {len(skipped)} subvideo(s) with non-approved status:",
            file=sys.stderr,
        )
        for sid, status in skipped:
            print(f"  {sid}: {status}", file=sys.stderr)

    return approved


def _event_time(rec: dict[str, Any]) -> float | None:
    value = rec.get("event_time")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _data_path(path_value: Any) -> str:
    path = Path(str(path_value))
    if path.is_absolute() or str(path).startswith("data/"):
        return str(path)
    return f"data/{path}"


def _build_test_subvideos(
    rec: dict[str, Any],
    split_info: dict[str, Any],
    *,
    generate_media: bool,
    extract_frames: bool,
    preprocessor: builder.VideoPreprocessor | None,
) -> list[dict[str, Any]]:
    subvideos: list[dict[str, Any]] = []

    full = builder.build_full_subvideo(
        rec,
        split_info,
        generate_media=generate_media,
        extract_frames=extract_frames,
        preprocessor=preprocessor,
    )
    if full is not None:
        subvideos.append(full)

    rec_type = rec["type"]
    has_fracture = rec.get("has_fracture_canonical", rec.get("has_fracture"))

    if rec_type == builder.VIDEO_ANOMALY_TYPE:
        return subvideos

    if rec_type == "未夹紧" and builder._event_frame(rec) is not None:
        subvideos.extend(
            builder.build_focus_subvideos(
                rec,
                split_info,
                generate_media=generate_media,
                extract_frames=extract_frames,
                preprocessor=preprocessor,
            )
        )
        subvideos.extend(
            builder.build_neg_before_after(
                rec,
                split_info,
                generate_media=generate_media,
                extract_frames=extract_frames,
                preprocessor=preprocessor,
            )
        )
        return subvideos

    if rec_type == "未夹紧":
        return subvideos

    if rec_type == "未断裂" or has_fracture is False:
        subvideos.extend(
            builder.build_non_fracture_clips(
                rec,
                split_info,
                generate_media=generate_media,
                extract_frames=extract_frames,
                preprocessor=preprocessor,
            )
        )
        return subvideos

    if has_fracture is True and rec_type in builder.FRACTURE_TYPES:
        subvideos.extend(
            builder.build_focus_subvideos(
                rec,
                split_info,
                generate_media=generate_media,
                extract_frames=extract_frames,
                preprocessor=preprocessor,
            )
        )
        subvideos.extend(
            builder.build_neg_before_after(
                rec,
                split_info,
                generate_media=generate_media,
                extract_frames=extract_frames,
                preprocessor=preprocessor,
            )
        )

    return subvideos


def _input_record(sub: dict[str, Any]) -> dict[str, Any]:
    mapping = sub.get("actual_frame_mapping") or sub.get("sampled_frames") or []
    return {
        "id": sub["subvideo_id"],
        "video_id": sub["subvideo_id"],
        "subvideo_id": sub["subvideo_id"],
        "source_video_id": sub["source_video"],
        "video_path": _data_path(sub["video_path"]),
        "crop_type": sub.get("crop_type"),
        "start_time": sub.get("start_time"),
        "end_time": sub.get("end_time"),
        "frame_mapping": mapping,
        "processor_fingerprint": sub.get("processor_fingerprint"),
    }


def _ground_truth_record(sub: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    has_fracture = sub.get("has_fracture_canonical", sub.get("has_fracture"))
    event_time = _event_time(source) if has_fracture is True else None
    record: dict[str, Any] = {
        "video_id": sub["subvideo_id"],
        "subvideo_id": sub["subvideo_id"],
        "source_video_id": sub["source_video"],
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "is_abnormal": sub.get("is_abnormal", False),
        "is_abnormal_canonical": sub.get("is_abnormal", False),
        "video_anomaly_kind": source.get("video_anomaly_kind"),
        "event_time_reliable": bool(event_time is not None),
        "event_frame_original": source.get("event_frame_original"),
        "event_time": event_time,
        "type": sub.get("type"),
        "location": sub.get("location"),
        "location_canonical": sub.get("location_canonical"),
        "fracture_between": sub.get("fracture_between"),
        "crop_type": sub.get("crop_type"),
        "start_time": sub.get("start_time"),
        "end_time": sub.get("end_time"),
    }
    # Preserve review fields for downstream evaluation analysis.
    if "review_status" in sub:
        record["review_status"] = sub["review_status"]
    if "reviewer_notes" in sub:
        record["reviewer_notes"] = sub["reviewer_notes"]
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate subvideo test artifacts from reviewed or raw metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use the default reviewed metadata (if available) or raw metadata
  python scripts/generate_test_subvideo_artifacts.py

  # Explicitly use reviewed metadata
  python scripts/generate_test_subvideo_artifacts.py \\
      --metadata data/07_metadata/test_subvideos_meta.label_reviewed.json

  # Allow non-approved samples to be skipped without blocking (not for official eval)
  python scripts/generate_test_subvideo_artifacts.py --no-strict
        """.strip(),
    )
    parser.add_argument("--video-meta", type=Path, default=VIDEO_META_DEFAULT)
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR_DEFAULT)
    parser.add_argument("--merged-dir", type=Path, default=MERGED_DIR_DEFAULT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help="Input subvideo metadata path. "
             "Defaults to test_subvideos_meta.label_reviewed.json if it exists, "
             "otherwise test_subvideos_meta.json.",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Strict mode: require reviewed metadata and block export if any sample is "
             "unreviewed or needs_regenerate. Dropped samples are always skipped. "
             "(default: on)",
    )
    parser.add_argument(
        "--model",
        default=str(ROOT / "models" / "minicpmv4_5"),
        help="MiniCPM-V model directory used by the training preprocessor.",
    )
    parser.add_argument(
        "--preprocessor",
        choices=["minicpm"],
        default="minicpm",
    )
    parser.add_argument(
        "--extract-frames",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Extract sampled frame images alongside generated subvideos.",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Only write candidate metadata; do not create mp4/frame files.",
    )
    parser.add_argument(
        "--skip-healthcheck",
        action="store_true",
        help="Skip preprocessor healthcheck after loading it.",
    )
    return parser.parse_args()


def _generate_subvideos_from_split(
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[str], str]:
    """Generate subvideos from the test split when no metadata input exists."""
    if not args.video_meta.exists():
        raise FileNotFoundError(args.video_meta)
    split_path = args.splits_dir / "test.json"
    if not split_path.exists():
        raise FileNotFoundError(split_path)

    records = json.loads(args.video_meta.read_text(encoding="utf-8"))
    by_video_id = {rec["video_id"]: rec for rec in records}
    test_split = json.loads(split_path.read_text(encoding="utf-8"))
    test_ids = test_split.get("video_ids", [])
    missing = sorted(set(test_ids) - set(by_video_id))
    if missing:
        raise ValueError(f"test split video_id(s) missing from video_meta: {missing}")

    preprocessor = builder._create_preprocessor(
        args.preprocessor, builder.VIDEO_MAXLEN, args.model
    )
    if not args.skip_healthcheck and not preprocessor.healthcheck():
        info = preprocessor.get_info()
        raise RuntimeError(f"preprocessor healthcheck failed: {info.name} ({info.backend})")
    print(f"Using preprocessor fingerprint={preprocessor.fingerprint()}")

    builder.EXCLUSIONS.clear()
    generated: list[dict[str, Any]] = []
    for video_id in test_ids:
        rec = by_video_id[video_id]
        split_info = {
            "split": "test_subvideos",
            "fold": "test_subvideos",
            "fold_assignments": ["test_subvideos"],
        }
        print(f"Processing test video {video_id}")
        subs = _build_test_subvideos(
            rec,
            split_info,
            generate_media=not args.metadata_only,
            extract_frames=args.extract_frames,
            preprocessor=preprocessor,
        )
        generated.extend(subs)

    return generated, test_ids, preprocessor.fingerprint()


def main() -> int:
    args = parse_args()
    metadata_path = args.metadata or _default_metadata_path(strict=args.strict)

    if metadata_path.exists():
        print(f"Using existing subvideo metadata: {metadata_path}")
        generated, top_level = _load_subvideos_from_metadata(metadata_path)
        # Infer source test count from unique source videos in the metadata.
        test_ids = sorted({sub["source_video"] for sub in generated if "source_video" in sub})
        preprocessor_fingerprint = None
        exclusions: list[dict[str, Any]] = []
    elif args.metadata is not None:
        # Explicit --metadata was requested but the file is missing: do not silently fall back.
        raise FileNotFoundError(
            f"Requested metadata file does not exist: {metadata_path}\n"
            "If you want to generate subvideos from video_meta instead, "
            "omit --metadata or create the metadata first."
        )
    else:
        # Default metadata path was used and is missing.
        if args.strict:
            raise FileNotFoundError(
                f"Reviewed metadata file not found: {metadata_path}\n"
                "In strict mode, test subvideos must be reviewed through the UI "
                "before export. Use --no-strict for debugging only."
            )
        print(f"Metadata {metadata_path} not found; generating subvideos from {args.video_meta}")
        generated, test_ids, preprocessor_fingerprint = _generate_subvideos_from_split(args)
        top_level = {}
        exclusions = list(builder.EXCLUSIONS)

    # Apply review filtering. In strict mode, metadata without review_status raises.
    used_subvideos = _filter_subvideos_by_review(generated, strict=args.strict)

    if not args.video_meta.exists():
        # Reading from metadata only; ground truth source fields will be partial.
        by_video_id: dict[str, dict[str, Any]] = {}
    else:
        records = json.loads(args.video_meta.read_text(encoding="utf-8"))
        by_video_id = {rec["video_id"]: rec for rec in records}

    inputs = [_input_record(sub) for sub in used_subvideos]
    gt = [
        _ground_truth_record(sub, by_video_id.get(sub["source_video"], {}))
        for sub in used_subvideos
    ]

    args.merged_dir.mkdir(parents=True, exist_ok=True)
    inputs_path = args.merged_dir / "test_subvideo_inputs.json"
    gt_path = args.merged_dir / "test_subvideo_ground_truth.json"
    inputs_path.write_text(
        json.dumps(inputs, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    gt_path.write_text(
        json.dumps(gt, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = dict(top_level)
    manifest.update(
        {
            "mode": "test_subvideos",
            "source_test_count": len(test_ids),
            "generated_count": len(generated),
            "exported_count": len(used_subvideos),
            "metadata_only": args.metadata_only,
            "review_filter_applied": _metadata_has_reviews(generated),
            "strict": args.strict,
            "inputs_path": str(inputs_path.relative_to(ROOT)),
            "ground_truth_path": str(gt_path.relative_to(ROOT)),
            "exclusions": exclusions,
            "subvideos": generated,
        }
    )
    if preprocessor_fingerprint is not None:
        manifest["preprocessor_fingerprint"] = preprocessor_fingerprint
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )

    print(f"Wrote {len(inputs)} inputs -> {inputs_path}")
    print(f"Wrote {len(gt)} ground-truth rows -> {gt_path}")
    print(f"Wrote manifest -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
