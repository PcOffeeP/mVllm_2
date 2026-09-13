# 可读版本控制正式迁移实施计划

- **Task ID**：`2026-09-07-readable-version-control-migration`。
- **上游**：[Intent](intent.md) 确认提交 `3dae30a0`；[Spec](spec.md) 确认提交 `6996d35d`。
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
| M4 | 三折训练及validation执行接线、双机CPU范围验收完成；代码7cb24398、证据7a750065。full/holdout实际读取与真实注册模型成功路径未验证，保持未关闭 |
| M5 | 进行中（Codex）：server_proxy实际加载、registry管理、交付校验及smoke已接线；本机联合179项与后续最终服务专项41项通过，独立审查通过本轮代码与本机证据范围；Linux最终41项通过；真实模型成功路径未验证，真实环境依赖继续保留（verification第32节） |
| M6 | 部分验收通过（store级恢复已完成，真实硬盘/大型产物待验收）：Mac/Linux109项通过，实际SSH往返、错误摘要拒绝和原隔离路径联合恢复通过；独立证据核查通过，真实硬盘/大型产物未验证；M8-R4 store级异根恢复已由2fce3ab1完成并通过Mac/Linux及独立局部验收，真实硬盘/大型产物与外部依赖整机恢复仍未验收（verification第33、39、41节） |
| M7–M8 | M7a完成（881c8181）：三个数据旧CLI退役，数据手册与入口索引同步，本机/Linux各57项通过、独立审查通过；M7b本批完成（60dd00bc）：四个旧训练/评测CLI退役及ARCHITECTURE/finetune文档收敛，双机证据见verification第35节；M7c本批完成（09035fd4）：旧queue写入退役、ROI显式路径及文档同步，两端验证见verification第36节；M7d本批完成（15b44009）：7个辅助CLI退役，验证见第37节；M7e本批完成（cc02acc1）：旧Prompt CLI退役、历史索引工具显式根及文档同步，两端179项通过/独立核查通过（第38节）；历史库保留。下一步M8完整Spec矩阵、源保护及Codeup main全部差异审查、交付材料。M8进行中（Codex）：f1b7d8a3至0963642b全量117提交/148文件独立审查，整仓CPU基线2603 passed/11 skipped；整体审查驳回，M8-R1代码3b63aa52完成、本机整仓及独立局部审查通过，Linux分三进程956 passed/1 skipped、各exit0，R1本轮范围已解决；M8-R4 store级异根恢复已解决本轮范围（代码2fce3ab1，Mac/Linux及独立局部验收，第41节），M8-R2 Prompt并发及M8-R3训练半提交已解决本轮范围（2b8cbc89）：Mac/Linux各466项、独立251项通过。历史汇总实物已交付（21条，verification第42节），handoff已补当前矩阵。真实环境缺口保留；未授权push/merge |

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
