"""迁移模块：显式区分只读预检与真实转换。

当前只提供已确认 Prompt 映射的只读迁移预检
:func:`precheck_prompt_migration`：先验证映射项（含用户确认状态）、
目标身份合法性与 legacy 源必需文件，再检查目标无冲突，返回只读报告。

约束（根 AGENTS.md / M0 证据）：
- versioning 完整身份 ``<kind>-v<协议>-r<N>``；fail-closed；
  禁止旧哈希身份、LATEST、短哈希前缀与隐式最新。
- 预检全程零写入：不创建 ``records/``、staging 或任何目标条目，
  不修改 legacy 源；报告只经返回值给出。
- 真实转换、history-summary、冲突恢复等不在本切片内。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from versioning.ids import InvalidIdentifier, parse_prompt_id

# M0 object-mapping.yaml 中"用户已逐项确认"的状态值。
_CONFIRMED_STATUS = "user_confirmed"

# M0 object-mapping.yaml prompt_mapping 声明的 Prompt 协议：已确认目标为
# prompt-v4.1-r1，协议段 v4.1。目标身份协议必须与此精确相等。
_PROMPT_PROTOCOL = "v4.1"

# legacy Prompt registry 相对根的路径模板（source-inventory.yaml）。
_LEGACY_PROMPT_REGISTRY = Path("pipeline") / "prompt_registry"

_LEGACY_REQUIRED_FILES = ("manifest.json", "prompt.yaml")


@dataclass(frozen=True)
class PromptMigrationPrecheckReport:
    """只读预检报告（仅经返回值给出，不落盘）。"""

    status: str  # "ready" 或 "blocked"
    source_legacy_id: str = ""
    target_identity: str = ""
    target_path: str = ""
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _identity_errors(identity: object) -> list[str]:
    """fail-closed 校验候选目标身份；返回错误列表（空 = 合法）。

    复用 versioning/ids.py 的权威解析口径（五类完整身份、revision 从 1
    开始且无前导零），并在通用合法性之上追加 Prompt 迁移契约匹配：
    kind 必须是 prompt（kind 专属解析器白名单语义），协议必须与 M0 映射
    声明的 v4.1 精确相等（不做前缀/包含匹配）。
    """
    if not isinstance(identity, str) or not identity:
        return ["candidate_target_identity 缺失或非字符串"]
    errors: list[str] = []
    if identity in {"LATEST", "latest"} or identity.endswith("LATEST"):
        errors.append("禁止 LATEST / 隐式最新身份")
    try:
        parsed = parse_prompt_id(identity)
    except InvalidIdentifier:
        errors.append(f"目标身份 {identity!r} 不符合 <kind>-v<协议>-r<N> 完整身份格式")
    else:
        if parsed.protocol != _PROMPT_PROTOCOL:
            errors.append(
                f"目标身份 {identity!r} 协议 {parsed.protocol!r} 与映射声明的 "
                f"Prompt 协议 {_PROMPT_PROTOCOL!r} 不一致"
            )
    return errors


def _validate_mapping_item(mapping_item: Mapping[str, object]) -> list[str]:
    """校验映射项本身（结构 + 确认状态），返回错误列表（空 = 合法）。"""
    errors: list[str] = []
    status = mapping_item.get("status")
    if status != _CONFIRMED_STATUS:
        errors.append(
            f"映射项 status={status!r} 未确认：只读预检仅接受 "
            f"{_CONFIRMED_STATUS!r}（fail-closed，pending/unknown 不得当 confirmed）"
        )
    source_id = mapping_item.get("source_legacy_id")
    if not isinstance(source_id, str) or not source_id:
        errors.append("source_legacy_id 缺失或非字符串")
    errors.extend(_identity_errors(mapping_item.get("candidate_target_identity")))
    target_path = mapping_item.get("target_path")
    if not isinstance(target_path, str) or not target_path:
        errors.append("target_path 缺失或非字符串")
    return errors


def _check_target_conflict(root: Path, mapping_item: Mapping[str, object]) -> list[str]:
    """检查目标是否已存在冲突条目；目标根不存在视为无冲突（只读，不创建）。"""
    errors: list[str] = []
    identity = mapping_item.get("candidate_target_identity")
    target_rel = mapping_item.get("target_path")
    if not isinstance(identity, str) or not isinstance(target_rel, str):
        return errors
    target = root / target_rel
    if target.exists():
        errors.append(f"目标条目已存在，冲突时停止（不覆盖、不自动改号）：{target_rel}")
        return errors
    records_root = root / "records"
    if records_root.is_dir():
        # 同身份不允许以任何文件形式占用（防改名冲突）。仅按精确身份判定
        # （文件名等于身份，或以"身份."为前缀）：prompt-v4.1-r10 等
        # revision 不同的同前缀邻居是不同身份，不构成冲突；同时覆盖
        # 无扩展名（r1）与复合扩展名（r1.yaml.bak、r1.tar.gz）等非标准形式。
        for existing in sorted(records_root.rglob("*")):
            if existing.is_file() and (
                existing.name == identity or existing.name.startswith(f"{identity}.")
            ):
                errors.append(f"records/ 下已存在同身份条目：{existing.relative_to(root)}")
                break
    return errors


def precheck_prompt_migration(
    root: Path, mapping_item: Mapping[str, object]
) -> PromptMigrationPrecheckReport:
    """对已确认 Prompt 映射执行只读迁移预检。

    校验（全部通过 -> ``status == "ready"``）：
      1. 映射项 ``status`` 为 ``user_confirmed``（消费 M0 确认状态，fail-closed）；
      2. 候选目标身份为合法 ``<kind>-v<协议>-r<N>`` 完整身份；
      3. legacy 源必需文件
         ``pipeline/prompt_registry/<source_legacy_id>/{manifest.json,prompt.yaml}``
         均存在；
      4. 目标无冲突（``<root>/<target_path>`` 与 ``records/`` 下同身份条目均不存在）。

    全程只读：不创建目录、不写文件、不修改 legacy 源；报告只经返回值给出。
    """
    root = Path(root)

    def report(errors: list[str]) -> PromptMigrationPrecheckReport:
        source_id = mapping_item.get("source_legacy_id")
        identity = mapping_item.get("candidate_target_identity")
        target_rel = mapping_item.get("target_path")
        return PromptMigrationPrecheckReport(
            status="blocked" if errors else "ready",
            source_legacy_id=source_id if isinstance(source_id, str) else "",
            target_identity=identity if isinstance(identity, str) else "",
            target_path=target_rel if isinstance(target_rel, str) else "",
            reasons=tuple(errors),
        )

    errors = _validate_mapping_item(mapping_item)

    source_id = mapping_item.get("source_legacy_id")
    if isinstance(source_id, str) and source_id:
        source_entry = root / _LEGACY_PROMPT_REGISTRY / source_id
        for name in _LEGACY_REQUIRED_FILES:
            required = source_entry / name
            if not required.is_file():
                errors.append(f"legacy 源必需文件缺失：{required.relative_to(root)}")

    errors.extend(_check_target_conflict(root, mapping_item))

    return report(errors)
