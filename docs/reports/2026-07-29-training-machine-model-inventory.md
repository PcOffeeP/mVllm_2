# 训练机模型资产只读盘点报告

> 日期：2026-07-29
> 训练机：`dell-Precision-3660`
> 项目：`/home/liuyang/文档/mVllm_2`
> 扫描时 Git HEAD：`c87d582`，工作区干净
> 状态：只读盘点完成，未移动、重命名或删除任何模型

## 1. 执行摘要

本次扫描覆盖整个训练机项目目录，并重点检查：

- `workspace/`；
- `LlamaFactory/`；
- `finetune/`；
- 项目根目录下其他可能保存模型的目录。

盘点发现：

| 项目 | 数量 |
| --- | ---: |
| 基础模型目录 | 1 |
| 可直接加载的 merged/full-weight 模型目录 | 22 |
| adapter 输出根目录 | 22 |
| adapter checkpoint 目录 | 108 |
| `finetune/` 内实际权重目录 | 0 |
| GGUF 模型 | 0 |

按物理目录计算，模型相关资产约为 `511.36 GB` 十进制，即约 `476.24 GiB`。其中：

| 位置 | merged/full-weight | adapter 树 | 约占空间 |
| --- | ---: | ---: | ---: |
| `models/minicpmv4_5` | 1 个基础模型 | 不适用 | 16.21 GiB |
| `LlamaFactory` | 18 个 merged | 18 个 adapter 根、88 个 checkpoint | 367.37 GiB |
| `workspace` | 4 个 merged | 4 个 adapter 根、20 个 checkpoint | 92.66 GiB |
| `finetune` | 0 | 0 | 无模型权重 |

训练机 `/home` 文件系统总计 937 GiB，已用 805 GiB，仅剩约 85 GiB。现有空间不足以
复制一份全部模型后再整理，后续迁移必须采用分批校验、同盘移动和必要兼容链接，不能进行
全量双份复制。

## 2. 识别口径

本次把以下文件作为模型资产标志：

- `adapter_model.safetensors` 或 `adapter_model.bin`；
- `model-*.safetensors`；
- `model.safetensors.index.json`；
- `pytorch_model*.bin`。

“模型数量”容易因 checkpoint 被重复计算，因此本报告分别统计：

1. 基础模型；
2. 每个训练产物的 adapter 根；
3. 每个可部署 merged 模型；
4. adapter 下的中间 checkpoint。

每个 merged BF16 目录约为 `17.41 GB` 十进制，即约 `16.21 GiB`，包含 10 个
safetensors 分片。

## 3. 项目根目录基础模型

项目根目录还存在一份最初未纳入三个目标目录的基础模型：

```text
/home/liuyang/文档/mVllm_2/models/minicpmv4_5
```

目录大小约 `16.21 GiB`。历史 4-bit adapter 评测仍有 11 处 JSON 证据引用该目录。它是
所有 LoRA/merged 模型的基座，不属于某个实验，也不应与发布模型一起归档或删除。

建议归类：

```text
workspace/models/base/minicpmv4_5
```

实际迁移前需要确认 LLaMA-Factory、adapter config 和评测 runtime 对该绝对路径的引用。

## 4. `LlamaFactory` 中的模型

`LlamaFactory` 总占用约 `368 GiB`，模型均位于：

```text
LlamaFactory/saves/minicpmv4_5/lora
```

### 4.1 当前 Agent 链路模型

| 原始训练身份 | adapter 树 | merged | 评测 | 建议分类 |
| --- | ---: | ---: | --- | --- |
| `sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3_seed3407` | 6.95 GiB，5 checkpoints | 16.21 GiB | valid 100.00%，joint 41.18%，state 56.00% | 当前发布模型 |

完整 merged 路径：

```text
/home/liuyang/文档/mVllm_2/LlamaFactory/saves/minicpmv4_5/lora/
sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3_seed3407_merged
```

已冻结 aggregate SHA-256：

```text
1f75e4f91db487273588c1e1c8bf867b20acdfc565c191d914915b366c4c1b1c
```

新模型名称：

```text
v4.1-agent-pipeline-fold0-r1
```

发布目录只需要 merged、最终可复现 adapter 和 manifest。5 个训练 checkpoint 仍属于原始
experiment，不应全部复制进 release。

### 4.2 Phase 2 Fold0 对比模型

以下 4 个模型均为 current release 上的 Fold0 实验模型，不是发布模型：

| 原始训练身份 | adapter + checkpoints | merged | valid | joint | state | 建议 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `coverage_first...seed3411` | 6.95 GiB | 16.21 GiB | 100.00% | 37.41% | 55.76% | experiment |
| `source_aware_3k_dd89...seed3407` | 6.95 GiB | 16.21 GiB | 100.00% | 36.24% | 47.76% | experiment |
| `source_aware_3k_dd89...seed3411` | 6.95 GiB | 16.21 GiB | 100.00% | 41.18% | 51.06% | experiment |
| `coverage_first_fallback...seed3413` | 6.95 GiB | 16.21 GiB | 100.00% | 35.06% | 54.59% | experiment |

它们应迁入各自的 `workspace/runs/<experiment-id>/`，保留为 sampling/seed 对比证据。

### 4.3 2026-07-24 visual 完整三折模型

| Fold | adapter + checkpoints | merged | valid | joint | state | 建议 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Fold0 | 6.95 GiB | 16.21 GiB | 98.12% | 42.12% | 54.12% | 历史三折 benchmark |
| Fold1 | 6.95 GiB | 16.21 GiB | 97.98% | 34.38% | 42.47% | 历史三折 benchmark |
| Fold2 | 6.95 GiB | 16.21 GiB | 94.80% | 45.38% | 53.47% | 历史三折 benchmark |

原始目录前缀：

```text
sft_tensile_v4_1_0_760050fad303_20260724_visual_fold{0,1,2}
```

这三个目录是三个独立模型，不是一个 full 模型。建议整体归入一个历史 benchmark
experiment，不能把 Fold2 单独晋级为发布模型。

### 4.4 2026-07-23 Fold0 消融模型

| 训练身份 | adapter + checkpoints | merged | valid | joint | state | 建议 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| visual only | 6.95 GiB | 16.21 GiB | 99.53% | 43.29% | 54.35% | 历史消融 |
| augmented language | 0.79 GiB | 16.21 GiB | 100.00% | 42.35% | 46.35% | 历史消融 |
| augmented visual | 6.95 GiB | 16.21 GiB | 97.41% | 39.76% | 47.06% | 历史消融 |

当前物理位置：

```text
LlamaFactory/saves/minicpmv4_5/lora/experiments/v4_1/
```

其中历史 JSON 仍引用迁移前的 LoRA 根路径，当前真实模型已经位于 `experiments/v4_1/`。
这些旧绝对路径应视为 `path_at_freeze`，不应回写修改历史结果。

### 4.5 V4.1 language 三折 archive

```text
LlamaFactory/saves/minicpmv4_5/lora/archive/v4_1_language/
├── ...fold0
├── ...fold0_merged
├── ...fold1
├── ...fold1_merged
├── ...fold2
└── ...fold2_merged
```

共 3 个 adapter 根、15 个 checkpoint 和 3 个 merged。每个 adapter 树约 0.79 GiB，
每个 merged 约 16.21 GiB。这些已经有明确 archive 语义，后续只需要补注册表和淘汰原因，
不应重新进入 current 候选。

### 4.6 V2 archive

```text
LlamaFactory/saves/minicpmv4_5/lora/archive/v2/
├── ...fold0_20260719
├── ...fold0_20260719_merged
├── ...fold1_20260719
├── ...fold1_20260719_merged
├── ...fold2_20260719
├── ...fold2_20260719_merged
├── ...full_20260719
└── ...full_20260719_merged
```

共 4 个 adapter 根、18 个 checkpoint 和 4 个 merged。这是旧协议模型，应作为完整的 V2
rollback/archive 资产管理，不能与 V4.1 实验混放。

历史结果仍引用这些模型迁移前的 LoRA 根路径；当前模型实际位于 `archive/v2/`，所以引用
扫描显示旧路径不存在。这不代表权重丢失，但说明后续注册表必须区分“冻结时路径”和“当前
受管路径”。

## 5. `workspace` 中的模型

### 5.1 Concise Prompt 三折

```text
workspace/runs/v4.1-prompt-concise-cv-v1-seed3411/
├── fold0/{adapter,merged,evaluation}
├── fold1/{adapter,merged,evaluation}
└── fold2/{adapter,merged,evaluation}
```

总大小约 `69.51 GiB`，包含 3 个 adapter 根、15 个 checkpoint 和 3 个 merged：

| Fold | valid | joint | state | 结论 |
| --- | ---: | ---: | ---: | --- |
| Fold0 | 89.41% | 43.53% | 46.35% | rejected experiment |
| Fold1 | 71.08% | 23.19% | 26.66% | rejected experiment |
| Fold2 | 82.72% | 34.15% | 39.02% | rejected experiment |

这组模型已经位于正确的新式 experiment 目录中，不需要再次搬入其他实验目录。后续只需
补 lifecycle manifest，并明确它不能晋级为 release。

### 5.2 Minimal Prompt Fold0

```text
workspace/runs/v4.1-prompt-minimal-v1-seed3411/
├── adapter/
├── merged/
├── evaluation/
└── logs/
```

总大小约 `23.17 GiB`，包含 1 个 adapter 根、5 个 checkpoint 和 1 个 merged。评测合法率
86.12%、joint 24.00%、state 35.06%，应标记为 rejected experiment。

### 5.3 没有模型权重的 workspace 实验

以下目录只有输入、reference 或准备文件，没有 adapter、merged 或 checkpoint：

```text
workspace/runs/v4.1-prompt-concise-v1-seed3411
workspace/runs/v4.1-prompt-concise-v2-seed3411
```

它们不是模型，只是未完成或准备阶段 experiment。后续注册表不能把这两个目录计入模型
数量。

## 6. `finetune` 中是否存在模型

结论：`finetune/` 内没有 `.safetensors`、PyTorch model bin、adapter 权重或 merged
权重。

当前占用：

| 目录 | 大小 | 内容 |
| --- | ---: | --- |
| `finetune/results` | 82 MiB | 评测摘要、逐样本记录、run identity |
| `finetune/run_logs` | 22 MiB | 训练、服务、部署日志 |
| `finetune/trainer_output/3k0_v3` | 14 MiB | tokenizer、训练状态和曲线，无 adapter 权重 |
| `finetune/experiments` | 88 KiB | Git 管理的实验配置和 manifest |

需要注意：历史结果仍有 11 处引用以下已经不存在的旧模型：

```text
LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_v3_merged
```

`finetune/trainer_output/3k0_v3` 仅保留 tokenizer 和训练状态，不能替代该 merged 权重。
因此该早期 legacy 模型应登记为“历史结果存在、模型权重缺失”。

## 7. 当前完整模型清单

### 7.1 基础模型

1. `models/minicpmv4_5`

### 7.2 V2

2. `archive/v2/...fold0_20260719_merged`
3. `archive/v2/...fold1_20260719_merged`
4. `archive/v2/...fold2_20260719_merged`
5. `archive/v2/...full_20260719_merged`

### 7.3 V4.1 language 和早期消融

6. `archive/v4_1_language/...fold0_merged`
7. `archive/v4_1_language/...fold1_merged`
8. `archive/v4_1_language/...fold2_merged`
9. `experiments/v4_1/...20260723_fold0_visual_merged`
10. `experiments/v4_1/...subvideo...fold0_language_merged`
11. `experiments/v4_1/...subvideo...fold0_visual_merged`

### 7.4 V4.1 visual 历史三折

12. `...20260724_visual_fold0_merged`
13. `...20260724_visual_fold1_merged`
14. `...20260724_visual_fold2_merged`

### 7.5 V4.1 Phase 2 Fold0

15. `...coverage_first...seed3407_merged`，当前 Agent 链路模型
16. `...coverage_first...seed3411_merged`
17. `...source_aware_3k_dd89...seed3407_merged`
18. `...source_aware_3k_dd89...seed3411_merged`
19. `...coverage_first_fallback...seed3413_merged`

### 7.6 Workspace Prompt 实验

20. `workspace/runs/v4.1-prompt-minimal-v1-seed3411/merged`
21. `workspace/runs/v4.1-prompt-concise-cv-v1-seed3411/fold0/merged`
22. `workspace/runs/v4.1-prompt-concise-cv-v1-seed3411/fold1/merged`
23. `workspace/runs/v4.1-prompt-concise-cv-v1-seed3411/fold2/merged`

序号包含 1 个基础模型，因此实际 fine-tuned merged 模型为 22 个。

## 8. 引用和身份问题

扫描 `finetune/results/**/*.json` 后发现：

- 当前发布模型路径存在，并有 5 组轻量结果或交付证据引用；
- 2026-07-24 visual 三折路径存在；
- Phase 2 五个 Fold0 模型路径存在；
- V2、V4.1 language 和 2026-07-23 消融模型已经物理迁入 archive/experiments，但冻结
  JSON 仍保留迁移前路径；
- legacy `sft_interval_3k0_v3_merged` 权重确实缺失；
- 当前目标目录中没有模型软链接。

本次没有对约 383 GB merged 权重重新执行全量 SHA-256，因此除了已经冻结的当前发布模型
外，尚不能仅凭相同目录大小认定两个 merged 模型重复。正式迁移前应优先利用已有 evidence
manifest；缺少已有 hash 的模型再分批计算。

## 9. 建议的迁移优先级

### P0：先建立 current release

将当前模型登记为：

```text
v4.1-agent-pipeline-fold0-r1
```

目标：

```text
workspace/models/releases/v4.1-agent-pipeline-fold0-r1
workspace/models/current
```

由于磁盘只剩 85 GiB，可容纳一次 16.21 GiB merged 的临时复制，但不能复制全部模型。
应先复制当前 merged、校验 hash、切换服务和 Agent；成功后再处理旧路径。

### P1：保持 workspace 实验原位

Prompt minimal 和 concise CV 已符合 `workspace/runs/<experiment-id>` 结构，只需补 manifest
和 rejected 状态，不需要搬迁。

### P2：迁移 LlamaFactory 活跃 V4.1 实验

依次处理：

1. Phase 2 其余四个 Fold0 模型；
2. 2026-07-24 visual 三折 benchmark；
3. 2026-07-23 三个消融模型。

每次只迁移一个 experiment，并在移动前扫描活动引用。

### P3：统一历史 archive

V2 和 V4.1 language 已有 archive 语义，可以最后移动到：

```text
workspace/models/archive/
```

迁移时保留历史 `path_at_freeze`，新增 current managed path，不重写冻结结果。

### P4：最后处理 checkpoint 和缺失资产

108 个 checkpoint 占约 `96.37 GiB`，是后续主要可回收空间，但不能在盘点阶段删除。应在
确认最终 adapter、best checkpoint 和 trainer state 的关系后，单独生成 checkpoint 保留/
删除清单。

`sft_interval_3k0_v3_merged` 登记为 missing legacy artifact，不尝试从 14 MiB 的
`finetune/trainer_output/3k0_v3` 伪恢复模型。

## 10. 本次操作边界

本次只执行目录、文件标志、大小和轻量 JSON 引用扫描：

- 没有移动或重命名目录；
- 没有创建软链接；
- 没有删除 checkpoint；
- 没有重新训练、合并或推理；
- 没有改动训练机 Git 工作区；
- 没有把大型本地产物加入 Git。
