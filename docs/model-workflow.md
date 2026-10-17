# 模型训练、评测与服务

本说明面向已经准备好数据、希望训练或运行模型的使用者。环境安装从[快速开始](../README.md#快速开始)进入；开发数据与独立 test 数据的构建见[数据处理](data-workflow.md)。正式操作统一使用 `python -m versioning`，所有版本使用 `data / prompt / train / model / eval` 五类完整身份，例如 `train-v4.1-r<N>`，其中 `<N>` 必须替换为明确分配的序号。

项目已实现冻结训练输入、三折与全量训练、严格评测、Registry 晋级及服务门禁。现有历史开发结果尚不能证明最终模型质量；新体系真实合格模型的加载与媒体推理成功路径、独立 test 使用资格、大型产物组合恢复仍未完成验收。命令接线和 CPU 合成验证不等于真实模型验收。

**开发测评显式区分协议。** `strict-v4.1` 保留历史严格评分；新开发配置选择 `semantic-v4.1`，使用全样本语义评分、独立格式诊断和逐折开发门。基座与成功折诊断来源已接入同一 Registry。接口及合成检查不构成真实模型质量证据；独立语义评分、受控性能证据和按用途准入的工程接线见下文；真实低权限判读、性能运行及生产验收仍按[实施计划](plans/model-evaluation-implementation.md)推进，实际状态见[项目 TODO](project-todo.md)。不得修改旧门或补写 passed 代替新协议证据。

基座真实来源登记、已完成折快照诊断、开发语义统计及已封存盲评答案导入已接入代码。预测判读策略默认两个 Agent 独立处理，分歧交第三个先独立再仲裁；可扩人数但配置预先冻结，不要求多个真人。纯导入接口不执行判读，也不证明真实隔离：本地评审进程、账户权限、安装摘要及现场输入仍须核验。独立评分已增加发包、封存和消费接线，性能入口接收冻结事件证据；两者的合成证据均不能取得真实生产资格。设计确认和接口实现均不授予真实模型调用、受限数据发送或测试集使用权限。

GPU 训练、权重合并、实际推理与完整评测在训练机执行，运行入口直接使用已按 Linux GPU 锁核验的 Conda Python 3.11.x。Mac 开发及人工审查使用 uv 的方式见[快速开始](../README.md#快速开始)。以下命令是操作说明，执行仍需相应任务授权。准备与摘要校验虽不加载模型，也可能扫描大量权重和媒体，须按实际数据量安排执行位置与磁盘空间。

## 1. 准备身份、输入与执行环境

从训练机仓库根目录运行以下 Python 命令；可以使用已激活 Conda 环境中的 Python，本文以 `"$PYTHON"` 显式绑定解释器。每次任务明确一个 store，并保留它的记录、MLflow 数据库和 artifact；不能用旧活动指针或最近目录自动选择输入。

| 参数或文件 | 来源与要求 |
| --- | --- |
| `PYTHON` | 已按 Linux GPU 锁核验的训练机 Conda Python 3.11.x 解释器绝对路径；核对所绑定的代码 checkout |
| `STORE` | 明确的 versioning store 绝对路径，数据、Prompt、训练、Registry 和评测共用此根 |
| `DATA`、`PROMPT`、`TRAIN`、`MODEL`、`EVAL` | 已确认的完整身份；新对象身份不得占用已有不可变对象 |
| `MEDIA_ROOT` | 数据实际引用的媒体根；七阶段开发发布为对应 `payload/`，迁移发布可能仍依赖外部旧 workspace 媒体 |
| `DATA_INPUTS` | 七阶段发布所用的原 inputs YAML，用于训练或 validation 准备时复验数据链；迁移数据改由 committed receipt 验签 |
| `TRAIN_CONFIG` | 调用者明确准备的 LLaMA-Factory 配置 YAML，包含实际基座路径、超参数、seed 和训练日程 |
| `ENVIRONMENT` | 从实际环境核实的非空依赖版本 YAML，例如 Python、torch、transformers、LLaMA-Factory 版本 |
| `GIT_COMMIT` | 本次执行所用代码提交；依赖、配置及代码版本须与冻结记录一致 |
| `EVAL_CONFIG` | 已确认的严格评测配置及质量阈值；validation 没有默认质量阈值 |

store 不会为使用者自动下载基座、提供训练数据或分配质量门槛。基座必须是实际存在的普通绝对目录；训练准备会冻结完整文件清单与内容摘要。已有大型权重是否在场必须现场核对，历史日志或 manifest 不能替代它们。

配置字段的完整规范见 [versioning 参数索引](../versioning/SCRIPTS.md)。原 `finetune` 训练与评测公开 CLI 已停用；保留的业务函数供新执行器调用。

## 2. 注册 Prompt

先准备 `PROMPT_DEFINITION` YAML，包含非空 `system_prompt`、`user_prompt` 和非空、不重复的字符串列表 `output_fields`，可附 `protocol_label` 保存业务契约标签。V4.1 输出字段为 `clip_state`、`fracture_mechanism`、`fracture_site`、`special_case`；具体取值遵守[业务契约](../pipeline/contracts/tensile_vlm_v4_1.json)。旧 `active_prompt.yaml` 不是新定义格式。

```sh
"$PYTHON" -m versioning prompt create --root "$STORE" \
  --version "$PROMPT" --protocol v4.1 --definition "$PROMPT_DEFINITION"
"$PYTHON" -m versioning prompt show --root "$STORE" --version "$PROMPT"
```

正式对象位于 `records/prompts/<prompt>.yaml`，已有身份拒绝覆盖。Prompt 正文与 schema 合法只证明输入可用，不证明模型质量。后续 `train prepare` 将它冻结到该训练的 `input/prompt.yaml`；训练模型的评测和服务继承其绑定的训练 Prompt，不允许临时替换正文以改变已登记模型；base 开发评测在配置中显式绑定正式任务 Prompt。

## 3. 冻结并执行训练

### 三折训练

`TRAIN_CONFIG` 顶层恰好包含 `fold0`、`fold1`、`fold2`，每个值为该折完整训练配置，三折使用相同基座。准备器绑定数据名称、冻结目录、媒体根与输出目录，保持 release 中已有成员、顺序和标签，不重新划分或增加采样。

`tokenized_path`、`adapter_name_or_path`、`resume_from_checkpoint` 非 null 时拒绝准备；当前接口不提供未冻结的外部 adapter 初始化或 checkpoint 续训。

```sh
"$PYTHON" -m versioning train prepare "$TRAIN" --root "$STORE" \
  --data-version "$DATA" --prompt-version "$PROMPT" \
  --config "$TRAIN_CONFIG" --environment "$ENVIRONMENT" \
  --git-commit "$GIT_COMMIT" --media-root "$MEDIA_ROOT" \
  --data-inputs "$DATA_INPUTS"
"$PYTHON" -m versioning train validate "$TRAIN" --root "$STORE"
```

上述示例面向七阶段发布；使用 committed receipt 验证的迁移数据时省去 `--data-inputs`，媒体根仍必须指向真实媒体，不能指向迁移来源镜像。

准备产物为 `workspace/runs/<train>/input/`，包含三折六份数据、dataset 索引、正式 Prompt 副本、训练配置、环境版本和校验清单。prepare/validate 不创建训练 Run，不加载推理模型。

取得实际训练授权后，可以一次运行全部三折，或分次运行：

```sh
"$PYTHON" -m versioning train run "$TRAIN" --root "$STORE" --fold 0
"$PYTHON" -m versioning train run "$TRAIN" --root "$STORE" --fold 1
"$PYTHON" -m versioning train run "$TRAIN" --root "$STORE" --fold 2
```

省略 `--fold` 会执行尚未完成的折。分次执行共享父 Run；成功但尚缺折时标记 `partial`，映射为 MLflow 原生 `KILLED`，表示本次调用结束而整组未完成。保留已完成折的冻结输入、输出及 MLflow 副本；执行器验签后复用，不重训该折。失败、中断、残留不完整输出、内容漂移或并发冲突拒绝自动续办，不能用分折恢复来绕过失败检查。

每折保存 adapter、有限数值训练指标及 `execution-evidence.json`。三折齐全后汇总真实执行证据，并导出 `records/training/<train>/manifest.yaml`。若完整训练已经完成，仅导出失败，可运行：

```sh
"$PYTHON" -m versioning train export "$TRAIN" --root "$STORE"
```

该命令从同一 completed Run 恢复导出，不重新训练或覆盖不同内容。训练 loss 与 eval loss 下降只表示训练目标收敛。

### 独立全量训练

开发侧方案稳定并取得全量训练授权后，另分配 `TRAIN` 身份。配置顶层仅为 `full`；沿用上面的准备参数并增加 `--scope full`。开发全集从三折 train/validation 来源按媒体身份去重构建，每个候选一次；标签冲突或各折全集不一致拒绝。

full 禁止训练中 validation、最佳 checkpoint 选择、隐式验证切分及 `max_samples` 截断，不能使用 holdout 选择训练日程或 checkpoint。准备后仍使用 `train validate/run/export`，run 不接受 `--fold`。full 只执行一次训练，不创建折子 Run，adapter 为父 Run 的 `full/adapter`；它不是把某折产物改名所得的模型。

## 4. 登记模型与验证集评测

开发评测由明确的 Registry 来源进入，禁止使用裸权重路径绕过身份与摘要检查。已完成训练沿下述 `model register` 登记；基座和成功折使用独立来源分支，不造训练记录、不改变父训练状态。

```sh
"$PYTHON" -m versioning model register "$BASE_MODEL" --root "$STORE" \
  --source-kind base --source-scope base --base-model-path "$BASE_MODEL_PATH" \
  --upstream-source "$UPSTREAM_SOURCE" --upstream-revision "$UPSTREAM_REVISION" \
  --git-commit "$GIT_COMMIT"
"$PYTHON" -m versioning model register "$DIAGNOSTIC_MODEL" --root "$STORE" \
  --source-scope diagnostic_fold --train-version "$TRAIN" --fold 0
```

`BASE_MODEL`、`DIAGNOSTIC_MODEL` 都是调用者分配的完整 model 身份。基座目录须含实际权重、config、tokenizer/processor，来源与固定 revision 须先核实；可用 config 来源字段或可识别 HF snapshot 路径须与声明一致；二者不足时，目录须含 `source-provenance.json`，schema 为 `tensile-base-provenance/v1`，含匹配的 upstream_source/upstream_revision 及非空 verified_by。该文件随字节冻结；一致性检查不等于密码学证明上游真实性。不接受 main/latest 等活动引用，不自动下载或升级。当前MiniCPM基座的固定文件比对与构造代码偏差见[固定来源核验](results/minicpm-fixed-source-audit-20261016.md)；权重相同不能替代代码来源，未核差异不通过空泛来源声明追认。登记创建来源 Run 的实际字节快照和 `model-source.json`，不造 train/data/Prompt。基座评测另显式绑定开发 data 与任务 Prompt。

诊断来源只接受真实 FINISHED 折的 execution receipt 和 adapter，冻结 checkpoint step、父 train/run、共享输入、基座与真实折号；不接受任意中途 checkpoint 或自定义 artifact。父 train 保持 partial，后续使用重验共享输入及来源。base/diagnostic 可用于开发测评和受控性能测量；性能入口见第 7 节，不能借 candidate/production alias 部署，也不能 finalize 为生产资格。

登记先校验真实训练执行证据、声明 artifact 全部文件和冻结基座，创建 Registry `mVllm2` 的 staging Model Version。它同时具有完整 `MODEL` 身份和 MLflow 数值版本；后者由登记结果取得，不猜测或默认选择最新版本。

`ARTIFACTS` 是调用者准备的 YAML 文件绝对路径，文件内容为 artifact mapping，不是命令行直接传入的 mapping 字面量。三折组包含三折，例如：

```yaml
fold0: {adapter: artifacts/fold0/adapter}
fold1: {adapter: artifacts/fold1/adapter}
fold2: {adapter: artifacts/fold2/adapter}
```

```sh
"$PYTHON" -m versioning model register "$MODEL" --root "$STORE" \
  --train-version "$TRAIN" --source-scope cross_validation --artifacts "$ARTIFACTS"
```

三折组不能提供 `--deploy-target`，也不能直接部署。single_fold 以 fold0 为例，使用仅含 `fold0` 的声明及 `--source-scope single_fold --deploy-target artifacts/fold0/adapter`；full 使用 `full: {adapter: artifacts/full/adapter}` 及 `--source-scope full --deploy-target artifacts/full/adapter`。每种声明均须对应训练证据中的真实 artifact。`single_fold` 仍从已完成的三折训练选一折；只有成功折的训练改用上面的 `diagnostic_fold` 分支，不能虚补其余折或修改父状态绕过。

当前正式执行链使用 adapter：训练执行器上传 adapter，Registry 逐文件核对训练执行证据中的 `<fold>/adapter/` 内容。接口接受 `merged` artifact 类型不代表已经实现独立合并及其证据登记通路。另行准备完整 merged 权重、修改 mapping，或在冻结 adapter 子树中后添 merged 文件，均不能补齐证据。真实 merged 合并、登记与后续使用须先完成独立确认的实现和验收；历史 BF16/merged 结果仅保留为原实验成果，不能沿用为新模型资格。

旧严格协议仍支持 single_fold 或 cross_validation 训练模型，使用对应开发 data 的完整 validation，无新增抽样。旧配置精确包含：

| 字段 | validation 配置 |
| --- | --- |
| `scope`、`split` | 与模型一致的 `single_fold` 或 `cross_validation`，以及 `validation` |
| `artifact_kind` | 当前正式操作使用 `adapter`；单折须等于唯一 deploy_target。接口接受 `merged`，其真实证据通路仍待实现与验收 |
| `scorer`、`sample_selection`、`aggregation` | `strict-v4.1`、`all`、`pooled` |
| `quantization_bit` | 显式 null 或 4；不同量化路线不能继承另一模型变体的结论 |
| `generation` | `do_sample: false`、`num_beams: 1`、`max_new_tokens: 256`、`video_max_frames: 8` |
| `thresholds` | 非空、明确批准的指标下限 mapping，取值在 0 至 1；允许的六指标见参数索引 |

取得 `MODEL_NUMBER` 后准备：

```sh
"$PYTHON" -m versioning eval prepare "$EVAL" --root "$STORE" \
  --model-version "$MODEL" --model-version-number "$MODEL_NUMBER" \
  --data-version "$DATA" --config "$EVAL_CONFIG" --git-commit "$GIT_COMMIT" \
  --media-root "$MEDIA_ROOT" --data-inputs "$DATA_INPUTS"
"$PYTHON" -m versioning eval validate "$EVAL" --root "$STORE"
```

迁移数据同样省去 `--data-inputs`。prepare 冻结模型、Prompt、数据、媒体、生成规则和评分实现，不下载权重或推理；必要时初始化 store 的本地 MLflow 基础设施。取得实际评测授权后在训练机执行 `eval run "$EVAL" --root "$STORE"`，正式权重由 Registry artifact 物化，执行前后核验摘要。

旧严格协议逐折结果为 `records.jsonl`、`failures.jsonl`、`summary.json`；父 Run 汇总逐样本预测与严格评分，正式导出为 `records/evaluations/<eval>/manifest.yaml`。运行失败不产生正式完成 manifest；完整推理但非法 JSON/schema 或指标不达标形成质量失败。完成后的导出故障可用 `eval export` 从同一 Run 补导出，不调用模型。失败 Run、已有输出或进程强制中断不提供自动覆盖重跑。

新开发协议的完整配置、judge 导入恢复和 baseline 报告见 [versioning 参数索引](../versioning/SCRIPTS.md#语义开发协议)。设置 `scorer: semantic-v4.1` 才使用新门；旧结果不会重新解释。所有失败、空输出与缺失字段保留在原样本分母，严格合法率独立于恢复结果；机制/位置按 GT 非 null 子集评分，预测状态不能改变分母。

三折分别检查状态 macro recall ≥ 0.65、每状态 recall ≥ 0.50，pooled 检查 joint ≥ 0.50、机制 macro F1 ≥ 0.50、位置 macro F1 ≥ 0.60。单折可以形成诊断，不能自动宣称三折通过；缺必测类或评审未完成报告证据不足。source_groups 必须由操作者核定候选到独立组的完整映射，包括更高试件依赖，视频来源名称不能证明统计独立。CI 是同组 bootstrap 报告，不新增 CI 硬门。

以下是开发链路的输入与产物交接；真实执行顺序为基座对照、对应完整单折诊断、完整三折。validation 结果不能替代独立 test 验收。

| 环节 | 输入提供者与入口 | 产物及下游 |
| --- | --- | --- |
| 数据与任务 Prompt | data 发布/迁移校验、`prompt create` | data release 与 `records/prompts/<prompt>.yaml` → train/eval prepare |
| 训练与成功折 | `train prepare/validate/run/export`；真实媒体、配置和基座 | 冻结 input、折 execution receipt、adapter；完整训练 manifest → trained register，成功折 receipt → diagnostic register |
| 来源登记 | `model register` 的 trained/base/diagnostic 分支 | Registry 数值版本、完整 model 身份；base/diagnostic 来源快照及 `model-source.json` → eval prepare/run |
| 冻结开发测评 | 操作者配置、完整独立组映射；`eval prepare/validate` | `workspace/evaluations/<eval>/input/evaluation.yaml`，媒体/Prompt/规则/来源摘要与多数类定义 → run |
| 推理与整理 | `eval run`；必要时 `eval score --blind-reviews` 导入已封存 judge 答案 | 原始逐样本与语义记录、逐折和 pooled 汇总 → export；judge 恢复不重新推理 |
| 正式导出与比较 | `eval export` 重验；多数类摘要与 `eval compare --baseline-eval-version` | `records/evaluations/<eval>/manifest.yaml` 和可追溯报告；质量绝对门与对照提升分开解释 |

判读恢复的每次有效导入先封存为 `output/review_attempts/0001.json`，上传父 Run 并由 `sha256_review_attempt_0001` 钉扎。相同导入幂等；已完成初判不可更换，仅基础设施故障可按冻结策略重试一次。全部尝试（含故障）的实际成本与计算总耗时进入 `summary.blind_import_audit`，累计耗时不代表墙钟延迟；export 重验尝试链、最终采用结果及摘要，将尝试文件纳入 manifest。恢复不会重置原 raw 或重推理。

`eval compare "$EVAL" --root "$STORE" --baseline-eval-version "$BASE_EVAL"` 从两个已完成的 semantic validation Run 形成 `records/evaluations/<eval>/paired/<base-eval>.json`，重验来源和同条件完整配对，不重新推理。多数类自动摘要是合成对照，其合法率或耗时不是模型能力。

接口可执行性和合成验证只证明接线、统计及拒绝逻辑，不能据此声称完成真实模型调用、训练机评测或质量通过；真实运行证据以项目 TODO 的验收记录为准。本轮独立评分的 sandbox 探针仅验证合成 canary 的进程限制，真实低权限 Agent 工作区、Ollama 安装/运行及完整隔离仍未验收；内容封存或访问声明不能代替现场技术隔离。性能与服务的真实验收仍未完成。

## 5. Full 模型的独立 test 验收

本节命令用于说明已接入的工程链路，不授予真实 test 使用权限。本轮仅允许合成验证，禁止运行真实模型评测或使用真实 test。

### 新独立语义协议

新配置显式选择 `scorer: semantic-holdout-v4.1`、`scope: full`，绑定完整 `source_groups`、预冻结 `blind_policy` 与 `review_runtime`；需要读取受限聚合时，prepare 前另冻结 `aggregate_authorization: {actor: <负责人>, role: acceptance-owner, os_uid: <实际UID>}`，评分 executor 不隐式取得此角色；阈值采用[测评方案](model-evaluation.md)中的最终质量门，不使用下文旧七门。配置核验入口为 `finetune/eval_review.py` 的 `validate_semantic_holdout_config`，模型须来自真实完整 full 训练；base、诊断折和开发 validation 不能代替它。

| 环节 | 输入提供者与入口 | 真实文件与消费者 |
| --- | --- | --- |
| 一次性锁定 | 获授权操作者先准备预注册；`data claim` 精确绑定 eval/model/data/split/executor/规则 | release 的 `authorization/` 与 staging 预注册 → `eval prepare/validate/run` |
| 一次推理 | 已发布无标签媒体、Registry 权重、训练 Prompt；`eval run` | `workspace/evaluations/<eval>/restricted/predictions.json`、`inference.json` → 匿名发包；此时不读真值 |
| 发包与暴露登记 | 操作者提供与冻结 policy 摘要一致的手册；`eval review_prepare --manual` | 受限 `anonymous-review.json`、映射及 `exposure.json`，授权目录 `exposed.yaml` → 本地评审和封存；不能恢复成未暴露 |
| 判读封存 | 独立执行者提供已封存判断 JSON；`eval review_seal --blind-reviews` | 受限 `review_attempts/`、`judge.json` → score；同内容重传幂等，完成初判不可替换，故障按冻结策略重试 |
| 受限评分与消费 | `eval score --executor` 核验原身份、raw、发包、判读，再读 sealed truth | 受限真值快照、语义记录、实际指标/CI、评分 receipt；承诺和 `consumed` → 公开 export |
| 公开导出 | `eval export` 从同 Run 重验 aggregate、规则、权重、评分承诺和消费事实 | `records/evaluations/<eval>/manifest.yaml` 仅 gate 与完整性证据 → Registry；不重新读真值 |

已有 `data claim`、`eval prepare/validate/run/score/export` 参数见下文；新协议在 run 与 score 之间插入：

```sh
"$PYTHON" -m versioning eval review_prepare "$EVAL" --root "$STORE" --manual "$REVIEW_MANUAL"
"$PYTHON" -m versioning eval review_seal "$EVAL" --root "$STORE" --blind-reviews "$SEALED_REVIEWS"
```

`REVIEW_MANUAL` 是操作者在 prepare 前冻结、与 policy 匹配的普通文件；`SEALED_REVIEWS` 由获授权的独立判读过程提供，不是代码自动生成的正确答案。受控执行入口为 `eval review_run "$EVAL" --root "$STORE"`，默认禁止真实模型调用；未来即使显式添加 `--allow-real-model-calls`，仍须实际部署/tokenizer/隔离证据齐全。固定 localhost Ollama broker 与 Mac worker 的 transport、部署凭据核验接口已实现；真实部署/tokenizer receipt 缺失或当前资产漂移时在真实请求前拒绝，测试仅使用合成资产/stub。本轮不执行该入口的真实调用。发包前实际运行 Mac `sandbox-exec` 拒绝访问探针，验证包只读、受限 canary/凭据不可读、他人结果不可写及网络/任意工具受限；不可用即拒绝发包。本轮合成工程 receipt 标记 `synthetic: true`、`real_model_deployment_verified: false`，未调用真实评审模型、未证明真实评审部署，因此即使合成 gate 全过仍不能晋级或取得服务资格。broker 每次调用保存 started/sealed 与 attempt 证据；未证实后台终止的 timeout 记 ambiguous 并立即停止，不自动重试或切模型。owner-only 全局锁和 `backend-ambiguous.json` 哨兵阻止后续请求，核定终态前不继续，也不停止共享 Ollama。

无正式eval的隔离准备先运行 `python -m finetune.eval_audit_isolation --run-probes --output /绝对路径/新报告.json`：只用合成canary和匿名worker，失败拒绝，不请求Ollama或生成正式部署凭据；详见[隔离与显示测点准备](results/evaluation-isolation-display-preflight-20261016.md)。

真实评审部署凭据由 `eval review_verify "$EVAL" --root "$STORE"` 核验；默认不联网，未来显式加 `--allow-local-review-metadata` 只准固定 localhost 的 tags/show 元数据，不生成回答。本地tokenizer候选已按固定HF revision落地，独立Python3.11依赖见根 `requirements-review.lock`；原HF直接编码存在NFC/NFD差异；2026-10-16按原方案修复现有适配层，保留HF模板与原文，以冻结GGUF规则构造内存计数器，进展与新版受审材料见[兼容修复记录](results/evaluation-review-compatibility-repair-20261016.md)，原始来源见[固定来源及材料](results/evaluation-tokenizer-materials-20261015.md)。输入 `config.review_tokenizers` 须在 prepare 前冻结每个批准模型的本地 HF 完整文件/大小/摘要、固定上游来源/revision、GGUF 模型摘要、依赖版本及源码摘要、provider 实现摘要、模板摘要和 `tokenizer_equivalence_audit: {path, sha256}`。本地加载使用 local_files_only、trust_remote_code=False，核验模板、special tokens 和关闭 thinking 的行为，封存受限 `review-deployment.json` 并提交 MLflow 摘要；注入 provider 的 receipt 永远 synthetic。

等价审计必须由具名 independent-tokenizer-auditor 提供受审 GGUF↔HF 映射、可核查 basis 文件/独立 GGUF counter 来源摘要及 golden messages→rendered prompt 摘要→token IDs。代码核验绑定、字节和本地 golden case，不接受 `equivalent: true` 自报；映射的独立审查范围与证据限制须明确，新兼容计数器要求v2映射绑定完整manifest/GGUF及派生规则；旧v1证据不自动升级。实际调用前以 HF 按冻结非 thinking 模板精确 render，同一字符串由兼容计数器 encode 核 8K 上限，再由 Ollama raw generate 使用同字符串，避免另套隐式模板；返回模型/token count 不一致拒绝。真实 review_run 还须显式调用授权、已提交真实部署凭据及当前模型/资产/依赖/profile 一致，不能仅凭开关放行。

新独立语义配置还须显式冻结 `device` 与 `runtime_variant`，与性能配置使用相同 device/dtype/库版本/预处理及量化声明。默认实际推理采集已加载模型、processor 帧属性、generation 和源码/版本，形成 `runtime_attestation`、`runtime_observation`，从 inference 经 score 延续到 manifest；旧 strict 不添加这些字段。工程 collector 已接入，本轮没有现场真实运行凭据。

恢复始终绑定同一 eval/model/data/split/executor/规则/raw/判读摘要。发包后不能撤销 exposed，score 完成无论质量通过或失败均消费授权；迁移、备份和恢复保留这些事实。已有评分承诺时可恢复完成/导出，不重推理或重读原真值；尚无承诺时仍须原授权核验真值来源。公开 MLflow/manifest 不发布实际分数、CI、映射、raw 或逐样本错误；受限聚合读取须在消费封存后执行 `eval restricted_summary "$EVAL" --root "$STORE" --actor "$ACCEPTANCE_OWNER"`，或调用 `finetune.eval_holdout.read_restricted_holdout_summary(root=..., eval_version=..., actor=...)`。`ACCEPTANCE_OWNER` 必须是 prepare 前显式冻结的 acceptance-owner；接口核验实际 OS UID、文件所有者、消费凭据和评分承诺，只返回聚合指标、支持数、诊断和 CI，不返回 raw/GT/逐样本。未冻结授权时拒绝，不默认由 score executor 读取，也不得用于调参。

### 旧 strict 冻结协议

**以下七门保留旧 strict 协议的冻结含义。** 新标准及格式分离规则以[测评方案](model-evaluation.md)及上节显式新协议为准。旧身份、旧报告与已消费 test 的限制保留，新协议不得重新利用已暴露 test；旧 passed 不获得新语义或性能资格。唯一例外为[测评方案 §10](model-evaluation.md#10-最终测试的非盲参考性口径) 明文裁决的 21 个既定 test source 非盲重建；该例外不改变其余已暴露 test 的禁用规则，也不授予任何独立资格。

匿名多 Agent 判读只适用于上节新协议；下述 strict 路线不执行新判读。两条路线均在 run 不读真值、score 才读真值并消费授权，禁止混用旧门与新规则。

先完成[数据处理中的独立 test 发布](data-workflow.md)，取得仍具独立使用资格、已全量人工审查且封存的 holdout data。发布须包含无标签 `evaluation_inputs/manifest.json`、`media/`、受限 `sealed_ground_truth/` 及构建凭证，绑定 full 模型所用开发版本。历史 test 划分、旧 sealed-test 目录或重新命名的对象不能自动获得资格。

`HOLDOUT_DATA` 为该完整 data 身份，`SPLIT` 为其独立验收 split，`EXECUTOR` 为授权执行身份，`PREREGISTRATION` 为提前准备的预注册 YAML。预注册包含完整 eval/model/data 身份、同一 split、`one_time: true`、`tuning_use: forbidden`、`recovery: {same_identity_only: true}`；rules 精确等于评测配置去除 thresholds 后的内容，thresholds 完全一致。full 配置沿用前节结构但 scope 为 full，并固定七项门槛：

```yaml
thresholds:
  four_state_macro_recall: 0.4006
  fracture_three_state_macro_recall: 0.3
  joint_correct_rate: 0.3921
  runtime_failure_count: 0
  strict_valid_rate: 1.0
  已断裂_recall: 0.15
  未断裂_recall: 0.7
```

失败次数必须等于 0，其余为最低值。四状态或三类断裂状态缺项、空记录拒绝评分；定义见[严格 holdout 指标](../finetune/holdout_metrics.py)。先获得 test 使用授权，再执行：

```sh
"$PYTHON" -m versioning data claim --root "$STORE" --version "$HOLDOUT_DATA" \
  --eval-version "$EVAL" --model-version "$MODEL" --split "$SPLIT" \
  --executor "$EXECUTOR" --pre-registration "$PREREGISTRATION"
"$PYTHON" -m versioning eval prepare "$EVAL" --root "$STORE" \
  --model-version "$MODEL" --model-version-number "$MODEL_NUMBER" \
  --data-version "$HOLDOUT_DATA" --config "$EVAL_CONFIG" --git-commit "$GIT_COMMIT" \
  --media-root "$STORE/data/releases/$HOLDOUT_DATA/media" --executor "$EXECUTOR" \
  --pre-registration "$STORE/evaluations/staging/$EVAL/authorization/pre_registration.yaml"
"$PYTHON" -m versioning eval validate "$EVAL" --root "$STORE"
"$PYTHON" -m versioning eval run "$EVAL" --root "$STORE"
"$PYTHON" -m versioning eval score "$EVAL" --root "$STORE" --executor "$EXECUTOR"
"$PYTHON" -m versioning eval export "$EVAL" --root "$STORE"
```

prepare/validate/run 不读真值。run 仅媒体推理，完成后等待 score，不创建折子 Run。score 核验同一 executor、冻结规则、预测和权重，再访问受限真值；七门均通过才 passed。无论质量通过或失败，评分均消费一次性授权；迁移、备份、恢复不重置消费状态。

实际七指标、预测、真值快照及逐样本评分保存在 `workspace/evaluations/<eval>/restricted/`，目录 0700、文件 0400，不上传普通 MLflow artifact。公开结果仅含七个 `gate_<指标名>` 0/1 状态与绑定证据，导出或服务准入不重读真值。权限控制不等于独立账户沙箱，须另保证受限运行环境。

恢复只允许同一完整绑定：尚未提交评分承诺时需重新授权核验原真值；已有承诺的完成或导出中断可用同一 score 恢复，不重新推理或重读原真值。推理中断且缺完整凭据、跨身份、内容漂移均拒绝。完整恢复条件见[接口规范](../versioning/SCRIPTS.md#full-模型的独立-holdout-验收)，不清空 authorization 后重试。

## 6. 晋级、备份范围与服务物化

晋级按用途复验，`semantic-v4.1` 开发结果和 `performance-v1` 性能结果均不能充当独立质量结果。新 `semantic-holdout-v4.1` 质量要求 full 模型、真实非合成评审完整性证据；candidate、approve、current 还要求同模型数值版本及配置的性能绑定。用户已确认新准入统一要求新独立质量加性能；停止以旧 strict 结果新增晋级/服务资格。既有 strict 记录保留原定义读取，已批准或已存在 alias 仅可按原模型、eval、alias 和用途绑定幂等恢复，不能改绑、换 alias 或借恢复新增服务资格。

正式评测 passed 且精确绑定模型数值版本后，单向 finalize；已有不同 eval 绑定不可改写。以单一部署目标模型为例：

```sh
"$PYTHON" -m versioning model finalize "$MODEL" --root "$STORE" --eval-version "$EVAL"
"$PYTHON" -m versioning model scope "$MODEL" --root "$STORE" --backup-scope adapter
"$PYTHON" -m versioning model manifest "$MODEL" --root "$STORE" \
  --target "$STORE/records/models/$MODEL/manifest.yaml"
"$PYTHON" -m versioning model alias "$MODEL" --root "$STORE" --alias candidate
"$PYTHON" -m versioning model current --root "$STORE" --alias candidate --service-mode development
```

新语义路线还须在服务 alias/批准前执行 `model bind-performance "$MODEL" --root "$STORE" --eval-version "$PERFORMANCE_EVAL"`，其中 `PERFORMANCE_EVAL` 为同一模型的独立 performance eval。绑定会重验模型/数值版本、Prompt、generation、量化、artifact 及抽帧预处理实现，要求非合成、完整显示端 E2E 和 passed；已有不同绑定不能替换。新准入还要求质量 execution 的 `runtime_attestation` 与性能的 runtime_variant/device/quantization_bit 完全一致；默认真实 runtime collector 已接线；本轮现场 attestation 未取得，缺少或不一致时拒绝，自报标志不能补证。manifest 保存质量/性能分开的 `evaluation_binding`，备份必须保留双方 Run/输入/产物，恢复后继续重验，不把恢复当作新资格。当前合成评审和未验真的显示端证据会被拒绝，所以上述命令示例不表示新生产通路已通过。

scope 是持久化的备份范围声明，不能把设置 scope 当作备份完成；只允许从 adapter 升级为 production_bundle。candidate 要求 finalized/passed、完整训练/评测证据、唯一 deploy_target 和有效 scope。`current` 再次验签并原子物化 `workspace/models/current`；它是显式服务缓存，不是可缺省的数据或模型版本指针。

production 须具 `production_bundle`、真实批准及对应准入条件。`production_bundle` 是备份范围机制，不提供 merged 合并或登记能力；缺少真实 merged 证据通路时，设置此 scope 不能证明完整生产交付链已经通过。只有用户明确批准生产使用后才执行 `model approve`，再设置 production alias，并以 `--alias production --service-mode production` 物化与启动。development 成功不能代替生产批准。三折组不能晋级为部署目标。

## 7. 服务配置、启动与真实媒体检查

本节的单次 smoke 只验证链路与身份，不能替代[性能验收](model-evaluation.md)。`serve_smoke.py` 的 300 秒请求超时不是“全部合格请求至少 95% 在五分钟内自动完成”的实测成绩。性能配置、事件统计、受控 session 和导出已接线；真实 GPU 采集及可信显示端测点尚未验收。只有后端响应时，须明确标记尚缺结果显示端证据。

已选新设计为 eval 的 performance 用途与独立临时受控端点，精确模型/权重/Prompt/变体和开发媒体白名单，不借 candidate/production alias、不用裸路径或test；模型可尚未质量/性能通过，但来源必须有效。性能 passed 不等于视觉 passed，各导出和准入须验用途。性能入口及限制见下节；本节以下服务命令仍使用正式 alias。评测 Agent 判读不算被测服务自动完成，也不把判读等待拼成五分钟成绩。

性能操作者须单独分配 `PERFORMANCE_EVAL` 和 `PERFORMANCE_CONFIG`，使用已验证的开发 data、明确 validation fold 与 `media_ids` 白名单。配置冻结 `generation`、显式 `quantization_bit`、`runtime_variant`（dtype、实际预处理摘要及 LLaMA-Factory/transformers 版本）、`device`（runtime_device、gpu_count）、`executor`、`session_id`、`issued_at/expires_at`、`phase`、`budget_gpu_hours`、资源增长策略（algorithm 为 window-net-growth），以及媒体分层/缓存/重复/retry/warmup/cold_start/client_instrumentation 七项 policy。warmup 必须为 `{request_ids: [显式ID...]}`，正式请求开始前全部终结，不能事后增加或换类。base 显式给任务 Prompt，trained 继承登记 Prompt；base、成功诊断折和 full 来源可测，test/holdout 在读取样本前拒绝。完整字段与 API 见[参数索引](../versioning/SCRIPTS.md#受控性能测量)。

```sh
"$PYTHON" -m versioning eval performance_prepare "$PERFORMANCE_EVAL" --root "$STORE" \
  --model-version "$MODEL" --model-version-number "$MODEL_NUMBER" --data-version "$DATA" \
  --config "$PERFORMANCE_CONFIG" --git-commit "$GIT_COMMIT" --media-root "$MEDIA_ROOT" \
  --data-inputs "$DATA_INPUTS"
"$PYTHON" -m versioning eval performance_validate "$PERFORMANCE_EVAL" --root "$STORE"
"$PYTHON" -m versioning eval performance_run "$PERFORMANCE_EVAL" --root "$STORE" \
  --performance-evidence "$PERFORMANCE_EVENTS"
"$PYTHON" -m versioning eval performance_export "$PERFORMANCE_EVAL" --root "$STORE"
```

`PERFORMANCE_EVENTS` 是受控采集器或合成测试提供的事件 JSON，schema 为 `tensile.performance-events/v1`；`performance_run` 导入、重放和封存事件，不隐式启动真实模型。prepare 以 ffprobe 和实际字节冻结白名单到 `workspace/evaluations/<eval>/input/evaluation.yaml`；执行保存 `output/events.json`、`summary.json` 和 `evaluation.yaml` 到同一 MLflow Run，export 重算全部原始事件/资源序列并发布 `records/evaluations/<eval>/manifest.yaml`。不可覆盖已有 output 以重置失败或分母。

`versioning.performance.ControlledPerformanceSession` 提供受控 session API：加载前和每次请求重验 Registry 来源、权重、冻结输入、executor/session、TTL 和开发媒体；仅 loopback、独立 token，复用实际 adapter；退出只关闭本 session。`open_performance_session(root=..., eval_version=..., executor=..., session_id=...)` 默认使用 `RegistryPerformanceLoader`，从 Registry 物化权重并核验实际 device/dtype/量化；4-bit 配置在 `runtime_variant.quantization` 精确冻结 `quant_type: nf4`、`double_quant: true`、`compute_dtype`、`quant_storage`、`skip_modules: [resampler]` 和 `excluded_module_dtype: bfloat16`，逐实际模块核验计算类型与存储类型，不把 uint8 存储视为计算精度；调用 `session.serve(port=...)` 启动、`session.export_events(path)` 封存采集事件，`session.close()` 关闭。该 API 会真实加载模型，只有取得训练机运行授权后才调用；本轮未调用。`run_performance_session(root=..., eval_version=..., executor=..., session_id=..., port=..., evidence_path=...)` 封装启动及 finally 清理：临时 `.session.json` 以 0600 保存本地 capability，退出后导出事件并删除该文件，只关闭自己的服务。CLI 对应 `eval performance_serve "$PERFORMANCE_EVAL" --root "$STORE" --executor "$EXECUTOR" --session-id "$SESSION_ID" --port "$PORT" --performance-evidence "$PERFORMANCE_EVENTS"`，它会真实加载模型，本轮未启动。采集器周期读取本进程 nvidia-smi VRAM、psutil RSS 与 GPU 保留时长预算；缺采集器报告证据缺口，不填零。不能以裸路径或服务 alias 绕过。预检预算最多 1 GPU 小时、正式最多 20 GPU 小时；到期/耗尽停止新请求并保留未完成事实。

事件 schema 以上传完成为唯一请求起点，支持排队、读取、预处理、推理、自动解析、后端完成与显示完成；当前受控 adapter 实际采集外层排队/推理/自动解析/后端完成，读取和预处理尚缺内部细阶段 hooks，报告 `stage_measurement_gaps`，不据事件名称声称已测得这些分阶段耗时；OOM 只按显式事件统计，通用 adapter 500 不冒充已诊断 OOM；重试保留同一 request 的原时钟、失败事实和分母。合格请求按 ≤60 秒/100 MiB、MP4/H.264、8-bit、≤1920×1080（按长短边）、≤60 fps 检查；正式不少于 100 请求且连续 30 分钟，全部合格请求至少 95% 在 300 秒内自动完成显示、失败率不超过 1%，无 OOM/crash/持续资源增长。预热单列；600/660 秒分别为后端/客户端绝对超时，300 秒超标不自动 kill。Agent/人工判读不能计自动成功。

`versioning/performance_receipts.py` 已提供显示端 receipt 接收与双签名核验。操作者在 prepare 前可冻结 `client_attestation_policy`：schema `tensile.performance-display-policy/v1`、client_id、client_source_sha256、instrumentation_sha256、由 `server_source_digest()` 取得的 server_source_sha256、不同的 client/server Ed25519 公钥、同 session_id 和 clock_protocol `client-monotonic-ns-upload-complete-to-render-v1`。私钥不入 plan；serve 从 `PERFORMANCE_SERVER_SIGNING_KEY_FILE` 的 owner-only 文件读取服务端私钥并核对公钥。

受控模型请求携带 32-byte hex 的 `x-performance-upload-nonce`，同 request 重试不变。client 通过 `GET /v1/performance/backend-receipt/{request_id}` 取得服务端签名的原上传/后端完成/输出摘要及 challenge，再用 `make_display_receipt` 与 `sign_document` 形成客户端签名包，向 `POST /v1/performance/display-receipt` 提交 `{receipt: ...}`。接口绑定冻结来源、session、客户端单调时钟、nonce、raw/完整自动字段和原请求；跨请求时钟不能回退，首次 receipt 锁定。`POST /v1/performance/finish`（body `{}`）仅在无进行中请求且所有自动成功均有签名显示凭据时正常结束本 session，随后服务端签整个 ledger。

客户端模型无关接线可使用 `versioning.performance_client.PerformanceClientBridge`：先 `begin_request`/`request_headers`，上传完成事件调用 `upload_complete`，拿到完整raw后 `receive_output` 验证服务回执；外部instrument确认完整raw与自动字段实际显示后 `display_complete`，再 `submit_receipt`/`finish`。重试保持ID/nonce/首次起点，签名器与transport均注入；适配器本身不能证明DOM或授真实资格。

真实性能 passed 要求非 synthetic、可信 client/server receipt 和 ledger 签名、实际 runtime collector 资格、clean finish 及全部原性能门同时成立；缺 policy/凭据/签名、未验真时间或合成事件均不能替代。OOM、挂起超时及不明后台状态会停止接收新请求。接收/核验工程已实现，外部客户端与真实显示测点尚未部署或验收，本轮未修改 TensileAgent，也未执行真实 client/model；本轮所有报告仍 synthetic、不得 passed。后端和未验真显示时间分别报告其测量边界，success P95 只辅助，不能替代全分母按时率。

先静态解析同一 store/alias/mode：

```sh
"$PYTHON" scripts/serve_manage_model_registry.py --root "$STORE" \
  resolve-current --alias candidate --service-mode development
"$PYTHON" scripts/serve_validate_delivery.py --root "$STORE" \
  --alias candidate --service-mode development
```

核对完整 model 身份、数值版本、base_model_version、fingerprint 和冻结 Prompt。`runtime_verified: false` 只表示静态检查，不能作为真实推理成功。

复制[部署 JSON 模板](../pipeline/server_deployment_manifest.example.json)到包外明确路径 `STARTUP`。model_version 与 adapter_version 都填所选完整模型身份；base_model_version 与 config_fingerprint 来自上述 resolver；processor_version、transformers_version、llamafactory_version、runtime_device、runtime_dtype 来自实际运行环境，max_frames 与冻结配置一致（V4.1 上限 8）。模板占位值不能保留。服务逐字段比对训练、正式 Prompt 与 passed eval 的冻结正文，动态 analysis 契约由该 Prompt 派生。

准备真实基座、artifact 缓存、可用 GPU 及磁盘，核对未占用的 `PORT`；`API_KEY` 从受限环境读取，不入 Git。取得推理授权后前台启动：

```sh
"$PYTHON" -m pipeline.server_proxy --root "$STORE" \
  --alias candidate --service-mode development --contract-version tensile-vlm/v4.1 \
  --deployment-manifest "$STARTUP" --host 127.0.0.1 --port "$PORT"
```

加载前后均重核绑定，漂移拒绝；裸 `--model` 路径不能绕过。另一个 shell 使用同一端口和 API key 预检：

```sh
curl --fail --silent --show-error -H "Authorization: Bearer ${API_KEY}" \
  "http://127.0.0.1:${PORT}/v1/tensile/contract"
```

核对动态 contract_version/hash、deployment_manifest 和 Registry 完整身份、数值版本、fingerprint，HTTP 200 本身不证明身份或质量正确。`VIDEO` 须为获准使用且可追溯的真实视频，不为方便使用受限 test 材料。执行：

```sh
"$PYTHON" -m pipeline.scripts.serve_smoke --root "$STORE" \
  --alias candidate --service-mode development --contract-version tensile-vlm/v4.1 \
  --base-url "http://127.0.0.1:${PORT}" --video "$VIDEO"
```

保留合法四字段输出、request ID、实际帧映射、tensor digest/shape、运行身份及日志；smoke 证明服务链路，模型质量依据正式评测。客户端使用同一冻结 Prompt 和动态契约，经兼容检查后交接，跨机连接使用 SSH tunnel。换模重新核对 alias、权重、Prompt 和部署 JSON；已有进程不会因 alias 改变自动切换。停止已有服务或他人任务须明确授权。

## 8. 备份与隔离恢复

备份先物化作用域模型，确认实际源完整，然后在训练机创建静态快照：

```sh
"$PYTHON" -m versioning model materialize "$MODEL" --root "$STORE"
"$PYTHON" -m versioning backup create --root "$STORE" --backup-root "$BACKUP"
"$PYTHON" -m versioning backup verify --root "$STORE" --backup-root "$BACKUP"
```

`BACKUP` 是已核对容量且不与源重叠的明确位置。adapter 范围保留声明 adapter；production_bundle 按机制保留已合法声明的 adapter 与 merged，不创建或补证 merged。当前训练证据链只有 adapter，不能将 scope 设置当作真实 merged 备份或生产链验收。快照包含数据、Prompt、模型 manifest 及按范围裁剪的 MLflow SQLite、训练 input/证据和绑定评测产物，不能据 scope 假定未声明权重已保存。外部基座和媒体不自动纳入，迁移发布引用的旧媒体目录不能因此删除。

跨机接收使用 `backup transfer`，显式提供已完成的源快照、SSH 主机、catalog SHA-256 和不存在的目标；只读远端，不传正在写入的 store，接收后再 verify。认证使用已有 OpenSSH 密钥。完整参数、权限及空间边界见[备份接口](../versioning/SCRIPTS.md#已完成备份的跨机传输)。

恢复到明确隔离根 `RESTORE_ROOT`，对象目标不存在，MLflow 目标也可为空普通目录：

```sh
"$PYTHON" -m versioning backup restore --root "$RESTORE_ROOT" --backup-root "$BACKUP" \
  --data-root "$RESTORE_ROOT/data" --prompts-root "$RESTORE_ROOT" \
  --models-root "$RESTORE_ROOT/workspace/models/materialized" \
  --mlflow-root "$RESTORE_ROOT/workspace/mlflow"
```

base/diagnostic 备份保留来源 receipt 和字节快照；diagnostic 还保留父 train 共享 input 和对应折 execution receipt。base 没有训练 Prompt，完整基座使用 production_bundle 备份范围，名称不表示生产批准。恢复不改外部基座冻结路径，仍须可核验原基座字节。

恢复重定位 MLflow 活动 artifact 地址，保留身份、alias、授权消费事实与冻结来源原文，不自动选服务 current。外部基座仍需在冻结引用路径可用并验签；重新训练或评测还须备齐原媒体、输入及代码依赖。四类对象发布不是整体事务，后段 I/O 失败可留下已发布部分；先检查结果，再向新隔离目标恢复，不自动覆盖或清理。

隔离副本通过记录与内容核查后，再显式执行 `model current --root "$RESTORE_ROOT" --alias candidate --service-mode development`，仍受同一准入门约束。已有 CPU 合成恢复记录只覆盖存储接线与拒绝行为，不能证明真实模型、外部依赖、大型权重或移动介质的整机恢复。不得删除唯一真实源来模拟故障。

## 操作失败与验收记录

缺身份、基座、媒体、正式证据或资格时停止在对应前置准备；内容漂移时核对来源，不手改摘要通过门禁；失败或中断保留 Run 和已有输出，不自动重跑。每次真实执行记录机器、代码提交、输入/输出路径、完整对象绑定、命令、结果和限制，再交接台账。

详细接口以 [versioning/SCRIPTS.md](../versioning/SCRIPTS.md)、[训练准备实现](../finetune/train_prepare_run.py)、[Registry 门禁](../versioning/registry.py)、[服务入口](../pipeline/server_proxy.py)为依据。既有工程验证及其范围见[迁移验证记录](results/version-control-migration/verification.md)；当前能力与缺口见[项目现状](project-status.md)，任务和执行顺序以[唯一台账](project-todo.md)为准。
