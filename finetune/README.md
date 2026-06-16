# 微调配置目录

本目录仅存放 TensileAgent 项目专属的 LLaMA-Factory 微调配置与验证脚本。
LLaMA-Factory 框架本身已迁移为仓库根目录的 Git submodule：`LlamaFactory/`。

## 目录结构

```text
finetune/
├── dataset_info.json          # 项目数据集注册表
├── README.md                  # 本说明
├── MiniCPM/config/            # models/minicpm-v-4.6 3-fold LoRA SFT YAML 配置
│   ├── minicpmv4_6_lora_sft_fold0.yaml
│   ├── minicpmv4_6_lora_sft_fold1.yaml
│   ├── minicpmv4_6_lora_sft_fold2.yaml
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

1. 下载基座模型到 `models/minicpm-v-4.6/`（见仓库根目录 `README.md`）。
2. 按根目录 `README.md` 准备训练数据，生成 `data/04_merged/` 或 `data/04_new_merged/` 下的 JSON。
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
llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_fold0.yaml

# Fold 1
llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_fold1.yaml

# Fold 2
llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_fold2.yaml
```

训练输出目录为 `LlamaFactory/saves/minicpmv4_6/lora/sft_3k{0,1,2}`。

## 合并 LoRA

```bash
cd finetune/
llamafactory-cli export MiniCPM/config/merge.yaml
```

合并后的完整模型输出到 `LlamaFactory/saves/minicpmv4_6/lora/sft_3k0_merged/`（默认对应 fold0，切换 fold 时请修改 `merge.yaml` 中的 `adapter_name_or_path` 与 `export_dir`）。

## 验证与评测

`finetune/validation/` 提供完整的推理与评测脚本，详细用法见各脚本的 `--help`。
