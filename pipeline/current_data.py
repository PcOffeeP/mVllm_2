"""Root-scoped semantic paths for active and isolated V4.1 data."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from pipeline.data_roots import (
    DataRootError,
    PROJECT_LOCAL_LEGACY_PATHS,
)
from pipeline.project_workspace import project_workspace_paths

CONTRACT_VERSION = "tensile-vlm/v4.1"
SEMANTIC_STAGING_CREATE_ENABLED = True
SEMANTIC_STAGING_LAYOUT = "semantic-staging-v2"
CURRENT_LAYOUT = "current-semantic-v2"
LEGACY_REBUILD_LAYOUT = "legacy-rebuild-v1"
SEMANTIC_REBUILD_SCHEMA = "tensile-v4.1-data-rebuild/v2"

METADATA_COLLECTIONS = frozenset(
    {
        "source_snapshots",
        "split_snapshots",
        "roi_manifests",
        "candidate_plans",
        "candidate_media_results",
        "review_reference",
        "review_queues",
        "review_decisions",
    }
)
LEGACY_METADATA_COLLECTIONS = {
    "roi_manifests": Path("v3/roi_manifests"),
    "candidate_plans": Path("v3/candidate_plans"),
    "candidate_media_results": Path("v3/candidate_media_results"),
    "review_reference": Path("v3/review_reference"),
    "review_queues": Path("v4_1/review_queues"),
    "review_decisions": Path("v4_1/review_decisions"),
}


@dataclass(frozen=True)
class DataContext:
    project_root: Path
    purpose: str
    layout_profile: str
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

    def metadata_collection(self, name: str) -> Path:
        if name not in METADATA_COLLECTIONS:
            raise DataRootError(f"未知 metadata collection: {name}")
        return self.metadata / name

    def legacy_metadata_collection(self, name: str) -> Path | None:
        if name not in METADATA_COLLECTIONS:
            raise DataRootError(f"未知 metadata collection: {name}")
        relative = LEGACY_METADATA_COLLECTIONS.get(name)
        return None if relative is None else self.metadata / relative

    def metadata_read_roots(self, name: str) -> tuple[Path, ...]:
        semantic = self.metadata_collection(name)
        legacy = self.legacy_metadata_collection(name)
        return (semantic,) if legacy is None else (semantic, legacy)

    def metadata_artifact_path(
        self,
        name: str,
        artifact_id: str,
        *,
        expected_schema: str,
        expected_tree_hash: str | None = None,
    ) -> Path:
        """Resolve and validate one exact semantic/legacy metadata artifact."""
        from pipeline.metadata_artifacts import resolve_metadata_artifact

        return resolve_metadata_artifact(
            self,
            collection=name,
            artifact_id=artifact_id,
            expected_schema=expected_schema,
            expected_tree_hash=expected_tree_hash,
        )

    def require_managed_output(
        self,
        value: str | Path,
        managed_root: Path,
        *,
        label: str,
    ) -> Path:
        """Reject explicit writer outputs outside their semantic managed root."""
        raw = Path(value)
        if not raw.is_absolute():
            raw = self.project_root / raw
        lexical = raw.absolute()
        lexical_root = Path(managed_root).absolute()
        try:
            relative = lexical.relative_to(lexical_root)
        except ValueError as exc:
            raise DataRootError(f"{label} 必须位于 {lexical_root}") from exc
        cursor = lexical_root
        for part in relative.parts:
            if cursor.is_symlink():
                raise DataRootError(f"{label} 不允许 symlink 路径: {cursor}")
            cursor = cursor / part
        if cursor.is_symlink():
            raise DataRootError(f"{label} 不允许 symlink 路径: {cursor}")
        resolved = raw.resolve()
        root = Path(managed_root).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise DataRootError(f"{label} 必须位于 {root}") from exc
        return resolved


CurrentDataPaths = DataContext


def resolve_data_artifact(value: str | Path, data_root: Path) -> Path:
    """Resolve one artifact against any semantic current/rebuild data root."""
    root = Path(data_root).resolve()
    semantic_root = root.name == "data" and (
        root.parent.name == "workspace"
        or root.parent.parent.name in {"data-rebuild", "data-staging"}
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
        layout_profile=(
            CURRENT_LAYOUT if purpose == "current" else SEMANTIC_STAGING_LAYOUT
        ),
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
    purpose: str = "staging",
) -> DataContext:
    """Build a context for one explicit semantic staging data root."""
    if purpose != "staging":
        raise DataRootError("显式 data root 只允许用于 semantic staging")
    project_root = Path(project_root).resolve()
    data_root = Path(data_root)
    if not data_root.is_absolute():
        data_root = project_root / data_root
    if data_root.is_symlink() or data_root.parent.is_symlink():
        raise DataRootError("staging data root 不允许 symlink")
    data_root = data_root.resolve()
    staging = project_root / "workspace" / "data-staging"
    try:
        relative = data_root.relative_to(staging)
    except ValueError as exc:
        raise DataRootError(f"staging data root 必须位于 {staging}") from exc
    if len(relative.parts) != 2 or relative.parts[1] != "data":
        raise DataRootError(
            "staging data root 必须符合 workspace/data-staging/<run-id>/data"
        )
    run_id = relative.parts[0]
    if run_id in {"", ".", ".."}:
        raise DataRootError("run-id 无效")
    return _context(project_root, data_root, purpose="staging")


def create_staging_context(project_root: Path, run_root: Path) -> DataContext:
    if not SEMANTIC_STAGING_CREATE_ENABLED:
        raise DataRootError("semantic staging create gate 尚未启用")
    project_root = Path(project_root).resolve()
    run_root = Path(run_root)
    if not run_root.is_absolute():
        run_root = project_root / run_root
    if run_root.exists():
        raise DataRootError(f"新 staging run 已存在: {run_root}")
    return data_context_for_root(project_root, run_root / "data")


def resume_staging_context(
    project_root: Path,
    run_root: Path,
    git_commit: str,
) -> DataContext:
    """Resume only a frozen semantic run produced by the same Git identity."""
    return validate_staging_state_identity(
        project_root,
        run_root,
        git_commit=git_commit,
    )


def validate_staging_state_identity(
    project_root: Path,
    run_root: Path,
    *,
    git_commit: str | None = None,
) -> DataContext:
    """Validate frozen semantic layout/root and optionally producer Git."""
    project_root = Path(project_root).resolve()
    raw_run_root = Path(run_root)
    if not raw_run_root.is_absolute():
        raw_run_root = project_root / raw_run_root
    if raw_run_root.is_symlink() or not raw_run_root.is_dir():
        raise DataRootError(f"staging run 必须是既存物理目录: {raw_run_root}")
    resolved_run_root = raw_run_root.resolve()
    raw_data_root = resolved_run_root / "data"
    if raw_data_root.is_symlink() or not raw_data_root.is_dir():
        raise DataRootError(
            f"staging data root 必须是既存物理目录: {raw_data_root}"
        )
    context = data_context_for_root(
        project_root,
        raw_data_root,
    )
    state_path = resolved_run_root / "control/rebuild.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataRootError(f"staging state 无法读取: {state_path}") from exc
    if not isinstance(state, Mapping):
        raise DataRootError("staging state 必须是 JSON object")
    state_git_commit = state.get("git_commit")
    if (
        state.get("schema_version") != SEMANTIC_REBUILD_SCHEMA
        or state.get("layout_profile") != SEMANTIC_STAGING_LAYOUT
        or state.get("run_root") != str(resolved_run_root)
        or state.get("data_root") != str(context.root)
        or not isinstance(state_git_commit, str)
        or not state_git_commit
        or (git_commit is not None and state_git_commit != git_commit)
    ):
        raise DataRootError("staging state 的 schema/layout/root/Git 身份不匹配")
    return context


def inspect_legacy_context(
    project_root: Path,
    run_root: Path,
) -> dict[str, Any]:
    """Read and validate a legacy run without granting write access."""
    project_root = Path(project_root).resolve()
    raw_run_root = Path(run_root)
    if not raw_run_root.is_absolute():
        raw_run_root = project_root / raw_run_root
    if raw_run_root.is_symlink() or not raw_run_root.is_dir():
        raise DataRootError(f"legacy run 必须是既存物理目录: {raw_run_root}")
    resolved_run_root = raw_run_root.resolve()
    legacy_parent = (project_root / "workspace/data-rebuild").resolve()
    try:
        relative = resolved_run_root.relative_to(legacy_parent)
    except ValueError as exc:
        raise DataRootError("legacy run 不在 workspace/data-rebuild") from exc
    if len(relative.parts) != 1:
        raise DataRootError("legacy run root 层级非法")
    state_path = resolved_run_root / "control/rebuild.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataRootError(f"legacy state 无法读取: {state_path}") from exc
    if not isinstance(state, Mapping):
        raise DataRootError("legacy state 必须是 JSON object")
    if (
        state.get("run_root") != str(resolved_run_root)
        or state.get("data_root") != str((resolved_run_root / "data").resolve())
    ):
        raise DataRootError("legacy state 的冻结 root 身份不匹配")
    git_commit = state.get("git_commit")
    if not isinstance(git_commit, str) or not git_commit:
        raise DataRootError("legacy state 缺少 producer Git commit")
    return {
        "layout_profile": LEGACY_REBUILD_LAYOUT,
        "run_root": str(resolved_run_root),
        "data_root": str((resolved_run_root / "data").resolve()),
        "producer_git_commit": git_commit,
        "state": dict(state),
    }


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
