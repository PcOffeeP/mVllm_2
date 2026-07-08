#!/usr/bin/env python3
"""Generate subvideo-based test artifacts for inference.

This mirrors the training-time subvideo input shape for the held-out test
videos without changing the default training subvideo builder, which still
skips test split records.
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
    return {
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate subvideo test artifacts.")
    parser.add_argument("--video-meta", type=Path, default=VIDEO_META_DEFAULT)
    parser.add_argument("--splits-dir", type=Path, default=SPLITS_DIR_DEFAULT)
    parser.add_argument("--merged-dir", type=Path, default=MERGED_DIR_DEFAULT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
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


def main() -> int:
    args = parse_args()
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

    preprocessor = builder._create_preprocessor(args.preprocessor, builder.VIDEO_MAXLEN, args.model)
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

    inputs = [_input_record(sub) for sub in generated]
    gt = [_ground_truth_record(sub, by_video_id[sub["source_video"]]) for sub in generated]

    args.merged_dir.mkdir(parents=True, exist_ok=True)
    inputs_path = args.merged_dir / "test_subvideo_inputs.json"
    gt_path = args.merged_dir / "test_subvideo_ground_truth.json"
    inputs_path.write_text(json.dumps(inputs, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    gt_path.write_text(json.dumps(gt, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "mode": "test_subvideos",
        "source_test_count": len(test_ids),
        "generated_count": len(generated),
        "metadata_only": args.metadata_only,
        "preprocessor_fingerprint": preprocessor.fingerprint(),
        "inputs_path": str(inputs_path.relative_to(ROOT)),
        "ground_truth_path": str(gt_path.relative_to(ROOT)),
        "exclusions": builder.EXCLUSIONS,
        "subvideos": generated,
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    print(f"Wrote {len(inputs)} inputs -> {inputs_path}")
    print(f"Wrote {len(gt)} ground-truth rows -> {gt_path}")
    print(f"Wrote manifest -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
