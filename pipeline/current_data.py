"""Root-scoped semantic paths for active and isolated V4.1 data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.data_roots import (
    DataRootError,
    PROJECT_LOCAL_LEGACY_PATHS,
)
from pipeline.project_workspace import project_workspace_paths

CONTRACT_VERSION = "tensile-vlm/v4.1"


@dataclass(frozen=True)
class DataContext:
    project_root: Path
    purpose: str
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

    @property
    def compatibility_workspace(self) -> Path:
        """Deprecated compatibility alias for callers not yet parameterized."""
        return self.root

    def resolve_artifact(self, value: str | Path) -> Path:
        """Resolve a semantic or frozen legacy path inside this context.

        Unknown absolute paths fail closed instead of leaking to an external
        machine-specific root.
        """
        return resolve_data_artifact(value, self.root)

    def semantic_path(self, value: str | Path) -> str:
        """Return a normalized semantic path relative to this data root."""
        resolved = self.resolve_artifact(value)
        relative = resolved.relative_to(self.root)
        if not relative.parts or relative.parts[0] not in {
            "source",
            "derived",
            "releases",
        }:
            raise DataRootError(f"路径不是受管语义路径: {value}")
        return relative.as_posix()


CurrentDataPaths = DataContext


def resolve_data_artifact(value: str | Path, data_root: Path) -> Path:
    """Resolve one artifact against any semantic current/rebuild data root."""
    root = Path(data_root).resolve()
    semantic_root = root.name == "data" and (
        root.parent.name == "workspace"
        or root.parent.parent.name == "data-rebuild"
    )
    raw = Path(value)
    if not raw.is_absolute() and ".." in raw.parts:
        raise DataRootError(f"相对路径不能包含父目录跳转: {value}")
    if not raw.is_absolute():
        resolved = root / raw
        if semantic_root:
            for legacy, semantic in PROJECT_LOCAL_LEGACY_PATHS.items():
                legacy_parts = Path(legacy).parts
                if raw.parts[: len(legacy_parts)] == legacy_parts:
                    resolved = root / semantic / Path(*raw.parts[len(legacy_parts) :])
                    break
    else:
        absolute = raw.resolve()
        try:
            absolute.relative_to(root)
            resolved = absolute
        except ValueError:
            resolved = None
            if semantic_root:
                data_indexes = [
                    index
                    for index, part in enumerate(raw.parts)
                    if part == "data"
                ]
                for index in reversed(data_indexes):
                    suffix = raw.parts[index:]
                    for legacy, semantic in PROJECT_LOCAL_LEGACY_PATHS.items():
                        legacy_parts = Path(legacy).parts
                        if suffix[: len(legacy_parts)] == legacy_parts:
                            resolved = (
                                root
                                / semantic
                                / Path(*suffix[len(legacy_parts) :])
                            )
                            break
                    if resolved is not None:
                        break
                    semantic_suffix = suffix[1:]
                    if semantic_suffix and semantic_suffix[0] in {
                        "source",
                        "derived",
                        "releases",
                    }:
                        resolved = root / Path(*semantic_suffix)
                        break
            if resolved is None:
                raise DataRootError(f"绝对路径无法映射到数据上下文: {raw}")
    resolved = resolved.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DataRootError(f"路径逃逸数据上下文: {value}") from exc
    return resolved


def _context(project_root: Path, root: Path, *, purpose: str) -> DataContext:
    project_root = Path(project_root).resolve()
    root = Path(root).resolve()
    source = root / "source"
    derived = root / "derived"
    return DataContext(
        project_root=project_root,
        purpose=purpose,
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
    )


def current_data_context(project_root: Path) -> DataContext:
    project_root = Path(project_root).resolve()
    return _context(
        project_root,
        project_workspace_paths(project_root).data,
        purpose="current",
    )


def data_context_for_root(
    project_root: Path,
    data_root: Path,
    *,
    purpose: str = "rebuild",
) -> DataContext:
    """Build a context for one explicit isolated rebuild root."""
    if purpose != "rebuild":
        raise DataRootError("显式 data root 只允许用于 rebuild")
    project_root = Path(project_root).resolve()
    data_root = Path(data_root)
    if not data_root.is_absolute():
        data_root = project_root / data_root
    data_root = data_root.resolve()
    rebuilds = project_root / "workspace" / "data-rebuild"
    try:
        relative = data_root.relative_to(rebuilds)
    except ValueError as exc:
        raise DataRootError(f"rebuild data root 必须位于 {rebuilds}") from exc
    if len(relative.parts) != 2 or relative.parts[1] != "data":
        raise DataRootError(
            "rebuild data root 必须符合 workspace/data-rebuild/<rebuild-id>/data"
        )
    rebuild_id = relative.parts[0]
    if rebuild_id in {"", ".", ".."}:
        raise DataRootError("rebuild-id 无效")
    return _context(project_root, data_root, purpose=purpose)


def data_context_from_arg(
    project_root: Path,
    data_root: Path | None,
) -> DataContext:
    """Resolve an optional CLI data root without environment fallbacks."""
    current = current_data_context(project_root)
    if data_root is None:
        return current
    candidate = Path(data_root)
    if not candidate.is_absolute():
        candidate = Path(project_root).resolve() / candidate
    if candidate.resolve() == current.root:
        return current
    return data_context_for_root(project_root, candidate)


def current_data_paths(
    project_root: Path,
) -> DataContext:
    """Compatibility wrapper for the fixed active data context."""
    return current_data_context(project_root)
