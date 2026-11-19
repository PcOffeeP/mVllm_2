"""设计事实检查。

未移植：--render（本模块仅负责检查，不生成渲染文档）；DF-004 七项阈值检查
（check_thresholds）的目标 finetune/holdout_metrics.py 未在本工作区检出，无法本机核对。
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
ALLOWED_STATES = ("active", "obsolete", "superseded")
ALLOWED_AFFECTS = ("prompt", "contract", "code", "data", "eval", "metrics", "gate", "ops")
FACT_ID_RE = re.compile(r"^DF-\d{3}$")
EVIDENCE_RE = re.compile(r"^(?P<path>.+):(?P<line>\d+)$")
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
DOC_PATH_ALLOWLIST = Path(__file__).resolve().parent / "doc-path-allowlist.txt"


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
    label = path.as_posix()
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


def check_doc_paths_mode(root: Path, allowlist_path: Path | None = None) -> int:
    """校验 md 里引用的仓库内路径确实存在；缺失则逐条报 MISSING 并退出 1。

    豁免按出现处判定：同一路径在历史文档里被豁免，不会连带豁免当前文档里的同名引用。
    """
    allowlist_path = allowlist_path or root / "script/checks/doc-path-allowlist.txt"
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
        print("若为示例/计划路径，可加入 `script/checks/doc-path-allowlist.txt`")
        return 1
    print("PASS  所有引用的目标路径均存在，或已由 script/checks/doc-path-allowlist.txt 豁免")
    return 0



def normalize(text: str) -> str:
    return " ".join(text.split())


def load_allowlist(path: Path) -> list:
    rules, problems = load_doc_path_allowlist(path)
    if problems:
        raise ValueError("; ".join(problems))
    return rules


def check_facts(root: Path, facts_path: Path) -> dict:
    root = Path(root).resolve()
    facts_path = Path(facts_path)
    totals = dict.fromkeys(("entries", "evidence", "passed", "drift", "gone", "unverifiable", "structure", "structure_errors"), 0)
    report = {"facts_path": str(facts_path), "totals": totals, "results": [], "structure_errors": []}

    def error(label, message):
        report["structure_errors"].append({"id": label, "message": message})
        totals["structure_errors"] += 1

    try:
        data = load_yaml(facts_path)
    except YamlError as exc:
        error("document", str(exc))
        return report
    if not isinstance(data, dict):
        error("document", "顶层必须是映射，包含 version 和 facts")
        return report
    if data.get("version") in (None, ""):
        error("document", "缺少 version")
    facts = data.get("facts")
    if not isinstance(facts, list):
        error("document", "facts 必须是列表")
        facts = []
    misreadings = _as_list(data.get("misreadings"))
    totals["entries"] = len(facts) + len(misreadings)

    def evidence(label, entry, location):
        ref, expect, problem = _evidence_entry(entry)
        if not isinstance(entry, dict) and problem is None:
            problem = "evidence 必须包含 ref 和 expect"
        match = EVIDENCE_RE.fullmatch(ref) if ref else None
        if problem is None and not match:
            problem = "ref 不符合 path:LINE"
        target = None
        if problem is None:
            path = match.group("path")
            try:
                target = (root / path).resolve()
                if Path(path).is_absolute() or not target.is_relative_to(root):
                    problem = "ref 必须为仓库内相对路径"
            except (OSError, ValueError, RuntimeError):
                problem = "ref 路径无法解析"
        category, actual, detail = "structure", None, problem
        if problem:
            error(label, problem)
        elif path.startswith(("pipeline/", "finetune/", "versioning/", "docs/results/")):
            category, detail = "unverifiable", "未检出前缀"
        elif not target.is_file():
            category = "unverifiable" if location == "original_worktree" else "gone"
            detail = "文件不存在"
        else:
            try:
                lines = target.read_text(encoding="utf-8").splitlines()
                line = int(match.group("line"))
                needle = normalize(expect)
                if 1 <= line <= len(lines) and needle in normalize(lines[line - 1]):
                    category, actual, detail = "pass", line, "指定行命中"
                else:
                    found = next((i for i, text in enumerate(lines, 1) if needle in normalize(text)), None)
                    category, actual, detail = ("drift", found, "其他行命中") if found is not None else ("gone", None, "未找到内容")
            except (OSError, UnicodeDecodeError) as exc:
                category, detail = "unverifiable", f"无法读取文件: {exc}"
        report["results"].append(dict(id=label, ref=ref, expect=expect, actual=actual, category=category, detail=detail))
        totals["evidence"] += 1
        totals["passed" if category == "pass" else category] += 1

    seen = set()
    for index, fact in enumerate(facts, 1):
        label = fact.get("id") if isinstance(fact, dict) else None
        label = label if isinstance(label, str) and label else f"facts[{index}]"
        if not isinstance(fact, dict):
            error(label, "条目必须是映射")
            continue
        if not FACT_ID_RE.fullmatch(label):
            error(label, "id 格式非法")
        elif label in seen:
            error(label, "id 重复")
        seen.add(label)
        if fact.get("state") not in ALLOWED_STATES:
            error(label, f"state 非法: {fact.get('state')!r}")
        if fact.get("state") == "obsolete" and not _text(fact.get("residue")):
            error(label, "state=obsolete 但没有非空 residue（墓碑必须留下处置说明）")
        for key in ("topic", "claim"):
            if not _text(fact.get(key)):
                error(label, f"缺少 {key}")
        affects = _as_list(fact.get("affects"))
        if not affects:
            error(label, "缺少 affects")
        for value in affects:
            if value not in ALLOWED_AFFECTS:
                error(label, f"affects 非法: {value!r}")
        refs = _as_list(fact.get("evidence"))
        if not refs:
            error(label, "缺少 evidence")
        for entry in refs:
            evidence(label, entry, fact.get("evidence_location"))
    for index, item in enumerate(misreadings, 1):
        label = f"misreadings[{index}]"
        if not isinstance(item, dict):
            error(label, "条目必须是映射")
            continue
        for key in ("wrong", "correct"):
            if not _text(item.get(key)):
                error(label, f"缺少 {key}")
        for entry in _as_list(item.get("evidence")):
            evidence(label, entry, item.get("evidence_location"))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--facts", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--check-doc-paths", action="store_true")
    parser.add_argument("--allowlist", type=Path)
    args = parser.parse_args(argv)
    if args.check_doc_paths:
        return check_doc_paths_mode(args.root, args.allowlist)
    report = check_facts(args.root, args.facts or args.root / "docs/facts.yaml")
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for result in report["results"]:
            actual = f"（实际行号 {result['actual']}）" if result["category"] == "drift" else ""
            print(f"{result['category'].upper()} {result['id']} {result['ref']}: {result['detail']}{actual}")
        for error in report["structure_errors"]:
            print(f"STRUCTURE {error['id']}: {error['message']}")
        totals = report["totals"]
        print(f"通过 {totals['passed']}，位置漂移 {totals['drift']}，原文消失 {totals['gone']}，"
              f"本机无法核对 {totals['unverifiable']}，结构错误 {totals['structure']}，"
              f"structure_errors {totals['structure_errors']}")
        print("合计:", totals)
    return int(args.strict and (bool(report["structure_errors"]) or any(report["totals"][key] for key in ("drift", "gone", "unverifiable", "structure"))))


if __name__ == "__main__":
    sys.exit(main())
