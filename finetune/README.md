# 微调与评估

本目录包含 MiniCPM-V LoRA 微调配置和直接输出评估脚本。LLaMA-Factory 位于仓库根目录的 `LlamaFactory/` 子模块。评估准则与视觉验证方向见 [docs/VISUAL_GROUNDING_AND_ROI_OPTIMIZATION.md](../docs/VISUAL_GROUNDING_AND_ROI_OPTIMIZATION.md)。

训练、GPU 推理和完整评测在训练电脑执行；本机只查看或复核已同步的预测结果。

## 环境准备

数据、基座模型、环境和人工审核流程见仓库根目录 [README.md](../README.md)。微调额外依赖：

```bash
cd LlamaFactory
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt
```

## 训练 LoRA

从 `finetune/` 运行。必须使用 `train_with_contract.py`，它会安装 MiniCPM 的 8 帧处理器约束。

```bash
cd finetune
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

python train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml
```

替换为 `fold1` 或 `fold2` 训练另外两个 fold。各配置中的 `output_dir` 是实际训练产物目录，以 YAML 为准。

## 合并 LoRA

编辑 `MiniCPM/config/merge.yaml` 中的 `adapter_name_or_path` 和 `export_dir`，使其对应要合并的 fold，然后执行：

```bash
cd finetune
llamafactory-cli export MiniCPM/config/merge.yaml
```

合并后的目录可直接用于评估。训练输出中的 checkpoint 和 adapter 应保留在训练电脑；若同步结果到仓库，建议只归档配置、指标、日志与曲线，不提交大型 checkpoint 或模型权重。

## 准备测试数据

测试数据有两条独立链路，都以 `data/05_splits/test.json` 为边界，但不共用子视频 metadata：

| 数据集 | 输入 | 产物 | 用途 |
| --- | --- | --- | --- |
| `test` | `data/05_splits/test.json` 中的 22 个源视频 | `test_inputs.json`、`test_ground_truth.json` | `--dataset test` |
| `test_subvideos` | 同一 `test.json` 生成的候选子视频 | `test_subvideos_meta.label_reviewed.json`、`test_subvideo_inputs.json`、`test_subvideo_ground_truth.json` | `--dataset test_subvideos` |

所有命令从仓库根目录执行。先生成 22 个测试源视频的评测清单：

```bash
python scripts/generate_test_artifacts.py
```

首次生成并审核测试子视频（仅当 `data/07_metadata/test_subvideos_meta.json` 不存在时）：

```bash
# --no-strict 仅用于首次生成尚未审核的候选媒体与 metadata
python scripts/generate_test_subvideo_artifacts.py --no-strict

# 在审核 UI 中标记 approved / dropped / needs_regenerate
streamlit run pipeline/scripts/review_subvideos_app.py -- \
  --metadata data/07_metadata/test_subvideos_meta.json

# 应用审核结论
python pipeline/scripts/apply_review_decisions.py \
  --metadata data/07_metadata/test_subvideos_meta.json \
  --decisions data/07_metadata/subvideo_test_review_decisions.json \
  --output data/07_metadata/test_subvideos_meta.reviewed.json \
  --strict

python pipeline/scripts/apply_label_corrections.py \
  --metadata data/07_metadata/test_subvideos_meta.reviewed.json \
  --output data/07_metadata/test_subvideos_meta.label_reviewed.json

# 严格模式下导出正式测试输入
python scripts/generate_test_subvideo_artifacts.py \
  --metadata data/07_metadata/test_subvideos_meta.label_reviewed.json
```

若有 `needs_regenerate` 样本，不得执行正式导出，也不要使用 `--no-strict` 的输出作为正式评测集。正式导出前确认测试 metadata 的每个 `source_video` 都属于 `data/05_splits/test.json`。

## 核心评估命令

在训练电脑上对一个模型和一个数据集运行：

```bash
cd /path/to/mVllm_2
python -m finetune.validation.run_evaluation \
  --dataset test \
  --model-dir /path/to/model \
  --out-dir finetune/results/eval_test
```

参数说明：

- `--dataset`：`test`（22 个测试源视频）、`test_subvideos`（审核后测试子视频），也可选 `fold_0_val`、`fold_1_val`、`fold_2_val`。
- `--model-dir`：必填，除非改用 `--predictions`；可为基座模型、合并模型或 adapter 目录。
- `--out-dir`：必填，评测结果目录。
- `--video-root`：视频不在默认 `data/01_videos` 时指定。
- `--max-samples`：仅用于小规模冒烟测试。
- `--predictions`：已有预测 JSONL 时跳过 GPU 推理。

基座模型与微调模型、源视频与子视频的对比，只需分别替换 `--model-dir` 和 `--dataset` 后重复运行。建议在 `--out-dir` 中分别标明模型和数据集，避免覆盖。

当前评测脚本没有 `--prompt` 参数，固定使用项目 prompt library 中的推理 prompt。如需比较不同 prompt，先修改 prompt library 或扩展评测脚本。

## 关联文档

- [仓库总览](../README.md)
- [数据处理与训练运行手册](../docs/DATA_PROCESSING_RUNBOOK.md)
- [视觉归因与 ROI 优化方向](../docs/VISUAL_GROUNDING_AND_ROI_OPTIMIZATION.md)

## 评估输出

每个输出目录包含：

- `evaluation_summary.json`：样本数、运行失败数与非空输出率。
- `evaluation_records.jsonl`：逐样本原始输出、错误和参考标签，是模型对比的主要依据。
- `runtime_failures.csv`：推理失败样本。

评估固定使用含 `confidence` 的推理 prompt，当前脚本不自动判定 JSON/schema 正确性。因此除比较运行失败率和非空输出率外，还应基于原始输出检查字段正确性、时间区间命中、联合成功率以及典型成功/失败样例。训练 loss 或 eval loss 的下降不能单独证明任务效果。

本机已有同步的预测 JSONL 时，可跳过 GPU 推理：

```bash
python -m finetune.validation.run_evaluation \
  --dataset test_subvideos \
  --predictions finetune/results/direct_test_subvideos.jsonl \
  --out-dir finetune/results/eval_test_subvideos
```
