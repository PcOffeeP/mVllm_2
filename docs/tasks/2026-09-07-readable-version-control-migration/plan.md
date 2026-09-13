# 可读版本控制正式迁移实施计划

- **Task ID**：`2026-09-07-readable-version-control-migration`。
- **上游**：[Intent](intent.md) 确认提交 `3dae30a0`；[Spec](spec.md) 确认提交 `0bf0baed`（承接789fa4fc；2026-09-13用户确认独立全量训练范围）。
- **分支**：`refactor/2026-09-07-readable-version-control-migration`；本机工作区 `/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2`。
- **目标**：按 Spec 完成实际入口和限定对象迁移，形成面向 Codeup main 的可审阅交付。此文件只编排实施，状态和每批结果写入[项目 TODO](../../project-todo.md)。
- **确认与执行边界**：用户已确认本 Plan，并要求先单独提交计划文档；本次提交不启动迁移实施。后续执行遵守文末列明的实施范围与单独授权边界。

## 执行基线与真实缺口

基础设施承接点为 `1b0d5823`；前序 1399 项 versioning 测试、2082 项整仓测试及独立复核均为历史证据，本次实施后按受影响范围重新验证。现场观察见[调查记录](../../results/version-control-migration-20260907.md)，不能把文件存在性当作完整性或加载证据。

规划时查明两处关键接入缺口：

- `versioning/data_pipeline.py` 的 `_derive_roi` 从文件名摘要生成 ROI，`run_subvideo` 为每视频生成两条记录；这是已有最小数据链行为，不能承接真实人工 ROI、视频剪裁和采样语义。M3 必须替换正式路径上的该行为，并保留真实业务规则。
- `versioning/cli.py` 的训练处理函数创建、更新 MLflow Run；实际训练仍在 `finetune/train_with_contract.py`，测评仍在 `finetune/eval_run.py`。M4 必须贯通真实调用，而非只补充状态管理测试。

## 文件范围与实施选择

以下是计划允许的精确代码文件集。不得将某个目录整体作为任意修改授权。M0 若发现遗漏的活动入口或底层身份依赖，先记录精确路径并更新 Plan；改变行为或职责时回到 Spec。

| 范围 | 允许新增或修改的文件 | 职责 |
| --- | --- | --- |
| 迁移转换与历史整理 | 新增 `versioning/migration.py`、`tests/versioning/test_migration.py`；修改 `versioning/cli.py`、`versioning/data_release.py`、`versioning/prompts.py` | 显式映射、预检、受控写入、简明历史信息提取 |
| 数据业务接入 | `versioning/data_pipeline.py`、`dvc.yaml`、`params.yaml`、`pipeline/data_rebuild.py`、`pipeline/scripts/rebuild_data.py`、`pipeline/scripts/release_build.py`、`pipeline/scripts/release_build_phase2.py`、`pipeline/scripts/review_candidates_app.py`、`pipeline/scripts/roi_annotation_app.py` | 七阶段真实输入输出、人工交接、旧写入口接管 |
| 训练与测评接入 | `finetune/train_build_dataset.py`、`finetune/train_build_source_aware_dataset.py`、`finetune/train_prepare_run.py`、`finetune/train_with_contract.py`、`finetune/eval_run.py`、`finetune/validation/constants.py`、`finetune/release_validate.py`、`finetune/v4_1_runtime.py`、`versioning/mlflow_train.py`、`versioning/mlflow_eval.py`、`versioning/manifest.py` | 冻结输入、实际执行器、Run 生命周期、正式引用校验 |
| 服务与模型接入 | `pipeline/server_proxy.py`、`pipeline/server_adapter.py`、`pipeline/model_registry.py`、`pipeline/server_deployment_manifest.example.json`、`scripts/serve_validate_delivery.py`、`scripts/serve_manage_model_registry.py`、`pipeline/scripts/serve_smoke.py`、`versioning/registry.py`、`versioning/materialize.py` | 启动和加载前统一解析合法 alias，停用旧开发例外 |
| 存储与备份 | `versioning/backup.py`、`pyproject.toml`、`uv.lock`、`requirements.txt`、`.gitignore` | 依赖兼容、运行存储、跨机传输及恢复接线 |
| 回归测试 | `tests/versioning/test_data_pipeline.py`、`tests/versioning/test_dvc_pipeline.py`、`tests/versioning/test_cli.py`、`tests/versioning/test_e2e.py`、`tests/versioning/test_mlflow_train.py`、`tests/versioning/test_mlflow_eval.py`、`tests/versioning/test_materialize.py`、`tests/versioning/test_registry.py`、`tests/versioning/test_backup.py`、`tests/test_train_with_contract.py`、`tests/test_eval_run.py`、`tests/test_serve_smoke.py`、`tests/test_serve_validate_delivery.py`、`tests/test_v4_1_runtime_pointers.py`、`tests/test_data_rebuild.py`、`tests/test_rebuild_source_only.py`、`tests/test_roi_annotation_app.py` | 真实入口接线、语义保持、失效与恢复回归 |
| 文档收敛 | `AGENTS.md`、`ARCHITECTURE.md`、`README.md`、`docs/project-guide.md`、`docs/DATA_PROCESSING_RUNBOOK.md`、`finetune/README.md`、`pipeline/SCRIPTS.md`、`pipeline/scripts/SCRIPTS.md`、`finetune/SCRIPTS.md`、`versioning/SCRIPTS.md`、`docs/project-todo.md`、`docs/plans/2026-09-01-readable-version-control-design.md`、`docs/plans/2026-09-01-readable-version-control-implementation.md` | 只同步实际生效入口、Spec 已确认的边界与历史阶段记录 |

**只读参考、默认保持不变：** `pipeline/source_bootstrap.py`、`pipeline/roi_manifest.py`、`pipeline/roi_media.py`、`pipeline/v3_candidate_plan.py`、`pipeline/v3_candidate_media.py`、`pipeline/v4_1_review_workflow.py`、业务契约、旧已发布 manifests、历史实验配置和报告。真实媒体算法优先复用；其身份写入若无法与业务算法分离，M0 报告并精确扩充 Plan，不复制一套变化后的算法冒充等价。

2026-09-12 M4精确补充：`finetune/validation/constants.py` 将旧数据路径常量的活动指针读取延后至legacy调用者显式请求，保留原返回值；模型推理仅导入生成参数时不再读取旧指针。该文件是实际model_runtime的直接依赖，此局部隔离不改变数据划分、生成参数或正式输入契约。

历史正式产物不原地改名、覆盖或删除；`stash@{0}` 保留。`finetune/active_data_release.json`、`pipeline/model_registry/current.json` 和旧模型 release manifest 作为历史证据保留，活动代码解除对它们的依赖。不存在合格 alias 时不改写旧模型质量结论。

**新轻量输出：** 本任务证据放入 `docs/results/version-control-migration/`，具体文件为 `source-inventory.yaml`、`object-mapping.yaml`、`entrypoint-map.md`、`history-summary.yaml`、`verification.md`、`handoff.md`。这些是映射、历史证据和验证记录，不是新的全局注册表或任务状态库。已确认正式对象的输出路径由完整版本名确定，在 object-mapping 中逐个列明后才允许写入；不预造版本编号。

## Batch 顺序与完成门

| Batch | 内容 | 依赖 | 可观察交付 |
| --- | --- | --- | --- |
| M0 | 真实对象、入口与写入边界核对 | Plan 确认 | 精确源清单、版本映射候选、入口调用图与保护清单 |
| M1 | 转换器和历史摘要 | M0 | 两个数据版本/一版 Prompt 的转换能力、模型核心事实可查询 |
| M2 | 隔离训练机环境与存储预检 | M0，M1 可并行准备 | Linux 测试环境、权限/锁/DVC/MLflow smoke 证据 |
| M3 | 数据七阶段真实接入 | M1、M2 | 真实小样本与人工交接证据，两个旧 release 语义一致迁移 |
| M4 | 训练与测评执行器接入 | M3 | 新身份贯穿输入冻结、执行调用、Run 和结果记录 |
| M5 | 服务入口严格切换 | M4 | 全部实际入口遵循 alias；无合格模型可拒绝启动 |
| M6 | 备份接线与恢复验证 | M3、M4 | 范围正确、传输及联合恢复证据；硬盘项单列 |
| M7 | 旧活动写入口退役与文档 | M3–M6 的非延期部分 | 单一正式写入者、无旧选择绕过、文档与入口一致 |
| M8 | 最终审查和交付 | M7 | 验收矩阵、独立审查、完整 Codeup 差异和限制清单 |

这些编号是施工分组，不增加 Spec 状态机。每批完成后更新 TODO：实际机器、提交、Proof 结果和限制；每个独立可验证代码步骤原子提交，不积压到整批结束。依赖失败只暂停受影响的下游。

### 当前实施进度（2026-09-13）

本节同步执行进度；项目任务状态仍以docs/project-todo.md为唯一台账，详细证据见docs/results/version-control-migration/verification.md。

| 阶段 | 当前状态与下一动作 |
| --- | --- |
| M0–M3 | 已完成现场核对、转换能力、隔离环境与真实数据链迁移验收 |
| M4 | 三折训练及validation执行接线、双机CPU范围验收完成；代码7cb24398、证据7a750065。本轮独立full训练与holdout媒体run/授权score接线完成（fed9bcfc），Linux819 passed/1 skipped、各exit0，双机及独立局部证据见第45节；真实训练/GPU、真实holdout读取及真实注册模型成功路径仍未验证，保持未关闭 |
| M5 | 进行中（Codex）：server_proxy实际加载、registry管理、交付校验及smoke已接线；本机联合179项与后续最终服务专项41项通过，独立审查通过本轮代码与本机证据范围；Linux最终41项通过；真实模型成功路径未验证，真实环境依赖继续保留（verification第32节） |
| M6 | 部分验收通过（store级恢复已完成，真实硬盘/大型产物待验收）：Mac/Linux109项通过，实际SSH往返、错误摘要拒绝和原隔离路径联合恢复通过；独立证据核查通过，真实硬盘/大型产物未验证；M8-R4 store级异根恢复已由2fce3ab1完成并通过Mac/Linux及独立局部验收，真实硬盘/大型产物与外部依赖整机恢复仍未验收（verification第33、39、41节） |
| M7–M8 | M7a完成（881c8181）：三个数据旧CLI退役，数据手册与入口索引同步，本机/Linux各57项通过、独立审查通过；M7b本批完成（60dd00bc）：四个旧训练/评测CLI退役及ARCHITECTURE/finetune文档收敛，双机证据见verification第35节；M7c本批完成（09035fd4）：旧queue写入退役、ROI显式路径及文档同步，两端验证见verification第36节；M7d本批完成（15b44009）：7个辅助CLI退役，验证见第37节；M7e本批完成（cc02acc1）：旧Prompt CLI退役、历史索引工具显式根及文档同步，两端179项通过/独立核查通过（第38节）；历史库保留。以下M8首次审查及后续驳回为历史推进记录，不作为当前下一动作。M8进行中（Codex）：f1b7d8a3至0963642b全量117提交/148文件独立审查，整仓CPU基线2603 passed/11 skipped；整体审查驳回，M8-R1代码3b63aa52完成、本机整仓及独立局部审查通过，Linux分三进程956 passed/1 skipped、各exit0，R1本轮范围已解决；M8-R4 store级异根恢复已解决本轮范围（代码2fce3ab1，Mac/Linux及独立局部验收，第41节），M8-R2 Prompt并发及M8-R3训练半提交已解决本轮范围（2b8cbc89）：Mac/Linux各466项、独立251项通过。历史汇总实物已交付（21条，第42节）；第43节物理Prompt已补齐，Mac整仓2647 passed/11 skipped、exit0。最终125提交/149文件独立审查已完成且因M8-R5驳回整包；当前矩阵已更新，第44节R5已由de1b51dd解决本轮范围，用户策略确认、Mac/Linux200项及独立局部证据通过；本轮full/holdout接线及双机隔离CPU验证已完成（fed9bcfc，Linux819 passed/1 skipped、各exit0，第45节）；第46节完整复审e1d70c58曾因M8-R6驳回，Mac整仓另发现M8-R7；两项已由d9ec1227修复，Mac整仓2694 passed/11 skipped、exit0，Linux两组179+1项各exit0，更新的独立整包代码审查覆盖140提交/152文件并通过（第47节）；真实环境缺口分别保留，未授权push/merge |

### 2026-09-13 交付收口与模型前置准备

当前下一动作以TODO及verification第48节为准：完成四文档独立核查、修正过期CLI与R6/R7状态；不重复第47节已通过的完整代码审查和CPU回归。真实环境限制继续保留。

用户本轮明确要求同时推进HOLDOUT-BUILD和MODEL-DIAG，先执行不改变行为契约的只读准备。精确新增轻量证据文件为`docs/results/model-diagnostics-preflight-20260913.json`，保存限定SSH元数据检查、历史development原记录重算的程序/摘要/返回结果和纯配置探针；不收录逐样本标签、预测或权重。该扩充仅用于本轮Proof落盘，不新增训练、holdout构建/使用或正式写入授权。

来源未指定与实际构建入口未接通阻塞HOLDOUT-BUILD。新发现的HOLDOUT-METRICS先记录并确认公共配置扩展，再按守护流程更新Spec/Plan；本轮不自行改变评分口径。MODEL-DIAG可复算已有开发预测，但concise缺失和历史visual权重断链阻塞新推理；找到精确备份位置后只读核验，不全盘搜寻或恢复覆盖产物。

### M0：核定范围与写入者

1. 刷新本机 Codeup 引用，分别检查本机和训练机分支、HEAD、未提交状态及独有提交；读取训练机不等于授权同步或合并。
2. 对两份 release 读取 manifest、payload 结构和上游审查关系；对当前 Prompt 比对实际文件与发布记录。完整性扫描在训练机执行，记录扫描范围与 I/O 预算。
3. 核对六组有权重历史 run、两个准备目录和已知 concise-cv 路径缺口；提取核心参数及允许读取的已有评估摘要。资料缺失写为未知，不为完整性重跑历史实验，不无限搜遍训练机。
4. 列出每个活动入口的调用方、身份解析、正式写入点和最终模型加载点；重点追踪上述服务文件及训练/数据脚本。只停用旧身份与写入路径，不把整个 pipeline/finetune 包当作可删除对象。
5. 将源和目标精确路径、显式候选版本、目标冲突检查、需要保持的状态列入 object-mapping；用户人工核对映射是原设计要求，不能用 Plan 批准替代对象核对。缺失源不补造，冲突不自动改号。

**停止条件：** 真实源与钉扎记录不符、发现运行中的写入任务、缺少读取授权、目标编号冲突、额外入口超出文件范围。不得停止已有进程来满足预检。

### M1：实现受控转换与简明历史记录

新增迁移模块，由统一 CLI 编排；显式区分只读预检与真实转换。数据和 Prompt 复用既有封存/冻结校验，先验证映射、引用和全部必需文件，再向独立目标写入；不得在旧目录中原地转换。

简明历史记录写入 history-summary，逐字段记录来源或未知原因，并保存原 ID；不分配伪造 model/eval 身份，不为复用导出器创建虚假 completed Run。真实完整对象确需登记时走原有契约，旧 Prompt 引用不能替换为当前 Prompt。

测试覆盖混合完整/缺失资料、准备目录、旧状态保持、目标冲突、复制中断以及同一次转换恢复。恢复凭证须绑定映射和源内容；没有可核实的同操作依据就停止，不复用碰巧同名的临时目录。

### M2：隔离环境准备

训练机项目为 `/home/liuyang/文档/mVllm_2`。实施时以任务专用隔离 checkout 和项目级环境验证已提交代码，保留现有 main 工作区；代码传递用已提交 Git 对象的 bundle/隔离 checkout，不默认 push 或强制对齐。精确远端新目录先记录于 verification，再创建；不得覆盖现有路径。

`/data/mVllm_2/dvc-remote/` 和 `/data/mVllm_2/mlflow/` 是设计目标。先只读检查权限；无权限则记录需要管理员完成的目录准备，不自行 sudo 或修改系统权限。现有 Conda 环境不原地升级；DVC/MLflow 与 pandas 的兼容性在独立项目环境中验证并记录锁定版本。

临时实例完成 Linux 文件锁、只读权限、DVC 小对象 remote 恢复及 SQLite/artifact 联合恢复。临时 store 不与正式 store 混用，fixture 不产生正式版本。任何训练机现存进程切换/停止另行确认。

### M3：接入真实数据语义

替换新正式 pipeline 中文件名派生 ROI 和固定两条 clip 的行为。调用现有 source、ROI、候选生成与媒体处理能力，保留几何、时间轴、采样帧、标签及审查语义；从底层业务计算中隔离旧哈希发布行为。DVC deps 同时包含实际输入、配置、契约和实现代码，人工回收结果保持外部依赖。

根 DVC 调用与真实 workspace 对齐，避免默认在仓库根另建第二份权威 data。用显式 workspace 根生成/消费版本，版本参数始终由调用者提供。

先在训练机用明确非正式小样本执行 ROI/剪裁/采样，逐条对比旧实现的输入输出；再演练审查导出到 Mac、回传及完整接收。两份已发布数据只做语义保持的映射、复制/登记与验证，不借迁移重跑出新内容。正式转换需 M0 映射人工核对和源完整性检查通过。

### M4：贯通训练和正式测评

让真实数据构建、训练准备和执行器调用共享 versioning 的身份与冻结校验；运行事件驱动 MLflow 开始、失败、fold 结束、汇总和导出。注入非 GPU 测试执行器检验参数传递和失败路径；不把它产生的记录写入正式 store。

评测入口先验证完整模型身份、数值版本、数据和配置，再解析权重路径；原始 model-dir 不能绕过正式测评入口。保存真实结果与评分上下文，不把历史 summary 转换为 passed。受限评测继续执行授权门。

训练机执行真实路径和输入准备 dry-run，不运行重训练或完整评测。实际执行器的静态调用、可控进程替身和准备验证分别记录，明确尚未进行真实 GPU 训练。

### M5：服务入口统一准入

将 server_proxy、server_adapter、交付验证、registry 管理及 smoke 的活动选择路径接入共享 alias 解析和 materialize 校验。保留 candidate/production 原有 passed 门和生产批准，不引入 legacy alias、开发豁免或手工路径回退。

从真实 CLI/服务启动入口测试无 alias、未通过模型、错误模式、缓存不一致和 Registry 不可用；验证加载器没有被调用且返回明确错误。成功路由用临时合法 fixture 和受控 loader 验证绑定，证据标为模拟。

无合格真实模型时，记录实际入口接管、拒绝启动已验证，真实模型加载/推理成功路径未验证。若已有服务进程运行，不擅自停止；实际进程变更另列明确动作，不以文件改完冒充运行进程已切换。

### M6：备份与恢复

核对当前备份模块的本地路径假设，接通从训练机一致性快照到 Mac 指定目标的受控传输；先以隔离小对象测试，失败不更新 verified，不把大型对象长期暂存 Mac 内置盘。正式 store 快照与 artifact 选择沿用同一范围规则。

恢复验证包括源缺失、catalog 损坏、传输中断、scope 升级、SQLite 与 artifact 联合恢复，以及 adapter 范围不夹带 merged。真实移动硬盘不可用时，在 TODO 单列未完成项；这不豁免本地/隔离环境下的备份功能验证，不触发源文件删除。真实硬盘路径和容量在设备连接后核对，不猜挂载点。

### M7–M8：退役、文档和交付

按 M0 的入口清单逐个证明旧解析/写入路径已不在活动调用链。`pipeline/artifact_index.py`、`pipeline/scripts/build_artifact_index.py` 初始只读核查；确认无活动依赖且列入精确删除清单后更新 Plan 再退役，不笼统删除整个目录。保留与数据语义有关的业务实现及历史审计内容。

同批更新 README、RUNBOOK、训练说明、脚本索引和 AGENTS 的活动/历史边界。历史 B0–B12 提交证据保持不变，追加本任务接入结果；长期文档按适用文档契约维护，操作文档由独立 reviewer 对照实际入口核查。

最终针对 Codeup main 到本任务 HEAD 的完整差异独立审查，包括本地 main 原有的独有提交，注明其来源。生成 handoff，包含每项 Spec 的证据、源对象保护检查、未验证真实硬盘/真实 GPU 成功路径、两端 Git 状态及拟合并目标。此时提出明确 merge/push 请求；本 Plan 不提前授权二者。

## Proof：场景、命令与证明范围

所有本机命令在上述本机 worktree 执行；训练机命令在已核对的隔离 checkout 中用该环境 Python 执行。以下新增测试路径在 M1 创建后才运行，不宣称已有命令今天可完成真实迁移。

| Spec 行为 | Proof | 证明内容与限制 |
| --- | --- | --- |
| 两个 release、一版 Prompt、身份不漂移 | `.venv/bin/python -m pytest -q tests/versioning/test_migration.py`；训练机对两份 payload 做流式文件清单/摘要比对 | 测试证明转换拒绝/恢复行为；真实逐文件比较才证明此次内容保持 |
| 历史参数和指标保真 | 同一迁移测试；人工抽核 history-summary 的来源、单位、split、缺失值 | 证明可追溯整理，不证明所有历史训练可复现 |
| 数据语义、人工交接、DVC 依赖 | `.venv/bin/python -m pytest -q tests/versioning/test_data_pipeline.py tests/versioning/test_dvc_pipeline.py tests/test_data_rebuild.py`；训练机非正式媒体对照及双机审查演练 | 防止最小 fixture 替代真实媒体行为；DVC 过期发现不自动执行 |
| 训练与测评实际接线 | `.venv/bin/python -m pytest -q tests/test_train_with_contract.py tests/test_eval_run.py tests/versioning/test_mlflow_train.py tests/versioning/test_mlflow_eval.py`；真实路径准备 dry-run | 参数和事件链、异常退出及引用门；不证明真实训练效果 |
| 服务切换及严格 alias | `.venv/bin/python -m pytest -q tests/test_serve_smoke.py tests/test_serve_validate_delivery.py tests/versioning/test_materialize.py tests/versioning/test_registry.py`；真实启动入口拒绝场景 | 证明活动入口拒绝绕过、加载前拦截；真实推理成功另列 |
| 备份与恢复 | `.venv/bin/python -m pytest -q tests/versioning/test_backup.py`；训练机/Linux 小对象联合恢复及跨机传输故障场景 | 隔离恢复与范围一致性；不能认证未连接的真实移动硬盘 |
| 单写、不可覆盖及回退 | 各入口并发创建、半写故障注入、恢复前后正式状态比较 | 证明冲突拒绝和证据不丢失；不以代码 git revert 代替状态恢复验证 |
| 旧入口全部接管 | entrypoint-map 每行记录修改位置及行为测试；检索 LATEST/index/短哈希并逐个分类 | 搜索只能发现线索，必须以实际调用测试证明没有绕过 |
| 最终回归与文档 | `.venv/bin/python -m pytest -q tests/versioning`；`.venv/bin/python -m pytest -q tests`；`git diff --check`；独立文档与最终 diff 审查 | 必须正常退出并记录 skip 原因；文件存在或链接正确不代表命令业务正确 |

每项验证记录代码提交、机器、命令、输入/输出位置、退出码与实际结论。对未跟踪新文件直接检查完整内容；代码/文档提交前精确暂存后执行 `git diff --cached --check`，不能只靠普通 diff 漏掉新文件。禁止用管道尾部成功掩盖测试失败。

## 风险与局部停止

- **权限和空间**：不覆盖源产物的迁移可能暂时多占空间；训练机先估算两份 release 和模型处理所需体量，空间不足不靠删除历史模型解决。
- **依赖和业务耦合**：旧算法可能混入身份写入，新增依赖可能破坏 Conda；先隔离测试，必要文件扩展进 Plan，数据语义变更回到 Spec。
- **当前代码与存储不一致**：传输期间源变化或运行进程写入，停止该对象转换，保留证据，不强制锁死或终止他人任务。
- **历史引用缺失**：按 Spec 标记未知，不无限补资料，不伪造 passed；只有正式对象的必需缺口阻塞其正式登记。
- **验证误报**：未测真实硬盘、真实训练及无合格模型的真实推理，各自明确列出；基础设施测试总数不代替实际接入证据。

## Plan 确认时的实施范围

请求用户确认本计划并明确授权其范围内的实现、正常原子提交、限定的训练机项目级隔离环境准备与小样本验证、经人工核对映射后的两个数据版本和一版 Prompt 迁移，以及历史摘要整理和入口接管。

merge/push、系统权限调整、停止已有服务或训练进程、真实重训练/完整评测、受限测试使用、历史权重删除不包含在上述授权中。遇到这些动作，只暂停相应部分并提供精确目标和理由。Plan 确认提交并取得实施授权前，不开始任何迁移实施；已有授权内的只读调查和草案整理可以继续。

## 2026-09-12 用户追加的审查者完整性修复

用户要求分析历史人工记录reviewer_id缺失，并修复未来人工审查必须补全审查者信息。此授权允许对既有review_candidates_app.py的legacy模式作局部缺陷修复：两模式开始前强制非空审查者标识、界面显示当前审查者、完整汇总前逐条检查作者。已有普通未断裂自动准入规则保持不变，不批量将匿名历史记录归给当前操作者，不改写历史封存对象。实施仅涉及既有允许文件review_candidates_app.py、rebuild_data.py中的继续审查命令提示、tests/versioning/test_data_pipeline.py及对应操作说明/任务证据；不调整共享历史读取/迁移schema。

## 2026-09-12 单维护者审查归属（取代上一节的手填要求）

用户明确确认历史人工审批均由本人完成，并批准默认使用“项目维护者”。新决定自动记录该角色，保留可选显式标识；不以旧记录缺姓名要求重审，不改写原历史记录。23条对象完全匹配的审批可依据本次确认复用，原审查时间保留，补充确认单独记录。人工决定完整性及媒体绑定门禁继续有效。


M7a精确范围：上述三个数据CLI停止历史写入并指向versioning显式七阶段；rebuild_data的旧编排函数仅保留为私有历史测试入口，tests/test_rebuild_source_only.py改为显式调用该私有入口，新的真实CLI拒绝回归放tests/test_data_rebuild.py。不删除artifact_index/artifact_resolver：source_bootstrap、ROI及候选媒体业务实现仍依赖它们。M4/M5尚未验证的真实成功路径不因本批关闭，其他未核定旧入口逐个列证据后处理。

M7b本批精确范围：停用train_build_dataset/train_prepare_run/train_with_contract/eval_run公开CLI，保留新入口直接调用的版本化业务函数及历史私有测试入口；回归在既有允许的tests/test_train_with_contract.py、tests/test_eval_run.py添加或调整。只读复跑tests/test_train_build_dataset.py与tests/test_train_build_source_aware_dataset.py，不改采样、评分或底层训练。ROI/审查/索引辅助入口不在本批退役范围。

M7c精确范围：review_candidates_app公开UI仅接受完整versioning-package，拒绝旧queue写入；roi_annotation_app仍作为ROI输入准备工具，显式要求metadata文件、output和project-root，不再在导入或参数处理中选择current/LATEST。历史解析器仅保留私有测试，ROI几何和人工决定业务不改。tests/test_roi_annotation_app.py加入该入口的精确回归范围，review回归复用tests/versioning/test_data_pipeline.py。索引库仍有历史业务依赖，保留而不删除。

M7d精确补充：允许修改pipeline/scripts/roi_freeze_decisions.py、roi_materialize_videos.py、subvideo_build_plan.py、subvideo_materialize_media.py、review_build_queue.py、review_build_phase2_queues.py、review_route_from_history.py，停止其公开CLI写入并指向versioning显式七阶段。versioning无上述脚本调用，保留历史私有main及解析器、业务库；回归新增在已允许tests/test_data_rebuild.py，复跑六个相关历史CLI测试及tests/versioning/test_data_pipeline.py。不变更几何、采样、分流规则或历史对象；不删除索引库。

M7d文档与历史测试补充：tests/test_subvideo_build_plan.py中的旧dry-run语义测试显式调用私有_legacy_main（既有真实数据缺失时仍skip，不当作通过）；允许docs/INFERENCE_SERVICE_RUNBOOK.md仅追加历史适用范围与现行服务链接，不重写历史操作或效果证据。

M7e精确补充：修改pipeline/prompt_control/__main__.py停用旧validate/publish公开CLI，历史main私有保留，不改core或__init__导出；模块启动先完成既有包导入，但不得解析/读取旧source或调用publish。修改pipeline/scripts/build_artifact_index.py，历史INDEX.md报告工具必须显式--data-root且目录存在，不再选择current根，不更改底层集合索引。新增回归在tests/test_prompt_control.py和tests/test_artifact_index.py；核对tests/versioning/test_prompts.py及test_cli.py。versioning/SCRIPTS.md补Prompt现行参数说明并将过期legacy不变条款同步为既定逐入口退役边界。

M7e文档精确补充：pipeline/prompt_control/README.md仅追加历史范围与现行Prompt链接，保留原历史说明；README/finetune说明/项目指南同步旧Prompt停用与新定义入口，不改变历史Prompt正文。

M8-R1精确测试补充：`tests/versioning/test_cli_holdout.py`随公共手工写入口停用更新，验证合法claim也不能由手工状态消费；既有低层holdout状态/消费故障测试继续保留。训练证据保存为实际父Run的`training-evidence.json` artifact及只写一次的摘要param，不产生新正式身份或全局索引。

2026-09-13 M8-R1已解决本轮范围（代码3b63aa52）：Mac整仓2623 passed/11 skipped，Linux分三进程956 passed/1 skipped、各exit0，独立代码/操作文档局部审查通过。首次Linux单进程回归触及1024文件句柄上限而exit1，已保留日志；相同代码及原限额分组复验通过，不能外推长期服务资源验收。完整证据见verification第40节。下一步M8-R4异根恢复、history-summary实物与最终整包复审；真实GPU/full/holdout及物理存储缺口保持，M8整体不关闭。


2026-09-13 M8-R4进行中（Codex）：从7bea4533继续已授权实施。修复恢复副本SQLite内的MLflow存储地址，保留不可变训练/评测内容及状态；验收要求新根读取、原模拟store不可达、备份不变、非法映射和冲突拒绝。代码限既有backup.py及已批准测试/文档，基础模型与外部媒体不因重定位扩大备份范围。

2026-09-13 M8-R4已解决本轮store级异根恢复范围（代码2fce3ab1）：Mac受影响回归175 passed/1 skipped，最后URI严格化另6 passed；Linux最终同一提交181 passed/1 skipped、exit0；独立代码/操作文档局部审查通过。原模拟store不可访问时，新根artifact读取、显式current/服务准入、后续写入与再次备份均通过；冻结事实和原备份保持。验证见第41节；真实硬盘/大型产物、外部依赖整机恢复与GPU不在通过范围。下一步补实际history-summary并做M8最终整包复审，整体迁移不关闭。

2026-09-13 M8历史汇总进行中（Codex）：承接a14b3d0a，读取训练机原工作区的限定run结构及隔离分支的五份轻量归档，生成已批准history-summary.yaml。分别保留来源根、归档声明与本轮观察；不写原工作区、不复制大型权重、不读取受限测试结果、不新增正式身份。验收覆盖声明对象全集、Spec核心字段的已知值/未知原因、指标口径与审批事实，并独立核查。

2026-09-13 同轮发现并修复M8历史生成器batch口径（Codex）：已证实原H9缺world_size却输出effective_batch_size；本轮改保留per_process_accumulated_batch及推导来源，全局值未知。变更仅既有migration.py与test_migration.py，RED有效，Mac migration+CLI247项通过；代码/产物/Linux与独立结论见verification第42节，不新增训练或正式身份。

2026-09-13 M8历史汇总本轮交付完成：history-summary.yaml含21条、234已知/152未知、47份轻量来源及实际权重stat，已独立验收；同轮公共生成器batch误记由d2ae4cee修复，Mac/Linux migration+CLI各247项通过，独立15项通过。证据见第42节。下一步核对物理/data下Prompt落位并做M8最终完整Spec矩阵与差异复审；真实GPU/full/holdout及硬盘/大型产物限制保留，整体迁移未完成。

2026-09-13 M8最终核查进行中（Codex，代码ab5c71ae）：使用既有公开prompt create入口把已确认Git定义登记到/data/mVllm_2，核对原文字段、字节SHA和重复写入拒绝；只新增同身份Prompt文件与隔离证据。并行执行Mac整仓CPU回归与f1b7d8a3→ab5c71ae完整独立审查，更新当前Spec验收矩阵。无新增方案取舍；full/holdout实际输入未接线与真实GPU未验证须分开记载。

2026-09-13 M8物理Prompt已完成（第43节）：公开create/show成功，重复create拒绝，1200字节及SHA与Git一致、9份保护文件保持。独立最终复审新增M8-R5 P2：当前concise Prompt对应合法candidate被固定服务analysis契约拒绝。先确认服务Prompt来源，再列精确接线和回归；不更改已冻结Prompt/输出/评分/alias门。该记录时最终CPU与独立完整审查进行中，最终复审结论见下条；full/holdout实现未接线、GPU与硬盘验证缺口分别保留。

M8-R5补充证据：独立临时fixture中同ID当前Prompt替换为固定服务契约后，resolver指纹不变而服务错误放行。最小修复必须绑定训练/eval冻结Prompt及摘要并拒绝当前定义漂移；这项完整性门不因兼容策略选择而省略。当前未改生产代码，独立发现及后续裁决见第43节。

2026-09-13 M8最终冻结代码复审完成：f1b7d8a3→ab5c71ae共125提交/149文件，独立整合11 passed/exit0及物理Prompt只读核查通过；整包驳回修改，保留M8-R5 P2，前序R1–R4/历史局部结论有效。同ID漂移拒绝属于已确认完整性要求，可先修复；仅兼容策略依赖用户裁决，不阻塞full/holdout等独立工作。

2026-09-13 M8本轮收尾：Mac冻结ab5c71ae整仓2647 passed/11 skipped，452.07秒且正常exit0；skip原因单独复核为10项缺V3本机fixture、1项缺V4.1本机数据。四份交付文档及52本地链接检查完成，独立核查已保留R5两反例和整包驳回。Linux提交实物Prompt与Mac回归的轻量证据后bundle回传；原main/源产物、Mac用户未跟踪文件和stash保持。下一步同ID漂移完整性修复；服务兼容策略待用户裁决，full/holdout实际输入接线继续按依赖推进，M8不关闭。


2026-09-13 M8-R5实施确认（Codex）：用户回复“可以”，批准服务analysis采用训练及通过评测时冻结并验签的Prompt，现有输出、评分、生成/重试、evidence和准入门保持。Spec已先行记录并单独提交；本计划复核后继续既有授权。

精确范围：pipeline/model_registry.py校验训练/评测/当前Prompt一致并纳入fingerprint，提供从绑定派生服务契约的共享函数；pipeline/server_proxy.py使用该契约并在加载后复验；pipeline/scripts/serve_smoke.py按同一绑定构造请求并验证动态契约摘要。tests/test_eval_run.py只扩充真实证据fixture的显式Prompt输入，tests/test_serve_smoke.py覆盖concise完整CPU链、当前/冻结漂移、加载时漂移、字段不兼容、实际FastAPI请求/重试与smoke；复跑现有契约/交付/Registry/恢复相关测试。必要文档仅同步versioning/SCRIPTS.md及四份任务证据，不修改已发布Prompt或底层业务契约。Mac代码提交后bundle同步既有隔离checkout，Linux分进程CPU回归及轻量证据提交回传；独立reviewer复核代码/操作说明/证据。真实GPU/full/holdout/硬盘缺口保持，不push/merge。

2026-09-13 M8-R5代码de1b51dd完成Mac范围：受影响7文件195 passed/1 skipped、193.63秒/exit0，新增冻结专项5 passed/exit0；独立25+5项及操作说明通过。用户确认的Spec789fa4fc/Plan511cfc14有效，代码经3提交bundle同步隔离分支，Linux按两个进程验证同7文件，实际结果见第44节收尾。整体迁移、full/holdout及真实环境限制保持。

2026-09-13 M8-R5最终验收：Linux第一组97 passed/1 skipped、99.72秒/exit0，第二组103 passed、115.60秒/exit0，合计200 passed/1 skipped；代码两端de1b51dd一致，7保护文件不变，原main干净。本轮R5已解决，最终双机证据和4文档核查后在Linux原子提交回传Mac。第43节整包驳回是历史完整审查结论，不以本次局部通过覆盖；下一步full/holdout实际输入接线及最终完整验收，GPU、硬盘/大型产物限制保留，M8不关闭。


2026-09-13 M4 full/holdout接线启动（Codex）：用户要求“补齐吧”。只实现和用隔离CPU数据验证，不取得真实holdout/重训授权。已核实两个前置：full训练证据当前只承认fold0/1/2，需确认独立full训练范围；holdout必须按已确认设计先媒体推理、后授权评分、普通导出只公开aggregate，不能把真值混进输入快照。先行局部修复限定versioning/cli.py和tests/versioning/test_cli_holdout.py：data claim在冻结预注册前校验完整四元组，避免错误参数留下不可变冻结文件，发布后仍复验。该步骤不改变claim身份/生命周期或数据布局；后续完整接线具体范围在决策确认后补入，不将参数可接受当作实现完成。


### M4 全量训练与 holdout 实际接线（2026-09-13）

用户明确答复“接受，增加独立全量训练范围”，前述待确认已解除；沿用“补齐吧”的实施授权，Spec 0bf0baed。先完成独立 full 训练来源与证据，再完成 holdout 的媒体推理、受限评分和 aggregate 导出，最后独立审查及两机隔离 CPU 验证。真实训练/GPU、真实 holdout 构建或读取、push/merge 均未授权。

精确文件范围：`finetune/train_build_dataset.py`（开发候选去重全量输入）、`finetune/train_prepare_run.py`（冻结/执行/导出 full）、`versioning/mlflow_train.py`（显式范围、父 Run 单次 full 事实）、`versioning/registry.py`（full 来源及产物证据）、`versioning/cli.py`（显式入口及冻结前身份检查）、`finetune/eval_run.py` 与新增 `finetune/eval_holdout.py`（实际 full/holdout 执行、媒体与评分分离、受限细节与公开 aggregate）、`versioning/holdout.py`、`versioning/mlflow_eval.py`（授权衔接）。测试限定 `tests/versioning/test_cli_holdout.py`、`tests/versioning/test_mlflow_train.py`、`tests/versioning/test_registry.py`、`tests/test_train_with_contract.py`、`tests/test_eval_run.py` 及新增 `tests/test_full_training.py`、`tests/test_eval_holdout.py`。操作说明增补 `versioning/SCRIPTS.md`、`finetune/SCRIPTS.md`，状态同步本 Plan、`docs/project-todo.md`、`docs/results/version-control-migration/verification.md`、`docs/results/version-control-migration/handoff.md`（B0–B12实施台账已标为历史范围，保持原文）；保留用户未跟踪 agent-handoff.md、stash、原训练机项目和所有正式产物。

实现选择：full 配置显式与三折区分，开发样本按媒体身份去重且标签冲突拒绝，冻结原六份划分来源以便核查；全量配置不开放训练中验证/隐式拆分，不擅自选择 epoch、seed 或其他训练日程。full 产物使用 full/adapter，MLflow 父 Run 记真实结果，禁止 fold 子 Run 和折结果改名。Registry 同时验证冻结范围、结果、权重摘要和模型来源范围。holdout 延续已批准的 media/evaluation_inputs/sealed_ground_truth/authorization 布局，预注册规则及阈值与冻结执行配置严格匹配，真值与逐样本评分不进入普通 MLflow artifact 或公开导出；消费遵守已有先写 consumed 后完成状态的顺序。

Proof：合成数据端到端覆盖 full prepare→run→export→model register 及 full holdout prepare→inference→score→export；验证三折输入/结果不变、重复标签冲突、范围混用、输入/权重漂移、失败状态、未授权真值访问、预注册身份/规则不符、跨身份恢复、消费后复用、公开产物无真值或逐样本明细。CPU 测试替换实际模型/tuner 回调，不能据此宣称真实训练效果或真实安全部署验证。先保留有效失败证据，修复后跑受影响回归，再由独立 reviewer 对照实际代码核查入口、失败路径和操作说明。Linux 仅使用现有隔离工作区及 CPU 环境；证据记录实际退出码，分进程避免既有 MLflow 句柄累计问题。


M4 holdout 接线细化：`eval prepare` 接收 `--pre-registration`/`--executor` 并要求先以 data claim 冻结；`eval run` 仅执行媒体推理，新增 `eval score --executor` 明确进入受限评分。冻结媒体清单使用 `evaluation_inputs/manifest.json`，包含完整 data/split、开发版本、来源隔离与划分核验以及无标签样本；受限标签仅由 score 读取 `sealed_ground_truth/labels.json`。逐样本推理/评分及读访问记录位于权限0700的执行私有目录，不上传普通MLflow；公开证据是身份、权重与规则绑定、aggregate和执行摘要。同一身份中断后仅复用已完整落盘并验签的阶段结果，不重跑已评分推理或清空claim；已消费完成只允许验签/导出。此拆分落实已确认的先媒体推理后授权评分，不新增真实数据使用授权。


2026-09-13 M4 full/holdout 实施进展（Codex）：full 数据/执行/证据及model登记已接通。独立训练审查发现2项P2（full完成半提交恢复、旧三折导出字节兼容），均修复，独立5项通过并局部复审通过；Mac训练/claim联合44项通过。holdout已增加显式媒体推理和score阶段，合成完整成功/质量失败、身份与规则拒绝、truth读隔离及评分/完成中断恢复9项通过；此前eval/CLI联合109 passed/1 skipped。holdout独立代码/操作说明审查与广回归正在执行，Linux仅完成只读预检：原项目及Codeup main均f1b7d8a3，隔离b40eaa90，tracked干净；尚未同步本轮代码。这里的通过均为CPUfixture，真实GPU、模型效果和HOLDOUT-BUILD继续保留未完成。

M4 文档一致性补充：允许精确更新 `docs/plans/2026-09-01-readable-version-control-design.md` 的训练范围、full来源与验收条款，并以D042记录用户已确认的独立全量训练决定；不重写架构或新增方案。本变更消除原文“模型晋级必须三折完整”与已确认full训练范围的冲突；同样交由独立reviewer对照Spec和实际实现核查。


2026-09-13 M4 full/holdout代码收口（Codex）：代码提交fed9bcfc；训练2项P2已复审闭环，holdout链接提前读truth的P2和伪造评分阶段恢复的P1（含完整私有文件伪造强化反例）已修复。无评分承诺时必须在授权score核对原source truth与快照并复算全部明细，之后才建立不可变承诺；已承诺恢复不重读原truth。独立最终7项通过及局部代码/操作说明通过，设计文档精确同步也已独立通过。Mac广回归679 passed/1 skipped、exit0，最终holdout另16 passed/exit0；广回归开始早于holdout最终修复，不能冒充全部在最终holdout版本复跑。Linux隔离工作区已验签bundle并快进到fed9bcfc，第一组163 passed/1 skipped、exit0；第二/三组及最终保护文件复验待完成。正式项目与真实产物仍只读，整体M4及迁移不关闭。


2026-09-13 M4 full/holdout双机证据收口：Linux同一fed9bcfc三组163/390/266 passed（共819 passed/1 skipped）全部exit0；既有AnyIO弃用告警保留，未改环境。12份代码/操作说明摘要一致，7份保护文件前后一致，原项目仍干净main@f1b7d8a3。仅Plan 0666462d在测试后另以单文件0/1提交快进，代码未变。设计、TODO、Plan、verification、handoff按第45节最终证据同步；独立最终证据核查后在Linux提交轻量文档并回传Mac。实现接线缺口已补齐，M4仍须真实训练/GPU/评分证据，HOLDOUT-BUILD未执行；下一步完整差异审查，整体迁移不关闭。

2026-09-13 本轮最终文档/证据独立核查通过：两端原日志、退出码、摘要与保护状态均一致；4处当前状态残留已修正并复核。仅局部验收通过，下一步仍为M8整包差异审查；轻量文档提交与回传由RUN docs-commit.json及Git历史追溯。

2026-09-13 M8完整差异复审进行中（Codex）：按既有M8范围冻结f1b7d8a3→e1d70c58全部138提交/152文件，独立reviewer执行完整差异和Spec矩阵核查，Mac最终整仓CPU回归并行执行。Codeup main已从Mac配置的远端只读刷新，双机原/隔离工作区及七份保护文件核验通过；不改变运行代码，不访问真实truth/GPU。本轮证据追加verification第46节，并同步TODO和handoff；审查与测试未结束前不写整包通过。

本轮整包审查新增M8-R6（P2）前置：外部adapter权重未纳入冻结输入，准备后漂移仍可执行并登记full模型；先保留反例并完成本轮审查，修复验收要求见TODO同标识。另发现finetune/README.md与entrypoint-map.md仍写full/holdout拒绝，按既有文档范围同步至实际入口并交独立核查。本轮不修改冻结运行代码。

2026-09-13 M8本轮完整审查收口：独立核对f1b7d8a3→e1d70c58共138提交/152文件，结论驳回修改；M8-R6两类外部训练权重漂移已由独立CPU反例证实，文档P3已校正待最终核查。独立34项整合回归及full→holdout→备份异根恢复→服务准入探针均exit0。Mac整仓2686 passed/1 failed/11 skipped、exit1（504.68秒，进程571.311秒）；单项通过及三文件组合失败证实M8-R7导入顺序问题。当前运行代码保持冻结，下一步先修M8-R6/M8-R7再回归及局部独立复核；真实环境与push/merge边界不变。

本轮六文档与第46节最终证据独立核查通过，文档P3闭环；M8-R6/M8-R7仍未修复，整包驳回结论保持。原始Mac证据已验签存档到Linux隔离目录，轻量文档在Mac提交后按既有授权bundle快进隔离分支，具体版本由Git历史及RUN sync-receipt.json追溯。

2026-09-13 M8-R6/R7当前实施（Codex）：选择已批准fail-closed路径，非null外部adapter/checkpoint在准备前拒绝，既有冻结记录在validate/run以及Registry训练证据门拒绝；测试使用合成旧记录验证不能登记ModelVersion。路径优先级测试改为新Python进程验证入口自身设定，运行时真实模块来源门保持。Mac定向179项和原先导入顺序组合1项通过；独立代码/操作说明局部复核已通过，整仓CPU正在运行，暂不关闭R6/R7。现行训练参数边界同步versioning/SCRIPTS.md，证据待写verification第47节。

M8-R6/R7实机隔离CPU进度：代码d9ec1227在Mac定向及独立局部审查后原子提交，bundle SHA 3dd5f2d321ae1cf59c6baeb17ce184741f1326101b8ce47573939b41f7dbe257；Linux仅隔离工作区0/1快进，同五文件SHA一致。Linux新环境两进程179 passed/exit0和顺序1 passed/49 deselected/exit0；七份保护文件及原项目main保持。Mac整仓仍运行，最终文档与整包复核未完成。

2026-09-13 M8-R6/R7最终验收：Mac同一代码`d9ec1227`整仓2694 passed/11 skipped（pytest 774.28秒，进程实际exit0），原导入顺序组合1 passed/49 deselected/exit0；Linux隔离分支训练/full/Registry 179 passed/exit0及顺序1 passed/49 deselected/exit0。独立reviewer复用上轮未变差异的完整审查证据，确认五文件修复及原始adapter/checkpoint反例均闭环，对Codeup main `f1b7d8a3` 至 `d9ec1227` 的140提交/152文件更新整包代码差异审查结论为通过；具体日志摘要与范围见verification第47节。R6/R7已解决本轮范围；M8父任务仍进行中，真实训练/GPU效果、授权新holdout及评分、真实硬盘/大型产物和外部依赖整机恢复未验收。下一步完成当前证据交付和双机隔离同步，再按TODO处理真实环境依赖；未获merge/push授权。

本次四份最终文档的追加独立复核因reviewer用量限制未返回结论；仅主Agent完成本地一致性与链接检查，后续可按第47节证据补做独立文档核查。已完成的独立整包代码审查不因这次工具错误改写。

本轮轻量文档`c3685578`经bundle SHA `ce4e77f8cb5182e96827304d582b49064056c40b55417b2281a0bd3c7dee3305`仅快进Linux隔离分支，`docs-sync-receipt.json`记录四文件范围、原正式项目干净及七保护文件不变。后续文档状态更新仍需按同一隔离同步纪律交付；真实环境验收和四文档独立补核保持待办。
