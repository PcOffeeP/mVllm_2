# Workspace 元数据目录说明

本文帮助开发者和数据审阅人员理解训练机
`workspace/data/derived/metadata/` 中同时存在根级文件、`v3/`、`v4/`、`v4_1/`
以及新语义目录的原因。它描述的是物理目录与使用边界，不替代 artifact manifest、
release manifest 或数据处理运行手册。

## 一句话原则

- `workspace/data/releases/<release-id>/` 是可直接用于正式训练的冻结输入；
- `workspace/data/derived/metadata/` 保存中间 manifest、候选、审阅和质量证据，
  不能仅凭目录名判断其是否可训练；
- `v3/`、`v4/`、`v4_1/` 是历史链路产物，默认只读，不原地移动、覆盖或删除；
- 新任务不再创建新的版本号父目录，而是写入无版本的语义 collection；
- 查找 artifact 时使用 manifest 中的 ID 和 tree hash，不使用“看起来最新”的目录。

## 当前目录地图

截至 2026-07-29，训练机正式数据根中的元数据大致如下：

```text
workspace/data/derived/metadata/
├── <根级历史 JSON 和审阅目录>
├── v3/
│   ├── roi_manifests/
│   ├── candidate_plans/
│   ├── candidate_media_results/
│   ├── review_reference/
│   └── review_decisions/
├── v4/
│   ├── review_queues/
│   └── review_decisions/
├── v4_1/
│   ├── review_queues/
│   ├── review_decisions/
│   ├── review_routes/
│   ├── effective_view_audits/
│   ├── experiments/
│   ├── source_aware_3k/
│   └── fixed_prompt/
└── <新语义 collections，随新 run 晋级后逐步出现>
    ├── source_snapshots/
    ├── split_snapshots/
    ├── roi_manifests/
    ├── candidate_plans/
    ├── candidate_media_results/
    ├── review_reference/
    ├── review_queues/
    └── review_decisions/
```

新语义 collection 没有全部出现并不表示代码仍应写旧目录。它们会在新的
`workspace/data-staging/<run-id>/` 通过人工门禁并正式 promote 后逐步进入正式数据根。

## 各区域的含义

| 区域 | 状态 | 主要内容 | 使用规则 |
| --- | --- | --- | --- |
| 根级旧文件和目录 | 历史遗留 | 早期 subvideo metadata、质量报告、审阅决定 | 只读；新代码不得继续生成同类根级散文件 |
| `v3/` | 历史正式链路 | ROI manifest、候选计划、候选媒体和审阅参考 | 只读兼容；部分旧 artifact 可由当前 resolver 按 ID 回退读取 |
| `v4/` | 短期过渡链路 | 一组 V4 queue 和 draft decision | 只读历史证据；当前不属于标准兼容解析入口 |
| `v4_1/` | 历史及现有实验 | V4.1 审阅、审计、实验数据 bundle | 只读或冻结实验输入；禁止继续把它当作新产物父目录 |
| 无版本语义 collection | 当前目标布局 | source/split snapshot、候选、队列、决定 | 新 run 的唯一正常 metadata 写入布局 |
| `releases/<release-id>/` | 正式发布 | 冻结训练 JSON、媒体引用和 release manifest | 只读；正式训练优先且原则上只使用这里 |

## 为什么不直接重命名旧目录

旧目录路径已经被以下证据引用：

- artifact manifest 和 release manifest；
- 已完成实验的运行配置、日志和结果摘要；
- 人工审阅 queue、decision 和审计报告；
- 内容寻址 ID、tree hash 与历史复现流程。

原地移动或合并目录会让这些冻结引用失效，也可能使历史实验无法复核。因此当前迁移采用：

1. 旧产物原位只读保留；
2. 新写入切换到语义 collection；
3. 读取时按精确 artifact ID 查找新路径，必要时回退受支持的历史路径；
4. 等新布局经过真实人工审阅、promote、训练和评测后，再单独制定历史归档方案。

这是一项兼容性选择，不代表旧目录已经整理完成。

## 人工查找规则

### 查找正式训练数据

从对应实验的 `release_manifest.json` 或 training run manifest 获取 `release_id`，然后查看：

```text
workspace/data/releases/<release-id>/
```

不要根据 `v3`、`v4`、`v4_1` 的版本号大小推测“最新训练数据”。

### 查找中间 artifact

先确定以下信息：

1. collection，例如 `review_queues`；
2. artifact ID，例如 queue ID；
3. manifest 中记录的 schema 和 tree hash；
4. 它属于新语义布局还是历史兼容布局。

当前标准回退关系为：

| Collection | 首选位置 | 历史回退位置 |
| --- | --- | --- |
| `roi_manifests` | `metadata/roi_manifests` | `metadata/v3/roi_manifests` |
| `candidate_plans` | `metadata/candidate_plans` | `metadata/v3/candidate_plans` |
| `candidate_media_results` | `metadata/candidate_media_results` | `metadata/v3/candidate_media_results` |
| `review_reference` | `metadata/review_reference` | `metadata/v3/review_reference` |
| `review_queues` | `metadata/review_queues` | `metadata/v4_1/review_queues` |
| `review_decisions` | `metadata/review_decisions` | `metadata/v4_1/review_decisions` |

`metadata/v4/` 没有列入当前 resolver 的标准回退关系。需要查看 V4 历史证据时应使用
冻结 manifest 或明确路径，不应让新代码自动选择它。

## 写入和清理边界

### 允许

- 新任务写入自己的 `workspace/data-staging/<run-id>/`；
- 完成人工审阅和所有门禁后，通过编排器 promote；
- 按 artifact ID 读取受支持的历史产物；
- 为历史目录生成只读 inventory、校验报告和归档计划。

### 禁止

- 根据目录名手工选择“最新”数据；
- 在正式训练中临时改用某个 `derived/metadata/v*_*/` 目录；
- 把新产物继续写入 `v3/`、`v4/` 或 `v4_1/`；
- 手工覆盖同名内容寻址目录；
- 在没有引用扫描、hash 校验和回滚方案时移动或删除旧数据；
- 把跳过某轮链路测试的人工审阅视为正式 release 已通过审阅。

## 已知过渡事项

1. `v4/` 只有少量过渡审阅产物，但尚未纳入统一 legacy resolver；在归档前必须先建立
   引用清单并记录其替代关系。
2. 部分 `finetune/MiniCPM/config/active/` 历史实验配置仍直接指向
   `metadata/v4_1/`。这些配置被路径守卫明确列为冻结历史输入，不应复制为新实验模板。
3. 正式数据根中的无版本语义 collection 尚未全部形成；首个真实 semantic staging run
   完成人工审阅和 promote 后，应重新核对本文目录快照。

## 相关文档

- [数据处理与训练发布运行手册](DATA_PROCESSING_RUNBOOK.md)
- [数据 staging 与语义化元数据路径设计](plans/2026-07-29-data-staging-semantic-paths-design.md)
- [项目内 workspace 设计](plans/2026-07-28-project-local-workspace-design.md)
- [项目内 workspace 迁移报告](reports/2026-07-28-project-local-workspace-migration.md)

