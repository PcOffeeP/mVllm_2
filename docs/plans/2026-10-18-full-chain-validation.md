<!-- DOCUMENT-CONTRACT
Purpose: 规定 R2 开训前必须完成的全链路质疑验证方案，把「若干条准备工作」升级为覆盖 C1–C14 的可复核闸门。
Scope: C1–C14 十四个环节各自的质疑点、验证方法、通过判据、产出证据、依赖与负责人；开训闸门检查表；失效传播矩阵；10 条已知问题台账；执行批次建议与需用户裁决的事项。
Must Preserve:
- 14 个环节任一项未 passed 即不得开训。Agent 不得自行放宽，不得用「基本没问题」「大致通过」代替 passed。
- 「已断裂」与「发生断裂」按时间位置区分，该区分已在冻结契约的 search_semantics 与 analysis.user_prompt 中定义。本轮质疑的是标签与画面是否一致，不改变这两条定义。
- 本文件只出方案。不改代码、不改数据、不改台账、不提交其它文件。
- 任何数字必须绑定 code_commit + data_release + prompt_version 三项，缺一不得作为引用依据。
Non-goals:
- 不实施任何修复，不裁决阈值取值，不代替用户对 waiver 的书面裁决。
-->

# 全链路质疑验证方案（R2 开训闸门）

> 状态：设计稿，2026-10-18 起草于分支 `feat/evaluation-development`。本轮只出方案，不改代码、不改数据、不改台账。14 个环节的执行、证据落地与人工判读属后续批次。

> 事实边界：本文档中的数字有三类来源。（1）仓库内可复核的代码与文档，标【实测】并给出 `文件:行`，行号一律为近似值，以 `grep -n` 实测为准。（2）仓库内实测记录，标【实测】并给出记录文件位置。（3）用户目视观察与据此的推理，标【推断】。凡未核实的条目标【待验证】，凡需复算的数字标【待复算】。本机未复现训练机 GPU 结果，也未在本机加载权重跑推理，涉及模型输出的结论全部来自训练机已产出的记录。

## 1. 核心原则

1. 默认每个环节都是错的，直到有证据证明它对。
2. 验证必须产出可复核的证据文件：命令输出、脚本结果、样本清单。不接受「看过了觉得没问题」。
3. 任一环节未通过，不得开训。
4. 失效传播：某环节的上游变更后，该环节及其下游的验证结论自动失效，必须重验。
5. 口径三元组：任何数字必须绑定 `code_commit` + `data_release` + `prompt_version`，缺一不可引用。

## 2. 标注约定与证据落地规则

标记含义固定为四种。【实测】表示命令或文件可当场复核。【推断】表示来自用户目视或逻辑推理，尚无量化证据。【待验证】表示本轮未做、需补做的条目。【待复算】表示文中数字来自既有记录，本轮必须按脚本重算后才能引用。

证据分两类存放。

- 文本类证据（JSON、CSV、MD、pytest 输出原文）落 `records/full-chain-validation-20261018/<环节编号>/`。该目录入 Git。依据：`.gitignore` 未忽略 `records/`【实测】。
- 媒体类证据（抽帧图、拼图、短视频）落 `~/pi-workspace/mVllm_2-audit/full-chain-validation-20261018/<环节编号>/`。该目录不入 Git。依据：`.gitignore` 含 `*.mp4`、`*.mov` 全局规则，且媒体文件体积大【实测】。

文中出现的审计脚本在「产出证据」中标明「待新建」。脚本放 `scripts/`，命名按仓库规范 `<阶段前缀>_<动作>_<对象>.py`，前缀按被审环节最近的主流程取 `release_`、`train_` 或 `eval_`，并同步 `scripts/SCRIPTS.md`。本轮提交不含这些脚本。

## 3. 逐环节验证方案

### C1 源数据接入

质疑点

1. 抽 30 条样本（按类分层：已断裂、未断裂、发生断裂各 10 条），逐帧问「这一帧的主体是不是拉伸试样？ROI 是否落在试样上且只覆盖试样？」已知反例：某样本把「锡纸擦不锈钢」镜头当成试样画面，出处为仓库外 `~/pi-workspace/mVllm_2-audit/frame-awareness-report-20261018.md` 的 P3 段落，该文件不在 Git 内【推断】。
2. 对 release 内每条视频，`ffprobe` 实测的 `fps`、`nb_frames`、`duration` 与 metadata 记录值是否一致？判据用偏差与差值，不用「大致一致」。
3. 视频文件清单、ROI 记录、metadata 三者按 `video_id` 做三向差集，是否存在只有 metadata 没有视频、或只有 ROI 没有视频的条目？
4. ROI 矩形是否全部落在视频像素界内（`0 ≤ x1 < x2 ≤ width`、`0 ≤ y1 < y2 ≤ height`），是否存在零面积 ROI？
5. 同一 `video_id` 是否出现多条 metadata（重复登记）？

验证方法

- 三向差集与重复检查：脚本读 `<STORE>/data/releases/<版本>/release.yaml` 与其指向的 metadata，按 `video_id` 建集合，输出差集与重复项。目录口径见 `docs/data-workflow.md` 的 `STORE/data/releases/VERSION/` 一行（近似 `:21`）。
- 全量 `ffprobe` 探测，逐条记录 `r_frame_rate`、`nb_frames`、`duration`，与 metadata 的 `fps`、`total_frames`、`duration` 比对。
- 帧抽样目视：脚本按等间隔抽 5 帧/条，拼成 contact sheet，人工逐条判读「主体是否试样、ROI 是否贴合」。
- ROI 界内检查：脚本读 ROI 记录与视频分辨率，做数值断言。

通过判据

- 三向差集条目数 = 0（性质型）。
- 同一 `video_id` 重复 metadata 条数 = 0（性质型）。
- 界外 ROI 数 = 0 且零面积 ROI 数 = 0（性质型）。
- `fps` 相对偏差 ≤ 1%，`total_frames` 绝对差值 ≤ 1 帧，`duration` 绝对偏差 ≤ 0.1 s。阈值来源：三项均无文档出处，**阈值待用户裁决**。
- 目视判读中「主体不是试样」的样本占比 ≤ 5%。阈值来源：无出处，**阈值待用户裁决**。

产出证据

- 路径：`records/full-chain-validation-20261018/c1/` 下 `media_probe.csv`、`id_diff.json`、`roi_bounds.json`。
- 路径：`~/pi-workspace/mVllm_2-audit/full-chain-validation-20261018/c1/` 下 `frame_samples/<video_id>.png`、`visual_review.md`（含判读人、判读时间、逐条结论）。
- 命令：

```console
$ .venv/bin/python scripts/release_audit_source_media.py --release <版本> --out records/full-chain-validation-20261018/c1/media_probe.csv
$ ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate,nb_frames,duration -of json <视频路径>
$ .venv/bin/python -m pytest tests/test_metadata_artifacts.py tests/test_roi_manifest.py -q
```

- 格式：CSV（全量探测）、JSON（差集与断言）、PNG（抽帧图，不入 Git）、MD（目视判读表）。

依赖

- 上游：无，本环节为首环。
- 外部条件：release 视频与 metadata 可读（本机副本或训练机）；人工目视判读；独立 reviewer 抽查至少 10% 的判读结论。

负责人

- 主 Agent 派单执行脚本。
- 人工目视判读。
- 独立 reviewer 抽查。
- 用户裁决两项无出处阈值。

### C2 事件时刻标注 `event_time`

质疑点

1. 抽样标为「已断裂」的样本 30 条，问「`event_time` 落在窗口可见分离首帧之前多少秒？」已知 `video_0110` 上 `event_time` 与人眼判读差约 3.5 s【推断】，需量化到分布。
2. 该时刻画面是否已可见分离？若 `event_time` 早于可见分离超过 0.5 s，该条的「已断裂」标签在视觉上是否还成立？
3. 偏差方向是否系统性偏早？同号偏差的样本占比是多少？
4. `event_time_reliable` 为 `true` 的样本里，偏差超过 0.5 s 的占比是多少？
5. 偏差是否与窗口时长相关（长窗口偏差更大）？

验证方法

- 抽 30 条，逐条导出 event 前后各 3 s、步长 0.2 s 的帧序列，人工标注「可见分离首帧」时刻 `t_vis`。
- 计算 `Δ = event_time − t_vis`，输出中位数、P10、P90、0.1 s 分箱直方图，与逐条清单。
- 按 `event_time_reliable` 分组统计偏差。
- 对 Δ 与窗口时长做散点，观察相关性，只作观察不作判据。

通过判据

- `|中位数 Δ| ≤ 0.5 s`。阈值来源：`EVENT_GUARD_SECONDS = 0.5`，`pipeline/v3_candidate_plan.py:36`【实测】。
- 偏差超过 0.5 s 的样本占比 ≤ 10%。阈值来源：无出处，**阈值待用户裁决**。
- 逐条清单覆盖全部 30 条，缺项数 = 0（性质型）。
- 偏差方向一致性只作观察项，不作 pass/fail。

产出证据

- 路径：`records/full-chain-validation-20261018/c2/` 下 `event_time_bias.csv`（逐条 `video_id`、`event_time`、`t_vis`、`Δ`、判读人）、`histogram.md`、`summary.json`。
- 路径：`~/pi-workspace/mVllm_2-audit/full-chain-validation-20261018/c2/` 下逐条帧序列图，不入 Git。
- 命令：

```console
$ ffmpeg -ss <t-3> -i <视频路径> -t 6 -vf fps=5 ~/pi-workspace/mVllm_2-audit/full-chain-validation-20261018/c2/<video_id>/%03d.png
$ .venv/bin/python scripts/eval_audit_event_time_bias.py --labels records/full-chain-validation-20261018/c2/event_time_bias.csv --out records/full-chain-validation-20261018/c2/summary.json
```

- 格式：CSV（逐条）、JSON（分布摘要）、MD（直方图与解读）、PNG（不入 Git）。

依赖

- 上游：C1（确认视频与 ROI 可用）。
- 外部条件：人工目视判读 30 条；帧抽取可读原始视频；用户裁决 10% 阈值。

负责人

- 主 Agent 派单执行脚本。
- 人工目视判读。
- 用户裁决抽样量与占比阈值。

### C3 候选窗口生成

质疑点

1. 给定窗口 `[start, end]` 与 `event`，几何上是否满足：未断裂 `end ≤ event − 0.5`、已断裂 `start ≥ event + 0.5`、发生断裂 `start < event < end`？
2. 是否存在标为「已断裂」但 `start < event + 0.5` 的窗口（窗口压在事件之前或跨事件）？反例条数是多少？
3. `pre` 止于 `event − 0.5`、`post` 起于 `event + 0.5` 的实现是否与文档一致？实现见 `pre_end = max(0.0, event - EVENT_GUARD_SECONDS)` 与 `post_start = min(duration, event + EVENT_GUARD_SECONDS)`（`pipeline/v3_candidate_plan.py` 近似 `:627`、`:659`，以 `grep -n` 实测为准）【实测】。
4. `transition` 窗口是否真的跨 event（`start < event < end`），还是可能退化到 event 一侧？
5. 当 `event < 0.5 s` 或 `event > duration − 0.5 s` 时，`pre` 与 `post` 是否产生零长或负长窗口？
6. 窗口起点是否与帧对齐（`_interval_from_frames`，`pipeline/v3_candidate_plan.py` 近似 `:413`），帧对齐后的实际区间是否仍然满足上述不等式？

验证方法

- 读候选计划 JSONL，对每条窗口跑几何断言，逐条记录通过与否。
- 统计四类窗口计数（`pre`、`post`、`transition`、`normal_negative`），与 `TARGET_DURATIONS = (2.0, 3.0, 5.0, 10.0, 20.0)`（`pipeline/v3_candidate_plan.py:34`）交叉核对实际时长。
- 对断言失败条目导出窗口、event、帧号三联数据，供 C4 复用。

通过判据

- 几何断言违反数 = 0（性质型）。
- 零长或负长窗口数 = 0（性质型）。
- 「已断裂」标签与几何条件的冲突数 = 0（性质型）。
- 断言总数与候选计划条目数相等（性质型，用于证明断言没有漏跑）。

产出证据

- 路径：`records/full-chain-validation-20261018/c3/` 下 `geometry_assert.json`（断言总数、违反清单）、`window_counts.csv`、`edge_cases.md`。
- 命令：

```console
$ .venv/bin/python scripts/eval_audit_label_geometry.py --plan <候选计划 JSONL> --out records/full-chain-validation-20261018/c3/geometry_assert.json
$ .venv/bin/python -m pytest tests/test_v3_labels.py tests/test_subvideo_build_plan.py -q
```

- 格式：JSON（断言结果）、CSV（计数）、MD（边界情形说明）。

依赖

- 上游：C2（`event_time` 的准确度决定几何断言的实际含义）。
- 外部条件：候选计划产物可读。

负责人

- 主 Agent 派单执行脚本。

### C4 标签赋值 `_state_for_interval`

质疑点

1. 标签是否必然等于视觉可判状态？已知结论：不必然。`_state_for_interval`（`pipeline/v3_candidate_plan.py:301`【实测】）只按 `start`、`end`、`event_time` 与 0.5 s guard 计算，不读画面。
2. 四类误标各有多少条：该断未断（`end ≤ event − 0.5` 但画面已分离）、不应断却标已断（`start ≥ event + 0.5` 但画面未分离）、首帧即断被标成「发生断裂」（`start < event < end` 但首帧已可见分离）、边界样本落「无法判断」（`event − 0.5 < end` 且 `start < event + 0.5`，但不满足 `start < event < end`）？四类的分支依据见 `_state_for_interval` 的判定顺序（近似 `:312`–`:319`）【实测】。
3. 按 C2 的 Δ 分布做最坏情况推演：当 `event_time` 偏差 0.5 s 时，多少条样本会跨进另一类？
4. 是否存在「画面未分离却进已断裂类」的样本被喂进训练集（正例污染）？条数是多少？
5. `event_time_reliable is not True` 的样本是否一律落「无法判断」，是否有本该可判的样本被这条前置条件挡掉？

验证方法

- 以 C2 的人工判读结果作参考真值，与几何标签做混淆矩阵（4 类 × 4 类）。
- 对 C2 的 Δ 分布做区间推演，产出「偏差 0.5 s 时的最大误标条数」。
- 抽 5% 样本做二次人工复核，两次判读不一致的条目单列。

通过判据

- 几何标签与视觉标签一致率 ≥ 90%。阈值来源：无出处，**阈值待用户裁决**。
- 正例污染条数 = 0（性质型，「画面未分离却标已断裂」按定义不可接受）。
- 四类误标清单逐条可枚举，缺项数 = 0（性质型）。
- 二次人工复核的不一致率 ≤ 10%。阈值来源：无出处，**阈值待用户裁决**。

产出证据

- 路径：`records/full-chain-validation-20261018/c4/` 下 `confusion_geometry_vs_visual.csv`、`mislabel_cases.csv`、`worst_case.md`。
- 命令：

```console
$ .venv/bin/python scripts/eval_audit_label_consistency.py --labels <候选计划 JSONL> --visual records/full-chain-validation-20261018/c2/event_time_bias.csv --out records/full-chain-validation-20261018/c4/confusion_geometry_vs_visual.csv
$ .venv/bin/python -m pytest tests/test_v3_labels.py tests/test_v4_1_labels.py -q
```

- 格式：CSV（混淆矩阵与逐条误标）、MD（最坏情况推演）。

依赖

- 上游：C1、C2、C3。
- 外部条件：人工复核 5% 样本；用户裁决一致率阈值。

负责人

- 主 Agent 派单执行脚本。
- 人工目视复核。
- 用户裁决一致率与不一致率阈值。

### C5 数据集构建

质疑点

1. `finetune/train_build_dataset.py` 是否用注册 Prompt 覆盖内嵌 system/user？`system_prompt=prompt["system_prompt"]` 与 `user_prompt=prompt["user_prompt"]`（近似 `:412`、`:422`【实测】）说明主路径走注册源，但近似 `:124`、`:234` 处另有内嵌模板。这两处是否仍可达？
2. 生成 dataset 的字段集合、示例 JSON 字段名、类别取值集合，是否与 `pipeline/prompt_library.yaml` 逐字一致？差集是什么？
3. assistant 标签格式是否与冻结契约一致？是否引入过期字段？
4. 过期字段 `fracture_between` 是否仍出现在数据集的目标里？`pipeline/prompt_library.yaml:9` 仍在要求该字段【实测】，且 `finetune/validation/constants.py:43` 的 `CORE_FIELDS` 仍含它【实测】。
5. `prompt_revision_id`（近似 `:436`、`:462`【实测】）是否与实际使用的模板文本哈希一一对应？是否存在同一 revision 下模板不同？

验证方法

- 字段集合比对：脚本读 dataset JSON 的 `system`、`user`、assistant 目标字段集合，与 `pipeline/prompt_library.yaml` 的 `system_prompt`、`user_prompt`、`target_format`、`target_schema` 做差集。
- 模板逐字比对：渲染后的 Prompt 文本与 yaml 文本做哈希比对。
- 取值集合比对：assistant 的 `type` 取值集合与 `target_schema.type` 的合法取值列表比对。
- 全量扫描 dataset 中过期字段出现次数。

通过判据

- 字段集合双向差集为空（性质型）。
- 模板文本哈希一致（性质型）。
- 过期字段 `fracture_between` 出现次数 = 0。当前 yaml 与 `CORE_FIELDS` 仍保留该字段，本项在清理前自动判 failed【实测】。
- `prompt_revision_id` 与模板哈希映射为单射（性质型）。

产出证据

- 路径：`records/full-chain-validation-20261018/c5/` 下 `prompt_field_diff.json`、`template_hash.txt`、`type_value_set.csv`。
- 命令：

```console
$ .venv/bin/python scripts/train_audit_prompt_alignment.py --dataset <dataset 目录> --prompt pipeline/prompt_library.yaml --out records/full-chain-validation-20261018/c5/prompt_field_diff.json
$ .venv/bin/python -m pytest tests/test_train_build_dataset.py tests/test_v3_contract_artifact.py -q
```

- 格式：JSON（差集）、TXT（哈希）、CSV（取值集合）。

依赖

- 上游：无（模板与字段可比对）。数据集目录需可读，只读访问即可。
- 外部条件：独立 reviewer 复核 yaml 与 dataset 的逐字结论。

负责人

- 主 Agent 派单执行脚本。
- 独立 reviewer 复核。

### C6 采样与分母

质疑点

1. 三折 1253/1014/1186、val 425/664/492、每折 train∪val=1678、交集 0、dup 0 是否可复算？【待复算】这些是待复算的主张，本轮不得当作既定事实引用。
2. 分层采样与重复倍率 3.0（顶 `SIGNATURE_COUNT_CAP = 3`，`finetune/train_build_source_aware_dataset.py:30`【实测】）是否扭曲类别分布？训练池「已断裂」占 1253 条中 188 条、15.00%（DF-010，`docs/design-facts.md:94`【实测】），采样后的占比差多少个百分点？
3. `HARD_NEGATIVES_PER_EPOCH = 900`、`ROWS_PER_EPOCH = 3000`（近似 `:24`、`:25`【实测】）是否把「已断裂」正例挤出每 epoch 的行数？
4. fold 之间 val 是否存在 `video_id` 泄漏（同一源视频的子窗口跨 fold）？
5. 三折的 support 不等时，聚合口径按简单合并还是加权？口径是否在报告中写明？

验证方法

- 按 fold 复算计数：脚本读采样输出 JSONL，用 `Counter` 按 fold 与 `clip_state` 聚合，输出每折 train/val 计数与交集。
- 泄漏检查：按源视频标识做 fold 间交集。
- 类别分布对比：训练池占比与采样后占比并列，标注两个口径（DF-010 记的是训练池候选，采样后是每 epoch 行）。

通过判据

- 复算计数与声称值完全一致（性质型）。不一致时声称值作废，按复算值为准，并在报告里写明偏差。
- fold 间源视频交集 = 0（性质型）。
- 每折 train 与 val 交集 = 0，折内重复条数 = 0（性质型）。
- 采样后「已断裂」占比与 15.00% 的差值 ≤ 3 个百分点。阈值来源：无出处，**阈值待用户裁决**。

产出证据

- 路径：`records/full-chain-validation-20261018/c6/` 下 `fold_counts.json`、`class_balance.csv`、`leak_check.txt`。
- 命令：

```console
$ .venv/bin/python scripts/train_audit_fold_counts.py --data <采样输出目录> --out records/full-chain-validation-20261018/c6/fold_counts.json
$ .venv/bin/python scripts/train_audit_fold_leakage.py --data <采样输出目录> --out records/full-chain-validation-20261018/c6/leak_check.txt
$ .venv/bin/python -m pytest tests/test_train_build_source_aware_dataset.py tests/test_fold_execution.py -q
```

- 格式：JSON（计数）、CSV（分布对比）、TXT（泄漏检查原文）。

依赖

- 上游：C4（标签质量决定类别分布的意义）、C5（数据集字段）。
- 外部条件：训练机数据目录可读。

负责人

- 主 Agent 派单执行脚本。
- 用户裁决分布差值阈值。

### C7 训练配置

质疑点

1. 关键参数是否与预期或契约一致？已核实 `finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/train_seed3407.yaml` 的实际值【实测】：`lora_rank: 8`、`lora_alpha: 16`、`lora_dropout: 0.25`、`learning_rate: 0.000005`、`num_train_epochs: 3`、`quantization_bit: 4`、`video_maxlen: 8`、`cutoff_len: 2048`、`additional_target: resampler`、`freeze_vision_tower: false`。
2. 这些值里哪些写进了契约文档、哪些只存在于 yaml？逐参数建两列表：「有出处」「无人认领」。
3. `cutoff_len: 2048` 与 512 视觉 token（每帧 64 token × 8 帧，`models/minicpm-v-4.5/preprocessor_config.json:12` 的 `image_feature_size: 64`【实测】、`finetune/validation/constants.py:36` 的 `VIDEO_MAX_FRAMES = 8`【实测】）加上 Prompt 与输出是否够用？是否发生截断？截断条数是多少？
4. `learning_rate: 0.000005` 与 `lora_dropout: 0.25` 的依据在哪份文档或实验？无出处即列入「无人认领」。
5. 三折配置是否只有 seed 与 fold 指向不同，其余参数逐字一致？差异项逐条列出。
6. `additional_target: resampler` 与 `freeze_vision_tower: false` 是否与量化训练的可训练参数清单一致？可训练参数量是多少？

验证方法

- 参数溯源：对每个参数名做全仓文档检索（`docs/`、`ARCHITECTURE.md`、契约文件），输出命中位置与未命中清单。
- 截断实测：用 processor 对 200 条样本做 tokenize 计数，报最大长度、超 2048 的条数、被截断的样本 `video_id`。
- 三折配置 diff。
- 可训练参数量：从训练日志或配置解析，输出数量级。

通过判据

- 「无人认领」参数清单完整枚举，缺项数 = 0（性质型）。本项不设数值阈值，清单本身即为结论。
- 截断条数 = 0（性质型）。
- 三折配置除 seed 与 fold 指向外差异数 = 0（性质型）。
- 最大序列长度 ≤ 2048（性质型，与上一条同源数据）。

产出证据

- 路径：`records/full-chain-validation-20261018/c7/` 下 `param_provenance.csv`、`token_lengths.csv`、`fold_config_diff.txt`。
- 命令：

```console
$ .venv/bin/python scripts/train_audit_config_provenance.py --config finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first --out records/full-chain-validation-20261018/c7/param_provenance.csv
$ .venv/bin/python scripts/train_audit_token_lengths.py --config <yaml> --samples 200 --out records/full-chain-validation-20261018/c7/token_lengths.csv
```

- 格式：CSV（溯源与长度）、TXT（配置 diff）。

依赖

- 上游：C5（Prompt 文本影响 token 长度）、C6（数据分布不影响 token 长度，但影响样本构成）。
- 外部条件：训练机（tokenize 需 processor 与数据）。

负责人

- 主 Agent 派单。
- 训练机 SSH 执行。
- 用户裁决「无人认领」参数是否可接受。

### C8 推理管线

质疑点

1. 评测侧 `temporal_ids` 全为 `-1`【实测】：`finetune/validation/video_loader.py` 的 `temporal_ids = [[0] * n] if temporal_fusion else None`（近似 `:113`），而 `TEMPORAL_FUSION_LEGACY = False`（`finetune/validation/constants.py:52`）。模型在没有帧序号、没有时间戳、无跨帧时序位置的前提下，是否具备判断「事件在片段前、片段内、片段后」的信息论必要条件？
2. `max_slice_nums=2` 与 `use_image_id=False`（`finetune/validation/model_runtime.py` 近似 `:151`–`:153`；`VIDEO_SLICE_MAX_NUMS = 2` 见 `finetune/validation/constants.py:48`【实测】）是否让 8 帧共享同一套 2D 位置编码，帧序无法区分？机制：`models/minicpm-v-4.5/resampler.py` 近似 `:188`–`:190` 只在 `max_temporal_size > -1` 时启用 temporal embedding，近似 `:286`–`:292` 只在 `pos_embed_temporal` 为真时把时序位置并入 key【实测】。
3. 帧采样是否可能跳过事件帧？8 帧对最短窗口（`TARGET_DURATIONS` 最小 2.0 s，`pipeline/v3_candidate_plan.py:34`【实测】）的帧间隔是多少秒？事件落在两帧之间的最大间隙是多少？
4. 视觉 token 数是否与 512 一致（每帧 64 × 8 帧）？在 `max_slice_nums=2` 下每帧是否仍为 64？
5. 若把 `temporal_ids` 从全 `-1` 改为帧序号，同一批输入的输出分布是否改变？（反事实 smoke，只做小样本，不改产线代码）

验证方法

- 只读 dump 传入 processor 的 `inputs`：对 20 条样本记录 `temporal_ids`、`image_bound`、`tgt_sizes` 的形状与取值摘要，不加载权重。
- 帧采样位置与 event 的相对关系逐条计算，输出事件到最近采样帧的间隔。
- 视觉 token 计数：从 processor 输出解析每帧 token 数。
- 反事实 smoke：改 `temporal_ids` 后跑 5 条，只记录输出差异，结论标注为探索性观察。

通过判据

- 复现「`temporal_ids` 非 `-1` 元素数 = 0」（性质型，与既有实测对齐）。
- 视觉 token 数 = 512，可复算（性质型）。
- 事件到最近采样帧的间隔分布给出（观察项，不设 pass/fail）。
- 反事实 smoke 只作观察，不作判据。

产出证据

- 路径：`records/full-chain-validation-20261018/c8/` 下 `processor_inputs.json`、`frame_sampling.csv`、`counterfactual_smoke.md`。
- 命令：

```console
$ .venv/bin/python scripts/eval_audit_processor_inputs.py --samples 20 --out records/full-chain-validation-20261018/c8/processor_inputs.json
$ .venv/bin/python -m pytest tests/test_frame_contract.py tests/test_dev_eval_preprocess_alignment.py -q
```

- 格式：JSON（张量摘要，不含权重）、CSV（帧采样）、MD（反事实观察）。

依赖

- 上游：C2（event 位置用于计算采样间隔）。
- 外部条件：训练机（processor 与数据）。

负责人

- 训练机 SSH 执行。
- 主 Agent 派单。

### C9 输出解析与形式校验

质疑点

1. 给一段合法但语义错误的输出（例如 `has_fracture: true` 而区间与类型矛盾），`strict_valid` 是否为 True？`strict_valid` 只校验形式【实测】，本条用于把该事实固化为可回归用例。
2. 给一个已被 v2 契约删除的字段 `fracture_between`，解析器是否静默接受？该字段仍在 `pipeline/prompt_library.yaml:9` 与 `finetune/validation/constants.py:43` 的 `CORE_FIELDS` 中【实测】。
3. 解析容错层级是否允许剥 markdown 代码块、截取首个 JSON 对象这类修补？这类修补是否掩盖了格式退化？相关测试见 `tests/test_output_normalizer.py`。
4. 缺字段、额外字段、类型错误、枚举越界四类畸形输入，各自判定结果是什么？是否都判不合法？
5. `task_metrics.py` 的 `interval_available` 与 `time_available` 分支（近似 `:25`–`:60`）在修复后是否不再把 `None == None` 判成对？修复前的白送判对发生在该文件近似 `:51` 一带，现分支见 `if interval_available:` 与 `elif time_available:`【实测】，需回归验证。

验证方法

- 构造畸形输入矩阵：4 类 × 每类 5 例，跑解析与形式校验，输出判定矩阵。
- 语义错误但形式合法用例 5 例，记录 `strict_valid` 结果。
- 过期字段接受性测试：单独喂含 `fracture_between` 的输出。
- 回归：`task_metrics.py` 的 `None == None` 用例，跑 `tests/test_holdout_metrics.py` 与 `tests/test_eval_holdout.py`。

通过判据

- 契约字段集合、数据集字段集合、解析器必填字段集合三向相等（性质型）。当前 `fracture_between` 残留导致本项判 failed，直到三处对齐【实测】。
- 四类畸形输入全部判不合法，通过率 = 0（性质型）。
- `None == None` 不再判对，回归用例通过（性质型）。
- 语义错误但形式合法时 `strict_valid` = True 属预期行为，只登记不作缺陷。

产出证据

- 路径：`records/full-chain-validation-20261018/c9/` 下 `parse_matrix.csv`、`strict_valid_cases.md`、`pytest_output.txt`。
- 命令：

```console
$ .venv/bin/python scripts/eval_audit_output_parser.py --out records/full-chain-validation-20261018/c9/parse_matrix.csv
$ .venv/bin/python -m pytest tests/test_output_normalizer.py tests/test_holdout_metrics.py tests/test_eval_holdout.py -q | tee records/full-chain-validation-20261018/c9/pytest_output.txt
```

- 格式：CSV（判定矩阵）、MD（用例说明）、TXT（pytest 原文）。

依赖

- 上游：C5（字段集合口径）、C8（输出内容由管线决定）。
- 外部条件：独立 reviewer 复核用例覆盖度。

负责人

- 主 Agent 派单执行脚本。
- 独立 reviewer 复核。

### C10 判分实现

质疑点

1. 每个指标的实现是否与定义一致？定义见 `finetune/holdout_metrics.py` 的 `METRIC_DEFINITIONS`（近似 `:23`–`:31`），实现在 `restricted_metrics`（近似 `:42`）、`public_gates`（近似 `:66`）、`gate_outcome`（近似 `:87`）【实测】。逐指标必须列「定义 / 实现位置 / 反打用例」。
2. 给定已知混淆矩阵，门禁是否按预期判 pass/fail？是否用合成数据反打验证过？
3. 冻结阈值是否如实现所写：`four_state_macro_recall 0.4006`、`fracture_three_state_macro_recall 0.3`、`joint_correct_rate 0.3921`、`runtime_failure_count 0`、`strict_valid_rate 1.0`、`已断裂_recall 0.15`、`未断裂_recall 0.7`（`finetune/holdout_metrics.py` 近似 `:12`–`:21`【实测】）？
4. 比较方向是否正确：`public_gates` 对计数类用 `==`，对比率类用 `>=`（近似 `:66`–`:85`【实测】）？方向错会不会把「越低越好」的指标判反？
5. `validate_thresholds` 要求阈值与冻结常量逐字相等（近似 `:33`–`:39`【实测】），那么改常量即同时放宽门禁。这种改动能否被发现？

验证方法

- 合成数据反打：至少 5 组用例。完美预测组、全塌缩组（全判同一类）、正类零预测组（33 条正样本 0 次预测）、runtime 失败 1 条组、阈值边界组（恰等于阈值）。
- 逐指标表：指标名 → 定义原文 → 实现函数与行号 → 反打用例编号 → 期望值 → 实测值。
- 边界与比较方向：对每个指标构造恰等于阈值、差 1e-6 两组。

通过判据

- 反打用例实测值与期望值不一致数 = 0（性质型）。
- 每个指标至少 1 个反打用例，且覆盖集合包含「全塌缩」与「完美」两类（性质型，缺项即 failed）。
- 正类零预测组的 `gate_已断裂_recall` = 0（性质型）。

产出证据

- 路径：`records/full-chain-validation-20261018/c10/` 下 `metric_definition_table.md`、`synthetic_counterexamples.py`（待新建）、`synthetic_results.json`。
- 命令：

```console
$ .venv/bin/python scripts/eval_audit_gate_counterexamples.py --out records/full-chain-validation-20261018/c10/synthetic_results.json
$ .venv/bin/python -m pytest tests/test_holdout_metrics.py -q
```

- 格式：MD（定义表）、PY（用例脚本）、JSON（结果）。

依赖

- 上游：C9（解析与字段口径）。
- 外部条件：独立 reviewer 复核反打用例是否覆盖塌缩情形。

负责人

- 主 Agent 派单执行脚本。
- 独立 reviewer 复核。

### C11 聚合与统计

质疑点

1. 是否记录 support（每类样本数）？只看比率时，33 条正样本与 330 条正样本的 0.15 门槛是否等价？
2. 是否给置信区间？Wilson 与 bootstrap 两种口径是否固定为一种并写明参数？
3. 是否做塌缩检测？R1 425 条预测中「已断裂」出现 0 次【实测】，而训练池该类占 15.00%（DF-010，`docs/design-facts.md:94`【实测】）。
4. 给定 33 条正样本、0 次预测，门禁会不会判 pass？逐 gate 推演，写明哪些 gate 会通过、哪些会失败。
5. 三折 support 不等（425/664/492【待复算】）时，聚合按简单合并还是加权？口径是否在报告中写明？

验证方法

- 用合成塌缩数据跑聚合，输出 support、比率、CI。
- 用 R1 的 425 条结果（若结果文件可得）跑同口径聚合，与历史记录对比。
- 塌缩检测逻辑：单类预测占比 = 100% 时报出，输出触发记录。

通过判据

- 每个聚合输出必含 support 字段（性质型，缺项即 failed）。
- 塌缩检测存在，且能在单类 0 预测时报出（性质型）。
- CI 口径在报告中显式写出（Wilson 或 bootstrap，二选一固定，性质型）。
- 33 条正样本 0 次预测的推演结论必须逐 gate 列明（性质型，缺项即 failed）。

产出证据

- 路径：`records/full-chain-validation-20261018/c11/` 下 `aggregate_with_support.json`、`collapse_detection.md`、`fold_support.csv`。
- 命令：

```console
$ .venv/bin/python scripts/eval_audit_aggregate_support.py --records <预测记录 JSONL> --out records/full-chain-validation-20261018/c11/aggregate_with_support.json
```

- 格式：JSON（聚合结果）、MD（塌缩检测与推演）、CSV（三折 support）。

依赖

- 上游：C6（support 与分布）、C10（gate 判定）。
- 外部条件：用户裁决 CI 口径与 support 下限。

负责人

- 主 Agent 派单执行脚本。
- 用户裁决口径。

### C12 门禁

质疑点

1. 每个阈值的定义出处与设定理由是什么？已知 `0.65` 与 `0.4006` 的来源不明或不完整【推断】，必须列为「阈值来源无法追溯」问题。
2. 新体系有硬闸机，老体系无闸机【实测】。老链路是否仍能产出被后续文档引用的评测结论？
3. 政策层已知存在三条显式放宽。这三条现在是否仍然成立、写在哪个文件？【待验证】
4. 阈值可被谁改、改后如何发现？`validate_thresholds` 只与冻结常量比对（近似 `:33`–`:39`），改常量即同时改门禁【实测】。

验证方法

- 逐阈值追出处：对每个阈值数值与其常量名做全仓检索（`docs/`、契约、`records/`），输出「阈值 → 出处 → 设定理由」三列表，缺口写「无法追溯」。
- 老体系闸机检查：检索 legacy 入口（`pipeline/`、`finetune/`）是否存在 outcome 判定与阻断逻辑，输出命中的文件与行。
- 政策放宽条目定位：检索 `docs/` 中的放宽表述，逐条核对是否仍有效。
- 阈值变更检测：核对是否有校验锁定阈值常量（现有 `validate_thresholds` 只能防传入值偏离常量）。

通过判据

- 每个阈值都有可追溯出处与理由（性质型）。不能追溯的阈值必须单列为待裁决，且在裁决前不得用于放行（性质型）。
- 老体系闸机缺失的事实复现，并写明影响范围（性质型）。
- 三条政策放宽逐条给出文件位置与当前有效性（性质型，缺项即 failed）。

产出证据

- 路径：`records/full-chain-validation-20261018/c12/` 下 `threshold_provenance.md`、`legacy_gate_check.txt`、`waiver_list.md`。
- 命令：

```console
$ grep -rn "0.4006\|four_state_macro_recall" docs/ finetune/ versioning/ | tee records/full-chain-validation-20261018/c12/legacy_gate_check.txt
```

- 格式：MD（溯源表）、TXT（检索原文）、MD（放宽清单）。

依赖

- 上游：C10（阈值实现）。
- 外部条件：用户裁决不可追溯阈值的处置。

负责人

- 主 Agent 派单。
- 用户裁决不可追溯阈值与放宽条目。

### C13 晋级与登记

质疑点

1. `versioning/registry.py` 的 `require_passed` 是否覆盖全部入口？`_run_eval_gate(..., require_passed=True)` 定义于近似 `:974`，阻断逻辑在近似 `:995`（`if require_passed and record.outcome != "passed":`）【实测】。
2. 调用点是否如记录所列：近似 `:522`、`:1041`、`:1097`–`:1098`、`:1196`、`:1210`、`:1281`、`:1361`，另有 `versioning/manifest.py:641`【实测】。是否有写入门函数未挂 gate？
3. 是否存在绕过路径：哪条 CLI 子命令或函数级 API 能在 `outcome != passed` 时写出 model release 或 service admission？
4. `require_passed=False` 的调用是否仍写出可被下游引用的产物？
5. 是否存在「先登记再验证」的顺序，使 `outcome` 可被后续覆盖？

验证方法

- 入口枚举：`python -m versioning --help` 与各子命令 help；AST 扫描 `versioning/registry.py`、`versioning/manifest.py` 的全部 `def`，标注哪些调用 `_run_eval_gate`、默认 `require_passed` 取值。
- 写入门函数前置 gate 覆盖率图：每个写 release 或 admission 的函数，列出前置 gate 调用。
- 绕过尝试：构造 `outcome=failed` 的 store 夹具，逐入口试跑，记录是否被拒绝。相关回归见 `tests/versioning/test_registry.py`、`tests/versioning/test_manifest.py`。

通过判据

- 写入门函数前置 gate 覆盖率 = 100%（性质型，未覆盖数 = 0）。
- `outcome=failed` 夹具下，成功写出 release 或 admission 的入口数 = 0（性质型）。
- 入口枚举清单与代码中的 `def` 数量可对账，缺项数 = 0（性质型）。

产出证据

- 路径：`records/full-chain-validation-20261018/c13/` 下 `entrypoint_matrix.csv`、`bypass_attempt.log`、`gate_coverage.md`。
- 命令：

```console
$ .venv/bin/python scripts/train_audit_registry_gate_coverage.py --out records/full-chain-validation-20261018/c13/gate_coverage.md
$ .venv/bin/python -m pytest tests/versioning/test_registry.py tests/versioning/test_manifest.py -q
```

- 格式：CSV（入口矩阵）、LOG（绕过尝试原文）、MD（覆盖率图）。

依赖

- 上游：C12（闸机口径）。
- 外部条件：本地 store 夹具可用；独立 reviewer 做对抗式复核。

负责人

- 主 Agent 派单执行脚本。
- 独立 reviewer 对抗式复核。

### C14 报告与档案

质疑点

1. 每个数字是否标了口径三元组（`code_commit` + `data_release` + `prompt_version`）？缺项的数字清单是什么？
2. `docs/plans/2026-10-18-evaluation-pipeline-redesign.md`、`docs/project-todo.md`、`docs/pending-blockers.md` 中所有 R1 指标数字，逐条问「能否还原出三元组」？
3. 历史结论是否需要加注「标签存疑」？R1 的 425 条指标建立在可能与画面不符的标签上【推断】。
4. 同一指标在不同文档出现不同值时，是否有口径标注区分，还是同口径矛盾？

验证方法

- 正则抽取三份文档中的百分数、比率、计数，落成清单。
- 逐条人工判定：三项口径是否可还原（是／部分／否）。
- 不能还原的条目进「必须加注」清单，并给出加注位置与文案建议。
- 跨文档同指标比对，输出矛盾清单。

通过判据

- 「必须加注」清单完整，缺项数 = 0（性质型）。
- 每条给出位置与加注文案建议（性质型）。
- 跨文档同口径矛盾条目逐条列出（性质型）。

产出证据

- 路径：`records/full-chain-validation-20261018/c14/` 下 `metric_provenance.csv`、`must_annotate.md`、`conflict_list.md`。
- 命令：

```console
$ .venv/bin/python scripts/eval_audit_metric_provenance.py --docs docs/plans/2026-10-18-evaluation-pipeline-redesign.md docs/project-todo.md docs/pending-blockers.md --out records/full-chain-validation-20261018/c14/metric_provenance.csv
```

- 格式：CSV（数字清单与口径判定）、MD（加注清单）、MD（矛盾清单）。

依赖

- 上游：C1–C13 的结论（加注对象包含本轮各环节证据）。
- 外部条件：用户裁决是否回填加注到原文。

负责人

- 主 Agent 派单执行脚本。
- 用户裁决加注范围。

## 4. 开训闸门

全部 14 项 `passed` 才允许开训。任一项 `failed` 或 `未验证` 均不得开训。`blocked` 或 `waived` 需用户书面裁决，Agent 不得自行放宽。

| 环节编号 | 环节名 | 通过判据（摘要） | 当前状态 | 证据路径 |
| --- | --- | --- | --- | --- |
| C1 | 源数据接入 | 三向差集 0、界外 ROI 0、目视非试样占比 ≤ 5%（阈值待裁决） | 未验证 | `records/full-chain-validation-20261018/c1/` |
| C2 | 事件时刻标注 `event_time` | 中位数 \|Δ\| ≤ 0.5 s、超 0.5 s 占比 ≤ 10%（阈值待裁决） | 未验证 | `records/full-chain-validation-20261018/c2/` |
| C3 | 候选窗口生成 | 几何断言违反 0、零长或负长窗口 0 | 未验证 | `records/full-chain-validation-20261018/c3/` |
| C4 | 标签赋值 `_state_for_interval` | 视觉一致率 ≥ 90%（阈值待裁决）、正例污染 0 | 未验证 | `records/full-chain-validation-20261018/c4/` |
| C5 | 数据集构建 | 字段集三向相等、模板哈希一致、过期字段 0 | 未验证 | `records/full-chain-validation-20261018/c5/` |
| C6 | 采样与分母 | 复算计数一致、fold 间源视频交集 0、分布差 ≤ 3 个百分点（阈值待裁决） | 未验证 | `records/full-chain-validation-20261018/c6/` |
| C7 | 训练配置 | 无人认领参数清单完整、截断 0、三折差异 0 | 未验证 | `records/full-chain-validation-20261018/c7/` |
| C8 | 推理管线 | `temporal_ids` 非 -1 元素 0、视觉 token 512 可复算 | 未验证 | `records/full-chain-validation-20261018/c8/` |
| C9 | 输出解析与形式校验 | 字段集三向相等、畸形输入全判不合法、`None == None` 回归通过 | 未验证 | `records/full-chain-validation-20261018/c9/` |
| C10 | 判分实现 | 反打用例不一致 0、覆盖塌缩与完美两类 | 未验证 | `records/full-chain-validation-20261018/c10/` |
| C11 | 聚合与统计 | 输出含 support、塌缩可报出、CI 口径固定 | 未验证 | `records/full-chain-validation-20261018/c11/` |
| C12 | 门禁 | 阈值出处与理由可追溯、老体系无闸机事实复现并写明范围 | 未验证 | `records/full-chain-validation-20261018/c12/` |
| C13 | 晋级与登记 | 前置 gate 覆盖率 100%、`outcome=failed` 下写出入口 0 | 未验证 | `records/full-chain-validation-20261018/c13/` |
| C14 | 报告与档案 | 「必须加注」清单完整、矛盾条目逐条列出 | 未验证 | `records/full-chain-validation-20261018/c14/` |

上表「当前状态」一栏 14 行全部为 `未验证`。不许留空，不许写「基本没问题」或「大致通过」。

#### 失效传播矩阵

| 变更环节 | 必须重验的下游 | 理由 |
| --- | --- | --- |
| C1 源数据 | C2、C3、C4、C5、C6 | 视频、ROI、metadata 一变，事件时刻与几何判定的参照全变 |
| C2 `event_time` | C3、C4、C6、C11 | 窗口几何、标签赋值、类别分布与 support 都按 event 计算 |
| C3 窗口生成 | C4、C6、C8 | 标签由几何算出，帧采样位置随窗口变化 |
| C4 标签赋值 | C6、C10、C11、C14 | 训练分布、判分口径、聚合与历史数字全部以标签为真值 |
| C5 数据集构建 | C6、C7、C9 | Prompt 与字段决定采样输入、token 长度与解析必填字段 |
| C6 采样与分母 | C11、C14 | support 与分布是聚合与历史对比的分母 |
| C7 训练配置 | C8（输入管线参数）、C14 | `video_maxlen`、`cutoff_len` 决定序列与截断口径 |
| C8 推理管线 | C9、C10、C11 | 输入表示决定输出内容，进而决定解析与判分结果 |
| C9 解析与字段 | C10 | 判分依赖解析后的字段 |
| C10 判分实现 | C11、C12、C13 | 指标值决定聚合、门禁与晋级结论 |
| C12 门禁阈值 | C13、C14 | 阈值一变，晋级结论与历史数字的可比性同时失效 |
| C13 晋级登记 | C14 | 登记结果进入档案引用 |

## 5. 已知问题台账

| 编号 | 问题 | 影响环节 | 当前状态 | 追加证据 |
| --- | --- | --- | --- | --- |
| K1 | 标为「已断裂」的子视频中很多首帧看不到可见断裂，标签可能与画面不符 | C2、C4、C6、C14 | 未验证（用户目视，待量化） | `records/full-chain-validation-20261018/c4/confusion_geometry_vs_visual.csv` |
| K2 | `event_time` 与人眼判读差约 3.5 s（`video_0110`） | C2、C3、C4 | 未验证【推断】 | `records/full-chain-validation-20261018/c2/event_time_bias.csv` |
| K3 | 评测侧 `temporal_ids` 全为 `-1` | C8、C10 | 已实测确认，归因未定（见 `docs/pending-blockers.md` 的 PB-002） | `docs/pending-blockers.md:29`（转引 `docs/project-todo.md:69` 的 CPU 复验）+ 仓库外 `~/pi-workspace/mVllm_2-audit/frame-awareness-report-20261018.md`（不入 Git）；`records/full-chain-validation-20261018/c8/processor_inputs.json` 为计划产物，待生成 |
| K4 | R1 425 条预测中「已断裂」出现 0 次 | C11、C10 | 已实测 | `docs/results/model-r1-effect-profile-20261018.md:216`、`:488`（旧口径；新口径 425 结果尚未入库，见 `docs/project-todo.md:82`）；`records/full-chain-validation-20261018/c11/aggregate_with_support.json` 为计划产物，待生成 |
| K5 | `finetune/validation/task_metrics.py:51` 一带曾因 `None == None` 白送判对 | C9 | 已修，待回归 | `records/full-chain-validation-20261018/c9/pytest_output.txt` |
| K6 | 过期字段 `fracture_between` 残留（v2 契约已删，`pipeline/prompt_library.yaml:9` 仍要求） | C5、C9 | 未清理（暂缓） | `records/full-chain-validation-20261018/c5/prompt_field_diff.json` |
| K7 | 老体系无闸机 | C12、C13 | 已读代码确认（非运行实测） | 仓库外 `~/pi-workspace/mVllm_2-audit/gate-status-20261018.md:250`（`pipeline/model_registry.py`、`finetune/release_validate.py` 只算分不拦人；不入 Git）；`records/full-chain-validation-20261018/c12/legacy_gate_check.txt` 为计划产物，待生成 |
| K8 | `strict_valid` 只校验形式 | C9、C10 | 已读代码确认（非运行实测） | `finetune/eval_run.py:344`（`strict_valid = prediction is not None`）+ `finetune/v4_1_runtime.py:451-461`（`parse_v4_1_output` 只做 `json.loads` 与标签词表规范化）；`records/full-chain-validation-20261018/c9/strict_valid_cases.md` 为计划产物，待生成 |
| K9 | 训练池「已断裂」占 15.00%（DF-010），模型从不输出该类 | C6、C11 | 已实测（两侧事实各自成立） | `docs/design-facts.yaml:131-142`（DF-010，`established_by: 代码核对`，evidence 指 `docs/plans/2026-10-18-evaluation-pipeline-redesign.md:83`）；`records/full-chain-validation-20261018/c6/class_balance.csv` 为计划产物，待生成 |
| K10 | 源数据个别帧内容与主题无关（某样本把「锡纸擦不锈钢」镜头当成试样画面） | C1、C4 | 已知 1 例，未系统排查 | `~/pi-workspace/mVllm_2-audit/full-chain-validation-20261018/c1/visual_review.md`（仓库外，不入 Git） |

K10 的原始出处为仓库外 `~/pi-workspace/mVllm_2-audit/frame-awareness-report-20261018.md` 的 P3 段落，该文件不在 Git 内。

## 6. 执行顺序与批次建议

先做 C2。理由三条。C1 的产出是 C2 的输入，但 C1 的量级是「全量探测加抽样目视」，C2 的量级是「30 条逐条判读」，两者可以并行起，C2 的人工判读排期最长。C2 的偏差分布是 C3、C4 判据的输入，晚做会让后两层判据悬空。C4 是整条链的真值来源，K1 与 K2 两条质疑都收在 C4，不先量化就没有可用的真值。

建议四个批次。

1. 批次一（可本机完成、不依赖训练机）：C5、C9、C10、C12、C13。五环都靠读代码、跑本地测试、构造合成数据，最快出结论，也能先暴露闸机与字段层面的硬缺陷。
2. 批次二（需媒体与人工目视）：C1、C2、C3、C4。四环串行，C2 的人工判读是瓶颈。C4 结束后才能判定 K1 是否成立。
3. 批次三（需训练机）：C6、C7、C8。三环要读训练机数据目录与 processor，C8 必须如实说明本机无法复现 GPU 结果。
4. 批次四（收口）：C11、C14。两环消费前三批证据，产出 support 口径、塌缩结论与「必须加注」清单。

批次一只在本地跑，允许与批次二并行。批次三开始前需用户给出训练机与 GPU 授权。

## 7. 本文档不做的事

- 不改任何代码，包括 `pipeline/v3_candidate_plan.py`、`finetune/validation/`、`versioning/registry.py`。
- 不改任何数据、Prompt、契约、阈值。
- 不改 `docs/project-todo.md`、`docs/pending-blockers.md`、`docs/design-facts.md`、`docs/design-facts.yaml`。
- 不提交其它文件。本轮提交只含本文件。
- 不执行训练、不启动评测、不调用远端接口。
- 不裁决阈值、不裁决 waiver、不裁决抽样量。

## 8. 下一步：需用户裁决的事项

1. 阈值来源：C2 的占比阈值、C4 的一致率阈值、C6 的分布差值阈值、C11 的 support 下限、C12 中无法追溯的 `0.65` 与 `0.4006`，各自取值由谁定、依据什么。
2. 抽样量 N：C1 与 C2 各抽多少条才能支撑结论。当前建议 30 条，依据是人力预算，不是统计功效计算。
3. 人工目视预算：C1 抽帧目视、C2 逐条判读、C4 二次复核，三处合计需要多少工时与几人。
4. 非通过项是否允许 waiver：哪些环节允许带条件通过，条件由谁书面确认，waiver 如何登记与失效。
5. CI 口径：C11 用 Wilson 还是 bootstrap，参数如何固定。
6. 历史数字的加注范围：C14 产出的「必须加注」清单是否回填到 `docs/plans/2026-10-18-evaluation-pipeline-redesign.md`、`docs/project-todo.md`、`docs/pending-blockers.md`。
