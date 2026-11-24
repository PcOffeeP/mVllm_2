# 多模型输入机制与训练机资源适配调研

**调研日期：** 2026-11-24。本文承接 [TODO §2 后续前置工作](../TODO.md#后续前置工作)（「完成多模型输入及训练机资源适配调研」）与 [基座模型测评方案](../eval/base-model-eval-plan.md)，为首次基座模型摸底测评打通多模型输入适配方案、DEC-005 抽帧口径决策输入与训练机启动前核对清单。

**基准与边界声明：**

- **仓内核对基线**：`feat/tensileagent-finetune` 提交 `f4a9a16a14b65066cf9158cdc1c289816595356a`（稀疏检出工作树，不含 `pipeline/`、`versioning/`）；当前生效第 2 批子视频清单 [data/sub_video/manifest.json](../../data/sub_video/manifest.json)（SHA-256 `c70686630c8fa0277305cc25a09821bc04ab853f6ce8a6ac3ca795998c08ac0f`，1,633 条候选，110 个源）。
- **只调研、不授权**：本文不最终拍板对比模型名单或抽帧口径，不修改现有契约或代码，不授权启动真实模型评测、训练或固定 test 推理。
- **证据分级纪律**：本文严格区分「仓内已核实证据（标明文件路径、行号或 `DF-*`／`DEC-*` 编号）」、「外部公开文档规格与显存／耗时估算（统一标注 `[外部文档/待训练机核实]`）」与「训练机尚未现场核对项（统一标注 `待训练机实测核对`）」，不编造任何训练机硬件、依赖版本或本地权重事实。

---

## 1. 背景与目标

当前项目已完成五类 11 叶字段评价口径确认（[DEC-003](../decisions/0003-five-label-eval-scope.md)、`DF-043`；[DEC-004](../decisions/0004-fragment-label-no-value-removal.md)、`DF-049`）、评测输入契约 6 篇拆分（[评测专题目录](../eval/README.md)）、帧对应抽帧取证设计（[DEC-005](../decisions/0005-frame-correspondence-evidence.md)、`DF-051`）、映射节点重命名至 `five-label-input-record/3`（`DF-052`），以及第 2 批子视频 B0（32/32）与 B1 固定 test（314/314）人工审核（见 [TODO](../TODO.md)）。

但首次基座模型摸底测评（[基座模型测评方案](../eval/base-model-eval-plan.md) §4 run A）仍被四项前置工作卡住：

1. **真实推理后端尚未落地**：[infer.py](../../script/five_label_eval/infer.py) 目前只有 `fake` backend，`transformers` 抛 `NotImplementedError`，`http` 既无参数也无实现（见 [inference-entry.md](../eval/inference-entry.md) §8）。
2. **多模型输入差异尚未对齐**：此前仅完成 [MiniCPM 视频加载与模型输入核查](minicpm-video-loading.md)；若后续纳入 Qwen2.5-VL、InternVL3 等开源视频 VLM 做基座横向对比，不同模型在 8 帧输入形式、`temporal_ids`/FPS 绑定、`max_pixels`/动态切片、JSON 稳定性与 `five-label-input-record/3` 溯源兼容性上存在显著差异。
3. **DEC-005 前置条件 1 尚未落纸**：[帧对应抽帧取证](../frame-correspondence-evidence.md)明确列出两项实现前置条件——条件 2（映射字段命名）已由 `DF-052` 落地，**条件 1（「模型输入抽帧口径须先落纸」）仍待用户拍板**。
4. **训练机推理资源未现场核验**：目前仓内仅核实了训练机 CPU/内存/磁盘/Python 3.11/ffmpeg 与旧仓 `minicpmv4_5` 分片大小（见 [training-machine-review-runbook.md](../training-machine-review-runbook.md) §2.1、`DF-044`），GPU 型号与空闲显存、CUDA/PyTorch/vLLM/transformers 版本、多模型权重在位状态均`待训练机实测核对`，[eval_paths.json](../../config/eval_paths.json) 的 `gpu-train` 全部 9 个路径仍是 `TODO_MIGRATION_FILL:*` 占位符。

本文围绕以上四项缺口给出证据对照、决策输入、可执行只读核对清单与最小适配器落地路线。

---

## 2. 现状代码与契约缺口分析

本节逐项核对 `f4a9a16` 工作树中 [infer.py](../../script/five_label_eval/infer.py)、[frames.py](../../script/five_label_eval/frames.py)、[paths.py](../../script/five_label_eval/paths.py)、[eval_paths.json](../../config/eval_paths.json) 与 [inference-entry.md](../eval/inference-entry.md)、[input-record.md](../eval/input-record.md)、[output-contract.md](../eval/output-contract.md)、[prompt.md](../eval/prompt.md) 的接口缺口。

> 注：经实读核对，[inference-entry.md](../eval/inference-entry.md) §1–§2 引用 `infer.py` 行号（如 `main` 74 行、`--backend` 84 行）较当前 `f4a9a16` 偏移 2 行（实际为 76 行、86 行）；下文均以 `f4a9a16` 实测行号为准。

### 2.1 `script/five_label_eval/infer.py` 与 `inference-entry.md` 缺口

| 维度 | 现状（`f4a9a16` 实读） | 契约/方案要求 | 缺口与影响 |
| --- | --- | --- | --- |
| `transformers` backend | `--backend` 在 `infer.py:86` 声明 `choices=("fake", "transformers")`，89–90 行直接 `raise NotImplementedError` | `DF-044` / `DEC-003` 第 9 条选定基座 `openbmb/MiniCPM-V-4_5` + `transformers` 加载 | 无模型加载、无处理器装配、无推理执行，无法运行 run A |
| `http` backend | CLI 未声明 `http`，无 `--endpoint`、`--api-model-name`、`--api-key-env`、`--timeout`、`--temperature`、`--max-tokens` 等参数 | [inference-entry.md](../eval/inference-entry.md) §8 规划 `http` 拟增；[agent-handoff-contract-draft.md](../eval/agent-handoff-contract-draft.md) §2.2 规划 OpenAI-compatible `/v1/chat/completions` | 无法对接 vLLM / SGLang 等多模型服务，也无法衔接未来 HTTP 服务评测 |
| Prompt 正文传递 | `infer.py:97` 执行 `load_prompt(args.prompt_file)[1]`，丢弃正文、仅保留 `prompt_id` | [prompt.md](../eval/prompt.md) §3 要求送模型文本与算 `prompt_id` 字节为同一份原文（不 `strip`） | 真实 backend 必须消费 `load_prompt` 返回的 `(text, prompt_id)` 二元组 |
| L3 帧图路径解析 | `infer.py:98` 仅调用 `read_records(input_config)`；`records.jsonl` 中 `frames[].image` 只是裸文件名（如 `frame_001.png`，`frames.py:706`），记录内无 `--out-dir` 字段 | 真实推理需按 `display_order` 顺序读取对应 PNG 字节并送入模型 | 缺少 `--frames-dir`（或按 `records.jsonl` 父目录解析 + 文件存在性 fail-closed 检查） |
| 推理前血缘复检 | `infer.py:98` 只 `read_records`，不调用 `verify_lineage`（仅拒绝旧 v2 schema 与遗留键名） | [input-record.md](../eval/input-record.md) §0 状态表 4 指出推理模式不重验 | 若输入记录与媒体在抽帧后被改动，推理前无法拦截；建议推理前默认校验或至少核对 L3 帧数与文件存在 |
| 超时与三态映射 | `infer.py:67–72` 仅用 `CATEGORY_ORDER` 轮转伪造 `request_failed`/`timeout`；无真实超时控制与异常捕获 | [inference-entry.md](../eval/inference-entry.md) §5、§7 要求 600s 超时（POSIX `SIGALRM`/`setitimer` 或 HTTP 客户端超时）并显式落盘 `request_failed`/`timeout`/`unprocessed` + `"raw_output": null` | 缺少可执行超时守卫、单条异常隔离（单条 OOM/HTTP 错误不得打崩整批导致已跑结果丢失）及中断补齐 `unprocessed` 策略 |
| `model_id` 身份与防 `fake` 混入 | `infer.py:91–92` 仅在 `fake` 时强制 `--model-id fake`；非 `fake` 时无校验；跨模型报告拦截 `fake` 未实现（`DF-037`） | [inference-entry.md](../eval/inference-entry.md) §4 要求 `model_id` 含基础权重 + adapter/合并版本 + 权重摘要，不得只写模型名；`DF-037` 要求跨模型比较拦截 `fake` | 缺少 `model_id` 规范格式/非 `fake` 守卫与运行侧元信息落盘（记录推理引擎、解码参数、权重摘要与单条耗时） |
| 独占写与崩溃恢复 | `infer.py:112` 先全量构造列表再一次性 `open("x")` 写入 | [base-model-eval-plan.md](../eval/base-model-eval-plan.md) §8.1 要求无中断崩溃且未处理数明确；[inference-entry.md](../eval/inference-entry.md) §6 禁止覆盖或原地追加 | 若 314 条评测在第 200 条崩溃，内存列表全部丢失；应采用启动即独占创建 `open("x")` + 逐条写入 `flush`，中断后新 `run_id` 重跑，保留原文件供审查 |

### 2.2 `script/five_label_eval/frames.py`（`five-label-input-record/3`）与 `config/eval_paths.json` 缺口

| 维度 | 现状（`f4a9a16` 实读） | 契约/决策要求 | 缺口与影响 |
| --- | --- | --- | --- |
| 默认抽帧数 | `frames.py:646` 与 `:887` 默认 `--clips-per-record 3` | `DF-044` / `DEC-003` 第 9 条定为**单请求 8 帧**；[inference-entry.md](../eval/inference-entry.md) §7 指出帧数不是自由参数 | 默认 3 帧易导致误抽；需在抽帧口径落纸后统一默认或强制显式配置并与 `input_id` 绑定 |
| 抽帧规则表示 | `frames.py:56–57` 硬编码静态常量 `CLIP_TO_MODEL_INPUT`（`kind: "ffmpeg_select_nth_decoded_frame"`, `offset: None`）；`identity` 中硬编码 `"selection_rule": "evenly_spaced_inclusive"`（`:715`） | [frame-correspondence-evidence.md](../frame-correspondence-evidence.md) 前置条件 1 要求抽帧口径落纸；[eval-subset.md](../eval/eval-subset.md) §4 要求含缩放时记入 `resize` 字段 | `frames[]` 节点的 `clip_to_model_input` 未记录抽帧规则名、目标帧数、短片策略与缩放参数；外读记录时只能从 `frames` 长度反推 |
| L3 逐帧宽高与 PNG 摘要 | `_extract_frames`（`frames.py:632–643`）仅做 `select+showinfo` 无 `scale` 滤镜；`frames[]` 条目（`:700–709`）**不含** `width`/`height` 与 PNG `sha256` | [input-record.md](../eval/input-record.md) §0 状态表 1/7 与 §17 明确标为「实现较窄」；[eval-subset.md](../eval/eval-subset.md) §4 要求 `max_pixels` 缩放策略入记录 | 无法直接从 `records.jsonl` 校验 L3 PNG 字节是否被改动或经何种 `max_pixels` 缩放；推理前若需验 PNG 完整性缺少哈希锚点 |
| L3 目录定位 | `records.jsonl` 仅存 `frames[].image`（如 `frame_001.png`），不记录父目录相对路径 | 下游 `infer.py` 与 `DEC-005` 抽帧取证均需定位 L3 帧文件 | 必须明确 `frames_dir` CLI 契约（如默认与 `records.jsonl` 同级目录 `<records_dir>/<candidate_id>/<image>`，或显式 `--frames-dir`） |
| `config/eval_paths.json` `gpu-train` | 9 个键全部为 `TODO_MIGRATION_FILL:<key>`（`eval_paths.json:15–26`）；`paths.py:20,58` 将其解析到 `/nonexistent/...` | 训练机运行评测前须填入实际路径并经核对 | 目前在训练机调用 `--profile gpu-train` 会因 `/nonexistent/...` 立即失败，须完成第 5 节核对后再更新 |
| Python 与依赖边界 | [pyproject.toml](../../pyproject.toml) 约束 `requires-python = ">=3.11,<3.12"`，核心依赖仅有 `av`/`dvc`/`mlflow`/`pandas`/`pyyaml`/`streamlit`/`opencv-python`，开发依赖含 `httpx>=0.28.1` | 训练机 `agent` 环境为 Python 3.11.15（[training-machine-review-runbook.md](../training-machine-review-runbook.md) §2.1）；推理引擎（vLLM/PyTorch/transformers）可能位于独立 conda 环境 | `http` backend 仅需 `httpx`（或标准库 `urllib`）即可直接在 3.11 `agent` 环境中运行，把重量级 GPU 依赖隔离在独立推理服务进程中；而本地 `transformers` backend 必须在含目标 CUDA/PyTorch/transformers 的训练机环境中执行 |

### 2.3 关键结构性结论：为什么必须坚持「L3 预抽帧列表」而不是把 MP4 交给推理服务二次抽帧

根据 `five-label-input-record/3`（[input-record.md](../eval/input-record.md) §1、§10）与 [DEC-005](../decisions/0005-frame-correspondence-evidence.md)，整个溯源链成立的核心前提是：**L3 模型输入帧与 L2 子视频之间由确定性的 `clip_to_model_input`（0 基解码帧号 `clip_frame_index`）绑定**。

- 若直接把 `.mp4` 路径或 `video_url` 交给 vLLM / `qwen-vl-utils` / `AutoProcessor` 内部抽帧：不同后端分别使用 Decord、PyAV、OpenCV 或 TorchCodec，按容器头时长/平均帧率采样，既无法保证与 `ffmpeg -count_frames` 0 基解码帧号一一对应（见 [minicpm-video-loading.md](minicpm-video-loading.md) §2 与 `video_0093` 头部 771 帧 vs 实解码 733 帧案例），也无法在不侵入服务端的情况下回收模型真正看到的帧号，会直接破坏 `DEC-005` 的按次抽帧取证锚点。
- **因此，跨模型评测的首选输入协议应为：先由本仓确定性抽帧产出 `records.jsonl`（`five-label-input-record/3`）与每个候选的 8 张 L3 PNG，再将这 8 张 PNG 作为有序帧序列送入各候选模型。** 若未来确需评测某模型的「原生 `video_url` 端到端加载」（反映完整默认管线），必须将其登记为独立 `input_id` 与独立 run，并在报告中明示「服务端内部二次抽帧、不具备 `DEC-005` 逐帧锚点证明」（符合 [design-test.md](../design-test.md) §2.1、§4.1 区分固定同帧对照与模型原生加载的要求）。

---

## 3. 候选开源视频 VLM 输入机制对照表

本节围绕已选基座 `openbmb/MiniCPM-V-4_5`（`DF-044`）及典型开源视频 VLM 候选（Qwen2.5-VL-7B/32B、InternVL3-8B/14B/38B）对照输入机制与适配成本。

> **核实边界声明**：除「MiniCPM-V-4.5 仓内已验证项」列明具体仓库路径与 `DF-*` 外，其余全部模型参数、处理器行为、vLLM 参数与显存估算均为公开文档整理，统一标记为 **`[外部文档/待训练机核实]`**；具体选用哪些对比模型仍由用户在 `TODO` `EVAL-DESIGN` 确认。

### 3.1 综合对照矩阵

| 对比维度 | MiniCPM-V-4.5（已选基座） | Qwen2.5-VL-7B-Instruct `[外部文档/待训练机核实]` | Qwen2.5-VL-32B-Instruct `[外部文档/待训练机核实]` | InternVL3-8B（及 14B/38B 档位） `[外部文档/待训练机核实]` |
| --- | --- | --- | --- | --- |
| **仓内状态与证据** | **已选基座**（`DEC-003` 第 9 条、`DF-044`）。训练机旧路径 `/home/liuyang/文档/mVllm_2/base-models/minicpmv4_5`（2026-11-14 核实 4 分片 17,391,890,184 B、bf16、36 层）；固定官方 processor 已在本机受控实跑（[minicpm-video-loading.md](minicpm-video-loading.md) §5.3）。注意历史记录显示训练机 `modeling_minicpmv.py` 多了 `self.post_init()`（同文 §1），须现场复核 | 仓内无本地权重与运行记录 `[外部文档/待训练机核实]` | 仓内无本地权重与运行记录 `[外部文档/待训练机核实]` | 仓内无本地权重与运行记录 `[外部文档/待训练机核实]` |
| **单卡 24 GB（4090 级）显存可行性** | 权重磁盘 ~16.2 GiB（17,391,890,184 B，`DF-044`）；bf16 + 8 帧推理在单卡 24 GB 级显卡上可行性高，历史旧链路亦支持 4-bit NF4（跳过 `resampler`，[inference-entry.md](../eval/inference-entry.md) §7）；具体空闲显存与峰值`待训练机实测核对` | ~8B 级（含视觉塔），BF16 权重约 16–17 GB，8 帧 + 受控 `max_pixels` 单卡 24 GB 可行性高 `[外部文档/待训练机核实]` | ~32B 级，BF16 权重约 64+ GB，**单卡 24 GB 不可直接 BF16 运行**；需 AWQ/GPTQ/FP8/4-bit 量化（约 18–20 GB，仍紧绷）或多卡张量并行 `[外部文档/待训练机核实]` | InternVL3-8B（~8B）BF16 约 16–17 GB，单卡 24 GB 可行性高；14B（BF16 ~28–30 GB）与 38B（BF16 ~76 GB）在单卡 24 GB 需量化或多卡 `[外部文档/待训练机核实]` |
| **8 帧输入方式（frames list vs video file）** | **原生支持 frames list**：旧评测加载器与官方 `model.chat` 均由外部抽帧得到 RGB PIL 列表再送 processor（[minicpm-video-loading.md](minicpm-video-loading.md) §2.2、§4.1）；vLLM OpenAI API 可按有序多图 `image_url`（base64）传入 `[外部文档/待训练机核实]` | `transformers` + `qwen-vl-utils` 原生支持在 `type="video"` 中直接传 **frames list**（PIL/ndarray/tensor）或按多图 `image_url` 传入；vLLM OpenAI API 传多图 `image_url` 即可严格固定 8 帧，`video_url` 则由服务端再采样 `[外部文档/待训练机核实]` | 同 Qwen2.5-VL-7B `[外部文档/待训练机核实]` | `transformers` 常规做法是外部抽帧后拼接每帧 `Frame1: <image>\n...` 多图序列（或新 HF 封装的 `apply_chat_template(..., num_frames=8)`）；vLLM OpenAI API 传 8 张 `image_url` + 显式帧序文本可固定 8 帧 `[外部文档/待训练机核实]` |
| **`temporal_ids` / FPS / 时序绑定** | **核心差异点**：4.5 架构具 3D-Resampler，`processor` 接收可选 `temporal_ids`（0.1 s 量化整数分组）。不传（`None`）时回填逐图/逐切片 `[-1]`（零时间嵌入，顺序仍由 `image_bound` 保留，已实跑验证：[minicpm-video-loading.md](minicpm-video-loading.md) §5.3、`DF-016`）；OpenAI 标准 `image_url` 载荷不直接暴露自定义 `temporal_ids` `[外部文档/待训练机核实]` | 原生采用 MRoPE（多维旋转位置编码），`video` 输入通过 `fps` / `second_per_grid_ts` 注入绝对时间尺度，且内部通常将连续 2 帧做时空 patch 合并（`temporal_patch_size=2`，8 帧恰好偶数对齐）；若改用独立多图 `image_url` 传入则退化为无 `fps` 的多图顺序（可在文本中附每帧 `pts_seconds`） `[外部文档/待训练机核实]` | 同 Qwen2.5-VL-7B `[外部文档/待训练机核实]` | 常规多帧方案在 prompt 文本中写 `Frame1 (t=0.00s): <image>` 表达时序，结合 V2PE 可变视觉位置编码；无专门的 `temporal_ids` 整数数组参数 `[外部文档/待训练机核实]` |
| **`max_pixels` / 分辨率上限与切片** | 旧训练/评测先按 `max_pixels=65,536`（256×256）、`min_pixels=256` 规整，再送 4.5 processor（目标面积 ~448²、宽高对齐 14 倍数、`max_slice_nums=2`；官方模型卡示例用 `max_slice_nums=1` 且无 256² 预规整，[minicpm-video-loading.md](minicpm-video-loading.md) §2、§4） | 动态原生分辨率，宽高按 `28`（patch 14 × merge 2）对齐；通过 `min_pixels` / `max_pixels`（在 `AutoProcessor` 或 vLLM `mm_processor_kwargs` 中）直接控制每帧 token 预算，支持按需对齐 65,536（256²）或 200,704（~448²） `[外部文档/待训练机核实]` | 同 Qwen2.5-VL-7B，但 32B 显存更紧，需更严格限制每帧 `max_pixels` 与 `max_model_len` `[外部文档/待训练机核实]` | 固定 `448×448` 动态分块（dynamic tiling），由 `max_num` / `max_dynamic_patch` 控制每帧最大切片数（多帧视频常设为 `max_num=1` 即每帧 1 个 448×448 缩略图以控显存与 token 数）；小画幅（如 `w_le_200` 60×80）会被缩放到 448×448 网格，需注意不得将处理器内部缩放误称为「获得清晰度增量」 `[外部文档/待训练机核实]` |
| **JSON 结构化输出稳定性（五类 11 叶字段中文 JSON）** | 8B 基座在无约束解码下可能出现 Markdown 代码围栏（`` ```json ``）、前后解释文字、省略多选叶项或改写字面量 `[推测/待训练机实测核对]`；`score.py` 已内置宽松提取并单独记 `strict_format_valid`（[output-contract.md](../eval/output-contract.md) §2） | 中文指令遵循与 JSON 稳定性通常较强；vLLM 支持 `guided_json` / `response_format` 约束解码（但 base 摸底阶段是否开启须严格受控，见 §3.2） `[外部文档/待训练机核实]` | 32B 指令遵循与复杂嵌套中文 JSON 稳定性通常优于 7B–8B 级；同样支持 vLLM 约束解码 `[外部文档/待训练机核实]` | 中文与多图理解能力较强；vLLM 支持 `guided_json` / `response_format` 约束解码；`transformers` 侧需依赖 prompt + 低温贪婪解码（`temperature=0`） `[外部文档/待训练机核实]` |
| **与 `five-label-input-record/3` (`clip_to_model_input`) 兼容性** | **完全兼容（高）**：直接消费 `frames.py` 产出的 8 张 L3 PNG 列表即可保持 `clip_frame_index` 逐帧绑定；若启用 `temporal_ids`，须额外记录 `temporal_ids` 量化规则与实算数组（优先走本地 `transformers` backend） | **高（按 8 帧列表输入时）**：将 8 张 L3 PNG 列表直接送入 `transformers` `video` 帧列表或 vLLM 多图 `image_url`，`L2→L3` 帧号完全一致；注意 `image_url`（多图）与 `video`（时空 2 帧合并）在视觉编码路径上不同，须在 `model_id`/配置中明确区分并固定一种 `[外部文档/待训练机核实]` | 同 Qwen2.5-VL-7B `[外部文档/待训练机核实]` | **高（按 8 帧多图输入时）**：8 张 L3 PNG 直接映射为 `Frame1..Frame8` 8 张图输入，与 `clip_to_model_input` 一一对应；若使用 HF `num_frames=8` 传 MP4 则会破坏 L3 绑定，应避免 `[外部文档/待训练机核实]` |

### 3.2 跨模型评测的关键方法论注意事项

1. **受控约束解码（`guided_json` / `response_format`）的启用边界**：
   - [base-model-eval-plan.md](../eval/base-model-eval-plan.md) §6.1 与 §8.1 明确规定：**base 阶段格式合法率（`strict_format_valid`）本身是待测产出指标，且主指标包含失败率**。
   - 若在首轮 run A 对 vLLM 模型开启 `guided_json` 而对 `transformers` 模型不开启，会造成跨模型不公平对比（掩盖模型真实的中文键名与嵌套枚举遵循能力）。
   - **建议**：首轮基座摸底默认**关闭** constrained decoding（统一使用 `temperature=0.0` / 贪婪解码 + 冻结 `five_label_v2.txt` 原文）；若后续需评估「约束解码能否挽救格式失败」，必须作为独立 `run_id`（并在解码配置中显式标注 `guided_json=true`）单独报告，不与无约束 run 混算。
2. **「多图 `image_url`」与「视频 `video` 张量」路径差异**：
   - 对 MiniCPM-V-4.5（3D-Resampler + `temporal_ids`）与 Qwen2.5-VL（`temporal_patch_size=2` + `fps` MRoPE），用多图 `image_url` 顺序传 8 张 PNG 与用原生视频张量接口传同一组 8 张 PNG，**视觉编码器的时间建模路径并不等价** `[外部文档/待训练机核实]`。
   - 因此，同一批实验必须把「输入通道类型（`multi_image_png` vs `video_frames_tensor`）」写入运行配置与 `input_id`/运行元数据；且按 [design-test.md](../design-test.md) §4.1，跨模型比较应明示这是「模型 + 对应输入配置」的整体表现。
3. **时间戳文本与 3b 顺序对照防泄露**：
   - 现行 [five_label_v2.txt](../../script/five_label_eval/prompts/five_label_v2.txt) 第 1 行明确写道「请只看画面内容作答：可用的帧图像、帧的先后顺序、以及每帧的时间戳」。
   - 这意味着主任务（run A）允许在多图/多帧输入侧按冻结格式提供每帧的相对时间戳（如 `pts_seconds` 相对片段起点的秒数），**但绝不允许把文件名、路径、`candidate_id` 或原视频绝对时间写进请求文本**；同时在未来 3b 顺序对照（A→B / B→A）中必须移除或重写时间戳与 `temporal_ids`，避免泄露原始帧序（见 [minicpm-video-loading.md](minicpm-video-loading.md) §6 第 5 条、[design-test.md](../design-test.md) §4.3）。
4. **`w_le_200` 小画幅与模型内缩放**：
   - 第 2 批 1,633 条候选中，按 [data/sub_video/manifest.json](../../data/sub_video/manifest.json) 实测：`w_le_200` 占 **881 条（53.9%）**、`w_200_400` 占 **448 条（27.4%）**、`w_gt_400` 占 **304 条（18.6%）**，宽度跨度 `60–924 px`、高度 `80–1232 px`。
   - 按 [eval-subset.md](../eval/eval-subset.md) §3–§4，禁止在前置预处理中主动放大（upscale）小画幅来抹平分档；即便某些模型处理器（如 InternVL3 的 448×448 tile 或 MiniCPM 的 14 倍数对齐）内部会做插值适配，报告仍必须严格按 L2 原始宽度 `size_bucket` 三档分列输出、不得跨档合并。

---

## 4. 「模型输入抽帧口径落纸」方案对比（DEC-005 前置条件 1 决策输入）

[帧对应抽帧取证](../frame-correspondence-evidence.md) §「实现前置条件与失效条件」规定：
> 1. 模型输入抽帧口径须先落纸。
> 2. 映射字段命名已定案并落地（任务 7 `MAPPING-NODE-RENAME`，`DF-052` 已完成）。

因此，**敲定本节抽帧口径是解锁 DEC-005 抽帧取证落地与正式 run A 抽帧的最后一项口径前提**。

### 4.1 当前第 2 批子视频真实分布基线（仓内实测）

直接统计 [data/sub_video/manifest.json](../../data/sub_video/manifest.json)（1,633 条候选，2026-11-24 实测）：

| 角色（`role`） | 候选数 | 含锚点数 | 帧数范围（最小 / 中位 / 最大） | 时长范围（`output.media.duration`，最小 / 中位 / 最大） | 帧率范围 |
| --- | ---: | ---: | --- | --- | --- |
| `pre` | 825 | 0 | 50 / 150 / 600 | 2.00 s / 5.00 s / 20.07 s | 25–30 fps |
| `fracture` | 576 | 576 | 45 / 125 / 600 | 1.50 s / 5.00 s / 20.00 s | 25–30 fps |
| `post` | 127 | 0 | 46 / 68 / 460 | 1.53 s / 2.40 s / 15.33 s | 25–30 fps |
| `coverage` | 93 | 0 | 177 / 600 / 600 | 5.90 s / 20.00 s / 20.00 s | 25–30 fps |
| `no_fracture` | 9 | 0 | 60 / 150 / 600 | 2.00 s / 5.00 s / 20.00 s | 25–30 fps |
| `unclamped` | 3 | 3 | 60 / 90 / 150 | 2.00 s / 3.00 s / 5.00 s | 25–30 fps |
| **合计** | **1,633** | **579** | **45 / 150 / 600（`< 8` 帧为 0 条）** | **1.50 s / 5.00 s / 20.07 s** | **25–30 fps** |

额外实测约束：
- 1,633 条候选中没有任何片段少于 8 帧（最短 45 帧 / 1.50 s）；上表时长按清单 `output.media.duration` 实测统计（`video_0099_pre_05` 的 `output.media.duration = 20.067 s`，约 `20.07 s`，而按 `total_frames / fps = 600 / 30` 为 `20.00 s`）。
- 579 条带锚点候选共有 1,155 个锚点，其相对位置 `output_frame / (total_frames - 1)` 分布在 `[0.184, 1.000]`（P10 = `0.203`，P50 = `0.503`，P90 = `0.802`，恰落在首尾端点 1 个）。
- 若沿用旧项目 `2 fps` 上限 8 帧公式 `max(1, min(int(duration * 2.0), 8, total_frames))`，会在 **746 / 1,633 条（45.7%）** 短于 4.0 s 的片段上抽出少于 8 帧（1.5 s 片段仅抽 3 帧）。

### 4.2 四种候选抽帧口径对比

| 方案 | 抽帧公式（0 基可解码帧 `total = L2.total_frames`） | 第 2 批（1,633 条）实测特性 | 优点 | 缺点与风险 | 推荐结论 |
| --- | --- | --- | --- | --- | --- |
| **方案 A：全片均匀含首尾固定 8 帧（`evenly_spaced_inclusive`）** | `count = 8`（`total >= 8` 时）；`idx[i] = round(i * (total - 1) / 7)`，`i = 0..7`（与 `frames.py:687` 现有公式完全一致） | 全量 1,633/1,633 稳定产出 8 帧；相邻帧间隔 `0.233–2.880 s`（中位 `0.733 s`，P90 `2.867 s`）；距 1,155 个已知锚点最近帧距中位 `0.233 s`、P90 `0.667 s`、最大 `1.233 s` | 1. **必含首帧 `0` 与末帧 `total-1`**，最利于完整呈现「初始状态→最终状态」变化（直接支撑 `未断裂 / 发生断裂 / 已断裂` 判别）；<br>2. **完全无真值泄露**，不依赖任何标注或角色；<br>3. **与 `frames.py` 现有代码零公式差异**，纯整数 0 基解码索引，训练与推理完全一致；<br>4. 满足 `DF-044` 固定 8 帧约束 | 20 s 长片（如 `coverage`）帧间隔约 2.86 s，极短暂瞬时断裂或微小开裂可能落在两帧之间（需靠「完整片段 vs 实际输入」双轨评价暴露，而非偷改抽帧） | **推荐默认主口径** |
| **方案 B：全片均匀分桶中点固定 8 帧（`uniform_bucket_midpoint`）** | `idx[i] = min(total - 1, floor((i + 0.5) * total / 8))`，`i = 0..7`（类似 MiniCPM 官方卡分桶中点） | 全量 1,633/1,633 稳定产出 8 帧；距 1,155 个已知锚点最近帧距中位 `0.133 s`、P90 `0.300 s`、最大 `0.700 s`（略近于方案 A，因多数锚点位于片内 20%–80%） | 中段桶中心采样更贴近片内中部事件，减少片头/片尾静止帧占比 | **丢失首帧 `0` 与末帧 `total-1`**（20 s 片段首帧落在 ~1.25 s、末帧落在 ~18.75 s，首尾共丢 ~2.5 s），对结尾才出现断裂或脱夹的片段不利；且需修改 `frames.py:687` 现有已测公式 | 可作次选备选（仅当用户明确偏好中段密集、接受丢首尾时考虑） |
| **方案 C：旧 `2 fps` 上限 8 帧（`fps_capped_2fps_max8`）** | `n = max(1, min(int(duration * 2.0), 8, total))`，再 `linspace(0, total-1, n)` | **746 / 1,633 条（45.7%）** 抽出 `< 8` 帧（1.5 s 断裂片仅 3 帧） | 仅与旧 v4.1 代码静态一致 | 直接违背 `DF-044` 统一 8 帧契约与历史 `max_frames=8` 硬要求；短断裂/断后片段本就信息紧张却被反向降帧 | **明确不推荐** |
| **方案 D：按时长自适应（>8 帧）或锚点加密** | 长片 >8 帧；或在断裂锚点前后加密取帧 | — | 理论上可提升长片或锚点附近覆盖 | ① `>8` 帧违背 `DF-044`（4090 显存限制下训练与推理统一 8 帧）；② 锚点加密在真实推理/测试期不可用且构成**严重标签泄露**（违反 [design-test.md](../design-test.md) §6 与 [prompt.md](../eval/prompt.md)） | **禁止作为主评测口径**（锚点分析仅可用于离线诊断，绝不可进主评测输入） |

### 4.3 `clip_to_model_input` 与 `input_id` 参数表示草案

当前 [frames.py](../../script/five_label_eval/frames.py)（56–57、714–725 行）已把 `selection_rule: "evenly_spaced_inclusive"` 与 `clips_per_record` 纳入 `input_id` 哈希，但 `frames[].frame_index_mapping.clip_to_model_input` 仍是无参数的静态常量：

```json
{
  "kind": "ffmpeg_select_nth_decoded_frame",
  "offset": null,
  "reason": "L3 帧由 ffmpeg select=eq(n\\,clip_frame_index) 从 L2 按解码序抽取"
}
```

待用户拍板抽帧口径后，建议在**不破坏 `clip_to_model_input` 节点名与 `L2 → L3` 方向（`DF-052`）**的前提下，在记录顶层或 `clip_to_model_input` 中显式固化以下参数（任何一项改变即改变 `input_id`；若改动 `record_schema` 字段结构须按惯例同步升版本号与测试）：

| 参数字段（建议） | 推荐默认取值 | 说明 |
| --- | --- | --- |
| `sampling_rule` | `"evenly_spaced_inclusive"` | 抽帧公式标识；与 `frames.py:715` 现值一致 |
| `target_frame_count` | `8` | 固定目标帧数（对齐 `DF-044`；不再沿用 `frames.py` 当前默认 `3`） |
| `short_clip_policy` | `"fail_closed"`（或待拍板） | `total_frames < 8` 时的确定性策略（见 §4.4 问题 2） |
| `resize` | `null`（不缩放）或 `{"method": "area_cap", "max_pixels": 65536, "min_pixels": 256, "upscale": false}` | 对齐 [eval-subset.md](../eval/eval-subset.md) §4：记录抽帧落盘阶段是否做缩放；`null` 表示 L3 PNG 保持 L2 原始像素，由各模型 processor 自行处理 |
| `temporal_ids_policy` | `"none"` / `"quantized_0.1s"` / `"not_applicable"` | 记录时间位置编码注入策略，供 MiniCPM 3D-Resampler 与 3b 顺序对照追溯 |
| `frames[].width` / `height` / `sha256` | 实测整数与 64 位小写 hex | 补齐 [input-record.md](../eval/input-record.md) §0 状态表 1/7 的「实现较窄」缺口，使 `infer.py` 与 `DEC-005` 工具可直接校验 L3 PNG 完整性 |

### 4.4 需要用户拍板的 4 个边界问题

1. **抽帧公式定案（DEC-005 前置条件 1）**：是否确认采用**方案 A（`evenly_spaced_inclusive`，固定 8 帧）**作为本轮正式默认口径，并将 `frames.py` 的默认帧数对齐为 8？
2. **极短片段（`total_frames < 8`）处置策略**：虽然第 2 批 1,633 条最短为 45 帧（0 条 `<8`），但未来虚拟试制或异常短片可能触及该边界。建议选其一：
   - **选项 1（推荐）**：`fail_closed` 直接报错拒绝进入 8 帧主评测批次（避免静默改变帧数语义）；
   - **选项 2**：保留全部 `total_frames` 帧（去重升序），在记录中显式标记 `actual_frame_count < target_frame_count`；
   - **选项 3**：重复末帧补齐至 8 帧（注意会引入重复帧，影响 `clip_frame_index` 唯一性，不推荐）。
3. **`max_pixels` 缩放归属**：
   - **选项 1（推荐）**：L3 PNG 保持 L2 原始画幅不缩放（`resize: null`），各模型在各自 processor / `mm_processor_kwargs` 中按约定 `max_pixels`（例如 MiniCPM 沿用 `65,536` 或官方 448²，需单独确认具体数值）处理并把 `max_pixels` 写入运行身份；优点是一份 L3 PNG 既满足 `DEC-005` 清晰人工查阅，又可被不同模型复用；
   - **选项 2**：在 `frames.py` 落盘 L3 PNG 前统一按 `max_pixels=65,536`（只缩不放）缩放，所有模型看到严格同像素 PNG；缺点是限制了高分辨率优势模型的上限且人工看 L3 证据图变模糊。
4. **MiniCPM-V-4.5 时序与切片参数**：首轮基座摸底（run A）是沿用旧链路（`temporal_ids=None`、`max_slice_nums=2`、`max_pixels=65,536` 规整，便于与历史 v4.1 链路对照），还是采用官方模型卡风格（0.1 s 量化 `temporal_ids` + `max_slice_nums=1`）？两者属于不同 `input_id`/运行配置，不可混算。

---

## 5. 训练机启动前资源与环境核对清单（Pre-flight Runbook）

> **硬红线：完成本节全部只读核对并把实测结果留存记录前，不得启动任何正式基座模型评测，也不得盲目填改 `config/eval_paths.json` 的 `gpu-train` 占位符。**

### 5.1 仓内已有训练机基线 vs 待现场核对项

| 核对类别 | 仓内已有记录（不可代替现场复核） | 本轮尚未核验（`待训练机实测核对`） |
| --- | --- | --- |
| 入口与工作区 | `ssh liuyang@100.70.83.68`（必须显式写用户名，主机名 `dell-Precision-3660` 不可省略用户名）；项目落点 `/home/liuyang/文档/TensileAgent-Finetune`（非 git 仓库），见 `DF-046` 与 [training-machine-review-runbook.md](../training-machine-review-runbook.md) §2 | 当前工作区 `script/five_label_eval/`、`docs/`、`data/sub_video/manifest.json` 是否已与本机最新提交同步 |
| CPU / 内存 / 磁盘 / 媒体工具 | 32 核、可用内存约 122 GB、`~/文档` 所在分区可用 536 GB、`ffmpeg`/`ffprobe` 4.4.2、`/home/liuyang/miniconda3/envs/agent/bin/python3.11`（3.11.15），见 [training-machine-review-runbook.md](../training-machine-review-runbook.md) §2.1 | 当前实时磁盘余量（若需新增 7B/8B/32B 权重，每套 8B 约需 16–20 GB、32B 约需 65 GB `[外部文档/待训练机核实]`） |
| GPU 与驱动 | 仅在 `DF-044` / `DEC-003` 中提到「受 4090 显存限制」，**无本轮 `nvidia-smi` 实测记录** | GPU 确切型号、卡数、总显存、当前空闲显存、占用进程、驱动版本与支持的最高 CUDA 版本 |
| 推理框架与依赖 | 仅确认 `agent` 环境 Python 3.11.15 | 全部 conda/venv 环境列表；CUDA Toolkit、PyTorch（含 `torch.cuda.is_bf16_supported()`）、`transformers`、`vllm`、`sglang`、`accelerate`、`bitsandbytes`、`flash_attn`、`decord`、`av`、`qwen_vl_utils`、`httpx`、`Pillow` 实际版本 |
| 本地模型权重 | `DF-044`（2026-11-14）核实 `/home/liuyang/文档/mVllm_2/base-models/minicpmv4_5` 存在 4 分片共 17,391,890,184 B、bf16、36 层；历史记录显示该目录 `modeling_minicpmv.py` 较官方多 `self.post_init()`（[minicpm-video-loading.md](minicpm-video-loading.md) §1） | `minicpmv4_5` 关键源码/配置/分片当前 SHA-256 与官方 revision 核对；其他候选模型（Qwen2.5-VL / InternVL3）是否已存在于本地或 HF 缓存及离线可用性 |

### 5.2 可直接复制执行的只读只查命令清单

以下所有命令均为**严格只读查询**（不修改任何文件、不下载权重、不启动服务或训练），可直接在本机通过 SSH 发往训练机执行并重定向保存日志到仓外目录（如本机 `/private/tmp/gpu-preflight-$(date +%Y%m%d).log`）：

#### 步骤 1：GPU、显存、当前进程与系统资源

```bash
ssh liuyang@100.70.83.68 '
echo "=== HOST & DATE ==="
hostname && date -Is
echo "=== NVIDIA-SMI ==="
nvidia-smi
echo "=== GPU CSV ==="
nvidia-smi --query-gpu=index,name,driver_version,memory.total,memory.used,memory.free,compute_cap --format=csv
echo "=== MEMORY & DISK ==="
free -h
df -h /home/liuyang /home/liuyang/文档 /tmp
'
```

#### 步骤 2：Conda / Python 环境与推理包版本盘点

```bash
ssh liuyang@100.70.83.68 '
echo "=== CONDA ENVS ==="
/home/liuyang/miniconda3/bin/conda env list 2>/dev/null || ls -la /home/liuyang/miniconda3/envs
echo "=== AGENT ENV CHECK ==="
/home/liuyang/miniconda3/envs/agent/bin/python3.11 -c "
import sys
print(\"python:\", sys.version)
for pkg in (\"torch\", \"torchvision\", \"transformers\", \"vllm\", \"sglang\", \"accelerate\", \"bitsandbytes\", \"flash_attn\", \"decord\", \"av\", \"qwen_vl_utils\", \"httpx\", \"PIL\", \"cv2\"):
    try:
        m = __import__(pkg)
        ver = getattr(m, \"__version__\", \"installed(no __version__)\")
    except Exception as e:
        ver = f\"MISSING ({type(e).__name__})\"
    print(f\"  {pkg:16s}: {ver}\")
try:
    import torch
    print(\"  cuda_available  :\", torch.cuda.is_available())
    print(\"  cuda_version    :\", torch.version.cuda)
    if torch.cuda.is_available():
        print(\"  bf16_supported  :\", torch.cuda.is_bf16_supported())
        print(\"  device_count    :\", torch.cuda.device_count(), [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())])
except Exception as e:
    print(\"  torch_probe_err :\", e)
"
'
```

> 若训练机存在其他专用推理环境（例如 `vllm`、`llamafactory`、`mvllm`），对步骤 2 输出中的每个环境路径替换解释器重复上述只读探针即可。

#### 步骤 3：本地模型权重目录与 MiniCPM-V-4.5 身份/差异核对

```bash
ssh liuyang@100.70.83.68 '
echo "=== CANDIDATE MODEL DIRS ==="
ls -lh /home/liuyang/文档/mVllm_2/base-models 2>/dev/null || echo "base-models dir not found"
du -sh /home/liuyang/文档/mVllm_2/base-models/* 2>/dev/null || true
ls -lh ~/.cache/huggingface/hub 2>/dev/null || echo "no default hf cache"

echo "=== MINICPM-V-4.5 SMALL FILES & SHARDS SHA256 ==="
DIR="/home/liuyang/文档/mVllm_2/base-models/minicpmv4_5"
if [ -d "$DIR" ]; then
  ls -la "$DIR"
  sha256sum "$DIR"/config.json "$DIR"/preprocessor_config.json \
    "$DIR"/processing_minicpmv.py "$DIR"/image_processing_minicpmv.py \
    "$DIR"/modeling_minicpmv.py "$DIR"/resampler.py 2>/dev/null || true
  grep -n "post_init" "$DIR"/modeling_minicpmv.py 2>/dev/null || true
  stat -c "%s %n" "$DIR"/*.safetensors 2>/dev/null || true
fi
'
```

对照基线（仓内已知）：
- 2026-11-10 官方固定 `openbmb/MiniCPM-V-4_5@daef484c...` 的两个处理器源码 SHA-256 见 [minicpm-video-loading.md](minicpm-video-loading.md) §5.3：
  - `processing_minicpmv.py`: `aeb292555aba3362108eb10827234c48b9fede526398cc15bdbec798ba2c7fdd`
  - `image_processing_minicpmv.py`: `52888748938f40fec0827d187383b4a8fa857f4cffad5a0939e2e449051950d7`
- 若训练机现场核出的 SHA-256 与官方不一致（例如 `modeling_minicpmv.py` 存在本地 `self.post_init()` 修改），须在 `model_id` 身份说明中显式记录该目录快照摘要，不得谎称为官方原样权重。

#### 步骤 4：数据与路径一致性核对（为填充 `config/eval_paths.json` 的 `gpu-train` 做准备）

```bash
ssh liuyang@100.70.83.68 '
ROOT="/home/liuyang/文档/TensileAgent-Finetune"
cd "$ROOT" || exit 1
echo "=== MEDIA COUNTS ==="
printf "source_videos   : %s\n" "$(find data/videos -maxdepth 1 -name "*.mp4" 2>/dev/null | wc -l)"
printf "roi_videos      : %s\n" "$(find data/roi/videos -maxdepth 1 -name "*.mp4" 2>/dev/null | wc -l)"
printf "sub_video_videos: %s\n" "$(find data/sub_video/videos -maxdepth 1 -name "*.mp4" 2>/dev/null | wc -l)"
echo "=== KEY FILE SHA256 ==="
sha256sum data/sub_video/manifest.json data/splits/three-fold/*.json docs/label.md \
  script/five_label_eval/prompts/five_label_v2.txt 2>/dev/null || true
echo "=== EVAL_PATHS CURRENT ==="
cat config/eval_paths.json 2>/dev/null || echo "config/eval_paths.json missing"
'
```

核对通过标准（与本机一致）：
- `source_videos = 110`、`roi_videos = 110`、`sub_video_videos = 1,633`；
- `data/sub_video/manifest.json` SHA-256 必须等于 `c70686630c8fa0277305cc25a09821bc04ab853f6ce8a6ac3ca795998c08ac0f`；
- `script/five_label_eval/prompts/five_label_v2.txt` SHA-256 必须等于 `cf299d672281e12ea5f3964bb08ffbe2d237e1dfad3503861e7e21a5872cc4cf`（[prompt.md](../eval/prompt.md) §5）；
- `output_dir` 与 `score_output_dir` 在 `gpu-train` 中应指向仓库目录之外（例如 `/home/liuyang/tensile-eval-runs/...`），避免把大规模 PNG 帧图与预测产物写入项目目录。

### 5.3 单条推理耗时与超时预算估算方法

- **既有超时契约**：`DEC-003` 第 4 条与 [inference-entry.md](../eval/inference-entry.md) §7 沿用单请求超时上限 **`600.0` 秒**（性能与超时本轮只记录、不设门槛）。
- **整批耗时估算（`[推测/待训练机实测核对]`）**：
  - 按 [design-test.md](../design-test.md) §7.2，首轮不默认并发，逐条串行推理，且**首次冷启动加载耗时**与**稳定态单条耗时**分开记录。
  - 在 B1 固定 test 314 条规模下（8 帧输入、输出 JSON 约 120–200 tokens）：
    - 若单卡 4090 上 8B 级模型稳定态单条耗时在 `3–10 s` `[外部文档/待训练机核实]`，则 314 条总耗时约 `16–52 min`（不含模型加载与预抽帧）；
    - 若使用 4-bit 量化或高切片数导致单条耗时升至 `15–30 s` `[外部文档/待训练机核实]`，则 314 条总耗时约 `1.3–2.6 h`；
    - 32B 级量化/多卡路径单条耗时与显存余量波动较大，必须先做 5–10 条开发集冒烟测量后再估算整批时间窗口。
- **实测标定规程**：正式启动 314 条 B1 前，须先在 **5–10 条开发集候选**（覆盖三个画幅档 `w_le_200` / `w_200_400` / `w_gt_400` 与 2 s / 20 s 两种时长）上跑冒烟，实测 `cold_load_seconds`、`p50`/`p95`/`max` 单条延迟、峰值显存（`nvidia-smi`）与超时触发行为，再确认是否维持 `600.0 s` 或调整单条超时上限（任何超时值调整须写入运行元数据，且不静默忽略预算）。

---

## 6. 最小适配器落地路线（供用户审批后实施）

> 本节为实施方案提案，**待用户审批确认第 4.4 节待决项并完成第 5 节训练机核对后再立项实施**；本文不改动 `script/five_label_eval/` 任何代码。

### 6.1 核心设计原则

1. **契约不变项严格锁定**：`fake` / `http` / `transformers` 三个 backend 共用同一套 `infer.py` CLI 身份校验、`predictions.jsonl` 行结构、`STATUS` 四态语义（`success` / `request_failed` / `timeout` / `unprocessed`）与独占不覆盖输出约束（[inference-entry.md](../eval/inference-entry.md) §8、[output-contract.md](../eval/output-contract.md) §3）。
2. **输入先落盘、再推理**：所有 backend 均消费 `frames.py` 产出的 `records.jsonl`（`five-label-input-record/3`）+ L3 PNG 文件，绝不在 `infer.py` 内部静默重抽 MP4，确保与 `DEC-005` 抽帧取证同源。
3. **重依赖隔离**：`infer.py` 主框架与 `http` backend 仅依赖标准库 + `httpx`（已在 [pyproject.toml](../../pyproject.toml) 开发依赖中），不强绑 `torch`/`transformers`/`vllm`；`transformers` backend 采用惰性导入（仅在 `--backend transformers` 时导入），保证本机 Mac（无 GPU/无 torch）与 CI 全量 `pytest` 零负担运行。

### 6.2 推荐模块边界

```text
script/five_label_eval/
├── frames.py                  # [小幅补齐] 对齐默认 8 帧、记录抽帧口径参数与 L3 PNG 宽高/SHA-256
├── infer.py                   # [扩展] 保留 main(argv=None) -> int；新增 --backend http、--frames-dir、超时与逐条落盘
└── backends/                  # [新增薄目录]
    ├── __init__.py            # InferenceRequest / InferenceResult 数据类与统一 Protocol
    ├── fake_backend.py        # 迁移现有 deterministic fake 逻辑，行为与测试 100% 等价
    ├── http_backend.py        # 优先落地：OpenAI-compatible POST /v1/chat/completions（覆盖 vLLM / SGLang）
    └── transformers_backend.py # 薄本地适配：直连 MiniCPM-V-4.5（含 temporal_ids / max_slice_nums / SIGALRM 超时）
```

#### 统一 Backend 接口契约（草案）

- **输入 `InferenceRequest`**：`candidate_id`、`record`（已通过 `read_records` 与推理前 `verify_lineage` + L3 PNG 存在性/摘要校验）、`frame_paths`（按 `display_order` 排好序的 `list[Path]`）、`frame_pts_seconds`（`list[float]`）、`prompt_text`（`load_prompt` 原文不 `strip`）、`timeout_seconds`、`decode_config`（`temperature`、`max_tokens`、`seed`、`extra_body` 等）。
- **输出 `InferenceResult`**：`status`（`"success" | "request_failed" | "timeout"`）、`raw_output`（`str | None`，非 `success` 强制 `None`）、`latency_seconds`、`error_detail`（写入独立 `run_meta.jsonl` 或日志，不污染 `score.py` 评分解析，注意 `predictions.jsonl` 仍遵守 [output-contract.md](../eval/output-contract.md) §3 禁止旁挂结构化标签字段的红线）。

#### 路线 1：OpenAI-compatible `http` backend（优先落地，覆盖多模型服务）

- **适用对象**：vLLM / SGLang 启动的 Qwen2.5-VL-7B/32B、InternVL3-8B/14B/38B、以及支持 OpenAI API 的 MiniCPM-V-4.5 与未来 `TensileAgent` HTTP 服务（衔接 [agent-handoff-contract-draft.md](../eval/agent-handoff-contract-draft.md) §2.2）。
- **请求构造**：将 8 张 L3 PNG 编码为 `data:image/png;base64,...` 的有序 `image_url` 项，按 `display_order` 排列，与 `prompt_text` 组成单轮 `user` 消息；通过 `--api-model-name` 指定服务端路由模型名，与严格权重身份 `--model-id`（含权重摘要）分离；认证密钥仅通过 `--api-key-env` 指定环境变量名读取，严禁命令行明文传 key。
- **可选契约探测**：支持 `--contract-endpoint`（如 `GET /v1/tensile/contract`），配置时在请求前 fail-closed 核对服务端声明的模型/契约身份。
- **三态映射**：
  - `httpx.TimeoutException` → `status="timeout"`, `raw_output=None`；
  - `httpx.RequestError` / HTTP 非 2xx / 响应 JSON 异常 / `choices` 为空 / `message.content` 非字符串或空串 → `status="request_failed"`, `raw_output=None`；
  - 正常返回非空字符串 → `status="success"`, `raw_output=<原文不做 strip 或围栏剥离>`。

#### 路线 2：薄本地 `transformers` backend（覆盖 MiniCPM-V-4.5 专属 `temporal_ids`）

- **适用对象**：直接落实 `DF-044`（`openbmb/MiniCPM-V-4_5` + `transformers`），并支持对 `temporal_ids`、`max_slice_nums`、`max_pixels` 像素规整做精确受控实验（这些参数无法通过标准 OpenAI `image_url` 接口完整透传）。
- **加载与身份保护**：强制 `local_files_only=True`、`trust_remote_code=True`（与历史 `model_runtime.py` 一致）；启动时计算模型目录关键配置文件及处理器源码 SHA-256 写入 `run_meta.json`，防止静默加载非预期代码。
- **超时与异常隔离**：复用 [inference-entry.md](../eval/inference-entry.md) §7 的 POSIX `SIGALRM` + `signal.setitimer(ITIMER_REAL)` 机制，非主线程或缺 `SIGALRM` 时 fail-closed 抛 `RuntimeError`（不静默忽略超时）；触发超时记 `status="timeout"`，捕获 `torch.cuda.OutOfMemoryError`（清理显存缓存后继续下一条）或其他单条推理异常记 `status="request_failed"`，确保单条失败不中断整批。

### 6.3 分阶段实施与测试策略

| 阶段 | 范围与交付物 | 验收与测试策略（严格区分合成测试与训练机实跑） |
| --- | --- | --- |
| **阶段 0（决策与核对）** | 用户确认 §4.4 四个边界问题；在训练机执行 §5.2 只读核对并留档；确定首批对比模型名单 | 产出训练机 Pre-flight 核对记录；更新 `DEC-005` 前置条件 1 状态 |
| **阶段 1（本机开发与单测）** | 1. 补齐 `frames.py` 8 帧默认口径与 L3 宽高/SHA-256；<br>2. 实现 `backends/` 抽象层 + `http_backend` + `transformers_backend` 骨架 + `infer.py` 逐条落盘与 `verify_lineage` 前置校验；<br>3. 补齐 `DF-037` 跨模型报告拦截 `fake` 的守卫 | **本机纯单测/mock 测试（无 GPU、无真实权重）**：<br>- `http_backend`：用 `httpx.MockTransport` 覆盖 200 正常、4xx/5xx、空 content、连接断开、超时映射、8 帧 base64 顺序保真、`prompt_text` 字节零修改、严禁泄露 `candidate_id`/文件路径；<br>- `transformers_backend`：用 stub processor/model 覆盖 `temporal_ids` 透传、帧序一致、`SIGALRM` 超时、OOM 映射 `request_failed`；<br>- 回归全量 `pytest` + `script.checks.facts`（`gone == 0`, `ambiguous == 0`） |
| **阶段 2（训练机冒烟验证）** | 填充并核对 `config/eval_paths.json` 的 `gpu-train`；在 **5–10 条开发集片段**上实跑 MiniCPM-V-4.5（`transformers`）与候选对比模型（`http`/vLLM） | 核对冷启动耗时、单条 P50/P95、显存峰值、`predictions.jsonl` 通过 `score.py` 评分、并验证 `DEC-005` 按次抽帧取证回溯闭环；开发集冒烟结果不得混作正式 test 结论 |
| **阶段 3（授权后正式 run A）** | 取得用户正式评测授权后，在已审完的 B1 固定 test（314 条）上按 [base-model-eval-plan.md](../eval/base-model-eval-plan.md) §4、§8.1 执行 run A | 按 §8.1 (a) 类判据验收 run 完整性，按画幅三档与来源级/片段级并列报告，再由用户决定是否进入 run B/C 及确定后续微调与阈值 |

---

## 7. 来源、核对范围与失效条件

### 7.1 仓内已核实证据

- 任务与决策：[docs/TODO.md](../TODO.md)（§2 `EVAL-DESIGN` 后续前置工作、§6 `SUBVIDEO-HUMAN-REVIEW`）、[docs/decisions/README.md](../decisions/README.md)、[DEC-003](../decisions/0003-five-label-eval-scope.md)、[DEC-004](../decisions/0004-fragment-label-no-value-removal.md)、[DEC-005](../decisions/0005-frame-correspondence-evidence.md)。
- 事实账本：[docs/facts.yaml](../facts.yaml)（`DF-016`、`DF-018`、`DF-019`、`DF-027`、`DF-028`、`DF-030`、`DF-032`、`DF-037`、`DF-041[superseded]`、`DF-043`、`DF-044`、`DF-046`、`DF-048`、`DF-049`、`DF-051`、`DF-052`）。
- 评测契约与方案：[docs/design-test.md](../design-test.md)、[docs/frame-correspondence-evidence.md](../frame-correspondence-evidence.md)、[docs/eval/README.md](../eval/README.md)、[docs/eval/base-model-eval-plan.md](../eval/base-model-eval-plan.md)、[docs/eval/inference-entry.md](../eval/inference-entry.md)、[docs/eval/input-record.md](../eval/input-record.md)、[docs/eval/prompt.md](../eval/prompt.md)、[docs/eval/output-contract.md](../eval/output-contract.md)、[docs/eval/eval-subset.md](../eval/eval-subset.md)、[docs/eval/agent-handoff-contract-draft.md](../eval/agent-handoff-contract-draft.md)。
- 既有调研与运行手册：[docs/research/minicpm-video-loading.md](minicpm-video-loading.md)、[docs/training-machine-review-runbook.md](../training-machine-review-runbook.md)、[docs/subvideo-current-logic.md](../subvideo-current-logic.md)。
- 代码、配置与清单实读：[script/five_label_eval/infer.py](../../script/five_label_eval/infer.py)、[script/five_label_eval/frames.py](../../script/five_label_eval/frames.py)、[script/five_label_eval/paths.py](../../script/five_label_eval/paths.py)、[script/five_label_eval/score.py](../../script/five_label_eval/score.py)、[script/five_label_eval/prompt_id.py](../../script/five_label_eval/prompt_id.py)、[script/five_label_eval/prompts/five_label_v2.txt](../../script/five_label_eval/prompts/five_label_v2.txt)、[script/five_label_eval/README.md](../../script/five_label_eval/README.md)、[config/eval_paths.json](../../config/eval_paths.json)、[pyproject.toml](../../pyproject.toml)、[data/sub_video/manifest.json](../../data/sub_video/manifest.json)。

### 7.2 外部参考边界（均标记为 `[外部文档/待训练机核实]`）

- Qwen2.5-VL 官方/vLLM 多模态视频与 `mm_processor_kwargs`（`max_pixels`/`fps`）、frames list 及 OpenAI-compatible 推理接口说明 `[外部文档/待训练机核实]`。
- InternVL3 Hugging Face `transformers` 与 vLLM 动态分辨率（`448×448` tile、`max_num`、`--media-io-kwargs`、`--limit-mm-per-prompt`）推理接口说明 `[外部文档/待训练机核实]`。
- MiniCPM-V-4.5 vLLM 服务化（`--trust-remote-code`、`minicpmv.py`、3D-Resampler 与 OpenAI-compatible 多图输入）说明 `[外部文档/待训练机核实]`；其原生 `transformers` 处理器行为已由 [minicpm-video-loading.md](minicpm-video-loading.md) §4–§5 固定 revision 核验。

**失效条件：**当 `script/five_label_eval/infer.py` 或 `frames.py` 的 CLI 参数、`five-label-input-record/3` schema、映射节点定义或默认抽帧规则发生变更；当用户正式拍板对比模型名单、抽帧口径（DEC-005 前置条件 1）、`max_pixels` 归属或 `temporal_ids` 策略；当训练机完成 §5.2 Pre-flight 实测并更新 `config/eval_paths.json` 的 `gpu-train` 配置；或当第 2 批子视频清单（1,633 条）被新批次取代时，本文受影响的缺口分析、统计数字、对照项与估算须重新核对。本文仅作调研与设计输入，不构成选型最终确认、实施授权或真实模型效果证据。
