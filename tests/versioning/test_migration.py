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

T11 behavior（本切片，主 Agent 选定，数据迁移批级只读预检 ready，
先写测试）—— 对 M0 已确认的两条 data 映射
（object-mapping.yaml data_mapping.items，用户 2026-09-07 确认；
D1：r1 superseded、replacement=data-v4.1-r2；r2 active）执行批级只读
预检：
- ``v4.1.0-760050fad303`` -> ``data-v4.1-r1``（target_status
  ``superseded``，replacement ``data-v4.1-r2``）；
- ``v4.1.0-ecb5aeb9657c`` -> ``data-v4.1-r2``（target_status ``active``）；
预检必须返回整批 ``ready`` 并包含逐对象报告（每条按 source_legacy_id
归因、target_identity / target_path 与映射一致、对象级 status ==
"ready"；未映射 sibling release 不得进入对象报告 —— 实现必须按映射项
定位源，不得扫描全 releases 目录）；全程零写入：不创建 ``<root>/data``、
working、release_staging、records 或任何目标条目；legacy 源树
（workspace/data/releases/）与旧 active pointers
（finetune/active_data_release.json、pipeline/prompt_control/
active_prompt.yaml）逐字节不变；ready 不得依赖 payload 已验证 ——
映射项的 source_verified / source_payload_complete 保持 M0 事实分级
（verified_local / training_observed），预检不得据此阻塞（本切片不做
payload 内容 provenance 门），也不得就地改写映射项把来源状态伪造成
payload 已验证。本切片不做真实转换、provenance 门、凭证（D2 凭证
格式/位置未裁决，预检报告不绑定任何凭证字段）或中断恢复；blocked
反向（任一对象不合格 -> 整批 blocked，D2 已确认语义）留待配套反向
切片（data 目标冲突 blocked 边界由 T12 覆盖，其余反向场景仍留待后续
切片）。

T12 behavior（本切片，reviewer 对 T11 的 P2，data 预检目标冲突边界，
先写测试）—— precheck_data_migration 的目标冲突检测必须在 data
正式对象根（映射 target_path ``data/releases/data-v4.1-rN/release.yaml``
的对象目录层 ``data/releases/``）上按精确身份进行，不得只复用 Prompt
的 ``_check_target_conflict``（只扫 records/；data 正式对象不在 records/
下，data 根下同身份目录/文件对当前实现不可见 -> 误判 ready）。复用 T11
双对象 data fixture（两条已确认映射 + 三份 legacy release + 旧数据/
Prompt 活动指针），两条映射声明的 target_path 文件均保持空闲（隔离
target_path 占用分支，结论只能由 data 根同身份扫描决定）：
1. 已存在 ``data/releases/data-v4.1-r1/`` 同身份目录（即使缺少
   release.yaml）-> 整批 blocked；
2. 已存在同身份非标准文件形式（如 ``data/releases/data-v4.1-r1.yaml``）
   -> 整批 blocked（同身份不允许以任何文件形式占用，防改名冲突）；
3. ``data/releases/data-v4.1-r10/`` 等更高 revision 邻居是不同身份
   （versioning/ids.py 权威解析口径，字符串前缀不等于同身份），不得
   误阻塞 ``data-v4.1-r1`` -> 整批 ready（修复不得反向过宽，与 T3/T4
   同口径）；
4. 任一对象冲突即整批 blocked（D2）：冲突经逐对象报告归因（blocked
   对象 status == "blocked" + 非空 reasons，非冲突对象保持 ready），
   冲突对象在第一位与第二位映射条目各出现至少一次（钉死只检查首条/
   末条映射的实现）；
5. 全程零写入：不覆盖/改名/清理既有条目，不创建目标、生命周期、
   records 条目，legacy 源树与旧 active pointers 逐字节不变，不就地
   修改传入映射项；fixture 只在 pytest tmp_path 下按映射指定的
   ``data/releases/...`` 目标布局模拟 data 正式对象根，不把 data 根
   写成训练机真实路径。本切片不做真实转换、provenance 门、凭证或
   恢复。

T13 behavior（本切片，主 Agent 选定，data 批级只读预检已钉扎 legacy
manifest provenance 门，先写测试）—— precheck_data_migration 必须对
旧数据活动指针钉扎的 legacy release 做 manifest 字节级 provenance 校验
（M0 source-inventory 证据：活动 release ``v4.1.0-ecb5aeb9657c`` 被
``finetune/active_data_release.json`` 钉扎，pin_facts 含
expected_manifest_sha256；非活动 release ``v4.1.0-760050fad303``
pinned_by: ~，无钉扎）：
1. 对 r2 映射项（``v4.1.0-ecb5aeb9657c`` -> ``data-v4.1-r2``，
   target_status ``active``）读取 ``finetune/active_data_release.json``；
2. 指针 ``release_id`` 必须精确等于该映射项的 ``source_legacy_id``
   （指向未映射 sibling 或错误源均 = 不符）；
3. 按 manifest 文件字节独立复算
   ``workspace/data/releases/<source_legacy_id>/manifest/
   release_manifest.json`` 的 SHA-256（测试与实现均不 import legacy
   ``pipeline`` / ``finetune`` 代码，哈希口径独立镜像自算）；
4. 与指针 ``expected_manifest_sha256`` 比对；
5. 匹配 -> 保持整批 ready；指针文件缺失、非 JSON、必需字段
   （``release_id`` / ``expected_manifest_sha256``）缺失、release_id
   不符或哈希不匹配 -> 整批 blocked（fail-closed）+ 非空 reasons +
   零写入，门失败按对象归因到被钉扎的 r2 映射项；
6. r1 映射项（``v4.1.0-760050fad303`` -> ``data-v4.1-r1``，M0
   pinned_by: ~，无钉扎）不受该门约束：不得因无钉扎而阻塞，也不得
   为其伪造 verified/passed（映射项 source_verified /
   source_payload_complete 保持 M0 事实分级）；
7. 预检不得修复/改写指针或 legacy manifest；本切片不做 manifest
   files 声明的 payload 文件哈希复算门、真实转换、凭证或恢复。

T14 behavior（本切片，主 Agent 选定，data 批级只读预检 legacy
manifest payload 文件哈希 provenance 门，先写测试）—— 批级只读预检
必须复算 legacy manifest 声明的 payload 文件哈希（对每个映射项，
不只对已钉扎活动 release —— T13 是指针钉扎的 manifest 文件字节门，
本切片是 manifest 自洽性/内容完整性门）：
1. 对每个映射项读取
   ``workspace/data/releases/<source_legacy_id>/manifest/
   release_manifest.json``；
2. 对 manifest ``files[]`` 中声明的每个 payload 文件，按文件字节
   独立复算 SHA-256（测试与实现均不 import legacy ``pipeline`` /
   ``finetune`` 代码，独立镜像自算）；
3. 与声明的 ``sha256`` 值比对；
4. 任一文件缺失、哈希字段缺失、哈希不匹配或路径异常（如指向
   release 目录之外的穿越路径）时，该对象 blocked，且整批 blocked
   （fail-closed）+ 非空 reasons + 按对象归因；
5. 匹配时保持 ready（门不得反向过宽）；
6. 该门是 manifest 自洽性/内容完整性机制，不等于训练机真实
   payload 已验证：不把 r1 的无钉扎状态伪造成 verified，映射项
   source_verified / source_payload_complete 保持 M0 事实分级；
7. 零写入：legacy 源树与旧 active pointers 逐字节不变；
8. 本切片不做真实转换、凭证、恢复。

T14-P3 补丁切片（reviewer 对 T14 的 P3，先写测试）—— 批级只读预检
解析 manifest ``files[]`` 声明的 payload 路径时遇到 symlink loop（或
其他路径解析异常）必须 fail-closed 经报告通道返回该对象 blocked +
整批 blocked + 非空 reasons，不得让 ``RuntimeError`` / ``OSError``
穿透 precheck_data_migration 入口（当前 production 的
``payload_file.resolve()`` 只被 ``except OSError`` 包裹，而本机
Python 3.11.14 的 resolve() 把 ELOOP 转成 ``RuntimeError: Symlink
loop from ...`` -> 穿透）；零写入，legacy 源（含 loop fixture）与旧
active pointers 逐字节不变；正常 payload 哈希匹配的对象仍 ready（门
不得反向过宽）。

T15-P2-1 补丁切片（reviewer 对 T15 的 P2-1，先写测试，不改
production）—— ``migrate_data`` 创建 ``state: sealed`` 的正式 data
release 后，目标必须真实满足既有封存语义（versioning/
data_release.py::seal_release 产出的位级事实与既有只读门
``assert_payload_sealed``，不另立新口径）：release 根目录与全部
payload 文件/目录去全部写位（0o222），``assert_payload_sealed`` 通过；
release.yaml 保留创建时写位（sealed 后唯一受控修改通道，封存不得
过度到受控通道）；receipt 与其所在 migration_receipts/ 目录
（及 data/releases/ 对象根层）是 release 外部的迁移控制面，不随
封存去写位；T15 内容/receipt 契约不回归（目标内容恰为 release.yaml
+ manifest 声明 payload 集合且逐字节一致、committed receipt 八字段
完整且哈希可复算）；legacy 源树（含权限位）与旧 active pointers
不变，不触发 DVC。T15 曾把“payload 封存去写位”划在范围边界之外
—— 本切片补上该绑定：声明 ``state: sealed`` 必须与事实一致。

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

    def precheck_data_migration(root: Path, mapping_items: Sequence[Mapping[str, object]]) -> object
        # T11 批级只读预检：mapping_items 为 object-mapping.yaml
        #   data_mapping.items 的解析结果（两条已确认映射；本用例逐字段
        #   镜像 M0 证据，含 status: "user_confirmed"、target_status、
        #   replacement（r1 条目）与 source_verified /
        #   source_payload_complete 事实分级）。逐对象校验映射项确认状态、
        #   候选目标身份合法性（data 完整身份 <kind>-v<协议>-r<N>）、
        #   legacy 源 workspace/data/releases/<source_legacy_id>/ 的
        #   manifest/release_manifest.json 与 payload 存在性、目标无冲突
        #   （T12 起目标冲突判定必须覆盖 data 正式对象根 data/releases/：
        #   映射 target_path 文件、data/releases/<身份>/ 同身份目录 ——
        #   即使缺少 release.yaml —— 与 data/releases/ 下同身份文件形式
        #   （<身份>.yaml 等）任一存在即冲突；data-v4.1-r10 等更高
        #   revision 邻居是不同身份，不构成冲突）、已钉扎 legacy manifest
        #   provenance 门（T13 起：对旧数据活动指针 finetune/
        #   active_data_release.json 钉扎的映射项，指针 release_id 必须
        #   精确等于该映射项 source_legacy_id，按 manifest 文件字节复算
        #   workspace/data/releases/<source_legacy_id>/manifest/
        #   release_manifest.json 的 sha256 必须与指针
        #   expected_manifest_sha256 匹配 —— 指针文件缺失、非 JSON、
        #   release_id / expected_manifest_sha256 字段缺失、release_id
        #   不符或哈希不匹配均整批 blocked，fail-closed，门失败按对象
        #   归因；无钉扎映射项不得因无钉扎阻塞，也不得伪造
        #   verified/passed），返回批级只读报告：
        #   report.status（"ready" / "blocked"，任一对象不合格即整批
        #   blocked，fail-closed）+ report.object_reports（逐对象报告
        #   序列，每条含 source_legacy_id / target_identity /
        #   target_path / status；未映射 release 不得出现）。
        # 预检全程零写入：不创建 <root>/data、working、release_staging、
        #   records 或任何目标条目，不改 legacy 源树与旧 active pointers，
        #   不写任何报告/缓存文件（报告只经返回值给出）；不就地修改传入
        #   映射项（不得把 training_observed 等来源状态伪造成 payload
        #   已验证；T13 门也不得给无钉扎映射项伪造 verified/passed）；
        #   T14 起预检还必须复算 manifest files[] 声明的 payload 文件
        #   哈希：对每个映射项（含无钉扎对象）逐 entry 按文件字节独立
        #   复算 SHA-256 与声明 sha256 比对 —— 文件缺失、哈希字段缺失、
        #   哈希不匹配或路径异常即该对象 blocked 且整批 blocked
        #   （fail-closed，按对象归因），匹配保持 ready；该门是 manifest
        #   自洽性/内容完整性机制，ready 不等于训练机真实 payload 已
        #   验证，不得就此升级映射项来源状态；报告不绑定任何凭证字段
        #   （D2 格式/位置未裁决）；T14-P3 起：payload 路径解析异常
        #   （如 declared 路径 symlink loop）同样 fail-closed 经报告
        #   通道 blocked（该对象 + 整批 + 非空 reasons，按对象归因），
        #   不得让 RuntimeError / OSError 穿透预检入口。

    def migrate_data(root: Path, mapping_items: Sequence[Mapping[str, object]]) -> object
        # T15/T16/T17 批级真实转换（写入阶段按对象独立写入；T15 钉单
        #   对象 r2 active 正向行为、T16 钉单对象 r1 superseded 正向
        #   行为、T17 钉双对象批（r2+r1 一次调用，D2 推荐顺序 r2 先于
        #   r1）终态与 replacement 同批可解析，返回值不绑定）：消费与
        #   precheck_data_migration 相同形状的映射批。对每条已确认映射
        #   在目标 root（可注入，表示目标数据根；真实取值 /data/mVllm_2
        #   —— Q4 用户确认，本测试只传 pytest tmp_path，不创建训练机
        #   真实路径）下创建正式 data release（data/releases/<完整身份>/，
        #   release.yaml + 与 legacy 源逐字节一致的 payload 文件集合），
        #   语义字段取 legacy manifest 声明值（不重算、不伪造），status
        #   按映射 target_status（r2 -> active，replacement 不存在；
        #   T16 起 r1 -> superseded 时 replacement 按映射声明写入
        #   release.yaml，且须在目标 root 下可解析为既有正式对象 ——
        #   训练引用门 validate_training_reference 对 superseded 拒绝、
        #   对 active 放行）；
        #   目标对象完整写入并验证后在目标 root 的
        #   migration_receipts/<target_identity>.receipt.yaml 原子写入
        #   committed receipt（operation_id / source_legacy_id /
        #   target_identity / target_path / source_manifest_sha256 /
        #   target_release_digest / status / written_at；
        #   source_manifest_sha256 为 legacy manifest 文件字节 SHA-256；
        #   target_release_digest 按目标 release 全部文件（相对 POSIX
        #   路径升序）拼接 ``<rel>\n<sha256>\n`` 行后的整体 SHA-256 复算
        #   可核实）。legacy 源与旧 active pointers 逐字节不变；不写
        #   records/、不触发 DVC、不就地修改传入映射项。T15-P2-1
        #   起：目标 release 声明 state: sealed 必须真实满足既有封存
        #   语义（seal_release 位级事实 + assert_payload_sealed 只
        #   读门）—— release 根与全部 payload 文件/目录去全部写位、
        #   release.yaml 保留创建时写位（sealed 后受控更新通道）；
        #   receipt 与 migration_receipts/ 是 release 外部迁移控制文
        #   件/目录，不随封存去写位。T18 起：完成态批级重跑必须幂等
        #   跳过 —— 双对象批完整转换后，同 root、同映射、同 legacy
        #   源的第二次 migrate_data 调用必须成功（不把已完成的
        #   r1/r2 当外来冲突拒绝），两对象识别为已完成并跳过：两个
        #   目标 release 子树与两份 receipt 逐字节不变（含 written_at）、
        #   目标侧零重写、不产生 data-v4.1-r3 等新身份、legacy 源与旧
        #   active pointers 不变；跳过的报告通道与返回值不绑定。批级
        #   恢复（中断后未完成对象继续）、凭证失配拒绝仍不在本切片。
        #   T18-P2 起（reviewer 对 T18 的 P2）：该完成态核实必须绑定
        #   superseded 映射的 replacement —— 映射声明的 replacement 与
        #   已提交事实（第一次转换写入的目标 release / receipt）不符
        #   时不得静默跳过，必须经 DataMigrationBlocked fail-closed 拒绝
        #   且零写入。T19-P4 起（用户裁决）：receipt 生命周期 —— 每个
        #   对象使用同一个 migration_receipts/<target_identity>.receipt.yaml，
        #   开始写目标前先原子写该文件为 status: in_progress、
        #   target_release_digest: null（绑定 operation / source / target /
        #   path / 写入前 re-validation 那份源 manifest 哈希 / 映射
        #   target_status / replacement）；中断后同一文件保留；目标完整
        #   写入并验证后同一文件原子替换为 committed receipt；恢复成功
        #   后同一文件转为 committed；不使用 migration_receipts.in.progress/
        #   等独立 credential 目录，不新增额外 credential 文件。
        #   T19-P4-P2 起（reviewer 对 T19-P4 的 P2）：该 in_progress 写
        #   入必须发生在对象的全部写入前数据校验（superseded replacement
        #   在目标 root 可解析为既有正式 release、release 语义字段合法
        #   如 counts.splits 派生）全部通过之后、任何目标子树写入之前
        #   —— 校验失败的 fail-closed 拒绝不得留下 in-progress receipt
        #   或目标目录（该对象零写入），修正输入后的重跑不得被失败路径
        #   遗留的 stale credential 失配拒绝堵死。

    def build_history_summary(root: Path, entries: Sequence[Mapping[str, object]]) -> object
        # H1 history-summary 纯构建（M1b 第一个切片，先写测试，不改
        #   production）：对已确认历史 Prompt entry（kind "prompt_history"、
        #   source_legacy_id "v4.1-concise-evidence-json-v1"、status
        #   "user_confirmed"，M0 registry_versions_not_migrating 用户确认
        #   仅进 history-summary，不迁移为正式 Prompt 身份）执行只读构
        #   建，返回 history-summary 文档（mapping）：history_summary_schema
        #   == "tensile-migration/history-summary/v1"；entries 为 list 且
        #   恰含声明的条目（不扫描 legacy 目录生成未声明条目）；每条
        #   entry 携带 entry_id（文档内 slug，非 <kind>-v<协议>-r<N> 正
        #   式身份）、kind、original_id（保留原始 legacy ID）、
        #   history_only: true、formal_identity: "none"（不分配任何新正
        #   式身份，文档内任何字符串值都不是正式身份）与 facts；facts
        #   内已知值为 {value, source} 形态（source 为非空 mapping 的字
        #   段级来源 provenance，须可指回该 entry 的 legacy 源文件：
        #   manifest-only 事实指 manifest.json、prompt.yaml-only 事实指
        #   prompt.yaml），事实值取 legacy manifest/prompt 源声明值
        #   （protocol_id / prompt_content_sha256 / publishing_code_commit /
        #   system_prompt / user_prompt / output_fields），不重算、不伪
        #   造、不取 sibling。全程纯构建零写入：不写 history-summary 文
        #   件、不创建 records/ 或任何目标条目、不改 legacy 源、不就地修
        #   改传入 entries。H2/H3 起（M1b 非法输入 fail-closed 反向最小
        #   切片）入口对非法输入必须 fail-closed 拒绝，不得静默构建文档
        #   （含 entries 为空的文档）：
        #   - entry ``status`` 白名单式只认 ``user_confirmed``（M0
        #     status_field_legend 唯一“用户已逐项确认”口径；
        #     pending_user_check / unknown / not_verified /
        #     verified_local（source_verified 事实分级，非确认门槛）/
        #     status 字段缺失一律拒绝）；
        #   - entry 不得夹带候选正式身份 ``candidate_target_identity``
        #     （如 prompt-v4.1-r1 / model-v4.1-r1：历史 entry history_only，
        #     仅进 history-summary，不迁移、不分配任何新正式身份）；
        #   - entry 不得声明 ``passed: true``（M0：不得把历史 summary
        #     转成 passed；pending 目标在用户确认前禁止写入或标记
        #     verified/passed）；
        #   - ``entries=None`` 与非可迭代输入必须拒绝，不得静默返回空
        #     文档；可迭代但元素非 mapping（如字符串）同样拒绝；
        #   - 全部拒绝经明确域错误（PromptMigrationBlocked 等 versioning
        #     域错误类型）或 blocked 报告通道给出，携带非空拒因，不得抛
        #     未类型化异常；拒绝零写入（legacy 源与全树逐字节不变）、
        #     不就地修改传入 entries；合法已确认 entry 对照仍正常构建。
        #   H4（M1b 源可读性与身份绑定门切片）起，声明源的可读性缺
        #   口与身份矛盾按缺口类别分流（unknown 与 blocked 必须可区分）：
        #   - 声明源缺失（源条目目录缺失/为空，或 manifest.json /
        #     prompt.yaml 单文件缺失）时，相关字段进入字段级 unknown
        #     （每条 unknown 事实携带非空 unknown_reason 与指向声明源
        #     路径的 attempted_source，不得伪装成已知值），entry 不得
        #     静默消失，不得整批因缺失 blocked；单文件缺失时未受影响
        #     的另一来源文件事实保持已知（H1 {value, source} 形态）；
        #   - 源文件存在但坏 JSON/YAML（含顶层非 mapping）时，必须整
        #     批 fail-closed（不得降级为 unknown 静默构建文档）；
        #   - 源文件可解析但身份字段（manifest.json / prompt.yaml 的
        #     revision_id）与 entry source_legacy_id 矛盾时，必须整批
        #     fail-closed（不得在错误身份下提取事实构建文档）；
        #   - 上述任一失败路径零写入、legacy 源不变、不就地修改传入
        #     entries，合法已确认 entry 对照仍正常构建（H1/H2 正向不回
        #     归）；
        #   H5（M1b prepare-only run 历史条目切片）起，kind
        #   ``prepare_only_run`` 的已确认 run entry（M0
        #   training_machine_run_evidence.prepare_only_runs：仅准备资
        #   料、未发现权重）不得成为训练事实：entry 输出
        #   ``training_status: "prepared_only"``；不声明任何权重存在
        #   （weights/adapter/merged/checkpoint/safetensors 命名族键只
        #   允许字段级 unknown 或显式非存在）；核心训练参数（seed /
        #   learning_rate / epochs / effective_batch_size / optimizer /
        #   precision / lora_rank / lora_alpha / lora_target_modules）
        #   全部字段级 unknown（准备资料中的 planned 参数不是训练执行
        #   事实）；不得出现在"有权重 run"分组；不产生任何 model 概念条
        #   目（不为 run 分配任何新正式身份）；保留原始 run ID 与来源；
        #   不伪造训练完成、权重、评测或通过状态；纯构建零写入、不扫
        #   描 sibling、合法 prompt_history entry 不回归。
        #   H6a（M1b weight run 历史条目第一切片）起，kind ``weight_run``
        #   的已确认 run entry（M0
        #   training_machine_run_evidence.weight_runs 首条
        #   ``v4.1-phase2-source-aware-v1-seed3407``：训练机只读观察
        #   "fold0 有 adapter 与 10 个 merged 分片，有 evidence_archive"）
        #   不得走 prompt registry 源路径，也不得 fail-closed 拒绝使
        #   entry 消失（M0 把有权重 run 列为仅进 history-summary 的允许
        #   历史记录）：entry 输出 evidence-derived ``training_status:
        #   "weights_observed"``（M0 明确"run 目录存在不等于完成训练"、
        #   object-mapping"不能当作 completed 训练" —— 不得输出
        #   completed，也不得输出 not_completed 等同样无证据的负向声
        #   明）；M0 结构观察分解出的已知事实 fold_scope == "fold0" 与
        #   adapter_present / merged_present == True（Spec「模型身份」
        #   最小内容的 fold 或全量范围 + 权重位置及存在性；{value,
        #   source} 形态，来源 provenance 指回声明 run 源）；核心训练参
        #   数（与 H5 同族九字段）保持字段级 unknown（M0 未记录 weight
        #   run 的任何参数值，声明 run 的 evidence_archive 内容未经核实
        #   —— 调查记录"归档尚未证明完整"；unknown 事实携带非空
        #   unknown_reason 与指回声明 run 源的 attempted_source，不携带
        #   非 None value）；不声明训练完成、通过、评测结果、model 正
        #   式身份或权重完整性/哈希验证（M0："全部未验证权重完整性与哈
        #   希"；与 H5 相反，权重存在性命名族键允许携带存在性值 ——
        #   权重存在是 M0 观察事实）；纯构建零写入、不扫描 sibling；
        #   合法 prompt_history 与 prepare_only_run entry 不回归。其余
        #   weight run 结构形态（run 根结构、merged 软链接来源链）、声
        #   明 run 源缺失（known gap）、有证据的核心训练参数提取（已
        #   核实归档 manifest）、多 entry 批量、eval/model 历史条目、
        #   history-summary 文件写入与 CLI 不在本切片（留 H6b 及后续）。
        #   H6b（M1b weight run 历史条目第二切片）起，weight run 的权重
        #   存在性判定口径必须一致（reviewer 对 H6a 的 P3：adapter_present
        #   递归任意文件、merged_present 顶层 safetensors，口径不一致）——
        #   两者都只把目录中的权重命名文件（例如 *.safetensors）计为权重，
        #   非权重文件（adapter_config.json / README.md / model-index.json
        #   等元数据文件）不得使 *_present 为 True；可观察目录中无权重命
        #   名文件时该 *_present 为已知 False（观察到的缺席，不是
        #   unknown）；adapter / merged 任一观察到权重 -> entry 照常构建且
        #   training_status 仍为 weights_observed（H6a 既有"任一证据即支
        #   撑分类"规则保持）。声明 run 源整体缺失（M0 known_gap 真实形态：
        #   预期 run 路径不存在）时，weight_run entry 不得 fail-closed 拒绝
        #   使 entry 消失、整批不得 blocked（Spec："身份、权重或结果证据
        #   不足时，可以保存明确标注缺失的历史记录"、"不能取得的历史值标
        #   为未知并注明来源缺口"；H4 同口径先例）—— fold_scope /
        #   adapter_present / merged_present 与九个核心训练参数全部字段级
        #   unknown（非空 unknown_reason + 指回声明 run 源的
        #   attempted_source，不携带非 None value），不输出 weights_observed
        #   / completed / not_completed / prepared_only 等无证据声明；
        #   fold0 缺失但 run 目录存在的其余结构形态、两个目录均无权重命
        #   名文件（完全无权重证据）的分流、merged 软链接来源链、有证据
        #   的核心训练参数提取、多 entry 批量、eval/model 历史条目、
        #   history-summary 文件写入与 CLI 仍不在本切片（留后续）。

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
缺失时，仍由测试内惰性解析 + 显式 AssertionError 钉出“真实转换行为
缺失”，不让 AttributeError / 原始 import 错误成为 RED。
T11（数据批级预检切片）同口径：migration 模块已存在而
precheck_data_migration 入口缺失时，仍由测试内惰性解析 + 显式
AssertionError 钉出“批级只读预检行为缺失”，不让原始 import 错误或
AttributeError 成为 RED。
T15（单对象 data 真实转换切片）同口径：migration 模块已存在而
migrate_data 批级入口缺失时，仍由测试内惰性解析 + 显式 AssertionError
钉出“单对象 r2 data 真实迁移行为缺失”。
T15-P2-1（封存补丁切片）同口径补充：migrate_data 入口已存在时，
RED 不经入口缺失分支给出 —— 由既有入口调用成功后的显式封存行为
AssertionError 钉出（assert_payload_sealed 的 ImmutableReleaseError
经 cause 链保留，不得直接充当 RED 结论）。
T15-P2-2（写入前 re-validation 补丁切片）同口径补充：migrate_data 入
口与 DataMigrationBlocked 拒绝通道均已存在时，RED 由 fail-closed 通道
与零写入断言钉出“写入前 re-validation 行为缺失”（DID NOT RAISE 或
原始 FileNotFoundError 穿透），不让原始未类型化异常直接充当 RED 结论。
T16（单对象 r1 superseded 转换切片）同口径补充：migrate_data 入口、
DataMigrationBlocked 拒绝通道与 T15 单对象 r2 转换均已存在时，RED 不经
入口缺失分支给出 —— 由 precheck-ready 的 r1 superseded 映射在真实转
换阶段的既有 fail-closed 拒绝钉出：本文件把该拒绝转成显式行为
AssertionError（原始 DataMigrationBlocked 经 cause 链保留，不得直接
充当 RED 结论）。
T18（完成态批级重跑幂等切片）同口径补充：migrate_data 入口、
DataMigrationBlocked 拒绝通道与 T17 双对象批终态均已存在（第一次完
整转换为 fixture 前置事实，失败即 T17 回归而非本切片 RED）时，RED
不经入口缺失分支给出 —— 当前 production 的 precheck 把已完成的
r1/r2 判为目标冲突，第二次调用被 DataMigrationBlocked 拒绝（完成对象
被当外来冲突）；本文件把该拒绝转成显式行为 AssertionError 钉出
"完成态批级重跑幂等跳过行为缺失"（原始 DataMigrationBlocked 经 cause
链保留，不得直接充当 RED 结论）。
T18-P2（reviewer 对 T18 的 P2，replacement 绑定补丁切片）同口径补
充：migrate_data 入口、DataMigrationBlocked 拒绝通道、T17 双对象批终
态与 T18 完成态幂等跳过均已存在（第一次完整转换与同映射重跑成功均
为 fixture 前置事实，失败即 T17/T18 回归而非本切片 RED）时，RED 不
经入口缺失分支给出 —— 当前 production 的完成态核实口径（receipt 逐
字段比对 + operation_id 派生 payload source/target/status +
source_manifest_sha256 + target_release_digest）不含 superseded 映射
的 replacement，r1 映射 replacement 变更后的第二次 migrate_data 调用
静默跳过成功返回；本文件把该静默跳过转成显式行为 AssertionError
钉出"完成态重跑 receipt 核实未绑定 superseded 映射的 replacement"，
拒绝通道错位（原始未类型化异常替代 DataMigrationBlocked）同样经显
式 AssertionError + cause 链转译（不得直接充当 RED 结论）。
T19-P4-P2（reviewer 对 T19-P4 的 P2，写入前数据校验失败零写入补
丁切片）同口径补充：migrate_data 入口、DataMigrationBlocked 拒绝通
道、T17 双对象批终态与 T19-P4 同一文件 in-progress receipt 生命周期
均已存在（变体批/坏 manifest 批 precheck ready、第一次调用
DataMigrationBlocked、r2 批内先完成保留均为 fixture 前置事实，失败即
既有切片回归而非本切片 RED），RED 不经入口缺失或拒绝通道缺失分支
给出 —— 当前 production 把 in-progress receipt 写在 superseded
replacement 可解析性校验与 release 语义字段校验（counts.splits 派生
等）之前，两类失败路径的拒绝发生时 receipt 已落盘（status:
in_progress）：零写入断言（receipt 不得存在）钉出“credential 落盘先
于写入前数据校验”（P2 缺陷形态）；修正输入后重跑不被阻塞的断言在
RED 阶段不执行到（失败先发生于零 receipt 断言），其当前 production
行为（stale credential 与修正后映射/源逐字段核实失配即拒绝重跑）恰
为本切片要钉死的缺陷，GREEN 后转为重跑不被阻塞的回归钉。
H1（M1b history-summary 第一个切片，单条已确认历史 Prompt entry 的
最小正向纯构建）同口径：migration 模块已存在而 build_history_summary
入口缺失时，仍由测试内惰性解析 + 显式 AssertionError 钉出
“history-summary 纯构建行为缺失”，不让原始 import 错误或
AttributeError 成为 RED。
H2/H3（M1b history-summary 非法输入 fail-closed 反向最小切片）同
口径补充：build_history_summary 入口已存在（H1 已 GREEN），RED 不
经入口缺失分支给出 —— 由当前对非法输入（entry status 非
user_confirmed / 夹带 candidate_target_identity 候选正式身份 /
声明 passed: true / entries=None 与非可迭代）静默构建文档（含空
文档）的显式行为 AssertionError 钉出“history-summary 非法输入
fail-closed 行为缺失”；拒绝若以未类型化异常（TypeError 等直接穿
透）给出，同样经显式 AssertionError + cause 链转译，不让原始未类
型化异常直接充当 RED 结论。entries 为可迭代但元素非 mapping
（字符串）的场景当前实现已经明确域错误通道 fail-closed，记录为
Unexpected PASS（回归钉），不当 RED；合法已确认 entry 的正向构
建由既有 H1 selector 复跑钉定（合法对照仍通过）。
H4（M1b history-summary 源可读性与身份绑定门切片）同口径补充：
build_history_summary 入口已存在（H1 已 GREEN），RED 不经入口缺
失分支给出，分两类钉出：
- 声明源缺失（源条目目录缺失/为空，或 manifest.json / prompt.yaml
  单文件缺失）时当前实现一律 PromptMigrationBlocked 整批拒绝
  （缺失被当 blocked，entry 消失，无字段级 unknown_reason /
  attempted_source），本文件把该拒绝转成显式行为 AssertionError
  （原始域错误经 cause 链保留）钉出“缺失资料字段级 unknown 行为
  缺失”；
- 源文件可解析但身份字段（manifest.json / prompt.yaml 的
  revision_id）与 source_legacy_id 矛盾时当前实现静默构建文档
  （在错误身份下提取事实），由 _expect_history_summary_fail_
closed 的显式 AssertionError（“不得静默构建 history-summary 文
档”）钉出“history-summary 身份绑定门缺失”。
源文件存在但坏 JSON/YAML（含顶层非 mapping）四参数当前实现已
经明确域错误通道整批 fail-closed，记录为 Unexpected PASS（回归
钉），不当 RED；合法已确认 entry 的正向构建由既有 H1 selector
复跑钉定（合法对照仍通过）。
H5（M1b history-summary prepare-only run 历史条目切片，prepare-only
run 不得成为训练事实）同口径补充：build_history_summary 入口已存在
（H1 已 GREEN），RED 不经入口缺失分支给出 —— 当前实现不按 kind 分流
（对任意非空 kind 一律按 prompt registry 源构建 prompt 形态 entry），
对已确认 prepare_only_run entry 静默构建无 training_status、无核心
训练参数事实的 prompt 形态文档（六个 prompt 事实全部 unknown），由
training_status 断言的显式 AssertionError 钉出“prepare-only run
历史条目行为缺失”；若实现改为对该 kind fail-closed 拒绝（仅准备资
料的 run 不是非法输入，H2/H3 非法输入域未覆盖它，拒绝会使 entry 消
失），同样经本切片的 try/except 转译为显式行为 AssertionError（原
始域错误经 cause 链保留）钉出同一 RED 结论；合法 prompt_history
entry 的正向构建由既有 H1 selector 复跑钉定（合法对照仍通过）。
H6a（M1b weight run 历史条目第一切片，单个已确认 weight_run entry
的历史字段提取）同口径补充：build_history_summary 入口已存在（H1
已 GREEN），RED 不经入口缺失分支给出 —— 当前实现不按 kind 分流到
run 历史路径（对 weight_run 仍走 prompt registry 源路径），对已确认
weight_run entry 静默构建无 training_status、无 fold/weights 已知
事实、无核心训练参数事实的 prompt 形态文档（六个 prompt 事实全部
unknown，attempted_source 指向不存在的 pipeline/prompt_registry/
<run_id>/），由 training_status 断言的显式 AssertionError 钉出
“weight run 历史条目行为缺失”；若实现改为对该 kind fail-closed 拒
绝（有权重 run 是 M0 明确允许保留的简明历史记录，拒绝会使 entry 消
失），同样经本切片的 try/except 转译为显式行为 AssertionError（原
始域错误经 cause 链保留）钉出同一 RED 结论；合法 prompt_history 与
prepare_only_run entry 的正向构建由既有 H1/H5 selector 复跑钉定
（合法对照仍通过）。
H6b（M1b weight run 历史条目第二切片：权重存在性判定口径一致 + 声明
run 源缺失 known gap 分流）同口径补充：build_history_summary 入口与
weight_run 分流已存在（H6a 已 GREEN），RED 不经入口缺失分支给出，两
类钉出：
- 权重存在性口径：当前实现 adapter_present 以递归任意文件判定 ——
  fold0/adapter 只剩非权重元数据文件（adapter_config.json /
  README.md）时仍输出 adapter_present == True；本文件由该已知事实值
  断言（期望已知 False）钉出"非权重文件被误判为权重"；merged 侧由
  对称场景（只剩非权重文件）钉定 merged_present 不得反向放宽为任意
  文件口径（防"统一口径"向更宽方向统一）。
- 声明 run 源缺失：当前实现对该形态 fail-closed 抛 PromptMigration-
  Blocked（"known gap 处理不在本切片内"），entry 消失、整批 blocked；
  本文件把该拒绝转成显式行为 AssertionError（原始域错误经 cause 链
  保留，不得直接充当 RED 结论）钉出"缺失资料字段级 unknown 行为缺
  失"；training_status 若仍输出 weights_observed（信任 entry 声明而
  非重新观察）由无证据声明断言钉出；合法 prompt_history /
  prepare_only_run / 有证据 weight_run entry 的正向构建由既有
  H1/H5/H6a selector 复跑钉定（合法对照仍通过，缺失分流不得过宽）。

范围边界：本文件只覆盖 Prompt 迁移（T1–T10）、T11–T14 数据迁移批级
只读预检切面（ready 正向、目标冲突边界、已钉扎 manifest provenance
门、manifest files 声明的 payload 文件哈希复算门）、T15–T18 单对象/批级
data 真实转换切面与 H1 history-summary 单条历史 Prompt entry 最小
正向纯构建切面 —— T1 ready 正向
最小切面、
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
路径维护，行为契约不变）、T11 数据迁移批级只读预检 ready 正向
（两条已确认 data 映射整批 ready + 逐对象报告 + 零写入 + legacy
源树与旧 active pointers 逐字节不变 + 不就地改写映射项；ready 不
依赖 payload 已验证）、T12 data 预检目标冲突边界（reviewer 对 T11
的 P2：data 正式对象根 data/releases/ 上同身份目录 —— 即使缺少
release.yaml —— 与同身份非标准文件形式必须整批 blocked + 冲突经逐
对象报告归因 + 零写入、legacy 源与旧 active pointers 不变；r10 等
更高 revision 邻居不得误阻塞）、T13 data 批级预检已钉扎 legacy
manifest provenance 门（指针 finetune/active_data_release.json 钉扎
的活动 release 映射项：指针 release_id 必须等于其 source_legacy_id +
manifest 文件字节复算 sha256 与指针 expected_manifest_sha256 比对，
匹配保持 ready；指针缺失/非 JSON/字段缺失/ID 不符/哈希不匹配整批
blocked + 按对象归因 + 零写入 + 指针与 legacy 源不变；r1 无钉扎
不阻塞、不伪造 verified/passed；首位与末位篡改双向钉定）、T14 data
批级预检 legacy manifest payload 文件哈希 provenance 门（manifest
files[] 声明的每个 payload 文件按文件字节复算 sha256 与声明值比对：
匹配保持 ready；r1（批内第二位）与 r2（第一位）payload 字节被等长
篡改双向钉定，entry 缺 sha256 字段或 path 穿越异常（指向 release
目录之外、文件仍存在）即该对象 blocked + 整批 blocked + 按对象归因
+ 非空 reasons + 零写入 + legacy 源与旧 pointers 不变；manifest 自
洽性/内容完整性机制不等于训练机真实 payload 已验证，r1 无钉扎不伪
造 verified）、T14-P3 payload 路径 symlink loop fail-closed（reviewer
对 T14 的 P3：manifest files[] 声明的 payload 路径解析成环时不得
让 RuntimeError / OSError 穿透预检入口，必须经报告通道该对象
blocked + 整批 blocked + 非空 reasons + 零写入，正常哈希匹配对象
仍 ready）、T15 单对象 data 真实转换最小切片（对单条已确认 r2 映射
v4.1.0-ecb5aeb9657c -> data-v4.1-r2 执行真实转换：在目标 root 下创建
正式 release data/releases/data-v4.1-r2/，目标内容恰为 release.yaml +
legacy manifest files[] 声明的 payload 文件集合且逐文件字节一致；
release.yaml 经既有 load_release_metadata 读取/校验语义接受，version
为 data-v4.1-r2、status 为 active、replacement 不存在；语义字段
（protocol / purpose / training_allowed / sample_count / splits /
source_batches）取 legacy manifest 声明值，不重算或伪造（fixture 注入
与 payload 可复算值故意不同的 counts 钉定语义溯源）；目标对象完整
写入并验证后在目标 root 的 migration_receipts/data-v4.1-r2.receipt.yaml
创建 committed receipt（八字段完整：operation_id / source_legacy_id /
target_identity / target_path / source_manifest_sha256 /
target_release_digest / status / written_at；source_manifest_sha256 与
源 manifest 文件字节哈希一致，target_release_digest 可由目标内容复算
核实）；legacy 源与旧 active pointers 逐字节不变；不写 records、不
触发 DVC、目标数据根以可注入 root 表示（测试只用 pytest tmp_path，
不创建训练机真实路径））、T15-P2-1 迁移目标封存绑定（reviewer 对
T15 的 P2-1：state: sealed 的迁移目标必须真实满足既有封存语义 ——
assert_payload_sealed 只读门通过 + release 根与全部 payload 文件/
目录去全部写位 + release.yaml 受控更新通道保留创建时写位 + receipt
与 migration_receipts/ 不随封存去写位 + legacy 源（含权限位）与旧
active pointers 不变 + T15 内容/receipt 契约不回归）、T15-P2-2 迁移
写入前 manifest files[] re-validation（reviewer 对 T15 的 P2-2：原始
precheck 通过后、写入前重新读取 manifest 时必须重新校验 files[] 声明
路径的安全性与 payload 存在性 —— precheck 后把 manifest 改为路径穿越
（写入侧越出目标 release）或删除一个声明 payload 文件，必须经
DataMigrationBlocked fail-closed 且零写入：不写目标外路径、不留半写
release、不写 receipt，legacy 源与旧 pointers 逐字节不变，不就地修改
映射项）、T16 单对象 r1 superseded data 真实转换切片（前提：目标
root 已存在正式 data-v4.1-r2 —— 先经当前 migrate_data 创建 r2，再对
单条已确认 r1 映射 v4.1.0-760050fad303 -> data-v4.1-r1（target_status
``superseded``、replacement ``data-v4.1-r2``，D1 用户确认）执行真实
转换：创建 data/releases/data-v4.1-r1/，payload 与 legacy r1 源逐
文件一致；release.yaml 经既有 load_release_metadata 读回，version 为
data-v4.1-r1、status 为 superseded、replacement 为 data-v4.1-r2 且在
目标 root 下可解析为既有正式 active r2；validate_training_reference
对 r1 拒绝（ReferenceNotAllowed）、对 r2 放行；写入 r1 committed
receipt（八字段与 T15 同语义，两处哈希独立复算核实）；语义字段取 r1
manifest 声明值（fixture 注入与 payload 可复算值、r2 声明值均不同的
counts 钉定语义溯源与读错源）；legacy 源与旧 active pointers 逐字节
不变，既有 r2 正式对象与 receipt 不被触碰；不做批级恢复、凭证失配、
重跑幂等）、T17 双对象批转换终态切片（一次 migrate_data 调用传入
r2+r1 两条已确认映射（D2 推荐顺序 r2 先于 r1）：两个正式 release 创
建并保留 —— r2 active（replacement 不存在）、r1 superseded 且
replacement=data-v4.1-r2 在同一次调用内解析为既有正式 active r2；
validate_training_reference 对 r2 放行、对 r1 拒绝（ReferenceNotAllowed）；
两份 committed receipt（八字段、双对象凭证互不相同、两处哈希独立复
算核实）；目标根恰含两个 release 与两份 receipt；未映射 sibling 不被
转换；legacy 源与旧 active pointers 逐字节不变；不做中断恢复、凭证
失配、重跑幂等；批内乱序输入（r1 先于 r2）的写入顺序行为不绑定）、
T18 完成态批级重跑幂等跳过切片（复用 T17 双对象 fixture：第一次完
整双对象批转换后，同 root、同映射、同 legacy 源的第二次 migrate_data
调用必须成功 —— 不把已完成的 r1/r2 正式对象当成外来冲突拒绝；两个
对象都识别为已完成并跳过：两个目标 release 子树与两份 receipt 逐字
节不变（含 written_at）、目标侧 mtime 与权限位零变化、不产生
data-v4.1-r3 等新身份、legacy 源与旧 active pointers 不变、不就地修改
映射项；跳过的报告通道与 migrate_data 返回值不绑定；不做中断恢复 ——
批内存在未完成对象时的"继续"语义与凭证失配拒绝不在本切片）、
T18-P2 完成态重跑 receipt 核实 replacement 绑定切片（reviewer 对 T18
的 P2，先写测试，不改 production：复用 T17/T18 双对象 fixture，第一
次完整双对象批转换 + 同映射幂等重跑成功后，仅把 r1 映射（superseded）
的 replacement 从 data-v4.1-r2 变更为另一完整 data 身份 data-v4.1-r9
—— 空目标根上 precheck-ready 的格式合法变体，保持同 root、同
legacy 源 —— 再次 migrate_data 调用必须经 DataMigrationBlocked
fail-closed 拒绝，不得静默跳过；既有两个 release 与两份 receipt 逐字
节不变（含 written_at）、零新增/删除条目（不产生 data-v4.1-r9 /
data-v4.1-r3 等新身份）、目标侧 mtime 与权限位零变化、legacy 源与旧
active pointers 不变、不就地修改传入映射项；恢复原 replacement 后的
同映射重跑仍成功跳过（拒绝不得过宽到拒绝一切完成态重跑）；核实纳
入 replacement 的具体机制与拒绝信息文本不绑定；映射其他字段
（target_status / target_path / source_legacy_id /
candidate_target_identity）的完成态失配已由 T18 既有核实口径覆盖
（receipt 逐字段比对 + operation_id 绑定 target_status），receipt 自身
被篡改的拒绝分支与批内部分完成恢复仍不在本切片）、T19 批内部分完成的
中断恢复切片（先写测试，不改 production：复用 T17/T18 双对象 fixture 与
并行双根（baseline / interrupted，fixture 字节级同构，baseline 根不受
注入干净转换一次）：对双对象批 [r2, r1]（D2 推荐顺序 r2 先于 r1）开始
转换，monkeypatch 在第二个对象 r1 的目标写入中途注入失败（仅命中
data/releases/data-v4.1-r1/ 子树内的 Path.write_bytes /
Path.write_text：写入非空严格前缀落盘后抛 OSError）—— 第一次调用必须
显式失败（struck_writes 非空钉死注入确实命中）；r2 作为已完成对象保留
（完整正式 release + committed receipt），r1 不得留下可被误认为正式完成
的对象（既有读取语义不能把 r1 读回为正式 release）且无 r1 committed
receipt —— 同一个 ``migration_receipts/data-v4.1-r1.receipt.yaml`` 按用
户确认生命周期以 in_progress 状态保留（中断后保留同一个 in-progress
receipt），不得另立 credential 目录或额外凭证文件；legacy 源与旧
pointers 逐字节不变；恢复注入后同 root、同映
射、同 legacy 源重跑必须成功：跳过凭证匹配的已完成 r2（release 与
receipt 逐字节不变、written_at 不刷新、r2 侧 mtime 不动）、继续并完
成 r1；最终两个目标 release 与无中断 baseline 逐文件字节一致，receipt
与 baseline 逐字段语义相等（written_at 记录各自写入时刻、单独排除，
其余七字段含确定性 operation_id / target_release_digest 必须相等）；
r1 读回为 superseded、replacement 解析为既有 active r2、语义字段取
manifest 声明值、封存事实保持；无新身份、不写 records / 生命周期目
录 / .dvc、不就地修改映射项；本切片不做凭证失配拒绝、乱序批输入、
migrate_data 返回值契约与跳过/继续的报告通道）、T19-P3 中断后 legacy
源内容变化的重跑 fail-closed 切片（D2 关键安全边界，先写测试，不改
production：复用 T19 中断 fixture，第一次转换 r2 完成、r1 写入中途被
中断后修改 legacy 源内容使恢复依据失配 —— 已完成对象 r2 的 manifest
counts 变更（指针 expected_manifest_sha256 随改复算保持 T13 钉扎门
绿、files[] 声明哈希不动保持 T14 自洽门绿，receipt 绑定的
source_manifest_sha256 与期望 release.yaml 内容失配）或未完成对象 r1
被中断命中那份 payload 在半写前缀区域内等长变更（manifest 声明哈希
随改复算保持 T14 自洽门绿，半写残骸不再是按当前源复算期望字节的严
格前缀）—— 同 root、相同映射重跑必须经 DataMigrationBlocked
fail-closed 拒绝且零写入：不跳过失配对象、不继续写入 r1、不重写 r2
或 receipt、不产生新身份、旧 pointers 与其余 legacy 内容零额外变化，
中断后保留的同一个 in-progress receipt 逐字节原样、不得被覆盖为
committed、不得另立 credential 目录；
恢复源原字节后的重跑仍成功跳过 r2 完成 r1（拒绝不得过宽；同一个
receipt 文件由 in_progress 原子转为 committed —— 用户确认生命周期，
不得新增额外 credential 文件或目录）；本切片
不做凭证失配消息优化，也不覆盖半写前缀区域不受影响的源变更（恢复
依据未失配：半写仍可核实为本转换部分写入，按 D2“未完成对象继
续”以当前全量预检验证过的源完成，如需钉定中断时刻源内容快照须另立
切片 —— 当前架构未持久化部分写入对象的源摘要，无法区分“源从未变
化”与“源在不影响已落盘前缀的区域变化”；已由后续 T19-P4 切片钉
定））、T19-P4 部分写入对象的中断前源快照凭证与“任何源内容变化都
停止”切片（D2 边界补齐 + 用户裁决的 in-progress receipt 生命周期，
先写测试，不改 production：用户已确认 —— 每个对象使用同一个
``migration_receipts/<target_identity>.receipt.yaml``，写入前该文件为
``status: in_progress``、``target_release_digest: null``，成功后原子替换
为 ``status: committed`` 与目标 digest；不使用
``migration_receipts.in_progress/`` 等独立 credential 目录；中断后保
留同一个 in-progress receipt，恢复成功后同一个文件转为 committed。
两个用例 ——
credential 存在性用例：双对象批 [r2, r1] 第一次转换 r2 完成、r1 写入
中途被中断（T19 同款注入）后，同一个
``migration_receipts/data-v4.1-r1.receipt.yaml``
必须已存在且为可核实的 in-progress receipt（不得接受独立 credential 目
录或任何额外凭证文件：按内容扫描目标树，绑定 r1 的非 committed 凭证
只能有该同一文件，目标侧不得新增 receipt 两份与两个 release 子树之外
的任何条目），status 必须为 in_progress、
target_release_digest 必须为 null，至少绑定
operation_id（非空字符串）、source_legacy_id / target_identity /
target_path（与 r1 映射项精确相等）、source_manifest_sha256（中断前
r1 源 manifest 文件字节 SHA-256）、映射 target_status（superseded）与
replacement（data-v4.1-r2），且不得标记 committed（也不得存在把未完
成 r1 伪称 committed 的绑定条目）；注入契约保证 receipt 写入时点先
于 r1 目标写入（第一次 r1 子树内写入即被中断命中且调用就此失败，完整
可解析的 in-progress receipt 只能在此之前落盘；credential 落在 r1 目标子树内
即被注入命中、不完整不可核实，等于不存在）；legacy 侧与旧 pointers
逐字节不变；源不变、同 root、同映射重跑必须仍成功（T19 恢复不回
归 —— in-progress receipt 是恢复依据不是恢复障碍），r1 完成后同一个
receipt 文件原子转为 committed receipt，保持既有八字段契约（不夹带
in-progress 凭证字段或映射项 dump），migration_receipts/ 恰含两份
receipt；fail-closed 用例：中断后修改 r1 源
manifest counts.published_candidates 11 -> 12（单一变量扰动，不影响已
落盘 payload 前缀：payload 字节与 files[] 声明不动保持 T14 自洽门
绿、r1 无钉扎保持 T13 指针门绿、残骸内无 release.yaml 且残骸字节仍
是当前源期望 payload 的严格前缀 —— 按当前“以当前源复算期望字节”
的恢复口径半写仍可核实，唯一能发现源已变化的只有中断前源快照
in-progress receipt），同 root、相同映射重跑必须经 DataMigrationBlocked
fail-closed 拒绝且零写入：不继续写入 r1、不重写 r2 或其 receipt、不
把同一个 r1 in-progress receipt 覆盖/补写为 committed（逐字节原样保
留）、不产生新身份、legacy 其余内容与旧 pointers
不变；恢复源原字节后重跑仍成功跳过 r2 完成 r1（拒绝不得过宽，r1 语
义字段取已恢复 manifest 声明值、同一个 receipt 文件由 in_progress 原
子转为 committed 且八字段契约保持、源绑定恢复后源快照）；本切片不
覆盖前缀区域受影响的源变化与已完成对象源变化（均
T19-P3 已钉）、不做 in-progress receipt 自身缺失/被篡改的拒绝分支、批内首个
对象即中断、拒绝信息文本、CLI、DVC、训练机真实路径；credential 的
文件名/位置/完成后转写已由用户裁决绑定（同一 receipt 文件、原子转
committed），不再是不绑定项）、T19-P4-P2 写入前数据校验失败的零写入
补丁切片（reviewer 对 T19-P4 的 P2，先写测试，不改 production）——
T19-P4 钉定的 in-progress receipt 生命周期（同一个
migration_receipts/<target_identity>.receipt.yaml，写目标前
in_progress、成功后原子转 committed）隐含时序契约：credential 只允
许在对象的全部写入前校验通过、即将开始写目标 release 时落盘；当前
production 把 credential 写在 superseded replacement 可解析性校验与
release 语义字段校验（counts.splits 派生等）之前，两类写入前数据校
验失败时 in-progress receipt 已落盘 —— fail-closed 拒绝留下绑定失败
输入的 stale credential，并把修正输入后的重跑堵死（credential 逐字
段核实失配即拒绝）。两个用例 —— 悬空 replacement 用例：双对象批
[r2, r1]（r1 replacement=格式合法但目标 root 无对应正式 release 的
data-v4.1-r9，变体批 precheck ready —— 失败只能由写入阶段的
replacement 可解析性校验归因）第一次调用必须经 DataMigrationBlocked
拒绝（r2 先完成保留）；拒绝必须真正零写入：不创建 r1 目标 release
目录、不留 in-progress receipt（migration_receipts/ 恰含 r2 committed
receipt 一份、data/releases/ 恰含 r2 一棵子树、目标侧无任何额外条
目、legacy 与旧 pointers 逐字节不变）；修正输入（replacement 改指
已完成的 data-v4.1-r2）后的重跑必须成功（不得被失败遗留的 stale
credential 失配拒绝堵死）：r2 幂等跳过零重写、r1 完整完成，终态与既
有 T17 双对象契约一致；非法 release 语义字段用例：r1 legacy manifest
counts 删除 splits 声明（files[] 声明哈希不动保持 T14 自洽门绿、r1
无钉扎保持 T13 指针门绿、批 precheck ready —— 失败只能由写入阶段
的 release 语义字段校验归因）同样必须 DataMigrationBlocked + 零写入
（无目标目录、无 in-progress receipt）；恢复 manifest 原字节后的重
跑必须成功（r2 幂等跳过、r1 完整完成、receipt 绑定恢复后源 manifest
哈希）；两用例均不做拒绝信息文本、批内首个对象即失败、credential
写入后的补偿清理（要求校验先于写入而非写入后补偿）、in-progress
receipt 自身缺失/被篡改的拒绝分支（T19-P2/P4 既有口径）、CLI、
DVC、训练机真实路径；T19-P4 正常中断 credential 生命周期不回归由既
有 T19-P4 selector 复跑钉定、H1 history-summary 单条历史 Prompt
entry 最小正向纯构建切片（M1b 第一个 current behavior：对 kind
prompt_history、source_legacy_id v4.1-concise-evidence-json-v1、
status user_confirmed 的单条已确认 entry 调用
build_history_summary(root, entries) 返回 history-summary 文档 ——
history_summary_schema 为 tensile-migration/history-summary/v1、
entries 恰含声明一条、original_id 保留原始 legacy ID、
history_only: true、formal_identity: "none"、entry_id 为文档内 slug
且非 <kind>-v<协议>-r<N> 正式身份、文档内任何字符串值都不是正式
身份；facts 从该 entry 的 legacy manifest/prompt 源提取（protocol_id /
prompt_content_sha256 / publishing_code_commit / system_prompt /
user_prompt / output_fields 六个必需事实，逐值与 legacy 源声明值相等，
不重算不伪造不取 sibling），已知值形态 {value, source{...}}、source
为非空 mapping 且可指回声明源的 legacy 文件（manifest-only 事实须
指 manifest.json、prompt.yaml-only 事实须指 prompt.yaml）；纯构建零
写入 —— 全树逐字节不变、legacy 源不变、不写 history-summary 文
件、不创建 records/、不就地修改传入 entry；fixture 镜像真实 legacy
prompt registry 完整三条目（v1 已确认历史源 + v2 /
fixed-full-fields-initial-v1 两个未声明 sibling，逐源内容不同），未
声明 sibling 的 ID 不得进入文档）；
以上切片之外
不实现/不要求
data 真实转换的其余行为（批级多对象乱序写入顺序、
批级恢复的其余形态（批内首个对象写入中途即中断的零完成对象恢复、
中断残骸清理/保留策略）、凭证失配拒绝的其余分支（映射字段变更的
完成态失配已由 T18-P2 钉、receipt 缺失/被篡改已由 T19-P2 钉、源内
容变化已由 T19-P3/T19-P4 钉；in-progress receipt 自身缺失/被篡
改的拒绝分支仍不绑定；其文件名/位置/完成后转写已由用户裁决绑定：
同一个 migration_receipts/<target_identity>.receipt.yaml，写入前
in_progress、成功后原子转 committed，不另立 credential 目录））、data blocked 反向其余场景（身份契约收紧、legacy 源
release 目录/manifest 缺失、声明的 payload 文件缺失——该存在性分支
由既有 production 检查 blocked，本文件未单列用例钉定）、history-
summary 的其余切面（H1 钉单条已确认 prompt_history entry 的纯构
建正向；H2/H3 钉非法输入 fail-closed 反向最小切片 —— entry
status 非 user_confirmed（pending_user_check / unknown /
not_verified / verified_local 事实分级误当确认门槛 / 字段缺失，
白名单式只认 user_confirmed）、夹带候选正式身份

candidate_target_identity（prompt-v4.1-r1 / model-v4.1-r1 等五族
完整身份；历史 entry history_only，不分配新正式身份）、声明
passed: true（M0：不得把历史 summary 转成 passed）、entries=None
与非可迭代输入（不得静默返回空文档），以及未确认+夹带身份、
声明 passed+夹带身份两类组合（各门相互独立）—— 一律经明确域错
误或 blocked 报告通道拒绝 + 非空拒因 + 零写入（legacy 源与全树逐
字节不变）+ 不就地修改传入 entries，合法已确认 entry 对照仍正常
构建（H1 selector 复跑钉定）；可迭代但元素非 mapping 的 entries
当前已经明确域错误通道 fail-closed，记为 Unexpected PASS 回归钉；
unknown/缺失资料形态、多 entry 批量与混合完整/缺失资料、
history-summary 文件写入、CLI 均不在本切片）、自动恢复/续传逻辑（冲突场景只断言 blocked 与零写入；
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

import errno
import hashlib
import importlib
import importlib.util
import json
import math
import shutil
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest
import yaml

from versioning.data_release import (
    DataReleaseError,
    ImmutableReleaseError,
    assert_payload_sealed,
    load_release_metadata,
    validate_training_reference,
)
from versioning.ids import is_valid_version_id
from versioning.prompts import (
    PROMPT_REQUIRED_FIELDS,
    PromptConflict,
    PromptError,
    load_prompt,
    prompt_path,
)
from versioning.state import DataStatus, ReferenceNotAllowed

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


# ---------------------------------------------------------------------------
# T11：数据迁移批级只读预检 —— 两条已确认 data 映射整批 ready + 逐对象
# 报告 + 零写入（M1a data precheck ready 切片，先写测试）
# ---------------------------------------------------------------------------

# M0 object-mapping.yaml data_mapping.items 的两条已确认映射（用户
# 2026-09-07 确认；D1：r1 superseded + replacement=data-v4.1-r2；
# r2 active）。R1 源为较旧 base release，R2 源为较新 Phase2 release
# （活动指针指向的 release）。
CONFIRMED_DATA_SOURCE_R1 = "v4.1.0-760050fad303"
CONFIRMED_DATA_TARGET_R1 = "data-v4.1-r1"
CONFIRMED_DATA_SOURCE_R2 = "v4.1.0-ecb5aeb9657c"
CONFIRMED_DATA_TARGET_R2 = "data-v4.1-r2"
# 未映射 sibling release（不在 data_mapping.items 中；合成 12-hex 旧哈希
# 身份，布局与两份已确认源同构）：钉死实现必须按映射项定位源、不得扫描
# 全 releases 目录（要求全目录都有映射 / 把 sibling 一并写入对象报告的
# 实现必被本切片捕获）。
UNMAPPED_DATA_SIBLING = "v4.1.0-0a1b2c3d4e5f"

# 批级只读预检必须保持不存在的目标根（M0：本机 <root>/data、records
# 均不存在）；working / release_staging 为数据 release 生命周期目录名
# （versioning/data_release.py），records/ 为新体系正式对象根。
_PRECHECK_FORBIDDEN_ROOTS = ("data", "working", "release_staging", "records")


def _fixture_pretty_json_bytes(value: Any) -> bytes:
    """合成 fixture 的 pretty JSON 字节（口径镜像真实 release manifest 写出）。

    与 pipeline/v4_1_training_release.py::_pretty_bytes 相同：
    json.dumps(..., ensure_ascii=False, indent=2, sort_keys=True,
    allow_nan=False) + "\\n"。fixture 独立镜像写出口径而非 import
    production，使 manifest 布局漂移先在 fixture 前置事实上暴露。
    """
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _synthetic_data_contract_hash() -> str:
    """合成 contract_hash（64-hex；结构对齐真实 v4.1 contract_hash 字段，值非真实契约）。"""
    return hashlib.sha256(
        "tensile-vlm/v4.1 合成 fixture contract（非真实训练机契约）".encode(
            "utf-8"
        )
    ).hexdigest()


def _legacy_data_payload_files(
    release_id: str, contract_hash: str, *, phase2: bool
) -> dict[str, bytes]:
    """合成但结构镜像真实 v4.1 训练 release payload 的文件集合。

    真实 release（pipeline/v4_1_training_release.py /
    v4_1_phase2_training_release.py 写出）的 payload 布局为
    metadata/training_candidates.json、datasets/{train,validation}/
    fold_N.json 与 reports/quality_report.json；Phase2 增量 release 另含
    metadata/combined_review_decisions.json。本 fixture 字段值合成、内容
    逐 release 嵌入 release_id（三份 release 的 payload 字节互不相同，
    使“读错源 / 从 sibling 补齐”的实现可捕获），结构与上述事实字段
    一致。
    """
    candidates = {
        "schema_version": "tensile-training-candidates/v4.1",
        "contract_hash": contract_hash,
        "candidates": [
            {
                "candidate_id": f"{release_id}-cand-{index:03d}",
                "scope": "development",
                "labels": {
                    "clip_state": "未断裂",
                    "fracture_mechanism": None,
                    "fracture_site": None,
                    "special_case": None,
                },
            }
            for index in range(3)
        ],
        "excluded": [],
        "candidate_count": 3,
        "excluded_count": 0,
    }
    files: dict[str, bytes] = {
        "metadata/training_candidates.json": _fixture_pretty_json_bytes(
            candidates
        ),
        "reports/quality_report.json": _fixture_pretty_json_bytes(
            {
                "release_id": release_id,
                "contract_hash": contract_hash,
                "counts": {"published_candidates": 3, "excluded_candidates": 0},
            }
        ),
    }
    if phase2:
        files["metadata/combined_review_decisions.json"] = (
            _fixture_pretty_json_bytes(
                {
                    "schema_version": "tensile-vlm-v4.1-combined-review/v1",
                    "combined_id": f"combined-{release_id}-fixture",
                    "release_id": release_id,
                }
            )
        )
    for fold in range(3):
        for split, directory in (("train", "train"), ("val", "validation")):
            files[f"datasets/{directory}/fold_{fold}.json"] = (
                _fixture_pretty_json_bytes(
                    {
                        "release_id": release_id,
                        "fold": fold,
                        "split": split,
                        "samples": [
                            f"{release_id}-cand-{index:03d}" for index in range(3)
                        ],
                    }
                )
            )
    return files


def _write_legacy_data_release(
    root: Path,
    release_id: str,
    *,
    contract_hash: str,
    base_release_id: str | None = None,
) -> bytes:
    """在 workspace/data/releases/<release_id> 下写入合成 legacy data release。

    镜像 M0 source-inventory.yaml data_releases 证据布局：
    ``<release_id>/manifest/release_manifest.json`` + payload。manifest
    字段名与事实字段对齐真实 v4_1_training_release /
    v4_1_phase2_training_release 写出的 release_manifest.json（base
    release 含 source_snapshot_id / split_snapshot_id；Phase2 增量
    release 含 base_release_id / combined_review_id）；files 声明值按
    本 fixture 实际 payload 字节复算（path / size_bytes / sha256），
    保持源内自洽（真实声明值见训练机 payload；fixture 字段值合成）。
    返回 manifest 字节。
    """
    release_dir = root / "workspace" / "data" / "releases" / release_id
    payload = _legacy_data_payload_files(
        release_id, contract_hash, phase2=base_release_id is not None
    )
    for relative, content in payload.items():
        target = release_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    manifest: dict[str, Any] = {
        "schema_version": "tensile-training-release/v4.1",
        "release_id": release_id,
        "status": "training_ready",
        "immutable": True,
        "contract_version": "tensile-vlm/v4.1",
        "contract_hash": contract_hash,
        "label_semantics": "frame_window_authoritative",
        "source_review_batch_id": f"review-batch-{release_id}-fixture",
        "source_queue_id": f"queue-{release_id}-fixture",
        "source_media_id": f"media-{release_id}-fixture",
        "counts": {
            "published_candidates": 3,
            "excluded_candidates": 0,
            "reviewed_candidates": 3,
        },
        "provenance": {
            "data_version": "4.1.0",
            "contract_hash": contract_hash,
            "release_id": release_id,
        },
        "files": [
            {
                "path": relative,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for relative, content in sorted(payload.items())
        ],
    }
    if base_release_id is None:
        manifest["source_snapshot_id"] = None
        manifest["split_snapshot_id"] = None
    else:
        manifest["base_release_id"] = base_release_id
        manifest["combined_review_id"] = f"combined-{release_id}-fixture"
        manifest["provenance"]["base_release_id"] = base_release_id

    manifest_path = release_dir / "manifest" / "release_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = _fixture_pretty_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    return manifest_bytes


def _write_legacy_data_layout(root: Path) -> bytes:
    """构建 T11 批级预检的完整 legacy fixture（M0 证据布局）。

    包含：
    - 两条已确认映射的 legacy data release：v4.1.0-760050fad303
      （较旧 base release）与 v4.1.0-ecb5aeb9657c（较新 Phase2
      release，base_release_id 指向 760050fad303，镜像 M0
      source-inventory / model_registry origin.release_id 事实）；
    - 未映射 sibling release v4.1.0-0a1b2c3d4e5f（完整同构布局，
      不在映射中）；
    - 旧数据活动指针 ``finetune/active_data_release.json``（镜像 M0
      pinned_by 事实；expected_manifest_sha256 / expected_contract_hash
      随合成活动 release manifest 复算，保持指针与源内自洽 —— 真实声明值
      见 M0 pin_facts，fixture 值随合成内容）；
    - 旧 Prompt 活动指针 ``pipeline/prompt_control/active_prompt.yaml``
      （声明 legacy revision_id；数据预检不得触碰）。

    返回活动 release（ecb5aeb9657c）的 manifest 字节。
    """
    contract_hash = _synthetic_data_contract_hash()
    _write_legacy_data_release(
        root, CONFIRMED_DATA_SOURCE_R1, contract_hash=contract_hash
    )
    active_manifest_bytes = _write_legacy_data_release(
        root,
        CONFIRMED_DATA_SOURCE_R2,
        contract_hash=contract_hash,
        base_release_id=CONFIRMED_DATA_SOURCE_R1,
    )
    _write_legacy_data_release(
        root, UNMAPPED_DATA_SIBLING, contract_hash=contract_hash
    )

    data_pointer = root / "finetune" / "active_data_release.json"
    data_pointer.parent.mkdir(parents=True, exist_ok=True)
    data_pointer.write_text(
        json.dumps(
            {
                "release_id": CONFIRMED_DATA_SOURCE_R2,
                "release_dir": (
                    f"workspace/data/releases/{CONFIRMED_DATA_SOURCE_R2}"
                ),
                "manifest": (
                    f"workspace/data/releases/{CONFIRMED_DATA_SOURCE_R2}"
                    "/manifest/release_manifest.json"
                ),
                "expected_contract_hash": contract_hash,
                "expected_manifest_sha256": hashlib.sha256(
                    active_manifest_bytes
                ).hexdigest(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    active_prompt_pointer = (
        root / "pipeline" / "prompt_control" / "active_prompt.yaml"
    )
    active_prompt_pointer.parent.mkdir(parents=True, exist_ok=True)
    active_prompt_pointer.write_bytes(
        _legacy_prompt_yaml_full(CONFIRMED_PROMPT_SOURCE_ID)
    )

    return active_manifest_bytes


def _confirmed_data_mapping_items() -> list[dict[str, Any]]:
    """逐字段镜像 M0 object-mapping.yaml data_mapping.items 的两条已确认条目。

    含 D1 用户确认字段（r1 条目 target_status superseded + replacement
    data-v4.1-r2；r2 条目 target_status active）。YAML 标量解析为字符串
    （status: user_confirmed -> "user_confirmed"）；source_verified /
    source_payload_complete 保持 M0 事实分级（verified_local /
    training_observed），不由 fixture 伪造成 payload 已验证。字段集与值
    与 M0 证据一致（含 D1 字段），使实现必须按真实证据结构消费映射批。
    """
    return [
        {
            "source_legacy_id": CONFIRMED_DATA_SOURCE_R2,
            "role": "当前活动数据 release（活动指针）",
            "source_verified": "verified_local",
            "source_inventory": (
                f"workspace/data/releases/{CONFIRMED_DATA_SOURCE_R2}"
            ),
            "source_payload_complete": "training_observed",
            "candidate_target_identity": CONFIRMED_DATA_TARGET_R2,
            "target_path": "data/releases/data-v4.1-r2/release.yaml",
            "status": "user_confirmed",
            "target_status": "active",
            "confirmed_by_user_date": "2026-09-07",
            "conflict_check": (
                "本机 <root>/data 不存在 → 当前无目标冲突；目标机器根下 "
                "data/ 需在迁移前复验"
            ),
            "preserve_state": [
                (
                    "release.yaml 的 status / purpose / training_allowed / "
                    "splits / source_batches"
                ),
                "payload 封存（去写位）保持不变",
                "source_batches 记录原始批次，不回填伪造",
            ],
            "notes": "活动 release。已确认 → data-v4.1-r2（较新的 Phase2 release）。",
        },
        {
            "source_legacy_id": CONFIRMED_DATA_SOURCE_R1,
            "role": "历史并存的非活动数据 release",
            "source_verified": "training_observed",
            "source_inventory": (
                f"workspace/data/releases/{CONFIRMED_DATA_SOURCE_R1}"
            ),
            "source_payload_complete": "training_observed",
            "candidate_target_identity": CONFIRMED_DATA_TARGET_R1,
            "target_path": "data/releases/data-v4.1-r1/release.yaml",
            "status": "user_confirmed",
            "target_status": "superseded",
            "replacement": CONFIRMED_DATA_TARGET_R2,
            "confirmed_by_user_date": "2026-09-07",
            "conflict_check": "同上：本机 <root>/data 不存在；目标机器根下复验",
            "preserve_state": [
                "release.yaml 状态字段",
                "payload 封存只读",
            ],
            "notes": "非活动。已确认 → data-v4.1-r1（较旧的上一轮基础 release）。",
        },
    ]


def _resolve_data_precheck_entry() -> Any:
    """惰性解析 T11 批级只读预检入口；模块或入口缺失时返回 None。

    RED Gate 设计（与 _resolve_precheck_entry /
    _resolve_prompt_migration_entry 同口径）：migration 模块已存在而
    precheck_data_migration 入口缺失时返回 None，由调用方以显式行为断言
    钉出“批级只读预检行为缺失”，不让原始 import 错误 / AttributeError
    成为 RED。
    """
    spec = importlib.util.find_spec("versioning.migration")
    if spec is None:
        return None
    module = importlib.import_module("versioning.migration")
    return getattr(module, "precheck_data_migration", None)


def test_confirmed_data_mappings_batch_precheck_returns_ready_without_writes(
    tmp_path: Path,
) -> None:
    r"""已确认两条 data 映射的批级只读预检：整批 ready + 逐对象报告 + 零写入。

    T11 behavior（数据迁移批级只读预检 ready 切片，主 Agent 选定，先写
    测试）—— 对 M0 已确认的两条 data 映射（D1 用户确认）：
    - ``v4.1.0-760050fad303`` -> ``data-v4.1-r1``（target_status
      ``superseded``，replacement ``data-v4.1-r2``）；
    - ``v4.1.0-ecb5aeb9657c`` -> ``data-v4.1-r2``（target_status
      ``active``）；
    执行批级只读预检时必须：
    1. 返回整批 ``ready``（报告经返回值给出，与 T1 绑定的报告通道
       同口径）；
    2. 报告包含逐对象结果：恰好两条对象报告，按 source_legacy_id 可
       归因，每条 target_identity / target_path 与映射一致且对象级
       status == "ready"（未映射 sibling 不得进入对象报告 —— 实现
       必须按映射项定位源，不得扫描全 releases 目录）；
    3. 零写入：不创建 ``<root>/data``、working、release_staging、
       records 或任何目标条目，全树无任何新增/修改/删除；
    4. legacy 源树（workspace/data/releases/ 下三份 release，含未映射
       sibling）与旧 active pointers
       （finetune/active_data_release.json、pipeline/prompt_control/
       active_prompt.yaml）逐字节不变，旧指针仍声明 legacy 身份；
    5. 不就地修改传入映射项：source_verified / source_payload_complete
       保持 M0 事实分级（verified_local / training_observed），预检
       不得把 training_observed 等来源状态伪造成 payload 已验证 ——
       ready 也不得依赖 payload 已验证（本切片不做 payload 内容
       provenance 门）。

    fixture（M0 证据布局，合成内容）：workspace/data/releases/
    <legacy-id>/manifest/release_manifest.json + payload（metadata/
    training_candidates.json、datasets/train|validation/fold_N.json、
    reports/quality_report.json；Phase2 release 另含 metadata/
    combined_review_decisions.json 与 base_release_id）；manifest files
    声明值按 fixture 实际 payload 字节复算保持源内自洽；活动指针
    expected_manifest_sha256 随合成 manifest 复算自洽。

    捕获的合理但错误实现：
    - 入口缺失（当前 production —— RED 起点）：versioning.migration
      无 precheck_data_migration -> 惰性解析返回 None，显式
      AssertionError 钉出“批级只读预检行为缺失”（不让原始 import
      错误 / AttributeError 成为 RED）；
    - 只做单对象预检或只返回批级标志（object_reports 缺失 / 只有一条）
      -> 对象报告数量断言失败；
    - 扫描全 releases 目录：要求所有 release 都有映射（未映射 sibling
      导致误 blocked）或把 sibling 一并写进对象报告（三条）-> ready
      断言或数量断言失败；
    - 从错误位置读源（root/releases、workspace/releases 等）-> 源
      不存在误 blocked -> ready 断言失败；
    - 预检即真实转换（创建 <root>/data/releases/<target>/release.yaml、
      working / release_staging、records）-> 目标根存在性断言 +
      全树快照断言失败；
    - 预检时改写 legacy 源（规范化 manifest、重建 payload、去写位）或
      旧 active pointers -> 全树快照断言失败 + 指针身份断言失败；
    - 把 training_observed 当作确认门槛或 payload 已验证要求（ready
      依赖 payload 完整性验证）-> 对合法 M0 状态输入误 blocked ->
      ready 断言失败；
    - 就地改写映射项（把 source_payload_complete 升级成 verified 等）
      -> 映射项不变断言失败；
    - 以异常替代报告返回 / 写报告文件到磁盘 -> 报告通道与零写入断言
      失败。

    范围边界（本切片不绑定）：blocked 反向行为（任一对象不合格 ->
    整批 blocked + reasons，D2 已确认语义，留待配套反向切片）、目标
    身份契约收紧（kind != data、协议不匹配）、legacy 源必需文件缺失
    反向、目标冲突反向、payload 内容 provenance 门（复算 manifest
    files 哈希）、真实转换（migrate_data_*）、凭证（D2 格式/位置未
    裁决，报告不绑定任何凭证字段）与中断恢复。
    """
    active_manifest_bytes = _write_legacy_data_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()

    # fixture 前置事实（对齐 M0 证据）：两条已确认源 + 未映射 sibling
    # 各含 manifest/release_manifest.json 与全部声明的 payload 文件
    # （manifest release_id / status 自洽）；旧数据指针声明活动 release
    # 并绑定合成 manifest 字节；旧 Prompt 指针声明 legacy revision_id；
    # 目标根（data / records 及生命周期目录 working / release_staging）
    # 均不存在。
    releases_root = tmp_path / "workspace" / "data" / "releases"
    for source_id in (
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
        UNMAPPED_DATA_SIBLING,
    ):
        release_dir = releases_root / source_id
        manifest_file = release_dir / "manifest" / "release_manifest.json"
        assert manifest_file.is_file(), (
            f"fixture 前置事实失败：legacy release manifest 缺失 {manifest_file}"
        )
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert manifest["release_id"] == source_id
        assert manifest["status"] == "training_ready"
        assert manifest["files"], (
            f"fixture 前置事实失败：{source_id} 的 manifest files 不能为空"
        )
        for entry in manifest["files"]:
            payload_file = release_dir / entry["path"]
            assert payload_file.is_file(), (
                f"fixture 前置事实失败：声明的 payload 文件缺失 {payload_file}"
            )
    data_pointer = tmp_path / "finetune" / "active_data_release.json"
    pointer = json.loads(data_pointer.read_text(encoding="utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        active_manifest_bytes
    ).hexdigest(), (
        "fixture 前置事实失败：活动指针 expected_manifest_sha256 必须与合成"
        "活动 release manifest 字节自洽"
    )
    assert pointer["expected_contract_hash"] == _synthetic_data_contract_hash()
    prompt_pointer = (
        tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml"
    )
    assert (
        yaml.safe_load(prompt_pointer.read_bytes())["revision_id"]
        == CONFIRMED_PROMPT_SOURCE_ID
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists()

    before = _snapshot_tree(tmp_path)

    precheck_data = _resolve_data_precheck_entry()
    assert precheck_data is not None, (
        "批级数据迁移只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（当前 behavior 未实现）"
    )

    report = precheck_data(tmp_path, mapping_items)

    # 1：整批 ready（报告只经返回值给出，不落盘、不打印替代）。
    assert report.status == "ready", (
        "两条已确认 data 映射的批级只读预检应返回整批 ready：实际 "
        f"status={getattr(report, 'status', None)!r}"
    )

    # 2：逐对象报告 —— 恰好两条，按 source_legacy_id 归因，对象级
    #    ready，target_identity / target_path 与映射一致；未映射
    #    sibling 不得进入对象报告。
    object_reports = list(report.object_reports)
    assert len(object_reports) == 2, (
        "批级报告必须包含恰好两条逐对象报告（两条已确认映射）：实际 "
        f"{len(object_reports)} 条"
    )
    reports_by_source = {
        obj_report.source_legacy_id: obj_report for obj_report in object_reports
    }
    assert set(reports_by_source) == {
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
    }, (
        "逐对象报告必须恰覆盖两条已确认映射的 source_legacy_id：实际 "
        f"{sorted(reports_by_source)}"
    )
    expected_targets = {
        CONFIRMED_DATA_SOURCE_R1: (
            CONFIRMED_DATA_TARGET_R1,
            "data/releases/data-v4.1-r1/release.yaml",
        ),
        CONFIRMED_DATA_SOURCE_R2: (
            CONFIRMED_DATA_TARGET_R2,
            "data/releases/data-v4.1-r2/release.yaml",
        ),
    }
    for source_id, obj_report in reports_by_source.items():
        target_identity, target_path = expected_targets[source_id]
        assert obj_report.status == "ready", (
            f"{source_id} 的逐对象报告应为 ready：实际 "
            f"{getattr(obj_report, 'status', None)!r}"
        )
        assert obj_report.target_identity == target_identity, (
            f"{source_id} 的逐对象报告 target_identity 应为 "
            f"{target_identity!r}：实际 {obj_report.target_identity!r}"
        )
        assert obj_report.target_path == target_path, (
            f"{source_id} 的逐对象报告 target_path 应为 "
            f"{target_path!r}：实际 {obj_report.target_path!r}"
        )

    # 3：零写入 —— 不创建 <root>/data、working、release_staging、
    #    records 或任何目标条目；全树无任何新增/修改/删除（含 staging、
    #    报告/缓存文件）。
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"批级只读预检不得创建目标根 {forbidden!r}"
        )
    assert _snapshot_tree(tmp_path) == before, (
        "批级只读预检必须零写入：不创建 <root>/data、working、staging、"
        "records 或任何目标条目，不产生报告/缓存文件，不改 legacy 源树"
    )

    # 4：legacy 源树与旧 active pointers 逐字节不变（全树快照已全局钉
    #    定）；旧指针仍声明 legacy 身份，不得被切换到新身份。
    assert (
        json.loads(data_pointer.read_text(encoding="utf-8"))["release_id"]
        == CONFIRMED_DATA_SOURCE_R2
    )
    assert (
        yaml.safe_load(prompt_pointer.read_bytes())["revision_id"]
        == CONFIRMED_PROMPT_SOURCE_ID
    )

    # 5：不就地修改传入映射项 —— source_verified /
    #    source_payload_complete 保持 M0 事实分级（verified_local /
    #    training_observed），不得被伪造成 payload 已验证。
    assert mapping_items == _confirmed_data_mapping_items()


# ---------------------------------------------------------------------------
# T12：data 预检目标冲突边界（reviewer 对 T11 的 P2）—— data 正式对象根
# 上的同身份目录 / 非标准文件形式必须整批 blocked，更高 revision 邻居
# 不得误阻塞（先写测试，不改 production）
# ---------------------------------------------------------------------------

# data 正式对象根下既有条目的哨兵字节：预检只报告冲突，不得覆盖、
# 改名、删除或追加既有条目（同身份条目以任何形式占用即冲突）。
_EXISTING_DATA_ROOT_ENTRY_BYTES = (
    b"<existing data release root entry: must not be touched>"
)


@pytest.mark.parametrize(
    (
        "existing_rel_path",
        "existing_kind",
        "conflicting_source_id",
        "expected_status",
    ),
    [
        pytest.param(
            "data/releases/data-v4.1-r1",
            "dir",
            CONFIRMED_DATA_SOURCE_R1,
            "blocked",
            id="second_item_same_identity_dir_without_release_yaml",
        ),
        pytest.param(
            "data/releases/data-v4.1-r1.yaml",
            "file",
            CONFIRMED_DATA_SOURCE_R1,
            "blocked",
            id="second_item_same_identity_nonstandard_file",
        ),
        pytest.param(
            "data/releases/data-v4.1-r2.yaml",
            "file",
            CONFIRMED_DATA_SOURCE_R2,
            "blocked",
            id="first_item_same_identity_nonstandard_file",
        ),
        pytest.param(
            "data/releases/data-v4.1-r10",
            "dir",
            None,
            "ready",
            id="higher_revision_prefix_neighbor_dir_not_conflict",
        ),
    ],
)
def test_data_batch_precheck_target_conflict_on_data_release_root(
    tmp_path: Path,
    existing_rel_path: str,
    existing_kind: str,
    conflicting_source_id: str | None,
    expected_status: str,
) -> None:
    r"""data 批级只读预检必须在 data 正式对象根上按精确身份检测目标冲突。

    T12 behavior（本切片，reviewer 对 T11 的 P2，先写测试）—— 当前
    production 的 precheck_data_migration 复用 Prompt 的
    ``_check_target_conflict``：只检查映射 target_path 文件占用与
    ``records/`` 下同身份条目，而 data 正式对象根是
    ``data/releases/``（映射 target_path ``data/releases/data-v4.1-rN/
    release.yaml`` 的对象目录层），data 根下同身份目录 / 文件对当前
    实现不可见 -> 误判 ready。行为口径（Spec「正式写入与失败恢复」+
    M0 global_pre_write_checks：目标写入前复验不存在同名正式对象；
    D2：任一对象不合格 -> 整批 blocked）：

    1. 已存在 ``data/releases/data-v4.1-r1/`` 同身份目录（即使缺少
       release.yaml，映射声明的 target_path 文件保持空闲）-> 整批
       blocked；
    2. 已存在同身份非标准文件形式（如 ``data/releases/
       data-v4.1-r1.yaml``）-> 整批 blocked（同身份不允许以任何文件
       形式占用，防改名冲突，与 T4 同口径）；
    3. ``data/releases/data-v4.1-r10/`` 等更高 revision 邻居是不同
       身份（versioning/ids.py 权威解析口径：revision 10 != 1，
       字符串前缀不等于同身份），不得误阻塞 ``data-v4.1-r1`` ->
       整批 ready（与 T3 同口径，修复不得反向过宽）；
    4. 任一对象冲突即整批 blocked（D2）：冲突经逐对象报告归因
       （blocked 对象 status == "blocked" + 非空 reasons，非冲突对象
       保持 ready），冲突对象在第一位与第二位映射条目各出现至少一次；
    5. 全程零写入 + legacy 源树 / 旧 active pointers 逐字节不变 +
       不就地修改传入映射项。

    四个场景全部复用 T11 双对象 fixture（两条已确认 data 映射 + 三份
    legacy release + 旧数据 / Prompt 活动指针），且两条映射声明的
    target_path 文件均保持空闲，使预检结论只能由 data 正式对象根上
    的同身份扫描路径决定（隔离 target_path 占用分支与 legacy 源分
    支）；两个“空目录”参数（r1 同身份冲突 vs r10 邻居）唯一差异是
    目录名，钉死判定必须按精确身份而非目录内容；fixture 只在 pytest
    tmp_path 下按映射指定的 ``data/releases/...`` 目标布局模拟 data
    正式对象根，不把 data 根写成训练机真实路径（legacy 源树仍为
    workspace/data/releases/ 的合成 fixture）。

    捕获的合理但错误实现：
    - 沿用 Prompt 的 _check_target_conflict（只扫 records/；data 正
      式对象不在 records/ 下）-> 三个 blocked 参数全部误判 ready ->
      status 断言失败（本切片 RED 起点）；
    - 只检查第一条映射条目 -> r1 条目（第二位）的两个冲突参数误判
      ready；只检查末位 / 第二条 -> r2 条目（第一位）参数误判 ready；
    - 只认 target_path 文件或 release.yaml 存在性、不认同身份空目
      录 -> same_identity_dir_without_release_yaml 失败；
    - 只认目录形式不认文件形式（或以 Path.stem 判定同身份 —— 会被
      身份中 v4.1 的点号截断）-> 对应 nonstandard_file 参数失败；
    - 前缀匹配判定同身份（startswith(identity)，data-v4.1-r10 是
      data-v4.1-r1 的字符串前缀）->
      higher_revision_prefix_neighbor_dir_not_conflict 误判 blocked
      （T3/T4 回归重演）；
    - 冲突时自动改号放行 / 覆盖 / 改名 / 清理既有条目 -> status 或
      哨兵字节与全树快照断言失败；
    - blocked 不带 reasons、逐对象归因缺失或把非冲突对象一并
      blocked -> reasons / 对象报告断言失败；
    - 预检即真实转换（创建目标 release、working、release_staging、
      records）-> 全树快照断言失败。

    范围边界（本切片不绑定）：data 身份契约收紧（kind != data、协议
    不匹配）、legacy 源文件缺失、payload 内容 provenance 门、真实转换
    （migrate_data_*）、凭证（D2 格式/位置未裁决，报告不绑定任何凭证
    字段）与中断恢复；target_path 文件本身被占用（release.yaml 已存
    在）的分支已由既有 target_path 占用语义覆盖，本切片不重复。
    """
    active_manifest_bytes = _write_legacy_data_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()

    # fixture 前置事实：映射批顺序为 r2 条目（第一位）-> r1 条目（第
    # 二位）；r1 冲突场景即“冲突对象放在第二位”（钉死只检查首条映射
    # 的实现），r2 冲突场景钉死只检查末位/第二条的实现。
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ]

    # 在 data 正式对象根（映射 target_path 指定的 data/releases/ 布局）
    # 下放置既有条目：dir 场景为空目录（即使缺少 release.yaml），file
    # 场景为哨兵字节文件。
    existing = tmp_path / existing_rel_path
    existing.parent.mkdir(parents=True, exist_ok=True)
    if existing_kind == "dir":
        existing.mkdir()
    else:
        existing.write_bytes(_EXISTING_DATA_ROOT_ENTRY_BYTES)

    # fixture 前置事实（对齐 T11）：三份 legacy release 的 manifest 存
    # 在；既有条目按指定形式存在；两条映射声明的 target_path 文件均
    # 保持空闲（冲突只能经 data 正式对象根上的同身份扫描发现，隔离
    # target_path 占用分支）；旧数据指针绑定活动 release manifest 字
    # 节；旧 Prompt 指针声明 legacy revision_id。
    releases_root = tmp_path / "workspace" / "data" / "releases"
    for source_id in (
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
        UNMAPPED_DATA_SIBLING,
    ):
        manifest_file = releases_root / source_id / "manifest" / "release_manifest.json"
        assert manifest_file.is_file(), (
            f"fixture 前置事实失败：legacy release manifest 缺失 {manifest_file}"
        )
    if existing_kind == "dir":
        assert existing.is_dir()
        assert not any(existing.iterdir()), (
            f"fixture 前置事实失败：dir 场景的既有条目必须为空目录 "
            f"（即使缺少 release.yaml）：{existing_rel_path}"
        )
    else:
        assert existing.read_bytes() == _EXISTING_DATA_ROOT_ENTRY_BYTES
    for item in mapping_items:
        assert not (tmp_path / str(item["target_path"])).exists(), (
            "fixture 前置事实失败：两条映射的 target_path 必须保持空闲，"
            "隔离 target_path 占用分支（冲突只能经 data 正式对象根上的"
            "同身份扫描发现）"
        )
    data_pointer = tmp_path / "finetune" / "active_data_release.json"
    pointer = json.loads(data_pointer.read_text(encoding="utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        active_manifest_bytes
    ).hexdigest(), (
        "fixture 前置事实失败：活动指针 expected_manifest_sha256 必须与"
        "合成活动 release manifest 字节自洽"
    )
    prompt_pointer = (
        tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml"
    )
    assert (
        yaml.safe_load(prompt_pointer.read_bytes())["revision_id"]
        == CONFIRMED_PROMPT_SOURCE_ID
    )

    before = _snapshot_tree(tmp_path)

    precheck_data = _resolve_data_precheck_entry()
    assert precheck_data is not None, (
        "批级数据迁移只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（当前 behavior 未实现）"
    )

    report = precheck_data(tmp_path, mapping_items)

    # 1：整批结论（D2：任一对象冲突 -> 整批 blocked；更高 revision 邻
    #    居是不同身份，不构成冲突 -> 整批 ready）。
    if expected_status == "blocked":
        assert report.status == "blocked", (
            f"data 正式对象根下已存在同身份条目（{existing_rel_path}；映射"
            f"声明的 target_path 文件保持空闲，records/ 亦不存在），预检"
            f"必须在 data 正式对象根上按精确身份检测目标冲突并整批 "
            f"blocked（D2）：实际 status={report.status!r}，"
            f"reasons={report.reasons!r}"
        )
        assert report.reasons, _BLOCKED_REASONS_REQUIRED_MSG
    else:
        assert report.status == "ready", (
            f"已有更高 revision 的同前缀邻居（{existing_rel_path}，"
            f"data-v4.1-r10 与 data-v4.1-r1 是不同身份，字符串前缀不等于"
            f"同身份）不构成目标冲突，整批预检应为 ready：实际 "
            f"status={report.status!r}，reasons={report.reasons!r}"
        )

    # 2：逐对象报告 —— 恰好两条（未映射 sibling 不得进入），冲突经
    #    blocked 对象 + 非空 reasons 可观察，非冲突对象保持 ready。
    object_reports = list(report.object_reports)
    assert len(object_reports) == 2, (
        "批级报告必须包含恰好两条逐对象报告（两条已确认映射）：实际 "
        f"{len(object_reports)} 条"
    )
    reports_by_source = {
        obj_report.source_legacy_id: obj_report for obj_report in object_reports
    }
    assert set(reports_by_source) == {
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
    }, (
        "逐对象报告必须恰覆盖两条已确认映射的 source_legacy_id：实际 "
        f"{sorted(reports_by_source)}"
    )
    for source_id, obj_report in reports_by_source.items():
        if source_id == conflicting_source_id:
            assert obj_report.status == "blocked", (
                f"{source_id} 的逐对象报告应为 blocked（data 正式对象根同"
                f"身份冲突必须按对象归因）：实际 {obj_report.status!r}"
            )
            assert obj_report.reasons, (
                f"{source_id} 的 blocked 对象报告必须携带非空 reasons"
                "（fail-closed 拒因按对象可观察，不得静默 blocked 或只给"
                "批级标志）"
            )
        else:
            assert obj_report.status == "ready", (
                f"{source_id} 的逐对象报告应为 ready（该映射项与 legacy 源"
                f"本身合格，整批 blocked 仅由冲突对象归因）：实际 "
                f"{obj_report.status!r}，reasons={obj_report.reasons!r}"
            )

    # 3：零写入 —— 不创建 records、生命周期目录（working /
    #    release_staging，含 data 根下）或任何目标条目；全树无任何
    #    新增/修改/删除（含报告/缓存文件）。
    for forbidden in (
        "records",
        "working",
        "release_staging",
        "data/working",
        "data/release_staging",
    ):
        assert not (tmp_path / forbidden).exists(), (
            f"批级只读预检不得创建 {forbidden!r}"
        )
    assert _snapshot_tree(tmp_path) == before, (
        "批级只读预检必须零写入：同身份冲突只 blocked，不覆盖、不改名、"
        "不清理既有条目，不创建目标 / 生命周期 / records 条目，不改 "
        "legacy 源树与旧 active pointers"
    )

    # 4：既有条目逐字节保持（file 形式哨兵字节不变；dir 形式仍为空目
    #    录）；旧 active pointers 仍声明 legacy 身份（全树快照已全局钉
    #    定逐字节不变）。
    if existing_kind == "file":
        assert existing.read_bytes() == _EXISTING_DATA_ROOT_ENTRY_BYTES
    else:
        assert existing.is_dir()
        assert not any(existing.iterdir())
    assert (
        json.loads(data_pointer.read_text(encoding="utf-8"))["release_id"]
        == CONFIRMED_DATA_SOURCE_R2
    )
    assert (
        yaml.safe_load(prompt_pointer.read_bytes())["revision_id"]
        == CONFIRMED_PROMPT_SOURCE_ID
    )

    # 5：不就地修改传入映射项（T11 同口径：source_verified /
    #    source_payload_complete 保持 M0 事实分级，不得伪造成 payload
    #    已验证）。
    assert mapping_items == _confirmed_data_mapping_items()


# ---------------------------------------------------------------------------
# T13：data 批级预检已钉扎 legacy manifest provenance 门 —— 指针钉扎的
# 活动 release manifest 文件字节必须独立复算 SHA-256 与指针
# expected_manifest_sha256 比对；指针不可用 / release_id 不符 / 哈希不匹
# 配即整批 blocked；r1（无钉扎）不阻塞、不伪造 verified（先写测试，
# 不改 production）
# ---------------------------------------------------------------------------

# 旧数据活动指针相对根路径（M0 source-inventory pinned_by；真实文件
# finetune/active_data_release.json 声明 release_id / release_dir /
# manifest / expected_contract_hash / expected_manifest_sha256 五字段）。
_DATA_POINTER_REL = Path("finetune") / "active_data_release.json"

# 指针非 JSON 场景的哨兵字节：json.loads 不可解析的损坏指针字节（含
# 可读说明便于失败诊断；预检后必须逐字节原样保持 —— 只读预检不修复）。
_CORRUPT_POINTER_BYTES = (
    b"<corrupted active_data_release.json fixture bytes: not json>"
)


def _manifest_file_of(root: Path, source_id: str) -> Path:
    """legacy data release manifest 文件路径（M0 source-inventory 布局）。"""
    return (
        root
        / "workspace"
        / "data"
        / "releases"
        / source_id
        / "manifest"
        / "release_manifest.json"
    )


def _rewrite_legacy_data_pointer(root: Path, pointer: dict[str, Any]) -> bytes:
    """按 fixture 指针写出口径重写旧数据活动指针，返回写出的字节。

    与 _write_legacy_data_layout 的指针写出口径一致（pretty JSON +
    尾随换行），供 T13 篡改场景构造指针变体；返回字节供调用方在预检
    后断言指针逐字节不变（只读预检不得修复 / 改写指针）。
    """
    pointer_file = root / _DATA_POINTER_REL
    pointer_file.parent.mkdir(parents=True, exist_ok=True)
    pointer_bytes = (
        json.dumps(pointer, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    pointer_file.write_bytes(pointer_bytes)
    return pointer_bytes


@pytest.mark.parametrize(
    ("scenario", "expected_status", "reverse_batch_order"),
    [
        pytest.param(
            "pinned_manifest_bytes_match",
            "ready",
            False,
            id="pinned_manifest_bytes_match_ready",
        ),
        pytest.param(
            "pinned_manifest_bytes_tampered",
            "blocked",
            False,
            id="manifest_bytes_tampered_first_position_batch_blocked",
        ),
        pytest.param(
            "pinned_manifest_bytes_tampered",
            "blocked",
            True,
            id="manifest_bytes_tampered_second_position_batch_blocked",
        ),
        pytest.param(
            "pointer_release_id_points_to_unmapped_sibling",
            "blocked",
            False,
            id="pointer_release_id_unmapped_sibling_batch_blocked",
        ),
        pytest.param(
            "pointer_release_id_points_to_wrong_source",
            "blocked",
            False,
            id="pointer_release_id_wrong_source_batch_blocked",
        ),
        pytest.param(
            "pointer_missing_release_id_field",
            "blocked",
            False,
            id="pointer_missing_release_id_field_batch_blocked",
        ),
        pytest.param(
            "pointer_missing_expected_manifest_sha256_field",
            "blocked",
            False,
            id="pointer_missing_expected_manifest_sha256_batch_blocked",
        ),
        pytest.param(
            "pointer_file_missing",
            "blocked",
            False,
            id="pointer_file_missing_batch_blocked",
        ),
        pytest.param(
            "pointer_non_json",
            "blocked",
            False,
            id="pointer_non_json_batch_blocked",
        ),
    ],
)
def test_data_batch_precheck_pinned_manifest_provenance_gate(
    tmp_path: Path,
    scenario: str,
    expected_status: str,
    reverse_batch_order: bool,
) -> None:
    r"""data 批级只读预检必须校验已钉扎 legacy manifest 的指针 provenance。

    T13 behavior（本切片，主 Agent 选定，先写测试）—— M0
    source-inventory 证据：活动 data release ``v4.1.0-ecb5aeb9657c``
    （映射 -> ``data-v4.1-r2``，target_status ``active``）被旧数据活动
    指针 ``finetune/active_data_release.json`` 钉扎（pin_facts 含
    expected_manifest_sha256）；非活动 release ``v4.1.0-760050fad303``
    （映射 -> ``data-v4.1-r1``，superseded）pinned_by: ~，无钉扎。批级
    只读预检必须：

    1. 对 r2 映射项读取 ``finetune/active_data_release.json``；
    2. 指针 ``release_id`` 精确等于该映射项的 ``source_legacy_id``
       （指向未映射 sibling 或错误源 = 不符）；
    3. 按 manifest 文件字节独立复算
       ``workspace/data/releases/<source_legacy_id>/manifest/
       release_manifest.json`` 的 SHA-256（测试与实现均不 import
       legacy ``pipeline`` / ``finetune`` 代码，哈希独立镜像自算）；
    4. 与指针 ``expected_manifest_sha256`` 比对；
    5. 匹配 -> 保持整批 ready；指针文件缺失、非 JSON、必需字段
       （``release_id`` / ``expected_manifest_sha256``）缺失、
       release_id 不符或哈希不匹配 -> 整批 blocked（fail-closed）+
       非空 reasons + 零写入，门失败按对象归因到被钉扎的 r2 映射项；
    6. r1（无钉扎）不得因无钉扎而阻塞，也不得被伪造 verified/passed
       （映射项 source_verified / source_payload_complete 保持 M0
       事实分级）。

    九个参数全部复用 T11/T12 双对象 fixture（两条已确认 data 映射 +
    三份 legacy release + 旧数据 / Prompt 活动指针），两条映射声明的
    target_path 文件均保持空闲（隔离目标冲突分支，blocked 结论只能
    由指针 provenance 门归因）；篡改只发生在 fixture 布局写好之后：
    - pinned_manifest_bytes_match：fixture 原样（指针与 manifest 字节
      自洽）-> ready 正向对照，钉死门不得反向过宽（指针可用且匹配时
      不得阻塞）；
    - manifest_bytes_tampered（首位 / 末位两个参数）：r2 源 manifest
      文件字节被追加尾随换行（JSON 语义不变：release_id / files 声明
      等其余预检查口径全部仍通过），指针仍持钉扎时的哈希 -> 复算必然
      不匹配 -> blocked；两个参数分别把被钉扎的 r2 映射放在批内第一
      位与第二位，钉死只检查首条 / 末条映射的实现；
    - pointer_release_id_points_to_unmapped_sibling / wrong_source：
      指针改写为钉扎未映射 sibling / r1 的源，且
      expected_manifest_sha256 随被指向 release 的 manifest 字节复算
      自洽 —— 唯一失败只能来自“指针未钉扎 r2 映射项声明的
      source_legacy_id”（钉死“只验证指针指向的 release”的错误实现）；
    - pointer_missing_release_id_field / missing_expected_manifest_
      sha256_field：指针缺单个必需字段（其余字段保留）-> blocked；
    - pointer_file_missing / pointer_non_json：指针文件缺失 / 字节损坏
      非 JSON -> blocked。

    捕获的合理但错误实现：
    - 不读指针、不做 provenance 门（当前 production —— RED 起点）：
      8 个 blocked 参数全部误判 ready -> 整批 status 断言失败；
    - 只做指针内部字段自洽、不按 manifest 文件字节复算（回读 manifest
      声明值自比 / 用 payload 哈希替代 manifest 文件字节哈希）->
      manifest 篡改参数误判 ready；
    - 只验证指针指向的 release（对 sibling / r1 源复算匹配即放行）->
      release_id 不符参数误判 ready；
    - 指针缺失 / 非 JSON / 字段缺失时静默放行或抛未类型化异常 ->
      对应参数 status 断言失败 / 异常传播判失败；
    - 对全部映射项一律要求钉扎（r1 无钉扎被阻塞）或给 r1 编造
      verified/passed（就地改写映射项 source_verified /
      source_payload_complete）-> r1 ready 断言 / 映射项不变断言失败；
    - blocked 时修复指针、重建 manifest、写报告/缓存文件 -> 指针字节
      断言与全树快照断言失败；
    - 只检查首位 / 末位映射项的钉扎门 -> 首位 / 末位篡改参数分别
      误判 ready。

    范围边界（本切片不绑定）：manifest files 声明的 payload 文件哈希
    复算门（manifest files[].sha256 与 payload 字节比对）、
    expected_contract_hash 门、r1 的任何 provenance 验证（r1 无钉扎，
    本切片不给 r1 编造 verified 状态，也不因无钉扎阻塞）、真实转换
    （migrate_data_*）、凭证（D2 格式/位置未裁决）与中断恢复。
    """
    active_manifest_bytes = _write_legacy_data_layout(tmp_path)
    pointer_file = tmp_path / _DATA_POINTER_REL
    r2_manifest_file = _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2)
    r1_manifest_file = _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1)

    # 场景化篡改（fixture 布局写好之后的唯一变量）。
    if scenario == "pinned_manifest_bytes_tampered":
        # 钉扎后 manifest 文件字节被改动（追加尾随空白；JSON 语义不变，
        # release_id / files 存在性等其余预检查口径全部仍通过），指针
        # 仍持钉扎时的 expected_manifest_sha256 -> 复算必然不匹配。
        r2_manifest_file.write_bytes(active_manifest_bytes + b"\n")
    elif scenario == "pointer_release_id_points_to_unmapped_sibling":
        # 指针钉扎未映射 sibling：expected_manifest_sha256 随 sibling 的
        # manifest 字节复算自洽，唯一失败只能是 release_id 不符。
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        pointer["release_id"] = UNMAPPED_DATA_SIBLING
        pointer["release_dir"] = (
            f"workspace/data/releases/{UNMAPPED_DATA_SIBLING}"
        )
        pointer["manifest"] = (
            f"workspace/data/releases/{UNMAPPED_DATA_SIBLING}"
            "/manifest/release_manifest.json"
        )
        pointer["expected_manifest_sha256"] = hashlib.sha256(
            _manifest_file_of(tmp_path, UNMAPPED_DATA_SIBLING).read_bytes()
        ).hexdigest()
        _rewrite_legacy_data_pointer(tmp_path, pointer)
    elif scenario == "pointer_release_id_points_to_wrong_source":
        # 指针钉扎错误源：release_id 指向 r1 的源（M0 pinned_by: ~；映射
        # target_status superseded），哈希随该源 manifest 复算自洽 ——
        # 唯一失败是“指针未钉扎 r2 映射项的 source_legacy_id”。
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        pointer["release_id"] = CONFIRMED_DATA_SOURCE_R1
        pointer["release_dir"] = (
            f"workspace/data/releases/{CONFIRMED_DATA_SOURCE_R1}"
        )
        pointer["manifest"] = (
            f"workspace/data/releases/{CONFIRMED_DATA_SOURCE_R1}"
            "/manifest/release_manifest.json"
        )
        pointer["expected_manifest_sha256"] = hashlib.sha256(
            r1_manifest_file.read_bytes()
        ).hexdigest()
        _rewrite_legacy_data_pointer(tmp_path, pointer)
    elif scenario == "pointer_missing_release_id_field":
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        del pointer["release_id"]
        _rewrite_legacy_data_pointer(tmp_path, pointer)
    elif scenario == "pointer_missing_expected_manifest_sha256_field":
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        del pointer["expected_manifest_sha256"]
        _rewrite_legacy_data_pointer(tmp_path, pointer)
    elif scenario == "pointer_file_missing":
        pointer_file.unlink()
    elif scenario == "pointer_non_json":
        pointer_file.write_bytes(_CORRUPT_POINTER_BYTES)
    elif scenario != "pinned_manifest_bytes_match":
        raise AssertionError(f"未知 T13 场景参数：{scenario!r}")

    mapping_items = _confirmed_data_mapping_items()
    if reverse_batch_order:
        # 把被钉扎的 r2 映射项换到批内第二位（fixture 原序 r2 在第一位）：
        # 预检结论不得依赖映射顺序（篡改对象在第一位 / 第二位各钉一次）。
        mapping_items = list(reversed(mapping_items))

    # fixture 前置事实：三份 legacy release manifest 存在；r1 源 manifest
    # 在任何场景都不被篡改（r1 无钉扎，门不适用）；两条映射的 target_path
    # 保持空闲（隔离目标冲突分支）。
    for source_id in (
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
        UNMAPPED_DATA_SIBLING,
    ):
        manifest_file = _manifest_file_of(tmp_path, source_id)
        assert manifest_file.is_file(), (
            f"fixture 前置事实失败：legacy release manifest 缺失 {manifest_file}"
        )
    r1_manifest_bytes = r1_manifest_file.read_bytes()
    r2_manifest_bytes_on_disk = r2_manifest_file.read_bytes()
    for item in mapping_items:
        assert not (tmp_path / str(item["target_path"])).exists(), (
            "fixture 前置事实失败：两条映射的 target_path 必须保持空闲，"
            "隔离目标冲突分支（blocked 结论只能由指针 provenance 门归因）"
        )

    # fixture 前置事实：按场景钉定指针状态（篡改必须真实生效，且失败只能
    # 由指针 provenance 门归因，不得夹带其他失败来源）。
    if scenario == "pinned_manifest_bytes_match":
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2
        assert pointer["expected_manifest_sha256"] == hashlib.sha256(
            r2_manifest_bytes_on_disk
        ).hexdigest(), (
            "fixture 前置事实失败：活动指针 expected_manifest_sha256 必须与"
            "活动 release manifest 文件字节复算哈希自洽"
        )
    elif scenario == "pinned_manifest_bytes_tampered":
        tampered_manifest = json.loads(r2_manifest_bytes_on_disk.decode("utf-8"))
        assert tampered_manifest["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
            "fixture 前置事实失败：篡改必须保持 JSON 语义不变（追加尾随"
            "空白），使 blocked 只能由 manifest 文件字节哈希不匹配归因"
        )
        assert all(
            (r2_manifest_file.parent.parent / entry["path"]).is_file()
            for entry in tampered_manifest["files"]
        ), "fixture 前置事实失败：篡改后的 manifest 声明 payload 仍必须齐全"
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2
        assert pointer["expected_manifest_sha256"] != hashlib.sha256(
            r2_manifest_bytes_on_disk
        ).hexdigest(), (
            "fixture 前置事实失败：篡改后 manifest 文件字节复算哈希必须与"
            "指针 expected_manifest_sha256 不一致"
        )
    elif scenario in (
        "pointer_release_id_points_to_unmapped_sibling",
        "pointer_release_id_points_to_wrong_source",
    ):
        pointed_source = (
            UNMAPPED_DATA_SIBLING
            if scenario == "pointer_release_id_points_to_unmapped_sibling"
            else CONFIRMED_DATA_SOURCE_R1
        )
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        assert pointer["release_id"] == pointed_source, (
            "fixture 前置事实失败：改写后的指针必须钉扎场景指定的"
            "非 r2 源 release"
        )
        assert pointer["expected_manifest_sha256"] == hashlib.sha256(
            _manifest_file_of(tmp_path, pointed_source).read_bytes()
        ).hexdigest(), (
            "fixture 前置事实失败：改写后的指针必须与被指向 release 的 "
            "manifest 字节自洽（唯一失败只能是 release_id 不符）"
        )
    elif scenario == "pointer_missing_release_id_field":
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        assert "release_id" not in pointer
        assert "expected_manifest_sha256" in pointer
    elif scenario == "pointer_missing_expected_manifest_sha256_field":
        pointer = json.loads(pointer_file.read_text(encoding="utf-8"))
        assert "release_id" in pointer
        assert "expected_manifest_sha256" not in pointer
    elif scenario == "pointer_file_missing":
        assert not pointer_file.exists(), (
            "fixture 前置事实失败：pointer_file_missing 场景必须真实删除"
            "旧数据活动指针文件"
        )
    elif scenario == "pointer_non_json":
        with pytest.raises(json.JSONDecodeError):
            json.loads(pointer_file.read_text(encoding="utf-8"))
        assert pointer_file.read_bytes() == _CORRUPT_POINTER_BYTES
    pointer_bytes_on_disk = (
        pointer_file.read_bytes() if pointer_file.is_file() else None
    )

    before = _snapshot_tree(tmp_path)

    precheck_data = _resolve_data_precheck_entry()
    assert precheck_data is not None, (
        "批级数据迁移只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（当前 behavior 未实现）"
    )

    report = precheck_data(tmp_path, mapping_items)

    # 1：整批结论（fail-closed：指针 provenance 门任一失败 -> 整批
    #    blocked；匹配 -> 保持 ready，不得反向过宽）。
    if expected_status == "blocked":
        assert report.status == "blocked", (
            f"已钉扎 legacy manifest provenance 门失效（scenario={scenario}）："
            "指针钉扎的活动 release manifest 文件字节复算哈希与指针 "
            "expected_manifest_sha256 不匹配，或指针缺失 / 非 JSON / 字段"
            "缺失 / release_id 不符时，批级只读预检必须整批 blocked"
            "（fail-closed，零写入）：实际 "
            f"status={getattr(report, 'status', None)!r}，"
            f"reasons={getattr(report, 'reasons', None)!r}"
        )
        assert report.reasons, _BLOCKED_REASONS_REQUIRED_MSG
    else:
        assert report.status == "ready", (
            "指针钉扎的活动 release manifest 文件字节复算哈希与指针 "
            "expected_manifest_sha256 匹配且两条映射合格时，批级只读预检"
            "应保持整批 ready（门不得反向过宽）：实际 "
            f"status={getattr(report, 'status', None)!r}，"
            f"reasons={getattr(report, 'reasons', None)!r}"
        )

    # 2：逐对象报告 —— 恰好两条；provenance 门失败按对象归因到被钉扎
    #    的 r2 映射项；r1（无钉扎）在全部场景保持 ready：不因无钉扎而
    #    阻塞，也不被伪造 verified/passed。
    object_reports = list(report.object_reports)
    assert len(object_reports) == 2, (
        "批级报告必须包含恰好两条逐对象报告（两条已确认映射）：实际 "
        f"{len(object_reports)} 条"
    )
    reports_by_source = {
        obj_report.source_legacy_id: obj_report for obj_report in object_reports
    }
    assert set(reports_by_source) == {
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
    }, (
        "逐对象报告必须恰覆盖两条已确认映射的 source_legacy_id：实际 "
        f"{sorted(reports_by_source)}"
    )
    r2_report = reports_by_source[CONFIRMED_DATA_SOURCE_R2]
    r1_report = reports_by_source[CONFIRMED_DATA_SOURCE_R1]
    if expected_status == "blocked":
        assert r2_report.status == "blocked", (
            "指针 provenance 门失败必须按对象归因到被钉扎的 r2 映射项"
            f"（{CONFIRMED_DATA_SOURCE_R2} -> {CONFIRMED_DATA_TARGET_R2}，"
            f"target_status active）：实际 status={r2_report.status!r}，"
            f"reasons={getattr(r2_report, 'reasons', None)!r}"
        )
        assert r2_report.reasons, (
            f"{CONFIRMED_DATA_SOURCE_R2} 的 blocked 对象报告必须携带非空 "
            "reasons（fail-closed 拒因按对象可观察，不得静默 blocked）"
        )
    else:
        assert r2_report.status == "ready", (
            f"{CONFIRMED_DATA_SOURCE_R2} 的逐对象报告应为 ready（指针钉扎"
            "的 manifest 文件字节复算匹配）：实际 "
            f"{getattr(r2_report, 'status', None)!r}"
        )
    assert r1_report.status == "ready", (
        f"r1 映射项（{CONFIRMED_DATA_SOURCE_R1}，M0 pinned_by: ~，无钉扎）"
        "自身合格：不得因无钉扎而阻塞，也不得为其伪造 verified/passed："
        f"实际 status={getattr(r1_report, 'status', None)!r}，"
        f"reasons={getattr(r1_report, 'reasons', None)!r}"
    )

    # 3：零写入 —— 不创建 <root>/data、working、release_staging、
    #    records 或任何目标条目；全树无任何新增/修改/删除（含报告/
    #    缓存文件）；blocked 不得修复指针、重建 manifest 或就地规范化
    #    任何文件。
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"批级只读预检不得创建目标根 {forbidden!r}"
        )
    assert _snapshot_tree(tmp_path) == before, (
        "批级只读预检必须零写入：指针 provenance 门失败只 blocked，不"
        "修复指针、不重建 manifest，不创建目标 / 生命周期 / records 条目，"
        "不改 legacy 源树"
    )

    # 4：指针与两份已映射 legacy manifest 逐字节保持场景态（全树快照已
    #    全局钉定；此处显式重读钉死指针与被篡改对象本身不被预检触碰）。
    if pointer_bytes_on_disk is None:
        assert not pointer_file.exists()
    else:
        assert pointer_file.read_bytes() == pointer_bytes_on_disk, (
            "批级只读预检不得修复 / 改写旧数据活动指针（含 blocked 场景）"
        )
    assert r1_manifest_file.read_bytes() == r1_manifest_bytes
    assert r2_manifest_file.read_bytes() == r2_manifest_bytes_on_disk

    # 5：不就地修改传入映射项 —— r1 无钉扎不得被伪造成 verified/passed
    #    （source_verified / source_payload_complete 保持 M0 事实分级，
    #    r1 training_observed / r2 verified_local 均不得升级）。
    expected_items = _confirmed_data_mapping_items()
    if reverse_batch_order:
        expected_items = list(reversed(expected_items))
    assert mapping_items == expected_items, (
        "批级只读预检不得就地改写传入映射项：无钉扎映射项的 "
        "source_verified / source_payload_complete 必须保持 M0 事实分级，"
        "不得伪造成 verified/passed"
    )


# ---------------------------------------------------------------------------
# T14：data 批级预检 legacy manifest payload 文件哈希 provenance 门 ——
# manifest files[] 声明的每个 payload 文件按文件字节复算 SHA-256 与声明
# sha256 比对；文件缺失、哈希字段缺失、哈希不匹配或路径异常即该对象
# blocked 且整批 blocked；匹配保持 ready（manifest 自洽性/内容完整性
# 机制，不等于训练机真实 payload 已验证）（先写测试，不改 production）
# ---------------------------------------------------------------------------

# payload 篡改目标：两份已映射 release 的 manifest files[] 均声明的
# datasets/train/fold_0.json（顶层 "fold": 0 字段）。
_TAMPERED_PAYLOAD_REL = "datasets/train/fold_0.json"
# 等长字节篡改标记/替换：字节改变、长度不变（size_bytes 声明保持自
# 洽）、JSON 仍合法 —— blocked 只能由哈希复算不匹配归因。
_PAYLOAD_TAMPER_MARKER = b'"fold": 0'
_PAYLOAD_TAMPER_REPLACEMENT = b'"fold": 9'
# 缺失哈希字段场景的目标 entry（path / size_bytes 保留，仅删 sha256；
# payload 文件仍在 —— 隔离“文件缺失”分支）。
_MISSING_SHA256_ENTRY_REL = "reports/quality_report.json"
# 路径异常场景的目标 entry：path 被改写为指向另一 release 内同名
# payload 的穿越路径（该文件真实存在 —— 隔离“文件缺失”分支；声明
# sha256 保留原值，复算必然不匹配）。
_PATH_ANOMALY_ENTRY_REL = "metadata/training_candidates.json"


def _payload_file_of(root: Path, source_id: str, relative_path: str) -> Path:
    """legacy release 声明 payload 文件的绝对路径（M0 布局）。"""
    return root / "workspace" / "data" / "releases" / source_id / relative_path


def _assert_payload_declared_hashes_self_consistent(
    root: Path, source_id: str
) -> None:
    """fixture 前置事实：manifest files[] 声明哈希随 payload 实际字节自洽。

    独立镜像门口径复算（不 import legacy pipeline / finetune 代码）：
    逐 entry 读 payload 文件字节，复算 sha256 / size 与声明值比对。使
    “fixture 的 manifest 声明哈希由合成 payload 实际字节独立复算”成为
    可断言的 fixture 事实而非构建代码的口头约定；ready 正向对照不得
    因 fixture 自身错值被误 blocked。
    """
    manifest = json.loads(
        _manifest_file_of(root, source_id).read_text(encoding="utf-8")
    )
    release_dir = root / "workspace" / "data" / "releases" / source_id
    for entry in manifest["files"]:
        payload_file = release_dir / entry["path"]
        assert payload_file.is_file(), (
            f"fixture 前置事实失败：{source_id} 声明的 payload 文件缺失 "
            f"{payload_file}"
        )
        content = payload_file.read_bytes()
        assert len(content) == entry["size_bytes"], (
            f"fixture 前置事实失败：{source_id} 的 {entry['path']} 声明 "
            f"size_bytes={entry['size_bytes']} 与实际 {len(content)} 不符"
        )
        assert hashlib.sha256(content).hexdigest() == entry["sha256"], (
            f"fixture 前置事实失败：{source_id} 的 {entry['path']} 声明 "
            f"sha256 与 payload 实际字节复算值不符"
        )


def _tamper_declared_payload_file(root: Path, source_id: str) -> bytes:
    """对 manifest 声明的 payload 文件做等长字节篡改，返回篡改后字节。

    把 ``datasets/train/fold_0.json`` 顶层 ``"fold": 0`` 改成
    ``"fold": 9``：字节改变、长度不变（size_bytes 声明保持自洽）、
    JSON 仍合法（不引入“文件损坏/无法解析”类旁路失败）。manifest 声明
    值与旧指针不动，blocked 只能由哈希复算不匹配归因。
    """
    payload_file = _payload_file_of(root, source_id, _TAMPERED_PAYLOAD_REL)
    original = payload_file.read_bytes()
    assert _PAYLOAD_TAMPER_MARKER in original, (
        f"fixture 前置事实失败：{source_id} 的 {_TAMPERED_PAYLOAD_REL} 应含"
        f"顶层字段标记 {_PAYLOAD_TAMPER_MARKER!r}"
    )
    tampered = original.replace(
        _PAYLOAD_TAMPER_MARKER, _PAYLOAD_TAMPER_REPLACEMENT, 1
    )
    assert len(tampered) == len(original) and tampered != original, (
        "fixture 前置事实失败：篡改必须改变字节且保持等长"
    )
    payload_file.write_bytes(tampered)
    return tampered


def _rewrite_legacy_release_manifest(
    root: Path, source_id: str, manifest: dict[str, Any]
) -> bytes:
    """按 fixture manifest 写出口径重写 legacy release manifest，返回字节。

    与 _write_legacy_data_release 的 manifest 写出口径一致（pretty JSON
    + 尾随换行），供 T14 manifest 篡改场景构造变体；返回字节供预检后
    断言 manifest 逐字节不变（只读预检不得修复/改写 manifest）。
    """
    manifest_bytes = _fixture_pretty_json_bytes(manifest)
    _manifest_file_of(root, source_id).write_bytes(manifest_bytes)
    return manifest_bytes


def _manifest_files_entry(manifest: dict[str, Any], path: str) -> dict[str, Any]:
    """取 manifest files[] 中指定 path 的 entry（不存在即前置事实失败）。"""
    for entry in manifest["files"]:
        if entry["path"] == path:
            return entry
    raise AssertionError(
        f"fixture 前置事实失败：manifest files[] 中不存在 path={path!r} 的 entry"
    )


@pytest.mark.parametrize(
    ("scenario", "expected_status", "failing_source_id"),
    [
        pytest.param(
            "payload_files_match",
            "ready",
            None,
            id="payload_files_match_ready",
        ),
        pytest.param(
            "r1_payload_bytes_tampered",
            "blocked",
            CONFIRMED_DATA_SOURCE_R1,
            id="r1_payload_hash_tampered_second_position_batch_blocked",
        ),
        pytest.param(
            "r2_payload_bytes_tampered",
            "blocked",
            CONFIRMED_DATA_SOURCE_R2,
            id="r2_payload_hash_tampered_first_position_batch_blocked",
        ),
        pytest.param(
            "r1_manifest_entry_missing_sha256_field",
            "blocked",
            CONFIRMED_DATA_SOURCE_R1,
            id="manifest_entry_missing_sha256_field_second_position_batch_blocked",
        ),
        pytest.param(
            "r1_manifest_entry_path_traversal_anomaly",
            "blocked",
            CONFIRMED_DATA_SOURCE_R1,
            id="manifest_entry_path_anomaly_second_position_batch_blocked",
        ),
    ],
)
def test_data_batch_precheck_payload_file_hash_provenance_gate(
    tmp_path: Path,
    scenario: str,
    expected_status: str,
    failing_source_id: str | None,
) -> None:
    r"""data 批级只读预检必须复算 legacy manifest 声明的 payload 文件哈希。

    T14 behavior（本切片，主 Agent 选定，先写测试）—— 批级只读预检
    对每个映射项（不只对已钉扎活动 release —— T13 是指针钉扎的
    manifest 文件字节门，本切片是 manifest 自洽性/内容完整性门）：
    1. 读取 ``workspace/data/releases/<source_legacy_id>/manifest/
       release_manifest.json``；
    2. 对 manifest ``files[]`` 声明的每个 payload 文件按文件字节独立
       复算 SHA-256（fixture 与实现均不 import legacy ``pipeline`` /
       ``finetune`` 代码，独立镜像自算）；
    3. 与声明 ``sha256`` 比对；
    4. 任一文件缺失、哈希字段缺失、哈希不匹配或路径异常（如指向
       release 目录之外的穿越路径）-> 该对象 blocked，且整批 blocked
       （D2 fail-closed）+ 非空 reasons + 按对象归因；
    5. 匹配 -> 保持整批 ready（门不得反向过宽）；
    6. 该门是 manifest 自洽性/内容完整性机制，不等于训练机真实
       payload 已验证：r1 的无钉扎状态（M0 pinned_by: ~）不得被伪
       造成 verified，映射项 source_verified / source_payload_complete
       保持 M0 事实分级 —— 本测试不绑真实训练机 payload 验证结论；
    7. 零写入：legacy 源树（含被篡改的 fixture 字节）与旧 active
       pointers 逐字节不变，不就地修改传入映射项。

    五个参数全部复用 T11–T13 双对象 fixture（两条已确认 data 映射 +
    三份 legacy release + 旧数据 / Prompt 活动指针），manifest files[]
    声明哈希由合成 payload 实际字节独立复算自洽（前置事实断言钉
    定）；两条映射声明的 target_path 保持空闲、T13 指针门在全部场景
    保持匹配（r2 manifest 文件字节不被任何场景改动 —— 前置事实钉
    定），blocked 结论只能由本切片的 payload 文件哈希门归因。篡改只
    发生在 fixture 布局写好之后：
    - payload_files_match：fixture 原样 -> ready 正向对照（钉死门不
      得反向过宽：声明哈希全部匹配时不得阻塞）；
    - r1_payload_bytes_tampered（失败对象在批内第二位）：r1 源
      ``datasets/train/fold_0.json`` 被等长字节篡改（``"fold": 0`` ->
      ``"fold": 9``；size_bytes 声明保持自洽、JSON 仍合法），manifest
      声明值与指针不动 -> 复算必然不匹配 -> blocked；r1 无钉扎，T13
      指针门不适用 —— 同时钉死门不得只覆盖已钉扎对象；
    - r2_payload_bytes_tampered（失败对象在第一位）：对已钉扎活动
      release r2 的同一 payload 文件做相同篡改 —— manifest 文件字节
      不动，T13 指针门保持匹配，blocked 只能由本门归因；
    - r1_manifest_entry_missing_sha256_field（失败对象在第二位）：
      r1 manifest 的 ``reports/quality_report.json`` entry 缺 sha256
      字段（path / size_bytes 保留、payload 文件仍在）-> 无法复算比
      对即 fail-closed blocked；
    - r1_manifest_entry_path_traversal_anomaly（失败对象在第二位）：
      r1 manifest 的 ``metadata/training_candidates.json`` entry path
      被改写为指向 r2 release 内同名 payload 的穿越路径（该文件真实
      存在 —— 隔离“文件缺失”分支；当前存在性检查对穿越路径放行
      -> 误 ready），声明 sha256 保留原值 -> 复算不匹配/路径异常 ->
      blocked。

    捕获的合理但错误实现：
    - 不复算 payload 哈希、只验存在性（当前 production —— RED 起点）：
      4 个 blocked 参数全部误判 ready -> 整批 status 断言失败；
    - 只复算已钉扎活动 release 的 payload / 只检查首位或末位映射项
      -> 对应位置参数误判 ready；
    - 回读 manifest 声明值自比、用 size_bytes 或 canonical JSON 替代
      文件字节哈希、或把 payload 哈希与 manifest 文件字节哈希（T13
      口径）互相替代 -> 篡改参数误判 ready 或 ready 对照误 blocked；
    - entry 缺 sha256 字段时静默跳过 / 默认放行 -> 缺失字段参数误
      判 ready；
    - 对指向 release 目录之外的穿越路径静默跳过该 entry（不阻塞）
      -> 路径异常参数误判 ready；
    - blocked 时修复 manifest / 重建 payload / 写报告缓存文件 ->
      全树快照断言失败；
    - 就地改写映射项把 r1 无钉扎状态伪造成 verified、或把 ready
      绑定“训练机 payload 已验证”-> 映射项不变断言失败。

    范围边界（本切片不绑定）：真实转换（migrate_data_*）、凭证（D2
    格式/位置未裁决）、恢复、训练机真实 payload 验证结论；声明的
    payload 文件缺失分支由既有存在性检查 blocked（production 已覆
    盖），本切片不单列用例；expected_contract_hash 门不在本切片。
    """
    _write_legacy_data_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()

    r1_manifest_file = _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1)
    r2_manifest_file = _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2)
    data_pointer_file = tmp_path / _DATA_POINTER_REL
    prompt_pointer = (
        tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml"
    )

    # 场景化篡改（fixture 布局写好之后的唯一变量）。
    if scenario == "r1_payload_bytes_tampered":
        _tamper_declared_payload_file(tmp_path, CONFIRMED_DATA_SOURCE_R1)
    elif scenario == "r2_payload_bytes_tampered":
        _tamper_declared_payload_file(tmp_path, CONFIRMED_DATA_SOURCE_R2)
    elif scenario == "r1_manifest_entry_missing_sha256_field":
        manifest = json.loads(r1_manifest_file.read_text(encoding="utf-8"))
        entry = _manifest_files_entry(manifest, _MISSING_SHA256_ENTRY_REL)
        del entry["sha256"]
        _rewrite_legacy_release_manifest(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, manifest
        )
    elif scenario == "r1_manifest_entry_path_traversal_anomaly":
        manifest = json.loads(r1_manifest_file.read_text(encoding="utf-8"))
        entry = _manifest_files_entry(manifest, _PATH_ANOMALY_ENTRY_REL)
        entry["path"] = (
            f"../{CONFIRMED_DATA_SOURCE_R2}/{_PATH_ANOMALY_ENTRY_REL}"
        )
        _rewrite_legacy_release_manifest(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, manifest
        )
    elif scenario != "payload_files_match":
        raise AssertionError(f"未知 T14 场景参数：{scenario!r}")

    r1_manifest_bytes_on_disk = r1_manifest_file.read_bytes()
    r2_manifest_bytes_on_disk = r2_manifest_file.read_bytes()
    pointer_bytes_on_disk = data_pointer_file.read_bytes()

    # fixture 前置事实（对齐 T11/T13）：三份 legacy release manifest
    # 存在；批序 r2 第一位、r1 第二位（r1 场景即失败对象在批内第二
    # 位）；两条映射的 target_path 保持空闲（隔离目标冲突分支）。
    for source_id in (
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
        UNMAPPED_DATA_SIBLING,
    ):
        assert _manifest_file_of(tmp_path, source_id).is_file(), (
            "fixture 前置事实失败：legacy release manifest 缺失 "
            f"{_manifest_file_of(tmp_path, source_id)}"
        )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：批序必须为 r2 第一位、r1 第二位（失败对象在第二位）"
    for item in mapping_items:
        assert not (tmp_path / str(item["target_path"])).exists(), (
            "fixture 前置事实失败：两条映射的 target_path 必须保持空闲，"
            "隔离目标冲突分支（blocked 结论只能由 payload 哈希门归因）"
        )

    # 前置事实：T13 指针 provenance 门在全部场景保持匹配（r2 manifest
    # 文件字节不被任何 T14 场景改动）—— blocked 不得与 T13 门混同。
    pointer = json.loads(pointer_bytes_on_disk.decode("utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        r2_manifest_bytes_on_disk
    ).hexdigest(), (
        "fixture 前置事实失败：活动指针 expected_manifest_sha256 必须与 "
        "r2 manifest 文件字节复算哈希自洽（T13 指针门保持绿，blocked 只"
        "能由本切片 payload 哈希门归因）"
    )

    # 前置事实：未篡改对象的 manifest 声明哈希随 payload 实际字节独立
    # 复算自洽（ready 对象的合法性钉定）。
    for source_id in (CONFIRMED_DATA_SOURCE_R2, CONFIRMED_DATA_SOURCE_R1):
        if failing_source_id is None or source_id != failing_source_id:
            _assert_payload_declared_hashes_self_consistent(tmp_path, source_id)

    # 场景专属前置事实：篡改必须真实生效，且失败只能由 payload 文件哈希
    # 门归因（不得夹带其他失败来源）。
    if scenario in ("r1_payload_bytes_tampered", "r2_payload_bytes_tampered"):
        assert failing_source_id is not None
        tampered_file = _payload_file_of(
            tmp_path, failing_source_id, _TAMPERED_PAYLOAD_REL
        )
        manifest = json.loads(
            _manifest_file_of(tmp_path, failing_source_id).read_text(
                encoding="utf-8"
            )
        )
        entry = _manifest_files_entry(manifest, _TAMPERED_PAYLOAD_REL)
        tampered_bytes = tampered_file.read_bytes()
        original_bytes = tampered_bytes.replace(
            _PAYLOAD_TAMPER_REPLACEMENT, _PAYLOAD_TAMPER_MARKER, 1
        )
        assert hashlib.sha256(original_bytes).hexdigest() == entry["sha256"], (
            "fixture 前置事实失败：篡改前 payload 字节复算哈希必须与 "
            "manifest 声明 sha256 一致（blocked 只能由篡改归因）"
        )
        assert len(tampered_bytes) == entry["size_bytes"], (
            "fixture 前置事实失败：篡改必须等长（size_bytes 声明保持自"
            "洽，blocked 不得由尺寸比对归因）"
        )
        assert hashlib.sha256(tampered_bytes).hexdigest() != entry["sha256"], (
            "fixture 前置事实失败：篡改后 payload 字节复算哈希必须与 "
            "manifest 声明 sha256 不一致"
        )
        assert isinstance(json.loads(tampered_bytes), dict), (
            "fixture 前置事实失败：篡改后 payload 必须仍为合法 JSON"
            "（不引入解析类旁路失败）"
        )
    elif scenario == "r1_manifest_entry_missing_sha256_field":
        manifest = json.loads(r1_manifest_bytes_on_disk.decode("utf-8"))
        entry = _manifest_files_entry(manifest, _MISSING_SHA256_ENTRY_REL)
        assert "sha256" not in entry, (
            "fixture 前置事实失败：该 entry 必须缺 sha256 字段"
        )
        assert isinstance(entry.get("path"), str), (
            "fixture 前置事实失败：缺哈希字段场景必须保留 path 声明，使 "
            "blocked 只能由 sha256 字段缺失归因"
        )
        assert _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, _MISSING_SHA256_ENTRY_REL
        ).is_file(), (
            "fixture 前置事实失败：缺哈希字段场景的 payload 文件必须仍在"
            "（blocked 不得由文件缺失归因）"
        )
    elif scenario == "r1_manifest_entry_path_traversal_anomaly":
        manifest = json.loads(r1_manifest_bytes_on_disk.decode("utf-8"))
        anomalous_path = (
            f"../{CONFIRMED_DATA_SOURCE_R2}/{_PATH_ANOMALY_ENTRY_REL}"
        )
        entry = _manifest_files_entry(manifest, anomalous_path)
        r1_release_dir = (
            tmp_path
            / "workspace"
            / "data"
            / "releases"
            / CONFIRMED_DATA_SOURCE_R1
        )
        resolved = r1_release_dir / anomalous_path
        assert resolved.is_file(), (
            "fixture 前置事实失败：穿越路径指向的文件必须真实存在（隔离"
            "“文件缺失”分支，blocked 只能由路径异常/哈希不匹配归因）"
        )
        assert not resolved.resolve().is_relative_to(
            r1_release_dir.resolve()
        ), (
            "fixture 前置事实失败：异常 path 必须指向 r1 release 目录之外"
        )
        assert hashlib.sha256(resolved.read_bytes()).hexdigest() != entry[
            "sha256"
        ], (
            "fixture 前置事实失败：穿越指向文件复算哈希必须与该 entry 声"
            "明 sha256 不一致"
        )

    before = _snapshot_tree(tmp_path)

    precheck_data = _resolve_data_precheck_entry()
    assert precheck_data is not None, (
        "批级数据迁移只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（当前 behavior 未实现）"
    )

    report = precheck_data(tmp_path, mapping_items)

    # 1：整批结论（fail-closed：任一映射项的 payload 文件哈希门失败 ->
    #    整批 blocked；全部匹配 -> ready，门不得反向过宽）。
    if expected_status == "blocked":
        assert report.status == "blocked", (
            f"legacy manifest payload 文件哈希 provenance 门失效"
            f"（scenario={scenario}）：manifest files[] 声明的 payload 文"
            "件按文件字节复算 SHA-256 与声明 sha256 不匹配 / 字段缺失 / "
            "路径异常时，批级只读预检必须该对象 blocked 且整批 blocked"
            "（fail-closed，零写入）：实际 "
            f"status={getattr(report, 'status', None)!r}，"
            f"reasons={getattr(report, 'reasons', None)!r}"
        )
        assert report.reasons, _BLOCKED_REASONS_REQUIRED_MSG
    else:
        assert report.status == "ready", (
            "两条已确认映射的 manifest files[] 声明哈希全部随 payload 实"
            "际字节复算匹配时，批级只读预检应保持整批 ready（门不得反向"
            "过宽，ready 亦不得被升级为训练机真实 payload 已验证）：实际 "
            f"status={getattr(report, 'status', None)!r}，"
            f"reasons={getattr(report, 'reasons', None)!r}"
        )

    # 2：逐对象报告 —— 恰好两条（未映射 sibling 不得进入）；门失败按
    #    对象归因；非失败对象保持 ready（其 manifest 声明哈希与 payload
    #    实际字节自洽，前置事实已钉定）。
    object_reports = list(report.object_reports)
    assert len(object_reports) == 2, (
        "批级报告必须包含恰好两条逐对象报告（两条已确认映射）：实际 "
        f"{len(object_reports)} 条"
    )
    reports_by_source = {
        obj_report.source_legacy_id: obj_report for obj_report in object_reports
    }
    assert set(reports_by_source) == {
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
    }, (
        "逐对象报告必须恰覆盖两条已确认映射的 source_legacy_id：实际 "
        f"{sorted(reports_by_source)}"
    )
    for source_id, obj_report in reports_by_source.items():
        if failing_source_id is not None and source_id == failing_source_id:
            assert obj_report.status == "blocked", (
                f"payload 文件哈希门失败必须按对象归因到 {source_id}：实际"
                f" status={obj_report.status!r}，"
                f"reasons={getattr(obj_report, 'reasons', None)!r}"
            )
            assert obj_report.reasons, (
                f"{source_id} 的 blocked 对象报告必须携带非空 reasons（fail-"
                "closed 拒因按对象可观察，不得静默 blocked）"
            )
        else:
            assert obj_report.status == "ready", (
                f"{source_id} 的逐对象报告应为 ready（其 manifest 声明哈希"
                "与 payload 实际字节自洽，整批 blocked 仅由失败对象归"
                f"因）：实际 {obj_report.status!r}，"
                f"reasons={getattr(obj_report, 'reasons', None)!r}"
            )

    # 3：零写入 —— 不创建 <root>/data、working、release_staging、
    #    records 或任何目标条目；全树无任何新增/修改/删除（含报告/
    #    缓存文件）；blocked 不得修复 manifest / 重建 payload。
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"批级只读预检不得创建目标根 {forbidden!r}"
        )
    assert _snapshot_tree(tmp_path) == before, (
        "批级只读预检必须零写入：payload 文件哈希门失败只 blocked，不修"
        "复 manifest、不重建 payload，不创建目标 / 生命周期 / records 条"
        "目，不改 legacy 源树与旧 active pointers"
    )

    # 4：legacy 源与旧 active pointers 逐字节保持场景态（全树快照已全局
    #    钉定；显式重读钉死被篡改对象与指针本身不被预检触碰）。
    assert r1_manifest_file.read_bytes() == r1_manifest_bytes_on_disk
    assert r2_manifest_file.read_bytes() == r2_manifest_bytes_on_disk
    assert data_pointer_file.read_bytes() == pointer_bytes_on_disk, (
        "批级只读预检不得修复 / 改写旧数据活动指针（含 blocked 场景）"
    )
    assert (
        yaml.safe_load(prompt_pointer.read_bytes())["revision_id"]
        == CONFIRMED_PROMPT_SOURCE_ID
    )

    # 5：不就地修改传入映射项 —— payload 文件哈希校验是 manifest 自洽
    #    性/内容完整性机制，不等于训练机真实 payload 已验证：r1 的无钉
    #    扎状态（M0 pinned_by: ~）不得被伪造成 verified，r2 的
    #    verified_local / r1 的 training_observed 均不得升级。
    assert mapping_items == _confirmed_data_mapping_items(), (
        "批级只读预检不得就地改写传入映射项：payload 文件哈希校验是 "
        "manifest 自洽性/内容完整性机制，不等于训练机真实 payload 已验"
        "证，source_verified / source_payload_complete 必须保持 M0 事实"
        "分级（r1 无钉扎不伪造 verified）"
    )


# ---------------------------------------------------------------------------
# T14-P3：data 批级预检 payload 路径 symlink loop fail-closed（reviewer 对
# T14 的 P3）—— manifest files[] 声明的 payload 路径解析成环时不得让
# RuntimeError / OSError 穿透预检入口，必须经报告通道该对象 blocked +
# 整批 blocked + 非空 reasons + 零写入；正常哈希匹配对象仍 ready（先写
# 测试，不改 production）
# ---------------------------------------------------------------------------

# symlink loop 落点：复用 T14 的篡改目标 datasets/train/fold_0.json ——
# manifest files[] 已声明该路径，其 sha256 / size_bytes 为原始真实
# payload 字节的声明值（fixture 布局期已定，不依赖读取 loop）。
_SYMLINK_LOOP_PAYLOAD_REL = _TAMPERED_PAYLOAD_REL

# 两节点环的第二链路名（manifest 未声明的 fixture 条目：只用于构成
# fold_0.json -> fold_0.loop_alias.json -> fold_0.json 间接环；预检只按
# 声明 entry 定位 payload，不受该额外条目影响）。
_SYMLINK_LOOP_ALIAS_REL = "datasets/train/fold_0.loop_alias.json"


def _replace_declared_payload_with_symlink_loop(
    root: Path, source_id: str, *, two_node: bool
) -> None:
    """把 manifest 声明的 payload 文件原位替换成 symlink loop（不改 manifest）。

    self-loop：``fold_0.json -> fold_0.json``；two-node loop：
    ``fold_0.json -> fold_0.loop_alias.json -> fold_0.json``（间接环，
    钉死只识别“路径直接自指”的补丁形态）。manifest 不被改写：声明的
    path / size_bytes / sha256 仍为原始真实 payload 的值 —— 声明
    sha256 与 loop 无关，blocked 只能由路径解析异常（fail-closed）归
    因，不得夹带“哈希字段缺失 / 声明值异常”类旁路失败。
    """
    loop_file = _payload_file_of(root, source_id, _SYMLINK_LOOP_PAYLOAD_REL)
    loop_file.unlink()
    if two_node:
        alias_file = _payload_file_of(root, source_id, _SYMLINK_LOOP_ALIAS_REL)
        loop_file.symlink_to(alias_file)
        alias_file.symlink_to(loop_file)
    else:
        loop_file.symlink_to(loop_file)


@pytest.mark.parametrize(
    "loop_shape",
    [
        pytest.param("self_loop", id="self_referential_loop_batch_blocked"),
        pytest.param("two_node_loop", id="two_node_indirect_loop_batch_blocked"),
    ],
)
def test_data_batch_precheck_payload_symlink_loop_fail_closed(
    tmp_path: Path, loop_shape: str
) -> None:
    r"""declared payload 路径是 symlink loop -> blocked 报告，不得穿透异常。

    T14-P3 behavior（本切片，reviewer 对 T14 的 P3，先写测试）—— 批级
    只读预检在解析 manifest files[] 声明的 payload 路径时遇到 symlink
    loop（或其他路径解析异常）必须 fail-closed：
    1. 不抛异常：``RuntimeError`` / ``OSError`` 不得穿透
       precheck_data_migration 入口（当前 production 的
       ``payload_file.resolve()`` 在本机 Python 3.11.14 上把 ELOOP 转
       成 ``RuntimeError: Symlink loop from ...``，而其 ``except
       OSError`` 不捕获 RuntimeError —— 本切片 RED 起点）；
    2. 该对象 blocked + 整批 blocked（D2）+ 非空 reasons + 按对象归
       因（fail-closed 结论必须经 T11/T14 已绑定的报告返回通道给出）；
    3. 零写入：不删除 / 修复 loop，不重建 payload，不创建目标 /
       生命周期 / records 条目，legacy 源树（含 loop fixture）与旧
       active pointers 逐字节不变；
    4. 正常 payload 哈希匹配的非失败对象（r2，批内第一位、已钉扎）仍
       ready —— 门不得反向过宽，也不得把整批一律 blocked 了事。

    fixture：复用 T11–T14 双对象 fixture（两条已确认 data 映射 + 三
    份 legacy release + 旧数据 / Prompt 活动指针）；r1（批内第二位、
    无钉扎）的 declared payload ``datasets/train/fold_0.json`` 被原位
    替换成 symlink loop，manifest 不动 —— 声明 sha256 是原始真实
    payload 字节的哈希（fixture 布局期已定，不依赖读取 loop），故
    blocked 只能由路径解析异常归因；两条映射 target_path 保持空闲
    （隔离目标冲突分支），r2 manifest 声明哈希与 payload 实际字节
    自洽、T13 指针门保持匹配（blocked 不得与其他门混同）。失败对象
    选 r1（无钉扎、第二位）同时钉死“只对已钉扎活动 release 做路径
    异常处理”的错误补丁。两个参数分别用自指环与两节点间接环，钉死
    只识别“路径直接自指”（readlink 与自身比较）的补丁形态。

    捕获的合理但错误实现：
    - 当前 production（RED 起点）：_check_legacy_data_source 对
      ``payload_file.resolve()`` 只 ``except OSError``，Python 3.11.14
      的 resolve() 把 symlink loop 转成 RuntimeError -> 穿透
      precheck_data_migration -> no-leak 守卫判失败（本用例预期 RED
      的 failure signature）；
    - 吞掉解析异常后跳过该 entry / 当作 payload 已验证 -> 误 ready ->
      status 断言失败；
    - 吞掉解析异常后“顺手修复”fixture（删除 loop、重建 payload、改
      写 manifest）-> 全树快照断言失败；
    - 只识别路径直接自指（readlink 与自身比较），不追多链路环 ->
      two_node_loop 参数仍穿透或误判 -> 失败；
    - blocked 不带 reasons / 不按对象归因 / 把 r2 一并 blocked ->
      reasons / 对象报告断言失败；
    - 以未类型化异常替代报告 -> 异常直接传播判失败（守卫点名
      RuntimeError / OSError，其余按原始 traceback 失败 —— 报告通
      道违约不因异常类型不同而豁免）。

    范围边界（本切片不绑定）：路径穿越（``..``）与绝对路径拒绝已由
    T14 钉定；真实转换（migrate_data_*）、凭证（D2 格式/位置未裁
    决）、恢复、训练机真实 payload 验证结论不在本切片。
    """
    _write_legacy_data_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()

    r1_manifest_file = _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1)
    r2_manifest_file = _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2)
    data_pointer_file = tmp_path / _DATA_POINTER_REL
    prompt_pointer = (
        tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml"
    )
    loop_file = _payload_file_of(
        tmp_path, CONFIRMED_DATA_SOURCE_R1, _SYMLINK_LOOP_PAYLOAD_REL
    )

    # 前置事实（替换前）：manifest files[] 已声明该 payload 路径，声明
    # sha256 / size_bytes 随原始真实 payload 字节自洽 —— 声明值在
    # fixture 布局期已定，不依赖读取 loop。
    manifest = json.loads(r1_manifest_file.read_text(encoding="utf-8"))
    entry = _manifest_files_entry(manifest, _SYMLINK_LOOP_PAYLOAD_REL)
    original_payload_bytes = loop_file.read_bytes()
    assert hashlib.sha256(original_payload_bytes).hexdigest() == entry[
        "sha256"
    ], (
        "fixture 前置事实失败：声明的 sha256 必须是原始真实 payload 字节"
        "的哈希（声明值不依赖读取 loop）"
    )
    assert len(original_payload_bytes) == entry["size_bytes"], (
        "fixture 前置事实失败：声明的 size_bytes 必须与原始真实 payload "
        "字节一致"
    )

    # 场景化改写（fixture 布局写好之后的唯一变量）：declared payload
    # 文件原位替换成 symlink loop；manifest 不动。
    _replace_declared_payload_with_symlink_loop(
        tmp_path,
        CONFIRMED_DATA_SOURCE_R1,
        two_node=loop_shape == "two_node_loop",
    )

    # 前置事实：loop 真实生效 —— declared path 是 symlink，且沿链接
    # stat 必然 ELOOP（OS 级路径解析异常事实，不依赖具体 Python 版本
    # 对 resolve() 的异常化口径）。
    assert loop_file.is_symlink(), (
        "fixture 前置事实失败：declared payload 路径必须被替换成 symlink"
    )
    with pytest.raises(OSError) as loop_excinfo:
        loop_file.stat()
    assert loop_excinfo.value.errno == errno.ELOOP, (
        "fixture 前置事实失败：declared payload 路径必须解析成 symlink "
        f"loop（stat ELOOP）：实际 errno={loop_excinfo.value.errno!r}"
    )
    if loop_shape == "two_node_loop":
        assert _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, _SYMLINK_LOOP_ALIAS_REL
        ).is_symlink(), (
            "fixture 前置事实失败：two-node loop 的第二链路必须真实存在"
        )

    # 前置事实：manifest files[] 仍原样声明该 loop 路径（本切片不触碰
    # manifest），entry 与替换前逐字段相等。
    manifest_after = json.loads(r1_manifest_file.read_text(encoding="utf-8"))
    assert _manifest_files_entry(
        manifest_after, _SYMLINK_LOOP_PAYLOAD_REL
    ) == entry, (
        "fixture 前置事实失败：manifest 声明 entry 必须保持原样（声明值"
        "不依赖读取 loop，blocked 只能由路径解析异常归因）"
    )

    # 前置事实（对齐 T11/T13/T14）：批序 r2 第一位、r1 第二位（失败
    # 对象在批内第二位）；两条映射 target_path 空闲（隔离目标冲突分支）。
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：批序必须为 r2 第一位、r1 第二位（失败对象在第二位）"
    for item in mapping_items:
        assert not (tmp_path / str(item["target_path"])).exists(), (
            "fixture 前置事实失败：两条映射的 target_path 必须保持空闲，"
            "隔离目标冲突分支（blocked 只能由 payload 路径解析异常归因）"
        )

    # 前置事实：r2（非失败对象）声明哈希随 payload 实际字节自洽、T13
    # 指针门保持匹配 —— blocked 不得与其他门混同。
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    r1_manifest_bytes_on_disk = r1_manifest_file.read_bytes()
    r2_manifest_bytes_on_disk = r2_manifest_file.read_bytes()
    pointer_bytes_on_disk = data_pointer_file.read_bytes()
    pointer = json.loads(pointer_bytes_on_disk.decode("utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        r2_manifest_bytes_on_disk
    ).hexdigest(), (
        "fixture 前置事实失败：活动指针 expected_manifest_sha256 必须与 "
        "r2 manifest 文件字节复算哈希自洽（T13 指针门保持绿，blocked 只"
        "能由本切片 payload 路径 loop 归因）"
    )

    before = _snapshot_tree(tmp_path)

    precheck_data = _resolve_data_precheck_entry()
    assert precheck_data is not None, (
        "批级数据迁移只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（当前 behavior 未实现）"
    )

    # no-leak 守卫：路径解析异常必须 fail-closed 经报告通道给出，不得
    # 以异常穿透替代（T11/T14 已绑定返回契约）。
    try:
        report = precheck_data(tmp_path, mapping_items)
    except (RuntimeError, OSError) as exc:
        pytest.fail(
            f"payload 路径含 symlink loop（{loop_shape}）时，批级只读预检"
            f"不得抛 {type(exc).__name__}: {exc} —— 路径解析异常必须 "
            "fail-closed 经报告通道返回该对象 blocked + 整批 blocked + "
            "非空 reasons（T11/T14 已绑定返回契约）"
        )

    # 1：整批 blocked + 非空 reasons（fail-closed）。
    assert report.status == "blocked", (
        f"declared payload 路径解析成 symlink loop（{loop_shape}）时，"
        "批级只读预检必须该对象 blocked 且整批 blocked（fail-closed，经"
        "报告通道）：实际 "
        f"status={getattr(report, 'status', None)!r}，"
        f"reasons={getattr(report, 'reasons', None)!r}"
    )
    assert report.reasons, _BLOCKED_REASONS_REQUIRED_MSG

    # 2：逐对象归因 —— 恰好两条；r1（loop 所在对象，批内第二位、无
    #    钉扎）blocked + 非空 reasons；r2（正常 payload 哈希匹配，第一
    #    位、已钉扎）保持 ready —— 门不得反向过宽。
    object_reports = list(report.object_reports)
    assert len(object_reports) == 2, (
        "批级报告必须包含恰好两条逐对象报告（两条已确认映射）：实际 "
        f"{len(object_reports)} 条"
    )
    reports_by_source = {
        obj_report.source_legacy_id: obj_report for obj_report in object_reports
    }
    assert set(reports_by_source) == {
        CONFIRMED_DATA_SOURCE_R1,
        CONFIRMED_DATA_SOURCE_R2,
    }, (
        "逐对象报告必须恰覆盖两条已确认映射的 source_legacy_id：实际 "
        f"{sorted(reports_by_source)}"
    )
    r1_report = reports_by_source[CONFIRMED_DATA_SOURCE_R1]
    r2_report = reports_by_source[CONFIRMED_DATA_SOURCE_R2]
    assert r1_report.status == "blocked", (
        "payload 路径解析成 symlink loop 必须按对象归因到 "
        f"{CONFIRMED_DATA_SOURCE_R1}（批内第二位、无钉扎 —— 门不因对象"
        f"位置或钉扎状态豁免）：实际 status={r1_report.status!r}，"
        f"reasons={getattr(r1_report, 'reasons', None)!r}"
    )
    assert r1_report.reasons, (
        f"{CONFIRMED_DATA_SOURCE_R1} 的 blocked 对象报告必须携带非空 "
        "reasons（fail-closed 拒因按对象可观察，不得静默 blocked）"
    )
    assert r2_report.status == "ready", (
        f"{CONFIRMED_DATA_SOURCE_R2} 的逐对象报告应为 ready（其 manifest "
        "声明哈希与 payload 实际字节自洽 —— 正常 payload 哈希匹配仍 "
        f"ready，门不得反向过宽）：实际 {r2_report.status!r}，"
        f"reasons={getattr(r2_report, 'reasons', None)!r}"
    )

    # 3：零写入 —— 不创建目标 / 生命周期 / records 条目；全树无任何
    #    新增/修改/删除；blocked 不得“顺手修复”loop / manifest / 指针。
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"批级只读预检不得创建目标根 {forbidden!r}"
        )
    assert _snapshot_tree(tmp_path) == before, (
        "批级只读预检必须零写入：payload 路径 symlink loop 只 blocked，"
        "不删除 / 修复 loop，不重建 payload，不创建目标 / 生命周期 / "
        "records 条目，不改 legacy 源树与旧 active pointers"
    )

    # 4：legacy 源（含 loop fixture）与旧 active pointers 逐字节保持场景
    #    态（全树快照已全局钉定；显式重读钉死 loop、manifest 与指针本
    #    身不被预检触碰）。
    assert loop_file.is_symlink(), (
        "批级只读预检不得删除 / 替换 symlink loop fixture"
    )
    assert r1_manifest_file.read_bytes() == r1_manifest_bytes_on_disk
    assert r2_manifest_file.read_bytes() == r2_manifest_bytes_on_disk
    assert data_pointer_file.read_bytes() == pointer_bytes_on_disk, (
        "批级只读预检不得修复 / 改写旧数据活动指针（含 blocked 场景）"
    )
    assert (
        yaml.safe_load(prompt_pointer.read_bytes())["revision_id"]
        == CONFIRMED_PROMPT_SOURCE_ID
    )

    # 5：不就地修改传入映射项（T11/T14 同口径：source_verified /
    #    source_payload_complete 保持 M0 事实分级，不得升级）。
    assert mapping_items == _confirmed_data_mapping_items(), (
        "批级只读预检不得就地改写传入映射项（source_verified / "
        "source_payload_complete 保持 M0 事实分级）"
    )


# ---------------------------------------------------------------------------
# T15：单对象 data 真实转换 —— 单条已确认 r2 映射 -> data-v4.1-r2 active
# 正式 release + migration_receipts/<target_identity>.receipt.yaml committed
# 凭证（先写测试，不改 production；M1a data real conversion 最小切片）
# ---------------------------------------------------------------------------

# T15 receipt 键集（已确认输入：receipt 为 YAML，记录以下八字段；键集
# 精确 —— 不夹带映射项整体 dump 或其他非契约字段，后续切片新增字段
# 须先修订本契约）。
_RECEIPT_FIELDS: tuple[str, ...] = (
    "operation_id",
    "source_legacy_id",
    "target_identity",
    "target_path",
    "source_manifest_sha256",
    "target_release_digest",
    "status",
    "written_at",
)


def _confirmed_r2_mapping_item() -> dict[str, Any]:
    """从双对象映射批中取 r2 单条已确认映射（M0 证据逐字段镜像）。

    T15 只对单条 r2 映射执行真实转换：fixture 仍复用 T11 的双对象布局
    （三份 legacy release + 旧数据 / Prompt 活动指针），但传入的映射批
    只含 r2 条目（v4.1.0-ecb5aeb9657c -> data-v4.1-r2，target_status
    ``active``）；r1 条目不在批内，本切片不转换 r1（superseded 转换与
    replacement 语义留待后续切片）。
    """
    items = [
        item
        for item in _confirmed_data_mapping_items()
        if item["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R2
    ]
    assert len(items) == 1, (
        "fixture 前置事实失败：双对象映射批中 r2 条目必须恰有一条"
    )
    return items[0]


def _resolve_migrate_data_entry() -> Any:
    """惰性解析 T15 批级真实转换入口；模块或入口缺失时返回 None。

    RED Gate 设计（与 _resolve_data_precheck_entry /
    _resolve_prompt_migration_entry 同口径）：migration 模块已存在而
    migrate_data 入口缺失时返回 None，由调用方以显式行为断言钉出
    “单对象 r2 data 真实迁移行为缺失”，不让原始 import 错误 /
    AttributeError 成为 RED。
    """
    spec = importlib.util.find_spec("versioning.migration")
    if spec is None:
        return None
    module = importlib.import_module("versioning.migration")
    return getattr(module, "migrate_data", None)


def _release_content_files(release_dir: Path) -> dict[str, bytes]:
    """枚举 release 目录全部文件：相对 POSIX 路径 -> 字节（含隐藏文件）。"""
    content: dict[str, bytes] = {}
    for path in sorted(
        release_dir.rglob("*"),
        key=lambda path: path.relative_to(release_dir).as_posix(),
    ):
        if path.is_file():
            content[path.relative_to(release_dir).as_posix()] = path.read_bytes()
    return content


def _recompute_target_release_digest(content: Mapping[str, bytes]) -> str:
    r"""按本切片钉定的复算口径从目标 release 内容复算 target_release_digest。

    口径（行为契约的一部分，实现必须按同一口径产出 receipt 的
    target_release_digest）：对目标 release 目录下全部文件按相对 POSIX
    路径升序，拼接 ``<rel>\n<sha256(file bytes)>\n`` 行后取 UTF-8 字节
    的 SHA-256（镜像 versioning/backup.py::_compute_object_sha256 的
    确定性对象摘要风格：逐文件 path / 哈希行拼接再整体哈希，不引入
    冗余 size 段）。receipt 是“目标对象完整写入并验证”的可核实凭证：
    digest 必须绑定目标全部内容（release.yaml + payload）——
    release.yaml 不含逐 payload 文件哈希，只覆盖它无法核实 payload 完
    整性；本测试独立镜像口径复算，使伪造 digest、写 receipt 早于目标
    完整写入/验证（digest 绑定半成品快照）或漏算文件的实现必被捕获。
    """
    lines = "".join(
        f"{relative}\n{hashlib.sha256(data).hexdigest()}\n"
        for relative, data in sorted(content.items())
    )
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def test_migrate_data_single_r2_mapping_creates_active_release_and_committed_receipt(
    tmp_path: Path,
) -> None:
    r"""单条已确认 r2 映射的真实 data 转换：active 正式 release + committed receipt。

    T15 behavior（本切片，主 Agent 选定，先写测试，不改 production）——
    对单条已确认 r2 映射 ``v4.1.0-ecb5aeb9657c`` -> ``data-v4.1-r2``
    （M0 object-mapping 已确认，target_status ``active``；训练机完整
    payload hash 已验证，见 verification.md）执行真实 data 转换时：
    1. 在目标 root 下创建正式 release ``data/releases/data-v4.1-r2/``；
    2. payload 文件集合和逐文件 SHA-256 与 legacy 源一致（目标内容恰为
       release.yaml + legacy manifest files[] 声明的 payload 文件集合，
       不夹带 README / manifest 副本等非本切片最小行为文件）；
    3. release.yaml 可被既有 data release 读取/校验语义
       （versioning.data_release.load_release_metadata）接受，version
       为 ``data-v4.1-r2``，status 为 ``active``，replacement 不存在；
    4. 语义字段来自 legacy manifest 声明值，不重算或伪造；
    5. 在目标 root 的 ``migration_receipts/data-v4.1-r2.receipt.yaml``
       创建 committed receipt，八字段完整；source_manifest_sha256 与
       源 manifest 文件字节哈希一致；target_release_digest 可由目标
       内容复算验证；
    6. legacy 源和旧 active pointers 逐字节不变；
    7. 不写 records、不就地修改映射项、不触发 DVC；目标数据根以可
       注入 root 表示（fixture 只用 pytest tmp_path，不创建训练机
       真实路径）；
    8. 本切片不做 r1 superseded、批级恢复、凭证失配、重跑幂等。

    fixture：复用 T11 双对象 fixture（三份 legacy release + 旧数据 /
    Prompt 活动指针），映射批只传 r2 单条；场景化注入（布局写好之后
    的唯一变量）：r2 legacy manifest 的 counts 与 payload 可复算值
    故意不同（published_candidates 7 vs payload 3 个候选；counts.splits
    各折计数全部异于 payload fold 文件样本数 3 —— counts.splits 键名
    镜像真实 manifest 结构 ``fold_N_train`` / ``fold_N_val``，见
    pipeline/v4_1_training_release.py 写出的 quality counts.splits），
    使行为项 4 的语义溯源可观察：正确实现读 manifest 声明值，从
    payload 重算的实现产出不同值必被捕获。注入只改 counts：files[]
    声明哈希不动（T14 manifest 自洽门保持绿），指针
    expected_manifest_sha256 随注入后 manifest 字节复算更新（T13
    钉扎门保持绿，不因注入被误触发）。

    捕获的合理但错误实现：
    - 入口缺失（当前 production —— RED 起点）：versioning.migration
      无 migrate_data -> 惰性解析返回 None，显式 AssertionError 钉出
      “单对象 r2 data 真实迁移行为缺失”（不让原始 import 错误 /
      AttributeError 成为 RED）；
    - 目标数据根硬编码训练机真实路径（/data/mVllm_2 等）-> 目标
      release / receipt 不出现在注入 root 下 -> 存在性断言失败；
    - 目标 release 漏 payload 文件 / 逐文件字节漂移（规范化、重排、
      重算写出）-> 精确文件集合与逐字节比对失败；
    - 夹带非最小行为文件（README.md / manifest 副本 / .dvc）-> 精确
      文件集合与 DVC 断言失败；
    - release.yaml 语义字段从 payload 重算（sample_count / splits 取
      payload 可复算值）-> 与 manifest 声明值比对失败（行为项 4）；
    - release.yaml 语义字段伪造（protocol / purpose /
      training_allowed / source_batches 偏离 legacy manifest 声明值）
      -> 比对失败；version 误用 legacy 哈希身份、status 偏离映射
      target_status 或 replacement 残留 -> 对应断言失败；
    - release.yaml 不合既有读取/校验语义（缺字段、非法值）->
      load_release_metadata 抛 ReleaseSchemaError -> 本用例判失败；
    - receipt 缺字段 / 键集不精确（夹带映射项 dump）-> 键集断言失败；
    - receipt 哈希伪造：source_manifest_sha256 非 manifest 文件字节
      口径（canonical JSON / 目录哈希 / 声明值自比）、
      target_release_digest 与目标内容复算不符（半途快照 / 只覆盖
      release.yaml / 漏算文件）-> 独立复算比对失败；
    - receipt 早于目标完整写入并验证（digest 绑定半成品）-> 复算
      比对失败；receipt status 非 committed -> status 断言失败；
    - 写 records/ / 生命周期目录（working、release_staging）/ .dvc /
      .gitignore -> 新增顶层条目与存在性断言失败；
    - 转换触碰 legacy 源或旧 active pointers（切换指针到新身份、规范
      化 manifest、改写 payload）-> 逐字节快照断言失败；
    - 夹带批外对象（转换 r1 / 未映射 sibling 或为其写目标条目 /
      receipt）-> data/releases/ 与 migration_receipts/ 精确内容断言
      失败；
    - 就地修改传入映射项 -> 映射项不变断言失败。

    范围边界（本切片不绑定）：r1 superseded 转换与 replacement 语义、
    批级多对象写入顺序、批级返回值契约（migrate_data 返回值本切片不
    绑定）、中断恢复 / 凭证失配拒绝 / 重跑幂等跳过（receipt 只钉创建
    与可核实性，不钉跳过逻辑）、payload 封存去写位、CLI、DVC 接入、
    训练机真实路径与权限准备（Q4 目录尚未创建，真实写入另行授权）。

    Binding（RED 证据绑定，供复跑核对）：
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_single_r2_mapping_creates_active_release_and_committed_receipt``
    - RED failure signature：fixture 构建、场景注入、前置事实断言与
      全树快照真实执行之后，显式 ``AssertionError: 单对象 r2 data
      真实迁移行为缺失：versioning.migration 未提供 migrate_data 入口
      （当前 behavior 未实现）``（原始 ImportError / AttributeError 不得
      成为 RED）；
    - ``pyproject.toml`` sha256（RED 时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：双对象布局 + r2 单条映射批 ----
    _write_legacy_data_layout(tmp_path)
    mapping_items = [_confirmed_r2_mapping_item()]

    # ---- 场景化注入（布局写好之后的唯一变量）：r2 manifest counts 与
    # payload 可复算值故意不同，使“语义字段取 manifest 声明值、不得
    # 从 payload 重算”（行为项 4）可观察。注入只改 counts，不动 files[]
    # 声明哈希（T14 门保持绿）；指针 expected_manifest_sha256 随注入后
    # manifest 字节复算更新（T13 钉扎门保持绿，不因注入被误触发）。
    r2_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r2_manifest["counts"] = {
        "published_candidates": 7,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 5,
            "fold_0_val": 2,
            "fold_1_train": 6,
            "fold_1_val": 4,
            "fold_2_train": 7,
            "fold_2_val": 1,
        },
    }
    r2_manifest_bytes = _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R2, r2_manifest
    )
    pointer = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        r2_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(tmp_path, pointer)

    # ---- fixture 前置事实（对齐 M0 证据 + 注入后自洽）----
    # 注入生效：counts 声明值与 payload 可复算值确实不同（注入有区分
    # 力 —— 重算 payload 的实现必产出不同值）。payload 候选数为 3
    # （fixture range(3)），每折 train/validation fold 文件样本数为 3。
    assert r2_manifest["counts"]["published_candidates"] == 7
    assert set(r2_manifest["counts"]["splits"]) == {
        f"fold_{fold}_{split}"
        for fold in range(3)
        for split in ("train", "val")
    }
    payload_candidates = json.loads(
        _payload_file_of(
            tmp_path,
            CONFIRMED_DATA_SOURCE_R2,
            "metadata/training_candidates.json",
        ).read_text(encoding="utf-8")
    )
    assert len(payload_candidates["candidates"]) == 3, (
        "fixture 前置事实失败：r2 payload 候选数应为 3（注入区分力的"
        "payload 侧事实）"
    )
    assert r2_manifest["counts"]["published_candidates"] != len(
        payload_candidates["candidates"]
    ), "fixture 前置事实失败：注入的声明值必须与 payload 可复算值不同"
    fold_0_train = json.loads(
        _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R2, "datasets/train/fold_0.json"
        ).read_text(encoding="utf-8")
    )
    assert len(fold_0_train["samples"]) == 3, (
        "fixture 前置事实失败：r2 payload fold 文件样本数应为 3"
    )
    assert r2_manifest["counts"]["splits"]["fold_0_train"] != len(
        fold_0_train["samples"]
    )
    # manifest files[] 声明哈希随 payload 实际字节自洽（T14 门保持绿）。
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    # 指针与注入后 manifest 字节自洽（T13 钉扎门保持绿）；指针仍声明
    # 活动 release 的 legacy 身份。
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须与"
        "r2 manifest 文件字节复算哈希自洽"
    )
    # 目标根空闲：data / records 及生命周期目录均不存在。
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )
    # 映射批恰为 r2 单条（M0 已确认条目逐字段镜像；r1 不在批内）。
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2
    ]
    assert mapping_items[0]["candidate_target_identity"] == (
        CONFIRMED_DATA_TARGET_R2
    )
    assert mapping_items[0]["target_status"] == "active"
    assert mapping_items[0]["target_path"] == (
        "data/releases/data-v4.1-r2/release.yaml"
    )

    before = _snapshot_tree(tmp_path)

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "单对象 r2 data 真实迁移行为缺失：versioning.migration 未提供 "
        "migrate_data 入口（当前 behavior 未实现）"
    )

    # 批级入口消费 r2 单条映射批；返回值本切片不绑定。
    migrate_data(tmp_path, mapping_items)

    # 1：目标 root 下创建正式 release data/releases/data-v4.1-r2/。
    release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    assert release_dir.is_dir(), (
        f"真实转换必须在目标 root 下创建正式 release：{release_dir}"
    )
    target_content = _release_content_files(release_dir)

    # 2：payload 文件集合与逐文件 SHA-256 与 legacy 源一致 —— 目标内容
    #    恰为 release.yaml + legacy manifest files[] 声明的 payload 文件
    #    集合（精确集合，不夹带非最小行为文件）；逐文件字节一致（字节
    #    一致即逐文件 SHA-256 一致，不重算、不规范化）。
    declared_payload_paths = sorted(
        entry["path"] for entry in r2_manifest["files"]
    )
    assert set(target_content) == {"release.yaml"} | set(
        declared_payload_paths
    ), (
        "目标 release 内容必须恰为 release.yaml + legacy manifest 声明的 "
        f"payload 文件集合：实际 {sorted(target_content)}"
    )
    legacy_release_root = (
        tmp_path / "workspace" / "data" / "releases" / CONFIRMED_DATA_SOURCE_R2
    )
    for relative in declared_payload_paths:
        legacy_bytes = (legacy_release_root / relative).read_bytes()
        assert target_content[relative] == legacy_bytes, (
            f"目标 payload 文件 {relative} 必须与 legacy 源逐字节一致"
            f"（fixture 语义：源 SHA-256 为 "
            f"{hashlib.sha256(legacy_bytes).hexdigest()}）"
        )

    # 3：release.yaml 可被既有 data release 读取/校验语义接受（解析即
    #    校验：schema、字段值域、version 与目录一致全由
    #    load_release_metadata 把关）；version 为 data-v4.1-r2，status
    #    为 active，replacement 不存在（字段缺席，既有受控通道在
    #    active 下写出的形式）。
    meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    assert meta.version == CONFIRMED_DATA_TARGET_R2, (
        f"release.yaml 的 version 必须为 {CONFIRMED_DATA_TARGET_R2!r}"
        f"（新体系完整身份，不得沿用 legacy 哈希身份）：实际 "
        f"{meta.version!r}"
    )
    assert meta.status is DataStatus.ACTIVE, (
        f"release.yaml 的 status 必须为 active（映射 target_status）：实际 "
        f"{meta.status!r}"
    )
    assert meta.replacement is None, (
        "active release 不得携带 replacement（replacement 仅 superseded "
        "时允许）"
    )
    release_yaml_raw = yaml.safe_load(target_content["release.yaml"])
    assert isinstance(release_yaml_raw, dict)
    assert "replacement" not in release_yaml_raw, (
        "active release 的 release.yaml 不得残留 replacement 键"
    )
    assert release_yaml_raw["status"] == "active"

    # 4：语义字段来自 legacy manifest 声明值，不重算或伪造。
    assert meta.protocol == r2_manifest["contract_version"], (
        "release.yaml 的 protocol 必须取 legacy manifest 的 "
        f"contract_version 声明值 {r2_manifest['contract_version']!r}，"
        f"不得伪造或改写标签：实际 {meta.protocol!r}"
    )
    assert meta.purpose == "development", (
        "legacy 训练 release（manifest status training_ready）的正式映射 "
        f"purpose 必须为 development：实际 {meta.purpose!r}"
    )
    assert meta.training_allowed is True, (
        "development 训练 release 的 training_allowed 必须为 true，不得"
        "伪造成不可训练语义"
    )
    assert meta.sample_count == (
        r2_manifest["counts"]["published_candidates"]
    ), (
        "sample_count 必须取 legacy manifest counts.published_candidates "
        f"声明值 {r2_manifest['counts']['published_candidates']}，不得从 "
        "payload 重算或伪造（fixture 注入的声明值与 payload 可复算值"
        "故意不同）"
    )
    expected_splits = {
        f"fold_{fold}": {
            "train": r2_manifest["counts"]["splits"][f"fold_{fold}_train"],
            "validation": r2_manifest["counts"]["splits"][f"fold_{fold}_val"],
        }
        for fold in range(3)
    }
    assert dict(meta.splits) == expected_splits, (
        "splits 必须取 legacy manifest counts.splits 声明值"
        "（fold_N_train -> train、fold_N_val -> validation，fold 名取其"
        " fold_N 前缀），不得从 payload fold 文件重算或伪造（fixture 注入"
        f"的声明值与 payload 可复算值故意不同）：实际 {dict(meta.splits)!r}"
    )
    expected_source_batches = {
        r2_manifest["source_review_batch_id"],
        r2_manifest["source_queue_id"],
        r2_manifest["source_media_id"],
    }
    assert set(meta.source_batches) == expected_source_batches, (
        "source_batches 必须记录 legacy manifest 声明的原始批次标识"
        f"（{sorted(expected_source_batches)}），不回填伪造：实际 "
        f"{sorted(meta.source_batches)}"
    )

    # 5：目标 root 的 migration_receipts/ 下创建 committed receipt，字段
    #    完整，两处哈希均可由测试独立复算核实。
    receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    assert receipt_file.is_file(), (
        "真实转换必须在目标对象完整写入并验证后创建 committed receipt："
        f"{receipt_file}"
    )
    receipt = yaml.safe_load(receipt_file.read_text(encoding="utf-8"))
    assert isinstance(receipt, dict), (
        "migration receipt 必须是 YAML 顶层映射"
    )
    assert set(receipt) == set(_RECEIPT_FIELDS), (
        "receipt 键集必须恰为八字段契约（operation_id / source_legacy_id"
        " / target_identity / target_path / source_manifest_sha256 / "
        "target_release_digest / status / written_at）：实际 "
        f"{sorted(receipt)}"
    )
    assert isinstance(receipt["operation_id"], str) and receipt["operation_id"], (
        "receipt.operation_id 必须是非空字符串（本切片不绑定其格式；可"
        "核实凭证绑定与重跑跳过逻辑留待后续切片）"
    )
    assert receipt["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R2, (
        f"receipt.source_legacy_id 必须为 {CONFIRMED_DATA_SOURCE_R2!r}："
        f"实际 {receipt['source_legacy_id']!r}"
    )
    assert receipt["target_identity"] == CONFIRMED_DATA_TARGET_R2, (
        f"receipt.target_identity 必须为 {CONFIRMED_DATA_TARGET_R2!r}："
        f"实际 {receipt['target_identity']!r}"
    )
    assert receipt["target_path"] == mapping_items[0]["target_path"], (
        "receipt.target_path 必须与映射项声明的 target_path 一致：实际 "
        f"{receipt['target_path']!r}"
    )
    assert receipt["source_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "receipt.source_manifest_sha256 必须与 legacy 源 manifest 文件"
        "字节哈希一致（文件字节口径，非 canonical JSON / 目录哈希 / "
        "声明值自比）"
    )
    assert receipt["target_release_digest"] == _recompute_target_release_digest(
        target_content
    ), (
        "receipt.target_release_digest 必须能由目标 release 内容按本切片"
        "钉定口径复算验证（目标全部文件按相对 POSIX 路径升序拼接"
        " <rel>/<sha256> 行后的整体 SHA-256）；digest 绑定半成品快照、只"
        "覆盖 release.yaml 或漏算文件的实现必被捕获"
    )
    assert receipt["status"] == "committed", (
        f"receipt.status 必须为 committed：实际 {receipt['status']!r}"
    )
    assert isinstance(receipt["written_at"], str) and receipt["written_at"], (
        "receipt.written_at 必须是非空字符串（本切片不绑定精确值与格式）"
    )

    # 6：legacy 源和旧 active pointers 逐字节不变（全树快照按 legacy 源
    #    树、旧数据指针与 pipeline 子树精确比对）；旧指针仍声明 legacy
    #    身份，不得被切换到新身份。
    after = _snapshot_tree(tmp_path)
    for subtree in ("workspace/", "finetune/", "pipeline/"):
        before_subtree = {
            key: value for key, value in before.items() if key.startswith(subtree)
        }
        after_subtree = {
            key: value for key, value in after.items() if key.startswith(subtree)
        }
        assert after_subtree == before_subtree, (
            f"真实转换不得改动 {subtree} 子树（legacy 源与旧 active "
            "pointers 逐字节不变；不改写、不规范化、不去写位）"
        )
    data_pointer_after = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_after["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "旧数据活动指针必须仍声明 legacy 身份，不得被切换到新身份"
    )
    prompt_pointer_after = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_after["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "旧 Prompt 活动指针必须仍声明 legacy revision_id"
    )

    # 7：不写 records、不触发 DVC、不夹带批外对象；目标数据根以可注入
    #    root 表示 —— 新增顶层条目恰为 data/ 与 migration_receipts/
    #    （硬编码训练机真实路径 /data/mVllm_2 的实现不会在注入 root 下
    #    留下目标条目，已被上方存在性断言捕获；本用例不触碰真实 /data）。
    before_top_levels = {key.split("/", 1)[0] for key in before}
    after_top_levels = {key.split("/", 1)[0] for key in after}
    assert after_top_levels - before_top_levels == {
        "data",
        "migration_receipts",
    }, (
        "真实转换只允许新增目标 data 根与 receipt 目录（目标数据根必须"
        f"以可注入 root 表示）：实际新增 "
        f"{sorted(after_top_levels - before_top_levels)}"
    )
    for forbidden in (
        "records",
        "working",
        "release_staging",
        "data/working",
        "data/release_staging",
    ):
        assert not (tmp_path / forbidden).exists(), (
            f"真实转换不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in after), (
        "真实转换不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    assert ".gitignore" not in after_top_levels, (
        "真实转换不得创建或改写 .gitignore（DVC 接入不在本切片）"
    )
    # data/releases/ 恰含批内对象；migration_receipts/ 恰含批内 receipt
    # （批只有 r2 单条，不夹带 r1 或未映射 sibling 的目标条目/凭证）。
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R2
    ], (
        "data/releases/ 必须恰含批内对象 data-v4.1-r2（批只传 r2 单条"
        "映射，不得夹带 r1 / 未映射 sibling）"
    )
    receipts_root = tmp_path / "migration_receipts"
    assert [
        entry.name for entry in sorted(receipts_root.iterdir())
    ] == [f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"], (
        "migration_receipts/ 必须恰含批内对象 receipt（不得夹带批外"
        "凭证）"
    )
    # 不就地修改传入映射项（source_verified / source_payload_complete
    # 保持 M0 事实分级，不得升级）。
    assert mapping_items == [_confirmed_r2_mapping_item()], (
        "真实转换不得就地改写传入映射项（M0 事实分级保持不变）"
    )


# ---------------------------------------------------------------------------
# T15-P2-1（reviewer 对 T15 的 P2-1）：声明 state: sealed 的迁移目标必须
# 真实封存 —— assert_payload_sealed 通过 + release 根 / payload 去写位 +
# release.yaml 受控更新通道保留 + receipt 不随封存去写位（先写测试，
# 不改 production）
# ---------------------------------------------------------------------------


def _snapshot_modes(root: Path) -> dict[str, int]:
    """相对 POSIX 路径 -> 权限位快照（根自身记为 "."），供前后比对。

    _snapshot_tree 只覆盖字节不覆盖权限位；本切片的“不修改 legacy”
    还含“不被迁移封存顺手去写位”，故单独快照 st_mode 供前后比对。
    """
    modes: dict[str, int] = {".": root.stat().st_mode}
    for path in sorted(root.rglob("*")):
        modes[path.relative_to(root).as_posix()] = path.stat().st_mode
    return modes


def test_migrate_data_target_release_declaring_sealed_state_is_actually_sealed(
    tmp_path: Path,
) -> None:
    """state: sealed 的迁移目标必须真实封存（P2-1，先写测试，不改 production）。

    T15-P2-1 behavior（reviewer 对 T15 的 P2-1：目标 release.yaml 写
    ``state: sealed``，但 payload 目录与文件仍可写，既有
    ``assert_payload_sealed`` 会拒绝 —— 声明与事实不符）——
    ``migrate_data`` 创建 ``state: sealed`` 的正式 data release 后，
    目标必须满足既有封存语义（versioning/data_release.py::
    seal_release 产出的位级事实与既有只读门 ``assert_payload_sealed``，
    不另立新口径）：
    1. 既有权威只读门 ``assert_payload_sealed(data/releases/
       data-v4.1-r2)`` 通过（不得抛 ImmutableReleaseError）；
    2. release 根目录去全部写位（0o222；既有约定：防根下新增条目）；
    3. payload 文件与目录（release.yaml / README.md / authorization
       既有豁免之外的全部条目）去全部写位；
    4. release.yaml 保留创建时写位（sealed 后唯一受控修改通道
       ``update_release_status`` 重写 status/replacement 依赖它；
       与同环境新建探针文件比对全部写位，不硬编码具体权限值）；
    5. T15 内容/receipt 契约不回归：目标内容恰为 release.yaml +
       legacy manifest files[] 声明 payload 集合且逐字节一致；
       release.yaml 经既有 load_release_metadata 读取/校验语义接受
       （version 为 data-v4.1-r2、status 为 active、语义字段取
       manifest 声明值）；committed receipt 八字段完整且两处哈希
       可由本测试独立复算核实；
    6. receipt 是 release 外部的迁移控制文件：文件与所在
       migration_receipts/ 目录（以及 data/releases/ 对象根层）都
       不得随封存去写位 —— 封存范围是 release 目录子树，不是迁移
       控制面；receipt 已写入（is_file + committed 契约）；
    7. legacy 源树与旧 active pointers 逐字节不变，且 legacy 源
       权限位不变（封存不得顺手波及 workspace/）；旧指针仍声明
       legacy 身份；
    8. 不触发 DVC、不写 records/ 与生命周期目录；不就地修改映射项。

    fixture：复用 T15 fixture（_write_legacy_data_layout 双对象 legacy
    布局 + r2 单条映射批 + counts 场景注入 + 指针 manifest 哈希随
    注入重写）—— 同一事实基线使封存断言与 T15 的内容/receipt 断言在
    同一对象上叠加：封存实现不得漂移 T15 已钉定的内容契约。

    捕获的合理但错误实现：
    - 当前 production（RED 起点）：migrate_data 只 mkdir + 逐字节复制
      payload + 写 release.yaml，从不去写位 -> assert_payload_sealed
      抛 ImmutableReleaseError（release 根目录仍可写），本用例转成
      显式行为 AssertionError（ImmutableReleaseError 作为 cause 链
      保留，不得直接充当 RED 结论）；
    - 只写 state: sealed 字段、不做任何 chmod（同上，位级断言逐条
      失败）；
    - 只去 payload 文件写位、不去目录写位（datasets/ 等目录仍可
      新增条目）/ 只去子目录、不去 release 根（根下可新增条目）->
      位级枚举断言失败；
    - 过度封存：release.yaml 一并去写位（破坏 sealed 后唯一受控修改
      通道）、migration_receipts/ 与 receipt、data/releases/ 一并去
      写位（破坏 release 外部迁移控制面与后续对象写入）-> 探针写位
      比对失败；
    - 封存波及 legacy：workspace/ 权限位漂移 -> legacy 权限位快照比对
      失败；
    - 封存改变内容契约（封存时规范化/重写 payload、补 README.md /
      manifest 副本等额外文件）-> T15 精确内容集合 + 逐字节 + receipt
      digest 复算断言失败。

    范围边界（本切片不绑定）：r1 superseded 转换与 replacement 语义、
    批级多对象写入顺序、批级返回值契约、批级恢复、凭证失配拒绝、
    重跑幂等跳过、update_release_status 的行为级受控修改（只钉
    release.yaml 写位保留）、CLI、DVC 接入、训练机真实路径与权限
    准备。若 production 已具备封存语义，本切片允许 Unexpected PASS
    （转为封存回归钉），不得为此制造无意义 production 修改。

    Binding（RED 证据绑定，供复跑核对）：
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_target_release_declaring_sealed_state_is_actually_sealed``
    - RED failure signature：fixture 构建、场景注入、前置事实断言与
      全树/权限位快照真实执行、migrate_data 调用成功之后，显式
      ``AssertionError: 声明 state: sealed 的迁移目标必须真实封存：
      assert_payload_sealed(data-v4.1-r2) 不得拒绝
      （ImmutableReleaseError: release 根目录仍可写: data-v4.1-r2）``
      （cause 链保留 ImmutableReleaseError；原始异常穿透 / import
      错误 / AttributeError 不得成为 RED）；
    - ``pyproject.toml`` sha256（RED 时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖
      该文件）。
    """
    # ---- fixture：复用 T15 双对象布局 + r2 单条映射批 + counts 场景注入 ----
    _write_legacy_data_layout(tmp_path)
    mapping_items = [_confirmed_r2_mapping_item()]

    r2_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r2_manifest["counts"] = {
        "published_candidates": 7,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 5,
            "fold_0_val": 2,
            "fold_1_train": 6,
            "fold_1_val": 4,
            "fold_2_train": 7,
            "fold_2_val": 1,
        },
    }
    r2_manifest_bytes = _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R2, r2_manifest
    )
    pointer = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        r2_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(tmp_path, pointer)

    # ---- fixture 前置事实（T15 同口径：注入自洽 + 目标根空闲）----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2
    ], "fixture 前置事实失败：映射批必须恰为 r2 单条"

    before = _snapshot_tree(tmp_path)
    legacy_modes_before = _snapshot_modes(tmp_path / "workspace")

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "单对象 r2 data 真实迁移行为缺失：versioning.migration 未提供 "
        "migrate_data 入口（当前 behavior 未实现）"
    )
    migrate_data(tmp_path, mapping_items)

    release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    assert release_dir.is_dir(), (
        f"真实转换必须在目标 root 下创建正式 release：{release_dir}"
    )

    # 1：既有权威只读门不得拒绝（封存语义的既有判定口径，不另立新门）。
    try:
        assert_payload_sealed(release_dir)
    except ImmutableReleaseError as exc:
        raise AssertionError(
            "声明 state: sealed 的迁移目标必须真实封存："
            f"assert_payload_sealed({release_dir.name}) 不得拒绝"
            f"（ImmutableReleaseError: {exc}）"
        ) from exc

    # 2/3：位级断言 —— release 根与全部 payload 文件/目录去全部写位；
    #      豁免口径镜像既有门（release.yaml / README.md /
    #      authorization；本目标无 README.md / authorization，豁免实际
    #      只剩 release.yaml）。
    assert not (release_dir.stat().st_mode & 0o222), (
        "迁移目标 release 根目录必须去全部写位（既有封存约定：防根下"
        "新增条目），当前仍可写"
    )
    for path in sorted(release_dir.rglob("*")):
        relative = path.relative_to(release_dir)
        if relative.parts[0] in ("release.yaml", "README.md", "authorization"):
            continue
        assert not (path.stat().st_mode & 0o222), (
            "迁移目标 payload 条目必须去全部写位（既有封存语义，豁免仅"
            f"限 release.yaml / README.md / authorization）：仍可写 "
            f"{relative.as_posix()}"
        )

    # 5（内容契约不回归）：目标内容恰为 release.yaml + manifest 声明
    #    payload 集合，逐字节一致（封存不得夹带 README.md / manifest
    #    副本等额外文件，也不得改写字节）。
    target_content = _release_content_files(release_dir)
    declared_payload_paths = sorted(
        entry["path"] for entry in r2_manifest["files"]
    )
    assert set(target_content) == {"release.yaml"} | set(
        declared_payload_paths
    ), (
        "封存后的目标 release 内容必须恰为 release.yaml + legacy "
        "manifest 声明的 payload 文件集合（T15 内容契约不回归）：实际 "
        f"{sorted(target_content)}"
    )
    legacy_release_root = (
        tmp_path / "workspace" / "data" / "releases" / CONFIRMED_DATA_SOURCE_R2
    )
    for relative in declared_payload_paths:
        assert target_content[relative] == (
            legacy_release_root / relative
        ).read_bytes(), (
            "封存不得改写目标 payload 字节（T15 逐字节契约不回归）："
            f"{relative}"
        )

    # release.yaml 声明 state: sealed（P2-1 的声明侧前提）且经既有读取/
    # 校验语义接受；version/status/语义字段保持 T15 口径（取 manifest
    # 声明值，不重算、不伪造 —— fixture 注入的 counts 与 payload 可
    # 复算值故意不同，封存实现若借机重算必被捕获）。
    meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    assert meta.state == "sealed", (
        "迁移目标 release.yaml 必须声明 state: sealed（P2-1 声明侧前提）"
        f"：实际 {meta.state!r}"
    )
    assert meta.version == CONFIRMED_DATA_TARGET_R2
    assert meta.status is DataStatus.ACTIVE, (
        f"release.yaml 的 status 必须为 active：实际 {meta.status!r}"
    )
    assert meta.replacement is None
    assert meta.protocol == r2_manifest["contract_version"]
    assert meta.purpose == "development"
    assert meta.training_allowed is True
    assert meta.sample_count == (
        r2_manifest["counts"]["published_candidates"]
    ), (
        "sample_count 必须保持取 manifest 声明值（封存不得借机重算）："
        f"实际 {meta.sample_count!r}"
    )
    assert dict(meta.splits) == {
        f"fold_{fold}": {
            "train": r2_manifest["counts"]["splits"][f"fold_{fold}_train"],
            "validation": r2_manifest["counts"]["splits"][f"fold_{fold}_val"],
        }
        for fold in range(3)
    }, (
        "splits 必须保持取 manifest 声明值（封存不得借机重算）：实际 "
        f"{dict(meta.splits)!r}"
    )
    assert set(meta.source_batches) == {
        r2_manifest["source_review_batch_id"],
        r2_manifest["source_queue_id"],
        r2_manifest["source_media_id"],
    }

    # 5（receipt 契约不回归）：committed receipt 八字段完整，两处哈希
    #    可独立复算核实。
    receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    assert receipt_file.is_file(), (
        "真实转换必须在目标对象完整写入并验证后创建 committed receipt"
        f"（封存不得改变 receipt 创建契约）：{receipt_file}"
    )
    receipt = yaml.safe_load(receipt_file.read_text(encoding="utf-8"))
    assert isinstance(receipt, dict), (
        "migration receipt 必须是 YAML 顶层映射"
    )
    assert set(receipt) == set(_RECEIPT_FIELDS), (
        "receipt 键集必须恰为八字段契约（封存不得改变键集）：实际 "
        f"{sorted(receipt)}"
    )
    assert receipt["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R2
    assert receipt["target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert receipt["target_path"] == mapping_items[0]["target_path"]
    assert receipt["status"] == "committed", (
        f"receipt.status 必须为 committed：实际 {receipt['status']!r}"
    )
    assert isinstance(receipt["operation_id"], str) and receipt["operation_id"]
    assert isinstance(receipt["written_at"], str) and receipt["written_at"]
    assert receipt["source_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "receipt.source_manifest_sha256 必须与 legacy 源 manifest 文件"
        "字节哈希一致"
    )
    assert receipt["target_release_digest"] == _recompute_target_release_digest(
        target_content
    ), (
        "receipt.target_release_digest 必须能由封存后的目标内容按钉定"
        "口径复算验证（封存不得改变内容或 digest 口径）"
    )

    # 7：legacy 源与旧 pointers 逐字节不变 + legacy 权限位不变（封存
    #    不得顺手波及 workspace/）；旧指针仍声明 legacy 身份。
    after = _snapshot_tree(tmp_path)
    for subtree in ("workspace/", "finetune/", "pipeline/"):
        before_subtree = {
            key: value for key, value in before.items() if key.startswith(subtree)
        }
        after_subtree = {
            key: value for key, value in after.items() if key.startswith(subtree)
        }
        assert after_subtree == before_subtree, (
            f"封存不得改动 {subtree} 子树（legacy 源与旧 active pointers "
            "逐字节不变；不改写、不规范化、不去写位）"
        )
    assert _snapshot_modes(tmp_path / "workspace") == legacy_modes_before, (
        "封存不得波及 legacy 源树权限位（workspace/ 被去写位同样是"
        "修改 legacy）"
    )
    data_pointer_after = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_after["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "旧数据活动指针必须仍声明 legacy 身份，不得被切换到新身份"
    )
    prompt_pointer_after = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_after["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "旧 Prompt 活动指针必须仍声明 legacy revision_id"
    )

    # 8：不触发 DVC、不写 records/ / 生命周期目录；新增顶层恰为 data/
    #    与 migration_receipts/；data/releases/ 与 migration_receipts/
    #    恰含批内对象；不就地修改映射项。
    before_top_levels = {key.split("/", 1)[0] for key in before}
    after_top_levels = {key.split("/", 1)[0] for key in after}
    assert after_top_levels - before_top_levels == {
        "data",
        "migration_receipts",
    }, (
        "真实转换只允许新增目标 data 根与 receipt 目录：实际新增 "
        f"{sorted(after_top_levels - before_top_levels)}"
    )
    for forbidden in (
        "records",
        "working",
        "release_staging",
        "data/working",
        "data/release_staging",
    ):
        assert not (tmp_path / forbidden).exists(), (
            f"真实转换不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in after), (
        "真实转换不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    assert ".gitignore" not in after_top_levels
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R2
    ], "data/releases/ 必须恰含批内对象 data-v4.1-r2"
    receipts_root = tmp_path / "migration_receipts"
    assert [
        entry.name for entry in sorted(receipts_root.iterdir())
    ] == [f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"], (
        "migration_receipts/ 必须恰含批内对象 receipt"
    )
    assert mapping_items == [_confirmed_r2_mapping_item()], (
        "真实转换不得就地改写传入映射项（M0 事实分级保持不变）"
    )

    # 4/6：封存边界写位比对（全部写位 0o222，与同环境新建探针比对，
    #      口径随当前 umask，不硬编码具体权限值）：release.yaml 是既有
    #      封存语义的受控更新通道，必须保留创建时写位；receipt 文件与
    #      migration_receipts/、data/releases/ 目录是 release 外部的
    #      迁移控制面（后续凭证切片读取、后续对象写入依赖写位），
    #      不得随封存去写位。探针在快照断言之后创建，不污染上面的
    #      全树/顶层比对。
    probe_file = tmp_path / ".write_mode_probe"
    probe_file.write_bytes(b"")
    probe_dir = tmp_path / ".write_mode_probe_dir"
    probe_dir.mkdir()
    release_yaml = release_dir / "release.yaml"
    assert (
        release_yaml.stat().st_mode & 0o222
    ) == (probe_file.stat().st_mode & 0o222), (
        "release.yaml 必须保留创建时写位（sealed 后唯一受控修改通道 "
        "update_release_status 重写 status/replacement 依赖它；封存"
        "不得过度到受控通道）"
    )
    assert (
        receipt_file.stat().st_mode & 0o222
    ) == (probe_file.stat().st_mode & 0o222), (
        "receipt 是 release 外部的迁移控制文件：不得随封存去写位"
        "（后续凭证失配拒绝 / 重跑幂等切片仍需读/更新迁移控制文件）"
    )
    assert (
        receipts_root.stat().st_mode & 0o222
    ) == (probe_dir.stat().st_mode & 0o222), (
        "migration_receipts/ 是 release 外部的迁移控制目录：不得随封存"
        "去写位（后续对象的 receipt 写入依赖目录写位）"
    )
    assert (
        releases_root.stat().st_mode & 0o222
    ) == (probe_dir.stat().st_mode & 0o222), (
        "data/releases/ 对象根层不得随封存去写位（封存范围是 release "
        "目录子树；后续对象（r1 等）的正式 release 写入依赖该层写位）"
    )


# ---------------------------------------------------------------------------
# T15-P2-2（reviewer 对 T15 的 P2-2）：migrate_data 在原始 precheck 通过
# 后、写入前重新读取 manifest 时必须重新校验 files[] 路径安全与 payload
# 存在性 —— precheck 与写入之间的 TOCTOU 窗口不得成为无校验写入通道
# （先写测试，不改 production）
# ---------------------------------------------------------------------------

# 场景 1 的穿越声明路径：对 legacy 源根相对（读取侧）解析回本 release
# 的同一 payload 文件（文件存在、字节与 entry 声明 sha256 一致 —— 失败
# 只能由路径安全归因，隔离文件缺失/哈希不匹配分支）；对目标 release
# 根相对（写入侧）越出目标 release 目录（../<源身份>/... 落到
# data/releases/<源身份>/ 下）—— 写目标外路径可观察。
_P2_2_TRAVERSED_PATH = f"../{CONFIRMED_DATA_SOURCE_R2}/{_PATH_ANOMALY_ENTRY_REL}"


def _tamper_r2_manifest_entry_path_to_traversal(root: Path) -> None:
    r"""场景 1 篡改：precheck 后把 r2 manifest files[] entry 的 path 改为穿越路径。

    只改写该 entry 的 ``path`` 声明（sha256 / size_bytes 声明不动，
    manifest 其余字段不动）：篡改后的失败只能由“写入前路径安全
    re-validation”归因；穿越路径指向的源文件与原 entry 是同一文件，
    字节复算 sha256 与声明值一致（隔离 payload 存在性/哈希复算分支）。
    """
    manifest = json.loads(
        _manifest_file_of(root, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    entry = _manifest_files_entry(manifest, _PATH_ANOMALY_ENTRY_REL)
    assert entry["path"] == _PATH_ANOMALY_ENTRY_REL, (
        "fixture 前置事实失败：篡改前该 entry 必须声明安全相对路径"
    )
    assert ".." in Path(_P2_2_TRAVERSED_PATH).parts, (
        "fixture 前置事实失败：篡改后的声明路径必须含 .. 穿越"
        "（对齐既有预检路径安全口径：拒绝绝对路径与 .. 穿越）"
    )
    legacy_release_dir = (
        root / "workspace" / "data" / "releases" / CONFIRMED_DATA_SOURCE_R2
    )
    traversed_source = legacy_release_dir / _P2_2_TRAVERSED_PATH
    assert traversed_source.is_file(), (
        "fixture 前置事实失败：穿越路径经 legacy 源根解析的 payload 文件"
        "必须真实存在（隔离 payload 存在性分支）"
    )
    assert (
        hashlib.sha256(traversed_source.read_bytes()).hexdigest()
        == entry["sha256"]
    ), (
        "fixture 前置事实失败：穿越路径解析的源文件字节复算 sha256 必须"
        "与 entry 声明值一致（隔离哈希复算分支，fail-closed 只能由路径"
        "安全归因）"
    )
    target_release_dir = root / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    escaped_write = target_release_dir / _P2_2_TRAVERSED_PATH
    assert not escaped_write.exists(), (
        "fixture 前置事实失败：穿越声明路径的写入逃逸目的地必须当前空闲"
        "（写目标外路径可观察）"
    )
    assert not escaped_write.resolve().is_relative_to(
        target_release_dir.resolve()
    ), (
        "fixture 前置事实失败：同一声明路径在写入侧必须越出目标 release "
        "目录（写目标外路径有区分力）"
    )
    entry["path"] = _P2_2_TRAVERSED_PATH
    _rewrite_legacy_release_manifest(root, CONFIRMED_DATA_SOURCE_R2, manifest)
    tampered_manifest = json.loads(
        _manifest_file_of(root, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    assert (
        _manifest_files_entry(
            tampered_manifest, _P2_2_TRAVERSED_PATH
        )["sha256"]
        == entry["sha256"]
    ), (
        "fixture 前置事实失败：篡改必须真实生效（entry path 已改写为"
        "穿越路径，sha256 声明保持不变）"
    )


def _delete_r2_declared_payload_file(root: Path) -> None:
    r"""场景 2 篡改：precheck 后删除 r2 manifest files[] 声明的 payload 文件。

    只删 payload 文件本身：manifest files[] 声明不动（仍声明该文件与
    sha256），失败只能由“写入前 payload 存在性 re-validation”归因。
    被删条目之前仍有其他声明条目（files[] 按路径升序，该 entry 位于第
    8 位）——“边写边校验、读到才失败”的实现会先写出前序 payload 再
    失败，留下半写 release；写入前 re-validation 必须在零写入时拒绝。
    """
    manifest = json.loads(
        _manifest_file_of(root, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    entry = _manifest_files_entry(manifest, _PATH_ANOMALY_ENTRY_REL)
    payload_file = _payload_file_of(
        root, CONFIRMED_DATA_SOURCE_R2, _PATH_ANOMALY_ENTRY_REL
    )
    assert payload_file.is_file(), (
        "fixture 前置事实失败：篡改前声明的 payload 文件必须存在"
    )
    entry_index = next(
        index
        for index, candidate in enumerate(manifest["files"])
        if candidate["path"] == _PATH_ANOMALY_ENTRY_REL
    )
    assert entry_index > 0, (
        "fixture 前置事实失败：被删条目之前必须仍有声明条目（半写 "
        "release 可观察，写入前 re-validation 与边写边失败可区分）"
    )
    payload_file.unlink()
    tampered_manifest = json.loads(
        _manifest_file_of(root, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    assert _manifest_files_entry(
        tampered_manifest, _PATH_ANOMALY_ENTRY_REL
    ) == entry, (
        "fixture 前置事实失败：删除后 manifest files[] 声明必须保持不变"
        "（仍声明该文件，fail-closed 只能由 payload 存在性归因）"
    )
    assert not payload_file.exists(), (
        "fixture 前置事实失败：篡改必须真实生效（声明 payload 文件已被"
        "删除）"
    )


def _install_post_precheck_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: Callable[[Path], None],
) -> dict[str, Any]:
    r"""monkeypatch 包装 precheck_data_migration：原始 precheck ready 后执行场景篡改。

    包装先调用原函数（原始 precheck 真实执行，语义不变，原报告对象
    原样返回）；原始报告 ready 时才篡改 tmp_path（fail-closed 结论只能
    由写入前 re-validation 归因，预检自身 blocked 不得混同）。篡改事实
    （原始报告状态 + 篡改后全树快照）记入返回的 record，供调用方做
    零写入断言与归因核对。
    """
    migration_module = importlib.import_module("versioning.migration")
    original_precheck = getattr(
        migration_module, "precheck_data_migration", None
    )
    assert original_precheck is not None, (
        "fixture 前置事实失败：versioning.migration 未提供 "
        "precheck_data_migration 入口（T15-P2-2 依赖既有预检先真实通过）"
    )
    record: dict[str, Any] = {
        "report_status": None,
        "tampered": False,
        "tree_after_tamper": None,
    }

    def wrapped_precheck(root: Any, items: Any) -> Any:
        report = original_precheck(root, items)
        record["report_status"] = report.status
        if report.status == "ready":
            tamper(tmp_path)
            record["tampered"] = True
            record["tree_after_tamper"] = _snapshot_tree(tmp_path)
        return report

    monkeypatch.setattr(
        migration_module, "precheck_data_migration", wrapped_precheck
    )
    return record


@pytest.mark.parametrize(
    ("scenario", "tamper"),
    [
        pytest.param(
            "manifest_entry_path_traversal",
            _tamper_r2_manifest_entry_path_to_traversal,
            id="manifest_entry_path_traversal_after_precheck",
        ),
        pytest.param(
            "declared_payload_file_deleted",
            _delete_r2_declared_payload_file,
            id="declared_payload_file_deleted_after_precheck",
        ),
    ],
)
def test_migrate_data_revalidates_manifest_paths_and_payload_after_precheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    tamper: Callable[[Path], None],
) -> None:
    r"""migrate_data 在 precheck 与写入之间必须重新校验 manifest files[]（P2-2）。

    T15-P2-2 behavior（reviewer 对 T15 的 P2-2：T15 的 manifest 自洽
    性/内容完整性校验只在预检阶段执行 —— 预检通过与写入之间存在
    TOCTOU 窗口，写入时重新读取的 manifest 可以不再是预检验证过的
    那份）—— ``migrate_data`` 在原始 precheck 通过后、写入前重新
    读取 manifest 时，必须重新校验 manifest files[] 声明路径的安全性
    与 payload 存在性：
    1. precheck 后把 manifest files[] entry 的 path 改为穿越路径（写入
       侧越出目标 release 目录）-> 必须 fail-closed：不得把 payload 写
       到目标 release 之外（不写目标外路径）、不得留下半写 release、
       不得写 receipt；
    2. precheck 后删除一个声明的 payload 文件 -> 必须 fail-closed：
       不得留下半写 release、不得写 receipt；
    3. 两个场景的 fail-closed 都必须经既有迁移拒绝通道
       ``DataMigrationBlocked`` 给出（T15 既有 blocked 分支的同一通道，
       不得以原始 FileNotFoundError / OSError 穿透替代 —— 未类型化异常
       不可归因且不是设计出的拒绝通道）；
    4. fail-closed 必须发生在任何写入之前（零写入）：目标 data 根与
       migration_receipts/ 不创建；除场景篡改自身（manifest 改写 /
       payload 删除）外全树逐字节不变（legacy 源与旧 active pointers
       逐字节不变）；不就地修改传入映射项。

    fixture：复用 T15 双对象布局 + r2 单条映射批（_write_legacy_data_
    layout + _confirmed_r2_mapping_item；含 T15 同款 counts 场景注入
    + 指针 manifest 哈希随注入重写 —— 不注入则 production 写入口径
    _derive_release_splits 在复制循环之前因 counts.splits 缺失拒绝，
    fail-closed 会由该无关门归因（伪绿）；注入后写入路径真实可
    达，re-validation 门可观察）。注入方式：monkeypatch 包装
    ``versioning.migration.precheck_data_migration`` —— 包装先调用原
    函数（原始 precheck 真实执行且必须 ready），ready 后再篡改
    tmp_path 中的 manifest / 删除 payload，再原样返回原报告；篡改
    发生在 migrate_data 的 precheck 调用返回与写入之间，使写入时
    重新读取的 manifest 与预检验证过的那份不同。包装记录原始报告
    状态与篡改后全树快照，供零写入断言与归因核对（篡改未发生 /
    预检自身 blocked 不得冒充 re-validation 结论）。

    捕获的合理但错误实现：
    - 当前 production（RED 起点）：_migrate_single_data_release 在写入
      时重新读取 manifest，但不做任何写入前 re-validation —— 场景 1
      以穿越路径把 payload 写到 data/releases/<源身份>/ 下并继续成功
      返回（DID NOT RAISE）；场景 2 在逐文件复制循环中途以原始
      FileNotFoundError 穿透，且前序 payload 已写出（半写 release 留
      在目标下）；
    - 只依赖循环中逐文件读取的异常（同上：半写 + 原始未类型化异常
      穿透）；
    - re-validation 只查路径安全不查 payload 存在性（或反之）-> 另一
      场景仍 DID NOT RAISE / 半写，单场景绿不能掩盖缺口；
    - re-validation 在部分写入之后才拒绝（先写 datasets/ 再查
      metadata/）-> 零写入全树快照比对失败（半写 release 可见）；
    - 借 re-validation 顺手修复 / 改写 manifest、payload 或旧指针 ->
      全树快照比对失败；
    - 预检自身 blocked（fixture 破损等）冒充 re-validation fail-closed
      -> record.tampered 归因核对失败。

    范围边界（本切片不绑定）：re-validation 的具体机制（重跑既有整批
    precheck 或最小化只重验 manifest files[] 路径安全与 payload 存在性
    —— 行为只钉 fail-closed + 零写入 + 拒绝通道，不钉机制与拒绝信息
    文本）、r1 superseded 转换与 replacement 语义、批级多对象写入顺序、
    批级恢复、凭证失配拒绝、重跑幂等跳过、manifest 其他字段（counts /
    contract 等）的写入前 re-validation（T15 已钉语义字段取声明值；
    本切片只钉 files[] 路径安全与 payload 存在性）、payload 封存去写位
    的时序、CLI、DVC 接入、训练机真实路径。

    Binding（RED 证据绑定，供复跑核对）：
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_revalidates_manifest_paths_and_payload_after_precheck``
    - RED failure signature：场景
      ``manifest_entry_path_traversal_after_precheck`` 以
      ``Failed: DID NOT RAISE DataMigrationBlocked`` 失败（当前
      production 不做写入前路径安全 re-validation，穿透到成功返回，
      且已把 payload 写到目标 release 之外的
      ``data/releases/<源身份>/`` 下）；场景
      ``declared_payload_file_deleted_after_precheck`` 以原始
      ``FileNotFoundError`` 在逐文件复制循环中途穿透失败（前序 payload
      已写出，半写 release 留在目标下）；两者均不得以原始未类型化
      异常穿透 / 成功返回充当有效 RED 之外的结论；
    - ``pyproject.toml`` sha256（RED 时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：复用 T15 双对象布局 + r2 单条映射批 + counts 场景
    # 注入（与 T15/P2-1 同款：写入路径真实可达，fail-closed 只能由写入
    # 前 re-validation 归因，不由 counts.splits 缺失等无关门归因）。----
    _write_legacy_data_layout(tmp_path)
    mapping_items = [_confirmed_r2_mapping_item()]

    r2_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r2_manifest["counts"] = {
        "published_candidates": 7,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 5,
            "fold_0_val": 2,
            "fold_1_train": 6,
            "fold_1_val": 4,
            "fold_2_train": 7,
            "fold_2_val": 1,
        },
    }
    r2_manifest_bytes = _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R2, r2_manifest
    )
    pointer = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        r2_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(tmp_path, pointer)

    # ---- fixture 前置事实（T15 同口径：注入自洽 + 目标根空闲）：原始
    # precheck（未被包装）对注入后状态整批 ready —— fail-closed 结论只
    # 能由写入前 re-validation 归因；映射批恰为 r2 单条。----
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（当前 behavior 未实现）"
    )
    report = precheck(tmp_path, mapping_items)
    assert report.status == "ready", (
        "fixture 前置事实失败：篡改前原始 precheck 必须整批 ready"
        f"（实际 {report.status!r}）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2
    ], "fixture 前置事实失败：映射批必须恰为 r2 单条"

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "单对象 r2 data 真实迁移行为缺失：versioning.migration 未提供 "
        "migrate_data 入口（当前 behavior 未实现）"
    )
    blocked_exc = getattr(
        importlib.import_module("versioning.migration"),
        "DataMigrationBlocked",
        None,
    )
    assert blocked_exc is not None, (
        "data 迁移拒绝通道缺失：versioning.migration 未提供 "
        "DataMigrationBlocked（fail-closed 必须经既有迁移拒绝通道给出）"
    )

    record = _install_post_precheck_tamper(tmp_path, monkeypatch, tamper)

    # ---- 行为：篡改后的 manifest 必须在写入前被 re-validation 拒绝
    #（fail-closed，经 DataMigrationBlocked 通道）。----
    with pytest.raises(blocked_exc):
        migrate_data(tmp_path, mapping_items)

    # ---- 归因核对：篡改确实发生在原始 precheck 返回 ready 之后、
    # migrate_data 返回之前（预检自身 blocked 不得冒充 re-validation
    # fail-closed）。----
    assert record["tampered"] is True, (
        "场景篡改未发生：包装的原始 precheck 未返回 ready —— fail-closed "
        "结论只能由写入前 re-validation 归因，不得由预检自身 blocked 混同"
    )
    assert record["report_status"] == "ready", (
        "fixture 前置事实失败：migrate_data 内的原始 precheck 调用必须"
        f"在篡改前返回 ready（实际 {record['report_status']!r}）"
    )

    # ---- 1/2：fail-closed 必须零写入。目标 data 根与 receipt 目录
    # 不得被创建（无半写 release、无 receipt 的最外层事实）。----
    for root_name in ("data", "migration_receipts"):
        assert not (tmp_path / root_name).exists(), (
            f"fail-closed 拒绝必须发生在任何写入之前：{root_name}/ 不得被"
            "创建（不得留下半写 release，不得写 receipt）"
        )
    if scenario == "manifest_entry_path_traversal":
        escaped_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_SOURCE_R2
        assert not escaped_dir.exists(), (
            "不得写目标外路径：穿越声明路径在目标 release 之外的写入"
            "逃逸不得发生"
        )

    # ---- 零写入全树比对：除场景篡改自身（manifest 改写 / payload
    # 删除）外逐字节不变 —— 不写目标外路径、不留半写 release、不写
    # receipt、legacy 源与旧 active pointers 逐字节不变（篡改后快照由
    # 包装在原始 precheck ready 后、migrate_data 写入前记录）。----
    assert _snapshot_tree(tmp_path) == record["tree_after_tamper"], (
        "fail-closed 拒绝必须零写入：migrate_data 失败后的全树必须与"
        "篡改刚发生时逐字节一致 —— 不得写目标外路径、不得留下半写 "
        "release、不得写 receipt、不得触碰 legacy 源与旧 active pointers"
    )

    # ---- 不就地修改传入映射项（T15 同口径）。----
    assert mapping_items == [_confirmed_r2_mapping_item()], (
        "fail-closed 拒绝不得就地改写传入映射项（M0 事实分级保持不变）"
    )


# ---------------------------------------------------------------------------
# T16：单对象 data 真实转换 —— 单条已确认 r1 映射 -> data-v4.1-r1
# superseded 正式 release + replacement=data-v4.1-r2 + committed receipt
#（先写测试，不改 production；行为前提：目标 root 已存在正式
# data-v4.1-r2，由当前 migrate_data 先行创建）
# ---------------------------------------------------------------------------


def _confirmed_r1_mapping_item() -> dict[str, Any]:
    """从双对象映射批中取 r1 单条已确认映射（M0 证据逐字段镜像）。

    T16 只对单条 r1 映射执行真实转换：fixture 复用 T11/T15 的双对象
    legacy 布局（三份 legacy release + 旧数据 / Prompt 活动指针），传入
    的映射批只含 r1 条目（v4.1.0-760050fad303 -> data-v4.1-r1，D1 用户
    确认：target_status ``superseded``、replacement ``data-v4.1-r2``）；
    r2 条目不在批内 —— r2 由前置的 migrate_data 调用先行创建（T15 既有
    行为；目标 root 已存在正式 data-v4.1-r2 是本切片的行为前提），本
    切片只转换 r1。
    """
    items = [
        item
        for item in _confirmed_data_mapping_items()
        if item["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1
    ]
    assert len(items) == 1, (
        "fixture 前置事实失败：双对象映射批中 r1 条目必须恰有一条"
    )
    return items[0]


def test_migrate_data_single_r1_superseded_mapping_creates_superseded_release_with_replacement(
    tmp_path: Path,
) -> None:
    r"""单条已确认 r1 superseded 映射的真实 data 转换：superseded 正式
    release + replacement + committed receipt（前提：目标 root 已存在
    正式 data-v4.1-r2）。

    T16 behavior（本切片，主 Agent 选定，先写测试，不改 production）——
    在目标 root 已存在正式 ``data-v4.1-r2`` 的前提下（fixture 先经当前
    ``migrate_data`` 创建 r2 —— T15 既有行为），对单条已确认 r1 映射
    ``v4.1.0-760050fad303`` -> ``data-v4.1-r1``（M0 object-mapping 已
    确认；D1 用户确认：target_status ``superseded``、replacement
    ``data-v4.1-r2``）执行真实 data 转换时：
    1. 在目标 root 下创建正式 release ``data/releases/data-v4.1-r1/``；
    2. payload 文件集合与逐文件字节和 legacy r1 源一致（目标内容恰为
       release.yaml + r1 legacy manifest files[] 声明的 payload 文件
       集合，不夹带非本切片最小行为文件）；
    3. release.yaml 可被既有 data release 读取/校验语义
       （versioning.data_release.load_release_metadata）接受；
    4. version 为 ``data-v4.1-r1``（新体系完整身份，不得沿用 legacy
       哈希身份）；
    5. status 为 ``superseded``（映射 target_status，D1 用户确认）；
    6. replacement 为 ``data-v4.1-r2``（映射声明值），且 replacement
       可解析 —— 在目标 root 下解析为既有正式对象并经既有读回语义给出
       active r2（既有 ``_validate_replacement`` 语义已保证 replacement
       是合法 data 完整身份且不指向自身；本切片把可解析性钉到真实存在
       的正式对象，不得是悬空引用）；
    7. ``validate_training_reference`` 对 r1 拒绝（既有训练引用门
       ``ReferenceNotAllowed`` —— superseded 数据不允许新引用），对
       r2 放行（active；且 r1 转换不得破坏既有 r2 的可训练性）；
    8. 在目标 root 的 ``migration_receipts/data-v4.1-r1.receipt.yaml``
       写入 committed receipt（八字段与 T15 同语义：键集恰为
       operation_id / source_legacy_id / target_identity / target_path /
       source_manifest_sha256 / target_release_digest / status /
       written_at；source_manifest_sha256 与 r1 legacy manifest 文件字节
       哈希一致；target_release_digest 可由 r1 目标内容按 T15 钉定口径
       复算核实）；
    9. legacy 源与旧 active pointers 逐字节不变；既有 r2 正式对象与
       r2 receipt 逐字节不变（r1 转换不得触碰已存在的正式对象）；不
       写 records、不触发 DVC、不新增顶层条目、不就地修改传入映射项；
    10. 本切片不做批级恢复、凭证失配拒绝、重跑幂等跳过（D2 已确认
        目标语义留待后续切片；r1 receipt 只钉创建与可核实性）。

    fixture：复用 T15 fixture（``_write_legacy_data_layout`` 双对象
    legacy 布局 + r2 counts 场景注入 + 指针 manifest 哈希随注入重写
    —— 不注入则 production 写入口径 ``_derive_release_splits`` 在写入
    前因 counts.splits 缺失拒绝，r2 无法创建，前置事实失败）。本切片
    新增场景变量：r1 legacy manifest 的 counts 同款注入
    （published_candidates 11、fold_N_train/fold_N_val 声明值），与 r1
    payload 可复算值（候选 3、每折样本 3）、r2 注入声明值
    （published_candidates 7）均故意不同 —— 使“语义字段取 r1 manifest
    声明值”可观察：从 payload 重算、读错源（取 r2 manifest 补齐）的实
    现必被捕获；也是 GREEN 可达性前提（r1 manifest 无 counts.splits 则
    共享写入口径在写入前拒绝，正确实现也永远无法通过）。注入只改
    counts：files[] 声明哈希不动（T14 manifest 自洽门保持绿）；r1 无
    钉扎（M0 pinned_by: ~），无需改写指针（T13 门对 r1 不适用）。

    捕获的合理但错误实现：
    - 当前 production（RED 起点）：migrate_data 在任何写入前对
      target_status 非 active 的映射 fail-closed 拒绝
      （DataMigrationBlocked：target_status='superseded' 的真实转换
      不在本切片内（仅覆盖 active））—— 本用例把该拒绝转成显式行为
      AssertionError（原始 DataMigrationBlocked 经 cause 链保留，不得
      直接充当 RED 结论）；r1 正式 release / receipt 均不产生；
    - 写入侧只认 active：绕过批级门后仍以“目标 release 验证失败：
      status 非 active”拒绝（同上，显式 AssertionError 钉出）；
    - superseded 落地但 replacement 缺失 / 悬空：release.yaml 不写
      replacement 键、replacement 误用 legacy 哈希身份或指向目标 root
      下不存在的对象 -> meta.replacement / replacement 可解析断言失败
      （既有 _validate_replacement 语义经 load_release_metadata 把关
      非法身份与自指）；
    - replacement 写入但 status 仍为 active / version 误用 legacy 哈希
      身份 -> status / version 断言失败；
    - 目标 release 漏 payload / 逐文件字节漂移 / 夹带非最小行为文件
      -> 精确文件集合与逐字节比对失败；
    - 语义字段从 payload 重算或从 r2 manifest 补齐（r1 与 r2 注入声明
      值故意不同）-> sample_count / splits 比对失败；
    - receipt 缺字段 / 键集不精确 / 哈希伪造（source_manifest_sha256 非
      r1 manifest 文件字节口径、target_release_digest 与 r1 目标内容
      复算不符或漏算文件）-> receipt 断言失败；
    - r1 转换触碰既有 r2 正式对象或 r2 receipt（改写 release.yaml、重
      新封存、补文件）-> 全树快照 before/after 比对失败；
    - 转换触碰 legacy 源或旧 active pointers（切换指针到新身份、改写
      manifest/payload）-> 逐字节快照断言失败；
    - 写 records/ / 生命周期目录 / .dvc / 新增顶层条目 -> 对应断言失
      败；就地修改传入映射项 -> 映射项不变断言失败；
    - 训练引用门语义漂移（对 superseded r1 放行）-> pytest.raises
      (ReferenceNotAllowed) DID NOT RAISE 失败（既有门由本切片在新体
      系迁移对象上钉定回归；对 r2 的拒绝 / 非法 release.yaml 同样经
      既有门失败）。

    范围边界（本切片不绑定）：批级多对象写入顺序（r1 与 r2 是两次独立
    migrate_data 调用，不在同一批内）、migrate_data 返回值契约、批级恢
    复、凭证失配拒绝、重跑幂等跳过（receipt 只钉创建与可核实性，不钉
    跳过逻辑）、r1 目标 payload 封存去写位（T15-P2-1 封存绑定覆盖共享
    写入口径；如 r1 封存出现缺口由后续补丁切片钉定，本切片不夹带）、
    replacement 的受控通道语义（update_release_status 后续行为）、
    CLI、DVC 接入、训练机真实路径与权限准备。

    Binding（RED 证据绑定，供复跑核对）：
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_single_r1_superseded_mapping_creates_superseded_release_with_replacement``
    - RED failure signature：fixture 构建、双 counts 场景注入、前置事实
      断言（含 r1/r2 manifest 自洽、r1 映射 D1 镜像、目标根空闲、r2 真实
      创建、r1 批 precheck-ready）、全树快照真实执行之后，显式
      ``AssertionError: 单对象 r1 superseded data 真实迁移行为缺失：
      ...``（cause 链保留当前 production 的
      ``DataMigrationBlocked: target_status='superseded' 的真实转换
      不在本切片内（仅覆盖 active）``；原始异常穿透 / import 错误 /
      AttributeError 不得成为 RED）；
    - ``pyproject.toml`` sha256（RED 时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：复用 T15 双对象布局 + r2 counts 场景注入（T15 同款：
    #      写入路径真实可达）+ 指针 manifest 哈希随注入重写。----
    _write_legacy_data_layout(tmp_path)
    r2_mapping = _confirmed_r2_mapping_item()
    r1_mapping = _confirmed_r1_mapping_item()

    r2_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r2_manifest["counts"] = {
        "published_candidates": 7,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 5,
            "fold_0_val": 2,
            "fold_1_train": 6,
            "fold_1_val": 4,
            "fold_2_train": 7,
            "fold_2_val": 1,
        },
    }
    r2_manifest_bytes = _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R2, r2_manifest
    )
    pointer = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        r2_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(tmp_path, pointer)

    # ---- 场景化注入（本切片新增变量）：r1 manifest counts 与 payload
    #      可复算值、r2 注入声明值均故意不同 —— “语义字段取 r1 manifest
    #      声明值（不重算、不读错源）”可观察，且共享写入口径对 r1 真实
    #      可达（fixture 基线 manifest 无 counts.splits，不注入则正确
    #      实现也会在写入前被无关门拒绝，测试永远无法 GREEN）。注入只
    #      改 counts：files[] 声明哈希不动（T14 门保持绿）；r1 无钉扎
    #      （M0 pinned_by: ~），无需改写指针（T13 门对 r1 不适用）。----
    r1_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).read_text(
            encoding="utf-8"
        )
    )
    r1_manifest["counts"] = {
        "published_candidates": 11,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 9,
            "fold_0_val": 4,
            "fold_1_train": 8,
            "fold_1_val": 2,
            "fold_2_train": 10,
            "fold_2_val": 3,
        },
    }
    _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R1, r1_manifest
    )

    # ---- fixture 前置事实（注入自洽 + 区分力 + D1 镜像 + 目标根空闲）----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    r1_payload_candidates = json.loads(
        _payload_file_of(
            tmp_path,
            CONFIRMED_DATA_SOURCE_R1,
            "metadata/training_candidates.json",
        ).read_text(encoding="utf-8")
    )
    assert len(r1_payload_candidates["candidates"]) == 3, (
        "fixture 前置事实失败：r1 payload 候选数应为 3（注入区分力的"
        "payload 侧事实）"
    )
    r1_fold_0_train = json.loads(
        _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, "datasets/train/fold_0.json"
        ).read_text(encoding="utf-8")
    )
    assert len(r1_fold_0_train["samples"]) == 3, (
        "fixture 前置事实失败：r1 payload fold 文件样本数应为 3"
    )
    assert r1_manifest["counts"]["published_candidates"] != len(
        r1_payload_candidates["candidates"]
    ), "fixture 前置事实失败：r1 注入声明值必须与 payload 可复算值不同"
    assert r1_manifest["counts"]["published_candidates"] != (
        r2_manifest["counts"]["published_candidates"]
    ), (
        "fixture 前置事实失败：r1 注入声明值必须与 r2 注入声明值不同"
        "（读错源可观察）"
    )
    assert r1_manifest["counts"]["splits"]["fold_0_train"] != len(
        r1_fold_0_train["samples"]
    ), "fixture 前置事实失败：r1 注入 splits 声明值必须与 payload 可复算值不同"
    # r1 映射逐字段镜像 D1 用户确认（M0 证据）：superseded +
    # replacement=data-v4.1-r2；r2 映射 target_status active。
    assert r1_mapping["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1
    assert r1_mapping["candidate_target_identity"] == (
        CONFIRMED_DATA_TARGET_R1
    )
    assert r1_mapping["target_path"] == "data/releases/data-v4.1-r1/release.yaml"
    assert r1_mapping["status"] == "user_confirmed"
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded"
        "（D1 用户确认）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2"
        "（D1 用户确认）"
    )
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "单对象 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T15 既有行为不可用，本切片 fixture 前置事实"
        "失败）"
    )
    blocked_exc = getattr(
        importlib.import_module("versioning.migration"),
        "DataMigrationBlocked",
        None,
    )
    assert blocked_exc is not None, (
        "data 迁移拒绝通道缺失：versioning.migration 未提供 "
        "DataMigrationBlocked（fail-closed 必须经既有迁移拒绝通道给出）"
    )

    # ---- 行为前提构造：先经当前 migrate_data 创建 r2（T15 既有单对象
    #      active 转换；目标 root 已存在正式 data-v4.1-r2）。----
    try:
        migrate_data(tmp_path, [r2_mapping])
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：当前 migrate_data 必须先成功创建 r2"
            "（T15 既有单对象 active 转换行为；原始异常经 cause 链保留）："
            f"{exc!r}"
        ) from exc
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    assert r2_release_dir.is_dir(), (
        "fixture 前置事实失败：r2 正式 release 必须已创建（目标 root 已"
        "存在正式 data-v4.1-r2 是本切片的行为前提）"
    )
    r2_meta = load_release_metadata(
        tmp_path / "data", CONFIRMED_DATA_TARGET_R2
    )
    assert r2_meta.version == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r2 必须经既有语义读回为 data-v4.1-r2"
    )
    assert r2_meta.status is DataStatus.ACTIVE, (
        "fixture 前置事实失败：r2 必须经既有语义读回为 active 正式对象"
    )
    r2_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：r2 committed receipt 必须已写入"
    )
    r2_receipt = yaml.safe_load(r2_receipt_file.read_text(encoding="utf-8"))
    assert isinstance(r2_receipt, dict) and (
        r2_receipt.get("status") == "committed"
    ), "fixture 前置事实失败：r2 receipt 必须为 committed"

    # ---- 前置事实：r1 单条映射批对“r2 已存在”的目标根 precheck 整批
    #      ready（既有精确身份口径下 r2 不是 r1 的冲突）—— migrate_data
    #      的 fail-closed 拒绝只能由写入阶段的切片边界归因，不得由预检
    #      自身 blocked 混同。----
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（当前 behavior 未实现）"
    )
    r1_precheck_report = precheck(tmp_path, [r1_mapping])
    assert r1_precheck_report.status == "ready", (
        "fixture 前置事实失败：r1 单条映射批的只读预检必须整批 ready"
        f"（实际 {r1_precheck_report.status!r}，reasons="
        f"{r1_precheck_report.reasons!r}）—— 既有正式 r2 的存在不得被误"
        "判为 r1 目标冲突"
    )

    before = _snapshot_tree(tmp_path)

    # ---- 行为：对单条已确认 r1 superseded 映射执行真实转换。----
    # RED Gate：当前 production 对 target_status 非 active 的映射在写入
    # 前 fail-closed 拒绝（DataMigrationBlocked）—— 本用例把该拒绝转成
    # 显式行为 AssertionError 钉出“单对象 r1 superseded 真实迁移行为缺
    # 失”，原始 DataMigrationBlocked 经 cause 链保留，不得直接充当 RED
    # 结论。
    try:
        migrate_data(tmp_path, [r1_mapping])
    except blocked_exc as exc:
        raise AssertionError(
            "单对象 r1 superseded data 真实迁移行为缺失：migrate_data 对 "
            "precheck-ready 的已确认 r1 映射（target_status=superseded、"
            f"replacement={CONFIRMED_DATA_TARGET_R2}，D1 用户确认）在真实"
            "转换阶段拒绝（本切片要求创建 data-v4.1-r1 superseded 正式 "
            "release + replacement 并写 committed receipt；原始拒绝经 "
            f"cause 链保留）：{exc}"
        ) from exc

    # 1：目标 root 下创建正式 release data/releases/data-v4.1-r1/。
    release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    assert release_dir.is_dir(), (
        f"真实转换必须在目标 root 下创建正式 release：{release_dir}"
    )
    target_content = _release_content_files(release_dir)

    # 2：payload 与 legacy r1 源逐文件一致 —— 目标内容恰为 release.yaml
    #    + r1 legacy manifest files[] 声明的 payload 文件集合（精确集合，
    #    不夹带非最小行为文件）；逐文件字节一致（字节一致即逐文件
    #    SHA-256 一致，不重算、不规范化）。
    declared_payload_paths = sorted(
        entry["path"] for entry in r1_manifest["files"]
    )
    assert set(target_content) == {"release.yaml"} | set(
        declared_payload_paths
    ), (
        "目标 release 内容必须恰为 release.yaml + r1 legacy manifest 声明"
        f"的 payload 文件集合：实际 {sorted(target_content)}"
    )
    legacy_release_root = (
        tmp_path / "workspace" / "data" / "releases" / CONFIRMED_DATA_SOURCE_R1
    )
    for relative in declared_payload_paths:
        legacy_bytes = (legacy_release_root / relative).read_bytes()
        assert target_content[relative] == legacy_bytes, (
            f"目标 payload 文件 {relative} 必须与 legacy r1 源逐字节一致"
            f"（fixture 语义：源 SHA-256 为 "
            f"{hashlib.sha256(legacy_bytes).hexdigest()}）"
        )

    # 3/4/5/6：release.yaml 经既有读取/校验语义接受（解析即校验：schema、
    #    字段值域、version 与目录一致、replacement 规则全由
    #    load_release_metadata 把关）；version 为 data-v4.1-r1；status 为
    #    superseded；replacement 为 data-v4.1-r2 且在目标 root 下可解析
    #    为既有正式 active r2。
    meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    assert meta.version == CONFIRMED_DATA_TARGET_R1, (
        f"release.yaml 的 version 必须为 {CONFIRMED_DATA_TARGET_R1!r}"
        f"（新体系完整身份，不得沿用 legacy 哈希身份）：实际 "
        f"{meta.version!r}"
    )
    assert meta.status is DataStatus.SUPERSEDED, (
        "release.yaml 的 status 必须为 superseded（映射 target_status，D1 "
        f"用户确认）：实际 {meta.status!r}"
    )
    assert meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        "release.yaml 的 replacement 必须为映射声明的 "
        f"{CONFIRMED_DATA_TARGET_R2!r}（D1 用户确认）：实际 "
        f"{meta.replacement!r}"
    )
    release_yaml_raw = yaml.safe_load(target_content["release.yaml"])
    assert isinstance(release_yaml_raw, dict), (
        "release.yaml 顶层必须是映射"
    )
    assert release_yaml_raw["status"] == "superseded", (
        "release.yaml 的原始 status 字段必须为 superseded：实际 "
        f"{release_yaml_raw.get('status')!r}"
    )
    assert release_yaml_raw["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "release.yaml 必须携带 replacement 键且值为 data-v4.1-r2：实际 "
        f"{release_yaml_raw.get('replacement')!r}"
    )
    replacement_meta = load_release_metadata(
        tmp_path / "data", meta.replacement
    )
    assert replacement_meta.version == CONFIRMED_DATA_TARGET_R2, (
        "superseded r1 的 replacement 必须可解析：在目标 root 下解析为"
        f"既有正式对象 {CONFIRMED_DATA_TARGET_R2!r}：实际解析为 "
        f"{replacement_meta.version!r}"
    )
    assert replacement_meta.status is DataStatus.ACTIVE, (
        "superseded r1 的 replacement 必须解析为既有正式 active r2（不得"
        "是悬空引用或非 active 对象）：实际 status="
        f"{replacement_meta.status!r}"
    )

    # 语义字段取 r1 legacy manifest 声明值（不重算、不伪造、不读错源
    # —— 注入声明值与 payload 可复算值、r2 声明值均不同）。superseded
    # r1 仍是 development 训练 release（training_allowed=true）：训练引
    # 用门对 r1 的拒绝只能由 superseded 状态归因（行为项 7 的归因前提），
    # 不得伪造成不可训练语义。
    assert meta.protocol == r1_manifest["contract_version"], (
        "release.yaml 的 protocol 必须取 r1 legacy manifest 的 "
        f"contract_version 声明值 {r1_manifest['contract_version']!r}："
        f"实际 {meta.protocol!r}"
    )
    assert meta.purpose == "development", (
        "legacy 训练 release（manifest status training_ready）的正式映射 "
        f"purpose 必须为 development：实际 {meta.purpose!r}"
    )
    assert meta.training_allowed is True, (
        "development 训练 release 的 training_allowed 必须为 true（拒绝新"
        "引用只能由 superseded 状态归因，不得伪造成不可训练语义）：实际"
        f" {meta.training_allowed!r}"
    )
    assert meta.sample_count == (
        r1_manifest["counts"]["published_candidates"]
    ), (
        "sample_count 必须取 r1 legacy manifest counts.published_candidates"
        f" 声明值 {r1_manifest['counts']['published_candidates']}，不得从 "
        "payload 重算、伪造或读错源（fixture 注入的声明值与 payload 可复"
        "算值、r2 声明值故意不同）"
    )
    expected_r1_splits = {
        f"fold_{fold}": {
            "train": r1_manifest["counts"]["splits"][f"fold_{fold}_train"],
            "validation": r1_manifest["counts"]["splits"][f"fold_{fold}_val"],
        }
        for fold in range(3)
    }
    assert dict(meta.splits) == expected_r1_splits, (
        "splits 必须取 r1 legacy manifest counts.splits 声明值"
        "（fold_N_train -> train、fold_N_val -> validation），不得从 payload "
        "fold 文件重算或读错源（fixture 注入的声明值与 payload 可复算值、"
        f"r2 声明值故意不同）：实际 {dict(meta.splits)!r}"
    )
    assert set(meta.source_batches) == {
        r1_manifest["source_review_batch_id"],
        r1_manifest["source_queue_id"],
        r1_manifest["source_media_id"],
    }, (
        "source_batches 必须记录 r1 legacy manifest 声明的原始批次标识"
        f"（不回填伪造、不读错源）：实际 {sorted(meta.source_batches)}"
    )

    # 7：训练引用门 —— superseded r1 拒绝新引用（既有门
    #    ReferenceNotAllowed），active r2 放行（r1 转换不得破坏既有 r2
    #    的可训练性）。
    with pytest.raises(ReferenceNotAllowed):
        validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)

    # 8：committed receipt（八字段与 T15 同语义；两处哈希独立复算核实）。
    receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    assert receipt_file.is_file(), (
        "真实转换必须在目标对象完整写入并验证后创建 committed receipt："
        f"{receipt_file}"
    )
    receipt = yaml.safe_load(receipt_file.read_text(encoding="utf-8"))
    assert isinstance(receipt, dict), (
        "migration receipt 必须是 YAML 顶层映射"
    )
    assert set(receipt) == set(_RECEIPT_FIELDS), (
        "receipt 键集必须恰为八字段契约（与 T15 同语义，不夹带映射项 "
        f"dump 或其他非契约字段）：实际 {sorted(receipt)}"
    )
    assert isinstance(receipt["operation_id"], str) and receipt["operation_id"], (
        "receipt.operation_id 必须是非空字符串（本切片不绑定其格式）"
    )
    assert receipt["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1, (
        f"receipt.source_legacy_id 必须为 {CONFIRMED_DATA_SOURCE_R1!r}："
        f"实际 {receipt['source_legacy_id']!r}"
    )
    assert receipt["target_identity"] == CONFIRMED_DATA_TARGET_R1, (
        f"receipt.target_identity 必须为 {CONFIRMED_DATA_TARGET_R1!r}："
        f"实际 {receipt['target_identity']!r}"
    )
    assert receipt["target_path"] == r1_mapping["target_path"], (
        "receipt.target_path 必须与映射项声明的 target_path 一致：实际 "
        f"{receipt['target_path']!r}"
    )
    assert receipt["source_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).read_bytes()
    ).hexdigest(), (
        "receipt.source_manifest_sha256 必须与 r1 legacy 源 manifest 文件"
        "字节哈希一致（文件字节口径；下方全树快照保证该字节与转换前"
        "一致）"
    )
    assert receipt["target_release_digest"] == (
        _recompute_target_release_digest(target_content)
    ), (
        "receipt.target_release_digest 必须能由 r1 目标 release 内容按 "
        "T15 钉定口径复算验证（目标全部文件按相对 POSIX 路径升序拼接 "
        "<rel>/<sha256> 行后的整体 SHA-256）；digest 绑定半成品快照、只"
        "覆盖 release.yaml 或漏算文件的实现必被捕获"
    )
    assert receipt["status"] == "committed", (
        f"receipt.status 必须为 committed：实际 {receipt['status']!r}"
    )
    assert isinstance(receipt["written_at"], str) and receipt["written_at"], (
        "receipt.written_at 必须是非空字符串（本切片不绑定精确值与格式）"
    )

    # 9：legacy 源与旧 active pointers 逐字节不变；既有 r2 正式对象与
    #    r2 receipt 不被触碰（r1 转换对 before 中任何既有条目零改动、
    #    零删除，新增条目只允许落在 r1 目标 release 目录子树与 r1
    #    receipt）；不新增顶层条目、不写 records/ 生命周期目录、不触发
    #    DVC；不就地修改传入映射项。
    after = _snapshot_tree(tmp_path)
    new_keys = set(after) - set(before)
    r1_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r1_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R1}"
    r1_release_prefix = f"{r1_release_root_rel}/"
    assert all(
        key == r1_receipt_rel
        or key == r1_release_root_rel
        or key.startswith(r1_release_prefix)
        for key in new_keys
    ), (
        "r1 真实转换只允许新增 r1 目标 release 目录子树（含目录条目）与 "
        f"r1 receipt：实际新增 {sorted(new_keys)}"
    )
    assert not set(before) - set(after), (
        "r1 真实转换不得删除/移动任何既有条目（既有 r2 正式对象与 "
        "receipt、legacy 源、旧 active pointers）"
    )
    for key, value in before.items():
        assert after[key] == value, (
            f"r1 真实转换不得改动既有条目 {key!r}（既有 r2 正式对象与 "
            "receipt、legacy 源与旧 active pointers 逐字节不变；不改"
            "写、不规范化、不去写位）"
        )
    data_pointer_after = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_after["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "旧数据活动指针必须仍声明 legacy 身份，不得被切换到新身份"
    )
    prompt_pointer_after = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_after["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "旧 Prompt 活动指针必须仍声明 legacy revision_id"
    )
    before_top_levels = {key.split("/", 1)[0] for key in before}
    after_top_levels = {key.split("/", 1)[0] for key in after}
    assert after_top_levels == before_top_levels, (
        "r1 真实转换不得新增任何顶层条目（data/ 与 migration_receipts/ "
        "已由 r2 创建存在）：实际新增 "
        f"{sorted(after_top_levels - before_top_levels)}"
    )
    for forbidden in (
        "records",
        "working",
        "release_staging",
        "data/working",
        "data/release_staging",
    ):
        assert not (tmp_path / forbidden).exists(), (
            f"真实转换不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in after), (
        "真实转换不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    assert ".gitignore" not in after_top_levels, (
        "真实转换不得创建或改写 .gitignore（DVC 接入不在本切片）"
    )
    # data/releases/ 恰含 r1 与 r2 两个正式对象；migration_receipts/ 恰
    # 含两份 receipt（r2 先行创建、r1 本切片写入；不夹带未映射 sibling
    # 的目标条目/凭证）。
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "data/releases/ 必须恰含 data-v4.1-r1 与 data-v4.1-r2（既有 r2 "
        "不被触碰，不夹带未映射 sibling）"
    )
    receipts_root = tmp_path / "migration_receipts"
    assert [
        entry.name for entry in sorted(receipts_root.iterdir())
    ] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], "migration_receipts/ 必须恰含 r1 与 r2 两份 receipt"
    assert r1_mapping == _confirmed_r1_mapping_item(), (
        "真实转换不得就地改写传入映射项（M0 事实分级保持不变）"
    )


# ---------------------------------------------------------------------------
# T17：双对象批转换终态 —— 一次 migrate_data 调用传入 r2+r1 两条映射
#（D2 推荐顺序 r2 先于 r1）创建两个正式 release + 两份 committed
# receipt，replacement 在同一次调用内可解析（先写测试，不改 production）
# ---------------------------------------------------------------------------


def test_migrate_data_dual_object_batch_creates_both_releases_and_committed_receipts(
    tmp_path: Path,
) -> None:
    r"""双对象批（r2 active + r1 superseded）一次 migrate_data 调用的终态。

    T17 behavior（本切片，主 Agent 选定，先写测试，不改 production）——
    对包含 r2 与 r1 的完整批（一次调用传入两条映射，D2 推荐顺序 r2
    先于 r1 —— r2 条目在前、r1 条目在后）执行一次
    ``migrate_data(root, mapping_items)`` 时：
    1. 创建并保留两个正式 release（data/releases/data-v4.1-r2/ 与
       data/releases/data-v4.1-r1/，payload 各与自身 legacy 源逐文件
       字节一致，目标内容恰为 release.yaml + 各自 manifest files[]
       声明的 payload 文件集合）；
    2. r2 为 active（经既有 load_release_metadata 读回；replacement
       不存在，release.yaml 不携带 replacement 键）；
    3. r1 为 superseded，replacement 为映射声明的 data-v4.1-r2 且可
       解析 —— 在目标 root 下解析为既有正式 active r2（replacement 在
       同一次调用内可解析：批内 r2 先行写入后 r1 的 replacement 解析
       必须成功，不得要求 replacement 在调用前已存在，也不得在批内
       悬空）；
    4. ``validate_training_reference`` 对 r2 放行、对 r1 拒绝
       （ReferenceNotAllowed）；
    5. 两份 receipt 均为 committed（八字段契约、双对象凭证互不相同、
       两处哈希独立复算核实）；
    6. 目标根恰有两个 release（data/releases/ 恰含 data-v4.1-r1 与
       data-v4.1-r2）和两份 receipt（migration_receipts/ 恰含两份
       receipt）；
    7. 未映射 sibling（v4.1.0-0a1b2c3d4e5f，不在映射批内）不被转换；
    8. legacy 源和旧 pointers 不变（workspace/、finetune/、pipeline/
       子树逐字节不变；旧指针仍声明 legacy 身份）；
    9. 本切片不做中断恢复、凭证失配、重跑幂等（批内乱序输入
       （r1 先于 r2）的写入顺序行为不绑定）。

    fixture：复用 T11 双对象 data fixture（三份 legacy release + 旧
    数据 / Prompt 活动指针，两条映射来自 _confirmed_data_mapping_items，
    r2 在前 —— D2 推荐顺序）+ T15/T16 同款 counts 场景注入（r2 注入
    published_candidates 7、r1 注入 11，与 payload 可复算值 3 互相不同
    —— 双对象批内语义溯源可观察：从 payload 重算或对象间读错源
    （r1 取 r2 manifest、r2 取 r1 manifest）必被捕获；共享写入口径对
    两对象真实可达 —— fixture 基线 manifest 无 counts.splits，不注入
    则正确实现也会在写入前被无关门拒绝，测试永远无法 GREEN）。注入只
    改 counts：files[] 声明哈希不动（T14 门保持绿）；r2 指针
    expected_manifest_sha256 随注入后 manifest 字节复算更新（T13 钉扎
    门保持绿）；r1 无钉扎（M0 pinned_by: ~），无需改写指针。

    RED Gate 设计说明（T17）：migrate_data 入口与 DataMigrationBlocked
    拒绝通道均已存在（T15/T16 既有），且当前 production 的批级实现
    （precheck 整批通过后按映射序逐对象写入 + superseded 写入前
    replacement 在目标 root 内解析）若已满足本切片终态，则本测试为
    Unexpected PASS（转为双对象批终态回归钉），不得为此制造无意义
    production 修改；若实现拒绝或失败，本测试把该拒绝/失败转成显式
    行为 AssertionError 钉出"双对象批转换终态行为缺失"（原始异常经
    cause 链保留，不得直接充当 RED 结论）。

    捕获的合理但错误实现：
    - 批级实现只处理首条映射（或单条映射）：r1 的正式 release /
      receipt 缺失 -> 存在性与精确内容断言失败；
    - precheck 阶段要求 replacement 在调用前已存在（把 T16 的"写入前
      replacement 解析"错误前移到整批预检）：空目标根上的双对象批整批
      blocked -> 前置事实 precheck-ready 断言失败；
    - 批内不保证 r2 先于 r1 写入（按任意顺序但 r1 的 replacement 解析
      发生在 r2 写入前 / 或批内对象间互相污染）-> r1 转换被拒或悬空
      -> 显式行为 AssertionError；
    - receipt 双对象串写（两份 receipt 同 operation_id / 哈希取错源
      / r1 receipt 携带 r2 身份字段）-> 逐 receipt 字段与互不相同断言
      失败；
    - 语义字段从 payload 重算或对象间读错源（r1 与 r2 注入声明值故意
      不同）-> sample_count / splits 比对失败；
    - 转换未映射 sibling（扫描全 releases 目录而非按映射定位）->
      data/releases/ 精确内容断言失败；
    - 转换触碰 legacy 源或旧 active pointers -> 子树逐字节比对失败；
    - 写 records/ / 生命周期目录 / .dvc / 就地修改映射项 -> 对应断言
      失败。

    Binding（证据绑定，供复跑核对）：
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_dual_object_batch_creates_both_releases_and_committed_receipts``
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：双对象布局 + r2/r1 counts 场景注入 + 指针哈希随注入
    #      重写（T15/T16 同款：两对象的共享写入口径真实可达，双对象批
    #      内语义溯源可观察）。----
    _write_legacy_data_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items

    r2_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r2_manifest["counts"] = {
        "published_candidates": 7,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 5,
            "fold_0_val": 2,
            "fold_1_train": 6,
            "fold_1_val": 4,
            "fold_2_train": 7,
            "fold_2_val": 1,
        },
    }
    r2_manifest_bytes = _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R2, r2_manifest
    )
    pointer = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        r2_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(tmp_path, pointer)

    r1_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).read_text(
            encoding="utf-8"
        )
    )
    r1_manifest["counts"] = {
        "published_candidates": 11,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 9,
            "fold_0_val": 4,
            "fold_1_train": 8,
            "fold_1_val": 2,
            "fold_2_train": 10,
            "fold_2_val": 3,
        },
    }
    _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R1, r1_manifest
    )

    # ---- fixture 前置事实（注入自洽 + 区分力 + D1/D2 镜像 + 目标根空闲）----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    # 注入区分力：r1 声明值 11、r2 声明值 7、payload 可复算值 3 互不相
    # 同 —— 双对象批内"语义字段取各自 manifest 声明值（不重算、不读错
    # 源、对象间不串写）"可观察。
    r1_payload_candidates = json.loads(
        _payload_file_of(
            tmp_path,
            CONFIRMED_DATA_SOURCE_R1,
            "metadata/training_candidates.json",
        ).read_text(encoding="utf-8")
    )
    assert len(r1_payload_candidates["candidates"]) == 3, (
        "fixture 前置事实失败：r1 payload 候选数应为 3（注入区分力的"
        "payload 侧事实）"
    )
    r1_fold_0_train = json.loads(
        _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, "datasets/train/fold_0.json"
        ).read_text(encoding="utf-8")
    )
    assert len(r1_fold_0_train["samples"]) == 3, (
        "fixture 前置事实失败：r1 payload fold 文件样本数应为 3"
    )
    assert r1_manifest["counts"]["published_candidates"] != len(
        r1_payload_candidates["candidates"]
    ), "fixture 前置事实失败：r1 注入声明值必须与 payload 可复算值不同"
    assert r2_manifest["counts"]["published_candidates"] != len(
        r1_payload_candidates["candidates"]
    ), "fixture 前置事实失败：r2 注入声明值必须与 payload 可复算值不同"
    assert r1_manifest["counts"]["published_candidates"] != (
        r2_manifest["counts"]["published_candidates"]
    ), (
        "fixture 前置事实失败：r1 与 r2 注入声明值必须不同（对象间读错"
        "源可观察）"
    )
    assert r1_manifest["counts"]["splits"]["fold_0_train"] != len(
        r1_fold_0_train["samples"]
    ), "fixture 前置事实失败：r1 注入 splits 声明值必须与 payload 可复算值不同"
    # D2 推荐顺序：批内 r2 在前、r1 在后（一次调用传入两条映射）。
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    # D1 镜像：r2 active（不携带 replacement）；r1 superseded +
    # replacement=data-v4.1-r2。
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded"
        "（D1 用户确认）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2"
        "（D1 用户确认）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )

    # 前置事实：空目标根上的双对象批整批 precheck ready —— precheck 不
    # 得要求 replacement 在调用前已存在（T16 的"写入前 replacement 解
    # 析"不得被错误前移到整批预检）；migrate_data 的任何拒绝/失败只能
    # 由写入阶段的行为归因。
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（当前 behavior 未实现）"
    )
    dual_precheck_report = precheck(tmp_path, mapping_items)
    assert dual_precheck_report.status == "ready", (
        "fixture 前置事实失败：双对象映射批（r2+r1，D2 推荐顺序）的只读"
        f"预检必须整批 ready（实际 {dual_precheck_report.status!r}，"
        f"reasons={dual_precheck_report.reasons!r}）—— 空目标根上不得"
        "要求 replacement 预先存在"
    )

    before = _snapshot_tree(tmp_path)

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（当前 behavior 未实现）"
    )

    # ---- 行为：一次调用传入两条映射（D2 推荐顺序 r2 先于 r1）。----
    # RED Gate：当前 production 若拒绝或失败，本用例把该拒绝/失败转成
    # 显式行为 AssertionError 钉出"双对象批转换终态行为缺失"，原始异常
    # 经 cause 链保留，不得直接充当 RED 结论；若当前实现已满足，本用例
    # 为 Unexpected PASS（双对象批终态回归钉）。
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "双对象批转换终态行为缺失：migrate_data 对 precheck-ready 的"
            "双对象映射批（r2 active + r1 superseded/replacement="
            f"{CONFIRMED_DATA_TARGET_R2}，D2 推荐顺序 r2 先于 r1）在真实"
            "转换阶段拒绝或失败（本切片要求一次调用创建两个正式 release"
            " 与两份 committed receipt；原始异常经 cause 链保留）：{exc!r}"
        ) from exc

    # 1：创建并保留两个正式 release；payload 与各自 legacy 源逐文件
    #    字节一致（目标内容恰为 release.yaml + 各自 manifest files[]
    #    声明的 payload 文件集合，不夹带非最小行为文件）。
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r1_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    assert r2_release_dir.is_dir(), (
        f"双对象批真实转换必须在目标 root 下创建正式 release：{r2_release_dir}"
    )
    assert r1_release_dir.is_dir(), (
        f"双对象批真实转换必须在目标 root 下创建正式 release：{r1_release_dir}"
    )
    r2_content = _release_content_files(r2_release_dir)
    r1_content = _release_content_files(r1_release_dir)

    r2_declared_payload_paths = sorted(
        entry["path"] for entry in r2_manifest["files"]
    )
    assert set(r2_content) == {"release.yaml"} | set(
        r2_declared_payload_paths
    ), (
        "r2 目标 release 内容必须恰为 release.yaml + r2 legacy manifest "
        f"声明的 payload 文件集合：实际 {sorted(r2_content)}"
    )
    r2_legacy_release_root = (
        tmp_path / "workspace" / "data" / "releases" / CONFIRMED_DATA_SOURCE_R2
    )
    for relative in r2_declared_payload_paths:
        legacy_bytes = (r2_legacy_release_root / relative).read_bytes()
        assert r2_content[relative] == legacy_bytes, (
            f"r2 目标 payload 文件 {relative} 必须与 legacy 源逐字节一致"
            f"（fixture 语义：源 SHA-256 为 "
            f"{hashlib.sha256(legacy_bytes).hexdigest()}）"
        )

    r1_declared_payload_paths = sorted(
        entry["path"] for entry in r1_manifest["files"]
    )
    assert set(r1_content) == {"release.yaml"} | set(
        r1_declared_payload_paths
    ), (
        "r1 目标 release 内容必须恰为 release.yaml + r1 legacy manifest "
        f"声明的 payload 文件集合：实际 {sorted(r1_content)}"
    )
    r1_legacy_release_root = (
        tmp_path / "workspace" / "data" / "releases" / CONFIRMED_DATA_SOURCE_R1
    )
    for relative in r1_declared_payload_paths:
        legacy_bytes = (r1_legacy_release_root / relative).read_bytes()
        assert r1_content[relative] == legacy_bytes, (
            f"r1 目标 payload 文件 {relative} 必须与 legacy 源逐字节一致"
            f"（fixture 语义：源 SHA-256 为 "
            f"{hashlib.sha256(legacy_bytes).hexdigest()}）"
        )

    # 2：r2 为 active（经既有读取/校验语义读回；replacement 不存在），
    #    语义字段取 r2 manifest 声明值（注入值 7 —— 与 r1 注入值 11、
    #    payload 可复算值 3 均不同，对象间读错源必被捕获）。
    r2_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    assert r2_meta.version == CONFIRMED_DATA_TARGET_R2, (
        f"r2 release.yaml 的 version 必须为 {CONFIRMED_DATA_TARGET_R2!r}"
        f"（新体系完整身份，不得沿用 legacy 哈希身份）：实际 "
        f"{r2_meta.version!r}"
    )
    assert r2_meta.status is DataStatus.ACTIVE, (
        f"r2 release.yaml 的 status 必须为 active（映射 target_status，D1）"
        f"：实际 {r2_meta.status!r}"
    )
    assert r2_meta.replacement is None, (
        "active r2 不得携带 replacement（replacement 仅 superseded 时允许）"
    )
    r2_release_raw = yaml.safe_load(r2_content["release.yaml"])
    assert isinstance(r2_release_raw, dict), (
        "r2 release.yaml 顶层必须是映射"
    )
    assert r2_release_raw["status"] == "active", (
        "r2 release.yaml 的原始 status 字段必须为 active：实际 "
        f"{r2_release_raw.get('status')!r}"
    )
    assert "replacement" not in r2_release_raw, (
        "active r2 的 release.yaml 不得残留 replacement 键"
    )
    assert r2_meta.protocol == r2_manifest["contract_version"], (
        "r2 release.yaml 的 protocol 必须取 r2 legacy manifest 的 "
        f"contract_version 声明值 {r2_manifest['contract_version']!r}："
        f"实际 {r2_meta.protocol!r}"
    )
    assert r2_meta.purpose == "development", (
        "legacy 训练 release（manifest status training_ready）的正式映射 "
        f"purpose 必须为 development：实际 {r2_meta.purpose!r}"
    )
    assert r2_meta.training_allowed is True, (
        "development 训练 release 的 training_allowed 必须为 true：实际 "
        f"{r2_meta.training_allowed!r}"
    )
    assert r2_meta.sample_count == (
        r2_manifest["counts"]["published_candidates"]
    ), (
        "r2 sample_count 必须取 r2 legacy manifest counts."
        f"published_candidates 声明值 "
        f"{r2_manifest['counts']['published_candidates']}，不得从 payload "
        "重算或读错源（fixture 注入的声明值与 payload 可复算值、r1 注入"
        "声明值故意不同）"
    )
    expected_r2_splits = {
        f"fold_{fold}": {
            "train": r2_manifest["counts"]["splits"][f"fold_{fold}_train"],
            "validation": r2_manifest["counts"]["splits"][f"fold_{fold}_val"],
        }
        for fold in range(3)
    }
    assert dict(r2_meta.splits) == expected_r2_splits, (
        "r2 splits 必须取 r2 legacy manifest counts.splits 声明值"
        "（fold_N_train -> train、fold_N_val -> validation），不得从 "
        "payload 重算或读错源（fixture 注入的声明值与 payload 可复算值、"
        f"r1 注入声明值故意不同）：实际 {dict(r2_meta.splits)!r}"
    )
    assert set(r2_meta.source_batches) == {
        r2_manifest["source_review_batch_id"],
        r2_manifest["source_queue_id"],
        r2_manifest["source_media_id"],
    }, (
        "r2 source_batches 必须记录 r2 legacy manifest 声明的原始批次标识"
        f"（不回填伪造、不读错源）：实际 {sorted(r2_meta.source_batches)}"
    )

    # 3：r1 为 superseded，replacement 为映射声明的 data-v4.1-r2 且可解
    #    析 —— 在目标 root 下解析为既有正式 active r2（同一次调用内可
    #    解析，不得悬空）；语义字段取 r1 manifest 声明值（注入值 11）。
    r1_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        f"r1 release.yaml 的 version 必须为 {CONFIRMED_DATA_TARGET_R1!r}"
        f"（新体系完整身份，不得沿用 legacy 哈希身份）：实际 "
        f"{r1_meta.version!r}"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        "r1 release.yaml 的 status 必须为 superseded（映射 target_status，"
        f"D1 用户确认）：实际 {r1_meta.status!r}"
    )
    assert r1_meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        "r1 release.yaml 的 replacement 必须为映射声明的 "
        f"{CONFIRMED_DATA_TARGET_R2!r}（D1 用户确认）：实际 "
        f"{r1_meta.replacement!r}"
    )
    r1_release_raw = yaml.safe_load(r1_content["release.yaml"])
    assert isinstance(r1_release_raw, dict), (
        "r1 release.yaml 顶层必须是映射"
    )
    assert r1_release_raw["status"] == "superseded", (
        "r1 release.yaml 的原始 status 字段必须为 superseded：实际 "
        f"{r1_release_raw.get('status')!r}"
    )
    assert r1_release_raw["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "r1 release.yaml 必须携带 replacement 键且值为 data-v4.1-r2：实际 "
        f"{r1_release_raw.get('replacement')!r}"
    )
    replacement_meta = load_release_metadata(
        tmp_path / "data", r1_meta.replacement
    )
    assert replacement_meta.version == CONFIRMED_DATA_TARGET_R2, (
        "superseded r1 的 replacement 必须可解析：在目标 root 下解析为"
        f"既有正式对象 {CONFIRMED_DATA_TARGET_R2!r}（同一次调用内写入的 "
        "r2，不得要求调用前已存在，也不得悬空）：实际解析为 "
        f"{replacement_meta.version!r}"
    )
    assert replacement_meta.status is DataStatus.ACTIVE, (
        "superseded r1 的 replacement 必须解析为既有正式 active r2（不得"
        f"是悬空引用或非 active 对象）：实际 status={replacement_meta.status!r}"
    )
    assert r1_meta.protocol == r1_manifest["contract_version"], (
        "r1 release.yaml 的 protocol 必须取 r1 legacy manifest 的 "
        f"contract_version 声明值 {r1_manifest['contract_version']!r}："
        f"实际 {r1_meta.protocol!r}"
    )
    assert r1_meta.purpose == "development", (
        "legacy 训练 release（manifest status training_ready）的正式映射 "
        f"purpose 必须为 development：实际 {r1_meta.purpose!r}"
    )
    assert r1_meta.training_allowed is True, (
        "development 训练 release 的 training_allowed 必须为 true（拒绝新"
        "引用只能由 superseded 状态归因，不得伪造成不可训练语义）：实际 "
        f"{r1_meta.training_allowed!r}"
    )
    assert r1_meta.sample_count == (
        r1_manifest["counts"]["published_candidates"]
    ), (
        "r1 sample_count 必须取 r1 legacy manifest counts."
        f"published_candidates 声明值 "
        f"{r1_manifest['counts']['published_candidates']}，不得从 payload "
        "重算、伪造或读错源（fixture 注入的声明值与 payload 可复算值、r2 "
        "注入声明值故意不同）"
    )
    expected_r1_splits = {
        f"fold_{fold}": {
            "train": r1_manifest["counts"]["splits"][f"fold_{fold}_train"],
            "validation": r1_manifest["counts"]["splits"][f"fold_{fold}_val"],
        }
        for fold in range(3)
    }
    assert dict(r1_meta.splits) == expected_r1_splits, (
        "r1 splits 必须取 r1 legacy manifest counts.splits 声明值"
        "（fold_N_train -> train、fold_N_val -> validation），不得从 "
        "payload 重算或读错源（fixture 注入的声明值与 payload 可复算值、"
        f"r2 注入声明值故意不同）：实际 {dict(r1_meta.splits)!r}"
    )
    assert set(r1_meta.source_batches) == {
        r1_manifest["source_review_batch_id"],
        r1_manifest["source_queue_id"],
        r1_manifest["source_media_id"],
    }, (
        "r1 source_batches 必须记录 r1 legacy manifest 声明的原始批次标识"
        f"（不回填伪造、不读错源）：实际 {sorted(r1_meta.source_batches)}"
    )

    # 4：训练引用门 —— active r2 放行，superseded r1 拒绝新引用
    #    （ReferenceNotAllowed）。
    validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    with pytest.raises(ReferenceNotAllowed):
        validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)

    # 5：两份 receipt 均为 committed（八字段契约、两处哈希独立复算核实、
    #    双对象凭证互不相同 —— 每对象一份独立 receipt，不得串写）。
    r2_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    r1_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    assert r2_receipt_file.is_file(), (
        "双对象批真实转换必须在目标对象完整写入并验证后创建 r2 "
        f"committed receipt：{r2_receipt_file}"
    )
    assert r1_receipt_file.is_file(), (
        "双对象批真实转换必须在目标对象完整写入并验证后创建 r1 "
        f"committed receipt：{r1_receipt_file}"
    )
    r2_receipt = yaml.safe_load(r2_receipt_file.read_text(encoding="utf-8"))
    r1_receipt = yaml.safe_load(r1_receipt_file.read_text(encoding="utf-8"))
    for receipt, identity, source_id, mapping, content in (
        (
            r2_receipt,
            CONFIRMED_DATA_TARGET_R2,
            CONFIRMED_DATA_SOURCE_R2,
            r2_mapping,
            r2_content,
        ),
        (
            r1_receipt,
            CONFIRMED_DATA_TARGET_R1,
            CONFIRMED_DATA_SOURCE_R1,
            r1_mapping,
            r1_content,
        ),
    ):
        assert isinstance(receipt, dict), (
            "migration receipt 必须是 YAML 顶层映射"
        )
        assert set(receipt) == set(_RECEIPT_FIELDS), (
            "receipt 键集必须恰为八字段契约（operation_id / "
            "source_legacy_id / target_identity / target_path / "
            "source_manifest_sha256 / target_release_digest / status / "
            f"written_at，不夹带映射项 dump 或其他非契约字段）：实际 "
            f"{sorted(receipt)}"
        )
        assert isinstance(receipt["operation_id"], str) and receipt[
            "operation_id"
        ], (
            "receipt.operation_id 必须是非空字符串（本切片不绑定其格式；"
            "凭证绑定与重跑跳过逻辑留待后续切片）"
        )
        assert receipt["source_legacy_id"] == source_id, (
            f"receipt.source_legacy_id 必须为 {source_id!r}：实际 "
            f"{receipt['source_legacy_id']!r}"
        )
        assert receipt["target_identity"] == identity, (
            f"receipt.target_identity 必须为 {identity!r}：实际 "
            f"{receipt['target_identity']!r}"
        )
        assert receipt["target_path"] == mapping["target_path"], (
            "receipt.target_path 必须与映射项声明的 target_path 一致：实际 "
            f"{receipt['target_path']!r}"
        )
        assert receipt["source_manifest_sha256"] == hashlib.sha256(
            _manifest_file_of(tmp_path, source_id).read_bytes()
        ).hexdigest(), (
            f"receipt.source_manifest_sha256 必须与 {source_id!r} legacy 源"
            " manifest 文件字节哈希一致（文件字节口径，非 canonical JSON / "
            "目录哈希 / 声明值自比；下方全树快照保证该字节与转换前一致）"
        )
        assert receipt["target_release_digest"] == (
            _recompute_target_release_digest(content)
        ), (
            f"receipt.target_release_digest 必须能由 {identity!r} 目标 "
            "release 内容按 T15 钉定口径复算验证（目标全部文件按相对 "
            "POSIX 路径升序拼接 <rel>/<sha256> 行后的整体 SHA-256）；"
            "digest 绑定半成品快照、串写另一对象内容或漏算文件的实现必"
            "被捕获"
        )
        assert receipt["status"] == "committed", (
            f"receipt.status 必须为 committed：实际 {receipt['status']!r}"
        )
        assert isinstance(receipt["written_at"], str) and receipt["written_at"], (
            "receipt.written_at 必须是非空字符串（本切片不绑定精确值与格式）"
        )
    # 双对象凭证互不相同：每对象一份独立 receipt（operation_id 与
    # target_release_digest 均不得跨对象串写/复用）。
    assert r2_receipt["operation_id"] != r1_receipt["operation_id"], (
        "双对象批内两份 receipt 的 operation_id 必须互不相同（每对象一份"
        "独立凭证，不得串写）"
    )
    assert (
        r2_receipt["target_release_digest"] != r1_receipt["target_release_digest"]
    ), (
        "双对象批内两份 receipt 的 target_release_digest 必须互不相同"
        "（各自绑定自身目标内容）"
    )

    # 6：目标根恰有两个 release 和两份 receipt（不夹带未映射 sibling
    #    的目标条目/凭证，无任何第三对象）。
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "data/releases/ 必须恰含批内两个正式对象 data-v4.1-r1 与 "
        "data-v4.1-r2（不夹带未映射 sibling 或任何第三对象）"
    )
    receipts_root = tmp_path / "migration_receipts"
    assert [
        entry.name for entry in sorted(receipts_root.iterdir())
    ] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        "migration_receipts/ 必须恰含批内两份 receipt（不得夹带批外凭证）"
    )

    # 7：未映射 sibling 不被转换（实现必须按映射项定位源与目标，不得
    #    扫描全 releases 目录把 sibling 一并转换；sibling 的 legacy 源
    #    逐字节不变由第 8 项 legacy 快照钉定）。
    assert not (
        tmp_path / "data" / "releases" / UNMAPPED_DATA_SIBLING
    ).exists(), (
        "未映射 sibling release 不得被转换（不得在 data/releases/ 下产生"
        f"任何 {UNMAPPED_DATA_SIBLING!r} 相关目标条目）"
    )
    assert not any(
        UNMAPPED_DATA_SIBLING in receipt_name
        for receipt_name in (
            r2_receipt_file.name,
            r1_receipt_file.name,
        )
    ), "未映射 sibling 不得产生任何 receipt"

    # 8：legacy 源和旧 pointers 不变（workspace/、finetune/、pipeline/
    #    子树逐字节不变；旧指针仍声明 legacy 身份，不得被切换到新身份）；
    #    新增条目只允许落在两个目标 release 目录子树与两份 receipt；
    #    不写 records、不触发 DVC、不就地修改传入映射项。
    after = _snapshot_tree(tmp_path)
    for subtree in ("workspace/", "finetune/", "pipeline/"):
        before_subtree = {
            key: value for key, value in before.items() if key.startswith(subtree)
        }
        after_subtree = {
            key: value for key, value in after.items() if key.startswith(subtree)
        }
        assert after_subtree == before_subtree, (
            f"双对象批真实转换不得改动 {subtree} 子树（legacy 源与旧 "
            "active pointers 逐字节不变；不改写、不规范化、不去写位）"
        )
    data_pointer_after = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_after["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "旧数据活动指针必须仍声明 legacy 身份，不得被切换到新身份"
    )
    prompt_pointer_after = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_after["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "旧 Prompt 活动指针必须仍声明 legacy revision_id"
    )
    new_keys = set(after) - set(before)
    r1_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R1}"
    r2_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R2}"
    r1_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r2_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    assert all(
        key == "data"
        or key == "data/releases"
        or key == r1_release_root_rel
        or key == r2_release_root_rel
        or key.startswith(f"{r1_release_root_rel}/")
        or key.startswith(f"{r2_release_root_rel}/")
        or key == "migration_receipts"
        or key == r1_receipt_rel
        or key == r2_receipt_rel
        for key in new_keys
    ), (
        "双对象批真实转换只允许新增两个目标 release 目录子树（含目录"
        f"条目）与两份 receipt：实际新增 {sorted(new_keys)}"
    )
    assert not set(before) - set(after), (
        "双对象批真实转换不得删除/移动任何既有条目（legacy 源与旧 "
        "active pointers）"
    )
    for key, value in before.items():
        assert after[key] == value, (
            f"双对象批真实转换不得改动既有条目 {key!r}（legacy 源与旧 "
            "active pointers 逐字节不变；不改写、不规范化、不去写位）"
        )
    before_top_levels = {key.split("/", 1)[0] for key in before}
    after_top_levels = {key.split("/", 1)[0] for key in after}
    assert after_top_levels - before_top_levels == {
        "data",
        "migration_receipts",
    }, (
        "双对象批真实转换只允许新增目标 data 根与 receipt 目录（目标数据"
        "根必须以可注入 root 表示；本用例只传 pytest tmp_path，不触碰真实"
        f"/data）：实际新增 {sorted(after_top_levels - before_top_levels)}"
    )
    for forbidden in (
        "records",
        "working",
        "release_staging",
        "data/working",
        "data/release_staging",
    ):
        assert not (tmp_path / forbidden).exists(), (
            f"双对象批真实转换不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in after), (
        "双对象批真实转换不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    assert ".gitignore" not in after_top_levels, (
        "双对象批真实转换不得创建或改写 .gitignore（DVC 接入不在本切片）"
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "双对象批真实转换不得就地改写传入映射项（M0 事实分级保持不变）"
    )


# ---------------------------------------------------------------------------
# T18：完成态批级重跑幂等跳过 —— 双对象批完整转换后，同 root、同映射、
# 同 legacy 源的第二次 migrate_data 调用必须成功并对已完成的 r1/r2 跳过：
# 零重写、receipt written_at 不变、无新身份（D2 已确认语义；先写测试，
# 不改 production）
# ---------------------------------------------------------------------------


def _snapshot_target_side_mtime_ns(root: Path) -> dict[str, int]:
    """目标侧（data/ 与 migration_receipts/ 子树全部条目）的 mtime_ns 快照。

    完成态重跑“无重写”的次级可观察判据：幂等跳过不写任何字节、不触碰
    任何元数据；“逐字节重写同一内容”在字节层与快照不可区分，但重写
    必然更新 mtime（receipt 侧另有 written_at 双保险；payload 已按
    T15-P2-1 封存去写位 0o444，重写会直接 PermissionError）。
    """
    snapshot: dict[str, int] = {}
    for subtree in ("data", "migration_receipts"):
        subtree_root = root / subtree
        snapshot[subtree] = subtree_root.stat().st_mtime_ns
        for path in sorted(subtree_root.rglob("*")):
            snapshot[
                path.relative_to(root).as_posix()
            ] = path.stat().st_mtime_ns
    return snapshot


def test_migrate_data_completed_dual_object_batch_rerun_skips_completed_objects_idempotently(
    tmp_path: Path,
) -> None:
    r"""完成态批级重跑：双对象批完整转换后再次调用同一 migrate_data 幂等跳过。

    T18 behavior（本切片，主 Agent 选定，先写测试，不改 production）——
    D2 已确认：中断/重跑同一次转换时，凭证匹配的已完成对象跳过，未完成
    对象继续；完成态重跑应幂等，不覆盖、不改号。本切片钉完成态批级重跑
    （批内两对象均已完成）：复用 T17 双对象 fixture 完整执行一次双对象
    批转换后，使用相同 root、相同映射、相同 legacy 源再次调用同一
    ``migrate_data(root, mapping_items)`` 时：
    1. 调用必须成功 —— 不得把已有 r1/r2 正式对象与 receipt 当成外来
       冲突而拒绝（当前实现的 precheck 目标冲突门会把已完成的
       data-v4.1-r1/r2 判为冲突并以 DataMigrationBlocked 拒绝，即本
       切片 RED 起点）；
    2. 两个对象都识别为已完成并跳过 —— 可观察判据：第二次调用前后
       目标侧零变化（下方 3/4/5 与全树快照、mtime、权限位断言），
       “跳过”不写任何字节；
    3. ``data/releases/data-v4.1-r1`` 与 ``data-v4.1-r2`` 内容逐字节
       不变（目标子树逐文件字节比对 + 全树快照）；
    4. 两份 receipt 内容逐字节不变，``written_at`` 不变（重跑不得刷新
       凭证时间戳或重算 digest），status 仍为 committed；
    5. 不产生 ``data-v4.1-r3`` 或其他新身份（data/releases/ 恰含 r1、
       r2 两个正式对象；migration_receipts/ 恰含两份 receipt；全树无
       任何新增/删除条目）；
    6. legacy 源和旧 pointers 不变（workspace/、finetune/、pipeline/
       子树逐字节不变；旧指针仍声明 legacy 身份，不得被切换）；
    7. 本切片不做中断恢复（批内存在未完成对象时的“继续”语义）、凭
       证失配（跳过判定的凭证不匹配分支）、migrate_data 返回值契约
       （T15 起不绑定，跳过时返回什么不绑定）与跳过报告通道（跳过
       是否/如何向调用方报告不绑定 —— 但不得写盘）。

    “识别为已完成并跳过”的绑定方式（行为项 2）：完成态重跑的零变化是
    可观察事实 —— 两个目标 release 子树与两份 receipt 在第二次调用前
    后逐字节一致（含 written_at），目标侧全部条目 mtime_ns 与权限位不
    变。“逐字节重写同一内容”无法从字节层区分，故辅以 mtime_ns 钉定
    （重写必然更新 mtime；receipt 重写则 written_at/mtime 双重暴露）；
    payload 已按 T15-P2-1 封存去写位（0o444），重写还会直接
    PermissionError。

    fixture：复用 T17 双对象 fixture（``_write_legacy_data_layout`` 三
    份 legacy release + 旧数据/Prompt 活动指针 + 两条映射来自
    ``_confirmed_data_mapping_items``，D2 推荐顺序 r2 先于 r1）+
    T15/T16 同款 counts 场景注入与指针 manifest 哈希随注入重写（不注
    入则 production 共享写入口径 ``_derive_release_splits`` 在写入前
    因 counts.splits 缺失拒绝，第一次转换无法完成，测试到不了完成态
    重跑点）；注入值与 T17 完全一致（r2 published_candidates 7、r1 为
    11），使两切片在同一事实基线上叠加。

    RED Gate 设计说明（T18）：migrate_data 入口、DataMigrationBlocked
    拒绝通道与 T17 双对象批终态均已存在（第一次完整转换成功是 fixture
    前置事实，失败即 T17 回归而非本切片 RED），RED 不经入口缺失分支
    给出 —— 当前 production 的 precheck_data_migration 对已完成 r1/r2
    命中目标冲突门（目标条目已存在 + data 正式对象根同身份条目），
    migrate_data 以 DataMigrationBlocked 拒绝第二次调用，把已完成的
    正式对象当成外来冲突；本用例把该拒绝转成显式行为 AssertionError
    钉出“完成态批级重跑幂等跳过行为缺失”（原始 DataMigrationBlocked
    经 cause 链保留，不得直接充当 RED 结论）；若当前实现已满足（调用
    成功 + 零变化），本用例为 Unexpected PASS（完成态重跑幂等回归钉），
    不得为此制造无意义 production 修改。

    捕获的合理但错误实现：
    - 当前 production（RED 起点）：第二次调用被 precheck 目标冲突门拒
      绝（已完成的 r1/r2 被当外来冲突）-> 显式行为 AssertionError；
    - “重跑即重做”：重写 release/receipt（即使字节恰好相同）->
      receipt written_at 变化 / 目标侧 mtime 变化 / 已封存 payload
      0o444 重写 PermissionError -> 对应断言失败；
    - “冲突即改号”：自动改号到 data-v4.1-r3 等新身份继续转换 ->
      data/releases/ 精确内容断言 + 全树快照零变化断言失败；
    - 只跳过首条/末条映射（另一对象仍被拒或重做）-> 调用失败或快照
      变化断言失败；
    - 重跑顺手触碰 legacy 源或旧 active pointers（切换指针、改写
      manifest/payload）-> 子树逐字节比对失败；
    - 重跑写盘报告/缓存（跳过清单、日志、临时文件）-> 全树快照零变
      化断言失败；就地修改传入映射项 -> 映射项不变断言失败。

    Binding（证据绑定，供复跑核对）：
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_completed_dual_object_batch_rerun_skips_completed_objects_idempotently``
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    - RED failure signature：恰一个失败用例，失败信息为 AssertionError
      “完成态批级重跑幂等跳过行为缺失：migrate_data 对完成态双对象批
      …把已完成的 r1/r2 正式对象当成外来冲突拒绝或失败…”，cause 链
      为原始 DataMigrationBlocked（“data 迁移预检未通过（fail-closed，
      零写入）：目标条目已存在，冲突时停止（不覆盖、不自动改号）：
      data/releases/data-v4.1-r2/release.yaml；data 正式对象根已存在
      同身份条目：data/releases/data-v4.1-r2；…（r1 同构两条）…”）；
      fixture 前置事实（第一次转换成功、两个 release 与两份 committed
      receipt 存在）全部不失败。
    """
    # ---- fixture：双对象布局 + r2/r1 counts 场景注入 + 指针哈希随注入
    #      重写（T17 同款：共享写入口径真实可达，第一次完整转换才能
    #      完成，测试才能到达完成态重跑点）。----
    _write_legacy_data_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items

    r2_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r2_manifest["counts"] = {
        "published_candidates": 7,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 5,
            "fold_0_val": 2,
            "fold_1_train": 6,
            "fold_1_val": 4,
            "fold_2_train": 7,
            "fold_2_val": 1,
        },
    }
    r2_manifest_bytes = _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R2, r2_manifest
    )
    pointer = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        r2_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(tmp_path, pointer)

    r1_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).read_text(
            encoding="utf-8"
        )
    )
    r1_manifest["counts"] = {
        "published_candidates": 11,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 9,
            "fold_0_val": 4,
            "fold_1_train": 8,
            "fold_1_val": 2,
            "fold_2_train": 10,
            "fold_2_val": 3,
        },
    }
    _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R1, r1_manifest
    )

    # ---- fixture 前置事实（注入自洽 + D1/D2 镜像 + 目标根空闲）----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded"
        "（D1 用户确认）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2"
        "（D1 用户确认）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T17 既有行为不可用，本切片 fixture 前置事实"
        "失败）"
    )

    # ---- 行为前提构造：第一次完整双对象批转换（T17 既有行为；完成态
    #      是本切片重跑语义的前提，该处失败是 T17 回归而非本切片 RED）。----
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：当前 migrate_data 必须先成功完成双对"
            "象批的第一次完整转换（T17 既有双对象批终态行为；原始异常经"
            f"cause 链保留）：{exc!r}"
        ) from exc

    # 完成态前置事实：两个正式 release 与两份 committed receipt 均已存
    # 在（批内两对象都已完成 —— 本切片钉完成态批的重跑；未完成对象的
    # “继续”语义不在本切片）。
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r1_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    assert r2_release_dir.is_dir(), (
        "fixture 前置事实失败：r2 正式 release 必须已创建（完成态前提）"
    )
    assert r1_release_dir.is_dir(), (
        "fixture 前置事实失败：r1 正式 release 必须已创建（完成态前提）"
    )
    r2_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    assert r2_meta.version == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r2 必须经既有语义读回为 data-v4.1-r2"
    )
    assert r2_meta.status is DataStatus.ACTIVE, (
        "fixture 前置事实失败：r2 必须经既有语义读回为 active 正式对象"
    )
    r1_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        "fixture 前置事实失败：r1 必须经既有语义读回为 data-v4.1-r1"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        "fixture 前置事实失败：r1 必须经既有语义读回为 superseded 正式"
        "对象"
    )
    r2_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    r1_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：r2 committed receipt 必须已写入（完成态"
        "前提）"
    )
    assert r1_receipt_file.is_file(), (
        "fixture 前置事实失败：r1 committed receipt 必须已写入（完成态"
        "前提）"
    )

    # ---- 捕获完成态基线：全树字节快照 + 目标子树/receipt 字节 +
    #      receipt 解析值（written_at 基线）+ 目标侧 mtime_ns 与权限位
    #      （“无重写”的次级判据）。----
    completed_tree = _snapshot_tree(tmp_path)
    r2_target_content = _release_content_files(r2_release_dir)
    r1_target_content = _release_content_files(r1_release_dir)
    assert "release.yaml" in r2_target_content, (
        "fixture 前置事实失败：r2 目标 release 必须含 release.yaml"
    )
    assert "release.yaml" in r1_target_content, (
        "fixture 前置事实失败：r1 目标 release 必须含 release.yaml"
    )
    r2_receipt_bytes = r2_receipt_file.read_bytes()
    r1_receipt_bytes = r1_receipt_file.read_bytes()
    r2_receipt_baseline = yaml.safe_load(r2_receipt_bytes)
    r1_receipt_baseline = yaml.safe_load(r1_receipt_bytes)
    for identity, receipt_baseline in (
        (CONFIRMED_DATA_TARGET_R2, r2_receipt_baseline),
        (CONFIRMED_DATA_TARGET_R1, r1_receipt_baseline),
    ):
        assert isinstance(receipt_baseline, dict), (
            f"fixture 前置事实失败：{identity} 的 receipt 必须是 YAML 顶层映射"
        )
        assert receipt_baseline.get("status") == "committed", (
            f"fixture 前置事实失败：{identity} 的完成态基线 receipt 必须为 "
            "committed"
        )
        assert isinstance(receipt_baseline.get("written_at"), str) and (
            receipt_baseline["written_at"]
        ), (
            f"fixture 前置事实失败：{identity} 的 receipt.written_at 必须是"
            "非空字符串（重跑不变断言的比对基线）"
        )
    target_side_mtime_baseline = _snapshot_target_side_mtime_ns(tmp_path)
    modes_baseline = _snapshot_modes(tmp_path)

    # ---- 行为：第二次调用同一 migrate_data（相同 root、相同映射批、
    #      相同 legacy 源；完成态批级重跑）。----
    # RED Gate：当前 production 的 precheck 把已完成的 r1/r2 判为目标冲
    # 突（目标条目已存在 + data 正式对象根同身份条目）并以
    # DataMigrationBlocked 拒绝第二次调用 —— 本用例把该拒绝转成显式
    # 行为 AssertionError 钉出“完成态批级重跑幂等跳过行为缺失”，原始
    # 异常经 cause 链保留；若当前实现已满足（调用成功 + 零变化），本
    # 用例为 Unexpected PASS（完成态重跑幂等回归钉）。
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "完成态批级重跑幂等跳过行为缺失：migrate_data 对完成态双对象"
            "批（r2 active + r1 superseded/replacement="
            f"{CONFIRMED_DATA_TARGET_R2}，D2 推荐顺序 r2 先于 r1，第一次完"
            "整转换已成功）的同 root、同映射、同 legacy 源第二次调用把已"
            "完成的 r1/r2 正式对象当成外来冲突拒绝或失败（本切片要求凭"
            "证匹配的已完成对象跳过：调用成功、零重写、零新身份、两份"
            "receipt 及 written_at 逐字节不变；原始异常经 cause 链保留）："
            f"{exc!r}"
        ) from exc

    # ---- 行为项 1+2：调用成功已钉定（不把已有 r1/r2 当外来冲突拒
    #      绝）；跳过的可观察判据是下方零变化断言（无重写即跳过，而非
    #      重做）。----

    # 3/4/5/6：第二次调用后全树零变化 —— 目标子树与 receipt 逐字节不
    # 变、legacy 源与旧 pointers 不变、无任何新增/删除条目（不产生
    # data-v4.1-r3 等新身份、不写跳过报告/缓存/records、不触发 DVC 均
    # 由全树键集与逐键字节比对钉定）。
    rerun_tree = _snapshot_tree(tmp_path)
    assert set(rerun_tree) == set(completed_tree), (
        "完成态批级重跑不得新增或删除任何条目（不产生 data-v4.1-r3 等"
        "新身份、不写跳过报告/缓存/records/生命周期目录、不删除既有条"
        "目）：实际新增 "
        f"{sorted(set(rerun_tree) - set(completed_tree))}，实际删除 "
        f"{sorted(set(completed_tree) - set(rerun_tree))}"
    )
    changed_entries = sorted(
        key
        for key, value in completed_tree.items()
        if rerun_tree[key] != value
    )
    assert not changed_entries, (
        "完成态批级重跑不得改动任何条目（两个目标 release 子树、两份 "
        "receipt、legacy 源与旧 active pointers 逐字节不变）：实际改动 "
        f"{changed_entries}"
    )

    # 3：两个目标 release 子树内容逐字节不变（显式重复全树结论，使该行
    #    为项在失败信息中可读归因）。
    assert _release_content_files(r2_release_dir) == r2_target_content, (
        "完成态批级重跑不得重写 data/releases/data-v4.1-r2（已完成对象"
        "跳过：逐文件字节必须与第一次转换后完全一致）"
    )
    assert _release_content_files(r1_release_dir) == r1_target_content, (
        "完成态批级重跑不得重写 data/releases/data-v4.1-r1（已完成对象"
        "跳过：逐文件字节必须与第一次转换后完全一致）"
    )

    # 4：两份 receipt 内容逐字节不变，written_at 不变（幂等跳过不重写凭
    #    证、不刷新时间戳、不重算 digest），status 仍为 committed。
    assert r2_receipt_file.read_bytes() == r2_receipt_bytes, (
        "完成态批级重跑不得重写 r2 receipt（凭证逐字节不变，含 "
        "written_at）"
    )
    assert r1_receipt_file.read_bytes() == r1_receipt_bytes, (
        "完成态批级重跑不得重写 r1 receipt（凭证逐字节不变，含 "
        "written_at）"
    )
    r2_receipt_after = yaml.safe_load(
        r2_receipt_file.read_text(encoding="utf-8")
    )
    r1_receipt_after = yaml.safe_load(
        r1_receipt_file.read_text(encoding="utf-8")
    )
    for identity, receipt_after, receipt_baseline in (
        (CONFIRMED_DATA_TARGET_R2, r2_receipt_after, r2_receipt_baseline),
        (CONFIRMED_DATA_TARGET_R1, r1_receipt_after, r1_receipt_baseline),
    ):
        assert receipt_after == receipt_baseline, (
            f"{identity} 的 receipt 内容在完成态重跑后必须不变（八字段"
            "逐一相等，不重算 digest、不改身份字段）"
        )
        assert receipt_after["written_at"] == receipt_baseline["written_at"], (
            f"{identity} 的 receipt.written_at 在完成态重跑后必须不变"
            "（幂等跳过不重写凭证；written_at 变化即重跑重做了转换）"
        )
        assert receipt_after["status"] == "committed", (
            f"{identity} 的 receipt.status 在完成态重跑后必须仍为 "
            "committed"
        )

    # 5：无新身份 —— data/releases/ 恰含 r1、r2 两个正式对象（不产生
    #    data-v4.1-r3）；migration_receipts/ 恰含两份 receipt。
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "完成态批级重跑不得产生 data-v4.1-r3 或任何其他新身份/新条目"
        "（不覆盖、不自动改号）：data/releases/ 必须恰含 "
        f"{CONFIRMED_DATA_TARGET_R1} 与 {CONFIRMED_DATA_TARGET_R2}"
    )
    assert not (
        tmp_path / "data" / "releases" / "data-v4.1-r3"
    ).exists(), "完成态批级重跑不得自动改号到 data-v4.1-r3"
    receipts_root = tmp_path / "migration_receipts"
    assert [
        entry.name for entry in sorted(receipts_root.iterdir())
    ] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], "migration_receipts/ 必须恰含 r1 与 r2 两份 receipt（重跑不新增凭证）"

    # 无重写（行为项 2 的次级判据）：目标侧全部条目 mtime_ns 不变 ——
    # “逐字节重写同一内容”在字节层不可区分，mtime 是其可观察痕迹
    # （receipt 侧另有 written_at 双保险；payload 已封存 0o444，重写会
    # 直接 PermissionError）。
    assert _snapshot_target_side_mtime_ns(tmp_path) == (
        target_side_mtime_baseline
    ), (
        "完成态批级重跑不得重写目标侧任何条目（跳过不触碰元数据："
        "data/ 与 migration_receipts/ 子树全部条目 mtime_ns 必须不变；"
        "字节恰好相同的重写也会更新 mtime）"
    )
    # 权限位不变：重跑不得重新封存/改写位（含 legacy 侧与目标侧）。
    assert _snapshot_modes(tmp_path) == modes_baseline, (
        "完成态批级重跑不得改动任何条目权限位（不重新封存、不改写位）"
    )

    # 6：legacy 源和旧 pointers 不变（全树快照已钉定；此处显式钉旧指针
    #    仍声明 legacy 身份，使失败信息可读归因）。
    data_pointer_after = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_after["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "完成态批级重跑不得切换旧数据活动指针（仍声明 legacy 身份）"
    )
    prompt_pointer_after = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_after["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "完成态批级重跑不得切换旧 Prompt 活动指针（仍声明 legacy "
        "revision_id）"
    )

    # 两次调用之间映射批不被就地修改（M0 事实分级保持不变）。
    assert mapping_items == _confirmed_data_mapping_items(), (
        "完成态批级重跑不得就地改写传入映射项（M0 事实分级保持不变）"
    )


# ---------------------------------------------------------------------------
# T18-P2：reviewer 对 T18 的 P2 —— 完成态重跑的 receipt 核实必须绑定
# superseded 映射的 replacement：映射 replacement 变更后不得静默跳过，
# 必须经 DataMigrationBlocked fail-closed 拒绝（先写测试，不改 production）
# ---------------------------------------------------------------------------


# r1 映射 replacement 的变更目标：格式合法的完整 data 身份（kind data、
# 协议 v4.1、revision 9 —— 空目标根上 precheck-ready 的变体），但目标
# root 下不存在该正式对象，且与第一次转换写入的已提交事实
# （r1 release.yaml replacement=data-v4.1-r2）不同。
_CHANGED_R1_REPLACEMENT = "data-v4.1-r9"


def _dual_object_batch_with_changed_r1_replacement() -> list[dict[str, Any]]:
    """双对象映射批的 r1 replacement 变体（与 M0 证据镜像批恰一处不同）。

    逐字段镜像 _confirmed_data_mapping_items（两条已确认映射，D2 推荐
    顺序 r2 先于 r1），唯一差异：r1 条目（superseded）的 replacement
    从 data-v4.1-r2 改为 _CHANGED_R1_REPLACEMENT（data-v4.1-r9）。
    返回全新对象；前置 precheck 对照与行为调用各自独立取用，不经
    production 就地改写互相污染。
    """
    items = _confirmed_data_mapping_items()
    r1_item = items[1]
    assert r1_item["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1, (
        "fixture 前置事实失败：双对象映射批第二位必须是 r1 条目"
        "（D2 推荐顺序 r2 先于 r1）"
    )
    r1_item["replacement"] = _CHANGED_R1_REPLACEMENT
    return items


def test_migrate_data_completed_batch_rerun_with_changed_replacement_fails_closed(
    tmp_path: Path,
) -> None:
    r"""完成态重跑遇 superseded 映射 replacement 变更：fail-closed 拒绝，不得静默跳过。

    T18-P2 behavior（reviewer 对 T18 的 P2，本切片先写测试，不改
    production）—— T18 的完成态幂等跳过以“receipt 核实与当前映射/
    源/目标全部匹配”为前提，但当前核实口径（receipt 逐字段比对 +
    operation_id 派生 payload source/target/status +
    source_manifest_sha256 + target_release_digest）不含 superseded 映射
    的 replacement —— r1 映射 replacement 变更后重跑会静默跳过，映射
    声明与已提交事实（r1 release.yaml replacement=data-v4.1-r2）不符
    的事实不被发现。本切片钉定：复用 T17/T18 双对象 fixture，第一次
    完整双对象批转换（r2 active + r1 superseded/replacement=
    data-v4.1-r2）成功、同映射幂等重跑成功后，仅把 r1 映射的
    replacement 从 data-v4.1-r2 变更为另一完整 data 身份
    data-v4.1-r9（空目标根上 precheck-ready 的格式合法变体 —— 后续
    拒绝不得由身份格式/源/映射结构归因），保持同 root、同 legacy 源，
    再次调用 ``migrate_data(root, mapping_items)`` 时：
    1. 必须经 ``DataMigrationBlocked``（或其子类）fail-closed 拒绝 ——
       不得静默跳过（成功返回即本切片 RED 起点：当前 production 的
       核实不绑定 replacement，r1 变更后整批仍被识别为已完成并跳过）；
    2. 既有两个目标 release 与两份 receipt 逐字节不变（含
       written_at / status committed）—— 拒绝不得覆盖、不得改写、不
       得重算 digest，也不得顺手把 r1 release.yaml 的 replacement 改写
       成新映射值；
    3. 零新增/删除条目：不产生 data-v4.1-r9 / data-v4.1-r3 等新身份
       （data/releases/ 恰含 r1、r2；migration_receipts/ 恰含两份
       receipt；目标侧 mtime 与权限位零变化 —— 无任何重写痕迹）；
    4. legacy 源和旧 pointers 不变（workspace/、finetune/、pipeline/
       子树逐字节不变；旧指针仍声明 legacy 身份）；
    5. 不就地修改传入映射项（原批与变更批都不被 production 改写）；
    6. 拒绝的具体机制（核实口径如何纳入 replacement —— receipt 新
       字段 / operation_id 派生 / 目标 release.yaml 比对）与拒绝信息
       文本不绑定，行为只钉 fail-closed 通道 + 零写入；
    7. 相同 replacement 的正常 T18 重跑仍成功跳过：同映射重跑（本用
       例内的前置对照）与恢复原 replacement 后的重跑（末尾对照）都
       必须成功且零变化 —— 拒绝只能由 replacement 变更归因，不得过
       宽到拒绝一切完成态重跑。

    fixture：复用 T17/T18 双对象 fixture（_write_legacy_data_layout
    三份 legacy release + 旧数据/Prompt 活动指针 + 两条映射来自
    _confirmed_data_mapping_items，D2 推荐顺序 r2 先于 r1）+ T15/T16/
    T17 同款 counts 场景注入与指针 manifest 哈希随注入重写（不注入则
    共享写入口径 _derive_release_splits 在写入前因 counts.splits 缺失
    拒绝，第一次转换无法完成，测试到不了完成态重跑点）；注入值与
    T17/T18 完全一致（r2 published_candidates 7、r1 为 11），使三切片
    在同一事实基线上叠加。

    RED Gate 设计说明（T18-P2）：migrate_data 入口、DataMigrationBlocked
    拒绝通道、T17 双对象批终态与 T18 完成态幂等跳过均已存在（第一次
    完整转换与同映射重跑成功均为 fixture 前置事实，失败即 T17/T18 回
    归而非本切片 RED），RED 不经入口缺失分支给出 —— 当前 production
    的完成态核实不绑定 replacement，r1 映射 replacement 变更
    （data-v4.1-r2 -> data-v4.1-r9）后的第二次 migrate_data 调用静默
    跳过成功返回；本用例把该静默跳过转成显式行为 AssertionError 钉
    出“完成态重跑 receipt 核实未绑定 superseded 映射的 replacement”
    （拒绝通道错位 —— 原始未类型化异常替代 DataMigrationBlocked ——
    同样经显式 AssertionError + cause 链转译，不得直接充当 RED 结论）。

    捕获的合理但错误实现：
    - 当前 production（RED 起点）：核实不含 replacement -> r1 变更后
      整批仍识别为已完成 -> 静默跳过成功返回 -> 显式行为
      AssertionError；
    - 拒绝通道错位：以原始未类型化异常（ValueError / KeyError /
      PermissionError 等）替代 DataMigrationBlocked -> 通道错位
      AssertionError（cause 链保留原始异常）；
    - 拒绝前/拒绝时有写入：改写 release / receipt（即使字节恰好相同
      也更新 mtime）或顺手封存/改权限位 -> 全树快照 / receipt 字节 /
      mtime / 权限位断言失败；
    - 拒绝时顺手“修复”：改写 r1 release.yaml 的 replacement 使其匹配
      新映射 / 重写 receipt -> 零写入断言失败；
    - 自动改号继续转换（把 r1 转成 data-v4.1-r3，或为 data-v4.1-r9
      创建正式对象/凭证）-> data/releases/ 与 migration_receipts/ 精确
      内容 + 全树快照断言失败；
    - 拒绝过宽：一切完成态重跑都被拒（同映射重跑 / 恢复原
      replacement 的重跑也失败）-> 前置对照或末尾对照断言失败（T18
      selector 同步回归可见）；
    - 拒绝归因错位：把变更批在空目标根上判 blocked（要求 replacement
      预先存在等）-> 前置 precheck-ready 断言失败（T17 已钉 precheck
      不要求 replacement 预先存在）；
    - 触碰 legacy 源或旧 active pointers / 就地改写传入映射项 -> 子树
      逐字节比对 / 映射项不变断言失败。

    范围边界（本切片不绑定）：核实纳入 replacement 的具体机制与拒绝信
    息文本；映射其他字段（target_status / target_path /
    source_legacy_id / candidate_target_identity）的完成态失配（已由
    T18 既有核实口径覆盖：receipt 逐字段比对 + operation_id 绑定
    target_status）；receipt 自身字段被篡改的拒绝分支；批内部分完成/
    中断恢复（“继续”语义）；replacement 变更为非法身份格式（预检身份
    门已覆盖）；active 映射携带 replacement 的完成态重跑；CLI、DVC、
    训练机真实路径。

    Binding（证据绑定，供复跑核对）：
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_completed_batch_rerun_with_changed_replacement_fails_closed``
    - RED failure signature：恰一个失败用例（本 selector），失败信息
      为 AssertionError “完成态重跑 receipt 核实未绑定 superseded 映
      射的 replacement（静默跳过）：r1 映射 replacement 从 data-v4.1-r2
      变更为 data-v4.1-r9 后，migrate_data 对完成态双对象批的同
      root、同 legacy 源第二次调用成功返回、未 fail-closed 拒绝 …”；
      fixture 前置事实（变更批空目标根 precheck ready、第一次转换成
      功、完成态基线、同映射重跑成功零变化）全部不失败；T17/T18 既
      有 selector 保持通过。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：双对象布局 + r2/r1 counts 场景注入 + 指针哈希随注入
    #      重写（T17/T18 同款：共享写入口径真实可达，第一次完整转换
    #      才能完成，测试才能到达完成态重跑点）。----
    _write_legacy_data_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items

    r2_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r2_manifest["counts"] = {
        "published_candidates": 7,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 5,
            "fold_0_val": 2,
            "fold_1_train": 6,
            "fold_1_val": 4,
            "fold_2_train": 7,
            "fold_2_val": 1,
        },
    }
    r2_manifest_bytes = _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R2, r2_manifest
    )
    pointer = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        r2_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(tmp_path, pointer)

    r1_manifest = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).read_text(
            encoding="utf-8"
        )
    )
    r1_manifest["counts"] = {
        "published_candidates": 11,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 9,
            "fold_0_val": 4,
            "fold_1_train": 8,
            "fold_1_val": 2,
            "fold_2_train": 10,
            "fold_2_val": 3,
        },
    }
    _rewrite_legacy_release_manifest(
        tmp_path, CONFIRMED_DATA_SOURCE_R1, r1_manifest
    )

    # ---- fixture 前置事实（注入自洽 + D1/D2 镜像 + 目标根空闲）。----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded"
        "（D1 用户确认）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2"
        "（D1 用户确认；本切片的变更基线）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )

    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（T11 既有行为不可用，本切片 "
        "fixture 前置事实失败）"
    )

    # ---- 前置对照（归因隔离）：replacement 变体批在空目标根上整批
    #      precheck ready —— data-v4.1-r9 是格式合法的完整 data 身份
    #      （T17 已钉 precheck 不要求 replacement 预先存在），变体批
    #      在完成态的任何拒绝只能由 receipt 核实归因，不得由身份格式
    #      / 源 / 映射结构归因。----
    variant_items = _dual_object_batch_with_changed_r1_replacement()
    variant_precheck_report = precheck(tmp_path, variant_items)
    assert variant_precheck_report.status == "ready", (
        "fixture 前置事实失败：r1 replacement 变体批（replacement="
        f"{_CHANGED_R1_REPLACEMENT}，格式合法完整 data 身份）在空目标根"
        "上必须整批 precheck ready —— 完成态场景的拒绝只能由 receipt "
        "核实归因，不得由身份格式/源/映射结构归因（实际 "
        f"{variant_precheck_report.status!r}，"
        f"reasons={variant_precheck_report.reasons!r}）"
    )

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T17 既有行为不可用，本切片 fixture 前置事实"
        "失败）"
    )
    blocked_exc = getattr(
        importlib.import_module("versioning.migration"),
        "DataMigrationBlocked",
        None,
    )
    assert blocked_exc is not None, (
        "data 迁移拒绝通道缺失：versioning.migration 未提供 "
        "DataMigrationBlocked（fail-closed 必须经既有迁移拒绝通道给出，"
        "本切片 fixture 前置事实失败）"
    )

    # ---- 行为前提构造：第一次完整双对象批转换（T17 既有行为；完成态
    #      是本切片重跑语义的前提，该处失败是 T17 回归而非本切片 RED）。----
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：当前 migrate_data 必须先成功完成双对"
            "象批的第一次完整转换（T17 既有双对象批终态行为；原始异常经"
            f"cause 链保留）：{exc!r}"
        ) from exc

    # 完成态前置事实：两个正式 release 与两份 committed receipt 均已存
    # 在；r1 已提交事实为 replacement=data-v4.1-r2（本切片变更将偏离的
    # 基线事实）。
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r1_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    assert r2_release_dir.is_dir(), (
        "fixture 前置事实失败：r2 正式 release 必须已创建（完成态前提）"
    )
    assert r1_release_dir.is_dir(), (
        "fixture 前置事实失败：r1 正式 release 必须已创建（完成态前提）"
    )
    r1_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        "fixture 前置事实失败：r1 必须经既有语义读回为 data-v4.1-r1"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        "fixture 前置事实失败：r1 必须经既有语义读回为 superseded 正式"
        "对象"
    )
    assert r1_meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 已提交事实的 replacement 必须为 "
        f"{CONFIRMED_DATA_TARGET_R2!r}（第一次转换写入的 release.yaml "
        "声明值；本切片的变更将偏离该已提交事实）"
    )
    r2_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    r1_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：r2 committed receipt 必须已写入（完成态"
        "前提）"
    )
    assert r1_receipt_file.is_file(), (
        "fixture 前置事实失败：r1 committed receipt 必须已写入（完成态"
        "前提）"
    )

    # ---- 捕获完成态基线：全树字节快照 + 目标子树/receipt 字节 +
    #      receipt 解析值（written_at 基线）+ 目标侧 mtime_ns 与权限位。----
    completed_tree = _snapshot_tree(tmp_path)
    r2_content_baseline = _release_content_files(r2_release_dir)
    r1_content_baseline = _release_content_files(r1_release_dir)
    assert "release.yaml" in r2_content_baseline, (
        "fixture 前置事实失败：r2 目标 release 必须含 release.yaml"
    )
    assert "release.yaml" in r1_content_baseline, (
        "fixture 前置事实失败：r1 目标 release 必须含 release.yaml"
    )
    r2_receipt_bytes = r2_receipt_file.read_bytes()
    r1_receipt_bytes = r1_receipt_file.read_bytes()
    receipt_baselines = {
        CONFIRMED_DATA_TARGET_R2: yaml.safe_load(r2_receipt_bytes),
        CONFIRMED_DATA_TARGET_R1: yaml.safe_load(r1_receipt_bytes),
    }
    for identity, receipt_baseline in receipt_baselines.items():
        assert isinstance(receipt_baseline, dict), (
            f"fixture 前置事实失败：{identity} 的 receipt 必须是 YAML 顶层映射"
        )
        assert receipt_baseline.get("status") == "committed", (
            f"fixture 前置事实失败：{identity} 的完成态基线 receipt 必须为 "
            "committed"
        )
        assert isinstance(receipt_baseline.get("written_at"), str) and (
            receipt_baseline["written_at"]
        ), (
            f"fixture 前置事实失败：{identity} 的 receipt.written_at 必须是"
            "非空字符串（重跑不变断言的比对基线）"
        )
    target_side_mtime_baseline = _snapshot_target_side_mtime_ns(tmp_path)
    modes_baseline = _snapshot_modes(tmp_path)

    # ---- 前置对照（T18 既有行为）：同映射完成态重跑必须成功跳过且零
    #      变化 —— 失败即 T18 回归而非本切片 RED；该对照与下方变更重
    #      跑构成单一变量对照（唯一差异是 r1 replacement）。----
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：同 root、同映射、同 legacy 源的完成态"
            "重跑必须成功跳过（T18 既有幂等跳过行为回归，非本切片 RED；"
            f"原始异常经 cause 链保留）：{exc!r}"
        ) from exc
    assert _snapshot_tree(tmp_path) == completed_tree, (
        "fixture 前置事实失败：同映射完成态重跑必须零变化（T18 既有幂等"
        "跳过行为回归：目标 release / receipt / legacy 源不得有任何字节"
        "或键集变化）"
    )

    # ---- 行为：仅变更 r1 映射的 replacement（data-v4.1-r2 ->
    #      data-v4.1-r9；同 root、同 legacy 源、批内其余字段逐字段不
    #      变），再次调用 migrate_data。----
    rerun_items = _dual_object_batch_with_changed_r1_replacement()
    assert rerun_items[0] == mapping_items[0], (
        "fixture 前置事实失败：变更批的 r2 条目必须与原批逐字段一致"
        "（单一变量对照：唯一差异只能是 r1 replacement）"
    )
    assert {
        key: value
        for key, value in rerun_items[1].items()
        if key != "replacement"
    } == {
        key: value
        for key, value in mapping_items[1].items()
        if key != "replacement"
    }, (
        "fixture 前置事实失败：变更批的 r1 条目除 replacement 外必须与"
        "原批逐字段一致（单一变量对照）"
    )
    assert rerun_items[1]["replacement"] == _CHANGED_R1_REPLACEMENT, (
        "fixture 前置事实失败：变更批 r1 replacement 必须为 "
        f"{_CHANGED_R1_REPLACEMENT!r}"
    )

    # RED Gate：当前 production 的完成态核实不绑定 replacement，变更后
    # 的重跑静默跳过成功返回 —— 本用例把该静默跳过转成显式行为
    # AssertionError 钉出“完成态重跑 receipt 核实未绑定 superseded 映射
    # 的 replacement”；拒绝通道错位（原始未类型化异常替代
    # DataMigrationBlocked）同样经显式 AssertionError + cause 链转译，
    # 不得直接充当 RED 结论。
    blocked_error: BaseException | None = None
    try:
        migrate_data(tmp_path, rerun_items)
    except blocked_exc as exc:
        blocked_error = exc
    except Exception as exc:
        raise AssertionError(
            "完成态重跑 replacement 变更的拒绝通道错位：migrate_data 对 "
            "r1 映射 replacement 变更（data-v4.1-r2 -> "
            f"{_CHANGED_R1_REPLACEMENT}）的完成态批级重跑必须经 "
            "DataMigrationBlocked（或其子类）fail-closed 拒绝，实际抛出 "
            f"{type(exc).__name__}（原始异常经 cause 链保留）：{exc!r}"
        ) from exc
    assert blocked_error is not None, (
        "完成态重跑 receipt 核实未绑定 superseded 映射的 replacement"
        "（静默跳过）：r1 映射 replacement 从 "
        f"{CONFIRMED_DATA_TARGET_R2} 变更为 {_CHANGED_R1_REPLACEMENT} 后，"
        "migrate_data 对完成态双对象批（第一次完整转换已成功、同映射重"
        "跑已成功跳过、唯一差异为 r1 replacement）的同 root、同 legacy "
        "源第二次调用成功返回、未 fail-closed 拒绝 —— 与已提交事实"
        f"（r1 release.yaml replacement={CONFIRMED_DATA_TARGET_R2}、两份 "
        "committed receipt）不符的映射变更被静默跳过；本切片要求完成态 "
        "receipt 核实绑定 superseded 映射的 replacement：失配必须经 "
        "DataMigrationBlocked fail-closed 拒绝且零写入"
    )

    # ---- 2/3/4/5：fail-closed 拒绝必须零写入 —— 全树零变化（目标
    #      release / receipt / legacy 源 / 旧 pointers 逐字节不变、无新
    #      增/删除条目、不产生新身份）。----
    after_tree = _snapshot_tree(tmp_path)
    assert set(after_tree) == set(completed_tree), (
        "fail-closed 拒绝必须零写入：不得新增或删除任何条目（不产生 "
        f"{_CHANGED_R1_REPLACEMENT} / data-v4.1-r3 等新身份、不写报告/"
        "缓存/records、不删除既有条目）：实际新增 "
        f"{sorted(set(after_tree) - set(completed_tree))}，实际删除 "
        f"{sorted(set(completed_tree) - set(after_tree))}"
    )
    changed_entries = sorted(
        key
        for key, value in completed_tree.items()
        if after_tree[key] != value
    )
    assert not changed_entries, (
        "fail-closed 拒绝必须零写入：不得改动任何条目（两个目标 release "
        "子树、两份 receipt、legacy 源与旧 active pointers 逐字节不变；"
        f"不得顺手改写 r1 release.yaml 的 replacement 或重写 receipt）："
        f"实际改动 {changed_entries}"
    )

    # 2：既有两个目标 release 子树逐字节不变（显式重复全树结论，使该行
    #    为项在失败信息中可读归因）。
    assert _release_content_files(r2_release_dir) == r2_content_baseline, (
        "fail-closed 拒绝不得重写 data/releases/data-v4.1-r2（既有正式"
        "对象逐文件字节不变）"
    )
    assert _release_content_files(r1_release_dir) == r1_content_baseline, (
        "fail-closed 拒绝不得重写 data/releases/data-v4.1-r1（既有正式"
        "对象逐文件字节不变；不得顺手把 release.yaml 的 replacement 改"
        "写成新映射值）"
    )

    # 2：两份 receipt 逐字节不变（含 written_at），status 仍 committed。
    assert r2_receipt_file.read_bytes() == r2_receipt_bytes, (
        "fail-closed 拒绝不得重写 r2 receipt（凭证逐字节不变，含 "
        "written_at）"
    )
    assert r1_receipt_file.read_bytes() == r1_receipt_bytes, (
        "fail-closed 拒绝不得重写 r1 receipt（凭证逐字节不变，含 "
        "written_at；不得重算 digest 或刷新时间戳）"
    )
    for identity, receipt_file in (
        (CONFIRMED_DATA_TARGET_R2, r2_receipt_file),
        (CONFIRMED_DATA_TARGET_R1, r1_receipt_file),
    ):
        receipt_after = yaml.safe_load(receipt_file.read_text(encoding="utf-8"))
        receipt_baseline = receipt_baselines[identity]
        assert receipt_after == receipt_baseline, (
            f"{identity} 的 receipt 内容在 fail-closed 拒绝后必须不变"
            "（八字段逐一相等，不重算 digest、不改身份字段）"
        )
        assert receipt_after["written_at"] == receipt_baseline["written_at"], (
            f"{identity} 的 receipt.written_at 在 fail-closed 拒绝后必须"
            "不变（凭证未被重写）"
        )
        assert receipt_after["status"] == "committed", (
            f"{identity} 的 receipt.status 在 fail-closed 拒绝后必须仍为 "
            "committed"
        )

    # 3：无新身份 —— data/releases/ 恰含 r1、r2（不产生 data-v4.1-r9 /
    #    data-v4.1-r3）；migration_receipts/ 恰含两份 receipt。
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "fail-closed 拒绝不得产生任何新身份/新条目（不覆盖、不自动改"
        f"号，不得为 {_CHANGED_R1_REPLACEMENT} 创建正式对象）："
        "data/releases/ 必须恰含 "
        f"{CONFIRMED_DATA_TARGET_R1} 与 {CONFIRMED_DATA_TARGET_R2}"
    )
    assert not (
        tmp_path / "data" / "releases" / _CHANGED_R1_REPLACEMENT
    ).exists(), (
        f"fail-closed 拒绝不得为变更 replacement {_CHANGED_R1_REPLACEMENT!r}"
        "创建任何正式对象或目标条目"
    )
    assert not (
        tmp_path / "data" / "releases" / "data-v4.1-r3"
    ).exists(), "fail-closed 拒绝不得自动改号到 data-v4.1-r3"
    receipts_root = tmp_path / "migration_receipts"
    assert [
        entry.name for entry in sorted(receipts_root.iterdir())
    ] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], "migration_receipts/ 必须恰含 r1 与 r2 两份 receipt（拒绝不新增凭证）"

    # 无重写的次级判据：目标侧全部条目 mtime_ns 不变；权限位不变（不重
    # 新封存、不改写位，含 legacy 侧与目标侧 —— 同映射重跑对照若有字
    # 节恰好相同的重写同样在此暴露）。
    assert _snapshot_target_side_mtime_ns(tmp_path) == (
        target_side_mtime_baseline
    ), (
        "fail-closed 拒绝不得触碰目标侧任何条目元数据（data/ 与 "
        "migration_receipts/ 子树全部条目 mtime_ns 必须不变；字节恰好相"
        "同的重写也会更新 mtime）"
    )
    assert _snapshot_modes(tmp_path) == modes_baseline, (
        "fail-closed 拒绝不得改动任何条目权限位（不重新封存、不改写位）"
    )

    # 4：legacy 源和旧 pointers 不变（全树快照已钉定；此处显式钉旧指针
    #    仍声明 legacy 身份，使失败信息可读归因）。
    data_pointer_after = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_after["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fail-closed 拒绝不得切换旧数据活动指针（仍声明 legacy 身份）"
    )
    prompt_pointer_after = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_after["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "fail-closed 拒绝不得切换旧 Prompt 活动指针（仍声明 legacy "
        "revision_id）"
    )

    # 5：不就地修改传入映射项（原批与变更批都不被改写；变更批与全新构
    #    造的期望变体逐字段相等）。
    assert mapping_items == _confirmed_data_mapping_items(), (
        "fail-closed 拒绝不得就地改写传入映射项（原批 M0 事实分级保持"
        "不变）"
    )
    assert rerun_items == _dual_object_batch_with_changed_r1_replacement(), (
        "fail-closed 拒绝不得就地改写传入的变更批（r1 replacement 变更"
        "必须保持调用方声明的值，不得被 production 回填成已提交事实）"
    )

    # ---- 末尾对照（行为项 7，防拒绝过宽）：恢复原 replacement
    #      （data-v4.1-r2）后，同 root、同 legacy 源的完成态重跑必须仍
    #      成功跳过且零变化 —— 拒绝只能由 replacement 失配归因；前述
    #      fail-closed 拒绝不得破坏完成态，也不得过宽到拒绝凭证匹配
    #      的正常重跑。----
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "拒绝过宽或完成态被破坏：恢复原 replacement（"
            f"{CONFIRMED_DATA_TARGET_R2}）后的同映射完成态重跑必须仍成功"
            "跳过（T18 既有幂等行为；若此处失败，说明前述 fail-closed 拒"
            "绝破坏了完成态凭证，或拒绝条件过宽到拒绝了凭证匹配的正常"
            f"重跑；原始异常经 cause 链保留）：{exc!r}"
        ) from exc
    assert _snapshot_tree(tmp_path) == completed_tree, (
        "恢复原 replacement 后的完成态重跑必须零变化（T18 既有幂等跳过"
        "行为：目标 release / receipt / legacy 源不得有任何字节或键集变"
        "化）"
    )
    assert _snapshot_target_side_mtime_ns(tmp_path) == (
        target_side_mtime_baseline
    ), (
        "恢复原 replacement 后的完成态重跑不得重写目标侧任何条目（幂等"
        "跳过：data/ 与 migration_receipts/ 子树全部条目 mtime_ns 不变）"
    )
    assert _snapshot_modes(tmp_path) == modes_baseline, (
        "恢复原 replacement 后的完成态重跑不得改动任何条目权限位（不重"
        "新封存、不改写位）"
    )


# ---------------------------------------------------------------------------
# T19：批内部分完成的中断恢复 —— 双对象批（D2 推荐顺序 r2 先于 r1）在第
# 二个对象 r1 的目标写入中途被中断后，同 root、同映射、同 legacy 源的重
# 跑必须跳过凭证匹配的已完成 r2、继续并完成 r1，最终状态与无中断
# baseline 的正式 release / receipt 语义一致（D2 已确认语义；先写测试，
# 不改 production）
# ---------------------------------------------------------------------------


class _TargetWriteInterruptionControl:
    """r1 目标写中断注入的开关：armed 期间持续命中 r1 目标子树内的写入。"""

    def __init__(self) -> None:
        self.armed = True


def _install_r1_target_mid_write_interruption(
    monkeypatch: pytest.MonkeyPatch,
    r1_release_dir: Path,
    struck_writes: list[Path],
) -> _TargetWriteInterruptionControl:
    r"""安装 r1 目标写入中途中断：先落盘非空严格前缀，再抛 OSError。

    中断形态与 T10 同口径（“写入已真实开始、未完成”的最小代表）：把当前
    写入数据的非空严格前缀写入目标文件并 flush 落盘，然后抛
    ``_SimulatedMidWriteInterruption`` —— 模拟进程写盘中途崩溃 / 磁盘 IO
    错误；写入开始前即失败的注入不产生残骸、无法区分原子与非原子实现，
    故不采用。与 T10 的全局 ``Path.write_text`` 中断不同，本注入只命中
    ``r1_release_dir`` 子树内的 ``Path.write_bytes`` / ``Path.write_text``
    （r2 的目标写入、r2 receipt 写入与其余写入均原样放行），使双对象批内
    “r2 完整完成后、r1 写入中途”的批内部分完成状态可构造。armed 期间每
    次命中写入都中断（防实现捕获首次失败后继续写完其余文件）；恢复
    （armed=False）后写回原语义。每次被中断的写入路径记入
    struck_writes，供调用方断言“中断确实命中 r1 目标创建过程中的真实写入”
    （注入失效时显式失败，而非空洞通过）。

    注入点契约：拦截当前 production
    ``versioning.migration._migrate_single_data_release`` 写 r1 目标的实际
    调用点 ``Path.write_bytes``（payload 逐文件复制）与
    ``Path.write_text``（release.yaml）。若实现更换写机制（如临时文件 +
    rename、shutil.copyfile），本注入可能不再命中 —— struck_writes 为空
    时由调用方的前置断言先失败，提示注入点随实际写路径维护；行为契约
    （第一次调用显式失败 + r2 完成保留 + r1 无正式完成对象 + 重跑跳过
    r2 完成 r1 + 终态与 baseline 一致）不随写机制改变。
    """
    control = _TargetWriteInterruptionControl()
    original_write_bytes = Path.write_bytes
    original_write_text = Path.write_text

    def _strike(self: Path, data_bytes: bytes) -> None:
        cut = max(1, len(data_bytes) // 2)
        with open(self, "wb") as handle:
            handle.write(data_bytes[:cut])
            handle.flush()
        struck_writes.append(self)
        raise _SimulatedMidWriteInterruption(
            f"simulated interruption mid-write of r1 target entry: {self}"
        )

    def interrupting_write_bytes(self: Path, data: bytes) -> int:
        if control.armed and self.is_relative_to(r1_release_dir):
            _strike(self, bytes(data))
        return original_write_bytes(self, data)

    def interrupting_write_text(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if control.armed and self.is_relative_to(r1_release_dir):
            _strike(
                self,
                data.encode(
                    encoding=encoding or "utf-8", errors=errors or "strict"
                ),
            )
        return original_write_text(
            self, data, encoding=encoding, errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "write_bytes", interrupting_write_bytes)
    monkeypatch.setattr(Path, "write_text", interrupting_write_text)
    return control


def _write_interrupt_scenario_layout(root: Path) -> None:
    """构建本切片双根共用的场景 fixture（T17/T18 同款布局与注入）。

    与 T17/T18 完全同款：``_write_legacy_data_layout`` 三份 legacy release
    + 旧数据/Prompt 活动指针 + r2/r1 counts 场景注入（r2
    published_candidates 7、r1 为 11，与 payload 可复算值 3 互相不同 ——
    双对象批内语义溯源可观察）+ r2 指针 expected_manifest_sha256 随注入后
    manifest 字节复算重写。不注入则共享写入口径 ``_derive_release_splits``
    在写入前因 counts.splits 缺失拒绝，r2 无法完成，测试到不了 r1 中断点；
    注入只改 counts：files[] 声明哈希不动（T14 门保持绿），指针哈希随注入
    复算（T13 钉扎门保持绿）。注入值与 T17/T18 完全一致，使各切片在同一
    事实基线上叠加。
    """
    _write_legacy_data_layout(root)
    r2_manifest = json.loads(
        _manifest_file_of(root, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r2_manifest["counts"] = {
        "published_candidates": 7,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 5,
            "fold_0_val": 2,
            "fold_1_train": 6,
            "fold_1_val": 4,
            "fold_2_train": 7,
            "fold_2_val": 1,
        },
    }
    r2_manifest_bytes = _rewrite_legacy_release_manifest(
        root, CONFIRMED_DATA_SOURCE_R2, r2_manifest
    )
    pointer = json.loads((root / _DATA_POINTER_REL).read_text(encoding="utf-8"))
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        r2_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(root, pointer)

    r1_manifest = json.loads(
        _manifest_file_of(root, CONFIRMED_DATA_SOURCE_R1).read_text(
            encoding="utf-8"
        )
    )
    r1_manifest["counts"] = {
        "published_candidates": 11,
        "excluded_candidates": 0,
        "reviewed_candidates": 3,
        "splits": {
            "fold_0_train": 9,
            "fold_0_val": 4,
            "fold_1_train": 8,
            "fold_1_val": 2,
            "fold_2_train": 10,
            "fold_2_val": 3,
        },
    }
    _rewrite_legacy_release_manifest(root, CONFIRMED_DATA_SOURCE_R1, r1_manifest)


def _legacy_side_of(snapshot: dict[str, bytes]) -> dict[str, bytes]:
    """从整树快照取 legacy 侧条目（workspace/、finetune/、pipeline/ 子树）。"""
    return {
        rel: content
        for rel, content in snapshot.items()
        if rel.split("/", 1)[0] in ("workspace", "finetune", "pipeline")
    }


def _assert_legacy_side_unchanged(
    before: dict[str, bytes], after: dict[str, bytes]
) -> None:
    """断言 legacy 侧（源树 + 旧 active pointers）零新增/删除/修改。"""
    before_side = _legacy_side_of(before)
    after_side = _legacy_side_of(after)
    changed = sorted(
        {rel for rel in before_side if after_side.get(rel) != before_side[rel]}
        | {rel for rel in after_side if rel not in before_side}
    )
    assert not changed, (
        "data 迁移（含中断失败路径与恢复重跑）不得修改、删除或新增 "
        "workspace/、finetune/、pipeline/ 子树的任何条目（legacy 源与旧 "
        f"active pointers 逐字节不变）：变化 {changed}"
    )


def _snapshot_r2_completed_side_mtime_ns(root: Path) -> dict[str, int]:
    """已完成 r2 侧（r2 release 子树 + r2 receipt）全部条目的 mtime_ns 快照。

    中断恢复重跑“跳过已完成对象”的次级可观察判据：跳过不写任何字节、不
    触碰任何元数据；“逐字节重写同一内容”在字节层与快照不可区分，但重写
    必然更新 mtime（receipt 侧另有 written_at 双保险；payload 已按
    T15-P2-1 封存去写位 0o444，重写会直接 PermissionError）。
    """
    snapshot: dict[str, int] = {}
    r2_release_dir = root / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    snapshot[f"data/releases/{CONFIRMED_DATA_TARGET_R2}"] = (
        r2_release_dir.stat().st_mtime_ns
    )
    for path in sorted(r2_release_dir.rglob("*")):
        snapshot[
            f"data/releases/{CONFIRMED_DATA_TARGET_R2}/"
            f"{path.relative_to(r2_release_dir).as_posix()}"
        ] = path.stat().st_mtime_ns
    r2_receipt = (
        root / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    snapshot[f"migration_receipts/{r2_receipt.name}"] = (
        r2_receipt.stat().st_mtime_ns
    )
    return snapshot


def _assert_receipt_semantics_match_baseline(
    receipt: Any, baseline_receipt: Any, identity: str
) -> None:
    r"""断言 receipt 与无中断 baseline 同对象 receipt 语义一致（除时间字段）。

    receipt 的 ``written_at`` 记录凭证写入时刻：中断恢复重跑与 baseline
    各自独立写入，允许不同（单独排除，仅要求非空字符串）。其余七字段
    （operation_id / source_legacy_id / target_identity / target_path /
    source_manifest_sha256 / target_release_digest / status）必须逐一相等
    —— operation_id 是绑定映射（source/target/status/replacement）与源
    manifest 字节的确定性凭证（“重跑同一次转换”），digest 绑定目标全部
    内容；二者相等即“最终状态与无中断 baseline 的 receipt 语义一致”。
    """
    assert isinstance(receipt, dict), (
        f"{identity} 的 receipt 必须是 YAML 顶层映射：实际 "
        f"{type(receipt).__name__}"
    )
    assert isinstance(baseline_receipt, dict), (
        f"fixture 前置事实失败：baseline 的 {identity} receipt 必须是 YAML "
        "顶层映射"
    )
    assert set(receipt) == set(_RECEIPT_FIELDS), (
        f"{identity} 的 receipt 键集必须恰为八字段契约（不夹带非契约字段）："
        f"实际 {sorted(receipt)}"
    )
    assert set(baseline_receipt) == set(_RECEIPT_FIELDS), (
        f"fixture 前置事实失败：baseline 的 {identity} receipt 键集必须恰为"
        f"八字段契约：实际 {sorted(baseline_receipt)}"
    )
    assert receipt["status"] == "committed", (
        f"{identity} 的 receipt.status 必须为 committed：实际 "
        f"{receipt['status']!r}"
    )
    for field in _RECEIPT_FIELDS:
        if field == "written_at":
            continue
        assert receipt[field] == baseline_receipt[field], (
            f"{identity} 的 receipt.{field} 必须与无中断 baseline 一致（同一次"
            "转换的重跑；written_at 之外的字段语义必须逐字段相等）：实际 "
            f"{receipt[field]!r}，baseline {baseline_receipt[field]!r}"
        )
    for source_label, value in (
        ("重跑终态", receipt["written_at"]),
        ("baseline", baseline_receipt["written_at"]),
    ):
        assert isinstance(value, str) and value, (
            f"{identity} 的 receipt.written_at（{source_label}）必须是非空字符"
            "串（两侧写入时刻允许不同，不得缺失）"
        )


def _assert_partial_object_receipt_not_committed(
    receipt_file: Path, target_identity: str, *, context: str
) -> None:
    r"""中断后的部分写入对象：同一 receipt 文件允许作为 in-progress
    credential 存在，但不得声称 committed。

    用户确认的 in-progress credential 生命周期（T19-P4 配套设计）：每个
    对象使用同一个 ``migration_receipts/<target_identity>.receipt.yaml``，
    在开始写入目标前先原子写 ``status: in_progress``、
    ``target_release_digest: null``，并绑定 operation / source / target /
    path / 中断前源 manifest 哈希 / 映射 target_status / replacement；中
    断后该文件保留；恢复重跑成功后该文件原子替换为既有八字段 committed
    receipt，完成后不额外保留 in-progress 状态。因此中断后该文件存在不
    是异常（是恢复依据），成功恢复后该文件转为 committed 是允许且必要
    的转写（committed 终态由各调用方的既有 receipt 契约断言钉定）。本
    断言只钉唯一不得发生的形态：把未完成对象伪称为 committed。credential
    的存在性与字段绑定契约由 T19-P4 用例独立钉定，本断言不要求存在
    （当前 production 偏离用户裁决，credential 写在
    migration_receipts.in.progress/ 独立目录、同一 receipt 文件缺失，
    本断言对此保持中性；存在性由 T19-P4 钉定同一文件契约）。
    """
    if not receipt_file.is_file():
        return
    try:
        parsed = yaml.safe_load(receipt_file.read_bytes())
    except Exception as exc:
        raise AssertionError(
            f"{context}：{target_identity} 的 receipt 文件存在但不可解析（存"
            "在即必须是可核实、不声称 committed 的 in-progress credential；"
            f"不可解析即无法核实不伪称 committed）：{exc!r}"
        ) from exc
    assert isinstance(parsed, Mapping), (
        f"{context}：{target_identity} 的 receipt 文件必须是 YAML 顶层映射"
        "（存在即必须是不声称 committed 的 in-progress credential）：实际 "
        f"{type(parsed).__name__}"
    )
    status = parsed.get("status")
    assert status != "committed", (
        f"{context}：不得存在把未完成 {target_identity} 伪称 committed 的凭"
        "证（committed receipt 只在目标完整写入并验证后产生；中断后同一文"
        "件允许且预期作为 in-progress credential 保留 —— 用户确认生命周"
        "期：写入前 status: in_progress、成功后原子转 committed）：实际 "
        f"{receipt_file.name} status={status!r}"
    )


def _assert_same_file_in_progress_receipt(
    receipt_file: Path,
    target_identity: str,
    mapping_item: Mapping[str, Any],
    source_manifest_sha256: str,
    *,
    context: str,
) -> bytes:
    r"""断言同一个 receipt 文件以 in_progress 状态存在且绑定完整。

    用户确认的 in-progress receipt 生命周期：每个对象使用同一个
    ``migration_receipts/<target_identity>.receipt.yaml``，写入前该文件为
    ``status: in_progress``、``target_release_digest: null``，并绑定
    operation / source / target / path / 写入前源 manifest 哈希 / 映射
    target_status / replacement；中断后同一文件保留，恢复成功后同一文件
    原子转为 committed。本断言钉该文件在中断后/拒绝后的形态：必须存在、
    可解析、status 为 in_progress、digest 为 null、字段绑定完整 ——
    不得接受独立 credential 目录（migration_receipts.in.progress/ 等）
    或额外凭证文件（同一 receipt 文件缺失即生命周期偏离）。返回文件字
    节，供调用方做后续逐字节不变比对。
    """
    assert receipt_file.is_file(), (
        f"{context}：同一个 receipt 文件 "
        f"migration_receipts/{target_identity}.receipt.yaml 必须存在（用"
        "户确认生命周期：写入前该文件为 status: in_progress、"
        "target_release_digest: null，中断后保留同一个 in-progress receipt，"
        "恢复成功后同一文件原子转为 committed；不得把 credential 写在 "
        "migration_receipts.in.progress/ 等独立目录或额外凭证文件）"
    )
    receipt_bytes = receipt_file.read_bytes()
    try:
        parsed = yaml.safe_load(receipt_bytes)
    except Exception as exc:
        raise AssertionError(
            f"{context}：同一个 receipt 文件存在但不可解析（in-progress "
            f"receipt 必须可核实）：{exc!r}"
        ) from exc
    assert isinstance(parsed, Mapping), (
        f"{context}：同一个 receipt 文件必须是 YAML 顶层映射（in-progress "
        f"receipt 必须可核实）：实际 {type(parsed).__name__}"
    )
    assert parsed.get("status") == "in_progress", (
        f"{context}：同一个 receipt 文件的 status 必须为 in_progress（部分"
        f"写入对象不得伪称 committed）：实际 {parsed.get('status')!r}"
    )
    assert parsed.get("target_release_digest") is None, (
        f"{context}：同一个 receipt 文件的 target_release_digest 必须为 "
        "null（目标尚未完整写入并验证；成功后原子替换为 committed 与目标"
        f" digest）：实际 {parsed.get('target_release_digest')!r}"
    )
    binding_errors = _in_progress_credential_binding_errors(
        parsed, mapping_item, source_manifest_sha256
    )
    assert not binding_errors, (
        f"{context}：同一个 in-progress receipt 字段绑定不完整（至少绑定 "
        "operation_id / source_legacy_id / target_identity / target_path / "
        "source_manifest_sha256（写入前源快照）/ target_status / "
        f"replacement）：{binding_errors}"
    )
    return receipt_bytes


def test_migrate_data_interrupted_dual_object_batch_rerun_skips_completed_r2_and_continues_r1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r"""批内部分完成的中断恢复：重跑跳过已完成 r2、继续完成 r1，终态与 baseline 一致。

    T19 behavior（本切片，主 Agent 选定，先写测试，不改 production）——
    D2 已确认：预检全量 fail-closed；写入按对象独立；逐对象生成可核实凭
    证；中断后重跑同一次转换，凭证匹配的已完成对象跳过，未完成对象继续；
    凭证不匹配或无法核实即停止，不覆盖、不改号。本切片钉批内部分完成的
    最小恢复切面：对双对象批 [r2, r1]（D2 推荐顺序 r2 先于 r1）开始转换，
    在第二个对象 r1 的写入过程中注入失败时：
    1. 第一次调用必须显式失败（注入确实命中 r1 目标写入：写入已真实开
       始、未完成 —— 非空严格前缀落盘后抛 OSError，struck_writes 非空）；
    2. r2 作为已完成对象保留：data/releases/data-v4.1-r2 完整正式
       release（经既有语义读回 active、封存事实保持）与 committed
       receipt（八字段契约）均在，不被 r1 的中断波及；
    3. r1 不得留下可被误认为正式完成的对象（既有读取语义
       load_release_metadata 不能把 r1 读回为正式 release），且不得存在
       r1 committed receipt —— 同一个
       migration_receipts/data-v4.1-r1.receipt.yaml 中断后允许（且按用户确
       认生命周期应当）以 in-progress 状态保留（status: in_progress、
       target_release_digest: null），成功恢复后同一文件原子转为
       committed（用户确认生命周期，T19-P4 钉存在性与字段绑定契约；
       本切片只排除把未完成对象伪称 committed）；
    4. legacy 源和旧 pointers 不变（workspace/、finetune/、pipeline/
       子树逐字节不变）；
    5. 恢复注入后，用相同 root、相同映射、相同 legacy 源重跑同一
       ``migrate_data``：必须成功 —— 跳过凭证匹配的已完成 r2（release
       与 receipt 逐字节不变、written_at 不刷新、r2 侧 mtime 不动），
       继续并完成 r1；
    6. 最终状态与无中断 baseline 的正式 release 和 receipt 语义一致：
       两个目标 release 与 baseline 逐文件字节一致（含 release.yaml 与
       全部 payload）；receipt 与 baseline 逐字段语义相等（written_at
       记录各自写入时刻、单独排除；其余七字段含确定性 operation_id /
       target_release_digest 必须相等）；r1 经既有语义读回为
       superseded、replacement 解析为既有 active r2、语义字段取 r1
       manifest 声明值（注入值 11）、封存事实保持；
       validate_training_reference 对 r2 放行、对 r1 拒绝；
    7. 无新身份：data/releases/ 恰含 r1、r2 两个正式对象，
       migration_receipts/ 恰含 r1 与 r2 两份 receipt（同一个 r1 receipt
       文件由 in_progress 原子转为 committed，不得新增额外 credential
       文件或目录 —— 不使用 migration_receipts.in.progress/ 等独立位置），
       不产生 data-v4.1-r3 等新身
       份；不写 records/、生命周期目录、.dvc；不就地修改传入映射项；
    8. 本切片不做凭证失配拒绝（receipt 被篡改 / 映射变更后的重跑拒绝分
       支，T18-P2 已钉 replacement 变更分支）、批内乱序输入（r1 先于
       r2）、migrate_data 返回值契约、跳过/继续的报告通道与 CLI、DVC、
       训练机真实路径。

    fixture：并行双根（baseline / interrupted），各自复用 T17/T18 双对象
    fixture（``_write_legacy_data_layout`` 三份 legacy release + 旧数据/
    Prompt 活动指针 + 两条映射来自 ``_confirmed_data_mapping_items``，D2
    推荐顺序 r2 先于 r1）+ T15/T16/T17/T18 同款 counts 场景注入与指针
    manifest 哈希随注入重写（``_write_interrupt_scenario_layout``，注入值
    与 T17/T18 完全一致：r2 published_candidates 7、r1 为 11）；双根
    fixture 前置断言字节级同构。baseline 根不受注入干净转换一次（T17 既
    有行为，失败即 T17 回归而非本切片 RED），其终态即本切片的最终状态对
    照基线；interrupted 根走 中断 -> 断言 -> 恢复 -> 重跑。

    注入方式：monkeypatch ``Path.write_bytes`` / ``Path.write_text``（当
    前 production ``_migrate_single_data_release`` 写 r1 目标的实际调用
    点），仅对 data/releases/data-v4.1-r1/ 子树内的写入生效：写入非空严
    格前缀字节后抛 ``_SimulatedMidWriteInterruption`` —— 模拟写盘中途崩
    溃 / 磁盘 IO 错误；前置断言 struck_writes 非空且全部落在 r1 目标子
    树内，钉死中断确实命中第二个对象的写入过程（注入失效 -> 显式失败，
    而非空洞通过）。

    RED Gate 设计说明（T19，本轮契约统一后更新）：migrate_data 入口、
    DataMigrationBlocked 拒绝通道、T17 双对象批终态、T18 完成态重跑幂等
    跳过与中断恢复行为均已存在（baseline 完整转换成功、第一次调用被
    中断命中且显式失败、r2 完成保留、r1 无正式完成对象均为 fixture
    前置事实，失败即既有切片回归而非本切片 RED），重跑路径本身已满足
    （跳过 r2 + 完成 r1 + 终态与 baseline 一致）。当前 RED 只由用户裁
    决的 in-progress receipt 生命周期偏离给出：当前 production 把
    credential 写在 migration_receipts.in.progress/ 独立目录、不使用同
    一个 migration_receipts/data-v4.1-r1.receipt.yaml，恢复路径完成后额
    外保留该目录与 credential 文件 —— 行为 7 的目标根新增条目断言把
    migration_receipts.in.progress/ 与其内 credential 检出为额外
    credential 目录/文件，显式 AssertionError 钉出“中断 + 恢复全程新增
    了用户裁决不允许的额外 credential 目录/文件”（同一 r1 receipt 文件
    从 in_progress 转为 committed 本身允许且必要）；production 返工到
    同一文件生命周期后本用例为 Unexpected PASS（转中断恢复回归钉），
    不得为此制造无意义 production 修改。

    捕获的合理但错误实现：
    - 当前 production（RED 起点，用户裁决生命周期偏离）：credential 写
      在 migration_receipts.in.progress/ 独立目录、恢复路径完成后保留该
      目录与 credential 文件 -> 行为 7 目标根新增条目断言失败（额外
      credential 目录/文件）；
    - “整批重做”：重跑重写 r2 release / receipt（即使字节恰好相同）->
      r2 receipt written_at 变化 / r2 侧 mtime 变化 / 已封存 payload
      0o444 重写 PermissionError -> 对应断言失败；
    - “冲突即改号”：自动改号到 data-v4.1-r3 等新身份继续 -> 目标根精确
      内容 + 全树快照断言失败；
    - 只跳过不继续（r1 未完成即返回“成功”）-> r1 release / receipt 缺失
      或与 baseline 不一致 -> 存在性与对照断言失败；
    - 只继续不跳过（r2 被重做或重跑整体被拒）-> r2 receipt 字节 / mtime
      断言失败或重跑失败；
    - 继续时读错源 / 从 payload 重算语义字段（r1 注入声明值 11 与
      payload 可复算值 3、r2 注入声明值 7 故意不同）-> sample_count /
      splits 对照断言失败；
    - r1 凭证与 r2 串写或 digest 绑定半成品快照 -> receipt 键集 / 独立
      复算 / baseline 对照断言失败；
    - 中断被吞掉后第一次调用“成功”返回 -> 第一次调用显式失败断言失败
      （批内部分完成状态不可构造）；
    - 重跑顺手触碰 legacy 源或旧 active pointers（切换指针、改写
      manifest/payload、去写位）-> legacy 侧逐字节比对失败；
    - 重跑写盘报告/缓存（跳过清单、日志、临时文件）-> 全树快照新增条目
      断言失败；就地修改传入映射项 -> 映射项不变断言失败。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（本切片仅新增本用
      例与配套 fixture helper，不改 production）。
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_interrupted_dual_object_batch_rerun_skips_completed_r2_and_continues_r1``
    - RED failure signature（本轮契约统一后）：恰一个失败用例（本
      selector），失败信息为 AssertionError “中断 + 恢复重跑全程只允许新
      增两个目标 release 目录子树（含目录条目）与两份 receipt…”，实际
      新增检出 migration_receipts.in.progress/ 与
      migration_receipts.in.progress/data-v4.1-r1.receipt.yaml（当前
      production 把 credential 写在独立目录、恢复路径完成后保留 —— 用户
      裁决要求同一个
      migration_receipts/data-v4.1-r1.receipt.yaml 从 in_progress 原子转
      为 committed，不另立 credential 目录/文件）；fixture 前置事实（双
      根同构、baseline 完整转换成功、第一次调用被中断命中且显式失败、
      r2 完成保留、r1 无正式完成对象、legacy 不变）全部不失败；同一
      r1 receipt 文件的 in_progress -> committed 转写不构成失败（允许且
      必要）。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：并行双根（baseline / interrupted），字节级同构断言钉死。----
    baseline_root = tmp_path / "baseline"
    interrupted_root = tmp_path / "interrupted"
    _write_interrupt_scenario_layout(baseline_root)
    _write_interrupt_scenario_layout(interrupted_root)
    assert _snapshot_tree(baseline_root) == _snapshot_tree(interrupted_root), (
        "fixture 前置事实失败：baseline 与 interrupted 双根 fixture 必须字"
        "节级同构（同布局、同 counts 注入、同指针；最终状态对照的可比性前"
        "提）"
    )
    for root in (baseline_root, interrupted_root):
        _assert_payload_declared_hashes_self_consistent(
            root, CONFIRMED_DATA_SOURCE_R1
        )
        _assert_payload_declared_hashes_self_consistent(
            root, CONFIRMED_DATA_SOURCE_R2
        )
        pointer = json.loads(
            (root / _DATA_POINTER_REL).read_text(encoding="utf-8")
        )
        assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
            "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
        )
        assert pointer["expected_manifest_sha256"] == hashlib.sha256(
            _manifest_file_of(root, CONFIRMED_DATA_SOURCE_R2).read_bytes()
        ).hexdigest(), (
            "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
            "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
        )
        for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
            assert not (root / forbidden).exists(), (
                f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
            )
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded（D1）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2（D1）"
    )
    r2_manifest = json.loads(
        _manifest_file_of(interrupted_root, CONFIRMED_DATA_SOURCE_R2).read_text(
            encoding="utf-8"
        )
    )
    r1_manifest = json.loads(
        _manifest_file_of(interrupted_root, CONFIRMED_DATA_SOURCE_R1).read_text(
            encoding="utf-8"
        )
    )
    r2_declared_payload_paths = sorted(
        entry["path"] for entry in r2_manifest["files"]
    )
    r1_declared_payload_paths = sorted(
        entry["path"] for entry in r1_manifest["files"]
    )

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T17 既有行为不可用，本切片 fixture 前置事实失"
        "败）"
    )
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（T11 既有行为不可用，本切片 fixture "
        "前置事实失败）"
    )
    dual_precheck_report = precheck(interrupted_root, mapping_items)
    assert dual_precheck_report.status == "ready", (
        "fixture 前置事实失败：空目标根上双对象批（r2+r1，D2 推荐顺序）的"
        f"只读预检必须整批 ready（实际 {dual_precheck_report.status!r}，"
        f"reasons={dual_precheck_report.reasons!r}）—— 第一次调用的失败只"
        "能由注入中断归因"
    )

    # ---- baseline：无中断完整转换（T17 既有行为；本切片最终状态对照）。----
    baseline_items = _confirmed_data_mapping_items()
    try:
        migrate_data(baseline_root, baseline_items)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：无中断 baseline 的双对象批完整转换必须成"
            "功（T17 既有双对象批终态行为回归，非本切片 RED；原始异常经 "
            f"cause 链保留）：{exc!r}"
        ) from exc
    assert baseline_items == _confirmed_data_mapping_items(), (
        "fixture 前置事实失败：baseline 完整转换不得就地改写传入映射项"
    )
    baseline_r2_release_dir = (
        baseline_root / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    )
    baseline_r1_release_dir = (
        baseline_root / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    )
    baseline_r2_content = _release_content_files(baseline_r2_release_dir)
    baseline_r1_content = _release_content_files(baseline_r1_release_dir)
    assert set(baseline_r2_content) == {"release.yaml"} | set(
        r2_declared_payload_paths
    ), (
        "fixture 前置事实失败：baseline r2 目标 release 内容必须恰为 "
        "release.yaml + r2 manifest 声明的 payload 文件集合"
    )
    assert set(baseline_r1_content) == {"release.yaml"} | set(
        r1_declared_payload_paths
    ), (
        "fixture 前置事实失败：baseline r1 目标 release 内容必须恰为 "
        "release.yaml + r1 manifest 声明的 payload 文件集合"
    )
    baseline_r2_receipt_file = (
        baseline_root
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    baseline_r1_receipt_file = (
        baseline_root
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    assert (
        baseline_r2_receipt_file.is_file()
        and baseline_r1_receipt_file.is_file()
    ), (
        "fixture 前置事实失败：baseline 完整转换必须写入两份 committed "
        "receipt"
    )
    baseline_r2_receipt = yaml.safe_load(
        baseline_r2_receipt_file.read_text(encoding="utf-8")
    )
    baseline_r1_receipt = yaml.safe_load(
        baseline_r1_receipt_file.read_text(encoding="utf-8")
    )
    for identity, receipt in (
        (CONFIRMED_DATA_TARGET_R2, baseline_r2_receipt),
        (CONFIRMED_DATA_TARGET_R1, baseline_r1_receipt),
    ):
        assert isinstance(receipt, dict), (
            f"fixture 前置事实失败：baseline {identity} receipt 必须是 YAML "
            "顶层映射"
        )
        assert set(receipt) == set(_RECEIPT_FIELDS), (
            f"fixture 前置事实失败：baseline {identity} receipt 键集必须恰为"
            f"八字段契约：实际 {sorted(receipt)}"
        )
        assert receipt["status"] == "committed", (
            f"fixture 前置事实失败：baseline {identity} receipt 必须为 "
            "committed"
        )
        assert isinstance(receipt["written_at"], str) and receipt["written_at"], (
            f"fixture 前置事实失败：baseline {identity} receipt.written_at 必"
            "须是非空字符串"
        )

    # ---- 行为前提构造：安装 r1 目标写中途中断（armed 期间持续命中）。----
    interrupted_before = _snapshot_tree(interrupted_root)
    r1_release_dir = (
        interrupted_root / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    )
    struck_writes: list[Path] = []
    interruption = _install_r1_target_mid_write_interruption(
        monkeypatch, r1_release_dir, struck_writes
    )

    # ---- 行为 1：第一次调用必须显式失败（r1 写入中途被中断命中）。----
    first_call_error: BaseException | None = None
    try:
        migrate_data(interrupted_root, mapping_items)
    except Exception as exc:
        first_call_error = exc
    assert first_call_error is not None, (
        "双对象批第一次调用必须在 r1 写入中途注入失败后显式失败（中断不得"
        "被吞掉后当作成功返回：r1 未完成而第一次调用成功返回，与“r1 写入过"
        "程中被中断”的前提矛盾，批内部分完成状态不可构造）"
    )
    assert struck_writes, (
        "中断注入失效：第一次调用的 r1 目标写入未被命中（struck_writes 为"
        "空 —— 注入点需随实际写路径维护：当前 production 经 "
        "Path.write_bytes 逐文件复制 r1 payload、Path.write_text 写 "
        "release.yaml；行为契约不随写机制改变，但本测试要求中断确实发生在"
        "第二个对象的写入过程中，而非空洞通过）"
    )
    assert all(
        path.is_relative_to(r1_release_dir) for path in struck_writes
    ), (
        "中断注入命中范围异常：被中断的写入必须全部落在 r1 目标子树 "
        f"data/releases/{CONFIRMED_DATA_TARGET_R1}/ 内（不得误伤 r2 目标写"
        f"入或 receipt 写入）：实际 {sorted(struck_writes)}"
    )

    # ---- 行为 2：r2 作为已完成对象保留（完整正式 release + committed
    #      receipt，不被 r1 的中断波及）。----
    r2_release_dir = (
        interrupted_root / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    )
    r2_receipt_file = (
        interrupted_root
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    r1_receipt_file = (
        interrupted_root
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    assert r2_release_dir.is_dir(), (
        "中断后 r2 必须作为已完成对象保留：data/releases/data-v4.1-r2 正式"
        "release 目录必须存在（批必须按 D2 推荐顺序 r2 先完成；r2 缺失即"
        "实现未先行完成 r2，或中断未发生在第二个对象的写入阶段）"
    )
    interrupted_r2_content = _release_content_files(r2_release_dir)
    assert set(interrupted_r2_content) == {"release.yaml"} | set(
        r2_declared_payload_paths
    ), (
        "中断后保留的 r2 目标 release 内容必须恰为 release.yaml + r2 "
        f"manifest 声明的 payload 文件集合：实际 {sorted(interrupted_r2_content)}"
    )
    r2_meta_after_interrupt = load_release_metadata(
        interrupted_root / "data", CONFIRMED_DATA_TARGET_R2
    )
    assert r2_meta_after_interrupt.version == CONFIRMED_DATA_TARGET_R2, (
        "中断后保留的 r2 必须经既有语义读回为 data-v4.1-r2"
    )
    assert r2_meta_after_interrupt.status is DataStatus.ACTIVE, (
        "中断后保留的 r2 必须经既有语义读回为 active 正式对象"
    )
    try:
        assert_payload_sealed(r2_release_dir)
    except Exception as exc:
        raise AssertionError(
            "中断后保留的 r2 封存事实必须保持（既有只读门 "
            f"assert_payload_sealed 通过；T15-P2-1 既有行为回归）：{exc!r}"
        ) from exc
    assert r2_receipt_file.is_file(), (
        "中断后 r2 的 committed receipt 必须已写入（r2 是已完成对象，逐对"
        "象生成可核实凭证）"
    )
    interrupted_r2_receipt_bytes = r2_receipt_file.read_bytes()
    interrupted_r2_receipt = yaml.safe_load(interrupted_r2_receipt_bytes)
    assert isinstance(interrupted_r2_receipt, dict), (
        "中断后 r2 receipt 必须是 YAML 顶层映射"
    )
    assert set(interrupted_r2_receipt) == set(_RECEIPT_FIELDS), (
        "中断后 r2 receipt 键集必须恰为八字段契约：实际 "
        f"{sorted(interrupted_r2_receipt)}"
    )
    assert interrupted_r2_receipt["status"] == "committed", (
        "中断后 r2 receipt 必须为 committed（已完成对象的凭证）"
    )
    r2_completed_side_mtime = _snapshot_r2_completed_side_mtime_ns(interrupted_root)

    # ---- 行为 3：r1 不得留下可被误认为正式完成的对象，且不得存在
    #      committed receipt（同一 receipt 文件中断后允许以 in-progress
    #      credential 形式保留 —— 用户确认生命周期，T19-P4 钉契约；成功恢
    #      复后该文件原子转为 committed 是允许且必要的转写）。----
    try:
        load_release_metadata(interrupted_root / "data", CONFIRMED_DATA_TARGET_R1)
    except DataReleaseError:
        pass
    except Exception as exc:
        raise AssertionError(
            "中断后 r1 不得留下可被误认为正式完成的对象：既有读取语义对 r1 "
            "的拒绝必须是 data release 域错误（ReleaseNotFound / "
            f"ReleaseSchemaError 等），实际 {type(exc).__name__}（原始异常经"
            f" cause 链保留）：{exc!r}"
        ) from exc
    else:
        raise AssertionError(
            "中断后 r1 不得留下可被误认为正式完成的对象：load_release_metadata"
            f" 竟把 {CONFIRMED_DATA_TARGET_R1!r} 读回为正式 release（中断必须"
            "发生在 r1 完整写入并验证之前，半写残骸不得呈现为正式完成对象）"
        )
    _assert_partial_object_receipt_not_committed(
        r1_receipt_file, CONFIRMED_DATA_TARGET_R1, context="中断后"
    )

    # ---- 行为 4：legacy 源和旧 pointers 不变（第一次中断失败路径）。----
    _assert_legacy_side_unchanged(
        interrupted_before, _snapshot_tree(interrupted_root)
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "中断失败路径不得就地改写传入映射项（M0 事实分级保持不变）"
    )

    # ---- 行为 5：恢复注入后重跑（相同 root、相同映射、相同 legacy 源）。----
    interruption.armed = False
    # RED Gate：当前 production 的 precheck 把已完成的 r2 判为目标冲突、
    # 把 r1 半写目录判为 data 根同身份冲突，重跑以 DataMigrationBlocked 拒
    # 绝 —— 本用例把该拒绝转成显式行为 AssertionError 钉出“批内部分完成
    # 的中断恢复行为缺失”，原始异常经 cause 链保留；若当前实现已满足（重
    # 跑成功 + 跳过 r2 + 完成 r1 + 终态与 baseline 一致），本用例为
    # Unexpected PASS（中断恢复回归钉）。
    try:
        migrate_data(interrupted_root, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "批内部分完成的中断恢复行为缺失：migrate_data 对双对象批（r2 已"
            "完成保留 + r1 写入中途被中断）的同 root、同映射、同 legacy 源重"
            "跑把已完成的 r2 当成外来冲突拒绝（或因 r1 半写目标冲突拒绝、或"
            "失败于其他原因）—— 本切片要求凭证匹配的已完成对象跳过、未完成"
            "对象继续并完成：重跑必须成功、r2 零重写、r1 完成且最终状态与无"
            "中断 baseline 的正式 release 和 receipt 语义一致（原始异常经 "
            f"cause 链保留）：{exc!r}"
        ) from exc

    # ---- 行为 5a：跳过已完成 r2 —— receipt 与 release 逐字节不变（含
    #      written_at）、r2 侧 mtime 不动（“跳过”不写任何字节）。----
    assert r2_receipt_file.read_bytes() == interrupted_r2_receipt_bytes, (
        "重跑不得重写已完成 r2 的 receipt（凭证逐字节不变，含 written_at；"
        "跳过即不重写、不刷新时间戳、不重算 digest）"
    )
    final_r2_receipt = yaml.safe_load(r2_receipt_file.read_text(encoding="utf-8"))
    assert final_r2_receipt == interrupted_r2_receipt, (
        "重跑后 r2 receipt 八字段内容必须与中断后保留状态逐一相等"
    )
    assert final_r2_receipt["written_at"] == interrupted_r2_receipt["written_at"], (
        "重跑后 r2 receipt.written_at 必须不变（跳过已完成对象不重写凭证；"
        "written_at 变化即重跑重做了 r2）"
    )
    assert _release_content_files(r2_release_dir) == interrupted_r2_content, (
        "重跑不得重写已完成 r2 的正式 release（逐文件字节与中断后保留状态"
        "完全一致；已封存 payload 0o444，重写会直接 PermissionError）"
    )
    assert _snapshot_r2_completed_side_mtime_ns(interrupted_root) == (
        r2_completed_side_mtime
    ), (
        "重跑不得触碰已完成 r2 侧任何条目元数据（r2 release 子树与 r2 "
        "receipt 全部条目 mtime_ns 必须不变；字节恰好相同的重写也会更新 "
        "mtime）"
    )

    # ---- 行为 5b/6：继续并完成 r1 —— 与无中断 baseline 逐文件字节一致。----
    assert r1_release_dir.is_dir(), (
        "重跑必须完成 r1 正式 release：data/releases/data-v4.1-r1"
    )
    final_r1_content = _release_content_files(r1_release_dir)
    assert set(final_r1_content) == {"release.yaml"} | set(
        r1_declared_payload_paths
    ), (
        "重跑完成的 r1 目标 release 内容必须恰为 release.yaml + r1 manifest "
        "声明的 payload 文件集合（半写残骸被完整内容取代，不夹带非最小行为文"
        f"件）：实际 {sorted(final_r1_content)}"
    )
    r1_byte_diff = sorted(
        relative
        for relative in set(final_r1_content) | set(baseline_r1_content)
        if final_r1_content.get(relative) != baseline_r1_content.get(relative)
    )
    assert not r1_byte_diff, (
        "重跑完成的 r1 目标 release 必须与无中断 baseline 逐文件字节一致"
        "（中断恢复的“继续”必须到达与干净转换相同的正式终态）：字节不一致"
        f"的文件 {r1_byte_diff}"
    )

    # r1 receipt：八字段契约 + 两处哈希独立复算核实 + 与 baseline 语义
    # 一致（written_at 单独排除）。
    assert r1_receipt_file.is_file(), (
        "重跑完成后必须写入 r1 committed receipt（未完成对象的凭证在对象"
        "完整写入并验证后产生）"
    )
    final_r1_receipt = yaml.safe_load(r1_receipt_file.read_text(encoding="utf-8"))
    assert isinstance(final_r1_receipt, dict), (
        "重跑写入的 r1 receipt 必须是 YAML 顶层映射"
    )
    assert set(final_r1_receipt) == set(_RECEIPT_FIELDS), (
        "重跑写入的 r1 receipt 键集必须恰为八字段契约（不夹带映射项 dump 或"
        f"非契约字段）：实际 {sorted(final_r1_receipt)}"
    )
    assert final_r1_receipt["status"] == "committed", (
        "重跑写入的 r1 receipt.status 必须为 committed：实际 "
        f"{final_r1_receipt['status']!r}"
    )
    assert final_r1_receipt["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1, (
        "r1 receipt.source_legacy_id 必须为 "
        f"{CONFIRMED_DATA_SOURCE_R1!r}：实际 "
        f"{final_r1_receipt['source_legacy_id']!r}"
    )
    assert final_r1_receipt["target_identity"] == CONFIRMED_DATA_TARGET_R1, (
        "r1 receipt.target_identity 必须为 "
        f"{CONFIRMED_DATA_TARGET_R1!r}：实际 "
        f"{final_r1_receipt['target_identity']!r}"
    )
    assert final_r1_receipt["target_path"] == r1_mapping["target_path"], (
        "r1 receipt.target_path 必须与映射项声明的 target_path 一致：实际 "
        f"{final_r1_receipt['target_path']!r}"
    )
    assert final_r1_receipt["source_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(interrupted_root, CONFIRMED_DATA_SOURCE_R1).read_bytes()
    ).hexdigest(), (
        "r1 receipt.source_manifest_sha256 必须与 r1 legacy 源 manifest 文件"
        "字节哈希一致（文件字节口径，非 canonical JSON / 目录哈希 / 声明值"
        "自比；下方 legacy 快照保证该字节与转换前一致）"
    )
    assert final_r1_receipt["target_release_digest"] == (
        _recompute_target_release_digest(final_r1_content)
    ), (
        "r1 receipt.target_release_digest 必须能由重跑完成的 r1 目标 release"
        "内容按 T15 钉定口径复算验证（目标全部文件按相对 POSIX 路径升序拼接"
        "<rel>/<sha256> 行后的整体 SHA-256；digest 绑定半成品快照或漏算文件"
        "的实现必被捕获）"
    )
    _assert_receipt_semantics_match_baseline(
        final_r1_receipt, baseline_r1_receipt, CONFIRMED_DATA_TARGET_R1
    )
    _assert_receipt_semantics_match_baseline(
        final_r2_receipt, baseline_r2_receipt, CONFIRMED_DATA_TARGET_R2
    )
    assert (
        final_r1_receipt["operation_id"] != final_r2_receipt["operation_id"]
    ), (
        "r1 与 r2 的 receipt operation_id 必须互不相同（每对象一份独立凭证，"
        "不得串写）"
    )
    assert (
        final_r1_receipt["target_release_digest"]
        != final_r2_receipt["target_release_digest"]
    ), (
        "r1 与 r2 的 receipt target_release_digest 必须互不相同（各自绑定自"
        "身目标内容）"
    )

    # r2 终态与 baseline 逐文件字节一致（中断 + 恢复重跑不得使已完成对象
    # 偏离干净转换终态；与上方“中断后保留内容不变”链合成 r2 全程无偏离）。
    assert _release_content_files(r2_release_dir) == baseline_r2_content, (
        "最终 r2 正式 release 必须与无中断 baseline 逐文件字节一致"
    )

    # r1 语义读回（与 baseline 同语义）：superseded、replacement 解析为既有
    # active r2、语义字段取 r1 manifest 声明值、封存事实保持。
    r1_meta = load_release_metadata(
        interrupted_root / "data", CONFIRMED_DATA_TARGET_R1
    )
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        f"r1 release.yaml 的 version 必须为 {CONFIRMED_DATA_TARGET_R1!r}（新"
        f"体系完整身份，不得沿用 legacy 哈希身份）：实际 {r1_meta.version!r}"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        "r1 release.yaml 的 status 必须为 superseded（映射 target_status，"
        f"D1 用户确认）：实际 {r1_meta.status!r}"
    )
    assert r1_meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        "r1 release.yaml 的 replacement 必须为映射声明的 "
        f"{CONFIRMED_DATA_TARGET_R2!r}（D1 用户确认）：实际 "
        f"{r1_meta.replacement!r}"
    )
    replacement_meta = load_release_metadata(
        interrupted_root / "data", r1_meta.replacement
    )
    assert replacement_meta.version == CONFIRMED_DATA_TARGET_R2, (
        "重跑完成的 r1 replacement 必须可解析：在目标 root 下解析为既有正式"
        f"对象 {CONFIRMED_DATA_TARGET_R2!r}（批内 r2 先行完成，恢复继续的 r1 "
        f"不得悬空）：实际解析为 {replacement_meta.version!r}"
    )
    assert replacement_meta.status is DataStatus.ACTIVE, (
        "重跑完成的 r1 replacement 必须解析为既有正式 active r2（不得是悬空"
        f"引用或非 active 对象）：实际 status={replacement_meta.status!r}"
    )
    assert r1_meta.protocol == r1_manifest["contract_version"], (
        "r1 release.yaml 的 protocol 必须取 r1 legacy manifest 的 "
        f"contract_version 声明值 {r1_manifest['contract_version']!r}：实际 "
        f"{r1_meta.protocol!r}"
    )
    assert r1_meta.purpose == "development", (
        "legacy 训练 release（manifest status training_ready）的正式映射 "
        f"purpose 必须为 development：实际 {r1_meta.purpose!r}"
    )
    assert r1_meta.training_allowed is True, (
        "development 训练 release 的 training_allowed 必须为 true（拒绝新引"
        f"用只能由 superseded 状态归因）：实际 {r1_meta.training_allowed!r}"
    )
    assert r1_meta.sample_count == (
        r1_manifest["counts"]["published_candidates"]
    ), (
        "r1 sample_count 必须取 r1 legacy manifest counts.published_candidates"
        f" 声明值 {r1_manifest['counts']['published_candidates']}，不得从 "
        "payload 重算、伪造或读错源（fixture 注入声明值与 payload 可复算值 "
        "3、r2 注入声明值故意不同）"
    )
    expected_r1_splits = {
        f"fold_{fold}": {
            "train": r1_manifest["counts"]["splits"][f"fold_{fold}_train"],
            "validation": r1_manifest["counts"]["splits"][f"fold_{fold}_val"],
        }
        for fold in range(3)
    }
    assert dict(r1_meta.splits) == expected_r1_splits, (
        "r1 splits 必须取 r1 legacy manifest counts.splits 声明值"
        "（fold_N_train -> train、fold_N_val -> validation），不得从 payload"
        f" 重算或读错源：实际 {dict(r1_meta.splits)!r}"
    )
    assert set(r1_meta.source_batches) == {
        r1_manifest["source_review_batch_id"],
        r1_manifest["source_queue_id"],
        r1_manifest["source_media_id"],
    }, (
        "r1 source_batches 必须记录 r1 legacy manifest 声明的原始批次标识"
        f"（不回填伪造、不读错源）：实际 {sorted(r1_meta.source_batches)}"
    )
    try:
        assert_payload_sealed(r1_release_dir)
    except Exception as exc:
        raise AssertionError(
            "重跑完成的 r1 封存事实必须与 baseline 一致（既有只读门 "
            "assert_payload_sealed 通过；state: sealed 必须与事实一致）："
            f"{exc!r}"
        ) from exc

    # 训练引用门（正式 release 语义一致）：active r2 放行，superseded r1
    # 拒绝新引用。
    validate_training_reference(
        interrupted_root / "data", CONFIRMED_DATA_TARGET_R2
    )
    with pytest.raises(ReferenceNotAllowed):
        validate_training_reference(
            interrupted_root / "data", CONFIRMED_DATA_TARGET_R1
        )

    # ---- 行为 7：无新身份 —— 目标根恰含两个正式对象与两份 receipt。----
    releases_root = interrupted_root / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "中断 + 恢复重跑不得产生 data-v4.1-r3 或任何其他新身份/新条目（不覆"
        "盖、不自动改号；未映射 sibling 不得被转换）：data/releases/ 必须恰"
        f"含 {CONFIRMED_DATA_TARGET_R1} 与 {CONFIRMED_DATA_TARGET_R2}"
    )
    assert not (releases_root / "data-v4.1-r3").exists(), (
        "中断 + 恢复重跑不得自动改号到 data-v4.1-r3"
    )
    assert not (releases_root / UNMAPPED_DATA_SIBLING).exists(), (
        "未映射 sibling release 不得被转换（不得在 data/releases/ 下产生"
        f"任何 {UNMAPPED_DATA_SIBLING!r} 相关目标条目）"
    )
    receipts_root = interrupted_root / "migration_receipts"
    assert [entry.name for entry in sorted(receipts_root.iterdir())] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        "migration_receipts/ 必须恰含 r1 与 r2 两份 receipt（重跑不新增凭"
        "证；同一个 r1 receipt 文件由 in_progress 原子转为 committed —— 用"
        "户确认生命周期，不得另立 credential 目录/文件）"
    )

    # ---- 行为 4（重跑后）+ 全局零越界：legacy 侧不变、新增条目只允许两
    #      个目标 release 子树与两份 receipt。----
    final_tree = _snapshot_tree(interrupted_root)
    _assert_legacy_side_unchanged(interrupted_before, final_tree)
    new_keys = set(final_tree) - set(interrupted_before)
    r1_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R1}"
    r2_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R2}"
    r1_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r2_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    assert all(
        key == "data"
        or key == "data/releases"
        or key == r1_release_root_rel
        or key == r2_release_root_rel
        or key.startswith(f"{r1_release_root_rel}/")
        or key.startswith(f"{r2_release_root_rel}/")
        or key == "migration_receipts"
        or key == r1_receipt_rel
        or key == r2_receipt_rel
        for key in new_keys
    ), (
        "中断 + 恢复重跑全程只允许新增两个目标 release 目录子树（含目录条"
        f"目）与两份 receipt（不写跳过报告/缓存/records/生命周期目录，亦"
        "不得新增额外 credential 文件或目录 —— 用户确认生命周期：同一个"
        f" {r1_receipt_rel} 从 in_progress 原子转为 committed，不使用"
        " migration_receipts.in.progress/ 等独立 credential 位置）：实际"
        f"新增 {sorted(new_keys)}"
    )
    for forbidden in (
        "records",
        "working",
        "release_staging",
        "data/working",
        "data/release_staging",
    ):
        assert not (interrupted_root / forbidden).exists(), (
            f"中断 + 恢复重跑不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in final_tree), (
        "中断 + 恢复重跑不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    data_pointer_after = json.loads(
        (interrupted_root / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_after["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "中断 + 恢复重跑不得切换旧数据活动指针（仍声明 legacy 身份）"
    )
    prompt_pointer_after = yaml.safe_load(
        (interrupted_root / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_after["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "中断 + 恢复重跑不得切换旧 Prompt 活动指针（仍声明 legacy "
        "revision_id）"
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "中断 + 恢复重跑不得就地改写传入映射项（M0 事实分级保持不变）"
    )


# ---------------------------------------------------------------------------
# T19-P2：reviewer 对 T19 的 P2 —— 完整目标 + 缺失/失配 receipt 的批级
# 重跑必须干净 fail-closed：经 DataMigrationBlocked 拒绝且零写入，不得把
# 完整目标误判为可恢复半写并退化为 PermissionError（先写测试，不改
# production）
# ---------------------------------------------------------------------------


# r1 receipt 各篡改场景的字段变体值（单一变量：仅被篡改字段偏离第一次
# 转换写入的 committed 契约值，其余七字段保持原值；值均为“另一份合法
# 凭证也长这样”的形态，使拒绝只能由凭证失配归因，不得由字段格式归
# 因）。
_TAMPERED_RECEIPT_STATUS = "in_progress"
_TAMPERED_RECEIPT_OPERATION_ID = "data-migration-" + "0" * 64
_TAMPERED_RECEIPT_TARGET_RELEASE_DIGEST = "f" * 64


def _tamper_r1_committed_receipt(root: Path, scenario: str) -> None:
    r"""对已提交的 r1 committed receipt 施加缺失/内容篡改（单一变量）。

    按 scenario 施加本切片唯一的状态扰动，全程不触碰 r1/r2 目标 release、
    legacy 源、旧 active pointers 与其余任何条目：
    - ``receipt_missing``：删除 ``migration_receipts/data-v4.1-r1.receipt.yaml``
      （完整目标 + receipt 缺失）；
    - ``receipt_status_tampered`` / ``receipt_operation_id_tampered`` /
      ``receipt_target_release_digest_tampered``：receipt 文件仍存在但对应
      字段被篡改（committed -> in_progress / 另一 64-hex operation_id /
      另一 64-hex target_release_digest），其余七字段保持原值。

    内容篡改经 yaml.safe_load + safe_dump(sort_keys=False) 往返重写（与
    production receipt 写出口径一致，written_at 以带引号字符串写出、
    往返字节稳定），使篡改后的文件与原 committed receipt 恰在被篡改
    字段一处不同；被篡改的 receipt 必须保持可解析的八字段映射，使下
    方重跑的拒绝只能由凭证失配归因，不得由解析失败归因。
    """
    receipt_file = (
        root / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    assert receipt_file.is_file(), (
        "fixture 前置事实失败：篡改入口要求 r1 committed receipt 先存在"
    )
    if scenario == "receipt_missing":
        receipt_file.unlink()
        return
    receipt = yaml.safe_load(receipt_file.read_text(encoding="utf-8"))
    assert isinstance(receipt, dict) and set(receipt) == set(_RECEIPT_FIELDS), (
        "fixture 前置事实失败：r1 committed receipt 必须是八字段契约映射"
    )
    if scenario == "receipt_status_tampered":
        receipt["status"] = _TAMPERED_RECEIPT_STATUS
    elif scenario == "receipt_operation_id_tampered":
        receipt["operation_id"] = _TAMPERED_RECEIPT_OPERATION_ID
    elif scenario == "receipt_target_release_digest_tampered":
        receipt["target_release_digest"] = (
            _TAMPERED_RECEIPT_TARGET_RELEASE_DIGEST
        )
    else:
        raise AssertionError(f"未知 receipt 扰动场景: {scenario!r}")
    receipt_file.write_text(
        yaml.safe_dump(receipt, sort_keys=False), encoding="utf-8"
    )


@pytest.mark.parametrize(
    "receipt_scenario",
    [
        pytest.param("receipt_missing", id="r1_receipt_missing"),
        pytest.param(
            "receipt_status_tampered", id="r1_receipt_status_tampered"
        ),
        pytest.param(
            "receipt_operation_id_tampered",
            id="r1_receipt_operation_id_tampered",
        ),
        pytest.param(
            "receipt_target_release_digest_tampered",
            id="r1_receipt_target_release_digest_tampered",
        ),
    ],
)
def test_migrate_data_completed_batch_rerun_with_missing_or_tampered_receipt_fails_closed(
    tmp_path: Path, receipt_scenario: str
) -> None:
    r"""完整目标 + 缺失/失配 receipt 的批级重跑：干净 fail-closed，不退化为 PermissionError。

    T19-P2 behavior（reviewer 对 T19 的 P2，本切片先写测试，不改
    production）—— T19 的中断恢复把“未完成对象的半写目标”判为可恢复
    （_resumable_partial_release：现存内容为期望字节的前缀即允许重建），
    但“完整目标 + receipt 缺失/失配”时同一判定会把完整目标误判为可恢复
    半写（完整内容恰为期望字节的（自反）前缀）：目标冲突被放宽、重跑
    进入重建路径，而已封存 payload（T15-P2-1 去写位 0o444）的首个写即
    PermissionError —— 拒绝通道从 DataMigrationBlocked 退化为操作系统
    权限异常，既非干净 fail-closed，也把完整目标的处置系于文件权限位的
    偶然事实，还掩盖了“凭证缺失/失配”这一真实归因。本切片钉定：复用
    T17/T18/T19 双对象 fixture 完整执行双对象批转换（r2 active + r1
    superseded/replacement=data-v4.1-r2）、同映射完成态重跑成功后，对
    r1 的 committed receipt 施加缺失或内容篡改（r1 目标完整保留：经既有
    语义读回为 superseded 正式对象、封存事实保持），同 root、同映射、
    同 legacy 源再次调用 ``migrate_data(root, mapping_items)`` 时：
    1. 必须经 ``DataMigrationBlocked``（或其子类）fail-closed 拒绝 ——
       不得成功返回（不得把该重跑当“已完成跳过”，也不得自愈重建/
       “修复” receipt 后当成功），不得把拒绝通道错位成 PermissionError
       或任何其他异常；
    2. 拒绝必须是写入前的只读判定：异常的 cause/context 链中不得出现
       PermissionError（“先尝试重建、在已封存 payload 上写失败后再转译”
       的实现不得通过 —— 权限位是偶然事实：目标一旦未封存，同一实现
       就会真的重写完整 release）；
    3. fail-closed 拒绝零写入：完整 r1/r2 目标 release 子树逐字节不变、
       目标侧 mtime 与权限位不变（不得“先解封再重建”）；缺失的
       receipt 不得被重建、被篡改的 receipt 不得被覆盖/“修复”；剩余
       receipt（未被扰动的 r2 receipt）逐字节不变（含 written_at /
       status committed）；不产生 data-v4.1-r3 等新身份；data/releases/
       与 migration_receipts/ 精确内容不变；
    4. legacy 源和旧 pointers 不变（workspace/、finetune/、pipeline/
       子树逐字节不变；旧指针仍声明 legacy 身份）；不就地修改传入映射项；
    5. 前置对照（T18 既有行为）：扰动前同 root、同映射的完成态重跑必须
       成功跳过且零变化 —— 完整 receipt 下的正常幂等跳过不被本切片破
       坏，重跑的拒绝只能由 receipt 缺失/失配归因；
    6. 末尾对照（拒绝不得过宽/不得破坏完成态）：把 r1 receipt 恢复为
       第一次转换写入的原字节后，同 root、同映射的完成态重跑必须重新
       成功跳过且零变化（T18 既有幂等行为）。

    fixture：复用 T19 场景 helper ``_write_interrupt_scenario_layout``
    （T17/T18 同款布局与注入：三份 legacy release + 旧数据/Prompt 活动
    指针 + r2/r1 counts 场景注入 + 指针 manifest 哈希随注入重写；两条
    映射来自 ``_confirmed_data_mapping_items``，D2 推荐顺序 r2 先于
    r1），使本切片与 T17/T18/T19 在同一事实基线上叠加。receipt 扰动由
    ``_tamper_r1_committed_receipt`` 施加（receipt_missing / status 篡
    改 / operation_id 篡改 / target_release_digest 篡改四场景参数化，
    均为单一变量扰动）。

    RED Gate 设计说明（T19-P2）：migrate_data 入口、DataMigrationBlocked
    拒绝通道、T17 双对象批终态、T18 完成态幂等跳过与 T19 半写恢复均
    已存在（第一次完整转换与同映射 T18 重跑成功均为 fixture 前置事
    实，失败即 T17/T18 回归而非本切片 RED），RED 不经入口缺失分支给
    出 —— 当前 production 对“完整目标 + receipt 缺失/失配”的重跑：
    _verified_completed_receipt 判 r1 未完成，_resumable_partial_release
    把完整 r1 目标误判为可恢复半写（完整内容为期望字节的自反前缀），
    precheck 冲突经 allow_existing 放宽后 r1 进入重建路径，已封存
    payload 0o444 的首个写（datasets/train/fold_0.json）即抛
    PermissionError；本用例把该通道错位转成显式行为 AssertionError
    钉出“完整目标 + 缺失/失配 receipt 的批级重跑未干净 fail-closed”
    （原始 PermissionError 经 cause 链保留，不得直接充当 RED 结论）；
    若当前实现已满足（DataMigrationBlocked + 零写入），本用例为
    Unexpected PASS（fail-closed 回归钉），不得为此制造无意义 production
    修改。

    捕获的合理但错误实现：
    - 当前 production（RED 起点）：完整目标被判可恢复半写 -> 重建尝试
      -> 已封存 payload 首个写 PermissionError -> 通道错位 AssertionError
      （cause 链保留 PermissionError）；
    - “自愈重建”：重跑发现目标完整后重建缺失 receipt / 覆写被篡改
      receipt 并成功返回 -> “未 fail-closed 拒绝”显式 AssertionError
      （缺失 receipt 被重建 / 被篡改 receipt 被修复亦经零写入断言暴
      露）；
    - “先解封再重建”：去除 payload 写位后重写完整 release（字节恰好
      相同）-> 权限位快照 / mtime 断言失败；
    - “写失败后转译”：尝试重建、捕获 PermissionError 再包装成
      DataMigrationBlocked -> cause/context 链 PermissionError 断言失败
      （处置系于权限位偶然事实，目标未封存时即真的重写完整 release）；
    - 其他通道错位（ValueError / KeyError / OSError 等未类型化异常替
      代 DataMigrationBlocked）-> 通道错位 AssertionError；
    - 拒绝时顺手改写 release / receipt / legacy 源 / 旧 pointers / 就地
      改写传入映射项 -> 全树快照零变化 / 指针 / 映射项断言失败；
    - 拒绝过宽：扰动前的同映射 T18 重跑或恢复 receipt 后的末尾对照也被
      拒 -> 前置/末尾对照断言失败（T18 selector 同步回归可见）。

    范围边界（本切片不绑定）：拒绝信息文本与 GREEN 判定“完整目标”的
    具体机制（receipt 核实失败后如何区分完整目标与半写残骸）；半写残
    骸的可恢复重建（T19 既有行为，本切片不得回归 —— T19 selector 保
    持绿即非回归，不在此重钉）；映射字段变更的完成态失配（T18-P2 已
    钉）；批内乱序输入、migrate_data 返回值契约、CLI、DVC、训练机真实
    路径。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（本切片仅新增本
      用例与配套 fixture helper，不改 production）。
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_completed_batch_rerun_with_missing_or_tampered_receipt_fails_closed``
    - RED failure signature：恰四个失败用例（四个参数化场景
      r1_receipt_missing / r1_receipt_status_tampered /
      r1_receipt_operation_id_tampered /
      r1_receipt_target_release_digest_tampered 各一），失败信息为
      AssertionError “完整目标 + 缺失/失配 receipt 的批级重跑拒绝通道
      错位：migrate_data 对双对象批（r1 目标完整保留 + r1 receipt 缺失/
      被篡改…）的同 root、同映射、同 legacy 源重跑必须经
      DataMigrationBlocked（或其子类）fail-closed 拒绝，实际抛出
      PermissionError…”，cause 链为原始 PermissionError（“[Errno 13]
      Permission denied: …/data/releases/data-v4.1-r1/datasets/train/
      fold_0.json”）；fixture 前置事实（第一次完整转换成功、同映射
      T18 重跑成功零变化、r1 完整目标可读回且封存、receipt 扰动就位）
      全部不失败；T17/T18/T18-P2/T19 selector 保持通过。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：T17/T18/T19 同款布局与 counts 场景注入 + 指针 manifest
    #      哈希随注入重写（_write_interrupt_scenario_layout，同一事实基
    #      线：r2 published_candidates 7、r1 为 11）。----
    _write_interrupt_scenario_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items

    # ---- fixture 前置事实（注入自洽 + D1/D2 镜像 + 目标根空闲）。----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    pointer = json.loads((tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded（D1）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2（D1）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )

    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T17 既有行为不可用，本切片 fixture 前置事实"
        "失败）"
    )
    blocked_exc = getattr(
        importlib.import_module("versioning.migration"),
        "DataMigrationBlocked",
        None,
    )
    assert blocked_exc is not None, (
        "data 迁移拒绝通道缺失：versioning.migration 未提供 "
        "DataMigrationBlocked（fail-closed 必须经既有迁移拒绝通道给出，"
        "本切片 fixture 前置事实失败）"
    )

    # ---- 行为前提构造：第一次完整双对象批转换（T17 既有行为；完整目标
    #      是本切片重跑语义的前提，该处失败是 T17 回归而非本切片 RED）。----
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：当前 migrate_data 必须先成功完成双对"
            "象批的第一次完整转换（T17 既有双对象批终态行为；原始异常经"
            f"cause 链保留）：{exc!r}"
        ) from exc

    # 完成态前置事实：两个正式 release 与两份 committed receipt 均已存
    # 在（r1/r2 目标完整 —— 本切片“完整目标 + receipt 缺失/失配”场景
    # 的目标侧基线）。
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r1_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    assert r2_release_dir.is_dir(), (
        "fixture 前置事实失败：r2 正式 release 必须已创建（完成态前提）"
    )
    assert r1_release_dir.is_dir(), (
        "fixture 前置事实失败：r1 正式 release 必须已创建（完成态前提）"
    )
    r2_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    assert r2_meta.version == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r2 必须经既有语义读回为 data-v4.1-r2"
    )
    assert r2_meta.status is DataStatus.ACTIVE, (
        "fixture 前置事实失败：r2 必须经既有语义读回为 active 正式对象"
    )
    r1_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        "fixture 前置事实失败：r1 必须经既有语义读回为 data-v4.1-r1"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        "fixture 前置事实失败：r1 必须经既有语义读回为 superseded 正式"
        "对象"
    )
    assert r1_meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 已提交事实的 replacement 必须为 "
        f"{CONFIRMED_DATA_TARGET_R2!r}"
    )
    r2_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    r1_receipt_file = (
        tmp_path
        / "migration_receipts"
        / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：r2 committed receipt 必须已写入（完成态"
        "前提）"
    )
    assert r1_receipt_file.is_file(), (
        "fixture 前置事实失败：r1 committed receipt 必须已写入（完成态"
        "前提）"
    )

    # ---- 捕获完成态基线：全树字节快照 + 目标子树/receipt 字节 + receipt
    #      解析值 + 目标侧 mtime_ns 与权限位（“零写入”的次级判据）。----
    completed_tree = _snapshot_tree(tmp_path)
    r2_content_baseline = _release_content_files(r2_release_dir)
    r1_content_baseline = _release_content_files(r1_release_dir)
    assert "release.yaml" in r2_content_baseline, (
        "fixture 前置事实失败：r2 目标 release 必须含 release.yaml"
    )
    assert "release.yaml" in r1_content_baseline, (
        "fixture 前置事实失败：r1 目标 release 必须含 release.yaml"
    )
    r2_receipt_bytes = r2_receipt_file.read_bytes()
    r1_receipt_bytes = r1_receipt_file.read_bytes()
    r1_receipt_baseline = yaml.safe_load(r1_receipt_bytes)
    r2_receipt_baseline = yaml.safe_load(r2_receipt_bytes)
    for identity, receipt_baseline in (
        (CONFIRMED_DATA_TARGET_R2, r2_receipt_baseline),
        (CONFIRMED_DATA_TARGET_R1, r1_receipt_baseline),
    ):
        assert isinstance(receipt_baseline, dict), (
            f"fixture 前置事实失败：{identity} 的 receipt 必须是 YAML 顶层映射"
        )
        assert set(receipt_baseline) == set(_RECEIPT_FIELDS), (
            f"fixture 前置事实失败：{identity} 的完成态基线 receipt 键集必须"
            f"恰为八字段契约：实际 {sorted(receipt_baseline)}"
        )
        assert receipt_baseline["status"] == "committed", (
            f"fixture 前置事实失败：{identity} 的完成态基线 receipt 必须为 "
            "committed"
        )
        assert isinstance(receipt_baseline["written_at"], str) and (
            receipt_baseline["written_at"]
        ), (
            f"fixture 前置事实失败：{identity} 的 receipt.written_at 必须是"
            "非空字符串（重跑不变断言的比对基线）"
        )

    # ---- 前置对照（行为项 5，T18 既有行为）：同 root、同映射、同 legacy
    #      源的完成态重跑必须成功跳过且零变化 —— 失败即 T18 回归而非本
    #      切片 RED；该对照与下方扰动重跑构成单一变量对照（唯一差异是
    #      r1 receipt 缺失/失配）。----
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：同 root、同映射、同 legacy 源的完成态"
            "重跑必须成功跳过（T18 既有幂等跳过行为回归，非本切片 RED；"
            f"原始异常经 cause 链保留）：{exc!r}"
        ) from exc
    assert _snapshot_tree(tmp_path) == completed_tree, (
        "fixture 前置事实失败：同映射完成态重跑必须零变化（T18 既有幂等"
        "跳过行为回归：目标 release / receipt / legacy 源不得有任何字节"
        "或键集变化）"
    )

    # ---- 行为前提构造：对 r1 committed receipt 施加缺失/内容篡改（唯一
    #      扰动；r1 目标完整保留）。----
    _tamper_r1_committed_receipt(tmp_path, receipt_scenario)

    # 扰动后前置事实：r1 完整目标保留 —— 内容与完成态基线逐字节一致、经
    # 既有语义读回为 superseded 正式对象、封存事实保持（PermissionError
    # 退化的机制前提：payload 已按 T15-P2-1 去写位 0o444）；receipt 扰动
    # 就位且为唯一差异。
    assert _release_content_files(r1_release_dir) == r1_content_baseline, (
        "fixture 前置事实失败：receipt 扰动不得触碰 r1 完整目标（扰动"
        "后 r1 release 必须与完成态基线逐字节一致）"
    )
    r1_meta_tampered = load_release_metadata(
        tmp_path / "data", CONFIRMED_DATA_TARGET_R1
    )
    assert r1_meta_tampered.status is DataStatus.SUPERSEDED, (
        "fixture 前置事实失败：r1 完整目标必须仍可经既有语义读回为 "
        "superseded 正式对象（“完整目标 + receipt 缺失/失配”的目标侧"
        "前提）"
    )
    try:
        assert_payload_sealed(r1_release_dir)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：r1 完整目标的封存事实必须保持（既有"
            f"只读门 assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    if receipt_scenario == "receipt_missing":
        assert not r1_receipt_file.is_file(), (
            "fixture 前置事实失败：receipt_missing 场景要求 r1 receipt "
            "确实被删除"
        )
        expected_receipts_listing = [f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"]
    else:
        assert r1_receipt_file.is_file(), (
            "fixture 前置事实失败：receipt 篡改场景要求 r1 receipt 文件"
            "仍存在（内容被篡改而非被删除）"
        )
        tampered_r1_receipt_bytes = r1_receipt_file.read_bytes()
        tampered_r1_receipt = yaml.safe_load(
            tampered_r1_receipt_bytes.decode("utf-8")
        )
        assert isinstance(tampered_r1_receipt, dict), (
            "fixture 前置事实失败：被篡改的 r1 receipt 必须仍可解析为 "
            "YAML 顶层映射（重跑的拒绝只能由凭证失配归因，不得由解析失"
            "败归因）"
        )
        tampered_field = {
            "receipt_status_tampered": "status",
            "receipt_operation_id_tampered": "operation_id",
            "receipt_target_release_digest_tampered": "target_release_digest",
        }[receipt_scenario]
        tampered_value = {
            "receipt_status_tampered": _TAMPERED_RECEIPT_STATUS,
            "receipt_operation_id_tampered": _TAMPERED_RECEIPT_OPERATION_ID,
            "receipt_target_release_digest_tampered": (
                _TAMPERED_RECEIPT_TARGET_RELEASE_DIGEST
            ),
        }[receipt_scenario]
        assert tampered_r1_receipt[tampered_field] == tampered_value, (
            f"fixture 前置事实失败：被篡改的 r1 receipt.{tampered_field} "
            f"必须为 {tampered_value!r}：实际 {tampered_r1_receipt[tampered_field]!r}"
        )
        assert {
            key: value
            for key, value in tampered_r1_receipt.items()
            if key != tampered_field
        } == {
            key: value
            for key, value in r1_receipt_baseline.items()
            if key != tampered_field
        }, (
            "fixture 前置事实失败：被篡改的 r1 receipt 除被篡改字段外必须"
            "与其余七字段保持原值（单一变量扰动）"
        )
        assert tampered_r1_receipt_bytes != r1_receipt_bytes, (
            "fixture 前置事实失败：篡改必须确实改变 r1 receipt 字节"
        )
        expected_receipts_listing = [
            f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
            f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
        ]

    # 扰动后基线：fail-closed 拒绝“零写入”判定的比对快照（含扰动自身
    # 的效果；缺失模式下 r1 receipt 不在键集中）。
    tampered_tree = _snapshot_tree(tmp_path)
    tampered_target_side_mtime = _snapshot_target_side_mtime_ns(tmp_path)
    tampered_modes = _snapshot_modes(tmp_path)

    # ---- 行为：同 root、同映射、同 legacy 源重跑同一 migrate_data。----
    # RED Gate：当前 production 把“完整目标 + receipt 缺失/失配”经
    # _resumable_partial_release 误判为可恢复半写，冲突经 allow_existing
    # 放宽后进入重建路径，已封存 payload 的首个写即 PermissionError ——
    # 本用例把该通道错位转成显式行为 AssertionError 钉出“未干净
    # fail-closed”，原始异常经 cause 链保留；若当前实现已满足
    # （DataMigrationBlocked + 零写入），本用例为 Unexpected PASS
    # （fail-closed 回归钉）。
    blocked_error: BaseException | None = None
    try:
        migrate_data(tmp_path, mapping_items)
    except blocked_exc as exc:
        blocked_error = exc
    except Exception as exc:
        raise AssertionError(
            "完整目标 + 缺失/失配 receipt 的批级重跑拒绝通道错位："
            "migrate_data 对双对象批（r1 目标完整保留 + r1 receipt 缺失/"
            f"被篡改，场景 {receipt_scenario!r}）的同 root、同映射、同 "
            "legacy 源重跑必须经 DataMigrationBlocked（或其子类）"
            "fail-closed 拒绝，实际抛出 "
            f"{type(exc).__name__}（不得把完整目标误判为可恢复半写并退化"
            "为 PermissionError：那既非干净 fail-closed，也把完整目标的处"
            "置系于已封存 payload 权限位的偶然事实，还掩盖了凭证缺失/失"
            "配的真实归因；原始异常经 cause 链保留）："
            f"{exc!r}"
        ) from exc
    assert blocked_error is not None, (
        "完整目标 + 缺失/失配 receipt 的批级重跑未 fail-closed 拒绝"
        "（静默成功）：migrate_data 对双对象批（r1 目标完整保留 + r1 "
        f"receipt 缺失/被篡改，场景 {receipt_scenario!r}）的同 root、同"
        "映射、同 legacy 源重跑成功返回 —— 完整目标在凭证缺失/失配时既"
        "不得被当“已完成对象”跳过，也不得被自愈重建 receipt 后当成功"
        "（缺失的 receipt 被重建、被篡改的 receipt 被修复均在下方零写入"
        "断言暴露）；本切片要求干净 fail-closed：经 DataMigrationBlocked "
        "拒绝且零写入"
    )

    # 行为项 2：拒绝必须是写入前的只读判定 —— cause/context 链不得含
    # PermissionError（“先尝试重建、写失败后转译”把完整目标的处置系于
    # 文件系统权限位的偶然事实：目标一旦未封存，同一实现就会真的重写
    # 完整 release）。
    chain_types: list[str] = []
    chain_cursor: BaseException | None = blocked_error
    visited_chain: set[int] = set()
    while chain_cursor is not None and id(chain_cursor) not in visited_chain:
        visited_chain.add(id(chain_cursor))
        chain_types.append(type(chain_cursor).__name__)
        next_cause = chain_cursor.__cause__
        chain_cursor = (
            next_cause if next_cause is not None else chain_cursor.__context__
        )
    assert "PermissionError" not in chain_types, (
        "完整目标 + 缺失/失配 receipt 的 fail-closed 拒绝退化为 "
        "PermissionError 转译：DataMigrationBlocked 的异常 cause/context "
        f"链中检出 PermissionError（链 {chain_types}）—— 拒绝必须是写入"
        "前的只读判定，不得经“重建尝试 -> 已封存 payload 写失败 -> 转译”"
        "给出（权限位是偶然事实：目标未封存时同一实现会真的重写完整 "
        "release）"
    )

    # ---- 行为项 3/4：fail-closed 拒绝必须零写入 —— 全树与扰动后基线完
    #      全一致（完整目标 / 剩余 receipt / legacy 源 / 旧 pointers 逐字
    #      节不变、无新增/删除条目、不产生新身份）。----
    after_tree = _snapshot_tree(tmp_path)
    assert set(after_tree) == set(tampered_tree), (
        "fail-closed 拒绝必须零写入：不得新增或删除任何条目（缺失的 "
        "receipt 不得被重建、不产生 data-v4.1-r3 等新身份、不写报告/"
        "缓存/records、不删除既有条目）：实际新增 "
        f"{sorted(set(after_tree) - set(tampered_tree))}，实际删除 "
        f"{sorted(set(tampered_tree) - set(after_tree))}"
    )
    changed_entries = sorted(
        key
        for key, value in tampered_tree.items()
        if after_tree[key] != value
    )
    assert not changed_entries, (
        "fail-closed 拒绝必须零写入：不得改动任何条目（完整 r1/r2 目标 "
        "release 子树、剩余 receipt、legacy 源与旧 active pointers 逐字节"
        "不变；不得重建/覆盖/“修复”被扰动的 receipt）：实际改动 "
        f"{changed_entries}"
    )

    # 完整目标逐字节不变（显式重复全树结论，使该行为项在失败信息中可
    # 读归因）。
    assert _release_content_files(r1_release_dir) == r1_content_baseline, (
        "fail-closed 拒绝不得重写完整的 data/releases/data-v4.1-r1"
        "（receipt 缺失/失配不得触发对完整目标的重建或“修复”写入）"
    )
    assert _release_content_files(r2_release_dir) == r2_content_baseline, (
        "fail-closed 拒绝不得重写 data/releases/data-v4.1-r2（未被扰动的"
        "已完成对象同样零重写）"
    )

    # receipt 状态保持扰动原样：缺失的不得被重建、被篡改的不得被覆盖/
    # “修复”；剩余 r2 receipt 逐字节不变（含 written_at / status
    # committed）。
    if receipt_scenario == "receipt_missing":
        assert not r1_receipt_file.is_file(), (
            "fail-closed 拒绝不得重建缺失的 r1 receipt（凭证缺口必须经 "
            "DataMigrationBlocked 显式暴露，不得被自愈补齐后当成功跳过）"
        )
    else:
        assert r1_receipt_file.read_bytes() == tampered_r1_receipt_bytes, (
            "fail-closed 拒绝不得覆盖/“修复”被篡改的 r1 receipt（失配凭"
            "证必须经 DataMigrationBlocked 显式暴露，不得被重写回 "
            "committed 契约值后当成功跳过）"
        )
        tampered_r1_receipt_after = yaml.safe_load(
            r1_receipt_file.read_text(encoding="utf-8")
        )
        assert tampered_r1_receipt_after == tampered_r1_receipt, (
            "被篡改的 r1 receipt 内容在 fail-closed 拒绝后必须保持扰动"
            "原样（含被篡改字段值；不重算 digest、不刷新 written_at）"
        )
    assert r2_receipt_file.read_bytes() == r2_receipt_bytes, (
        "fail-closed 拒绝不得重写 r2 receipt（剩余凭证逐字节不变，含 "
        "written_at）"
    )
    r2_receipt_after = yaml.safe_load(r2_receipt_file.read_text(encoding="utf-8"))
    assert r2_receipt_after == r2_receipt_baseline, (
        "r2 receipt 内容在 fail-closed 拒绝后必须不变（八字段逐一相等，"
        "不重算 digest、不刷新时间戳）"
    )
    assert r2_receipt_after["written_at"] == r2_receipt_baseline["written_at"], (
        "r2 receipt.written_at 在 fail-closed 拒绝后必须不变（凭证未被重写）"
    )
    assert r2_receipt_after["status"] == "committed", (
        "r2 receipt.status 在 fail-closed 拒绝后必须仍为 committed"
    )

    # 无新身份 —— data/releases/ 恰含 r1、r2；migration_receipts/ 恰含
    # 各场景扰动后的 receipt 集合。
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "fail-closed 拒绝不得产生任何新身份/新条目（不覆盖、不自动改"
        f"号）：data/releases/ 必须恰含 {CONFIRMED_DATA_TARGET_R1} 与 "
        f"{CONFIRMED_DATA_TARGET_R2}"
    )
    assert not (tmp_path / "data" / "releases" / "data-v4.1-r3").exists(), (
        "fail-closed 拒绝不得自动改号到 data-v4.1-r3"
    )
    receipts_root = tmp_path / "migration_receipts"
    actual_receipts_listing = [
        entry.name for entry in sorted(receipts_root.iterdir())
    ]
    assert actual_receipts_listing == expected_receipts_listing, (
        "migration_receipts/ 必须恰含各场景扰动后的 receipt 集合（拒绝"
        "不新增/不重建/不删除凭证）：实际 "
        f"{actual_receipts_listing}，期望 {expected_receipts_listing}"
    )

    # 无重写的次级判据：目标侧全部条目 mtime_ns 不变；权限位不变（不重
    # 新封存、不改写位、不得“先解封再重建”）。
    assert _snapshot_target_side_mtime_ns(tmp_path) == tampered_target_side_mtime, (
        "fail-closed 拒绝不得触碰目标侧任何条目元数据（data/ 与 "
        "migration_receipts/ 子树全部条目 mtime_ns 必须不变；字节恰好"
        "相同的重写也会更新 mtime）"
    )
    assert _snapshot_modes(tmp_path) == tampered_modes, (
        "fail-closed 拒绝不得改动任何条目权限位（不重新封存、不改写位、"
        "不得先解封再重建完整目标）"
    )

    # legacy 源和旧 pointers 不变（全树快照已钉定；此处显式钉旧指针仍
    # 声明 legacy 身份，使失败信息可读归因）。
    data_pointer_after = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_after["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fail-closed 拒绝不得切换旧数据活动指针（仍声明 legacy 身份）"
    )
    prompt_pointer_after = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_after["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "fail-closed 拒绝不得切换旧 Prompt 活动指针（仍声明 legacy "
        "revision_id）"
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "fail-closed 拒绝不得就地改写传入映射项（M0 事实分级保持不变）"
    )

    # ---- 末尾对照（行为项 6，拒绝不得过宽/不得破坏完成态）：把 r1
    #      receipt 恢复为第一次转换写入的原字节后，同 root、同映射的
    #      完成态重跑必须重新成功跳过且零变化（T18 既有幂等行为）——
    #      拒绝只能由 receipt 缺失/失配归因。----
    r1_receipt_file.write_bytes(r1_receipt_bytes)
    assert _snapshot_tree(tmp_path) == completed_tree, (
        "末尾对照前提失败：恢复 r1 receipt 原字节后，整树必须回到完成态"
        "基线（fail-closed 拒绝未破坏完成态；任何残留改动都在此暴露）"
    )
    restored_target_side_mtime = _snapshot_target_side_mtime_ns(tmp_path)
    restored_modes = _snapshot_modes(tmp_path)
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "拒绝过宽或完成态被破坏：恢复 r1 receipt 原字节（第一次转换"
            "写入的 committed 契约值）后的同 root、同映射完成态重跑必须"
            "重新成功跳过（T18 既有幂等行为；若此处失败，说明前述 "
            "fail-closed 拒绝破坏了完成态凭证，或拒绝条件过宽到拒绝了"
            f"凭证匹配的正常重跑；原始异常经 cause 链保留）：{exc!r}"
        ) from exc
    assert _snapshot_tree(tmp_path) == completed_tree, (
        "恢复 r1 receipt 后的完成态重跑必须零变化（T18 既有幂等跳过行为："
        "目标 release / receipt / legacy 源不得有任何字节或键集变化）"
    )
    assert _snapshot_target_side_mtime_ns(tmp_path) == restored_target_side_mtime, (
        "恢复 r1 receipt 后的完成态重跑不得重写目标侧任何条目（幂等跳"
        "过：data/ 与 migration_receipts/ 子树全部条目 mtime_ns 不变）"
    )
    assert _snapshot_modes(tmp_path) == restored_modes, (
        "恢复 r1 receipt 后的完成态重跑不得改动任何条目权限位（不重新"
        "封存、不改写位）"
    )


# ---------------------------------------------------------------------------
# T19-P3：D2 关键安全边界 —— 中断后 legacy 源内容发生变化（使恢复依据失
# 配）时，同 root、相同映射的重跑必须停止：经 DataMigrationBlocked 干净
# fail-closed 且零写入，不得跳过失配对象、不得继续写入未完成对象、不得
# 重写已完成对象或其凭证、不得产生新身份（先写测试，不改 production）
# ---------------------------------------------------------------------------

# 场景 r2_completed_source_manifest_changed 的注入变体值：r2 legacy
# manifest counts.published_candidates 7 -> 8（与 T17/T18/T19 注入值 7 故
# 意不同，使 r2 receipt 绑定的 source_manifest_sha256 与按当前源期望的
# release.yaml 语义内容同时失配）。
_R2_CHANGED_PUBLISHED_CANDIDATES = 8

# 场景 r1_partial_source_payload_changed 的等长替换标记（与 T14 的
# _tamper_declared_payload_file 同款口径："fold": 0 -> "fold": 9 —— 字节
# 改变、长度不变、JSON 仍合法）。该字段位于 payload 文件头部，落在中断
# 注入写下的严格前缀区域内，使 r1 半写残骸不再是按当前源复算期望字节
# 的（严格）前缀。
_PREFIX_REGION_MARKER = b'"fold": 0'
_PREFIX_REGION_REPLACEMENT = b'"fold": 9'


def _change_completed_r2_legacy_source_manifest(root: Path) -> dict[str, bytes]:
    r"""修改已完成对象 r2 的 legacy 源 manifest，返回原字节供末尾对照恢复。

    场景 r2_completed_source_manifest_changed 的单一变量扰动：仅改
    counts.published_candidates（7 -> _R2_CHANGED_PUBLISHED_CANDIDATES）。
    payload 与 manifest files[] 声明哈希不动（T14 manifest 自洽门保持
    绿）；旧数据活动指针 expected_manifest_sha256 随修改后 manifest 字节
    复算重写（T13 已钉扎 manifest provenance 门保持绿）—— 两个既有只读门
    均不阻塞，使下方重跑的拒绝只能由恢复依据失配（receipt 绑定源摘要与
    期望内容）归因，不得由指针门或 manifest 自洽门归因。
    """
    manifest_bytes_original = _manifest_file_of(
        root, CONFIRMED_DATA_SOURCE_R2
    ).read_bytes()
    pointer_bytes_original = (root / _DATA_POINTER_REL).read_bytes()
    manifest = json.loads(manifest_bytes_original.decode("utf-8"))
    manifest["counts"]["published_candidates"] = (
        _R2_CHANGED_PUBLISHED_CANDIDATES
    )
    changed_manifest_bytes = _rewrite_legacy_release_manifest(
        root, CONFIRMED_DATA_SOURCE_R2, manifest
    )
    pointer = json.loads(pointer_bytes_original.decode("utf-8"))
    pointer["expected_manifest_sha256"] = hashlib.sha256(
        changed_manifest_bytes
    ).hexdigest()
    _rewrite_legacy_data_pointer(root, pointer)
    return {
        "r2_manifest": manifest_bytes_original,
        "pointer": pointer_bytes_original,
    }


def _change_partial_r1_legacy_source_payload(
    root: Path, r1_release_dir: Path, struck_path: Path
) -> dict[str, Any]:
    r"""修改未完成对象 r1 的 legacy 源 payload，返回原字节与失配事实。

    场景 r1_partial_source_payload_changed 的单一变量扰动：定位中断注入实
    际命中的那份 payload（struck_path 相对 r1 目标 release 根的声明路径），
    对 legacy 源文件做等长替换（_PREFIX_REGION_MARKER ->
    _PREFIX_REGION_REPLACEMENT），替换位置必须落在注入写下的严格前缀区域
    内（以实际落盘的半写字节为准断言），使 r1 半写残骸不再是按当前源复算
    期望字节的（严格）前缀；manifest files[] 对应 entry 的 sha256 /
    size_bytes 随改复算重写（T14 manifest 自洽门保持绿 —— 拒绝不得由
    manifest 声明哈希门归因）。

    返回键：declared_rel（声明路径）、original_payload / tampered_payload
    （改前/改后 payload 字节）、partial_present（目标内实际落盘的半写字
    节）、r1_manifest（改前 manifest 原字节）—— 后者供末尾对照恢复。
    """
    declared_rel = struck_path.relative_to(r1_release_dir).as_posix()
    payload_file = _payload_file_of(root, CONFIRMED_DATA_SOURCE_R1, declared_rel)
    original_payload = payload_file.read_bytes()
    assert _PREFIX_REGION_MARKER in original_payload, (
        "fixture 前置事实失败：被中断命中的 r1 payload 应含头部字段标记 "
        f"{_PREFIX_REGION_MARKER!r}（fixture 布局漂移需同步维护本场景的替"
        "换标记）"
    )
    partial_present = (r1_release_dir / declared_rel).read_bytes()
    assert (
        0 < len(partial_present) < len(original_payload)
        and original_payload.startswith(partial_present)
    ), (
        "fixture 前置事实失败：r1 目标内被中断命中的文件必须是 legacy 源"
        "对应文件字节的非空严格前缀（T19 注入的写盘中途中断形态；写入机制"
        "变更时需随实际写路径维护）"
    )
    marker_position = original_payload.index(_PREFIX_REGION_MARKER)
    assert marker_position < len(partial_present), (
        "fixture 前置事实失败：等长替换必须落在半写前缀区域内（位置 "
        f"{marker_position} >= 半写长度 {len(partial_present)}），否则半写"
        "内容仍是改后期望字节的前缀，恢复依据未失配"
    )
    tampered_payload = original_payload.replace(
        _PREFIX_REGION_MARKER, _PREFIX_REGION_REPLACEMENT, 1
    )
    assert len(tampered_payload) == len(original_payload) and (
        tampered_payload != original_payload
    ), "fixture 前置事实失败：替换必须改变字节且保持等长（size 声明自洽）"
    assert not tampered_payload.startswith(partial_present), (
        "fixture 前置事实失败：修改后 r1 半写残骸必须不再是按当前源复算期"
        "望字节的（严格）前缀（恢复依据失配的事实前提）"
    )
    payload_file.write_bytes(tampered_payload)
    manifest_bytes_original = _manifest_file_of(
        root, CONFIRMED_DATA_SOURCE_R1
    ).read_bytes()
    manifest = json.loads(manifest_bytes_original.decode("utf-8"))
    entry = _manifest_files_entry(manifest, declared_rel)
    entry["sha256"] = hashlib.sha256(tampered_payload).hexdigest()
    entry["size_bytes"] = len(tampered_payload)
    _rewrite_legacy_release_manifest(root, CONFIRMED_DATA_SOURCE_R1, manifest)
    return {
        "declared_rel": declared_rel,
        "original_payload": original_payload,
        "tampered_payload": tampered_payload,
        "partial_present": partial_present,
        "r1_manifest": manifest_bytes_original,
    }


@pytest.mark.parametrize(
    "source_change_scenario",
    [
        pytest.param(
            "completed_object_source_changed",
            id="r2_completed_source_manifest_changed",
        ),
        pytest.param(
            "partial_object_source_changed",
            id="r1_partial_source_payload_changed",
        ),
    ],
)
def test_migrate_data_interrupted_batch_rerun_after_legacy_source_change_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_change_scenario: str,
) -> None:
    r"""中断后 legacy 源内容变化使恢复依据失配的重跑：fail-closed 拒绝且零写入。

    T19-P3 behavior（D2 关键安全边界，先写测试，不改 production）—— D2
    已确认（T19 同款表述）：中断后重跑同一次转换，凭证匹配的已完成对象
    跳过，未完成对象继续；凭证不匹配或无法核实即停止，不覆盖、不改号。
    本切片钉“恢复依据失配”的中断后重跑：复用 T19 中断 fixture（双对象批
    [r2, r1] 第一次转换 r2 完成、r1 目标写入中途被中断：r2 完整正式
    release + committed receipt，r1 半写残骸 + 无 committed receipt ——
    同一个 migration_receipts/data-v4.1-r1.receipt.yaml 按用户确认生命
    周期以 in_progress 状态保留（写入前 status: in_progress、
    target_release_digest: null，T19-P4 钉字段绑定契约；不得另立
    credential 目录）），在第一次中断
    后修改 legacy 源内容使恢复依据失配（两个参数化场景，单一变量扰动）：
    1. 已完成对象 r2 的源变化（r2_completed_source_manifest_changed）：
       r2 legacy manifest counts.published_candidates 7 -> 8（旧数据活动指
       针 expected_manifest_sha256 随改复算保持 T13 钉扎门绿、files[] 声明
       哈希不动保持 T14 自洽门绿）—— r2 receipt 绑定的 source_manifest_
       sha256（连带 operation_id 派生 payload 与期望 release.yaml 内容）
       不再匹配当前源；
    2. 未完成对象 r1 的源变化（r1_partial_source_payload_changed）：r1
       legacy payload（中断注入实际命中的那份文件）在半写前缀区域内等长
       变更（manifest 声明哈希随改复算保持 T14 自洽门绿）—— r1 半写残骸
       不再是按当前源复算期望字节的（严格）前缀。
    同 root、相同映射（legacy 源内容已被本测试主动修改）重跑同一
    ``migrate_data`` 时：
    3. 必须经 ``DataMigrationBlocked``（或其子类）fail-closed 拒绝 —— 不
       得成功返回（不得把失配的 r2 当“凭证匹配的已完成对象”跳过、不得把
       失配的 r1 半写判为“可恢复”继续重建），不得把拒绝通道错位成
       PermissionError 或任何其他异常；
    4. 拒绝必须是写入前的只读判定：异常 cause/context 链不得含
       PermissionError（“先尝试重建/续写、写失败后再转译”不得通过 —— 权
       限位是偶然事实，目标未封存时同一实现就会真的写入）；
    5. fail-closed 拒绝零写入：整树（含测试主动修改的 legacy 源字节）与修
       改后基线逐字节一致、目标侧 mtime 与权限位不变 —— 已完成 r2 正式
       release 与 receipt 逐字节不变（不重写、不刷新 written_at、不重算
       digest、不“重新封存”）、r1 半写残骸逐字节原样（不继续写入、不清
       理、不重建）、migration_receipts/ 不新增凭证也不删除既有凭证（不
       把中断后保留的同一个 r1 in-progress receipt 补写/覆盖为 committed，
       逐字节原样；不得另立 migration_receipts.in.progress/ 等额外
       credential 目录/文件 —— 用户确认生命周期：中断后保留同一个
       migration_receipts/data-v4.1-r1.receipt.yaml，status 保持
       in_progress）、不产生 data-v4.1-r3 等新身份、不
       写 records / 生命周期目录 / .dvc；
    6. legacy 侧零额外变化：除测试主动修改的源文件（保持测试写出的字节
       原样）外，旧 pointers 与其余 legacy 内容不被重跑触碰（全树快照钉
       定）；不就地修改传入映射项；
    7. 末尾对照（拒绝不得过宽 / 不得破坏恢复路径）：把被修改的 legacy 源
       恢复为原字节后，同 root、同映射的重跑必须重新成功（T19 既有中断恢
       复行为：跳过凭证匹配的已完成 r2、继续并完成 r1）—— 拒绝只能由源
       内容变化归因；完成的 r1 读回为 superseded、replacement 解析为既有
       active r2、语义字段取（已恢复的）manifest 声明值、封存事实保持、
       receipt 八字段可独立复算核实；同一个 r1 receipt 文件由（中断后保
       留的）in_progress 原子转为 committed receipt（用户确认生命周期，
       允许且必要；完成后不额外保留 in-progress 状态，不得新增额外
       credential 文件或目录）；r2 侧零重
       写（receipt 字节与 mtime 不动）；
    8. 本切片不做凭证失配消息优化（拒绝信息文本与“失配”归因通道不绑
       定）、不做批内乱序输入、migrate_data 返回值契约、跳过/继续的报告
       通道、CLI、DVC、训练机真实路径。

    fixture：复用 T19 场景 helper ``_write_interrupt_scenario_layout`` 与
    ``_install_r1_target_mid_write_interruption``（T17/T18/T19 同款布局：
    三份 legacy release + 旧数据/Prompt 活动指针 + r2/r1 counts 场景注入
    （r2 published_candidates 7、r1 为 11）+ r2 指针 manifest 哈希随注入
    复算；两条映射来自 ``_confirmed_data_mapping_items``，D2 推荐顺序 r2
    先于 r1）。T19 的并行双根在本切片简化为单根：本切片重跑主路径是拒绝
    （无成功终态需要 baseline 对照），末尾对照（恢复源后重跑成功）即
    T19 既有恢复成功路径的复验。

    RED Gate 设计说明（T19-P3）：migrate_data 入口、DataMigrationBlocked
    拒绝通道、T17 双对象批终态与 T19 中断恢复均已存在（第一次中断调用成
    功构造批内部分完成状态为 fixture 前置事实，失败即 T19 回归而非本切
    片 RED），RED 不经入口缺失分支给出 —— 当前 production 对“恢复依据失
    配”的重跑：已完成对象的 receipt 核实逐字段绑定 source_manifest_
    sha256（+ operation_id 派生 payload + target_release_digest），源变化
    即核实失败、不进入已完成跳过；未完成对象的半写核实要求现存内容为按
    当前源复算期望字节的（严格）前缀，源变化即不可核实、不进入可恢复重
    建；两者均退回既有 fail-closed 预检目标冲突门，以 DataMigrationBlocked
    干净拒绝且零写入 —— 本用例按本轮 TDD 约束为 Unexpected PASS（转为
    fail-closed 回归钉），不得为此制造无意义 production 修改。

    捕获的合理但错误实现：
    - “只看 receipt 存在即跳过”：已完成对象不做 source_manifest_sha256
      核实（或核实不绑定源内容）即跳过 r2、继续 r1 -> 重跑成功返回 ->
      行为 3 的“静默成功”AssertionError；
    - “半写一律可恢复”：不按当前源复算期望字节即重建 r1（或先落盘再比
      对）-> 重跑写入 r1 -> 行为 5 的 r1 残骸逐字节断言失败（或已封存场
      景退化 PermissionError -> 行为 3/4 断言失败）；
    - “重做失配对象”：对源变化的 r2 重建/重写 release 或 receipt（重新
      封存、刷新 written_at、重算 digest 绑定新源）-> 行为 5 的 r2 侧逐
      字节 / mtime / 权限位断言失败（已封存 payload 0o444 重写即
      PermissionError，行为 4 链检查同报）；
    - “改号续跑”：跳过失配对象后自动改号新身份 -> 行为 5 的整树 / 新身
      份断言失败；
    - 通道错位：以 PermissionError / ValueError / OSError 等未类型化异
      常替代 DataMigrationBlocked -> 行为 3 通道错位 AssertionError；
    - “先写后拒”：先尝试写入、失败后再转译拒绝 -> 行为 4 cause 链
      PermissionError 断言失败（处置系于权限位偶然事实）；
    - 拒绝时顺手改写 legacy 源 / 旧 pointers / 就地改写传入映射项 -> 行
      为 5/6 全树快照与映射项断言失败；
    - 拒绝过宽：源恢复原字节后的末尾对照重跑也被拒 -> 行为 7 断言失败
      （T19 selector 同步回归可见）。

    范围边界（本切片不绑定）：拒绝信息文本与 GREEN 判定“恢复依据失配”
    的具体归因通道（当前实现经既有 fail-closed 预检目标冲突门拒绝，不要
    求专门失配消息）；r1 legacy manifest 的 counts 类字段变更但半写前缀区
    域不受影响时（半写内容仍是按当前源复算期望字节的前缀，恢复依据未失
    配），当前实现按 D2“未完成对象继续”以当前（预检全量验证过的）源完
    成 r1 —— 该形态不属本切片“使恢复依据失配”场景，如需钉定“中断时刻
    源内容快照绑定”须另立切片（当前架构未持久化部分写入对象的源摘要，
    无法区分“源从未变化”与“源在不影响已落盘前缀的区域变化”）；映射字
    段变更的完成态失配（T18-P2 已钉 replacement 变更分支）、receipt 自身
    缺失/被篡改的完整目标重跑（T19-P2 已钉）、批内乱序输入、migrate_data
    返回值契约、CLI、DVC、训练机真实路径。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（本切片仅新增本
      用例与配套 fixture helper 及模块 docstring 清单条目，不改
      production）。
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_interrupted_batch_rerun_after_legacy_source_change_fails_closed``
    - RED/Unexpected PASS signature（本轮契约统一后）：当前 production
      把 credential 写在 migration_receipts.in.progress/ 独立目录，同
      一个 migration_receipts/data-v4.1-r1.receipt.yaml 缺失 —— 两个
      参数化用例均在中断后 fixture 前置事实上失败（AssertionError “同
      一个 receipt 文件 migration_receipts/data-v4.1-r1.receipt.yaml
      必须存在（用户确认生命周期…）”）；production 返工到同一文件生命
      周期后：恰两个参数化用例
      （r2_completed_source_manifest_changed /
      r1_partial_source_payload_changed）全部通过；fixture 前置事实（布
      局自洽、空目标根 precheck ready、第一次调用被中断命中且显式失败、
      r2 完成保留、r1 半写且同一个 receipt 文件为 in_progress、源修改后
      失配事实成立且 T13/T14
      既有门保持绿）全部不失败；拒绝经 DataMigrationBlocked 给出且零写
      入（同一个 r1 in-progress receipt 逐字节原样）；末尾对照恢复源原
      字节后重跑成功完成 r1（T19 行为不回归；同一个 receipt 文件原子转
      为 committed）。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：T17/T18/T19 同款布局与 counts 场景注入 + 指针 manifest
    #      哈希随注入重写（同一事实基线：r2 published_candidates 7、r1 为
    #      11）。----
    _write_interrupt_scenario_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items

    # ---- fixture 前置事实（注入自洽 + D1/D2 镜像 + 目标根空闲）。----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    pointer = json.loads((tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded（D1）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2（D1）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )
    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T19 既有行为不可用，本切片 fixture 前置事实失"
        "败）"
    )
    blocked_exc = getattr(
        importlib.import_module("versioning.migration"),
        "DataMigrationBlocked",
        None,
    )
    assert blocked_exc is not None, (
        "data 迁移拒绝通道缺失：versioning.migration 未提供 "
        "DataMigrationBlocked（fail-closed 必须经既有迁移拒绝通道给出，本"
        "切片 fixture 前置事实失败）"
    )
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（T11 既有行为不可用，本切片 fixture "
        "前置事实失败）"
    )
    dual_precheck_report = precheck(tmp_path, mapping_items)
    assert dual_precheck_report.status == "ready", (
        "fixture 前置事实失败：空目标根上双对象批（r2+r1，D2 推荐顺序）的"
        f"只读预检必须整批 ready（实际 {dual_precheck_report.status!r}，"
        f"reasons={dual_precheck_report.reasons!r}）—— 第一次调用的失败只"
        "能由注入中断归因"
    )

    interrupted_before = _snapshot_tree(tmp_path)
    r1_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R1

    # ---- 行为前提构造：安装 r1 目标写中途中断（T19 同款注入）。----
    struck_writes: list[Path] = []
    interruption = _install_r1_target_mid_write_interruption(
        monkeypatch, r1_release_dir, struck_writes
    )
    first_call_error: BaseException | None = None
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        first_call_error = exc
    assert first_call_error is not None, (
        "双对象批第一次调用必须在 r1 写入中途注入失败后显式失败（T19 既"
        "有批内部分完成状态构造，中断不得被吞掉后当作成功返回）"
    )
    assert struck_writes, (
        "中断注入失效：第一次调用的 r1 目标写入未被命中（T19 注入点契约："
        "struck_writes 为空即注入点需随实际写路径维护，本切片的场景构造依"
        "赖 r1 半写残骸真实存在）"
    )
    assert all(
        path.is_relative_to(r1_release_dir) for path in struck_writes
    ), (
        "中断注入命中范围异常：被中断的写入必须全部落在 r1 目标子树 "
        f"data/releases/{CONFIRMED_DATA_TARGET_R1}/ 内：实际 "
        f"{sorted(struck_writes)}"
    )

    # ---- 批内部分完成状态前置事实（T19 既有行为）：r2 完整完成 + committed
    #      receipt 保留，r1 半写残骸 + 同一个 receipt 文件以 in_progress
    #      状态保留（用户确认生命周期，下方断言钉定）。----
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r2_receipt_file = (
        tmp_path / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    r1_receipt_file = (
        tmp_path / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r2_meta_after_interrupt = load_release_metadata(
        tmp_path / "data", CONFIRMED_DATA_TARGET_R2
    )
    assert r2_meta_after_interrupt.status is DataStatus.ACTIVE, (
        "fixture 前置事实失败：中断后 r2 必须经既有语义读回为 active 正式"
        "对象（批内部分完成状态的已完成侧前提）"
    )
    try:
        assert_payload_sealed(r2_release_dir)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：中断后保留的 r2 封存事实必须保持（既有"
            f"只读门 assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：中断后 r2 committed receipt 必须已写入（已"
        "完成对象的凭证是本切片恢复依据失配场景的绑定对象）"
    )
    r2_completed_receipt_bytes = r2_receipt_file.read_bytes()
    r2_completed_receipt = yaml.safe_load(
        r2_completed_receipt_bytes.decode("utf-8")
    )
    assert isinstance(r2_completed_receipt, dict), (
        "fixture 前置事实失败：r2 receipt 必须是 YAML 顶层映射"
    )
    assert set(r2_completed_receipt) == set(_RECEIPT_FIELDS), (
        "fixture 前置事实失败：r2 receipt 键集必须恰为八字段契约：实际 "
        f"{sorted(r2_completed_receipt)}"
    )
    assert r2_completed_receipt["status"] == "committed", (
        "fixture 前置事实失败：r2 receipt 必须为 committed"
    )
    # 同一个 receipt 文件按用户确认生命周期以 in_progress 状态保留（写入
    # 前 status: in_progress、target_release_digest: null；T19-P4 钉字段
    # 绑定契约）：中断后必须存在且不伪称 committed —— 当前 production
    # 偏离用户裁决（credential 写在 migration_receipts.in.progress/ 独
    # 立目录、同一 receipt 文件缺失）时在此显式失败。字节快照供拒绝后
    # 逐字节不变比对。
    r1_manifest_sha256_at_interruption = hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).read_bytes()
    ).hexdigest()
    r1_receipt_bytes_after_interrupt = _assert_same_file_in_progress_receipt(
        r1_receipt_file,
        CONFIRMED_DATA_TARGET_R1,
        r1_mapping,
        r1_manifest_sha256_at_interruption,
        context="fixture 前置事实失败（中断后）",
    )
    r1_partial_content = _release_content_files(r1_release_dir)
    assert r1_partial_content, (
        "fixture 前置事实失败：中断后 r1 目标内必须存在半写残骸（本切片"
        "场景构造依赖“已有部分写入”这一事实）"
    )
    _assert_legacy_side_unchanged(interrupted_before, _snapshot_tree(tmp_path))
    assert mapping_items == _confirmed_data_mapping_items(), (
        "fixture 前置事实失败：中断失败路径不得就地改写传入映射项"
    )

    # ---- 状态快照：中断后保留状态（末尾对照与 r2 侧零重写的比对基线）。----
    interrupted_tree = _snapshot_tree(tmp_path)
    r2_completed_content = _release_content_files(r2_release_dir)
    r2_completed_side_mtime = _snapshot_r2_completed_side_mtime_ns(tmp_path)
    r1_manifest_declared = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).read_text(
            encoding="utf-8"
        )
    )
    r1_declared_payload_paths = sorted(
        entry["path"] for entry in r1_manifest_declared["files"]
    )

    # ---- 行为前提构造：解除注入后修改 legacy 源内容，使恢复依据失配。----
    interruption.armed = False
    if source_change_scenario == "completed_object_source_changed":
        changed_source = _change_completed_r2_legacy_source_manifest(tmp_path)
        changed_r2_manifest_bytes = _manifest_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R2
        ).read_bytes()
        assert hashlib.sha256(
            changed_r2_manifest_bytes
        ).hexdigest() != r2_completed_receipt["source_manifest_sha256"], (
            "fixture 前置事实失败：r2 源修改后 receipt 绑定的 "
            "source_manifest_sha256 必须失配（本场景的恢复依据失配事实前"
            "提）"
        )
        changed_r2_manifest = json.loads(
            changed_r2_manifest_bytes.decode("utf-8")
        )
        assert changed_r2_manifest["counts"]["published_candidates"] != (
            r2_meta_after_interrupt.sample_count
        ), (
            "fixture 前置事实失败：修改后 r2 manifest 声明值必须与已完成 "
            "r2 release 记录的语义内容不同（期望内容失配）"
        )
        pointer_after_change = json.loads(
            (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
        )
        assert pointer_after_change["expected_manifest_sha256"] == (
            hashlib.sha256(changed_r2_manifest_bytes).hexdigest()
        ), (
            "fixture 前置事实失败：指针 expected_manifest_sha256 必须随修"
            "改后 r2 manifest 复算（T13 钉扎门保持绿，重跑的拒绝不得由指"
            "针门归因）"
        )
        _assert_payload_declared_hashes_self_consistent(
            tmp_path, CONFIRMED_DATA_SOURCE_R2
        )
    else:
        changed_source = _change_partial_r1_legacy_source_payload(
            tmp_path, r1_release_dir, struck_writes[0]
        )
        assert changed_source["declared_rel"] in set(r1_declared_payload_paths), (
            "fixture 前置事实失败：被中断命中的文件必须是 r1 manifest "
            "files[] 声明的 payload（注入点契约：写入机制变更时需随实际写"
            "路径维护）"
        )
        _assert_payload_declared_hashes_self_consistent(
            tmp_path, CONFIRMED_DATA_SOURCE_R1
        )
        pointer_after_change = json.loads(
            (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
        )
        assert pointer_after_change["expected_manifest_sha256"] == hashlib.sha256(
            _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
        ).hexdigest(), (
            "fixture 前置事实失败：本场景不触碰 r2 源，指针与 r2 manifest "
            "必须保持自洽（T13 钉扎门保持绿，重跑的拒绝不得由指针门归因）"
        )

    # ---- 修改后基线：fail-closed 拒绝“零写入”判定的比对快照（含测试主
    #      动修改的源字节自身）。----
    tampered_tree = _snapshot_tree(tmp_path)
    tampered_target_side_mtime = _snapshot_target_side_mtime_ns(tmp_path)
    tampered_modes = _snapshot_modes(tmp_path)

    # ---- 行为 3/4：同 root、相同映射重跑 —— 必须经 DataMigrationBlocked
    #      fail-closed 拒绝（RED Gate：当前 production 干净拒绝时本用例为
    #      Unexpected PASS / fail-closed 回归钉）。----
    blocked_error: BaseException | None = None
    try:
        migrate_data(tmp_path, mapping_items)
    except blocked_exc as exc:
        blocked_error = exc
    except Exception as exc:
        raise AssertionError(
            "中断后 legacy 源内容变化的重跑拒绝通道错位：migrate_data 对双"
            "对象批（r2 已完成保留 + r1 写入中途被中断，中断后 legacy 源内"
            f"容已修改使恢复依据失配，场景 {source_change_scenario!r}）的"
            "同 root、相同映射重跑必须经 DataMigrationBlocked（或其子类）"
            f"fail-closed 拒绝，实际抛出 {type(exc).__name__}（不得以未类型"
            "化异常替代迁移域错误通道；原始异常经 cause 链保留）："
            f"{exc!r}"
        ) from exc
    assert blocked_error is not None, (
        "中断后 legacy 源内容变化的重跑未 fail-closed 拒绝（静默成功）："
        "migrate_data 对双对象批（r2 已完成保留 + r1 写入中途被中断，中"
        f"断后 legacy 源内容已修改使恢复依据失配，场景 "
        f"{source_change_scenario!r}）的同 root、相同映射重跑成功返回 —— "
        "恢复依据失配时既不得把失配的已完成对象当“凭证匹配”跳过，也不得"
        "把失配的半写对象当“可恢复”继续重建；本切片要求停止：经 "
        "DataMigrationBlocked fail-closed 拒绝且零写入"
    )

    # 行为 4：拒绝必须是写入前的只读判定 —— cause/context 链不得含
    # PermissionError（“先尝试重建/续写、写失败后再转译”把处置系于文件系
    # 统权限位的偶然事实，不得通过）。
    chain_types: list[str] = []
    chain_cursor: BaseException | None = blocked_error
    visited_chain: set[int] = set()
    while chain_cursor is not None and id(chain_cursor) not in visited_chain:
        visited_chain.add(id(chain_cursor))
        chain_types.append(type(chain_cursor).__name__)
        next_cause = chain_cursor.__cause__
        chain_cursor = (
            next_cause if next_cause is not None else chain_cursor.__context__
        )
    assert "PermissionError" not in chain_types, (
        "恢复依据失配的 fail-closed 拒绝退化为 PermissionError 转译："
        "DataMigrationBlocked 的异常 cause/context 链中检出 "
        f"PermissionError（链 {chain_types}）—— 拒绝必须是写入前的只读判"
        "定，不得经“重建尝试 -> 写失败 -> 转译”给出（权限位是偶然事实："
        "目标未封存时同一实现会真的写入失配内容）"
    )

    # ---- 行为 5/6：fail-closed 拒绝必须零写入 —— 整树与修改后基线逐字节
    #      一致（含测试主动修改的源文件保持原样）。----
    after_tree = _snapshot_tree(tmp_path)
    tree_changed = sorted(
        key
        for key in set(tampered_tree) | set(after_tree)
        if tampered_tree.get(key) != after_tree.get(key)
    )
    assert not tree_changed, (
        "恢复依据失配的 fail-closed 拒绝必须零写入：整树（含测试主动修"
        "改的 legacy 源、旧 active pointers、已完成 r2 release/receipt、"
        "r1 半写残骸）必须与修改后基线逐字节一致（不继续写入 r1、不重建"
        "r1、不补写 r1 receipt、不重写 r2 或 receipt、不清理残骸、不“重"
        "新封存”、不写报告/缓存/records/生命周期目录）：实际变化条目 "
        f"{tree_changed}"
    )
    assert r2_receipt_file.read_bytes() == r2_completed_receipt_bytes, (
        "fail-closed 拒绝不得重写已完成 r2 的 receipt（恢复依据失配不"
        "得触发对凭证的重写/“重新封印”/digest 重算—— 拒绝前必须停止）"
    )
    assert _release_content_files(r2_release_dir) == r2_completed_content, (
        "fail-closed 拒绝不得重写已完成的 data/releases/data-v4.1-r2（失"
        "配的已完成对象既不得被跳过放行，也不得被重建）"
    )
    assert _release_content_files(r1_release_dir) == r1_partial_content, (
        "fail-closed 拒绝不得继续写入 r1（半写残骸必须逐字节原样保留，"
        "不得被清理、补写或用改后源内容重建）"
    )
    # 同一个 r1 receipt 文件（中断后保留的 in-progress receipt）必须逐
    # 字节原样：不得被补写/覆盖为 committed（凭证只在对象完整写入并验证
    # 后产生；拒绝路径零写入），也不得被删除/重写（恢复依据不得被破坏）。
    assert r1_receipt_file.read_bytes() == r1_receipt_bytes_after_interrupt, (
        "fail-closed 拒绝不得改写同一个 r1 in-progress receipt（更不得覆"
        "盖/补写为 committed —— 凭证只在对象完整写入并验证后产生；恢复"
        "依据必须为下一次重跑保留，拒绝路径零写入）"
    )
    _assert_same_file_in_progress_receipt(
        r1_receipt_file,
        CONFIRMED_DATA_TARGET_R1,
        r1_mapping,
        r1_manifest_sha256_at_interruption,
        context="fail-closed 拒绝后",
    )
    assert _snapshot_target_side_mtime_ns(tmp_path) == (
        tampered_target_side_mtime
    ), (
        "fail-closed 拒绝不得触碰目标侧任何条目元数据（data/ 与 "
        "migration_receipts/ 子树全部条目 mtime_ns 必须不变；字节恰好相同"
        "的重写也会更新 mtime）"
    )
    assert _snapshot_modes(tmp_path) == tampered_modes, (
        "fail-closed 拒绝不得改动任何条目权限位（不重新封存、不改写位、"
        "不得先解封再重建）"
    )
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "fail-closed 拒绝不得产生任何新身份/新条目（不覆盖、不自动改号）："
        f"data/releases/ 必须恰含 {CONFIRMED_DATA_TARGET_R1} 与 "
        f"{CONFIRMED_DATA_TARGET_R2}"
    )
    assert not (releases_root / "data-v4.1-r3").exists(), (
        "fail-closed 拒绝不得自动改号到 data-v4.1-r3"
    )
    receipts_root = tmp_path / "migration_receipts"
    assert [entry.name for entry in sorted(receipts_root.iterdir())] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        "fail-closed 拒绝后 migration_receipts/ 必须恰含 r1 in-progress 与"
        " r2 committed 两份 receipt（不新增凭证、不删除既有凭证；中断后"
        "保留的同一个 r1 receipt 不得被补写/覆盖为 committed，不得另立"
        " credential 目录/文件）"
    )
    for forbidden in ("records", "working", "release_staging"):
        assert not (tmp_path / forbidden).exists(), (
            f"fail-closed 拒绝不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in after_tree), (
        "fail-closed 拒绝不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "fail-closed 拒绝不得就地改写传入映射项（M0 事实分级保持不变）"
    )

    # ---- 行为 7（末尾对照前提）：恢复被修改的 legacy 源原字节 —— 整树必须
    #      精确回到中断后保留状态（零写入 + 恢复逐字节精确的双重证据）。----
    if source_change_scenario == "completed_object_source_changed":
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).write_bytes(
            changed_source["r2_manifest"]
        )
        (tmp_path / _DATA_POINTER_REL).write_bytes(changed_source["pointer"])
    else:
        _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, changed_source["declared_rel"]
        ).write_bytes(changed_source["original_payload"])
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).write_bytes(
            changed_source["r1_manifest"]
        )
    assert _snapshot_tree(tmp_path) == interrupted_tree, (
        "末尾对照前提失败：恢复被修改的 legacy 源原字节后，整树必须精确回"
        "到中断后保留状态（fail-closed 拒绝零写入 + 恢复逐字节精确，任"
        "何残留改动都在此暴露）"
    )

    # ---- 行为 7（末尾对照）：源恢复后同 root、同映射重跑必须重新成功（T19
    #      既有中断恢复行为：跳过 r2、完成 r1）—— 拒绝不得过宽。----
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "拒绝过宽或恢复路径被破坏：恢复 legacy 源原字节后的同 root、"
            "同映射重跑必须重新成功（T19 既有中断恢复行为：跳过凭证匹配的"
            "已完成 r2、继续并完成 r1；若此处失败，说明前述 fail-closed 拒"
            "绝条件过宽到拒绝了源未变化的正常恢复，或恢复路径被破坏；原始"
            f"异常经 cause 链保留）：{exc!r}"
        ) from exc

    # ---- 行为 7 终态：r1 完成（语义取已恢复的 manifest 声明值）、r2 零重
    #      写、无新身份、legacy 侧回到初始。----
    final_tree = _snapshot_tree(tmp_path)
    r1_final_content = _release_content_files(r1_release_dir)
    assert set(r1_final_content) == {"release.yaml"} | set(
        r1_declared_payload_paths
    ), (
        "末尾对照重跑必须完成 r1 正式 release：内容恰为 release.yaml + "
        "r1 manifest 声明的 payload 文件集合：实际 "
        f"{sorted(r1_final_content)}"
    )
    for declared_rel in r1_declared_payload_paths:
        assert r1_final_content[declared_rel] == _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, declared_rel
        ).read_bytes(), (
            f"末尾对照完成的 r1 payload {declared_rel!r} 必须与（已恢复的）"
            "legacy 源逐字节一致"
        )
    r1_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        "末尾对照完成的 r1 必须经既有语义读回为 data-v4.1-r1"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        "末尾对照完成的 r1 status 必须为 superseded（映射 target_status，"
        f"D1 用户确认）：实际 {r1_meta.status!r}"
    )
    assert r1_meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        "末尾对照完成的 r1 replacement 必须为映射声明的 "
        f"{CONFIRMED_DATA_TARGET_R2!r}：实际 {r1_meta.replacement!r}"
    )
    replacement_meta = load_release_metadata(
        tmp_path / "data", r1_meta.replacement
    )
    assert replacement_meta.status is DataStatus.ACTIVE, (
        "末尾对照完成的 r1 replacement 必须解析为既有正式 active r2"
    )
    assert r1_meta.sample_count == (
        r1_manifest_declared["counts"]["published_candidates"]
    ), (
        "末尾对照完成的 r1 sample_count 必须取（已恢复的）r1 manifest "
        "counts.published_candidates 声明值"
    )
    expected_r1_splits = {
        f"fold_{fold}": {
            "train": r1_manifest_declared["counts"]["splits"][
                f"fold_{fold}_train"
            ],
            "validation": r1_manifest_declared["counts"]["splits"][
                f"fold_{fold}_val"
            ],
        }
        for fold in range(3)
    }
    assert dict(r1_meta.splits) == expected_r1_splits, (
        "末尾对照完成的 r1 splits 必须取（已恢复的）r1 manifest "
        "counts.splits 声明值"
    )
    try:
        assert_payload_sealed(r1_release_dir)
    except Exception as exc:
        raise AssertionError(
            "末尾对照完成的 r1 封存事实必须保持（既有只读门 "
            f"assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    with pytest.raises(ReferenceNotAllowed):
        validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)

    assert r1_receipt_file.is_file(), (
        "末尾对照重跑完成后必须写入 r1 committed receipt"
    )
    r1_final_receipt = yaml.safe_load(r1_receipt_file.read_text(encoding="utf-8"))
    assert isinstance(r1_final_receipt, dict), (
        "末尾对照写入的 r1 receipt 必须是 YAML 顶层映射"
    )
    assert set(r1_final_receipt) == set(_RECEIPT_FIELDS), (
        "末尾对照写入的 r1 receipt 键集必须恰为八字段契约：实际 "
        f"{sorted(r1_final_receipt)}"
    )
    assert r1_final_receipt["status"] == "committed", (
        "末尾对照写入的 r1 receipt.status 必须为 committed"
    )
    assert r1_final_receipt["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1, (
        "r1 receipt.source_legacy_id 必须为 "
        f"{CONFIRMED_DATA_SOURCE_R1!r}"
    )
    assert r1_final_receipt["target_identity"] == CONFIRMED_DATA_TARGET_R1, (
        "r1 receipt.target_identity 必须为 "
        f"{CONFIRMED_DATA_TARGET_R1!r}"
    )
    assert r1_final_receipt["target_path"] == r1_mapping["target_path"], (
        "r1 receipt.target_path 必须与映射项声明的 target_path 一致"
    )
    assert r1_final_receipt["source_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).read_bytes()
    ).hexdigest(), (
        "r1 receipt.source_manifest_sha256 必须与（已恢复的）r1 源 manifest "
        "文件字节哈希一致（拒绝不得破坏恢复后凭证的源绑定）"
    )
    assert r1_final_receipt["target_release_digest"] == (
        _recompute_target_release_digest(r1_final_content)
    ), (
        "r1 receipt.target_release_digest 必须能由完成的 r1 目标内容按钉定"
        "口径复算验证"
    )

    assert r2_receipt_file.read_bytes() == r2_completed_receipt_bytes, (
        "末尾对照重跑不得重写已完成 r2 的 receipt（跳过即不重写）"
    )
    assert _release_content_files(r2_release_dir) == r2_completed_content, (
        "末尾对照重跑不得重写已完成 r2 的正式 release"
    )
    assert _snapshot_r2_completed_side_mtime_ns(tmp_path) == (
        r2_completed_side_mtime
    ), (
        "末尾对照重跑不得触碰已完成 r2 侧任何条目元数据（r2 release 子树"
        "与 r2 receipt 全部条目 mtime_ns 不变）"
    )

    # 整树差异只允许 r1 完成侧（半写残骸被完整内容取代）+ 同一个 r1
    # receipt 文件的 in_progress -> committed 转写（用户确认生命周期：
    # 中断后保留同一个 in-progress receipt，恢复成功后同一文件原子转为
    # committed；不得新增额外 credential 文件或目录）。
    r1_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R1}"
    r1_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    new_keys = set(final_tree) - set(interrupted_tree)
    assert all(
        key == r1_receipt_rel
        or key == r1_release_root_rel
        or key.startswith(f"{r1_release_root_rel}/")
        for key in new_keys
    ), (
        "末尾对照重跑只允许新增 r1 完成侧条目（release 子树内文件/目录）"
        f"与 r1 receipt（不写报告/缓存/records/生命周期目录，亦不得新增"
        "额外 credential 文件或目录 —— 同一个 r1 receipt 文件由 in_progress"
        f"原子转为 committed）：实际新增 {sorted(new_keys)}"
    )
    changed_keys = sorted(
        key
        for key in interrupted_tree
        if final_tree.get(key) != interrupted_tree[key]
    )
    assert all(
        key == r1_receipt_rel
        or key == r1_release_root_rel
        or key.startswith(f"{r1_release_root_rel}/")
        for key in changed_keys
    ), (
        "末尾对照重跑只允许改变 r1 release 子树内条目（半写残骸被完整内"
        "容取代）与同一个 r1 receipt 文件的 in_progress -> committed 转写"
        "（用户确认生命周期，允许且必要）；其余任何条目（r2 侧、legacy"
        "源、旧 pointers、migration_receipts/ 内其他凭证）必须逐字"
        f"节不变：实际变化 {changed_keys}"
    )
    assert not set(interrupted_tree) - set(final_tree), (
        "末尾对照重跑不得删除任何既有条目"
    )
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "末尾对照重跑不得产生新身份：data/releases/ 必须恰含 r1 与 r2"
    )
    assert [entry.name for entry in sorted(receipts_root.iterdir())] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        "末尾对照重跑后 migration_receipts/ 必须恰含 r1 与 r2 两份 receipt"
    )
    _assert_legacy_side_unchanged(interrupted_before, final_tree)
    data_pointer_final = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_final["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "全程不得切换旧数据活动指针（仍声明 legacy 身份；源恢复后指针回"
        "到 fixture 原字节）"
    )
    prompt_pointer_final = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_final["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "全程不得切换旧 Prompt 活动指针（仍声明 legacy revision_id）"
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "全程不得就地改写传入映射项（M0 事实分级保持不变）"
    )


# ---------------------------------------------------------------------------
# T19-P4：D2 边界补齐 —— 部分写入对象必须在开始写入前持久化可核实的
# in-progress recovery credential（绑定映射与中断前源快照：operation_id /
# source_legacy_id / target_identity / target_path / source_manifest_sha256 /
# 映射 target_status / replacement）；中断后任何 legacy 源内容变化 —— 含
# 不影响已落盘 payload 前缀的 manifest 语义变化 —— 的重跑都必须
# fail-closed 停止（先写测试，不改 production）
# ---------------------------------------------------------------------------

# 场景 prefix_unaffected_manifest_change 的注入变体值：r1 legacy manifest
# counts.published_candidates 11 -> 12（与 T17/T18/T19 注入值 11、r2 注入值
# 7、payload 可复算值 3 故意互不相同）。counts 只喂 release.yaml 语义内
# 容：半写残骸内没有 release.yaml、payload 字节与 files[] 声明不动，故
# 该变化不影响已落盘前缀 —— 按当前“以当前源复算期望字节”的恢复口径半
# 写仍可核实为本转换部分写入，唯一能发现源已变化的只有中断前源快照
# credential。
_R1_CHANGED_PUBLISHED_CANDIDATES = 12


def _iter_yaml_mappings(value: Any) -> list[Mapping[str, Any]]:
    """递归枚举已解析 YAML/JSON 值中的全部 mapping 节点（含嵌套）。"""
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        found.append(value)
        for item in value.values():
            found.extend(_iter_yaml_mappings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_iter_yaml_mappings(item))
    return found


def _find_recovery_credential_candidates(
    root: Path, source_id: str, identity: str
) -> list[tuple[str, Mapping[str, Any]]]:
    r"""按内容契约发现绑定指定对象的凭证候选（越界发现口径）。

    用户已裁决 in-progress receipt 使用同一个
    ``migration_receipts/<target_identity>.receipt.yaml``（不再位置不绑
    定）；本函数保留为越界发现口径：扫描目标树全部非 symlink 文件，按
    YAML 解析（JSON 是其子集，两种写出格式均可发现），递归取全部 mapping
    节点，凡含等于指定 source_legacy_id 或 target_identity 的键即为候
    选 —— 调用方据此断言“目标侧非 committed 凭证只允许同一个 receipt 文
    件”“不得存在伪称 committed 的绑定条目”。committed receipt（八字
    段）与 in-progress receipt 同口径枚举，由调用方按 status 与字段绑定
    分别断言 —— 本函数只做发现，不做契约判定。
    """
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            parsed = yaml.safe_load(path.read_bytes())
        except Exception:
            continue
        for mapping in _iter_yaml_mappings(parsed):
            if (
                mapping.get("source_legacy_id") == source_id
                or mapping.get("target_identity") == identity
            ):
                candidates.append((path.relative_to(root).as_posix(), mapping))
    return candidates


def _in_progress_credential_binding_errors(
    credential: Mapping[str, Any],
    mapping_item: Mapping[str, Any],
    expected_source_manifest_sha256: str,
) -> list[str]:
    r"""核实 in-progress recovery credential 的字段绑定，返回错误列表。

    credential 至少必须绑定（D2 边界确认：恢复凭证必须绑定映射和源内
    容；源内容不符即停止）：
    - ``operation_id``：非空字符串（绑定“同一次转换”的操作身份）；
    - ``source_legacy_id`` / ``target_identity`` / ``target_path``：与映
      射项精确相等；
    - ``source_manifest_sha256``：与中断前 legacy 源 manifest 文件字节
      SHA-256 相等（中断前源快照 —— 恢复依据；重跑时与当前源比对，源
      内容不符即停止）；
    - ``target_status`` / ``replacement``：与映射项声明精确相等（r1：
      superseded / data-v4.1-r2；credential 不得发明与映射不符的生命周
      期）；
    - ``status``（若存在）不得为 committed（部分写入对象的凭证不得伪称
      已完成）。
    """
    errors: list[str] = []
    operation_id = credential.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        errors.append(f"operation_id 缺失或非字符串（实际 {operation_id!r}）")
    expected_bindings: tuple[tuple[str, Any], ...] = (
        ("source_legacy_id", mapping_item.get("source_legacy_id")),
        ("target_identity", mapping_item.get("candidate_target_identity")),
        ("target_path", mapping_item.get("target_path")),
        ("source_manifest_sha256", expected_source_manifest_sha256),
        ("target_status", mapping_item.get("target_status")),
        ("replacement", mapping_item.get("replacement")),
    )
    for field, expected_value in expected_bindings:
        if credential.get(field) != expected_value:
            errors.append(
                f"{field}={credential.get(field)!r} 与映射/中断前源快照期望 "
                f"{expected_value!r} 不符"
            )
    if credential.get("status") == "committed":
        errors.append(
            "status='committed'：中断后的 in-progress credential 不得标记 "
            "committed"
        )
    return errors


def _change_partial_r1_legacy_source_manifest_counts(
    root: Path,
) -> dict[str, bytes]:
    r"""修改未完成对象 r1 的 legacy 源 manifest counts（不影响已落盘前缀）。

    场景 prefix_unaffected_manifest_change 的单一变量扰动：仅改
    counts.published_candidates（11 -> _R1_CHANGED_PUBLISHED_CANDIDATES）。
    payload 字节与 manifest files[] 声明哈希不动（T14 manifest 自洽门保
    持绿）；r1 无钉扎（M0 pinned_by: ~，旧数据活动指针钉扎 r2），指针门
    不受影响（T13 保持绿）—— 两个既有只读门均不阻塞，重跑若被拒绝只能
    由中断前源快照 credential 与当前源内容的比对归因。返回改前 manifest
    原字节供末尾对照恢复。
    """
    manifest_bytes_original = _manifest_file_of(
        root, CONFIRMED_DATA_SOURCE_R1
    ).read_bytes()
    manifest = json.loads(manifest_bytes_original.decode("utf-8"))
    assert (
        manifest["counts"]["published_candidates"]
        != _R1_CHANGED_PUBLISHED_CANDIDATES
    ), "fixture 前置事实失败：注入变体值必须与 T17/T18/T19 注入值不同"
    manifest["counts"]["published_candidates"] = _R1_CHANGED_PUBLISHED_CANDIDATES
    _rewrite_legacy_release_manifest(root, CONFIRMED_DATA_SOURCE_R1, manifest)
    return {"r1_manifest": manifest_bytes_original}


def test_migrate_data_interrupted_partial_object_persists_verifiable_in_progress_source_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r"""部分写入对象必须在开始写入前持久化可核实的中断前源快照凭证。

    T19-P4 behavior（D2 边界补齐，先写测试，不改 production）—— D2 已确
    认：恢复凭证必须绑定映射和源内容；源内容不符即停止。T19 的中断恢复
    只核实“半写目标内容是否为按当前源复算期望字节的前缀”，未持久化部分
    写入对象的中断前源快照：若中断后 legacy 源发生不影响已落盘前缀的变
    化（如 manifest counts 变化，见配套 fail-closed 用例），“按当前源复
    算”的恢复依据无法发现源已变化，会以改后源内容继续恢复。本切片钉凭
    证存在性切面：对双对象批 [r2, r1]（D2 推荐顺序 r2 先于 r1）开始转
    换，在第二个对象 r1 的写入过程中注入失败（T19 同款注入）时：
    1. 第一次调用必须显式失败（struck_writes 非空且全部落在 r1 目标子
       树内，T19 既有形态，fixture 前置事实）；
    2. r2 作为已完成对象保留（完整正式 release + committed receipt，
       T19 既有行为，fixture 前置事实）；r1 半写残骸 + 无 r1 committed
       receipt（T19 既有形态，fixture 前置事实）；
    3. 中断后必须已存在绑定 r1 的可核实 in-progress receipt —— 用户已
       裁决生命周期：每个对象使用同一个
       ``migration_receipts/data-v4.1-r1.receipt.yaml``，写入前该文件为
       ``status: in_progress``、``target_release_digest: null``，中断后
       同一文件保留；该文件必须可解析为 YAML mapping，至少绑定
       operation_id（非空字符串）、source_legacy_id / target_identity /
       target_path（与 r1 映射项精确相等）、source_manifest_sha256（中
       断前 r1 legacy manifest 文件字节 SHA-256 —— 第一次调用读到的源
       快照）、映射 target_status（superseded）与 replacement
       （data-v4.1-r2）；
    4. 同一 receipt 文件不得标记 committed；中断后也不得存在任何把未完
       成 r1 伪称为 committed 的绑定条目；不得接受独立 credential 目
       录 —— 目标侧绑定 r1 的 in-progress 凭证只允许存在于同一个
       receipt 文件（migration_receipts.in.progress/ 等额外目录/文件均
       为生命周期偏离），migration_receipts/ 必须恰含 r1 in-progress
       与 r2 committed 两份 receipt，目标侧不得新增两个 release 子树与
       两份 receipt 之外的任何条目；
    5. 同一个 receipt 文件的写入时点必须先于 r1 目标写入：注入契约使第
       一次调用死在 r1 目标子树内的第一个写入上（写入非空严格前缀后抛
       OSError），完整可解析的 in-progress receipt 只能在此之前落盘 ——
       receipt 落在 r1 目标子树内即被注入命中、只落半截不可解析，等于
       不存在；
    6. legacy 源与旧 pointers 逐字节不变（credential 不得写进 legacy
       侧）；
    7. 恢复注入后，源不变、同 root、同映射重跑必须仍成功（T19 既有恢
       复行为不回归 —— in-progress receipt 是恢复依据，不是恢复障碍），
       r1 完成后同一个 receipt 文件原子转为 committed receipt，保持既有
       八字段契约（不夹带 in-progress 凭证字段或映射项 dump），完成后不
       额外保留 in-progress 状态；migration_receipts/ 恰含两份 receipt，
       全程不得新增额外 credential 文件或目录；
    8. receipt 的文件名/位置/完成后转写已由用户裁决绑定（同一个
       receipt 文件、in_progress 原子转 committed，不另立 credential 目
       录），不再是不绑定项；本切片不做前缀区域受影响的源变化
       fail-closed（T19-P3 已钉半写前缀区域内的变化）、不做已完成对象
       源变化（T19-P3 已钉）、不做 in-progress receipt 自身缺失/被篡改
       的拒绝分支、批内首个对象即中断、CLI、DVC、训练机真实路径。

    fixture：复用 T19 场景 helper ``_write_interrupt_scenario_layout`` 与
    ``_install_r1_target_mid_write_interruption``（T17/T18/T19 同款布局：
    三份 legacy release + 旧数据/Prompt 活动指针 + r2/r1 counts 场景注
    入（r2 published_candidates 7、r1 为 11）+ r2 指针 manifest 哈希随
    注入复算；两条映射来自 ``_confirmed_data_mapping_items``，D2 推荐顺
    序 r2 先于 r1）。credential 发现口径：
    ``_find_recovery_credential_candidates`` 扫描目标树全部非 symlink 文
    件、按 YAML 解析、递归取 mapping 节点，凡含等于 r1 source_legacy_id
    / target_identity 的键即为候选 —— committed receipt（八字段）与
    in-progress credential 同口径枚举，由 status 与字段绑定分别断言。

    RED Gate 设计说明（T19-P4，本轮契约统一后更新）：migrate_data 入
    口、DataMigrationBlocked 拒绝通道、T17 双对象批终态、T19 中断恢复
    与中断前源快照凭证机制均已存在（第一次中断调用成功构造批内部分完
    成状态为 fixture 前置事实，失败即 T19 回归而非本切片 RED），RED 不
    经入口缺失分支给出 —— 当前 production 偏离用户裁决的生命周期：把
    credential 写在 migration_receipts.in.progress/ 独立目录（status 为
    in_progress、target_release_digest null、字段绑定齐全），同一个
    migration_receipts/data-v4.1-r1.receipt.yaml 中断后不存在 -> 中断后
    fixture 前置事实的显式行为 AssertionError 钉出“同一个 receipt 文
    件未按用户确认生命周期以 in_progress 状态保留（credential 被写到
    了独立目录）”；若当前实现已返工到同一文件生命周期（in-progress
    receipt 已在同一文件持久化且绑定完整），本用例为 Unexpected PASS
    （转为凭证存在性回归钉），不得为此制造无意义 production 修改。

    捕获的合理但错误实现：
    - 当前 production（RED 起点，用户裁决生命周期偏离）：credential 写
      在 migration_receipts.in.progress/ 独立目录、同一个 receipt 文件
      缺失 -> 中断后同一文件契约断言失败（不得接受独立 credential 目
      录）；
    - “完成后才补写”：credential 在对象完成后才写 -> 中断后不存在 ->
      同一文件契约断言失败（半写对象的源快照必须在写入前持久化才有恢
      复依据）；
    - “credential 不绑源内容”：只绑映射字段不绑 source_manifest_sha256，
      或绑 canonical JSON / 目录哈希 / 声明值自比等错误口径 -> 绑定核
      实断言失败（中断后源变化无从发现）；
    - “credential 绑错源快照”：source_manifest_sha256 与中断前 manifest
      文件字节不等 -> 绑定核实断言失败；
    - “credential 不绑映射生命周期”：缺 target_status / replacement 或
      与映射声明不等 -> 绑定核实断言失败（无法核实“同一次转换”）；
    - “credential 伪称完成”：status 标 committed -> 非 committed 断言
      失败；
    - “credential 写进 r1 目标子树”：被注入命中、只落半截不可解析 ->
      发现断言失败（且破坏目标内容契约）；
    - “credential 写进 legacy 侧”：legacy 逐字节不变断言失败；
    - “credential 阻塞恢复”：恢复重跑因 credential 存在被拒 -> 行为 7
      断言失败（恢复路径不得因恢复依据的存在而失败）；
    - “receipt 夹带非契约字段”：完成后 r1 receipt 键集 != 八字段 -> 契
      约断言失败（credential 字段不得泄漏进 committed receipt）。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（本切片仅新增用
      例与配套 fixture helper 及模块 docstring 清单条目，不改
      production）。
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_interrupted_partial_object_persists_verifiable_in_progress_source_credential``
    - RED failure signature（本轮契约统一后）：恰一个失败用例（本
      selector），失败信息为 AssertionError “fixture 前置事实失败（中
      断后）：同一个 receipt 文件
      migration_receipts/data-v4.1-r1.receipt.yaml 必须存在（用户确认
      生命周期：写入前该文件为 status: in_progress、
      target_release_digest: null，中断后保留同一个 in-progress receipt，
      恢复成功后同一文件原子转为 committed；不得把 credential 写在
      migration_receipts.in.progress/ 等独立目录或额外凭证文件）”；
      fixture 前置事实（布局自洽、空目标根 precheck ready、第一次调用
      被中断命中且显式失败、r2 完成保留且 committed receipt 八字段、
      r1 半写残骸、legacy 不变）全部不失败。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：T17/T18/T19 同款布局与 counts 场景注入（同一事实基
    #      线：r2 published_candidates 7、r1 为 11）。----
    _write_interrupt_scenario_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items

    # ---- fixture 前置事实（注入自洽 + D1/D2 镜像 + 目标根空闲）。----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    pointer = json.loads((tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded（D1）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2（D1）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )
    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T19 既有行为不可用，本切片 fixture 前置事实失"
        "败）"
    )
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（T11 既有行为不可用，本切片 fixture "
        "前置事实失败）"
    )
    dual_precheck_report = precheck(tmp_path, mapping_items)
    assert dual_precheck_report.status == "ready", (
        "fixture 前置事实失败：空目标根上双对象批（r2+r1，D2 推荐顺序）的"
        f"只读预检必须整批 ready（实际 {dual_precheck_report.status!r}，"
        f"reasons={dual_precheck_report.reasons!r}）—— 第一次调用的失败只"
        "能由注入中断归因"
    )

    interrupted_before = _snapshot_tree(tmp_path)
    r1_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r1_receipt_file = (
        tmp_path / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r2_receipt_file = (
        tmp_path / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    # 中断前源快照：第一次调用读到的 r1 manifest 文件字节（本用例全程不
    # 改 legacy 源，该字节即 credential 必须绑定的中断时刻源快照）。
    r1_manifest_bytes_at_interruption = _manifest_file_of(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    ).read_bytes()
    r1_manifest_sha256_at_interruption = hashlib.sha256(
        r1_manifest_bytes_at_interruption
    ).hexdigest()
    r1_manifest_declared = json.loads(
        r1_manifest_bytes_at_interruption.decode("utf-8")
    )
    r1_declared_payload_paths = sorted(
        entry["path"] for entry in r1_manifest_declared["files"]
    )

    # ---- 行为前提构造 + 行为 1：第一次调用在 r1 写入中途被中断（T19 同
    #      款注入：armed 期间持续命中 r1 目标子树内的写入）。----
    struck_writes: list[Path] = []
    interruption = _install_r1_target_mid_write_interruption(
        monkeypatch, r1_release_dir, struck_writes
    )
    first_call_error: BaseException | None = None
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        first_call_error = exc
    assert first_call_error is not None, (
        "双对象批第一次调用必须在 r1 写入中途注入失败后显式失败（T19 既"
        "有批内部分完成状态构造，中断不得被吞掉后当作成功返回）"
    )
    assert struck_writes, (
        "中断注入失效：第一次调用的 r1 目标写入未被命中（T19 注入点契约："
        "struck_writes 为空即注入点需随实际写路径维护；credential 的“写"
        "入先于 r1 目标写入”时点判定依赖第一次调用死于 r1 子树内第一个写"
        "入上）"
    )
    assert all(
        path.is_relative_to(r1_release_dir) for path in struck_writes
    ), (
        "中断注入命中范围异常：被中断的写入必须全部落在 r1 目标子树 "
        f"data/releases/{CONFIRMED_DATA_TARGET_R1}/ 内：实际 "
        f"{sorted(struck_writes)}"
    )

    # ---- fixture 前置事实：批内部分完成状态（T19 既有行为）。----
    r2_meta_after_interrupt = load_release_metadata(
        tmp_path / "data", CONFIRMED_DATA_TARGET_R2
    )
    assert r2_meta_after_interrupt.status is DataStatus.ACTIVE, (
        "fixture 前置事实失败：中断后 r2 必须经既有语义读回为 active 正式"
        "对象（批内部分完成状态的已完成侧前提）"
    )
    try:
        assert_payload_sealed(r2_release_dir)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：中断后保留的 r2 封存事实必须保持（既有"
            f"只读门 assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：中断后 r2 committed receipt 必须已写入（已"
        "完成对象的凭证）"
    )
    r2_receipt_bytes_after_interrupt = r2_receipt_file.read_bytes()
    r2_completed_receipt = yaml.safe_load(
        r2_receipt_bytes_after_interrupt.decode("utf-8")
    )
    assert isinstance(r2_completed_receipt, dict), (
        "fixture 前置事实失败：r2 receipt 必须是 YAML 顶层映射"
    )
    assert set(r2_completed_receipt) == set(_RECEIPT_FIELDS), (
        "fixture 前置事实失败：r2 receipt 键集必须恰为八字段契约：实际 "
        f"{sorted(r2_completed_receipt)}"
    )
    assert r2_completed_receipt["status"] == "committed", (
        "fixture 前置事实失败：r2 receipt 必须为 committed"
    )
    r2_completed_content = _release_content_files(r2_release_dir)
    assert set(r2_completed_content) == {"release.yaml"} | set(
        sorted(
            entry["path"]
            for entry in json.loads(
                _manifest_file_of(
                    tmp_path, CONFIRMED_DATA_SOURCE_R2
                ).read_text(encoding="utf-8")
            )["files"]
        )
    ), (
        "fixture 前置事实失败：中断后保留的 r2 目标 release 内容必须恰为 "
        "release.yaml + r2 manifest 声明的 payload 文件集合"
    )
    r1_receipt_bytes_after_interrupt = _assert_same_file_in_progress_receipt(
        r1_receipt_file,
        CONFIRMED_DATA_TARGET_R1,
        r1_mapping,
        r1_manifest_sha256_at_interruption,
        context="fixture 前置事实失败（中断后）",
    )
    r1_partial_content = _release_content_files(r1_release_dir)
    assert r1_partial_content, (
        "fixture 前置事实失败：中断后 r1 目标内必须存在半写残骸（部分写"
        "入对象的 credential 切片依赖“写入已真实开始、未完成”这一事实）"
    )
    assert "release.yaml" not in r1_partial_content, (
        "fixture 前置事实失败：中断注入应命中的是 r1 目标 payload 写入"
        "（当前 production 先复制 manifest files[] 声明的 payload、后写 "
        "release.yaml；写入机制变更时本前置事实与注入点需随实际写路径维"
        "护）"
    )
    for relative, partial_bytes in r1_partial_content.items():
        source_payload = _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, relative
        ).read_bytes()
        assert relative in set(r1_declared_payload_paths), (
            "fixture 前置事实失败：r1 半写残骸必须是 manifest 声明的 "
            f"payload（实际 {relative!r}）"
        )
        assert (
            0 < len(partial_bytes) < len(source_payload)
            and source_payload.startswith(partial_bytes)
        ), (
            "fixture 前置事实失败：r1 半写残骸必须是 legacy 源对应文件字"
            f"节的非空严格前缀（实际 {relative!r}：{len(partial_bytes)} 字节）"
        )
    _assert_legacy_side_unchanged(interrupted_before, _snapshot_tree(tmp_path))
    assert mapping_items == _confirmed_data_mapping_items(), (
        "fixture 前置事实失败：中断失败路径不得就地改写传入映射项"
    )
    r2_completed_side_mtime = _snapshot_r2_completed_side_mtime_ns(tmp_path)

    # ---- 行为 3/4/5（RED）：中断后同一个 receipt 文件必须以 in_progress
    #      状态存在且绑定完整；不得接受独立 credential 目录或额外凭证文
    #      件，不得存在把未完成 r1 伪称 committed 的绑定条目。----
    candidates = _find_recovery_credential_candidates(
        tmp_path, CONFIRMED_DATA_SOURCE_R1, CONFIRMED_DATA_TARGET_R1
    )
    committed_claims = [
        relative
        for relative, mapping in candidates
        if mapping.get("status") == "committed"
    ]
    assert not committed_claims, (
        "中断后不得存在把未完成 r1 伪称为 committed 的凭证条目（r1 尚未完"
        f"整写入并验证，半写对象不得有 committed 状态凭证）：{committed_claims}"
    )
    # 同一个 receipt 文件的存在性/状态/字段绑定契约已由上方 fixture 前置
    # 事实钉定（_assert_same_file_in_progress_receipt：必须存在、status
    # 为 in_progress、target_release_digest 为 null、绑定完整）。此处钉
    # “不得接受独立 credential 目录或额外凭证文件”：目标侧绑定 r1 的非
    # committed 凭证只能有同一个 receipt 文件。
    r1_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r2_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    target_side_in_progress_claims = sorted(
        relative
        for relative, mapping in candidates
        if mapping.get("status") != "committed"
        and not relative.startswith(("workspace/", "finetune/", "pipeline/"))
    )
    assert target_side_in_progress_claims == [r1_receipt_rel], (
        "中断后绑定 r1 的 in-progress 凭证只允许存在于同一个 receipt 文件 "
        f"{r1_receipt_rel}（用户确认生命周期：每个对象使用同一个 "
        "migration_receipts/<target_identity>.receipt.yaml，写入前 "
        "status: in_progress、target_release_digest: null，中断后保留同一"
        "个 in-progress receipt；不得把 credential 写在 "
        "migration_receipts.in.progress/ 等独立目录或任何额外凭证文件）："
        f"实际 {target_side_in_progress_claims}"
    )
    # 全树快照口径：目标侧新增条目只允许两个 release 子树、
    # migration_receipts/ 目录与两份 receipt —— 额外 credential 目录/文件
    # （含 migration_receipts.in.progress/）在此一并检出。
    interrupted_tree_after = _snapshot_tree(tmp_path)
    r1_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R1}"
    r2_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R2}"
    interrupted_new_keys = set(interrupted_tree_after) - set(interrupted_before)
    assert all(
        key == "data"
        or key == "data/releases"
        or key == r1_release_root_rel
        or key == r2_release_root_rel
        or key.startswith(f"{r1_release_root_rel}/")
        or key.startswith(f"{r2_release_root_rel}/")
        or key == "migration_receipts"
        or key == r1_receipt_rel
        or key == r2_receipt_rel
        for key in interrupted_new_keys
    ), (
        "中断后目标侧只允许新增两个 release 目录子树（含目录条目）、"
        "migration_receipts/ 与两份 receipt —— 不得新增额外 credential 文"
        "件或目录（如 migration_receipts.in.progress/）：实际新增 "
        f"{sorted(interrupted_new_keys)}"
    )
    receipts_root = tmp_path / "migration_receipts"
    assert [entry.name for entry in sorted(receipts_root.iterdir())] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        "中断后 migration_receipts/ 必须恰含 r1 in-progress 与 r2 "
        "committed 两份 receipt（同一个 r1 receipt 文件是 in-progress "
        "credential —— 用户确认生命周期；不得另立 credential 目录/文件）"
    )

    # ---- 行为 7：源不变、同 root、同映射重跑必须仍成功（T19 恢复不回
    #      归 —— credential 是恢复依据，不是恢复障碍）。----
    interruption.armed = False
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "in-progress credential 的存在不得破坏 T19 既有恢复路径：源不"
            "变、同 root、同映射的重跑必须仍成功（跳过已完成 r2、继续并完"
            "成 r1；credential 的存在不得使恢复被拒，原始异常经 cause 链保"
            f"留）：{exc!r}"
        ) from exc

    # ---- 行为 7 终态：r1 完成（内容恰为 release.yaml + 声明 payload，
    #      payload 与源逐字节一致）。----
    final_r1_content = _release_content_files(r1_release_dir)
    assert set(final_r1_content) == {"release.yaml"} | set(
        r1_declared_payload_paths
    ), (
        "恢复重跑完成的 r1 目标 release 内容必须恰为 release.yaml + r1 "
        "manifest 声明的 payload 文件集合（credential 不得作为目标内容泄"
        f"漏进 release 子树）：实际 {sorted(final_r1_content)}"
    )
    for declared_rel in r1_declared_payload_paths:
        assert final_r1_content[declared_rel] == _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, declared_rel
        ).read_bytes(), (
            f"恢复完成的 r1 payload {declared_rel!r} 必须与 legacy 源逐字"
            "节一致"
        )

    # ---- 行为 7 终态：r1 committed receipt 保持既有八字段契约 + 两处
    #      哈希独立复算核实。----
    assert r1_receipt_file.is_file(), (
        "恢复重跑完成后必须写入 r1 committed receipt"
    )
    final_r1_receipt = yaml.safe_load(r1_receipt_file.read_text(encoding="utf-8"))
    assert isinstance(final_r1_receipt, dict), (
        "恢复重跑写入的 r1 receipt 必须是 YAML 顶层映射"
    )
    assert set(final_r1_receipt) == set(_RECEIPT_FIELDS), (
        "credential 机制不得破坏 committed receipt 既有八字段契约（完成后"
        "的 receipt 键集必须恰为八字段，不得夹带 in-progress 凭证字段或映"
        f"射项 dump）：实际 {sorted(final_r1_receipt)}"
    )
    assert final_r1_receipt["status"] == "committed", (
        "恢复重跑写入的 r1 receipt.status 必须为 committed：实际 "
        f"{final_r1_receipt['status']!r}"
    )
    assert final_r1_receipt["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1, (
        "r1 receipt.source_legacy_id 必须为 "
        f"{CONFIRMED_DATA_SOURCE_R1!r}：实际 "
        f"{final_r1_receipt['source_legacy_id']!r}"
    )
    assert final_r1_receipt["target_identity"] == CONFIRMED_DATA_TARGET_R1, (
        "r1 receipt.target_identity 必须为 "
        f"{CONFIRMED_DATA_TARGET_R1!r}：实际 "
        f"{final_r1_receipt['target_identity']!r}"
    )
    assert final_r1_receipt["target_path"] == r1_mapping["target_path"], (
        "r1 receipt.target_path 必须与映射项声明的 target_path 一致：实际 "
        f"{final_r1_receipt['target_path']!r}"
    )
    assert final_r1_receipt["source_manifest_sha256"] == (
        r1_manifest_sha256_at_interruption
    ), (
        "r1 receipt.source_manifest_sha256 必须与（本用例全程未变的）r1 "
        "源 manifest 文件字节哈希一致 —— credential 绑定的中断前源快照与"
        "源不变恢复的 receipt 源绑定是同一口径"
    )
    assert final_r1_receipt["target_release_digest"] == (
        _recompute_target_release_digest(final_r1_content)
    ), (
        "r1 receipt.target_release_digest 必须能由完成的 r1 目标内容按钉"
        "定口径复算验证"
    )
    assert isinstance(final_r1_receipt["written_at"], str) and final_r1_receipt[
        "written_at"
    ], "r1 receipt.written_at 必须是非空字符串"
    assert isinstance(final_r1_receipt["operation_id"], str) and final_r1_receipt[
        "operation_id"
    ], "r1 receipt.operation_id 必须是非空字符串"

    # r1 语义读回：superseded、replacement 解析为既有 active r2、语义字
    # 段取 manifest 声明值（注入值 11）、封存事实保持；训练引用门不回归。
    r1_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        "恢复完成的 r1 必须经既有语义读回为 data-v4.1-r1"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        "恢复完成的 r1 status 必须为 superseded（映射 target_status，D1 "
        f"用户确认）：实际 {r1_meta.status!r}"
    )
    assert r1_meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        "恢复完成的 r1 replacement 必须为映射声明的 "
        f"{CONFIRMED_DATA_TARGET_R2!r}：实际 {r1_meta.replacement!r}"
    )
    replacement_meta = load_release_metadata(
        tmp_path / "data", r1_meta.replacement
    )
    assert replacement_meta.status is DataStatus.ACTIVE, (
        "恢复完成的 r1 replacement 必须解析为既有正式 active r2"
    )
    assert r1_meta.sample_count == (
        r1_manifest_declared["counts"]["published_candidates"]
    ), (
        "恢复完成的 r1 sample_count 必须取 r1 manifest 声明值（fixture 注"
        "入声明值与 payload 可复算值故意不同，钉定语义溯源）：实际 "
        f"{r1_meta.sample_count!r}"
    )
    expected_r1_splits = {
        f"fold_{fold}": {
            "train": r1_manifest_declared["counts"]["splits"][
                f"fold_{fold}_train"
            ],
            "validation": r1_manifest_declared["counts"]["splits"][
                f"fold_{fold}_val"
            ],
        }
        for fold in range(3)
    }
    assert dict(r1_meta.splits) == expected_r1_splits, (
        "恢复完成的 r1 splits 必须取 r1 manifest counts.splits 声明值"
    )
    assert set(r1_meta.source_batches) == {
        r1_manifest_declared["source_review_batch_id"],
        r1_manifest_declared["source_queue_id"],
        r1_manifest_declared["source_media_id"],
    }, "恢复完成的 r1 source_batches 必须记录 manifest 声明的原始批次标识"
    try:
        assert_payload_sealed(r1_release_dir)
    except Exception as exc:
        raise AssertionError(
            "恢复完成的 r1 封存事实必须保持（既有只读门 assert_payload_"
            f"sealed 通过）：{exc!r}"
        ) from exc
    validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    with pytest.raises(ReferenceNotAllowed):
        validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)

    # ---- 行为 7 终态：r2 侧零重写（receipt 字节 / 内容 / mtime 不动）、
    #      无新身份、legacy 侧不变、不就地改写映射项。----
    assert r2_receipt_file.read_bytes() == r2_receipt_bytes_after_interrupt, (
        "恢复重跑不得重写已完成 r2 的 receipt（跳过即不重写）"
    )
    assert _release_content_files(r2_release_dir) == r2_completed_content, (
        "恢复重跑不得重写已完成 r2 的正式 release"
    )
    assert _snapshot_r2_completed_side_mtime_ns(tmp_path) == (
        r2_completed_side_mtime
    ), (
        "恢复重跑不得触碰已完成 r2 侧任何条目元数据（r2 release 子树与 "
        "r2 receipt 全部条目 mtime_ns 不变）"
    )
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "恢复重跑不得产生 data-v4.1-r3 或任何其他新身份/新条目："
        f"data/releases/ 必须恰含 {CONFIRMED_DATA_TARGET_R1} 与 "
        f"{CONFIRMED_DATA_TARGET_R2}"
    )
    receipts_root_final = tmp_path / "migration_receipts"
    assert [entry.name for entry in sorted(receipts_root_final.iterdir())] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        "恢复重跑后 migration_receipts/ 必须恰含 r1 与 r2 两份 receipt（同"
        "一个 r1 receipt 文件由 in_progress 原子转为 committed —— 用户确"
        "认生命周期；完成后不额外保留 in-progress 状态，不得另立 credential"
        " 目录/文件）"
    )
    final_tree = _snapshot_tree(tmp_path)
    _assert_legacy_side_unchanged(interrupted_before, final_tree)
    final_new_keys = set(final_tree) - set(interrupted_before)
    assert all(
        key == "data"
        or key == "data/releases"
        or key == r1_release_root_rel
        or key == r2_release_root_rel
        or key.startswith(f"{r1_release_root_rel}/")
        or key.startswith(f"{r2_release_root_rel}/")
        or key == "migration_receipts"
        or key == r1_receipt_rel
        or key == r2_receipt_rel
        for key in final_new_keys
    ), (
        "中断 + 恢复重跑全程只允许新增两个 release 目录子树（含目录条目）、"
        "migration_receipts/ 与两份 receipt —— 不得新增额外 credential 文件"
        f"或目录（如 migration_receipts.in.progress/）：实际新增 "
        f"{sorted(final_new_keys)}"
    )
    for forbidden in (
        "records",
        "working",
        "release_staging",
        "data/working",
        "data/release_staging",
    ):
        assert not (tmp_path / forbidden).exists(), (
            f"恢复重跑不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in final_tree), (
        "恢复重跑不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    data_pointer_final = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_final["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "全程不得切换旧数据活动指针（仍声明 legacy 身份）"
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "全程不得就地改写传入映射项（M0 事实分级保持不变）"
    )


def test_migrate_data_interrupted_batch_rerun_after_prefix_unaffected_source_manifest_change_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r"""中断后 r1 源 manifest 语义变化（不影响已落盘前缀）的重跑必须 fail-closed 停止。

    T19-P4 behavior（D2 边界补齐，先写测试，不改 production）—— D2 已确
    认：恢复凭证必须绑定映射和源内容；源内容不符即停止。T19-P3 钉了
    “使恢复依据失配”的两类源变化（已完成对象 manifest counts 变化、未完
    成对象半写前缀区域内 payload 变化）—— 两者都会被当前实现的核实口径
    （receipt 逐字段绑定 source_manifest_sha256 / 半写内容为当前源期望字
    节的前缀）发现。本切片钉 D2 的剩余边界：未完成对象 r1 的源 manifest
    语义变化但**不影响已落盘 payload 前缀**时（counts.published_candidates
    11 -> 12：payload 字节与 files[] 声明不动、半写残骸内没有
    release.yaml、残骸字节仍是当前源期望 payload 的严格前缀），按当前
    “以当前源复算期望字节”的恢复口径半写仍可核实为本转换部分写入，T13
    指针门（r1 无钉扎、r2 源未动）与 T14 自洽门（files[] 声明不动）均保
    持绿 —— 当前实现无从发现源已变化，会以改后源内容继续恢复。本切片要
    求：恢复依据必须绑定中断前源快照（部分写入对象在开始写入前持久化
    in-progress credential，见配套 credential 用例），中断后任何 legacy
    源内容变化（含不影响已落盘前缀的变化）重跑必须停止：
    1. 第一次双对象批调用 [r2, r1]：r2 完成、r1 写入中途被中断（T19 同
       款注入，fixture 前置事实：struck_writes 非空、r2 完整 + committed
       receipt、r1 半写残骸 + 同一个
       migration_receipts/data-v4.1-r1.receipt.yaml 以 in_progress 状态
       保留（用户确认生命周期，status: in_progress、
       target_release_digest: null）、legacy 不变）；
    2. 中断后修改 r1 源 manifest counts.published_candidates（不影响已
       落盘前缀，场景定义事实由前置断言钉死）；
    3. 同 root、相同映射（legacy 源内容已被本测试主动修改）重跑同一
       ``migrate_data`` 必须经 ``DataMigrationBlocked``（或其子类）
       fail-closed 拒绝 —— 不得成功返回（不得把源已变化的 r1 半写判为
       “可恢复”继续重建、不得以改后源内容完成 r1），不得把拒绝通道错位
       成 PermissionError 或任何其他异常；异常 cause/context 链不得含
       PermissionError（拒绝必须是写入前的只读判定）；
    4. fail-closed 拒绝零写入：整树（含测试主动修改的 legacy 源字节）与
       修改后基线逐字节一致、目标侧 mtime 与权限位不变 —— 不继续写 r1
       （半写残骸逐字节原样）、不重写 r2 或其 receipt、不把中断后保留的
       同一个 r1 in-progress receipt 覆盖/补写为 committed（逐字节原样
       保留，仍绑定中断前源快照；migration_receipts/ 恰含 r1 in-progress
       与 r2 committed 两份 receipt，不得另立 credential 目录/文件）、
       不产生 data-v4.1-r3 等新身份、不写 records / 生命周期目录 / .dvc、
       不就地修改传入映射项；
    5. 末尾对照（拒绝不得过宽 / 不得破坏恢复路径）：把 r1 源 manifest 恢
       复为原字节后，同 root、同映射的重跑必须重新成功（T19 既有中断恢
       复行为：跳过已完成 r2、继续并完成 r1）；完成的 r1 语义字段取（已
       恢复的）manifest 声明值（11）、封存事实保持、同一个 receipt 文件
       由 in_progress 原子转为 committed receipt —— 保
       持既有八字段契约且 source_manifest_sha256 与恢复后源 manifest 文
       件字节一致，migration_receipts/ 恰含两份 receipt、全程不得新增
       额外 credential 文件或目录；r2 侧零重写；legacy 侧与旧 pointers 不变；
    6. receipt 的文件名/位置/完成后转写已由用户裁决绑定（同一个
       receipt 文件、in_progress 原子转 committed，不另立 credential 目
       录），不再是不绑定项；本切片不做前缀区域受影响的源变化（T19-P3
       已钉）、不做已完成对象源变化（T19-P3 已钉）、不做 in-progress
       receipt 自身缺失/被篡改的拒绝分支、拒绝信息文本与“失配”归因通
       道、批内首个对象即中断、CLI、DVC、训练机真实路径。

    fixture：复用 T19 场景 helper ``_write_interrupt_scenario_layout`` 与
    ``_install_r1_target_mid_write_interruption``（T17/T18/T19 同款布局与
    counts 注入：r2 published_candidates 7、r1 为 11）；源变化经
    ``_change_partial_r1_legacy_source_manifest_counts`` 单一变量注入。本
    轮契约统一后，同一个 receipt 文件的中断后存在性（用户裁决生命周期）
    是本用例的 fixture 前置事实（``_assert_same_file_in_progress_receipt``
    —— 必须存在、status in_progress、target_release_digest null、绑定
    完整）与拒绝后零写入附带核实基线（逐字节原样、不得被覆盖为
    committed）；目标侧越界发现口径与配套 credential 用例同款（绑定 r1
    的非 committed 凭证只允许同一个 receipt 文件）。

    RED Gate 设计说明（T19-P4 fail-closed 用例，本轮契约统一后更新）：
    migrate_data 入口、DataMigrationBlocked 拒绝通道、T17 双对象批终
    态、T19 中断恢复与中断前源快照凭证机制均已存在（第一次中断调用成
    功构造批内部分完成状态为 fixture 前置事实，失败即 T19 回归而非本切
    片 RED），D2 的源变化 fail-closed 行为本身当前已满足（重跑经凭证与
    当前源比对后以 DataMigrationBlocked 干净拒绝且零写入）—— 本用例当
    前的 RED 只由用户裁决生命周期偏离给出：production 把 credential 写
    在 migration_receipts.in.progress/ 独立目录，同一个
    migration_receipts/data-v4.1-r1.receipt.yaml 中断后不存在 -> 中断
    后 fixture 前置事实的显式行为 AssertionError 钉出“同一个 receipt 文
    件未按用户确认生命周期以 in_progress 状态保留”；若 production 已
    返工到同一文件生命周期，本用例为 Unexpected PASS（转为 D2 源变化
    fail-closed 回归钉），不得为此制造无意义 production 修改。

    捕获的合理但错误实现：
    - 当前 production（RED 起点，用户裁决生命周期偏离）：credential 写
      在 migration_receipts.in.progress/ 独立目录、同一个 receipt 文件
      缺失 -> 中断后同一文件契约 fixture 前置事实断言失败；
    - （历史形态，源变化检测缺失时）重跑成功、r1 以改后源内容完成 ->
      “静默成功”AssertionError（RED 证据摘要随失败信息给出）；
    - “半写一律可恢复”：不绑定中断前源快照，只要残骸仍是当前源期望字节
      的前缀就继续重建 r1 -> 重跑写入 r1 -> 静默成功或零写入断言失败；
    - “只拦 payload 变化”：credential 只绑 payload/前缀哈希、不绑
      source_manifest_sha256 -> counts 变化发现不了 -> 静默成功（D2 要
      求“任何 legacy 源内容变化都停止”）；
    - “重做失配对象”：对源变化的 r1 重建/重写 release 或 receipt ->
      零写入断言失败（r2 侧 / r1 残骸 / credential 逐字节比对）；
    - “覆盖 credential 为 committed”：拒绝路径顺手把 credential 改写或
      补写 committed receipt -> 零写入与“不得覆盖 credential 为
      committed”断言失败；
    - 通道错位：以 PermissionError / ValueError / OSError 等未类型化异常
      替代 DataMigrationBlocked -> 通道错位 AssertionError；
    - “先写后拒”：先尝试写入、失败后再转译拒绝 -> cause 链
      PermissionError 断言失败；
    - 拒绝过宽：源恢复原字节后的末尾对照重跑也被拒 -> 行为 5 断言失败
      （T19 selector 同步回归可见）。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（本切片仅新增本
      用例与配套 fixture helper 及模块 docstring 清单条目，不改
      production）。
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_interrupted_batch_rerun_after_prefix_unaffected_source_manifest_change_fails_closed``
    - RED failure signature（本轮契约统一后）：恰一个失败用例（本
      selector），失败信息为 AssertionError “fixture 前置事实失败（中断
      后）：同一个 receipt 文件 migration_receipts/data-v4.1-r1.receipt.yaml
      必须存在（用户确认生命周期：写入前该文件为 status: in_progress、
      target_release_digest: null，中断后保留同一个 in-progress receipt，
      恢复成功后同一文件原子转为 committed；不得把 credential 写在
      migration_receipts.in.progress/ 等独立目录或额外凭证文件）”；
      fixture 前置事实（布局自洽、空目标根 precheck
      ready、第一次调用被中断命中且显式失败、r2 完成保留、r1 半写残骸、
      legacy 不变）全部不失败；源修改后前缀未受影响且 T13/T14 既有门保
      持绿的断言在 RED 阶段不执行到（失败先发生于同一文件契约）。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：T17/T18/T19 同款布局与 counts 场景注入（同一事实基
    #      线：r2 published_candidates 7、r1 为 11）。----
    _write_interrupt_scenario_layout(tmp_path)
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items

    # ---- fixture 前置事实（注入自洽 + D1/D2 镜像 + 目标根空闲）。----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    pointer = json.loads((tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded（D1）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2（D1）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )
    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T19 既有行为不可用，本切片 fixture 前置事实失"
        "败）"
    )
    blocked_exc = getattr(
        importlib.import_module("versioning.migration"),
        "DataMigrationBlocked",
        None,
    )
    assert blocked_exc is not None, (
        "data 迁移拒绝通道缺失：versioning.migration 未提供 "
        "DataMigrationBlocked（fail-closed 必须经既有迁移拒绝通道给出，本"
        "切片 fixture 前置事实失败）"
    )
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（T11 既有行为不可用，本切片 fixture "
        "前置事实失败）"
    )
    dual_precheck_report = precheck(tmp_path, mapping_items)
    assert dual_precheck_report.status == "ready", (
        "fixture 前置事实失败：空目标根上双对象批（r2+r1，D2 推荐顺序）的"
        f"只读预检必须整批 ready（实际 {dual_precheck_report.status!r}，"
        f"reasons={dual_precheck_report.reasons!r}）—— 第一次调用的失败只"
        "能由注入中断归因"
    )

    interrupted_before = _snapshot_tree(tmp_path)
    r1_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r1_receipt_file = (
        tmp_path / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r2_receipt_file = (
        tmp_path / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    # 中断前源快照：第一次调用读到的 r1 manifest 文件字节（credential 必
    # 须绑定的快照口径；末尾对照恢复也用该原字节）。
    r1_manifest_bytes_original = _manifest_file_of(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    ).read_bytes()
    r1_manifest_sha256_original = hashlib.sha256(
        r1_manifest_bytes_original
    ).hexdigest()
    r1_manifest_declared = json.loads(
        r1_manifest_bytes_original.decode("utf-8")
    )
    r1_declared_payload_paths = sorted(
        entry["path"] for entry in r1_manifest_declared["files"]
    )

    # ---- 行为前提构造 + 行为 1：第一次调用在 r1 写入中途被中断（T19 同
    #      款注入）。----
    struck_writes: list[Path] = []
    interruption = _install_r1_target_mid_write_interruption(
        monkeypatch, r1_release_dir, struck_writes
    )
    first_call_error: BaseException | None = None
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        first_call_error = exc
    assert first_call_error is not None, (
        "双对象批第一次调用必须在 r1 写入中途注入失败后显式失败（T19 既"
        "有批内部分完成状态构造，中断不得被吞掉后当作成功返回）"
    )
    assert struck_writes, (
        "中断注入失效：第一次调用的 r1 目标写入未被命中（T19 注入点契约："
        "struck_writes 为空即注入点需随实际写路径维护，本切片场景构造依赖"
        " r1 半写残骸真实存在）"
    )
    assert all(
        path.is_relative_to(r1_release_dir) for path in struck_writes
    ), (
        "中断注入命中范围异常：被中断的写入必须全部落在 r1 目标子树 "
        f"data/releases/{CONFIRMED_DATA_TARGET_R1}/ 内：实际 "
        f"{sorted(struck_writes)}"
    )

    # ---- fixture 前置事实：批内部分完成状态（T19 既有行为）。----
    r2_meta_after_interrupt = load_release_metadata(
        tmp_path / "data", CONFIRMED_DATA_TARGET_R2
    )
    assert r2_meta_after_interrupt.status is DataStatus.ACTIVE, (
        "fixture 前置事实失败：中断后 r2 必须经既有语义读回为 active 正式"
        "对象（批内部分完成状态的已完成侧前提）"
    )
    try:
        assert_payload_sealed(r2_release_dir)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：中断后保留的 r2 封存事实必须保持（既有"
            f"只读门 assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：中断后 r2 committed receipt 必须已写入"
    )
    r2_receipt_bytes_after_interrupt = r2_receipt_file.read_bytes()
    r2_completed_receipt = yaml.safe_load(
        r2_receipt_bytes_after_interrupt.decode("utf-8")
    )
    assert isinstance(r2_completed_receipt, dict), (
        "fixture 前置事实失败：r2 receipt 必须是 YAML 顶层映射"
    )
    assert set(r2_completed_receipt) == set(_RECEIPT_FIELDS), (
        "fixture 前置事实失败：r2 receipt 键集必须恰为八字段契约：实际 "
        f"{sorted(r2_completed_receipt)}"
    )
    assert r2_completed_receipt["status"] == "committed", (
        "fixture 前置事实失败：r2 receipt 必须为 committed"
    )
    r1_receipt_bytes_after_interrupt = _assert_same_file_in_progress_receipt(
        r1_receipt_file,
        CONFIRMED_DATA_TARGET_R1,
        r1_mapping,
        r1_manifest_sha256_original,
        context="fixture 前置事实失败（中断后）",
    )
    r1_partial_content = _release_content_files(r1_release_dir)
    assert r1_partial_content, (
        "fixture 前置事实失败：中断后 r1 目标内必须存在半写残骸（本切片"
        "“不影响已落盘前缀”的场景定义依赖残骸真实存在）"
    )
    assert "release.yaml" not in r1_partial_content, (
        "fixture 前置事实失败：中断注入应命中的是 r1 目标 payload 写入"
        "（当前 production 先复制 manifest files[] 声明的 payload、后写 "
        "release.yaml；写入机制变更时本前置事实与注入点需随实际写路径维"
        "护）"
    )
    for relative, partial_bytes in r1_partial_content.items():
        source_payload = _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, relative
        ).read_bytes()
        assert relative in set(r1_declared_payload_paths), (
            "fixture 前置事实失败：r1 半写残骸必须是 manifest 声明的 "
            f"payload（实际 {relative!r}）"
        )
        assert (
            0 < len(partial_bytes) < len(source_payload)
            and source_payload.startswith(partial_bytes)
        ), (
            "fixture 前置事实失败：r1 半写残骸必须是 legacy 源对应文件字"
            f"节的非空严格前缀（实际 {relative!r}）"
        )
    _assert_legacy_side_unchanged(interrupted_before, _snapshot_tree(tmp_path))
    assert mapping_items == _confirmed_data_mapping_items(), (
        "fixture 前置事实失败：中断失败路径不得就地改写传入映射项"
    )

    # ---- 状态快照：中断后保留状态（credential 附带核实、末尾对照与
    #      r2 侧零重写的比对基线）。----
    interrupted_tree = _snapshot_tree(tmp_path)
    r2_completed_content = _release_content_files(r2_release_dir)
    r2_completed_side_mtime = _snapshot_r2_completed_side_mtime_ns(tmp_path)

    # ---- 同一个 receipt 文件之外不得存在任何额外 credential 文件/目录
    #      （不得接受独立 credential 位置：目标侧绑定 r1 的非 committed
    #      凭证只能有同一个 receipt 文件，其存在性/状态/绑定已由上方
    #      fixture 前置事实钉定、字节快照已捕获供拒绝后逐字节不变比对）。----
    credential_candidates = _find_recovery_credential_candidates(
        tmp_path, CONFIRMED_DATA_SOURCE_R1, CONFIRMED_DATA_TARGET_R1
    )
    r1_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    extra_in_progress_credentials = sorted(
        relative
        for relative, mapping in credential_candidates
        if mapping.get("status") != "committed"
        and not relative.startswith(("workspace/", "finetune/", "pipeline/"))
        and relative != r1_receipt_rel
    )
    assert not extra_in_progress_credentials, (
        "中断后绑定 r1 的 in-progress 凭证只允许存在于同一个 receipt 文件 "
        f"{r1_receipt_rel}（用户确认生命周期：每个对象使用同一个 "
        "migration_receipts/<target_identity>.receipt.yaml，写入前 "
        "status: in_progress、target_release_digest: null，中断后保留同一"
        "个 in-progress receipt；不得把 credential 写在 "
        "migration_receipts.in.progress/ 等独立目录或任何额外凭证文件）："
        f"实际 {extra_in_progress_credentials}"
    )

    # ---- 行为前提构造：解除注入后修改 r1 源 manifest counts（不影响已
    #      落盘前缀的单一变量扰动）。----
    interruption.armed = False
    changed_source = _change_partial_r1_legacy_source_manifest_counts(tmp_path)
    changed_manifest_bytes = _manifest_file_of(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    ).read_bytes()
    assert (
        hashlib.sha256(changed_manifest_bytes).hexdigest()
        != r1_manifest_sha256_original
    ), (
        "fixture 前置事实失败：修改后的 r1 manifest 文件字节哈希必须与中断"
        "前源快照不同（本场景“源内容已变化”的事实前提）"
    )
    changed_manifest = json.loads(changed_manifest_bytes.decode("utf-8"))
    assert changed_manifest["counts"]["published_candidates"] == (
        _R1_CHANGED_PUBLISHED_CANDIDATES
    ), "fixture 前置事实失败：注入变体值必须生效"
    assert changed_manifest["counts"]["published_candidates"] != (
        r1_manifest_declared["counts"]["published_candidates"]
    ), (
        "fixture 前置事实失败：修改后声明值必须与中断前声明值不同（期望 "
        "release.yaml 语义内容失配）"
    )
    # 场景定义事实：变化不影响已落盘前缀 —— files[] 声明逐字节不动、
    # payload 字节不动（T14 自洽门保持绿）、残骸内没有 release.yaml、残骸
    # 字节仍是当前源期望 payload 的严格前缀。
    assert changed_manifest["files"] == r1_manifest_declared["files"], (
        "fixture 前置事实失败：注入必须只改 counts，files[] 声明（payload "
        "路径/哈希/size）不得变化（T14 自洽门保持绿，拒绝不得由 manifest "
        "声明哈希门归因）"
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    pointer_after_change = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert pointer_after_change["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：本场景不触碰 r2 源，指针与 r2 manifest 必须"
        "保持自洽（T13 钉扎门保持绿，重跑的拒绝不得由指针门归因）"
    )
    for relative, partial_bytes in r1_partial_content.items():
        source_payload = _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, relative
        ).read_bytes()
        assert (
            source_payload.startswith(partial_bytes)
            and len(partial_bytes) < len(source_payload)
        ), (
            "场景定义事实失败：源 manifest counts 变化不得影响已落盘前缀"
            f"（{relative!r} 残骸字节必须仍是当前源 payload 的严格前缀，"
            "否则本场景退化为 T19-P3 已钉的“前缀区域受影响”变化）"
        )
    assert "release.yaml" not in r1_partial_content, (
        "场景定义事实失败：残骸内不得存在 release.yaml（counts 变化喂的是"
        " release.yaml 语义内容；残骸内存在 release.yaml 即变化影响可观察"
        "的已落盘内容，本场景不成立）"
    )

    # ---- 修改后基线：fail-closed 拒绝“零写入”判定的比对快照（含测试主
    #      动修改的源字节自身）。----
    tampered_tree = _snapshot_tree(tmp_path)
    tampered_target_side_mtime = _snapshot_target_side_mtime_ns(tmp_path)
    tampered_modes = _snapshot_modes(tmp_path)

    # ---- 行为 3（RED）：同 root、相同映射重跑 —— 必须经
    #      DataMigrationBlocked fail-closed 拒绝。----
    blocked_error: BaseException | None = None
    try:
        migrate_data(tmp_path, mapping_items)
    except blocked_exc as exc:
        blocked_error = exc
    except Exception as exc:
        raise AssertionError(
            "中断后 r1 源 manifest 变化（不影响已落盘 payload 前缀）的重跑"
            "拒绝通道错位：migrate_data 对双对象批（r2 已完成保留 + r1 写"
            "入中途被中断，中断后 r1 源 manifest counts 已修改使中断前源"
            "快照与当前源不符）的同 root、相同映射重跑必须经 "
            "DataMigrationBlocked（或其子类）fail-closed 拒绝，实际抛出 "
            f"{type(exc).__name__}（不得以未类型化异常替代迁移域错误通"
            f"道；原始异常经 cause 链保留）：{exc!r}"
        ) from exc
    silent_success_evidence = ""
    if blocked_error is None:
        # RED 证据摘要：当前实现把改后源内容当作可恢复继续的依据完成了
        # r1 —— 证明当前实现无法阻止（无中断前源快照 credential，“按当前
        # 源复算期望字节”的半写核实在本场景必然匹配）。
        r1_receipt_written = r1_receipt_file.is_file()
        r1_release_sample_count: Any = None
        release_yaml_after = r1_release_dir / "release.yaml"
        if release_yaml_after.is_file():
            parsed_release = yaml.safe_load(
                release_yaml_after.read_text(encoding="utf-8")
            )
            if isinstance(parsed_release, Mapping):
                r1_release_sample_count = parsed_release.get("sample_count")
        silent_success_evidence = (
            "当前实现以改后源内容继续恢复并完成了 r1：r1 committed receipt "
            f"已写出={r1_receipt_written}，r1 release.yaml sample_count="
            f"{r1_release_sample_count!r}（中断前 manifest 声明值为 "
            f"{r1_manifest_declared['counts']['published_candidates']}）—— "
        )
    assert blocked_error is not None, (
        "中断后 r1 源 manifest 变化（不影响已落盘 payload 前缀）的重跑未 "
        "fail-closed 拒绝（静默成功）：" + silent_success_evidence +
        "D2 已确认：恢复凭证必须绑定映射和源内容；源内容不符即停止。r1 "
        "的中断前源快照（第一次调用读到的 manifest 文件字节）与当前源已"
        "经不同（counts.published_candidates "
        f"{r1_manifest_declared['counts']['published_candidates']} -> "
        f"{_R1_CHANGED_PUBLISHED_CANDIDATES}），部分写入对象的恢复依据必须"
        "以中断前源快照为准（在开始写入前持久化 in-progress credential，"
        "见配套 credential 用例），不得按改后源内容继续恢复。场景事实：该"
        "变化不影响已落盘 payload 前缀（payload 字节与 files[] 声明不动、"
        "残骸内无 release.yaml、残骸仍是当前源期望字节的严格前缀），既有 "
        "T13 指针门 / T14 自洽门均保持绿 —— 按当前源复算的恢复依据无法发"
        "现源已变化，本切片要求经 credential 与当前源比对后 fail-closed 停"
        "止（T19-P4 行为缺失）"
    )

    # 行为 3：拒绝必须是写入前的只读判定 —— cause/context 链不得含
    # PermissionError。
    chain_types: list[str] = []
    chain_cursor: BaseException | None = blocked_error
    visited_chain: set[int] = set()
    while chain_cursor is not None and id(chain_cursor) not in visited_chain:
        visited_chain.add(id(chain_cursor))
        chain_types.append(type(chain_cursor).__name__)
        next_cause = chain_cursor.__cause__
        chain_cursor = (
            next_cause if next_cause is not None else chain_cursor.__context__
        )
    assert "PermissionError" not in chain_types, (
        "源已变化的 fail-closed 拒绝退化为 PermissionError 转译："
        "DataMigrationBlocked 的异常 cause/context 链中检出 "
        f"PermissionError（链 {chain_types}）—— 拒绝必须是写入前的只读判"
        "定，不得经“重建尝试 -> 写失败 -> 转译”给出（权限位是偶然事实："
        "目标未封存时同一实现会真的写入失配内容）"
    )

    # ---- 行为 4：fail-closed 拒绝必须零写入 —— 整树与修改后基线逐字节
    #      一致（含测试主动修改的 legacy 源、旧 active pointers、已完成
    #      r2 release/receipt、r1 半写残骸、in-progress credential）。----
    after_tree = _snapshot_tree(tmp_path)
    tree_changed = sorted(
        key
        for key in set(tampered_tree) | set(after_tree)
        if tampered_tree.get(key) != after_tree.get(key)
    )
    assert not tree_changed, (
        "源已变化的 fail-closed 拒绝必须零写入：整树（含测试主动修改的"
        " legacy 源、旧 active pointers、已完成 r2 release/receipt、r1 半"
        "写残骸、in-progress credential）必须与修改后基线逐字节一致（不"
        "继续写入 r1、不重建 r1、不补写 r1 receipt、不重写 r2 或 receipt、"
        "不清理残骸、不“重新封存”、不写报告/缓存/records/生命周期目录）："
        f"实际变化条目 {tree_changed}"
    )
    assert r2_receipt_file.read_bytes() == r2_receipt_bytes_after_interrupt, (
        "fail-closed 拒绝不得重写已完成 r2 的 receipt（源已变化不得触发对"
        "凭证的重写/“重新封印”/digest 重算 —— 拒绝前必须停止）"
    )
    assert _release_content_files(r2_release_dir) == r2_completed_content, (
        "fail-closed 拒绝不得重写已完成的 data/releases/data-v4.1-r2（已完"
        "成对象的凭证与目标不得被源变化波及）"
    )
    assert _release_content_files(r1_release_dir) == r1_partial_content, (
        "fail-closed 拒绝不得继续写入 r1（源已变化的半写对象必须停止：残"
        "骸逐字节原样保留，不得被清理、补写或用改后源内容重建）"
    )
    assert r1_receipt_file.read_bytes() == r1_receipt_bytes_after_interrupt, (
        "fail-closed 拒绝不得改写同一个 r1 in-progress receipt（更不得覆"
        "盖/补写为 committed —— 凭证只在对象完整写入并验证后产生；同一文"
        "件是中断前源快照的持久化凭证，重跑用它与当前源比对后停止，拒绝路"
        "径不得破坏下一次比对的依据，零写入）"
    )
    _assert_same_file_in_progress_receipt(
        r1_receipt_file,
        CONFIRMED_DATA_TARGET_R1,
        r1_mapping,
        r1_manifest_sha256_original,
        context="fail-closed 拒绝后",
    )
    candidates_after_rejection = _find_recovery_credential_candidates(
        tmp_path, CONFIRMED_DATA_SOURCE_R1, CONFIRMED_DATA_TARGET_R1
    )
    committed_claims_after = [
        relative
        for relative, mapping in candidates_after_rejection
        if mapping.get("status") == "committed"
    ]
    assert not committed_claims_after, (
        "fail-closed 拒绝后不得存在把未完成 r1 伪称为 committed 的凭证条"
        f"目（拒绝路径零写入，credential 不得被覆盖为 committed）："
        f"{committed_claims_after}"
    )
    assert _snapshot_target_side_mtime_ns(tmp_path) == (
        tampered_target_side_mtime
    ), (
        "fail-closed 拒绝不得触碰目标侧任何条目元数据（data/ 与 "
        "migration_receipts/ 子树全部条目 mtime_ns 必须不变；字节恰好相同"
        "的重写也会更新 mtime）"
    )
    assert _snapshot_modes(tmp_path) == tampered_modes, (
        "fail-closed 拒绝不得改动任何条目权限位（不重新封存、不改写位、"
        "不得先解封再重建）"
    )
    releases_root = tmp_path / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "fail-closed 拒绝不得产生任何新身份/新条目（不覆盖、不自动改号）："
        f"data/releases/ 必须恰含 {CONFIRMED_DATA_TARGET_R1} 与 "
        f"{CONFIRMED_DATA_TARGET_R2}"
    )
    assert not (releases_root / "data-v4.1-r3").exists(), (
        "fail-closed 拒绝不得自动改号到 data-v4.1-r3"
    )
    receipts_root = tmp_path / "migration_receipts"
    assert [entry.name for entry in sorted(receipts_root.iterdir())] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        "fail-closed 拒绝后 migration_receipts/ 必须恰含 r1 in-progress 与"
        " r2 committed 两份 receipt（不新增凭证、不删除既有凭证；中断后保"
        "留的同一个 r1 receipt 不得被补写/覆盖为 committed，不得另立 "
        "credential 目录/文件）"
    )
    for forbidden in ("records", "working", "release_staging"):
        assert not (tmp_path / forbidden).exists(), (
            f"fail-closed 拒绝不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in after_tree), (
        "fail-closed 拒绝不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "fail-closed 拒绝不得就地改写传入映射项（M0 事实分级保持不变）"
    )

    # ---- 行为 5（末尾对照前提）：恢复被修改的 r1 源 manifest 原字节 ——
    #      整树必须精确回到中断后保留状态。----
    _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1).write_bytes(
        changed_source["r1_manifest"]
    )
    assert _snapshot_tree(tmp_path) == interrupted_tree, (
        "末尾对照前提失败：恢复被修改的 legacy 源原字节后，整树必须精确回"
        "到中断后保留状态（fail-closed 拒绝零写入 + 恢复逐字节精确，任何"
        "残留改动都在此暴露）"
    )

    # ---- 行为 5（末尾对照）：源恢复后同 root、同映射重跑必须重新成功
    #      （T19 既有中断恢复行为：跳过 r2、完成 r1）—— 拒绝不得过宽。----
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        raise AssertionError(
            "拒绝过宽或恢复路径被破坏：恢复 r1 源 manifest 原字节后的同 "
            "root、同映射重跑必须重新成功（T19 既有中断恢复行为：跳过凭"
            "证匹配的已完成 r2、继续并完成 r1；若此处失败，说明前述 "
            "fail-closed 拒绝条件过宽到拒绝了源未变化的正常恢复，或恢复路"
            f"径被破坏；原始异常经 cause 链保留）：{exc!r}"
        ) from exc

    # ---- 行为 5 终态：r1 完成（内容恰为 release.yaml + 声明 payload、
    #      payload 与已恢复的源逐字节一致）。----
    final_r1_content = _release_content_files(r1_release_dir)
    assert set(final_r1_content) == {"release.yaml"} | set(
        r1_declared_payload_paths
    ), (
        "末尾对照重跑必须完成 r1 正式 release：内容恰为 release.yaml + "
        "r1 manifest 声明的 payload 文件集合：实际 "
        f"{sorted(final_r1_content)}"
    )
    for declared_rel in r1_declared_payload_paths:
        assert final_r1_content[declared_rel] == _payload_file_of(
            tmp_path, CONFIRMED_DATA_SOURCE_R1, declared_rel
        ).read_bytes(), (
            f"末尾对照完成的 r1 payload {declared_rel!r} 必须与（已恢复"
            "的）legacy 源逐字节一致"
        )

    # r1 committed receipt：八字段契约保持 + 绑定恢复后的源快照。
    assert r1_receipt_file.is_file(), (
        "末尾对照重跑完成后必须写入 r1 committed receipt"
    )
    final_r1_receipt = yaml.safe_load(r1_receipt_file.read_text(encoding="utf-8"))
    assert isinstance(final_r1_receipt, dict), (
        "末尾对照写入的 r1 receipt 必须是 YAML 顶层映射"
    )
    assert set(final_r1_receipt) == set(_RECEIPT_FIELDS), (
        "credential 机制不得破坏 committed receipt 既有八字段契约（完成后"
        "的 receipt 键集必须恰为八字段，不得夹带 in-progress 凭证字段或映"
        f"射项 dump）：实际 {sorted(final_r1_receipt)}"
    )
    assert final_r1_receipt["status"] == "committed", (
        "末尾对照写入的 r1 receipt.status 必须为 committed"
    )
    assert final_r1_receipt["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1, (
        "r1 receipt.source_legacy_id 必须为 "
        f"{CONFIRMED_DATA_SOURCE_R1!r}"
    )
    assert final_r1_receipt["target_identity"] == CONFIRMED_DATA_TARGET_R1, (
        "r1 receipt.target_identity 必须为 "
        f"{CONFIRMED_DATA_TARGET_R1!r}"
    )
    assert final_r1_receipt["target_path"] == r1_mapping["target_path"], (
        "r1 receipt.target_path 必须与映射项声明的 target_path 一致"
    )
    assert final_r1_receipt["source_manifest_sha256"] == (
        r1_manifest_sha256_original
    ), (
        "r1 receipt.source_manifest_sha256 必须与（已恢复的）r1 源 manifest "
        "文件字节哈希一致（拒绝不得破坏恢复后凭证的源绑定）"
    )
    assert final_r1_receipt["target_release_digest"] == (
        _recompute_target_release_digest(final_r1_content)
    ), (
        "r1 receipt.target_release_digest 必须能由完成的 r1 目标内容按钉定"
        "口径复算验证"
    )

    # r1 语义读回：superseded、replacement 解析为既有 active r2、语义字段
    # 取（已恢复的）manifest 声明值（11）、封存事实保持。
    r1_meta = load_release_metadata(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        "末尾对照完成的 r1 必须经既有语义读回为 data-v4.1-r1"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        "末尾对照完成的 r1 status 必须为 superseded（映射 target_status，"
        f"D1 用户确认）：实际 {r1_meta.status!r}"
    )
    assert r1_meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        "末尾对照完成的 r1 replacement 必须为映射声明的 "
        f"{CONFIRMED_DATA_TARGET_R2!r}：实际 {r1_meta.replacement!r}"
    )
    replacement_meta = load_release_metadata(
        tmp_path / "data", r1_meta.replacement
    )
    assert replacement_meta.status is DataStatus.ACTIVE, (
        "末尾对照完成的 r1 replacement 必须解析为既有正式 active r2"
    )
    assert r1_meta.sample_count == (
        r1_manifest_declared["counts"]["published_candidates"]
    ), (
        "末尾对照完成的 r1 sample_count 必须取（已恢复的）r1 manifest "
        "counts.published_candidates 声明值（恢复只能以源原字节完成，证明"
        "拒绝只由源变化归因）"
    )
    expected_r1_splits = {
        f"fold_{fold}": {
            "train": r1_manifest_declared["counts"]["splits"][
                f"fold_{fold}_train"
            ],
            "validation": r1_manifest_declared["counts"]["splits"][
                f"fold_{fold}_val"
            ],
        }
        for fold in range(3)
    }
    assert dict(r1_meta.splits) == expected_r1_splits, (
        "末尾对照完成的 r1 splits 必须取（已恢复的）r1 manifest "
        "counts.splits 声明值"
    )
    try:
        assert_payload_sealed(r1_release_dir)
    except Exception as exc:
        raise AssertionError(
            "末尾对照完成的 r1 封存事实必须保持（既有只读门 "
            f"assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R2)
    with pytest.raises(ReferenceNotAllowed):
        validate_training_reference(tmp_path / "data", CONFIRMED_DATA_TARGET_R1)

    # r2 侧零重写、无新身份、legacy 侧回到初始、旧 pointers 不变。
    assert r2_receipt_file.read_bytes() == r2_receipt_bytes_after_interrupt, (
        "末尾对照重跑不得重写已完成 r2 的 receipt（跳过即不重写）"
    )
    assert _release_content_files(r2_release_dir) == r2_completed_content, (
        "末尾对照重跑不得重写已完成 r2 的正式 release"
    )
    assert _snapshot_r2_completed_side_mtime_ns(tmp_path) == (
        r2_completed_side_mtime
    ), (
        "末尾对照重跑不得触碰已完成 r2 侧任何条目元数据（r2 release 子树"
        "与 r2 receipt 全部条目 mtime_ns 不变）"
    )
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        "末尾对照重跑不得产生新身份：data/releases/ 必须恰含 r1 与 r2"
    )
    assert [entry.name for entry in sorted(receipts_root.iterdir())] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        "末尾对照重跑后 migration_receipts/ 必须恰含 r1 与 r2 两份 receipt"
        "（同一个 r1 receipt 文件由 in_progress 原子转为 committed —— 用"
        "户确认生命周期；不得另立 credential 目录/文件、不得额外保留 "
        "in-progress 状态）"
    )
    final_tree = _snapshot_tree(tmp_path)
    _assert_legacy_side_unchanged(interrupted_before, final_tree)
    final_new_keys = set(final_tree) - set(interrupted_before)
    r1_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R1}"
    r2_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R2}"
    r2_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    assert all(
        key == "data"
        or key == "data/releases"
        or key == r1_release_root_rel
        or key == r2_release_root_rel
        or key.startswith(f"{r1_release_root_rel}/")
        or key.startswith(f"{r2_release_root_rel}/")
        or key == "migration_receipts"
        or key == r1_receipt_rel
        or key == r2_receipt_rel
        for key in final_new_keys
    ), (
        "中断 + 拒绝 + 恢复重跑全程只允许新增两个 release 目录子树（含目录"
        "条目）、migration_receipts/ 与两份 receipt —— 不得新增额外 "
        f"credential 文件或目录（如 migration_receipts.in.progress/）：实际"
        f"新增 {sorted(final_new_keys)}"
    )
    data_pointer_final = json.loads(
        (tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_final["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "全程不得切换旧数据活动指针（仍声明 legacy 身份；源恢复后指针回"
        "到 fixture 原字节）"
    )
    prompt_pointer_final = yaml.safe_load(
        (tmp_path / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_final["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "全程不得切换旧 Prompt 活动指针（仍声明 legacy revision_id）"
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "全程不得就地改写传入映射项（M0 事实分级保持不变）"
    )


# ---------------------------------------------------------------------------
# T19-P4-P2：写入前 replacement / release 数据校验失败的零写入
# （reviewer 对 T19-P4 的 P2，先写测试，不改 production）
# ---------------------------------------------------------------------------


def _strip_r1_manifest_release_semantics_splits(root: Path) -> bytes:
    r"""删除 r1 legacy manifest counts.splits 声明（release 语义字段非法场景）。

    场景注入（T19-P4-P2 非法 release 语义字段用例）：_write_interrupt_
    scenario_layout 注入后的 r1 manifest counts 含 splits 声明；本函数
    删除 counts.splits，使写入侧 release 语义字段校验
    （_derive_release_splits 按 counts.splits 派生 release.yaml splits）
    必然失败 —— precheck 不校验 counts 语义（只读预检对该批仍 ready，
    失败只能由写入阶段归因）。files[] 声明哈希不动（T14 manifest 自洽
    门保持绿），r1 无钉扎（M0 pinned_by: ~，T13 指针门不受影响）。
    返回改前 manifest 原字节，供调用方在末尾恢复对照（重跑不得被
    stale credential 阻塞的修正输入）。
    """
    manifest_file = _manifest_file_of(root, CONFIRMED_DATA_SOURCE_R1)
    manifest_bytes_original = manifest_file.read_bytes()
    manifest = json.loads(manifest_bytes_original.decode("utf-8"))
    counts = manifest.get("counts")
    assert isinstance(counts, dict) and counts.get("splits"), (
        "fixture 前置事实失败：场景注入后的 r1 manifest counts 必须含非空 "
        "splits 声明（_write_interrupt_scenario_layout 注入值）"
    )
    del counts["splits"]
    _rewrite_legacy_release_manifest(root, CONFIRMED_DATA_SOURCE_R1, manifest)
    assert manifest_file.read_bytes() != manifest_bytes_original, (
        "fixture 前置事实失败：删除 counts.splits 必须真实改写 r1 manifest "
        "字节"
    )
    stripped = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert isinstance(stripped.get("counts"), dict) and (
        "splits" not in stripped["counts"]
    ), (
        "fixture 前置事实失败：改写后 r1 manifest counts 不得再含 splits "
        "声明"
    )
    return manifest_bytes_original


def _assert_rejected_object_zero_writes(
    root: Path,
    *,
    failing_source_id: str,
    failing_identity: str,
    completed_identity: str,
    rejection_context: str,
    snapshot_before_first_call: dict[str, bytes],
) -> None:
    r"""断言写入前数据校验失败的 fail-closed 拒绝对该对象真正零写入。

    T19-P4-P2（reviewer 对 T19-P4 的 P2）核心断言，两个用例共用：
    in-progress receipt 只允许在对象的全部写入前校验（superseded
    replacement 可解析性、release 语义字段如 counts.splits 派生合法）
    通过、即将开始写目标 release 时落盘（T19-P4 用户裁决生命周期）；
    这些校验的失败必须先于任何凭证/目标写入发生 ——
    - 不得留下 in-progress receipt：同一个
      ``migration_receipts/<identity>.receipt.yaml`` 与任何其他位置/形式
      的凭证条目（migration_receipts.in.progress/ 等独立目录）均不得
      存在；目标树中不得存在任何绑定失败对象的凭证（含 committed 伪
      称 —— 越界发现口径 _find_recovery_credential_candidates）；
    - 不得创建目标 release 目录：data/releases/ 只允许含批内已完成对
      象的 release 子树；
    - migration_receipts/ 只允许含已完成对象的 committed receipt；
    - 目标侧相对第一次调用前的快照不得新增除已完成对象 release 子
      树、migration_receipts/ 与其 committed receipt 之外的任何条目
      （records / working / release_staging / .dvc 均禁止）；
    - legacy 源与旧 active pointers 逐字节不变。
    先落盘的 receipt 绑定失败输入成为 stale credential，会把修正输入
    后的重跑堵死 —— 正是本切片要钉死的缺陷形态。
    """
    failing_release_dir = root / "data" / "releases" / failing_identity
    failing_receipt_file = (
        root / "migration_receipts" / f"{failing_identity}.receipt.yaml"
    )
    receipt_evidence = "不存在"
    if failing_receipt_file.exists():
        try:
            parsed_receipt = yaml.safe_load(failing_receipt_file.read_bytes())
        except Exception:
            receipt_evidence = "存在但不可解析"
        else:
            receipt_evidence = (
                f"存在且 status={parsed_receipt.get('status')!r}"
                if isinstance(parsed_receipt, Mapping)
                else "存在但顶层非 mapping"
            )
    assert not failing_receipt_file.exists(), (
        f"{rejection_context}必须零写入：不得留下 in-progress receipt —— "
        f"migration_receipts/{failing_identity}.receipt.yaml（或任何其他"
        "位置的凭证条目）不得存在：in-progress receipt 只允许在对象的"
        "全部写入前校验（superseded replacement 可解析性、release 语义"
        "字段合法）通过、即将开始写目标 release 时落盘（T19-P4 用户裁"
        "决生命周期），写入前数据校验失败的 fail-closed 拒绝必须先于凭"
        "证写入发生；先落盘的 receipt 绑定失败输入成为 stale "
        "credential，会把修正输入后的重跑堵死（reviewer 对 T19-P4 的 "
        f"P2）：实际 {receipt_evidence}"
    )
    assert not failing_release_dir.exists(), (
        f"{rejection_context}必须零写入：不得创建目标 release 目录 "
        f"data/releases/{failing_identity}（写入前数据校验失败发生在该"
        "对象任何目标子树写入之前）"
    )
    candidates = _find_recovery_credential_candidates(
        root, failing_source_id, failing_identity
    )
    assert not candidates, (
        f"{rejection_context}必须零写入：目标树中不得存在任何绑定失败对"
        f"象（{failing_source_id} / {failing_identity}）的凭证条目"
        "（committed 或 in-progress 均不允许 —— 失败路径零写入，不另立 "
        f"credential 目录/文件）：实际 {candidates}"
    )
    receipts_root = root / "migration_receipts"
    assert [entry.name for entry in sorted(receipts_root.iterdir())] == [
        f"{completed_identity}.receipt.yaml"
    ], (
        f"{rejection_context}后 migration_receipts/ 必须恰含已完成对象 "
        f"{completed_identity} 的 committed receipt 一份（失败对象零凭"
        f"证）：实际 "
        f"{[entry.name for entry in sorted(receipts_root.iterdir())]}"
    )
    releases_root = root / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        completed_identity
    ], (
        f"{rejection_context}后 data/releases/ 必须恰含已完成对象 "
        f"{completed_identity} 的 release 子树一棵（失败对象零目标写入、"
        "不得产生任何其他身份/新条目）：实际 "
        f"{[entry.name for entry in sorted(releases_root.iterdir())]}"
    )
    after_tree = _snapshot_tree(root)
    _assert_legacy_side_unchanged(snapshot_before_first_call, after_tree)
    completed_release_root_rel = f"data/releases/{completed_identity}"
    completed_receipt_rel = f"migration_receipts/{completed_identity}.receipt.yaml"
    new_keys = set(after_tree) - set(snapshot_before_first_call)
    assert all(
        key == "data"
        or key == "data/releases"
        or key == completed_release_root_rel
        or key.startswith(f"{completed_release_root_rel}/")
        or key == "migration_receipts"
        or key == completed_receipt_rel
        for key in new_keys
    ), (
        f"{rejection_context}后目标侧只允许新增已完成对象的 release 目录"
        f"子树（含目录条目）、migration_receipts/ 与其 committed "
        f"receipt —— 失败对象零写入，不得新增额外 credential 文件或目"
        f"录（如 migration_receipts.in.progress/）：实际新增 "
        f"{sorted(new_keys)}"
    )
    for forbidden in ("records", "working", "release_staging"):
        assert not (root / forbidden).exists(), (
            f"{rejection_context}不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in after_tree), (
        f"{rejection_context}不得触发 DVC（不得产生任何 .dvc 文件）"
    )


def _rerun_after_input_fix_and_assert_dual_batch_final_state(
    root: Path,
    *,
    fixed_mapping_items: list[dict[str, Any]],
    r1_manifest_bytes: bytes,
    r1_manifest_declared: Mapping[str, Any],
    r2_receipt_bytes_before_rerun: bytes,
    r2_release_content_before_rerun: Mapping[str, bytes],
    r2_completed_side_mtime_ns: Mapping[str, int],
    fixture_baseline_snapshot: dict[str, bytes],
    fix_context: str,
) -> None:
    r"""修正输入后的重跑必须成功（不被 stale credential 阻塞）且终态完整。

    T19-P4-P2 行为 3/4（两个用例共用）：失败路径零写入后不存在遗留
    credential，仅修正输入（r1 映射 replacement 改指既有正式 release /
    恢复 r1 manifest 语义字段原字节）后的重跑必须成功 —— 不得被失败
    调用遗留的 stale in-progress credential 与修正后映射/源的逐字段核
    实失配拒绝堵死（credential 失配拒绝的既有语义只应作用于真实中断
    的部分写入对象恢复，不适用于从未开始写目标的失败路径）。重跑语
    义复用既有行为：已完成 r2 凭证匹配幂等跳过（release/receipt 逐字
    节、mtime_ns 零变化），未完成 r1 完整完成：
    - data/releases/ 恰含 r1、r2；migration_receipts/ 恰含两份
      committed receipt（不遗留 in-progress 状态、不新增凭证文件/目
      录、不产生 data-v4.1-r9 / data-v4.1-r3 等新身份）；
    - r1 语义读回：superseded、replacement 解析为既有 active r2、
      sample_count / splits / source_batches 取（修正后的）manifest 声
      明值、封存事实保持；训练引用门 r2 放行、r1 拒绝；
    - r1 内容恰为 release.yaml + manifest 声明 payload 且逐字节一致；
    - r1 committed receipt 八字段契约：source_manifest_sha256 与修正后
      r1 manifest 文件字节哈希一致、target_release_digest 可由 r1 目
      标内容按钉定口径复算验证；
    - legacy 源与旧 active pointers 与 fixture 基线逐字节一致；目标侧
      新增条目只允许两个 release 子树、migration_receipts/ 与两份
      receipt；不写 records / working / release_staging、不触发 DVC；
    - 不就地改写传入映射项。
    """
    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T17 既有行为不可用，本切片 fixture 前置事实失"
        "败）"
    )
    try:
        migrate_data(root, fixed_mapping_items)
    except Exception as exc:
        raise AssertionError(
            f"{fix_context}后的重跑必须成功：不得被失败调用遗留的 stale "
            "in-progress credential 阻塞（写入前数据校验失败的拒绝路径不"
            "得遗留任何凭证 —— 遗留 credential 绑定失败输入，与修正后"
            "映射/源逐字段核实必然失配，把修正输入后的重跑堵死；credential "
            "失配拒绝只应作用于真实中断的部分写入对象恢复）：原始异常经 "
            f"cause 链保留：{exc!r}"
        ) from exc

    r1_release_dir = root / "data" / "releases" / CONFIRMED_DATA_TARGET_R1
    r2_release_dir = root / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r1_receipt_file = (
        root / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r2_receipt_file = (
        root / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )

    releases_root = root / "data" / "releases"
    assert [entry.name for entry in sorted(releases_root.iterdir())] == [
        CONFIRMED_DATA_TARGET_R1,
        CONFIRMED_DATA_TARGET_R2,
    ], (
        f"{fix_context}后的重跑不得产生新身份/新条目：data/releases/ 必须"
        f"恰含 {CONFIRMED_DATA_TARGET_R1} 与 {CONFIRMED_DATA_TARGET_R2}："
        f"实际 {[entry.name for entry in sorted(releases_root.iterdir())]}"
    )
    receipts_root = root / "migration_receipts"
    assert [entry.name for entry in sorted(receipts_root.iterdir())] == [
        f"{CONFIRMED_DATA_TARGET_R1}.receipt.yaml",
        f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml",
    ], (
        f"{fix_context}后的重跑必须恰留下两份 receipt（r1 与 r2 各一份 "
        "committed receipt；不得遗留 in-progress 状态或额外 credential "
        "文件/目录）：实际 "
        f"{[entry.name for entry in sorted(receipts_root.iterdir())]}"
    )

    # r1 语义读回：superseded、replacement 解析为既有 active r2、语义字
    # 段取（修正后的）manifest 声明值、封存事实保持；训练引用门不回归。
    r1_meta = load_release_metadata(root / "data", CONFIRMED_DATA_TARGET_R1)
    assert r1_meta.version == CONFIRMED_DATA_TARGET_R1, (
        f"{fix_context}后重跑完成的 r1 必须经既有语义读回为 "
        f"{CONFIRMED_DATA_TARGET_R1}"
    )
    assert r1_meta.status is DataStatus.SUPERSEDED, (
        f"{fix_context}后重跑完成的 r1 status 必须为 superseded（映射 "
        f"target_status，D1 用户确认）：实际 {r1_meta.status!r}"
    )
    assert r1_meta.replacement == CONFIRMED_DATA_TARGET_R2, (
        f"{fix_context}后重跑完成的 r1 replacement 必须为映射声明的 "
        f"{CONFIRMED_DATA_TARGET_R2!r}：实际 {r1_meta.replacement!r}"
    )
    replacement_meta = load_release_metadata(
        root / "data", r1_meta.replacement
    )
    assert replacement_meta.status is DataStatus.ACTIVE, (
        f"{fix_context}后重跑完成的 r1 replacement 必须解析为既有正式 "
        "active r2"
    )
    assert r1_meta.sample_count == (
        r1_manifest_declared["counts"]["published_candidates"]
    ), (
        f"{fix_context}后重跑完成的 r1 sample_count 必须取 r1 manifest 声"
        "明值（fixture 注入声明值与 payload 可复算值故意不同，钉定语义"
        f"溯源）：实际 {r1_meta.sample_count!r}"
    )
    expected_r1_splits = {
        f"fold_{fold}": {
            "train": r1_manifest_declared["counts"]["splits"][
                f"fold_{fold}_train"
            ],
            "validation": r1_manifest_declared["counts"]["splits"][
                f"fold_{fold}_val"
            ],
        }
        for fold in range(3)
    }
    assert dict(r1_meta.splits) == expected_r1_splits, (
        f"{fix_context}后重跑完成的 r1 splits 必须取 r1 manifest "
        "counts.splits 声明值"
    )
    assert set(r1_meta.source_batches) == {
        r1_manifest_declared["source_review_batch_id"],
        r1_manifest_declared["source_queue_id"],
        r1_manifest_declared["source_media_id"],
    }, (
        f"{fix_context}后重跑完成的 r1 source_batches 必须记录 manifest "
        "声明的原始批次标识"
    )
    try:
        assert_payload_sealed(r1_release_dir)
    except Exception as exc:
        raise AssertionError(
            f"{fix_context}后重跑完成的 r1 封存事实必须保持（既有只读门 "
            f"assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    validate_training_reference(root / "data", CONFIRMED_DATA_TARGET_R2)
    with pytest.raises(ReferenceNotAllowed):
        validate_training_reference(root / "data", CONFIRMED_DATA_TARGET_R1)

    # r1 内容恰为 release.yaml + manifest 声明 payload，逐字节与源一致。
    final_r1_content = _release_content_files(r1_release_dir)
    r1_declared_payload_paths = sorted(
        entry["path"] for entry in r1_manifest_declared["files"]
    )
    assert set(final_r1_content) == {"release.yaml"} | set(
        r1_declared_payload_paths
    ), (
        f"{fix_context}后重跑完成的 r1 目标 release 内容必须恰为 "
        "release.yaml + r1 manifest 声明的 payload 文件集合：实际 "
        f"{sorted(final_r1_content)}"
    )
    for declared_rel in r1_declared_payload_paths:
        assert final_r1_content[declared_rel] == _payload_file_of(
            root, CONFIRMED_DATA_SOURCE_R1, declared_rel
        ).read_bytes(), (
            f"{fix_context}后重跑完成的 r1 payload {declared_rel!r} 必须与 "
            "legacy 源逐字节一致"
        )

    # r1 committed receipt 八字段契约 + 两处哈希独立复算核实。
    assert r1_receipt_file.is_file(), (
        f"{fix_context}后重跑完成后必须写入 r1 committed receipt"
    )
    final_r1_receipt = yaml.safe_load(r1_receipt_file.read_text(encoding="utf-8"))
    assert isinstance(final_r1_receipt, dict), (
        f"{fix_context}后重跑写入的 r1 receipt 必须是 YAML 顶层映射"
    )
    assert set(final_r1_receipt) == set(_RECEIPT_FIELDS), (
        f"{fix_context}后重跑写入的 r1 receipt 键集必须恰为八字段契约（不"
        "得夹带 in-progress 凭证字段或映射项 dump）：实际 "
        f"{sorted(final_r1_receipt)}"
    )
    assert final_r1_receipt["status"] == "committed", (
        f"{fix_context}后重跑写入的 r1 receipt.status 必须为 committed：实"
        f"际 {final_r1_receipt['status']!r}"
    )
    assert final_r1_receipt["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1, (
        f"{fix_context}后重跑写入的 r1 receipt.source_legacy_id 必须为 "
        f"{CONFIRMED_DATA_SOURCE_R1!r}：实际 "
        f"{final_r1_receipt['source_legacy_id']!r}"
    )
    assert final_r1_receipt["target_identity"] == CONFIRMED_DATA_TARGET_R1, (
        f"{fix_context}后重跑写入的 r1 receipt.target_identity 必须为 "
        f"{CONFIRMED_DATA_TARGET_R1!r}：实际 "
        f"{final_r1_receipt['target_identity']!r}"
    )
    r1_fixed_item = next(
        item
        for item in fixed_mapping_items
        if item["source_legacy_id"] == CONFIRMED_DATA_SOURCE_R1
    )
    assert final_r1_receipt["target_path"] == r1_fixed_item["target_path"], (
        f"{fix_context}后重跑写入的 r1 receipt.target_path 必须与映射项声明"
        f"一致：实际 {final_r1_receipt['target_path']!r}"
    )
    assert final_r1_receipt["source_manifest_sha256"] == hashlib.sha256(
        r1_manifest_bytes
    ).hexdigest(), (
        f"{fix_context}后重跑写入的 r1 receipt.source_manifest_sha256 必须"
        "与（修正后的）r1 源 manifest 文件字节哈希一致"
    )
    assert final_r1_receipt["target_release_digest"] == (
        _recompute_target_release_digest(final_r1_content)
    ), (
        f"{fix_context}后重跑写入的 r1 receipt.target_release_digest 必须"
        "能由完成的 r1 目标内容按钉定口径复算验证"
    )
    assert (
        isinstance(final_r1_receipt["operation_id"], str)
        and final_r1_receipt["operation_id"]
    ), (
        f"{fix_context}后重跑写入的 r1 receipt.operation_id 必须是非空字符串"
    )
    assert (
        isinstance(final_r1_receipt["written_at"], str)
        and final_r1_receipt["written_at"]
    ), f"{fix_context}后重跑写入的 r1 receipt.written_at 必须是非空字符串"

    # r2 侧零重写（跳过已完成对象：receipt 字节 / 内容 / mtime 不动）。
    assert r2_receipt_file.read_bytes() == r2_receipt_bytes_before_rerun, (
        f"{fix_context}后的重跑不得重写已完成 r2 的 receipt（跳过即不重写）"
    )
    assert _release_content_files(r2_release_dir) == dict(
        r2_release_content_before_rerun
    ), f"{fix_context}后的重跑不得重写已完成 r2 的正式 release"
    assert _snapshot_r2_completed_side_mtime_ns(root) == dict(
        r2_completed_side_mtime_ns
    ), (
        f"{fix_context}后的重跑不得触碰已完成 r2 侧任何条目元数据（r2 "
        "release 子树与 r2 receipt 全部条目 mtime_ns 不变）"
    )

    # 全树口径：legacy 侧与 fixture 基线逐字节一致；目标侧新增条目只允
    # 许两个 release 子树、migration_receipts/ 与两份 receipt。
    final_tree = _snapshot_tree(root)
    _assert_legacy_side_unchanged(fixture_baseline_snapshot, final_tree)
    r1_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R1}"
    r2_release_root_rel = f"data/releases/{CONFIRMED_DATA_TARGET_R2}"
    r1_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R1}.receipt.yaml"
    )
    r2_receipt_rel = (
        f"migration_receipts/{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    final_new_keys = set(final_tree) - set(fixture_baseline_snapshot)
    assert all(
        key == "data"
        or key == "data/releases"
        or key == r1_release_root_rel
        or key == r2_release_root_rel
        or key.startswith(f"{r1_release_root_rel}/")
        or key.startswith(f"{r2_release_root_rel}/")
        or key == "migration_receipts"
        or key == r1_receipt_rel
        or key == r2_receipt_rel
        for key in final_new_keys
    ), (
        f"{fix_context}后的重跑全程只允许新增两个 release 目录子树（含目"
        "录条目）、migration_receipts/ 与两份 receipt —— 不得新增额外 "
        f"credential 文件或目录：实际新增 {sorted(final_new_keys)}"
    )
    for forbidden in ("records", "working", "release_staging"):
        assert not (root / forbidden).exists(), (
            f"{fix_context}后的重跑不得创建 {forbidden!r}"
        )
    assert not any(key.endswith(".dvc") for key in final_tree), (
        f"{fix_context}后的重跑不得触发 DVC（不得产生任何 .dvc 文件）"
    )
    data_pointer_final = json.loads(
        (root / _DATA_POINTER_REL).read_text(encoding="utf-8")
    )
    assert data_pointer_final["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "全程不得切换旧数据活动指针（仍声明 legacy 身份）"
    )
    prompt_pointer_final = yaml.safe_load(
        (root / "pipeline" / "prompt_control" / "active_prompt.yaml")
        .read_bytes()
    )
    assert prompt_pointer_final["revision_id"] == CONFIRMED_PROMPT_SOURCE_ID, (
        "全程不得切换旧 Prompt 活动指针（仍声明 legacy revision_id）"
    )
    assert fixed_mapping_items == _confirmed_data_mapping_items(), (
        "全程不得就地改写传入映射项（M0 事实分级保持不变）"
    )


def test_migrate_data_dangling_replacement_rejected_without_persisting_in_progress_receipt(
    tmp_path: Path,
) -> None:
    r"""悬空 replacement 的 fail-closed 拒绝必须零写入：不留 in-progress receipt。

    T19-P4-P2 behavior（reviewer 对 T19-P4 的 P2，先写测试，不改
    production）—— T19-P4 为部分写入对象钉定了 in-progress receipt 生
    命周期（同一个 migration_receipts/<target_identity>.receipt.yaml，
    写目标前 in_progress、成功后原子转 committed），但当前 production
    在 _migrate_single_data_release 中把该 credential 写在 superseded
    replacement 可解析性校验之前 —— replacement 悬空时 in-progress
    receipt 已落盘，fail-closed 拒绝留下绑定失败输入的 stale
    credential，并堵死修正输入后的重跑（credential 逐字段核实失配即
    拒绝）。本切片钉定：
    1. superseded 映射的 replacement 悬空（格式合法完整 data 身份，但
       目标 root 中没有对应正式 release）时，migrate_data 必须经
       DataMigrationBlocked fail-closed 拒绝（T15/T16 既有写入前
       replacement 可解析性语义）；
    2. 该拒绝必须真正零写入：不创建 r1 目标 release 目录、不留
       in-progress receipt（migration_receipts/ 恰含批内先完成的 r2
       committed receipt 一份），目标侧无任何额外条目，legacy 源与旧
       active pointers 逐字节不变；
    3. 修正输入（r1 replacement 改指已完成的 data-v4.1-r2）后的重跑必
       须成功 —— 不得被失败调用遗留的 stale credential 失配拒绝堵死：
       r2 幂等跳过零重写、r1 完整完成，终态与既有 T17 双对象契约一致；
    4. T19-P4 正常中断的 credential 生命周期不回归（由既有 T19-P4
       selector 复跑钉定，本用例不注入中断）。

    fixture：复用 T17/T18/T19 场景布局 _write_interrupt_scenario_layout
    （三份 legacy release + 旧数据/Prompt 活动指针 + r2/r1 counts 注入，
    r2 published 7、r1 为 11）与 T18-P2 的 replacement 变体批
    _dual_object_batch_with_changed_r1_replacement（r1 replacement=
    data-v4.1-r9，空目标根上 precheck-ready 的格式合法变体 —— T17 已钉
    precheck 不要求 replacement 预先存在；第一次调用的失败只能由写入
    阶段的 replacement 可解析性校验归因，不得由身份格式/源/映射结构归
    因）。

    RED Gate 设计说明（T19-P4-P2 悬空 replacement 用例）：migrate_data
    入口、DataMigrationBlocked 拒绝通道与 T17/T18/T19 既有行为均存在
    （变体批 precheck ready、第一次调用在 r1 处 DataMigrationBlocked
    —— 悬空 replacement 的 fail-closed 拒绝本身当前已满足，r2 批内先
    完成亦为既有行为，均为 fixture 前置事实），本切片 RED 不经入口缺
    失或拒绝通道缺失分支给出 —— 由拒绝后的零写入断言钉出
    “in-progress receipt 已在 replacement 可解析性校验失败前落盘”：
    当前 production 在校验前写入
    migration_receipts/data-v4.1-r1.receipt.yaml（status: in_progress），
    零 receipt 断言失败（P2 缺陷形态）；修正 replacement 后的重跑断言
    在 RED 阶段不执行到（失败先发生于零 receipt 断言），其当前
    production 行为（被 stale credential 失配拒绝）恰为本切片行为 3 要
    钉死的缺陷，GREEN 后转为重跑不被阻塞的回归钉。

    捕获的合理但错误实现：
    - 当前 production（RED 起点，P2 缺陷）：credential 写在 replacement
      可解析性校验之前 -> 悬空 replacement 拒绝后 r1 receipt 以
      in_progress 遗留 -> 零 receipt 断言失败；
    - “写入后补偿清理”：先写 credential、校验失败后再删除 -> 时序上仍
      先落盘（中断/崩溃窗口内遗留 stale credential），零写入断言钉的
      是“校验先于写入”而非“失败后清理”，补偿实现无法通过时序契约；
    - “不校验可解析性”：只校验 replacement 格式 -> 悬空 replacement 静
      默写出带悬空引用的 superseded release -> 第一次调用未显式失败/
      既有读取语义断言失败（T15/T16 已钉，本切片不重复）；
    - “修正后被 stale credential 阻塞”：失败遗留 credential 使修正后
      重跑失配被拒 -> 行为 3 断言失败；
    - “顺带重写已完成对象”：修正重跑重写 r2 或其 receipt -> r2 侧零重
      写断言失败。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（本切片仅新增用
      例与配套 helper 及模块 docstring 清单条目，不改 production）。
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_dangling_replacement_rejected_without_persisting_in_progress_receipt``
    - RED failure signature：恰一个失败用例（本 selector），失败信息为
      AssertionError “悬空 replacement 的 fail-closed 拒绝必须零写入：
      不得留下 in-progress receipt —— migration_receipts/
      data-v4.1-r1.receipt.yaml（或任何其他位置的凭证条目）不得存在：
      ……（reviewer 对 T19-P4 的 P2）：实际 存在且 status='in_progress'”；
      fixture 前置事实（变体批 precheck ready、第一次调用
      DataMigrationBlocked、r2 完成保留且 committed receipt 八字段）全
      部不失败。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：T17/T18/T19 同款布局与 counts 场景注入（同一事实基
    #      线：r2 published_candidates 7、r1 为 11）。----
    _write_interrupt_scenario_layout(tmp_path)
    mapping_items = _dual_object_batch_with_changed_r1_replacement()
    r2_mapping, r1_mapping = mapping_items

    # ---- fixture 前置事实（注入自洽 + D1/D2 镜像 + 变体批归因隔离）。----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    pointer = json.loads((tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded（D1）"
    )
    assert r1_mapping["replacement"] == _CHANGED_R1_REPLACEMENT, (
        "fixture 前置事实失败：r1 映射 replacement 必须为悬空变体 "
        f"{_CHANGED_R1_REPLACEMENT!r}（格式合法完整 data 身份）"
    )
    assert _CHANGED_R1_REPLACEMENT != CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：悬空 replacement 必须与已确认的 "
        f"{CONFIRMED_DATA_TARGET_R2!r} 是不同身份"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )
    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T17 既有行为不可用，本切片 fixture 前置事实"
        "失败）"
    )
    blocked_exc = getattr(
        importlib.import_module("versioning.migration"),
        "DataMigrationBlocked",
        None,
    )
    assert blocked_exc is not None, (
        "data 迁移拒绝通道缺失：versioning.migration 未提供 "
        "DataMigrationBlocked（fail-closed 必须经既有迁移拒绝通道给出，本"
        "切片 fixture 前置事实失败）"
    )
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（T11 既有行为不可用，本切片 fixture "
        "前置事实失败）"
    )
    variant_precheck_report = precheck(tmp_path, mapping_items)
    assert variant_precheck_report.status == "ready", (
        "fixture 前置事实失败：悬空 replacement 变体批（replacement="
        f"{_CHANGED_R1_REPLACEMENT}，格式合法完整 data 身份）在空目标根上"
        "必须整批 precheck ready —— 第一次调用的失败只能由写入阶段的 "
        "replacement 可解析性校验归因，不得由身份格式/源/映射结构归因"
        f"（实际 {variant_precheck_report.status!r}，"
        f"reasons={variant_precheck_report.reasons!r}）"
    )

    fixture_baseline = _snapshot_tree(tmp_path)
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
    r1_manifest_bytes = _manifest_file_of(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    ).read_bytes()
    r1_manifest_declared = json.loads(r1_manifest_bytes.decode("utf-8"))

    # ---- 行为 1：第一次调用经 DataMigrationBlocked fail-closed 拒绝。----
    first_call_error: BaseException | None = None
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        first_call_error = exc
    assert isinstance(first_call_error, blocked_exc), (
        "replacement 悬空（目标 root 无对应正式 release）的双对象批第一"
        "次调用必须经 DataMigrationBlocked fail-closed 拒绝（T15/T16 既"
        "有写入前 replacement 可解析性语义；r2 批内先完成、r1 在写入阶"
        f"段被拒）：实际 {first_call_error!r}"
    )

    # ---- fixture 前置事实：批内部分完成（r2 先完成，T19 既有形态）。----
    r2_meta_after_rejection = load_release_metadata(
        tmp_path / "data", CONFIRMED_DATA_TARGET_R2
    )
    assert r2_meta_after_rejection.status is DataStatus.ACTIVE, (
        "fixture 前置事实失败：拒绝发生时批内先完成的 r2 必须经既有语义"
        "读回为 active 正式对象（批内部分完成状态的已完成侧前提）"
    )
    try:
        assert_payload_sealed(
            tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2
        )
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：批内先完成的 r2 封存事实必须保持（既有"
            f"只读门 assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    r2_receipt_file = (
        tmp_path / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：批内先完成的 r2 committed receipt 必须已写入"
    )
    r2_receipt_bytes_before_rerun = r2_receipt_file.read_bytes()
    r2_completed_receipt = yaml.safe_load(
        r2_receipt_bytes_before_rerun.decode("utf-8")
    )
    assert isinstance(r2_completed_receipt, dict), (
        "fixture 前置事实失败：r2 receipt 必须是 YAML 顶层映射"
    )
    assert set(r2_completed_receipt) == set(_RECEIPT_FIELDS), (
        "fixture 前置事实失败：r2 receipt 键集必须恰为八字段契约：实际 "
        f"{sorted(r2_completed_receipt)}"
    )
    assert r2_completed_receipt["status"] == "committed", (
        "fixture 前置事实失败：r2 receipt 必须为 committed"
    )
    r2_release_content_before_rerun = _release_content_files(r2_release_dir)
    r2_completed_side_mtime = _snapshot_r2_completed_side_mtime_ns(tmp_path)

    # ---- 行为 2（RED 核心）：悬空 replacement 的拒绝零写入 —— 不得创
    #      建目标目录，也不得留下 in-progress receipt。----
    _assert_rejected_object_zero_writes(
        tmp_path,
        failing_source_id=CONFIRMED_DATA_SOURCE_R1,
        failing_identity=CONFIRMED_DATA_TARGET_R1,
        completed_identity=CONFIRMED_DATA_TARGET_R2,
        rejection_context="悬空 replacement 的 fail-closed 拒绝",
        snapshot_before_first_call=fixture_baseline,
    )
    assert mapping_items == _dual_object_batch_with_changed_r1_replacement(), (
        "全程不得就地改写传入映射项（悬空 replacement 变体批保持不变）"
    )

    # ---- 行为 3：修正输入（replacement 改指已完成的 r2）后的重跑不被
    #      stale credential 阻塞 + 双对象终态完整。----
    _rerun_after_input_fix_and_assert_dual_batch_final_state(
        tmp_path,
        fixed_mapping_items=_confirmed_data_mapping_items(),
        r1_manifest_bytes=r1_manifest_bytes,
        r1_manifest_declared=r1_manifest_declared,
        r2_receipt_bytes_before_rerun=r2_receipt_bytes_before_rerun,
        r2_release_content_before_rerun=r2_release_content_before_rerun,
        r2_completed_side_mtime_ns=r2_completed_side_mtime,
        fixture_baseline_snapshot=fixture_baseline,
        fix_context="修正 r1 映射 replacement 为已完成的 data-v4.1-r2",
    )


def test_migrate_data_invalid_release_semantics_rejected_without_persisting_in_progress_receipt(
    tmp_path: Path,
) -> None:
    r"""非法 release 语义字段（缺 counts.splits）的拒绝必须零写入：不留 receipt。

    T19-P4-P2 behavior（reviewer 对 T19-P4 的 P2，先写测试，不改
    production）—— 与悬空 replacement 用例同一缺陷形态的另一半：当前
    production 把 in-progress credential 写在 release 语义字段校验
    （_build_release_data / _derive_release_splits 按 legacy manifest
    counts.splits 派生 release.yaml splits）之前 —— 语义字段非法（例如
    缺 counts.splits）时 in-progress receipt 已落盘，fail-closed 拒绝留
    下绑定失败输入的 stale credential，并堵死修正输入后的重跑。本切
    片钉定：
    1. legacy manifest 的 release 语义字段非法（counts 删除 splits 声
       明）时，migrate_data 必须经 DataMigrationBlocked fail-closed 拒
       绝；
    2. 该拒绝必须真正零写入：不创建 r1 目标 release 目录、不留
       in-progress receipt（migration_receipts/ 恰含批内先完成的 r2
       committed receipt 一份），目标侧无任何额外条目，legacy 源（含
       测试主动改坏的 manifest 字节）与旧 active pointers 在拒绝后逐
       字节不变；
    3. 恢复 manifest 原字节（修正输入）后的重跑必须成功 —— 不得被失
       败调用遗留的 stale credential 失配拒绝堵死：r2 幂等跳过零重写、
       r1 完整完成（语义字段取已恢复 manifest 声明值），终态与既有
       T17 双对象契约一致；
    4. T19-P4 正常中断的 credential 生命周期不回归（由既有 T19-P4
       selector 复跑钉定，本用例不注入中断）。

    fixture：复用 T17/T18/T19 场景布局 _write_interrupt_scenario_layout
    （三份 legacy release + 旧数据/Prompt 活动指针 + r2/r1 counts 注
    入，r2 published 7、r1 为 11）+ r1 manifest counts 删除 splits 声
    明（_strip_r1_manifest_release_semantics_splits：files[] 声明哈
    希不动保持 T14 自洽门绿、r1 无钉扎保持 T13 指针门绿、precheck 不
    校验 counts 语义使该批仍 precheck ready —— 第一次调用的失败只能
    由写入阶段的 release 语义字段校验归因）；两条映射保持 D1 原样
    （r1 replacement=data-v4.1-r2，r2 批内先完成后可解析）。基线快
    照分两份：pristine（改坏前拍，末段 legacy 侧与全树 diff 的对照
    基线 —— 恢复原字节后逐字节可比）与 stripped（改坏后拍，第一次
    调用零写入比对的基线）。

    RED Gate 设计说明（T19-P4-P2 非法 release 语义字段用例）：与悬空
    replacement 用例同口径 —— migrate_data 入口、DataMigrationBlocked
    拒绝通道与 T17/T18/T19 既有行为均存在（坏 manifest 批 precheck
    ready、第一次调用在 r1 处 DataMigrationBlocked —— 缺 counts.splits
    的写入侧拒绝本身当前已满足，r2 批内先完成亦为既有行为，均为
    fixture 前置事实），RED 不经入口缺失或拒绝通道缺失分支给出 ——
    由拒绝后的零写入断言钉出“in-progress receipt 已在 release 语义
    字段校验失败前落盘”：当前 production 在校验前写入
    migration_receipts/data-v4.1-r1.receipt.yaml（status: in_progress），
    零 receipt 断言失败（P2 缺陷形态）；恢复 manifest 后的重跑断言在
    RED 阶段不执行到（失败先发生于零 receipt 断言），其当前 production
    行为（stale credential 绑定坏 manifest 哈希、与恢复后源失配被拒）
    恰为本切片行为 3 要钉死的缺陷，GREEN 后转为重跑不被阻塞的回归钉。

    捕获的合理但错误实现：
    - 当前 production（RED 起点，P2 缺陷）：credential 写在 release 语
      义字段校验之前 -> 缺 counts.splits 拒绝后 r1 receipt 以
      in_progress 遗留 -> 零 receipt 断言失败；
    - “写入后补偿清理”：先写 credential、校验失败后再删除 -> 时序上仍
      先落盘（中断/崩溃窗口内遗留 stale credential），零写入断言钉的
      是“校验先于写入”而非“失败后清理”；
    - “坏语义静默放行/伪造”：缺 splits 时伪造空 splits 或回填重算值写
      出 release -> 第一次调用未显式失败/语义溯源断言失败（T15 已钉
      语义字段取声明值不重算不伪造，本切片不重复）；
    - “恢复后被 stale credential 阻塞”：失败遗留 credential 使恢复后
      重跑失配被拒 -> 行为 3 断言失败；
    - “顺带重写已完成对象”：恢复重跑重写 r2 或其 receipt -> r2 侧零
      重写断言失败。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（本切片仅新增用
      例与配套 helper 及模块 docstring 清单条目，不改 production）。
    - 命令：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_migrate_data_invalid_release_semantics_rejected_without_persisting_in_progress_receipt``
    - RED failure signature：恰一个失败用例（本 selector），失败信息为
      AssertionError “非法 release 语义字段（缺 counts.splits）的
      fail-closed 拒绝必须零写入：不得留下 in-progress receipt ——
      migration_receipts/data-v4.1-r1.receipt.yaml（或任何其他位置的凭
      证条目）不得存在：……（reviewer 对 T19-P4 的 P2）：实际 存在且
      status='in_progress'”；fixture 前置事实（坏 manifest 批 precheck
      ready、第一次调用 DataMigrationBlocked、r2 完成保留且 committed
      receipt 八字段）全部不失败。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    # ---- fixture：T17/T18/T19 同款布局与 counts 场景注入 + r1 manifest
    #      删除 counts.splits（release 语义字段非法变体）。----
    _write_interrupt_scenario_layout(tmp_path)
    # pristine 基线（改坏前拍）：末段 legacy 侧与全树 diff 的对照基线
    #（legacy 侧 == 场景注入原字节；目标根空闲）。
    pristine_baseline = _snapshot_tree(tmp_path)
    r1_manifest_bytes_original = _strip_r1_manifest_release_semantics_splits(
        tmp_path
    )
    r1_manifest_declared_original = json.loads(
        r1_manifest_bytes_original.decode("utf-8")
    )
    stripped_manifest_declared = json.loads(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1)
        .read_text(encoding="utf-8")
    )
    mapping_items = _confirmed_data_mapping_items()
    r2_mapping, r1_mapping = mapping_items

    # ---- fixture 前置事实（注入自洽 + D1/D2 镜像 + 坏 manifest 批归
    #      因隔离）。----
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R1
    )
    _assert_payload_declared_hashes_self_consistent(
        tmp_path, CONFIRMED_DATA_SOURCE_R2
    )
    assert "splits" not in stripped_manifest_declared["counts"], (
        "fixture 前置事实失败：改写后 r1 manifest counts 必须不含 splits "
        "声明（本切片场景定义：release 语义字段非法）"
    )
    pointer = json.loads((tmp_path / _DATA_POINTER_REL).read_text(encoding="utf-8"))
    assert pointer["release_id"] == CONFIRMED_DATA_SOURCE_R2, (
        "fixture 前置事实失败：旧数据活动指针必须钉扎 r2 映射声明的源"
    )
    assert pointer["expected_manifest_sha256"] == hashlib.sha256(
        _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R2).read_bytes()
    ).hexdigest(), (
        "fixture 前置事实失败：注入后指针 expected_manifest_sha256 必须"
        "与 r2 manifest 文件字节复算哈希自洽（T13 钉扎门保持绿）"
    )
    assert [item["source_legacy_id"] for item in mapping_items] == [
        CONFIRMED_DATA_SOURCE_R2,
        CONFIRMED_DATA_SOURCE_R1,
    ], "fixture 前置事实失败：双对象映射批必须按 D2 推荐顺序 r2 先于 r1 排列"
    assert r2_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R2
    assert r2_mapping["target_status"] == "active", (
        "fixture 前置事实失败：r2 映射 target_status 必须为 active（D1）"
    )
    assert "replacement" not in r2_mapping, (
        "fixture 前置事实失败：r2 映射不得携带 replacement（D1）"
    )
    assert r1_mapping["candidate_target_identity"] == CONFIRMED_DATA_TARGET_R1
    assert r1_mapping["target_status"] == "superseded", (
        "fixture 前置事实失败：r1 映射 target_status 必须为 superseded（D1）"
    )
    assert r1_mapping["replacement"] == CONFIRMED_DATA_TARGET_R2, (
        "fixture 前置事实失败：r1 映射 replacement 必须为 data-v4.1-r2"
        "（D1；r2 批内先完成后可解析，本切片失败只能由 release 语义字"
        "段校验归因，不得由 replacement 可解析性归因）"
    )
    for forbidden in _PRECHECK_FORBIDDEN_ROOTS:
        assert not (tmp_path / forbidden).exists(), (
            f"fixture 前置事实失败：目标根 {forbidden!r} 必须保持空闲"
        )
    migrate_data = _resolve_migrate_data_entry()
    assert migrate_data is not None, (
        "双对象批 data 真实迁移入口缺失：versioning.migration 未提供 "
        "migrate_data 入口（T17 既有行为不可用，本切片 fixture 前置事实"
        "失败）"
    )
    blocked_exc = getattr(
        importlib.import_module("versioning.migration"),
        "DataMigrationBlocked",
        None,
    )
    assert blocked_exc is not None, (
        "data 迁移拒绝通道缺失：versioning.migration 未提供 "
        "DataMigrationBlocked（fail-closed 必须经既有迁移拒绝通道给出，本"
        "切片 fixture 前置事实失败）"
    )
    precheck = _resolve_data_precheck_entry()
    assert precheck is not None, (
        "批级只读预检行为缺失：versioning.migration 未提供 "
        "precheck_data_migration 入口（T11 既有行为不可用，本切片 fixture "
        "前置事实失败）"
    )
    bad_semantics_precheck_report = precheck(tmp_path, mapping_items)
    assert bad_semantics_precheck_report.status == "ready", (
        "fixture 前置事实失败：r1 manifest 缺 counts.splits 的双对象批必"
        "须整批 precheck ready（只读预检不校验 counts 语义；files[] 声明"
        "哈希自洽保持 T14 门绿、r1 无钉扎保持 T13 门绿）—— 第一次调用"
        "的失败只能由写入阶段的 release 语义字段校验归因，不得由指针/"
        f"payload 哈希/映射结构归因（实际 "
        f"{bad_semantics_precheck_report.status!r}，"
        f"reasons={bad_semantics_precheck_report.reasons!r}）"
    )

    stripped_baseline = _snapshot_tree(tmp_path)
    r2_release_dir = tmp_path / "data" / "releases" / CONFIRMED_DATA_TARGET_R2

    # ---- 行为 1：第一次调用经 DataMigrationBlocked fail-closed 拒绝。----
    first_call_error: BaseException | None = None
    try:
        migrate_data(tmp_path, mapping_items)
    except Exception as exc:
        first_call_error = exc
    assert isinstance(first_call_error, blocked_exc), (
        "r1 legacy manifest release 语义字段非法（counts 缺 splits 声明）"
        "的双对象批第一次调用必须经 DataMigrationBlocked fail-closed 拒"
        "绝（T15 既有写入侧 release 语义字段校验语义；r2 批内先完成、"
        f"r1 在写入阶段被拒）：实际 {first_call_error!r}"
    )

    # ---- fixture 前置事实：批内部分完成（r2 先完成，T19 既有形态）。----
    r2_meta_after_rejection = load_release_metadata(
        tmp_path / "data", CONFIRMED_DATA_TARGET_R2
    )
    assert r2_meta_after_rejection.status is DataStatus.ACTIVE, (
        "fixture 前置事实失败：拒绝发生时批内先完成的 r2 必须经既有语义"
        "读回为 active 正式对象（批内部分完成状态的已完成侧前提）"
    )
    try:
        assert_payload_sealed(r2_release_dir)
    except Exception as exc:
        raise AssertionError(
            "fixture 前置事实失败：批内先完成的 r2 封存事实必须保持（既有"
            f"只读门 assert_payload_sealed 通过）：{exc!r}"
        ) from exc
    r2_receipt_file = (
        tmp_path / "migration_receipts" / f"{CONFIRMED_DATA_TARGET_R2}.receipt.yaml"
    )
    assert r2_receipt_file.is_file(), (
        "fixture 前置事实失败：批内先完成的 r2 committed receipt 必须已写入"
    )
    r2_receipt_bytes_before_rerun = r2_receipt_file.read_bytes()
    r2_completed_receipt = yaml.safe_load(
        r2_receipt_bytes_before_rerun.decode("utf-8")
    )
    assert isinstance(r2_completed_receipt, dict), (
        "fixture 前置事实失败：r2 receipt 必须是 YAML 顶层映射"
    )
    assert set(r2_completed_receipt) == set(_RECEIPT_FIELDS), (
        "fixture 前置事实失败：r2 receipt 键集必须恰为八字段契约：实际 "
        f"{sorted(r2_completed_receipt)}"
    )
    assert r2_completed_receipt["status"] == "committed", (
        "fixture 前置事实失败：r2 receipt 必须为 committed"
    )
    r2_release_content_before_rerun = _release_content_files(r2_release_dir)
    r2_completed_side_mtime = _snapshot_r2_completed_side_mtime_ns(tmp_path)

    # ---- 行为 2（RED 核心）：非法 release 语义字段的拒绝零写入 —— 不
    #      得创建目标目录，也不得留下 in-progress receipt。----
    _assert_rejected_object_zero_writes(
        tmp_path,
        failing_source_id=CONFIRMED_DATA_SOURCE_R1,
        failing_identity=CONFIRMED_DATA_TARGET_R1,
        completed_identity=CONFIRMED_DATA_TARGET_R2,
        rejection_context="非法 release 语义字段（缺 counts.splits）的 fail-closed 拒绝",
        snapshot_before_first_call=stripped_baseline,
    )
    assert mapping_items == _confirmed_data_mapping_items(), (
        "全程不得就地改写传入映射项（M0 事实分级保持不变）"
    )

    # ---- 行为 3：恢复 manifest 原字节（修正输入）后的重跑不被 stale
    #      credential 阻塞 + 双对象终态完整。----
    r1_manifest_file = _manifest_file_of(tmp_path, CONFIRMED_DATA_SOURCE_R1)
    r1_manifest_file.write_bytes(r1_manifest_bytes_original)
    assert r1_manifest_file.read_bytes() == r1_manifest_bytes_original, (
        "fixture 前置事实失败：恢复后的 r1 manifest 必须与改坏前原字节逐"
        "字节一致（单一变量修正：仅恢复 counts.splits 声明）"
    )
    _rerun_after_input_fix_and_assert_dual_batch_final_state(
        tmp_path,
        fixed_mapping_items=mapping_items,
        r1_manifest_bytes=r1_manifest_bytes_original,
        r1_manifest_declared=r1_manifest_declared_original,
        r2_receipt_bytes_before_rerun=r2_receipt_bytes_before_rerun,
        r2_release_content_before_rerun=r2_release_content_before_rerun,
        r2_completed_side_mtime_ns=r2_completed_side_mtime,
        fixture_baseline_snapshot=pristine_baseline,
        fix_context="恢复 r1 manifest counts.splits 声明",
    )


# ---------------------------------------------------------------------------
# H1：history-summary —— 单条已确认历史 Prompt entry 的最小正向纯构建
# ---------------------------------------------------------------------------

# 第三个真实 registry 条目（M0 source-inventory pipeline_prompt_registry：
# v4.1-fixed-full-fields-initial-v1，历史 Prompt，仅 registry 存在）。H1
# fixture 把它与 v4.1-concise-evidence-json-v1（已确认历史源）、
# v4.1-concise-evidence-json-v2（当前活动 Prompt）共同写入，镜像真实
# legacy prompt registry 的完整三条目布局；后两者在本切片中是未声明
# sibling（H1 只声明 v1 一条 entry）。
_THIRD_REGISTRY_SOURCE_ID = "v4.1-fixed-full-fields-initial-v1"

# 真实 legacy registry manifest 的逐源 publishing_code_commit 与
# generated_at（M0 source-inventory manifest_facts / 真实 manifest.json
# 声明值，verified_local）。fixture 其余字段值合成，但这两个字段取真实
# 声明值以保持证据结构可追溯。
_REGISTRY_PUBLISHING_COMMITS: dict[str, str] = {
    HISTORY_SIBLING_SOURCE_ID: "4c56f7c958b830e43e301739aa4d71b2eb1c1f99",
    CONFIRMED_PROMPT_SOURCE_ID: "98f0476d50138a7577e65426338a44a1baaec040",
    _THIRD_REGISTRY_SOURCE_ID: "4999ae0191c1473642163ed421649b29805beddf",
}
_REGISTRY_GENERATED_AT: dict[str, str] = {
    HISTORY_SIBLING_SOURCE_ID: "2026-07-28T21:41:33+08:00",
    CONFIRMED_PROMPT_SOURCE_ID: "2026-07-28T21:44:58+08:00",
    _THIRD_REGISTRY_SOURCE_ID: "2026-07-28T15:11:41+08:00",
}


def _write_full_history_prompt_registry(root: Path) -> bytes:
    """H1 fixture：镜像真实 legacy prompt registry 的完整三条目布局。

    三个真实条目全部写入 ``pipeline/prompt_registry/<source_id>/
    {manifest.json,prompt.yaml}``（M0 source-inventory
    pipeline_prompt_registry 布局）。manifest.json 逐字段镜像真实
    manifest 的字段集与生成 recipe
    （pipeline/prompt_control/core.py::_manifest_payload，测试独立镜像
    自算、不 import legacy production）：哈希字段按真实 recipe 从合成
    prompt.yaml 复算（prompt_content_sha256 权威六字段 payload recipe；
    prompt_yaml_sha256 / source_sha256 文件字节 recipe 且镜像真实事实
    source_sha256 == prompt_yaml_sha256；system_prompt_sha256 /
    user_prompt_sha256 字符串 UTF-8 字节；fields_and_labels_sha256
    output_fields+label_pools canonical JSON），publishing_code_commit /
    generated_at 取真实 manifest 声明值，其余标识字段取合成
    prompt.yaml 声明值 —— 源内自洽。三条目 prompt.yaml 内容逐源不同
    （system_prompt 内嵌源标记），使"扫全 registry / 取错 sibling"
    的实现无法通过 H1 的事实值断言。

    返回已确认历史源（v4.1-concise-evidence-json-v1）prompt.yaml 的
    字节。
    """
    registry = root / "pipeline" / "prompt_registry"
    for source_id in (
        HISTORY_SIBLING_SOURCE_ID,
        CONFIRMED_PROMPT_SOURCE_ID,
        _THIRD_REGISTRY_SOURCE_ID,
    ):
        entry_dir = registry / source_id
        entry_dir.mkdir(parents=True, exist_ok=True)
        prompt_bytes = _legacy_prompt_yaml_full(source_id)
        (entry_dir / "prompt.yaml").write_bytes(prompt_bytes)
        prompt = yaml.safe_load(prompt_bytes)
        fields_and_labels_payload = {
            "output_fields": prompt["output_fields"],
            "label_pools": prompt["label_pools"],
        }
        manifest = {
            "schema_version": "tensile-prompt-registry-manifest/v1",
            "prompt_schema_version": prompt["schema_version"],
            "protocol_id": prompt["protocol_id"],
            "revision_id": prompt["revision_id"],
            "prompt_content_sha256": _prompt_content_sha256_of_yaml(prompt_bytes),
            "prompt_yaml_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "source_path": "pipeline/prompt_control/active_prompt.yaml",
            "source_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "system_prompt_sha256": hashlib.sha256(
                prompt["system_prompt"].encode("utf-8")
            ).hexdigest(),
            "user_prompt_sha256": hashlib.sha256(
                prompt["user_prompt"].encode("utf-8")
            ).hexdigest(),
            "fields_and_labels_sha256": hashlib.sha256(
                json.dumps(
                    fields_and_labels_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
            "publishing_code_commit": _REGISTRY_PUBLISHING_COMMITS[source_id],
            "generated_at": _REGISTRY_GENERATED_AT[source_id],
            "immutable": True,
        }
        (entry_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    return (registry / HISTORY_SIBLING_SOURCE_ID / "prompt.yaml").read_bytes()


def _confirmed_prompt_history_entry() -> dict[str, Any]:
    """逐字段镜像 M0 证据结构的已确认 prompt_history entry（H1 输入）。

    结构对齐 M0 object-mapping.yaml 的历史整理口径
    （model_train_eval_history.entries 的 source_id / verified /
    history_only / status / confirmed_by_user_date / notes 字段族）与
    prompt registry 历史条目语境：kind 为 H1 契约的 ``prompt_history``，
    source_legacy_id 指向真实历史源 ``v4.1-concise-evidence-json-v1``
    （M0 registry_versions_not_migrating：用户确认仅进 history-summary，
    不迁移为新的正式 Prompt 身份），status 为 ``user_confirmed``
    （M0 status_field_legend 唯一"用户已逐项确认"口径；由入口自身读
    取该字段消费，调用方不预过滤成布尔标志，后续 pending/未确认的反
    向切片才能绑定同一入口）。entry 不携带 candidate_target_identity
    —— 历史 entry 不分配正式目标身份，与 prompt_mapping.items 的已
    确认迁移条目结构性区分。
    """
    return {
        "kind": "prompt_history",
        "source_legacy_id": HISTORY_SIBLING_SOURCE_ID,
        "role": "历史 Prompt（registry 存在，非活动；仅进 history-summary）",
        "source_verified": "verified_local",
        "history_only": True,
        "status": "user_confirmed",
        "confirmed_by_user_date": "2026-09-07",
        "notes": (
            "M0 registry_versions_not_migrating：该历史 Prompt 仅进 "
            "history-summary，不迁移为新的正式 Prompt 身份；历史引用不能"
            "替换为当前 Prompt。"
        ),
    }


def _resolve_history_summary_entry() -> Any:
    """惰性解析 H1 history-summary 纯构建入口；模块或入口缺失返回 None。

    RED Gate 设计（与 _resolve_precheck_entry 同口径）：不让原始
    import 错误或 AttributeError 成为 RED，由调用方以显式行为断言
    钉出"history-summary 纯构建行为缺失"。
    """
    spec = importlib.util.find_spec("versioning.migration")
    if spec is None:
        return None
    module = importlib.import_module("versioning.migration")
    return getattr(module, "build_history_summary", None)


def _document_string_fragments(value: Any) -> list[str]:
    """递归收集文档内全部字符串片段（mapping 键、序列元素、标量）。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        fragments: list[str] = []
        for key, item in value.items():
            fragments.extend(_document_string_fragments(key))
            fragments.extend(_document_string_fragments(item))
        return fragments
    if isinstance(value, (list, tuple)):
        item_fragments: list[str] = []
        for item in value:
            item_fragments.extend(_document_string_fragments(item))
        return item_fragments
    if value is None:
        return []
    return [str(value)]


def test_confirmed_prompt_history_entry_builds_history_summary_document_without_writes(
    tmp_path: Path,
) -> None:
    r"""单条已确认历史 Prompt entry 的最小正向纯构建（H1，M1b history-summary
    第一个 current behavior，先写测试，不改 production）。

    H1 behavior —— 对已确认历史 Prompt entry（kind ``prompt_history``、
    source_legacy_id ``v4.1-concise-evidence-json-v1``、status
    ``user_confirmed``，M0 registry_versions_not_migrating 用户确认仅进
    history-summary）调用 ``build_history_summary(root, entries)`` 应：
    1. 返回 history-summary 文档（mapping）：
       ``history_summary_schema`` == ``tensile-migration/history-summary/v1``，
       ``entries`` 为 list 且恰含声明的一条；
    2. 保留 ``original_id``（v4.1-concise-evidence-json-v1，原始
       legacy ID）；
    3. 标记 ``history_only: true`` 与 ``formal_identity: "none"``；
    4. 从该 entry 的 legacy manifest/prompt 源提取事实（facts：六个必
       需事实 protocol_id / prompt_content_sha256 /
       publishing_code_commit / system_prompt / user_prompt /
       output_fields，已知值形态 ``{value, source}``，source 为非空
       mapping 的字段级来源 provenance），事实 value 必须与 legacy 源
       声明值逐值相等（不重算、不伪造、不取 sibling）；manifest-only
       事实的 source 必须指回声明源的 manifest.json、prompt.yaml-only
       事实的 source 必须指回声明源的 prompt.yaml（protocol_id 两源均
       有，允许任一，但须指回声明源条目目录）；
    5. 纯构建零写入（全树快照逐字节不变）；
    6. legacy 源不变（同 5）；
    7. 不扫描目录生成未声明条目：fixture 镜像真实 legacy prompt
       registry 完整三条目（v1 已确认历史源 + v2 /
       fixed-full-fields-initial-v1 两个未声明 sibling，prompt.yaml
       逐源内容不同），文档恰含一条 entry，未声明 sibling 的 ID 不得
       出现在文档任何字符串中；
    8. 不分配任何新正式身份：entry_id 为文档内 slug（非空字符串）
       且不是 ``<kind>-v<协议>-r<N>`` 正式身份，文档内任何字符串值都
       不是正式身份，不创建 records/ 条目；
    9. 不写 history-summary 文件（同 5：不落盘
       docs/results/.../history-summary.yaml、migration_receipts/
       或任何其他目标条目，文档只经返回值给出）。

    unknown / 缺失资料形态、pending/未确认 entry 的 blocked 反向、多
    entry 批量与混合完整/缺失资料、history-summary 文件写入、CLI 均
    不在本切片。

    fixture：_write_full_history_prompt_registry 镜像真实 legacy
    prompt registry（三个真实条目，manifest.json 逐字段镜像真实
    manifest 字段集与生成 recipe、哈希独立复算保持源内自洽，
    publishing_code_commit / generated_at 取真实声明值）；entry 输入
    _confirmed_prompt_history_entry 逐字段镜像 M0 证据结构（status 由
    入口自身读取消费，调用方不预过滤）。

    RED Gate 设计说明（H1）：migration 模块已存在而 build_history_summary
    入口缺失时，仍由测试内惰性解析 + 显式 AssertionError 钉出
    "history-summary 纯构建行为缺失"，不让原始 import 错误或
    AttributeError 成为 RED；fixture 构建、前置事实断言与全树快照真实
    执行之后才失败，映射到当前 behavior 未实现。

    捕获的合理但错误实现：
    - 构建时写盘（history-summary 文件、records/、staging、任何目标
      条目）-> 全树快照对比失败；
    - 改写/规范化 legacy 源 -> 全树快照对比失败；
    - 扫描整个 legacy registry 生成 sibling 条目 -> entries 数量 /
      未声明 sibling ID 断言失败；
    - 取错 sibling（扫目录取首个/活动源）-> 事实值断言失败（逐源内容
      不同）；
    - 给历史 entry 分配正式身份（entry_id 或文档内任何字符串为
      ``<kind>-v<协议>-r<N>``、formal_identity 不是 "none"）-> 正式身
      份断言失败；
    - 伪造/重算事实值（不取 manifest/prompt.yaml 声明值）-> 事实值
      断言失败；
    - 事实不携带来源或 source 为空/不可指回声明源文件 -> provenance
      断言失败；
    - 不接受 M0 证据结构的 entry（期望别的输入形状）-> 调用即失败；
    - 对合法已确认输入 fail-closed（抛错或返回非法文档）-> 文档断言
      失败；
    - 就地改写传入 entry -> 输入不变断言失败。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（本切片仅新增
      用例与配套 helper、常量及模块 docstring 清单条目，不改
      production）。
    - 命令（新 selector）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_confirmed_prompt_history_entry_builds_history_summary_document_without_writes``
    - 既有 selector 复跑（回归钉）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_confirmed_prompt_mapping_precheck_returns_ready_without_writes``
      （通过）；全 migration 文件：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py``（RED 时点：80 passed + 1
      failed，失败恰为本 selector）。
    - RED failure signature：恰一个失败用例（本 selector），失败信息
      为 AssertionError "history-summary 纯构建行为缺失：
      versioning.migration 未提供 build_history_summary 入口（当前
      behavior 未实现）"；fixture 前置事实（三 registry 条目存在、未
      声明 sibling 内容逐源不同、目标根不存在）全部不失败；不出现
      ModuleNotFoundError / ImportError / AttributeError。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （``[tool.pytest.ini_options] testpaths / pythonpath`` 解析依赖该
      文件）。
    """
    declared_bytes = _write_full_history_prompt_registry(tmp_path)
    declared_entry_dir = (
        tmp_path / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    )

    # ---- fixture 前置事实（对齐 M0 证据）：三条目齐全、声明源与
    #      未声明 sibling 内容逐源不同、目标根不存在。----
    assert (declared_entry_dir / "prompt.yaml").read_bytes() == declared_bytes, (
        "fixture 前置事实失败：已确认历史源 prompt.yaml 必须可逐字节读回"
    )
    assert (declared_entry_dir / "manifest.json").is_file(), (
        "fixture 前置事实失败：已确认历史源 manifest.json 必须存在"
    )
    for sibling_id in (CONFIRMED_PROMPT_SOURCE_ID, _THIRD_REGISTRY_SOURCE_ID):
        sibling_dir = tmp_path / "pipeline" / "prompt_registry" / sibling_id
        assert (sibling_dir / "manifest.json").is_file() and (
            sibling_dir / "prompt.yaml"
        ).is_file(), (
            f"fixture 前置事实失败：未声明 sibling {sibling_id} 必须以完整"
            " registry 条目存在（钉死目录扫描）"
        )
        assert (
            sibling_dir / "prompt.yaml"
        ).read_bytes() != declared_bytes, (
            f"fixture 前置事实失败：未声明 sibling {sibling_id} 的 "
            "prompt.yaml 内容必须与声明源逐源不同（钉死取错源）"
        )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    before = _snapshot_tree(tmp_path)
    entry = _confirmed_prompt_history_entry()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    document = build(tmp_path, [entry])

    # ---- 行为 1：返回 history-summary 文档（schema + 恰一条 entry）。----
    assert isinstance(document, Mapping), (
        "build_history_summary 必须返回 history-summary 文档（mapping）："
        f"实际 {type(document).__name__!r}"
    )
    assert (
        document.get("history_summary_schema")
        == "tensile-migration/history-summary/v1"
    ), (
        "history-summary 文档必须声明 history_summary_schema == "
        "'tensile-migration/history-summary/v1'：实际 "
        f"{document.get('history_summary_schema')!r}"
    )
    document_entries = document.get("entries")
    assert isinstance(document_entries, list), (
        "history-summary 文档的 entries 必须是 list：实际 "
        f"{type(document_entries).__name__!r}"
    )
    assert len(document_entries) == 1, (
        "history-summary 文档必须恰含声明的一条 entry（不得扫描 legacy "
        f"目录生成未声明条目）：实际 {len(document_entries)} 条"
    )
    summary_entry = document_entries[0]
    assert isinstance(summary_entry, Mapping), (
        "history-summary entry 必须是 mapping：实际 "
        f"{type(summary_entry).__name__!r}"
    )

    # ---- 行为 2：保留 original_id；entry kind 保持声明。----
    assert summary_entry.get("original_id") == HISTORY_SIBLING_SOURCE_ID, (
        "history-summary entry 必须保留 original_id（原始 legacy ID）："
        f"实际 {summary_entry.get('original_id')!r}"
    )
    assert summary_entry.get("kind") == "prompt_history", (
        "history-summary entry 必须保持声明的 kind（prompt_history）："
        f"实际 {summary_entry.get('kind')!r}"
    )

    # ---- 行为 3：history_only / formal_identity。----
    assert summary_entry.get("history_only") is True, (
        "history-summary entry 必须标记 history_only: true：实际 "
        f"{summary_entry.get('history_only')!r}"
    )
    assert summary_entry.get("formal_identity") == "none", (
        "history-summary entry 必须标记 formal_identity: none（不分配新"
        f"正式身份）：实际 {summary_entry.get('formal_identity')!r}"
    )

    # ---- 行为 8a：entry_id 是文档内 slug，不是正式身份。----
    entry_id = summary_entry.get("entry_id")
    assert isinstance(entry_id, str) and entry_id, (
        "history-summary entry 必须携带非空字符串 entry_id（文档内 "
        f"slug）：实际 {entry_id!r}"
    )
    assert not is_valid_version_id(entry_id), (
        "entry_id 必须是文档内 slug，不得是 <kind>-v<协议>-r<N> 正式身份"
        f"（不得为历史 entry 分配新正式身份）：实际 {entry_id!r}"
    )

    # ---- 行为 4：facts 从声明源的 legacy manifest/prompt 提取，已知
    #      值形态 {value, source{...}}，携带字段级来源 provenance。----
    facts = summary_entry.get("facts")
    assert isinstance(facts, Mapping) and facts, (
        "history-summary entry 必须携带非空 facts（从 legacy 源提取的"
        f"事实）：实际 {facts!r}"
    )
    declared_manifest = json.loads(
        (declared_entry_dir / "manifest.json").read_text(encoding="utf-8")
    )
    declared_prompt = yaml.safe_load(declared_bytes)
    expected_fact_values = {
        "protocol_id": declared_manifest["protocol_id"],
        "prompt_content_sha256": declared_manifest["prompt_content_sha256"],
        "publishing_code_commit": declared_manifest["publishing_code_commit"],
        "system_prompt": declared_prompt["system_prompt"],
        "user_prompt": declared_prompt["user_prompt"],
        "output_fields": declared_prompt["output_fields"],
    }
    for name, expected_value in expected_fact_values.items():
        assert name in facts, (
            f"facts 必须包含从 legacy 源提取的必需事实 {name}：实际键集 "
            f"{sorted(facts)}"
        )
        fact = facts[name]
        assert isinstance(fact, Mapping), (
            f"已知事实 {name} 必须为 {{value, source}} 形态的 mapping："
            f"实际 {type(fact).__name__!r}"
        )
        assert set(fact) == {"value", "source"}, (
            f"已知事实 {name} 的键集必须恰为 {{value, source}}：实际 "
            f"{sorted(fact)}"
        )
        assert fact["value"] == expected_value, (
            f"已知事实 {name} 的 value 必须与 legacy 源声明值逐值相等"
            f"（不重算、不伪造、不取 sibling）：实际 {fact['value']!r}，"
            f"期望 {expected_value!r}"
        )
        source = fact["source"]
        assert isinstance(source, Mapping) and source, (
            f"已知事实 {name} 必须携带非空 mapping 形态的字段级来源 "
            f"provenance（source）：实际 {source!r}"
        )

    # provenance 必须可指回声明源的 legacy 文件：manifest-only 事实 ->
    # manifest.json；prompt.yaml-only 事实 -> prompt.yaml；protocol_id
    # 两源均有 -> 允许任一，但须指回声明源条目目录。
    legacy_entry_rel_dir = f"pipeline/prompt_registry/{HISTORY_SIBLING_SOURCE_ID}"
    manifest_only_facts = ("prompt_content_sha256", "publishing_code_commit")
    prompt_only_facts = ("system_prompt", "user_prompt", "output_fields")
    for name in manifest_only_facts:
        source_text = " ".join(_document_string_fragments(facts[name]["source"]))
        assert legacy_entry_rel_dir in source_text, (
            f"manifest-only 事实 {name} 的来源 provenance 必须指回声明源"
            f"条目（{legacy_entry_rel_dir}）：实际 {source_text!r}"
        )
        assert "manifest.json" in source_text, (
            f"manifest-only 事实 {name} 的来源 provenance 必须指回声明源"
            f"的 manifest.json：实际 {source_text!r}"
        )
    for name in prompt_only_facts:
        source_text = " ".join(_document_string_fragments(facts[name]["source"]))
        assert legacy_entry_rel_dir in source_text, (
            f"prompt.yaml-only 事实 {name} 的来源 provenance 必须指回声明"
            f"源条目（{legacy_entry_rel_dir}）：实际 {source_text!r}"
        )
        assert "prompt.yaml" in source_text, (
            f"prompt.yaml-only 事实 {name} 的来源 provenance 必须指回声明"
            f"源的 prompt.yaml：实际 {source_text!r}"
        )
    protocol_source_text = " ".join(
        _document_string_fragments(facts["protocol_id"]["source"])
    )
    assert legacy_entry_rel_dir in protocol_source_text, (
        "protocol_id 事实的来源 provenance 必须指回声明源条目"
        f"（{legacy_entry_rel_dir}，manifest.json 与 prompt.yaml 均可）："
        f"实际 {protocol_source_text!r}"
    )

    # ---- 行为 7：不扫描目录生成未声明条目（sibling ID 不得进入文档）。----
    all_strings = _document_string_fragments(document)
    for sibling_id in (CONFIRMED_PROMPT_SOURCE_ID, _THIRD_REGISTRY_SOURCE_ID):
        assert not any(sibling_id in fragment for fragment in all_strings), (
            f"未声明 sibling {sibling_id} 不得进入 history-summary 文档的"
            "任何字符串（实现必须按声明 entry 定位源，不得扫描 legacy 目"
            "录生成未声明条目）"
        )

    # ---- 行为 8b：不分配任何新正式身份（文档内任何字符串都不是正式
    #      身份）。----
    for fragment in all_strings:
        assert not is_valid_version_id(fragment), (
            "history-summary 文档内不得出现任何 <kind>-v<协议>-r<N> 正式"
            f"身份（历史 entry 不分配新正式身份）：实际出现 {fragment!r}"
        )

    # ---- 行为 5/6/9：纯构建零写入 —— 全树逐字节不变（legacy 源不变、
    #      不写 history-summary 文件、不创建任何目标条目）。----
    assert _snapshot_tree(tmp_path) == before, (
        "build_history_summary 必须纯构建零写入：全树快照逐字节不变"
        "（不写 history-summary 文件、不创建 records/ 或任何目标条目、"
        "不改 legacy 源）"
    )
    assert not (tmp_path / "records").exists(), (
        "纯构建不得创建 records/ 或任何正式对象条目（不分配新正式身份）"
    )
    assert not (tmp_path / "docs").exists(), (
        "纯构建不得写入 history-summary 文件（本切片只经返回值给出文档）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"纯构建不得落盘任何 history-summary 命名文件：发现 {path}"
        )

    # ---- 不就地修改传入 entry。----
    assert entry == _confirmed_prompt_history_entry(), (
        "全程不得就地改写传入 entry（H1 输入事实保持不变）"
    )


# ---------------------------------------------------------------------------
# H2/H3：history-summary —— 非法输入 fail-closed 反向最小切片（先写测试，
# 不改 production）
# ---------------------------------------------------------------------------

# H2/H3 拒绝通道可接受的明确域错误类型名（versioning.migration 内）。
# build_history_summary 是 H1 已绑定的纯构建入口（文档只经返回值给出），
# 非法输入的拒绝经 H1 已文档化的 PromptMigrationBlocked 域错误通道给出；
# DataMigrationBlocked 与 versioning.prompts.PromptError 亦为 versioning
# 域内明确域错误，一并接受（后续切片新增专用拒绝类型时由
# _is_history_summary_domain_error 的模块/命名口径兜底接受）。
_HISTORY_DOMAIN_ERROR_NAMES = ("PromptMigrationBlocked", "DataMigrationBlocked")


def _is_history_summary_domain_error(exc: BaseException) -> bool:
    """判定异常是否为 versioning 域内明确域错误（拒绝通道合规性）。

    接受两类通道：
    - versioning.migration 内已定义的迁移域错误类型
      （PromptMigrationBlocked / DataMigrationBlocked）或
      versioning.prompts 的 PromptError 族（含 PromptMigrationBlocked
      的既有基类）；
    - 后续切片在 versioning 域内新增的专用拒绝类型（类型名含
      ``Blocked`` 或以 ``Error`` 结尾，且定义于 ``versioning.*`` 模块）。

    builtins / os 等处的未类型化异常（TypeError、ValueError、KeyError、
    AttributeError、OSError、RuntimeError 等直接穿透）一律不是合规
    拒绝通道。
    """
    spec = importlib.util.find_spec("versioning.migration")
    if spec is not None:
        migration = importlib.import_module("versioning.migration")
        for name in _HISTORY_DOMAIN_ERROR_NAMES:
            domain_type = getattr(migration, name, None)
            if isinstance(domain_type, type) and isinstance(exc, domain_type):
                return True
    if isinstance(exc, PromptError):
        return True
    exc_type = type(exc)
    return exc_type.__module__.startswith("versioning.") and (
        "Blocked" in exc_type.__name__ or exc_type.__name__.endswith("Error")
    )


def _expect_history_summary_fail_closed(
    build: Any, root: Path, entries: Any
) -> str:
    """调用 build_history_summary 并断言非法输入 fail-closed，返回非空拒因。

    拒绝必须经明确域错误或 blocked 报告通道给出：
    - 抛出异常：异常必须是 versioning 域内明确域错误
      （_is_history_summary_domain_error），不得是未类型化异常直接穿透
      —— 未类型化异常经 AssertionError + cause 链转译判失败；异常消息
      必须非空（可读拒因，不得静默拒绝）；
    - 返回值：必须是携带 status == "blocked" 且非空 reasons 的 blocked
      报告（mapping 或带 status / reasons 属性的报告对象均可）。

    返回 history-summary 文档（含 entries 为空的文档）即未拒绝：
    断言失败 —— 不得对非法输入静默构建文档，也不得静默返回空文档。
    """
    try:
        result = build(root, entries)
    except Exception as exc:
        if not _is_history_summary_domain_error(exc):
            raise AssertionError(
                "非法 history 输入的拒绝必须经明确域错误（PromptMigrationBlocked "
                "等 versioning 域错误）或 blocked 报告通道给出，不得抛未"
                f"类型化异常直接穿透：实际 {type(exc).__module__}."
                f"{type(exc).__name__}: {exc}"
            ) from exc
        assert str(exc).strip(), (
            "fail-closed 拒绝必须携带非空拒因（明确域错误消息非空），"
            "不得静默拒绝"
        )
        return str(exc)
    if isinstance(result, Mapping) and "history_summary_schema" in result:
        entry_count = len(result.get("entries") or [])
        raise AssertionError(
            "非法 history 输入必须 fail-closed 拒绝，不得静默构建 "
            "history-summary 文档（含 entries 为空的文档）：实际返回 "
            f"schema={result.get('history_summary_schema')!r}、"
            f"entries={entry_count} 条的文档"
        )
    if isinstance(result, Mapping):
        status = result.get("status")
        reasons = result.get("reasons")
    else:
        status = getattr(result, "status", None)
        reasons = getattr(result, "reasons", None)
    assert status == "blocked", (
        "非法 history 输入必须 fail-closed：抛明确域错误或返回 "
        f"status == 'blocked' 的报告；实际返回 {type(result).__name__!r}，"
        f"status={status!r}"
    )
    reason_items = [str(reason) for reason in reasons] if reasons else []
    assert reason_items, (
        "blocked 报告必须携带非空 reasons（可读拒因）：fail-closed 拒绝"
        "不得静默"
    )
    return "；".join(reason_items)


def _history_entry_with_violation(violation: str) -> dict[str, Any]:
    """按 violation 构造携带非法字段的 history entry（H2/H3 输入）。

    基于 H1 已确认 entry（_confirmed_prompt_history_entry：status
    user_confirmed、不携带 candidate_target_identity / passed）单变量
    扰动：除 violation 指定字段外其余字段保持合法取值，使拒绝只能由
    该非法字段引起（隔离变量，legacy 源始终齐全）。组合参数
    （pending+candidate、passed+candidate）钉定各门相互独立，不得只检
    查其一而漏过另一类夹带。
    """
    entry = _confirmed_prompt_history_entry()
    if violation == "status_pending_user_check":
        entry["status"] = "pending_user_check"
    elif violation == "status_unknown":
        entry["status"] = "unknown"
    elif violation == "status_not_verified":
        entry["status"] = "not_verified"
    elif violation == "status_verified_local_fact_grading":
        entry["status"] = "verified_local"
    elif violation == "status_missing":
        del entry["status"]
    elif violation == "candidate_prompt_identity":
        entry["candidate_target_identity"] = CONFIRMED_PROMPT_TARGET_ID
    elif violation == "candidate_model_identity":
        entry["candidate_target_identity"] = "model-v4.1-r1"
    elif violation == "passed_true":
        entry["passed"] = True
    elif violation == "pending_status_plus_candidate_identity":
        entry["status"] = "pending_user_check"
        entry["candidate_target_identity"] = CONFIRMED_PROMPT_TARGET_ID
    elif violation == "passed_true_plus_candidate_identity":
        entry["passed"] = True
        entry["candidate_target_identity"] = "model-v4.1-r1"
    else:
        raise AssertionError(f"未知 violation {violation!r}")
    return entry


def _assert_legal_history_entry_still_builds(build: Any, root: Path) -> None:
    """合法对照（H2/H3 反向门不得反向过宽）：已确认 entry 仍正常构建。

    完整 H1 正向契约由既有 H1 selector 复跑钉定；此处只做每参数内的
    轻量对照，证明 fixture 与入口通道可用，非法输入的拒绝只能由该
    非法字段 / 非法 entries 形态引起，且反向门不得误伤合法已确认
    entry（对一切输入一律拒绝不是合规 fail-closed）。
    """
    legal_document = build(root, [_confirmed_prompt_history_entry()])
    legal_entries = (
        legal_document.get("entries") if isinstance(legal_document, Mapping) else None
    )
    assert isinstance(legal_entries, list) and len(legal_entries) == 1, (
        "反向门不得反向过宽：合法已确认 prompt_history entry 必须仍正常"
        "构建恰含一条 entry 的 history-summary 文档（H1 正向行为不回归）；"
        f"实际 {type(legal_document).__name__} / entries={legal_entries!r}"
    )


@pytest.mark.parametrize(
    "violation",
    [
        pytest.param("status_pending_user_check", id="status_pending_user_check"),
        pytest.param("status_unknown", id="status_unknown"),
        pytest.param("status_not_verified", id="status_not_verified"),
        pytest.param(
            "status_verified_local_fact_grading",
            id="status_verified_local_mistaken_as_confirmation",
        ),
        pytest.param("status_missing", id="status_field_missing"),
        pytest.param("candidate_prompt_identity", id="candidate_prompt_identity"),
        pytest.param("candidate_model_identity", id="candidate_model_identity"),
        pytest.param("passed_true", id="passed_true_declaration"),
        pytest.param(
            "pending_status_plus_candidate_identity",
            id="pending_status_plus_candidate_identity",
        ),
        pytest.param(
            "passed_true_plus_candidate_identity",
            id="passed_true_plus_candidate_identity",
        ),
    ],
)
def test_history_summary_rejects_unconfirmed_or_smuggled_entries_fail_closed(
    tmp_path: Path, violation: str
) -> None:
    r"""未确认 / 夹带候选正式身份 / 声明 passed 的 history entry 必须被
    fail-closed 拒绝：明确域错误 + 非空拒因 + 零写入 + 输入不变
    （H2/H3，M1b history-summary 非法输入反向最小切片，先写测试，不
    改 production）。

    H2/H3 behavior —— 对携带非法字段的 history entry（fixture 与 H1 同
    一套：_write_full_history_prompt_registry 完整三条目 legacy
    registry，声明源 v4.1-concise-evidence-json-v1 始终齐全）调用
    ``build_history_summary(root, [entry])`` 必须：
    1. fail-closed 拒绝（H2 三类 entry 级非法输入）：
       - entry ``status`` 不是 ``user_confirmed``：pending_user_check
         （M0 status_field_legend“未生效，禁止写入”）、unknown（已知
         缺失）、not_verified（完整性/存在性未确认）、verified_local
         （source_verified 的事实分级，不是确认门槛）、status 字段缺
         失 —— 白名单式只认 user_confirmed，不得黑名单式只拒已知
         pending 值；
       - entry 夹带候选正式身份 ``candidate_target_identity``：历史
         entry 是 history_only（M0 registry_versions_not_migrating /
         model_train_eval_history：仅进 history-summary，不分配任何
         新正式身份），夹带 prompt-v4.1-r1（Prompt 迁移目标身份）或
         model-v4.1-r1（五族完整身份）即试图把 history entry 伪装成
         迁移条目 / 伪造身份 —— 必须拒绝（即使 status 保持
         user_confirmed）；
       - entry 声明 ``passed: true``：M0 model_train_eval_history
         scope_note“不得把历史 summary 转成 passed”、
         global_pre_write_checks“禁止写入或标记 verified/passed” ——
         entry 不得自我声明通过状态（即使 status 保持
         user_confirmed）；
       - 组合参数（pending + candidate / passed + candidate）钉定各门
         相互独立：不得只检查 status 而放行夹带身份，也不得只查身份
         键而放行 passed 声明；
    2. 拒绝经明确域错误（PromptMigrationBlocked 等 versioning 域错
       误）或 blocked 报告通道给出，携带非空拒因，不得抛未类型化异常
       （TypeError / ValueError / KeyError / AttributeError / OSError
       等直接穿透不是合规拒绝）；
    3. 不得静默构建文档：返回 history-summary 文档（含声明源事实的
       entry）即未拒绝，判失败 —— 不得为未确认 / 夹带身份 / 声明
       passed 的 entry 构建 history-summary 条目；
    4. 零写入：全树逐字节不变（legacy 源不变、不写 history-summary 文
       件、不创建 records/ 或任何目标条目）；
    5. 不就地修改传入 entry。

    fixture 隔离：entry 的 source_legacy_id 指向的 legacy 源
    manifest.json / prompt.yaml 始终存在且事实齐全（H1 fixture 前置事
    实），使拒绝只能由非法 entry 字段引起，不得由源缺失混入；合法对
    照（同 fixture 下 H1 已确认 entry）仍正常构建 —— 反向门不得反向
    过宽（对一切输入一律拒绝不是合规 fail-closed），H1 完整正向契约
    由既有 H1 selector 复跑钉定。

    RED Gate 设计（H2/H3）：build_history_summary 入口已存在（H1 已
    GREEN），RED 不经入口缺失分支给出 —— 当前实现对全部 10 个参数
    静默构建文档（fail-closed 行为缺失），由
    _expect_history_summary_fail_closed 的显式 AssertionError（“不得静默构建 history-summary
    文档”）钉出“history-summary 非法输入 fail-closed 行为缺失”；
    拒绝若以未类型化异常给出，同样经 AssertionError + cause 链转译。

    捕获的合理但错误实现：
    - 不读 entry status 字段（当前实现）-> 全部 status 参数静默构建文
      档，判失败；
    - 黑名单式 status 校验（只拒 pending_user_check）-> unknown /
      not_verified / verified_local / status_field_missing 参数失败；
    - 只检查 status、不检查夹带身份键 -> candidate_prompt_identity /
      candidate_model_identity 参数静默构建文档，判失败；
    - 只按 kind 判断（凡 prompt_history 一律放行）-> passed_true /
      组合参数失败；
    - 对合法已确认 entry 也拒绝（反向过宽）-> 合法对照断言失败；
    - 拒绝时抛未类型化异常（TypeError 等）-> 通道合规性断言失败
      （cause 链保留原始异常）；
    - 静默拒绝（异常消息为空）-> 非空拒因断言失败；
    - 拒绝路径写盘（history-summary 文件、records/、staging）-> 全树
      快照对比失败；
    - 就地改写传入 entry -> 输入不变断言失败。
    """
    _write_full_history_prompt_registry(tmp_path)
    declared_entry_dir = (
        tmp_path / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    )

    # ---- fixture 前置事实（对齐 H1）：声明源齐全，拒绝只能由非法
    #      entry 字段引起；目标根不存在。----
    assert (declared_entry_dir / "manifest.json").is_file(), (
        "fixture 前置事实失败：已确认历史源 manifest.json 必须存在"
    )
    assert (declared_entry_dir / "prompt.yaml").is_file(), (
        "fixture 前置事实失败：已确认历史源 prompt.yaml 必须存在"
    )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    entry = _history_entry_with_violation(violation)
    expected_entry = _history_entry_with_violation(violation)

    before = _snapshot_tree(tmp_path)

    # ---- 合法对照：反向门不得反向过宽（合法已确认 entry 仍构建）。----
    _assert_legal_history_entry_still_builds(build, tmp_path)

    # ---- 行为 1/2/3：fail-closed 拒绝 + 明确域错误/blocked 通道 +
    #      非空拒因 + 不静默构建文档。----
    _expect_history_summary_fail_closed(build, tmp_path, [entry])

    # ---- 行为 4：零写入 —— 全树逐字节不变（legacy 源不变、不写
    #      history-summary 文件、不创建任何目标条目）。----
    assert _snapshot_tree(tmp_path) == before, (
        "fail-closed 拒绝必须零写入：全树快照逐字节不变（不写 "
        "history-summary 文件、不创建 records/ 或任何目标条目、不改 "
        "legacy 源）"
    )
    assert not (tmp_path / "records").exists(), (
        "拒绝路径不得创建 records/ 或任何正式对象条目（不分配新正式身份）"
    )
    assert not (tmp_path / "docs").exists(), (
        "拒绝路径不得写入 history-summary 文件（文档只经返回值给出）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"拒绝路径不得落盘任何 history-summary 命名文件：发现 {path}"
        )

    # ---- 行为 5：不就地修改传入 entry。----
    assert entry == expected_entry, (
        "全程不得就地改写传入 entry（H2/H3 输入事实保持不变）"
    )


@pytest.mark.parametrize(
    "illegal_entries",
    [
        pytest.param(None, id="entries_none"),
        pytest.param(42, id="entries_non_iterable_int"),
        pytest.param("abc", id="entries_iterable_of_non_mappings"),
    ],
)
def test_history_summary_rejects_none_and_non_iterable_entries_fail_closed(
    tmp_path: Path, illegal_entries: Any
) -> None:
    r"""entries=None 与非可迭代输入必须被 fail-closed 拒绝，不得静默
    返回空文档：明确域错误 + 非空拒因 + 零写入 + legacy 不变（H2/H3，
    M1b history-summary 非法输入反向最小切片，先写测试，不改
    production）。

    H2/H3 behavior —— 对非法 ``entries`` 输入调用
    ``build_history_summary(root, entries)`` 必须：
    1. ``entries=None`` 与非可迭代输入（如整数）fail-closed 拒绝：
       不得静默返回 entries 为空的 history-summary 文档（空文档会被
       调用方当作“无历史需整理”消费，掩盖输入错误）；
    2. 可迭代但元素非 mapping（如字符串，元素为字符）同样拒绝：不
       得把非 mapping 元素当 entry 构建文档（当前实现已经
       PromptMigrationBlocked 域错误通道拒绝 —— 本参数为 Unexpected
       PASS 回归钉，钉定该通道不得回归为未类型化异常或静默空文档）；
    3. 拒绝经明确域错误（PromptMigrationBlocked 等 versioning 域错
       误）或 blocked 报告通道给出，携带非空拒因，不得抛未类型化异常
       （TypeError / ValueError 等直接穿透不是合规拒绝）；
    4. 零写入：全树逐字节不变（legacy 源不变、不写 history-summary
       文件、不创建 records/ 或任何目标条目）。

    fixture 与合法对照同
    test_history_summary_rejects_unconfirmed_or_smuggled_entries_fail_
    closed：声明源齐全 + 合法已确认 entry
    仍正常构建，使拒绝只能由 entries 形态引起，且反向门不得反向过宽。

    RED Gate 设计（H2/H3）：当前实现把 list(entries) 的 TypeError 静
    默吞掉（items = []），对 None / 42 返回 entries 为空的文档 ——
    由 _expect_history_summary_fail_closed 的显式 AssertionError（“不
    得静默构建 history-summary 文档（含 entries 为空的文档）”）钉出
    RED；entries_iterable_of_non_mappings 参数当前已 fail-closed，记
    为 Unexpected PASS。

    捕获的合理但错误实现：
    - 吞掉 TypeError 静默返回空文档（当前实现）-> entries_none /
      entries_non_iterable_int 参数判失败；
    - 让 list() 的原始 TypeError 直接穿透 -> 通道合规性断言失败
      （未类型化异常，cause 链保留）；
    - 把 None 当“空批”返回 ready 文档 -> 同第一类，判失败；
    - 对合法 entry 列表也拒绝（反向过宽）-> 合法对照断言失败；
    - 静默拒绝（空消息）-> 非空拒因断言失败；
    - 拒绝路径写盘 -> 全树快照对比失败。
    """
    _write_full_history_prompt_registry(tmp_path)
    declared_entry_dir = (
        tmp_path / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    )

    # ---- fixture 前置事实（对齐 H1）：声明源齐全、目标根不存在。----
    assert (declared_entry_dir / "manifest.json").is_file(), (
        "fixture 前置事实失败：已确认历史源 manifest.json 必须存在"
    )
    assert (declared_entry_dir / "prompt.yaml").is_file(), (
        "fixture 前置事实失败：已确认历史源 prompt.yaml 必须存在"
    )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    before = _snapshot_tree(tmp_path)

    # ---- 合法对照：反向门不得反向过宽（合法已确认 entry 仍构建）。----
    _assert_legal_history_entry_still_builds(build, tmp_path)

    # ---- 行为 1/2/3：fail-closed 拒绝 + 明确域错误/blocked 通道 +
    #      非空拒因 + 不静默返回空文档。----
    _expect_history_summary_fail_closed(build, tmp_path, illegal_entries)

    # ---- 行为 4：零写入 —— 全树逐字节不变（legacy 源不变、不写
    #      history-summary 文件、不创建任何目标条目）。----
    assert _snapshot_tree(tmp_path) == before, (
        "fail-closed 拒绝必须零写入：全树快照逐字节不变（不写 "
        "history-summary 文件、不创建 records/ 或任何目标条目、不改 "
        "legacy 源）"
    )
    assert not (tmp_path / "records").exists(), (
        "拒绝路径不得创建 records/ 或任何正式对象条目"
    )
    assert not (tmp_path / "docs").exists(), (
        "拒绝路径不得写入 history-summary 文件（文档只经返回值给出）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"拒绝路径不得落盘任何 history-summary 命名文件：发现 {path}"
        )
# ---------------------------------------------------------------------------
# H4：history-summary —— 声明源可读性与身份绑定门（先写测试，不改
# production）
# ---------------------------------------------------------------------------
#
# H4 behavior（本切片，主 Agent 选定，M1b history-summary 源可读性与身
# 份绑定门，先写测试，不改 production）—— build_history_summary 对声明
# 源 legacy ``pipeline/prompt_registry/<source_legacy_id>/
# {manifest.json,prompt.yaml}`` 的可读性缺口与身份矛盾按缺口类别分流，
# unknown 与 blocked 必须可区分（M0/Spec 证据：object-mapping.yaml
# model_train_eval_history 存在用户已确认、但声明源路径缺失的 history
# entry（known gap 明确记录），Plan M1 要求 history-summary"逐字段记录来
# 源或未知原因"）：
# 1. 声明源缺失（源条目目录缺失 / 目录为空 / manifest.json 或
#    prompt.yaml 单文件缺失）时，相关字段进入字段级 unknown，每条
#    unknown 事实携带非空 unknown_reason（可读缺失原因）与
#    attempted_source（指回声明源条目目录及其来源文件的曾尝试读取路
#    径），不得伪装成已知值；entry 不得静默消失，文档不得整批因缺失
#    blocked；未受影响的另一来源文件事实保持 H1 已知形态
#    {value, source}；
# 2. 源文件存在但坏 JSON/YAML（含合法解析但顶层非 mapping）时，必须
#    整批 fail-closed，不得降级为 unknown 静默构建文档（坏源是可读性
#    缺口的存在性证据，与"确实不在"的缺失必须可区分）；
# 3. 源文件可解析、内容哈希自洽，但身份字段（manifest.json /
#    prompt.yaml 的 revision_id，M0 verified_local：真实 manifest 的
#    revision_id 与所在 registry 目录名精确一致）与 entry
#    source_legacy_id 矛盾时，必须整批 fail-closed，不得在错误身份下
#    提取事实构建文档；
# 4. 上述全部路径零写入（legacy 源与全树逐字节不变、不写
#    history-summary 文件、不创建 records/ 或任何目标条目、不修复/
#    重建缺失源）、不就地修改传入 entry；合法已确认 entry 对照仍正常
#    构建（H1/H2 正向不回归）。
# 多 entry 批量（混合完整/缺失资料）、run/eval/model 历史条目、
# history-summary 文件写入与 CLI 不在本切片。

# H4 事实分组口径：镜像 H1 production _HISTORY_FACT_SOURCES ——
# manifest-only 事实指 manifest.json、prompt.yaml-only 事实指
# prompt.yaml；protocol_id 两源均有（H1 允许任一来源），两文件全缺失时
# 必须为 unknown（attempted_source 仅钉指回条目目录），单文件缺失时其
# unknown/known 归属不单独钉死（允许实现取另一来源声明值或标 unknown）。
_H4_ALL_FACT_NAMES = (
    "protocol_id",
    "prompt_content_sha256",
    "publishing_code_commit",
    "system_prompt",
    "user_prompt",
    "output_fields",
)
_H4_FACT_SOURCE_FILES = {
    "protocol_id": None,
    "prompt_content_sha256": "manifest.json",
    "publishing_code_commit": "manifest.json",
    "system_prompt": "prompt.yaml",
    "user_prompt": "prompt.yaml",
    "output_fields": "prompt.yaml",
}

# 各源缺失形态下六个必需事实的期望归属（unknown / known，其余 = 不钉死）。
_H4_MISSING_SOURCE_STATES = {
    "source_dir_missing": {
        "unknown": _H4_ALL_FACT_NAMES,
        "known": (),
    },
    "source_dir_empty": {
        "unknown": _H4_ALL_FACT_NAMES,
        "known": (),
    },
    "manifest_missing": {
        "unknown": ("prompt_content_sha256", "publishing_code_commit"),
        "known": ("system_prompt", "user_prompt", "output_fields"),
    },
    "prompt_missing": {
        "unknown": ("system_prompt", "user_prompt", "output_fields"),
        "known": ("prompt_content_sha256", "publishing_code_commit"),
    },
}

# 声明源坏内容（文件存在：是不可解析/不可用，不是缺失）。manifest 侧
# 覆盖坏 JSON 与合法 JSON 但顶层非 mapping；prompt 侧镜像覆盖坏 YAML
# 与合法 YAML 但顶层非 mapping。
_H4_SOURCE_CORRUPTIONS = {
    "manifest_bad_json": ("manifest.json", b'{ not valid json'),
    "manifest_not_mapping": ("manifest.json", b"[1, 2]\n"),
    "prompt_bad_yaml": ("prompt.yaml", b"system_prompt: [unclosed flow"),
    "prompt_not_mapping": ("prompt.yaml", b"- a\n- b\n"),
}


def _remove_history_declared_source(root: Path, source_state: str) -> None:
    """按 source_state 移除声明源（v4.1-concise-evidence-json-v1）文件。

    只动声明源条目，未声明 sibling（v4.1-concise-evidence-json-v2 /
    v4.1-fixed-full-fields-initial-v1）保持完整 —— entry 的缺口形态只能
    由声明源缺失引起，不得由 sibling 损伤混入。
    """
    declared_dir = root / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    if source_state == "source_dir_missing":
        shutil.rmtree(declared_dir)
    elif source_state == "source_dir_empty":
        (declared_dir / "manifest.json").unlink()
        (declared_dir / "prompt.yaml").unlink()
    elif source_state == "manifest_missing":
        (declared_dir / "manifest.json").unlink()
    elif source_state == "prompt_missing":
        (declared_dir / "prompt.yaml").unlink()
    else:
        raise AssertionError(f"未知 source_state {source_state!r}")


def _assert_history_declared_source_state(root: Path, source_state: str) -> None:
    """钉定源缺失 mutation 真实生效且未声明 sibling 完好（fixture 前置）。"""
    declared_dir = root / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    if source_state == "source_dir_missing":
        assert not declared_dir.exists(), (
            "fixture 前置事实失败：source_dir_missing 下声明源条目目录必须不存在"
        )
    else:
        assert declared_dir.is_dir(), (
            "fixture 前置事实失败：该形态下声明源条目目录必须存在"
        )
        if source_state in ("source_dir_empty", "manifest_missing"):
            assert not (declared_dir / "manifest.json").exists(), (
                "fixture 前置事实失败：该形态下声明源 manifest.json 必须缺失"
            )
        else:
            assert (declared_dir / "manifest.json").is_file(), (
                "fixture 前置事实失败：该形态下声明源 manifest.json 必须存在"
            )
        if source_state in ("source_dir_empty", "prompt_missing"):
            assert not (declared_dir / "prompt.yaml").exists(), (
                "fixture 前置事实失败：该形态下声明源 prompt.yaml 必须缺失"
            )
        else:
            assert (declared_dir / "prompt.yaml").is_file(), (
                "fixture 前置事实失败：该形态下声明源 prompt.yaml 必须存在"
            )
    for sibling_id in (CONFIRMED_PROMPT_SOURCE_ID, _THIRD_REGISTRY_SOURCE_ID):
        sibling_dir = root / "pipeline" / "prompt_registry" / sibling_id
        assert (sibling_dir / "manifest.json").is_file() and (
            sibling_dir / "prompt.yaml"
        ).is_file(), (
            f"fixture 前置事实失败：未声明 sibling {sibling_id} 必须保持完整"
            "（缺失只能由声明源引起）"
        )


def _assert_history_fact_is_unknown(
    fact: Any,
    *,
    name: str,
    declared_rel_dir: str,
    expected_file: str | None,
) -> None:
    """断言单条事实为 H4 字段级 unknown 形态（与 blocked 可区分的缺口形态）。

    契约：
    - fact 为 mapping，携带非空字符串 unknown_reason（可读缺失原因，
      不得静默标 unknown）；
    - 携带非空 attempted_source（曾尝试读取的声明源路径；字符串或含
      路径片段的 mapping 结构均可），必须指回声明源条目目录；
      expected_file 非 None（manifest-only / prompt.yaml-only 事实）时
      还须指回对应来源文件；
    - 不得携带非 None 的 value（缺失资料不得伪装成已知值，不重算、不
      伪造、不取 sibling）。
    """
    assert isinstance(fact, Mapping), (
        f"缺失源的事实 {name} 必须以 mapping 形态进入字段级 unknown（携带 "
        f"unknown_reason / attempted_source）：实际 {type(fact).__name__!r}"
    )
    reason = fact.get("unknown_reason")
    assert isinstance(reason, str) and reason.strip(), (
        f"缺失源的事实 {name} 必须携带非空字符串 unknown_reason（可读缺失"
        f"原因，不得静默标 unknown）：实际 {reason!r}"
    )
    attempted = fact.get("attempted_source")
    attempted_text = " ".join(_document_string_fragments(attempted))
    assert attempted_text.strip(), (
        f"缺失源的事实 {name} 必须携带非空 attempted_source（曾尝试读取的"
        f"声明源路径）：实际 {attempted!r}"
    )
    assert declared_rel_dir in attempted_text, (
        f"缺失源的事实 {name} 的 attempted_source 必须指回声明源条目目录"
        f"（{declared_rel_dir}）：实际 {attempted_text!r}"
    )
    if expected_file is not None:
        assert expected_file in attempted_text, (
            f"缺失源的事实 {name} 的 attempted_source 必须指回其来源文件 "
            f"{expected_file}：实际 {attempted_text!r}"
        )
    if "value" in fact:
        assert fact["value"] is None, (
            f"缺失源的事实 {name} 不得携带非 None 的 value（缺失资料不得伪装"
            f"成已知值）：实际 {fact['value']!r}"
        )


def _assert_history_fact_is_known(
    fact: Any,
    *,
    name: str,
    expected_value: Any,
    declared_rel_dir: str,
    expected_file: str | None,
) -> None:
    """断言单条事实保持 H1 已知形态 {value, source}（未受影响的来源文件）。"""
    assert isinstance(fact, Mapping), (
        f"未受影响来源的事实 {name} 必须保持 H1 已知形态 {{value, source}} 的"
        f" mapping：实际 {type(fact).__name__!r}"
    )
    assert set(fact) == {"value", "source"}, (
        f"未受影响来源的事实 {name} 的键集必须恰为 {{value, source}}（H1 契约，"
        f"单文件缺失不得改变已知事实形态）：实际 {sorted(fact)}"
    )
    assert fact["value"] == expected_value, (
        f"未受影响来源的事实 {name} 的 value 必须与声明源声明值逐值相等（不重"
        f"算、不伪造、不取 sibling）：实际 {fact['value']!r}，期望 "
        f"{expected_value!r}"
    )
    source = fact["source"]
    assert isinstance(source, Mapping) and source, (
        f"未受影响来源的事实 {name} 必须携带非空 mapping 形态的字段级来源 "
        f"provenance（source）：实际 {source!r}"
    )
    source_text = " ".join(_document_string_fragments(source))
    assert declared_rel_dir in source_text, (
        f"未受影响来源的事实 {name} 的来源 provenance 必须指回声明源条目"
        f"（{declared_rel_dir}）：实际 {source_text!r}"
    )
    if expected_file is not None:
        assert expected_file in source_text, (
            f"未受影响来源的事实 {name} 的来源 provenance 必须指回其来源文件 "
            f"{expected_file}：实际 {source_text!r}"
        )


def _rewrite_history_declared_prompt_revision(
    root: Path, new_revision_id: str
) -> None:
    """把声明源 prompt.yaml 的身份字段 revision_id 改写为 new_revision_id。

    其余字节不变；同步改写 manifest.json 的 prompt_yaml_sha256 /
    source_sha256（真实 registry 事实：source_sha256 == prompt_yaml_sha256
    == prompt.yaml 文件字节哈希），保持 fixture 除 revision_id 矛盾外自
    洽：权威内容哈希 payload 不含 revision_id，prompt_content_sha256 声
    明值不需改动、仍与 prompt.yaml 声明值一致 —— 拒绝只能由身份字段矛
    盾引起。
    """
    entry_dir = root / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    prompt_bytes = (entry_dir / "prompt.yaml").read_bytes()
    replaced = prompt_bytes.replace(
        f"revision_id: {HISTORY_SIBLING_SOURCE_ID}\n".encode("utf-8"),
        f"revision_id: {new_revision_id}\n".encode("utf-8"),
    )
    assert replaced != prompt_bytes, (
        "fixture 前置事实失败：prompt.yaml revision_id 改写必须真实生效"
    )
    (entry_dir / "prompt.yaml").write_bytes(replaced)
    manifest = json.loads((entry_dir / "manifest.json").read_text(encoding="utf-8"))
    file_hash = hashlib.sha256(replaced).hexdigest()
    manifest["prompt_yaml_sha256"] = file_hash
    manifest["source_sha256"] = file_hash
    (entry_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rewrite_history_declared_manifest_revision(
    root: Path, new_revision_id: str
) -> None:
    """把声明源 manifest.json 的身份字段 revision_id 改写为
    new_revision_id，其余声明字段（含全部哈希）保持不变。"""
    entry_dir = root / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    manifest = json.loads((entry_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("revision_id") == HISTORY_SIBLING_SOURCE_ID, (
        "fixture 前置事实失败：改写前 manifest revision_id 必须与条目目录/"
        "source_legacy_id 一致"
    )
    manifest["revision_id"] = new_revision_id
    (entry_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "source_state",
    [
        pytest.param("source_dir_missing", id="source_dir_missing"),
        pytest.param("source_dir_empty", id="source_dir_empty"),
        pytest.param("manifest_missing", id="manifest_missing"),
        pytest.param("prompt_missing", id="prompt_missing"),
    ],
)
def test_history_summary_missing_declared_source_records_field_level_unknown_without_blocking(
    tmp_path: Path, source_state: str
) -> None:
    r"""声明源缺失时相关字段必须进入字段级 unknown（unknown_reason +
    attempted_source），entry 不静默消失、不整批 blocked（H4，M1b
    history-summary 源可读性门，先写测试，不改 production）。

    H4 behavior —— 对已确认 prompt_history entry（H1 同一 fixture 与
    entry：kind prompt_history、source_legacy_id
    v4.1-concise-evidence-json-v1、status user_confirmed），其声明源
    legacy 文件按 source_state 缺失（源条目目录缺失 / 目录为空 /
    manifest.json 单缺失 / prompt.yaml 单缺失；未声明 sibling 保持完
    整）时调用 ``build_history_summary(root, [entry])`` 必须：
    1. 返回 history-summary 文档（history_summary_schema ==
       tensile-migration/history-summary/v1），不得 fail-closed 拒绝
       —— 不得整批因缺失 blocked（抛域错误或返回 blocked 报告均判失
       败，与 H2/H3 非法输入的 blocked 通道必须可区分）；
    2. entries 恰含声明的一条：entry 不得静默消失，也不得扫描 legacy
       目录生成未声明条目；entry 级结构保持 H1（original_id 保留原始
       legacy ID（来源是 entry 声明而非源文件）、kind 保持声明、
       history_only: true、formal_identity: "none"、entry_id 为非空
       文档内 slug 且非 <kind>-v<协议>-r<N> 正式身份）；
    3. facts 逐字段进入 unknown（缺失不是删字段）：
       - 全缺失形态（目录缺失 / 为空）：六个必需事实全部 unknown；
       - manifest_missing：manifest-only 事实（prompt_content_sha256 /
         publishing_code_commit）unknown，prompt.yaml-only 事实
         （system_prompt / user_prompt / output_fields）保持 H1 已知形
         态 {value, source}（值取声明源 prompt.yaml 声明值）；
       - prompt_missing：镜像对称；
       - protocol_id 两源均有：全缺失形态下必须 unknown，单文件缺失形
         态下归属不钉死（取另一来源声明值或标 unknown 均可）；
    4. 每条 unknown 事实为 mapping，携带非空字符串 unknown_reason（可
       读缺失原因，不得静默标 unknown）与非空 attempted_source（曾
       尝试读取的声明源路径：指回声明源条目目录，manifest-only /
       prompt.yaml-only 事实分别指回 manifest.json / prompt.yaml）；
       unknown 事实不得携带非 None 的 value（缺失资料不得伪装成已知
       值，不从 sibling 取内容）；
    5. 纯构建零写入：全树快照逐字节不变（不写 history-summary 文件、
       不创建 records/ 或任何目标条目、不修复/重建缺失的 legacy 源）；
    6. 不就地修改传入 entry。

    fixture 隔离：_write_full_history_prompt_registry 完整三条目
    registry；mutation 只移除声明源对应文件，sibling 保持完整 —— 缺失
    只能由声明源引起。合法对照在 mutation 前对完整 fixture 执行（证
    明 fixture 与入口通道可用、分流不误伤合法已确认 entry）。

    RED Gate 设计（H4）：build_history_summary 入口已存在（H1 已
    GREEN）。当前实现（H3 反向切片）对声明源缺失一律抛
    PromptMigrationBlocked（"manifest.json/prompt.yaml 缺失或无法解
    析: [Errno 2] …"）—— 把缺失当 blocked、entry 消失、无字段级
    unknown_reason / attempted_source。本测试把该拒绝转成显式行为
    AssertionError（原始域错误经 cause 链保留，不得直接充当 RED 结
    论）钉出"缺失资料字段级 unknown 行为缺失"；fixture 构建、合法对
    照、mutation 生效前置断言与全树快照均真实执行后才失败。

    捕获的合理但错误实现：
    - 缺失 fail-closed（当前实现）-> 转译后的显式 AssertionError 判失
      败；
    - entry 静默消失（跳过缺失源条目）/ 返回空文档 -> entries 数量断言
      失败；
    - 返回 blocked 报告 -> history_summary_schema 断言失败；
    - unknown 字段缺 unknown_reason / attempted_source 或二者为空 ->
      字段级断言失败；
    - unknown 字段携带伪造 value（从 sibling 取内容冒充已知值）->
      非 None value 断言失败（全缺失形态另有 sibling ID 不得进入文档
      断言兜底）；
    - 单文件缺失时把未受影响来源的已知事实也标 unknown（缺口扩大）或
      值漂移（取 sibling 声明值）-> 已知事实形态与值断言失败；
    - 构建路径写盘（history-summary 文件、records/、重建/修复源文件）
      -> 全树快照对比失败；
    - 就地改写传入 entry -> 输入不变断言失败。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（H4 仅新增用例
      与配套 helper/常量及模块 docstring 清单条目，不改 production）。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （与 H1/H2/H3 binding 记录一致，``[tool.pytest.ini_options]
      testpaths / pythonpath`` 解析依赖该文件）。
    - 命令（新 selector）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_history_summary_missing_declared_source_records_field_level_unknown_without_blocking``
      —— RED 时点恰 4 failed（四个 source_state 参数）、0 passed，失
      败为转译后的 AssertionError"声明源缺失必须进入字段级 unknown…"，
      cause 链保留原始 PromptMigrationBlocked；不出现原始异常直接充当
      RED 结论，fixture 前置事实与合法对照全部不失败。
    - 既有 selector 复跑（回归钉）：H1 selector（-k test_confirmed_
      prompt_history_entry_builds_history_summary_document_without_
      writes）与 H2/H3 selectors（-k history_summary_rejects）通过。
    """
    declared_bytes = _write_full_history_prompt_registry(tmp_path)
    declared_entry_dir = (
        tmp_path / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    )
    declared_rel_dir = f"pipeline/prompt_registry/{HISTORY_SIBLING_SOURCE_ID}"

    # ---- fixture 前置事实（对齐 H1）：声明源与 sibling 完整、目标根
    #      不存在；预捕获声明源声明值（mutation 后文件不可读）。----
    assert (declared_entry_dir / "prompt.yaml").read_bytes() == declared_bytes, (
        "fixture 前置事实失败：已确认历史源 prompt.yaml 必须可逐字节读回"
    )
    assert (declared_entry_dir / "manifest.json").is_file(), (
        "fixture 前置事实失败：已确认历史源 manifest.json 必须存在"
    )
    declared_manifest = json.loads(
        (declared_entry_dir / "manifest.json").read_text(encoding="utf-8")
    )
    declared_prompt = yaml.safe_load(declared_bytes)
    assert declared_manifest.get("revision_id") == HISTORY_SIBLING_SOURCE_ID and (
        declared_prompt.get("revision_id") == HISTORY_SIBLING_SOURCE_ID
    ), (
        "fixture 前置事实失败：完整声明源的身份字段必须与 source_legacy_id"
        " 一致（本用例只测缺失形态，不测身份矛盾）"
    )
    expected_known_values = {
        "protocol_id": declared_manifest["protocol_id"],
        "prompt_content_sha256": declared_manifest["prompt_content_sha256"],
        "publishing_code_commit": declared_manifest["publishing_code_commit"],
        "system_prompt": declared_prompt["system_prompt"],
        "user_prompt": declared_prompt["user_prompt"],
        "output_fields": declared_prompt["output_fields"],
    }
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    entry = _confirmed_prompt_history_entry()
    expected_entry = _confirmed_prompt_history_entry()

    # ---- 合法对照（mutation 前、fixture 完整）：分流不得误伤合法已确
    #      认 entry（H1 正向行为不回归）。----
    _assert_legal_history_entry_still_builds(build, tmp_path)

    # ---- 按参数移除声明源对应文件，钉定 mutation 生效且 sibling 完好。----
    _remove_history_declared_source(tmp_path, source_state)
    _assert_history_declared_source_state(tmp_path, source_state)

    before = _snapshot_tree(tmp_path)

    # ---- 行为 1：缺失不得整批 blocked / entry 不得消失。----
    try:
        document = build(tmp_path, [entry])
    except Exception as exc:
        raise AssertionError(
            "声明源缺失必须进入字段级 unknown（unknown_reason / "
            "attempted_source），不得 fail-closed 拒绝使 entry 消失或整批"
            f"blocked（H4 缺失资料形态行为缺失）：实际抛出 "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        ) from exc
    assert isinstance(document, Mapping), (
        "声明源缺失必须返回 history-summary 文档（entry 进入字段级 "
        f"unknown，不整批 blocked）：实际 {type(document).__name__!r}"
    )
    assert (
        document.get("history_summary_schema")
        == "tensile-migration/history-summary/v1"
    ), (
        "声明源缺失不得整批 blocked：必须返回 history-summary 文档"
        "（history_summary_schema == 'tensile-migration/history-summary/v1'）："
        f"实际 {document.get('history_summary_schema')!r}"
    )

    # ---- 行为 2：恰一条 entry，entry 级结构保持 H1。----
    document_entries = document.get("entries")
    assert isinstance(document_entries, list), (
        "history-summary 文档的 entries 必须是 list：实际 "
        f"{type(document_entries).__name__!r}"
    )
    assert len(document_entries) == 1, (
        "声明源缺失时 entry 不得静默消失，也不得生成未声明条目：文档必须恰含"
        f"声明的一条 entry：实际 {len(document_entries)} 条"
    )
    summary_entry = document_entries[0]
    assert isinstance(summary_entry, Mapping), (
        "history-summary entry 必须是 mapping：实际 "
        f"{type(summary_entry).__name__!r}"
    )
    assert summary_entry.get("original_id") == HISTORY_SIBLING_SOURCE_ID, (
        "缺失源 entry 必须保留 original_id（原始 legacy ID 来源是 entry 声明"
        f"而非源文件）：实际 {summary_entry.get('original_id')!r}"
    )
    assert summary_entry.get("kind") == "prompt_history", (
        "缺失源 entry 必须保持声明的 kind（prompt_history）：实际 "
        f"{summary_entry.get('kind')!r}"
    )
    assert summary_entry.get("history_only") is True, (
        "缺失源 entry 必须标记 history_only: true：实际 "
        f"{summary_entry.get('history_only')!r}"
    )
    assert summary_entry.get("formal_identity") == "none", (
        "缺失源 entry 必须标记 formal_identity: none（不分配新正式身份）："
        f"实际 {summary_entry.get('formal_identity')!r}"
    )
    entry_id = summary_entry.get("entry_id")
    assert isinstance(entry_id, str) and entry_id, (
        "缺失源 entry 必须携带非空字符串 entry_id（文档内 slug）：实际 "
        f"{entry_id!r}"
    )
    assert not is_valid_version_id(entry_id), (
        "entry_id 必须是文档内 slug，不得是 <kind>-v<协议>-r<N> 正式身份："
        f"实际 {entry_id!r}"
    )

    # ---- 行为 3/4：facts 逐字段按缺失形态进入 unknown（字段级
    #      unknown_reason / attempted_source）或保持 H1 已知形态。----
    facts = summary_entry.get("facts")
    assert isinstance(facts, Mapping) and facts, (
        "缺失源 entry 必须携带非空 facts（缺失资料进入字段级 unknown，不是"
        f"删字段）：实际 {facts!r}"
    )
    expected_split = _H4_MISSING_SOURCE_STATES[source_state]
    for name in _H4_ALL_FACT_NAMES:
        assert name in facts, (
            f"缺失源时必需事实 {name} 不得从 facts 中消失（缺失进入字段级 "
            f"unknown，不是删字段）：实际键集 {sorted(facts)}"
        )
        fact = facts[name]
        if name in expected_split["unknown"]:
            _assert_history_fact_is_unknown(
                fact,
                name=name,
                declared_rel_dir=declared_rel_dir,
                expected_file=_H4_FACT_SOURCE_FILES[name],
            )
        elif name in expected_split["known"]:
            _assert_history_fact_is_known(
                fact,
                name=name,
                expected_value=expected_known_values[name],
                declared_rel_dir=declared_rel_dir,
                expected_file=_H4_FACT_SOURCE_FILES[name],
            )
        # protocol_id 在单文件缺失形态下归属不钉死（H1 允许任一来源：
        # 取另一来源声明值或标 unknown 均可），不在此断言。

    # ---- 全缺失形态兜底：不得从 sibling 取内容冒充（sibling ID 不得
    #      进入文档任何字符串）。----
    if source_state in ("source_dir_missing", "source_dir_empty"):
        all_strings = _document_string_fragments(document)
        for sibling_id in (CONFIRMED_PROMPT_SOURCE_ID, _THIRD_REGISTRY_SOURCE_ID):
            assert not any(sibling_id in fragment for fragment in all_strings), (
                f"声明源全缺失时未声明 sibling {sibling_id} 不得进入文档任何"
                "字符串（unknown 事实不得从 sibling 取内容冒充已知值）"
            )

    # ---- 行为 5：纯构建零写入（不修复/重建缺失源、不落盘任何目标）。----
    assert _snapshot_tree(tmp_path) == before, (
        "缺失形态的纯构建必须零写入：全树快照逐字节不变（不写 "
        "history-summary 文件、不创建 records/ 或任何目标条目、不修复或"
        "重建缺失的 legacy 源）"
    )
    assert not (tmp_path / "records").exists(), (
        "缺失形态纯构建不得创建 records/ 或任何正式对象条目"
    )
    assert not (tmp_path / "docs").exists(), (
        "缺失形态纯构建不得写入 history-summary 文件（文档只经返回值给出）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"缺失形态纯构建不得落盘任何 history-summary 命名文件：发现 {path}"
        )

    # ---- 行为 6：不就地修改传入 entry。----
    assert entry == expected_entry, (
        "全程不得就地改写传入 entry（H4 输入事实保持不变）"
    )


@pytest.mark.parametrize(
    "corruption",
    [
        pytest.param("manifest_bad_json", id="manifest_bad_json"),
        pytest.param("manifest_not_mapping", id="manifest_not_mapping"),
        pytest.param("prompt_bad_yaml", id="prompt_bad_yaml"),
        pytest.param("prompt_not_mapping", id="prompt_not_mapping"),
    ],
)
def test_history_summary_unparseable_declared_source_fails_closed(
    tmp_path: Path, corruption: str
) -> None:
    r"""声明源存在但坏 JSON/YAML（含顶层非 mapping）时必须整批
    fail-closed，不得降级为 unknown 静默构建文档（H4，M1b
    history-summary 源可读性门，先写测试，不改 production）。

    H4 behavior —— 对已确认 prompt_history entry（H1 同一 fixture 与
    entry），其声明源对应文件被覆写为坏内容（manifest.json：非合法
    JSON / 合法 JSON 但顶层非 mapping；prompt.yaml：非合法 YAML / 合法
    YAML 但顶层非 mapping；另一来源文件保持完整，文件存在性钉定"是
    不可解析/不可用，不是缺失"）时调用 ``build_history_summary(root,
    [entry])`` 必须：
    1. 整批 fail-closed：经明确域错误（PromptMigrationBlocked 等
       versioning 域错误）或 blocked 报告通道拒绝，携带非空拒因（复用
       H2/H3 的 _expect_history_summary_fail_closed 通道契约）；
       不得返回 history-summary 文档 —— 含把坏源字段标 unknown 的文
       档也不行：坏源是可读性缺口的存在性证据，降级为 unknown 是静默
       丢弃可读证据的 fail-open，与"源确实不在"的缺失（行为 1 的字段
       级 unknown）必须可区分；即使另一来源文件完好可提取部分事实，
       也不得部分构建；
    2. 零写入：全树逐字节不变（legacy 源不变、不写 history-summary 文
       件、不创建 records/ 或任何目标条目）；
    3. 不就地修改传入 entry；合法已确认 entry 对照仍正常构建（mutation
       前对完整 fixture 执行）。

    RED Gate 设计（H4）：本用例对当前实现为 Unexpected PASS（回归钉）
    —— 当前 _build_history_summary_entry 对 manifest.json /
    prompt.yaml 的 json.loads / yaml.safe_load 失败与顶层非 mapping 均
    经 PromptMigrationBlocked 域错误通道整批拒绝，满足本切片契约；记录
    为 Unexpected PASS，不当 RED，钉定该通道不得回归为静默文档、字段级
    unknown 或未类型化异常穿透。

    捕获的合理但错误实现：
    - 坏源降级为字段级 unknown 构建文档 -> _expect_history_summary_
      fail_closed 的"不得静默构建文档"断言失败；
    - 只在另一文件也坏时才拒绝（部分构建）-> 同上；
    - 拒绝以未类型化异常穿透 -> 通道合规性断言失败（cause 链保留）；
    - 静默拒绝（空拒因）-> 非空拒因断言失败；
    - 拒绝路径写盘 -> 全树快照对比失败；
    - 就地改写传入 entry -> 输入不变断言失败。

    Binding（证据绑定，供复跑核对）：
    - 命令（新 selector）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_history_summary_unparseable_declared_source_fails_closed``
      —— 本切片时点 4 passed（Unexpected PASS 回归钉），GREEN 后保持
      通过。
    - 测试文件与 ``pyproject.toml`` sha256 同本切片缺失用例 docstring
      的 Binding 记录。
    """
    _write_full_history_prompt_registry(tmp_path)
    declared_entry_dir = (
        tmp_path / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    )
    file_name, corrupt_bytes = _H4_SOURCE_CORRUPTIONS[corruption]

    # ---- fixture 前置事实（对齐 H1）：声明源完整、目标根不存在。----
    assert (declared_entry_dir / "manifest.json").is_file(), (
        "fixture 前置事实失败：覆写前已确认历史源 manifest.json 必须存在"
    )
    assert (declared_entry_dir / "prompt.yaml").is_file(), (
        "fixture 前置事实失败：覆写前已确认历史源 prompt.yaml 必须存在"
    )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    entry = _confirmed_prompt_history_entry()
    expected_entry = _confirmed_prompt_history_entry()

    # ---- 合法对照（corruption 前）：门不得反向过宽。----
    _assert_legal_history_entry_still_builds(build, tmp_path)

    # ---- 覆写声明源对应文件为坏内容（文件存在：是不可解析，不是缺
    #      失）；另一来源文件保持完整。----
    (declared_entry_dir / file_name).write_bytes(corrupt_bytes)
    assert (declared_entry_dir / file_name).read_bytes() == corrupt_bytes, (
        "fixture 前置事实失败：坏内容覆写必须真实生效"
    )
    other_file = (
        "prompt.yaml" if file_name == "manifest.json" else "manifest.json"
    )
    assert (declared_entry_dir / other_file).is_file(), (
        "fixture 前置事实失败：另一来源文件必须保持完整（拒绝只能由坏"
        "内容引起，不得由缺失混入）"
    )

    before = _snapshot_tree(tmp_path)

    # ---- 行为 1：整批 fail-closed（明确域错误/blocked 通道 + 非空
    #      拒因 + 不静默构建文档，含 unknown 形态的文档）。----
    _expect_history_summary_fail_closed(build, tmp_path, [entry])

    # ---- 行为 2：零写入 —— 全树逐字节不变。----
    assert _snapshot_tree(tmp_path) == before, (
        "坏源 fail-closed 拒绝必须零写入：全树快照逐字节不变（不写 "
        "history-summary 文件、不创建 records/ 或任何目标条目、不改 "
        "legacy 源）"
    )
    assert not (tmp_path / "records").exists(), (
        "坏源拒绝路径不得创建 records/ 或任何正式对象条目"
    )
    assert not (tmp_path / "docs").exists(), (
        "坏源拒绝路径不得写入 history-summary 文件（文档只经返回值给出）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"坏源拒绝路径不得落盘任何 history-summary 命名文件：发现 {path}"
        )

    # ---- 行为 3：不就地修改传入 entry。----
    assert entry == expected_entry, (
        "全程不得就地改写传入 entry（H4 输入事实保持不变）"
    )


@pytest.mark.parametrize(
    "identity_mutation",
    [
        pytest.param("manifest_revision_mismatch", id="manifest_revision_mismatch"),
        pytest.param("prompt_revision_mismatch", id="prompt_revision_mismatch"),
        pytest.param("both_revisions_mismatch", id="both_revisions_mismatch"),
    ],
)
def test_history_summary_source_identity_field_mismatch_fails_closed(
    tmp_path: Path, identity_mutation: str
) -> None:
    r"""源文件可解析、内容哈希自洽，但身份字段 revision_id 与
    source_legacy_id 矛盾时必须整批 fail-closed（H4，M1b
    history-summary 身份绑定门，先写测试，不改 production）。

    H4 behavior —— 真实 legacy registry 的 manifest.json 与 prompt.yaml
    均携带身份字段 revision_id（M0 verified_local：三份真实 manifest /
    prompt.yaml 的 revision_id 与其所在 registry 目录名（即条目
    source_legacy_id）精确一致）。对已确认 prompt_history entry（H1
    同一 fixture 与 entry），其声明源文件可解析、内容哈希自洽
    （prompt_content_sha256 按权威 recipe 与 prompt.yaml 声明值一致、
    prompt_yaml_sha256 与 prompt.yaml 文件字节一致），但 revision_id
    被改写为另一真实身份（manifest.json 单侧 / prompt.yaml 单侧 / 双
    侧）时调用 ``build_history_summary(root, [entry])`` 必须：
    1. 整批 fail-closed（_expect_history_summary_fail_closed 通道契
       约）：不得在错误身份下静默提取事实构建文档 —— 那会把 A 身份
       的源内容归到 B 身份的 entry 下，是历史归因漂移（也不得改为从
       revision_id 指向的 sibling 目录取内容）；
    2. 零写入：全树逐字节不变（legacy 源不变、不写 history-summary 文
       件、不创建 records/ 或任何目标条目）；
    3. 不就地修改传入 entry；合法已确认 entry 对照仍正常构建（mutation
       前对完整 fixture 执行）。

    fixture 隔离：改写只动身份字段 revision_id（manifest 侧 / prompt
    侧 / 双侧），manifest 的内容与文件字节哈希字段同步保持自洽（见
    _rewrite_history_declared_prompt_revision），使拒绝只能由身份矛
    盾引起，不得由内容哈希失配或缺失混入。

    RED Gate 设计（H4）：当前实现完全不读取/比对 revision_id，对三类
    矛盾参数全部静默构建文档（含声明源事实的 entry）—— 由 _expect_
    history_summary_fail_closed 的显式 AssertionError（"不得静默构建
    history-summary 文档"）钉出"history-summary 身份绑定门缺失"。

    捕获的合理但错误实现：
    - 不比对 revision_id（当前实现）-> 全部参数静默构建文档，判失败；
    - 只比 manifest 侧 / 只比 prompt.yaml 侧 -> 另一单侧参数静默放行，
      判失败；
    - 把身份矛盾降级为字段级 unknown 文档 -> 必须与源缺失可区分（矛盾
      是 fail-closed，不是 unknown），"不得静默构建文档"断言失败；
    - 按 revision_id 改读 sibling 目录取内容 -> 归因漂移，同上判失败；
    - 拒绝以未类型化异常穿透 / 空拒因 -> 通道合规性与非空拒因断言失败；
    - 拒绝路径写盘 / 就地改写传入 entry -> 快照与输入不变断言失败。

    Binding（证据绑定，供复跑核对）：
    - 命令（新 selector）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_history_summary_source_identity_field_mismatch_fails_closed``
      —— RED 时点恰 3 failed（三个 identity_mutation 参数）、
      0 passed，失败为 _expect_history_summary_fail_closed 的
      AssertionError"非法 history 输入必须 fail-closed 拒绝，不得静默
      构建 history-summary 文档…"（当前实现返回含声明源事实的文档）；
      fixture 前置事实与合法对照全部不失败。
    - 测试文件与 ``pyproject.toml`` sha256 同本切片缺失用例 docstring
      的 Binding 记录。
    """
    _write_full_history_prompt_registry(tmp_path)
    declared_entry_dir = (
        tmp_path / "pipeline" / "prompt_registry" / HISTORY_SIBLING_SOURCE_ID
    )

    # ---- fixture 前置事实（对齐 H1）：声明源完整、目标根不存在。----
    assert (declared_entry_dir / "manifest.json").is_file(), (
        "fixture 前置事实失败：改写前已确认历史源 manifest.json 必须存在"
    )
    assert (declared_entry_dir / "prompt.yaml").is_file(), (
        "fixture 前置事实失败：改写前已确认历史源 prompt.yaml 必须存在"
    )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    entry = _confirmed_prompt_history_entry()
    expected_entry = _confirmed_prompt_history_entry()

    # ---- 合法对照（mutation 前）：门不得反向过宽。----
    _assert_legal_history_entry_still_builds(build, tmp_path)

    # ---- 按参数改写身份字段 revision_id（只动身份，哈希保持自洽）。----
    if identity_mutation == "manifest_revision_mismatch":
        _rewrite_history_declared_manifest_revision(
            tmp_path, CONFIRMED_PROMPT_SOURCE_ID
        )
    elif identity_mutation == "prompt_revision_mismatch":
        _rewrite_history_declared_prompt_revision(
            tmp_path, _THIRD_REGISTRY_SOURCE_ID
        )
    elif identity_mutation == "both_revisions_mismatch":
        # prompt 侧改写同步更新 manifest 文件字节哈希，须先于 manifest
        # 侧 revision_id 改写执行。
        _rewrite_history_declared_prompt_revision(
            tmp_path, CONFIRMED_PROMPT_SOURCE_ID
        )
        _rewrite_history_declared_manifest_revision(
            tmp_path, CONFIRMED_PROMPT_SOURCE_ID
        )
    else:
        raise AssertionError(f"未知 identity_mutation {identity_mutation!r}")

    # ---- mutation 生效前置事实：两文件存在且可解析、内容哈希自洽 ——
    #      拒绝只能由身份字段矛盾引起。----
    manifest = json.loads(
        (declared_entry_dir / "manifest.json").read_text(encoding="utf-8")
    )
    prompt_bytes = (declared_entry_dir / "prompt.yaml").read_bytes()
    prompt = yaml.safe_load(prompt_bytes)
    assert isinstance(manifest, Mapping) and isinstance(prompt, Mapping), (
        "fixture 前置事实失败：改写后两份源文件必须仍可解析为 mapping"
    )
    assert _prompt_content_sha256_of_yaml(prompt_bytes) == manifest.get(
        "prompt_content_sha256"
    ), (
        "fixture 前置事实失败：改写后 prompt_content_sha256 必须仍与 "
        "prompt.yaml 声明值按权威 recipe 一致（矛盾只能由 revision_id 引起）"
    )
    assert (
        hashlib.sha256(prompt_bytes).hexdigest() == manifest.get("prompt_yaml_sha256")
    ), (
        "fixture 前置事实失败：改写后 prompt_yaml_sha256 必须与 prompt.yaml "
        "文件字节一致"
    )
    if identity_mutation in ("manifest_revision_mismatch", "both_revisions_mismatch"):
        assert manifest.get("revision_id") != HISTORY_SIBLING_SOURCE_ID, (
            "fixture 前置事实失败：manifest 侧矛盾必须真实生效"
        )
    if identity_mutation in ("prompt_revision_mismatch", "both_revisions_mismatch"):
        assert prompt.get("revision_id") != HISTORY_SIBLING_SOURCE_ID, (
            "fixture 前置事实失败：prompt.yaml 侧矛盾必须真实生效"
        )
    if identity_mutation == "manifest_revision_mismatch":
        assert prompt.get("revision_id") == HISTORY_SIBLING_SOURCE_ID, (
            "fixture 前置事实失败：单侧矛盾下另一文件身份字段必须保持与 "
            "source_legacy_id 一致"
        )
    if identity_mutation == "prompt_revision_mismatch":
        assert manifest.get("revision_id") == HISTORY_SIBLING_SOURCE_ID, (
            "fixture 前置事实失败：单侧矛盾下另一文件身份字段必须保持与 "
            "source_legacy_id 一致"
        )

    before = _snapshot_tree(tmp_path)

    # ---- 行为 1：整批 fail-closed（不得在错误身份下构建文档）。----
    _expect_history_summary_fail_closed(build, tmp_path, [entry])

    # ---- 行为 2：零写入 —— 全树逐字节不变。----
    assert _snapshot_tree(tmp_path) == before, (
        "身份矛盾 fail-closed 拒绝必须零写入：全树快照逐字节不变（不写 "
        "history-summary 文件、不创建 records/ 或任何目标条目、不改 "
        "legacy 源）"
    )
    assert not (tmp_path / "records").exists(), (
        "身份矛盾拒绝路径不得创建 records/ 或任何正式对象条目"
    )
    assert not (tmp_path / "docs").exists(), (
        "身份矛盾拒绝路径不得写入 history-summary 文件（文档只经返回值给出）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"身份矛盾拒绝路径不得落盘任何 history-summary 命名文件：发现 {path}"
        )

    # ---- 行为 3：不就地修改传入 entry。----
    assert entry == expected_entry, (
        "全程不得就地改写传入 entry（H4 输入事实保持不变）"
    )

# ---------------------------------------------------------------------------
# H5：history-summary —— prepare-only run 历史条目不得成为训练事实
#（M1b，先写测试，不改 production）
# ---------------------------------------------------------------------------

# M0 source-inventory.yaml training_machine_run_evidence.prepare_only_runs
# 的两个真实 run（run_id 含 "/"；训练机只读调查 training_observed：
# "发现 input 资料；v1 另有 prepared-config-untrained；本次未发现权重"，
# migration_meaning："按准备资料调查，不能导入为 completed 训练，也不能
# 保留为模型"）。本切片声明 v1 一条 entry；v2 保持未声明 sibling。
PREPARE_ONLY_RUN_V1_ID = "v4.1-prompt-concise-v1/seed3411"
PREPARE_ONLY_RUN_V2_ID = "v4.1-prompt-concise-v2/seed3411"

# M0 training_machine_run_evidence.weight_runs 首条真实 run（训练机只读
# 调查："fold0 有 adapter 与 10 个 merged 分片，有 evidence_archive"）。
# 作为未声明 sibling 写入 fixture：扫描 workspace/runs/ 或从 sibling 取
# 权重事实的实现必被本切片捕获。
WEIGHT_RUN_SIBLING_ID = "v4.1-phase2-source-aware-v1-seed3407"

# Spec「核心历史信息的最低内容」核心训练参数字段族：seed、学习率
# （learning_rate）、epoch 或训练步数（epochs）、有效 batch size
# （effective_batch_size）、优化器（optimizer）、精度（precision）、
# LoRA rank/alpha/target modules（lora_rank / lora_alpha /
# lora_target_modules）。prepare-only run 无训练执行事实，M0 对这两个
# run 未记录任何参数值，这些参数必须以字段级 unknown 进入文档。
PREPARE_ONLY_CORE_TRAIN_PARAM_FACTS = (
    "seed",
    "learning_rate",
    "epochs",
    "effective_batch_size",
    "optimizer",
    "precision",
    "lora_rank",
    "lora_alpha",
    "lora_target_modules",
)

# 参数名反走私 token：facts 内名字含这些 token 的事实一律不得携带已知
# 值（防止实现改用 configured_seed / num_train_epochs / train_steps 等
# 名字把准备资料中的 planned 参数登记为训练事实）。
_H5_PARAM_NAME_TOKENS = (
    "seed",
    "learning_rate",
    "epoch",
    "step",
    "batch",
    "optim",
    "precision",
    "lora",
)

# 训练事实存在性声明 token：summary entry 内任何键名携带这些 token 的
# 位置不得声明权重 / 模型 / 训练完成 / 评测 / 通过的存在性（允许字段
# 级 unknown 形态、None / False / 空值等显式非存在记录）。
_H5_CLAIM_KEY_TOKENS = (
    "weight",
    "adapter",
    "merged",
    "checkpoint",
    "safetensors",
    "model",
    "completed",
    "passed",
    "eval",
)

# 权重文件名 token（fixture 前置事实用：已声明 prepare-only run 目录内
# 不得出现任何权重命名文件；weight run sibling 内必须出现）。
_H5_WEIGHT_FILE_NAME_TOKENS = ("adapter", "merged", "checkpoint", "safetensors")


def _write_prepare_only_runs_layout(root: Path) -> None:
    """H5 fixture：镜像 M0 training_machine_run_evidence 的 runs 布局。

    - 已声明 prepare-only run ``v4.1-prompt-concise-v1/seed3411``：只有
      input 资料（``inputs/``：dataset_info.json + datasets/
      seed_3411.json + datasets/fold_0_validation.json）与
      ``prepared-config-untrained/``（planned train.yaml + status
      "prepared" 的 manifest.json，结构对齐
      ``finetune/train_prepare_run.py`` 写出的 prepared experiment
      manifest；planned 输出路径指向尚未物化的 adapter/merged 位置），
      无任何权重命名文件 —— M0："发现 input 资料；v1 另有
      prepared-config-untrained；本次未发现权重"；
    - 未声明 sibling prepare-only run ``v4.1-prompt-concise-v2/
      seed3411``：仅 input 资料（M0 第二个 prepare-only run）；
    - 未声明 sibling weight run ``v4.1-phase2-source-aware-v1-seed3407``：
      ``fold0/`` 下 adapter + 10 个 merged 分片 + ``evidence_archive/``
      （合成字节，镜像 M0 weight_runs 首条观察）。

    字段值合成（非真实权重/资料），结构与事实字段对齐 M0 证据；planned
    参数与 planned 输出路径都是准备资料，不是训练执行事实。
    """
    runs_root = root / "workspace" / "runs"

    def _write_inputs(run_dir: Path, run_id: str) -> None:
        inputs_dir = run_dir / "inputs"
        (inputs_dir / "datasets").mkdir(parents=True, exist_ok=True)
        (inputs_dir / "dataset_info.json").write_bytes(
            _fixture_pretty_json_bytes(
                {
                    "schema_version": "tensile-input-refs/v4.1-fixture",
                    "run_id": run_id,
                    "release_id": "v4.1.0-760050fad303",
                }
            )
        )
        for split_file, row_count in (("seed_3411", 3), ("fold_0_validation", 2)):
            (inputs_dir / "datasets" / f"{split_file}.json").write_bytes(
                _fixture_pretty_json_bytes(
                    {
                        "run_id": run_id,
                        "split_file": split_file,
                        "row_count": row_count,
                    }
                )
            )

    _write_inputs(runs_root / PREPARE_ONLY_RUN_V1_ID, PREPARE_ONLY_RUN_V1_ID)
    _write_inputs(runs_root / PREPARE_ONLY_RUN_V2_ID, PREPARE_ONLY_RUN_V2_ID)

    experiment_dir_name = PREPARE_ONLY_RUN_V1_ID.replace("/", "-")
    config_dir = runs_root / PREPARE_ONLY_RUN_V1_ID / "prepared-config-untrained"
    config_dir.mkdir(parents=True, exist_ok=True)
    planned_config = {
        "model_name_or_path": "models/minicpm-v-4.5",
        "output_dir": f"finetune/experiments/{experiment_dir_name}/adapter",
        "seed": 3411,
        "learning_rate": 5e-05,
        "num_train_epochs": 1.0,
        "per_device_train_batch_size": 2,
        "gradient_accumulation_steps": 8,
        "optimizer": "adamw_torch",
        "bf16": True,
        "lora_rank": 8,
        "lora_alpha": 16,
        "lora_target": "all",
    }
    config_bytes = yaml.safe_dump(
        planned_config, allow_unicode=True, sort_keys=False
    ).encode("utf-8")
    (config_dir / "train.yaml").write_bytes(config_bytes)
    (config_dir / "manifest.json").write_bytes(
        _fixture_pretty_json_bytes(
            {
                "schema_version": "tensile-vlm-v4.1-semantic-experiment/v1",
                "immutable": True,
                "experiment_id": experiment_dir_name,
                "status": "prepared",
                "seed": 3411,
                "paths": {
                    "input": f"workspace/runs/{PREPARE_ONLY_RUN_V1_ID}/inputs",
                    "adapter": f"finetune/experiments/{experiment_dir_name}/adapter",
                    "merged": f"finetune/experiments/{experiment_dir_name}/merged",
                },
                "train_config": {
                    "path": "train.yaml",
                    "sha256": hashlib.sha256(config_bytes).hexdigest(),
                },
                "expected_optimizer_steps": 1125,
            }
        )
    )

    weight_fold_dir = runs_root / WEIGHT_RUN_SIBLING_ID / "fold0"
    (weight_fold_dir / "adapter").mkdir(parents=True, exist_ok=True)
    (weight_fold_dir / "adapter" / "adapter_model.safetensors").write_bytes(
        f"<synthetic adapter bytes: {WEIGHT_RUN_SIBLING_ID}>".encode("utf-8")
    )
    (weight_fold_dir / "merged").mkdir(parents=True, exist_ok=True)
    for shard_index in range(1, 11):
        (
            weight_fold_dir
            / "merged"
            / f"model-{shard_index:05d}-of-00010.safetensors"
        ).write_bytes(
            (
                f"<synthetic merged shard {shard_index}/10: "
                f"{WEIGHT_RUN_SIBLING_ID}>"
            ).encode("utf-8")
        )
    (runs_root / WEIGHT_RUN_SIBLING_ID / "evidence_archive").mkdir(
        parents=True, exist_ok=True
    )


def _confirmed_prepare_only_run_entry() -> dict[str, Any]:
    """逐字段镜像 M0 证据结构的已确认 prepare_only_run entry（H5 输入）。

    kind 为 M0 对齐的 ``prepare_only_run``（source-inventory
    training_machine_run_evidence.prepare_only_runs 的分组名）；
    source_legacy_id 为 M0 记录的原始 run ID（含 "/"）；status
    ``user_confirmed``（用户确认该 run 仅进 history-summary、不迁移、
    不分配任何新正式身份），由入口自身读取该字段消费；source_verified
    保持 ``training_observed`` 事实分级（M0 训练机只读调查），与确认
    状态分离。entry 不携带 candidate_target_identity / passed。
    """
    return {
        "kind": "prepare_only_run",
        "source_legacy_id": PREPARE_ONLY_RUN_V1_ID,
        "role": "prepare-only run（M0 prepare_only_runs：发现 input 资料；未发现权重）",
        "source_verified": "training_observed",
        "history_only": True,
        "status": "user_confirmed",
        "confirmed_by_user_date": "2026-09-07",
        "notes": (
            "M0 source-inventory prepare_only_runs：按准备资料调查，不能导入为 "
            "completed 训练，也不能保留为模型。"
        ),
    }


def _assert_h5_fact_is_unknown(fact: Any, *, name: str, run_id: str) -> None:
    """断言 prepare-only run 事实为 H4 同口径字段级 unknown 形态。"""
    assert isinstance(fact, Mapping), (
        f"prepare-only run 的事实 {name} 必须以 mapping 形态进入字段级 unknown"
        f"（携带 unknown_reason / attempted_source）：实际 {type(fact).__name__!r}"
    )
    reason = fact.get("unknown_reason")
    assert isinstance(reason, str) and reason.strip(), (
        f"prepare-only run 的事实 {name} 必须携带非空字符串 unknown_reason"
        f"（prepare-only run 无训练执行事实，缺失原因不得静默）：实际 {reason!r}"
    )
    attempted = fact.get("attempted_source")
    attempted_text = " ".join(_document_string_fragments(attempted))
    assert attempted_text.strip(), (
        f"prepare-only run 的事实 {name} 必须携带非空 attempted_source（指回声明"
        f"的 run 源）：实际 {attempted!r}"
    )
    assert run_id in attempted_text, (
        f"prepare-only run 的事实 {name} 的 attempted_source 必须指回声明的 run"
        f"源（{run_id}）：实际 {attempted_text!r}"
    )
    if "value" in fact:
        assert fact["value"] is None, (
            f"prepare-only run 的事实 {name} 不得携带非 None 的 value（准备资料"
            f"不是训练执行事实，不得登记为已知值）：实际 {fact['value']!r}"
        )


def _h5_value_claims_existence(item: Any) -> bool:
    """判定 claim-token 键下的值是否构成存在性 / 完成 / 通过声明。

    允许的形态（返回 False）：None / False / 空串 / 空列表 / 空 mapping、
    字段级 unknown 形态 mapping、value 为 None/False 的非存在性记录；
    其余（True、非零数、非空字符串、非空列表、携带非 None/False value
    的 mapping）一律视为声明。
    """
    if item is None or item is False:
        return False
    if isinstance(item, Mapping):
        return "value" in item and item["value"] not in (None, False)
    if isinstance(item, str):
        return bool(item.strip())
    if isinstance(item, (list, tuple)):
        return len(item) > 0
    return True


def _assert_h5_no_training_fact_claims(value: Any, path: str) -> None:
    """递归断言 summary entry 内不存在任何训练事实存在性声明。

    任何键名携带 claim token（weights / adapter / merged / checkpoint /
    safetensors / model / completed / passed / eval 命名族）的位置不得
    声明权重、模型、训练完成、评测或通过状态的存在性：值只能为
    None / False / 空值 / 字段级 unknown 形态或 value 为 None/False 的
    非存在性记录；自由文本不得放在这些键下（避免把"未发现"之类的
    描述伪装成结构性事实）。
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            child_path = f"{path}.{key}"
            if any(token in key_text for token in _H5_CLAIM_KEY_TOKENS):
                assert not _h5_value_claims_existence(item), (
                    f"prepare-only run 的 summary entry 不得声明训练事实：键 "
                    f"{child_path} 携带存在性 / 完成 / 通过值 {item!r}（权重、"
                    "模型、训练完成、评测或通过状态不得伪造；相关字段只能以"
                    "字段级 unknown 或显式非存在记录）"
                )
            _assert_h5_no_training_fact_claims(item, child_path)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_h5_no_training_fact_claims(item, f"{path}[{index}]")


def _assert_h5_not_grouped_as_weight_run(
    document: Mapping[str, Any], run_id: str
) -> None:
    """断言 prepare-only run 不得出现在任何"有权重 run"分组下。

    文档内任何"有权重 run"分组键（键名同时含 weight 与 run，如
    weight_runs / runs_with_weights）的子树不得引用该 run ID（字段级
    unknown 形态的事实值除外 —— 其 attempted_source 合法指回声明 run
    源，不构成分组归属）。文档无此类分组键时本断言空转，entry 级分类
    由 kind / training_status 断言钉定。
    """

    def _visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key).lower()
                child_path = f"{path}.{key}"
                if "weight" in key_text and "run" in key_text and not (
                    isinstance(item, Mapping)
                    and isinstance(item.get("unknown_reason"), str)
                ):
                    group_text = " ".join(_document_string_fragments(item))
                    assert run_id not in group_text, (
                        f"prepare-only run {run_id!r} 不得出现在有权重 run 分组 "
                        f"{child_path} 下（prepare-only run 不是训练事实，不得"
                        "与有权重 run 归入同一分组）"
                    )
                _visit(item, child_path)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                _visit(item, f"{path}[{index}]")

    _visit(document, "document")


def test_confirmed_prepare_only_run_entry_not_registered_as_training_fact(
    tmp_path: Path,
) -> None:
    r"""已确认 prepare-only run 历史条目不得成为训练事实（H5，M1b
    history-summary prepare-only run 切片，先写测试，不改 production）。

    H5 behavior —— 对已确认 prepare-only run 历史条目（kind
    ``prepare_only_run``、source_legacy_id
    ``v4.1-prompt-concise-v1/seed3411``、status ``user_confirmed``；M0
    source-inventory training_machine_run_evidence.prepare_only_runs：
    训练机只读调查"发现 input 资料；v1 另有 prepared-config-untrained；
    本次未发现权重"，migration_meaning"按准备资料调查，不能导入为
    completed 训练，也不能保留为模型"）调用
    ``build_history_summary(root, [entry])`` 必须：
    1. 返回 history-summary 文档（history_summary_schema ==
       tensile-migration/history-summary/v1），不得 fail-closed 拒绝该
       kind 使 entry 消失 —— prepare-only run 是允许的历史查询记录
       （Spec：资料不完整的记录仍可用于历史查询，但不能伪装成可重现
       或可部署模型），fail-closed 拒绝只能保留给 H2/H3 的非法输入域；
    2. entry 输出 ``training_status == "prepared_only"``：准备资料不是
       训练执行事实，不得输出 completed / trained 等完成语义；
    3. 不声明任何权重存在：entry 内任何键名携带 weights / adapter /
       merged / checkpoint / safetensors 命名族 token 的位置不得声明
       存在性值（允许字段级 unknown 形态或 None / False 显式非存在；
       M0：本次未发现权重，准备资料中的 planned adapter / merged 输出
       路径不是权重事实）；
    4. 核心训练参数（Spec「核心历史信息的最低内容」：seed /
       learning_rate / epochs / effective_batch_size / optimizer /
       precision / lora_rank / lora_alpha / lora_target_modules）全部以
       H4 同口径字段级 unknown 进入 facts：非空 unknown_reason（说明仅
       发现准备资料、无训练执行记录）+ 指回声明 run 源的
       attempted_source，不携带非 None value —— prepared-config-
       untrained 中的 planned 参数（seed 3411 等）是准备资料，不是
       训练执行事实，不得登记为已知值；任何名字含参数 token
       （seed / learning_rate / epoch / step / batch / optim /
       precision / lora）的事实同样不得携带已知值（反走私：不得改用
       configured_seed / num_train_epochs / train_steps 等名字登记）；
    5. 不出现在"有权重 run"分组：entry 分类保持 kind
       ``prepare_only_run`` + training_status ``prepared_only``；文档内
       任何"有权重 run"分组键（键名同时含 weight 与 run）的子树不得
       引用该 run ID；
    6. 不产生任何 model 概念条目：entries 恰含声明的一条（不得为该
       run 派生 model 等其他概念条目，也不得扫描 runs 目录生成
       sibling 条目），文档内任何字符串值都不是
       ``<kind>-v<协议>-r<N>`` 正式身份（M0 model_train_eval_history
       scope_note：不为复用导出器伪造 completed Run / 模型）；
    7. 保留原始 run ID 和来源：original_id ==
       v4.1-prompt-concise-v1/seed3411（含 "/" 的原始 legacy run ID）；
       unknown 事实的 attempted_source 指回声明 run 源；
    8. 不伪造训练完成、权重、评测或通过状态：entry 内任何键名携带
       completed / passed / eval / model 命名族 token 的位置不得声明
       完成 / 通过 / 评测结果 / 模型身份值；
    9. 纯构建零写入：全树快照逐字节不变（不写 history-summary 文件、
       不创建 records/ 或任何目标条目、不改 legacy 源树 —— 含
       workspace/runs/ 准备资料与 pipeline/prompt_registry/）；
       不就地修改传入 entry；
    10. 合法已确认 prompt_history entry 对照仍正常构建（H1 正向不回
        归，反向门不得因新增 run 分类而误伤既有合法 entry）。

    fixture：_write_prepare_only_runs_layout 镜像 M0
    training_machine_run_evidence 的 workspace/runs/ 布局 ——
    已声明 prepare-only run 只有 inputs/ 与 prepared-config-untrained/
    （无任何权重命名文件）；未声明 sibling prepare-only run
    （v4.1-prompt-concise-v2/seed3411，仅 input 资料）与未声明 sibling
    weight run（v4.1-phase2-source-aware-v1-seed3407/fold0/，adapter +
    10 个 merged 分片 + evidence_archive，合成字节）。加上
    _write_full_history_prompt_registry 的完整三条目 legacy prompt
    registry（合法对照与 prompt sibling 钉死）。entry 输入
    _confirmed_prepare_only_run_entry 逐字段镜像 M0 证据结构（status
    user_confirmed 由入口自身读取消费；source_verified 保持
    training_observed 事实分级）。

    RED Gate 设计（H5）：build_history_summary 入口已存在（H1 已
    GREEN），RED 不经入口缺失分支给出。当前实现不按 kind 分流（对
    任意非空 kind 一律按 prompt registry 源构建 prompt 形态 entry）：
    对本用例 entry 静默构建无 training_status、无核心训练参数事实的
    prompt 形态文档（六个 prompt 事实全部 unknown，attempted_source
    指向不存在的 pipeline/prompt_registry/<run_id>/）—— 由
    training_status 断言的显式 AssertionError 钉出"prepare-only run
    历史条目行为缺失"。若实现改为对该 kind fail-closed 拒绝（任务允许
    的另一缺陷形态），拒绝经本用例 try/except 转译为显式行为
    AssertionError（原始域错误经 cause 链保留）钉出同一 RED 结论，不
    让原始异常直接充当 RED。fixture 前置事实与合法对照全部真实执行
    后才失败。

    捕获的合理但错误实现：
    - 对 prepare_only_run kind fail-closed 拒绝（entry 消失）-> 转译后
      的显式 AssertionError 判失败；
    - 不输出 training_status / 输出 completed 等完成语义（当前实现形
      态）-> 行为 2 断言失败；
    - 登记权重存在（从 weight run sibling 取 adapter/merged 分片、把
      prepared manifest 的 planned 输出路径当权重事实、weights: true）
      -> 行为 3 的 claims 扫描失败；
    - 把 prepared-config-untrained 的 planned 参数登记为已知训练参数
      （seed: 3411 等，含改用 configured_seed / num_train_epochs /
      train_steps 等名字）-> 行为 4 的核心参数 unknown / 参数 token
      反走私断言失败；
    - 把 entry 分到有权重 run 分组 -> 行为 5 断言失败；
    - 派生 model 概念条目 / 分配正式身份 -> 行为 6 断言失败；
    - 扫描 workspace/runs/ 生成 sibling 条目或取 sibling 事实 ->
      entries 数量 / sibling ID 断言失败；
    - 构建路径写盘（history-summary 文件、records/、staging、改准备
      资料）-> 全树快照对比失败；
    - 丢失原始 run ID（含 "/" 丢失）-> original_id 断言失败；
    - 就地改写传入 entry -> 输入不变断言失败；
    - 对合法 prompt_history entry 也拒绝或改变 H1 行为（如按 kind 白
      名单拒绝 prompt_history）-> 合法对照断言失败。

    多 entry 批量（两个 prepare-only run 同批）、weight-run/eval/model
    历史条目、prepare-only run 的非法输入反向（夹带 passed /
    candidate_target_identity 的 run entry 对 H2/H3 门的适用）、
    history-summary 文件写入与 CLI 不在本切片。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（H5 仅新增用例
      与配套 helper/常量及模块 docstring 清单条目，不改 production）。
    - 命令（新 selector）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_confirmed_prepare_only_run_entry_not_registered_as_training_
      fact``
    - RED failure signature：恰一个失败用例（本 selector），失败为
      行为 2 的 AssertionError（training_status 实际 None !=
      'prepared_only'）；fixture 前置事实、入口解析与合法对照全部
      不失败；不出现 ModuleNotFoundError / ImportError /
      AttributeError 或原始异常直接充当 RED 结论。
    - 既有 selector 复跑（回归钉）：H1 selector（-k
      test_confirmed_prompt_history_entry_builds_history_summary_
      document_without_writes）通过；全 migration 文件 RED 时点：
      105 passed + 1 failed（失败恰为本 selector）。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （与 H1–H4 binding 记录一致，``[tool.pytest.ini_options] testpaths /
      pythonpath`` 解析依赖该文件）。
    """
    _write_full_history_prompt_registry(tmp_path)
    _write_prepare_only_runs_layout(tmp_path)
    declared_run_dir = tmp_path / "workspace" / "runs" / PREPARE_ONLY_RUN_V1_ID

    # ---- fixture 前置事实（对齐 M0 证据）：已声明 prepare-only run
    #      只有输入/准备资料；planned 参数真实存在（使"核心参数
    #      unknown"断言非空洞）；v2 / weight run sibling 存在；prompt
    #      registry 完整（合法对照依赖）；目标根不存在。----
    assert declared_run_dir.is_dir(), (
        "fixture 前置事实失败：已声明 prepare-only run 目录必须存在"
    )
    declared_files = [path for path in declared_run_dir.rglob("*") if path.is_file()]
    assert declared_files, (
        "fixture 前置事实失败：已声明 prepare-only run 目录必须携带输入/准备资料"
    )
    for path in declared_files:
        assert not any(
            token in path.name.lower() for token in _H5_WEIGHT_FILE_NAME_TOKENS
        ), (
            f"fixture 前置事实失败：已声明 prepare-only run 目录必须只有输入/"
            f"准备资料，不得含权重命名文件：发现 {path}"
        )
    prepared_manifest_file = (
        declared_run_dir / "prepared-config-untrained" / "manifest.json"
    )
    prepared_manifest = json.loads(prepared_manifest_file.read_text(encoding="utf-8"))
    assert prepared_manifest.get("status") == "prepared", (
        "fixture 前置事实失败：prepared-config-untrained manifest 必须声明 "
        "status: prepared（准备资料，非训练完成）"
    )
    planned_config = yaml.safe_load(
        (declared_run_dir / "prepared-config-untrained" / "train.yaml").read_bytes()
    )
    assert planned_config.get("seed") == 3411 and "learning_rate" in planned_config, (
        "fixture 前置事实失败：准备资料必须真实携带 planned 参数（使核心参数 "
        "unknown 断言非空洞：实现不得把 planned 参数登记为训练事实）"
    )
    assert not (tmp_path / "finetune").exists(), (
        "fixture 前置事实失败：planned adapter/merged 输出位置必须未物化"
        "（prepare-only run 本次未发现权重）"
    )
    v2_run_dir = tmp_path / "workspace" / "runs" / PREPARE_ONLY_RUN_V2_ID
    assert v2_run_dir.is_dir() and any(v2_run_dir.rglob("*.json")), (
        "fixture 前置事实失败：第二个 prepare-only run（未声明 sibling）必须以"
        "input 资料存在"
    )
    weight_fold_dir = (
        tmp_path / "workspace" / "runs" / WEIGHT_RUN_SIBLING_ID / "fold0"
    )
    assert (weight_fold_dir / "adapter" / "adapter_model.safetensors").is_file() and (
        any((weight_fold_dir / "merged").glob("*.safetensors"))
    ), (
        "fixture 前置事实失败：weight run sibling 必须真实携带 adapter 与 "
        "merged 分片（钉死扫描 runs 目录 / 从 sibling 取权重事实的实现）"
    )
    for prompt_source_id in (
        HISTORY_SIBLING_SOURCE_ID,
        CONFIRMED_PROMPT_SOURCE_ID,
        _THIRD_REGISTRY_SOURCE_ID,
    ):
        prompt_dir = tmp_path / "pipeline" / "prompt_registry" / prompt_source_id
        assert (prompt_dir / "manifest.json").is_file() and (
            prompt_dir / "prompt.yaml"
        ).is_file(), (
            f"fixture 前置事实失败：legacy prompt registry 条目 {prompt_source_id} "
            "必须完整（合法对照依赖）"
        )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    entry = _confirmed_prepare_only_run_entry()
    expected_entry = _confirmed_prepare_only_run_entry()

    # ---- 合法对照：合法已确认 prompt_history entry 仍正常构建（H1 正向
    #      不回归；新增 run 分类不得反向过宽）。----
    _assert_legal_history_entry_still_builds(build, tmp_path)

    before = _snapshot_tree(tmp_path)

    # ---- 行为 1：已确认 prepare_only_run entry 必须构建文档，不得
    #      fail-closed 拒绝 kind 使 entry 消失。----
    try:
        document = build(tmp_path, [entry])
    except Exception as exc:
        raise AssertionError(
            "已确认 prepare_only_run 历史条目必须进入 history-summary 文档"
            "（prepare-only run 是允许的历史查询记录，不得 fail-closed 拒绝使"
            " entry 消失；prepare-only run 历史条目行为缺失）：实际抛出 "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        ) from exc
    assert isinstance(document, Mapping), (
        "build_history_summary 必须返回 history-summary 文档（mapping）：实际 "
        f"{type(document).__name__!r}"
    )
    assert (
        document.get("history_summary_schema")
        == "tensile-migration/history-summary/v1"
    ), (
        "history-summary 文档必须声明 history_summary_schema == "
        "'tensile-migration/history-summary/v1'：实际 "
        f"{document.get('history_summary_schema')!r}"
    )
    document_entries = document.get("entries")
    assert isinstance(document_entries, list), (
        "history-summary 文档的 entries 必须是 list：实际 "
        f"{type(document_entries).__name__!r}"
    )
    assert len(document_entries) == 1, (
        "history-summary 文档必须恰含声明的一条 entry（不得扫描 runs 目录生成"
        " sibling 条目，也不得为 prepare-only run 派生 model 等其他概念条目）："
        f"实际 {len(document_entries)} 条"
    )
    summary_entry = document_entries[0]
    assert isinstance(summary_entry, Mapping), (
        "history-summary entry 必须是 mapping：实际 "
        f"{type(summary_entry).__name__!r}"
    )

    # ---- 行为 6/7：entries 恰一条；保留原始 run ID、分类与来源结构。----
    assert summary_entry.get("original_id") == PREPARE_ONLY_RUN_V1_ID, (
        "prepare-only run entry 必须保留 original_id（含 '/' 的原始 legacy "
        f"run ID）：实际 {summary_entry.get('original_id')!r}"
    )
    assert summary_entry.get("kind") == "prepare_only_run", (
        "prepare-only run entry 必须保持声明的 kind（prepare_only_run，M0 "
        f"prepare_only_runs 对齐分类，不得归入有权重 run 分类）：实际 "
        f"{summary_entry.get('kind')!r}"
    )
    assert summary_entry.get("history_only") is True, (
        "prepare-only run entry 必须标记 history_only: true：实际 "
        f"{summary_entry.get('history_only')!r}"
    )
    assert summary_entry.get("formal_identity") == "none", (
        "prepare-only run entry 必须标记 formal_identity: none（不分配新正式"
        f"身份）：实际 {summary_entry.get('formal_identity')!r}"
    )
    entry_id = summary_entry.get("entry_id")
    assert isinstance(entry_id, str) and entry_id, (
        "prepare-only run entry 必须携带非空字符串 entry_id（文档内 slug）："
        f"实际 {entry_id!r}"
    )
    assert not is_valid_version_id(entry_id), (
        "entry_id 必须是文档内 slug，不得是 <kind>-v<协议>-r<N> 正式身份："
        f"实际 {entry_id!r}"
    )

    # ---- 行为 2：training_status: prepared_only。----
    assert summary_entry.get("training_status") == "prepared_only", (
        "prepare-only run 历史条目必须输出 training_status == 'prepared_only'"
        "（准备资料不是训练执行事实，不得输出 completed 等完成语义，也不得缺"
        "失训练状态分类）：实际 "
        f"{summary_entry.get('training_status')!r}"
    )

    # ---- 行为 4：核心训练参数全部字段级 unknown（planned 参数不得登记
    #      为训练事实），参数名反走私。----
    facts = summary_entry.get("facts")
    assert isinstance(facts, Mapping) and facts, (
        "prepare-only run entry 必须携带非空 facts（核心训练参数以字段级 "
        f"unknown 进入文档，不是无事实）：实际 {facts!r}"
    )
    for name in PREPARE_ONLY_CORE_TRAIN_PARAM_FACTS:
        assert name in facts, (
            f"prepare-only run 的 facts 必须包含核心训练参数 {name}（Spec「核心"
            f"历史信息的最低内容」，缺失资料进入字段级 unknown 而不是删字段）："
            f"实际键集 {sorted(facts)}"
        )
        _assert_h5_fact_is_unknown(
            facts[name], name=name, run_id=PREPARE_ONLY_RUN_V1_ID
        )
    for name, fact in facts.items():
        if any(token in str(name).lower() for token in _H5_PARAM_NAME_TOKENS):
            _assert_h5_fact_is_unknown(
                fact, name=name, run_id=PREPARE_ONLY_RUN_V1_ID
            )

    # ---- 行为 3/8：不声明任何权重存在；不伪造训练完成、评测或通过状态。----
    _assert_h5_no_training_fact_claims(summary_entry, "entry")

    # ---- 行为 5：不出现在"有权重 run"分组。----
    _assert_h5_not_grouped_as_weight_run(document, PREPARE_ONLY_RUN_V1_ID)

    # ---- 行为 6：不产生任何 model 概念条目 / 不分配任何新正式身份。----
    all_strings = _document_string_fragments(document)
    for fragment in all_strings:
        assert not is_valid_version_id(fragment), (
            "history-summary 文档内不得出现任何 <kind>-v<协议>-r<N> 正式身份"
            f"（prepare-only run 不分配 model/train/eval 等任何新正式身份）："
            f"实际出现 {fragment!r}"
        )

    # ---- 不扫描 sibling：未声明 run 与 prompt sibling 的 ID 不得进入
    #      文档任何字符串。----
    for sibling_id in (
        PREPARE_ONLY_RUN_V2_ID,
        WEIGHT_RUN_SIBLING_ID,
        HISTORY_SIBLING_SOURCE_ID,
        CONFIRMED_PROMPT_SOURCE_ID,
        _THIRD_REGISTRY_SOURCE_ID,
    ):
        assert not any(sibling_id in fragment for fragment in all_strings), (
            f"未声明 sibling {sibling_id} 不得进入 history-summary 文档的任何"
            "字符串（实现必须按声明 entry 定位源，不得扫描 legacy 目录或从"
            "sibling 取内容）"
        )

    # ---- 行为 9：纯构建零写入 —— 全树逐字节不变（legacy 源不变、不写
    #      history-summary 文件、不创建任何目标条目）。----
    assert _snapshot_tree(tmp_path) == before, (
        "build_history_summary 必须纯构建零写入：全树快照逐字节不变"
        "（不写 history-summary 文件、不创建 records/ 或任何目标条目、不改 "
        "legacy 源树含 workspace/runs/ 准备资料）"
    )
    assert not (tmp_path / "records").exists(), (
        "纯构建不得创建 records/ 或任何正式对象条目（不分配新正式身份）"
    )
    assert not (tmp_path / "docs").exists(), (
        "纯构建不得写入 history-summary 文件（本切片只经返回值给出文档）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"纯构建不得落盘任何 history-summary 命名文件：发现 {path}"
        )

    # ---- 不就地修改传入 entry。----
    assert entry == expected_entry, (
        "全程不得就地改写传入 entry（H5 输入事实保持不变）"
    )


# ---------------------------------------------------------------------------
# H6a：history-summary —— 单条已确认 weight_run entry 的历史字段提取
#（M1b，先写测试，不改 production）
# ---------------------------------------------------------------------------
#
# H6a behavior（本切片，主 Agent 选定，M1b history-summary weight run
# 第一切片，先写测试，不改 production）—— 对已确认 weight run 历史条
# 目只登记有证据的事实（Spec：简明历史记录不冒充完整正式运行或质量通
# 过；M0 evidence：source-inventory.yaml
# training_machine_run_evidence.weight_runs 首条
# v4.1-phase2-source-aware-v1-seed3407，训练机只读观察"fold0 有 adapter
# 与 10 个 merged 分片，有 evidence_archive"；notes："run 目录存在不等
# 于完成训练……全部未验证权重完整性与哈希"；object-mapping
# model_train_eval_history：不能当作 completed 训练）：
# 1. entry 必须进入 history-summary 文档，不得 fail-closed 拒绝使
#    entry 消失（M0 把六个有权重 run 列为仅进 history-summary 的允许
#    历史记录，用户已确认 history_decision）；
# 2. 保留原始 run ID 与分类：original_id 保留 M0 记录的原始 run ID；
#    kind 保持 "weight_run"（有权重 run 分类，不得误归 prepare_only_
#    run 或 prompt 形态）；
# 3. training_status 为 evidence-derived "weights_observed"：M0 观察
#    到权重存在，训练完成状态被 M0 明确排除（"run 目录存在不等于完成
#    训练"、"不能当作 completed 训练"）—— 不得输出 completed，也不得
#    输出 not_completed 等同样无证据的负向声明（"不等于完成"不等于
#    "未完成"）；唯一有证据的分类是"观察到权重存在"本身（M0 weight_
#    runs 分组名 / "有 adapter 与 10 个 merged 分片"）；
# 4. M0 结构观察分解出的已知事实（Spec「模型身份」最小内容：fold 或
#    全量范围 + 权重位置及存在性）：fold_scope == "fold0"、
#    adapter_present is True、merged_present is True（{value, source}
#    形态，source 为非空 mapping 且指回声明 run 源；权重事实的
#    source 须指回观察到它们的 fold0 位置）；
# 5. 核心训练参数（Spec「核心训练参数」九字段族，与 H5 同族）全部字
#    段级 unknown：M0 未记录 weight run 的任何核心训练参数值，声明
#    run 的 evidence_archive 内容未经 M0 核实（调查记录："归档尚未证
#    明完整"），fixture 中声明 run 内不存在任何参数来源文件；unknown
#    事实携带非空 unknown_reason 与指回声明 run 源的
#    attempted_source，不携带非 None value；参数名反走私：任何名字
#    含参数 token 的事实不得携带已知值（sibling prepare-only run 的
#    planned seed 3411 与 sibling 归档 manifest 的合成参数不得进入）；
# 6. 不声明训练完成、通过、评测结果、model 正式身份或权重完整性 /
#    哈希验证：completed / passed / eval / model / verif / hash /
#    integrity / checksum / sha 命名族键不得携带存在性值（M0：全部未
#    验证权重完整性与哈希；不得把历史 summary 转成 passed；不为 run
#    分配任何新正式身份）。与 H5 相反，weights / adapter / merged /
#    checkpoint / safetensors 命名族键允许携带存在性值 —— 权重存在
#    是本 run 的 M0 观察事实；
# 7. 不扫描 sibling：entries 恰含声明的一条；未声明 sibling（两个
#    prepare-only run、run 根结构 weight run、三个 prompt registry
#    条目）的 ID 不得进入文档任何字符串；不取 sibling 结构事实
#    （run 根结构 sibling 无 fold0/，取错结构必被 fold_scope 断言捕
#    获）；
# 8. 不分配任何新正式身份：文档内任何字符串值都不是
#    <kind>-v<协议>-r<N> 正式身份；
# 9. 纯构建零写入：全树快照逐字节不变（不写 history-summary 文件、
#    不创建 records/ 或任何目标条目、不改 legacy 源树含
#    workspace/runs/ 权重与准备资料）；不就地修改传入 entry；
# 10. 合法已确认 prompt_history 与 prepare_only_run entry 对照仍正常
#     构建（H1/H5 正向不回归，新增 run 分类不得反向过宽）。
# 其余 weight run 结构形态（prompt-minimal run 根结构声明、
# coverage-first seed3407 的 merged 软链接来源链）、声明 run 源缺失
# （known gap：concise-cv 预期路径不存在）、有证据的核心训练参数提取
# （已核实归档 training_run_manifest）、多 entry 批量、eval/model 历
# 史条目（H9/H10）、history-summary 文件写入与 CLI 不在本切片（H6b
# 及后续）。

# M0 source-inventory.yaml training_machine_run_evidence.weight_runs 首
# 条真实 run（训练机只读调查 training_observed："fold0 有 adapter 与
# 10 个 merged 分片，有 evidence_archive"）。本切片声明该 run 一条
# entry；其余五个 weight run 保持未声明 sibling。该 run 与 H5 fixture
# 的 WEIGHT_RUN_SIBLING_ID 是同一真实 run —— H5 把它作为未声明
# sibling 钉死扫描，H6a 把它声明为 entry 钉死提取。
WEIGHT_RUN_DECLARED_ID = WEIGHT_RUN_SIBLING_ID

# M0 weight_runs 第 5 条真实 run（"run 根下有 adapter 与 10 个 merged
# 分片，有归档目录；结构与 fold0 子目录模式不同"）。作为未声明
# sibling 写入 fixture：权重直接位于 run 根（无 fold0/ 子目录），
# 扫描 workspace/runs/ 或从 sibling 取结构事实的实现必被捕获。
WEIGHT_RUN_ROOT_SIBLING_ID = "v4.1-prompt-minimal-v1-seed3411"

# Spec「核心训练参数」九字段族（与 H5 同族共享常量）：M0 对 weight run
# 只记录目录结构观察，未记录任何核心训练参数值，这些参数必须以字段级
# unknown 进入文档；有证据的参数提取（已核实的归档 manifest）属 H6b。
WEIGHT_RUN_CORE_TRAIN_PARAM_FACTS = PREPARE_ONLY_CORE_TRAIN_PARAM_FACTS

# M0 对已声明 run 的结构观察（"fold0 有 adapter 与 10 个 merged 分片，
# 有 evidence_archive"）分解出的已知事实名（Spec「模型身份」最小内容的
# fold 或全量范围 + 权重位置及存在性）。
WEIGHT_RUN_FOLD_SCOPE_FACT = "fold_scope"
WEIGHT_RUN_ADAPTER_PRESENT_FACT = "adapter_present"
WEIGHT_RUN_MERGED_PRESENT_FACT = "merged_present"
WEIGHT_RUN_KNOWN_FACTS = (
    WEIGHT_RUN_FOLD_SCOPE_FACT,
    WEIGHT_RUN_ADAPTER_PRESENT_FACT,
    WEIGHT_RUN_MERGED_PRESENT_FACT,
)

# H6a evidence-derived training_status 分类值：M0 把这组 run 归类为
# "有权重历史 run"（weight_runs 分组），观察事实是权重存在；训练完成
# 状态被 M0 明确排除（"run 目录存在不等于完成训练"、"不能当作
# completed 训练"）—— 既不能输出 completed（无证据的完成声明），也不
# 能输出 not_completed（"不等于完成"不等于"未完成"，负向声明同样无证
# 据），唯一有证据的分类是"观察到权重存在"本身。
WEIGHT_RUN_TRAINING_STATUS = "weights_observed"

# 参数名反走私 token（与 H5 同口径）：facts 内名字含这些 token 的事实
# 一律不得携带已知值（防止实现从 sibling prepare-only run 的 planned
# 配置或 sibling 归档 manifest 登记参数，含改用 configured_seed /
# num_train_epochs 等名字）。
_H6_PARAM_NAME_TOKENS = _H5_PARAM_NAME_TOKENS

# 数据 / Prompt 引用反走私 token：M0 未记录该 run 的数据或 Prompt 引用
# （调查记录："仍需逐训练核对实际冻结 Prompt，不能由 active Prompt 推
# 断历史输入"），名字含这些 token 的事实若存在只能为字段级 unknown，
# 防止从 sibling prepare-only run 的 input 资料（dataset_info.json 的
# release_id 等）走私已知引用。
_H6_REFERENCE_NAME_TOKENS = ("prompt", "release", "dataset", "data", "split")

# H6a 禁止存在性声明的命名族 token：训练完成（completed：run 目录存
# 在不等于完成训练）、通过（passed：不得把历史 summary 转成 passed）、
# 评测（eval：已有评估指标属后续切片）、model 正式身份（不为 run 分配
# 任何新正式身份）与权重完整性 / 哈希验证（M0：全部未验证权重完整性与
# 哈希；含 sha256 命名族）。weights / adapter / merged / checkpoint /
# safetensors 命名族不在禁止列表 —— 与 H5 相反，权重存在性是本 run 的
# M0 观察事实。
_H6_CLAIM_KEY_TOKENS = (
    "completed",
    "passed",
    "eval",
    "model",
    "verif",
    "hash",
    "integrity",
    "checksum",
    "sha",
)


def _write_weight_run_root_sibling_layout(root: Path) -> None:
    """H6a fixture：镜像 M0 weight_runs 第 5 条的 run 根结构 sibling。

    未声明 sibling weight run ``v4.1-prompt-minimal-v1-seed3411``：M0
    观察为"run 根下有 adapter 与 10 个 merged 分片，有归档目录；结构
    与 fold0 子目录模式不同" —— 权重直接位于 run 根下（无 fold0/ 子目
    录）。归档目录内放一份合成 training_run_manifest.json（结构镜像
    docs/results/model_evidence/*/input/training_run_manifest.json 的
    真实归档 manifest 字段集，字段值合成、seed 与任何真实 run 都不
    同），作为"从 sibling 归档取参数"实现的诱饵：已声明 run 的
    evidence_archive 保持为空目录（M0 未核实归档内容），任何已知参数
    值都只可能来自 sibling。字段值合成（非真实资料），结构与事实字段
    对齐 M0 证据。
    """
    run_dir = root / "workspace" / "runs" / WEIGHT_RUN_ROOT_SIBLING_ID
    (run_dir / "adapter").mkdir(parents=True, exist_ok=True)
    (run_dir / "adapter" / "adapter_model.safetensors").write_bytes(
        f"<synthetic adapter bytes: {WEIGHT_RUN_ROOT_SIBLING_ID}>".encode("utf-8")
    )
    (run_dir / "merged").mkdir(parents=True, exist_ok=True)
    for shard_index in range(1, 11):
        (
            run_dir / "merged" / f"model-{shard_index:05d}-of-00010.safetensors"
        ).write_bytes(
            (
                f"<synthetic merged shard {shard_index}/10: "
                f"{WEIGHT_RUN_ROOT_SIBLING_ID}>"
            ).encode("utf-8")
        )
    (run_dir / "evidence_archive").mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence_archive" / "training_run_manifest.json").write_bytes(
        _fixture_pretty_json_bytes(
            {
                "schema_version": (
                    "tensile-vlm-v4.1-training-run/v1-fixture-bait"
                ),
                "run_id": WEIGHT_RUN_ROOT_SIBLING_ID,
                "seed": 9999,
                "learning_rate": 9e-05,
                "epochs": 9.0,
                "effective_batch_size": 99,
                "optimizer": "adamw_fixture",
                "precision": "fp32_fixture",
                "lora_rank": 99,
                "lora_alpha": 99,
                "lora_target_modules": ["fixture_module"],
                "actual_optimizer_steps": 9999,
                "completed_at": "2026-01-01T00:00:00+08:00",
            }
        )
    )


def _confirmed_weight_run_entry() -> dict[str, Any]:
    """逐字段镜像 M0 证据结构的已确认 weight_run entry（H6a 输入）。

    kind 为 M0 对齐的 ``weight_run``（source-inventory
    training_machine_run_evidence.weight_runs 的分组名）；
    source_legacy_id 为 M0 记录的首条原始 run ID（不带 "/"，与
    prepare-only run 的 ``<experiment>/seed<N>`` 形态不同）；observed
    逐字取 M0 观察记录；status ``user_confirmed``（M0 object-mapping
    model_train_eval_history 的 history_decision：用户确认六个有权重
    run 仅进 history-summary，不分配任何新正式身份），由入口自身读
    取该字段消费；source_verified 保持 ``training_observed`` 事实分
    级（M0 训练机只读调查），与确认状态分离。entry 不携带
    candidate_target_identity / passed。
    """
    return {
        "kind": "weight_run",
        "source_legacy_id": WEIGHT_RUN_DECLARED_ID,
        "role": (
            "有权重历史 run（M0 weight_runs 首条：历史模型候选，"
            "需继续验证来源和归档完整性）"
        ),
        "source_verified": "training_observed",
        "history_only": True,
        "status": "user_confirmed",
        "confirmed_by_user_date": "2026-09-07",
        "observed": (
            "fold0 有 adapter 与 10 个 merged 分片，有 evidence_archive"
        ),
        "notes": (
            "M0 source-inventory weight_runs notes：run 目录存在不等于完"
            "成训练；全部未验证权重完整性与哈希。object-mapping "
            "model_train_eval_history：不能当作 completed 训练。"
        ),
    }


def _assert_h6_fact_is_unknown(fact: Any, *, name: str, run_id: str) -> None:
    """断言 weight run 事实为 H4/H5 同口径字段级 unknown 形态。"""
    assert isinstance(fact, Mapping), (
        f"weight run 的事实 {name} 必须以 mapping 形态进入字段级 unknown"
        f"（携带 unknown_reason / attempted_source）：实际 {type(fact).__name__!r}"
    )
    reason = fact.get("unknown_reason")
    assert isinstance(reason, str) and reason.strip(), (
        f"weight run 的事实 {name} 必须携带非空字符串 unknown_reason（M0 "
        f"未记录该字段值，缺失原因不得静默）：实际 {reason!r}"
    )
    attempted = fact.get("attempted_source")
    attempted_text = " ".join(_document_string_fragments(attempted))
    assert attempted_text.strip(), (
        f"weight run 的事实 {name} 必须携带非空 attempted_source（指回声明"
        f"的 run 源）：实际 {attempted!r}"
    )
    assert run_id in attempted_text, (
        f"weight run 的事实 {name} 的 attempted_source 必须指回声明的 run"
        f"源（{run_id}）：实际 {attempted_text!r}"
    )
    if "value" in fact:
        assert fact["value"] is None, (
            f"weight run 的事实 {name} 不得携带非 None 的 value（无证据值"
            f"不得登记为已知）：实际 {fact['value']!r}"
        )


def _assert_h6_known_fact(
    fact: Any,
    *,
    name: str,
    run_id: str,
    expected_value: Any,
    must_reference_fold: bool = False,
) -> None:
    """断言 weight run 已知事实为 {value, source} 形态且来源指回声明源。"""
    assert isinstance(fact, Mapping), (
        f"weight run 的已知事实 {name} 必须为 {{value, source}} 形态的 "
        f"mapping：实际 {type(fact).__name__!r}"
    )
    assert set(fact) == {"value", "source"}, (
        f"weight run 的已知事实 {name} 的键集必须恰为 {{value, source}}："
        f"实际 {sorted(fact)}"
    )
    if isinstance(expected_value, bool):
        assert fact["value"] is expected_value, (
            f"weight run 的已知事实 {name} 的 value 必须为 "
            f"{expected_value!r}（M0 结构观察声明值）：实际 {fact['value']!r}"
        )
    else:
        assert fact["value"] == expected_value, (
            f"weight run 的已知事实 {name} 的 value 必须与 M0 结构观察声明值"
            f"相等（不重算、不伪造、不取 sibling）：实际 {fact['value']!r}，"
            f"期望 {expected_value!r}"
        )
    source = fact["source"]
    assert isinstance(source, Mapping) and source, (
        f"weight run 的已知事实 {name} 必须携带非空 mapping 形态的来源 "
        f"provenance（source，指回声明 run 源）：实际 {source!r}"
    )
    source_text = " ".join(_document_string_fragments(source))
    assert source_text.strip(), (
        f"weight run 的已知事实 {name} 的来源 provenance 必须非空：实际 "
        f"{source_text!r}"
    )
    assert run_id in source_text, (
        f"weight run 的已知事实 {name} 的来源 provenance 必须指回声明的 run"
        f"源（{run_id}）：实际 {source_text!r}"
    )
    if must_reference_fold:
        assert "fold0" in source_text, (
            f"weight run 的已知事实 {name} 的来源 provenance 必须指回观察到"
            f"该事实的 fold0 位置（权重位置及存在性）：实际 {source_text!r}"
        )


def _assert_h6_no_completion_or_verification_claims(
    value: Any, path: str
) -> None:
    """递归断言 weight run summary entry 内不存在完成 / 验证类声明。

    与 H5 的 _assert_h5_no_training_fact_claims 不同：weight run 的权重
    存在性是 M0 观察事实，weights / adapter / merged / checkpoint /
    safetensors 命名族键允许携带存在性值（H6a 钉定的三个已知事实即属
    此类）；禁止的是 M0 明确排除的声明 —— 训练完成（completed：run 目
    录存在不等于完成训练）、通过（passed：不得把历史 summary 转成
    passed）、评测结果（eval：已有评估指标属后续切片）、model 正式身份
    （不为 run 分配任何新正式身份）与权重完整性 / 哈希验证（M0：全部
    未验证权重完整性与哈希）。
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            child_path = f"{path}.{key}"
            if any(token in key_text for token in _H6_CLAIM_KEY_TOKENS):
                assert not _h5_value_claims_existence(item), (
                    f"weight run 的 summary entry 不得声明 {child_path}：键"
                    f"携带训练完成 / 通过 / 评测 / model 身份 / 权重完整性验"
                    f"证的存在性值 {item!r}（M0 未证实训练完成，权重完整性与"
                    "哈希全部未验证，不得把历史 summary 转成 passed）"
                )
            _assert_h6_no_completion_or_verification_claims(item, child_path)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_h6_no_completion_or_verification_claims(
                item, f"{path}[{index}]"
            )


def _assert_legal_prepare_only_run_entry_still_builds(
    build: Any, root: Path
) -> None:
    """合法对照（H6a 新增 run 分类不得反向过宽）：prepare_only_run 不回归。

    完整 H5 正向契约由既有 H5 selector 复跑钉定；此处只做轻量对照，
    证明 weight run 历史条目分类不得反向过宽到改变既有合法 run entry
    的行为。
    """
    legal_document = build(root, [_confirmed_prepare_only_run_entry()])
    legal_entries = (
        legal_document.get("entries")
        if isinstance(legal_document, Mapping)
        else None
    )
    assert isinstance(legal_entries, list) and len(legal_entries) == 1, (
        "weight run 分类不得反向过宽：合法已确认 prepare_only_run entry 必须"
        "仍正常构建恰含一条 entry 的 history-summary 文档（H5 正向行为不回"
        f"归）；实际 {type(legal_document).__name__} / entries={legal_entries!r}"
    )
    legal_entry = legal_entries[0]
    assert isinstance(legal_entry, Mapping), (
        "合法已确认 prepare_only_run entry 的 history-summary entry 必须是 "
        f"mapping：实际 {type(legal_entry).__name__!r}"
    )
    assert legal_entry.get("training_status") == "prepared_only", (
        "weight run 分类不得反向过宽：合法已确认 prepare_only_run entry 的 "
        "training_status 必须保持 'prepared_only'（H5 正向行为不回归）：实际 "
        f"{legal_entry.get('training_status')!r}"
    )


def test_confirmed_weight_run_entry_records_observed_weights_and_evidence_gaps(
    tmp_path: Path,
) -> None:
    r"""单条已确认 weight run entry 只登记有证据的观察事实（H6a，M1b
    history-summary weight run 第一切片，先写测试，不改 production）。

    H6a behavior —— 对已确认 weight run 历史条目（kind
    ``weight_run``、source_legacy_id
    ``v4.1-phase2-source-aware-v1-seed3407``、status
    ``user_confirmed``；M0 source-inventory
    training_machine_run_evidence.weight_runs 首条：训练机只读观察
    "fold0 有 adapter 与 10 个 merged 分片，有 evidence_archive"，
    notes "run 目录存在不等于完成训练……全部未验证权重完整性与哈希"）
    调用 ``build_history_summary(root, [entry])`` 必须：
    1. 返回 history-summary 文档（history_summary_schema ==
       tensile-migration/history-summary/v1），不得 fail-closed 拒绝该
       kind 使 entry 消失 —— 有权重 run 是 M0 明确允许保留的简明历史
       记录（Spec：试验性模型允许保留简明历史记录，资料不完整的记录仍
       可用于历史查询），fail-closed 拒绝只能保留给 H2/H3 的非法输入
       域；
    2. 保留原始 run ID 与分类：original_id ==
       v4.1-phase2-source-aware-v1-seed3407；kind == "weight_run"（保
       持有权重 run 分类，不得误归 prepare_only_run 或 prompt 形态）；
       history_only: true；formal_identity: "none"；entry_id 为文档内
       slug 且非 <kind>-v<协议>-r<N> 正式身份；
    3. 输出 evidence-derived ``training_status == "weights_observed"``：
       M0 观察到权重存在，训练完成状态被 M0 明确排除 —— 不得输出
       completed（无证据的完成声明），也不得输出 not_completed 等同
       样无证据的负向声明（"run 目录存在不等于完成训练"不等于"训练
       未完成"）；
    4. M0 结构观察分解出的已知事实（Spec「模型身份」最小内容：fold 或
       全量范围 + 权重位置及存在性）：fold_scope == "fold0"、
       adapter_present is True、merged_present is True，已知值形态
       {value, source}，source 为非空 mapping 且指回声明 run 源；权重
       事实的 source 须指回观察到它们的 fold0 位置；不重算、不伪
       造、不取 sibling；
    5. 核心训练参数（seed / learning_rate / epochs /
       effective_batch_size / optimizer / precision / lora_rank /
       lora_alpha / lora_target_modules，与 H5 同族）全部以 H4 同口径
       字段级 unknown 进入 facts：非空 unknown_reason + 指回声明 run 源
       的 attempted_source，不携带非 None value（M0 未记录 weight run
       的任何参数值；声明 run 的 evidence_archive 内容未经 M0 核实，
       fixture 中声明 run 内不存在任何参数来源文件）；任何名字含参数
       token（seed / learning_rate / epoch / step / batch / optim /
       precision / lora）或数据 / Prompt 引用 token（prompt / release /
       dataset / data / split）的事实同样不得携带已知值（反走私：不
       得从 sibling prepare-only run 的 planned 配置（seed 3411）、
       sibling input 资料（release_id）或 sibling 归档 manifest（合成
       参数）登记任何已知值）；
    6. 不声明训练完成、通过、评测结果、model 正式身份或权重完整性 /
       哈希验证：entry 内任何键名携带 completed / passed / eval /
       model / verif / hash / integrity / checksum / sha 命名族 token
       的位置不得声明存在性值（允许字段级 unknown 形态或 None / False
       显式非存在记录）；weights / adapter / merged / checkpoint /
       safetensors 命名族键允许携带存在性值 —— 与 H5 相反，权重存在
       是本 run 的 M0 观察事实；
    7. 不扫描 sibling：entries 恰含声明的一条（不得扫描 workspace/
       runs/ 生成 sibling 条目，也不得为 run 派生 model 等其他概念条
       目）；未声明 sibling（v4.1-prompt-concise-v1/seed3411、
       v4.1-prompt-concise-v2/seed3411、v4.1-prompt-minimal-v1-
       seed3411 与三个 prompt registry 条目）的 ID 不得进入文档任何字
       符串；
    8. 不分配任何新正式身份：文档内任何字符串值都不是
       <kind>-v<协议>-r<N> 正式身份（M0 model_train_eval_history
       scope_note：不为复用导出器伪造 completed Run / 模型）；
    9. 纯构建零写入：全树快照逐字节不变（不写 history-summary 文件、
       不创建 records/ 或任何目标条目、不改 legacy 源树含
       workspace/runs/ 权重与准备资料）；不就地修改传入 entry；
    10. 合法已确认 prompt_history 与 prepare_only_run entry 对照仍正常
        构建（H1/H5 正向不回归，新增 run 分类不得反向过宽）。

    fixture：_write_prepare_only_runs_layout 镜像 M0
    training_machine_run_evidence 的 workspace/runs/ 布局 —— 已声明
    weight run ``v4.1-phase2-source-aware-v1-seed3407`` 呈 M0 观察的
    fold0 结构（fold0/adapter + 10 个 merged 分片 + 空 evidence_archive/
    —— M0 未核实归档内容，故声明 run 内没有任何参数来源文件）；两个
    未声明 prepare-only sibling（v1 携带 planned 参数 seed 3411 的
    prepared-config-untrained）。_write_weight_run_root_sibling_layout 补
    充未声明 run 根结构 weight run sibling（v4.1-prompt-minimal-v1-
    seed3411：权重在 run 根、无 fold0/，归档内放合成参数诱饵 manifest）。
    加上 _write_full_history_prompt_registry 的完整三条目 legacy prompt
    registry（合法对照与 prompt sibling 钉死）。entry 输入
    _confirmed_weight_run_entry 逐字段镜像 M0 证据结构（observed 逐字
    取 M0 观察记录；status user_confirmed 由入口自身读取消费；
    source_verified 保持 training_observed 事实分级）。

    RED Gate 设计（H6a）：build_history_summary 入口已存在（H1 已
    GREEN），RED 不经入口缺失分支给出。当前实现不按 kind 分流到 run
    历史路径（对 weight_run 仍走 prompt registry 源路径）：对本用例
    entry 静默构建无 training_status、无 fold/weights 已知事实、无核
    心训练参数事实的 prompt 形态文档（六个 prompt 事实全部 unknown，
    attempted_source 指向不存在的 pipeline/prompt_registry/<run_id>/）
    —— 由 training_status 断言的显式 AssertionError 钉出"weight run
    历史条目行为缺失"。若实现改为对该 kind fail-closed 拒绝（任务允许
    的另一缺陷形态），拒绝经本用例 try/except 转译为显式行为
    AssertionError（原始域错误经 cause 链保留）钉出同一 RED 结论，不
    让原始异常直接充当 RED。fixture 前置事实与两个合法对照全部真实执
    行后才失败。

    捕获的合理但错误实现：
    - 对 weight_run kind fail-closed 拒绝（entry 消失）-> 转译后的显式
      AssertionError 判失败；
    - 走 prompt registry 源路径（当前实现形态：无 training_status、
      无 fold/weights 已知事实、prompt 事实 unknown 的 attempted_source
      指向 pipeline/prompt_registry/<run_id>）-> 行为 3 断言失败；
    - 输出 completed / not_completed / prepared_only -> 行为 3 断言失
      败；
    - 不输出 fold_scope / adapter_present / merged_present 或伪造其值
      （fold_scope 非 fold0、来源不指回声明 run 源）-> 行为 4 断言失
      败；
    - 从 sibling prepare-only run 的 planned 配置（seed 3411）、
      sibling input 资料（release_id）或 sibling 归档 manifest（合成参
      数）登记已知参数 / 引用（含改用 configured_seed / num_train_
      epochs 等名字）-> 行为 5 的 unknown / 反走私断言失败；
    - 声明训练完成 / passed / 评测结果 / model 身份 -> 行为 6 claims
      扫描失败；
    - 声明权重完整性 / 哈希已验证 -> 行为 6 claims 扫描失败；
    - 扫描 workspace/runs/ 生成 sibling 条目或取 sibling 结构事实
      （run 根结构 sibling 无 fold0/）-> 行为 7 / fold_scope 断言失
      败；
    - 为 run 派生 model 概念条目 / 分配正式身份 -> 行为 7/8 断言失
      败；
    - 构建路径写盘（history-summary 文件、records/、staging、改
      workspace/runs/ 权重与准备资料）-> 全树快照对比失败；
    - 丢失原始 run ID -> original_id 断言失败；
    - 就地改写传入 entry -> 输入不变断言失败；
    - 对合法 prompt_history / prepare_only_run entry 改变 H1/H5 行为
      -> 合法对照断言失败。

    多 entry 批量（多个 weight run 同批）、其余 weight run 结构形态
    （run 根结构声明、merged 软链接来源链）、声明 run 源缺失（known
    gap）、有证据的核心训练参数提取（已核实归档 manifest）、eval /
    model 历史条目（H9/H10）、prepare-only 与 weight run 的非法输入反
    向（H2/H3 门对 run entry 的适用）、history-summary 文件写入与
    CLI 不在本切片。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（H6a 仅新增用
      例与配套 helper/常量及模块 docstring 清单条目，不改 production）。
    - 命令（新 selector）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_confirmed_weight_run_entry_records_observed_weights_and_
      evidence_gaps``
    - RED failure signature：恰一个失败用例（本 selector），失败为
      行为 3 的 AssertionError（training_status 实际 None !=
      'weights_observed'）；fixture 前置事实、入口解析与两个合法对照
      全部不失败；不出现 ModuleNotFoundError / ImportError /
      AttributeError 或原始异常直接充当 RED 结论。
    - 既有 selector 复跑（回归钉）：H1–H5 小 selector（-k 同口径 7 个
      用例名）26 passed；全 migration 文件 RED 时点：106 passed +
      1 failed（失败恰为本 selector）。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （与 H1–H5 binding 记录一致，``[tool.pytest.ini_options]
      testpaths / pythonpath`` 解析依赖该文件）。
    """
    _write_full_history_prompt_registry(tmp_path)
    _write_prepare_only_runs_layout(tmp_path)
    _write_weight_run_root_sibling_layout(tmp_path)
    declared_run_dir = tmp_path / "workspace" / "runs" / WEIGHT_RUN_DECLARED_ID
    declared_fold_dir = declared_run_dir / "fold0"

    # ---- fixture 前置事实（对齐 M0 证据）：已声明 run 呈 M0 观察的
    #      fold0 结构；声明 run 内没有任何参数来源文件（核心参数
    #      unknown 断言非空洞 —— 已知参数值只能来自 sibling）；sibling
    #      prepare-only run 携带 planned 参数与 input 引用（走私诱
    #      饵）；run 根结构 weight sibling 存在（结构取错必被捕获）；
    #      prompt registry 完整（合法对照依赖）；目标根不存在。----
    assert (declared_fold_dir / "adapter" / "adapter_model.safetensors").is_file(), (
        "fixture 前置事实失败：已声明 weight run 必须呈 M0 观察的 fold0 "
        "结构（fold0/adapter 存在）"
    )
    merged_shards = sorted((declared_fold_dir / "merged").glob("*.safetensors"))
    assert len(merged_shards) == 10, (
        "fixture 前置事实失败：已声明 weight run 的 fold0/merged 必须有 "
        f"M0 观察的 10 个分片：实际 {len(merged_shards)}"
    )
    assert (declared_run_dir / "evidence_archive").is_dir(), (
        "fixture 前置事实失败：已声明 weight run 必须有 M0 观察的 "
        "evidence_archive 目录"
    )
    declared_files = [path for path in declared_run_dir.rglob("*") if path.is_file()]
    assert declared_files, (
        "fixture 前置事实失败：已声明 weight run 目录必须携带 M0 观察的"
        "权重文件"
    )
    for path in declared_files:
        assert path.suffix not in {".json", ".yaml", ".yml"}, (
            "fixture 前置事实失败：已声明 weight run 内不得存在任何参数来"
            f"源文件（M0 未核实归档内容，核心参数 unknown 断言才有依据）："
            f"发现 {path}"
        )
    prepare_only_dir = (
        tmp_path / "workspace" / "runs" / PREPARE_ONLY_RUN_V1_ID
    )
    prepared_manifest = json.loads(
        (
            prepare_only_dir
            / "prepared-config-untrained"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert prepared_manifest.get("status") == "prepared", (
        "fixture 前置事实失败：sibling prepare-only run 的 prepared "
        "manifest 必须声明 status: prepared"
    )
    planned_config = yaml.safe_load(
        (
            prepare_only_dir / "prepared-config-untrained" / "train.yaml"
        ).read_bytes()
    )
    assert planned_config.get("seed") == 3411 and "learning_rate" in planned_config, (
        "fixture 前置事实失败：sibling prepare-only run 必须真实携带 "
        "planned 参数（走私诱饵：实现不得把 sibling 的 planned 参数登记"
        "为该 weight run 的训练事实）"
    )
    root_sibling_dir = (
        tmp_path / "workspace" / "runs" / WEIGHT_RUN_ROOT_SIBLING_ID
    )
    assert (root_sibling_dir / "adapter" / "adapter_model.safetensors").is_file(), (
        "fixture 前置事实失败：run 根结构 weight run sibling 必须存在"
        "（权重在 run 根，结构与已声明 run 不同）"
    )
    assert any((root_sibling_dir / "merged").glob("*.safetensors")), (
        "fixture 前置事实失败：run 根结构 weight run sibling 必须真实携"
        "带 merged 分片"
    )
    sibling_manifest = json.loads(
        (
            root_sibling_dir
            / "evidence_archive"
            / "training_run_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert sibling_manifest.get("seed") == 9999, (
        "fixture 前置事实失败：sibling 归档诱饵 manifest 必须携带与一切真"
        "实 run 不同的合成参数（从 sibling 取参数的实现才会登记出该值）"
    )
    for prompt_source_id in (
        HISTORY_SIBLING_SOURCE_ID,
        CONFIRMED_PROMPT_SOURCE_ID,
        _THIRD_REGISTRY_SOURCE_ID,
    ):
        prompt_dir = tmp_path / "pipeline" / "prompt_registry" / prompt_source_id
        assert (prompt_dir / "manifest.json").is_file() and (
            prompt_dir / "prompt.yaml"
        ).is_file(), (
            f"fixture 前置事实失败：legacy prompt registry 条目 {prompt_source_id} "
            "必须完整（合法对照依赖）"
        )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    # ---- 行为 10：合法对照 —— H1 prompt_history 与 H5 prepare_only_run
    #      正向不回归（新增 run 分类不得反向过宽）。----
    _assert_legal_history_entry_still_builds(build, tmp_path)
    _assert_legal_prepare_only_run_entry_still_builds(build, tmp_path)

    before = _snapshot_tree(tmp_path)
    entry = _confirmed_weight_run_entry()
    expected_entry = _confirmed_weight_run_entry()

    # ---- 行为 1：已确认 weight_run entry 必须构建文档，不得 fail-closed
    #      拒绝 kind 使 entry 消失。----
    try:
        document = build(tmp_path, [entry])
    except Exception as exc:
        raise AssertionError(
            "已确认 weight_run 历史条目必须进入 history-summary 文档"
            "（有权重 run 是 M0 明确允许保留的简明历史记录，不得 "
            "fail-closed 拒绝使 entry 消失；weight run 历史条目行为缺"
            "失）：实际抛出 "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        ) from exc
    assert isinstance(document, Mapping), (
        "build_history_summary 必须返回 history-summary 文档（mapping）：实际 "
        f"{type(document).__name__!r}"
    )
    assert (
        document.get("history_summary_schema")
        == "tensile-migration/history-summary/v1"
    ), (
        "history-summary 文档必须声明 history_summary_schema == "
        "'tensile-migration/history-summary/v1'：实际 "
        f"{document.get('history_summary_schema')!r}"
    )
    document_entries = document.get("entries")
    assert isinstance(document_entries, list), (
        "history-summary 文档的 entries 必须是 list：实际 "
        f"{type(document_entries).__name__!r}"
    )
    assert len(document_entries) == 1, (
        "history-summary 文档必须恰含声明的一条 entry（不得扫描 runs 目录生成"
        " sibling 条目，也不得为 weight run 派生 model 等其他概念条目）："
        f"实际 {len(document_entries)} 条"
    )
    summary_entry = document_entries[0]
    assert isinstance(summary_entry, Mapping), (
        "history-summary entry 必须是 mapping：实际 "
        f"{type(summary_entry).__name__!r}"
    )

    # ---- 行为 2：保留原始 run ID、分类与来源结构。----
    assert summary_entry.get("original_id") == WEIGHT_RUN_DECLARED_ID, (
        "weight run entry 必须保留 original_id（M0 记录的原始 run ID）："
        f"实际 {summary_entry.get('original_id')!r}"
    )
    assert summary_entry.get("kind") == "weight_run", (
        "weight run entry 必须保持声明的 kind（weight_run，M0 weight_runs "
        f"对齐分类，不得误归 prepare_only_run 或 prompt 形态）：实际 "
        f"{summary_entry.get('kind')!r}"
    )
    assert summary_entry.get("history_only") is True, (
        "weight run entry 必须标记 history_only: true：实际 "
        f"{summary_entry.get('history_only')!r}"
    )
    assert summary_entry.get("formal_identity") == "none", (
        "weight run entry 必须标记 formal_identity: none（不分配新正式身"
        f"份）：实际 {summary_entry.get('formal_identity')!r}"
    )
    entry_id = summary_entry.get("entry_id")
    assert isinstance(entry_id, str) and entry_id, (
        "weight run entry 必须携带非空字符串 entry_id（文档内 slug）：实际 "
        f"{entry_id!r}"
    )
    assert not is_valid_version_id(entry_id), (
        "entry_id 必须是文档内 slug，不得是 <kind>-v<协议>-r<N> 正式身份："
        f"实际 {entry_id!r}"
    )

    # ---- 行为 3：training_status: weights_observed（evidence-derived，
    #      是否 completed 由证据决定 —— M0 明确排除完成状态，也不允许
    #      无证据的负向声明）。----
    assert summary_entry.get("training_status") == WEIGHT_RUN_TRAINING_STATUS, (
        "weight run 历史条目必须输出 training_status == 'weights_observed'"
        "（M0 观察到权重存在；训练完成状态被 M0 明确排除 —— 不得输出 "
        "completed，也不得输出 not_completed 等同样无证据的负向声明，还不得"
        "误归 prepared_only）：实际 "
        f"{summary_entry.get('training_status')!r}"
    )

    # ---- 行为 4：M0 结构观察分解出的已知事实（fold_scope /
    #      adapter_present / merged_present），{value, source} 形态，
    #      来源指回声明 run 源；权重事实的来源须指回 fold0 观察位置。----
    facts = summary_entry.get("facts")
    assert isinstance(facts, Mapping) and facts, (
        "weight run entry 必须携带非空 facts（M0 结构观察的已知事实与字段级 "
        f"unknown 的核心训练参数）：实际 {facts!r}"
    )
    for name in WEIGHT_RUN_KNOWN_FACTS:
        assert name in facts, (
            f"weight run 的 facts 必须包含 M0 结构观察分解出的已知事实 "
            f"{name}（Spec「模型身份」最小内容：fold 或全量范围 + 权重位置"
            f"及存在性）：实际键集 {sorted(facts)}"
        )
    _assert_h6_known_fact(
        facts[WEIGHT_RUN_FOLD_SCOPE_FACT],
        name=WEIGHT_RUN_FOLD_SCOPE_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value="fold0",
    )
    _assert_h6_known_fact(
        facts[WEIGHT_RUN_ADAPTER_PRESENT_FACT],
        name=WEIGHT_RUN_ADAPTER_PRESENT_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value=True,
        must_reference_fold=True,
    )
    _assert_h6_known_fact(
        facts[WEIGHT_RUN_MERGED_PRESENT_FACT],
        name=WEIGHT_RUN_MERGED_PRESENT_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value=True,
        must_reference_fold=True,
    )

    # ---- 行为 5：核心训练参数全部字段级 unknown（M0 未记录 weight run
    #      的任何参数值；声明 run 内没有参数来源文件），参数名与数据 /
    #      Prompt 引用名反走私。----
    for name in WEIGHT_RUN_CORE_TRAIN_PARAM_FACTS:
        assert name in facts, (
            f"weight run 的 facts 必须包含核心训练参数 {name}（Spec「核心历史"
            f"信息的最低内容」，缺失资料进入字段级 unknown 而不是删字段）："
            f"实际键集 {sorted(facts)}"
        )
        _assert_h6_fact_is_unknown(
            facts[name], name=name, run_id=WEIGHT_RUN_DECLARED_ID
        )
    for name, fact in facts.items():
        name_lower = str(name).lower()
        if any(token in name_lower for token in _H6_PARAM_NAME_TOKENS) or any(
            token in name_lower for token in _H6_REFERENCE_NAME_TOKENS
        ):
            _assert_h6_fact_is_unknown(
                fact, name=name, run_id=WEIGHT_RUN_DECLARED_ID
            )

    # ---- 行为 6：不声明训练完成、通过、评测结果、model 正式身份或权
    #      重完整性 / 哈希验证。----
    _assert_h6_no_completion_or_verification_claims(summary_entry, "entry")

    # ---- 行为 8：不分配任何新正式身份（文档内任何字符串都不是正式
    #      身份）。----
    all_strings = _document_string_fragments(document)
    for fragment in all_strings:
        assert not is_valid_version_id(fragment), (
            "history-summary 文档内不得出现任何 <kind>-v<协议>-r<N> 正式"
            f"身份（weight run 不分配 model/train/eval 等任何新正式身份）："
            f"实际出现 {fragment!r}"
        )

    # ---- 行为 7：不扫描 sibling —— 未声明 run 与 prompt sibling 的 ID
    #      不得进入文档任何字符串。----
    for sibling_id in (
        PREPARE_ONLY_RUN_V1_ID,
        PREPARE_ONLY_RUN_V2_ID,
        WEIGHT_RUN_ROOT_SIBLING_ID,
        HISTORY_SIBLING_SOURCE_ID,
        CONFIRMED_PROMPT_SOURCE_ID,
        _THIRD_REGISTRY_SOURCE_ID,
    ):
        assert not any(sibling_id in fragment for fragment in all_strings), (
            f"未声明 sibling {sibling_id} 不得进入 history-summary 文档的任何"
            "字符串（实现必须按声明 entry 定位源，不得扫描 legacy 目录或从"
            "sibling 取内容）"
        )

    # ---- 行为 9：纯构建零写入 —— 全树逐字节不变（legacy 源不变含
    #      workspace/runs/ 权重与准备资料、不写 history-summary 文件、
    #      不创建任何目标条目）。----
    assert _snapshot_tree(tmp_path) == before, (
        "build_history_summary 必须纯构建零写入：全树快照逐字节不变"
        "（不写 history-summary 文件、不创建 records/ 或任何目标条目、不改 "
        "legacy 源树含 workspace/runs/ 权重与准备资料）"
    )
    assert not (tmp_path / "records").exists(), (
        "纯构建不得创建 records/ 或任何正式对象条目（不分配新正式身份）"
    )
    assert not (tmp_path / "docs").exists(), (
        "纯构建不得写入 history-summary 文件（本切片只经返回值给出文档）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"纯构建不得落盘任何 history-summary 命名文件：发现 {path}"
        )

    # ---- 不就地修改传入 entry。----
    assert entry == expected_entry, (
        "全程不得就地改写传入 entry（H6a 输入事实保持不变）"
    )


# ---------------------------------------------------------------------------
# H6b：history-summary —— weight run 权重存在性判定口径一致 + 声明源缺
# 失 known gap 分流（M1b，先写测试，不改 production）
# ---------------------------------------------------------------------------
#
# H6b behavior（本切片，主 Agent 选定，M1b history-summary weight run
# 第二切片，先写测试，不改 production）—— 两项：
# 1. 权重存在性判定口径一致（reviewer 对 H6a 的 P3：adapter_present 使
#    用递归任意文件判定，merged_present 使用顶层 safetensors 判定，两
#    者口径不一致）：两者都只把目录中的权重命名文件（例如
#    *.safetensors）计为权重，不得把非权重文件（adapter_config.json /
#    README.md / model-index.json 等元数据文件）误判为权重；可观察目
#    录中无权重命名文件时该 *_present 为已知 False（观察到的缺席，
#    目录可观察、判定结果确定，不是 unknown）；adapter / merged 任一
#    观察到权重 -> entry 照常构建且 training_status 仍为
#    weights_observed（H6a 既有"未观察到 adapter / merged 权重存在性
#    证据"才拒绝的任一证据规则保持，H6a 不回归）。
# 2. 声明 run 源缺失（workspace/runs/<source_legacy_id> 整个缺失；M0
#    known_gap 真实形态：source-inventory.yaml known_gap.expected_run
#    workspace/runs/v4.1-prompt-concise-cv-v1-seed3411 "训练机预期路
#    径不存在"，object-mapping model_train_eval_history 将该 run 列为
#    用户确认 history-only entry："训练机对应 run 路径缺失（known
#    gap）"）时，weight_run entry 不得 fail-closed 拒绝使 entry 消
#    失、整批不得 blocked（Spec："身份、权重或结果证据不足时，可以
#    保存明确标注缺失的历史记录，不能把它作为完整的新正式对象供下
#    游执行"、"不能取得的历史值标为未知并注明来源缺口"；M0 known_gap
#    meaning："不能断言模型在整台训练机上不存在；需沿历史报告定位"，
#    既非权重存在也非准备资料观察；H4 同口径先例：声明源缺失 -> 字段
#    级 unknown，缺失与坏源可区分）：fold_scope / adapter_present /
#    merged_present 与九个核心训练参数全部进入字段级 unknown（非空
#    unknown_reason + 指回声明 run 源的 attempted_source，不携带非
#    None value），不输出 weights_observed（无权重观察证据，也不得信
#    任 entry 声明代替重新观察）/ completed / not_completed /
#    prepared_only 等无证据声明；不取 sibling（planned 配置、归档诱
#    饵、其余 run 目录）。
# 有证据的 H6a 行为不回归（H6a selector 复跑钉定 + 本切片合法对照）；
# 不扫描 sibling；纯构建零写入。fold0 缺失但 run 目录存在的其余结构
# 形态（含 run 根权重结构）、fold0/adapter 与 merged 均无权重命名文
# 件（完全无权重证据）的分流、merged 软链接来源链、有证据的核心训
# 练参数提取（已核实归档 manifest）、多 entry 批量、eval/model 历史
# 条目（H9/H10）、history-summary 文件写入与 CLI 不在本切片（留后
# 续）。


# T1/T2 共用的未声明 sibling ID 集（fixture 与文档反扫描断言共用）。
_H6B_UNDECLARED_SIBLING_IDS = (
    PREPARE_ONLY_RUN_V1_ID,
    PREPARE_ONLY_RUN_V2_ID,
    WEIGHT_RUN_ROOT_SIBLING_ID,
    HISTORY_SIBLING_SOURCE_ID,
    CONFIRMED_PROMPT_SOURCE_ID,
    _THIRD_REGISTRY_SOURCE_ID,
)


def _replace_declared_adapter_weights_with_non_weight_files(root: Path) -> None:
    """场景 A mutation：声明 run 的 fold0/adapter 只剩非权重元数据文件。

    移除 M0 观察的权重文件 adapter_model.safetensors，写入两个真实适
    配器目录常见形态的非权重元数据文件（adapter_config.json /
    README.md）。配置内容刻意不含九个核心训练参数 token（本切片只钉
    存在性判定口径，不新增参数来源歧视面；核心参数 unknown 的既有钉
    定由 H6a selector 与本用例的 sibling 走私诱饵覆盖）。
    """
    adapter_dir = (
        root / "workspace" / "runs" / WEIGHT_RUN_DECLARED_ID / "fold0" / "adapter"
    )
    weight_file = adapter_dir / "adapter_model.safetensors"
    assert weight_file.is_file(), (
        "fixture 前置事实失败：替换前 fold0/adapter 必须有 M0 观察的权重文件"
    )
    weight_file.unlink()
    (adapter_dir / "adapter_config.json").write_bytes(
        _fixture_pretty_json_bytes(
            {
                "schema_version": "tensile-adapter-metadata-fixture/v1",
                "note": "非权重元数据（合成 fixture，不含训练参数）",
            }
        )
    )
    (adapter_dir / "README.md").write_bytes(
        "<synthetic adapter metadata note>\n".encode("utf-8")
    )


def _restore_declared_adapter_weight_file(root: Path) -> None:
    """场景 B 前置：恢复声明 run 的 fold0/adapter 权重文件（场景 A 已移除）。"""
    adapter_dir = (
        root / "workspace" / "runs" / WEIGHT_RUN_DECLARED_ID / "fold0" / "adapter"
    )
    weight_file = adapter_dir / "adapter_model.safetensors"
    assert not weight_file.exists(), (
        "fixture 前置事实失败：场景 B 恢复前 adapter 权重文件必须已被场景 A 移除"
    )
    weight_file.write_bytes(
        f"<synthetic adapter bytes: {WEIGHT_RUN_DECLARED_ID}>".encode("utf-8")
    )


def _replace_declared_merged_shards_with_non_weight_file(root: Path) -> None:
    """场景 B mutation：声明 run 的 fold0/merged 只剩非权重元数据文件。"""
    merged_dir = (
        root / "workspace" / "runs" / WEIGHT_RUN_DECLARED_ID / "fold0" / "merged"
    )
    shards = sorted(merged_dir.glob("*.safetensors"))
    assert len(shards) == 10, (
        "fixture 前置事实失败：替换前 fold0/merged 必须有 M0 观察的 10 个分"
        f"片：实际 {len(shards)}"
    )
    for shard in shards:
        shard.unlink()
    (merged_dir / "model-index.json").write_bytes(
        _fixture_pretty_json_bytes(
            {
                "schema_version": "tensile-merged-metadata-fixture/v1",
                "note": "非权重元数据（合成 fixture，非 safetensors 分片）",
            }
        )
    )


def _assert_legal_weight_run_entry_still_builds(build: Any, root: Path) -> None:
    """轻量对照：有证据的已确认 weight_run entry（H6a）仍正常构建。

    完整 H6a 正向契约由既有 H6a selector 复跑钉定；此处只做轻量对照，
    证明缺失分流与口径修正不得反向过宽到改变既有有证据 weight run
    entry 的行为（training_status 仍为 weights_observed）。
    """
    legal_document = build(root, [_confirmed_weight_run_entry()])
    legal_entries = (
        legal_document.get("entries") if isinstance(legal_document, Mapping) else None
    )
    assert isinstance(legal_entries, list) and len(legal_entries) == 1, (
        "有证据 weight run entry 不得被新增分流反向过宽拒绝：合法已确认 "
        "weight_run entry 必须仍正常构建恰含一条 entry 的 history-summary "
        f"文档（H6a 正向行为不回归）；实际 {type(legal_document).__name__} / "
        f"entries={legal_entries!r}"
    )
    legal_entry = legal_entries[0]
    assert isinstance(legal_entry, Mapping) and (
        legal_entry.get("training_status") == WEIGHT_RUN_TRAINING_STATUS
    ), (
        "合法有证据 weight_run entry 的 training_status 必须保持 "
        f"'weights_observed'（H6a 正向行为不回归）：实际 "
        f"{legal_entry.get('training_status')!r}"
    )


def test_confirmed_weight_run_entry_weight_existence_requires_weight_named_files(
    tmp_path: Path,
) -> None:
    r"""adapter_present 与 merged_present 必须用一致的权重存在性口径
    （只认权重命名文件，不得把非权重文件误判为权重）（H6b 第一切片，
    M1b history-summary，先写测试，不改 production）。

    H6b behavior —— reviewer 对 H6a 的 P3：adapter_present 使用递归任
    意文件判定，merged_present 使用顶层 safetensors 判定，两者口径不
    一致。对已确认 weight run 历史条目（H6a 同一 entry：kind
    ``weight_run``、source_legacy_id ``v4.1-phase2-source-aware-v1-"
    "seed3407``、status ``user_confirmed``）调用
    ``build_history_summary(root, [entry])``：
    1. 口径基线（H6a 不回归）：fold0/adapter 与 fold0/merged 均有权重
       文件时（H6a fixture），adapter_present / merged_present 均为已
       知 True，training_status == weights_observed —— 证明口径收紧不
       是把一切判 False；
    2. 场景 A（adapter 非权重文件）：fold0/adapter 只剩非权重元数据文
       件（adapter_config.json + README.md，目录可观察、无任何权重命
       名文件）、fold0/merged 仍带 10 个分片时，adapter_present 必须
       为已知 False（{value: False, source} 形态，来源指回声明 run 源
       且指回 fold0 观察位置）—— 非权重文件不得使 adapter_present 为
       True；merged_present 保持已知 True；entry 照常构建不 blocked
       （merged 权重证据足够，H6a 任一证据规则保持），training_status
       仍为 weights_observed（merged 权重存在性证据支撑分类）；
    3. 场景 B（merged 非权重文件）：fold0/adapter 恢复权重文件、
       fold0/merged 只剩非权重元数据文件（model-index.json，无任何
       safetensors）时，merged_present 必须为已知 False、
       adapter_present 为已知 True —— merged 口径不得反向放宽为任意
       文件（防"统一口径"向更宽方向统一）；entry 照常构建，
       training_status 仍为 weights_observed（adapter 权重证据足够）；
    4. 两个场景均保持 H6a 其余行为：fold_scope 已知 "fold0"；九个核心
       训练参数字段级 unknown（sibling planned 配置 seed 3411 与归档诱
       饵 manifest seed 9999 不得走私，参数名 / 引用名反走私）；不声明
       completed / passed / eval / model / verif / hash / integrity /
       checksum / sha 命名族存在性值；entry_id 为文档内 slug 且非正式
       身份，文档内任何字符串都不是 <kind>-v<协议>-r<N> 正式身份；未
       声明 sibling ID 不得进入文档任何字符串（不扫描 sibling）；
    5. 纯构建零写入：每次 build 全树快照逐字节不变（不写
       history-summary 文件、不创建 records/、不改 legacy 源树）；不就
       地修改传入 entry。

    fixture：与 H6a 同款三件套（_write_full_history_prompt_registry +
    _write_prepare_only_runs_layout + _write_weight_run_root_sibling_
    layout）。场景 A/B 是对声明 run 的 fixture mutation（H4 同款先例：
    先合法对照、后 mutation）：场景 A 只移除 adapter 权重文件并写入两
    个非权重元数据文件（内容不含核心训练参数 token，不新增参数来源歧
    视面）；场景 B 恢复 adapter 权重、移除 merged 分片并写入一个非权
    重元数据文件。两次 build 均单 entry，未声明 sibling 保持完好。

    RED Gate 设计（H6b）：build_history_summary 入口与 weight_run 分流
    已存在（H6a 已 GREEN），RED 不经入口缺失分支给出。当前实现
    adapter_present 以递归任意文件判定 —— 场景 A 的 adapter_config.json
    使 adapter_present == True，由该已知事实值断言（期望已知 False）钉
    出"非权重文件被误判为权重"；场景 B 断言当前实现已满足（merged 本
    就按 safetensors 判定），作为回归钉防"统一口径"时反向放宽 merged。
    场景 A 先失败即 RED（场景 B 断言不执行）；fixture 前置事实、口径
    基线与全树快照真实执行后才失败。

    捕获的合理但错误实现：
    - adapter_present 沿用递归任意文件判定（当前实现）-> 场景 A
      adapter_present 值断言失败（True != False）；
    - "统一口径"时把 merged 放宽为任意文件口径 -> 场景 B
      merged_present 值断言失败（True != False）；
    - 把可观察目录中的无权重状态标为 unknown 而非已知 False（缺席不
      可观察化）-> 场景 A/B 的 {value: False, source} 形态断言失败；
    - adapter 非权重文件时 fail-closed 拒绝（无视 merged 权重证据）->
      场景 A 转译后的显式 AssertionError 判失败；
    - weights_observed 误改为要求 adapter 权重证据（任一证据规则被改）
      -> 场景 A/B training_status 断言失败；
    - 从 sibling（planned 配置 seed 3411、归档诱饵 manifest seed 9999）
      登记已知参数 -> 核心参数 unknown / 反走私断言失败；
    - 声明训练完成 / passed / 评测 / model 身份 / 哈希已验证 -> claims
      扫描失败；
    - 扫描 runs 目录生成 sibling 条目或取 sibling 事实 -> entries 数量
      / sibling ID 断言失败；
    - 构建路径写盘 -> 全树快照对比失败；
    - 就地改写传入 entry -> 输入不变断言失败。

    fold0 缺失但 run 目录存在的其余结构形态、fold0/adapter 与 merged
    均无权重命名文件（完全无权重证据）的分流方向（fail-closed 保持还
    是字段级 unknown）、merged 软链接来源链、有证据的核心训练参数提
    取、多 entry 批量、eval/model 历史条目、history-summary 文件写入
    与 CLI 不在本切片（留后续）。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（H6b 仅新增用
      例与配套 helper/常量及模块 docstring 清单条目，不改 production）。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （与 H1–H6a binding 记录一致，``[tool.pytest.ini_options]
      testpaths / pythonpath`` 解析依赖该文件）。
    - 命令（新 selector）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_confirmed_weight_run_entry_weight_existence_requires_weight_named_files``
    - RED failure signature：恰一个失败用例（本 selector），失败为场
      景 A 的 adapter_present 已知值断言（实际 True != 期望 False，
      "非权重文件不得误判为权重"）；fixture 前置事实、口径基线与入
      口解析全部不失败；不出现 ModuleNotFoundError / ImportError /
      AttributeError 或原始异常直接充当 RED 结论。
    - 既有 selector 复跑（回归钉）：H1–H6a 小 selector（-k 同口径八个
      用例名）27 passed；全 migration 文件 RED 时点：全部既有用例
      passed + 本 selector 失败（失败恰为本 selector）。
    """
    _write_full_history_prompt_registry(tmp_path)
    _write_prepare_only_runs_layout(tmp_path)
    _write_weight_run_root_sibling_layout(tmp_path)
    declared_run_dir = tmp_path / "workspace" / "runs" / WEIGHT_RUN_DECLARED_ID
    adapter_dir = declared_run_dir / "fold0" / "adapter"
    merged_dir = declared_run_dir / "fold0" / "merged"

    # ---- fixture 前置事实（对齐 M0/H6a）：权重文件真实存在（口径基线
    #      非空洞：真实权重文件使 *_present 为 True）；sibling 诱饵与
    #      prompt registry 完整；目标根不存在。----
    assert (adapter_dir / "adapter_model.safetensors").is_file(), (
        "fixture 前置事实失败：声明 run 的 fold0/adapter 必须有 M0 观察的"
        "权重文件（口径基线：真实权重文件使 adapter_present 为 True）"
    )
    assert len(sorted(merged_dir.glob("*.safetensors"))) == 10, (
        "fixture 前置事实失败：声明 run 的 fold0/merged 必须有 M0 观察的 "
        "10 个分片"
    )
    assert (declared_run_dir / "evidence_archive").is_dir(), (
        "fixture 前置事实失败：声明 run 必须有 M0 观察的 evidence_archive"
    )
    root_sibling_dir = tmp_path / "workspace" / "runs" / WEIGHT_RUN_ROOT_SIBLING_ID
    assert (root_sibling_dir / "adapter" / "adapter_model.safetensors").is_file(), (
        "fixture 前置事实失败：run 根结构 sibling 必须存在（反扫描诱饵）"
    )
    planned_config = yaml.safe_load(
        (
            tmp_path
            / "workspace"
            / "runs"
            / PREPARE_ONLY_RUN_V1_ID
            / "prepared-config-untrained"
            / "train.yaml"
        ).read_bytes()
    )
    assert planned_config.get("seed") == 3411 and "learning_rate" in planned_config, (
        "fixture 前置事实失败：sibling planned 配置必须真实携带参数（走私诱饵）"
    )
    sibling_manifest = json.loads(
        (
            root_sibling_dir / "evidence_archive" / "training_run_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert sibling_manifest.get("seed") == 9999, (
        "fixture 前置事实失败：sibling 归档诱饵 manifest 必须携带合成参数"
    )
    for prompt_source_id in (
        HISTORY_SIBLING_SOURCE_ID,
        CONFIRMED_PROMPT_SOURCE_ID,
        _THIRD_REGISTRY_SOURCE_ID,
    ):
        prompt_dir = tmp_path / "pipeline" / "prompt_registry" / prompt_source_id
        assert (prompt_dir / "manifest.json").is_file() and (
            prompt_dir / "prompt.yaml"
        ).is_file(), (
            f"fixture 前置事实失败：legacy prompt registry 条目 {prompt_source_id} "
            "必须完整（反扫描诱饵依赖）"
        )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    entry = _confirmed_weight_run_entry()
    expected_entry = _confirmed_weight_run_entry()

    # ---- 行为 1：口径基线（H6a 不回归）—— 真实权重文件使两个
    #      *_present 均为已知 True，training_status 为 weights_observed
    #      （证明口径修正不是把一切判 False / 拒绝一切）。----
    before_baseline = _snapshot_tree(tmp_path)
    baseline_document = build(tmp_path, [_confirmed_weight_run_entry()])
    baseline_entries = baseline_document.get("entries")
    assert isinstance(baseline_entries, list) and len(baseline_entries) == 1, (
        "口径基线（H6a 不回归）：完整权重 fixture 下 entry 必须正常构建恰含"
        f"一条：实际 {baseline_entries!r}"
    )
    baseline_entry = baseline_entries[0]
    assert isinstance(baseline_entry, Mapping), (
        "口径基线 entry 必须是 mapping：实际 "
        f"{type(baseline_entry).__name__!r}"
    )
    baseline_facts = baseline_entry.get("facts")
    assert isinstance(baseline_facts, Mapping), (
        "口径基线 entry 必须携带 facts：实际 "
        f"{type(baseline_facts).__name__!r}"
    )
    for name, expected_value in (
        (WEIGHT_RUN_FOLD_SCOPE_FACT, "fold0"),
        (WEIGHT_RUN_ADAPTER_PRESENT_FACT, True),
        (WEIGHT_RUN_MERGED_PRESENT_FACT, True),
    ):
        assert name in baseline_facts, (
            f"口径基线 facts 必须包含 {name}（H6a 正向行为不回归）：实际键集 "
            f"{sorted(baseline_facts)}"
        )
        _assert_h6_known_fact(
            baseline_facts[name],
            name=name,
            run_id=WEIGHT_RUN_DECLARED_ID,
            expected_value=expected_value,
            must_reference_fold=(name != WEIGHT_RUN_FOLD_SCOPE_FACT),
        )
    assert (
        baseline_entry.get("training_status") == WEIGHT_RUN_TRAINING_STATUS
    ), (
        "口径基线 training_status 必须保持 weights_observed（H6a 正向行为不"
        f"回归）：实际 {baseline_entry.get('training_status')!r}"
    )
    assert _snapshot_tree(tmp_path) == before_baseline, (
        "口径基线 build 必须纯构建零写入（H6a 不回归）"
    )

    # ---- 场景 A mutation：adapter 只剩非权重元数据文件（merged 权重
    #      仍在）。钉定 mutation 生效。----
    _replace_declared_adapter_weights_with_non_weight_files(tmp_path)
    assert not any(adapter_dir.rglob("*.safetensors")), (
        "fixture 前置事实失败：场景 A 下 fold0/adapter 必须无任何权重命名文"
        "件（存在性判定只应看到非权重元数据文件）"
    )
    assert (adapter_dir / "adapter_config.json").is_file() and (
        adapter_dir / "README.md"
    ).is_file(), (
        "fixture 前置事实失败：场景 A 下 fold0/adapter 必须真实携带非权重"
        "元数据文件（adapter_present 判定对象真实存在）"
    )
    assert len(sorted(merged_dir.glob("*.safetensors"))) == 10, (
        "fixture 前置事实失败：场景 A 下 fold0/merged 必须仍有 10 个分片"
        "（merged 权重证据足够，entry 不得因 adapter 非权重文件 blocked）"
    )

    before_scenario_a = _snapshot_tree(tmp_path)

    # ---- 行为 2：场景 A —— adapter 非权重文件不得误判为权重；merged
    #      权重证据足够，entry 照常构建且 weights_observed。----
    try:
        document = build(tmp_path, [entry])
    except Exception as exc:
        raise AssertionError(
            "fold0/adapter 只剩非权重元数据文件时 entry 必须照常构建"
            "（merged 权重存在性证据足够，H6a 任一证据规则保持，不得 "
            "fail-closed 拒绝）：实际抛出 "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        ) from exc
    scenario_a_entries = document.get("entries")
    assert isinstance(scenario_a_entries, list) and len(scenario_a_entries) == 1, (
        "场景 A 文档必须恰含声明的一条 entry（不得扫描 runs 目录生成 sibling "
        f"条目）：实际 {scenario_a_entries!r}"
    )
    scenario_a_summary = scenario_a_entries[0]
    assert isinstance(scenario_a_summary, Mapping), (
        "场景 A entry 必须是 mapping：实际 "
        f"{type(scenario_a_summary).__name__!r}"
    )
    assert scenario_a_summary.get("original_id") == WEIGHT_RUN_DECLARED_ID, (
        "场景 A entry 必须保留 original_id（H6a 正向行为不回归）：实际 "
        f"{scenario_a_summary.get('original_id')!r}"
    )
    assert scenario_a_summary.get("kind") == "weight_run", (
        "场景 A entry 必须保持声明 kind：实际 "
        f"{scenario_a_summary.get('kind')!r}"
    )
    assert scenario_a_summary.get("training_status") == WEIGHT_RUN_TRAINING_STATUS, (
        "场景 A 下 training_status 必须仍为 weights_observed（merged 权重存"
        "在性证据足够支撑分类，H6a 任一证据规则保持）：实际 "
        f"{scenario_a_summary.get('training_status')!r}"
    )
    scenario_a_facts = scenario_a_summary.get("facts")
    assert isinstance(scenario_a_facts, Mapping) and scenario_a_facts, (
        "场景 A entry 必须携带非空 facts：实际 "
        f"{scenario_a_facts!r}"
    )
    _assert_h6_known_fact(
        scenario_a_facts.get(WEIGHT_RUN_FOLD_SCOPE_FACT),
        name=WEIGHT_RUN_FOLD_SCOPE_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value="fold0",
    )
    # 核心断言（RED Gate）：非权重文件不得使 adapter_present 为 True ——
    # 观察到的缺席是已知 False（目录可观察，判定结果确定），不是 unknown。
    _assert_h6_known_fact(
        scenario_a_facts.get(WEIGHT_RUN_ADAPTER_PRESENT_FACT),
        name=WEIGHT_RUN_ADAPTER_PRESENT_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value=False,
        must_reference_fold=True,
    )
    _assert_h6_known_fact(
        scenario_a_facts.get(WEIGHT_RUN_MERGED_PRESENT_FACT),
        name=WEIGHT_RUN_MERGED_PRESENT_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value=True,
        must_reference_fold=True,
    )
    for name in WEIGHT_RUN_CORE_TRAIN_PARAM_FACTS:
        assert name in scenario_a_facts, (
            f"场景 A 下核心训练参数 {name} 不得从 facts 中消失（H6a 正向行为"
            f"不回归）：实际键集 {sorted(scenario_a_facts)}"
        )
        _assert_h6_fact_is_unknown(
            scenario_a_facts[name], name=name, run_id=WEIGHT_RUN_DECLARED_ID
        )
    for name, fact in scenario_a_facts.items():
        name_lower = str(name).lower()
        if any(token in name_lower for token in _H6_PARAM_NAME_TOKENS) or any(
            token in name_lower for token in _H6_REFERENCE_NAME_TOKENS
        ):
            _assert_h6_fact_is_unknown(
                fact, name=name, run_id=WEIGHT_RUN_DECLARED_ID
            )
    _assert_h6_no_completion_or_verification_claims(scenario_a_summary, "entry")
    scenario_a_strings = _document_string_fragments(document)
    for fragment in scenario_a_strings:
        assert not is_valid_version_id(fragment), (
            "场景 A 文档内不得出现任何正式身份：实际出现 "
            f"{fragment!r}"
        )
    for sibling_id in _H6B_UNDECLARED_SIBLING_IDS:
        assert not any(
            sibling_id in fragment for fragment in scenario_a_strings
        ), (
            f"场景 A 下未声明 sibling {sibling_id} 不得进入文档任何字符串（不"
            "扫描 sibling、不取 sibling 内容）"
        )
    assert _snapshot_tree(tmp_path) == before_scenario_a, (
        "场景 A build 必须纯构建零写入：全树快照逐字节不变"
    )
    assert not (tmp_path / "records").exists() and not (tmp_path / "docs").exists(), (
        "场景 A 纯构建不得创建 records/ 或 docs/（history-summary 只经返回值）"
    )
    assert entry == expected_entry, (
        "场景 A 全程不得就地改写传入 entry（H6a 输入事实保持不变）"
    )

    # ---- 场景 B mutation：adapter 权重恢复；merged 只剩非权重元数据
    #      文件。钉定 mutation 生效。----
    _restore_declared_adapter_weight_file(tmp_path)
    _replace_declared_merged_shards_with_non_weight_file(tmp_path)
    assert (adapter_dir / "adapter_model.safetensors").is_file(), (
        "fixture 前置事实失败：场景 B 下 fold0/adapter 必须恢复权重文件"
    )
    assert not any(merged_dir.glob("*.safetensors")), (
        "fixture 前置事实失败：场景 B 下 fold0/merged 必须无任何权重命名文"
        "件（merged_present 判定对象真实存在）"
    )
    assert (merged_dir / "model-index.json").is_file(), (
        "fixture 前置事实失败：场景 B 下 fold0/merged 必须真实携带非权重元"
        "数据文件（防 merged 口径反向放宽为任意文件）"
    )

    before_scenario_b = _snapshot_tree(tmp_path)

    # ---- 行为 3：场景 B —— merged 非权重文件不得误判为权重；adapter
    #      权重证据足够，entry 照常构建且 weights_observed。----
    try:
        document_b = build(tmp_path, [entry])
    except Exception as exc:
        raise AssertionError(
            "fold0/merged 只剩非权重元数据文件时 entry 必须照常构建"
            "（adapter 权重存在性证据足够，H6a 任一证据规则保持，不得 "
            "fail-closed 拒绝）：实际抛出 "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        ) from exc
    scenario_b_entries = document_b.get("entries")
    assert isinstance(scenario_b_entries, list) and len(scenario_b_entries) == 1, (
        "场景 B 文档必须恰含声明的一条 entry：实际 {scenario_b_entries!r}"
    )
    scenario_b_summary = scenario_b_entries[0]
    assert isinstance(scenario_b_summary, Mapping), (
        "场景 B entry 必须是 mapping：实际 "
        f"{type(scenario_b_summary).__name__!r}"
    )
    assert scenario_b_summary.get("original_id") == WEIGHT_RUN_DECLARED_ID, (
        "场景 B entry 必须保留 original_id：实际 "
        f"{scenario_b_summary.get('original_id')!r}"
    )
    assert scenario_b_summary.get("kind") == "weight_run", (
        "场景 B entry 必须保持声明 kind：实际 "
        f"{scenario_b_summary.get('kind')!r}"
    )
    assert scenario_b_summary.get("training_status") == WEIGHT_RUN_TRAINING_STATUS, (
        "场景 B 下 training_status 必须仍为 weights_observed（adapter 权重存"
        "在性证据足够支撑分类，H6a 任一证据规则保持）：实际 "
        f"{scenario_b_summary.get('training_status')!r}"
    )
    scenario_b_facts = scenario_b_summary.get("facts")
    assert isinstance(scenario_b_facts, Mapping) and scenario_b_facts, (
        "场景 B entry 必须携带非空 facts：实际 "
        f"{scenario_b_facts!r}"
    )
    _assert_h6_known_fact(
        scenario_b_facts.get(WEIGHT_RUN_FOLD_SCOPE_FACT),
        name=WEIGHT_RUN_FOLD_SCOPE_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value="fold0",
    )
    _assert_h6_known_fact(
        scenario_b_facts.get(WEIGHT_RUN_ADAPTER_PRESENT_FACT),
        name=WEIGHT_RUN_ADAPTER_PRESENT_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value=True,
        must_reference_fold=True,
    )
    _assert_h6_known_fact(
        scenario_b_facts.get(WEIGHT_RUN_MERGED_PRESENT_FACT),
        name=WEIGHT_RUN_MERGED_PRESENT_FACT,
        run_id=WEIGHT_RUN_DECLARED_ID,
        expected_value=False,
        must_reference_fold=True,
    )
    for name in WEIGHT_RUN_CORE_TRAIN_PARAM_FACTS:
        assert name in scenario_b_facts, (
            f"场景 B 下核心训练参数 {name} 不得从 facts 中消失（H6a 正向行为"
            f"不回归）：实际键集 {sorted(scenario_b_facts)}"
        )
        _assert_h6_fact_is_unknown(
            scenario_b_facts[name], name=name, run_id=WEIGHT_RUN_DECLARED_ID
        )
    for name, fact in scenario_b_facts.items():
        name_lower = str(name).lower()
        if any(token in name_lower for token in _H6_PARAM_NAME_TOKENS) or any(
            token in name_lower for token in _H6_REFERENCE_NAME_TOKENS
        ):
            _assert_h6_fact_is_unknown(
                fact, name=name, run_id=WEIGHT_RUN_DECLARED_ID
            )
    _assert_h6_no_completion_or_verification_claims(scenario_b_summary, "entry")
    scenario_b_strings = _document_string_fragments(document_b)
    for fragment in scenario_b_strings:
        assert not is_valid_version_id(fragment), (
            "场景 B 文档内不得出现任何正式身份：实际出现 "
            f"{fragment!r}"
        )
    for sibling_id in _H6B_UNDECLARED_SIBLING_IDS:
        assert not any(
            sibling_id in fragment for fragment in scenario_b_strings
        ), (
            f"场景 B 下未声明 sibling {sibling_id} 不得进入文档任何字符串（不"
            "扫描 sibling、不取 sibling 内容）"
        )
    assert _snapshot_tree(tmp_path) == before_scenario_b, (
        "场景 B build 必须纯构建零写入：全树快照逐字节不变"
    )
    assert not (tmp_path / "records").exists() and not (tmp_path / "docs").exists(), (
        "场景 B 纯构建不得创建 records/ 或 docs/（history-summary 只经返回值）"
    )
    assert entry == expected_entry, (
        "场景 B 全程不得就地改写传入 entry（H6a 输入事实保持不变）"
    )


def test_confirmed_weight_run_entry_missing_declared_source_records_unknown_without_blocking(
    tmp_path: Path,
) -> None:
    r"""声明 run 源缺失时 weight_run entry 不得消失：结构事实与核心参数
    进入字段级 unknown，整批不 blocked（H6b 第二切片，M1b history-
    summary，先写测试，不改 production）。

    H6b behavior —— 声明 run 源（workspace/runs/<source_legacy_id>）整
    个缺失（M0 known_gap 真实形态：source-inventory.yaml
    training_machine_run_evidence.known_gap：expected_run
    workspace/runs/v4.1-prompt-concise-cv-v1-seed3411 "训练机预期路
    径不存在"，meaning "不能断言模型在整台训练机上不存在；需沿历史
    报告定位"；object-mapping model_train_eval_history 将该 run 列为
    用户确认 history-only entry："训练机对应 run 路径缺失（known
    gap）"）时，对已确认 weight_run entry（H6a 同一 entry：kind
    ``weight_run``、source_legacy_id ``v4.1-phase2-source-aware-v1-"
    "seed3407``、status ``user_confirmed``，其声明源在构建前被整体移
    除）调用 ``build_history_summary(root, [entry])`` 必须：
    1. 返回 history-summary 文档，不得 fail-closed 拒绝使 entry 消失、
       整批不得 blocked（Spec："身份、权重或结果证据不足时，可以保存
       明确标注缺失的历史记录，不能把它作为完整的新正式对象供下游执
       行"、"不能取得的历史值标为未知并注明来源缺口"；H4 同口径先
       例：缺失与坏源可区分，缺失不是 blocked）；
    2. entries 恰含声明的一条：entry 不得静默消失，也不得扫描 runs 目
       录生成未声明条目；entry 级结构保持（original_id 保留原始 run
       ID、kind 保持 weight_run、history_only: true、formal_identity:
       "none"、entry_id 为文档内 slug 且非 <kind>-v<协议>-r<N> 正式身
       份）；
    3. 不输出无证据声明：training_status 不得为 weights_observed（源
       缺失时无任何权重观察证据；也不得信任 entry 声明代替重新观察）、
       completed、not_completed、prepared_only（M0 known_gap：路径缺
       失 —— 既非权重存在也非准备资料观察，四者均为伪造分类）；
       training_status 若存在必须为非空字符串；entry 内任何键名携带
       completed / passed / eval / model / verif / hash / integrity /
       checksum / sha 命名族 token 的位置不得声明存在性值；
    4. 结构事实与核心参数全部字段级 unknown（缺失不是删字段，也与
       已知 False 可区分 —— 源缺失时判定不可观察）：fold_scope /
       adapter_present / merged_present 与九个核心训练参数均携带非空
       unknown_reason 与指回声明 run 源（workspace/runs/<run_id>）的
       attempted_source，不携带非 None value（缺失源不得伪装成已知
       值，不得把 H6a 的 M0 结构观察声明值当作仍然成立）；参数名 /
       数据与 Prompt 引用名反走私：不得从 sibling（planned 配置 seed
       3411、归档诱饵 manifest seed 9999）登记任何已知值；
    5. 纯构建零写入：全树快照逐字节不变（不写 history-summary 文件、
       不创建 records/、不修复/重建缺失源、不改 sibling）；不就地修
       改传入 entry；
    6. 合法对照（mutation 前）：H1 prompt_history、H5 prepare_only_run
       与 H6a 有证据 weight_run entry 均仍正常构建（缺失分流不得过宽）。

    fixture：与 H6a 同款三件套；mutation 为整体移除声明 run 目录（M0
    known_gap 形态：预期路径不存在），未声明 sibling（两个 prepare-only
    run、run 根结构 weight run、三个 prompt registry 条目）保持完好。

    RED Gate 设计（H6b）：build_history_summary 入口与 weight_run 分流
    已存在（H6a 已 GREEN），RED 不经入口缺失分支给出。当前实现（H6a）
    对声明 run 源缺失一律抛 PromptMigrationBlocked（"声明源 ...
    缺失：fold0 权重结构未观察到，weight run 历史条目的 known gap 处
    理不在本切片内（fail-closed，不伪造已知事实）"）—— 缺失被当
    blocked、entry 消失、无字段级 unknown_reason / attempted_source。
    本测试把该拒绝转成显式行为 AssertionError（原始域错误经 cause 链
    保留，不得直接充当 RED 结论）钉出"缺失资料字段级 unknown 行为缺
    失"；fixture 构建、合法对照、mutation 生效前置断言与全树快照均
    真实执行后才失败。若实现改为信任 entry 声明输出 weights_observed
    （非重新观察），由无证据声明断言钉出。

    捕获的合理但错误实现：
    - 声明源缺失 fail-closed（当前实现）-> 转译后的显式 AssertionError
      判失败；
    - entry 静默消失（跳过缺失源条目）/ 返回空文档 -> entries 数量断言
      失败；
    - 信任 entry 声明输出 training_status == weights_observed（M0 历
      史观察代替重新观察）-> 无证据声明断言失败；
    - 输出 completed / not_completed / prepared_only -> 无证据声明断言
      失败；
    - 结构事实从 facts 中消失（删字段）或伪造已知值（含已知 False ——
      源缺失时缺席不可观察）-> unknown 形态断言失败；
    - 从 sibling（planned 配置、归档诱饵、其余 run 目录）取参数 / 引
      用 / 结构事实冒充 -> unknown 形态 + sibling ID 断言失败；
    - 缺失分流过宽：合法有证据 weight_run entry 也被改判 unknown ->
      合法对照 training_status 断言失败；
    - 构建路径写盘（history-summary 文件、records/、重建/修复缺失源）
      -> 全树快照对比失败；
    - 就地改写传入 entry -> 输入不变断言失败。

    fold0 缺失但 run 目录存在的其余结构形态、fold0/adapter 与 merged
    均无权重命名文件（完全无权重证据）的分流方向、merged 软链接来源
    链、有证据的核心训练参数提取、多 entry 批量、eval/model 历史条
    目、history-summary 文件写入与 CLI 不在本切片（留后续）。

    Binding（证据绑定，供复跑核对）：
    - 测试文件：``tests/versioning/test_migration.py``（H6b 仅新增用
      例与配套 helper/常量及模块 docstring 清单条目，不改 production）。
    - ``pyproject.toml`` sha256（本切片时点）：
      ``424c669b6d8150fe0245de88777d05adcd2f5aeeeaa8a67d57c9d4186fc7ee1f``
      （与 H1–H6a binding 记录一致，``[tool.pytest.ini_options]
      testpaths / pythonpath`` 解析依赖该文件）。
    - 命令（新 selector）：``.venv/bin/python -m pytest -q
      tests/versioning/test_migration.py -k
      test_confirmed_weight_run_entry_missing_declared_source_records_unknown_without_blocking``
    - RED failure signature：恰一个失败用例（本 selector），失败为转
      译后的 AssertionError（"声明 run 源缺失必须进入字段级 unknown…"
      ），cause 链保留原始 PromptMigrationBlocked（声明源缺失被当
      blocked、entry 消失）；fixture 前置事实、合法对照与 mutation 生
      效断言全部不失败；不出现 ModuleNotFoundError / ImportError /
      AttributeError 或原始异常直接充当 RED 结论。
    - 既有 selector 复跑（回归钉）：H1–H6a 小 selector（-k 同口径八
      个用例名）27 passed；全 migration 文件 RED 时点：全部既有用例
      passed + 本 selector 失败（失败恰为本 selector）。
    """
    _write_full_history_prompt_registry(tmp_path)
    _write_prepare_only_runs_layout(tmp_path)
    _write_weight_run_root_sibling_layout(tmp_path)
    declared_run_dir = tmp_path / "workspace" / "runs" / WEIGHT_RUN_DECLARED_ID
    runs_root = tmp_path / "workspace" / "runs"

    # ---- fixture 前置事实（mutation 前）：声明 run 源完整呈 fold0 结
    #      构；未声明 sibling 完整（缺失只能由声明源移除引起）；prompt
    #      registry 完整（合法对照依赖）；目标根不存在。----
    assert declared_run_dir.is_dir() and (declared_run_dir / "fold0").is_dir(), (
        "fixture 前置事实失败：声明 run 源必须完整（mutation 才能钉定缺失）"
    )
    assert (
        declared_run_dir / "fold0" / "adapter" / "adapter_model.safetensors"
    ).is_file() and any(
        (declared_run_dir / "fold0" / "merged").glob("*.safetensors")
    ), (
        "fixture 前置事实失败：声明 run 源必须真实携带 M0 观察的权重结构"
        "（合法对照依赖）"
    )
    for sibling_id in (
        PREPARE_ONLY_RUN_V1_ID,
        PREPARE_ONLY_RUN_V2_ID,
        WEIGHT_RUN_ROOT_SIBLING_ID,
    ):
        assert (runs_root / sibling_id).is_dir(), (
            f"fixture 前置事实失败：未声明 sibling {sibling_id} 必须存在（反"
            "扫描诱饵与走私诱饵依赖）"
        )
    for prompt_source_id in (
        HISTORY_SIBLING_SOURCE_ID,
        CONFIRMED_PROMPT_SOURCE_ID,
        _THIRD_REGISTRY_SOURCE_ID,
    ):
        prompt_dir = tmp_path / "pipeline" / "prompt_registry" / prompt_source_id
        assert (prompt_dir / "manifest.json").is_file() and (
            prompt_dir / "prompt.yaml"
        ).is_file(), (
            f"fixture 前置事实失败：legacy prompt registry 条目 {prompt_source_id} "
            "必须完整（合法对照依赖）"
        )
    assert not (tmp_path / "records").exists()
    assert not (tmp_path / "docs").exists()

    build = _resolve_history_summary_entry()
    assert build is not None, (
        "history-summary 纯构建行为缺失：versioning.migration 未提供 "
        "build_history_summary 入口（当前 behavior 未实现）"
    )

    entry = _confirmed_weight_run_entry()
    expected_entry = _confirmed_weight_run_entry()

    # ---- 行为 6：合法对照（mutation 前、fixture 完整）—— H1/H5/H6a
    #      正向行为不回归，缺失分流不得过宽到拒绝有证据 entry。----
    _assert_legal_history_entry_still_builds(build, tmp_path)
    _assert_legal_prepare_only_run_entry_still_builds(build, tmp_path)
    _assert_legal_weight_run_entry_still_builds(build, tmp_path)

    # ---- mutation：声明 run 源整体缺失（M0 known_gap 形态：预期路径
    #      不存在）；未声明 sibling 保持完好。----
    shutil.rmtree(declared_run_dir)
    assert not declared_run_dir.exists(), (
        "fixture 前置事实失败：mutation 后声明 run 源目录必须不存在"
        "（M0 known_gap：预期路径缺失）"
    )
    for sibling_id in (
        PREPARE_ONLY_RUN_V1_ID,
        PREPARE_ONLY_RUN_V2_ID,
        WEIGHT_RUN_ROOT_SIBLING_ID,
    ):
        assert (runs_root / sibling_id).is_dir(), (
            f"fixture 前置事实失败：mutation 后未声明 sibling {sibling_id} "
            "必须保持完好（缺失只能由声明源引起）"
        )

    before = _snapshot_tree(tmp_path)

    # ---- 行为 1：声明源缺失不得整批 blocked / entry 不得消失。----
    try:
        document = build(tmp_path, [entry])
    except Exception as exc:
        raise AssertionError(
            "声明 run 源缺失必须进入字段级 unknown（unknown_reason / "
            "attempted_source 指回声明 run 源），entry 不得消失、整批不得 "
            "blocked（M0 known_gap 是允许保留的明确标注缺失的历史记录，"
            "Spec：身份、权重或结果证据不足时保存明确标注缺失的历史记录；"
            "H6b 缺失资料形态行为缺失）：实际抛出 "
            f"{type(exc).__module__}.{type(exc).__name__}: {exc}"
        ) from exc
    assert isinstance(document, Mapping), (
        "声明源缺失必须返回 history-summary 文档（mapping）：实际 "
        f"{type(document).__name__!r}"
    )
    assert (
        document.get("history_summary_schema")
        == "tensile-migration/history-summary/v1"
    ), (
        "声明源缺失不得整批 blocked：必须返回 history-summary 文档：实际 "
        f"{document.get('history_summary_schema')!r}"
    )
    document_entries = document.get("entries")
    assert isinstance(document_entries, list), (
        "history-summary 文档的 entries 必须是 list：实际 "
        f"{type(document_entries).__name__!r}"
    )
    assert len(document_entries) == 1, (
        "声明源缺失时 entry 不得静默消失，也不得扫描 runs 目录生成未声明条"
        f"目：文档必须恰含声明的一条 entry：实际 {len(document_entries)} 条"
    )
    summary_entry = document_entries[0]
    assert isinstance(summary_entry, Mapping), (
        "history-summary entry 必须是 mapping：实际 "
        f"{type(summary_entry).__name__!r}"
    )

    # ---- entry 级结构保持（original_id / kind / history_only /
    #      formal_identity / entry_id）。----
    assert summary_entry.get("original_id") == WEIGHT_RUN_DECLARED_ID, (
        "缺失源 entry 必须保留 original_id（原始 run ID 来源是 entry 声明而非"
        f"源目录）：实际 {summary_entry.get('original_id')!r}"
    )
    assert summary_entry.get("kind") == "weight_run", (
        "缺失源 entry 必须保持声明的 kind（weight_run）：实际 "
        f"{summary_entry.get('kind')!r}"
    )
    assert summary_entry.get("history_only") is True, (
        "缺失源 entry 必须标记 history_only: true：实际 "
        f"{summary_entry.get('history_only')!r}"
    )
    assert summary_entry.get("formal_identity") == "none", (
        "缺失源 entry 必须标记 formal_identity: none（不分配新正式身份）："
        f"实际 {summary_entry.get('formal_identity')!r}"
    )
    entry_id = summary_entry.get("entry_id")
    assert isinstance(entry_id, str) and entry_id, (
        "缺失源 entry 必须携带非空字符串 entry_id（文档内 slug）：实际 "
        f"{entry_id!r}"
    )
    assert not is_valid_version_id(entry_id), (
        "entry_id 必须是文档内 slug，不得是 <kind>-v<协议>-r<N> 正式身份："
        f"实际 {entry_id!r}"
    )

    # ---- 行为 3：不输出无证据声明（training_status 四个伪造分类值全
    #      部禁止；无权重观察证据，也不得信任 entry 声明代替重新观察）。----
    training_status = summary_entry.get("training_status")
    assert training_status != WEIGHT_RUN_TRAINING_STATUS, (
        "声明 run 源缺失时不得输出 training_status == 'weights_observed'"
        "（无任何权重观察证据；也不得信任 entry 声明代替重新观察 —— 缺失"
        "资料的分类是伪造）：实际 "
        f"{summary_entry.get('training_status')!r}"
    )
    assert training_status != "completed", (
        "声明 run 源缺失时不得输出 completed（无证据的完成声明，M0 明确排除"
        f"）：实际 {summary_entry.get('training_status')!r}"
    )
    assert training_status != "not_completed", (
        "声明 run 源缺失时不得输出 not_completed（“不等于完成”不等于“未完"
        "成”，无证据的负向声明同样禁止）：实际 "
        f"{summary_entry.get('training_status')!r}"
    )
    assert training_status != "prepared_only", (
        "声明 run 源缺失时不得输出 prepared_only（该 run 无任何准备资料观察："
        "M0 known_gap meaning：预期路径缺失，非权重存在也非准备资料观察，"
        "分类是伪造）：实际 "
        f"{summary_entry.get('training_status')!r}"
    )
    if training_status is not None:
        assert isinstance(training_status, str) and training_status.strip(), (
            "缺失源 entry 的 training_status 若存在必须为非空字符串：实际 "
            f"{training_status!r}"
        )

    # ---- 行为 4：结构事实与核心参数全部字段级 unknown（缺失不是删字
    #      段，也不是已知 False —— 源缺失时缺席不可观察）。----
    facts = summary_entry.get("facts")
    assert isinstance(facts, Mapping) and facts, (
        "缺失源 entry 必须携带非空 facts（结构事实与核心参数进入字段级 "
        f"unknown，不是删字段）：实际 {facts!r}"
    )
    for name in WEIGHT_RUN_KNOWN_FACTS + WEIGHT_RUN_CORE_TRAIN_PARAM_FACTS:
        assert name in facts, (
            f"声明源缺失时结构事实/核心参数 {name} 不得从 facts 中消失（缺失"
            f"进入字段级 unknown，不是删字段）：实际键集 {sorted(facts)}"
        )
        _assert_h6_fact_is_unknown(
            facts[name], name=name, run_id=WEIGHT_RUN_DECLARED_ID
        )
    for name, fact in facts.items():
        name_lower = str(name).lower()
        if any(token in name_lower for token in _H6_PARAM_NAME_TOKENS) or any(
            token in name_lower for token in _H6_REFERENCE_NAME_TOKENS
        ):
            _assert_h6_fact_is_unknown(
                fact, name=name, run_id=WEIGHT_RUN_DECLARED_ID
            )

    # ---- 行为 3 兼：不声明训练完成 / 通过 / 评测 / model 身份 / 权重
    #      完整性与哈希验证。----
    _assert_h6_no_completion_or_verification_claims(summary_entry, "entry")

    # ---- 不分配任何新正式身份；不扫描 sibling —— 未声明 sibling 的
    #      ID 不得进入文档任何字符串（缺失 run 的已知事实不得从
    #      sibling 取内容冒充）。----
    all_strings = _document_string_fragments(document)
    for fragment in all_strings:
        assert not is_valid_version_id(fragment), (
            "history-summary 文档内不得出现任何 <kind>-v<协议>-r<N> 正式身份："
            f"实际出现 {fragment!r}"
        )
    for sibling_id in _H6B_UNDECLARED_SIBLING_IDS:
        assert not any(sibling_id in fragment for fragment in all_strings), (
            f"声明源缺失时未声明 sibling {sibling_id} 不得进入 history-summary "
            "文档任何字符串（unknown 事实不得从 sibling 取内容冒充已知值）"
        )

    # ---- 行为 5：纯构建零写入 —— 全树逐字节不变（不写 history-summary
    #      文件、不创建 records/、不修复/重建缺失源、不改 sibling）。----
    assert _snapshot_tree(tmp_path) == before, (
        "缺失形态的纯构建必须零写入：全树快照逐字节不变（不写 history-summary "
        "文件、不创建 records/ 或任何目标条目、不修复或重建缺失的声明 run "
        "源）"
    )
    assert not (tmp_path / "records").exists(), (
        "缺失形态纯构建不得创建 records/ 或任何正式对象条目"
    )
    assert not (tmp_path / "docs").exists(), (
        "缺失形态纯构建不得写入 history-summary 文件（文档只经返回值给出）"
    )
    for path in tmp_path.rglob("*"):
        assert "history-summary" not in path.name, (
            f"缺失形态纯构建不得落盘任何 history-summary 命名文件：发现 {path}"
        )

    # ---- 不就地修改传入 entry。----
    assert entry == expected_entry, (
        "全程不得就地改写传入 entry（H6b 输入事实保持不变）"
    )
