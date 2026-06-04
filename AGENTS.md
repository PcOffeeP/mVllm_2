# AGENTS.md — mVllm 项目开发约束

> 所有 Agent 操作本仓库时必须遵守。

## 项目定位
mVllm：基于 MiniCPM-V-4.6 的视频多模态 LoRA/QLoRA 微调项目，分析材料拉伸断裂行为。
数据：110 个标注视频，stratified 3-fold CV。任务：断裂时刻（time）+ 断裂模式（type）。

---

## 模型与配置约束
- model_name_or_path: `../MiniCPM-V-4.6`
- template: `minicpm_v_4_6`
- flash_attn: `fa2`
- video_maxlen: 36, cutoff_len: 8192, media_dir: `../data`
- env: `export DOWNSAMPLE_MODE=4x DISABLE_VERSION_CHECK=1`
- preprocessing_num_workers: 4~16
- 训练：LoRA (rank=16, alpha=32, dropout=0.1) + QLoRA 4-bit
- optim: paged_adamw_8bit, lr=1.5e-5 cosine, epochs=8, warmup_ratio=0.05
- weight_decay=0.1, adam_beta2=0.95, max_grad_norm=1000, bf16=true
- batch: 1 × grad_accum 16, gradient_checkpointing=true, seed=42

---

## 依赖约束
- **Python 3.11 硬要求**
- transformers==5.7.0, torch==2.8.0, peft==0.18.1, bitsandbytes>=0.39.0, trl==0.24.0
- sentencepiece 必须装；DeepSpeed 不需要（LoRA 单卡）
- CUDA runtime: `conda install -c nvidia cuda-runtime=13.0`

| 环境 | torch | flash-attn | 驱动 | 其他 |
|------|-------|-----------|------|------|
| 4090 | cu121 | fa2==2.8.3 | ≥550 | YAML 改 flash_attn: fa2 |

---

## mm_plugin.py 已知修改
文件：`finetune/src/llamafactory/data/mm_plugin.py`

### MiniCPMV4_6Plugin._get_mm_inputs
- 视频处理必须为**平级 if 块**（不嵌套在 images 内）
- 所有 `processor()` 调用须带 `text=''` 参数
- `processor(videos=...)` 不能用 `video_processor(videos)` 代替

### _build_v4_6_placeholder
- `target_sizes is None` 需空值保护 → `torch.full((n_patches, 2), 448)`

---

## 数据流与 pipeline
### 产出与注册
- pipeline → `data/04_merged/{fold}_{train,val}.json`（6 个文件）
- dataset_info.json 注册名: `tensile_video_3k{0,1,2}_{train,val}`

### 关键约束
- 视频路径相对 `media_dir: ../data` 解析（CWD=finetune/）
- CSV 时间: `XXX.XXs`（无空格），禁用 `XXX.XX s`
- 视频命名: `video_XXXX.mp4`（4 位零填充），路径正斜杠 `/`
- 材料类型: 金属、高分子、复材

### 模型下载
```bash
modelscope download --model OpenBMB/MiniCPM-V-4.6 --local_dir ./MiniCPM-V-4.6
```
默认下载全部文件。需含 model.safetensors, tokenizer.json, preprocessor_config.json。
若缺 Processor → 改用 `snapshot_download('openbmb/MiniCPM-V-4_6', local_dir='...')`

---

## 3-Fold CV
| Fold | train | val |
|------|-------|-----|
| 0 | tensile_video_3k1_train + 3k2_train | tensile_video_3k0_val |
| 1 | tensile_video_3k0_train + 3k2_train | tensile_video_3k1_val |
| 2 | tensile_video_3k0_train + 3k1_train | tensile_video_3k2_val |
每 fold 只用自己对应的 train/val JSON，不跨 fold。

---

## 多机器部署
- 单分支 + 固定 commit；Mac 作控制塔，执行环境只读；data/ 完整同步

## 参考文档
ROADMAP.md, TASK_TRACKER.md, docs/frac_mode.md, docs/question_pool.md
