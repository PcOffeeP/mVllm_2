# 微调与评估

本目录包含 TensileAgent 的 MiniCPM-V LoRA 微调配置和直接输出评估脚本。LLaMA-Factory 位于仓库根目录的 `LlamaFactory/` 子模块。

训练、GPU 推理和完整评测请在训练电脑执行；本机只适合查看或复核已同步的预测结果。

## 开始前

数据、基座模型、环境和人工审核的完整准备流程以仓库根目录 [README.md](../README.md) 为准。本说明只列出微调与评估所需的核心命令。

安装训练依赖：

```bash
cd LlamaFactory
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt
```

## 训练 LoRA

从 `finetune/` 运行。必须使用 `train_with_contract.py`，它会为训练进程安装 MiniCPM 的 8 帧处理器约束。

```bash
cd finetune
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

# 选择一个 fold 训练
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml
```

将命令末尾的配置替换为 `fold1` 或 `fold2`，即可训练另外两个 fold。各配置中的 `output_dir` 是实际训练产物目录；请以 YAML 为准，不要手工猜测路径。

## 合并 LoRA

编辑 `MiniCPM/config/merge.yaml` 中的 `adapter_name_or_path` 和 `export_dir`，使其对应要合并的 fold，然后执行：

```bash
cd finetune
llamafactory-cli export MiniCPM/config/merge.yaml
```

合并后的目录可直接用于评估。训练输出中的 checkpoint 和 adapter 应保留在训练电脑；若需同步结果到仓库，建议只归档配置、指标、日志与曲线，不提交大型 checkpoint 或模型权重。

## 测评：基座模型与微调模型对比

正式测评需要比较两种模型：基座模型和微调/合并后的模型；每种模型都必须覆盖以下两类测试内容：

- `test`：22 个原始测试指示频。
- `test_subvideos`：由这 22 个视频生成、并完成审核后导出的全部测试子视频（审核标记为 `dropped` 的样本不进入正式测评）。

### 测试数据与训练数据是两条独立链路

两条链路都以 `data/05_splits/test.json` 或训练 fold 划分为边界，但不共用子视频 metadata，也不能互相替代：

| 用途 | 输入与生成范围 | 审核后产物 | 下游用途 |
| --- | --- | --- | --- |
| 训练 | 训练 fold 的视频生成候选子视频，记录在 `data/07_metadata/subvideos_meta.json` | `subvideos_meta.label_reviewed.json` | `training_sample_builder.py` 生成训练/验证 JSON |
| 原始视频测试 | 只读取 `data/05_splits/test.json` 中的 22 个视频 | `data/06_merged/test_inputs.json`、`test_ground_truth.json` | `--dataset test` |
| 测试子视频 | 首次生成时读取同一个 `test.json` 中的 22 个视频，生成候选子视频 | `test_subvideos_meta.label_reviewed.json`，以及 `test_subvideo_inputs.json`、`test_subvideo_ground_truth.json` | `--dataset test_subvideos` |

因此，测试视频不会被送入训练样本构建器；训练子视频也不会被 `test_subvideos` 测评读取。

### 先准备测试数据

以下命令均从仓库根目录执行。先生成 22 个原始测试视频的评测清单：

```bash
python scripts/generate_test_artifacts.py
```

首次生成并审核这 22 个测试视频的子视频（仅当 `data/07_metadata/test_subvideos_meta.json` 尚不存在时）：

```bash
# metadata 不存在时，此脚本在代码中固定读取 data/05_splits/test.json；不会遍历训练/验证视频。
# --no-strict 仅用于首次生成尚未审核的候选媒体与 metadata。
python scripts/generate_test_subvideo_artifacts.py --no-strict

# 在审核 UI 中逐条标记 approved、dropped 或 needs_regenerate
streamlit run pipeline/scripts/review_subvideos_app.py -- \
  --metadata data/07_metadata/test_subvideos_meta.json

# 将审核结论写回 metadata，并应用审核后的标签
python pipeline/scripts/apply_review_decisions.py \
  --metadata data/07_metadata/test_subvideos_meta.json \
  --decisions data/07_metadata/subvideo_test_review_decisions.json \
  --output data/07_metadata/test_subvideos_meta.reviewed.json \
  --strict
python pipeline/scripts/apply_label_corrections.py \
  --metadata data/07_metadata/test_subvideos_meta.reviewed.json \
  --output data/07_metadata/test_subvideos_meta.label_reviewed.json

# 严格模式下导出正式测试输入；未审核或 needs_regenerate 的样本会阻止导出
python scripts/generate_test_subvideo_artifacts.py \
  --metadata data/07_metadata/test_subvideos_meta.label_reviewed.json
```

若有 `needs_regenerate` 样本，不得执行正式导出，也不要使用 `--no-strict` 的输出作为正式评测集。当前脚本在已有 `test_subvideos_meta.json` 时只会复用该 metadata，不能按单个样本重新生成媒体；需要先补齐该脚本的重生成能力，再完成复审和严格导出。正式导出前还必须确认测试 metadata 的每个 `source_video` 都属于 `data/05_splits/test.json`；当前脚本读取已有 metadata 时不会执行这项校验。

### 核心测评命令

在训练电脑上对一个模型和一个数据集运行：

```bash
cd /path/to/mVllm_2
python -m finetune.validation.run_evaluation \
  --dataset test \
  --model-dir /path/to/model \
  --out-dir finetune/results/model_test
```

基座模型与微调模型的对比，只需分别替换 `--model-dir` 后重复此命令；原始视频与子视频的对比，只需把 `--dataset test` 改为 `--dataset test_subvideos`。建议在 `--out-dir` 中分别标明模型和数据集，避免覆盖结果。

可调整的参数：

- `--dataset`：`test`（22 个原始测试视频）、`test_subvideos`（审核后测试子视频）；也可选 `fold_0_val`、`fold_1_val`、`fold_2_val` 做 fold 验证。
- `--model-dir`：必填，除非改用 `--predictions`；可为基座模型、合并模型或可加载的 adapter 目录。
- `--out-dir`：必填，评测结果目录。
- `--video-root`：视频不在默认 `data/01_videos` 时指定根目录。
- `--max-samples`：仅用于小规模冒烟测试。
- `--predictions`：已有预测 JSONL 时跳过 GPU 推理并复核结果。

当前评测脚本没有 `--prompt` 参数：它固定使用项目 prompt library 中的推理 user prompt 与 system prompt。因此“更换模型”和“更换数据集”是命令行可选项；如需比较不同 prompt，必须先修改 prompt library 或扩展评测脚本，不能把不存在的 prompt 参数写进 README。

每个输出目录包含：

- `evaluation_summary.json`：样本数、运行失败数与非空输出率。
- `evaluation_records.jsonl`：逐样本原始输出、错误和参考标签，是比较模型表现的主要依据。
- `runtime_failures.csv`：推理失败样本。

评估固定使用含 `confidence` 的推理 prompt，当前脚本不自动判定 JSON/schema 正确性。因此除比较运行失败率和非空输出率外，还应基于逐样本原始输出检查字段正确性、时间区间命中、联合成功率以及典型成功/失败样例。训练 loss 或 eval loss 的下降不能单独证明任务效果。

本机已有训练电脑同步的预测 JSONL 时，可跳过 GPU 推理并复核单组结果：

```bash
python -m finetune.validation.run_evaluation \
  --dataset test_subvideos \
  --predictions finetune/results/direct_test_subvideos.jsonl \
  --out-dir finetune/results/eval_test_subvideos
```
