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
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from versioning.data_release import (
    load_release_metadata,
    parse_release_metadata,
    seal_payload,
)
from versioning.ids import InvalidIdentifier, parse_data_id, parse_prompt_id
from versioning.prompts import (
    PromptConflict,
    PromptError,
    create_prompt,
)
from versioning.state import DataStatus

# M0 object-mapping.yaml 中"用户已逐项确认"的状态值。
_CONFIRMED_STATUS = "user_confirmed"

# M0 object-mapping.yaml prompt_mapping 声明的 Prompt 协议：已确认目标为
# prompt-v4.1-r1，协议段 v4.1。目标身份协议必须与此精确相等。
_PROMPT_PROTOCOL = "v4.1"

# legacy Prompt registry 相对根的路径模板（source-inventory.yaml）。
_LEGACY_PROMPT_REGISTRY = Path("pipeline") / "prompt_registry"

_LEGACY_REQUIRED_FILES = ("manifest.json", "prompt.yaml")

# M0 object-mapping.yaml data_mapping 声明的 data 协议：已确认目标为
# data-v4.1-r1 / data-v4.1-r2，协议段 v4.1。目标身份协议必须与此精确相等。
_DATA_PROTOCOL = "v4.1"

# D1 用户确认的 data 目标生命周期字段取值。
_DATA_TARGET_STATUSES = ("active", "superseded")

# legacy data release 相对根的路径模板（source-inventory.yaml data_releases）。
_LEGACY_DATA_RELEASES = Path("workspace") / "data" / "releases"
_LEGACY_DATA_MANIFEST = Path("manifest") / "release_manifest.json"
_LEGACY_DATA_REQUIRED_FILES = (_LEGACY_DATA_MANIFEST,)

# 旧数据活动指针相对根路径（M0 source-inventory pinned_by 事实：活动
# data release 被该指针钉扎；非活动 release pinned_by: ~，无钉扎）。
_LEGACY_DATA_ACTIVE_POINTER = Path("finetune") / "active_data_release.json"

# 指针 provenance 门必需字段：release_id 必须钉扎映射项声明的
# source_legacy_id；expected_manifest_sha256 是钉扎时的
# workspace/data/releases/<source_legacy_id>/manifest/release_manifest.json
# 文件字节 SHA-256（复算比对口径，非 canonical JSON、非 payload 哈希）。
_LEGACY_DATA_POINTER_REQUIRED_FIELDS = (
    "release_id",
    "expected_manifest_sha256",
)

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


@dataclass(frozen=True)
class DataMigrationObjectPrecheckReport:
    """批级只读预检的逐对象报告（按 source_legacy_id 归因）。"""

    status: str  # "ready" 或 "blocked"
    source_legacy_id: str = ""
    target_identity: str = ""
    target_path: str = ""
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DataMigrationPrecheckReport:
    """data 迁移批级只读预检报告（仅经返回值给出，不落盘）。"""

    status: str  # "ready" 或 "blocked"
    object_reports: tuple[DataMigrationObjectPrecheckReport, ...] = field(
        default_factory=tuple
    )
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _data_identity_errors(identity: object) -> list[str]:
    """fail-closed 校验 data 候选目标身份；返回错误列表（空 = 合法）。"""
    if not isinstance(identity, str) or not identity:
        return ["candidate_target_identity 缺失或非字符串"]
    errors: list[str] = []
    if identity in {"LATEST", "latest"} or identity.endswith("LATEST"):
        errors.append("禁止 LATEST / 隐式最新身份")
    try:
        parsed = parse_data_id(identity)
    except InvalidIdentifier:
        errors.append(
            f"目标身份 {identity!r} 不符合 <kind>-v<协议>-r<N> 完整身份格式"
        )
    else:
        if parsed.protocol != _DATA_PROTOCOL:
            errors.append(
                f"目标身份 {identity!r} 协议 {parsed.protocol!r} 与映射声明的 "
                f"data 协议 {_DATA_PROTOCOL!r} 不一致"
            )
    return errors


def _data_target_status_errors(mapping_item: Mapping[str, object]) -> list[str]:
    """校验 D1 用户确认字段 target_status / replacement（fail-closed）。"""
    errors: list[str] = []
    target_status = mapping_item.get("target_status")
    if target_status not in _DATA_TARGET_STATUSES:
        errors.append(
            f"target_status={target_status!r} 非法：data 迁移仅接受 "
            f"{_DATA_TARGET_STATUSES}"
        )
        return errors
    if target_status == "superseded":
        replacement = mapping_item.get("replacement")
        if not isinstance(replacement, str) or not replacement:
            errors.append(
                "target_status 为 superseded 时 replacement 缺失或非字符串"
            )
        else:
            errors.extend(_data_identity_errors(replacement))
    return errors


def _check_legacy_data_source(
    root: Path, mapping_item: Mapping[str, object]
) -> list[str]:
    """检查 legacy data 源 manifest 与声明 payload 内容完整性（只读，fail-closed）。

    按映射项的 source_legacy_id 定位
    ``workspace/data/releases/<source_legacy_id>``（不扫描 releases 目录，
    未映射 sibling 不参与本对象报告）；manifest/release_manifest.json 必须
    存在且其 release_id 与源身份一致；manifest files 声明的每个 payload
    文件（manifest 自洽性/内容完整性门）必须：
      - ``path`` 为安全的相对路径（拒绝绝对路径、``..`` 穿越与解析后
        越出 legacy release 根的路径，fail-closed 且在读取前拒绝）；
      - 文件存在；
      - ``sha256`` 字段存在且为字符串；
      - 按文件字节独立复算 SHA-256 与声明值精确比对（不用 canonical
        JSON、size_bytes 或声明值自比替代文件字节哈希；不复用 T13 指针
        门的 manifest 文件字节口径）。

    该门是 manifest 自洽性/内容完整性机制，不等于训练机真实 payload
    已验证：training_observed 等来源状态不得升级为 payload 已验证。
    """
    errors: list[str] = []
    source_id = mapping_item.get("source_legacy_id")
    if not isinstance(source_id, str) or not source_id:
        return errors
    release_dir = root / _LEGACY_DATA_RELEASES / source_id
    for required in _LEGACY_DATA_REQUIRED_FILES:
        if not (release_dir / required).is_file():
            errors.append(
                f"legacy 源必需文件缺失：{(release_dir / required).relative_to(root)}"
            )
    if errors:
        return errors
    manifest_file = release_dir / _LEGACY_DATA_MANIFEST
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"legacy 源 release_manifest.json 无法解析: {exc}"]
    if not isinstance(manifest, Mapping):
        return ["legacy 源 release_manifest.json 顶层必须是 mapping"]
    if manifest.get("release_id") != source_id:
        errors.append(
            f"legacy 源 manifest release_id={manifest.get('release_id')!r} "
            f"与源身份 {source_id!r} 不一致"
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        errors.append("legacy 源 release_manifest.json 缺少非空 files 声明")
        return errors
    release_root = release_dir.resolve()
    for entry in files:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
            errors.append("legacy 源 manifest files 条目缺少 path 声明")
            continue
        declared_path = entry["path"]
        path_obj = Path(declared_path)
        if path_obj.is_absolute() or ".." in path_obj.parts:
            errors.append(
                "legacy 源 manifest files 条目 path 异常："
                f"{declared_path!r}（拒绝绝对路径与 .. 穿越）"
            )
            continue
        payload_file = release_dir / declared_path
        try:
            resolved = payload_file.resolve()
        except (OSError, RuntimeError) as exc:
            # fail-closed：路径解析异常（含 symlink loop，Python 3.11
            # 的 resolve() 将 ELOOP 转成 RuntimeError）一律拒绝，不
            # 用 absolute() 回退弱化越界检查。
            errors.append(
                "legacy 源 manifest files 条目 path 无法解析"
                "（fail-closed）: "
                f"{declared_path!r}: {exc}"
            )
            continue
        if not resolved.is_relative_to(release_root):
            errors.append(
                "legacy 源 manifest files 条目 path 解析后越出 legacy "
                f"release 根：{declared_path!r}"
            )
            continue
        if not payload_file.is_file():
            errors.append(
                f"legacy 源声明的 payload 文件缺失：{payload_file.relative_to(root)}"
            )
            continue
        declared_hash = entry.get("sha256")
        if not isinstance(declared_hash, str) or not declared_hash:
            errors.append(
                "legacy 源 manifest files 条目缺少 sha256 声明："
                f"{declared_path!r}"
            )
            continue
        try:
            recomputed = hashlib.sha256(payload_file.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(
                f"legacy 源声明的 payload 文件无法读取（fail-closed）: "
                f"{declared_path!r}: {exc}"
            )
            continue
        if recomputed != declared_hash:
            errors.append(
                "legacy 源 payload 文件哈希不匹配："
                f"{declared_path!r} 按文件字节复算 SHA-256={recomputed} "
                f"与 manifest 声明 sha256 {declared_hash} 不一致"
            )
    return errors


def _check_pinned_manifest_provenance(
    root: Path, mapping_item: Mapping[str, object]
) -> list[str]:
    """已钉扎 legacy manifest provenance 门（只读，fail-closed）。

    仅对带钉扎证据的映射项启用：M0 source-inventory pinned_by 事实钉扎
    的是活动 data release（映射 target_status ``active``），非活动
    release（``superseded``）pinned_by: ~，无钉扎 —— 门对无钉扎映射项
    不适用（不阻塞，也不伪造 verified/passed）。门对带钉扎映射项：
      1. 读取旧数据活动指针 ``finetune/active_data_release.json``；
      2. 指针 ``release_id`` 必须精确等于该映射项的 ``source_legacy_id``
         （钉扎未映射 sibling 或错误源 = 不符）；
      3. 按文件字节独立复算
         ``workspace/data/releases/<source_legacy_id>/manifest/
         release_manifest.json`` 的 SHA-256（不 import legacy
         pipeline / finetune 代码，独立镜像自算；不用 canonical JSON、
         目录哈希或 payload 哈希，不回读 manifest 声明值自比）；
      4. 与指针 ``expected_manifest_sha256`` 比对。

    指针缺失、非 JSON、顶层非 mapping、必需字段缺失、release_id 不符或
    哈希不匹配均返回错误（fail-closed）。全程只读，不修复指针、不重建
    manifest、不就地修改传入映射项。
    """
    if mapping_item.get("target_status") != "active":
        return []
    source_id = mapping_item.get("source_legacy_id")
    if not isinstance(source_id, str) or not source_id:
        return []

    pointer_file = root / _LEGACY_DATA_ACTIVE_POINTER
    if not pointer_file.is_file():
        return [
            "旧数据活动指针缺失："
            f"{_LEGACY_DATA_ACTIVE_POINTER}（已钉扎活动 release 的 "
            "manifest provenance 无法核验，fail-closed）"
        ]
    try:
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return [
            f"旧数据活动指针 {_LEGACY_DATA_ACTIVE_POINTER} 非 JSON / "
            f"无法解析（manifest provenance 无法核验，fail-closed）: {exc}"
        ]
    if not isinstance(pointer, Mapping):
        return [
            "旧数据活动指针顶层必须是 mapping（manifest provenance "
            "无法核验，fail-closed）"
        ]
    missing = [
        name for name in _LEGACY_DATA_POINTER_REQUIRED_FIELDS if name not in pointer
    ]
    if missing:
        return [
            "旧数据活动指针缺少必需字段: "
            + ", ".join(missing)
            + "（manifest provenance 无法核验，fail-closed）"
        ]
    pointer_release_id = pointer["release_id"]
    if pointer_release_id != source_id:
        return [
            "旧数据活动指针未钉扎该映射项声明的源："
            f"指针 release_id={pointer_release_id!r} 与映射项 "
            f"source_legacy_id={source_id!r} 不符（fail-closed）"
        ]
    expected = pointer["expected_manifest_sha256"]
    manifest_file = root / _LEGACY_DATA_RELEASES / source_id / _LEGACY_DATA_MANIFEST
    if not manifest_file.is_file():
        # legacy 源必需文件缺失由 _check_legacy_data_source 归因，此处不再重复。
        return []
    try:
        recomputed = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
    except OSError as exc:
        return [
            f"钉扎的 legacy release manifest 文件字节无法读取（fail-closed）: {exc}"
        ]
    if recomputed != expected:
        return [
            "已钉扎 legacy manifest provenance 不一致：按 manifest 文件字节"
            f"复算 SHA-256={recomputed} 与指针 expected_manifest_sha256 "
            f"{expected} 不匹配（fail-closed）"
        ]
    return []


def precheck_data_migration(
    root: Path, mapping_items: Any
) -> DataMigrationPrecheckReport:
    """对已确认 data 映射批执行只读迁移预检（T11）。

    逐映射项（按 source_legacy_id 定位源，不扫描未映射 sibling）校验：
      1. 映射项 ``status`` 为 ``user_confirmed``（消费 M0 确认状态，fail-closed）；
      2. 候选目标身份为合法 ``data-v<协议>-r<N>`` 完整身份且协议为 v4.1；
      3. D1 用户确认字段：``target_status`` 为 active / superseded；
         superseded 时 ``replacement`` 为合法 data 身份；
      4. legacy 源 ``workspace/data/releases/<source_legacy_id>`` 的
         manifest/release_manifest.json 存在、release_id 与源身份一致、
         声明的 payload 文件路径安全（拒绝绝对路径 / ``..`` 穿越 / 解析后
         越出 release 根）且齐全，并按文件字节复算每个声明 payload 文件
         的 SHA-256 与 manifest 声明 sha256 比对（manifest 自洽性/内容
         完整性门，fail-closed；不等于训练机真实 payload 已验证）；
      5. 目标无冲突（``<root>/<target_path>`` 已存在、``records/`` 下或
         data 正式对象根（target_path 的对象目录层，如
         ``data/releases/``）下同身份条目存在均 blocked）；
      6. 已钉扎 manifest provenance 门（T13）：target_status ``active``
         的映射项（M0 pinned_by 钉扎）经旧数据活动指针
         ``finetune/active_data_release.json`` 核验 —— 指针
         ``release_id`` 必须等于该映射项 ``source_legacy_id``，且
         ``workspace/data/releases/<source_legacy_id>/manifest/
         release_manifest.json`` 文件字节 SHA-256 必须与指针
         ``expected_manifest_sha256`` 匹配；指针缺失 / 非 JSON / 字段
         缺失 / release_id 不符 / 哈希不匹配即该对象 blocked；无钉扎
         映射项不适用本门（不阻塞、不伪造 verified）。

    整批 ``status`` 为 ready 当且仅当全部对象报告 ready。全程零写入：
    不创建 ``<root>/data``、working、release_staging、records 或任何目标
    条目，不修改 legacy 源树、旧 active pointers 或传入映射项；报告只经
    返回值给出。manifest payload 文件哈希门已在当前实现内；训练机真实
    payload 验证、真实转换、凭证与恢复不在本切片内。
    """
    root = Path(root)
    try:
        items = list(mapping_items)
    except TypeError:
        items = []
    batch_errors: list[str] = []
    if not items:
        batch_errors.append("data 映射批为空：预检需至少一条映射项")

    object_reports: list[DataMigrationObjectPrecheckReport] = []
    for mapping_item in items:
        if not isinstance(mapping_item, Mapping):
            object_reports.append(
                DataMigrationObjectPrecheckReport(
                    status="blocked",
                    reasons=("映射项必须是 mapping",),
                )
            )
            continue
        errors: list[str] = []
        if mapping_item.get("status") != _CONFIRMED_STATUS:
            errors.append(
                f"映射项 status={mapping_item.get('status')!r} 未确认：只读预检仅接受 "
                f"{_CONFIRMED_STATUS!r}（fail-closed，pending/unknown 不得当 confirmed）"
            )
        source_id = mapping_item.get("source_legacy_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append("source_legacy_id 缺失或非字符串")
        errors.extend(
            _data_identity_errors(mapping_item.get("candidate_target_identity"))
        )
        errors.extend(_data_target_status_errors(mapping_item))
        target_path = mapping_item.get("target_path")
        if not isinstance(target_path, str) or not target_path:
            errors.append("target_path 缺失或非字符串")

        if isinstance(source_id, str) and source_id:
            errors.extend(_check_legacy_data_source(root, mapping_item))
        errors.extend(_check_target_conflict(root, mapping_item))
        errors.extend(_check_data_root_conflict(root, mapping_item))
        errors.extend(_check_pinned_manifest_provenance(root, mapping_item))

        object_reports.append(
            DataMigrationObjectPrecheckReport(
                status="blocked" if errors else "ready",
                source_legacy_id=source_id if isinstance(source_id, str) else "",
                target_identity=(
                    mapping_item["candidate_target_identity"]
                    if isinstance(mapping_item.get("candidate_target_identity"), str)
                    else ""
                ),
                target_path=target_path if isinstance(target_path, str) else "",
                reasons=tuple(errors),
            )
        )

    all_ready = (
        not batch_errors
        and all(obj.status == "ready" for obj in object_reports)
    )
    reasons = tuple(batch_errors) + tuple(
        reason
        for obj in object_reports
        for reason in obj.reasons
    )
    return DataMigrationPrecheckReport(
        status="ready" if all_ready else "blocked",
        object_reports=tuple(object_reports),
        reasons=reasons,
    )


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
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError) as exc:
        # canonical 化失败（如 YAML 特殊浮点 .nan/.inf 非 JSON 兼容）
        # fail-closed：权威 recipe 对该 payload 无法产出任何合法哈希，
        # 返回错误列表经报告通道 blocked，不穿透 ValueError/TypeError。
        return [
            "legacy 源 prompt.yaml 内容哈希 payload 无法 canonical 化"
            f"（非 JSON 兼容值，权威 recipe 无法复算）: {exc}"
        ]
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


def _check_data_root_conflict(
    root: Path, mapping_item: Mapping[str, object]
) -> list[str]:
    """检查 data 正式对象根上的同身份条目冲突（只读，不创建）。

    按映射 target_path 定位 data 正式对象根（如 target_path
    ``data/releases/data-v4.1-r1/release.yaml`` 的对象根为
    ``data/releases/``，即 target_path 上溯两层：对象目录层之上），同
    身份目录（即使缺少 release.yaml）或同身份文件形式（``name ==
    identity or name.startswith(identity + ".")``，覆盖无扩展名与复合
    扩展名等非标准形式）即冲突；仅按精确身份判定，``data-v4.1-r10``
    等同前缀但 revision 不同的邻居是不同身份，不构成冲突。data 根不
    存在视为无冲突。
    """
    errors: list[str] = []
    identity = mapping_item.get("candidate_target_identity")
    target_rel = mapping_item.get("target_path")
    if not isinstance(identity, str) or not isinstance(target_rel, str):
        return errors
    data_root_rel = Path(target_rel).parent.parent
    if str(data_root_rel) in ("", "."):
        return errors
    data_root = root / data_root_rel
    if not data_root.is_dir():
        return errors
    for existing in sorted(data_root.iterdir()):
        if existing.name == identity or existing.name.startswith(f"{identity}."):
            errors.append(
                f"data 正式对象根已存在同身份条目：{existing.relative_to(root)}"
            )
            break
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


# ---------------------------------------------------------------------------
# T15：data 真实转换（单对象 active 最小切片）
# ---------------------------------------------------------------------------

# committed migration receipt 相对目标根的路径目录；每条映射一份
# ``<target_identity>.receipt.yaml``。
_MIGRATION_RECEIPTS_DIR = Path("migration_receipts")

_RECEIPT_COMMITTED_STATUS = "committed"

# legacy manifest 中映射到 source_batches 的原始批次标识字段（M0
# object-mapping preserve_state：source_batches 记录原始批次，不回填伪造）。
_LEGACY_SOURCE_BATCH_FIELDS = (
    "source_review_batch_id",
    "source_queue_id",
    "source_media_id",
)

# legacy manifest counts.splits 的声明键口径：fold_N_train -> train、
# fold_N_val -> validation（fold 名取 fold_N 前缀）。
_SPLIT_TRAIN_SUFFIX = "_train"
_SPLIT_VAL_SUFFIX = "_val"


class DataMigrationBlocked(Exception):
    """data 迁移拒绝通道：预检未通过或命中本切片未覆盖场景。

    fail-closed：任何写入前抛出，不遗留半写入目标对象。
    """


def _derive_release_splits(raw_splits: object) -> dict[str, dict[str, int]]:
    """从 legacy manifest counts.splits 声明值派生 release.yaml splits。

    声明键 ``fold_N_train`` / ``fold_N_val`` 分别映射为 fold ``fold_N``
    的 ``train`` / ``validation`` 计数（语义取自 manifest 声明值，不重算）。
    """
    if not isinstance(raw_splits, Mapping) or not raw_splits:
        raise DataMigrationBlocked(
            "legacy manifest counts.splits 缺失或为空，无法派生 splits"
        )
    splits: dict[str, dict[str, int]] = {}
    for key, value in raw_splits.items():
        if not isinstance(key, str) or not key:
            raise DataMigrationBlocked(
                f"legacy manifest counts.splits 键非法: {key!r}"
            )
        if key.endswith(_SPLIT_TRAIN_SUFFIX):
            fold, part = key[: -len(_SPLIT_TRAIN_SUFFIX)], "train"
        elif key.endswith(_SPLIT_VAL_SUFFIX):
            fold, part = key[: -len(_SPLIT_VAL_SUFFIX)], "validation"
        else:
            raise DataMigrationBlocked(
                "legacy manifest counts.splits 键不符合 "
                f"fold_N_train/fold_N_val 口径: {key!r}"
            )
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise DataMigrationBlocked(
                f"legacy manifest counts.splits[{key!r}] 必须是非负整数"
            )
        fold_splits = splits.setdefault(fold, {})
        if part in fold_splits:
            raise DataMigrationBlocked(
                f"legacy manifest counts.splits 对 fold {fold!r} 重复声明 {part!r}"
            )
        fold_splits[part] = value
    for fold, fold_splits in splits.items():
        if set(fold_splits) != {"train", "validation"}:
            raise DataMigrationBlocked(
                f"legacy manifest counts.splits 对 fold {fold!r} 缺少 train/"
                "validation 之一"
            )
    return splits


def _build_release_data(
    identity: str,
    source_id: str,
    manifest: Mapping[str, object],
    mapping_item: Mapping[str, object],
) -> dict[str, Any]:
    """从 legacy manifest 声明值构造目标 release.yaml 数据（不重算、不伪造）。

    语义字段全部读取 legacy manifest：protocol 取 contract_version、
    sample_count 取 counts.published_candidates、splits 取 counts.splits
    声明值、source_batches 取原始批次标识；purpose/training_allowed 按
    legacy 训练 release（manifest status training_ready）的正式映射固定为
    development/true；status 按映射 target_status：superseded 携带映射声明
    的 replacement，active 不得携带 replacement（fail-closed）。
    """
    if manifest.get("status") != "training_ready":
        raise DataMigrationBlocked(
            f"legacy manifest status={manifest.get('status')!r} 的真实转换不在"
            "本切片内（仅覆盖 training_ready 训练 release）"
        )
    protocol = manifest.get("contract_version")
    if not isinstance(protocol, str) or not protocol:
        raise DataMigrationBlocked("legacy manifest contract_version 缺失或非字符串")
    counts = manifest.get("counts")
    if not isinstance(counts, Mapping):
        raise DataMigrationBlocked("legacy manifest counts 缺失或不是 mapping")
    sample_count = counts.get("published_candidates")
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count < 0
    ):
        raise DataMigrationBlocked(
            "legacy manifest counts.published_candidates 必须是非负整数"
        )
    splits = _derive_release_splits(counts.get("splits"))
    source_batches = [
        manifest.get(name) for name in _LEGACY_SOURCE_BATCH_FIELDS
    ]
    if any(
        not isinstance(batch, str) or not batch for batch in source_batches
    ):
        raise DataMigrationBlocked(
            "legacy manifest 原始批次标识（source_review_batch_id / "
            "source_queue_id / source_media_id）缺失或非字符串"
        )
    target_status = mapping_item.get("target_status")
    replacement = mapping_item.get("replacement")
    if target_status == DataStatus.SUPERSEDED.value:
        release_data: dict[str, Any] = {
            "version": identity,
            "protocol": protocol,
            "state": "sealed",
            "purpose": "development",
            "training_allowed": True,
            "description": f"自 legacy data release {source_id} 迁移",
            "sample_count": sample_count,
            "source_batches": source_batches,
            "splits": splits,
            "status": DataStatus.SUPERSEDED.value,
            "replacement": replacement,
        }
        return release_data
    if replacement is not None:
        raise DataMigrationBlocked(
            "active release 不得携带 replacement（replacement 仅 superseded "
            "时允许）"
        )
    return {
        "version": identity,
        "protocol": protocol,
        "state": "sealed",
        "purpose": "development",
        "training_allowed": True,
        "description": f"自 legacy data release {source_id} 迁移",
        "sample_count": sample_count,
        "source_batches": source_batches,
        "splits": splits,
        "status": DataStatus.ACTIVE.value,
    }


def _release_content_digest(release_dir: Path) -> str:
    """按钉定口径复算目标 release 内容摘要。

    对 release 目录下全部文件按相对 POSIX 路径升序，拼接
    ``<rel>\n<sha256(file bytes)>\n`` 行后取 UTF-8 字节的 SHA-256。
    """
    lines = "".join(
        f"{relative}\n{hashlib.sha256(data).hexdigest()}\n"
        for relative, data in sorted(
            (
                (path.relative_to(release_dir).as_posix(), path.read_bytes())
                for path in release_dir.rglob("*")
                if path.is_file()
            ),
            key=lambda item: item[0],
        )
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _migrate_single_data_release(
    root: Path, mapping_item: Mapping[str, object]
) -> Path:
    """对单条已确认映射执行 data 真实转换，返回写入的 receipt 路径。"""
    source_id = mapping_item["source_legacy_id"]
    identity = mapping_item["candidate_target_identity"]
    target_rel = mapping_item["target_path"]
    target_status = mapping_item["target_status"]

    legacy_release_dir = root / _LEGACY_DATA_RELEASES / source_id
    manifest_file = legacy_release_dir / _LEGACY_DATA_MANIFEST
    manifest_bytes = manifest_file.read_bytes()
    source_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, Mapping):
        raise DataMigrationBlocked("legacy 源 release_manifest.json 顶层必须是 mapping")
    files = manifest.get("files")
    if not isinstance(files, list) or not all(
        isinstance(entry, Mapping) and isinstance(entry.get("path"), str)
        for entry in files
    ):
        raise DataMigrationBlocked("legacy 源 release_manifest.json files 声明非法")

    # 写入前 re-validation（P2-2）：预检通过与写入之间存在 TOCTOU 窗口，
    # 写入时重新读取的 manifest 可以不再是预检验证过的那份。在任何目标
    # 目录/文件写入前，对当前 manifest 重跑与预检同口径的
    # _check_legacy_data_source（files[] 路径安全 + payload 存在性 + 哈希），
    # 任一不满足即 fail-closed 拒绝，不创建目标目录、不留半写 release、
    # 不写 receipt。
    source_errors = _check_legacy_data_source(root, mapping_item)
    if source_errors:
        raise DataMigrationBlocked(
            "写入前 manifest/payload re-validation 未通过（fail-closed，零写入）："
            + "；".join(source_errors)
        )

    # superseded 目标：replacement 必须指向目标 root 中已有的正式 release
    # （fail-closed：任何目标目录/文件写入前核验，悬空引用零写入拒绝）。
    if target_status == DataStatus.SUPERSEDED.value:
        replacement = mapping_item.get("replacement")
        if not isinstance(replacement, str) or not replacement:
            raise DataMigrationBlocked(
                "target_status 为 superseded 时 replacement 缺失或非字符串"
            )
        # load_release_metadata 的 root 为 releases/ 的上一层（即 target_path
        # 上溯三层：release.yaml -> 对象目录 -> releases/ -> data 根）。
        replacement_root = root / Path(target_rel).parent.parent.parent
        try:
            load_release_metadata(replacement_root, replacement)
        except Exception as exc:
            raise DataMigrationBlocked(
                f"replacement={replacement!r} 在目标 root 下不可解析为既有"
                f"正式 release（fail-closed，零写入）: {exc}"
            ) from exc

    release_data = _build_release_data(identity, source_id, manifest, mapping_item)
    # 落盘前经既有 data release 校验语义（parse_release_metadata：schema、
    # 字段值域、身份一致性、replacement 规则）接受。
    parse_release_metadata(release_data)

    release_dir = root / Path(target_rel).parent
    release_dir.mkdir(parents=True, exist_ok=True)
    # payload 逐字节复制（保持文件集合与字节一致，不规范化、不重算）。
    for entry in files:
        declared_path = entry["path"]
        payload_target = release_dir / declared_path
        payload_target.parent.mkdir(parents=True, exist_ok=True)
        payload_target.write_bytes((legacy_release_dir / declared_path).read_bytes())
    (release_dir / "release.yaml").write_text(
        yaml.safe_dump(release_data, sort_keys=False), encoding="utf-8"
    )

    # 目标对象完整写入后经既有读取语义端到端验证（version 与目录一致等）。
    meta = load_release_metadata(release_dir.parent.parent, identity)
    expected_status = DataStatus(target_status)
    if meta.status is not expected_status:
        raise DataMigrationBlocked(
            f"目标 release 验证失败：status={meta.status!r} 非 {expected_status.value}"
        )

    # release.yaml 写入与 metadata 验证完成后、digest/receipt 写入前，经
    # 既有封存语义（seal_payload：release.yaml/README.md/authorization 保留
    # 写位、其余 payload 条目与 release 根去写位）使声明的 state: sealed
    # 与位级事实一致；封存仅作用于 release 目录子树，不波及 release 外部
    # 的 migration_receipts/ 与 legacy 源。digest/receipt 后续只读目标内容。
    seal_payload(release_dir)

    # operation_id：确定性哈希，绑定映射 source/target/status 与
    # source_manifest_sha256（同一转换的重跑产出同一 operation_id）。
    operation_payload = {
        "source_legacy_id": source_id,
        "target_identity": identity,
        "target_status": target_status,
        "source_manifest_sha256": source_manifest_sha256,
    }
    operation_id = "data-migration-" + hashlib.sha256(
        json.dumps(
            operation_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    # 目标完整写入并验证后原子写入 committed receipt（八字段契约，无多余键）。
    receipt = {
        "operation_id": operation_id,
        "source_legacy_id": source_id,
        "target_identity": identity,
        "target_path": target_rel,
        "source_manifest_sha256": source_manifest_sha256,
        "target_release_digest": _release_content_digest(release_dir),
        "status": _RECEIPT_COMMITTED_STATUS,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt_dir = root / _MIGRATION_RECEIPTS_DIR
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{identity}.receipt.yaml"
    tmp_path = receipt_dir / f".{identity}.receipt.yaml.tmp"
    try:
        tmp_path.write_text(
            yaml.safe_dump(receipt, sort_keys=False), encoding="utf-8"
        )
        os.replace(tmp_path, receipt_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return receipt_path


def migrate_data(root: Path, mapping_items: Any) -> tuple[Path, ...]:
    """对已确认 data 映射批执行真实转换（T15 单对象 active 最小切片）。

    先经 :func:`precheck_data_migration` 做整批只读预检：非 ready 抛
    ``DataMigrationBlocked``（fail-closed，零写入）。ready 后对每条映射
    在目标 root（可注入，表示目标数据根）下创建正式 data release
    （``<target_path>`` 对象目录：release.yaml + 与 legacy 源逐字节一致
    的 manifest files[] 声明 payload），语义字段取 legacy manifest 声明值
    （不重算、不伪造），status 按映射 target_status；目标对象完整写入并
    经既有读取语义（``load_release_metadata``）验证后，在
    ``migration_receipts/<target_identity>.receipt.yaml`` 原子写入
    committed receipt（operation_id / source_legacy_id / target_identity /
    target_path / source_manifest_sha256 / target_release_digest / status /
    written_at 八字段）。legacy 源与旧 active pointers 逐字节不变；不写
    records/、working、release_staging、不触发 DVC、不就地修改传入映射项。

    本切片覆盖 ``target_status`` 为 ``active`` / ``superseded`` 的单对象/
    逐条转换：superseded 目标按映射声明写入 replacement，且 replacement
    必须在写入前解析为目标 root 中已有的正式 release（fail-closed，零
    写入拒绝悬空引用）；active 目标不得携带 replacement。批级恢复、凭证
    失配拒绝、重跑幂等跳过不在本切片（越界输入在写入前即 fail-closed
    拒绝）。

    返回写入的 receipt 路径序列（与映射批同序；返回值契约本切片不绑定）。
    """
    root = Path(root)
    try:
        items = list(mapping_items)
    except TypeError:
        items = []

    report = precheck_data_migration(root, items)
    if report.status != "ready":
        raise DataMigrationBlocked(
            "data 迁移预检未通过（fail-closed，零写入）：" + "；".join(report.reasons)
        )
    if not items:
        raise DataMigrationBlocked("data 映射批为空：无转换对象")

    # 任何写入前先拒绝本切片未覆盖的 target_status（当前覆盖 active /
    # superseded；其余状态留待后续切片），避免批内半写入。
    for mapping_item in items:
        if not isinstance(mapping_item, Mapping):
            raise DataMigrationBlocked("映射项必须是 mapping")
        target_status = mapping_item.get("target_status")
        if target_status not in _DATA_TARGET_STATUSES:
            raise DataMigrationBlocked(
                f"target_status={target_status!r} 的真实转换"
                "不在本切片内（仅覆盖 active / superseded）"
            )

    receipt_paths: list[Path] = []
    for mapping_item in items:
        receipt_paths.append(_migrate_single_data_release(root, mapping_item))
    return tuple(receipt_paths)
