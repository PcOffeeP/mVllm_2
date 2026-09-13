# 当前项目状态与开发原则

> 本文保留历史阶段记录。2026-09-14现场模型资产与新体系门禁背景见[当前真实模型背景](MODEL_GATE_BASELINE.md)；历史工程通过、旧指针及清单中的存活状态不代表当前新门禁通过。

> 更新时间：2026-07-29
> 权威范围：`mVllm_2` 数据、训练、模型资产、推理服务及 TensileAgent 对接

## 一句话状态

项目已经拥有一款能够稳定走通 VLM 训练、合并、推理服务和 TensileAgent 调用链路的
V4.1 Fold0 中间模型；接下来的主要工作是提升模型任务效果，而不是继续证明工程链路
能否运行。

## 当前交付对象

当前唯一发布模型：

`v4.1-agent-pipeline-fold0-r1`

它代表：

- `v4.1`：模型实际实现的协议版本；
- `agent-pipeline`：该模型的核心价值是完成 Agent 链路验证；
- `fold0`：仅使用 Fold0 训练范围；
- `r1`：该身份下第一轮保留模型。

它不代表：

- 当前三折最优模型；
- full-data 模型；
- 独立测试通过；
- production-ready；
- 项目最终模型。

训练机的权威入口：

```text
workspace/models/current
  -> workspace/models/releases/v4.1-agent-pipeline-fold0-r1
```

Git 中的权威身份：

```text
pipeline/model_registry/current.json
pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json
```

## 当前模型证据

已经完成：

- root adapter 和 merged BF16 完整聚合哈希校验；
- `tensile-vlm/v4.1` 契约身份校验；
- 训练机 `127.0.0.1:8002` loopback 推理服务启动；
- 真实拉伸 MP4 service smoke；
- TensileAgent doctor；
- 实际 Agent 视频调用；
- V2 历史回滚对象保留。

尚未完成或未通过：

- Stage B、Stage D、Stage G 模型质量门；
- full-data final 训练；
- 独立测试通过；
- production approval。

因此工程链路通过和模型质量通过必须始终作为两个不同结论表述。

## 最新三折实验

`v4.1-prompt-concise-cv-v1-seed3411` 已完成三折训练、最佳 checkpoint 回载、adapter
合并和 1581 条严格评测。

它解决了训练越过最佳点后继续运行的问题，但没有解决任务效果：

- contract 合法率：79.63%；
- joint correct：32.07%；
- `clip_state`：35.80%；
- 322 条严格非法输出；
- 明显坍缩到“未断裂”；
- `临界未断裂`和`已断裂`召回率均为 0%。

因此该组三折仍属于 `workspace/runs/` 中的实验，不晋级为 release。

## 当前开发理念

### 开发闭环

本项目以“帧窗口证据”为中心，而不是简单增加子视频数量。完整开发闭环如下：

1. **定义任务契约**：冻结输入媒体约束、输出字段、枚举、Prompt 和生成参数。
2. **治理原始视频**：记录来源、实验编号、标注、ROI 和源视频级 split。
3. **生成帧窗口证据**：物化子视频与实际采样帧，避免把近重复画面当作独立证据。
4. **人工审查标签**：自动规则只负责候选分流，人工结论才可以进入冻结发布。
5. **发布训练数据**：开发数据与独立测试数据分别形成内容寻址、不可覆盖的 release。
6. **运行受控实验**：先在固定 fold 隔离单一变量，并保存完整 checkpoint 学习轨迹。
7. **执行严格评测**：检查 schema 合法率、字段准确率、状态召回、混淆矩阵和失败样例。
8. **完成三折选择**：只有跨 fold 稳定的方案才进入全量训练候选。
9. **管理模型生命周期**：实验产物进入 `workspace/runs/`，人工确认后才能晋级为 release。
10. **交付推理服务**：服务从 `workspace/models/current` 加载发布模型，并校验完整身份。

同一源视频可以贡献多个窗口，但不能把近重复帧当作独立视觉证据；三折用于选择方案，
最终模型必须使用全部合格开发数据训练，并由从未参与调参的独立测试发布验收。

工程链路验收和模型质量验收相互独立：模型可以成功训练、合并、部署和被 Agent 调用，
但仍可能因为类别坍缩、契约非法或断裂召回不足而不能作为最终模型。

### 1. 先固定身份，再比较效果

每个实验必须冻结：

- 数据 release；
- Prompt revision 与内容 hash；
- contract 与 schema hash；
- fold、seed、采样和训练参数；
- adapter、merged 和评测身份。

不能把不同数据、Prompt 和训练日程下的指标差异直接解释成单一变量效果。

### 2. 工程链路和模型质量分开验收

工程链路回答：

> 模型能否被合并、部署、调用并返回符合契约的证据？

模型质量回答：

> 模型是否在独立、严格、可比较的任务指标上达到要求？

前者通过不能替代后者。

### 3. 模型先实验，后发布

```text
workspace/runs/<experiment-id>
        |
        | 严格评测与人工确认
        v
workspace/models/releases/<model-name>
        |
        | 服务与 Agent 验证
        v
workspace/models/current
```

合并成功不等于发布，单折指标好也不等于最终模型。

### 4. 名称表达模型身份，manifest 表达复现细节

模型名固定为：

`<协议版本>-<核心要点>-<训练范围>-r<轮次>`

seed、日期、checkpoint、数据 hash 和 Prompt hash 放入 manifest，不继续堆进目录名。

### 5. Checkpoint 按分析状态管理

Checkpoint 同时服务于：

- 断点续训；
- best/last 对比；
- 中间学习能力分析；
- 定位类别坍缩、契约退化和过拟合发生的 step。

因此不能因为已有 merged 就自动删除。当前保留：

- 发布模型来源实验的全部 5 个 checkpoint；
- 最新 prompt-concise 三折的全部 15 个 checkpoint。

其他已完成且无需继续分析的实验只删除 checkpoint，保留 adapter、merged、指标和日志。

### 6. 数据和权重都使用项目内 workspace

- 当前数据：`workspace/data`；
- 实验：`workspace/runs`；
- 发布模型：`workspace/models/releases`；
- 当前模型：`workspace/models/current`。

`tensile-data` 和 `LlamaFactory/saves` 只保留历史兼容入口，不再作为新工作的权威根。

## 下一轮优化目标

优先级按证据链排序：

1. 对保留的三折 checkpoint 做逐 step 严格评测，确定契约退化和类别坍缩从何时开始；
2. 隔离 Prompt 精简、采样配额和训练日程三个变量；
3. 首先恢复接近 100% 的四字段 contract 合法率；
4. 提升`临界未断裂`、`发生断裂`、`已断裂`召回，避免“未断裂”偏置；
5. 只有完整三折稳定优于当前基准后，才讨论 full-data 模型；
6. 方案冻结后再执行独立测试，不根据独立测试结果回头调参。

## 文档入口

- [仓库总览](../README.md)
- [微调、合并与评测](../finetune/README.md)
- [数据处理运行手册](DATA_PROCESSING_RUNBOOK.md)
- [V4.1 数据发布](V4_1_DATA_RELEASES.md)
- [推理服务运行手册](INFERENCE_SERVICE_RUNBOOK.md)
- 模型资产生命周期（文档已归档，见 git 历史）
- Checkpoint 清理报告（文档已归档，见 git 历史）
- [当前发布模型证据](results/v4_1_agent_pipeline_fold0_r1/README.md)
- [最新三折结果](results/v4_1_prompt_concise_cv_v1_seed3411/README.md)
