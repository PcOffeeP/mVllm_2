"""`script/checks/facts.py` 的契约测试。

覆盖范围：
- 单元层：`normalize`、白名单规则解析（`load_allowlist`）；
- 行为层：除集成用例外，每个用例都在 `tmp_path` 里造 `<tmp>/docs/facts.yaml` 与被引用的源文件，
  再用 `main(["--root", str(tmp), ...])` 跑一遍，按 `category` 六分类口径、JSON 固定形状、
  默认模式（不带 `--json`）的人类可读输出文案与 `--strict` 退出码断言；
- `--check-doc-paths`：在 `tmp_path` 里 `git init` 造小仓库做行为测试，不扫真实仓库；
- 集成层：`test_should_report_real_facts_without_breaking_invariants` 等少量用例读真实仓库数据，
  只断不变量与退出码，不断言具体条数（真实数据随文档修订漂移）。

分类口径（`category`，**锚文本**口径：`ref` 的行号只是提示，判定以 `expect` 原文能否在目标文件中
定位为准）：

| category | 含义 | `actual` / `actual_line` / `matches` |
| --- | --- | --- |
| `pass` | 记录行命中（命中即早退，不做全文搜索） | 记录行号 / 同 / `[]` |
| `pass_moved` | 记录行未命中，但全文唯一命中（位置已变） | 唯一命中行号 / 同 / `[]` |
| `gone` | 记录行未命中且全文未找到内容 | `None` / `None` / `[]` |
| `ambiguous` | 记录行未命中且全文多处命中（不默认取第一处） | `None` / `None` / 全部命中行号（升序） |
| `unverifiable` | 未检出前缀、原工作区特有文件缺失、文件无法读取 | `None` |
| `structure` | 结构或 `expect` 非法 | `None` |

旧口径的 `drift`（位置漂移）已废除：行号对不上但原文在别处唯一命中改为 `pass_moved`，多处命中改为
`ambiguous`。`pass_moved` 只提示位置变化，**不**触发 `--strict` 拦截。

汇总口径（`totals` 精确键集合见 `TOTALS_KEYS`）：`entries == facts 条数 + misreadings 条数`；
`passed == passed_anchored + passed_moved`（分别数 `pass` 与 `pass_moved`）；
`passed + gone + ambiguous + unverifiable + structure == evidence == len(results)`；
`structure` 只数 evidence 级结构错误，`structure_errors` 数全部结构错误记录（文档级 + 条目级 +
evidence 级）。

失效条件：`script/checks/facts.py` 的分类口径、`totals` / `results` 键集合、默认输出文案或
`--strict` 语义变更时，本文件需同步修订。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Sequence

import pytest

from script.checks.facts import check_facts, load_allowlist, main, normalize

ROOT = Path(__file__).resolve().parents[3]
# 基线键：几乎每个用例都要读，缺任一即断。
LEGACY_TOTALS_KEYS = {
    "entries",
    "evidence",
    "passed",
    "gone",
    "unverifiable",
    "structure",
}
# 锚文本口径新增/改名的计数键：`drift` 废止，`passed` 拆成 anchored + moved，新增 `ambiguous`。
ANCHOR_TOTALS_KEYS = {"passed_anchored", "passed_moved", "ambiguous"}
# 完整键集合（契约）：由 `test_should_expose_exact_totals_key_set` 断言，不放进共享不变量里，
# 否则同一根因会让几十个用例一起红、掩盖各自要验证的行为。
TOTALS_KEYS = LEGACY_TOTALS_KEYS | ANCHOR_TOTALS_KEYS | {"structure_errors"}
RESULT_KEYS = {
    "id",
    "ref",
    "expect",
    "actual",
    "actual_line",
    "matches",
    "category",
    "detail",
}
# 五个中文汇总标签（默认模式必须逐条带数字）。
SUMMARY_LABELS = ("通过", "原文消失", "歧义", "本机无法核对", "结构错误")
# 旧口径标签：不得再作为类别或汇总标签出现在默认输出里。
DEPRECATED_LABELS = ("位置漂移", "DRIFT")
requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="`--check-doc-paths` 行为测试需要 git"
)


# --------------------------------------------------------------------------- #
# 造数据：块风格 YAML，尽量不依赖 flow 写法，便于任何 YAML 子集解析器读取
# --------------------------------------------------------------------------- #
def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_facts(root: Path, body: str) -> Path:
    return _write(root, "docs/facts.yaml", textwrap.dedent(body).lstrip("\n"))


def _ev(ref: str, expect: str | None = "alpha") -> list[str]:
    """一条 evidence 条目；expect 传 None 表示整个键缺失。expect 参数是 YAML 标量原文。"""
    lines = [f"      - ref: {ref}"]
    if expect is not None:
        lines.append(f"        expect: {expect}")
    return lines


def _fact(
    fact_id: str,
    evidence: Sequence[str] = (),
    *,
    state: str = "active",
    topic: str = "主题",
    claim: str = "断言",
    affects: Sequence[str] = ("code",),
    evidence_location: str | None = None,
    residue: str | None = None,
) -> list[str]:
    lines = [
        f"  - id: {fact_id}",
        f"    state: {state}",
        f"    topic: {topic}",
        f"    claim: {claim}",
    ]
    if affects:
        lines.append("    affects:")
        lines.extend(f"      - {value}" for value in affects)
    else:
        lines.append("    affects:")
    lines.append("    evidence:")
    lines.extend(evidence)
    if evidence_location is not None:
        lines.append(f"    evidence_location: {evidence_location}")
    if residue is not None:
        lines.append(f"    residue: {residue}")
    return lines


def _misreading(
    wrong: str = "误读", correct: str = "正读", evidence: Sequence[str] = ()
) -> list[str]:
    lines = [f"  - wrong: {wrong}", f"    correct: {correct}"]
    if evidence:
        lines.append("    evidence:")
        lines.extend(evidence)
    return lines


def _yaml(
    *fact_blocks: Sequence[str], misreadings: Sequence[Sequence[str]] | None = None
) -> str:
    lines = ["version: 1", "facts:"]
    for block in fact_blocks:
        lines.extend(block)
    if misreadings is not None:
        lines.append("misreadings:")
        for block in misreadings:
            lines.extend(block)
    return "\n".join(lines) + "\n"


def _linear_source(root: Path) -> None:
    """三行源文件：第 1 行 alpha、第 2 行 placeholder、第 3 行 beta。"""
    _write(root, "src/a.txt", "alpha\nplaceholder\nbeta\n")


def _repeated_source(root: Path) -> None:
    """三行源文件：第 1 行 x，第 2、3 行都是 alpha（全文多处命中）。"""
    _write(root, "src/dup.txt", "x\nalpha\nalpha\n")


def _passing_repo(root: Path) -> None:
    _linear_source(root)
    _write_facts(root, _yaml(_fact("DF-001", _ev("src/a.txt:1", "alpha"))))


def _moved_repo(root: Path) -> None:
    """记录行写错、但 `expect` 原文在文件里唯一命中第 3 行：判 `pass_moved`（位置已变）。"""
    _linear_source(root)
    _write_facts(root, _yaml(_fact("DF-001", _ev("src/a.txt:2", "beta"))))


def _ambiguous_repo(root: Path) -> None:
    """记录行写错、且 `expect` 原文在文件里命中第 2、3 两处：判 `ambiguous`（不默认取第一处）。"""
    _repeated_source(root)
    _write_facts(root, _yaml(_fact("DF-001", _ev("src/dup.txt:1", "alpha"))))


# --------------------------------------------------------------------------- #
# 断言辅助
# --------------------------------------------------------------------------- #
def _run_json(capsys, argv: Sequence[str]) -> tuple[int, dict]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out)


def _run_text(capsys, argv: Sequence[str]) -> tuple[int, str]:
    """跑默认模式（不带 `--json`），拿人类可读 stdout。"""
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out


def _report(capsys, root: Path) -> dict:
    return _run_json(capsys, ["--root", str(root), "--json"])[1]


def _count_for_label(out: str, label: str) -> int:
    """取默认输出里某个中文汇总标签后紧跟的数字；取不到就断言失败。"""
    match = re.search(rf"{label}[^\d\n]{{0,12}}(\d+)", out)
    assert match is not None, f"默认输出缺少中文汇总标签 {label!r} 及其数字：\n{out}"
    return int(match.group(1))


def _structure_error_count(report: dict) -> int:
    totals = report["totals"]
    assert "structure_errors" in totals, (
        f"totals 必须含 structure_errors 计数键，实际键 {sorted(totals)}"
    )
    return totals["structure_errors"]


def _init_doc_path_repo(root: Path) -> None:
    """在 `root` 造一个只有 1 个受跟踪 md 的小 git 仓库，md 里引用一个不存在的仓库内路径。"""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q"], cwd=root, check=True, capture_output=True, text=True
    )
    _write(root, "README.md", "计划中的目标 docs/missing-target.md 尚未创建。\n")
    subprocess.run(
        ["git", "add", "README.md"], cwd=root, check=True, capture_output=True, text=True
    )


def _by_category(report: dict, category: str) -> list[dict]:
    return [result for result in report["results"] if result["category"] == category]


def _result_for(report: dict, ref: str) -> dict:
    matches = [result for result in report["results"] if result["ref"] == ref]
    assert len(matches) == 1, f"ref {ref!r} 应恰好一条结果，实际 {matches!r}"
    return matches[0]


def _structure_text(report: dict) -> str:
    """把 structure_errors 的 id 与 message 拼成一段文本，供文案子串断言。"""
    parts: list[str] = []
    for error in report["structure_errors"]:
        parts.append(str(error.get("id", "")))
        parts.append(str(error.get("message", "")))
    return " ".join(parts)


def _assert_invariants(report: dict, expected_entries: int | None = None) -> None:
    totals = report["totals"]
    results = report["results"]

    assert LEGACY_TOTALS_KEYS <= set(totals), (
        f"totals 缺基线键：{sorted(LEGACY_TOTALS_KEYS - set(totals))}"
    )
    assert ANCHOR_TOTALS_KEYS <= set(totals), (
        f"totals 缺锚文本口径的分类键 {sorted(ANCHOR_TOTALS_KEYS - set(totals))}"
        f"（旧口径的 drift 已废止），实际键 {sorted(totals)}"
    )
    assert len(results) == totals["evidence"]
    assert totals["passed"] == totals["passed_anchored"] + totals["passed_moved"], (
        "passed 必须等于 passed_anchored + passed_moved，实际"
        f" {totals['passed']} vs {totals['passed_anchored']} + {totals['passed_moved']}"
    )
    assert (
        totals["passed"]
        + totals["gone"]
        + totals["ambiguous"]
        + totals["unverifiable"]
        + totals["structure"]
        == totals["evidence"]
    ), f"五类计数之和必须等于 evidence，实际 totals={totals!r}"
    assert totals["structure"] == len(_by_category(report, "structure"))
    assert totals["passed_anchored"] == len(_by_category(report, "pass"))
    assert totals["passed_moved"] == len(_by_category(report, "pass_moved"))
    assert totals["ambiguous"] == len(_by_category(report, "ambiguous"))
    assert not _by_category(report, "drift"), "drift 类别已废止，不应再出现在 results 里"
    if expected_entries is not None:
        assert totals["entries"] == expected_entries
    for result in results:
        assert RESULT_KEYS <= set(result)
        if result["category"] in ("pass", "pass_moved"):
            assert isinstance(result["actual"], int)
            assert not isinstance(result["actual"], bool)
            assert result["actual_line"] == result["actual"], (
                f"{result['category']} 的 actual 与 actual_line 必须一致：{result!r}"
            )
            assert result["matches"] == [], (
                f"{result['category']} 的 matches 必须为空：{result!r}"
            )
        if result["category"] in ("gone", "ambiguous", "unverifiable"):
            assert result["actual"] is None, (
                f"{result['category']} 的 actual 必须为 None：{result!r}"
            )
        if result["category"] in ("gone", "ambiguous"):
            assert result["actual_line"] is None, (
                f"{result['category']} 的 actual_line 必须为 None：{result!r}"
            )
        if result["category"] == "gone":
            assert result["matches"] == [], f"gone 的 matches 必须为空：{result!r}"


# --------------------------------------------------------------------------- #
# 1. normalize：空白归一
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  a\t\tb  ", "a b"),
        ("a\nb", "a b"),
        ("def   target(\tvalue )", "def target( value )"),
        ("", ""),
        ("   \t\n ", ""),
    ],
)
def test_should_collapse_whitespace_runs_and_strip(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


# --------------------------------------------------------------------------- #
# 2. 结构错误：文档级
# --------------------------------------------------------------------------- #
def test_should_report_structure_error_when_version_missing(tmp_path: Path, capsys) -> None:
    _write(
        tmp_path,
        "docs/facts.yaml",
        _yaml(_fact("DF-001", _ev("src/a.txt:1", "alpha"))).replace("version: 1\n", "", 1),
    )
    _linear_source(tmp_path)

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "缺 version 必须在 structure_errors 里报出来"
    assert "version" in _structure_text(report).lower()
    _assert_invariants(report)


def test_should_report_structure_error_when_facts_is_not_a_list(
    tmp_path: Path, capsys
) -> None:
    _write(tmp_path, "docs/facts.yaml", "version: 1\nfacts: 不是列表\n")

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "facts 不是列表必须在 structure_errors 里报出来"
    assert "facts" in _structure_text(report).lower()
    assert report["totals"]["evidence"] == 0
    _assert_invariants(report)


# --------------------------------------------------------------------------- #
# 3. 结构错误：条目级 id
# --------------------------------------------------------------------------- #
def test_should_report_structure_error_when_id_duplicated(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha")),
            _fact("DF-001", _ev("src/a.txt:3", "beta")),
        ),
    )

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "重复 id 必须在 structure_errors 里报出来"
    assert "DF-001" in _structure_text(report)
    _assert_invariants(report, expected_entries=2)


def test_should_report_structure_error_when_id_format_illegal(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-1", _ev("src/a.txt:1", "alpha"))))

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "id 格式非法必须在 structure_errors 里报出来"
    assert "DF-1" in _structure_text(report)
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_error_when_state_invalid(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(_fact("DF-001", _ev("src/a.txt:1", "alpha"), state="draft")),
    )

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "非法 state 必须在 structure_errors 里报出来"
    assert "draft" in _structure_text(report)
    _assert_invariants(report, expected_entries=1)


# --------------------------------------------------------------------------- #
# 4. 结构错误：topic / claim / affects / evidence
# --------------------------------------------------------------------------- #
def test_should_report_structure_error_when_topic_or_claim_empty(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha"), topic='""'),
            _fact("DF-002", _ev("src/a.txt:3", "beta"), claim='""'),
        ),
    )

    report = _report(capsys, tmp_path)

    text = _structure_text(report)
    assert "DF-001" in text, "topic 为空必须在 structure_errors 里报出来"
    assert "DF-002" in text, "claim 为空必须在 structure_errors 里报出来"
    _assert_invariants(report, expected_entries=2)


def test_should_report_structure_error_when_affects_empty(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(_fact("DF-001", _ev("src/a.txt:1", "alpha"), affects=())),
    )

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "affects 为空必须在 structure_errors 里报出来"
    assert "DF-001" in _structure_text(report)
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_error_when_affects_value_unknown(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(_fact("DF-001", _ev("src/a.txt:1", "alpha"), affects=("code", "mystery"))),
    )

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "affects 未知取值必须在 structure_errors 里报出来"
    text = _structure_text(report)
    assert "DF-001" in text
    assert "mystery" in text
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_error_when_evidence_missing(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", ())))

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "evidence 为空必须在 structure_errors 里报出来"
    assert "DF-001" in _structure_text(report)
    assert report["totals"]["evidence"] == 0
    _assert_invariants(report, expected_entries=1)


# --------------------------------------------------------------------------- #
# 5. 正向判定：pass / pass_moved / gone
# --------------------------------------------------------------------------- #
def test_should_pass_when_expect_matches_line_after_whitespace_normalization(
    tmp_path: Path, capsys
) -> None:
    _write(tmp_path, "src/ws.txt", "line one\ndef   target(\tvalue )\n")
    _write_facts(
        tmp_path,
        _yaml(_fact("DF-001", _ev("src/ws.txt:2", "def target( value )"))),
    )

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/ws.txt:2")
    assert result["category"] == "pass"
    assert result["actual"] == 2
    assert result["actual_line"] == 2
    assert result["detail"] == "记录行命中"
    assert result["matches"] == []
    assert report["totals"]["passed"] == 1
    assert report["totals"]["passed_anchored"] == 1
    assert report["totals"]["passed_moved"] == 0
    assert report["totals"]["gone"] == 0
    assert report["totals"]["ambiguous"] == 0
    assert report["totals"]["unverifiable"] == 0
    assert report["totals"]["structure"] == 0
    _assert_invariants(report, expected_entries=1)


def test_should_pass_moved_when_expect_moved_to_another_line(
    tmp_path: Path, capsys
) -> None:
    """记录行对不上、但原文在全文唯一命中：改判 pass_moved（不再是旧口径的 drift）。"""
    _moved_repo(tmp_path)

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:2")
    assert result["category"] == "pass_moved", (
        f"行号错但全文唯一命中应判 pass_moved，实际 {result['category']!r}"
    )
    assert result["actual"] == 3, "位置已变的 actual 必须是唯一命中的真实行号"
    assert result["actual_line"] == 3
    assert result["matches"] == []
    assert "3" in result["detail"], (
        f"位置已变的 detail 必须写出唯一命中行号 3，实际 {result['detail']!r}"
    )
    assert report["totals"]["passed"] == 1
    assert report["totals"]["passed_moved"] == 1
    assert report["totals"]["passed_anchored"] == 0
    assert report["totals"]["gone"] == 0
    assert report["totals"]["ambiguous"] == 0
    _assert_invariants(report, expected_entries=1)


def test_should_count_pass_moved_in_totals_when_record_line_misses_and_expect_unique(
    tmp_path: Path, capsys
) -> None:
    """锚文本口径的汇总：记录行错 + 全文唯一命中 = pass_moved，并计入 passed。"""
    _moved_repo(tmp_path)

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:2")
    totals = report["totals"]
    assert result["category"] == "pass_moved"
    assert result["actual_line"] == 3
    assert totals["passed"] == 1
    assert totals["passed_moved"] == 1
    assert totals["passed_anchored"] == 0
    assert totals["ambiguous"] == 0
    assert "drift" not in totals, f"旧口径的 drift 键已废止，实际键 {sorted(totals)}"
    _assert_invariants(report, expected_entries=1)


def test_should_be_gone_when_expect_absent_from_existing_file(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:2", "gamma"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:2")
    assert result["category"] == "gone"
    assert result["actual"] is None
    assert result["actual_line"] is None
    assert result["matches"] == []
    assert result["detail"] == "未找到内容"
    assert report["totals"]["gone"] == 1
    assert report["totals"]["passed"] == 0
    assert report["totals"]["ambiguous"] == 0
    _assert_invariants(report, expected_entries=1)


def test_should_be_gone_when_ref_file_missing_outside_unchecked_prefixes(
    tmp_path: Path, capsys
) -> None:
    _write_facts(
        tmp_path,
        _yaml(_fact("DF-001", _ev("src/missing.txt:3", "alpha"))),
    )

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/missing.txt:3")
    assert result["category"] == "gone"
    assert result["actual"] is None
    assert result["actual_line"] is None
    assert "文件不存在" in result["detail"], (
        f"gone 的 detail 应指出文件不存在，实际 {result['detail']!r}"
    )
    assert report["totals"]["gone"] == 1
    assert report["totals"]["unverifiable"] == 0
    _assert_invariants(report, expected_entries=1)


# --------------------------------------------------------------------------- #
# 5b. 锚文本口径：命中即停（记录行命中不做全文搜索）与多处命中
# --------------------------------------------------------------------------- #
def test_should_not_search_whole_file_when_record_line_hits(tmp_path: Path, capsys) -> None:
    """第 2 行命中，即使全文有两处 alpha 也不得判 ambiguous（命中即停）。"""
    _repeated_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/dup.txt:2", "alpha"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/dup.txt:2")
    assert result["category"] == "pass", (
        "记录行命中必须早退（实现若先做全文搜索会变 ambiguous），"
        f"实际 {result['category']!r}"
    )
    assert result["detail"] == "记录行命中"
    assert result["matches"] == []
    assert report["totals"]["ambiguous"] == 0
    assert report["totals"]["passed_anchored"] == 1
    _assert_invariants(report, expected_entries=1)


def test_should_mark_ambiguous_when_needle_hits_multiple_lines(
    tmp_path: Path, capsys
) -> None:
    """记录行错且全文多处命中：判 ambiguous，列出全部命中行号，不得默认取第一处。"""
    _ambiguous_repo(tmp_path)

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/dup.txt:1")
    assert result["category"] == "ambiguous"
    assert result["matches"] == [2, 3], (
        f"必须列出全部命中行号（升序），实际 {result['matches']!r}"
    )
    assert result["actual"] is None, "歧义时不得给出单一 actual（不得默认取第一处）"
    assert result["actual_line"] is None
    assert report["totals"]["ambiguous"] == 1
    assert report["totals"]["passed"] == 0
    _assert_invariants(report, expected_entries=1)

    code, out = _run_text(capsys, ["--root", str(tmp_path), "--strict"])

    assert code != 0, f"存在 ambiguous 时必须让 --strict 非 0：\n{out}"
    assert _count_for_label(out, "歧义") == 1
    detail_lines = [line for line in out.splitlines() if "src/dup.txt:1" in line]
    assert detail_lines, f"默认输出缺少歧义明细行：\n{out}"
    assert any(
        line.startswith("AMBIGUOUS DF-001 src/dup.txt:1:") for line in detail_lines
    ), (
        "歧义明细行须为 `<CATEGORY 大写> <id> <ref>: <detail>`（AMBIGUOUS DF-001 src/dup.txt:1: ...）：\n"
        + "\n".join(detail_lines)
    )
    assert any(re.search(r"2[^\d]*3", line) for line in detail_lines), (
        "歧义明细行必须列出全部命中行号 2 与 3：\n" + "\n".join(detail_lines)
    )


# --------------------------------------------------------------------------- #
# 6. 证据级结构错误：expect / ref / 未知键
# --------------------------------------------------------------------------- #
def test_should_report_structure_for_empty_expect(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:1", '""'))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:1")
    assert result["category"] == "structure"
    assert report["totals"]["structure"] == 1
    assert "expect" in _structure_text(report).lower(), "expect 为空不得静默跳过"
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_for_non_string_expect(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    # `expect: 123` 在 YAML 里是整数，禁止隐式转换成字符串断言。
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:1", "123"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:1")
    assert result["category"] == "structure"
    assert report["totals"]["structure"] == 1
    assert "expect" in _structure_text(report).lower(), "expect 非字符串不得静默跳过"
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_when_expect_key_missing(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:1", None))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:1")
    assert result["category"] == "structure"
    assert report["totals"]["structure"] == 1
    assert "expect" in _structure_text(report).lower(), "缺 expect 不得静默跳过"
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_for_unknown_evidence_key(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(_fact("DF-001", ["      - ref: src/a.txt:1", "        contnt: alpha"])),
    )

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:1")
    assert result["category"] == "structure"
    assert report["totals"]["structure"] == 1
    assert report["structure_errors"], "未知 evidence 键必须在 structure_errors 里留记录"
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_when_ref_has_no_line_number(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt", "alpha"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt")
    assert result["category"] == "structure"
    assert report["totals"]["structure"] == 1
    _assert_invariants(report, expected_entries=1)


# --------------------------------------------------------------------------- #
# 7. unverifiable：未检出前缀 + evidence_location: original_worktree
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ref",
    [
        "pipeline/contracts/tensile_vlm_v4_1.json:196",
        "finetune/eval_semantics.py:63",
        "versioning/README.md:4",
        "docs/results/report.md:12",
    ],
)
def test_should_mark_unverifiable_for_unchecked_out_prefix(
    tmp_path: Path, capsys, ref: str
) -> None:
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev(ref, "任何片段"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, ref)
    assert result["category"] == "unverifiable"
    assert result["detail"] == "未检出前缀"
    assert result["actual"] is None
    assert report["totals"]["unverifiable"] == 1
    assert report["totals"]["passed"] == 0
    assert report["totals"]["gone"] == 0
    _assert_invariants(report, expected_entries=1)


def test_should_mark_unverifiable_when_original_worktree_ref_file_missing(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact(
                "DF-001",
                _ev("notes/remote-only.md:4", "只在原工作区存在的原文"),
                evidence_location="original_worktree",
            ),
            _fact("DF-002", _ev("src/a.txt:1", "alpha")),
        ),
    )

    report = _report(capsys, tmp_path)

    remote = _result_for(report, "notes/remote-only.md:4")
    assert remote["category"] == "unverifiable", "evidence_location: original_worktree 缺失须为 unverifiable"
    assert remote["actual"] is None
    assert "文件不存在" in remote["detail"], (
        f"原工作区缺失的 detail 应指出文件不存在，实际 {remote['detail']!r}"
    )
    local = _result_for(report, "src/a.txt:1")
    assert local["category"] == "pass", "同一份 YAML 里本机命中的 ref 仍算 pass"
    assert report["totals"]["unverifiable"] == 1
    assert report["totals"]["passed"] == 1
    assert report["totals"]["gone"] == 0
    _assert_invariants(report, expected_entries=2)


def test_should_still_pass_local_ref_inside_original_worktree_entry(
    tmp_path: Path, capsys
) -> None:
    """`docs/facts.yaml` 头部写明：同一 entry 的其余 evidence 仍可在本仓核对。"""
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact(
                "DF-001",
                _ev("notes/remote-only.md:4", "只在原工作区存在的原文")
                + _ev("src/a.txt:1", "alpha"),
                evidence_location="original_worktree",
            )
        ),
    )

    report = _report(capsys, tmp_path)

    assert _result_for(report, "notes/remote-only.md:4")["category"] == "unverifiable"
    assert _result_for(report, "src/a.txt:1")["category"] == "pass"
    assert report["totals"]["unverifiable"] == 1
    assert report["totals"]["passed"] == 1
    _assert_invariants(report, expected_entries=1)


def test_should_mark_unverifiable_when_file_cannot_be_decoded(
    tmp_path: Path, capsys
) -> None:
    """非 UTF-8 文件读不出来：不得当 gone/pass，必须判 unverifiable 并写明无法读取。"""
    binary = tmp_path / "src" / "bin.txt"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\xff\xfe\x00alpha\n")
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/bin.txt:1", "alpha"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/bin.txt:1")
    assert result["category"] == "unverifiable", (
        f"无法解码的文件必须判 unverifiable，实际 {result['category']!r}"
    )
    assert result["actual"] is None
    assert "无法读取文件" in result["detail"], (
        f"detail 应含「无法读取文件」，实际 {result['detail']!r}"
    )
    assert report["totals"]["unverifiable"] == 1
    assert report["totals"]["gone"] == 0
    _assert_invariants(report, expected_entries=1)


# --------------------------------------------------------------------------- #
# 8. misreadings
# --------------------------------------------------------------------------- #
def test_should_report_structure_error_for_empty_wrong_and_pass_its_evidence(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha")),
            misreadings=[
                _misreading(wrong='""', correct="正读内容"),
                _misreading(
                    wrong="误读内容",
                    correct="正读内容",
                    evidence=_ev("src/a.txt:3", "beta"),
                ),
            ],
        ),
    )

    report = _report(capsys, tmp_path)

    errors = report["structure_errors"]
    assert errors, "misreadings 的 wrong 为空必须报结构错误"
    assert any(
        str(error.get("id", "")).startswith("misreadings[") for error in errors
    ), f"结构错误 id 须为 misreadings[<序号>]，实际 {[e.get('id') for e in errors]!r}"
    assert _result_for(report, "src/a.txt:3")["category"] == "pass"
    assert report["totals"]["passed"] == 2
    _assert_invariants(report, expected_entries=3)


# --------------------------------------------------------------------------- #
# 9. 退出码口径
# --------------------------------------------------------------------------- #
def test_should_return_zero_without_strict_when_expect_moved(
    tmp_path: Path, capsys
) -> None:
    _moved_repo(tmp_path)
    report = _report(capsys, tmp_path)
    assert report["totals"]["passed_moved"] == 1

    code = main(["--root", str(tmp_path)])

    assert code == 0, "默认模式只报告不拦人"


def test_should_return_zero_with_strict_when_only_pass_moved(
    tmp_path: Path, capsys
) -> None:
    """位置已变（pass_moved）只提示、不拦人：--strict 必须返回 0。"""
    _moved_repo(tmp_path)
    report = _report(capsys, tmp_path)
    totals = report["totals"]
    assert totals["passed_moved"] == 1
    assert totals["gone"] == 0
    assert totals["ambiguous"] == 0
    assert totals["unverifiable"] == 0
    assert totals["structure"] == 0
    assert report["structure_errors"] == []

    code = main(["--root", str(tmp_path), "--strict"])

    assert code == 0, "只有 pass_moved 时 --strict 必须返回 0（位置变化不拦人）"


def test_should_return_zero_with_strict_when_all_pass(tmp_path: Path, capsys) -> None:
    _passing_repo(tmp_path)
    report = _report(capsys, tmp_path)
    assert report["totals"]["passed"] == 1
    assert report["structure_errors"] == []

    code = main(["--root", str(tmp_path), "--strict"])

    assert code == 0


# --------------------------------------------------------------------------- #
# 10. JSON 输出与 check_facts 的一致性
# --------------------------------------------------------------------------- #
def test_should_emit_parseable_json_with_fixed_shape_and_invariants(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha")),
            _fact("DF-002", _ev("src/a.txt:3", "beta")),
            _fact("DF-003", _ev("src/a.txt:9", "gamma")),
        ),
    )

    code, report = _run_json(capsys, ["--root", str(tmp_path), "--json"])

    assert code == 0
    assert isinstance(report["facts_path"], str)
    assert report["facts_path"].endswith("docs/facts.yaml")
    assert isinstance(report["results"], list)
    assert isinstance(report["structure_errors"], list)
    assert RESULT_KEYS <= set(report["results"][0])
    assert report["totals"]["entries"] == 3
    assert report["totals"]["passed"] == 2
    assert report["totals"]["gone"] == 1
    _assert_invariants(report, expected_entries=3)


def test_should_return_same_report_from_check_facts_as_json_cli(
    tmp_path: Path, capsys
) -> None:
    _passing_repo(tmp_path)
    facts_path = tmp_path / "docs" / "facts.yaml"

    _, report = _run_json(capsys, ["--root", str(tmp_path), "--json"])

    assert check_facts(tmp_path, facts_path) == report


# --------------------------------------------------------------------------- #
# 11. 白名单解析
# --------------------------------------------------------------------------- #
def test_should_parse_rules_and_skip_comments_and_blank_lines(tmp_path: Path) -> None:
    allowlist = tmp_path / "doc-path-allowlist.txt"
    allowlist.write_text(
        "# 注释\n"
        "refs: docs/.*\\.md\n"
        "files: docs/guide\\.md\n"
        "\n"
        "refs: a\\.py files: docs/x\\.md\n",
        encoding="utf-8",
    )

    rules = load_allowlist(allowlist)

    assert isinstance(rules, list)
    assert len(rules) == 3


def test_should_raise_value_error_when_allowlist_refs_pattern_missing(
    tmp_path: Path,
) -> None:
    allowlist = tmp_path / "doc-path-allowlist.txt"
    allowlist.write_text("refs:\n", encoding="utf-8")

    with pytest.raises(ValueError, match="缺正则") as excinfo:
        load_allowlist(allowlist)

    assert "refs" in str(excinfo.value)


def test_should_raise_value_error_when_allowlist_regex_invalid(tmp_path: Path) -> None:
    allowlist = tmp_path / "doc-path-allowlist.txt"
    allowlist.write_text("refs: ([unclosed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="正则无效") as excinfo:
        load_allowlist(allowlist)

    assert "refs" in str(excinfo.value)


def test_should_load_non_empty_rules_from_repo_allowlist() -> None:
    rules = load_allowlist(ROOT / "script" / "checks" / "doc-path-allowlist.txt")

    assert isinstance(rules, list)
    assert len(rules) > 0, "移植的白名单必须能解析出非空规则列表"
    assert all(rule is not None for rule in rules)


# --------------------------------------------------------------------------- #
# 12. CLI 其它参数
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_should_exit_zero_on_help_and_print_usage(capsys, flag: str) -> None:
    try:
        code = main([flag])
    except SystemExit as exc:  # argparse 风格实现按 SystemExit(0) 退出
        code = 0 if exc.code is None else int(exc.code)

    assert code == 0
    assert capsys.readouterr().out.strip()


# --------------------------------------------------------------------------- #
# 13. 集成用例：真实 docs/facts.yaml（唯一读真实数据的判定用例）
# --------------------------------------------------------------------------- #
def test_should_report_real_facts_without_breaking_invariants(capsys) -> None:
    code, report = _run_json(capsys, ["--json"])

    assert code == 0, "默认模式下真实数据必须只报告、不拦人"
    assert report["facts_path"].endswith("docs/facts.yaml")
    assert Path(report["facts_path"]).is_file()
    _assert_invariants(report)
    totals = report["totals"]
    for category in (
        "passed",
        "passed_anchored",
        "passed_moved",
        "gone",
        "ambiguous",
        "unverifiable",
        "structure",
    ):
        assert 0 <= totals[category] <= totals["evidence"]


# --------------------------------------------------------------------------- #
# 14. totals 契约：固定键集合、structure_errors 与 structure 的区别
# --------------------------------------------------------------------------- #
def test_should_expose_exact_totals_key_set(tmp_path: Path, capsys) -> None:
    _passing_repo(tmp_path)

    report = _report(capsys, tmp_path)

    assert set(report["totals"]) == TOTALS_KEYS, (
        f"totals 键集合应为 {sorted(TOTALS_KEYS)}，实际 {sorted(report['totals'])}"
    )
    assert "drift" not in report["totals"], (
        f"旧键 drift 必须废止，实际键 {sorted(report['totals'])}"
    )
    assert report["totals"]["structure_errors"] == len(report["structure_errors"]) == 0


def test_should_expose_exact_result_key_set(tmp_path: Path, capsys) -> None:
    _passing_repo(tmp_path)

    report = _report(capsys, tmp_path)

    assert len(report["results"]) == 1
    assert set(report["results"][0]) == RESULT_KEYS, (
        f"单条 result 键集合应为 {sorted(RESULT_KEYS)}，实际 {sorted(report['results'][0])}"
    )


def test_should_count_entry_level_structure_errors_apart_from_structure_category(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha"), affects=("code", "mystery"))
        ),
    )

    report = _report(capsys, tmp_path)

    assert report["totals"]["structure"] == 0, "条目级结构错误不计入 evidence 级 structure"
    assert _structure_error_count(report) == 1
    assert report["totals"]["entries"] == 1, "结构错误不改变 entries 计数"
    assert report["totals"]["passed"] == 1
    _assert_invariants(report, expected_entries=1)


def test_should_sum_all_structure_error_levels_in_totals(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    body = _yaml(
        _fact("DF-001", _ev("src/a.txt:1", '""'), affects=("code", "mystery")),
        _fact("DF-002", _ev("src/a.txt:3", "beta")),
    ).replace("version: 1\n", "", 1)
    _write(tmp_path, "docs/facts.yaml", body)

    report = _report(capsys, tmp_path)

    text = _structure_text(report)
    assert "version" in text.lower(), "文档级结构错误缺失"
    assert "mystery" in text, "条目级结构错误缺失"
    assert "expect" in text.lower(), "evidence 级结构错误缺失"
    assert report["totals"]["structure"] == 1, "只有 evidence 级错误计入 structure"
    assert _structure_error_count(report) == len(report["structure_errors"])
    _assert_invariants(report, expected_entries=2)


def test_should_count_entries_as_facts_plus_misreadings(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha")),
            _fact("DF-002", _ev("src/a.txt:3", "beta")),
            misreadings=[_misreading(evidence=_ev("src/a.txt:1", "alpha"))],
        ),
    )

    report = _report(capsys, tmp_path)

    assert report["totals"]["entries"] == 3, "entries = facts 条数 + misreadings 条数"
    assert report["totals"]["evidence"] == 3
    assert report["totals"]["passed"] == 3
    _assert_invariants(report, expected_entries=3)


# --------------------------------------------------------------------------- #
# 15. 默认模式（不带 --json）的人类可读输出
# --------------------------------------------------------------------------- #
def _mixed_repo(root: Path) -> None:
    """五类各一条：1 通过 / 1 原文消失 / 1 歧义 / 1 本机无法核对 / 1 结构错误。"""
    _linear_source(root)
    _repeated_source(root)
    _write_facts(
        root,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha")),
            _fact("DF-002", _ev("src/a.txt:2", "gamma")),
            _fact("DF-003", _ev("src/dup.txt:1", "alpha")),
            _fact("DF-004", _ev("pipeline/contracts/x.json:1", "片段")),
            # 未知 evidence 键：evidence 级结构错误（category=structure）
            _fact("DF-005", ["      - ref: src/a.txt:3", "        contnt: beta"]),
        ),
    )


def test_should_print_chinese_summary_labels_with_numbers(tmp_path: Path, capsys) -> None:
    _mixed_repo(tmp_path)

    _, out = _run_text(capsys, ["--root", str(tmp_path)])

    expected = {"通过": 1, "原文消失": 1, "歧义": 1, "本机无法核对": 1, "结构错误": 1}
    for label, count in expected.items():
        assert label in SUMMARY_LABELS
        assert _count_for_label(out, label) == count, (
            f"汇总标签 {label!r} 的数字应为 {count}，输出为：\n{out}"
        )
    for label in DEPRECATED_LABELS:
        assert label not in out, f"旧口径标签 {label!r} 不得再出现在默认输出里：\n{out}"


def test_should_print_pass_moved_detail_with_actual_line(tmp_path: Path, capsys) -> None:
    _moved_repo(tmp_path)

    _, out = _run_text(capsys, ["--root", str(tmp_path)])

    lines = [line for line in out.splitlines() if "src/a.txt:2" in line]
    assert lines, f"默认输出缺少位置已变明细行：\n{out}"
    assert any(
        line.startswith("PASS_MOVED DF-001 src/a.txt:2:") for line in lines
    ), (
        "位置已变明细行须为 `<CATEGORY 大写> <id> <ref>: <detail>`"
        "（PASS_MOVED DF-001 src/a.txt:2: ...）：\n" + "\n".join(lines)
    )
    assert any("3" in line for line in lines), (
        "位置已变明细行必须写出唯一命中行号 3（ref 里只有 2）：\n" + "\n".join(lines)
    )
    assert _count_for_label(out, "通过") == 1, (
        f"位置已变计入「通过」，实际输出：\n{out}"
    )


def test_should_print_gone_ref_in_default_output(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:2", "gamma"))))

    _, out = _run_text(capsys, ["--root", str(tmp_path)])

    lines = [line for line in out.splitlines() if "src/a.txt:2" in line]
    assert lines, f"默认输出缺少原文消失明细行：\n{out}"
    assert any(
        line.startswith("GONE DF-001 src/a.txt:2:") and "未找到内容" in line
        for line in lines
    ), (
        "原文消失明细行须为 `GONE DF-001 src/a.txt:2: 未找到内容` 形式：\n"
        + "\n".join(lines)
    )
    assert _count_for_label(out, "原文消失") == 1


def test_should_print_entry_level_structure_error_in_default_output(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha"), affects=("code", "mystery"))
        ),
    )

    _, out = _run_text(capsys, ["--root", str(tmp_path)])

    lines = [line for line in out.splitlines() if "mystery" in line]
    assert lines, f"默认输出必须能看到条目级结构错误（affects 超枚举）：\n{out}"
    assert any("DF-001" in line for line in lines), (
        "结构错误明细行须带条目 id：\n" + "\n".join(lines)
    )


# --------------------------------------------------------------------------- #
# 16. --strict 退出码口径：gone / unverifiable / 条目级结构错误 各自单测
# --------------------------------------------------------------------------- #
def test_should_return_nonzero_with_strict_when_only_gone_present(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:2", "gamma"))))

    report = _report(capsys, tmp_path)
    assert report["totals"]["gone"] == 1
    assert report["totals"]["ambiguous"] == 0
    assert report["totals"]["passed_moved"] == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "--strict"]) != 0, "只有 gone 也必须让 --strict 非 0"


def test_should_return_nonzero_with_strict_when_only_unverifiable_present(
    tmp_path: Path, capsys
) -> None:
    _write_facts(
        tmp_path, _yaml(_fact("DF-001", _ev("pipeline/contracts/x.json:1", "片段")))
    )

    report = _report(capsys, tmp_path)
    assert report["totals"]["unverifiable"] == 1
    assert report["totals"]["gone"] == 0
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "--strict"]) != 0, (
        "只有 unverifiable 也必须让 --strict 非 0"
    )


def test_should_return_nonzero_with_strict_when_only_entry_level_structure_error(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha"), affects=("code", "mystery"))
        ),
    )

    report = _report(capsys, tmp_path)
    assert report["totals"]["ambiguous"] == 0
    assert report["totals"]["passed_moved"] == 0
    assert report["totals"]["gone"] == 0
    assert report["totals"]["unverifiable"] == 0
    assert report["totals"]["structure"] == 0
    assert report["structure_errors"], "本条要覆盖的正是 evidence 全 pass 但结构错误非空"
    capsys.readouterr()

    assert main(["--root", str(tmp_path), "--strict"]) != 0, (
        "structure_errors 非空时 --strict 必须非 0，即使五类计数里只有 pass"
    )


def test_should_return_nonzero_with_strict_json_and_keep_pure_json(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:2", "gamma"))))

    code = main(["--root", str(tmp_path), "--json", "--strict"])
    out = capsys.readouterr().out

    assert code != 0
    report = json.loads(out)  # 整段 stdout 必须是纯 JSON，多一行文本就会解析失败
    assert report["totals"]["gone"] == 1
    assert "drift" not in report["totals"]


# --------------------------------------------------------------------------- #
# 17. state: obsolete 必须带 residue
# --------------------------------------------------------------------------- #
def test_should_report_structure_error_when_obsolete_entry_lacks_residue(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(_fact("DF-001", _ev("src/a.txt:1", "alpha"), state="obsolete")),
    )

    report = _report(capsys, tmp_path)

    assert report["structure_errors"], "state: obsolete 缺 residue 必须报结构错误"
    assert "residue" in _structure_text(report).lower()
    assert report["totals"]["passed"] == 1, "residue 缺失不影响 evidence 判定"
    _assert_invariants(report, expected_entries=1)


def test_should_not_report_residue_error_when_obsolete_entry_has_residue(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact(
                "DF-001",
                _ev("src/a.txt:1", "alpha"),
                state="obsolete",
                residue="已由 DF-002 取代",
            )
        ),
    )

    report = _report(capsys, tmp_path)

    assert report["structure_errors"] == [], (
        f"带 residue 的 obsolete 条目不得报结构错误，实际 {report['structure_errors']!r}"
    )
    assert report["totals"]["passed"] == 1
    _assert_invariants(report, expected_entries=1)


# --------------------------------------------------------------------------- #
# 18. evidence 判定边界
# --------------------------------------------------------------------------- #
def test_should_pass_moved_when_line_number_out_of_range(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:99", "beta"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:99")
    assert result["category"] == "pass_moved", (
        f"行号越界但原文在全文唯一命中 = 位置已变，不是 gone，实际 {result['category']!r}"
    )
    assert result["actual"] == 3
    assert result["actual_line"] == 3
    assert report["totals"]["passed_moved"] == 1
    assert report["totals"]["passed_anchored"] == 0
    assert report["totals"]["gone"] == 0
    _assert_invariants(report, expected_entries=1)


def test_should_pass_moved_when_ref_points_to_blank_line(tmp_path: Path, capsys) -> None:
    _write(tmp_path, "src/blank.txt", "alpha\n\nbeta\n")
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/blank.txt:2", "beta"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/blank.txt:2")
    assert result["category"] == "pass_moved", (
        f"指向空行且原文在全文唯一命中 = 位置已变，实际 {result['category']!r}"
    )
    assert result["actual"] == 3
    assert result["actual_line"] == 3
    assert report["totals"]["ambiguous"] == 0
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_for_absolute_ref_path(tmp_path: Path, capsys) -> None:
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("/etc/passwd:1", "root"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "/etc/passwd:1")
    assert result["category"] == "structure", "绝对路径 ref 必须判结构错误，不得读仓库外文件"
    assert "相对路径" in _structure_text(report)
    assert report["totals"]["structure"] == 1
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_when_ref_escapes_root(tmp_path: Path, capsys) -> None:
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("../outside.txt:1", "alpha"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "../outside.txt:1")
    assert result["category"] == "structure", "越出仓库根的 ref 必须判结构错误"
    assert report["totals"]["structure"] == 1
    assert report["totals"]["gone"] == 0
    _assert_invariants(report, expected_entries=1)


def test_should_pass_when_path_contains_colon(tmp_path: Path, capsys) -> None:
    _write(tmp_path, "src/a:b.py", "x\nalpha\n")
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a:b.py:2", "alpha"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a:b.py:2")
    assert result["category"] == "pass", "路径里的冒号不能被当成分隔符"
    assert result["actual"] == 2
    assert report["totals"]["passed"] == 1
    _assert_invariants(report, expected_entries=1)


def test_should_report_structure_when_expect_contains_newline(
    tmp_path: Path, capsys
) -> None:
    _write(tmp_path, "src/a.txt", "alpha\nbeta\n")
    _write_facts(
        tmp_path,
        _yaml(
            _fact(
                "DF-001",
                [
                    "      - ref: src/a.txt:1",
                    "        expect: |-",
                    "          alpha",
                    "          beta",
                ],
            )
        ),
    )

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:1")
    assert result["category"] == "structure", "多行 expect 无法当单行内容断言"
    assert "换行" in _structure_text(report)
    _assert_invariants(report, expected_entries=1)


def test_should_mark_ambiguous_when_needle_repeats(
    tmp_path: Path, capsys
) -> None:
    """记录行（第 1 行 x）未命中、全文两处命中：判 ambiguous，不得取首次命中。"""
    _ambiguous_repo(tmp_path)

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/dup.txt:1")
    assert result["category"] == "ambiguous"
    assert result["matches"] == [2, 3], (
        f"多处命中必须列出全部行号 [2, 3]，实际 {result['matches']!r}"
    )
    assert result["actual"] is None, "多处命中不得默认取第一处（actual 必须为 None）"
    assert result["actual_line"] is None
    assert report["totals"]["ambiguous"] == 1
    assert report["totals"]["passed"] == 0
    _assert_invariants(report, expected_entries=1)

    assert main(["--root", str(tmp_path), "--strict"]) != 0, (
        "存在 ambiguous 时 --strict 必须返回非 0"
    )


# --------------------------------------------------------------------------- #
# 19. misreadings 的三种口径
# --------------------------------------------------------------------------- #
def test_should_report_structure_error_when_misreading_correct_empty(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha")),
            misreadings=[_misreading(wrong="误读内容", correct='""')],
        ),
    )

    report = _report(capsys, tmp_path)

    errors = report["structure_errors"]
    assert errors, "misreadings 的 correct 为空必须报结构错误"
    assert any("correct" in str(error.get("message", "")) for error in errors), (
        f"结构错误文案须点出 correct，实际 {[e.get('message') for e in errors]!r}"
    )
    _assert_invariants(report, expected_entries=2)


def test_should_pass_moved_for_misreading_evidence(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha")),
            misreadings=[_misreading(evidence=_ev("src/a.txt:2", "beta"))],
        ),
    )

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:2")
    assert result["category"] == "pass_moved"
    assert result["actual"] == 3
    assert result["actual_line"] == 3
    assert result["id"] == "misreadings[1]"
    # 本 fixture 有两条 evidence：DF-001 的 src/a.txt:1 记录行命中（第 1 行就是 alpha），
    # misreadings[1] 的 src/a.txt:2 位置已变（第 2 行是 placeholder，beta 唯一命中第 3 行）；
    # 按契约 C，两者都计入 passed，因此 passed == 2 == passed_anchored(1) + passed_moved(1)。
    assert report["totals"]["passed_moved"] == 1
    assert report["totals"]["passed_anchored"] == 1
    assert report["totals"]["passed"] == 2
    _assert_invariants(report, expected_entries=2)


def test_should_mark_misreading_evidence_unverifiable_for_unchecked_prefix(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(
        tmp_path,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha")),
            misreadings=[
                _misreading(evidence=_ev("pipeline/contracts/x.json:1", "片段"))
            ],
        ),
    )

    report = _report(capsys, tmp_path)

    result = _result_for(report, "pipeline/contracts/x.json:1")
    assert result["category"] == "unverifiable"
    assert report["totals"]["unverifiable"] == 1
    _assert_invariants(report, expected_entries=2)


# --------------------------------------------------------------------------- #
# 20. --facts 指向非默认 YAML
# --------------------------------------------------------------------------- #
def test_should_read_facts_from_custom_path_and_ignore_default(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    # 默认文件里的条目是「不该被读到」的哨兵：若被读，会多出 DF-900 与 gone 计数。
    _write_facts(tmp_path, _yaml(_fact("DF-900", _ev("src/a.txt:9", "gamma"))))
    custom = _write(
        tmp_path,
        "custom/facts-copy.yaml",
        _yaml(_fact("DF-001", _ev("src/a.txt:1", "alpha"))),
    )

    code, report = _run_json(
        capsys, ["--root", str(tmp_path), "--facts", str(custom), "--json"]
    )

    assert code == 0
    assert Path(report["facts_path"]).resolve() == custom.resolve(), (
        f"report 的 facts_path 应为 --facts 指定的文件，实际 {report['facts_path']!r}"
    )
    assert [result["id"] for result in report["results"]] == ["DF-001"], (
        "默认 docs/facts.yaml 的哨兵条目不得被读入"
    )
    assert report["totals"]["entries"] == 1
    assert report["totals"]["passed"] == 1
    _assert_invariants(report, expected_entries=1)


# --------------------------------------------------------------------------- #
# 21. --check-doc-paths 行为（tmp 里造小仓库，不扫真实仓库）
# --------------------------------------------------------------------------- #
@requires_git
def test_should_report_missing_doc_path_when_not_exempted(
    tmp_path: Path, capsys
) -> None:
    _init_doc_path_repo(tmp_path)

    code = main(["--root", str(tmp_path), "--check-doc-paths"])
    out = capsys.readouterr().out

    assert code != 0, f"引用不存在且未豁免时必须非 0：\n{out}"
    assert "MISSING" in out
    assert "docs/missing-target.md" in out


@requires_git
def test_should_follow_root_scoped_default_allowlist(tmp_path: Path, capsys) -> None:
    _init_doc_path_repo(tmp_path)
    _write(
        tmp_path,
        "script/checks/doc-path-allowlist.txt",
        "refs: docs/missing-target\\.md\n",
    )

    code = main(["--root", str(tmp_path), "--check-doc-paths"])
    out = capsys.readouterr().out

    assert code == 0, (
        "默认白名单位置必须随 --root 走（<root>/script/checks/doc-path-allowlist.txt）：\n"
        + out
    )
    assert re.search(r"豁免\s*1\s*处", out), f"输出须含豁免计数：\n{out}"


@requires_git
def test_should_honor_explicit_allowlist_override(tmp_path: Path, capsys) -> None:
    _init_doc_path_repo(tmp_path)
    override = tmp_path / "other-allowlist.txt"
    override.write_text("refs: docs/missing-target\\.md\n", encoding="utf-8")

    code = main(
        ["--root", str(tmp_path), "--check-doc-paths", "--allowlist", str(override)]
    )
    out = capsys.readouterr().out

    assert not (tmp_path / "script" / "checks" / "doc-path-allowlist.txt").exists()
    assert code == 0, f"--allowlist 显式覆盖必须生效：\n{out}"
    assert re.search(r"豁免\s*1\s*处", out), f"输出须含豁免计数：\n{out}"


# --------------------------------------------------------------------------- #
# 22. 白名单规则解析：ref / file 的具体取值
# --------------------------------------------------------------------------- #
def test_should_parse_refs_only_rule_into_ref_pattern(tmp_path: Path) -> None:
    allowlist = tmp_path / "doc-path-allowlist.txt"
    allowlist.write_text("refs: docs/.*\\.md\n", encoding="utf-8")

    rules = load_allowlist(allowlist)

    assert len(rules) == 1
    rule = rules[0]
    assert rule["text"] == "refs: docs/.*\\.md"
    assert rule["source"].endswith(":1")
    assert rule["file"] is None, "只给 refs 时 file 必须是 None"
    assert rule["ref"] is not None
    assert rule["ref"].fullmatch("docs/guide.md")
    assert not rule["ref"].fullmatch("src/a.py")


def test_should_parse_files_only_rule_into_file_pattern(tmp_path: Path) -> None:
    allowlist = tmp_path / "doc-path-allowlist.txt"
    allowlist.write_text("files: docs/guide\\.md\n", encoding="utf-8")

    rules = load_allowlist(allowlist)

    assert len(rules) == 1
    rule = rules[0]
    assert rule["text"] == "files: docs/guide\\.md"
    assert rule["ref"] is None, "只给 files 时 ref 必须是 None"
    assert rule["file"] is not None
    assert rule["file"].fullmatch("docs/guide.md")
    assert not rule["file"].fullmatch("docs/other.md")


def test_should_parse_combined_refs_and_files_rule(tmp_path: Path) -> None:
    allowlist = tmp_path / "doc-path-allowlist.txt"
    allowlist.write_text("refs: a\\.py files: docs/x\\.md\n", encoding="utf-8")

    rules = load_allowlist(allowlist)

    assert len(rules) == 1
    rule = rules[0]
    assert rule["text"] == "refs: a\\.py files: docs/x\\.md"
    assert rule["ref"] is not None and rule["file"] is not None
    assert rule["ref"].fullmatch("a.py")
    assert rule["file"].fullmatch("docs/x.md")
    assert not rule["ref"].fullmatch("sub/a.py"), "规则按 fullmatch 判定，不做子串搜索"
