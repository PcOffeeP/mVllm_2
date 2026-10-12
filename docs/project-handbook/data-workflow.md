# 从原始视频到可用数据

本项目把材料拉伸视频整理为经过裁剪、采样和标签审查的子视频。train 数据用于三折训练、验证和独立全量训练；test 数据用于最终独立测试，构建与使用都有单独的隔离及授权要求。正式处理入口是 `python -m versioning data`。

本文是新文档包的候选数据指南。当前项目证据和未完成事项见[项目现状](project-status.md)，模型训练及测试使用见[模型流程](model-workflow.md)。命令说明不代表真实数据构建、test 使用或模型运行已经获准。

## 执行前认识两个目录

代码 checkout 保存实现、契约和配置；独立的 versioning **store** 保存工作产物、发布及登记对象。所有命令都明确提供 store，不从旧 `LATEST`、集合索引或短哈希推断版本。

| 位置 | 用途 |
| --- | --- |
| `INPUTS.project_root` | 原视频、注释、人工 ROI 决定、split、参考文件和处理器配置的实际输入根 |
| `STORE/data/working/BATCH/` | train 批次的七阶段目录，每阶段包含 `stage_manifest.json` |
| `STORE/data/releases/VERSION/` | 完整身份发布；`release.yaml` 是状态与血缘元数据，不能仅凭目录存在判断可用 |
| `STORE/data/test_working/BATCH/` | test 的受限批次根，内部有自己的 `data/working/BATCH/` |

身份格式是 `data-v<协议>-r<N>`，例如 `data-v4.1-r3`。摘要用于校验文件完整性，不是身份。批次名字和完整版本由操作者明确选择，不能静默改号重试。

Mac 适合输入准备、ROI 人工决定、完整审查包 UI 和轻量文件检查。真实 ROI 物化、子视频生成、大量校验及正式数据发布在训练机执行；模型训练、GPU 推理及完整评测也只在训练机执行。Mac 通过 uv 调用已部署的 Python 3.11.x 解释器；训练机直接使用已按 Linux GPU 锁核验的 Conda Python 3.11.x。解释器须对应实际 checkout 与依赖，不按旧环境名猜测。机器与环境准备见[快速开始](README.md#快速开始)。

## 1. 准备真实输入

七阶段的第一步是冻结输入，不能代替人工选择数据、决定 split 或提供 ROI。先准备下面的文件，再把它们的真实路径、大小和摘要填入 inputs。

### 原视频与注释

视频名字为 `video_0001.mp4` 形式，`video_id` 必须与文件 stem 一致。两份 CSV 都必须无重复且恰好覆盖本批视频；标签来自核对过的标注，视频属性由后续真实 probe 验证，不能填占位值。

| 文件 | 必需列 |
| --- | --- |
| `all_videos_tag.csv` | `id`、`video_path`、`断裂时间点`、`断裂模式`、`材料类型`、`清晰度`、`断裂位置`、`断裂帧数`、`视频时长`、`视频帧率`、`视频总帧数`、`has_fracture`、`is_abnormal` |
| `video_mapping.csv` | `标准化文件名`、`原始文件名`、`来源目录`、`材料类别`、`状态`、`duration`、`resolution`、`codec` |

tags 的 `video_path` 文件名与 ID 对应。mapping 的原始文件名及来源目录非空，状态是 `existing` 或 `new`。列语义及治理逻辑见[输入实现](../../pipeline/source_bootstrap.py)和[现行校验](../../versioning/data_pipeline.py)的 `run_input_source`。历史 110 个原视频或特定 train/test 数量不构成新批次固定要求。

### split 与 ROI 决定

split 使用已确认的原视频成员划分，包含 `test` 和三个 fold 的 `train`/`val` 七份列表，并绑定全部源视频 SHA256。每折 train、val、test 不相交且覆盖本批 source。现行入口保存、校验既定划分，不重新随机划分；历史冻结 split 可逐项转录，改变成员或测试使用资格需另行决定。

ROI UI 的输入 `ROI_METADATA` 是数组或含 `videos` 数组的 JSON，逐项有唯一 `video_id`、定位真实视频的 `video_path` 及真实视频属性/事件信息。跨机使用时，`video_path` 必须是两机共有的项目内相对路径，与 inputs 中对应视频 pin 的 `path` 一致：Mac 的 `MEDIA_PROJECT_ROOT` 和训练机的 `INPUTS.project_root` 各自解析到该相对位置的同一份视频内容。两机项目根可以不同，视频相对布局及 SHA256 必须一致。

metadata 可以来自核对过的历史 source snapshot 的 `video_meta.json`，也可以由操作者按本批真实视频准备。如果历史 metadata 保存了机器专属绝对路径，先准备并核对具有上述相对布局的便携 metadata，再进行人工 ROI 决定；不能直接沿用 Mac 绝对路径，也不能事后手改已冻结决定绕过校验。UI 会把 metadata 路径原样写入决定的 `source_video_path`，训练机 ROI 阶段会解析并要求它与对应输入 pin 的实际文件相同。同结构与读取逻辑见[ROI UI](../../pipeline/scripts/roi_annotation_app.py)及[ROI 物化校验](../../versioning/data_pipeline.py)的 `run_input_roi`。新 source 阶段输出 `source_manifest.json`，不会自动生成供 UI 选择的旧 snapshot 身份。

Mac 上从代码仓库运行，`MAC_PYTHON` 是[快速开始](README.md#快速开始)中已部署的 Mac 环境解释器绝对路径，`MEDIA_PROJECT_ROOT` 解析 metadata 中的媒体路径，`ROI_OUTPUT` 是可编辑决定文件，不能覆盖 metadata 或已有封存文件：

```sh
uv --no-config run --no-project --no-python-downloads --python "$MAC_PYTHON" \
  python -m streamlit run pipeline/scripts/roi_annotation_app.py -- \
  --metadata "$ROI_METADATA" --output "$ROI_OUTPUT" --project-root "$MEDIA_PROJECT_ROOT"
```

逐视频选择 `fixed_roi`（精确 3:4 裁剪）或 `no_crop`（完整画面后 padding 到 3:4），检查可见性和关键时刻预览。完成的 `roi_decisions.json` 必须覆盖本批全部视频、全部 approved，并绑定源路径、摘要、分辨率、几何和策略版本。将决定文件复制到 inputs 声明的真实项目根，再记录 pin。训练机还会复验来源、尺寸与时间轴，UI 保存成功不等于物化通过。

### inputs、参考与处理器

inputs 是 `schema: tensile-data/inputs/v1` 的 YAML。每个文件 pin 精确包含 `path`、`size_bytes`、`sha256`：路径为 `project_root` 内规范相对路径，大小是非负整数，摘要为真实完整 64 位 SHA256。文件及路径不能经过符号链接；重复键、alias/merge、额外或缺失字段均拒绝。

| inputs 字段 | 来源 |
| --- | --- |
| `schema`、`batch`、`project_root` | 固定 schema、本批名字、存在的真实绝对目录 |
| `source.videos` | 非空视频 pin 列表，每项另有 `video_id` |
| `source.annotations.tags` / `mapping` | 两份已核对 CSV 的 pin |
| `split` | 上述既定 split 文件 pin |
| `roi_decisions` | 完整人工 ROI 决定 pin |
| `media.config` | 候选契约及 development/test 两域参考的配置 pin |
| `media.preprocessor.kind` / `config` | `minicpm` 与真实处理器描述 pin |
| `contract` | [当前四字段业务契约](../../pipeline/contracts/tensile_vlm_v4_1.json)的 pin |

`split` 文件使用 `tensile-data/split-inputs/v1`，含 batch、完整 `source_sha256` 和七份 `splits`。`media.config` 使用 `tensile-data/media-inputs/v1`，钉扎 [v3 候选契约](../../pipeline/contracts/tensile_vlm_v3.json)、`development_reference`、`test_reference`。候选算法仍复用 v3 模块，发布契约仍为 v4.1。两域参考有同一 `reference_id`，其 source inventory 与对应域成员一致，记录绑定对应源视频；没有历史参考也必须显式提供合法空记录文件，不能缺文件后回退。

处理器描述使用 `tensile-data/preprocessor-inputs/v1`，包含项目内普通相对目录 `model_root`、加载所需文件的完整 pins、`max_frames: 8`、正有限 `video_fps`、实际 `expected_fingerprint`。至少包含 `config.json`、`preprocessor_config.json`，tokenizer、动态处理代码及相对依赖也须钉扎，外部 `auto_map` 拒绝。指纹来自同一目录及参数下的 `MiniCPMVideoPreprocessor.fingerprint()`，不能填示例摘要。此步骤准备处理器，不加载模型权重或推理。

完整嵌套字段见[接口索引：显式数据七阶段](../../versioning/SCRIPTS.md#显式数据七阶段)，实际解析器是 `load_data_inputs`、`_load_media_inputs`。inputs 不会生成缺失的决定、参考或指纹。真实运行需训练机具备 ffmpeg、PyAV 和 MiniCPM 处理器依赖。

## 2. 冻结、裁剪和生成待审包

从训练机代码仓库执行。先设置 `PYTHON`（已按 Linux GPU 锁核验、匹配 checkout 的 Conda Python 3.11.x 绝对路径）、`STORE`（独立 store 根）、`INPUTS`（完整 YAML 绝对路径）、`BATCH`（与 YAML 一致）、`VERSION`（确认过且未占用的完整 data 身份）。`RETURN` 暂留为人工回收后的明确路径。

| 阶段 | 输入 → 主要产物及检查 |
| --- | --- |
| `source` | 视频、CSV、split、契约 → 冻结媒体/注释/split、`source_manifest.json`；检查 pins、属性和成员 |
| `roi` | source 与人工决定 → 裁剪媒体、冻结决定、`roi_manifest.json`；检查几何与时间轴 |
| `subvideo` | ROI、候选契约、参考、处理器 → 子视频、采样帧、映射、排除理由、`subvideo_manifest.json`；实际采样门通过才保留 |
| `review_export` | 子视频、参考、冻结契约 → 可搬移的完整审查包，包含媒体、队列与阶段 manifest |

```sh
"$PYTHON" -m versioning data source --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data roi --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data subvideo --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data review_export --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
```

产物位于 `STORE/data/working/BATCH/<阶段>/`。既有阶段只在输入、上游和完整文件匹配时复用，漂移即停止。候选数量由实际事件窗口与算法产生，不能按每个视频固定条数估计。train 待审候选与 test 审计材料隔离，后者不进入 train 发布。

## 3. 人工审查、回收与发布

把训练机整个 `review_export/` 复制到 Mac 的普通目录 `PACKAGE`，保留媒体、队列、契约及 `stage_manifest.json`。不能只复制队列 JSON。Mac 设置已部署环境的 `MAC_PYTHON`，并设置包外 `DRAFT` 和 `REVIEW_OUTPUT`，运行：

```sh
uv --no-config run --no-project --no-python-downloads --python "$MAC_PYTHON" \
  python -m streamlit run pipeline/scripts/review_candidates_app.py -- \
  --versioning-package "$PACKAGE" --draft "$DRAFT" --output-root "$REVIEW_OUTPUT"
```

完整包模式默认审查者为“项目维护者”，可用 `--reviewer-id` 指定其他非空身份。打开、保存、冻结均复验整包；所有待审候选必须进入终态，才生成 `REVIEW_OUTPUT/review_return.json`。草稿不能指向这个冻结文件。历史审批复用须核对媒体、帧、时间戳和标签并保留依据，fixture 不能当人工审批。旧 `--queue` 写入和局部候选筛选不能替代此交接。

把冻结 JSON 完整复制回训练机，设置其路径为 `RETURN`，继续完成三步：

```sh
"$PYTHON" -m versioning data review_import --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --results "$RETURN"
"$PYTHON" -m versioning data release --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
"$PYTHON" -m versioning data release_validate --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
```

`review_import` 核对完整决定、审查者、时间、标签和证据绑定；`release` 形成工作区构建证据并封存正式发布；`release_validate` 只读验证上游绑定、payload、权限及训练准入，输出 JSON，不启动模型训练。

train 发布的 `payload/` 包含子视频及帧、契约、split、审查回收、`metadata/training_candidates.json`、六份 fold 数据集、`dataset_info.json` 和 `reports/quality_report.json`。同级 `release.yaml`、`README.md` 管元数据；DVC store 另有 `payload.dvc`。下游训练使用完整 VERSION 和原 `--data-inputs`，新七阶段发布的媒体根是该版本 payload，详见[模型流程](model-workflow.md)。

完整版本已存在即冲突，中断 staging 保留供显式核查，不自动删除、覆盖或改号。修改数据应生成新身份，不能原地修封存 payload。

## 4. 使用 DVC 管理 train 流程

DVC 负责依赖和内容追踪，完整 data 身份仍由 versioning 管理。仓库根模板没有默认批次或版本。在 STORE 初始化 DVC：有 Git store 用 `dvc init`，已明确不使用 SCM 的独立 store 用 `dvc init --no-scm`。然后从代码仓库生成实际配置：

```sh
"$PYTHON" -m versioning data dvc-config --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --results "$RETURN" --version "$VERSION"
```

此动作生成 store 内的 `dvc.yaml`/`params.yaml`，不是第八阶段。配置追踪所有显式及嵌套输入、处理器文件和实际实现代码；RETURN 可以尚不存在，但不能在阶段输出内。不同内容的旧配置不会自动覆盖；跨机器须重新生成以绑定实际代码和解释器位置。

在 STORE 中用 `dvc status` 查看过期，用 `dvc repro review_export` 手动推进到待审包，人工回收完成后用 `dvc repro release_validate` 继续。工作输出使用 persist，漂移不会静默删旧结果重建。正式 payload 单独跟踪；恢复后重新验证权限与绑定。不要对全部封存的 `payload.dvc` 执行强制 commit，pipeline 补登记只针对 `dvc commit --force dvc.yaml`。remote 的权限和复制目标须明确配置，不能把受限 test 数据沿用 train 的发布方式。

## 5. test 数据：隔离构建与完整审查

新 test 不是把已有验证或测试数据改名。先确认来源及使用资格，再获实际数据构建授权。完整构建接口已实现，但文档不证明真实未使用 test 已准备好。

准备独立的全 test 批次 inputs：`test` 覆盖全部 source，六份 fold 列表显式为空；两域参考的 `records` 都为空，development source inventory 为空、test inventory 覆盖全部 source。其余视频、ROI、契约、处理器及 pins 沿用前文要求。

另准备 JSON/YAML `TEST_CONFIG`，schema 为 `tensile-data/holdout-build/v1`，绑定 batch、inputs 文件摘要、完整 `development_data_version` 及该 train `release.yaml` 摘要。`development_sources` 和 `used_test_sources` 是两份非语义来源清单的 pins，路径相对 INPUTS.project_root。

每份清单使用 `tensile-data/source-isolation/v1`，包含对应字段名作为 `scope`、非空视频 ID → 原视频 SHA256 的 `sources`、`reviewer_id`、含时区的 `reviewed_at` 和说明依据的 `reference`。train 清单须精确覆盖绑定发布的 `payload/metadata/training_candidates.json` source；缺少该证据的历史发布不自动兼容。由操作者核查两份清单完整且新 test 未用于调参；程序检查 ID/内容无重叠和新 source 无重复，不能替代人工资格确认。不得读取旧 test 真值来填写清单。精确字段见[接口索引](../../versioning/SCRIPTS.md#test-数据分支处理全量人工审查与封存)和[隔离实现](../../versioning/holdout_pipeline.py)。

将 TEST_CONFIG 设为绝对路径，调用七阶段时每次都加 `--purpose holdout --test-config "$TEST_CONFIG"`，例如：

```sh
"$PYTHON" -m versioning data source --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data roi --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data subvideo --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
"$PYTHON" -m versioning data review_export --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH"
```

完整待审包位于 `STORE/data/test_working/BATCH/data/working/BATCH/review_export/`。受限工作区、Mac 副本及审查输出目录必须 owner-only，已有宽权限目录被拒绝而不自动修改。全部候选都人工审查，包括普通未断裂；没有历史标签建议或自动准入。用前文完整包 UI 交接，草稿及回收文件不能进 Git 或公开位置，RETURN 文件仅 owner 可读写。

```sh
"$PYTHON" -m versioning data review_import --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --results "$RETURN"
"$PYTHON" -m versioning data release --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
"$PYTHON" -m versioning data release_validate --purpose holdout --test-config "$TEST_CONFIG" --root "$STORE" --inputs "$INPUTS" --batch "$BATCH" --version "$VERSION"
```

test 发布包含 `media/`、无标签 `evaluation_inputs/manifest.json`、owner-only `sealed_ground_truth/`、只公开通过状态的 `payload/quality_report.json` 和 `build_receipt.json`。它保持 `purpose: holdout`、`training_allowed: false`、`split: holdout`，不生成训练 datasets；train 在线入口拒绝使用。受限构建凭证及真值不上传 Git/MLflow，完整备份保留权限；现有 dvc-config 只支持 train。

test 的 release_validate 会读取本次新 test 真值核对构建内容，实际执行仍需数据授权；它不执行模型测试，也不创建 claim。相同绑定可按既有恢复规则重试，冲突拒绝，不能清除已消费授权。权限布局不等于独立操作系统沙箱。

封存完成后交接完整 data 身份、公开 `media/` 路径、构建凭证和 train 数据绑定。最终 full 模型登记、独立测试资格、预注册与执行授权就绪后，才进入[模型流程](model-workflow.md)的 `data claim` → `eval prepare/run/score/export`。prepare/run 不读真值，score 才在同一执行身份下授权读取；通过和失败都会消费一次性 claim，不能用于调参后重测。

## 已有数据与清理边界

以下是仓库迁移记录保存的 train 数据背景，不是本轮训练机刷新结果：

| 完整身份 | 迁移时状态 | 内容 |
| --- | --- | --- |
| `data-v4.1-r1` | superseded | 原 `v4.1.0-760050fad303` 基础发布，用于恢复历史引用，不能建立新训练引用 |
| `data-v4.1-r2` | active | 原 `v4.1.0-ecb5aeb9657c` Phase2 train 发布 |

发布数量和各折统计集中在[项目现状](project-status.md)，来源是[原始发布报告](../results/v4_1_phase2_development_release/README.md)；身份与状态来自[对象映射](../results/version-control-migration/object-mapping.yaml)及[迁移验证](../results/version-control-migration/verification.md)。新训练引用仍须在线校验状态及许可。

迁移保留原内容和 split，不能重新生成数据冒充同一发布。两个迁移对象仍引用旧 workspace 外部媒体，store 尚不自包含。旧 workspace、历史元数据及共享 pipeline 函数可能仍被发布或实验引用；入口退役不表示目录和函数可以删除。清理前必须扫描引用、归档必要证据并验证备份，执行范围由项目现有台账和用户授权决定。

## 失败时如何处理

| 失败 | 处理 |
| --- | --- |
| pin、指纹、上游或阶段文件漂移 | 停止，核对真实来源与环境；需要更改输入时确认新批次及新完整身份 |
| split、ROI、参考或 metadata 缺失 | 回到输入准备，不猜测决定、不自动划分、不恢复旧默认入口 |
| 审查包缺媒体、候选未完成 | 恢复完整包，完成全部终态后冻结；不绕过验签 |
| 完整版本冲突或遗留 staging | 保留现物及进程证据，按显式恢复规则处理，不覆盖和清空 |
| test 来源、隔离或授权不足 | 保持阻塞，补来源核查及资格确认，不能读取真值补资格 |
| 恢复后 payload、权限或绑定校验失败 | 停止下游引用，核对数据与原输入，不改写封存对象制造通过 |

实现接口以 [versioning 索引](../../versioning/SCRIPTS.md)、[数据实现](../../versioning/data_pipeline.py)和[发布实现](../../versioning/data_release.py)为准；迁移决定及验证仍保留原始证据，不在候选指南中创建第二份任务台账。
