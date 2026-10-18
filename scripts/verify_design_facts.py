#!/usr/bin/env python3
"""校验 docs/design-facts.yaml，并由它渲染 docs/design-facts.md。

用法（三种模式互斥，缺省为校验；`--root` 对三种模式均可用）：
    python scripts/verify_design_facts.py [--root <仓库根>]
                                                     # 校验：逐项打印 PASS/PASS(no-expect)/FAIL，任一 FAIL 退出 1
    python scripts/verify_design_facts.py --render [--root <仓库根>]
                                                     # 渲染：由 yaml 重新生成 docs/design-facts.md，退出 0
    python scripts/verify_design_facts.py --check-doc-paths [--root <仓库根>]
                                                     # 路径自检：检查 md 里引用的仓库内路径是否存在，缺失退出 1
    python scripts/verify_design_facts.py --help     # 打印本说明，退出 0（独立于模式与 --root）

`--root` 把仓库根与 yaml / md / 阈值源码路径一并重定向；校验、渲染、路径自检三种模式都接受它。
`--root` 必须是**已存在的目录**，否则按参数错误打印用法并退出 2（三种模式一致）。这是相对旧版的
行为变化：旧版对不存在的目录会继续执行，`--check-doc-paths` 要到 `git -C <目录> ls-files` 才报
`退出码 128` 并退出 1，错误原因被藏在 git 的 stderr 里。

未知参数（如拼错的 --rendr）打印用法并退出 2，绝不静默回落到校验模式。
若 `--check-doc-paths` 扫不到任何可判定引用（例如正则 / 扩展名 / 前缀常量被改坏），该模式判 FAIL 而非 PASS。

--check-doc-paths 的覆盖范围与已知盲区（PASS 只代表「受检范围内路径存在」）：
- 扫描对象：`git ls-files '*.md'` 的受跟踪文件；引用主体限 ASCII `[A-Za-z0-9_./-]`。
- 识别前缀：`docs/`、`pipeline/`、`finetune/`、`versioning/`、`tests/`、`scripts/`、`records/`，
  可带若干 `./` 或 `../` 段；扩展名限 md / py / jsonl / json / yaml / yml / csv。
- 判定：同一引用按「仓库根」与「引用所在 md 的目录」双解析，两条解析路径任一命中才算通过。命中还须同时满足
  「解析结果落在仓库根之内」与「目标是普通文件（`is_file()`）」：越出仓库根的解析结果一律判缺失（如 `../../x`），
  同名的目录不算存在；指向符号链接时按其解析目标判定。只判存在性，不校验行号。
- 含 `...` 的占位引用不判存在性，逐条打印 SKIP 并计数；含全角省略号 `…` 的引用只打印 NOTE、不判定。
- 大小写是否敏感取决于文件系统：Linux（区分大小写）会判缺失，macOS 默认大小写不敏感卷可能判通过。
- 不覆盖：上述七类前缀以外的写法（绝对路径、`store/…`、`workspace/…`、`~/…`、URL）、行号后缀的
  正确性、非 md 文件、未被 git 跟踪的文件；因此 PASS 不等于「全仓路径都对」。

--check-doc-paths 的白名单是 `scripts/doc-path-allowlist.txt`（相对被检查的仓库根），三种规则形式：
- `refs: <regex>`（可省略前缀，默认 refs）用 `re.fullmatch` 匹配「引用路径本身」，豁免该路径的所有出现处；
- `files: <regex>` 用 `re.fullmatch` 匹配「引用所在文件」，豁免这些文件里的所有引用；
- `refs: <regex> files: <regex>`（同一行，顺序不限）要求两者都匹配才豁免，用于精确到「某文件中的某引用」。
豁免按**出现处**判定：同一路径在 A 文件被豁免，不会连带豁免 B 文件里的同名引用；一条路径只有在
所有出现处都存在或都被豁免时才算通过。`#` 开头为注释；文件不存在时视为空白名单（不 FATAL）但会注明；
0 命中的规则会打印 UNUSED RULE（仅提示，不改退出码）。

实现约束：
- 只用标准库，不 import 任何项目模块。
- 冻结阈值一律用 `ast` 解析 `finetune/holdout_metrics.py` 的 `THRESHOLDS` 字面量，不 import 该模块。
- 阈值校验是双向的：源码 THRESHOLDS 的项数、键集合与 claim 抽出的键集合必须一致，再逐项比值。
- evidence 支持两种写法：字符串 `path:LINE`（旧格式，无内容断言，标记 `PASS(no-expect)`）与映射
  `{ref: path:LINE, expect: 片段}`。映射只允许 `ref` 与 `expect` 两个键，`expect` 必须是非空、单行的
  字符串：拼错键名、缺 expect、空串 / null / 非字符串 / 含换行一律 FAIL（fail-closed），不得降级成
  `PASS(no-expect)`，否则断言会被静默丢弃。有 expect 时目标行必须按字面包含该片段（区分大小写、非模糊、
  非正则），失败文案同时打印期望片段与目标行实际内容。evidence 只接受仓库内相对路径
  （绝对路径与越出仓库根的引用一律 FAIL），防止事实锚定到仓库外。
- `expect` 值内**不支持行内注释**：yaml 子集只认整行注释，`expect: def target  # 说明` 会把
  `# 说明` 一并吞进期望片段。该写法不会静默通过（片段通常匹配不上而判 FAIL），需要整行注释请另起一行。
  值里的 `#` 一律原样保留（加不加引号都一样），只是 YAML 行内注释不被本子集支持。
- `expect` 必须是能唯一钉住该行语义的片段（唯一性由人工判断，工具只做字面命中校验）；
  越短越接近恒真（如 `expect: def` 无意义），应能区分「该行确实表达了这条事实」与
  「该行只是碰巧还在同一行号」。片段长度以能钉住语义为准；受标识符长度或引用语法限制时可超出常规长度
  （不以字数设硬阈值），但不得为了凑长度裁成恒真片段。
- 校验模式逐条 evidence 各占一行；聚合行按「带 expect 的 evidence N 条，命中 M 条」表述。该聚合行只在
  evidence 全部通过时打印，因此 M 恒等于 N，读者看不到 M < N；有 FAIL 时改由逐条 FAIL 行说明（N 为 0
  即没有任何内容断言）。
- 总结区的 `无内容断言的 evidence：N 条` 口径：N 只统计最终判定为 `PASS(no-expect)` 的条目（旧格式
  字符串，且 ref / 行号 / 非空行等检查全部通过）；被判 FAIL 的条目一律不计入，否则出现 FAIL 时这个数
  会「凭空变好」，被误读成断言健全程度提升。结构校验失败、evidence 根本没被检查时，该行改为打印
  `无内容断言的 evidence：未检查（结构校验已失败）`，不打印会误导的 0。
- 仓库根缺省按脚本自身位置推断（`Path(__file__).resolve().parents[1]`），不依赖 cwd；`--root <仓库根>`
  可显式重定向（校验 / 渲染 / --check-doc-paths 均可用），便于在隔离的假仓库中运行。
- `--render` 同样 fail-closed：evidence 形状非法（尤其 `expect` 含换行）时退出 1 且不写文件，
  不把多行片段折叠成源码里并不存在的单行假片段。边界：该预检只挡「evidence 形状非法」，**不**校验
  `ref` 是否符合 `path:LINE`、行号是否越界、目标文件是否存在——这些是校验模式的职责，`--render`
  不重复实现，也就不会因它们拒写。渲染会把 `expect` 原样写进 `docs/design-facts.md`，
  而该 md 又是 `--check-doc-paths` 的扫描对象：回填 `expect` 时应避开形如仓库相对路径的文本
  （如 `docs/...`、`scripts/...`），否则可能被当成引用扫描而引入假 MISSING。
- 写文件副作用：`--render`（含 `--render --root <目录>`）会在目标根下 `mkdir -p docs/` 并写
  `docs/design-facts.md`；校验模式与 `--check-doc-paths` 只读。写入走「同目录临时文件 + `os.replace`」
  的原子替换，中途 `OSError` 不会留下被截断的 md（`mkdir -p` 建出的空目录可能保留）。
- 符号链接边界：`os.replace` 替换的是链接这个目录项本身，md 若是符号链接，渲染后它变成普通文件
  （旧实现是穿透写，内容会落到链接目标里），链接关系不再保留。
- 残留边界：`finally` 清理临时文件在 SIGKILL / 外部超时杀进程时不会执行，此时会残留
  `docs/.design-facts.md.<pid>.tmp`，需要手工删除；它不是 md 本体，不影响后续校验。
- yaml 只用标准库解析其子集（映射、序列、块标量 `|`/`>`、行内序列 `[a, b]`、整行注释）；
  超出子集时明确报错，不静默误解析。
- `--check-doc-paths` 只做存在性检查，不校验行号；引用的路径主体限 ASCII 字符，
  避免把「`a.py`和`b.py`」这类中文连写吞成一条假路径。
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from contextlib import contextmanager
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
USAGE = (
    "用法：python scripts/verify_design_facts.py <模式> [--root <仓库根>]\n"
    "模式（三选一，缺省为校验）：--render | --check-doc-paths | 不带模式参数\n"
    "其它：--help（打印本说明，独立于模式与 --root）"
)
# 文档路径自检：引用主体限 ASCII（不用 \w，`\w` 会匹配中文导致相邻两个路径被吞成一条）。
# 允许若干 `./` / `../` 前缀（提取时保留，判存在性时按仓库根或引用所在目录解析）。
# 扩展名里 jsonl 必须排在 json 之前，否则 `.jsonl` 会被截成 `.json`。
DOC_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./\-])"
    r"(?P<ref>"
    r"(?:\.\.?/)*"
    r"(?:docs|pipeline|finetune|versioning|tests|scripts|records)/"
    r"[A-Za-z0-9_./\-]+\.(?:md|py|jsonl|json|yaml|yml|csv)"
    r")(?![A-Za-z0-9_])"
)
# 全角省略号占位：ASCII 正则提不到这种写法（如 `docs/plans/…report.md`），单列一条 NOTE 以免静默消失。
ELLIPSIS_HINT_RE = re.compile(
    r"(?:docs|pipeline|finetune|versioning|tests|scripts|records)/\S*…"
)
# 白名单规则关键字：`refs:` 与 `files:` 可单独出现，也可同行同时出现（两个都匹配才豁免）。
RULE_KEYWORD_RE = re.compile(r"(?:^|\s)(?P<kind>refs|files):\s*")
DOC_PATH_ALLOWLIST = Path("scripts") / "doc-path-allowlist.txt"
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


EVIDENCE_KEYS = ("ref", "expect")


def _evidence_entry(entry) -> tuple[str, str | None, str | None]:
    """把 evidence 条目归一成 (ref 文本, expect 片段, 结构错误)。

    字符串 `path:LINE` 是旧格式（无内容断言，标记 `PASS(no-expect)`）；映射只允许 `ref` 与 `expect`
    两个键，且必须带非空、单行的字符串 `expect`。任何形状错误都返回错误文案，不降级成「无内容断言」：
    拼错键名、缺 expect、空串 / null / 非字符串 / 含换行的 expect 都会让断言静默丢失，必须 fail-closed。
    """
    if not isinstance(entry, dict):
        return ("" if entry is None else str(entry).strip()), None, None
    reference = entry.get("ref")
    ref_text = reference.strip() if isinstance(reference, str) else ""
    unknown = [key for key in entry if key not in EVIDENCE_KEYS]
    if unknown:
        names = "、".join(repr(key) for key in unknown)
        return ref_text, None, f"evidence 映射出现未知键 {names}（只允许 ref 与 expect）"
    if reference is None:
        return ref_text, None, "evidence 映射缺少 ref"
    if not ref_text:
        return ref_text, None, "evidence 映射的 ref 必须是非空字符串"
    if "expect" not in entry:
        return (
            ref_text,
            None,
            "evidence 映射缺少 expect（映射写法必须带内容断言；无断言请改用字符串 path:LINE）",
        )
    expect = entry.get("expect")
    if not isinstance(expect, str):
        return (
            ref_text,
            None,
            f"evidence 的 expect 必须是字符串，实际是 {type(expect).__name__}（禁止隐式转换）",
        )
    if not expect.strip():
        return ref_text, None, "evidence 的 expect 为空（空白串不能当内容断言）"
    if "\n" in expect or "\r" in expect:
        return ref_text, None, "evidence 的 expect 含换行，无法作为单行内容断言"
    return ref_text, expect, None


def _evidence_shape_problems(data) -> list[str]:
    """用与校验相同的形状规则扫 facts 与 misreadings 的 evidence，返回问题清单（渲染前 fail-closed 用）。"""
    problems: list[str] = []
    for fact in _facts_of(data):
        label = _text(fact.get("id")) or "<无 id>"
        for entry in _as_list(fact.get("evidence")):
            _, _, shape_error = _evidence_entry(entry)
            if shape_error is not None:
                problems.append(f"{label} evidence：{shape_error}")
    misreadings = data.get("misreadings") if isinstance(data, dict) else None
    for index, item in enumerate(_as_list(misreadings), start=1):
        if not isinstance(item, dict):
            continue
        for entry in _as_list(item.get("evidence")):
            _, _, shape_error = _evidence_entry(entry)
            if shape_error is not None:
                problems.append(f"misreadings[{index}] evidence：{shape_error}")
    return problems


def _check_evidence_refs(
    label: str, refs, root: Path
) -> tuple[list[tuple[str, str]], int, int, int]:
    """逐条校验 evidence，返回 ([(状态, 文案)], 无内容断言的条数, 带 expect 的检查条数, 命中条数)。

    状态取值：`pass`（有 expect 且命中）、`no-expect`（旧格式字符串，保持原校验）、`fail`。
    「带 expect 的检查条数」与「命中条数」是两个量：前者是真正到达内容断言比较的条数，后者是片段
    确实出现在目标行的条数，二者在全部通过时相等。
    有 expect 时要求目标行按字面包含该片段（区分大小写、非模糊、非正则），失败文案同带期望片段与实际行内容。
    被判 FAIL 的条目不计入「无内容断言」：断言被静默丢弃不应伪装成缺省行为。
    """
    records: list[tuple[str, str]] = []
    no_expect = 0
    expect_checked = 0
    expect_hits = 0
    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root
    for entry in refs:
        reference, expect, shape_error = _evidence_entry(entry)
        if shape_error is not None:
            records.append(("fail", f"{label} evidence {reference or entry!r}：{shape_error}"))
            continue
        match = EVIDENCE_RE.match(reference)
        if not match:
            records.append(("fail", f"{label} evidence ref {reference!r} 不符合 path:LINE 形式"))
            continue
        relative = match.group("path")
        line_no = int(match.group("line"))
        if Path(relative).is_absolute():
            records.append(("fail", f"{label} evidence {reference}：必须是仓库内相对路径，实际是绝对路径"))
            continue
        target = root / relative
        try:
            resolved = target.resolve()
        except OSError as exc:
            records.append(("fail", f"{label} evidence {reference}：无法解析路径（{exc}）"))
            continue
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            records.append(("fail", f"{label} evidence {reference}：越出仓库根"))
            continue
        if not target.is_file():
            records.append(("fail", f"{label} evidence {reference}：文件不存在（{relative}）"))
            continue
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            records.append(("fail", f"{label} evidence {reference}：无法读取 {relative}（{exc}）"))
            continue
        if line_no < 1 or line_no > len(lines):
            records.append(
                ("fail", f"{label} evidence {reference}：行号越界（{relative} 共 {len(lines)} 行）")
            )
            continue
        line_text = lines[line_no - 1]
        if not line_text.strip():
            records.append(("fail", f"{label} evidence {reference}：指向空行"))
            continue
        if expect is not None:
            expect_checked += 1
            if expect not in line_text:
                records.append(
                    (
                        "fail",
                        f"{label} evidence {reference}：期望片段 {expect!r} 未出现在该行；"
                        f"实际行内容 {line_text!r}",
                    )
                )
                continue
            expect_hits += 1
            records.append(("pass", f"{label} evidence {reference}"))
        else:
            no_expect += 1
            records.append(("no-expect", f"{label} evidence {reference}"))
    return records, no_expect, expect_checked, expect_hits


def check_evidence(
    facts_raw, misreadings, root: Path
) -> tuple[list[tuple[str, str]], int, int, int, list[str]]:
    """facts 与 misreadings 的 evidence 用同一套规则校验；misreadings 另要求 wrong/correct 非空。

    返回 (逐条结果, 无内容断言的 evidence 条数, 带 expect 的检查条数, 命中条数, 非 evidence 逐条的结构问题)。
    """
    records: list[tuple[str, str]] = []
    no_expect = 0
    expect_checked = 0
    expect_hits = 0
    extra: list[str] = []
    for fact in _facts_of({"facts": facts_raw}):
        label = _text(fact.get("id")) or "<无 id>"
        refs = _as_list(fact.get("evidence"))
        if not refs:
            extra.append(f"{label} 缺少 evidence")
            continue
        fact_records, fact_no_expect, fact_checked, fact_hits = _check_evidence_refs(label, refs, root)
        records.extend(fact_records)
        no_expect += fact_no_expect
        expect_checked += fact_checked
        expect_hits += fact_hits
    for index, item in enumerate(_as_list(misreadings), start=1):
        label = f"misreadings[{index}]"
        if not isinstance(item, dict):
            extra.append(f"{label} 不是映射，无法校验")
            continue
        if not _text(item.get("wrong")):
            extra.append(f"{label} 缺少非空 wrong")
        if not _text(item.get("correct")):
            extra.append(f"{label} 缺少非空 correct")
        # evidence 对误读条目是可选补充锚点，有则必须同规则合法。
        refs = _as_list(item.get("evidence"))
        if refs:
            item_records, item_no_expect, item_checked, item_hits = _check_evidence_refs(
                label, refs, root
            )
            records.extend(item_records)
            no_expect += item_no_expect
            expect_checked += item_checked
            expect_hits += item_hits
    return records, no_expect, expect_checked, expect_hits, extra


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
def _render_evidence(entry) -> str:
    """把 evidence 渲染成 `path:LINE` 或 `path:LINE（expect：片段）`，绝不输出映射的 repr。

    `expect` 原样输出、不折叠空白：折叠会造出源码里并不存在的假片段，多行 expect 由 render_mode
    在写文件前直接拒绝（fail-closed）。
    """
    if isinstance(entry, dict):
        reference = "" if entry.get("ref") is None else str(entry.get("ref")).strip()
        expect = entry.get("expect")
        if isinstance(expect, str) and expect.strip():
            return f"{reference}（expect：{expect}）"
        return reference
    return "" if entry is None else str(entry).strip()


def _render_fact(fact: dict) -> list[str]:
    lines = [f"### {_text(fact.get('id'))} [{_text(fact.get('state'))}] {_text(fact.get('topic'))}"]
    lines.append(_text(fact.get("claim")))
    lines.append("出处：")
    for ref in _as_list(fact.get("evidence")):
        lines.append(f"- {_render_evidence(ref)}")
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
                lines.append(f"  - 出处：{_render_evidence(ref)}")
    else:
        lines.append("（当前没有登记常见误读。）")

    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- #
# 文档路径存在性自检（--check-doc-paths）
# --------------------------------------------------------------------------- #
def _git_md_files(root: Path) -> tuple[list[str] | None, str | None]:
    """用 `git -C <root> ls-files -z '*.md'` 取受跟踪的 md 清单；失败时返回原因。

    用 `-z` 是为了关掉 git 对非 ASCII 路径的引号转义，否则中文文件名无法直接打开。
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return None, f"无法执行 git：{exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or "无输出"
        return None, (
            f"git -C {root} ls-files -z '*.md' 退出码 {completed.returncode}"
            f"（不是 git 仓库或 git 不可用？）：{detail}"
        )
    files = [chunk for chunk in completed.stdout.split("\0") if chunk.strip()]
    return files, None


def _scan_md_refs(root: Path, md_files: list[str]) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """逐行抽取 md 里的仓库内路径引用。

    返回 (引用列表, 占位跳过列表, 全角省略号提示列表, 读取问题)；含 `...` 的占位引用记入跳过列表
    而不判存在性，以便输出里区分「占位符」与「手滑写错的路径」；含全角 `…` 的写法提不到，
    单独记入提示列表，避免静默消失。
    """
    refs: list[dict] = []
    skipped: list[dict] = []
    hints: list[dict] = []
    problems: list[str] = []
    for relative in md_files:
        try:
            text = (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{relative} 无法读取：{exc}")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in DOC_PATH_RE.finditer(line):
                item = {"ref": match.group("ref"), "file": relative, "line": lineno}
                if "..." in item["ref"]:
                    skipped.append(item)
                    continue
                refs.append(item)
            if "…" in line and ELLIPSIS_HINT_RE.search(line):
                hints.append({"file": relative, "line": lineno})
    return refs, skipped, hints, problems


def _parse_rule_line(line: str) -> tuple[dict | None, str | None]:
    """解析一行白名单规则：返回 ({refs 源码或 None, files 源码或 None}, 错误信息)。

    支持三种形式：`refs: R`（可省略前缀）、`files: F`、`refs: R files: F`（顺序不限）。
    """
    marks = list(RULE_KEYWORD_RE.finditer(line))
    if not marks:
        return {"refs": line.strip(), "files": None}, None
    parts: dict[str, str] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(line)
        kind = mark.group("kind")
        value = line[mark.end():end].strip()
        if kind in parts:
            return None, f"{kind}: 在同一行重复出现"
        if not value:
            return None, f"{kind}: 后缺正则"
        parts[kind] = value
    return {"refs": parts.get("refs"), "files": parts.get("files")}, None


def load_doc_path_allowlist(path: Path) -> tuple[list[dict], list[str]]:
    """读白名单：返回规则列表与问题列表；文件不存在时视为空白名单。

    每条规则是 {ref, file, source, text, hits}：ref / file 是已编译正则或 None，
    两者均给出时必须同时 fullmatch 才豁免；hits 记录它**匹配到**的出现处数，仅用于判 UNUSED RULE
    （豁免归属取首个匹配的规则），不代表实际豁免数量。
    """
    rules: list[dict] = []
    problems: list[str] = []
    if not path.is_file():
        return rules, problems
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return rules, [f"白名单 {path} 无法读取：{exc}"]
    label = DOC_PATH_ALLOWLIST.as_posix()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed, error = _parse_rule_line(line)
        if error is not None:
            problems.append(f"{label}:{lineno} {error}")
            continue
        compiled: dict[str, re.Pattern | None] = {"refs": None, "files": None}
        for kind in ("refs", "files"):
            pattern = parsed[kind]
            if pattern is None:
                continue
            try:
                compiled[kind] = re.compile(pattern)
            except re.error as exc:
                problems.append(f"{label}:{lineno} {kind}: 正则无效：{pattern!r}（{exc}）")
        rules.append(
            {
                "ref": compiled["refs"],
                "file": compiled["files"],
                "source": f"{label}:{lineno}",
                "text": line,
                "hits": 0,
            }
        )
    return rules, problems


def _match_rule(rule: dict, ref: str, md_file: str) -> bool:
    """判定一条规则是否豁免某个出现处：refs 与 files 都给出时必须同时匹配。"""
    if rule["ref"] is not None and not rule["ref"].fullmatch(ref):
        return False
    if rule["file"] is not None and not rule["file"].fullmatch(md_file):
        return False
    return True


def _ref_exists(root: Path, ref: str, md_file: str) -> tuple[bool, bool]:
    """双解析存在性：返回 (按仓库根拼接是否为文件, 按引用所在 md 的目录拼接是否为文件)。

    两条解析路径都要求最终路径落在仓库根之内（与默认模式的 evidence 校验一致）：
    `../` 只要不出根仍合法，`../..` 这类越出仓库根的写法一律按「不存在」处理；
    目标必须是普通文件，同名的目录不算命中。
    """
    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root.absolute()
    results: list[bool] = []
    for base in (root, (root / md_file).parent):
        try:
            target = (base / ref).resolve()
        except OSError:
            results.append(False)
            continue
        try:
            target.relative_to(root_resolved)
        except ValueError:
            results.append(False)
            continue
        results.append(target.is_file())
    return results[0], results[1]


def check_doc_paths_mode(root: Path) -> int:
    """校验 md 里引用的仓库内路径确实存在；缺失则逐条报 MISSING 并退出 1。

    豁免按出现处判定：同一路径在历史文档里被豁免，不会连带豁免当前文档里的同名引用。
    """
    print(f"CHECK 文档路径存在性：{root}")
    md_files, error = _git_md_files(root)
    if error is not None:
        print(f"FAIL  {error}")
        return 1
    if not md_files:
        print("FAIL  git ls-files '*.md' 没有返回任何文件，无法自检（不在 git 仓库内或没有受跟踪的 md）")
        return 1

    refs, skipped, hints, problems = _scan_md_refs(root, md_files)
    if problems:
        for problem in problems:
            print(f"FAIL  {problem}")
        return 1
    allowlist_path = root / DOC_PATH_ALLOWLIST
    rules, allow_problems = load_doc_path_allowlist(allowlist_path)
    if allow_problems:
        for problem in allow_problems:
            print(f"FAIL  {problem}")
        return 1
    if not allowlist_path.is_file():
        print(f"NOTE  白名单文件不存在：{allowlist_path}（视为空白名单）")

    by_ref: dict[str, list[dict]] = {}
    for item in refs:
        by_ref.setdefault(item["ref"], []).append(item)

    for item in skipped:
        print(f"SKIP {item['ref']}  <- {item['file']}:{item['line']}")
    for item in hints:
        print(f"NOTE  含全角省略号、未判定  <- {item['file']}:{item['line']}")

    if not refs:
        print(
            "FAIL  未扫描到任何可判定引用"
            f"（占位符 SKIP {len(skipped)} 处、全角省略号 NOTE {len(hints)} 处）"
        )
        return 1

    hits = {"both": 0, "root": 0, "file": 0}
    missing: list[dict] = []
    unknown_refs: list[str] = []
    exempt_places = 0
    for ref in sorted(by_ref):
        unresolved: list[dict] = []
        for item in by_ref[ref]:
            at_root, at_file = _ref_exists(root, ref, item["file"])
            if at_root and at_file:
                hits["both"] += 1
                continue
            if at_root or at_file:
                hits["root" if at_root else "file"] += 1
                continue
            matched = [rule for rule in rules if _match_rule(rule, ref, item["file"])]
            if matched:
                for rule in matched:
                    rule["hits"] += 1
                exempt_places += 1
                continue
            unresolved.append(item)
        if unresolved:
            unknown_refs.append(ref)
            missing.extend(unresolved)

    for item in missing:
        print(f"MISSING {item['ref']}  <- {item['file']}:{item['line']}")

    if rules:
        for rule in rules:
            if rule["hits"] == 0:
                print(f"UNUSED RULE {rule['source']} {rule['text']}")

    print(
        f"扫描：{len(md_files)} 个受跟踪 md，{len(refs)} 处引用，{len(by_ref)} 个唯一路径；"
        f"存在 {sum(hits.values())} 处（root {hits['root']}、file {hits['file']}、both {hits['both']}）"
    )
    print(
        f"合计 {len(refs)} 处引用，唯一路径 {len(by_ref)}，不存在 {len(missing)} 处"
        f"（涉 {len(unknown_refs)} 个路径，白名单豁免 {exempt_places} 处）"
    )
    if skipped:
        print(f"占位符跳过 {len(skipped)} 处（含 `...`，不判存在性）")
    if hints:
        print(f"含全角省略号、未判定 {len(hints)} 处")
    if missing:
        print("若为示例/计划路径，可加入 `scripts/doc-path-allowlist.txt`")
        return 1
    print("PASS  所有引用的目标路径均存在，或已由 scripts/doc-path-allowlist.txt 豁免")
    return 0


# --------------------------------------------------------------------------- #
# 模式
# --------------------------------------------------------------------------- #
def _collect(results: list[tuple[str, str]], label: str, problems: list[str]) -> None:
    if problems:
        results.extend(("fail", f"{label}：{problem}") for problem in problems)
    else:
        results.append(("pass", label))


def run_checks() -> tuple[list[tuple[str, str]], int | None]:
    """跑全部校验项，返回 ([(状态, 文案)], 无内容断言的 evidence 条数)。

    第二个元素为 `None` 表示 evidence 根本没被检查（前置结构已失败）：调用方不得当成 0 打印，
    否则会被误读成「没有无断言条目」。
    """
    results: list[tuple[str, str]] = []
    try:
        data = load_yaml(YAML_PATH)
    except YamlError as exc:
        return [("fail", f"无法解析 docs/design-facts.yaml：{exc}")], None
    if not isinstance(data, dict):
        return [("fail", "docs/design-facts.yaml 顶层不是映射（缺少 version / facts 结构）")], None

    facts_raw = data.get("facts")
    misreadings_raw = _as_list(data.get("misreadings"))
    misreadings = [item for item in misreadings_raw if isinstance(item, dict)]
    results.append(
        (
            "pass",
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
        return results, None

    _collect(
        results,
        "facts 字段合法（id 唯一且匹配 ^DF-\\d{3}$、state 在枚举内、affects 取值合法、topic 与 claim 非空）",
        check_structure(facts_raw),
    )
    # evidence 逐条打印；有任何逐条 FAIL 或结构问题时不再输出聚合 PASS 行（避免自相矛盾）。
    evidence_records, no_expect, expect_checked, expect_hits, evidence_extra = check_evidence(
        facts_raw, misreadings_raw, ROOT
    )
    results.extend(evidence_records)
    results.extend(("fail", f"evidence 结构问题：{problem}") for problem in evidence_extra)
    if not evidence_extra and all(status != "fail" for status, _ in evidence_records):
        results.append(
            (
                "pass",
                "facts 与 misreadings 的 evidence 均为仓库内存在的 path:LINE 且指向非空行；"
                f"带 expect 的 evidence {expect_checked} 条，命中 {expect_hits} 条"
                "（0 条即没有任何内容断言）；misreadings 的 wrong 与 correct 非空",
            )
        )
    _collect(results, "state=obsolete 的条目都带非空 residue", check_residue(facts_raw))
    _collect(
        results,
        f"{THRESHOLD_FACT_ID} claim 的阈值键集与 ast 解析的 THRESHOLDS 一致（各 {EXPECTED_THRESHOLD_COUNT} 项）且逐项相等",
        check_thresholds(facts_raw),
    )
    _collect(results, "docs/design-facts.md 与 --render 结果逐字节一致", check_markdown(data))
    return results, no_expect


@contextmanager
def _root_scope(root: Path | None):
    """临时把仓库根及 yaml / md / 阈值源码路径重定向到 `root`，退出时（含异常）还原。

    默认（`root is None`）不重定向；用上下文而不是裸函数，避免被 import 复用时状态泄漏到下一次调用。
    """
    global ROOT, YAML_PATH, MD_PATH, THRESHOLDS_PATH
    if root is None:
        yield
        return
    saved = (ROOT, YAML_PATH, MD_PATH, THRESHOLDS_PATH)
    ROOT = root
    YAML_PATH = root / "docs" / "design-facts.yaml"
    MD_PATH = root / "docs" / "design-facts.md"
    THRESHOLDS_PATH = root / "finetune" / "holdout_metrics.py"
    try:
        yield
    finally:
        ROOT, YAML_PATH, MD_PATH, THRESHOLDS_PATH = saved


def validate_mode(root: Path | None = None) -> int:
    with _root_scope(root):
        try:
            results, no_expect = run_checks()
        except Exception as exc:  # 兜底：绝不以 traceback 结束
            print(f"FAIL  校验过程异常：{type(exc).__name__}: {exc}")
            return 1
        failed = 0
        passed = 0
        no_expect_rows = 0
        for status, message in results:
            if status == "pass":
                passed += 1
                print(f"PASS  {message}")
            elif status == "no-expect":
                no_expect_rows += 1
                print(f"PASS(no-expect)  {message}")
            else:
                failed += 1
                print(f"FAIL  {message}")
        print(
            f"\n合计 {len(results)} 项：PASS {passed}，PASS(no-expect) {no_expect_rows}，FAIL {failed}"
        )
        if no_expect is None:
            print("无内容断言的 evidence：未检查（结构校验已失败）")
        else:
            print(f"无内容断言的 evidence：{no_expect} 条")
        return 1 if failed else 0


def render_mode(root: Path | None = None) -> int:
    with _root_scope(root):
        try:
            data = load_yaml(YAML_PATH)
        except YamlError as exc:
            print(f"FAIL  无法解析 docs/design-facts.yaml，未渲染：{exc}")
            return 1
        if not isinstance(data, dict):
            print("FAIL  docs/design-facts.yaml 顶层不是映射，未渲染")
            return 1
        # fail-closed：形状非法的 evidence（尤其多行 expect）不得被折叠成假片段写进 md。
        shape_problems = _evidence_shape_problems(data)
        if shape_problems:
            print("FAIL  存在非法 evidence，未渲染（含换行 / 空值 / 非字符串 / 未知键的写法会让断言失真）：")
            for problem in shape_problems:
                print(f"  - {problem}")
            return 1
        # 先写同目录临时文件再 os.replace：中途 OSError 不会把已存在的 md 截成半成品。
        tmp_path = MD_PATH.parent / f".{MD_PATH.name}.{os.getpid()}.tmp"
        try:
            MD_PATH.parent.mkdir(parents=True, exist_ok=True)
            text = render_markdown(data)
            tmp_path.write_text(text, encoding="utf-8", newline="\n")
            os.replace(tmp_path, MD_PATH)
        except OSError as exc:
            print(f"FAIL  无法写入 docs/design-facts.md：{exc}")
            return 1
        finally:
            # 成功时临时文件已被 replace 移走，这里只是无害地清掉失败残留。
            try:
                tmp_path.unlink()
            except OSError:
                pass
        print(f"RENDER docs/design-facts.md：{len(_facts_of(data))} 条事实")
        print("提示：请再运行 `python scripts/verify_design_facts.py` 校验")
        return 0


def _split_root_arg(args: list[str]) -> tuple[list[str], str | None, str | None]:
    """抽出 `--root <路径>` / `--root=<路径>`；返回 (其余参数, root 文本, 错误信息)。

    下面三种情况按参数错误处理（退出 2）：取值缺失或为空、取值以 `--` 开头（疑似把参数当路径）、
    重复给出 `--root`（不静默取最后一个）。
    """
    rest: list[str] = []
    root: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--root":
            if index + 1 >= len(args):
                return rest, None, "--root 缺少取值（后面没有参数）"
            value = args[index + 1]
            if value.startswith("--"):
                return rest, None, f"--root 缺少取值（后面紧跟的是参数 {value}，疑似把参数当路径）"
            if not value.strip():
                return rest, None, "--root 取值为空"
            if root is not None:
                return rest, None, f"--root 重复给出（已给 {root}，又给 {value}）"
            root = value
            index += 2
            continue
        if arg.startswith("--root="):
            value = arg[len("--root="):]
            if not value.strip():
                return rest, None, "--root 取值为空"
            if value.startswith("--"):
                return rest, None, f"--root 缺少取值（{value} 以 -- 开头，疑似把参数当路径）"
            if root is not None:
                return rest, None, f"--root 重复给出（已给 {root}，又给 {value}）"
            root = value
            index += 1
            continue
        rest.append(arg)
        index += 1
    return rest, root, None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "-h" in args or "--help" in args:
        print(__doc__)
        return 0
    rest, root_text, root_error = _split_root_arg(args)
    if root_error is not None:
        print(f"FAIL  {root_error}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    check_doc_paths = "--check-doc-paths" in rest
    unknown = [arg for arg in rest if arg not in ("--render", "--check-doc-paths")]
    if unknown:
        print(f"FAIL  未知参数：{' '.join(unknown)}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if root_text is not None and not Path(root_text).expanduser().is_dir():
        print(f"FAIL  --root 指向的不是目录：{root_text}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    if check_doc_paths and "--render" in rest:
        print("FAIL  --render 与 --check-doc-paths 互斥，一次只运行一种模式", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    root = Path(root_text).expanduser() if root_text else None
    if check_doc_paths:
        return check_doc_paths_mode(root if root is not None else ROOT)
    if "--render" in rest:
        return render_mode(root)
    return validate_mode(root)


if __name__ == "__main__":
    sys.exit(main())
