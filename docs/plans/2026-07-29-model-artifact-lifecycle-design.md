# 训练机模型资产分区、命名与发布生命周期设计

> 日期：2026-07-29
> 状态：已实施；当前发布、实验迁移、兼容链接、注册表与 checkpoint 策略均已落地
> 适用范围：训练机 `/home/liuyang/文档/mVllm_2` 内现有和后续 VLM 模型资产

## 1. 目标

本设计解决训练机模型权重散落在 `workspace/runs/`、
`LlamaFactory/saves/minicpmv4_5/lora/` 等目录，实验模型、阶段模型和当前发布模型难以区分的
问题。

改造后：

1. 当前项目发布模型具有独立、稳定且可直接识别的物理目录；
2. 其他训练模型统一归入实验运行目录，并能追溯数据、Prompt、fold、seed 和评测结果；
3. 新模型必须先作为实验产物，经对比和验收后才能晋级为发布模型；
4. 旧发布模型进入 archive，保留回滚和复现能力；
5. 所有模型名称固定表达协议版本、核心要点、训练范围和模型轮次。

## 2. 非目标

本设计不包含：

- 把大型模型权重、训练数据、逐样本推理记录或运行日志提交到 Git；
- 在模型整理过程中重新训练、重新合并或重新评测模型；
- 将当前阶段模型表述为 production-ready、full-data final 或 production-approved；
- 自动删除历史权重；
- 修改冻结评测结果、历史 run identity 或已有证据文件中的原始路径记录；
- 引入数据库、DVC、对象存储或外部模型注册平台。

## 3. 约束

- `workspace/` 是训练机项目内大型、机器本地资产的统一根目录，并保持 Git ignored；
- Git 只保存轻量模型注册表、发布 manifest、部署配置、指标摘要和文档；
- 现有部署 manifest 和历史评测记录包含绝对模型路径，迁移不能直接批量移动后再补救；
- 当前发布模型仍是 Fold0 中间开发模型，完成了 Agent 链路验证，但不代表最终最佳模型；
- 所有移动必须在确认没有训练、合并、评测或推理进程写入目标目录后执行；
- 删除 archive 权重必须单独获得用户明确授权。

## 4. 方案选择

### 4.1 只移动物理目录

优点是直观、改动少。缺点是无法稳定记录发布状态，会破坏现有绝对路径引用，后续仍可能
重新出现目录与身份不一致。

### 4.2 只建立注册表或 `current` 软链接

优点是不移动大型权重，实施风险较低。缺点是模型物理文件仍然散乱，没有解决实验模型和
发布模型混放的问题。

### 4.3 物理分区、轻量注册表和 `current` 指针

该方案同时提供清晰的物理边界、可审计身份和稳定部署入口。迁移成本高于前两种方案，但能
长期约束后续训练和发布流程，因此采用该方案。

## 5. 模型命名规范

### 5.1 固定格式

所有可保存的模型身份使用：

```text
<protocol-version>-<core-purpose>-<training-scope>-r<round>
```

字段顺序不可交换，也不可省略。

当前 Agent 链路模型正式命名为：

```text
v4.1-agent-pipeline-fold0-r1
```

### 5.2 协议版本

`protocol-version` 来自模型实际实现的推理协议：

```text
tensile-vlm/v4.1 -> v4.1
```

Prompt、seed、采样、学习率、LoRA 参数或训练数据数量变化但协议不变时，不改变该字段。
只有输入输出 schema、字段语义、枚举、必填关系或兼容性边界变化时才使用新的协议版本。

### 5.3 核心要点

`core-purpose` 使用简短的 kebab-case 语义名称，说明该轮模型为什么存在，而不是重复项目
背景。

允许示例：

```text
agent-pipeline
prompt-canonical
prompt-concise
sampling-balanced
epoch-gated
```

不允许把以下复现细节放入核心要点：

- `seed3407`；
- checkpoint step；
- 内容 hash；
- 日期；
- `MiniCPM-V`、`tensile-fracture-vlm` 等整个项目共有的背景前缀；
- `best`、`new`、`final2` 等无法长期解释的词。

### 5.4 训练范围

`training-scope` 必须明确权重使用了哪一范围的数据：

- `fold0`、`fold1`、`fold2`：对应冻结 split 中的零基 fold；
- `fold3` 及更大编号：仅在冻结 split 真实包含对应 fold 时使用；
- `full`：使用当时冻结的全部 development training data 训练出的单一模型。

三折指标汇总不是单一权重，不能命名为 `full`。当前三折划分只包含 `fold0`、`fold1`、
`fold2`。

### 5.5 模型轮次

`r<round>` 表示相同协议版本、核心要点和训练范围下，第几个完成并保留的不同模型产物，
从 `r1` 开始递增。

- 产生不同权重并保留为独立模型时递增；
- 训练失败且没有形成保留模型时不占用轮次；
- 重试后模型文件 hash 与已有模型完全相同时不产生新轮次；
- seed、数据 release、Prompt revision 或训练配置发生变化但仍沿用相同核心要点时，形成
  新保留权重应递增；
- 模型从 experiment 晋级为 release 时身份和轮次不改变，只改变 lifecycle status；
- 不允许覆盖已有轮次目录或让同一名称对应不同 aggregate hash。

完整复现信息必须写入 manifest，而不是继续扩展模型名称。

### 5.6 名称与实验 ID 分离

实验 ID 描述“做了什么实验”，模型名称描述“这个权重是什么”。二者允许不同，但必须在
manifest 中双向关联。

例如：

```text
experiment_id: v4.1-prompt-concise-cv-v1-seed3411
model_name:    v4.1-prompt-concise-fold1-r1
```

## 6. 推荐目录结构

```text
mVllm_2/
└── workspace/
    ├── data/
    ├── runs/
    │   └── <experiment-id>/
    │       ├── input/
    │       ├── fold0/
    │       │   ├── adapter/
    │       │   ├── merged/
    │       │   └── evaluation/
    │       ├── logs/
    │       └── experiment-manifest.json
    └── models/
        ├── current -> releases/v4.1-agent-pipeline-fold0-r1
        ├── releases/
        │   └── v4.1-agent-pipeline-fold0-r1/
        │       ├── merged/
        │       ├── adapter/
        │       └── release-manifest.json
        └── archive/
            ├── releases/
            │   └── <superseded-model-name>/
            └── unclassified/
                └── <legacy-directory-name>/
```

目录职责：

- `workspace/runs/`：所有新训练首先落入这里；它是实验过程的唯一活动根；
- `workspace/models/releases/`：只保存已经人工确认的发布模型；
- `workspace/models/current`：只指向当前项目默认发布模型；
- `workspace/models/archive/releases/`：保存被新模型替代的历史发布模型；
- `workspace/models/archive/unclassified/`：隔离暂时无法建立可靠实验身份的历史权重。

不单独建立长期 `candidates/` 目录。候选模型仍属于 `workspace/runs/`，避免产生第三份活动
权重和含糊的中间状态。

## 7. 轻量模型注册表

Git 管理：

```text
pipeline/model_registry/
├── current.json
├── releases/
│   └── v4.1-agent-pipeline-fold0-r1.json
└── archive/
    └── <superseded-model-name>.json
```

每个模型 manifest 至少记录：

- `model_name`；
- `protocol_version` 和 contract hash；
- `core_purpose`；
- `training_scope`；
- `round`；
- lifecycle status；
- experiment ID、data release、Prompt revision 和 Prompt hash；
- fold、seed、采样策略和训练配置身份；
- adapter、merged artifact 的路径、格式、文件数和 aggregate hash；
- checkpoint 或最终 adapter 来源；
- evaluator、指标摘要和证据路径；
- deployment manifest 和 Agent 验证证据；
- limitations、production approval 和淘汰原因。

训练机发布目录内的 `release-manifest.json` 必须与 Git 注册表中对应身份一致。部署入口同时
校验 `current.json`、目标 manifest、contract hash 和模型 aggregate hash。

## 8. 生命周期

模型状态固定为：

```text
experiment -> evaluated -> accepted -> released/current
                                      -> rejected
released/current -> superseded -> archived
```

规则：

1. 新训练只能写入 `workspace/runs/<experiment-id>/`；
2. 完成合并不代表发布，严格评测完成后才进入 `evaluated`；
3. 只有人工确认模型身份、指标、限制和部署用途后才能进入 `accepted`；
4. 晋级时将需要长期保存的 merged 和最小可复现 adapter 放入不可覆盖的 release 目录；
5. smoke、contract 和 Agent 预检通过后，原子更新 `current`；
6. 原 current 标记为 `superseded`，再移入 `archive/releases/`；
7. archive 权重经过保留期和单独授权后可以删除，但其 Git manifest、指标、哈希和淘汰原因
   永久保留。

## 9. 当前模型身份

当前准备整理为项目默认发布模型的权重：

```text
v4.1-agent-pipeline-fold0-r1
```

其来源身份保持：

```text
experiment/training variant:
  coverage-first seed3407
training scope:
  fold0
artifact:
  merged BF16
primary purpose:
  Agent 链路验证
```

其发布 manifest 必须继续明确：

```text
lifecycle_status: current
release_type: milestone
quality_tier: intermediate_development_model
full_data_final: false
production_approved: false
```

“当前默认发布模型”只描述项目选择，不表示该模型已经达到生产质量或最终研究效果。

## 10. 现有资产迁移

### 10.1 盘点阶段

迁移前生成只读资产清单，至少包含：

- 原路径、目录大小和最近修改时间；
- adapter、checkpoint、merged BF16 或其他格式；
- safetensors 文件数和 aggregate hash；
- 可关联的 experiment、fold、seed、Prompt、data release；
- 评测结果和指标摘要；
- Git 文件、deployment manifest、Agent bundle 对该路径的引用；
- 建议分类：current release、experiment、superseded release、duplicate、unclassified。

盘点阶段不移动、不覆盖、不删除任何模型。

### 10.2 当前模型晋级

1. 确认训练和推理进程未写入当前模型目录；
2. 重新核对现有 10 个 merged BF16 分片和 aggregate hash；
3. 创建 `v4.1-agent-pipeline-fold0-r1` 注册表和发布 manifest；
4. 将 merged 和最小可复现 adapter 放入 release 目录；
5. 若磁盘允许，优先复制、全量核验后再切换；磁盘不足时才使用同文件系统移动并立即建立
   旧路径兼容链接；
6. 更新新的 deployment manifest、service component 和 TensileAgent delivery bundle；
7. 完成 contract、真实视频 smoke、SSH tunnel 和 Agent 预检；
8. 原子创建或更新 `workspace/models/current`。

冻结历史证据中的 `path_at_freeze` 不重写。兼容链接在全部活动引用迁移完成前保留。

### 10.3 实验模型归档

- 已能关联新式 experiment ID 的模型移动到对应 `workspace/runs/<experiment-id>/`；
- 能识别但尚未建立新式 experiment ID 的旧模型，先建立 legacy-import manifest；
- 无法确认来源或 hash 冲突的模型进入 `archive/unclassified/`；
- adapter 中间 checkpoint 默认随实验保存，不进入 release；
- 明确重复且 aggregate hash 相同的权重先记录重复关系，不能在盘点阶段直接删除。

### 10.4 后续训练约束

训练入口必须拒绝：

- 输出到 `LlamaFactory/saves/minicpmv4_5/lora/` 根目录；
- 覆盖已存在的 experiment 或模型轮次；
- 缺少 experiment contract、Prompt hash、data release 或模型名称；
- 模型名称中的协议版本、fold 与实际 manifest 不一致。

## 11. 失败处理

- 同名模型但 hash 不同：停止迁移，不覆盖任何目录；
- 不同名称但 hash 相同：记录 duplicate 关系，保留一个权威物理副本后再决定去重；
- manifest 与物理文件不一致：模型不得晋级或成为 current；
- 旧路径仍有活动引用：保留兼容链接并阻止退役；
- 复制或移动中断：current 指针保持原值，部署继续读取原模型；
- 新模型 smoke 或 Agent 预检失败：不更新 current，候选退回 experiment；
- archive 磁盘不足：先报告容量和可回收清单，不自动删除；
- 找不到可靠来源的模型：进入 unclassified，不推测实验身份。

## 12. 测试与验收

### 12.1 命名

- 合法名称能解析为协议版本、核心要点、训练范围和轮次；
- fold 与 experiment contract、split manifest 一致；
- full 模型确实来自冻结的全量 development training data；
- 同一名称只能对应一个 aggregate hash；
- seed、日期和 hash 不出现在发布模型名称中。

### 12.2 资产完整性

- 迁移前后文件数、总字节数和全部模型文件 hash 一致；
- adapter 和 merged 的来源关系可验证；
- release manifest、Git 注册表和物理目录身份一致；
- 历史冻结证据内容和 hash 不被修改。

### 12.3 部署

- `current` 指向 Git `current.json` 声明的同一模型；
- 服务返回正确的 contract version、contract hash 和 deployment identity；
- 真实 development 视频 GPU smoke 通过；
- TensileAgent 使用显式 V4.1 配置完成 contract 和 deployment 预检；
- 回滚到上一 archive release 的步骤可执行。

### 12.4 后续训练

- 新 adapter、merged、evaluation 和 logs 全部位于 `workspace/runs/`；
- LlamaFactory LoRA 根目录不再产生新的散落模型；
- rejected experiment 不进入 releases；
- promotion 不改变模型名称或已有权重内容；
- superseded release 的 manifest 保留淘汰原因和替代模型。

## 13. 实施边界与完成标准

本设计应拆为三个原子实施步骤：

1. 建立命名校验、轻量注册表 schema 和只读资产盘点工具；
2. 迁移并验证当前 `v4.1-agent-pipeline-fold0-r1`，切换部署和 Agent 引用；
3. 分批分类历史实验模型，并约束所有后续训练输出。

以下条件全部满足后，模型资产整理才算完成：

1. 当前发布模型独立位于 `workspace/models/releases/`，且 `current` 指向正确；
2. 当前模型名称完整表达 `v4.1`、`agent-pipeline`、`fold0` 和 `r1`；
3. 当前部署、服务和 Agent bundle 不再依赖散落的 LlamaFactory 模型路径；
4. 所有新训练只写入 `workspace/runs/`；
5. 训练机现有模型均具有明确分类或进入 unclassified 隔离区；
6. 旧发布模型可回滚，历史轻量身份永久保留；
7. 未经单独授权没有删除任何历史权重。
