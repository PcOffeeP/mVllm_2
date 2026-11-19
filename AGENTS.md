# Project Agent Instructions

## 工作区与主线分支

- `TensileAgent-Finetune` 工作区的长期主线分支为 `feat/tensileagent-finetune`。开始工作和合并前核对当前 worktree、分支与提交；任务分支仍按下方规则从当前工作分支创建并合并回原工作分支。
- `main` 是原项目 `mVllm_2` 工作区的分支，不是本工作区的长期主线。不要仅凭共享仓库或分支名称将两者等同；向主线合并及推送仍需用户授权。

### Git 纪律

- 每个独立的小任务先从当前工作分支新建任务分支，在任务分支完成对应工作并提交，核对提交和目标分支后合并回原工作分支；达到合并条件后，向用户获取授权，然后合并。**严禁**私自 push。
- 定期核对本地短期分支与各 worktree 的状态；
- worktree 合并后，在已获删除授权的范围内清理 worktree 及其使用的短期分支。
- 保留主线、未合并或用途不明的分支；

## 并行工作管理

### 1.1 一个工作线一个 worktree

- 新工作线使用 `git worktree add ../TensileAgent-Finetune-<线名> -b work/<线名>`；同一 worktree 内不得并行两个写入者。
- 每条线使用独立分支，完工后以 `git merge --ff-only` 合并回本工作区长期主线分支 `feat/tensileagent-finetune`，以「工作区与主线分支」小节为准，并遵守合并授权要求。
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

仅针对全局共享只读项：动 `data/` 共享项前，先建 `docs/changes/<日期>-<工作线>-<对象>.md`，写明意图、涉及文件、时间窗口、备份位置、回滚方式；完成后追加「已完成 + 实际结果」；过期文件可直接删除，不归档。

### 1.4 准入检查（合并前必须跑）

```bash
.venv/bin/python -m pytest
.venv/bin/python -m script.checks.facts
```

pytest 须通过；facts 校验器的 `gone`／`ambiguous` 不得相对仓库内记录的基线新增，新增即须先修。当前基线为 `gone` 14、`ambiguous` 0；`docs/facts.yaml` 头部注释记录的历史五类分布基线为 `gone` 4、`ambiguous` 0。差额中 6 条因 2026-11-19 退役已作废批次清单、4 条因删除 `docs/eval-migration-plan.md`，目标文件已不存在，均为待处理项；修好后应回落到 `gone` 4。

查看当前五类分布并与上述基线及 `docs/facts.yaml` 头部注释对照：

```bash
.venv/bin/python -m script.checks.facts --json | .venv/bin/python -c 'import json,sys; t=json.load(sys.stdin)["totals"]; print({k: t[k] for k in ("evidence","passed","gone","ambiguous","unverifiable","structure")})'
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
