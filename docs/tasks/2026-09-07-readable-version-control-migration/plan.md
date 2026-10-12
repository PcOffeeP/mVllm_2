# 可读版本控制正式迁移实施计划

- **Task ID**：`2026-09-07-readable-version-control-migration`。
- **上游**：[Intent](intent.md) 确认提交 `3dae30a0`；[Spec](spec.md) 确认提交 `b1aaf315`（承接31d20154；用户确认逐折执行与证据复用）。
- **历史任务分支**：`refactor/2026-09-07-readable-version-control-migration`；本机工作区 `/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2`。
- **目标**：保存已确认的实施范围、选择、完成门及 Proof。工程迁移于 2026-09-14 完成交付；后续任务只在[项目 TODO](../../project-todo.md)维护。
- **确认与执行边界**：本 Plan 的实施已按历次确认与授权执行，最终集成先推任务分支、再快进 Codeup main 至 `5acebc27` 并同步训练机（验证第67节）。本文件保留的施工步骤和 Proof 用于追溯，不是新的执行授权。2026-10-12 仅整理文档与独立核查，不 SSH、不训练或评测。

## 规划基线与当时接入缺口

基础设施承接点为 `1b0d5823`；前序 1399 项 versioning 测试、2082 项整仓测试及独立复核是基础设施历史证据；后续迁移验证按具体代码与机器记录，未在本轮文档整理中复跑。现场观察见[调查记录](../../results/version-control-migration-20260907.md)，不能把文件存在性当作完整性或加载证据。

规划时查明两处关键接入缺口：

- `versioning/data_pipeline.py` 的 `_derive_roi` 从文件名摘要生成 ROI，`run_subvideo` 为每视频生成两条记录；这是已有最小数据链行为，不能承接真实人工 ROI、视频剪裁和采样语义。M3 必须替换正式路径上的该行为，并保留真实业务规则。
- `versioning/cli.py` 的训练处理函数创建、更新 MLflow Run；实际训练仍在 `finetune/train_with_contract.py`，测评仍在 `finetune/eval_run.py`。M4 必须贯通真实调用，而非只补充状态管理测试。

## 已确认文件范围与实施选择

以下保留迁移时确认的精确代码文件集。不得将某个目录整体作为任意修改授权。M0 若发现遗漏的活动入口或底层身份依赖，先记录精确路径并更新 Plan；改变行为或职责时回到 Spec。

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

历史正式产物不原地改名、覆盖或删除；`stash@{0}` 保留。`finetune/active_data_release.json`、`pipeline/model_registry/current.json` 和旧模型 release manifest 作为历史证据保留，活动代码解除对它们的依赖。不存在合格 alias 时不改写旧模型质量结论。

**新轻量输出：** 本任务证据放入 `docs/results/version-control-migration/`，具体文件为 `source-inventory.yaml`、`object-mapping.yaml`、`entrypoint-map.md`、`history-summary.yaml`、`verification.md`、`handoff.md`。这些是映射、历史证据和验证记录，不是新的全局注册表或任务状态库。已确认正式对象的输出路径由完整版本名确定，在 object-mapping 中逐个列明后才允许写入；不预造版本编号。

## 已执行批次顺序与完成门

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

## 最终工程交付矩阵

工程交付按确认范围已解决；详细失败、修复和分组日志保留在[验证记录](../../results/version-control-migration/verification.md)，当前后续动作只查[项目 TODO](../../project-todo.md)。

| 范围 | 最终工程结果 | 验证证据及限制 |
| --- | --- | --- |
| M0–M2：范围、转换及隔离环境 | 源/映射/入口核对、data/Prompt 转换、历史摘要及 Linux 隔离验证完成 | 第12–18节及 source-inventory/object-mapping；不证明全部历史模型可重现 |
| M3：数据处理与人工审查 | 两份发布语义保持、真实媒体小样本对照、双机审查包往返及封存校验完成 | 第19–24节；r1/r2 外部媒体仍引用原 workspace，新 store 不自包含 |
| M4：训练与测评 | 三折、独立 full、正式 validation 与 holdout 推理/授权评分接线完成 | 第25–31、45节；以 CPU 替身和输入预检证明接线，真实训练及模型效果未验 |
| M5：服务准入 | alias/Registry/冻结 Prompt 绑定、实际入口拒绝及 CPU 成功路由完成 | 第32、43–44节；合格真实模型加载、GPU 推理及 HTTP 成功路径未验 |
| M6：备份与恢复 | 跨机小对象传输及 store 级异根联合恢复完成 | 第33、39、41节；真实硬盘、大型权重和外部依赖整机组合恢复未验 |
| M7：逐入口退役 | 旧数据/训练/评测/Prompt/队列/辅助写 CLI 已逐入口停用；业务函数与历史对象保留 | 第34–38节及 entrypoint-map；不能删除整个 legacy 包 |
| M8：独立审查与最终交付 | R1–R7 修复闭环、140提交/152文件完整代码审查通过；后续四批增量独立审查映射及授权集成完成 | 第40–48、66–67节；历史 Mac 整仓 2694 passed/11 skipped，未在本轮复跑 |
| 冻结七门及 test 分支 | 七门原定义接线、独立七阶段审查/封存与最终 full 测试接线完成 | 第49–53节；既定21 source已定位，独立使用资格及真实构建仍缺 |
| 双平台部署 | Mac 轻量/Linux GPU 新隔离环境锁定安装及 doctor 验收完成，代码83724995 | 第62–63节；旧环境未修补、新环境未正式激活 |
| 三折分次执行 | 显式选折、同父 Run、验签复用、partial 和完整汇总门完成，代码61effebd | 第64–65节；合成工程验收，不含真实训练 |
| 集成与模型基线 | MODEL_GATE_BASELINE独立核查后，按授权顺序推任务分支、快进main并同步训练机 | 第67节；历史落点5acebc27，今日训练机现状尚未刷新 |

### 保留的后续限制

真实训练、质量、test 和真实服务成功路径分别由 TODO 中的 MODEL-DIAG / HOLDOUT-BUILD / FINAL-TRAIN / MODEL-QUALITY 跟踪；ENV-ACTIVATION 与 RECOVERY-VALIDATION 承接正式环境和物理恢复缺口。旧指针目标仍待用户裁决，不恢复旧写入；清理不阻塞工程交付，必须满足既有完整迁移、冗余、引用退出和诊断保护条件。

下一轮先刷新训练机只读事实。本轮只完成文档收敛及独立核查，不运行本文件中的施工、测试、训练或评测命令。

## 已确认施工步骤（供实施追溯）

以下保留每阶段的技术选择和停止门，不再用于安排当前下一动作。

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

所有本机命令在上述本机 worktree 执行；训练机命令在已核对的隔离 checkout 中用该环境 Python 执行。以下命令是实施时的 Proof 设计；实际执行版本、机器、结果与限制以验证记录为准，不是本轮测试记录。

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

## 人工审查归属的决定演进（2026-09-12）

用户要求分析历史人工记录reviewer_id缺失，并修复未来人工审查必须补全审查者信息。此授权允许对既有review_candidates_app.py的legacy模式作局部缺陷修复：两模式开始前强制非空审查者标识、界面显示当前审查者、完整汇总前逐条检查作者。已有普通未断裂自动准入规则保持不变，不批量将匿名历史记录归给当前操作者，不改写历史封存对象。实施仅涉及既有允许文件review_candidates_app.py、rebuild_data.py中的继续审查命令提示、tests/versioning/test_data_pipeline.py及对应操作说明/任务证据；不调整共享历史读取/迁移schema。

### 最终确认：单维护者审查归属（取代手填要求）

用户明确确认历史人工审批均由本人完成，并批准默认使用“项目维护者”。新决定自动记录该角色，保留可选显式标识；不以旧记录缺姓名要求重审，不改写原历史记录。23条对象完全匹配的审批可依据本次确认复用，原审查时间保留，补充确认单独记录。人工决定完整性及媒体绑定门禁继续有效。

M7a精确范围：上述三个数据CLI停止历史写入并指向versioning显式七阶段；rebuild_data的旧编排函数仅保留为私有历史测试入口，tests/test_rebuild_source_only.py改为显式调用该私有入口，新的真实CLI拒绝回归放tests/test_data_rebuild.py。不删除artifact_index/artifact_resolver：source_bootstrap、ROI及候选媒体业务实现仍依赖它们。M4/M5的真实成功路径不因工程验收关闭，其他未核定旧入口逐个列证据后处理。

M7b本批精确范围：停用train_build_dataset/train_prepare_run/train_with_contract/eval_run公开CLI，保留新入口直接调用的版本化业务函数及历史私有测试入口；回归在既有允许的tests/test_train_with_contract.py、tests/test_eval_run.py添加或调整。只读复跑tests/test_train_build_dataset.py与tests/test_train_build_source_aware_dataset.py，不改采样、评分或底层训练。ROI/审查/索引辅助入口不在本批退役范围。

M7c精确范围：review_candidates_app公开UI仅接受完整versioning-package，拒绝旧queue写入；roi_annotation_app仍作为ROI输入准备工具，显式要求metadata文件、output和project-root，不再在导入或参数处理中选择current/LATEST。历史解析器仅保留私有测试，ROI几何和人工决定业务不改。tests/test_roi_annotation_app.py加入该入口的精确回归范围，review回归复用tests/versioning/test_data_pipeline.py。索引库仍有历史业务依赖，保留而不删除。

M7d精确补充：允许修改pipeline/scripts/roi_freeze_decisions.py、roi_materialize_videos.py、subvideo_build_plan.py、subvideo_materialize_media.py、review_build_queue.py、review_build_phase2_queues.py、review_route_from_history.py，停止其公开CLI写入并指向versioning显式七阶段。versioning无上述脚本调用，保留历史私有main及解析器、业务库；回归新增在已允许tests/test_data_rebuild.py，复跑六个相关历史CLI测试及tests/versioning/test_data_pipeline.py。不变更几何、采样、分流规则或历史对象；不删除索引库。

M7d文档与历史测试补充：tests/test_subvideo_build_plan.py中的旧dry-run语义测试显式调用私有_legacy_main（既有真实数据缺失时仍skip，不当作通过）；允许docs/INFERENCE_SERVICE_RUNBOOK.md仅追加历史适用范围与现行服务链接，不重写历史操作或效果证据。

M7e精确补充：修改pipeline/prompt_control/__main__.py停用旧validate/publish公开CLI，历史main私有保留，不改core或__init__导出；模块启动先完成既有包导入，但不得解析/读取旧source或调用publish。修改pipeline/scripts/build_artifact_index.py，历史INDEX.md报告工具必须显式--data-root且目录存在，不再选择current根，不更改底层集合索引。新增回归在tests/test_prompt_control.py和tests/test_artifact_index.py；核对tests/versioning/test_prompts.py及test_cli.py。versioning/SCRIPTS.md补Prompt现行参数说明并将过期legacy不变条款同步为既定逐入口退役边界。

M7e文档精确补充：pipeline/prompt_control/README.md仅追加历史范围与现行Prompt链接，保留原历史说明；README/finetune说明/项目指南同步旧Prompt停用与新定义入口，不改变历史Prompt正文。

M8-R1精确测试补充：`tests/versioning/test_cli_holdout.py`随公共手工写入口停用更新，验证合法claim也不能由手工状态消费；既有低层holdout状态/消费故障测试继续保留。训练证据保存为实际父Run的`training-evidence.json` artifact及只写一次的摘要param，不产生新正式身份或全局索引。

M8-R5补充证据与已确认方案：用户确认采用训练及通过评测时冻结并验签的 Prompt，输出/评分/生成/重试及准入门保持。独立临时fixture中同ID当前Prompt替换为固定服务契约后，resolver指纹不变而服务错误放行。最小修复必须绑定训练/eval冻结Prompt及摘要并拒绝当前定义漂移；这项完整性门不因兼容策略选择而省略。该发现及后续裁决见第43–44节，修复已闭环。

精确范围：pipeline/model_registry.py校验训练/评测/当前Prompt一致并纳入fingerprint，提供从绑定派生服务契约的共享函数；pipeline/server_proxy.py使用该契约并在加载后复验；pipeline/scripts/serve_smoke.py按同一绑定构造请求并验证动态契约摘要。tests/test_eval_run.py只扩充真实证据fixture的显式Prompt输入，tests/test_serve_smoke.py覆盖concise完整CPU链、当前/冻结漂移、加载时漂移、字段不兼容、实际FastAPI请求/重试与smoke；复跑现有契约/交付/Registry/恢复相关测试。必要文档仅同步versioning/SCRIPTS.md及四份任务证据，不修改已发布Prompt或底层业务契约。Mac代码提交后bundle同步既有隔离checkout，Linux分进程CPU回归及轻量证据提交回传；独立reviewer复核代码/操作说明/证据。真实GPU/full/holdout/硬盘缺口保持，该局部批次不包含 push/merge；后续最终集成另按授权执行。

### M4 全量训练与 holdout 实际接线（2026-09-13）

精确文件范围：`finetune/train_build_dataset.py`（开发候选去重全量输入）、`finetune/train_prepare_run.py`（冻结/执行/导出 full）、`versioning/mlflow_train.py`（显式范围、父 Run 单次 full 事实）、`versioning/registry.py`（full 来源及产物证据）、`versioning/cli.py`（显式入口及冻结前身份检查）、`finetune/eval_run.py` 与新增 `finetune/eval_holdout.py`（实际 full/holdout 执行、媒体与评分分离、受限细节与公开 aggregate）、`versioning/holdout.py`、`versioning/mlflow_eval.py`（授权衔接）。测试限定 `tests/versioning/test_cli_holdout.py`、`tests/versioning/test_mlflow_train.py`、`tests/versioning/test_registry.py`、`tests/test_train_with_contract.py`、`tests/test_eval_run.py` 及新增 `tests/test_full_training.py`、`tests/test_eval_holdout.py`。操作说明增补 `versioning/SCRIPTS.md`、`finetune/SCRIPTS.md`，状态同步本 Plan、`docs/project-todo.md`、`docs/results/version-control-migration/verification.md`、`docs/results/version-control-migration/handoff.md`（B0–B12实施台账已标为历史范围，保持原文）；保留用户未跟踪 agent-handoff.md、stash、原训练机项目和所有正式产物。

实现选择：full 配置显式与三折区分，开发样本按媒体身份去重且标签冲突拒绝，冻结原六份划分来源以便核查；全量配置不开放训练中验证/隐式拆分，不擅自选择 epoch、seed 或其他训练日程。full 产物使用 full/adapter，MLflow 父 Run 记真实结果，禁止 fold 子 Run 和折结果改名。Registry 同时验证冻结范围、结果、权重摘要和模型来源范围。holdout 延续已批准的 media/evaluation_inputs/sealed_ground_truth/authorization 布局，预注册规则及阈值与冻结执行配置严格匹配，真值与逐样本评分不进入普通 MLflow artifact 或公开导出；消费遵守已有先写 consumed 后完成状态的顺序。

Proof：合成数据端到端覆盖 full prepare→run→export→model register 及 full holdout prepare→inference→score→export；验证三折输入/结果不变、重复标签冲突、范围混用、输入/权重漂移、失败状态、未授权真值访问、预注册身份/规则不符、跨身份恢复、消费后复用、公开产物无真值或逐样本明细。CPU 测试替换实际模型/tuner 回调，不能据此宣称真实训练效果或真实安全部署验证。先保留有效失败证据，修复后跑受影响回归，再由独立 reviewer 对照实际代码核查入口、失败路径和操作说明。Linux 仅使用现有隔离工作区及 CPU 环境；证据记录实际退出码，分进程避免既有 MLflow 句柄累计问题。

M4 holdout 接线细化：`eval prepare` 接收 `--pre-registration`/`--executor` 并要求先以 data claim 冻结；`eval run` 仅执行媒体推理，新增 `eval score --executor` 明确进入受限评分。冻结媒体清单使用 `evaluation_inputs/manifest.json`，包含完整 data/split、开发版本、来源隔离与划分核验以及无标签样本；受限标签仅由 score 读取 `sealed_ground_truth/labels.json`。逐样本推理/评分及读访问记录位于权限0700的执行私有目录，不上传普通MLflow；公开证据是身份、权重与规则绑定、aggregate和执行摘要。同一身份中断后仅复用已完整落盘并验签的阶段结果，不重跑已评分推理或清空claim；已消费完成只允许验签/导出。此拆分落实已确认的先媒体推理后授权评分，不新增真实数据使用授权。

M4 文档一致性补充：允许精确更新 `docs/plans/2026-09-01-readable-version-control-design.md` 的训练范围、full来源与验收条款，并以D042记录用户已确认的独立全量训练决定；不重写架构或新增方案。本变更消除原文“模型晋级必须三折完整”与已确认full训练范围的冲突；同样交由独立reviewer对照Spec和实际实现核查。


## HOLDOUT-METRICS 实施批次（2026-09-13）

用户已明确要求按原七项门槛补齐；Spec确认提交55b3f4d4。精确代码范围：新增`finetune/holdout_metrics.py`集中原定义与冻结阈值、私有指标和公开gate聚合；修改`finetune/eval_run.py`仅为full配置路由到七门校验；修改`finetune/eval_holdout.py`贯通准备、评分、恢复、公开证据及下游校验，并将新模块加入冻结实现摘要。不改validation评分、源数据或历史对象。

精确测试范围：新增`tests/test_holdout_metrics.py`，修改`tests/test_eval_holdout.py`的合成四状态fixture及全链路断言；若共享fixture调用者受影响，仅修其必要断言并在证据列明。文档范围沿既有TODO/Plan/verification/handoff，加`versioning/SCRIPTS.md`及`finetune/SCRIPTS.md`的指标说明/模块索引。

先验证七门完整性、固定阈值与比较方向；用合成四状态原记录与历史f04ca7cb评分函数逐项对照（包括缺类、非法、runtime失败和边界），确认validation不变。再验证媒体推理不读truth、授权score、质量失败后consumed、完成中断恢复、私有评分重验、公开无数值指标泄漏及Registry准入拒绝篡改。旧泛化full配置不能自动改写为七门。

本机按受影响套件验证并取得独立reviewer局部审查；代码提交后沿既有bundle授权核对双机独有提交和保护文件，仅快进隔离checkout，在Linux现有CPU环境分进程复跑受影响套件。记录实际退出、日志SHA、实际执行代码和机器；不重复未变化的整包审查与模型实验。新批完成后更新验收状态，真实holdout来源/构建、GPU和硬盘缺口保留。Spec确认仅涵盖本批七门；实现沿用户“补齐”的明确授权，不要求再次批准同一取舍。

## 2026-09-13 test 数据分支实施批次

上游Spec042f335e，用户已明确确认方案并要求继续实施。现行叙述采用train/test数据分支，代码标识和历史记录保持原样。精确范围：新增`versioning/holdout_pipeline.py`与`tests/versioning/test_holdout_pipeline.py`；修改`versioning/data_pipeline.py`（共享审查导出可选择全部test候选）、`versioning/cli.py`（显式用途与test配置路由）、`finetune/eval_holdout.py`（构建证据绑定）、`tests/test_eval_holdout.py`（新发布到最终模型测试的合成接线），以及`versioning/SCRIPTS.md`、TODO、handoff、verification。其他长期文档仅做用户要求的叙述术语映射，不替换代码标记、配置值、路径或历史身份。

顺序：先增加显式test配置（冻结train版本、train/历史测试source身份与摘要清单），在owner-only独立工作区复用source/ROI/子视频算法；然后全量人工审查往返、媒体/真值分离发布与只读校验；最后接最终full模型测试并完成受影响回归、独立代码及入口说明核查。发布前后核验相同输入、source隔离、媒体内容、审查完整性，已发布内容和授权事实不可覆盖。训练及测试消费不由数据命令自动启动。

Proof：合成fixture验证七阶段、缺审/篡改/跨分支/身份或内容重叠拒绝、受限权限、公开数据无标签、同操作重试与冲突保留、最终模型测试从真实构建器产物消费及claim时序；train已有链路定向回归。只在本机或Linux隔离目录执行CPU测试，记录实际exit及机器/代码版本。真实数据/模型效果、硬盘和受限测试使用均保留未验收；本批不push或merge。

## 双平台部署实施批次

承接本次单独提交的双平台部署Spec及用户实施授权。精确文件范围：pyproject.toml、uv.lock、requirements.txt、新requirements-linux-gpu.lock；新增scripts/source_prepare_environment.py、scripts/source_validate_environment.py、scripts/SCRIPTS.md、tests/test_environment_deployment.py；局部更新README.md、finetune/README.md、TODO、handoff、verification。保持LlamaFactory子模块代码、版本身份与训练业务不变。

先统一pandas/MLflow兼容依赖并补cropper/媒体读取包，分别锁定Mac轻量和Linux GPU依赖；实现显式平台/新环境路径安装与doctor，绑定当前Git子模块来源，错误输入fail-closed，不安装系统包；最后做拒绝/失败传播测试、Mac新环境和Linux新隔离环境安装及入口验证。需要网络的安装只写新环境和工具缓存；不安装进agent/cpm45。新脚本和文档接受局部独立审查，保留真实安装失败证据。安装成功不等同模型可用，无真实训练/推理/test。

## M4-FOLD已确认实施批次（Spec b1aaf315）

承接用户对逐折规则及工程验证的确认。实施范围：finetune/train_prepare_run.py、versioning/cli.py，必要的versioning训练证据辅助逻辑；tests/test_train_with_contract.py、tests/versioning/test_cli.py及必要单折定向测试；局部更新finetune/README.md、TODO、handoff、verification。不改冻结三折结构或full契约。先接入选择参数，在现有train锁内核对父/子Run与逐折不可变证据，成功缺折partial、三折齐全沿用汇总/完成门；用合成trainer覆盖分次执行、完成折复用、漂移/残留/失败/并发拒绝与full回归，最后独立审查。复用现有partial原生状态映射，界面说明该映射而不改变公共状态契约。真实训练与test不执行。

## 已确认的交付与授权决定

- **工程与模型分开验收**（Spec `a5cfa86f`）：取消有限真实训练作为工程分支默认前置；旧模型及未通过质量门的事实保留。最终模型质量、真实成功路径及大型/外部恢复不由工程替身证据关闭。
- **独立 full 范围**（Spec `0bf0baed`）：用户确认增加 full 训练，不改冻结三折；full 使用独立配置与 full/adapter，holdout 先媒体推理、后授权 score，普通导出只公开 aggregate。
- **模型诊断仍待确认**：单折新基线方向、开发侧门槛及资源预算未确定；冻结 canary 或任意交叉替换 Prompt 的能力未实现，不列为当前动作。详细候选及证据缺口只在 MODEL-DIAG 条目维护。
- **条件清理持续有效**：旧数据及旧 run/model 的已验证冗余副本可按既有授权处理；89 个 train 视频仅验签，占用检查未过，删除0。未取消诊断或测试策略，不删新 store 外部依赖、唯一源和当前模型。
- **最终集成已完成**：用户明确先写模型背景文档，再推任务分支、后合并 main；2026-09-14 按顺序执行至 `5acebc27` 并同步训练机，回执见第67节。历史任务分支与隔离环境保留，默认解释器未切换。
- **授权只适用于已确认动作**：历史计划与集成授权不能自动用于新的 push/merge、系统权限调整、停止服务/训练、真实重训练/完整评测、受限测试使用或删除未核实产物。2026-10-12 用户仅授权本轮文档整理和独立核查。
