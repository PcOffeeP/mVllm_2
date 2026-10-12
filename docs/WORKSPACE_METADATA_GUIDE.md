# 工作目录与历史元数据说明

## 正式 store 的职责

新数据任务使用显式 store、inputs 和 batch，入口为 `python -m versioning`。工作产物位于 `<store>/data/working/<batch>/`，发布位于 `<store>/data/releases/<完整data身份>/`；test 分支使用受限工作区及隔离真值。准确目录与输入 schema 见[versioning 索引](../versioning/SCRIPTS.md)和[数据手册](DATA_PROCESSING_RUNBOOK.md)。

正式 Prompt 位于 `<store>/records/prompts/<完整身份>.yaml`，训练冻结副本位于 `<store>/workspace/runs/<train身份>/input/`。MLflow 管实际训练、评测与模型记录；Git 中导出的 manifest 是单向证据，不反写源对象。

新体系不使用集合 index.json、LATEST、短哈希或 artifact resolver 历史回退选择正式版本。数据身份、许可、封存及输入一致性须通过在线门校验，目录存在不足以证明可训练。

## 旧 workspace 的历史区域

以下解释旧 `workspace/data/derived/metadata/` 布局，基于 2026-07-29 历史目录记录。它不规定新批次写入位置，今天的目录存在性须在训练机刷新。

| 区域 | 历史内容 | 保留边界 |
| --- | --- | --- |
| 根级 JSON 和审阅目录 | 早期子视频、质量报告、审阅决定 | 保留冻结引用，不继续生成同类散文件 |
| `v3/` | ROI、候选计划/媒体、审阅参考 | 部分历史库按明确 artifact ID 读取 |
| `v4/` | 过渡审阅队列和决定 | 依据冻结 manifest 或明确路径追溯 |
| `v4_1/` | 审阅、审计、source-aware 与 fixed-prompt 实验 | 历史实验配置仍可能直接引用 |
| 无版本语义 collection | 原 source/split snapshot、候选、队列和决定 | 旧 staging/promote 方案的产物，不是 versioning 当前写入规则 |
| `workspace/data/releases/<旧身份>/` | 原封存训练输入及媒体引用 | 通过[发布映射](V4_1_DATA_RELEASES.md)核对新身份，不能绕过正式训练引用门 |

`pipeline/artifact_resolver.py` 等历史模块仍供共享业务及报告使用；其中 collection 回退属于 legacy 读取能力。公开旧重建、ROI物化、候选/队列写入与 promote 编排 CLI 已停用，保留库不授予旧写入资格。精确入口状态见[迁移清单](results/version-control-migration/entrypoint-map.md)。

## 查找与清理

新任务从完整版本、阶段 manifest 与冻结输入追溯媒体及决定。历史实验从原运行 manifest 的明确 ID、路径和内容摘要查找，不能用版本号大小或目录修改时间推断当前对象。

旧路径被发布、实验配置、人工决定及新迁移对象的外部引用绑定。原位移动、改名或删除可能破坏可读性与复现证据；只读保留优先于目录整齐。数据迁移不等于外部媒体已复制进 store。

清理继续按[MODEL-ARCHIVE及项目台账](project-todo.md)执行：先完成引用扫描、必要配置/日志/预测归档、完整性和备份核验，再按获准清单操作。不删除唯一源、不跟随链接误入发布库，不把缺文件解释为未使用。

## 导航

- [项目指南](project-guide.md)：链路关系和双机连接。
- [数据手册](DATA_PROCESSING_RUNBOOK.md)：当前输入、工作阶段和发布步骤。
- [数据发布](V4_1_DATA_RELEASES.md)：正式身份、状态及历史统计。
- [验证记录](results/version-control-migration/verification.md)：迁移与恢复证据。
