# 已过期原设计与迁移映射

> 状态：已过期
> 当前设计：[`docs/PROJECT_PLAN.md`](../PROJECT_PLAN.md) v2

本目录保存 v2 项目计划批准前的三份原设计文档，仅用于追溯。它们包含已经废弃的 `N/A`、边界哨兵、旧最终输出和旧终止条件，不能直接指导实现。

| 归档文档 | 已纳入项目计划的内容 | 后续实施方案需要承接的细节 |
|---|---|---|
| [`model_agent_interface.md`](./architecture/model_agent_interface.md) | 系统分层、五字段模型输出、HTTP 模型服务、Agent 公共结果 | 精确 JSON Schema、HTTP 媒体传输、工具结果契约、Prompt、错误与重试、公共与诊断输出序列化 |
| [`model_finetuning_design.md`](./architecture/model_finetuning_design.md) | CSV 权威性、视频级划分、ShareGPT 数据接口、MiniCPM-V 4.6 与 LoRA 路线 | 样本类型、片段生成、metadata、LLaMA-Factory 配置、真实预处理核对、数据质量验证 |
| [`agent_iteration_design.md`](./architecture/agent_iteration_design.md) | 双决策后端、程序状态机、完整覆盖、局部重复确认、Runner 与评估方向 | 工具调用、状态转移、上下文历史、候选范围更新、冲突处理、终止原因、配置与回归测试 |

迁移规则：

- 只迁移与 v2 项目计划一致的细节；冲突内容必须重新设计，不能照搬。
- 每项细节只能由一个实施方案负责，避免模型契约、数据构建和 Agent Runtime 重复定义同一规则。
- 对应实施方案批准并验证后，才可以删除归档文档。
