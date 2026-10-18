# 迁移入口调用图与保护清单

本表在M0核查基础上按已验证入口更新。M7a关闭三个旧数据发布/重建CLI；M7b本批关闭四个旧训练/评测CLI；不能从局部切换推断整个legacy包退役。历史证据保留在verification及Git；完整身份以versioning/ids.py为准。

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

M0发现的文件名ROI和固定两条候选属于早期最小实现，已不能代表当前正式入口。新链不重新划分三折，不新增采样，不生成旧release_pointer。M3真实媒体和人工交接证据见verification第24节；输入/输出完整说明见DATA_PROCESSING_RUNBOOK及versioning/SCRIPTS.md。

## 3) 数据历史入口（M7a停用范围与保留依赖）

| 路径 | 当前状态 | 保留原因/后续动作 |
| --- | --- | --- |
| pipeline/scripts/release_build.py | 实际脚本与main先返回停用提示；不解析旧参数或进入写入 | 解析器/私有旧编排供历史测试，业务builder未删除 |
| pipeline/scripts/release_build_phase2.py | 包括validate-only在内的CLI已停用，无旧默认路径选择 | 既有Phase2发布对象走确认mapping复制迁移，不重建冒充等价 |
| pipeline/scripts/rebuild_data.py | run/resume/promote/source-only/check-only的CLI均停止，--help只显示新入口 | _legacy_main为显式历史测试路径；底层source/ROI/候选算法与状态回归保留 |
| pipeline/data_rebuild.py | 库函数保留，不作为本轮已退役对象 | tree_inventory等仍为业务依赖；旧promote/index写入函数仅停止上述CLI可达路径 |
| pipeline/scripts/review_candidates_app.py | 仅接受versioning-package完整审查包，旧queue解析时即拒绝 | 保留历史批次业务函数和读取规则；不改写原审查决定 |
| pipeline/scripts/roi_annotation_app.py | ROI输入准备界面保留，metadata/output/project-root均必填 | 导入和公开参数解析不选current/LATEST；仅接受metadata实际文件，旧解析器保留私有历史测试 |

M7d补充：roi_freeze_decisions、roi_materialize_videos、subvideo_build_plan、subvideo_materialize_media、review_build_queue、review_build_phase2_queues、review_route_from_history七个脚本的公开main及脚本/模块启动均在业务导入前停止；含check-only/dry-run也不开放旧选择。versioning无这些CLI调用，历史main改为私有测试入口，业务函数不变。

artifact_index、artifact_resolver和build_artifact_index.py未删除。source_bootstrap、roi_manifest、roi_media、v3_candidate_plan、v3_candidate_media、v4_1_review_workflow、v4_1_training_release及历史重建代码仍引用相关模块；上述独立数据辅助CLI已停止，但业务库与历史读取/索引工具仍有引用，不能把CLI退役等同于库无依赖。

### Prompt与历史索引入口

pipeline/prompt_control/__main__.py公开validate/publish及实际脚本/模块入口已停用，拒绝旧source读取和registry写入；模块启动保留既有包__init__导入core定义（含PyYAML依赖），不以Python -S模块可用性为验收。core/__init__公共库导出保持历史兼容，原main私有保留。新正式Prompt写入使用versioning prompt create，已有对象通过显式mapping迁移。

build_artifact_index.py保留为历史报告工具，必须显式指定现存data-root，仅生成INDEX.md，不选择current根、不更改集合index/LATEST、不授予新对象资格。artifact_index/resolver仍供历史业务和报告读取使用，保留库有实际引用依据。

## 4) 训练与测评入口（M7b本批）

| 路径 | 公开CLI状态 | 新入口调用与保留边界 |
| --- | --- | --- |
| finetune/train_build_dataset.py | main和脚本/模块启动停用 | build_versioned_datasets供train/eval准备调用；历史固定Prompt构建保留私有编排测试 |
| finetune/train_prepare_run.py | 旧实验准备CLI停用 | versioning.cli直接调用prepare_versioned_run、verify_versioned_run、execute_versioned_run、export_versioned_run |
| finetune/train_with_contract.py | 直接training-yaml CLI停用 | execute_versioned_run按冻结范围调用run_training（三折逐折、full一次），传入已冻结内存配置；保留LLaMA-Factory来源检查与processor契约 |
| finetune/eval_run.py | 裸model-dir与旧release选择CLI停用 | versioning.cli调用prepare/verify/execute/export_versioned_evaluation；Registry完整model和数值版本、原fold与Prompt绑定不变 |
| finetune/train_build_source_aware_dataset.py | 无独立main | 历史采样及共享辅助函数保留；新体系不扩大3k采样 |
| finetune/release_validate.py、finetune/v4_1_runtime.py | 校验原语保留 | 新旧业务共用契约与标签校验；不删除当前仍被调用的实现 |

四个已停用CLI在第三方/业务导入前拒绝，help仅迁移说明，无legacy开关。私有_legacy_main仅供明确的历史语义回归；旧prepare库函数内生成的历史运行命令也不能绕过脚本停用门。独立full训练和holdout代码接线已完成（fed9bcfc，verification第45节）；真实新模型训练、GPU测评与真实holdout评分成功路径仍缺证据，不因代码接线或旧CLI退役宣称真实验收通过。

full训练使用同一开发release三折共同全集去重，冻结六份来源和full输入；训练父Run无fold子Run，Registry核对full实际来源和adapter。holdout由eval_run委托finetune/eval_holdout.py：build_holdout_input冻结媒体及授权引用，execute_holdout_inference仅媒体推理，公开eval score调用score_holdout_evaluation进入授权评分；validate_holdout_execution验证公开承诺及consumed。私有预测/真值/逐样本结果不进入普通导出，未建立评分承诺时须核验原truth来源，已承诺恢复不重读原truth。参数及清单schema以versioning/SCRIPTS.md为准。

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

## history-summary 中的历史路径说明

`history-summary.yaml` 中 16 处 `path: docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md` 指向的文件已随 2026-10-18 清理移除；该字段记录迁移当时被接受的历史路径，保留原文以维持接受史原貌。该文件为 schema `tensile-migration/history-summary/v1` 的生成产物，重生成会覆盖手写内容，故说明只写在本节。

## 保护清单
1. 仅按已确认迁移计划逐入口切换；已停用上述三个数据和四个训练/评测CLI，其他legacy路径和历史产物保留，不批量删除包。
2. versioning 只接受 <kind>-v<协议>-r<N> 完整身份，fail-closed；禁止哈希/ LATEST/短前缀/隐式最新。
3. 历史正式产物（active_data_release.json、model_registry/current.json、旧模型 release manifest、review_decisions 层级）保留为历史证据，活动代码解除依赖。
4. M0记录的raw模型加载缺口已在M4正式eval和M5服务入口逐步接线；具体范围与未验证项以上文及verification为准，不能把代码接线当作真实推理成功。
5. 真实媒体重处理、训练、评测/GPU推理在训练机；本机开发、受控小对象测试与轻量证据操作按授权执行。
6. 每一项已切换结论须对应实际入口测试；私有历史函数保留不等于允许恢复旧CLI，代码接线不构成真实模型效果证明。
