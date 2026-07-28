# V4.1 Prompt Minimal V1 Seed3411 结果

> 日期：2026-07-28
> 实验：`v4.1-prompt-minimal-v1-seed3411`
> 状态：已训练、已合并、已完成 Fold 0 严格评测
> 建议：拒绝该 Prompt revision 作为 coverage-first 基线的替代方案

## 身份

| 项目 | 值 |
| --- | --- |
| development release | `v4.1.0-ecb5aeb9657c` |
| fold | 0 |
| seed | 3411 |
| 训练样本 | 3,000 |
| 验证样本 | 425 |
| Prompt revision | `v4.1-fixed-full-fields-initial-v1` |
| Prompt content SHA-256 | `2e4e0ad6503dfabab6239028060164edaf0c04cf98923687ddb273e7a21d34d3` |
| experiment contract SHA-256 | `ddec9c90dd8cfb2cc55d094929d556c2685ce429b4daa580b1b6949c08762123` |
| adapter SHA-256 | `55c8e446af827cfb8c2c3cb0ac1aed8dc88bffb9641fb2713fc188dbb3df3e18` |
| merged evidence manifest SHA-256 | `49edbf37119b5e1784e5b10ee731b56834a7e9f8c47c1e9272be0b98ebe5ee56` |

训练和评测使用同一份 `input/experiment_contract.json`。评测的 `run_identity.json`
显式记录该 contract、Prompt revision 和 Prompt content hash，没有使用历史 overlay。

## 训练与合并

- 完成 3 epoch、1,125 optimizer steps；
- `train_loss = 0.06303396`；
- 最佳及最终 `eval_loss = 0.06288376`；
- 最佳 checkpoint 为 `checkpoint-250`；
- 最终 adapter 与最佳 checkpoint 的权重 SHA-256 完全一致；
- adapter 为 460,430,776 字节；
- BF16 merged 模型包含 10 个权重分片；
- merged 目录共 30 个文件、17,407,993,021 字节。

训练 loss 只能证明训练目标收敛，不能替代下面的真实生成效果。

## Fold 0 严格评测

425 条全部完成，没有 runtime failure。

| 指标 | Prompt minimal | coverage-first seed3411 | 变化 |
| --- | ---: | ---: | ---: |
| JSON/contract 合法率 | 86.12% | 100.00% | -13.88 pp |
| joint correct | 24.00% | 37.41% | -13.41 pp |
| `clip_state` | 35.06% | 55.76% | -20.71 pp |
| `fracture_mechanism` | 38.82% | 44.00% | -5.18 pp |
| `fracture_site` | 39.76% | 51.06% | -11.29 pp |
| `special_case` | 86.12% | 100.00% | -13.88 pp |

`clip_state` 各类召回：

| 状态 | Prompt minimal | coverage-first seed3411 |
| --- | ---: | ---: |
| 临界未断裂 | 0.00% | 22.81% |
| 发生断裂 | 57.64% | 54.17% |
| 已断裂 | 12.12% | 0.00% |
| 未断裂 | 32.46% | 76.44% |

主要失败：

- 59 条严格非法输出完全是同一个模式：将 JSON `null` 输出成字符串 `"null"`；
- 模型没有预测任何 `临界未断裂`；
- `未断裂`召回由 76.44% 降到 32.46%；
- 预测明显向 `发生断裂`偏移，未达到“降低标签偏置”的实验目的。

## 实际使用的 Prompt

System Prompt：

```text
你是一位材料力学视频分析助手。请仅依据当前输入视频中可见的信息完成判断，不要推测视频片段之外发生的事件。

请以一个合法 JSON 对象给出结果，不要输出解释、Markdown 或其他文字。结果包含 clip_state、fracture_mechanism、fracture_site、special_case 四个字段。

本任务使用以下标签池：

clip_state：
未断裂、临界未断裂、发生断裂、已断裂、无法判断。

fracture_mechanism：
韧性断裂、脆性断裂、界面脱粘、爆炸性断裂、半脆半韧断裂，以及 null。

fracture_site：
inside_gauge、outside_gauge_non_root、grip_root，以及 null。

special_case：
未夹紧、视频异常，以及 null。

输出结构：

{"clip_state": ..., "fracture_mechanism": ..., "fracture_site": ..., "special_case": ...}
```

User Prompt：

```text
请根据这段拉伸试验视频，判断试样是否发生断裂，并给出相应的断裂模式和断裂位置。
```

该 Prompt 列出了字段和标签池，但没有像 coverage-first Prompt 那样说明：

- 五种 `clip_state` 的时序判定语义；
- `临界未断裂`的视觉条件；
- JSON `null` 与字符串 `"null"` 的区别；
- 四字段之间的联动约束；
- special case 与 `无法判断`的关系。

结合 59 条完全相同的 `"null"` 非法输出、零条 `临界未断裂`预测及明显增多的断裂预测，
可以推断这种删减过度削弱了输出约束和状态判定边界。该结果不支持用 minimal-v1 替换
coverage-first Prompt。

## 训练机产物

```text
workspace/runs/v4.1-prompt-minimal-v1-seed3411/
├── adapter/
├── merged/
├── evaluation/
│   ├── evaluation_records.jsonl
│   ├── evaluation_summary.json
│   ├── run_identity.json
│   ├── runtime_failures.csv
│   └── evidence_manifest.json
└── logs/
    ├── train.log
    ├── merge.log
    └── evaluation.log
```

大型权重和逐样本结果保留在训练机的 Git 忽略 workspace 中。
