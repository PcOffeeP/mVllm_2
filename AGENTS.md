# 项目开发约束

> 本文件记录项目中需要遵守的约束。所有 Agent 在操作本仓库时需遵守。

## 官方参考

MiniCPM-V-4.6 微调官方 CookBook（LLaMA-Factory 方案）：
https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/finetune/llamafactory/llamafactory_minicpmv46_zh.md

与官方 CookBook 的关键差异：
- Full fine-tuning → LoRA + QLoRA (4-bit)：显存限制
- 未使用 DeepSpeed：LoRA 显存够用
- cutoff_len: 4096 → 8192：视频 token 量大
- eval/save 按 epoch（非 steps）：数据集小
- gradient_checkpointing: true（官方未启用）：显存优化

已启用训练参数（与官方一致）：
- warmup_ratio=0.05 / weight_decay=0.1 / adam_beta2=0.95

## 训练前必须设置

```bash
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1
```

- `media_dir`: 必须设为 `../data`（从 CWD=finetune/ 正确解析到 `data/01_videos/`）
- `template`: 必须使用 `minicpm_v_4_6`，禁止用 `minicpm_v`

## 3-Fold 交叉验证

- fold0: dataset=tensile_video_3k1,3k2 / eval_dataset=tensile_video_3k0
- fold1: dataset=tensile_video_3k0,3k2 / eval_dataset=tensile_video_3k1
- fold2: dataset=tensile_video_3k0,3k1 / eval_dataset=tensile_video_3k2
- 禁止只在单个 fold 上训练（错误用法）

## 多机器部署

- 单分支 + 固定 commit 策略
- 执行环境只读，Mac 作为控制塔

## 数据目录结构

- data/ 完整同步到每台机器，保持 `data/01_videos/` 与 `data/04_merged/` 相对关系
- 原始视频：`data/01_videos/`
- 标注文件：`data/02_annotations/`
- 数据集划分：`data/03_splits/`
- 合并产物：`data/04_merged/`

## 数据格式

- CSV 时间格式：`XXX.XXs`（无空格，禁止 `XXX.XX s`）
- 视频路径：正斜杠 `/`，如 `videos/video_XXXX.mp4`
- 视频文件命名：`video_XXXX.mp4`（4 位零填充序号）
- 新标注视频追加到 `data/02_annotations/video_mapping.csv`

## 标注规范

- 材料类型归为：金属、高分子、复材
- `video_mapping.csv` 固定字段：标准化文件名、原始文件名、来源目录、材料类别、状态、duration、resolution、codec

## 脚本与执行

- 从项目根目录运行，路径格式 `pipeline/scripts/xxx.py`、`data/...`
- Python 3.11 / transformers 5.7.0 / torch 2.8.0
- 验证与推理脚本见 `finetune/AAA-TS-Video/validation/`（evaluate_*.py, run_inference.py 等）
