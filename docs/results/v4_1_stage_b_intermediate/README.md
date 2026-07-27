# V4.1 Stage B intermediate model acceptance

> 状态：上一轮完整 coverage-first seed3407 被接受为当前版本的中间开发模型；
> 原 Stage B 质量门和 LOSO 门仍明确为失败。

2026-07-27，用户明确要求停止继续重训练，以
`v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3` 的完整
seed3407 产物推进后续 pre-acceptance 和 Agent 集成。本决策没有改写旧 gate report、
没有降低旧阈值，也没有把失败结果标成质量通过。

新的 intermediate integration gate 只授权：

- V4.1 pre-acceptance 服务集成；
- TensileAgent V4.1 runtime 集成和 development/合成验证。

它不授权：

- 新一轮或完整三折/全量训练；
- 独立模型验收、production alias 或完整生产通过命名；
- 读取 sealed labels。

模型、训练、评测、原失败 gate 和 promoted runtime contract 已由训练机上的
`finetune/accept_v4_1_intermediate_model.py` 使用全量模型哈希冻结。完整 manifest
保存在训练机的内容寻址结果目录，轻量身份见 `acceptance_summary.json`。

本轮 prompt-clarified 训练在 75/1125 steps 时按用户决定精确停止；PID 已退出，
checkpoint-50、optimizer、trainer log 和 orchestration state 已原子移动到同盘
quarantine，未删除、未覆盖，也不作为当前模型产物。其 analysis prompt 已从历史
overlay 原样提升到两仓主 V4.1 contract artifact。
