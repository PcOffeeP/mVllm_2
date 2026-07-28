"""Semantic project-local paths for the active V4.1 lineage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.project_workspace import project_workspace_paths

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
) -> CurrentDataPaths:
    project_root = Path(project_root).resolve()
    root = project_workspace_paths(project_root).data
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
        training_releases=root / "releases",
        # Transitional attribute name for callers that resolve frozen
        # ``data/...`` identities. It is a physical data root, not a symlink
        # compatibility workspace.
        compatibility_workspace=root,
    )
