"""布局迁移守卫：防止代码 / 配置 / 测试重新写回被撤销的 ``workspace/`` 布局。

目的
----
用户已决定拆除 ``workspace/`` 目录，内容搬到顶层语义目录（``data`` / ``trains`` /
``models`` / ``mlflow`` / ``evaluations`` / ``audits/...`` / ``data-staging`` /
``data-rebuild`` / ``base-models``）。P0+P1 只改代码 / 配置 / 测试与 ``.gitignore``，
物理搬迁留到 P2。本文件是覆盖两个阶段的性质型护栏：只用「存在 / 不存在」「路径段」
这类性质判定，不记录任何收集数、文件数等快照数值。

守卫分三块：

* T1：旧物理路径不该再存在（P2 已完成，``PENDING_PHYSICAL_MOVE`` 必须为空）。
* T2：``evaluations`` 不再位于 ``workspace/`` 之下。
* T3：源码 / 配置里的旧布局字面量（``root / "workspace" / "mlflow"``、
  ``"workspace/models/"``、``workspace/data-staging`` 三种写法）必须清零，
  仅允许 ``versioning/backup.py`` 的「备份包内结构」行用 ``layout-guard-allow``
  标记豁免（标记行还必须同时含 ``workspace/evaluations``，并有行数上限）。
* T4：``pipeline.project_workspace`` 的路径语义直接以仓库根为根。
* T5 / T6：新布局路径不得被 git 跟踪，且必须被 ``.gitignore`` 覆盖。

已知限制
--------
T3 的三条正则只覆盖「引号内的 ``workspace`` 段」与「``workspace`` 后紧跟旧子目录」
两种字面量形态；``Path(root, "workspace")``、``root.joinpath("workspace", "data")``
这类把目录名当独立参数传入的写法不被匹配（刻意不扩大正则：``COMPAT_WORKSPACE_NAME
= "workspace"`` 等合法的兼容常量会被误伤），该缺口由 code review 兜底。

失效条件
--------
物理搬迁完成（P2）且新布局登记进 ``docs/design-facts.yaml`` 之后：把 T1 / T2 的
结论并入 design-facts 的 evidence，或直接删除本文件。二者必居其一，不得无限期
滞留。
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from pipeline.project_workspace import (
    experiment_workspace_paths,
    project_workspace_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

# 目标映射表：旧路径 -> 新路径。T1 以此为唯一判据来源。
LEGACY_TO_FLATTENED = {
    "workspace/data": "data",
    "workspace/runs": "trains",
    "workspace/models": "models",
    "workspace/mlflow": "mlflow",
    "workspace/evaluations": "evaluations",
    "workspace/base-source-audit": "audits/base-source-audit",
    "workspace/review-environment": "audits/review-environment",
    "workspace/data-staging": "data-staging",
    "workspace/data-rebuild": "data-rebuild",
    "models/minicpm-v-4.5": "base-models/minicpmv4_5",
    "models/minicpmv4_5": "base-models/minicpmv4_5",
}

# P2 物理搬迁已完成，本集合必须保持为空；新增旧路径一律视为写回旧布局。
PENDING_PHYSICAL_MOVE: set[str] = set()

# 新布局的顶层目录名。models 走既有规则（models/* 已被忽略），不在 T6 断言内。
FLATTENED_TOP_LEVEL = (
    "data",
    "trains",
    "mlflow",
    "evaluations",
    "audits",
    "data-staging",
    "data-rebuild",
    "base-models/probe",
)


def _flattened() -> bool:
    """P2 物理搬迁完成信号：只有新布局才会出现的目录已经落盘。

    注意这不是 skip：搬迁完成后 T1 会把 ``PENDING_PHYSICAL_MOVE`` 全部按「必须消失」
    判定，T2 会要求 ``evaluations`` 出现在顶层。
    """
    return (REPO_ROOT / "trains").is_dir() or (REPO_ROOT / "evaluations").is_dir()


# --------------------------------------------------------------------------- #
# T1 旧物理目录不存在
# --------------------------------------------------------------------------- #

def test_t1_pending_physical_move_is_subset_of_mapping() -> None:
    """防集合腐烂：PENDING 集合里的每个旧路径都必须是映射表的键。"""
    unknown = sorted(PENDING_PHYSICAL_MOVE - set(LEGACY_TO_FLATTENED))
    assert unknown == [], (
        f"PENDING_PHYSICAL_MOVE 含映射表里不存在的旧路径：{unknown}；"
        "请先把它加进 LEGACY_TO_FLATTENED，或从集合移除"
    )


def test_t1_legacy_physical_paths_are_absent() -> None:
    """除 P2 待搬迁项外，映射表里的旧物理路径必须全部不存在。"""
    flattened = _flattened()
    still_present = [
        old
        for old in LEGACY_TO_FLATTENED
        if (REPO_ROOT / old).exists()
        and not (old in PENDING_PHYSICAL_MOVE and not flattened)
    ]

    assert still_present == [], (
        f"旧路径仍存在，代码可能已写回旧布局：{still_present}；"
        f"新位置应分别是 "
        f"{[LEGACY_TO_FLATTENED[old] for old in still_present]}"
    )


# --------------------------------------------------------------------------- #
# T2 evaluations 布局
# --------------------------------------------------------------------------- #

def test_t2_workspace_evaluations_paths_are_absent() -> None:
    """evaluations 及其 staging 子目录不得位于 workspace/ 之下。"""
    under_workspace = REPO_ROOT / "workspace" / "evaluations"

    assert not under_workspace.exists(), (
        f"旧 evaluations 路径仍存在：{under_workspace}；应迁到 {REPO_ROOT / 'evaluations'}"
    )
    assert not (under_workspace / "staging").exists(), (
        f"旧 evaluations staging 路径仍存在：{under_workspace / 'staging'}；"
        "staging 应随 evaluations 一起迁到顶层"
    )


def test_t2_evaluations_lives_at_top_level_when_flattened() -> None:
    """物理搬迁完成后，evaluations 必须出现在顶层。"""
    if _flattened():  # 完成信号，不是 skip
        assert (REPO_ROOT / "evaluations").is_dir(), (
            "新布局已生效但顶层 evaluations/ 不存在；"
            "evaluations 产物必须有明确落点"
        )


# --------------------------------------------------------------------------- #
# T3 源码静态扫描
# --------------------------------------------------------------------------- #

_OLD_SEGMENTS = r"data|runs|models|mlflow|evaluations|data-staging|data-rebuild"

# 旧布局的三种写法：路径拼接（root / "workspace" / "mlflow"）、字符串前缀
# （"workspace/models/"）、裸路径片段（workspace/data-staging），以及把 workspace
# 直接当作路径根的孤立拼接（root = repo_root / "workspace"）。
_LEGACY_PATTERNS = (
    re.compile(rf"workspace[\"'\s/]*[/\"'\s]+(?:{_OLD_SEGMENTS})\b"),
    re.compile(rf"workspace\s*/\s*\"(?:{_OLD_SEGMENTS})\""),
    re.compile(r"/\s*[\"']workspace[\"']"),
)

# 显式排除的非搬迁对象：.compat/workspace 与 store/workspace/**。
_OUT_OF_SCOPE = re.compile(
    r"(?:\.compat|\bstore)[\"']?\s*[/\s]\s*[\"']?workspace"
)

ALLOW_MARKER = "layout-guard-allow"

# 豁免上限而非等值：备份包内部结构属于历史布局，只能就地标记，不能改写。
_BACKUP_MODULE = "versioning/backup.py"
_BACKUP_ALLOW_LIMIT = 8

# 豁免标记的唯一合法位置：备份包内部结构属于历史布局，只能就地标记、不得改写。
# 任何其它文件出现该标记即视为绕过护栏。
_BACKUP_PACK_STRUCTURE = "workspace/evaluations"

_SCAN_ROOTS = ("pipeline", "versioning", "finetune", "scripts", "delivery", "tests")
_SCAN_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".toml"}
_SKIP_DIR_NAMES = {
    ".venv",
    "__pycache__",
    ".git",
    "docs",
    "records",
    "LlamaFactory",
    "workspace",
}


def _scanned_files() -> Iterator[Path]:
    """按 brief 范围枚举待扫描文件（返回相对仓库根的路径）。"""
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT)
            if any(part in _SKIP_DIR_NAMES for part in rel.parts):
                continue
            if path.resolve() == SELF:
                # 本文件持有旧路径字面量作为守卫数据，自我扫描无意义。
                continue
            yield rel

    for path in sorted(REPO_ROOT.iterdir()):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        if path.resolve() == SELF:
            continue
        yield path.relative_to(REPO_ROOT)


def _legacy_reference_violations() -> list[tuple[str, int, str]]:
    """返回豁免后仍命中旧布局字面量的 (相对路径, 行号, 行文本)。"""
    violations: list[tuple[str, int, str]] = []
    for rel in _scanned_files():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            if _OUT_OF_SCOPE.search(line):
                continue
            if any(pattern.search(line) for pattern in _LEGACY_PATTERNS):
                violations.append((str(rel), lineno, line.strip()))
    return violations


def test_t3_no_legacy_workspace_literals_in_sources() -> None:
    """源码 / 配置 / 测试中不得再出现旧 workspace 布局字面量。"""
    violations = _legacy_reference_violations()
    preview = "\n".join(f"{rel}:{lineno}: {line}" for rel, lineno, line in violations[:20])

    assert violations == [], (
        f"发现 {len(violations)} 处仍引用旧 workspace/ 布局（该目录在迁移后不存在）。\n"
        "只有 versioning/backup.py 的「备份包内结构」行可用 layout-guard-allow 豁免。\n"
        f"前 20 条：\n{preview}"
    )


def _allow_marker_occurrences() -> list[tuple[str, int, str]]:
    """枚举扫描范围内带豁免标记的 (相对路径, 行号, 行文本)。"""
    occurrences: list[tuple[str, int, str]] = []
    for rel in _scanned_files():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                occurrences.append((str(rel), lineno, line.strip()))
    return occurrences


def test_t3_allow_marker_appears_only_in_backup_module() -> None:
    """豁免标记只允许出现在 versioning/backup.py，其它文件出现即视为滥用。"""
    offenders = [
        (rel, lineno, line)
        for rel, lineno, line in _allow_marker_occurrences()
        if rel != _BACKUP_MODULE
    ]
    detail = "\n".join(f"{rel}:{lineno}: {line}" for rel, lineno, line in offenders)

    assert offenders == [], (
        f"豁免标记 {ALLOW_MARKER} 只允许出现在 {_BACKUP_MODULE}，"
        f"但有 {len(offenders)} 处出现在其它文件：\n{detail}\n"
        "布局语义必须真正迁移，不能靠豁免绕过"
    )


def test_t3_backup_allow_marker_only_guards_pack_structure() -> None:
    """backup.py 里被标记的行必须同时含 workspace/evaluations（备份包内结构）。"""
    backup = REPO_ROOT / _BACKUP_MODULE
    if not backup.is_file():  # 不 skip：备份包结构豁免的载体不见了应显式失败
        pytest.fail(f"{_BACKUP_MODULE} 不存在，无法校验 {ALLOW_MARKER} 的适用范围")

    marked_lines = backup.read_text(encoding="utf-8").splitlines()
    misplaced = [
        (lineno, line.strip())
        for lineno, line in enumerate(marked_lines, 1)
        if ALLOW_MARKER in line and _BACKUP_PACK_STRUCTURE not in line
    ]
    detail = "\n".join(f"{_BACKUP_MODULE}:{lineno}: {line}" for lineno, line in misplaced)

    assert misplaced == [], (
        f"{_BACKUP_MODULE} 中被标记的行必须同时含 {_BACKUP_PACK_STRUCTURE!r}"
        f"（豁免只保护备份包内结构），但有 {len(misplaced)} 行不含：\n{detail}"
    )


def test_t3_backup_allow_marker_count_is_within_limit() -> None:
    """backup.py 的豁免行数不得超过上限（性质型上限，不作等值断言）。"""
    backup = REPO_ROOT / _BACKUP_MODULE
    if not backup.is_file():  # 不 skip：备份包结构豁免的载体不见了应显式失败
        pytest.fail(f"{_BACKUP_MODULE} 不存在，无法统计 {ALLOW_MARKER}")

    backup_marked = sum(
        1
        for line in backup.read_text(encoding="utf-8").splitlines()
        if ALLOW_MARKER in line
    )

    assert backup_marked <= _BACKUP_ALLOW_LIMIT, (
        f"{_BACKUP_MODULE} 中有 {backup_marked} 行带 {ALLOW_MARKER}，"
        f"超过上限 {_BACKUP_ALLOW_LIMIT}；豁免只能覆盖历史备份包内部布局"
    )


# --------------------------------------------------------------------------- #
# T4 project_workspace_paths 语义
# --------------------------------------------------------------------------- #

def test_t4_workspace_root_is_repository_root(tmp_path: Path) -> None:
    """项目根即 workspace 根，路径里不再有 workspace 段。"""
    paths = project_workspace_paths(tmp_path)

    assert paths.root == tmp_path.resolve()


def test_t4_children_are_not_nested_under_workspace(tmp_path: Path) -> None:
    """data / runs / models 等子路径的首段都不是 workspace。"""
    paths = project_workspace_paths(tmp_path)
    repo_root = tmp_path.resolve()
    nested = {
        name: str(getattr(paths, name))
        for name in (
            "data",
            "runs",
            "models",
            "model_releases",
            "model_archive",
        )
        if getattr(paths, name).relative_to(repo_root).parts[0] == "workspace"
    }

    assert nested == {}, f"这些路径仍落在 workspace 下：{nested}"


def test_t4_child_directory_names_follow_flattened_layout(tmp_path: Path) -> None:
    """子目录名与顶层语义目录一致（runs -> trains）。"""
    paths = project_workspace_paths(tmp_path)

    assert paths.runs.name == "trains"
    assert paths.data.name == "data"
    assert paths.models.name == "models"
    assert paths.model_releases.name == "releases"


def test_t4_experiment_run_dir_lands_in_trains(tmp_path: Path) -> None:
    """实验运行目录首段是 trains。"""
    paths = experiment_workspace_paths(tmp_path, "v4.1-x-v1-seed1")

    assert paths.run_dir.relative_to(tmp_path.resolve()).parts[0] == "trains"


# --------------------------------------------------------------------------- #
# T5 git 跟踪
# --------------------------------------------------------------------------- #

def test_t5_flattened_paths_are_not_git_tracked() -> None:
    """新布局目录下不得有被 git 跟踪的文件（产物归训练机，不进仓库）。"""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            "data",
            "trains",
            "models",
            "mlflow",
            "evaluations",
            "audits",
            "data-staging",
            "data-rebuild",
            "base-models",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "", (
        f"新布局目录下有被 git 跟踪的文件：\n{result.stdout}"
    )


# --------------------------------------------------------------------------- #
# T6 gitignore 覆盖
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", FLATTENED_TOP_LEVEL)
def test_t6_gitignore_covers_flattened_path(path: str) -> None:
    """新布局目录必须被 .gitignore 覆盖。"""
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f".gitignore 未覆盖新布局路径 {path!r}（git check-ignore 返回 "
        f"{result.returncode}）"
    )
