"""`scripts/verify_design_facts.py --check-doc-paths` 的回归测试。

每个用例都在 `tmp_path` 里造一个假仓库（`git init` + `git add` 进索引，模式本身只用
`ls-files`，不需要 commit），再用真实脚本对着它跑一遍，只读仓库内的脚本文件。
断言覆盖退出码与具体文案（`MISSING <路径>` / `PASS`），避免「什么都没检查」也算通过。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_design_facts.py"


def _child_env() -> dict[str, str]:
    """去掉 `GIT_*` 变量：父进程若设了 `GIT_DIR` / `GIT_WORK_TREE` / `GIT_INDEX_FILE`，
    子进程里的 `git init` / `git add` 与被测脚本的 `git ls-files` 都会落到别的仓库上。"""
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _run(root: Path) -> subprocess.CompletedProcess:
    """在 `root` 里对真实脚本跑一次 `--check-doc-paths`。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check-doc-paths", "--root", str(root)],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_child_env(),
    )


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git_index(root: Path) -> None:
    """建仓并把当前文件全部加入索引（`--check-doc-paths` 只扫受跟踪的 md）。"""
    for command in (["git", "init", "-q"], ["git", "add", "-A"]):
        subprocess.run(
            command,
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_child_env(),
        )


def _context(result: subprocess.CompletedProcess) -> str:
    """断言失败时把诊断信息带进失败消息。"""
    return (
        f"\nreturncode={result.returncode}"
        f"\nstdout:\n{result.stdout}"
        f"\nstderr:\n{result.stderr}"
    )


def _missing_refs(stdout: str) -> list[str]:
    """取 `MISSING <路径>  <- 文件:行` 行里被判缺失的路径。"""
    refs = []
    for line in stdout.splitlines():
        if line.startswith("MISSING "):
            refs.append(line.split()[1])
    return refs


def test_missing_referenced_path_fails_the_check(tmp_path: Path):
    _write(tmp_path, "docs/a.md", "示例见 docs/results/nope-missing.md 。\n")
    _git_index(tmp_path)

    result = _run(tmp_path)

    assert result.returncode != 0, _context(result)
    assert "MISSING docs/results/nope-missing.md" in result.stdout, _context(result)


def test_existing_referenced_path_passes_the_check(tmp_path: Path):
    _write(tmp_path, "docs/a.md", "示例见 docs/results/nope-missing.md 。\n")
    _write(tmp_path, "docs/results/nope-missing.md", "# 占位\n")
    _git_index(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0, _context(result)
    assert "PASS" in result.stdout, _context(result)
    assert _missing_refs(result.stdout) == [], _context(result)


def test_allowlisted_reference_is_exempt_from_missing_check(tmp_path: Path):
    _write(tmp_path, "docs/a.md", "示例见 docs/results/nope-missing.md 。\n")
    # `refs:` 用 `re.fullmatch` 匹配引用路径本身，因此 `.` 要转义。
    _write(
        tmp_path,
        "scripts/doc-path-allowlist.txt",
        "# 计划中的路径，尚未创建\nrefs: docs/results/nope-missing\\.md\n",
    )
    _git_index(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0, _context(result)
    assert "PASS" in result.stdout, _context(result)
    # 断言「确实走了豁免分支」：只断言退出 0 无法排除「有白名单就整体豁免」的假绿。
    assert "白名单豁免 1 处" in result.stdout, _context(result)


def test_allowlist_rule_that_matches_nothing_does_not_exempt(tmp_path: Path):
    # 负向控制：白名单文件存在、但规则不匹配该引用时，缺口路径仍必须判 MISSING。
    _write(tmp_path, "docs/a.md", "示例见 docs/results/nope-missing.md 。\n")
    _write(
        tmp_path,
        "scripts/doc-path-allowlist.txt",
        "# 规则指向另一个路径，与被引用的缺口路径无关\nrefs: docs/results/other\\.md\n",
    )
    _git_index(tmp_path)

    result = _run(tmp_path)

    assert result.returncode != 0, _context(result)
    assert "MISSING docs/results/nope-missing.md" in result.stdout, _context(result)
    assert "白名单豁免 0 处" in result.stdout, _context(result)


def test_dot_prefixed_references_resolve_without_false_missing(tmp_path: Path):
    # `./` 前缀：按「仓库根」解析命中 docs/exists.md
    _write(tmp_path, "docs/root.md", "同类文件见 ./docs/exists.md 。\n")
    _write(tmp_path, "docs/exists.md", "# exists\n")
    # `../` 前缀：只能按「引用所在 md 的目录」解析命中 docs/target.md
    _write(tmp_path, "docs/nested.md", "上级目录见 ../docs/target.md 。\n")
    _write(tmp_path, "docs/target.md", "# target\n")
    _git_index(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0, _context(result)
    assert "PASS" in result.stdout, _context(result)
    assert _missing_refs(result.stdout) == [], _context(result)
    # 两条引用都要真的被抽取判定，避免 `./` `../` 因提取失败而「零引用即 PASS」。
    assert "合计 2 处引用" in result.stdout, _context(result)
    # 两条基址各命中一次：`./` 只能按仓库根命中，`../` 只能按引用所在 md 的目录命中。
    assert "存在 2 处（root 1、file 1、both 0）" in result.stdout, _context(result)


# --------------------------------------------------------------------------- #
# `files:` 单条件、`refs:` + `files:` 双条件与变异自证
#
# 这一组用例守住 `_match_rule` 的 AND 语义：`ref` / `file` 非 None 时必须各自 fullmatch，
# 任一不匹配都不得豁免。E/F/G 是同一缺陷的三种照妖镜（files 恒真、refs 恒真、任一条件被忽略），
# H 用真实源码的变异副本把 F 的红绿关系固化成机器可验证的断言。
# --------------------------------------------------------------------------- #
MISSING_REF = "versioning/nope_missing.py"
REF_MD = "docs/tasks/x.md"
_ALLOWLIST = "scripts/doc-path-allowlist.txt"


def _run_script(script: Path, root: Path) -> subprocess.CompletedProcess:
    """同 `_run`，但可指定脚本副本（变异自证需要跑临时目录里的改写版）。"""
    return subprocess.run(
        [sys.executable, str(script), "--check-doc-paths", "--root", str(root)],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_child_env(),
    )


def _repo_with_missing_ref(root: Path, allowlist: str) -> None:
    """造一个「md 引用不存在路径 + 给定白名单」的假仓库。"""
    _write(root, REF_MD, f"示例见 {MISSING_REF} 。\n")
    _write(root, _ALLOWLIST, allowlist)
    _git_index(root)


def test_files_only_rule_exempts_references_in_matching_file(tmp_path: Path):
    # E：只给 `files:` 时，ref 为 None，`files` 命中即整篇豁免。
    _repo_with_missing_ref(tmp_path, "files: docs/tasks/.*\n")

    result = _run(tmp_path)

    assert result.returncode == 0, _context(result)
    assert "PASS" in result.stdout, _context(result)
    assert _missing_refs(result.stdout) == [], _context(result)
    # 断言「确实走了 files 分支的豁免」，而非引用没被抽取（零引用会判 FAIL）。
    assert "白名单豁免 1 处" in result.stdout, _context(result)


def test_files_only_rule_does_not_exempt_when_file_not_matching(tmp_path: Path):
    # F：防恒真关键用例——`files:` 不匹配引用所在文件时绝不能豁免。
    _repo_with_missing_ref(tmp_path, "files: docs/other/.*\n")

    result = _run(tmp_path)

    assert result.returncode == 1, _context(result)
    assert f"MISSING {MISSING_REF}" in result.stdout, _context(result)
    assert _missing_refs(result.stdout) == [MISSING_REF], _context(result)
    assert "白名单豁免 0 处" in result.stdout, _context(result)
    # 规则被读入但 0 命中：证明白名单确实被解析过，不是文件被整体忽略。
    assert "UNUSED RULE" in result.stdout, _context(result)


@pytest.mark.parametrize(
    ("allowlist_line", "expected_returncode", "expect_missing"),
    [
        pytest.param(
            "refs: versioning/nope_missing\\.py files: docs/other/.*\n",
            1,
            True,
            id="g1-ref-matches-file-does-not",
        ),
        pytest.param(
            "refs: versioning/other\\.py files: docs/tasks/.*\n",
            1,
            True,
            id="g2-file-matches-ref-does-not",
        ),
        pytest.param(
            "refs: versioning/nope_missing\\.py files: docs/tasks/.*\n",
            0,
            False,
            id="g3-both-match",
        ),
    ],
)
def test_refs_and_files_conditions_must_both_match(
    tmp_path: Path, allowlist_line: str, expected_returncode: int, expect_missing: bool
):
    # G：同行 `refs:` + `files:` 是 AND 语义，只匹配一边不得豁免（正则按 fullmatch 全整匹配）。
    _repo_with_missing_ref(tmp_path, allowlist_line)

    result = _run(tmp_path)

    assert result.returncode == expected_returncode, _context(result)
    if expect_missing:
        assert f"MISSING {MISSING_REF}" in result.stdout, _context(result)
        assert _missing_refs(result.stdout) == [MISSING_REF], _context(result)
        assert "白名单豁免 0 处" in result.stdout, _context(result)
    else:
        assert "PASS" in result.stdout, _context(result)
        assert _missing_refs(result.stdout) == [], _context(result)
        assert "白名单豁免 1 处" in result.stdout, _context(result)


def test_files_branch_forced_true_is_caught_by_case_f(tmp_path: Path):
    # H：变异自证——把 `_match_rule` 的 files 分支改成「永不拦截」（恒真）后，
    # F 的负向判据必须失效（returncode 由 1 变 0）。这样 F 的红绿关系被机器固化：
    # 若有人把 files 判定写成恒真，F 会红；F 绿则说明 files 分支真的在拦截。
    original = SCRIPT.read_text(encoding="utf-8")
    guard = 'if rule["file"] is not None and not rule["file"].fullmatch(md_file):'
    assert original.count(guard) == 1, "变异锚点在源码里不再唯一，需先复核 scripts/verify_design_facts.py"
    mutated_guard = "if False and " + guard[len("if "):]
    mutated = original.replace(guard, mutated_guard)
    assert mutated != original, "变异替换未命中，脚本源码可能已改动"

    _repo_with_missing_ref(tmp_path, "files: docs/other/.*\n")
    mutated_script = tmp_path / "mutated_verify_design_facts.py"
    mutated_script.write_text(mutated, encoding="utf-8")

    # 变异副本跑到 F 场景：恒真缺陷让 files 不匹配也豁免，负向判据失效。
    mutated_result = _run_script(mutated_script, tmp_path)
    # 同一场景用原脚本对照：证明失败只来自变异本身，不是环境或假仓库的问题。
    original_result = _run(tmp_path)

    assert mutated_result.returncode == 0, (
        "变异副本没有复现恒真缺陷（说明变异锚点已漂移）" + _context(mutated_result)
    )
    assert _missing_refs(mutated_result.stdout) == [], _context(mutated_result)
    assert original_result.returncode == 1, _context(original_result)
    assert f"MISSING {MISSING_REF}" in original_result.stdout, _context(original_result)
