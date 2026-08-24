from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.data_roots import (
    DataRootError,
    initialize_root,
    initialize_workspace,
    load_config,
    resolve_workspace_artifact,
    validate_root,
    validate_workspace,
    workspace_portable_path,
    workspace_relative_path,
)


def _make_config(tmp_path: Path) -> dict[str, object]:
    """Inline minimal data-roots config to avoid dependency on deleted file."""
    config_path = tmp_path / "data_roots.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_data_home": str(tmp_path / "data"),
                "profiles": {
                    "tensile-vlm/v2": {
                        "directory": "archive",
                        "git_ref": "tensile-vlm-v2-final",
                        "lifecycle": "frozen",
                        "workspace_links": {
                            "data/01_videos": "source/videos",
                            "data/02_annotations": "source/annotations",
                            "data/03_subvideos": "derived/subvideos",
                            "data/04_frames": "derived/frames",
                            "data/05_splits": "source/splits",
                            "data/06_merged": "derived/merged",
                            "data/07_metadata": "derived/metadata",
                            "data/08_incremental_review": "derived/review_rounds",
                            "data/08_training_ready": "training_releases",
                        },
                    },
                    "tensile-vlm/v4.1": {
                        "directory": "current",
                        "git_ref": "main",
                        "lifecycle": "active",
                        "workspace_links": {
                            "data/01_videos": "source/videos",
                            "data/02_annotations": "source/annotations",
                            "data/03_roi_videos": "derived/roi_videos",
                            "data/03_subvideos_roi": "derived/subvideos",
                            "data/04_frames_roi": "derived/frames",
                            "data/05_splits": "source/splits",
                            "data/07_metadata": "derived/metadata",
                            "data/08_training_ready": "training_releases",
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_committed_profiles_use_distinct_roots(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    assert config["profiles"]["tensile-vlm/v2"]["directory"] == "archive"
    assert config["profiles"]["tensile-vlm/v2"]["git_ref"] == "tensile-vlm-v2-final"
    assert config["profiles"]["tensile-vlm/v2"]["lifecycle"] == "frozen"
    assert config["profiles"]["tensile-vlm/v4.1"]["directory"] == "current"
    assert config["profiles"]["tensile-vlm/v4.1"]["git_ref"] == "main"
    assert config["profiles"]["tensile-vlm/v4.1"]["lifecycle"] == "active"


def test_initialize_and_validate_versioned_roots(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    data_home = tmp_path / "data_home"

    v2 = initialize_root(config, "tensile-vlm/v2", data_home=data_home)
    v4_1 = initialize_root(config, "tensile-vlm/v4.1", data_home=data_home)

    assert v2 != v4_1
    assert validate_root(
        config,
        "tensile-vlm/v2",
        data_home=data_home,
    )["lifecycle"] == "frozen"
    assert validate_root(
        config,
        "tensile-vlm/v4.1",
        data_home=data_home,
    )["lifecycle"] == "active"


def test_rejects_contract_mismatch(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    data_home = tmp_path / "data_home"
    root = initialize_root(config, "tensile-vlm/v2", data_home=data_home)
    marker_path = root / ".tensile-data-root.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["contract_version"] = "tensile-vlm/v4.1"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(DataRootError, match="contract_version"):
        validate_root(config, "tensile-vlm/v2", data_home=data_home)


def test_workspace_links_stay_inside_version_root(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    data_home = tmp_path / "data_home"
    root = initialize_root(config, "tensile-vlm/v4.1", data_home=data_home)
    for target_name in config["profiles"]["tensile-vlm/v4.1"]["workspace_links"].values():
        (root / target_name).mkdir(parents=True, exist_ok=True)

    workspace = initialize_workspace(
        config,
        "tensile-vlm/v4.1",
        data_home=data_home,
    )
    result = validate_workspace(
        config,
        "tensile-vlm/v4.1",
        data_home=data_home,
    )

    assert result["link_count"] == 8
    assert (workspace / "data/03_subvideos_roi").resolve() == (
        root / "derived/subvideos"
    ).resolve()


def test_remaps_frozen_absolute_data_path_without_following_symlink(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "current/.compat/workspace"
    old = Path("/old/machine/project/data/03_subvideos_roi/example.mp4")

    mapped = resolve_workspace_artifact(old, workspace)

    assert mapped == workspace / "data/03_subvideos_roi/example.mp4"
    assert workspace_relative_path(mapped, workspace) == (
        "data/03_subvideos_roi/example.mp4"
    )


def test_maps_semantic_target_back_to_frozen_workspace_path(tmp_path: Path) -> None:
    workspace = tmp_path / "current/.compat/workspace"
    target = tmp_path / "current/derived/subvideos"
    target.mkdir(parents=True)
    link = workspace / "data/03_subvideos_roi"
    link.parent.mkdir(parents=True)
    link.symlink_to(Path("../../../derived/subvideos"))
    video = target / "example.mp4"
    video.touch()

    assert workspace_portable_path(video, workspace) == (
        "data/03_subvideos_roi/example.mp4"
    )


def test_project_local_root_maps_frozen_paths_without_symlinks(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "workspace/data"
    frozen = "data/03_subvideos_roi/example.mp4"
    semantic = data_root / "derived/subvideos/example.mp4"

    assert resolve_workspace_artifact(frozen, data_root) == semantic
    assert workspace_portable_path(semantic, data_root) == frozen
    assert not any(data_root.rglob("*"))
