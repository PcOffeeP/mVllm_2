# 输出契约：11 个叶字段 · 5 个顶层键 · 边界样例

**失效条件：** `script/five_label_eval/score.py` 的 `VERSION`／`SINGLES`／`MULTIS`／`FIELDS`／`STATUS` 常量或 `allowed()`／`truth_cell()`／`_extract()`／`prepare()`／`field_metrics()` 的判定行改变（本文末「代码同步状态」已按 `VERSION = "five-label-score/3"` 核对，上述常量或判定行一旦改动须重新核对）；`predictions.jsonl` 必填项改变；`docs/label.md` 的标签定义或 `docs/design-test.md` 的评分口径改变。以上任一发生，本文须重新核对后才能用于新批次。

行号指 `script/five_label_eval/score.py`（下称 `score.py`）现行版本。评分口径（分母定义、精确率口径）不在本文，见 `docs/design-test.md`。

## 1. 字段与取值

**11 个叶字段（`FIELDS`，20 行）= 3 个单值 + 8 个多选叶项**

| 叶字段（多选写 `组.叶项`） | 允许取值字面量 | 来源常量与行号 |
| --- | --- | --- |
| `断裂状态` | 未断裂 / 发生断裂 / 已断裂 / 无法判断 | `SINGLES` 13–17 |
| `断裂模式` | 脆性断裂 / 韧性断裂 / 半脆半韧断裂 / 无法判断 | `SINGLES` 13–17 |
| `断裂位置` | 标距内 / 标距外非根部 / 夹持根部 / 无法判断 | `SINGLES` 13–17 |
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

其余常量：`VERSION` 12；`REQUEST_KEYS` 21 = `run_id/model_id/prompt_id/input_id/request_id`；`IDENTITY` 22 = `manifest_sha256/candidate_id/clip_sha256/source_id/source_type`；`STATUS` 23 = `success/request_failed/timeout/unprocessed`；`EVIDENCE` 24 = `sufficient/insufficient/unknown`。字段数是 11 叶字段／5 顶层键，与 `docs/design-test.md:210` 的「13 项」不是同一计数，勿混读。

**三条取值纪律**

1. **`无` 不是片段层模式／位置合法值**：旧人工值由 `truth_cell()` 判 `invalid`，模型值亦 `invalid`；帧号／时间列的「无」不受影响。
2. **评分器不做归一化**：无别名映射、无全角／半角修正、无空白修正，取值只经 `allowed()`（112–113 行）比对。
3. **多选不许省略、不许用空列表代替「全部为否」**：父键非对象记 `invalid`（209–210 行），缺叶项记 `missing`（213–214 行），叶项集合不全另记 issue（201 行）。

## 2. 四类边界样例

| 样例 | 内容 | 评分器行为与行号 |
| --- | --- | --- |
| (a) 缺项 | 省略 `断裂位置` 与 `断裂现象.开裂` | 两项 `missing`（211–212、213–214 行）；`断裂现象` 叶项集合不全另记 issue（201 行）；`strict_format_valid=False`（220 行）；其余字段照常评分 |
| (b) 字面量错 | `断裂状态` 写自造值（如 `断裂`），或模式／位置及某多选叶项写 `无` | 该字段 `invalid`（215–216 行，`allowed()` 112–113 不含该值）；不波及其它字段；`strict_format_valid=False` |
| (c) 跨字段冲突 | `断裂状态=未断裂` 且 `异常情况.爆炸性断裂=是` | 两字段各自 `valid` 并照常计分；`combinations()`（137 行）记冲突，聚合键 `prediction_combination_conflicts`（444 行）每行 +1；原文不改写、不纠正 |
| (d) 围栏包裹 | 整个 JSON 外有 Markdown 代码围栏或前后说明文字 | 仍能提取；issue `surrounding_text_or_fence`（191 行）；`strict_format_valid=False`（220 行）；字段判 `valid` |

`未断裂` + 具体模式／位置自 `five-label-score/3` 起不再记为冲突。

**提取失败与 issue 全集**：`not exactly one extractable JSON object`（189 行，无对象或多于一个并列对象）、`top level is not object`（195 行）、`top_level_keys_mismatch`（198 行，顶层键集合不等于 5 键）、`<组名>: expected explicit per-item object`（201 行）。上述任一与 189／195 行同属「整份无法解析」时，11 个叶字段全记 `extraction_failed`；`strict_format_valid` 要求严格解析成功、无任何 issue、且 11 个字段全 `valid`（220 行）。`combinations()` 只对 `valid` 字段生效。

**包裹标签与主榜口径（2026-11-25，[DEC-006](../decisions/0006-eval-frame-sampling-and-model-lineup.md) 第 6 条）**：主评测榜单维护本契约的严格单 JSON 约束。对 `GLM-4.1V-9B-Thinking` 等即使开启服务端思考段剥离仍保留 `<answer>...</answer>` 包裹标签的模型，主榜采用**原生格式罚分**（`<answer>...</answer>` 原样落入 `raw_output`，按上表样例 (d) 记 `surrounding_text_or_fence` 且 `strict_format_valid=False`），**不预埋解包分支**；未来若确需做解包对照，须另起独立 `run_id` 并在报告中显式披露。

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

## 4. `无法判断`：同一字面量、同一语义

模式／位置新增 `layered`：`fracture_states`、`denominator`、`excluded_clips`、`excluded_distribution`；准确率、逐类召回／精确率与混淆矩阵只计人工状态为发生断裂／已断裂、该字段人工有效且已尝试的片段。排除片段的人工取值分布不计比例。`uncertain_rate` 与 `over_uncertain_rate` 口径不变，五类全对及其余九字段口径不变。

`无法判断` 在真值侧只有一个语义：**11 个叶字段（3 个单值 + 8 个多选叶项）的人工「无法判断」一律判 `valid`**，与其它合法字面量同权。`truth_cell()`（116 行）只保留三条分支：空串／`None` → `unlabeled`（117–118 行）、非字符串或不在 `allowed(field)` → `invalid`（119–120 行）、其余 → `valid`（121 行）；`five-label-score/2` 起已无 ``"unknown" if value == "无法判断" and field not in SINGLES `` 守卫，真值侧不再产生 `unknown` 状态。

| 环节 | 现行口径（`VERSION = "five-label-score/3"`） | 行号 |
| --- | --- | --- |
| 真值侧（11 个叶字段完全相同） | `无法判断` → `valid`，不是 `unknown`、也不是未标 | `truth_cell` 121 |
| 准确率分母 | 真值 `valid` 且请求已尝试即入分母；模式／位置还要求人工状态为发生断裂或已断裂，排除分布单列不计比例 | 375–381、390–394 |
| 逐类召回 `classes[L].recall` | 每个字段都产出；标签集 = `allowed(field)`（单值用 `SINGLES[field]`，多选用是／否／无法判断），「无法判断」类同样有召回 | 408–412（标签集取自 `allowed()` 112–113） |
| 逐类精确率 `classes[L].precision` | 同上，每个标签（含「无法判断」）都给；分母**不按人工取值筛选** | 408–412 |
| 模型侧：多选叶项答 `无法判断`、人工为「是」或「否」 | 额外计入 `failures_or_uncertain_by_truth` 的 `explicit_uncertain` 单列，并在准确率与召回分母内计为不正确 | 388–389 |
| 模型侧：多选叶项答 `无法判断`、人工同为 `无法判断` | 属答对，**不**计入上述失败／不确定单列 | 388（条件 `h != "无法判断"`） |
| 过度不确定率 `over_uncertain_rate`（仅 8 个多选叶项） | 模型答 `无法判断` 而人工为「是」或「否」数 ÷ 人工为「是」或「否」数；单列，不进任何综合分 | 420–427（分母 421、分子 422、比值 427） |
| 无法判断率 `uncertain_rate` | 每个字段都产出 `{"human": 人工「无法判断」比例, "model": 模型答「无法判断」比例}`，两者分母相同 = 全部已尝试且该字段人工 `valid` 的行数（不按断裂状态分层） | 413–414 |

模型的「无法判断」与人工的「无法判断」是两件事，勿混读：**真值侧没有语义分叉**（上表第一行，11 个字段同一规则）；模型侧仍有一条只对多选叶项生效的失败归类——人工为「是」或「否」时，模型答 `无法判断` 计入 `explicit_uncertain` 单列（388–389 行）。这是**模型侧口径**，不是把真值侧的多选「无法判断」降级为未知；人工同为「无法判断」时它是正确回答，不入该单列。为防止「一律答无法判断」刷准确率，8 个多选叶项另出 `over_uncertain_rate`（420–427 行），与下面保留的顶层指标并存但含义不同。

344 行与 373–374 行**性质不同，不要混读**：344 行是输入审核侧守卫 `cell["label"] not in (None, "", "无法确定", "无法判断")`——证据为 `insufficient`／`unknown` 时不允许断言确定标签，否则抛 `InputError`；它**不把 `无法确定` 变成显式不确定**，该 label 通过本行校验后仍由 `truth_cell`（119–120 行）判 `invalid`。373–374 行才是真正的 `explicit_uncertain` 计数（`pstatus == "valid"` 且 `pred["value"] in ("无法确定", "无法判断")` 时 `pred_counts["explicit_uncertain"] += 1`），覆盖全部 11 个叶字段、计在 `prediction_counts` 里；它的分母是**全部行**（含人工未标的行；未处理与提取失败因 `pstatus != "valid"` 不会命中），与 `uncertain_rate.model`（分母 = 已尝试且该字段人工 `valid` 的片段）不同。两处的旧字面量均为历史兼容残留，不属于本契约现行取值：`无法确定` 在 373 行受 `pstatus == "valid"` 约束、而 `allowed()` 已不含该值，故**现行值域下该分支的 `无法确定` 一侧不可达**，只有 `无法判断` 能命中；`无法识别` 评分器**完全不识别**（`grep -c 无法识别 script/five_label_eval/score.py` = 0），写进任一字段即 `invalid`。两处的旧字面量由本分支提交 `8cf19b4` 引入，术语统一提交 `045536c` 未改动。

多选的顶层指标口径本轮未变，与新加的 `classes` 并存：`TP/FN/FP/TN` 只由人工明确「是」／「否」和模型明确「是」／「否」产生（396–402、423 行）；`recall`（识别比例）= TP ÷ 人工为「是」的已尝试数（425 行）；`precision` = TP ÷ (TP + FP)（425 行）；`false_positive_rate_explicit_only` = FP ÷ (FP + TN)（426 行）。因此同一场景下 `classes.是.precision` 与 `precision` **不相等是正常的**：前者分母含「人工为无法判断、模型报是」的样本，后者只含模型明确报「是」相对人工明确「否」的 FP。报告层同时打印两组值，不得相互替代。

## 5. 代码同步状态（已按 `five-label-score/3` 核对）

`SINGLES` 在 13–17 行；`combinations()` 在 137–144 行，仅保留未断裂与爆炸性断裂／断后脱夹互斥。`field_metrics()` 在 354–428 行，分层资格与排除分布在 360、375–381、390–394 行，`layered` 结构在 416–419 行；`uncertain_rate` 的分母是已尝试且该字段人工有效的片段（375、382–387、413–414 行），不按断裂状态分层。

本节按工作区中 `VERSION = "five-label-score/3"`（12 行）的 `score.py`（557 行）逐行核对，逐项列出现行口径与对应判定行；行号以该版本为准，`score.py` 再次改动后须重新核对。

| 项 | 现行状态（`VERSION = "five-label-score/3"`） | 对评分的影响 |
| --- | --- | --- |
| `SINGLES`（13–17 行）字面量 | 单值三类的不确定值 = `无法判断`；`allowed()`（112–113 行）只返回 `SINGLES[field]` 或 `("是","否","无法判断")`，**不接受**旧值 `无法确定` | 任一叶字段写 `无法确定` 直接判 `invalid`（`truth_cell` 119–120 行的 `value not in allowed(field)` 分支），既不算不确定也不算未标 |
| `truth_cell`（116 行） | 只有三条分支：`unlabeled`（117–118 行）、`invalid`（119–120 行）、`valid`（121 行）。`` "unknown" if value == "无法判断" and field not in SINGLES `` 守卫**已删除** | 11 个叶字段的人工 `无法判断` 一律记 `valid`；模式／位置还须满足断裂状态分层才进 accuracy 与逐类 recall／precision。真值侧 `unknown` 状态**不复存在**，`truth_counts` 只会出现 `valid`／`unlabeled`／`invalid` |
| `field_metrics`（354–428 行） | 每个字段都产出 `classes`（408–412 行）与 `uncertain_rate`（413–414 行）；8 个多选叶项另产出 `over_uncertain_rate`（420–427 行）。保留的顶层 `TP/FN/FP/TN`、`recall`、`precision`、`false_positive_rate_explicit_only` 口径未变（396–402、423–426 行） | `classes` 与顶层 `precision` 并存但含义不同：「人工为无法判断、模型报是」会计入 `classes.是.precision` 的分母，不进 `precision` = TP÷(TP+FP)；`classes` 的标签集取自 `allowed()`（112–113 行），所以单值字段会为 `SINGLES[field]` 的每个字面量（含「无法判断」，不含旧值「无」）各出一行 |
| 388–389 行（失败／不确定单列，已收窄） | `if pstatus != "valid" or (p == "无法判断" and field not in SINGLES and h != "无法判断"):` | 只有「多选叶项、模型答 `无法判断`、人工为是或否」才额外计入失败／不确定；人工同为 `无法判断` 时属答对，不入该单列。单值字段从不因模型 `无法判断` 进入该单列（它们只进 373–374 行的 `pred_counts["explicit_uncertain"]`） |
| 344 行（输入审核侧） | `cell["label"] not in (None, "", "无法确定", "无法判断")`：证据为 `insufficient`／`unknown` 时**不允许断言确定标签**，否则抛 `InputError` | 这是断言禁令，**不是显式不确定计数**；`无法确定` 通过本行校验后仍由 `truth_cell`（119–120 行）判 `invalid` |
| 373–374 行（预测侧） | `if pstatus == "valid" and pred["value"] in ("无法确定", "无法判断"): pred_counts["explicit_uncertain"] += 1` —— 真正的显式不确定计数，覆盖全部 11 个叶字段、计在 `prediction_counts` 里 | 保留 `无法确定` 字面量，但 `allowed()` 已不含该值，**现行值域下该分支不可达**（写 `无法确定` 会先判 `invalid`）；只有 `无法判断` 能命中。分母是**全部行**（含人工未标的行；未处理与提取失败因 `pstatus != "valid"` 不会命中），与 `uncertain_rate.model`（分母 = 已尝试且该字段人工 `valid` 的片段）不同，勿混读 |
| 375–381、390–394 行 | `prediction_status == "unprocessed"` 或真值非 `valid` 即 `continue`，随后 `attempted += 1` | accuracy 分母取真值 `valid` 且已尝试；模式／位置还须状态为发生断裂或已断裂；人工 `无法判断` 因记 `valid` 留在分母内，未处理不经分母 |
| `aggregate`（431–447 行）与 `all_five_correct_supplement`（446 行） | 计算逻辑未改：`eligible`（432–433 行）= 已尝试且 11 个叶字段真值全 `valid`；`joint`（437–438 行）= 其中 11 项全对的片段数 | **派生变更**：因 `truth_cell` 一律判 `valid`，含「多选人工无法判断」的片段现进入本比率分母（434–435 行为该说明的代码注释）；旧口径下这类片段被排除 |

**结论：现行不确定取值只有一个字面量 `无法判断`**（单值三类与 8 个多选叶项相同），且真值侧 11 个叶字段同语义、一律 `valid`。两个历史写法在评分器里的处境不同：`无法确定` 在 344 行（输入审核侧断言禁令）与 373–374 行（预测侧 `explicit_uncertain` 计数）作为历史兼容字面量出现；`无法识别` 评分器**完全不识别**（`grep -c 无法识别 script/five_label_eval/score.py` = 0），写进任一字段即 `invalid`。评分器之外的上游兼优点见 §5.1（数据切分、标注页面、归档生成旧路径、审核工作台显示层），本文不穷举。

### 5.1 需要历史兼容时怎么做

评分器本身不做归一化（见 §1 取值纪律 2）：无别名映射、无全半角修正、无空白修正。历史 CSV／旧批次里的 `无法确定`／`无法识别` 必须**在进入评分前由上游归一**，不能指望评分器接受：

| 环节 | 现行做法 |
| --- | --- |
| 数据切分 `script/data_split/generate.py:46–49` | `ALIASES` 把 `无法确定`（`断裂状态`／`断裂模式`／`断裂位置` 三列）与 `无法识别`（仅 `断裂模式`）归一为 `无法判断`；单值三类的值域见同文件 `FIELDS`（34–42 行，单值三列为 35–37 行），只列 `无法判断` |
| 同上 `:50` | `UNCERTAIN = {"无", "无法确定", "无法判断"}`：分层加权（196、200 行）与「确定值」判定（351 行）把旧词与新词同等当作不确定值 |
| 旧标注页面 `script/annotation/review_annotation.js:94–95` | `legacyUncertainLabels`：三列登记 `无法确定`、`断裂模式` 另加 `无法识别`；`annotationLabel()`（429–431 行）显示时统一为 `无法判断`，原值经 `data-legacy` 选项保留（433–436 行） |
| 现行标注台 `script/roi/label_fields.py:65–70` | `_LEGACY_DISPLAY`：四组历史写法显示为 `无法判断（原值：…）`，不改写已存记录；规则出处见 `docs/label.md` §8「固定组合」中的「已有标注」条（102 行） |
| 归档生成旧路径 `script/subvideo_generation/_legacy/core/generate.py:30` | `UNCERTAIN_INPUTS = (UNCERTAIN, "无法确定")`：旧批次输入判定同时接受 `无法判断` 与 `无法确定`，以保持旧批次可复现 |
| 同文件 `:31`、`:42–44` | `LEGACY_UNCERTAIN = ("无法确定", "无法识别")` + `_unified_uncertain()`：派生输出统一为 `无法判断`，源值原样透传不改写 |
| 审核工作台显示层 `script/subvideo_review/static/app.js:10–15` | `legacyUncertain` 映射 + `unifiedTerm()`：`无法确定`／`无法识别` 只在显示时统一为 `无法判断`，已存记录与源标注字节不改写 |
| 既有历史 CSV 直接喂评分器 | 不归一就落到 `truth_cell` 的 `invalid` 分支（119–120 行），该字段不进 accuracy 分母，只记 `invalid` 计数 |

历史批次若需与旧口径可比，做法是在上游产出一份归一后的输入文件单独保存，而不是修改评分器或放宽 `allowed()`；评分器只认现行字面量。
