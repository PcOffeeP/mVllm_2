<!-- DOCUMENT-CONTRACT
Purpose: 记录 2026-10-21 项目本地布局扁平化（取消 `workspace/` 根段）的映射表、本阶段改动范围、尚未执行的 P2 物理搬迁清单，以及阅读历史记录时的换算规则。
Scope: 仅覆盖 checkout 根下的项目本地目录及 `workspace/` 段的去留；不涉及 versioning store 的内部结构，也不涉及 `.compat/workspace` 与 `store/workspace/**`。
Must Preserve:
- 映射表是旧路径→新路径的唯一依据；发现映射与实际不一致时先报冲突，不得按记忆临时改写。
- 必须写明「本阶段未做物理搬迁」，不得表述成搬迁已完成。
- 必须写明历史记录（冻结快照与历史计划）保留旧路径原文，不得回改。
- 本文与其它文档互相引用一律用标题或条目定位，不写行号。
失效条件: P2 物理搬迁完成且新布局登记进 `docs/design-facts.yaml` 后，本文内容并入 design-facts 或直接删除，二者必居其一；不得长期滞留。
Non-goals:
- 不记录本批 commit 明细（见 `docs/project-todo.md` 的 LAYOUT-FLATTEN 条目）。
- 不重复代码、测试实现细节与操作命令。
-->

# 项目本地布局扁平化（2026-10-21）

用户 2026-10-21 决定彻底拆掉 `workspace/` 目录，把内容搬到顶层语义目录。本文是这次布局变更的唯一映射依据，也是「今天还按哪套路径操作」的现状说明。

## 本文何时作废

P2 物理搬迁完成且新布局登记进 `docs/design-facts.yaml` 之后，本文内容并入 design-facts 或直接删除；到期不处理即违反本文件契约。除此之外的情形（例如只补一条映射、只补一个遗留项）属于就地更新，不构成作废。

## 1. 映射表（唯一依据）

| 旧 | 新 |
|---|---|
| `workspace/data` | `data` |
| `workspace/runs` | `trains` |
| `workspace/models` | `models` |
| `workspace/mlflow` | `mlflow` |
| `workspace/evaluations` | `evaluations`（含 `staging/`） |
| `workspace/base-source-audit` | `audits/base-source-audit` |
| `workspace/review-environment` | `audits/review-environment` |
| `workspace/data-staging` | `data-staging` |
| `workspace/data-rebuild` | `data-rebuild` |
| `models/minicpmv4_5` / `models/minicpm-v-4.5`（基座） | `base-models/minicpmv4_5` |
| `.compat/workspace`、`store/workspace/**` | 不动（不属于本次映射，store 域是独立命名空间） |

## 2. 本阶段做了什么

- 只改代码、配置、测试与 `.gitignore`：路径层不再拼接 `workspace/` 段，项目根即 workspace 根；`.gitignore` 以 `/data`、`/trains`、`/base-models`、`/mlflow`、`/evaluations`、`/audits`、`/data-staging`、`/data-rebuild` 取代 `/workspace/`，并删除失效的 `/data/` 家族子规则；`models/*` 保持原样（它只排除子项，目录本身可跟踪）。除这 8 条新规则外，`.gitignore` **另保留一条 `/workspace/` 临时忽略**（注释已写明用途）：P2 物理搬迁前该目录仍在磁盘上，删掉该行会让残留产物变成未跟踪文件；P2 删除目录后连该行一并删除。
- **未做物理搬迁**：`workspace/` 目录仍在磁盘上，本机现含 `base-source-audit/`、`mlflow/`、`review-environment/`、`runs/`；`models/` 下仍是 `minicpm-v-4.5` 基座。
- **验证限制（P2 前，审查 Finding #4）**：`versioning/migration.py` 的 legacy 常量已按 P2 后的落点书写——`_LEGACY_DATA_RELEASES` 为 `data/releases`、`_PREPARE_ONLY_RUN_SOURCE_ROOT` 为 `trains`、模型侧取 `models/releases/<模型名>`。P2 物理搬迁完成前，`workspace/` 下的旧源仍在原处，在训练机上跑 migration / backup restore 相关入口会因旧源路径缺失而 fail-closed；这些入口在 P2 前的输出一律视为**未验证**，不得据此声称迁移或恢复可用。P2 搬迁完成后须在训练机重跑并按结果更新本段。
- 现行操作文档改指新路径；历史证据快照（`docs/results/**` 与 `records/r1-run-20261018/**`）与历史计划（`docs/plans/**`）零改动。

## 3. 尚未做：P2 物理搬迁清单

本机 checkout 的现状与训练机不同，下表按「旧目录 → 新目录」列出待搬对象；不存在于本机的项须在训练机核对后执行。

1. `workspace/data` → `data`
2. `workspace/runs` → `trains`
3. `workspace/models` → `models`
4. `workspace/mlflow` → `mlflow`
5. `workspace/evaluations`（含 `staging/`）→ `evaluations`
6. `workspace/base-source-audit` → `audits/base-source-audit`
7. `workspace/review-environment` → `audits/review-environment`
8. `workspace/data-staging` → `data-staging`
9. `workspace/data-rebuild` → `data-rebuild`
10. `models/minicpm-v-4.5` → `base-models/minicpmv4_5`
11. 清理空的 `workspace/` 目录本身
12. 搬迁后跑布局守卫测试 T1/T2（`tests/test_layout_migration_guard.py`），并同步清空该文件的 PENDING_PHYSICAL_MOVE 集合

搬迁前必须确认两端 Git 状态、未提交改动与产物唯一副本，违反「删除先列清单并取得授权」纪律的操作一律不得执行。

## 4. 阅读历史记录时的换算

`docs/results/**`、`records/r1-run-20261018/**` 与 `docs/plans/**` 是冻结快照与历史计划，仍按旧布局书写，**不得回改**。阅读这些记录时按下表换算：遇到 `workspace/<子目录>` 直接替换为映射表对应项。

带日期的实测记录（例如 2026-10-18 训练机 `du` 体量、2026-10-19 逐帧核验）描述的是当时的磁盘状态，换算只用于理解「那批产物现在该在哪」，不能据此声称目录已经在新位置。

## 5. 引用约定

本文与其它文档相互引用一律使用标题、条目名或稳定关键词定位，不写行号：行号会在每次插入后整体位移，而现有校验只判路径存在性、不判行号。

## 6. 相关入口

- 忽略规则：`.gitignore` 顶部的「项目本地产物」块（含 `/xxx` 不带尾斜杠的原因说明）。
- 布局守卫：`tests/test_layout_migration_guard.py`（T1 旧路径、T2 evaluations、T3 源码字面量、T4 路径语义、T5 跟踪状态、T6 忽略覆盖）。
- 台账条目：`docs/project-todo.md` 的 LAYOUT-FLATTEN 及本批登记的遗留项。
