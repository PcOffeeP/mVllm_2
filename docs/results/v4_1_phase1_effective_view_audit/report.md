# V4.1 有效视图审计历史报告（2026-07-25）

本文保留当时的审计方法、来源和结果，不作为新数据批次的操作手册。现行处理见[数据流程](../../data-workflow.md)，冻结结果仍在本目录。

阶段 1 只生成审计与人工复审候选，不创建训练发布，也不把自动标签或 V3 标签提升为
V4.1 真值。

## 当时的审计入口

```bash
python -m finetune.eval_audit_effective_views \
  --test-materialized \
  /home/liuyang/文档/tensile-data/current/derived/metadata/v4_1/\
test_audit_candidate_media_results/candidate-media-53d068569a09/\
test_materialized_audit.json \
  --output-dir \
  /home/liuyang/文档/tensile-data/current/derived/metadata/v4_1/\
effective_view_audits/phase1_verified
```

默认输入绑定：

- 正式发布 `v4.1.0-760050fad303`；
- 正式发布对应的 `candidate-media-8de972530561` 实际抽帧记录；
- 410 项实验候选对应的 `candidate-media-b442478052cd`；
- V3 `candidate-plan-ce36b9226be5` 中隔离的 test-audit 候选。

有效帧签名是 `source_video + actual_frame_mapping.original_frame` 的内容哈希。它不使用
计划窗口代替模型实际采样帧。近重复簇只在同一源视频内计算，默认以有效帧首尾包络
IoU `>= 0.80` 合并。单源贡献报告默认门槛为池内 `10%`。

## 2026-07-25 审计结果

- 审计 ID：`effective-view-audit-eeb18caba8bd`
- 正式发布：1275 项、85 个源、1275 个唯一有效视图；
- 自动候选：410 项、44 个源、410 个唯一有效视图；
- 其中 252 项未与正式发布形成近重复簇，158 项与正式发布近重复；
- test-audit：332 项、20 个可物化源、332 个唯一有效视图；
- 原 test 清单共 21 个源；`video_0005` 因 `视频异常` 被旧计划跳过；
- test-audit 332 个视频和 2142 张实际采样帧的 SHA-256/大小校验全部通过；
- 三折中每折训练源与验证源互斥；
- 85 个开发源与 21 个 test 源互斥；
- 三个池都没有精确重复签名，单源贡献均未超过 10%。

完整轻量制品位于
[`docs/results/v4_1_phase1_effective_view_audit/`](.)。

## 人工复审边界

- `development_review_candidates.json` 包含 410 项开发候选；
- `sealed_test_review_candidates.json` 包含 332 项独立测试候选；
- 两份清单中的历史标签仅是 `v3_unreviewed_hint`，`labels_are_truth=false`；
- 阶段 2 必须从实际帧画面重新判断四个 V4.1 字段；
- 密封测试真值冻结后不得进入训练、采样、学习曲线或模型选择流程。

## 尚未形成覆盖的能力

| 能力 | 有效样本 | 唯一有效视图 | 独立源 | 状态 |
|---|---:|---:|---:|---|
| 证据不足且 `special_case=null` | 0 | 0 | 0 | 未验收 |
| `未夹紧` | 0 | 0 | 0 | 未验收 |
| `视频异常` | 0 | 0 | 0 | 有 1 个真实源待生成候选，仍未验收 |

`video_0005` 只能作为待生成和人工判断的真实 `视频异常` 来源，不能用旧 V3 标签直接
创建 V4.1 真值。人为遮挡、降质或截断媒体只能进入鲁棒性对照池，不能计入真实来源覆盖。

## 产物说明

- `coverage_report.json`：按池、状态、特殊情况、组合和源统计覆盖；
- `leakage_report.json`：折内源隔离、开发/测试隔离和近重复簇；
- `development_review_candidates.json`：开发人工复审候选；
- `sealed_test_review_candidates.json`：隔离测试人工复审候选；
- `unable_judgment_pool.json`：三类 `无法判断` 能力的覆盖或缺口；
- `audit_manifest.json`：输入哈希、完整库存、策略和完成门禁；
- `manifest.json`：上述轻量制品的 SHA-256 索引。

阶段 1 结果不会修改旧发布 `v4.1.0-760050fad303`。
