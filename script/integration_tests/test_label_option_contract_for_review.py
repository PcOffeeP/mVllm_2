"""Static consumer contract: the human review workbench must speak the scorer label set.

The review workbench (``script/subvideo_review``) validates the same three
single-value fracture fields that the scorer scores, so a workbench still
offering the superseded term 「无法确定」 silently writes records the scorer does
not recognise.  This module parses the workbench sources as text and compares
them with ``script.five_label_eval/score.py``'s ``SINGLES``: no server, no
browser, no node, no writes.

Failure conditions (re-check this module when any of them changes):

- ``script/subvideo_review/server.py`` stops declaring a module-level
  ``OPTIONS = {...}`` literal, or moves the three single-value field lists out
  of a plain literal (e.g. builds them from variables).
- ``script/five_label_eval/score.py`` renames or reshapes ``SINGLES``.
- ``script/subvideo_review/static/index.html`` renames the selects
  ``fracture-status`` / ``fracture-mode`` / ``fracture-location``, or stops
  writing their options as plain ``<option value="...">text</option>`` pairs
  (self-closing or attribute-free options break the static parse).
- The HTML assertions are order-sensitive: reordering the options of a single
  select, or rewording the visible label of an option so it no longer equals its
  ``value``, is now a failure rather than allowed drift.

The optional environment variable ``SUBVIDEO_REVIEW_SERVER_PATH`` overrides the
inspected ``server.py`` path and ``SUBVIDEO_REVIEW_HTML_PATH`` overrides the
inspected ``index.html`` path.  Both exist only so a mutation test can prove this
guard really is red on a mutated copy of the file; normal runs must not set them.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

from script.five_label_eval.score import SINGLES


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = PROJECT_ROOT / "script/subvideo_review/server.py"
HTML_PATH = PROJECT_ROOT / "script/subvideo_review/static/index.html"

# select id in index.html -> field name in score.SINGLES
SINGLE_SELECT_IDS = {"fracture-status": "断裂状态",
                     "fracture-mode": "断裂模式",
                     "fracture-location": "断裂位置"}

SERVER_PATH_ENV = "SUBVIDEO_REVIEW_SERVER_PATH"
HTML_PATH_ENV = "SUBVIDEO_REVIEW_HTML_PATH"
UNIFIED = "无法判断"

# One ``<option ...>visible text</option>`` pair inside a select.
OPTION_RE = re.compile(r"<option\b([^>]*)>(.*?)</option>", re.S)
VALUE_ATTR_RE = re.compile(r'\bvalue="([^"]*)"')


def server_source_path():
    """Return the server.py to inspect; the env override is for mutation tests only."""
    override = os.environ.get(SERVER_PATH_ENV)
    return Path(override) if override else SERVER_PATH


def html_source_path():
    """Return the index.html to inspect; the env override is for mutation tests only."""
    override = os.environ.get(HTML_PATH_ENV)
    return Path(override) if override else HTML_PATH


def server_single_options(path=None):
    """Return ``{field: [values]}`` of the module-level OPTIONS literal in server.py.

    Only the three single-value fields are read; the two per-item groups are
    dict comprehensions and are intentionally left to the server's own tests.
    """
    path = server_source_path() if path is None else path
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    assignments = [node for node in tree.body
                   if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                   and any(isinstance(target, ast.Name) and target.id == "OPTIONS"
                           for target in node.targets)]
    assert len(assignments) == 1, \
        f"{path} 应只声明一处模块级 OPTIONS 字典字面量，实际找到 {len(assignments)} 处"
    options = {}
    for key_node, value_node in zip(assignments[0].value.keys, assignments[0].value.values):
        field = ast.literal_eval(key_node)
        if field not in SINGLES:
            continue
        try:
            options[field] = ast.literal_eval(value_node)
        except ValueError as exc:  # not a plain literal (e.g. list(SINGLES[...]))
            raise AssertionError(
                f"server.py 的 OPTIONS[{field}] 必须是可直接静态读取的字面量列表"
                f"（如 [\"未断裂\", ...]），否则本静态守卫无法核对它与评分器的一致性：{exc}") from exc
    return options


def select_block(html, select_id):
    """Return the ``<select id="...">...</select>`` fragment owning that control."""
    match = re.search(r'<select\b[^>]*\bid="%s"[^>]*>(.*?)</select>' % re.escape(select_id),
                      html, re.S)
    assert match, f"index.html 中找不到 select#{select_id}，审核页单字段控件的 id 已变化"
    return match.group(1)


def select_options(html, select_id):
    """Return ``[(value, visible text), ...]`` of one select, in document order.

    The leading ``value=""`` placeholder (「未选择」) is skipped: it is not a
    label the page can save.
    """
    block = select_block(html, select_id)
    parsed = [(attrs, re.sub(r"<[^>]+>", "", body).strip())
              for attrs, body in OPTION_RE.findall(block)]
    opened = len(re.findall(r"<option\b", block))
    assert len(parsed) == opened, (
        f"select#{select_id} 有 {opened} 处 <option>，但只有 {len(parsed)} 处是可静态解析的"
        f" <option ...>文本</option> 写法；本守卫无法核对它们的文本与 value 是否一致")
    options = []
    for attrs, text in parsed:
        value = VALUE_ATTR_RE.search(attrs)
        assert value, (
            f"select#{select_id} 的 <option {attrs.strip()}> 缺少 value=\"...\" 属性，"
            f"本守卫无法把它与评分器标签集对齐")
        if value.group(1):
            options.append((value.group(1), text))
    return options


def select_option_values(html, select_id):
    """Return the non-empty option values of one select, in document order."""
    return [value for value, _ in select_options(html, select_id)]


def first_difference(actual, expected):
    """Describe the first positional difference so a reordering is readable."""
    for index, (got, want) in enumerate(zip(actual, expected)):
        if got != want:
            return f"第 {index + 1} 项为 {got!r}，期望 {want!r}"
    if len(actual) != len(expected):
        return f"共 {len(actual)} 项，期望 {len(expected)} 项"
    return "无差异"


@pytest.mark.parametrize("field", list(SINGLES))
def test_review_server_offers_the_scorer_label_set_in_the_same_order(field):
    options = server_single_options()

    assert field in options, f"server.py 的 OPTIONS 缺少单值字段「{field}」"
    assert options[field] == list(SINGLES[field]), (
        f"审核工作台的 OPTIONS[{field}] 必须与评分器 SINGLES[{field}] 完全一致（含顺序）："
        f"当前为 {options[field]!r}，期望 {list(SINGLES[field])!r}；"
        f"工作台若仍写「无法确定」，评分器不认这些记录。"
    )


@pytest.mark.parametrize("select_id,field", sorted(SINGLE_SELECT_IDS.items()))
def test_review_page_single_select_offers_exactly_the_scorer_label_set(select_id, field):
    expected = list(SINGLES[field])
    options = select_option_values(html_source_path().read_text(encoding="utf-8"), select_id)

    assert options == expected, (
        f"index.html 的 select#{select_id} 可选值必须与评分器 SINGLES[{field}] 完全一致（含顺序）："
        f"{first_difference(options, expected)}；实际 {options!r}，期望 {expected!r}；"
        f"顺序错位或仍提供「无法确定」都会让页面写出评分器不认的标签。"
    )
    assert UNIFIED in options, f"select#{select_id} 必须提供统一术语「{UNIFIED}」"


@pytest.mark.parametrize("select_id,field", sorted(SINGLE_SELECT_IDS.items()))
def test_review_page_single_select_option_text_matches_its_value(select_id, field):
    options = select_options(html_source_path().read_text(encoding="utf-8"), select_id)

    mismatched = [(value, text) for value, text in options if value != text]
    assert not mismatched, (
        f"index.html 的 select#{select_id}（{field}）每个 option 的显示文本必须与它的 value 相同，"
        f"以下项不一致（value, 文本）：{mismatched!r}；用户看到的词与保存的值不同时，"
        f"审核页会静默写下与界面文字不符的标签。"
    )
