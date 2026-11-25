# DEC-006：评测 8 帧抽帧口径、输入参数与首轮基座模型名单

- **决策状态：已确认。** 用户已于 2026-11-25 确认以下 6 项决定。
- **记录日期：2026-11-25。**
- **适用范围：** 五类标签离线基座模型首轮摸底测评的 L3 模型输入抽帧口径、短片边界、L3 PNG 缩放归属、MiniCPM-V-4.5 首轮时序与切片参数、首轮 8B–9B 基座模型名单，以及 `GLM-4.1V` `<answer>...</answer>` 格式冲突处置。
- **实施状态：** 决策已定案；`script/five_label_eval/frames.py` 与 `infer.py` 的代码适配、训练机前置只读体检及真实评测尚未完成。登记本决定不构成启动真实模型评测、下载权重或训练的授权。
- **验证状态：** 本记录不提供真实模型评测结果或训练机实测显存结论。

## 背景

[DEC-005 帧对应抽帧取证](0005-frame-correspondence-evidence.md)（独立取证 CLI 已于 2026-11-24 随 PR #21 落地于 `script/frame_correspondence/`）要求「模型输入抽帧口径须先落纸」作为前置条件 1；同时，PR #20 产出的三篇调研文档（[8 帧抽帧口径方案](../research/model-input-frame-sampling-options.md)、[8B/9B 模型选型对比](../research/vlm-8b-9b-model-comparison.md)、[训练机前置体检与适配器规划](../research/eval-preflight-and-adapter-plan.md)）梳理出 6 项须在代码适配与首轮基座摸底前拍板的边界问题。

## 决定

1. **8 帧抽帧公式（DEC-005 前置条件 1）：采用方案 A（`evenly_spaced_inclusive`，固定 8 帧）**
   - 对任意 `total_frames >= 8` 的 L2 子视频，按 0 基可解码帧序全片均匀含首尾抽取固定 8 帧：`idx[i] = round(i * (total_frames - 1) / 7)`（`i = 0..7`），必含首帧 `0` 与末帧 `total_frames - 1`。
   - `script/five_label_eval/frames.py` 的默认抽帧数由 `3` 对齐为 `8`（承接 `DF-044` 单请求 8 帧约束）。
   - 主评测严禁将 `.mp4` 交给推理服务二次抽帧，统一消费 `frames.py` 预抽落盘的 8 张 L3 PNG 与 `five-label-input-record/3` 输入记录。

2. **极短片段（`total_frames < 8`）策略：采用 `fail_closed`**
   - 当片段可解码总帧数少于 8 帧时，显式报错并拒绝进入 8 帧主评测批次；严禁静默减帧、丢帧或通过重复末帧补齐至 8 帧。

3. **L3 PNG 缩放归属：保持 L2 原始分辨率（`resize: null`）**
   - `frames.py` 落盘 L3 PNG 时不加缩放滤镜（`resize: null`），保留 L2 子视频原始像素，使同一份 L3 PNG 同时满足 `DEC-005` 清晰人工核查与多模型复用。
   - 各模型在各自 processor / `mm_processor_kwargs` 中按约定 `max_pixels` 进行视觉预处理，并将实际 `max_pixels` 写入运行身份。

4. **MiniCPM-V-4.5 首轮时序与切片参数：采用官方风格，并登记为后续对照/优化项**
   - 首轮基座摸底采用官方模型卡风格：**`0.1 s` 量化 `temporal_ids` + `max_slice_nums=1`**，并在运行身份中显式记录。
   - 该参数选择显式登记为**后续持续跟踪的对照/优化项**（同步记入 [TODO](../TODO.md) 与 [基座模型测评方案](../eval/base-model-eval-plan.md)）：首轮基线完成后，可另起独立 `run_id` 与旧链路配置（`temporal_ids=None`、`max_slice_nums=2`、`max_pixels=65,536` 规整）做同口径配对对照，两者不得混算。3b 顺序对照实验仍须关闭或重写时间编号以防顺序泄露。

5. **首轮 8B–9B 基座模型名单：锁定第一梯队（3+1 款）**
   - 首轮基座摸底固定纳入 4 款 8B 级非思考/标准模型：
     1. `openbmb/MiniCPM-V-4_5`（`MiniCPM-V-4.5`，本地 `transformers` backend）
     2. `Qwen/Qwen3-VL-8B-Instruct`（`Qwen3-VL-8B-Instruct`，OpenAI-compatible `http` backend）
     3. `OpenGVLab/InternVL3-8B`（`InternVL3-8B`，OpenAI-compatible `http` backend）
     4. `OpenGVLab/InternVL3_5-8B`（`InternVL3.5-8B` 标准版，**不含 ViR / InternVL3.5-Flash**，OpenAI-compatible `http` backend）
   - 第二梯队（`Keye-VL-1.5-8B`、`Ovis2.5-9B`）与第三梯队（`Qwen3-VL-8B-Thinking`、`GLM-4.1V-9B-Thinking`、`MiMo-VL-7B-RL`）延后至首轮基线结果出来后再决定是否追加。

6. **`GLM-4.1V` `<answer>...</answer>` 处置：主榜采用方案 1（原生格式罚分），不预埋解包分支**
   - 主评测榜单严格维护现有单 JSON 输出契约（`five-label-score/3` / `five_label_v2.txt`）：对保留 `<answer>...</answer>` 包裹标签的模型输出，原样写入 `raw_output` 并承受 `score.extract` 的 `surrounding_text_or_fence` 与 `strict_format_valid=False` 罚分。
   - **不在推理适配器中预埋 `<answer>` 解包分支**；若未来确需测试 `GLM-4.1V` 的解包对照效果，须经确认后另起独立 `run_id` 并在报告中显式披露，不得与主榜原生格式结果混算。

## 影响与不改的部分

- **补齐前置条件**：本决定正式关闭 [DEC-005](0005-frame-correspondence-evidence.md) 前置条件 1（「模型输入抽帧口径须先落纸」）；与已落地的 `five-label-input-record/3`（`DF-052`）及独立取证 CLI（PR #21）共同构成按次取证的上游契约基础。
- **不改的部分**：不修改 `docs/label.md`、不修改 `five-label-score/3` 评分口径与 `five_label_v2.txt` 原文、不改变固定 test（314 条）的隔离红线、不改变 `DEC-005`「只作人工可查证据、不替代 `full` 收据」的证明强度界限，也不因登记本决定而自动授权训练机实跑。

## 取代关系

本决定不取代 [DEC-003](0003-five-label-eval-scope.md) 或 [DEC-005](0005-frame-correspondence-evidence.md)，而是在 `DEC-003` 第 9 条（`DF-044` 单请求 8 帧与基座 `MiniCPM-V-4.5`）基础上锁定首轮多模型对照名单、L3 抽帧公式、短片边界、缩放归属及 MiniCPM/GLM 适配口径。

**失效条件：** 单请求 8 帧上限（`DF-044`）、五类严格单 JSON 输出契约（`five-label-score/3`）、第一梯队模型可用性或硬件显存预算（单卡 24 GB）发生变更，或用户基于首轮基线结果正式调整抽帧公式、模型名单或 `<answer>` 处置口径时，本记录须重新核对并登记新决策。
