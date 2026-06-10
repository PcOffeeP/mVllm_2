# AGENTS.md - mVllm 项目开发约束

> 所有 Agent 操作本仓库时必须遵守。本文只保留稳定决策、易踩坑约束和权威入口；具体参数以被链接的配置文件为准。

## 1. 项目定位

mVllm 是基于 MiniCPM-V-4.6 的视频多模态 LoRA/QLoRA 微调项目，用于分析材料拉伸断裂行为。任务输出包括断裂时刻 `time` 和断裂模式 `type`，数据采用 110 个标注视频的 stratified 3-fold CV。

## 2. 权威配置入口

- 训练配置：[finetune/AAA-TS-Video/MiniCPM/config/minicpmv4_6_lora_sft_fold0.yaml](finetune/AAA-TS-Video/MiniCPM/config/minicpmv4_6_lora_sft_fold0.yaml)
- 合并配置：[finetune/AAA-TS-Video/MiniCPM/config/merge.yaml](finetune/AAA-TS-Video/MiniCPM/config/merge.yaml)
- Python 版本：[.python-version](.python-version)、[pyproject.toml](pyproject.toml)
- 环境安装：[README.md](README.md)
- Pipeline 配置：[pipeline/config/question_pool.yaml](pipeline/config/question_pool.yaml)
- 领域说明：[docs/frac_mode.md](docs/frac_mode.md)、[docs/question_pool.md](docs/question_pool.md)
- 项目路线：[docs/roadmap.md](docs/roadmap.md)

不要在 `AGENTS.md` 复制完整训练超参或依赖清单；如果配置变更，优先更新权威文件，再按需更新这里的约束摘要。

## 3. 模型与运行约束

- 基础模型路径固定为 `../MiniCPM-V-4.6`，对话模板固定为 `minicpm_v_4_6`。
- 当前训练方案为 LoRA + QLoRA 4-bit；优化器、学习率、batch、长度等细节以训练 YAML 为准。
- Python 需满足 `>=3.11`；核心训练依赖版本以 README 的安装段落为准。
- `sentencepiece` 必须安装；单卡 LoRA 不需要 DeepSpeed。
- 运行训练前设置：`export DOWNSAMPLE_MODE=4x DISABLE_VERSION_CHECK=1`
- `media_dir` 按训练配置相对 `finetune/` 解析，当前指向 `../data`。
- 4090 环境使用 `flash_attn: fa2`；CUDA、torch、flash-attn 版本以环境文档或训练记录为准。

## 4. 数据与交叉验证

- Pipeline 产出 `data/04_merged/{fold}_{train,val}.json`，并通过 `dataset_info.json` 注册为 `tensile_video_3k{0,1,2}_{train,val}`。
- 视频路径使用正斜杠 `/`，文件名保持 `video_XXXX.mp4` 四位零填充。
- CSV 时间格式必须是 `XXX.XXs`，不要写成 `XXX.XX s`。
- 材料类型限定为：金属、高分子、复材。
- 每个 fold 只使用对应 train/val JSON，不跨 fold 混用。

3-fold 数据集组合：

| Fold | train | val |
| --- | --- | --- |
| 0 | `tensile_video_3k1_train` + `tensile_video_3k2_train` | `tensile_video_3k0_val` |
| 1 | `tensile_video_3k0_train` + `tensile_video_3k2_train` | `tensile_video_3k1_val` |
| 2 | `tensile_video_3k0_train` + `tensile_video_3k1_train` | `tensile_video_3k2_val` |

## 5. MiniCPM 多模态补丁约束

涉及 [finetune/src/llamafactory/data/mm_plugin.py](finetune/src/llamafactory/data/mm_plugin.py) 时保持以下行为：

- `MiniCPMV4_6Plugin._get_mm_inputs` 中视频处理为平级 `if` 块，不嵌套在 images 分支内。
- 所有 `processor()` 调用都带 `text=''`。
- 视频处理使用 `processor(videos=...)`，不要替换为 `video_processor(videos)`。
- `_build_v4_6_placeholder` 对 `target_sizes is None` 做空值保护，使用 `torch.full((n_patches, 2), 448)`。

## 6. 操作边界

- 修改必须保持小而准；不要顺手重构、格式化或清理无关代码。
- 发现配置与本文不一致时，以权威配置文件为准，并在回复中指出差异。
- 禁止自动执行 `git add`、`git commit`、`git push`；只有用户明确要求「提交 / commit / 推送 / push」时才执行对应操作。
