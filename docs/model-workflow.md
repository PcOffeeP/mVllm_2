# 模型训练、评测与服务

本说明面向已经准备好数据、希望训练或运行模型的使用者。环境安装从[快速开始](../README.md#快速开始)进入；开发数据与独立 test 数据的构建见[数据处理](data-workflow.md)。正式操作统一使用 `python -m versioning`，所有版本使用 `data / prompt / train / model / eval` 五类完整身份，例如 `train-v4.1-r<N>`，其中 `<N>` 必须替换为明确分配的序号。

项目已实现冻结训练输入、三折与全量训练、严格评测、Registry 晋级及服务门禁。现有历史开发结果尚不能证明最终模型质量；新体系真实合格模型的加载与媒体推理成功路径、独立 test 使用资格、大型产物组合恢复仍未完成验收。命令接线和 CPU 合成验证不等于真实模型验收。

**开发测评显式区分协议。** `strict-v4.1` 保留历史严格评分；新开发配置选择 `semantic-v4.1`，使用全样本语义评分、独立格式诊断和逐折开发门。基座与成功折诊断来源已接入同一 Registry。接口及合成检查不构成真实模型质量证据；新 holdout、真实低权限盲评进程、受控性能入口和完整生产准入仍按[实施计划](plans/model-evaluation-implementation.md)推进，实际状态见[项目 TODO](project-todo.md)。不得修改旧门或补写 passed 代替新协议证据。

基座真实来源登记、已完成折快照诊断、开发语义统计及已封存盲评答案导入已接入代码。预测判读策略默认两个 Agent 独立处理，分歧交第三个先独立再仲裁；可扩人数但配置预先冻结，不要求多个真人。纯导入接口不执行判读，也不证明真实隔离：本地评审进程、账户权限、安装摘要及现场输入仍须核验，新 holdout 和独立性能入口仍待实施。设计确认和接口实现均不授予真实模型调用、受限数据发送或测试集使用权限。

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

`BASE_MODEL`、`DIAGNOSTIC_MODEL` 都是调用者分配的完整 model 身份。基座目录须含实际权重、config、tokenizer/processor，来源与固定 revision 须先核实；可用 config 来源字段或可识别 HF snapshot 路径须与声明一致；二者不足时，目录须含 `source-provenance.json`，schema 为 `tensile-base-provenance/v1`，含匹配的 upstream_source/upstream_revision 及非空 verified_by。该文件随字节冻结；一致性检查不等于密码学证明上游真实性。不接受 main/latest 等活动引用，不自动下载或升级。登记创建来源 Run 的实际字节快照和 `model-source.json`，不造 train/data/Prompt。基座评测另显式绑定开发 data 与任务 Prompt。

诊断来源只接受真实 FINISHED 折的 execution receipt 和 adapter，冻结 checkpoint step、父 train/run、共享输入、基座与真实折号；不接受任意中途 checkpoint 或自定义 artifact。父 train 保持 partial，后续使用重验共享输入及来源。base/diagnostic 只用于开发测评；性能受控入口尚待实现，不能借 candidate/production alias 部署，也不能 finalize 为生产资格。

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

接口可执行性和合成验证只证明接线、统计及拒绝逻辑，不能据此声称完成真实模型调用、训练机评测或质量通过；真实运行证据以项目 TODO 的验收记录为准。真实低权限 Agent 工作区、Ollama 运行和权限隔离尚未完成，内容封存/访问声明不能代替技术隔离。新 holdout、性能与服务全链分别属于后续实施范围。

## 5. Full 模型的独立 test 验收

**以下七门是现行旧协议的代码事实，不是新确认的最终视觉标准。** 新标准及格式分离规则以[测评方案](model-evaluation.md)为准，但新 holdout 授权评分、受限盲评与最终导出/准入绑定尚未实现；开发侧的语义与盲评导入不能替代这些环节。以下命令不能执行新语义验收；旧身份、旧报告与已消费 test 的限制保留，新协议不得重新利用已暴露 test。

新语义环节采用匿名多 Agent 判读而非双真人审查；Agent只见固定回答/手册，不能访问GT/视频/被测模型身份或其他初判，未决才交用户盲态复核或计失败。发包的预测 exposure、逐 Agent 结果封存和同身份恢复需新增实现；现行 run 不读真值、score 才读真值并在完成时消费授权的时点不改写为已存在的新功能。匿名包发放和外部 Agent 调用仍须具体授权及权限核验。

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

本节仍复验现行评测证据。未来新方案还需精确绑定语义协议、盲评证据及分开的质量/性能结论；旧 passed 不自动获得新质量或交互性能资格，格式放宽也不扩大现有 production 授权。

正式评测 passed 且精确绑定模型数值版本后，单向 finalize；已有不同 eval 绑定不可改写。以单一部署目标模型为例：

```sh
"$PYTHON" -m versioning model finalize "$MODEL" --root "$STORE" --eval-version "$EVAL"
"$PYTHON" -m versioning model scope "$MODEL" --root "$STORE" --backup-scope adapter
"$PYTHON" -m versioning model manifest "$MODEL" --root "$STORE" \
  --target "$STORE/records/models/$MODEL/manifest.yaml"
"$PYTHON" -m versioning model alias "$MODEL" --root "$STORE" --alias candidate
"$PYTHON" -m versioning model current --root "$STORE" --alias candidate --service-mode development
```

scope 是持久化的备份范围声明，不能把设置 scope 当作备份完成；只允许从 adapter 升级为 production_bundle。candidate 要求 finalized/passed、完整训练/评测证据、唯一 deploy_target 和有效 scope。`current` 再次验签并原子物化 `workspace/models/current`；它是显式服务缓存，不是可缺省的数据或模型版本指针。

production 须具 `production_bundle`、真实批准及对应准入条件。`production_bundle` 是备份范围机制，不提供 merged 合并或登记能力；缺少真实 merged 证据通路时，设置此 scope 不能证明完整生产交付链已经通过。只有用户明确批准生产使用后才执行 `model approve`，再设置 production alias，并以 `--alias production --service-mode production` 物化与启动。development 成功不能代替生产批准。三折组不能晋级为部署目标。

## 7. 服务配置、启动与真实媒体检查

本节的单次 smoke 只验证链路与身份，不能替代[性能验收](model-evaluation.md)。`serve_smoke.py` 的 300 秒请求超时不是“全部合格请求至少 95% 在五分钟内自动完成”的实测成绩。新性能采集、统计与完整交互测点均待实施；只有后端响应时，须明确标记尚缺结果显示端证据。

已选新设计为 eval 的 performance 用途与独立临时受控端点，精确模型/权重/Prompt/变体和开发媒体白名单，不借 candidate/production alias、不用裸路径或test；模型可尚未质量/性能通过，但来源必须有效。性能 passed 不等于视觉 passed，各导出和准入须验用途。本节以下现有服务命令不能直接启动该入口；评测 Agent 判读不算被测服务自动完成，也不把判读等待拼成五分钟成绩。

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
