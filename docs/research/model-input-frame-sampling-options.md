# 模型输入 8 帧抽帧口径选型方案（DEC-005 前置条件 1）

**定位：**本文是 [DEC-005 帧对应抽帧取证](../decisions/0005-frame-correspondence-evidence.md) 前置条件 1（「模型输入抽帧口径须先落纸」，见 [frame-correspondence-evidence.md](../frame-correspondence-evidence.md)）的专项决策输入文档，基于第 2 批子视频**开发集（1,319 条候选 / 955 个锚点）**实测数据对比 4 种抽帧口径，明确 `clip_to_model_input` 参数表示草案与待用户拍板的 4 个边界问题。8B/9B 模型选型横评另见 [vlm-8b-9b-model-comparison.md](vlm-8b-9b-model-comparison.md)，训练机前置只读体检与推理适配器规划另见 [eval-preflight-and-adapter-plan.md](eval-preflight-and-adapter-plan.md)。

**调研日期：** 2026-11-24。

**基准与边界声明：**

- **仓内核对基线**：`feat/tensileagent-finetune` 提交 `07d9c8e6030f62ac604a186b777ab1b7dc280e42`；当前生效第 2 批子视频清单 [data/sub_video/manifest.json](../../data/sub_video/manifest.json)（SHA-256 `c70686630c8fa0277305cc25a09821bc04ab853f6ce8a6ac3ca795998c08ac0f`，共 1,633 条候选 = 开发集 1,319 条 + 固定 test 314 条）。
- **固定 test 隔离红线**：固定 test（314 条候选、200 个锚点）**严禁参与任何抽帧口径选型或参数调优**；下文所有方案对比与决策依据均严格限定在开发集（1,319 条候选、955 个锚点）内计算。
- **只给方案、不代拍板**：本文不修改 `script/five_label_eval/frames.py` 或输入记录 schema，须经用户确认 §5 待决项后再落地。

---

## 1. 为什么必须先固定「L3 预抽 8 帧列表」口径

[帧对应抽帧取证](../frame-correspondence-evidence.md) 列出两项实现前置条件：
1. **模型输入抽帧口径须先落纸**（本文承接的待决项）；
2. 映射字段命名已定案并落地（任务 7 `MAPPING-NODE-RENAME` 已于 2026-11-24 完成，`five-label-input-record/3` 启用 `clip_to_model_input`／`clip_to_roi`／`roi_to_original` 并显式拒绝旧 v2，见 `DF-052`）。

根据 `five-label-input-record/3`（[input-record.md](../eval/input-record.md) §1、§10）与 `DF-044`（受 4090 显存限制统一单请求 8 帧），整条四层血缘链（`L0 原始源视频 ← L1 ROI 视频 ← L2 子视频 → L3 模型输入帧`）成立的前提是：**L3 模型输入帧与 L2 子视频之间由确定性的 `clip_to_model_input`（0 基可解码帧号 `clip_frame_index`）绑定**。

- **禁止在主评测中把 `.mp4` 交给推理服务二次抽帧**：不同模型与推理引擎（vLLM、Decord、PyAV、OpenCV、`qwen-vl-utils`）对容器头时长、可变帧率及异常帧计数的处理并不一致（参见 [minicpm-video-loading.md](minicpm-video-loading.md) §2 与 `video_0093` 文件头 771 帧 vs 实解码 733 帧案例，`DF-028`）。一旦由服务端内部再采样，就无法确定模型实际看到的是哪 8 帧，会直接破坏 `DEC-005` 的按次抽帧取证锚点。
- **主评测首选输入协议**：先由本仓确定性抽帧脚本（[frames.py](../../script/five_label_eval/frames.py)）按统一落纸口径产出 `records.jsonl`（`five-label-input-record/3`）与每候选 8 张 L3 PNG，再把同一组有序 8 帧送入各候选模型。若未来确需对照某模型「原生 `video_url` 端到端加载」，须登记独立 `input_id` 与独立 `run_id`，并在报告中明示不具备 `DEC-005` 逐帧锚点绑定（[design-test.md](../design-test.md) §2.1、§4.1）。

---

## 2. 第 2 批子视频真实分布基线（仓内实测）

直接统计 [data/sub_video/manifest.json](../../data/sub_video/manifest.json)（2026-11-24 实测，全批次 1,633 条仅作整体概览，选型统计严格只取开发集 1,319 条）：

| 角色（`role`） | 全批次候选数 | 全批次含锚点数 | 帧数范围（最小 / 中位 / 最大） | 时长范围（`output.media.duration`，最小 / 中位 / 最大） | 帧率范围 |
| --- | ---: | ---: | --- | --- | --- |
| `pre` | 825 | 0 | 50 / 150 / 600 | 2.00 s / 5.00 s / 20.07 s | 25–30 fps |
| `fracture` | 576 | 576 | 45 / 125 / 600 | 1.50 s / 5.00 s / 20.00 s | 25–30 fps |
| `post` | 127 | 0 | 46 / 68 / 460 | 1.53 s / 2.40 s / 15.33 s | 25–30 fps |
| `coverage` | 93 | 0 | 177 / 600 / 600 | 5.90 s / 20.00 s / 20.00 s | 25–30 fps |
| `no_fracture` | 9 | 0 | 60 / 150 / 600 | 2.00 s / 5.00 s / 20.00 s | 25–30 fps |
| `unclamped` | 3 | 3 | 60 / 90 / 150 | 2.00 s / 3.00 s / 5.00 s | 25–30 fps |
| **合计（批次概览）** | **1,633** | **579** | **45 / 150 / 600（`< 8` 帧为 0 条）** | **1.50 s / 5.00 s / 20.07 s** | **25–30 fps** |

关键实测约束（严格区分「批次概览」与「选型依据」，**固定 test 314 条候选及 200 个 test 锚点不参与抽帧方案选型**）：
- 1,633 条候选中没有任何片段少于 8 帧（最短 45 帧 / 1.50 s）；上表时长按清单 `output.media.duration` 实测统计（`video_0099_pre_05` 的 `output.media.duration = 20.067 s`，约 `20.07 s`，而按 `total_frames / fps = 600 / 30` 为 `20.00 s`）。
- 579 条带锚点候选合计 1,155 个锚点 = **开发集 479 条（955 个锚点）** + 固定 test 100 条（200 个锚点）。下文 §3 的方案对比**仅采用开发集 1,319 条候选与 955 个开发集锚点**：开发集 955 个锚点的相对位置 `output_frame / (total_frames - 1)` 分布在 `[0.184, 1.000]`（P10 = `0.203`，P50 = `0.503`，P90 = `0.802`，恰落在首尾端点 1 个）。
- 若沿用旧项目 `2 fps` 上限 8 帧公式 `max(1, min(int(duration * 2.0), 8, total_frames))`，在**开发集 1,319 条**中会有 **608 / 1,319 条（46.1%）** 短于 4.0 s 的片段抽出少于 8 帧（全批次概览为 746 / 1,633 条，45.7%；1.5 s 片段仅抽 3 帧）。

---

## 3. 四种候选 8 帧抽帧口径对比（选型数据仅取开发集 1,319 条 / 955 锚点）

| 方案 | 抽帧公式（0 基可解码帧 `total = L2.total_frames`） | 开发集（1,319 条 / 955 锚点）实测特性 | 优点 | 缺点与风险 | 推荐结论 |
| --- | --- | --- | --- | --- | --- |
| **方案 A：全片均匀含首尾固定 8 帧（`evenly_spaced_inclusive`）** | `count = 8`（`total >= 8` 时）；`idx[i] = round(i * (total - 1) / 7)`，`i = 0..7`（与 `frames.py:687` 现有公式完全一致） | 开发集 1,319/1,319 稳定产出 8 帧；**每条片段最大相邻帧间隔** `0.233–2.880 s`（中位 `0.720 s`、P90 `2.867 s`），**全部 9,233 个相邻帧间隔** `0.200–2.880 s`（中位 `0.700 s`、P90 `2.840 s`）；距开发集 955 个锚点最近帧距中位 `0.200 s`、P90 `0.667 s`、最大 `1.233 s`（注：全批次 1,633 条概览下，每片最大间隔为 `0.233–2.880 s` 中位 `0.733 s` / P90 `2.867 s`，全部 11,431 个相邻间隔为 `0.200–2.880 s` 中位 `0.700 s` / P90 `2.840 s`） | 1. **必含首帧 `0` 与末帧 `total-1`**，最利于完整呈现「初始状态→最终状态」变化（直接支撑 `未断裂 / 发生断裂 / 已断裂` 判别）；<br>2. **完全无真值泄露**，不依赖任何标注或角色；<br>3. **与 `frames.py` 现有公式一致**，纯整数 0 基解码索引；待后续训练入口接入同一抽帧规则后再实现训练/推理抽帧统一；<br>4. 满足 `DF-044` 固定 8 帧约束 | 20 s 长片（如 `coverage`）帧间隔约 2.86 s，极短暂瞬时断裂或微小开裂可能落在两帧之间（需靠「完整片段 vs 实际输入」双轨评价暴露，而非偷改抽帧） | **推荐默认主口径** |
| **方案 B：全片均匀分桶中点固定 8 帧（`uniform_bucket_midpoint`）** | `idx[i] = min(total - 1, floor((i + 0.5) * total / 8))`，`i = 0..7`（类似 MiniCPM 官方卡分桶中点） | 开发集 1,319/1,319 稳定产出 8 帧；距开发集 955 个锚点最近帧距中位 `0.133 s`、P90 `0.300 s`、最大 `0.700 s`（略近于方案 A，因开发集多数锚点位于片内 20%–80%） | 中段桶中心采样更贴近片内中部事件，减少片头/片尾静止帧占比 | **丢失首帧 `0` 与末帧 `total-1`**（20 s 片段首帧落在 ~1.25 s、末帧落在 ~18.75 s，首尾共丢 ~2.5 s），对结尾才出现断裂或脱夹的片段不利；且需修改 `frames.py:687` 现有已测公式 | 可作次选备选（仅当用户明确偏好中段密集、接受丢首尾时考虑） |
| **方案 C：旧 `2 fps` 上限 8 帧（`fps_capped_2fps_max8`）** | `n = max(1, min(int(duration * 2.0), 8, total))`，再 `linspace(0, total-1, n)` | 开发集 **608 / 1,319 条（46.1%）** 抽出 `< 8` 帧（1.5 s 断裂片仅 3 帧） | 仅与旧 v4.1 代码静态一致 | 直接违背 `DF-044` 统一 8 帧契约与历史 `max_frames=8` 硬要求；短断裂/断后片段本就信息紧张却被反向降帧 | **明确不推荐** |
| **方案 D：按时长自适应（>8 帧）或锚点加密** | 长片 >8 帧；或在断裂锚点前后加密取帧 | — | 理论上可提升长片或锚点附近覆盖 | ① `>8` 帧违背 `DF-044`（4090 显存限制下训练与推理统一 8 帧）；② 锚点加密在真实推理/测试期不可用且构成**严重标签泄露**（违反 [design-test.md](../design-test.md) §6 与 [prompt.md](../eval/prompt.md)） | **禁止作为主评测口径**（锚点分析仅可用于离线诊断，绝不可进主评测输入） |

---

## 4. `clip_to_model_input` 与 `input_id` 参数表示草案

当前 [frames.py](../../script/five_label_eval/frames.py)（56–57、714–725 行）已将 `selection_rule: "evenly_spaced_inclusive"` 与 `clips_per_record` 纳入 `input_id` 哈希，但 `frames[].frame_index_mapping.clip_to_model_input` 仍是无参数的静态常量：

```json
{
  "kind": "ffmpeg_select_nth_decoded_frame",
  "offset": null,
  "reason": "L3 帧由 ffmpeg select=eq(n\\,clip_frame_index) 从 L2 按解码序抽取"
}
```

待用户拍板抽帧口径后，建议在**不破坏 `clip_to_model_input` 节点名与 `L2 → L3` 方向（`DF-052`）**的前提下，在记录顶层或 `clip_to_model_input` 中显式固化以下参数（任一项改变即改变 `input_id`；若改动 `record_schema` 结构须同步升版本号与守卫测试）：

| 参数字段（建议） | 推荐默认取值 | 说明 |
| --- | --- | --- |
| `sampling_rule` | `"evenly_spaced_inclusive"` | 抽帧公式标识；与 `frames.py:715` 现值一致 |
| `target_frame_count` | `8` | 固定目标帧数（对齐 `DF-044`；替换 `frames.py:887` 当前默认 `3`） |
| `short_clip_policy` | `"fail_closed"`（待拍板） | `total_frames < 8` 时的确定性策略（见 §5 问题 2） |
| `resize` | `null`（不缩放）或 `{"method": "area_cap", "max_pixels": 65536, "min_pixels": 256, "upscale": false}` | 对齐 [eval-subset.md](../eval/eval-subset.md) §4：记录抽帧落盘阶段是否做缩放；`null` 表示 L3 PNG 保持 L2 原始像素，由各模型 processor 自行处理 |
| `temporal_ids_policy` | `"none"` / `"quantized_0.1s"` / `"not_applicable"` | 记录时间位置编码注入策略，供 MiniCPM 3D-Resampler 与 3b 顺序对照追溯 |
| `frames[].width` / `height` / `sha256` | 实测整数与 64 位小写 hex | 补齐 [input-record.md](../eval/input-record.md) §0 状态表 1/7 的「实现较窄」缺口，使 `infer.py` 与 `DEC-005` 工具可直接核验 L3 PNG 完整性 |

---

## 5. 需要用户拍板的 4 个边界问题

1. **抽帧公式定案（DEC-005 前置条件 1）**：是否确认采用**方案 A（`evenly_spaced_inclusive`，固定 8 帧）**作为本轮正式默认口径，并将 `frames.py` 默认帧数由 `3` 对齐为 `8`？
2. **极短片段（`total_frames < 8`）处置策略**：虽然第 2 批 1,633 条最短为 45 帧（0 条 `<8`），但未来虚拟试制或异常短片可能触及该边界。建议选其一：
   - **选项 1（推荐）**：`fail_closed` 直接报错拒绝进入 8 帧主评测批次（避免静默改变帧数语义）；
   - **选项 2**：保留全部 `total_frames` 帧（去重升序），并在记录中显式标记 `actual_frame_count < target_frame_count`；
   - **选项 3**：重复末帧补齐至 8 帧（会破坏 `clip_frame_index` 唯一性，不推荐）。
3. **`max_pixels` 缩放归属**：
   - **选项 1（推荐）**：L3 PNG 保持 L2 原始画幅不缩放（`resize: null`），各模型在各自 processor / `mm_processor_kwargs` 中按约定 `max_pixels` 处理并写入运行身份；一份 L3 PNG 同时满足 `DEC-005` 清晰人工查阅与多模型复用；
   - **选项 2**：在 `frames.py` 落盘 L3 PNG 前统一按 `max_pixels=65,536`（只缩不放）缩放，所有模型看到严格同像素 PNG；但会压低高分辨率模型的视觉上限并降低人工核查图清晰度。
4. **MiniCPM-V-4.5 时序与切片参数**：首轮基座摸底（run A）是沿用旧链路（`temporal_ids=None`、`max_slice_nums=2`、`max_pixels=65,536` 规整），还是采用官方模型卡风格（0.1 s 量化 `temporal_ids` + `max_slice_nums=1`）？两者属不同运行身份，不可混算。

---

## 6. 来源与失效条件

- **仓内依据**：[docs/frame-correspondence-evidence.md](../frame-correspondence-evidence.md)、[DEC-005](../decisions/0005-frame-correspondence-evidence.md)、[DEC-003](../decisions/0003-five-label-eval-scope.md)、[docs/facts.yaml](../facts.yaml)（`DF-028`、`DF-044`、`DF-051`、`DF-052`）、[docs/eval/input-record.md](../eval/input-record.md)、[docs/eval/eval-subset.md](../eval/eval-subset.md)、[docs/eval/prompt.md](../eval/prompt.md)、[docs/design-test.md](../design-test.md)、[docs/research/minicpm-video-loading.md](minicpm-video-loading.md)、[script/five_label_eval/frames.py](../../script/five_label_eval/frames.py)、[data/sub_video/manifest.json](../../data/sub_video/manifest.json)。
- **同系列关联专题**：[vlm-8b-9b-model-comparison.md](vlm-8b-9b-model-comparison.md) · [eval-preflight-and-adapter-plan.md](eval-preflight-and-adapter-plan.md)。

**失效条件：**当用户正式拍板 §5 四个边界问题并落地到 `script/five_label_eval/frames.py` 与 `five-label-input-record/*` 新版本；当第 2 批子视频清单（1,633 条，开发集 1,319 条）被新批次取代；或当单请求 8 帧上限（`DF-044`）发生变更时，本文的分布统计、方案对比与草案参数须重新核对。本文仅作决策输入，不构成代码改动或正式评测授权。
