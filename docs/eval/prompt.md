# prompt：正文位置 · 约束项与评分器行为 · 版本与冻结

**失效条件：** v1 正文文件被改动或换版本号；`prompt_id` 形态改变；术语统一分支合并后 v1 正文未同步；`script/five_label_eval/score.py` 的 `_extract()`／`allowed()`／`truth_cell()` 判定行改变；冻结入口 `versioning/prompts.py` 落地本仓库或改变产物形态。以上任一发生，本文的约束项对照表与版本策略都须重新核对。

## 1. v1 正文的位置

| 项 | 值 |
| --- | --- |
| 路径 | `script/five_label_eval/prompts/five_label_v1.txt` |
| 本分支落地状态 | **未落地**。本分支 `feat/eval-input-contract` 无该文件；正文只存在于分支 `feat/eval-fake-slice`（提交 `89b3624`） |
| 规模 | 19 行 |
| 现行版本号 | v1 |
| 身份 | `prompt_id = prompt@sha256:<文件字节的 sha256>` |

正文要点（概括，不复制原文）：禁止依据文件名／路径／元数据／时长／文字线索猜答案；逐项显式回答、不得省略；不得用空列表表示「全部为否」；证据不足用该字段规定的不确定值；给出三单值字段的字面量清单；两个多选组逐项 `是`／`否`／`无法判断`；给出组合规则（未断裂或未夹紧时 `断裂模式`／`断裂位置` 须为 `无`；未断裂时 `爆炸性断裂`、`断后脱夹` 不得为 `是`）；只输出一个 JSON 对象，禁止解释、Markdown 围栏与前缀后缀文字。

## 2. 约束项与评分器行为

| 模板必须包含的约束项 | 违反后的评分器行为 | 行号 |
| --- | --- | --- |
| 只输出一个 JSON 对象，禁止前后缀文字与 Markdown 围栏 | 有围栏或前后缀仍可提取，但记 issue `surrounding_text_or_fence` 并令 `strict_format_valid=False`；解析出多余或零个对象则全部字段 `extraction_failed` | 191（issue）、220（strict）、189（`not exactly one extractable JSON object`） |
| 逐项显式给出 3 个单值与 8 个叶项，不得省略 | 单值缺键、叶项缺键记 `missing`；整组不是对象或叶项集合不全另记 issue | 211–212、213–214（`missing`）、201（`<组名>: expected explicit per-item object`）、205–218（逐字段判定） |
| 不得用空列表表示「全部为否」 | 父键为非对象（含 `[]`）时该组每个叶项记 `invalid`，注释明写 `[] never means all negative` | 209–210 |
| 取值必须逐字一致，不得自造、改写、翻译 | 非字符串或不在允许值内记 `invalid` | `allowed()` 112–113；`_extract()` 215–216 |
| 单值字段的不确定值写 `无法判断` | 单值字段的 `无法判断` 是合法类别 | `allowed()` 112–113；`truth_cell` 121 |
| 多选叶项只用 `是`／`否`／`无法判断` | 写 `无` 或任何其他非允许值记 `invalid` | `allowed()` 113 |
| 组合规则（未断裂／未夹紧 → `断裂模式`／`断裂位置` = `无`） | 不判 `invalid`；`combinations()` 记冲突，聚合键 `prediction_combination_conflicts` 每行 +1 | 137（`combinations()`）、423（聚合） |
| 顶层恰好 5 个键 | 顶层键集合不等时记 issue `top_level_keys_mismatch`，`strict_format_valid=False` | 198、220 |

`strict_format_valid` 的完整条件：严格解析成功、无任何 issue、11 个叶字段全 `valid`（220 行）。因此「格式分」与「内容分」分开看，围栏与缺项不影响已有字段的正确性计分。

## 3. 版本策略

- **改一个字即新版本号**：不改字面量、只改措辞也换版本，因为身份按文件字节计算，任何字节变化都会改变 `prompt_id`。
- **身份形态**：`prompt@sha256:<摘要>`，前缀常量 `PROMPT_ID_PREFIX = "prompt@sha256:"`，函数 `prompt_id_for_bytes`（见 `feat/eval-fake-slice:script/five_label_eval/prompt_id.py`）。该分支的 `load_prompt` 返回「原文（不 strip）+ 身份」，即送模型的文本与算摘要的字节是同一份。
- **版本号与摘要双记**：批次记录里既写人可读版本 `v1`，也写 `prompt_id`；`score.py` 只校验一批内 `prompt_id` 唯一（288–291 行），不解析版本语义。
- **不允许同名改动**：已用于批次的版本号不得再改内容，只能新增 `v2` 并留下两版正文文件。

## 4. 冻结机制（训练机侧复用项）

| 项 | 内容 |
| --- | --- |
| 复用模块 | `versioning/prompts.py` 的 `load_prompt`（242 行）、`freeze_prompt`（275 行）、`verify_frozen_prompt`（315 行） |
| 落地状态 | **只存在于旧项目 `mVllm_2`（只读参考）**，本仓库与训练机侧尚未落地；本机不可用 |
| 冻结产物形态 | 版本号 + 内容摘要（文件字节 sha256）+ 冻结校验入口（按版本号取回并重算摘要比对） |
| 校验方式 | 重算正文文件字节摘要，与冻结产物中记录的摘要逐字比对；不一致即拒绝出批次，不静默降级 |
| 与 `prompt_id` 的关系 | 冻结产物中的摘要即 `prompt@sha256:` 的摘要部分，两者必须是同一算法、同一字节输入 |

本机只能做到「文本 + 摘要」两件事（`prompt_id.py` 侧），冻结登记与校验须在训练机侧接入后才有产物。在本机声称「已冻结」不成立。

## 5. 跨分支待办

**术语同步（第一条实例）**：v1 正文当前仍把单值不确定值写成旧字面量 `无法确定`（该文本位于 `feat/eval-fake-slice`，属历史文本，**非本契约现行取值**）。术语统一分支合并后，v1 正文须把该字面量同步改为 `无法判断`，并按上一节改一个字即升版本号（改为 v2）；同时更新 `prompt@sha256:` 身份与所有引用 v1 的评测记录说明。

## 6. 不在 v1 范围、列为待决

| 项 | 状态 |
| --- | --- |
| 诊断题（证据选择／顺序题） | **不在 v1 范围**，列为待决；v1 只做五类标签判读 |
| 抽帧策略：选哪几帧、是否强制含锚点帧、是否覆盖断裂瞬间 | 待决，属 `docs/eval/input-record.md` 与 `docs/TODO.md`；**送模型的帧数本身不是可调项**（processor 硬性要求 8，见 `docs/eval/inference-entry.md` §7） |
| 空画面／无画面对照用的 prompt | 待决；若实现须另建版本号，不得复用 v1 身份 |
