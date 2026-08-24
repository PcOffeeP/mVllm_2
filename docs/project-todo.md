# Project TODO

记录项目开发者的期望与当前实现之间尚未解决的差异。

## 待处理

### rebuild 流水线预存状态机缺陷

- **关联主题**：核心链路节点 2（数据快照 / ROI 子视频重建）与 `rebuild_v4_1_data.py` 状态机。
- **开发者期望**：完整 rebuild 流水线 review 模式下应能从 `source_snapshotted` 正常进入 `waiting_for_roi_review`。
- **当前实现**：当 `roi_decisions.json` 未预置时，流程在 `rebuild_v4_1_data.py` 中因 `source_snapshotted -> waiting_for_roi_review` 状态跳转不在 `pipeline/data_rebuild.py` 的 `ALLOWED_TRANSITIONS` 内而崩溃（`rebuild_v4_1_data.py:541` 触发，`data_rebuild.py:46-59` 校验）。
- **存在差异**：该缺陷在 HEAD 上即可复现，非本次变更引入；本次仅文档记录，未修复代码逻辑。
- **影响**：review 模式下首次运行必须预置 `roi_decisions.json`，否则 fail-closed；需在单独立项中修复状态机允许此合法跳转或调整初始化顺序。
- **代码依据**：
  - `pipeline/scripts/rebuild_v4_1_data.py`
  - `pipeline/data_rebuild.py`
- **待决定或后续动作**：单独立项修复 rebuild 流水线状态机，允许 `source_snapshotted -> waiting_for_roi_review` 跳转或保证 review 阶段启动前已加载/生成 `roi_decisions.json`。
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`

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
  - `finetune/run_v4_1_evaluation.py`
  - `docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md`
  - `docs/CURRENT_PROJECT_STATUS.md`
- **待决定或后续动作**：诊断“未断裂”坍缩根因（Prompt、采样、损失、后处理等），设计下一轮固定单一变量的对比实验。
- **记录版本**：`ca6311dd3def65aa3dee2081cbe31de2770c5439`

### V3 命名遗留容易误导为旧契约

- **关联主题**：核心链路节点 3（候选帧窗口计划与物化）。
- **开发者期望**：V4.1 数据链路的模块和脚本命名应清晰表达其当前用途，避免开发者误以为仍在使用 V3 契约。
- **当前实现**：候选物化核心模块仍命名为 `pipeline/v3_candidate_plan.py`、`pipeline/v3_candidate_media.py`、`scripts/subvideo_build_plan.py`、`scripts/materialize_v3_candidate_media.py`。这些模块在 V4.1 中继续承担候选计划与媒体物化职责，只是沿用了历史 provenance 路径名。
- **存在差异**：命名暗示 V3，实际服务于 V4.1；README/AGENTS/RUNBOOK 虽已说明，但代码级命名未改。
- **影响**：新开发者容易误解链路阶段；需要额外依赖文档说明。
- **代码依据**：
  - `pipeline/v3_candidate_plan.py`
  - `pipeline/v3_candidate_media.py`
  - `pipeline/scripts/rebuild_v4_1_data.py`（import 了上述 v3 模块）
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

## 待确认

（暂无）

## 已解决

（只记录由代码变更解决并经过核对的事项；当前本轮首次创建，尚未记录。）
