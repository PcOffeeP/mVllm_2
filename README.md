# mVllm — 材料拉伸断裂行为视频理解模型微调

基于 MiniCPM-V-4.6 的视频多模态模型微调项目，用于理解和分析材料拉伸断裂行为视频。

详细约束与规范见 [AGENTS.md](./AGENTS.md)。

---

## 目录结构

```
mVllm/
├── data/
│   ├── 01_videos/              # 原始视频文件 (video_0001~video_0110.mp4)
│   ├── 02_annotations/         # CSV 标注 + video_mapping.csv + all_videos_tag.csv
│   ├── 03_splits/              # stratified 3-fold 划分文件
│   └── 04_merged/              # 合并后的训练数据 JSON
├── pipeline/
│   ├── scripts/                # 数据处理脚本
│   │   ├── dataset_manager.py       # 生成 stratified 3-fold split
│   │   ├── generate_questions.py    # 生成带随机问题的训练 JSON
│   │   ├── fill_answers.py          # 从 CSV 填入答案
│   │   ├── merge_batches.py         # 合并各 batch 为最终训练 JSON
│   │   ├── init_json.py             # 初始化 JSON
│   │   ├── randomize_qs.py
│   │   ├── test_fill_answers.py
│   │   └── video_rename.py
│   ├── config/                 # 问题池配置 (question_pool.yaml)
│   ├── templates/
│   │   └── template.json             # 问题模板
│   └── batches/                # 中间产物 (processed/ + answered/)
├── finetune/                   # LLaMA-Factory 训练目录
│   ├── data/
│   │   └── dataset_info.json         # 数据集注册表
│   ├── AAA-TS-Video/MiniCPM/config/
│   │   ├── minicpmv4_6_lora_sft_fold0.yaml  # Fold 0 训练配置
│   │   ├── minicpmv4_6_lora_sft_fold1.yaml  # Fold 1 训练配置
│   │   ├── minicpmv4_6_lora_sft_fold2.yaml  # Fold 2 训练配置
│   │   └── merge.yaml                         # LoRA 合并配置
│   ├── AAA-TS-Video/validation/      # 推理与评测脚本
│   │   ├── run_inference.py
│   │   ├── evaluate_joint.py
│   │   ├── evaluate_time.py
│   │   ├── evaluate_type.py
│   │   ├── prepare_ground_truth.py
│   │   ├── plot_type_confusion_matrix.py
│   │   ├── common.py
│   │   └── config.py
│   └── saves/                  # 训练产出 (当前为空)
├── docs/
│   ├── frac_mode.md            # 断裂模式分类指南
│   └── question_pool.md        # 问题池参考
├── assets/
├── AGENTS.md                   # 项目开发约束
├── ROADMAP.md                  # 工作计划与路线图
└── README.md
```

---

## Phase 1：数据准备

**前置条件**：视频文件放入 `data/01_videos/`，CSV 标注文件放入 `data/02_annotations/`。

从项目根目录依次执行：

```bash
# Step 1: 生成 stratified 3-fold 划分
python3 pipeline/scripts/dataset_manager.py

# Step 2: 对每个 fold 生成带随机问题的训练数据
python3 pipeline/scripts/generate_questions.py \
  -s data/03_splits/stratified_3_fold_0.json \
  -b stratified_3_fold_0

python3 pipeline/scripts/generate_questions.py \
  -s data/03_splits/stratified_3_fold_1.json \
  -b stratified_3_fold_1

python3 pipeline/scripts/generate_questions.py \
  -s data/03_splits/stratified_3_fold_2.json \
  -b stratified_3_fold_2

# Step 3: 从 CSV 填入答案
python3 pipeline/scripts/fill_answers.py -b stratified_3_fold_0
python3 pipeline/scripts/fill_answers.py -b stratified_3_fold_1
python3 pipeline/scripts/fill_answers.py -b stratified_3_fold_2

# Step 4: 合并为训练用 JSON（输出到 data/04_merged/）
python3 pipeline/scripts/merge_batches.py --source answered
```

完成后，`data/04_merged/` 下会生成六个训练/验证数据集文件：
- `stratified_3_fold_0_train.json`
- `stratified_3_fold_0_val.json`
- `stratified_3_fold_1_train.json`
- `stratified_3_fold_1_val.json`
- `stratified_3_fold_2_train.json`
- `stratified_3_fold_2_val.json`

这些数据集已在 `finetune/data/dataset_info.json` 中注册为 `tensile_video_3k0_train`、`tensile_video_3k0_val`、`tensile_video_3k1_train`、`tensile_video_3k1_val`、`tensile_video_3k2_train`、`tensile_video_3k2_val`。

---

## Phase 2：安装依赖

> ⚠️ 前置检查：运行 `nvidia-smi` 确认 Driver Version ≥ 550。
> 驱动不足需先升级，否则 torch 2.8.0 无法运行。

> **Python 版本**：官方 CookBook 要求 Python 3.11，项目统一使用 Python 3.11。

### 镜像源配置（国内用户必做）

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

以下为完整安装方案。

### RTX 4090（本地桌面）

> **优势**：SM 8.9 架构原生支持 Flash Attention 2，训练时需启用 `fa2`。

```bash
# 1. Python 环境
conda create -n mvllm python=3.11 -y
conda activate mvllm

# 2. PyTorch 三件套
pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 -i https://pypi.tuna.tsinghua.edu.cn/simple -f https://download.pytorch.org/whl/cu121

# 2.5 CUDA Runtime（若系统缺 libcudart.so）
conda install -c nvidia cuda-runtime=13.0 -y

# 3. 核心训练依赖（含 flash-attn，4090 支持）
pip install transformers==5.7.0 accelerate==1.13.0 peft==0.18.1 bitsandbytes>=0.39.0 trl==0.24.0 wandb ninja einops safetensors tokenizers sentencepiece
MAX_JOBS=32 pip install --no-build-isolation flash-attn==2.8.3

# 4. LLaMA-Factory
cd finetune/
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt

# 5. 锁定 transformers 版本
pip install transformers==5.7.0

# 6. 模型下载
pip install modelscope
# export HF_ENDPOINT=https://hf-mirror.com  # 备选：国内用户可通过 HF 镜像下载
modelscope download --model OpenBMB/MiniCPM-V-4.6 --local_dir ./MiniCPM-V-4_6
# ⚠️ 若训练报错 "Processor was not found"，说明 modelscope 下载不完整。
# 改用：python -c "from huggingface_hub import snapshot_download; snapshot_download('openbmb/MiniCPM-V-4_6', local_dir='./MiniCPM-V-4_6')"
```

> ⚠️ 下载完成后，确认各 fold YAML 中 `model_name_or_path` 已指向本地路径 `../MiniCPM-V-4_6`。

> ⚠️ **4090 需额外修改训练 YAML**：将 `flash_attn: sdpa` 改为 `flash_attn: fa2`，以启用 Flash Attention 2 加速。

> 💡 4090 用户可将 YAML 中 `preprocessing_num_workers` 提升至 4~16，加速数据预处理。

---

## Phase 3：训练

### 3-fold 交叉验证结构

项目采用 **3-fold 交叉验证**，每个 fold 使用 2 份数据训练、1 份数据验证：

| Fold | 训练集 | 验证集 | 配置文件 |
|------|--------|--------|----------|
| Fold 0 | 3k1_train + 3k2_train | 3k0_val | `minicpmv4_6_lora_sft_fold0.yaml` |
| Fold 1 | 3k0_train + 3k2_train | 3k1_val | `minicpmv4_6_lora_sft_fold1.yaml` |
| Fold 2 | 3k0_train + 3k1_train | 3k2_val | `minicpmv4_6_lora_sft_fold2.yaml` |

其中 3k0_train / 3k0_val / 3k1_train / 3k1_val / 3k2_train / 3k2_val 对应 Phase 1 生成的 `tensile_video_3k0_train` / `tensile_video_3k0_val` / `tensile_video_3k1_train` / `tensile_video_3k1_val` / `tensile_video_3k2_train` / `tensile_video_3k2_val` 数据集。

### 启动训练

```bash
# 确保在 finetune/ 目录下
cd finetune/

# DOWNSAMPLE_MODE 控制视频帧下采样策略，可选 2x / 4x / 8x
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

# Fold 0: 训练用 3k1+3k2，验证用 3k0
llamafactory-cli train AAA-TS-Video/MiniCPM/config/minicpmv4_6_lora_sft_fold0.yaml

# Fold 1: 训练用 3k0+3k2，验证用 3k1
llamafactory-cli train AAA-TS-Video/MiniCPM/config/minicpmv4_6_lora_sft_fold1.yaml

# Fold 2: 训练用 3k0+3k1，验证用 3k2
llamafactory-cli train AAA-TS-Video/MiniCPM/config/minicpmv4_6_lora_sft_fold2.yaml
```

三个 fold 相互独立，可串行执行也可在不同 GPU 上并行。

### 训练配置说明

| 配置项 | 默认值 |
|--------|--------|
| 模型 | `openbmb/MiniCPM-V-4_6` |
| 微调方式 | LoRA (rank=16, alpha=32, dropout=0.1) |
| 量化 | 4-bit (QLoRA) |
| 模板 | `minicpm_v_4_6` |
| cutoff_len | 8192 |
| 视频最大帧数 | 36 |
| 批次大小 | 1 × 梯度累积 16 |
| 学习率 | 1.5e-5 (cosine) |
| 训练轮数 | 8 |
| warmup_ratio | 0.05 |
| weight_decay | 0.1 |
| adam_beta2 | 0.95 |
| optim | paged_adamw_8bit |
| max_grad_norm | 1000 |
| seed | 42 |
| gradient_checkpointing | ✅ |
| media_dir | `../data` |

> **`media_dir` 说明**：`media_dir: ../data` 确保训练数据 JSON 中的视频相对路径（如 `01_videos/video_0001.mp4`）能够从 `finetune/` 正确解析到 `data/01_videos/` 下的实际视频文件。

---

## Phase 4：合并 LoRA Adapter

训练完成后，使用 `merge.yaml` 将 LoRA adapter 合并到基础模型中：

```bash
cd finetune/

# 合并指定 fold 的 adapter（以 Fold 0 为例）
llamafactory-cli export AAA-TS-Video/MiniCPM/config/merge.yaml
```

`merge.yaml` 中 `adapter_name_or_path` 指向训练产出目录（如 `./saves/minicpmv4_6/lora/sft_3k0`），合并后的完整模型输出到 `export_dir`（如 `./saves/minicpmv4_6/lora/sft_3k0_merged`）。切换 fold 时修改对应路径即可。

## Phase 5：验证与评测

训练完成后，模型权重保存路径（以 Fold 0 为例）：`finetune/saves/minicpmv4_6/lora/sft_3k0/`。

验证策略为 **epoch 级评估**，以 `eval_loss` 为最佳模型指标，训练结束时自动加载最优 checkpoint。

### 推理与评测流程

`finetune/AAA-TS-Video/validation/` 目录提供完整的推理与评测脚本：

1. **推理**：`run_inference.py` 对指定 fold 的测试集执行模型推理
2. **评测**：
   - `evaluate_time.py` — 断裂时间 MAE 评测
   - `evaluate_type.py` — 断裂模式分类准确率评测
   - `evaluate_joint.py` — 联合评测（时间 + 模式）
3. **辅助**：
   - `prepare_ground_truth.py` — 生成 ground truth 文件
   - `plot_type_confusion_matrix.py` — 绘制分类混淆矩阵
   - `common.py` / `config.py` — 共享工具与配置

详细用法见各脚本的 `--help` 参数说明。

---

## 与官方 CookBook 的差异

本项目基于 [MiniCPM-V CookBook](https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/finetune/llamafactory/llamafactory_minicpmv46_zh.md) 的 LLaMA-Factory 微调流程，但根据材料视频理解任务的实际情况做了以下调整：

| 差异点 | 官方 CookBook | 本项目 | 原因 |
|--------|-------------|--------|------|
| 微调方式 | Full fine-tuning | LoRA + QLoRA (4-bit) | 单卡显存限制，无法支撑全参微调 |
| cutoff_len | 默认（较短） | 8192 | 视频帧 token 量大，需更长上下文 |
| eval / save 策略 | 按 step | 按 epoch | 数据集较小（~110 视频），按 step 评估频率过高 |
| gradient_checkpointing | 未启用 | 启用 | 节省显存，以少量计算换显存空间 |

核心流程（数据准备 → LLaMA-Factory 训练 → epoch 级验证）与官方保持一致，差异仅体现在训练配置层面以适应实际硬件条件和数据规模。

---

## 数据约束

项目数据格式受 [AGENTS.md](./AGENTS.md) 约束，关键要点：

- CSV 时间格式统一为 `XXX.XXs`（**无空格**），不使用 `XXX.XX s`
- 视频文件命名标准化为 `video_XXXX.mp4`（4 位零填充）
- 新标注视频需追加到 `data/02_annotations/video_mapping.csv`
- 材料类型归为四大类：金属、高分子、复材
- 所有脚本使用 `python3` 调用，从项目根目录执行
- Python 版本：3.11
