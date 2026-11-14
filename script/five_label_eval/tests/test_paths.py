"""Contract tests for `paths.load_profile`.

Every config here is injected through `config_path` into pytest's `tmp_path`; the shipped
`config/eval_paths.json` and the real home directory are never read, so no absolute path
literal appears in this file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from script.five_label_eval import paths

# 明显相对的临时值：解析后必须落到仓库根下。
RELATIVE_VALUE = "relative/only/scratch/dir"
HOME_VALUE = "~/x/y"
PLACEHOLDER_VALUE = "TODO_MIGRATION_FILL:output_dir"
# 独立推导的仓库根：本文件位于 <repo>/script/five_label_eval/tests/test_paths.py，故 parents[3]
# 就是仓库根。期望值刻意不引用 `paths.REPO_ROOT`，否则把该常量改坏时本文件会跟着一起变绿。
REPO_ROOT_FROM_TEST_FILE = Path(__file__).resolve().parents[3]


def profile_values(**overrides):
    """Nine key values: one relative path plus one `~` path, all in scratch space."""
    values = {key: f"{RELATIVE_VALUE}/{key}" for key in paths.PROFILE_KEYS}
    values["source_videos"] = HOME_VALUE
    values.update(overrides)
    return values


def write_config(tmp_path, profiles, name="eval_paths.json"):
    """Write a minimal `profiles` config and return its scratch path."""
    path = tmp_path / name
    path.write_text(json.dumps({"schema": "five-label-eval-paths/1", "profiles": profiles}),
                    encoding="utf-8")
    return path


def test_load_profile_should_return_exactly_the_nine_profile_keys_as_paths(tmp_path):
    config = write_config(tmp_path, {"scratch": profile_values()})

    profile = paths.load_profile("scratch", config_path=config)

    assert len(paths.PROFILE_KEYS) == 9
    assert set(profile) == set(paths.PROFILE_KEYS)
    assert all(isinstance(value, Path) for value in profile.values())


def test_load_profile_should_join_relative_value_onto_repository_root(tmp_path):
    # Arrange：独立推导的仓库根必须真的指向工作树（script/ 目录在此下方）。
    assert (REPO_ROOT_FROM_TEST_FILE / "script" / "five_label_eval").is_dir()
    config = write_config(tmp_path, {"scratch": profile_values(sub_video_dir=RELATIVE_VALUE)})

    # Act
    profile = paths.load_profile("scratch", config_path=config)

    # Assert
    assert profile["sub_video_dir"].is_absolute()
    assert profile["sub_video_dir"] == REPO_ROOT_FROM_TEST_FILE / RELATIVE_VALUE
    # 尾段原样保留：拼接不能吞掉或改写相对值的分段。
    assert profile["sub_video_dir"].parts[-len(RELATIVE_VALUE.split("/")):] == tuple(RELATIVE_VALUE.split("/"))


def test_load_profile_should_expand_home_prefix(tmp_path):
    config = write_config(tmp_path, {"scratch": profile_values(source_videos=HOME_VALUE)})

    profile = paths.load_profile("scratch", config_path=config)

    assert profile["source_videos"] == Path(HOME_VALUE).expanduser()
    assert "~" not in str(profile["source_videos"])
    assert profile["source_videos"].is_absolute()


def test_load_profile_should_list_available_profiles_when_name_unknown(tmp_path):
    config = write_config(tmp_path, {"alpha": profile_values(), "beta": profile_values()})

    with pytest.raises(paths.EvalPathError) as excinfo:
        paths.load_profile("gamma", config_path=config)

    message = str(excinfo.value)
    assert "alpha" in message
    assert "beta" in message


def test_load_profile_should_name_the_missing_key(tmp_path):
    values = profile_values()
    del values["sub_video_manifest"]
    config = write_config(tmp_path, {"scratch": values})

    with pytest.raises(paths.EvalPathError) as excinfo:
        paths.load_profile("scratch", config_path=config)

    assert "sub_video_manifest" in str(excinfo.value)


@pytest.mark.parametrize("bad_value", [None, "", 3])
def test_load_profile_should_name_key_whose_value_is_not_nonempty_text(tmp_path, bad_value):
    config = write_config(tmp_path, {"scratch": profile_values(roi_videos=bad_value)})

    with pytest.raises(paths.EvalPathError) as excinfo:
        paths.load_profile("scratch", config_path=config)

    assert "roi_videos" in str(excinfo.value)


def test_load_profile_should_keep_placeholder_value_outside_repository(tmp_path):
    config = write_config(tmp_path, {"gpu-like": profile_values(output_dir=PLACEHOLDER_VALUE)})

    profile = paths.load_profile("gpu-like", config_path=config)

    assert profile["output_dir"].is_absolute()
    assert not str(profile["output_dir"]).startswith(str(paths.REPO_ROOT))
    assert paths.is_placeholder(profile) is True
    assert paths.is_placeholder(profile, "output_dir") is True


def test_is_placeholder_should_be_true_for_a_raw_unresolved_placeholder_value():
    """配置里未解析的原始值（不经 load_profile）也必须被识别为占位，否则消费方会当真路径用。"""
    raw_profile = {"output_dir": PLACEHOLDER_VALUE}

    assert paths.is_placeholder(raw_profile, "output_dir") is True


def test_is_placeholder_should_be_false_for_a_raw_ordinary_value():
    raw_profile = {"output_dir": "data/x"}

    assert paths.is_placeholder(raw_profile, "output_dir") is False


def test_is_placeholder_should_be_false_for_an_ordinary_profile(tmp_path):
    config = write_config(tmp_path, {"scratch": profile_values()})

    profile = paths.load_profile("scratch", config_path=config)

    assert paths.is_placeholder(profile) is False
    assert paths.is_placeholder(profile, "output_dir") is False


def test_load_profile_should_raise_when_config_file_missing(tmp_path):
    with pytest.raises(paths.EvalPathError):
        paths.load_profile("scratch", config_path=tmp_path / "absent.json")
