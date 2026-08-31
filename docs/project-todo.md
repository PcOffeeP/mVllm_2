# Project TODO

本文件是项目持续维护的任务台账，记录用户目标、当前差距、执行顺序和验证结果。维护规则见 [AGENTS.md](../AGENTS.md#todo-执行与维护)，不另建平行 TODO。

- 更新日期：2026-08-31。
- 本轮依据：本地基线 `8acaf2cf`、当前源码/已同步公开结果，以及用户确认已完成的前序 Agent 调查记录。前序对本文件的未提交修改已纳入；本轮只整理文档，没有连接训练机或重跑实验。
- 主 Agent 汇总并维护，其他执行 Agent 按 AGENTS.md 交接证据和新发现。任务标识固定，不随排序改变。

## 下一步与执行顺序

**下一项先执行 TEST-POLICY：只读核查已使用的独立测试集和后续验收规则，形成可裁决方案；随后把主要技术工作投入 MODEL-DIAG。** 历史问题 REL-VERIFY、CONTRACT-HASH 已关闭，不再重复安排首跑或契约找回。

1. 核对 sealed-test 公开结果与既有授权/使用记录，写清现有测试集的允许用途、复测条件及是否需要新的未使用测试集；不得读取受限语义结果或重新推理。
2. 需要用户裁决时，提交具体方案及影响；等待期间继续整理 MODEL-DIAG 的开发集证据和训练机任务单，不停住独立准备工作。
3. 先核三折模型身份与原始预测，再做无需重训的推理对照，最后考虑单变量训练。任何新推理/训练开始前，明确机器、输入、输出、资源和既有授权范围。
4. 开发侧三折方案稳定并冻结后，才进入全量最终训练、独立验收和模型晋级。新数据 release 切换前完成 RELEASE-POINTER；沿用现有 release 时它不阻塞首轮诊断。

| 顺序/定位 | 固定标识 | 任务 | 状态 | 依赖或触发条件 |
| --- | --- | --- | --- | --- |
| 先做的前置 | TEST-POLICY | 明确后续独立测试策略 | 待处理 | 已有一次性评测的公开证据 |
| 主要技术工作 | MODEL-DIAG | 诊断并改善三折类别坍缩与契约退化 | 待处理 | 可先只读整理开发证据；执行实验前明确测试隔离边界和授权 |
| 清理前置 | MODEL-ARCHIVE | 中间模型证据归档与权重清理准备 | 进行中（主 Agent） | MODEL-DIAG 权重依赖、完整证据备份、显式删除授权 |
| 发布前配套 | RELEASE-POINTER | 安全更新并激活数据 release 指针 | 待处理 | 下一次数据 release 切换前完成 |
| 后续训练 | FINAL-TRAIN | 全量开发数据训练最终候选 | 阻塞 | 开发侧三折验收通过、TEST-POLICY 策略确定及训练授权 |
| 总体验收 | MODEL-QUALITY | 最终模型质量验收与晋级 | 阻塞 | FINAL-TRAIN 候选、约定的独立验收及其他适用质量门 |
| 文档收尾 | DOC-INDEX | 修正脚本索引的过期缺陷描述 | 待处理 | 本轮新发现，不阻塞模型诊断 |
| 低优先级 | CONTRACT-NAMING | 澄清候选规划与训练发布的契约边界 | 待处理 | 先解释真实用途，再决定是否兼容重命名 |

MODEL-QUALITY 是总目标，不重复开实验，也不要求先通过最终独立验收才允许训练最终候选。新发现改变依赖时，同步本表和条目并说明原因。

## 待处理与阻塞事项

### MODEL-ARCHIVE — 中间模型证据归档与权重清理准备

- **状态/来源**：进行中（主 Agent）；用户要求验证能否保留历次训练参数和结果后清除训练机 run 下模型文件。本轮仅验证，无删除授权。
- **已证实事实与差距**：2026-08-31 训练机 `workspace/runs` 约 90.253 GiB；原清单漏列两组 source-aware，concise-cv 约定路径不存在；r1 来源仍有 5 个 checkpoint，merged 为发布库软链接。5 组未发布模型 merged 权重合计约 80.988 GiB，各 root LoRA 约 439.1 MiB。原清单不足以放行删除；当前快照未哈希权重，未归档原始预测和完整训练日志。
- **依赖**：MODEL-DIAG 对历史/当前模型和阶段 checkpoint 的需求；当前发布模型及 `pipeline/checkpoint_policy.json` 保护边界。权重清理不隐含取消诊断任务。
- **下一动作**：按 MODEL_INVENTORY 第 8 节归档实际配置、模型/数据/Prompt/评测身份、完整日志和原始预测、文件哈希及备份校验；查 concise-cv 备份或迁移位置。逐 run 确定仅留研究记录还是保留 adapter 以便重新合并，形成显式候选清单后取得删除授权。保留 adapter 的方案先验证准确基座与合并链路，不以直挂 4-bit 代替 merged BF16。
- **验收标准**：每模型每 fold 有可核查的原始配置和结果链、缺失证据明确、归档已备份并校验；清理路径不跟随链接误入发布库，不删除在用模型和未完成诊断所需文件；训练机按获准清单执行并记录删除前后体量、保留文件完整性及对应机器提交。完成可行性审查不等于归档或删除完成。
- **证据/版本/验证限制**：[模型清单](MODEL_INVENTORY.md#8-2026-08-31-清理可行性核查)、[训练机快照](results/model-inventory-audit-20260831/remote_snapshot.json)。本地核查基线 `7b8192bd`，远端 `main@f1b7d8a3` 干净，本地独有 3 提交、远端独有 0；本轮 SSH 仅执行 Git 状态、文件 stat/目录/链接与轻量 JSON 读取，不启动 GPU 任务、训练、合并或评测，不读取受限测试语义结果。仅快照及文档落本机，未同步/删除远程文件。独立 reviewer 的原稿 findings 已核对：保护条件缺失 P1、模型清单过期/证据不足/效果结论过度 P2；修订后独立 reviewer 复审通过，无剩余可执行文档问题；10 个清单链接、指标/契约对照与 `git diff --check` 通过。修正归档要求仍不代表已满足删除条件。

### TEST-POLICY — 明确后续独立测试策略

- **状态/来源**：待处理；从原“独立测试 release 与 full-data final”拆出，保留最终模型由未参与调参的独立数据验收的用户目标。
- **事实与差距**：`v4.1-sealed-test-5546b8bf1ec3` 已创建；公开结果记录 `stage-d-run-da566a5644f8` 完成 299 条评测、整体未通过、`sealed_test_exposed: true`，详细语义指标仍受限。缺少的是后续验收策略，不是从零创建已有测试 release；已执行不等于全部标签泄漏，也不能再称为从未使用。
- **下一动作**：核对公开结果、预注册协议及授权/claim 记录，形成现有测试集允许用途、复测条件、是否另备未使用 holdout 的决策稿。需要用户裁决时写明方案及影响，不读取受限预测或标签来帮助选择。
- **依赖/边界**：只读核查可立即开始；新测试集构建、一次性评测或复测须遵循明确授权，不能由本任务推定。
- **验收标准**：记录选定策略、决定依据、适用模型、source 隔离要求、阈值冻结时点、授权条件和最终证据输出位置；若需新测试 release，另建前置任务，列明数据来源、人工审查、发布入口与产物，不把构建隐含在“策略已确定”中。
- **证据/限制**：[公开结果](results/v4_1_stage_d_sealed_test_release/public_gate_summary.json)、[阶段记录](results/v4_1_stage_d_sealed_test_release/README.md)；历史身份、授权和 claim 位于 `finetune/results/v4_1_stage_d_*` 对应目录。这里只引用公开 pass/fail 与完整性信息；训练机当前状态未在本轮核实。

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
- **依赖/边界**：开发集只读整理不等待 TEST-POLICY 裁决；实验执行前明确测试隔离规则、冻结开发侧阈值并核对授权。现有交付配置记录 optimization paused / retraining unauthorized，本次文档维护不代表恢复训练授权。不使用 sealed-test 调参，不补字段伪造合法率，不删除诊断所需 checkpoint。
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
- **下一动作/解除条件**：MODEL-DIAG 达到开发侧三折标准、TEST-POLICY 策略确定并取得适用训练授权后，冻结最终数据范围、Prompt、采样、训练日程与模型身份。
- **入口与产物**：先核对现有数据构建/配置入口的 Fold0 限制，准备全量数据包和配置；`finetune/train_with_contract.py` 消费训练 YAML，保存 adapter/checkpoint；再用经核实的合并入口生成 merged 身份，交 MODEL-QUALITY 验收。全量准备与合并命令须在任务单核实，缺失能力作为前置实现，不编造现成脚本。
- **验收标准**：全部合格开发数据按冻结方案纳入，未混入测试来源；真实训练/合并完成，模型与数据/配置/代码/哈希可追溯，保存最终候选及轻量 manifest。完成本项不自动获得 production approval。
- **证据/限制**：[开发 release 摘要](results/v4_1_phase2_development_release/release_summary.json)、[当前模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json)、[训练说明](../finetune/README.md)；本轮无全量最终模型证据。

### MODEL-QUALITY — 最终模型质量验收与晋级

- **状态/来源**：阻塞；原“当前发布模型质量门未通过”，作为总目标，依赖 MODEL-DIAG、TEST-POLICY、FINAL-TRAIN。
- **事实与差距**：`v4.1-agent-pipeline-fold0-r1` 已用于工程链路验证，但 Stage B/D/G 标志均为 false，`production_approved: false`。标志为 false 不等于每一门都已执行失败，须查各门证据。
- **下一动作**：核对适用质量门、阈值和证据要求并落实到子任务；最终候选和测试前置齐备后，按授权协议完成独立验收及其他质量门，再决定晋级。
- **入口与产物**：参照 [发布证据](results/v4_1_agent_pipeline_fold0_r1/README.md) 和 [服务手册](INFERENCE_SERVICE_RUNBOOK.md) 核对执行入口；冻结报告和模型哈希，经注册表发布新身份并同步 delivery，核对服务加载对象。缺可执行入口则先补任务单/实现，不把历史归档命令写成现成流程。
- **验收标准**：预定质量门与身份校验均有证据，模型/报告/注册表/delivery/服务一致；新候选不覆盖旧模型历史结论，工程成功不能替代质量通过。
- **证据/限制**：[交付配置](../delivery/model_component.json)、[模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json) 及 TEST-POLICY 公开结果；目前不满足最终交付标准。

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

## Skill 改进候选（待确认，不属于当前实现范围）

### SKILL-FEEDBACK — 用实际迭代案例评估 explain-project 的维护能力

- **状态/来源**：待确认；用户要求后续结合经验考虑针对性改进，当前未要求修改 skill。
- **现有规则**：本机 Pi skill 位于 `/Users/pcoffeep/.pi/agent/skills/explain-project/SKILL.md`，模板位于同目录 `references/todo-document.md`。本轮只读核对：它支持初次介绍及后续问答时维护 TODO，但不负责完整任务执行流程；模板“已解决”偏向代码修复，不充分表达误报澄清、远端验收和多 Agent 交接。后续修改前须核对当时版本，不假定其他机器同路径可用。
- **案例/候选调整**：REL-VERIFY 是环境验收，CONTRACT-HASH 是误报关闭，都无需业务代码修复；TEST-POLICY / FINAL-TRAIN 体现任务拆分与排序；DOC-INDEX 体现解决后发现文档残留。候选包括证据来源/机器标记、关闭原因、固定标识与拆分关联、新问题去重和交接。
- **下一动作/边界**：继续积累案例，区分项目流程约束与通用文档能力；用户决定修改时再加载适用的 skill 创建/修改规则，选取有证据的最小改动。不把 4090、封存测试或本项目排序推广为通用要求，不宣称 skill 已有当前执行循环。
- **验收标准（未来获准修改时）**：改进有案例和边界，保留项目介绍与任务执行职责分离，用初次创建、后续更新、误报关闭、执行中新发现等案例验证；当前只记录候选。

## 已解决与已关闭

以下区分前序 Agent 的记录与本轮核查；不统一声称所有事项都经过本轮全量测试或远端复验。前两项由用户确认完成，本轮保留关闭状态。

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

- 2026-08-31 模型清理可行性核查：新增 MODEL-ARCHIVE，修正 MODEL-DIAG 的远端权重路径现状；保留既有 holdout 决策及其他未提交修改。仅只读检查远端，补充清单和本地证据；本轮没有归档全部原始产物或删除权重。下一步在任何清理前先完成证据备份与诊断依赖裁决，原独立测试准备与 MODEL-DIAG 主线不因此取消。

- 2026-08-31：承接前序 Agent 关闭的指针验收和 v3 误报；余下五个原事项按依赖重排，其中独立测试/full-data 拆成两个任务，质量门保留为总目标；新发现 DOC-INDEX，另记 SKILL-FEEDBACK；修正命名、哈希、提交和证据边界。此次仅维护 AGENTS.md 与本文件，提交可用 `git log -- AGENTS.md docs/project-todo.md` 追溯。
- 本轮文档验证：独立 reviewer 结论通过、无可执行问题；31 个本地 Markdown 链接路径有效，13 个任务标识唯一，`git diff --check` 通过。核查仅覆盖文档及引用的本地代码/公开产物，不代表重新验收远端任务或模型质量。
