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
| `test` | `data/05_splits/test.json` 中的 21 个源视频 | `test_inputs.json`、`test_ground_truth.json` | `--dataset test` |
| `test_subvideos` | 同一 `test.json` 生成的候选子视频 | `test_subvideos_meta.label_reviewed.json`、`test_subvideo_inputs.json`、`test_subvideo_ground_truth.json` | `--dataset test_subvideos` |

所有命令从仓库根目录执行。先生成 21 个测试源视频的评测清单：

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

## Prompt Engineering 与 Visual Evidence 实验

这两类实验只在训练电脑运行。当前开发电脑负责脚本、静态测试、结果同步后的人工审阅，不负责模型加载、GPU 推理或完整 sweep。实验使用 `pipeline/prompt_library.yaml` 中独立的 `experiments` 配置，不会改变正式训练 `system_prompt`。

### 训练电脑执行清单

1. 同步代码、Fold 0 merged 数据和视频产物。
2. 确认传入的是可由 Transformers 直接加载的基座或 merged 模型目录，并核对 checkpoint、adapter、merged metadata。
3. 在仓库根目录运行本节的单元测试。
4. 运行 Prompt Engineering 实验。
5. 运行 Visual Evidence pilot。
6. 打包两个完整结果目录并同步回当前开发电脑。
7. 在开发电脑按 `manual_review_queue.csv` 做两阶段审阅。

训练电脑的静态测试命令：

```bash
PYTHONPATH=. uv run pytest \
  tests/test_prompt_sweep.py \
  tests/test_validation_rebuild.py \
  -q
```

### Prompt Engineering

```bash
python -m finetune.validation.run_prompt_sweep prompt \
  --model-dir /path/to/current-merged-model
```

只有 `--model-dir` 必填。默认使用：

- `fold_0_val`；
- `light`、`medium_relaxed`、`medium` 三个变体；
- User Prompt seed `42`；
- 8 个采样帧；
- greedy decoding，`num_beams=1`；
- `max_new_tokens=256`；
- 自动创建 `finetune/results/prompt_sweep/prompt/<model-name>-<UTC timestamp>/`。

本轮实验 Prompt 版本为 `round_3_relaxed_decision_boundary`。`light` 只规定四字段 JSON；`medium_relaxed` 约束 JSON 类型和合法枚举，但移除 false/null 的字段联动，并要求先独立判断 `has_fracture`，局部字段不确定不能自动把画面中已观察到的断裂改判为未断裂；`medium` 保留上一轮完整的 `null` 联动规则作为对照。这样 light/medium_relaxed 用于观察最小结构约束效果，medium_relaxed/medium 用于判断字段联动是否造成保守化。`natural`、`strict` 及上一轮 Evidence 变体仍保留在 Prompt 库中供历史复现，但不再进入默认 sweep。正式训练 Prompt 及其顶层版本保持不变，实验版本会单独写入 `experiment_manifest.json`。

### Visual Evidence pilot

```bash
python -m finetune.validation.run_prompt_sweep evidence \
  --model-dir /path/to/current-merged-model
```

默认在 Fold 0 的 17 个当前有效源视频中各选择一个固定样本，配对比较：

- `medium_relaxed`：带字段类型和枚举约束、但不强制字段联动的四字段 JSON；
- `medium_relaxed_evidence`：沿用同一最终字段协议，先输出自由文本字符串 `visual_evidence`；
- 两个条件均使用 `max_new_tokens=512`；
- 自动创建 `finetune/results/prompt_sweep/evidence/<model-name>-<UTC timestamp>/`。

pilot manifest 由 source、目标标签和 `sha256("42:" + sample_id)` 确定，具体 sample ID 与 hash 会写入 `sample_manifest.json`。脚本还会导出模型实际收到的帧和 contact sheet，人工审阅不能用源视频代替这些输入帧。

### 可选调试参数

正式运行不需要传入以下参数；仅在调试时覆盖默认值：

- `--out-dir`：指定一个尚不存在的输出目录；
- `--dataset`：Prompt Engineering 调试时可切换到其他 fold validation；固定 evidence pilot 只支持 `fold_0_val`；
- `--max-samples`：至少为 2，且脚本仍会保证 dry run 包含正负样本；
- `--video-root`：媒体不在默认路径时使用；
- `--user-prompt-seed`：默认 `42`，正式基线不要随意修改。

变体、pilot manifest、最大帧数、generation config 和 token 上限由子命令固定，不作为常规 CLI 参数。旧 `--prompt user|system|test` 只作隐藏兼容入口并会发出弃用警告。

### 自动预检与停止条件

模型加载前，脚本会：

- 检查 split、merged 数据、源视频覆盖和媒体文件；
- 核对 Fold 0 split 与 `subvideos_meta.label_reviewed.json` 的选择结果；
- 固化 Prompt、数据和模型 manifest；
- 拒绝覆盖已有目录。

脚本会报告 Fold split 与 merged validation 的源视频覆盖差异，并把详情写入 `sample_manifest.json`。存在审核记录并不代表该源一定进入目标 fold；`selected_splits` 未包含目标 fold 的源只记录审计信息。只有 metadata 明确将源选入目标 fold、但 merged validation 仍缺失时，脚本才会在模型加载前停止，此时必须重新生成或重新同步一致的数据 artifact，不能绕过检查。

模型目录还必须包含可审计的来源文件。基座模型使用 `model_metadata.json`：

```json
{"model_kind":"base","base_model":"/path/to/base-model"}
```

LoRA 合并模型使用 `merge_metadata.json`，并写明实际来源：

```json
{
  "model_kind": "merged",
  "base_model": "/path/to/base-model",
  "adapter_path": "/path/to/checkpoint-or-adapter",
  "checkpoint_step": 1200
}
```

脚本会拒绝 adapter-only、只有配置没有权重、缺少来源 metadata、base model 与 `config.json` 冲突的目录；并对所有实际模型权重文件逐一记录大小和 SHA256。训练机器打包 merged 模型时应同时复制上述 metadata，不能事后凭目录名猜测 checkpoint。

模型加载后，脚本先对一个断裂和一个未断裂样本运行全部条件。dry run 为空或报错时不会启动完整 sweep。

### 输出目录与审阅

每次实验目录包含：

- `experiment_manifest.json`：实验、Prompt、生成配置和代码版本；
- `model_manifest.json`：实际模型路径、配置与关键文件 hash；
- `sample_manifest.json`：样本、源视频、标签和数据覆盖审计；
- `evaluation_records.jsonl`：逐样本原始输出、解析结果、token 数和采样时间戳；
- `prompt_sweep_summary.json`：条件级格式、标签分布和配对翻转；
- `source_level_summary.json`：按源视频汇总，不能把同源子视频视为独立样本；
- `manual_review_queue.csv`：隐藏条件和 ground truth 的第一阶段审阅表；
- `manual_review_key.json`：第二阶段解盲所需的条件、标签和解析结果；
- `runtime_failures.csv`：预检、dry run 或逐样本失败；
- `frames/`：模型实际收到的帧与 contact sheet；
- `run_command.txt`：实际执行命令。

人工审阅分两步：第一步只看实际输入帧和原始输出，检查格式、视觉依据、幻觉与自洽；第二步再用 `manual_review_key.json` 查看条件、ground truth 和最终四字段，检查标签合理性以及 evidence 是否支持结论。

JSON/schema 合法、输出理由流畅或 loss 下降都不能证明模型使用了视觉信息。Prompt 与 evidence 实验只能在 Fold 0 上迭代；正式 21 源 test 必须等 Prompt、模型、schema、ROI、采样和生成参数全部冻结后再运行。

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

- `--dataset`：`test`（21 个测试源视频）、`test_subvideos`（审核后测试子视频），也可选 `fold_0_val`、`fold_1_val`、`fold_2_val`。
- `--model-dir`：必填，除非改用 `--predictions`；可为基座模型、合并模型或 adapter 目录。
- `--out-dir`：必填，评测结果目录。
- `--video-root`：视频不在默认 `data/01_videos` 时指定。
- `--max-samples`：仅用于小规模冒烟测试。
- `--predictions`：已有预测 JSONL 时跳过 GPU 推理。

基座模型与微调模型、源视频与子视频的对比，只需分别替换 `--model-dir` 和 `--dataset` 后重复运行。建议在 `--out-dir` 中分别标明模型和数据集，避免覆盖。

核心评测脚本固定使用项目 prompt library 中的推理 prompt。Prompt 对照实验使用上文的 `run_prompt_sweep prompt|evidence` 子命令。

## 关联文档

- [仓库总览](../README.md)
- [数据处理与训练运行手册](../docs/DATA_PROCESSING_RUNBOOK.md)
- [视觉归因与 ROI 优化方向](../docs/VISUAL_GROUNDING_AND_ROI_OPTIMIZATION.md)

## 评估输出

每个输出目录包含：

- `evaluation_summary.json`：样本数、运行失败数与非空输出率。
- `evaluation_records.jsonl`：逐样本原始输出、错误和参考标签，是模型对比的主要依据。
- `runtime_failures.csv`：推理失败样本。

历史直接评估链路仍可复现含 `confidence` 的旧推理 prompt，但它不属于 TensileAgent 的生产视觉契约。生产调用固定使用 `pipeline/contracts/tensile_vlm_v1.json` 的四字段输出，confidence 由 Agent 依据多轮证据计算，不能从 MiniCPM 单轮输出复制。除比较运行失败率和非空输出率外，还应基于原始输出检查字段正确性、时间区间命中、联合成功率以及典型成功/失败样例。训练 loss 或 eval loss 的下降不能单独证明任务效果。

## TensileAgent 生产契约

权威 artifact 为 `pipeline/contracts/tensile_vlm_v1.json`，`pipeline/prompt_library.yaml` 的 `production` 区必须与其保持一致。生产主调用只使用一个固定 System/User Prompt，MiniCPM 输出严格四字段；需要视觉说明时，Agent 对同一 clip 和实际帧另行调用固定 Evidence Prompt，主调用标签不会传入 Evidence Prompt。

训练机器启动代理服务前执行：

```bash
python -m pipeline.production_contract
```

将输出的 `contract_version` 和 `prompt_contract_hash` 填入基于 `pipeline/server_deployment_manifest.example.json` 创建的部署 manifest。服务端 adapter 会拒绝错误 hash，TensileAgent 也会对响应中的部署 metadata 再次校验。修改 Prompt、generation 配置、最大帧数或字段协议后，不得沿用旧 hash。

本机已有同步的预测 JSONL 时，可跳过 GPU 推理：

```bash
python -m finetune.validation.run_evaluation \
  --dataset test_subvideos \
  --predictions finetune/results/direct_test_subvideos.jsonl \
  --out-dir finetune/results/eval_test_subvideos
```
