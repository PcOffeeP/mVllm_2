"""布局守卫与项目目录用例共用的仓库形状探针。

文件名刻意不以 ``test_`` 开头，pytest 不会收集它。

本模块回答两个与 sparse-checkout 部分检出有关的问题：

* ``PIPELINE_AVAILABLE``：``pipeline`` 包在本 worktree 是否可导入。本 worktree 是
  non-cone sparse-checkout，白名单不含 ``pipeline/``，因此磁盘上没有该目录。依赖
  它的用例据此**显式、可计数**地跳过（``requires_pipeline``），而不是把整个测试
  模块静默跳过——不依赖 ``pipeline`` 的用例必须真正执行。
* ``sparse_checkout_excludes(rel)``：给定已跟踪路径是否属于「索引里有、本 worktree
  未检出」的 sparse-checkout 排除项。用于把「部分检出造成的环境缺口」与「文件真被
  删除 / 挪走」区分开：前者可数跳过，后者必须仍然硬失败。

判定方式
--------
``PIPELINE_AVAILABLE`` 只用 ``importlib.util.find_spec`` 查 spec，不真正 import
``pipeline`` 包（避免收集期副作用），任何异常都按「不可用」处理。

``sparse_checkout_excludes`` 依赖 ``git ls-files -t`` 的标记位：skip-worktree 项为
大写 ``S``（后接一个空格），普通已跟踪项为 ``H``。实测（本 worktree）：

* ``git ls-files -t -- versioning/backup.py`` -> ``S versioning/backup.py``
  （索引有、磁盘无、被 sparse-checkout 排除）
* ``git ls-files -t -- tests/test_project_workspace.py`` -> ``H tests/test_project_workspace.py``
* 未被跟踪的路径 -> 输出为空

失效条件
--------
sparse-checkout 恢复为完整检出（白名单包含 ``pipeline/`` 与 ``versioning/``）后，
``PIPELINE_AVAILABLE`` 恒为 True、``sparse_checkout_excludes`` 恒为 False，本模块
只剩兼容价值；确认无调用点后可整体删除。
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

PIPELINE_SKIP_REASON = (
    "sparse-checkout 未检出 pipeline/：本 worktree 的部分检出白名单不含 pipeline/，"
    "该用例依赖 pipeline 包，无法在本机执行"
)


def _probe_pipeline_available() -> bool:
    """只查 spec、不真正 import 包；不检出与导入失败都按不可用处理。"""
    try:
        return importlib.util.find_spec("pipeline") is not None
    except Exception:  # 探针不得把「跳过判定」变成收集期异常
        return False


PIPELINE_AVAILABLE: bool = _probe_pipeline_available()

# 依赖 pipeline 包的用例统一挂这个标记；理由可逐条在 -rs 输出里看到。
requires_pipeline = pytest.mark.skipif(
    not PIPELINE_AVAILABLE,
    reason=PIPELINE_SKIP_REASON,
)


def sparse_checkout_excludes(rel: str) -> bool:
    """该已跟踪路径是否被 sparse-checkout 排除（索引有、worktree 里没有）。

    ``rel`` 是相对仓库根的 POSIX 路径。未被跟踪的路径返回 False（不属 sparse 排除）。
    """
    result = subprocess.run(
        ["git", "ls-files", "-t", "--", rel],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return any(line.startswith("S ") for line in result.stdout.splitlines())
