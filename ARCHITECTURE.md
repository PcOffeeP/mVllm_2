<!-- DOCUMENT-CONTRACT
Purpose: 描述 mVllm_2 仓库当前真实系统组成与边界，作为仓库架构导航与可读版本控制新体系的维护入口。
Scope: 系统边界与双机角色、现役 legacy 链路指向、新体系职责划分与当前实现范围、未迁移 legacy 边界、文档导航；不展开运行细节。
Must Preserve:
- 只描述当前真实状态；区分"核心基础设施已实现"与"正式链路已迁移"，不得混写。
- 新体系入口 `versioning/` 使用五类 `<kind>-v<协议>-r<N>` 完整可读身份，其中 `kind` 为 data/prompt/train/model/eval；哈希 `index.json`/`LATEST`/短哈希前缀仅属 legacy 旧链路。
- 双机边界：训练/推理/正式版本写入在训练机，本机只做开发、轻量验证与文档；本机产物视为从训练机同步的结果。
Non-goals:
- 不重复 README/RUNBOOK 的运行细节、命令与步骤。
- 不承载迁移任务台账或批次计划（见实施台账）。
- 不重述架构决策理由与目标细节（以设计文档为准）。
-->

# mVllm_2 架构

> 状态：核心基础设施已实现，正式链路尚未迁移。本文从全局视角描述仓库"现在是什么"；权威架构目标见[设计文档](docs/plans/2026-09-01-readable-version-control-design.md)，批次实施证据见[实施台账](docs/plans/2026-09-01-readable-version-control-implementation.md)。

## 1. 文档导航

- [README.md](README.md)：仓库概述、当前维护协议与常用流程入口。
- [AGENTS.md](AGENTS.md)：项目 Agent 运行规则，含双机边界、新旧体系分域与提交信息约定。
- [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md)：现役 legacy 数据处理运行手册。
- [finetune/README.md](finetune/README.md)：现役 legacy 训练与测评说明。
- [docs/plans/2026-09-01-readable-version-control-design.md](docs/plans/2026-09-01-readable-version-control-design.md)：可读版本控制架构权威设计（目标）。
- [docs/plans/2026-09-01-readable-version-control-implementation.md](docs/plans/2026-09-01-readable-version-control-implementation.md)：`refactor/readable-version-control` 分支实施台账（批次状态）。
- [docs/project-todo.md](docs/project-todo.md)：项目唯一任务台账与下一步入口。
- [docs/adr/ADR-0001.md](docs/adr/ADR-0001.md)：采用可读版本控制及 Git/DVC/MLflow 职责边界的决策记录。

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

## 4. 新体系（核心基础设施已实现，正式迁移未执行）

可读版本控制核心基础设施已在 `refactor/readable-version-control` 分支实现；以下能力可在本地 fixture 环境使用，但尚未替换 legacy 正式入口：

- **入口**：顶层包 `versioning/`，统一启动方式 `python -m versioning`。
- **身份**：五类 `<kind>-v<协议>-r<N>` 完整版本名，其中 `kind` 为 data / prompt / train / model / eval；新体系不使用哈希 ID、集合 `index.json`、`LATEST` 指针、短哈希前缀解析或隐式当前版本选择。
- **职责划分**：
  - Git：源码、Prompt、配置、文档、DVC 轻量文件与 MLflow 导出的 manifest；
  - DVC：数据 pipeline 与数据产物；
  - MLflow：训练运行、实际参数、模型、指标、测评与运行状态。
  - **显式版本纪律（全体系规则，设计 §9/§11.6）**：面向身份写入与状态晋级的关键操作（如 `create_prompt`、`stage_release`、`run_release`）一律要求显式传入完整版本号，缺省/猜测即 fail-closed 拒绝；`suggest_next_id` 仅为建议函数，供操作者取用后再显式传入，不自动采用。
- **已实现能力（B2，身份与状态机）**：
  - **可读身份模块 `versioning/ids.py`**：五类 `<kind>-v<协议>-r<N>` 完整版本名的解析、校验与构造，其中 `kind` 为 data/prompt/train/model/eval；严格拒绝 latest、短前缀、后缀与隐式选择，`\Z` 锚定禁止尾随换行等额外字符。
  - **状态机模块 `versioning/state.py`**：`WorkflowState` 六态（prepared/running/partial/failed/completed/archived）合法转换表；`RunStatus` 与 workflow_state 固定组合校验；`RecordValidity`（valid/invalid）不可逆（invalid 不得复活）；`DataStatus` 三态（active/superseded/invalid）与引用语义（仅 active 可建新引用，invalid 禁止一切引用）。
- **已实现能力（B3，数据封存与 holdout 安全）**：
  - **数据 release 生命周期 `versioning/data_release.py`**：数据版本 working→release_staging→sealed 生命周期与 `release.yaml` schema；seal 原子封存并强制不可变（payload 与身份字段只读、移除写权限），非法重用/覆盖/状态逆转 fail-closed；仅受控修改 `status` 与可选 `replacement`；status 语义（`active` 可建新训练/测评引用、`superseded` 仅恢复历史引用、`invalid` 禁止一切新引用）；训练引用门校验 `validate_training_reference`。
  - **holdout 安全 `versioning/holdout.py`**：`purpose: holdout` 数据强制 `training_allowed: false`；`sealed_ground_truth/` 隔离结构；预注册原子冻结到 eval staging 的稳定只读路径；`authorization/claim.yaml` 按完整身份、executor 与预注册 SHA-256 建立全局一次性 claim（创建、同身份恢复、一次性消费、fail-closed 拒绝重复消费/覆盖已有 claim/已消费授权重用）。
- **已实现能力（B4，DVC pipeline 七阶段与最小 CLI）**：
  - **根 `dvc.yaml`**：七阶段固定顺序 source→roi→subvideo→review_export→review_import→release→release_validate；相邻阶段经 outs/deps 闭合衔接；`review_import` 消费外部人工审查结果 `data/review_results/<batch>.yaml`（不含于任何阶段产物，关卡显式，审查摘要与所审内容 digest 绑定）；`release` 依赖 `review_import` 产物，审查未回收或结论不通过时 release 及下游不可执行；`release_validate` 只报告不启动训练。`release` 的 outs 为固定路径 `data/release_payload`（可整体重建的普通 out）+ `data/release_pointer.json`（指针，普通 out），**无 `data/releases` out、无 persist**；目标版本经 DVC params 注入——阶段 `cmd` 用 `--version ${release_version}` 并声明 `params: [release_version]`，操作者显式编辑根 `params.yaml`。
  - **数据 pipeline 模块 `versioning/data_pipeline.py`**：七阶段真实最小转换（非占位）；上游内容 digest 沿链贯穿 manifest，使 DVC out-hash 沿链传播；审查关卡 `ReviewGateError` fail-closed；审查结果 YAML 的 `content_sha256`（64 位摘要）与所审内容绑定，release 复核 decisions 绑定摘要与当前内容一致才放行；release 组装 accepted payload 后封存为正式数据版本并写 `release_pointer.json`。
  - **封存目录形态**：正式版本 `data/releases/<version>/` 含 `release.yaml` + `README.md` + `payload/` 子目录；`release.yaml` 与 `README.md` 属 Git 跟踪边界（保持可写、受控更新），`payload/` 在 DVC 仓库内经 `dvc add` 生成 `payload.dvc` 指针纳入管理；payload 封存只读（去写位）。
  - **数据 CLI `versioning/cli.py` + `versioning/__main__.py`**：`python -m versioning data <stage>` 供 dvc.yaml 调用；缺参/非法 stage/阶段失败均非零退出（fail-closed）；`release` 必填显式 `--version`。
  - **release_validate 真实校验**：`release_validate` 真实调用 `assert_payload_sealed` 与 `validate_training_reference` 两项校验，报告先落盘 `data/reports/<version>.validation.json` 再按结果 fail-closed，不硬编码通过。
- **已实现能力（B5，Prompt 版本与冻结）**：
  - **`versioning/prompts.py`**：Prompt 版本注册、不可变性与训练 input 冻结副本——正式 Prompt 单一权威位置 `records/prompts/prompt-v<协议>-r<N>.yaml`（Git 跟踪、不可覆盖）；训练时仅从该位置冻结复制到 `workspace/runs/train-v.../input/prompt.yaml`，不形成第二套正式位置、不扫描历史目录猜测当前 Prompt、单一状态权威；冻结副本与源结构不一致 / 篡改检测 fail-closed。
- **已实现能力（B6，MLflow 训练记录）**：
  - **`versioning/mlflow_train.py`**：train-v 父 Run + fold0/1/2 嵌套子 Run（`mlflow.parentRunId`）的 MLflow 训练记录模型；父 Run 记录共同输入 tags（data_version/prompt_version/git_commit/base_model）与 config params，三折汇总指标写父 Run；`workflow_state`↔原生 RunStatus 固定组合（委托 `versioning.state`）；受控恢复（FAILED/KILLED 子 Run 经原 Run ID 恢复 RUNNING，不新建）；completed 晋级门（全部必需 fold FINISHED + summary_complete）；`record_validity=invalid` 下游拒绝（`validate_train_for_promotion`）；读取 fail-closed（篡改 workflow_state/run_status 组合或 record_validity 值域拒绝）；store 句柄寻址双隔离（`TrainRecordStore` 独立 tracking_uri，不依赖全局 tracking 状态）。
- **已实现能力（B7，MLflow 测评与 manifest 单向导出）**：
  - **`versioning/mlflow_eval.py`**：eval-v 独立父 Run（独立实验，D023）的 MLflow 测评记录模型；显式 `eval_id` 定位；父 Run 记录五引用 tags（model_id / model_version_number / data_version / config / git_commit）与 scope/outcome/summary 等标签；创建时在线精确校验 Registry Model Version、关联 train 与 data release；三种 scope（single_fold / cross_validation / full）fold 绑定校验，cross_validation 严格绑定 fold0/1/2 子 Run；holdout 完成时在结论门内校验冻结预注册与 claim、先原子写入消费证据，再提交可恢复的 MLflow 完成状态；`record_validity=invalid` 下游拒绝；读取 fail-closed；受控恢复保留原 Run ID 不新建。
  - **`versioning/manifest.py`**：data/prompt/train/eval 四段聚合 manifest 与独立 model manifest 的**单向导出**证据文件及发布门；严格校验键集合、值域、跨段血缘，以及模型的 Registry 数值版本、source run、source scope、artifacts 和唯一 deploy target；export 幂等重导或冲突拒绝，且不反向修改源对象。
- **已实现能力（B8，Model Registry、物化与晋级门）**：
  - **`versioning/registry.py`**：唯一 Registered Model `mVllm2` 的两阶段 Model Registry 与晋级门。完成 train 先由 `register_model` 创建无 `eval_id` 的 staging Model Version；登记时在线复验 train、data release 与训练许可，进程内锁 + 文件锁把同 ID 查重/创建及 eval 绑定读改写串行化；eval 创建前按 `model_id` + 数值版本在线精确校验，passed 后由 `finalize_model_evaluation` 单向绑定且不得覆盖。candidate/production 均拒绝未绑定模型及 `deploy_target: null` 的三折模型组；解析 alias 时仍在线复验 train/eval/data、source scope 与唯一部署目标。
  - **`versioning/materialize.py`**：服务物化必须显式给出 `service_mode` 与 alias；完整下载到同文件系统临时目录，核对 Registry 精确数值版本、严格 model manifest、本地元数据和唯一 deploy target 后，才原子切换 `workspace/models/current`。下载失败、manifest 缺失/错配、旧目标损坏、断链或 alias 漂移均保留旧 current 并 fail-closed。
- **已实现能力（B9，离线备份 catalog 与恢复）**：
  - **`versioning/backup.py`**：离线备份 catalog 与恢复。`enumerate_backup_sources`（scope tag 驱动、物化目录为模型备份源、fail-closed）；adapter 模型按白名单仅备份本地身份资料、严格 model manifest 与声明的 adapter，production_bundle 才备份声明的 adapter 与 merged；MLflow store 只保留 SQLite、作用域模型声明的训练 artifact 和已绑定正式 eval artifact，避免从 store 整树夹带 adapter 模型的 merged；`create_backup`（真实复制 + 落盘前全量校验含 SQLite integrity_check + 差异修复 + 原子替换 + prev 快照）；`load_backup_catalog` / `verify_backup` / `restore_backup`（零副作用、目标冲突拒绝、灾难恢复 + manifest 原路径恢复 + 封存权限重放）。
  - **`versioning/data_release.py`**：`seal_payload` 提升为公开 API（保留 `_seal_payload` 兼容别名）。
- **已实现能力（B10，统一入口与端到端闭环）**：
  - **统一 CLI**：`python -m versioning` 提供 data/prompt/train/eval/model/backup 六类子命令；所有正式版本由调用方显式传入，缺失参数、非法引用与领域门失败均以非零状态停止。
  - **holdout 接线**：data claim 先把预注册原子冻结到 `evaluations/staging/<eval>/authorization/pre_registration.yaml`，再显式绑定 eval/model/data/split 四元组、executor 与完整 SHA-256；train create 在线执行数据训练引用门并拒绝 holdout；eval create 校验冻结摘要与未消费 claim，eval 完成门按摘要复验内容、先写 `consumed.yaml` 再提交 MLflow 完成状态，跨机器路径不同但内容完全一致时仍可按同一身份安全恢复，任何内容漂移均拒绝。
  - **闭环证据**：fixture 测试覆盖数据发布、Prompt 冻结、训练父子 Run、测评父子 Run、模型注册/范围/model manifest/alias/current、eval manifest 单向导出和 backup catalog；反向用例覆盖无授权 holdout 测评、holdout 训练、三折模型 alias、悬空 model manifest、并发重复登记/改绑、manifest 并发冲突、人工 current、范围降级、adapter 夹带 merged 及物化中断拒绝。

## 5. 当前实现范围

- **B2 完成（身份与状态机）**：`versioning/ids.py`（五类可读身份解析/校验/生成）与 `versioning/state.py`（workflow_state 状态机）已实现，共 331 例测试。
- **B3 完成（数据封存与 holdout 安全）**：`versioning/data_release.py`（release 生命周期、seal 不可变、status 语义、训练引用门）与 `versioning/holdout.py`（holdout 隔离、pre_registration、一次性 claim）已实现，新增 138 例测试（含 8 个审查修复回归用例）；`tests/versioning/` 共 469 例全绿。
- **B4 完成（DVC pipeline 七阶段与最小 CLI）**：根 `dvc.yaml`（七阶段固定顺序、依赖链、review_import 外部人工输入依赖、release 依赖 review_import、release outs 固定路径 `data/release_payload` + `data/release_pointer.json`，无 `data/releases` out / persist，版本经 DVC params 注入）、`versioning/data_pipeline.py`（七阶段真实转换、上游 digest 贯穿 manifest、审查关卡 ReviewGateError、审查 `content_sha256` 绑定、release_validate 真实校验 + fail-closed）、`versioning/cli.py` + `versioning/__main__.py`（`python -m versioning data <stage>`，release 必填显式 `--version`，fail-closed exit code）已实现；新增 54 例测试（test_data_pipeline 34 + test_dvc_pipeline 20）；`tests/versioning/` 共 523 例全绿。
- **B5 完成（Prompt 版本与冻结）**：`versioning/prompts.py`（records/prompts 单一权威、训练 input 冻结副本、篡改检测；create_prompt 显式版本纪律、suggest_next_id 仅建议）已实现；新增 `test_prompts.py` 99 例全绿；`tests/versioning/` 共 622 例全绿，全量 `1305 passed / 11 skipped / 0 failed`。
- **B6 完成（MLflow 训练记录）**：`versioning/mlflow_train.py`（train 父 Run + fold0/1/2 嵌套子 Run、workflow_state↔RunStatus 固定组合、受控恢复、completed 晋级门、invalid 下游拒绝、读取 fail-closed、store 句柄双隔离）已实现；新增 `test_mlflow_train.py` 137 例全绿；`tests/versioning/` 共 760 例全绿，全量 `1443 passed / 11 skipped / 0 failed`。
- **B7 完成（MLflow 测评与 manifest 单向导出）**：`versioning/mlflow_eval.py`（eval 独立父 Run、显式 eval_id、五引用 tags、创建时 holdout 鉴权校验、三 scope fold 绑定、aggregate 输入集合==观测集合、结论门 invalid 优先、读取 fail-closed 注入防护、受控恢复原 Run ID）与 `versioning/manifest.py`（四段单向导出：build ID 先行→data/prompt/train/eval 门+链路一致、validate 严格键集合+值域+跨段、export 幂等+冲突+单向）已实现；B10 进一步把 holdout claim 的一次性消费接入 eval 完成门。B7 新增 `test_mlflow_eval.py` 223 例 + `test_manifest.py` 200 例全绿；`tests/versioning/` 当时共 1183 例全绿，全量 `1866 passed / 11 skipped / 0 failed`。
- **B8 完成（Model Registry、物化与晋级门）**：初版提交实现 Registry、晋级门、备份范围和基础导出；B12 最终复核补齐了并发唯一性、严格 model manifest、唯一 deploy target gate、`versioning/materialize.py` 的 alias→`models/current` 原子物化及 service_mode 启动校验。最终测试数和复审结论以实施台账为准。
- **B9 完成（离线备份 catalog 与恢复）**：`versioning/backup.py`（enumerate_backup_sources scope tag 驱动、create_backup 真实复制 + 落盘前全量校验含 SQLite integrity_check + 差异修复 + 原子替换 + prev 快照、load/verify/restore 零副作用 + 目标冲突拒绝 + 灾难恢复 + 封存权限重放）与 `versioning/data_release.py`（seal_payload 提升公开 API，保留别名）已实现；新增 `test_backup.py` 34 例全绿；全量 `2043 passed / 11 skipped / 0 failed`。
- **B10 完成（统一入口与端到端闭环）**：`versioning/cli.py` 整合 data/prompt/train/eval/model/backup；模型登记采用 register→eval→finalize 两阶段闭环；CLI、端到端及 holdout 反向测试覆盖缺参、Registry 精确引用、预注册冻结与内容漂移、消费写入和 MLflow 状态提交中断恢复。`tests/versioning/` 共 1383 例全绿；整仓最终结果以实施台账为准。该证据仅来自本机临时环境，不代表训练机真实迁移或模型效果验收。

## 6. 尚未迁移的 legacy 边界

- 已迁移：无。
- 未迁移：哈希数据 ID、集合 `index.json`、`LATEST` 指针、短哈希前缀解析等旧机制仍属 legacy 现役链路，直至正式迁移完成时再处理；新体系不使用。

## 7. 后续工作边界

- 旧对象映射、legacy 活动入口切换、训练机真实路径预检、真实数据/模型迁移及 merge/push 均不属于本轮核心基础设施实现，须按项目 TODO 另行授权和验收。
