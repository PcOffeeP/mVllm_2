"""迁移只读预检测试 — T1 ready 正向切片 + T2 fail-closed blocked 反向切片。

契约来源：
- Plan docs/tasks/2026-09-07-readable-version-control-migration/plan.md（M1）：
  新增迁移模块 ``versioning/migration.py``，显式区分只读预检与真实转换；
  先验证映射、引用和全部必需文件，再向独立目标写入；不得在旧目录原地转换。
- Spec 同目录 spec.md「正式写入与失败恢复」：转换/切换前确认输入引用完整、
  语义一致；同一目标身份冲突时停止，不覆盖、不自动改号。
- M0 证据 docs/results/version-control-migration/object-mapping.yaml
  （prompt_mapping.items 中 status: user_confirmed 的已确认条目，用户 2026-09-07 确认）
  与同目录 source-inventory.yaml（pipeline_prompt_registry：
  ``pipeline/prompt_registry/<source_id>/{manifest.json,prompt.yaml}``；
  本机 <root>/records 不存在 → 无目标冲突）。
- 根 AGENTS.md 新体系规则：versioning 只接受 ``<kind>-v<协议>-r<N>`` 完整身份，
  fail-closed；禁止旧哈希身份、LATEST、短哈希前缀与隐式最新。
- 既有目标侧契约 versioning/prompts.py：正式位置为
  ``<root>/records/prompts/prompt-v4.1-r1.yaml``（prompt_path）。

当前 behavior（T1 最小切面，主 Agent 选定）：
对已确认 Prompt 映射 ``v4.1-concise-evidence-json-v2`` -> ``prompt-v4.1-r1``
执行只读迁移预检时，应返回 ``ready``，并且：
- 目标根 ``<root>/records`` 零写入（不创建 records/prompts/、staging 或任何目标条目）；
- legacy 源树逐字节不变。

T2 behavior（本切片，主 Agent 选定）—— 只读预检必须 fail-closed：
对不合格输入返回 ``blocked``（报告携带非空 reasons），且目标根零写入、
legacy 源零改动。blocked 结论必须经与 T1 相同的报告返回通道给出，
不得以未类型化异常替代（报告通道已被 T1 绑定）。四类场景（各取代表例）：
1. 映射 ``status`` 不是 ``user_confirmed``：pending_user_check / unknown /
   verified_local（source_verified 的事实分级误当确认门槛）/ status 字段缺失
   —— M0 status_field_legend 中 user_confirmed 是唯一"用户已逐项确认"口径；
2. 候选目标身份非法或禁用：legacy prompt 旧身份复用
   （v4.1-concise-evidence-json-v2）、全 40 位旧哈希、短哈希前缀、LATEST、
   前导零 revision（prompt-v4.1-r01；versioning/ids.py 权威规则要求
   revision 从 1 开始且无前导零）；
3. legacy 源必需文件缺失：manifest.json / prompt.yaml / 整个源条目
   （fixture 特意保留完整历史 sibling，钉死"扫错位置查文件/从 sibling
   补齐"两类错误实现）；
4. 目标已存在冲突：target_path 被既有正式对象占用，或 records/ 下已存在
   同身份条目（M0 global_pre_write_checks"不存在同名正式对象"逐个复验）；
   冲突只 blocked，不覆盖、不自动改号，不触发任何恢复/转换。

预期 production API（供实现对照，模块 ``versioning.migration``）::

    def precheck_prompt_migration(root: Path, mapping_item: Mapping[str, object]) -> object
        # mapping_item 为 object-mapping.yaml prompt_mapping.items 单条的解析结果；
        # 本用例逐字段镜像 M0 已确认条目（含 status: "user_confirmed"），
        # 使"映射项已确认"的判定必须由该入口自身读取 status 字段完成
        # （不得由调用方预过滤成布尔标志，否则配套的 pending 拒绝切片无法绑定同一入口）。
        # 只读预检：校验映射项与目标身份合法性、定位 legacy 源必需文件
        #   （pipeline/prompt_registry/<source_legacy_id>/{manifest.json,prompt.yaml}）、
        #   检查目标无冲突，返回带 ``status`` 属性的只读报告对象；
        #   确认映射 + 源必需文件齐全 + 目标无冲突 -> status == "ready"。
        # 预检全程零写入：不创建 records/、records/prompts/、staging 或任何目标条目，
        #   不改 legacy 源，不写任何报告/缓存文件（报告只经返回值给出）。
        # 本切片不要求预检复算 legacy prompt_content_sha256：
        #   内容保真校验（含哈希 recipe 定义）属于真实转换切片。
        # 预检不得把 pending/unknown 当 confirmed：该拒绝行为属于配套反向用例切片，
        #   本测试只喂入 status == "user_confirmed" 的映射项，不覆盖拒绝路径。

RED Gate 设计说明（本轮 TDD 约束）：
本文件编写时 ``versioning/migration.py`` 尚不存在。若在模块顶层
``import versioning.migration``，pytest 会在 collection 阶段以
ModuleNotFoundError 失败，测试体完全不执行——按本轮 RED Gate 限制，
原始 ImportError / ModuleNotFoundError 不能宣布为有效 RED。
因此本模块顶层不 import migration，而在测试体内用
``importlib.util.find_spec("versioning.migration")`` 惰性解析入口：
父包 versioning 已存在时，find_spec 对缺失子模块返回 None 而不抛错
（本机 Python 3.11.14 已验证）。入口缺失时由本测试的显式 AssertionError
钉出"只读预检行为缺失"：失败发生在 fixture 构建、前置事实断言与全树
快照真实执行之后，映射到当前 behavior 未实现，而非 import 机制错误。

范围边界：本文件只覆盖 Prompt 只读预检 —— T1 ready 正向最小切面、
T2 blocked 反向四类场景，以及 T3 目标冲突精确身份边界回归；不实现/
不要求真实转换、data 迁移、history-summary、CLI、恢复逻辑（冲突场景
只断言 blocked 与零写入，不断言任何恢复行为）。T2 身份场景只绑定
behavior 列举的禁用形式（旧哈希、LATEST、短哈希、前导零）；r0、
revision 上限、kind 限定为 prompt 等更细身份规则留给后续身份收紧切片。
T3（reviewer 对 2a927d14 的 P3 边界备注）：目标冲突检测必须按精确
身份判断 —— 已有 ``records/prompts/prompt-v4.1-r10.yaml``（不同身份，
字符串上以 ``prompt-v4.1-r1`` 为前缀）不得阻塞目标 ``prompt-v4.1-r1``
的只读预检；真正同身份的 records/ 下条目仍必须 blocked。T4（reviewer
对 F1 修复的 P2 回归）：同身份判定不得依赖 ``Path.stem`` ——
``stem == identity`` 只认标准单后缀 ``.yaml`` 形式，对同身份的无
扩展名（``prompt-v4.1-r1``）、备份后缀（``prompt-v4.1-r1.yaml.bak``）
与复合后缀（``prompt-v4.1-r1.tar.gz``）文件全部误放行；同身份必须
以任何文件形式 blocked，r10 同前缀邻居同时保持 ready。所有用例只在
pytest ``tmp_path`` 下模拟仓库根，不触碰真实 records/、workspace/、
pipeline/、finetune/；legacy 树为按 M0 证据布局重建的合成 fixture
（字段值合成、结构与事实字段对齐 M0 证据）。
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

CONFIRMED_PROMPT_SOURCE_ID = "v4.1-concise-evidence-json-v2"
CONFIRMED_PROMPT_TARGET_ID = "prompt-v4.1-r1"
# 不迁移的历史 sibling（M0：仅进入 history-summary），用于确保实现按映射项
# 定位源，而不是扫描整个 legacy registry。
HISTORY_SIBLING_SOURCE_ID = "v4.1-concise-evidence-json-v1"


def _legacy_prompt_yaml() -> bytes:
    """合成但 schema 对齐 M0 preserve_state 的 legacy prompt.yaml 字节。

    字段名取 object-mapping.yaml preserve_state（system_prompt /
    user_prompt / output_fields 逐字段一致）；output_fields 取
    finetune/README.md 记载的 v4.1 真实四字段。
    """
    return (
        "system_prompt: 你是判定材料拉伸断裂行为的视觉模型。\n"
        "user_prompt: 请逐字段输出 JSON 判定结果。\n"
        "output_fields:\n"
        "  - clip_state\n"
        "  - fracture_mechanism\n"
        "  - fracture_site\n"
        "  - special_case\n"
    ).encode("utf-8")


def _write_legacy_prompt_registry(root: Path) -> Path:
    """在模拟仓库根下按 M0 证据布局构建 legacy Prompt registry。

    镜像 source-inventory.yaml pipeline_prompt_registry：每个
    ``<source_id>/`` 下恰有 manifest.json 与 prompt.yaml。
    manifest 字段名与事实字段对齐 source-inventory manifest_facts；
    prompt_content_sha256 按 fixture 自身 prompt.yaml 字节计算以保持自洽
    （真实值见 M0 证据；本切片不要求实现复算该哈希）。
    """
    registry = root / "pipeline" / "prompt_registry"
    prompt_bytes = _legacy_prompt_yaml()
    source_commits = {
        CONFIRMED_PROMPT_SOURCE_ID: "98f0476d50138a7577e65426338a44a1baaec040",
        HISTORY_SIBLING_SOURCE_ID: "4c56f7c958b830e43e301739aa4d71b2eb1c1f99",
    }
    for source_id, publishing_commit in source_commits.items():
        entry = registry / source_id
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "prompt.yaml").write_bytes(prompt_bytes)
        manifest = {
            "protocol_id": "tensile-vlm/v4.1",
            "prompt_content_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "publishing_code_commit": publishing_commit,
        }
        (entry / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return registry / CONFIRMED_PROMPT_SOURCE_ID


def _confirmed_prompt_mapping_item() -> dict[str, Any]:
    """逐字段镜像 M0 object-mapping.yaml prompt_mapping.items 的已确认条目。

    YAML 标量解析为字符串（status: user_confirmed -> "user_confirmed"），
    字段集与值与 M0 证据保持一致，使实现必须按真实证据结构消费映射项。
    """
    return {
        "source_legacy_id": CONFIRMED_PROMPT_SOURCE_ID,
        "role": "当前活动 Prompt（活动指针，本地与训练机一致）",
        "source_verified": "verified_local",
        "candidate_target_identity": CONFIRMED_PROMPT_TARGET_ID,
        "target_path": "records/prompts/prompt-v4.1-r1.yaml",
        "status": "user_confirmed",
        "confirmed_by_user_date": "2026-09-07",
        "conflict_check": "本机 <root>/records 不存在 → 当前无目标冲突",
        "preserve_state": [
            "system_prompt / user_prompt / output_fields 逐字段一致",
            "源 manifest 中 prompt_content_sha256 / publishing_code_commit "
            "记录进 history-summary",
        ],
        "notes": "最可能为 M1 迁移的'一版 Prompt'，但需用户确认"
        "（不能由活动指针推断历史训练输入）。",
    }


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    """以相对路径 -> 字节的方式快照整个 root 树（目录记为 b"<dir>"）。

    覆盖任何新增/删除/修改：目标根 records/、staging 目录、legacy 源文件
    字节均包含在内，构成"只读预检零写入"的完整判定。
    """
    snapshot: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[rel] = f"<symlink:{path.readlink()}>".encode("utf-8")
        elif path.is_dir():
            snapshot[rel] = b"<dir>"
        else:
            snapshot[rel] = path.read_bytes()
    return snapshot


def _resolve_precheck_entry() -> Any:
    """惰性解析只读预检入口；模块或入口缺失时返回 None。

    RED Gate 设计：不让 import 机制抛 ModuleNotFoundError（无效 RED），
    由调用方以显式行为断言钉出"只读预检行为缺失"。
    """
    spec = importlib.util.find_spec("versioning.migration")
    if spec is None:
        return None
    module = importlib.import_module("versioning.migration")
    return getattr(module, "precheck_prompt_migration", None)


def test_confirmed_prompt_mapping_precheck_returns_ready_without_writes(
    tmp_path: Path,
) -> None:
    """已确认 Prompt 映射的只读预检：ready + 目标根零写入 + 源逐字节不变。

    捕获的合理但错误实现（正向最小切面内可观察的部分）：
    - 预检时创建目标目录/文件（records/、records/prompts/、目标条目）
      -> 目标根存在性断言 + 全树快照对比失败；
    - 预检时建 staging 或写任何报告/缓存文件 -> 全树快照对比失败；
    - 预检时改写/规范化 legacy 源 -> 全树快照对比失败（逐字节）；
    - 预检即真实转换（写入正式 prompt 文件）-> 同上；
    - 对合法已确认输入 fail-closed（返回非 ready 或抛错）-> status 断言失败；
    - 不接受 M0 证据结构的映射项（期望别的输入形状）-> 调用即失败。
    pending/unknown 被当 confirmed 的错误在本正向输入下不可观察，
    由配套反向用例切片钉定（见模块 docstring 范围边界）。
    """
    source_entry = _write_legacy_prompt_registry(tmp_path)

    # fixture 前置事实（对齐 M0 证据）：源必需文件存在；目标根不存在。
    assert (source_entry / "manifest.json").is_file()
    assert (source_entry / "prompt.yaml").is_file()
    assert not (tmp_path / "records").exists()

    before = _snapshot_tree(tmp_path)

    precheck = _resolve_precheck_entry()
    assert precheck is not None, (
        "只读 Prompt 迁移预检行为缺失：versioning.migration 未提供 "
        "precheck_prompt_migration 入口（当前 behavior 未实现）"
    )

    report = precheck(tmp_path, _confirmed_prompt_mapping_item())

    assert report.status == "ready"

    # 目标根零写入：records/ 仍不存在（未创建 records/prompts/ 或任何目标条目）。
    assert not (tmp_path / "records").exists()
    # legacy 源逐字节不变 + 全树零写入（无 staging、无任何新增/修改/删除）。
    assert _snapshot_tree(tmp_path) == before


# ---------------------------------------------------------------------------
# T2：fail-closed —— 不合格输入的只读预检必须 blocked 且零写入
# ---------------------------------------------------------------------------

# 冲突场景中既有正式对象的哨兵字节：预检不得覆盖、改名、删除或追加。
_EXISTING_TARGET_BYTES = b"<existing formal prompt object: must not be touched>"

# blocked 报告必须携带非空 reasons：fail-closed 拒绝必须经返回值给出可读
# 拒因（明确域错误通道），调用方才能区分“为什么被拒”；不得静默 blocked。
_BLOCKED_REASONS_REQUIRED_MSG = (
    "blocked 报告必须携带非空 reasons：fail-closed 拒绝必须经返回值给出"
    "可读拒因（明确域错误通道），不得静默 blocked"
)


def _run_blocked_precheck(root: Path, mapping_item: dict[str, Any]) -> Any:
    """执行只读预检并断言 fail-closed 通道：status == blocked + 非空 reasons。

    blocked 结论必须经与 T1 相同的报告返回通道给出；以未类型化异常替代
    报告会破坏 T1 已绑定的返回契约，由本断言（或异常直接传播）判失败。
    """
    precheck = _resolve_precheck_entry()
    assert precheck is not None, (
        "只读 Prompt 迁移预检行为缺失：versioning.migration 未提供 "
        "precheck_prompt_migration 入口（当前 behavior 未实现）"
    )
    report = precheck(root, mapping_item)
    assert report.status == "blocked", (
        f"不合格输入必须 fail-closed 返回 blocked：实际 status={report.status!r}"
    )
    assert report.reasons, _BLOCKED_REASONS_REQUIRED_MSG
    return report


@pytest.mark.parametrize(
    "bad_status",
    [
        pytest.param("pending_user_check", id="pending_user_check"),
        pytest.param("unknown", id="unknown"),
        pytest.param("verified_local", id="verified_local_mistaken_as_confirmation"),
        pytest.param(None, id="status_field_missing"),
    ],
)
def test_precheck_blocks_unconfirmed_mapping_status(
    tmp_path: Path, bad_status: object
) -> None:
    """映射 status 不是 user_confirmed -> blocked + 零写入（fail-closed）。

    M0 object-mapping.yaml status_field_legend：user_confirmed 是唯一
    "用户已逐项确认、可作 M1 固定验收输入"的状态；pending_user_check
    "未生效，禁止写入"；unknown 属"已知缺失"；verified_local 只是
    source_verified 的事实分级，不是确认门槛。

    捕获的合理但错误实现：
    - 黑名单式校验（只拒已知 pending 值、其余一律放行）-> unknown /
      verified_local / status_field_missing 参数失败；合法实现必须白名单
      式只认 user_confirmed；
    - 把 source_verified 的 verified_local 误当确认状态 ->
      verified_local_mistaken_as_confirmation 参数失败；
    - status 字段缺失时默认放行 -> status_field_missing 参数失败；
    - 预检根本不读 status 字段 -> 全部参数失败；
    - 拒绝时抛异常替代报告 -> T1 已绑定报告返回通道，本用例判失败；
    - blocked 不带 reasons（调用方无从得知拒因）-> reasons 断言失败；
    - 被拒时仍创建 records/ 或改写 legacy 源 -> 零写入断言失败。
    除 status 外其余字段保持 T1 的合法取值，使 blocked 只能由确认状态
    引起（隔离变量）。
    """
    _write_legacy_prompt_registry(tmp_path)
    mapping_item = _confirmed_prompt_mapping_item()
    if bad_status is None:
        del mapping_item["status"]
    else:
        mapping_item["status"] = bad_status

    assert not (tmp_path / "records").exists()
    before = _snapshot_tree(tmp_path)

    _run_blocked_precheck(tmp_path, mapping_item)

    assert not (tmp_path / "records").exists()
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    "bad_identity",
    [
        pytest.param(CONFIRMED_PROMPT_SOURCE_ID, id="legacy_prompt_old_identity"),
        pytest.param(
            "98f0476d50138a7577e65426338a44a1baaec040", id="full_old_hash"
        ),
        pytest.param("98f0476", id="short_hash_prefix"),
        pytest.param("LATEST", id="latest_pointer"),
        pytest.param("prompt-v4.1-r01", id="leading_zero_revision"),
    ],
)
def test_precheck_blocks_forbidden_target_identity(
    tmp_path: Path, bad_identity: str
) -> None:
    r"""候选目标身份非法或禁用形式 -> blocked + 零写入（fail-closed）。

    身份口径：根 AGENTS.md 只接受五类完整 ``<kind>-v<协议>-r<N>`` 身份，
    禁止旧哈希身份、LATEST、短哈希前缀与隐式最新；versioning/ids.py 的
    权威正则要求 revision 为 ``[1-9]\d*``（从 1 开始、无前导零），因此
    ``prompt-v4.1-r01`` 不是合法完整身份。

    代表例（target_path 保持合法，使 blocked 只能由身份字段引起）：
    - legacy_prompt_old_identity：legacy prompt 旧身份（v<协议>-<描述>-r<N>，
      即 source_legacy_id）直接复用作目标 —— 最 plausible 的映射填写错误；
    - full_old_hash / short_hash_prefix：全旧哈希与短哈希前缀；
    - latest_pointer：LATEST / 隐式最新指针；
    - leading_zero_revision：前导零 revision（r01）。

    捕获的合理但错误实现：
    - 不读 candidate_target_identity、从 target_path 文件名反推身份 ->
      本用例 target_path 合法而身份字段被替换，反推实现误返回 ready；
    - "形似版本号即放行"的宽松校验（接受前导零 r01）->
      leading_zero_revision 参数失败；
    - 接受 legacy <协议>-<描述>-r<N> 旧身份当新完整身份 ->
      legacy_prompt_old_identity 参数失败；
    - 接受旧哈希 / 短哈希 / LATEST -> 对应参数失败；
    - 身份非法时"顺手规范化"（写入、改名或生成目标文件）->
      零写入断言失败；
    - blocked 不带 reasons -> reasons 断言失败。
    """
    _write_legacy_prompt_registry(tmp_path)
    mapping_item = _confirmed_prompt_mapping_item()
    mapping_item["candidate_target_identity"] = bad_identity

    assert not (tmp_path / "records").exists()
    before = _snapshot_tree(tmp_path)

    _run_blocked_precheck(tmp_path, mapping_item)

    assert not (tmp_path / "records").exists()
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    "missing",
    [
        pytest.param("manifest.json", id="manifest_missing"),
        pytest.param("prompt.yaml", id="prompt_yaml_missing"),
        pytest.param("entry", id="source_entry_missing"),
    ],
)
def test_precheck_blocks_missing_legacy_source_files(
    tmp_path: Path, missing: str
) -> None:
    """legacy 源必需文件缺失 -> blocked + 零写入（fail-closed）。

    M0 source-inventory.yaml 规定每个 prompt registry 条目必须
    ``<source_id>/{manifest.json,prompt.yaml}`` 齐全；缺失源不补造。
    fixture 特意保留完整的历史 sibling 条目（不迁移，仅进 history-summary），
    使"扫错位置查文件"与"从 sibling 复制补齐"的错误实现必被捕获。

    捕获的合理但错误实现：
    - 只查源目录存在、不查必需文件 -> manifest_missing /
      prompt_yaml_missing 参数失败；
    - 只查 manifest.json 不查 prompt.yaml（或反之）-> 对应单文件缺失
      参数失败；
    - 在错误位置查文件（registry 根 / glob 全树 / 指向 sibling）->
      目标源缺文件而 sibling 完整，扫错位置的实现误返回 ready；
    - 缺源时自动从 sibling 复制或重建源文件（伪造源、改 legacy 树）->
      零写入断言失败；
    - 缺文件时降级放行（"缺失只警告不阻塞"）-> status 断言失败；
    - blocked 不带 reasons -> reasons 断言失败。
    """
    source_entry = _write_legacy_prompt_registry(tmp_path)
    sibling_entry = (
        tmp_path / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    )
    if missing == "entry":
        shutil.rmtree(source_entry)
        assert not source_entry.exists()
    else:
        (source_entry / missing).unlink()
        assert not (source_entry / missing).is_file()
        other = "prompt.yaml" if missing == "manifest.json" else "manifest.json"
        assert (source_entry / other).is_file()

    # 前置事实：目标源缺必需文件，而 sibling 保持齐全（隔离错误定位）。
    assert (sibling_entry / "manifest.json").is_file()
    assert (sibling_entry / "prompt.yaml").is_file()
    assert not (tmp_path / "records").exists()

    before = _snapshot_tree(tmp_path)

    _run_blocked_precheck(tmp_path, _confirmed_prompt_mapping_item())

    assert not (tmp_path / "records").exists()
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    "conflict_kind",
    [
        pytest.param("target_path", id="target_path_occupied"),
        pytest.param("records_elsewhere", id="same_identity_in_records"),
    ],
)
def test_precheck_blocks_existing_target_conflict(
    tmp_path: Path, conflict_kind: str
) -> None:
    """目标已存在造成冲突 -> blocked + 既有正式对象逐字节保持。

    Spec「正式写入与失败恢复」：同一目标身份冲突时停止，不覆盖、不自动
    改号；M0 global_pre_write_checks：目标 <root>/records 写入前必须
    复验不存在同名正式对象。两个代表场景：
    - target_path_occupied：映射指定的目标文件位置被既有正式对象占用；
    - same_identity_in_records：target_path 空闲，但 records/ 下已存在
      同身份条目（防改名冲突，"不存在同名正式对象"逐个复验）。

    捕获的合理但错误实现：
    - 完全不做冲突检查 -> status 断言失败；
    - 只查 target_path、不查 records/ 下同身份条目 ->
      same_identity_in_records 参数失败；
    - 冲突时自动改号（r2）继续放行 -> status 断言失败（不得自动改号）；
    - 预检即开始转换：覆盖/改名/删除既有正式对象或新增任何文件 ->
      全树快照断言失败（既有对象哨兵字节保持原样）；
    - blocked 不带 reasons -> reasons 断言失败。
    """
    _write_legacy_prompt_registry(tmp_path)
    mapping_item = _confirmed_prompt_mapping_item()
    if conflict_kind == "target_path":
        occupied = tmp_path / str(mapping_item["target_path"])
    else:
        occupied = (
            tmp_path
            / "records"
            / "archive"
            / f"{CONFIRMED_PROMPT_TARGET_ID}.yaml"
        )
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(_EXISTING_TARGET_BYTES)

    # 前置事实：冲突对象存在；same_identity_in_records 场景下目标位置空闲。
    assert occupied.is_file()
    if conflict_kind == "records_elsewhere":
        assert not (tmp_path / str(mapping_item["target_path"])).exists()

    before = _snapshot_tree(tmp_path)

    _run_blocked_precheck(tmp_path, mapping_item)

    # 既有正式对象逐字节保持（不覆盖、不改名、不删除、不追加），全树零写入。
    assert occupied.read_bytes() == _EXISTING_TARGET_BYTES
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    ("existing_rel_path", "expected_status"),
    [
        pytest.param(
            "records/prompts/prompt-v4.1-r10.yaml",
            "ready",
            id="higher_revision_prefix_neighbor_not_conflict",
        ),
        pytest.param(
            "records/archive/prompt-v4.1-r1.yaml",
            "blocked",
            id="exact_same_identity_elsewhere_still_conflict",
        ),
    ],
)
def test_precheck_target_conflict_matches_exact_identity(
    tmp_path: Path, existing_rel_path: str, expected_status: str
) -> None:
    """目标冲突检测必须按精确身份判断（reviewer P3 边界回归，先写失败测试）。

    边界事实：``prompt-v4.1-r10`` 与 ``prompt-v4.1-r1`` 是两个不同身份
    （revision 10 ≠ 1，versioning/ids.py 权威解析口径），但字符串上
    ``prompt-v4.1-r1`` 恰是 ``prompt-v4.1-r10`` 的前缀（加一个 "0"）。
    两个场景的映射 target_path（records/prompts/prompt-v4.1-r1.yaml）
    均保持空闲，使预检结论只能由 records/ 下同身份条目扫描路径决定
    （隔离 target_path 占用分支）：
    - higher_revision_prefix_neighbor_not_conflict：已有
      ``records/prompts/prompt-v4.1-r10.yaml``（不同身份、同前缀邻居）
      -> 预检必须 ``ready``；
    - exact_same_identity_elsewhere_still_conflict：已有
      ``records/archive/prompt-v4.1-r1.yaml``（精确同身份，位于
      target_path 之外）-> 预检仍必须 ``blocked``（与 T2
      same_identity_in_records 同口径，钉死修复不得反向过宽）。

    捕获的合理但错误实现：
    - 前缀匹配判定同身份（rglob(f"{identity}*")，prompt-v4.1-r1*
      会命中 prompt-v4.1-r10.yaml / r11 / r100…）->
      higher_revision_prefix_neighbor_not_conflict 参数失败；
    - 修复反向过宽（不再扫描 records/ 下同身份条目，或把任何既有
      前缀邻居都放行、同身份也放行）->
      exact_same_identity_elsewhere_still_conflict 参数失败；
    - ready 场景下顺手创建目标/staging 条目 -> 全树快照断言失败；
    - blocked 场景下清理/改名/覆盖既有条目 -> 哨兵字节与全树快照
      断言失败；
    - blocked 不带 reasons -> reasons 断言失败。
    """
    _write_legacy_prompt_registry(tmp_path)
    mapping_item = _confirmed_prompt_mapping_item()
    occupied = tmp_path / existing_rel_path
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(_EXISTING_TARGET_BYTES)

    # 前置事实：既有条目存在；映射指定的 target_path 空闲（两场景同构，
    # 差异只在既有条目的身份是否精确等于目标身份）。
    assert occupied.is_file()
    assert not (tmp_path / str(mapping_item["target_path"])).exists()

    before = _snapshot_tree(tmp_path)

    precheck = _resolve_precheck_entry()
    assert precheck is not None, (
        "只读 Prompt 迁移预检行为缺失：versioning.migration 未提供 "
        "precheck_prompt_migration 入口（当前 behavior 未实现）"
    )
    report = precheck(tmp_path, mapping_item)

    if expected_status == "blocked":
        assert report.status == "blocked", (
            f"records/ 下已存在精确同身份条目，预检必须 fail-closed 返回 "
            f"blocked：实际 status={report.status!r}"
        )
        assert report.reasons, _BLOCKED_REASONS_REQUIRED_MSG
    else:
        assert report.status == "ready", (
            f"已有不同身份的同前缀邻居条目（revision 不同）不构成目标冲突，"
            f"预检应为 ready：实际 status={report.status!r}，"
            f"reasons={report.reasons!r}"
        )

    # 既有条目逐字节保持；全树零写入（ready 场景亦不得创建任何新条目）。
    assert occupied.read_bytes() == _EXISTING_TARGET_BYTES
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    ("existing_rel_path", "expected_status"),
    [
        pytest.param(
            "records/prompts/prompt-v4.1-r10.yaml",
            "ready",
            id="higher_revision_prefix_neighbor_still_ready",
        ),
        pytest.param(
            "records/archive/prompt-v4.1-r1",
            "blocked",
            id="same_identity_no_extension_blocked",
        ),
        pytest.param(
            "records/archive/prompt-v4.1-r1.yaml.bak",
            "blocked",
            id="same_identity_backup_extension_blocked",
        ),
        pytest.param(
            "records/archive/prompt-v4.1-r1.tar.gz",
            "blocked",
            id="same_identity_compound_extension_blocked",
        ),
    ],
)
def test_precheck_blocks_same_identity_nonstandard_file_forms(
    tmp_path: Path, existing_rel_path: str, expected_status: str
) -> None:
    """同身份非标准文件形式条目必须 blocked（F1 修复的 P2 回归，先写失败测试）。

    Reviewer 对 F1 修复（``existing.stem == identity`` 精确判定）的 P2
    回归证据（本机 venv Python 3.11.14 实测复核，结论与 reviewer 一致、
    stem 具体值以实测为准）：``Path.stem`` 只按最后一个点切割文件名 ——
    - ``Path('prompt-v4.1-r1').stem == 'prompt-v4'``（身份中 v4.1 的点
      使唯一“后缀”被解析为 ``'.1-r1'``，无扩展名文件的身份被截断）；
    - ``Path('prompt-v4.1-r1.yaml.bak').stem == 'prompt-v4.1-r1.yaml'``
      （stem 只剥离最后一个后缀 ``.bak``）；
    - ``Path('prompt-v4.1-r1.tar.gz').stem == 'prompt-v4.1-r1.tar'``
      （同上，只剥离 ``.gz``）。
    因此 ``stem == identity`` 对这三类“同身份、不同文件形式”全部误判
    为不同身份 -> 误放行。行为口径（与 T3 及 T2 same_identity_in_records
    同源，M0 global_pre_write_checks“不存在同名正式对象”逐个复验）：
    同身份不允许以任何文件形式占用 records/（防改名冲突），文件形式
    （无扩展名 / 备份后缀 / 复合后缀）不改变身份判定；r10 等 revision
    不同的同前缀邻居仍是不同身份，必须保持 ready（F1 修复成果不得被
    本切片反向回退）。

    四个场景（映射 target_path records/prompts/prompt-v4.1-r1.yaml 均
    保持空闲，使预检结论只能由 records/ 下同身份条目扫描路径决定，
    隔离 target_path 占用分支）：
    - higher_revision_prefix_neighbor_still_ready：已有
      ``records/prompts/prompt-v4.1-r10.yaml`` -> ready；
    - same_identity_no_extension_blocked：已有
      ``records/archive/prompt-v4.1-r1``（无扩展名）-> blocked；
    - same_identity_backup_extension_blocked：已有
      ``records/archive/prompt-v4.1-r1.yaml.bak`` -> blocked；
    - same_identity_compound_extension_blocked：已有
      ``records/archive/prompt-v4.1-r1.tar.gz`` -> blocked。

    捕获的合理但错误实现：
    - 沿用 ``existing.stem == identity``（只认标准单后缀 .yaml 形式）
      -> 三个 blocked 参数全部失败（stem 被点号切割后 != identity）；
    - 只比较整文件名 == identity（无扩展名形式反而通过、标准 .yaml
      形式误放行）-> 与 T3 exact_same_identity_elsewhere_still_conflict
      联合捕获两类形式；
    - 修复反向过宽：为覆盖非标准形式退回前缀匹配
      （rglob(f"{identity}*")，会命中 prompt-v4.1-r10.yaml / r11…）->
      higher_revision_prefix_neighbor_still_ready 参数失败（F1 回归
      重演）；
    - ready 场景顺手创建目标/staging 条目 -> 全树快照断言失败；
    - blocked 场景清理/改名/覆盖既有条目 -> 哨兵字节与全树快照断言
      失败；
    - blocked 不带 reasons -> reasons 断言失败。
    """
    _write_legacy_prompt_registry(tmp_path)
    mapping_item = _confirmed_prompt_mapping_item()
    occupied = tmp_path / existing_rel_path
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(_EXISTING_TARGET_BYTES)

    # 前置事实：既有条目以指定文件形式存在；映射指定的 target_path 空闲
    # （四个场景同构，差异只在既有条目的身份/文件形式是否构成冲突）。
    assert occupied.is_file()
    assert not (tmp_path / str(mapping_item["target_path"])).exists()

    before = _snapshot_tree(tmp_path)

    precheck = _resolve_precheck_entry()
    assert precheck is not None, (
        "只读 Prompt 迁移预检行为缺失：versioning.migration 未提供 "
        "precheck_prompt_migration 入口（当前 behavior 未实现）"
    )
    report = precheck(tmp_path, mapping_item)

    if expected_status == "blocked":
        assert report.status == "blocked", (
            f"records/ 下已存在同身份条目的非标准文件形式"
            f"（{existing_rel_path}），同身份不得以任何文件形式占用，预检"
            f"必须 fail-closed 返回 blocked：实际 status={report.status!r}"
        )
        assert report.reasons, _BLOCKED_REASONS_REQUIRED_MSG
    else:
        assert report.status == "ready", (
            f"已有不同身份的同前缀邻居条目（revision 不同）不构成目标冲突，"
            f"预检应为 ready：实际 status={report.status!r}，"
            f"reasons={report.reasons!r}"
        )

    # 既有条目逐字节保持；全树零写入（ready 场景亦不得创建任何新条目）。
    assert occupied.read_bytes() == _EXISTING_TARGET_BYTES
    assert _snapshot_tree(tmp_path) == before
