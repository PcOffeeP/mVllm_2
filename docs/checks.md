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
| 子视频生成（把源视频切成候选片段那一步） | 片段怎么切、规则怎么派、批次怎么续跑 | 32 | 1·29·0·2 | 批次已退役，审计规则和写盘入口仍在，当前无对象可查；整套检查需单独运行。 |
| 人工审核（你看片打标签的界面） | 审核服务、ROI 决策、标注审核 | 16 | 15·0·0·1 | 批次已退役，标签组合筛选规则仍在，当前无对象可查。 |
| 模型评价（评分器与模型输入记录） | 评分器、帧来源链、清单转换、推理入口 | 17 | 15·0·0·2 | 在跑的这部分是好的；模型交付校验已删。 |
| 文档与事实（`docs/facts.yaml` 那套「哪句话有出处」的记录） | 文档里的证据还对不对得上原文 | 6 | 3·1·1·1 | 校验程序已移植回 `script/checks/facts.py`，判定改为锚文本（`expect` 能否定位、行号只作提示），实测通过 203（记录行命中 189、位置已变 14）、原文消失 4、歧义 0；标题/锚点校验仍缺。 |
| 仓库卫生（哪些文件该进版本库、哪些不该） | 仓库布局、旧路径、Git 忽略规则 | 43 | 19·20·0·4 | 19 项已真正执行并通过；20 项按未检出目录逐条具名跳过（18 项缺 `pipeline/`、2 项缺 `versioning/backup.py`）。 |

六层合计 20+32+16+17+6+43=134；绿 71、黄 52、红 1、孤儿 10。

## 3. 主表：只列「需要你知道」的检查

下面 24 行是项目负责人现在必须知道的检查。为避免术语拖住阅读，先说明四个词：文件指纹（文件内容算出来的一串字符，内容变一个字节就会变）、批次身份（这批产物是由哪几个输入、哪套规则生成的）、契约（人和程序之间约定好的规则）、校验器（检查这些规则有没有被遵守的程序）。本文只使用这四个核心术语。

| 编号 | 它在管什么（人话，一句话） | 检查的输入 → 输出的判断 | 谁在跑 | 状态 | 怎么自己确认它现在是这个状态 |
|---|---|---|---|---|---|
| L2-30 | 审计记录里的清单摘要与当前清单是否一致 | 批次审计记录与清单 → 摘要一致 | 规则和写盘入口仍在；对象已随批次退役，当前无可查对象 | 孤儿 | 新批次生成后对照其清单与核验记录 |
| L2-31 | 审计记录里的运行摘要是否属于当前批次 | 批次审计记录 → 运行摘要属于该批次 | 规则和写盘入口仍在；对象已随批次退役，当前无可查对象 | 孤儿 | 新批次生成后核对其运行摘要 |
| L2-32 | 有没有程序负责生成和维护审计文件 | `script/subvideo_generation/generate.py` 的写文件动作 → 应当生成或维护 `audit.json` | 生成入口已具备写盘能力（`--write-audit` / `--replace-audit`，fail-closed + 原子写），有 29 例测试守住 | 绿 | 运行 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q script/subvideo_generation/tests/test_audit_record_writes.py`，看到 29 例通过 |
| L4-16 | 模型/服务交付时的批次身份对不对 | 交付产物与约定规则 → 身份一致才放行 | 没有；脚本已删除 | 孤儿 | 仓库里找不到 `scripts/serve_validate_delivery.py` |
| L4-17 | 模型/服务有没有越界输出 | 服务响应与允许范围 → 不越界 | 没有；脚本已删除 | 孤儿 | 仓库里找不到 `scripts/serve_validate_no_oob.py` |
| L5-01 | 文档证据的 `expect` 原文是否还能在文件中定位（行号只作提示） | `docs/facts.yaml` 的 ref 证据 → `expect` 原文可在目标文件定位，位置变化不算错 | `.venv/bin/python -m script.checks.facts --json`（2026-11-19 实测） | 绿 | 运行该 `--json` 命令，看 `totals.passed`（实测 203，其中记录行命中 189、位置已变 14）与 `totals.ambiguous`（实测 0）；`totals.passed_moved` 不再算失败 |
| L5-02 | 文档证据的 expect 断言是否还成立 | `docs/facts.yaml` 的 expect 字段 → 断言内容仍与原文一致，或在全文多处出现无法唯一确定 | `.venv/bin/python -m script.checks.facts --json`（2026-11-19 实测） | 红 | 运行该 `--json` 命令，看 `totals.gone`（实测 4，表示 expect 在全文都找不到）与 `totals.ambiguous`（实测 0，多处命中无法唯一确定） |
| L5-03 | 文档里写的仓库路径是否真实存在 | Markdown 中的仓库内路径 → 路径存在 | `.venv/bin/python -m script.checks.facts --check-doc-paths` | 黄 | 运行该命令，会看到 41 个受跟踪 Markdown「无法读取」后退出 1（sparse-checkout 未检出，尚给不出路径判定） |
| L5-04 | 文档记录格式的状态取值是否合法 | `docs/facts.yaml` 的状态字段 → 取值在允许列表内 | `.venv/bin/python -m script.checks.facts --json`（2026-11-19 实测） | 绿 | 运行该 `--json` 命令，看 `structure_errors`：49 条 state 全部合法，DF-044 的 `affects` 已修正，`structure_errors` 实测为 0 |
| L5-05 | 原 1132 行文档事实校验程序本身 | `docs/facts.yaml` 与仓库文件 → 证据、路径检查结果 | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q script/checks/tests`（87 项） | 绿 | 运行该 pytest 命令看 `87 passed`，再跑 `.venv/bin/python -m script.checks.facts` 看五类汇总 |
| L5-06 | 文档内部标题与互相引用是否还连得上 | `docs/facts.yaml` 的标题与锚点引用 → 引用目标存在 | 没有；移植版只校验证据行与文档路径，不含标题/锚点校验 | 孤儿 | 在 `script/checks/facts.py` 里搜索 `anchor`／标题解析，没有对应逻辑 |
| L6-40 | 仓库有没有持续集成 | 仓库根目录 → 存在 CI 配置 | 没有 | 孤儿 | 在项目根目录执行 `ls -la .github`，提示没有该目录 |
| L6-41 | 提交前有没有自动检查钩子 | 仓库根目录 → 存在提交前钩子配置 | 没有 | 孤儿 | 在项目根目录执行 `ls -la .pre-commit-config.yaml`，提示没有该文件 |
| L6-42 | Git 钩子目录里有没有真正生效的钩子 | Git 钩子目录 → 存在非样例钩子 | 没有 | 孤儿 | 执行 `ls $(git rev-parse --git-path hooks)`，只看到 `*.sample` 文件 |
| L6-43 | 已删除校验器的回归测试是否还留在索引里 | Git 索引与磁盘文件 → 索引中的测试文件在磁盘上存在 | 没有；磁盘上没有，跑不到 | 孤儿 | `tests/test_verify_design_facts.py`、`tests/test_serve_validate_delivery.py`、`tests/test_environment_deployment.py` 已从索引移除，磁盘上也没有 |
| L1-03 | 标注表的非法取值与标签组合 | 标注表记录 → 缺少 ID、重复 ID、空标签、非法枚举、不合法标签组合都被拒绝 | `script/data_split/tests/test_generate.py:132` | 绿 | 运行 `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/data_split/tests`，该测试通过 |
| L1-13 | ROI 输出的画面尺寸、时长、方向 | ROI 输出媒体 → 几何、时间、方向符合要求才验收 | `script/roi/tests/test_core.py:328` | 绿 | 运行 `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider script/roi/tests`，该测试通过 |
| L3-16 | 审核与评分的集成行为 | 集成测试集 → 82 项行为检查通过 | 默认 pytest；本次实测 717 项通过（另有 20 项具名跳过），其中集成 82 项 | 绿 | 运行默认 `pytest`，看到集成测试通过 |
| L4-01 | 评分器检查身份字段和文件指纹格式 | 评分文件 → 身份字段存在、文件指纹格式正确 | `script/five_label_eval/score.py:91` | 绿 | 运行默认 `pytest` 中评价相关测试，或打开 `script/five_label_eval/score.py:91` 看校验逻辑 |
| L1-01…L1-02 | 标注表与划分清单的历史记录是否还对应得上当前文件 | 记录中的文件指纹与当前文件 → 指纹一致 | 测试会跑，但记录本身在漂移 | 黄 | 打开 `data/split-inputs/source-groups-20261107.json:6` 与 `data/splits/three-fold/manifest.json:256`，比对记录中的文件指纹和当前文件 |
| L2-01…L2-29 | 子视频生成全阶段的契约与身份校验 | 源视频、标注、规则 → 片段、覆盖、续跑、审计都符合规则 | 须单独运行该目录测试 | 黄 | 打开 `pyproject.toml` 第 19 行，看默认测试范围里没有 `script/subvideo_generation/tests` |
| L3-08 | 审核页「标签组合待复核」筛选 | 批次核验记录与清单 → 摘要一致时筛选可用 | 筛选规则仍在；对象已随批次退役，当前无可查对象 | 孤儿 | 新批次生成后核对其记录与筛选 |
| L3-15 | 审核服务与标注审核的测试 | 对应测试目录 → 45 + 10 项检查通过 | 默认 pytest；审核服务和标注审核测试均通过 | 绿 | 运行默认 `pytest`，收集审核服务 45 项、标注审核 10 项，全部通过 |
| L6-01…L6-39 | 仓库布局与忽略规则 | 仓库文件结构 → 布局符合扁平化规则、忽略规则覆盖到位 | 默认 `pytest` 会收集全部 63 个测试条目 | 19·20·0（绿·黄·红） | 运行默认 `pytest`，报告显示 `717 passed, 20 skipped`；加 `-rs` 可逐条看到 20 条跳过理由：18 条为 sparse-checkout 未检出 `pipeline/`、2 条为未检出 `versioning/backup.py` |

## 4. 现在最该处理的六件事

六件事按优先级排好了；时间只够做三件时，按 1、2、3 的顺序做。

1. **`docs/facts.yaml` 的 287 条证据里仍有 4 条原文消失。** 校验器已于 2026-11-19 移植回 `script/checks/facts.py`（默认报告模式、`--strict` 拦截），`docs/facts.yaml` 头部注释也已同步改写成「由该脚本核对」，不再声称「当前无自动校验器」。证据判定改为锚文本契约：以 `expect` 原文能否在目标文件中定位为准，`ref` 里的行号只作提示，正文移动导致行号变化不算错；只有原文被改写、被删除，或在同一文件中出现多处、无法唯一确定（单列为「歧义」）时才算问题。最近一次实测（`.venv/bin/python -m script.checks.facts --json`）的五类分布是：通过 203（记录行命中 189、位置已变 14）、原文消失 4、歧义 0、本机无法核对 80、结构错误 0，合计 287 条证据。影响是仍有 4 条事实记录与原文的连接断了：其 `expect` 在全文找不到，需要补回文件、改路径或删除条目；另有 80 条引用的路径在本机未检出（sparse-checkout），只能在原工作区或训练机上核对。标题与锚点校验仍未移植（台账 L5-06 记为孤儿）。修好之后，正文增删导致的行号移动不会再报错、也不需逐条改行号；只有原文被改写、被删除，或同一文件里出现多处命中无法唯一确定时，校验器才会在第一时间报错，而不是等到审计才发现。DF-044 的 `affects` 已修正，条目级结构错误实测为 0。

2. **审计记录写入入口仍在，但旧批次对象已退役。** 显式执行 `--audit-only --write-audit` 可写入；已有记录须显式加 `--replace-audit` 才覆盖。批次身份或清单校验不通过时 fail-closed 拒绝写入；写盘为原子替换，有 29 例测试覆盖。旧批次的清单与核验记录已移除，当前无可查对象，L2-30、L2-31 和 L3-08 因此记为孤儿；新批次生成后以该批次清单和核验记录为准。

3. **仓库卫生 39 项检查已从「静默跳过」改为「19 项执行通过 + 20 项具名跳过」。** 两个文件原本在模块级 `pytest.importorskip("pipeline")`，条件不满足就整文件跳过，默认测试报告 `660 passed, 2 skipped`，这 39 项一个都没跑。现改为惰性依赖：不依赖 `pipeline` 的用例直接执行（`tests/test_layout_migration_guard.py` 的 T1/T2/T3/T5/T6 与 `tests/test_project_workspace.py` 的 Git 忽略用例，两文件共 43 个测试条目实测全通过）；真正依赖 `pipeline` 的 18 项用 `pytest.mark.skipif` 逐条具名跳过，理由写明「sparse-checkout 未检出 pipeline/」；`versioning/backup.py` 的 2 个豁免守卫改用 skip-worktree 探针区分「被 sparse-checkout 排除」（具名跳过）与「文件真丢失」（仍按原来的 `pytest.fail` 硬失败），因此硬失败守卫没有被放宽。实测默认 `pytest` 为 `717 passed, 20 skipped`、0 失败。仍存两点限制：（a）T3 的字面量扫描面在当前检出下只剩 `tests/` 的两个文件与根目录文件——`pipeline`/`versioning`/`finetune`/`delivery` 被 sparse-checkout 排除（HEAD 跟踪 116 个 `pipeline` 文件，磁盘上一个都没有），所以「旧布局字面量清零」的本机结论不等于全仓结论；同理 L6-08 在当前检出下没有可扫的备份模块，是通过但空转。（b）20 项跳过条目的断言本体（含 `tests/test_project_workspace.py` 里 12 处 `pytest.raises` 的 match 文案）在本机完全没有执行，只是计数可见，不等于已验证。要把这 20 项也真跑，需把 `/pipeline/`、`/versioning/` 加进 `git sparse-checkout` 白名单后重跑同一条命令，届时这些用例会自动转为执行。

4. **默认测试命令覆盖 8 个测试目录。** 默认范围实测收集 737 项，其中 717 项通过、20 项具名跳过、0 项失败；9 个测试目录中唯一不在默认范围的是 `script/subvideo_generation/tests`（337 项，需单独按需运行）。按实际执行数计算，默认覆盖 717/1074 ≈ 66.8%（1074 = 717 通过 + 20 跳过 + 337 未纳入默认范围）；子视频生成测试此前耗时超过 10 分钟仍未跑完，需要按需单独运行。

5. **划分清单与 ROI 清单里记录的文件指纹，没有任何程序回读比对。** 指纹分别写入 `script/data_split/generate.py:530` 和 `script/roi/core.py:416`；只有测试会比对，生产链路不检查。影响是输入换了、产物没换也没人发现；本次已实证：`data/splits/three-fold/manifest.json:256` 起的 12 项输入记录中，4 项与当前文件对不上（`docs_label.md`、`generate.py`、`labels.csv` 内容已变；`docs_data-split-design.md` 已改名为 `docs/split/data-split-design.md` 且内容亦变），另 6 个 `old_fold_*` 快照从未入库，一直没人发现。修它要在划分和 ROI 的入口程序里加入回读比对：每次读取清单时，先核对清单里记录的文件指纹是否与磁盘当前文件一致；不一致时拒绝继续或要求重新生成。修好之后，输入文件悄悄被替换、重命名或内容变更时，程序会停下来要求确认，不会继续用旧清单跑。（2026 年 11 月补记，仅作登记、不新增检查项也不改计数：ROI 清单记录的是绝对路径，读取逻辑已改为「存在即用、缺失则按显式项目根解析 `data`/`script`/`docs` 相对后缀、两者皆无则报错」；本机 110 条源/输出路径全部原样可用，重定位路径由 20 例合成测试覆盖（`script/roi/tests/test_manifest_paths.py`）。）

6. **所有检查都靠人记得去跑。** 仓库没有 `.github` 目录（无持续集成），没有 `.pre-commit-config.yaml`，Git 钩子目录里只有 `*.sample` 样例文件。影响是检查跑没跑、什么时候跑、跑的结果是什么，全凭个人记忆；时间一长必然漏跑，问题积累到审计时才暴露。修它至少要加一项持续集成配置，在每次推送/合并请求时跑默认测试；再配一个提交前钩子，拦截明显会破坏契约的变更；对耗时的子视频生成测试可以单独放到 nightly 或手动触发。修好之后，检查会变成常规动作而不是记忆负担，基础破坏在提交前或合并前就能被拦住。

## 5. 已经失守的能力

下面六项校验被删除后，一部分已恢复替代品，见最后一列；其余仍没有替代品。

| 已删除的校验 | 以前能防住什么 | 删除时间 | 现在有没有替代品 |
|---|---|---|---|
| `scripts/verify_design_facts.py`（1132 行） | `docs/facts.yaml` 每条证据的文件、行号、原文是否还对得上（现口径下行号只作提示） | 2026-11-14，提交 `4cd54fa` | `script/checks/facts.py`（已移植，按锚文本判定：`expect` 能否在文件中定位、行号只作提示、新增「歧义」类别；实测见第 4 节第 1 条） |
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
| L2-30 | 子视频生成 | 核验记录的清单摘要与批次清单对照；规则及写盘入口仍在，对象已随批次退役，当前无可查对象。 | `script/subvideo_generation/generate.py:925` | 新批次生成后对照记录与清单 | 孤儿 |
| L2-31 | 子视频生成 | 核验记录的运行摘要与批次身份对照；规则及写盘入口仍在，对象已随批次退役，当前无可查对象。 | `script/subvideo_generation/generate.py:925` | 新批次生成后核对运行摘要 | 孤儿 |
| L2-32 | 子视频生成 | 生成入口已具备审计记录写盘能力（`--write-audit` / `--replace-audit`，fail-closed + 原子写 + 显式覆盖 + 单锁临界区），有 29 例测试守住；旧批次已退役，当前无可查对象（见 L2-30、L2-31）。 | `script/subvideo_generation/generate.py:925`，写盘函数 `write_audit_record`；读取位置 `script/subvideo_review/server.py:154` | 显式执行 `--audit-only --write-audit`（覆盖需 `--replace-audit`），另有 29 例测试 | 绿 |

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
| L3-08 | 人工审核 | 标签组合待复核筛选规则仍在；对象已随批次退役，当前无可查对象。 | `script/subvideo_review/server.py:252`；`script/subvideo_review/README.md:11` | 新批次生成后审核页加载核验摘要 | 孤儿 |
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
| L5-01 | 文档与事实 | 证据 expect 原文可定位，本次实测通过 203 条（记录行命中 189、位置已变 14）；歧义 0 条。 | `script/checks/facts.py` | `--json` | 绿 |
| L5-02 | 文档与事实 | expect 在全文找不到 4 条；多处命中（歧义）0 条。 | `script/checks/facts.py` | `--json` | 红 |
| L5-03 | 文档与事实 | sparse-checkout 下 41 个受跟踪 Markdown 无法读取，尚不能判定路径。 | `script/checks/facts.py`；`script/checks/doc-path-allowlist.txt` | `--check-doc-paths` | 黄 |
| L5-04 | 文档与事实 | 49 条 state 合法；DF-044 的 affects 已修正，`structure_errors` 实测为 0。 | `script/checks/facts.py` | `--json` | 绿 |
| L5-05 | 文档与事实 | 移植版校验器的测试 87 项通过，提供五类汇总。 | `script/checks/facts.py` | pytest；默认模式 | 绿 |
| L5-06 | 文档与事实 | 移植版不含标题与锚点校验。 | `script/checks/facts.py` | 无 | 孤儿 |

### 仓库卫生层（L6）

| 编号 | 层 | 一句话说明 | 位置 | 触发方式 | 状态 |
|---|---|---|---|---|---|
| L6-01 | 仓库卫生 | 待搬迁清单必须是映射表的子集。 | `tests/test_layout_migration_guard.py:109` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-02 | 仓库卫生 | 旧布局的物理目录不能再存在。 | `tests/test_layout_migration_guard.py:118` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-03 | 仓库卫生 | 工作区根目录不能再存在。 | `tests/test_layout_migration_guard.py:129` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-04 | 仓库卫生 | 待搬迁清单必须保持为空。 | `tests/test_layout_migration_guard.py:142` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-05 | 仓库卫生 | 工作区内旧的 evaluations 路径不能再存在。 | `tests/test_layout_migration_guard.py:154` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-06 | 仓库卫生 | 扁平化后 evaluations 应在顶层。 | `tests/test_layout_migration_guard.py:167` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-07 | 仓库卫生 | 源码里不能有旧工作区路径字面量。 | `tests/test_layout_migration_guard.py:287` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-08 | 仓库卫生 | 例外标记只允许出现在备份模块。 | `tests/test_layout_migration_guard.py:310` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-09 | 仓库卫生 | 例外标记只能用于打包结构判断。 | `tests/test_layout_migration_guard.py:326` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `versioning/backup.py` | 黄 |
| L6-10 | 仓库卫生 | 例外标记数量不超过上限。 | `tests/test_layout_migration_guard.py:354` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `versioning/backup.py` | 黄 |
| L6-11 | 仓库卫生 | 源码里不能有旧基座模型路径字面量。 | `tests/test_layout_migration_guard.py:439` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-12 | 仓库卫生 | 旧基座路径探测能识别已知字面量。 | `tests/test_layout_migration_guard.py:453` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-13 | 仓库卫生 | 白名单条目仍只对应一行宿主代码。 | `tests/test_layout_migration_guard.py:505` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-14 | 仓库卫生 | 旧基座路径被抓、新路径放行的端到端检查。 | `tests/test_layout_migration_guard.py:547` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-15 | 仓库卫生 | 白名单条数不超过上限。 | `tests/test_layout_migration_guard.py:593` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-16 | 仓库卫生 | 工作区根目录就是仓库根目录。 | `tests/test_layout_migration_guard.py:611` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-17 | 仓库卫生 | 子项目不能嵌套在工作区里。 | `tests/test_layout_migration_guard.py:619` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-18 | 仓库卫生 | 子目录名符合扁平化布局。 | `tests/test_layout_migration_guard.py:639` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-19 | 仓库卫生 | 实验产物落在 trains 目录。 | `tests/test_layout_migration_guard.py:650` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-20 | 仓库卫生 | 扁平化产物未被 Git 跟踪。 | `tests/test_layout_migration_guard.py:661` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-21 | 仓库卫生 | 数据媒体与运行时锁文件未被 Git 跟踪。 | `tests/test_layout_migration_guard.py:688` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-22 | 仓库卫生 | 忽略规则覆盖扁平化路径。 | `tests/test_layout_migration_guard.py:710` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-23 | 仓库卫生 | 数据记录不被误忽略。 | `tests/test_layout_migration_guard.py:735` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-24 | 仓库卫生 | 各种视频格式被忽略。 | `tests/test_layout_migration_guard.py:749` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-25 | 仓库卫生 | 当前 v4.1 路径都在项目内。 | `tests/test_project_workspace.py:42` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-26 | 仓库卫生 | 重建时旧路径映射到隔离根目录。 | `tests/test_project_workspace.py:56` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-27 | 仓库卫生 | 错误根目录与路径逃逸被拒绝。 | `tests/test_project_workspace.py:74` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-28 | 仓库卫生 | 冻结的绝对路径被正确映射。 | `tests/test_project_workspace.py:90` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-29 | 仓库卫生 | 候选计划路径不带重建编号。 | `tests/test_project_workspace.py:106` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-30 | 仓库卫生 | 候选与审核路径都不带重建编号。 | `tests/test_project_workspace.py:121` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-31 | 仓库卫生 | 查看旧上下文只读且要求冻结根目录。 | `tests/test_project_workspace.py:147` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-32 | 仓库卫生 | 暂存创建的门与续跑身份。 | `tests/test_project_workspace.py:175` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-33 | 仓库卫生 | 续跑拒绝符号链接的根目录。 | `tests/test_project_workspace.py:210` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-34 | 仓库卫生 | 写入守卫拒绝旧根目录与版本化根目录。 | `tests/test_project_workspace.py:243` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-35 | 仓库卫生 | 语义化实验编号决定产物目录。 | `tests/test_project_workspace.py:280` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-36 | 仓库卫生 | 模块不暴露默认实验编号。 | `tests/test_project_workspace.py:301` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-37 | 仓库卫生 | 扁平化本地产物被 Git 忽略。 | `tests/test_project_workspace.py:305` | 默认 `pytest` 实跑通过（本次实测） | 绿 |
| L6-38 | 仓库卫生 | 工作区模块不依赖环境变量。 | `tests/test_project_workspace.py:331` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-39 | 仓库卫生 | 模型输出必须落在工作区 runs 下。 | `tests/test_project_workspace.py:344` | 默认 `pytest` 逐条具名跳过：sparse-checkout 未检出 `pipeline/` | 黄 |
| L6-40 | 仓库卫生 | 无持续集成（仓库无 `.github` 目录）。 | 当前不存在：仓库根目录无 `.github` | 无 | 孤儿 |
| L6-41 | 仓库卫生 | 无 `.pre-commit-config.yaml`。 | 当前不存在：仓库根目录无该文件 | 无 | 孤儿 |
| L6-42 | 仓库卫生 | Git 钩子目录只有 `*.sample` 样例（`git rev-parse --git-path hooks` 指向的目录）。 | 当前不存在：钩子目录仅含样例 | 无 | 孤儿 |
| L6-43 | 仓库卫生 | `tests/test_verify_design_facts.py`、`tests/test_serve_validate_delivery.py` 与 `tests/test_environment_deployment.py` 已从索引移除，磁盘上也没有。 | 当前不存在：索引和磁盘均无 | 无 | 孤儿 |

六层 20+32+16+17+6+43=134；绿 71、黄 52、红 1、孤儿 10。

## 7. 这份台账自己的失效条件

以下任一变化发生后，本台账需要重写：

- 新增或删除检查项，导致总数不再是 134。
- 测试目录或默认测试范围调整。
- `docs/facts.yaml` 的处理决定改变，或新批次清单与核验记录生成。
- 六层划分调整。
- `pipeline/` 或 `versioning/` 被检出后，当前逐条具名跳过的 20 项恢复运行，需重跑并更新第 2 节仓库卫生层计数与第 4 节第 3 条。
