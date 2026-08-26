# V4.1 数据发布

本文记录 `main` 上当前 V4.1 训练数据的 development release 与历史基础发布统计。
详细的数据处理、审查与发布操作见 [数据处理与训练发布运行手册](DATA_PROCESSING_RUNBOOK.md)。

## 当前 development 发布

当前 development 发布：

```text
workspace/data/releases/v4.1.0-ecb5aeb9657c
```

该发布包含 1678 个唯一媒体，并被当前 coverage-first Fold0 模型和最新 concise Prompt
三折实验使用。各折记录数：

| Fold | Train | Validation |
| ---- | ----: | ---------: |
| 0    |  1253 |        425 |
| 1    |  1014 |        664 |
| 2    |  1186 |        492 |

## 历史基础三折发布

历史基础三折发布：

```text
workspace/data/releases/v4.1.0-760050fad303
```

基础发布统计：

| 项目                 |        数量 |
| -------------------- | ----------: |
| 物化候选             |        1285 |
| 人工审查             |         774 |
| 自动稳定阴性         |         511 |
| 排除                 |          10 |
| 正式发布             |        1275 |
| Fold 0 train / val   |   850 / 425 |
| Fold 1 train / val   |   830 / 445 |
| Fold 2 train / val   |   929 / 346 |

## 数据版本原则

两个发布都是内容寻址、不可覆盖的训练输入。更正数据必须生成新的发布编号，不能直接
修改现有发布目录。跨 release 比较必须提供共同样本分析，不能把全量指标差异直接归因于
Prompt 或训练策略。

活跃 V4.1 数据和运行产物使用项目内、Git 忽略的本地 workspace：

```text
workspace/
├── data/
│   ├── source/
│   ├── derived/
│   └── releases/
├── runs/<experiment-id>/
│   ├── input/
│   ├── adapter/ 或 fold*/adapter/
│   ├── merged/ 或 fold*/merged/
│   ├── evaluation/
│   └── logs/
└── models/
    ├── current -> releases/<model-name>
    ├── releases/
    └── archive/
```

首次从旧根迁移时执行（脚本已删除，见 git 历史）：

```bash
python pipeline/scripts/source_migrate_workspace.py --copy
python pipeline/scripts/source_migrate_workspace.py
```

迁移会把旧 `training_releases/` 物理复制为 `releases/`，并逐文件比较数量、字节数和
SHA-256；不会创建软链接，也不会删除旧根。`config/data_roots.json` 与
manage_versioned_data_roots.py（已归档，见 git 历史）仅用于历史 V2/V4.1 外部根复现。

更详细的数据入口、迁移设计与校验结果见 [数据处理与训练发布运行手册](DATA_PROCESSING_RUNBOOK.md)
以及：

- V2 封存与 V4.1 数据隔离设计（文档已归档，见 git 历史）
- V2 / V4.1 数据隔离迁移报告（文档已归档，见 git 历史）
- [项目实现与数据约定说明](./project-guide.md)
