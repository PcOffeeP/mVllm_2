"""Project-local workspace paths and semantic experiment identities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

EXPERIMENT_ID_PATTERN = re.compile(
    r"^v4\.1-[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+-seed[0-9]+$"
)
CURRENT_EXPERIMENT_ID = "v4.1-prompt-minimal-v1-seed3411"


class ProjectWorkspaceError(ValueError):
    """A project-local workspace or semantic experiment ID is invalid."""


def validate_experiment_id(value: str) -> str:
    if not isinstance(value, str) or not EXPERIMENT_ID_PATTERN.fullmatch(value):
        raise ProjectWorkspaceError(
            "experiment ID 必须符合 "
            "<protocol>-<changed-variable>-<revision>-seed<seed>"
        )
    return value


@dataclass(frozen=True)
class ProjectWorkspacePaths:
    repo_root: Path
    root: Path
    data: Path
    runs: Path


@dataclass(frozen=True)
class ExperimentWorkspacePaths:
    experiment_id: str
    git_dir: Path
    run_dir: Path
    input: Path
    adapter: Path
    merged: Path
    evaluation: Path
    logs: Path


def project_workspace_paths(project_root: Path) -> ProjectWorkspacePaths:
    repo_root = Path(project_root).resolve()
    root = repo_root / "workspace"
    return ProjectWorkspacePaths(
        repo_root=repo_root,
        root=root,
        data=root / "data",
        runs=root / "runs",
    )


def experiment_workspace_paths(
    project_root: Path,
    experiment_id: str,
) -> ExperimentWorkspacePaths:
    experiment_id = validate_experiment_id(experiment_id)
    workspace = project_workspace_paths(project_root)
    run_dir = workspace.runs / experiment_id
    return ExperimentWorkspacePaths(
        experiment_id=experiment_id,
        git_dir=workspace.repo_root / "finetune" / "experiments" / experiment_id,
        run_dir=run_dir,
        input=run_dir / "input",
        adapter=run_dir / "adapter",
        merged=run_dir / "merged",
        evaluation=run_dir / "evaluation",
        logs=run_dir / "logs",
    )
