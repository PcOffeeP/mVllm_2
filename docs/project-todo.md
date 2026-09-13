# Project TODO

本文件是项目持续维护的任务台账，记录用户目标、当前差距、执行顺序和验证结果。维护规则见 [AGENTS.md](../AGENTS.md#todo-执行与维护)，不另建平行 TODO。

- 更新日期：随“最近维护记录”持续更新，不以文件头日期代替记录。
- 本轮依据：迁移任务已确认Spec/Plan、第47节整包代码审查及本轮第48节交付核查和模型主线只读证据。详细证据见下述目标条目与验证记录；其他任务保留其原先注明的机器、代码版本和授权边界。
- 主 Agent 汇总并维护，其他执行 Agent 按 AGENTS.md 交接证据和新发现。任务标识固定，不随排序改变。

## 下一步与执行顺序

**当前执行入口（用户已确认收口拆分）**：优先完成工程分支的合并前验收矩阵与train实际输入预检，同时整理MODEL-DIAG新方案；最终模型任务按原依赖继续，清理降为非阻塞配套。工程交付终点为获授权合并Codeup main并核验落点，不能把合并当作模型质量通过。下方历史批次的“下一步”以此处及收口矩阵为准。

### 分支收口矩阵

| 分类 | 现有任务/范围 | 当前事实与剩余动作 | 收口条件 |
| --- | --- | --- | --- |
| 合并前 | VERSION-CONTROL-FORMAL-MIGRATION：train数据与Prompt | M3迁移/真实媒体对照已完成；新store仍有外部媒体依赖。第59节当前r2/Prompt及1678媒体完整内存输入预检通过；后续训练冻结仍需显式配置 | 实际输入全部可解析，来源与引用一致；不能删除仍被引用的旧路径 |
| 合并前 | M4/M5实际执行与服务接管 | CPU接线和旧入口拒绝已有；真实GPU/模型加载成功路径仍缺 | 每个缺口补实机证据，或明确接受后续转交边界；未裁决前保留阻塞，不能仅因模型任务后置而豁免 |
| 合并前或明确转交 | M6恢复范围 | store级异根恢复已验收；真实硬盘、大型产物和外部依赖恢复未完整验收 | 移动硬盘按既有决定单独未完成；其他缺口逐项裁决，不推定已接受整体豁免 |
| 合并前 | M8最终交付 | 整包审查及四交付文档核查已有冻结范围；后续代码另有局部审查 | 对最终范围确认审查覆盖、必要回归、文档/证据一致性；不重做已完成历史修复 |
| 合并前 | RELEASE-POINTER、CONTRACT-NAMING | 旧指针目标适用性待决，契约命名为低优先级 | 裁决是否取消或明确后续任务；不恢复旧写入、不顺手重命名 |
| 合并及合并后 | Git交付 | 当前仅核对本地引用，未刷新Codeup或执行集成 | 刷新两机/目标远端、精确PR范围、用户push/merge授权；核验main落点、同步和适用冒烟后关闭工程任务 |
| 后续模型 | HOLDOUT-BUILD | test接线已完成，来源使用资格和真实处理/审查/封存仍缺 | 沿用原TEST-POLICY及七门，不复用已暴露测试；冻结就绪支撑最终训练 |
| 后续模型 | MODEL-DIAG → FINAL-TRAIN → MODEL-QUALITY | 旧三折权重缺失，不持续搜寻；新诊断方案待确认 | train单折可行性→三折开发验证→全量最终训练→一次性test→晋级/真实服务验收，分别落实执行授权 |
| 不阻塞 | MODEL-ARCHIVE | 条件清理已授权；89个train视频副本验签，占用检查未完成，删除0 | 条件满足才清理；不占用模型与工程收口主线 |

**当前推荐第一项**：整理train真实输入预检与M4/M5/M6逐项缺口，给出具体“补证/转交”裁决单；这一步无需训练或test使用。工程合并与最终模型验收分开，不表示已有真实环境缺口自动解除。

2026-09-13 Linux续办（Codex）：用户明确指出初始test视频已划分，授权训练机调查。已找到`workspace/data/source/splits/test.json`的21个test source，原视频21/21存在，train分支89source，三折与test无交集；不再要求用户重新提供既定路径。Linux隔离7b0e01d5已运行本批同代码427 passed/1 skipped、两组exit0，七保护文件未变。详见[第52节](results/version-control-migration/verification.md#linux-test-branch-source-20260913)。历史claim/gate确认旧release已暴露，媒体凭据文件名覆盖其中20source，video_0005无该批候选凭据；原旧release目录缺失，逐source最终消费映射未完整复核。既定划分已找到，不等于全体可作为新独立测试；保留TEST-POLICY，不重划、不复测、不擅自放行。

**现行术语**：train 数据分支用于三折训练/验证及全量训练；test 数据分支仅用于最终独立测试。代码/配置仍使用 `development` / `holdout` / `test_audit`，历史身份不改。下文前轮记录中的旧称按此对应解释。

2026-09-13 续办（Codex）：用户已确认完整test数据分支并授权实施；Spec042f335e、Plan66416f0f、代码abafdbf2。独立受限处理、全量人工审查、封存发布和最终full模型测试已接通；Mac合成回归427 passed/1 skipped、两进程均exit0，局部独立代码及入口说明审查通过。详见[第51节](results/version-control-migration/verification.md#test-branch-20260913)。真实新source、人工审查和适用构建/测试使用授权仍未就绪，HOLDOUT-BUILD不关闭；此为第51节Mac阶段记录；随后Linux独立验收见第52节，不借用前批结果。

**M8 整包代码差异审查已通过，范围冻结于 `f1b7d8a3→d9ec1227`（140提交/152文件）；不重做已完成修复与整包审查。四份交付文档独立核查已闭环；HOLDOUT-METRICS也已完成七门接线、双机合成验证及局部独立代码审查，当前按模型主线依赖准备真实环境前置。**

2026-09-13 当前维护（Codex）：本机及Linux隔离分支执行前均为干净`f76d0f4a`，正式项目与Codeup main仍为`f1b7d8a3`。第47节的Mac整仓2694 passed/11 skipped、实际exit0，Linux179项及顺序1项各exit0均为前轮运行；本轮独立reviewer逐件核验原日志、SHA、七保护文件及同步回执通过，没有重跑或将CPU结果当模型效果。四文档首轮发现两项P3：后续任务沿用已退役CLI、当前动作残留R6/R7旧失败；本轮修正文案后局部复核通过（含新增只读证据），最终结论见[验证第48节](results/version-control-migration/verification.md#delivery-preparation-20260913)。M8及真实环境缺口仍未关闭，未请求merge/push。

本轮推进HOLDOUT-BUILD来源/入口预检与MODEL-DIAG开发记录复算：新source尚未指定，新体系release集合仅见r1/r2；未创建或授权测试集。新增HOLDOUT-METRICS前置：基线配置不能表达已冻结七指标；用户已确认按原门槛补齐，Spec55b3f4d4/Plan061d2598单独提交，代码f1be1060已完成本轮双机验证和局部独立代码审查（第49节）。历史visual开发集1216条已在Linux按现行严格解析器重新评分、各折原摘要一致；concise原始记录仍缺，visual三折merged路径均断链。详见第48节及[轻量证据](results/model-diagnostics-preflight-20260913.json)。只复算历史开发输出，不是新推理或模型质量通过。

**最终独立验收依赖 HOLDOUT-BUILD；当前因使用资格证据不足而阻塞，优先继续不依赖它的 MODEL-DIAG 证据准备。** TEST-POLICY 已关闭（选定新建未使用 holdout、现有 sealed-test 不复测不调参）；历史问题 REL-VERIFY、CONTRACT-HASH 已关闭，不再重复安排首跑或契约找回。

1. HOLDOUT-BUILD先补齐使用资格证据，满足适用授权后才构建未使用的 test 数据分支：隔离独立于开发/调参的 source，按已冻结阈值发布 sealed-test release，走预注册 + 一次性授权 + claim 流程；不得读取或混用现有 sealed-test 的受限语义结果。本步单独执行，不隐含于“策略已确定”。
2. 持续整理 MODEL-DIAG 的开发集证据和训练机任务单：先核三折模型身份与原始预测，再做无需重训的推理对照，最后考虑单变量训练。任何新推理/训练开始前，明确机器、输入、输出、资源和既有授权范围。
3. 开发侧三折方案稳定、holdout 构建就绪并冻结后，才进入全量最终训练、独立验收和模型晋级。新体系release切换使用显式完整身份；RELEASE-POINTER的原旧指针维护目标待裁决，不构成新体系切换的自动前置。

| 顺序/定位 | 固定标识 | 任务 | 状态 | 依赖或触发条件 |
| --- | --- | --- | --- | --- |
| 独立验收前置 | HOLDOUT-BUILD | 构建并授权未使用的 test 数据分支 | 阻塞 | 代码接线及双机合成验收已完成；既定21个test source已定位，使用资格、人工审查及真实操作授权待落实 |
| 评分接线前置 | HOLDOUT-METRICS | 冻结七项holdout门槛接线 | 已解决（本轮代码/CPU范围） | f1be1060；真实holdout验收仍归HOLDOUT-BUILD/MODEL-QUALITY |
| 主要技术工作 | MODEL-DIAG | 诊断并改善三折类别坍缩与契约退化 | 进行中（Codex；只读准备） | 历史开发记录可复算；concise原件缺失及visual断链阻塞推理对照 |
| 清理前置 | MODEL-ARCHIVE | 中间模型证据归档与权重清理准备 | 进行中（主 Agent） | 条件删除已授权；仍须证明完整迁移、冗余性及MODEL-DIAG依赖已保留 |
| 发布前配套 | RELEASE-POINTER | 原旧指针维护目标适用性 | 待确认 | 新体系已显式选版本；待用户裁决原目标，不恢复旧写入 |
| 后续训练 | FINAL-TRAIN | 全量开发数据训练最终候选 | 阻塞 | 开发侧三折验收通过、holdout 测试集就绪及训练授权 |
| 总体验收 | MODEL-QUALITY | 最终模型质量验收与晋级 | 阻塞 | FINAL-TRAIN 候选、holdout 独立验收及其他适用质量门 |
| 文档收尾 | DOC-INDEX | 修正脚本索引的过期缺陷描述 | 已解决 | M7a 已对照 promote 实现修正脚本索引 |
| 低优先级 | CONTRACT-NAMING | 澄清候选规划与训练发布的契约边界 | 待处理 | 先解释真实用途，再决定是否兼容重命名 |
| 后续迁移 | VERSION-CONTROL-FORMAL-MIGRATION | 正式迁移可读版本控制体系 | 进行中（执行者 Codex；M3完成；M4/M5真实环境缺口保留；M6部分验收通过，R4 store级异根恢复已验收，真实硬盘/大型产物仍未验收；M7a完成，M7b本批完成，M7c本批完成，M7d本批完成，M7e本批完成，M8进行中（完整差异审查与交付，Codex）） | 按已确认Plan推进；真实重训/完整评测及merge/push仍需另行授权 |

MODEL-QUALITY 是总目标，不重复开实验，也不要求先通过最终独立验收才允许训练最终候选。新发现改变依赖时，同步本表和条目并说明原因。

## 待处理与阻塞事项

### MODEL-ARCHIVE — 中间模型证据归档与权重清理准备

- **状态/来源**：进行中（主 Agent）；用户要求验证能否保留历次训练参数和结果后清除训练机 run 下模型文件。用户已授权在完整迁移核验通过后清理旧数据与旧模型副本；未满足条件的文件继续保留。
- **已证实事实与差距**：2026-08-31 训练机 `workspace/runs` 约 90.253 GiB；原清单漏列两组 source-aware，concise-cv 约定路径不存在；r1 来源仍有 5 个 checkpoint，merged 为发布库软链接。5 组未发布模型 merged 权重合计约 80.988 GiB，各 root LoRA 约 439.1 MiB。原清单不足以放行删除；当前快照未哈希权重，未归档原始预测和完整训练日志。
- **依赖**：MODEL-DIAG 对历史/当前模型和阶段 checkpoint 的需求；当前发布模型及 `pipeline/checkpoint_policy.json` 保护边界。权重清理不隐含取消诊断任务。
- **下一动作**：按 MODEL_INVENTORY 第 8 节归档实际配置、模型/数据/Prompt/评测身份、完整日志和原始预测、文件哈希及备份校验；查 concise-cv 备份或迁移位置。逐 run 确定仅留研究记录还是保留 adapter 以便重新合并，形成显式候选清单后取得删除授权。保留 adapter 的方案先验证准确基座与合并链路，不以直挂 4-bit 代替 merged BF16。
- **验收标准**：每模型每 fold 有可核查的原始配置和结果链、缺失证据明确、归档已备份并校验；本轮新增visual三fold merged断链与concise缺失归入同一保护依赖（验证第48节）；清理路径不跟随链接误入发布库，不删除在用模型和未完成诊断所需文件；训练机按获准清单执行并记录删除前后体量、保留文件完整性及对应机器提交。完成可行性审查不等于归档或删除完成。
- **证据/版本/验证限制**：[模型清单](MODEL_INVENTORY.md#8-2026-08-31-清理可行性核查)、[训练机快照](results/model-inventory-audit-20260831/remote_snapshot.json)、[模型归档证据包索引](results/model_evidence/README.md)、[试点证据包`v4.1-prompt-minimal-v1-seed3411`](results/model_evidence/v4.1-prompt-minimal-v1-seed3411/README.md)。本地核查基线 `7b8192bd`，远端 `main@f1b7d8a3` 干净，本地独有 3 提交、远端独有 0；本轮 SSH 仅执行 Git 状态、文件 stat/目录/链接与轻量 JSON 读取，不启动 GPU 任务、训练、合并或评测，不读取受限测试语义结果。仅快照及文档落本机，未同步/删除远程文件。独立 reviewer 的原稿 findings 已核对：保护条件缺失 P1、模型清单过期/证据不足/效果结论过度 P2；修订后独立 reviewer 复审通过，无剩余可执行文档问题；10 个清单链接、指标/契约对照与 `git diff --check` 通过。修正归档要求仍不代表已满足删除条件。

### HOLDOUT-BUILD — 构建并授权未使用的 test 数据分支

- **状态/来源**：阻塞（Codex已完成test数据分支处理/全量人工审查/封存发布/最终测试接线，代码abafdbf2；解除条件为核清既定test source独立使用资格、取得适用真实构建授权、完成人工审查及真实媒体验证）；由TEST-POLICY拆出，数据冻结支撑FINAL-TRAIN，最终候选测试支撑MODEL-QUALITY。
- **事实与差距**：既定test分支21个视频及三折隔离已在训练机找到，不再以“source未指定”阻塞定位。旧release `v4.1-sealed-test-5546b8bf1ec3` 的一次性claim与completed/exposed凭据仍在；其摘要20source与332份媒体凭据的20source集合相关联，video_0005无该批候选凭据。原发布目录已缺失，不能把“缺文件”解释为“没用过”，也不能仅据无候选就认定video_0005可独立覆盖七门。当前缺口是使用资格及正式输入证据，不是初始划分不存在；未使用的新release尚未发现。
- **数据来源**：定义并人工审查一个独立于开发/调参的 source；沿用 `development_source_isolation_verified`、`test_split_binding_verified` 的隔离要求，纳入前核对 source 边界，避免与现有 sealed-test 或开发验证集混用。
- **人工审查**：对候选样本执行有效视图/剪裁人工审查（对应 `review_*` 流程），核对批次与 source 分层，形成冻结的 review batch 后再生成 release。
- **发布入口与差距**：test七阶段显式使用`--purpose holdout --test-config ...`，新模块`versioning/holdout_pipeline.py`在owner-only工作区复用媒体算法，所有候选必须人工审查。train默认路径不变。真实输入必须为独立test批次、具备冻结train版本的source清单及旧测试非语义来源清单；当前既定test source已定位；可用资格与完整非语义清单仍须核定。新入口及完整参数/产物来源见[入口说明](../versioning/SCRIPTS.md#test-数据分支处理全量人工审查与封存)。
- **已确认实施与限制**：用户已确认上一轮待决方案，Mac合成完整builder→claim→prepare→run→score通过。原审查发现真值摘要未校验P1和发布rename后封存尾步恢复P2均修复并专项复核；公开input仅固定整体receipt摘要，真值pin在授权score读取。当前test分支不自动向DVC remote发布受限数据；源码与Mac验证完成不表示真实数据已构建，Linux本批随后427/1skip通过，见第52节。
- **授权流程**：预注册一次性授权 + one-time claim，沿用现有 stage_d 流程；授权条件 `one_time`、`tuning_use: forbidden`、`pre_stage_g_outputs: aggregate_pass_fail_and_integrity_only`，首次模型调用前原子写入 claim，只允许同一 run identity 恢复。
- **阈值**：沿用 `stage-d-preparation-5cd1b3fa343c` 已冻结的 7 项阈值（`four_state_macro_recall 0.4006`、`fracture_three_state_macro_recall 0.3`、`joint_correct_rate 0.3921`、`runtime_failure_count 0`、`strict_valid_rate 1.0`、`已断裂_recall 0.15`、`未断裂_recall 0.7`）。
- **依赖/边界**：本任务只负责构建、审查、发布与授权一个未使用 holdout，不隐含“策略已确定即已构建”；完成本项不等同于最终模型已通过该 holdout 验收。不得读取现有 sealed-test 受限语义结果来构造 holdout。
- **验收标准**：新的未使用 holdout release 已构建并经人工审查，source 隔离与 test-split binding 校验通过，manifest/ground-truth/quality_report及预注册准备可追溯。数据冻结就绪先支撑FINAL-TRAIN；最终model/eval身份确定并获使用授权后，首次模型调用前建立绑定claim，再支撑MODEL-QUALITY。不能要求先有最终模型claim才能训练该模型。
- **证据/限制**：[验证第48节](results/version-control-migration/verification.md#delivery-preparation-20260913)及[轻量证据](results/model-diagnostics-preflight-20260913.json)。已核查新store集合与公开入口，未全盘扫描旧sealed-test集合，不推断历史对象已消失；未读取受限语义或创建真实holdout。最终候选model/eval身份形成前不提前创建绑定它们的一次性claim；保留预注册和首次模型调用前claim的要求。

### HOLDOUT-METRICS — 已冻结七项holdout门槛与正式评分入口衔接

- **状态/来源**：已解决（Codex，本轮代码/CPU范围，f1be1060）；HOLDOUT-BUILD本轮准备发现，用户已明确“确认，按原七项门槛补齐”，Spec55b3f4d4/Plan061d2598已单独提交。保持TEST-POLICY原定义和阈值，validation不变。
- **发现时基线事实（第48节，修复前）**：`finetune/eval_run.py::_formal_config`当时仅接受六项通用正确率，holdout共用此配置与最小值比较。七项既定门槛中仅`joint_correct_rate`可原名表达；宏召回、两类召回、runtime失败数及strict合法率均不能原样输入。纯配置反例拒绝七项、单joint控制通过，未访问数据/Registry。
- **下一动作/依赖**：已接入七门完整配置、私有数值指标及公开二值gate，Mac两进程614 passed/1 skipped、Linux首组加拆组167/240合计614 passed/1 skipped，实际各exit0，独立93项及篡改/Registry探针通过。Linux原合并组文件句柄耗尽exit1保留，不声称单进程通过。原f04ca7cb定义核对：runtime失败数等于0，其余为下限，缺四状态拒绝；原函数200组合成差分一致。不自动重命名或遗漏门槛，也不把全部指标当下限。
- **验收标准**：七项可冻结并与预注册精确一致，原输出重算可追溯；缺类、非法输出、runtime失败、边界值、恢复及下游准入均按原规则决定，不消费真实测试集来验代码。
- **证据/限制**：[第48节](results/version-control-migration/verification.md#delivery-preparation-20260913)、轻量JSON的`threshold_probe`；第48节保留缺口发现快照；本轮已按确认实施，最终验证与代码版本见第49节。既有整包代码审查保留原冻结范围，新增变更另行验收。

### MODEL-DIAG — 诊断并改善三折类别坍缩与契约退化

#### 新诊断方案草案（待确认，不是训练授权）

目标是建立当前新入口下可追溯、可重复的train分支基线，逐步诊断字段遗漏与类别偏置；不承诺恢复旧实验，也不将缺失权重视为继续搜寻的前置。

- 推荐从冻结train版本和明确基座修订重新建立一个单折基线，使用对应fold的完整validation及现有严格评分入口。先只读验证输入/配置/资源，明确完整data、prompt、train身份和媒体根；基座存在性与适用性另核，不预设当前已经可用。
- 数据、Prompt、采样、训练日程、生成参数先冻结；单折结果用于定位合法率和类别召回退化，每轮只调整一个因素。单折方案稳定后扩展三折，再按既定依赖进入full训练与最终test。
- 开发侧同时报告四字段合法率/正确率、各状态召回、macro recall、joint与失败样例。开发侧数值通过门槛须在实验前确认，不能借用test七项门槛或观察结果后回填；若正式validation配置不能表达诊断指标，先提出局部设计，不悄悄改接口。
- 不引入冻结分层canary或任意替换模型训练Prompt的交叉入口；这些能力尚未实现，增加它们会扩大范围。另一方向是先建立全部三折基线，比较更完整但成本更高；推荐单折起步会有fold偏差风险，必须由后续三折验收控制，不能据单折直接放行full训练。
- 待确认项：是否采用上述新基线方向；随后冻结基座/数据/Prompt/配置、开发侧门槛和资源预算。确认方案后仍须取得真实训练/推理授权。本轮只交付草案。


- **状态/来源**：进行中（Codex；只读证据准备）；原“三折实验出现类别坍缩与契约退化”。目标是在固定证据与评价口径下找到可跨 fold 复现的改进方案。
- **事实与差距**：已同步报告记录 `v4.1-prompt-concise-cv-v1-seed3411` 的 1581 条评测：contract 合法率 79.63%、joint correct 32.07%、`clip_state` 35.80%，322 条非法输出中 311 条缺 `special_case`，“临界未断裂”和“已断裂”召回为 0%。这支持退化症状，不证明 Prompt、采样或早停中的任何一个是单独根因。
- **下一动作**：每个步骤分别交接证据，新发现关联本任务，不悄悄加入当前实验。
  1. 在训练机核对既有 release、checkpoint step、adapter/merged 哈希、Prompt contract、生成参数、评分器代码和逐样本记录；只同步允许公开的开发集轻量摘要。缺产物则记录补同步/补评测任务，不用本机测试代替模型结果。
  2. 从已有开发验证集构建固定、按状态和 source 分层的 canary 清单，确认每个被测模型对应 fold 的训练排除关系；先重算既有记录，再做历史/当前模型与历史/当前 Prompt 的交叉推理对照。
  3. 对保留 checkpoint 做阶段性严格评测，定位字段遗漏和类别偏置开始的 step；保持样本、评分器和生成参数可比较，原始输出与评分结果分开保存。
  4. 根据诊断分别调整 Prompt、采样配额或训练日程，冻结其他因素；单折筛选后扩展到三折。组合修改另列候选，不作为单变量归因证据。
- **入口与产物**：2026-09-13训练机复核concise约定run/三fold原始记录缺失；历史visual的三折原始记录可读，但run_identity指向的merged均为断链，目标是`workspace/runs/v4.1-visual-cv-v1-seed3407/fold{0,1,2}/merged`。新正式评测由`python -m versioning eval prepare/validate/run/export`消费合法model完整身份、Registry数值版本和冻结data/Prompt；旧`finetune/eval_run.py`仅保留业务函数，CLI已停用，不能用裸路径绕过。正式入口目前使用全validation，尚不支持冻结分层canary或任意替换模型训练Prompt；这些对照能力须作为后续获确认的诊断方案，不写成现成命令。
- **准备与执行边界**：按[新入口说明](../versioning/SCRIPTS.md)准备完整data/prompt/train身份、显式媒体根、来源输入及三折配置；`versioning train prepare/validate`负责冻结与校验，`run/export`负责实际执行和产物证据。旧build/prepare/train CLI已停用；底层函数供新入口调用。历史模型只有报告/裸目录时不能强行登记为新正式completed；先找回原始配置、权重及逐样本身份链。
- **依赖/边界**：开发集只读整理不等待 HOLDOUT-BUILD；实验执行前明确测试隔离规则、冻结开发侧阈值并核对授权。现有交付配置记录 optimization paused / retraining unauthorized，本次文档维护不代表恢复训练授权。不使用 sealed-test 调参，不补字段伪造合法率，不删除诊断所需 checkpoint。
- **验收标准**：身份链一致、原始预测可追溯，根因分清事实与假设；报告四字段合法率/正确率、各状态召回、macro recall、joint correct、分布和失败样例；单变量结果可比较，三折达到预定开发侧标准后才放行 FINAL-TRAIN。仅完成诊断时记录阶段结果，不宣称效果改进已完成。
- **证据/限制**：[三折报告](results/v4_1_prompt_concise_cv_v1_seed3411/README.md)、[项目状态](CURRENT_PROJECT_STATUS.md)、[交付配置](../delivery/model_component.json)。报告第 10.2 节同时改 Prompt/采样/早停的建议不满足本任务的单变量标准；本轮已在Linux重算历史visual的1216条开发原记录，concise原始预测仍缺且未复算。新增[第48节证据](results/version-control-migration/verification.md#delivery-preparation-20260913)记录三fold模型断链和能力前置，不能据历史输出关闭改善任务。

### RELEASE-POINTER — 安全更新并激活数据 release 指针

- **状态/来源**：待确认（迁移后适用性）；原“release 指针文件更新自动化”。旧指针原目标保留追溯，未授权恢复其活动写入。
- **事实与差距**：当前指针手动维护；运行时校验契约内容哈希和 manifest 文件哈希，原方案仅更新两个字段不完整。
- **下一动作**：先裁决旧指针维护目标在迁移后的适用性；以下保留原目标而非当前执行指令：成功验证后整体原子更新 `release_id`、`release_dir`、`manifest`、`expected_contract_hash`、`expected_manifest_sha256`，记录选中该 release 的依据。构建自己的产物再自算哈希只证明一致性，不冒充独立信任校验。
- **入口与产物**：正式新数据发布走`python -m versioning data release/release_validate`和完整data身份，训练显式选择版本；旧`release_build_phase2.py`CLI已退役。原active_data_release.json作为历史保护证据保留，不能再将修改五字段旧指针写成新release切换前置。
- **依赖**：迁移后本条原“旧指针自动激活”目标适用性待用户裁决；当前不阻塞显式选择新data身份的诊断。若仍需legacy只读消费者维护，先明确精确范围，禁止恢复旧正式写入。
- **验收标准（原目标，待裁决）**：若保留legacy专用维护，五字段同源一致、预检失败不写、原子更新且可追溯；若取消此目标，依据用户决定关闭。新体系以显式完整data身份及冻结引用验证为准。
- **证据/限制**：[运行时](../finetune/v4_1_runtime.py) 的 `_load_active_release_pointer` / `load_release_expectations`；实现未开始，REL-VERIFY 通过不代表本项完成。

### FINAL-TRAIN — 全量开发数据训练最终候选

- **状态/来源**：阻塞；从原“独立测试 release 与 full-data final”拆出，是 MODEL-QUALITY 的前置。
- **事实与差距**：当前发布模型只用 Fold0，`full_data_final: false`；development release 有 1678 条发布候选。候选数不自动等于最终训练行数，训练资格与采样策略仍须冻结。
- **下一动作/解除条件**：MODEL-DIAG 达到开发侧三折标准、HOLDOUT-BUILD的数据构建/审查/冻结及预注册准备就绪（模型绑定claim在候选产生并获测试使用授权后建立）并取得适用训练授权后，冻结最终数据范围、Prompt、采样、训练日程与模型身份。
- **入口与产物**：独立full能力已由fed9bcfc实现且双机隔离CPU验收；正式入口为`versioning train prepare --scope full`，消费同一开发release全集、每候选一次及显式full配置，继而validate/run/export产生一个full/adapter，登记时`--source-scope full`。详见[新入口说明](../versioning/SCRIPTS.md#独立全量训练)。不再安排重做full代码；真实运行仍等待上列模型、holdout及训练授权前置。
- **验收标准**：全部合格开发数据按冻结方案纳入，未混入测试来源；真实训练/合并完成，模型与数据/配置/代码/哈希可追溯，保存最终候选及轻量 manifest。完成本项不自动获得 production approval。
- **证据/限制**：[开发 release 摘要](results/v4_1_phase2_development_release/release_summary.json)、[当前模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json)、[训练说明](../finetune/README.md)；本轮无全量最终模型证据。

### MODEL-QUALITY — 最终模型质量验收与晋级

- **状态/来源**：阻塞；原“当前发布模型质量门未通过”，作为总目标，依赖 MODEL-DIAG、FINAL-TRAIN、HOLDOUT-BUILD和HOLDOUT-METRICS；RELEASE-POINTER原目标适用性另待裁决。
- **事实与差距**：`v4.1-agent-pipeline-fold0-r1` 已用于工程链路验证，但 Stage B/D/G 标志均为 false，`production_approved: false`。标志为 false 不等于每一门都已执行失败，须查各门证据。
- **下一动作**：核对适用质量门、阈值和证据要求并落实到子任务；最终候选和测试前置齐备后，按授权协议完成独立验收及其他质量门，再决定晋级。
- **入口与产物**：参照 [发布证据](results/v4_1_agent_pipeline_fold0_r1/README.md) 和 [服务手册](INFERENCE_SERVICE_RUNBOOK.md) 核对执行入口；冻结报告和模型哈希，经注册表发布新身份并同步 delivery，核对服务加载对象。缺可执行入口则先补任务单/实现，不把历史归档命令写成现成流程。
- **验收标准**：预定质量门与身份校验均有证据，模型/报告/注册表/delivery/服务一致；新候选不覆盖旧模型历史结论，工程成功不能替代质量通过。
- **证据/限制**：[交付配置](../delivery/model_component.json)、[模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json) 及现有 sealed-test 公开结果；目前不满足最终交付标准。

### DOC-INDEX — 修正脚本索引的过期缺陷描述

- **状态/来源**：已解决；关联已解决的 PIPE-INDEX，本轮 M7a 文档同步完成。
- **结果**：脚本索引已删除“promote 未传播 source/split 索引”的过期描述，说明历史 promote 业务函数在快照移入正式 workspace 后更新集合索引，同时标明公开 rebuild_data CLI 已停用。
- **验收/证据**：对照 `pipeline/data_rebuild.py::_update_snapshot_collection_indexes` 及 promote 中的调用顺序核对；实现来源 `cdb8632c`，本轮仅修正文档。历史业务联合回归本机 57 passed；修改提交由 `git log -- pipeline/scripts/SCRIPTS.md docs/project-todo.md` 追溯。
- **限制**：不重新开放 legacy CLI，不代表索引库已退役；未执行真实数据 promote。

### CONTRACT-NAMING — 澄清候选规划与训练发布的契约边界

- **状态/来源**：待处理，低优先级；原“V3 命名遗留”。目标是降低理解成本，不改变冻结产物语义。
- **事实与差距**：候选计划 `_validate_contract` 要求 v3，重建入口实际加载 v3；后续 V4.1 审查/发布继续复用候选。因此不是纯历史路径，也不能直接换成 v4.1 契约。
- **下一动作/依赖**：先在模块说明中解释复用边界；仍有必要时再设计不带版本号的模块命名与兼容方案。主链路问题优先。
- **验收标准**：模块说明、imports、SCRIPTS.md 和流程文档一致；若重命名，验证既有调用与历史产物兼容性，不意外改变内容寻址身份。
- **证据/限制**：[候选计划](../pipeline/v3_candidate_plan.py)、[候选物化](../pipeline/v3_candidate_media.py)、[重建入口](../pipeline/scripts/rebuild_data.py)；尚未实施澄清或重命名。

### VERSION-CONTROL-FORMAL-MIGRATION — 正式迁移可读版本控制体系

- **状态/来源**：进行中（执行者 Codex；M2 已完成，2026-09-11 用户已确认 M3 显式输入契约与七阶段内部映射，2026-09-12 要求按交接继续本地实施）；由 VERSION-CONTROL-MIGRATION 核心基础设施完成后拆出。用户授权建立 Task Artifact，Intent 已确认提交 `3dae30a0`，Spec 已确认提交 `6996d35d`，Plan 已确认并提交 `11e54b31`；2026-09-11 用户进一步明确授权限定的 bundle/隔离 checkout、项目级环境和非 GPU smoke，该 M2 授权范围已执行完毕；2026-09-12 用户进一步确认 M3 精确执行单，已授权隔离同步、新 CPU 环境、小样本与两份数据复制。merge/push main、训练/GPU/完整评测仍不在授权内。
- **任务关联**：[Intent](tasks/2026-09-07-readable-version-control-migration/intent.md)、[Spec](tasks/2026-09-07-readable-version-control-migration/spec.md)、[Plan](tasks/2026-09-07-readable-version-control-migration/plan.md)（已确认提交 `11e54b31`）。任务分支为 `refactor/2026-09-07-readable-version-control-migration`，由用户确认重命名原分支并保留历史，承接基线 `1b0d5823`。原 B0–B12 台账中的旧分支名作为历史记录保留。
- **已确认范围**：迁移两个已发布数据版本和当前一版 Prompt `v4.1-concise-evidence-json-v2`；历史模型保留身份、核心训练参数及已有指标，不要求补齐全部历史信息。所有活动入口完成切换，保持单一正式写入者及不可抹去新事实的恢复规则。candidate/production 门禁不变；无合格模型时实际服务入口拒绝启动是允许状态，不要求历史开发模型继续服务。
- **规划发现与修复（历史）**：M3已替换最小数据链，M4已接入三折及独立full执行器；当前证据以第47–48节为准，不将早期“待M4”规划作为当前动作。
- **现场证据**：2026-09-07 网络恢复后只读调查成功；当时远端干净 `main@f1b7d8a3`，origin 为 Codeup。两个 release、三个 Prompt registry 目录、八个 run、五个历史归档目录和一个发布模型目录可见；六组 run 有 adapter，两个 concise run 仅见准备资料；concise-cv 预期路径不存在，`/data/mVllm_2` 尚未建立。完整观察及扫描边界见[调查记录](results/version-control-migration-20260907.md)，提交 `821e5953`。未验证权重哈希、加载、数据完整性或历史原始记录完整性，尚未分配新正式身份；无远端写入。
- **已证实事实与差距**：M0 证据已提交，训练机 payload 完整 hash 已验证，`/data/mVllm_2` 已只读验证可写。M1a 本地 Prompt/Data 迁移核心已完成并通过 review；M1b H1–H12 与统一 migration CLI 已完成。M2 以完整 bundle 建立隔离 checkout，再以 SHA-256 一致且 `git bundle verify` 通过的增量 bundle 更新到修复提交 `c4b53d08`；原有训练机 `main@f1b7d8a3` 始终干净。项目级 Python 3.11.16 环境锁定 DVC 3.67.1、MLflow 3.15.2、pandas 3.0.3 等关键版本。首轮 Linux 236 passed / 1 failed 暴露 inode 复用竞态；最小修复和独立 reviewer 三轮闭环 2 个 P2 与 1 个 P3 后，训练机 CLI+migration **241 passed**。跨进程锁、只读权限、DVC push-delete-pull、MLflow/SQLite artifact 联合恢复均通过；H9 四个真实 run 与 H11 的 1 model + 5 eval 只读成功路径通过。`/data/mVllm_2/dvc-remote`、`/data/mVllm_2/mlflow` 仍不存在且本轮未创建；截至M2完成时，真实移动硬盘恢复、正式store与真实迁移写入未执行；M3本轮已完成两份data复制，见下方最新证据。legacy `pipeline/`、`finetune/` 仍按旧规则运行。
- **下一动作/依赖**：M3真实数据链及M4–M7限定接线/退役、M8-R1至R7代码与CPU验收已完成，证据见第24–47节；四文档独立核查已完成；HOLDOUT-METRICS代码f1be1060及双机合成验收完成，按HOLDOUT-BUILD及MODEL-DIAG前置准备真实环境验收。M4/M5真实GPU成功路径、真实硬盘/大型产物及外部依赖整机恢复继续未验收。历史full/holdout第45节及整包第47节不重做；本次没有实际训练/受限测试使用或push/merge授权。
- **验收标准**：按已确认 Spec 核对两个数据版本及一版 Prompt 的内容保持、历史关联可查询、所有活动入口接管、单写与恢复不丢事实、训练机真实环境证据、文档及独立审查。Codeup 为发布依据，最终交付覆盖相对 Codeup main 的完整差异。
- **证据/限制**：[验证记录](results/version-control-migration/verification.md)第12–24节及[执行单](results/version-control-migration/handoff.md)。M3h本机完整1768 passed/exit0，各切片独立审查通过；真实媒体对照2份ROI、34份子视频、211张帧字节一致。正式r1/r2共20个声明payload与原源SHA一致、有效receipt、只读封存、r1拒绝/r2允许元数据新引用门，独立reviewer复验通过，训练机证据提交bf3d4ca。r1/r2共9421/11986个外部视频/帧引用在原workspace/data映射后全部可达，新store不自包含。Mac真实界面23完成/0待审，回收与训练机导入及257文件封存校验通过独立复核；新视觉审批0次，复用依据用户确认记录。M3已完成，完整回归与实机最终校验见第23–24节。未执行真实训练/GPU/完整评测、未改旧指针或正式main；M4–M7后续证据见第25–38节，M8进行中，M4/M5真实环境缺口保留。

### M8-R7 — 训练入口路径优先级测试依赖全局导入顺序：已解决（本轮范围）

- **状态/来源**：已解决（Codex；代码 `d9ec1227`）；父任务整仓测试在 `e1d70c58` 发现，原第46节为失败证据。
- **已证实事实与修复**：原测试受其他测试收集时的 `sys.path` 变动影响。路径优先级断言现由新 Python 进程验证，训练器对实际 LLaMA-Factory 模块来源的运行时拒绝门保留。
- **验收与证据**：[验证第47节](results/version-control-migration/verification.md#m8-r6-r7-20260913)：原失败顺序组合 Mac/Linux 各 1 passed/49 deselected、exit0；Mac 整仓 2694 passed/11 skipped、实际 exit0；独立复核另验证错误实际来源仍被拒绝。11项 skip 均因本机历史数据/fixture 缺失，不代表真实模型效果。

### M8-R6 — 外部训练初始化权重未纳入冻结输入：已解决（本轮范围）

- **状态/来源**：已解决（Codex；代码 `d9ec1227`）；父任务完整独立审查在 `e1d70c58` 发现 P2，原 adapter/checkpoint 漂移反例见第46节。
- **已证实事实与修复**：当前契约不支持外部 adapter 或 checkpoint 初始化/恢复；CV/full 的 prepare 在冻结前拒绝两类非null配置，旧冻结记录在 validate/run/export 与 Registry 训练证据门拒绝。旧完成/失败事实不改写，缺少来源证据的模型不能登记或进入后续准入。
- **验收与证据**：[验证第47节](results/version-control-migration/verification.md#m8-r6-r7-20260913)：Mac 相关179项、Linux同组179项各exit0；独立审查重用原两类漂移 fixture，旧记录各拒绝且Run/ModelVersion/状态/params不变；整包代码差异审查对140提交/152文件结论通过。上述为CPU合成验证，未声称外部权重路径已获支持或真实GPU训练通过。

### M8-R5 — 服务Prompt来源未与被评冻结输入绑定：已解决（本轮范围）

- **状态/来源**：已解决（本轮实现范围；Codex；用户2026-09-13确认兼容策略，Spec789fa4fc/Plan511cfc14）；父任务VERSION-CONTROL-FORMAL-MIGRATION的最终完整独立复审发现P2，代码ab5c71ae。
- **已证实事实与差距**：第43节发现时，prompt-v4.1-r1保持原concise-v2内容，与固定service analysis的system/user不同。独立CPU链路在真实证据门下构建合法candidate后，server_proxy.main仍在加载器前拒绝；不是缺alias的允许拒绝，不能宣称此Prompt对应模型端到端可服务。反例还证明同ID当前定义替换为固定契约后，resolver指纹不变且错误放行服务，未与训练/eval冻结内容绑定。
- **依赖/下一动作**：用户2026-09-13已确认采用模型冻结并验签的Prompt，保持输出/评分/alias/审批/备份门禁，并同步请求识别、重试和交付契约。Spec789fa4fc/Plan511cfc14记录，代码de1b51dd已实现。Mac广回归195 passed/1 skipped及新增5项通过，独立25+5项和操作说明通过；Linux最终200 passed/1 skipped、两组exit0，保护文件保持；本轮R5闭环。后续实际GPU加载/模型效果另验；父任务full/holdout接线及双机隔离CPU验证已完成（fed9bcfc，第45节），第46节原整包驳回已由第47节R6/R7修复及更新的独立代码审查闭环，真实holdout仍未验证。
- **验收标准**：当前迁移Prompt的合法模型可以通过实际服务CLI路由并使用其冻结输入；不兼容输出结构、模型版本/文件漂移、非法alias继续拒绝。训练/eval冻结Prompt及其摘要必须进入服务绑定，当前同ID内容漂移在加载前拒绝。CPU替身证据与GPU模型加载/效果证据分别标记，不将修复外推为模型质量通过。
- **证据/验证限制**：[第43节](results/version-control-migration/verification.md#m8-final-20260913)，pipeline/server_proxy.py:447–452；独立fixture`/private/tmp/mvllm2-final-concise-service-0bdr7oux`。修复证据见[第44节](results/version-control-migration/verification.md#m8-r5-prompt-20260913)，代码de1b51dd；旧行号/fixture仅追溯发现时事实。未运行GPU或读取受限测试结果，不以本轮局部通过代替整体验收。

## Skill 改进候选（待确认，不属于当前实现范围）

### SKILL-FEEDBACK — 用实际迭代案例评估 explain-project 的维护能力

- **状态/来源**：待确认；用户要求后续结合经验考虑针对性改进，当前未要求修改 skill。
- **现有规则**：本机 Pi skill 位于 `/Users/pcoffeep/.pi/agent/skills/explain-project/SKILL.md`，模板位于同目录 `references/todo-document.md`。本轮只读核对：它支持初次介绍及后续问答时维护 TODO，但不负责完整任务执行流程；模板“已解决”偏向代码修复，不充分表达误报澄清、远端验收和多 Agent 交接。后续修改前须核对当时版本，不假定其他机器同路径可用。
- **案例/候选调整**：REL-VERIFY 是环境验收，CONTRACT-HASH 是误报关闭，都无需业务代码修复；TEST-POLICY / FINAL-TRAIN 体现任务拆分与排序；DOC-INDEX 体现解决后发现文档残留。候选包括证据来源/机器标记、关闭原因、固定标识与拆分关联、新问题去重和交接。
- **下一动作/边界**：继续积累案例，区分项目流程约束与通用文档能力；用户决定修改时再加载适用的 skill 创建/修改规则，选取有证据的最小改动。不把 4090、封存测试或本项目排序推广为通用要求，不宣称 skill 已有当前执行循环。
- **验收标准（未来获准修改时）**：改进有案例和边界，保留项目介绍与任务执行职责分离，用初次创建、后续更新、误报关闭、执行中新发现等案例验证；当前只记录候选。

## 已解决与已关闭

以下区分前序 Agent 的记录与本轮核查；不统一声称所有事项都经过本轮全量测试或远端复验。前两项由用户确认完成，本轮保留关闭状态；TEST-POLICY 本轮由用户裁决后关闭。

### VERSION-CONTROL-MIGRATION — 可读版本控制核心基础设施：已解决

- **结果**：`refactor/readable-version-control` 已完成 B0–B12。新增独立 `python -m versioning` 六领域入口、五类完整可读身份、数据封存与 DVC 七阶段、Prompt 冻结、MLflow train/eval、不可覆盖 manifest、唯一 `mVllm2` Registry、严格 model layout 与 alias/current、分级离线备份及灾难恢复；legacy 入口保持不变。
- **最终证据**：核心修复提交 `9965dc1b`；`tests/versioning/` `1399 passed`，整仓 `2082 passed / 11 skipped`，均正常退出；9 个目标 Markdown 本地链接、2 个 YAML、172 个 tracked JSON、编译、CLI help、diff/未跟踪/大文件检查通过。独立 reviewer 对 R1–R11 执行相关套件、故障注入、备份恢复与跨进程锁攻击，结论为无剩余 P0–P3 actionable finding。完整提交与 finding 证据见[实施台账](plans/2026-09-01-readable-version-control-implementation.md)。
- **验证限制**：未连接训练机，未执行 GPU/真实模型/正式数据/真实移动硬盘操作；`fcntl.flock` 已在当前 macOS 双进程验证，Linux 训练机 smoke 尚未执行。未 merge、未 push、未正式迁移或删除 legacy。
- **后续拆分**：正式迁移另记 VERSION-CONTROL-FORMAL-MIGRATION，需用户单独确认范围与授权；其未开始不影响本核心基础设施任务关闭。

### AGENT-INSTRUCTIONS — Codex/Pi 共用指令契约修正：已解决

- **结果**：项目根 `AGENTS.md` 补建 Document Contract；新体系身份明确为 `<kind>-v<协议>-r<N>`，legacy ID/index 规则整体限定到 `pipeline/`、`finetune/` 旧入口；提交尾注按 Codex/Pi 真实执行平台区分；临时分支状态、SSH 明细、评测字段明细和 skill 起源历史从长期根指令移出或下沉，委派要求改为平台无关的结果约束。`ARCHITECTURE.md` 的三处身份简写同步修正。
- **Pi 配套**：Pi 用户级 `SYSTEM.md` 增加项目约束传递字段和 Gate；Pi 用户级 `AGENTS.md` 的平台名称修正。Pi 的具体角色集合继续由其用户级配置独立维护，不在项目根 Instruction 中复制。
- **证据/限制**：`versioning` 身份测试、Markdown 链接检查、Document Contract/Decision Log 唯一性、Pi JSON/frontmatter 静态校验及 `git diff --check` 作为本轮验收；未连接训练机，未启动真实 Pi 模型会话，也未执行图片生成任务。Pi 用户级文件位于仓库外，不随项目 Git 提交同步到其他机器。

### RUNBOOK-CONTRACT — 数据处理运行手册初始契约化与版本解耦：已解决

- **结果**：为 [数据处理运行手册](DATA_PROCESSING_RUNBOOK.md) 补建独立、精简的 Document Contract；标题和长期定位不再绑定特定链路版本，正文集中声明当前数据处理链路版本为 4.1，并保留候选计划使用 v3、审查与发布使用 v4.1 的真实契约边界。README 导航已同步。
- **文档决定**：文档级 Decision Log 的 D001 记录继续维护单一、不带版本号的主手册；版本升级时同步核对版本声明、版本特有路径、命令、默认值和验收条件，不只替换版本号，也不另建平行主手册。
- **证据/验证限制**：本地 `git diff --check`、两个治理块唯一性与本地 Markdown 链接检查通过；脚本默认值静态核对支持 v3/v4.1 边界。独立 reviewer 首轮发现 Contract 将统一 resolver 能力错误泛化到 `review_decisions` 的 P2，修正为保留各集合解析与路径边界后复审通过、无剩余可执行问题；reviewer 另执行 2 个相关测试，结果 `2 passed`。本轮未连接训练机，未运行 GPU、媒体物化或完整发布链路，不能据此宣称重新认证了手册中的全部既有命令。

### TEST-POLICY — 后续独立测试策略已确定：已关闭

- **关闭依据/用户裁决**：用户按建议执行① 新建未使用 holdout 测试集（是）；② 现有 sealed-test 不复测（否）；③ 新 holdout 阈值沿用已冻结值。策略据此确定，本任务关闭。
- **选定策略**：最终候选模型的独立验收采用新建的、未使用的 holdout 测试集；现有唯一 sealed-test `v4.1-sealed-test-5546b8bf1ec3` 仅作历史参考/回归监控，不复测、不调参。
- **决定依据**：唯一 sealed-test 已暴露且一次性（`passed: false`、`sealed_test_exposed: true`，预注册用途 `one_time_sealed_clip_evaluation`、约束 `tuning_use: forbidden`、`one_time: true`、`resume_policy: same_identity_only`）；本地 `finetune/results/v4_1_stage_d_claims/` 与训练机 `sealed_test_releases/` 均只有这一个 release，无未使用 holdout（两路独立证据印证）。
- **适用模型**：最终候选模型（FINAL-TRAIN 产出的候选）。
- **source 隔离要求**：沿用 `development_source_isolation_verified: true`、`test_split_binding_verified: true`，holdout 数据须独立于开发/调参的 source。
- **阈值冻结时点**：沿用 preparation `stage-d-preparation-5cd1b3fa343c` 已冻结的 7 项阈值（`four_state_macro_recall 0.4006`、`fracture_three_state_macro_recall 0.3`、`joint_correct_rate 0.3921`、`runtime_failure_count 0`、`strict_valid_rate 1.0`、`已断裂_recall 0.15`、`未断裂_recall 0.7`）。
- **授权条件**：`one_time`、`tuning_use: forbidden`、`pre_stage_g_outputs: aggregate_pass_fail_and_integrity_only`，沿用现有 stage_d 预注册一次性授权 + claim 流程。
- **证据/限制**：现有 sealed-test 证据位于 [公开结果](results/v4_1_stage_d_sealed_test_release/public_gate_summary.json)、[阶段记录](results/v4_1_stage_d_sealed_test_release/README.md) 及 `finetune/results/v4_1_stage_d_*`（授权/claim/run）；新 holdout 证据位置由 HOLDOUT-BUILD 任务执行时定义。本项只记录策略与依据，不执行推理或调参。

### REL-VERIFY — 训练机 release 指针实证：已解决

- **关闭依据**：前序 Agent 记录在训练机 `/home/liuyang/文档/mVllm_2` 执行 `python finetune/release_validate.py --verify-media`，退出码 0，`release_id: v4.1.0-ecb5aeb9657c`、`contract_version: tensile-vlm/v4.1`、`media_verified: true`。
- **核对值**：契约内容哈希 `47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937`；manifest 字节哈希 `ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`，对应指针的两个钉扎字段。三折 train/validation 计数为 1253/425、1014/664、1186/492。
- **证据/限制**：[指针](../finetune/active_data_release.json)、[验证入口](../finetune/release_validate.py)、前序写入本文件的训练机记录及用户确认。本轮未重跑；前序未附执行 HEAD 和独立日志路径，不补造这些信息。`0ffecb3a` 是校验代码历史版本，不是远端执行版本。

### CONTRACT-HASH — 历史 v3 契约哈希差异：已关闭（误报）

- **关闭依据**：前序 Agent 核对训练机历史 manifest，确认是哈希口径混淆，并非契约丢失；据其记录，本地/训练机契约文件与 Git `033d82b4` 版本逐字节一致。
- **核对值**：文件 SHA-256 为 `e963cddff086114d5501392355ee64347e616c9b383f837f7293030b664d64af`；规范化内容哈希为 `3f9f8217774cb4947fc4e19e41a5fe14b8a5ea30c8e84ed4f664abddd9de04f0`，与内嵌哈希及历史 `identity.inputs.tensile_vlm_v3_contract_sha256` 一致。
- **证据/限制**：[契约](../pipeline/contracts/tensile_vlm_v3.json)、[算法](../pipeline/v3_candidate_plan.py)；训练机历史路径 `workspace/data/derived/metadata/v3/candidate_plans/candidate-plan-ce36b9226be5/manifest.json`，前序记录 plan_id 为 `candidate-plan-ce36b9226be5`。关闭的是“契约丢失”误报，不把字段一致性扩大为本轮完整重建所有历史计划成功。原记录版本 `e027e82e` 只追溯问题来源。

### PIPE-INDEX — promote 不传播快照索引：已解决

- **结果**：`pipeline/data_rebuild.py` 在锁内、状态落盘前更新 source/split 集合的 index.json 与 LATEST，校验后写入，重入幂等且缺必要输入时 fail-closed。
- **证据**：修复提交 `cdb8632c`；`_update_snapshot_collection_indexes`、`tests/test_data_rebuild.py`。前序测试记录 `uv run pytest tests/ -q`：682 passed、12 skipped，并记录 reviewer 复验；本轮只核对提交和代码，未重跑。
- **残余**：脚本索引过期描述已在 DOC-INDEX 修正，不影响原代码缺陷关闭。

### PIPE-STATE — rebuild 首跑状态跳转缺失：已解决

- **结果**：允许 `source_snapshotted` 转入 `waiting_for_roi_review`，无预置 ROI 决策的 review 模式首跑可等待人工标注，复跑幂等。
- **证据**：修复提交 `cdb8632c`；`pipeline/data_rebuild.py`、`tests/test_rebuild_source_only.py`。前序全量测试和 reviewer 记录同 PIPE-INDEX，本轮未复跑。

### ROI-DEFAULT — ROI 标注默认 metadata 路径失效：已解决

- **结果**：`pipeline/scripts/roi_annotation_app.py` 从 source_snapshots 的 LATEST 解析 video_meta.json，支持显式路径/ID/前缀；缺 LATEST 或前缀歧义时 fail-closed。
- **证据**：修复提交 `cdb8632c`、`tests/test_roi_annotation_app.py`；前序全量测试和 reviewer 记录同 PIPE-INDEX。`f6881883` 为历史文档版本，不再标为未提交修复。
- **残余**：Streamlit 显示原始 ValueError traceback 是此前接受的呈现层风险；本轮未重新验收 UI。

## 最近维护记录

- 2026-09-12 M3b：source 逐项读取真实 CSV 与显式视频，复用标签治理、保留给定 split；全部输入与阶段文件验签、临时完整构建后发布。reviewer 的锁等待漂移 P2 经有效 RED/修复/独立复验闭环；专项17 passed，本机完整1707 passed、exit0。代码按同次提交追溯；后续 ROI/子视频未提交增量不属于此证据。M3继续进行中，未连接训练机或迁移正式对象。

- 2026-09-12：按用户交接继续 M3 本地实施，已完成 M3a 只读输入 envelope 加载门（同次提交可经 `git log -- versioning/data_pipeline.py` 追溯）。有效 RED 8 个缺字段断言失败；定向 61 passed；本机完整新体系 1690 passed、exit 0；独立 reviewer 无可执行 finding。Codeup 任务分支只读核对仍为 `2027c4dc`，main 仍为 `f1b7d8a3`；未连接训练机、未 push/merge 或正式迁移。下一切片为真实 source snapshot+split 及 `--inputs` CLI，整体 M3 保持进行中。

- 2026-09-11：按用户要求暂停 M3，先同步本机、Codeup 与训练机隔离任务分支。同步前本机 `93847d9f`、训练机隔离 `c4b53d08` 为严格祖先关系且双方独有提交 `0/2`，Codeup 尚无同名分支；本机用显式 Codeup refspec 首次推送，训练机保留 bundle `origin`、新增 `codeup` remote，经 fetch 核对后以 `--ff-only` 快进并改设 Codeup upstream。本同步记录提交后将再次显式 push/fetch/fast-forward，最终三端 SHA 以只读核对为准；Codeup 与训练机正式 `main@f1b7d8a3` 未修改，M3 未实施。

- 2026-09-11：完成 M2 训练机隔离环境与存储预检。完整及增量 bundle 均经本机/训练机 SHA-256 与 `git bundle verify` 核对，隔离 checkout 更新到 `c4b53d08`，原有 `main@f1b7d8a3` 保持干净。Linux CLI+migration 241 passed；跨进程锁、只读权限、DVC 小对象恢复、MLflow/SQLite artifact 联合恢复、H9 四个真实 run 和 H11 的 1 model + 5 eval 只读成功路径均通过。正式 store、真实移动硬盘恢复、迁移对象写入、训练/GPU/完整评测、merge/push 均未执行；下一阶段为 M3 数据七阶段真实接入。

- 本轮：完成 M1 最后的 migration CLI 切片，统一入口增加 Prompt/Data 预检与迁移、history-summary 构建与固定路径发布六个显式动作。TDD 有效 RED 后实现显式 root/输入文件门、blocked 非零退出与 JSON 拒因、全层级重复 YAML 键拒绝；独立 reviewer 三轮闭环 4 个 P2 后无剩余 P0–P3。CLI 50 passed、migration 187 passed、reviewer 联合 237 passed，最新工作树完整 `tests/versioning` 1625 passed，均正常退出。前一轮完整套件打印汇总后的额外耗时已经进程采样定位到 Python 终止 GC，不冒充 CLI 失败。本轮未连接训练机、未执行真实迁移、训练、推理、merge 或 push；下一步为 M2 隔离环境与存储预检。

- 本轮：M1b history-summary 已推进至 H12。H11 已提交 `10ba00c2`。H12 新增固定路径 history-summary 文件发布：先完成纯构建，再通过稳定 no-follow 目录 FD、排他临时文件、hard-link 无覆盖提交、写入/可见 inode 双重复核和目录 fsync 原子发布；既有目标、链接路径、并发替换与清理异常均 fail-closed 或返回明确已提交结果，不覆盖或误删竞争对象。两位独立 reviewer 多轮对抗复核后终审通过、无 P0–P3；当前 migration 187 passed，H11 时点 `tests/versioning` 1573 passed，H12 后全套尚未重跑。下一切片为 migration CLI；本轮未连接训练机、未执行真实迁移、训练、推理、merge 或 push。

- 2026-09-04 可读版本控制核心基础设施收尾：关闭 VERSION-CONTROL-MIGRATION，记录 `9965dc1b`、本机 `1399` 项新体系测试与整仓 `2082 passed / 11 skipped`、最终 reviewer R1–R11 闭环和实机验证限制；拆出待确认的 VERSION-CONTROL-FORMAL-MIGRATION。本轮未连接训练机，未 merge、push、迁移或删除 legacy。

- 2026-09-03 Agent 指令双平台修正：依据独立审查修正项目根 AGENTS 的版本身份、legacy 分域、提交归因、作用域和委派表述，并同步 ARCHITECTURE 与 project-guide；Pi 用户级编排增加项目约束传递 Gate。仅做本机文档/配置与静态验证，不连接训练机、不运行真实 Pi 子任务。

- 2026-09-01 数据处理运行手册初始契约化：新增 Document Contract 和文档级 D001，将手册定位与 4.1 版本号解耦，在正文声明 4.1 为当前执行基线并同步 README 导航；接受 reviewer 关于 `review_decisions` resolver 例外的 P2，修正 Contract 后复审通过。仅修改文档，不连接训练机或执行数据处理。

- 2026-08-31 模型清理可行性核查：新增 MODEL-ARCHIVE，修正 MODEL-DIAG 的远端权重路径现状；保留既有 holdout 决策及其他未提交修改。仅只读检查远端，补充清单和本地证据；本轮没有归档全部原始产物或删除权重。下一步在任何清理前先完成证据备份与诊断依赖裁决，原独立测试准备与 MODEL-DIAG 主线不因此取消。

- 本轮：承接 TEST-POLICY 裁决并关闭该任务，记录选定策略与决定依据（新建未使用 holdout、现有 sealed-test 不复测不调参）；新增前置任务 HOLDOUT-BUILD 入“待处理与阻塞事项”并列入执行顺序表；同步更新下一步、FINAL-TRAIN / MODEL-QUALITY / MODEL-DIAG 的依赖表述。本轮仅维护本文件，未连接训练机或重跑实验，不新增日期/时间。
- 2026-08-31：承接前序 Agent 关闭的指针验收和 v3 误报；余下五个原事项按依赖重排，其中独立测试/full-data 拆成两个任务，质量门保留为总目标；新发现 DOC-INDEX，另记 SKILL-FEEDBACK；修正命名、哈希、提交和证据边界。此次仅维护 AGENTS.md 与本文件，提交可用 `git log -- AGENTS.md docs/project-todo.md` 追溯。
- 本轮文档验证：独立 reviewer 结论通过、无可执行问题；31 个本地 Markdown 链接路径有效，13 个任务标识唯一，`git diff --check` 通过。核查仅覆盖文档及引用的本地代码/公开产物，不代表重新验收远端任务或模型质量。

- 2026-09-12 M3c：冻结 ROI/source 身份、真实几何与裁剪适配完成；独立 reviewer 的非有限时长 P2 经 RED/修复闭环。ROI18项、source+ROI35项通过；独立 ROI-only 快照完整1725 passed、exit0（484.94秒），暂存代码与快照一致。真实媒体仍待训练机验收，继续子视频及后续阶段。

- 2026-09-12 M3d：两scope候选规划/真实裁剪/实际采样适配和预处理器逐文件钉扎完成；3个reviewer P2均经RED/修复/复验闭环，定向12项通过、独立快照完整1737 passed/exit0。没有真实AutoProcessor或训练机媒体证据。继续审查、发布、UI与CLI/DVC。

- 2026-09-12 M3e：真实开发候选审查包与完整绑定回收完成，定向12项、独立完整1749 passed/exit0，独立reviewer无finding。非空历史参考与冲突保护已独立复验；真实人工及跨机回传仍待验证，继续发布/UI/CLI/DVC。

- 2026-09-12 M3f：真实六份开发集数据、媒体/标签/split保持、封存及只读validate完成。reviewer发现的3处校验遗漏和锁等待目录变化均经RED/修复/独立复验关闭；专项8项，独立完整1757 passed/exit0。真实对象写入未执行，后续UI和入口集成尚待提交。

- 2026-09-12 M3g：显式审查包接入现有界面，草稿/冻结角色和路径保护完成；reviewer两个P2均闭环。5项边界、1项AppTest完整交互、独立完整1763 passed/exit0；测试图像/视频/决定均为fixture，不冒充真人审查。继续最终CLI/DVC完整验收与待授权训练机步骤。

- 2026-09-12 M3h：七阶段公共 CLI/真实 DVC 输入与上游依赖全部接通；针对性245 passed、完整1768 passed/exit0，独立reviewer25项及操作文档核查通过。训练机执行单测试参考范围P2已修复并复审通过。只读核对训练机分支、依赖、原视频与源manifest；真实媒体、双机人工回传及两份release复制待明确授权，M3未完成。代码版本以同次提交追溯。

- 2026-09-12 M3真实验收：用户明确确认执行单后同步隔离代码并建立独立CPU环境；真实七阶段前四步、34候选旧算法对照及两份release正式复制通过独立核查。Mac已收包验签并只读检查界面。用户提示核对普通未断裂自动规则：11条确为自动，剩余23条是历史人工批准而作者空缺，不能自动豁免或伪造身份。人工回传待补，M3保持进行中；详见训练机原子证据提交bf3d4ca。

- 2026-09-12 M3 Linux回归：244pass/1fail定位为DVC临时remote绝对中文路径编码限制，测试改同目标相对地址后22项通过，独立审查通过；本机完整1768pass/exit0。未修改生产代码，人工回传缺口不变。

- 2026-09-12 人工审查追踪修复：用户回忆旧批准应为本人，并要求修复未来字段完整性。确认legacy入口审查者可选、保存与迁移保留None，手册必填未落实；新增两模式非空标识、界面显示、完整冻结逐条作者校验，并补继续审查命令。13项专项/47项legacy回归、完整1780项通过且正常退出，独立review22项及真实临时保存链通过；不批量归因旧匿名决定，M3真实回传缺口仍保留。

- 2026-09-12 M3完成：用户明确确认唯一维护者历史审批归属；新UI默认项目维护者，23条对象匹配的旧审批保留原时间/标签复用，11条普通未断裂自动。Mac回传、训练机review_import→隔离开发release/validate通过（34样本257文件）；独立复核确认源记录/旧指针/main不变。Mac完整1772项、legacy47项、独立28项、Linux专项5项均正常退出。两份正式release复制及真实媒体对照证据已齐；M4–M8待推进，整体迁移继续进行中。代码7a122323，训练机闭环证据按本次提交追溯。

- 2026-09-12 M4a：真实训练适配器接受已加载配置的深拷贝，保留处理器契约/源码来源门并传播执行失败；CLI拒绝重复YAML键。Mac RED为6 failed/1 passed；GREEN及独立reviewer均7 passed/exit0，无finding。证据见验证记录第25节，提交按本条同次提交追溯。M4继续进行，未执行GPU/训练机操作。

- 2026-09-12 M4b：实际fold执行事件接通临时MLflow验证，处理参数截断和参数写入失败两个独立reviewer P2；完整148项通过，复审11项及边界验证通过。证据见验证记录第26节；M4仍进行中。

- 2026-09-12 Prompt实际迁移：按已确认唯一映射生成Git正式prompt-v4.1-r1；两端源SHA相同，独立reviewer逐字段/内容hash/标准加载验证通过，旧源与指针未改。证据见验证记录第27节；训练机目标同步另行记录。

- 2026-09-12 M4c/d：新身份三折输入冻结、显式原媒体根与实际训练调用接通；独立审查2个P1和1个P2已闭环，广回归233项、七阶段接线1项及独立核查通过。正式Prompt已Git登记。训练机真实输入准备尚待执行，正式eval仍未接线，M4整体未完成；证据见第28–29节。

- 2026-09-12 M4训练侧实机验收：训练机隔离分支6c43479e上公共prepare/validate均exit0，1678视频/165,485,727字节及六份5034行引用全部通过独立验签；三折数量1253/425、1014/664、1186/492与原r2一致。Linux专项11 passed/exit0，无MLflow/模型加载/训练。CPU环境缺peft/accelerate，不能声称训练就绪；正式eval仍待接线，M4整体进行中。实机证据在实际训练机同次提交，见验证记录第29.1节。

- 2026-09-13 M8整体审查：冻结f1b7d8a3至0963642b完整117提交/148文件，reviewer独立复现M8-R1–R4并驳回整体候选。R2/R3本机/Linux各466项及独立251项通过，已解决本轮范围，该次审查时R1实际证据门及R4异根恢复未解决；R1后续修复见第40节，R4与历史汇总实物仍待补。已同步handoff当前Spec矩阵与verification第39节，原M3执行单保留为历史。未merge/push或运行GPU。

2026-09-13 M8-R1已解决本轮范围（代码3b63aa52）：Mac整仓2623 passed/11 skipped，Linux分三进程956 passed/1 skipped、各exit0，独立代码/操作文档局部审查通过。首次Linux单进程回归触及1024文件句柄上限而exit1，已保留日志；相同代码及原限额分组复验通过，不能外推长期服务资源验收。完整证据见verification第40节。下一步M8-R4异根恢复、history-summary实物与最终整包复审；真实GPU/full/holdout及物理存储缺口保持，M8整体不关闭。


2026-09-13 M8-R4进行中（Codex）：从7bea4533继续已授权实施。修复恢复副本SQLite内的MLflow存储地址，保留不可变训练/评测内容及状态；验收要求新根读取、原模拟store不可达、备份不变、非法映射和冲突拒绝。代码限既有backup.py及已批准测试/文档，基础模型与外部媒体不因重定位扩大备份范围。

2026-09-13 M8-R4已解决本轮store级异根恢复范围（代码2fce3ab1）：Mac受影响回归175 passed/1 skipped，最后URI严格化另6 passed；Linux最终同一提交181 passed/1 skipped、exit0；独立代码/操作文档局部审查通过。原模拟store不可访问时，新根artifact读取、显式current/服务准入、后续写入与再次备份均通过；冻结事实和原备份保持。验证见第41节；真实硬盘/大型产物、外部依赖整机恢复与GPU不在通过范围。下一步补实际history-summary并做M8最终整包复审，整体迁移不关闭。

2026-09-13 M8历史汇总进行中（Codex）：承接a14b3d0a，读取训练机原工作区的限定run结构及隔离分支的五份轻量归档，生成已批准history-summary.yaml。分别保留来源根、归档声明与本轮观察；不写原工作区、不复制大型权重、不读取受限测试结果、不新增正式身份。验收覆盖声明对象全集、Spec核心字段的已知值/未知原因、指标口径与审批事实，并独立核查。

2026-09-13 同轮发现并修复M8历史生成器batch口径（Codex）：已证实原H9缺world_size却输出effective_batch_size；本轮改保留per_process_accumulated_batch及推导来源，全局值未知。变更仅既有migration.py与test_migration.py，RED有效，Mac migration+CLI247项通过；代码/产物/Linux与独立结论见verification第42节，不新增训练或正式身份。

2026-09-13 M8历史汇总本轮交付完成：history-summary.yaml含21条、234已知/152未知、47份轻量来源及实际权重stat，已独立验收；同轮公共生成器batch误记由d2ae4cee修复，Mac/Linux migration+CLI各247项通过，独立15项通过。证据见第42节。下一步核对物理/data下Prompt落位并做M8最终完整Spec矩阵与差异复审；真实GPU/full/holdout及硬盘/大型产物限制保留，整体迁移未完成。

- 2026-09-13 M8最终复审与物理Prompt：ab5c71ae在/data登记相同1200字节Prompt，独立验签/标准show/重复拒绝通过；Mac整仓2647 passed/11 skipped、exit0，11项skip均本机历史数据缺失。完整125提交/149文件独立复审已完成并驳回整包，新增M8-R5冻结Prompt绑定P2，R1–R4/历史局部证据有效。下一步先补同ID漂移拒绝，兼容策略待用户确认，full/holdout实际输入接线独立推进；整体迁移未完成。见verification第43节。

- 2026-09-13 M8-R5已解决本轮范围：用户确认冻结Prompt策略，Spec789fa4fc/Plan511cfc14、代码de1b51dd；Mac195 passed/1 skipped及新增5项通过，Linux200 passed/1 skipped、双组exit0，独立25+5项和操作说明通过。训练/eval/当前定义绑定、动态契约摘要、实际FastAPI请求/重试/smoke均有CPU证据；没有GPU或真实HTTP监听。台账与矩阵同步，下一步full/holdout实际输入接线及最终完整验收，M8整体不关闭。


2026-09-13 M4 full/holdout接线完成（Codex，代码fed9bcfc）：用户确认独立full训练范围，保持三折原划分和旧导出格式，全量开发候选只训练一次并记录full产物来源；holdout新增媒体run/显式授权score，评分承诺建立前必须核验原truth来源和实际明细，已承诺恢复与公开导出不重读原truth。独立审查的2项训练P2、holdout链接P2和评分恢复P1（含强化伪造反例）已闭环，代码/操作说明/设计局部通过。Mac广回归679 passed/1 skipped与最终holdout16项、Linux最终819 passed/1 skipped均正常exit0，七份保护文件及原项目保持，完整证据见verification第45节。M4仍进行中：缺真实模型训练/GPU评分证据；HOLDOUT-BUILD未执行，不将CPU替身写成模型质量通过。下一动作是最终整包差异审查及交付矩阵收口，整体迁移、真实硬盘与真实模型效果不据此关闭。


2026-09-13 test使用资格只读续查：用户已授权限定范围身份调查。当前数据目录和已发现的pre-semantic-portal-20260723备份中共6个媒体receipt集合，均无video_0005；18份manifest/identity已按非语义字段核对。迁移清单只列source、derived、training_releases→releases，不覆盖sealed_test_releases；这说明verified不证明旧test发布已迁移，不能据此认定删除原因。未找回299样本的完整发布身份清单，现阶段21个source的独立使用资格均为“证据不足”，并非“全部未用”；其中20个已有与暴露release相关联的物化证据。run_identity的初始化状态不能覆盖后续gate的completed/exposed事实。下一步最小缺失材料是旧发布的无标签candidate/source清单或对应备份；不扩大读取受限语义、不重划分或放行复用。详见verification第53节。


2026-09-13 MODEL-DIAG限定目录续查：Linux只读目录与路径stat实际exit0。evidence_archive顶层5组名称不含目标concise/visual三折；现存concise-v1仅input/reference、concise-v2仅input，不能替代concise-cv；/data/mVllm_2/workspace仅data、finetune仅active_data_release.json。六个约定三折merged目标仍不存在。未检查其他发布库内容或全盘备份，不能断言模型全部丢失；没有读取权重/预测/test内容或重跑既有评分。下一步需目标身份绑定的模型/原始预测备份，或另行确认诊断方案；test资格阻塞不取消MODEL-DIAG，也不授权重训。证据见verification第54节及docs/results/model-location-followup-20260913.json。


2026-09-13 MODEL-DIAG发布库身份及恢复目标：Linux只读release-manifest核查exit0，已知legacy发布库只有v4.1-agent-pipeline-fold0-r1，origin为coverage-first单折实验，不能替代concise/visual三折。已从历史concise报告提取三折summary/records共6个SHA256恢复比对目标；尚未找回文件，报告摘要不是原件或模型权重的独立证明。已知位置线索核查到此收束，等待准确备份路径/迁移记录；不重复扫描、重训或擅自改用其他模型。详见verification第55节。


2026-09-13 条件清理授权（Codex）：用户明确旧数据和旧训练run/模型两类均包括，只删除已验证完整迁移且不再需要的旧副本。本轮Linux预检exit0：历史迁移source_root已不存在；pre-semantic备份不在该迁移清单映射内；旧LlamaFactory顶层16个模型软链接，10个目标存在、6个断链，不能当作重复权重。workspace/runs包含迁移后的实际目标，当前发布库保持保护。删除白名单为空，实际删除0、释放0字节；不是授权缺失，而是完整迁移/冗余性证据未满足。后续先建立旧备份到保留位置的逐文件映射、内容一致性和引用退出证明，再在本次条件授权内清理；不继续索取缺失三折模型备份，不把此次决定解释为取消MODEL-DIAG或TEST-POLICY。


2026-09-13 train原视频清理候选：按用户条件授权在Linux核对旧备份01_videos到workspace/data/source/videos，89个train视频逐文件大小/SHA256一致，共5852142357字节（约5.45GiB），21个test视频未读内容。两工作区tracked运行代码/配置未见该备份路径引用。删除程序的占用预检遇到不可读/proc文件句柄，实际exit1且发生于首次unlink和证据目录创建之前；sudo -n只读能力探针要求密码，未提权。删除0、释放0，旧副本保留。候选清单与完整程序已保存；后续完成有权限的占用检查后再沿用授权执行，不能把候选已验签写成已删除。


2026-09-13 train真实输入预检：Linux隔离bb73e4dd执行正式build_versioned_datasets(scope=full)，实际exit0；data-v4.1-r2 + prompt-v4.1-r1 + 原workspace/data媒体根成功生成内存输入。三折train/validation为1253/425、1014/664、1186/492，full为1678，唯一媒体1678个共165485727字节逐一哈希；媒体名提取source与既定21个test ID无交集，此项不代替内容隔离或test资格。没有Run写入、训练或GPU执行。完整结果摘要见docs/results/train-input-preflight-20260913.json及verification第59节。


### 工程实机缺口执行单（承接M4/M5/M6，未自动豁免）

| 范围 | 本轮已消除的不确定性 | 下一项具体动作 | 输入/产物与验收 | 边界 |
| --- | --- | --- | --- | --- |
| M4真实训练执行 | 当前train版本、Prompt、三折/full数据和媒体可构建 | 先冻结单折工程验证配置、基座修订和资源预算；确认后在训练机运行 | 明确完整train身份；产生实际trainer日志、adapter、终止状态、MLflow与导出一致性证明 | 真实训练未授权；不能把本轮预检作成功运行 |
| M5模型/服务成功路径 | 现有中间模型不可冒充合格最终模型 | 合法候选及精确passed eval就绪后，实际启动服务并调用固定请求 | model数值版本、冻结Prompt、实际权重摘要、HTTP结果和退出证据一致 | 不伪造passed/alias；候选尚未就绪。建议随模型任务补成功路径，合并前须用户明确接受这项转交 |
| M6大型产物/外部依赖恢复 | 新store非自包含，依赖原workspace/data；不能删掉媒体根 | 明确目标备份设备/目录、容量和外部依赖清单，安排隔离恢复与重验 | 数据、adapter/merged、SQLite及外部依赖在恢复根可用；正式对象不覆盖 | 移动硬盘可独立未完成已有确认；其余大型/外部依赖范围尚不自动豁免 |

M4配置/资源初检已完成（第60节）；下一步核对同进程训练环境并选择有限三折工程验证方案。现有入口不支持独立单折，不能直接执行前述单折建议。不启动训练。M5成功路径转交及M6剩余验收接受范围作为明确合并前裁决；最终模型质量继续后续主线，尚未满足的工程证据不标记完成。


2026-09-13 M4配置/资源预检：基座路径models/minicpm_v_4_5存在并解析到models/minicpmv4_5，config声明openbmb/MiniCPM-V-4_5；仅stat/配置，未验完整权重或冻结修订。4090查询时24564MiB总显存、约1081MiB使用、利用率0%；/data约3.4TiB可用。cpm45有torch/transformers/peft等训练包，但importlib.metadata未发现mlflow分发包；正式适配器在同进程调用run_training，不能假设CPU隔离环境与GPU环境已贯通。公共入口仅cross_validation三折整组或full，没有单折选项；前文“现成单折工程验证”建议收窄为待设计方案。下一步先核对完整执行环境与有限三折工程验证方案，不创建训练版本、不启动训练。
