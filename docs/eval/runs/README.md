# 正式评测结果总入口（`docs/eval/runs/`）

> 本页汇总本轮五类标签离线评测（`five-label-score/3`）在冻结开发集 [`eval-dev-v1`](../../../data/eval-subsets/eval-dev-v1.json)（210 条 / 87 源，全部 `source_type = real`，严格按 [DEC-007](../../decisions/0007-dev-test-dedup-exclusion.md) 排除近重复源）上的正式评测结果与跨模型对照总表。

**失效条件：** 当评测子集由 `eval-dev-v1` 切换至新版本、评分器版本脱离 `five-label-score/3`、或本目录下既有 Run 产物被替换/撤回而未同步更新本页总表与链接时，本页汇总结论须重新核对。

---

## 1. 本目录与训练机 `evaluations/` 的分工

| 存储位置 | Git 状态 | 承担内容 | 说明 |
| --- | --- | --- | --- |
| **`docs/eval/runs/`**（本目录） | **受 Git 跟踪**（通过 PR 同步回本机） | 跨模型汇总总入口（本页）、三画幅档完整必报项分档报告（[`width-band-breakdown.md`](width-band-breakdown.md)）及每次正式 Run 原样归档的 `report.md`、`results.json`、运行元数据（`predictions.jsonl.meta.json` 或 `run_meta.json`）与 `snapshot_identity.json` | 不提交独立的原始 `predictions.jsonl`、推理/显存日志（`*.log`）或 PNG 抽帧；注：原样归档的 `results.json` 为 `score.py` 原始输出，内部仍保留逐样本 `raw_output` 与预测元数据以便审计复算 |
| 训练机 `/home/liuyang/文档/TensileAgent-Finetune/evaluations/` | **被 `.gitignore` 忽略**（受 `tests/test_layout_migration_guard.py` T6 守卫约束） | `eval-dev-v1/` 共享抽帧输入（1,680 张 PNG 与清单）、`runs/` 完整原始产物（含 `predictions.jsonl`、`*.log`、`score/` 与权重代码白名单）、`smoke/` 小样本冒烟留档 | 大体积媒体与原始推理日志留在训练机，避免污染 Git 仓库并守住顶层 `/evaluations` 忽略边界 |

---

## 2. 第一梯队模型评测状态总览（`eval-dev-v1`，210 条 / 87 源，共 11 组已归档 Run）

> **评分与口径**：`five-label-score/3`（`prompt@sha256:cf299d672281e12ea5f3964bb08ffbe2d237e1dfad3503861e7e21a5872cc4cf`，8 帧 `evenly_spaced_inclusive`、`fail_closed`、`resize: null`，按 [DEC-006](../../decisions/0006-eval-frame-sampling-and-model-lineup.md) 执行）。
> 按 [`docs/eval/eval-subset.md`](../eval-subset.md) §3 硬约束：**同一标签不得跨画幅档合并为单一数字**，因此本节仅列运行状态、格式合法率、请求状态与归档入口；所有标签准确率与 `无法判断` 比例统一在 §3 与 [`width-band-breakdown.md`](width-band-breakdown.md) 按三画幅档独立并列展示。本轮按 [DEC-003](../../decisions/0003-five-label-eval-scope.md) 只报数、不设通过阈值或自动晋级；用户已结合本页配对 Run A/B 与 4090 QLoRA 冒烟结果确认 [DEC-008](../../decisions/0008-finetune-base-model-and-sft-recipe.md) 锁定首轮 SFT 主基座。

| 模型（[DEC-006](../../decisions/0006-eval-frame-sampling-and-model-lineup.md) 第一梯队） | Run 定位与后端 | 状态 | 格式严格合法 | 请求失败 / 超时 / 未处理 | 直达目录 |
| --- | --- | --- | --- | --- | --- |
| **`MiniCPM-V-4.5`** | **Run A（`transformers` DEC-006 方向）**：`0.1 s` 量化 `temporal_ids`，`max_slice_nums=1` | 历史初步观测（2026-11-25；processor 实际逐帧像素上限未核实，补齐运行身份前不入正式跨模型主榜） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261125-minicpm-v45-tf-dev-v1/`](20261125-minicpm-v45-tf-dev-v1/) |
| **`MiniCPM-V-4.5`** | **Run A（`vLLM HTTP` 对照）**：同 8 帧输入服务化对照 | 历史初步观测（2026-11-25；服务端 processor 实际像素上限未记录，补齐前不入正式跨模型主榜） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261125-minicpm-v45-vllm-dev-v1/`](20261125-minicpm-v45-vllm-dev-v1/) |
| **`MiniCPM-V-4.5`** | **Run B 无画面盲答**：`vLLM 0.34.0` HTTP 描述性纯文本先验对照（剥离全部图像帧，解码参数未记入 `run_meta.json`） | 历史初步观测（2026-11-25；仅作描述性先验对照，非严格配对实验） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261125-minicpm-v45-runb-noimage-dev-v1/`](20261125-minicpm-v45-runb-noimage-dev-v1/) |
| **`Qwen3-VL-8B-Instruct`** | **Run A（`vLLM 0.34.0` HTTP）**：`bfloat16`、`--max-model-len 8192`、`mm_processor_kwargs=null`（快照默认 `Qwen2VLImageProcessorFast`：`min_pixels=65,536`、`max_pixels=16,777,216`、`patch_size=16`、`merge_size=2`） | 已完成并归档（2026-11-26；已配对 Run B；**[DEC-008](../../decisions/0008-finetune-base-model-and-sft-recipe.md) 锁定首轮 SFT 主基座**） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261126-qwen3-vl-8b-vllm-dev-v1/`](20261126-qwen3-vl-8b-vllm-dev-v1/) |
| **`Qwen3-VL-8B-Instruct`** | **Run B 严格配对无图盲测（`vLLM 0.34.0` HTTP `--no-image`）**：同服务、同解码参数、同 Prompt，零图像输入（`prompt_tokens=614`） | 已完成并归档（2026-11-26；全部 11 字段 100% 诚实输出 `无法判断`） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1/`](20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1/) |
| **`InternVL3-8B`**（早期原生非 `-hf`，`InternVLChatModel`） | **Run A（`vLLM 0.34.0` HTTP）**：`bfloat16`、`--trust-remote-code`、`--max-model-len 12288`、`--hf-overrides '{"max_dynamic_patch": 4}'`（单帧至多 `4+1=5` 块） | 历史非 HF 权重留档（2026-11-26 盘上权重已切换为 HF 版；全量带 ```` ```json ```` 围栏；无配对 Run B） | 0/210 (0.0%) | `0 / 0 / 0` | [`20261126-internvl3-8b-vllm-dev-v1/`](20261126-internvl3-8b-vllm-dev-v1/) |
| **`InternVL3-8B-hf`**（LlamaFactory 兼容 HF 版，`InternVLForConditionalGeneration`） | **Run A（`vLLM 0.34.0` HTTP）**：`bfloat16`、`trust_remote_code=false`、`--max-model-len 12288`、`--mm-processor-kwargs '{"max_patches": 4}'`（单帧至多 `4+1=5` 块，`prompt_tokens` 2,686~10,878） | 已完成并归档（2026-11-26；已配对 Run B；全量带 ```` ```json ```` 围栏但均成功解析） | 0/210 (0.0%) | `0 / 0 / 0` | [`20261126-internvl3-8b-hf-vllm-dev-v1/`](20261126-internvl3-8b-hf-vllm-dev-v1/) |
| **`InternVL3-8B-hf`**（HF 版） | **Run B 严格配对无图盲测（`vLLM 0.34.0` HTTP `--no-image`）**：同服务、同解码参数、同 Prompt，零图像输入（`prompt_tokens=614`） | 已完成并归档（2026-11-26；**先验幻觉红灯**：210/210 恒定输出 `发生断裂` 且全部字段 `unc=0%`） | 0/210 (0.0%) | `0 / 0 / 0` | [`20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1/`](20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1/) |
| **`InternVL3_5-8B`**（早期原生非 `-HF`，不含 ViR） | **Run A（`vLLM 0.34.0` HTTP）**：`bfloat16`、`--trust-remote-code`、`--max-model-len 12288`、`--hf-overrides '{"max_dynamic_patch": 4}'`（单帧至多 `4+1=5` 块） | 历史非 HF 权重留档（2026-11-26 盘上权重已切换为 HF 版；1 条带围栏；无配对 Run B） | 209/210 (99.5%) | `0 / 0 / 0` | [`20261126-internvl3_5-8b-vllm-dev-v1/`](20261126-internvl3_5-8b-vllm-dev-v1/) |
| **`InternVL3_5-8B-HF`**（LlamaFactory 兼容 HF 版，不含 ViR） | **Run A（`vLLM 0.34.0` HTTP）**：`bfloat16`、`trust_remote_code=false`、`--max-model-len 12288`、`--mm-processor-kwargs '{"max_patches": 4}'`（单帧至多 `4+1=5` 块，`prompt_tokens` 2,686~10,878） | 已完成并归档（2026-11-26；已配对 Run B；仅 `w_200_400` 1 条带围栏；三档 `五类全对` 均 0%） | 209/210 (99.5%) | `0 / 0 / 0` | [`20261126-internvl3_5-8b-hf-vllm-dev-v1/`](20261126-internvl3_5-8b-hf-vllm-dev-v1/) |
| **`InternVL3_5-8B-HF`**（HF 版） | **Run B 严格配对无图盲测（`vLLM 0.34.0` HTTP `--no-image`）**：同服务、同解码参数、同 Prompt，零图像输入（`prompt_tokens=614`） | 已完成并归档（2026-11-26；全部 11 字段 100% 诚实输出 `无法判断`） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1/`](20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1/) |

---

## 3. 三画幅档独立对比、配对 Run A/B 诊断与 4090 QLoRA 冒烟总结

### 3.1 三画幅档独立对比表（`eval-dev-v1` 宽度分档：`width_rule_le200_lt400`）

> 按 [`docs/eval/eval-subset.md`](../eval-subset.md) §1、§3、§4 契约要求，在各档样本上使用 `script.five_label_eval.score.aggregate` 独立统计（`eval-dev-v1` 全部为 `source_type = real`，虚拟数据 0 条；L3 落盘 `resize: null`）。下表完整列示全部 **11 组已归档 Run**（既有 6 组 + 2026-11-26 新增 5 组：Qwen3-VL 配对 Run B 与 InternVL3/3.5-HF 配对 Run A/B）的核心字段分档对照；**全部 11 个叶字段**的分档准确率、模型与人工 `无法判断` 比例及各 Run 实际生效的 vLLM/processor 参数详见 **[三画幅档完整必报项分档报告](width-band-breakdown.md)**。
> 注：早期非 HF 版 `InternVL3-8B` / `InternVL3_5-8B` 通过 `--trust-remote-code --hf-overrides '{"max_dynamic_patch": 4}'` 约束块数；新 HF 版 `InternVL3-8B-hf` / `InternVL3_5-8B-HF` 由 `vLLM 0.34.0` 原生加载（`trust_remote_code=false`），通过 `--mm-processor-kwargs '{"max_patches": 4}'` 实现等效单帧至多 `4+1=5` 块（`448×448`、`prompt_tokens` `2,686~10,878`）。

| 画幅档（来源数 / 片段数 / 断裂真值数） | 模型 / Run | 请求失败 / 超时 / 未处理 | 断裂状态准确率（模型 `unc`） | 断裂模式 (`frac`) | 断裂位置 (`frac`) | 断裂现象.伸长（模型 `unc`） | 五类全对（补充） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **`w_le_200`** (`w ≤ 200`，48 源 / `n=112` / `frac=51`) | `MiniCPM-V-4.5` (`tf-dev-v1`*) | `0 / 0 / 0` | 26/112 (23.21%) (`unc` 52.68%) | 8/51 (15.69%) | 3/51 (5.88%) | 22/112 (19.64%) (`unc` 91.96%) | 0/112 (0.00%) |
| | `MiniCPM-V-4.5` (`vllm-dev-v1`*) | `0 / 0 / 0` | 38/112 (33.93%) (`unc` 15.18%) | 8/51 (15.69%) | 3/51 (5.88%) | 24/112 (21.43%) (`unc` 66.07%) | 1/112 (0.89%) |
| | `MiniCPM-V-4.5` (`runb-noimage` 历史) | `0 / 0 / 0` | 9/112 (8.04%) (`unc` 0.00%) | 8/51 (15.69%) | 3/51 (5.88%) | 21/112 (18.75%) (`unc` 0.00%) | 0/112 (0.00%) |
| | **`Qwen3-VL-8B-Instruct`** (`vllm` Run A) | `0 / 0 / 0` | 50/112 (44.64%) (`unc` 3.57%) | 8/51 (15.69%) | 3/51 (5.88%) | 16/112 (14.29%) (`unc` 53.57%) | 1/112 (0.89%) |
| | `Qwen3-VL-8B-Instruct` (`runb-noimage` 配对) | `0 / 0 / 0` | 7/112 (6.25%) (`unc` 100.00%) | 8/51 (15.69%) | 3/51 (5.88%) | 25/112 (22.32%) (`unc` 100.00%) | 0/112 (0.00%) |
| | `InternVL3-8B` (非 HF `vllm` Run A, 0% 严格) | `0 / 0 / 0` | **57/112 (50.89%)** (`unc` 0.00%) | **10/51 (19.61%)** | **6/51 (11.76%)** | **26/112 (23.21%)** (`unc` 91.96%) | 2/112 (1.79%) |
| | **`InternVL3-8B-hf`** (HF `vllm` Run A, 0% 严格) | `0 / 0 / 0` | **57/112 (50.89%)** (`unc` 0.00%) | **10/51 (19.61%)** | **6/51 (11.76%)** | **26/112 (23.21%)** (`unc` 91.96%) | **3/112 (2.68%)** |
| | `InternVL3-8B-hf` (`runb-noimage` 配对, 0% 严格) | `0 / 0 / 0` | 42/112 (37.50%) (`unc` 0.00%) ⚠️ | 27/51 (52.94%) ⚠️ | 28/51 (54.90%) ⚠️ | 66/112 (58.93%) (`unc` 0.00%) ⚠️ | 0/112 (0.00%) |
| | `InternVL3_5-8B` (非 HF `vllm` Run A) | `0 / 0 / 0` | 52/112 (46.43%) (`unc` 6.25%) | 8/51 (15.69%) | 3/51 (5.88%) | 25/112 (22.32%) (`unc` 100.00%) | 0/112 (0.00%) |
| | **`InternVL3_5-8B-HF`** (HF `vllm` Run A) | `0 / 0 / 0` | 52/112 (46.43%) (`unc` 6.25%) | 8/51 (15.69%) | 3/51 (5.88%) | 25/112 (22.32%) (`unc` 100.00%) | 0/112 (0.00%) |
| | `InternVL3_5-8B-HF` (`runb-noimage` 配对) | `0 / 0 / 0` | 7/112 (6.25%) (`unc` 100.00%) | 8/51 (15.69%) | 3/51 (5.88%) | 25/112 (22.32%) (`unc` 100.00%) | 0/112 (0.00%) |
| **`w_200_400`** (`200 < w < 400`，20 源 / `n=42` / `frac=17`) | `MiniCPM-V-4.5` (`tf-dev-v1`*) | `0 / 0 / 0` | 12/42 (28.57%) (`unc` 11.90%) | 2/17 (11.76%) | 2/17 (11.76%) | 6/42 (14.29%) (`unc` 40.48%) | 0/42 (0.00%) |
| | `MiniCPM-V-4.5` (`vllm-dev-v1`*) | `0 / 0 / 0` | 14/42 (33.33%) (`unc` 2.38%) | 2/17 (11.76%) | 1/17 (5.88%) | 12/42 (28.57%) (`unc` 57.14%) | 1/42 (2.38%) |
| | `MiniCPM-V-4.5` (`runb-noimage` 历史) | `0 / 0 / 0` | 4/42 (9.52%) (`unc` 0.00%) | 2/17 (11.76%) | 1/17 (5.88%) | 10/42 (23.81%) (`unc` 0.00%) ⚠️ | 0/42 (0.00%) |
| | **`Qwen3-VL-8B-Instruct`** (`vllm` Run A) | `0 / 0 / 0` | **22/42 (52.38%)** (`unc` 0.00%) | 2/17 (11.76%) | 1/17 (5.88%) | 10/42 (23.81%) (`unc` 11.90%) | **4/42 (9.52%)** |
| | `Qwen3-VL-8B-Instruct` (`runb-noimage` 配对) | `0 / 0 / 0` | 1/42 (2.38%) (`unc` 100.00%) | 2/17 (11.76%) | 1/17 (5.88%) | 22/42 (52.38%) (`unc` 100.00%) | 0/42 (0.00%) |
| | `InternVL3-8B` (非 HF `vllm` Run A, 0% 严格) | `0 / 0 / 0` | 19/42 (45.24%) (`unc` 0.00%) | **3/17 (17.65%)** | 2/17 (11.76%) | 16/42 (38.10%) (`unc` 64.29%) | 2/42 (4.76%) |
| | **`InternVL3-8B-hf`** (HF `vllm` Run A, 0% 严格) | `0 / 0 / 0` | 19/42 (45.24%) (`unc` 0.00%) | **3/17 (17.65%)** | **3/17 (17.65%)** | 18/42 (42.86%) (`unc` 52.38%) | 2/42 (4.76%) |
| | `InternVL3-8B-hf` (`runb-noimage` 配对, 0% 严格) | `0 / 0 / 0` | 13/42 (30.95%) (`unc` 0.00%) ⚠️ | 4/17 (23.53%) ⚠️ | 12/17 (70.59%) ⚠️ | 10/42 (23.81%) (`unc` 0.00%) | 0/42 (0.00%) |
| | `InternVL3_5-8B` (非 HF `vllm` Run A) | `0 / 0 / 0` | **22/42 (52.38%)** (`unc` 9.52%) | 2/17 (11.76%) | 1/17 (5.88%) | **22/42 (52.38%)** (`unc` 97.62%) | 0/42 (0.00%) |
| | **`InternVL3_5-8B-HF`** (HF `vllm` Run A) | `0 / 0 / 0` | 21/42 (50.00%) (`unc` 11.90%) | 2/17 (11.76%) | 1/17 (5.88%) | **22/42 (52.38%)** (`unc` 97.62%) | 0/42 (0.00%) |
| | `InternVL3_5-8B-HF` (`runb-noimage` 配对) | `0 / 0 / 0` | 1/42 (2.38%) (`unc` 100.00%) | 2/17 (11.76%) | 1/17 (5.88%) | 22/42 (52.38%) (`unc` 100.00%) | 0/42 (0.00%) |
| **`w_gt_400`** (`w ≥ 400`，19 源 / `n=56` / `frac=18`) | `MiniCPM-V-4.5` (`tf-dev-v1`*) | `0 / 0 / 0` | 33/56 (58.93%) (`unc` 1.79%) | 0/18 (0.00%) | **3/18 (16.67%)** | 28/56 (50.00%) (`unc` 44.64%) | 5/56 (8.93%) |
| | `MiniCPM-V-4.5` (`vllm-dev-v1`*) | `0 / 0 / 0` | 30/56 (53.57%) (`unc` 0.00%) | 0/18 (0.00%) | 1/18 (5.56%) | 25/56 (44.64%) (`unc` 51.79%) | 6/56 (10.71%) |
| | `MiniCPM-V-4.5` (`runb-noimage` 历史) | `0 / 0 / 0` | 4/56 (7.14%) (`unc` 0.00%) | 0/18 (0.00%) | 1/18 (5.56%) | 41/56 (73.21%) (`unc` 0.00%) ⚠️ | 0/56 (0.00%) |
| | **`Qwen3-VL-8B-Instruct`** (`vllm` Run A) | `0 / 0 / 0` | **34/56 (60.71%)** (`unc` 0.00%) | 1/18 (5.56%) | 1/18 (5.56%) | **32/56 (57.14%)** (`unc` 0.00%) | **10/56 (17.86%)** |
| | `Qwen3-VL-8B-Instruct` (`runb-noimage` 配对) | `0 / 0 / 0` | 6/56 (10.71%) (`unc` 100.00%) | 0/18 (0.00%) | 1/18 (5.56%) | 4/56 (7.14%) (`unc` 100.00%) | 0/56 (0.00%) |
| | `InternVL3-8B` (非 HF `vllm` Run A, 0% 严格) | `0 / 0 / 0` | 26/56 (46.43%) (`unc` 0.00%) | 1/18 (5.56%) | 2/18 (11.11%) | 13/56 (23.21%) (`unc` 50.00%) | 2/56 (3.57%) |
| | **`InternVL3-8B-hf`** (HF `vllm` Run A, 0% 严格) | `0 / 0 / 0` | 25/56 (44.64%) (`unc` 0.00%) | **2/18 (11.11%)** | 2/18 (11.11%) | 15/56 (26.79%) (`unc` 44.64%) | 2/56 (3.57%) |
| | `InternVL3-8B-hf` (`runb-noimage` 配对, 0% 严格) | `0 / 0 / 0` | 14/56 (25.00%) (`unc` 0.00%) ⚠️ | 5/18 (27.78%) ⚠️ | 10/18 (55.56%) ⚠️ | 11/56 (19.64%) (`unc` 0.00%) | 0/56 (0.00%) |
| | `InternVL3_5-8B` (非 HF `vllm` Run A) | `0 / 0 / 0` | 31/56 (55.36%) (`unc` 3.57%) | 0/18 (0.00%) | 1/18 (5.56%) | 5/56 (8.93%) (`unc` 94.64%) | 0/56 (0.00%) |
| | **`InternVL3_5-8B-HF`** (HF `vllm` Run A) | `0 / 0 / 0` | 31/56 (55.36%) (`unc` 3.57%) | 0/18 (0.00%) | 1/18 (5.56%) | 5/56 (8.93%) (`unc` 94.64%) | 0/56 (0.00%) |
| | `InternVL3_5-8B-HF` (`runb-noimage` 配对) | `0 / 0 / 0` | 6/56 (10.71%) (`unc` 100.00%) | 0/18 (0.00%) | 1/18 (5.56%) | 4/56 (7.14%) (`unc` 100.00%) | 0/56 (0.00%) |

> `*` 标注的 `MiniCPM-V-4.5` 两组视觉 Run 属历史初步观测（processor 实际像素上限未核实/未记录）；表内加粗数值仅在视觉 Run A 间标注领先，不与 Run B 盲答先验混比。由于三档对应的源视频集合与真值分布各不相同，跨档数值差异仅作观测记录，不直接等同于画幅分辨率的因果效应。

### 3.2 严格配对 Run A vs Run B 核心诊断发现（按三画幅档分述）

借助 PR #29 落地的 `infer.py --no-image` 严格配对能力（同权重快照、同 `vLLM 0.34.0` 服务、同解码参数 `temperature=0.0, max_tokens=512`、同 `prompt_id`），三款主力开放基座在「看图 vs 盲答」的真实视觉依赖上呈现截然分化：

1. **`Qwen3-VL-8B-Instruct`（唯一兼具「盲测 100% 诚实」与「高画幅显著视觉增益」的基座）**：
   - **Run B 诚实度满分**：无图输入下，全部 210 条样本的全部 11 个叶字段均 **100.00% 诚实输出 `无法判断`**，零先验幻觉；严格单 JSON 格式在 Run A/B 均保持 **210/210 (100.0%)**。
   - **三画幅档真实视觉净增益（Run A − Run B）**：
     - `w_le_200`（`n=112`）：`断裂状态` `+38.39 pp`（`6.25% → 44.64%`），`五类全对` `+0.89 pp`；`断裂现象.伸长` `-8.04 pp`（Run B 全 `unc` 撞中人工 22.32% `unc`，Run A 在低画幅仅 53.57% `unc`）；
     - `w_200_400`（`n=42`）：`断裂状态` **`+50.00 pp`**（`2.38% → 52.38%`），`五类全对` `+9.52 pp`；`断裂现象.伸长` `-28.57 pp`（因该档人工 `unc` 高达 52.38%，全 `unc` 盲答被动撞中）；
     - `w_gt_400`（`n=56`）：`断裂状态` **`+50.00 pp`**（`10.71% → 60.71%`），`断裂现象.伸长` **`+50.00 pp`**（`7.14% → 57.14%`，且 `unc=0%`），`断裂模式` `+5.56 pp`（命中 `脆性断裂` 1/5），`五类全对` **`+17.86 pp`**（`0% → 17.86%`）。
   - **待微调突破点**：零样本下对真实断裂仍偏保守（`发生断裂` 召回为 `w_le_200` `0/42`、`w_200_400` `1/13`、`w_gt_400` `3/14`，三档 `已断裂` 召回均为 `0`），是 SFT 阶段的核心提分目标。

2. **`InternVL3-8B-hf`（格式违约 + Run B 严重先验幻觉红灯）**：
   - **与旧非 HF 权重一致性**：HF 版 Run A 与早期非 HF 版行为高度接近（三档 `断裂状态` `50.89% / 45.24% / 44.64%`，`w_gt_400` 命中 `发生断裂` `6/14` 但同时将 `13/32` 条 `未断裂` 误报为 `发生断裂`；210/210 仍全量包裹 ```` ```json ```` 围栏，严格格式 `0.0%`）。
   - **Run B 严重先验幻觉**：剥离图像后，模型**并未输出 `无法判断`**，而是对全部 210 条样本**恒定幻觉输出完全相同的先验模板**（`断裂状态=发生断裂`、`断裂模式=脆性断裂`、`断裂位置=标距内`、`开裂=是`、其余 7 项均为 `否`，全字段 `unc=0.00%`）。
   - **盲答反超警示（按档）**：因 Run A 大量退化为 `未断裂`（171/210），恒定猜先验的 Run B 在三画幅档的 `断裂模式`（`52.94% / 23.53% / 27.78%` vs Run A `19.61% / 17.65% / 11.11%`）与 `断裂位置`（`54.90% / 70.59% / 55.56%` vs Run A `11.76% / 17.65% / 11.11%`）及 `w_le_200` `伸长`（`58.93%` vs `23.21%`）全面反超 Run A。这证明单看某字段绝对准确率会掩盖先验猜题风险，必须结合 `unc` 率与配对 Run B 联合审视。

3. **`InternVL3_5-8B-HF`（格式修复、Run B 诚实，但 Run A 过度保守退化）**：
   - 严格格式合法率 `209/210 (99.52%)`（Run A 仅 `w_200_400` `video_0084_pre_05` 带围栏）与 `210/210 (100.0%)`（Run B）；Run B 同样 100% 诚实输出 `无法判断`。
   - 但 Run A 与旧非 HF 版一致呈现极端保守拒答：`未断裂` 196 条 + `无法判断` 14 条，三档 `发生断裂` 与 `已断裂` 召回全为 `0`，`断裂模式`/`断裂位置` 全档 100% `unc`，三档 `五类全对` 均为 **`0.00%`**。

4. **`MiniCPM-V-4.5`（历史初步观测与非严格配对 Run B 留档）**：
   - 历史描述性 Run B（2026-11-25，解码参数未落盘）在三档均恒定输出 `断裂状态=已断裂` 与 `断裂现象.伸长=是`（`w_gt_400` 档 `伸长` 盲答 `41/56 = 73.21%` 仍高于全部零样本视觉 Run）；两组视觉 Run 需补齐 processor 实际逐帧像素上限运行身份后方可进入正式跨模型主榜。

### 3.3 4 款基座单卡 RTX 4090（24 GB）`vlm-sft` QLoRA 冒烟结果汇总

为验证实际可微调性与训练/推理视觉分辨率对齐，2026-11-26 在训练机（1× RTX 4090 24,564 MiB）新建隔离 Conda 环境 `vlm-sft`（克隆自 `agent`，`transformers==4.57.6`，editable `LlamaFactory@4447137e`），用 10 条合成 8 帧样本（`disable_shuffling: true` 首两步直接压测最大 `804×1072 = 861,888 px` 与 `726×968 = 702,768 px` 样本，`lora_rank=16`、`lora_target=all`、`gradient_checkpointing=true`、`bs=1`、`max_steps=2`）实测全部 4 款第一梯队基座：

| 基座模型 | `LlamaFactory` 模板与配置 | 显存峰值（4090 24,564 MiB） | 单步耗时 / 状态 | 训练 vs vLLM 推理分辨率对齐与关键发现 |
| --- | --- | ---: | --- | --- |
| **`Qwen3-VL-8B-Instruct`** | `qwen3_vl_nothink`，`bf16` LoRA（`1,200k` / `262k`） | `23,457` / `24,049 MiB` | **OOM** | 24 GB 卡 8 帧场景必须启用 4-bit QLoRA |
| **`Qwen3-VL-8B-Instruct`**（**锁定黄金配方**） | `qwen3_vl_nothink`，**`4-bit bnb` + `paged_adamw_8bit` + `expandable_segments:True`**，`image_max_pixels=1,200,000` / `min=65,536` | **`22,525 MiB`**（余量 `> 2.0 GiB`） | `~6.37 s/step` · **PASS** | **100% 全分辨率对齐**（覆盖 L2 最大 `924×1232` 不降采样）；导出 `167 MB` adapter 已实测通过 `vLLM 0.34.0 --enable-lora` 加载并单请求 `3.81s` 返回合法五类 JSON（注：默认 AdamW 峰值 `24,047 MiB` 过紧） |
| **`MiniCPM-V-4.5`** | `minicpm_v`，`4-bit bnb` + `paged_adamw_8bit`，`image_max_pixels=589,824` / `min=65,536`，`trust_remote_code=true` | `15,515 MiB` | `~3.78 s/step` · **PASS** | `transformers 4.57.6` 直接路径加载无点号报错；`resampler` 与 `vpm` 正常冻结不量化（`0.4994%` 可训参数） |
| **`InternVL3-8B-hf`** | `intern_vl`，`4-bit bnb` + `paged_adamw_8bit`，`cutoff_len=12288`，**`crop_to_patches: false`** | `13,763 MiB` | `~2.02 s/step` · **PASS** | 开启 `crop_to_patches: true` **报错失败**（`tokens: 12162, features: 26624`）：`mm_plugin.py:847` 硬编码 `max_patches: 12`，不改框架源码无法在 SFT 对齐 vLLM `max_patches: 4` |
| **`InternVL3_5-8B-HF`** | `intern_vl`，`4-bit bnb` + `paged_adamw_8bit`，`cutoff_len=12288`，**`crop_to_patches: false`** | `14,697 MiB` | `~2.29 s/step` · **PASS** | 同上：`crop_to_patches: true` 触发同一 `mm_plugin.py:847` `max_patches: 12` 报错 |

> **决策落地**：结合配对 Run A/B 诊断与上表 4090 实测，用户已确认 **[DEC-008](../../decisions/0008-finetune-base-model-and-sft-recipe.md)**，正式锁定 **`Qwen3-VL-8B-Instruct`** 与上述黄金 4-bit QLoRA 配方为首轮微调主路线，并确立 `vlm-eval` vLLM 严禁 `PATH` 混入 `vlm-sft/bin`（避免 `ninja` + `nvcc` 触发 FlashInfer JIT 崩溃）以及 SFT 严格三折隔离红线（Fold 0 仅在 `eval-dev-v1 ∩ fold_0_val` 69 条上验证，永不触碰 `eval-test-v1`）。

---

## 4. 各 Run 归档目录与产物直达链接

> **审计与引用边界**：下表原样归档的 `report.md` 与 `results.json` 为评分器原始输出，内含跨档总体标签指标，**仅供审计复算**；正式引用与跨模型比较须一律使用按三画幅档拆分的 [`width-band-breakdown.md`](width-band-breakdown.md)。

| Run ID | 角色与后端 | 可读评分报告（原件，仅供审计） | 结构化评分结果（原件，仅供审计） | 运行元数据与快照身份 |
| --- | --- | --- | --- | --- |
| [`20261125-minicpm-v45-tf-dev-v1`](20261125-minicpm-v45-tf-dev-v1/) | Run A 初步观测（`MiniCPM-V-4.5` / `transformers` DEC-006 方向） | [`report.md`](20261125-minicpm-v45-tf-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-tf-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261125-minicpm-v45-tf-dev-v1/predictions.jsonl.meta.json) |
| [`20261125-minicpm-v45-vllm-dev-v1`](20261125-minicpm-v45-vllm-dev-v1/) | Run A 初步观测（`MiniCPM-V-4.5` / `vLLM HTTP` 对照） | [`report.md`](20261125-minicpm-v45-vllm-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261125-minicpm-v45-vllm-dev-v1/predictions.jsonl.meta.json) |
| [`20261125-minicpm-v45-runb-noimage-dev-v1`](20261125-minicpm-v45-runb-noimage-dev-v1/) | Run B 描述性纯文本先验对照（`MiniCPM-V-4.5` / `vLLM 0.34.0` HTTP） | [`report.md`](20261125-minicpm-v45-runb-noimage-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-runb-noimage-dev-v1/results.json) | [`run_meta.json`](20261125-minicpm-v45-runb-noimage-dev-v1/run_meta.json) |
| [`20261126-qwen3-vl-8b-vllm-dev-v1`](20261126-qwen3-vl-8b-vllm-dev-v1/) | Run A（`Qwen3-VL-8B-Instruct` / `vLLM 0.34.0` HTTP） | [`report.md`](20261126-qwen3-vl-8b-vllm-dev-v1/report.md) | [`results.json`](20261126-qwen3-vl-8b-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-qwen3-vl-8b-vllm-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-qwen3-vl-8b-vllm-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-qwen3-vl-8b-vllm-dev-v1/snapshot_identity.json) |
| [`20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1`](20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1/) | Run B 严格配对无图盲测（`Qwen3-VL-8B-Instruct` / `vLLM 0.34.0` HTTP `--no-image`） | [`report.md`](20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1/report.md) | [`results.json`](20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-qwen3-vl-8b-vllm-runb-noimage-dev-v1/snapshot_identity.json)（同快照自 Run A 原样绑定） |
| [`20261126-internvl3-8b-vllm-dev-v1`](20261126-internvl3-8b-vllm-dev-v1/) | Run A 历史非 HF 版（`InternVL3-8B` / `vLLM 0.34.0` HTTP，`max_dynamic_patch=4` + `use_thumbnail=true`） | [`report.md`](20261126-internvl3-8b-vllm-dev-v1/report.md) | [`results.json`](20261126-internvl3-8b-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-internvl3-8b-vllm-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-internvl3-8b-vllm-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-internvl3-8b-vllm-dev-v1/snapshot_identity.json) |
| [`20261126-internvl3-8b-hf-vllm-dev-v1`](20261126-internvl3-8b-hf-vllm-dev-v1/) | Run A HF 版（`InternVL3-8B-hf` / `vLLM 0.34.0` HTTP，`max_patches=4`） | [`report.md`](20261126-internvl3-8b-hf-vllm-dev-v1/report.md) | [`results.json`](20261126-internvl3-8b-hf-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-internvl3-8b-hf-vllm-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-internvl3-8b-hf-vllm-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-internvl3-8b-hf-vllm-dev-v1/snapshot_identity.json) |
| [`20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1`](20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1/) | Run B 严格配对无图盲测 HF 版（`InternVL3-8B-hf` / `vLLM 0.34.0` HTTP `--no-image`） | [`report.md`](20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1/report.md) | [`results.json`](20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-internvl3-8b-hf-vllm-runb-noimage-dev-v1/snapshot_identity.json)（同快照自 Run A 原样绑定） |
| [`20261126-internvl3_5-8b-vllm-dev-v1`](20261126-internvl3_5-8b-vllm-dev-v1/) | Run A 历史非 HF 版（`InternVL3_5-8B` / `vLLM 0.34.0` HTTP，`max_dynamic_patch=4` + `use_thumbnail=true`） | [`report.md`](20261126-internvl3_5-8b-vllm-dev-v1/report.md) | [`results.json`](20261126-internvl3_5-8b-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-internvl3_5-8b-vllm-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-internvl3_5-8b-vllm-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-internvl3_5-8b-vllm-dev-v1/snapshot_identity.json) |
| [`20261126-internvl3_5-8b-hf-vllm-dev-v1`](20261126-internvl3_5-8b-hf-vllm-dev-v1/) | Run A HF 版（`InternVL3_5-8B-HF` / `vLLM 0.34.0` HTTP，`max_patches=4`） | [`report.md`](20261126-internvl3_5-8b-hf-vllm-dev-v1/report.md) | [`results.json`](20261126-internvl3_5-8b-hf-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-internvl3_5-8b-hf-vllm-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-internvl3_5-8b-hf-vllm-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-internvl3_5-8b-hf-vllm-dev-v1/snapshot_identity.json) |
| [`20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1`](20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1/) | Run B 严格配对无图盲测 HF 版（`InternVL3_5-8B-HF` / `vLLM 0.34.0` HTTP `--no-image`） | [`report.md`](20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1/report.md) | [`results.json`](20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-internvl3_5-8b-hf-vllm-runb-noimage-dev-v1/snapshot_identity.json)（同快照自 Run A 原样绑定） |

> 注：上述全部 11 组归档目录的 `report.md`、`results.json`、`run_meta.json`、`predictions.jsonl.meta.json` 均从训练机 `/home/liuyang/文档/TensileAgent-Finetune/evaluations/runs/` 原样同步（零字节修改）；2026-11-26 的 8 组 Run 均附有与静态模型快照绑定的 `snapshot_identity.json`（记录 `config.json` / `preprocessor_config.json` / `model.safetensors.index.json` / `tokenizer_config.json` SHA-256、全部 4 份 `.safetensors` 权重分片逐片 SHA-256 与字节数及生效视觉 processor 参数，满足 `docs/eval/inference-entry.md` §4 与 DEC-006 身份契约；三组 Run B 沿用各自配对 Run A 的同快照 `snapshot_identity.json` 原件，其中 `/data/models/Qwen3-VL-8B-Instruct` 经独立核验自 `2026-11-25 22:08` 保持静态未动）。完整分档必报项与预处理边界另见 [`width-band-breakdown.md`](width-band-breakdown.md)。
