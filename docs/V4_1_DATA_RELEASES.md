# V4.1 数据发布

## 正式身份与迁移对应关系

正式入口只接受完整 `data-v<协议>-r<N>` 身份。以下是已确认并完成复制迁移的 train 数据对应关系，状态以各 release 的 `release.yaml` 为准；本页引用 2026-09-14 前的验收记录，本轮未刷新训练机。

| 完整身份 | 迁移时状态 | 历史来源 | 用途 |
| --- | --- | --- | --- |
| `data-v4.1-r1` | superseded | `v4.1.0-760050fad303` | 基础发布；恢复历史引用，不能建立新训练引用 |
| `data-v4.1-r2` | active | `v4.1.0-ecb5aeb9657c` | Phase2 train 发布背景；新引用仍须在线校验状态与训练许可 |

目标为 `<store>/data/releases/<完整身份>/`，同级 `release.yaml` 描述状态及血缘，`payload/` 保存封存数据。训练机正式 store 的历史落点为 `/data/mVllm_2`；不得按目录日期、旧 active 指针或 LATEST 猜测版本。

[对象映射](results/version-control-migration/object-mapping.yaml)记录身份与状态决定；[验证记录第20–24节](results/version-control-migration/verification.md)记录复制、payload 验签及引用门。两份迁移发布仍引用原 workspace 的外部媒体，store 尚不自包含。删除、移动源媒体前必须扫描引用并完成备份及替代核验。

## Phase2 train 发布统计

历史发布 `v4.1.0-ecb5aeb9657c` 包含 1678 个唯一媒体，被历史 coverage-first Fold0 与 concise 三折实验使用。迁移保留其内容和 split，不重新构建冒充同一发布。

| Fold | Train | Validation |
| --- | ---: | ---: |
| 0 | 1253 | 425 |
| 1 | 1014 | 664 |
| 2 | 1186 | 492 |

## 基础发布统计

历史发布 `v4.1.0-760050fad303` 的统计如下，源证据见[有效视图审计](V4_1_PHASE1_EFFECTIVE_VIEW_AUDIT.md)及[Phase2发布记录](results/v4_1_phase2_development_release/README.md)。

| 项目 | 数量 |
| --- | ---: |
| 物化候选 | 1285 |
| 人工审查 | 774 |
| 自动稳定阴性 | 511 |
| 排除 | 10 |
| 正式发布 | 1275 |
| Fold 0 train / val | 850 / 425 |
| Fold 1 train / val | 830 / 445 |
| Fold 2 train / val | 929 / 346 |

## 构建、引用与测试边界

新发布由[现行数据手册](DATA_PROCESSING_RUNBOOK.md)的显式七阶段构建。更正数据生成新的完整身份，不原地修改封存 payload；DVC 内部哈希用于完整性，不是日常版本身份。

train 数据用于三折训练/validation 和全量训练；test 数据仅用于最终独立测试。上表不表示新的未使用 test 已就绪，使用资格、审查及封存依赖见[HOLDOUT-BUILD](project-todo.md)。

旧 `workspace/data/releases/<哈希身份>/` 及旧模型实验路径只用于历史证据追溯，不是新任务默认根。跨 release 比较需说明共同样本、采样、Prompt 与评分口径，不把全量分数差异直接归因为单变量。
