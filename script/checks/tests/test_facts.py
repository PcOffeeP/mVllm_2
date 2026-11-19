"""`script/checks/facts.py` 的契约测试。

覆盖范围：
- 单元层：`normalize`、白名单规则解析（`load_allowlist`）；
- 行为层：除集成用例外，每个用例都在 `tmp_path` 里造 `<tmp>/docs/facts.yaml` 与被引用的源文件，
  再用 `main(["--root", str(tmp), ...])` 跑一遍，按 `category` 五分类口径、JSON 固定形状、
  默认模式（不带 `--json`）的人类可读输出文案与 `--strict` 退出码断言；
- `--check-doc-paths`：在 `tmp_path` 里 `git init` 造小仓库做行为测试，不扫真实仓库；
- 集成层：`test_should_report_real_facts_without_breaking_invariants` 等少量用例读真实仓库数据，
  只断不变量与退出码，不断言具体条数（真实数据随文档修订漂移）。

分类口径（`category`）：`pass` / `drift` / `gone` / `unverifiable` / `structure`。
汇总口径（`totals`）：`entries == facts 条数 + misreadings 条数`；
`passed + drift + gone + unverifiable + structure == evidence == len(results)`；
`structure` 只数 evidence 级结构错误，`structure_errors` 数全部结构错误记录（文档级 + 条目级 +
evidence 级）。

失效条件：`script/checks/facts.py` 的分类口径、`totals` 键集合、默认输出文案或 `--strict` 语义变更时，
本文件需同步修订。
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
    "drift",
    "gone",
    "unverifiable",
    "structure",
}
# 完整键集合（契约）：由 `test_should_expose_exact_totals_key_set` 断言，不放进共享不变量里，
# 否则同一根因会让几十个用例一起红、掩盖各自要验证的行为。
TOTALS_KEYS = LEGACY_TOTALS_KEYS | {"structure_errors"}
RESULT_KEYS = {"id", "ref", "expect", "actual", "category", "detail"}
# 五个中文汇总标签（默认模式必须逐条带数字）。
SUMMARY_LABELS = ("通过", "位置漂移", "原文消失", "本机无法核对", "结构错误")
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


def _passing_repo(root: Path) -> None:
    _linear_source(root)
    _write_facts(root, _yaml(_fact("DF-001", _ev("src/a.txt:1", "alpha"))))


def _drift_repo(root: Path) -> None:
    _linear_source(root)
    _write_facts(root, _yaml(_fact("DF-001", _ev("src/a.txt:2", "beta"))))


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
    assert len(results) == totals["evidence"]
    assert (
        totals["passed"]
        + totals["drift"]
        + totals["gone"]
        + totals["unverifiable"]
        + totals["structure"]
        == totals["evidence"]
    )
    assert totals["structure"] == len(_by_category(report, "structure"))
    if expected_entries is not None:
        assert totals["entries"] == expected_entries
    for result in results:
        assert RESULT_KEYS <= set(result)
        if result["category"] in ("pass", "drift"):
            assert isinstance(result["actual"], int)
            assert not isinstance(result["actual"], bool)
        if result["category"] in ("gone", "unverifiable"):
            assert result["actual"] is None


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
# 5. 三类正向判定：pass / drift / gone
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
    assert report["totals"]["passed"] == 1
    assert report["totals"]["drift"] == 0
    assert report["totals"]["gone"] == 0
    assert report["totals"]["unverifiable"] == 0
    assert report["totals"]["structure"] == 0
    _assert_invariants(report, expected_entries=1)


def test_should_drift_when_expect_moved_to_another_line(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:2", "beta"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:2")
    assert result["category"] == "drift"
    assert result["actual"] == 3, "漂移的 actual 必须是首次命中的真实行号"
    assert report["totals"]["drift"] == 1
    assert report["totals"]["passed"] == 0
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
    assert report["totals"]["gone"] == 1
    assert report["totals"]["passed"] == 0
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
    assert report["totals"]["gone"] == 1
    assert report["totals"]["unverifiable"] == 0
    _assert_invariants(report, expected_entries=1)


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
def test_should_return_zero_without_strict_when_drift_present(
    tmp_path: Path, capsys
) -> None:
    _drift_repo(tmp_path)
    report = _report(capsys, tmp_path)
    assert report["totals"]["drift"] == 1

    code = main(["--root", str(tmp_path)])

    assert code == 0, "默认模式只报告不拦人"


def test_should_return_nonzero_with_strict_when_drift_present(
    tmp_path: Path, capsys
) -> None:
    _drift_repo(tmp_path)
    report = _report(capsys, tmp_path)
    assert report["totals"]["drift"] == 1

    code = main(["--root", str(tmp_path), "--strict"])

    assert code != 0, "--strict 下漂移必须让退出码非 0"


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
    for category in ("passed", "drift", "gone", "unverifiable", "structure"):
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
    assert report["totals"]["structure_errors"] == len(report["structure_errors"]) == 0


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
    """2 通过 / 1 位置漂移 / 1 原文消失 / 1 本机无法核对 / 0 结构错误。"""
    _linear_source(root)
    _write_facts(
        root,
        _yaml(
            _fact("DF-001", _ev("src/a.txt:1", "alpha") + _ev("src/a.txt:3", "beta")),
            _fact("DF-002", _ev("src/a.txt:2", "beta")),
            _fact("DF-003", _ev("src/a.txt:2", "gamma")),
            _fact("DF-004", _ev("pipeline/contracts/x.json:1", "片段")),
        ),
    )


def test_should_print_chinese_summary_labels_with_numbers(tmp_path: Path, capsys) -> None:
    _mixed_repo(tmp_path)

    _, out = _run_text(capsys, ["--root", str(tmp_path)])

    expected = {"通过": 2, "位置漂移": 1, "原文消失": 1, "本机无法核对": 1, "结构错误": 0}
    for label, count in expected.items():
        assert label in SUMMARY_LABELS
        assert _count_for_label(out, label) == count, (
            f"汇总标签 {label!r} 的数字应为 {count}，输出为：\n{out}"
        )


def test_should_print_actual_line_number_in_drift_detail(tmp_path: Path, capsys) -> None:
    _drift_repo(tmp_path)

    _, out = _run_text(capsys, ["--root", str(tmp_path)])

    lines = [line for line in out.splitlines() if "src/a.txt:2" in line]
    assert lines, f"默认输出缺少 drift 明细行：\n{out}"
    assert any(re.search(r"实际行号[：: ]*3", line) for line in lines), (
        "drift 明细行必须写出实际行号 3：\n" + "\n".join(lines)
    )


def test_should_print_gone_ref_in_default_output(tmp_path: Path, capsys) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:2", "gamma"))))

    _, out = _run_text(capsys, ["--root", str(tmp_path)])

    lines = [line for line in out.splitlines() if "src/a.txt:2" in line]
    assert lines, f"默认输出缺少原文消失明细行：\n{out}"
    assert any("原文消失" in line or "GONE" in line for line in lines), (
        "原文消失明细行须标明类别并带 ref：\n" + "\n".join(lines)
    )


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
    assert report["totals"]["drift"] == 0
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
    assert report["totals"]["drift"] == 0
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
    _drift_repo(tmp_path)

    code = main(["--root", str(tmp_path), "--json", "--strict"])
    out = capsys.readouterr().out

    assert code != 0
    report = json.loads(out)  # 整段 stdout 必须是纯 JSON，多一行文本就会解析失败
    assert report["totals"]["drift"] == 1


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
def test_should_drift_with_real_line_when_line_number_out_of_range(
    tmp_path: Path, capsys
) -> None:
    _linear_source(tmp_path)
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/a.txt:99", "beta"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/a.txt:99")
    assert result["category"] == "drift", "行号越界但内容在别处 = 位置漂移，不是 gone"
    assert result["actual"] == 3
    assert report["totals"]["drift"] == 1
    _assert_invariants(report, expected_entries=1)


def test_should_drift_when_ref_points_to_blank_line(tmp_path: Path, capsys) -> None:
    _write(tmp_path, "src/blank.txt", "alpha\n\nbeta\n")
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/blank.txt:2", "beta"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/blank.txt:2")
    assert result["category"] == "drift", "指向空行且内容在别处 = 位置漂移"
    assert result["actual"] == 3
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


def test_should_drift_to_first_occurrence_when_needle_repeats(
    tmp_path: Path, capsys
) -> None:
    _write(tmp_path, "src/dup.txt", "x\nalpha\nalpha\n")
    _write_facts(tmp_path, _yaml(_fact("DF-001", _ev("src/dup.txt:1", "alpha"))))

    report = _report(capsys, tmp_path)

    result = _result_for(report, "src/dup.txt:1")
    assert result["category"] == "drift"
    assert result["actual"] == 2, "重复片段取首次命中行"
    _assert_invariants(report, expected_entries=1)


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


def test_should_drift_for_misreading_evidence(tmp_path: Path, capsys) -> None:
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
    assert result["category"] == "drift"
    assert result["actual"] == 3
    assert result["id"] == "misreadings[1]"
    assert report["totals"]["drift"] == 1
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
