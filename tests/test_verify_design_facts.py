"""`scripts/verify_design_facts.py` 的回归测试。

每个用例都在 `tmp_path` 里造一个假仓库（`git init` + `git add` 进索引，模式本身只用
`ls-files`，不需要 commit），再用真实脚本对着它跑一遍，只读仓库内的脚本文件。
断言覆盖退出码与具体文案（`MISSING <路径>` / `PASS`），避免「什么都没检查」也算通过。

后半部分（I/J/K/L 与 `--render`）覆盖 evidence 的内容断言：`{ref, expect}` 映射写法、
新旧格式的输出标记（`PASS` / `PASS(no-expect)` / `FAIL`）、无内容断言的计数、validate 模式的
`--root`，以及渲染时是否把 expect 片段一并写进 md。

末尾一组用例守住「evidence 映射的形状必须被强制」这条契约：映射缺 `ref`、`ref` 非字符串或不带行号、
键名拼错、缺 `expect`、`expect` 为空 / null / 非字符串 / 含换行时一律 FAIL，不得静默降级成
`PASS(no-expect)`；`--render` 遇到同样的形状时 fail-closed（退出 1、不写 md）。
"""
from __future__ import annotations

import importlib.util
import os
import re
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


# --------------------------------------------------------------------------- #
# evidence 的内容断言（`{ref, expect}`）、旧格式兼容、validate 模式 `--root` 与渲染
#
# 目标契约（用户已授权改实现）：
# - evidence 支持字符串 `path:LINE`（旧格式）与映射 `{ref: path:LINE, expect: 片段}`；
# - 有 expect 时目标行必须**包含**该片段，否则判 FAIL，且失败文案同带期望片段与实际行内容；
# - 无 expect 时保持旧行为，但输出标记 `PASS(no-expect)`，不判 FAIL；
# - validate 模式逐条 evidence 打印 `PASS` / `PASS(no-expect)` / `FAIL`，总结区给出
#   `无内容断言的 evidence：N 条`，出现 FAIL 退出 1，全 PASS 退出 0；
# - validate 支持 `--root <仓库根>`，语义与 `--check-doc-paths` 一致。
#
# tmp 仓库里的阈值事实与 md 渲染都按真实规则构造成「本来就该通过」，这样断言咬住的是 evidence
# 判定本身，而不是被无关检查的噪音带偏（见 `_build_design_facts_repo` 的注释）。
# --------------------------------------------------------------------------- #
DEFAULT_YAML = "docs/design-facts.yaml"
DEFAULT_MD = "docs/design-facts.md"
# 目标文件三行：第 1 行给阈值事实做锚点，第 2 行带 expect，第 3 行给旧格式字符串 evidence。
TARGET_SOURCE = "# 说明行：阈值事实的 evidence 锚点\ndef target():\n    return 1\n"
TARGET_REF = "src/target.py:2"
THRESHOLD_REF = "src/target.py:1"
# 第 3 行是 `    return 1`，两个用途取值相同，故只留一个常量：
# - DF-002 的旧格式字符串 evidence（无内容断言）；
# - 「非字符串 expect 被 str() 强转后恰好命中」的锚点（`expect: 1`）。
LINE3_REF = "src/target.py:3"
# 目标行（第 2 行）的真实文本：FAIL 文案必须带上它，否则「实际行内容」语义无处落地。
TARGET_LINE_TEXT = "def target():"
EXPECT_GOOD = "def target"
# 故意取「目标文件里根本不存在」的串：命中它只能是校验器把 expect 当恒真。
EXPECT_WRONG = "这段文字在目标行里不存在"
# 冻结阈值事实的键名与取值：必须与下面的 `THRESHOLDS` 字面量逐项相等，
# 否则 `check_thresholds` 会额外报 FAIL，把 evidence 用例的判决淹掉。
THRESHOLD_PAIRS = (("a", 1.0), ("b", 2.0), ("c", 3.0), ("d", 4.0), ("e", 5.0), ("f", 6.0), ("g", 7.0))
THRESHOLDS_SOURCE = (
    "THRESHOLDS = {\n"
    + "".join(f'    "{key}": {value!r},\n' for key, value in THRESHOLD_PAIRS)
    + "}\n"
)


def _design_facts_yaml(expect: str) -> str:
    """按 evidence 目标契约把三种写法放进同一个最小事实库。

    - DF-001：`{ref, expect}`（I/J/L 的目标）
    - DF-002：旧格式字符串（K 的目标，也是「无内容断言」计数的唯一来源，应为 1 条）
    - DF-004：阈值事实，claim 与 `THRESHOLDS` 逐项相等，让 `check_thresholds` 不产生噪音
    """
    return _design_facts_yaml_with_evidence_block(
        f"      - ref: {TARGET_REF}\n        expect: {expect}\n"
    )


def _design_facts_yaml_with_evidence_block(evidence_block: str) -> str:
    """同 `_design_facts_yaml`，但 DF-001 的 evidence 片段原样交给调用方（含缩进）。

    需要扭曲 evidence 形状（拼错键名、丢 expect、缩进错层、非法取值）的用例用它。
    """
    claim = "冻结阈值：" + "；".join(f"{key} {value!r}" for key, value in THRESHOLD_PAIRS) + "。"
    return (
        "version: 1\n"
        "facts:\n"
        "  - id: DF-001\n"
        "    state: active\n"
        "    affects: [code]\n"
        "    topic: 内容断言\n"
        "    claim: 带 expect 的 evidence 必须命中目标行的内容。\n"
        "    evidence:\n"
        + evidence_block
        + "  - id: DF-002\n"
        "    state: active\n"
        "    affects: [code]\n"
        "    topic: 内容断言\n"
        "    claim: 旧格式字符串 evidence 仍然受支持。\n"
        "    evidence:\n"
        "      - " + LINE3_REF + "\n"
        "  - id: DF-004\n"
        "    state: active\n"
        "    affects: [metrics]\n"
        "    topic: 冻结阈值\n"
        "    claim: " + claim + "\n"
        "    evidence:\n"
        "      - ref: " + THRESHOLD_REF + "\n"
        "        expect: 说明行\n"
    )


def _build_design_facts_repo(root: Path, *, expect: str) -> None:
    """造一个 evidence / 阈值 / md 三项都能通过的最小仓库（只写 `root` 内的文件）。"""
    _build_design_facts_repo_with_evidence_block(
        root, evidence_block=f"      - ref: {TARGET_REF}\n        expect: {expect}\n"
    )


def _build_design_facts_repo_with_evidence_block(root: Path, *, evidence_block: str) -> None:
    """同 `_build_design_facts_repo`，但 DF-001 的 evidence 片段由调用方给定。"""
    _write(root, "src/target.py", TARGET_SOURCE)
    _write(root, "finetune/holdout_metrics.py", THRESHOLDS_SOURCE)
    _write(root, DEFAULT_YAML, _design_facts_yaml_with_evidence_block(evidence_block))


def _render_in_repo(root: Path) -> subprocess.CompletedProcess:
    """对 tmp 仓库跑 `--render --root <root>`：渲染结果落到 `<root>/docs/design-facts.md`。

    `--root` 把仓库根与 yaml / md / 阈值路径一并重定向（与 `--check-doc-paths` 同语义），
    因此不需要把脚本复制进 tmp 仓库，也不会碰到当前仓库的 docs/。
    """
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--render", "--root", str(root)],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_child_env(),
    )


def _validate_repo(root: Path) -> subprocess.CompletedProcess:
    """对 tmp 仓库跑 validate 模式：用真实脚本 + `--root <root>`。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_child_env(),
    )


def _evidence_pass_line(fact_id: str, ref: str) -> re.Pattern:
    """命中行：`PASS  <fact_id> evidence <ref>`（`PASS\\s+` 天然排除 `PASS(no-expect)`）。"""
    return re.compile(rf"^PASS\s+{fact_id}\s+evidence\s+{re.escape(ref)}", re.MULTILINE)


def _evidence_no_expect_line(fact_id: str, ref: str) -> re.Pattern:
    return re.compile(rf"^PASS\(no-expect\)\s+{fact_id}\s+evidence\s+{re.escape(ref)}", re.MULTILINE)


def _fail_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("FAIL")]


def test_evidence_expect_hit_passes_when_target_line_contains_snippet(tmp_path: Path):
    # I：expect 命中 → 该 evidence 判 PASS，且整仓无其它 FAIL（退出码 0）。
    _build_design_facts_repo(tmp_path, expect=EXPECT_GOOD)
    render = _render_in_repo(tmp_path)
    assert render.returncode == 0, _context(render)

    result = _validate_repo(tmp_path)

    assert result.returncode == 0, _context(result)
    assert _evidence_pass_line("DF-001", TARGET_REF).search(result.stdout), _context(result)
    assert _fail_lines(result.stdout) == [], _context(result)


def test_evidence_expect_mismatch_fails_naming_fact_ref_and_snippet(tmp_path: Path):
    # J：防恒真的关键用例——expect 写成文件里不存在的串时必须 FAIL，绝不判恒真。
    # 三个要素（fact_id / ref / 期望片段）必须出现在同一条 FAIL 行里。
    _build_design_facts_repo(tmp_path, expect=EXPECT_WRONG)
    render = _render_in_repo(tmp_path)
    assert render.returncode == 0, _context(render)

    result = _validate_repo(tmp_path)

    assert result.returncode == 1, _context(result)
    assert _evidence_pass_line("DF-001", TARGET_REF).search(result.stdout) is None, _context(result)
    fails = _fail_lines(result.stdout)
    assert fails, _context(result)
    # 失败只应来自 DF-001 的 expect 不匹配：其它检查（阈值、md 一致性）都按真实规则构造成通过。
    assert all("DF-001" in line for line in fails), (
        "出现了与 expect 不匹配无关的 FAIL" + _context(result)
    )
    line = fails[0]
    assert TARGET_REF in line, "FAIL 行没有点名 evidence ref" + _context(result)
    assert EXPECT_WRONG in line, "FAIL 行没有带上期望片段" + _context(result)
    # 只断言「期望片段」「ref」还不够：实现可以完全不打印目标行内容，读报错的人无从判断差在哪。
    assert "实际行内容" in line, "FAIL 行没有「实际行内容」这个语义标记" + _context(result)
    assert TARGET_LINE_TEXT in line, (
        f"FAIL 行没有带上目标行的真实文本 {TARGET_LINE_TEXT!r}" + _context(result)
    )


def test_legacy_string_evidence_passes_with_no_expect_marker(tmp_path: Path):
    # K：旧格式（字符串、无 expect）仍 PASS，但必须显式标记 no-expect，且总结区给出计数。
    _build_design_facts_repo(tmp_path, expect=EXPECT_GOOD)
    render = _render_in_repo(tmp_path)
    assert render.returncode == 0, _context(render)

    result = _validate_repo(tmp_path)

    assert result.returncode == 0, _context(result)
    assert _evidence_no_expect_line("DF-002", LINE3_REF).search(result.stdout), _context(result)
    # 裸 `PASS` 行会掩盖「这条 evidence 根本没有内容断言」，因此必须不是裸 PASS。
    assert _evidence_pass_line("DF-002", LINE3_REF).search(result.stdout) is None, _context(result)
    # 计数只断前缀 + 数字（标点细节由实现决定）；仓库里恰好只有 DF-002 一条无内容断言。
    count = re.search(r"无内容断言的 evidence[：:]\s*(\d+)\s*条", result.stdout)
    assert count, "总结区缺少无内容断言的 evidence 计数" + _context(result)
    assert int(count.group(1)) == 1, _context(result)


def test_flipping_expect_to_wrong_value_turns_pass_into_fail(tmp_path: Path):
    # L：变异自证——同一 tmp 仓库里只把 expect 由正确值改成错误值，判决必须从 PASS 翻成 FAIL。
    # 全程只写 tmp_path 内的副本，不动仓库内任何文件。
    _build_design_facts_repo(tmp_path, expect=EXPECT_GOOD)
    first_render = _render_in_repo(tmp_path)
    assert first_render.returncode == 0, _context(first_render)

    before = _validate_repo(tmp_path)
    assert before.returncode == 0, _context(before)
    assert _evidence_pass_line("DF-001", TARGET_REF).search(before.stdout), _context(before)

    # 变异：只改 expect 的取值，ref 与目标文件都保持不变。
    _write(tmp_path, DEFAULT_YAML, _design_facts_yaml(EXPECT_WRONG))
    second_render = _render_in_repo(tmp_path)
    assert second_render.returncode == 0, _context(second_render)

    after = _validate_repo(tmp_path)

    assert after.returncode == 1, _context(after)
    assert _evidence_pass_line("DF-001", TARGET_REF).search(after.stdout) is None, _context(after)
    fails = _fail_lines(after.stdout)
    assert fails, _context(after)
    assert all("DF-001" in line for line in fails), (
        "翻转后的 FAIL 不只来自 expect 不匹配（validate --root 可能没把 md / 阈值检查一并重定向）"
        + _context(after)
    )
    assert EXPECT_WRONG in fails[0] and TARGET_REF in fails[0], _context(after)
    # 控制项：同一仓库里的旧格式 evidence 不受影响，证明翻转只由 expect 取值引起。
    assert _evidence_no_expect_line("DF-002", LINE3_REF).search(after.stdout), _context(after)


def test_render_shows_expect_snippet_for_mapping_evidence(tmp_path: Path):
    # `--render` 必须把 expect 片段渲染出来；同时旧格式仍渲染成原来的 `- path:LINE`。
    _build_design_facts_repo(tmp_path, expect=EXPECT_GOOD)

    render = _render_in_repo(tmp_path)

    assert render.returncode == 0, _context(render)
    md = (tmp_path / DEFAULT_MD).read_text(encoding="utf-8")
    bullets = [line for line in md.splitlines() if TARGET_REF in line]
    assert len(bullets) == 1, md
    bullet = bullets[0]
    assert EXPECT_GOOD in bullet, "渲染结果里没有 expect 片段：" + md
    # 排除「把 dict 直接 str() 出来」这种假命中（当前实现的 `- {'ref': ..., 'expect': ...}`）。
    assert "{" not in bullet and "'ref'" not in bullet, "evidence 被渲染成了 dict 的 repr：" + md
    stripped = [line.strip() for line in md.splitlines()]
    assert f"- {LINE3_REF}" in stripped, "旧格式字符串 evidence 的渲染结果被改动了：" + md


# --------------------------------------------------------------------------- #
# `--render --root` 的落盘边界与「折行假片段」
#
# `--root` 对 `--render` 同样生效（把仓库根、yaml / md / 阈值路径一并重定向），因此 tmp 仓库的渲染
# 不需要复制脚本，也不会碰当前仓库的 docs/。含换行的 expect 在渲染侧不得被折成单行：
# 折出来的单行片段在源码里根本不存在，会被读文档的人当成真断言。
# --------------------------------------------------------------------------- #
REPO_MD = Path(__file__).resolve().parents[1] / "docs" / "design-facts.md"
MULTILINE_EXPECT_BLOCK = (
    f"      - ref: {TARGET_REF}\n"
    "        expect: |\n"
    "          def target():\n"
    "              return 1\n"
)
# 若渲染用 `" ".join(text.split())` 折叠，`def target():\n    return 1` 会变成这个单行假片段。
FOLDED_MULTILINE_EXPECT = "def target(): return 1"
# 预置在目标 md 里的哨兵内容：渲染在预检阶段就 fail-closed，文件必须原样保留（不得被改写）。
SENTINEL_MD = "# 哨兵：含换行 expect 时应被预检拦住，本行不得被覆盖\n"


def test_render_with_root_writes_only_inside_the_target_root(tmp_path: Path):
    # `--render --root` 必须只改写目标根下的 md；当前仓库的 docs/design-facts.md 保持逐字节不变。
    _build_design_facts_repo(tmp_path, expect=EXPECT_GOOD)
    repo_md_existed = REPO_MD.exists()
    repo_md_before = REPO_MD.read_bytes() if repo_md_existed else None

    render = _render_in_repo(tmp_path)

    assert render.returncode == 0, _context(render)
    rendered = tmp_path / DEFAULT_MD
    assert rendered.is_file(), "--render --root 没有把 md 写到目标根下" + _context(render)
    assert "DF-001" in rendered.read_text(encoding="utf-8"), (
        "目标根下的 md 不是本次渲染结果" + _context(render)
    )
    assert REPO_MD.exists() == repo_md_existed, (
        "--render --root 在当前仓库里新建了 docs/design-facts.md" + _context(render)
    )
    assert (REPO_MD.read_bytes() if repo_md_existed else None) == repo_md_before, (
        "--render --root 改动了当前仓库的 docs/design-facts.md" + _context(render)
    )


def test_render_does_not_fold_multiline_expect_into_a_fake_snippet(tmp_path: Path):
    # 渲染侧 fail-closed：含换行的 expect 使 `--render` 退出 1 且**不写文件**。
    # 只断「不折叠」是恒真的（渲染器本就不折叠），必须断到预检真的拦住了落盘。
    _build_design_facts_repo_with_evidence_block(tmp_path, evidence_block=MULTILINE_EXPECT_BLOCK)
    _write(tmp_path, DEFAULT_MD, SENTINEL_MD)

    render = _render_in_repo(tmp_path)

    assert render.returncode == 1, (
        "含换行的 expect 没有被 render 侧预检判 FAIL（应 fail-closed）" + _context(render)
    )
    assert "未渲染" in render.stdout, "render 的失败文案没有说明没落盘" + _context(render)
    assert "DF-001" in render.stdout, "render 的失败文案没有点名出错的事实" + _context(render)
    md_path = tmp_path / DEFAULT_MD
    assert md_path.read_text(encoding="utf-8") == SENTINEL_MD, (
        "预检没拦住写文件：目标 md 被改写或重新生成了" + _context(render)
    )
    assert FOLDED_MULTILINE_EXPECT not in md_path.read_text(encoding="utf-8"), (
        "渲染把含换行的 expect 折成了源码里不存在的单行片段" + _context(render)
    )


# --------------------------------------------------------------------------- #
# evidence 映射的形状必须被强制（不得静默降级成 `PASS(no-expect)`）
#
# 契约：evidence 映射只允许 `ref` 与 `expect` 两个键；`ref` 必须是非空字符串且符合 `path:LINE`；
# `expect` 必须是非空、单行的字符串。下面每一行都是「断言被静默吞掉」的写法：修复前的实现把它们
# 降级成 `PASS(no-expect)` 并退出 0，断言凭空消失却看起来全绿。
#
# 每条 param 的 `keyword` 必须是**唯一**指向本形态守卫的最小文案锚点。取宽泛词（如 `expect`）会让
# 该 param 被相邻分支的文案满足而近乎恒真——拼错键名就是这种坑：`expec` 是 `expect` 的子串，
# 而「缺少 expect」分支的文案同样含它，于是删掉未知键守卫照样绿。因此 typo 用例另带 `forbidden`。
# --------------------------------------------------------------------------- #
# 反向断言用：未知键形态的 FAIL 行不得含本串（含它说明判决来自「缺少 expect」分支，而非未知键守卫）。
FORBIDDEN_MISSING_EXPECT = "缺少 expect"
# 缺 ref / ref 非字符串这两条用例拿不到可用的合法 ref，只能断「该 fact 不得出现任何 PASS 行」；
# 空串在 `_evidence_pass_line` 里退化成前缀匹配，对该 fact 的任意 PASS 行都成立，故是正确的更严断言。
NO_REF = ""


_DF001_EVIDENCE_CASES = [
    pytest.param(
        f"      - ref: {TARGET_REF}\n        expec: 不存在XYZ\n",
        TARGET_REF,
        "未知键",
        FORBIDDEN_MISSING_EXPECT,
        id="typo-expec-key",
    ),
    # 下面两条故意守同一分支（「映射缺少 expect」），但 YAML 形态不同、成因不同，都保留：
    # - mapping-without-expect：映射里根本没写 `expect` 键；
    # - expect-indented-to-fact-level：写了 `expect`，但缩进错层（4 空格 < 映射的 8 空格），
    #   解析后该键落到了 fact 层，映射里只剩 `ref`。守的是「YAML 缩进错层 → 键落到 fact 层」这一事实，
    #   不能让「缩进写错」被静默当成「合法无 expect」。
    pytest.param(
        f"      - ref: {TARGET_REF}\n",
        TARGET_REF,
        "缺少 expect",
        None,
        id="mapping-without-expect",
    ),
    pytest.param(
        f"      - ref: {TARGET_REF}\n        expect:\n",
        TARGET_REF,
        "expect",
        None,
        id="expect-empty-value",
    ),
    pytest.param(
        f"      - ref: {TARGET_REF}\n        expect: null\n",
        TARGET_REF,
        "expect",
        None,
        id="expect-null",
    ),
    pytest.param(
        f"      - ref: {TARGET_REF}\n        expect: ~\n",
        TARGET_REF,
        "expect",
        None,
        id="expect-tilde",
    ),
    pytest.param(
        f"      - ref: {TARGET_REF}\n    expect: {EXPECT_GOOD}\n",
        TARGET_REF,
        "缺少 expect",
        None,
        id="expect-indented-to-fact-level",
    ),
    pytest.param(
        f"      - ref: {LINE3_REF}\n        expect: 1\n",
        LINE3_REF,
        "expect",
        None,
        id="expect-non-string-int",
    ),
    pytest.param(
        f'      - ref: {TARGET_REF}\n        expect: ""\n',
        TARGET_REF,
        "expect",
        None,
        id="expect-blank-quoted",
    ),
    pytest.param(
        f'      - ref: {TARGET_REF}\n        expect: "   "\n',
        TARGET_REF,
        "expect",
        None,
        id="expect-whitespace-only",
    ),
    pytest.param(
        MULTILINE_EXPECT_BLOCK,
        TARGET_REF,
        "expect",
        None,
        id="expect-multiline-block",
    ),
    # 映射缺 `ref`：完全没有 ref，`expect` 再合法也不能算通过。
    pytest.param(
        f"      - expect: {EXPECT_GOOD}\n",
        NO_REF,
        "缺少 ref",
        None,
        id="mapping-without-ref",
    ),
    # `ref` 非字符串（yaml 把 `123` 解析成 int）：禁止隐式转换，否则 `123` 会被 str() 成假路径。
    pytest.param(
        f"      - ref: 123\n        expect: {EXPECT_GOOD}\n",
        NO_REF,
        "非空字符串",
        None,
        id="ref-not-a-string",
    ),
    # `ref` 是字符串但不带行号：`path:LINE` 是唯一合法形式，缺行号不得被默认成第 1 行。
    pytest.param(
        "      - ref: src/target.py\n"
        f"        expect: {EXPECT_GOOD}\n",
        "src/target.py",
        "不符合 path:LINE",
        None,
        id="ref-without-line",
    ),
]


@pytest.mark.parametrize(
    ("evidence_block", "ref", "keyword", "forbidden"), _DF001_EVIDENCE_CASES
)
def test_malformed_expect_must_fail_instead_of_degrading_to_no_expect(
    tmp_path: Path, evidence_block: str, ref: str, keyword: str, forbidden: str | None
):
    # 所有形状都必须：退出 1 + 有一条点名 DF-001 与形态关键词的 FAIL 行 + 不得出现
    # DF-001 的 PASS / PASS(no-expect) 行（后者正是「断言被静默丢弃」的表面绿）。
    _build_design_facts_repo_with_evidence_block(tmp_path, evidence_block=evidence_block)
    render = _render_in_repo(tmp_path)

    result = _validate_repo(tmp_path)

    assert result.returncode == 1, _context(result)
    assert _evidence_no_expect_line("DF-001", ref).search(result.stdout) is None, (
        "evidence 形状错误被判成了 PASS(no-expect)，断言被静默丢弃" + _context(result)
    )
    assert _evidence_pass_line("DF-001", ref).search(result.stdout) is None, _context(result)
    df001_fails = [line for line in _fail_lines(result.stdout) if "DF-001" in line]
    assert df001_fails, "没有任何点名 DF-001 的 FAIL 行" + _context(result)
    assert any(keyword in line for line in df001_fails), (
        f"FAIL 行没有提到形态关键词 {keyword!r}，无法定位是哪种写法出错" + _context(result)
    )
    if forbidden is not None:
        assert all(forbidden not in line for line in df001_fails), (
            f"FAIL 行里出现了 {forbidden!r}：判决来自相邻分支而非本形态的守卫，"
            "该 param 无法唯一咬住这条守卫" + _context(result)
        )
    # 渲染成功时 md 与 yaml 一致，FAIL 只应来自 evidence 判定，不该被 md 不一致的噪音带走。
    if (tmp_path / DEFAULT_MD).exists() and render.returncode == 0:
        assert all("DF-001" in line for line in _fail_lines(result.stdout)), (
            "出现了与 evidence 形状无关的 FAIL" + _context(result)
        )


# --------------------------------------------------------------------------- #
# I1：被判 FAIL 的旧格式 evidence 不得计入「无内容断言的 evidence：N 条」
#
# 口径是「最终判定为 PASS(no-expect) 的条目数」。把 `no_expect += 1` 提前到「拿到 entry 之后」
# （在 ref / 行号检查之前），或对同一条目加两次，N 都会虚高——出现 FAIL 时这个数反而变大，会被
# 误读成断言健全程度提升。因此断言三点：退出 1；N 与 stdout 里 PASS(no-expect) 行数相等；
# N 严格小于 evidence 总条数。
# --------------------------------------------------------------------------- #
# 行号越界（src/target.py 只有 3 行）：形状合法，但 ref 检查必然 FAIL。
FAILING_LEGACY_REF = "src/target.py:99"
LEGACY_PASS_REF = "src/target.py:1"
# 在基础事实库之后追加两条旧格式字符串 evidence：一条合法（DF-005），一条行号越界（DF-006）。
EXTRA_LEGACY_FACTS = (
    "  - id: DF-005\n"
    "    state: active\n"
    "    affects: [code]\n"
    "    topic: 内容断言\n"
    "    claim: 第二条合法的旧格式字符串 evidence。\n"
    "    evidence:\n"
    f"      - {LEGACY_PASS_REF}\n"
    "  - id: DF-006\n"
    "    state: active\n"
    "    affects: [code]\n"
    "    topic: 内容断言\n"
    "    claim: 行号越界的旧格式字符串 evidence 必须判 FAIL。\n"
    "    evidence:\n"
    f"      - {FAILING_LEGACY_REF}\n"
)


def _no_expect_count(stdout: str) -> re.Match | None:
    return re.search(r"无内容断言的 evidence[：:]\s*(\d+)\s*条", stdout)


def test_failed_legacy_evidence_is_not_counted_as_no_expect(tmp_path: Path):
    # evidence 共 5 条：DF-001 / DF-004 是带 expect 的映射，DF-002 / DF-005 是合法旧格式，
    # DF-006 是必 FAIL 的旧格式（行号越界）。正确的 N 只能是 2。
    yaml_text = _design_facts_yaml(EXPECT_GOOD) + EXTRA_LEGACY_FACTS
    _build_design_facts_repo(tmp_path, expect=EXPECT_GOOD)
    _write(tmp_path, DEFAULT_YAML, yaml_text)
    render = _render_in_repo(tmp_path)
    assert render.returncode == 0, _context(render)

    result = _validate_repo(tmp_path)

    # ① 判决本身：DF-006 必须 FAIL，整仓退出 1（且 FAIL 不来自无关检查）。
    assert result.returncode == 1, _context(result)
    fail_lines = _fail_lines(result.stdout)
    assert fail_lines, _context(result)
    assert all("DF-006" in line for line in fail_lines), (
        "FAIL 不是（只）来自 DF-006 的行号越界" + _context(result)
    )
    assert any("行号越界" in line for line in fail_lines), _context(result)
    # 被判 FAIL 的条目不得被打成 no-expect（否则 ② 只需「多计数」就能被满足）。
    assert _evidence_no_expect_line("DF-006", FAILING_LEGACY_REF).search(result.stdout) is None, (
        "行号越界的旧格式 evidence 被判成了 PASS(no-expect)" + _context(result)
    )
    # ② 计数必须与 PASS(no-expect) 行数相等；③ 必须严格小于 evidence 总条数。
    no_expect_rows = [
        line for line in result.stdout.splitlines() if line.startswith("PASS(no-expect)")
    ]
    assert len(no_expect_rows) == 2, (
        "PASS(no-expect) 行数不是 DF-002 + DF-005 两条" + _context(result)
    )
    count = _no_expect_count(result.stdout)
    assert count, "总结区缺少无内容断言的 evidence 计数" + _context(result)
    assert int(count.group(1)) == len(no_expect_rows), (
        "无内容断言的计数与 PASS(no-expect) 行数不一致：有 FAIL 条目被算进去了" + _context(result)
    )
    evidence_total = len([line for line in yaml_text.splitlines() if line.startswith("      - ")])
    assert evidence_total == 5, f"夹具的 evidence 条数变了：{evidence_total}"
    assert int(count.group(1)) < evidence_total, (
        "无内容断言的计数等于 evidence 总条数：FAIL 的旧格式条目也被计入" + _context(result)
    )


# --------------------------------------------------------------------------- #
# I2：结构校验早退时必须打印「未检查（结构校验已失败）」，不得退化成「0 条」
#
# `run_checks` 的两个早退分支返回 (results, None)，`validate_mode` 见到 None 才打印「未检查」。
# 把 None 改成 0，输出会变成「无内容断言的 evidence：0 条」——看起来像「本来就没有无断言条目」，
# 而真相是 evidence 根本没被检查。
# --------------------------------------------------------------------------- #
UNCHECKED_LINE = "未检查（结构校验已失败）"
TOP_LEVEL_LIST_YAML = "- 第一项\n- 第二项\n"  # 顶层是列表，不是映射
MISSING_VERSION_YAML = _design_facts_yaml(EXPECT_GOOD).replace("version: 1\n", "", 1)


@pytest.mark.parametrize(
    ("yaml_text", "case"),
    [
        pytest.param(TOP_LEVEL_LIST_YAML, "顶层不是映射", id="top-level-list"),
        pytest.param(MISSING_VERSION_YAML, "缺少 version", id="missing-version"),
    ],
)
def test_structural_failure_reports_unchecked_instead_of_zero_no_expect(
    tmp_path: Path, yaml_text: str, case: str
):
    # 早退发生在 evidence 检查之前，渲染/ md 一致性都不会被走到，故只写 yaml。
    assert yaml_text != _design_facts_yaml(EXPECT_GOOD), f"{case} 夹具没改动 yaml"
    _build_design_facts_repo(tmp_path, expect=EXPECT_GOOD)
    _write(tmp_path, DEFAULT_YAML, yaml_text)

    result = _validate_repo(tmp_path)

    assert result.returncode == 1, _context(result)
    summary = [line for line in result.stdout.splitlines() if "无内容断言的 evidence" in line]
    assert len(summary) == 1, "总结区必须且只能有一行无内容断言的结论" + _context(result)
    assert UNCHECKED_LINE in summary[0], (
        f"{case} 早退时没有标明 evidence 未检查" + _context(result)
    )
    assert "：0 条" not in summary[0], (
        f"{case} 早退被退化成误导性的 0 条" + _context(result)
    )
    assert "无内容断言的 evidence：0" not in result.stdout, _context(result)


def _load_script_module():
    """同进程载入被测脚本，供函数级打桩使用。

    例外说明：本文件其余用例一律「tmp 仓库 + subprocess 跑真实脚本」，但 `validate_mode` 的
    `except Exception` 兜底只能靠同进程注入异常触达——子进程里没有可注入点，除非改脚本本身
    （生产代码，测试不得改）。这里用 importlib 从同一份脚本文件载入一个独立模块对象，
    monkeypatch 只打在模块属性上，pytest 在用例结束时自动还原，不污染同进程其它用例。
    """
    spec = importlib.util.spec_from_file_location("verify_design_facts_under_test", SCRIPT)
    assert spec and spec.loader, f"无法为 {SCRIPT} 构造 importlib spec"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_internal_exception_reports_failure_without_zero_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    # 兜底分支：`run_checks` 抛异常时必须以 FAIL 文案 + 退出 1 收场，不得 traceback，
    # 也不得因为「没拿到计数」而打出「0 条」。
    module = _load_script_module()

    def boom():
        raise RuntimeError("模拟 run_checks 内部异常")

    monkeypatch.setattr(module, "run_checks", boom)

    exit_code = module.validate_mode(tmp_path)

    out = capsys.readouterr().out
    assert exit_code == 1, out
    assert "校验过程异常" in out, out
    assert "RuntimeError" in out, out
    assert "：0 条" not in out, out


# --------------------------------------------------------------------------- #
# M：真实仓库守卫——仓库内 evidence 必须全部带内容断言
#
# 缺口：工具把字符串式（旧格式）evidence 判成 `PASS(no-expect)`，且**不改变退出码**。于是「真实仓库
# 无内容断言的 evidence：0 条」当前只是一次性观测：之后任何人手写一条 `- path:LINE`，这个数字变大
# 而整仓依旧全绿、CI 不拦。上面所有用例都跑在 tmp 仓库上，只能证明工具行为，证明不了仓库现状。
# 本用例把「仓库内 evidence 必须全部带内容断言」这条已确立的项目约定钉成回归。
#
# 例外说明：这是本文件**唯一对真实仓库「内容状态」做断言**的用例，其余用例一律 tmp 仓库 + `--root`。
# （`test_render_with_root_writes_only_inside_the_target_root` 也会读真实的 docs/design-facts.md，
# 但只断言它未被改动，不判断其内容正确与否。）理由：被守的对象是「真实事实库此刻是否守约定」，
# 只有对真实仓库跑一次才成立；因此用例只读仓库——子进程 cwd 指向仓库根、不加 `--root`、不写任何文件。
#
# 变红时怎么办：新增的旧格式 evidence 要改写成映射形式
# `{ref: <path:LINE>, expect: <该行必然包含的片段>}`（写法见 docs/design-facts.yaml 里 DF-001）。
# 不得为让它变绿而删断言或改本用例。
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(__file__).resolve().parents[1]
# 汇总区里 `PASS(no-expect) N，FAIL N` 是唯一「断言全带内容、无判决失败」的最小唯一子串：
# 单看 `PASS(no-expect)` 会把汇总行也算进去（那一行本就含这个词），单看 `0` 又毫无定位力。
ALL_GREEN_MARKER = "PASS(no-expect) 0，FAIL 0"
NO_EXPECT_HINT = (
    "仓库内 evidence 必须全部带内容断言：旧格式字符串 evidence 会被判 PASS(no-expect) 且退出码不变，"
    "等于把断言静默丢弃。请把它改写成映射形式 {ref: <path:LINE>, expect: <该行必然包含的片段>}。"
)
# 退出码非 0 的红态有多种成因（行号漂移、md 未重渲染、evidence 缺内容断言……），首条断言只能用
# 中性提示指向真因候选；把 NO_EXPECT_HINT 用在这里会把读者误导向「改写成映射形式」这一种可能。
REAL_REPO_RED_HINT = (
    "真实仓库自检未全绿（退出码非 0）。成因候选：ref 的行号已漂移（path:LINE 指向的行挪位）、"
    "docs/design-facts.md 未按设计事实重新渲染、或某条 evidence 缺内容断言。真因见下方 stdout 的 FAIL 行。"
)


def _run_on_real_repo() -> subprocess.CompletedProcess:
    """在真实仓库根上跑 validate 模式（只读：不改文件、不加 `--root`、不传 `--render`）。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_child_env(),
    )


def test_real_repo_evidence_all_carry_content_assertions():
    """真实仓库此刻的自检必须全绿，且 evidence 全部带内容断言。

    边界：本用例读的是工作区当前状态，依赖整仓一致性——他人未提交的半成品（例如改了
    docs/design-facts.yaml 却没重渲染 md）同样会让它变红。作为整仓门禁可以接受，但不应被
    当作判断「本次改动是否 OK」的纯单测信号。
    """
    # Act：对真实仓库跑一次真实脚本。
    result = _run_on_real_repo()

    # 逐条标记行（`PASS(no-expect)  <消息>`）才是「无内容断言」的证据；汇总行 `PASS(no-expect) 0`
    # 只是计数，按行首前缀统计可把两者区分开。
    no_expect_rows = [
        line for line in result.stdout.splitlines() if line.startswith("PASS(no-expect)")
    ]

    # Assert ①：真实仓库此刻应全 PASS（红态既可能来自新增的旧格式 evidence，也可能来自行号漂移、
    # md 未重渲染或别处未提交改动，所以提示保持中性并指向真因候选，完整 stdout 一并带上）。
    assert result.returncode == 0, REAL_REPO_RED_HINT + _context(result)
    # Assert ②：逐条 PASS(no-expect) 行数必须为 0（一条都不许有），失败时点名具体条目。
    # 放在总结区断言之前：红态才能直接指出是哪一条 evidence 缺内容断言，而不是只报「总结区数字不对」。
    assert not no_expect_rows, "\n".join(
        [
            f"有 {len(no_expect_rows)} 条 evidence 缺内容断言：",
            *no_expect_rows,
            NO_EXPECT_HINT,
            _context(result),
        ]
    )
    # Assert ③：总结区的口径必须是 0 条，不是「未检查」也不是正数。
    assert "无内容断言的 evidence：0 条" in result.stdout, (
        "总结区没有给出「无内容断言的 evidence：0 条」" + NO_EXPECT_HINT + _context(result)
    )
    # Assert ④：汇总行必须是「无判决失败」的形态（并顺带咬住汇总里的 no-expect 计数为 0）。
    assert ALL_GREEN_MARKER in result.stdout, (
        f"汇总行不是 `{ALL_GREEN_MARKER}` 的形态" + _context(result)
    )
