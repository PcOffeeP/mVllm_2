# V4.1 Stage D sealed-test release

2026-07-27 已完成 Stage D 数据前置门，但尚未授权或启动一次性推理。

- review queue：`v4-1-phase2-sealed_test-4f66487a6315`
- frozen review batch：`review-batch-6a8d94bd7675`
- sealed-test release：`v4.1-sealed-test-5546b8bf1ec3`
- release manifest SHA-256：
  `b996f0540681066de0731ffcab5a0f760bc691fcb6e6bd1e687eb150b7b96e72`
- review queue candidates：332
- admitted candidates：299
- excluded candidates：33
- admitted independent sources：20

发布器完整验证当前 V4.1 contract、queue、人工 batch、summary、实际媒体、帧哈希、
development source 隔离和 test split。受限 ground-truth 文件及目录权限分别为
`0600`、`0700`。轻量证据不包含逐样本真值、类别分布或 source-level 语义信息。

release manifest 的 `one_time_evaluation_authorized` 仍为 `false`。创建该数据发布不等于
Stage D 模型验收通过，也不授权读取逐样本预测或把测试结果用于调参。
