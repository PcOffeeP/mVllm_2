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
        #   件/目录，不随封存去写位。批级恢复、凭证失配拒绝、重跑
        #   幂等跳过不在本切片。

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

范围边界：本文件只覆盖 Prompt 迁移（T1–T10）、T11–T14 数据迁移批级
只读预检切面（ready 正向、目标冲突边界、已钉扎 manifest provenance
门、manifest files 声明的 payload 文件哈希复算门）与 T15–T16 单对象
data 真实转换切面 —— T1 ready 正向
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
失配、重跑幂等；批内乱序输入（r1 先于 r2）的写入顺序行为不绑定）；
以上切片之外
不实现/不要求
data 真实转换的其余行为（批级多对象乱序写入顺序、
批级恢复、凭证失配拒绝、重跑幂等跳过）、data blocked 反向其余场景（身份契约收紧、legacy 源
release 目录/manifest 缺失、声明的 payload 文件缺失——该存在性分支
由既有 production 检查 blocked，本文件未单列用例钉定）、history-summary、CLI、自动恢复/续传逻辑（冲突场景只断言 blocked 与零写入；
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
    ImmutableReleaseError,
    assert_payload_sealed,
    load_release_metadata,
    validate_training_reference,
)
from versioning.prompts import (
    PROMPT_REQUIRED_FIELDS,
    PromptConflict,
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
