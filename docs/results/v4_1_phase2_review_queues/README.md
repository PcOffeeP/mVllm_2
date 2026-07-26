# V4.1 阶段 2 隔离审查队列

2026-07-25 已从冻结审计 `effective-view-audit-eeb18caba8bd` 生成两个内容绑定的
人工审查队列：

| scope | queue ID | 候选 | 独立源 |
| --- | --- | ---: | ---: |
| development | `v4-1-phase2-development-dc453f01fb23` | 410 | 44 |
| sealed test | `v4-1-phase2-sealed_test-a16926aca6d2` | 332 | 20 |

两个队列均绑定 V4.1 契约、阶段 1 审计、materialized 输入和候选集合哈希，并声明
`labels_are_truth=false`。完整加载已经逐项验证视频和模型采样帧；开发与密封测试源视频
交集为空。

队列保存在训练机的 V4.1 数据根，不进入 Git。此目录只保存可追溯的轻量身份。

2026-07-26 已用上一轮冻结 batch `review-batch-9043bbe4c286` 按固定历史基准规则生成
内容寻址分流：

| scope | routing ID | 已有人工决定 | 历史一致沿用 | 人工待审 |
| --- | --- | ---: | ---: | ---: |
| development | `history-review-route-0b2c1c78a832` | 33 | 233 | 144 |
| sealed test | `history-review-route-fecdab9f5502` | 0 | 0 | 332 |

development 的人工待审范围只包含上一轮标签曾变化、被丢弃或需要重生成的同源候选；
已有 33 条当前人工决定不重复进入待审。历史一致沿用项独立保存为
`historical_consensus`，不记作本轮人工批准。sealed test 没有合格同源历史，因此保持
全量人工审查。

训练机分流制品位于
`data/current/derived/metadata/v4_1/review_routes/<routing-id>/`，每个目录包含
`routing_manifest.json`、`manual_candidate_ids.json`、
`historical_consensus.json` 和 `existing_human_decisions.json`。重复运行得到相同
routing ID；原始队列和 development 完整草稿未被修改。

当前仍没有阶段 2 冻结 review batch，也没有创建新的开发或密封测试发布。

密封测试队列及其未来决定不得进入训练、采样、学习曲线或模型选择流程。
