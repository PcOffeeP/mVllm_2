> **迁入说明**
>
> - 来源：`codeup/diagnostics/data-visual-audit` @ `bcdf4f36`
> - 原始提交日期：2026-07-19
> - 迁入日期：2026-10-18
> - 迁入原因：保留 2026-07 诊断结论与负面证据：`has_fracture` recall 9.50%、legal/joint 0%、任何 checkpoint 与 E1～E4 不得发布。
> - 阅读提示：本文件结论形成于 2026-07，其中路径、命令与数据位置**可能已失效**；正文数字与结论**保持原样未改**，请按历史证据阅读，不要当作当前状态。
> - 改名映射：原 `docs/diagnostics_report.md` → 迁入后 `docs/results/diagnostics-data-visual-audit-20260719.md`
> - 正文中原指向同目录 `diagnostics_report.md` 的相对链接已改为反引号写法，仅为避免制造失效链接，未改动文字。
> - 失效路径（正文引用、当前仓库不存在）：`pipeline/scripts/quality_check.py`、`finetune/MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml`
> - 未随迁（原 `finetune/results/diagnostics/` 下的数据与依赖，留 `bcdf4f36` + bundle）：`finetune/results/diagnostics/data_audit/training_distribution.json`、`finetune/results/diagnostics/visual_audit/visual_audit_summary.json`、`finetune/results/diagnostics/checkpoint_comparison/full_run_exact/checkpoint_comparison.json`、`finetune/results/diagnostics/checkpoint_comparison/production_prompt_run/checkpoint_comparison.json`、`finetune/results/diagnostics/minimal_overfit/minimal_overfit_summary_exact.json`、`finetune/results/diagnostics/control_experiments/control_comparison.json`、`finetune/results/diagnostics/control_experiments/visual_gate/visual_gate_summary.temporal_reindexed.json`

# mVllm_2 诊断流程

## 0. 项目状态总览

状态：**计划中的阶段 0～5 已执行完成，并于 2026-07-19 使用当前 production prompt 重评全部可用 checkpoint。诊断验收未通过，不应将当前任何 checkpoint 或控制实验模型发布为合格模型。**

最终结论：

- 训练/推理预处理链路原先存在实质性错位，现已修复并验证为 prompt token 逐 token 一致（524/524），6 个视觉块边界一致。
- 历史 medium-prompt checkpoint 对比显示 `has_fracture` recall 固定在 10.06% 左右；当前 production-prompt 重评固定为 9.50%，均排除训练后期塌缩。
- 16 条最小过拟合集可达到 has/interval/type/location/joint 全部 100%，且视觉反事实会改变输出，证明 LoRA、视觉输入和标签链路能够学习。
- 32 条盲审中，56.25% 的正样本断裂不清晰可见，81.25% 的正样本 GT 区间与可见转变不匹配；核心瓶颈是数据可辨识性和标签/裁剪质量。
- E1～E4 均未达到验收线。E4 虽有最高 source-macro F1（0.3948），但 interval exact 和 joint 均为 0，不能作为候选模型。
- 当前 `tensile-vlm/v1` production prompt 下，step 200～final 的 recall 均为 9.50%，legal 与 joint 均为 0；不存在可发布 checkpoint。
- 旧 `full_run_exact` 和 E0～E4 使用 `medium` 实验 prompt，只保留为历史诊断证据，不能代表当前 production prompt 性能。

详细结论见 `diagnostics_report.md`。

## 1. 已知事实（最终确认）

- fold 0 训练集 953 条：491 正 / 462 负，不失衡
- [4,5] 是 fracture_between 最密集区间（104 条），[1,2] 仅 86 条
- neg_before → 100% 负样本，focus_* → 100% 正样本（裁剪捷径）
- 类型源视频多样性：界面脱粘 4 源、齐根断裂 3 源、组合 2 源、爆炸性 1 源、半脆半韧 1 源
- quality_check 已修复白名单模式，1724 条误报已消除
- 静态预检全部通过；本轮新增 production prompt 评测测试后，本地完整测试为 272 passed

## 2. 工作目录和分支

- 分支：`diagnostics/data-visual-audit`
- 训练机项目目录：`~/文档/mVllm_2`
- 训练机已安装：conda 环境（含 torch、transformers）+ pytest

## 3. 已完成的工作

### 3.1 阶段 0：静态预检

- quality_check.py 改为白名单模式，新增 _validate_test_subvideo_artifacts
- 新增 7 个测试（72/72 passed）
- 训练机验证：所有预检 0 错误

### 3.2 阶段 1：训练数据审计

- 生成 training_distribution.json（51.7 KB）
- 19 条告警：裁剪捷径、源多样性不足、区间分布不均

### 3.3 阶段 2：实际视觉盲审

- 盲审 32 条：16 正、15 负、1 异常
- 正样本断裂清晰可见 7/16，不清晰或不可见 9/16
- 正样本 GT 与可见转变匹配 3/16，不匹配 13/16
- frame mapping 32/32 对齐，排除帧加载索引漂移
- 判定：停止直接基于原候选集重训，先修 ROI、帧采样和标签映射

### 3.4 阶段 3：Checkpoint 对比

- 实际存在并完成：step 200、250、300、350、360、final；step 150 产物不存在，已在汇总中如实标记 missing
- 所有完成点的 `has_fracture` recall 均为 0.100559
- 最佳 source-macro F1 是 step 300 的 0.354851；eval-loss 选中的 step 350 并非任务指标最优
- 所有诊断验收项均失败，排除“训练后期召回塌缩”
- 2026-07-19 用当前 `tensile-vlm/v1` contract 重评 324 条验证样本：
  - step 200～final 的 recall 均为 0.094972
  - legal 与 joint 均为 0
  - schema valid 仅 0.027778～0.052469
  - 绝大多数输出只有 `has_fracture` 一个字段
  - final adapter 与 checkpoint 350 的 SHA-256 相同，旧 metadata 指向 360 不可信

### 3.5 阶段 4：最小过拟合

- 修复推理链路后，训练/推理 prompt token 完全一致：524/524，6 个 image bounds
- 240-step LoRA 在 16 条训练样本上达到：
  - has_fracture accuracy/F1/recall = 1.0
  - interval exact/±1 = 1.0
  - type/location/joint = 1.0
- 反事实 exact-changed rate：
  - 首帧重复 25.00%
  - 倒序 25.00%
  - 黑帧 43.75%
- 判定：训练链路可学习且使用视觉输入；主要问题在数据质量与跨源泛化

### 3.6 阶段 5：控制变量重训

原始 84 条候选正样本的视觉门禁失败（true 20、uncertain 44、false 20，区间 3-4 无合格样本）。随后只使用 8 个人工确认的真实转变源，通过确定性时序重采样构造 56 正 + 56 同源负样本，7 个 interval 各 8 条，并记录完整 hash/provenance 后才放行 E1～E3。

| 实验 | 受控改动 | has F1 | recall | interval exact | joint | source-macro F1 | 结论 |
|------|----------|-------:|-------:|---------------:|------:|----------------:|------|
| E0 | 原基线，LR 5e-6 | 0.1782 | 0.1006 | 0.0112 | 0.0112 | 0.3525 | 不通过 |
| E1 | 修复数据，原正则 | 0.1683 | 0.0950 | 0.0056 | 0.0056 | 0.2207 | 不通过 |
| E2 | E1 + dropout 0.1 | 0.1683 | 0.0950 | 0.0056 | 0.0056 | 0.2207 | 不通过 |
| E3 | E2 + weight decay 0.01 | 0.1683 | 0.0950 | 0.0112 | 0.0112 | 0.1619 | 不通过 |
| E4 | 原数据，LR 1e-5 | 0.1782 | 0.1006 | 0.0000 | 0.0000 | 0.3948 | 不通过 |

模型选择脚本按预定 source-macro 指标选出 E4，但多指标验收否决 E4；不得只依据单一 selection metric 发布模型。

## 4. 实施中发现并修复的链路问题

- 训练插件会将每帧约束到最大 256×256 像素，并使用 `max_slice_nums=2`；旧推理未对齐。
- 旧推理传入 `temporal_ids`，将 6 帧打包为 1 个视觉块；训练使用 6 个独立视觉块。
- 旧评测会裁掉 system/user 尾部换行，与训练 prompt 不一致。
- 上述问题已在 `finetune/validation/model_runtime.py` 和诊断评测脚本中修复，并由 `audit_training_inference_alignment.py` 验证。
- 修复前产生的最小过拟合和 checkpoint 指标均视为 superseded，不得与 exact/full_run_exact 结果混用。

## 5. 关键文件清单

| 路径 | 说明 |
|------|------|
| `pipeline/scripts/quality_check.py` | 质量检查器（已修复） |
| `finetune/results/diagnostics/data_audit/training_distribution.json` | 数据审计报告 |
| `finetune/results/diagnostics/visual_audit/visual_audit_summary.json` | 32 条盲审汇总 |
| `finetune/results/diagnostics/checkpoint_comparison/full_run_exact/checkpoint_comparison.json` | 历史 medium-prompt checkpoint 汇总 |
| `finetune/results/diagnostics/checkpoint_comparison/production_prompt_run/checkpoint_comparison.json` | 当前 production-prompt checkpoint 汇总 |
| `finetune/results/diagnostics/minimal_overfit/minimal_overfit_summary_exact.json` | 修正后的最小过拟合汇总 |
| `finetune/results/diagnostics/control_experiments/control_comparison.json` | E0～E4 对比 |
| `finetune/results/diagnostics/control_experiments/visual_gate/visual_gate_summary.temporal_reindexed.json` | 修复数据门禁与 provenance |
| `finetune/MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml` | Fold 0 训练配置 |
| `finetune/validation/model_runtime.py` | 模型加载与推理 |

## 6. 验收标准

| 指标 | 阶段 0 ✅ | 阶段 2~4 目标 | 最终 test 前 |
|------|:---------:|:-------------:|:------------:|
| JSON valid | >=99.5% | — | — |
| legal combination | >=99% | — | >=99.5% |
| has_fracture F1 | — | >=75% | — |
| has_fracture recall | — | >=75% | >=85% |
| positive interval ±1 | — | >=75% | — |
| positive joint success | — | >=40% | >=60% |
| source-macro vs clip-micro 差距 | — | <10pp | — |

## 7. 注意事项

- 所有命令在项目根目录执行，用 conda python（非 uv）
- 验证集只用 fold_0_val，不得用 test/test_subvideo
- 每次实验记录：experiment_id, git_commit, dataset_hash, checkpoint_step, prompt_hash
- checkpoint 对比默认使用 `--prompt-mode production`；若使用 embedded prompt，必须在报告中单独标识，不得混表
- 输出统一放：finetune/results/diagnostics/
- 当前数据质量修复完成前，不得进入最终 test 或发布阶段
