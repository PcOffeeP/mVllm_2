# TensileAgent

> 基于 MiniCPM-V-4.5 对材料拉伸试验视频进行断裂理解：判断是否断裂、定位断裂区间、识别断裂模式与位置。

## 项目目标

- 判断视频中是否发生试样断裂。
- 定位断裂发生在哪两个相邻采样帧之间。
- 区分韧性断裂、脆性断裂、界面脱粘等断裂模式。
- 判断断裂发生在标距内还是标距外。
- 识别未断裂、视频异常、未夹紧等特殊情况。
- 输出严格的四字段 JSON，便于训练和评估解析。

训练、推理和评估统一使用四字段 JSON；`confidence` 不由 MiniCPM 单轮输出。

## 项目结构

```text
pipeline/
├── scripts/                  数据生成、审核、导出、质量检查
├── preprocessing/            视频帧处理与 MiniCPM processor 适配
├── prompt_library.yaml       唯一 System/User Prompt 配置
├── server_proxy.py           同进程推理服务
└── llamafactory_contract.py  帧数和处理器契约

finetune/
├── train_with_contract.py    微调训练入口
├── MiniCPM/config/           训练与模型导出配置
├── validation/               推理与评估
└── dataset_info.json         LLaMA-Factory 数据集注册信息

data/
├── 01_videos/                源视频
├── 02_annotations/           原始标注
├── 03_subvideos/             生成的子视频
├── 04_frames/                子视频采样帧
├── 05_splits/                训练/验证/测试划分
├── 06_merged/                待发布的训练/评估构建结果（中间工作区）
├── 07_metadata/              审核、质量检查和版本冻结元数据（过程证据）
└── 08_training_ready/        通过质量门的版本化训练交付物（训练唯一入口）

scripts/                      独立校验与测试评估输入生成工具
tests/                        项目测试
docs/                         项目计划和实现文档
LlamaFactory/                 LLaMA-Factory 子模块
models/                       本地模型权重目录
```

视频、模型权重和中间数据通常不纳入版本控制，需在实验环境中准备或同步。

## 环境准备

推荐 Python 3.11、Conda、Linux/GPU 环境。

```bash
git submodule update --init --recursive

conda create -n mVllm2 python=3.11 pip -y
conda activate mVllm2

pip install -r requirements.txt
pip install -e ./LlamaFactory
```

将 MiniCPM-V-4.5 基座模型放入 `models/`，或在脚本中通过 `--model` 指定。子视频生成需要 `ffmpeg` 和 `ffprobe`。

## 快速开始

所有命令从仓库根目录执行。完整数据流程以 [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md) 为准。

### 1. 生成数据

> 详细的子视频生成与数据流程见 [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md)。

小样本验证：

```bash
python pipeline/scripts/subvideo_builder.py \
  --model models/minicpmv4_5 \
  --sample-size 10 \
  --sample-output-dir data/sample_subvideos
```

确认无误后完整生成：

```bash
python pipeline/scripts/subvideo_builder.py --model models/minicpmv4_5
```

### 2. 审核子视频

> 详细的人工审核与增量复审流程见 [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md)。

训练级子视频：

```bash
streamlit run pipeline/scripts/review_subvideos_app.py -- \
  --metadata data/07_metadata/subvideos_meta.json
```

测试级子视频使用对应 metadata 运行同一脚本。

实验性的源视频固定 ROI 标注工具：

```bash
streamlit run pipeline/scripts/roi_annotation_app.py -- \
  --metadata data/07_metadata/video_meta.json \
  --output data/07_metadata/roi_decisions.json
```

该工具只保存 ROI / 不裁剪决定，不生成训练视频，也不修改当前激活的数据发布版本。
全部 110 条决定完成后，使用
`uv run python pipeline/scripts/freeze_roi_decisions.py --check-only` 校验，再去掉
`--check-only` 冻结为不可覆盖的 ROI manifest。

### 3. 导出训练数据

> 详细的训练数据导出、质量检查与版本冻结步骤见 [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md)。

首次审核完成或增量复审安全合并后，依次执行：

```bash
# 将人工审核决定合并到子视频元数据
python pipeline/scripts/apply_review_decisions.py \
  --metadata data/07_metadata/subvideos_meta.json \
  --decisions data/07_metadata/subvideo_train_review_decisions_final.json \
  --output data/07_metadata/subvideos_meta.reviewed.json \
  --strict

# 应用人工复核后的标签修正
python pipeline/scripts/apply_label_corrections.py \
  --metadata data/07_metadata/subvideos_meta.reviewed.json \
  --output data/07_metadata/subvideos_meta.label_reviewed.json

# 在人工审核基线上缩减脆性断裂 neg_before 样本
python pipeline/scripts/filter_reviewed_neg_before.py \
  --output-report data/07_metadata/filter_neg_before_dropped_report.json

# 根据元数据和划分构建训练样本
python pipeline/scripts/training_sample_builder.py \
  --subvideos-meta data/07_metadata/subvideos_meta.filtered_neg_before.label_reviewed.json \
  --video-meta data/07_metadata/video_meta.json \
  --splits-dir data/05_splits \
  --output-dir data/06_merged

# 检查帧索引是否超出子视频边界
python scripts/validate_no_oob.py \
  --subvideos-meta data/07_metadata/subvideos_meta.filtered_neg_before.label_reviewed.json

# 对训练样本执行质量检查
python pipeline/scripts/quality_check.py \
  --subvideos-meta data/07_metadata/subvideos_meta.filtered_neg_before.label_reviewed.json \
  --merged-dir data/06_merged

# 锁定当前数据版本并生成快照
python pipeline/scripts/freeze_data_version.py \
  --merged-dir data/06_merged \
  --subvideos-meta data/07_metadata/subvideos_meta.filtered_neg_before.label_reviewed.json \
  --video-meta data/07_metadata/video_meta.json \
  --splits-dir data/05_splits \
  --subvideo-dir data/03_subvideos \
  --lock data/07_metadata/data_version_lock.json

# 发布并切换到不可覆盖的训练版本
python pipeline/scripts/publish_training_release.py --activate
```

`03`–`07` 都属于数据处理工作区。只有
`data/08_training_ready/<release_id>/` 中状态为 `training_ready` 的版本可供正式训练；
当前版本记录在 `finetune/active_data_release.json`。

特别注意：前面的构建、校验和冻结命令不会自动写入 `08_training_ready`。每一轮数据处理
都必须显式执行最后的发布命令；只有带 `--activate` 发布成功后，训练和评估才会切换到
新版本。旧发布版本不会被覆盖，`scripts/clear_data_outputs.py` 也不会删除它们。若只需
重新激活一个已经存在的版本：

```bash
python pipeline/scripts/publish_training_release.py \
  --activate-existing <release_id>
```

各脚本支持 `--help` 查看参数。完整的下一轮运行顺序、重复版本处理和失败恢复规则见
[数据处理运行手册](docs/DATA_PROCESSING_RUNBOOK.md)。

### 4. 训练模型

> 详细的训练、合并与评估命令见 [finetune/README.md](finetune/README.md)。

```bash
cd finetune
python train_with_contract.py \
  MiniCPM/config/train_fold0.yaml
```

项目采用 LoRA 微调和 3-fold 视频级划分。训练配置使用稳定的用途命名，实验版本和
运行批次由 YAML 内的发布标识及 `output_dir` 固定。不得复用旧实验的输出目录；各
fold 参数和产物路径以对应 YAML 为准。

### 5. 评估模型

> 详细的评估命令与数据集说明见 [finetune/README.md](finetune/README.md)。

在训练机上运行：

```bash
python -m finetune.validation.run_evaluation \
  --dataset test \
  --model-dir /path/to/merged_model \
  --out-dir finetune/results/eval_test
```

已有预测 JSONL 时，可本地复核：

```bash
python -m finetune.validation.run_evaluation \
  --dataset test \
  --predictions /path/to/predictions.jsonl \
  --out-dir finetune/results/eval_test
```

## 推理服务

生产服务固定使用 `pipeline/contracts/tensile_vlm_v2.json`。其中 analysis Prompt
是全量模型训练 Prompt 的版本化快照；服务启动和请求处理均不再动态读取 YAML。
查看当前固定契约身份：

```bash
python -m pipeline.production_contract
```

从 `pipeline/server_deployment_manifest.example.json` 复制启动配置并替换全部
`REPLACE_*`。启动配置只写模型、adapter、processor、框架和运行环境；服务会从
已验证的 artifact 注入 `contract_version` 与 `contract_hash`。TensileAgent 会先调用
`GET /v1/tensile/contract` 固定部署快照，并逐轮检查漂移。

```bash
python -m pipeline.server_proxy \
  --model /path/to/merged_model \
  --deployment-manifest /path/to/deployment_manifest.json
```

分析和视觉证据都通过 `POST /v1/chat/completions`。服务只接受 artifact 中的固定
Prompt；analysis 非法输出由服务端最多重试两次，Agent 客户端不追加动态纠错文本。

全量模型在训练机上的前台/后台启动、预检、真实视频冒烟、TensileAgent 接入、停止和
故障排查见 [全量模型推理服务运行手册](docs/INFERENCE_SERVICE_RUNBOOK.md)。

## 测试

```bash
python -m pytest -q \
  tests/test_apply_review_decisions.py \
  tests/test_generate_test_subvideo_artifacts.py \
  tests/test_quality_check.py \
  tests/test_validation_rebuild.py \
  tests/test_review_subvideos_app_helpers.py
```

LLaMA-Factory 自带测试需要额外深度学习依赖，与项目数据流水线测试分开运行。

## 相关文档

- [Agent 工作说明](AGENTS.md)
- [数据处理与训练运行手册](docs/DATA_PROCESSING_RUNBOOK.md)
- [微调说明](finetune/README.md)
- [最终 Prompt 策略](docs/FINAL_PROMPT_POLICY.md)
- [唯一 Prompt 配置](pipeline/prompt_library.yaml)
- [人工审核后的再生成与复标规则](docs/REVIEW_REGENERATION_RULES.md)
- [视觉归因与 ROI 优化方向](docs/VISUAL_GROUNDING_AND_ROI_OPTIMIZATION.md)
- [材料拉伸断裂行为分类指南](assets/frac_mode.md)
- [旧基线问题池](assets/question_pool.md)

## 运行边界

- 数据生成、训练和完整推理依赖模型权重、视频媒体和运行环境。
- 训练与 GPU 推理应在远程 Linux/GPU 机器执行。
- 本机可进行代码检查、轻量测试和已有预测结果复核。
- 评估应同时参考结构化指标、原始输出和典型成功/失败样例，不能只看 train loss 或 eval loss。
