"""迁移模块：显式区分只读预检与真实转换。

提供已确认 Prompt 映射的两段入口：
- :func:`precheck_prompt_migration`：只读预检，先验证映射项（含用户确认
  状态）、目标身份合法性与 legacy 源必需文件，再检查目标无冲突，返回
  只读报告；
- :func:`migrate_prompt`：对已确认映射执行真实转换，读取 legacy 源
  ``system_prompt`` / ``user_prompt`` / ``output_fields``，经
  ``versioning.prompts.create_prompt`` 的既有创建/校验语义创建正式
  Prompt，返回完整 prompt ID。

约束（根 AGENTS.md / M0 证据）：
- versioning 完整身份 ``<kind>-v<协议>-r<N>``；fail-closed；
  禁止旧哈希身份、LATEST、短哈希前缀与隐式最新。
- 预检全程零写入：不创建 ``records/``、staging 或任何目标条目，
  不修改 legacy 源；报告只经返回值给出。
- history-summary、冲突恢复等不在本切片内。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from versioning.ids import InvalidIdentifier, parse_prompt_id
from versioning.prompts import (
    PromptConflict,
    PromptError,
    create_prompt,
)

# M0 object-mapping.yaml 中"用户已逐项确认"的状态值。
_CONFIRMED_STATUS = "user_confirmed"

# M0 object-mapping.yaml prompt_mapping 声明的 Prompt 协议：已确认目标为
# prompt-v4.1-r1，协议段 v4.1。目标身份协议必须与此精确相等。
_PROMPT_PROTOCOL = "v4.1"

# legacy Prompt registry 相对根的路径模板（source-inventory.yaml）。
_LEGACY_PROMPT_REGISTRY = Path("pipeline") / "prompt_registry"

_LEGACY_REQUIRED_FILES = ("manifest.json", "prompt.yaml")

# legacy prompt_content_sha256 的 payload 字段（权威 recipe，
# pipeline/prompt_control/core.py::prompt_content_sha256；不含 revision_id）。
_LEGACY_CONTENT_HASH_PAYLOAD_FIELDS = (
    "schema_version",
    "protocol_id",
    "system_prompt",
    "user_prompt",
    "output_fields",
    "label_pools",
)


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


def _check_legacy_provenance(source_entry: Path) -> list[str]:
    """复算 legacy 源 prompt_content_sha256 并与 manifest 声明值比对。

    按权威 recipe（pipeline/prompt_control/core.py::prompt_content_sha256）
    从 legacy prompt.yaml 取六字段 payload（schema_version / protocol_id /
    system_prompt / user_prompt / output_fields / label_pools，不含
    revision_id），经 json.dumps(ensure_ascii=False, sort_keys=True,
    separators=(",", ":"), allow_nan=False).encode("utf-8") canonical 化后
    取 sha256；与 manifest.json 声明的 prompt_content_sha256 比对，不匹配
    或任一步无法完成（解析失败、缺字段、声明值缺失/非字符串）均返回错误
    列表（fail-closed）。这是 legacy 源 provenance 校验：不复用
    prompt_yaml_sha256 文件字节口径，不回读声明值自比，不写入迁移目标。
    """
    prompt_file = source_entry / "prompt.yaml"
    manifest_file = source_entry / "manifest.json"
    try:
        prompt = yaml.safe_load(prompt_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"legacy 源 prompt.yaml 无法解析，无法复算内容哈希: {exc}"]
    if not isinstance(prompt, Mapping):
        return ["legacy 源 prompt.yaml 顶层必须是 mapping，无法复算内容哈希"]
    missing = [
        name for name in _LEGACY_CONTENT_HASH_PAYLOAD_FIELDS if name not in prompt
    ]
    if missing:
        return [
            "legacy 源 prompt.yaml 缺少内容哈希 payload 字段: "
            + ", ".join(missing)
        ]
    payload = {
        name: prompt[name] for name in _LEGACY_CONTENT_HASH_PAYLOAD_FIELDS
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    recomputed = hashlib.sha256(canonical).hexdigest()

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"legacy 源 manifest.json 无法解析，无法读取声明内容哈希: {exc}"]
    if not isinstance(manifest, Mapping):
        return ["legacy 源 manifest.json 顶层必须是 mapping，无法读取声明内容哈希"]
    declared = manifest.get("prompt_content_sha256")
    if not isinstance(declared, str) or not declared:
        return ["legacy 源 manifest.json 缺少 prompt_content_sha256 声明值"]
    if recomputed != declared:
        return [
            "legacy 源内容 provenance 不一致：按权威 recipe 复算的 "
            f"prompt_content_sha256={recomputed} 与 manifest 声明值 {declared} 不匹配"
        ]
    return []


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
         均存在；文件齐全时复算 legacy 源 ``prompt_content_sha256``
         （权威 recipe：六字段 canonical JSON payload，不含 revision_id）
         并与 manifest 声明值比对（fail-closed，不匹配即 blocked；该哈希
         不写入迁移目标）；
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
        required_missing = any(
            not (source_entry / name).is_file() for name in _LEGACY_REQUIRED_FILES
        )
        if required_missing:
            for name in _LEGACY_REQUIRED_FILES:
                required = source_entry / name
                if not required.is_file():
                    errors.append(f"legacy 源必需文件缺失：{required.relative_to(root)}")
        else:
            # 源必需文件齐全：复算 prompt_content_sha256 与 manifest 声明值
            # 比对（T8 内容 provenance 一致性门，fail-closed）。
            errors.extend(_check_legacy_provenance(source_entry))

    errors.extend(_check_target_conflict(root, mapping_item))

    return report(errors)


class PromptMigrationBlocked(PromptError):
    """迁移预检未通过（映射/身份/源文件类域错误）；拒绝转换，不做任何写入。"""


def migrate_prompt(root: Path, mapping_item: Mapping[str, object]) -> str:
    """对已确认 Prompt 映射执行真实转换，返回创建的完整 prompt ID。

    先经 :func:`precheck_prompt_migration` 做只读预检：
    - 非 ready 且原因为映射项/身份/legacy 源文件类域错误时，抛
      ``PromptMigrationBlocked``（fail-closed，零写入）；
    - 非 ready 且仅目标冲突时，复用 ``create_prompt`` 的既有
      ``PromptConflict`` 语义拒绝（不覆盖、不自动改号）。

    ready 时从映射指定的 legacy 源
    ``pipeline/prompt_registry/<source_legacy_id>/prompt.yaml`` 读取
    ``system_prompt`` / ``user_prompt`` / ``output_fields``，经
    ``create_prompt``（含 ``parse_prompt_definition`` 校验）在
    ``records/prompts/<完整身份>.yaml`` 创建正式 Prompt。不写入
    provenance / label_pools / revision_id 等非标准字段；不修改
    legacy 源、旧 active pointers 或传入映射项。
    """
    root = Path(root)
    report = precheck_prompt_migration(root, mapping_item)
    if report.status != "ready":
        conflict_errors = _check_target_conflict(root, mapping_item)
        if not conflict_errors or any(
            reason not in conflict_errors for reason in report.reasons
        ):
            raise PromptMigrationBlocked(
                "Prompt 迁移预检未通过：" + "；".join(report.reasons)
            )
        # 仅目标冲突：target_path 冲突交给 create_prompt 自然抛出
        # PromptConflict；records/ 下同身份条目（target_path 空闲）同样
        # 经 PromptConflict 拒绝，不得绕过改名冲突静默创建。
        target_rel = mapping_item.get("target_path")
        if not isinstance(target_rel, str) or not (root / target_rel).exists():
            raise PromptConflict("；".join(report.reasons))

    identity = mapping_item["candidate_target_identity"]
    parsed = parse_prompt_id(identity)  # 预检已校验，此处必为完整 prompt ID
    source_id = mapping_item["source_legacy_id"]
    source_prompt = (
        root / _LEGACY_PROMPT_REGISTRY / source_id / "prompt.yaml"
    )
    try:
        raw = yaml.safe_load(source_prompt.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PromptMigrationBlocked(
            f"legacy 源 prompt.yaml 无法解析: {exc}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise PromptMigrationBlocked("legacy 源 prompt.yaml 顶层必须是 mapping")
    try:
        system_prompt = raw["system_prompt"]
        user_prompt = raw["user_prompt"]
        output_fields = raw["output_fields"]
    except KeyError as exc:
        raise PromptMigrationBlocked(
            f"legacy 源 prompt.yaml 缺少必需字段: {exc}"
        ) from exc

    return create_prompt(
        root,
        parsed.protocol,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output_fields=output_fields,
        version=identity,
    )
