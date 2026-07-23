"""Semantic paths for the only active data-processing lineage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.data_roots import (
    load_config,
    resolve_data_home,
    version_root,
    workspace_root,
)

CONTRACT_VERSION = "tensile-vlm/v4.1"


@dataclass(frozen=True)
class CurrentDataPaths:
    root: Path
    source: Path
    videos: Path
    annotations: Path
    splits: Path
    derived: Path
    roi_videos: Path
    subvideos: Path
    frames: Path
    metadata: Path
    training_releases: Path
    compatibility_workspace: Path


def current_data_paths(
    project_root: Path,
    *,
    data_home: Path | None = None,
) -> CurrentDataPaths:
    project_root = Path(project_root).resolve()
    config = load_config(project_root / "config/data_roots.json")
    resolved_home = resolve_data_home(
        config,
        project_root=project_root,
        override=data_home,
    )
    root = version_root(
        config,
        CONTRACT_VERSION,
        data_home=resolved_home,
    )
    source = root / "source"
    derived = root / "derived"
    return CurrentDataPaths(
        root=root,
        source=source,
        videos=source / "videos",
        annotations=source / "annotations",
        splits=source / "splits",
        derived=derived,
        roi_videos=derived / "roi_videos",
        subvideos=derived / "subvideos",
        frames=derived / "frames",
        metadata=derived / "metadata",
        training_releases=root / "training_releases",
        compatibility_workspace=workspace_root(
            config,
            CONTRACT_VERSION,
            data_home=resolved_home,
        ),
    )
