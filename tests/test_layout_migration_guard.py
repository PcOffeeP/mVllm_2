"""布局迁移守卫：防止代码 / 配置 / 测试重新写回被撤销的 ``workspace/`` 布局。

目的
----
用户已决定拆除 ``workspace/`` 目录，内容搬到顶层语义目录（``data`` / ``trains`` /
``models`` / ``mlflow`` / ``evaluations`` / ``audits/...`` / ``data-staging`` /
``data-rebuild`` / ``base-models``）。P0+P1 只改代码 / 配置 / 测试与 ``.gitignore``，
物理搬迁留到 P2。本文件是覆盖两个阶段的性质型护栏：只用「存在 / 不存在」「路径段」
这类性质判定，不记录任何收集数、文件数等快照数值。

守卫分三块：

* T1：旧物理路径不该再存在（P2 已完成，``PENDING_PHYSICAL_MOVE`` 必须为空，
  ``workspace/`` 根段本身也必须不存在）。
* T2：``evaluations`` 不再位于 ``workspace/`` 之下；顶层 ``evaluations`` 若存在
  必须是目录。均为无条件性质断言，不依赖任何「搬迁完成信号」目录是否落盘。
* T3：源码 / 配置里的旧布局字面量（``root / "workspace" / "mlflow"``、
  ``"workspace/models/"``、``workspace/data-staging`` 三种写法）必须清零，
  仅允许 ``versioning/backup.py`` 的「备份包内结构」行用 ``layout-guard-allow``
  标记豁免（标记行还必须同时含 ``workspace/evaluations``，并有行数上限）。
  同一区块还覆盖 P2 搬走的**旧基座路径**：``models/minicpm-v-4.5`` /
  ``models/minicpmv4_5`` 的斜杠连写字面量必须清零（新位置是
  ``base-models/minicpmv4_5``）。``_BASE_MODEL_ALLOWLIST`` 豁免机制保留但**当前为空**
  （历史测试夹具已改指新基座路径，不再需要豁免）；空集由用例显式断言，条目形如
  ``(相对路径, 行内唯一片段) -> 理由``，条数受性质型上限约束，且每条都必须仍能唯一
  命中宿主文件里的一行（腐坏即失败）。遮蔽自证用 ``monkeypatch`` 临时注入条目，
  不依赖真实豁免存在。
* T4：``pipeline.project_workspace`` 的路径语义直接以仓库根为根。
* T5 / T6：训练等本地产物不得被 git 跟踪；``data`` 中的标注、划分和 ROI
  记录允许进入 Git，视频与运行锁仍须忽略。

已知限制
--------
T3 的三条 workspace 正则只覆盖「引号内的 ``workspace`` 段」与「``workspace`` 后紧跟
旧子目录」两种字面量形态；``Path(root, "workspace")``、``root.joinpath("workspace",
"data")`` 这类把目录名当独立参数传入的写法不被匹配（刻意不扩大正则：
``COMPAT_WORKSPACE_NAME = "workspace"`` 等合法的兼容常量会被误伤），该缺口由 code
review 兜底。

旧基座路径检测只覆盖 ``models/<名字>`` 的斜杠连写形态，并刻意带边界：名字前不得是
路径名 / 盘符字符（``base-models/minicpmv4_5``、``../base-models/minicpmv4_5`` 因此
不命中），名字后不得是名字字符（``models/minicpmv4_5.bak`` 不命中），紧跟 ``:`` 的
形态结构性排除（``minicpmv4_5:models/minicpm-v-4.5:max_frames=8`` 这类指纹标签串里
``:`` 是无空白字段分隔符、不是路径分隔符，不做磁盘访问）。同样不覆盖
``Path("models", "minicpmv4_5")``、``tmp_path / "models" / "minicpmv4_5"`` 这类分段构造
（与 workspace 侧限制一致），也不覆盖 ``"model_version": "minicpm-v-4.5"`` 这类**没有
``models/`` 前缀**的裸名字——后者是契约里的模型名而非路径，T3 不判名字语义。

失效条件
--------
双端（本机与训练机）物理搬迁完成且验证通过后：把 T1 / T2 / T3 旧基座检测的结论
并入 design-facts 的 evidence，或直接删除本文件。二者必居其一，不得无限期
滞留。
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("pipeline", reason="sparse-checkout 未检出 pipeline/：该模块依赖 pipeline 包")

from pipeline.project_workspace import (
    experiment_workspace_paths,
    project_workspace_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

# 目标映射表：旧路径 -> 新路径。T1 以此为唯一判据来源。
LEGACY_TO_FLATTENED = {
    "workspace/data": "data",
    "workspace/runs": "trains",
    "workspace/models": "models",
    "workspace/mlflow": "mlflow",
    "workspace/evaluations": "evaluations",
    "workspace/base-source-audit": "audits/base-source-audit",
    "workspace/review-environment": "audits/review-environment",
    "workspace/data-staging": "data-staging",
    "workspace/data-rebuild": "data-rebuild",
    "models/minicpm-v-4.5": "base-models/minicpmv4_5",
    "models/minicpmv4_5": "base-models/minicpmv4_5",
}

# P2 物理搬迁已完成，本集合必须保持为空；新增旧路径一律视为写回旧布局。
PENDING_PHYSICAL_MOVE: set[str] = set()

# 本地产物目录名。data 中的结构化记录入 Git；models 走既有规则，不在 T6 断言内。
FLATTENED_TOP_LEVEL = (
    "trains",
    "mlflow",
    "evaluations",
    "audits",
    "data-staging",
    "data-rebuild",
    "base-models/probe",
)


# --------------------------------------------------------------------------- #
# T1 旧物理目录不存在
# --------------------------------------------------------------------------- #

def test_t1_pending_physical_move_is_subset_of_mapping() -> None:
    """防集合腐烂：PENDING 集合里的每个旧路径都必须是映射表的键。"""
    unknown = sorted(PENDING_PHYSICAL_MOVE - set(LEGACY_TO_FLATTENED))
    assert unknown == [], (
        f"PENDING_PHYSICAL_MOVE 含映射表里不存在的旧路径：{unknown}；"
        "请先把它加进 LEGACY_TO_FLATTENED，或从集合移除"
    )


def test_t1_legacy_physical_paths_are_absent() -> None:
    """映射表里的旧物理路径必须全部不存在（无任何「待搬迁」例外）。"""
    still_present = [old for old in LEGACY_TO_FLATTENED if (REPO_ROOT / old).exists()]

    assert still_present == [], (
        f"旧路径仍存在，代码可能已写回旧布局：{still_present}；"
        f"新位置应分别是 "
        f"{[LEGACY_TO_FLATTENED[old] for old in still_present]}"
    )


def test_t1_workspace_root_directory_is_absent() -> None:
    """``workspace/`` 根段本身必须不存在（双端物理搬迁完成后的性质判据）。"""
    workspace_root = REPO_ROOT / "workspace"

    assert not workspace_root.exists(), (
        f"旧布局根目录仍存在：{workspace_root}；内容应已搬到顶层语义目录"
    )
    assert not workspace_root.is_symlink(), (
        f"旧布局根目录仍以符号链接形式存在：{workspace_root}；"
        "搬迁后不得留下任何 workspace 入口"
    )


def test_t1_pending_physical_move_must_stay_empty() -> None:
    """``PENDING_PHYSICAL_MOVE`` 必须为空：搬迁完成后旧路径不再有「待搬迁」例外。"""
    assert PENDING_PHYSICAL_MOVE == set(), (
        f"P2 已完成，PENDING_PHYSICAL_MOVE 必须为空，实际含 "
        f"{sorted(PENDING_PHYSICAL_MOVE)}；新增旧路径不得以「待搬迁」名义继续存在"
    )


# --------------------------------------------------------------------------- #
# T2 evaluations 布局
# --------------------------------------------------------------------------- #

def test_t2_workspace_evaluations_paths_are_absent() -> None:
    """evaluations 及其 staging 子目录不得位于 workspace/ 之下。"""
    under_workspace = REPO_ROOT / "workspace" / "evaluations"

    assert not under_workspace.exists(), (
        f"旧 evaluations 路径仍存在：{under_workspace}；应迁到 {REPO_ROOT / 'evaluations'}"
    )
    assert not (under_workspace / "staging").exists(), (
        f"旧 evaluations staging 路径仍存在：{under_workspace / 'staging'}；"
        "staging 应随 evaluations 一起迁到顶层"
    )


def test_t2_evaluations_lives_at_top_level_when_flattened() -> None:
    """``evaluations`` 只能落在顶层，且顶层落点若存在必须是目录。

    刻意不设「``trains`` / ``evaluations`` 是否已落盘」的门槛：本机搬迁后这些运行
    产物目录并不存在，任何这类门槛都会让本用例恒真空转。改用无条件性质断言，
    两种仓库形态（产物目录存在 / 不存在）都真实执行。
    """
    under_workspace = REPO_ROOT / "workspace" / "evaluations"
    top_level = REPO_ROOT / "evaluations"

    assert not under_workspace.exists(), (
        f"evaluations 不得位于 workspace/ 之下：{under_workspace}；"
        f"唯一合法落点是 {top_level}"
    )
    assert not top_level.is_file(), (
        f"顶层 evaluations 必须是目录（或不存在），不能是普通文件：{top_level}"
    )
    if top_level.exists():
        assert top_level.is_dir(), (
            f"顶层 evaluations 已存在但不是目录：{top_level}；"
            "evaluations 产物必须有明确的目录落点"
        )


# --------------------------------------------------------------------------- #
# T3 源码静态扫描
# --------------------------------------------------------------------------- #

_OLD_SEGMENTS = r"data|runs|models|mlflow|evaluations|data-staging|data-rebuild"

# 旧布局的三种写法：路径拼接（root / "workspace" / "mlflow"）、字符串前缀
# （"workspace/models/"）、裸路径片段（workspace/data-staging），以及把 workspace
# 直接当作路径根的孤立拼接（root = repo_root / "workspace"）。
_LEGACY_PATTERNS = (
    re.compile(rf"workspace[\"'\s/]*[/\"'\s]+(?:{_OLD_SEGMENTS})\b"),
    re.compile(rf"workspace\s*/\s*\"(?:{_OLD_SEGMENTS})\""),
    re.compile(r"/\s*[\"']workspace[\"']"),
)

# 显式排除的非搬迁对象：.compat/workspace 与 store/workspace/**。
_OUT_OF_SCOPE = re.compile(
    r"(?:\.compat|\bstore)[\"']?\s*[/\s]\s*[\"']?workspace"
)

ALLOW_MARKER = "layout-guard-allow"

# 豁免上限而非等值：备份包内部结构属于历史布局，只能就地标记，不能改写。
_BACKUP_MODULE = "versioning/backup.py"
_BACKUP_ALLOW_LIMIT = 8

# 豁免标记的唯一合法位置：备份包内部结构属于历史布局，只能就地标记、不得改写。
# 任何其它文件出现该标记即视为绕过护栏。
_BACKUP_PACK_STRUCTURE = "workspace/evaluations"

_SCAN_ROOTS = ("pipeline", "versioning", "finetune", "scripts", "delivery", "tests")
# 已知限制：扫描后缀不含 ``.md``，文档叙述里允许保留旧路径字面量（例如
# ``pipeline/scripts/diagnostics/SCRIPTS.md`` 中说明「失效路径」的段落）。
# ``models/`` 前缀不在 ``scripts/verify_design_facts.py --check-doc-paths``（该脚本已随 ``scripts/`` 按用户要求删除，不再在仓库内，当前无替代校验器）的判定范围内
# （该检查器只识别 ``docs`` / ``pipeline`` / ``finetune`` / ``versioning`` / ``tests`` /
# ``scripts`` / ``records`` 七类仓库内前缀），因此此处唯一兜底是 code review；
# ``docs/`` 另被 ``_SKIP_DIR_NAMES`` 整体跳过。刻意不把 ``.md`` 纳入扫描：文档
# 需要引用旧路径来解释「以前在哪」，纳入扫描只会逼出无意义的豁免条目。
#
# 已知限制：未跟踪的本地产物目录（``audits/``、``mlflow/``、``base-models/``、
# ``models/``）不在 ``_SCAN_ROOTS`` 内，扫描不覆盖——它们是运行产物而非源码 / 配置。
# 其中 ``audits/base-source-audit/**`` 保留历史审计产物的原文，仍含旧基座路径字面量
# （实扫命中 ``acquire.py``、``acquisition.json``、``build_origin_report.py``），属历史
# 记录，不回改。
_SCAN_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".toml"}
_SKIP_DIR_NAMES = {
    ".venv",
    "__pycache__",
    ".git",
    "docs",
    "records",
    "LlamaFactory",
    "workspace",
}


def _scanned_files() -> Iterator[Path]:
    """按 brief 范围枚举待扫描文件（返回相对仓库根的路径）。"""
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT)
            if any(part in _SKIP_DIR_NAMES for part in rel.parts):
                continue
            if path.resolve() == SELF:
                # 本文件持有旧路径字面量作为守卫数据，自我扫描无意义。
                continue
            yield rel

    for path in sorted(REPO_ROOT.iterdir()):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        if path.resolve() == SELF:
            continue
        yield path.relative_to(REPO_ROOT)


def _legacy_reference_violations() -> list[tuple[str, int, str]]:
    """返回豁免后仍命中旧布局字面量的 (相对路径, 行号, 行文本)。"""
    violations: list[tuple[str, int, str]] = []
    for rel in _scanned_files():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            if _OUT_OF_SCOPE.search(line):
                continue
            if any(pattern.search(line) for pattern in _LEGACY_PATTERNS):
                violations.append((str(rel), lineno, line.strip()))
    return violations


def test_t3_no_legacy_workspace_literals_in_sources() -> None:
    """源码 / 配置 / 测试中不得再出现旧 workspace 布局字面量。"""
    violations = _legacy_reference_violations()
    preview = "\n".join(f"{rel}:{lineno}: {line}" for rel, lineno, line in violations[:20])

    assert violations == [], (
        f"发现 {len(violations)} 处仍引用旧 workspace/ 布局（该目录在迁移后不存在）。\n"
        "只有 versioning/backup.py 的「备份包内结构」行可用 layout-guard-allow 豁免。\n"
        f"前 20 条：\n{preview}"
    )


def _allow_marker_occurrences() -> list[tuple[str, int, str]]:
    """枚举扫描范围内带豁免标记的 (相对路径, 行号, 行文本)。"""
    occurrences: list[tuple[str, int, str]] = []
    for rel in _scanned_files():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                occurrences.append((str(rel), lineno, line.strip()))
    return occurrences


def test_t3_allow_marker_appears_only_in_backup_module() -> None:
    """豁免标记只允许出现在 versioning/backup.py，其它文件出现即视为滥用。"""
    offenders = [
        (rel, lineno, line)
        for rel, lineno, line in _allow_marker_occurrences()
        if rel != _BACKUP_MODULE
    ]
    detail = "\n".join(f"{rel}:{lineno}: {line}" for rel, lineno, line in offenders)

    assert offenders == [], (
        f"豁免标记 {ALLOW_MARKER} 只允许出现在 {_BACKUP_MODULE}，"
        f"但有 {len(offenders)} 处出现在其它文件：\n{detail}\n"
        "布局语义必须真正迁移，不能靠豁免绕过"
    )


def test_t3_backup_allow_marker_only_guards_pack_structure() -> None:
    """backup.py 里被标记的行必须同时含 workspace/evaluations（备份包内结构）。"""
    backup = REPO_ROOT / _BACKUP_MODULE
    if not backup.is_file():  # 不 skip：备份包结构豁免的载体不见了应显式失败
        pytest.fail(f"{_BACKUP_MODULE} 不存在，无法校验 {ALLOW_MARKER} 的适用范围")

    marked_lines = backup.read_text(encoding="utf-8").splitlines()
    misplaced = [
        (lineno, line.strip())
        for lineno, line in enumerate(marked_lines, 1)
        if ALLOW_MARKER in line and _BACKUP_PACK_STRUCTURE not in line
    ]
    detail = "\n".join(f"{_BACKUP_MODULE}:{lineno}: {line}" for lineno, line in misplaced)

    assert misplaced == [], (
        f"{_BACKUP_MODULE} 中被标记的行必须同时含 {_BACKUP_PACK_STRUCTURE!r}"
        f"（豁免只保护备份包内结构），但有 {len(misplaced)} 行不含：\n{detail}"
    )


def test_t3_backup_allow_marker_count_is_within_limit() -> None:
    """backup.py 的豁免行数不得超过上限（性质型上限，不作等值断言）。"""
    backup = REPO_ROOT / _BACKUP_MODULE
    if not backup.is_file():  # 不 skip：备份包结构豁免的载体不见了应显式失败
        pytest.fail(f"{_BACKUP_MODULE} 不存在，无法统计 {ALLOW_MARKER}")

    backup_marked = sum(
        1
        for line in backup.read_text(encoding="utf-8").splitlines()
        if ALLOW_MARKER in line
    )

    assert backup_marked <= _BACKUP_ALLOW_LIMIT, (
        f"{_BACKUP_MODULE} 中有 {backup_marked} 行带 {ALLOW_MARKER}，"
        f"超过上限 {_BACKUP_ALLOW_LIMIT}；豁免只能覆盖历史备份包内部布局"
    )


# --------------------------------------------------------------------------- #
# T3 旧基座路径（models/minicpm-v-4.5 / models/minicpmv4_5 -> base-models/minicpmv4_5）
# --------------------------------------------------------------------------- #

_BASE_MODEL_NAMES = r"minicpm-v-4\.5|minicpmv4_5"

# 旧基座路径的斜杠连写字面量。三处边界都是必要的，缺一项就会误报或漏报：
# * 名字前不得是路径名 / 盘符字符 [\w:-]：排除 base-models/ 与 ../base-models/
#   （被 - 挡住），也排除 ``"minicpmv4_5:models/minicpm-v-4.5:max_frames=8"`` 这类指纹
#   标签串——那里的 : 是无空白字段分隔符，不是路径分隔符，标签值不做磁盘访问。
# * 名字后不得是名字字符 [\w.-]：排除 models/minicpmv4_5.bak 这类其它文件名。
# * 要求 models/ 与名字斜杠连写：models/releases/minicpmv4_5（新布局）与
#   Path("models", "minicpmv4_5") 这类分段构造都不命中（与 T3 已知限制一致）。
_LEGACY_BASE_MODEL_PATTERNS = (
    re.compile(rf"(?<![\w:-])models/(?:{_BASE_MODEL_NAMES})(?![\w.-])"),
)

# (相对路径, 行内唯一片段, 理由)：正则边界无法结构性排除、但确认不是真实旧路径引用的
# 历史 / 测试夹具内容。**当前为空**：两条历史夹具（``tests/test_frame_contract.py``
# 与 ``tests/versioning/test_migration.py``）已改指 ``base-models/minicpmv4_5``，
# 不再需要豁免。机制保留只为将来真有不可迁移的历史夹具时逐条登记；空集本身由
# ``test_t3_base_model_allowlist_*`` 显式断言，不会静默变成空转。
_BASE_MODEL_ALLOWLIST: tuple[tuple[str, str, str], ...] = ()

# 性质型上限而非等值：豁免只服务确有不可迁移理由的历史夹具，不得随需求增长。
_BASE_MODEL_ALLOW_LIMIT = 3


def _matches_legacy_base_model(line: str) -> bool:
    """判断单行是否含旧基座路径字面量（守卫与自证用例共用同一判据）。"""
    return any(pattern.search(line) for pattern in _LEGACY_BASE_MODEL_PATTERNS)


def _base_model_allowlisted(rel: str, line: str) -> bool:
    """该行是否被某条 (相对路径, 行内唯一片段) 豁免命中。

    豁免必须精确到「整行只有这一处命中」：把片段本身剔除后，剩余文本不得
    再命中检测——否则同一行里的第二处旧路径会被一起豁免（片段成了让整行
    放行的通行证）。
    """
    return any(
        rel == allow_rel
        and fragment in line
        and not _matches_legacy_base_model(line.replace(fragment, "", 1))
        for allow_rel, fragment, _reason in _BASE_MODEL_ALLOWLIST
    )


def _base_model_reference_violations() -> list[tuple[str, int, str]]:
    """返回豁免后仍命中旧基座路径字面量的 (相对路径, 行号, 行文本)。"""
    violations: list[tuple[str, int, str]] = []
    for rel in _scanned_files():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _base_model_allowlisted(str(rel), line):
                continue
            if _matches_legacy_base_model(line):
                violations.append((str(rel), lineno, line.strip()))
    return violations


def test_t3_no_legacy_base_model_literals_in_sources() -> None:
    """源码 / 配置 / 测试中不得再出现 models/ 前缀的旧基座路径字面量。"""
    violations = _base_model_reference_violations()
    preview = "\n".join(f"{rel}:{lineno}: {line}" for rel, lineno, line in violations[:20])

    assert violations == [], (
        f"发现 {len(violations)} 处仍引用旧基座路径（P2 后该位置不存在）。\n"
        "新位置是 base-models/minicpmv4_5，请改指新路径；"
        "_BASE_MODEL_ALLOWLIST 只登记历史夹具，"
        "不能用于绕过迁移。\n"
        f"前 20 条：\n{preview}"
    )


def test_t3_base_model_detector_matches_legacy_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """自证检测能力：正例必须命中、反例必须不命中（防止护栏空转）。"""
    positives = (
        'BASE = ROOT / "models/minicpm-v-4.5"',
        'parser.add_argument("--model", default="models/minicpmv4_5")',
    )
    negatives = (
        '"base-models/minicpmv4_5"',
        '"../base-models/minicpmv4_5"',
        '"models/releases/minicpmv4_5"',
        '"model_version": "minicpm-v-4.5"',
        # 指纹标签串：: 紧邻形态由前边界结构性排除，不需要 allowlist。
        '"processor_fingerprint": "minicpmv4_5:models/minicpm-v-4.5:max_frames=8",',
    )

    assert _LEGACY_BASE_MODEL_PATTERNS, (
        "_LEGACY_BASE_MODEL_PATTERNS 为空，旧基座路径守卫会恒真"
    )
    missed = [line for line in positives if not _matches_legacy_base_model(line)]
    false_hits = [line for line in negatives if _matches_legacy_base_model(line)]

    assert missed == [], f"这些正例（旧基座路径字面量）未被检测到：{missed}"
    assert false_hits == [], f"这些反例（新布局 / 裸名字）被误报：{false_hits}"

    # 遮蔽自证：allowlist 只豁免片段本身，同一行里的第二处旧路径不得被连带
    # 豁免（否则一条豁免可以让整行放行）。真实 allowlist 已空，因此用 monkeypatch
    # 临时注入一条只认本自证片段的豁免，让豁免分支真实执行——不得因为空集就
    # 删掉这条自证。
    allow_rel = "tests/test_frame_contract.py"
    allow_fragment = (
        'MiniCPMVideoPreprocessor("models/minicpmv4_5", processor=processor)'
    )
    monkeypatch.setattr(
        f"{__name__}._BASE_MODEL_ALLOWLIST",
        ((allow_rel, allow_fragment, "遮蔽自证临时条目（非真实豁免）"),),
    )

    # 正控：片段单独出现时豁免必须真的放行，否则下面「不得连带豁免」的断言
    # 可以因为豁免完全失效而恒真。
    assert _base_model_allowlisted(allow_rel, f"{allow_fragment}\n"), (
        "注入的豁免对单处命中必须放行，否则遮蔽自证失去对照：" f"{allow_fragment}"
    )

    masked = f'{allow_fragment}  # 另见 "models/minicpm-v-4.5"'
    assert _matches_legacy_base_model(masked), f"遮蔽用例本身必须命中检测：{masked}"
    assert not _base_model_allowlisted(allow_rel, masked), (
        "allowlist 片段命中即整行放行，掩盖了同一行里的第二处旧基座路径：" f"{masked}"
    )


def test_t3_base_model_allowlist_entries_still_match_single_host_line() -> None:
    """防 allowlist 腐烂：每条豁免必须仍能唯一命中宿主文件里的 1 行。

    当前无任何豁免，逐条校验没有主体，因此先显式断言空集（否则本用例会静默
    变成「看起来通过但什么都没查」）；将来新增条目的唯一性与存在性由下面
    的循环继续断言。
    """
    assert _BASE_MODEL_ALLOWLIST == (), (
        "当前不应保留旧基座路径豁免（历史夹具已改指 base-models/minicpmv4_5）；"
        f"新增豁免必须先证明它不是可迁移的旧布局引用，实际为 "
        f"{_BASE_MODEL_ALLOWLIST!r}"
    )

    missing: list[str] = []
    ambiguous: list[str] = []
    for rel, fragment, _reason in _BASE_MODEL_ALLOWLIST:
        path = REPO_ROOT / rel
        if not path.is_file():
            missing.append(f"{rel}: 宿主文件不存在（片段 {fragment!r}）")
            continue
        hits = [
            lineno
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            )
            if fragment in line
        ]
        if not hits:
            missing.append(f"{rel}: 找不到含片段 {fragment!r} 的行")
        elif len(hits) > 1:
            ambiguous.append(f"{rel}: 片段 {fragment!r} 命中 {len(hits)} 行 {hits}")

    assert missing == [], (
        f"{len(missing)} 条豁免已失效（宿主文件里不再有对应行），请删除或修正：\n"
        + "\n".join(missing)
    )
    assert ambiguous == [], (
        "这些豁免片段在宿主文件里命中多行，无法精确定位到单行（一条豁免可能掩盖多处）：\n"
        + "\n".join(ambiguous)
    )


def test_t3_base_model_guard_flags_legacy_and_passes_new_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端到端正例：枚举 -> 检测 -> 豁免跳过 整链在临时仓库根上真跑。

    只替换 ``_scanned_files`` 与 ``REPO_ROOT``：前者给出待扫文件清单，后者
    决定 ``(REPO_ROOT / rel).read_text()`` 读到的是夹具文件；扫描枚举本身由
    全仓实扫覆盖，此处不重复枚举逻辑。第三段再把 ``_BASE_MODEL_ALLOWLIST``
    换成只认夹具文件的单个条目，让「片段命中即放行」的豁免分支也在同一条链路上
    真实执行。
    """
    monkeypatch.setattr(f"{__name__}._scanned_files", lambda: [Path("bad_case.py")])
    monkeypatch.setattr(f"{__name__}.REPO_ROOT", tmp_path)
    fixture = tmp_path / "bad_case.py"

    fixture.write_text('BASE = ROOT / "models/minicpmv4_5"\n', encoding="utf-8")
    violations = _base_model_reference_violations()
    assert violations == [("bad_case.py", 1, 'BASE = ROOT / "models/minicpmv4_5"')], (
        "端到端扫描必须在夹具文件里报出旧基座路径（路径 / 行号 / 行文本）："
        f"实际 {violations!r}"
    )

    fixture.write_text('BASE = ROOT / "base-models/minicpmv4_5"\n', encoding="utf-8")
    violations = _base_model_reference_violations()
    assert violations == [], (
        "端到端扫描不得把新布局 base-models/minicpmv4_5 报成违规："
        f"实际 {violations!r}"
    )

    # 第三段：豁免分支。把 allowlist 换成只认夹具文件的条目，同一行命中片段后
    # 整行放行。setattr 目标用字符串形式，避免在模块顶部新增 import（import 会插到
    # 映射表之前，而映射表里 `models/minicpm-v-4.5` 那一行是 design-facts 的
    # evidence 锚点）。
    allow_fragment = 'MiniCPMVideoPreprocessor("models/minicpm-v-4.5", processor=processor)'
    monkeypatch.setattr(
        f"{__name__}._BASE_MODEL_ALLOWLIST",
        (("bad_case.py", allow_fragment, "端到端夹具：豁免分支自证"),),
    )
    fixture.write_text(f"{allow_fragment}\n", encoding="utf-8")
    violations = _base_model_reference_violations()
    assert violations == [], (
        "端到端扫描必须按 allowlist 放行夹具文件里的已登记片段："
        f"实际 {violations!r}"
    )


def test_t3_base_model_allowlist_count_is_within_limit() -> None:
    """豁免条数不得超过上限，且当前为空（性质型上限，不作等值断言）。"""
    count = len(_BASE_MODEL_ALLOWLIST)

    assert not _BASE_MODEL_ALLOWLIST, (
        "当前无豁免条目，实际为 " f"{_BASE_MODEL_ALLOWLIST!r}"
    )
    assert count <= _BASE_MODEL_ALLOW_LIMIT, (
        f"_BASE_MODEL_ALLOWLIST 有 {count} 条，超过上限 {_BASE_MODEL_ALLOW_LIMIT}；"
        "豁免只覆盖历史夹具，新增代码必须直接改指 base-models/minicpmv4_5"
    )


# --------------------------------------------------------------------------- #
# T4 project_workspace_paths 语义
# --------------------------------------------------------------------------- #

def test_t4_workspace_root_is_repository_root(tmp_path: Path) -> None:
    """项目根即 workspace 根，路径里不再有 workspace 段。"""
    paths = project_workspace_paths(tmp_path)

    assert paths.root == tmp_path.resolve()


def test_t4_children_are_not_nested_under_workspace(tmp_path: Path) -> None:
    """data / runs / models 等子路径的首段都不是 workspace。"""
    paths = project_workspace_paths(tmp_path)
    repo_root = tmp_path.resolve()
    nested = {
        name: str(getattr(paths, name))
        for name in (
            "data",
            "runs",
            "models",
            "model_releases",
            "model_archive",
        )
        if getattr(paths, name).relative_to(repo_root).parts[0] == "workspace"
    }

    assert nested == {}, f"这些路径仍落在 workspace 下：{nested}"


def test_t4_child_directory_names_follow_flattened_layout(tmp_path: Path) -> None:
    """子目录名与顶层语义目录一致（runs -> trains）。"""
    paths = project_workspace_paths(tmp_path)

    assert paths.runs.name == "trains"
    assert paths.data.name == "data"
    assert paths.models.name == "models"
    assert paths.model_releases.name == "releases"


def test_t4_experiment_run_dir_lands_in_trains(tmp_path: Path) -> None:
    """实验运行目录首段是 trains。"""
    paths = experiment_workspace_paths(tmp_path, "v4.1-x-v1-seed1")

    assert paths.run_dir.relative_to(tmp_path.resolve()).parts[0] == "trains"


# --------------------------------------------------------------------------- #
# T5 git 跟踪
# --------------------------------------------------------------------------- #

def test_t5_flattened_paths_are_not_git_tracked() -> None:
    """训练、模型等本地产物不得被 Git 跟踪。"""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            "trains",
            "models",
            "mlflow",
            "evaluations",
            "audits",
            "data-staging",
            "data-rebuild",
            "base-models",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "", (
        f"新布局目录下有被 git 跟踪的文件：\n{result.stdout}"
    )


def test_t5_data_media_and_runtime_lock_are_not_git_tracked() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "data"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    media_extensions = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
    unexpected = [
        name for name in result.stdout.split("\0") if name
        and (Path(name).suffix.lower() in media_extensions
             or name == "data/roi/.roi.lock")
    ]
    assert unexpected == [], f"视频或运行锁不应被 Git 跟踪：{unexpected}"


# --------------------------------------------------------------------------- #
# T6 gitignore 覆盖
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", FLATTENED_TOP_LEVEL)
def test_t6_gitignore_covers_flattened_path(path: str) -> None:
    """新布局目录必须被 .gitignore 覆盖。"""
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f".gitignore 未覆盖新布局路径 {path!r}（git check-ignore 返回 "
        f"{result.returncode}）"
    )


@pytest.mark.parametrize("path", (
    "data/annotation-table-full.csv",
    "data/split-inputs/source-groups-20261107.json",
    "data/splits/three-fold/test.json",
    "data/splits/three-fold/fold_0_train.json",
    "data/splits/three-fold/manifest.json",
    "data/roi/decisions.json",
    "data/roi/manifest.json",
    "data/roi/label_reviews.json",
))
def test_t6_data_records_are_not_ignored(path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"标注、划分与 ROI 记录应允许进入 Git：{path!r}；{result.stderr}"
    )


@pytest.mark.parametrize("extension", ("mp4", "mov", "mkv", "avi", "m4v", "webm"))
@pytest.mark.parametrize("uppercase", (False, True))
def test_t6_data_video_formats_are_ignored(extension: str, uppercase: bool) -> None:
    suffix = extension.upper() if uppercase else extension
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", f"data/roi/videos/probe.{suffix}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"视频应被忽略：{suffix}；{result.stderr}"
