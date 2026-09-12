# 迁移入口调用图与保护清单

本表在M0核查基础上按已验证入口更新。当前M7a仅关闭三个旧数据发布/重建CLI；不能从局部切换推断整个legacy包退役。历史证据保留在verification及Git；完整身份以versioning/ids.py为准。

entrypoint_map_schema: tensile-migration/entrypoint-map/v1
task_id: "2026-09-07-readable-version-control-migration"
evidence_level: verified_local   # 入口职责均从本机代码文件读取核实

## 1) 统一编排入口（新体系顶层包）
- entry: "python -m versioning"（versioning/__main__.py -> versioning/cli.py）
  role: "新体系统一 CLI，所有正式对象由调用方显式给完整 ID，不猜 latest、不自动加号"
  subcommands: ["data", "prompt", "train", "eval", "model", "backup", "migration"]
  identity_resolution:
    - "versioning/ids.py：仅接受 data/prompt/train/model/eval 五族完整 ID"
    - "data 引用通过 versioning/data_release.validate_training_reference 校验 training_allowed/status（fail-closed）"
    - "eval/model 通过 versioning/registry 的门（require_passed=True）校验 train/eval 记录与 alias"
  formal_write_points:
    - "data release：seal_release 写 data/releases/<full-id>/release.yaml 并去写位封存"
    - "prompt：records/prompts/<full-id>.yaml；冻结副本 workspace/runs/<train>/input/prompt.yaml"
    - "model 注册/晋级/alias/物化：MLflow store workspace/mlflow（注册表 mVllm2）"
  notes: "这是 M1 新增 migration.py 的承载入口（Plan 要求统一 CLI 编排）。"

## 2) 数据七阶段（M3已接入真实业务）

正式CLI统一要求root/inputs/batch；release和release_validate另需完整data版本。data_pipeline的run_input_source/roi/subvideo/review_export/review_import/release及对应校验使用冻结原视频、注释、给定split、人工ROI、实际候选媒体/processor、完整人工回收；输出工作阶段manifest及data/releases/<完整身份>/payload。

M0发现的文件名ROI和固定两条候选属于早期最小实现，已不能代表当前正式入口。新链不重新划分三折，不新增采样，不生成旧release_pointer。M3真实媒体和人工交接证据见verification第24节；输入/输出完整说明见DATA_PROCESSING_RUNBOOK第10节及versioning/SCRIPTS.md。

## 3) 数据历史入口（M7a停用范围与保留依赖）

| 路径 | 当前状态 | 保留原因/后续动作 |
| --- | --- | --- |
| pipeline/scripts/release_build.py | 实际脚本与main先返回停用提示；不解析旧参数或进入写入 | 解析器/私有旧编排供历史测试，业务builder未删除 |
| pipeline/scripts/release_build_phase2.py | 包括validate-only在内的CLI已停用，无旧默认路径选择 | 既有Phase2发布对象走确认mapping复制迁移，不重建冒充等价 |
| pipeline/scripts/rebuild_data.py | run/resume/promote/source-only/check-only的CLI均停止，--help只显示新入口 | _legacy_main为显式历史测试路径；底层source/ROI/候选算法与状态回归保留 |
| pipeline/data_rebuild.py | 库函数保留，不作为本轮已退役对象 | tree_inventory等仍为业务依赖；旧promote/index写入函数仅停止上述CLI可达路径 |
| pipeline/scripts/review_candidates_app.py | versioning-package为新完整审查包模式，queue为旧模式 | 两种模式互斥；新模式不默认选择、不支持局部筛选；旧UI写入退役待单独核定 |
| pipeline/scripts/roi_annotation_app.py | 原ROI输入准备界面保留 | 旧模式仍可按source_snapshots LATEST找metadata；新数据输入必须明确冻结ROI文件，不把该默认值当新身份 |

artifact_index、artifact_resolver和build_artifact_index.py未删除。source_bootstrap、roi_manifest、roi_media、v3_candidate_plan、v3_candidate_media、v4_1_review_workflow、v4_1_training_release及历史重建代码仍引用相关模块；其中部分为独立辅助入口，不能仅凭新的正式CLI不直接import就判定零活动依赖。

## 4) 训练与测评入口（M4接线及剩余legacy边界）
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
  notes: "新prepare/validate/run/export已接入三折冻结与MLflow执行器；旧main尚保留，必须在M7后续单独核定，不宣称全部入口已接管。"
- finetune/eval_run.py
  role: "真实可续跑严格 V4.1 评测，对某 validation fold 逐样本推理"
  identity:
    - "校验 release（RELEASE_ID / expected contract hash / schema）"
    - "校验 V4.1 contract 身份（contract_hash == RUNTIME_CONTRACT_HASH）"
    - "通过 prompt_control 加载实验契约或 (legacy) analysis prompt overlay"
  model_load_point: "finetune/validation/model_runtime.load_model(model-dir, adapter-dir)"
  notes: "新正式eval prepare/validate/run/export已绑定Registry完整model与数值版本、原fold和Prompt；full/holdout实际读取拒绝。旧main仍支持model-dir，尚未列为已退役，不把历史summary转为passed。"
- finetune/release_validate.py / finetune/v4_1_runtime.py
  role: "经 finetuning runtime 校验不可变 release；解析/校验 V4.1 训练输入与输出"
  protection: "这些是真实校验原语；接管时应复用其校验，不复制一套等价实现冒充"

## 5) 服务与模型域入口（M5 严格切换）

2026-09-12接线更新：以下为代码入口状态；合成模型与受控loader的本机证据见verification第32节，不代表运行中服务或真实GPU已切换。

| 入口 | 当前身份与行为 |
| --- | --- |
| pipeline/server_proxy.py | 必填root、alias、service-mode、contract-version和deployment-manifest；通过共享resolver后才调用ChatModel，加载后再验；删除raw --model |
| pipeline/server_adapter.py | 仅包装响应并校验既有11字段deployment；实际选择在server_proxy完成，额外model_registry身份由proxy加入 |
| pipeline/model_registry.py | resolve_service_model调用MLflow alias门与current/manifest校验，比较缓存与权威artifact全部文件内容，生成绑定指纹；旧current读函数仅保留历史读取 |
| scripts/serve_validate_delivery.py | 公共validate_components及CLI通过共享resolver，无旧开发例外；历史组件审计只保留私有函数，不能作为新服务准入 |
| scripts/serve_manage_model_registry.py | validate/resolve-current要求显式alias与mode并通过共享resolver；inventory仅历史盘点，不授予模型资格 |
| pipeline/scripts/serve_smoke.py | 必填root/alias/mode/contract，发送媒体前核对preflight的Registry身份与指纹；响应也必须同一绑定，前后重验alias |

生产模式只接受production。服务解析不自动物化或修复缓存，不回退旧current.json；缺合格模型立即失败。当前没有合格真实模型成功加载证据。

## 6) 新体系身份/写入核心模块
- versioning/registry.py：MLflow Registry（mVllm2）晋级门、alias(candidate/production)、fail-closed 校验；materialize_model 到 models/<model_id>/
- versioning/materialize.py：alias -> workspace/models/current 原子物化与启动校验；validate_service_current
- versioning/manifest.py：DataRecordRef / PromptRecordRef / TrainRecordRef / EvalRecordRef / export_manifest / model manifest 校验
- versioning/mlflow_train.py / mlflow_eval.py：train/eval Run 生命周期与记录存储
- versioning/backup.py：离线备份 create/verify/restore与显式SSH transfer，catalog钉扎与原子不覆盖发布；M6实测证据见verification第33节

## 保护清单
1. 仅按已确认迁移计划逐入口切换；本轮停用上述三个数据CLI，其他legacy路径和历史产物保留，不批量删除包。
2. versioning 只接受 <kind>-v<协议>-r<N> 完整身份，fail-closed；禁止哈希/ LATEST/短前缀/隐式最新。
3. 历史正式产物（active_data_release.json、model_registry/current.json、旧模型 release manifest、review_decisions 层级）保留为历史证据，活动代码解除依赖。
4. M0记录的raw模型加载缺口已在M4正式eval和M5服务入口逐步接线；具体范围与未验证项以上文及verification为准，不能把代码接线当作真实推理成功。
5. 真实媒体重处理、训练、评测/GPU推理在训练机；本机开发、受控小对象测试与轻量证据操作按授权执行。
6. 每一项已切换结论须对应实际入口测试；私有历史函数保留不等于允许恢复旧CLI，代码接线不构成真实模型效果证明。
