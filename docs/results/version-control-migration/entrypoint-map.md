# M0 入口调用图与保护清单（entrypoint map）
# 任务：2026-09-07-readable-version-control-migration · M0 · 证据草稿
#
# 目标：为后续真实入口接管（M4/M5/M7）提供"当前活动入口 → 调用方 → 身份解析 →
# 正式写入点 → 最终模型加载点"的可追溯证据。
# 本文只描述现状与保护边界；不修改任何入口、不判定入口已接管。
# 身份解析以 versioning/ids.py 的 <kind>-v<协议>-r<N> 完整身份为 fail-closed 标准。

entrypoint_map_schema: tensile-migration/entrypoint-map/v1
task_id: "2026-09-07-readable-version-control-migration"
evidence_level: verified_local   # 入口职责均从本机代码文件读取核实

## 1) 统一编排入口（新体系顶层包）
- entry: "python -m versioning"（versioning/__main__.py -> versioning/cli.py）
  role: "新体系统一 CLI，所有正式对象由调用方显式给完整 ID，不猜 latest、不自动加号"
  subcommands: ["data", "prompt", "train", "eval", "model", "backup"]
  identity_resolution:
    - "versioning/ids.py：仅接受 data/prompt/train/model/eval 五族完整 ID"
    - "data 引用通过 versioning/data_release.validate_training_reference 校验 training_allowed/status（fail-closed）"
    - "eval/model 通过 versioning/registry 的门（require_passed=True）校验 train/eval 记录与 alias"
  formal_write_points:
    - "data release：seal_release 写 data/releases/<full-id>/release.yaml 并去写位封存"
    - "prompt：records/prompts/<full-id>.yaml；冻结副本 workspace/runs/<train>/input/prompt.yaml"
    - "model 注册/晋级/alias/物化：MLflow store workspace/mlflow（注册表 mVllm2）"
  notes: "这是 M1 新增 migration.py 的承载入口（Plan 要求统一 CLI 编排）。"

## 2) 数据七阶段（新体系，DVC）
- entry: "versioning/data_pipeline.py · run_stage"（经 cli `data <action>`）
  stages: [source, roi, subvideo, review_export, review_import, release, release_validate]
  role: "DVC 数据 pipeline 最小实现；release_validate 只报告不启动训练"
  identity_resolution:
    - "release 阶段必须显式传 version；用 parse_data_id 校验"
    - "review_import 用 content_sha256 绑定审查结论与内容"
  formal_write_points:
    - "working/<batch>/ 中间产物；data/releases/<full-id>（经 stage_release + seal_release）"
  known_gap（M3 需替换）:
    - "_derive_roi 由视频名摘要派生 ROI；run_subvideo 每视频固定 2 条 clip → 不承接真实人工 ROI/剪裁/采样语义"
  protection:
    - "不把固定 2-clip / 文件名 ROI 当作真实业务语义；M3 前不得宣称已接入真实数据语义"

## 3) 数据业务接入点（legacy，M4/M7 接管候选）
- pipeline/data_rebuild.py 与 pipeline/scripts/rebuild_data.py
  role: "隔离 V4.1 数据重建/续跑/promote（legacy 状态与原子提升原语）"
  identity: "使用 legacy artifact_index/artifact_resolver + LATEST 解析"
  protection: "legacy 旧写入口在 M7 前保持原样，不切换/删除/重构；不得被新写入绕过"
- pipeline/scripts/release_build.py / release_build_phase2.py
  role: "校验已审查候选并发布不可变训练 release（legacy：v4_1_training_release）"
  protection: "保留与数据语义有关的业务实现与历史审计内容；迁移只做语义保持"
- pipeline/scripts/review_candidates_app.py / roi_annotation_app.py
  role: "人工审查/ROI 标注 Streamlit 界面；ROI app 只写 ROI 决定文件，不生成裁剪媒体（MVP 声明）"
  identity: "roi_annotation_app 默认从 source_snapshots 集合 LATEST 解析 video_meta"
  protection: "人工交接链路保留；LATEST 解析仅限 legacy 域，不得迁移进 versioning 正式写入"

## 4) 训练与测评入口（legacy 实际执行器，M4 接管）
- finetune/train_with_contract.py
  role: "启动 LLaMA-Factory 训练（MiniCPM child-processor 契约）"
  identity: "读取 training-yaml 配置；校验 LlamaFactory src 无漂移"
  notes: "真实训练执行器；M4 必须贯通真实调用，而非只补状态管理测试。"
- finetune/train_build_dataset.py / train_build_source_aware_dataset.py
  role: "由当前 data 路径 + Prompt revision 派生 seed3411 / source-aware 3k 采样 bundle"
  identity: "经 pipeline/prompt_control 加载实验契约；绑定不可变 Prompt revision"
  notes: "依赖 current_data_paths（legacy 当前数据指针）。"
- finetune/train_prepare_run.py
  role: "准备一个语义化的 V4.1 Prompt 实验（legacy run 准备）"
  notes: "与 versioning/mlflow_train 的 Run 生命周期是新旧两套；M4 需统一身份贯穿。"
- finetune/eval_run.py
  role: "真实可续跑严格 V4.1 评测，对某 validation fold 逐样本推理"
  identity:
    - "校验 release（RELEASE_ID / expected contract hash / schema）"
    - "校验 V4.1 contract 身份（contract_hash == RUNTIME_CONTRACT_HASH）"
    - "通过 prompt_control 加载实验契约或 (legacy) analysis prompt overlay"
  model_load_point: "finetune/validation/model_runtime.load_model(model-dir, adapter-dir)"
  notes: "原始 model-dir 不能绕过正式测评入口；历史 summary 不转 passed。"
- finetune/release_validate.py / finetune/v4_1_runtime.py
  role: "经 finetuning runtime 校验不可变 release；解析/校验 V4.1 训练输入与输出"
  protection: "这些是真实校验原语；接管时应复用其校验，不复制一套等价实现冒充"

## 5) 服务与模型域入口（M5 严格切换）
- pipeline/server_proxy.py
  role: "集成 MiniCPM 服务（uvicorn FastAPI），加载 ChatModel 并暴露 /v1/chat/completions 与 contract preflight"
  identity:
    - "--model 直接给模型路径；--deployment-manifest 启动配置（10 固定字段）"
    - "contract 按 --contract-version 选择 v2 或 v4.1 生产契约"
  model_load_point: "ChatModel(_chat_model_args(args.model))"
  notes: "当前模型路径经 --model 显式给出，未经过 versioning alias/materialize 校验 → M5 需接入 alias 解析与 materialize 校验。"
- pipeline/server_adapter.py
  role: "给 OpenAI 响应注入 preprocessing 证据（frames/deployment）"
  identity: "校验 deployment_snapshot 11 字段与 contract_hash"
  notes: "响应注入器，不含正式身份解析；需与 alias 校验联动。"
- pipeline/model_registry.py
  role: "legacy 模型身份解析（MODEL_NAME_PATTERN <protocol>-<core>-<foldN|full>-r<N>）与 current 解析、artifact 校验"
  identity: "current.json + releases/<model>.json + aggregate sha256"
  formal_write_point: "读取 model_registry/current.json 与 releases/；resolve_current_artifact 解析路径"
  protection: "legacy 解析保留为历史证据；M7 只停用旧身份/写入路径，不把整个包当删除对象"
- scripts/serve_validate_delivery.py
  role: "校验 model/service delivery 组件身份、绑定与既有 gate 记录"
  identity: "校验 schema、manifest 绑定、artifact_gate/runtime_gate、source commit 为 HEAD 祖先"
  notes: "把既有 quality_status false 等读作记录，不自动升级为通过。"
- scripts/serve_manage_model_registry.py
  role: "检查/校验项目本地模型 artifact registry（inventory / validate / resolve-current）"
  identity: "经 pipeline.model_registry load_current_model / resolve_current_artifact / verify_current_artifacts"
  notes: "legacy 清单/校验入口，不含 versioning 的 MLflow alias 门。"
- pipeline/scripts/serve_smoke.py
  role: "对运行中服务做真实 HTTP smoke（contract preflight + analysis 请求 + preprocessing 校验）"
  identity: "本地契约与 preflight/响应 contract_hash 一致"
  protection: "只对已启动服务做 smoke；不负责启动/准入"

## 6) 新体系身份/写入核心模块（只读引用，M0 不改）
- versioning/registry.py：MLflow Registry（mVllm2）晋级门、alias(candidate/production)、fail-closed 校验；materialize_model 到 models/<model_id>/
- versioning/materialize.py：alias -> workspace/models/current 原子物化与启动校验；validate_service_current
- versioning/manifest.py：DataRecordRef / PromptRecordRef / TrainRecordRef / EvalRecordRef / export_manifest / model manifest 校验
- versioning/mlflow_train.py / mlflow_eval.py：train/eval Run 生命周期与记录存储
- versioning/backup.py：离线备份 create/verify/restore

## 保护清单（M0 结论）
1. legacy `pipeline/`、`finetune/` 既有入口保持原样，不切换/删除/重构/批量改名直至正式迁移完成。
2. versioning 只接受 <kind>-v<协议>-r<N> 完整身份，fail-closed；禁止哈希/ LATEST/短前缀/隐式最新。
3. 历史正式产物（active_data_release.json、model_registry/current.json、旧模型 release manifest、review_decisions 层级）保留为历史证据，活动代码解除依赖。
4. 最终模型加载点当前在 server_proxy(--model) 与 eval_run(model-dir)；M5 前不得宣称已由 versioning alias 严格接管。
5. 真实写入/评测/GPU 推理只发生在训练机；本机只做文档与证据整理。
6. 本文为 M0 草稿，每一行"已接管"类结论均需对应行为测试（Plan Proof 表），文件存在不构成接管证明。
