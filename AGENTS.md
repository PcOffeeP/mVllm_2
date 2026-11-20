# Project Agent Instructions

## 工作区与主线分支

- `TensileAgent-Finetune` 工作区的长期主线分支为 `feat/tensileagent-finetune`，远程 PR 审查主战场为 `github`（`PcOffeeP/mVllm_2`，PR 流程基线 tag：`pr-workflow-baseline-20261120`）；`codeup` 仅在重要节点或定期同步备份。
- `main` 是原项目 `mVllm_2` 工作区的分支，不是本工作区的长期主线。不要仅凭共享仓库或分支名称将两者等同。
- 开始工作前先核对当前 worktree、分支、最新主线提交与 `sparse-checkout` 状态。

### Git 纪律

- **PR 审查流**：每个独立任务开始前先运行 `bash script/sync_and_clean.sh`（自动拉取最新 `github/feat/tensileagent-finetune`、同步主工作区并清理已合并的干净 `work/*` 残留），再从最新 `feat/tensileagent-finetune` 新建独立 worktree 与 `work/<线名>` 任务分支；在任务分支完成工作并跑通 1.4 节准入检查后，将 `work/<线名>` 推送到 `github` 并创建指向 `feat/tensileagent-finetune` 的 PR（`gh pr create --base feat/tensileagent-finetune`，按 `.github/PULL_REQUEST_TEMPLATE.md` 填写）。
- **权限红线**：允许 Agent 推送自己的 `work/*` 任务分支并创建/更新 PR；**严禁** push `feat/tensileagent-finetune` 或 `main`，**严禁**自行合并 PR，也不要再本地 `--ff-only` 直接合并回主线。
- **合并与自动清理**：PR 统一由用户在 GitHub 审查后以 **Create a merge commit** 合并，主线保留“任务信封”合并节点（`git log --first-parent` 一任务一行，展开可看分步提交）；远程 `work/*` 分支由 GitHub 仓库的 `Automatically delete head branches` 自动删除。
- **本地清理预授权**：对已完全合并进 `github/feat/tensileagent-finetune` 且工作树完全干净的本地 `work/*` 分支及对应 worktree，已永久预授权 Agent 通过 `bash script/sync_and_clean.sh` 自动清理，无需逐次请示；主线、未合并、含未提交改动或用途不明的分支严禁删除。

## 并行工作管理

### 1.1 一个工作线一个 worktree

- 新建工作线前先运行 `bash script/sync_and_clean.sh` 同步主线并顺手清理已合并的干净 `work/*` worktree 与分支；再使用 `git worktree add ../TensileAgent-Finetune-<线名> -b work/<线名>` 创建独立工作树（同一 worktree 内不得并行两个写入者）。
- 新建 worktree 后须核对 `git sparse-checkout list` 与主工作区一致（未检出 `pipeline/`、`versioning/`），避免多检出文件导致测试计数口径漂移。
- 每条线使用独立 `work/<线名>` 分支，完工跑通准入检查后推送到 `github` 并向 `feat/tensileagent-finetune` 提交 PR，由用户在 GitHub 审查后以 Create a merge commit 合并。
- 共享 worktree 会让各自的 `git status` 互相可见；一方执行 `git switch` 会连带改变另一方的工作树。

### 1.2 路径所有权表

| 所有权 | 路径 |
| --- | --- |
| 全局共享、默认只读 | `data/annotation-table-full.csv`、`data/splits/`、`data/roi/*.json`、`data/split-inputs/`、`data/videos/`、`data/roi/videos/` |
| 子视频线 | `data/sub_video/`、`data/subvideo-review/`、`docs/label.md`、`script/subvideo_generation/`、`script/subvideo_review/` |
| 虚拟数据线 | `data/virtual/`、`script/checks/virtual_dataset.py` |
| 检查体系线 | `script/checks/`、`docs/checks.md`、`docs/facts.yaml` |
| 共享文档（短事务，改完立即提交） | `docs/guide.md`、`README.md`、`docs/TODO.md` |

路径不重叠可任意并行；重叠时先声明者优先，另一方改用其他任务或等待。

### 1.3 变更窗口声明

仅针对全局共享只读项：动 `data/` 共享项前，先建 `docs/changes/<日期>-<工作线>-<对象>.md`，写明意图、涉及文件、时间窗口、备份位置、回滚方式；完成后追加「已完成 + 实际结果」；自「已完成」记录之日起保留 7 天，过期文件可直接删除，不归档。

### 1.4 准入检查（合并前必须跑）

```bash
.venv/bin/python -m pytest
.venv/bin/python -m script.checks.facts
```

pytest 须通过；facts 校验器的 `gone`／`ambiguous` 不得相对仓库内记录的基线新增，新增即须先修。当前基线为 `gone` 4、`ambiguous` 0；实测五类分布为证据 290、通过 206、`gone` 4、`ambiguous` 0、本机无法核对 80、结构错误 0，与 `docs/facts.yaml` 头部注释一致。残留的 4 条 `gone` 属既有问题（DF-022、DF-027，以及 DF-047 的两条），目标文件已不存在，仍待处理。

默认模式即使 `gone > 0` 也退出 0，退出码不代表准入通过，判据以基线对照为准。查看当前五类分布并与上述基线及 `docs/facts.yaml` 头部注释对照：

```bash
.venv/bin/python -m script.checks.facts --json | .venv/bin/python -c 'import json,sys; t=json.load(sys.stdin)["totals"]; print({k: t[k] for k in ("evidence","passed","gone","ambiguous","unverifiable","structure")})'
```

自动判断当前基线（不满足时退出非零）：

```bash
.venv/bin/python -m script.checks.facts --json | .venv/bin/python -c 'import json,sys; t=json.load(sys.stdin)["totals"]; print({k: t[k] for k in ("evidence","passed","gone","ambiguous","unverifiable","structure")}); sys.exit(not (t["gone"] <= 4 and t["ambiguous"] == 0))'
```

### 1.5 冲突处置

合并冲突由后到者解决，不得强推；发现他人未提交改动与自己重叠时，改为在自己的 worktree 里改同一文件、合并时人工取舍，不要直接编辑对方工作树。

### 1.6 明确禁止

- 不得因为「工作区有别人未提交的改动」就停手或要求对方停工——应改用独立 worktree 或选不重叠路径；
- 不得在共享 worktree 里 `git switch` 到自己的任务分支；
- 不得把备份目录建在仓库内。

## 项目资料

开始工作时，依次阅读 `docs/facts.yaml`、`docs/TODO.md` 和 `docs/guide.md`。

引用事实时核对其状态和适用范围。契约、代码与文档不一致时先报告冲突；区分直接证据和推断。

## 双机与结果证据

- 本机用于开发和轻量检查；
- 模型训练、GPU 推理、评测和长时间数据处理在训练机执行。使用训练机前核对其状态。

## 纪律

- 以实际运行的检查作为验收依据，说明来源、口径和覆盖范围；测试可被收集不等于测试通过。
- 新建文档写明失效条件；文档引用使用稳定标题或编号。权威操作文档的新增或整体重写须由不同 Agent 独立核查。
