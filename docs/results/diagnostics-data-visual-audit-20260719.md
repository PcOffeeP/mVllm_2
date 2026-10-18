> **迁入说明**
>
> - 来源：`codeup/diagnostics/data-visual-audit` @ `bcdf4f36`
> - 原始提交日期：2026-07-19
> - 迁入日期：2026-10-18
> - 迁入原因：保留 2026-07 诊断结论与负面证据：`has_fracture` recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
> - 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置**可能已失效**；正文数字与结论**保持原样未改**，请按历史证据阅读，不要当作当前状态。
> - 失效路径（正文引用、当前仓库不存在）：`pipeline/contracts/tensile_vlm_v1.json`
> - 未随迁（原 `finetune/results/diagnostics/` 下的数据与依赖，留 `bcdf4f36` + bundle）：`finetune/results/diagnostics/checkpoint_comparison/production_prompt_run`、`finetune/results/diagnostics/minimal_overfit/preprocessing_alignment.json`

# mVllm_2 诊断执行报告

日期：2026-07-19
执行位置：开发机做静态分析与汇总；GPU 训练、推理和评测均在训练机执行。

## 结论

计划中的阶段 0～5 已全部执行，并于 2026-07-19 使用当前 production system/user prompt 重新评测全部可用 checkpoint。模型验收仍然失败。当前主要问题不是 LoRA 或视觉输入链路无法学习，而是模型在完整验证集上形成了强烈的“未断裂”偏置，同时不能稳定遵循四字段输出契约。当前任何 checkpoint 或 E1～E4 模型都不应作为合格模型发布。

## 2026-07-19 当前 production prompt 重评

本轮固定使用 `pipeline/contracts/tensile_vlm_v1.json` 中的 system/user prompt：

- contract version：`tensile-vlm/v1`
- contract SHA-256：`138892f185bf4bbafdb388243d99b0fa7d5116598c2ab6f5254fcaafd01ddd7b`
- system prompt SHA-256：`ff4fa8f6d478f4c860997570f23ec4c40647749de2c4ee621987abc12a9130b4`
- 验证集：人工修订后的 `fold_0_val.json`，324 条、17 个源
- dataset SHA-256：`e0b8b4df05e1ad222993878146e6f28f29fc3095306fc8bed46956f3bc6cd3a6`
- 运行错误：所有 checkpoint 均为 0

| 模型 | schema | legal | has accuracy | has F1 | recall | type macro-F1 | location | interval exact | interval ±1 | joint |
|------|-------:|------:|-------------:|-------:|-------:|--------------:|---------:|---------------:|------------:|------:|
| step 200 | 2.78% | 0% | 47.22% | 16.75% | 9.50% | 6.03% | 0% | 1.68% | 2.79% | 0% |
| step 250 | 4.32% | 0% | 47.22% | 16.75% | 9.50% | 6.03% | 0% | 1.68% | 3.35% | 0% |
| step 300 | 4.63% | 0% | 47.53% | 16.83% | 9.50% | 6.03% | 0% | 1.68% | 3.35% | 0% |
| step 350 | 4.63% | 0% | 47.53% | 16.83% | 9.50% | 6.03% | 0% | 1.68% | 3.91% | 0% |
| step 360 | 5.25% | 0% | 47.53% | 16.75% | 9.50% | 6.03% | 0% | 1.68% | 3.91% | 0% |
| final | 4.63% | 0% | 47.53% | 16.83% | 9.50% | 6.03% | 0% | 1.68% | 3.91% | 0% |

所有模型的 JSON 可解析率为 99.69%～100%，但这不代表符合输出契约。典型输出只有 `{"has_fracture": false}`：step 200/250 为 299/324 条，step 300/350/360/final 为 300/324 条。四字段完整输出只有 23～24 条，且 legal combination 与 joint success 对所有模型均为 0。final 的少数正预测还会输出训练词表外的 `"颈缩"`、`"中部"`、`"试样中部"`，或把 `fracture_between` 生成为超长数字字符串，说明失败同时涉及字段缺失、枚举漂移和区间生成失控。

这说明：

1. 200～final 的断裂召回完全不变，不存在可通过挑选后期 checkpoint 解决的问题。
2. step 300/350/final 的微小 F1 优势没有任务意义；所有模型均远低于验收线。
3. final adapter SHA-256 与 checkpoint 350 相同，final 实质是 checkpoint 350 的合并版本；旧 `merge_metadata.json` 指向 360 是产物链路错误。
4. 旧 `full_run_exact` 和 E0～E4 使用的是 `medium` 实验 prompt，而非当前 production contract。它们只能作为历史诊断证据，不得作为当前 prompt 下的模型性能或与本表直接比较。

证据：`finetune/results/diagnostics/checkpoint_comparison/production_prompt_run/`

## 关键证据

### 1. 训练/推理链路

旧推理把多帧打包成单一视觉块，且图像尺寸、slice 参数和 prompt 空白字符均与训练不一致。修复后：

- training prompt tokens：524
- inference prompt tokens：524
- exact token match：true
- image bounds / target sizes：6 / 6

证据：`finetune/results/diagnostics/minimal_overfit/preprocessing_alignment.json`

### 2. 人工视觉盲审

32 条样本包含 16 正、15 负、1 异常：

- 正样本清晰可见断裂：7/16
- 不清晰或不可见：9/16（56.25%）
- GT 与可见转变匹配：3/16
- GT 不匹配：13/16（81.25%）
- frame mapping：32/32 对齐

这排除了帧读取索引漂移，并直接确认原数据的可辨识性与标签质量不足。

### 3. 旧 Checkpoint 对比（历史 medium prompt）

step 200、250、300、350、360 和 final 的 `has_fracture` recall 均为 0.100559。最佳 source-macro F1 是 step 300 的 0.354851，而 eval-loss 选中 step 350。所有验收阈值均失败，因此：

- 不是训练后期召回塌缩；
- 不能继续用 eval-loss 单独选择模型；
- step 150 没有可用产物，已标记 missing，没有伪造补测。

该结果使用旧 `medium` 实验 prompt，已由上方 production prompt 重评取代，不能再作为当前线上 prompt 的性能数字。

### 4. 最小过拟合

修复后的 240-step LoRA 在 16 条训练样本上达到：

- JSON/schema/legal：100%
- has accuracy/F1/recall：100%
- type/location：100%
- interval exact/±1：100%
- joint success：100%

视觉反事实相对原视频的 exact-changed rate 为：首帧重复 25%、倒序 25%、黑帧 43.75%。因此模型能够记忆小数据并对视觉变化作出响应，训练链路本身成立。

旧的 `minimal_overfit_summary.json` 是预处理修复前结果，已由 `minimal_overfit_summary_exact.json` 明确标记为失效。

### 5. 数据门禁与控制实验（历史 medium prompt）

原始候选的 84 条正样本盲审结果为 true 20、uncertain 44、false 20，且区间 3-4 无合格样本，门禁正确拒绝直接训练。

随后使用 8 个视觉确认源，确定性时序重采样得到 56 正 + 56 同源负样本，7 个 interval 各 8 条。修复数据集 SHA-256：

`17a15986d6c11967af1417e3577b89df4e619c5c28727c1ad88bbad8c5e0156c`

E0～E4 结果：

| 实验 | has F1 | recall | interval exact | joint | source-macro F1 | legal |
|------|-------:|-------:|---------------:|------:|----------------:|------:|
| E0 | 0.1782 | 0.1006 | 0.0112 | 0.0112 | 0.3525 | 0.6080 |
| E1 | 0.1683 | 0.0950 | 0.0056 | 0.0056 | 0.2207 | 0.9537 |
| E2 | 0.1683 | 0.0950 | 0.0056 | 0.0056 | 0.2207 | 0.9537 |
| E3 | 0.1683 | 0.0950 | 0.0112 | 0.0112 | 0.1619 | 0.9568 |
| E4 | 0.1782 | 0.1006 | 0.0000 | 0.0000 | 0.3948 | 0.5031 |

E1～E3 改善了合法组合率，但未改善断裂识别；E4 的 source-macro 指标较高，却把 interval/joint 降为 0。没有实验通过多指标验收。

E0～E4 的推理同样使用旧 `medium` 实验 prompt。其“控制实验均未通过”的结论仍成立，但其中的绝对指标不能代表当前 production prompt 性能；如需比较这些重训模型，必须按本轮相同 contract 重新评测。

## 验收结论

| 指标 | 要求 | 最好可用结果 | 通过 |
|------|-----:|-------------:|:----:|
| JSON valid | ≥99.5% | 100%（production prompt） | 是 |
| legal combination | ≥99% | 0%（production prompt） | 否 |
| has F1 | ≥75% | 16.83%（production prompt） | 否 |
| has recall | ≥75% | 9.50%（production prompt） | 否 |
| interval ±1 | ≥75% | 3.91%（production prompt） | 否 |
| joint | ≥40% | 0%（production prompt） | 否 |
| source/clip gap | <10pp | 15.58pp～15.66pp（production prompt） | 否 |

最终判定：**诊断计划执行完成，模型交付验收失败。**

## 后续进入新训练前的硬门槛

1. 冻结 `tensile-vlm/v1` contract，并用它重新生成训练 JSON 的 system/user prompt；不要继续用旧训练 system prompt 与线上 prompt 混训。
2. 在重训前加入四字段格式门禁：负样本也必须输出 `fracture_between:null`、`type:"未断裂"`、`location:null`；先用 16 条最小过拟合验证 schema/legal 均为 100%。
3. 重新生成 ROI 和时间区间标签，并逐源人工确认可见断裂转变。
4. 训练集和验证集都以 source 为单位建立门禁，正样本清晰可见率应达到 ≥95%，标签区间人工一致率应达到 ≥95%。
5. 增加各断裂类型的独立源视频数量，避免单源类型捷径，并移除 `focus_*` 必为正、`neg_before` 必为负的裁剪命名/构造捷径。
6. 保留当前 exact 预处理一致性审计作为每次训练的前置测试。
7. 新模型必须同时通过 has、interval、joint、legal 和 source-level 指标；不得只按 eval-loss 或单一 source-macro 指标发布。

## 产物同步

训练机轻量诊断产物已同步到当前工作区，未同步 merged model、adapter 权重和生成视频。2026-07-19 production-prompt 评测同步压缩包 SHA-256：

`5f2626522a67d7be036349c6f22099bb1c9b10de45b6b76874835286e8ed53e5`
