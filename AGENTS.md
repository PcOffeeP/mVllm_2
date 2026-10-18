<!-- DOCUMENT-CONTRACT
Purpose: 规定所有在 mVllm_2 仓库工作的 Agent 必须遵守的项目级执行、安全、证据与交接约束。
Scope: 双机边界、Git 与授权纪律、新旧体系路由、任务台账维护及权威文档核查；平台专属编排由各 Agent 的用户级配置负责。
Must Preserve:
- GPU、完整评测和长时间数据处理只在训练机执行；证据不足时不得用本机轻量检查冒充真实效果。
- legacy 旧链路与 versioning 新体系必须分域，versioning 仅接受五类完整可读身份并 fail-closed。
- Agent 提交必须准确标明实际执行平台；push、merge 和远程高风险操作必须遵守明确授权边界。
- docs/project-todo.md 是唯一项目任务台账，状态、证据、依赖和交接必须可追溯。
Non-goals:
- 不保存临时分支、HEAD、当前任务状态或实施批次。
- 不展开 SSH、评测指标或其他已有权威文档负责的低频操作细节。
- 不规定 Codex、Pi 或其他平台内部的 subagent 编排实现。
-->

# Project Agent Instructions

关联文档：

- [docs/project-todo.md](docs/project-todo.md)：唯一项目任务台账与下一步入口。
- [docs/project-status.md](docs/project-status.md)：项目现状、双机角色与训练机连接信息。
- [docs/data-workflow.md](docs/data-workflow.md)
- [docs/model-workflow.md](docs/model-workflow.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [README.md](README.md)

## 开工必读顺序

1. `docs/design-facts.md` —— 现行设计事实（**必读**；不看等于从碎片推断）
2. `docs/project-status.md` —— 当前阶段与结论
3. `docs/project-todo.md` —— 任务台账与状态
4. 按任务看具体文档

## 结论优先级与引用规则

- 冲突时优先级：**契约 > 代码 > 文档 > 推断**。
- 文档与代码不一致时：**先报冲突，不得择一执行**。
- 引用任何文档前核其在 `docs/design-facts.yaml` 中的 `state`；`obsolete` 者只能作历史证据，不得作为现行依据。
- 回答"为什么"类问题时，若依据来自 design-facts，须标注 `DF-xxx`；无编号的结论自动降级为「推断」。
- 修改契约 / Prompt / 阈值 / 数据生成逻辑后，**必须同步更新 `docs/design-facts.yaml`**，并跑 `python scripts/verify_design_facts.py`；不通过不得提交。

## 验收与举证规则

### 判据用性质，不用快照数值

- 硬判据只写**性质**，例如「测试收集 0 error」「相对基线只增不减」「链接 0 失效」「标识数不变」；性质型判据不怕漂移。
- 任何具体数值（收集数、文件数、字节数、行数）**必须在写进 brief、清单或报告前现场实测**，并同时写明实测时间与基线 commit。
- 基线快照可以记录，但必须标注「仅作参照，**不作判据**」。
- 若某计数**下降**，必须在报告中逐一解释原因（哪些测试被删除 / 被跳过 / 被重命名），不得静默通过。
- 禁止在 brief 或清单里写「必须等于 <历史数字>」这类要求。历史数字只能作为「不低于基线」或「与基线一致」的比较对象，且该基线必须先现场复核。

### 写进 brief 的路径与行号都是断言

- 任何交给他人（含子 agent）的路径，必须先用 `git ls-files <path>` 或 `test -e <path>` 验证存在，再写进 brief；凭记忆拼路径等同于散布未核实结论。
- 无法在派发前确认的路径，必须显式标注「待验证」，并写明「以实况为准，发现偏差必须报告」。
- 行号一律标注为「近似，需 `grep -n` 自行确认」；不得把记忆中的行号当事实。
- 接收方发现 brief 与实况不符时：**按实况执行 + 在报告中显式记录偏差**（brief 原写什么、实况是什么、凭哪条命令确认）；不得静默照做，也不得静默改口径。

### 举证义务

- 声称「已核实」必须附核实动作（命令 + 输出原文），否则一律视为未核实。
- 引用历史数字必须标来源（文件:行 / commit / 报告路径）与产生日期。
- 同一结论里混用不同口径的数字时，必须分别标注口径（例如「旧管线 425 条」vs「新管线 425 条」），不得并列比较，也不得跨口径加减。

### 测试基线快照（参照用，不作判据）

| 日期 | 基线 | 收集数 | 说明 |
|---|---|---|---|
| 2026-10-18 | `ca46c57e` 干净 HEAD（detached worktree 口径） | 实测 3300，0 error | 仅作参照，不作判据；实际以当次实测为准 |
| 2026-10-18 | 当前工作区 `31b0ab2d` 含 3 个未提交改动 | 实测 3304，0 error | 同上 |

- 复现命令与实测输出（实测时刻 `2026-10-19 01:25:05 +0800`，取自 `git show -s --format=%ci 31b0ab2d`；日期列记的是会话日期，实测跨零点）：

```console
# 口径 A：当前工作区（仓库根目录）
$ .venv/bin/python -m pytest --collect-only -q 2>&1 | tail -3; echo "exit=$?"
tests/versioning/test_state.py::TestDataStatusReferenceSemantics::test_invalid_rejects_historical_restore

3304 tests collected in 1.39s
exit=0

# 口径 B：ca46c57e detached worktree（cwd 为 worktree，用同一 venv 解释器）
$ git worktree add --detach /tmp/wt-ca46c57e ca46c57e
$ cd /tmp/wt-ca46c57e && /Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/.venv/bin/python -m pytest --collect-only -q 2>&1 | tail -3; echo "exit=$?"
tests/versioning/test_state.py::TestDataStatusReferenceSemantics::test_invalid_rejects_historical_restore

3300 tests collected in 4.46s
exit=0
```

- 口径对应：表中第一行 = 口径 B（`ca46c57e` detached worktree，3300）；第二行 = 口径 A（工作区 `31b0ab2d` + 3 个未提交改动，3304）。两次均 `exit=0`，无 collection error。
- 表内只记**净数**：净数不变或上升，可能同时掩盖用例被删除与被重命名；核对改动必须比对 test id 集合，不能只看总数。

## 双机工作机制

- 当前电脑用于项目开发、代码查看、结果文件检查、静态分析、文档整理和结论汇总。
- 实际模型训练、GPU 推理、评测跑分、长时间数据处理，以及任何依赖 4090 显卡的任务，必须在另一台训练电脑上执行。
- 当前电脑上看到的训练目录、日志、指标、预测文件和报告，视为从训练电脑同步或复制过来的结果产物；Agent 可以基于这些产物做效果分析，但不得默认当前电脑能复现实验。
- 当需要判断模型实际效果时，优先使用训练电脑产出的真实评测结果、预测样例、指标文件和日志，而不是仅凭本机可运行的轻量检查。
- 如果当前电脑缺少 checkpoint、LoRA adapter、merged model、预测样例或评测指标，应将结论标记为“证据不足”，并明确需要在训练电脑上补跑或补同步的内容。
- 不要在当前电脑上启动重训练、GPU 推理或长评测任务；如需这些操作，应生成可在训练电脑执行的命令、任务单或检查清单。

## 双机 Git 提交纪律

- 两台机器是同一项目的独立 Git 工作区。操作或同步前分别检查分支、`HEAD`、`git status` 和两端独有提交，禁止覆盖未提交修改或未经检查强制对齐。
- 每完成一个可独立验证步骤，在实际产出机器完成必要校验并原子化 `git commit`；提交前检查范围、`git diff --check` 和必要测试。跨机步骤分别提交代码/流程与轻量 manifest、哈希或报告，大型及敏感产物不入 Git。
- 默认禁止 `git push` / `git merge`；仅在用户明确授权并确认两端状态、提交内容及目标远端分支后执行，不默认强制推送或合并。

## 提交信息约定

- Agent 创建的提交必须以单独一行准确标明实际执行平台：Codex 使用 `以上commit由codex生成。`，Pi 使用 `以上commit由Pi生成。`；禁止使用其他 Agent 的名称进行归因。
- 禁止修改全局 Git 身份配置（user.name / user.email 等）。

## 训练机操作

- 连接信息、远程项目路径和命令格式以 [docs/project-status.md](docs/project-status.md#已记录的机器与资产位置) 为准；认证只使用本机已有的 OpenSSH 密钥或 SSH agent，不在仓库中保存私钥、口令或其他凭据。
- 需要训练、GPU 推理、完整评测或长时间数据处理时，通过 SSH 在训练机执行；连接前先明确命令、输入、输出位置和预计资源占用。
- 默认只操作远程项目目录及明确指定的训练产物。删除或覆盖远程文件、修改系统配置、安装系统级依赖、停止已有任务等高风险操作，必须先获得用户明确授权。

## 训练结果验收口径

- `train_loss` / `eval_loss` 下降只能证明训练目标收敛，不能单独证明模型任务效果好。
- 按被评模型的冻结契约和 [docs/model-workflow.md](docs/model-workflow.md) 中的严格评测口径验收；不得在不同契约之间混用字段或指标。
- 对 LoRA/merged 模型做结论前，应确认实际加载的模型路径、checkpoint step、adapter 文件、metadata 和评测结果彼此一致。
- 如果训练目录中的 metadata 指向旧实验、缺少 adapter/checkpoint，或评测结果无法对应到当前模型，应优先指出产物链路问题，而不是给出正向效果结论。

## 新旧体系边界

- 新旧边界按入口核定，不按整个包推断。尚未切换的 `pipeline/`、`finetune/` legacy 路径维持既有规则；只有在已确认迁移方案、实施授权及该入口验收范围内才能停止旧写入。已停用入口不得恢复为宽松回退，历史产物及仍被调用的业务函数不得因此批量删除或改名。
- 新体系入口为顶层包 `versioning/`，启动方式为 `python -m versioning`；当前状态及逐入口证据以 [项目TODO](docs/project-todo.md) 为准，设计与基础设施历史见 [可读版本控制实施台账](docs/plans/2026-09-01-readable-version-control-implementation.md)。

## 新体系（versioning）规则

- versioning 入口必须使用 `<kind>-v<协议>-r<N>` 完整版本名，其中 `kind` 仅限 data / prompt / train / model / eval。
- 新体系内禁止哈希版本身份、集合 `index.json`、`LATEST` 指针、短哈希前缀解析以及隐式"当前版本"选择。
- 缺少必要参数或引用不合法时立即停止（fail-closed），不自动回退或猜测。

## 仓库级命名规范

总原则：会"被修改"的东西不带版本号；只"新增不修改"的不可变产物必须带版本号/标识。历史版本一律从 git 历史获取，禁止 `_old`/`_v2`/`_bak` 类后缀。

1. 脚本命名：`<阶段前缀>_<动作>_<对象>.py`，阶段前缀对应项目主流程：
   - `source_`（初始数据划分）、`roi_`（ROI 标注/冻结/物化）、`subvideo_`（子视频生成）、`review_`（人工审查）、`release_`（数据发布）、`train_`（Prompt 准备与训练）、`eval_`（测评）、`serve_`（模型发布与推理）；
   - 动作用词表：build_ / prepare_ / run_ / validate_ / audit_ / freeze_ / materialize_ / monitor_ / smoke_ / route_ / rebuild_ / manage_；
   - 脚本服务哪个契约由代码内加载的契约文件声明，不由文件名声明；
   - 被取代的脚本直接删除（git 历史即归档）；
   - 每个脚本目录配同目录 SCRIPTS.md 索引。
2. 分支命名：`<类型>/<主题>[-<补充>]`，全小写连字符；类型限定：feat/ fix/ refactor/ data/ exp/ docs/ chore/；数据轮次用 `data/<yyyymm>-round<N>`（日期+轮次，不挂协议版本）；main 是唯一长期分支，其余短命合并即删。

## Legacy 不可变产物与索引规则

本节仅适用于 `pipeline/`、`finetune/` 下尚未迁移的现有入口，直至正式迁移完成；不得用于 `versioning/`。

1. 不可变产物 ID（沿用现有格式）：
   - 数据 release：`v<协议版本>-<内容哈希>`（如 v4.1.0-ecb5aeb9657c）
   - 契约：`tensile_vlm_v<版本>.json`
   - Prompt revision：`v<协议>-<描述>-r<N>`
   - 模型 release：`v<协议>-<描述>-fold<N>-r<N>`
   - 实验：`v<协议>-<主题>-v<N>-seed<N>`
2. 不可变产物集合目录必须配 `index.json`（由生成脚本自动维护）；追加索引后原子写入 `LATEST`，记录完整产物 ID。解析顺序为 `None（读 LATEST） → 完整 ID → 短哈希前缀`；失败时提示“先运行生成步骤或显式传入产物 ID”。`build_artifact_index.py` 从各集合索引生成全局总览。同一集合仅允许一个写入进程，避免并发覆盖；LATEST 表示最近一次物化或复用触碰的产物。`review_decisions` 目录层级为 queue_id/workspace-hash/batch，索引可解析，但 resolver 不能按 ID 直接解析路径，调用方不得假定支持。具体覆盖范围以实现为准，已修复缺陷与待办状态统一记录在 TODO，避免在本文件重复维护。

## TODO 执行与维护

本节规定项目内的持续维护规则；具体任务、优先级与证据只放在 `docs/project-todo.md`。主 Agent 负责汇总和最终更新，执行其他任务的 Agent 同样必须交接状态与新发现，不能把维护留给最初创建文档的 skill。

1. **开始前**：读 TODO 的“下一步”及目标条目，核对相关代码、产物和 Git 修改；保留其他 Agent 的未提交工作。按依赖选择可执行任务，排序变化写明原因；任务标识固定，不因移动、关闭或重开而改号。
2. **条目内容**：每个未关闭任务写明状态、来源/用户目标、已证实事实与差距、依赖、下一动作、验收标准、证据位置和验证限制。状态使用“待处理 / 进行中 / 阻塞 / 待确认 / 已解决 / 已关闭（误报或取消）”；进行中注明执行者，阻塞注明解除条件。建议阈值与假设不得冒充用户决定或既定要求。
3. **迭代发现**：执行中发现与目标相关且有证据的新问题，先合并重复项，否则新建标识并关联发现它的任务；不确定的问题放“待确认”。阻塞当前验收的写成前置，其余排队，不静默扩大当前实现范围。记录新任务不等于获得重训、测试集使用或其他受限操作的授权。
4. **完成与交接**：逐项核对验收标准，记录变更、执行机器/代码版本、验证命令与结果、证据路径、独立审查结论（适用时）和残余风险，再更新状态及下一步。实现完成但缺真实环境证据时保留未关闭状态；误报可凭调查证据关闭，取消须注明用户决定。引用前序 Agent 的验证必须注明来源，不写成本轮复跑。提交版本已知后及时更新；同次提交的记录可用 `git log -- <相关文件>` 追溯，禁止拿问题发现版本冒充修复版本。
5. **同步与裁决**：任务拆分后保留原目标和父子依赖，完成子任务不自动完成上层验收。同步执行顺序表、条目与受影响文档，已关闭项保留简短结论和证据，详细历史查 Git。业务阈值、测试集复用等需要用户决定时提出具体问题；能独立推进的准备工作继续做。审查、提交及跨机操作沿用本文件其他规则，不另建重复流程。

## 文档与审查纪律

1. 权威操作类文档（如 RUNBOOK、部署手册）的新建或整体重写，必须执行两段式：撰写 → 独立核查（由不同 Agent 对照实际代码逐条验证），不得仅凭作者自验入库。
2. 派发任务时必须明确区分已确认的背景事实与验收标准；结构性、完整性要求必须写入验收标准，不得只作为背景说明。
3. 重写/新建流程类文档的验收标准必须包含链路完整性检查：目标流程每个环节的入口脚本与产物在文档中可追溯（无"从天而降"的参数或产物）。
4. 表述规范：在各种文档中或向用户表述时，禁止使用「节点几」这类内部抽象表达（如「节点5」「节点9」）；应直接使用模型训练整个链路中对应的流程名称，例如人工审查、数据发布、模型训练。

<!-- DECISION-LOG
D001 — 仓库级 Instruction 同时服务 Codex 与 Pi，提交尾注按真实执行平台区分。
Why: 固定写成 Codex 会错误归因 Pi 的提交，破坏提交历史的来源审计。

D002 — 新旧版本身份规则在根 Instruction 中显式分域，legacy 细节不得用于 versioning。
Why: 两套入口迁移期间并存，而 versioning 的解析器只接受 `<kind>-v<协议>-r<N>` 完整身份。

D003 — 迁移保护按实际入口和已确认验收边界生效，当前状态由项目TODO负责。
Why: 已确认方案要求逐入口停止旧写入；把整个包永久视作未迁移会与实际停用门冲突，也不能据局部迁移删除仍被调用的业务实现。
-->
