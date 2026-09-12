<!-- DOCUMENT-CONTRACT
Purpose: 定位 versioning 的实际入口，并提供显式数据输入与人工交接的操作边界。
Scope: CLI 模块索引、七阶段数据命令、输入契约、DVC 配置和审查包回收。
Must Preserve:
- 五类完整可读身份、显式输入与 fail-closed，不引入当前版本回退。
- 区分数据业务处理、人工决定和正式封存；不能把测试替身当真实媒体验收。
- legacy 公共入口维持原样，显式新模式不读旧活动指针或创建旧集合身份。
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
| `train` | `mlflow_train.py` | 训练父 Run、三折子 Run、汇总与完成门 |
| `eval` | `mlflow_eval.py`、`manifest.py` | 测评父子 Run、Registry 精确引用、holdout 消费、结论门与 eval manifest 单向导出 |
| `model` | `registry.py`、`manifest.py`、`materialize.py` | `mVllm2` 两阶段 register/finalize、model manifest、唯一部署目标 gate、alias 与 `models/current` 原子物化 |
| `backup` | `backup.py` | 离线备份 catalog、完整性验证与显式目标恢复 |
| `migration` | `migration.py` | 从显式 object mapping 执行 Prompt/Data 只读预检或迁移，从声明 entry 纯构建或固定路径发布 history-summary |

`cli.py` 只编排上述领域模块，不实现第二套状态或身份规则；`__main__.py` 仅转发统一入口。
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
"$PYTHON" -m streamlit run pipeline/scripts/review_candidates_app.py --   --versioning-package "$PACKAGE" --reviewer-id "$REVIEWER"   --draft "$DRAFT" --output-root "$REVIEW_OUTPUT"
```

`REVIEWER` 为实际审查者，旧队列与新审查包两种模式均要求非空标识，界面显示本次审查者。
汇总前逐条检查作者；缺失的历史决定必须重新核对保存，不自动归给当前操作人。
`DRAFT` 与 `REVIEW_OUTPUT` 都必须位于包外；草稿不能指向
`REVIEW_OUTPUT/review_return.json`。打开包、保存草稿、完成冻结均会复验包；所有候选完成
后生成该回收文件，保留真实审查者、时间、备注、标签和采样证据。不要把 fixture 决定
当成人工结果。`--queue` 继续走 legacy UI，两种输入模式互斥；新模式不接受局部候选筛选。

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
