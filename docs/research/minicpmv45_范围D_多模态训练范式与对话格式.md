# 调研主题：范围 D — MiniCPM-V-4.5 多模态训练范式与对话格式

> 调研员：MiniCPM调研员 ｜ 调研日期：当前会话 ｜ 调研方式：官方 GitHub 文档 + arXiv 技术报告 + HuggingFace 官方模型仓库源码（经 hf-mirror 镜像获取原文）+ 社区文章交叉验证
> 可信度标注约定：**【官方】**= OpenBMB 官方文档/官方代码；**【论文】**= arXiv 技术报告/正式论文；**【社区】**= 第三方解读，需谨慎对待。

---

## 1. 预训练与对齐全流程（MiniCPM-V 4.5）

### 1.1 三阶段渐进式预训练【论文】【官方】

来源：[MiniCPM-V 4.5 技术报告 arXiv:2509.18154, §2.2.1](https://arxiv.org/html/2509.18154v1)

- **Stage 1（视觉-语言对齐 warm-up）**：只训练 **2D-Resampler**，ViT 与 LLM 全部冻结；使用 image-caption 数据，以最小成本建立视觉与语言模态的初始对齐。
- **Stage 2（感知基础增强）**：解冻 **视觉编码器（ViT）**，使用 OCR 富集数据 + image-caption 数据；由于该阶段数据的语言质量/流畅度不足，**LLM 保持冻结**。
- **Stage 3（端到端全量训练）**：**解冻全部参数（含 LLM）**，使用最高质量数据（纯文本语料、图文交错样本、视频、前两阶段精选子集），覆盖多图推理与时序理解；采用 Warmup-Stable-Decay 学习率调度，decay 阶段逐步加入更多高质量指令与知识密集型数据。
- 论文给出的 Takeaway："基础能力可以建立在不完备的异构数据上，关键是**选择性地冻结参数**。"

### 1.2 预训练数据组成【论文】

来源：同上，§2.2.2

- Image Caption：LAION-2B、COYO 等 + 中文网页图文对，CLIP 过滤 + Capsfusion 重描述 + 概念标签均衡。
- 图文交错数据：Common Crawl、OmniCorpus、MINT-1T，做相关性/知识密度过滤。
- OCR 合成数据：自然场景渲染文本 + HTML 渲染图。
- 文档数据：论文、报告、教科书（高知识密度、复杂版面）。
- 视频 Caption：WebVid、Vript、OpenVid + 详细重标注。
- **统一文档知识/OCR 学习范式**（§2.2.3）：对文档图像文本区域施加动态噪声腐蚀（低/中/高三档），要求模型重建原文，使模型在"清晰时做精确 OCR、重度遮挡时靠多模态上下文做知识推理"之间自适应切换；摆脱脆弱的外部 PDF 解析器，并避免过度增强导致的幻觉。

### 1.3 两阶段 SFT【论文】

来源：同上，§2.3.1

- **Stage 1：General SFT** —— 多样化高质量指令-回复数据激活预训练知识、对齐人类指令；混入 **10% 高质量纯文本数据**防止纯文本能力退化并提升训练稳定性。
- **Stage 2：Long-CoT & 3D-Resampler** —— (a) 引入 Long-CoT warm-up 指令（含反思、回溯等认知模式）支持深思考模式；(b) **在此阶段把 2D-Resampler 升级为 3D-Resampler**，并引入高帧率/长视频数据；由于架构统一，该升级只需少量高质量视频数据即可高效完成。SFT 数据要点：STEM 数据做视觉依赖性过滤 + 一致性校验 + 拒绝采样；Long-CoT 数据来自 OpenThoughts + 自建管线，**只保留难题**（"过滤简单题、聚焦难题是 Long-CoT warm-up 的关键"），并用 RLAIF-V 做 claim 级事实校验。

### 1.4 后训练 RL（混合快/深思考 + RLAIF-V）【论文】【官方】

来源：同上，§2.4；[官方 GitHub README / minicpm_v4dot5_zh.md](https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/minicpm_v4dot5_zh.md)；[RLAIF-V 仓库](https://github.com/RLHF-V/RLAIF-V)；[RLPR 仓库](https://github.com/OpenBMB/RLPR)

- **奖励体系**：简单短答案用规则校验（号称 98% reward 准确率）；复杂自然语言答案用 RLPR 的概率型奖励；另加人类偏好 RM 作为稠密信号，但 **RM 只评最终答案部分、不评长思维链**（避免 OOD 导致的不稳定）。总奖励 R = R_acc + R_format + R_rep + ½·标准化 R_rm。
- **混合 RL**：短思考/长思考两种模式由 prompt 控制（`enable_thinking`），SFT 初始化后，用 **GRPO** 联合优化，rollout 时随机交替两种模式；**移除了 KL 与 entropy 损失**以提升稳定性。消融显示混合策略用 70.5% 的 token 成本达到优于单一长思考模式的效果。
- **RLAIF-V（DPO 阶段，CVPR 2025 Highlights）**：同一生成条件下采样多个回复 → 将回复分解为可验证的原子 claim 并逐条校验 → 按 claim 级校验得分构建偏好对 → 用 **DPO** 训练，显著降低视觉幻觉（MMHal-Bench 上超 GPT-4o-latest）。4.5 将 RLAIF-V **扩展到了视频模态**。

---

## 2. Chat Template 与特殊 Token 设计【官方代码】

来源（官方模型仓库源码，经镜像逐字获取）：
- [processing_minicpmv.py（openbmb/MiniCPM-V-4_5）](https://huggingface.co/openbmb/MiniCPM-V-4_5/blob/main/processing_minicpmv.py)
- [image_processing_minicpmv.py](https://huggingface.co/openbmb/MiniCPM-V-4_5/blob/main/image_processing_minicpmv.py)
- [tokenizer_config.json](https://huggingface.co/openbmb/MiniCPM-V-4_5/blob/main/tokenizer_config.json)

### 2.1 Chat template

- MiniCPM-V-4.5 基于 **Qwen3-8B**，chat template 为 Qwen3 风格：`<|im_start|>role\n …content… <|im_end|>\n`；`eos_token = <|im_end|>`，`pad_token = <|endoftext|>`，`bos_token = <|im_start|>`。
- template 原生支持 **思考模式开关**：`add_generation_prompt` 时，若 `enable_thinking=False` 则注入 `<think>\n\n</think>\n\n`（空思考，即快思考）；`enable_thinking=True` 则注入 `<think>\n` 开启深思考。assistant 历史消息中 `</think>` 前的内容会被拆为 reasoning_content 处理。

### 2.2 视觉相关特殊 token（均已在词表中注册为 special token）

- `<image>` / `</image>`（im_start/im_end）：一张图（或视频组首帧）的**概览图**占位，中间填 64 个 `<unk>` 作为视觉特征占位符。
- `<slice>` / `</slice>`（slice_start/slice_end）：**高清切片**占位，每个切片同样 64 个 `<unk>`，按切片网格以换行符 `\n` 分行拼接，保留 2D 空间结构。
- `<image_id>` / `</image_id>`：多图场景的图片编号占位（`use_image_id=True` 时生效）。
- `<unk>`：视觉特征的**占位 token**，前向时由 `image_bound` 定位后被真实视觉 embedding 替换。
- 关键机制（`get_slice_image_placeholder`）：每张图的文本占位 = `<image>+<unk>*64+</image>` + 切片网格占位（`<slice>+<unk>*64+</slice>` × 网格数，行间 `\n`）。`image_feature_size=64`，即每个视觉单元（概览图/切片/视频包）固定 64 token。
- 注意：MiniCPM-V 的 `<image>` 不是 Qwen-VL 的 `<|vision_start|>` 体系；词表虽继承了 Qwen 的 `<|vision_start|>` 等 token，但实际视觉占位走 `<image>/<slice>/<unk>` 这一套自有体系。**训练数据里的 `<image>` 占位符必须与图片数量严格对应**（processor 中 `assert len(image_tags) == len(image_sizes[index])`，不匹配会直接报错）。

### 2.3 Processor 输出字段语义（forward 的直接输入）

`MiniCPMVProcessor.__call__` 最终返回（源码逐字确认）：

| 字段 | 语义 |
|---|---|
| `input_ids` / `attention_mask` | 左 padding 的文本 token 序列，视觉占位处为 `<unk>` |
| `pixel_values` | 按 patch 展开的视觉输入（`reshape_by_patch`，shape [3, patch_size, HW/patch_size]），嵌套 list 结构 |
| `image_sizes` | 每张图的原始 (W,H) |
| `tgt_sizes` | 每个切片/帧的**目标 patch 网格尺寸** (H/14, W/14)，供 Resampler 对 2D 位置编码做插值 |
| `image_bound` | **每个视觉单元在 input_ids 中的 (start, end) 区间**（im_start/slice_start 之后 1 位到 im_end/slice_end），forward 据此把视觉 embedding 原位替换 `<unk>` 占位 |
| `temporal_ids` | **视频时序分组 ID**：图像为 `[[-1], …]`；视频时，每个子 list 是一个"帧组/包"（如 `[[0,1,2,3,4,5],[6,7,…],…]`），同组帧（默认最多 6 帧）被 3D-Resampler **联合压缩成 64 token** |
| `skip_image_idx` | 视频模式下，**同一帧组内除首帧外**其余帧的 `<image>` 文本占位被置空（因其 token 已合并进首帧组），用于文本侧对齐 |

官方 README 对 temporal_ids 的说明（逐字）："The 3d-resampler compresses multiple frames into 64 tokens by introducing temporal_ids. … organize your video data into two corresponding sequences: `frames: List[Image]` 和 `temporal_ids: List[List[Int]]`"。来源：[OpenBMB/MiniCPM-V README – Chat with Video](https://github.com/OpenBMB/MiniCPM-V)。第三方推理框架（vLLM）实现中也消费同样的 `tgt_sizes`/`temporal_ids` 字段，可作旁证：[vLLM minicpmv 文档](https://docs.vllm.ai/en/v0.11.0/api/vllm/model_executor/models/minicpmv.html)【社区/框架侧确认】。

---

## 3. 官方微调文档要点

### 3.1 官方 LLaMA-Factory 最佳实践【官方】

来源：[docs/llamafactory_train_and_infer.md](https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/llamafactory_train_and_infer.md)

- 安装要求：`pip install -e ".[torch,metrics,deepspeed,minicpm_v]"`（LLaMA-Factory 内置 `minicpm_v` / `minicpm_o` template）。
- 数据格式：消息内嵌 `<image>` / `<video>` 占位 + 顶层 `images`/`videos` 路径列表（注意：此处 `<image>` 是 **LLaMA-Factory 数据层占位符**，会被其 mm_plugin 转成 MiniCPM-V 原生占位体系，不要与模型原生 `<image><unk>…</image>` 混淆）。
- 官方 LoRA 示例配置：`finetuning_type: lora`，**`lora_target: q_proj,v_proj`**（只打 LLM 注意力投影），`template: minicpm_o/minicpm_v`，`cutoff_len: 3072`，lr 1e-5。
- 官方全参示例配置：`finetuning_type: full` + **示例中 `freeze_vision_tower: true`**（冻结视觉塔）+ DeepSpeed ZeRO-2 + flash_attn fa2。
- **文档滞后说明**：该文档"Support Models"一节仍列 MiniCPM-V-4 / o-2_6 / V-2_6，未更新 4.5；但官方 News（2025.09.01）明确"MiniCPM-V 4.5 已被 LLaMA-Factory 官方支持"。两处信息以 News 为准【官方，存在文档版本不一致，已标注】。

### 3.2 官方自研微调脚本（transformers Trainer + DeepSpeed）【官方】

来源：[finetune/readme.md](https://github.com/OpenBMB/MiniCPM-V/blob/main/finetune/readme.md)（脚本面向 V-2.6/o-2.6/2.5/2.0，机制说明有参考价值）

- 数据必须提供 `<image>` 或 `<image_XX>` 占位符指明图像插入位置；无占位时图像默认放在对话最前。
- 显存与 token 预算：V2.6 单图 64 token；`max_slice_nums=9` 时一张 1344×1344 图约 64×(9+1) token；多图 SFT 建议 `MODEL_MAX_LENGTH=4096`，超限截断。
- **视觉模块训练开关**：`--tune_vision false` 可不训练视觉模块（VPM）以省显存——FAQ 语境暗示**默认可训练视觉模块**，是否训练由用户按显存/任务决定。
- LoRA 基于 peft 实现；建议 adapter 配置里用绝对路径，便于加载基座。
- 参考显存（A100 80G，ZeRO-3 + gradient checkpointing + CPU offload，max_len 2048, bs 1）：LoRA 约 13–14.4 GiB/卡，全参约 15.6–16 GiB/卡。
- **为何视觉模块常需参与训练**：官方文档未给出系统性论述（标注：官方未明说）；从预训练 recipe 可推断——视觉侧（ViT+Resampler）承载领域感知能力，领域偏移（如医疗/工业影像、特定视频帧率模式）时冻结视觉侧会限制上限；而 LoRA 默认只打 LLM 的 q/v_proj，本质假设"视觉理解已足够、只改指令/输出分布"。此为基于官方 recipe 的推断【论文+推断，非官方明文】。

---

## 4. 与微调实践相关的要点（直接影响 LoRA / 数据预处理 / 评测）

1. **视频数据的核心是 temporal_ids 分组**。3D-Resampler 把同一组的最多 6 帧压成 64 token；自研数据管线若绕过 LLaMA-Factory，必须自己构造 `frames + temporal_ids` 两组对齐序列，并保证文本侧只保留每组首帧的 `<image>` 占位（skip_image_idx 机制）。帧组划分（MAX_NUM_FRAMES、帧率）直接决定 token 数与时序分辨率。
2. **`<unk>`×64 占位 + image_bound 替换机制**意味着：训练样本的 input_ids 长度包含视觉 token；估算 `model_max_length`/cutoff_len 时必须把每张图 (切片数+1)×64、每段视频 组数×64 计入，否则静默截断会砍掉答案部分。
3. **LoRA target 选择**：官方示例只打 `q_proj,v_proj`。若任务需要改变视觉感知（如断裂检测这类细粒度视觉判断），纯 LLM LoRA 可能欠拟合视觉侧；可考虑 `tune_vision`（全量训练 ViT/Resampler）或把 Resampler 投影层纳入可训练参数——但这会显著增加显存与过拟合风险，需权衡。
4. **Chat template 一致性**：4.5 用 Qwen3 风格 `<|im_start|>` 模板 + `enable_thinking` 开关。SFT 数据若混入 `<think>` 块，需确认 template 的 reasoning 拆分逻辑与评测时 `enable_thinking` 设置一致，否则训练/评测分布不匹配。LLaMA-Factory 中必须用 `template: minicpm_v`（不是 qwen 系模板），因为视觉占位体系不同。
5. **`<image>` 占位符与媒体数量严格一一对应**（processor 内 assert），多图/视频样本构造时错位会直接训练报错或静默错配。
6. **冻结策略有官方先例**：预训练本身就大量用"选择性冻结"（Stage1 只训 Resampler、Stage2 冻结 LLM）；全参 SFT 官方示例默认冻结视觉塔。所以"LoRA + 冻结视觉"是官方认可的主流路径，"解冻视觉"是显存充足且视觉域偏移大时的进阶选项。
7. **评测口径**：RLAIF-V 的对齐目标说明官方高度重视幻觉抑制；做医疗类评测时，除准确率外建议补幻觉率/事实性指标，与官方对齐技术方向一致。

---

## 5. 信息冲突与不确定项

- **LLaMA-Factory 文档支持列表滞后**（未列 4.5）vs 官方 News 宣称 2025.09.01 起 LLaMA-Factory 支持 4.5 —— 以 News 与 LLaMA-Factory 主仓库 `minicpm_v` template 现状为准。【官方内部不一致，已标注】
- **"视觉模块是否应参与微调"官方无明文结论**；finetune/readme 的 FAQ 只给出 `--tune_vision false` 省显存的选项，未给出何时应开。上文第 3.2 末段与第 4.3 条为基于官方 recipe 的推断。【推断，非官方确认】
- 知乎专栏《[从零开始学MLLM-11] minicpm-v-4.5 模型结构解析》(https://zhuanlan.zhihu.com/p/1945055398575988742) 对 4.5 chat template 与数据流有逐行解读，但本次抓取被 403 拦截，仅获得摘要片段；其"4.5 数据处理流程与 2.6 基本一致"的说法与官方 processor 源码结构相符，可作旁证但未经全文核实。【社区解读，部分验证】
- LLaMA-Factory 侧视频抽帧参数（`video_fps`、`video_maxlen` 等）属于 LLaMA-Factory 自身数据参数，未在本次抓取的官方文档中逐字确认，建议以训练机上实际安装的 LLaMA-Factory 版本源码为准。【待本地验证】
