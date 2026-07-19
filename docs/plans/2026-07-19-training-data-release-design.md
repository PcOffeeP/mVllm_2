# 训练数据发布目录设计

## 目标与范围

将数据处理工作区和可直接训练的最终产物明确分离。`data/03_subvideos` 至
`data/07_metadata` 继续保存生成、审核、筛选、检查和冻结过程；只有通过质量门并由
发布脚本写入 `data/08_training_ready/<release_id>/` 的文件才允许用于训练。

本次整理不重新生成样本、不改变样本内容和数据划分，也不执行训练或 GPU 评测。

## 方案比较

1. 直接重排 `06_merged` 和 `07_metadata`：目录最彻底，但会破坏大量脚本默认值和
   历史命令，迁移风险高。
2. 只重命名现有文件：改动小，但处理中与可训练状态仍混在同一目录，无法形成发布门。
3. 新增版本化发布目录：保留可追溯的处理工作区，同时提供唯一、只读式训练入口。

采用方案 3。

## 发布目录

```text
data/08_training_ready/<release_id>/
├── datasets/
│   ├── train/fold_{0,1,2}.json
│   ├── validation/fold_{0,1,2}.json
│   └── evaluation/
│       ├── source_videos/{inputs,ground_truth}.json
│       └── subvideos/{inputs,ground_truth}.json
├── metadata/training_subvideos.json
├── reports/{sample_statistics,quality_check}.json
└── manifest/{data_version_lock,release_manifest}.json
```

`release_id` 默认由数据版本锁的版本号和样本清单 SHA-256 前八位组成，例如
`v2.0.0-1dab1e5e`。相同 ID 已存在时拒绝覆盖；发布过程先写临时目录，全部复制和哈希
校验成功后再原子改名。

## 发布规则

- 发布前要求质量报告 `error_count == 0`。
- 训练 metadata 必须是以 `.label_reviewed.json` 结尾的正式产物。
- 六个 fold 文件、样本统计、质量报告和数据版本锁缺一不可。
- 两组评估文件各自必须成对出现；允许整组不存在，不允许只存在一半。
- `release_manifest.json` 记录每个发布文件的用途、来源、大小和 SHA-256。
- 发布目录只包含消费端需要的最终文件，不复制审核队列、决策 delta 或生成中间态。

## 消费端与迁移

`finetune/dataset_info.json` 和本地评估读取路径改为当前发布版本；
`finetune/active_data_release.json` 是当前版本的唯一指针。现有
`data/06_merged`、`data/07_metadata` 文件保留作为来源和历史证据，不移动、不覆盖。
下一轮重新处理数据后，先完成原有四个质量门，再运行发布脚本并显式切换消费端版本。

## 验证

- 单元测试覆盖缺失文件、失败质量报告、成对评估文件、确定性 ID、拒绝覆盖和 manifest
  哈希。
- 对当前已构建产物发布一次，并逐文件比对 SHA-256。
- 运行数据发布相关测试及现有数据质量测试；不在本机启动训练或 GPU 评测。
