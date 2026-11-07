# 现有子视频生成与默认标签

本文梳理 `versioning data subvideo` 实际调用的代码。这里的**默认标签**是生成候选片段时根据源记录和时间窗口推导的初始标签；它不是人工审查结论，也不是模型预测。

本文只依据静态代码，未运行子视频生成或验证视频画面。旧标签语义不等同于当前人工标注说明。

**失效条件：** 子视频入口、候选规划、标签映射或审查衔接发生影响本文规则的变更时，本文作废；届时将仍有效的内容并入 `docs/facts.yaml`，或删除本文。

## 1. 从输入到审查

```text
冻结输入 + ROI 阶段产物 + 批次
             ↓
按开发集和测试审计的源视频清单规划候选
             ↓
按时间窗口生成候选区间及默认标签
             ↓
裁剪视频 → 按预处理器采样 → 检查采样门禁
             ↓
通过的候选进入清单；未通过的候选记录排除原因
             ↓
审查导出 → 人工审查 → 审查结果回收 → 开发集发布
```

入口为 `python -m versioning data subvideo`，需要显式指定根目录、冻结输入和批次。它读取 ROI 阶段清单、预处理器配置及文件，以及开发集和测试审计的参考记录；两组源视频分别规划，测试候选的 scope 为 `test_audit`。参考记录还参与部分窗口选择与匹配。

代码位置：[阶段分派和子视频阶段](../versioning/data_pipeline.py) 的 `run_stage`、`run_input_subvideo`。

## 2. 哪些源视频参与生成

| 源记录条件 | 处理 |
| --- | --- |
| 明确为断裂，且有可靠事件时间 | 生成事件前、包含事件和事件后候选 |
| 明确为未断裂 | 生成未断裂候选 |
| 断裂，但事件时间缺失或不可靠 | 跳过，并记录原因 |
| 未夹紧、视频异常或无法归类 | 跳过，并记录原因 |

这里的分类来自输入记录字段；规划器不会重新观看视频判断源视频状态。

代码位置：[候选规划](../pipeline/v3_candidate_plan.py) 的 `_source_kind`、`_build_scope_candidates`、`_skip_record`。

## 3. 片段窗口怎样选

### 通用规则

| 项目 | 代码规则 |
| --- | --- |
| 目标时长 | 尝试 2、3、5、10、20 秒；不是每个源视频都能产生所有时长 |
| 帧对齐 | 按 ROI 视频的帧率和总帧数确定起止帧，并记录对应时间和时长 |
| 最短时长 | 候选不足 1 秒时不加入 |
| 事件保护间隔 | 事件前、后各留 0.5 秒；断前或断后窗口不跨入该间隔 |
| 去重和上限 | 帧区间与状态相同的候选去重；不同窗口角色分别有数量上限 |
| 状态检查 | 窗口推导出的状态必须符合该窗口角色的预期，否则不加入 |

**事件后长度的边界：** 当前代码检查的是候选最短 1 秒，不表示已经检查事件后至少有 2 秒素材。

代码位置：[候选规划](../pipeline/v3_candidate_plan.py) 的常量、`_aligned_interval`、`_raw_candidates_for_source`。

### 按源视频类型选窗口

| 源视频 | 窗口 | 选择方式 |
| --- | --- | --- |
| 断裂 | 包含事件 | 尝试不同目标时长和事件相对位置；标准窗口放不下时，还会尝试自适应窗口 |
| 断裂 | 事件前 | 根据源断裂类型选择靠近事件的窗口，或在事件前区间取前、中、后窗口 |
| 断裂 | 事件后 | 从事件时间加 0.5 秒开始，可取完整剩余段及其分段 |
| 未断裂 | 未断裂窗口 | 在整段视频中按目标时长取窗口；位置由视频 ID 的哈希确定性轮换 |

包含事件的窗口会参考历史记录：已批准或已修正的记录中，帧范围和标签均完全一致的数量会影响模板排序。

代码位置：[候选规划](../pipeline/v3_candidate_plan.py) 的 `_transition_templates_for_source`、`_selected_pre_event_durations`、`_post_event_windows`、`_raw_candidates_for_source`。

## 4. 默认标签怎样确定

### 第一步：按窗口确定断裂状态

下表中的“事件”指源记录提供的可靠事件时间。条件按代码顺序判断。

| 条件 | `clip_state` |
| --- | --- |
| 源视频为未断裂 | 未断裂 |
| 断裂源的片段结束时间 ≤ 事件时间 − 0.5 秒 | 未断裂 |
| 断裂源的片段开始时间 ≥ 事件时间 + 0.5 秒 | 已断裂 |
| 断裂事件严格位于片段开始和结束之间 | 发生断裂 |
| 其他情况 | 无法判断 |

规划器最终只保留与窗口角色预期状态相符的候选。例如，事件前窗口必须得到“未断裂”。

### 第二步：填充其他字段

| 字段 | “发生断裂”或“已断裂” | 其他状态 |
| --- | --- | --- |
| `fracture_mechanism`、`root_break` | 按源记录 `type` 的旧类型映射填写；未匹配时为 `null` | `null` |
| `location` | 仅保留合法的 `location_canonical`：`inside_gauge` 或 `outside_gauge` | `null` |
| `special_case` | `null` | 仅“无法判断”时取源类别对应的特殊情况 |

未夹紧和视频异常源在候选规划时会被跳过；“无法判断”也不符合正常窗口角色的预期状态，因此不能把 `special_case` 的字段规则理解为这些源会正常生成候选。

例如，旧类型“韧性断裂”映射为韧性机制和 `root_break=false`；“齐根断裂”映射为机制 `null` 和 `root_break=true`。代码会校验字段和组合。**时间与源标签推导出的结果，即使内部自洽，也不能证明画面中的标签正确。**

代码位置：[候选规划](../pipeline/v3_candidate_plan.py) 的 `_state_for_interval`、`_candidate_labels`；[v3 标签规则](../pipeline/v3_labels.py) 的 `_LEGACY_TYPE_MAP`、`map_legacy_fracture_type`、`validate_v3_labels`。

## 5. 裁剪和采样怎样把关

代码按候选起止帧裁剪 ROI 视频，生成子视频，并依据冻结的预处理器生成采样帧和映射。视频与采样映射经过检查后，才会进入成功物化的候选清单。

| 检查对象 | 规则或结果 |
| --- | --- |
| 发生断裂候选 | 采样须覆盖事件前，以及事件时或事件后 |
| 断前、断后候选 | 采样不得越过各自的 0.5 秒保护边界 |
| 采样门禁不通过 | 排除候选并记录原因 |
| 预处理器指纹不一致、采样数超限等 | 阶段失败 |
| 阶段清单 | 记录规划、成功物化、排除和跳过的信息 |

代码位置：[子视频阶段](../versioning/data_pipeline.py) 的 `run_input_subvideo`；[媒体处理](../pipeline/v3_candidate_media.py) 的 `build_crop_command`、`validate_actual_sampling_gate`。

## 6. 默认标签如何进入审查

### 规划标记与审查队列

| 阶段 | 对象 | 处理 |
| --- | --- | --- |
| 候选规划 | “发生断裂”“已断裂” | 标记 `manual_required` |
| 候选规划 | 普通“未断裂” | 标记 `automatic_validation` |
| 开发集审查导出 | 已物化的断裂候选 | 加入审查包，生成 v4.1 建议标签 |
| 开发集审查导出 | 源类型恰为“韧性断裂”，且窗口为 `pre_event_back` 的特定断前候选 | 也加入审查包，生成“临界未断裂”建议标签 |
| 测试审计导出 | `test_audit` 候选 | 使用独立的 scope 分支 |

规划标记不是审查完成证明。尤其是特定断前候选：规划时可标为 `automatic_validation`，审查导出仍会把它选入人工审查。

### 回收与发布

1. `review_import` 要求回收结果与导出批次和清单绑定，完整覆盖审查队列，并通过标签及证据检查。
2. 开发集发布时，需要人工审查的候选若缺少决定，会报错；被标为丢弃或需要重新生成的候选被排除。
3. 未进入人工队列的候选，只有转换并校验为普通“未断裂”标签时才能自动准入。

代码位置：[候选规划](../pipeline/v3_candidate_plan.py) 的 `_build_scope_candidates`；[审查及发布阶段](../versioning/data_pipeline.py) 的 `run_input_review_export`、`_validate_input_review_return`、`_input_release_rows`；[审查候选规则](../pipeline/v4_1_review_workflow.py) 的 `_is_incipient_candidate`、`_proposal`。

## 7. 入口边界与待确认事项

| 对象 | 状态 |
| --- | --- |
| `versioning data subvideo` | 本文所述入口，复用 v3 候选规划及媒体函数 |
| `pipeline/scripts/subvideo_build_plan.py`、`pipeline/scripts/subvideo_materialize_media.py` | 旧独立命令入口已停用；文件内仍保留旧实现 |
| [归档生成器](../pipeline/scripts/archive/subvideo_builder.py) | 更早的历史逻辑，字段和默认值不能直接套到本文入口 |

代码位置：[旧命令索引](../pipeline/scripts/SCRIPTS.md)、[规划命令](../pipeline/scripts/subvideo_build_plan.py)、[媒体命令](../pipeline/scripts/subvideo_materialize_media.py)。

仅看代码不能确定某次实际批次使用了哪些输入、生成了哪些片段、标签是否符合画面，以及人工审查是否完成。这些事项须对照该批次产物和审查记录确认。
