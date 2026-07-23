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
    workspace_relative_path,
)

ROOT = Path(__file__).resolve().parents[1]


def test_committed_profiles_use_distinct_roots() -> None:
    config = load_config(ROOT / "config/data_roots.json")

    assert config["profiles"]["tensile-vlm/v2"]["directory"] == "v2"
    assert config["profiles"]["tensile-vlm/v2"]["git_ref"] == "tensile-vlm-v2-final"
    assert config["profiles"]["tensile-vlm/v2"]["lifecycle"] == "frozen"
    assert config["profiles"]["tensile-vlm/v4.1"]["directory"] == "v4_1"
    assert config["profiles"]["tensile-vlm/v4.1"]["git_ref"] == "main"
    assert config["profiles"]["tensile-vlm/v4.1"]["lifecycle"] == "active"


def test_initialize_and_validate_versioned_roots(tmp_path: Path) -> None:
    config = load_config(ROOT / "config/data_roots.json")

    v2 = initialize_root(config, "tensile-vlm/v2", data_home=tmp_path)
    v4_1 = initialize_root(config, "tensile-vlm/v4.1", data_home=tmp_path)

    assert v2 != v4_1
    assert validate_root(
        config,
        "tensile-vlm/v2",
        data_home=tmp_path,
    )["lifecycle"] == "frozen"
    assert validate_root(
        config,
        "tensile-vlm/v4.1",
        data_home=tmp_path,
    )["lifecycle"] == "active"


def test_rejects_contract_mismatch(tmp_path: Path) -> None:
    config = load_config(ROOT / "config/data_roots.json")
    root = initialize_root(config, "tensile-vlm/v2", data_home=tmp_path)
    marker_path = root / ".tensile-data-root.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["contract_version"] = "tensile-vlm/v4.1"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(DataRootError, match="contract_version"):
        validate_root(config, "tensile-vlm/v2", data_home=tmp_path)


def test_workspace_links_stay_inside_version_root(tmp_path: Path) -> None:
    config = load_config(ROOT / "config/data_roots.json")
    root = initialize_root(config, "tensile-vlm/v4.1", data_home=tmp_path)
    for target_name in config["profiles"]["tensile-vlm/v4.1"]["workspace_links"].values():
        (root / target_name).mkdir(parents=True, exist_ok=True)

    workspace = initialize_workspace(
        config,
        "tensile-vlm/v4.1",
        data_home=tmp_path,
    )
    result = validate_workspace(
        config,
        "tensile-vlm/v4.1",
        data_home=tmp_path,
    )

    assert result["link_count"] == 8
    assert (workspace / "data/03_subvideos_roi").resolve() == (
        root / "processing/03_subvideos_roi"
    ).resolve()


def test_remaps_frozen_absolute_data_path_without_following_symlink(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "v4_1/workspace"
    old = Path("/old/machine/project/data/03_subvideos_roi/example.mp4")

    mapped = resolve_workspace_artifact(old, workspace)

    assert mapped == workspace / "data/03_subvideos_roi/example.mp4"
    assert workspace_relative_path(mapped, workspace) == (
        "data/03_subvideos_roi/example.mp4"
    )
