#!/usr/bin/env python3
"""Build a deterministic full-training dataset from an immutable release.

The released fold files intentionally contain repeated samples across folds.
This tool reads all train and validation folds, verifies that every repeated
video has an identical payload, and writes one canonical row per video outside
the immutable release directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


FULL_DATASET_NAME = "tensile_video_interval_full_train"


class FullDatasetError(RuntimeError):
    """Raised when the release cannot safely produce a full dataset."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FullDatasetError(f"cannot read JSON: {path}: {exc}") from exc


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_release(release_dir: Path) -> tuple[str, Path]:
    manifest_path = release_dir / "manifest" / "release_manifest.json"
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise FullDatasetError("release manifest must be a JSON object")
    release_id = manifest.get("release_id")
    if not isinstance(release_id, str) or not release_id:
        raise FullDatasetError("release manifest has no release_id")
    if manifest.get("status") != "training_ready":
        raise FullDatasetError("release is not training_ready")
    if manifest.get("immutable") is not True:
        raise FullDatasetError("release is not marked immutable")
    quality = manifest.get("quality")
    if not isinstance(quality, dict) or quality.get("error_count") != 0:
        raise FullDatasetError("release quality gate did not pass")
    return release_id, manifest_path


def build_full_dataset(release_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return canonical full rows and provenance without writing files."""
    release_dir = release_dir.resolve()
    release_id, release_manifest_path = _validate_release(release_dir)
    source_paths = [
        release_dir / "datasets" / split / f"fold_{fold}.json"
        for split in ("train", "validation")
        for fold in range(3)
    ]

    canonical_by_video: dict[tuple[str, ...], tuple[str, dict[str, Any], str]] = {}
    occurrence_counts: Counter[tuple[str, ...]] = Counter()
    source_entries: list[dict[str, Any]] = []
    total_rows = 0

    for path in source_paths:
        rows = _read_json(path)
        if not isinstance(rows, list):
            raise FullDatasetError(f"fold dataset must be a JSON list: {path}")
        source_entries.append(
            {
                "path": str(path.relative_to(release_dir)),
                "row_count": len(rows),
                "sha256": _sha256_file(path),
            }
        )
        total_rows += len(rows)
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise FullDatasetError(f"row {index} is not an object: {path}")
            videos = row.get("videos")
            if (
                not isinstance(videos, list)
                or not videos
                or not all(isinstance(item, str) and item for item in videos)
            ):
                raise FullDatasetError(f"row {index} has invalid videos: {path}")
            video_key = tuple(videos)
            canonical = _canonical_json(row)
            previous = canonical_by_video.get(video_key)
            if previous is not None and previous[0] != canonical:
                raise FullDatasetError(
                    "conflicting payload for videos "
                    f"{video_key!r}: {previous[2]} and {path.relative_to(release_dir)}"
                )
            canonical_by_video.setdefault(
                video_key, (canonical, row, str(path.relative_to(release_dir)))
            )
            occurrence_counts[video_key] += 1

    rows = [
        canonical_by_video[key][1]
        for key in sorted(canonical_by_video, key=lambda value: _canonical_json(value))
    ]
    histogram = Counter(occurrence_counts.values())
    provenance = {
        "schema_version": "1.0",
        "release_id": release_id,
        "release_manifest": {
            "path": str(release_manifest_path.relative_to(release_dir)),
            "sha256": _sha256_file(release_manifest_path),
        },
        "deduplication_key": "videos",
        "source_row_count": total_rows,
        "unique_row_count": len(rows),
        "duplicate_occurrence_count": total_rows - len(rows),
        "occurrence_histogram": {
            str(count): videos for count, videos in sorted(histogram.items())
        },
        "sources": source_entries,
    }
    return rows, provenance


def _dataset_info() -> dict[str, Any]:
    return {
        FULL_DATASET_NAME: {
            "file_name": "full_train.json",
            "formatting": "sharegpt",
            "columns": {
                "messages": "messages",
                "videos": "videos",
            },
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "observation_tag": "observation",
                "function_tag": "function_call",
                "system_tag": "system",
            },
        }
    }


def write_full_dataset(
    release_dir: Path, output_dir: Path
) -> tuple[Path, Path, Path]:
    """Build and atomically write dataset, registry, and provenance files."""
    rows, provenance = build_full_dataset(release_dir)
    output_dir = output_dir.resolve()
    release_dir = release_dir.resolve()
    if output_dir == release_dir or release_dir in output_dir.parents:
        raise FullDatasetError("output_dir must be outside the immutable release")

    dataset_path = output_dir / "full_train.json"
    dataset_info_path = output_dir / "dataset_info.json"
    provenance_path = output_dir / "full_train.provenance.json"
    if any(path.exists() for path in (dataset_path, dataset_info_path, provenance_path)):
        raise FullDatasetError(f"refusing to overwrite existing output in {output_dir}")

    dataset_bytes = (
        json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    dataset_info_bytes = (
        json.dumps(_dataset_info(), ensure_ascii=False, indent=2).encode("utf-8")
        + b"\n"
    )
    provenance["output"] = {
        "dataset": {
            "path": dataset_path.name,
            "size_bytes": len(dataset_bytes),
            "sha256": _sha256_bytes(dataset_bytes),
        },
        "dataset_info": {
            "path": dataset_info_path.name,
            "dataset_name": FULL_DATASET_NAME,
            "size_bytes": len(dataset_info_bytes),
            "sha256": _sha256_bytes(dataset_info_bytes),
        },
    }
    provenance_bytes = (
        json.dumps(provenance, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_tmp = output_dir / f".{dataset_path.name}.tmp"
    dataset_info_tmp = output_dir / f".{dataset_info_path.name}.tmp"
    provenance_tmp = output_dir / f".{provenance_path.name}.tmp"
    try:
        dataset_tmp.write_bytes(dataset_bytes)
        dataset_info_tmp.write_bytes(dataset_info_bytes)
        provenance_tmp.write_bytes(provenance_bytes)
        dataset_tmp.replace(dataset_path)
        dataset_info_tmp.replace(dataset_info_path)
        provenance_tmp.replace(provenance_path)
    finally:
        dataset_tmp.unlink(missing_ok=True)
        dataset_info_tmp.unlink(missing_ok=True)
        provenance_tmp.unlink(missing_ok=True)
    return dataset_path, dataset_info_path, provenance_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a deduplicated full-training dataset from six fold files."
    )
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate and print provenance without writing output",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.validate_only:
        _, provenance = build_full_dataset(args.release_dir)
        print(json.dumps(provenance, ensure_ascii=False, indent=2))
    else:
        dataset_path, dataset_info_path, provenance_path = write_full_dataset(
            args.release_dir, args.output_dir
        )
        print(f"dataset: {dataset_path}")
        print(f"dataset_info: {dataset_info_path}")
        print(f"provenance: {provenance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
