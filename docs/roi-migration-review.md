# 视频 ROI 迁移审查与待确认方案

**状态：供用户确认的静态审查稿。** 原项目已有人工选框、决定校验和视频裁剪实现，但不能直接视为适用于本轮五类标签的完整方案。可作为迁移候选的是几何计算、来源绑定和裁剪校验；3:4 比例、全项可见性审核、关键时刻检查及正式数据入口的接入方式仍需确认。本次只形成文档，没有运行 GUI、读取视频画面、生成媒体、迁入脚本或使用 test。

本稿对应[迁移审查大纲](migration-review-outline.md)第 4 节 C「视频检查与 ROI 处理」。ROI 是源视频中保留试样及相关观察证据的画面区域；此处处理完整源视频，不负责选择子视频时间窗口或推导片段标签。

## 1. 来源、输入基准与证据边界

代码来源为原工作区 `/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2` 的 `main`，核对提交为 `2c272ce3548c917bbfa96fe474858f9bf1998893`。下文代码链接均指向该原工作区的实际文件，不指向本工作区尚未显示的同名路径。链接用于本机追溯；跨机器复核应在上述提交定位同一文件和函数，不能把这些绝对路径当作通用部署目录。

本轮输入以[项目导航](guide.md)列出的 `data/v2/annotation-table-full.csv`、`data/v2/videos/` 及[标签说明](label.md)为起点。这些材料尚未因整理完成而冻结、发布或接入训练。既有划分保留，新标注已按 ID 与划分清单对照，素材身份和后续允许处理范围仍待核查，见[数据划分审查](data-split-migration-review.md)；本稿不授权处理 test。当前数据处理和模型评价不使用断裂时间类标注，已有记录保留，见 [facts.yaml](facts.yaml) 的 DF-018、DF-019。

| 编号 | 实际读取的来源与定位 | 支持的内容 |
| --- | --- | --- |
| R1 | [原项目 ROI GUI](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/pipeline/scripts/roi_annotation_app.py:74)，`_parse_args`、`main` | 显式输入、交互、预览和保存 |
| R2 | [原项目决定构造](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/pipeline/scripts/roi_annotation_app.py:447)，`build_decision`；同文件几何函数和 `audit_timestamps` | 记录字段、3:4 几何、审核时间点与可见性要求 |
| R3 | [原项目 ROI 校验与历史冻结库](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/pipeline/roi_manifest.py:120)，`_validate_decision`、`build_roi_manifest_bundle` | 决定合法性、来源摘要、历史冻结格式 |
| R4 | [原项目 ROI 媒体库](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/pipeline/roi_media.py:78)，`filter_for_decision`、`build_ffmpeg_command`、`validate_temporal_contract` | 裁剪、补边、编码和媒体属性校验 |
| R5 | [原项目正式 ROI 阶段](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/versioning/data_pipeline.py:1122)，`run_input_roi` | 正式输入绑定、执行与产物 |
| R6 | [原项目显式输入与阶段发布](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/versioning/data_pipeline.py:761)，`load_data_inputs`、`_load_input_stage`、`_publish_input_stage` | 完整输入 pin、阶段身份、复用及拒绝覆盖 |
| R7 | [原项目命令索引](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/pipeline/scripts/SCRIPTS.md)、[显式数据七阶段](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/versioning/SCRIPTS.md:225) | 活动入口与停用 CLI 的边界 |
| R8 | [原项目历史冻结脚本](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/pipeline/scripts/roi_freeze_decisions.py)、[历史媒体脚本](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/pipeline/scripts/roi_materialize_videos.py) | 两个 CLI 当前均提示停用；普通调用返回退出码 2 的实现 |

上述结论来自源码阅读。没有据此认定历史 ROI 决定仍有效，也没有验证本轮真实视频的方向、可解码性、长视频表现或裁剪后的标签可判读性。

## 2. 先区分三种职责与两条产物路径

现行人工准备入口是 `roi_annotation_app.py`：明确给出 metadata JSON、输出 JSON 和媒体项目根，交互选择固定框或不裁剪，仅保存决定。metadata 接受数组或含 `videos` 数组的对象，每条要求唯一非空 `video_id`，视频由 `video_path` 定位；没有路径时仍保留 `source/videos/<video_id>.mp4` 的旧回退。因此不能把新 CSV 或目录直接交给 GUI 后假定它已对应本轮视频。GUI 不解析 LATEST、快照 ID 或短前缀，文件内保留的 `_legacy_parse_args` 不是 `main` 使用的解析器。（R1）

正式写入入口是 `python -m versioning data roi`，实际调用 `run_input_roi`。它读取已固定的输入 YAML 和已发布的 `source` 阶段，校验人工决定，再裁剪或补边并发布 `roi` 阶段。它复用 `roi_manifest` 的 `_decision_index`、`_validate_decision`，以及 `roi_media` 的过滤器、命令和时间属性检查；**不调用历史 `build_roi_manifest_bundle` 或 `materialize_plan`**。（R3—R7）

历史冻结、媒体库另有一套内容身份：`roi-manifest-…`、`roi-media-…`，涉及集合索引、LATEST 和独立 bundle。两个同名辅助 CLI 的 `main` 已停用，留存的 `_legacy_main` 和业务函数不代表公开命令可继续运行。历史格式供理解来源和依赖，不能与正式阶段产物混写成一条已确认的新链路。（R7、R8）

| 环节 | 输入 | 输出及写入边界 |
| --- | --- | --- |
| 人工 ROI 准备 | 显式 metadata JSON、可解析的源视频路径、已有决定 JSON（若存在） | 可编辑的决定 JSON；原子替换该输出文件，不生成裁剪视频，不修改标签 CSV |
| 正式 ROI 阶段 | `tensile-data/inputs/v1` YAML、其中的 `roi_decisions` 文件 pin、完整 `source` 阶段及其媒体和划分 | `STORE/data/working/BATCH/roi/` 下的 `media/<video_id>.mp4`、`roi_manifest.json`、`roi_decisions.frozen.json`、`stage_manifest.json` |
| 历史冻结库 | 决定 JSON、视频 metadata、含 `video_ids` 的 test manifest | 历史 manifest、冻结决定、`development_roi.json`、`test_roi_audit.json`、校验报告；不是本轮拟定输出 |
| 历史媒体库 | 历史冻结目录、完全匹配的 metadata 和可选视频 ID 子集 | 历史 media bundle、`video_meta.roi.json`、报告、索引；不是正式 `run_input_roi` 的落盘格式 |

正式输入的 pin 是路径、文件大小和完整 SHA-256 的组合。ROI 决定必须恰好覆盖 source 全集，绑定输入中每个明确视频的路径、摘要和真实分辨率；审核时间点须非空、为有限数值且位于源视频时长内。`run_input_roi` 使用 source 阶段复制出的媒体生成产物，并沿用其划分，不重新划分。（R5、R6）

这里的接入仍有范围差异：现有 `load_data_inputs` 即使只做 ROI，也要求 source tags/mapping、split、ROI、media 配置、处理器配置和 contract 等完整文件 pin。原操作文档规定其中使用旧 v3/v4.1 契约和 MiniCPM 配置；输入解析函数本身只钉扎这些文件，并不等于已验证本轮五类标签的语义。是否保留这个完整七阶段外壳，或先设计只覆盖 ROI 的输入边界，属于待确认的接口与状态流选择。（R6、R7）

## 3. 现有选框和审核规则

### 3.1 一个源视频使用一个固定框

固定 ROI 由拖拽框确认，目标宽高比为 **3:4**。保存的有效像素框是后续裁剪依据；实现把框规范为边界内的偶数像素精确 3:4 框，并同时保存边距、归一化框、源分辨率和交互方式。固定框不能以全零边距冒充不裁剪，正式校验要求 `interaction_mode=drag_box`、`aspect_ratio_strategy=crop_exact`。（R2、R3）

`no_crop` 保留完整源画面，其边距必须全零、交互方式为 `no_crop`、策略为 `pad_to_target`。物化时居中补黑边到容纳源画面的最小偶数像素精确 3:4 画布，不缩放。两种模式均不是跟踪移动试样的动态 ROI；固定框需覆盖整个过程中所需的观察范围。（R2—R4）

### 3.2 审核状态与人工承诺

每条决定保存 `approved` 或 `needs_review`。前者要求有已检查时间点，且五项可见性全部为真：上夹具、下夹具、完整试样可见，仍可判断相对位置，仍可判断是否齐根断裂。后者可保留尚未完成的记录，但正式 ROI 阶段拒绝未 approved 的决定。备注、审核时间和源文件大小、修改时间、SHA-256 一并保存。（R2、R3）

GUI 生成的关键时间点包括开头、25%、50%、75%、接近结尾；存在有限 `event_time` 时，还加入其前后 0.2 秒及该时刻。滑块初值也使用该字段，否则取视频中点。审核者勾选“我已检查关键时刻预览”后，保存的是生成的整组时间点；代码没有逐帧证明审核者确实观看，也不能证明这些稀疏时刻覆盖了全部关键现象。（R1、R2）

GUI 可以载入策略 1.0、1.1 的记录，但显示为旧策略待复审；正式校验只接受当前策略 **1.2** 和决定 schema **1.0**。旧记录能打开，不表示可以直接冻结。源文件大小或修改时间变化会触发界面警告，正式阶段还校验源摘要和分辨率；重新保存需重新核查内容，不能只更新摘要使检查通过。（R1—R3、R5）

### 3.3 裁剪及失败处理

媒体命令读取第一路视频，固定框采用 crop，不裁剪采用 pad，并设置 `setsar=1`；输出为 H.264、`preset=fast`、`CRF=23`、`yuv420p`，去除音频，使用 `-vsync 0`。这仍会重新编码，不能宣称像素无损。（R4）

输出检查要求分辨率符合目标、帧数相同、标称帧率在数值容差内相同、时长差不超过 `max(0.02 秒, 1/max(源标称帧率, 1 fps) + 0.005 秒)`。该检查未逐帧比较时间戳或视觉内容，因此只能表述为所列媒体属性通过，不能扩写为所有帧时间戳、细小裂纹或快速碎片均被无损保留。（R4）

正式阶段通过锁和临时目录生成，全部完成、输入及上游复核后才发布；既有阶段只在身份、文件清单和上游摘要一致时复用，冲突则拒绝覆盖。错误决定、覆盖不完整、源文件漂移、媒体命令失败或输出属性不符会停止该阶段；现有正式 ROI 阶段没有逐视频“跳过但继续发布”的分支。历史 `materialize_plan` 则允许未完成 bundle 中保留已生成的视频并在重跑时检查复用，两种失败恢复方式不能混称。（R4—R6）

## 4. 本轮五类标签需要验证什么

现有五项可见性审核集中于试样、夹具和位置，没有覆盖全部五类标签。本轮不能只因旧审核框全勾选，就断言裁剪后标签仍成立。

| 本轮判断 | 裁剪后必须保留的证据与现有规则缺口 |
| --- | --- |
| 断裂状态 | 首段连通性、首次可见分离、断后两端等证据。固定框和稀疏预览可能遗漏回弹、出画或短暂分离；几何合法不能验证状态正确。 |
| 断裂模式 | 断前塑性变形、局部形态及不同阶段的可靠证据。固定比例和重编码是否削弱小尺度信息，尚无本轮画面验证。 |
| 断裂位置 | 上下夹具和试样的相对关系。旧审核与此有直接联系，但新标签采用相对位置分类，不能把旧 `location_judgable` 当作新类别已经校准。 |
| 异常情况 | 未夹紧需观察相对滑移；视频异常可能来自原始拍摄；爆炸性断裂需保留碎片飞散范围。固定窄框可能截去异常证据；人工裁剪造成的信息损失也不应无说明地改成源视频异常标签。 |
| 断裂现象 | 伸长、颈缩、开裂、界面分离和断后脱夹各自需要过程、细节或夹具关系。现有五个复选框未逐项确认这些现象。 |

特别有三处需要先报告差异：

- **审核门与不确定样本：** 新标签允许某些字段无法确定、异常/现象无法判断，未断裂或未夹紧时模式和位置可填固定“无”。旧 ROI 门却要求位置、齐根判断等全真；真实缺少某项可见证据的样本可能无法进入正式阶段。是否按任务适用项审核、保留原审核门并另行分流，或采用其他处置，不能擅自决定。`no_crop` 同样需要五项全真，并不能自动解除这一限制。
- **事件时间与当前范围：** GUI 的审核抽帧和默认位置仍使用 `event_time`，与 DF-019 当前不使用断裂时间类标注的边界需要衔接。后续可考虑不用该字段的浏览与审核方式，但不能在尚未修改时宣称 ROI 工具已无此依赖，也不能据此重新启用事件时间标签。
- **整源标签与裁剪可判读性：** 裁剪可以改变可见证据。源视频五类标注不能无条件视为 ROI 产物或后续每个子片段的正确标签；是否需增加裁剪后复核、哪些字段可沿用，应在数据衔接方案中确认。

## 5. 供确认的设计问题

以下只请求方案决定，不表示获得代码修改或真实媒体处理授权。

| 编号 | 需要用户确认的具体问题 | 决定影响 |
| --- | --- | --- |
| ROI-Q1 | 本轮是否继续采用“每源视频一个固定 3:4 框，必要时全画面补边”的方式？若无法容纳夹具、回弹或碎片范围，是扩大固定框、使用全画面，还是另行设计？ | 决定几何与交互可沿用程度；不预设动态 ROI。 |
| ROI-Q2 | 是否继续要求五项可见性全部通过？对原本无法确定、未夹紧或视频异常的样本，采用适用项审核、独立分流还是其他明确规则？ | 决定哪些源视频可发布为 ROI 输入；不默认丢弃或强行通过。 |
| ROI-Q3 | 在不使用断裂时间类标注的前提下，如何确认完整过程已检查？是否采用均匀预览加人工浏览并记录检查范围，或其他不依赖 `event_time` 的方法？ | 决定审核证据及 GUI 适配；自动时间点本身不能证明检查充分。 |
| ROI-Q4 | 是否新增面向五类标签的信息保留检查，并对裁剪后证据不足记录独立复核结果？哪些源标签允许作为初值，哪些必须重看？ | 决定 ROI 与标签、后续子视频审查的衔接，避免改写原标签。 |
| ROI-Q5 | 输入、输出是否沿用正式七阶段 pin 与 stage 体系？若沿用，怎样接入新标注并解除旧契约/候选配置的语义耦合；若分阶段建设，ROI 独立边界是什么？ | 决定公共输入接口、状态流和迁移依赖；不擅自复制整套旧系统。 |
| ROI-Q6 | 是否保留现有重编码参数、去音频和媒体属性容差？需要哪些获准的非 test 样例检查细节、旋转方向、可变帧率和快速事件？ | 决定媒体验收口径；逐帧时间戳保留和视觉细节尚无证据。 |

输入范围、视频素材身份及其与既有划分的对应仍是上述设计落地的前置条件。任何后续 test 准备或隔离处理须另行确认，不因历史冻结库含 test 审计文件而默认获准。

## 6. 迁移候选范围及实施前验证

这里的“候选”表示待确认后再决定迁入，不是已经决定保留或已经迁移。

| 候选对象 | 静态审查意见 | 必要依赖与边界 |
| --- | --- | --- |
| `pipeline/scripts/roi_annotation_app.py` | 调整后候选；保留显式路径与拖框能力，按 ROI-Q1—Q4 处理审核语义和时间依赖 | 当前顶层导入 Streamlit、Pillow；GUI 另需 streamlit-cropper、ffmpeg/ffprobe。还依赖 `pipeline.current_data`、`artifact_resolver`，不能只拷贝文件。 |
| `pipeline/roi_manifest.py` 的决定校验 | 來源绑定、覆盖检查、几何一致性适合作为候选；全真审核和版本常量须跟随确认后的新策略 | 它从 GUI 模块导入常量和几何函数，故无界面校验仍带入 Streamlit/Pillow 依赖；是否抽出纯校验模块需方案及实施范围确认。 |
| `pipeline/roi_media.py` 的几何、命令与属性检查 | 作为算法候选，待 ROI-Q1、Q6 确认及媒体验证 | 依赖 ffmpeg/ffprobe；历史计划/索引部分另依赖 `artifact_index`、`artifact_resolver`、`current_data`。不要求因复用少量函数而迁入全部历史 bundle 写入。 |
| `versioning/data_pipeline.py::run_input_roi` 及阶段基础设施 | 保留来源 pin、上游复核与拒绝覆盖的约束意图；整体入口是否沿用待 ROI-Q5 | 依赖完整 source 阶段、输入 pin 解析、YAML、stage 发布和 versioning 模块；不是可单独复制的 ROI 脚本。 |
| 两个停用辅助 CLI | 作为历史证据保留，不列为本轮活动入口候选 | 不恢复其 LATEST/短前缀回退，不因旧脚本中仍有参数解析函数而迁入公开操作流程。 |
| 原 ROI 测试 | 按实际保留功能筛选并适配 | 涵盖几何、决定、来源变化和历史冻结/媒体行为；旧 CLI/LATEST 测试不能作为新入口验收要求。 |

原测试文件可在[GUI 测试](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/tests/test_roi_annotation_app.py)、[manifest 测试](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/tests/test_roi_manifest.py)、[media 测试](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/tests/test_roi_media.py)及[入口测试](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/tests/test_roi_entrypoint.py)定位。本次只查看了测试名称和覆盖线索，没有运行、收集或判定通过。

获得具体实施授权后，验证应覆盖最终待提交内容：先以合成记录核对路径显式性、全量覆盖、来源/策略漂移拒绝、边界框与不裁剪几何、适用项审核及失败发布行为；再在训练机状态和输入范围核对后，以获准的非 test 媒体检查方向、分辨率、帧数、时长、真实画面与五类证据是否保留。两层证据分别记录，轻量静态检查或合成测试不能代替真实媒体验收。长时间视频处理遵守训练机约束。

## 7. 本稿检查范围与失效条件

本次完成原项目指定源码及必要入口的静态阅读，区分了 GUI 决定、正式阶段与历史 bundle，核对了主要输入输出和版本约束。没有修改源代码、契约、阈值或 `facts.yaml`，没有运行真实媒体和模型。独立审查核对了上述主要入口，并用纯内存低帧率样例发现时长容差公式遗漏下限，本文已据源码修正；未发现其他可执行问题。该检查没有运行 GUI 或真实视频。本文是待确认审查稿，不能直接用作已批准的操作手册，仍需用户审阅。

**失效条件：** 原项目来源提交、ROI 策略/决定 schema、正式入口或相关依赖变化，或用户确认新的 ROI 方案、输入范围和五类标签规则后，本稿对应结论须重新核对。待确认方案实施并形成经核查的正式说明后，本文转为历史审查记录，或将仍有效结论并入新的权威文档；不得继续把本稿的问题表当作未变更的执行规则。
