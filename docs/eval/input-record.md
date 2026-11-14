# 输入记录：四层画面谱系 · 四个帧索引 · 一致性校验

**失效条件：** `data/sub_video/manifest.json` 移除或改变 `output.frame_mapping`／`output.frame_preserving_replay`／`output.media`／`sources[].roi_media` 的语义；媒体目录结构改变（含 `data/videos`、`data/roi/videos`、`data/sub_video/videos` 的层级或命名）；源→ROI 同序性证据被推翻或出现反例；`ffprobe`／`ffmpeg` 取帧语义改变；`script/five_label_eval/score.py` 的 `input_review_id` 校验行改变。以上任一发生，本文的四层谱系、推导链与校验判据都须重新核对。

## 1. 四层画面谱系

一条输入记录必须能沿四层回溯到原始素材。四层各记：媒体路径、sha256、fps、总帧数、宽高。

| 层 | 媒体 | 路径 | sha256 来源 | fps | 总帧数 | 宽高 |
| --- | --- | --- | --- | --- | --- | --- |
| L0 原始源视频 | `<video_id>.mp4` | `data/videos/<video_id>.mp4` | `sources[].source_sha256`（110/110 有） | 清单未直接给，须 `ffprobe` 实测 | 同上（实测，按解码帧计） | 同上（实测） |
| L1 ROI 视频 | `<video_id>.mp4` | `data/roi/videos/<video_id>.mp4` | `sources[].roi_sha256`（110/110 有） | `sources[].roi_media.fps`（110/110 有） | `sources[].roi_media.total_frames` | `sources[].roi_media.width/height` |
| L2 子视频（片段） | `<candidate_id>.mp4` | `data/sub_video/videos/<candidate_id>.mp4` | 候选 `output.sha256`（1621/1621 有，即 `clip_sha256`） | `output.media.fps`（1621/1621 有） | `output.media.total_frames` | `output.media.width/height` |
| L3 模型输入帧 | 抽出的 N 帧（PNG 导出，无独立媒体文件） | `<export_dir>/frame_<n>.png` | 逐帧 PNG 的 sha256 | 不适用（先后由 `display_order` 决定） | 送模型的帧数（帧数不是自由参数，见 `docs/eval/inference-entry.md` §7） | 每帧 PNG 的宽高（预处理后） |

**现状（写作时）**：`data/` 下无 `data/videos/`、`data/roi/videos/`、`data/sub_video/videos/` 目录，`.mp4` 被 `.gitignore` 忽略，媒体须另行授权取得；`data/roi/` 只有 `decisions.json` 与 `manifest.json`，`data/sub_video/` 只有 `audit.json`、`manifest.json`、`summary.json`。L0 的 fps／总帧数／宽高清单未直接提供，只能实测，不得沿用 L1 或 L2 的值代替。

## 2. 每帧四个索引

| 索引 | 含义 | 帧空间 | 取值约束 |
| --- | --- | --- | --- |
| `original_source_frame_index` | 该帧在 L0 原始源视频中的帧号 | L0 | 仅当该帧绑定 `verification` 且声明同序时填整数；否则填 `null` |
| `roi_frame_index` | 该帧在 L1 ROI 视频中的帧号 | L1 | 由 §4 推导，须落在 `[0, L1.total_frames)` |
| `clip_frame_index` | 该帧在 L2 片段中的帧号 | L2 | 由抽帧规则给出，须落在 `[0, L2.total_frames)` |
| `display_order` | 该帧在送模型序列中的位置 | 记录级序列 | 从 0 起连续，不跳号 |

**字段更名**：旧字段名 `source_frame_index` 已更名为 `original_source_frame_index`。更名原因是旧名既可读成「源视频帧号」也可读成「source_start_frame 推导出的帧号」，正是 §3 那个陷阱的来源。尚未合并的分支代码里仍用旧名 `source_frame_index`，读那些产物时须按旧名理解，不得与本契约的 `original_source_frame_index` 混为同一取值。

## 3. 命名陷阱：`source_start_frame` 的 "source" 指 **ROI 视频**

**`output.frame_mapping.source_start_frame` 里的 "source" 是「片段的直接来源」，即 L1 ROI 视频，不是 L0 原始源视频。** 键名沿用旧命名，字面与实际指代不一致。

| 误用 | 后果 |
| --- | --- |
| 把 `source_start_frame` 当 L0 原始源帧号，直接令 `original_source_frame_index = source_start_frame + clip_frame_index` | 跳过同序性验证就产出一批「看起来有值」的源帧号；这些值没有绑定任何 `verification`，按本契约必须全部回退为 `null`，等于整批 `original_source_frame_index` 全空——错误不会报错，只会让依赖源帧号的证据选择实验整批作废 |
| 把 `source_start_frame` 与 `anchors[].source_frame` 直接相减来推偏移 | 得到系统性偏移；两者分属 L1 与 L0 两个空间，不能直接相减 |

**正确用法**：`source_start_frame` 只参与 L1 空间内的推导（§4 第一级），L0 帧号只能由第二级、且必须带 `verification` 才能填。

**自检方法**：取任一有锚点的候选，用 `anchors` 三元组反查起点所在空间。以 `video_0001_fracture_01` 为例，锚点三元组为 `{output_frame: 191, roi_frame: 1164, source_frame: 1164}`，清单 `source_start_frame = 973`；`973 + 191 = 1164`，与 `roi_frame` 与 `source_frame` 同时相等，说明 973 是 ROI 空间的起点，且该候选源与 ROI 同序。若某个候选算出 `source_start_frame + anchors[].output_frame` 与 `anchors[].roi_frame` 不等，说明该候选的 `frame_mapping` 不能按本式使用，须停止整批并报错，不得就地调整。

## 4. 推导链

```text
clip_frame_index  --(+ source_start_frame − output_start_frame)-->  roi_frame_index
roi_frame_index   --(源→ROI 同序已验证，且绑定 verification)-->      original_source_frame_index
```

| 级 | 公式 | 前提 |
| --- | --- | --- |
| L2 → L1 | `roi_frame_index = source_start_frame + clip_frame_index − output_start_frame` | 该候选 `output.frame_mapping` 存在；当前 1621/1621 条 `output_start_frame == 0`，故实际退化为 `roi_frame_index = source_start_frame + clip_frame_index` |
| L1 → L0 | `original_source_frame_index = roi_frame_index` | **必须**满足 §5 的同序性证据，且该帧绑定记录级 `verification`（`verdict_id`／`method`／`evidence_sha256`／`checked_at`）；三级判定顺序见 §6 |

**无 `verification` 时**：该帧 `kind` 填 `unverified`，`original_source_frame_index` 填 `null`——不写 `0`、不写 `-1`、不省略字段。一条记录内不同帧允许取不同 `kind`；同一条记录内所有 `kind != "unverified"` 的帧必须来自同一 `verification`（记录级单对象），锚点来源与实测来源需并用时拆成两条记录。

## 5. 同序性证据三条（并列记录，不得只取其一）

| # | 证据 | 规模 | 说明 |
| --- | --- | --- | --- |
| 1 | 源与 ROI 的实测解码帧数逐例相等 | 写作时抽检 9 例，逐例相等 | 直接实测；只覆盖 9 例，不能外推到 110 个来源。计数口径按 §7 的 c2：取 `ffprobe -count_frames` 的实解码帧数，**不是**文件头 `nb_frames` |
| 2 | 清单 `sources[].frame_preserving_replay.status == "verified_frame_preserving_replay"`，`proof_type == "exact_static_spatial_pipeline_replay"`，`mapping == "source_frame_i_to_ROI_frame_i_by_verified_frame_preserving_pipeline"` | 110/110 | 与 `docs/facts.yaml` 的 DF-027、DF-028 一致；是声明侧证据，不替代独立复核 |
| 3 | `output.frame_mapping.anchors` 三元组中 `roi_frame == source_frame` 全等 | 1155/1155 三元组（579 条候选非空；`anchors` 键 1621/1621 都有，1042 条为空数组） | 清单生成侧逐帧记录；空数组表示无锚点，**不能**读成「已核实为不同序」 |

三条证据缺一不可：证据 1 只覆盖 9 例，证据 2 是声明，证据 3 只覆盖 579 条候选。**并列记录要求不因下面的实现而放宽**：同一条记录内所有 `kind != "unverified"` 的帧必须来自同一 `verification`（记录级单对象），锚点来源与实测来源需并用时拆成两条记录。

三条证据在实现里是 §6 三级判定的**输入**，不是彼此替代的判据：证据 3 对应优先级 1，证据 2 对应优先级 2 的 c1 与 c3，证据 1 的口径按 c2 改为解码帧数；实际档位分布见 §8。**独立复核结论未绑定前，仍不得只用优先级 2 的证据做逐帧追溯分析**（原因见 §11）：实现只保证「有证据才填帧号」，不保证「帧号已被字节级核对」。只凭证据 2 或只凭证据 3 提前填源帧号依然不合规。

## 6. 三级同序证据：判定顺序与 `method`

L1→L0（`roi_to_source`）的原始源帧号只在三级证据之一成立时填写。判定顺序固定为「先 anchors 全真 → 再来源级三条件 → 否则 `unverified`」，**任一更高级成立即停止**，不再检查更低级；都不成立时帧号留 `null`，不猜、不就近取整。实现为提交 `2baf363` 的 `script/five_label_eval/frames.py:146`（`derive_lineage`）。

**前置链（先于三级判定）**：以下任一失败即直接 `unverified` 并记失败 token，不进入三级判定。

| 顺序 | 前置条件 | 失败 token |
| ---: | --- | --- |
| 1 | `candidate.output` 存在 | `no_output` |
| 2 | `output.frame_preserving_replay.status == "verified_frame_preserving_replay"`（即 §7 的 c3） | `replay_unverified` |
| 3 | `clip_frame_index` 是非负整数 | `bad_clip_index` |
| 4 | `output.frame_mapping` 存在 | `no_frame_mapping` |
| 5 | `output.frame_mapping.source_start_frame` 是非负整数（L1 空间起点，见 §3） | `bad_source_start` |

前置链第 2 项说明 c3 是**两级共用的前置条件**，不是只有优先级 2 才要求；因此优先级 2 的失败 token 集合里 `c3_candidate_replay` 实际不可达——c3 不成立时已在前置链返回 `replay_unverified`。

| 优先级 | 节点／kind | 触发条件 | `method` |
| ---: | --- | --- | --- |
| 1 | `roi_to_source.kind = explicit_pairs` | `frame_mapping.anchors` 非空，且每条锚点同时满足 `roi_frame == source_start_frame + output_frame` 与 `source_frame == roi_frame` | `manifest_anchors` |
| 2 | `roi_to_source.kind = offset`（`offset = 0`） | `anchors` 为空或缺失，且 c1、c2、c3 全真（逐条见 §7） | `source_replay_mapping` |
| 3 | `roi_to_source.kind = unverified` | 以上都不成立 | `unverified` |

- 两级成立时都用 `offset = 0`：该级证据本身就是「`roi_frame == source_frame`」，差的只是 `kind`——优先级 1 记显式帧对 `explicit_pairs`，优先级 2 记偏移 `offset`。
- `anchors` 非空但任一条目非法或自相矛盾（`roi_frame != source_start_frame + output_frame` 或 `source_frame != roi_frame`）是**硬失败**，记 token `anchors_broken` 并停在 `unverified`，**绝不**回退到优先级 2；`anchors` 声明了但不是数组同样按硬失败处理。
- 帧级 `roi_to_source.method` 与记录级 `verification.method` 必须一致；`unverified` 时 `kind`、`method` 都写 `unverified`，`offset` 只能是 `null`（契约容忍 `0`）**不得非零**，且 `reason` 非空（节点自证，`frames.py:506`）；成立级别的节点 `offset` 必须是整数 `0`。
- 实测档位分布：579 条走优先级 1、1,042 条走优先级 2、0 条 `unverified`（来源见 §8）。

**失效条件：** `ROI_TO_SOURCE_METHODS` 的 method 名称、`kind` 与 `method` 的配对关系、锚点一致性判据或前置链顺序变更即失效（`frames.py:40`）。

## 7. 来源级三条件（c1／c2／c3）

只有优先级 2 需要这三条；三条同时成立才给出 `source_replay_mapping`，缺一条即 `unverified`。

| 编号 | 条件 | 判据 | 实现位置 |
| --- | --- | --- | --- |
| c1 | 来源记录可用 | 候选的 `source_video_id` 在 `sources[]` 中存在（`found is True`），且该来源 `frame_preserving_replay.status == "verified_frame_preserving_replay"`、`mapping == "source_frame_i_to_ROI_frame_i_by_verified_frame_preserving_pipeline"`（声明 `source_frame_i → ROI_frame_i` 同序的唯一常量） | `_source_record_usable`，`frames.py:98`；常量在 `frames.py:39` |
| c2 | L0 与 L1 的**实测解码帧数**相等 | `l0_decoded` 与 `l1_decoded` 都是正整数且相等；任一边缺失或探测失败都不算通过（不得当 0，也不得「缺一边按相等处理」） | `_source_decoded_counts_equal`，`frames.py:104` |
| c3 | 该候选自身 replay 已验 | `output.frame_preserving_replay.status == "verified_frame_preserving_replay"` | `derive_lineage`，`frames.py:146` |

- **c2 用实测解码帧数，不读文件头**：`decoded_frame_count` 走 `ffprobe -count_frames -show_entries stream=nb_read_frames`（`frames.py:274`），**不是**文件头 `nb_frames`；清单里的 `frame_count`／`metadata_frame_count` 也不参与。110 个来源里有 1 条的清单帧数与 ROI 实解码帧数不等，用清单值会把这个差异抹平（`frames.py:802` 注释）。
- **c2 的开销**：`-count_frames` 会全解码，同一路径一次运行内只探测一次（`_FRAME_COUNT_CACHE`，`frames.py:56`）。
- **`proof_type` 不在 c1 判据内**：§5 证据 2 把 `proof_type == "exact_static_spatial_pipeline_replay"` 列为声明侧条件，代码只校 `status` 与 `mapping`，`proof_type` 仅被读入来源证据索引供追溯（`frames.py:796`），不参与判定。清单实测该项 110/110 都是该值，两者目前没有分歧。
- c3 同时是 §6 的前置链条件；它在 `verification.conditions.source_replay` 三元组里仍被独立记录，前置链已失败时也如实写布尔值，便于按条件建诊断直方图。
- 三条的布尔值在三档都写进 `verification.conditions`：`explicit_pairs` 对应优先级 1 的锚点自检，`source_replay` 对应本节的 c1／c2／c3。

**失效条件：** 三条件任一字段名或字面量（`SOURCE_MAPPING`、`verified_frame_preserving_replay`）变更、c2 改回读文件头帧数、或来源级 replay 记录增加新条件即失效。

## 8. 实测覆盖率（`--coverage-scan` 全量扫描）

2026-11-14 对全量清单跑 `--coverage-scan`：只解析清单并数帧，不抽帧、不写视频、不产 PNG。

| 项 | 数值 | 占比 |
| --- | ---: | ---: |
| 候选总数 | 1,621 | 100% |
| `manifest_anchors`（优先级 1） | 579 | 35.72% |
| `source_replay_mapping`（优先级 2） | 1,042 | 64.28% |
| `unverified`（三级都不成立） | 0 | 0.00% |
| `frame_index_coverage` | 1.0000 | — |

- 579 + 1,042 + 0 = 1,621，与清单逐条对齐：本次只读核对 `data/sub_video/manifest.json` 得 `anchors` 非空 579 条、空数组 1,042 条、候选 1,621 条、`sources[]` 110 条。
- 扫描耗时约 11 分钟；开销来自对每个来源的 L0 与 L1 各做一次 `-count_frames`（§7），与候选条数无关。
- 只读元数据与帧数：扫描不做任何媒体摘要，也不写视频或图片；`--coverage-scan` 分支只产出 summary JSON（`frames.py:878`）。
- 每候选的判定以 `clip_frame_index = 0` 调用 `derive_lineage`（`_coverage_scan`，`frames.py:819`）。优先级 2 的偏移恒为 0，证据级别与具体帧号无关，故每候选结论代表该候选能拿到哪一级证据，不是逐帧取值的抽样。
- 只数帧数**不能**替代字节级摘要校验，这条限制见 §11。

**来源标注（区分实测与实现）**：三档计数、占比与 `frame_index_coverage` 来自上述 `--coverage-scan` 全量扫描；档位判据、`kind`／`method` 取值与字段名来自提交 `2baf363` 的实现；候选数、`anchors` 空／非空条数与来源数已用只读脚本对清单复核一致。

**失效条件：** 清单批次变更、三档判据（§6／§7）或 `frame_index_coverage` 定义变更后，本节数字即失效，须重跑 `--coverage-scan`。

## 9. 批级 summary：`lineage_summary` 与两种口径

schema 固定为 `five-label-lineage-summary/1`（`SUMMARY_SCHEMA`，`frames.py:44`）。统计项为各 `method` 的计数与占比，以及 `unverified` 的失败条件直方图。

| 字段 | 内容 |
| --- | --- |
| `total` | 参与统计的候选数 |
| `verified_by_method` | `manifest_anchors`／`source_replay_mapping`／`unverified` 三档计数；未知 `method` 一律归入 `unverified`，保证三档之和等于 `total` |
| `ratios` | 三档占比，`total = 0` 时为 0.0 |
| `unverified_reasons` | `unverified` 行的 `failed_conditions` token 直方图（一行多个 token 各计一次）；是 token 计数，不是自由文本 `reason` |
| `frame_index_coverage` | `(total − unverified) / total` |
| `warning`／`warning_text` | `unverified` 占比超过 5% 时置真并给出文案 |

- **告警不改退出码**：`unverified` 占比**超过** 5%（恰好 5% 仍算可接受）时打印 `!!! {warning_text}`，进程仍返回 0（`_report_coverage`，`frames.py:834`；阈值 `COVERAGE_WARNING_RATIO`，`frames.py:46`）。
- **口径区别（必须写清）**：`--coverage-scan` 是全量口径；抽帧／推理模式下 summary 只含本批来源。

| 模式 | 来源探测范围 | 未涉及来源的 c2 |
| --- | --- | --- |
| `--coverage-scan` | 全量：`add_source_decoded_counts(..., source_ids=None)` 探测全部 110 个来源（`frames.py:880`） | 每个来源都可判 |
| 抽帧／推理模式 | 只探测本批选中的候选用到的来源（`frames.py:889`） | `l0_decoded`／`l1_decoded` 保持缺省 `None`，c2 判不成立 |

两份产物**同一 schema 但没有 scope 标记字段**：不得并排比较，也不得当成同一口径的两次测量。把抽帧模式的 summary 当全批覆盖率，会把未探测来源的候选全误算成 `unverified`，读出虚高的 `unverified` 占比；反过来把全量 summary 当某批次的结论同样不成立。

**失效条件：** `SUMMARY_SCHEMA` 字面量、上述字段名、5% 阈值或两种口径的分支变更即失效。

## 10. 三个映射节点：名称与实际方向

`frames[].frame_index_mapping` 固定三个节点（`frames.py:677-679`）。名字与实际方向不完全一致，读取时一律以本表为准。

| 节点 | 实际方向 | 含义 |
| --- | --- | --- |
| `media_to_clip` | L2 → L3 | 从 L2 片段媒体按解码序取第 `clip_frame_index` 个解码帧作为 L3 模型输入；`kind = ffmpeg_select_nth_decoded_frame`、`offset = None`，是抽帧规则常量（`MEDIA_TO_CLIP`，`frames.py:53`），不做帧号换算 |
| `source_to_media` | **L2 → L1** | 记片段帧号到 ROI 帧号的加性偏移：`offset = source_start_frame`，`roi_frame_index = clip_frame_index + offset`。名字里的 source 指**片段自身的来源媒体（L1 ROI 视频）**，不是原始源视频 |
| `roi_to_source` | L1 → L0 | ROI 帧号 → 原始源视频帧号；`kind` 与 `method` 由 §6 的三级证据给出，成立时 `offset = 0` |

**`source_to_media` 这个名字是历史遗留、方向易误读，读取时以本表为准。** 代码同一处也留了命名陷阱注释（`frames.py:134-137`、`155-157`），并明确 `source_to_media` 记 L2→L1、`roi_to_source` 才是 L1→L0。该重命名是已确认的待办方向，已在 `docs/TODO.md` 登记为「7. MAPPING-NODE-RENAME — 重命名映射节点，消除 source_to_media 的方向误读」：登记前不得据名字反推方向。

补充：节点自证只覆盖后两项——`verify_lineage` 校 `source_to_media.offset` 与 `roi_to_source` 的形态，`media_to_clip` 是常量，不逐帧校验（`frames.py:380`、`451`、`506`）。

**失效条件：** 三个节点键名、方向或 `MEDIA_TO_CLIP` 的 `kind` 变更即失效；重命名落地后本表须整体替换。

## 11. 最重要：来源级证据在 ROI 重生成后会静默错位

**本节是全文最重要的限制。** 优先级 2（`source_replay_mapping`）的三条件只看声明与帧数，不看媒体字节。

失效场景：ROI 视频被单独重新生成——换编码器、改裁剪参数、或变帧率源改时间基——而 `sources[]` 的 replay 记录没有重算。此时 L0 与 L1 的**帧数可能仍然相等**，`status` 仍是 `verified_frame_preserving_replay`，`mapping` 常量没变，于是两条来源级条件（c1、c2）全真、c3 也仍成立，但**帧号已经错位**：同一个 `roi_frame` 在重生成后的 ROI 里指向另一张画面。

后果：1,042 条 `source_replay_mapping` 候选会静默给出错位的 `original_source_frame_index`，不报错、不降级、不告警；579 条 `manifest_anchors` 不受影响（候选自带显式帧对自证）。按 `method` 分组做的溯源结论，两组可信度因此不同。

所以：`--coverage-scan` 只读帧数，**不能替代字节级摘要校验**。帧数相等只证明「长度对得上」，不证明「内容对得上」。字节级校验在记录态另有位置——`lineage_media.l0/l1/l2` 的实测 `sha256` 与声明 `declared_sha256` 逐层比对（`verify_lineage`，`frames.py:488-501`），且实测 `lineage_sha256` 参与 `input_id` 身份（`frames.py:693`）；而 `--coverage-scan` 既不产记录，也不做任何媒体摘要。

触发条件（必须执行）：**ROI 重生成后必须重算 `sources[]` 的 replay 记录，并重新绑定 `evidence_sha256`。** 未重算前，该来源下的候选不得使用优先级 2 的证据，`original_source_frame_index` 须退回 `null`。来源级 `evidence_sha256` 取 `sources[].frame_preserving_replay.receipt_sha256`（`frames.py:238-241`）；候选 replay 里作为 L0／L1 声明摘要的 `source_sha256`／`roi_sha256` 同样要换（`frames.py:645-650`）。

**失效条件：** 来源级证据补上字节级校验、`lineage_media` 摘要比对或 `input_id` 身份构成变更即失效。

## 12. `verdict_id` 的粒度差异

`verdict_id` 形如 `replay@<receipt 前 12 位>`，但两级证据的粒度不同，引用前必须说明是哪一级。

| 级 | 取值来源 | 粒度 | 实测 |
| --- | --- | --- | --- |
| 优先级 1 anchors 级 | 候选自身 `output.frame_preserving_replay.receipt_sha256`（退化到 `source_receipt_sha256`） | 逐候选 | 579 条候选对应 579 个不同 `verdict_id` |
| 优先级 2 来源级 | `sources[].frame_preserving_replay.receipt_sha256`（`frames.py:238-241`） | 按来源 | 1,042 条候选只对应 106 个不同 `verdict_id` |
| `unverified` | 固定字符串 `unverified` | 不适用 | 全量扫描 0 条 |

1,042 条候选只对应 106 个不同 `verdict_id`，是因为这 1,042 条分布在 106 个来源上：清单共 110 个来源，其中 4 个来源只出 anchors 候选，故不进优先级 2。两级都用 `replay@` 前缀、都没有级别标记字段，只能靠 `verification.method` 区分（`_verdict_id`，`frames.py:82`）。

引用纪律：

- 按来源的 `verdict_id` **不能**当逐候选统计：把 106 当 1,042 条候选的独立证据数会低估，把 1,042 当 106 个来源的逐源证据会重复计数。
- 同一 `verdict_id` 出现在多条候选里，只说明它们共享同一条来源 replay 决策，不说明帧号经过逐候选核对。
- receipt 不可用时退化形态是 `replay@no-receipt:<status>`，不是合法证据身份。

**来源标注**：106 与 579 由提交 `2baf363` 的实现规则加对 `data/sub_video/manifest.json` 的只读核对得出（1,042 条 `anchors` 为空的候选涉及 106 个不同 `source_video_id`，去重后的来源 receipt 也是 106 个）；1,042 这一分母来自 §8 的全量扫描。

**失效条件：** `_verdict_id` 的前缀或截断长度、receipt 取值优先级变更，或新增级别标记字段即失效。

## 13. 帧号口径

- 一律按**可解码帧序列**计数，0 基。与标注表和 `ffmpeg select` 中 `n` 的语义（解码帧序号）同口径；清单实际用 `select=between(n\,A\,B)` 形式，不限于 `eq`。
- 文件头帧数与解码帧数不一致时**两者都记**：`video_0093` 文件头 771 帧、实际可解码 733 帧，`delta = 38`。记录级须给 `{decoded, container_header, delta}`，无不一致时该字段为 `null`。
- **不得用文件头计数参与取帧**，也不得用平均 fps 与时长反推帧号。

## 14. `size_bucket` 三档

| 档名 | 区间（按媒体实际宽度 `width`） | 判据 |
| --- | --- | --- |
| `w_le_200` | 宽 ≤ 200 | `width <= 200` |
| `w_200_400` | 200 < 宽 < 400 | `width < 400` |
| `w_gt_400` | 宽 ≥ 400 | 其余 |

- 规则标识 `SIZE_BUCKET_SOURCE = "width_rule_le200_lt400"`，记录里 `size_bucket_source` 取该标识（常量在 `script/five_label_eval/frames.py:36`，三档判定在 `size_bucket()` 函数体 `script/five_label_eval/frames.py:60-61`）。即 **200 归 `w_le_200`、400 归 `w_gt_400`**。
- **旧版边界表述已被实现取代**：旧文档写的「含下界不含上界」（把 200 归 `w_200_400`）与实现不符，不得再引用。
- `size_bucket` 必须由 `width` 机械推导，不允许人工指定；档名只是标签，归属一律以区间式为准。

## 15. 四层一致性自动校验

每次跑完自动执行，验不过即报错退出（非 0），**不静默、不出 `predictions.jsonl`**。

| # | 判据形式 | 失败含义 |
| --- | --- | --- |
| 1 | L3 ⊆ L2：每个 `clip_frame_index` ∈ `[0, L2.total_frames)`，且该帧在 L2 解码中实际存在 | 抽帧越界或片段帧数记错 |
| 2 | L2 ⊆ L1：`min(roi_frame_index) == source_start_frame + min(clip_frame_index) − output_start_frame`，且 `max(roi_frame_index) < L1.total_frames` | 片段不是 L1 的一段，或起点空间搞错 |
| 3 | L1 ↔ L0 同序：`L0.total_frames == L1.total_frames`（解码帧计）；或该候选 `anchors` 三元组满足 `roi_frame == source_frame`；或 `verification` 已绑定并声明同序 | L1 与 L0 不同序，或同序尚未绑定证据 |
| 4 | 锚点一致：命中锚点的帧，三个索引与锚点三元组逐项相等 | 锚点与推导冲突，须以锚点为准并记 issue（带候选 ID、帧号与两套取值） |
| 5 | 身份一致：记录 `candidate_id`／`clip_sha256`／`manifest_sha256` 与清单逐项相等 | 记录绑定了错误的候选或错误的清单版本 |

判据 3 的三个分支是「或」关系，任一成立即通过；三者都不成立时记录级 `verification` 为 `null`、所有 `original_source_frame_index` 为 `null`，**仍可出批次**（评分不受影响），但依赖源帧号的证据选择实验不得在该批次上做。

## 16. 逐层证据导出

每层都能导出 PNG 供人工核对，每次评测都产，不再只留在诊断脚本侧。

| 层 | 导出内容 | 用途 |
| --- | --- | --- |
| L0 | 源视频广角帧 PNG | 核对夹具关系与断裂位置是否在画面内 |
| L1 | ROI 视频对应帧 PNG | 核对 ROI 裁剪是否吃掉了关键区域 |
| L2 | 片段对应帧 PNG | 核对片段起点与时长 |
| L3 | 实际送模型的每一帧 PNG + 逐帧 sha256 + contact sheet | 核对模型输入本身 |

记录级给 `export_dir`、每帧 PNG 的 sha256、contact sheet 路径与 sha256。

**限制（不得省略）**：人能看到的导出图 ≠ 还原模型内部的视觉编码。processor 的切片、张量布局、`image_bound`、temporal 分组与导出 PNG 不对应；导出图只能证明「取到的是这几帧」，不能证明「模型内部看到的就是这些像素」。不得据导出图推定模型内部所见。

## 17. 并入旧版两条旁路

| 旧实现 | 位置 | 本轮处置 |
| --- | --- | --- |
| 数据构建期记录 `frame_artifacts`（含 path／sha256／size） | `mVllm_2/versioning/data_pipeline.py:1432` | 旧实现把帧证据留在旁路；本轮并入主链路，进输入记录 |
| 离线诊断脚本 `export_review_frames.py` 产出 `review_frames_manifest.json` | `mVllm_2/pipeline/scripts/diagnostics/SCRIPTS.md:26` | 同上：导出不再是独立离线动作，由 §16 每次评测自动产出 |

两条旁路共同的缺口是**帧号、实际像素尺寸、视频内容摘要**三样缺失，本轮必须补齐（见 `docs/eval/inference-entry.md` §7）。

## 18. 与 `input_review_id` 的绑定

| 项 | 规则 | 行号（`score.py`） |
| --- | --- | --- |
| 必填身份 | 输入人审记录须给 `candidate_id`、`clip_sha256` + 5 个 `REQUEST_KEYS`（`run_id`／`model_id`／`prompt_id`／`input_id`／`request_id`）+ `input_review_id` | 300–301 |
| 逐项一致 | 该记录的请求身份必须与对应预测请求**逐项完全相同**，否则 `InputError` | 307–309 |
| 重复修订 | 同一 `(请求身份, input_review_id)` 出现第二次 → `InputError` | 302–304 |
| 审核状态 | `review_status` ∈ `confirmed`／`draft`／`returned`／`question` | 305–306 |

绑定意义：输入记录证明「模型该看到哪几帧」，`input_review_id` 证明「人核对过这几帧确实是这些」。两者缺一时，帧号链路只是自证。当前 `data/subvideo-review/reviews.json` 的 `revisions` 长度为 0（真实人工审核 0 条），实际输入人审也尚未开始，故本节的绑定关系目前只有规则、没有数据。
