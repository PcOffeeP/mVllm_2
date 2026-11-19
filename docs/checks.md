# 检查机制台账

这份台账记录全项目 134 处检查的位置、触发方式与当前状态，给负责人一个单一视图。全项目的校验散在代码、测试和数据里，没有统一台账，已经造成两类后果：文档证据的行号漂移了没人发现，审计记录放进了错误的批次也没人发现。这份台账是 2026-11-18 的现状快照，不是实施计划。

## 1. 这张表怎么读

每个检查用下面四种颜色标记：

- **绿**：有人在跑，现在通过。
- **黄**：检查存在，但覆盖窄、条件不满足时会静默跳过，或只是提醒不拦人。
- **红**：现在实测不一致，需要处理。
- **孤儿**：检查代码或规则还在，但没有任何地方会触发它；或者压根没有程序去做这件事。

本台账的「绿」指**本次核验有人实际跑过并通过**，不代表有人在定期跑；定期触发缺失的问题见第 4 节第 6 条。状态是 2026-11-18 的快照，过期条件见第 7 节。

## 2. 六层总览

| 层 | 这一层管什么 | 检查项数量 | 绿·黄·红·孤儿 | 一句话结论 |
|---|---|---|---|---|
| 源数据（标注表、划分、裁剪区域 ROI） | 原始标注、数据划分、画面裁剪这些输入对不对 | 20 | 18·2·0·0 | 能跑、能过，但两处记录与当前文件对不上（内容等价，未列入第 4 节）。 |
| 子视频生成（把源视频切成候选片段那一步） | 片段怎么切、规则怎么派、批次怎么续跑 | 32 | 0·29·2·1 | 唯一的 2 个红项在这里；整套检查要单独跑，本次没跑完。 |
| 人工审核（你看片打标签的界面） | 审核服务、ROI 决策、标注审核 | 16 | 15·1·0·0 | 跑得过；但审核页的「标签组合待复核」筛选现在用不了。 |
| 模型评价（评分器与模型输入记录） | 评分器、帧来源链、清单转换、推理入口 | 17 | 15·0·0·2 | 在跑的这部分是好的；模型交付校验已删。 |
| 文档与事实（`docs/facts.yaml` 那套「哪句话有出处」的记录） | 文档里的证据还对不对得上原文 | 6 | 2·1·2·1 | 校验程序已移植回 `script/checks/facts.py`，实测 0 条位置漂移、3 条原文消失；标题/锚点校验仍缺。 |
| 仓库卫生（哪些文件该进版本库、哪些不该） | 仓库布局、旧路径、Git 忽略规则 | 43 | 0·39·0·4 | 39 个检查被静默跳过，从未真正跑过。 |

六层合计 20+32+16+17+6+43=134；绿 50、黄 72、红 4、孤儿 8。

## 3. 主表：只列「需要你知道」的检查

下面 24 行是项目负责人现在必须知道的检查。为避免术语拖住阅读，先说明四个词：文件指纹（文件内容算出来的一串字符，内容变一个字节就会变）、批次身份（这批产物是由哪几个输入、哪套规则生成的）、契约（人和程序之间约定好的规则）、校验器（检查这些规则有没有被遵守的程序）。本文只使用这四个核心术语。

| 编号 | 它在管什么（人话，一句话） | 检查的输入 → 输出的判断 | 谁在跑 | 状态 | 怎么自己确认它现在是这个状态 |
|---|---|---|---|---|---|
| L2-30 | 审计记录里的清单摘要与当前清单是否一致 | `data/sub_video/audit.json:3` 的清单摘要 → 必须与当前清单摘要一致 | 没人跑；该记录现在只被审阅服务读取 | 红 | 打开 `data/sub_video/audit.json` 看第 3 行，与 `data/sub_video/manifest.json` 当前内容算出的摘要比对 |
| L2-31 | 审计记录里的运行摘要是否属于当前批次 | `data/sub_video/audit.json:12` 的运行摘要 → 必须是当前批次 | 没人跑 | 红 | 打开 `data/sub_video/audit.json` 看第 12 行，再打开 `data/sub_video/superseded-20261113/audit.json` 看同一字段，两者相同即说明是上一批次 |
| L2-32 | 有没有程序负责生成和维护审计文件 | `script/subvideo_generation/generate.py` 的写文件动作 → 应当生成或维护 `audit.json` | 没有任何程序 | 孤儿 | 在 `script/subvideo_generation/generate.py` 里搜索 `audit.json`，看不到写文件动作；只有 `script/subvideo_review/server.py:154` 读取它 |
| L4-16 | 模型/服务交付时的批次身份对不对 | 交付产物与约定规则 → 身份一致才放行 | 没有；脚本已删除 | 孤儿 | 仓库里找不到 `scripts/serve_validate_delivery.py` |
| L4-17 | 模型/服务有没有越界输出 | 服务响应与允许范围 → 不越界 | 没有；脚本已删除 | 孤儿 | 仓库里找不到 `scripts/serve_validate_no_oob.py` |
| L5-01 | 文档证据的行号是否还指得到原文 | `docs/facts.yaml` 的 ref 证据 → 行号与原文对得上 | `.venv/bin/python -m script.checks.facts --json`（2026-11-19 实测） | 红 | 运行该 `--json` 命令，看 `totals.drift`（实测 23） |
| L5-02 | 文档证据的 expect 断言是否还成立 | `docs/facts.yaml` 的 expect 字段 → 断言内容仍与原文一致 | `.venv/bin/python -m script.checks.facts --json`（2026-11-19 实测） | 红 | 运行该 `--json` 命令，看 `totals.gone`（实测 3，表示 expect 在全文都找不到） |
| L5-03 | 文档里写的仓库路径是否真实存在 | Markdown 中的仓库内路径 → 路径存在 | `.venv/bin/python -m script.checks.facts --check-doc-paths` | 黄 | 运行该命令，会看到 41 个受跟踪 Markdown「无法读取」后退出 1（sparse-checkout 未检出，尚给不出路径判定） |
| L5-04 | 文档记录格式的状态取值是否合法 | `docs/facts.yaml` 的状态字段 → 取值在允许列表内 | `.venv/bin/python -m script.checks.facts --json`（2026-11-19 实测） | 绿 | 运行该 `--json` 命令，看 `structure_errors`：49 条 state 全部合法，DF-044 的 `affects` 已修正，`structure_errors` 实测为 0 |
| L5-05 | 原 1132 行文档事实校验程序本身 | `docs/facts.yaml` 与仓库文件 → 证据、路径检查结果 | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q script/checks/tests`（73 项） | 绿 | 运行该 pytest 命令看 `73 passed`，再跑 `.venv/bin/python -m script.checks.facts` 看五类汇总 |
| L5-06 | 文档内部标题与互相引用是否还连得上 | `docs/facts.yaml` 的标题与锚点引用 → 引用目标存在 | 没有；移植版只校验证据行与文档路径，不含标题/锚点校验 | 孤儿 | 在 `script/checks/facts.py` 里搜索 `anchor`／标题解析，没有对应逻辑 |
| L6-40 | 仓库有没有持续集成 | 仓库根目录 → 存在 CI 配置 | 没有 | 孤儿 | 在项目根目录执行 `ls -la .github`，提示没有该目录 |
| L6-41 | 提交前有没有自动检查钩子 | 仓库根目录 → 存在提交前钩子配置 | 没有 | 孤儿 | 在项目根目录执行 `ls -la .pre-commit-config.yaml`，提示没有该文件 |
| L6-42 | Git 钩子目录里有没有真正生效的钩子 | Git 钩子目录 → 存在非样例钩子 | 没有 | 孤儿 | 执行 `ls $(git rev-parse --git-path hooks)`，只看到 `*.sample` 文件 |
| L6-43 | 已删除校验器的回归测试是否还留在索引里 | Git 索引与磁盘文件 → 索引中的测试文件在磁盘上存在 | 没有；磁盘上没有，跑不到 | 孤儿 | `tests/test_verify_design_facts.py`、`tests/test_serve_validate_delivery.py`、`tests/test_environment_deployment.py` 已从索引移除，磁盘上也没有 |
| L1-03 | 标注表的非法取值与标签组合 | 标注表记录 → 缺少 ID、重复 ID、空标签、非法枚举、不合法标签组合都被拒绝 | `script/data_split/tests/test_generate.py:132` | 绿 | 运行 `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests`，该测试通过 |
| L1-13 | ROI 输出的画面尺寸、时长、方向 | ROI 输出媒体 → 几何、时间、方向符合要求才验收 | `script/roi/tests/test_core.py:328` | 绿 | 运行 `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests`，该测试通过 |
| L3-16 | 审核与评分的集成行为 | 集成测试集 → 82 项行为检查通过 | 默认 pytest；本次实测 640 项通过，其中集成 82 项 | 绿 | 运行默认 `pytest`，看到集成测试通过 |
| L4-01 | 评分器检查身份字段和文件指纹格式 | 评分文件 → 身份字段存在、文件指纹格式正确 | `script/five_label_eval/score.py:91` | 绿 | 运行默认 `pytest` 中评价相关测试，或打开 `script/five_label_eval/score.py:91` 看校验逻辑 |
| L1-01…L1-02 | 标注表与划分清单的历史记录是否还对应得上当前文件 | 记录中的文件指纹与当前文件 → 指纹一致 | 测试会跑，但记录本身在漂移 | 黄 | 打开 `data/split-inputs/source-groups-20261107.json:6` 与 `data/splits/three-fold/manifest.json:256`，比对记录中的文件指纹和当前文件 |
| L2-01…L2-29 | 子视频生成全阶段的契约与身份校验 | 源视频、标注、规则 → 片段、覆盖、续跑、审计都符合规则 | 须单独运行该目录测试 | 黄 | 打开 `pyproject.toml` 第 19 行，看默认测试范围里没有 `script/subvideo_generation/tests` |
| L3-08 | 审核页「标签组合待复核」筛选 | `audit.json` 的清单摘要与当前清单 → 一致时筛选可用 | 审核页加载时触发，但现在不一致导致筛选灰掉 | 黄 | 打开审核页，看「标签组合待复核」筛选是否不可用；或打开 `data/sub_video/audit.json:3` 与当前清单摘要比对 |
| L3-15 | 审核服务与标注审核的测试 | 对应测试目录 → 45 + 10 项检查通过 | 默认 pytest；审核服务和标注审核测试均通过 | 绿 | 运行默认 `pytest`，收集审核服务 45 项、标注审核 10 项，全部通过 |
| L6-01…L6-39 | 仓库布局与忽略规则 | 仓库文件结构 → 布局符合扁平化规则、忽略规则覆盖到位 | 默认测试会收集，但条件不满足就整体跳过 | 黄 | 运行默认 `pytest`，报告显示 `640 passed, 2 skipped`，这 2 个跳过文件里共有 39 个相关检查 |

## 4. 现在最该处理的六件事

六件事按优先级排好了；时间只够做三件时，按 1、2、3 的顺序做。

1. **`docs/facts.yaml` 的 287 条证据没有校验器。** 原 1132 行校验程序 `scripts/verify_design_facts.py` 在 2026-11-14 随 `scripts/` 目录一起删除；`docs/facts.yaml` 头部注释自己也承认「当前无自动校验器，evidence 的行号、路径存在性与 expect 匹配须人工核对」。影响是事实记录与代码、文档之间的连接正在断裂：本次复核 287 条里 214 条能在本机核对，其中 27 条在原行号找不到原句（23 条只是句子挪了位置，4 条句子已被改写或消失）；另有 73 条标记「证据取自原工作区」，80 条引用指向 21 个本机没有检出的文件，都无法核对。修它要先决定那 73 + 80 条无法核对的证据是保留、补充文件还是删除；然后恢复或重写一个校验器，逐条修正 27 条漂移或消失的证据。修好之后，文档引用的行号、原文、仓库路径再发生变化时，校验器会在第一时间报错，而不是等到审计才发现。 2026-11-19 已把该校验器移植回 `script/checks/facts.py`，本次实测报告 204 条通过 / 0 条位置漂移 / 3 条原文消失，另有 80 条本机无法核对；DF-044 的 `affects` 已修正，条目级结构错误实测为 0。

2. **`data/sub_video/audit.json` 没人生成、没人维护，内容却属于上一批次。** 文件大小 12,022 字节；第 3 行的清单摘要和第 12 行的运行摘要，与 `data/sub_video/superseded-20261113/audit.json` 的对应字段逐字符相同；生成入口 `script/subvideo_generation/generate.py` 里没有该文件名字面量，也没有写文件动作，审计结果只打印到屏幕。影响是审核页的「标签组合待复核」筛选现在不可用；`audit.json` 里记着 54 条候选（判据为「未断裂且断后脱夹」51 条 + 「未断裂且爆炸性断裂」6 条，并集 54 条），这些候选只能靠人工线下复算。修它要决定 `audit.json` 是改成由生成脚本写入、还是由审阅服务维护、或者干脆删除；如果保留，必须让生成或审阅程序在每次批次运行时更新它。修好之后，审核页筛选能实时给出正确结果，以后不会再把上一批次的审计记录当成当前批次用。

3. **仓库卫生的 39 个检查被静默跳过。** `tests/test_layout_migration_guard.py:65` 和 `tests/test_project_workspace.py:10` 在模块级依赖 `pipeline` 包，条件不满足就整体跳过；而 `pipeline/` 目录因为仓库只检出部分目录而不在本机。影响是运行默认测试时报告「640 passed, 2 skipped」，这 39 个检查一个都没跑；「测试全绿」会让人误以为仓库布局与忽略规则已经成立。修它要么把缺失的 `pipeline/` 目录也检出来，要么把这两个测试改成不依赖该目录也能跑，要么把仓库卫生检查从依赖模块里解耦。修好之后，仓库扁平化布局、旧路径字面量、Git 忽略规则等 39 项规则会有人真正去跑，不会被静默跳过掩盖。

4. **默认测试命令覆盖 8 个测试目录。** 默认范围实测收集 640 项并全部通过；9 个测试目录中唯一不在默认范围的是 `script/subvideo_generation/tests`（308 项，需单独按需运行）。按收集数计算，默认覆盖 640/948 ≈ 67.5%；子视频生成测试此前耗时超过 10 分钟仍未跑完，需要按需单独运行。

5. **划分清单与 ROI 清单里记录的文件指纹，没有任何程序回读比对。** 指纹分别写入 `script/data_split/generate.py:530` 和 `script/roi/core.py:392`；只有测试会比对，生产链路不检查。影响是输入换了、产物没换也没人发现；本次已实证：`data/splits/three-fold/manifest.json:256` 起的 12 项输入记录中，4 项与当前文件对不上（`docs_label.md`、`generate.py`、`labels.csv` 内容已变；`docs_data-split-design.md` 已改名为 `docs/split/data-split-design.md` 且内容亦变），另 6 个 `old_fold_*` 快照从未入库，一直没人发现。修它要在划分和 ROI 的入口程序里加入回读比对：每次读取清单时，先核对清单里记录的文件指纹是否与磁盘当前文件一致；不一致时拒绝继续或要求重新生成。修好之后，输入文件悄悄被替换、重命名或内容变更时，程序会停下来要求确认，不会继续用旧清单跑。

6. **所有检查都靠人记得去跑。** 仓库没有 `.github` 目录（无持续集成），没有 `.pre-commit-config.yaml`，Git 钩子目录里只有 `*.sample` 样例文件。影响是检查跑没跑、什么时候跑、跑的结果是什么，全凭个人记忆；时间一长必然漏跑，问题积累到审计时才暴露。修它至少要加一项持续集成配置，在每次推送/合并请求时跑默认测试；再配一个提交前钩子，拦截明显会破坏契约的变更；对耗时的子视频生成测试可以单独放到 nightly 或手动触发。修好之后，检查会变成常规动作而不是记忆负担，基础破坏在提交前或合并前就能被拦住。

## 5. 已经失守的能力

下面六项校验被删除后，一部分已恢复替代品，见最后一列；其余仍没有替代品。

| 已删除的校验 | 以前能防住什么 | 删除时间 | 现在有没有替代品 |
|---|---|---|---|
| `scripts/verify_design_facts.py`（1132 行） | `docs/facts.yaml` 每条证据的文件、行号、原文是否还对得上 | 2026-11-14，提交 `4cd54fa` | `script/checks/facts.py`（已移植，实测见第 4 节第 1 条） |
| 同一程序的文档路径检查模式（配白名单 `scripts/doc-path-allowlist.txt`） | 文档里写的仓库路径是否真的存在 | 同上 | `script/checks/facts.py --check-doc-paths` + `script/checks/doc-path-allowlist.txt`（已随本次移植恢复；当前工作区部分目录未检出，会按「无法读取」报错） |
| `scripts/serve_validate_delivery.py`（181 行） | 模型/服务交付时的批次身份是否正确 | 同上 | 没有 |
| `scripts/serve_validate_no_oob.py`（289 行） | 模型/服务有没有越界输出 | 同上 | 没有 |
| `scripts/source_validate_environment.py`（119 行） | 环境依赖与源数据配置是否符合要求 | 同上 | 没有 |
| 上述校验程序自己的回归测试 `tests/test_verify_design_facts.py`、`tests/test_serve_validate_delivery.py` | 校验程序本身的逻辑不被改坏 | 同上（脚本删了，测试文件已从 Git 索引移除，磁盘上也没有） | 没有 |

## 6. 附录：完整清单

这里按六层列出全部 134 项检查，供以后核对使用。

本表以一个能独立给出通过或不通过结论的判断点为一项。同一件事在代码里可能由多处共同保证，本表只记一个判断点；如果按一个代码函数或一条测试用例来数，分到六层的数量会与本表不同，但总数以本表为准。

### 源数据层（L1）

| 编号 | 层 | 一句话说明 | 位置 | 触发方式 | 状态 |
|---|---|---|---|---|---|
| L1-01 | 源数据 | 分组记录的标注表文件指纹与当前表不符；已实测仅 44 个单元格从「无法确定」规范为「无法判断」，两版均为 111 行 × 28 列、表头逐字节相同、其余内容等价，不是真问题。 | `data/split-inputs/source-groups-20261107.json:6` | 查看记录并与当前标注表比对 | 黄 |
| L1-02 | 源数据 | 划分清单的 12 项输入记录中，`docs_label.md`、`generate.py`、`labels.csv` 内容已变，`docs_data-split-design.md` 已改名为 `docs/split/data-split-design.md` 且内容亦变；6 个 `old_fold_*` 快照从未入库，`groups.json` 和 `test.json` 一致；这是生成后的历史漂移，不代表划分失效。 | `data/splits/three-fold/manifest.json:256` | 查看记录并与当前文件及入库历史比对 | 黄 |
| L1-03 | 源数据 | 缺少 ID、重复 ID、空标签、非法枚举或不合法标签组合必须拒绝。 | `script/data_split/tests/test_generate.py:132` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests` | 绿 |
| L1-04 | 源数据 | 旧的不确定性术语归一化为「无法判断」。 | `script/data_split/tests/test_generate.py:153` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests` | 绿 |
| L1-05 | 源数据 | 分组跨测试集边界、成员重复或缺失等声明必须拒绝。 | `script/data_split/tests/test_generate.py:167` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests` | 绿 |
| L1-06 | 源数据 | 生成时保留测试集、开发集按整个来源分组轮换训练和验证，且集合不重叠。 | `script/data_split/tests/test_generate.py:291` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests` | 绿 |
| L1-07 | 源数据 | 新生成清单绑定输入、输出字节的指纹以及代码和规则信息。 | `script/data_split/tests/test_generate.py:320` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests` | 绿 |
| L1-08 | 源数据 | 同样输入在不同随机种子下生成的字节可复现。 | `script/data_split/tests/test_generate.py:379` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests` | 绿 |
| L1-09 | 源数据 | 暂存后的发布失败不留下正式或部分发布目录。 | `script/data_split/tests/test_generate.py:400` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests` | 绿 |
| L1-10 | 源数据 | 来源视频身份与裁剪决定不符时不能生成 ROI。 | `script/roi/tests/test_core.py:105` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-11 | 源数据 | 无裁剪时保留源画面并补到最小偶数画布。 | `script/roi/tests/test_core.py:211` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-12 | 源数据 | 固定裁剪记录各边移除量并拒绝非法几何范围。 | `script/roi/tests/test_core.py:223` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-13 | 源数据 | 输出媒体的几何、时间或方向不符合要求时拒绝验收。 | `script/roi/tests/test_core.py:328` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-14 | 源数据 | 外部导入输出的文件指纹不符时不能发布或重新绑定来源。 | `script/roi/tests/test_core.py:698` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-15 | 源数据 | ROI 标签显式编辑只保存变化值，原始标注 CSV 字节不变。 | `script/roi/tests/test_label_reviews.py:77` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-16 | 源数据 | 旧浏览器修订不能静默覆盖较新的标签编辑。 | `script/roi/tests/test_label_reviews.py:143` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-17 | 源数据 | 非法标签值或仅来源字段的编辑不能写入复核记录。 | `script/roi/tests/test_label_reviews.py:169` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-18 | 源数据 | 整理 ROI 视频时，输入已改变或缺失不能发布部分结果。 | `script/roi/tests/test_organize_videos.py:168` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-19 | 源数据 | 清理准备时规范位置的媒体未验证则不能发布。 | `script/roi/tests/test_cleanup_readiness.py:176` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |
| L1-20 | 源数据 | 老输出字节变化不能被静默接受。 | `script/roi/tests/test_simple_workflow.py:160` | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests` | 绿 |

### 子视频生成层（L2）

| 编号 | 层 | 一句话说明 | 位置 | 触发方式 | 状态 |
|---|---|---|---|---|---|
| L2-01 | 子视频生成 | 检查审计输出是否暴露降级工具链信息。 | `script/subvideo_generation/tests/test_audit_toolchain_surface.py:35` | 单独运行对应测试 | 黄 |
| L2-02 | 子视频生成 | 内容审计不因当前代码指纹变化而改变结论。 | `script/subvideo_generation/tests/test_content_audit_ignores_code_identity.py:22` | 单独运行对应测试 | 黄 |
| L2-03 | 子视频生成 | 策略分派要求源标注行。 | `script/subvideo_generation/tests/test_coverage_rule_guards.py:51` | 单独运行对应测试 | 黄 |
| L2-04 | 子视频生成 | 无锚点且无法判断的源视频进入覆盖策略。 | `script/subvideo_generation/tests/test_coverage_rule_guards.py:132` | 单独运行对应测试 | 黄 |
| L2-05 | 子视频生成 | 覆盖窗口的步长和尾窗符合规则。 | `script/subvideo_generation/tests/test_coverage_stride_plan.py:21` | 单独运行对应测试 | 黄 |
| L2-06 | 子视频生成 | 可靠事件不会因兼容的新标签被丢弃。 | `script/subvideo_generation/tests/test_generation_contract.py:44` | 单独运行对应测试 | 黄 |
| L2-07 | 子视频生成 | 精确事件窗口保留保护区与事件后素材。 | `script/subvideo_generation/tests/test_generation_contract.py:72` | 单独运行对应测试 | 黄 |
| L2-08 | 子视频生成 | 片段证明失败时不能留下已发布输出。 | `script/subvideo_generation/tests/test_generation_contract.py:228` | 单独运行对应测试；合成媒体需要 FFmpeg | 黄 |
| L2-09 | 子视频生成 | 当前规划结果与黄金计划对照。 | `script/subvideo_generation/tests/test_golden_plan.py:89` | 单独运行对应测试；缺工具或真实素材可跳过 | 黄 |
| L2-10 | 子视频生成 | 代码指纹变化不阻止身份匹配的批次续跑。 | `script/subvideo_generation/tests/test_identity_ignores_code.py:32` | 单独运行对应测试 | 黄 |
| L2-11 | 子视频生成 | 旧批次可做内容审计但没有规则摘要时拒绝续跑。 | `script/subvideo_generation/tests/test_legacy_batch_content_audit_and_resume_refusal.py:24` | 单独运行该模块测试 | 黄 |
| L2-12 | 子视频生成 | 标注或划分输入变化时续跑被拒绝。 | `script/subvideo_generation/tests/test_resume_rejects_input_change.py:7` | 单独运行该模块测试 | 黄 |
| L2-13 | 子视频生成 | 窗口、覆盖或特殊规则变化时续跑被拒绝。 | `script/subvideo_generation/tests/test_resume_rejects_rules_change.py:18` | 单独运行该模块测试 | 黄 |
| L2-14 | 子视频生成 | 规则登记表字段和摘要的形状与稳定性受检查。 | `script/subvideo_generation/tests/test_rules_registry.py:206` | 单独运行该模块测试 | 黄 |
| L2-15 | 子视频生成 | 覆盖策略判据按源标注而非视频编号判断。 | `script/subvideo_generation/tests/test_rules_registry.py:368` | 单独运行对应测试 | 黄 |
| L2-16 | 子视频生成 | 本地 FFmpeg 标记为降级，缺失或版本探测失败为硬错误。 | `script/subvideo_generation/tests/test_toolchain_degradation.py:40` | 单独运行该模块测试 | 黄 |
| L2-17 | 子视频生成 | 未夹紧现象锚点的文档记录有歧义或不可用时被拒绝。 | `script/subvideo_generation/tests/test_unclamped_contract.py:61` | 单独运行对应测试 | 黄 |
| L2-18 | 子视频生成 | 未夹紧源内容不匹配时被阻止。 | `script/subvideo_generation/tests/test_unclamped_contract.py:152` | 单独运行对应测试；真实媒体测试有工具依赖 | 黄 |
| L2-19 | 子视频生成 | 统一规划检查覆盖窗口的短视频、步长和尾窗。 | `script/subvideo_generation/tests/test_unified_contract.py:124` | 单独运行对应测试 | 黄 |
| L2-20 | 子视频生成 | 续跑编码前检查清单是否遭篡改。 | `script/subvideo_generation/tests/test_unified_contract.py:290` | 单独运行对应测试 | 黄 |
| L2-21 | 子视频生成 | basic 校验不调用逐帧验证器。 | `script/subvideo_generation/tests/test_verification_modes.py:205` | 单独运行对应测试 | 黄 |
| L2-22 | 子视频生成 | none 校验不探测输出媒体。 | `script/subvideo_generation/tests/test_verification_modes.py:295` | 单独运行对应测试 | 黄 |
| L2-23 | 子视频生成 | 视频目录扫描只接受顶层 MP4，并拒绝无效目录或符号链接。 | `script/subvideo_generation/tests/test_videos_dir_mode.py:237` | 单独运行该组测试 | 黄 |
| L2-24 | 子视频生成 | 虚拟视频目录输入字节变化时续跑被拒绝。 | `script/subvideo_generation/tests/test_videos_dir_mode.py:484` | 单独运行对应测试；缺 FFmpeg 可跳过 | 黄 |
| L2-25 | 子视频生成 | 虚拟批次续跑不因代码侧变化而失败。 | `script/subvideo_generation/tests/test_virtual_identity_rules.py:39` | 单独运行对应测试；缺 FFmpeg 可跳过 | 黄 |
| L2-26 | 子视频生成 | 规则摘要不同时拒绝续跑。 | `script/subvideo_generation/generate.py:194` | 续跑或完整批次审计时比较身份 | 黄 |
| L2-27 | 子视频生成 | 输入、批次模式或模式版本身份不同时拒绝续跑。 | `script/subvideo_generation/generate.py:196` | 续跑或完整批次审计时比较身份 | 黄 |
| L2-28 | 子视频生成 | 运行期间输入或生成规则发生变化时中止。 | `script/subvideo_generation/generate.py:200` | 运行中的身份复核 | 黄 |
| L2-29 | 子视频生成 | 完整批次审计比较 summary 与从 manifest 计算的摘要。 | `script/subvideo_generation/generate.py:820` | 显式执行完整批次审计 | 黄 |
| L2-30 | 子视频生成 | 审计记录的清单摘要与当前 manifest 的摘要不一致。 | `data/sub_video/audit.json:3` | 只读计算当前清单摘要并对照记录 | 红 |
| L2-31 | 子视频生成 | 审计记录的本轮运行摘要属于上一批次；当前和 superseded 审计文件均为 12022 字节且两个记录摘要相同。 | `data/sub_video/audit.json:12` | 对照旧审计文件与记录摘要 | 红 |
| L2-32 | 子视频生成 | 没有程序生成或维护 audit.json；generate.py 无该字面量、write_text 或 json.dump，审计结果只打印；仓库中仅审阅服务读取该文件。 | `script/subvideo_generation/generate.py:953`；读取位置 `script/subvideo_review/server.py:154` | 不存在自动生成或维护触发 | 孤儿 |

### 人工审核层（L3）

| 编号 | 层 | 一句话说明 | 位置 | 触发方式 | 状态 |
|---|---|---|---|---|---|
| L3-01 | 人工审核 | 审核标签值及完整性由服务校验。 | `script/subvideo_review/server.py:53` | 保存审核 | 绿 |
| L3-02 | 人工审核 | 不在清单中的来源被拒绝。 | `script/subvideo_review/server.py:368` | 请求来源视频或候选视频 | 绿 |
| L3-03 | 人工审核 | 审核记录只有身份字段与当前候选一致才匹配。 | `script/subvideo_review/server.py:423` | 读取审核 | 绿 |
| L3-04 | 人工审核 | 审核记录修订摘要和重复 ID 会被核对。 | `script/subvideo_review/server.py:404` | 读取记录 | 绿 |
| L3-05 | 人工审核 | 审核保存使用锁文件串行化。 | `script/subvideo_review/server.py:514` | 保存审核 | 绿 |
| L3-06 | 人工审核 | 保存时先写同目录 .reviews- 临时文件再替换记录，并清理遗留临时文件。 | `script/subvideo_review/server.py:533` | 保存审核 | 绿 |
| L3-07 | 人工审核 | 当前审核修订记录存于 reviews.json。 | `data/subvideo-review/reviews.json:1` | 审核服务读取 | 绿 |
| L3-08 | 人工审核 | 标签组合待复核筛选要求 audit.json 清单摘要与当前清单一致；当前记录与当前清单不一致，筛选不可用，54 条候选只能线下人工复算。 | `script/subvideo_review/server.py:252`；`data/sub_video/audit.json:3`；`data/sub_video/audit.json:19`；`script/subvideo_review/README.md:11` | 审核页加载审计摘要 | 黄 |
| L3-09 | 人工审核 | 审核媒体读取时核对文件摘要。 | `script/subvideo_review/server.py:458` | 播放审核视频 | 绿 |
| L3-10 | 人工审核 | 清单与规则等变更后停止使用原快照。 | `script/subvideo_review/server.py:385` | 审核服务操作 | 绿 |
| L3-11 | 人工审核 | ROI 决策校验审核状态及批准条件。 | `script/roi/app.py:431` | 保存 ROI 决策 | 绿 |
| L3-12 | 人工审核 | ROI 已存决策与来源文件状态不符时页面提示。 | `script/roi/app.py:814` | 打开 ROI 视频 | 绿 |
| L3-13 | 人工审核 | ROI 审核状态保存在决策文件。 | `data/roi/decisions.json:14` | ROI 页面读取 | 绿 |
| L3-14 | 人工审核 | 标注审核替换 CSV 时核对预期内容。 | `script/annotation/review_run_annotation.py:373` | 标注审核提交 | 绿 |
| L3-15 | 人工审核 | 审核服务与标注审核测试均在 pytest 默认测试范围；分别收集 45、10 项，全部通过。 | `script/subvideo_review/tests/test_server.py:1`；`pyproject.toml:19` | 默认 pytest 收集 | 绿 |
| L3-16 | 人工审核 | 集成测试在默认范围，收集 82 项；浏览器脚本行为测试缺 Node 时跳过。 | `script/integration_tests/test_label_runtime_behavior.py:272`；`pyproject.toml:19` | 默认 pytest 收集 | 绿 |

### 模型评价层（L4）

| 编号 | 层 | 一句话说明 | 位置 | 触发方式 | 状态 |
|---|---|---|---|---|---|
| L4-01 | 模型评价 | 评分器检查身份字段及文件指纹格式。 | `script/five_label_eval/score.py:91` | 评分输入校验 | 绿 |
| L4-02 | 模型评价 | 评分器拒绝重复候选及冲突来源类型。 | `script/five_label_eval/score.py:230` | 准备评分 | 绿 |
| L4-03 | 模型评价 | 评分器拒绝预测候选与摘要不一致。 | `script/five_label_eval/score.py:289` | 准备评分 | 绿 |
| L4-04 | 模型评价 | 评分器检查 JSON 重复键。 | `script/five_label_eval/score.py:57` | 读取评分输入 | 绿 |
| L4-05 | 模型评价 | 评分器区分字段真值及未知值。 | `script/five_label_eval/score.py:116` | 计算评分 | 绿 |
| L4-06 | 模型评价 | 帧记录来源链验证返回不可信原因。 | `script/five_label_eval/frames.py:380` | 验证帧来源链 | 绿 |
| L4-07 | 模型评价 | 帧来源链由候选及回放证据推导。 | `script/five_label_eval/frames.py:146` | 构建帧记录 | 绿 |
| L4-08 | 模型评价 | 帧来源链核对媒体与记录摘要身份。 | `script/five_label_eval/frames.py:558` | 验证帧来源链 | 绿 |
| L4-09 | 模型评价 | 草稿清单拒绝重复或缺失的候选选择。 | `script/five_label_eval/build_manifest.py:16` | 构建清单草稿 | 绿 |
| L4-10 | 模型评价 | 清单转换检查候选及视频摘要格式。 | `script/five_label_eval/manifest_convert.py:54` | 转换清单 | 绿 |
| L4-11 | 模型评价 | 清单转换对来源类型的推断要求来源 ID 符合条件。 | `script/five_label_eval/manifest_convert.py:40` | 转换清单 | 绿 |
| L4-12 | 模型评价 | 模型输入规划拒绝清单外候选及摘要不一致的记录。 | `script/five_label_eval/infer.py:46` | 规划假预测 | 绿 |
| L4-13 | 模型评价 | 推理入口目前仅实现 fake 后端，transformers 后端未实现。 | `script/five_label_eval/infer.py:90` | 显式调用推理入口 | 绿 |
| L4-14 | 模型评价 | 路径配置加载和占位符识别由路径模块处理。 | `script/five_label_eval/paths.py:27` | 读取评价路径配置 | 绿 |
| L4-15 | 模型评价 | 提示词内容可生成身份摘要；评价测试默认收集 225 项，本次实测全部通过。 | `script/five_label_eval/prompt_id.py:12`；`pyproject.toml:19` | 计算提示词身份；默认 pytest 收集 | 绿 |
| L4-16 | 模型评价 | 模型与服务交付身份校验脚本 181 行，提交 4cd54fa 于 2026-11-14 删除。 | `scripts/serve_validate_delivery.py`（当前不存在） | 无 | 孤儿 |
| L4-17 | 模型评价 | 越界检查脚本 289 行，提交 4cd54fa 于 2026-11-14 删除。 | `scripts/serve_validate_no_oob.py`（当前不存在） | 无 | 孤儿 |

### 文档与事实层（L5）

| 编号 | 层 | 一句话说明 | 位置 | 触发方式 | 状态 |
|---|---|---|---|---|---|
| L5-01 | 文档与事实 | 证据行号位置漂移实测 0 条。 | `script/checks/facts.py` | `--json` | 红 |
| L5-02 | 文档与事实 | expect 在全文找不到实测 3 条。 | `script/checks/facts.py` | `--json` | 红 |
| L5-03 | 文档与事实 | sparse-checkout 下 41 个受跟踪 Markdown 无法读取，尚不能判定路径。 | `script/checks/facts.py`；`script/checks/doc-path-allowlist.txt` | `--check-doc-paths` | 黄 |
| L5-04 | 文档与事实 | 49 条 state 合法；DF-044 的 affects 已修正，`structure_errors` 实测为 0。 | `script/checks/facts.py` | `--json` | 绿 |
| L5-05 | 文档与事实 | 移植版校验器的测试 73 项通过，提供五类汇总。 | `script/checks/facts.py` | pytest；默认模式 | 绿 |
| L5-06 | 文档与事实 | 移植版不含标题与锚点校验。 | `script/checks/facts.py` | 无 | 孤儿 |

### 仓库卫生层（L6）

| 编号 | 层 | 一句话说明 | 位置 | 触发方式 | 状态 |
|---|---|---|---|---|---|
| L6-01 | 仓库卫生 | 待搬迁清单必须是映射表的子集。 | `tests/test_layout_migration_guard.py:109` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-02 | 仓库卫生 | 旧布局的物理目录不能再存在。 | `tests/test_layout_migration_guard.py:118` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-03 | 仓库卫生 | 工作区根目录不能再存在。 | `tests/test_layout_migration_guard.py:129` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-04 | 仓库卫生 | 待搬迁清单必须保持为空。 | `tests/test_layout_migration_guard.py:142` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-05 | 仓库卫生 | 工作区内旧的 evaluations 路径不能再存在。 | `tests/test_layout_migration_guard.py:154` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-06 | 仓库卫生 | 扁平化后 evaluations 应在顶层。 | `tests/test_layout_migration_guard.py:167` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-07 | 仓库卫生 | 源码里不能有旧工作区路径字面量。 | `tests/test_layout_migration_guard.py:287` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-08 | 仓库卫生 | 例外标记只允许出现在备份模块。 | `tests/test_layout_migration_guard.py:310` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-09 | 仓库卫生 | 例外标记只能用于打包结构判断。 | `tests/test_layout_migration_guard.py:326` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-10 | 仓库卫生 | 例外标记数量不超过上限。 | `tests/test_layout_migration_guard.py:346` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-11 | 仓库卫生 | 源码里不能有旧基座模型路径字面量。 | `tests/test_layout_migration_guard.py:425` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-12 | 仓库卫生 | 旧基座路径探测能识别已知字面量。 | `tests/test_layout_migration_guard.py:439` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-13 | 仓库卫生 | 白名单条目仍只对应一行宿主代码。 | `tests/test_layout_migration_guard.py:491` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-14 | 仓库卫生 | 旧基座路径被抓、新路径放行的端到端检查。 | `tests/test_layout_migration_guard.py:533` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-15 | 仓库卫生 | 白名单条数不超过上限。 | `tests/test_layout_migration_guard.py:579` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-16 | 仓库卫生 | 工作区根目录就是仓库根目录。 | `tests/test_layout_migration_guard.py:596` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-17 | 仓库卫生 | 子项目不能嵌套在工作区里。 | `tests/test_layout_migration_guard.py:603` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-18 | 仓库卫生 | 子目录名符合扁平化布局。 | `tests/test_layout_migration_guard.py:622` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-19 | 仓库卫生 | 实验产物落在 trains 目录。 | `tests/test_layout_migration_guard.py:632` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-20 | 仓库卫生 | 扁平化产物未被 Git 跟踪。 | `tests/test_layout_migration_guard.py:643` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-21 | 仓库卫生 | 数据媒体与运行时锁文件未被 Git 跟踪。 | `tests/test_layout_migration_guard.py:670` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-22 | 仓库卫生 | 忽略规则覆盖扁平化路径。 | `tests/test_layout_migration_guard.py:692` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-23 | 仓库卫生 | 数据记录不被误忽略。 | `tests/test_layout_migration_guard.py:717` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-24 | 仓库卫生 | 各种视频格式被忽略。 | `tests/test_layout_migration_guard.py:731` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-25 | 仓库卫生 | 当前 v4.1 路径都在项目内。 | `tests/test_project_workspace.py:40` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-26 | 仓库卫生 | 重建时旧路径映射到隔离根目录。 | `tests/test_project_workspace.py:53` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-27 | 仓库卫生 | 错误根目录与路径逃逸被拒绝。 | `tests/test_project_workspace.py:70` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-28 | 仓库卫生 | 冻结的绝对路径被正确映射。 | `tests/test_project_workspace.py:85` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-29 | 仓库卫生 | 候选计划路径不带重建编号。 | `tests/test_project_workspace.py:100` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-30 | 仓库卫生 | 候选与审核路径都不带重建编号。 | `tests/test_project_workspace.py:114` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-31 | 仓库卫生 | 查看旧上下文只读且要求冻结根目录。 | `tests/test_project_workspace.py:139` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-32 | 仓库卫生 | 暂存创建的门与续跑身份。 | `tests/test_project_workspace.py:166` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-33 | 仓库卫生 | 续跑拒绝符号链接的根目录。 | `tests/test_project_workspace.py:200` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-34 | 仓库卫生 | 写入守卫拒绝旧根目录与版本化根目录。 | `tests/test_project_workspace.py:232` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-35 | 仓库卫生 | 语义化实验编号决定产物目录。 | `tests/test_project_workspace.py:268` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-36 | 仓库卫生 | 模块不暴露默认实验编号。 | `tests/test_project_workspace.py:288` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-37 | 仓库卫生 | 扁平化本地产物被 Git 忽略。 | `tests/test_project_workspace.py:292` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-38 | 仓库卫生 | 工作区模块不依赖环境变量。 | `tests/test_project_workspace.py:317` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-39 | 仓库卫生 | 模型输出必须落在工作区 runs 下。 | `tests/test_project_workspace.py:329` | 默认测试会收集到它，但条件不满足就整体跳过 | 黄 |
| L6-40 | 仓库卫生 | 无持续集成（仓库无 `.github` 目录）。 | 当前不存在：仓库根目录无 `.github` | 无 | 孤儿 |
| L6-41 | 仓库卫生 | 无 `.pre-commit-config.yaml`。 | 当前不存在：仓库根目录无该文件 | 无 | 孤儿 |
| L6-42 | 仓库卫生 | Git 钩子目录只有 `*.sample` 样例（`git rev-parse --git-path hooks` 指向的目录）。 | 当前不存在：钩子目录仅含样例 | 无 | 孤儿 |
| L6-43 | 仓库卫生 | `tests/test_verify_design_facts.py`、`tests/test_serve_validate_delivery.py` 与 `tests/test_environment_deployment.py` 已从索引移除，磁盘上也没有。 | 当前不存在：索引和磁盘均无 | 无 | 孤儿 |

六层 20+32+16+17+6+43=134；绿 50、黄 72、红 4、孤儿 8。

## 7. 这份台账自己的失效条件

以下任一变化发生后，本台账需要重写：

- 新增或删除检查项，导致总数不再是 134。
- 测试目录或默认测试范围调整。
- `docs/facts.yaml` 或 `data/sub_video/audit.json` 的处理决定改变。
- 六层划分调整。
- `pipeline/` 等目录被检出后，那 39 个检查恢复运行。
