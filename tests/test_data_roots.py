from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.data_roots import (
    COMPAT_WORKSPACE_NAME,
    DataRootError,
    initialize_root,
    initialize_workspace,
    is_data_root_shaped,
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
    assert workspace.joinpath("data/03_subvideos_roi").resolve() == (
        root / "derived/subvideos"
    ).resolve()


def test_remaps_frozen_absolute_data_path_without_following_symlink(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "current/.compat/workspace"
    old = Path("/old/machine/project/data/03_subvideos_roi/example.mp4")

    mapped = resolve_workspace_artifact(old, workspace)

    assert mapped == workspace.joinpath("data/03_subvideos_roi/example.mp4")
    assert workspace_relative_path(mapped, workspace) == (
        "data/03_subvideos_roi/example.mp4"
    )


def test_maps_semantic_target_back_to_frozen_workspace_path(tmp_path: Path) -> None:
    workspace = tmp_path / "current/.compat/workspace"
    target = tmp_path / "current/derived/subvideos"
    target.mkdir(parents=True)
    link = workspace.joinpath("data/03_subvideos_roi")
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
    data_root = tmp_path.joinpath(COMPAT_WORKSPACE_NAME, "data")
    frozen = "data/03_subvideos_roi/example.mp4"
    semantic = data_root / "derived/subvideos/example.mp4"

    assert resolve_workspace_artifact(frozen, data_root) == semantic
    assert workspace_portable_path(semantic, data_root) == frozen
    assert not any(data_root.rglob("*"))


# --------------------------------------------------------------------------- #
# 扁平化后的顶层数据根（``<repo>/data``）解析契约
# --------------------------------------------------------------------------- #


def _assert_no_duplicated_data_segment(path: Path) -> None:
    """断言解析结果里没有连续重复的 ``data`` 段。"""
    segments = Path(path).parts
    duplicated = [
        index
        for index, (left, right) in enumerate(zip(segments, segments[1:]))
        if left == "data" and right == "data"
    ]

    assert duplicated == [], (
        f"解析结果出现 {len(duplicated)} 处连续 data/data 段"
        f"（位置 {duplicated}）：{path}；"
        "说明顶层数据根没有被识别为数据根，legacy 编号身份被当成字面子路径拼接"
    )


def test_top_level_data_root_maps_frozen_numbered_paths(tmp_path: Path) -> None:
    """顶层 ``<repo>/data`` 数据根 + 显式 project_local=True 应走 legacy 语义映射。

    扁平化后项目数据根直接是 ``<repo>/data``，没有可供内省的旧工作区目录段，
    因此重映射只能由调用方显式声明 project_local。声明之后 ``data/03_subvideos``
    必须落到 ``derived/subvideos``，而不是拼成数据根下的编号子目录副本。
    """
    data_root = tmp_path / "data"
    (data_root / "derived/subvideos").mkdir(parents=True)
    expected = data_root / "derived/subvideos/x.mp4"

    mapped = resolve_workspace_artifact(
        "data/03_subvideos/x.mp4", data_root, project_local=True
    )

    assert mapped == expected, (
        "应走 legacy 语义映射（data/03_subvideos -> derived/subvideos）："
        "顶层数据根 + project_local=True 时编号身份是语义别名，不是字面目录名；"
        f"期望 {expected}，实际 {mapped}"
    )
    _assert_no_duplicated_data_segment(mapped)


def test_top_level_data_root_without_flag_keeps_literal_join(tmp_path: Path) -> None:
    """契约（**不是**期望行为）：重映射必须由调用方显式声明 project_local。

    默认 project_local=False 时只保留搬迁前旧布局的兼容判定
    （旧工作区目录段下的 data 目录）。顶层 ``<repo>/data`` 末段同样叫 data，
    但父目录不是旧布局的工作区目录，因此不被识别为数据根，解析退化为字面拼接，
    得到数据根下的 ``data/03_subvideos/x.mp4``，该路径并不存在。

    本用例把这个「必须显式声明」的契约钉死：若有人把默认值改为 True，
    或加入「末段名为 data 即视为数据根」的隐式内省，本条会失败。
    """
    data_root = tmp_path / "data"
    data_root.mkdir()
    frozen = "data/03_subvideos/x.mp4"
    expected_literal = data_root / frozen

    literal = resolve_workspace_artifact(frozen, data_root)

    assert literal == expected_literal, (
        "未声明 project_local 时必须保持字面拼接"
        "（重映射需要调用方显式声明，不能靠实参形状隐式推断）："
        f"期望 {expected_literal}，实际 {literal}"
    )
    assert not literal.exists(), (
        "字面拼接出的编号路径不应存在"
        f"（真实数据在 derived/ 下，说明此处已漏传 project_local）：{literal}"
    )


def test_top_level_data_root_absolute_frozen_path_maps(tmp_path: Path) -> None:
    """跨机 manifest 里的绝对冻结身份在顶层数据根下同样按语义映射。"""
    data_root = tmp_path / "data"
    (data_root / "derived/subvideos").mkdir(parents=True)
    frozen = Path("/mnt/remote/data/03_subvideos_roi/x.mp4")
    expected = data_root / "derived/subvideos/x.mp4"

    mapped = resolve_workspace_artifact(frozen, data_root, project_local=True)

    assert mapped == expected, (
        "绝对路径中 data 之后的后缀应走 legacy 语义映射"
        "（data/03_subvideos_roi -> derived/subvideos）："
        f"期望 {expected}，实际 {mapped}"
    )
    _assert_no_duplicated_data_segment(mapped)


def test_release_media_root_is_not_treated_as_data_root(tmp_path: Path) -> None:
    """发布媒体根 ``<数据版本根>/releases/<版本>/media`` 不做语义重映射。

    该子树的末段是 media 而不是 data，历史视频就存放在这里，
    编号身份对它是真实子路径；若重映射到 derived/ 会指向不存在的目录，
    故必须保持字面拼接。
    """
    media_root = tmp_path / "data/releases/v1/media"
    media_root.mkdir(parents=True)
    frozen = "data/03_subvideos/x.mp4"
    expected_literal = media_root / frozen

    literal = resolve_workspace_artifact(frozen, media_root)

    assert literal == expected_literal, (
        "发布媒体根不是受管数据根，必须保持字面拼接"
        "（编号身份在此就是真实子路径，不得映射到 derived/）："
        f"期望 {expected_literal}，实际 {literal}"
    )


def test_is_data_root_shaped(tmp_path: Path) -> None:
    """形状判定：只有末段名为 data 的实参才是数据根候选。"""
    shaped = [
        tmp_path / "data",
        tmp_path / "data-staging/run/data",
        tmp_path / "data-rebuild/run/data",
        tmp_path / "x" / COMPAT_WORKSPACE_NAME / "data",
    ]
    unshaped = [
        tmp_path / "data/releases/v1/media",
        tmp_path / "p/payload",
        tmp_path / "data/derived",
    ]

    wrongly_rejected = [str(path) for path in shaped if not is_data_root_shaped(path)]
    wrongly_accepted = [str(path) for path in unshaped if is_data_root_shaped(path)]

    assert wrongly_rejected == [], (
        "这些实参末段名为 data，应判定为数据根形状"
        f"（否则调用方拿不到 project_local 依据）：{wrongly_rejected}"
    )
    assert wrongly_accepted == [], (
        "这些实参不是受管数据根（发布媒体根 / 七阶段 payload 根 / derived 子目录），"
        "不应判定为数据根形状，否则会把它们的编号身份误重映射到 derived/："
        f"{wrongly_accepted}"
    )


def test_caller_idiom_declares_project_local_only_for_data_root_shaped_media(
    tmp_path: Path,
) -> None:
    """调用方写法：``project_local=is_data_root_shaped(media_root)``。

    finetune/train_build_dataset.py 与 finetune/eval_run.py 以该写法把媒体根
    形状转成 project_local 声明。本用例钉住「媒体根是顶层 ``<repo>/data``
    形状时，冻结编号身份必须解析到 derived/」，防止调用方漏传 flag 后
    静默退化成数据根下的编号副本（发布媒体根的否定方向见
    ``test_release_media_root_is_not_treated_as_data_root`` 与
    ``test_is_data_root_shaped``）。
    """
    media_root = tmp_path / "data"
    (media_root / "derived/subvideos").mkdir(parents=True)
    frozen = "data/03_subvideos_roi/x.mp4"
    expected = media_root / "derived/subvideos/x.mp4"

    resolved = resolve_workspace_artifact(
        frozen, media_root, project_local=is_data_root_shaped(media_root)
    )

    assert resolved == expected, (
        "is_data_root_shaped(顶层数据根) 应为 True 并触发 legacy 语义映射"
        "（data/03_subvideos_roi -> derived/subvideos）："
        f"期望 {expected}，实际 {resolved}"
    )
    _assert_no_duplicated_data_segment(resolved)
