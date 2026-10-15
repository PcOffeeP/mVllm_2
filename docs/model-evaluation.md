# 模型评测设计

本文保存已确认的评测设计，覆盖开发诊断、最终独立验收及交互性能。它是目标协议，**不表示实现或真实评测已完成，也不是可直接执行的新操作手册**。现行命令及原协议见[模型工作流](model-workflow.md)与 [versioning 参数索引](../versioning/SCRIPTS.md)；实现差距及验收批次见[实施计划](plans/model-evaluation-implementation.md)，任务状态只由[项目 TODO](project-todo.md)维护。

## 1. 目标与结论边界

模型只根据当前视频窗口内实际采样的视觉证据，输出 V4.1 四字段：`clip_state`、`fracture_mechanism`、`fracture_site`、`special_case`。枚举、null 约束和字段关系以[业务契约](../pipeline/contracts/tensile_vlm_v4_1.json)为准。本次不扩展到断裂时刻定位、片段外事件推断或应力应变预测，不改变业务契约。

评测分别形成三类结论：

- 视觉语义能力：四字段表达是否正确，是否达到开发或最终质量门。
- 输出形式与评测整理依赖：原始严格 JSON/schema 合法率、规则恢复率、Agent 判读及人工复核比例、一致性和恢复成本。
- 交互性能与服务稳定性：用户端自动完整结果的时限、失败率及资源表现。

严格格式失败不直接判定视觉能力失败；评测 Agent 恢复或人工复核的语义正确也不能当作被测模型自动服务成功。训练 loss 收敛、相对 base 改善、开发通过、最终视觉质量通过及生产批准分别记录，不相互替代。

## 2. 所有样本计分与语义整理

固定评测清单是总分母。运行失败、超时、空输出、字段缺失和不可读输出均保留，不删除困难样本；相应未表达字段不得分。推理未完整完成时保留失败事实，不能伪造正式完成记录。原始响应与运行结果冻结后，语义整理不再次调用模型，不重写 raw，不以修复后的 JSON 冒充原始严格合法输出。

每条响应依以下顺序进入唯一处理分支，前一分支已完成处理的响应不重复进入后一分支：

1. **严格解析**：原始响应严格满足 JSON/schema 时，直接提取四字段。
2. **冻结规则恢复**：严格解析失败时，用开发阶段预先冻结的确定性规则，恢复原文明示的字段。规则、词表、歧义处理与实现摘要均冻结；不能在看到 test 结果后追加规则或改阈值。
3. **多 Agent 独立盲评**：默认两个 Agent 独立提取原文明示字段，按字段一致采用；仅分歧字段交第三个 Agent。第三个先独立判读并封存答案，再查看分歧作仲裁。可配置三个或更多参与者，但参与者、确切模型版本、提示词、规则、汇总方式及失败/重试策略必须评测前冻结；不默认任意多数票，也不不断增加 Agent 凑答案。
4. **不可读或盲态复核**：仲裁仍未解决时，用户可在盲态复核，或将相应字段记为无法判读并计失败；复核也不看 GT 或视频。

各 Agent 独立初判时只见匿名 raw 与冻结手册，不见 GT、视频、被测模型身份、标签文件名或其他 Agent 的答案；第三 Agent 封存自身初判后才可查看分歧内容作仲裁，GT/视频/模型身份始终不可见。主 Agent 和被测模型不提供答案意见。失败、缺失或矛盾不能变成正确，已一致字段不反复投票。已冻结 raw 可同步并行判读，但 judge 答案须先封存，再进入 score，不能见到分数后改判。相同模型可能共同犯错；进程或会话独立不等于错误独立，不能声称多 Agent 一致就保证测量正确。

部分字段明确时可获得该字段分数，但 joint 必须四字段均明确且正确。字段缺失不等于显式 null；不能因为预测“未断裂”就替模型补齐其余三个 null。语义提取只整理模型已表达的答案，不根据真值、视频或业务常识替它作答。

报告总样本数、互斥分支数量/比例、逐字段可读率、逐 Agent 原始结果及字段来源、一致率、分歧率、仲裁率、人工复核比例与改判，以及恢复成本和延迟；统计具体算法在执行前冻结，尚无已确认硬门。原始严格 JSON/schema 合法率始终独立报告，不能用语义整理后合法率替换。Agent 判读是评测整理，不属于被测模型自动交互成功，恢复耗时不拼入五分钟模型服务成绩；只有严格解析或冻结规则解析成功才计自动完成。未来若把 Agent 纳入部署，需另行设计和授权。

## 3. 评分口径

| 指标 | 分母与处理 |
| --- | --- |
| 四字段正确率 | 每个字段均以全部评测样本为分母；显式 null 按 GT 是否为 null 判定，缺失/不可读为错 |
| joint correct rate | 四字段全部明确且同时正确的样本数 / 全部样本数；失败不剔除 |
| 四状态 macro recall | 仅对 GT 为未断裂、临界未断裂、发生断裂、已断裂的四类分别计算 recall，再取算术平均；不是加入“无法判断”的五类宏平均 |
| 每状态 recall | 对应 GT 状态的正确预测 / 该 GT 状态总数；GT 可判断而预测无法判断、缺失或运行失败均为错 |
| GT 无法判断 | 单列支持数、预测表现和混淆；仍参与全部样本四字段/joint及适用专项指标，不混入四状态 macro recall |
| 机制、位置 macro F1 | 各自在 GT 该字段非 null 的固定适用子集上计算；按契约相应非 null 类别报告 P/R/F1、支持数和 macro F1。不能按预测状态或预测非 null 筛选；状态判错也保留样本，机制/位置按各自明确答案独立评分；相应字段 null/缺失/非法为错 |
| GT 为 null 时误填 | 机制、位置分别报告 GT null 样本中预测非 null 的数量与比例，独立展示不适用字段的正确性 |
| special_case | 未夹紧、视频异常逐类报告 precision、recall、支持数及误报/漏报；null 正确性仍纳入字段与 joint |

机制或位置的 GT 适用集合由标注决定，不能仅凭预测状态排除“状态判错但机制/位置本应有答案”的样本。GT null 误填必须可追溯；special_case 的逐类 precision 也须包含其他 GT 类别上的误报。

缺类、支持数不足或关键场景未覆盖时，记录“证据不足”，不自动通过，也不为了过门事后重划样本。各类样本量、独立 source 数和更高层试件组数均报告；目前没有已确认的最小 source 数或样本数硬门。CI 采用按独立 source 或更高试件组分组的 95% 区间，避免把同源窗口当成独立证据；具体分组层级、重采样/估计方法等须执行前冻结，未确认 CI 宽度或下界硬门。F1 的缺类/零预测处理、macro 类集合的缺类表现、舍入与比较精度、group CI 的分组和权重等会影响结果，须实施前明确；不能静默选择或据缺类得出通过。

## 4. 数据独立性与固定对照

开发 train/validation 与最终 test 按独立 source 隔离；若多个 source 来自同一试件或存在更高依赖层级，按更高试件组检查隔离。补做近重复排查，报告场景分层与各类支持数。窗口数量不能替代独立来源数量。发现泄漏或资格不足时先处理资格问题，不偷换划分或将历史 test 改名为新 test。

base 与 fine-tuned 对照固定相同媒体、采样帧规则、Prompt、解码参数和 scorer；同一样本配对比较。报告绝对指标是否过门及 paired 提升，两者分开。优于 base 尚不是已确认硬门。多数类 baseline 的构造与参数仅在开发数据确定，不读取 test 真值调参。

默认在开发集比较 base；最终 test 只运行一个冻结的 full 候选，不默认增加 base 的 test 调用。基座登记方案已确认、待实现：沿用 `model-v<协议>-r<N>` 和同一 Registry，以互斥 `base` / `trained` 来源分支分别核验，而非把 `train_id` 随意改为可选来放宽门禁。

base 绑定真实固定来源/上游 revision，以及权重、配置、tokenizer/processor 的完整内容摘要；不伪造 train、训练 data 或训练 Prompt。base eval 显式绑定评测 data 和任务 Prompt，与 fine-tuned 使用同 Prompt、媒体、decode 和 scorer。trained 分支继续继承真实 train 的 Prompt 并准确绑定其 base。来源不明先核查，不加载。新 record/schema 明确区分来源，旧不可变对象不补字段；base 仅用于开发对照和受控性能测量，不自动取得生产资格。

仍只使用 data / prompt / train / model / eval 五类完整身份，不增加第六 kind、集合 index、LATEST 或隐式当前版本。具体可信基座版本和现场摘要尚未核验，来源架构确认不等于权重已具备加载资格。

## 5. 开发与最终质量门

以下数值是已确认的新协议目标，尚未接入现行严格评分器。所有适用门同时满足才能通过；缺类或证据不足不能据其他门达标而通过。

| 指标 | 开发门 | 最终独立 test 门 |
| --- | --- | --- |
| 四状态 macro recall | ≥ 0.65，且每折都达到 | ≥ 0.70 |
| 每个状态 recall | ≥ 0.50，且每折四类都达到 | ≥ 0.60 |
| joint correct rate | 三折 pooled ≥ 0.50 | ≥ 0.60 |
| 机制 macro F1 | 三折 pooled ≥ 0.50 | ≥ 0.60 |
| 位置 macro F1 | 三折 pooled ≥ 0.60 | ≥ 0.70 |
| 未夹紧、视频异常逐类 P/R | 完整报告，无开发硬门 | 每一类 precision 和 recall 均 ≥ 0.60 |

单折诊断用于定位问题，不能代替完整三折。三折 pooled 由完整逐样本记录合并计算，不能简单平均三个 F1；状态门另检查每折，防止 pooled 掩盖某折坍缩。严格合法率、分支比例、评测整理依赖、CI 与相对 baseline 提升独立报告，不擅自增加新硬门。

“先单折诊断”的完成折登记方案已确认、待实现：复用已 FINISHED 折的 execution receipt，形成实际字节的不可变快照；绑定 parent train/run、真实 fold 号、checkpoint step、input/config/data/Prompt/code、base、tokenizer/processor 和权重摘要。诊断 model 登记只核验该完成折及共享 input 有效，父 train 保持 partial；三折真实全完成后才记 completed。其他折失败不抹去该折已成功的历史证据；共享输入漂移或来源 invalid 阻止后续使用，但不删除历史。

初版只接受完成折，不接受任意训练中 checkpoint，不补其他折、不借 full 绕门。诊断模型只用于对应折完整开发 validation 与受控性能测量，不替代完整三折或 full，也不默认设置服务 alias。当前代码仍要求完整训练，以上不是现成登记能力。

## 6. 从开发到最终验收

| 顺序 | 输入及前置 | 目标动作与输出 |
| --- | --- | --- |
| 资格与规则冻结 | 开发 data、契约、候选来源、依赖/预算；独立来源和近重复检查 | 冻结评分规则、盲评手册、对照条件及开发阈值；拟新增逻辑产物“新协议冻结记录” |
| baseline 与单折诊断 | 有正式身份的 base、开发多数类 baseline；对应 single_fold 训练模型与完整 validation | 同媒体对照，保留 raw、失败与完整诊断；不抽掉困难样本 |
| 完整三折 | 已冻结开发方案及三折模型/完整 validation | 每折状态门与 pooled 门同时检查，形成开发结论 |
| test 构建就绪 | 未使用 test 资格、独立来源、完整人工数据审查和封存 | 发布无标签推理输入、受限真值及构建证据；完成可预先确定的预注册准备 |
| 独立 full 训练 | 开发三折达到门槛、test 构建/冻结及预注册准备就绪、适用训练授权 | 开发全集去重，每候选一次独立训练；不以 test 选 checkpoint 或日程 |
| 一次性绑定 | full 候选 model/eval 身份已确定，获 test 使用授权 | 首次模型调用前，claim 精确绑定 model/eval/data/split/executor/规则；不要求先 test 通过才训 full |
| 一次推理与 raw 冻结 | 无标签媒体输入、已核验权重与冻结调用规则 | 一次媒体推理、保留失败；冻结原始响应与运行证据 |
| 盲评语义整理 | 匿名 raw、冻结规则与手册、获授权评审 | 拟新增逻辑产物“预测语义整理与盲评审计证据”；不看 GT/video/model |
| 受限 score 与报告 | 已冻结 raw/语义记录、受限真值、同一授权绑定 | 按新协议受限评分，保留授权消费、实际指标、公开许可范围内报告及导出证据 |
| 发布与服务 | 精确绑定的质量、形式/评测整理依赖、性能证据及相应批准 | 保留 candidate / production 区别；视觉过门不自动证明服务或生产合格 |

表中是目标流程；拟新增逻辑产物尚未分配文件路径或 CLI。既有链路可追溯关系见下一节。test 数据准备可与开发工作并行，性能准备也不依赖一次 test 结果。最终 claim 在候选出现后建立；test 资格及数据构建就绪在 FINAL-TRAIN 前完成。

盲评权限架构已确认、待实现：提供身份元数据脱敏但语义不变的匿名只读评审包，映射和原 raw 保持受限。每个 Agent 工作进程使用独立低权限工作区/身份，只能读包、写自身结果，不提供 GT、视频、训练目录、凭据或自由网络/工具访问。须以实际技术隔离验证职责；提示词、同一高权限账号 chmod 或同账号的多个会话，均不能证明安全或物理隔离。具体运行适配及实际账户尚未部署。 原始回答作为待判读数据，不作为 Agent 指令；不向判读 Agent 暴露检索真值或执行任意工具的能力。若采用远端评审模型，只由受控适配器向预先批准的端点发送获准匿名包，实际供应方和数据发送许可未核定前不调用。

首次推理前 claim 锁定。现有实现仅在 score 读真值，并在 score commit 保留 consumed 事实；新协议另在评审包发放时记录预测 exposed，发包后不能退回“未用”。补传包或未完成判读只允许同 identity、同内容恢复，不重推理、不改规则、不重置 claim；Agent retry 预先冻结，不能挑答案。

普通 MLflow/public manifest 继续只保留 gate 和 integrity 证据。消费封存后，获授权验收负责人可查看受限聚合数值，不能据此调参；开发侧不获得逐样本 GT/errors。公开细节另行授权，旧 sealed-test 不开放。本轮不创建账户、连接外部评审模型或发送 raw；实际 Agent 供应方/版本、访问许可及是否允许将受限 raw 发至指定外部平台必须确切核定，不能推断已获任意发送授权。

## 7. 现有实现与目标的界线

| 当前环节 | 已有入口、输入与产物 | 新设计差距 |
| --- | --- | --- |
| 数据与 Prompt | `versioning data` 发布开发 data；`prompt create` 从定义生成 `records/prompts/<prompt>.yaml`；契约来自 `pipeline/contracts/tensile_vlm_v4_1.json` | 新协议来源分组/支持数/近重复证据须核验，不能从窗口数推定 |
| 训练 | `train prepare/validate/run/export`；冻结 data、Prompt、基座、配置/环境；`workspace/runs/<train>/input/` → adapter、执行证据及 `records/training/<train>/manifest.yaml` | 三折/full 编排已存在，真实运行与开发门证据未由本文产生 |
| 模型登记 | `model register` 从真实已完成 train/artifact 登记完整 model 与数值 Registry 版本；single_fold 也要求原训练完成及三折证据 | base 正式来源及先单折诊断的训练/登记适配尚需实现，禁止空 train、partial 冒充完成或虚补折 |
| 开发评测 | `eval prepare/validate/run/export`；`finetune/eval_run.py` 冻结输入于 `workspace/evaluations/<eval>/input/evaluation.yaml`；逐折 `records.jsonl/failures.jsonl/summary.json` → MLflow 父 Run → `records/evaluations/<eval>/manifest.yaml` | 当前 `strict-v4.1/all/pooled` 只有六类阈值指标；没有本设计的恢复/盲评、macro F1、逐折状态门和统计协议 |
| test 数据 | `versioning/holdout_pipeline.py` 的 source/roi/subvideo/review_export/review_import/release/release_validate；`data/releases/<data>/` 的媒体、`evaluation_inputs/manifest.json`、`sealed_ground_truth/`、`build_receipt.json` | 数据标签审查不是预测盲评；真实资格与构建状态见 HOLDOUT-BUILD |
| test 授权与评分 | `data claim` → `eval prepare/validate/run/score/export`；`finetune/eval_holdout.py`、`versioning/holdout.py`；实际评分在 `workspace/evaluations/<eval>/restricted/`，公开二值 gate | `finetune/holdout_metrics.py` 硬编码原七门；新协议、盲评证据、安全/公开接口与恢复绑定未实现 |
| 晋级与服务 | `versioning/registry.py` 校验 train/model 数值版本/正式 eval；`model finalize/alias/current` → `pipeline.server_proxy` → adapter；`pipeline/scripts/serve_smoke.py` 核查响应绑定 | 旧 passed 不代表新协议通过；新三类结论及用途还需全链绑定；受控 performance 通路未实现，smoke 的 300 秒 timeout 不是性能门 |

现有命令的参数和输入来源以[模型工作流](model-workflow.md)、[数据工作流](data-workflow.md)、[脚本索引](../finetune/SCRIPTS.md)为准。新协议需贯穿配置、冻结实现摘要、记录、MLflow、manifest、Registry 准入和服务绑定；不能直接改原七门常量后让旧 identity 含义改变，不给旧测试重评分、重测或补 passed。

## 8. 交互性能与稳定性

测量用户上传完成至完整自动结果显示的端到端耗时，包含排队、读取、预处理、推理和自动解析。本仓库提供视觉服务；交互编排和结果展示由独立 TensileAgent 项目负责，完整 E2E 需核定客户端测点及跨仓库修改授权，本次不授权修改该项目。后端响应耗时独立报告，不能冒充显示端 E2E；评测 Agent 恢复/人工复核成本单列，不计模型服务自动成功。

已确认验收条件：

- 全部合格请求中，至少 95% 在 300 秒内自动完成并显示完整结果。失败、超时及需要 Agent 判读或人工复核的请求都不能计为按时完成；成功请求耗时 P95 仅作辅助，不能用成功子集掩盖失败。
- 初始场景为单用户、单进行中请求串行处理；不外推并发吞吐或多用户能力。
- 正式运行至少 100 次请求，并覆盖至少 30 分钟连续处理；两个条件同时满足，可由同一次运行提供证据。预热单独记录，不混入正式请求。
- 请求失败率 ≤ 1%，无 OOM、进程 crash 或持续资源增长。报告 peak VRAM、分阶段耗时、吞吐和 cold start；cold start 与 ready 后稳态分开。

执行前冻结媒体分层、缓存/重复/重试规则、设备和模型变体、Prompt/解码/自动解析、计时边界及日志关联。内部 retry 属于同一 request 的耗时，不清零或改作新成功请求；跨批次恢复或重试也不能重置原请求计时、失败事实和分母。300 秒是按时完成判据，不自动代表 kill 或请求 timeout；超标样本保留真实结果及超标事实。

最大合法视频规格、请求 timeout、具体 base 来源、资源与运行预算、generation/量化等变体选择仍须执行前冻结；其中重大取舍需用户确认，本文不代填数值。性能集使用开发侧获准媒体，不使用 sealed truth；性能证据绑定实际模型加载路径和变体，没有合格加载路径只能准备方案，不能造 passed。视觉能力过门不自动满足服务性能或 production 批准。

性能进入通路已确认、待实现：在 eval 领域增加 performance 用途的正式接口（不是当前可运行命令），精确绑定 Registry 数值 model、冻结来源/权重、Prompt/generation、开发媒体 allowlist、设备、预算、TTL 和授权会话。可测尚未质量或性能 passed 的 base、诊断完成折或 full；复用 adapter 实际推理代码，通过临时 loopback 受控端点和受控通道连接 client，不使用 candidate/production alias、裸路径或 test。测后仅退出本次自己的进程，不影响已有服务。

performance passed 不等于 quality passed；export、finalize、manifest 与准入均验用途及同模型配置。来源核验 → 可诊断/可测 → 视觉通过/性能通过 → 正式服务批准分层成立，旧服务门不放宽，也不形成“先 passed 才能测、先测才能 passed”的循环。实际接口和运行适配仍待实现；可信 base 版本、最大视频规格、timeout、统计细节、实际评审供应方与数据权限、资源预算等执行值仍须核定，不因此重开已确认架构。
