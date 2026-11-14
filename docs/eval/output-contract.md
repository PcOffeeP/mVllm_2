# 输出契约：11 个叶字段 · 5 个顶层键 · 边界样例

**失效条件：** 术语统一分支 `feat/eval-unify-uncertain` 合入本分支后未复核本文末「代码同步状态」；`script/five_label_eval/score.py` 的 `VERSION`／`SINGLES`／`MULTIS`／`FIELDS`／`STATUS` 常量或 `allowed()`／`truth_cell()`／`_extract()`／`prepare()` 的判定行改变；`predictions.jsonl` 必填项改变；`docs/label.md` 的标签定义或 `docs/design-test.md` 的评分口径改变。以上任一发生，本文须重新核对后才能用于新批次。

行号一律指 `script/five_label_eval/score.py`（下称 `score.py`，本分支 530 行）。评分口径（分母定义、精确率口径）不在本文，见 `docs/design-test.md`。

## 1. 字段与取值

**11 个叶字段（`FIELDS`，20 行）= 3 个单值 + 8 个多选叶项**

| 叶字段（多选写 `组.叶项`） | 允许取值字面量 | 来源常量与行号 |
| --- | --- | --- |
| `断裂状态` | 未断裂 / 发生断裂 / 已断裂 / 无法判断 | `SINGLES` 13–17 |
| `断裂模式` | 脆性断裂 / 韧性断裂 / 半脆半韧断裂 / 无法判断 / 无 | `SINGLES` 13–17 |
| `断裂位置` | 标距内 / 标距外非根部 / 夹持根部 / 无法判断 / 无 | `SINGLES` 13–17 |
| `异常情况.未夹紧` | 是 / 否 / 无法判断 | 叶项名 `MULTIS` 18；值域 `allowed()` 112–113 |
| `异常情况.视频异常` | 是 / 否 / 无法判断 | 同上 |
| `异常情况.爆炸性断裂` | 是 / 否 / 无法判断 | 同上 |
| `断裂现象.伸长` | 是 / 否 / 无法判断 | 叶项名 `MULTIS` 19；值域 `allowed()` 112–113 |
| `断裂现象.颈缩` | 是 / 否 / 无法判断 | 同上 |
| `断裂现象.开裂` | 是 / 否 / 无法判断 | 同上 |
| `断裂现象.界面分离` | 是 / 否 / 无法判断 | 同上 |
| `断裂现象.断后脱夹` | 是 / 否 / 无法判断 | 同上 |

**取值顺序以 `script/five_label_eval/score.py` 的 `SINGLES` 为准**（上表仅按该常量顺序抄录，不自行排序）；多选叶项的 `是`／`否`／`无法判断` 同理由 `allowed()` 给出。

**5 个顶层键（`_extract()` 196 行的 `expected`）**

| 顶层键 | 类型 | 行号 |
| --- | --- | --- |
| `断裂状态`、`断裂模式`、`断裂位置` | 字符串单值，取值同上表前三行 | `SINGLES` 13–17 |
| `异常情况` | 对象，必须恰好给 3 个叶项 | `MULTIS` 18 |
| `断裂现象` | 对象，必须恰好给 5 个叶项 | `MULTIS` 19 |

其余常量：`VERSION` 12；`REQUEST_KEYS` 21 = `run_id/model_id/prompt_id/input_id/request_id`；`IDENTITY` 22 = `manifest_sha256/candidate_id/clip_sha256/source_id/source_type`；`STATUS` 23 = `success/request_failed/timeout/unprocessed`；`EVIDENCE` 24 = `sufficient/insufficient/unknown`。字段数是 11 叶字段／5 顶层键，与 `docs/design-test.md:206` 的「13 项」不是同一计数，勿混读。

**三条取值纪律**

1. **`无` 是合法确定值**，只出现在 `断裂模式`、`断裂位置`，表示未断裂或未夹紧下的固定组合，不等于「未标」。
2. **评分器不做归一化**：无别名映射、无全角／半角修正、无空白修正，取值只经 `allowed()`（112–113 行）比对。
3. **多选不许省略、不许用空列表代替「全部为否」**：父键非对象记 `invalid`（209–210 行），缺叶项记 `missing`（213–214 行），叶项集合不全另记 issue（201 行）。

## 2. 四类边界样例

| 样例 | 内容 | 评分器行为与行号 |
| --- | --- | --- |
| (a) 缺项 | 省略 `断裂位置` 与 `断裂现象.开裂` | 两项 `missing`（211–212、213–214 行）；`断裂现象` 叶项集合不全另记 issue（201 行）；`strict_format_valid=False`（220 行）；其余字段照常评分 |
| (b) 字面量错 | `断裂状态` 写自造值（如 `断裂`），或某多选叶项写 `无` | 该字段 `invalid`（215–216 行，`allowed()` 112–113 不含该值）；不波及其它字段；`strict_format_valid=False` |
| (c) 跨字段冲突 | `断裂状态=未断裂` 且 `断裂模式=韧性断裂` | 两字段各自 `valid` 并照常计分；`combinations()`（137 行）记冲突，聚合键 `prediction_combination_conflicts`（423 行）每行 +1；原文不改写、不纠正 |
| (d) 围栏包裹 | 整个 JSON 外有 Markdown 代码围栏或前后说明文字 | 仍能提取；issue `surrounding_text_or_fence`（191 行）；`strict_format_valid=False`（220 行）；字段判 `valid` |

**提取失败与 issue 全集**：`not exactly one extractable JSON object`（189 行，无对象或多于一个并列对象）、`top level is not object`（195 行）、`top_level_keys_mismatch`（198 行，顶层键集合不等于 5 键）、`<组名>: expected explicit per-item object`（201 行）。上述任一与 189／195 行同属「整份无法解析」时，11 个叶字段全记 `extraction_failed`；`strict_format_valid` 要求严格解析成功、无任何 issue、且 11 个字段全 `valid`（220 行）。`combinations()` 只对 `valid` 字段生效。

## 3. `predictions.jsonl` 必填项

每条由 `prepare()`（235 行）校验，逐条在 279–297 行。

| 项 | 要求 | 行号 |
| --- | --- | --- |
| `candidate_id`、`clip_sha256` + 5 个 `REQUEST_KEYS`（共 7 项） | 非空字符串；缺／空／非字符串 → `InputError`，CLI 退出码 2 | 279–281 |
| `status` | 必须 ∈ `STATUS` 四值：`success`／`request_failed`／`timeout`／`unprocessed` | 284–285 |
| `raw_output` | **键必须存在**；值为字符串或 `null`；失败行也要写 `"raw_output": null` | 286–287 |
| `input_review_id` | 可为 `null` 或省略；若给则非空字符串 | 282 |
| 批次三元组 | 一批只允许一个 `(run_id, model_id, prompt_id)`，混入第二个 → `InputError` | 288–291 |
| 每候选每批一行 | 同一候选在批内出现第二行 → `InputError` | 295–296 |
| `clip_sha256` 一致 | 必须等于清单中该 `candidate_id` 的 `clip_sha256` | 293 |
| 缺记录 | 不报错，按 `status="unprocessed"` 计，其 `raw_output` 不被提取 | 324–327 |

清单侧身份校验见 `validate_identity`（91 行）；`IDENTITY`（22 行）五字段必填，`source_type` ∈ `real|virtual`。

**硬约束：`raw_output` 是唯一样本载体，禁止在 predictions 行里旁挂结构化标签字段**（如 `labels`／`fields`／`parsed`）。理由：评分器只读 `raw_output` 并自行用 `extract()`／`_extract()`（152、162 行）重新解析，旁挂字段完全惰性——不报错、不参与任何指标；一旦解析器口径与旁挂字段不同，指标看着正常但测的不是模型真正输出的那份数据，且无法事后判定差异来源。

## 4. `无法判断` 的两个含义

| 出现位置 | 判定 | 行号 | 指标后果 |
| --- | --- | --- | --- |
| 单值字段（`断裂状态`／`断裂模式`／`断裂位置`） | **合法类别**：术语统一后 `truth_cell` 的 `and field not in SINGLES` 守卫使真值侧记 `valid` | `truth_cell` 121 | 计入 accuracy 分母（377–379 行），并作为 `SINGLES` 的一个标签参与逐类 recall／precision（399–404 行） |
| 多选叶项（8 项） | **未知标记**：真值侧记 `unknown` | `truth_cell` 121 | 因 377–379 行「真值非 `valid` 即跳过」被排除出 accuracy 分母；预测侧写 `无法判断` 在 384 行计入失败／不确定计数 |

两侧都不做换算：同一个字面量在两个位置得到两种语义，取决于字段属于 `SINGLES` 还是 `MULTIS`，与书写形式无关。349 与 375 行仍是 `("无法确定", "无法判断")` 双字面量元组（历史兼容字面量，不属于本契约现行取值，`6024d75` 未改动），因此这两行对两种写法都判为显式不确定。

## 5. 代码同步状态（本契约生效的前置条件）

本契约按**术语统一后**的口径写：单值字段的不确定值 = `无法判断`。术语统一提交 `6024d75`／`56cde0a`／`b295e88` 位于分支 `feat/eval-unify-uncertain`，**尚未并入**本分支 `feat/eval-input-contract`。在合并前：

| 项 | 未合并时的现状 | 影响 |
| --- | --- | --- |
| `SINGLES`（13–17 行）字面量 | 仍为旧值 `无法确定`（**历史字面量，非本契约现行取值**） | 按本契约写的单值 `无法判断` 会被 `allowed()` 判 `invalid` |
| `truth_cell` 121 行 | `field not in SINGLES` 守卫尚不存在 | 单值 `无法判断` 会被记 `unknown` 而非 `valid` |
| `field_metrics` 384 行 | `field not in SINGLES` 守卫尚不存在 | 单值 `无法判断` 会被计入失败／不确定计数 |

**因此合并 `feat/eval-unify-uncertain` 是本契约生效的前置条件**；合并前本分支的评分结果只能按旧口径读。行号在两版一致，本文引用不受合并影响。
