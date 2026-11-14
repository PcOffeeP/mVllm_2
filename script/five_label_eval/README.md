# 五类标签本地评分工具

本工具把已锁定的人审标签与模型原回答逐字段比较，生成 `results.json` 和可读的 `report.md`。它只读取调用者显式指定的 JSON / JSONL 文件，不打开视频、不抽帧、不请求模型，也不执行训练、发布或晋级。当前验收只使用合成数据；真实人审、实际模型输入和模型效果均未由本工具验证。

使用项目根目录 `.venv` 的 Python 3.11（`pyproject.toml` 要求 `>=3.11,<3.12`）即可，无额外依赖。正式数据使用和真实测评仍须遵守项目授权。本工具没有默认读取数据目录的路径。

## 先用完全合成的数据运行

在项目根目录执行，两个输出目录都必须尚不存在：

```bash
python -m script.five_label_eval.synthetic_example --output /tmp/five-label-invented
python -m script.five_label_eval.score \
  --manifest /tmp/five-label-invented/manifest.json \
  --reviews /tmp/five-label-invented/reviews.jsonl \
  --predictions /tmp/five-label-invented/predictions.jsonl \
  --input-reviews /tmp/five-label-invented/input_reviews.jsonl \
  --output /tmp/five-label-invented-result
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/private/tmp/five-label-tests script/five_label_eval/tests
```

测试命令带两个参数是为了不污染仓库：`-p no:cacheprovider` 阻止在仓库内生成 `.pytest_cache`，`--basetemp` 把测试临时目录指向 `/private/tmp` 而非仓库下的 `.pytest_tmp*`，两者配合 `PYTHONDONTWRITEBYTECODE=1` 使跑完测试后工作区保持干净。

正常评分返回 0，输出 `results.json` 与 `report.md`。身份冲突、输入 JSON/JSONL 重键或文件错误返回 2，并说明对象；已有输出目录不会被覆盖。模型原回答中的重键或非法标签属于需要评分的预测问题，会记录在逐字段状态中，而不会中止整批。

合成例有 4 个真实类型和 1 个虚拟类型的虚构来源：真实部分 2 次成功、1 次失败、1 个未处理；“伸长”识别比例是 2/3，五类全对补充比例是 2/3。其一成功请求的输入人审认为状态证据不足，给出“无法判断”，因此完整片段状态仍为正确，而实际输入状态计为未正确。两者不混算。这里的 `real` 只是合成 JSON 的分组名称，没有真实媒体。

## 文件身份与固定清单

评分读取以下文件。JSONL 每个非空行必须是一个 JSON 对象。输入身份文件禁止重复键；缺身份或冲突不会凭顺序选择。

| 输入 | 作用 |
| --- | --- |
| `--manifest` | JSON 对象，显式固定候选、媒体摘要、来源和采用的人审修订 |
| `--reviews` | 审核工具导出的 JSONL，可含多次修订和未审占位行 |
| `--predictions` | JSONL，同一运行、模型、Prompt 下每候选至多一个选定请求 |
| `--input-reviews` | 可选 JSONL，人工针对该请求实际收到的画面重新判定证据与答案 |

清单最小结构如下；此处哈希是格式示例，实际值须替换为对应字节的 SHA-256：

```json
{
  "manifest_version": "example/1",
  "samples": [{
    "manifest_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "candidate_id": "candidate-1",
    "clip_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "source_id": "source-1",
    "source_type": "real",
    "review_id": "immutable-review-1"
  }]
}
```

`manifest_sha256` 是生成清单字节摘要，`clip_sha256` 是片段字节摘要，都要求 64 位小写十六进制。评分本身不打开生成清单或媒体复算它们；它负责各输入记录间的身份一致性。CLI 另记录本次实际读取的四份输入文件的字节摘要。

`source_type` 只接受 `real` 或 `virtual`。同一 `source_id` 不能在本批次跨两个来源类型。`candidate_id` 在清单内必须唯一，同名而摘要不同也报错。`review_id` 必须显式填写：非空字符串表示锁定不可变修订；`null` 表示没有选用的人审记录。不会静默使用最新修订。清单和模型记录可以保留额外元数据，例如划分、折号、权重摘要、生成参数、输入帧清单的外部引用；这些额外值会随逐样本结果保存，不自动核验其内容。

审核行需有清单中同名的五个身份字段、`review_id`、`review_status` 和 `labels`。状态为 `confirmed` 才使用其标签；`draft`、`returned`、`question` 都当作未审核真值。审核工具的未审占位行可以使用 `review_status: "unreviewed"`、`review_id: null`、`labels: {}`。非空审核修订重复报错；已锁修订缺失、来源或摘要不同均报错。导出中的其他修订不被自动选中。

## 从审核导出生成清单草稿

候选较多时，可由 `build_manifest` 复制身份，无需逐条手写摘要。准备审核工作台的**最新决定导出** JSONL，以及用户明确选择的候选 ID 文件。ID 文件必须是非空 JSON 字符串数组，例如 `["candidate-7", "candidate-2"]`；工具保留该顺序，只复制这两个对象，不扩选其他候选。

```bash
python -m script.five_label_eval.build_manifest \
  --reviews /path/to/current-decisions.jsonl \
  --candidate-ids /path/to/explicit-candidate-ids.json \
  --manifest-version user-chosen-version \
  --output /path/to/new-manifest-draft.json
```

路径和版本值须替换为实际选定的输入与新输出文件。父目录须已存在；输出使用独占创建，已有同名文件时报错，不覆盖。成功返回 0；重复 ID、缺失对象、非法摘要、缺修订身份、非法状态或文件错误返回 2，不生成草稿。源 JSONL 的重复候选即使修订号不同也拒绝：此工具不接收历史全量导出，不根据时间或行顺序挑选修订。JSON 重复键同样拒绝。工具信任调用者提供的“最新决定导出”，不会自行查询是否有更新的决定。

草稿逐 ID 复制 `manifest_sha256`、`candidate_id`、`clip_sha256`、`source_id`、`source_type`、准确的 `review_id` 和 `review_status`；不复制或编造标签。输出记录输入导出文件与 ID 文件的字节 SHA-256，并有 `draft_status: "identity_snapshot_not_frozen"`、`review_status_counts` 和 `not_confirmed`。所有内容均只来自显式输入，不打开媒体，不访问模型或发布入口。

与评分器一致，confirmed、unreviewed、draft、returned、question 均可保留在草稿中；未审项准确保留 null review_id，草稿、退回与疑问项保留各自实际修订。命令逐项打印 `NOT CONFIRMED` 提示，文件内也列明状态。**生成成功只表示身份快照写出，不表示全部已审核。**没有额外预览／正式模式，这个工具的所有输出都是草稿。

评分器可以直接消费该 JSON，并从 `--reviews` 中读取锁定修订；仍然只有 confirmed 标签进入真值。草稿不是正式测评集：正式冻结、test 或虚拟候选选择、数据准入及实际使用仍须对应授权。即使全部选中项 confirmed，工具也不自动作出这些决定。

## 五类标签和模型记录

人工 `labels` 与模型 `raw_output` 中的目标对象使用相同的五个中文顶层字段：

```json
{
  "断裂状态": "发生断裂",
  "断裂模式": "韧性断裂",
  "断裂位置": "标距内",
  "异常情况": {"未夹紧": "否", "视频异常": "否", "爆炸性断裂": "否"},
  "断裂现象": {"伸长": "是", "颈缩": "是", "开裂": "否", "界面分离": "否", "断后脱夹": "否"}
}
```

单选取值依据[本轮标签说明](../../docs/label.md)：状态为未断裂、发生断裂、已断裂、无法判断；模式为脆性断裂、韧性断裂、半脆半韧断裂、无法判断、无；位置为标距内、标距外非根部、夹持根部、无法判断、无。多选每一项都必须显式为“是”“否”或“无法判断”；空数组不是正常负例。工具不自动转换旧名称、英文键或旧四字段。

人工空字符串、null、缺项视为未标；非法值单列 invalid，不拿来构造正负例。未标仅影响对应字段，其余有效字段照常比较。**多选叶项的“无法判断”自评分器版本 `five-label-score/2` 起是合法可比较类别**（与单选一致，不再记未知）：真值侧记有效，进该字段准确率分母，并作为“无法判断”这一类参与逐类召回与精确率。单选人工“无法判断”和合法固定值“无”同样是有效可比较标签。

每条模型记录的最小结构：

```json
{
  "candidate_id": "candidate-1",
  "clip_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "run_id": "run-1",
  "model_id": "weights-identity-1",
  "prompt_id": "prompt-identity-1",
  "input_id": "actual-input-identity-1",
  "request_id": "request-1",
  "status": "success",
  "raw_output": "{\"断裂状态\":\"发生断裂\"}",
  "input_review_id": null
}
```

以上原回答有意只写一个字段，其余会标为 missing。`raw_output` 始终保存模型原文，失败无原回答时填 null。`status` 只接受 `success`、`request_failed`、`timeout`、`unprocessed`。未出现的预测记录等于未处理。一个评分批次只接受相同 `run_id`、`model_id`、`prompt_id`，每候选一个请求；重试或模型对照需显式选择并分别评分，不自动挑选答案。不同模型输入可以各有 `input_id`，但实际输入身份必须可追溯，不能只用随意同名替代。

提取器先解析整段 JSON；失败后只允许提取唯一的完整 JSON 对象（可以有代码围栏或说明文字），该情况不算严格格式合法。多个并列对象、无法解析或非对象为 extraction_failed。重键不选择首值或尾值：受影响字段标 invalid，其他唯一字段仍可评分。缺字段、非法值、提取失败与模型明确不确定分开记录。

`strict_format_valid` 只检查恰好五个顶层字段、完整多选子键、类型、枚举、无重键和无外围文字，不检查回答是否与人审相同。跨字段组合检查独立统计：未断裂或未夹紧要求模式和位置为“无”；未断裂与爆炸性断裂、断后脱夹冲突。组合冲突保留原文并按实际各字段评分，不自动修改标签，也不自动批准使用。人工标签中的组合冲突同样保留并显示，须由人审流程处理。

## 独立记录模型实际收到的画面

完整片段答案与实际输入答案是两套真值。没有输入人审时，工具给出 unreviewed 和不可计算，不从完整片段或模型回答补答案。

每条输入人审记录需有 `candidate_id`、`clip_sha256`、`run_id`、`model_id`、`prompt_id`、`input_id`、`request_id`，与具体预测完全一致；另有不可变 `input_review_id`、`review_status`、`fields`。预测行的 `input_review_id` 必须显式锁定该修订，null 或省略表示未选用；存在未被选用的历史修订也不会自动采用。输入人审状态取值与普通非空修订相同，仅 confirmed 用作真值。

`fields` 沿用五类层级，每个叶字段改为包含 `evidence` 与 `label` 的对象。例如：

```json
{
  "断裂状态": {"evidence": "insufficient", "label": "无法判断"},
  "断裂模式": {"evidence": "unknown", "label": null},
  "断裂现象": {
    "伸长": {"evidence": "sufficient", "label": "是"},
    "颈缩": {"evidence": "insufficient", "label": "无法判断"}
  }
}
```

`evidence` 必须为 sufficient（充分）、insufficient（不足）或 unknown（无法确认）；未审核字段自动列 unreviewed。证据不足或无法确认时禁止给出确定的“是”“否”或确定单选标签，可用 null、空白或该字段的不确定标签；非法标签会单列而不计分。证据充分也不会补造任何缺失答案。

实际输入结果按每字段证据充分／不足／无法确认／未审核分别展示。单选输入标签“无法判断”仍能独立比较；多选输入侧的“无法判断”自 `five-label-score/2` 起同样是可比较类别（与单选同语义），不再按“没有确定正负真值”处理。证据不足或无法确认时仍禁止断言确定的“是”“否”或确定单选标签，该断言禁令未变。无论输入证据是否不足，完整片段端到端分母保持不变。这里的输入人审只能证明人可检查的画面记录，不能证明已重建模型内部全部视觉编码。

## 分母和结果结构

每个比例都输出 numerator、denominator、value、reason。分母为零时 value 为 null、reason 为“证据不足／无法计算”。总体正确率、召回、精确率、误报率和五类全对的以下口径均已由用户确认；其中精确率、误报率与五类全对作为补充统计，不设通过阈值，不接自动晋级。逐类召回／精确率（`classes`）、`over_uncertain_rate`、`uncertain_rate` 是随本轮“多选人工无法判断改为合法可比较类别”一并落地的派生指标，沿用同一分母口径，同样不设阈值、不接自动晋级。

| 统计 | 实现口径 |
| --- | --- |
| 按字段正确率（准确率） | 与人工相同数 / 该字段人工标签有效（单选为 `SINGLES` 字面量、多选为是／否／无法判断）且已尝试数。单值与多选同一口径；人工“无法判断”在分母内 |
| 逐类召回（`classes[L].recall`，每个字段都产出） | 人工为 L 且预测为 L 数 / 人工为 L 且已尝试数。单值标签集 = `SINGLES[field]`（含“无法判断”“无”），多选为是 / 否 / 无法判断 |
| 逐类精确率（`classes[L].precision`，每个字段都产出） | 人工为 L 且预测为 L 数 / 预测明确为 L 且人工真值 valid 且已尝试数。每个字段、每个标签都给，含“无法判断”。分母**不按人工取值筛选**，所以“人工=无法判断、模型=是”会计入“是”类精确率的分母 |
| 多选识别比例（顶层 `recall`） | TP / 人工为是且已尝试数 |
| 多选精确率（顶层 `precision`，已确认补充） | TP/(TP+FP)。与 `classes.是.precision` 口径不同，两者可以不等，勿混读 |
| 多选误报率（已确认补充） | FP/(FP+TN)，仅覆盖人工为否且模型明确答是／否的样本 |
| 过度不确定率（`over_uncertain_rate`，8 个多选叶项） | 模型答“无法判断”而人工为是或否数 / 人工为是或否的已尝试数。防“滥答无法判断”刷分的制衡指标，单列，不进任何综合分，不改其它指标分母 |
| 无法判断率（`uncertain_rate`，每个字段都产出） | `{"human": 人工真值为“无法判断”比例, "model": 模型答“无法判断”比例}`，两者分母相同 = 已尝试且真值 valid 的行数 |
| 五类全对（已确认补充） | 所有叶字段全对数 / 全部人工叶字段可比较且已尝试片段数。含多选人工“无法判断”的片段自 `five-label-score/2` 起进入分母（派生变更，见下） |

`prediction_counts["explicit_uncertain"]` 与 `uncertain_rate.model` 分母不同，勿混读：前者计在“预测字段状态”里，覆盖全部行（人工未标的行也算；未处理与提取失败不计）；后者只取已尝试且真值 valid 的行。

11 个叶字段的人工“无法判断”都是有效可比较类别：模型同样回答“无法判断”可计该字段正确，计入该类别召回与精确率；其余项目也正确时可以计五类全对。五类全对的分母只排除任一人工字段未标／无效的片段，**不再排除含多选人工“无法判断”的片段**——这是随上述真值侧改动引出的派生变更（计算逻辑本身未改）。多选模型“无法判断”不进入“是／否”的顶层精确率与误报率分母（口径未变），仍按对应有效人工真值计入正确率和识别比例分母，并单列；为防止“一律答无法判断”刷分，另出 `over_uncertain_rate` 作为制衡指标。

TP、FN、FP、TN 只由人工明确“是／否”和模型明确“是／否”产生。人工正例上的请求失败、超时、缺字段、无效字段、提取失败及模型“无法判断”仍在识别比例分母，单列原因，不能伪装成明确 FN。人工负例中的失败与不确定也单列，不进入上述显式负例误报率分母。未处理不计错误。人工未标不进入该字段真值分母（真值侧已无“未知”状态：11 个叶字段的人工“无法判断”记 valid，进分母），模型在这些对象上的回答保存在 `prediction_by_truth`，不补人审答案。

`results.json` 的 `groups.real` 与 `groups.virtual` 各自有完整片段 `full_clip`、实际输入 `actual_input` 和 `by_source`。前两者均包含逐叶字段结果（准确率、`classes` 逐类召回／精确率、`uncertain_rate`、多选 `over_uncertain_rate`、顶层 TP/FN/FP/TN 与识别比例／精确率／误报率）、取值／未标／无效数量、来源数、混淆、预测字段状态和失败；`by_source` 与 `actual_input.evidence_by_field` 共用同一 `field_metrics()`，因此也带上述键。`actual_input.evidence_by_field` 按证据状态再分组。`samples` 保存锁定身份、原回答与 JSONL 行引用、逐项人审、提取状态、输入证据和冲突；CLI 的 `input_files` 保存所读取文件摘要。`report.md` 逐字段打印准确率、`classes` 各标签的召回／精确率、`uncertain_rate`、多选 `over_uncertain_rate` 与顶层指标，并展示逐片段结果；JSON 保留完整可追溯内容。**已知展示层限制：**`report.md` 的“逐来源”与“输入证据”子区块仍只打印准确率（多选另加识别比例），不打印 `classes`／`uncertain_rate`／`over_uncertain_rate`；完整逐类指标见 `results.json`。来源层只展示其自身片段统计，不合成加权总分。

## 验证和边界

合成测试使用独立手算期望，覆盖 TP/FN/FP/TN、失败仍在分母、人工“无法判断”作为多选合法类别、未标与空白、未处理、无正例/无负例、部分字段缺失、重键、空数组、组合冲突、多修订锁定、同名不同摘要、来源隔离和实际输入证据不足。测试命令见首节。可以将 `score(manifest, reviews, predictions, input_reviews=())` 用作纯 Python 接口；它不读文件，CLI 负责严格 JSON/JSONL 解码和文件摘要。

工具不核实媒体字节、实际抽帧是否等于 input_id、人审内容、来源是否独立、训练暴露或模型权重是否真实对应 model_id。运行者需先确保这些身份指向可复查记录；合成通过不能证明真实数据、运行环境或模型效果。当前不评价时间标签，没有旧阈值、加权汇总、晋级和发布接入。

**失效条件：**五类标签定义、输入证据复核规则、身份绑定方式或统计分母改变后，必须更新评分版本、此说明和对应行为测试，再用于新的评分批次。本次“多选叶项人工『无法判断』改为合法可比较类别”的口径变更已将 `VERSION` 升为 `five-label-score/2`；下一次同类改动同样须先升版本号再改文档。
