# 调研主题：范围 C —— MiniCPM-V-4.5 的语言模型 backbone（Qwen3）架构与 MiniCPM 家族自研 LLM 训练原理

> 调研员：MiniCPM调研员 ｜ 调研日期：2026-07-25
> 可信度标注约定：【官方】= OpenBMB/清华官方渠道（GitHub、HF 模型卡、arXiv 论文、官方博客）；【论文】= arXiv 论文；【社区】= 社区解读/媒体转载；【推测】= 无官方依据的分析判断。

---

## 1. MiniCPM-V-4.5 的 LLM backbone：Qwen3-8B

### 1.1 backbone 选型事实

- MiniCPM-V 4.5 基于 **SigLIP2-400M 视觉编码器 + Qwen3-8B 语言模型**构建，总参数量约 8B（官方口径 8.7B）。【官方】
  - 来源：https://github.com/OpenBMB/MiniCPM-V （GitHub 官方 README，Model Zoo 与新闻区）
  - 来源：https://www.kdnuggets.com/top-7-open-source-ocr-models （转述官方模型卡）
  - 来源：http://mp.weixin.qq.com/s?__biz=Mzg4MTE3MDAxOQ==&mid=2247499182&idx=4&sn=6904f812cefc2232924502814a3fc24d 【社区转载】
- 技术报告（arXiv:2509.18154）将架构描述为三段式：轻量视觉编码器（LLaVA-UHD 切图策略）→ 统一 3D-Resampler → LLM decoder；报告正文未在架构节强调 backbone 名称，但 LLM decoder 即 Qwen3-8B。【论文】
  - 来源：https://arxiv.org/html/2509.18154v1

### 1.2 Qwen3-8B 架构参数（来自官方 config.json 的社区转录，与官方发布一致）

| 参数 | 值 | 说明 |
|---|---|---|
| model_type / 架构 | qwen3 / Qwen3ForCausalLM | 标准 decoder-only Transformer |
| num_hidden_layers | 36 | Decoder 层数 |
| hidden_size | 4096 | 隐藏维度 |
| num_attention_heads | 32 | Q 头数 |
| num_key_value_heads | 8 | KV 头数 → **GQA，分组比 4:1** |
| head_dim | 128 | 每头维度（32×128=4096，独立定义） |
| intermediate_size | 12288 | MLP 中间维度（SwiGLU，激活 silu） |
| vocab_size | 151936 | 词表（Qwen 系 BPE tokenizer） |
| max_position_embeddings | 32768（原生） | 官方称可通过 YaRN 扩展到 131072 |
| rope_theta | 1,000,000 | RoPE 基频 |
| 归一化 | RMSNorm (eps 1e-6) + **QK-Norm** | Qwen3 系列特征：Q/K 上加 RMSNorm 稳定训练 |
| attention_bias | False | QKV 投影无 bias |

来源（社区对官方 config.json 的转录/解析，数值与官方一致）：
- https://hpc101.zjusct.io/lab/Lab5-TinyLLM/ （浙大 HPC101 实验讲义，列出 36 层/4096/32头/8KV头/12288/151936）
- https://blog.csdn.net/gitblog_00722/article/details/157346217 （config.json 逐项解析）
- https://github.com/vllm-project/vllm/issues/23141 （实际部署 config 实例）

注：Qwen3-8B 官方模型卡（Qwen/Qwen3-8B）因网络原因本次未能直接抓取，以上数值建议以基座权重目录下 `config.json` 为最终准绳（本地权重中可直接核对）。

### 1.3 Qwen3 的混合推理特性

Qwen3 系列原生支持 think / non-think 双模式（通过 chat template 的 enable_thinking 控制）。MiniCPM-V 4.5 的"短推理/长推理混合模式"（hybrid reasoning，prompt 控制切换 + 混合 RL 训练）与此一脉相承。【论文】
- 来源：https://arxiv.org/html/2509.18154v1 （§2.4.3 Hybrid Reinforcement Learning：模式由 prompt 控制，SFT 初始化两种行为，RL 阶段 rollout 随机交替两种模式，GRPO 优化）

---

## 2. MiniCPM-V 系列 backbone 选型历史与"为何用 Qwen"

### 2.1 选型历史（均为官方发布口径）

| 版本 | LLM backbone | 总参数 | 来源 |
|---|---|---|---|
| MiniCPM-V 2.0 (2024.02/04) | MiniCPM-2.4B（自研） | ~3B | https://github.com/OpenBMB/MiniCPM-V （News 区） |
| MiniCPM-Llama3-V 2.5 (2024.05) | Llama3-8B-Instruct | ~9B | 同上 |
| MiniCPM-V 2.6 (2024.08) | Qwen2-7B | ~8B | 同上 |
| MiniCPM-V 4.0 (2025.08) | **MiniCPM4-3B（自研）** | 4.1B | https://www.oschina.net/news/364538 （官方发布转载） |
| MiniCPM-o 2.6 (2025.01) | Qwen2-7B + Whisper-medium 等 | ~9B | GitHub README |
| MiniCPM-V 4.5 (2025.08) | **Qwen3-8B** | ~8.7B | GitHub README / 技术报告 |
| MiniCPM-o 4.5 (2026.02) | Qwen3-8B + Whisper-medium + CosyVoice2 | ~9B | GitHub README |
| MiniCPM-V 4.6 (2026.05) | Qwen3.5-0.8B | 1.3B | GitHub README |

### 2.2 为何 4.5 改用 Qwen3-8B（而非自研 MiniCPM4-8B）

- **未检索到 OpenBMB 对该切换的官方解释**。【推测】以下为基于公开信息的分析：
  1. MiniCPM-V 的选型历来是"目标参数规模内选最强、生态最好的开放 LLM"，并不绑定自研 LLM（2.5 用 Llama3、2.6 用 Qwen2 即为先例）。
  2. Qwen3-8B（2025.04 发布）在 8B 档位综合能力（尤其推理、混合 think 模式）是当时开源最强之一，且其 dense attention 架构被 vLLM / llama.cpp / LLaMA-Factory 等主流框架原生支持——这与 MiniCPM-V 4.5 发布后一个月（2025.09.01）即被 llama.cpp、vLLM、LLaMA-Factory 官方支持的事实相符（GitHub News 区）。
  3. 自研 MiniCPM4-8B 的核心卖点 InfLLM v2 稀疏注意力需要专用 CUDA kernel（infllmv2_cuda_impl）和推理系统 CPM.cu 支撑，生态兼容性差；把它放进一个面向端侧部署、强调框架兼容的 MLLM 会显著抬高适配成本。V 4.0 用的是 MiniCPM4-**3B**（小模型档位稀疏注意力适配压力较小），4.5 冲击 8B 旗舰性能时选择了 dense 的 Qwen3-8B。
  - 旁证：https://github.com/openbmb/minicpm （MiniCPM4.1-8B 需在 config 中加 sparse_config 启用 InfLLM v2）；https://modelscope.cn/datasets/OpenBMB/InfLLM-V2-data-5B （InfLLM v2 需要专门 CUDA kernel）

---

## 3. MiniCPM 家族自研 LLM 核心技术（背景知识）

### 3.1 MiniCPM 1.0（arXiv:2404.06395，2024.04）——WSD 学习率调度器

- 发布 1.2B 与 2.4B（非嵌入参数）两个 SLM，主张"用小模型做规模化训练策略探索"。【论文】
  - 来源：https://arxiv.org/abs/2404.06395 ；https://arxiv.org/html/2404.06395v1
- **WSD（Warmup-Stable-Decay）调度器**：训练分三段——warmup 线性升至峰值 → stable 段保持峰值学习率跑绝大部分步数 → decay 段快速衰减。相对 cosine 的优势：不需要预先确定总步数、stable 段任意 checkpoint 都可继续训练（continual training 友好）、中间 ckpt 质量高。【论文】
  - 数学形式与综述引用：https://arxiv.org/html/2510.06826v1 （Mid-Training Survey 对 WSD 的复述）
- **关键现象**：decay 阶段（约占总 token 的 ~10%）loss 会出现急剧下降（"断崖式"）；在 decay 段混入高质量数据（SFT 风格数据、知识密集数据）收益最大。由此衍生"两阶段数据策略"：stable 段用大规模普通预训练数据，decay 段用高质量数据。【论文】
  - 来源：https://arxiv.org/html/2404.06395v1 ；https://arxiv.org/html/2510.06826v1
- **模型风洞（Model Wind Tunnel）方法论**：在小模型上做批量超参/scaling 实验（含 batch size 标定：损失不再随 batch 增大而显著下降的最优 batch size），把结论外推到大模型，降低试错成本。该思想后来在 MiniCPM4 中升级为 ModelTunnel v2。【论文】
  - 来源：https://arxiv.org/abs/2404.06395
- 影响力佐证：WSD 后被多家采用（如 arXiv:2407.01178 Memory3、arXiv:2408.13359 Power Scheduler 均以 MiniCPM 的 WSD 为基线）。【社区/论文】

### 3.2 MiniCPM4（arXiv:2506.07900，2025.06）——端侧 8B 的四位一体效率创新

官方论文从四个维度做效率创新：【论文】来源：https://arxiv.org/abs/2506.07900 ；https://arxiv.org/pdf/2506.07900

1. **模型架构：InfLLM v2 可训练稀疏注意力**
   - 同时加速长上下文 prefill 与 decode；块级稀疏（block top-k），注意力稀疏度约 81%；无需像 NSA 那样引入大量额外参数，兼容"短文本预训练→长文本继续训练"的标准流程（dense→sparse 可切换）。
   - 后续单独成文：InfLLM-V2（arXiv:2509.24663），MiniCPM4 / MiniCPM4.1-8B 是首个开源的原生稀疏注意力模型。
   - 来源：https://arxiv.org/abs/2509.24663 ；https://modelscope.cn/datasets/OpenBMB/InfLLM-V2-data-5B ；https://eu.36kr.com/en/p/3501893279014024 【社区】
2. **训练数据：UltraClean + UltraChat v2**
   - UltraClean：高效预训练数据过滤/生成策略（产出 UltraFineWeb）；UltraChat v2：SFT 数据集。仅凭 **8T token** 训练即达到可比性能——官方称相当 Qwen3-8B 训练数据量的 22%，且在端侧处理 128K 长文档时速度快 7 倍。
   - 来源：https://arxiv.org/pdf/2506.07900
3. **训练算法：ModelTunnel v2 + 训练工程**
   - ModelTunnel v2：自动化预训练超参搜索，结合 scaling law、ScalingBench（loss→下游准确率的 sigmoid 映射指标）与 μP（ maximal update parameterization，小模型超参迁移到大模型）。
   - 训练工程：多 token 预测（MTP）训练目标（兼顾投机采样接受长度）、FP8 混合精度训练。
   - 后训练：chunk-wise rollout（长轨迹分块并行 RL、负载均衡）、BitCPM4。
   - 来源：https://arxiv.org/pdf/2506.07900 ；http://emergentmind.com/topics/modeltunnel-v2 【社区解读】
4. **量化：BitCPM4（三值 QAT）**
   - 两阶段量化感知训练：用高精度预训练模型初始化量化阶段，QAT 成本降至常规方法的 1/10 token；将 MiniCPM4 适配为三值（ternary）版本 BitCPM4，面向极端资源受限设备，实现 90% 位宽压缩。
   - 来源：https://arxiv.org/pdf/2506.07900 ；https://modelscope.cn/models/JunHowie/MiniCPM4-8B 【模型卡转载】
5. **推理系统：CPM.cu**（端侧推理框架，集成稀疏注意力、投机采样等）。
   - 来源：https://arxiv.org/abs/2506.07900

### 3.3 设计理念小结（跨代一致性）

- 一以贯之的路线：**端侧高效 + 训练策略科学化**（风洞/ModelTunnel 超参搜索、WSD 数据-学习率协同、数据质量优先于数量）。V 系列（多模态）则务实选型：目标尺寸内最强的开放 LLM + 自研高效视觉侧（LLaVA-UHD 切图、2D/3D-Resampler 高倍压缩）。【官方+推测】
- MiniCPM-V 4.5 技术报告本身也体现了这种传承：预训练 Stage 3 明确采用 **WSD 调度器**，并在 decay 段逐步加入高质量指令与知识密集数据（§2.2.1）。【论文】https://arxiv.org/html/2509.18154v1

---

## 4. 与微调实践相关的要点（LoRA / 数据预处理 / 评测）

1. **LoRA 目标模块**：Qwen3-8B 是 GQA（32Q/8KV），`k_proj`/`v_proj` 输出维度只有 q_proj 的 1/4（8×128=1024 vs 4096）。LoRA 建议覆盖 `q_proj,k_proj,v_proj,o_proj`（甚至 `gate/up/down_proj`，LLaMA-Factory 的 `all-linear`），冻结 embed_tokens/lm_head（词表 151936 很大，训练它们开销巨大）。若只调 `q,v`，会漏掉 o_proj 与 MLP，对结构化 JSON 输出（has_fracture/type/location 等字段）的格式对齐不利。
2. **backbone 是 dense attention**：V 4.5 用的是 Qwen3-8B 稠密注意力，**不含** InfLLM v2 稀疏注意力，因此标准 FlashAttention-2 / SDPA 训练路径即可，无需 OpenBMB 专用 kernel；这也是 LLaMA-Factory/vLLM 能原生支持的原因。【官方，GitHub News 2025.09.01】
3. **序列长度预算**：3D-Resampler 把 6 帧 448×448 压成 64 个视觉 token（每帧约 21.3 token，96× 压缩）；官方最多采样 1080 帧 @10fps。训练视频样本时按 `⌈帧数/6⌉×64 + 文本 token` 估算序列长度，LLaMA-Factory 的 `cutoff_len`、抽帧数（video_fps / nframes）要与之匹配；Qwen3 原生 RoPE 位置上限 32768，超出需 YaRN（评测长视频时注意）。【论文，arXiv:2509.18154 §2.1.1】
4. **推理模式与数据模板**：模型支持短/长推理两种模式，由 prompt 控制；SFT 数据若混入 `<think>...</think>` 风格长链样本，会同时影响输出格式与长度分布。做"断裂检测 JSON 输出"这类任务时，建议统一用短推理（non-think）模板，并在评测 prompt 与训练模板间保持严格一致，否则 has_fracture 等字段的 JSON 合法率会被模式错配拖累。【论文，§2.3/§2.4.3】
5. **WSD 的启示（间接）**：基座预训练"decay 段喂高质量数据"的经验同样适用于 SFT 实践——把最高质量/最贴近验收口径的样本放在训练后段（或提高其采样权重）通常有效；但 LoRA SFT 本身用 LLaMA-Factory 默认 cosine/线性调度即可，无需复刻 WSD。【论文+推测】
6. **QK-Norm 与训练稳定性**：Qwen3 的 QK-Norm 使注意力 logits 更稳定，LoRA 微调时可使用相对常规稍高的学习率（社区常用 1e-4 量级）而不易发散；但若观察到 loss 尖峰，优先降 LR 而非改 warmup。【社区推测，供参考】
7. **评测对齐**：技术报告显示官方在 OpenCompass 上对 5 个 benchmark 用长推理模式、其余用短推理模式，且 reasoning 模式报 3 次平均——评测自家微调模型时也应固定模式+多次采样取均值，避免把采样方差当作效果差异。【论文，§3.1】
8. **tokenizer/词表**：vocab 151936 的 Qwen BPE tokenizer；视频/图像的特殊占位 token（如 `<|video_pad|>` 等，具体以 `processor`/`chat_template` 为准）在预处理时必须走官方 processor，手工拼模板极易错位。【官方代码库惯例，需以权重目录 chat_template 核对】

---

## 5. 未能确认 / 存在冲突的信息

- **官方未解释 4.5 从 MiniCPM4-3B（V 4.0）切换到 Qwen3-8B 的原因**，§2.2 的三条理由均为分析推测。
- MiniCPM4-8B 的精确层数/hidden size 本次未取得一手 config（论文以技术点为主），如需精确参数建议直接读 openbmb/MiniCPM4-8B 权重的 config.json。
- HuggingFace 模型卡 openbmb/MiniCPM-V-4_5 本次因网络错误未能直接抓取，模型卡级细节（如 license、int4 量化版信息）以 GitHub README 与技术报告为准。
- 部分社区文章（KDnuggets、微信公众号、36kr）数据为二手转述，已在文中标注【社区】。
