#!/usr/bin/env python3
"""Physically copy and verify active V4.1 data in the project-local workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.project_workspace import project_workspace_paths

MANAGED_DIRS = {
    "source": "source",
    "derived": "derived",
    "training_releases": "releases",
}
MANIFEST_NAME = "migration_manifest.json"


class WorkspaceMigrationError(RuntimeError):
    """Raised when the physical migration cannot be proven lossless."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root: Path, *, source_layout: bool) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total_bytes = 0
    mapping = MANAGED_DIRS if source_layout else {value: value for value in MANAGED_DIRS.values()}
    for source_name, canonical_name in mapping.items():
        managed_root = root / source_name
        if not managed_root.is_dir():
            raise WorkspaceMigrationError(f"缺少受管目录: {managed_root}")
        for path in sorted(managed_root.rglob("*")):
            if path.is_symlink():
                raise WorkspaceMigrationError(f"受管目录中不允许软链接: {path}")
            if not path.is_file():
                continue
            relative = Path(canonical_name) / path.relative_to(managed_root)
            size = path.stat().st_size
            total_bytes += size
            files.append(
                {
                    "path": relative.as_posix(),
                    "bytes": size,
                    "sha256": sha256_file(path),
                }
            )
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
    }


def _copy_managed(source_root: Path, staging_root: Path) -> None:
    if staging_root.exists():
        raise WorkspaceMigrationError(f"迁移暂存目录已存在，请先核实后处理: {staging_root}")
    staging_root.mkdir(parents=True)
    for source_name, destination_name in MANAGED_DIRS.items():
        source = source_root / source_name
        if not source.is_dir():
            raise WorkspaceMigrationError(f"缺少受管目录: {source}")
        shutil.copytree(
            source,
            staging_root / destination_name,
            symlinks=False,
            copy_function=shutil.copy2,
        )


def migrate(
    source_root: Path,
    destination_root: Path,
    *,
    copy: bool,
) -> dict[str, Any]:
    source_root = source_root.expanduser().resolve()
    destination_root = destination_root.expanduser().resolve()
    if source_root == destination_root:
        raise WorkspaceMigrationError("源目录与目标目录不能相同")

    source_inventory = inventory(source_root, source_layout=True)
    if copy:
        if destination_root.exists():
            raise WorkspaceMigrationError(f"目标目录已存在，拒绝覆盖: {destination_root}")
        staging_root = destination_root.parent / f".{destination_root.name}.migrating"
        _copy_managed(source_root, staging_root)
        destination_inventory = inventory(staging_root, source_layout=False)
        if source_inventory != destination_inventory:
            raise WorkspaceMigrationError("暂存副本与源目录的文件清单、大小或 SHA256 不一致")
        os.replace(staging_root, destination_root)
    elif not destination_root.is_dir():
        raise WorkspaceMigrationError(f"目标目录不存在: {destination_root}")

    destination_inventory = inventory(destination_root, source_layout=False)
    if source_inventory != destination_inventory:
        raise WorkspaceMigrationError("目标目录与源目录的文件清单、大小或 SHA256 不一致")

    release_manifests = {
        entry["path"]: entry["sha256"]
        for entry in source_inventory["files"]
        if entry["path"].startswith("releases/")
        and Path(entry["path"]).name in {"manifest.json", "release_manifest.json"}
    }
    result = {
        "schema_version": "tensile-vlm-project-workspace-migration/v1",
        "source_root": str(source_root),
        "destination_root": str(destination_root),
        "managed_directory_mapping": MANAGED_DIRS,
        "file_count": source_inventory["file_count"],
        "total_bytes": source_inventory["total_bytes"],
        "release_manifest_sha256": release_manifests,
        "verified": True,
    }
    (destination_root / MANIFEST_NAME).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    default_destination = project_workspace_paths(PROJECT_ROOT).data
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=PROJECT_ROOT.parent / "tensile-data/current",
    )
    parser.add_argument("--destination-root", type=Path, default=default_destination)
    parser.add_argument(
        "--copy",
        action="store_true",
        help="copy into an absent destination; without this flag only verify",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        json.dumps(
            migrate(args.source_root, args.destination_root, copy=args.copy),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
