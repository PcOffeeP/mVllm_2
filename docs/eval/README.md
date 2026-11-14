# 评测输入契约 · 专题文档集

**失效条件：** 任一专题文件改名或与其他专题合并；`script/five_label_eval/score.py` 的字段、取值或判定行改变（本文按 `VERSION = "five-label-score/2"` 核对）；后续若再次变更取值字面量而未复核下方的同步清单；`script/subvideo_review/server.py`、`script/data_split/generate.py`、`data/annotation-table-full.csv` 或 `docs/facts.yaml` 的对应位置改变。以上任一发生，本页的范围界定、阅读顺序与同步清单都须重新核对。

## 范围界定

| 本集负责 | 不负责（去别处） |
| --- | --- |
| 输出契约（11 叶字段／5 顶层键／边界样例） | 评分口径：分母定义、精确率口径 → `docs/design-test.md` |
| prompt 正文要求、版本与冻结 | 标签定义与语义 → `docs/label.md` |
| 推理入口 CLI、身份字段、三态 | 评分器实现细节 → `script/five_label_eval/score.py` |
| 输入记录结构、四层画面谱系、帧索引 | 清单生成与审核工作台 → `docs/subvideo-review-workflow.md` |
| 评测子集的分档、抽样与冻结 | 实施顺序与批次管理 → `docs/TODO.md` |

## 阅读顺序

`本页 → output-contract → prompt → inference-entry → input-record → eval-subset`

先读 `output-contract` 是因为下游一切（prompt 约束、入口身份字段、输入记录）都以它的字段名和取值字面量为准。**`input-record` 是核心**：它决定「模型真正看到的是哪几帧、这几帧来自哪一层媒体」，一旦帧号或命名口径错了，输出格式再规范也无法回溯，而其余五份文件都只约束「格式与身份」，只有它约束「内容来源」。

## 改契约时要同步哪些地方

| 改动类型 | 必须同步的对象 | 校验方式 |
| --- | --- | --- |
| 字段名、取值字面量、判定逻辑 | `script/five_label_eval/score.py`：`VERSION` 12（现为 `five-label-score/2`）、`SINGLES` 13–17、`MULTIS` 18–19、`FIELDS` 20、`allowed()` 112–113、`truth_cell()` 116–121（11 个叶字段的「无法判断」现为合法可比较类别，真值侧一律 `valid`）、`_extract()` 162–222、`field_metrics()` 359–414（新增 `classes` 398–402、`uncertain_rate` 403–404、多选 `over_uncertain_rate` 406–413；顶层 `TP/FN/FP/TN`、`recall`、`precision`、`false_positive_rate_explicit_only` 口径未变，409–412） | `python -m pytest script/five_label_eval/tests`，并核对 `VERSION` 已升号 |
| prompt 文本 | `script/five_label_eval/prompts/five_label_v1.txt` 正文，以及 `prompt_id`（文件字节摘要随之改变）；改一个字即新版本号（当前 `v1` 是已知例外：`29a7688` 当日订正后的字节与任何批次都无引用关系，升 v2 待用户确认，见 `docs/eval/prompt.md` §5） | 重算 `prompt@sha256:` 并对比批次记录的 `prompt_id` |
| 审核工作台取值 | `script/subvideo_review/server.py:28–34` 的 `OPTIONS`（单值三类 + 两组多选叶项） | 工作台 `validate_labels` 拒绝越界值；改后重跑 `script/subvideo_review/tests` |
| split 管线归一别名 | `script/data_split/generate.py` 的 `FIELDS` 34–42（单值三列 35–37）值域、`ALIASES` 46–49（把单值字段的历史字面量 `无法确定` 与 `无法识别` 归一为 `无法判断`；`无法识别` 仅见于 `断裂模式`） | 改后重跑 `script/data_split/tests`；别名与评分器取值不一致会让输出静默判 `invalid` |
| CSV 值域 | `data/annotation-table-full.csv` 的 `断裂状态`／`断裂模式`／`断裂位置`／`异常_*`／`现象_*` 列 | 逐列取值与 `allowed()` 比对，越界值单独列出 |
| 事实登记 | `docs/facts.yaml` 中与本契约相关的条目（如 DF-027、DF-028 的源→ROI 同序与重放结论） | YAML 解析通过、条目 id 唯一、`state` 与实际证据一致（本仓库当前无专门校验脚本，至少做这两项检查）；`state` 变更时同步本集引用的结论 |

该清单来自术语统一那次事故的经验：单值字段与多选叶项的不确定值曾写成互不相同的两个字面量，任何一处漏改都不会报错——模型输出会被 `allowed()`（112–113 行）判 `invalid`，指标照常产出但数值无声失真，直到逐字段比对才发现。术语已统一，且自 `five-label-score/2` 起 11 个叶字段的「无法判断」在真值侧同语义（一律记 `valid`、同进准确率分母与逐类召回／精确率）：现行不确定值只有 `无法判断` 一个字面量，单值与多选的差别只落在**模型侧**——多选答「无法判断」而人工为「是」或「否」时单列失败／不确定，人工同为「无法判断」时计正确。

## 各文件失效条件

| 文件 | 失效条件 |
| --- | --- |
| `output-contract.md` | 评分器常量或判定行改变（现按 `VERSION = "five-label-score/2"` 核对）；后续若再次变更取值字面量而未同步 `output-contract` 的代码同步状态 |
| `prompt.md` | v1 正文改动；`prompt_id` 形态或冻结入口改变；后续若再次变更取值字面量而未同步 v1 正文。**现时已同步**：v1 正文已合入本分支，其单值三类不确定值为 `无法判断`，`prompt_id` 已按当前字节重算并记录于 `docs/eval/prompt.md` §5 |
| `inference-entry.md` | CLI 参数增删；`http` backend 落地；身份字段口径或三态触发条件改变 |
| `input-record.md` | 清单新增／移除 `frame_mapping.anchors`、`frame_preserving_replay`；媒体目录结构改变；同序性证据被推翻 |
| `eval-subset.md` | `max_pixels` 或预处理策略改变；画幅分布改变；分档规则改变 |
| 本页 | 任一专题文件改名或合并；同步清单所列对象改变 |
