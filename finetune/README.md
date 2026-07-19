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
`dataset_info.json` 只指向 `data/08_training_ready/` 中当前激活的发布版本；
版本身份见 `active_data_release.json`。这两个文件由
`publish_training_release.py --activate` 同步维护，不要手工把
`data/06_merged/` 配置为训练入口。

训练前从仓库根目录确认当前版本：

```bash
cat finetune/active_data_release.json
python -m json.tool \
  data/08_training_ready/<release_id>/manifest/release_manifest.json
```

必须确认 manifest 的 `status` 为 `training_ready`、`quality.error_count` 为 `0`，并且
`dataset_info.json` 中六个数据集指向同一个 `release_id`。若当前版本不正确，使用
`python pipeline/scripts/publish_training_release.py --activate-existing <release_id>`
切换，不要修改发布目录中的文件。

```bash
cd finetune
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

python train_with_contract.py \
  MiniCPM/config/train_fold0.yaml
```

替换为 `train_fold1.yaml` 或 `train_fold2.yaml` 训练另外两个 fold。配置中的数据发布
版本和 `output_dir` 必须对应实际运行批次，不能沿用旧实验路径。训练入口默认拒绝
覆盖已有目录。

## 合并 LoRA

使用与训练 fold 对应的固定 merge 配置：

```bash
cd finetune
llamafactory-cli export MiniCPM/config/merge_fold0.yaml
```

替换为 `fold1` 或 `fold2` 合并另外两个 fold。合并后的目录可直接用于评估。训练输出
中的 checkpoint 和 adapter 应保留在训练电脑；若同步结果到仓库，建议只归档配置、
指标、日志与曲线，不提交大型 checkpoint 或模型权重。

## 全量训练

三折交叉验证完成后，将三个 fold 的 train 和 validation 六份文件合并，并按 `videos`
去重。测试源视频和测试子视频不进入全量训练数据。数据由固定发布版本确定性生成到
`finetune/generated/full_training/`。生成后的 dataset、registry 和 provenance 应作为
独立的数据提交归档，不与交叉验证结果或训练代码混在同一个提交。

从仓库根目录执行：

```bash
python finetune/prepare_full_training_dataset.py \
  --release-dir data/08_training_ready/v2.0.0-1dab1e5e \
  --output-dir finetune/generated/full_training/v2_0_0_1dab1e5e_20260719

python finetune/run_full_training_pipeline.py --validate-only
python finetune/run_full_training_pipeline.py
```

`--validate-only` 必须确认三折交叉验证汇总、全量数据 provenance/hash、训练配置和输出
目录均有效。正式流水线会依次使用 `MiniCPM/config/train_full.yaml` 训练、使用
`MiniCPM/config/merge_full.yaml` 合并，并在隔离的 `test` 与 `test_subvideos` 上做最终
评测。若目标训练目录、merged 目录或评测目录存在但产物不完整，流水线会拒绝覆盖。

## 准备测试数据

测试数据有两条独立链路，都以 `data/05_splits/test.json` 为边界，但不共用子视频 metadata：

| 数据集 | 输入 | 产物 | 用途 |
| --- | --- | --- | --- |
| `test` | `data/05_splits/test.json` 中的 21 个源视频 | 发布版本中的 `datasets/evaluation/source_videos/` | `--dataset test` |
| `test_subvideos` | 同一 `test.json` 生成的候选子视频 | 发布版本中的 `datasets/evaluation/subvideos/` | `--dataset test_subvideos` |

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

若有 `needs_regenerate` 样本，不得执行正式导出，也不要使用 `--no-strict` 的输出作为正式评测集。正式导出前确认测试 metadata 的每个 `source_video` 都属于 `data/05_splits/test.json`。完成质量检查与版本冻结后，必须通过
`python pipeline/scripts/publish_training_release.py --activate` 发布，评估代码不会直接读取
`data/06_merged/`。

## 最终 Prompt 策略

Prompt Engineering 阶段已经结束。训练和核心评测只使用
`pipeline/prompt_library.yaml` 顶部的一个 `system_prompt` 和一个
`user_prompt`。生产 artifact 会逐字保存这两个 Prompt 作为 analysis 快照。这两个
Prompt 与当前 merged 模型的训练分布一致；后续修改只允许
编辑这两个字段，不再维护 Prompt Sweep、Evidence Pilot、测试 Prompt 或生产
Prompt 副本。

模型原始输出必须经过 `pipeline/output_normalizer.py`。Prompt 负责视觉判断，
Normalizer 负责字符串布尔、非法区间、非法类型和字段联动修复。最终选择依据和历史
实验摘要见 [最终 Prompt 策略](../docs/FINAL_PROMPT_POLICY.md)。

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

核心评测脚本固定使用项目 Prompt 库中的唯一 System/User Prompt。

## 关联文档

- [仓库总览](../README.md)
- [数据处理与训练运行手册](../docs/DATA_PROCESSING_RUNBOOK.md)
- [视觉归因与 ROI 优化方向](../docs/VISUAL_GROUNDING_AND_ROI_OPTIMIZATION.md)

## 评估输出

每个输出目录包含：

- `evaluation_summary.json`：样本数、运行失败数、原始 JSON 合法率、规范化合法率、修复率及任务指标。
- `evaluation_records.jsonl`：逐样本原始输出、规范化输出、自动修复记录、错误和参考标签，是模型对比的主要依据。
- `runtime_failures.csv`：推理失败样本。

生产调用固定使用四字段输出；confidence 由 Agent 依据多轮证据计算，不能从
MiniCPM 单轮输出复制。除比较运行失败率和非空输出率外，还应基于归一化输出检查
字段正确性、时间区间命中、联合成功率以及典型成功/失败样例。训练 loss 或
eval loss 的下降不能单独证明任务效果。

## TensileAgent 生产契约

训练与核心评测 Prompt 的唯一编辑入口是 `pipeline/prompt_library.yaml`。生产服务
只加载自包含的 `pipeline/contracts/tensile_vlm_v2.json`；其中 analysis Prompt
必须与当前 YAML 逐字一致，同时固定四字段 schema、异常语义、evidence Prompt、
生成参数和视频帧数。

训练机器启动代理服务前执行：

```bash
python -m pipeline.production_contract
```

基于 `pipeline/server_deployment_manifest.example.json` 创建启动配置，只填写模型、
adapter、processor、框架和 runtime 身份，不得自行填写 contract 字段。服务会注入
固定 `contract_version`/`contract_hash`；TensileAgent 会在预检和每轮响应中校验。
修改 Prompt、generation、最大帧数或字段协议后必须发布新的 canonical artifact/hash。

本机已有同步的预测 JSONL 时，可跳过 GPU 推理：

```bash
python -m finetune.validation.run_evaluation \
  --dataset test_subvideos \
  --predictions finetune/results/direct_test_subvideos.jsonl \
  --out-dir finetune/results/eval_test_subvideos
```
