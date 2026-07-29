# V4.1 Concise Prompt 三折训练与历史模型对比分析报告

> 日期：2026-07-29
> 当前实验：`v4.1-prompt-concise-cv-v1-seed3411`
> 当前 Prompt：`v4.1-concise-evidence-json-v2`
> 状态：三折训练、最佳 checkpoint 回载、adapter 合并和全量严格评测均已完成
> 审查状态：待独立 reviewer 审查

## 1. 执行摘要

当前实验在 development release `v4.1.0-ecb5aeb9657c` 上完成了 Fold0、
Fold1、Fold2 三折训练和对应验证折的 merged BF16 推理评测，共评测 1,581 条，
没有 runtime failure。

训练侧的过拟合控制按设计生效：

- Fold0、Fold1、Fold2 分别在 300、350、250 optimizer steps 早停；
- 三折最佳 checkpoint 分别为 225、275、175；
- 最终 adapter 均与各自最佳 checkpoint 权重 SHA-256 一致；
- 上一轮在验证损失回升后仍继续训练至 1,125 steps 的问题没有复现。

但任务级效果未达到可接受水平：

- 三折加权 JSON/contract 合法率为 `79.63%`；
- joint correct 为 `32.07%`；
- `clip_state`、`fracture_mechanism`、`fracture_site` 分别为
  `35.80%`、`34.85%`、`37.44%`；
- 322 条输出严格非法，其中 311 条遗漏 `special_case`；
- 模型将 68.88% 的样本预测为“未断裂”，而目标中的“未断裂”仅占 35.42%；
- “临界未断裂”和“已断裂”的三折合计召回率均为 `0%`。

历史完整三折模型中，综合表现最好的是
`v4_1_0_760050fad303_20260724_visual`。它在旧 release 的 1,216 条三折验证样本上
取得 `97.12%` 合法率、`40.21%` joint correct、`49.67%` `clip_state`、
`50.66%` mechanism 和 `56.66%` site。

旧 release 的 1,216 条验证样本全部包含在当前 release 中。把当前模型限制到完全相同的
1,216 条样本后，joint correct 为 `40.13%`，与历史模型近似持平；但合法率下降
14.06 个百分点，三个主要字段分别下降 6.66、7.48 和 11.43 个百分点。
这说明当前模型的 joint 指标被“未断裂”偏置掩盖，不能据此认为当前模型与历史模型等效。

综合证据支持以下结论：

1. 当前早停方案解决了“越过最佳点后继续训练”的运行问题；
2. 当前模型的主要问题已经从过拟合转为输出契约退化和类别坍缩；
3. release 扩大使完整三折验证更难，但无法解释共同样本上的字段退化；
4. Prompt 精简、采样配额变化以及不足一个 3,000 行 epoch 即早停，是需要优先隔离的变量；
5. 在完成交叉 Prompt 对照前，不能把退化单独归因于 Prompt 或采样中的任一项。

## 2. 范围与验收口径

本报告回答四个问题：

1. 当前三折训练是否完整，过拟合控制是否按配置生效；
2. 当前三折 merged model 的任务级效果如何；
3. 历史训练结果中哪个版本综合表现最好；
4. 当前三折与历史最佳版本在数据、Prompt、采样和训练日程上有什么差别。

本报告不把 `train_loss` 或 `eval_loss` 当作任务效果结论。模型验收以严格推理评测中的
JSON/contract 合法率、四字段正确率、joint correct、状态召回和失败样例为准。

不同 release 的全量指标不能直接作为因果对比。为降低样本差异影响，本报告额外计算了
历史和当前 release 共有的 1,216 条验证样本上的当前模型指标。

## 3. 实验身份

### 3.1 当前实验

| 项目 | 值 |
| --- | --- |
| experiment ID | `v4.1-prompt-concise-cv-v1-seed3411` |
| release | `v4.1.0-ecb5aeb9657c` |
| Prompt revision | `v4.1-concise-evidence-json-v2` |
| Prompt content SHA-256 | `0040c7d73cc417ac81fca196fec3c4a30b011ca15549eb324a3a37cde0aff6db` |
| experiment contract SHA-256 | `6ea640efeed5fa196c7af9a2b753ac012cea954326f23eac8f5554d452e1ea3a` |
| experiment contract file SHA-256 | `feded32c864a8f6a6f1c6b6ee7ef09f91c166ae4b99d5981bf5127dab31635b1` |
| sampling manifest SHA-256 | `ba7e03cd3dfab97b1a0cd942cb17a67b842d1596ebf435d4cc3c99025d334566` |
| training seed | `3411` |
| prepared training code commit | `001d636b9ba1fe310466d64fb19a8b92309c3d9f` |
| frozen config commit | `eebe0797981633a1e0a81b60fed81b80e0e7fd1f` |
| evaluation-time repository HEAD | `0225d934fc6ad62394df8e2d61eb2a80a50bfc34` |

从 frozen config commit 到 evaluation-time HEAD，
`finetune/run_v4_1_evaluation.py`、基础 V4.1 contract、模型推理 runtime 和 Prompt
control 目录没有 diff。评测期间 evaluator 和 contract 没有随其他提交漂移。

三折配置位于：

```text
finetune/experiments/v4.1-prompt-concise-cv-v1-seed3411/
├── train_fold0.yaml
├── train_fold1.yaml
├── train_fold2.yaml
├── merge_fold0.yaml
├── merge_fold1.yaml
├── merge_fold2.yaml
└── manifest.json
```

### 3.2 历史最佳完整三折实验

| 项目 | 值 |
| --- | --- |
| run ID | `v4_1_0_760050fad303_20260724_visual` |
| release | `v4.1.0-760050fad303` |
| inference | merged BF16 |
| seed | `3407` |
| fold count | 3 |
| total validation samples | 1,216 |
| historical summary SHA-256 | `395d3c1b9dd15779788afc1bbb434212b30ea00ef35e0e86f83dd1e89a624784` |

历史汇总：

[three_fold_summary.json](../../../finetune/results/v4_1_0_760050fad303_20260724_visual/three_fold_validation/three_fold_summary.json)

历史训练配置：

[v4_1_visual](../../../finetune/MiniCPM/config/active/v4_1_visual)

历史 summary 记录的 `contract_hash` 为
`47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937`，
当前 summary 记录的是修正后的 runtime contract hash
`3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`。
提交 `c6098ab1` 修正了 evaluator 的 contract 身份记录并增加 Prompt contract 支持，
没有修改 `parse_v4_1_output`、`score_v4_1_prediction` 或标签语义。因此历史和当前指标
使用相同的严格解析与评分逻辑，但 run identity 不是字节级相同；reviewer 应独立复核这一点。

### 3.3 同 release 的历史 Fold0 参考

严格限定当前 release `v4.1.0-ecb5aeb9657c` 和当前 runtime contract 时，历史结果只有
Fold0，没有完整三折。其中 coverage-first seed3407 是综合最均衡的 Fold0 参考：

| 指标 | coverage-first seed3407 |
| --- | ---: |
| contract valid | 100.00% |
| joint correct | 41.18% |
| `clip_state` | 56.00% |
| mechanism | 45.88% |
| site | 54.82% |

它不能替代完整三折基线，但可用于隔离同 release Fold0 上的 Prompt 和采样差异。

## 4. 当前三折训练结果

### 4.1 完成状态

训练按 Fold0 → Fold1 → Fold2 顺序连续完成。三个根 adapter 均包含
`adapter_config.json`、`adapter_model.safetensors`、`trainer_state.json`、
`train_results.json` 和 `eval_results.json`。

| Fold | 训练开始 | 训练完成 | 最佳 checkpoint | 停止 step | 停止 epoch |
| --- | --- | --- | ---: | ---: | ---: |
| 0 | 2026-07-28 22:19 | 2026-07-29 00:05 | 225 | 300 | 0.80 |
| 1 | 2026-07-29 00:05 | 2026-07-29 02:35 | 275 | 350 | 0.93 |
| 2 | 2026-07-29 02:35 | 2026-07-29 04:11 | 175 | 250 | 0.67 |

### 4.2 损失轨迹与早停

| Fold | 最佳 eval loss | 停止前 eval loss | 最佳后无改善次数 | 最终回载 |
| --- | ---: | ---: | ---: | --- |
| 0 | 0.061839 | 0.063067 | 3 | checkpoint-225 |
| 1 | 0.079850 | 0.093899 | 3 | checkpoint-275 |
| 2 | 0.079206 | 0.084071 | 3 | checkpoint-175 |

配置为每 25 steps 验证一次、`early_stopping_patience=3`。三折均在最佳点后 75 steps
停止，行为与配置一致。

上一轮 Prompt minimal Fold0 在 step 250 达到 `0.062884` 后仍训练至 step 1,125，
验证损失最高升至约 `0.139`。当前 Fold0 最佳 eval loss 比上一轮低约 1.66%，
且在 step 300 停止。训练运行层面的过拟合控制有效。

这不等于模型不再具有过拟合倾向。三折验证损失仍在最佳点后回升，只是训练及时停止并
回载了最佳权重。

## 5. 当前三折全量严格评测

### 5.1 各折指标

| Fold | 样本 | contract valid | joint | `clip_state` | mechanism | site | runtime failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 425 | 89.41% | 43.53% | 46.35% | 47.06% | 46.12% | 0 |
| 1 | 664 | 71.08% | 23.19% | 26.66% | 26.81% | 29.82% | 0 |
| 2 | 492 | 82.72% | 34.15% | 39.02% | 35.16% | 40.24% | 0 |
| 加权 | 1,581 | **79.63%** | **32.07%** | **35.80%** | **34.85%** | **37.44%** | **0** |

各折 `special_case` correct 与 contract valid 相同，因为严格非法记录的所有字段均按失败计分。

### 5.2 状态分布与召回

| `clip_state` | 目标数 | 正确数 | 召回率 |
| --- | ---: | ---: | ---: |
| 未断裂 | 560 | 483 | 86.25% |
| 发生断裂 | 642 | 83 | 12.93% |
| 临界未断裂 | 174 | 0 | 0.00% |
| 已断裂 | 205 | 0 | 0.00% |

预测分布：

| 预测 | 数量 | 占比 |
| --- | ---: | ---: |
| 未断裂 | 1,089 | 68.88% |
| 发生断裂 | 159 | 10.06% |
| 临界未断裂 | 8 | 0.51% |
| 已断裂 | 3 | 0.19% |
| 严格非法 | 322 | 20.37% |

模型输出明显坍缩到“未断裂”。这会提高未断裂样本上的 joint correct，因为未断裂的三个
附加字段都为 `null`；同时严重损害其他状态的召回。因此 joint correct 必须和状态召回、
字段正确率、合法率一起解释。

### 5.3 严格非法输出

322 条严格非法输出分为：

- 311 条缺少 `special_case`；
- 11 条输出 `special_case: "未夹紧"`，同时保持
  `clip_state: "未断裂"`，违反 special case 必须对应“无法判断”的契约。

缺少字段的典型形式为：

```json
{"clip_state":"发生断裂","fracture_mechanism":"韧性断裂","fracture_site":"inside_gauge"}
```

这不是 JSON 语法错误，而是缺少必需字段导致的 contract failure。

## 6. 历史结果筛选

历史评测中存在不同 release、不同 precision、不同 adapter 加载方式和单折 smoke test。
本报告采用以下筛选原则：

1. 排除 1 条样本的 smoke test；
2. 完整三折优先于单折；
3. merged BF16 优先作为训练版本主结果；
4. 同 release、同 runtime contract 的结果用于直接局部参考；
5. 不把旧 release 的绝对指标直接解释为当前 release 上的预期值。

按上述原则，历史完整三折最佳版本是
`v4_1_0_760050fad303_20260724_visual`：

| 指标 | 历史 visual 三折 |
| --- | ---: |
| contract valid | 97.12% |
| joint correct | 40.21% |
| `clip_state` | 49.67% |
| mechanism | 50.66% |
| site | 56.66% |

该版本各折 joint 为 42.12%、34.38%、45.38%。历史单折最高 joint 是它的 Fold2
`45.38%`，但单折最高值不应替代三折加权结论。

## 7. 与历史最佳模型的对比

### 7.1 全量结果

| 模型 | release | 样本 | valid | joint | state | mechanism | site |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 历史 visual 三折 | `760050fad303` | 1,216 | 97.12% | 40.21% | 49.67% | 50.66% | 56.66% |
| 当前 concise 三折 | `ecb5aeb9657c` | 1,581 | 79.63% | 32.07% | 35.80% | 34.85% | 37.44% |

当前 release 的 Fold0 验证集与历史完全相同；Fold1 在历史 445 条基础上新增 219 条，
Fold2 在历史 346 条基础上新增 146 条。新增样本使当前全量结果更难，故仅凭上表无法隔离
训练版本差异。

### 7.2 完全相同的 1,216 条样本

从当前三折记录中只保留旧 release 已有样本，得到：

| 模型 | valid | joint | state | mechanism | site |
| --- | ---: | ---: | ---: | ---: | ---: |
| 历史 visual 三折 | **97.12%** | **40.21%** | **49.67%** | **50.66%** | **56.66%** |
| 当前模型共同子集 | 83.06% | 40.13% | 43.01% | 43.17% | 45.23% |
| 当前相对变化 | -14.06 pp | -0.08 pp | -6.66 pp | -7.48 pp | -11.43 pp |

共同子集上的 joint 几乎相同，但当前模型：

- 严格非法数从历史的 35 增至 206；
- “发生断裂”召回从 33.58% 降至 12.99%；
- “临界未断裂”召回从 31.06% 降至 0%；
- “已断裂”召回从 9.00% 降至 0%；
- “未断裂”召回从 74.59% 升至 85.92%。

因此 joint 持平不是能力持平，而是预测偏置改变后形成的指标补偿。

### 7.3 同 current release Fold0 参考

| 指标 | coverage-first seed3407 | 当前 Fold0 | 当前变化 |
| --- | ---: | ---: | ---: |
| valid | 100.00% | 89.41% | -10.59 pp |
| joint | 41.18% | 43.53% | +2.35 pp |
| state | 56.00% | 46.35% | -9.65 pp |
| mechanism | 45.88% | 47.06% | +1.18 pp |
| site | 54.82% | 46.12% | -8.71 pp |

当前 Fold0 的 joint 提升不足以抵消合法率、状态和位置指标的下降。

## 8. 训练方案差异

### 8.1 模型与 LoRA 参数

以下配置保持一致：

- MiniCPM-V 4.5；
- `lora_target: all`；
- rank 8、alpha 16、dropout 0.25；
- `additional_target: resampler`；
- vision tower 和 multimodal projector 均不冻结；
- 4-bit QLoRA；
- learning rate `5e-6`；
- weight decay `0.2`；
- batch size 1、gradient accumulation 8；
- cosine scheduler、warmup ratio 0.1。

没有证据表明本次退化来自 rank、dropout、学习率或 weight decay 的变化。

### 8.2 数据发布版

历史 release 每折原始训练数为 850、830、929；当前 release 每折唯一训练候选为
1,253、1,014、1,186。

当前验证目标更偏向断裂：

| release | 未断裂 | 发生断裂 | 临界未断裂 | 已断裂 |
| --- | ---: | ---: | ---: | ---: |
| 历史 1,216 条 | 44.98% | 33.55% | 13.24% | 8.22% |
| 当前 1,581 条 | 35.42% | 40.61% | 11.01% | 12.97% |

当前 release 更难，但共同样本上的退化证明“验证集更难”不是唯一原因。

### 8.3 采样策略

当前每折扩采样到 3,000 条，并限制同 source 和同 effective-frame signature 的重复。
以 current release Fold0 为例：

| 状态 | 历史 coverage-first seed3407 | 当前 Fold0 |
| --- | ---: | ---: |
| 未断裂 | 900 | 1,142 |
| 发生断裂 | 1,185 | 943 |
| 临界未断裂 | 351 | 351 |
| 已断裂 | 564 | 564 |

当前采样相当于把 242 个 exposure 从“发生断裂”转给“未断裂”。这与预测向未断裂坍缩
方向一致，是一个强相关证据，但尚不能独立证明因果。

### 8.4 Prompt

历史 contract Prompt：

- system prompt 99 字符；
- user prompt 666 字符；
- 总计约 765 字符；
- user prompt 明确重复四字段、状态决策树、字段联动和特殊情况规则。

当前 Prompt：

- system prompt 444 字符；
- user prompt 39 字符；
- 总计约 483 字符；
- 状态定义和枚举集中到 system prompt；
- user prompt 仅保留一般任务描述。

当前 Prompt 总长度更短，但 system 部分更长，且删除了历史 user prompt 中更细粒度的
强制输出表达。训练时 system 和 user 都随每条样本传入，因此把约束从 user 移到 system
本身不会减少每条训练样本的重复；真正减少的是总 prompt token 和约束细节。

当前 311 条遗漏 `special_case` 与 Prompt 精简方向一致，但在执行交叉 Prompt 对照前，
只能表述为强相关，不能认定为单一原因。

### 8.5 训练日程

| 项目 | 历史 visual | 当前 concise |
| --- | ---: | ---: |
| epoch 上限 | 3 | 2 |
| eval/save steps | 50 | 25 |
| early stopping | 无 | patience 3 |
| 实际 optimizer steps | 321 / 312 / 351 | 300 / 350 / 250 |
| 完整数据遍历 | 原始训练集约 3 次 | 扩采样集不足 1 epoch |
| seed | 3407 | 3411 |

两者实际 optimizer steps 接近，但数据暴露方式不同。历史模型完整遍历较小的唯一候选集
三次；当前三折在 3,000 行扩采样集的 0.67–0.93 epoch 停止。

早停成功防止验证损失持续恶化，但可能在扩采样序列完整覆盖前结束训练。该影响需要通过
“至少完成一个 epoch 后才启用早停”的对照实验确认。

## 9. 证据分级

### 9.1 已确认事实

- 三折训练、合并和全量评测均完成，runtime failure 为 0；
- 三折早停和最佳 checkpoint 回载均按配置生效；
- 当前模型存在 322 条严格非法输出，其中 311 条缺少 `special_case`；
- 当前模型在全量和共同子集上均严重偏向“未断裂”；
- 当前三折没有正确识别任何“临界未断裂”和“已断裂”；
- 当前和历史模型结构及主要 LoRA/优化器参数一致；
- 当前 release 验证集包含历史 release 的全部验证样本；
- 在相同 1,216 条样本上，当前模型的合法率和三个主要字段指标均低于历史模型。

### 9.2 强推断

- Prompt 精简削弱了四字段完整输出约束；
- Fold0 采样中未断裂 exposure 增加促进了未断裂偏置；
- 在不足一个 3,000 行 epoch 时早停可能降低了状态覆盖。

这些推断与观测方向一致，但当前实验同时改变了 Prompt、release、采样、seed 和训练日程，
不能单独归因。

### 9.3 尚未确认

- 新增训练候选是否存在标签质量或 source 分布问题；
- seed 3407 → 3411 对当前三折退化的贡献；
- 仅恢复历史 Prompt 能否修复 schema 和状态召回；
- 仅恢复 coverage-first 配额能否消除未断裂偏置；
- 至少完成一个完整 epoch 后，任务指标是否继续改善或再次过拟合。

## 10. 建议的下一步实验

### 10.1 先做无需重训的交叉 Prompt 测试

在固定、按状态分层的同一小型 canary 上运行：

1. 历史最佳模型 + 历史 Prompt；
2. 历史最佳模型 + 当前 concise Prompt；
3. 当前模型 + 当前 concise Prompt；
4. 当前模型 + 历史 Prompt。

该 2×2 对照可初步区分推理 Prompt 与训练权重的影响。canary 必须覆盖四种有效
`clip_state`，并报告字段缺失率和各状态召回。

### 10.2 下一轮训练只改受控变量

建议的首个训练对照：

- 恢复历史 Prompt 的四字段强制输出和字段联动语义；
- 保留当前 release 和 source-level 三折；
- 将 Fold0 未断裂固定回约 900/3,000，并把 exposure 返还给发生断裂；
- 为 Fold1、Fold2制定同一比例、受容量约束的配额；
- 至少完成一个完整 3,000 行 epoch 后才允许早停；
- 保持 rank、dropout、learning rate、weight decay 不变。

这能避免再次同时改变过多变量。

### 10.3 增加验收门槛

下一轮不能只用 eval loss 和 joint correct。建议至少设置：

- contract valid rate ≥ 97%；
- 临界未断裂召回 > 0，且设置明确下限；
- 已断裂召回 > 0，且设置明确下限；
- 发生断裂召回显著高于当前 12.93%；
- 不允许预测分布中单一普通状态占比异常超过目标分布；
- 同时报告 macro state recall；
- 三折均通过，而不是只看 Fold0。

具体阈值应由 reviewer 结合业务容忍度审查后冻结。

## 11. Reviewer 建议重点

请 reviewer 独立核对：

1. 历史最佳版本选择是否合理，是否遗漏其他完整三折证据；
2. 共同 1,216 条样本筛选是否确实按 `video_path` 精确交集；
3. 加权指标和百分点差异是否计算正确；
4. 当前 322 条非法输出的分类是否完整；
5. joint 持平但字段退化的解释是否存在评分器结构性误读；
6. 当前采样配额与未断裂偏置之间是否有其他混杂变量；
7. “至少一完整 epoch 后早停”是否与现有 Trainer callback 实现兼容；
8. 建议的交叉 Prompt canary 是否足以隔离推理 Prompt 影响；
9. 下一轮验收门槛是否需要加入 source-level bootstrap 置信区间；
10. 当前结论是否错误地把相关性写成因果。

## 12. 证据位置与哈希

当前训练机：

```text
/home/liuyang/文档/mVllm_2/workspace/runs/v4.1-prompt-concise-cv-v1-seed3411/
├── input/
├── fold0/
│   ├── adapter/
│   ├── merged/
│   └── evaluation/
├── fold1/
│   ├── adapter/
│   ├── merged/
│   └── evaluation/
└── fold2/
    ├── adapter/
    ├── merged/
    └── evaluation/
```

当前评测摘要 SHA-256：

| Fold | `evaluation_summary.json` |
| --- | --- |
| 0 | `5f74b404db1ab4ec1e3fa9a11cfb7d33f93a1208d9df1da26992817cee55ae5f` |
| 1 | `ad4be872311eadfebd665571d1dc1d37aa480b79076c025833a3ca633212460b` |
| 2 | `e4b18217f97dcc15f25790487c878fca2d3596b9c4967dd0289ad11f33a7ad6f` |

逐样本记录 SHA-256：

| Fold | `evaluation_records.jsonl` |
| --- | --- |
| 0 | `bba43698f8ac850ab0e8375c0c2ead895c1b8ab401c53afc9c2ce60cfeb676ce` |
| 1 | `c57f58d5e669259aeb0ca1d03f9216c04324c255acc84f1d196aafa91c3032da` |
| 2 | `72e2bfcdd27e697da906c4d33120b3fb9a12d5ea81b59af3ff98a256e745d98c` |

历史冻结结果：

```text
finetune/results/v4_1_0_760050fad303_20260724_visual/
docs/results/v4_1_0_760050fad303_20260724_visual/
```

大型权重和当前逐样本推理记录保留在训练机 Git 忽略的 `workspace/` 中，没有纳入 Git。

## 13. 限制

- 本报告没有重新评测历史模型，只使用已冻结的历史严格评测证据；
- 历史和当前 summary 的 contract identity 字段不同；代码 diff 表明评分逻辑未变，
  但仍应由 reviewer 复核；
- 不同 release 的全量结果仅用于背景，直接结论优先使用共同样本；
- 共同样本重算使用当前已有逐样本记录，没有改变生成输出；
- 当前实验同时改变多个变量，根因结论只能分级表述；
- 报告尚未经过独立 reviewer 审查。
