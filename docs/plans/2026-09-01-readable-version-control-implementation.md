# 可读版本控制架构实施台账（refactor/readable-version-control）

> 文档定位：本文件是 `refactor/readable-version-control` 分支的**实施台账**，记录本分支分批实施"可读版本控制架构"核心基础设施的批次计划、状态跟踪与恢复上下文。它不是项目级 TODO（项目级任务台账见 `docs/project-todo.md`），也不是架构权威（架构权威见设计文档）。
>
> 权威关系：**目标要求以确认后的设计文档为准，当前现状以代码和测试证据为准。**本文件只编排实施批次与验收，不重新定义架构；任何与[设计文档](2026-09-01-readable-version-control-design.md)冲突的表述以设计文档为准，任何与真实代码冲突的表述以代码和测试证据为准。实施后代码与设计冲突时，该 batch 不得完成；重大不可调和冲突暂停并交用户裁决。本文件不改变设计文档的责任边界。
>
> 最近更新时间：2026-09-04（B0–B12 全部完成）。B10 初版 `5d0b30a1` 后的最终复核发现 11 项问题，已由修复提交 `9965dc1b` 闭环；B11 文档提交为 `0506142a`、`8fdc1011` 并随修复同步；最终 `tests/versioning/` 为 `1399 passed`，整仓为 `2082 passed / 11 skipped / 0 failed`，两者均正常退出。reviewer 最终复审无剩余 P0–P3 actionable finding。完整提交映射见 §6.3，findings 处理见 §6.4。

## 1. 基线事实

以下为实施开始前已核验的基线，作为各 batch 验收与回滚的参照。

- **分支与提交（实施起点）**：基线分支 `main`，起点 HEAD `cc59312c6d72891bd0a03c70e8a6b759f97cbd74`；实施分支 `refactor/readable-version-control`。本行只记录开工基线，当前完成态与完整提交链见 §6。
- **修改前测试基线**：`uv run pytest tests/ -q` → `682 passed, 12 skipped, 0 failed`。12 个 skip 全部为 fastapi 未安装 / V3 fixtures / V4.1 workspace 数据缺失，属稳定已知跳过。
- **当前回归对照基线（B10 初版后）**：`PYTHONWARNINGS=ignore .venv/bin/python -m pytest -q tests` 已输出 `2066 passed, 11 skipped, 0 failed`；该次进程在 pytest 摘要后未自行退出并被中断，只作为修复前调查基线，不作为 B12 最终通过证据。B9 的最后一次正常退出基线仍为 `2043 passed, 11 skipped, 0 failed`。
- **依赖现状**：`pyproject.toml` + `uv.lock`（uv 管理，Python 3.11.14）；`dvc`、`mlflow` 均未声明、未安装；`requirements.txt`（训练机 Conda）亦无二者。
- **文档现状**：项目根无 `ARCHITECTURE.md`；`docs/adr/` 不存在；`docs/plans/` 仅设计文档（当前未跟踪，B0 纳入跟踪）。
- **需保护**：`stash@{0}`（他人工作，任何 batch 不得触碰）；旧链路代码与正式产物全程只读保留。
- **命名规范冲突**：`AGENTS.md` 现有"命名规范"仍强制哈希 ID / `index.json` / `LATEST` / 短哈希解析，与设计文档 §2.13 冲突，将在 B0 治理时序中做规则级最小改写（legacy 旧入口维持原规则原样，新 `versioning` 入口改用可读身份）；"以上commit由codex生成。"提交信息约定目前未写入任何文档，将补入 `AGENTS.md`。

## 2. 本轮范围边界

**本轮 = 核心基础设施**，包含：

- 独立新入口（`python -m versioning`）；
- 五类可读身份（data/prompt/train/model/eval）与状态机核心；
- 数据封存与 release 管理；
- DVC 七阶段 pipeline；
- Prompt 版本与冻结；
- MLflow 训练/测评记录；
- manifest 单向导出；
- Registry alias 与物化；
- 离线备份基础规则；
- 文档体系；
- 测试。

**明确排除（本轮不做）**：

- 旧对象映射（历史哈希产物到可读版本的迁移映射）；
- 删除旧哈希代码（`LATEST`、短前缀解析、内容哈希身份生成、集合 `index.json`）；
- 训练机操作（真实路径预检、SSH、GPU、真实数据/模型迁移）；
- 真实数据/模型迁移；
- merge / push。

## 3. 新体系技术选型约定

- **新顶层 Python 包**：`versioning/`，与 `pipeline/`、`finetune/` 平级；测试在 `tests/versioning/`；统一入口 `python -m versioning`。
- **新 DVC pipeline**：仓库根 `dvc.yaml`（旧链路无 DVC，无冲突）。
- **MLflow**：使用本地 SQLite + 本地 artifact store；测试一律用 `tmp_path` 临时实例，不连正式 remote、不启动常驻服务。

## 4. Batch 总表

| Batch | 一句话目标 |
| --- | --- |
| B0 | 基线固化与最小治理时序：提交文档基座 + AGENTS.md 分域改写 + ARCHITECTURE.md 骨架 |
| B1 | 依赖基座：声明并安装 dvc/mlflow，保持测试基线 |
| B2 | 可读身份与状态机核心：五类 ID 解析/校验 + workflow_state 状态机 |
| B3 | 数据封存、release 管理与 holdout 安全：working→release_staging→sealed + 一次性 claim |
| B4 | DVC pipeline 七阶段与最小 CLI：根 dvc.yaml + 真实最小实现 + stale 验证 + 人工审查关卡 |
| B5 | Prompt 版本与冻结：records/prompts 正式位置 + 训练 input 冻结副本 |
| B6 | MLflow 训练记录：train-v 父 Run + 三折子 Run + 状态映射 |
| B7 | MLflow 测评与 train/eval manifest 导出：eval-v + holdout 鉴权 + fold 绑定校验 |
| B8 | Model Registry、物化与晋级门：mVllm2 + alias gate + 原子物化 + offline_backup_scope 状态 |
| B9 | 离线备份 catalog 与恢复：backup_catalog 原子维护 + 复制验证 + SQLite/artifact 联合恢复 |
| B10 | 独立入口与端到端闭环：整合扩展统一 CLI + holdout 鉴权接线 + 全链路 fixture 测试 |
| B11 | 文档最终整合与一致性复核：交叉一致性、链接、对照真实代码核查 |
| B12 | 最终复核与收尾：全量测试、对抗式复核、关闭标准执行、实施文档收尾 |

## 5. 各 Batch 小节

### B0 — 基线固化与最小治理时序

- **状态**：completed
- **开始时间**：2026-09-02
- **当前动作**：B0 已完成并回填。提交 `a5bfca1b`（docs: 纳入设计文档与实施台账，新增 TODO 总任务）与 `a37f4acc`（docs: AGENTS 分域改写 + ARCHITECTURE 骨架）；提交前检查（无意外文件/无秘密/无大文件/`git diff --check`）全部通过，`stash@{0}` 完好。
- **目标**：把设计文档、本实施文档、TODO 总条目作为本分支首批提交固化，并在规则层完成最小治理改写与架构骨架，形成后续 batch 的基线。
- **包含范围**：
  - 提交 `docs/plans/2026-09-01-readable-version-control-design.md`、本实施文档、`docs/project-todo.md` 的 `VERSION-CONTROL-MIGRATION` 总条目。
  - **最小治理改写（根 `AGENTS.md`）**：明确分域——legacy 旧入口维持原规则原样；新 `versioning` 入口必须使用可读身份，不再使用哈希 ID / `index.json` / `LATEST` / 短哈希解析；并补入提交信息约定"以上commit由codex生成。"。此步只做规则级最小修改，保持简洁，不重写旧链路说明。
  - **创建根 `ARCHITECTURE.md` 初始骨架（含 Document Contract）**：起草前阅读并遵循 `/Users/pcoffeep/.pi/agent/skills/doc-contract/SKILL.md`；只描述当前真实状态——legacy 链路为现役、新体系在建、系统边界与三工具（Git/DVC/MLflow）职责；标注"当前实现范围"为空/在建。
- **排除范围**：不修改任何代码；不触碰 `stash@{0}`；不 merge、不 push；`AGENTS.md` 仅做规则级最小修改，不重写旧链路内容。
- **前置依赖**：用户对 batch 计划的一次性批准。
- **将修改的模块/文档**：`docs/plans/`（纳入跟踪）、`docs/project-todo.md`、`AGENTS.md`（最小治理改写）、`ARCHITECTURE.md`（新建骨架，含 Document Contract）。
- **可观察完成结果**：`git log` 新增 2–3 个原子提交（提交信息含"以上commit由codex生成。"）；`AGENTS.md` 已完成分域最小治理改写；`ARCHITECTURE.md` 骨架与 Document Contract 已建立并描述当前真实状态。
- **测试与验收命令**：`git log --oneline -3`；`git diff --check`；确认提交范围仅含上述文档；reviewer 核对 `AGENTS.md` 分域规则与 `ARCHITECTURE.md` 骨架。
- **失败路径/反向检查**：若提交范围混入代码或无关文件，回退并重做；若治理改写误伤 legacy 旧入口规则或新入口未改用可读身份，视为失败；若 `stash@{0}` 被触碰，立即停止并报告。
- **独立复核要求**：reviewer 核对提交内容、`AGENTS.md` 分域规则与 `ARCHITECTURE.md` 骨架是否符合 Document Contract。
- **回滚点**：分支基点 `cc59312c`。
- **风险与阻塞条件**：用户未批准 batch 计划则阻塞；提交信息约定/治理规则未确认则阻塞。
- **预计提交边界**：2–3 个原子提交（文档）。
- **完成后填**：修改文件清单：`docs/plans/2026-09-01-readable-version-control-design.md`、本实施台账、`docs/project-todo.md`、`AGENTS.md`、`ARCHITECTURE.md`；验证结果：提交前检查（无意外文件/无秘密/无大文件/`git diff --check`）全部通过，`stash@{0}` 完好；审查结论：reviewer 核对通过；提交哈希：`a5bfca1b`、`a37f4acc`；残余风险：无新增。

### B1 — 依赖基座

- **状态**：completed
- **开始时间**：2026-09-02
- **当前动作**：B1 已完成并回填。提交 `6482bed3`（chore: 新增 dvc 与 mlflow 项目级依赖）；冒烟验证在 pandas 3 下通过，新测试基线 `683 passed / 11 skipped / 0 failed`。
- **目标**：为 DVC 与 MLflow 建立依赖基座，且不破坏现有测试基线。
- **包含范围**（实际实施）：`pyproject.toml` 增加 `dvc>=3,<4`、`mlflow>=3,<4`，并新增 `[tool.uv] override-dependencies = ["pandas>=3.0.3"]`（mlflow 2/3.x 均硬依赖 `pandas<3`，与项目 `pandas>=3.0.3` 冲突——此方案偏离原计划 `mlflow>=2,<3`，记录于 §6.5）；dev 组新增 httpx2（starlette 1.3.1 TestClient 所需）；`requirements.txt` 同步声明；`uv lock` 更新并安装验证。
- **排除范围**：不初始化正式 DVC remote；不启动 MLflow 服务。
- **前置依赖**：B0 完成。
- **将修改的模块/文档**：`pyproject.toml`、`requirements.txt`、`uv.lock`。
- **可观察完成结果**：`uv run python -c "import dvc, mlflow"` 成功；`uv run pytest tests/ -q` 仍 `682 passed / 0 failed`。
- **测试与验收命令**：`uv run python -c "import dvc, mlflow"`；`uv run pytest tests/ -q`。
- **失败路径/反向检查**：若依赖安装破坏现有测试或引入版本冲突，回退依赖变更并报告。
- **独立复核要求**：reviewer 核对依赖声明与安装结果。
- **回滚点**：B0 提交。
- **风险与阻塞条件**：dvc/mlflow 与现有依赖（如 pandas/streamlit）版本冲突。
- **预计提交边界**：1 个提交（依赖文件）。
- **完成后填**：修改文件清单：`pyproject.toml`、`requirements.txt`、`uv.lock`；验证结果：`uv run python -c "import dvc, mlflow"` 成功，测试 `683 passed / 11 skipped / 0 failed`；MLflow 3 冒烟——SQLite tracking、嵌套子 Run（`mlflow.start_run(parent_run_id=..., nested=True)`）、search_runs DataFrame、Registry alias（set_registered_model_alias/get_model_version_by_alias）在 pandas 3 下全部可用；安装版本：dvc 3.67.1、mlflow 3.15.2、pandas 3.0.3；审查结论：reviewer 核对通过；提交哈希：`6482bed3`；残余风险：mlflow 依赖偏离原计划及 `requirements.txt` 冻结条目不一致，见 §6.5。

### B2 — 可读身份与状态机核心

- **状态**：completed
- **开始时间**：2026-09-02
- **当前动作**：B2 已完成并回填。`versioning/ids.py`、`versioning/state.py` 与 `versioning/__init__.py` 已实现，`tests/versioning/` 331 例全绿；提交 `30519042`。
- **目标**：建立五类可读身份解析/生成/严格校验，以及 workflow_state 状态机核心。
- **包含范围**：
  - `versioning/ids.py`：data/prompt/train/model/eval 五类 ID 解析、生成、严格校验；拒绝 `final`/`new`/`fixed`/`latest`/日期/seed/fold/checkpoint/自由文本后缀；禁止短前缀/模糊匹配/隐式 latest。
  - `versioning/state.py`：`workflow_state`（prepared/running/partial/failed/completed/archived）；`record_validity`（valid/invalid）；data status（active/superseded/invalid）；合法转换表与 `IllegalTransition` 等异常。
  - 测试 `tests/versioning/test_ids.py`、`test_state.py`：成功路径 + 全部非法转换反向测试。
- **排除范围**：不实现数据封存、DVC、MLflow 等下游逻辑。
- **前置依赖**：B1。
- **将修改的模块/文档**：`versioning/ids.py`、`versioning/state.py`、`tests/versioning/test_ids.py`、`tests/versioning/test_state.py`，并同步本实施台账 B2 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：五类 ID 合法/非法用例全部通过；状态机合法转换与全部非法转换反向用例通过。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`。
- **失败路径/反向检查**：非法 ID 被接受、非法状态转换被放行、短前缀/隐式 latest 未被拒绝，均视为失败。
- **独立复核要求**：reviewer（身份与状态机）。
- **回滚点**：B1 提交。
- **风险与阻塞条件**：状态转换表与设计文档 §5.3/§10 不一致。
- **预计提交边界**：1 个提交（模块 + 测试）。
- **完成后填**：修改文件清单：`versioning/__init__.py`、`versioning/ids.py`、`versioning/state.py`、`tests/versioning/test_ids.py`、`tests/versioning/test_state.py`；验证结果：`tests/versioning/` 287→331 passed，全量 `1014 passed / 11 skipped / 0 failed`；审查结论：reviewer 发现 1 P2 + 2 P3（尾随换行 / bool / 字符串异常），均已修复并补 44 个回归用例，复审通过；提交哈希：`30519042`；残余风险：无新增。

### B3 — 数据封存与 release 管理

- **状态**：completed
- **开始时间**：2026-09-02
- **当前动作**：B3 已完成并回填。`versioning/data_release.py`（release 生命周期、seal 不可变、status 语义、训练引用门）与 `versioning/holdout.py`（holdout 隔离、pre_registration、一次性 claim）已实现；`tests/versioning/test_data_release.py`、`test_holdout.py` 新增 138 例（含 8 个审查修复回归用例）；全量 `1144 passed / 11 skipped / 0 failed`；独立审查 3 P2 + 1 P3 修复后复审关闭、复审新增 1 P3（`create_claim` executor 校验）已修复并补 3 个参数化回归用例，复审已闭环；提交 `9de8acbb`；残余风险为 seal chmod 窗口（见完成回填）。
- **目标**：实现数据 working→release_staging→sealed 生命周期与 release.yaml 管理与 holdout 一次性 claim 安全边界。
- **包含范围**：
  - `versioning/data_release.py`：working→release_staging→sealed 生命周期；`release.yaml` schema；seal 后 payload 与身份字段只增不改；仅允许受控修改 `status` 与可选 `replacement`；非法重用/覆盖/状态逆转 fail-closed。
  - status 语义：`active` 可建新训练/测评；`superseded` 仅恢复历史引用；`invalid` 禁止一切新引用。
  - **holdout 安全边界（fixture-only）**：`purpose: holdout` 数据版本的 `training_allowed: false` 强制；`sealed_ground_truth/` 权限隔离结构；`authorization/claim.yaml` 全局一次性 claim（创建、同身份恢复、重复消费拒绝、覆盖已有 claim 拒绝、已消费授权不得再当可用授权）；`pre_registration.yaml` 结构。
  - `tmp_path` fixture 测试 + holdout 反向测试（未授权引用 holdout / 重复消费 claim / 覆盖已有 claim 均被拒绝）。
- **排除范围**：不实现 DVC 阶段、不连接真实数据；holdout 实现仅限 fixture/临时环境，不触碰真实 ground truth。
- **前置依赖**：B2。
- **将修改的模块/文档**：`versioning/data_release.py`、`versioning/authorization.py`（claim/pre_registration）、`versioning/_sealed_ground_truth.py`（或同批内对应模块）、`tests/versioning/test_data_release.py`、`tests/versioning/test_holdout.py`，并同步本实施台账 B3 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：seal 后身份字段不可改、payload 只读；非法覆盖/重用/状态逆转被拒绝；`purpose: holdout` 数据强制 `training_allowed: false`；一次性 claim 的创建/恢复/重复消费/覆盖语义正确；status 语义按设计生效。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`。
- **失败路径/反向检查**：seal 后字段可改、payload 可写、非法状态逆转放行，均视为失败；不同执行身份或不同 eval/model/data/split 四元组的 claim 恢复被拒绝。
- **独立复核要求**：reviewer（不可变性）。
- **回滚点**：B2 提交。
- **风险与阻塞条件**：release.yaml schema 与设计文档 §5.1 不一致。
- **预计提交边界**：1 个提交。
- **完成后填**：修改文件清单：`versioning/data_release.py`、`versioning/holdout.py`、`tests/versioning/test_data_release.py`、`tests/versioning/test_holdout.py`；验证结果：`tests/versioning/` 469 例全绿（B3 新增 138 例，含 8 个审查修复回归用例），全量 `uv run pytest tests/ -q` → `1144 passed / 11 skipped / 0 failed`；审查结论：独立审查 3 P2 + 1 P3 修复后复审关闭、复审新增 1 P3（`create_claim` executor 校验）已修复并补 3 个参数化回归用例，复审已闭环；提交哈希：`9de8acbb`；残余风险：seal 流程在 release rename 后最后一步 chmod 失败存在短暂不一致窗口——非静默（可检出）、不可重试，已接受记录。后注（合规修正说明，随显式版本纪律修正提交 `6b0d53bf69748f03005811a6f92308039b7691bc` 落实）：B3 中 `stage_release` 的行为经后续合规修正提交调整——其 `version` 参数改为显式必传、不接受缺省或建议值（显式版本纪律，见设计 §9/§11.6），该修正不改动 B3 已回填的封存与不可变语义。

### B4 — DVC pipeline 七阶段

- **状态**：completed（台账修正——此前误置 completed，实际经两轮 reviewer 修复 3 个 P2 与显式版本纪律改造后才真实完成，提交 `ae0bcef0`）
- **开始时间**：2026-09-02
- **当前动作**：B4 已完成并回填（台账修正）。根 `dvc.yaml`（七阶段固定顺序、依赖链、review_import 外部人工输入依赖、release 依赖 review_import、release outs 固定路径 `data/release_payload` + `data/release_pointer.json`，无 `data/releases` out / persist，版本号经 DVC params 注入 `${release_version}`）、`versioning/data_pipeline.py`（七阶段真实转换、上游 digest 贯穿 manifest、审查 `content_sha256` 绑定、release_validate 真实校验 + fail-closed）、`versioning/cli.py` + `versioning/__main__.py`（`python -m versioning data <stage>`，release 必填显式 `--version`，fail-closed exit code）已实现；`tests/versioning/test_data_pipeline.py`（34 例）+ `test_dvc_pipeline.py`（20 例）共 54 例全绿；`tests/versioning/` 共 523 例全绿。经两轮 reviewer 修复：修正测试缺陷（DVC run-cache 断言排除 `.dvc` 内部；fixture 时序改先 repro review_export）并退回/修复 production/dvc.yaml 缺陷（digest 传播、persist outs 等 3 个 P2）；随后实施显式版本纪律改造（release/stage_release 显式版本）。
- **目标**：在仓库根 `dvc.yaml` 表达七阶段数据 pipeline，并实现真实最小转换。
- **包含范围**：
  - 根 `dvc.yaml`：source/roi/subvideo/review_export/review_import/release/release_validate 七阶段。
  - 命令调用 `python -m versioning data ...` 子命令的真实最小实现（对 fixture 数据做真实文件转换，非占位）。
  - 人工审查为显式关卡：review_export 产物后流程停止；review_import 校验审查结果文件完整性与通过标记；未回收或校验失败时 release 必须非零退出阻断；release_validate 只报告不启动训练。
  - **最小 CLI 所有权**：`versioning/__main__.py` / `versioning/cli.py` 在 B4 创建，仅含 `data` 子命令供 dvc.yaml 调用；train/eval/model/backup 子命令留待 B10 整合扩展。
  - **DVC stale 验证**：DVC 只报告 stale 不自动执行；参数/代码/输入变化后 `dvc status` 能识别过期。
  - **临时 local remote 校验测试**：push→删除本地对象→pull→恢复校验，只用 `tmp_path` 临时 remote，不连正式 remote。
  - 集成测试：在 `tmp_path` 初始化临时 DVC 仓库跑通七阶段 fixture 闭环 + 审查缺失阻断反向测试；临时 local remote 恢复反向测试。
- **排除范围**：不连正式 remote；不启动训练。
- **前置依赖**：B1、B2、B3。
- **将修改的模块/文档**：`dvc.yaml`、`versioning/__main__.py`、`versioning/cli.py`（最小 `data` 子命令）、`versioning/` 相关 data 子命令、`tests/versioning/test_dvc_pipeline.py`、`tests/versioning/test_cli_data.py`，并同步本实施台账 B4 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：七阶段 fixture 闭环跑通；审查缺失时 release 非零退出阻断；release_validate 只报告不启动训练；DVC 对 stale 只报告不自动执行且 `dvc status` 能识别参数/代码/输入变化导致的过期；临时 local remote push→删对象→pull 能恢复。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`；临时 DVC 仓库内 `dvc repro` 相关阶段。
- **失败路径/反向检查**：审查未回收仍放行 release、release_validate 触发训练、阶段顺序错误，均视为失败。
- **独立复核要求**：reviewer（pipeline 关卡）。
- **回滚点**：B3 提交。
- **风险与阻塞条件**：DVC 版本行为差异、临时仓库初始化失败。
- **预计提交边界**：1–2 个提交。
- **完成后填**：修改文件清单：`dvc.yaml`、`versioning/__main__.py`、`versioning/cli.py`、`versioning/data_pipeline.py`、`tests/versioning/test_data_pipeline.py`、`tests/versioning/test_dvc_pipeline.py`；验证结果：`tests/versioning/` 523 例全绿（B4 新增 54 例：test_data_pipeline 34 + test_dvc_pipeline 20），全量 `uv run pytest tests/ -q` → `1306 passed / 11 skipped / 0 failed`（含 B5；提交门含 P3-1 冲突残留回归用例，已随 B4 提交入库）；审查结论：台账修正——原误置 completed，实际经两轮 reviewer 修复 3 个 P2（digest 传播、persist outs 等，含 release outs 改为固定 `data/release_payload` + 指针、去除 persist、版本经 params 注入）与显式版本纪律改造后才真实完成；B3 封存语义不受影响；提交哈希：`ae0bcef0`；残余风险：无新增。审查闭环补充：显式版本纪律修正提交 `6b0d53bf`（含 data_release.py 行为修正、受影响测试、三份文档同步）归入本批审查闭环记录，提交门 `1306 passed / 11 skipped / 0 failed`（含 P3-1 冲突残留回归用例，已随 B4 提交入库）。

### B5 — Prompt 版本与冻结

- **状态**：completed（提交 `345510a6`）
- **当前动作**：B5 已完成并回填。`versioning/prompts.py`（328 行，records/prompts 单一权威、训练 input 冻结副本、篡改检测；create_prompt 显式版本纪律、suggest_next_id 仅建议）与 `tests/versioning/test_prompts.py`（99 例）已实现全绿；全量 `1305 passed / 11 skipped / 0 failed`。提交 `345510a6`；显式版本纪律修正提交 `6b0d53bf` 归入本批审查闭环记录。
- **目标**：实现 Prompt 版本契约与训练 input 冻结副本。
- **包含范围**：
  - `versioning/prompts.py` + `records/prompts/` 目录契约（正式 Prompt 单一位置 `records/prompts/prompt-v<协议>-r<N>.yaml`，Git 跟踪）。
  - 训练输入冻结明确副本 freeze 操作：训练时仅从 `records/prompts/` 冻结复制到 `workspace/runs/train-v.../input/prompt.yaml`；不得形成第二套 Prompt 正式位置；禁止扫描历史目录猜测当前 Prompt；单一状态权威。
  - 测试：解析、冻结副本一致性、非法引用拒绝。
- **排除范围**：不实现训练执行。
- **前置依赖**：B2。
- **将修改的模块/文档**：`versioning/prompts.py`、`records/prompts/`（正式 Prompt 单一位置）、`tests/versioning/test_prompts.py`，并同步本实施台账 B5 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：正式 Prompt 文件不可覆盖；冻结副本与 Git 声明版本结构化一致；非法引用被拒绝。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`。
- **失败路径/反向检查**：冻结副本与源不一致仍放行、非法引用被接受、扫描历史目录猜测当前 Prompt，均视为失败。
- **独立复核要求**：reviewer（Prompt 契约）。
- **回滚点**：B4 提交。
- **风险与阻塞条件**：Prompt 契约与设计文档 §5.2 不一致。
- **预计提交边界**：1 个提交。
- **完成后填**：修改文件清单：`versioning/prompts.py`、`records/prompts/`（正式 Prompt 单一位置）、`tests/versioning/test_prompts.py`；验证结果：`test_prompts.py` 99 例全绿，`tests/versioning/` 共 622 例全绿，全量 `uv run pytest tests/ -q` → `1305 passed / 11 skipped / 0 failed`；审查结论：reviewer 在 B5 发现显式版本纪律 P2，作为统一改造（create_prompt/stage_release/run_release 显式完整版本号、suggest_next_id 仅建议）随各模块修正落实；提交哈希：`345510a6`；残余风险：无新增。审查闭环补充：显式版本纪律修正提交 `6b0d53bf`（含 data_release.py 行为修正、受影响测试、三份文档同步）归入本批审查闭环记录，提交门 `1306 passed / 11 skipped / 0 failed`（含 P3-1 冲突残留回归用例，已随 B4 提交入库）。

### B6 — MLflow 训练记录

- **状态**：completed
- **当前动作**：B6 已完成并回填。`versioning/mlflow_train.py`（584 行）已实现，`tests/versioning/test_mlflow_train.py` 137 例全绿；全量 `1443 passed / 11 skipped / 0 failed`。审查 2 P2 + 1 P3 均修复并补 22 个回归用例；残余风险见完成回填。
- **目标**：实现 train-v 父 Run + 三折子 Run 的 MLflow 训练记录与状态映射。
- **包含范围**：
  - `versioning/mlflow_train.py`：一个 train-v 对应一个父 Run，fold 为子 Run；父 Run 记录共同输入/配置/Git commit。
  - `workflow_state` 与原生 RunStatus 固定映射表执行；prepared→running→completed→archived 与 running↔partial↔failed 转换校验；partial/failed 只能受控恢复回 running。
  - 父 Run completed 需全部必需 fold FINISHED 且汇总完整；不完整 fold 不得晋级模型。
  - 集成测试用 `tmp_path` SQLite + artifact store。
- **排除范围**：不实现模型晋级、不连接正式 MLflow。
- **前置依赖**：B1、B2。
- **将修改的模块/文档**：`versioning/mlflow_train.py`、`tests/versioning/test_mlflow_train.py`，并同步本实施台账 B6 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：父子 Run 关系完整；状态映射与非法组合拒绝正确；不完整 fold 不晋级。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`。
- **失败路径/反向检查**：非法状态组合放行、不完整 fold 晋级、partial/failed 直接改 completed，均视为失败。
- **独立复核要求**：reviewer（状态机）。
- **回滚点**：B5 提交。
- **风险与阻塞条件**：MLflow 原生状态与 workflow_state 映射与设计文档 §5.3 不一致。
- **预计提交边界**：1–2 个提交。
- **完成后填**：修改文件清单：`versioning/mlflow_train.py`、`tests/versioning/test_mlflow_train.py`；验证结果：`test_mlflow_train.py` 137 例全绿，`tests/versioning/` 共 760 例全绿，全量 `uv run pytest tests/ -q` → `1443 passed / 11 skipped / 0 failed`；审查结论：reviewer 发现 2 P2（invalid 优先序、私有 helper 耦合）+ 1 P3（读路径 ID 校验），均修复并补 22 个回归用例，闭环；提交哈希：`f43d56c6`（实现）、`dd992f01`（文档同步）；残余风险：summary_complete 仅查 tag 存在性、状态写回非原子瞬时窗口、缺 tag 抛 KeyError 而非域异常、MLflow 版本行为绑定 3.15.2（见 §6.5）。

### B7 — MLflow 测评与 train/eval manifest 单向导出

- **状态**：completed
- **当前动作**：B7 已完成并回填。MLflow eval、train/eval manifest 单向导出、holdout 授权门及其反向测试已落地；提交 `3fdb920c`（实现）与 `0441d385`（文档同步）。
- **目标**：实现 eval-v 测评记录与 train/eval manifest 单向导出（model manifest 移入 B8）。
- **包含范围**：
  - `versioning/mlflow_eval.py`：eval-v 独立父 Run，显式引用模型/数据/配置/Git commit；`record_validity=invalid` 对象被下游拒绝。
  - `versioning/manifest.py`：train/eval manifest 最小字段；只能从 MLflow 单向导出；幂等重导。
  - 三类更正路径：导出器格式错误→幂等重导；可变运行标签→只改 MLflow；正式事实错误→旧对象 invalid + 新建版本。
  - 测试覆盖导出可复现性与更正路径。
  - **holdout 授权校验**：正式 eval 在创建引用 holdout 的 eval 版本前校验——无有效 claim 或无 pre_registration 时拒绝创建；训练入口对 `purpose: holdout` 数据一律 fail-closed 拒绝。
- **排除范围**：不实现 Registry 物化；model manifest 导出不在本批（B8）。
- **前置依赖**：B6（消除与 B8 的 manifest 循环依赖；本批不再依赖 B8）。
- **将修改的模块/文档**：`versioning/mlflow_eval.py`、`versioning/manifest.py`（train/eval）、`versioning/mock_train_entry.py` 或同批训练入口鉴权接线、`tests/versioning/test_mlflow_eval.py`、`tests/versioning/test_manifest.py`、`tests/versioning/test_holdout_auth.py`，并同步本实施台账 B7 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：train/eval manifest 最小字段正确、导出可复现、幂等重导；三类更正路径行为正确；invalid 对象被下游拒绝；single-fold / cross-validation / full-data 三种 scope 分开校验，cross-validation 严格绑定 fold0–fold2 子 Run（每 fold 对应模型 artifact、数据 split、样本数、records/failures 路径），缺失/重复/错配/额外 fold 均拒绝封存，aggregate 输入集合必须与声明 fold 集合完全一致；eval manifest 只能从通过上述校验的完成 Run 导出；对 holdout 的 eval 无有效 claim/pre_registration 时拒绝创建。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`。
- **失败路径/反向检查**：非完成 Run 导出、人工修改未检测、正式事实错误未走 invalid+新版本，均视为失败；cross-validation 的 fold 缺失/重复/错配/额外、aggregate 与声明 fold 不一致仍导出、无授权引用 holdout 仍建 eval、对 holdout 训练入口放行，均视为失败。
- **独立复核要求**：reviewer（manifest）。
- **回滚点**：B6 提交。
- **风险与阻塞条件**：manifest 字段与设计文档 §2.6/§5.3-5.5 不一致。
- **预计提交边界**：1–2 个提交。
- **完成后填**：修改文件清单：`versioning/mlflow_eval.py`、`versioning/manifest.py`、`tests/versioning/test_mlflow_eval.py`、`tests/versioning/test_manifest.py`；验证结果：`test_mlflow_eval.py` 223 例 + `test_manifest.py` 200 例全绿（含 18 个审查修复回归用例及其 RED 有效性证明），`tests/versioning/` 共 1183 例全绿，全量 `uv run pytest tests/ -q` → `1866 passed / 11 skipped / 0 failed`；审查结论：B7a 2 P2（aggregate 写前校验、list 观测校验对齐）+ B7b 1 P2（_train_gate 异常包装）+ 1 健壮性（严格 hex），全部修复并补 18 个回归用例（含 RED 有效性证明），4 P2 闭环；提交哈希：`3fdb920c`（实现）、`0441d385`（文档同步）；残余风险：B7 与 B6 同源累积——读取/结论门依赖 tag 组合与值域校验（非原子瞬时窗口）、manifest 校验绑定 digest 严格性与 MLflow 3.15.2 行为（见 §6.5）。

### B8 — Model Registry、物化与 alias 晋级门/备份范围

- **状态**：completed
- **开始时间**：2026-09-02
- **当前动作**：B8 已完成并回填。`versioning/registry.py`（636 行）已实现，`tests/versioning/test_registry.py` + `test_materialize.py` 共 143 例全绿；全量 `2009 passed / 11 skipped / 0 failed`。审查 1 P2（approve 缺 eval 关联校验，fail-open）已修复并补回归（变异测试证明）；覆盖缺口（materialize model_id 分歧）已补。
- **目标**：实现唯一 Registered Model `mVllm2`、models/current 原子物化、统一 alias mutation gate，并把 `offline_backup_scope` 状态及单向升级规则纳入本批。
- **包含范围**：
  - `versioning/registry.py`：唯一 Registered Model `mVllm2`；`model-v<协议>-r<N>` 映射唯一数值 Model Version；`model_id` tag 全 Registry 唯一且注册后不改绑；candidate/production alias 仅逻辑路由。
  - `versioning/materialize.py`：models/current 物化缓存：临时目录下载 + 校验后原子替换；alias 与物化不一致/断链/半物化/错误 manifest 拒绝启动；`service_mode development|production` 显式校验。
  - **model manifest**：在临时 Registry 真实 Model Version 注册完成后导出并验证全部字段（registered_model、数值 Model Version、source_run_id、source_scope、artifacts、deploy_target）；消除 B7↔B8 循环依赖。
  - **统一 alias mutation gate**：设置 candidate 前必须先写 scope=adapter；设置 production 前必须先升级 scope=production_bundle 且通过规定质量门并取得用户批准标记；所有 alias 修改必须经此 gate，禁止绕过。gate 校验：来源训练 record_validity=valid、原生 RunStatus=FINISHED、workflow_state∈{completed,archived}、必需 fold 与汇总完整、模型有唯一 deploy_target。
  - **offline_backup_scope 状态与单向升级规则**（由 B9 前移）：仅允许 缺失→adapter→production_bundle 单向升级，不得降级/清除。
  - 测试用临时 Registry。
- **排除范围**：不连接正式 MLflow、不加载真实模型。
- **前置依赖**：B6、B7（model manifest 依赖 B6 的训练 Run（source_run_id）与 B7 的 manifest 导出基础设施）。
- **将修改的模块/文档**：`versioning/registry.py`、`versioning/materialize.py`、`versioning/manifest.py`（model manifest 增量）、`versioning/scope.py`（offline_backup_scope 状态，或同批对应模块）、`tests/versioning/test_registry.py`、`tests/versioning/test_materialize.py`、`tests/versioning/test_manifest_model.py`、`tests/versioning/test_scope.py`，并同步本实施台账 B8 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：model_id 唯一且不改绑；alias 仅逻辑路由；物化原子替换；不一致/断链/半物化拒绝启动；service_mode 显式校验；alias gate 全路径生效（先 scope=adapter 再 candidate、先 scope=production_bundle 且质量门+批准再 production）；`offline_backup_scope` 单向升级正确且不可降级/清除。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`。
- **失败路径/反向检查**：alias 与物化不一致仍启动、半物化目标出现、service_mode 缺失仍启动、三折模型组成为 current，均视为失败；负向测试：先设 alias 后写 scope、无效训练晋级 candidate/production、未批准 production、无 deploy_target、scope 降级/清除仍被允许，均视为失败。
- **独立复核要求**：reviewer（alias/物化）。
- **回滚点**：B7 提交。
- **风险与阻塞条件**：物化原子替换与设计文档 §7 不一致。
- **预计提交边界**：1–2 个提交。
- **完成后填**：修改文件清单：`versioning/registry.py`、`tests/versioning/test_registry.py`、`tests/versioning/test_materialize.py`；验证结果：`test_registry.py` + `test_materialize.py` 共 143 例全绿，全量 `uv run pytest tests/ -q` → `2009 passed / 11 skipped / 0 failed`；审查结论：1 P2（approve 缺 eval 关联校验，fail-open）已修复并补回归（变异测试证明），覆盖缺口（materialize model_id 分歧）已补，闭环；提交哈希：`c1f515d7`（实现）、`a350c8cc`（文档同步）；残余风险：无新增。

### B9 — 离线备份 catalog 与恢复规则

- **状态**：completed
- **当前动作**：B9 已完成并回填。`versioning/backup.py`（enumerate_backup_sources scope tag 驱动、create_backup 真实复制 + 落盘前全量校验含 SQLite integrity_check + 差异修复 + 原子替换 + prev 快照、load/verify/restore 零副作用 + 目标冲突拒绝 + 灾难恢复 + 封存权限重放）与 `versioning/data_release.py`（seal_payload 提升公开 API，保留 `_seal_payload` 别名）已实现；`tests/versioning/test_backup.py` 34 例全绿；全量 `2043 passed / 11 skipped / 0 failed`。审查两轮（1 P1 + 2 P2 + 5 P3）全部修复并补 8 个回归用例（突变验证证明敏感），闭环。
- **目标**：实现离线备份的 backup_catalog 管理、复制验证与恢复规则（`offline_backup_scope` 状态已前移至 B8，本批只消费它）。
- **包含范围**：
  - `versioning/backup.py`：`offline_backup_scope`（B8 前移的状态及单向规则）确定源集合 = 全部正式数据 + 带范围 tag 的模型，按历史最高范围确定；执行复制并验证。
  - `backup_catalog.yaml` schema：对象 ID/类型/来源/时间/范围/verified；catalog 存在但文件缺失/损坏不能判定完成；catalog 可从实际对象重建；备份成功不自动删源。
  - **catalog 原子维护**：临时文件写入+校验后原子替换并保留上一份可读快照；每次运行对 catalog 全部既有对象重新核对实际文件。
  - **恢复规则**：SQLite 一致性快照备份；SQLite 与 artifact store 联合恢复；恢复后验证——可查询父子 Run、指标、Model Version、alias 和 artifact。
  - fixture 测试 + 恢复验证测试，全部用临时目录/临时 MLflow store，不连真实硬盘/训练机。
- **排除范围**：不连接真实移动硬盘、不执行真实备份；不实现/扩展 `offline_backup_scope` 状态机（已在 B8）。
- **前置依赖**：B3、B8（`offline_backup_scope` 状态与单向规则来自 B8）。
- **将修改的模块/文档**：`versioning/backup.py`、`tests/versioning/test_backup.py`、`tests/versioning/test_restore.py`，并同步本实施台账 B9 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：源集合按历史最高范围确定；catalog 存在但文件缺失不判完成；catalog 可重建、原子替换并保留上一份快照、每次核对实际文件；备份成功不删源；SQLite 与 artifact store 联合恢复后可查询父子 Run、指标、Model Version、alias 和 artifact。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`。
- **失败路径/反向检查**：源集合范围计算错误、catalog 存在即判完成、catalog 原子替换/快照失效、备份成功删源、恢复后无法查询父子 Run/指标/Model Version/alias/artifact、SQLite 与 artifact store 联合恢复不一致，均视为失败。
- **独立复核要求**：reviewer（备份与恢复规则）。
- **回滚点**：B8 提交。
- **风险与阻塞条件**：backup_catalog schema 与设计文档 §2.11 不一致。
- **预计提交边界**：1 个提交。
- **完成后填**：修改文件清单：`versioning/backup.py`、`versioning/data_release.py`（seal_payload 公开化）、`tests/versioning/test_backup.py`；验证结果：`test_backup.py` 34 例全绿，全量 `uv run pytest tests/ -q` → `2043 passed / 11 skipped / 0 failed`；审查结论：两轮审查（1 P1 + 2 P2 + 5 P3）全部修复并补 8 个回归用例（突变验证证明敏感），闭环；提交哈希：`0da89585`（实现）、`115d14f5`（文档同步）；残余风险：无新增。

### B10 — 独立入口与端到端闭环

- **状态**：completed
- **目标**：建立统一 CLI 入口并跑通端到端 fixture 闭环。
- **包含范围**：
  - **整合并扩展统一 CLI**（在 B4 的 `versioning/__main__.py` / `cli.py` 最小 `data` 子命令基础上整合训练/测评/物化/备份全部子命令）：data/prompt/train/eval/model/backup 子命令，显式版本参数，缺参即停并提示。
  - **holdout 鉴权接线**：把 B3（holdout 一次性 claim / pre_registration）与 B7（eval 授权校验、训练 fail-closed）的校验接线到 data/train/eval 子命令。
  - 端到端 fixture 测试：data release→prompt 冻结→train 记录→model 注册→eval→manifest 导出→backup catalog 全链路临时环境闭环；
  - holdout 反向端到端测试：无授权引用 holdout 建 eval / 对 holdout 数据触发训练均被拒绝。
- **排除范围**：不连接真实环境。
- **前置依赖**：B2–B9。
- **将修改的模块/文档**：`versioning/__main__.py`、`versioning/cli.py`（B4 最小入口的整合扩展）、`tests/versioning/test_cli.py`、`tests/versioning/test_e2e.py`、`tests/versioning/test_cli_holdout.py`，并同步本实施台账 B10 状态与 `ARCHITECTURE.md` 对应章节增量。
- **可观察完成结果**：统一入口各子命令可用；缺参即停并提示；data/train/eval 子命令已接线 holdout 鉴权；端到端 fixture 闭环跑通；holdout 反向端到端用例通过。
- **测试与验收命令**：`uv run pytest tests/versioning/ -q`；`python -m versioning --help`。
- **失败路径/反向检查**：缺参仍继续、子命令不可用、端到端链路中断、鉴权未接线/反向用例被放行，均视为失败。
- **独立复核要求**：reviewer（入口与闭环）。
- **回滚点**：B9 提交。
- **风险与阻塞条件**：子命令与设计文档 §7 显式版本纪律不一致。
- **预计提交边界**：1 个提交。
- **完成后填**：初版修改 `.gitignore`、`dvc.yaml`、统一 CLI、holdout 接线及 E2E 测试，提交 `5d0b30a1`；最终复核发现的 Registry 并发、eval 恢复、严格 model manifest、唯一 deploy target、alias/current 与备份闭环由 `9965dc1b` 修复。最终 `tests/versioning/` → `1399 passed`，整仓 → `2082 passed / 11 skipped`，均正常退出；reviewer 最终复审通过。

### B11 — 文档最终整合与一致性复核

- **状态**：completed
- **目标**：文档最终整合与一致性复核。不再承担新文档主体的补写（治理骨架已在 B0、各 batch 已完成同批文档），只做交叉一致性、链接、与真实代码对照核查及收尾润色。
- **包含范围**：
  - 更新 `README.md`（新入口最短路径与文档导航）。
  - 新建 `docs/adr/`（ADR-0001 记录采用可读版本控制总体决策及关键子决策索引）。
  - 对各 batch 已同批完成的文档做交叉一致性整合：`docs/DATA_PROCESSING_RUNBOOK.md`（新 DVC pipeline 章节）、`finetune/README.md`（新 MLflow 记录章节）、相关 `SCRIPTS.md` 增补。
  - 对 `ARCHITECTURE.md`（B0 骨架）做增量同步与收尾润色，与真实代码交叉核对，必要时更新"当前实现范围"。
  - 交叉一致性、Markdown 链接检查、与真实代码/测试证据对照核查。
- **排除范围**：不补写 `ARCHITECTURE.md`/`AGENTS.md` 新主体（主体与治理已在 B0）；不删除旧链路代码；不迁移真实产物。
- **前置依赖**：B0–B10（文档须对照真实代码）。
- **将修改的模块/文档**：`README.md`、`docs/adr/ADR-0001.md`、`docs/DATA_PROCESSING_RUNBOOK.md`、`finetune/README.md`、相关 `SCRIPTS.md`、`ARCHITECTURE.md`（B0 骨架增量同步）。
- **可观察完成结果**：文档与真实代码一致；交叉一致性、链接检查通过；ADR-0001 已建立；`ARCHITECTURE.md` 骨架已同步至当前实现范围。
- **测试与验收命令**：Markdown 链接检查；`git diff --check`；reviewer 对照真实代码逐条核查。
- **失败路径/反向检查**：文档与代码不一致、链接断裂、交叉冲突未消除，均视为失败。
- **独立复核要求**：所有新建/重写的权威文档由 reviewer 对照真实代码逐条独立核查。
- **回滚点**：B10 提交。
- **风险与阻塞条件**：文档与真实代码不一致。
- **预计提交边界**：2–3 个提交（按文档职责拆分）。
- **完成后填**：架构/设计/ADR 提交 `0506142a`；README、RUNBOOK、finetune 与 `versioning/SCRIPTS.md` 提交 `8fdc1011`；`9965dc1b` 同步最终实现差异。9 个目标文档本地链接检查、`dvc.yaml`/`params.yaml` YAML 解析、172 个 tracked JSON 解析、CLI help 与 `git diff --check` 全部通过；reviewer 已对照最终代码复审通过。

### B12 — 最终复核与收尾

- **状态**：completed
- **目标**：全量复核、处理 findings、收尾实施文档。
- **包含范围**：全量 `uv run pytest tests/ -q`、`git diff --check`、Markdown 链接检查、YAML/JSON 校验、未跟踪产物/大文件检查；reviewer 对整个分支最终对抗式复核；findings 处理；实施文档收尾（完整提交映射）；向用户提交合并建议（不 merge、不 push）。
- **排除范围**：不 merge、不 push；不执行训练机操作。
- **前置依赖**：B0–B11。
- **将修改的模块/文档**：本实施文档（收尾）。
- **可观察完成结果**：全量测试通过；静态检查通过；reviewer 无未解决 P0/P1；所有 actionable findings 均已修复，或已记录理由、影响与验证限制；实施文档含完整提交映射；合并建议已提交用户。
- **测试与验收命令**：`uv run pytest tests/ -q`；`git diff --check`；Markdown 链接检查；YAML/JSON 校验。
- **失败路径/反向检查**：存在未关闭 P0/P1、测试回归、文档与代码不一致；影响已确认完成标准的未修复 P2 仍被接受；未记录理由/影响/验证限制而保留的 finding，均视为未完成。
- **独立复核要求**：reviewer 对整个分支最终对抗式复核。
- **回滚点**：B11 提交。
- **风险与阻塞条件**：需用户重大取舍的 finding 未暂停请示、回归未修复。
- **预计提交边界**：1 个提交（文档收尾）。
- **完成后填**：`9965dc1b` 修改 Registry/eval/manifest/materialize/backup/CLI、相关测试及同步文档，关闭 §6.4 的 R1–R11；最终 `tests/versioning/` `1399 passed`，整仓 `2082 passed / 11 skipped`，均正常退出；9 文档链接、2 YAML、172 tracked JSON、编译、CLI help、diff/未跟踪/大文件检查通过。reviewer 独立执行 622 项相关套件、37 项最终备份套件、聚焦回归与跨进程文件锁攻击，结论为无剩余 P0–P3 actionable finding。最终台账与项目 TODO 收尾由本文件最后一次文档提交（`git log -- docs/plans/2026-09-01-readable-version-control-implementation.md docs/project-todo.md` 可追溯）完成。残余风险仅为 §6.5 的实机验证限制。

## 6. 状态跟踪与恢复

### 6.1 当前 batch

- **当前 batch**：B12（completed；B0–B12 核心基础设施实施与最终复核全部完成）。

### 6.2 Batch 状态表

| Batch | 状态 | 提交哈希 | 备注 |
| --- | --- | --- | --- |
| B0 | completed | a5bfca1b, a37f4acc | B0 基线固化完成 |
| B1 | completed | 6482bed3 | B1 依赖基座完成（残余风险见 §6.5） |
| B2 | completed | 30519042 | B2 身份与状态机完成 |
| B3 | completed | 9de8acbb | B3 数据封存与 holdout 安全完成（seal chmod 窗口见 §6.5） |
| B4 | completed | ae0bcef0 | B4 DVC pipeline 七阶段完成（台账修正回填） |
| B5 | completed | 345510a6 | B5 Prompt 版本与冻结完成（显式版本纪律修正提交 6b0d53bf 归入 B4/B5 审查闭环） |
| B6 | completed | f43d56c6, dd992f01 | B6 MLflow 训练记录完成 |
| B7 | completed | 3fdb920c, 0441d385 | B7 MLflow 测评与 manifest 单向导出完成 |
| B8 | completed | c1f515d7, a350c8cc | B8 Registry + 晋级门 + 物化完成（含 offline_backup_scope） |
| B9 | completed | 0da89585, 115d14f5 | B9 离线备份 catalog、恢复与文档同步完成 |
| B10 | completed | 5d0b30a1, 9965dc1b | 统一入口与端到端闭环完成，最终复核问题已关闭 |
| B11 | completed | 0506142a, 8fdc1011, 9965dc1b | 文档与最终代码一致性复核通过 |
| B12 | completed | 9965dc1b | R1–R11 已修复并复审关闭；最终全量与静态验收通过 |

### 6.3 提交映射表

| Batch | 提交哈希 | 提交信息摘要 | 涉及文件 |
| --- | --- | --- | --- |
| B0 | a5bfca1b | docs: 纳入设计文档与实施台账，新增 TODO 总任务 | docs/plans、docs/project-todo.md |
| B0 | a37f4acc | docs: AGENTS 分域改写 + ARCHITECTURE 骨架 | AGENTS.md、ARCHITECTURE.md |
| B1 | 6482bed3 | chore: 新增 dvc 与 mlflow 项目级依赖 | pyproject.toml、requirements.txt、uv.lock |
| B2 | 30519042 | feat(versioning): 新增可读身份与状态机核心模块 | versioning/__init__.py、ids.py、state.py、tests/versioning/ |
| B3 | 9de8acbb | feat(versioning): 新增数据封存 release 管理与 holdout 安全模块 | versioning/data_release.py、holdout.py、tests/versioning/test_data_release.py、test_holdout.py |
| B4 | ae0bcef0b5eaae6efdcceb3ead46b84074c757b2 | feat(versioning): DVC pipeline 七阶段与最小 CLI（台账修正回填） | dvc.yaml、versioning/__main__.py、cli.py、data_pipeline.py、tests/versioning/test_data_pipeline.py、test_dvc_pipeline.py |
| B5 | 345510a6dba8888bc4fd73e84a85acd38e4c6f35 | feat(versioning): Prompt 版本契约与训练 input 冻结副本 | versioning/prompts.py、records/prompts/、tests/versioning/test_prompts.py |
| 修正 | 6b0d53bf69748f03005811a6f92308039b7691bc | fix(versioning): 显式版本纪律修正（data_release 行为、受影响测试、三份文档同步；归入 B3 修正说明与 B4/B5 审查闭环） | versioning/data_release.py 等、受影响测试、三份文档 |
| B6 | f43d56c6 | feat(versioning): MLflow 训练记录模型 | versioning/mlflow_train.py、tests/versioning/test_mlflow_train.py |
| B6 | dd992f01 | docs: 同步 B6 MLflow 训练记录文档与实施台账 | 文档同步 |
| B7 | 3fdb920c | feat(versioning): MLflow 测评与 manifest 单向导出 | versioning/mlflow_eval.py、versioning/manifest.py、tests/versioning/test_mlflow_eval.py、test_manifest.py |
| B7 | 0441d385 | docs: 同步 B7 MLflow 测评与 manifest 文档及实施台账 | 文档同步 |
| B8 | c1f515d7 | feat(versioning): Model Registry、晋级门与物化 | versioning/registry.py、tests/versioning/test_registry.py、test_materialize.py |
| B8 | a350c8cc | docs: 同步 B8 Registry/晋级门/物化文档及实施台账 | 文档同步 |
| B9 | 0da89585 | feat(versioning): 离线备份 catalog 与恢复 | versioning/backup.py、versioning/data_release.py、tests/versioning/test_backup.py |
| B9 | 115d14f5 | docs: 同步 B9 备份 catalog/恢复文档及实施台账 | 文档同步 |
| B10 | 5d0b30a1 | feat(versioning): 完成统一入口与端到端安全闭环（初版，最终复核后 reopened） | .gitignore、dvc.yaml、versioning/、tests/versioning/ |
| B11 | 0506142a | docs: 收敛可读版本控制架构与决策 | ARCHITECTURE.md、设计文档、ADR-0001 |
| B11 | 8fdc1011 | docs: 补齐统一入口与运行导航 | README、RUNBOOK、finetune/README、versioning/SCRIPTS.md |
| B12 | 9965dc1b | fix(versioning): 补齐模型交付与并发安全闭环 | Registry/eval/manifest/materialize/backup/CLI、相关测试与同步文档 |

### 6.4 审查 findings 与处理

- **B12-R1（已修复并复审关闭）**：Registry 的“查重→创建”及“读取 eval 绑定→写 tag”不是并发事务。现全部 Registry mutation 共用进程内锁 + POSIX 文件锁；同一 model_id 并发登记恰一成功，不同 eval 并发 finalize 不覆盖首个绑定。
- **B12-R2（已修复并复审关闭）**：eval 完成状态在“服务端已提交 FINISHED、客户端丢失响应”后重试不幂等。现仅当 outcome、完整身份及 holdout 消费凭据一致时 completed/FINISHED 恢复成功，任何差异拒绝。
- **B12-R3（已修复并复审关闭）**：补齐严格 model manifest、`source_scope/artifacts/deploy_target` 门、alias 精确 `models/current` 原子物化及必填 `service_mode` 校验；E2E 先导出 model manifest，三折模型拒绝 alias/current。
- **B12-R4（已修复并复审关闭，P1）**：model layout 现要求 `artifacts/<scope>/...` 规范安全相对路径并拒绝 `.`；model manifest、物化与备份逐项核对实际 artifact，失败不切 current/不发布 catalog。
- **B12-R5（已修复并复审关闭，P2）**：`offline_backup_scope` 及 approve/alias/invalid 等 Registry mutation 统一纳入同一 Registry 写锁；并发升级不得降级。
- **B12-R6（已修复并复审关闭，P2）**：`models/current` 临时下载只先检查 deploy target，其他声明 artifact 缺失时会在报错前留下半物化目录，后续重试持续失败。已改为临时目录的 metadata、全部声明 artifact 与 deploy target 均通过后才发布，失败清理临时目录；已补反向用例。
- **B12-R7（已修复并复审关闭，P2）**：服务启动校验只检查 current 所指目录的内容，未要求其精确位于 `models/materialized/<alias model_id>`，外部人工目录可伪造通过。已增加受控根与精确目标校验，外部手工 symlink 反向用例已通过。
- **B12-R8（已修复并复审关闭，P2）**：model manifest 初次导出为 check-then-write，并发异内容可双成功、后写覆盖。train/eval 与 model manifest 现统一采用临时文件完整落盘 + 排他硬链接发布；目标已存在时仅同字节幂等，异内容冲突；并发异内容回归钉定恰一成功一冲突。
- **B12-R9（已修复并复审关闭，P1/P2）**：一是 eval 在 outcome 已写、workflow_state 写入失败后允许异 outcome 重试覆盖；现任一合法 outcome 一旦落盘即锁定，同结论恢复、异结论在任何后续写入/holdout 消费前拒绝。二是 adapter 范围此前复制完整模型目录并夹带 merged；现模型备份按 scope 白名单复制，adapter 仅保留 materialized 身份资料和声明 adapter，production_bundle 保留声明 adapter+merged，正式 eval 证据仍由同批 MLflow store 承载。两类反向用例已补。
- **B12-R10（已修复并复审关闭，P1）**：首次范围裁剪只处理 model 对象，仍遗漏两条灾难恢复链路：model manifest 未进入 catalog，恢复后引用悬空；固定 MLflow store 又整树夹带 adapter 模型的 merged。现每个 scoped model 的严格 manifest 明确进入其 catalog 并恢复到原 `records/models/<id>/manifest.yaml`；MLflow store 改为 SQLite + scoped model 声明的训练 artifact + 已绑定正式 eval artifact 白名单，adapter 对应 train run 的 merged 在整个 backup_root 中均不存在，production_bundle 的 merged 保留。灾难恢复用例继续验证 manifest，并在恢复后执行 `materialize_current` 与 `validate_service_current`。
- **B12-R11（已修复并复审关闭，P1）**：备份从枚举 scope/白名单到复制 SQLite 与发布 catalog 未持有同一 Registry 快照，期间粘性 scope 升级可生成“catalog=adapter、备份 SQLite=production_bundle、merged 缺失”的自相矛盾成功备份。现暴露共用的 Registry snapshot lock，`create_backup` 在同一跨进程临界区内完成枚举、所有复制、复验和 catalog 发布；所有 Registry mutation 均使用同一把锁。barrier 回归与 reviewer 独立双进程攻击均证明写入会被快照锁阻塞。

### 6.5 残余风险

- **B1 残留风险**：mlflow 2.x 与 3.x 均硬依赖 `pandas<3`，与项目 `pandas>=3.0.3` 冲突，最终采用 `mlflow>=3,<4` + `[tool.uv] override-dependencies = ["pandas>=3.0.3"]`，偏离原计划 `mlflow>=2,<3`；`requirements.txt` 既有 `fastapi==0.138.0`/`starlette==0.52.1` 冻结条目与 uv 解析版本（0.141.1/1.3.1）不一致（训练机 Conda 用，本轮不处理）。
- **B3 残留风险**：seal 流程在 release rename 后最后一步 chmod 写权限移除失败会留下未完全封存窗口；该失败非静默（可检出）、不可重试，已接受记录，不做自动重试。
- **B6 残留风险**：`summary_complete` 晋级门仅检查 tag 存在性（不校验值）；父 Run 状态写回（tag + RunStatus）非原子，存在瞬时窗口；读取缺 tag 时抛 `KeyError` 而非域异常；MLflow 行为绑定 3.15.2（B1 安装版本）。均非阻断，已接受记录。
- **B7 残留风险（与 B6 同源累积）**：eval 读取 fail-closed 与结论门（invalid 优先）依赖 tag 组合与值域校验，父 Run 状态写回/结论标记非原子存在瞬时窗口；manifest 校验绑定 digest 严格性与 export 单向性、依赖 MLflow 3.15.2 行为。均非阻断，已接受记录。
- 文件系统与 MLflow 之间不存在真实跨资源原子事务；当前实现采用不可覆盖证据、固定提交顺序与同身份幂等恢复，最终复核须覆盖各中断点。
- Registry/backup 的 `fcntl.flock` 已在当前 macOS 以独立双进程攻击验证阻塞，但尚未在 Linux 训练机 smoke；真实移动硬盘容量不足、中断恢复及真实 adapter/merged 加载恢复也未在本轮执行。
- 本分支仅为核心基础设施，正式迁移（旧对象映射、训练机操作、真实数据/模型迁移、merge/push）需另行授权。

### 6.6 下一步

- 本分支核心基础设施已完成。下一阶段是单独授权的正式迁移：旧对象映射、训练机/Linux smoke、真实 adapter/merged 与移动硬盘恢复演练、旧链路退役、merge/push；本轮不自动进入这些工作。

### 6.7 新接收者恢复工作所需最小上下文

- 分支：`refactor/readable-version-control`，核心修复 HEAD `9965dc1b`；最终台账/TODO 收尾提交由 `git log --` 追溯。B0–B12 完整映射见 §6.3。
- 权威设计：`docs/plans/2026-09-01-readable-version-control-design.md`（D040/D041 已随已确认两阶段模型生命周期和稳定预注册冻结路径更新）。
- 本实施台账：`docs/plans/2026-09-01-readable-version-control-implementation.md`。
- 项目级任务台账：`docs/project-todo.md` 的 `VERSION-CONTROL-MIGRATION` 总条目。
- 测试基线：B9 最后正常退出为 `2043 passed, 11 skipped, 0 failed`；B10 初版后整仓输出 `2066 passed, 11 skipped, 0 failed`，但摘要后进程未自行退出并被中断，不算 B12 最终证据；R11 后 `tests/versioning/` 已正常退出为 `1399 passed`。
- 需保护：`stash@{0}`（他人工作，任何 batch 不得触碰）；旧链路代码与正式产物全程只读。
- 提交信息约定：含"以上commit由codex生成。"。
- 禁止：merge、push、训练机操作、真实数据/模型迁移。
- 下一动作：等待用户决定是否另行授权正式迁移、训练机实机验证或合并/推送；核心基础设施不再有未完成 batch。

## 7. 停止与升级条件

（P1-4、P2-10 关闭标准）任一情况发生即暂停并报告用户，不继续推进：

- 工作区归属不明修改（如 `stash@{0}` 被触碰或出现来源不明的未提交改动）；
- 分支来源不明；
- 设计/代码重大冲突（本文件与设计文档或真实代码不一致且无法裁决）；
- 必须改旧链路（超出本轮"只读保留旧链路"边界）；
- 需正式数据/训练机（真实数据、GPU、SSH、训练机操作）；
- 未授权高风险操作（删除、覆盖、系统级依赖变更、merge、push）；
- 明显回归（测试基线被破坏且无法解释）；
- 无法闭环（某 batch 无法达到可观察完成结果）；
- 系统级依赖变更（超出 B1 声明的 dvc/mlflow 范围）；
- 秘密泄露风险；
- reviewer P0/P1 未关闭；
- batch 范围扩大（超出本轮核心基础设施边界）；
- 无法保护现有工作（旧链路代码或正式产物面临被覆盖/删除风险）。

**B12 关闭标准补充**：所有 actionable findings 必须修复；不修复的 finding 必须记录理由、影响与验证限制；影响已确认完成标准的 P2 不得接受；仅非阻断残余风险可经明确记录保留；需用户重大取舍时暂停并请示。
