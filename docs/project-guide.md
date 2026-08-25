# mVllm_2 Project Guide

<!-- explain-project
verified_commit: 116d66af7777b5eb114b9cacbc664bda6ccf1ad0
verified_worktree: clean（本次仅更新 project-guide.md；指纹已排除该文件）
-->

mVllm_2 把材料拉伸试验视频治理为来源可追踪、标签可审查的 V4.1 视觉训练样本，并基于 MiniCPM-V-4.5 完成 LoRA 微调、严格评测与可复现的模型服务交付。

## 核心链路

```text
原始视频与标注
    ↓
数据快照 / ROI 子视频重建
    ↓
候选帧窗口计划与物化（v3 命名遗留）
    ↓
人工审查队列与决策
    ↓
不可覆盖的 training release 发布
    ↓
Prompt revision 注册 + 固定 Prompt 训练集构建
    ↓
训练准备 + 受控 LoRA 微调
    ↓
严格评测
    ↓
模型注册表晋级 + delivery 门禁校验
    ↓
推理服务交付
```

## 承重规则

1. **release 不可覆盖**：workspace 中 `data/releases/<release-id>/` 一旦发布即只读；后续训练/评测必须绑定到已冻结的 release identity。
2. **registry 是模型身份唯一事实源**：服务加载、交付校验、Agent 对接全部通过 `pipeline/model_registry/current.json` 解析当前模型，不能从目录名或实验文件名推断。
3. **工程链路与模型质量分开验收**：训练成功、服务启动、Agent 调通只证明链路可运行；最终模型仍需通过 Stage B/D/G 质量门，当前尚未通过。

## 步骤 → 脚本 → 产物（当前实现）

以下对照表把用户的 7 步流程映射到当前实际入口脚本、输入和产物位置。产物默认在 `workspace/` 下（训练机生成，大文件不入 Git）；脚本和小型 manifest 在 Git 仓库内。" orchestrator "指 `rebuild_v4_1_data.py` 把该步骤封装在内的意思。

| 用户步骤 | 当前脚本（精确路径） | 关键输入 | 产物位置（精确目录/文件） | 关键规则/约束 |
|---|---|---|---|---|
| 1. 初始数据 | `pipeline/scripts/rebuild_v4_1_data.py run --source-only`<br>（底层调用 `_source_stage`） | `workspace/data/source/videos/*.mp4`（110 个源视频）<br>`workspace/data/source/annotations/all_videos_tag.csv`<br>`workspace/data/source/annotations/video_mapping.csv`<br>`workspace/data/source/splits/*.json` | `workspace/data/derived/metadata/source_snapshots/<snapshot_id>/`<br>`workspace/data/derived/metadata/split_snapshots/<split_id>/` | 必须 110 个 MP4；CSV 列由 `source_bootstrap.TAG_COLUMNS` / `MAPPING_COLUMNS` 固定；split 必须 89 dev / 21 test（`DEFAULT_TEST_RATIO=0.2`）。`--source-only` 会初始化 run state（写 `run_root/control/rebuild.json`）并将 roi/review 模式烘焙为不可变身份，同一 run-root 续跑完整流水线时必须使用相同模式，否则需换 run-root。 |
| 2. ROI 与剪切 | `pipeline/scripts/roi_annotation_app.py`（Streamlit UI）<br>`pipeline/scripts/freeze_roi_decisions.py`<br>`pipeline/scripts/materialize_roi_videos.py`<br> orchestrator: `rebuild_v4_1_data.py` | 源视频 + `video_meta.json`<br>人工 ROI 决定 → `roi_decisions.json` | `workspace/data/derived/metadata/roi_decisions.json`<br>`workspace/data/derived/metadata/roi_manifests/<roi-manifest-id>/`<br>`workspace/data/derived/roi_videos/<roi-media-id>/videos/<video_id>.mp4` | 必须冻结 ROI manifest 后才物化；输出 3:4 比例、保留原时间轴；`check-only` 可预检。 |
| 3. 子视频生成 | `pipeline/scripts/subvideo_build_plan.py`<br>`pipeline/scripts/materialize_v3_candidate_media.py`<br>底层：`pipeline/v3_candidate_plan.py` + `pipeline/v3_candidate_media.py`<br> orchestrator: `rebuild_v4_1_data.py` | ROI 视频目录 + `video_meta.roi.json`<br>review reference (`review_reference/<review-ref-id>/`)<br>`pipeline/contracts/tensile_vlm_v3.json` | `workspace/data/derived/metadata/candidate_plans/<plan_id>/`<br>`workspace/data/derived/subvideos/<plan_id>/videos/<candidate_id>.mp4`<br>`workspace/data/derived/frames/<plan_id>/<candidate_id>/frame_*.jpg`<br>`workspace/data/derived/metadata/candidate_media_results/<media_id>/` | 生成规则在 `v3_candidate_plan.py` 中硬编码（policy v3-candidate-policy/2.0）；每个源视频产出 transition / pre_event / post_event / stable_negative 四类候选；仅 gate 通过的候选进入下游；`v3` 是 provenance 命名遗留。详见下文「子视频生成重点展开」。 |
| 4. 人工审查 | `pipeline/scripts/build_v4_1_review_queue.py`<br>`pipeline/scripts/review_v4_candidates_app.py`（Streamlit UI）<br>`pipeline/scripts/route_v4_1_review_from_history.py`<br>`pipeline/scripts/build_v4_1_phase2_review_queues.py`<br> orchestrator: `rebuild_v4_1_data.py` | `candidate_media_results/<media_id>/development_materialized.json`<br>`candidate_media_results/<media_id>/manifest.json`<br>`pipeline/contracts/tensile_vlm_v4_1.json` | `workspace/data/derived/metadata/review_queues/<queue_id>/review_queue.json`<br>`workspace/data/derived/metadata/review_decisions/<queue_id>/<batch_id>/decisions.json` | 仅 development 中 `clip_state` 为「发生断裂/已断裂」进入人工队列；Phase 2 用 `build_v4_1_phase2_review_queues.py` 生成隔离队列；`route_v4_1_review_from_history.py` 用上一批冻结决定分流。 |
| 5. 数据发布 | `pipeline/scripts/build_v4_1_training_release.py`<br>`pipeline/scripts/build_v4_1_phase2_training_release.py`<br> orchestrator: `rebuild_v4_1_data.py` | 上述 review queue + decisions<br>source/split snapshot<br>`pipeline/contracts/tensile_vlm_v4_1.json` | `workspace/data/releases/<release-id>/`（只读、不可覆盖）<br>当前 active release: `v4.1.0-ecb5aeb9657c`（由 Phase 2 脚本生成）<br>基础不可变发布: `v4.1.0-760050fad303` | release 目录一旦生成即 immutable；后续训练只能绑定已发布 release identity；Phase 2 release 在基础 release 上叠加有效视图审计和额外人工决定。 |
| 6. 训练准备 | `pipeline/prompt_control/__main__.py`（validate/publish）<br>`finetune/build_v4_1_source_aware_3k.py`<br>`finetune/build_v4_1_fixed_prompt_dataset.py`<br>`finetune/prepare_v4_1_fixed_prompt_run.py` | 已发布 release（默认 `v4.1.0-ecb5aeb9657c`）<br>已发布 prompt revision（当前 active: `v4.1-concise-evidence-json-v2`）<br>baseline LLaMA-Factory YAML | `pipeline/prompt_registry/<revision_id>/`（Git）<br>`workspace/data/derived/metadata/v4_1/source_aware_3k/<sampling_id>/`<br>`workspace/runs/<experiment_id>/input/`<br>`finetune/experiments/<experiment_id>/{train,merge}.yaml` | 只能从已发布 prompt revision 生成 experiment contract；训练数据 3k/epoch，默认 seeds 3407+3411；`prepare_v4_1_fixed_prompt_run.py` 校验配置变化范围。 |
| 7. 测评与部署 | `finetune/train_with_contract.py`<br>`finetune/run_v4_1_evaluation.py`<br>`pipeline/model_registry.py` + `pipeline/scripts/validate_delivery_components.py`（实际路径 `scripts/validate_delivery_components.py`）<br>`pipeline/server_proxy.py` | `finetune/experiments/<experiment_id>/train.yaml`<br>merged model dir<br>release + experiment contract | `workspace/runs/<experiment_id>/adapter/`<br>`workspace/runs/<experiment_id>/merged/`<br>`workspace/runs/<experiment_id>/evaluation/`<br>`pipeline/model_registry/current.json`（Git manifest）<br>`workspace/models/releases/<model-name>/`（权重，不入 Git）<br>`delivery/model_component.json`、`delivery/service_component.json`（Git）<br>loopback-only OpenAI 风格 API | 当前 registry 指向 `v4.1-agent-pipeline-fold0-r1`；质量门未通过，不能对外暴露 production alias；服务默认绑定 `tensile-vlm/v2`，启动需 `--deployment-manifest`。 |

### 多版本说明

- **当前在用的候选生成链路**：`subvideo_build_plan.py` / `materialize_v3_candidate_media.py` 是当前 V4.1 的正式入口；模块名中的 `v3` 来自 provenance 路径，不代表契约回退到 V3（`RUNBOOK` 与 `v3_candidate_plan.py` 注释均已确认）。
- **旧版本入口**：`pipeline/scripts/archive/` 保留 V2/V3 历史命令（如 `publish_training_release.py`、`review_subvideos_app.py`、`subvideo_builder.py` 等），当前流程不要从这里启动。
- **Phase 2 脚本**：`build_v4_1_phase2_review_queues.py` 和 `build_v4_1_phase2_training_release.py` 用于在阶段 1 审计后对 development 做进一步隔离审查并生成新的 release；当前 active release `v4.1.0-ecb5aeb9657c` 即 Phase 2 release，基础 release `v4.1.0-760050fad303` 保持冻结。
- **单一 orchestrator**：日常复跑可用 `rebuild_v4_1_data.py run --run-root <staging> --roi-mode reuse --review-mode reuse` 一次性完成 1→5；RUNBOOK 和各独立脚本用于分步调试或小样本验证。

## ROI 标注与物化重点展开

**输入**：来自第 1 步的源视频与 `video_meta.json`（source snapshot 产物），以及 `split_snapshots/<id>/test.json`（冻结阶段需要）。

**三个脚本职责与调用顺序**：

1. `pipeline/scripts/roi_annotation_app.py`：Streamlit UI，读取 `video_meta.json` 与源视频，人工选择 `fixed_roi`（拖拽锁定 3:4 红框）或 `no_crop`（保留全画面），确认可见性检查后写出 `workspace/data/derived/metadata/roi_decisions.json`。
2. `pipeline/scripts/freeze_roi_decisions.py`：校验 `roi_decisions.json` 的完整覆盖、策略版本、几何一致性、可见性、源视频 SHA-256，并按 `test.json` 将决定切分为 `development_roi.json` 与 `test_roi_audit.json`，生成内容寻址的 `roi_manifests/<roi-manifest-id>/`。
3. `pipeline/scripts/materialize_roi_videos.py`：读取冻结的 ROI manifest，用 ffmpeg 为每个决定物化 3:4 的 ROI 源视频，输出到 `workspace/data/derived/roi_videos/<roi-media-id>/`。

`rebuild_v4_1_data.py run` 在 `_run_pipeline` 中按上述顺序封装了冻结、物化两个阶段（`roi_validated` → `roi_media_ready`），`--roi-mode reuse` 可复用已标注的 `roi_decisions.json`。

**人工决定内容**：不是画任意框，而是二选一：

- `fixed_roi`：在源画面上拖拽锁定为 3:4 的红框，最终按 `pixel_box` 精确裁剪；策略为 `crop_exact`。
- `no_crop`：保留完整画面，后续用黑边 padding 到 3:4；策略为 `pad_to_target`。

批准前必须勾选 5 项可见性检查（上下夹具、完整试样、位置可判、齐根断裂可判），并检查关键时刻预览。

**roi_decisions.json 单条决定字段**：`source_video_id`、`source_video_path`、`mode`、`review_status`、请求的 `requested_margins` 与生效的 `margins`、`normalized_box`、`pixel_box`、`target_aspect_ratio`（固定为 `3:4`）、`aspect_ratio_strategy`（`crop_exact` 或 `pad_to_target`）、`interaction_mode`（`drag_box` 或 `no_crop`）、`source_resolution`、`source_sha256`、`source_size_bytes`、`source_mtime_ns`、`reviewed_timestamps`、`visibility_checks`、`roi_policy_version`、`reviewed_at`、`reviewer_notes`。

**冻结产出结构**（`roi_manifests/<roi-manifest-id>/`）：

- `manifest.json`：身份哈希、split guard（dev/test 数量与重叠校验）、各 artifact 哈希。
- `roi_decisions.frozen.json`：带 `roi_manifest_id` 的完整决定副本。
- `development_roi.json`：dev 集合（默认 89 条）的 ROI 决定。
- `test_roi_audit.json`：test 集合（默认 21 条）的 ROI 决定，用于审计而非训练。
- `validation_report.json`：总数、dev/test 数量、模式计数、哈希校验结果。

冻结强校验规则包括：110 条全覆盖、无重复、全部 `approved`、策略版本匹配、`fixed_roi` 必须精确 3:4 偶像素、`no_crop` 边距全零、可见性全通过、源视频 SHA-256 一致。

**物化规则**：

- `fixed_roi`：ffmpeg `crop=w:h:x:y,setsar=1`，按冻结的 `pixel_box` 裁剪。
- `no_crop`：ffmpeg `pad=target_w:target_h:x:y:color=black,setsar=1`，计算最小能包住源画面的偶数 3:4 canvas。
- 编码：H.264 / yuv420p、`-vsync 0` 保持帧同步、`-an` 丢弃音频、`-crf 23 -preset fast`。
- 时间轴：校验输出帧数、标称帧率、时长与源一致，不改变播放速度。
- 产物目录：`workspace/data/derived/roi_videos/<roi-media-id>/videos/<video_id>.mp4`，以及 `video_meta.roi.json`、`validation_report.json`、`manifest.json`。
- 幂等性：`materialize_plan` 先检查目标目录是否存在且 identity/hash 一致；一致则复用，不一致则报错或重新生成。

**执行位置**：标注 UI 在 Mac 上运行（Streamlit + 本地 ffprobe 抽帧）；冻结是轻量 JSON 校验，均可运行；物化依赖 ffmpeg、读写大视频、多线程，设计在训练机/Linux 上运行。本机 `workspace/` 目前无 ROI 产物，大产物需从训练机同步。

**与上下游接口**：上游是第 1 步的 source snapshot / split snapshot；下游子视频生成读取 `roi_videos/<roi-media-id>/video_meta.roi.json` 与 `videos/<video_id>.mp4`，作为 candidate plan 的输入。

## 子视频生成重点展开

**输入**：不是原始视频，而是 ROI 物化产物 `workspace/data/derived/roi_videos/<roi-media-id>/videos/<video_id>.mp4`（3:4 源视频）及其 `video_meta.roi.json`。`load_plan_inputs()` 还会校验 review reference 的 split（必须 89 development / 21 test， inventories 无交叉且完整覆盖 ROI metadata）和 `pipeline/contracts/tensile_vlm_v3.json` 的 contract hash。`subvideo_build_plan.py` 默认指向 `roi-media-84ea2bd3a052` 与 `review-ref-7cd2e73a1cd1`，这些 ID 与基础发布 `v4.1.0-760050fad303` 的上游一致。

**两个脚本的分工（计划与物化分离）**：
- `subvideo_build_plan.py` 只做轻量元数据计划：读入 ROI media、review reference、contract，按硬编码策略计算所有候选窗口，输出 `candidate_plans/<plan_id>/`（`manifest.json`、`development_candidates.json`、`test_candidate_audit.json`、`needs_review.json`、`statistics.json`）。**不写 MP4/帧**，`media_generated=false`。
- `materialize_v3_candidate_media.py` 做重执行：读入冻结的 plan，用 ffmpeg 裁剪每个候选的 MP4，再用真实 MiniCPM-V processor 采样并导出 JPG，同时运行 sampling gate；输出 `subvideos/<plan_id>/videos/`、`frames/<plan_id>/<candidate_id>/`、`candidate_media_results/<media_id>/`（含 `development_materialized.json`、`test_materialized_audit.json`、`review_queue.json`、`generation_report.json`、`manifest.json` 及每条候选的 receipt）。
- 分离意图：plan 是确定性的轻量 dry-run 产物，可重复、可审查、可内容寻址；物化涉及大视频 I/O 与模型处理，允许按 `--scope` / `--candidate-ids` / `--limit` 做子集生成，也便于在训练机上隔离运行。

**生成规则定义位置**：规则硬编码在 `pipeline/v3_candidate_plan.py`（`POLICY_VERSION = "v3-candidate-policy/2.0"`，第 23 行）。关键常量（第 24–35 行）：
- 目标时长 `TARGET_DURATIONS = (2.0, 3.0, 5.0, 10.0, 20.0)` 秒；
- 断裂事件附近窗口位置 `EVENT_POSITIONS = (0.20, 0.35, 0.50, 0.65, 0.80)`；
- 事件禁区 `EVENT_GUARD_SECONDS = 0.5`；
- 最小候选时长 `MIN_CANDIDATE_SECONDS = 1.0`；
- 上限：`TRANSITION_CAP=10`、`BRITTLE_PRE_EVENT_CAP=3`、`DUCTILE_PRE_EVENT_CAP=15`、`OTHER_PRE_EVENT_CAP=4`、`POST_EVENT_CAP=4`、`NORMAL_NEGATIVE_CAP=5`。

**四类候选语义与时间窗口计算**（代码位置：`v3_candidate_plan.py` `_raw_candidates_for_source` 约第 335 行起）：
- 先由 `_source_kind()` 判断源视频是「断裂 / 非断裂 / 未夹紧 / 视频异常」；只有断裂且 `event_time_reliable=True` 才有 transition/pre/post；未夹紧、视频异常或缺少可靠 event_time 的源视频被写入 `*_skipped_sources.json`，不产生候选。
- `transition`（`clip_state=发生断裂`）：窗口必须满足 `start_time < event < end_time`。对 `TARGET_DURATIONS` 中每个目标时长，取 `EVENT_POSITIONS` 的事件位置比例（如 0.5 表示事件位于窗口正中），生成标准窗口；随后按与历史 reference 的“相同帧区间 + 相同标签”兼容数量排序，选取两个循环位移（cyclic shift），合计上限 `TRANSITION_CAP=10`。若标准窗口放不下，则使用 `_adaptive_transition_window` 自适应选择一个能放下的最大时长（仍保持同一事件比例），最多额外 1 个（`transition_adaptive_cap: 1`）。
- `pre_event`（`clip_state=未断裂`，断裂前的源）：窗口必须完全位于 `event - EVENT_GUARD_SECONDS` 之前。策略按断裂机制分三种：
  - 脆性/爆炸性断裂 → `abrupt_end_aligned`，取最短、中位数、最长三个可行时长，上限 3；
  - 韧性/半脆半韧断裂 → `process_front_middle_back`，对每个可行时长都在前、中、后三个位置采样，上限 15；
  - 其他 → `other_end_aligned`，取可行时长前 4 个，上限 4。
- `post_event`（`clip_state=已断裂`，断裂后的源）：窗口从 `event + EVENT_GUARD_SECONDS` 开始。先生成「整体」窗口；若整体时长 ≥3s 则分为 2 段，≥6s 则分为 3 段；每段都 ≥`MIN_CANDIDATE_SECONDS`，合计上限 `POST_EVENT_CAP=4`。
- `stable_negative`（`clip_state=未断裂`，非断裂源）：对 `TARGET_DURATIONS` 中每个目标时长，以视频总时长的不同比例为中心生成窗口，中心比例按 `video_id` SHA-256 hash 对 `EVENT_POSITIONS` 做旋转选取，上限 `NORMAL_NEGATIVE_CAP=5`。
- 同一 `(start_frame, end_frame, clip_state)` 去重；窗口实际帧数由 `_aligned_interval()` 按源视频 fps 对齐。

**每个源视频产出多少条候选**：没有固定条数，取决于源时长、event_time 位置、断裂机制与历史 reference 匹配情况。上限由各类 CAP 控制；reference 的「兼容 exact 匹配」会影响 transition 的位移选择，但不改变上限。`statistics.json` 会记录每个 source 的实际贡献数。

**candidate_id 与 plan_id 生成**：
- `candidate_id = "{video_id}_v3_{STATE_SLUGS[state]}_f{start_frame:06d}-{end_frame:06d}"`（`STATE_SLUGS` 映射：`未断裂→pre`、`发生断裂→transition`、`已断裂→post`、`无法判断→unknown`），见 `_build_scope_candidates` 约第 474 行。
- `plan_id = "candidate-plan-{sha256(identity)[:12]}"`，`identity` 包含 schema_version、输入 manifests/contract 的 SHA-256、以及完整 policy 字典（`v3_candidate_plan.py` `build_candidate_plan` 约第 523 行）。因此 plan 是内容寻址的：输入或策略任一变化都会产生新 plan_id。
- `media_id = "candidate-media-{sha256(identity)[:12]}"`，`identity` 包含 plan_id、plan manifest hash、ROI media_id、processor fingerprint、encoding profile、gate version、scopes、候选集合 hash（`v3_candidate_media.py` `load_media_plan` 约第 149 行）。
- 幂等/覆盖：`subvideo_build_plan.py` 写计划前若目录已存在，则逐文件校验 identity、input_paths、artifact hashes，完全一致才复用，否则报错（`materialize_candidate_plan` 约第 583 行）。`materialize_v3_candidate_media.py` 同样：若 `result_dir/manifest.json` 已存在则完整校验 identity、artifact hashes、receipts 及媒体文件 hash；单条候选若 receipt 已存在且媒体未漂移则复用（`_validate_complete_result`、`_process_candidate` 约第 448/388 行）。**拒绝覆盖**。

**采样帧（frames）何时、如何生成，谁消费**：
- 帧不是计划阶段生成，而是在 `materialize_v3_candidate_media.py` 的 `_process_candidate()` 中生成。对每个通过 probe 校验的 clip，调用 `MiniCPMVideoPreprocessor.sample()`（`max_frames=8`、`video_fps=2.0`），采样数 = `min(8, floor(duration * 2.0))`，再用 `np.linspace` 在解码帧中均匀取位（`pipeline/preprocessing/minicpm_preprocessor.py` 第 320–340 行）。因此帧数不一定是 8：2s Clip 约 4 帧，5s 及以上最多 8 帧。
- 然后用 ffmpeg `select=eq(n\,{clip_frame})` 把每个采样帧导出为 `frame_{input_index:04d}.jpg`（`v3_candidate_media.py` `_export_frames` 约第 416 行）。
- `actual_frame_mapping` 记录 `input_index → clip_frame → original_frame → 源视频 timestamp`，写入 materialized candidate 和 receipt。
- 下游：`build_v4_1_review_queue.py` / `review_v4_candidates_app.py` 读取 materialized 结果里的帧路径；训练时 LLaMA-Factory / MiniCPM 实际看到的输入就是这组采样帧（以及对应的 `actual_frame_mapping`），而不是任意抽帧或完整子视频。

**gate 规则**：
- 第一层是 clip probe 校验：`v3_candidate_media.py` `_validate_clip_probe` 约第 282 行，检查输出帧数、分辨率、fps、时长与源一致。
- 第二层是 actual sampling gate：`validate_actual_sampling_gate` 约第 335 行，检查：
  - 采样帧非空且 `input_index` 连续、`clip_frame` 单调无重复、timestamp 单调；
  - `transition` 必须至少有一帧在 event 前、一帧在 event 后；
  - `pre_event` 若源有断裂，则所有采样 timestamp 必须 ≤ `event - EVENT_GUARD_SECONDS`；
  - `post_event` 所有采样 timestamp 必须 ≥ `event + EVENT_GUARD_SECONDS`。
- 未通过 gate 的候选写入 `generation_report.json` 的 `excluded` 列表，不进入 `development_materialized.json` 和 `review_queue.json`。
- `review_queue.json` 只在 gate 通过的 development 候选中，挑选 `clip_state ∈ {"发生断裂", "已断裂"}` 的条目（`v3_candidate_media.py` `MANUAL_REVIEW_STATES`，约第 34 行）。

**candidate_media_results 与 candidate_plans/subvideos 的关系**：
- `candidate_plans/<plan_id>/`：纯元数据计划，无媒体，可以被多次物化（例如换 processor 或子集）但本身不绑定处理器身份。
- `subvideos/<plan_id>/videos/` 与 `frames/<plan_id>/<candidate_id>/`：实际媒体文件，按 plan_id 组织。
- `candidate_media_results/<media_id>/`：一次具体物化运行的完整证据包，包括 identity、每条候选的 receipt、gate 结果、`actual_frame_mapping`、视频/帧 hash、以及汇总 manifest。它是 plan → review queue / training release 之间的桥接层。

**运行机器**：
- `subvideo_build_plan.py` 是轻量 JSON 计算，Mac 或训练机均可运行；`--dry-run` 模式下不创建目录，只打印身份与统计。
- `materialize_v3_candidate_media.py` 需要 ffmpeg、MiniCPM model、大视频读写，且实际调用 transformers processor，**设计在训练机/Linux 上运行**；Mac 只能跑 `--check-only`（验证输入、源媒体、processor fingerprint 和输出身份，不生成媒体）。

**现状：哪个 plan_id/media_id 是当前 release 的上游**：
- 基础不可变发布 `v4.1.0-760050fad303` 的上游是默认脚本指向的 `candidate-plan-ce36b9226be5` + `candidate-media-8de972530561`（`materialize_v3_candidate_media.py` 默认 `DEFAULT_PLAN_ID`；RUNBOOK 与 `audit_v4_1_effective_views.py` 默认值交叉印证）。`v3` 命名前缀即来自此脚本。
- 当前活跃 Phase 2 release `v4.1.0-ecb5aeb9657c` 额外引入了 410 条实验候选，其产物路径指向 `candidate-plan-v41exp-c99cd2894bb0` + `candidate-media-b442478052cd`（`docs/results/v4_1_phase1_effective_view_audit/audit_manifest.json`、`pipeline/scripts/build_v4_1_phase2_training_release.py` 默认值）。**仓库当前脚本中未找到生成 `v41exp` 候选的入口**（`grep -R v41exp` 仅在结果文档与测试 fixture 中出现），这是第 3 步脚本与当前最新发布上游之间的一个未验证缺口。

**与审查步骤的接口**：
- `materialize_v3_candidate_media.py` 物化后产出 `candidate_media_results/<media_id>/review_queue.json`，其中只包含 development 中 gate 通过且 `clip_state` 为「发生断裂」或「已断裂」的候选；
- `build_v4_1_review_queue.py` 读取 `development_materialized.json` + `manifest.json`，按 V4.1 contract 校验并生成 `workspace/data/derived/metadata/review_queues/<queue_id>/review_queue.json`；
- `review_v4_candidates_app.py` 消费该 queue，把人工决定写入 `workspace/data/derived/metadata/review_decisions/<queue_id>/<batch_id>/decisions.json`；
- `build_v4_1_training_release.py` 汇总 approved/corrected 决定，生成不可覆盖的 `workspace/data/releases/<release-id>/`。

## 链路节点

### 1. 原始视频与标注

- **拥有**：workspace/data/source 下的源视频、源标注和 split 定义。
- **产出**：经 `source_bootstrap` 形成的内容寻址 source snapshot 与 split snapshot。
- **下一站**：ROI 重建脚本消费 snapshot，保证后续所有子视频可回溯到源。

### 2. 数据快照 / ROI 子视频重建

- **拥有**：`pipeline/scripts/rebuild_v4_1_data.py` 主导整个 rebuild 流水线；`pipeline/roi_manifest.py` 负责冻结校验；`pipeline/roi_media.py` 负责物化。
- **接收**：source snapshot 的 `video_meta.json`、split snapshot 的 `test.json`、人工产出的 `roi_decisions.json`。
- **产出**：冻结的 `roi_manifests/<roi-manifest-id>/`、物化后的 `roi_videos/<roi-media-id>/`（含 3:4 源视频与 `video_meta.roi.json`）。
- **关键规则**：冻结必须完整覆盖 110 个视频且按 dev/test 切分；物化保留原时间轴与帧率；`fixed_roi` 精确裁剪 3:4，`no_crop` 黑边 padding 到 3:4。
- **下一站**：进入候选帧窗口计划。

### 3. 候选帧窗口计划与物化

- **拥有**：`pipeline/v3_candidate_plan.py`、`pipeline/v3_candidate_media.py`、对应 `scripts/subvideo_build_plan.py` 与 `scripts/materialize_v3_candidate_media.py`。
- **接收**：ROI 子视频、原始视频 split、标签规则。
- **产出**：候选帧窗口计划、物化的子视频/帧、媒体门禁结果；规则与上限见 `pipeline/v3_candidate_plan.py`（`TARGET_DURATIONS`、`EVENT_POSITIONS`、各类 `*_CAP` 等常量）。
- **命名说明**：模块名中的 `v3` 是 provenance 遗留，V4.1 继续复用这些物化机制，不代表契约回退到 V3。
- **下一站**：满足门禁的候选进入 V4.1 审查队列。

### 4. 人工审查队列与决策

- **拥有**：`pipeline/v4_1_review_workflow.py`、`pipeline/v4_1_review_decisions.py`、Streamlit 审查 UI 辅助脚本。
- **接收**：候选媒体与自动分流结果。
- **产出**：review queue、review evidence、人工决策结果。
- **下一站**：决策结果汇入 training release。

### 5. 不可覆盖的 training release 发布

- **拥有**：`pipeline/v4_1_training_release.py`。
- **接收**：审查后的标签、源 snapshot binding、媒体清单。
- **产出**：`workspace/data/releases/<release-id>/` 下的 manifest、dataset_info、媒体文件；当前活跃发布为 `v4.1.0-ecb5aeb9657c`（Phase 2 development release），基础不可变发布为 `v4.1.0-760050fad303`。
- **下一站**：由 `finetune/build_v4_1_fixed_prompt_dataset.py` 绑定到具体 Prompt revision。

### 6. Prompt revision 注册 + 固定 Prompt 训练集构建

- **拥有**：`pipeline/prompt_control/` 提供 active prompt 校验与发布；`pipeline/prompt_registry/` 存放不可变 revision。
- **接收**：training release、已发布 Prompt revision（当前活跃 `v4.1-concise-evidence-json-v2`）。
- **产出**：固定 Prompt 的语义实验输入目录，含 experiment contract。
- **下一站**：`finetune/prepare_v4_1_fixed_prompt_run.py` 生成训练配置。

### 7. 训练准备 + 受控 LoRA 微调

- **拥有**：`finetune/prepare_v4_1_fixed_prompt_run.py`、`finetune/train_with_contract.py`。
- **接收**：固定 Prompt 训练集、LLaMA-Factory 基线配置、contract 校验。
- **产出**：workspace/runs/<experiment-id>/ 下的 adapter、merged 模型、日志。
- **下一站**：`finetune/run_v4_1_evaluation.py` 在验证集上做严格评测。

### 8. 严格评测

- **拥有**：`finetune/run_v4_1_evaluation.py`。
- **接收**：release、experiment contract、merged/adapter 模型。
- **产出**：schema 合法率、四字段准确率、`clip_state` 混淆矩阵、失败样例等。
- **下一站**：只有跨 fold 稳定且质量门通过的方案才晋级发布；当前多数实验停留在 workspace/runs/。

### 9. 模型注册表晋级 + delivery 门禁校验

- **拥有**：`pipeline/model_registry.py`、`scripts/validate_delivery_components.py`（仓库根 `scripts/` 下）、`delivery/model_component.json`、`delivery/service_component.json`。
- **接收**：人工确认的模型目录、评测证据、契约身份。
- **产出**：`pipeline/model_registry/releases/<model-name>.json` 与 `current.json`。
- **当前发布**：`v4.1-agent-pipeline-fold0-r1`（Fold0 中间模型，质量门未通过）。
- **下一站**：推理服务从 registry 加载该模型。

### 10. 推理服务交付

- **拥有**：`pipeline/server_proxy.py`。
- **接收**：registry 指向的 merged 模型、production contract、服务启动配置。
- **产出**：loopback-only 的 OpenAI 风格 API，输入 MP4 base64，输出四字段 JSON（V4.1 字段或 V2 字段，取决于启动的 contract version）。
- **约束**：`server_proxy.py` 默认绑定 `tensile-vlm/v2` contract，可通过 `--contract-version tensile-vlm/v4.1` 启动 V4.1 模式；禁止对外暴露 production alias。

## 关键细节

### V4.1 输出字段

`clip_state`、`fracture_mechanism`、`fracture_site`、`special_case`。权威契约见 `pipeline/contracts/tensile_vlm_v4_1.json`，运行时校验见 `pipeline/v4_1_labels.py`。

### 双机工作流

- Mac（本机）：uv + Python 3.11，负责代码检查、文档、Streamlit 审查 UI、轻量校验。
- 训练机（Linux/GPU，SSH 100.70.83.68）：Conda，负责训练、GPU 推理、完整评测、重数据处理。
- 本机看到的大量训练产物是从训练机同步过来的结果，不应默认本机能复现实验。

### workspace 是产物层

`workspace/` 被 Git 忽略，存放数据、实验运行、模型资产。代码与轻量 manifest 入 Git，大型产物与一次性评测记录不入 Git。

## 当前限制与未知

- 当前唯一发布模型 `v4.1-agent-pipeline-fold0-r1` 已通过工程链路，但 Stage B/D/G 质量门未通过，不是 production-ready 最终模型。
- 最新三折实验 `v4.1-prompt-concise-cv-v1-seed3411` 已跑通全流程，但出现类别坍缩、契约非法和断裂状态召回不足，未晋级 release。
- 本机无法运行训练、GPU 推理和完整评测；缺少产物时应标记为“证据不足”。
- 第 3 步当前仓库脚本（`subvideo_build_plan.py` / `materialize_v3_candidate_media.py`）可验证默认 `candidate-plan-ce36b9226be5` / `candidate-media-8de972530561` 的生成逻辑，但活跃 Phase 2 release 额外使用的 `candidate-plan-v41exp-c99cd2894bb0` / `candidate-media-b442478052cd` 的生成入口未在当前脚本/模块中找到，属于未验证缺口。
