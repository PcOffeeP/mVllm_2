"""Static consumer contract for the single unified "无法判断" uncertainty term.

Every consumer of the three single-value fracture fields (annotation UI, the
pure form spec, the split generator and the scorer) must agree on the same
label set.  This module parses the browser sources as text and reads the real
annotation CSV read-only: no browser, no network, no writes into the project.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from script.data_split import generate as splitter
from script.five_label_eval import score as scorer
from script.roi import label_fields as fields


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = PROJECT_ROOT / "script/annotation/review_annotation.html"
JS_PATH = PROJECT_ROOT / "script/annotation/review_annotation.js"
ANNOTATION_CSV = PROJECT_ROOT / "data/annotation-table-full.csv"

# The three `<select>` controls of the annotation tool that write single labels.
SINGLE_CONTROLS = {"断裂状态": "state", "断裂模式": "mechanism", "断裂位置": "site"}
UNIFIED = "无法判断"
SUPERSEDED = "无法确定"


def html_text():
    return HTML_PATH.read_text(encoding="utf-8")


def js_text():
    return JS_PATH.read_text(encoding="utf-8")


def select_block(html, control_id):
    """Return the `<select id="...">...</select>` fragment owning that control."""
    match = re.search(r'<select\b[^>]*\bid="%s"[^>]*>(.*?)</select>' % re.escape(control_id),
                      html, re.S)
    assert match, f"select#{control_id} not found in review form"
    return match.group(1)


def select_option_values(html, control_id):
    """Return the non-empty option values of one select, in document order."""
    return [value for value in re.findall(r'<option\b[^>]*\bvalue="([^"]*)"', select_block(html, control_id))
            if value]


def js_string_constants(source):
    """Map JS `const <name> = "<literal>";` identifiers to their string values."""
    return dict(re.findall(r'const\s+([A-Za-z_$][\w$]*)\s*=\s*"([^"]*)"\s*;', source))


# One `[<columnConstant>, <value>]` entry; the value is a string literal or an
# array of string literals, the two shapes the annotation tool may use.
LEGACY_MAP_ENTRY_RE = re.compile(
    r'\[\s*([A-Za-z_$][\w$]*)\s*,\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|\[[^\[\]]*\])\s*\]')


def _skip_js_string(source, index):
    """Return the index just past the JS string literal starting at `index`."""
    quote = source[index]
    index += 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    raise AssertionError(f"unterminated JS string literal in legacyUncertainLabels: {source[index:]!r}")


def js_map_literal_body(source, name):
    """Return the text between the outer brackets of `<name> = new Map([...])`.

    Bracket depth is scanned so that nested value arrays are returned intact;
    a missing literal or an unterminated one fails loudly.
    """
    opener = re.search(r'\b%s\s*=\s*new\s+Map\(\s*\[' % re.escape(name), source)
    assert opener, f"{name} = new Map([...]) literal not found in review_annotation.js"
    index = start = opener.end()
    depth = 1
    while index < len(source):
        char = source[index]
        if char in '"\'`':
            index = _skip_js_string(source, index)
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                assert re.match(r'\s*\)', source[index + 1:]), \
                    f"{name} Map literal is not closed by `])` in review_annotation.js"
                return source[start:index]
        index += 1
    raise AssertionError(f"unterminated {name} Map literal in review_annotation.js")


def legacy_entry_values(raw_value):
    """Return the legacy label(s) of one map entry, keeping the written order."""
    if raw_value.startswith("["):
        values = tuple(first or second for first, second in
                       re.findall(r'"([^"\\]*)"|\'([^\'\\]*)\'', raw_value))
        assert values, f"no string literals inside legacyUncertainLabels value array: {raw_value}"
        return values
    assert raw_value[0] in '"\'', f"unsupported legacyUncertainLabels value: {raw_value}"
    return (raw_value[1:-1],)


def js_legacy_uncertain_map(source):
    """Parse `legacyUncertainLabels` into {column name: tuple of legacy values}.

    Each entry may hold a single string literal or an array of string literals,
    e.g. `new Map([[mechanismColumn, ["无法确定", "无法识别"]], ...])`.  The
    literal is written with column constants, so the constants are resolved
    through their top-level declarations.  An unresolved identifier, an
    unsupported value shape or a leftover fragment fails loudly instead of
    silently producing an empty or partial mapping.
    """
    body = js_map_literal_body(source, "legacyUncertainLabels")
    constants = js_string_constants(source)
    leftover = re.sub(r"[\s,]", "", LEGACY_MAP_ENTRY_RE.sub("", body))
    assert not leftover, f"unparsed fragment in legacyUncertainLabels literal: {leftover!r}"
    mapping = {}
    for key, raw_value in LEGACY_MAP_ENTRY_RE.findall(body):
        assert key in constants, f"unresolved column constant in legacyUncertainLabels: {key}"
        mapping[constants[key]] = legacy_entry_values(raw_value)
    assert mapping, f"legacyUncertainLabels entries could not be parsed: {body!r}"
    return mapping


def js_function_body(source, name):
    match = re.search(r'function\s+%s\s*\([^)]*\)\s*\{(.*?)\n  \}' % re.escape(name), source, re.S)
    assert match, f"function {name} not found in review_annotation.js"
    return match.group(1)


def js_legacy_pairs(source=None):
    """Return the {(column, legacy value)} pairs the annotation tool accepts."""
    mapping = js_legacy_uncertain_map(js_text() if source is None else source)
    return {(column, legacy) for column, values in mapping.items() for legacy in values}


def annotation_rows():
    with ANNOTATION_CSV.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize("column", sorted(SINGLE_CONTROLS))
def test_review_form_single_select_offers_exactly_the_scorer_label_set(column):
    options = select_option_values(html_text(), SINGLE_CONTROLS[column])

    assert set(options) == set(scorer.SINGLES[column])


@pytest.mark.parametrize("column", sorted(SINGLE_CONTROLS))
def test_review_form_single_select_does_not_offer_the_superseded_term(column):
    block = select_block(html_text(), SINGLE_CONTROLS[column])

    assert f'value="{SUPERSEDED}"' not in block


@pytest.mark.parametrize("column", sorted(scorer.SINGLES))
def test_review_form_spec_options_equal_the_scorer_label_set(column):
    spec = fields.FIELDS_BY_COLUMN[column]
    options = [value for value in spec.options if value]

    # HTML == label_fields == score: both consumers anchor on the scorer set.
    assert set(options) == set(scorer.SINGLES[column])


def test_annotation_tool_still_recognizes_historical_uncertain_values():
    mapping = js_legacy_uncertain_map(js_text())

    assert SUPERSEDED in mapping.get("断裂状态", ()), mapping
    assert SUPERSEDED in mapping.get("断裂位置", ()), mapping
    assert "无法识别" in mapping.get("断裂模式", ()), mapping


# A synthetic literal in the shape the fix is expected to use: one column may
# carry several legacy values, written as an array next to the column constant.
MULTI_VALUE_LEGACY_SOURCE = '''
  const stateColumn = "断裂状态";
  const mechanismColumn = "断裂模式";
  const legacyUncertainLabels = new Map([[stateColumn, "无法确定"],
    [mechanismColumn, ["无法确定", "无法识别"]]]);
'''


def test_legacy_map_parser_reads_multi_value_entry_when_a_column_has_several_legacy_values():
    mapping = js_legacy_uncertain_map(MULTI_VALUE_LEGACY_SOURCE)

    assert mapping == {"断裂状态": (SUPERSEDED,), "断裂模式": (SUPERSEDED, "无法识别")}
    assert js_legacy_pairs(MULTI_VALUE_LEGACY_SOURCE) == {
        ("断裂状态", SUPERSEDED), ("断裂模式", SUPERSEDED), ("断裂模式", "无法识别")}


def test_legacy_map_parser_fails_loudly_when_an_entry_value_shape_is_unsupported():
    unsupported = '''
  const mechanismColumn = "断裂模式";
  const legacyUncertainLabels = new Map([[mechanismColumn, new Set(["无法确定"])]]);
'''

    with pytest.raises(AssertionError, match="unparsed fragment in legacyUncertainLabels literal"):
        js_legacy_uncertain_map(unsupported)


def test_annotation_tool_legacy_values_are_exactly_the_split_alias_pairs():
    accepted = js_legacy_pairs()
    aliases = set(splitter.ALIASES)

    assert len(aliases) == 4, aliases
    # Both directions: a pair missing from the tool or an extra pair both fail.
    assert accepted == aliases, (sorted(aliases - accepted), sorted(accepted - aliases))


def test_label_fields_legacy_display_is_exactly_the_split_alias_pairs():
    aliases = set(splitter.ALIASES)

    assert len(aliases) == 4, aliases
    assert set(fields._LEGACY_DISPLAY) == aliases, \
        (sorted(aliases - set(fields._LEGACY_DISPLAY)), sorted(set(fields._LEGACY_DISPLAY) - aliases))


def test_annotation_tool_displays_historical_values_with_the_unified_term():
    body = js_function_body(js_text(), "annotationLabel")

    assert UNIFIED in body, body
    assert SUPERSEDED not in body, body


@pytest.mark.parametrize("column,legacy", [
    ("断裂状态", SUPERSEDED), ("断裂位置", SUPERSEDED),
    ("断裂模式", SUPERSEDED), ("断裂模式", "无法识别"),
])
def test_legacy_cell_is_displayed_as_unified_term_and_keeps_its_original_value(column, legacy):
    spec = fields.FIELDS_BY_COLUMN[column]

    label = fields.option_label(spec, legacy)

    assert label.startswith(UNIFIED), label
    assert legacy in label, label


@pytest.mark.parametrize("column", sorted(scorer.SINGLES))
def test_current_unified_value_is_stored_and_displayed_verbatim(column):
    spec = fields.FIELDS_BY_COLUMN[column]

    assert fields.option_label(spec, UNIFIED) == UNIFIED


@pytest.mark.parametrize("column", sorted(scorer.SINGLES))
def test_split_fields_accept_only_the_unified_uncertain_value(column):
    allowed = splitter.FIELDS[column]

    assert UNIFIED in allowed, allowed
    assert SUPERSEDED not in allowed, allowed


@pytest.mark.parametrize("column,legacy", [
    ("断裂状态", SUPERSEDED), ("断裂模式", SUPERSEDED),
    ("断裂位置", SUPERSEDED), ("断裂模式", "无法识别"),
])
def test_split_aliases_map_every_historical_value_to_the_unified_term(column, legacy):
    assert splitter.ALIASES.get((column, legacy)) == UNIFIED


def test_split_alias_covers_mechanism_and_site_not_only_state():
    aliased_columns = {column for column, _ in splitter.ALIASES}

    assert {"断裂状态", "断裂模式", "断裂位置"} <= aliased_columns, splitter.ALIASES


def test_real_annotation_table_normalizes_without_a_single_illegal_label():
    rows = annotation_rows()

    assert len(rows) == 110
    illegal = []
    normalized = []
    for row in rows:
        try:
            normalized.append(splitter.normalize_row(row))
        except splitter.SplitError as exc:
            illegal.append(f"{row.get('id')}: {exc}")
    assert illegal == []
    splitter.validate_labels(rows)
    for column in scorer.SINGLES:
        observed = {row[column] for row in normalized}
        assert observed <= set(scorer.SINGLES[column]), (column, sorted(observed))
