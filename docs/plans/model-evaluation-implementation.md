# 模型评测实施计划

本计划承接[已确认评测设计](../model-evaluation.md)，将目标协议映射到当前实现的缺口与验收批次。**本次仅有文档写入授权，不授权代码修改、真实数据处理、训练、推理、评测、SSH 或 test 使用。** 后续代码实施和训练机执行分别取得适用授权。基座来源、完成折登记、多 Agent 盲评隔离及 performance 用途通路均已确认待实现；现场输入、具体执行值及外部数据访问许可未核定，全链不能称为可立即运行。

任务状态、负责人、实际执行版本与证据统一写入[项目 TODO](../project-todo.md)；本文不另设任务台账。下述批次只规定实现顺序、依赖与验收，不能凭计划中的产物名称声称文件已经存在。

## 1. 当前基线与不可破坏的边界

现状证据于 2026-10-15 按本机 `b827f73f` 的实现只读核对；本次从 `ee2b3af2` 续补确认设计，不使用真实模型运行验证现状，也未刷新训练机。用户确认的设计与阈值完整保存于[模型评测设计](../model-evaluation.md)。现行可执行接口见 [versioning/SCRIPTS.md](../../versioning/SCRIPTS.md)，业务入口职责见 [finetune/SCRIPTS.md](../../finetune/SCRIPTS.md)。

| 证据位置 | 当前已实现事实 | 尚缺能力 |
| --- | --- | --- |
| `finetune/eval_run.py` 的 `FORMAL_METRICS`、`_formal_input` 及配置校验 | 正式 validation 冻结模型、Prompt、数据/媒体、生成参数和实现摘要；只接受 `strict-v4.1/all/pooled`，六类阈值指标 | 语义恢复/预测盲评、适用子集 F1、每折状态门、统计证据与新配置 |
| `finetune/holdout_metrics.py` 的 `THRESHOLDS`、`restricted_metrics`、`public_gates` | 原七门固定，真实数值受限，公开仅 gate 0/1 | 新最终门及其独立冻结协议；不能就地改常量重解释旧记录 |
| `finetune/eval_holdout.py`、`versioning/holdout.py` 与 `versioning/holdout_pipeline.py` | 无标签推理与显式受限 score 分离；claim、消费与同身份恢复；test 构建凭证 | raw 冻结后的盲评阶段、安全授权/盲化证明及新协议恢复一致性 |
| `versioning/mlflow_eval.py`、`versioning/manifest.py` | eval 记录、Run 与正式导出 | 新指标、分支/评审审计/统计口径与协议的可验证记录 |
| `versioning/registry.py` 的 `validate_model_for_evaluation`、`_run_eval_gate` | model 数值版本精确匹配、真实 train 证据和正式 passed 门 | 正式 base 来源、新协议证据校验和三类结论绑定 |
| `versioning/registry.py::_run_train_gate` / `_validate_train_execution_artifacts`、`versioning/mlflow_train.py::validate_train_for_promotion` | 登记要求 completed/archived；非 full 要求三折真实证据；single_fold 仅从完成训练选一折 | 只完成一折的 partial train 无法登记；完成折 receipt 不可变快照登记方案已确认待实现，父 train 不改完成状态 |
| `pipeline/v4_1_review_workflow.py`、`versioning/data_pipeline.py` | 人工数据标签审查 | 预测 raw 的默认双 Agent 独立判读和第三 Agent 仲裁；现有数据审查不能替代 |
| `pipeline/output_normalizer.py` | 旧 V2 字段修补逻辑 | 不可直接用于 V4.1 新语义提取，更不能用补字段提升合法率 |
| `pipeline/server_proxy.py`、`pipeline/server_adapter.py`、`pipeline/scripts/serve_smoke.py` | 推理锁、响应身份/帧/digest 与一次 smoke；smoke 默认 timeout 300 秒 | 上传完成至结果显示的 E2E 计时、连续负载、资源统计与性能门；推理锁不证明性能通过 |

所有新正式对象保持五类 `<kind>-v<协议>-r<N>` 完整身份，不新增 kind、哈希身份、集合 index、LATEST 或隐式 fallback。实现协议与业务 V4.1 四字段契约应分别绑定；新旧评测语义必须可辨识，不覆盖旧 eval，不对旧 sealed-test 重评分/重测，不补造通过状态。

## 2. 批次 A：纯语义评分与防作弊约束

对应 TODO：`EVAL-SEMANTICS`；依赖 `EVAL-PROTOCOL` 的已确认文档。获得代码授权后可使用合成数据开展，不依赖受限 test 真值或真实 GPU。

实现范围：建立独立可测试的语义提取与评分原语；严格解析、冻结规则恢复、多 Agent 独立盲评/仲裁结果导入和不可读互斥归类；保留 raw、字段来源及缺失状态。新增模块/配置名及路径在实施前按仓库规范确定，本文不虚构可运行 CLI。评审接口按已确认匿名只读包和低权限 Agent 工作进程隔离设计；本轮不部署、不开放受限数据或连接外部模型。

验收必须覆盖：

- 固定样本清单，失败/空输出/字段缺失不被丢弃；显式 null 与未表达区分；部分字段可计分而 joint 必须四字段明确正确。
- 四状态宏召回不混入 GT 无法判断；GT 可判断的预测拒答计错；GT 无法判断单列并保留在相应全部样本指标中。
- 机制/位置子集只按 GT 非 null 决定；预测状态错误不能移出分母；GT null 误填单列；特殊类别的误报来自完整相关样本。
- 原始严格合法率不被恢复结果覆盖；规则不能补模型没说出的答案；同一响应不能在多个分支重复计数。
- 缺类/支持不足不自动 passed；统计支持数和来源分组；95% group CI 的方法/分组等先冻结，不擅增 CI 或最小 source 硬门。F1 缺类/零预测、宏平均类集合在缺类时的行为、舍入与比较精度、CI 分组/权重等未定细节若实质影响结论，实施前确认，不能写成隐藏默认值。
- 默认两个独立 Agent 按字段一致采用；分歧字段才交第三 Agent，第三者先独立封存判读再看分歧。多于两个初判者时参与者、确切模型版本、提示词、规则、汇总及重试策略提前冻结，不任意多数票或增员凑答案。主 Agent/被测模型不提供意见，已一致字段不反复投票。
- 仅匿名 raw+手册可见，GT/video/model 身份/标签文件名/其他初判均不可见；无法仲裁时用户盲态复核或计无法判读失败。记录逐 Agent 结果、字段来源、一致/分歧/仲裁/人工复核及改判、成本与延迟，先封存 judge 答案再 score。相同模型共错风险必须说明。
- 防作弊测试涵盖按预测筛样本、删失败、根据 GT/video 补答案、把缺失补 null、pooled 掩盖折坍缩、规则事后漂移等反例。

交付为拟新增逻辑产物“评分协议定义、纯评分器、合成反例验证证据”。不输出真实模型效果结论。

## 3. 批次 B：开发评测与正式 baseline

对应 TODO：`EVAL-DEVELOPMENT`；依赖批次 A，服务于 `MODEL-DIAG`。纯接线开发可先做；真实执行依赖明确模型来源、媒体/环境与独立运行授权。

保持现有链路输入来源可追溯：开发发布 data 和 `records/prompts/<prompt>.yaml` → `train prepare/validate/run/export` 冻结输入与真实 adapter → `model register` 登记完整 model 与数值版本 → `eval prepare/validate/run/export` 使用对应完整 validation → 逐折记录、父 Run 和 `records/evaluations/<eval>/manifest.yaml`。新增证据进入哪些文件、字段/schema 与接口兼容策略由本批明确，不能把设计逻辑产物当成现有文件。

需要贯穿改造：评测配置/schema、冻结手册与规则摘要、输入样本/来源分组、raw 与语义记录、MLflow 汇总、逐折/pooled 指标、导出重验与 manifest。配置必须明确选择新协议，旧身份继续使用其原规则；禁止只在显示报告层算新指标而让正式 passed 仍走旧门。

基座登记方案已确认：同一 Registry 和 `model-v<协议>-r<N>`，record/schema 以互斥 base / trained 来源分支核验。base 绑定真实固定来源/上游 revision 与权重、配置、tokenizer/processor 完整摘要，不造 train/训练 data/训练 Prompt；eval 显式绑定 data 与任务 Prompt，和 fine-tuned 同媒体/decode/scorer。trained 继承真实 train Prompt 并准确绑定 base。旧不可变记录不补字段，不靠随意可选 train_id 放宽门禁。未知来源先核查不加载；base 仅开发对照/受控性能，不自动生产。具体可信版本及摘要仍需现场核验。多数类 baseline 仅从开发数据构造。

完成折登记方案已确认：由已 FINISHED 折 execution receipt 形成不可变实际字节快照，绑定 parent train/run、真实 fold、checkpoint step、input/config/data/Prompt/code、base、tokenizer/processor 及权重摘要。诊断 model 只验该折和共享 input 有效，parent 保持 partial，三折全部真实完成才 completed；不改 partial、不虚补折、不借 full。其他折失败不抹去该折成功历史，共享输入漂移或来源 invalid 阻止后续使用且保留历史。初版不接受任意中途 checkpoint；只用于对应折完整开发 validation 和受控性能，不替代 CV/full、不默认服务 alias。

验收要求：

- base 与 fine-tuned 同媒体、Prompt、采样/解码和 scorer；配对提升与绝对过门分别报告，优于 base 不新增为硬门。
- base/trained 来源互斥且逐分支拒绝缺证、来源漂移或伪造引用；完成折登记核验 receipt 与快照实际字节，parent 保持 partial；后续折失败不消除其历史，后续使用仍重验共享 input/来源。缺折不能冒充三折完成。
- 单折必须完整对应 validation；三折完整汇合，分别验证每折 macro recall ≥ 0.65、各状态 recall ≥ 0.50，以及 pooled joint ≥ 0.50、机制 F1 ≥ 0.50、位置 F1 ≥ 0.60。特殊 P/R 完整报告，不增开发硬门。
- export、重新加载记录与 Registry 重验同一协议及原始分母；内容漂移、缺评审证据或所需折证据时 fail-closed。
- 每一链路环节的入口、输入提供者、实际产物、摘要及下一环节消费者在更新后的 SCRIPTS/模型工作流中可追溯。

真实开发执行顺序为 baseline → 对应完整单折诊断 → 完整三折。合成接线通过不关闭 MODEL-DIAG 的真实质量差距。

## 4. 批次 C：新 holdout 协议、权限与一次性恢复

对应 TODO：`EVAL-HOLDOUT`，衔接 `HOLDOUT-BUILD`、`FINAL-TRAIN` 和 `MODEL-QUALITY`；依赖批次 A/B 的冻结协议与正式证据，但权限设计和 test 资格准备可并行。

权限架构已确认：匿名只读评审包只脱敏身份元数据、不改语义，映射和 raw 保持受限；每个 Agent 工作进程独立低权限工作区/身份，仅可读包及写自己结果，不提供 GT/video/训练目录、凭据或自由网络/工具访问。必须验证真实技术隔离，不能把提示词、同一高权限账号 chmod 或同账号多会话当成安全/物理隔离证据。具体平台适配和实际账户尚未部署；若用远端模型，只由受控适配器向批准端点发送获准匿名包，判读 Agent 不获得自由联网工具。本轮不建账户、不连接外部模型、不发 raw。实际供应方、模型版本和受限数据外发许可另核，不推断任意外部发送已获授权。

首次推理前 claim 锁定；保持当前 run 不读真值、score 才读真值以及 score commit 的 consumed 语义。新发包动作增加不可撤销的 prediction exposed 证据，不能发包后恢复未用；补传包或未完成判读只同 identity/内容恢复，不重新推理、改规则或重置 claim，Agent retry 先冻结且不可挑答案。普通 MLflow/public manifest 仍只含 gate+integrity；消费封存后获授权验收负责人可看受限聚合数值且不可调参，开发侧不获逐样本 GT/errors；公开细节另授权，旧 sealed-test 不开放。

目标链路逐环节如下：

| 环节 | 现有输入/入口基础 | 新实现需产生或验证的证据 |
| --- | --- | --- |
| test 资格与构建 | 已获资格的独立 source，经 `data source/roi/subvideo/review_export/review_import/release/release_validate --purpose holdout` | 真实全量人工数据审查、隔离/近重复检查；发布媒体、无标签 manifest、受限真值、构建凭证；新统计协议的支持数证据 |
| 预注册准备与 full | 开发三折过门，test 封存就绪，`train` full 链路 | test 就绪在 FINAL-TRAIN 前完成；可预先冻结的规则/门/角色已准备，候选一次 full，不用 test 选 checkpoint |
| 一次性 claim | full model/eval 身份已出现，`data claim` | 首次调用前精确绑定候选、data/split/executor、新规则与授权；不要求先测试通过才训练 |
| 推理与 raw 冻结 | `eval prepare/validate/run` 从无标签 manifest/媒体与 Registry 权重推理 | 全部请求、失败与 raw 完整冻结，不读真值；冻结完成后不再次调用模型补答案 |
| 语义整理 | 拟新增接口，接收匿名 raw、规则与手册 | 匿名只读包、低权限进程、默认双 Agent 独立字段结果及第三 Agent 先独立后仲裁；judge 先封存，记录 exposed/盲化/恢复证据，具体路径/CLI 未实现 |
| 受限评分 | `eval score` 的现有受限入口 | 检查 raw/语义/规则/模型/授权绑定后才读真值；新最终所有门同时满足；不把评测 Agent/人工恢复正确计为自动性能成功 |
| 导出与恢复 | `eval export`、现有消费凭据及备份机制 | 协议及消费事实随导出/迁移/备份恢复保留；同身份恢复不增加推理、不重置消费、不改规则；公开内容只按精确批准范围 |

新门为：状态 macro recall ≥ 0.70、四类各 recall ≥ 0.60、joint ≥ 0.60、机制 F1 ≥ 0.60、位置 F1 ≥ 0.70，未夹紧与视频异常各自 P/R 均 ≥ 0.60。缺类不得通过，CI 与严格合法率仍独立报告。

验收覆盖仅可读包/写自身结果的越权拒绝、文件/凭据/网络工具隔离、盲化泄露、发包 exposed 不回退、不同规则/模型/数据/评审结果绑定、raw 漂移、非法重试、推理中断、整理中断、评分承诺前后中断、导出中断及备份恢复消费不重置。实现须覆盖已确认 claim/exposed/score commit consumed 的不同状态及公开 gate+integrity 边界；不能沿用“改七门常量”方案偷换原协议。最终真实 test 调用只给一个冻结 full 候选，执行须另获 test 使用授权。

## 5. 批次 D：交互 E2E 与稳定性证据

对应 TODO：`EVAL-PERFORMANCE`。测量工具与开发媒体准备可与前述工作并行，不依赖一次 test 结果；正式模型运行依赖合格加载链与授权，不能用 backend 或替身结果造 passed。

**受控测量通路已确认待实现**：在 eval 领域增加 performance 用途接口（非当前命令），精确绑定 Registry 数值 model、冻结来源/权重、Prompt/generation、开发媒体 allowlist、设备、预算、TTL 和授权会话。base、完成折诊断及 full 可在尚无质量/性能 passed 时进入受控测量；复用 adapter 实际推理代码，临时 loopback 受控端点经受控通道连接 client，不用 candidate/production alias、裸路径或 test。测后仅退出自身进程，不影响已有服务。真实来源不合格或授权会话无效时不加载。

验收须拒绝数值版本/来源/权重/Prompt/generation 漂移、allowlist 外媒体、过期 TTL 或越权会话；性能结果的 export、finalize、manifest 与准入重验用途和同模型配置。performance passed 不能被当作 quality passed；来源核验、可诊断/可测、视觉/性能通过、正式服务批准分层处理，旧门不放宽、不产生循环。具体接口/适配仍待实现，不能补 passed 或借 alias 绕门。

在上传完成端建立 request 起点、完整自动结果显示端建立终点；关联排队、读取、预处理、推理、自动解析、内部 retry 与错误状态。展示与交互编排由独立 TensileAgent 项目负责，本仓库只提供视觉服务；客户端测点与跨仓库写入授权须另核，本次不授权改该项目。当前 server 锁和 smoke timeout 只提供实现参考，不满足这个边界。拟新增逻辑产物为“性能冻结方案、逐请求时间线、资源序列及验收报告”，具体代码接口和路径待实施确定；不另造第六正式身份种类。

执行前冻结单用户单进行中请求串行场景、媒体分层、最大合法规格、缓存/重复/重试、预热、cold start/ready、模型/基座/量化及 generation、资源和预算、timeout。最大视频规格、timeout、具体 base 来源、预算/资源/变体仍有未决值；重大方案先确认。300 秒仅为按时完成门，不自动 kill。

验收要求：正式请求 ≥ 100 且覆盖 ≥ 30 分钟连续处理；至少 95% 合格请求在 300 秒内自动显示完整结果，失败/超时/依赖评测 Agent 判读或人工复核不进按时完成分子；成功耗时 P95 辅报。请求失败率 ≤ 1%，无 OOM/crash/持续资源增长；报告 peak VRAM、各阶段、吞吐与 cold start，和稳态分开。内部及跨批次 retry 不重置同一 request 时间、失败事实或总分母，预热独立。100 次请求可能耗时数小时；同一次运行满足数量和时长即可，不为 30 分钟条件额外重复。报告真实计时覆盖范围，只有 backend 时标明确未验证 display E2E，不外推并发。

性能只使用获准开发媒体，不接触 sealed truth；仅严格或冻结规则解析成功计自动完成。评测 Agent 恢复成本/延迟独立记录，不拼入五分钟模型服务成绩；未来部署纳入 Agent 需另方案。工具测试和替身测量只能验证计数/计时/拒绝逻辑，正式性能证据必须来自训练机真实模型与实际客户端显示链路。

## 6. 批次 E：发布、服务绑定与完整验证

对应 TODO：`EVAL-INTEGRATION`；依赖各适用批次证据，衔接 `MODEL-QUALITY`，不自动关闭其他真实环境任务。

将视觉质量、形式/评测整理依赖及性能三类结论绑定同一模型完整身份、Registry 数值版本、Prompt、数据范围、权重和运行变体。更新 `versioning/registry.py`、eval/manifest/MLflow 重验及服务 resolver/adapter 的相关契约，使新协议准入不能被旧 passed 或无盲评凭据绕过。保持 `model finalize/alias/current` 的 candidate/production 分离和现有批准边界；视觉通过不能自动批准 production。

最终服务准入与批次 D 受控测量资格分离的方案已确认，待实现其用途校验和真实运行适配；本批不得放宽现行服务门，也不得要求已有性能 passed 才能首次受控测量。base/诊断模型不能凭 performance 结果获得正式服务资格。

验收包括：prepare → validate → run → 语义整理 → score/aggregate → export → Registry 准入 → 服务物化的绑定一致；无新协议证据、权重/Prompt/变体漂移或语义整理缺失时拒绝；原协议历史记录仍按其冻结定义解释。备份/隔离恢复保留新证据、受限权限和消费状态，不能借恢复重用 test。更新相关 SCRIPTS、数据/模型流程及本设计的现状说明，并由不同 Agent 对照代码独立核查流程完整性。

实际 GPU、真实 test、客户端 E2E、真实服务与大型产物恢复分别验证并报告限制，任何一项合成检查不得替代真实效果。代码授权不隐含 test、训练或生产批准；必要条件缺失时停止对应环节，保留可独立推进部分。

## 7. 执行前仍需核定

可信基座具体版本与现场摘要、最大合法视频规格、timeout、F1 零预测/缺类与 precision 舍入、group CI 层级/权重、实际评审 Agent 供应方/确切版本及数据访问许可、资源预算等仍待核定。重大统计或执行取舍依适用授权确认；已确认的来源分支、完成折登记、Agent 隔离和受控性能架构不再标为待讨论。不得把设计确认写成账户/接口已部署、权重已验签或受限 raw 已获外发许可。

## 8. 台账关联与完成口径

`EVAL-PROTOCOL` 记录本轮设计/计划文档交付；`EVAL-SEMANTICS`、`EVAL-DEVELOPMENT`、`EVAL-HOLDOUT`、`EVAL-PERFORMANCE`、`EVAL-INTEGRATION` 的实际状态统一由 TODO 维护。MODEL-DIAG 继续承担开发改善，HOLDOUT-BUILD 承担真实 test 数据资格与构建，FINAL-TRAIN 承担独立 full 训练，MODEL-QUALITY 承担最终模型质量与晋级总目标；子任务完成不自动关闭父目标。

后续每批交接须记录实际执行机器/代码、授权范围、变更入口、完整身份、输入来源、实际输出及消费者、验证命令/结果、独立审查（适用时）和残余风险。新接口或产物一经实现，再把本文的逻辑名称替换为实有路径及相应证据；不预先填写成功版本、真实指标或通过状态。
