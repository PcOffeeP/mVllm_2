# 视频 ROI 迁移审查与待确认方案

**状态：供用户确认的静态审查稿，尚未实施迁移。** 原项目已有人工选框、决定校验和视频裁剪代码，可以提供迁移候选；但它的固定 3:4 画幅和审核门能否保留本轮五类标签所需的证据，仍需确认和验证。

ROI 是源视频中要保留的试样及相关观察区域。本文对应[迁移审查大纲](migration-review-outline.md)第 4 节 C，讨论**完整源视频的画面裁剪**。后续子视频的时间窗口与片段标签由其他环节确定。

| 先了解的事项 | 当前结论 |
| --- | --- |
| 可以研究复用什么 | 几何计算、源视频身份绑定、决定校验和媒体属性检查；均为候选，未决定直接迁入。 |
| 用户现在要决定什么 | 画面范围、审核条件、ROI 中时间信息的用途、五类证据复核、正式入口及编码验收，见第 2 节 ROI-Q1—Q6。 |
| 已做了什么 | 原稿完成源码静态审查；本次重写保留其发现、证据和待决项，并按用户澄清修正时间信息的适用边界。 |
| 尚未验证什么 | 未运行 GUI、读取视频画面、生成媒体、迁入脚本或使用 test；历史决定及本轮真实视频的可用性、方向、长视频表现和裁剪可判读性均未据此验真。 |

## 1. 先分清三种时间用途

用户最新澄清允许断裂时间类标签用于子视频生成；当前不训练或评价模型的时间预测任务。这两种用途应分开判断。

| 用途 | 本轮边界 |
| --- | --- |
| 子视频生成时定位与选窗 | 可以使用断裂帧、时间点或时间范围等时间信息；具体窗口及标签衔接规则仍需确认。 |
| 模型预测断裂时间 | 当前不训练、不评价此任务；面向模型判别的范围仍为断裂状态、断裂模式、断裂位置、异常情况和断裂现象五类。 |
| ROI 审核时定位预览画面 | 旧 GUI 使用 `event_time` 辅助抽帧和设置滑块初值。本轮是否沿用这一做法仍待 ROI-Q3 确认，不能从子视频用途直接推出。 |

已有时间记录保留，时间信息的使用边界已记录于 [facts.yaml](facts.yaml) 的 DF-013、DF-019。旧 GUI 使用 `event_time` 本身不构成与本轮范围的矛盾，也不能据此断定必须移除该字段；具体用途仍按 ROI-Q3 确认，本文不据此授权真实媒体处理。

## 2. 需要用户确认的六个问题

这些问题决定旧实现可以沿用到什么程度。**方案确认与代码修改、真实媒体处理授权分开核定。**

| 编号 | 需要用户确认的具体问题 | 决定影响 |
| --- | --- | --- |
| ROI-Q1 | 本轮是否继续采用“每源视频一个固定 3:4 框，必要时全画面补边”的方式？若无法容纳夹具、回弹或碎片范围，是扩大固定框、使用全画面，还是另行设计？ | 决定几何与交互可沿用程度；不预设动态 ROI。 |
| ROI-Q2 | 是否继续要求五项可见性全部通过？对原本无法确定、未夹紧或视频异常的样本，采用适用项审核、独立分流还是其他明确规则？ | 决定哪些源视频可发布为 ROI 输入；不默认丢弃或强行通过。 |
| ROI-Q3 | 本轮 ROI 审核是否继续以 `event_time` 辅助定位？无论是否使用，怎样通过预览、人工浏览及记录确认完整过程已检查？ | 决定时间信息在 ROI 环节的用途及 GUI 适配；子视频选窗可以用时间信息，但不自动确认 ROI 也沿用旧做法。自动时间点不能证明检查充分。 |
| ROI-Q4 | 是否新增面向五类标签的信息保留检查，并对裁剪后证据不足记录独立复核结果？哪些源标签允许作为初值，哪些必须重看？ | 决定 ROI 与标签、后续子视频审查的衔接，避免改写原标签。 |
| ROI-Q5 | 输入、输出是否沿用正式七阶段 pin 与 stage 体系？若沿用，怎样接入新标注并解除旧契约/候选配置的语义耦合；若分阶段建设，ROI 独立边界是什么？ | 决定公共输入接口、状态流和迁移依赖；不擅自复制整套旧系统。 |
| ROI-Q6 | 是否保留现有重编码参数、去音频和媒体属性容差？需要哪些获准的非 test 样例检查细节、旋转方向、可变帧率和快速事件？ | 决定媒体验收口径；逐帧时间戳保留和视觉细节尚无证据。 |

输入范围、视频素材身份及其与既有划分的对应仍是上述设计落地的前置条件。任何后续 test 准备或隔离处理须另行确认，不因历史冻结库含 test 审计文件而默认获准。

## 3. 旧工具怎样分工，分别产生什么

### 3.1 人工决定与正式裁剪是两个步骤

1. **GUI 只保存决定。** `roi_annotation_app.py` 接收明确的 metadata、输出路径和媒体项目根；人工选固定框或不裁剪，保存 JSON，不生成视频、不改标签 CSV。
2. **正式入口校验并生成媒体。** `python -m versioning data roi` 调用 `run_input_roi`，读取固定输入和已发布的 `source` 阶段，验证决定，裁剪或补边，最后发布 `roi` 阶段。
3. **历史 bundle 属于另一条产物路径。** 正式入口复用部分校验与媒体函数，但不调用历史 `build_roi_manifest_bundle` 或 `materialize_plan`；不能将两套路径拼成已经确认的新链路。（R1、R3—R7；来源索引见第 7 节）

| 环节 | 输入 | 输出及写入边界 |
| --- | --- | --- |
| 人工 ROI 准备 | 显式 metadata JSON、可解析的源视频路径、已有决定 JSON（若存在） | 可编辑决定 JSON；原子替换该输出文件。 |
| 正式 ROI 阶段 | `tensile-data/inputs/v1` YAML、其中的 `roi_decisions` 文件 pin、完整 `source` 阶段及其媒体和划分 | `STORE/data/working/BATCH/roi/` 下的 `media/<video_id>.mp4`、`roi_manifest.json`、`roi_decisions.frozen.json`、`stage_manifest.json`。 |
| 历史冻结库 | 决定 JSON、视频 metadata、含 `video_ids` 的 test manifest | 历史 manifest、冻结决定、`development_roi.json`、`test_roi_audit.json`、校验报告；不是本轮拟定输出。 |
| 历史媒体库 | 历史冻结目录、完全匹配的 metadata、可选视频 ID 子集 | 历史 media bundle、`video_meta.roi.json`、报告和索引；不是正式阶段的落盘格式。 |

历史冻结和媒体库使用 `roi-manifest-…`、`roi-media-…` 内容身份，并涉及集合索引、LATEST 和独立 bundle。`roi_freeze_decisions.py`、`roi_materialize_videos.py` 的公开 `main` 均已停用，普通调用返回退出码 2；保留 `_legacy_main` 和业务函数不表示公开命令仍可运行。（R7、R8）

### 3.2 输入不能只换成新 CSV 路径

| 入口 | 现有要求 | 本轮接入时需要注意什么 |
| --- | --- | --- |
| GUI metadata | JSON 数组，或含 `videos` 数组的对象；每条有唯一非空 `video_id`，由 `video_path` 找媒体。缺路径时回退到 `source/videos/<video_id>.mp4`。 | 新 CSV 或新目录不能直接视为已适配；需要明确记录如何对应本轮视频。GUI 不解析 LATEST、快照 ID 或短前缀；`_legacy_parse_args` 不是 `main` 使用的解析器。（R1） |
| 正式输入 pin | pin 是路径、文件大小与完整 SHA-256 的组合。决定恰好覆盖 source 全集，并绑定每条源视频路径、摘要和真实分辨率；审核时间点非空、有限且在时长内。 | 正式阶段使用 source 复制出的媒体，沿用其划分，不重新划分。（R5、R6） |
| 完整输入体系 | `load_data_inputs` 即使只做 ROI，也要求 source tags/mapping、split、ROI、media 配置、处理器配置及 contract 等完整文件 pin。 | 原操作文档使用旧 v3/v4.1 契约和 MiniCPM 配置。解析并固定文件不等于验证了新五类标签语义；保留七阶段体系还是建立独立 ROI 边界，见 ROI-Q5。（R6、R7） |

## 4. 现有规则做了什么，检查又止于哪里

### 4.1 两种画面处理方式

两种方式都对整段源视频采用同一画面范围，没有跟踪移动试样的动态 ROI。（R2—R4）

| 模式 | 几何与记录要求 | 生成视频时的行为 |
| --- | --- | --- |
| `fixed_roi`：固定框 | 拖框后规范为边界内、偶数像素、精确 3:4 的有效像素框；保存边距、归一化框、源分辨率和交互方式。不得以全零边距冒充不裁剪；正式校验要求 `interaction_mode=drag_box`、`aspect_ratio_strategy=crop_exact`。 | 按有效像素框 crop；固定框须覆盖全过程所需的观察范围。 |
| `no_crop`：保留全画面 | 边距全零，交互方式为 `no_crop`，策略为 `pad_to_target`。 | 居中补黑边至能容纳源画面的最小偶数像素精确 3:4 画布，不缩放。 |

### 4.2 审核通过代表哪些承诺

| 检查项 | 现有行为 | 证据边界 |
| --- | --- | --- |
| 决定状态 | 可保存 `approved` 或 `needs_review`；正式阶段拒绝未 approved 的决定。approved 须有已检查时间点，且五项可见性全部为真。 | 五项是上夹具、下夹具、完整试样可见，以及相对位置、是否齐根断裂仍可判断；尚未覆盖本轮全部五类标签。 |
| 审核记录 | 保存备注、审核时间，以及源文件大小、修改时间、SHA-256。 | 记录存在不证明画面已充分检查。 |
| 默认预览点 | 开头、25%、50%、75%、接近结尾；有有限 `event_time` 时加上该时刻及前后 0.2 秒。滑块初值也用该字段，否则取中点。 | 勾选“我已检查关键时刻预览”后保存整组生成时间点；代码不能逐帧证明实际观看，也不能证明稀疏预览覆盖全部关键现象。 |
| 策略版本 | GUI 可打开策略 1.0、1.1 的记录，但显示旧策略待复审；正式校验只接受策略 1.2、决定 schema 1.0。 | 能打开旧记录不等于可以直接冻结。 |
| 来源变化 | 大小或修改时间变化触发 GUI 警告；正式阶段另查摘要和分辨率。 | 重新保存须重新核查内容，不能只更新摘要以通过检查。 |

以上来自 R1—R3、R5。`no_crop` 仍须五项可见性全真，并不会绕过审核门。

### 4.3 重编码与输出检查

| 项目 | 现有规则 |
| --- | --- |
| 视频命令 | 读取第一路视频，crop 或 pad 后设置 `setsar=1`；H.264、`preset=fast`、`CRF=23`、`yuv420p`、去音频、`-vsync 0`。 |
| 分辨率与帧数 | 分辨率符合目标，帧数与源视频相同。 |
| 标称帧率 | 在数值容差内与源视频相同。 |
| 时长 | 差值不超过 `max(0.02 秒, 1/max(源标称帧率, 1 fps) + 0.005 秒)`。 |

这会重新编码，不能称为像素无损。上述检查没有逐帧比较时间戳或视觉内容；通过仅能说明所列媒体属性符合要求，不能证明所有帧时间戳、细小裂纹或快速碎片均无损保留。（R4）

### 4.4 正式阶段与历史库怎样处理失败

| 路径 | 发布、复用与失败行为 |
| --- | --- |
| 正式 `run_input_roi` | 用锁和临时目录生成；全部完成且复核输入、上游后才发布。既有阶段仅在身份、文件清单和上游摘要一致时复用，冲突拒绝覆盖。错误决定、覆盖不完整、源文件漂移、媒体命令失败或属性不符均停止阶段，没有逐视频“跳过但继续发布”分支。 |
| 历史 `materialize_plan` | 未完成 bundle 可保留已生成视频，重跑时检查并复用。不能将这一恢复方式写成正式阶段行为。 |

依据为 R4—R6。

## 5. 本轮五类标签还缺哪些画面保证

几何合法和旧审核框全勾选，都不能证明裁剪后的五类标签仍成立。下表说明需要保留什么，以及现有规则尚未证明什么。

| 本轮判断 | 必须保留的画面证据 | 已知缺口 |
| --- | --- | --- |
| 断裂状态 | 首段连通性、首次可见分离、断后两端。 | 固定框和稀疏预览可能漏掉回弹、出画或短暂分离。 |
| 断裂模式 | 断前塑性变形、局部形态、不同阶段的可靠证据。 | 固定比例与重编码是否削弱小尺度信息，未做本轮画面验证。 |
| 断裂位置 | 上下夹具与试样的相对关系。 | 旧 `location_judgable` 与此相关，但不表示已经校准本轮相对位置类别。 |
| 异常情况 | 未夹紧的相对滑移、原始拍摄异常、爆炸性断裂的碎片飞散范围。 | 窄框可能截去异常证据；裁剪损失不能无说明地改成源视频异常标签。 |
| 断裂现象 | 伸长、颈缩、开裂、界面分离、断后脱夹所需的过程、细节或夹具关系。 | 现有五个复选框未逐项确认这些现象。 |

还有两处标签衔接问题，不能通过选框本身解决：

- **旧审核门可能挡住本轮允许的不确定样本。** 新标签允许某些字段无法确定、异常/现象无法判断；未断裂或未夹紧时，模式和位置可填固定“无”。旧门却要求位置、齐根判断等全真。按适用项审核、保留原门另行分流或采用其他规则，须由 ROI-Q2 确认，不能默认丢弃或强行通过。
- **源标签不能无条件复制给 ROI 或子片段。** 裁剪会改变可见证据，子片段又会改变观察时段。是否增加裁剪后复核、哪些字段可作初值、哪些必须重看，须通过 ROI-Q4 及后续数据衔接方案确认。

ROI 中 `event_time` 的用途另见第 1 节及 ROI-Q3；它不属于上述标签矛盾，也不因当前不做模型时间预测而必须删除。

## 6. 迁移候选与后续验证

这里的“候选”表示待确认后再决定迁入，不是已经决定保留或已经迁移。

| 候选对象 | 静态审查意见 | 必要依赖与边界 |
| --- | --- | --- |
| `pipeline/scripts/roi_annotation_app.py` | 调整后候选；保留显式路径与拖框能力，按 ROI-Q1—Q4 处理审核语义及 `event_time` 的适用方式 | 当前顶层导入 Streamlit、Pillow；GUI 另需 streamlit-cropper、ffmpeg/ffprobe。还依赖 `pipeline.current_data`、`artifact_resolver`，不能只拷贝文件。 |
| `pipeline/roi_manifest.py` 的决定校验 | 来源绑定、覆盖检查、几何一致性适合作为候选；全真审核和版本常量须跟随确认后的新策略 | 它从 GUI 模块导入常量和几何函数，故无界面校验仍带入 Streamlit/Pillow 依赖；是否抽出纯校验模块需方案及实施范围确认。 |
| `pipeline/roi_media.py` 的几何、命令与属性检查 | 作为算法候选，待 ROI-Q1、Q6 确认及媒体验证 | 依赖 ffmpeg/ffprobe；历史计划/索引部分另依赖 `artifact_index`、`artifact_resolver`、`current_data`。不要求因复用少量函数而迁入全部历史 bundle 写入。 |
| `versioning/data_pipeline.py::run_input_roi` 及阶段基础设施 | 保留来源 pin、上游复核与拒绝覆盖的约束意图；整体入口是否沿用待 ROI-Q5 | 依赖完整 source 阶段、输入 pin 解析、YAML、stage 发布和 versioning 模块；不是可单独复制的 ROI 脚本。 |
| 两个停用辅助 CLI | 作为历史证据保留，不列为本轮活动入口候选 | 不恢复其 LATEST/短前缀回退，不因旧脚本中仍有参数解析函数而迁入公开操作流程。 |
| 原 ROI 测试 | 按实际保留功能筛选并适配 | 涵盖几何、决定、来源变化和历史冻结/媒体行为；旧 CLI/LATEST 测试不能作为新入口验收要求。 |

原测试文件可在[GUI 测试](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/tests/test_roi_annotation_app.py)、[manifest 测试](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/tests/test_roi_manifest.py)、[media 测试](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/tests/test_roi_media.py)及[入口测试](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/tests/test_roi_entrypoint.py)定位。原稿仅查看测试名称和覆盖线索，没有运行、收集或判定通过；本次重写未新增测试运行。

获得具体实施授权后，验证须覆盖最终待提交内容，分两层记录：

| 验证层次 | 检查对象 | 能证明与不能证明的内容 |
| --- | --- | --- |
| 合成记录与轻量检查 | 显式路径、全量覆盖、来源/策略漂移拒绝、边界框与不裁剪几何、确认后的审核规则、失败发布行为 | 验证所保留功能的规则与边界，不能代替真实媒体验收。 |
| 获准的非 test 媒体 | 在核对训练机状态和输入范围后，检查方向、分辨率、帧数、时长、真实画面与五类证据 | 评价实际裁剪后的可判读性；长时间视频处理须在训练机进行，不能由合成检查推定通过。 |

## 7. 来源、输入基准与源码索引

代码来源为原工作区 `/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2` 的 `main`，核对提交为 `2c272ce3548c917bbfa96fe474858f9bf1998893`。下文代码链接均指向该原工作区的实际文件，不指向本工作区尚未显示的同名路径。链接用于本机追溯；跨机器复核应在上述提交定位同一文件和函数，不能把这些绝对路径当作通用部署目录。

本轮输入以[项目导航](guide.md)列出的 `data/annotation-table-full.csv`、`data/videos/` 及[标签说明](label.md)为起点。这些材料尚未因整理完成而冻结、发布或接入训练。既有划分保留，新标注已按 ID 与划分清单对照，素材身份和后续允许处理范围仍待核查，见[数据划分审查](data-split-migration-review.md)；本稿不授权处理 test。断裂时间信息的适用范围以第 1 节的最新澄清为准；已有记录保留，不能把历史的宽泛排除措辞继续用作禁止子视频选窗的依据。

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

## 8. 检查记录与失效条件

| 记录 | 实际覆盖及限制 |
| --- | --- |
| 原稿静态审查 | 阅读原项目指定源码和必要入口，区分 GUI 决定、正式阶段、历史 bundle，核对主要输入输出和版本约束。未修改源码、契约、阈值或 `facts.yaml`，未运行真实媒体和模型。 |
| 原稿独立审查 | 核对主要入口，并以纯内存低帧率样例发现原时长容差公式漏掉下限；原稿已据源码修正。当时未发现其他可执行问题。未运行 GUI 或真实视频，此结论不代替本次改写的独立复核。 |
| 本次可读性重写 | 将概览、时间用途和用户待决问题前置；用表格区分工具、输入输出、审核、媒体和失败行为。已按原稿核对重要事实及边界，并定点回看 GUI、几何和媒体命令源码。未新增真实运行或模型效果证据。 |

本文仍是待确认审查稿，不能直接用作已批准的操作手册。

**失效条件：** 原项目来源提交、ROI 策略/决定 schema、正式入口或相关依赖变化，或用户确认新的 ROI 方案、输入范围和五类标签规则后，对应结论须重新核对。方案实施并形成经核查的正式说明后，本文转为历史审查记录，或将仍有效结论并入新的权威文档；不得继续把本稿问题表当作未变更的执行规则。
