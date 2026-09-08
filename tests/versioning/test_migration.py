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

T6 behavior（本切片，主 Agent 选定）—— Prompt 真实转换最小切片：
对已确认映射 ``v4.1-concise-evidence-json-v2`` -> ``prompt-v4.1-r1``
执行真实转换时：
1. 在新 versioning 存储创建正式 Prompt ``prompt-v4.1-r1``
   （``records/prompts/prompt-v4.1-r1.yaml``）；
2. 转换后的 system_prompt / user_prompt / output_fields 与 legacy 源
   结构化相等（逐字段、保序）；
3. legacy 源树逐字节不变；
4. 旧 active pointers（pipeline/prompt_control/active_prompt.yaml、
   finetune/active_data_release.json）不被修改，仍声明 legacy 身份；
5. 同身份目标已存在时不覆盖（经既有 Prompt 冲突域通道拒绝）；
6. 复用既有 Prompt 创建/校验语义，不直接伪造目标文件；
7. 本切片不做 data 转换、history-summary、CLI、中断恢复，也不复算
   legacy prompt_content_sha256（内容哈希保真属后续切片）；provenance
   不写入非标准目标字段（保留在 M0 object-mapping 与后续 history-summary）。

T7 behavior（本切片，reviewer 对 1a7f011d 的 P3 缺口补齐，先写测试）——
migrate_prompt 的异常类型分流必须稳定（真实转换是写入入口，预检非
ready 的拒绝通道必须按失败类别可辨）：
1. 预检非 ready 且原因为映射项/候选身份/legacy 源文件类域错误时，
   必须抛 ``PromptMigrationBlocked``（迁移域错误通道），且零写入；
   域错误与目标冲突并存时域错误通道优先（仍 PromptMigrationBlocked）；
2. 预检非 ready 仅因 records/ 下同身份条目占用（映射 target_path 空闲）
   时，必须抛 ``PromptConflict``（复用既有 Prompt 冲突域通道），且零
   写入——不得绕过改名冲突在空闲 target_path 静默创建正式对象；
3. 两条异常通道互斥可辨（PromptMigrationBlocked 与 PromptConflict 互
   不是对方实例），ready 转换与 target_path 被占用的既有行为不回归
   （T6 selector 复跑钉定）。

T8 behavior（本切片，主 Agent 选定，legacy prompt 内容哈希保真门，
先写测试）—— Prompt 只读预检必须增加 legacy 源内容 provenance
一致性门：
1. 读取 legacy 源 ``pipeline/prompt_registry/<source_legacy_id>/prompt.yaml``；
2. 按权威 recipe 复算 ``prompt_content_sha256``：payload 字段为
   schema_version / protocol_id / system_prompt / user_prompt /
   output_fields / label_pools（不含 revision_id），经
   ``json.dumps(..., ensure_ascii=False, sort_keys=True,
   separators=(",", ":"), allow_nan=False).encode("utf-8")`` canonical
   化后取 sha256（权威定义 ``pipeline/prompt_control/core.py::
   prompt_content_sha256``，已对三份真实 manifest：
   v4.1-concise-evidence-json-v1 / v2、v4.1-fixed-full-fields-initial-v1
   离线复现匹配）；
3. 与 legacy ``manifest.json`` 声明的 ``prompt_content_sha256`` 比对；
4. 不匹配 -> ``blocked`` + 非空 reasons + 零写入（fail-closed）；
5. 匹配 -> 保持 ``ready``（T1 正向行为不回归）；
6. 该哈希是 legacy 源 provenance 校验，不要求写入迁移目标（T6 目标
   键集断言继续钉定）；``prompt_yaml_sha256``（原始 prompt.yaml 文件
   字节哈希）是另一套哈希，不得混用或互相替代；
7. 既有三字段迁移行为（T6）不变。

T10 behavior（本切片，主 Agent 选定，M1a 中断安全小行为切片，先写
测试）—— Prompt 真实转换的目标创建过程被中断/失败时不得留下半写入
正式对象：注入“写入已真实开始、未完成”的中断（对当前 production
create_prompt 的目标写调用点 Path.write_text 写入非空严格前缀字节后
抛 OSError，模拟写盘中途崩溃 / IO 错误；写入前即失败的注入不产生
残骸、无法区分原子与非原子实现，故不采用），断言：
1. 目标路径无任何文件 —— 半写/空写残骸同样禁止，正式对象只在完整
   写入后才“存在”；半写残骸既破坏“目标无冲突”预检口径（records/
   下同身份条目以任何文件形式占用即冲突），又让同一转换的重跑被
   create_prompt 的同名冲突语义（PromptConflict）拒绝；
2. legacy 源与旧 active pointers 逐字节不动（records/ 之外零变化）；
3. 恢复正常写入后，在不改映射与源内容的前提下重跑同一转换，必须
   成功创建完整 prompt-v4.1-r1（load_prompt 全契约读回），且结果与
   无中断基线逐字节一致（records/ 整棵子树比对）。
若 production 已具备原子写入/失败清理语义，本切片允许 Unexpected
PASS（转为中断安全回归钉），不得为此制造无意义 production 修改。
自动恢复/续传（识别“同一转换”的已提交事实、凭证绑定映射与源内容）
不在本切片 —— 重跑是对 migrate_prompt 的全新调用；data 复制中断、
history-summary、CLI 亦不在本切片。

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
        # T8 起（本文件内容哈希保真切片），预检还必须增加 legacy 源内容
        #   provenance 一致性门：按权威 recipe（pipeline/prompt_control/
        #   core.py::prompt_content_sha256；六字段 canonical JSON payload，
        #   不含 revision_id）从 legacy prompt.yaml 复算
        #   prompt_content_sha256，与 manifest 声明值比对——不匹配 ->
        #   blocked + 非空 reasons（fail-closed），匹配 -> 保持 ready；
        #   prompt_yaml_sha256（原始文件字节哈希）是另一套哈希，不得混用；
        #   该门不要求把哈希写入迁移目标。
        # 预检不得把 pending/unknown 当 confirmed：该拒绝行为属于配套反向用例切片，
        #   本测试只喂入 status == "user_confirmed" 的映射项，不覆盖拒绝路径。

    def migrate_prompt(root: Path, mapping_item: Mapping[str, object]) -> str
        # T6 真实转换：消费与 precheck 相同形状的映射项（M0 证据结构），
        #   读取 legacy 源 pipeline/prompt_registry/<source_legacy_id>/prompt.yaml
        #   的 system_prompt / user_prompt / output_fields，经既有 Prompt
        #   创建/校验语义（versioning.prompts.create_prompt /
        #   parse_prompt_definition）在 records/prompts/<完整身份>.yaml 创建
        #   正式 Prompt，返回创建的完整 prompt ID（"prompt-v4.1-r1"）。
        #   目标已存在等冲突经既有 Prompt 域错误通道拒绝（PromptConflict，
        #   即 create_prompt 同名冲突语义），不覆盖、不自动改号；
        #   legacy 源与旧 active pointers 逐字节不变；provenance
        #   （prompt_content_sha256 / publishing_code_commit 等）不写入目标
        #   文件（保留在 M0 object-mapping 与后续 history-summary）；
        #   不修改传入映射项。

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
T6（真实转换切片）同口径：migration 模块已存在但 migrate_prompt 入口
缺失时，仍由测试内惰性解析 + 显式 AssertionError 钉出"真实转换行为
缺失"，不让 AttributeError / 原始 import 错误成为 RED。

范围边界：本文件只覆盖 Prompt 迁移 —— T1 ready 正向最小切面、
T2 blocked 反向四类场景、T3 目标冲突精确身份边界回归、T4 同身份非
标准文件形式回归、T5 身份契约收紧、T6 真实转换最小切片（创建
正式 prompt-v4.1-r1 + 同身份重转换不覆盖）、T7 真实转换异常分流
（映射/身份/源文件域错误经 PromptMigrationBlocked、records/ 同
身份占用经 PromptConflict，两路零写入），以及 T8 legacy prompt
内容哈希保真门（precheck 按权威 recipe 复算 prompt_content_sha256
与 manifest 声明值比对：匹配保持 ready、被篡改 blocked + 非空
reasons + 零写入；该哈希是 legacy 源 provenance 校验，不写入迁移
目标，T6 三字段迁移行为不变）、T9 内容哈希门 NaN/Inf 边界
（provenance payload 含 YAML .nan/.inf 特殊浮点字面量时 canonical
化失败必须经报告通道 blocked + 非空 reasons，不得让 ValueError/
TypeError 穿透 precheck 入口，零写入）、T10 目标创建中断安全
（目标写中途被中断不得留下半写入正式对象；legacy 源与旧 active
pointers 逐字节不动；恢复正常后重跑同一转换成功创建完整
prompt-v4.1-r1 且与无中断基线 records/ 子树逐字节一致；注入点为
当前 production 的 Path.write_text，写机制变更时注入点随实际写
路径维护，行为契约不变）；以上切片之外不实现/不要求
data 迁移、history-summary、CLI、自动恢复/续传逻辑（冲突场景只断言 blocked 与零写入；
T10 的“重跑”是对 migrate_prompt 的全新调用，不断言任何自动恢复行为）。T2 身份场景只绑定
behavior 列举的禁用形式（旧哈希、LATEST、短哈希、前导零）；r0、
revision 上限、revision 是否必须等于已确认的 r1 等更细身份规则留给
后续身份收紧切片。T5（本文件身份收紧切片，reviewer 对 2a927d14
身份校验复用通用 parse_version_id 的发现）：通用合法性不等于契约
匹配 —— 合法五类 versioning ID 但 kind 非 prompt（data-v4.1-r1 等）、
或协议与映射声明的 Prompt 协议（M0 确认目标 prompt-v4.1-r1 -> v4.1）
不符（prompt-v4.2-r1、前缀陷阱 prompt-v4.10-r1）一律 blocked。
T3（reviewer 对 2a927d14 的 P3 边界备注）：目标冲突检测必须按精确
身份判断 —— 已有 ``records/prompts/prompt-v4.1-r10.yaml``（不同身份，
字符串上以 ``prompt-v4.1-r1`` 为前缀）不得阻塞目标 ``prompt-v4.1-r1``
的只读预检；真正同身份的 records/ 下条目仍必须 blocked。T4（reviewer
对 F1 修复的 P2 回归）：同身份判定不得依赖 ``Path.stem`` ——
``stem == identity`` 只认标准单后缀 ``.yaml`` 形式，对同身份的无
扩展名（``prompt-v4.1-r1``）、备份后缀（``prompt-v4.1-r1.yaml.bak``）
与复合后缀（``prompt-v4.1-r1.tar.gz``）文件全部误放行；同身份必须
以任何文件形式 blocked，r10 同前缀邻居同时保持 ready。T9（本文件
内容哈希门 NaN/Inf 边界切片，主 Agent 选定）：legacy prompt.yaml 的
provenance payload 含 YAML 特殊浮点字面量 ``.nan`` / ``.inf`` 时
（PyYAML 解析为 float nan/inf，权威 recipe 的
json.dumps(..., allow_nan=False) canonical 化必然抛 ValueError，对该
payload 无法产出任何合法哈希），预检必须 fail-closed 经报告通道返回
blocked + 非空 reasons，不得让 ValueError/TypeError 穿透
precheck_prompt_migration；零写入、legacy 源不变；合法 Prompt 仍
ready（既有正向用例钉定，本切片不改其判定）。所有用例只在
pytest ``tmp_path`` 下模拟仓库根，不触碰真实 records/、workspace/、
pipeline/、finetune/；legacy 树为按 M0 证据布局重建的合成 fixture
（字段值合成、结构与事实字段对齐 M0 证据）。
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from versioning.prompts import (
    PROMPT_REQUIRED_FIELDS,
    PromptConflict,
    load_prompt,
    prompt_path,
)

CONFIRMED_PROMPT_SOURCE_ID = "v4.1-concise-evidence-json-v2"
CONFIRMED_PROMPT_TARGET_ID = "prompt-v4.1-r1"
# 不迁移的历史 sibling（M0：仅进入 history-summary），用于确保实现按映射项
# 定位源，而不是扫描整个 legacy registry。
HISTORY_SIBLING_SOURCE_ID = "v4.1-concise-evidence-json-v1"


def _prompt_content_sha256_of_yaml(prompt_yaml: bytes) -> str:
    """按权威 recipe 从 prompt.yaml 字节复算 legacy prompt_content_sha256。

    权威 recipe（pipeline/prompt_control/core.py::prompt_content_sha256，
    即 _prompt_identity_payload + _canonical_bytes 的组合）：payload 字段
    为 schema_version / protocol_id / system_prompt / user_prompt /
    output_fields / label_pools（不含 revision_id），经
    json.dumps(..., ensure_ascii=False, sort_keys=True,
    separators=(",", ":"), allow_nan=False).encode("utf-8") canonical
    化后取 sha256。该 recipe 已对三份真实 manifest
    （v4.1-concise-evidence-json-v1 / v2、v4.1-fixed-full-fields-initial-v1）
    离线复现匹配。prompt_yaml_sha256（prompt.yaml 原始文件字节的
    sha256）是另一套哈希，不得与本值混用或互相替代。本 fixture 独立
    镜像 recipe 而非 import production，使 production recipe 漂移会先
    在 fixture 前置事实上暴露（复算值 != manifest 声明值）。
    """
    prompt = yaml.safe_load(prompt_yaml)
    payload = {
        "schema_version": prompt["schema_version"],
        "protocol_id": prompt["protocol_id"],
        "system_prompt": prompt["system_prompt"],
        "user_prompt": prompt["user_prompt"],
        "output_fields": prompt["output_fields"],
        "label_pools": prompt["label_pools"],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _legacy_prompt_yaml_full(source_id: str) -> bytes:
    """合成但结构镜像真实 legacy prompt.yaml / active_prompt.yaml 的完整字节。

    真实文件（pipeline/prompt_registry/<id>/prompt.yaml 与
    pipeline/prompt_control/active_prompt.yaml，M0 verified_local）顶层
    字段为 schema_version / protocol_id / revision_id / system_prompt /
    user_prompt / output_fields / label_pools；registry prompt.yaml 与
    活动指针文件逐字节相同（manifest source_sha256 == prompt_yaml_sha256）。
    本 fixture 字段值合成，但结构与上述事实字段一致；output_fields 取
    finetune/README.md 记载的 v4.1 真实四字段；system_prompt 内嵌源
    标记，使"读错源"（扫全 registry、取历史 sibling）的实现无法通过
    结构化相等断言（已确认源与 sibling 内容必须不同）。T8 起（fixture
    recipe 修正）本 builder 是全部 legacy registry fixture 的唯一
    prompt.yaml 来源：权威 recipe 复算需要 schema_version / label_pools
    等全部 payload 字段，旧预检 fixture 的三字段极简 prompt.yaml
    （system_prompt / user_prompt / output_fields）无法支撑内容哈希门。
    """
    return (
        "schema_version: tensile-prompt-control/v1\n"
        "protocol_id: tensile-vlm/v4.1\n"
        f"revision_id: {source_id}\n"
        "\n"
        f"system_prompt: 你是判定材料拉伸断裂行为的视觉模型。"
        f"（合成 fixture，源 {source_id}；仅依据当前视频的可见证据判断）\n"
        "user_prompt: 请逐字段输出 JSON 判定结果。\n"
        "output_fields:\n"
        "  - clip_state\n"
        "  - fracture_mechanism\n"
        "  - fracture_site\n"
        "  - special_case\n"
        "\n"
        "label_pools:\n"
        "  clip_state:\n"
        "    - 未断裂\n"
        "    - 临界未断裂\n"
        "    - 发生断裂\n"
        "    - 已断裂\n"
        "    - 无法判断\n"
        "  fracture_mechanism:\n"
        "    - 韧性断裂\n"
        "    - 脆性断裂\n"
        "    - 界面脱粘\n"
        "    - 爆炸性断裂\n"
        "    - 半脆半韧断裂\n"
        "    - null\n"
        "  fracture_site:\n"
        "    - inside_gauge\n"
        "    - outside_gauge_non_root\n"
        "    - grip_root\n"
        "    - null\n"
        "  special_case:\n"
        "    - 未夹紧\n"
        "    - 视频异常\n"
        "    - null\n"
    ).encode("utf-8")


def _write_legacy_registry_entries(root: Path) -> bytes:
    """在模拟仓库根下按 M0 证据布局写入 legacy Prompt registry 两个条目。

    镜像 source-inventory.yaml pipeline_prompt_registry：每个
    ``<source_id>/`` 下恰有 manifest.json 与 prompt.yaml（已确认源 +
    历史 sibling，prompt.yaml 内容逐源不同）。manifest 字段名与事实
    字段对齐 source-inventory manifest_facts；prompt_content_sha256
    按权威 recipe（_prompt_content_sha256_of_yaml，权威定义
    pipeline/prompt_control/core.py）从该条目自身 prompt.yaml 复算，
    保持源内自洽（真实声明值见 M0 证据 manifest_facts；fixture 字段值
    合成，声明值随合成内容）。fixture 修正说明（至 fdb34d12 的旧
    实现）：旧 fixture 曾把 prompt_content_sha256 写成 prompt.yaml
    全文件字节 sha256——那是 prompt_yaml_sha256 口径，不是内容哈希；
    T8 门一旦落地，该错值会让全部 ready 用例被误 blocked，故先于新
    测试修正。

    返回已确认源 prompt.yaml 的字节。
    """
    registry = root / "pipeline" / "prompt_registry"
    source_commits = {
        CONFIRMED_PROMPT_SOURCE_ID: "98f0476d50138a7577e65426338a44a1baaec040",
        HISTORY_SIBLING_SOURCE_ID: "4c56f7c958b830e43e301739aa4d71b2eb1c1f99",
    }
    for source_id, publishing_commit in source_commits.items():
        entry = registry / source_id
        entry.mkdir(parents=True, exist_ok=True)
        prompt_bytes = _legacy_prompt_yaml_full(source_id)
        (entry / "prompt.yaml").write_bytes(prompt_bytes)
        manifest = {
            "protocol_id": "tensile-vlm/v4.1",
            "prompt_content_sha256": _prompt_content_sha256_of_yaml(prompt_bytes),
            "publishing_code_commit": publishing_commit,
        }
        (entry / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return (registry / CONFIRMED_PROMPT_SOURCE_ID / "prompt.yaml").read_bytes()


def _write_legacy_prompt_registry(root: Path) -> Path:
    """构建 legacy Prompt registry fixture，返回已确认源条目路径。

    registry 两条目经 _write_legacy_registry_entries 写入（manifest 的
    prompt_content_sha256 按权威 recipe 复算，源内自洽）；供 T1/T2/T3/
    T4/T5/T7 预检与转换异常用例消费，T8 内容哈希保真门在此 fixture
    上绑定匹配/篡改两类行为。
    """
    _write_legacy_registry_entries(root)
    return root / "pipeline" / "prompt_registry" / CONFIRMED_PROMPT_SOURCE_ID


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


def _write_full_legacy_prompt_layout(root: Path) -> bytes:
    """构建 T6 真实转换切片的完整 legacy fixture（M0 证据布局）。

    包含：
    - legacy Prompt registry 两条目（已确认源 + 历史 sibling），经
      _write_legacy_registry_entries 写入：prompt.yaml 为结构镜像真实
      legacy 源的七字段合成内容（逐源不同），manifest 的
      prompt_content_sha256 按权威 recipe 从该条目自身 prompt.yaml 复算，
      保持源内自洽，供 T8 内容哈希保真门消费（sibling M0：仅进
      history-summary，不迁移，prompt.yaml 内容与已确认源不同）；
    - 旧 Prompt 活动指针 ``pipeline/prompt_control/active_prompt.yaml``
      （与已确认源 prompt.yaml 逐字节相同，镜像 manifest
      source_sha256 == prompt_yaml_sha256 事实，声明 revision_id 为
      legacy id）；
    - 旧数据活动指针 ``finetune/active_data_release.json``（镜像 M0
      pinned_by 事实；Prompt 转换不得触碰）。

    返回已确认源 prompt.yaml 的字节，供结构化相等断言直接消费。
    """
    confirmed_bytes = _write_legacy_registry_entries(root)

    active_pointer = root / "pipeline" / "prompt_control" / "active_prompt.yaml"
    active_pointer.parent.mkdir(parents=True, exist_ok=True)
    active_pointer.write_bytes(confirmed_bytes)

    data_pointer = root / "finetune" / "active_data_release.json"
    data_pointer.parent.mkdir(parents=True, exist_ok=True)
    data_pointer.write_text(
        json.dumps(
            {
                "release_id": "v4.1.0-ecb5aeb9657c",
                "release_dir": "workspace/data/releases/v4.1.0-ecb5aeb9657c",
                "manifest": (
                    "workspace/data/releases/v4.1.0-ecb5aeb9657c"
                    "/manifest/release_manifest.json"
                ),
                "expected_contract_hash": (
                    "47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937"
                ),
                "expected_manifest_sha256": (
                    "ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return confirmed_bytes


def _resolve_prompt_migration_entry() -> Any:
    """惰性解析 T6 真实转换入口；模块或入口缺失时返回 None。

    RED Gate 设计（与 _resolve_precheck_entry 同口径）：migration 模块
    已存在而 migrate_prompt 入口缺失时返回 None，由调用方以显式行为
    断言钉出"真实转换行为缺失"，不让 AttributeError / 原始 import
    错误成为 RED。
    """
    spec = importlib.util.find_spec("versioning.migration")
    if spec is None:
        return None
    module = importlib.import_module("versioning.migration")
    return getattr(module, "migrate_prompt", None)


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


# ---------------------------------------------------------------------------
# T5：身份收紧 —— 合法 versioning ID 但不符 Prompt 迁移契约 -> blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contract_violating_identity",
    [
        pytest.param("data-v4.1-r1", id="wrong_kind_data"),
        pytest.param("train-v4.1-r1", id="wrong_kind_train"),
        pytest.param("model-v4.1-r1", id="wrong_kind_model"),
        pytest.param("eval-v4.1-r1", id="wrong_kind_eval"),
        pytest.param("prompt-v4.2-r1", id="wrong_protocol_v4_2"),
        pytest.param("prompt-v4.10-r1", id="wrong_protocol_v4_10"),
    ],
)
def test_precheck_blocks_target_identity_mismatching_prompt_contract(
    tmp_path: Path, contract_violating_identity: str
) -> None:
    """合法 versioning ID 但不符 Prompt 迁移契约 -> blocked + 零写入（fail-closed）。

    身份收紧口径（本切片 behavior，M1a 最小身份契约切片）：Prompt 只读
    预检的目标身份不仅要通过 versioning/ids.py 的通用合法性解析（五类完整
    ``<kind>-v<协议>-r<N>``），还必须与 Prompt 迁移契约本身匹配：
    - kind 必须是 prompt：``data-v4.1-r1`` 等其余四类的合法 ID 一律不得
      被 Prompt precheck 接受为 ready；
    - 协议必须与映射声明的 Prompt 协议一致：M0 object-mapping.yaml 中
      用户确认的 Prompt 目标是 ``prompt-v4.1-r1``（协议 v4.1），协议
      不同的合法 ID 不符契约。

    通用合法性 ≠ 契约匹配（本切片要钉住的实现缺陷，reviewer 已复现）：
    ``parse_version_id`` 对五类 kind 一律放行，当前实现复用它，因此
    ``data-v4.1-r1`` 会被 Prompt precheck 误判为 ready；kind 专属的
    权威口径在 ids.py 中已存在（``parse_prompt_id`` / kind 白名单）。

    代表例（target_path 保持合法不动，使 blocked 只能由身份字段引起）：
    - wrong_kind_data：``data-v4.1-r1`` —— M0 同文件 data_mapping.items
      的已确认数据目标值，最 plausible 的映射串行复制错误；也是
      reviewer 复现的现行为缺陷（当前实现误返回 ready）；
    - wrong_kind_train / wrong_kind_model / wrong_kind_eval：其余三类
      合法 ID，钉死“kind 必须是 prompt”是白名单语义，而非只拒 data 的
      黑名单；
    - wrong_protocol_v4_2：``prompt-v4.2-r1`` —— kind 合法、协议不是
      映射声明的 v4.1；
    - wrong_protocol_v4_10：``prompt-v4.10-r1`` —— 协议 ``v4.10`` 在
      字符串上以 ``v4.1`` 为前缀（与 T3/T4 的 r1/r10 前缀陷阱同类），
      钉死协议必须精确等于 v4.1，不得以前缀/包含匹配放行。

    捕获的合理但错误实现：
    - 只复用 ``parse_version_id`` 通用合法性、不做契约匹配（当前实现
      ——RED 起点）-> 全部参数失败（ready 误判）；
    - kind 黑名单式校验（只拒 data、其余放行）-> train/model/eval
      参数失败；
    - 只查 kind 不查协议（kind 合法即放行）-> 两个 wrong_protocol
      参数失败；
    - 协议前缀/包含匹配（``"v4.1" in identity`` 或 startswith）->
      wrong_protocol_v4_10 参数失败（v4.10 含前缀 v4.1 被误放行）；
    - 不读 candidate_target_identity、从 target_path 文件名反推身份 ->
      本用例 target_path 合法而身份字段不符契约，反推实现误返回 ready；
    - 身份不符契约时“顺手规范化”（写入、改名或生成目标文件）->
      零写入断言失败；
    - blocked 不带 reasons -> reasons 断言失败。
    revision 不在本切片口径内（不测试 prompt-v4.1-r2 等仅 revision 不同
    的输入）；r0、revision 上限等更细身份规则仍留后续切片。
    """
    _write_legacy_prompt_registry(tmp_path)
    mapping_item = _confirmed_prompt_mapping_item()
    mapping_item["candidate_target_identity"] = contract_violating_identity

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


# ---------------------------------------------------------------------------
# T6：真实转换 —— 已确认 Prompt 映射创建正式 prompt-v4.1-r1
# ---------------------------------------------------------------------------


def test_confirmed_prompt_mapping_real_conversion_creates_formal_prompt(
    tmp_path: Path,
) -> None:
    r"""已确认 Prompt 映射的真实转换：创建正式 prompt-v4.1-r1、保真且零越界。

    当前 behavior（M1a Prompt 真实转换最小切片）—— 对已确认映射
    ``v4.1-concise-evidence-json-v2`` -> ``prompt-v4.1-r1`` 执行真实转换：
    1. 在新 versioning 存储创建正式 Prompt ``prompt-v4.1-r1``
       （records/prompts/prompt-v4.1-r1.yaml）；
    2. 转换后的 system_prompt / user_prompt / output_fields 与 legacy 源
       结构化相等（逐字段、保序）；
    3. legacy 源树逐字节不变；
    4. 旧 active pointers（pipeline/prompt_control/active_prompt.yaml 与
       finetune/active_data_release.json）不被修改，仍声明 legacy 身份；
    5. 同身份目标已存在时不覆盖（经既有 Prompt 冲突域通道拒绝）；
    6. 复用既有 Prompt 创建/校验语义（load_prompt 全契约读回），
       不直接伪造目标文件；
    7. 不产生 data 转换 / history-summary / CLI / 中断恢复副作用。

    捕获的合理但错误实现：
    - 字节复制 legacy prompt.yaml 到目标位置（身份不改）-> 目标缺
      ``version: prompt-v4.1-r1`` 且携带 schema_version / protocol_id /
      revision_id / label_pools 等 legacy 字段，load_prompt 抛
      PromptSchemaError（version 字段缺失/与文件名不一致），键集断言
      同时失败；
    - 字段丢失 / 内容截断 / output_fields 乱序或误取 label_pools 键 ->
      结构化相等断言失败（output_fields 与真实 v4.1 四字段逐项相等且
      保序）；
    - 读错源（扫全 registry、取历史 sibling、从其他文件拼字段）->
      sibling 的 system_prompt 与已确认源不同（fixture 内嵌源标记），
      结构化相等断言失败；
    - 修改 legacy 源（改写 prompt.yaml / manifest.json）或旧 active
      pointers（切换 active_prompt.yaml 指向新身份、动数据指针）->
      既有条目逐字节对比失败，revision_id / release_id 显式断言失败；
    - 覆盖已存在正式对象（同身份重转换静默成功、覆盖、自动改号 r2、
      清理重建）-> pytest.raises(PromptConflict) 失败，或目标字节/全树
      快照断言失败；
    - 绕过既有创建语义伪造目标文件（不经 schema/身份校验直接写盘）->
      load_prompt 完整契约读回失败（version 字段与文件名一致、五必填
      字段齐全且值合法），或键集 != PROMPT_REQUIRED_FIELDS；
    - provenance 写入目标文件（prompt_content_sha256 /
      publishing_code_commit 等非标准字段）-> 键集断言失败（provenance
      保留在 M0 object-mapping 与后续 history-summary，不进目标）；
    - 顺手产生本切片外副作用（history-summary 文件、staging、records/
      下别名或 current 指针、sibling 的正式目标、报告/缓存文件）->
      新增条目集合恰为目标文件路径及其目录的断言失败；
    - 就地修改传入映射项（M0 证据的内存镜像）-> 映射项不变断言失败；
    - 对合法已确认输入 fail-closed（抛错或未创建目标）-> 返回值与目标
      存在性断言失败。

    冲突拒绝通道的绑定说明：真实转换是写入操作，与只读预检的报告通道
    （T1 已绑定 status 属性返回）不同；既有 Prompt 创建语义（create_prompt）
    对同名正式对象一致抛 PromptConflict（versioning/prompts.py 域错误），
    本切片按"复用既有创建语义"绑定该通道——不覆盖、不自动改号、不静默
    成功。中断后的恢复/续传语义不在本切片（spec：仅能恢复可证实属于同
    一操作的未完成工作），故重转换按冲突停止，而非幂等续传。

    RED Gate：本测试编写时 versioning.migration 尚无 migrate_prompt 入口；
    测试内惰性解析入口并以显式 AssertionError 钉出"真实转换行为缺失"，
    失败发生在 fixture 构建、前置事实断言与全树快照真实执行之后，
    不让原始 ImportError/ModuleNotFoundError/AttributeError 成为 RED。
    """
    mapping_item = _confirmed_prompt_mapping_item()
    confirmed_prompt_bytes = _write_full_legacy_prompt_layout(tmp_path)

    # fixture 前置事实（对齐 M0 证据）：已确认源必需文件齐全；历史
    # sibling 完整且内容与已确认源不同（读错源可捕获）；活动指针与
    # 已确认源逐字节相同并声明 legacy 身份；数据指针声明 legacy
    # release；目标根不存在；映射 target_path 与权威 prompt_path 一致。
    confirmed_entry = (
        tmp_path / "pipeline" / "prompt_registry" / CONFIRMED_PROMPT_SOURCE_ID
    )
    assert (confirmed_entry / "manifest.json").is_file()
    assert (confirmed_entry / "prompt.yaml").is_file()
    legacy_raw = yaml.safe_load(confirmed_prompt_bytes)
    assert legacy_raw["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID
    assert legacy_raw["output_fields"] == [
        "clip_state",
        "fracture_mechanism",
        "fracture_site",
        "special_case",
    ]
    sibling_prompt = (
        tmp_path
        / "pipeline"
        / "prompt_registry"
        / HISTORY_SIBLING_SOURCE_ID
        / "prompt.yaml"
    )
    sibling_raw = yaml.safe_load(sibling_prompt.read_bytes())
    assert sibling_raw["system_prompt"] != legacy_raw["system_prompt"]
    active_pointer = tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml"
    assert active_pointer.read_bytes() == confirmed_prompt_bytes
    data_pointer = tmp_path / "finetune" / "active_data_release.json"
    assert (
        json.loads(data_pointer.read_text(encoding="utf-8"))["release_id"]
        == "v4.1.0-ecb5aeb9657c"
    )
    assert not (tmp_path / "records").exists()
    assert prompt_path(tmp_path, CONFIRMED_PROMPT_TARGET_ID) == tmp_path / str(
        mapping_item["target_path"]
    )

    before = _snapshot_tree(tmp_path)

    migrate_prompt = _resolve_prompt_migration_entry()
    assert migrate_prompt is not None, (
        "真实 Prompt 迁移转换行为缺失：versioning.migration 未提供 "
        "migrate_prompt 入口（当前 behavior 未实现）"
    )

    created = migrate_prompt(tmp_path, mapping_item)
    assert created == CONFIRMED_PROMPT_TARGET_ID, (
        f"真实转换应返回创建的完整 prompt ID {CONFIRMED_PROMPT_TARGET_ID!r}："
        f"实际 {created!r}"
    )

    # 1+6：目标经既有 Prompt 契约可完整读回（version 字段与文件名一致、
    # 五必填字段齐全且值合法）——字节复制或绕过校验伪造的文件无法通过。
    target_file = (
        tmp_path / "records" / "prompts" / f"{CONFIRMED_PROMPT_TARGET_ID}.yaml"
    )
    assert target_file.is_file()
    converted = load_prompt(tmp_path, CONFIRMED_PROMPT_TARGET_ID)
    assert converted.version == CONFIRMED_PROMPT_TARGET_ID

    # 2：三字段与 legacy 源结构化相等（逐字段、保序；与真实 v4.1 四字段
    # 一致——fixture 前置事实已钉死源值）。
    assert converted.system_prompt == legacy_raw["system_prompt"]
    assert converted.user_prompt == legacy_raw["user_prompt"]
    assert converted.output_fields == tuple(legacy_raw["output_fields"])
    assert converted.output_fields == (
        "clip_state",
        "fracture_mechanism",
        "fracture_site",
        "special_case",
    )

    # 键集恰为标准 prompt 字段：provenance（prompt_content_sha256 /
    # publishing_code_commit）与 legacy 字段（schema_version / protocol_id /
    # revision_id / label_pools）均不得写入目标文件。
    target_raw = yaml.safe_load(target_file.read_text(encoding="utf-8"))
    assert set(target_raw) == set(PROMPT_REQUIRED_FIELDS), (
        f"目标文件键集必须恰为标准 prompt 字段 {PROMPT_REQUIRED_FIELDS}："
        f"实际 {sorted(target_raw)}"
    )

    # 3+4：既有条目（legacy 源树 + 旧 active pointers）逐字节不变，无删除、
    # 无修改；旧指针仍声明 legacy 身份。
    after = _snapshot_tree(tmp_path)
    changed = [
        rel for rel, content in before.items() if after.get(rel) != content
    ]
    assert not changed, (
        f"真实转换不得修改或删除任何既有条目（legacy 源与旧 active "
        f"pointers 逐字节不变）：{sorted(changed)}"
    )
    assert (
        yaml.safe_load(active_pointer.read_bytes())["revision_id"]
        == CONFIRMED_PROMPT_SOURCE_ID
    )
    assert (
        json.loads(data_pointer.read_text(encoding="utf-8"))["release_id"]
        == "v4.1.0-ecb5aeb9657c"
    )

    # 7：新增条目恰为目标文件及其目录——无 staging、无报告/缓存文件、
    # 无 history-summary、无 records/ 别名或 current 指针、无历史
    # sibling 的正式目标、无 provenance sidecar。
    added = set(after) - set(before)
    assert added == {
        "records",
        "records/prompts",
        str(mapping_item["target_path"]),
    }, f"真实转换只应新增目标文件及其目录：实际新增 {sorted(added)}"

    # 5：同身份重转换必须经既有 Prompt 冲突域通道拒绝（PromptConflict，
    # 即 create_prompt 同名冲突语义）——不覆盖、不自动改号、不清理重建、
    # 不静默成功；目标与全树保持第一次转换后的状态。
    first_target_bytes = target_file.read_bytes()
    after_first = _snapshot_tree(tmp_path)
    with pytest.raises(PromptConflict):
        migrate_prompt(tmp_path, mapping_item)
    assert target_file.read_bytes() == first_target_bytes
    assert _snapshot_tree(tmp_path) == after_first

    # 映射项是 M0 证据的内存镜像：真实转换不得就地修改。
    assert mapping_item == _confirmed_prompt_mapping_item()


# ---------------------------------------------------------------------------
# T7：真实转换异常分流 —— 域错误经 PromptMigrationBlocked、records/ 同
# 身份占用经 PromptConflict 拒绝，两路均零写入（reviewer 对 1a7f011d 的 P3）
# ---------------------------------------------------------------------------


def _resolve_prompt_migration_blocked_type() -> Any:
    """惰性解析迁移域错误异常类；模块或类缺失时返回 None。

    RED Gate 设计（与 _resolve_precheck_entry /
    _resolve_prompt_migration_entry 同口径）：不让原始 ImportError /
    AttributeError 成为 RED，由调用方以显式断言钉出“迁移域错误
    异常通道缺失”。
    """
    spec = importlib.util.find_spec("versioning.migration")
    if spec is None:
        return None
    module = importlib.import_module("versioning.migration")
    return getattr(module, "PromptMigrationBlocked", None)


@pytest.mark.parametrize(
    "block_kind",
    [
        pytest.param("mapping_status_pending", id="mapping_status_pending"),
        pytest.param("identity_legacy_old", id="identity_legacy_old"),
        pytest.param("source_manifest_missing", id="source_manifest_missing"),
        pytest.param(
            "mapping_pending_plus_records_occupation",
            id="mapping_pending_plus_records_occupation",
        ),
    ],
)
def test_migrate_prompt_domain_errors_raise_prompt_migration_blocked(
    tmp_path: Path, block_kind: str
) -> None:
    """预检非 ready 且含映射/身份/源文件类域错误 -> PromptMigrationBlocked + 零写入。

    T7 behavior（reviewer 对 1a7f011d 的 P3 缺口，先写测试）：migrate_prompt
    是写入入口，预检非 ready 的拒绝必须按失败类别分流 —— 映射项未确认
    （status != user_confirmed）、候选目标身份非法/不符 Prompt 迁移契约、
    legacy 源必需文件缺失三类域错误必须经迁移域错误通道
    ``PromptMigrationBlocked`` 拒绝（fail-closed），且零写入；域错误与
    目标冲突并存时域错误通道优先（仍 PromptMigrationBlocked），不得因
    同时存在冲突而改走 PromptConflict 通道。

    四个代表场景（各自保持映射 target_path 空闲，隔离 target_path 冲突
    分支；前三者各取一类域错误代表例，域内其余形式已由 T2/T5 在预检层
    钉定，本用例只钉真实转换入口的分流通道）：
    - mapping_status_pending：映射 status 为 pending_user_check（映射类；
      M0 status_field_legend“未生效，禁止写入”）；
    - identity_legacy_old：候选目标身份复用 legacy prompt 旧身份
      （v4.1-concise-evidence-json-v2；身份类，T2 legacy_prompt_old_identity
      同款输入）；
    - source_manifest_missing：legacy 源 manifest.json 缺失（源文件类；
      T2 manifest_missing 同款输入）；
    - mapping_pending_plus_records_occupation：status 未确认 + records/
      下已存在同身份条目（域错误与冲突并存 -> 域错误通道优先）。

    前置锚定：同一输入的只读预检必须 blocked（预检口径由 T2/T5 钉定，
    此处只锚定 T7 分流的触发前提成立；预检零写入由 T1/T2 钉定）。

    捕获的合理但错误实现：
    - 域错误笼统抛 PromptError / ValueError（不定义迁移域错误通道）
      -> pytest.raises(PromptMigrationBlocked) 失败；
    - 域错误误走冲突通道（一律抛 PromptConflict）-> raises 断言失败
      （PromptConflict 不是 PromptMigrationBlocked 子类）；
    - 把 PromptMigrationBlocked 实现为 PromptConflict 子类（通道合并，
      调用方 except PromptConflict 会吞掉域错误拒绝）-> isinstance 守卫
      断言失败；
    - 预检非 ready 仍继续转换（blocked 当警告跳过、先创建目标/staging
      再抛错、“创建后回滚”不彻底）-> raises 断言失败（无异常抛出）或
      全树快照断言失败：拒绝路径同样零写入；
    - 混合场景见冲突即抛 PromptConflict（域错误不优先）->
      mapping_pending_plus_records_occupation 参数失败；
    - 拒绝时改写 legacy 源 / 清理或改名既有 records/ 条目 ->
      全树快照断言失败。

    TDD 口径：本用例先于运行写入（1a7f011d 已含分流实现）；允许
    Unexpected PASS —— 分流行为已满足时本用例为回归钉定，不触发任何
    production 修改。
    """
    _write_legacy_prompt_registry(tmp_path)
    mapping_item = _confirmed_prompt_mapping_item()
    occupied: Path | None = None
    if block_kind == "mapping_status_pending":
        mapping_item["status"] = "pending_user_check"
    elif block_kind == "identity_legacy_old":
        mapping_item["candidate_target_identity"] = CONFIRMED_PROMPT_SOURCE_ID
    elif block_kind == "source_manifest_missing":
        manifest = (
            tmp_path
            / "pipeline"
            / "prompt_registry"
            / CONFIRMED_PROMPT_SOURCE_ID
            / "manifest.json"
        )
        manifest.unlink()
        assert not manifest.is_file()
    else:
        # mapping_pending_plus_records_occupation：域错误与目标冲突并存。
        mapping_item["status"] = "pending_user_check"
        occupied = (
            tmp_path / "records" / "archive" / f"{CONFIRMED_PROMPT_TARGET_ID}.yaml"
        )
        occupied.parent.mkdir(parents=True)
        occupied.write_bytes(_EXISTING_TARGET_BYTES)

    # 前置事实：映射 target_path 空闲（拒绝不得由 target_path 冲突引起）；
    # 混合场景下 records/ 同身份占用条目已存在。
    assert not (tmp_path / str(mapping_item["target_path"])).exists()
    if occupied is not None:
        assert occupied.is_file()

    # 前置锚定：同一输入的只读预检必须 blocked。
    _run_blocked_precheck(tmp_path, mapping_item)

    before = _snapshot_tree(tmp_path)

    migrate_prompt = _resolve_prompt_migration_entry()
    assert migrate_prompt is not None, (
        "真实 Prompt 迁移转换行为缺失：versioning.migration 未提供 "
        "migrate_prompt 入口（当前 behavior 未实现）"
    )
    blocked_type = _resolve_prompt_migration_blocked_type()
    assert blocked_type is not None, (
        "Prompt 迁移域错误异常通道缺失：versioning.migration 未定义 "
        "PromptMigrationBlocked（当前 behavior 未实现）"
    )

    with pytest.raises(blocked_type) as excinfo:
        migrate_prompt(tmp_path, mapping_item)

    # 两条异常通道互斥可辨：域错误拒绝不得误走冲突通道。
    assert not isinstance(excinfo.value, PromptConflict), (
        "映射/身份/源文件类域错误必须经 PromptMigrationBlocked 拒绝，"
        "不得误走 PromptConflict 冲突通道"
    )

    # 零写入：全树逐字节不变 —— 不创建 records/、目标条目或 staging，
    # 不改 legacy 源；混合场景下既有占用条目哨兵字节保持原样。
    assert _snapshot_tree(tmp_path) == before
    if occupied is not None:
        assert occupied.read_bytes() == _EXISTING_TARGET_BYTES
    else:
        assert not (tmp_path / "records").exists()


def test_migrate_prompt_records_identity_occupation_raises_prompt_conflict(
    tmp_path: Path,
) -> None:
    """预检非 ready 仅因 records/ 同身份占用（target_path 空闲）-> PromptConflict + 零写入。

    T7 behavior（reviewer 对 1a7f011d 的 P3 缺口，先写测试）：映射项、
    候选身份、legacy 源全部合格，映射 target_path 空闲，但 records/ 下
    已存在同身份条目（records/archive/prompt-v4.1-r1.yaml，防改名冲突，
    与 T2 same_identity_in_records 同构）时，migrate_prompt 不得绕过同
    身份占用在空闲 target_path 静默创建正式对象，必须复用既有 Prompt
    冲突域通道 ``PromptConflict`` 拒绝（与 target_path 被占用时
    create_prompt 的同名冲突语义同通道），且零写入。

    与 T6 冲突切片的分工：T6 已绑定 target_path 被同身份正式对象占用
    -> 重转换 PromptConflict 不覆盖；本用例补齐另一支占用形态 ——
    占用在 records/ 他处、target_path 空闲。若实现只依赖 create_prompt
    的目标文件存在性检查，本场景会被静默绕过（在 target_path 创建
    第二个同身份正式对象），因此“target_path 不得被创建”是本用例的
    核心断言。

    前置锚定：同一输入的只读预检必须 blocked（T2
    same_identity_in_records 同口径；预检口径本身由 T2/T3/T4 钉定）。

    捕获的合理但错误实现：
    - 不做 records/ 同身份扫描、只依赖 create_prompt 目标文件存在性
      检查 -> 在空闲 target_path 静默创建正式对象：raises 断言失败
      （未抛 PromptConflict）且 target_path 存在性断言失败；
    - 误走迁移域错误通道（抛 PromptMigrationBlocked）-> raises 断言
      失败（PromptMigrationBlocked 不是 PromptConflict 子类）；
    - 冲突时自动改号（r2）继续转换 -> raises 断言失败（未抛冲突异常）；
    - 冲突时改名/移动/删除既有占用条目或新增任何文件 -> 哨兵字节与
      全树快照断言失败。

    TDD 口径：本用例先于运行写入（1a7f011d 已含分流实现）；允许
    Unexpected PASS —— 分流行为已满足时本用例为回归钉定，不触发任何
    production 修改。
    """
    _write_legacy_prompt_registry(tmp_path)
    mapping_item = _confirmed_prompt_mapping_item()
    occupied = (
        tmp_path / "records" / "archive" / f"{CONFIRMED_PROMPT_TARGET_ID}.yaml"
    )
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(_EXISTING_TARGET_BYTES)

    # 前置事实：records/ 下已存在同身份条目；映射指定的 target_path
    # 空闲 —— 映射、身份、legacy 源全部合格，blocked 只能由同身份占用
    # 引起。
    assert occupied.is_file()
    assert not (tmp_path / str(mapping_item["target_path"])).exists()

    # 前置锚定：同一输入的只读预检必须 blocked。
    _run_blocked_precheck(tmp_path, mapping_item)

    before = _snapshot_tree(tmp_path)

    migrate_prompt = _resolve_prompt_migration_entry()
    assert migrate_prompt is not None, (
        "真实 Prompt 迁移转换行为缺失：versioning.migration 未提供 "
        "migrate_prompt 入口（当前 behavior 未实现）"
    )

    with pytest.raises(PromptConflict) as excinfo:
        migrate_prompt(tmp_path, mapping_item)

    # 两条异常通道互斥可辨：仅冲突拒绝不得误走迁移域错误通道
    # （PromptMigrationBlocked 类缺失时该守卫由域错误用例的显式断言
    # 兜底；守卫同时把“PromptMigrationBlocked 被实现为 PromptConflict
    # 子类”的通道合并错误判失败）。
    blocked_type = _resolve_prompt_migration_blocked_type()
    if blocked_type is not None:
        assert not isinstance(excinfo.value, blocked_type), (
            "仅 records/ 同身份占用（target_path 空闲）的冲突必须经 "
            "PromptConflict 拒绝，不得误走 PromptMigrationBlocked 通道"
        )

    # 零写入：不得绕过改名冲突静默在 target_path 创建正式对象，也不得
    # 改名/覆盖/清理既有占用条目；全树逐字节不变。
    assert not (tmp_path / str(mapping_item["target_path"])).exists()
    assert occupied.read_bytes() == _EXISTING_TARGET_BYTES
    assert _snapshot_tree(tmp_path) == before


# ---------------------------------------------------------------------------
# T8：legacy prompt 内容哈希保真门 —— precheck 换权威 recipe 复算
# prompt_content_sha256 并与 manifest 声明值比对（M1a 内容 provenance 切片，
# 先写失败测试）
# ---------------------------------------------------------------------------


def test_precheck_prompt_content_sha256_match_returns_ready(tmp_path: Path) -> None:
    r"""prompt_content_sha256 复算匹配 -> 只读预检保持 ready + 零写入。

    T8 behavior（正向，主 Agent 选定）：Prompt 只读预检增加 legacy 源
    内容 provenance 一致性门 —— 按 pipeline/prompt_control/core.py 的
    权威 recipe（六字段 canonical JSON payload：schema_version /
    protocol_id / system_prompt / user_prompt / output_fields /
    label_pools，不含 revision_id）从 legacy prompt.yaml 复算
    ``prompt_content_sha256``，与 manifest 声明值一致时必须保持 T1 的
    ready 行为（内容哈希门不得对合法 legacy 源误伤）。

    fixture 前置事实同时钉死两套哈希口径的可区分性：manifest 声明值
    按权威 recipe 复算，且 != prompt.yaml 原始文件字节的 sha256
    （prompt_yaml_sha256 口径），也与历史 sibling 的内容哈希不同。
    因此任何混用两套哈希、复算读错源、或 canonical 化偏离权威
    recipe（误含 revision_id、漏 sort_keys / separators、
    ensure_ascii=True、放开 allow_nan 等）的实现都会在本合法输入上
    复算出不同值 -> 误 blocked -> 本用例失败。

    捕获的合理但错误实现：
    - 完全不实现内容哈希门（当前 production）-> 本正向输入与"无门"
      实现同判 ready，本用例不可区分（预期 PASS，非 RED）；RED 证据
      由配套 test_precheck_blocks_prompt_content_sha256_mismatch 给出。
      本用例的价值在门实现后转为 recipe/过严回归钉；
    - 混用 prompt_yaml_sha256 口径（按文件字节复算内容哈希）->
      复算值 != 声明值 -> 误 blocked -> status 断言失败；
    - 复算读错哈希来源（历史 sibling 的 prompt.yaml / active pointer /
      manifest 自身）-> 与已确认源声明值不匹配 -> 误 blocked ->
      status 断言失败；
    - 匹配时顺手写入（缓存复算值、规范化 legacy 源、写报告文件）->
      全树快照断言失败；
    - 匹配时 fail-closed（blocked 或抛错替代报告）-> status 断言失败。
    """
    source_entry = _write_legacy_prompt_registry(tmp_path)

    # 前置事实：manifest 声明值 == 权威 recipe 复算值（合法 legacy 源）；
    # 且 != prompt.yaml 文件字节 sha256（两套哈希口径可区分）；
    # 且 != 历史 sibling 的内容哈希（读错源可捕获）。
    prompt_bytes = (source_entry / "prompt.yaml").read_bytes()
    manifest = json.loads(
        (source_entry / "manifest.json").read_text(encoding="utf-8")
    )
    declared = manifest["prompt_content_sha256"]
    assert declared == _prompt_content_sha256_of_yaml(prompt_bytes), (
        "fixture 前置事实失败：manifest 声明值必须等于按权威 recipe "
        "复算的 prompt_content_sha256"
    )
    assert declared != hashlib.sha256(prompt_bytes).hexdigest(), (
        "fixture 前置事实失败：prompt_content_sha256 必须与 prompt.yaml "
        "文件字节 sha256（prompt_yaml_sha256 口径）不同，否则两套哈希"
        "口径不可区分"
    )
    sibling_prompt = (
        tmp_path
        / "pipeline"
        / "prompt_registry"
        / HISTORY_SIBLING_SOURCE_ID
        / "prompt.yaml"
    ).read_bytes()
    assert _prompt_content_sha256_of_yaml(sibling_prompt) != declared, (
        "fixture 前置事实失败：已确认源与历史 sibling 的内容哈希必须"
        "不同（否则读错源不可捕获）"
    )
    assert not (tmp_path / "records").exists()

    before = _snapshot_tree(tmp_path)

    precheck = _resolve_precheck_entry()
    assert precheck is not None, (
        "只读 Prompt 迁移预检行为缺失：versioning.migration 未提供 "
        "precheck_prompt_migration 入口（当前 behavior 未实现）"
    )
    report = precheck(tmp_path, _confirmed_prompt_mapping_item())

    assert report.status == "ready", (
        f"prompt_content_sha256 复算匹配的合法 legacy 源必须保持 ready"
        f"（内容 provenance 门不得误伤）：实际 status={report.status!r}，"
        f"reasons={report.reasons!r}"
    )

    # 目标根零写入 + 全树零写入（复算/比对本身不得有任何写副作用）。
    assert not (tmp_path / "records").exists()
    assert _snapshot_tree(tmp_path) == before


@pytest.mark.parametrize(
    "tamper_kind",
    [
        pytest.param(
            "declared_yaml_file_bytes_hash", id="declared_yaml_file_bytes_hash"
        ),
        pytest.param(
            "declared_sibling_content_hash", id="declared_sibling_content_hash"
        ),
        pytest.param(
            "prompt_yaml_content_modified", id="prompt_yaml_content_modified"
        ),
    ],
)
def test_precheck_blocks_prompt_content_sha256_mismatch(
    tmp_path: Path, tamper_kind: str
) -> None:
    r"""prompt_content_sha256 复算值与 manifest 声明值不匹配 -> blocked + 零写入。

    T8 behavior（反向，主 Agent 选定，先写失败测试）：只读预检必须
    fail-closed 地校验 legacy 源内容 provenance —— 按权威 recipe（见
    _prompt_content_sha256_of_yaml）从 legacy prompt.yaml 复算
    prompt_content_sha256，与 manifest 声明值不匹配时返回 blocked
    （非空 reasons）且零写入。三个篡改场景的映射项、候选身份、
    target_path 与 records/ 均保持合法，使 blocked 只能由内容哈希门
    引起（隔离变量）：
    - declared_yaml_file_bytes_hash：manifest 声明值被换成 prompt.yaml
      原始文件字节的 sha256 —— 既是声明值篡改（与权威 recipe 复算值
      不匹配），也是错误 recipe 陷阱：按文件字节口径复算的实现会
      在此得到"匹配" -> 误 ready -> 本参数失败。该口径正是本轮
      fixture 修正前 fixture 自己写错的哈希（prompt.yaml 全文件字节
      sha256 误当 prompt_content_sha256），钉死不得回退；
    - declared_sibling_content_hash：声明值被换成历史 sibling 的真实
      内容哈希（复制错 manifest 行的 plausible 篡改形态；值本身是
      well-formed sha256，钉死"只校验声明值格式合法就放行"的实现）；
    - prompt_yaml_content_modified：prompt.yaml 的 system_prompt 被篡改
      而 manifest 声明值保持原值（provenance 反向漂移：内容已变、
      声明未更新）。

    捕获的合理但错误实现：
    - 完全不复算内容哈希（当前 production —— RED 起点）：预检只查
      文件存在性，三个参数全部误 ready -> status 断言失败；
    - 只从 manifest 回读声明值与自身比对（无复算参与）-> 三个参数
      全部误 ready -> status 断言失败；
    - 按文件字节口径复算 -> declared_yaml_file_bytes_hash 参数复算值
      == 被篡改的声明值 -> 误 ready -> 本参数失败；
    - 只校验声明值是 64-hex 格式、不与复算值比对 ->
      declared_sibling_content_hash 参数误 ready -> 本参数失败；
    - 复算 payload 字段缺失/多余（漏 label_pools、误含 revision_id）
      或 canonical 化偏离权威 recipe -> 复算口径漂移：合法输入误
      blocked（正向用例失败）或篡改输入漏检（对应参数失败）；
    - 不匹配时"顺手修复"（改写 manifest / prompt.yaml、重建源条目、
      写缓存）-> 全树快照断言失败；
    - 不匹配时以未类型化异常替代报告 -> T1 已绑定报告返回通道，
      _run_blocked_precheck 判失败；
    - blocked 不带 reasons -> reasons 断言失败。

    RED Gate：本用例编写时 versioning.migration 的
    precheck_prompt_migration 尚未实现内容哈希门（只查映射/身份/
    源文件存在性/目标冲突），三个参数均预期失败（status='ready'
    误判），即有效 RED；门实现后本用例转为篡改回归钉。
    """
    source_entry = _write_legacy_prompt_registry(tmp_path)
    manifest_path = source_entry / "manifest.json"
    prompt_path = source_entry / "prompt.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prompt_bytes = prompt_path.read_bytes()

    if tamper_kind == "declared_yaml_file_bytes_hash":
        manifest["prompt_content_sha256"] = (
            hashlib.sha256(prompt_bytes).hexdigest()
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif tamper_kind == "declared_sibling_content_hash":
        sibling_manifest = json.loads(
            (
                tmp_path
                / "pipeline"
                / "prompt_registry"
                / HISTORY_SIBLING_SOURCE_ID
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        manifest["prompt_content_sha256"] = sibling_manifest[
            "prompt_content_sha256"
        ]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        tampered = prompt_bytes.replace(
            "视觉模型".encode("utf-8"),
            "视觉模型（prompt.yaml 内容被篡改，manifest 声明值未更新）".encode(
                "utf-8"
            ),
        )
        assert tampered != prompt_bytes, "fixture 前置事实失败：内容篡改必须生效"
        prompt_path.write_bytes(tampered)

    # 前置事实：篡改后按权威 recipe 复算的值必与 manifest 声明值不匹配
    # （mismatch 真实存在，且只能由内容哈希门捕获）。
    recomputed = _prompt_content_sha256_of_yaml(prompt_path.read_bytes())
    declared = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "prompt_content_sha256"
    ]
    assert recomputed != declared, (
        "fixture 前置事实失败：篡改必须造成复算值与声明值不匹配"
    )
    assert not (tmp_path / "records").exists()

    before = _snapshot_tree(tmp_path)

    _run_blocked_precheck(tmp_path, _confirmed_prompt_mapping_item())

    # 零写入：不创建 records/，不改被篡改的 legacy 源（含 manifest /
    # prompt.yaml 本身），全树逐字节不变。
    assert not (tmp_path / "records").exists()
    assert _snapshot_tree(tmp_path) == before


# ---------------------------------------------------------------------------
# T9：内容哈希门 NaN/Inf 边界 —— provenance payload 含 YAML .nan/.inf 特殊
# 浮点字面量时，canonical 化失败必须经报告通道 blocked（不得泄漏
# ValueError/TypeError），零写入
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nan_inf_literal",
    [
        pytest.param(".nan", id="nan_literal_in_payload"),
        pytest.param(".inf", id="inf_literal_in_payload"),
    ],
)
def test_precheck_blocks_nan_inf_in_provenance_payload(
    tmp_path: Path, nan_inf_literal: str
) -> None:
    """payload 含 .nan/.inf -> blocked 报告 + 非空 reasons + 零写入，不得泄漏 ValueError/TypeError。

    T9 behavior（主 Agent 选定，内容哈希门 NaN/Inf 边界切片，先写
    失败测试）：legacy prompt.yaml 的 provenance payload 含 YAML 特殊
    浮点字面量 ``.nan`` / ``.inf`` 时，PyYAML 将其解析为 float nan /
    inf（非字符串、非 None），权威 recipe 的 canonical 化
    ``json.dumps(..., allow_nan=False)`` 对该 payload 必然抛
    ``ValueError: Out of range float values are not JSON compliant``
    —— 即权威 recipe 对该 payload 根本无法产出任何合法哈希。
    precheck_prompt_migration 必须把这一失败 fail-closed 成报告：
    ``status == "blocked"`` + 非空 reasons（与 T1 绑定的返回通道），
    不得让 ValueError/TypeError 穿透预检入口；同时零写入、legacy 源
    逐字节保持注入后状态。合法 Prompt 的 ready 行为不被本切片改变
    （既有正向用例钉定：T1 ready 正向切面与 T8 匹配保持 ready 用例，
    本切片不新增也不修改 ready 判定）。

    注入点（最 plausible 的混入形态）：真实 v4.1 label_pools 以不加
    引号的 ``null`` 作空值标记（fixture 已镜像），把已确认源
    prompt.yaml 中首个 ``null`` 标记（fracture_mechanism 池末位）改写
    成 ``.nan`` / ``.inf``。manifest 保持原样 —— 声明值仍是原合法内容
    的哈希，即“内容被写坏后声明值未更新”的真实漂移形态（与 T8
    prompt_yaml_content_modified 同构）。因此 blocked 可由 canonical
    化失败或复算值不匹配任一 fail-closed 路径给出；本用例钉住的新
    行为是：该失败必须经报告通道给出，而不是以异常穿透替代。

    捕获的合理但错误实现：
    - 当前 production（RED 起点）：_check_legacy_provenance 对
      json.dumps(..., allow_nan=False) 的 ValueError 无捕获，异常
      穿透 precheck_prompt_migration -> 显式 no-leak 守卫判失败
      （本用例预期 RED 的 failure signature）；
    - canonical 化失败被当“复算通过”静默放行（吞异常后跳过内容
      哈希门）-> 误 ready -> status 断言失败；
    - 把 NaN/Inf 规范化成 None 后再复算：规范化后 payload 与原合法
      内容逐字段相等，复算值 == manifest 声明值（fixture 特意保持
      原内容声明值）-> 误 ready -> status 断言失败（payload 确实
      含 .nan/.inf，行为上必须 blocked）；
    - blocked 不带 reasons -> reasons 断言失败；
    - 拒绝时“顺手修复”（改写 prompt.yaml / manifest、清理重建源条
      目、写缓存或报告文件、创建 records/ 或 staging）-> 零写入与
      全树快照断言失败；
    - 以 ValueError/TypeError 之外的未类型化异常替代报告 -> 异常
      直接传播判失败（守卫显式点名行为禁止的两类异常，其余按原始
      traceback 失败 —— 报告通道违约不因异常类型不同而豁免）。

    边界备注（本用例不钉定的形态）：放宽 canonical 化
    （allow_nan=True 让 ValueError 消失）在“manifest 声明值保持原
    内容哈希”的本 fixture 下，会因复算值（含 NaN/Infinity token 的
    伪 canonical JSON）与声明值不匹配而同样 blocked，与本用例结论
    一致，不构成额外判据；“声明值恰好对上宽松口径”的放行形态不在
    本切片（legacy 工具链的权威 recipe 对 NaN payload 无法产出任何
    声明值，该组合只能出自伪造 manifest，留待后续切片按需钉定）。

    RED Gate：本用例编写时 precheck 的内容哈希门对非 JSON 兼容
    payload 泄漏 ValueError（json.dumps allow_nan=False 未捕获），
    两个参数均预期在 no-leak 守卫处失败 —— 有效 RED；canonical 化
    失败转报告通道的实现落地后，本用例转为 NaN/Inf 边界回归钉。
    """
    source_entry = _write_legacy_prompt_registry(tmp_path)
    prompt_file = source_entry / "prompt.yaml"
    original_bytes = prompt_file.read_bytes()
    tampered = original_bytes.replace(
        "    - null\n".encode("utf-8"),
        f"    - {nan_inf_literal}\n".encode("utf-8"),
        1,
    )
    assert tampered != original_bytes, (
        "fixture 前置事实失败：label_pools null 标记注入必须真实改写 "
        "prompt.yaml"
    )
    prompt_file.write_bytes(tampered)

    # 前置事实 1：PyYAML 把 .nan/.inf 解析为 float nan/inf（非字符串、
    # 非 None），注入真实落在 provenance payload 内（fracture_mechanism
    # 池末位标记）。
    parsed = yaml.safe_load(prompt_file.read_bytes())
    injected = parsed["label_pools"]["fracture_mechanism"][-1]
    assert isinstance(injected, float) and (
        math.isnan(injected) or math.isinf(injected)
    ), (
        f"fixture 前置事实失败：{nan_inf_literal!r} 必须被 PyYAML 解析为 "
        f"float nan/inf：实际 {injected!r}"
    )
    # 前置事实 2：六字段 payload 在注入后仍可解析、字段齐全，但按权威
    # recipe canonical 化必然抛 ValueError（allow_nan=False）—— 正是当
    # 前 production 泄漏的异常源头；权威 recipe 对该 payload 无法产出
    # 任何合法哈希。
    with pytest.raises(ValueError):
        _prompt_content_sha256_of_yaml(prompt_file.read_bytes())
    # 前置事实 3：manifest 保持原合法内容的声明值（内容写坏后声明值
    # 未更新），与原内容复算值自洽。
    manifest = json.loads(
        (source_entry / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["prompt_content_sha256"] == _prompt_content_sha256_of_yaml(
        original_bytes
    ), "fixture 前置事实失败：manifest 声明值必须保持原合法内容的哈希"

    assert not (tmp_path / "records").exists()
    before = _snapshot_tree(tmp_path)

    precheck = _resolve_precheck_entry()
    assert precheck is not None, (
        "只读 Prompt 迁移预检行为缺失：versioning.migration 未提供 "
        "precheck_prompt_migration 入口（当前 behavior 未实现）"
    )
    mapping_item = _confirmed_prompt_mapping_item()

    try:
        report = precheck(tmp_path, mapping_item)
    except (ValueError, TypeError) as exc:
        pytest.fail(
            f"provenance payload 含 {nan_inf_literal!r} 时，只读预检不得抛 "
            f"{type(exc).__name__}: {exc} —— canonical 化失败必须 "
            f"fail-closed 经报告通道返回 blocked + 非空 reasons"
            "（T1 已绑定返回契约）"
        )

    assert report.status == "blocked", (
        f"provenance payload 含 {nan_inf_literal!r} 时预检必须 fail-closed "
        f"返回 blocked：实际 status={report.status!r}"
    )
    assert report.reasons, _BLOCKED_REASONS_REQUIRED_MSG

    # 零写入：目标根不创建；legacy 源（含被注入 .nan/.inf 的 prompt.yaml
    # 与未更新的 manifest）逐字节保持注入后状态 —— 预检不得“顺手修复”
    # 坏值、改写声明值或产生任何 staging/缓存/报告文件。
    assert not (tmp_path / "records").exists()
    assert _snapshot_tree(tmp_path) == before


# ---------------------------------------------------------------------------
# T10：中断安全 —— 目标创建过程被中断不得留下半写入正式对象；恢复
# 正常后重跑同一转换成功且与无中断基线逐字节一致（M1a 小行为切片，
# 先写测试）
# ---------------------------------------------------------------------------


class _SimulatedMidWriteInterruption(OSError):
    """模拟目标正式对象写入中途被中断（进程崩溃 / IO 错误的代表性形态）。"""


def _install_mid_write_interruption(
    monkeypatch: pytest.MonkeyPatch, struck_writes: list[Path]
) -> None:
    """安装期间中断所有 ``Path.write_text``：先落盘非空严格前缀，再抛 OSError。

    中断形态取“写入已真实开始但未完成”的最小代表：把 data 的非空严格
    前缀写入目标文件并 flush 落盘，然后抛 ``_SimulatedMidWriteInterruption``
    —— 模拟进程写盘中途崩溃 / 磁盘 IO 错误。写入开始前即失败的注入
    不产生任何残骸，无法区分原子与非原子实现，故不采用。每次被中断
    的写入路径记入 struck_writes，供调用方断言“中断确实命中了目标创建
    过程中的真实写入”（注入失效时显式失败，而非空洞通过）。

    注入点契约：拦截当前 production ``versioning.prompts.create_prompt``
    写正式对象的实际调用点 ``Path.write_text``。若实现更换写机制
    （如临时文件 + rename），本注入可能不再命中 —— struck_writes 为
    空时由调用方的前置断言先失败，提示注入点随实际写路径维护；行为
    契约（无半写正式对象 + 重跑成功 + 与基线一致）不随写机制改变。
    """

    def interrupting_write_text(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        cut = max(1, len(data) // 2)
        with open(
            self,
            "w",
            encoding=encoding or "utf-8",
            errors=errors,
            newline=newline,
        ) as handle:
            handle.write(data[:cut])
            handle.flush()
        struck_writes.append(self)
        raise _SimulatedMidWriteInterruption(
            f"simulated interruption mid-write of formal object: {self}"
        )

    monkeypatch.setattr(Path, "write_text", interrupting_write_text)


def _records_subtree(snapshot: dict[str, bytes]) -> dict[str, bytes]:
    """从整树快照取 records/ 子树（含 ``records`` 目录条目自身）。"""
    return {
        rel: content
        for rel, content in snapshot.items()
        if rel == "records" or rel.startswith("records/")
    }


def _non_records(snapshot: dict[str, bytes]) -> dict[str, bytes]:
    """从整树快照取 records/ 之外的条目（legacy 源树 + 旧 active pointers）。"""
    return {
        rel: content
        for rel, content in snapshot.items()
        if not (rel == "records" or rel.startswith("records/"))
    }


def _assert_non_records_unchanged(
    before: dict[str, bytes], after: dict[str, bytes]
) -> None:
    """断言 records/ 之外零新增/删除/修改（legacy 源与旧指针逐字节不动）。"""
    before_kept = _non_records(before)
    after_kept = _non_records(after)
    changed = sorted(
        {rel for rel in before_kept if after_kept.get(rel) != before_kept[rel]}
        | {rel for rel in after_kept if rel not in before_kept}
    )
    assert not changed, (
        "真实转换（含中断失败路径）不得修改、删除或新增 records/ 之外的"
        f"任何条目（legacy 源与旧 active pointers 逐字节不变）：变化 {changed}"
    )


def test_migrate_prompt_interrupted_target_write_leaves_no_partial_object_and_rerun_matches_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中断目标写 -> 无半写正式对象、legacy/指针不动；恢复后重跑成功且与基线一致。

    T10 behavior（M1a 中断安全小行为切片，主 Agent 选定，先写测试）——
    已确认映射 ``v4.1-concise-evidence-json-v2`` -> ``prompt-v4.1-r1``
    的真实转换在目标创建过程中被中断（写入已真实开始、未完成）时：
    1. 不得在目标路径留下半写入正式对象：目标文件必须不存在（半写 /
       空写残骸同样是“半写入正式对象” —— 正式对象只在完整写入后才
       “存在”；残骸既破坏“目标无冲突”预检口径，又让同一转换的重跑
       被 create_prompt 同名冲突语义拒绝）；
    2. legacy 源与旧 active pointers 逐字节不动（records/ 之外零变化；
       旧指针仍声明 legacy 身份）；
    3. 恢复正常写入后，在不改映射与源内容的前提下重跑同一转换，必须
       成功创建完整 ``prompt-v4.1-r1``（load_prompt 全契约读回），且
       结果与无中断基线逐字节一致（records/ 整棵子树比对）。

    注入方式：monkeypatch ``Path.write_text``（当前 production
    create_prompt 的目标写调用点）写入非空严格前缀字节后抛 OSError
    —— 模拟写盘中途崩溃 / 磁盘 IO 错误；前置断言 struck_writes 非空，
    钉死中断确实命中目标创建过程中的真实写入（注入失效 -> 显式失败，
    而非空洞通过）。

    基线对照：并行双根 fixture（baseline / interrupted，字节级同构，
    fixture 前置断言钉死）；baseline 根不受注入干净转换一次，
    interrupted 根走 中断 -> 断言 -> 恢复 -> 重跑；重跑结果与 baseline
    的 records/ 子树逐字节比对。

    捕获的合理但错误实现：
    - 直接写目标且失败留残（当前 production —— RED 起点：
      create_prompt 直接 ``target.write_text``，无失败清理/原子写入，
      中断后目标路径留下半写文件）-> 断言 1 失败（有效 RED 的
      failure signature）；残骸同时让重跑被 PromptConflict 拒绝 ——
      即使跳过断言 1，重跑成功断言也会失败；
    - 重跑覆盖残骸（重跑发现半写文件后静默覆盖重建）-> 断言 1 已先
      失败：半写正式对象在中断后即已存在；且“覆盖”破坏 T6 绑定的
      同身份不覆盖语义（重跑对既有正式对象必须 PromptConflict 拒绝）；
    - 失败时“顺手”修改 legacy 状态（改写源 prompt.yaml / manifest、
      切换旧 active pointers 指向新身份、动数据指针）-> 断言 2 失败
      （records/ 外全树逐字节对比 + 指针身份显式断言）；
    - 吞掉中断异常伪造成功返回（清理后正常返回“已创建”）->
      pytest.raises(Exception) 守卫失败：中断必须以失败显式暴露，
      不得伪造创建成功；
    - 中断失败误报为目标冲突（抛 PromptConflict）-> 通道守卫失败：
      中断前不存在任何身份占用，PromptConflict 语义是“不覆盖、不
      重试”，与本行为“重跑应成功”直接矛盾；
    - 重跑绕过校验伪造目标（不经 parse_prompt_definition / 与基线
      不同字节）-> load_prompt 全契约读回失败，或与基线 records/
      子树逐字节比对失败；
    - 映射项被就地修改（重跑消费被第一次尝试改写的映射）-> 重跑前
      的 mapping_item 不变断言失败。

    TDD 口径 / Unexpected PASS 判据：本用例编写时 create_prompt 为直接
    写入、无失败清理，中断必留半写残骸 -> 预期有效 RED（failure
    signature 见断言 1 消息）；若 production 已具备原子写入 / 失败清理
    语义，本用例转为 Unexpected PASS（中断安全回归钉），不得为此制造
    无意义 production 修改。恢复/续传语义（识别“同一转换”的已提交事实、
    凭证绑定映射与源内容）不在本切片 —— 重跑是对 migrate_prompt 的
    全新调用；data 复制中断、history-summary、CLI 亦不在本切片。
    """
    baseline_root = tmp_path / "baseline"
    interrupted_root = tmp_path / "interrupted"

    mapping_item = _confirmed_prompt_mapping_item()
    confirmed_bytes = _write_full_legacy_prompt_layout(baseline_root)
    assert _write_full_legacy_prompt_layout(interrupted_root) == confirmed_bytes
    # fixture 前置事实：双根字节级同构；两根目标目录均不存在；映射
    # target_path 与权威 prompt_path 一致。
    assert _snapshot_tree(baseline_root) == _snapshot_tree(interrupted_root)
    assert not (baseline_root / "records").exists()
    assert not (interrupted_root / "records").exists()
    assert prompt_path(baseline_root, CONFIRMED_PROMPT_TARGET_ID) == (
        baseline_root / str(mapping_item["target_path"])
    )
    assert prompt_path(interrupted_root, CONFIRMED_PROMPT_TARGET_ID) == (
        interrupted_root / str(mapping_item["target_path"])
    )

    migrate_prompt = _resolve_prompt_migration_entry()
    assert migrate_prompt is not None, (
        "真实 Prompt 迁移转换行为缺失：versioning.migration 未提供 "
        "migrate_prompt 入口（当前 behavior 未实现）"
    )

    before_interrupted = _snapshot_tree(interrupted_root)

    # ---- 无中断基线：baseline 根不受注入，干净转换一次 ----
    created = migrate_prompt(baseline_root, mapping_item)
    assert created == CONFIRMED_PROMPT_TARGET_ID, (
        f"基线转换应返回完整 prompt ID {CONFIRMED_PROMPT_TARGET_ID!r}："
        f"实际 {created!r}"
    )
    baseline_converted = load_prompt(baseline_root, CONFIRMED_PROMPT_TARGET_ID)
    assert baseline_converted.version == CONFIRMED_PROMPT_TARGET_ID
    legacy_raw = yaml.safe_load(confirmed_bytes)
    assert baseline_converted.system_prompt == legacy_raw["system_prompt"]
    assert baseline_converted.user_prompt == legacy_raw["user_prompt"]
    assert baseline_converted.output_fields == tuple(legacy_raw["output_fields"])
    baseline_records = _records_subtree(_snapshot_tree(baseline_root))
    assert set(baseline_records) == {
        "records",
        "records/prompts",
        str(mapping_item["target_path"]),
    }, f"基线转换应恰新增目标文件及其目录：实际 {sorted(baseline_records)}"

    # ---- 中断注入 + 中断尝试 ----
    struck_writes: list[Path] = []
    _install_mid_write_interruption(monkeypatch, struck_writes)

    with pytest.raises(Exception) as excinfo:
        migrate_prompt(interrupted_root, mapping_item)

    # 中断必须显式以失败暴露，不得吞掉异常伪造“已创建”成功返回
    # （fail-closed）。中断的具体异常通道不在本切片绑定 —— 它是操作
    # 失败而非预检拒绝；此处只钉“必须失败”。
    assert not isinstance(excinfo.value, PromptConflict), (
        "目标创建中途被中断不是身份占用拒绝（中断前 records/ 无任何"
        "同身份条目、target_path 空闲）：不得以 PromptConflict 误报"
        " —— 该通道语义是“不覆盖、不重试”，与本行为“恢复后重跑应"
        "成功”直接矛盾"
    )
    # 前置事实：中断确实命中目标创建过程中的至少一次真实写入 ——
    # 注入失效（如实现更换写机制）时显式失败，而非空洞通过。
    assert struck_writes, (
        "中断注入未命中任何写入：注入点与目标创建的实际写路径不符，"
        "本用例前提失效（注入点需随写机制更新，行为契约不变）"
    )

    # 1）无半写入正式对象：目标路径必须不存在任何文件 —— 半写/空写
    #    残骸同样是“半写入正式对象”（正式对象只在完整写入后才存在）；
    #    残骸还会让重跑被 create_prompt 同名冲突语义拒绝。
    target_file = prompt_path(interrupted_root, CONFIRMED_PROMPT_TARGET_ID)
    assert not target_file.exists(), (
        f"被中断的真实转换不得在目标路径留下半写入正式对象：实际存在 "
        f"{target_file}（{target_file.stat().st_size} 字节，前 120 字节 "
        f"{target_file.read_bytes()[:120]!r}）—— 半写残骸破坏“目标无冲突”"
        "预检口径，并让同一转换的重跑以 PromptConflict 拒绝"
    )

    # 2）legacy 源与旧 active pointers 逐字节不动（records/ 之外零变化；
    #    records/ 内允许仅目录级残留 —— 目录不是正式对象且不阻塞重跑）。
    after_interrupted = _snapshot_tree(interrupted_root)
    _assert_non_records_unchanged(before_interrupted, after_interrupted)
    active_pointer = (
        interrupted_root / "pipeline" / "prompt_control" / "active_prompt.yaml"
    )
    assert (
        yaml.safe_load(active_pointer.read_bytes())["revision_id"]
        == CONFIRMED_PROMPT_SOURCE_ID
    )
    data_pointer = interrupted_root / "finetune" / "active_data_release.json"
    assert (
        json.loads(data_pointer.read_text(encoding="utf-8"))["release_id"]
        == "v4.1.0-ecb5aeb9657c"
    )

    # ---- 恢复正常写入，重跑同一转换 ----
    monkeypatch.undo()
    # 不改映射（同一映射对象未被中断的尝试修改）与源内容（上一步已钉
    # legacy 逐字节不变）。
    assert mapping_item == _confirmed_prompt_mapping_item()

    created = migrate_prompt(interrupted_root, mapping_item)
    assert created == CONFIRMED_PROMPT_TARGET_ID, (
        f"恢复正常后重跑同一转换应成功创建完整 prompt ID "
        f"{CONFIRMED_PROMPT_TARGET_ID!r}（无残骸阻塞）：实际 {created!r}"
    )

    # 重跑结果经既有 Prompt 全契约可读回，三字段与 legacy 源结构化相等。
    rerun_converted = load_prompt(interrupted_root, CONFIRMED_PROMPT_TARGET_ID)
    assert rerun_converted.version == CONFIRMED_PROMPT_TARGET_ID
    assert rerun_converted.system_prompt == legacy_raw["system_prompt"]
    assert rerun_converted.user_prompt == legacy_raw["user_prompt"]
    assert rerun_converted.output_fields == tuple(legacy_raw["output_fields"])

    # 3）重跑结果与无中断基线逐字节一致：records/ 整棵子树相等
    #    （目标文件字节相同，且无任何额外残留条目）。
    rerun_records = _records_subtree(_snapshot_tree(interrupted_root))
    only_baseline = sorted(set(baseline_records) - set(rerun_records))
    only_rerun = sorted(set(rerun_records) - set(baseline_records))
    differing = sorted(
        rel
        for rel in set(baseline_records) & set(rerun_records)
        if baseline_records[rel] != rerun_records[rel]
    )
    assert not (only_baseline or only_rerun or differing), (
        "重跑创建的正式对象必须与无中断基线逐字节一致（records/ 整棵"
        f"子树）：仅基线有 {only_baseline}，仅重跑有 {only_rerun}，"
        f"字节不同 {differing}"
    )

    # 重跑后 legacy 源与旧 active pointers 仍逐字节不动。
    after_rerun = _snapshot_tree(interrupted_root)
    _assert_non_records_unchanged(before_interrupted, after_rerun)
