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
| `Qwen3-VL-8B-Instruct` | Run A 主榜 / Run B 对照（权重已就绪 `/data/models/Qwen3-VL-8B-Instruct`） | 待评测（预留） | — | — | 待归档 |
| `InternVL3-8B` | Run A 主榜 / Run B 对照（权重已就绪 `/data/models/InternVL3-8B`，原生非 `-HF`） | 待评测（预留） | — | — | 待归档 |
| `InternVL3_5-8B` | Run A 主榜 / Run B 对照（权重已就绪 `/data/models/InternVL3_5-8B`，标准版不含 ViR） | 待评测（预留） | — | — | 待归档 |

---

## 3. 三画幅档独立对比与 Run B 文字先验红灯结论

### 3.1 三画幅档独立对比表（`eval-dev-v1` 宽度分档：`width_rule_le200_lt400`）

> 按 [`docs/eval/eval-subset.md`](../eval-subset.md) §1、§3、§4 契约要求，在各档样本上使用 `script.five_label_eval.score.aggregate` 独立统计（`eval-dev-v1` 全部为 `source_type = real`，虚拟数据 0 条；L3 落盘 `resize: null`）。下表展示核心字段分档对照；**全部 11 个叶字段**的分档准确率、模型与人工 `无法判断` 比例及各 Run 的 processor 像素上限说明详见 **[三画幅档完整必报项分档报告](width-band-breakdown.md)**。

| 画幅档（来源数 / 片段数 / 断裂真值数） | Run | 请求失败 / 超时 / 未处理 | 断裂状态准确率（模型 `unc`） | 断裂模式 (`frac`) | 断裂位置 (`frac`) | 断裂现象.伸长（模型 `unc`） | 五类全对（补充） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **`w_le_200`** (`w ≤ 200`，48 源 / `n=112` / `frac=51`) | `tf-dev-v1` | `0 / 0 / 0` | 26/112 (23.21%) (`unc` 52.68%) | 8/51 (15.69%) | 3/51 (5.88%) | 22/112 (19.64%) (`unc` 91.96%) | 0/112 (0.00%) |
| | `vllm-dev-v1` | `0 / 0 / 0` | 38/112 (33.93%) (`unc` 15.18%) | 8/51 (15.69%) | 3/51 (5.88%) | 24/112 (21.43%) (`unc` 66.07%) | 1/112 (0.89%) |
| | `runb-noimage` | `0 / 0 / 0` | 9/112 (8.04%) (`unc` 0.00%) | 8/51 (15.69%) | 3/51 (5.88%) | 21/112 (18.75%) (`unc` 0.00%) | 0/112 (0.00%) |
| **`w_200_400`** (`200 < w < 400`，20 源 / `n=42` / `frac=17`) | `tf-dev-v1` | `0 / 0 / 0` | 12/42 (28.57%) (`unc` 11.90%) | 2/17 (11.76%) | 2/17 (11.76%) | 6/42 (14.29%) (`unc` 40.48%) | 0/42 (0.00%) |
| | `vllm-dev-v1` | `0 / 0 / 0` | 14/42 (33.33%) (`unc` 2.38%) | 2/17 (11.76%) | 1/17 (5.88%) | 12/42 (28.57%) (`unc` 57.14%) | 1/42 (2.38%) |
| | `runb-noimage` | `0 / 0 / 0` | 4/42 (9.52%) (`unc` 0.00%) | 2/17 (11.76%) | 1/17 (5.88%) | 10/42 (23.81%) (`unc` 0.00%) ⚠️ | 0/42 (0.00%) |
| **`w_gt_400`** (`w ≥ 400`，19 源 / `n=56` / `frac=18`) | `tf-dev-v1` | `0 / 0 / 0` | **33/56 (58.93%)** (`unc` 1.79%) | 0/18 (0.00%) | 3/18 (16.67%) | 28/56 (50.00%) (`unc` 44.64%) | 5/56 (8.93%) |
| | `vllm-dev-v1` | `0 / 0 / 0` | **30/56 (53.57%)** (`unc` 0.00%) | 0/18 (0.00%) | 1/18 (5.56%) | 25/56 (44.64%) (`unc` 51.79%) | 6/56 (10.71%) |
| | `runb-noimage` | `0 / 0 / 0` | 4/56 (7.14%) (`unc` 0.00%) | 0/18 (0.00%) | 1/18 (5.56%) | **41/56 (73.21%)** (`unc` 0.00%) ⚠️ | 0/56 (0.00%) |

- **分档观察结论**：`tf-dev-v1` 在 `w_gt_400` 档的 `断裂状态` 准确率为 **58.93%**（模型 `unc` 仅 1.79%），在 `w_200_400` 为 **28.57%**（`unc` 11.90%），在 `w_le_200` 档为 **23.21%**（`unc` 升至 52.68%）；`vllm-dev-v1` 同样在 `w_gt_400`（53.57%）高于 `w_200_400`（33.33%）与 `w_le_200`（33.93%）。由于三档对应的源视频集合与真值分布各不相同，此处仅记录观测到的档间差异，画幅分辨率本身的因果影响留待同片段的受控分辨率对照验证。

### 3.2 Run B 无画面文字先验红灯结论（按三画幅档分述）

- **盲答坍缩现象**：在完全剥离图像帧的 Run B（[`20261125-minicpm-v45-runb-noimage-dev-v1/`](20261125-minicpm-v45-runb-noimage-dev-v1/)）中，`MiniCPM-V-4.5` 在三个画幅档（`w_le_200` 112 条、`w_200_400` 42 条、`w_gt_400` 56 条）均恒定输出 `断裂状态 = 已断裂` 与 `断裂现象.伸长 = 是`，对其余 9 个字段均 100% 输出 `无法判断`。
- **两项红灯警示（按档口径；描述性先验对照边界）**：
  > **对照边界说明**：本 Run B 仅作为**描述性纯文本先验对照**，不是“只改变有无画面、其余变量严格一致”的受控配对实验——同属 `vLLM 0.34.0` 后端并不能证明权重快照与解码参数（`run_meta.json` 未落盘）逐项一致，且 `tf-dev-v1` 的 `transformers` 后端暂无同后端纯文本 Run B。
  1. **「伸长」字段在中/高画幅档出现盲答反超**：
     - **`w_gt_400`**（`n=56`）：Run B 恒定猜 `"是"` 拿到 **41/56 (73.21%)**，大幅高于带画面视觉推理的 `tf-dev-v1`（28/56 = 50.00%，`unc` 44.64%）与 `vllm-dev-v1`（25/56 = 44.64%，`unc` 51.79%）；
     - **`w_200_400`**（`n=42`）：Run B 拿到 **10/42 (23.81%)**，高于 `tf-dev-v1`（6/42 = 14.29%，`unc` 40.48%），低于 `vllm-dev-v1`（12/42 = 28.57%，`unc` 57.14%）；
     - **`w_le_200`**（`n=112`）：Run B 为 **21/112 (18.75%)**，低于两个视觉 Run（`tf-dev-v1` 22/112 = 19.64%，`vllm-dev-v1` 24/112 = 21.43%）。按档拆看可见盲答反超高度依赖各档真值 `"是"` 的先验占比，若跨档合并则会掩盖 `w_le_200` 与 `w_gt_400` 方向相反的结论。
  2. **「断裂模式」各档正确预测全部落在 `无法判断` 真值上**：三组 Run 在三档的准确率分别为 `w_le_200` **8/51 (15.69%)**、`w_200_400` **2/17 (11.76%)**、`w_gt_400` **0/18 (0.00%)**；所有正确预测均来自模型输出 `无法判断` 并命中真值中的 `无法判断`（`vllm-dev-v1` 与 `runb-noimage` 三档均 100% 输出 `无法判断`，`tf-dev-v1` 在 `w_le_200` 112/112、`w_200_400` 41/42、`w_gt_400` 56/56 输出 `无法判断`，仅在 `w_200_400` 有 1 条预测 `脆性断裂`；三组在三档对 `脆性断裂` / `韧性断裂` / `半脆半韧断裂` 的召回全为 `0`）。
- **后续解读纪律**：评测 `Qwen3-VL-8B-Instruct`、`InternVL3-8B`、`InternVL3_5-8B` 时，必须按三画幅档同步对照 Run B 与模型 `无法判断` 率，禁止跨档合并单一指标或仅凭单字段准确率判断视觉增益。

---

## 4. 各 Run 归档目录与产物直达链接

> **审计与引用边界**：下表原样归档的 `report.md` 与 `results.json` 为评分器原始输出，内含跨档总体标签指标，**仅供审计复算**；正式引用与跨模型比较须一律使用按三画幅档拆分的 [`width-band-breakdown.md`](width-band-breakdown.md)。

| Run ID | 角色与后端 | 可读评分报告（原件，仅供审计） | 结构化评分结果（原件，仅供审计） | 运行元数据 |
| --- | --- | --- | --- | --- |
| [`20261125-minicpm-v45-tf-dev-v1`](20261125-minicpm-v45-tf-dev-v1/) | Run A 初步观测（`transformers` DEC-006 方向） | [`report.md`](20261125-minicpm-v45-tf-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-tf-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261125-minicpm-v45-tf-dev-v1/predictions.jsonl.meta.json) |
| [`20261125-minicpm-v45-vllm-dev-v1`](20261125-minicpm-v45-vllm-dev-v1/) | Run A 初步观测（`vLLM HTTP` 对照） | [`report.md`](20261125-minicpm-v45-vllm-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-vllm-dev-v1/results.json) | [`predictions.jsonl.meta.json`](20261125-minicpm-v45-vllm-dev-v1/predictions.jsonl.meta.json) |
| [`20261125-minicpm-v45-runb-noimage-dev-v1`](20261125-minicpm-v45-runb-noimage-dev-v1/) | Run B 描述性纯文本先验对照（`vLLM 0.34.0` HTTP） | [`report.md`](20261125-minicpm-v45-runb-noimage-dev-v1/report.md) | [`results.json`](20261125-minicpm-v45-runb-noimage-dev-v1/results.json) | [`run_meta.json`](20261125-minicpm-v45-runb-noimage-dev-v1/run_meta.json) |

> 注：上述 9 份归档文件均从训练机 `/home/liuyang/文档/TensileAgent-Finetune/evaluations/runs/` 原样同步（零字节修改）。Run A 两组的元数据文件保留推理入口 `script/five_label_eval/infer.py` 的原生命名 `predictions.jsonl.meta.json`，Run B 保留原生命名 `run_meta.json`（经核对训练机同目录 `vllm.log`，Run B 由 `vLLM 0.34.0` HTTP 服务以 `bfloat16` / `max_model_len=8192` 产出，对应 `vllm-dev-v1` 后端，其解码参数未写入 `run_meta.json`；`tf-dev-v1` 暂无独立 `transformers` 后端 Run B）。完整分档必报项与预处理边界另见 [`width-band-breakdown.md`](width-band-breakdown.md)。
