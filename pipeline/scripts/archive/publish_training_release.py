#!/usr/bin/env python3
"""Publish validated pipeline outputs as an immutable training-data release.

This is the only normal data-flow step that writes ``data/08_training_ready``.
Steps that build, validate, or freeze ``06_merged`` do not publish automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
MERGED_DIR_DEFAULT = DATA_DIR / "06_merged"
METADATA_DIR_DEFAULT = DATA_DIR / "07_metadata"
RELEASES_DIR_DEFAULT = DATA_DIR / "08_training_ready"
TRAINING_METADATA_DEFAULT = (
    METADATA_DIR_DEFAULT / "subvideos_meta.filtered_neg_before.label_reviewed.json"
)
QUALITY_REPORT_DEFAULT = METADATA_DIR_DEFAULT / "quality_check_report.json"
VERSION_LOCK_DEFAULT = METADATA_DIR_DEFAULT / "data_version_lock.json"

RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

REQUIRED_SOURCE_FILES = {
    "datasets/train/fold_0.json": ("fold_0_train.json", "fold 0 training dataset"),
    "datasets/train/fold_1.json": ("fold_1_train.json", "fold 1 training dataset"),
    "datasets/train/fold_2.json": ("fold_2_train.json", "fold 2 training dataset"),
    "datasets/validation/fold_0.json": ("fold_0_val.json", "fold 0 validation dataset"),
    "datasets/validation/fold_1.json": ("fold_1_val.json", "fold 1 validation dataset"),
    "datasets/validation/fold_2.json": ("fold_2_val.json", "fold 2 validation dataset"),
    "reports/sample_statistics.json": ("samples_meta.json", "training sample statistics"),
}

EVALUATION_GROUPS = {
    "source_videos": {
        "datasets/evaluation/source_videos/inputs.json": (
            "test_inputs.json",
            "source-video evaluation inputs",
        ),
        "datasets/evaluation/source_videos/ground_truth.json": (
            "test_ground_truth.json",
            "source-video evaluation ground truth",
        ),
    },
    "subvideos": {
        "datasets/evaluation/subvideos/inputs.json": (
            "test_subvideo_inputs.json",
            "subvideo evaluation inputs",
        ),
        "datasets/evaluation/subvideos/ground_truth.json": (
            "test_subvideo_ground_truth.json",
            "subvideo evaluation ground truth",
        ),
    },
}

DATASET_REGISTRY_TARGETS = {
    "tensile_video_interval_fold0_train": "datasets/train/fold_0.json",
    "tensile_video_interval_fold0_val": "datasets/validation/fold_0.json",
    "tensile_video_interval_fold1_train": "datasets/train/fold_1.json",
    "tensile_video_interval_fold1_val": "datasets/validation/fold_1.json",
    "tensile_video_interval_fold2_train": "datasets/train/fold_2.json",
    "tensile_video_interval_fold2_val": "datasets/validation/fold_2.json",
}


class ReleaseError(ValueError):
    """Raised when source artifacts do not satisfy the release contract."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseError(f"required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"invalid JSON file: {path}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _combined_sha256(paths: list[Path]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(paths):
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def derive_release_id(version_lock: dict[str, Any]) -> str:
    version = version_lock.get("version")
    sample_sha = (version_lock.get("sample_manifest") or {}).get("sha256")
    if not isinstance(version, str) or not version.strip():
        raise ReleaseError("data version lock has no non-empty version")
    if not isinstance(sample_sha, str) or len(sample_sha) < 8:
        raise ReleaseError("data version lock has no valid sample_manifest.sha256")
    version_part = version if version.startswith("v") else f"v{version}"
    return f"{version_part}-{sample_sha[:8]}"


def _validate_release_id(release_id: str) -> None:
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise ReleaseError(
            "release ID must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_' or '-'"
        )


def _validate_quality_report(
    report: dict[str, Any],
    report_path: Path,
    merged_dir: Path,
    training_metadata: Path,
) -> None:
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ReleaseError(f"quality report has no summary object: {report_path}")
    error_count = summary.get("error_count")
    if error_count != 0:
        raise ReleaseError(
            f"quality report is not publishable: error_count={error_count!r}: {report_path}"
        )
    reported_merged_dir = summary.get("merged_dir")
    if (
        not isinstance(reported_merged_dir, str)
        or Path(reported_merged_dir).name != merged_dir.name
    ):
        raise ReleaseError(
            "quality report does not identify the selected merged directory: "
            f"{reported_merged_dir!r}"
        )
    reported_metadata = summary.get("subvideos_meta")
    if (
        not isinstance(reported_metadata, str)
        or Path(reported_metadata).name != training_metadata.name
    ):
        raise ReleaseError(
            "quality report does not identify the selected training metadata: "
            f"{reported_metadata!r}"
        )


def _validate_training_metadata(path: Path) -> None:
    if not path.name.endswith(".label_reviewed.json"):
        raise ReleaseError(
            "training metadata must be a formal file ending in .label_reviewed.json: "
            f"{path}"
        )
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("subvideos"), list):
        raise ReleaseError(f"training metadata has no subvideos array: {path}")


def _validate_frozen_samples(merged_dir: Path, version_lock: dict[str, Any]) -> None:
    manifest = version_lock.get("sample_manifest")
    if not isinstance(manifest, dict):
        raise ReleaseError("data version lock has no sample_manifest object")
    names = manifest.get("files")
    expected_sha = manifest.get("sha256")
    if not isinstance(names, list) or not names or not all(isinstance(name, str) for name in names):
        raise ReleaseError("data version lock sample_manifest.files is invalid")
    paths = [merged_dir / name for name in names]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ReleaseError(f"frozen sample files are missing: {', '.join(missing)}")
    actual_sha = _combined_sha256(paths)
    if actual_sha != expected_sha:
        raise ReleaseError(
            "data/06_merged no longer matches data_version_lock.json: "
            f"expected {expected_sha}, got {actual_sha}"
        )


def _collect_sources(
    merged_dir: Path,
    training_metadata: Path,
    quality_report: Path,
    version_lock: Path,
) -> dict[str, tuple[Path, str]]:
    sources: dict[str, tuple[Path, str]] = {
        destination: (merged_dir / source_name, purpose)
        for destination, (source_name, purpose) in REQUIRED_SOURCE_FILES.items()
    }
    sources.update(
        {
            "metadata/training_subvideos.json": (
                training_metadata,
                "authoritative filtered and label-reviewed training metadata",
            ),
            "reports/quality_check.json": (
                quality_report,
                "passing data quality report",
            ),
            "manifest/data_version_lock.json": (
                version_lock,
                "frozen source-data and sample provenance",
            ),
        }
    )

    for group_name, group in EVALUATION_GROUPS.items():
        existing = [
            destination
            for destination, (source_name, _purpose) in group.items()
            if (merged_dir / source_name).is_file()
        ]
        if existing and len(existing) != len(group):
            missing_names = [
                source_name
                for destination, (source_name, _purpose) in group.items()
                if destination not in existing
            ]
            raise ReleaseError(
                f"evaluation group {group_name!r} is incomplete; missing: "
                f"{', '.join(missing_names)}"
            )
        if len(existing) == len(group):
            sources.update(
                {
                    destination: (merged_dir / source_name, purpose)
                    for destination, (source_name, purpose) in group.items()
                }
            )

    missing = [str(path) for path, _purpose in sources.values() if not path.is_file()]
    if missing:
        raise ReleaseError(f"required release sources are missing: {', '.join(missing)}")
    return sources


def publish_release(
    *,
    merged_dir: Path = MERGED_DIR_DEFAULT,
    training_metadata: Path = TRAINING_METADATA_DEFAULT,
    quality_report: Path = QUALITY_REPORT_DEFAULT,
    version_lock: Path = VERSION_LOCK_DEFAULT,
    releases_dir: Path = RELEASES_DIR_DEFAULT,
    release_id: str | None = None,
    project_root: Path = PROJECT_ROOT,
) -> tuple[Path, dict[str, Any]]:
    """Validate and atomically publish one immutable release directory."""
    quality_payload = _read_json(quality_report)
    version_payload = _read_json(version_lock)
    if not isinstance(quality_payload, dict) or not isinstance(version_payload, dict):
        raise ReleaseError("quality report and data version lock must be JSON objects")

    _validate_quality_report(
        quality_payload,
        quality_report,
        merged_dir,
        training_metadata,
    )
    _validate_training_metadata(training_metadata)
    _validate_frozen_samples(merged_dir, version_payload)

    resolved_release_id = release_id or derive_release_id(version_payload)
    _validate_release_id(resolved_release_id)
    release_dir = releases_dir / resolved_release_id
    if release_dir.exists():
        raise ReleaseError(f"release already exists and will not be overwritten: {release_dir}")

    sources = _collect_sources(
        merged_dir,
        training_metadata,
        quality_report,
        version_lock,
    )
    releases_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = releases_dir / f".{resolved_release_id}.tmp-{uuid.uuid4().hex}"
    manifest_files: list[dict[str, Any]] = []

    try:
        for relative_destination, (source, purpose) in sorted(sources.items()):
            destination = staging_dir / relative_destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            source_sha = _sha256_file(source)
            copied_sha = _sha256_file(destination)
            if copied_sha != source_sha:
                raise ReleaseError(f"copied file hash mismatch: {source} -> {destination}")
            manifest_files.append(
                {
                    "path": relative_destination,
                    "purpose": purpose,
                    "source": _display_path(source, project_root),
                    "size_bytes": destination.stat().st_size,
                    "sha256": copied_sha,
                }
            )

        manifest = {
            "schema_version": "1.0",
            "release_id": resolved_release_id,
            "status": "training_ready",
            "immutable": True,
            "source_data_version": version_payload.get("version"),
            "source_sample_manifest_sha256": (
                version_payload.get("sample_manifest") or {}
            ).get("sha256"),
            "quality": {
                "error_count": quality_payload["summary"].get("error_count"),
                "warning_count": quality_payload["summary"].get("warning_count"),
            },
            "files": manifest_files,
        }
        manifest_path = staging_dir / "manifest" / "release_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        staging_dir.rename(release_dir)
        return release_dir, manifest
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        raise


def activate_release(release_dir: Path, project_root: Path = PROJECT_ROOT) -> None:
    """Point training and local evaluation configs at an existing release."""
    release_dir = release_dir.resolve()
    project_root = project_root.resolve()
    try:
        release_relative = release_dir.relative_to(project_root)
    except ValueError as exc:
        raise ReleaseError(
            f"active release must be inside the project root: {release_dir}"
        ) from exc
    release_manifest = release_dir / "manifest" / "release_manifest.json"
    manifest = _read_json(release_manifest)
    if not isinstance(manifest, dict) or manifest.get("status") != "training_ready":
        raise ReleaseError(f"release is not marked training_ready: {release_manifest}")

    dataset_info_path = project_root / "finetune" / "dataset_info.json"
    dataset_info = _read_json(dataset_info_path)
    if not isinstance(dataset_info, dict):
        raise ReleaseError(f"dataset registry must be a JSON object: {dataset_info_path}")
    missing_entries = sorted(set(DATASET_REGISTRY_TARGETS) - set(dataset_info))
    if missing_entries:
        raise ReleaseError(
            f"dataset registry is missing entries: {', '.join(missing_entries)}"
        )

    for dataset_name, relative_dataset_path in DATASET_REGISTRY_TARGETS.items():
        target = release_dir / relative_dataset_path
        if not target.is_file():
            raise ReleaseError(f"release dataset is missing: {target}")
        relative_from_finetune = Path("..") / target.relative_to(project_root)
        dataset_info[dataset_name]["file_name"] = str(relative_from_finetune)
        dataset_info[dataset_name]["folder"] = str(relative_from_finetune.parent)

    active_release_path = project_root / "finetune" / "active_data_release.json"
    # WARNING: this script regenerates the runtime pointer and therefore strips
    # the pinned trust anchors (expected_contract_hash / expected_manifest_sha256).
    # After release_build, manually backfill both fields from the corresponding
    # release_summary.json before the pointer is considered production-frozen.
    active_release = {
        "release_id": manifest.get("release_id"),
        "release_dir": str(release_relative),
        "manifest": str(release_manifest.relative_to(project_root)),
    }
    _write_json_atomic(dataset_info_path, dataset_info)
    _write_json_atomic(active_release_path, active_release)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="将通过质量门的数据处理结果发布为版本化训练交付物"
    )
    parser.add_argument("--merged-dir", type=Path, default=MERGED_DIR_DEFAULT)
    parser.add_argument(
        "--training-metadata", type=Path, default=TRAINING_METADATA_DEFAULT
    )
    parser.add_argument("--quality-report", type=Path, default=QUALITY_REPORT_DEFAULT)
    parser.add_argument("--version-lock", type=Path, default=VERSION_LOCK_DEFAULT)
    parser.add_argument("--releases-dir", type=Path, default=RELEASES_DIR_DEFAULT)
    parser.add_argument(
        "--release-id",
        help="显式版本目录名；默认由 data version 和 sample manifest hash 生成",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="发布成功后，将训练和本地评估配置切换到该版本",
    )
    parser.add_argument(
        "--activate-existing",
        metavar="RELEASE_ID",
        help="不重新发布，只激活 08_training_ready 下已存在的指定版本",
    )
    args = parser.parse_args(argv)

    if args.activate and args.activate_existing:
        parser.error("--activate 和 --activate-existing 不能同时使用")

    if args.activate_existing:
        try:
            _validate_release_id(args.activate_existing)
            release_dir = args.releases_dir / args.activate_existing
            activate_release(release_dir)
            manifest = _read_json(release_dir / "manifest" / "release_manifest.json")
        except ReleaseError as exc:
            print(f"激活失败: {exc}", file=sys.stderr)
            return 1
        print(f"训练数据版本已激活: {release_dir}")
        print(f"  release_id: {manifest['release_id']}")
        print("  active: true")
        return 0

    try:
        release_dir, manifest = publish_release(
            merged_dir=args.merged_dir,
            training_metadata=args.training_metadata,
            quality_report=args.quality_report,
            version_lock=args.version_lock,
            releases_dir=args.releases_dir,
            release_id=args.release_id,
        )
        if args.activate:
            activate_release(release_dir)
    except ReleaseError as exc:
        print(f"发布失败: {exc}", file=sys.stderr)
        return 1

    print(f"训练数据发布完成: {release_dir}")
    print(f"  release_id: {manifest['release_id']}")
    print(f"  files: {len(manifest['files'])}")
    print("  status: training_ready")
    if args.activate:
        print("  active: true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
