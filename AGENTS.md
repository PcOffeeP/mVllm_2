# Project Agent Instructions

> 本文件分为两部分：**第一部分「项目不变量与验收红线」**适用于本项目所有 Agent（含只读子 Agent / `reviewer`）；**第二部分「主 Agent 工作流」**仅适用于负责推进任务的主 Agent，子 Agent 仅按 brief 边界行动，不执行主 Agent 起手流程。

---

## 一、项目不变量与验收红线（所有 Agent 共享）

### 1. 工作区、分支与远程边界

- `TensileAgent-Finetune` 工作区的长期主线分支为 `feat/tensileagent-finetune`，远程 PR 审查主战场为 `github`（`PcOffeeP/mVllm_2`，PR 流程基线 tag：`pr-workflow-baseline-20261120`）；`codeup` 仅在重要节点或定期同步备份。
- `main` 是原项目 `mVllm_2` 工作区的分支，不是本工作区的长期主线。不要仅凭共享仓库或分支名称将两者等同。
- **权限红线**：允许 Agent 推送自己的 `work/*` 任务分支并创建/更新 PR；**严禁** push `feat/tensileagent-finetune` 或 `main`，**严禁**自行合并 PR，也不要再本地 `--ff-only` 直接合并回主线。
- **sparse-checkout 口径**：本工作区未检出 `pipeline/`、`versioning/`，新建 worktree 后须核对 `git sparse-checkout list` 与主工作区一致，避免多检出文件导致测试计数口径漂移。
- 不得把备份目录建在仓库内。

### 2. 路径所有权表与变更窗口声明

| 所有权 | 路径 |
| --- | --- |
| 全局共享、默认只读 | `data/annotation-table-full.csv`、`data/splits/`、`data/roi/*.json`、`data/split-inputs/`、`data/videos/`、`data/roi/videos/` |
| 子视频线 | `data/sub_video/`、`data/subvideo-review/`、`docs/label.md`、`script/subvideo_generation/`、`script/subvideo_review/` |
| 虚拟数据线 | `data/virtual/`、`script/checks/virtual_dataset.py` |
| 检查体系线 | `script/checks/`、`docs/checks.md`、`docs/facts.yaml` |
| 共享文档（短事务，改完立即提交） | `docs/guide.md`、`README.md`、`docs/TODO.md` |

- **变更窗口声明（Draft PR 占坑机制）**：仅针对全局共享只读项（及训练机/未入库共享媒体目录）：
  1. **开工前探针**：动共享项前先运行 `gh pr list --state open --json number,headRefName,title,isDraft,labels,files`，确认没有其他在途 PR（含 Draft PR）正在修改同一共享资源；若已有在途 PR 占坑，须等待其合并或关闭后再动手，不得并发写入或基于过期数据启动高成本下游任务；
  2. **先占坑再干活（Draft PR）**：确认空闲后，先在自己的 `work/*` 分支新建 `docs/changes/<日期>-<工作线>-<对象>.md`（写明意图、涉及文件/资源、时间窗口、备份位置、回滚方式），立刻提交推送并创建 **Draft PR** 占坑（Draft 状态下合并按钮锁死，同时跨 worktree、跨 Agent、跨本机/训练机实时可见）：
     ```bash
     git push -u github work/<线名>
     gh pr create --draft --base feat/tensileagent-finetune --title "wip(lock): <简述>" --body-file docs/changes/<日期>-<工作线>-<对象>.md
     ```
  3. **完工转正与保留期**：完成后在同一分支追加实际改动与「已完成 + 实际结果」并推送，先按 `.github/PULL_REQUEST_TEMPLATE.md` 更新正式标题与 PR 正文（`gh pr edit --title "<正式标题>" --body-file <PR正文文件>`，去掉 `wip(lock):` 前缀以满足 `pr-template-check`），再执行 `gh pr ready` 转为 Ready for review；PR 合并或关闭后占坑自动释放。变更单自「已完成」记录之日起保留 7 天，过期文件可直接删除，不归档。

### 3. 准入检查与基线标准（合并前必须跑）

```bash
.venv/bin/python -m pytest
.venv/bin/python -m script.checks.facts
```

- `pytest` 须通过；`facts` 校验器的 `gone`／`ambiguous` 不得相对仓库内记录的基线新增，新增即须先修。当前基线为 `gone` 0、`ambiguous` 0；当前实测五类分布为证据 294、通过 214（记录行命中 165、位置已变 49）、`gone` 0、`ambiguous` 0、本机无法核对 80、结构错误 0，与 `docs/facts.yaml` 头部注释一致。此前残留的 4 条 `gone`（DF-022、DF-027、DF-047 的两条）已于 2026-11-21 重指向改写后的原句，现无残留。
- 默认模式即使 `gone > 0` 也退出 0，退出码不代表准入通过，判据以基线对照为准。查看当前五类分布或自动判断当前基线（不满足时退出非零）：

```bash
.venv/bin/python -m script.checks.facts --json | .venv/bin/python -c 'import json,sys; t=json.load(sys.stdin)["totals"]; print({k: t[k] for k in ("evidence","passed","gone","ambiguous","unverifiable","structure")})'
.venv/bin/python -m script.checks.facts --json | .venv/bin/python -c 'import json,sys; t=json.load(sys.stdin)["totals"]; print({k: t[k] for k in ("evidence","passed","gone","ambiguous","unverifiable","structure")}); sys.exit(not (t["gone"] <= 0 and t["ambiguous"] == 0))'
```

### 4. 双机边界与结果纪律

- 本机用于开发和轻量检查；模型训练、GPU 推理、评测和长时间数据处理在训练机执行。使用训练机前核对其状态。
- 引用事实时核对其状态和适用范围。契约、代码与文档不一致时先报告冲突；区分直接证据和推断。
- 以实际运行的检查作为验收依据，说明来源、口径和覆盖范围；测试可被收集不等于测试通过。
- 新建文档写明失效条件；文档引用使用稳定标题或编号。权威操作文档的新增或整体重写须由不同 Agent 独立核查。

---

## 二、主 Agent 工作流（仅主 Agent 执行）

### 1. 开工准备与项目资料

- 主 Agent 接手新任务时，先核对当前 worktree、分支、最新主线提交与 `sparse-checkout` 状态，并依次阅读 `docs/facts.yaml`、`docs/TODO.md` 和 `docs/guide.md`。

### 2. PR 审查流与独立 worktree

- 每个独立任务开始前先运行 `bash script/sync_and_clean.sh`（自动拉取最新 `github/feat/tensileagent-finetune`、同步主工作区并清理已合并的干净 `work/*` 残留），再使用 `git worktree add --no-track ../TensileAgent-Finetune-<线名> -b work/<线名> github/feat/tensileagent-finetune` 创建独立工作树（同一 worktree 内不得并行两个写入者）。
- 在任务分支完成工作并跑通准入检查后，将 `work/<线名>` 推送到 `github` 并创建指向 `feat/tensileagent-finetune` 的 PR（`gh pr create --base feat/tensileagent-finetune`，按 `.github/PULL_REQUEST_TEMPLATE.md` 填写）。
- **合并与自动清理**：PR 统一由用户在 GitHub 审查后以 **Create a merge commit** 合并，主线保留“任务信封”合并节点（`git log --first-parent` 一任务一行，展开可看分步提交）；远程 `work/*` 分支由 GitHub 仓库的 `Automatically delete head branches` 自动删除。
- **本地清理预授权**：对已完全合并进 `github/feat/tensileagent-finetune` 且工作树完全干净的本地 `work/*` 分支及对应 worktree，已永久预授权 Agent 通过 `bash script/sync_and_clean.sh` 自动清理，无需逐次请示；主线、未合并、含未提交改动或用途不明的分支严禁删除。

### 3. 并行冲突与禁止事项

- 路径不重叠可任意并行；重叠时先声明者优先，另一方改用其他任务或等待。
- 合并冲突由后到者解决，不得强推；发现他人未提交改动与自己重叠时，改为在自己的 worktree 里改同一文件、合并时人工取舍，不要直接编辑对方工作树。
- 共享 worktree 会让各自的 `git status` 互相可见；一方执行 `git switch` 会连带改变另一方的工作树。
- **明确禁止**：
  - 不得因为「工作区有别人未提交的改动」就停手或要求对方停工——应改用独立 worktree 或选不重叠路径；
  - 不得在共享 worktree 里 `git switch` 到自己的任务分支。
