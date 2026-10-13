# Project TODO

本文件是唯一项目任务台账，记录当前目标、差距、依赖和验收证据。维护规则见 [AGENTS.md](../AGENTS.md#todo-执行与维护)。固定标识不随排序或关闭改变。

## 当前状态与下一步

**数据处理及活动入口的工程迁移已解决。** 2026-09-14，迁移分支先推送，再快进 Codeup main 至 `5acebc27` 并同步训练机正式代码；集成与双机 CLI 记录见[验证第67节](results/version-control-migration/verification.md)。这不表示真实 GPU 训练、最终模型质量、独立 test、真实服务成功路径或整机恢复通过。

**当前状态（2026-10-13）**：DOC-INTEGRATION 和 REMOTE-STATE-REFRESH 已完成。用户随后授权新建正式Conda环境；ENV-ACTIVATION 已在训练机建立 `mvllm2`（Python3.11.17），按GPU锁安装并绑定正式checkout，通过环境验收，见[部署记录](results/conda-environment-setup-20261013.md)。保留agent/cpm45，不同步代码，不启动数据处理、训练、推理或评测。下一步核定候选模型来源并确认MODEL-DIAG方案；新体系正式训练/评测/模型记录尚未产生符合当前阶段，不作为迁移失败，也不创建空记录补目录。环境可用不等于模型质量或恢复通过。

新体系正式入口为 `python -m versioning`，显式使用五类完整可读身份。train 数据分支用于三折开发验证和 full 训练，test 分支只用于最终独立测试；代码中的 `development` / `holdout` / `test_audit` 保留原值。旧媒体仍被新 store 引用，不得按“迁移完成”删除旧目录。

| 顺序/定位 | 固定标识 | 当前任务与状态 | 依赖、下一动作 |
| --- | --- | --- | --- |
| 已完成前序 | DOC-INTEGRATION | 已解决：正式整合文档目录 | 根README及三份正文正式启用，覆盖旧说明清理；独立核查通过，台账/设计/证据保留 |
| 已完成前序 | README-PUBLIC-INTRO | 已解决：项目介绍与新人快速开始 | 独立核查通过；验证第69节，无动态执行 |
| 已完成前序 | DOC-CONSOLIDATION | 已解决：文档及台账收敛 | 独立核查通过；验证第68节；候选手册及运行约定见文档整理记录 |
| 本轮已完成 | REMOTE-STATE-REFRESH | 已解决：限定范围训练机只读刷新 | 实时事实及缺口已记录；未执行同步、环境切换或模型运行 |
| 模型准备 | MODEL-DIAG | 待确认：诊断方向与开发侧门槛 | 可继续公开开发证据准备；新基线方案和真实运行授权分别确认 |
| 独立验收前置 | HOLDOUT-BUILD | 阻塞：未使用 test 数据资格及构建 | 既定 21 source 已定位；缺使用资格、非语义来源清单及真实审查/构建条件 |
| 本轮已完成 | ENV-ACTIVATION | 已解决：正式Conda环境与checkout绑定 | mvllm2 Python3.11.17、241锁项一致、doctor/pip check通过；真实业务未运行 |
| 备份验收 | RECOVERY-VALIDATION | 待处理：真实大型产物组合恢复 | store 级恢复已验；真实硬盘、权重、SQLite 与外部依赖缺完整证据 |
| 后续训练 | FINAL-TRAIN | 阻塞：full 最终候选 | 开发侧三折通过、test 构建冻结就绪及适用训练授权 |
| 总体验收 | MODEL-QUALITY | 阻塞：最终质量及晋级 | FINAL-TRAIN、独立 test 及其他适用质量门；真实服务成功路径另核 |
| 非阻塞清理 | MODEL-ARCHIVE | 进行中（主 Agent）：归档与条件清理准备 | 证明完整迁移、冗余、引用退出及诊断保护；候选未删除 |
| 目标裁决 | RELEASE-POINTER | 待确认：旧指针目标适用性 | 新入口已显式选版本；不恢复旧写入、不阻塞新数据选择 |
| 低优先级 | CONTRACT-NAMING | 待处理：契约命名与复用边界 | 先解释实际职责，需要改名时再确认兼容方案 |

MODEL-QUALITY 是总目标。先冻结 test 数据及预注册准备，再训练最终候选；绑定 model/eval 的一次性 claim 在最终身份确定并获测试使用授权后、首次模型调用前建立。不能倒置为先测试通过才允许训练该候选。

## 待处理、待确认与阻塞事项

### RECOVERY-VALIDATION — 真实大型产物与外部依赖组合恢复

- **状态/来源**：待处理；迁移 Spec 保留的物理恢复限制，工程交付后继续单独验收。
- **事实与差距**：store 级异根恢复、SQLite/artifact 小对象联合恢复已通过；真实移动硬盘、大型 adapter/merged、SQLite、外部媒体与基座的整机组合恢复未完整验收，新 store 不自包含。
- **依赖/下一动作**：只读刷新已完成；继续核定备份、源/目标、设备容量及受保护引用，准备明确恢复任务单及适用操作授权；不删除唯一源。
- **验收标准**：恢复对象和外部依赖范围明确，摘要一致；原路径不可用时，恢复副本可解析并支持约定读取/准入；原备份和不可变事实保持。GPU 加载/模型效果另按授权验收。
- **证据/限制**：[验证记录](results/version-control-migration/verification.md)第33、39、41、66–67节；已有 CPU/store 证据不能外推为灾难恢复通过，本轮不执行恢复。


### MODEL-ARCHIVE — 中间模型证据归档与权重清理准备

- **状态/来源**：进行中（主 Agent）；用户要求验证能否保留历次训练参数和结果后清除训练机 run 下模型文件。用户已授权在完整迁移核验通过后清理旧数据与旧模型副本；未满足条件的文件继续保留。
- **已证实事实与差距**：2026-08-31 训练机 `workspace/runs` 约 90.253 GiB；原清单漏列两组 source-aware，concise-cv 约定路径不存在；r1 来源仍有 5 个 checkpoint，merged 为发布库软链接。5 组未发布模型 merged 权重合计约 80.988 GiB，各 root LoRA 约 439.1 MiB。原清单不足以放行删除；当时快照未哈希权重，未归档原始预测和完整训练日志。
- **现场增量（2026-10-13）**：旧Fold0及5个phase run的索引分片在场；coverage-first seed3407 merged仍共享发布库。concise/visual只在限定位置检查，未全面搜索或哈希权重、核验备份，清理条件仍未满足。见[现场报告](results/remote-state-refresh-20261013.md)。
- **依赖**：MODEL-DIAG 对历史/当前模型和阶段 checkpoint 的需求；当前发布模型及 `pipeline/checkpoint_policy.json` 保护边界。权重清理不隐含取消诊断任务。
- **下一动作**：按[归档模型清单第 8 节](results/model-inventory.md#8-2026-08-31-清理可行性核查)归档实际配置、模型/数据/Prompt/评测身份、完整日志和原始预测、文件哈希及备份校验；仅按已知身份和准确备份线索核查，不持续搜索缺失三折模型。逐 run 确定仅留研究记录还是保留 adapter 以便重新合并，形成显式候选清单并核对既有条件删除授权。保留 adapter 的方案先验证准确基座与合并链路，不以直挂 4-bit 代替 merged BF16。
- **验收标准**：每模型每 fold 有可核查的原始配置和结果链、缺失证据明确、归档已备份并校验；2026-09-13 新增 visual 三 fold merged 断链与concise缺失归入同一保护依赖（验证第48节）；清理路径不跟随链接误入发布库，不删除在用模型和未完成诊断所需文件；训练机按获准清单执行并记录删除前后体量、保留文件完整性及对应机器提交。完成可行性审查不等于归档或删除完成。
- **证据/版本/验证限制**：[模型清单](results/model-inventory.md#8-2026-08-31-清理可行性核查)、[训练机快照](results/model-inventory-audit-20260831/remote_snapshot.json)、[模型归档证据包索引](results/model_evidence/README.md)、[试点证据包`v4.1-prompt-minimal-v1-seed3411`](results/model_evidence/v4.1-prompt-minimal-v1-seed3411/README.md)。本地核查基线 `7b8192bd`，远端 `main@f1b7d8a3` 干净，本地独有 3 提交、远端独有 0；2026-08-31 调查的 SSH 仅执行 Git 状态、文件 stat/目录/链接与轻量 JSON 读取，不启动 GPU 任务、训练、合并或评测，不读取受限测试语义结果。仅快照及文档落本机，未同步/删除远程文件。独立 reviewer 的原稿 findings 已核对：保护条件缺失 P1、模型清单过期/证据不足/效果结论过度 P2；修订后独立 reviewer 复审通过，无剩余可执行文档问题；10 个清单链接、指标/契约对照与 `git diff --check` 通过。修正归档要求仍不代表已满足删除条件。
- **后续证据**：2026-09-13 条件清理授权涵盖旧数据及旧 run/model 的已核实冗余副本；89 个 train 视频大小/SHA 一致，但占用预检权限不足，删除 0、释放 0。新 store 的外部媒体与当前发布库仍受保护；见[验证记录](results/version-control-migration/verification.md)第56–58节。下一轮刷新后核定候选，不能将历史验签当作今日可删除证明。

### HOLDOUT-BUILD — 构建并授权未使用的 test 数据分支

- **状态/来源**：阻塞（Codex已完成test数据分支处理/全量人工审查/封存发布/最终测试接线，代码abafdbf2；解除条件为核清既定test source独立使用资格、取得适用真实构建授权、完成人工审查及真实媒体验证）；由TEST-POLICY拆出，数据冻结支撑FINAL-TRAIN，最终候选测试支撑MODEL-QUALITY。
- **事实与差距**：既定test分支21个视频及三折隔离已在训练机找到，不再以“source未指定”阻塞定位。旧release `v4.1-sealed-test-5546b8bf1ec3` 的一次性claim与completed/exposed凭据仍在；其摘要20source与332份媒体凭据的20source集合相关联，video_0005无该批候选凭据。原发布目录已缺失，不能把“缺文件”解释为“没用过”，也不能仅据无候选就认定video_0005可独立覆盖七门。当前缺口是使用资格及正式输入证据，不是初始划分不存在；未使用的新release尚未发现。
- **数据来源**：定义并人工审查一个独立于开发/调参的 source；沿用 `development_source_isolation_verified`、`test_split_binding_verified` 的隔离要求，纳入前核对 source 边界，避免与现有 sealed-test 或开发验证集混用。
- **人工审查**：对候选样本执行有效视图/剪裁人工审查（对应 `review_*` 流程），核对批次与 source 分层，形成冻结的 review batch 后再生成 release。
- **发布入口与差距**：test七阶段显式使用`--purpose holdout --test-config ...`，新模块`versioning/holdout_pipeline.py`在owner-only工作区复用媒体算法，所有候选必须人工审查。train默认路径不变。真实输入必须为独立test批次、具备冻结train版本的source清单及旧测试非语义来源清单；当前既定test source已定位；可用资格与完整非语义清单仍须核定。新入口及完整参数/产物来源见[入口说明](../versioning/SCRIPTS.md#test-数据分支处理全量人工审查与封存)。
- **已确认实施与限制**：用户于 2026-09-13 确认 test 分支方案，Mac合成完整builder→claim→prepare→run→score通过。原审查发现真值摘要未校验P1和发布rename后封存尾步恢复P2均修复并专项复核；公开input仅固定整体receipt摘要，真值pin在授权score读取。当前test分支不自动向DVC remote发布受限数据；2026-09-13 源码与 Mac 验证完成不表示真实数据已构建，随后 Linux 同代码 427 passed/1 skipped 通过，见第52节。
- **授权流程**：预注册一次性授权 + one-time claim，沿用现有 stage_d 流程；授权条件 `one_time`、`tuning_use: forbidden`、`pre_stage_g_outputs: aggregate_pass_fail_and_integrity_only`，首次模型调用前原子写入 claim，只允许同一 run identity 恢复。
- **阈值**：沿用 `stage-d-preparation-5cd1b3fa343c` 已冻结的 7 项阈值（`four_state_macro_recall 0.4006`、`fracture_three_state_macro_recall 0.3`、`joint_correct_rate 0.3921`、`runtime_failure_count 0`、`strict_valid_rate 1.0`、`已断裂_recall 0.15`、`未断裂_recall 0.7`）。
- **依赖/边界**：本任务只负责构建、审查、发布与授权一个未使用 holdout，不隐含“策略已确定即已构建”；完成本项不等同于最终模型已通过该 holdout 验收。不得读取现有 sealed-test 受限语义结果来构造 holdout。
- **验收标准**：新的未使用 holdout release 已构建并经人工审查，source 隔离与 test-split binding 校验通过，manifest/ground-truth/quality_report及预注册准备可追溯。数据冻结就绪先支撑FINAL-TRAIN；最终model/eval身份确定并获使用授权后，首次模型调用前建立绑定claim，再支撑MODEL-QUALITY。不能要求先有最终模型claim才能训练该模型。
- **证据/限制**：[验证第48节](results/version-control-migration/verification.md#delivery-preparation-20260913)及[轻量证据](results/model-diagnostics-preflight-20260913.json)。2026-09-13 已核查新 store 集合与公开入口，未全盘扫描旧sealed-test集合，不推断历史对象已消失；未读取受限语义或创建真实holdout。最终候选model/eval身份形成前不提前创建绑定它们的一次性claim；保留预注册和首次模型调用前claim的要求。

### MODEL-DIAG — 诊断并改善三折类别坍缩与契约退化

#### 新诊断方案草案（待确认，不是训练授权）

目标是建立当前新入口下可追溯、可重复的train分支基线，逐步诊断字段遗漏与类别偏置；不承诺恢复旧实验，也不将缺失权重视为继续搜寻的前置。

- 推荐从冻结train版本和明确基座修订重新建立一个单折基线，使用对应fold的完整validation及现有严格评分入口。先只读验证输入/配置/资源，明确完整data、prompt、train身份和媒体根；基座存在性与适用性另核，不预设当前已经可用。
- 数据、Prompt、采样、训练日程、生成参数先冻结；单折结果用于定位合法率和类别召回退化，每轮只调整一个因素。单折方案稳定后扩展三折，再按既定依赖进入full训练与最终test。
- 开发侧同时报告四字段合法率/正确率、各状态召回、macro recall、joint与失败样例。开发侧数值通过门槛须在实验前确认，不能借用test七项门槛或观察结果后回填；若正式validation配置不能表达诊断指标，先提出局部设计，不悄悄改接口。
- 不引入冻结分层canary或任意替换模型训练Prompt的交叉入口；这些能力尚未实现，增加它们会扩大范围。另一方向是先建立全部三折基线，比较更完整但成本更高；推荐单折起步会有fold偏差风险，必须由后续三折验收控制，不能据单折直接放行full训练。
- 待确认项：是否采用上述新基线方向；随后冻结基座/数据/Prompt/配置、开发侧门槛和资源预算。确认方案后仍须取得真实训练/推理授权。该方向仍为草案。


- **状态/来源**：待确认（诊断方案；可继续只读证据准备）；原“三折实验出现类别坍缩与契约退化”。目标是在固定证据与评价口径下找到可跨 fold 复现的改进方案。
- **事实与差距**：已同步报告记录 `v4.1-prompt-concise-cv-v1-seed3411` 的 1581 条评测：contract 合法率 79.63%、joint correct 32.07%、`clip_state` 35.80%，322 条非法输出中 311 条缺 `special_case`，“临界未断裂”和“已断裂”召回为 0%。这支持退化症状，不证明 Prompt、采样或早停中的任何一个是单独根因。
- **下一动作**：整理已允许公开的开发证据、缺失文件身份和现行入口任务单；将上述新基线方向、开发侧门槛与资源预算交用户确认。下一轮训练机只读刷新由 REMOTE-STATE-REFRESH 统一安排；不重复全盘查找缺失三折模型，不将报告摘要当作权重或原始预测。方案确认和真实训练/推理授权分别落实后才执行实验。

- **入口与产物**：2026-09-13训练机复核concise约定run/三fold原始记录缺失；历史visual的三折原始记录可读，但run_identity指向的merged均为断链，目标是`workspace/runs/v4.1-visual-cv-v1-seed3407/fold{0,1,2}/merged`。新正式评测由`python -m versioning eval prepare/validate/run/export`消费合法model完整身份、Registry数值版本和冻结data/Prompt；旧`finetune/eval_run.py`仅保留业务函数，CLI已停用，不能用裸路径绕过。正式入口目前使用全validation，尚不支持冻结分层canary或任意替换模型训练Prompt；这些对照能力须作为后续获确认的诊断方案，不写成现成命令。
- **准备与执行边界**：按[新入口说明](../versioning/SCRIPTS.md)准备完整data/prompt/train身份、显式媒体根、来源输入及三折配置；`versioning train prepare/validate`负责冻结与校验，`run/export`负责实际执行和产物证据。旧build/prepare/train CLI已停用；底层函数供新入口调用。历史模型只有报告/裸目录时不能强行登记为新正式completed；先找回原始配置、权重及逐样本身份链。
- **依赖/边界**：开发集只读整理不等待 HOLDOUT-BUILD；实验执行前明确测试隔离规则、冻结开发侧阈值并核对授权。现有交付配置记录 optimization paused / retraining unauthorized；本轮只整理该方案与证据说明，不执行准备命令或恢复训练授权。不使用 sealed-test 调参，不补字段伪造合法率，不删除诊断所需 checkpoint。
- **验收标准**：身份链一致、原始预测可追溯，根因分清事实与假设；报告四字段合法率/正确率、各状态召回、macro recall、joint correct、分布和失败样例；单变量结果可比较，三折达到预定开发侧标准后才放行 FINAL-TRAIN。仅完成诊断时记录阶段结果，不宣称效果改进已完成。
- **证据/限制**：[三折报告](results/v4_1_prompt_concise_cv_v1_seed3411/README.md)、[模型门禁基线](results/model-gate-baseline-20260914.md)、[交付配置](../delivery/model_component.json)。报告第 10.2 节同时改 Prompt/采样/早停的建议不满足本任务的单变量标准；2026-09-13 在 Linux 重算历史 visual 的 1216 条开发原记录，concise原始预测仍缺且未复算。新增[第48节证据](results/version-control-migration/verification.md#delivery-preparation-20260913)记录三fold模型断链和能力前置，不能据历史输出关闭改善任务。

### RELEASE-POINTER — 安全更新并激活数据 release 指针

- **状态/来源**：待确认（迁移后适用性）；原“release 指针文件更新自动化”。旧指针原目标保留追溯，未授权恢复其活动写入。
- **事实与差距**：原 legacy 指针为手动维护；运行时校验契约内容哈希和 manifest 文件哈希，原方案仅更新两个字段不完整。
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
- **证据/限制**：[开发 release 摘要](results/v4_1_phase2_development_release/release_summary.json)、[当前模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json)、[模型流程](model-workflow.md)；截至既有记录无全量最终模型证据；2026-10-13只读刷新了限定文件位置，未执行全量训练或模型质量验收。

### MODEL-QUALITY — 最终模型质量验收与晋级

- **状态/来源**：阻塞；原“当前发布模型质量门未通过”，作为总目标，依赖 MODEL-DIAG、FINAL-TRAIN、HOLDOUT-BUILD和HOLDOUT-METRICS；RELEASE-POINTER原目标适用性另待裁决。
- **事实与差距**：`v4.1-agent-pipeline-fold0-r1` 已用于工程链路验证，但 Stage B/D/G 标志均为 false，`production_approved: false`。标志为 false 不等于每一门都已执行失败，须查各门证据。
- **下一动作**：核对适用质量门、阈值和证据要求并落实到子任务；最终候选和测试前置齐备后，按授权协议完成独立验收及其他质量门，再决定晋级。
- **入口与产物**：参照 [发布证据](results/v4_1_agent_pipeline_fold0_r1/README.md) 和 [模型流程](model-workflow.md) 核对执行入口；冻结报告和模型哈希，经注册表发布新身份并同步 delivery，核对服务加载对象。缺可执行入口则先补任务单/实现，不把历史归档命令写成现成流程。
- **验收标准**：预定质量门与身份校验均有证据，模型/报告/注册表/delivery/服务一致；新候选不覆盖旧模型历史结论，工程成功不能替代质量通过。
- **证据/限制**：[交付配置](../delivery/model_component.json)、[模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json) 及现有 sealed-test 公开结果；目前不满足最终交付标准。

### CONTRACT-NAMING — 澄清候选规划与训练发布的契约边界

- **状态/来源**：待处理，低优先级；原“V3 命名遗留”。目标是降低理解成本，不改变冻结产物语义。
- **事实与差距**：候选计划 `_validate_contract` 要求 v3，重建入口实际加载 v3；后续 V4.1 审查/发布继续复用候选。因此不是纯历史路径，也不能直接换成 v4.1 契约。
- **下一动作/依赖**：先在模块说明中解释复用边界；仍有必要时再设计不带版本号的模块命名与兼容方案。主链路问题优先。
- **验收标准**：模块说明、imports、SCRIPTS.md 和流程文档一致；若重命名，验证既有调用与历史产物兼容性，不意外改变内容寻址身份。
- **证据/限制**：[候选计划](../pipeline/v3_candidate_plan.py)、[候选物化](../pipeline/v3_candidate_media.py)、[重建入口](../pipeline/scripts/rebuild_data.py)；尚未实施澄清或重命名。

## Skill 改进候选（待确认，不属于当前实现范围）

### SKILL-FEEDBACK — 用实际迭代案例评估 explain-project 的维护能力

- **状态/来源**：待确认；用户要求后续结合经验考虑针对性改进，当前未要求修改 skill。
- **现有规则**：本机 Pi skill 位于 `/Users/pcoffeep/.pi/agent/skills/explain-project/SKILL.md`，模板位于同目录 `references/todo-document.md`。原调查只读核对：它支持初次介绍及后续问答时维护 TODO，但不负责完整任务执行流程；模板“已解决”偏向代码修复，不充分表达误报澄清、远端验收和多 Agent 交接。后续修改前须核对当时版本，不假定其他机器同路径可用。
- **案例/候选调整**：REL-VERIFY 是环境验收，CONTRACT-HASH 是误报关闭，都无需业务代码修复；TEST-POLICY / FINAL-TRAIN 体现任务拆分与排序；DOC-INDEX 体现解决后发现文档残留。候选包括证据来源/机器标记、关闭原因、固定标识与拆分关联、新问题去重和交接。
- **下一动作/边界**：继续积累案例，区分项目流程约束与通用文档能力；用户决定修改时再加载适用的 skill 创建/修改规则，选取有证据的最小改动。不把 4090、封存测试或本项目排序推广为通用要求，不宣称 skill 已有当前执行循环。
- **验收标准（未来获准修改时）**：改进有案例和边界，保留项目介绍与任务执行职责分离，用初次创建、后续更新、误报关闭、执行中新发现等案例验证；当前只记录候选。

## 已解决与已关闭

### REMOTE-STATE-REFRESH — 训练机现状只读刷新

- **状态/来源**：已解决（2026-10-13，Codex）；用户授权只读现状核查，禁止远程写入、同步代码、训练与评测。
- **结果**：训练机 main 与实时 Codeup main 均为 `3f200461` 且训练机/子模块干净；Mac 起始 `59dee2d1` 比该基线领先 5 提交。Conda agent/cpm45 为 Python3.11.15，但当前锁依赖与源码绑定仍有缺口；历史 mirror venv 绑定隔离 checkout。r2 active，1678 个去重媒体引用 stat 缺失0；旧Fold0与基座索引分片在场，concise/visual在限定路径仍有权重缺口；指定store正式运行记录尚未产生。
- **后续/依赖**：MODEL-DIAG、MODEL-ARCHIVE 与 RECOVERY-VALIDATION 保持原状态；ENV-ACTIVATION由随后获授权的新Conda环境部署解决；正式 Registry 配置根与模型来源随环境/诊断准备核定，不据指定目录缺失推断全盘无记录。
- **验收/证据**：[现场报告](results/remote-state-refresh-20261013.md)、[返回快照](results/remote-state-refresh-20261013.json)记录机器、起始版本、命令、退出结果、覆盖范围与限制；独立reviewer已核查返回快照、锁项与正文链接；普通git status潜在索引刷新偏差已披露，无其他可执行问题。报告及台账提交由 `git log -- docs/results/remote-state-refresh-20261013.md` 追溯。
- **限制**：模型盘点一次普通git status可能刷新.git/index，未采集前后元数据，不能证明或排除；这不影响工作区内容干净的结论。没有加载模型、导入torch、执行doctor、读取测试语义、哈希大型产物或全面验证媒体链接/解码；不存在性结论限指定路径。只读刷新完成不代表正式Conda合格、真实质量/test/服务或恢复通过。

### ENV-ACTIVATION — 正式解释器与最终 checkout 绑定

- **状态/来源**：已解决（Codex，2026-10-13）；用户同意按当前GPU锁新建Conda Python3.11环境、保留旧环境并绑定正式checkout。
- **结果**：训练机 `/home/liuyang/miniconda3/envs/mvllm2/bin/python` 为Python3.11.17；GPU锁241个精确项缺失0/版本差0，244包兼容检查通过，doctor errors为空、CUDA可见且训练模块导入通过。LlamaFactory editable绑定正式 `/home/liuyang/文档/mVllm_2/LlamaFactory`，checkout/submodule为3f200461/4447137e且保持干净。
- **保护与后续使用**：agent/cpm45的发行包元数据、conda-meta和指定pycache快照前后相同；没有修改用户shell默认环境。后续显式使用新Conda解释器，checkout/依赖/子模块变动后重新核验绑定；历史venv和旧环境继续保留，不重新打开已解决部署功能任务。
- **验收/证据**：[部署报告](results/conda-environment-setup-20261013.md)、[执行快照](results/conda-environment-setup-20261013.json)；安装及审计SSH均exit0，冻结脚本通过独立执行前审查，结果独立核查通过：脚本身份及返回快照一致、241锁项和旧环境保护证据匹配，原31任务标识保留，83本地链接/锚点有效；未关闭模型/test/恢复任务。Mac本地记录提交由 `git log -- docs/results/conda-environment-setup-20261013.md` 追溯。
- **限制**：没有同步代码、初始化业务store、处理媒体、加载模型、训练、推理或评测；环境验收不关闭模型/test/真实服务及恢复门槛，旧环境摘要比较不等于所有文件逐字节审计。


以下保留前序任务原验收依据，历史测试未因文档整理而复跑。工程任务关闭不自动关闭模型、test 或真实恢复验收。

### DOC-INTEGRATION — 正式整合项目文档目录：已解决

- **状态/来源**：已解决（Codex，2026-10-12，本机）；用户认可四份说明并授权正式替换根README、清理覆盖旧说明，保留任务台账、设计决策和原始验证证据。
- **结果/验收**：正式入口为根README与docs下data-workflow、model-workflow、project-status；删除七份重复说明及候选目录，完整归档模型现场基线、模型清单和阶段一审计报告。同步AGENTS/架构/接口索引和停用CLI提示导航，不改变运行入口行为或授权。Mac uv、训练机Conda Python、3.11.x及两平台依赖分工保持。
- **独立核查**：reviewer结论通过，无可执行问题；冻结版本50份Markdown、289个本地链接/锚点0错误，25个shell块语法通过。原30个任务标识保留，31标识唯一；65份非Markdown原结果、ADR/迁移确认链/研究材料及决策日志完整性核对通过，归档统计和清理标准未丢失；十个Python变更严格仅停用提示路径文本。
- **证据/限制**：[正式整合记录](results/documentation-consolidation-20261012.md)；提交由 `git log -- README.md docs/project-todo.md` 追溯。本轮不执行pytest、业务CLI、安装、UI/server、SSH、实际数据处理、训练、推理或评测；历史结果未复跑，不关闭模型/test/Conda现场或真实恢复缺口。下一步仍为REMOTE-STATE-REFRESH。

### README-PUBLIC-INTRO — 项目介绍与新人快速开始：已解决

- **状态/来源**：已解决（Codex，2026-10-12，本机）；用户要求根README面向首次访问者介绍项目概念、实际用途、初步成果及快速开始。
- **结果/验收**：README以项目介绍和快速开始为核心，解释窗口采样/四字段、ROI/LoRA/三折，介绍历史Fold0开发集成果并保留未通过最终独立test的限制；给出两平台部署、检查入口、资产前置和分目标手册导航。没有虚构公开下载、许可或可直接推理的演示。
- **独立核查**：reviewer对照部署脚本、锁文件、子模块、契约、历史逐项结果及Registry，结论通过，无可执行问题。用户已有顶部治理块删除保留。
- **证据/限制**：[验证第69节](results/version-control-migration/verification.md#readme-public-intro-20261012)；文档命令未运行，未安装、SSH、训练、推理或评测。提交由 `git log -- README.md` 追溯。

### DOC-CONSOLIDATION — 现行文档与任务台账收敛：已解决

- **状态/来源**：已解决（Codex，2026-10-12，本机）；用户授权统一迁移后状态、正文和导航，保留设计/决定/验证证据，清除过期下一动作并独立核查。
- **结果/验收**：前序现行数据、训练与服务正文退出旧 CLI 操作；当前状态、完整数据身份与入口导航一致。工程迁移等已解决事项统一进入关闭区；MODEL-DIAG 待确认，模型/test/真实恢复限制保留。已执行 Plan 保存范围、选择与最终矩阵，详细历史仍在验证记录和 Git。
- **后续成果**：新候选手册在 `389c797e` 完成交付及独立核查，`f8af0bba` 修复 ROI 直接文件导入并统一 Mac uv/训练机 Conda Python 及 Python 3.11.x；具体实际检查和限制见[文档整理记录](results/documentation-consolidation-20261012.md)。这些结果没有刷新训练机或关闭真实环境、模型/test 与恢复缺口；正式目录切换由 DOC-INTEGRATION 承接。
- **独立核查**：reviewer 对照代码及历史证据核查17份正文；首轮服务模板路径 P2 已修复并复核，最终无剩余可执行问题，结论通过。输入来源、七阶段产物、UI交接、claim/评分、alias服务参数及证据边界均静态核对。
- **证据/限制**：[验证第68节](results/version-control-migration/verification.md#document-consolidation-20261012)记录该次覆盖、检查和限制；该次未 SSH、训练、推理、评测、运行应用或 pytest，历史动态结果未复跑。提交由 `git log -- docs/project-todo.md` 追溯。

### VERSION-CONTROL-FORMAL-MIGRATION — 正式迁移可读版本控制体系：已解决

- **状态/来源**：已解决（已确认工程范围，2026-09-14）；用户授权先模型调查落文档、再推任务分支、后合并 main；`5acebc27` 按序进入 Codeup main 并同步训练机正式代码，双机 CLI 核验通过。
- **关联与已确认范围**：[Intent](tasks/2026-09-07-readable-version-control-migration/intent.md)、[Spec](tasks/2026-09-07-readable-version-control-migration/spec.md)、[已执行 Plan](tasks/2026-09-07-readable-version-control-migration/plan.md)。承接核心基础设施，迁移两个已发布 data 与一版 Prompt，保留历史模型事实，接管活动入口；单写、完整身份、恢复不丢事实及原质量门保持。
- **结果/验收**：数据真实媒体对照、审查包双机往返及 r1/r2 内容保持完成；训练/评测/服务执行接线、旧 CLI 退役、store 异根恢复、七门、test 分支、部署及逐折工程验收完成。最终整包及后续增量独立审查、授权集成、双机代码落点已闭环。
- **证据**：[验证记录](results/version-control-migration/verification.md)第12–24节（迁移与真实媒体）、25–47节（接线/退役/恢复/完整审查）、48–55节（交付与模型/test证据）、59–65节（输入/部署/逐折）、66–67节（最终范围与集成）；[入口清单](results/version-control-migration/entrypoint-map.md)、[交接](results/version-control-migration/handoff.md)。历史详细施工记录由验证记录与 Git 追溯，不再作为下一动作。
- **保留限制与后续任务**：新 store 引用原 workspace 媒体，不能删除被引用路径；真实 GPU 训练、独立 test、最终质量与真实服务成功路径归 HOLDOUT-BUILD / MODEL-DIAG / FINAL-TRAIN / MODEL-QUALITY；真实大型/外部依赖组合恢复归 RECOVERY-VALIDATION，正式解释器激活归 ENV-ACTIVATION。远端记录未在本次2026-10-12整理中刷新，不把 CPU 工程验收写成模型效果通过。


### HOLDOUT-METRICS — 已冻结七项holdout门槛与正式评分入口衔接

- **状态/来源**：已解决（Codex，该批代码/CPU范围，f1be1060）；HOLDOUT-BUILD该批准备发现，用户已明确“确认，按原七项门槛补齐”，Spec55b3f4d4/Plan061d2598已单独提交。保持TEST-POLICY原定义和阈值，validation不变。
- **发现时基线事实（第48节，修复前）**：`finetune/eval_run.py::_formal_config`当时仅接受六项通用正确率，holdout共用此配置与最小值比较。七项既定门槛中仅`joint_correct_rate`可原名表达；宏召回、两类召回、runtime失败数及strict合法率均不能原样输入。纯配置反例拒绝七项、单joint控制通过，未访问数据/Registry。
- **完成结果**：已接入七门完整配置、私有数值指标及公开二值gate，Mac两进程614 passed/1 skipped、Linux首组加拆组167/240合计614 passed/1 skipped，实际各exit0，独立93项及篡改/Registry探针通过。Linux原合并组文件句柄耗尽exit1保留，不声称单进程通过。原f04ca7cb定义核对：runtime失败数等于0，其余为下限，缺四状态拒绝；原函数200组合成差分一致。不自动重命名或遗漏门槛，也不把全部指标当下限。
- **验收标准**：七项可冻结并与预注册精确一致，原输出重算可追溯；缺类、非法输出、runtime失败、边界值、恢复及下游准入均按原规则决定，不消费真实测试集来验代码。
- **证据/限制**：[第48节](results/version-control-migration/verification.md#delivery-preparation-20260913)、轻量JSON的`threshold_probe`；第48节保留缺口发现快照；该批已按确认实施，最终验证与代码版本见第49节。既有整包代码审查保留原冻结范围，新增变更另行验收。

### DOC-INDEX — 修正脚本索引的过期缺陷描述

- **状态/来源**：已解决；关联已解决的 PIPE-INDEX，该批 M7a 文档同步完成。
- **结果**：脚本索引已删除“promote 未传播 source/split 索引”的过期描述，说明历史 promote 业务函数在快照移入正式 workspace 后更新集合索引，同时标明公开 rebuild_data CLI 已停用。
- **验收/证据**：对照 `pipeline/data_rebuild.py::_update_snapshot_collection_indexes` 及 promote 中的调用顺序核对；实现来源 `cdb8632c`，该批仅修正文档。历史业务联合回归本机 57 passed；修改提交由 `git log -- pipeline/scripts/SCRIPTS.md docs/project-todo.md` 追溯。
- **限制**：不重新开放 legacy CLI，不代表索引库已退役；未执行真实数据 promote。

### M8-R7 — 训练入口路径优先级测试依赖全局导入顺序：已解决（该批范围）

- **状态/来源**：已解决（Codex；代码 `d9ec1227`）；父任务整仓测试在 `e1d70c58` 发现，原第46节为失败证据。
- **已证实事实与修复**：原测试受其他测试收集时的 `sys.path` 变动影响。路径优先级断言现由新 Python 进程验证，训练器对实际 LLaMA-Factory 模块来源的运行时拒绝门保留。
- **验收与证据**：[验证第47节](results/version-control-migration/verification.md#m8-r6-r7-20260913)：原失败顺序组合 Mac/Linux 各 1 passed/49 deselected、exit0；Mac 整仓 2694 passed/11 skipped、实际 exit0；独立复核另验证错误实际来源仍被拒绝。11项 skip 均因本机历史数据/fixture 缺失，不代表真实模型效果。

### M8-R6 — 外部训练初始化权重未纳入冻结输入：已解决（该批范围）

- **状态/来源**：已解决（Codex；代码 `d9ec1227`）；父任务完整独立审查在 `e1d70c58` 发现 P2，原 adapter/checkpoint 漂移反例见第46节。
- **已证实事实与修复**：当前契约不支持外部 adapter 或 checkpoint 初始化/恢复；CV/full 的 prepare 在冻结前拒绝两类非null配置，旧冻结记录在 validate/run/export 与 Registry 训练证据门拒绝。旧完成/失败事实不改写，缺少来源证据的模型不能登记或进入后续准入。
- **验收与证据**：[验证第47节](results/version-control-migration/verification.md#m8-r6-r7-20260913)：Mac 相关179项、Linux同组179项各exit0；独立审查重用原两类漂移 fixture，旧记录各拒绝且Run/ModelVersion/状态/params不变；整包代码差异审查对140提交/152文件结论通过。上述为CPU合成验证，未声称外部权重路径已获支持或真实GPU训练通过。

### M8-R5 — 服务Prompt来源未与被评冻结输入绑定：已解决（该批范围）

- **状态/来源**：已解决（该批实现范围；Codex；用户2026-09-13确认兼容策略，Spec789fa4fc/Plan511cfc14）；父任务VERSION-CONTROL-FORMAL-MIGRATION的最终完整独立复审发现P2，代码ab5c71ae。
- **已证实事实与差距**：第43节发现时，prompt-v4.1-r1保持原concise-v2内容，与固定service analysis的system/user不同。独立CPU链路在真实证据门下构建合法candidate后，server_proxy.main仍在加载器前拒绝；不是缺alias的允许拒绝，不能宣称此Prompt对应模型端到端可服务。反例还证明同ID当前定义替换为固定契约后，resolver指纹不变且错误放行服务，未与训练/eval冻结内容绑定。
- **已确认决定与结果**：用户2026-09-13已确认采用模型冻结并验签的Prompt，保持输出/评分/alias/审批/备份门禁，并同步请求识别、重试和交付契约。Spec789fa4fc/Plan511cfc14记录，代码de1b51dd已实现。Mac广回归195 passed/1 skipped及新增5项通过，独立25+5项和操作说明通过；Linux最终200 passed/1 skipped、两组exit0，保护文件保持；该批R5闭环。后续实际GPU加载/模型效果另验；父任务full/holdout接线及双机隔离CPU验证已完成（fed9bcfc，第45节），第46节原整包驳回已由第47节R6/R7修复及更新的独立代码审查闭环，真实holdout仍未验证。
- **验收标准**：当前迁移Prompt的合法模型可以通过实际服务CLI路由并使用其冻结输入；不兼容输出结构、模型版本/文件漂移、非法alias继续拒绝。训练/eval冻结Prompt及其摘要必须进入服务绑定，当前同ID内容漂移在加载前拒绝。CPU替身证据与GPU模型加载/效果证据分别标记，不将修复外推为模型质量通过。
- **证据/验证限制**：[第43节](results/version-control-migration/verification.md#m8-final-20260913)，pipeline/server_proxy.py:447–452；独立fixture`/private/tmp/mvllm2-final-concise-service-0bdr7oux`。修复证据见[第44节](results/version-control-migration/verification.md#m8-r5-prompt-20260913)，代码de1b51dd；旧行号/fixture仅追溯发现时事实。未运行GPU或读取受限测试结果，不以该批局部通过代替整体验收。

### M4-FOLD — 三折分次执行入口

- **状态/来源**：已解决（本批工程实现，61effebd）；用户确认逐折接口与复用/partial规则并授权工程实施，Spec b1aaf315、Plan902d8c9d。
- **发现时事实（修复前，e7efb56b）**：prepare需要三折完整配置；当时run循环执行全部折，已存在任一输出即拒绝；底层有fold子Run，但不能绕过公共入口手工记完成。2026-09-14核对e7efb56b：CLI虽然解析`--fold`，train run未传入执行器，不能用该参数实现单折；详见verification第64节。
- **已确认方案**：同一train版本冻结三折，`train run --fold 0/1/2`仅执行指定折；省略`--fold`保留整组三折行为（续办时仅执行未完成折），full拒绝`--fold`；分次执行同一父Run，已完成折验签复用不重训，部分成功不标整组completed；三折真实证据齐全后汇总；full独立。失败折不自动覆盖或续训。
- **验收**：逐折真实适配器调用边界用合成替身验证，子/父状态与产物一致；已完成折不重跑、并发/漂移/失败保留、缺折不晋级、旧full行为不退化。无需为了此功能启动实际模型训练。
- **结果/限制**：实现及独立审查通过；Linux 最终 123 项合成回归通过，见验证第65节；集成已完成（第67节）。真实训练与模型效果不在此工程验收内。


### ENV-DEPLOY — 环境依赖与可重复部署

- **状态/来源**：已解决（本批部署实现与双平台新环境验收，83724995）；用户确认统一部署入口与隔离验证，未修改旧环境。
- **发现时事实（修复前）**：见verification第62节。agent现有GPU训练依赖自洽但缺DVC/MLflow/cropper；cpm45有7缺包和4版本冲突且editable来源旧项目；隔离环境为CPU集成环境且pandas违反MLflow声明。README缺少cropper安装；finetune说明引用不存在的requirements/minicpm-v.txt。pyproject与GPU依赖的AV区间不兼容，不能直接合并安装。
- **实施结果/剩余边界**：已实现Mac轻量/Linux GPU锁定配置、兼容DVC/MLflow/pandas、cropper、单入口与doctor，双平台新环境通过；详见第63节。正式激活解释器须结合最终checkout路径核定，不能让editable引用被删除；正式激活另记 ENV-ACTIVATION。
- **验收**：新建环境可按文档自动部署，pip check无冲突，DVC/MLflow及活动CLI可导入，LLaMA-Factory来源正确、ffmpeg/ffprobe可用；Mac不装GPU栈，Linux明确CUDA包；合成链路与入口验收通过，过程不训练模型或使用test。
- **前轮核查边界（第62节）**：当轮仅包元数据、pip check和文件审阅；没有下载解析安装测试、安装依赖、改环境或训练。pip check通过仅证明已安装包声明不冲突，不证明项目所需包完整。


### VERSION-CONTROL-MIGRATION — 可读版本控制核心基础设施：已解决

- **结果**：`refactor/readable-version-control` 已完成 B0–B12。新增独立 `python -m versioning` 六领域入口、五类完整可读身份、数据封存与 DVC 七阶段、Prompt 冻结、MLflow train/eval、不可覆盖 manifest、唯一 `mVllm2` Registry、严格 model layout 与 alias/current、分级离线备份及灾难恢复；当时尚未进行 legacy 入口迁移。
- **最终证据**：核心修复提交 `9965dc1b`；`tests/versioning/` `1399 passed`，整仓 `2082 passed / 11 skipped`，均正常退出；9 个目标 Markdown 本地链接、2 个 YAML、172 个 tracked JSON、编译、CLI help、diff/未跟踪/大文件检查通过。独立 reviewer 对 R1–R11 执行相关套件、故障注入、备份恢复与跨进程锁攻击，结论为无剩余 P0–P3 actionable finding。完整提交与 finding 证据见[实施台账](plans/2026-09-01-readable-version-control-implementation.md)。
- **验证限制**：未连接训练机，未执行 GPU/真实模型/正式数据/真实移动硬盘操作；`fcntl.flock` 已在当前 macOS 双进程验证，基础设施验收时 Linux 训练机 smoke 尚未执行（随后正式迁移已补）。未 merge、未 push、未正式迁移或删除 legacy。
- **后续拆分**：正式迁移另记 VERSION-CONTROL-FORMAL-MIGRATION，按用户单独确认与授权实施；该正式迁移现已解决，核心基础设施的历史关闭依据不变。

### AGENT-INSTRUCTIONS — Codex/Pi 共用指令契约修正：已解决

- **结果**：项目根 `AGENTS.md` 补建 Document Contract；新体系身份明确为 `<kind>-v<协议>-r<N>`，legacy ID/index 规则整体限定到 `pipeline/`、`finetune/` 旧入口；提交尾注按 Codex/Pi 真实执行平台区分；临时分支状态、SSH 明细、评测字段明细和 skill 起源历史从长期根指令移出或下沉，委派要求改为平台无关的结果约束。`ARCHITECTURE.md` 的三处身份简写同步修正。
- **Pi 配套**：Pi 用户级 `SYSTEM.md` 增加项目约束传递字段和 Gate；Pi 用户级 `AGENTS.md` 的平台名称修正。Pi 的具体角色集合继续由其用户级配置独立维护，不在项目根 Instruction 中复制。
- **证据/限制**：`versioning` 身份测试、Markdown 链接检查、Document Contract/Decision Log 唯一性、Pi JSON/frontmatter 静态校验及 `git diff --check` 作为该批验收；未连接训练机，未启动真实 Pi 模型会话，也未执行图片生成任务。Pi 用户级文件位于仓库外，不随项目 Git 提交同步到其他机器。

### RUNBOOK-CONTRACT — 数据处理运行手册初始契约化与版本解耦：已解决

- **结果**：为当时的 `docs/DATA_PROCESSING_RUNBOOK.md`（现行说明由[数据处理](data-workflow.md)承接，原文可查 Git）补建独立、精简的 Document Contract；标题和长期定位不再绑定特定链路版本，正文集中声明当前数据处理链路版本为 4.1，并保留候选计划使用 v3、审查与发布使用 v4.1 的真实契约边界。README 导航已同步。
- **文档决定**：文档级 Decision Log 的 D001 记录继续维护单一、不带版本号的主手册；版本升级时同步核对版本声明、版本特有路径、命令、默认值和验收条件，不只替换版本号，也不另建平行主手册。
- **证据/验证限制**：本地 `git diff --check`、两个治理块唯一性与本地 Markdown 链接检查通过；脚本默认值静态核对支持 v3/v4.1 边界。独立 reviewer 首轮发现 Contract 将统一 resolver 能力错误泛化到 `review_decisions` 的 P2，修正为保留各集合解析与路径边界后复审通过、无剩余可执行问题；reviewer 另执行 2 个相关测试，结果 `2 passed`。该批未连接训练机，未运行 GPU、媒体物化或完整发布链路，不能据此宣称重新认证了手册中的全部既有命令。

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
- **证据/限制**：[指针](../finetune/active_data_release.json)、[验证入口](../finetune/release_validate.py)、前序写入本文件的训练机记录及用户确认。该批未重跑；前序未附执行 HEAD 和独立日志路径，不补造这些信息。`0ffecb3a` 是校验代码历史版本，不是远端执行版本。

### CONTRACT-HASH — 历史 v3 契约哈希差异：已关闭（误报）

- **关闭依据**：前序 Agent 核对训练机历史 manifest，确认是哈希口径混淆，并非契约丢失；据其记录，本地/训练机契约文件与 Git `033d82b4` 版本逐字节一致。
- **核对值**：文件 SHA-256 为 `e963cddff086114d5501392355ee64347e616c9b383f837f7293030b664d64af`；规范化内容哈希为 `3f9f8217774cb4947fc4e19e41a5fe14b8a5ea30c8e84ed4f664abddd9de04f0`，与内嵌哈希及历史 `identity.inputs.tensile_vlm_v3_contract_sha256` 一致。
- **证据/限制**：[契约](../pipeline/contracts/tensile_vlm_v3.json)、[算法](../pipeline/v3_candidate_plan.py)；训练机历史路径 `workspace/data/derived/metadata/v3/candidate_plans/candidate-plan-ce36b9226be5/manifest.json`，前序记录 plan_id 为 `candidate-plan-ce36b9226be5`。关闭的是“契约丢失”误报，不把字段一致性扩大为该批完整重建所有历史计划成功。原记录版本 `e027e82e` 只追溯问题来源。

### PIPE-INDEX — promote 不传播快照索引：已解决

- **结果**：`pipeline/data_rebuild.py` 在锁内、状态落盘前更新 source/split 集合的 index.json 与 LATEST，校验后写入，重入幂等且缺必要输入时 fail-closed。
- **证据**：修复提交 `cdb8632c`；`_update_snapshot_collection_indexes`、`tests/test_data_rebuild.py`。前序测试记录 `uv run pytest tests/ -q`：682 passed、12 skipped，并记录 reviewer 复验；该批只核对提交和代码，未重跑。
- **残余**：脚本索引过期描述已在 DOC-INDEX 修正，不影响原代码缺陷关闭。

### PIPE-STATE — rebuild 首跑状态跳转缺失：已解决

- **结果**：允许 `source_snapshotted` 转入 `waiting_for_roi_review`，无预置 ROI 决策的 review 模式首跑可等待人工标注，复跑幂等。
- **证据**：修复提交 `cdb8632c`；`pipeline/data_rebuild.py`、`tests/test_rebuild_source_only.py`。前序全量测试和 reviewer 记录同 PIPE-INDEX，该批未复跑。

### ROI-DEFAULT — ROI 标注默认 metadata 路径失效：已解决

- **结果**：`pipeline/scripts/roi_annotation_app.py` 从 source_snapshots 的 LATEST 解析 video_meta.json，支持显式路径/ID/前缀；缺 LATEST 或前缀歧义时 fail-closed。
- **证据**：修复提交 `cdb8632c`、`tests/test_roi_annotation_app.py`；前序全量测试和 reviewer 记录同 PIPE-INDEX。`f6881883` 为历史文档版本，不再标为未提交修复。
- **残余**：Streamlit 显示原始 ValueError traceback 是此前接受的呈现层风险；该批未重新验收 UI。

## 最近维护记录

- **2026-10-12（Codex，正式文档整合）**：新增 DOC-INTEGRATION，承接用户的根 README 替换和覆盖旧说明清理授权；保留原 30 个任务标识、设计决策和原始验证证据，最终独立核查通过、无可执行问题，DOC-INTEGRATION已解决。Mac uv、训练机 Conda Python 与 3.11.x 约定保持；本轮无 SSH、实际数据处理、训练、推理或评测，现场刷新仍为下一步。

- **2026-10-12（Codex，README续办）**：根README改为面向首次访问者的项目介绍与快速开始，静态独立核查通过，见验证第69节。无安装、SSH、训练或评测；训练机刷新仍后置。

- **2026-10-12（Codex，本机文档整理）**：移除迁移前的合并/补接线下一动作，将已解决工程条目统一放入关闭区；MODEL-DIAG 未实现 canary/交叉 Prompt 对照退出当前步骤，单折新基线仍待确认。恢复与正式环境激活保留独立未完成条目；DOC-CONSOLIDATION 经独立核查通过，首轮模板路径问题修复并复核，证据见验证第68节。未 SSH、训练、评测或清理产物。
- **2026-09-14（历史交付）**：工程交付与模型质量分开，部署和逐折能力验收后，按用户授权先推任务分支再快进 main 并同步训练机，见验证第63–67节。正式解释器未激活、真实训练/test/服务成功路径及物理恢复未验收。
- **2026-09-13（必要决定与调查）**：test 七阶段和七门接通不改变 TEST-POLICY；21 个既定 test source 已找到，但使用资格均证据不足，其中20个存在与暴露 release 关联的媒体凭据，见验证第49–53节。缺失三折权重的已知位置调查收束，不持续搜索、不以其他单折模型替代，见第54–55节。条件清理授权持续有效，89 个 train 视频仅验签，删除为0，见第56–58节。工程范围取消真实训练默认前置、正式输入预检与环境调查见第59–62节。

更早的施工、失败、修复与测试日志见[迁移验证记录](results/version-control-migration/verification.md)，原维护顺序可查 `git log -- docs/project-todo.md`。历史结果均按原机器、代码版本和覆盖范围读取，本轮不宣称复跑。

- **2026-10-13（Codex，只读刷新）**：REMOTE-STATE-REFRESH 完成限定现场查询；两端起始版本、环境来源、数据引用与模型资产已落报告。未执行业务写入、同步或真实模型运行；普通git status潜在索引刷新偏差明确留证。ENV-ACTIVATION 和模型/test/恢复缺口保持。

- **2026-10-13（Codex，训练机Conda部署）**：按用户授权新建mvllm2，Python3.11.17、GPU锁241项一致、doctor/依赖检查通过，ENV-ACTIVATION已解决。旧环境保护摘要和代码状态保持；无业务运行或代码同步，新体系记录按流程生成。
