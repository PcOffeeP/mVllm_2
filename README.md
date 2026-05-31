# mVllm — 材料拉伸断裂行为视频理解模型微调

基于 MiniCPM-V-4.5 的视频多模态模型微调项目，用于理解和分析材料拉伸断裂行为视频。

详细约束与规范见 [AGENTS.md](./AGENTS.md)。

---

## 目录结构

```
mVllm/
├── data/
│   ├── 01_videos/              # 原始视频文件 (video_0001~video_0110.mp4)
│   ├── 02_annotations/         # CSV 标注 + video_mapping.csv
│   ├── 03_splits/              # stratified 3-fold 划分文件
│   └── 04_merged/              # 合并后的训练数据 JSON
├── pipeline/
│   ├── scripts/                # 数据处理脚本
│   │   ├── dataset_manager.py       # 生成 stratified 3-fold split
│   │   ├── generate_questions.py    # 生成带随机问题的训练 JSON
│   │   ├── fill_answers.py          # 从 CSV 填入答案
│   │   ├── merge_batches.py         # 合并各 batch 为最终训练 JSON
│   │   └── init_json.py             # 初始化 JSON
│   ├── config/                 # 问题池配置 (question_pool.yaml)
│   └── batches/                # 中间产物 (processed/ + answered/)
├── finetune/                   # LLaMA-Factory 训练目录
│   ├── data/
│   │   └── dataset_info.json         # 数据集注册表
│   ├── AAA-TS-Video/MiniCPM/config/
│   │   ├── minicpmv4_5_lora_sft.yaml       # v1 训练配置
│   │   └── minicpmv4_5_lora_sft_v2.yaml    # v2 训练配置
│   └── saves/                  # 训练产出
├── AGENTS.md                   # 项目开发约束
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

完成后，`data/04_merged/` 下会生成三个训练数据集文件：
- `stratified_3_fold_0.json`
- `stratified_3_fold_1.json`
- `stratified_3_fold_2.json`

这些数据集已在 `finetune/data/dataset_info.json` 中注册为 `tensile_video_3k0`、`tensile_video_3k1`、`tensile_video_3k2`。

---

## Phase 2：安装依赖

> **Python 版本**：官方 CookBook 要求 Python 3.11，当前项目使用 Python 3.13，需降级至 3.11 后执行以下安装。

关键依赖版本：`transformers==5.7.0`（官方 CookBook 硬要求），其他依赖按以下命令安装。

```bash
# 1. PyTorch（建议先装，确保 CUDA 兼容）
pip install torch==2.8.0 torchvision==0.23.0

# 2. 核心训练依赖
pip install transformers==5.7.0 accelerate==1.13.0 deepspeed==0.18.3 peft==0.18.1 trl==0.24.0 wandb ninja einops safetensors tokenizers sentencepiece

# 3. Flash Attention（编译安装）
MAX_JOBS=32 pip install --no-build-isolation flash-attn==2.8.3

# 4. 进入 finetune/ 目录
cd finetune/

# 5. LLaMA-Factory 核心 + MiniCPM-V 视频处理依赖
pip install -e ".[metrics,deepspeed]"
pip install -r examples/requirements/minicpm-v.txt

# 6. （可选）从 ModelScope 下载模型
pip install modelscope
```

---

## Phase 3：训练

### MiniCPM-V-4.6 训练（推荐）

```bash
# 确保在 finetune/ 目录下
cd finetune/

# DOWNSAMPLE_MODE 控制视频帧下采样策略，可选 2x / 4x / 8x
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

# 启动训练（默认使用 fold 2 数据）
llamafactory-cli train AAA-TS-Video/MiniCPM/config/minicpmv4_6_lora_sft.yaml
```

### MiniCPM-V-4.5 训练

```bash
cd finetune/

# 使用 v2 配置启动训练（默认使用 fold 2 数据）
llamafactory-cli train AAA-TS-Video/MiniCPM/config/minicpmv4_5_lora_sft_v2.yaml
```

### 训练配置说明

| 配置项 | v4.6 默认值 | v4.5 v2 默认值 |
|--------|-----------|---------------|
| 模型 | `openbmb/MiniCPM-V-4_6` | `openbmb/MiniCPM-V-4_5` |
| 微调方式 | LoRA (rank=16, alpha=32) | LoRA (rank=16, alpha=32) |
| 量化 | 4-bit (QLoRA) | 4-bit |
| 模板 | `minicpm_v_4_6` | `minicpm_v` |
| 数据集 | `tensile_video_3k2` | `tensile_video_3k2` |
| cutoff_len | 8192 | — |
| 视频最大帧数 | 36 | 36 |
| 批次大小 | 1 × 梯度累积 18 | 1 × 梯度累积 18 |
| 学习率 | 1.5e-5 (cosine) | 1.5e-5 (cosine) |
| 训练轮数 | 8 | 8 |
| 验证集比例 | 10% | 10% |
| gradient_checkpointing | ✅ | — |

可通过修改 `dataset` 字段切换 fold：将 `tensile_video_3k2` 改为 `tensile_video_3k0` 或 `tensile_video_3k1`。

---

## 验证

训练完成后，模型权重保存路径：
- v4.6：`finetune/saves/minicpmv4_6/lora/sft_3k2/`
- v4.5：`finetune/saves/minicpmv4_5/lora/sft_3k2_v2/`

验证策略为 **epoch 级评估**，以 `eval_loss` 为最佳模型指标，训练结束时自动加载最优 checkpoint。

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
- Python 版本：3.13
