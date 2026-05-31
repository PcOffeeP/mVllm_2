# 项目开发约束

> 本文件记录项目中需要遵守的小约束。所有 Agent 在操作本仓库时需遵守。

## 官方参考

MiniCPM-V-4.6 微调官方 CookBook（LLaMA-Factory 方案）：
https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/main/finetune/llamafactory/llamafactory_minicpmv46_zh.md

与官方 CookBook 的关键差异及原因：
- LoRA+QLoRA（非 full fine-tuning）：显存限制
- cutoff_len=8192（非 4096）：视频场景 token 量更大
- eval/save 按 epoch（非 steps）：数据集小（1320条）
- 未使用 DeepSpeed：LoRA 显存够用
- 未设置 warmup=0.05/weight_decay=0.1/adam_beta2=0.95：LoRA 场景待验证

训练前必须设置环境变量：
- export DOWNSAMPLE_MODE=4x（推荐，提升效果）
- export DISABLE_VERSION_CHECK=1

## 数据格式

- CSV 时间格式统一为数值型 `XXX.XXs`（无空格），不使用 `XXX.XX s`
- 视频路径使用正斜杠 `/`，如 `videos/video_XXXX.mp4`
- 视频文件命名标准化为 `video_XXXX.mp4`（4 位零填充序号）
- 新标注视频需追加到 `data/02_annotations/video_mapping.csv`

## 脚本与执行

- 所有脚本使用 `#!/usr/bin/env python3` shebang，命令行调用统一用 `python3`（非 `python`）
- 脚本从项目根目录运行，路径引用格式如 `pipeline/scripts/xxx.py`、`data/...`
- Python 版本：3.11
- transformers 版本：5.7.0

## 数据目录结构

- 原始视频：`data/01_videos/`
- 标注文件：`data/02_annotations/`
- 数据集划分：`data/03_splits/`
- 合并产物：`data/04_merged/`

## 标注规范

- 材料类型归为四大类：金属、高分子、复材
- `video_mapping.csv` 固定字段：标准化文件名、原始文件名、来源目录、材料类别、状态、duration、resolution、codec
