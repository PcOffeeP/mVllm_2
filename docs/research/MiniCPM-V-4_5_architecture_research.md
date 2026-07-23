# 调研主题：MiniCPM-V-4.5 整体架构总览（范围 A）

调研日期：以本次会话时间为准。调研员：MiniCPM调研员（技术调研专员子代理）。

## 一、模型组成与整体结构

MiniCPM-V-4.5 是 OpenBMB / 面壁智能 2025-08-26 开源的 8B 级端侧多模态大模型（MLLM），架构由三大模块组成（论文 Section 2.1 明确划分）：

1. **视觉编码器**：SigLIP2-400M（SigLIP2-So400M 规格）。模型 config 中 `vision_config` 为 siglip 类型，hidden_size=1152、27 层、16 个注意力头、patch_size=14，与 SigLIP2-So400M 的公开配置一致。
2. **连接/重采样模块：统一 3D-Resampler**（核心创新，详见第三节）。
3. **语言模型 backbone（LLM 解码器）**：Qwen3-8B。模型 config 显示 hidden_size=4096、36 层、GQA（32 Q 头 / 8 KV 头）、head_dim=128、vocab_size=151748、rope_theta=1e6，即 Qwen3-8B 的配置。

- 来源（官方）：HuggingFace 模型卡 <https://huggingface.co/openbmb/MiniCPM-V-4_5>（经 hf-mirror 镜像读取）
- 来源（官方）：模型 config.json <https://hf-mirror.com/openbmb/MiniCPM-V-4_5/raw/main/config.json>
- 来源（论文）：MiniCPM-V 4.5 技术报告 arXiv:2509.18154 <https://arxiv.org/abs/2509.18154>
- 来源（官方）：GitHub <https://github.com/OpenBMB/MiniCPM-V>

## 二、参数量构成

- 官方模型卡口径："built on Qwen3-8B and SigLIP2-400M with a total of 8B parameters"。
- 技术报告效率对比表中标注的模型 size 为 **8.7B**（含全部模块）。
- 分项推断（社区/推断口径，官方未逐项公布）：Qwen3-8B 约 8.2B（含 embedding）；SigLIP2-So400M 约 0.4B；3D-Resampler（cross-attention + 可学习 query）参数量很小（数千万级，推断）。
- ⚠️ 冲突标注：官方"8B"与技术报告表格"8.7B"并存，前者是约数/宣传口径，后者更接近实际参数总量。LoRA 可训练参数占比估算应以 8.7B 为分母。

## 三、核心架构：统一 3D-Resampler

- 由前代 2D-Resampler 扩展而来，对图像/视频做统一的时空联合压缩（cross-attention + 可学习 query，query 数 query_num=64，见 config）。
- **图像**：采用 LLaVA-UHD 切分策略处理任意宽高比高分辨率图，每个 slice 经 cross-attention 压成固定 64 token；448×448 图像仅 64 token（多数 MLLM 需 256 token），即 4× 压缩率。
- **视频**：沿时间维度把相邻帧打包（package，最多 6 帧/包），每包联合压缩为 64 token → **96× 视频 token 压缩率**（6 帧 448×448 → 64 token；对比 Qwen2.5-VL 同规模需 1536 token）。
- 视频采样上限：每视频最多 1080 帧、最高 10 fps；训练时 package size 与帧率随机增强。
- 图像与视频共享同一 Resampler 权重，因此从 2D 升级到 3D 只需轻量 SFT 阶段，且图像能力可迁移到视频（官方观察到未训练视频 OCR 数据也具备视频 OCR 能力）。
- 时间信息通过 `temporal_ids`（TIME_SCALE=0.1s 的时间戳量化 id，随打包帧分组传入）注入。
- 来源（论文）：arXiv:2509.18154 Section 2.1.1；来源（官方）：HF 模型卡 "Key Techniques" 及视频推理示例代码。

## 四、上下文长度与视觉 token 预算

- config.json：`max_position_embeddings = 40960`。
- 第三方推理框架 Xinference 文档标注 Context Length = 32768（<https://inference.readthedocs.io/en/v1.13.0/models/builtin/llm/minicpm-v-4.5.html>，社区/框架口径）。
- ⚠️ 冲突标注：官方 config 给 40960，社区框架按 Qwen3 原生 32K 标注 32768。官方模型卡未直接写明文本上下文长度，微调时建议以 32768 为保守上限。
- 视觉 token 预算（官方/论文确认）：每 slice 64 token；高分辨率图最大 9 个 slice（`max_slice_nums=9`，另有 1 个全局缩略图 slice，即单图约 640 token 量级）；单 slice 分辨率 448（scale_resolution=448）；支持最高约 180 万像素（如 1344×1344）任意宽高比图像。
- 视频：每包（≤6 帧）64 token；最多 1080 帧 → 视频视觉 token 上限约 64×(1080/6)=11520 token（按论文参数推算，非官方直接给出的数字）。
- 来源（官方）：config.json / preprocessor_config.json（<https://hf-mirror.com/openbmb/MiniCPM-V-4_5/raw/main/preprocessor_config.json>）。

## 五、官方宣称能力与 Benchmark 表现

官方模型卡宣称（官方口径）：
- OpenCompass（8 个主流 benchmark 平均）**77.0**，超过 GPT-4o-latest、Gemini-2.0 Pro 和 Qwen2.5-VL 72B，为 30B 以下最强 MLLM。
- 视频理解：Video-MME (w/o subs) 67.9 / (w/ subs) 73.5；LVBench 50.4；MLVU 75.1；LongVideoBench 63.9；MotionBench 59.7；FavorBench 56.0（论文 Table 1）。Video-MME 上为 30B 以下 SOTA，且推理时间仅为 Qwen2.5-VL-7B 的 8.7%、显存 46.7%（8×A100 实测：0.26h / 28G vs 3.00h / 60G）。
- OCR/文档：OCRBench 89.0（超 GPT-4o-latest）；OmniDocBench 通用 MLLM 中 PDF 解析 SOTA（EN 0.175 / ZH 0.253，越低越好）。
- 幻觉控制：ObjHalBench CHAIRs 9.3、MMHal-Bench Rate 19.4%，优于 GPT-4o-latest（RLAIF-V 训练）。
- 可控混合推理：fast thinking / deep thinking 双模式，通过 `enable_thinking=True/False` 切换；混合 RL（GRPO）联合优化。
- 30+ 语言多语言能力。
- 来源（论文）：arXiv:2509.18154 Table 1/2/3；来源（官方）：HF 模型卡 Evaluation 部分。

训练流程（论文确认，供理解模型行为）：三阶段预训练（先只训 2D-Resampler → 解冻视觉编码器 → 全量端到端）→ 两阶段 SFT（通用 SFT + Long-CoT & 3D-Resampler 升级）→ 混合 RL（GRPO，规则奖励 + RLPR 概率奖励 + 偏好 RM，长短推理模式随机交替）→ RLAIF-V（DPO 降幻觉）。

框架支持（官方确认）：LLaMA-Factory 自 2025-08-26 起官方支持 MiniCPM-V-4.5 微调（上游 PR #9022）；vLLM v0.10.2、llama.cpp b6282 已支持；SGLang/Ollama 当时仍在合并中。
- 来源（官方）：GitHub News 2025-09-01 条目与 HF 模型卡 Framework Support Matrix。

## 六、与微调实践相关的要点

1. **LoRA 挂点选择**：模型 = Qwen3-8B（4096 hidden, 36 层, GQA）+ SigLIP2-400M + 3D-Resampler。LLaMA-Factory 对该模型的 LoRA 默认作用于 LLM 部分；若视频理解任务需要调整视觉对齐，需确认是否冻结 vision tower / resampler（官方预训练范式也是分阶段解冻，说明全量乱解冻有风险）。
2. **视频数据预处理必须匹配 3D-Resampler 协议**：帧打包（≤6 帧/包）、`temporal_ids`（TIME_SCALE=0.1 量化时间戳）、每包 64 token 的占位符数量必须与实际帧数/打包数一致，否则训练-推理分布不一致。官方推理示例中 `max_slice_nums=1`、`use_image_id=False` 用于视频——微调数据构造也应遵循。
3. **token 预算估算**：每 6 帧 ≈ 64 token，1080 帧长视频 ≈ 11.5K 视觉 token；加上文本部分，32K 上下文做长视频 SFT 基本够用，但打包数、切片数设错会立刻爆上下文或丢帧。
4. **视觉 token 极少 = 定位类任务天然受限**：64 token/帧的极限压缩以效率换空间细粒度，视频目标定位、精确时序区间（interval）类输出可能受压缩损失影响；微调评测时不能只看过拟合的训练指标，要看 interval 命中率等任务指标。
5. **双推理模式影响数据格式**：模型有 fast/deep thinking 两种模式，SFT 数据若混入思维链格式需与官方模式控制方式（enable_thinking 提示机制）对齐，否则评测时模式不一致会导致指标波动。
6. **评测基线参考**：官方 Video-MME 73.5(w/ subs)、MotionBench 59.7 等可作为微调后退化检查的参照；RLAIF-V 阶段已专门降幻觉，SFT 不当可能破坏该特性（MMHal-Bench 可监测）。
7. **显存参考**：官方 Video-MME 全评测仅需 28G 显存（bf16 推理），单卡 4090（24G）做 bf16 全量推理偏紧，LoRA 微调需量化/梯度检查点等手段（社区经验，非官方数字）。

## 七、信息可信度汇总

- 官方确认：模型组成（Qwen3-8B + SigLIP2-400M）、8B 总参、3D-Resampler 96× 压缩、1080 帧/10fps 上限、OpenCompass 77.0 及各 benchmark 分数、LLaMA-Factory/vLLM/llama.cpp 支持（GitHub README + HF 模型卡 + config 文件）。
- 论文确认（arXiv:2509.18154）：架构三模块划分、训练流程细节、8.7B 总量口径、效率对比数字、混合 RL 消融。
- 社区/框架口径（需谨慎）：上下文 32768（Xinference）、部分分项参数量推断、4090 显存经验值。
- 冲突未决：官方 config max_position_embeddings=40960 vs 社区标注 32768；"8B" vs "8.7B" 两种参数量口径。
