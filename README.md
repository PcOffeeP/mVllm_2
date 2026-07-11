# TensileAgent

> 材料拉伸试验视频断裂行为理解 —— 基于 MiniCPM-V-4.5 的视频微调、断裂区间定位与类型识别项目。

TensileAgent 面向材料拉伸试验视频，利用视觉语言模型理解试样在加载过程中的形貌变化，判断试样是否断裂，并进一步识别断裂发生的时间区间、断裂模式和断裂位置。

项目的核心不是对整段视频做一次简单分类，而是把视频转换为带有时间顺序的采样帧序列，建立“视觉证据—断裂区间—断裂属性”之间的对应关系。

## 项目目标

项目希望解决以下问题：

- 判断视频中是否发生试样断裂；
- 定位断裂发生在哪两个相邻采样帧之间；
- 区分韧性断裂、脆性断裂、界面脱粘等断裂模式；
- 判断断裂发生在标距内还是标距外；
- 识别未断裂、视频异常、未夹紧等特殊情况；
- 通过解释型监督，让模型依据可见的形貌变化进行判断，而不是只学习固定 JSON 格式。

训练阶段使用“判断依据 + 结构化结果”的监督格式；推理和评估阶段在结果中增加模型对当前判断的 `confidence` 字段。

## 方法概览

### Frame-Interval 建模

项目采用 frame-interval 作为时间定位的基本单位：

1. 将拉伸试验视频按照统一的视觉处理契约抽取为有序帧序列；
2. 使用相邻采样帧索引对 `[i, i+1]` 表示断裂发生的区间；
3. 将断裂前后不同时间窗口裁剪为多个子视频；
4. 根据子视频中的可见证据生成训练样本；
5. 使用 3-fold 视频级划分进行训练和验证。

这种方式比直接预测整段视频的单一标签更适合描述断裂发生的瞬间，也能使训练数据中的时间标注和模型实际看到的帧保持一致。

### 统一 Prompt 与解释型监督

训练和推理使用同一套 prompt 模板库：

- 同一任务提供多种等价问法；
- 覆盖断裂判断、断裂区间、断裂模式、断裂位置和异常情况；
- 训练 target 不包含 `confidence`；
- 推理 target 要求模型根据视觉证据给出 `confidence`；
- 训练和评估记录 prompt 模板版本，便于复现实验。

Prompt 模板位于：

```text
pipeline/prompt_library.yaml
```

## 项目结构

```text
pipeline/
├── scripts/                  数据生成、审核、导出和质量检查
├── preprocessing/            视频帧处理与 MiniCPM processor 适配
├── prompt_library.yaml       训练/推理共用的 prompt 模板库
├── server_proxy.py           同进程推理服务
└── llamafactory_contract.py  帧数和处理器契约

finetune/
├── train_with_contract.py    微调训练入口
├── MiniCPM/config/           训练与模型导出配置
├── validation/               推理、评估和 prompt 测试
└── dataset_info.json         LLaMA-Factory 数据集注册信息

data/
├── 01_videos/                原始视频
├── 02_annotations/           原始标注
├── 03_subvideos/             生成的子视频
├── 04_frames/                子视频采样帧
├── 05_splits/                训练/验证/测试划分
├── 06_merged/                训练和评估输入
└── 07_metadata/              视频、子视频和数据版本元数据

scripts/                      独立校验与测试评估输入生成工具
tests/                        项目测试
docs/                         项目计划和实现文档
LlamaFactory/                 LLaMA-Factory 子模块
models/                       本地模型权重目录
```

视频、模型权重以及部分中间数据产物通常不纳入版本控制，需要在实验环境中准备或同步。

## 数据流程

从原始标注到训练和评估，整体流程如下：

> 从“只有原视频与 CSV 标注”开始执行、包含全量人工审查、增量复审、安全合并与最终训练数据导出的权威步骤，请阅读 [数据处理与训练运行手册](docs/DATA_PROCESSING_RUNBOOK.md)。本节只保留流程概览。

```text
原始视频与标注
      │
      ▼
元数据整理与 3-fold 划分
      │
      ▼
训练级子视频与采样帧生成
      │
      ├── 训练级子视频人工审核
      │
      └── 测试级子视频生成与人工审核
      │
      ▼
审核决策应用与标签修正
      │
      ▼
训练样本 / 测试输入 / ground truth
      │
      ▼
帧区间、标签、路径、版本和数据泄漏检查
      │
      ▼
模型训练、合并与 raw-output 评估
```

### 子视频与帧映射

每个子视频 metadata 会记录：

- 源视频和子视频路径；
- 起止时间、帧号和时长；
- `crop_type` 与窗口选择原因；
- 断裂标签、断裂区间、类型和位置；
- processor 指纹；
- 实际采样帧及其源视频/子视频坐标映射。

子视频生成、帧抽取和训练读取必须遵守同一套处理契约，避免训练时重新抽帧后导致标注区间偏移。

### 人工审核

训练级和测试级子视频使用同一套本地审核 UI。审核人员可以查看视频、采样帧和窗口信息，并对标签进行确认或修改。

审核结果包含三类状态：

- `approved`：进入后续训练或评估；
- `dropped`：保留媒体文件和记录，但从数据集合中剔除；
- `needs_regenerate`：标记为需要重新生成，并阻止正式导出。

审核决策文件分别用于训练级和测试级子视频，之后由导出脚本生成审核后的 metadata 和数据集。

## 环境准备

项目推荐使用 Python 3.11、Conda 和 pip。训练和完整视频处理通常在 Linux/GPU 环境执行。

```bash
git submodule update --init --recursive

conda create -n mVllm2 python=3.11 pip -y
conda activate mVllm2

pip install -r requirements.txt
pip install -e ./LlamaFactory
```

将 MiniCPM-V-4.5 基座模型放入 `models/`，或在运行脚本时通过参数指定模型目录。子视频生成还需要 `ffmpeg` 和 `ffprobe`。

## 使用流程

以下命令均从仓库根目录执行。

完整执行时请以 [数据处理与训练运行手册](docs/DATA_PROCESSING_RUNBOOK.md) 为准；它明确了何时冻结划分、何时只做增量复审，以及哪些步骤必须在训练电脑运行。

### 生成数据

```bash
python3 pipeline/scripts/dataset_manager.py

python3 pipeline/scripts/subvideo_builder.py \
  --model models/minicpmv4_5 \
  --sample-size 10 \
  --sample-output-dir data/sample_subvideos
```

小样本确认无误后，再执行完整子视频生成：

```bash
python3 pipeline/scripts/subvideo_builder.py --model models/minicpmv4_5
```

### 启动审核 UI

训练级子视频：

```bash
streamlit run pipeline/scripts/review_subvideos_app.py -- \
  --metadata data/07_metadata/subvideos_meta.json
```

测试级子视频使用测试 metadata 运行同一脚本。

### 导出训练数据并检查

审核完成后，依次应用审核决策、生成训练样本并执行质量检查：

```bash
python3 pipeline/scripts/apply_review_decisions.py
python3 pipeline/scripts/apply_label_corrections.py
python3 pipeline/scripts/training_sample_builder.py

python3 scripts/validate_no_oob.py
python3 pipeline/scripts/quality_check.py
python3 pipeline/scripts/freeze_data_version.py
```

各脚本支持通过 `--help` 查看输入、输出和路径参数。

## 模型训练

训练入口：

```bash
cd finetune
python3 train_with_contract.py \
  MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml
```

项目采用 LoRA 微调和 3-fold 视频级划分。不同 fold 使用各自的 YAML 配置，训练参数以配置文件为准。训练完成后，可使用 LLaMA-Factory 的 export 配置将 LoRA adapter 合并为可直接推理的模型。

## 模型评估

评估阶段主要保存模型原始返回，先保证输出协议和实验信息可追溯，再根据需要扩展自动指标。

评估结果包括：

- `evaluation_records.jsonl`：逐样本 raw output、运行错误和参考信息；
- `evaluation_summary.json`：数据集、模型路径、prompt 版本和 generation 配置；
- `runtime_failures.csv`：推理失败记录。

在训练机上运行模型评估：

```bash
python3 -m finetune.validation.run_evaluation \
  --dataset test \
  --model-dir /path/to/merged_model \
  --out-dir finetune/results/eval_test
```

如果已有模型预测 JSONL，也可以在本地只复核评估输出：

```bash
python3 -m finetune.validation.run_evaluation \
  --dataset test \
  --predictions /path/to/predictions.jsonl \
  --out-dir finetune/results/eval_test
```

评估数据包括两类：

1. 原测试视频；
2. 经过人工审核的测试级子视频。

当前阶段重点检查 raw output 是否非空、是否包含结果区、prompt 版本是否一致。字段准确率、断裂区间命中率、断裂类型和位置指标可在数据和模型结果稳定后继续扩展。

## 推理服务

项目提供同进程推理服务，将视频预处理、模型推理和结果返回封装在一起：

```bash
python3 -m pipeline.server_proxy \
  --model /path/to/merged_model \
  --deployment-manifest /path/to/deployment_manifest.json
```

部署清单用于记录 processor 版本、最大帧数等运行契约。

## 测试

运行项目核心测试：

```bash
python3 -m pytest -q \
  tests/test_apply_review_decisions.py \
  tests/test_generate_test_subvideo_artifacts.py \
  tests/test_quality_check.py \
  tests/test_validation_rebuild.py \
  tests/test_review_subvideos_app_helpers.py
```

LLaMA-Factory 自带测试需要额外的深度学习和 API 依赖，和项目本身的轻量数据流水线测试分开运行。

## 相关文档

- [数据处理与训练运行手册](docs/DATA_PROCESSING_RUNBOOK.md)（从原视频和 CSV 到最终训练数据的权威流程）
- [微调数据、人工审核和评估重设计计划](docs/plans/2026-07-09-finetune-data-review-and-eval-redesign.md)
- [训练数据审核流水线实现说明](docs/IMPLEMENTATIONS/2026-06-30-training-data-review-pipeline.md)
- [训练说明](finetune/README.md)
- [Prompt 模板库](pipeline/prompt_library.yaml)

## 运行边界

- 数据生成、训练和完整推理依赖模型权重、视频媒体和相应运行环境；
- 训练与 GPU 推理应在远程 Linux/4090 机器执行；
- 本机可以进行代码检查、轻量测试和已有预测结果复核；
- 评估结论应同时参考结构化指标、模型原始输出以及典型成功/失败样例，不能只依据 train loss 或 eval loss。
