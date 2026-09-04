"""B10 统一 CLI 的命令结构、缺参和错误边界。"""

from __future__ import annotations

import pytest

from versioning.cli import main


def test_top_level_help_lists_all_domains(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    for command in ("data", "prompt", "train", "eval", "model", "backup"):
        assert command in output


@pytest.mark.parametrize(
    "argv",
    [
        ["data", "release"],
        ["data", "release_validate"],
        ["prompt", "create"],
        ["train", "create", "train-v4.1-r1"],
        ["eval", "create", "eval-v4.1-r1"],
        ["model", "register", "model-v4.1-r1"],
    ],
)
def test_incomplete_commands_stop_with_usage_error(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert "缺少必填参数" in capsys.readouterr().err


def test_unknown_data_stage_is_fail_closed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["data", "latest"]) == 1
    assert "未知 stage" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["train", "fold-start", "train-v4.1-r1"],
        ["eval", "fold-start", "eval-v4.1-r1"],
        ["eval", "summary", "eval-v4.1-r1"],
    ],
)
def test_non_create_usage_errors_do_not_initialize_store(
    tmp_path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    assert main([*argv, "--root", str(root)]) == 2
    assert "缺少必填参数" in capsys.readouterr().err
    assert not (root / "workspace" / "mlflow").exists()
