# mVllm_2 Project Guide

<!-- explain-project
verified_commit: f8522587284a522b700ef0511ceff326619c7034
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
| 3. 子视频生成 | `pipeline/scripts/build_v3_candidate_plan.py`<br>`pipeline/scripts/materialize_v3_candidate_media.py`<br>底层：`pipeline/v3_candidate_plan.py` + `pipeline/v3_candidate_media.py`<br> orchestrator: `rebuild_v4_1_data.py` | ROI 视频目录 + `video_meta.roi.json`<br>review reference (`review_reference/<review-ref-id>/`)<br>`pipeline/contracts/tensile_vlm_v3.json` | `workspace/data/derived/metadata/candidate_plans/<plan_id>/`<br>`workspace/data/derived/subvideos/<plan_id>/videos/<candidate_id>.mp4`<br>`workspace/data/derived/frames/<plan_id>/<candidate_id>/frame_*.jpg`<br>`workspace/data/derived/metadata/candidate_media_results/<media_id>/` | 生成规则在 `v3_candidate_plan.py` 中硬编码（policy v3-candidate-policy/2.0）；每个源视频产出 transition / pre_event / post_event / stable_negative 四类候选；仅 gate 通过的候选进入下游；`v3` 是 provenance 命名遗留。详见下文「子视频生成重点展开」。 |
| 4. 人工审查 | `pipeline/scripts/build_v4_1_review_queue.py`<br>`pipeline/scripts/review_v4_candidates_app.py`（Streamlit UI）<br>`pipeline/scripts/route_v4_1_review_from_history.py`<br>`pipeline/scripts/build_v4_1_phase2_review_queues.py`<br> orchestrator: `rebuild_v4_1_data.py` | `candidate_media_results/<media_id>/development_materialized.json`<br>`candidate_media_results/<media_id>/manifest.json`<br>`pipeline/contracts/tensile_vlm_v4_1.json` | `workspace/data/derived/metadata/review_queues/<queue_id>/review_queue.json`<br>`workspace/data/derived/metadata/review_decisions/<queue_id>/<batch_id>/decisions.json` | 仅 development 中 `clip_state` 为「发生断裂/已断裂」进入人工队列；Phase 2 用 `build_v4_1_phase2_review_queues.py` 生成隔离队列；`route_v4_1_review_from_history.py` 用上一批冻结决定分流。 |
| 5. 数据发布 | `pipeline/scripts/build_v4_1_training_release.py`<br>`pipeline/scripts/build_v4_1_phase2_training_release.py`<br> orchestrator: `rebuild_v4_1_data.py` | 上述 review queue + decisions<br>source/split snapshot<br>`pipeline/contracts/tensile_vlm_v4_1.json` | `workspace/data/releases/<release-id>/`（只读、不可覆盖）<br>当前 active release: `v4.1.0-ecb5aeb9657c`（由 Phase 2 脚本生成）<br>基础不可变发布: `v4.1.0-760050fad303` | release 目录一旦生成即 immutable；后续训练只能绑定已发布 release identity；Phase 2 release 在基础 release 上叠加有效视图审计和额外人工决定。 |
| 6. 训练准备 | `pipeline/prompt_control/__main__.py`（validate/publish）<br>`finetune/build_v4_1_source_aware_3k.py`<br>`finetune/build_v4_1_fixed_prompt_dataset.py`<br>`finetune/prepare_v4_1_fixed_prompt_run.py` | 已发布 release（默认 `v4.1.0-ecb5aeb9657c`）<br>已发布 prompt revision（当前 active: `v4.1-concise-evidence-json-v2`）<br>baseline LLaMA-Factory YAML | `pipeline/prompt_registry/<revision_id>/`（Git）<br>`workspace/data/derived/metadata/v4_1/source_aware_3k/<sampling_id>/`<br>`workspace/runs/<experiment_id>/input/`<br>`finetune/experiments/<experiment_id>/{train,merge}.yaml` | 只能从已发布 prompt revision 生成 experiment contract；训练数据 3k/epoch，默认 seeds 3407+3411；`prepare_v4_1_fixed_prompt_run.py` 校验配置变化范围。 |
| 7. 测评与部署 | `finetune/train_with_contract.py`<br>`finetune/run_v4_1_evaluation.py`<br>`pipeline/model_registry.py` + `pipeline/scripts/validate_delivery_components.py`（实际路径 `scripts/validate_delivery_components.py`）<br>`pipeline/server_proxy.py` | `finetune/experiments/<experiment_id>/train.yaml`<br>merged model dir<br>release + experiment contract | `workspace/runs/<experiment_id>/adapter/`<br>`workspace/runs/<experiment_id>/merged/`<br>`workspace/runs/<experiment_id>/evaluation/`<br>`pipeline/model_registry/current.json`（Git manifest）<br>`workspace/models/releases/<model-name>/`（权重，不入 Git）<br>`delivery/model_component.json`、`delivery/service_component.json`（Git）<br>loopback-only OpenAI 风格 API | 当前 registry 指向 `v4.1-agent-pipeline-fold0-r1`；质量门未通过，不能对外暴露 production alias；服务默认绑定 `tensile-vlm/v2`，启动需 `--deployment-manifest`。 |

### 多版本说明

- **当前在用的候选生成链路**：`build_v3_candidate_plan.py` / `materialize_v3_candidate_media.py` 是当前 V4.1 的正式入口；模块名中的 `v3` 来自 provenance 路径，不代表契约回退到 V3（`RUNBOOK` 与 `v3_candidate_plan.py` 注释均已确认）。
- **旧版本入口**：`pipeline/scripts/archive/` 保留 V2/V3 历史命令（如 `publish_training_release.py`、`review_subvideos_app.py`、`subvideo_builder.py` 等），当前流程不要从这里启动。
- **Phase 2 脚本**：`build_v4_1_phase2_review_queues.py` 和 `build_v4_1_phase2_training_release.py` 用于在阶段 1 审计后对 development 做进一步隔离审查并生成新的 release；当前 active release `v4.1.0-ecb5aeb9657c` 即 Phase 2 release，基础 release `v4.1.0-760050fad303` 保持冻结。
- **单一 orchestrator**：日常复跑可用 `rebuild_v4_1_data.py run --run-root <staging> --roi-mode reuse --review-mode reuse` 一次性完成 1→5；RUNBOOK 和各独立脚本用于分步调试或小样本验证。

## 子视频生成重点展开

**输入**：不是原始视频，而是 `workspace/data/derived/roi_videos/<roi-media-id>/videos/<video_id>.mp4`（经 ROI 归一化后的 3:4 源视频）及其 `video_meta.roi.json`。`load_plan_inputs()` 还会校验 review reference split（必须 89/21）和 `pipeline/contracts/tensile_vlm_v3.json`。

**生成规则定义位置**：规则直接写在 `pipeline/v3_candidate_plan.py` 中，政策版本为 `v3-candidate-policy/2.0`。关键常量（源码确认）：
- 目标时长 `TARGET_DURATIONS = (2.0, 3.0, 5.0, 10.0, 20.0)` 秒；
- 断裂事件附近窗口位置 `EVENT_POSITIONS = (0.20, 0.35, 0.50, 0.65, 0.80)`；
- 事件禁区 `EVENT_GUARD_SECONDS = 0.5`；
- 最小候选时长 `MIN_CANDIDATE_SECONDS = 1.0`；
- 各类上限：`TRANSITION_CAP=10`、`BRITTLE_PRE_EVENT_CAP=3`、`DUCTILE_PRE_EVENT_CAP=15`、`OTHER_PRE_EVENT_CAP=4`、`POST_EVENT_CAP=4`、`NORMAL_NEGATIVE_CAP=5`。

**每个输入视频产出什么**：
- 对断裂且 `event_time_reliable` 的源视频：
  - `transition`（发生断裂）：最多 10 个，按断裂事件附近窗口生成；
  - `pre_event`（未断裂）：脆性 3 个、韧性最多 15 个、其他 4 个；
  - `post_event`（已断裂）：最多 4 个，含整体与分区窗口；
- 对非断裂源视频：
  - `stable_negative`（未断裂）：最多 5 个，位置按 video_id hash 旋转选取；
- 未夹紧/视频异常/缺少可靠 event_time 的源视频被记录到 `*_skipped_sources.json`，不产生候选。

**候选命名与目录结构**：
- candidate_id = `<video_id>_v3_<state>_f<start_frame>-<end_frame>`；
- 计划目录：`workspace/data/derived/metadata/candidate_plans/<plan_id>/`；
- 子视频：`workspace/data/derived/subvideos/<plan_id>/videos/<candidate_id>.mp4`；
- 采样帧：`workspace/data/derived/frames/<plan_id>/<candidate_id>/frame_0000.jpg` … `frame_0007.jpg`（MiniCPM `max_frames=8`）。

**与审查步骤的接口**：
- `materialize_v3_candidate_media.py` 物化后会生成 `candidate_media_results/<media_id>/review_queue.json`，其中只包含 development 中 `clip_state` 为「发生断裂」或「已断裂」的候选；
- `build_v4_1_review_queue.py` 读取 `development_materialized.json` + `manifest.json`，按 V4.1 contract 校验并生成 `workspace/data/derived/metadata/review_queues/<queue_id>/review_queue.json`；
- `review_v4_candidates_app.py` 消费该 queue，把人工决定写入 `workspace/data/derived/metadata/review_decisions/<queue_id>/<batch_id>/decisions.json`；
- `build_v4_1_training_release.py` 汇总 approved/corrected 决定，生成不可覆盖的 `workspace/data/releases/<release-id>/`。

## 链路节点

### 1. 原始视频与标注

- **拥有**：workspace/data/source 下的源视频、源标注和 split 定义。
- **产出**：经 `source_bootstrap` 形成的内容寻址 source snapshot 与 split snapshot。
- **下一站**：ROI 重建脚本消费 snapshot，保证后续所有子视频可回溯到源。

### 2. 数据快照 / ROI 子视频重建

- **拥有**：`pipeline/scripts/rebuild_v4_1_data.py` 主导整个 rebuild 流水线。
- **接收**：source snapshot、ROI manifest。
- **产出**：ROI 子视频、帧目录、各阶段 state/artifact 记录。
- **下一站**：进入候选计划。

### 3. 候选帧窗口计划与物化

- **拥有**：`pipeline/v3_candidate_plan.py`、`pipeline/v3_candidate_media.py`、对应 `scripts/build_v3_candidate_plan.py` 与 `scripts/materialize_v3_candidate_media.py`。
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
