# 项目任务清单

> 最后更新：2026-05-28

## ⚠️ 重要前提

- **数据已就绪**：110 个视频，stratified 3-fold，merged JSON 在 `data/04_merged/`
- **v1 训练效果差**：type accuracy 9.2%，time MAE 242s
- **v2 改善空间有限**：配置已就绪但未执行；训练耗时长，请控制投入预期

## 1. 数据清洗（优先级最高）

- [x] 统一时间格式：CSV 时间格式已统一为 `<float>s` ✅
- [ ] 产出数据冻结报告：样本数、类别分布、fold 分布、清洗规则

## 2. MiniCPM v2 重训闭环

- [ ] 启动 v2 全量重训（依赖标签和时间格式统一）
- [ ] v2 推理：time / type / joint 三类任务
- [ ] v2 评测：与 v1 指标对比（baseline: type acc 9.2%, time MAE 242s）

## 3. 多模型横向对比（均未开始）

候选模型：InternVL3.5-8B / GLM-4.1V-9B-Thinking / MiMo-VL-7B-RL-2508 / Qwen3-VL-8B-Instruct

- [ ] 确认各模型 LLaMA-Factory 支持情况
- [ ] 准备各模型配置草案（template、数据键、输出目录）
- [ ] 各模型 smoke test（小样本通过预处理和最小训练步骤）
- [ ] 形成框架决策表：LLaMA-Factory 可行 / 需 fallback / 暂缓
- [ ] 选择下一轮正式训练模型（按可行性、资源、预期收益排序）
