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
正式人工审查尚未开始，当前没有冻结 review batch，也没有创建新的开发或密封测试发布。

密封测试队列及其未来决定不得进入训练、采样、学习曲线或模型选择流程。
