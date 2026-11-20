# 变更窗口声明：训练机同步与旧批次归档

- 状态：进行中
- 时间窗口：自 2026-11-20 起，完成同步、归档及核验后结束。
- 动因：重标注与三折重跑后，训练机的 `script/` 落后 22 个文件且缺少 `--write-audit`，`docs/` 中 runbook 缺 §5.1，输入数据（标注表、6 个 fold 文件、`source-groups`、`roi/manifest.json`）均非当前版本。

## 涉及文件

来源为 Mac 侧 `git archive HEAD` 生成的 tar 流，经 SSH 解包到训练机仓库 `/home/liuyang/文档/TensileAgent-Finetune`（下称 `$R`），只覆盖以下路径，其余一律不动：

```text
script
docs
AGENTS.md
pyproject.toml
data/annotation-table-full.csv
data/splits/three-fold
data/split-inputs/source-groups-20261107.json
data/roi/manifest.json
```

在 Mac 项目根执行的命令形态如下，远端路径含中文，使用引号保护：

```bash
R='/home/liuyang/文档/TensileAgent-Finetune'
git archive --format=tar HEAD script docs AGENTS.md pyproject.toml data/annotation-table-full.csv data/splits/three-fold data/split-inputs/source-groups-20261107.json data/roi/manifest.json | ssh liuyang@100.70.83.68 'tar -xf - -C "'"$R"'"'
```

不同步 `data/roi/decisions.json`、`data/subvideo-review/reviews.json`，以避免覆盖训练机上可能更新的复核记录；不同步任何媒体文件。本批次经授权采用 `git archive HEAD | ssh … tar` 的目录解包方式同步，作为 runbook §5 的一次性例外，同时适用于 §5 的逐文件 `rsync` 方式限制及禁止从本机向训练机写入或覆盖 `data/` 下任何文件的禁令。例外范围仅限上述八项路径，其中 `data/` 例外仅限 `data/annotation-table-full.csv`、`data/splits/three-fold/`、`data/split-inputs/source-groups-20261107.json`、`data/roi/manifest.json` 四项输入；`data/roi/decisions.json`、`data/subvideo-review/reviews.json`、任何媒体文件及其他路径仍禁止写入，其他批次不适用本例外。例外边界以本声明为准，不通过修改 runbook §5 正文实现。

旧批次归档计划：将 `$R/data/sub_video/manifest.json`、`$R/data/sub_video/summary.json` 和 `$R/data/sub_video-plan/` 下的清单与摘要移动到训练机仓库外暂存目录 `~/pi-workspace-backup/tensile-20261120/sub_video-retired-20261108/`；媒体此前已删。本阶段只归档不删除；仅在新批次生成完成、已按 runbook §5.1 回传本机并通过全量哈希核对、正式准备开审时，才删除暂存副本。

## 备份位置

覆盖前将所有将被覆盖的内容备份到训练机仓库外 `~/pi-workspace-backup/tensile-20261120/`，保留原相对路径。本声明自「已完成」记录之日起保留 7 天，期满可直接删除，不归档。

## 回滚方式

将备份目录内容复制回原位，并逐文件按 `sha256` 核对恢复内容与备份一致；归档的旧批次清单与摘要从暂存目录复制回原位并核对 `sha256`。

## 验证方式

旧批次归档逐文件核对迁移前后 `sha256` 一致；同步内容逐文件比对 Mac 与训练机两端 `sha256`。训练机 `script`、`docs` 与 Git HEAD 的文件集合和二级 `sha256` 均须一致；多余文件只登记不删除。
