<!-- DOCUMENT-CONTRACT
Purpose: 描述 mVllm_2 仓库当前真实系统组成与边界，作为仓库架构导航与可读版本控制新体系的维护入口。
Scope: 系统边界与双机角色、按入口划分的新旧链路指向、新体系职责划分与当前实现范围、未迁移 legacy 边界、文档导航；不展开运行细节。
Must Preserve:
- 只描述当前真实状态；区分"核心基础设施已实现"与"正式链路已迁移"，不得混写。
- 新体系入口 `versioning/` 使用五类 `<kind>-v<协议>-r<N>` 完整可读身份，其中 `kind` 为 data/prompt/train/model/eval；哈希 `index.json`/`LATEST`/短哈希前缀仅属 legacy 旧链路。
- 双机边界：训练/推理/正式版本写入在训练机，本机只做开发、轻量验证与文档；本机产物视为从训练机同步的结果。
Non-goals:
- 不重复 README/RUNBOOK 的运行细节、命令与步骤。
- 不承载迁移任务台账或批次计划（见项目TODO）。
- 不重述架构决策理由与目标细节（以设计文档为准）。
-->

# mVllm_2 架构

> 状态：正式入口正按已确认迁移范围逐个接管，部分入口已停止旧写入；真实环境验收缺口仍保留。本文描述模块边界；架构目标见[设计文档](docs/plans/2026-09-01-readable-version-control-design.md)，当前任务状态见[项目TODO](docs/project-todo.md)，历史B批次见[基础设施实施台账](docs/plans/2026-09-01-readable-version-control-implementation.md)。

## 1. 文档导航

- [README.md](README.md)：仓库概述、当前维护协议与常用流程入口。
- [AGENTS.md](AGENTS.md)：项目 Agent 运行规则，含双机边界、新旧体系分域与提交信息约定。
- [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md)：显式七阶段数据手册及历史流程参考。
- [finetune/README.md](finetune/README.md)：现行训练/评测入口导航与历史实验参考。
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

## 3. 新旧入口边界

正式数据七阶段和限定对象迁移由versioning接管；旧release_build/release_build_phase2/rebuild_data CLI已停用。训练与验证集评测通过versioning调用finetune业务函数，旧train_build_dataset/train_prepare_run/train_with_contract/eval_run CLI也已停用。服务入口按MLflow alias与service mode复验后加载。

ROI输入准备、legacy人工审查及相关索引辅助依赖仍保留，不能把局部退役扩大为删除整个pipeline或finetune。入口明细见[入口清单](docs/results/version-control-migration/entrypoint-map.md)。历史产物不原地改写；旧current/LATEST不作为新身份选择依据。

## 4. 新体系职责与实现

基础设施提供身份、生命周期和存储原语；正式CLI在此之上绑定真实输入及执行器。数据链已有训练机真实媒体验证，训练/评测接线的受控测试不代表真实模型效果通过。

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
- **数据七阶段与DVC**：根dvc.yaml是模板；显式root/inputs/batch与发布version由生成配置绑定。source→roi→subvideo→review_export→review_import→release→release_validate调用run_input_*真实业务链，冻结原视频、注释、原split、人工ROI及实际候选媒体。完整审查包交给UI，包外review_return.json由review_import验签后消费。
  - 工作阶段输出使用persist；输入漂移拒绝，不自动清旧结果。release封存data/releases/<完整版本>/payload，元数据同级，DVC只跟踪payload；不写release_pointer.json。release_validate只读复验，不启动训练。完整链路见数据手册第10节。
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
  - **统一 CLI**：`python -m versioning` 提供 data/prompt/train/eval/model/backup/migration 七类子命令；所有正式版本由调用方显式传入，缺失参数、非法引用与领域门失败均以非零状态停止。
  - **holdout 接线**：data claim 先把预注册原子冻结到 `evaluations/staging/<eval>/authorization/pre_registration.yaml`，再显式绑定 eval/model/data/split 四元组、executor 与完整 SHA-256；train create 在线执行数据训练引用门并拒绝 holdout；eval create 校验冻结摘要与未消费 claim，eval 完成门按摘要复验内容、先写 `consumed.yaml` 再提交 MLflow 完成状态，跨机器路径不同但内容完全一致时仍可按同一身份安全恢复，任何内容漂移均拒绝。
  - **闭环证据**：fixture 测试覆盖数据发布、Prompt 冻结、训练父子 Run、测评父子 Run、模型注册/范围/model manifest/alias/current、eval manifest 单向导出和 backup catalog；反向用例覆盖无授权 holdout 测评、holdout 训练、三折模型 alias、悬空 model manifest、并发重复登记/改绑、manifest 并发冲突、人工 current、范围降级、adapter 夹带 merged 及物化中断拒绝。

## 5. 基础设施历史实现记录

以下B2–B12描述各批次当时的实现和测试，保持历史证据；其中B4最小pipeline已由第4节的真实七阶段替换，不能把旧路径/测试数当成当前运行规范。

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

- 已接管：显式数据七阶段、限定数据/Prompt对象迁移、三折训练及validation评测执行器、严格alias服务与跨机备份；逐项证据和未验证范围见项目TODO及入口清单，不能等同真实模型全链验收。
- 未迁移：哈希数据 ID、集合 `index.json`、`LATEST` 指针、短哈希前缀解析等仍被部分legacy辅助模块引用，按入口清单保留核查；新体系不使用，已停用CLI不得恢复默认选择。

## 7. 后续工作边界

- 剩余legacy辅助入口和索引依赖继续按已批准任务逐个核定；真实模型训练/推理、full/holdout实际输入及大型硬盘恢复保留验收缺口。既有迁移实施授权持续有效，merge/push及其他超出该授权的操作须另行授权。
