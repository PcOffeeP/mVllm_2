# DEC-008：首轮微调主基座选型、RTX 4090 QLoRA 配方、InternVL-HF 切换与三折隔离红线

- **决策状态：已确认。** 用户已于 2026-11-26 基于 `eval-dev-v1` 全量配对 Run A / Run B 评测结果与 4 款基座单卡 RTX 4090（24 GB）`LlamaFactory` QLoRA 冒烟实测，确认锁定首轮微调主基座与训练配方边界。
- **记录日期：2026-11-26。**
- **适用范围：** 五类标签离线微调（SFT）首轮主基座锁定、训练机 `vlm-sft` 环境与 `vlm-eval` 服务共存边界、RTX 4090（24 GB）8 帧全分辨率对齐 QLoRA 配方、InternVL 权重 `-hf`/`-HF` 切换与 `LlamaFactory` 切块限制记录，以及 SFT 三折隔离红线。
- **实施状态：** 训练机 `vlm-sft` 环境、`LlamaFactory` 子模块（`4447137e`）、InternVL-HF 权重替换、配对 Run A / Run B 评测与 4 款基座 10 样本 8 帧合成 QLoRA 冒烟均已实测验证完成；正式三折 SFT 训练尚未启动（待 B3 人工审核推进并经用户明确授权后按折启动）。
- **验证状态：** 本文引用的评测指标、显存峰值、吞吐与 vLLM `--enable-lora` 回环均来自 2026-11-26 训练机（`dell-Precision-3660`，1× RTX 4090 24,564 MiB）实测并经独立核验。

---

## 背景

[DEC-006](0006-eval-frame-sampling-and-model-lineup.md) 锁定了第一梯队 3+1 款 8B 级基座模型。2026-11-26 完成了三项决定微调路线的实证闭环：

1. **配对 Run B（`--no-image` 纯文本先验盲测，PR #29）**：在冻结开发集 [`eval-dev-v1`](../../data/eval-subsets/eval-dev-v1.json)（210 条 / 87 源，严格按 [DEC-007](0007-dev-test-dedup-exclusion.md) 排除近重复源）上，为 `Qwen3-VL-8B-Instruct`、`InternVL3-8B-hf` 与 `InternVL3_5-8B-HF` 完成了与 Run A 同服务、同解码参数、同 Prompt 的严格配对无图盲测，区分真实视觉增益与纯文本先验幻觉。
2. **InternVL 非 HF 权重替换为 HF 兼容版**：原非 HF 权重 `InternVL3-8B` / `InternVL3_5-8B`（`InternVLChatModel`）被 `LlamaFactory/src/llamafactory/model/patcher.py:402-407` 显式拒载；按用户授权已替换为 ModelScope 官方 HF 版 `InternVL3-8B-hf` 与 `InternVL3_5-8B-HF`（`InternVLForConditionalGeneration`），并重跑配对 Run A / Run B。
3. **单卡 RTX 4090（24 GB）`vlm-sft` 环境搭建与 4 模型 8 帧 QLoRA 冒烟**：实测对比了 4 款第一梯队基座在 8 帧高分辨率真实输入（含 `804×1072 = 861,888 px` 与 `726×968 = 702,768 px` 峰值样本）下的显存、训练/推理像素对齐度与 `vLLM --enable-lora` 加载回环。

---

## 决定

### 1. 锁定首轮 SFT 主基座：`Qwen3-VL-8B-Instruct`

- 正式锁定 **`Qwen3-VL-8B-Instruct`**（`/data/models/Qwen3-VL-8B-Instruct`，`Qwen3VLForConditionalGeneration`，`model.safetensors.index.json` SHA-256 `520b2e05…bff070`）作为首轮五类标签 SFT 唯一主基座。
- **实测依据（严守 [`docs/eval/eval-subset.md`](../eval/eval-subset.md) §3 三画幅档分列口径，不跨档合算总分）**：
  - **格式与工程零违约**：Run A 与 Run B 均达到严格单 JSON 合法率 **210/210（100.0%）**，无需 `--trust-remote-code` 或 `--hf-overrides`，vLLM 0.34.0 原生 8,192 上下文承载 8 帧全分辨率输入。
  - **Run B 诚实度与视觉净增益最优**：在无图 Run B 中，对全部 210 条样本的全部 11 个叶字段均 **100% 诚实输出 `无法判断`**（零先验幻觉）；相对 Run B，8 帧视觉 Run A 在三画幅档全面拉升：`断裂状态` 分别提升 **`+38.39 pp`（`w_le_200`） / `+50.00 pp`（`w_200_400`） / `+50.00 pp`（`w_gt_400`）**，高画幅档 `w_gt_400` 的 `断裂现象.伸长` 提升 **`+50.00 pp`**（`7.14% → 57.14%`），`五类全对` 在三档分别提升 `+0.89 / +9.52 / +17.86 pp`（至 `0.89% / 9.52% / 17.86%`）。
  - **唯一在 RTX 4090 上实现 8 帧全分辨率训练/推理 100% 对齐且完整跑通 `vLLM --enable-lora` 回环的基座**（详见 §2、§3）。
- **其余 3 款第一梯队基座处置**：
  - **`InternVL3-8B-hf`**：暂不作为首轮 SFT 主基座。Run A/B 均 `0/210` 严格合法（全量包裹 ```` ```json ```` 围栏）；更关键的是在无图 Run B 中**对 210/210 样本恒定幻觉输出 `断裂状态=发生断裂` 且全部字段 `unc=0.00%`**（先验猜测在三画幅档的 `断裂模式` 与 `断裂位置` 上反而高于 Run A）；且受限于 `LlamaFactory` `InternVLPlugin` 硬编码 `max_patches: 12`（见 §4），不改框架源码无法在 8 帧 SFT 中对齐 vLLM `max_patches: 4`。
  - **`InternVL3_5-8B-HF`**：暂不作为首轮 SFT 主基座。虽格式修复（Run A `209/210`、Run B `210/210`）且 Run B 100% 诚实输出 `无法判断`，但 Run A 极端保守退化（196 条 `未断裂` + 14 条 `无法判断`，三档 `发生断裂`/`已断裂` 召回全为 `0`，三档 `五类全对` 全为 `0.00%`），且受同一 `InternVLPlugin` 切块限制。
  - **`MiniCPM-V-4.5`**：保留作备选对照路线（已在 `vlm-sft` 验证 4-bit QLoRA 冒烟 `15,515 MiB` 通过），当前不并行投入首轮主训；若后续入主榜须先补齐视觉 Run 的 processor 实际逐帧像素上限运行身份。

### 2. 锁定训练机 `vlm-sft` 独立 Conda 环境与 PATH 隔离红线

- **环境方案（Option B，零侵入既有环境）**：在训练机（`dell-Precision-3660`）以 `conda create -n vlm-sft --clone agent -y` 克隆建立专用训练环境 `vlm-sft`，升级 `transformers==4.57.6`，并以 editable 模式安装已初始化的仓库子模块 `/home/liuyang/文档/TensileAgent-Finetune/LlamaFactory`（commit `4447137e08c172d7701594b4d1695a6d4a869cbd`，`pip install --no-deps -e`）。
- **已验证软件栈**：`Python 3.11.15`、`torch 2.5.1+cu124`、`transformers 4.57.6`（满足 `LlamaFactory/pyproject.toml` `>=4.55.0,<=5.6.0,!=4.57.0` 且支持 `Qwen3VLForConditionalGeneration`、`InternVLForConditionalGeneration` 以及直接路径加载 `MiniCPM-V-4.5` 无点号路径报错）、`peft 0.18.1`、`accelerate 1.11.0`、`trl 0.24.0`、`bitsandbytes 0.49.2`、`av 16.0.0`、`llamafactory 0.9.6.dev0`；`pip check` 与 `check_dependencies()` 全通过。
- **既有环境零改动**：`vlm-eval`（`Python 3.12.16` / `torch 2.14.0+cu130` / `transformers 5.22.2` / `vllm 0.34.0`）、`mvllm2`（`transformers 4.56.1`）与 `agent`（`transformers 4.56.1`）均保持 100% 原状不动。
- **强制运维红线（`PATH` 隔离）**：运行 `vlm-eval` 的 `vLLM` 服务时，**严禁将 `vlm-sft/bin` 混入 `PATH`**。实测 `vlm-sft/bin/ninja` 会联合系统 `/usr/bin/nvcc` 触发 FlashInfer 采样 JIT 编译并因 `nvcc fatal: Unknown option '--compress-mode=size'` 崩溃；保持干净系统 `PATH`（不含 `ninja`）可稳定跳过 FlashInfer JIT 正常服务。

### 3. 锁定 RTX 4090（24 GB）`Qwen3-VL-8B-Instruct` 黄金 8 帧全分辨率对齐配方

10 样本合成 8 帧 QLoRA/LoRA 冒烟（`disable_shuffling: true` 首两步直接压测 `eval-dev-v1` 最大分辨率 `804×1072 = 861,888 px` 与 `726×968 = 702,768 px` 样本，`lora_rank=16`、`lora_target=all`、`gradient_checkpointing=true`、`per_device_train_batch_size=1`、`max_steps=2`）实测结果如下：

| 配置 | 精度 / 优化器 | `image_max_pixels` / `min_pixels` | 结果与显存峰值（4090 24,564 MiB） | 结论 |
| --- | --- | --- | --- | --- |
| `bf16` LoRA | `bf16` / AdamW | `1,200,000` / `65,536` | **OOM**（`23,457 MiB`，`ForCausalLMLoss` `logits.float()` 分配 4.25 GiB 失败） | 淘汰 |
| `bf16` LoRA（降像素） | `bf16` / AdamW | `262,144` / `65,536` | **OOM**（`24,049 MiB`，分配 1.54 GiB 失败） | 淘汰（24 GB 卡须用 4-bit QLoRA） |
| 4-bit QLoRA（默认优化器） | `4-bit bnb` / AdamW | `1,200,000` / `65,536` | PASS（`12.67s`，`~6.33s/step`，`24,047 MiB`） | 显存过紧，不推荐 |
| **黄金配方（锁定）** | **`4-bit bnb` + `paged_adamw_8bit` + `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`** | **`1,200,000` / `65,536`** | **PASS（`12.74s`，`~6.37s/step`，峰值 `22,525 MiB`，较默认优化器省 `1,522 MiB`，留出 `> 2.0 GiB` 余量）** | **锁定为首轮正式 SFT 基准配方** |

- **核心锁定参数**：
  - `template: qwen3_vl_nothink`
  - `quantization_bit: 4`、`quantization_method: bnb`（4-bit QLoRA）
  - `image_max_pixels: 1200000`、`image_min_pixels: 65536`（完整覆盖 L2 最大单帧 `924×1232 = 1,138,368 px` 不降采样，与 `vLLM` 评测默认 `Qwen2VLImageProcessorFast` `min_pixels=65,536` / `max_pixels=16,777,216` 在全部样本上实现 **100% 分辨率对齐**）
  - `lora_rank: 16`、`lora_target: all`、`gradient_checkpointing: true`、`optim: paged_adamw_8bit`
  - 环境变量：`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
- **推理回环验真**：上述黄金配方导出的 `adapter_model.safetensors`（167 MB）已实测通过 `vlm-eval` 环境中 `vLLM 0.34.0 --enable-lora` 加载（31s 启动），单条真实 8 帧 `804×1072` 样本（`prompt_tokens=7,430`、`completion_tokens=93`）`3.81s` 返回 HTTP 200 及合法五类 JSON。

### 4. InternVL-HF 权重切换与 `LlamaFactory` `InternVLPlugin` 限制留档

- **权重切换结果**：训练机 `/data/models/` 已删除原非 HF `InternVL3-8B` 与 `InternVL3_5-8B`，并验证落盘 ModelScope HF 版：
  - `/data/models/InternVL3-8B-hf`（`15G`，`InternVLForConditionalGeneration`，4/4 分片、781/781 张量、`model.safetensors.index.json` SHA-256 `5551d292…b0dfd4`）；
  - `/data/models/InternVL3_5-8B-HF`（`16G`，`InternVLForConditionalGeneration`，4/4 分片、841/841 张量、`model.safetensors.index.json` SHA-256 `b15fa5f3…f77d1b`）。
  - 两款 HF 权重在 `vLLM 0.34.0` 上均**无需 `--trust-remote-code` 或 `--hf-overrides`**，在 `--max-model-len 12288` 下须传 `--mm-processor-kwargs '{"max_patches": 4}'`（默认 `max_patches=12` 在最大 8 帧样本上达 `27,262` tokens 触发 HTTP 400）。
- **`InternVLPlugin` 硬编码 `max_patches: 12` 实测发现**：
  - `vlm-sft` 4-bit QLoRA 冒烟（`template: intern_vl`、`paged_adamw_8bit`、`cutoff_len: 12288`）在默认 **`crop_to_patches: false`**（每帧 1 patch）下均通过：`InternVL3-8B-hf` 峰值 `13,763 MiB`（`~2.02s/step`，`155M` adapter），`InternVL3_5-8B-HF` 峰值 `14,697 MiB`（`~2.29s/step`，`167M` adapter）。
  - 开启 **`crop_to_patches: true`** 时两款模型均报错失败：`ValueError: Image features and image tokens do not match: tokens: 12162, features 26624`。根因是 `LlamaFactory/src/llamafactory/data/mm_plugin.py:847` 硬编码 `max_patches: 12`，8 张大帧展开为 104 块（`26,624` 视觉特征 token），被 `cutoff_len: 12288` 截断为 `12,162` 个 `<IMG_CONTEXT>` token。
  - **结论**：在不修改 `LlamaFactory` 源码暴露可配 `max_patches` 前，InternVL-HF 8 帧 SFT 只能以 `crop_to_patches: false` 运行（与 `vLLM max_patches: 4` 存在训练/推理视觉分辨率错配）；这是首轮优先锁定 `Qwen3-VL-8B-Instruct` 的重要工程依据之一。

### 5. SFT 三折严格隔离红线（防数据泄漏）

- **严禁在整份 `eval-dev-v1`（210 条，横跨三折验证集）上训练**：任何折的训练数据构造器严禁摄入跨折验证源，也严禁摄入 [DEC-007](0007-dev-test-dedup-exclusion.md) [`data/splits/dev-exclusions.json`](../../data/splits/dev-exclusions.json) 中排除的开发源（`video_0006`、`video_0079` 及其 20 条子视频）与 15 条隔离虚拟视频。
- **按折严格隔离训练与验证**：对每一折 $k \in \{0, 1, 2\}$：
  - **训练集**：仅限该折 `data/splits/three-fold/fold_{k}_train.json` 扣除 `DEC-007` 排除源后的 **58 个干净开发源**中已完成人工确认的片段；
  - **验证集**：严格限定为 **`eval-dev-v1 ∩ fold_{k}_val`**（扣除 `DEC-007` 后每折均 29 个干净验证源：其中 **Fold 0 验证集为 69 条 / 29 源**，Fold 1 为 73 条 / 29 源，Fold 2 为 68 条 / 29 源），并按三画幅档（`w_le_200` / `w_200_400` / `w_gt_400`）分档报告，不跨档合并主指标。
- **封存终测集零触碰红线**：[`data/eval-subsets/eval-test-v1.json`](../../data/eval-subsets/eval-test-v1.json)（314 条 / 21 源）全程封存，严禁用于训练、超参调优、早停选点、Prompt 迭代或适配器挑选。

---

## 影响与不改的部分

- **不改的部分**：不改写 `docs/label.md`、不改写 `data/splits/three-fold/*.json`、不改写 `data/splits/dev-exclusions.json`、不改写冻结评测子集 `data/eval-subsets/eval-{dev,test}-v1.json`、不改写 `five-label-score/3` 评分口径与 `five_label_v2.txt` 原文，也不修改训练机既有 `vlm-eval` / `mvllm2` / `agent` Conda 环境。
- **不构成自动开训授权**：本决定锁定技术基座、配方与隔离边界；正式三折 SFT 训练须在 B3 人工审核与训练数据构造核验就绪后按阶段确认启动。

## 取代关系

本决定在 [DEC-006](0006-eval-frame-sampling-and-model-lineup.md)（第一梯队评测名单与 8 帧口径）与 [DEC-007](0007-dev-test-dedup-exclusion.md)（近重复排除口径）基础上，进一步锁定首轮微调主基座、训练环境与 QLoRA 配方，不取代或修改 DEC-006 / DEC-007 的既有条款。其中 DEC-006 第 5 条所列 `InternVL3-8B` / `InternVL3_5-8B` 在训练机磁盘上已替换为 HF 兼容权重 `InternVL3-8B-hf` / `InternVL3_5-8B-HF`，历史非 HF Run A 归档与新 HF 配对 Run A/B 归档在 [`docs/eval/runs/README.md`](../eval/runs/README.md) 中分列保留、互不混算。

**失效条件：** 若未来升级训练机显卡显存规格（突破 24 GB）、升级 `LlamaFactory` 或 `transformers`/`vLLM` 主版本、补丁改造 `InternVLPlugin` 可配 `max_patches`、引入新的首轮之外基座模型，或用户重新指定首轮微调主基座时，须重新核对显存/对齐冒烟并登记新决策。
