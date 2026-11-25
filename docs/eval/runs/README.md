# 正式评测结果总入口（`docs/eval/runs/`）

> 本页汇总本轮五类标签离线评测（`five-label-score/3`）在冻结开发集 [`eval-dev-v1`](../../../data/eval-subsets/eval-dev-v1.json)（210 条 / 87 源，全部 `source_type = real`，严格按 [DEC-007](../../decisions/0007-dev-test-dedup-exclusion.md) 排除近重复源）上的正式评测结果与跨模型对照总表。

**失效条件：** 当评测子集由 `eval-dev-v1` 切换至新版本、评分器版本脱离 `five-label-score/3`、或本目录下既有 Run 产物被替换/撤回而未同步更新本页总表与链接时，本页汇总结论须重新核对。

---

## 1. 本目录与训练机 `evaluations/` 的分工

| 存储位置 | Git 状态 | 承担内容 | 说明 |
| --- | --- | --- | --- |
| **`docs/eval/runs/`**（本目录） | **受 Git 跟踪**（通过 PR 同步回本机） | 跨模型汇总总入口（本页）、三画幅档完整必报项分档报告（[`width-band-breakdown.md`](width-band-breakdown.md)）及每次正式 Run 原样归档的 `report.md`、`results.json`、运行元数据（`predictions.jsonl.meta.json` 或 `run_meta.json`） | 不提交独立的原始 `predictions.jsonl`、推理/显存日志（`*.log`）或 PNG 抽帧；注：原样归档的 `results.json` 为 `score.py` 原始输出，内部仍保留逐样本 `raw_output` 与预测元数据以便审计复算 |
| 训练机 `/home/liuyang/文档/TensileAgent-Finetune/evaluations/` | **被 `.gitignore` 忽略**（受 `tests/test_layout_migration_guard.py` T6 守卫约束） | `eval-dev-v1/` 共享抽帧输入（1,680 张 PNG 与清单）、`runs/` 完整原始产物（含 `predictions.jsonl`、`*.log`、`score/` 与权重代码白名单）、`smoke/` 小样本冒烟留档 | 大体积媒体与原始推理日志留在训练机，避免污染 Git 仓库并守住顶层 `/evaluations` 忽略边界 |

---

## 2. 第一梯队模型评测状态总览（`eval-dev-v1`，210 条 / 87 源）

> **评分与口径**：`five-label-score/3`（`prompt@sha256:cf299d672281e12ea5f3964bb08ffbe2d237e1dfad3503861e7e21a5872cc4cf`，8 帧 `evenly_spaced_inclusive`、`fail_closed`、`resize: null`，按 [DEC-006](../../decisions/0006-eval-frame-sampling-and-model-lineup.md) 执行）。
> 按 [`docs/eval/eval-subset.md`](../eval-subset.md) §3 硬约束：**同一标签不得跨画幅档合并为单一数字**，因此本节仅列运行状态、格式合法率、请求状态与归档入口；所有标签准确率与 `无法判断` 比例统一在 §3 与 [`width-band-breakdown.md`](width-band-breakdown.md) 按三画幅档独立并列展示。本轮按 [DEC-003](../../decisions/0003-five-label-eval-scope.md) 只报数、不设通过阈值或自动晋级。

| 模型（[DEC-006](../../decisions/0006-eval-frame-sampling-and-model-lineup.md) 第一梯队） | Run 定位与后端 | 状态 | 格式严格合法 | 请求失败 / 超时 / 未处理 | 直达目录 |
| --- | --- | --- | --- | --- | --- |
| **`MiniCPM-V-4.5`** | **Run A（`transformers` DEC-006 方向）**：`0.1 s` 量化 `temporal_ids`，`max_slice_nums=1` | 历史初步观测（2026-11-25；processor 实际逐帧像素上限未核实，补齐运行身份前不入正式跨模型主榜） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261125-minicpm-v45-tf-dev-v1/`](20261125-minicpm-v45-tf-dev-v1/) |
| **`MiniCPM-V-4.5`** | **Run A（`vLLM HTTP` 对照）**：同 8 帧输入服务化对照 | 历史初步观测（2026-11-25；服务端 processor 实际像素上限未记录，补齐前不入正式跨模型主榜） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261125-minicpm-v45-vllm-dev-v1/`](20261125-minicpm-v45-vllm-dev-v1/) |
| **`MiniCPM-V-4.5`** | **Run B 无画面盲答**：`vLLM 0.34.0` HTTP 描述性纯文本先验对照（剥离全部图像帧，解码参数未记入 `run_meta.json`） | 历史初步观测（2026-11-25；仅作描述性先验对照，非严格配对实验） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261125-minicpm-v45-runb-noimage-dev-v1/`](20261125-minicpm-v45-runb-noimage-dev-v1/) |
| **`Qwen3-VL-8B-Instruct`** | **Run A（`vLLM 0.34.0` HTTP）**：`bfloat16`、`--max-model-len 8192`、`mm_processor_kwargs=null`（快照默认 `Qwen2VLImageProcessorFast`：`min_pixels=65,536`、`max_pixels=16,777,216`、`patch_size=16`、`merge_size=2`） | 首轮 Run A 已完成并归档（2026-11-26；无配对 Run B） | 210/210 (100.0%) | `0 / 0 / 0` | [`20261126-qwen3-vl-8b-vllm-dev-v1/`](20261126-qwen3-vl-8b-vllm-dev-v1/) |
| **`InternVL3-8B`**（原生非 `-HF`） | **Run A（`vLLM 0.34.0` HTTP）**：`bfloat16`、`--trust-remote-code`、`--max-model-len 12288`、`--hf-overrides '{"max_dynamic_patch": 4}'`（`use_thumbnail=true`，动态网格上限 4 块 + 1 块全图缩略图 = 单帧至多 5 块 `448×448`） | 首轮 Run A 已完成并归档（2026-11-26；全量带 ```` ```json ```` 围栏但均成功解析；无配对 Run B） | 0/210 (0.0%) | `0 / 0 / 0` | [`20261126-internvl3-8b-vllm-dev-v1/`](20261126-internvl3-8b-vllm-dev-v1/) |
| **`InternVL3_5-8B`**（标准版不含 ViR） | **Run A（`vLLM 0.34.0` HTTP）**：`bfloat16`、`--trust-remote-code`、`--max-model-len 12288`、`--hf-overrides '{"max_dynamic_patch": 4}'`（`use_thumbnail=true`，动态网格上限 4 块 + 1 块全图缩略图 = 单帧至多 5 块 `448×448`） | 首轮 Run A 已完成并归档（2026-11-26；1 条带围栏；无配对 Run B） | 209/210 (99.5%) | `0 / 0 / 0` | [`20261126-internvl3_5-8b-vllm-dev-v1/`](20261126-internvl3_5-8b-vllm-dev-v1/) |

---

## 3. 三画幅档独立对比、基座观察与 Run B 先验红灯

### 3.1 三画幅档独立对比表（`eval-dev-v1` 宽度分档：`width_rule_le200_lt400`）

> 按 [`docs/eval/eval-subset.md`](../eval-subset.md) §1、§3、§4 契约要求，在各档样本上使用 `script.five_label_eval.score.aggregate` 独立统计（`eval-dev-v1` 全部为 `source_type = real`，虚拟数据 0 条；L3 落盘 `resize: null`）。下表展示 4 款第一梯队基座（共 6 个正式 Run）核心字段分档对照；**全部 11 个叶字段**的分档准确率、模型与人工 `无法判断` 比例及各 Run 实际生效的 vLLM/processor 参数详见 **[三画幅档完整必报项分档报告](width-band-breakdown.md)**。
> 注：各模型视觉预处理存在差异——`MiniCPM-V-4.5` 两组视觉 Run 尚未记录 processor 实际像素上限（标为历史初步观测）；`Qwen3-VL-8B-Instruct` 沿用模型快照 `preprocessor_config.json` 默认配置（`Qwen2VLImageProcessorFast`：`shortest_edge/min_pixels=65,536`、`longest_edge/max_pixels=16,777,216`、`patch_size=16`、`merge_size=2`，`prompt_tokens` 1190~7430）；`InternVL3-8B` 与 `InternVL3_5-8B` 在 `config.json` 启用 `use_thumbnail=true`、`force_image_size=448`，并通过 `--hf-overrides '{"max_dynamic_patch": 4}'` 将动态网格上限设为 4 块（多块时追加 1 块全图缩略图，单帧实际总块数上限为 `4+1=5` 块 `448×448`、每块 256 视觉 token，单帧上限 1,280 视觉 token）以适配 `--max-model-len 12288`（详见各 Run `run_meta.json`）。

| 画幅档（来源数 / 片段数 / 断裂真值数） | 模型 / Run | 请求失败 / 超时 / 未处理 | 断裂状态准确率（模型 `unc`） | 断裂模式 (`frac`) | 断裂位置 (`frac`) | 断裂现象.伸长（模型 `unc`） | 五类全对（补充） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **`w_le_200`** (`w ≤ 200`，48 源 / `n=112` / `frac=51`) | `MiniCPM-V-4.5` (`tf-dev-v1`*) | `0 / 0 / 0` | 26/112 (23.21%) (`unc` 52.68%) | 8/51 (15.69%) | 3/51 (5.88%) | 22/112 (19.64%) (`unc` 91.96%) | 0/112 (0.00%) |
| | `MiniCPM-V-4.5` (`vllm-dev-v1`*) | `0 / 0 / 0` | 38/112 (33.93%) (`unc` 15.18%) | 8/51 (15.69%) | 3/51 (5.88%) | 24/112 (21.43%) (`unc` 66.07%) | 1/112 (0.89%) |
| | `MiniCPM-V-4.5` (`runb-noimage`) | `0 / 0 / 0` | 9/112 (8.04%) (`unc` 0.00%) | 8/51 (15.69%) | 3/51 (5.88%) | 21/112 (18.75%) (`unc` 0.00%) | 0/112 (0.00%) |
| | **`Qwen3-VL-8B-Instruct`** (`vllm`) | `0 / 0 / 0` | 50/112 (44.64%) (`unc` 3.57%) | 8/51 (15.69%) | 3/51 (5.88%) | 16/112 (14.29%) (`unc` 53.57%) | 1/112 (0.89%) |
| | **`InternVL3-8B`** (`vllm`, 0% 严格格式) | `0 / 0 / 0` | **57/112 (50.89%)** (`unc` 0.00%) | **10/51 (19.61%)** | **6/51 (11.76%)** | **26/112 (23.21%)** (`unc` 91.96%) | **2/112 (1.79%)** |
| | **`InternVL3_5-8B`** (`vllm`) | `0 / 0 / 0` | 52/112 (46.43%) (`unc` 6.25%) | 8/51 (15.69%) | 3/51 (5.88%) | 25/112 (22.32%) (`unc` 100.00%) | 0/112 (0.00%) |
| **`w_200_400`** (`200 < w < 400`，20 源 / `n=42` / `frac=17`) | `MiniCPM-V-4.5` (`tf-dev-v1`*) | `0 / 0 / 0` | 12/42 (28.57%) (`unc` 11.90%) | 2/17 (11.76%) | 2/17 (11.76%) | 6/42 (14.29%) (`unc` 40.48%) | 0/42 (0.00%) |
| | `MiniCPM-V-4.5` (`vllm-dev-v1`*) | `0 / 0 / 0` | 14/42 (33.33%) (`unc` 2.38%) | 2/17 (11.76%) | 1/17 (5.88%) | 12/42 (28.57%) (`unc` 57.14%) | 1/42 (2.38%) |
| | `MiniCPM-V-4.5` (`runb-noimage`) | `0 / 0 / 0` | 4/42 (9.52%) (`unc` 0.00%) | 2/17 (11.76%) | 1/17 (5.88%) | 10/42 (23.81%) (`unc` 0.00%) ⚠️ | 0/42 (0.00%) |
| | **`Qwen3-VL-8B-Instruct`** (`vllm`) | `0 / 0 / 0` | **22/42 (52.38%)** (`unc` 0.00%) | 2/17 (11.76%) | 1/17 (5.88%) | 10/42 (23.81%) (`unc` 11.90%) | **4/42 (9.52%)** |
| | **`InternVL3-8B`** (`vllm`, 0% 严格格式) | `0 / 0 / 0` | 19/42 (45.24%) (`unc` 0.00%) | **3/17 (17.65%)** | **2/17 (11.76%)** | 16/42 (38.10%) (`unc` 64.29%) | 2/42 (4.76%) |
| | **`InternVL3_5-8B`** (`vllm`) | `0 / 0 / 0` | **22/42 (52.38%)** (`unc` 9.52%) | 2/17 (11.76%) | 1/17 (5.88%) | **22/42 (52.38%)** (`unc` 97.62%) | 0/42 (0.00%) |
| **`w_gt_400`** (`w ≥ 400`，19 源 / `n=56` / `frac=18`) | `MiniCPM-V-4.5` (`tf-dev-v1`*) | `0 / 0 / 0` | 33/56 (58.93%) (`unc` 1.79%) | 0/18 (0.00%) | **3/18 (16.67%)** | 28/56 (50.00%) (`unc` 44.64%) | 5/56 (8.93%) |
| | `MiniCPM-V-4.5` (`vllm-dev-v1`*) | `0 / 0 / 0` | 30/56 (53.57%) (`unc` 0.00%) | 0/18 (0.00%) | 1/18 (5.56%) | 25/56 (44.64%) (`unc` 51.79%) | 6/56 (10.71%) |
| | `MiniCPM-V-4.5` (`runb-noimage`) | `0 / 0 / 0` | 4/56 (7.14%) (`unc` 0.00%) | 0/18 (0.00%) | 1/18 (5.56%) | **41/56 (73.21%)** (`unc` 0.00%) ⚠️ | 0/56 (0.00%) |
| | **`Qwen3-VL-8B-Instruct`** (`vllm`) | `0 / 0 / 0` | **34/56 (60.71%)** (`unc` 0.00%) | **1/18 (5.56%)** | 1/18 (5.56%) | 32/56 (57.14%) (`unc` 0.00%) | **10/56 (17.86%)** |
| | **`InternVL3-8B`** (`vllm`, 0% 严格格式) | `0 / 0 / 0` | 26/56 (46.43%) (`unc` 0.00%) | **1/18 (5.56%)** | 2/18 (11.11%) | 13/56 (23.21%) (`unc` 50.00%) | 2/56 (3.57%) |
| | **`InternVL3_5-8B`** (`vllm`) | `0 / 0 / 0` | 31/56 (55.36%) (`unc` 3.57%) | 0/18 (0.00%) | 1/18 (5.56%) | 5/56 (8.93%) (`unc` 94.64%) | 0/56 (0.00%) |

> `*` 标注的 `MiniCPM-V-4.5` 两组视觉 Run 属历史初步观测（processor 实际像素上限未核实/未记录）。由于三档对应的源视频集合与真值分布各不相同，跨档数值差异仅作观测记录，不直接等同于画幅分辨率的因果效应。

### 3.2 四款第一梯队基座零样本优劣势观察（按三画幅档与类别召回拆解）

结合 `score.aggregate` 的分档类别召回（recall）诊断，4 款基座在零样本下的共性瓶颈与分化特征非常清晰：

1. **共性瓶颈——普遍存在强「未断裂」先验偏置**：
   - 全部 4 款基座在零样本下对 **`已断裂`** 类别的召回在三个画幅档均为 **`0`**（`w_le_200` `0/9`、`w_200_400` `0/4`、`w_gt_400` `0/4`）；绝大多数模型的 `断裂状态` 准确率主要来自对多数类 `未断裂` 的命中。
2. **`Qwen3-VL-8B-Instruct`（综合最均衡、工程最省心）**：
   - **优势**：严格格式合法率 **100.0%**（210/210 零违约）；无需 `--trust-remote-code`，`--max-model-len 8192` 下直接跑通 8 帧原图；在中/高画幅档的 `断裂状态`（`52.38%` / `60.71%`）与 `五类全对`（`9.52%` / `17.86%`）领先，并在 `断裂现象` 上观察到更高准确率、较少输出 `无法判断`——在 `w_gt_400` 档 5 项 `断裂现象` 均 0% `unc`，`开裂` 96.43%、`界面分离` 100.00%、`断后脱夹` 96.43%（注：`w_gt_400` 档 `界面分离` 100.00% 来自 56 条全阴性样本，`断后脱夹` 96.43% 亦未命中该档唯一阳性样本，需结合类别分布解读）。
   - **短板**：对真实断裂仍偏保守，`发生断裂` 召回为 `w_le_200` `0/42`、`w_200_400` `1/13`、`w_gt_400` `3/14`；`断裂模式` 仅在 `w_gt_400` 命中 1 条非 `unc` 真值（`脆性断裂` 1/5），`断裂位置` 非 `unc` 召回为 0。
3. **`InternVL3-8B`（真实断裂视觉捕捉最积极，但格式围栏硬伤）**：
   - **优势**：**唯一在全部三个画幅档均取得非零 `发生断裂` 召回**（`w_le_200` `4/42`、`w_200_400` `1/13`、`w_gt_400` `5/14`）且在三档均命中非 `unc` `断裂模式`（`脆性断裂` 2/27、`韧性断裂` 1/11、`韧性断裂` 1/12）与 `断裂位置`（`标距内` 3/28、1/12、2/10）的基座；`异常情况` 三项全档准确率领先（87.50%–100.00%）。
   - **短板**：全量 210/210 输出带 ```` ```json ```` Markdown 围栏导致严格格式合法率 **0.0%**（虽可被评分器解析）；且依赖 `--trust-remote-code` 与 `--hf-overrides '{"max_dynamic_patch": 4}'` 才避免 8 帧 token 超限；低画幅 `断裂现象` 较保守（`unc` 72.32%–91.96%）。
4. **`InternVL3_5-8B`（格式修复但零样本过度保守退化）**：
   - **优势**：严格格式合法率由 3.0 的 0% 跃升至 **99.5%**（209/210，仅 `w_200_400` 1 条带围栏）。
   - **短板**：零样本拒答极端保守——三档 `发生断裂` 召回均为 `0`（0/42、0/13、0/14），`断裂模式` 与 `断裂位置` 三档均 **100% 输出 `无法判断`**，`断裂现象` 5 叶项在三档的 `unc` 高达 **83.33%–100.00%**（`w_200_400` 档 `伸长` 52.38% 准确率系几乎全答 `无法判断` 恰好撞中人工 52.38% `unc` 占比），三档 `五类全对` 均为 **0.00%**。
5. **`MiniCPM-V-4.5`（历史初步观测）**：
   - `tf-dev-v1` 在 `w_gt_400` 档 `断裂状态` 58.93%（`发生断裂` 2/14），但 `vllm-dev-v1` 三档 `发生断裂` 召回均为 `0`，且两者 `断裂模式` 非 `unc` 召回均为 `0`；若后续纳入正式跨模型主榜需先补齐 processor 实际逐帧像素上限运行身份。

### 3.3 Run B 无画面文字先验红灯结论（按三画幅档分述）

- **盲答坍缩现象**：在完全剥离图像帧的 Run B（[`20261125-minicpm-v45-runb-noimage-dev-v1/`](20261125-minicpm-v45-runb-noimage-dev-v1/)）中，`MiniCPM-V-4.5` 在三个画幅档（`w_le_200` 112 条、`w_200_400` 42 条、`w_gt_400` 56 条）均恒定输出 `断裂状态 = 已断裂` 与 `断裂现象.伸长 = 是`，对其余 9 个字段均 100% 输出 `无法判断`。
- **两项红灯警示（按档口径；描述性先验对照边界）**：
  > **对照边界说明**：本 Run B 仅作为**描述性纯文本先验对照**，不是“只改变有无画面、其余变量严格一致”的受控配对实验——同属 `vLLM 0.34.0` 后端并不能证明权重快照与解码参数（`run_meta.json` 未落盘）逐项一致，且 `tf-dev-v1` 与 3 款新基座暂无同后端纯文本 Run B。
  1. **「伸长」字段在中/高画幅档出现盲答反超**：
     - **`w_gt_400`**（`n=56`）：Run B 恒定猜 `"是"` 拿到 **41/56 (73.21%)**，仍高于全部 4 款视觉模型（最高的 `Qwen3-VL-8B-Instruct` 为 32/56 = 57.14%，`MiniCPM-V-4.5` `tf-dev-v1` 为 50.00%）；
     - **`w_200_400`**（`n=42`）：Run B 拿到 **10/42 (23.81%)**，与 `Qwen3-VL-8B-Instruct`（23.81%）持平；而 `InternVL3_5-8B` 虽拿到 22/42 (52.38%)，实为 97.62% 输出 `无法判断` 命中人工 `unc` 占比；
     - **`w_le_200`**（`n=112`）：Run B 为 **21/112 (18.75%)**，按档拆看可见盲答与全 `unc` 策略都会随各档真值分布产生表面高分，必须结合 `unc` 率与类别召回解读。
  2. **「断裂模式」在多数基座上正确预测仍主要落在 `无法判断` 真值上**：`MiniCPM-V-4.5` 与 `InternVL3_5-8B` 三档非 `unc` 类别召回均为 `0`；`Qwen3-VL-8B-Instruct` 仅在 `w_gt_400` 命中 1 条 `脆性断裂`（1/5）；仅 `InternVL3-8B` 在三档均出现非 `unc` 命中（按档分别为：`w_le_200` 2 条 `脆性断裂` 2/27、`w_200_400` 1 条 `韧性断裂` 1/11、`w_gt_400` 1 条 `韧性断裂` 1/12）。

### 3.4 下一步微调基座选型参考依据（供用户决策，不作自动晋级）

> 按 [DEC-003](../../decisions/0003-five-label-eval-scope.md) 本轮只报数、不设自动晋级阈值；以下基于 `eval-dev-v1` 首轮 Run A 实测数据整理微调选型建议，最终方向由用户拍板：

1. **首选微调基座：`Qwen3-VL-8B-Instruct`**
   - 依据：零样本格式 100% 严格合法、无 `trust_remote_code` 维护风险、vLLM 原生 8192 上下文直接承载 8 帧原图无需改动态切块参数，且在中/高画幅档的 `断裂状态`、`断裂现象` 与 `五类全对` 综合最均衡；微调核心目标是打破「未断裂」先验偏置，拉升 `发生断裂`/`已断裂` 及 `断裂模式`/`断裂位置` 召回。
2. **并行对照微调基座（若资源允许双基座 SFT）：`InternVL3-8B`**
   - 依据：唯一在零样本三档均捕捉到真实 `发生断裂`、`断裂模式` 与 `断裂位置` 正类信号的 8B 基座，视觉底座对拉伸断裂事件敏感度高；其主要格式短板（Markdown ```` ```json ```` 围栏）可列为 SFT 阶段的待验证修正目标（本轮尚无微调实测证据），同时需保持 `--hf-overrides '{"max_dynamic_patch": 4}'` 与 `--trust-remote-code` 的推理/训练一致口径。
3. **暂不作为首轮微调主选：`InternVL3_5-8B` 与 `MiniCPM-V-4.5`**
   - `InternVL3_5-8B` 在本任务零样本呈现极端保守拒答（`发生断裂` 0 召回、`断裂现象` 三档 `unc` 达 `83.33%–100.00%`），相较同门 `InternVL3-8B` 无视觉优势；`MiniCPM-V-4.5` 架构定制较深且当前视觉 Run 尚未补齐 processor 像素上限运行身份，建议暂置次选。

---

## 4. 各 Run 归档目录与产物直达链接

> **审计与引用边界**：下表原样归档的 `report.md` 与 `results.json` 为评分器原始输出，内含跨档总体标签指标，**仅供审计复算**；正式引用与跨模型比较须一律使用按三画幅档拆分的 [`width-band-breakdown.md`](width-band-breakdown.md)。

| Run ID | 角色与后端 | 可读评分报告（原件，仅供审计） | 结构化评分结果（原件，仅供审计） | 运行元数据与快照身份 |
| --- | --- | --- | --- | --- |
| [`20261125-minicpm-v45-tf-dev-v1`](20261125-minicpm-v45-tf-dev-v1/) | Run A 初步观测（`MiniCPM-V-4.5` / `transformers` DEC-006 方向） | [`report.md`](20261125-minicpm-v45-tf-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-tf-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261125-minicpm-v45-tf-dev-v1/predictions.jsonl.meta.json) |
| [`20261125-minicpm-v45-vllm-dev-v1`](20261125-minicpm-v45-vllm-dev-v1/) | Run A 初步观测（`MiniCPM-V-4.5` / `vLLM HTTP` 对照） | [`report.md`](20261125-minicpm-v45-vllm-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261125-minicpm-v45-vllm-dev-v1/predictions.jsonl.meta.json) |
| [`20261125-minicpm-v45-runb-noimage-dev-v1`](20261125-minicpm-v45-runb-noimage-dev-v1/) | Run B 描述性纯文本先验对照（`MiniCPM-V-4.5` / `vLLM 0.34.0` HTTP） | [`report.md`](20261125-minicpm-v45-runb-noimage-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-runb-noimage-dev-v1/results.json) | [`run_meta.json`](20261125-minicpm-v45-runb-noimage-dev-v1/run_meta.json) |
| [`20261126-qwen3-vl-8b-vllm-dev-v1`](20261126-qwen3-vl-8b-vllm-dev-v1/) | Run A（`Qwen3-VL-8B-Instruct` / `vLLM 0.34.0` HTTP） | [`report.md`](20261126-qwen3-vl-8b-vllm-dev-v1/report.md) | [`results.json`](20261126-qwen3-vl-8b-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-qwen3-vl-8b-vllm-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-qwen3-vl-8b-vllm-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-qwen3-vl-8b-vllm-dev-v1/snapshot_identity.json) |
| [`20261126-internvl3-8b-vllm-dev-v1`](20261126-internvl3-8b-vllm-dev-v1/) | Run A（`InternVL3-8B` / `vLLM 0.34.0` HTTP，`max_dynamic_patch=4` + `use_thumbnail=true`） | [`report.md`](20261126-internvl3-8b-vllm-dev-v1/report.md) | [`results.json`](20261126-internvl3-8b-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-internvl3-8b-vllm-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-internvl3-8b-vllm-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-internvl3-8b-vllm-dev-v1/snapshot_identity.json) |
| [`20261126-internvl3_5-8b-vllm-dev-v1`](20261126-internvl3_5-8b-vllm-dev-v1/) | Run A（`InternVL3_5-8B` / `vLLM 0.34.0` HTTP，`max_dynamic_patch=4` + `use_thumbnail=true`） | [`report.md`](20261126-internvl3_5-8b-vllm-dev-v1/report.md) | [`results.json`](20261126-internvl3_5-8b-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261126-internvl3_5-8b-vllm-dev-v1/predictions.jsonl.meta.json) · [`run_meta.json`](20261126-internvl3_5-8b-vllm-dev-v1/run_meta.json) · [`snapshot_identity.json`](20261126-internvl3_5-8b-vllm-dev-v1/snapshot_identity.json) |

> 注：上述 21 份原始评测产物（前 3 组 9 份 + 2026-11-26 新增 3 组 12 份）均从训练机 `/home/liuyang/文档/TensileAgent-Finetune/evaluations/runs/` 原样同步（零字节修改）；2026-11-26 新增 3 组另附与 `run_id` 绑定的 [`snapshot_identity.json`](20261126-qwen3-vl-8b-vllm-dev-v1/snapshot_identity.json)（各记录训练机实测核对的 `model.safetensors.index.json` / `config.json` / `preprocessor_config.json` / `tokenizer_config.json` SHA-256 摘要、4 份权重分片字节数及生效视觉 processor 参数，满足 `docs/eval/inference-entry.md` §4 与 DEC-006 身份契约）。完整分档必报项与预处理边界另见 [`width-band-breakdown.md`](width-band-breakdown.md)。
