# Project TODO

本项目唯一任务台账（最新核对日期：**2026-11-25**，对应主线 `feat/tensileagent-finetune`）。设计与代码事实见 [facts.yaml](facts.yaml)，重要已确认决定见 [决策总览](decisions/README.md)，专题文档入口见 [项目导航](guide.md)。

## 项目现状总览（2026-11-25 实测）

- **源级输入**：110 个真实源视频（89 开发三折 + 21 固定 test；2026-11-25 [去重审计](research/source-video-dedup-audit.md)与 [DEC-007](decisions/0007-dev-test-dedup-exclusion.md) 按选项 A 在 `data/splits/dev-exclusions.json` 中强制排除与 test 近重复的 `video_0006`/`video_0079`，原 `data/splits/three-fold/*.json` 逐字节不动，有效开发源 **87**、每折 `58/29`，虚拟视频隔离由 12 升至 **15**），当前源标注表 [data/annotation-table-full.csv](../data/annotation-table-full.csv)（SHA-256 `c928bea3…c1ec354c`）与 ROI 清单 [data/roi/manifest.json](../data/roi/manifest.json)（110/110 `success`，2026-11-20 重扫）已就位。
- **候选子视频批次**：第 2 批（`basic` 档）已于 2026-11-20 在训练机生成并回传，共 **1,633 条**候选（开发集 1,319、固定 test 314；扣除选项 A 排除的 `video_0006` 19 条与 `video_0079` 1 条后有效开发候选 1,299 条），三份清单（`manifest.json`、`summary.json`、`audit.json`）已入库，本机媒体逐条 SHA-256 核对 `1,633/1,633` 一致。
- **人工审核进度**（以 [reviews.json](../data/subvideo-review/reviews.json) 实测为准，最新时间戳 `2026-11-25T08:46:05.068136+00:00`）：本批次身份有效确认 **527 / 1,633**（B0 校准批 `32/32`、B1 固定 test 批 `314/314`、B2 三折 val 抽样批 `180/180`、清单外试审 `1` 条 = `video_0050_coverage_02`），未审核 **1,106** 条，草稿／疑问／退回均为 0。**B0、B1、B2 已全部审完**，下一批次为 B3（开发集其余未审候选）。
- **尚未启动项**：真实模型训练、真实 GPU 推理、正式模型评测、数据发布与旧 `versioning` 晋级接入均**未执行**；源标注表发现的疑似错标已登记在 `§8 SOURCE-RELABEL`（9 源 12 字段），当前暂不改表。

| 编号与代号 | 任务名称 | 当前状态 | 当前关键进展／下一步 |
| --- | --- | --- | --- |
| [2. EVAL-DESIGN](#2-eval-design--设计并确认评价体系) | 设计并确认评价体系 | 进行中 | 五类评价口径、6 篇输入契约、PR #20 三篇调研、PR #21 独立取证 CLI、[DEC-006](decisions/0006-eval-frame-sampling-and-model-lineup.md)（8 帧抽帧口径与首轮 3+1 基座名单）、PR #23 [源视频去重与虚拟泄漏审计](research/source-video-dedup-audit.md)及 [DEC-007](decisions/0007-dev-test-dedup-exclusion.md)（选项 A 排除清单）已就位；待训练机体检、适配器代码、样本充分性与正式阈值 |
| [3. EVAL-VERSIONING](#3-eval-versioning--按新评价设计更新-versioning-评价与晋级门槛) | 更新 `versioning` 评价与晋级门槛 | 待处理 | 依赖 `EVAL-DESIGN` 定稿与真实测评证据 |
| [4. DATA-HANDOFF](#4-data-handoff--梳理新标注到数据生成的衔接方案) | 梳理新标注到数据生成的衔接方案 | 进行中 | 1,633 条新批次已回传核验；审核进度移交 `§6`，选项 A 排除清单 `data/splits/dev-exclusions.json` 已落地，待定虚拟视频切分策略与发布衔接 |
| [5. EVAL-SUBSET](#5-eval-subset--从新批次候选子视频构建测评候选子集) | 构建测评候选子集 | 已冻结（2026-11-25） | 已按方案 A 冻结 [`data/eval-subsets/eval-dev-v1.json`](../data/eval-subsets/eval-dev-v1.json)（210 条 / 87 源，严格排除 `DEC-007` 近重复源）与 [`data/eval-subsets/eval-test-v1.json`](../data/eval-subsets/eval-test-v1.json)（314 条 / 21 源，封存终测），并在 `script/five_label_eval/` 落地 `DEC-007` 代码防漏网守卫；登记见 [eval-subset.md](eval/eval-subset.md) §6.1 |
| [6. SUBVIDEO-HUMAN-REVIEW](#6-subvideo-human-review--人工审核新批次候选片段) | 人工审核新批次候选片段 | 进行中 | **当前主线**：B0（32/32）、B1（314/314）与 **B2（180/180，2026-11-25）** 已全部完成，累计有效确认 **527/1,633** → 下一步 B3（未审 1,106） |
| [7. MAPPING-NODE-RENAME](#7-mapping-node-rename--重命名映射节点消除-source_to_media-的方向误读) | 重命名映射节点 | 已解决（2026-11-24） | 已改用 `clip_to_model_input`／`clip_to_roi`／`roi_to_original`（`five-label-input-record/3`，显式拒绝旧 v2），见 `DF-052` |
| [8. SOURCE-RELABEL](#8-source-relabel--源标注待改清单与集中修正) | 源标注待改清单与集中修正 | 等待确认／未开始 | 已登记 9 源 12 字段（7 个 test 源 + 2 个开发集源）；暂不改表，建议 B3 审完、正式微调前集中复核 |
| [1. LABEL-ANNOTATION](#1-label-annotation--确认标签基准并进行人工标注) | 确认标签基准并进行人工标注 | 已解决（2026-11-07） | 110 条源标注与材料类型补全已完成；后续修正由 `§8` 跟踪 |

---

## 2. EVAL-DESIGN — 设计并确认评价体系

**状态：** 进行中。本轮五类评价口径已按 [DEC-003](decisions/0003-five-label-eval-scope.md)（2026-11-14）确认，片段层删除「无」与分层评分已按 [DEC-004](decisions/0004-fragment-label-no-value-removal.md)（2026-11-16）确认，帧对应抽帧取证设计已按 [DEC-005](decisions/0005-frame-correspondence-evidence.md)（2026-11-23）确认且独立取证 CLI 已于 PR #21（2026-11-24）落地于 `script/frame_correspondence/`，PR #20（2026-11-24）三篇多模型评测调研已合入，首轮 8 帧抽帧口径与第一梯队 3+1 基座名单已按 [DEC-006](decisions/0006-eval-frame-sampling-and-model-lineup.md)（2026-11-25）确认；评分工具与身份清单草稿工具已有合成验证；真实推理适配器、训练机前置体检、样本充分性、正式阈值与测评子集冻结尚未落地。

### 目标

基于本轮已确认的五类标签，明确各类别的评价方法、多选现象、异常与「无法判断」的处理、统计分母、结果报告和质量要求。现有 v4.1 评分与旧阈值不直接套用。

### 当前进展

- **评价设计与决策已成型**：[整体模型测评设计](design-test.md)已记录质量及性能、五类标签分母与失败处理、多模型及三组数据对照、测试安排与记录方式；[DEC-003](decisions/0003-five-label-eval-scope.md)（DF-043）已确认 11 项核心口径，含源级「无法判读」样本进入训练与评价（作为「无法判断」能力类别）、多选 8 叶项与 `over_uncertain_rate`、本轮只报数不设正式阈值与性能门槛、诊断题不纳入本轮主评价、虚拟视频仅做试制与链路检查。
- **评测输入契约与方案文件已拆分归位**：2026-11-14 将原单文件索引 `docs/eval-input-contract.md` 并入 [评测专题目录](eval/README.md) 并拆为 6 篇专题（`output-contract.md`、`prompt.md`、`inference-entry.md`、`input-record.md`、`eval-subset.md`）；另已形成 [基座模型测评方案](eval/base-model-eval-plan.md)、[帧对应抽帧取证](frame-correspondence-evidence.md)（[DEC-005](decisions/0005-frame-correspondence-evidence.md)）及未冻结的 [Agent 视觉与交付契约草案](eval/agent-handoff-contract-draft.md)。
- **评分工具完成合成验证**：用户已确认五类逐项输出、准确率与召回分母、失败与未知分列、冲突逐项评分，以及精确率、误报率和五类全对的补充口径（DF-030）。[本地评分工具](../script/five_label_eval/README.md)与身份清单草稿工具已通过人工构造的合成数据核验；完整片段与实际输入的人审分开，真实与虚拟分开。标签名称同步的浏览器核验亦基于合成 CSV，不代表真实标注或真实模型评价已验证。
- **位置校准规则已降级收敛**：按 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 7 条，以 [位置校准样例集](label-calibration/README.md) 现存 9 例样例与 [标签说明](label.md) 第 5 节「断裂位置」规则为准，不再整批重标。
- **多模型调研与独立抽帧取证 CLI 已落地（2026-11-24）**：PR #20 已合入三篇专项调研（[8B/9B 模型选型对比](research/vlm-8b-9b-model-comparison.md)、[8 帧抽帧口径方案](research/model-input-frame-sampling-options.md)、[训练机前置体检与推理适配器规划](research/eval-preflight-and-adapter-plan.md)）；PR #21 已合入 `DEC-005` 独立帧对应抽帧取证 CLI（[script/frame_correspondence/README.md](../script/frame_correspondence/README.md)，尚未在真实运行产物上实跑）。
- **评测 8 帧抽帧口径与首轮基座名单已拍板（2026-11-25，[DEC-006](decisions/0006-eval-frame-sampling-and-model-lineup.md) / `DF-053`）**：
  1. 8 帧抽帧公式（关闭 `DEC-005` 前置条件 1）：采用方案 A（`evenly_spaced_inclusive`，全片均匀含首尾，固定 8 帧），`frames.py` 默认帧数由 `3` 对齐为 `8`；
  2. 短片（`total_frames < 8`）策略：采用 `fail_closed` 报错拒接，不静默减帧或重复补帧；
  3. L3 PNG 缩放归属：保持 L2 原始分辨率（`resize: null`），各模型 processor 应用约定 `max_pixels` 并记入运行身份；
  4. `MiniCPM-V-4.5` 时序与切片参数：首轮采用官方风格（`0.1 s` 量化 `temporal_ids` + `max_slice_nums=1`），**并登记为后续对照/优化项**（首轮基线后可另起独立 `run_id` 与旧链路配置对照）；
  5. 首轮 8B–9B 基座名单：锁定第一梯队 3+1 款（`MiniCPM-V-4.5`、`Qwen3-VL-8B-Instruct`、`InternVL3-8B`、`InternVL3.5-8B` 标准版不含 ViR），第二/三梯队延后至首轮基线之后；
  6. `GLM-4.1V` `<answer>...</answer>` 处置：主榜采用方案 1（原生格式罚分），不预埋解包分支（未来若测试须另起独立 `run_id` 对照）。
- **未落地项**：训练／业务契约、真实模型推理适配器（`http` / `transformers`）、训练机只读体检、正式通过阈值与晋级衔接尚未落地。

### 下一步

- [x] 位置视觉规则校准：已按 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 7 条降级为以 [样例集](label-calibration/README.md) 现存 9 例样例与 [标签说明](label.md) 第 5 节为准，不再整批重标。
- [x] 整理并确认本轮评价标准及其适用范围：已于 2026-11-14 确认，结论见 [DEC-003](decisions/0003-five-label-eval-scope.md)（DF-043）。
- [ ] 对照本轮标注与已确认分母，明确除已确认项（含 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 1 条源级「无法判读」用途）外仍待敲定的补充统计口径；当前不评价模型预测断裂时间类标签的能力（DF-019）。
- [ ] 结合人工审核后的真实片段标签分布，讨论类别覆盖、样本充分性、正式阈值及评分工具的校准需求（不据源视频数量推断子视频或各划分的样本充分性）。

### 完成标准

- [ ] 各类别评价方法、统计分母和异常处理规则清楚且无遗留争议。
- [ ] 多选现象和「无法判断」的处理方式清楚并完成口径对齐。
- [ ] 结果报告的内容、适用范围和质量要求明确。
- [ ] 需要用户决定的评价标准已全部列出并获得明确确认。

> 注：设计完成不等于实施或真实评测完成。

### 后续前置工作

正式测评启动前须具备的前置核对（与本任务设计定稿分开跟踪）：

- [x] 位置视觉规则典型样例校准：已按 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 7 条收敛至 [样例集](label-calibration/README.md) 9 例与 `docs/label.md` 第 5 节。
- [x] 评分工具合成验证：已用人工构造小例核验多选未知、缺字段、失败、组合冲突与已确认分母（仅合成数据，不代表真实测评）。
- [ ] 补齐源视频近似素材去重核查及新增虚拟视频来源核查：2026-11-25 已完成 110 源全量 5,995 对去重审计与 65 条虚拟视频泄漏审查（PR #23，见 [源视频去重与虚拟泄漏审计](research/source-video-dedup-audit.md)）并按 [DEC-007](decisions/0007-dev-test-dedup-exclusion.md) 落地选项 A 排除清单 [`data/splits/dev-exclusions.json`](../data/splits/dev-exclusions.json)（排除 `video_0006`/`video_0079` 及其 20 条子视频，隔离 15 条虚拟视频）；余下未决项为 32 条 `1280×720` 复材固定机位簇其余未复核配对（含 5 条 test）及训练机仓外历史暴露核查。
- [x] 完成多模型输入及训练机资源适配调研：已完成 [MiniCPM 视频加载核查](research/minicpm-video-loading.md) 与 PR #20 三篇专项调研（[8B/9B 模型选型](research/vlm-8b-9b-model-comparison.md)、[8 帧抽帧口径](research/model-input-frame-sampling-options.md)、[训练机前置体检与适配器规划](research/eval-preflight-and-adapter-plan.md)），6 项核心边界已按 [DEC-006](decisions/0006-eval-frame-sampling-and-model-lineup.md) 拍板；待执行训练机只读体检与推理适配器落地。
- [ ] 核对实际待测模型权重、微调结果、数据、输入及评分规则的完整身份。
- [ ] （后续优化/对照项，首轮基线后）`MiniCPM-V-4.5` 时序与切片参数对照：首轮按 [DEC-006](decisions/0006-eval-frame-sampling-and-model-lineup.md) 采用官方风格（`0.1 s` 量化 `temporal_ids` + `max_slice_nums=1`），后续可另起独立 `run_id` 与旧链路配置（`temporal_ids=None`、`max_slice_nums=2`、`max_pixels=65,536` 规整）做同口径对照优化。

### 等待确认

- 首轮基座名单（第一梯队 3+1 款）与 8 帧抽帧口径已按 [DEC-006](decisions/0006-eval-frame-sampling-and-model-lineup.md) 确认；样本是否足够、正式通过阈值、第二/三梯队是否追加及多模型组合方式，待审核数据、训练机体检与首轮基线证据具备后确认；本轮按 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 3、4 条只报数、不设门槛。
- 组合冲突保留原回答、逐项评分并单列；本轮不自动接入晋级或发布，其他自动使用方式另行决定。

### 限制与关联

- 本条不构成真实模型评测、使用固定 test 跑模型或其他实施授权；评价协议与晋级衔接由 [§3 EVAL-VERSIONING](#3-eval-versioning--按新评价设计更新-versioning-评价与晋级门槛) 承接。
- **生成规则改动验收约束**：凡涉及子视频生成规则改动，验收时必须单独运行 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/private/tmp/subvideo-tests script/subvideo_generation/tests`（默认 `testpaths` 不含该目录，耗时约 5–6 分钟，不能被默认全量 `pytest` 替代）。

---

## 3. EVAL-VERSIONING — 按新评价设计更新 versioning 评价与晋级门槛

**状态：** 待处理；依赖 [§2 EVAL-DESIGN](#2-eval-design--设计并确认评价体系) 的整体评价设计完成并获得真实测评依据。

### 目标

在整体评价设计确认后，审查并更新原工作区 `versioning` 的评价协议、指标与晋级门槛，使其与新五类标签及已确认的质量、性能评价口径一致。

### 当前进展

- 现有 `versioning` 评价及晋级路径仍依赖旧 v4.1 协议与历史七门阈值（DF-004、DF-005），新五类标签尚未接入（`versioning/` 目录亦未在本 sparse-checkout 工作区检出）。
- 旧指标、旧阈值与断裂时间戳测评指标不得自动迁入；真实测评入口与固定 test 的使用边界须依据最终确认的设计另行核对。

### 下一步

- [ ] `EVAL-DESIGN` 定稿后，对照最终设计梳理协议、记录、指标、晋级条件与现有入口的差异。
- [ ] 明确更新范围、兼容边界与验证方案；正式阈值、样本充分性及待决项按已确认设计另定。

### 完成标准

- [ ] 新评价与晋级口径和已确认设计一致，质量、性能及证据不足的处理均可追溯。
- [ ] 旧 v4.1 口径仅保留其原有适用边界，不与新协议混用。
- [ ] 必要验证通过，且真实运行证据与静态或合成验证分开记录。

### 限制与关联

- 关联 [§2 EVAL-DESIGN](#2-eval-design--设计并确认评价体系)、DF-003、DF-004、DF-005、DF-018。
- 登记本项不构成实施、真实模型测评、使用 test 或数据链路操作授权。

---

## 4. DATA-HANDOFF — 梳理新标注到数据生成的衔接方案

**状态：** 进行中。第 2 批子视频（1,633 条，`basic` 档）已于 2026-11-20 在训练机生成、回传本机并完成全量逐条 SHA-256 核对（`1,633/1,633` 一致），三份清单已纳入 `data/sub_video/`；逐片人工审核进度统一由 [§6 SUBVIDEO-HUMAN-REVIEW](#6-subvideo-human-review--人工审核新批次候选片段) 跟踪；本项余下待决为虚拟视频切分策略、审核反馈收敛及后续发布接口衔接。

### 目标

承接本轮标注、固定划分与 ROI，按已确认规则统一生成子视频候选并核对画面对应；开发集与固定测试集每个源只生成一次，保留原三折归属，衔接人工逐片审核与后续数据发布。

### 当前进展

- **上游标注、划分与 ROI 就位**：110 条源标注（含材料类型补全）见 [§1 LABEL-ANNOTATION](#1-label-annotation--确认标签基准并进行人工标注) 与 [整体标签分布](label-distribution.md)。用户确认 110 个源视频各来自独立试验（近似素材仍待核查）；固定 21 条 `test.json`，89 条开发三折已于 2026-11-08 精简至 `data/splits/three-fold/`（仅保留 7 份成员 JSON 与 `manifest.json`），并于 2026-11-19 重标注定稿后重跑开发三折为 train／val `59/30`、`59/30`、`60/29`。2026-11-20 已重扫 ROI 清单（`data/roi/manifest.json`，SHA-256 `24b2dfa3019462dbef27fc00314901d30ad308802a458b31d95a90e4dc6948b3`），7/7 划分摘要、110/110 折归属与 110/110 标签均与当前输入一致，详见 [本轮划分结果](split/data-split-result.md) 与 [ROI 工具说明](../script/roi/README.md)。
- **时间标注与选窗规则已落地**：用户于 2026-11-07 澄清：断裂时间类标注可用于子视频生成；当前不为时间预测任务构建训练集，也不评价模型对时间类标签的预测表现（DF-019）。现行 [子视频生成与审核规则](subvideo-current-logic.md) 已实现精确帧不扩范围、时间范围两端各留 0.5 秒保护间隔、断后保护间隔外至少 2 秒源素材（DF-015）、`coverage` 数据判据（无断裂锚点且状态不可判或视频异常=是，DF-045）及片段标签按画面独立审核；数据与测评总链路见 [模型评价设计第 8 节](design-test.md#8-训练测评与交付衔接fj-阶段)。
- **双机分工与跨机同步已落地（2026-11-14 确认，DF-046／DEC-003 第 10、11 条）**：
  - 子视频生成在训练机执行（入口 `ssh liuyang@100.70.83.68`，主机名 `dell-Precision-3660`，训练机落点 `~/文档/TensileAgent-Finetune`）；媒体产物默认留在训练机，需在本机审查时按 [跨机审查运行手册](training-machine-review-runbook.md) §5.1 单向同步（训练机→本机、逐文件 `rsync` 禁 `--delete`、按 `output.sha256` 全量核对，DF-048）。
  - 清单与人工审查记录回传 Mac 并提交 Git；人工审查服务以 HTTP 提供、经 SSH 隧道访问，服务本身仍只监听回环。
  - 2026-11-14 决策曾记「Mac 侧旧批次作废：`data/sub_video/videos` 待删除」，原旧批次三个 JSON 已于 2026-11-19 删除，2026-11-20 新批次媒体回传并完成 `1,633/1,633` 核对后已全面替代旧批次。
- **当前生效批次（第 2 批，2026-11-20 生成，PR #2 合并）**：通过 [统一入口](../script/subvideo_generation/generate.py) 先跑 `--verification basic --output-dir data/sub_video`，再跑 `--audit-only --write-audit --output-dir data/sub_video` 产出 `audit.json`（该批重生成与训练机同步历史变更单已于 2026-11-25 经用户授权清理）。共 **1,633 个候选**（开发集 1,319、固定 test 314；媒体 191,625,749 B 不入库，本机逐条核对 `output.sha256` `1,633/1,633` 一致）：
  - 角色计数：`pre` 825、`fracture` 576、`post` 127、`coverage`（93）、`no_fracture` 9、`unclamped` 3；`excluded_windows=54`（pre 越下界保护 28、post 余量不足 2 秒 18、过渡未覆盖完整事件 6、未夹紧素材不足 2）。
  - 较历史 1,621 个候选新增的 12 个全部来自 `video_0040`（断裂模式由脆性改为半脆半韧，`pre` 由 3 增至 15）；其余 109 个来源逐源逐角色一致。
  - 审计记录 `candidates_needing_attention=63`（63 条均含「未断裂片段的断后脱夹需复核」，其中 15 条兼有「未断裂与爆炸性断裂互斥」）；`manifest_sha256` 与 `run_summary_sha256` 核对一致。按 [生成逻辑 §8](subvideo-current-logic.md)，`basic`／`none` 不提供任何帧对应证明。
- **审核工具与专题文档已接入导航**：[独立审核工具](../script/subvideo_review/README.md)与 [审核与评分衔接](subvideo-review-workflow.md) 已接入第 2 批清单并完成 B0（32/32）与 B1（314/314）真实人工审核（详见 [§6](#6-subvideo-human-review--人工审核新批次候选片段)）；`docs/subvideo-current-logic.md`、`docs/subvideo-review-workflow.md` 与 `docs/training-machine-review-runbook.md` 均已于 PR #12 纳入 [项目导航](guide.md)「子视频生成、审核与跨机运行」节。
- **历史已删除／已退役批次摘要（仅作追溯，不再作为可用产物）**：
  - 2026-11-09 开发集初裁批（67 源 / 1,123 片段，两段严格重放通过）：已于 2026-11-11 按用户要求删除，删除前未审核、未发布。
  - 2026-11-11 统一第 1 批：本轮重新编码 1,621 个候选（开发集 1,307、固定测试集 314），通过源到 ROI、ROI 到片段严格重放与完整解码检查；该批次已退役，其清单、摘要和核验记录已删除，训练机仓外暂存副本亦已于 2026-11-20 核对后删除（历史变更单已于 2026-11-25 经用户授权清理）。

### 下一步

- [x] 按视频 ID 核对新标注与既有划分对应、字段覆盖及使用边界（近似素材与模拟来源核查仍在 `EVAL-DESIGN` 后续前置工作跟踪）。
- [x] 完成旧规则加严初裁、两段严格重放核验及事件后保护间隔外 2 秒素材检查（DF-015）。
- [x] 在训练机重生成第 2 批子视频（`basic` 档，1,633 候选 / 191,625,749 B）并回传本机逐条哈希核对（`1,633/1,633` 一致）。
- [x] 重生成后按新批次身份完成 B0 校准批（32/32，2026-11-23）与 B1 固定 test 批（314/314，2026-11-24）；旧批次 37 条修订按历史保留、不改写不删除。
- [x] 清理 4 条既有 `facts.yaml` 原文消失条目（DF-022、DF-027、DF-047×2）：已于 PR #9（2026-11-21）归零（`gone = 0`）。
- [ ] 结合人工审核反馈归纳重复问题；如确需调整规则或重生成真实／虚拟媒体，先提交方案并取得用户明确授权。
- [ ] 确认虚拟视频（110 条真实源之外）的窗口切分策略与 schema 去留：当前 [`script/subvideo_generation/virtual.py`](../script/subvideo_generation/virtual.py) 仅采用暂定滑窗（20 秒窗、15 秒步长，`role=window`，单一策略点 `plan_virtual_windows`，换策略不可 `--resume`）；目录约定为 `data/virtual/<版本>/`（见 [data/README.md](../data/README.md)，首批 `video-V1` 已迁入），独立 schema `tensile-virtual-sub-video/1` 是否长期保留一并待定。按 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 6 条，虚拟视频不纳入本轮主评价，当前暂缓推进。
- [ ] 明确仅有断裂时间点（无帧号）时的源帧定位办法，以及人工审核完成后的数据发布接口。

### 完成标准

- [ ] 已有划分、标注输入及其使用边界清楚，覆盖情况有可追溯依据。
- [ ] ROI、子视频生成、标签和审查各环节的输入输出、依赖及未决事项清楚。
- [ ] 初裁与统一新批次有完整可追溯记录；片段标签与五类评价口径一致，所有拟发布片段均具备人工审核决定。
- [ ] 子视频相关文档经用户最终审阅确认，且静态代码梳理与实际运行验证保持明确区分。

### 等待确认

- 虚拟视频窗口切分策略与 `tensile-virtual-sub-video/1` schema 是否长期保留。
- 仅有断裂时间点时的源帧定位规则及数据发布接口设计。

### 限制与关联

- **逐片人工审核进度**：统一由 [§6 SUBVIDEO-HUMAN-REVIEW](#6-subvideo-human-review--人工审核新批次候选片段) 跟踪，本节不再重复列出待审复选框。
- **双机操作红线**：在训练机改运行代码前须先同步 `script/`，禁止在训练机直接改写 `data/`；B2（每折 val 抽样 60 条）、B3（开发集三折 train 全量）边界不变，固定 test 不参与训练；源级「无法判读」16 条按 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 1 条纳入训练与评价。
- **特例与未授权边界**：`video_0093` 因断裂靠近结尾，只生成 15 个断裂前片段，事件与断后窗口条件不满足；固定测试媒体仅获准用于候选生成、核对与人工审核，模型训练、测评、时间预测任务与数据发布均未执行；技术验证不替代人工看片和标签审核。
- **历史提交备忘**：原记录中提交 `7015aaf` 正文「保留期由 30 天改为 7 天」属措辞失误，该提交已合入远端主线，保留原历史不再 amend。

---

## 5. EVAL-SUBSET — 从新批次候选子视频构建测评候选子集

**状态：** 已冻结（2026-11-25）。用户已于 2026-11-25 拍板采用方案 A 正式冻结两份测评子集：开发评测集 [`data/eval-subsets/eval-dev-v1.json`](../data/eval-subsets/eval-dev-v1.json)（`dev_all_clean`，210 条 / 87 源，SHA-256 `9de4f9c5f852254a14049b940f679fc0069ffdfa1b0e5d50ca6219d2c1736890`）与固定封存终测集 [`data/eval-subsets/eval-test-v1.json`](../data/eval-subsets/eval-test-v1.json)（`test_B1`，314 条 / 21 源，SHA-256 `8e20b903544284c6f3ae90088e0f823d70e1ee21ee8b5a8640395d0001f23f19`），完整登记见 [评测子集专题](eval/eval-subset.md) §6.1；原 [子视频候选分层与 B2 抽样草稿](subvideo-eval-subset-draft.md) 保留作抽样过程留档。同步已在 `script/five_label_eval/` 全入口落地 [DEC-007](decisions/0007-dev-test-dedup-exclusion.md) 代码防漏网守卫（`exclusions.py`）与离线回归测试。

### 目标

从新批次清单（当前 1,633 条候选）中按片段角色、五类标签与画幅三档分层构建并冻结正式测评子集，确保三个画幅档均有样本且严格执行 [DEC-007](decisions/0007-dev-test-dedup-exclusion.md) 去重排除；旧批次曾有 1,621 个候选（开发集 1,307、固定测试集 314），现已退役。

### 当前进展

- **正式冻结子集已落盘并可复现核验（2026-11-25，方案 A）**：由 [`script/five_label_eval/freeze_subsets.py`](../script/five_label_eval/freeze_subsets.py) 确定性生成并支持 `--verify` 逐字节复核，登记见 [eval-subset.md](eval/eval-subset.md) §6.1 与 `docs/facts.yaml`（`DF-055`）：
  - `eval-dev-v1`（[`data/eval-subsets/eval-dev-v1.json`](../data/eval-subsets/eval-dev-v1.json)，SHA-256 `9de4f9c5f852254a14049b940f679fc0069ffdfa1b0e5d50ca6219d2c1736890`）：`dev_all_clean` 全部 **210 条 / 87 源**（B0 32 + 试审 1 + 干净 B2 177；严格排除 `data/splits/dev-exclusions.json` 里的 `video_0006`/`video_0079` 及其 B2 已审的 `video_0006_pre_06`、`video_0006_pre_13`、`video_0079_fracture_01`）；三画幅档 `w_le_200` 112/48 源、`w_200_400` 42/20 源、`w_gt_400` 56/19 源；三折 val 分别为 69/29、73/29、68/29 源。
  - `eval-test-v1`（[`data/eval-subsets/eval-test-v1.json`](../data/eval-subsets/eval-test-v1.json)，SHA-256 `8e20b903544284c6f3ae90088e0f823d70e1ee21ee8b5a8640395d0001f23f19`）：`test_B1` 全部 **314 条 / 21 源**（固定封存终测集，严禁用于调参或选 Prompt）；三画幅档 `w_le_200` 90/7 源、`w_200_400` 140/8 源、`w_gt_400` 84/6 源。
- **DEC-007 代码防漏网守卫已落地（2026-11-25）**：新增 [`script/five_label_eval/exclusions.py`](../script/five_label_eval/exclusions.py)，并在 `manifest_convert`、`build_manifest`、`frames`、`infer`、`score` 全入口强制加载 `data/splits/dev-exclusions.json`（显式选中排除源/片段或隔离虚拟视频时 fail-closed 报错，全量转换/抽帧时自动过滤），同时支持 `--candidate-ids` 直接传入 `tensile-eval-subset/1` 冻结子集 JSON；离线回归测试见 `script/five_label_eval/tests/test_eval_subsets_and_exclusions.py`。
- **全量 1,633 条分层统计草稿（2026-11-24，现作抽样过程留档）**：见 [subvideo-eval-subset-draft.md](subvideo-eval-subset-draft.md)。开发集 1,319 条、固定 test 314 条；三个画幅档在全部（`881/448/304`，`55/29/26` 源）、开发集（`791/308/220`，`48/21/20` 源）与固定 test（`90/140/84`，`7/8/6` 源）下均有样本且来源数均 ≥ 6；仅 `no_fracture`（2 源）与 `unclamped`（1 源）< 3 源，已标明仅报个案与计数。核验记录 `data/sub_video/audit.json` 的 **63 条**待关注候选均已完成人工确认（B1 23 + B0 3 + B2 37）。
- **已退役批次历史对照（仅追溯）**：已退役批次的清单与摘要已删除，历史角色计数为 `pre` 813、`fracture` 576、`post` 127、`coverage` 93、`no_fracture` 9、`unclamped` 3；已退役批次已删除的核验记录曾标记 `candidates_needing_attention: 54` 的候选优先纳入并优先核验。

### 下一步

- [x] 基于当前第 2 批清单（1,633 条）与已审核记录，按「片段角色 × 五类标签 × 画幅三档」列出分层表，标明每层候选数与可用来源数（见 [subvideo-eval-subset-draft.md](subvideo-eval-subset-draft.md) §2）。
- [x] 按画幅三档统计候选分布，确认每档都有样本；来源数 < 3 的层（`no_fracture` 2 源、`unclamped` 1 源）已明示只报个案与计数。
- [x] 按当前批次 `data/sub_video/audit.json`（63 条待关注候选）列出优先核验清单（见 [subvideo-eval-subset-draft.md](subvideo-eval-subset-draft.md) §3）。
- [x] 产出候选清单草稿（含生成方式、来源、清单 SHA-256 与 B2 180 条抽样名单），明确标注「非冻结集」。
- [x] 按用户确认方案 A 冻结正式测评子集 `eval-dev-v1`（210/87 源）与 `eval-test-v1`（314/21 源）并在 `script/five_label_eval/` 落地 DEC-007 代码防漏网守卫（2026-11-25）。

### 完成标准

- [x] 分层表覆盖全部片段角色、五类标签与三个画幅档，并写明每层选取理由（见 [subvideo-eval-subset-draft.md](subvideo-eval-subset-draft.md)）。
- [x] 三个画幅档均有样本，档位归属按 [评测子集专题](eval/eval-subset.md) 的区间判据核对。
- [x] 当前批次核验记录中的重点候选（63 条）已在清单中标出并全部人工确认。
- [x] 正式冻结子集 `eval-dev-v1` / `eval-test-v1` 可确定性复现，登记文件 SHA-256 与用途边界，且与 `data/splits/dev-exclusions.json` 零交集。
- [x] 用户已确认方案 A 并完成正式冻结。

### 等待确认

- 虚拟来源未来如纳入诊断评测时的分层口径（本轮主评价按 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 6 条不纳入）。

### 限制与关联

- 本任务不运行模型、不评分、不发布数据；冻结子集不改变固定测试集（`eval-test-v1`）严禁用于调参或选 Prompt 的用途界限。
- 关联 [评测子集专题](eval/eval-subset.md) §6.1、[子视频候选分层与 B2 抽样草稿](subvideo-eval-subset-draft.md)、[DEC-007](decisions/0007-dev-test-dedup-exclusion.md)、[§2 EVAL-DESIGN](#2-eval-design--设计并确认评价体系)、[§6 SUBVIDEO-HUMAN-REVIEW](#6-subvideo-human-review--人工审核新批次候选片段)。

---

## 6. SUBVIDEO-HUMAN-REVIEW — 人工审核新批次候选片段

**状态：** 进行中（**当前主线任务**）。B0 校准批已完成 `32/32`（2026-11-23），B1 固定 test 批已完成 `314/314`（2026-11-24，PR #16 合并），**B2 三折 val 抽样批已完成 `180/180`（2026-11-25）**；本批次身份有效确认累计 **527 / 1,633**（B0 32 条 + B1 314 条 + B2 180 条 + B0 清单外试审 `video_0050_coverage_02` 1 条），草稿 0、疑问 0、退回 0，未审核 **1,106 / 1,633**。下一步推进 B3（开发集其余未审候选，可按 [DEC-007](decisions/0007-dev-test-dedup-exclusion.md) 跳过已排除的 `video_0006`/`video_0079` 未审子视频）。

### 目标

由用户逐片观看第 2 批清单（1,633 条候选）并填写五类 11 项片段标签，按来源聚簇、按 `B0 → B1 → B2 → B3` 批次顺序推进；人工决定写入独立的 [reviews.json](../data/subvideo-review/reviews.json)，供后续候选选取、训练与测评使用。

### 当前进展

- **实测数字口径（2026-11-25）**：以 [reviews.json](../data/subvideo-review/reviews.json)（SHA-256 `dfe682763c8308c66387642ddb0d0ce67d2c25a2a21c4ac404ac1f7478592f27`，最新时间戳 `2026-11-25T08:46:05.068136+00:00`）及当前批次清单（`manifest_sha256` = `c70686630c8fa0277305cc25a09821bc04ab853f6ce8a6ac3ca795998c08ac0f`）为准：不可变修订总数 **578** 条 = 本批次身份 **541** 条（对应 **527** 条有效确认候选：B0 32 + B1 314 + B2 180 + 试审 1）+ 旧批次身份 **37** 条（属历史隔离记录，不计入有效进度，不改写、不删除）。
- **B2 审完与同源同角色比对（2026-11-25）**：B2 全部 180 条已确认（覆盖 87 个开发源及全部 37 条未审待关注候选）；同源同角色（≥2 条）共 31 组，其中 9 组存在字段取值差异（`video_0013`、`0024`、`0028`、`0040`、`0045`、`0057`、`0068`、`0084`、`0110`），均属不同切片窗口可见范围差异（不自动视为源表错误，亦未擅自改表）；B2 审核期间用户直接确认的开发集源表待改项（`video_0043` 2 字段、`video_0046` 1 字段）已登记至 [§8 SOURCE-RELABEL](#8-source-relabel--源标注待改清单与集中修正)。
- **审核工具与批次选择已就绪**：[审核工具](../script/subvideo_review/README.md)打开候选时按候选标签预填 11 项作为草稿初值，确认仍须人工点击（DF-047），源标签只作另列参考、不参与预填，不回写生成清单或源标注；`audit.json` 经身份核对后提供 63 条重点提示。`B0`（32 条）、`B1`（314 条）、`B2`（180 条 `explicit_ids`：三折 val 池 `432 / 440 / 447` 各抽 60 条未审候选，全收 37 条未审待关注、100% 覆盖 87 个未审开发源，详见 [subvideo-eval-subset-draft.md](subvideo-eval-subset-draft.md) §4）、`B3`（1,319 条开发集）在 [batches.json](../data/subvideo-review/batches.json) 中均已为 `ready`。
- **审核方法约定**：按来源聚簇连续审核；采用「两遍填法」（第一遍按画面给值，第二遍复核不确定与组合冲突项）；隔批做防漂移抽检。
- **历史规则与旧批次说明**：2026-11-16 起片段层模式／位置删除「无」，改按第 4 节证据门槛判断并按断裂状态分层评分（[DEC-004](decisions/0004-fragment-label-no-value-removal.md)、DF-049）；旧 1,621 批次的 18 条已确认候选（含 10 条旧值修订及早期 `video_0001` 试审）均随批次切换自然隔离为历史记录。生成层旧规则写入的「无」在审核展示与预填时映射为「无法判断」并提示，不改写清单字节。

### 下一步

- [x] B0 校准批已审完并留档（32/32 已确认，审完日期 2026-11-23，全部取自开发集，按来源分组聚簇）：
  - `video_0002`：`video_0002_unclamped_01`、`video_0002_unclamped_02`
  - `video_0013`：`video_0013_fracture_01`、`video_0013_pre_01`
  - `video_0014`：`video_0014_fracture_01`
  - `video_0015`：`video_0015_coverage_01`
  - `video_0017`：`video_0017_fracture_01`
  - `video_0021`：`video_0021_coverage_01`
  - `video_0026`：`video_0026_fracture_01`、`video_0026_fracture_02`、`video_0026_fracture_03`（同源连号聚簇块）、`video_0026_pre_01`
  - `video_0040`：`video_0040_pre_01`
  - `video_0045`：`video_0045_fracture_01`、`video_0045_pre_01`
  - `video_0050`：`video_0050_coverage_01`
  - `video_0052`：`video_0052_no_fracture_01`、`video_0052_no_fracture_02`
  - `video_0068`：`video_0068_pre_01`
  - `video_0071`：`video_0071_fracture_01`
  - `video_0074`：`video_0074_fracture_01`、`video_0074_fracture_02`、`video_0074_pre_01`、`video_0074_post_01`
  - `video_0080`：`video_0080_post_01`、`video_0080_post_02`
  - `video_0083`：`video_0083_fracture_01`
  - `video_0099`：`video_0099_fracture_01`、`video_0099_fracture_02`
  - `video_0106`：`video_0106_fracture_01`、`video_0106_post_01`、`video_0106_post_02`
- [x] B1 固定 test 批已审完并入库（314/314 已确认，2026-11-24，PR #16）：test 划分内未审核 0 条，草稿／疑问／退回均为 0；审核中发现的疑似源表错标已登记至 [§8 SOURCE-RELABEL](#8-source-relabel--源标注待改清单与集中修正)。
- [x] B2 三折 val 抽样批已审完并入库（180/180 已确认，2026-11-25）：规则以 `explicit_ids` 写入 `data/subvideo-review/batches.json`（`seed=20261124`，不含已审 33 条，全收 37 条未审待关注，详见 [subvideo-eval-subset-draft.md](subvideo-eval-subset-draft.md) §4）；已确认项全部归档于 `reviews.json`，审核中补充确认的开发集源表待改项已登记至 [§8 SOURCE-RELABEL](#8-source-relabel--源标注待改清单与集中修正)。
- [ ] B3 开发集三折 train 全量（`batches.json` 返回全部 1,319 条开发候选，审核时在页面按状态筛选跳过已确认项，并按 [DEC-007](decisions/0007-dev-test-dedup-exclusion.md) 跳过已排除源 `video_0006`/`video_0079` 的未审候选）：在 B2 之后推进，每批完成后同步进度与遗留问题。
- [ ] 建立防漂移抽检记录（抽检片段、复看结论与差异处理）。

### 完成标准

- [ ] B0、B1、B2、B3 各批完成并有可核对的审核记录（截至 2026-11-25：B0、B1、B2 已完成，B3 未完成）。
- [ ] 审阅中发现的重复问题已归纳，需要改规则的已提交确认。
- [ ] 全部拟发布片段的审核记录均可追溯到片段、来源与生成身份；未审片段不发布。

### 限制与关联

- 本节与 `data/subvideo-review/reviews.json` 是人工审核进度的唯一权威入口。
- 审核由用户本人看画面执行，不以机器核验代替；本任务不运行模型、不训练、不测评，测试集候选仅参与看片与标签审核，不因此授权模型测试或用于训练。
- **守卫提示**：`script/subvideo_review/tests/test_batches.py` 直接解析本节 `### 下一步` 中的 32 条 B0 候选名及 [subvideo-eval-subset-draft.md](subvideo-eval-subset-draft.md) §4.3 中的 180 条 B2 候选名并与 `batches.json` 对账，调整清单时须同步保持格式一致。

---

## 7. MAPPING-NODE-RENAME — 重命名映射节点，消除 source_to_media 的方向误读

**状态：** 已解决（2026-11-24）。用户确认采用纯语义命名并升至 `five-label-input-record/3`、显式拒绝旧 v2 记录；代码、测试、契约文档与 `docs/facts.yaml`（`DF-052` 取代 `DF-041`）已同步完成。

### 目标

把 `frames[].frame_index_mapping` 的三个节点改成能直接体现层级方向的名称，消除 `source_to_media` 被误读为「源视频 → 媒体」的风险，并同步代码、记录 schema 与文档口径。

### 当前进展

- **已完成映射重命名与 schema 升级（2026-11-24）**：`media_to_clip` → `clip_to_model_input`（L2 → L3）、`source_to_media` → `clip_to_roi`（L2 → L1）、`roi_to_source` → `roi_to_original`（L1 → L0）；`RECORD_SCHEMA` 升级为 `five-label-input-record/3`。
- **旧记录显式拒绝已落地**：`read_records` 与 `verify_lineage` 对旧 `record_schema`（含 `/2`）以及含任一旧键名的记录均显式报错拒绝并点名新 schema 与新键名；`test_frames.py` 已补对应单元测试。
- **文档与事实库已对齐**：[输入记录专题](eval/input-record.md) §10、[帧对应抽帧取证](frame-correspondence-evidence.md) 与 `docs/facts.yaml`（新增 `DF-052` supersede `DF-041`，保留 `DF-041` 原结论作历史记录）已全部同步。

### 下一步

- [x] 拟定三个节点的新名称及旧名到新名的映射，并获用户确认（`clip_to_model_input`／`clip_to_roi`／`roi_to_original`）。
- [x] 在 `script/five_label_eval/frames.py` 更新输出字段名，同步记录 schema 版本（`five-label-input-record/3`）与合法性校验。
- [x] 同步 [输入记录专题](eval/input-record.md) §10 方向表与失效条件，并在 `docs/facts.yaml` 新增 `DF-052` supersede `DF-041`（不就地改写旧结论）。
- [x] 明确旧批次记录（含 `source_to_media` 键与 v2 schema）采用显式拒绝策略，写入文档并补单元测试。

### 完成标准

- [x] `frames.py` 输出、记录 schema、`docs/eval/input-record.md` §10 与 `docs/facts.yaml` 四处使用同一套新键名，无残留旧键名。
- [x] 旧批次记录的处理方式有明确说明（显式拒绝）与对应单元测试。
- [x] 全量测试与 `facts` 校验通过，命名契约变更证据落入 `docs/facts.yaml` 新条目（`DF-052`）。

### 限制与关联

- 清单上游字段 `output.frame_mapping.source_start_frame` 本身未改名，仍指 L1 ROI 空间起点。
- 关联 [输入记录专题](eval/input-record.md) §10、[帧对应抽帧取证](frame-correspondence-evidence.md)、DF-041（`superseded`）、DF-052。

---

## 8. SOURCE-RELABEL — 源标注待改清单与集中修正

**状态：** 等待确认／未开始。本轮仅登记 B1 人工审核中发现的源标注疑似错标，**不动 `data/annotation-table-full.csv`**，不重生成子视频，也不重审已确认片段。

### 目标

集中记录人工审核片段时发现的源视频标注（[data/annotation-table-full.csv](../data/annotation-table-full.csv)）待修正项，待人工审核阶段收敛后一次性复核并改表，避免零散改表导致输入指纹反复变动。片段最终标签始终以片段画面为准，源标签只作参考。

### 当前进展

2026-11-24 对 [reviews.json](../data/subvideo-review/reviews.json)（当时 SHA-256 `c2a0ab5df72023de2527a3bf0a35ade758ffd3da994eac5563d4a21bb38cb3c8`）做同源同角色比对：31 个来源中 17 个存在字段取值差异（`video_0005`、`0010`、`0019`、`0025`、`0038`、`0041`、`0062`、`0063`、`0067`、`0078`、`0082`、`0087`、`0088`、`0089`、`0093`、`0094`、`0095`），多数属窗口可见范围不同，其中 7 个固定测试集来源、9 个字段级条目纳入待核清单；2026-11-25 补充登记开发集来源 `video_0043`（2 个字段）与 `video_0046`（1 个字段）。当前合计 **9 个来源、12 个字段级条目**（7 个固定测试集 `test.json` + 2 个开发集，行号为 CSV 物理行号，第 1 行为表头）：

#### 已确认待改项（8 源 10 字段）

精简版清单见 [待修改原视频源标注字段](pending-source-relabels.md)；完整依据、待定项与改表流程以本节为唯一真源。

| 源视频 ID | CSV 行号 | 字段 | 现值 → 建议值 | 审核依据与附带注意 |
| --- | ---: | --- | --- | --- |
| `video_0005` | 6 | `断裂模式` | 脆性断裂 → 韧性断裂 | 已确认 `coverage_01`、`_02` 均判「韧性断裂」；源表备注记「视频最后画面发生偏移，导致断裂行为不可见」 |
| `video_0010` | 11 | `现象_伸长` | 无法判断 → 是 | 已确认 8 条 `fracture` 中 5 条（`_01`–`_05`）判「是」、3 条（`_06`–`_08`）判「无法判断」；`pre_05`–`pre_10` 亦判「是」 |
| `video_0019` | 20 | `现象_断后脱夹` | 否 → 是 | 已确认 9 条 `fracture`（`_01`–`_09`）全部判「是」；3 条 `post` 判「无法判断」 |
| `video_0025` | 26 | `断裂位置` | 无法判断 → 夹持根部 | 已确认 10 条 `fracture` 中 `_08`–`_10` 与 3 条 `post` 判「夹持根部」，`_01`–`_07` 判「无法判断」；**附带备注待清**：原 `标注备注` 为「下夹具不可见，导致断裂位置不确定。」，改表须一并确认清空或改写 |
| `video_0025` | 26 | `异常_视频异常` | 是 → 否 | **与已确认片段相左**：10 条 `fracture` 中 7 条（`_01`–`_07`）判「是」、3 条（`_08`–`_10`）判「否」；15 条 `pre` 全部判「否」 |
| `video_0041` | 42 | `现象_断后脱夹` | 是 → 否 | **与已确认片段部分相左**：8 条 `fracture` 中 `_07`、`_08` 判「是」，其余 6 条判「否」 |
| `video_0043` | 44 | `现象_伸长` | 否 → 是 | 2026-11-25 审核补充（属开发集 `fold_0_train`／`fold_1_val`／`fold_2_train`，非 `test.json`）；用户直接确认 |
| `video_0043` | 44 | `断裂模式` | 脆性断裂 → 半脆半韧断裂 | 2026-11-25 审核补充（同上，属开发集）；用户直接确认；**注意**：属开发集，正式改表时须评估是否重跑开发三折划分 |
| `video_0046` | 47 | `现象_伸长` | 否 → 是 | 2026-11-25 审核补充（属开发集 `fold_0_val`／`fold_1_train`／`fold_2_train`，非 `test.json`）；用户直接确认 |
| `video_0063` | 64 | `断裂位置` | 标距外非根部 → 标距内 | 已确认 8 条 `fracture`（`_01`–`_08`）全部判「标距内」；10 条 `pre` 与 1 条 `post` 判「无法判断」 |

#### 审查比对新发现待定项（2 源 2 字段）

| 源视频 ID | CSV 行号 | 字段 | 现值 → 建议值 | 审核依据与说明 |
| --- | ---: | --- | --- | --- |
| `video_0038` | 39 | `异常_视频异常` | 否 → 待定 | 15 条 `pre` 中 `_01`–`_03` 判「是」，`_04`–`_15` 与 4 条 `fracture` 判「否」；同源 `pre` 另有模式／位置／颈缩随窗口变化的差异，属可见范围不同，本身不构成源表错误 |
| `video_0041` | 42 | `断裂模式` | 半脆半韧断裂 → 待定 | 8 条 `fracture` 中 6 条（`_03`–`_08`）判「脆性断裂」、2 条（`_01`、`_02`）判「半脆半韧断裂」；同源 `现象_伸长` 亦为 2 条「是」、6 条「否」 |

### 下一步

- [ ] 复核整片：对上述 9 个来源逐条回看源视频，区分源表错误与片段窗口可见范围差异。
- [ ] 定最终值：逐项给出定案值与依据（含与已确认片段相左的两项及 `video_0025` 关联备注）。
- [ ] 备份 CSV：改动前将 `data/annotation-table-full.csv` 备份至仓库外位置，并记录改前／改后 SHA-256。
- [ ] 占坑改表：按 `AGENTS.md` 全局共享只读项流程先开 Draft PR 占坑，再仅修改已定案字段与备注（保持 UTF-8 BOM、全 CRLF 与行序不变）。
- [ ] 核对连带影响：逐项落实「后续前置工作」，并在 `docs/changes/` 留存变更单后回填本节进展。

### 完成标准

- [ ] 全部 9 个来源、12 个字段级条目（含 `video_0025` 关联备注）复核完毕，每项有明确结论与可追溯依据。
- [ ] 若执行改表：具备仓外备份、改前后 SHA-256 记录，且改动范围严格限于定案字段与备注。
- [ ] 「后续前置工作」各项连带影响核对完毕，结论写入 `docs/changes/` 变更单。

### 后续前置工作

- **历史划分指纹保留**：`data/splits/three-fold/manifest.json` 的 `inputs."labels.csv".sha256` 记录的是 2026-11-19 生成划分时的历史指纹（`c928bea3…c1ec354c`），检查项 L1-02（见 [checks.md](checks.md)）当前为黄灯；改表后应保留历史划分清单，另在变更单与 `docs/facts.yaml` DF-033 追加新 CSV 指纹，不为消黄改写历史划分清单（当前已含开发集来源 `video_0043`、`video_0046`，正式改表时须评估是否重跑开发三折划分）。
- **源级统计与文档同步**：同步更新 [整体标签分布](label-distribution.md)、[划分设计](split/data-split-design.md)、[测评数据覆盖建议](research/evaluation-data-requirements.md) 与 `data/split-inputs/source-groups-20261107.json` 的来源指纹。
- **事实链与规则边界**：在 `docs/facts.yaml` DF-033 的标注表 SHA 链（`9970d259…` → `2f046b06…` → `c928bea3…`）追加新 SHA，不就地覆盖旧值；在变更单与 `docs/facts.yaml` 中显式写明 `docs/label.md` 与 DF-049 的「源标注层不动」仅指片段层删除「无」不连带改源表，而非禁止修正源表错标——**切勿为此顺手编辑 `docs/label.md`**（审核身份包含该文件字节哈希 `label_rules_sha256`，哪怕只改说明文字，重启审核服务后也会将全部 527 条现有确认记录归入历史）。
- **ROI 清单评估**：明确是否重扫 `data/roi/manifest.json`（重扫只刷标签快照与指纹、不重编码视频；不重扫则清单快照滞后），将取舍写入变更单。
- **红线（严禁重生成子视频）**：无论源表如何修正，**不得因此重生成 `data/sub_video/` 清单或重新生成已审片段**。单改 CSV 不会使已确认的 527 条审核记录失效；但改表后直接对当前批次跑 `--audit-only` 会因输入身份指纹不符而拒跑，复验当前批次须使用生成时的输入快照。

### 等待确认

1. 源层（按整片判）与片段层（按窗口判）两层各自独立的口径是否维持不变。
2. `video_0025`（`异常_视频异常`）与 `video_0041`（`现象_断后脱夹`）两项与已确认片段相左，以源表为准、以片段为准还是仅记差异。
3. 集中改表时点：建议待 B2／B3 全部审完、进入正式测评或训练冻结前一次性改表（B2 期间仅追加清单、不动源表），待用户确认。

### 限制与关联

- 本条只登记待办，不构成修改 `data/annotation-table-full.csv`、重生成媒体或重新审核的授权。
- 关联 [待修改原视频源标注字段](pending-source-relabels.md)、[§6 SUBVIDEO-HUMAN-REVIEW](#6-subvideo-human-review--人工审核新批次候选片段)、[§1 LABEL-ANNOTATION](#1-label-annotation--确认标签基准并进行人工标注)、[§4 DATA-HANDOFF](#4-data-handoff--梳理新标注到数据生成的衔接方案)、DF-033、DF-049。

---

## 1. LABEL-ANNOTATION — 确认标签基准并进行人工标注

**状态：** 已解决（2026-11-07）；本轮 110 条源视频标注、结果整理与材料类型补全已完成（后续术语统一于 2026-11-14 完成，6 处重标注于 2026-11-19 完成，当前 CSV SHA-256 为 `c928bea3…c1ec354c`；新发现的源表待改项由 [§8 SOURCE-RELABEL](#8-source-relabel--源标注待改清单与集中修正) 跟踪）。

### 完成结果

- 按用户确认的 [标签说明](label.md) 完成 110 条源视频五类标签标注；无法定位精确断裂帧的视频按 DF-013 记录时间上下界，不视为漏标。
- 第二轮成果位于 `data/`：[标注表](../data/annotation-table-full.csv) 及本地原视频目录 `data/videos/`（媒体不入 Git，目录约定见 [data/README.md](../data/README.md)），CSV 视频路径以项目根目录为基准；材料类型已按唯一视频 ID 和文件名从 `data/source/annotations/all_videos_tag.csv` 补全。
- 用户确认本轮无需维护旧原视频与旧子视频的对应关系。

### 历史验证记录（2026-11-07 本机基线）

以下为 2026-11-07 当时执行的完成范围记录（非当前 CSV 指纹，不作固定验收判据）：

- 基线 `5113c142bf7daa87d0f019e6f291a033034d2b37`：`csv.DictReader` 输出 `rows: 110`（有断裂 90、无断裂 4、无法判读 16），`all_new_paths_exist: True`、`all_paths_project_relative: True`；视频复制校验 `videos_hash_verified: 110`、`non_path_cells_equal: 2970`、`source_csv_unchanged: true`。
- 基线 `a54285cca53907b1e7d9f6fd9d7359c054a1b0ed`：回填材料类型空值 110 条后当时 CSV SHA-256 为 `d8ef6206da327971ad731ffcfdfeb31cfacc2c8c3775268cd1f38478cdbb6584`（后续版本演变见 `docs/facts.yaml` DF-033）。

### 限制与关联

- 「无法判读」是已填写的判断结果，其评价与训练用途已于 2026-11-14 按 [DEC-003](decisions/0003-five-label-eval-scope.md) 第 1 条确认；旧断裂帧数与旧派生字段存在冲突、未回填。
- 标注工具默认路径最初指向原表 `data/annotation/annotation-table-full.csv` 与 `data/source/videos`，已于提交 `9bfe34a` 切换为当前第二轮副本 `data/annotation-table-full.csv` 与 `data/videos`（见 `script/annotation/review_run_annotation.py`）。
- 标注 CSV、来源分组、划分清单与 ROI 非视频结果纳入 Git 管理（不等于已发布或已有独立备份）；视频媒体与运行锁继续忽略。
- 历史衔接追溯：此前约定为「数据重建、契约升级及代码适配待标签基准、输入和实施授权具备后另行安排」；当前已按 [§4 DATA-HANDOFF](#4-data-handoff--梳理新标注到数据生成的衔接方案) 阶段授权完成初裁与第 2 批候选生成，真实模型训练、测评与数据发布仍未获授权。旧 v4.1 材料留在原工作区供追溯。

---

## 附录：测评迁移计划删除前结论留档

2026-11-19 `docs/eval-migration-plan.md` 已删除；该文档自述「只写规格，不含代码」，规格仍未实现、迁移点判据① 未勾选，本仓 `script/` 无对应实现。以下保留删除前的结论原文留档（供 `docs/facts.yaml` DF-037 锚定追溯，不新建任务、不构成实施授权）：

本地 Mac | 链路梳理、输入与清单元数据、fake backend 切片验证、报告模板、判据与文档
本地产出永不作为测评结果
`fake` backend 的 `model_id` 固定为字符串 `fake`
命中 `fake` 即报错退出

---

**失效条件：** 当项目任务进度、生效数据批次、人工审核计数、关键决策或阻塞项发生变化时，须以当前仓库实测状态（含 `data/subvideo-review/reviews.json`、`docs/facts.yaml` 与 `docs/decisions/`）同步更新本台账；本文件不替代原始清单或审核记录作为数据源。
