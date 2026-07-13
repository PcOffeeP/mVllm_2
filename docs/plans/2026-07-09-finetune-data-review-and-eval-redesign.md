# 拉伸断裂微调流程优化计划：训练语义、审查 UI 与基础评估

## Summary

优化目标是让微调模型理解拉伸断裂标签，而不是学习固定 JSON 输出。流程分三块：

1. 训练样本改为多问法 + 结构化 JSON 监督。
2. 训练级和测试级子视频都进入同一套人工审查 UI。
3. 评估先保持轻量，重点保存模型原始输出，并保证 prompt 与训练一致。

默认决策：

- 训练输出采用严格的四字段 JSON。
- 训练 target 去掉 `confidence`。
- 推理时仍要求模型自行返回 `confidence`。
- 人工复查 UI 同时服务训练子视频和测试子视频。
- 评估集只保留两类：原测试视频、审核后的测试级子视频。
- 当前阶段不优先做复杂自动指标，先稳定保存 raw output。

## 1. 训练环节

建立统一 prompt 模板库，训练和推理必须从同一套模板生成。

训练 prompt 不再使用单一固定问法，而是为同一任务生成多种等价提问，覆盖：

- 是否断裂
- 断裂发生在哪两个采样帧之间
- 断裂模式
- 断裂位置
- 未断裂、视频异常、未夹紧等情况辨别

训练 assistant target 改为：

```text
{"has_fracture": ..., "fracture_between": ..., "type": ..., "location": ...}
```

训练 target 不包含 `confidence`。推理时结果区包含 `confidence`，由模型根据可见证据自行判断。

prompt 采用轻约束、强语义：重点解释判断标准，不使用过强 system prompt。

## 2. 子视频人工复查 UI

新增本地审查 UI 脚本，例如：

```text
pipeline/scripts/review_subvideos_app.py
```

优先使用 Streamlit 实现。

UI 支持两种输入：

- 训练级子视频 metadata
- 测试级子视频 metadata

左侧显示待审查列表：

- `subvideo_id`
- 源视频
- crop 类型
- 当前状态
- 风险等级
- 未审查、已通过、已丢弃、已修改过滤

中间显示审查内容：

- 子视频 mp4
- 采样帧图片或 contact sheet
- 窗口时间
- 帧映射
- `crop_type`
- `selection_reason`

右侧显示并允许修改标签：

- `has_fracture`
- `fracture_between`
- `type`
- `location`

审查操作：

- `审查通过`：记录通过状态，并保存当前标签。
- `丢弃子视频`：记录丢弃状态，导出时剔除该样本；默认不物理删除 mp4 和帧图。
- `需要重新生成`：记录阻塞状态，正式导出时失败并报告。

UI 写出 review decisions 文件：

```text
data/07_metadata/review_decisions/subvideo_train_review_decisions.json
data/07_metadata/subvideo_test_review_decisions.json
```

## 3. 数据导出与质量门

训练级子视频导出流程：

```text
subvideos_meta.json
+ subvideo_train_review_decisions.json
→ subvideos_meta.reviewed.json
→ subvideos_meta.label_reviewed.json
→ data/06_merged/fold_*_train.json / fold_*_val.json
```

测试级子视频导出流程：

```text
test_subvideos_meta.json
+ subvideo_test_review_decisions.json
→ 审核后的测试子视频 metadata
→ 测试级评估输入与 ground truth
```

正式导出要求：

- 所有样本必须是 `approved` 或 `dropped`。
- 存在未审查或 `needs_regenerate` 时失败。
- `dropped` 样本不进入训练或评估集合。
- 修正后的标签覆盖自动生成标签。
- 原始标签和审查记录必须保留，便于追溯。

质量检查先聚焦必要项：

- 训练 target 不含 `confidence`。
- 结果区可解析。
- 训练/推理 prompt 来自同一模板版本。
- 审查决策完整。

## 4. 测试评估

评估集保留两类：

1. 原测试视频：来自原始 test split。
2. 审核后的测试级子视频：由测试视频生成子视频后，经 UI 人工审核确认。

测试级子视频必须走与训练级子视频相同的人工审核 UI 流程。

当前阶段评估脚本主要保存 raw output：

- `evaluation_records.jsonl` 保存每条视频的原始返回。
- `evaluation_summary.json` 保存数据集、模型路径、prompt 模板版本、generation 参数、输出数量。

暂不优先做复杂自动指标，只保留基础检查：

- raw output 是否非空。
- 输出是否为可解析且字段完整的 JSON。
- prompt 是否与训练模板版本一致。

后续需要更严谨比较时，再扩展字段准确率、区间命中率、模式分类和位置判断等指标。

## 5. Test Plan

UI/审查流程测试：

- approved 样本进入导出结果。
- dropped 样本被剔除但媒体文件不删除。
- 修改标签后导出的 metadata 使用修正标签。
- 未审查和 `needs_regenerate` 阻塞正式导出。

训练样本测试：

- assistant target 不包含 `confidence`。
- 每条样本只含 `videos`、`messages`，且 assistant target 是可解析 JSON。
- prompt 变体来自统一模板源。

测试评估流程测试：

- 原测试视频和测试级子视频都能生成评估输入。
- 测试级子视频必须使用审核后的 metadata 和 ground truth。
- 评估输出完整保存 raw output、prompt 模板版本和模型信息。

## 6. Assumptions

- 暂不引入单独的“人工强确认小集”。
- 测试级子视频与训练级子视频一样需要人工审核。
- 当前阶段评估重点是保存模型原始输出和验证 prompt 一致性，不追求复杂自动打分。
- 丢弃样本默认只记录决策并在导出阶段剔除，不立即删除媒体文件。
