#!/usr/bin/env python3
"""校验 docs/design-facts.yaml，并由它渲染 docs/design-facts.md。

用法：
    python scripts/verify_design_facts.py            # 逐项打印 PASS/FAIL，任一失败退出 1
    python scripts/verify_design_facts.py --render   # 由 yaml 重新生成 docs/design-facts.md，退出 0
    python scripts/verify_design_facts.py --help     # 打印本说明，退出 0

未知参数（如拼错的 --rendr）打印用法并退出 2，绝不静默回落到校验模式。

实现约束：
- 只用标准库，不 import 任何项目模块。
- 冻结阈值一律用 `ast` 解析 `finetune/holdout_metrics.py` 的 `THRESHOLDS` 字面量，不 import 该模块。
- 阈值校验是双向的：源码 THRESHOLDS 的项数、键集合与 claim 抽出的键集合必须一致，再逐项比值。
- evidence 只接受仓库内相对路径（绝对路径与越出仓库根的引用一律 FAIL），防止事实锚定到仓库外。
- 仓库根按脚本自身位置推断（`Path(__file__).resolve().parents[1]`），不依赖 cwd，便于在隔离的假仓库中运行。
- yaml 只用标准库解析其子集（映射、序列、块标量 `|`/`>`、行内序列 `[a, b]`、整行注释）；
  超出子集时明确报错，不静默误解析。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "docs" / "design-facts.yaml"
MD_PATH = ROOT / "docs" / "design-facts.md"
THRESHOLDS_PATH = ROOT / "finetune" / "holdout_metrics.py"

HEADER = (
    "<!-- generated from docs/design-facts.yaml by "
    "scripts/verify_design_facts.py --render，请勿手改 -->"
)

ALLOWED_STATES = ("active", "obsolete", "superseded")
ALLOWED_AFFECTS = ("prompt", "contract", "code", "data", "eval", "metrics", "gate", "ops")
FACT_ID_RE = re.compile(r"^DF-\d{3}$")
EVIDENCE_RE = re.compile(r"^(?P<path>.+):(?P<line>\d+)$")
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
THRESHOLD_FACT_ID = "DF-004"
EXPECTED_THRESHOLD_COUNT = 7
# claim 里的阈值写成 `<键名> <数值>`（多项以中文分号连接）。
# 键名先按「无空白的键名候选 + 数值」抓取，再要求候选里至少含一个 ASCII 字母或下划线：
# 纯中文词（如「共 7 项」「阈值 7 项」）是叙述文字，不计作阈值键名。
THRESHOLD_PAIR_RE = re.compile(
    r"(?P<key>[A-Za-z0-9_\u4e00-\u9fff]+)\s*[:：]?\s*(?P<number>" + NUMBER + r")"
)
THRESHOLD_KEY_LIKE_RE = re.compile(r"[A-Za-z_]")
USAGE = "用法：python scripts/verify_design_facts.py [--render | --help]"
RENDER_HINT = "请重新运行 `python scripts/verify_design_facts.py --render`（该文件是生成产物，禁止手改）"


# --------------------------------------------------------------------------- #
# yaml 子集解析（只用标准库）
# --------------------------------------------------------------------------- #
class YamlError(Exception):
    """yaml 子集解析失败。"""


def _split_key(content: str) -> tuple[str, bool, str]:
    """把一行 `键: 值` 拆成 (键, 是否有分隔符, 值文本)。"""
    match = re.match(r"^(?P<key>[^:#]+?)\s*:(?:\s+(?P<value>.*))?$", content)
    if not match:
        return "", False, ""
    return match.group("key").strip(), True, (match.group("value") or "")


def _scalar(text: str):
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    if value in ("", "null", "Null", "NULL", "~"):
        return None
    if value in ("true", "True"):
        return True
    if value in ("false", "False"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


class _YamlSubsetParser:
    """按缩进解析本项目 yaml 用到的 YAML 子集；超出子集即报错。"""

    def __init__(self, text: str, label: str):
        self.lines = text.splitlines()
        self.label = label
        self.index = 0

    def _error(self, lineno: int, message: str) -> YamlError:
        return YamlError(f"{self.label} 第 {lineno} 行：{message}")

    def _peek(self):
        """返回下一个有效行的 (行号, 缩进, 去缩进内容)；跳过空行与整行注释。"""
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                self.index += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if raw[:indent].count("\t"):
                raise self._error(self.index + 1, "使用制表符缩进，超出本脚本支持的 yaml 子集")
            return self.index + 1, indent, raw[indent:]
        return None

    def parse_document(self):
        head = self._peek()
        if head is None:
            raise YamlError(f"{self.label} 为空，无法解析")
        value = self.parse_block(head[1])
        rest = self._peek()
        if rest is not None:
            raise self._error(rest[0], "缩进无法归入任何已解析块")
        return value

    def parse_block(self, indent: int):
        lineno, actual, content = self._peek()
        if actual != indent:
            raise self._error(lineno, f"缩进异常：期望 {indent}，实际 {actual}")
        if content == "-" or content.startswith("- "):
            return self.parse_sequence(indent)
        return self.parse_mapping(indent)

    def parse_sequence(self, indent: int) -> list:
        items: list = []
        while True:
            head = self._peek()
            if head is None:
                break
            lineno, actual, content = head
            if actual < indent:
                break
            if actual > indent:
                raise self._error(lineno, f"缩进异常：序列项应为 {indent}，实际 {actual}")
            if not (content == "-" or content.startswith("- ")):
                break
            self.index += 1
            rest = content[1:].lstrip()
            if not rest:
                nxt = self._peek()
                if nxt is None or nxt[1] <= indent:
                    items.append(None)
                else:
                    items.append(self.parse_block(nxt[1]))
                continue
            child_indent = indent + (len(content) - len(rest))
            key, has_sep, value_text = _split_key(rest)
            if has_sep:
                first = {key: self.parse_value(value_text.strip(), child_indent, lineno)}
                items.append(self.parse_mapping(child_indent, first))
            else:
                items.append(self.parse_value(rest, indent, lineno))
        return items

    def parse_mapping(self, indent: int, result: dict | None = None) -> dict:
        mapping: dict = {} if result is None else result
        while True:
            head = self._peek()
            if head is None:
                break
            lineno, actual, content = head
            if actual < indent:
                break
            if actual > indent:
                raise self._error(lineno, f"缩进异常：映射键应为 {indent}，实际 {actual}")
            if content == "-" or content.startswith("- "):
                break
            key, has_sep, value_text = _split_key(content)
            if not has_sep:
                raise self._error(lineno, f"无法解析为 `键: 值`：{content!r}")
            if key in mapping:
                raise self._error(lineno, f"键 {key} 重复")
            self.index += 1
            mapping[key] = self.parse_value(value_text.strip(), indent, lineno)
        return mapping

    def parse_value(self, text: str, parent_indent: int, lineno: int):
        if text in ("|", "|-", "|+", ">", ">-", ">+"):
            return self.parse_block_scalar(text[0], parent_indent)
        if text.startswith("["):
            if not text.endswith("]"):
                raise self._error(lineno, f"行内序列未用 ] 闭合：{text!r}")
            inner = text[1:-1].strip()
            if not inner:
                return []
            return [_scalar(part) for part in inner.split(",")]
        if text.startswith("{"):
            raise self._error(lineno, "不支持行内映射 {}，请改用块格式")
        if text == "":
            nxt = self._peek()
            if nxt is None or nxt[1] <= parent_indent:
                return None
            return self.parse_block(nxt[1])
        if text.startswith(("&", "*", "!")):
            raise self._error(lineno, f"不支持 yaml 锚点/标签：{text!r}")
        return _scalar(text)

    def parse_block_scalar(self, style: str, parent_indent: int) -> str:
        collected: list[str] = []
        base_indent = None
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            if not raw.strip():
                collected.append("")
                self.index += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= parent_indent:
                break
            if base_indent is None:
                base_indent = indent
            if indent < base_indent:
                break
            collected.append(raw[base_indent:])
            self.index += 1
        while collected and not collected[-1].strip():
            collected.pop()
        if style == ">":
            return " ".join(part.strip() for part in collected if part.strip())
        return "\n".join(collected)


def _rel(path: Path) -> str:
    """把路径显示成仓库相对路径（便于 PASS/FAIL 文案与真实文件一致）。"""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def load_yaml(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise YamlError(f"文件不存在：{_rel(path)}") from None
    except UnicodeDecodeError as exc:
        raise YamlError(f"文件不是 UTF-8：{_rel(path)}（{exc}）") from None
    except OSError as exc:
        raise YamlError(f"文件不可读：{_rel(path)}（{exc}）") from None
    return _YamlSubsetParser(text, _rel(path)).parse_document()


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _text(value) -> str:
    """折叠为单行文本（渲染与文案统一用它）。"""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _facts_of(data) -> list:
    if not isinstance(data, dict):
        return []
    return [fact for fact in _as_list(data.get("facts")) if isinstance(fact, dict)]


# --------------------------------------------------------------------------- #
# 校验项
# --------------------------------------------------------------------------- #
def check_structure(facts_raw) -> list[str]:
    problems: list[str] = []
    seen: dict[str, int] = {}
    for index, fact in enumerate(_as_list(facts_raw), start=1):
        if not isinstance(fact, dict):
            problems.append(f"facts[{index}] 不是映射，无法校验")
            continue
        fact_id = fact.get("id")
        label = fact_id if isinstance(fact_id, str) and fact_id else f"facts[{index}]"
        if not isinstance(fact_id, str) or not FACT_ID_RE.match(fact_id):
            problems.append(f"{label} 的 id {fact_id!r} 不匹配 ^DF-\\d{{3}}$")
        elif fact_id in seen:
            problems.append(f"id 重复：{fact_id}（facts[{seen[fact_id]}] 与 facts[{index}]）")
        else:
            seen[fact_id] = index
        state = fact.get("state")
        if state not in ALLOWED_STATES:
            problems.append(f"{label} 的 state {state!r} 不在 {'/'.join(ALLOWED_STATES)} 内")
        affects = _as_list(fact.get("affects"))
        if not affects:
            problems.append(f"{label} 缺少 affects")
        for value in affects:
            if value not in ALLOWED_AFFECTS:
                problems.append(f"{label} 的 affects 含未知取值 {value!r}")
        if not _text(fact.get("topic")):
            problems.append(f"{label} 缺少 topic")
        if not _text(fact.get("claim")):
            problems.append(f"{label} 缺少 claim")
    return problems


def check_residue(facts_raw) -> list[str]:
    problems: list[str] = []
    for fact in _facts_of({"facts": facts_raw}):
        if fact.get("state") != "obsolete":
            continue
        label = _text(fact.get("id")) or "<无 id>"
        if not _text(fact.get("residue")):
            problems.append(f"{label} 的 state=obsolete 但没有非空 residue（墓碑必须留下处置说明）")
    return problems


def _check_evidence_refs(label: str, refs, root: Path) -> list[str]:
    """校验一组 `path:LINE` 引用：仓库内相对路径、文件存在、行号在 1..总行数、该行非空。"""
    problems: list[str] = []
    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root
    for ref in refs:
        reference = "" if ref is None else str(ref).strip()
        match = EVIDENCE_RE.match(reference)
        if not match:
            problems.append(f"{label} 的 evidence {reference!r} 不符合 path:LINE 形式")
            continue
        relative = match.group("path")
        line_no = int(match.group("line"))
        if Path(relative).is_absolute():
            problems.append(f"{label} 的 evidence 必须是仓库内相对路径，实际是绝对路径：{reference}")
            continue
        target = root / relative
        try:
            resolved = target.resolve()
        except OSError as exc:
            problems.append(f"{label} 的 evidence 无法解析路径：{reference}（{exc}）")
            continue
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            problems.append(f"{label} 的 evidence 越出仓库根：{reference}")
            continue
        if not target.is_file():
            problems.append(f"{label} 的 evidence 文件不存在：{relative}（引用 {reference}）")
            continue
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{label} 的 evidence 无法读取：{relative}（{exc}）")
            continue
        if line_no < 1 or line_no > len(lines):
            problems.append(
                f"{label} 的 evidence 行号越界：{reference}（{relative} 共 {len(lines)} 行）"
            )
            continue
        if not lines[line_no - 1].strip():
            problems.append(f"{label} 的 evidence 指向空行：{reference}")
    return problems


def check_evidence(facts_raw, misreadings, root: Path) -> list[str]:
    """facts 与 misreadings 的 evidence 用同一套规则校验；misreadings 另要求 wrong/correct 非空。"""
    problems: list[str] = []
    for fact in _facts_of({"facts": facts_raw}):
        label = _text(fact.get("id")) or "<无 id>"
        refs = _as_list(fact.get("evidence"))
        if not refs:
            problems.append(f"{label} 缺少 evidence")
            continue
        problems.extend(_check_evidence_refs(label, refs, root))
    for index, item in enumerate(_as_list(misreadings), start=1):
        label = f"misreadings[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{label} 不是映射，无法校验")
            continue
        if not _text(item.get("wrong")):
            problems.append(f"{label} 缺少非空 wrong")
        if not _text(item.get("correct")):
            problems.append(f"{label} 缺少非空 correct")
        # evidence 对误读条目是可选补充锚点，有则必须同规则合法。
        refs = _as_list(item.get("evidence"))
        if refs:
            problems.extend(_check_evidence_refs(label, refs, root))
    return problems


def read_thresholds(path: Path) -> tuple[dict | None, str | None]:
    """用 ast 解析源码中的 THRESHOLDS 字面量（不 import 模块）。"""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"无法读取 {_rel(path)}：{exc}"
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return None, f"{_rel(path)} 无法被 ast 解析：{exc}"
    found = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value_node = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value_node = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "THRESHOLDS" for t in targets):
            continue
        try:
            found = ast.literal_eval(value_node)
        except (ValueError, TypeError, SyntaxError) as exc:
            return None, f"{_rel(path)} 的 THRESHOLDS 不是可解析的字面量：{exc}"
        break
    if not isinstance(found, dict):
        return None, f"未在 {_rel(path)} 中找到 THRESHOLDS 字典字面量"
    return found, None


def extract_threshold_pairs(claim: str) -> dict[str, list[float]]:
    """抽取 claim 里所有 `<键名> <数值>` 对，键名 → 出现过的取值列表（保留重复出现）。"""
    pairs: dict[str, list[float]] = {}
    for match in THRESHOLD_PAIR_RE.finditer(claim):
        key = match.group("key")
        if not THRESHOLD_KEY_LIKE_RE.search(key):
            continue
        pairs.setdefault(key, []).append(float(match.group("number")))
    return pairs


def _fmt_keys(keys) -> str:
    listed = list(keys)
    return "、".join(listed) if listed else "（无）"


def check_thresholds(facts_raw) -> list[str]:
    facts = _facts_of({"facts": facts_raw})
    fact = next((item for item in facts if _text(item.get("id")) == THRESHOLD_FACT_ID), None)
    if fact is None:
        return [f"缺少 {THRESHOLD_FACT_ID} 事实，无法核对冻结阈值"]
    claim = _text(fact.get("claim"))
    if not claim:
        return [f"{THRESHOLD_FACT_ID} 的 claim 为空，无法抽取阈值"]
    thresholds, error = read_thresholds(THRESHOLDS_PATH)
    if error is not None:
        return [error]
    source_keys = list(thresholds)
    problems: list[str] = []

    # 1. 源码侧项数必须恰好是七道门（防止删项后 claim 仍写旧值也能 PASS）。
    if len(source_keys) != EXPECTED_THRESHOLD_COUNT:
        problems.append(
            f"{_rel(THRESHOLDS_PATH)} 的 THRESHOLDS 应为 {EXPECTED_THRESHOLD_COUNT} 项，"
            f"实际 {len(source_keys)} 项，键集：{_fmt_keys(source_keys)}"
        )

    # 2. claim 抽出的键集必须与源码键集相等：缺键、多键都 FAIL 并点名。
    pairs = extract_threshold_pairs(claim)
    claim_keys = list(pairs)
    missing = [key for key in source_keys if key not in pairs]
    extra = [key for key in claim_keys if key not in thresholds]
    if missing or extra:
        problems.append(
            f"{THRESHOLD_FACT_ID} 的 claim 阈值键集与 {_rel(THRESHOLDS_PATH)} 的 THRESHOLDS 键集不相等："
            f"缺 {_fmt_keys(missing)}，多 {_fmt_keys(extra)}（源码键集：{_fmt_keys(source_keys)}）"
        )

    # 3. 键集合相等后逐项比数值；同键多值视为无法确定单一证据。
    for key in source_keys:
        values = pairs.get(key, [])
        if not values:
            continue
        distinct = sorted(set(values))
        if len(distinct) > 1:
            problems.append(f"{THRESHOLD_FACT_ID} 的 claim 中阈值 {key} 出现多个取值 {distinct}，无法确定单一证据")
            continue
        if distinct[0] != float(thresholds[key]):
            problems.append(
                f"{THRESHOLD_FACT_ID} 的 claim 中 {key}={distinct[0]!r} 与 "
                f"{_rel(THRESHOLDS_PATH)} 的 THRESHOLDS {thresholds[key]!r} 不一致"
            )
    return problems


def check_markdown(data) -> list[str]:
    expected = render_markdown(data).encode("utf-8")
    if not MD_PATH.is_file():
        return [f"docs/design-facts.md 不存在，{RENDER_HINT}"]
    if MD_PATH.read_bytes() != expected:
        return [f"docs/design-facts.md 与 --render 结果不一致（被手改或未重新生成），{RENDER_HINT}"]
    return []


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def _render_fact(fact: dict) -> list[str]:
    lines = [f"### {_text(fact.get('id'))} [{_text(fact.get('state'))}] {_text(fact.get('topic'))}"]
    lines.append(_text(fact.get("claim")))
    lines.append("出处：")
    for ref in _as_list(fact.get("evidence")):
        lines.append(f"- {'' if ref is None else str(ref).strip()}")
    lines.append("")
    return lines


def render_markdown(data) -> str:
    facts = _facts_of(data)
    misreadings = [item for item in _as_list(data.get("misreadings") if isinstance(data, dict) else None)
                   if isinstance(item, dict)]

    lines: list[str] = [HEADER, ""]

    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for fact in facts:
        if _text(fact.get("state")) == "obsolete":
            continue
        topic = _text(fact.get("topic"))
        if topic not in groups:
            groups[topic] = []
            order.append(topic)
        groups[topic].append(fact)
    for topic in order:
        lines.append(f"## {topic}")
        lines.append("")
        for fact in groups[topic]:
            lines.extend(_render_fact(fact))

    lines.append("## 已废弃（墓碑）")
    lines.append("")
    obsolete = [fact for fact in facts if _text(fact.get("state")) == "obsolete"]
    if obsolete:
        for fact in obsolete:
            lines.extend(_render_fact(fact))
            residue = _text(fact.get("residue"))
            if residue:
                lines.append(f"墓碑：{residue}")
                lines.append("")
    else:
        lines.append("（当前没有已废弃条目。）")
        lines.append("")

    lines.append("## 常见误读")
    lines.append("")
    if misreadings:
        for item in misreadings:
            lines.append(f"- **误读**：{_text(item.get('wrong'))}")
            lines.append(f"  - 正确：{_text(item.get('correct'))}")
            for ref in _as_list(item.get("evidence")):
                lines.append(f"  - 出处：{'' if ref is None else str(ref).strip()}")
    else:
        lines.append("（当前没有登记常见误读。）")

    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- #
# 模式
# --------------------------------------------------------------------------- #
def _collect(results: list[tuple[bool, str]], label: str, problems: list[str]) -> None:
    if problems:
        results.extend((False, f"{label}：{problem}") for problem in problems)
    else:
        results.append((True, label))


def run_checks() -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    try:
        data = load_yaml(YAML_PATH)
    except YamlError as exc:
        return [(False, f"无法解析 docs/design-facts.yaml：{exc}")]
    if not isinstance(data, dict):
        return [(False, "docs/design-facts.yaml 顶层不是映射（缺少 version / facts 结构）")]

    facts_raw = data.get("facts")
    misreadings_raw = _as_list(data.get("misreadings"))
    misreadings = [item for item in misreadings_raw if isinstance(item, dict)]
    results.append(
        (
            True,
            f"docs/design-facts.yaml 可解析：{len(_as_list(facts_raw))} 条事实，"
            f"{len(misreadings)} 条常见误读",
        )
    )

    top_problems: list[str] = []
    if "version" not in data or data.get("version") in (None, ""):
        top_problems.append("缺少顶层字段 version（应为整数，当前 schema 版本 1）")
    if "facts" not in data:
        top_problems.append("缺少顶层字段 facts（事实清单）")
    elif not isinstance(facts_raw, list):
        top_problems.append(f"顶层 facts 应为列表，实际 {type(facts_raw).__name__}")
    _collect(results, "顶层字段 version 与 facts 齐全", top_problems)
    if top_problems:
        return results

    _collect(
        results,
        "facts 字段合法（id 唯一且匹配 ^DF-\\d{3}$、state 在枚举内、affects 取值合法、topic 与 claim 非空）",
        check_structure(facts_raw),
    )
    _collect(
        results,
        "facts 与 misreadings 的 evidence 均为仓库内存在的 path:LINE 且指向非空行；"
        "misreadings 的 wrong 与 correct 非空",
        check_evidence(facts_raw, misreadings_raw, ROOT),
    )
    _collect(results, "state=obsolete 的条目都带非空 residue", check_residue(facts_raw))
    _collect(
        results,
        f"{THRESHOLD_FACT_ID} claim 的阈值键集与 ast 解析的 THRESHOLDS 一致（各 {EXPECTED_THRESHOLD_COUNT} 项）且逐项相等",
        check_thresholds(facts_raw),
    )
    _collect(results, "docs/design-facts.md 与 --render 结果逐字节一致", check_markdown(data))
    return results


def validate_mode() -> int:
    try:
        results = run_checks()
    except Exception as exc:  # 兜底：绝不以 traceback 结束
        print(f"FAIL  校验过程异常：{type(exc).__name__}: {exc}")
        return 1
    failed = 0
    for ok, message in results:
        if ok:
            print(f"PASS  {message}")
        else:
            failed += 1
            print(f"FAIL  {message}")
    print(f"\n合计 {len(results)} 项：PASS {len(results) - failed}，FAIL {failed}")
    return 1 if failed else 0


def render_mode() -> int:
    try:
        data = load_yaml(YAML_PATH)
    except YamlError as exc:
        print(f"FAIL  无法解析 docs/design-facts.yaml，未渲染：{exc}")
        return 1
    if not isinstance(data, dict):
        print("FAIL  docs/design-facts.yaml 顶层不是映射，未渲染")
        return 1
    try:
        MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        MD_PATH.write_text(render_markdown(data), encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"FAIL  无法写入 docs/design-facts.md：{exc}")
        return 1
    print(f"RENDER docs/design-facts.md：{len(_facts_of(data))} 条事实")
    print("提示：请再运行 `python scripts/verify_design_facts.py` 校验")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    unknown = [arg for arg in args if arg != "--render"]
    if unknown:
        print(f"FAIL  未知参数：{' '.join(unknown)}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if "--render" in args:
        return render_mode()
    return validate_mode()


if __name__ == "__main__":
    sys.exit(main())
