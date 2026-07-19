# 最终 Prompt 策略

## 决策

Prompt Engineering 阶段已经结束。项目只保留一个 `system_prompt` 和一个
`user_prompt`，二者的唯一编辑入口均为
`pipeline/prompt_library.yaml`。训练样本构建和核心评测读取这一对 Prompt；
`pipeline/contracts/tensile_vlm_v2.json` 将其逐字保存为生产 analysis 快照。
生产运行时只读取该自包含 artifact。Evidence 使用 artifact 内独立的固定观察 Prompt，
不进入训练数据，也不改变 analysis Prompt。

最终 Prompt 逐字复用当前 merged 模型的训练分布：

- 953 条 Fold 0 训练样本使用同一个 System Prompt；
- 固定 User Prompt 选自训练时真实使用的六个模板；
- 953 条 Assistant 目标均为四字段 JSON，且 `has_fracture` 均为 JSON 布尔值。

模型输出仍通过 `pipeline/output_normalizer.py` 做结构修复。Prompt 负责视觉判断，
Normalizer 负责字符串布尔、非法区间、非法类型及字段联动修复。

## 历史实验结论

固定 merged 模型、324 个 Fold 0 验证样本和 17 个源视频时：

| 变体 | has_fracture recall | precision | 结论 |
|---|---:|---:|---|
| light | 0.279330 | 0.617284 | Recall 最好，但原始字段较松散 |
| medium | 0.094972 | 0.708333 | 严格规则造成明显保守化 |
| medium_relaxed（归一化后） | 0.094972 | 0.680000 | 未改善 Recall，且输出向未断裂坍缩 |

`medium_relaxed` 的 324 条输出中有 299 条是同一个字符串布尔
`"has_fracture":"false"`。继续增加 Prompt 规则没有带来任务收益，因此删除历史
Sweep 产物并停止维护实验变体。历史细节仍可从 Git 记录恢复。

## 后续修改规则

后续若需调整 Prompt，只修改 `pipeline/prompt_library.yaml` 顶部的：

1. `system_prompt`
2. `user_prompt`

修改后必须重新运行静态测试、生成生产契约 hash，并在训练机对冻结测试集执行核心
评测。不得重新引入并行 Prompt 副本。
