# Project TODO

记录项目开发者的期望与当前实现之间尚未解决的差异。

## 待处理

### 训练机首跑需实证 release 指针钉扎值

- **关联主题**：核心链路节点 5（training release）与节点 9（模型注册表晋级）。
- **开发者期望**：在挂载真实 workspace 的训练机上首次运行时，应通过 `python finetune/release_validate.py` 校验当前 `finetune/active_data_release.json` 中的钉扎 `expected_contract_hash`（`ba61695c...`）与真实 `release_manifest.json` 的契约 hash 字节完全一致。
- **当前实现**：指针文件中的钉扎值已在代码中写入，但尚未在训练机真实 manifest 上实证跑通。
- **存在差异**：本地/CI 测试使用显式传入期望值的方式跳过指针校验，不能替代训练机对真实钉扎值的实证。
- **影响**：若钉扎值与真实 manifest 字节不一致，训练/评测入口将 fail-closed。
- **代码依据**：
  - `finetune/active_data_release.json`
  - `finetune/release_validate.py`
  - `finetune/v4_1_runtime.py`（`validate_release` / `load_release_expectations`）
- **待决定或后续动作**：训练机首跑后确认 `python finetune/release_validate.py` 通过，并记录验证结果。
- **记录版本**：`0ffecb3a`

### 历史 v3 契约哈希不可复现

- **关联主题**：核心链路节点 3（候选帧窗口计划与物化）与历史训练产物溯源。
- **开发者期望**：仓库中已提交的 `pipeline/contracts/tensile_vlm_v3.json` 应与训练机历史 manifest 记录的契约 hash 逐字节一致，以便复现历史候选计划。
- **当前实现**：训练机历史 manifest 记录的 v3 契约 hash 为 `3f9f82...`，而仓库当前已提交版本的 `pipeline/contracts/tensile_vlm_v3.json` hash 为 `e963cdd...`，两者不符。
- **存在差异**：生成历史 plan 时工作区存在未提交的契约改动，该版本契约内容未进入仓库，导致无法逐字节复现历史 plan 的内容寻址身份。
- **影响**：历史 plan 的 `plan_id` / manifest hash 无法在当前仓库直接复现；内容寻址链本身仍可保证血缘与输出一致性，但严格逐字节复现缺失中间契约版本。
- **代码依据**：
  - `pipeline/contracts/tensile_vlm_v3.json`
  - 训练机历史 manifest 中的契约 hash 记录
- **待决定或后续动作**：将该缺口记录为已知可复现性限制；如需严格复现历史 plan，需找回或重建当时工作区未提交的契约版本。
- **记录版本**：`e027e82e04d5a0f5ffb05b5d4d6d0ad1fa75ee85`

### 当前发布模型质量门未通过

- **关联主题**：核心链路节点 9（模型注册表晋级 + delivery 门禁校验）与节点 8（严格评测）。
- **开发者期望**：当前发布模型 `v4.1-agent-pipeline-fold0-r1` 应通过 Stage B、Stage D、Stage G 模型质量门，成为可被验收的模型。
- **当前实现**：模型已完整走通训练、合并、推理服务、Agent 调用链路，并在 registry 中标记为 `current`；但 `delivery/model_component.json` 中 `stage_b_passed`、`stage_d_passed`、`stage_g_passed` 均为 `false`，`production_approved` 为 `false`。
- **存在差异**：工程链路验收 ≠ 模型质量验收。当前模型是中间开发模型，不能作为 production-ready 或最终模型交付。
- **影响**：TensileAgent 可调用，但输出质量尚未满足最终验收标准。
- **代码依据**：
  - `pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json`
  - `delivery/model_component.json`
  - `docs/CURRENT_PROJECT_STATUS.md`
- **待决定或后续动作**：制定并执行提升 `clip_state`、`fracture_mechanism`、`fracture_site`、`special_case` 四字段准确率的下一轮实验方案。
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`

### 最新三折实验出现类别坍缩与契约退化

- **关联主题**：核心链路节点 8（严格评测）。
- **开发者期望**：三折受控实验应产生跨 fold 稳定、可晋级为全量训练候选的方案。
- **当前实现**：`v4.1-prompt-concise-cv-v1-seed3411` 三折已完成训练、最佳 checkpoint 回载、合并与 1581 条评测；结果加权 contract 合法率 79.63%，joint correct 32.07%，`clip_state` 35.80%，322 条严格非法输出，明显坍缩到“未断裂”，`临界未断裂`和`已断裂`召回均为 0%。
- **存在差异**：模型能训练成功，但任务效果未达标，实验未晋级为 release。
- **代码依据**：
  - `finetune/eval_run.py`
  - `docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md`
  - `docs/CURRENT_PROJECT_STATUS.md`
- **待决定或后续动作**：诊断“未断裂”坍缩根因（Prompt、采样、损失、后处理等），设计下一轮固定单一变量的对比实验。
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`

### V3 命名遗留容易误导为旧契约

- **关联主题**：核心链路节点 3（候选帧窗口计划与物化）。
- **开发者期望**：V4.1 数据链路的模块和脚本命名应清晰表达其当前用途，避免开发者误以为仍在使用 V3 契约。
- **当前实现**：候选物化核心模块仍命名为 `pipeline/v3_candidate_plan.py`、`pipeline/v3_candidate_media.py`、`scripts/subvideo_build_plan.py`、`scripts/subvideo_materialize_media.py`。这些模块在 V4.1 中继续承担候选计划与媒体物化职责，只是沿用了历史 provenance 路径名。
- **存在差异**：命名暗示 V3，实际服务于 V4.1；README/AGENTS/RUNBOOK 虽已说明，但代码级命名未改。
- **影响**：新开发者容易误解链路阶段；需要额外依赖文档说明。
- **代码依据**：
  - `pipeline/v3_candidate_plan.py`
  - `pipeline/v3_candidate_media.py`
  - `pipeline/scripts/rebuild_data.py`（import 了上述 v3 模块）
  - `docs/DATA_PROCESSING_RUNBOOK.md` 第 165–168 行
- **待决定或后续动作**：决定是否重命名（并保持 provenance 兼容）或在模块级 docstring/注释中显式说明 V4.1 用途。
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`

### 独立测试 release 与 full-data final 模型尚未完成

- **关联主题**：核心链路节点 5（training release）与节点 9（模型注册表晋级）。
- **开发者期望**：最终模型应使用全部合格开发数据训练，并由从未参与调参的独立测试 release 验收。
- **当前实现**：当前发布模型仅使用 Fold0；存在 development release（1678 条），但尚未完成 full-data final 训练与独立测试 release 流程。
- **存在差异**：模型训练范围与验收数据均未达到最终交付标准。
- **代码依据**：
  - `finetune/README.md`
  - `docs/CURRENT_PROJECT_STATUS.md`
  - `pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json`（`full_data_final: false`）
- **待决定或后续动作**：在质量门问题解决后，规划全量训练与独立测试 release。
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`

### release 指针文件更新自动化

- **关联主题**：核心链路节点 5（training release）与节点 9（模型注册表晋级）。
- **开发者期望**：每次 `release_build` 完成后，`finetune/active_data_release.json` 中的 `release_id` 与 `expected_contract_hash` 应自动更新为刚发布 release 的钉扎值，避免手动维护导致遗漏或自证化攻击窗口。
- **当前实现**：指针文件更新为手动步骤，reviewer 已确认当前为手动写入 `expected_contract_hash`，存在更新延迟或错配风险。
- **存在差异**：release 构建流程不自动回填 git 跟踪的指针文件，依赖人工核对 docs/results 中的冻结 manifest 摘要。
- **影响**：若指针未随 release 更新，训练/评测入口将 fail-closed 或验证失败；手动操作也更容易出现 copy-paste 错误。
- **代码依据**：
  - `finetune/active_data_release.json`
  - `finetune/v4_1_runtime.py`（`_load_active_release_pointer` / `load_release_expectations`）
  - `pipeline/scripts/release_build_phase2.py`（release_build 入口）
- **待决定或后续动作**：在 `release_build_phase2` 完成阶段自动覆写 `finetune/active_data_release.json` 的 `release_id` 与 `expected_contract_hash`，并补充校验确保与刚生成的 manifest 一致。
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`

## 待确认

（暂无）

## 已解决

（只记录由代码变更解决并经过核对的事项。以下三项已通过代码变更修复并经全量测试与独立 reviewer 复验。）

### promote 不传播 index.json

- **关联主题**：核心链路节点 2（数据快照）与 `promote`（`pipeline/data_rebuild.py`）。
- **解决情况**：`promote` 已在互斥锁内、状态落盘前为 `source_snapshots`/`split_snapshots` 集合写入 `index.json` + LATEST（复用 `artifact_index.append_entry` / `artifact_resolver.update_latest`）；两段式先校验后写入防半写；重入幂等（`append_entry` 内建同 id 同内容跳过，`created_at` 沿用）；缺 payload 文件或必要 key 时 fail-closed（`DataRebuildError`）。
- **验证**：全量测试 `uv run pytest tests/ -q` → 682 passed, 12 skipped；新增行为级测试覆盖 `_update_snapshot_collection_indexes`。
- **代码依据**：
  - `pipeline/data_rebuild.py`（`_update_snapshot_collection_indexes`）
  - `pipeline/artifact_index.py`
  - `pipeline/scripts/build_artifact_index.py`
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`（修复在未提交工作区中验证，尚未提交为独立 commit）

### rebuild 流水线预存状态机缺陷

- **关联主题**：核心链路节点 2（数据快照 / ROI 子视频重建）与 `rebuild_data.py` 状态机。
- **解决情况**：`pipeline/data_rebuild.py` 的 `ALLOWED_TRANSITIONS` 中 `source_snapshotted` 已增加 `waiting_for_roi_review`；review 模式首跑（无预置 `roi_decisions.json`）可正常进入等待人工标注（rc=0），复跑幂等。
- **验证**：全量测试 `uv run pytest tests/ -q` → 682 passed, 12 skipped；新增行为级测试覆盖该合法状态跳转与首跑/复跑幂等。
- **代码依据**：
  - `pipeline/scripts/rebuild_data.py`
  - `pipeline/data_rebuild.py`
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`（修复在未提交工作区中验证，尚未提交为独立 commit）

### roi_annotation_app.py --metadata 默认路径失效

- **关联主题**：核心链路节点 2（ROI 标注）与 source snapshot 索引。
- **解决情况**：`_parse_args` 已复用 `artifact_resolver.resolve_cli_artifact_path` 解析 `source_snapshots` 集合 LATEST 的 `video_meta.json`；支持显式路径/ID/前缀；无 LATEST 或前缀歧义时 fail-closed（`ValueError`）。已同步 `docs/DATA_PROCESSING_RUNBOOK.md` 与模块 docstring。
- **残余风险**：`ValueError` 在 streamlit 下呈现为裸 traceback（呈现层 UX 问题，已裁决为可接受的残余风险）。
- **验证**：全量测试 `uv run pytest tests/ -q` → 682 passed, 12 skipped；新增行为级测试覆盖默认路径解析。
- **代码依据**：
  - `pipeline/scripts/roi_annotation_app.py`（`_parse_args`）
  - `pipeline/scripts/build_artifact_index.py` / `pipeline/artifact_index.py`（`source_snapshots` LATEST 解析）
- **记录版本**：`f6881883`（修复在未提交工作区中验证，尚未提交为独立 commit）
