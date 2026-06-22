# 模型微调侧设计文档

> 项目:mVllm-frame-interval-agent
> 模型:MiniCPM-V 4.6
> 日期:2026-06-11
> 状态:已过期
> 替代文档:[`docs/PROJECT_PLAN.md`](../../PROJECT_PLAN.md) v2

---

## 0. 文档地位与适用范围

本文档是 `mVllm-frame-interval-agent` 项目**模型微调侧**的设计文档,定义数据管道、训练样本构建、模型微调训练及模型侧配置参数。若本文与 `dataset_info.json`、训练 YAML、CSV 标注文件等权威配置不一致,以对应文件为准并优先修订本文。

断裂行为的视觉现象说明可参考 [`assets/frac_mode.md`](../../assets/frac_mode.md)，但训练标签仍以 CSV 原始字段及 canonical 派生字段为准。

本文只定义新 worktree 的帧区间迭代定位方案中**模型侧**的实现;旧 worktree 中"直接预测断裂时间与断裂模式"的方案仅作为对比基线,不在本文范围内继续扩展。

### 与其他文档的关系

- [`docs/architecture/agent_iteration_design.md`](./agent_iteration_design.md):定义 Agent 迭代控制器、评估体系及 Agent 侧配置。
- [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md):定义微调模型与 Agent 之间的接口契约,包括模型输出 JSON Schema、Tool Schema、Prompt 契约、索引/时间换算规则等。本文在涉及这些契约时仅做引用说明,详细定义以接口契约为准。

---

## 1. 项目概述

### 1.1 目标

训练一个基于多模态大模型的**帧区间判别模型**,并配合外部迭代控制器,逐步缩小视频断裂时间范围,最终定位材料拉伸试验视频的断裂时刻。

### 1.2 与旧方案的根本区别

| 维度 | 旧方案 | 新方案 |
|---|---|---|
| 预测方式 | 直接输出断裂秒数(回归/分类) | 输出"断裂发生在哪两帧之间"(区间判别) |
| 推理流程 | 单轮预测 | 多轮迭代,逐步收缩时间区间 |
| 信息利用 | 一次性观看全视频 | 每轮聚焦子区间,逐层定位 |
| 失败模式 | 偏差大时无修正机制 | 每轮有置信度,可提前终止或加权融合 |

核心思想:**不直接预测精确秒数,而是通过多轮问答让模型判断"断裂在哪两帧之间",外部 Agent 据此迭代缩小范围。**

### 1.3 成功标准

| 指标 | 目标 | 说明 |
|---|---|---|
| 区间命中率 | ≥ 80% | 预测区间包含真实断裂时间的比例 |
| within_1s | ≥ 60% | 点估计(区间中点)与真实时间误差 ≤ 1s |
| within_3s | ≥ 85% | 点估计与真实时间误差 ≤ 3s |
| within_5s | ≥ 95% | 点估计与真实时间误差 ≤ 5s |
| type macro-F1 | ≥ 0.75 | 断裂类型(韧性/脆性等)分类性能 |
| location 准确率 | ≥ 0.70 | 标距内/外判断准确率,仅在 location != N/A 子集上计算 |

---

## 2. 技术决策记录(ADR)

以下决策已与项目团队确认,记录如下:

| 决策项 | 选定方案 | 理由 |
|---|---|---|
| 子视频存储 | **独立 `.mp4` 子视频为模型微调训练主产物,帧图仅作为采样映射/调试缓存** | 微调样本直接使用子视频地址作为 `videos` 输入,训练格式更简洁;训练子视频的核心作用是让断裂时刻在片段中的位置更均匀,避免模型只学到"断裂集中在视频后段"的偏置。Agent 推理阶段不复用训练集子视频,而是基于原始视频和当前 `sample_range` 动态生成临时推理片段 |
| `location` 标注 | 直接读取 CSV 的 `断裂位置` 字段,N/A 保留为 `"N/A"` | CSV 已补全,`inside_gauge`/`outside_gauge`/`N/A` 可直接使用;N/A 用于异常/未断裂样本 |
| 断裂帧号 | 直接读取 CSV 的 `断裂帧数` 作为 `event_frame_original`,不再用 `round(event_time × fps)` 覆盖 | CSV 中的 `断裂帧数` 为权威值,已人工填实;仅在无法解析时留空 |
| 训练框架 | **LLaMA-Factory** | 团队已熟悉该框架,现有基础设施(环境、配置模板、训练脚本)可直接复用 |
| 划分策略 | **按原始视频划分 + 3-fold 交叉验证** | 保证同一原始视频的所有子视频不跨训练/验证/测试集合,避免数据泄漏 |
| 旧代码处理 | **旧方案冻结保留为 baseline,不继续扩展;新实现走独立 pipeline** | 旧 `data/04_merged` 与可跑 YAML 保留作对比基线;新 interval 数据管道输出到 `data/04_new_merged`,通过切换 `dataset` 键名即可在新旧数据之间切换 |

---

## 3. 数据管道

### 3.1 元数据管理

**输入**

- `data/02_annotations/all_videos_tag.csv`:原始标注 CSV,共 110 条记录、13 列,所有字段均已填满。关键列映射如下:
  - `id` → `video_id`
  - `video_path` → `video_path`
  - `断裂时间点` → `event_time`(可解析为数字时,单位为秒;不可解析时保留原字符串)
  - `断裂模式` → `type`
  - `材料类型` → `material_type`
  - `清晰度` → `resolution`
  - `断裂位置` → `location`(`inside_gauge` / `outside_gauge` / `N/A`)
  - `断裂帧数` → `event_frame_original`(权威帧号,不再用公式覆盖)
  - `视频时长` / `视频帧率` / `视频总帧数` → 与 ffprobe 提取值交叉校验
  - `has_fracture` / `is_abnormal` → 直接读取 CSV 同名列
- `data/01_videos/*.mp4`:原始视频文件

**处理流程**

1. 读取视频元信息:使用 `ffprobe` 或 OpenCV (`cv2`) 提取 `fps`, `total_frames`, `duration`
2. 读取断裂帧号:直接采用 CSV 的 `断裂帧数` 字段作为 0-based `event_frame_original`;导入时按上述第 6 步抽样校验;若该字段为 N/A 或不可解析,则置为 `null`
3. 读取 `location`:直接采用 CSV 的 `断裂位置` 字段(`inside_gauge` / `outside_gauge` / `N/A`)
4. 读取附加字段:将 CSV 的 `材料类型` 映射为 `material_type`,`清晰度` 映射为 `resolution`
5. 异常标记:根据 `type` 字段识别未断裂、未夹紧、视频异常等样本,标记 `is_abnormal`
6. **0-based 帧号校验**:CSV `断裂帧数` 声称采用 0-based 索引,导入时必须抽样核对视频帧
   - 对少量样本(建议 ≥5 条,覆盖不同视频)使用 `cv2` / `ffmpeg` 抽取 `event_frame_original` 帧并人工/自动检查该帧是否确实为断裂帧(或断裂前一帧)。
   - 若 `event_frame_original` 指向断裂后一帧或明显偏移,记录验证结论并决定是否对全部样本做 `-1` 偏移修正。
   - 校验结论写入 `data/metadata/frame_index_validation.json`:包含抽样视频 ID、`event_frame_original`、校验方式、0/1-based 判定结论、修正偏移量。

**输出**

- `data/metadata/video_meta.json`:结构化元数据文件

Schema(单条记录)见第 5.1 节。

**标签映射规则**

1. `has_fracture`:直接读取 CSV 的 `has_fracture` 列。作为一致性校验,当 CSV 的 `断裂时间点` 可解析为数字时间 **且** `断裂帧数` 可解析为整数时,期望 `has_fracture = true`;`type` 为 `未断裂`、`未夹紧`、`视频异常` 等模式时通常对应 `has_fracture = false`。若出现不一致,按 CSV 原值保留并由后处理模块记录警告。
2. `is_abnormal`:优先直接读取 CSV 的 `is_abnormal` 字段。当前 CSV 中 `is_abnormal = TRUE` 的样本,其 `type` 均为 `未断裂`、`未夹紧` 或 `视频异常`;仅 `video_0064` 例外(`type=视频异常` 但 `is_abnormal=FALSE`),按 CSV 原值保留。
3. `event_time`:CSV `断裂时间点` 可解析为数字时,转换为 float(秒);不可解析时保留原字符串或置为 `null`,由下游模块按需处理。

---

### 3.2 子视频生成与训练样本构建

> **本模块为最复杂模块**,负责原始视频划分、子视频裁剪、帧采样标签计算、训练格式转换。

**输入**

- 第 3.1 节输出:`data/metadata/video_meta.json`
- 原始视频:`data/01_videos/*.mp4`

#### Step 1 - 原始视频划分

**目标划分(新 interval 方案)**

1. **测试集划分**:按原始视频级别,随机抽取 20% 作为 Test 集(`test_ratio = 0.2`),分层变量优先为 `type + location`。
2. **训练集内 3-fold**:剩余 80% 视频进行 stratified 3-fold,分层变量同样优先为 `type + location`（3-fold 仅在剩余 80% 训练集内进行，test 集不参与 3-fold）。
3. **稀有 strata 处理**:若按 `type + location` 划分导致某些 strata 样本数 ≤2(稀有 `type` 或稀有 `type+location` 组合),采用以下策略避免 strata 过小或数据泄漏:
   - **合并稀有层**:将样本数 ≤2 的 `type+location` 组合合并为 `rare_fracture` / `other_fracture` 等虚拟层,仅用于划分,不改变模型输出标签;
   - **降级为仅按 `type` 分层**：若合并后仍过于稀疏，则退化为仅按 `type`（全局共 10 类：7 个断裂类 `韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂` + 3 个非断裂/异常类 `未断裂`、`未夹紧`、`视频异常`）进行分层；
   - **人工固定 + 剩余分层**:对极少量无法合并的稀有样本,人工指定其归属(如固定到 test 或某一 fold),剩余样本再按上述规则分层。
4. **N/A location 单独成层**:所有 `location = N/A` 的原始视频(无断裂/异常)单独作为一个 strata,不参与 `type + location` 的组合分层。
5. **标签生成**:每个原始视频标记以下标签之一:
   - `test`
   - `fold_0_train` / `fold_0_val`
   - `fold_1_train` / `fold_1_val`
   - `fold_2_train` / `fold_2_val`

> **划分原则**:同一原始视频的所有子视频必须归属同一集合,禁止跨集合泄漏;稀有/合并层仅服务于划分,不影响下游 `type` / `location` 标签。

**当前基线(与仓库实现一致)**

- 当前可跑 YAML 与 `dataset_info.json` 使用 `data/04_merged/stratified_3_fold_{0,1,2}_{train,val}.json`,无独立 test 集,按材料类型做 3-fold train/val 划分。
- 新 interval 数据管道落地前,继续沿用 `data/04_merged` 与 `tensile_video_3k*` dataset_info 作为基线。

**迁移路径(新 interval 方案)**

1. 实现新的 `dataset_manager.py`,输出:
   - `data/04_new_merged/fold_{0,1,2}_{train,val}.json`
   - `data/04_new_merged/test.json`
   - `data/04_new_merged/samples_meta.json`
2. 在 `finetune/dataset_info.json` 中注册新的 dataset 键名(如 `tensile_video_interval_fold0_train` 等),并指向 `data/04_new_merged`。
3. 新划分以 `type + location` 分层,`location = N/A` 的异常样本单独成层。
4. 旧 `data/04_merged` 数据保留作为基线对比,不删除;训练 YAML 通过切换 `dataset` 键名即可在新旧数据之间切换。

> **不变量3 / 新旧方案 test split 一致性强约束**：旧方案必须复用新方案的 video-level test split 重新生成或过滤测试输入；新旧对比只能在相同的 `video_id` 集合上进行，不允许旧方案使用自己的 test split 或全量数据。若旧 baseline 当前无独立 test 集，则需通过新方案的 test split 过滤其输出后计算指标。

#### Step 2 - 子视频类型(7 种)

所有子视频均从原始视频中截取,共 7 种类型(全时长按父视频是否断裂分为正/负两种情形)。为避免模型输出 JSON 与父视频真实信息混淆,训练样本额外记录父视频 metadata:`source_type`、`source_location`。

**当前片段 `type` / `location` 基本规则**:
- 当前片段 `has_fracture = true`:`type` 必须为父视频 CSV 中的 7 个断裂类别之一（`韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂`），不得为 `未断裂` / `未夹紧` / `视频异常`；`location` 为 `inside_gauge` / `outside_gauge` / `N/A`。若父视频 `has_fracture=true` 但 `type` 属于非断裂/异常类，应作为数据一致性错误记录。
- 当前片段 `has_fracture = false`:`type` 只能取 `未断裂` / `未夹紧` / `视频异常` 之一,`location` 一律为 `"N/A"`。

| 类型 | 说明 | `has_fracture` | `type` / `location`(当前片段) | `source_type` / `source_location`(父视频) | 配置参数 |
|---|---|---|---|---|---|
| 1a. **全时长 - 正样本** | 原始视频本身,父视频包含断裂 | true | 父视频 CSV 中的 7 个断裂类别之一（不得为 `未断裂` / `未夹紧` / `视频异常`） | 同父视频 CSV | - |
| 1b. **全时长 - 负样本** | 原始视频本身,父视频无断裂 | false | CSV 原值(`未断裂` / `未夹紧` / `视频异常`)/ `N/A` | 与 `type` / `location` 一致 | - |
| 2. **局部聚焦 - 短窗口** | 围绕断裂帧,窗口 3s,断裂点位于子视频内不同位置 | true | 父视频 CSV 中的 7 个断裂类别之一 / 位置 | 同父视频 CSV | `focus_windows[0] = 3` |
| 3. **局部聚焦 - 中窗口** | 同上,窗口 10s | true | 父视频 CSV 中的 7 个断裂类别之一 / 位置 | 同父视频 CSV | `focus_windows[1] = 10` |
| 4. **局部聚焦 - 长窗口** | 同上,窗口 30s | true | 父视频 CSV 中的 7 个断裂类别之一 / 位置 | 同父视频 CSV | `focus_windows[2] = 30` |
| 5. **负样本 - 断裂前** | 断裂时刻之前片段(如断裂前 5s ~ 断裂前 1s) | false | `未断裂` / `N/A` | 父视频 CSV 真实断裂类型 / 位置 | `neg_before_duration = 5` |
| 6. **负样本 - 断裂后** | 断裂时刻之后片段(如断裂后 1s ~ 断裂后 5s) | false | `未断裂` / `N/A` | 父视频 CSV 真实断裂类型 / 位置 | `neg_after_duration = 5` |
| 7. **负样本 - 无断裂视频** | `has_fracture = FALSE` 的视频的任意片段 | false | CSV 原值(`未断裂` / `未夹紧` / `视频异常`)/ `N/A` | 与 `type` / `location` 一致 | - |

**当前片段 `type` / `location` 与父视频 `source_type` / `source_location` 的区分**

- 模型输入/输出层面的 `type` / `location` **仅描述当前片段**:
  - 当前片段包含断裂（正样本 / 全时长正样本）：`type` 必须且只能取 7 个断裂类之一：`韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂`；`location` 为 `inside_gauge` / `outside_gauge` / `N/A`。
  - 当前片段不包含断裂(人工负样本 / 无断裂视频):`type` 为 `未断裂` / `未夹紧` / `视频异常` 之一,`location` 为 `N/A`。
- 父视频真实断裂信息仅保存在训练 metadata 的 `source_type` / `source_location` 中,**不进入模型输出 JSON**。详见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 2.6 节。

**异常样本与 `location = N/A` 的处理**

- `is_abnormal = TRUE` 的样本(如 `未断裂`、`未夹紧`、`视频异常`):不生成局部聚焦子视频和断裂前后负样本,仅保留全时长样本作为异常类别训练;全时长样本的 `has_fracture` 按 CSV 填写,`fracture_between` 为 `null`。
- `location = N/A` 的样本:不生成 location 监督信号,但 `has_fracture`/`type` 仍参与训练;location 相关评估仅在 `location != N/A` 子集上计算。

**局部聚焦窗口的位置比例**

断裂点在子视频中的位置比例可取以下 5 个值:

- `focus_positions = [0.2, 0.35, 0.5, 0.65, 0.8]`

即:对于窗口大小 `W` 和帧率 `fps`,先以权威帧号 `event_frame_original` 为中心计算帧范围 `[event_frame_original - round(W * ratio * fps), event_frame_original + round(W * (1 - ratio) * fps)]`,再换算为时间范围 `[start_frame / fps, end_frame / fps]` 用于截取子视频。若 `event_frame_original` 不可解析,则跳过局部聚焦子视频生成。

> 窗口大小和位置比例均可通过 YAML 配置调整。

#### Step 3 - 子视频生成

- 使用 `ffmpeg` 或 OpenCV 按时间区间截取独立 `.mp4` 子视频。
- 主产物为**子视频文件**,统一路径前缀:`data/02_subvideos/{video_id}_{crop_type}_{idx}.mp4`
- 命名示例:`data/02_subvideos/video_0001_focus_3s_50pct.mp4`
- 帧图目录 `data/03_frames/{video_id}_{crop_type}_{idx}/frame_{:04d}.jpg` 仅作为标签计算、推理映射或人工调试缓存,不是训练主输入。
- `data/02_subvideos` 是模型微调训练数据产物;Agent 推理阶段基于原始视频动态生成当前轮次的临时推理片段,不依赖训练集中的子视频文件。
- 记录子视频元数据(见第 5.2 节)

#### Step 4 - 帧采样与标签计算

对每个子视频执行以下操作:

1. **按 LLaMA-Factory 视频解码规则确定实际采样帧数**:`video_maxlen = 36` 为上限,`video_fps = 8.0` 为默认采样帧率(均可配置)。对时长为 `duration` 的子视频,实际送入模型的帧数为:
   ```text
   N = min(total_frames_in_subvideo, video_maxlen, max(1, floor(duration * video_fps)))
   ```
   例如 3s 子视频在默认 `video_fps=8.0` 下实际采样 `N=24` 帧,10s/30s 子视频受 `video_maxlen=36` 限制实际采样 36 帧。
   - 由于训练视觉输入是 `.mp4` 子视频,`fracture_between` 的索引必须对应 LLaMA-Factory 实际送入模型的采样帧序列;数据构造器的采样规则需与训练/推理解码规则保持一致。
2. **计算每个采样帧的对应信息**:
   - `sampled_frame[i].input_index`:采样序号,从 0 开始,到 `N - 1`。
   - `sampled_frame[i].original_frame`:该采样帧在原始视频中的全局帧号,**0-based**。
   - `sampled_frame[i].timestamp`:该采样帧在原始视频中的时间戳(秒)。
   - `sampled_frame[i].frame_path`:该采样帧对应的可选图文件路径,用于标签计算、调试与推理侧映射;训练视觉输入以 `video_path` 指向的 `.mp4` 子视频为准。
3. **窗口裁剪与边界处理**:
   - 子视频时间范围换算为帧范围后,必须 clamp 到 `[0, total_frames - 1]`。
   - 实际采样只发生在有效帧上;若目标区间超出视频边界,越界部分仅保留到边界帧,且 `input_index` 仍连续编号。
   - 等价规则:`original_frame[k]` 计算后 clamp 到 `[0, total_frames - 1]`,保证所有采样帧映射到有效原视频帧。
4. **计算 `fracture_between`**:设 `event_frame_original` 为 CSV 读取的 0-based 断裂帧号(有效范围 `[0, total_frames - 1]`),按以下规则确定 `fracture_between = [i, i+1]`:
   - **正常区间**:找到唯一 `i`(`0 <= i < N - 1`)使得 `original_frame[i] <= event_frame_original < original_frame[i+1]`,则 `fracture_between = [i, i+1]`。
   - **越界前段**:若 `event_frame_original < original_frame[0]`,取 `fracture_between = [0, 0]`。
   - **越界末段**:若 `event_frame_original >= original_frame[N-1]`,取 `fracture_between = [N-1, N-1]`。
   - **恰好命中采样帧**:若 `event_frame_original == original_frame[i]` 且 `i > 0`,取左侧区间 `fracture_between = [i-1, i]`;若 `i = 0`,按越界前段取 `[0, 0]`。
5. **负样本**:`has_fracture = false`,`fracture_between = null`。

#### Step 5 - 训练格式转换(LLaMA-Factory 对话格式)

将每个子视频转换为一个 LLaMA-Factory 多模态对话样本。示例见第 5.3 节。

**输出文件清单**

| 文件 | 路径 | 说明 |
|---|---|---|
| 子视频文件(主产物) | `data/02_subvideos/{video_id}_{crop_type}_{idx}.mp4` | 每个片段对应的独立视频文件;训练样本 `videos` 字段直接引用该路径 |
| 帧图目录(可选缓存) | `data/03_frames/{video_id}_{crop_type}_{idx}/frame_{:04d}.jpg` | 用于标签计算、推理侧映射或人工调试;不是训练主输入 |
| 训练 JSON(当前基线) | `data/04_merged/stratified_3_fold_{0,1,2}_{train,val}.json` | 当前可跑 YAML 使用的 3-fold 训练/验证集,无 test 集;旧方案冻结保留 |
| 训练 JSON(新 interval 方案) | `data/04_new_merged/fold_{0,1,2}_{train,val}.json` | 目标 3-fold 训练/验证集 |
| 测试 JSON(新 interval 方案) | `data/04_new_merged/test.json` | 目标 20% 测试集 |
| 样本元数据 | `data/04_new_merged/samples_meta.json` | 所有样本的元信息索引 |

---

### 3.3 Prompt 设计与训练配置

#### Prompt 设计规范

微调模型在**训练与推理阶段使用同一套 System Prompt 模板**,由 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 6.1 节统一定义。System Prompt 固定,训练时由**数据构造器**写入每条样本的 `messages[0]`;Agent 侧仅在 System Prompt 之上追加动态构建的 user prompt。

训练样本的 user prompt 由数据构造器根据片段类型动态生成,模拟 Agent 会发送的 prompt 分布:

- **正片段(`has_fracture = true`)**:user prompt 包含当前区间的时间范围、采样帧数,并要求输出 `has_fracture`、`fracture_between`、`type`、`location`、`confidence`。
- **负片段(`has_fracture = false`)**:user prompt 要求判断是否存在断裂;若不存在,则 `type` 只能取 `未断裂` / `未夹紧` / `视频异常` 之一,`location` 为 `N/A`。

无论哪种片段,System Prompt 均保持不变,user prompt 必须包含 `<video>` 视觉占位符,占位符数量须与 `videos` 字段长度一致(本方案每个样本仅含一个视频片段,对应 `videos` 中的一个 `.mp4` 子视频路径),并在其后描述任务。具体要素如下:

1. **视觉占位符**:`content` 中必须包含 `<video>`,与输入模型的子视频路径一一对应。
2. **角色设定**:明确模型的身份("你是一个材料拉伸试验视频分析助手")。
3. **任务描述**:当前需要分析什么("请判断这段视频是否包含断裂")。
4. **输入说明**:当前区间的时间范围、帧数等。
5. **输出格式要求**:严格合法的 JSON schema,包含 `has_fracture`、`fracture_between`、`type`、`location`、`confidence` 字段。

> 注:Agent 在推理时可根据当前迭代阶段调整 **user prompt** 的措辞和重点(例如初期侧重"有无断裂",后期侧重"精确边界"),但**不得修改 system prompt**。完整 Prompt 契约见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 6 节。

#### LLaMA-Factory YAML 配置要点

以下 YAML 示例与当前可跑配置 `finetune/MiniCPM/config/minicpmv4_6_lora_sft_fold0.yaml` 保持一致;实际训练时以该文件为准。

```yaml
# === model ===
model_name_or_path: ../models/minicpm-v-4.6
cache_dir: null
trust_remote_code: true
flash_attn: fa2

# === method ===
stage: sft
do_train: true
do_eval: true
finetuning_type: lora
lora_rank: 16
lora_alpha: 32
lora_dropout: 0.1
quantization_bit: 4

# === dataset ===
dataset: tensile_video_3k0_train  # 在 dataset_info.json 中注册;3-fold 时每折切换
eval_dataset: tensile_video_3k0_val  # 对应 fold 的验证集键名
dataset_dir: ../finetune
template: minicpm_v_4_6
video_fps: 8.0    # 视频采样帧率超参数,后续可通过消融实验调整
video_maxlen: 36  # 视频采样帧数上限;实际帧数 N = min(total_frames, video_maxlen, max(1, floor(duration * video_fps)))
cutoff_len: 8192
media_dir: ../data
preprocessing_num_workers: 4
overwrite_cache: true

# === output ===
output_dir: ../LlamaFactory/saves/minicpmv4_6/lora/sft_3k0
save_strategy: epoch
eval_strategy: epoch
load_best_model_at_end: true
metric_for_best_model: eval_loss
greater_is_better: false

# === train ===
per_device_train_batch_size: 1
gradient_accumulation_steps: 16
learning_rate: 1.5e-5
num_train_epochs: 8
lr_scheduler_type: cosine
warmup_ratio: 0.05
bf16: true
```

#### dataset_info.json 注册

训练样本使用 `messages` + `role` / `content` + `videos` 格式。在 LLaMA-Factory 的 `dataset_info.json` 中注册如下(当前基线已采用相同字段映射):

```json
{
  "tensile_video_3k0_train": {
    "file_name": "../data/04_merged/stratified_3_fold_0_train.json",
    "folder": "../data/04_merged",
    "formatting": "sharegpt",
    "columns": {
      "messages": "messages",
      "videos": "videos"
    },
    "tags": {
      "role_tag": "role",
      "content_tag": "content",
      "user_tag": "user",
      "assistant_tag": "assistant"
    }
  }
}
```

> **注意**:
> - 3-fold 训练时,每折需分别切换 `dataset` 与 `eval_dataset` 为对应 fold 的训练/验证集键名(如 `tensile_video_3k0_train` / `tensile_video_3k0_val`)。
> - 新 interval 方案落地后,在 `dataset_info.json` 中新增 `tensile_video_interval_fold{i}_{train,val}` 键名,指向 `data/04_new_merged`。

#### 训练数据 confidence 标注规范

与 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 2.4 节保持一致:

- **Ground truth 样本**:所有训练样本的 `confidence` 均标注为 `1.0`,即假设人工标注和 CSV 读取标签是确定的。
- **负样本**:`has_fracture: false` 的样本同样标注 `confidence: 1.0`,表示"该片段确实不包含断裂"是确定事实。
- 模型在推理时自报的 `confidence` 反映其对当前输入的主观不确定性,与训练标签的 `1.0` 含义不同。

`confidence` 字段仅出现在 assistant 输出的 JSON 字符串中,不作为额外监督信号使用。

#### 模型输出 JSON

微调模型在推理时的输出 JSON Schema 定义见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 2 节。示例仅在接口契约文件中保留,避免重复。

**负样本 `type` / `location` 与父视频 `source_type` / `source_location` 规则**

与 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 2.5、2.6 节保持一致:

- **当前片段 `has_fracture = false` 且父视频本身无断裂**(全时长异常样本):
  - 模型输出 JSON 中的 `type` 仅允许 `未断裂` / `未夹紧` / `视频异常` 三者之一(不允许使用 `none`)；训练标签由样本构造器决定:真实无断裂/异常样本保留其 CSV 标注。
  - `source_type` / `source_location` 与 `type` / `location` 一致。
- **当前片段 `has_fracture = false` 但来自 `has_fracture = true` 的父视频**(断裂前/后人工负样本子片段):
  - 模型输出 JSON 中的 `type` 必须为 `未断裂` / `未夹紧` / `视频异常` 之一;若父视频为正常断裂视频,人工负片段统一使用 `未断裂`。`location` 必须为 `"N/A"`。
  - 父视频真实断裂类型/位置仅保存在训练 metadata 的 `source_type` / `source_location` 中,**不进入模型输出 JSON**。

---

### 3.4 模型微调训练

**训练流程**

1. **3-fold 独立训练**:对每一折分别执行完整训练流程
   - 当前基线:Fold 0 使用 `data/04_merged/stratified_3_fold_0_train.json` 训练,`data/04_merged/stratified_3_fold_0_val.json` 验证;其余两折类推。
   - 新 interval 方案:Fold 0 使用 `data/04_new_merged/fold_0_train.json` 训练,`data/04_new_merged/fold_0_val.json` 验证;其余两折类推。

2. **Checkpoint 保存路径**:
   ```
   LlamaFactory/saves/minicpmv4_6/lora/sft_3k0/
   LlamaFactory/saves/minicpmv4_6/lora/sft_3k1/
   LlamaFactory/saves/minicpmv4_6/lora/sft_3k2/
   ```

3. **验证策略**:每轮 epoch 后在验证集上评估 JSON 输出准确率,保存最佳 checkpoint。

---

## 4. 数据 Schema(模型侧)

### 4.1 video_meta.json(单条记录)

```json
{
  "video_id": "video_0001",
  "video_path": "data/01_videos/video_0001.mp4",
  "fps": 30.0,
  "total_frames": 15000,
  "duration": 500.0,
  "event_time": 145.4,
  "event_frame_original": 4362,
  "type": "韧性断裂",
  "location": "inside_gauge",
  "material_type": "金属",
  "resolution": "480P",
  "has_fracture": true,
  "is_abnormal": false
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `video_id` | string | 视频唯一标识 |
| `video_path` | string | 原始视频文件路径 |
| `fps` | float | 视频帧率 |
| `total_frames` | int | 总帧数 |
| `duration` | float | 视频时长(秒) |
| `event_time` | float / string / null | 标注断裂时刻(秒);CSV `断裂时间点` 可解析为数字时为 float,否则保留原字符串或置为 null |
| `event_frame_original` | int / null | CSV 中的 `断裂帧数`;可解析时为 int,否则为 null |
| `type` | string | 断裂模式,取值须为 CSV 实际枚举之一(共 10 个,组合标签作为独立类别) |
| `location` | string | 标距内/外位置:`inside_gauge` / `outside_gauge` / `N/A` |
| `material_type` | string | 材料类型(CSV `材料类型`) |
| `resolution` | string | 视频清晰度(CSV `清晰度`) |
| `has_fracture` | bool | 是否发生断裂 |
| `is_abnormal` | bool | 是否为异常样本 |

### 4.2 子视频元数据(单条)

```json
{
  "subvideo_id": "video_0001_focus_3s_50pct",
  "source_video": "video_0001",
  "video_path": "data/02_subvideos/video_0001_focus_3s_50pct.mp4",
  "frame_paths": [
    "data/03_frames/video_0001_focus_3s_50pct/frame_0000.jpg",
    "..."
  ],
  "start_time": 143.9,
  "end_time": 146.9,
  "duration": 3.0,
  "crop_type": "focus_short",
  "event_position_ratio": 0.5,
  "has_fracture": true,
  "fracture_between": [17, 18],
  "type": "韧性断裂",
  "location": "inside_gauge",
  "source_type": "韧性断裂",
  "source_location": "inside_gauge",
  "fold": "fold_0_train",
  "split": "train"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `subvideo_id` | string | 子视频/片段唯一标识 |
| `source_video` | string | 来源原始视频 ID |
| `video_path` | string | **主产物**:独立 `.mp4` 子视频路径,训练样本 `videos` 字段直接引用该路径 |
| `frame_paths` | list[string] / null | 可选采样帧图路径列表,用于标签计算、推理映射或调试;不是训练主输入 |
| `start_time` | float | 在原始视频中的起始时间(秒) |
| `end_time` | float | 在原始视频中的结束时间(秒) |
| `duration` | float | 子视频时长(秒) |
| `crop_type` | string | 裁剪类型(见第 3.2 节 Step 2) |
| `event_position_ratio` | float/null | 断裂点在子视频中的位置比例 |
| `has_fracture` | bool | 当前片段是否包含断裂 |
| `fracture_between` | `[int, int]` / null | 当前片段内断裂区间;负样本为 `null` |
| `type` | string | 当前片段的 `type`；`has_fracture = true` 时为 7 个断裂类之一：`韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂`；`has_fracture = false` 时为 `未断裂` / `未夹紧` / `视频异常` |
| `location` | string | 当前片段的 `location`(`inside_gauge` / `outside_gauge` / `N/A`) |
| `source_type` | string | 父视频真实断裂类型(`has_fracture = true` 父视频)或当前片段 type(无断裂父视频) |
| `source_location` | string | 父视频真实断裂位置(`has_fracture = true` 父视频)或 `"N/A"` |
| `fold` | string | 所属 fold 及集合 |
| `split` | string | `train` / `val` / `test` |

### 4.3 训练样本(LLaMA-Factory 格式)

训练样本使用 `messages` + `role` / `content` + `videos` 格式,System Prompt 固定,user prompt 由数据构造器动态生成。`source_type` / `source_location` 作为样本 metadata 附加在顶层,不进入 `messages`。

```json
{
  "id": "video_0001_focus_3s_50pct",
  "videos": [
    "data/02_subvideos/video_0001_focus_3s_50pct.mp4"
  ],
  "messages": [
    {
      "role": "system",
      "content": "你是一个材料拉伸试验视频分析助手。你的任务是分析给定的视频片段,判断试样是否发生断裂。\n\n如果存在断裂,请回答:\n1. 断裂发生在哪两帧之间(用帧索引表示,如 [17, 18])\n2. 断裂模式(若存在断裂,has_fracture=true,type 只能从 7 个断裂类中选:韧性断裂;脆性断裂;界面脱粘;齐根断裂;爆炸性断裂;半脆半韧断裂;界面脱粘、齐根断裂。其中组合标签 `界面脱粘、齐根断裂` 作为独立类别,与单独的 `界面脱粘`、`齐根断裂` 不同。若不存在断裂,has_fracture=false,type 只能从 3 个非断裂/异常类中选:未断裂;未夹紧;视频异常)\n3. 断裂位置是否在标距内(inside_gauge / outside_gauge / N/A)\n4. 你对判断的置信度(confidence,0.0 ~ 1.0 的浮点数)\n\n如果判断不存在断裂,has_fracture 为 false,fracture_between 为 null,type 只能取 `未断裂` / `未夹紧` / `视频异常` 三者之一(不允许输出 `none`;根据当前片段内容判断取值),location 填 \"N/A\",confidence 仍需给出(表示你对\"无断裂\"判断的置信度)。\n\n输出必须为严格合法的 JSON 格式,不要包含任何其他解释文字。confidence 字段为必填项。\n输出 Schema:{\"has_fracture\": bool, \"fracture_between\": [int, int]或null, \"type\": str, \"location\": str, \"confidence\": float}"
    },
    {
      "role": "user",
      "content": "<video>\n请分析这段拉伸试验视频,判断是否存在断裂。当前区间为 [143.9, 146.9] 秒,按 video_fps=8.0 与 video_maxlen=36 实际采样 24 帧。"
    },
    {
      "role": "assistant",
      "content": "{\"has_fracture\": true, \"fracture_between\": [17, 18], \"type\": \"韧性断裂\", \"location\": \"inside_gauge\", \"confidence\": 1.0}"
    }
  ],
  "has_fracture": true,
  "fracture_between": [17, 18],
  "source_type": "韧性断裂",
  "source_location": "inside_gauge"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 样本唯一标识 |
| `videos` | list[string] | 视觉输入:子视频 `.mp4` 路径列表。每个元素对应 `content` 中的一个 `<video>` 占位符;本方案每个样本通常只有一个子视频路径 |
| `messages` | list[dict] | `role` / `content` 对话列表,必须包含 `system`、`user`、`assistant` |
| `has_fracture` | bool | 当前片段是否包含断裂(metadata) |
| `fracture_between` | `[int, int]` / null | 当前片段内断裂区间(metadata) |
| `source_type` | string | 父视频真实断裂类型;正片段与 `type` 相同,人工负片段保留父视频信息 |
| `source_location` | string | 父视频真实断裂位置;正片段与 `location` 相同,人工负片段保留父视频信息 |

---

## 5. 配置参数(模型侧)

所有可配置参数集中管理,建议通过 YAML 文件(如 `config/frame_interval.yaml`)维护。本节仅列出与模型侧直接相关的参数:

| 参数名 | 默认值 | 说明 |
|---|---|---|
| `video_fps` | 8.0 | LLaMA-Factory 视频采样帧率超参数;后续可通过消融实验调整 |
| `video_maxlen` | 36 | LLaMA-Factory 的视频采样帧数上限;实际帧数 `N = min(total_frames, video_maxlen, max(1, floor(duration * video_fps)))` |
| `cutoff_len` | 8192 | LLaMA-Factory 的 `cutoff_len` |
| `focus_windows` | `[3, 10, 30]` | 局部聚焦窗口大小列表(秒) |
| `focus_positions` | `[0.2, 0.35, 0.5, 0.65, 0.8]` | 断裂点在子视频中的位置比例 |
| `neg_before_duration` | 5 | 断裂前负样本片段长度(秒) |
| `neg_after_duration` | 5 | 断裂后负样本片段长度(秒) |
| `test_ratio` | 0.2 | 目标测试集占原始视频比例(当前基线无独立 test 集) |
| `n_folds` | 3 | 交叉验证折数 |
| `dataset_manager_output` | `data/04_new_merged/` | 新 interval 方案生成的训练/验证/测试 JSON 输出目录;当前基线使用 `data/04_merged/` |

> Agent 侧配置参数(如 `max_rounds`、`tolerance_seconds`、`agent.backend` 等)见 [`docs/architecture/agent_iteration_design.md`](./agent_iteration_design.md) 第 6 节。

---

## 6. 实现顺序与里程碑

| 阶段 | 时间 | 负责模块 | 交付物 | 验收标准 |
|---|---|---|---|---|
| **Phase 1** | Week 1 | 元数据管理 + 子视频生成与训练样本构建 | `video_meta.json`、子视频 `.mp4` 文件、可选帧图缓存、训练/测试 JSON | 所有子视频生成完毕,JSON 格式通过 LLaMA-Factory 数据加载验证 |
| **Phase 2** | Week 2 | Prompt 设计与训练配置 + 模型微调训练 | YAML 配置、`dataset_info.json`、3 个 fold 的 checkpoint | 每折训练 loss 收敛,验证集上 JSON 可解析率 > 95% |

> Phase 3-4(Agent 迭代与评估)见 [`docs/architecture/agent_iteration_design.md`](./agent_iteration_design.md) 第 7 节。

---

## 7. 风险与待办(数据/训练侧)

| 风险项 | 影响 | 缓解措施 | 状态 |
|---|---|---|---|
| `location` 已补全但含 N/A | location 准确率需在 `location != N/A` 子集上计算,N/A 样本不参与 location 评估 | 显式过滤 N/A;若需 location 全量评估,需额外标注策略 | 🟢 已解决 |
| `event_frame_original` 来源变更 | 由 CSV `断裂帧数` 直接读取,不再自动计算;不可解析时置为 null | 依赖 CSV 质量;读取时校验可解析性,异常值在日志中显式记录 | 🟢 已解决 |
| 子视频磁盘空间膨胀 | 110 个原视频 × 多窗口 × 多位置 × 负样本,存储可能达数十 GB | 监控 `data/02_subvideos/` 目录大小;必要时压缩或清理可选帧图缓存 | 🟡 需监控 |
| LLaMA-Factory 子视频读取性能 | 大量独立 `.mp4` 文件可能导致 I/O 瓶颈 | Phase 1 后期做小批量训练测试,若性能不足则评估更高效的视频缓存或解码方案 | 🟡 待验证 |
| 局部聚焦窗口超参调优 | 窗口大小直接影响模型判断难度 | 先按默认值启动,Phase 4 通过消融实验确定最优配置 | 🟢 已知 |
| 3-fold 训练时间 | 每折需独立训练,总时间可能较长 | 评估单折训练耗时后决定是否并行化(多 GPU) | 🟡 待评估 |

### 待办清单

- [x] 确认 MiniCPM-V 4.6 在 LLaMA-Factory 中的 template 名称为 `minicpm_v_4_6`
- [ ] 实现新 interval 方案的 `dataset_manager.py`,生成 `data/04_new_merged/`
- [ ] 在 `dataset_info.json` 中注册 `tensile_video_interval_*` 键名
- [ ] Phase 1 结束后评估子视频总磁盘占用
- [ ] Phase 2 前确认 LLaMA-Factory 版本兼容性

---

## 附录 A:模型数据流图

```
原始视频 (data/01_videos/*.mp4)
    + 标注 CSV (data/02_annotations/all_videos_tag.csv)
    |
    v
┌─────────────────────────────────────┐
│  元数据管理                           │
│  - ffprobe / cv2 提取 fps/帧数/时长   │
│  - 读取 CSV 的 event_frame_original    │
│  - 读取 location / material_type / resolution │
│  - 异常标记                            │
└─────────────────────────────────────┘
    |
    v  data/metadata/video_meta.json
┌─────────────────────────────────────┐
│  划分 + 子视频生成 + 样本构建          │
│  - Step 1: 原始视频 3-fold 划分        │
│  - Step 2: 生成 7 种类型子视频         │
│  - Step 3: ffmpeg 裁剪                │
│  - Step 4: 帧采样 + 标签计算            │
│  - Step 5: LLaMA-Factory 格式转换      │
└─────────────────────────────────────┘
    |
    +--> data/02_subvideos/*.mp4  (主产物)
    +--> data/03_frames/{video_id}_{crop_type}_{idx}/frame_*.jpg  (可选缓存)
    +--> data/04_merged/stratified_3_fold_*_{train,val}.json  (当前基线)
    +--> data/04_new_merged/fold_*_{train,val}.json          (新 interval 方案)
    +--> data/04_new_merged/test.json                        (新 interval 方案)
    |
    v
┌─────────────────────────────────────┐
│  Prompt 规范 + 训练配置                │
│  - Prompt 设计规范(Agent 动态构建)    │
│  - 微调模型 System Prompt 模板          │
│  - LLaMA-Factory YAML 配置            │
│  - dataset_info.json 注册             │
└─────────────────────────────────────┘
    |
    v
┌─────────────────────────────────────┐
│  模型微调训练 (LLaMA-Factory)         │
│  - 3-fold 独立训练                    │
│  - 输出 checkpoints                   │
└─────────────────────────────────────┘
    |
    v  LlamaFactory/saves/minicpmv4_6/lora/sft_3k*/
```

> 完整数据流图(含 Agent 迭代与评估)见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 附录 A。
