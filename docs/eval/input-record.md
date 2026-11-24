# 输入记录：四层画面谱系 · 四个帧索引 · 一致性校验

**失效条件：** `data/sub_video/manifest.json` 移除或改变 `output.frame_mapping`／`output.frame_preserving_replay`／`output.media`／`sources[].roi_media` 的语义；媒体目录结构改变（含 `data/videos`、`data/roi/videos`、`data/sub_video/videos` 的层级或命名）；源→ROI 同序性证据被推翻或出现反例；`ffprobe`／`ffmpeg` 取帧语义改变；`script/five_label_eval/score.py` 的 `input_review_id` 校验行改变。以上任一发生，本文的四层谱系、推导链与校验判据都须重新核对。

## 0. 实现状态（读正文前先读这张表）

**本文是规格，不等同于当前实现。** 下表逐项给出实现状态，读正文时以该表为准；标「规格要求但实现较宽／较窄」或「未实现」的条目，**不得当作已交付能力引用**——它们说的是「应该做到什么」，不是「现在能拿到什么」。行号为对 `feat/tensileagent-finetune`（`b9d4f57`）实读所得，代码变更后须重核。

| 能力 | 当前状态 | 落地位置或缺口 |
| --- | --- | --- |
| 1. 四层谱系与三帧号推导 | `已实现` | L0／L1／L2 层由 `_layer_media` 逐层产出（`script/five_label_eval/frames.py:336-363`），`lineage_media` 装配三层（`:645-651`）；`roi_frame_index = source_start + clip_frame_index`（`:203`）、`original_source_frame_index = roi_frame_index`（`:133`）。L3 只落 `frames[].image` 与 `pts_seconds`（`:670-676`）；逐帧摘要与宽高不在本项，见第 7 项 |
| 2. 三级同序证据（anchors／来源级／`unverified`） | `已实现` | 三档方法名 `ROI_TO_ORIGINAL_METHODS`（`:40`）；anchors 档含条目非法／自相矛盾的硬失败（`:211-231`），来源级走 `if c1 and c2`（`:232-241`），都不成立落 `unverified` 并写 `failed_conditions`（`:242-247`） |
| 3. `lineage_summary` 与 5% 警告 | `已实现` | `SUMMARY_SCHEMA`（`:44`）、`COVERAGE_WARNING_RATIO = 0.05`（`:46`）、`lineage_summary`（`:754-783`，只有**超过** 5% 才置 `warning`，判定在 `:775`）、`_report_coverage` 打印 `!!!` 且不改退出码（`:834-847`） |
| 4. 四层一致性校验 `verify_lineage` | `规格要求但实现较窄` | **已校**：判据 1 的区间检查（`:442`、`:449`）、判据 2 的加性偏移（`:451-459`）、判据 5 的两组摘要（`:484-501`、`:558-574`）。**较窄**：判据 1「该帧在 L2 解码中实际存在」无独立校验，只查 `0 <= idx < total`，存在性由抽帧成功隐含；判据 4 在 `verify_lineage` 里没有任何 anchors 比对，只有 `method == manifest_anchors` 的门控（`:398-403`），锚点一致性靠 `derive_lineage` 自证（`:218`）加「偏移公式 + 同号」在构造期隐含，记录本身也不含 anchors 列表可供独立比对；`--coverage-scan` 只调 `derive_lineage`（`:819-831`），**不执行** `verify_lineage`；推理模式只 `read_records`、不重验（`script/five_label_eval/infer.py:96`）。**更严**：判据 3 声明为「或」，实现对所有非 `unverified` 记录一律强制 `l0.total_frames == l1.total_frames`（`:425-427`） |
| 5. 逐层证据导出 `--export-lineage-png` | `已实现` | 默认关（`store_true`，参数 `:858-859`），调用分支在抽帧模式写完 records 之后（`:907-910`）；导出目录 `<out_dir>/lineage/<candidate_id>/`（`:726`），命名 `:738`、L3 复制 `:744-745`，跳过行写 `skips.jsonl`（`:747-750`）。边界：L3 复制用裸 `shutil.copyfile`（`:744-745`），失败不在「不中断」保证内，会落到 `main` 的 `OSError` 分支返回 2（`:912-914`） |
| 6. 帧号口径（0 基可解码、文件头差异） | `规格要求但实现较宽` | 解码计数走 `ffprobe -count_frames`（命令 `:281-282`，函数 `:274-290`）；`delta = decoded − container_header`（`:354`）、计数失败带 `reason`（`:351-352`）、无不一致为 `null`（`:356`）均与正文一致。差异在粒度：`frame_count_notes` 挂在**每层** `lineage_media.<layer>` 下（`:363`、`:645-651`），记录里没有单一记录级 `frame_count_notes` 字段 |
| 7. 逐帧 PNG 的宽高 | `规格要求但实现较窄` | `frames[]` 条目字段为 `display_order`／`decode_order`／`clip_frame_index`／`roi_frame_index`／`original_source_frame_index`／`is_anchor`／`anchor_ref`／`media_role`／`image`／`pts_seconds`／`frame_index_mapping`（`:670-680`），**没有** `width`／`height`；宽高只记到 L0／L1／L2 媒体层（`:357-363`、`:699-701`）。「每帧 PNG 宽高即 L2 宽高」是推断：抽帧命令只有 `select`+`showinfo`、无 `scale` 滤镜（`:603-606`），不是记录里的事实 |
| 8. `unverified` 记录下 L0／L1 缺 `declared_sha256` 时不记 reason | `已实现` | `if layer == "l2" or not unverified:`（`:495-497`）——`l2` 缺省恒判失败，`unverified` 的 L0／L1 缺省只 `continue` 不记 reason。判定为**有意**：L0／L1 的 `declared_sha256` 取自 replay 块的 `source_sha256`／`roi_sha256`（`:646-649`），`unverified` 记录该块可能缺失，不豁免则 §15「仍可出批次」不成立；但代码无注释、无专门测试，只有行为证据 |

## 1. 四层画面谱系

一条输入记录必须能沿四层回溯到原始素材。四层各记：媒体路径、sha256、fps、总帧数、宽高〔实现见状态表 1 与 7：L3 无独立媒体文件，只记 `frames[].image` 与帧数，sha256／fps／宽高均未入记录〕。

| 层 | 媒体 | 路径 | sha256 来源 | fps | 总帧数 | 宽高 |
| --- | --- | --- | --- | --- | --- | --- |
| L0 原始源视频 | `<video_id>.mp4` | `data/videos/<video_id>.mp4` | `sources[].source_sha256`（110/110 有） | 清单未直接给，须 `ffprobe` 实测 | 同上（实测，按解码帧计） | 同上（实测） |
| L1 ROI 视频 | `<video_id>.mp4` | `data/roi/videos/<video_id>.mp4` | `sources[].roi_sha256`（110/110 有） | `sources[].roi_media.fps`（110/110 有） | `sources[].roi_media.total_frames` | `sources[].roi_media.width/height` |
| L2 子视频（片段） | `<candidate_id>.mp4` | `data/sub_video/videos/<candidate_id>.mp4` | 候选 `output.sha256`（1621/1621 有，即 `clip_sha256`） | `output.media.fps`（1621/1621 有） | `output.media.total_frames` | `output.media.width/height` |
| L3 模型输入帧 | 抽出的 N 帧（PNG，无独立媒体文件） | `<out_dir>/<candidate_id>/frame_<nnn>.png`（`--out-dir` 下按候选分目录，落盘命名 `frame_%03d.png`，`frames.py:602-607`） | 记录不含逐帧 PNG 摘要：可核的只有 L2 媒体摘要（`clip_sha256`／`media.sha256`）与 `frames[].image` 这个文件名（`frames.py:676`） | 不适用（先后由 `display_order` 决定） | 送模型的帧数（帧数不是自由参数，见 `docs/eval/inference-entry.md` §7） | 每帧 PNG 的宽高即 L2 片段宽高（抽帧不加缩放滤镜）〔实现见状态表 7：记录未记逐帧宽高，此等式只由抽帧无 scale 滤镜推断〕 |

**现状**：本文写作时 `data/videos/`、`data/roi/videos/`、`data/sub_video/videos/` 三个媒体目录未检出；2026-11-14 实测三目录已存在，分别有 110、110、1,621 个 `.mp4`（`ls data/videos | wc -l` 等）。上述是历史记录，`data/sub_video/videos/` 当前为空目录；三个 JSON 已于 2026-11-19 删除。本页保留该批次的契约与历史核对，新批次生成后须按第 3 行失效条件重新核对。媒体字节被 `.gitignore` 的 `*.mp4` 忽略、不随本文档分发，真实数据处理仍按各阶段授权执行；`data/roi/` 除 `videos/` 外为 `decisions.json` 与 `manifest.json`。L0 的 fps／总帧数／宽高清单未直接提供，只能实测，不得沿用 L1 或 L2 的值代替。

## 2. 每帧四个索引

| 索引 | 含义 | 帧空间 | 取值约束 |
| --- | --- | --- | --- |
| `original_source_frame_index` | 该帧在 L0 原始源视频中的帧号 | L0 | 仅当**记录级** `verification.method != "unverified"`（声明同序）时填整数；否则填 `null`。`verification` 是记录级字段，帧条目不携带 `verification` |
| `roi_frame_index` | 该帧在 L1 ROI 视频中的帧号 | L1 | 由 §4 推导，须落在 `[0, L1.total_frames)`；记录级 `unverified` 时为 `null` |
| `clip_frame_index` | 该帧在 L2 片段中的帧号 | L2 | 由抽帧规则给出，须落在 `[0, L2.total_frames)` |
| `display_order` | 该帧在送模型序列中的位置 | 记录级序列 | 从 0 起连续，不跳号 |

**字段更名**：旧字段名 `source_frame_index` 已更名为 `original_source_frame_index`。更名原因是旧名既可读成「源视频帧号」也可读成「source_start_frame 推导出的帧号」，正是 §3 那个陷阱的来源。更名随提交 `2baf363` 落地后，记录 schema 与 `derive_lineage`／`verify_lineage` 一律只认新名。除本文这段更名说明自身的引用外，`script/` 下只余两处非 schema 命中：`script/five_label_eval/frames.py:17` 的模块 docstring 记着「删除旧的 ``source_frame_index``」这件事本身；`script/subvideo_generation/pilot/anchor_evidence.py:240` 只有一个名为 `source_frame_index_is_a_claim_not_a_verified_mapping` 的布尔标记键（语义是「帧号是声明而非已验证映射」，不是该字段）。本仓当前没有任何批次记录使用旧名。

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
clip_frame_index  --(+ source_start_frame)-->                        roi_frame_index
roi_frame_index   --(源→ROI 同序已验证，且绑定 verification)-->      original_source_frame_index
```

| 级 | 公式 | 前提 |
| --- | --- | --- |
| L2 → L1 | `roi_frame_index = source_start_frame + clip_frame_index` | 该候选 `output.frame_mapping` 存在，且 `source_start_frame` 是非负整数（实现原文 `roi_frame_index = source_start + clip_frame_index`，`frames.py:203`）；`output_start_frame` 不参与推导 |
| L1 → L0 | `original_source_frame_index = roi_frame_index` | **必须**满足 §5 的同序性证据，且记录级 `verification` 已绑定并声明同序（`verdict_id`／`method`／`evidence_sha256`／`checked_at` 均为记录级字段，帧条目不携带）；三级判定顺序见 §6 |

**关于 `output.frame_mapping.output_start_frame`**：该字段在清单中存在，但**当前实现不读取**——`frames.py` 里除 `derive_lineage` 的 docstring 声明（`:155`「是输出序起点，绝不参与 ROI 推导」）之外没有任何读取点，`derive_lineage` 只取 `source_start_frame`（`:199-203`）。它的含义是片段起点在片段自身输出序列里的帧号，与 ROI 帧号无关，清单实测恒为 0。**因而不存在「`output_start_frame` 恒为 0，所以含它和不含它等价」这种关系**：含 `− output_start_frame` 的写法在该字段非 0 时会给出错误结果，公式一律以本表的实现形式为准。（此处「不读取」限于评测侧：`script/five_label_eval/frames.py` 与 `script/five_label_eval/score.py` 均无读取点；生成期的切片自校验另会读到该字段，例如 `script/subvideo_generation/generate.py:372` 把它作为 `frame_mapping` 整体相等校验的一部分。）

**记录级 `unverified` 时**（`verification.method == "unverified"`，三级证据都不成立）：`unverified` 是**记录级**判定，由候选决定、不随帧号变化，**帧条目没有 `kind` 字段**——`kind` 只出现在 `frames[].frame_index_mapping` 的三个节点上。此时 `roi_frame_index` 与 `original_source_frame_index` 都是 `null`（不写 `0`、不写 `-1`、不省略字段），`clip_to_roi` 与 `roi_to_original` 两个节点的 `kind` 以及 `roi_to_original.method` 都写 `unverified`、`offset` 为 `null`、`reason` 非空。同一条记录内所有帧的 `roi_to_original.kind`／`method` **必然同值**，且都须与记录级 `verification.method` 配对：不配对即进 `verify_lineage` 的 reasons、`extract_record` 抛 `InputError`，故「同记录内不同帧取不同 `kind`」不成立。锚点来源与实测来源需并用时拆成两条记录。

## 5. 同序性证据三条（并列记录，不得只取其一）

| # | 证据 | 规模 | 说明 |
| --- | --- | --- | --- |
| 1 | 源与 ROI 的实测解码帧数逐例相等 | 写作时抽检 9 例，逐例相等 | 直接实测；只覆盖 9 例，不能外推到 110 个来源。计数口径按 §7 的 c2：取 `ffprobe -count_frames` 的实解码帧数，**不是**文件头 `nb_frames` |
| 2 | 清单 `sources[].frame_preserving_replay.status == "verified_frame_preserving_replay"`，`proof_type == "exact_static_spatial_pipeline_replay"`，`mapping == "source_frame_i_to_ROI_frame_i_by_verified_frame_preserving_pipeline"` | 110/110 | 与 `docs/facts.yaml` 的 DF-027、DF-028 一致；是声明侧证据，不替代独立复核 |
| 3 | `output.frame_mapping.anchors` 三元组中 `roi_frame == source_frame` 全等 | 1155/1155 三元组（579 条候选非空；`anchors` 键 1621/1621 都有，1042 条为空数组） | 清单生成侧逐帧记录；空数组表示无锚点，**不能**读成「已核实为不同序」 |

三条证据缺一不可：证据 1 只覆盖 9 例，证据 2 是声明，证据 3 只覆盖 579 条候选。**并列记录要求不因下面的实现而放宽**：同一记录的帧共用记录级 `verification`（记录级单对象；帧条目不携带 `verification`，`roi_to_original.kind`／`method` 逐帧同值），锚点来源与实测来源需并用时拆成两条记录。

三条证据在实现里是 §6 三级判定的**输入**，不是彼此替代的判据：证据 3 对应优先级 1，证据 2 对应优先级 2 的 c1 与 c3，证据 1 的口径按 c2 改为解码帧数；实际档位分布见 §8。**独立复核结论未绑定前，仍不得只用优先级 2 的证据做逐帧追溯分析**（原因见 §11）：实现只保证「有证据才填帧号」，不保证「帧号已被字节级核对」。只凭证据 2 或只凭证据 3 提前填源帧号依然不合规。

## 6. 三级同序证据：判定顺序与 `method`

L1→L0（`roi_to_original`）的原始源帧号只在三级证据之一成立时填写。判定顺序固定为「先 anchors 全真 → 再来源级三条件 → 否则 `unverified`」，**任一更高级成立即停止**，不再检查更低级；都不成立时帧号留 `null`，不猜、不就近取整。实现为 `script/five_label_eval/frames.py`（`derive_lineage`）。

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
| 1 | `roi_to_original.kind = explicit_pairs` | `frame_mapping.anchors` 非空，且每条锚点同时满足 `roi_frame == source_start_frame + output_frame` 与 `source_frame == roi_frame` | `manifest_anchors` |
| 2 | `roi_to_original.kind = offset`（`offset = 0`） | `anchors` 为空或缺失，且 c1、c2、c3 全真（逐条见 §7） | `source_replay_mapping` |
| 3 | `roi_to_original.kind = unverified` | 以上都不成立 | `unverified` |

- 两级成立时都用 `offset = 0`：该级证据本身就是「`roi_frame == source_frame`」，差的只是 `kind`——优先级 1 记显式帧对 `explicit_pairs`，优先级 2 记偏移 `offset`。
- `anchors` 非空但任一条目非法或自相矛盾（`roi_frame != source_start_frame + output_frame` 或 `source_frame != roi_frame`）是**硬失败**，记 token `anchors_broken` 并停在 `unverified`，**绝不**回退到优先级 2；`anchors` 声明了但不是数组同样按硬失败处理。
- 帧级 `roi_to_original.method` 与记录级 `verification.method` 必须一致；`unverified` 时 `kind`、`method` 都写 `unverified`，`offset` 只能是 `null`（契约容忍 `0`）**不得非零**，且 `reason` 非空（节点自证，`frames.py`）；成立级别的节点 `offset` 必须是整数 `0`。
- 实测档位分布：579 条走优先级 1、1,042 条走优先级 2、0 条 `unverified`（来源见 §8）。

**失效条件：** `ROI_TO_ORIGINAL_METHODS` 的 method 名称、`kind` 与 `method` 的配对关系、锚点一致性判据或前置链顺序变更即失效（`frames.py:40`）。

## 7. 来源级三条件（c1／c2／c3）

只有优先级 2 需要这三条；三条同时成立才给出 `source_replay_mapping`，缺一条即 `unverified`。

| 编号 | 条件 | 判据 | 实现位置 |
| --- | --- | --- | --- |
| c1 | 来源记录可用 | 候选的 `source_video_id` 在 `sources[]` 中存在（`found is True`），且该来源 `frame_preserving_replay.status == "verified_frame_preserving_replay"`、`mapping == "source_frame_i_to_ROI_frame_i_by_verified_frame_preserving_pipeline"`（声明 `source_frame_i → ROI_frame_i` 同序的唯一常量） | `_source_record_usable`，`frames.py:98`；常量在 `frames.py:39` |
| c2 | L0 与 L1 的**实测解码帧数**相等 | `l0_decoded` 与 `l1_decoded` 都是正整数且相等；任一边缺失或探测失败都不算通过（不得当 0，也不得「缺一边按相等处理」） | `_source_decoded_counts_equal`，`frames.py:104` |
| c3 | 该候选自身 replay 已验 | `output.frame_preserving_replay.status == "verified_frame_preserving_replay"` | `derive_lineage`，`frames.py:146` |

- **c2 用实测解码帧数，不读文件头**：`decoded_frame_count` 走 `ffprobe -count_frames -show_entries stream=nb_read_frames`（`frames.py:274`），**不是**文件头 `nb_frames`；清单里的 `frame_count`／`metadata_frame_count` 也不参与。110 个来源里有 1 条的清单帧数与 ROI 实解码帧数不等，用清单值会把这个差异抹平（`frames.py:805-806` 注释）。
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

- 579 + 1,042 + 0 = 1,621，与清单逐条对齐：本次只读核对 `data/sub_video/manifest.json` 得 `anchors` 非空 579 条、空数组 1,042 条、候选 1,621 条、`sources[]` 110 条；该批次已退役，当前以新批次清单为准。
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

## 10. 三个映射节点：名称与实际方向（`five-label-input-record/3`）

`frames[].frame_index_mapping` 固定三个节点（`frames.py` 常量 `MAPPING_NODE_KEYS`），记录 schema 为 **`five-label-input-record/3`**（2026-11-24 完成任务 7 `MAPPING-NODE-RENAME` 重命名，由 `DF-052` 取代 `DF-041`）：

| 现行节点（v3） | 实际方向 | 含义 | 旧 v2 键名（已废止） |
| --- | --- | --- | --- |
| `clip_to_model_input` | L2 → L3 | 从 L2 片段媒体按解码序取第 `clip_frame_index` 个解码帧作为 L3 模型输入；`kind = ffmpeg_select_nth_decoded_frame`、`offset = None`，是抽帧规则常量（`CLIP_TO_MODEL_INPUT`），不做帧号换算 | `media_to_clip` |
| `clip_to_roi` | **L2 → L1** | 记片段帧号到 ROI 帧号的加性偏移：`offset = source_start_frame`，`roi_frame_index = clip_frame_index + offset` | `source_to_media` |
| `roi_to_original` | L1 → L0 | ROI 帧号 → 原始源视频帧号；`kind` 与 `method` 由 §6 的三级证据给出，成立时 `offset = 0` | `roi_to_source` |

抽帧取证工具按本表方向读取映射。

**旧批次记录处理策略（显式拒绝，不做静默兼容）**：当前仓库尚无已冻结的正式 v2 输入记录。`five-label-input-record/3` 在 `read_records` 与 `verify_lineage` 中**显式拒绝**旧 `record_schema`（如 `five-label-input-record/2`）以及含任一旧键名（`media_to_clip`、`source_to_media`、`roi_to_source`）的记录，报错均点名期望的 `five-label-input-record/3` 与新键名；历史 v2 命名遗留仅留作本表对照与 `DF-041`（`superseded`）追溯。

补充：节点自证覆盖后两项——`verify_lineage` 校 `clip_to_roi.offset` 与 `roi_to_original` 的形态，并拦截任何旧键名或旧 `record_schema`；`clip_to_model_input` 是常量，不逐帧校验。

**失效条件：** `RECORD_SCHEMA`、三个节点键名、方向、`CLIP_TO_MODEL_INPUT` 的 `kind` 或旧 v2 拒绝策略变更即失效。

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

**来源标注**：106 与 579 由提交 `2baf363` 的实现规则加对 `data/sub_video/manifest.json` 的只读核对得出（1,042 条 `anchors` 为空的候选涉及 106 个不同 `source_video_id`，去重后的来源 receipt 也是 106 个）；1,042 这一分母来自 §8 的全量扫描；该批次已退役，当前以新批次清单为准。

**失效条件：** `_verdict_id` 的前缀或截断长度、receipt 取值优先级变更，或新增级别标记字段即失效。

## 13. 帧号口径

- 一律按**可解码帧序列**计数，0 基。与标注表和 `ffmpeg select` 中 `n` 的语义（解码帧序号）同口径；清单实际用 `select=between(n\,A\,B)` 形式，不限于 `eq`。
- 文件头帧数与解码帧数不一致时**两者都记**，`delta` 的方向由实现固定为 **`delta = decoded − container_header`**（`frames.py:354`，即实测可解码帧数减文件头声明帧数）。`video_0093` 文件头 `container_header` 771 帧、实际可解码 `decoded` 733 帧，故 **`delta = 733 − 771 = −38`**（可解码帧比文件头少 38 帧）。记录级须给 `{decoded, container_header, delta}`，无不一致时该字段为 `null`（三键在 `frames.py:354` 给出；计数失败时整块另带 `reason`，见 `frames.py:351-352`；无不一致时整块为 `null`，见 `frames.py:356`）。〔实现见状态表 6：该块在每层 `lineage_media.<layer>` 下各一份，无记录级单一字段〕
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

抽帧模式每产出一条记录即执行一次（`frames.py:703`），验不过即报错退出（非 0），**不静默、不出 `predictions.jsonl`**〔实现见状态表 4：`--coverage-scan` 不执行 `verify_lineage`，推理模式只 `read_records` 不重验〕。

| # | 判据形式 | 失败含义 |
| --- | --- | --- |
| 1 | L3 ⊆ L2：每个 `clip_frame_index` ∈ `[0, L2.total_frames)`，且该帧在 L2 解码中实际存在〔实现见状态表 4：记录态只校区间，逐帧存在性由抽帧成功隐含〕 | 抽帧越界或片段帧数记错 |
| 2 | L2 ⊆ L1：逐帧 `roi_frame_index == clip_frame_index + clip_to_roi.offset`（`offset = source_start_frame`），且每个 `roi_frame_index` ∈ `[0, L1.total_frames)` | 片段不是 L1 的一段，或起点空间搞错 |
| 3 | L1 ↔ L0 同序：`L0.total_frames == L1.total_frames`（解码帧计）；或该候选 `anchors` 三元组满足 `roi_frame == source_frame`；或 `verification` 已绑定并声明同序 | L1 与 L0 不同序，或同序尚未绑定证据 |
| 4 | 锚点一致：命中锚点的帧，三个索引与锚点三元组逐项相等〔实现见状态表 4：`verify_lineage` 无锚点比对，只由 `derive_lineage` 自证加偏移公式隐含〕 | 锚点与推导冲突，须以锚点为准并记 issue（带候选 ID、帧号与两套取值） |
| 5 | L2 摘要一致：`record.clip_sha256` 与 `record.media.sha256` 都必须等于 `lineage_media.l2.sha256`（实测值，`_digest_identity_reasons`，`frames.py:558-574`），且每层 `lineage_media` 的实测 `sha256` 必须等于其 `declared_sha256`（`frames.py:488-501`）；`l2` 的 `declared_sha256` 缺失或空串恒判失败，而 `unverified` 记录的 L0／L1 缺 `declared_sha256` 时不记 reason（`frames.py:494-498`） | 记录摘要与实测媒体字节不一致，或实测字节与清单声明不一致 |

判据 3 的三个分支是「或」关系，任一成立即通过〔实现见状态表 4：非 `unverified` 记录一律另加强制 `l0.total_frames == l1.total_frames`，比「或」更严〕；三者都不成立时记录级 `verification.method` 为 `unverified`（`verification` 块必定存在：`verify_lineage` 缺块即判失败，`frames.py:389-392`），所有帧的 `original_source_frame_index` 与 `roi_frame_index` 都是 `null`，**仍可出批次**（评分不受影响），但依赖源帧号的证据选择实验不得在该批次上做。

**`candidate_id` 与 `manifest_sha256` 不在 `verify_lineage` 的校验范围内**：两者都在 `extract_record` 构造记录时确定——`candidate_id` 直接取自清单候选（`frames.py:623-624`），`manifest_sha256` 由清单文件字节实算（正常路径在 `main()`，`frames.py:876`；`extract_record` 内的兜底分支在 `frames.py:638-639`）；`verify_lineage` 只校帧号范围、映射节点形态与摘要，不回头比对清单，故「记录与清单逐项相等」不是它给出的保证。

## 16. 逐层证据导出（`--export-lineage-png`，默认不产）

逐层 PNG **不是每次评测都产**：默认只抽 L3 的帧图（落到 `out_dir/<candidate_id>/`），四层证据导出须在命令行显式加 `--export-lineage-png` 开关（参数定义 `frames.py:858`，调用分支 `frames.py:907-910`）。不加开关时不产出任何 L0／L1／L2 层图。实现里**没有** `export_dir` 字段，也**没有** contact sheet（实测 `grep -rn "export_dir\|contact_sheet" script/` 零命中）。

| 层 | 开关打开时导出什么 | 用途 |
| --- | --- | --- |
| L0 | 源视频第 `roi_frame_index` 个解码帧 PNG | 核对夹具关系与断裂位置是否在画面内 |
| L1 | ROI 视频第 `roi_frame_index` 个解码帧 PNG | 核对 ROI 裁剪是否吃掉了关键区域 |
| L2 | 片段第 `clip_frame_index` 个解码帧 PNG | 核对片段起点与时长 |
| L3 | 把抽帧阶段已落盘的 `out_dir/<candidate_id>/frame_*.png` 复制进导出目录 | 核对模型输入本身 |

- **输出位置**：`<out_dir>/lineage/<candidate_id>/`（`export_lineage_png`，`frames.py:721-726`），与 `--out-dir` 同一根的子树。
- **命名规则**（`frames.py:730-738`、`744-745`）：L0／L1／L2 为 `<candidate_id>_L0_f<roi_frame_index>.png`、`<candidate_id>_L1_f<roi_frame_index>.png`、`<candidate_id>_L2_f<clip_frame_index>.png`；L3 为 `<candidate_id>_L3_order<display_order>.png`。
- **记录里如何引用**：记录仍只给 `frames[].image`（抽帧阶段的文件名，如 `frame_001.png`，`frames.py:676`）。**记录不含导出目录、不含逐帧 PNG 的 sha256，也没有 contact sheet 字段**；导出目录只能由 `--out-dir` 与 `candidate_id` 反推，读记录读不到。
- **失败不中断**：某层取不到整数帧号（`unverified` 记录的 `roi_frame_index` 为 `null`，`frames.py:733-737`）或 ffmpeg 导出失败时，该帧记进 `<out_dir>/lineage/<candidate_id>/skips.jsonl`（`frames.py:748-750`），脚本仍返回 0，并打印 `Lineage PNGs: N exported, M skipped`（`frames.py:909`）。

**限制（不得省略）**：人能看到的导出图 ≠ 还原模型内部的视觉编码。processor 的切片、张量布局、`image_bound`、temporal 分组与导出 PNG 不对应；导出图只能证明「取到的是这几帧」，不能证明「模型内部看到的就是这些像素」。不得据导出图推定模型内部所见。

## 17. 并入旧版两条旁路

| 旧实现 | 位置 | 本轮处置 |
| --- | --- | --- |
| 数据构建期记录 `frame_artifacts`（含 path／sha256／size） | `mVllm_2/versioning/data_pipeline.py:1432` | 旧实现把帧证据留在旁路；本轮并入主链路，进输入记录 |
| 离线诊断脚本 `export_review_frames.py` 产出 `review_frames_manifest.json` | `mVllm_2/pipeline/scripts/diagnostics/SCRIPTS.md:26` | 同上：导出不再是独立离线动作，加 `--export-lineage-png` 即随主链路产出（默认不产，见 §16） |

两条旁路共同的缺口是**帧号、实际像素尺寸、视频内容摘要**三样缺失，本轮必须补齐（见 `docs/eval/inference-entry.md` §7）〔实现见状态表 7：逐帧 PNG 宽高尚未入记录，像素尺寸只到 L0／L1／L2 媒体层〕。

## 18. 与 `input_review_id` 的绑定

| 项 | 规则 | 行号（`score.py`） |
| --- | --- | --- |
| 必填身份 | 输入人审记录须给 `candidate_id`、`clip_sha256` + 5 个 `REQUEST_KEYS`（`run_id`／`model_id`／`prompt_id`／`input_id`／`request_id`）+ `input_review_id` | 300–301 |
| 逐项一致 | 该记录的请求身份必须与对应预测请求**逐项完全相同**，否则 `InputError` | 307–309 |
| 重复修订 | 同一 `(请求身份, input_review_id)` 出现第二次 → `InputError` | 302–304 |
| 审核状态 | `review_status` ∈ `confirmed`／`draft`／`returned`／`question` | 305–306 |

绑定意义：输入记录证明「模型该看到哪几帧」，`input_review_id` 证明「人核对过这几帧确实是这些」。两者缺一时，帧号链路只是自证。当前 `data/subvideo-review/reviews.json` 的 `revisions` 长度为 0（真实人工审核 0 条），实际输入人审也尚未开始，故本节的绑定关系目前只有规则、没有数据。
