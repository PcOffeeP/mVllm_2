<!-- generated from docs/design-facts.yaml by scripts/verify_design_facts.py --render，请勿手改 -->

## clip_state 五值的契约语义是断裂事件方向

### DF-001 [active] clip_state 五值的契约语义是断裂事件方向
契约 `search_semantics` 把 `clip_state` 定义为方向字段：未断裂=`fracture_event_is_after_clip`、发生断裂=`fracture_event_is_within_clip`、已断裂=`fracture_event_is_before_clip`、临界未断裂=`fracture_event_is_after_clip_with_visible_precursors`、无法判断=`no_directional_evidence`。
出处：
- pipeline/contracts/tensile_vlm_v4_1.json:196（expect：direction_field": "clip_state）
- pipeline/contracts/tensile_vlm_v4_1.json:197（expect：未断裂": "fracture_event_is_after_clip",）
- pipeline/contracts/tensile_vlm_v4_1.json:198（expect：发生断裂": "fracture_event_is_within_clip）
- pipeline/contracts/tensile_vlm_v4_1.json:199（expect：已断裂": "fracture_event_is_before_clip）
- pipeline/contracts/tensile_vlm_v4_1.json:200（expect：无法判断": "no_directional_evidence）
- pipeline/contracts/tensile_vlm_v4_1.json:213（expect：临界未断裂": "fracture_event_is_after_clip_with_visible_precursors）

## 已断裂的首帧锚点写在契约 Prompt 正文里

### DF-002 [active] 已断裂的首帧锚点写在契约 Prompt 正文里
契约 `analysis.user_prompt` 正文明写「可靠画面从一开始就已分离且没有片段内断裂前证据时为已断裂」，首帧锚点以文字形式存在于 Prompt 中，不是只存在于代码或评审判据里。
出处：
- pipeline/contracts/tensile_vlm_v4_1.json:168（expect：可靠画面从一开始就已分离且没有片段内断裂前证据时为已断裂）

## strict_valid 只校验输出形式，不校验语义

### DF-003 [active] strict_valid 只校验输出形式，不校验语义
`strict_valid` 通过只表示输出形式合法：单个 JSON 对象、无重复键、恰含契约四字段、枚举合法、跨字段组合合法；`extract_semantics` 按定义不接收标签、视频或模型身份，因此严格合法率不含语义正确性。
出处：
- finetune/eval_semantics.py:63（expect：def _validate_target(value: Mapping)）
- finetune/eval_semantics.py:99（expect：extract_semantics(raw_output:）
- finetune/eval_semantics.py:101（expect：never receives labels, video or model identity）
- finetune/eval_semantics.py:119（expect：raise ValueError("duplicate keys")）
- finetune/eval_semantics.py:126（expect：fields=fields, strict_valid=True）

## 七道冻结门的阈值

### DF-004 [active] 七道冻结门的阈值
`finetune/holdout_metrics.py` 冻结七道门阈值：four_state_macro_recall 0.4006；fracture_three_state_macro_recall 0.3；joint_correct_rate 0.3921；runtime_failure_count 0；strict_valid_rate 1.0；已断裂_recall 0.15；未断裂_recall 0.7。
出处：
- finetune/holdout_metrics.py:12（expect：THRESHOLDS = {）
- finetune/holdout_metrics.py:13（expect：four_state_macro_recall': 0.4006）
- finetune/holdout_metrics.py:14（expect：fracture_three_state_macro_recall': 0.3）
- finetune/holdout_metrics.py:15（expect：joint_correct_rate': 0.3921）
- finetune/holdout_metrics.py:16（expect：runtime_failure_count': 0,）
- finetune/holdout_metrics.py:17（expect：strict_valid_rate': 1.0）
- finetune/holdout_metrics.py:18（expect：已断裂_recall': 0.15）
- finetune/holdout_metrics.py:19（expect：未断裂_recall': 0.7）

## 新体系晋级有硬闸机

### DF-005 [active] 新体系晋级有硬闸机
新体系晋级路径以 `require_passed=True` 调用 eval 结论门；eval 记录 `outcome` 不等于 `passed` 时抛 `PromotionGateRejected`，晋级被硬性拒绝，不降级为警告。
出处：
- versioning/registry.py:522（expect：record.eval_id, require_passed=True)）
- versioning/registry.py:995（expect：record.outcome != "passed"）
- versioning/registry.py:997（expect：outcome={record.outcome!r}，未通过）

## 老体系模型登记与发布校验没有等价的 pass/fail 拦截

### DF-006 [active] 老体系模型登记与发布校验没有等价的 pass/fail 拦截
老体系没有等价的指标门拦截：`finetune/release_validate.py` 校验的是数据 release（封存校验 + 迁移凭据比对），`pipeline/model_registry.py` 校验的是产物哈希与 Prompt/身份漂移，其通过标志 `"passed": True` 只表示这些校验都通过；两处都不含七门阈值的 pass/fail 判断。
出处：
- finetune/release_validate.py:46（expect：assert_payload_sealed(release)）
- finetune/release_validate.py:61（expect：receipt.get("status") != "committed"）
- finetune/release_validate.py:65（expect：migration receipt does not match）
- pipeline/model_registry.py:304（expect："passed": True,）

## R1 在旧口径（1 组 / 64 token）下的实测效果

### DF-007 [active] R1 在旧口径（1 组 / 64 token）下的实测效果
R1 模型在旧口径（1 组 / 64 视觉 token、425 条 fold 0 validation）实测：`strict_valid_rate` 1、四字段 joint 正确率 0.411765、已断裂召回 0/33、发生断裂召回 66/144=0.458333、临界未断裂召回 13/57=0.228070。
出处：
- docs/results/model-r1-effect-profile-20261018.md:216（expect：已断裂 | 0/33）
- docs/results/model-r1-effect-profile-20261018.md:200（expect：严格合法条数 | 425）
- docs/results/model-r1-effect-profile-20261018.md:202（expect：四字段 joint 正确率 | 0.411765）
- docs/results/model-r1-effect-profile-20261018.md:214（expect：临界未断裂 | 13/57 | 0.228070）
- docs/results/model-r1-effect-profile-20261018.md:215（expect：发生断裂 | 66/144 | 0.458333）

## R1 在 8 帧 / 8 组 / 512 token 新口径下的重测结果

### DF-008 [active] R1 在 8 帧 / 8 组 / 512 token 新口径下的重测结果
同一模型、同一 425 条数据、同一 Prompt，仅把管线换成 8 帧 / 8 组 / 512 视觉 token 重测（2026-10-18）：四字段 joint 由 41.18% 升到 50.59%、已断裂仍 0/33、发生断裂 recall 由 45.83% 升到 59.72%、strict_valid 0.9906、临界未断裂 recall 由 0.2281 降到 0.1053；该重测结果文件尚未入库，本事实的仓库内锚点是任务台账的 R2-REALTRAIN 条目。
出处：
- docs/project-todo.md:82（expect：joint 由 **41.18%**（旧口径 1 组 / 64 token）升至 **50.59%**）

## 换管线已被实测否证为已断裂零召回的原因

### DF-009 [active] 换管线已被实测否证为已断裂零召回的原因
同模型、同 425 条、同 Prompt、只改管线的对照实测两侧已断裂召回均为 0/33，「64 token 丢帧序导致零召回」这一假设被否证（2026-10-18）（台账记载的对照实测；原始 425 条结果文件尚未入库）。
出处：
- docs/project-todo.md:82（expect：结论：**换管线不是零召回的原因**）

## 训练池里已断裂不稀缺

### DF-010 [active] 训练池里已断裂不稀缺
训练池中已断裂的占比：1253 条候选中 188 条（15.00%），每 epoch 3000 行中 564 行（18.80%），重复倍率 3.0 已顶到 `SIGNATURE_COUNT_CAP` 的上限值 3。
出处：
- docs/plans/2026-10-18-evaluation-pipeline-redesign.md:85（expect：1253 条候选中 188 条（15.00%））
- finetune/train_build_source_aware_dataset.py:30（expect：SIGNATURE_COUNT_CAP = 3）

## 训练机项目工作区路径

### DF-011 [active] 训练机项目工作区路径
训练机上的项目代码目录是 `/home/liuyang/文档/mVllm_2`。
出处：
- docs/project-status.md:21（expect：训练机代码目录 | `/home/liuyang/文档/mVllm_2`）

## 「已断裂」标签是 event_time 的循环推论，不是视觉判据

### DF-012 [active] 「已断裂」标签是 event_time 的循环推论，不是视觉判据
「已断裂」不是独立的视觉判据，而是 `event_time` 的循环推论：post 窗口起点硬编码为 `event + 0.5s`（`EVENT_GUARD_SECONDS = 0.5`），「已断裂」又由同一条不等式判出——区间 `start` 不早于 `event + 0.5`；物化阶段再主动拒绝任何采样帧早于 `event + 0.5` 的「已断裂」候选（`post_event_sample_crosses_guard`）。因此「标签 vs 窗口起点」的几何核算在定义上必然成立，不能用于证伪标签；标签正确性只能由独立的视觉判据（可见分离第一帧的人工标注或确定性检测）验证。
出处：
- pipeline/v3_candidate_plan.py:36（expect：EVENT_GUARD_SECONDS = 0.5）
- pipeline/v3_candidate_plan.py:314（expect：if start >= event + EVENT_GUARD_SECONDS）
- pipeline/v3_candidate_plan.py:659（expect：min(duration, event + EVENT_GUARD_SECONDS)）
- pipeline/v3_candidate_media.py:430（expect：elif state == "已断裂":）
- pipeline/v3_candidate_media.py:433（expect：value < event + EVENT_GUARD_SECONDS）
- pipeline/v3_candidate_media.py:434（expect：post_event_sample_crosses_guard）

## 标签锚点已裁决为「可见分离第一帧」

### DF-013 [active] 标签锚点已裁决为「可见分离第一帧」
用户于 2026-10-18 裁决：标签锚点采用「可见分离第一帧」（视觉可判），不锚在物理裂纹起始（视觉不可判）。`event_time` 改为该锚点的时间，但历史列不覆盖——数据表新增 `visible_separation_time` 列承载新值，原 `断裂时间点` 列原样保留、不改写不换算，用于新旧锚点的偏差分布统计与可追溯。理由：只有视觉可判的量才能作为视觉模型的标签与被评测对象；该锚点与用户原始判读口径一致；该锚点可被标注者独立复标，也可被确定性检测规则独立复现。
出处：
- docs/plans/2026-10-18-label-rebuild.md:70（expect：语义定为「**可见分离第一帧**」的时间）
- docs/plans/2026-10-18-label-rebuild.md:72（expect：数据表新增 `visible_separation_time` 列）
- docs/plans/2026-10-18-label-rebuild.md:101（expect：选 A —— **可见分离第一帧**（视觉可判））

## 标签语义变更必须升契约哈希

### DF-014 [active] 标签语义变更必须升契约哈希
若 `已断裂` 等标签的语义改变，即使枚举集合与取值域不变，也必须升 `contract_hash`，否则同一契约编号下会并存两套标签定义，使同一 `contract_hash` 下记录的评测结果无法判断是按哪套标签算的。反向不成立：只重算 `event_time` 的数值而不改标签语义定义时，不需要升哈希。本次标签重建（锚点由 `event + 0.5` 的几何偏移改为可见分离第一帧）属必须升哈希的一侧。
出处：
- pipeline/contracts/tensile_vlm_v4_1.json:3（expect：contract_hash": "3798f00cbec7）
- docs/plans/2026-10-18-label-rebuild.md:184（expect：即使枚举集合不变（四档名字与取值域都没变））
- docs/plans/2026-10-18-label-rebuild.md:185（expect：若只是**重算 `event_time` 的数值**）

## 已废弃（墓碑）

（当前没有已废弃条目。）

## 常见误读

- **误读**：父子窗口状态不同 = 数据矛盾
  - 正确：错。子窗口以断裂事件为锚重新裁剪，本来就可以包含断裂前片段，父子窗口状态不同是设计预期
- **误读**：格式合法率 1.0 = 判对了
  - 正确：错。`strict_valid` 只校验形式（单 JSON、无重复键、恰含四字段、枚举与跨字段组合），不校验语义正确性
  - 出处：finetune/eval_semantics.py:101（expect：never receives labels, video or model identity）
- **误读**：已断裂召回 0 = 管线丢掉帧序
  - 正确：错。已实测换管线仍 0/33，管线不是零召回的原因
  - 出处：docs/project-todo.md:82（expect：已断裂仍 **0/33**）
- **误读**：模型答不出帧数 = 模型缺陷
  - 正确：错。帧序输出属过期要求，现行契约 `analysis.user_prompt` 只要求四字段输出
  - 出处：pipeline/contracts/tensile_vlm_v4_1.json:168（expect：请输出且只输出 clip_state、fracture_mechanism）
- **误读**：几何上自洽 = 标签正确
  - 正确：错。几何自洽是同义反复：post 窗口起点与「已断裂」判据共用 `event + 0.5` 这一条不等式，物化阶段又主动拒绝早于该时刻的帧，核算必然成立，它不包含任何视觉信息；标签正确性必须由独立的视觉判据（可见分离第一帧）验证，见 DF-012 / DF-013。
  - 出处：pipeline/v3_candidate_plan.py:314（expect：if start >= event + EVENT_GUARD_SECONDS:）
  - 出处：pipeline/v3_candidate_media.py:433（expect：any(value < event + EVENT_GUARD_SECONDS）
- **误读**：预测缺失 = 不计入统计
  - 正确：错。分母由真值侧决定：只要真值区间可用，样本就留在区间分母里，预测缺失按不正确计分；否则「拒答/不输出」会成为逃避评分的策略。
  - 出处：finetune/validation/task_metrics.py:29（expect：= _valid_interval(target_interval)）
  - 出处：finetune/validation/task_metrics.py:35（expect：predicted_interval == target_interval）
  - 出处：finetune/validation/task_metrics.py:96（expect：score["interval_available"]）
  - 出处：finetune/validation/task_metrics.py:107（expect：interval_scored_samples": len(interval)）
- **误读**：路径能对上内容 = 引用正确
  - 正确：错。行号与内容对得上不代表文件路径存在：把 `v3_candidate_plan.py` 放在 `pipeline/scripts/` 下（实际位置是 `pipeline/` 根）时，引用处的行号与内容仍可能对得上，但该路径并不存在；引用前必须对路径本身做存在性实测，现由 `scripts/verify_design_facts.py --check-doc-paths` 兜底。这属于条件式反例：该错误写法曾出现在仓库外审计 brief 中（订正记录见仓库外 `~/pi-workspace/mVllm_2-audit/label-anchor-decision-20261018.md:22`，不在 Git 内，不是仓库证据）；仓库内从未有过该路径。
  - 出处：pipeline/SCRIPTS.md:23（expect：v3_candidate_plan.py`](v3_candidate_plan.py)）
