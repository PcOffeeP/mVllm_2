# 微调配置目录

本目录仅存放 TensileAgent 项目专属的 LLaMA-Factory 微调配置与验证脚本。
LLaMA-Factory 框架本身已迁移为仓库根目录的 Git submodule：`LlamaFactory/`。

## 目录结构

```text
finetune/
├── dataset_info.json          # 项目数据集注册表
├── README.md                  # 本说明
├── MiniCPM/config/            # models/minicpm-v-4.5 3-fold LoRA SFT YAML 配置
│   ├── minicpmv4_5_lora_sft_interval_fold0.yaml
│   ├── minicpmv4_5_lora_sft_interval_fold1.yaml
│   ├── minicpmv4_5_lora_sft_interval_fold2.yaml
│   └── merge.yaml
└── validation/                # 推理与评测脚本
    ├── run_inference.py
    ├── evaluate_joint.py
    ├── evaluate_time.py
    ├── evaluate_type.py
    ├── prepare_ground_truth.py
    ├── plot_type_confusion_matrix.py
    ├── common.py
    └── config.py
```

## 前置条件

1. 下载基座模型到 `models/minicpm-v-4.5/`（见仓库根目录 `README.md`）。
2. 按根目录 `README.md` 准备训练数据：先完成人工媒体审核、`prune_reviewed_subvideos.py` 清洗和 `review_subvideo_labels.py` 标签复检，再由 `subvideos_meta.label_reviewed.json` 生成 `data/06_merged/` 下的 JSON。
3. `finetune/dataset_info.json` 已注册 `tensile_video_3k*` / `tensile_video_interval_*` 数据集。

## 安装 LLaMA-Factory

```bash
cd LlamaFactory/
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt
```

## 启动训练

所有 YAML 中的相对路径均基于 `finetune/` 解析，因此训练与合并命令需在 `finetune/` 下执行：

```bash
cd finetune/
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

# Fold 0
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold0.yaml

# Fold 1
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold1.yaml

# Fold 2
python3 train_with_contract.py MiniCPM/config/minicpmv4_5_lora_sft_interval_fold2.yaml
```

训练输出目录为 `LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k{0,1,2}`。必须通过 `train_with_contract.py` 启动，以便实际子处理器的 8 帧约束在每个训练进程中生效。

训练前应确认根目录数据链路已经通过：

```bash
python3 scripts/validate_no_oob.py
python3 pipeline/scripts/quality_check.py \
  --subvideos-meta data/07_metadata/subvideos_meta.label_reviewed.json
```

`training_sample_builder.py`、`quality_check.py`、`validate_no_oob.py` 和 `freeze_data_version.py` 当前默认都使用 `data/07_metadata/subvideos_meta.label_reviewed.json`。不要用未经过人工审核和标签复检的 `subvideos_meta.json` 生成正式训练 JSON。

## 合并 LoRA

```bash
cd finetune/
llamafactory-cli export MiniCPM/config/merge.yaml
```

合并后的完整模型输出到 `LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0_merged/`（默认对应 fold0，切换 fold 时请修改 `merge.yaml` 中的 `adapter_name_or_path` 与 `export_dir`）。

## 归档训练结果

训练输出位于 `LlamaFactory/saves/` 下，包含大量中间检查点与冗余文件。仅需将核心指标与配置归档到 `finetune/saves/`，通过 Git 同步到仓库。

在训练机上执行归档（以 fold0 为例，fold1/fold2 替换目录名中的 `3k0` → `3k1`/`3k2`）：

在仓库根目录执行：

```bash
SRC=LlamaFactory/saves/minicpmv4_5/lora/sft_interval_3k0
DST=finetune/saves/minicpmv4_5/lora/sft_interval_3k0
mkdir -p "$DST"
cp "$SRC"/all_results.json "$SRC"/train_results.json "$SRC"/eval_results.json \
   "$SRC"/trainer_log.jsonl "$SRC"/training_loss.png "$SRC"/training_eval_loss.png \
   "$SRC"/adapter_config.json "$SRC"/training_args.bin "$SRC"/trainer_state.json \
   "$SRC"/README.md "$DST"/
```

提交并推送（在仓库根目录执行）：

```bash
cd /path/to/mVllm_2/
git add finetune/saves/
git commit -m "chore(finetune): archive fold0 training results"
git push
```

本地 Mac 拉取归档：

```bash
cd /path/to/mVllm_2/
git pull
```

### 归档文件清单

| ✅ 归档 | ❌ 跳过 |
|---------|----------|
| `all_results.json` | `checkpoint-*/`（中间检查点，体积大） |
| `train_results.json` | `adapter_model.safetensors`（保留在 `LlamaFactory/saves/` 下用于合并 LoRA） |
| `eval_results.json` | `optimizer.pt` |
| `trainer_log.jsonl` | `scheduler.pt` |
| `training_loss.png` | `added_tokens.json` |
| `training_eval_loss.png` | `special_tokens_map.json` |
| `adapter_config.json` | `tokenizer_config.json` |
| `training_args.bin` | `tokenizer.json` |
| `trainer_state.json` | `chat_template.json` |
| `README.md` | `preprocessor_config.json` |

## 验证与评测

`finetune/validation/` 提供完整的推理与评测脚本，详细用法见各脚本的 `--help`。
