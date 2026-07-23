# 调研主题：MiniCPM-V 系列（重点是 4.5）与 LoRA/SFT 微调直接相关的工程细节（范围 E）

> 调研员：MiniCPM调研员。调研时间基于当前轮次；来源分为【官方确认】（OpenBMB 官方仓库/文档/论文）、【社区经验】（GitHub issues、CSDN/博客等）、【源码核实】（直接阅读 LLaMA-Factory / 官方脚本源码）。冲突或不确定之处已显式标注。

---

## 1. LoRA target modules 的官方与社区推荐

### 1.1 官方 finetune 脚本（transformers Trainer + DeepSpeed 路线）

- 官方 `finetune/finetune_lora.sh` 的默认 LoRA 目标模块为正则 `"llm\..*layers\.\d+\.self_attn\.(q_proj|k_proj|v_proj|o_proj)"`，即**只挂在 LLM（语言模型）自注意力的 q/k/v/o 四个投影层**，不匹配视觉编码器（vpm，SigLIP）和 Resampler。【官方确认】
  来源：https://github.com/OpenBMB/MiniCPM-V/blob/main/finetune/finetune_lora.sh
- 同一脚本默认 `--tune_vision true --tune_llm false --use_lora true`：含义是"LLM 本体全量参数冻结、仅训练 LLM 上的 LoRA adapter，同时视觉塔 vpm 以普通全参方式参与训练"；学习率默认 `1e-6`。【官方确认】（注意：该默认组合比较特殊，很多社区实践会改 `--tune_vision false`）
  来源：同上脚本；官方 finetune readme 的 FAQ 明确建议 OOM 时加 `--tune_vision false` 不训练视觉模块：https://github.com/OpenBMB/MiniCPM-V/blob/main/finetune/readme.md
- 重要边界：**官方 finetune 脚本声明仅支持 MiniCPM-V 4.0 / MiniCPM-o 2.6 / MiniCPM-V 2.6 / MiniCPM-Llama3-V 2.5 / MiniCPM-V 2.0，未声明支持 MiniCPM-V-4.5**。【官方确认】
  来源：https://github.com/OpenBMB/MiniCPM-V/blob/main/finetune/readme.md

### 1.2 官方 Cookbook（LLaMA-Factory 路线，明确支持 MiniCPM-V-4.5）

- 官方《MiniCPM-V & MiniCPM-o Cookbook v5》给出 MiniCPM-V-4.5 的 LLaMA-Factory LoRA 配置：`lora_target: q_proj,v_proj`（**只挂 q/v 两投影**，比官方脚本的 q/k/v/o 更保守），`learning_rate: 1.0e-5`，`template: minicpm_v`，`cutoff_len: 3072`（注释明确：该长度**包含多模态 token 占用**）。【官方确认】
  来源：https://www.bookstack.cn/read/minicpm-o-5-zh/21133a7ea3b90a90.md ；官方仓库等价文档 https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/llamafactory_train_and_infer.md （该文档页标注支持到 MiniCPM-V-4 / o-2_6 / V-2_6，4.5 是 Cookbook v5 新增支持）
- LLaMA-Factory 的 `lora_target` 是**按模块名子串匹配**，`q_proj,v_proj` 会同时命中 LLM 内所有叫 q_proj/v_proj 的层；Resampler 的 cross-attention 层与 SigLIP 视觉塔层若同名也会被命中，但官方推荐配置显然以 LLM 为主要目标。【社区经验/框架行为，需注意正则/子串匹配范围】

### 1.3 社区实践的差异

- 社区 LoRA 教程普遍沿用官方正则 `llm\..layers\.\d+\.self_attn\.(q_proj|k_proj|v_proj|o_proj)`（显式限定在 `llm.` 命名空间下，避免误挂视觉/Resampler 模块），LoRA 学习率社区常用 `1e-4 ~ 2e-4`，与官方脚本的 `1e-6`、Cookbook 的 `1e-5` 相差 1–2 个数量级。【社区经验，与官方存在明显冲突，需自行实验；可能的解释是官方 lr=1e-6 搭配了 `tune_vision=true` 的全参视觉训练，而社区配置通常冻结视觉塔、只训 LoRA，故需要更高 lr】
  来源：https://blog.csdn.net/gitblog_00257/article/details/151428339 、https://blog.csdn.net/gitblog_01034/article/details/151129613 、LLaMA-Factory issue 中用户配置示例 https://github.com/hiyouga/LLaMA-Factory/issues/6655

---

## 2. 为什么 llm / resampler / vision tower 要分开设置学习率或冻结

依据 MiniCPM-V 4.5 技术报告的训练配方，官方自己在预训练阶段就严格分模块解冻，这为微调策略提供了直接依据：【论文】

- 预训练 Stage 1：**只训练 Resampler**（随机初始化的压缩层），其余全冻结，用 image-caption 数据做模态对齐的热身——因为压缩层是新初始化的，必须先单独对齐。
- 预训练 Stage 2：解冻视觉编码器（喂 OCR/图文数据），**LLM 保持冻结**——该阶段数据不够流畅，避免污染语言能力。
- 预训练 Stage 3：全部参数端到端训练，并采用 Warmup-Stable-Dacy 学习率调度。
- SFT 阶段官方还混入 10% 纯文本数据以防文本能力退化。
  来源：https://arxiv.org/html/2509.18154v1 （§2.2.1、§2.3.1）

由此得出的工程共识（官方文档 + 社区一致的推断）：

- **视觉塔（vpm，SigLIP2-400M）在下游 SFT 中通常冻结**：官方 LLaMA-Factory 全量微调示例配置 `freeze_vision_tower: true`；【官方确认】来源：Cookbook v5 与 https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/llamafactory_train_and_infer.md 。官方 finetune readme FAQ 也把 `--tune_vision false` 列为省显存首选手段。【官方确认】
- **Resampler 是"对齐层"**：参数量小但对模态对齐至关重要。LoRA 微调时社区主流做法是不动它（名字不匹配 q/v 等投影层自然被跳过）；官方全参脚本才会 `tune_vision` 带着它一起训。【社区经验 + 官方脚本行为】
- **LLM 侧用 LoRA 低秩适配**，避免小数据集上全参训练导致的灾难性遗忘——论文 SFT 混入 10% 文本数据也侧面说明官方对遗忘问题敏感。【论文 + 社区经验】

---

## 3. LLaMA-Factory 对 MiniCPM-V 的支持方式与已知坑

### 3.1 支持方式【官方确认】

- 官方 News（2025-09-01）：MiniCPM-V 4.5 已被 llama.cpp、vLLM、LLaMA-Factory 官方支持。来源：https://github.com/OpenBMB/MiniCPM-V
- 安装：`pip install -e ".[torch,metrics,deepspeed,minicpm_v]"`；旧版 `minicpm_v` extra 实际装的是 soundfile/torchvision/torchaudio/vector_quantize_pytorch/vocos/msgpack 等（主要为 MiniCPM-o 音频链路）。【源码核实：v0.9.3 setup.py】
- 数据格式：sharegpt 格式，`messages` 中放 `<image>`/`<video>` 占位符，与 `images`/`videos` 字段一一对应；在 `data/dataset_info.json` 注册。视频数据集参考 `mllm_video_demo.json`。【官方确认】来源：Cookbook v5、官方 docs/llamafactory_train_and_infer.md
- 关键 YAML 项：`template: minicpm_v`（o 系列用 `minicpm_o`，"不要改"）、`trust_remote_code: true`、`cutoff_len: 3072`（含多模态 token）。LoRA 合并导出用 `llamafactory-cli export` + merge yaml。【官方确认】

### 3.2 已知坑

1. **MiniCPM-o-4.5 在 LLaMA-Factory 中只能按视觉（V）模型微调，不支持 Omni（音频）模式**；直接微调会报 `ValueError: Audio feature extractor was not found`。【官方确认，issue 中官方人员回复】来源：https://github.com/OpenBMB/MiniCPM-V/issues/1073 。纯 V-4.5 无此问题。
2. **用官方 finetune 脚本（非 LLaMA-Factory）训练 MiniCPM-V-4.5 会踩 Resampler 相关报错**（`resampler.py batch_attn_forward` 形状错误，`shape '[1034, 33088, 128]' is invalid`）——再次印证官方脚本不支持 4.5，4.5 的 Resampler 带 temporal 维度，与旧脚本的数据构造不兼容。【社区报告 + 与官方支持列表交叉印证】来源：https://github.com/OpenBMB/MiniCPM-V/issues/967
3. **LLaMA-Factory 的视频处理方式与 MiniCPM-V-4.5 原生 3D-Resampler 时序打包不一致**（本调研最重要的发现之一，【源码核实】，src/llamafactory/data/mm_plugin.py `MiniCPMVPlugin`）：
   - 视频按 `video_fps`（默认 2.0）抽帧、`video_maxlen`（默认 128 帧）截断；
   - 每帧被当作**独立图片**用 `max_slice_nums=2` 编码，`<video>` 占位符被展开为 N 个 `(<image>./</image>)` 图像占位符；
   - **不使用官方推理代码中的 `temporal_ids` / 时序 package 打包**，即每帧走 2D 路径而非 6 帧→64 token 的 3D 联合压缩；意味着微调时的 token 成本与官方推理路径不同，且帧间时序建模依赖 LLM 而非 Resampler；
   - 同一样本**不允许图像和视频同时输入**（代码直接 `raise ValueError("MiniCPM-V model does not support input images and videos at the same time.")`）。
   来源：https://raw.githubusercontent.com/hiyouga/LLaMA-Factory/main/src/llamafactory/data/mm_plugin.py （MiniCPMVPlugin 类）
4. transformers 版本兼容坑：曾出现 `trust_remote_code` 参数解析不兼容、`minicpm_v` extra 与其他 extra 冲突等问题；LLaMA-Factory 当前 main 已将核心依赖拉平为 `transformers>=4.55.0`（旧版 extra 体系在 v0.9.3 及以前）。【社区经验 + 源码核实】来源：https://blog.gitcode.com/a3f06882c5a5e8f2ae5cd52b7c3f1d90.html 、https://github.com/hiyouga/LLaMA-Factory/issues/7678 、pyproject.toml
5. 视频抽帧参数是全局的：LLaMA-Factory 的 `video_maxlen` 对每个视频独立生效，多视频样本可能截断后面的视频（通用问题，有改进 PR）。【社区经验】来源：https://github.com/hiyouga/LLaMA-Factory/issues/7693

---

## 4. 视频输入预处理的官方建议（抽帧策略、帧数上限、token 换算）

### 4.1 官方模型能力上限【论文】

- 每个视频**最多采样 1080 帧，最高帧率 10 fps**；训练时 package size（时序打包的相邻帧数）和帧率做随机增强以增强鲁棒性；推理时这些超参可调以适配不同场景/设备。
- 3D-Resampler 将**相邻 6 帧 448×448 视频帧联合压缩为 64 个 token**（对比多数 MLLM 需 1536–3072 token），实现 96× 视频 token 压缩率；VideoMME 消融显示 3D 平均每帧仅 21.3 token，是 2D 路径（64 token/帧）的 1/3。
  来源：https://arxiv.org/html/2509.18154v1 （§2.1.1、Table 5）

### 4.2 官方推理代码的默认配置【官方确认】

- HF 模型卡/README 视频示例：`MAX_NUM_FRAMES=180`（超过则按 fps 上限重采样），且视频输入必须组织为两个对应序列：`frames: List[Image]` 和 `temporal_ids: List[List[int]]`——这是 3D-Resampler 知道哪些帧属于同一时序 package 的依据。
  来源：https://ai.gitcode.com/OpenBMB/MiniCPM-V-4_5-GPTQ （OpenBMB 官方镜像，与 HF 模型卡一致）、https://ai.gitcode.com/OpenBMB/MiniCPM-V-4_5

### 4.3 与上下文长度的换算（微调 cutoff_len 规划用）

- 原生 3D 路径：每 package（默认约 6 帧）≈ 64 token → 180 帧 ≈ 30 个 package ≈ **约 1920 视觉 token**；1080 帧上限 ≈ 180 package ≈ **约 11520 token**。图像路径（LLaVA-UHD 切片）：448×448 单切片 64 token；1344×1344 最多 9 slice + 1 缩略图 ≈ 640 token/图（v2.6 口径，4.5 同架构思路）。【论文 + 官方 readme】来源：https://arxiv.org/html/2509.18154v1 、https://github.com/OpenBMB/MiniCPM-V/blob/main/finetune/readme.md
- **注意 LLaMA-Factory 路径不同**：其视频按独立帧 × slice=2 编码（≈128 token/帧），128 帧上限 ≈ 1.6 万视觉 token，远超 `cutoff_len: 3072` 默认值——**在 LLaMA-Factory 中做视频 SFT 必须同时调大 `cutoff_len` 并调小 `video_fps`/`video_maxlen`，否则样本被截断（截断会切断图像占位符与视觉 token 的对应关系）**。【源码核实 + 推断，官方 cookbook 未明示此换算】

---

## 5. 微调时容易踩的架构相关坑

1. **`tgt_sizes` 与 `temporal_ids` 必须正确传递**：Resampler 前向签名为 `resampler(vision_embedding, tgt_sizes, all_temporal_ids)`；任何绕过官方 processor/自定义 collator 的做法若丢掉 `tgt_sizes`（每个切片的目标网格尺寸，决定 2D 位置嵌入形状）或视频 `temporal_ids`，会直接报形状错误。官方 finetune `dataset.py` 显式保留 `image_bound` 与 `tgt_sizes` 两个字段。【源码核实/官方代码】来源：https://github.com/OpenBMB/MiniCPM-V/blob/main/finetune/dataset.py 、https://github.com/OpenBMB/MiniCPM-V/issues/967
2. **`image_bound` 边界 token 对齐**：MiniCPM-V 用 `<image>...</image>` 风格的边界标记把视觉 token 段嵌入文本序列，占位符数量必须与图像/视频帧数量一致；LLaMA-Factory 的 plugin 会按 `image_sizes` 展开占位符，若数据里 `<image>` 数量与 `images` 字段不符会在校验或训练时对错位。【官方确认（数据格式要求）+ 源码核实】来源：Cookbook v5、mm_plugin.py
3. **截断破坏对齐**：总 token（含视觉 token）超过 `model_max_length`/`cutoff_len` 会被截断，多图 SFT 官方建议 `MODEL_MAX_LENGTH=4096`。【官方确认】来源：https://github.com/OpenBMB/MiniCPM-V/blob/main/finetune/readme.md
4. **PEFT 包装 Resampler 的风险**：4.5 的 Resampler 是 `torch.nn.MultiheadAttention` 风格实现，若把 Resampler 加进 `modules_to_save` 或 LoRA target，forward 的多签名参数（tgt_sizes/temporal_ids）可能与 PEFT 的包装不兼容（issue #967 的堆栈即 `peft/utils/other.py _forward_wrapped` 调用 resampler 时报形状错误）。【社区报告，机制解释为本调研推断】来源：https://github.com/OpenBMB/MiniCPM-V/issues/967
5. **LoRA 加载路径**：官方建议 adapter 配置里保留基座模型绝对路径，因为 LoRA checkpoint 只存 adapter，加载时按 adapter config 里的路径找基座；`AutoPeftModelForCausalLM` 曾报缺 `get_input_embeddings`，需更新模型目录里的 `model_minicpmv.py`。【官方确认】来源：https://github.com/OpenBMB/MiniCPM-V/blob/main/finetune/readme.md
6. 注意力实现：官方建议 `attn_implementation='sdpa'` 或 `flash_attention_2`，**不要用 eager**。【官方确认】来源：HF 模型卡镜像 https://ai.gitcode.com/OpenBMB/MiniCPM-V-4_5

---

## 6. 与微调实践相关的要点（直接影响 LoRA / 数据预处理 / 评测）

- **选框架**：MiniCPM-V-4.5 微调走 **LLaMA-Factory + `template: minicpm_v`**（官方唯一明确支持 4.5 的路径）；不要套用官方 transformers finetune 脚本（仅到 4.0）。
- **LoRA 配置**：起步用官方 Cookbook 口径 `lora_target: q_proj,v_proj`、`lr 1e-5`、`cutoff_len 3072`；若只训 LoRA 且显存充裕，可参照社区提高到 `1e-4` 并对比验证集。**不要**把 Resampler/视觉塔名字加进 LoRA target。
- **冻结策略**：LoRA 微调时视觉塔与 Resampler 默认冻结即可（天然不匹配 target）；全参微调参考官方示例 `freeze_vision_tower: true`。
- **视频数据预处理（关键）**：LLaMA-Factory 的视频是"独立帧 + slice=2"路径，不是官方 6 帧→64 token 的 3D 打包路径：
  - 显存/长度预算按 ≈128 token/帧估算，`cutoff_len` 必须覆盖 帧数×128 + 文本；
  - 用 `video_fps`（默认 2.0）与 `video_maxlen`（默认 128）控制抽帧；长视频任务需自行加大并在训练中验证；
  - **评测一致性风险**：训练走 LLaMA-Factory 的逐帧路径、评测走官方 `model.chat` 的 3D-Resampler 时序打包路径（`temporal_ids`、`MAX_NUM_FRAMES=180`），两条输入路径的视觉 token 组织不同，可能造成训练-评测分布偏移——评测时建议同时报告两种推理路径的指标，或在评测脚本中复现训练时的逐帧输入方式。【本调研基于源码的推断，未见官方明示，建议实验验证】
- **数据格式纪律**：`<image>`/`<video>` 占位符数量与媒体文件数量严格一致；同一样本不要混图像和视频（LLaMA-Factory 直接报错）；总长留余量避免截断切断视觉段。
- **checkpoint 一致性**：LoRA 只存 adapter，合并用官方 export yaml；记录基座模型绝对路径、LLaMA-Factory 版本、transformers 版本（>=4.55 与旧版差异大），避免 metadata 指向旧实验。
- **显存参考**：官方统计 LoRA 微调 2×A100(80G) 约 14.4 GiB/卡（max_len 2048、bs=1、ZeRO-2/3+offload），视频长样本会显著超过该值。【官方确认】来源：finetune/readme.md

---

## 7. 可信度总表

| 结论 | 可信度 |
|---|---|
| 官方脚本 LoRA target=LLM q/k/v/o、lr 1e-6、tune_vision/llm 开关 | 官方确认（官方脚本源码） |
| Cookbook（LLaMA-Factory）q_proj,v_proj / lr 1e-5 / cutoff_len 3072 / freeze_vision_tower | 官方确认 |
| 官方 finetune 脚本不支持 4.5；4.5 用 LLaMA-Factory | 官方确认（支持列表 + issue 官方回复） |
| 3D-Resampler 6帧→64token、1080 帧/10fps 上限、temporal_ids 输入格式 | 论文 + 官方模型卡 |
| LLaMA-Factory 视频=逐帧独立编码、fps=2/maxlen=128/slice=2、不用 temporal_ids、图视频不能混输 | 源码核实（当前 main 分支） |
| 社区 LoRA lr 1e-4~2e-4 | 社区经验（与官方冲突，已标注） |
| 训练-评测视频路径不一致导致分布偏移 | 本调研推断（基于源码差异，未实验验证） |
| "PEFT 包装 Resampler 报形状错"的机制解释 | 社区报告为实，机制为推断 |
