<!-- DOCUMENT-CONTRACT
Purpose: 定位 versioning 的实际入口，并提供显式数据输入与人工交接的操作边界。
Scope: CLI 模块索引、七阶段数据命令、输入契约、DVC 配置、审查包回收、Prompt注册与冻结、三折训练、正式验证集测评及备份传输入口。
Must Preserve:
- 五类完整可读身份、显式输入与 fail-closed，不引入当前版本回退。
- 区分数据业务处理、人工决定和正式封存；不能把测试替身当真实媒体验收。
- 已切换入口按确认方案停用旧写入；历史对象与仍被调用的业务实现保留，新入口不读旧活动指针或创建旧集合身份。
Non-goals:
- 不替代训练、测评、部署及备份各自的验收规范。
- 不保存本次实施进度、临时主机状态或迁移授权。
-->

# versioning 入口与模块索引

统一入口为 `python -m versioning`；正式版本参数必须使用完整
`<kind>-v<协议>-r<N>` 身份，缺失或非法引用会以非零状态停止。

| CLI 领域 | 主要模块 | 作用 |
| --- | --- | --- |
| `data` | `data_pipeline.py`、`data_release.py`、`holdout.py` | 七阶段 DVC 数据 pipeline、封存、训练引用门、预注册冻结与 holdout claim |
| `prompt` | `prompts.py` | 注册不可变 Prompt，并冻结/校验训练 input 副本 |
| `train` | `mlflow_train.py`、`finetune/train_prepare_run.py`、`finetune/train_with_contract.py` | 冻结六份数据与三折配置、真实训练调用、父子 Run、汇总与完成后导出 |
| `eval` | `finetune/eval_run.py`、`mlflow_eval.py`、`manifest.py` | 正式validation输入冻结、Registry精确引用、实际推理与严格评分、父子Run和不可变导出；低层holdout授权记录API保留 |
| `model` | `registry.py`、`manifest.py`、`materialize.py` | `mVllm2` 两阶段 register/finalize、model manifest、唯一部署目标 gate、alias 与 `models/current` 原子物化 |
| `backup` | `backup.py` | 离线备份 catalog、完整性验证与显式目标恢复 |
| `migration` | `migration.py` | 从显式 object mapping 执行 Prompt/Data 只读预检或迁移，从声明 entry 纯构建或固定路径发布 history-summary |

`cli.py` 只编排上述领域模块，不实现第二套状态或身份规则；`__main__.py` 仅转发统一入口。

## Prompt注册与冻结

现行入口为`python -m versioning prompt`。操作者准备定义YAML，包含非空`system_prompt`、`user_prompt`与非空且无重复字符串的`output_fields`列表；可给`protocol_label`以保存业务协议标签。定义不是旧active_prompt.yaml格式，不能直接把旧文件当新定义发布。已有Prompt应按确认mapping走migration，保持原正文和身份对应。

```sh
python -m versioning prompt create --root <store绝对路径> \
  --version <完整prompt版本> --protocol <版本协议段如v4.1> --definition <定义YAML>
python -m versioning prompt show --root <store绝对路径> --version <完整prompt版本>
```

create在`records/prompts/<完整prompt版本>.yaml`创建正式对象，版本协议段须匹配，已有版本拒绝覆盖或自动加号。正文/schema有效不代表模型质量通过。训练通常由`train prepare`绑定这个Prompt；单独冻结和复验可使用：

```sh
python -m versioning prompt freeze --root <store绝对路径> \
  --version <完整prompt版本> --train-version <完整train版本>
python -m versioning prompt verify --root <store绝对路径> \
  --version <完整prompt版本> --train-version <完整train版本>
```

冻结副本位于`workspace/runs/<train>/input/prompt.yaml`，正式对象仍以records/prompts为权威。旧`python -m pipeline.prompt_control validate/publish`及其脚本入口均已停用；旧core读取、校验和发布函数保留历史业务回归，不是现行操作接口。

## 三折训练准备与执行

`train prepare` 显式选择一个完整 train、data 和 prompt 身份。一个 train 包含 fold0、fold1、fold2；每折使用 release 中对应的 train/validation 文件，保持成员、顺序和标签，不重新划分或增加采样。`--config` 指向调用者准备的 YAML：顶层恰好为 `fold0`、`fold1`、`fold2`，各值为该折的完整 LLaMA-Factory 训练配置。`model_name_or_path` 必须为实际存在的绝对目录，三折相同；其余超参数原样保留。准备器只绑定数据集名称、冻结数据目录、显式媒体根和该 train 的输出目录；拒绝可能绕过这些输入的 `tokenized_path`。

`--environment` 指向调用者核实的依赖版本 YAML（例如实际 Python、torch、transformers、LLaMA-Factory 版本），`--git-commit` 记录执行代码版本。版本号和配置必须由调用者明确选择；以下尖括号是必填占位符。

```bash
python -m versioning train prepare <完整train版本> \
  --root <store绝对路径> --data-version <完整data版本> \
  --prompt-version <完整prompt版本> --config <三折配置.yaml> \
  --environment <依赖版本.yaml> --git-commit <代码commit> \
  --media-root <实际媒体根>
python -m versioning train validate <完整train版本> --root <store绝对路径>
```

迁移数据通过该 store 的 committed receipt 核验平铺发布内容；七阶段数据须额外传 `--data-inputs <原inputs.yaml>`，复验原发布链及 `payload/`。迁移数据的媒体根通常是原训练机项目的 `workspace/data`，来源镜像不能替代它；自包含七阶段发布使用该版本 `payload/` 作为媒体根。准备时冻结实际视频 SHA/大小，执行前复验媒体内容。检查、准备及验证不会创建 MLflow Run 或加载模型权重。

准备产物为 `workspace/runs/<train>/input/`，含 `data-version.txt`、`prompt.yaml`、`training.yaml`、`environment.yaml`、六份数据 JSON、`dataset_info.json` 和内容校验清单。正式 Prompt 必须预先存在于 `records/prompts/`。旧记录中的样本数量与历史训练结果不会因准备而改变。

取得训练授权后，在训练机运行 `python -m versioning train run <完整train版本> --root <store绝对路径>`。该命令调用真实训练适配器，使用冻结配置，向 `<store>/workspace/mlflow` 写入父 Run 和三个子 Run；每折实际 `train_results.json` 必须有有限数值指标，产物上传到父 Run 的 `foldN/adapter`。三折和汇总完成后导出 `records/training/<train>/manifest.yaml`。训练损失汇总不代表质量通过。

完成后的导出若失败，可用 `python -m versioning train export <完整train版本> --root <store绝对路径>` 从同一 completed Run 补导出；不重新训练，不覆盖不同内容。已有训练输出或失败 Run 不会由 `run` 自动覆盖或恢复；须先核对原 Run 和 checkpoint 后处理。底层 `create/fold-start/fold-end/summary/complete` 是记录 API，手动推进状态不能替代上述实际执行证据。
完整参数运行 `python -m versioning <领域> --help` 查看。
迁移命令不会扫描 sibling 或选择“当前”对象：Prompt/Data 动作必须显式给出
`tensile-migration/object-mapping/v1` 映射文件，history 动作必须显式给出 entry YAML 列表，
六个 migration 动作都必须显式给出 `--root`。映射或 entry 中的重复 YAML 键会被拒绝；
预检报告为 `blocked` 时保留 JSON 拒因并以非零状态退出。

所有正式写入都要求显式版本；CLI 的项目数据根必须显式传入，Registry、eval、alias 与
manifest 在操作时在线复验其 train/data/eval 血缘。测试中的临时 store 推断不属于正式入口。
服务物化必须显式给出 `service_mode` 与 alias；三折模型组不具备唯一 `deploy_target`，只能用于
比较和聚合测评，不能成为 candidate、production 或 `models/current`。

模型备份按 `offline_backup_scope` 实际裁剪文件：`adapter` 只包含
`materialized.yaml` 与 Registry 声明的 adapter 路径；`production_bundle`
包含声明的 adapter 与 merged 路径。每个作用域模型的严格 manifest 一并恢复到
`records/models/<id>/manifest.yaml`；MLflow store 仅保存 SQLite、上述声明训练产物
和已绑定正式测评产物，不通过整树复制夹带 adapter 模型的 merged。

## 正式验证集测评

`eval prepare / validate / run / export` 连接实际严格V4.1推理与评分器。当前支持已注册的`single_fold`（fold0）或`cross_validation`（fold0/1/2）模型，逐折使用显式data版本的完整validation划分；不新增采样。`full`与holdout的实际读取尚未接入，这四个动作在读取数据内容或加载权重前拒绝该范围。既有低层`create/fold-start/fold-end/aggregate/summary/complete`与holdout授权API保留，手动状态或历史summary不构成实际执行证据。

先由完成的train通过`model register`登记模型，取得完整model版本与数值MLflow Model Version；Registry声明必须有每折所选adapter或merged artifact。Prompt来自该模型的训练绑定，须已位于store的`records/prompts/`。data输入使用已验证的迁移receipt，或用`--data-inputs`提供七阶段发布的原始输入。媒体根使用原实际外部媒体目录，不能把迁移来源镜像当作媒体根。

准备命令：

```bash
python -m versioning eval prepare <完整eval版本> --root <store绝对路径> \
  --model-version <完整model版本> --model-version-number <Registry数值版本> \
  --data-version <完整data版本> --config <评价配置YAML> \
  --git-commit <核实的代码提交> --media-root <实际媒体根绝对路径>
```

评价配置必须精确包含下列字段，不接受重复YAML键或额外参数：

| 字段 | 取值与含义 |
| --- | --- |
| `scope` | `single_fold`或`cross_validation`，必须与Registry模型一致 |
| `split` | `validation` |
| `artifact_kind` | 显式选择`adapter`或`merged`，每折必须具备该artifact |
| `scorer`、`sample_selection` | 分别为`strict-v4.1`、`all` |
| `quantization_bit` | 显式`null`或`4` |
| `aggregation` | 必须显式写`pooled`，确认按各折实际样本行合并评分；省略或其他规则会拒绝 |
| `generation` | 精确mapping：`do_sample: false`、`num_beams: 1`、`max_new_tokens: 256`、`video_max_frames: 8` |
| `thresholds` | 必须显式给出非空mapping，各值为已确定的0到1最低阈值，全部达到才判为passed；没有默认质量阈值 |

阈值可用指标为`contract_valid_rate`、`joint_correct_rate`、`clip_state_correct_rate`、`fracture_mechanism_correct_rate`、`fracture_site_correct_rate`、`special_case_correct_rate`。分母为所选样本数，空值与非法预测遵守现有严格评分器规则。跨折汇总将各折实际结果按行合并评分，沿用六位小数的指标口径。配置内容、模型绑定、Prompt、样本、媒体摘要、生成参数和评分实现摘要冻结在`workspace/evaluations/<eval>/input/evaluation.yaml`；prepare不下载权重，不创建eval Run，不执行推理。它会访问显式store中的Registry，必要时初始化本地MLflow基础设施。

`python -m versioning eval validate <完整eval版本> --root <store绝对路径>`重核冻结输入和上游内容，不执行推理。取得实际测评授权后，在训练机运行`python -m versioning eval run <完整eval版本> --root <store绝对路径>`。run从冻结输入取得身份，拒绝命令行覆盖model、data、outcome等参数，且只使用`<store>/workspace/mlflow`。权重从已验证的Registry artifact物化到本次私有临时目录；adapter使用Registry绑定的基座目录，基座必须是存在的普通绝对目录。旧加载器需要的下划线目录别名必须解析到同一已核验目录，已有同名其他目录或错误软链接会在加载前拒绝。执行前后核验内容摘要，并保留实际权重摘要。该过程包含权重复制、媒体与权重哈希扫描及GPU推理，资源预算须按实际模型和数据量核定。

每折记录`records.jsonl`、`failures.jsonl`和`summary.json`；正式父Run保存`evaluation.yaml`、汇总`summary.json`及两份合并JSONL。运行失败保留已有结果并标记failed，无正式manifest；解析非法但推理完整属于质量结果，可形成`outcome: failed`。全部结果上传完成后才提交结论并导出`records/evaluations/<eval>/manifest.yaml`，其中保存Run引用、数值模型版本和产物摘要。staging结果不是导出权威。

完成后的导出失败可运行`python -m versioning eval export <完整eval版本> --root <store绝对路径>`：从同一MLflow Run下载并验签结果，按冻结评分实现重核样本/指标/结论，幂等发布manifest，不再次调用模型、不覆盖不同内容。需保留冻结input及相同评分实现。已有输出或失败Run不会自动重跑、覆盖或续跑；进程强制终止、持续后端故障与创建响应丢失后的恢复仍须核对原Run，不将普通异常处理视作这些场景已完成验证。

## 显式数据七阶段

`--root` 是 versioning store 根，`--inputs` 是固定全部真实输入的 YAML；两者职责不同。
七阶段均要求 `--root`、`--inputs`、`--batch`，发布和校验另要求完整 `--version`，
回收另要求 `--results`。`data claim` 沿用独立的 holdout 消费契约。
真实 v4.1 构建当前发布 development；test_audit 媒体单独保留在子视频阶段，不能混入
开发集审查与训练数据。已有两个 legacy release 的迁移使用 `migration data-*`，
不能通过重新运行本链代替语义保持的复制迁移。

输入 YAML 的 schema 为 `tensile-data/inputs/v1`，精确字段如下。所有 pin 都是
`{path: 项目根内规范相对路径, size_bytes: 非负整数, sha256: 完整64位摘要}`；
摘要仅作完整性校验，不作版本身份。路径不能经过符号链接，文件必须存在，内容变化后
不能沿用旧 pin。YAML 重复键、alias/merge、额外或缺失字段均拒绝。

| 字段 | 内容 |
| --- | --- |
| `schema`、`batch`、`project_root` | 上述 schema、显式批次、真实项目绝对目录 |
| `source.videos` | 非空列表，每项在 pin 字段之外含 `video_id`，格式 `video_0001`，与 MP4 文件名一致 |
| `source.annotations.tags`、`source.annotations.mapping` | 两份 pin，内容为现有 source tags/mapping CSV，恰好覆盖声明的视频全集 |
| `split` | 显式 split 描述文件 pin，不重新计算成员 |
| `roi_decisions` | 已完成的人工作业 ROI 决定文件 pin，内容使用既有 ROI schema，完整覆盖 source 且绑定来源/摘要/分辨率 |
| `media.config` | 媒体输入描述 pin，含候选契约与两类历史参考 |
| `media.preprocessor.kind`、`media.preprocessor.config` | kind 必须为 `minicpm`，config 为实际预处理器描述 pin |
| `contract` | 现有 `tensile_vlm_v4_1.json` 业务契约 pin |

`split` 内容精确为 `schema: tensile-data/split-inputs/v1`、`batch`、
`source_sha256`（全部视频 ID 到原视频摘要）、`splits`。
`splits` 含 `test` 和 `fold_0_train` / `fold_0_val` 至三个 fold 的七份视频 ID 列表；
每个 fold 的 train/val/test 不相交且覆盖 source，保留 rare-pool 等已决定的成员分配。

`media.config` 内容精确为 `schema: tensile-data/media-inputs/v1`、
`candidate_contract`、`development_reference`、`test_reference`；后三项都是 pin。
候选契约使用既有 v3 业务契约，两个历史参考必须有同一 `reference_id`，其
`source_inventory` 分别与 development/test 成员一致，`records` 中每个
`reference_record_id` 唯一且绑定本域 source。空历史参考必须由输入明确声明，不能缺文件后回退为空。

预处理器描述精确为 `schema: tensile-data/preprocessor-inputs/v1`、`model_root`
（项目内普通相对目录）、`files`（加载所需配置、处理代码、tokenizer等的完整 pin 列表，
path 仍相对项目根）、`max_frames: 8`、正有限 `video_fps`、实际 `expected_fingerprint`。
至少包含 `config.json` 和 `preprocessor_config.json`，动态模块与相对依赖也须钉扎；
外部 `auto_map` 拒绝。实际 fingerprint 来自既有 `MiniCPMVideoPreprocessor.fingerprint()`，
必须使用同一模型目录和运行参数，不填占位值。运行时从只包含声明文件的独立快照加载处理器，
不会加载模型权重或启动推理。配置准备好后可用 `load_data_inputs` 和 `build_input_dvc_configuration`
先做只读预检；真实媒体运行还需训练机的 ffmpeg、PyAV 与完整 MiniCPM 处理器依赖。

以下变量由操作者明确设置：`PYTHON` 为当前项目解释器的绝对路径，`STORE` 为独立 store，
`INPUTS` 为上述完整 YAML，`BATCH` 与 YAML 一致，`VERSION` 为确认过且未占用的完整 data ID，
`RETURN` 为包外的人工回收 JSON 路径。命令从代码仓库执行；真实媒体处理在训练机进行。

```sh
"$PYTHON" -m versioning data source --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data roi --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data subvideo --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data review_export --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
```

每阶段在 `STORE/data/working/BATCH/<阶段>/` 发布完整目录，带 `stage_manifest.json`。
既有阶段只能在输入、文件和上游完全匹配时复用；漂移时立即停止，不能覆盖旧结果。
`source` 保存媒体/注释/给定 split；`roi` 保存裁剪媒体/冻结决定；`subvideo` 保存两域的
候选计划、真实视频、模型采样帧、采样映射及失败排除原因；`review_export` 包含开发集
待审候选、媒体、历史参考和冻结契约。各阶段无隐式当前批次或当前版本。

将完整 `STORE/data/working/BATCH/review_export/` 复制到 Mac 的普通目录 `PACKAGE`。
包可迁移路径，不能只复制队列 JSON 或替换媒体。Mac 的项目环境中运行：

```sh
"$PYTHON" -m streamlit run pipeline/scripts/review_candidates_app.py --   --versioning-package "$PACKAGE"   --draft "$DRAFT" --output-root "$REVIEW_OUTPUT"
```

本项目由唯一维护者审查；完整审查包模式默认将“项目维护者”写入新人工决定，无需填写姓名。可用 `--reviewer-id` 显式指定其他非空标识，界面显示本次审查者。
历史缺失姓名不要求重新审批，也不改写旧记录。复用历史审批须确认媒体、帧、时间戳和标签一致，并单独保存维护者确认依据。新回收文件仍验证决定完整性与证据绑定。
`DRAFT` 与 `REVIEW_OUTPUT` 都必须位于包外；草稿不能指向
`REVIEW_OUTPUT/review_return.json`。打开包、保存草稿、完成冻结均会复验包；所有候选完成
后生成该回收文件，保留真实审查者、时间、备注、标签和采样证据。不要把 fixture 决定
当成人工结果。旧`--queue`写入模式已停用，参数解析时即拒绝；完整包模式不接受局部候选筛选。

把该回收文件复制到训练机明确的 `RETURN` 路径后执行：

```sh
"$PYTHON" -m versioning data review_import --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --results "$RETURN"
"$PYTHON" -m versioning data release --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
"$PYTHON" -m versioning data release_validate --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
```

release 保存 `data/working/BATCH/release/` 构建证据，并封存
`data/releases/VERSION/payload/` 中的媒体、冻结契约/审查、六份 fold 数据集、dataset_info
与质量计数；`release.yaml`/`README.md` 位于同级元数据边界。DVC store 中另生成 `payload.dvc`，
只跟踪 payload。完整版本已存在时立即冲突；中断遗留 staging 时停止并保留供显式恢复，
不自行删旧对象或改号。`release_validate` 只读校验绑定、全部 payload 文件、封存权限与
训练准入，输出 JSON，不启动训练，也不生成 `release_pointer.json`。

## DVC 配置与手动执行

仓库根 `dvc.yaml` 是七阶段模板，`params.yaml` 无默认数据版本或输入。先由操作者在
`STORE` 初始化 DVC（已有 Git store 用 `dvc init`；明确不使用 SCM 的独立 store 可用
`dvc init --no-scm`），再从代码仓库生成参数化配置：

```sh
"$PYTHON" -m versioning data dvc-config --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --results "$RETURN" --version "$VERSION"
```

`dvc-config` 是配置动作，不是第八个数据阶段。它只生成 store 内的 `dvc.yaml`/`params.yaml`，
覆盖全部显式视频、注释、split、ROI决定、输入配置、业务契约、嵌套历史参考、处理器文件与
实际 Python 实现代码依赖。回收路径可尚不存在，但不能位于阶段输出内；缺少人工回收时
review_import 阻断。命令包含实际解释器和代码位置，跨机器迁移配置时须显式重新生成，
不能复制后假定原绝对路径有效。不同内容的既有配置不覆盖，需先由操作者处理配置冲突。

在 `STORE` 中运行 `dvc status` 只报告过期；`dvc repro review_export` 手动推进到待审包，
完成回收后 `dvc repro release_validate` 继续执行。工作阶段输出使用 persist，输入漂移不会
通过 DVC 自动删除旧结果后悄悄重建；需明确新批次、完整 pins 和新版本。正式封存目录不作为
普通 pipeline out，payload 单独经 DVC 跟踪；恢复后需重新校验封存权限与绑定。不要对全部
已封存 `payload.dvc` 执行强制 commit，pipeline 的测试/补登记限于 `dvc commit --force dvc.yaml`。


## 已完成备份的跨机传输

备份创建仍在训练机执行，输入为显式store、data、Prompt和物化模型根。先完成对应模型的scope声明及物化，并确保所有正式数据与作用域模型的源齐全。示例中的绝对路径必须替换为已核对位置，目标父目录预先存在：

```sh
python -m versioning backup create --root /absolute/store --backup-root /absolute/snapshot
python -m versioning backup verify --root /absolute/store --backup-root /absolute/snapshot
sha256sum /absolute/snapshot/backup_catalog.yaml
```

create复用Registry一致性锁与SQLite快照、粘性scope裁剪，完成后再传输该快照；不要直接传输正在写入的MLflow store。记录上一步catalog摘要并保持源快照不变。Mac使用既有OpenSSH配置/密钥接收：

```sh
python -m versioning backup transfer --root /absolute/local-project --ssh-host configured-training-host --source-backup-root /absolute/snapshot --catalog-sha256 <已核对的64位SHA256> --backup-root /absolute/destination
python -m versioning backup verify --root /absolute/local-project --backup-root /absolute/destination
```

transfer只通过SSH调用远端tar读取显式源目录，不在远端创建快照或修改文件。主机只接受host或user@host形式；不接受shell片段。接收流直接写入目标同级私有临时目录，拒绝绝对路径、越界路径、重复成员、软/硬链接和特殊文件。目标端核对钉扎的catalog摘要、全部声明文件、额外文件及SQLite完整性后才发布目标目录，保留原catalog的身份与verified记录，不重新分配版本。

目标必须不存在，不合并或覆盖已有备份；最终发布使用Mac/Linux原子no-replace接口，文件系统或平台不支持时失败，不回退到可覆盖的rename；同目标并发传输由排他锁拒绝。正常异常会清理本次临时目录和锁，原源与已有目标保持；连接中断后可对同一未变快照重试。进程被强制杀死可能遗留临时目录或锁，需要先确认没有存活传输再人工处置，入口不会猜测锁失效。升级scope后在训练机重新create并核对新catalog，再传输到新的明确目标。实际磁盘空间至少容纳所选快照，目标同级临时目录发布后即成为最终备份，不另外保留整份tar；大产物应直接写到已核对的目标存储，不默认暂存Mac内置盘。

恢复仍使用既有restore入口，四类输出根必须核对且不得覆盖正式对象：

```sh
python -m versioning backup restore --root /absolute/isolated-project --backup-root /absolute/destination --data-root /absolute/isolated-data --prompts-root /absolute/isolated-project --models-root /absolute/isolated-models --mlflow-root /absolute/original-mlflow-path
```

SQLite中的artifact URI保留原绝对路径；完整MLflow artifact查询恢复需在原路径布局下演练，任意改目录后的文件复制不构成完整可用性证明。本机可以验签训练机快照，联合恢复在训练机受控隔离对象的原路径布局下验证；不删除或覆盖真实唯一源以模拟故障。真实移动硬盘与真实大型模型恢复是否通过，单独以实际证据验收。

<!-- DECISION-LOG
D001 — Contract中的legacy整体现状保护改为按已确认入口退役，保留历史对象与业务实现。
Why: 已批准的迁移Spec要求单一正式写入者；旧“公共入口维持原样”条款与实际逐入口切换冲突，不能用于恢复旧选择或发布绕过。
-->
