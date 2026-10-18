"""`scripts/verify_design_facts.py --check-doc-paths` 的回归测试。

每个用例都在 `tmp_path` 里造一个假仓库（`git init` + `git add` 进索引，模式本身只用
`ls-files`，不需要 commit），再用真实脚本对着它跑一遍，只读仓库内的脚本文件。
断言覆盖退出码与具体文案（`MISSING <路径>` / `PASS`），避免「什么都没检查」也算通过。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_design_facts.py"


def _run(root: Path) -> subprocess.CompletedProcess:
    """在 `root` 里对真实脚本跑一次 `--check-doc-paths`。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check-doc-paths", "--root", str(root)],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git_index(root: Path) -> None:
    """建仓并把当前文件全部加入索引（`--check-doc-paths` 只扫受跟踪的 md）。"""
    for command in (["git", "init", "-q"], ["git", "add", "-A"]):
        subprocess.run(command, cwd=str(root), check=True, capture_output=True, text=True)


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
    assert "docs/results/nope-missing.md" not in _missing_refs(result.stdout), _context(result)


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
