# 8B/9B 开源视频多模态基座模型综合对比与选型调研

**定位：**本文是纯模型选型与视频输入机制专题调研，聚焦用户已确认的 3 款核心模型（MiniCPM-V-4.5、Qwen3-VL-8B、InternVL3-8B）及 Hugging Face / ModelScope 上同规模（7B–9B）主流开源视频多模态模型的横向对比，输出首轮基座模型摸底测评的候选梯队与跨模型输入适配要点。模型输入 8 帧抽帧公式选型另见 [model-input-frame-sampling-options.md](model-input-frame-sampling-options.md)，训练机前置只读体检与代码适配规划另见 [eval-preflight-and-adapter-plan.md](eval-preflight-and-adapter-plan.md)。

**调研日期：** 2026-11-24。

**基准与证据边界：**

- **仓内核对基线**：`feat/tensileagent-finetune` 提交 `07d9c8e6030f62ac604a186b777ab1b7dc280e42`（含已合入的 PR #18 与 PR #21；第 2 批子视频清单 [data/sub_video/manifest.json](../../data/sub_video/manifest.json) 共 1,633 条候选、110 个源，SHA-256 `c70686630c8fa0277305cc25a09821bc04ab853f6ce8a6ac3ca795998c08ac0f`）。
- **只调研、不授权**：本文不代表最终冻结对比模型名单，不授权下载权重或启动真实评测／训练。
- **证据分级纪律**：仓内已核实事实标明具体文件路径与 `DF-*`／`DEC-*` 编号；所有来自 Hugging Face / ModelScope / 官方模型卡 / vLLM / LLaMA-Factory 公开资料的模型规格、许可证、输入机制与单卡 24 GB 显存估算均统一标注 **`[外部文档/待训练机核实]`**，实测前不得当作训练机已验证结论。

---

## 1. 选型范围与用户已确认基线

承接 [TODO §2 后续前置工作](../TODO.md#后续前置工作) 与 [基座模型测评方案](../eval/base-model-eval-plan.md)，结合用户对本轮基座模型选型的明确确认，本调研锁定 **7B–9B 同规模开源视频多模态模型**（适配单卡 24 GB 级训练机与后续 LoRA/SFT 微调）：

1. **已确认的 3 款核心模型**：
   - **MiniCPM-V-4.5**（`openbmb/MiniCPM-V-4_5`）：仓内既定基座（[DEC-003](../decisions/0003-five-label-eval-scope.md) 第 9 条、`DF-044`），已有固定官方 processor 受控验证记录（[minicpm-video-loading.md](minicpm-video-loading.md) §5.3）。
   - **Qwen3-VL-8B**（`Qwen/Qwen3-VL-8B-Instruct` 与 `Qwen/Qwen3-VL-8B-Thinking`）：按用户确认，**不采用 Qwen2.5-VL，直接采用 Qwen3-VL**。
   - **InternVL3-8B**（`OpenGVLab/InternVL3-8B` / `OpenGVLab/InternVL3-8B-hf`）：用户已确认纳入，同时对照其同系演进标准版 **InternVL3.5-8B**（`OpenGVLab/InternVL3_5-8B` / `OpenGVLab/InternVL3_5-8B-HF`；注：标准版仍沿用动态高分辨率切块而不含 ViR，ViR 仅属于另行发布的 **InternVL3.5-Flash** 变体 `[外部文档/待训练机核实]`）。
2. **Hugging Face & ModelScope 同规模（7B–9B）横向对比候选（4 款）**：
   - **GLM-4.1V-9B-Thinking**（`zai-org/GLM-4.1V-9B-Thinking` / `THUDM/GLM-4.1V-9B-Thinking`）
   - **Ovis2.5-9B**（`AIDC-AI/Ovis2.5-9B`）
   - **Keye-VL-1.5-8B**（`Kwai-Keye/Keye-VL-1_5-8B`）
   - **MiMo-VL-7B-RL**（`XiaomiMiMo/MiMo-VL-7B-RL`）

以上共覆盖 **7 个模型家族（8 个主对照条目）**，兼顾通用视觉感知、细粒度原生分辨率、视频专精（Slow-Fast）与视觉思维链（Thinking）四条主流技术路线。

---

## 2. 候选模型身份、平台分布与生态总表

> 下表除 MiniCPM-V-4.5 的仓内路径与分片字节（`DF-044`）外，其余仓库 ID、许可证、架构与单卡 24 GB 显存可行性均属 **`[外部文档/待训练机核实]`**；正式下载与商业使用前须以目标仓库实际 `LICENSE` 与 `config.json` 为准。

| 分类 | 模型名称 | Hugging Face 仓库 ID | ModelScope 可得性 | 参数规模 | 许可证 | 推理生态（vLLM / `transformers`） | 微调生态（LLaMA-Factory / ms-swift） | 单卡 24 GB（4090 级）BF16 推理可行性 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **已确认核心** | **MiniCPM-V-4.5** | `openbmb/MiniCPM-V-4_5` | 有官方镜像 `OpenBMB/MiniCPM-V-4_5` `[外部文档/待训练机核实]` | ~8B（仓内 `DF-044` 实测 4 分片共 17,391,890,184 B、bf16、36 层） | 代码 Apache-2.0；权重 MiniCPM 社区协议（学术免费，商用需登记备案） `[外部文档/待训练机核实]` | `transformers`（`trust_remote_code=True`，仓内已有固定处理器验证）；vLLM 支持（`--trust-remote-code`） `[外部文档/待训练机核实]` | LLaMA-Factory 支持（旧仓已有配置线索，见 [minicpm-video-loading.md](minicpm-video-loading.md) §2.1）；ms-swift 支持 `[外部文档/待训练机核实]` | **高**（权重 ~16.2 GiB，8 帧受控切片单卡可行；旧链路亦保留 4-bit NF4 回退，见 [inference-entry.md](../eval/inference-entry.md) §7；实测峰值`待训练机实测核对`） |
| **已确认核心** | **Qwen3-VL-8B-Instruct** / **Thinking** | `Qwen/Qwen3-VL-8B-Instruct`；`Qwen/Qwen3-VL-8B-Thinking` | 有官方主仓（含 BF16 与 FP8 变体） `[外部文档/待训练机核实]` | ~8B `[外部文档/待训练机核实]` | **Apache-2.0** `[外部文档/待训练机核实]` | `transformers` 原生 `Qwen3VLForConditionalGeneration`；vLLM 一等原生支持（含 `--media-io-kwargs` / `--mm-processor-kwargs`） `[外部文档/待训练机核实]` | LLaMA-Factory 与 ms-swift 均已跟进支持 `[外部文档/待训练机核实]` | **高**（BF16 权重约 16–17 GB，8 帧 + 受控 `max_pixels` 单卡可行；另有官方 FP8 变体可进一步降显存 `[外部文档/待训练机核实]`） |
| **已确认核心** | **InternVL3-8B** | `OpenGVLab/InternVL3-8B`；`OpenGVLab/InternVL3-8B-hf` | 有官方镜像 `[外部文档/待训练机核实]` | ~8B `[外部文档/待训练机核实]` | 代码 MIT / 模型按基座遵循 **Apache-2.0**（以仓内模型卡为准） `[外部文档/待训练机核实]` | `transformers`（`-hf` 版标准接口或原生 `trust_remote_code=True`）；vLLM（≥0.10）一等支持 `[外部文档/待训练机核实]` | LLaMA-Factory（支持 `-hf` 路径）与 ms-swift 均原生支持 `[外部文档/待训练机核实]` | **高**（BF16 权重约 16–17 GB；需限制动态切片 `max_num` 与 `--limit-mm-per-prompt` 防 8 帧 prefill OOM `[外部文档/待训练机核实]`） |
| **同系演进对照** | **InternVL3.5-8B**（标准版） | `OpenGVLab/InternVL3_5-8B`；`OpenGVLab/InternVL3_5-8B-HF` | 有官方镜像 `[外部文档/待训练机核实]` | ~8B `[外部文档/待训练机核实]` | 同 InternVL3（代码 MIT / 模型 Apache-2.0，以模型卡为准） `[外部文档/待训练机核实]` | `transformers` 与 vLLM（≥0.10，`--trust-remote-code`）原生支持；主升级为 Cascade RL 与推理/Thinking 对齐（**不含 ViR**，ViR 仅属 **InternVL3.5-Flash** 变体） `[外部文档/待训练机核实]` | LLaMA-Factory 与 ms-swift 均已接入 `[外部文档/待训练机核实]` | **高**（BF16 权重约 16–17 GB；标准版仍按 448×448 动态切块、每 patch 256 visual tokens、**无 ViR 压缩收益**，显存约束与 InternVL3-8B 同级，同样需控 `max_num` 与 `--limit-mm-per-prompt` `[外部文档/待训练机核实]`） |
| **横向候选** | **GLM-4.1V-9B-Thinking** | `zai-org/GLM-4.1V-9B-Thinking`（同 `THUDM/GLM-4.1V-9B-Thinking`） | 有官方镜像 `[外部文档/待训练机核实]` | ~9B `[外部文档/待训练机核实]` | **MIT** `[外部文档/待训练机核实]` | `transformers` 与 vLLM 支持；vLLM `--reasoning-parser glm45` **仅剥离 `</think>` 前思考段，仍保留 `<answer>...</answer>` 包裹标签**（非 special token，`skip_special_tokens=True` 不移除） `[外部文档/待训练机核实]` | LLaMA-Factory 内置支持（`<image>` + `<think>...</think><answer>...</answer>` 模板） `[外部文档/待训练机核实]` | **中偏高**（9B BF16 权重约 18–19 GB，在 24 GB 卡上 KV cache 余量较 8B 更紧，且长思维链增加生成 KV 占用 `[外部文档/待训练机核实]`） |
| **横向候选** | **Ovis2.5-9B** | `AIDC-AI/Ovis2.5-9B` | 有官方镜像 `[外部文档/待训练机核实]` | ~9B `[外部文档/待训练机核实]` | **Apache-2.0** `[外部文档/待训练机核实]` | `transformers`（`trust_remote_code=True`）与 vLLM 原生支持（支持 `enable_thinking` / `thinking_budget` 开关） `[外部文档/待训练机核实]` | 生态以官方脚本与 ms-swift 为主；LLaMA-Factory 适配成熟度需在目标版本核实 `[外部文档/待训练机核实]` | **中偏高**（9B BF16 权重约 18–19 GB，原生分辨率输入若不设像素上限可能拉高 prefill 显存 `[外部文档/待训练机核实]`） |
| **横向候选** | **Keye-VL-1.5-8B** | `Kwai-Keye/Keye-VL-1_5-8B` | 有官方镜像 `[外部文档/待训练机核实]` | ~8B `[外部文档/待训练机核实]` | **Apache-2.0** `[外部文档/待训练机核实]` | `transformers` 与 vLLM 原生支持（`KeyeVL1_5ForConditionalGeneration`，128K 上下文） `[外部文档/待训练机核实]` | ms-swift 原生支持；LLaMA-Factory 支持度需按具体版本核实 `[外部文档/待训练机核实]` | **高**（8B BF16 约 16–17 GB，Slow-Fast 策略对静态帧降像素分配，8 帧输入显存友好 `[外部文档/待训练机核实]`） |
| **横向候选** | **MiMo-VL-7B-RL** | `XiaomiMiMo/MiMo-VL-7B-RL`（含 `MiMo-VL-7B-RL-2508`） | 有官方镜像 `[外部文档/待训练机核实]` | ~7B `[外部文档/待训练机核实]` | **MIT** `[外部文档/待训练机核实]` | 复用通用多模态条件生成架构，vLLM 与 `transformers` 开箱即用 `[外部文档/待训练机核实]` | LLaMA-Factory 与 ms-swift 均友好支持 `[外部文档/待训练机核实]` | **很高**（7B BF16 约 14–15 GB，单卡 24 GB 显存余量最大、吞吐较快 `[外部文档/待训练机核实]`） |

---

## 3. 拉伸试验五类标签场景专项输入机制对照

本项目的拉伸视频片段具有四个鲜明工程特征（仓内实测，见 [eval-subset.md](../eval/eval-subset.md) 与 [data/sub_video/manifest.json](../../data/sub_video/manifest.json)）：
1. **画幅两极分化且小图占比高**：第 2 批 1,633 条候选中 `w_le_200`（宽 ≤ 200，最小 60×80）占 **881 条（53.9%）**、`w_200_400` 占 **448 条（27.4%）**、`w_gt_400`（最大 924×1232）占 **304 条（18.6%）**；
2. **细粒度局部与时序并重**：需同时辨认全局状态跃迁（`未断裂 / 发生断裂 / 已断裂`）、夹具相对位置（`标距内 / 标距外非根部 / 夹持根部`）与微小局部现象（`颈缩 / 开裂 / 界面分离 / 断后脱夹 / 未夹紧`）；
3. **固定 8 帧 + 强血缘绑定**：按 `DF-044` 统一 8 帧，且为满足 [DEC-005](../decisions/0005-frame-correspondence-evidence.md) 按次抽帧取证，**必须优先将 `frames.py` 预抽好的 8 张 L3 PNG 列表送入模型**（绑定 `five-label-input-record/3` 的 `clip_to_model_input`），避免把 MP4 交给服务端二次抽帧导致帧号漂移；
4. **严格中文嵌套 JSON 契约**：现行 [five_label_v2.txt](../../script/five_label_eval/prompts/five_label_v2.txt) 要求只输出单个 5 顶层键、11 叶字段中文 JSON，禁止围栏与前后缀解释，[score.py](../../script/five_label_eval/score.py) 不做字面量归一化（[output-contract.md](../eval/output-contract.md) §1–§2）。

### 3.1 七家族视频输入机制与场景适配对照表

| 模型 | 8 帧输入方式与 `clip_to_model_input` 兼容性 | 分辨率/切片机制与细粒度形变适配 | 时序位置编码与 3b 顺序对照兼容 | 严格 11 叶字段中文 JSON 稳定性与输出风险 |
| --- | --- | --- | --- | --- |
| **MiniCPM-V-4.5**（已确认基座） | **高（原生 frames list）**：`transformers` 与旧评测加载器均直接接收 8 张 RGB PIL 列表，与 `clip_to_model_input` 零漂移绑定；vLLM 可走 8 张有序 `image_url`（但标准 OpenAI 载荷不直接暴露自定义 `temporal_ids`） `[仓内已核实 + 外部文档/待训练机核实]` | 4.5 processor 目标面积约 `448²`、宽高对齐 14 倍数，受 `max_slice_nums`（1 或 2）控制；旧链路前置 `max_pixels=65,536`（256²）规整会压缩大画幅细节（[minicpm-video-loading.md](minicpm-video-loading.md) §2、§4） | **3D-Resampler + 可选 `temporal_ids`**（0.1 s 量化整数分组）。不传（`None`）时回填 `[-1]`（零时间嵌入，顺序仍由 `image_bound` 保留，已实跑验证：`DF-016`）；3b 顺序对照须关闭或重写时间编号防泄露 | 8B 基座无约束解码可能出现围栏或漏叶项 `[推测/待训练机实测核对]`；无原生 `<think>` 前缀干扰，直接适配 `score.py` 提取器 |
| **Qwen3-VL-8B-Instruct**（已确认核心） | **高（frames list / 多图 `image_url`）**：vLLM OpenAI API 传 8 张 `image_url` 可严格锁死 L3 8 帧；`transformers` 亦可直接传预抽帧列表进入视频通道（注意 `image_url` 多图路径与原生 `video` 时空路径不同，须固定并记入运行配置） `[外部文档/待训练机核实]` | 原生动态分辨率 + **DeepStack**（多层 ViT 视觉特征注入 LLM），对细小裂缝、颈缩轮廓与夹具边缘的细节保留能力在同规模模型中属第一梯队；支持 `max_pixels` 显式控 token 预算 `[外部文档/待训练机核实]` | **Interleaved-MRoPE**（交错三维时空旋转位置编码），原生为视频时序设计；多图 `image_url` 路径可在文本中附每帧相对 `pts_seconds`，3b 对照时去掉时间戳即可防泄露 `[外部文档/待训练机核实]` | **Instruct 变体中文指令遵循与嵌套 JSON 稳定性通常极佳**，无 `<think>` 推理链污染 `raw_output`，最贴合 `five_label_v2.txt` 严格单对象输出要求 `[外部文档/待训练机核实]` |
| **Qwen3-VL-8B-Thinking**（已确认核心同系） | 同 Qwen3-VL-8B-Instruct `[外部文档/待训练机核实]` | 同 Qwen3-VL-8B-Instruct（DeepStack + 动态分辨率） `[外部文档/待训练机核实]` | 同 Qwen3-VL-8B-Instruct（Interleaved-MRoPE） `[外部文档/待训练机核实]` | **需特别留意输出解析风险**：默认输出长思维链推理过程，若原样进入 `raw_output` 易触发 `surrounding_text_or_fence` 或因思考段中出现草稿 JSON 导致 `extraction_failed`，且单条 token 耗时显著拉长（见 §3.2） `[外部文档/待训练机核实]` |
| **InternVL3-8B**（已确认核心） | **高（8 张多图序列）**：常规多帧输入为 `Frame1..Frame8` 对应 8 张预抽 L3 PNG（`image_url` 或 `transformers` 多图），与 `clip_to_model_input` 一一对应；须避免直接传 MP4 给 `num_frames=8` 导致二次解码漂移 `[外部文档/待训练机核实]` | 固定 `448×448` 动态分块（dynamic tiling），由 `max_num` / `max_dynamic_patch` 控制每帧切片上限（8 帧场景常设 `max_num=1` 或 `2` 控显存）；注意对 `w_le_200`（60×80）处理器内部会插值到 448×448，不代表获得额外像素信息 `[外部文档/待训练机核实]` | 结合 **V2PE**（可变视觉位置编码）+ 显式帧序/时间戳文本前缀；顺序完全由帧列表排列决定，3b 对照易控 `[外部文档/待训练机核实]` | 工业与通用中文视觉理解扎实，非 Thinking 模式直接输出 JSON，与 `score.py` 兼容性好 `[外部文档/待训练机核实]` |
| **InternVL3.5-8B**（标准版，同系演进对照） | 同 InternVL3-8B（8 张多图列表保持 `clip_to_model_input` 绑定） `[外部文档/待训练机核实]` | 标准版 `OpenGVLab/InternVL3_5-8B` / `-HF` **沿用 448×448 动态高分辨率切块（每 patch 256 visual tokens，不含 ViR 压缩）**，主要升级在于 **Cascade RL** 与推理对齐；若后续要专项检验 ViR（Visual Resolution Router）视觉 token 压缩对微小开裂/颈缩的影响，须改选明确的 **InternVL3.5-Flash** checkpoint `[外部文档/待训练机核实]` | 同 InternVL3 族，支持交错多帧/视频与长上下文 `[外部文档/待训练机核实]` | 经 Cascade RL 对齐后推理表现较 InternVL3-8B 增强；须确认默认聊天模板是否触发思考块并固定非思考/标准 JSON 模式 `[外部文档/待训练机核实]` |
| **GLM-4.1V-9B-Thinking**（横向候选） | **高（8 张多图列表）**：支持多图 `<image>` 序列输入，兼容 L3 预抽帧；vLLM 传 `video_url` 时需避开自动二次采样 `[外部文档/待训练机核实]` | 动态分辨率编码，视觉推理与空间关系判别强 `[外部文档/待训练机核实]` | 支持多帧视频与图文交错时序理解 `[外部文档/待训练机核实]` | **原生强绑定 `<think>...</think><answer>...</answer>` 范式，存在两层格式冲突**：vLLM `--reasoning-parser glm45` 仅剥离 `</think>` 前内容，**仍会保留 `<answer>...</answer>` 包裹标签**（`tokenizer_config.json` 将其标为非 special token，`skip_special_tokens=True` 不会移除）。因此即使启用 `glm45`，将剩余文本送入 `score.extract` **仍会触发 `surrounding_text_or_fence` 且 `strict_format_valid=False`**（即便内部 5 类 JSON 完全合法），且单条延迟高于非思考模型；开启 `glm45` **不等于**已解决严格 JSON 兼容（决策选项见 §3.2） `[外部文档/待训练机核实]` |
| **Ovis2.5-9B**（横向候选） | **高（有序帧序列）**：支持多帧图像序列输入，兼容 L3 8 帧绑定 `[外部文档/待训练机核实]` | **原生分辨率 ViT（NaViT 风格）**，避免固定 448×448 切块割裂细长试样或放大失真，对细微裂缝、夹具边界与小画幅 `w_le_200` 在架构上极具针对性 `[外部文档/待训练机核实]` | 多帧视觉 token 按序进入 LLM 主干，可配帧序/相对时间戳文本 `[外部文档/待训练机核实]` | **优势在于支持 `enable_thinking` 开关与 `thinking_budget` 控制**，首轮摸底可显式关闭 thinking 以获得干净单 JSON，后续还可同权重对比开启 thinking 的收益 `[外部文档/待训练机核实]` |
| **Keye-VL-1.5-8B**（横向候选） | **中高（视频帧序列）**：原生面向视频设计，8 帧预抽图可按有序多图/帧列表输入；注意 Slow-Fast 帧间相似度分配依赖视频帧通路，走纯 `image_url` 时是否完整激活 Slow-Fast 须在训练机核实 `[外部文档/待训练机核实]` | **Slow-Fast 动态编码策略**：对帧间变化剧烈的关键帧分配高分辨率（Slow 通路）、对静止帧分配低分辨率（Fast 通路），天然契合拉伸视频「前段缓变、断裂瞬间剧变」的物理特征 `[外部文档/待训练机核实]` | 专精长短视频时空建模（128K 上下文），时序敏感度强 `[外部文档/待训练机核实]` | 经 LongCoT + RL 对齐，须实测默认模式是否输出思考段并验证中文五类 11 叶 JSON 遵循度 `[外部文档/待训练机核实]` |
| **MiMo-VL-7B-RL**（横向候选） | **高（frames list / 多图）**：代码兼容通用动态分辨率视频架构，8 张预抽 PNG 易接入 vLLM 与 `transformers` `[外部文档/待训练机核实]` | 原生分辨率 ViT，7B 轻量化，兼顾细粒度视觉定位与较低显存开销 `[外部文档/待训练机核实]` | 原生支持多帧视频与长帧预算推理 `[外部文档/待训练机核实]` | 经 MORL 强化学习，可能倾向输出推理过程；须在 5–10 条开发集冒烟中核实是否带 `<think>` 及中文枚举字面量遵循稳定性 `[外部文档/待训练机核实]` |

### 3.2 跨模型评测的关键方法论注意事项

1. **Thinking 模型与严格单 JSON 契约的冲突处置**：
   - 现行 [score.py](../../script/five_label_eval/score.py) 与 [output-contract.md](../eval/output-contract.md) §2 要求 `raw_output` 只能包含一个干净 JSON 对象；一旦模型在正文前输出 `<think>...</think>`，即使末尾给出合法 JSON，也会触发 `surrounding_text_or_fence` 令 `strict_format_valid=False`，而如果 `<think>` 内部举例写出第二个 `{...}` 片段，整条样本会直接判 `extraction_failed`。
   - **处置纪律**：首轮基座摸底优先选用 **非思考 / Instruct 模式**（如 `Qwen3-VL-8B-Instruct`、`InternVL3-8B`、`MiniCPM-V-4.5`、`Ovis2.5-9B(enable_thinking=False)`）；若评测 `Qwen3-VL-8B-Thinking`、`GLM-4.1V-9B-Thinking` 等思考型变体，必须明确是否启用服务端 `--reasoning-parser` 仅把最终 `message.content` 写入 `raw_output`（并将思考过程另存 `run_meta`），且须与无 parser 的直出模式拆分为不同 `run_id`、并在报告中如实披露（不得把服务端剥离后的结果冒充模型原生无前后缀遵循能力）。
   - **特别针对 `GLM-4.1V-9B-Thinking` 的 `<answer>...</answer>` 剩余冲突**：因 vLLM `glm45` parser 仍保留 `<answer>...</answer>`（非 special token，`skip_special_tokens=True` 不移除），开启 `glm45` 后送入 `score.extract` 仍会命中 `surrounding_text_or_fence` 并令 `strict_format_valid=False` `[外部文档/待训练机核实]`。评测该模型前须二选一拍板：**（默认）保留原生格式罚分**，维持全部候选模型在同一套五类严格单 JSON 契约下公平打分；或**（须经批准）新增独立标明身份的 `<answer>` 解包模式**（独立 `run_id` 并在报告显式披露，绝不静默解包，也不得把开启 `glm45` 写成已实现严格 JSON 兼容）。
2. **受控约束解码（`guided_json` / `response_format`）边界**：
   - 按 [base-model-eval-plan.md](../eval/base-model-eval-plan.md) §6.1 与 §8.1，base 阶段格式合法率本身是待测产出指标。首轮摸底默认**关闭** `guided_json`（统一贪婪解码 `temperature=0.0` + 冻结 `five_label_v2.txt` 原文）；若后续考察约束解码收益，须作为独立 `run_id` 单独报告。
3. **「多图 `image_url`」与「原生视频张量」通道差异**：
   - 对 MiniCPM-V-4.5（3D-Resampler + `temporal_ids`）、Qwen3-VL（Interleaved-MRoPE）与 Keye-VL-1.5（Slow-Fast），同一组 8 张 L3 PNG 经标准 OpenAI `image_url` 多图接口 vs 原生视频张量接口，其视觉编码路径可能不等价 `[外部文档/待训练机核实]`。必须将输入通道类型（`multi_image_png` vs `video_frames_tensor`）写入运行身份，按 [design-test.md](../design-test.md) §4.1 明确跨模型对比反映的是「模型 + 对应输入配置」的整体表现。
4. **时间戳提示与画幅三档红线**：
   - [five_label_v2.txt](../../script/five_label_eval/prompts/five_label_v2.txt) 第 1 行允许模型看到帧图像、帧顺序与每帧相对时间戳，但**严禁传入文件名、路径、`candidate_id` 或原视频绝对时间**；未来 3b 顺序对照须移除或重写时间戳与 `temporal_ids` 防泄露（见 [minicpm-video-loading.md](minicpm-video-loading.md) §6 第 5 条）。
   - 无论模型内部是否将小画幅插值到 448×448，评测报告均须严格按 [eval-subset.md](../eval/eval-subset.md) §3 的 L2 原始宽度三档（`w_le_200` / `w_200_400` / `w_gt_400`）分列输出，不得跨档合并。

---

## 4. 首轮摸底推荐梯队与选型建议

结合用户已确认的 3 款核心模型、单卡 24 GB 显存约束、严格中文 JSON 契约适配度以及后续微调（LLaMA-Factory / ms-swift）落地成本，建议按三个梯队分批推进基座摸底：

| 梯队 | 推荐模型 | 定位与纳入理由 | 建议推理入口 |
| --- | --- | --- | --- |
| **第一梯队（首轮必测核心，3+1 款）** | 1. **`openbmb/MiniCPM-V-4_5`**<br>2. **`Qwen/Qwen3-VL-8B-Instruct`**<br>3. **`OpenGVLab/InternVL3-8B`**<br>4. **`OpenGVLab/InternVL3_5-8B`**（标准版同系对照） | 直接覆盖用户确认的全部 3 款核心基座，并同口径检验 InternVL3 → InternVL3.5 标准版（Cascade RL 对齐升级，仍沿用同口径 448×448 动态切块、不含 ViR；若后续需测 ViR 动态压缩则另选明确的 InternVL3.5-Flash checkpoint）在拉伸细粒度任务上的净增益；4 款均为 8B 级、非思考直出 JSON、vLLM 与 LLaMA-Factory 生态成熟 | MiniCPM-V-4.5 走薄本地 `transformers` backend（支持 `temporal_ids` 对照）；其余 3 款统一走 vLLM OpenAI-compatible `http` backend |
| **第二梯队（高差异化架构补充，2 款）** | 5. **`Kwai-Keye/Keye-VL-1_5-8B`**<br>6. **`AIDC-AI/Ovis2.5-9B`**（首轮 `enable_thinking=False`） | 若第一梯队摸底暴露「瞬时断裂漏抓」或「`w_le_200` 小画幅细微裂纹辨识不足」，分别用 Keye-VL-1.5（视频专精 Slow-Fast）与 Ovis2.5-9B（原生分辨率无切块 + 可切换思考模式）做针对性架构验证；均为 Apache-2.0 | 统一走 vLLM OpenAI-compatible `http` backend（均需在 5–10 条开发集冒烟中核实 8 帧通路与显存余量） |
| **第三梯队（Thinking 推理专项与轻量备选，2 款）** | 7. **`Qwen/Qwen3-VL-8B-Thinking`** & **`zai-org/GLM-4.1V-9B-Thinking`**<br>8. **`XiaomiMiMo/MiMo-VL-7B-RL`** | 专项验证「视觉思维链能否提升复杂组合判断（如半脆半韧断裂、多选现象区分）」，须先敲定 `--reasoning-parser` 剥离口径及 GLM-4.1V `<answer>...</answer>` 处置方式（默认保留原生格式罚分 vs 经批准的独立身份解包模式）并独立 `run_id`；MiMo-VL-7B-RL（MIT）作为 7B 更低显存参照 | vLLM OpenAI-compatible `http` backend（Thinking 变体需配置对应 reasoning parser 并记录思考段与总耗时；GLM-4.1V 须显式遵循 §3.2 `<answer>` 处置边界） |

**待用户确认事项**：
1. 首轮 run A 是先跑**第一梯队 3 款**（MiniCPM-V-4.5、Qwen3-VL-8B-Instruct、InternVL3-8B），还是把 **InternVL3.5-8B** 一并纳入首轮？
2. 第二梯队（Keye-VL-1.5-8B / Ovis2.5-9B）与 Thinking 变体（Qwen3-VL-8B-Thinking / GLM-4.1V-9B-Thinking）是留在首轮摸底之后按需追加，还是现在就纳入候选下载清单？

---

## 5. 来源与失效条件

### 5.1 仓内已核实证据

- [docs/TODO.md](../TODO.md)（§2 `EVAL-DESIGN` 后续前置工作）、[docs/decisions/0003-five-label-eval-scope.md](../decisions/0003-five-label-eval-scope.md)（`DEC-003`）、[docs/decisions/0005-frame-correspondence-evidence.md](../decisions/0005-frame-correspondence-evidence.md)（`DEC-005`）、[docs/facts.yaml](../facts.yaml)（`DF-016`、`DF-043`、`DF-044`、`DF-051`、`DF-052`）。
- [docs/research/minicpm-video-loading.md](minicpm-video-loading.md)、[docs/design-test.md](../design-test.md)、[docs/eval/base-model-eval-plan.md](../eval/base-model-eval-plan.md)、[docs/eval/inference-entry.md](../eval/inference-entry.md)、[docs/eval/output-contract.md](../eval/output-contract.md)、[docs/eval/eval-subset.md](../eval/eval-subset.md)、[script/five_label_eval/score.py](../../script/five_label_eval/score.py)、[script/five_label_eval/prompts/five_label_v2.txt](../../script/five_label_eval/prompts/five_label_v2.txt)、[data/sub_video/manifest.json](../../data/sub_video/manifest.json)。
- 同系列关联专题：[model-input-frame-sampling-options.md](model-input-frame-sampling-options.md) · [eval-preflight-and-adapter-plan.md](eval-preflight-and-adapter-plan.md)。

### 5.2 外部参考边界（均标记 `[外部文档/待训练机核实]`）

- Hugging Face 与 ModelScope 公开模型卡、vLLM 多模态支持文档及 LLaMA-Factory / ms-swift 适配说明：`Qwen/Qwen3-VL-8B-Instruct` & `Thinking`、`OpenGVLab/InternVL3-8B` & `InternVL3_5-8B`、`zai-org/GLM-4.1V-9B-Thinking`、`AIDC-AI/Ovis2.5-9B`、`Kwai-Keye/Keye-VL-1_5-8B`、`XiaomiMiMo/MiMo-VL-7B-RL`、`openbmb/MiniCPM-V-4_5`。

**失效条件：**当用户正式冻结对比模型名单、单卡硬件显存预算（如由单卡 24 GB 变更为多卡或更大显存）、五类 11 叶字段输出契约（`five-label-score/3` / `five_label_v2.txt`）发生变更，或上述候选模型在训练机实测显存、vLLM/LLaMA-Factory 兼容性、许可证条款与本文外部公开信息不一致时，本文受影响的对照项与推荐梯队须重新核对。本文仅作选型调研，不构成最终选型批准、下载授权或真实模型效果证据。
