# V4.1 Agent pipeline Fold0 R1 deployment

`v4.1-agent-pipeline-fold0-r1` 是当前项目唯一晋级到
`workspace/models/releases/` 的中间开发模型。它来自 coverage-first、seed 3407
的 Fold0 训练结果，其价值是已经走通训练、合并、推理服务和 TensileAgent 调用链路；
它不代表三折最优、全量训练、独立测试通过或生产发布。

2026-07-29 完成模型资产重构后，训练机使用
`workspace/models/current/merged` 重新启动 loopback 推理服务。发布目录中的 merged
和 adapter 均通过完整聚合哈希校验，真实拉伸 MP4 服务冒烟与 TensileAgent 开发冒烟
通过。历史 Stage B、Stage D 和 Stage G 质量结论未改变。

Checkpoint 本轮仅随实验 adapter 迁移到 `workspace/runs/`，没有删除；清理策略将在
后续单独执行。
