<!-- DOCUMENT-CONTRACT
Purpose: 描述 mVllm_2 仓库当前真实系统组成与边界，作为仓库架构导航与可读版本控制新体系逐步落地的扩展骨架。
Scope: 系统边界与双机角色、现役 legacy 链路指向、在建新体系职责划分与当前实现范围、未迁移 legacy 边界、文档导航；不展开运行细节。
Must Preserve:
- 只描述当前真实状态；在建目标一律标注"在建"，禁止把目标设计写成已实现。
- 新体系入口 `versioning/` 使用五类可读身份（data/prompt/train/model/eval `v<协议>-r<N>` 族）；哈希 `index.json`/`LATEST`/短哈希前缀仅属 legacy 旧链路。
- 双机边界：训练/推理/正式版本写入在训练机，本机只做开发、轻量验证与文档；本机产物视为从训练机同步的结果。
Non-goals:
- 不重复 README/RUNBOOK 的运行细节、命令与步骤。
- 不承载迁移任务台账或批次计划（见实施台账）。
- 不重述架构决策理由与目标细节（以设计文档为准）。
-->

# mVllm_2 架构

> 状态：骨架级。本文从全局视角描述仓库"现在是什么"，不把目标设计写成已完成；在建内容在对应章节明确标注。权威架构目标见[设计文档](docs/plans/2026-09-01-readable-version-control-design.md)，批次实施进度见[实施台账](docs/plans/2026-09-01-readable-version-control-implementation.md)。

## 1. 文档导航

- [README.md](README.md)：仓库概述、当前维护协议与常用流程入口。
- [AGENTS.md](AGENTS.md)：项目 Agent 运行规则，含双机边界、新旧体系分域与提交信息约定。
- [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md)：现役 legacy 数据处理运行手册。
- [finetune/README.md](finetune/README.md)：现役 legacy 训练与测评说明。
- [docs/plans/2026-09-01-readable-version-control-design.md](docs/plans/2026-09-01-readable-version-control-design.md)：可读版本控制架构权威设计（目标）。
- [docs/plans/2026-09-01-readable-version-control-implementation.md](docs/plans/2026-09-01-readable-version-control-implementation.md)：`refactor/readable-version-control` 分支实施台账（批次状态）。
- [docs/project-todo.md](docs/project-todo.md)：项目唯一任务台账与下一步入口。

## 2. 系统边界与双机角色

以下边界沿用 [AGENTS.md](AGENTS.md) 的既有事实，不在本文重复展开。

- **本机（Mac）**：项目开发、代码查看、结果文件检查、静态分析、文档整理、结论汇总与轻量验证。
- **训练机**（SSH `100.70.83.68`，主机 `dell-Precision-3660`）：实际模型训练、GPU 推理、评测跑分、长时间数据处理，以及正式版本写入。
- 本机看到的训练目录、日志、指标、预测文件和报告视为从训练机同步/复制的结果；本机默认不能复现实验，效果结论以训练机真实产物为准。
- 当前电脑缺 checkpoint、LoRA adapter、merged 模型、预测样例或评测指标时，结论标注为"证据不足"，并明确需要补跑或补同步的内容。

## 3. 现役链路（legacy）

- **数据处理**：`pipeline/` 现有入口，双机步骤以 [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md) 为核对基线。
- **训练与测评**：`finetune/` 现有入口，说明见 [finetune/README.md](finetune/README.md)。
- 这些是尚未迁移的 legacy 路径：维持既有规则原样、全程只读保留，不切换、删除、重构或批量改名，直至正式迁移完成。

## 4. 在建新体系（target，在建）

可读版本控制新体系正在 `refactor/readable-version-control` 分支逐步落地，当前均为目标描述：

- **入口（在建）**：顶层包 `versioning/`，统一启动方式 `python -m versioning`。
- **身份（在建）**：五类可读身份 data / prompt / train / model / eval 的 `v<协议>-r<N>` 族完整版本名；新体系不使用哈希 ID、集合 `index.json`、`LATEST` 指针、短哈希前缀解析或隐式当前版本选择。
- **职责划分（在建）**：
  - Git：源码、Prompt、配置、文档、DVC 轻量文件与 MLflow 导出的 manifest；
  - DVC：数据 pipeline 与数据产物；
  - MLflow：训练运行、实际参数、模型、指标、测评与运行状态。
- **已实现能力（B2，身份与状态机）**：
  - **可读身份模块 `versioning/ids.py`**：五类可读身份 data/prompt/train/model/eval 的 `v<协议>-r<N>` 完整版本名解析、校验与构造；严格拒绝 latest、短前缀、后缀与隐式选择，`\Z` 锚定禁止尾随换行等额外字符。
  - **状态机模块 `versioning/state.py`**：`WorkflowState` 六态（prepared/running/partial/failed/completed/archived）合法转换表；`RunStatus` 与 workflow_state 固定组合校验；`RecordValidity`（valid/invalid）不可逆（invalid 不得复活）；`DataStatus` 三态（active/superseded/invalid）与引用语义（仅 active 可建新引用，invalid 禁止一切引用）。
- **已实现能力（B3，数据封存与 holdout 安全）**：
  - **数据 release 生命周期 `versioning/data_release.py`**：数据版本 working→release_staging→sealed 生命周期与 `release.yaml` schema；seal 原子封存并强制不可变（payload 与身份字段只读、移除写权限），非法重用/覆盖/状态逆转 fail-closed；仅受控修改 `status` 与可选 `replacement`；status 语义（`active` 可建新训练/测评引用、`superseded` 仅恢复历史引用、`invalid` 禁止一切新引用）；训练引用门校验 `validate_training_reference`。
  - **holdout 安全 `versioning/holdout.py`**：`purpose: holdout` 数据强制 `training_allowed: false`；`sealed_ground_truth/` 隔离结构；`pre_registration.yaml` 预登记结构；`authorization/claim.yaml` 全局一次性 claim（创建、同身份恢复、一次性消费、fail-closed 拒绝重复消费/覆盖已有 claim/已消费授权重用）。

## 5. 当前实现范围

- **B2 完成（身份与状态机）**：`versioning/ids.py`（五类可读身份解析/校验/生成）与 `versioning/state.py`（workflow_state 状态机）已实现，共 331 例测试。
- **B3 完成（数据封存与 holdout 安全）**：`versioning/data_release.py`（release 生命周期、seal 不可变、status 语义、训练引用门）与 `versioning/holdout.py`（holdout 隔离、pre_registration、一次性 claim）已实现，新增 130 例测试（含 8 个审查修复回归用例）；`tests/versioning/` 共 461 例全绿，全量 `1144 passed / 11 skipped / 0 failed`。
- §4 其余内容（B4 起各批次）仍为在建目标，不作已实现理解。

## 6. 尚未迁移的 legacy 边界

- 已迁移：无。
- 未迁移：哈希数据 ID、集合 `index.json`、`LATEST` 指针、短哈希前缀解析等旧机制仍属 legacy 现役链路，直至正式迁移完成时再处理；新体系不使用。

## 7. 扩展预留

- 本文为后续 batch 增量扩展预留：随各 batch 落地，§4/§5 对应小节由"在建"逐步转为"已实现"，§2 可按需补充物化与服务相关边界。当前不预填未实现的细节或目录。
