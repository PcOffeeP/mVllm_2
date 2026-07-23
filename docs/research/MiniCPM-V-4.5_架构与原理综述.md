# MiniCPM-V-4.5 基座模型架构与原理综述

> 整理自五路并行调研（官方 GitHub / HF 模型卡 / arXiv 技术报告 / LLaMA-Factory 源码核实），
> 面向本仓库的断裂检测视频 SFT 场景。可信度标注：【官方】= OpenBMB 官方文档/模型卡；
> 【论文】= arXiv:2509.18154；【社区】= 社区经验，需自行验证；【推断】= 调研中的合理推断。
>
> 详细分报告见同目录：
> - `MiniCPM-V-4_5_architecture_research.md`（整体架构总览）
> - `minicpm_llm_backbone_report.md`（LLM backbone 与 MiniCPM 家族训练原理）
> - `minicpmv45_范围D_多模态训练范式与对话格式.md`（训练范式与 chat template）
> - `范围E_MiniCPM-V_LoRA_SFT工程细节调研.md`（LoRA/SFT 工程细节）

## 1. 一句话概括

MiniCPM-V-4.5 是 OpenBMB/面壁智能 2025 年 8 月开源的 8B 级端侧多模态大模型，采用
**SigLIP2-400M 视觉编码器 → 统一 3D-Resampler（时空联合压缩）→ Qwen3-8B 语言模型**
三段式架构。其核心思想是：用极强的视觉 token 压缩换取视频/多图的高吞吐，让 8B 模型
在 32K 上下文内吃下最长 1080 帧的视频。

## 2. 三段式架构详解

### 2.1 视觉编码器：SigLIP2-So400M

- 27 层 ViT，hidden 1152，16 头，patch_size=14，预训练分辨率 448×448。
- 每 448×448 输入产生 (448/14)² = 1024 个 patch token。
- 高分辨率图像不走 NaViT，而是 **LLaVA-UHD 式动态切分**：
  按输入分辨率估计理想 slice 数，选每片最接近 448×448 的网格切分，
  每片 + 1 张整体缩略图（overview）分别过 ViT。
- slice 数上限 `max_slice_nums`：4.5 时代 `trust_remote_code` 默认 9
  （新版 transformers 集成/4.6 文档建议图像 36、视频 1——以所用 checkpoint 自带代码为准）。
- 最大约 1.8M 像素（1344×1344）任意宽高比，token 密度约 2822 像素/token。

### 2.2 连接层：统一 3D-Resampler（本模型核心创新）

- 结构：Perceiver 式 cross-attention 压缩器，**64 个可学习 query**
  （`query_num=64`），叠加 2D 空间位置编码 + **时间位置编码**。
- 图像：每个 slice 被压成固定 64 token（1024 patch → 64 token，16× 空间压缩）。
  单图视觉 token ≈ (slice 数 + 1 overview) × 64。
- 视频：相邻帧按"帧包（package）"分组（**最多 6 帧/包**），
  3D-Resampler 利用相邻帧冗余做时空联合压缩，**每包 → 64 token**，
  即 16× 空间 × 6× 时间 = **96× 视频压缩率**。
  - 每帧实际 token = 64 / package_size（消融实测平均约 21.3 token/帧）。
  - 采样上限：1080 帧、最高 10 fps；训练时 package size 与 fps 随机增强。
- 图像 = package_size 1 的特例，**图像与视频共用同一套 Resampler 权重**，
  2D→3D 升级只需少量视频数据 SFT 完成；图像能力可无缝迁移到视频
  （官方观测到未训练视频 OCR 也涌现出该能力）。
- 时间信息通过 `temporal_ids` 注入（0.1s 量化的帧组 ID）。

### 2.3 语言模型：Qwen3-8B

| 参数 | 值 |
|---|---|
| 层数 / hidden_size | 36 / 4096 |
| 注意力 | GQA：32 Q 头 / 8 KV 头，head_dim=128，带 QK-Norm |
| MLP | SwiGLU，intermediate 12288 |
| 词表 | 151936（Qwen BPE） |
| RoPE | theta=1e6，原生 32768（config 写 40960；第三方标注 32768，按 32K 保守规划） |
| 归一化 | RMSNorm |

- 注意：V 4.5 用的是 **dense attention 的 Qwen3-8B**，不含自研 MiniCPM4 的
  InfLLM v2 稀疏注意力，因此 LLaMA-Factory / vLLM 等主流框架原生支持。
- 总参数量：官方口径"8B"，论文表格 8.7B（约数差异）。
- 双推理模式：fast/deep thinking，`enable_thinking` 切换（模板注入空 `<think></think>`
  或 `<think>\n`），混合 RL（GRPO）联合训练。

## 3. 训练范式（预训练 → SFT → RL）

1. **三阶段渐进式预训练**（选择性冻结贯穿始终）：
   - Stage 1：只训 2D-Resampler（模态对齐热身），ViT/LLM 冻结；
   - Stage 2：解冻 ViT，OCR/文档数据，LLM 冻结（数据语言质量不足，避免污染）；
   - Stage 3：全参端到端，WSD 学习率调度，decay 段混入高质量指令数据。
2. **两阶段 SFT**：通用 SFT（混 10% 纯文本防退化）→ Long-CoT + 2D→3D Resampler 升级。
3. **后训练 RL**：混合快慢思考 GRPO（规则奖励 + RLPR + 偏好 RM）→
   **RLAIF-V**（claim 级事实校验 + DPO 降幻觉，已扩展到视频模态）。

MiniCPM 家族背景技术：WSD 调度器（decay 段喂高质量数据）、模型风洞超参探索、
MiniCPM4 的 InfLLM v2 稀疏注意力与 BitCPM4 三值量化——V 4.5 继承了
WSD 与选择性冻结的训练哲学，但 LLM 侧务实采用 Qwen3-8B。

## 4. 对话格式与 processor 输出契约

- 模板：Qwen3 风格 `<|im_start|>...<|im_end|>`，LLaMA-Factory 中 `template: minicpm_v`。
- 视觉占位体系是 MiniCPM 自有的：`<image>/<unk>×64/</image>`（概览）、
  `<slice>/<unk>×64/</slice>`（切片，`\n` 分行保留 2D 结构）、`<image_id>`（多图编号）。
  `<unk>` 前向时被视觉 embedding 原位替换。
- processor 关键输出字段：
  - `tgt_sizes`：每片/帧的 patch 网格 (H/14, W/14)，供 Resampler 位置编码插值；
  - `image_bound`：每个视觉单元在 input_ids 中的 (start, end)，前向据此替换；
  - `temporal_ids`：视频帧组 ID（图像为 -1），同组帧联合压缩为 64 token；
  - 视频输入须组织为 `frames: List[Image]` + `temporal_ids: List[List[int]]`。
- **占位符数量与媒体数必须严格一致**（processor 内 assert）。

## 5. 对本仓库微调的关键工程结论

1. **框架路径**：V-4.5 微调走 **LLaMA-Factory**（官方 News 确认支持，PR #9022）；
   官方自研 finetune 脚本仅支持到 4.0，对 4.5 会踩 Resampler 形状错误。
2. **⚠️ 训练-推理路径不一致风险（重要）**：LLaMA-Factory 的视频处理是**逐帧独立编码**
   （video_fps 默认 2.0、video_maxlen 默认 128、max_slice_nums=2，约 128 token/帧），
   **不使用 temporal_ids / 6 帧打包的 3D 路径**；而官方推理 `model.chat` 走 3D-Resampler
   打包路径（MAX_NUM_FRAMES=180）。两者视觉 token 组织不同，存在训练-评测分布偏移。
   本仓库已有自研预处理管线（pipeline/preprocessing/minicpm_preprocessor.py），
   需在训练机验证该管线与评测侧的一致性。
3. **token 预算公式**：原生 3D 路径 ⌈帧数/package⌉×64；LLaMA-Factory 路径 帧数×(slice+1)×64。
   `cutoff_len` 必须覆盖视觉 token + 文本，否则截断会切断占位符与视觉 token 的对应。
4. **LoRA 配置**：官方口径 `lora_target: q_proj,v_proj`、lr 1e-5（官方自研脚本则挂
   q/k/v/o 且 lr 1e-6 + tune_vision）；社区常用 1e-4。**不要把 Resampler / 视觉塔加入
   LoRA target**（PEFT 包装与 tgt_sizes/temporal_ids 签名不兼容）。
5. **冻结策略**：官方全参示例 `freeze_vision_tower: true`；"LoRA + 冻结视觉"是官方
   主流路径。若断裂检测这类细粒度视觉判断欠拟合，再考虑解冻视觉侧做消融。
6. **压缩的代价**：每帧 10.7–64 token 意味着极端细节（细小断裂区域、微小纹理）可能被
   压缩掉。评测可关注 `max_slice_nums`/帧数上限变化，并记录为评测配置。
7. **验收口径**：官方 OpenCompass 77.0、Video-MME 73.5、MotionBench 59.7、
   MMHal-Bench 19.4% 可作退化监测基线；任务侧仍需按 AGENTS.md 要求看
   JSON 合法率、has_fracture 准确性、interval 命中率、joint success 等。
8. **模板纪律**：SFT 数据与评测的 `enable_thinking` 设置必须一致；断裂检测 JSON 任务
   建议统一短推理（non-think）模板。

## 6. 未决/冲突信息

- 上下文长度：config 40960 vs 社区 32768——按 32K 保守规划。
- 参数量："8B"（模型卡）vs "8.7B"（论文表格）——LoRA 占比估算用 8.7B。
- `max_slice_nums` 默认值（9 vs 36）随版本变化——以所用 checkpoint 自带 processor 为准。
- 官方未解释 V 4.0(MiniCPM4-3B) → V 4.5(Qwen3-8B) 切换原因。

## 主要来源

- 技术报告：<https://arxiv.org/abs/2509.18154>
- 官方仓库：<https://github.com/OpenBMB/MiniCPM-V>
- 模型卡：<https://huggingface.co/openbmb/MiniCPM-V-4_5>
- 官方 LLaMA-Factory 文档：<https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/llamafactory_train_and_infer.md>
- LLaMA-Factory mm_plugin 源码（当前 main 分支核实）
