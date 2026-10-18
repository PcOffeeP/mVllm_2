<!-- generated from docs/design-facts.yaml by scripts/verify_design_facts.py --render，请勿手改 -->

## clip_state 五值的契约语义是断裂事件方向

### DF-001 [active] clip_state 五值的契约语义是断裂事件方向
契约 `search_semantics` 把 `clip_state` 定义为方向字段：未断裂=`fracture_event_is_after_clip`、发生断裂=`fracture_event_is_within_clip`、已断裂=`fracture_event_is_before_clip`、临界未断裂=`fracture_event_is_after_clip_with_visible_precursors`、无法判断=`no_directional_evidence`。
出处：
- pipeline/contracts/tensile_vlm_v4_1.json:196
- pipeline/contracts/tensile_vlm_v4_1.json:197
- pipeline/contracts/tensile_vlm_v4_1.json:198
- pipeline/contracts/tensile_vlm_v4_1.json:199
- pipeline/contracts/tensile_vlm_v4_1.json:200
- pipeline/contracts/tensile_vlm_v4_1.json:213

## 已断裂的首帧锚点写在契约 Prompt 正文里

### DF-002 [active] 已断裂的首帧锚点写在契约 Prompt 正文里
契约 `analysis.user_prompt` 正文明写「可靠画面从一开始就已分离且没有片段内断裂前证据时为已断裂」，首帧锚点以文字形式存在于 Prompt 中，不是只存在于代码或评审判据里。
出处：
- pipeline/contracts/tensile_vlm_v4_1.json:168

## strict_valid 只校验输出形式，不校验语义

### DF-003 [active] strict_valid 只校验输出形式，不校验语义
`strict_valid` 通过只表示输出形式合法：单个 JSON 对象、无重复键、恰含契约四字段、枚举合法、跨字段组合合法；`extract_semantics` 按定义不接收标签、视频或模型身份，因此严格合法率不含语义正确性。
出处：
- finetune/eval_semantics.py:63
- finetune/eval_semantics.py:99
- finetune/eval_semantics.py:101
- finetune/eval_semantics.py:119
- finetune/eval_semantics.py:126

## 七道冻结门的阈值

### DF-004 [active] 七道冻结门的阈值
`finetune/holdout_metrics.py` 冻结七道门阈值：four_state_macro_recall 0.4006；fracture_three_state_macro_recall 0.3；joint_correct_rate 0.3921；runtime_failure_count 0；strict_valid_rate 1.0；已断裂_recall 0.15；未断裂_recall 0.7。
出处：
- finetune/holdout_metrics.py:12
- finetune/holdout_metrics.py:13
- finetune/holdout_metrics.py:14
- finetune/holdout_metrics.py:15
- finetune/holdout_metrics.py:16
- finetune/holdout_metrics.py:17
- finetune/holdout_metrics.py:18
- finetune/holdout_metrics.py:19

## 新体系晋级有硬闸机

### DF-005 [active] 新体系晋级有硬闸机
新体系晋级路径以 `require_passed=True` 调用 eval 结论门；eval 记录 `outcome` 不等于 `passed` 时抛 `PromotionGateRejected`，晋级被硬性拒绝，不降级为警告。
出处：
- versioning/registry.py:522
- versioning/registry.py:995
- versioning/registry.py:996

## 老体系模型登记与发布校验没有等价的 pass/fail 拦截

### DF-006 [active] 老体系模型登记与发布校验没有等价的 pass/fail 拦截
老体系没有等价的指标门拦截：`finetune/release_validate.py` 校验的是数据 release（封存校验 + 迁移凭据比对），`pipeline/model_registry.py` 校验的是产物哈希与 Prompt/身份漂移，其通过标志 `"passed": True` 只表示这些校验都通过；两处都不含七门阈值的 pass/fail 判断。
出处：
- finetune/release_validate.py:46
- finetune/release_validate.py:61
- finetune/release_validate.py:65
- pipeline/model_registry.py:304

## R1 在旧口径（1 组 / 64 token）下的实测效果

### DF-007 [active] R1 在旧口径（1 组 / 64 token）下的实测效果
R1 模型在旧口径（1 组 / 64 视觉 token、425 条 fold 0 validation）实测：`strict_valid_rate` 1、四字段 joint 正确率 0.411765、已断裂召回 0/33、发生断裂召回 66/144=0.458333、临界未断裂召回 13/57=0.228070。
出处：
- docs/results/model-r1-effect-profile-20261018.md:199
- docs/results/model-r1-effect-profile-20261018.md:200
- docs/results/model-r1-effect-profile-20261018.md:212
- docs/results/model-r1-effect-profile-20261018.md:213
- docs/results/model-r1-effect-profile-20261018.md:214

## R1 在 8 帧 / 8 组 / 512 token 新口径下的重测结果

### DF-008 [active] R1 在 8 帧 / 8 组 / 512 token 新口径下的重测结果
同一模型、同一 425 条数据、同一 Prompt，仅把管线换成 8 帧 / 8 组 / 512 视觉 token 重测（2026-10-18）：四字段 joint 由 41.18% 升到 50.59%、已断裂仍 0/33、发生断裂 recall 由 45.83% 升到 59.72%、strict_valid 0.9906、临界未断裂 recall 由 0.2281 降到 0.1053；该重测结果文件尚未入库，本事实的仓库内锚点是任务台账的 R2-REALTRAIN 条目。
出处：
- docs/project-todo.md:82

## 换管线已被实测否证为已断裂零召回的原因

### DF-009 [active] 换管线已被实测否证为已断裂零召回的原因
同模型、同 425 条、同 Prompt、只改管线的对照实测两侧已断裂召回均为 0/33，「64 token 丢帧序导致零召回」这一假设被否证（2026-10-18）（台账记载的对照实测；原始 425 条结果文件尚未入库）。
出处：
- docs/project-todo.md:82

## 训练池里已断裂不稀缺

### DF-010 [active] 训练池里已断裂不稀缺
训练池中已断裂的占比：1253 条候选中 188 条（15.00%），每 epoch 3000 行中 564 行（18.80%），重复倍率 3.0 已顶到 `SIGNATURE_COUNT_CAP` 的上限值 3。
出处：
- docs/plans/2026-10-18-evaluation-pipeline-redesign.md:83
- finetune/train_build_source_aware_dataset.py:30

## 训练机项目工作区路径

### DF-011 [active] 训练机项目工作区路径
训练机上的项目代码目录是 `/home/liuyang/文档/mVllm_2`。
出处：
- docs/project-status.md:21

## 已废弃（墓碑）

（当前没有已废弃条目。）

## 常见误读

- **误读**：父子窗口状态不同 = 数据矛盾
  - 正确：错。子窗口以断裂事件为锚重新裁剪，本来就可以包含断裂前片段，父子窗口状态不同是设计预期
- **误读**：格式合法率 1.0 = 判对了
  - 正确：错。`strict_valid` 只校验形式（单 JSON、无重复键、恰含四字段、枚举与跨字段组合），不校验语义正确性
  - 出处：finetune/eval_semantics.py:101
- **误读**：已断裂召回 0 = 管线丢掉帧序
  - 正确：错。已实测换管线仍 0/33，管线不是零召回的原因
  - 出处：docs/project-todo.md:82
- **误读**：模型答不出帧数 = 模型缺陷
  - 正确：错。帧序输出属过期要求，现行契约 `analysis.user_prompt` 只要求四字段输出
  - 出处：pipeline/contracts/tensile_vlm_v4_1.json:168
