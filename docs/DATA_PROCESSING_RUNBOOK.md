<!-- DOCUMENT-CONTRACT
Purpose: 为项目当前受支持的数据处理链路提供可持续维护、可执行且可验证的端到端运行指南。
Audience: 需要首次跑通、复现或维护项目数据处理链路的开发者和操作人员。
Scope: 显式输入准备、versioning store 七阶段、人工审查交接、train/test 数据封存、DVC 及 holdout 数据授权交接与跨机边界。
Must Preserve:
- 手册的标题和长期定位不绑定某一链路版本；当前支持版本与主要适用契约集中声明，版本特有差异在相关步骤中明确标注。
- 每个流程环节都给出可追溯的入口、主要输入与产物、执行机器、验收检查和进入下一步的条件。
- 冻结产物与 release 不可覆盖；上游产物选择和身份必须可追溯，以显式 store、完整身份与文件绑定维护新旧入口的路径边界。
- 区分本机轻量操作与训练机重计算或 GPU 操作，不暗示本机能够复现训练机任务。
Non-goals:
- 记录某次运行状态、历史发布基线或实验结果。
- 展开模型训练、评分算法或部署流程；holdout 章节仅说明数据授权与执行接口交接，细则引用训练手册及 versioning 索引。
-->

# 数据处理运行手册

正式数据处理统一使用 `python -m versioning data`。本文提供当前链路的输入准备、七阶段、人工交接、发布和封存操作；训练与模型评分规范分别见[训练手册](../finetune/README.md)和[完整 holdout 验收接口](../versioning/SCRIPTS.md#full-模型的独立-holdout-验收)。命令示例是操作接口，不授予真实数据构建、测试使用、训练或评测授权。

## 适用范围与执行边界

当前审查及发布业务契约为 `pipeline/contracts/tensile_vlm_v4_1.json`，候选算法复用 `pipeline/contracts/tensile_vlm_v3.json` 与 `pipeline/v3_candidate_plan.py`、`pipeline/v3_candidate_media.py`；模块名称中的 v3 不代表发布契约回退。新体系正式身份仅接受完整 `data-v4.1-r<N>`，必须显式指定 store、批次和输入，不解析旧集合 index、LATEST 或短哈希。

Mac 负责 ROI 输入准备、完整包人工审查及轻量文件检查；训练机负责 ROI 裁剪、子视频/采样帧生成、大量文件校验与正式发布。模型训练、GPU 推理和完整评测只在训练机执行。环境解释器必须与实际 checkout 和依赖匹配；不根据历史环境名猜测当前解释器。训练机连接见[双机工作流](project-guide.md#双机工作流)。

旧重建、ROI 冻结/物化、候选规划/物化、队列及发布 CLI 已退役，精确清单见[pipeline 脚本索引](../pipeline/scripts/SCRIPTS.md)。保留的历史业务函数和媒体引用仍可能被使用；不得删除旧 workspace 或把历史发布重新生成来替代已确认的复制迁移。历史映射与验证见[object mapping](results/version-control-migration/object-mapping.yaml)、[迁移验证记录](results/version-control-migration/verification.md)及[交接记录](results/version-control-migration/handoff.md)。执行次序和现状只在[项目台账](project-todo.md)维护。

## 输入准备

### 源视频与两份注释

源视频使用 `video_0001.mp4` 格式，inputs 中的 `video_id` 与文件 stem 一致。`all_videos_tag.csv` 与 `video_mapping.csv` 都必须无重复且恰好覆盖本批源视频。列定义来自 `pipeline/source_bootstrap.py`，由 `versioning/data_pipeline.py::run_input_source` 校验：

| 文件 | 必需列及来源要求 |
| --- | --- |
| tags CSV | `id`、`video_path`、`断裂时间点`、`断裂模式`、`材料类型`、`清晰度`、`断裂位置`、`断裂帧数`、`视频时长`、`视频帧率`、`视频总帧数`、`has_fracture`、`is_abnormal`；`video_path` 文件名必须与 ID 匹配 |
| mapping CSV | `标准化文件名`、`原始文件名`、`来源目录`、`材料类别`、`状态`、`duration`、`resolution`、`codec`；原文件名及来源目录非空，状态为 `existing` 或 `new` |

标签来自已核对的原始标注；视频属性在 source 阶段由真实 probe 校验和治理，不能用占位帧率/时长代替。新入口不硬编码 110 个视频或 89/21 数量；历史数据数量不是每个新批次的固定要求。

### 既定 split 与 ROI 人工输入

split 由操作者提供已确认的成员划分，包含 test 和三个 fold 的 train/val 七份列表及全部原视频 SHA256。可从已核对的历史冻结 split 文件逐项转录既定成员到下述新输入 schema；新入口只校验并保存，不重新随机划分。新划分或测试集资格判断是独立决策。

ROI 输入准备先于七阶段，因为 inputs 必须绑定已完成的决定。`ROI_METADATA` 是明确的 JSON 文件：来源为核对过的历史 source snapshot 的 `video_meta.json`，或操作者根据本批视频准备的同结构清单（数组或含 `videos` 数组的对象）。每项包含唯一 `video_id`、可解析的 `video_path` 和真实视频属性/事件信息；媒体根与路径共同定位实际视频。新 source 阶段产出 `source_manifest.json`，不产出供 UI 自动选择的历史 snapshot 身份。缺少 metadata 时先完成清单准备，不能恢复已停用的重建 CLI。

```sh
"$PYTHON" -m streamlit run pipeline/scripts/roi_annotation_app.py -- \
  --metadata "$ROI_METADATA" --output "$ROI_OUTPUT" --project-root "$MEDIA_PROJECT_ROOT"
```

`PYTHON` 为本机实际项目解释器；`MEDIA_PROJECT_ROOT` 用来解析清单中的媒体路径；`ROI_OUTPUT` 为包外可编辑草稿，不得覆盖 metadata 或已有封存文件。在 UI 中逐视频确认 `fixed_roi`（精确 3:4 裁剪）或 `no_crop`（完整画面后 padding 到 3:4），完成可见性检查及关键时刻预览。输出 `roi_decisions.json` 完整覆盖本批且全部 approved；绑定来源路径、SHA、分辨率、几何和策略版本。训练机 ROI 阶段复验真实尺寸与时间轴，不凭界面保存成功放行。

人工完成后将 ROI 文件复制到 inputs 所声明的真实项目根内，核对与源视频的绑定，再记录 pin。媒体项目根必须定位真实媒体，不能用迁移来源镜像替代训练媒体根。

### 冻结 inputs YAML

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


完整字段与解析器见[versioning 输入契约](../versioning/SCRIPTS.md#显式数据七阶段)及 `versioning/data_pipeline.py::load_data_inputs`。inputs 不会替操作者生成 split、历史参考、ROI 或处理器指纹；没有来源的参数不能进入执行。历史参考是明确的已核对文件；空参考也须显式提供合法结构。

## 数据七阶段

从代码仓库执行。训练机上由操作者明确设置：`PYTHON` 为匹配 checkout 的项目解释器绝对路径，`STORE` 为独立 versioning store 根，`INPUTS` 为上述完整 YAML 绝对路径，`BATCH` 与 YAML 一致，`VERSION` 为已确认且未占用的完整 data 身份。`RETURN` 是人工交接后回到训练机的回收 JSON 路径。

| 阶段 | 入口 | 明确输入 | STORE 内输出与准入检查 |
| --- | --- | --- | --- |
| 原始输入冻结 | `data source` | 视频、两份注释、给定 split、业务契约 | `data/working/BATCH/source/` 的 `media/`、注释、split 文件、`source_manifest.json`；校验 pin、视频属性和成员 |
| ROI 物化 | `data roi` | source、人工决定 | `data/working/BATCH/roi/` 裁剪媒体、`roi_manifest.json`、冻结决定；校验来源、尺寸、几何和时间轴 |
| 子视频与采样帧 | `data subvideo` | ROI、候选契约、两域参考、处理器配置 | `data/working/BATCH/subvideo/` 候选计划、真实 MP4、采样帧、映射及排除证据；校验实际采样门 |
| 审查导出 | `data review_export` | 候选媒体、参考、冻结契约 | `data/working/BATCH/review_export/` 完整可搬移包；所有声明媒体及证据匹配 |
| 审查回收 | `data review_import` | 同一 inputs、人工 RETURN | `data/working/BATCH/review_import/`；决定完整覆盖且审查人、时间、标签、证据绑定合法 |
| 数据发布 | `data release` | 审查回收、完整 VERSION | `data/working/BATCH/release/` 构建证据，`data/releases/VERSION/payload/`；拒绝版本冲突 |
| 发布验证 | `data release_validate` | 同一 inputs/batch/version | JSON 报告；核验 payload、上游、封存权限与训练准入，不启动训练 |

各阶段包含 `stage_manifest.json`，输入、上游、完整文件都一致时才复用；漂移即停止，不自动删除、覆盖或改号。候选数量由实际视频/事件窗口和现有算法决定，不固定为每视频若干条；采样门核对时间戳及事件前后帧，失败候选记录排除原因。开发域待审候选与 test 审计材料隔离，后者不能进入训练发布。

```sh
"$PYTHON" -m versioning data source --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data roi --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data subvideo --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data review_export --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
```

## 人工审查交接与发布

将训练机整个 `STORE/data/working/BATCH/review_export/` 复制到 Mac 的普通目录 `PACKAGE`，保留媒体、队列、契约和 stage manifest，不能只带队列 JSON。Mac 明确设置自身 `PYTHON` 和包外 `DRAFT`、`REVIEW_OUTPUT`：

```sh
"$PYTHON" -m streamlit run pipeline/scripts/review_candidates_app.py -- \
  --versioning-package "$PACKAGE" --draft "$DRAFT" --output-root "$REVIEW_OUTPUT"
```

草稿不能指向 `REVIEW_OUTPUT/review_return.json`。完整包模式默认审查者为“项目维护者”，可用 `--reviewer-id` 指定其他非空身份。UI 打开、保存和冻结均复验整包，所有候选形成终态才冻结回收文件，不接受旧 `--queue` 模式或局部候选筛选。历史审批复用须核对媒体、帧、时间戳和标签并保留确认依据；fixture 不构成人工审批。

冻结得到 `REVIEW_OUTPUT/review_return.json` 后，完整复制该文件到训练机的 `RETURN` 路径，再执行：

```sh
"$PYTHON" -m versioning data review_import --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --results "$RETURN"
"$PYTHON" -m versioning data release --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
"$PYTHON" -m versioning data release_validate --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
```

正式 payload 包含媒体、冻结契约/审查、六份 fold 数据集、dataset_info 与质量计数；`release.yaml`、`README.md` 位于同级元数据边界，DVC store 中另有 `payload.dvc`。发布不可覆盖，中断 staging 保留供显式核查，不自动清理。训练准备显式绑定 VERSION；七阶段数据须同时提供原 `--data-inputs`，媒体根使用该版本 payload。已复制迁移的历史数据则按 committed receipt 复验，外部媒体根仍为原实际位置，不能假定自包含。

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


## test 数据分支：独立构建与全量审查

叙述统一使用 **train 数据分支**（三折训练/验证及全量训练）与 **test 数据分支**（最终独立测试）。现有字段及值 `development`、`holdout`、`test_audit`、`validation` 和历史身份保持不变。以下命令是执行接口，不赋予真实数据构建、测试使用或训练授权。

`holdout_pipeline.py` 复用 source/ROI/子视频算法，使用独立 `STORE/data/test_working/BATCH/`，顶层及批次目录必须 owner-only；存在的宽权限目录拒绝，不自动修改。实际七阶段位于其内部 `data/working/BATCH/`。每批绑定输入与隔离配置摘要，漂移后不能继续复用。test 输入必须是独立全 test source 批次：split 的 `test` 覆盖全部声明视频，六份 fold train/val 列表显式为空；两类历史参考的 `records` 均为空，source_inventory 分别为空和全部 test source。沿用输入视频、ROI、处理器、业务契约及pin格式。

另提供 `TEST_CONFIG`，JSON或YAML，字段精确为：

| 字段 | 必须提供的内容 |
| --- | --- |
| `schema` | `tensile-data/holdout-build/v1` |
| `batch`、`inputs_sha256` | 与 `INPUTS` 批次及原文件SHA256一致 |
| `development_data_version`、`development_release_sha256` | 完整 train data 身份及其 release.yaml 摘要 |
| `development_sources`、`used_test_sources` | 两份非语义来源审查清单pin，路径相对INPUTS.project_root，含path/size_bytes/sha256 |

每份来源清单精确包含 `schema: tensile-data/source-isolation/v1`、`scope`（与对应配置字段同名）、`sources`（非空video_ID到原视频SHA256映射）、`reviewer_id`、含时区的`reviewed_at`、非空`reference`（审查来源说明）。train清单ID必须精确覆盖已发布`payload/metadata/training_candidates.json`的source，缺失该证据即拒绝，不推断历史对象兼容。两个清单由操作者提供已核查的完整证据；程序校验其pin、身份覆盖及新test source与两者的ID/内容摘要无交集，并拒绝新source内部重复内容，不能替代人工确认清单完整和从未用于调参。不得读取旧测试真值来填写清单。

在既有变量之外，`TEST_CONFIG`为上述配置的绝对路径：

```bash
"$PYTHON" -m versioning data source --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data roi --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data subvideo --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data review_export --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
```

导出包为`STORE/data/test_working/BATCH/data/working/BATCH/review_export/`，必须连同媒体和stage_manifest完整保留。test全部候选进入人工审查，包括普通未断裂；无历史标签建议，不自动准入。沿用本文人工审查交接的 `review_candidates_app.py --versioning-package` 工作流；复制后的包目录及`REVIEW_OUTPUT`均须owner-only，草稿/回收文件不得进入Git或公开位置。所有决定带审查人/时间，并精确绑定每个候选及媒体。冻结得到包外`review_return.json`后，将其作为`RETURN`，文件权限仅owner可读写：

```bash
"$PYTHON" -m versioning data review_import --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --results "$RETURN"
"$PYTHON" -m versioning data release --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
"$PYTHON" -m versioning data release_validate --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
```

发布`data/releases/VERSION/`内的`media/`、无标签`evaluation_inputs/manifest.json`、owner-only `sealed_ground_truth/`（labels、审查原件、隔离清单和阶段证据）、仅通过状态的`payload/quality_report.json`以及`build_receipt.json`。发布保持`purpose: holdout`、`training_allowed: false`、`split: holdout`，不创建训练datasets。CLI只输出阶段状态和路径；受限构建凭证不上传Git或MLflow，完整数据备份须保留权限。既有`data dvc-config`仅支持train路径，test分支不自动向DVC remote发布受限数据。

相同完整绑定与审查可重试；冲突拒绝，已消费authorization保留。staging恢复须核对完整inventory，rename后的根目录封存尾步只在其余文件均已封存时恢复。`release_validate`是数据管理校验，会读取当前新test真值并核对构建内容，因此真实执行仍需适用数据授权；它不执行模型测试或创建claim。

最终full模型身份形成并获测试使用授权后，使用已有`data claim`及`eval prepare/run/score/export`，data版本指定上述VERSION，媒体根指定`STORE/data/releases/VERSION/media`。prepare/run验证构建凭证整体摘要、公开媒体及train版本绑定，不读取真值。授权score首次或未承诺恢复时验证真值字节与构建时pin一致；已承诺恢复不重读真值。公开input仅绑定整份构建凭证摘要，不公开裸真值摘要；既定七门及claim消费规则不变。缺构建凭证的旧对象不自动补证或重新获得测试资格。


## Holdout claim、推理与授权评分交接

封存 test 数据不自动授予测试使用资格。最终 full 模型须来自已完成的独立全量训练并已登记，确认使用资格和实际执行授权后，操作者准备评测配置及预注册。配置、原七项固定质量门、受限输出及恢复规则以[完整 holdout 验收接口](../versioning/SCRIPTS.md#full-模型的独立-holdout-验收)和[训练/评测规范](../finetune/README.md)为准；不能把 validation 六项指标替代 holdout 七门。

预注册 YAML 必含 `eval_version`、`model_version`、`data_version`、`split`、`rules`、`thresholds`、`one_time`、`tuning_use` 和 `recovery` 九个字段（由 `versioning/holdout.py::parse_pre_registration` 核对）；绑定完整 eval/model/data 身份、相同 split、`one_time: true`、`tuning_use: forbidden`、`recovery: {same_identity_only: true}`；rules 精确等于评测配置去掉 thresholds 的内容，thresholds 完全一致。由操作者明确设置 `EVAL`、`MODEL`、Registry 数值 `MODEL_NUMBER`、`EVAL_CONFIG`、`PRE_REGISTRATION`、授权 `EXECUTOR`、实际代码 `COMMIT`；`VERSION` 是前述 holdout 发布，`SPLIT` 与其及预注册一致。

```sh
"$PYTHON" -m versioning data claim --root "$STORE" --version "$VERSION" \
  --eval-version "$EVAL" --model-version "$MODEL" --split "$SPLIT" \
  --executor "$EXECUTOR" --pre-registration "$PRE_REGISTRATION"
"$PYTHON" -m versioning eval prepare "$EVAL" --root "$STORE" \
  --model-version "$MODEL" --model-version-number "$MODEL_NUMBER" \
  --data-version "$VERSION" --config "$EVAL_CONFIG" --git-commit "$COMMIT" \
  --media-root "$STORE/data/releases/$VERSION/media" --executor "$EXECUTOR" \
  --pre-registration "$STORE/evaluations/staging/$EVAL/authorization/pre_registration.yaml"
"$PYTHON" -m versioning eval validate "$EVAL" --root "$STORE"
"$PYTHON" -m versioning eval run "$EVAL" --root "$STORE"
"$PYTHON" -m versioning eval score "$EVAL" --root "$STORE" --executor "$EXECUTOR"
"$PYTHON" -m versioning eval export "$EVAL" --root "$STORE"
```

claim 校验隔离布局与完整绑定，将预注册原子冻结到上示路径，再在 release 的 `authorization/claim.yaml` 写入一次性绑定。prepare/validate/run 不读真值；run 在训练机只执行媒体推理，完整后保持父 Run running，等待显式 score。score 核对同一执行身份、推理与授权证据后才读真值，私有逐样本记录及实际七指标位于 `workspace/evaluations/EVAL/restricted/`。公开 MLflow/manifest 只保留绑定、执行摘要及七门通过状态。无论评分 passed 或 failed，都先持久化 consumed，再提交 completed；export 验签同一 Run，不重复推理或重置消费。

权限和阶段调用不等于独立操作系统沙箱。评分/导出中断遵守原消费和恢复边界，不能手工清空 claim、跨身份续办或用状态写入 CLI 制造通过。所有 train prepare/validate/run 在线拒绝 holdout、training_allowed false 或 invalid 数据。工程接线已存在，真实模型质量和真实独立 test 使用仍以台账证据为准；本手册不声明真实环境验收已完成。

## 故障处理与追溯

| 现象 | 下一动作 |
| --- | --- |
| pin、上游或阶段文件漂移 | 停止；核对真实来源，再确认新批次、输入及完整版本，保留旧证据 |
| 完整版本已存在或遗留 staging | 核对原发布/进程与 inventory，显式处理冲突；不自动覆盖或删除 |
| metadata、ROI 或 split 缺失 | 回到输入准备；不猜测决定、不重分成员、不恢复旧默认选择 |
| ffmpeg、PyAV 或处理器不可用/指纹不符 | 核对训练机项目环境和钉扎文件，不能以本机替身代替真实物化 |
| 审查包不完整或候选未完成 | 保持完整包与媒体，完成全部终态后冻结，不拆包绕过验签 |
| holdout 隔离、使用资格或授权不足 | 保留阻塞并补来源审查/确认，禁止改名旧测试集或读取真值补资格 |
| DVC 恢复后封存/绑定校验失败 | 停止下游使用并核对 payload、权限及原输入，不强制改写封存对象 |

旧链路参数和施工过程从 Git 历史及现有验证记录追溯；旧集合索引只用于必要的历史对象调查，不能成为新版本选择入口。新问题、证据限制与下一步回到[唯一项目台账](project-todo.md)。

<!-- DECISION-LOG
D001 — 将本文维护为不绑定版本号的数据处理主手册，并在正文集中声明当前支持的链路版本。
Why: 数据处理链路后续可能升级；把版本号写入标题会让长期入口与 4.1 偶然耦合，容易产生平行手册或遗留过期入口。
Trade-off: 版本升级时必须同时核对当前版本声明、版本特有路径、命令、默认值和验收条件，不能只修改版本号。
D002 — 现行显式七阶段与历史操作参考分区，保留旧业务解释但停用旧CLI不再作为操作入口。
Why: 迁移已确认逐入口停止旧写入；保留参数历史有助追溯，但不能让旧说明重新授予发布权限。
D003 — 移除旧 CLI 操作正文，现行输入准备、七阶段及 test/评分交接成为唯一操作链。
Why: 迁移交付后历史可执行示例会与单一正式写入入口冲突；D002 的历史追溯改由 Git 与已有验证记录承载。
-->
