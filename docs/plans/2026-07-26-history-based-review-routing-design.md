# 基于上一轮审查的固定分流流程设计

## 目标与范围

把“存在上一轮冻结审查时，以上一轮审查为基准”固化为 V4.1 人工审查的内置流程。
系统先生成可追溯的分流清单，再把候选划分为：

- 当前轮已经人工完成；
- 可以按历史共识自动沿用；
- 必须进入本轮人工复审。

本流程只减少重复审查，不降低来源隔离、媒体哈希、候选身份和标签合法性门禁。

## 非目标

- 不把一个原视频压缩成唯一标签；同一原视频的不同窗口角色仍可有不同真值。
- 不把自动沿用记录伪装成 `human approved`。
- 不修改上一轮冻结 review batch、当前原始队列或已有人工决定。
- 不把 development 历史真值用于 sealed test；没有合格历史基线时仍全量人工审查。
- 不跨契约哈希或标签语义版本复用历史结果。

## 约束与假设

- 上一轮必须是已冻结、校验通过且与当前 `tensile-vlm/v4.1` 契约哈希一致的 review
  batch。
- 当前队列、上一轮 batch、媒体和阶段 1 审计都必须以路径和 SHA-256 绑定。
- 历史基准粒度为 `source_video + semantic_window_role`，而不是单纯
  `source_video`。第一版至少支持 `transition` 和 `post_event`。
- 当前轮已经保存的人工决定优先级最高，不能被历史自动沿用覆盖。
- 任一来源在上一轮出现 `corrected`、`dropped` 或 `needs_regenerate`，该来源的当前候选
  全部进入人工复审。

## 方案比较

### 方案 A：独立分流清单与历史沿用制品

生成一个内容寻址的 routing manifest。每个候选明确记录
`existing_human / historical_consensus / manual_review`，自动沿用项另存历史来源、
角色共识、引用决定和标签。

优点是不会伪造人工审批，发布器可以区分真值来源，历史和当前决定都可追溯。缺点是发布阶段
需要显式合并三类输入。

### 方案 B：给 review decision schema 增加自动状态

增加 `carried_forward` 状态并与人工决定保存在同一 batch。实现集中，但容易让下游把自动
状态误算为人工 reviewed，也会扩大现有决定 schema 的语义。

### 方案 C：把历史标签预填成 `approved`

改动最少，但会把未由本轮审核者确认的标签伪装成人工批准，无法满足审计要求，不采用。

采用方案 A。

## 固定分流规则

按以下顺序处理每个当前候选，先命中的规则优先：

1. 当前轮已有合法人工决定：标记 `existing_human`，原样保留。
2. 没有上一轮冻结 batch、身份不匹配或契约哈希不同：标记 `manual_review`。
3. 该 `source_video` 在上一轮出现任一 `corrected / dropped / needs_regenerate`：
   标记 `manual_review`。
4. 无法从当前候选和历史候选确定相同的 `semantic_window_role`：
   标记 `manual_review`。
5. 同一 `source_video + semantic_window_role` 的上一轮有效标签不是唯一共识：
   标记 `manual_review`。
6. 历史共识与当前候选提示标签不完全一致：标记 `manual_review`。
7. 其余候选标记 `historical_consensus`，沿用唯一历史共识。

`historical_consensus` 只表示满足固定复用策略，不表示本轮人工看过。

## 组件与职责

- 历史路由器：读取当前队列、上一轮冻结决定和当前草稿，生成 routing manifest。
- 角色归一化器：从受支持的候选字段或候选 ID 映射
  `transition / post_event / pre_event / other`；未知角色 fail closed。
- 历史共识生成器：只使用上一轮 `approved` 的有效标签，并输出参与共识的历史决定 ID。
- 人工子队列：只包含 `manual_review` 候选；若这些候选已有当前轮决定，则迁移并校验后保留。
- 历史沿用制品：保存自动项标签、上一轮 batch/hash、引用决定、策略版本和当前队列身份。
- 发布门禁：未来发布器必须分别统计 `existing_human`、`historical_consensus` 和新人工决定，
  不得把后二者合并成同一个人工计数。

## 数据流与状态

```text
当前完整队列
  + 上一轮冻结 review batch
  + 当前轮已有 draft
  + 契约/审计/媒体身份
            |
            v
    history-based router
      |        |        |
      |        |        +--> manual_review 子队列
      |        +-----------> historical_consensus 制品
      +--------------------> existing_human 引用
            |
            v
      内容寻址 routing manifest
```

重复运行相同输入必须得到相同 routing ID。既有目标存在时只允许逐字节一致的幂等复用，
拒绝覆盖或静默更新。

## 当前批次预期分流

development 当前 410 项：

- 已有当前轮人工决定：33 项，来自 4 个上一轮仅 `approved` 的来源；
- 可按历史角色共识自动沿用：其余 233 项；
- 上一轮出现 `corrected`：117 项、12 个来源，人工复审；
- 上一轮出现 `dropped`：27 项、3 个来源，人工复审。

因此 development 人工待审范围为 144 项。已有 33 项不重复进入待审队列。

sealed test 的 332 项与 development 来源隔离，没有合格的上一轮同源基线，因此仍为
332 项人工待审。

## 失败处理

- 上一轮 batch 未冻结、哈希漂移或决定 schema 非法：全部转人工，不部分复用。
- 当前人工决定与历史共识冲突：保留当前人工决定并记录冲突，不自动回退。
- 候选角色未知、历史角色没有记录或共识不唯一：转人工。
- 当前提示与历史共识不一致：转人工，并在 routing manifest 记录差异。
- development 与 sealed test 来源重叠：整个分流失败。
- 自动沿用项进入人工计数或缺少历史引用：发布门禁失败。

## 测试策略

- 单元测试覆盖全部七条优先级规则。
- 覆盖同一来源多种窗口角色，证明不会使用单一源视频级标签。
- 覆盖 `corrected / dropped / needs_regenerate` 任一状态触发整源复审。
- 覆盖当前轮人工决定优先并可迁移到人工子队列。
- 覆盖历史共识与当前提示一致及冲突路径。
- 覆盖无历史、契约漂移、batch 漂移、角色未知和重复 candidate ID。
- 使用当前真实轻量清单验证 development 分流为
  `33 existing + 233 historical + 144 manual`，sealed test 为 `332 manual`。
- 运行现有全量测试和 `git diff --check`。

## 迁移与发布边界

第一版只生成 routing manifest、历史沿用制品和人工子队列，不创建训练或密封测试发布。
当前 410/332 原始队列继续只读保留。发布器适配作为后续独立步骤，在人工决定冻结后执行。

本设计取代旧设计中“历史结果只能用于展示、所有新增媒体必须逐条重审”的绝对规则，但只在
上述冻结身份、整源稳定和角色级唯一共识同时满足时允许复用；其他情况仍 fail closed
进入人工审查。
