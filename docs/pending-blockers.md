# 未结事项登记册（pending blockers）

**用途声明**：本文件登记项目中所有「未结事项」——等外部条件的、等用户决策的、已知技术债。它存在的意义是让「这件事还没结」在仓库内有唯一可查位置，而不是只散落在对话记录和仓库外报告里。结项时必须更新状态并附结项证据；新增挂起事项必须当天登记。

**状态词表**：`blocked`（等外部条件）/ `waiting-decision`（等人决定）/ `ready`（条件已满足可开工）/ `closed`（已结，保留记录）。

**维护规则**：任何「搁置」动作必须在同一提交里写入本文件（状态 + 解除条件 + 记录日期）；结项时把状态改 `closed` 并附 commit hash 或仓库外报告路径；已结条目保留，不删除。

## A. 等待外部条件（blocked）

### PB-001 训练机无法访问 Codeup

- status: blocked
- 阻塞/依赖: 训练机所在校园网处于 Srun 强制门户未认证态：出站 `:80` 被劫持并返回逐字节相同的 `302 Server: SrunServer1.0`，`:22`/`:443`/`:9418` 被静默丢弃（超时）；`codeup.aliyun.com` 只有 A 记录、无原生 AAAA（`getent ahostsv6` 只返回 `::ffff:` IPv4-mapped），因此无法改走当时正常的 IPv6 通道。提供方=用户，需在门户完成实名认证。
- 解除条件: 训练机 `nmcli` 输出显示 `IP4-CONNECTIVITY:4 (full)`，且 `nc -zv codeup.aliyun.com 22` 成功（退出码 0）。两条命令的输出原文须留存。
- 前置动作: 用户在 `https://gw.buaa.edu.cn/index_1.html` 完成实名认证（门户 `Location` 已携带该机 MAC `a4:fa:76:08:8a:01` 与 `user_ip=172.19.53.12`），认证完成后由 agent 复跑上述两条命令并保留输出原文。
- 负责人: 用户
- 证据与背景: 仓库内 `docs/project-status.md:20`（仅证明目标机 SSH 地址与身份，不含网络故障事实）；仓库外 `~/pi-workspace/mVllm_2-audit/codeup-unreachable-20261018.md`（**不在 Git 内**，:18、:24–:25、:109、:154、:162 为成因与判据原文）。门户 URL、MAC、丢包与 DNS 现象均仅见于该报告。
- 记录日期: 2026-10-18
- 备注: 认证必须在训练机实际所在网络环境完成；不能把「本机能连 Codeup」当作训练机可用。报告记为 `IP4-CONNECTIVITY:2 (portal)`，与本条解除条件要求的 `4 (full)` 是同一指标的前后态。

### PB-002 `temporal_ids` 全为 -1 的归因（模型是否感知帧序）

- status: blocked
- 阻塞/依赖: 需训练机可用（见 PB-001）与用户 GPU/训练机授权。成因未查明前，无法决定 R2 是「修链路注入时序」还是「改判据绕开时序」。
- 解除条件: 在训练机只读查明并给出书面结论，归因到以下三类之一并附命令与输出原文——(a) 配置未传、(b) plugin 不支持、(c) 需 patch。
- 前置动作: PB-001 解除后开专项任务，先只读复现并 dump 传入 processor 的 `temporal_ids`（不加载权重、不改代码即可完成的先做）。
- 负责人: agent（需用户先授权 GPU/训练机）
- 证据与背景: 仓库内 `docs/project-todo.md:69`（CPU 复验实测 `temporal_ids` 全 `-1`，flat `[-1]×8`，depth `1/8/1`，由 processor 回填）、`docs/project-todo.md:96`（`load_video_frames` 默认 `temporal_fusion=False`，返回 `temporal_ids=None` 交给 processor 回填，逐帧成组）；仓库外 `~/pi-workspace/mVllm_2-audit/frame-awareness-report-20261018.md`（**不在 Git 内**）。
- 记录日期: 2026-10-18
- 备注: 允许临时改动以复现，但查清后必须还原，**不得提交 LlamaFactory 子模块**；结论未定前不得把「模型不具备时序感知」写入 `docs/design-facts.*`。

### PB-003 R2 三折真实训练与评测

- status: blocked
- 阻塞/依赖: PB-001、PB-002、门禁 v2 定稿（PB-004/PB-007/PB-008 合流）、训练预算实测校准四条全部 `closed`，且用户给出 GPU 训练授权。
- 解除条件: 上述四条状态均为 `closed`（各自附结项证据）+ 用户书面 GPU 授权记录。
- 前置动作: 冻结 r2 训练 YAML（仓库内当前不存在），跑首 50 步实测校准预算（现 3 epoch 三折约 5.78 h 为推算值）。
- 负责人: 用户 + agent
- 证据与背景: `docs/project-todo.md:40`（台账顺序表 R2-REALTRAIN 行）、`docs/project-todo.md:57`（R2-REALTRAIN 章节）、`docs/project-todo.md:83`（R2 前置四项）。
- 记录日期: 2026-10-18
- 备注: 预算为推算值；本轮口径与 R1 不可比，见 PB-009。前置未完成就开训，评测结论将无法与 R1 同口径比较。

## B. 等待决策（waiting-decision）

### PB-004 门禁门槛 k 值（漏检 vs 误报代价比）

- status: waiting-decision
- 阻塞/依赖: 需用户给出 k 的数量级；L1 门槛必须由 k 推导，**不得沿用现有 0.65 / 0.4006**（来源不明）。
- 解除条件: 用户给出 k 的数量级（如 3 / 10 / 50）并指明依据。
- 前置动作: 按 k 推导各 L1 门限，落 `finetune/eval_build_gate_thresholds.py`（该文件目前不存在，`git ls-files` 已确认）并复现三档情景。
- 负责人: 用户
- 证据与背景: `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:513`（U1 k 值取多少）、同文件 `:514`（U2/T1 选型）；`docs/project-todo.md:83`（④ 门槛由 k 推导、不许沿用现有数值）；现行阈值现状 `finetune/holdout_metrics.py:12`–`:19`（`four_state_macro_recall: 0.4006` 在 `:13`），`finetune/eval_run.py:612`（`expected_thresholds` 内 `four_state_macro_recall: 0.65`）。
- 记录日期: 2026-10-18
- 备注: k 未定时所有 L1 门限数值均不可写入实现；改门槛属门禁口径变更，须与指标定义、报告口径同批（见 PB-008）。

### PB-005 T1 判读器选型（用哪个 API 模型、单价、数据出境）

- status: waiting-decision
- 阻塞/依赖: 需用户指定 API 模型与预算口径，并明确数据是否允许出境。
- 解除条件: 用户书面指定模型名、单价口径（含平均 token 数来源），并回答数据出境是否允许。
- 前置动作: 实现 judge 客户端骨架，用 18 条 golden 跑双判读 κ 与人工一致率校准（判据：Cohen's κ ≥ 0.6、与人工一致率 ≥ 0.85）。
- 负责人: 用户
- 证据与背景: `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:514`（U2 用哪个 API 模型）、`:521`（U9 单价与平均 token 数，待取供应商公开价）、`:224`–`:228`（双判读一致性、与人工一致率、偏置统计、版本冻结）、`:14`（待用户裁决清单）；`docs/project-todo.md:84`（用户已裁决 T 判读器走 API 调用，本地只能跑 89B 级模型）。
- 记录日期: 2026-10-18
- 备注: 模型、Prompt 版本、`temperature=0` 三项须同时冻结并写入 `judge_id`，任一变化即新判读器、须重做一致率检验。

### PB-006 判例集（100–150 条人工标注）

- status: waiting-decision
- 阻塞/依赖: 人工标注未完成；这是 T1 校准与抽取规则的前提。
- 解除条件: 标注集入库且条数落在 100–150，每条形如「原文 / 人工判定等级 / 等价表述」，入库路径固定。
- 前置动作: 按已定抽取口径产出候选 200 条，人工标注后裁剪到 100–150。
- 负责人: 用户主导、agent 辅助整理
- 证据与背景: `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:491`（判例库登记路径 `finetune/validation/cases/judge_cases.jsonl`，标为「新增 / 阶段一产出」）；`docs/project-todo.md:83`（③ T1 须完成校准）。
- 记录日期: 2026-10-18
- 备注: 本登记册沿用请求中的 `golden/cases.jsonl` 说法，而仓库内设计稿写作 `finetune/validation/cases/judge_cases.jsonl`——**两处命名不一致，以实施定稿为准**；落库时须先统一并回写本条。

### PB-007 「机制」「位置」两字段的判分口径

- status: waiting-decision
- 阻塞/依赖: 需用户明确边界——自由描述还是固定词表，语义等价如何判定（M2 判定标准）。
- 解除条件: 用户给出字段取值空间（词表 or 自由文本）与语义等价的判定规则，并明确 M2/M3 计分方式。
- 前置动作: 把口径写进判据表，补对应规则与测试样例。
- 负责人: 用户
- 证据与背景: `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:189`（S7c 机制/位置判分，标为「位置与机制的表述空间大，规则覆盖不全」）、`:212`（`reason_code` 枚举含「机制错 / 表述歧义」）、`:518`（U6 M3 权重 w）、`:525`（U13 evidence 通道是否纳入常规诊断）；`docs/project-todo.md:84`（M3 不计入严格正确但必须单列报告）。
- 记录日期: 2026-10-18
- 备注: 口径定稿前不要动 Prompt 与判分实现；改口径即改门禁，须与 PB-004/PB-008 同批。

### PB-008 两轴指标是否接入门禁

- status: waiting-decision
- 阻塞/依赖: 暂缓，等 PB-004（k 定稿）。
- 解除条件: k 定稿后**同批**修改三项——指标定义、门槛、报告口径，三项缺一不得单独合入。
- 前置动作: 按 k 推导轴 1 / 轴 2 门槛，复算 R1 旧口径两值做对照。
- 负责人: 双方
- 证据与背景: `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:311`–`:338`（§6.5 两轴定义与成对报告要求）、`:364`（旧口径点估计 84/177=0.474576、66/129=0.511628，标注「待验证」）；`docs/project-todo.md:83`（指标定义、门槛、口径必须同批改）。
- 记录日期: 2026-10-18
- 备注: 时序定位准确率条件于预测侧，单独引用无效，必须与断裂检出率成对报告；`:364` 两值在 PB-014 抽看完成前按「标注待验证」使用。

### PB-009 R1↔R2 可比性登记方式

- status: waiting-decision
- 阻塞/依赖: 改 Prompt 即升 `prompt-v4.1-r3`，与 R1、与本次 0/33 基线均不可比，需用户确认登记口径。
- 解除条件: 用户确认三件事——在哪登记（台账 / 报告）、如何表述（是否显式建「不同口径」对照行）、旧数字是否标「不可直接比较」。
- 前置动作: 按裁决改台账口径说明与报告模板（不删旧数字、不做静默换算）。
- 负责人: 用户
- 证据与背景: `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:517`（U5 R1 与 R2 可比性如何登记）、`:16`、`:36`（新口径数字来源与「仓库内尚无对应结果文件」）、`:505`–`:507`（§10.3 旧口径数字处理：补写四项元数据、禁止用换算系数折算）；`docs/project-todo.md:82`（新口径 425 条结果尚未入库）。
- 记录日期: 2026-10-18
- 备注: 禁止用换算系数把旧数字折算成新口径——换算依赖对分布形状的假设，假设无从验证。

### PB-010 Prompt 判据重写并升版本到 `prompt-v4.1-r3`

- status: waiting-decision
- 阻塞/依赖: 判据已存在于契约，但存在「否定命题不可证」问题（要求模型证明片段内未发生变化的空隙），需先定口径再重写。
- 解除条件: PB-007 定稿 + 重写方案评审通过 + 口径登记方式确定（见 PB-009）。
- 前置动作: 起草重写后的 `analysis.user_prompt`（含「先描述首帧状态 → 再看末帧 → 再定档」的显式首帧锚点），走评审后升版本。
- 负责人: 双方
- 证据与背景: `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:110`（§3.2 判据已编码在契约，U4 已查证关闭）；契约 `pipeline/contracts/tensile_vlm_v4_1.json:168`（`analysis.user_prompt` 现有首帧锚点文字，见 DF-002）；`docs/project-todo.md:83`（① 按权威语义重写 Prompt 并补首帧锚点）。
- 记录日期: 2026-10-18
- 备注: 「否定命题不可证」的论证目前**仅见仓库外材料与本轮对话（均不在 Git 内），仓库内暂无锚点，待补写进本节证据**；改 Prompt 必须同步升版本并同步 `docs/design-facts.*`。DF-002 记载的是现行 r2 正文已含首帧锚点文字，与「补显式三段式锚点」不矛盾，但重写时须避免与 DF-002 表述冲突。

## C. 技术债（按依赖标 blocked 或 ready）

### PB-011 过期设计残留（模型输出帧区间 `fracture_between`）

- status: blocked
- 阻塞/依赖: 需用户裁定 v2 legacy 路径是否继续维护；裁定前不得改。
- 解除条件: 用户裁定「下线」或「保留」——若下线，删除残留后 `contract_hash` 与 `EXPECTED_CONTRACT_HASH` 同步更新，且相关测试同步通过。
- 前置动作: 先产出引用清单（哪些代码/测试/产物仍读 `fracture_between`），再提交裁定请求。
- 负责人: 用户决策、agent 执行
- 证据与背景: `pipeline/contracts/tensile_vlm_v2.json:4`（`model_output_fields` 含 `fracture_between`）、`:12`（字段定义）、`:46`（`user_prompt` 要求给断裂帧区间）；`pipeline/prompt_library.yaml:9`、`:30`；`pipeline/production_contract.py:15`（`EXPECTED_CONTRACT_HASH`）、`:19`（`fracture_between` 列在固定字段清单里）；测试强耦合 `tests/test_production_contract.py:52`、`:295`（两处断言 `contract_hash == EXPECTED_CONTRACT_HASH`）；仓库外 `~/pi-workspace/mVllm_2-audit/obsolete-frame-design-20261018.md`（**不在 Git 内**）。
- 记录日期: 2026-10-18
- 备注: `pipeline/prompt_library.yaml` 与 v2 契约正文被测试强制逐字相等，任何改动都会连带改哈希与冻结测试，不能顺手改。

### PB-012 源数据体检（帧内容与主题无关）

- status: blocked
- 阻塞/依赖: 需读取 1,678 候选的帧画面；本机是否存在对应媒体副本尚未核实，抽检须在能读媒体的机器上执行。
- 解除条件: 对 1,678 候选做帧内容一致性抽检，产出问题样本清单（候选 ID + 帧号 + 问题描述 + 是否影响标注），清单落盘并有路径。
- 前置动作: 先确认媒体可访问性（本机 store 或训练机），再定抽检比例与判据。
- 负责人: agent
- 证据与背景: 仓库外 `~/pi-workspace/mVllm_2-audit/frame-awareness-report-20261018.md`（**不在 Git 内**，:325`–`:349 近似，其中 P3 段落记录模型把首帧描述为试样、把另一帧描述为「锡纸擦不锈钢」）；仓库内仅有 `docs/project-todo.md:50`（1,678 候选 / 85 来源的数据口径）和 `docs/results/training-data-ledger-20261017.md`（分折表），都不含帧内容体检结论。
- 记录日期: 2026-10-18
- 备注: 现象目前只见于**模型自述**（非人工看图），未核实前不得据此否定数据可用性；须人工或直接看帧复核后才算证据。

### PB-013 帧感知实验结论待并入事实库

- status: ready
- 阻塞/依赖: 无外部条件；但 `docs/design-facts.*` 属另一 agent 的写入面，本任务不得改动。
- 解除条件: `docs/design-facts.yaml` 的 `misreadings` 段追加一条（误读「每帧独立编码 = 模型知道时序」→ 正确结论），且 `python scripts/verify_design_facts.py` 通过。
- 前置动作: 起草该条 wrong/correct 文案并附 evidence 行号，交给负责事实库的 agent 合入。
- 负责人: agent
- 证据与背景: `docs/design-facts.yaml:154`（`misreadings:` 段现有 4 条，分别起于 `:155`、`:157`、`:160`、`:163`，不含该条）；`docs/project-todo.md:96`（逐帧成组的实现事实）、`docs/project-todo.md:69`（`temporal_ids` 全 `-1` 实测）。
- 记录日期: 2026-10-18
- 备注: 事实库由脚本校验 evidence 行号必须指向真实非空行，行号入册前须复核；该结论与 PB-002 的归因边界相邻——PB-002 未结前，本条只登记「逐帧编码 ≠ 时序感知」，不得写成「模型已知/不知帧序」。

### PB-014 人工抽看 20 条帧画面

- status: waiting-decision
- 阻塞/依赖: 需用户肉眼判断；20 条样本的 contact sheet 已导出，但在仓库外。
- 解除条件: 用户看完 20 条并给出逐条判断（首帧是否肉眼可见分离），结论落盘。
- 前置动作: 把 contact sheet 路径与逐条编号清单发给用户，逐条记录判断。
- 负责人: 用户
- 证据与背景: `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:160`（V1 抽看 10–30 条首帧）、`:523`（U11 33 条「已断裂」标注语义待抽看）、`:364`（33 条标注在抽看前按「标注待验证」使用）；仓库外 `~/pi-workspace/mVllm_2-audit/manual-frames-20261018/`（**不在 Git 内**，20 个样本目录各含一张 `contact_sheet.png`，无顶层汇总图）+ `~/pi-workspace/mVllm_2-audit/manual-frame-review-20261018.md`（**不在 Git 内**，逐条清单与判断顺序说明）。
- 记录日期: 2026-10-18
- 备注: 抽看结果直接决定轴 2 判定前提，未完成前不得把轴 2 数值当结论。

## D. 已确认结论（供对照，避免重复调研）

本节为已定论结论，登记目的是避免重复调研；引用时按下面给出的 `DF-xxx` 或 `文件:行` 标注。

1. 换管线（64 → 512 token）不是「已断裂」零召回的原因：同模型、同数据、同 Prompt，两侧均 0/33。出处：`docs/design-facts.yaml` DF-009、`docs/project-todo.md:82`。
2. `strict_valid_rate` 只校验形式，不校验语义。出处：`docs/design-facts.yaml` DF-003、`finetune/eval_semantics.py:101`。
3. 父子窗口状态不同是设计使然，不是数据矛盾——**此条正在核实中，若核实否证须同时更新本节与 `docs/design-facts.yaml:154` 的 misreadings 首条**。出处：`docs/design-facts.yaml:154`（首条正文在 `:155`–`:156`）。
4. 模型输出「已断裂」在 425 条预测中出现 0 次。出处：`docs/project-todo.md:82`、`docs/plans/2026-10-18-evaluation-pipeline-redesign.md:362`（预测分布无「已断裂」键）。
5. 训练池「已断裂」占 15.00%，非数据稀缺。出处：`docs/design-facts.yaml` DF-010、`docs/plans/2026-10-18-evaluation-pipeline-redesign.md:83`（1253 条候选 188 条 = 15.00%，每 epoch 3000 行 564 行 = 18.80%）、`finetune/train_build_source_aware_dataset.py:30`（`SIGNATURE_COUNT_CAP = 3`，支撑「重复倍率 3.0 已顶上限」）。
