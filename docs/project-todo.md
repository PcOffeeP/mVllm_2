# Project TODO

本文件是项目持续维护的任务台账，记录用户目标、当前差距、执行顺序和验证结果。维护规则见 [AGENTS.md](../AGENTS.md#todo-执行与维护)，不另建平行 TODO。

- 更新日期：随“最近维护记录”持续更新，不以文件头日期代替记录。
- 本轮依据：可读版本控制核心修复提交 `9965dc1b`、当前源码与本机最终回归，以及既有任务各自注明日期/机器的证据。前序对本文件的未提交修改已保留；本轮未连接训练机，未执行真实模型/数据迁移、merge 或 push。
- 主 Agent 汇总并维护，其他执行 Agent 按 AGENTS.md 交接证据和新发现。任务标识固定，不随排序改变。

## 下一步与执行顺序

**下一项先执行 HOLDOUT-BUILD：构建并授权一个未使用的 holdout 测试集，作为最终模型独立验收的前置，同时继续 MODEL-DIAG。** TEST-POLICY 已关闭（选定新建未使用 holdout、现有 sealed-test 不复测不调参）；历史问题 REL-VERIFY、CONTRACT-HASH 已关闭，不再重复安排首跑或契约找回。

1. 构建并授权未使用 holdout 测试集：隔离独立于开发/调参的 source，按已冻结阈值发布 sealed-test release，走预注册 + 一次性授权 + claim 流程；不得读取或混用现有 sealed-test 的受限语义结果。本步单独执行，不隐含于“策略已确定”。
2. 持续整理 MODEL-DIAG 的开发集证据和训练机任务单：先核三折模型身份与原始预测，再做无需重训的推理对照，最后考虑单变量训练。任何新推理/训练开始前，明确机器、输入、输出、资源和既有授权范围。
3. 开发侧三折方案稳定、holdout 构建就绪并冻结后，才进入全量最终训练、独立验收和模型晋级。新数据 release 切换前完成 RELEASE-POINTER；沿用现有 release 时它不阻塞首轮诊断。

| 顺序/定位 | 固定标识 | 任务 | 状态 | 依赖或触发条件 |
| --- | --- | --- | --- | --- |
| 独立验收前置 | HOLDOUT-BUILD | 构建并授权未使用 holdout 测试集 | 待处理 | TEST-POLICY 已确定策略；作为 FINAL-TRAIN / MODEL-QUALITY 独立验收的前置 |
| 主要技术工作 | MODEL-DIAG | 诊断并改善三折类别坍缩与契约退化 | 待处理 | 可先只读整理开发证据；执行实验前明确测试隔离边界和授权 |
| 清理前置 | MODEL-ARCHIVE | 中间模型证据归档与权重清理准备 | 进行中（主 Agent） | MODEL-DIAG 权重依赖、完整证据备份、显式删除授权 |
| 发布前配套 | RELEASE-POINTER | 安全更新并激活数据 release 指针 | 待处理 | 下一次数据 release 切换前完成 |
| 后续训练 | FINAL-TRAIN | 全量开发数据训练最终候选 | 阻塞 | 开发侧三折验收通过、holdout 测试集就绪及训练授权 |
| 总体验收 | MODEL-QUALITY | 最终模型质量验收与晋级 | 阻塞 | FINAL-TRAIN 候选、holdout 独立验收及其他适用质量门 |
| 文档收尾 | DOC-INDEX | 修正脚本索引的过期缺陷描述 | 待处理 | 本轮新发现，不阻塞模型诊断 |
| 低优先级 | CONTRACT-NAMING | 澄清候选规划与训练发布的契约边界 | 待处理 | 先解释真实用途，再决定是否兼容重命名 |
| 后续迁移 | VERSION-CONTROL-FORMAL-MIGRATION | 正式迁移可读版本控制体系 | 进行中（M1a 本地迁移核心已完成，M1b history-summary 进行中） | 核心基础设施已完成；范围、训练机操作、legacy 退役、merge/push 均需另行授权 |

MODEL-QUALITY 是总目标，不重复开实验，也不要求先通过最终独立验收才允许训练最终候选。新发现改变依赖时，同步本表和条目并说明原因。

## 待处理与阻塞事项

### MODEL-ARCHIVE — 中间模型证据归档与权重清理准备

- **状态/来源**：进行中（主 Agent）；用户要求验证能否保留历次训练参数和结果后清除训练机 run 下模型文件。本轮仅验证，无删除授权。
- **已证实事实与差距**：2026-08-31 训练机 `workspace/runs` 约 90.253 GiB；原清单漏列两组 source-aware，concise-cv 约定路径不存在；r1 来源仍有 5 个 checkpoint，merged 为发布库软链接。5 组未发布模型 merged 权重合计约 80.988 GiB，各 root LoRA 约 439.1 MiB。原清单不足以放行删除；当前快照未哈希权重，未归档原始预测和完整训练日志。
- **依赖**：MODEL-DIAG 对历史/当前模型和阶段 checkpoint 的需求；当前发布模型及 `pipeline/checkpoint_policy.json` 保护边界。权重清理不隐含取消诊断任务。
- **下一动作**：按 MODEL_INVENTORY 第 8 节归档实际配置、模型/数据/Prompt/评测身份、完整日志和原始预测、文件哈希及备份校验；查 concise-cv 备份或迁移位置。逐 run 确定仅留研究记录还是保留 adapter 以便重新合并，形成显式候选清单后取得删除授权。保留 adapter 的方案先验证准确基座与合并链路，不以直挂 4-bit 代替 merged BF16。
- **验收标准**：每模型每 fold 有可核查的原始配置和结果链、缺失证据明确、归档已备份并校验；清理路径不跟随链接误入发布库，不删除在用模型和未完成诊断所需文件；训练机按获准清单执行并记录删除前后体量、保留文件完整性及对应机器提交。完成可行性审查不等于归档或删除完成。
- **证据/版本/验证限制**：[模型清单](MODEL_INVENTORY.md#8-2026-08-31-清理可行性核查)、[训练机快照](results/model-inventory-audit-20260831/remote_snapshot.json)、[模型归档证据包索引](results/model_evidence/README.md)、[试点证据包`v4.1-prompt-minimal-v1-seed3411`](results/model_evidence/v4.1-prompt-minimal-v1-seed3411/README.md)。本地核查基线 `7b8192bd`，远端 `main@f1b7d8a3` 干净，本地独有 3 提交、远端独有 0；本轮 SSH 仅执行 Git 状态、文件 stat/目录/链接与轻量 JSON 读取，不启动 GPU 任务、训练、合并或评测，不读取受限测试语义结果。仅快照及文档落本机，未同步/删除远程文件。独立 reviewer 的原稿 findings 已核对：保护条件缺失 P1、模型清单过期/证据不足/效果结论过度 P2；修订后独立 reviewer 复审通过，无剩余可执行文档问题；10 个清单链接、指标/契约对照与 `git diff --check` 通过。修正归档要求仍不代表已满足删除条件。

### HOLDOUT-BUILD — 构建并授权未使用 holdout 测试集

- **状态/来源**：待处理；由 TEST-POLICY 关闭时拆出，作为 FINAL-TRAIN / MODEL-QUALITY 的前置。目标是构建一个未参与开发/调参的 holdout 测试集，用于最终候选模型的独立验收。
- **事实与差距**：现有唯一 sealed-test `v4.1-sealed-test-5546b8bf1ec3` 已暴露且一次性，不复测不调参；本地与训练机均无未使用 holdout。需要一个新的、未使用的 holdout 测试集及其对应授权链路。
- **数据来源**：定义并人工审查一个独立于开发/调参的 source；沿用 `development_source_isolation_verified`、`test_split_binding_verified` 的隔离要求，纳入前核对 source 边界，避免与现有 sealed-test 或开发验证集混用。
- **人工审查**：对候选样本执行有效视图/剪裁人工审查（对应 `review_*` 流程），核对批次与 source 分层，形成冻结的 review batch 后再生成 release。
- **发布入口**：沿用 sealed-test release 构建流程，生成 release manifest、`sealed_ground_truth`、`quality_report` 等产物，并校验契约、清单、帧哈希与权限，再写入 index/LATEST。
- **授权流程**：预注册一次性授权 + one-time claim，沿用现有 stage_d 流程；授权条件 `one_time`、`tuning_use: forbidden`、`pre_stage_g_outputs: aggregate_pass_fail_and_integrity_only`，首次模型调用前原子写入 claim，只允许同一 run identity 恢复。
- **阈值**：沿用 `stage-d-preparation-5cd1b3fa343c` 已冻结的 7 项阈值（`four_state_macro_recall 0.4006`、`fracture_three_state_macro_recall 0.3`、`joint_correct_rate 0.3921`、`runtime_failure_count 0`、`strict_valid_rate 1.0`、`已断裂_recall 0.15`、`未断裂_recall 0.7`）。
- **依赖/边界**：本任务只负责构建、审查、发布与授权一个未使用 holdout，不隐含“策略已确定即已构建”；完成本项不等同于最终模型已通过该 holdout 验收。不得读取现有 sealed-test 受限语义结果来构造 holdout。
- **验收标准**：新的未使用 holdout release 已构建并经人工审查，source 隔离与 test-split binding 校验通过，manifest/ground-truth/quality_report 与授权 claim 齐备、可追溯；为 FINAL-TRAIN / MODEL-QUALITY 的独立验收提供就绪入口。
- **证据/限制**：产物落位按现有约定记录于 `docs/results/` 对应新目录与 `finetune/results/v4_1_stage_d_*` 式授权/claim/run 目录；本轮仅登记任务，未实际构建 holdout。

### MODEL-DIAG — 诊断并改善三折类别坍缩与契约退化

- **状态/来源**：待处理；原“三折实验出现类别坍缩与契约退化”。目标是在固定证据与评价口径下找到可跨 fold 复现的改进方案。
- **事实与差距**：已同步报告记录 `v4.1-prompt-concise-cv-v1-seed3411` 的 1581 条评测：contract 合法率 79.63%、joint correct 32.07%、`clip_state` 35.80%，322 条非法输出中 311 条缺 `special_case`，“临界未断裂”和“已断裂”召回为 0%。这支持退化症状，不证明 Prompt、采样或早停中的任何一个是单独根因。
- **下一动作**：每个步骤分别交接证据，新发现关联本任务，不悄悄加入当前实验。
  1. 在训练机核对既有 release、checkpoint step、adapter/merged 哈希、Prompt contract、生成参数、评分器代码和逐样本记录；只同步允许公开的开发集轻量摘要。缺产物则记录补同步/补评测任务，不用本机测试代替模型结果。
  2. 从已有开发验证集构建固定、按状态和 source 分层的 canary 清单，确认每个被测模型对应 fold 的训练排除关系；先重算既有记录，再做历史/当前模型与历史/当前 Prompt 的交叉推理对照。
  3. 对保留 checkpoint 做阶段性严格评测，定位字段遗漏和类别偏置开始的 step；保持样本、评分器和生成参数可比较，原始输出与评分结果分开保存。
  4. 根据诊断分别调整 Prompt、采样配额或训练日程，冻结其他因素；单折筛选后扩展到三折。组合修改另列候选，不作为单变量归因证据。
- **入口与产物**：既有报告约定输入和权重路径为训练机 `workspace/runs/v4.1-prompt-concise-cv-v1-seed3411/`，但 2026-08-31 只读检查该路径不存在（见 MODEL-ARCHIVE 快照），需先查备份/迁移位置；依赖这些权重的推理与阶段 checkpoint 评测暂不能执行，已有报告整理仍可推进。[eval_run.py](../finetune/eval_run.py) 读取指定 fold、model-dir 和适用 experiment-contract，向独立 out-dir 写 `run_identity.json`、`evaluation_records.jsonl`、`evaluation_summary.json`。`--max-samples` 只截取样本，不等于分层抽样；先核对/补齐按冻结清单选样的能力，不能假称 CLI 已支持。
- **准备与执行边界**：[脚本索引](../finetune/SCRIPTS.md) 中的 `train_build_dataset.py`、`train_prepare_run.py`、`train_with_contract.py` 分别负责数据包、配置与训练；前两者含固定 fold/seed/3000 行约束。执行者须核对能否表达目标对照，任务单列出实际数据包、配置、checkpoint/merged 生成与评测路径；缺能力先实现，不复用默认值或覆盖旧实验。本条不是已验证可直接运行的全量命令。
- **依赖/边界**：开发集只读整理不等待 HOLDOUT-BUILD；实验执行前明确测试隔离规则、冻结开发侧阈值并核对授权。现有交付配置记录 optimization paused / retraining unauthorized，本次文档维护不代表恢复训练授权。不使用 sealed-test 调参，不补字段伪造合法率，不删除诊断所需 checkpoint。
- **验收标准**：身份链一致、原始预测可追溯，根因分清事实与假设；报告四字段合法率/正确率、各状态召回、macro recall、joint correct、分布和失败样例；单变量结果可比较，三折达到预定开发侧标准后才放行 FINAL-TRAIN。仅完成诊断时记录阶段结果，不宣称效果改进已完成。
- **证据/限制**：[三折报告](results/v4_1_prompt_concise_cv_v1_seed3411/README.md)、[项目状态](CURRENT_PROJECT_STATUS.md)、[交付配置](../delivery/model_component.json)。报告第 10.2 节同时改 Prompt/采样/早停的建议不满足本任务的单变量标准；本轮未复算训练机原始预测。

### RELEASE-POINTER — 安全更新并激活数据 release 指针

- **状态/来源**：待处理；原“release 指针文件更新自动化”。目标是减少人工错配，同时保留可信身份校验和明确激活语义。
- **事实与差距**：当前指针手动维护；运行时校验契约内容哈希和 manifest 文件哈希，原方案仅更新两个字段不完整。
- **下一动作**：设计发布与激活的边界；成功验证后整体原子更新 `release_id`、`release_dir`、`manifest`、`expected_contract_hash`、`expected_manifest_sha256`，记录选中该 release 的依据。构建自己的产物再自算哈希只证明一致性，不冒充独立信任校验。
- **入口与产物**：[release_build_phase2.py](../pipeline/scripts/release_build_phase2.py) 调用发布器生成 release manifest；激活逻辑需新增/补齐，写入 [active_data_release.json](../finetune/active_data_release.json)，再通过 [release_validate.py](../finetune/release_validate.py) 默认钉扎路径验收。
- **依赖**：下一次 release 切换前完成；沿用现有 release 的首轮诊断不受阻。
- **验收标准**：五字段同源一致；预检查和失败构建不动指针，激活失败不留下半写状态，旧指针可追溯恢复；明确不静默激活的规则，覆盖成功、失败、重复执行和身份漂移场景；提交经核对的指针变更。
- **证据/限制**：[运行时](../finetune/v4_1_runtime.py) 的 `_load_active_release_pointer` / `load_release_expectations`；实现未开始，REL-VERIFY 通过不代表本项完成。

### FINAL-TRAIN — 全量开发数据训练最终候选

- **状态/来源**：阻塞；从原“独立测试 release 与 full-data final”拆出，是 MODEL-QUALITY 的前置。
- **事实与差距**：当前发布模型只用 Fold0，`full_data_final: false`；development release 有 1678 条发布候选。候选数不自动等于最终训练行数，训练资格与采样策略仍须冻结。
- **下一动作/解除条件**：MODEL-DIAG 达到开发侧三折标准、HOLDOUT-BUILD 就绪（未使用 holdout 已构建并授权）并取得适用训练授权后，冻结最终数据范围、Prompt、采样、训练日程与模型身份。
- **入口与产物**：先核对现有数据构建/配置入口的 Fold0 限制，准备全量数据包和配置；`finetune/train_with_contract.py` 消费训练 YAML，保存 adapter/checkpoint；再用经核实的合并入口生成 merged 身份，交 MODEL-QUALITY 验收。全量准备与合并命令须在任务单核实，缺失能力作为前置实现，不编造现成脚本。
- **验收标准**：全部合格开发数据按冻结方案纳入，未混入测试来源；真实训练/合并完成，模型与数据/配置/代码/哈希可追溯，保存最终候选及轻量 manifest。完成本项不自动获得 production approval。
- **证据/限制**：[开发 release 摘要](results/v4_1_phase2_development_release/release_summary.json)、[当前模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json)、[训练说明](../finetune/README.md)；本轮无全量最终模型证据。

### MODEL-QUALITY — 最终模型质量验收与晋级

- **状态/来源**：阻塞；原“当前发布模型质量门未通过”，作为总目标，依赖 MODEL-DIAG、RELEASE-POINTER、FINAL-TRAIN、HOLDOUT-BUILD。
- **事实与差距**：`v4.1-agent-pipeline-fold0-r1` 已用于工程链路验证，但 Stage B/D/G 标志均为 false，`production_approved: false`。标志为 false 不等于每一门都已执行失败，须查各门证据。
- **下一动作**：核对适用质量门、阈值和证据要求并落实到子任务；最终候选和测试前置齐备后，按授权协议完成独立验收及其他质量门，再决定晋级。
- **入口与产物**：参照 [发布证据](results/v4_1_agent_pipeline_fold0_r1/README.md) 和 [服务手册](INFERENCE_SERVICE_RUNBOOK.md) 核对执行入口；冻结报告和模型哈希，经注册表发布新身份并同步 delivery，核对服务加载对象。缺可执行入口则先补任务单/实现，不把历史归档命令写成现成流程。
- **验收标准**：预定质量门与身份校验均有证据，模型/报告/注册表/delivery/服务一致；新候选不覆盖旧模型历史结论，工程成功不能替代质量通过。
- **证据/限制**：[交付配置](../delivery/model_component.json)、[模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json) 及现有 sealed-test 公开结果；目前不满足最终交付标准。

### DOC-INDEX — 修正脚本索引的过期缺陷描述

- **状态/来源**：待处理；本轮维护中发现，关联已解决的 PIPE-INDEX。
- **事实与差距**：[pipeline/scripts/SCRIPTS.md](../pipeline/scripts/SCRIPTS.md) 的 `build_artifact_index.py` 行仍称 promote 未传播 source/split 索引，与 `cdb8632c` 实现矛盾。AGENTS.md 本轮已移除同一过期描述，脚本索引尚待同步。
- **下一动作/依赖**：对照 `pipeline/data_rebuild.py` 的 `_update_snapshot_collection_indexes` 更新该行，只核对受影响的覆盖说明；不阻塞模型诊断，不重开已修好的代码问题。
- **验收标准**：脚本索引与实际 promote 行为一致，相关文档不再把该缺陷列为当前待办；记录变更和核对依据。
- **证据/限制**：上述代码和 `cdb8632c`；本轮未修改脚本索引文件。

### CONTRACT-NAMING — 澄清候选规划与训练发布的契约边界

- **状态/来源**：待处理，低优先级；原“V3 命名遗留”。目标是降低理解成本，不改变冻结产物语义。
- **事实与差距**：候选计划 `_validate_contract` 要求 v3，重建入口实际加载 v3；后续 V4.1 审查/发布继续复用候选。因此不是纯历史路径，也不能直接换成 v4.1 契约。
- **下一动作/依赖**：先在模块说明中解释复用边界；仍有必要时再设计不带版本号的模块命名与兼容方案。主链路问题优先。
- **验收标准**：模块说明、imports、SCRIPTS.md 和流程文档一致；若重命名，验证既有调用与历史产物兼容性，不意外改变内容寻址身份。
- **证据/限制**：[候选计划](../pipeline/v3_candidate_plan.py)、[候选物化](../pipeline/v3_candidate_media.py)、[重建入口](../pipeline/scripts/rebuild_data.py)；尚未实施澄清或重命名。

### VERSION-CONTROL-FORMAL-MIGRATION — 正式迁移可读版本控制体系

- **状态/来源**：进行中（M1a 本地迁移核心已完成，M1b history-summary 进行中）；由 VERSION-CONTROL-MIGRATION 核心基础设施完成后拆出。用户授权建立 Task Artifact，Intent 已确认提交 `3dae30a0`，Spec 已确认提交 `6996d35d`，Plan 已确认并提交 `11e54b31`；merge/push 继续单独授权。
- **任务关联**：[Intent](tasks/2026-09-07-readable-version-control-migration/intent.md)、[Spec](tasks/2026-09-07-readable-version-control-migration/spec.md)、[Plan](tasks/2026-09-07-readable-version-control-migration/plan.md)（已确认提交 `11e54b31`）。任务分支为 `refactor/2026-09-07-readable-version-control-migration`，由用户确认重命名原分支并保留历史，承接基线 `1b0d5823`。原 B0–B12 台账中的旧分支名作为历史记录保留。
- **已确认范围**：迁移两个已发布数据版本和当前一版 Prompt `v4.1-concise-evidence-json-v2`；历史模型保留身份、核心训练参数及已有指标，不要求补齐全部历史信息。所有活动入口完成切换，保持单一正式写入者及不可抹去新事实的恢复规则。candidate/production 门禁不变；无合格模型时实际服务入口拒绝启动是允许状态，不要求历史开发模型继续服务。
- **规划发现**：`versioning/data_pipeline.py` 当前从文件名派生 ROI、固定生成两条 clip 记录，尚未承接真实媒体语义；训练 CLI 管理 Run 状态，真实执行器接线仍需完成。Plan 的 M3/M4 明确覆盖这两处差距，不能沿用 B0–B12 测试宣称真实业务已接入。
- **现场证据**：2026-09-07 网络恢复后只读调查成功；当时远端干净 `main@f1b7d8a3`，origin 为 Codeup。两个 release、三个 Prompt registry 目录、八个 run、五个历史归档目录和一个发布模型目录可见；六组 run 有 adapter，两个 concise run 仅见准备资料；concise-cv 预期路径不存在，`/data/mVllm_2` 尚未建立。完整观察及扫描边界见[调查记录](results/version-control-migration-20260907.md)，提交 `821e5953`。未验证权重哈希、加载、数据完整性或历史原始记录完整性，尚未分配新正式身份；无远端写入。
- **已证实事实与差距**：M0 证据已提交并更新，包含 source inventory、object mapping、entrypoint map。训练机 payload 完整 hash 已验证；`/data/mVllm_2` 已由用户准备并只读验证可写。M1a 本地迁移核心已完成：Prompt 迁移 precheck、真实转换、provenance、中断安全已完成；Data 预检、目标冲突、manifest/payload hash、r2 active、r1 superseded/replacement、双对象批转换、幂等、中断恢复、receipt 失配 fail-closed、in-progress source snapshot 均已完成并通过 review。M1b history-summary 已开始：H1 历史 Prompt 条目纯构建已完成并提交 `309f1d83`；H2/H3 非法 history entry fail-closed 已完成并提交 `71598ab9`；H4 源缺失 unknown / 坏源 fail-closed / 身份绑定已完成并提交 `0ee83d8e`；H5 prepare-only run 历史条目已完成并提交 `2bb7b175`。当前本地权威验证 `tests/versioning` 1505 passed（HEAD `2bb7b175`）。history-summary 的真实文件写入、多 entry 批量、run/eval/model 完整条目、CLI 仍未完成。真实训练机迁移写入仍未执行，迁移代码尚未同步到训练机；M3–M8 尚未开始。legacy `pipeline/`、`finetune/` 仍按旧规则运行；未在 Linux 训练机验证跨进程锁，未用真实 adapter/merged、正式数据或移动硬盘做恢复演练。
- **下一动作/依赖**：继续 M1b history-summary（真实文件写入、多 entry 批量、run/eval/model 完整条目、CLI 尚未完成），随后按 M0–M8 分批推进。真实训练机迁移写入、迁移代码同步到训练机、实际对象写入均需人工核对映射与授权；merge/push、停止远端进程、系统权限变更及真实重训练/完整评测不包含在计划的实施授权中。
- **验收标准**：按已确认 Spec 核对两个数据版本及一版 Prompt 的内容保持、历史关联可查询、所有活动入口接管、单写与恢复不丢事实、训练机真实环境证据、文档及独立审查。Codeup 为发布依据，最终交付覆盖相对 Codeup main 的完整差异。
- **证据/限制**：[实施台账](plans/2026-09-01-readable-version-control-implementation.md)、[架构说明](../ARCHITECTURE.md)、[项目指南](project-guide.md)。真实移动硬盘恢复允许单独保持未完成，但不能宣称真实备份可恢复；无合格模型时真实模型加载/推理成功仍记未验证。当前 M1a 本地迁移核心已完成、M1b history-summary 进行中（H1–H5 已提交，真实文件写入/批量/完整条目/CLI 未完成），但真实训练机迁移写入与代码同步未执行，M3–M8 未开始，不得宣称 M1b 或迁移已完成或伪造真实 payload/GPU 验证。

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
- **残余**：脚本索引过期描述独立跟踪 DOC-INDEX，不影响代码缺陷关闭。

### PIPE-STATE — rebuild 首跑状态跳转缺失：已解决

- **结果**：允许 `source_snapshotted` 转入 `waiting_for_roi_review`，无预置 ROI 决策的 review 模式首跑可等待人工标注，复跑幂等。
- **证据**：修复提交 `cdb8632c`；`pipeline/data_rebuild.py`、`tests/test_rebuild_source_only.py`。前序全量测试和 reviewer 记录同 PIPE-INDEX，本轮未复跑。

### ROI-DEFAULT — ROI 标注默认 metadata 路径失效：已解决

- **结果**：`pipeline/scripts/roi_annotation_app.py` 从 source_snapshots 的 LATEST 解析 video_meta.json，支持显式路径/ID/前缀；缺 LATEST 或前缀歧义时 fail-closed。
- **证据**：修复提交 `cdb8632c`、`tests/test_roi_annotation_app.py`；前序全量测试和 reviewer 记录同 PIPE-INDEX。`f6881883` 为历史文档版本，不再标为未提交修复。
- **残余**：Streamlit 显示原始 ValueError traceback 是此前接受的呈现层风险；本轮未重新验收 UI。

## 最近维护记录

- 本轮：刷新 VERSION-CONTROL-FORMAL-MIGRATION 台账到当前真实进度。M1a 本地迁移核心已完成（Prompt 迁移 precheck/真实转换/provenance/中断安全，Data 预检/目标冲突/manifest-payload hash/r2 active/r1 superseded-replacement/双对象批转换/幂等/中断恢复/receipt 失配 fail-closed/in-progress source snapshot 均完成并通过 review）；M1b history-summary 已开始：H1 历史 Prompt 条目纯构建提交 `309f1d83`，H2/H3 非法 history entry fail-closed 提交 `71598ab9`，H4 源缺失 unknown / 坏源 fail-closed / 身份绑定提交 `0ee83d8e`，H5 prepare-only run 历史条目提交 `2bb7b175`；当前本地权威验证 `tests/versioning` 1505 passed，HEAD `2bb7b175`。history-summary 真实文件写入、多 entry 批量、run/eval/model 完整条目、CLI 仍未完成。训练机 payload 完整 hash 已验证，`/data/mVllm_2` 已由用户准备并只读验证可写；真实训练机迁移写入与迁移代码同步仍未执行，M3–M8 尚未开始。本轮仅维护本文件，未连接训练机、未执行真实迁移、未 merge/push。

- 2026-09-04 可读版本控制核心基础设施收尾：关闭 VERSION-CONTROL-MIGRATION，记录 `9965dc1b`、本机 `1399` 项新体系测试与整仓 `2082 passed / 11 skipped`、最终 reviewer R1–R11 闭环和实机验证限制；拆出待确认的 VERSION-CONTROL-FORMAL-MIGRATION。本轮未连接训练机，未 merge、push、迁移或删除 legacy。

- 2026-09-03 Agent 指令双平台修正：依据独立审查修正项目根 AGENTS 的版本身份、legacy 分域、提交归因、作用域和委派表述，并同步 ARCHITECTURE 与 project-guide；Pi 用户级编排增加项目约束传递 Gate。仅做本机文档/配置与静态验证，不连接训练机、不运行真实 Pi 子任务。

- 2026-09-01 数据处理运行手册初始契约化：新增 Document Contract 和文档级 D001，将手册定位与 4.1 版本号解耦，在正文声明 4.1 为当前执行基线并同步 README 导航；接受 reviewer 关于 `review_decisions` resolver 例外的 P2，修正 Contract 后复审通过。仅修改文档，不连接训练机或执行数据处理。

- 2026-08-31 模型清理可行性核查：新增 MODEL-ARCHIVE，修正 MODEL-DIAG 的远端权重路径现状；保留既有 holdout 决策及其他未提交修改。仅只读检查远端，补充清单和本地证据；本轮没有归档全部原始产物或删除权重。下一步在任何清理前先完成证据备份与诊断依赖裁决，原独立测试准备与 MODEL-DIAG 主线不因此取消。

- 本轮：承接 TEST-POLICY 裁决并关闭该任务，记录选定策略与决定依据（新建未使用 holdout、现有 sealed-test 不复测不调参）；新增前置任务 HOLDOUT-BUILD 入“待处理与阻塞事项”并列入执行顺序表；同步更新下一步、FINAL-TRAIN / MODEL-QUALITY / MODEL-DIAG 的依赖表述。本轮仅维护本文件，未连接训练机或重跑实验，不新增日期/时间。
- 2026-08-31：承接前序 Agent 关闭的指针验收和 v3 误报；余下五个原事项按依赖重排，其中独立测试/full-data 拆成两个任务，质量门保留为总目标；新发现 DOC-INDEX，另记 SKILL-FEEDBACK；修正命名、哈希、提交和证据边界。此次仅维护 AGENTS.md 与本文件，提交可用 `git log -- AGENTS.md docs/project-todo.md` 追溯。
- 本轮文档验证：独立 reviewer 结论通过、无可执行问题；31 个本地 Markdown 链接路径有效，13 个任务标识唯一，`git diff --check` 通过。核查仅覆盖文档及引用的本地代码/公开产物，不代表重新验收远端任务或模型质量。
