"""Runtime behaviour of the annotation tool's historical-value mapping.

`test_label_option_contract.py` only reads the browser sources as text: it can
prove that a mapping entry exists, but not that `annotationLabel` / `setControl`
/ the `completionIssues` invalid scan actually agree at run time.  Replacing the
mapping lookup with a plain equality check used to keep every test green.

This module therefore *executes* the real fragments of
`script/annotation/review_annotation.js` (the three column constants, the
`legacyUncertainLabels` literal, `annotationLabel`, `setControl` and the
`annotationOptions` invalid scan) together with the real `<option>` lists of the
three `<select>` controls, inside a throw-away node process.  Nothing is
re-implemented in the test: only extracted source text is evaluated, and a
failed extraction is a hard assertion error, never a skip.

No npm package, no browser and no network is involved; node itself is the only
external dependency and the whole module skips (with a reason) without it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from script.integration_tests.test_label_option_contract import (
    html_text,
    js_map_literal_body,
    js_text,
    select_option_values,
)


NODE = shutil.which("node")
NODE_MISSING_REASON = (
    "node 不可用（shutil.which('node') 为 None）：本模块用 node 执行 review_annotation.js 的"
    "历史值映射片段，没有 node 就无法验证运行期行为；这不是实现缺陷。"
)

# The three `<select>` controls that write a single fracture label.
SINGLE_CONTROLS = {"断裂状态": "state", "断裂模式": "mechanism", "断裂位置": "site"}
UNIFIED = "无法判断"
SUPERSEDED = "无法确定"

# (column, raw cell value) still found in old tables that now display as UNIFIED.
LEGACY_CASES = [
    ("断裂状态", SUPERSEDED),
    ("断裂模式", SUPERSEDED),
    ("断裂位置", SUPERSEDED),
    ("断裂模式", "无法识别"),
]
UNIFIED_CASES = [(column, UNIFIED) for column in sorted(SINGLE_CONTROLS)]
# Values the tool has no mapping for: shown verbatim and still reported invalid.
UNKNOWN_CASES = [
    ("断裂状态", "旧表自定义值"),
    ("断裂模式", "无法判断 "),
    ("断裂位置", "无法确定 "),
]

COLUMN_CONSTANTS = ("stateColumn", "mechanismColumn", "siteColumn")

# Every (kind, column, value) probed in the node process, in report order.
ALL_CASES = ([("legacy", column, value) for column, value in LEGACY_CASES]
             + [("unified", column, value) for column, value in UNIFIED_CASES]
             + [("unknown", column, value) for column, value in UNKNOWN_CASES])


# --- extraction of the real source fragments ---------------------------------

def _skip_js_string(source, index):
    """Return the index just past the JS string/template literal at `index`."""
    quote = source[index]
    index += 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if quote == "`" and char == "$" and source[index + 1:index + 2] == "{":
            index = _balanced(source, index + 1, "{", "}")
            continue
        index += 1
    raise AssertionError(f"unterminated JS string literal near: {source[max(0, index - 80):index]!r}")


def _balanced(source, open_index, open_char, close_char):
    """Return the index just past the bracket matching `source[open_index]`.

    Strings, template literals and comments are skipped so that braces inside
    them do not unbalance the scan.  Regex literals are not tracked; a fragment
    holding one would end in an explicit "unbalanced" error, not a silent pass.
    """
    assert source[open_index] == open_char, (open_char, source[open_index:open_index + 60])
    depth = 1
    index = open_index + 1
    while index < len(source):
        char = source[index]
        if char in "\"'`":
            index = _skip_js_string(source, index)
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index)
            index = len(source) if newline == -1 else newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            assert end != -1, f"unterminated block comment from {index}: {source[index:index + 80]!r}"
            index = end + 2
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise AssertionError(
        f"unbalanced {open_char}{close_char} starting at offset {open_index}: "
        f"{source[open_index:open_index + 160]!r}")


def js_function_source(source, name):
    """Return the complete `function <name>(...) { ... }` text from the source."""
    match = js_function_match(source, name)
    # The regex ends on the body's opening brace, which is the one to balance.
    body_open = match.end() - 1
    assert source[body_open] == "{", (name, source[body_open:body_open + 40])
    body_end = _balanced(source, body_open, "{", "}")
    return source[match.start():body_end].rstrip()


def js_function_match(source, name):
    """Return the regex match anchoring one function declaration."""
    match = re.search(r'function\s+%s\s*\([^)]*\)\s*\{' % name, source)
    assert match, f"function {name} not found in review_annotation.js"
    return match


def js_column_constant_declarations(source):
    """Return the `const <x>Column = "...";` declarations of the single fields."""
    declarations = {}
    for name in COLUMN_CONSTANTS:
        match = re.search(r'\n(\s*)const\s+%s\s*=\s*"([^"]*)"\s*;' % name, source)
        assert match, f"const {name} = \"...\"; not found in review_annotation.js"
        declarations[name] = match.group(0).strip()
    return declarations


def js_invalid_scan_source(source):
    """Return the `for (const [name, options] of annotationOptions) {...}` block.

    This is the scan `completionIssues` uses to report labels the current option
    list does not offer; it is the only place a legacy value can become an
    `invalid` entry.
    """
    match = re.search(r'for\s*\(\s*const\s*\[\s*name\s*,\s*options\s*\]\s*of\s+annotationOptions\s*\)\s*\{',
                      source)
    assert match, "completionIssues invalid scan over annotationOptions not found in review_annotation.js"
    end = _balanced(source, source.index("{", match.end() - 1), "{", "}")
    return source[match.start():end]


def annotation_option_snapshot():
    """Return {column: [option values]} from the real annotation form."""
    html = html_text()
    return {column: select_option_values(html, control_id)
            for column, control_id in SINGLE_CONTROLS.items()}


def node_probe_script():
    """Assemble one node script out of the real source fragments."""
    js = js_text()
    declarations = js_column_constant_declarations(js)
    legacy_map = "const legacyUncertainLabels = new Map([%s]);" % js_map_literal_body(
        js, "legacyUncertainLabels")
    annotation_label = js_function_source(js, "annotationLabel")
    set_control = js_function_source(js, "setControl")
    invalid_scan = js_invalid_scan_source(js)

    snapshot = annotation_option_snapshot()
    for column, values in snapshot.items():
        assert values, f"select#{SINGLE_CONTROLS[column]} has no option values in review_annotation.html"
        assert UNIFIED in values, f"select#{SINGLE_CONTROLS[column]} does not offer {UNIFIED}"

    snapshot_js = "const annotationOptions = new Map([%s]);" % ", ".join(
        '[%s, new Set(%s)]' % (json.dumps(column, ensure_ascii=False),
                               json.dumps(values, ensure_ascii=False))
        for column, values in snapshot.items())

    cases = [list(case) for case in ALL_CASES]

    return "\n".join([
        '"use strict";',
        "// Assembled from script/annotation/review_annotation.js and .html; do not edit.",
        declarations["stateColumn"],
        declarations["mechanismColumn"],
        declarations["siteColumn"],
        "",
        legacy_map,
        snapshot_js,
        "",
        annotation_label,
        "",
        set_control,
        "",
        "const document = {",
        "  createElement(tagName) {",
        '    return { tagName: tagName.toUpperCase(), dataset: {}, value: "", textContent: "", disabled: false };',
        "  },",
        "};",
        "let fields = new Map();",
        "",
        "function makeSelect(values) {",
        "  return {",
        '    tagName: "SELECT",',
        "    dataset: {},",
        "    options: values.map((value) => ({ value, dataset: {}, textContent: value, disabled: false })),",
        '    value: "",',
        "    querySelector() { return null; },",
        "    append(option) { this.options.push(option); },",
        "  };",
        "}",
        "",
        "function invalidScan(read) {",
        "  const missing = [];",
        "  const invalid = [];",
        invalid_scan,
        "  return { missing, invalid };",
        "}",
        "",
        "function probe(column, current) {",
        "  const control = makeSelect([...annotationOptions.get(column)]);",
        "  fields = new Map([[control, column]]);",
        "  const before = control.options.length;",
        "  setControl(control, current);",
        "  const appended = control.options.slice(before);",
        "  const row = new Map([[column, current]]);",
        "  for (const [name, values] of annotationOptions) {",
        '    if (name !== column) row.set(name, [...values][0] || "");',
        "  }",
        "  const read = (name) => (row.has(name) ? row.get(name) : \"\");",
        "  const scan = invalidScan(read);",
        "  return {",
        "    column,",
        "    current,",
        "    label: annotationLabel(column, current),",
        "    syntheticOptions: appended.map((option) => (",
        "      { text: option.textContent, disabled: option.disabled, value: option.value })),",
        "    selectedValue: control.value,",
        "    missing: scan.missing,",
        "    invalid: scan.invalid,",
        "  };",
        "}",
        "",
        "const cases = %s;" % json.dumps(cases, ensure_ascii=False),
        "const results = cases.map(([, column, value]) => probe(column, value));",
        "process.stdout.write(JSON.stringify(results));",
        "",
    ])


@pytest.fixture(scope="module")
def runtime_probes():
    """Run the assembled fragments once; return {(kind, column, value): probe result}."""
    if NODE is None:
        pytest.skip(NODE_MISSING_REASON)

    script = node_probe_script()
    workdir = Path(tempfile.mkdtemp(prefix="annotation-label-runtime-"))
    try:
        script_path = workdir / "probe.js"
        script_path.write_text(script, encoding="utf-8")
        completed = subprocess.run([NODE, str(script_path)], capture_output=True, text=True, timeout=120)
        assert completed.returncode == 0, (
            "node probe failed\n--- stdout ---\n%s\n--- stderr ---\n%s\n--- script ---\n%s"
            % (completed.stdout, completed.stderr, script))
        try:
            results = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - only on a broken probe
            raise AssertionError("node probe did not print JSON: %r\n%s"
                                 % (completed.stdout, completed.stderr)) from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    assert len(results) == len(ALL_CASES), (len(results), len(ALL_CASES))
    grouped = {}
    for (kind, column, value), result in zip(ALL_CASES, results):
        assert (result["column"], result["current"]) == (column, value), (kind, column, value, result)
        grouped[(kind, column, value)] = result
    return grouped


# --- (a) historical values become the unified term ---------------------------

@pytest.mark.parametrize("column,legacy", LEGACY_CASES)
def test_historical_uncertain_cell_is_labelled_with_the_unified_term(runtime_probes, column, legacy):
    result = runtime_probes[("legacy", column, legacy)]

    assert result["label"] == UNIFIED, f"{column}×{legacy!r}: label={result['label']!r}"


@pytest.mark.parametrize("column,legacy", LEGACY_CASES)
def test_historical_uncertain_cell_synthetic_option_is_disabled_and_shows_the_original(
        runtime_probes, column, legacy):
    result = runtime_probes[("legacy", column, legacy)]

    assert len(result["syntheticOptions"]) == 1, f"{column}×{legacy!r}: {result['syntheticOptions']}"
    option = result["syntheticOptions"][0]
    assert option["text"] == f"{UNIFIED}（原值：{legacy}）", f"{column}×{legacy!r}: {option}"
    assert option["disabled"] is True, f"{column}×{legacy!r}: {option}"


@pytest.mark.parametrize("column,legacy", LEGACY_CASES)
def test_historical_uncertain_cell_is_not_reported_invalid(runtime_probes, column, legacy):
    result = runtime_probes[("legacy", column, legacy)]

    assert column not in result["invalid"], f"{column}×{legacy!r}: invalid={result['invalid']}"


# --- (b) the unified term itself is a normal, selectable option --------------

@pytest.mark.parametrize("column", sorted(SINGLE_CONTROLS))
def test_unified_term_is_labelled_verbatim(runtime_probes, column):
    result = runtime_probes[("unified", column, UNIFIED)]

    assert result["label"] == UNIFIED, f"{column}: label={result['label']!r}"


@pytest.mark.parametrize("column", sorted(SINGLE_CONTROLS))
def test_unified_term_is_selectable_without_a_synthetic_option(runtime_probes, column):
    result = runtime_probes[("unified", column, UNIFIED)]

    assert result["syntheticOptions"] == [], f"{column}: {result['syntheticOptions']}"
    assert result["selectedValue"] == UNIFIED, f"{column}: selected={result['selectedValue']!r}"


@pytest.mark.parametrize("column", sorted(SINGLE_CONTROLS))
def test_unified_term_is_not_reported_invalid(runtime_probes, column):
    result = runtime_probes[("unified", column, UNIFIED)]

    assert column not in result["invalid"], f"{column}: invalid={result['invalid']}"


# --- (c) values outside the map stay verbatim and are flagged ----------------

@pytest.mark.parametrize("column,value", UNKNOWN_CASES)
def test_unregistered_value_is_labelled_verbatim(runtime_probes, column, value):
    result = runtime_probes[("unknown", column, value)]

    assert result["label"] == value, f"{column}×{value!r}: label={result['label']!r}"


@pytest.mark.parametrize("column,value", UNKNOWN_CASES)
def test_unregistered_value_shows_a_pending_review_option_and_stays_enabled(runtime_probes, column, value):
    result = runtime_probes[("unknown", column, value)]

    assert len(result["syntheticOptions"]) == 1, f"{column}×{value!r}: {result['syntheticOptions']}"
    option = result["syntheticOptions"][0]
    assert option["text"] == f"原值（待复核） · {value}", f"{column}×{value!r}: {option}"
    assert option["disabled"] is False, f"{column}×{value!r}: {option}"


@pytest.mark.parametrize("column,value", UNKNOWN_CASES)
def test_unregistered_value_is_reported_invalid(runtime_probes, column, value):
    result = runtime_probes[("unknown", column, value)]

    assert result["invalid"] == [column], f"{column}×{value!r}: invalid={result['invalid']}"
