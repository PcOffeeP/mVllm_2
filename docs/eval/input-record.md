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
| L1 → L0 | `original_source_frame_index = roi_frame_index` | **必须**满足 §5 的同序性证据，且该帧绑定记录级 `verification`（`verdict_id`／`method`／`evidence_sha256`／`checked_at`） |

**无 `verification` 时**：该帧 `kind` 填 `unverified`，`original_source_frame_index` 填 `null`——不写 `0`、不写 `-1`、不省略字段。一条记录内不同帧允许取不同 `kind`；同一条记录内所有 `kind != "unverified"` 的帧必须来自同一 `verification`（记录级单对象），锚点来源与实测来源需并用时拆成两条记录。

## 5. 同序性证据三条（并列记录，不得只取其一）

| # | 证据 | 规模 | 说明 |
| --- | --- | --- | --- |
| 1 | 源与 ROI 的 `nb_frames` 逐例相等 | 本轮抽检 9 例，逐例相等 | 直接实测；只覆盖 9 例，不能外推到 110 个来源 |
| 2 | 清单 `sources[].frame_preserving_replay.status == "verified_frame_preserving_replay"`，`proof_type == "exact_static_spatial_pipeline_replay"`，`mapping == "source_frame_i_to_ROI_frame_i_by_verified_frame_preserving_pipeline"` | 110/110 | 与 `docs/facts.yaml` 的 DF-027、DF-028 一致；是声明侧证据，不替代独立复核 |
| 3 | `output.frame_mapping.anchors` 三元组中 `roi_frame == source_frame` 全等 | 1155/1155 三元组（579 条候选非空；`anchors` 键 1621/1621 都有，1042 条为空数组） | 清单生成侧逐帧记录；空数组表示无锚点，**不能**读成「已核实为不同序」 |

三条证据缺一不可：证据 1 只覆盖 9 例，证据 2 是声明，证据 3 只覆盖 579 条候选。**独立复核结论未绑定前，`kind` 一律填 `unverified`、`original_source_frame_index` 一律填 `null`**；只凭证据 2 或只凭证据 3 提前填源帧号均不合规。

## 6. 帧号口径

- 一律按**可解码帧序列**计数，0 基。与标注表和 `ffmpeg select` 中 `n` 的语义（解码帧序号）同口径；清单实际用 `select=between(n\,A\,B)` 形式，不限于 `eq`。
- 文件头帧数与解码帧数不一致时**两者都记**：`video_0093` 文件头 771 帧、实际可解码 733 帧，`delta = 38`。记录级须给 `{decoded, container_header, delta}`，无不一致时该字段为 `null`。
- **不得用文件头计数参与取帧**，也不得用平均 fps 与时长反推帧号。

## 7. `size_bucket` 三档

| 档名 | 区间（按媒体实际宽度 `width`） | 判据 |
| --- | --- | --- |
| `w_le_200` | 宽 ≤ 200 | `width <= 200` |
| `w_200_400` | 200 < 宽 < 400 | `width < 400` |
| `w_gt_400` | 宽 ≥ 400 | 其余 |

- 规则标识 `SIZE_BUCKET_SOURCE = "width_rule_le200_lt400"`，记录里 `size_bucket_source` 取该标识（`feat/eval-fake-slice:script/five_label_eval/frames.py:22`，判定在 34–35 行）。即 **200 归 `w_le_200`、400 归 `w_gt_400`**。
- **旧版边界表述已被实现取代**：旧文档写的「含下界不含上界」（把 200 归 `w_200_400`）与实现不符，不得再引用。
- `size_bucket` 必须由 `width` 机械推导，不允许人工指定；档名只是标签，归属一律以区间式为准。

## 8. 四层一致性自动校验

每次跑完自动执行，验不过即报错退出（非 0），**不静默、不出 `predictions.jsonl`**。

| # | 判据形式 | 失败含义 |
| --- | --- | --- |
| 1 | L3 ⊆ L2：每个 `clip_frame_index` ∈ `[0, L2.total_frames)`，且该帧在 L2 解码中实际存在 | 抽帧越界或片段帧数记错 |
| 2 | L2 ⊆ L1：`min(roi_frame_index) == source_start_frame + min(clip_frame_index) − output_start_frame`，且 `max(roi_frame_index) < L1.total_frames` | 片段不是 L1 的一段，或起点空间搞错 |
| 3 | L1 ↔ L0 同序：`L0.total_frames == L1.total_frames`（解码帧计）；或该候选 `anchors` 三元组满足 `roi_frame == source_frame`；或 `verification` 已绑定并声明同序 | L1 与 L0 不同序，或同序尚未绑定证据 |
| 4 | 锚点一致：命中锚点的帧，三个索引与锚点三元组逐项相等 | 锚点与推导冲突，须以锚点为准并记 issue（带候选 ID、帧号与两套取值） |
| 5 | 身份一致：记录 `candidate_id`／`clip_sha256`／`manifest_sha256` 与清单逐项相等 | 记录绑定了错误的候选或错误的清单版本 |

判据 3 的三个分支是「或」关系，任一成立即通过；三者都不成立时记录级 `verification` 为 `null`、所有 `original_source_frame_index` 为 `null`，**仍可出批次**（评分不受影响），但依赖源帧号的证据选择实验不得在该批次上做。

## 9. 逐层证据导出

每层都能导出 PNG 供人工核对，每次评测都产，不再只留在诊断脚本侧。

| 层 | 导出内容 | 用途 |
| --- | --- | --- |
| L0 | 源视频广角帧 PNG | 核对夹具关系与断裂位置是否在画面内 |
| L1 | ROI 视频对应帧 PNG | 核对 ROI 裁剪是否吃掉了关键区域 |
| L2 | 片段对应帧 PNG | 核对片段起点与时长 |
| L3 | 实际送模型的每一帧 PNG + 逐帧 sha256 + contact sheet | 核对模型输入本身 |

记录级给 `export_dir`、每帧 PNG 的 sha256、contact sheet 路径与 sha256。

**限制（不得省略）**：人能看到的导出图 ≠ 还原模型内部的视觉编码。processor 的切片、张量布局、`image_bound`、temporal 分组与导出 PNG 不对应；导出图只能证明「取到的是这几帧」，不能证明「模型内部看到的就是这些像素」。不得据导出图推定模型内部所见。

## 10. 并入旧版两条旁路

| 旧实现 | 位置 | 本轮处置 |
| --- | --- | --- |
| 数据构建期记录 `frame_artifacts`（含 path／sha256／size） | `mVllm_2/versioning/data_pipeline.py:1432` | 旧实现把帧证据留在旁路；本轮并入主链路，进输入记录 |
| 离线诊断脚本 `export_review_frames.py` 产出 `review_frames_manifest.json` | `mVllm_2/pipeline/scripts/diagnostics/SCRIPTS.md:26` | 同上：导出不再是独立离线动作，由 §9 每次评测自动产出 |

两条旁路共同的缺口是**帧号、实际像素尺寸、视频内容摘要**三样缺失，本轮必须补齐（见 `docs/eval/inference-entry.md` §7）。

## 11. 与 `input_review_id` 的绑定

| 项 | 规则 | 行号（`score.py`） |
| --- | --- | --- |
| 必填身份 | 输入人审记录须给 `candidate_id`、`clip_sha256` + 5 个 `REQUEST_KEYS`（`run_id`／`model_id`／`prompt_id`／`input_id`／`request_id`）+ `input_review_id` | 300–301 |
| 逐项一致 | 该记录的请求身份必须与对应预测请求**逐项完全相同**，否则 `InputError` | 307–309 |
| 重复修订 | 同一 `(请求身份, input_review_id)` 出现第二次 → `InputError` | 302–304 |
| 审核状态 | `review_status` ∈ `confirmed`／`draft`／`returned`／`question` | 305–306 |

绑定意义：输入记录证明「模型该看到哪几帧」，`input_review_id` 证明「人核对过这几帧确实是这些」。两者缺一时，帧号链路只是自证。当前 `data/subvideo-review/reviews.json` 的 `revisions` 长度为 0（真实人工审核 0 条），实际输入人审也尚未开始，故本节的绑定关系目前只有规则、没有数据。
