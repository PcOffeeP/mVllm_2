# 可读版本控制正式迁移实施计划

- **Task ID**：`2026-09-07-readable-version-control-migration`。
- **上游**：[Intent](intent.md) 确认提交 `3dae30a0`；[Spec](spec.md) 确认提交 `b1aaf315`（承接31d20154；用户确认逐折执行与证据复用）。
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

来源未指定与实际构建入口未接通阻塞HOLDOUT-BUILD。当时HOLDOUT-METRICS先记录待确认；用户随后确认按七项原门槛补齐，Spec55b3f4d4及下文专门实施批次承接，当前代码f1be1060已局部独立审查通过，双机最终验证见第49节。MODEL-DIAG可复算已有开发预测，但concise缺失和历史visual权重断链阻塞新推理；找到精确备份位置后只读核验，不全盘搜寻或恢复覆盖产物。

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


## HOLDOUT-METRICS 实施批次（2026-09-13）

用户已明确要求按原七项门槛补齐；Spec确认提交55b3f4d4。精确代码范围：新增`finetune/holdout_metrics.py`集中原定义与冻结阈值、私有指标和公开gate聚合；修改`finetune/eval_run.py`仅为full配置路由到七门校验；修改`finetune/eval_holdout.py`贯通准备、评分、恢复、公开证据及下游校验，并将新模块加入冻结实现摘要。不改validation评分、源数据或历史对象。

精确测试范围：新增`tests/test_holdout_metrics.py`，修改`tests/test_eval_holdout.py`的合成四状态fixture及全链路断言；若共享fixture调用者受影响，仅修其必要断言并在证据列明。文档范围沿既有TODO/Plan/verification/handoff，加`versioning/SCRIPTS.md`及`finetune/SCRIPTS.md`的指标说明/模块索引。

先验证七门完整性、固定阈值与比较方向；用合成四状态原记录与历史f04ca7cb评分函数逐项对照（包括缺类、非法、runtime失败和边界），确认validation不变。再验证媒体推理不读truth、授权score、质量失败后consumed、完成中断恢复、私有评分重验、公开无数值指标泄漏及Registry准入拒绝篡改。旧泛化full配置不能自动改写为七门。

本机按受影响套件验证并取得独立reviewer局部审查；代码提交后沿既有bundle授权核对双机独有提交和保护文件，仅快进隔离checkout，在Linux现有CPU环境分进程复跑受影响套件。记录实际退出、日志SHA、实际执行代码和机器；不重复未变化的整包审查与模型实验。新批完成后更新验收状态，真实holdout来源/构建、GPU和硬盘缺口保留。Spec确认仅涵盖本批七门；实现沿用户“补齐”的明确授权，不要求再次批准同一取舍。


HOLDOUT-METRICS本批收口：代码f1be1060及两入口说明局部独立审查通过；Mac614 passed/1 skipped、两进程exit0，Linux首组207/1skip加拆组167+240、三进程exit0。Linux原单进程合并组文件句柄限制失败保留（第49节），不改系统限额，不重复首组或旧整包审查。原200组合成定义差分一致，私有指标/公开gate篡改拒绝。当前按TODO的独立source、实际构建、模型原件与真实环境依赖推进；新的七门能力不代表真实holdout或模型质量已验收。


2026-09-13 续办只读准备：Mac基线0d8a9f55，HOLDOUT-BUILD核查深入到审查导出及发布两层development过滤，消费端媒体/真值schema定位完成。待决推荐为独立holdout审查/构建、全量人工审查与受限输出分离，详见verification第50节。此段仅记录发现和依赖，不批准公共接口或数据流扩展；确认后先修订Spec，再确认实现Plan。七项指标既有批准及已完成验证保持；真实source/非语义隔离清单未指定，不执行真实构建或测试使用。


## 2026-09-13 test 数据分支实施批次

上游Spec042f335e，用户已明确确认方案并要求继续实施。现行叙述采用train/test数据分支，代码标识和历史记录保持原样。精确范围：新增`versioning/holdout_pipeline.py`与`tests/versioning/test_holdout_pipeline.py`；修改`versioning/data_pipeline.py`（共享审查导出可选择全部test候选）、`versioning/cli.py`（显式用途与test配置路由）、`finetune/eval_holdout.py`（构建证据绑定）、`tests/test_eval_holdout.py`（新发布到最终模型测试的合成接线），以及`versioning/SCRIPTS.md`、TODO、handoff、verification。其他长期文档仅做用户要求的叙述术语映射，不替换代码标记、配置值、路径或历史身份。

顺序：先增加显式test配置（冻结train版本、train/历史测试source身份与摘要清单），在owner-only独立工作区复用source/ROI/子视频算法；然后全量人工审查往返、媒体/真值分离发布与只读校验；最后接最终full模型测试并完成受影响回归、独立代码及入口说明核查。发布前后核验相同输入、source隔离、媒体内容、审查完整性，已发布内容和授权事实不可覆盖。训练及测试消费不由数据命令自动启动。

Proof：合成fixture验证七阶段、缺审/篡改/跨分支/身份或内容重叠拒绝、受限权限、公开数据无标签、同操作重试与冲突保留、最终模型测试从真实构建器产物消费及claim时序；train已有链路定向回归。只在本机或Linux隔离目录执行CPU测试，记录实际exit及机器/代码版本。真实数据/模型效果、硬盘和受限测试使用均保留未验收；本批不push或merge。


本批代码abafdbf2已完成test分支处理、全量人工审查、封存发布及最终full测试接线；Mac427 passed/1 skipped、两组exit0，独立局部代码与入口说明核查通过，原P1/P2及权限/只读验证修复已闭环，见verification第51节。历史七门评分批次的双机证据不作本批复跑；本次尚未同步Linux。下一步提供新test source、非语义隔离清单和适用真实构建授权后进行训练机媒体/审查/封存验收；模型权重缺失仍阻塞MODEL-DIAG，真实训练、测试使用、删除与push/merge边界保持。


2026-09-13 Linux续办：用户授权第一步隔离验收与第二步训练机既定划分调查。隔离分支经bundle0/5快进至7b0e01d5，仅task checkout，正式main未动；同代码两组265、162/1skip各exit0。既定test21/train89来源和隔离已定位，21视频存在；旧测试claim/exposure及20source媒体凭据关联已记录，video_0005无该批候选。下一步核清使用资格及输入证据，不要求重新指定已找到路径、不擅自改划分或复用受限测试。精确Linux证据目录为`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/test-branch-verification-20260913/`，详见verification第52节。本次只有CPU合成验证和非语义只读调查，原真实数据/模型/删除/push及正式main merge边界保持。


2026-09-13 test使用资格只读续查：用户已授权限定范围身份调查。当前数据目录和已发现的pre-semantic-portal-20260723备份中共6个媒体receipt集合，均无video_0005；18份manifest/identity已按非语义字段核对。迁移清单只列source、derived、training_releases→releases，不覆盖sealed_test_releases；这说明verified不证明旧test发布已迁移，不能据此认定删除原因。未找回299样本的完整发布身份清单，现阶段21个source的独立使用资格均为“证据不足”，并非“全部未用”；其中20个已有与暴露release相关联的物化证据。run_identity的初始化状态不能覆盖后续gate的completed/exposed事实。下一步最小缺失材料是旧发布的无标签candidate/source清单或对应备份；不扩大读取受限语义、不重划分或放行复用。详见verification第53节。


2026-09-13 MODEL-DIAG限定目录续查：Linux只读目录与路径stat实际exit0。evidence_archive顶层5组名称不含目标concise/visual三折；现存concise-v1仅input/reference、concise-v2仅input，不能替代concise-cv；/data/mVllm_2/workspace仅data、finetune仅active_data_release.json。六个约定三折merged目标仍不存在。未检查其他发布库内容或全盘备份，不能断言模型全部丢失；没有读取权重/预测/test内容或重跑既有评分。下一步需目标身份绑定的模型/原始预测备份，或另行确认诊断方案；test资格阻塞不取消MODEL-DIAG，也不授权重训。证据见verification第54节及docs/results/model-location-followup-20260913.json。


2026-09-13 MODEL-DIAG发布库身份及恢复目标：Linux只读release-manifest核查exit0，已知legacy发布库只有v4.1-agent-pipeline-fold0-r1，origin为coverage-first单折实验，不能替代concise/visual三折。已从历史concise报告提取三折summary/records共6个SHA256恢复比对目标；尚未找回文件，报告摘要不是原件或模型权重的独立证明。已知位置线索核查到此收束，等待准确备份路径/迁移记录；不重复扫描、重训或擅自改用其他模型。详见verification第55节。


2026-09-13 条件清理授权（Codex）：用户明确旧数据和旧训练run/模型两类均包括，只删除已验证完整迁移且不再需要的旧副本。本轮Linux预检exit0：历史迁移source_root已不存在；pre-semantic备份不在该迁移清单映射内；旧LlamaFactory顶层16个模型软链接，10个目标存在、6个断链，不能当作重复权重。workspace/runs包含迁移后的实际目标，当前发布库保持保护。删除白名单为空，实际删除0、释放0字节；不是授权缺失，而是完整迁移/冗余性证据未满足。后续先建立旧备份到保留位置的逐文件映射、内容一致性和引用退出证明，再在本次条件授权内清理；不继续索取缺失三折模型备份，不把此次决定解释为取消MODEL-DIAG或TEST-POLICY。


2026-09-13 train原视频清理候选：按用户条件授权在Linux核对旧备份01_videos到workspace/data/source/videos，89个train视频逐文件大小/SHA256一致，共5852142357字节（约5.45GiB），21个test视频未读内容。两工作区tracked运行代码/配置未见该备份路径引用。删除程序的占用预检遇到不可读/proc文件句柄，实际exit1且发生于首次unlink和证据目录创建之前；sudo -n只读能力探针要求密码，未提权。删除0、释放0，旧副本保留。候选清单与完整程序已保存；后续完成有权限的占用检查后再沿用授权执行，不能把候选已验签写成已删除。


## 2026-09-13 已确认：工程分支收口与模型交付拆分

用户确认先整理合并前/后续模型/非阻塞清理三类清单并提出新的模型诊断方案。沿用Intent“迁移成功不表示模型质量达标”和Spec的服务接管/模型可用性分别验收；不改变完整身份、数据语义、七门、一次性测试或Registry门禁。工程交付以约定范围验收、用户批准集成、合并Codeup main并核验落点为终点；本次确认不直接授权push/merge。

执行顺序：先按TODO收口矩阵将每个剩余真实环境缺口对应到证据与完成条件，明确仍阻塞项；核对当前train版本及外部媒体依赖，整理新增代码相对已审基线的差异；准备最终PR范围、必要验证与独立审查。保持已有审查冻结范围，不因文档增加重复整包历史修复。最终集成前刷新目标远端与两机状态，核对独有提交和精确目标后申请push/merge执行授权；获准合并后核验main提交、两机同步和适用冒烟。当前并不宣称可以立即合并。

模型任务保留HOLDOUT-BUILD、MODEL-DIAG、FINAL-TRAIN、MODEL-QUALITY原标识及父子依赖，最终模型质量不是本工程分支默认硬门槛。真实GPU/服务成功路径的工程验收缺口不得自动转为已完成：逐项明确如何补证或由用户接受转交边界。大型/外部依赖恢复缺口同理保留，移动硬盘既有允许单独未完成的决定保持。

清理MODEL-ARCHIVE移至非阻塞配套；原条件删除授权保留，89个train原视频候选未删除，不继续以清理占用检查阻塞主线。精确文件范围仅本Plan、TODO、handoff、verification；诊断方案草案存于现有TODO条目，尚不修改训练配置或代码，不创建平行任务台账。


2026-09-13 train真实输入预检：Linux隔离bb73e4dd执行正式build_versioned_datasets(scope=full)，实际exit0；data-v4.1-r2 + prompt-v4.1-r1 + 原workspace/data媒体根成功生成内存输入。三折train/validation为1253/425、1014/664、1186/492，full为1678，唯一媒体1678个共165485727字节逐一哈希；媒体名提取source与既定21个test ID无交集，此项不代替内容隔离或test资格。没有Run写入、训练或GPU执行。完整结果摘要见docs/results/train-input-preflight-20260913.json及verification第59节。


2026-09-13 M4配置/资源预检：基座路径models/minicpm_v_4_5存在并解析到models/minicpmv4_5，config声明openbmb/MiniCPM-V-4_5；仅stat/配置，未验完整权重或冻结修订。4090查询时24564MiB总显存、约1081MiB使用、利用率0%；/data约3.4TiB可用。cpm45有torch/transformers/peft等训练包，但importlib.metadata未发现mlflow分发包；正式适配器在同进程调用run_training，不能假设CPU隔离环境与GPU环境已贯通。公共入口仅cross_validation三折整组或full，没有单折选项；前文“现成单折工程验证”建议收窄为待设计方案。下一步先核对完整执行环境与有限三折工程验证方案，不创建训练版本、不启动训练。


## 当前执行边界纠正（Spec a5cfa86f）

取消将有限真实训练作为本分支默认下一步。按用户最新范围，先核对agent环境与DVC/MLflow执行环境，补齐逐折入口，再验证新体系的身份、记录、导出、恢复及活动入口接管，准备合并材料。真实质量训练及test留后续，旧模型保留且不放宽门禁。逐折接口具体方案待确认；依赖该方案的代码变更暂不执行，其余只读核验与文档维护继续。

本轮基座只读全文件哈希与分片结构核查，保留必要摘要到现有verification，不新增长期结果文件、不写正式训练版本、不删除既有模型文件。上游master不能当不可变修订，本地内容指纹与上游来源证明分别表述。


2026-09-13 环境与部署文件核查：agent/cpm45均无DVC/MLflow；实际安装在隔离.conda-m2（MLflow3.15.2、DVC3.67.1），.venv-m3通过system-site-packages继承。agent pip check exit0，cpm45 exit1且editable LLaMA-Factory指向旧mVllm项目；两个隔离环境pip check均因MLflow要求pandas<3、实际3.0.3而exit1。新增ENV-DEPLOY部署一致性前置，不把历史CPU测试通过解释为依赖声明一致。

## 双平台部署实施批次

承接本次单独提交的双平台部署Spec及用户实施授权。精确文件范围：pyproject.toml、uv.lock、requirements.txt、新requirements-linux-gpu.lock；新增scripts/source_prepare_environment.py、scripts/source_validate_environment.py、scripts/SCRIPTS.md、tests/test_environment_deployment.py；局部更新README.md、finetune/README.md、TODO、handoff、verification。保持LlamaFactory子模块代码、版本身份与训练业务不变。

先统一pandas/MLflow兼容依赖并补cropper/媒体读取包，分别锁定Mac轻量和Linux GPU依赖；实现显式平台/新环境路径安装与doctor，绑定当前Git子模块来源，错误输入fail-closed，不安装系统包；最后做拒绝/失败传播测试、Mac新环境和Linux新隔离环境安装及入口验证。需要网络的安装只写新环境和工具缓存；不安装进agent/cpm45。新脚本和文档接受局部独立审查，保留真实安装失败证据。安装成功不等同模型可用，无真实训练/推理/test。

2026-09-14 ENV-DEPLOY本批已解决：双profile锁定部署与doctor完成，当前代码83724995；Mac新环境安装/doctor exit0、361项定向回归通过、最新部署边界12项通过；Linux新GPU环境通过显式镜像安装/doctor exit0。独立审查发现的P1/P2均闭环，镜像增量复核通过；七保护SHA及正式/原隔离工作区保持。旧agent/cpm45未修补，新环境未正式激活。官方源首轮主动中断exit1及部分环境保留；完整证据第63节。本批不训练、不test、不push/merge。下一步恢复M4-FOLD逐折接口方案确认与工程收口，不再以依赖缺失或重训为默认前置。


2026-09-14 M4-FOLD接口核对完成（e7efb56b，verification第64节）：现有train run忽略已解析的--fold并执行全部冻结配置，不能作为单折入口使用。下一步确认TODO中的显式选折、partial、同父Run续办及完成折验签复用方案，再更新Spec/Plan实施。ENV-DEPLOY不重做；本次无训练、test、远程操作或业务代码修改。


## M4-FOLD已确认实施批次（Spec b1aaf315）

承接用户对逐折规则及工程验证的确认。实施范围：finetune/train_prepare_run.py、versioning/cli.py，必要的versioning训练证据辅助逻辑；tests/test_train_with_contract.py、tests/versioning/test_cli.py及必要单折定向测试；局部更新finetune/README.md、TODO、handoff、verification。不改冻结三折结构或full契约。先接入选择参数，在现有train锁内核对父/子Run与逐折不可变证据，成功缺折partial、三折齐全沿用汇总/完成门；用合成trainer覆盖分次执行、完成折复用、漂移/残留/失败/并发拒绝与full回归，最后独立审查。复用现有partial原生状态映射，界面说明该映射而不改变公共状态契约。真实训练与test不执行。


2026-09-14 M4-FOLD本批工程实现已解决：Spec b1aaf315/Plan902d8c9d、代码61effebd；显式单折、同父Run分次执行、逐折证据验签复用、partial与完整三折完成门已接通。两项P2经独立反例复验闭环，提前汇总拒绝增量复核通过；Linux最终123项合成回归exit0（独立测试工具目录覆盖，非GPU运行锁自带pytest）。详见verification第65节；保留真实训练/服务成功路径与恢复缺口，不改变旧模型质量门。下一步为最终集成范围、审查覆盖及M4/M5/M6补证或转交裁决，不重训、不test、不push/merge。


2026-09-14 最终集成候选核查（基线9077690f，verification第66节）：新鲜Codeup main=f1b7d8a3，任务分支包含全部远端历史及Mac main额外6提交，共181提交/170文件，无远端或训练机遗漏的独有提交。历史整包140提交审查保持，后续41提交按七门/test分支/部署/逐折四批映射到既有独立审查；README e7efb56b操作说明本轮独立核查补齐。修正TODO把已允许后置的真实模型成功路径重复列为待裁决阻塞的问题；真实硬盘/大型产物/外部依赖整机恢复限制继续显著保留。工程候选进入集成准备，实际push/merge、正式工作区同步/解释器激活及合并后验证仍未执行，整体任务须这些完成后才能关闭。
