# 变更窗口声明：训练机同步与旧批次归档

- 状态：同步与归档已完成；暂存副本已于 2026-11-20 删除，见 §8。
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

## 已完成

完成日期 2026-11-20。本声明保留期至 2026-11-27，期满可直接删除、不归档。

### 1. 同步

- 来源为 Mac 侧 `git archive --format=tar HEAD`（HEAD `d3168d9`）的 tar 流，经 SSH 解包到 `$R`，覆盖「涉及文件」所列八项路径；管道退出码 `PIPE_EXIT=0`。
- `script`：112 个文件，二级 `sha256` 为 `30b405bf2da1aaacb5510c1517ccae2fefd680e0a7c9638e0d0a174bd029a4a3`，与 Mac HEAD 一致。
- `script` 与 `docs` 共 262 个共有文件逐条比对哈希，差异 0 条，二级 `sha256` 为 `cd7bb42180d7281db3601575a61048c7ec3fdd5f52350c03285535385218bf09`。

### 2. 输入一致性

共核对 11 项，11/11 一致。

- `data/annotation-table-full.csv`：`c928bea3…1ec354c`。
- `data/splits/three-fold/manifest.json`：`1ad84afb…055f6ae2`；同目录 7 份成员逐个一致。
- `data/split-inputs/source-groups-20261107.json`：`a640cd71…6adaa7`。
- `data/roi/manifest.json`：`24b2dfa3…4dc6948b3`。

### 3. runbook 与复核记录

- 训练机 `docs/training-machine-review-runbook.md` 同步后含 `### 5.1`（审查前媒体同步）与新增的 `### 2.1 运行环境`，文件 `sha256` 与 Mac HEAD 一致。
- `data/subvideo-review/reviews.json` 未被覆盖：mtime 为 2026-11-15，早于本次操作窗口。

### 4. 备份

- 覆盖前备份位于训练机仓库外 `~/pi-workspace-backup/tensile-20261120/`，共 205 个文件、约 7.1M，含 `pre-sync-sha256.txt`。

### 5. 旧批次归档

- 移入 `~/pi-workspace-backup/tensile-20261120/sub_video-retired-20261108/` 的 4 个文件：`data/sub_video/manifest.json` 10511341 B、`data/sub_video/summary.json` 4820 B、`data/sub_video-plan/manifest.json` 22057123 B、`data/sub_video-plan/summary.json` 4697 B，合计 32577981 B。
- 迁移前后逐文件 `sha256` 清单一致；归档后 `$R/data/sub_video` 只余空目录 `videos/`。本阶段只归档、未删除。

### 6. 范围例外：补同步 `data/roi/decisions.json`

- 训练机此前从未有过该文件（不是本轮删除），故原计划将其排除在八项路径之外；随后按单独授权补同步此一个文件，未覆盖训练机任何既有内容。
- 方式同为 `git archive --format=tar HEAD data/roi/decisions.json` 经 SSH 解包，管道退出码 0。
- 两端 `sha256` 均为 `58cbb6ca8d086fda1c34d27b4c9ca4c7ac3bb139304115ddf2779192ea4a9e74`，文件 169902 B。
- 同步前后 `$R/data/` 下其余文件的 mtime 与大小均未变化，新增项仅此一个文件。

### 7. 遗留事实

- 训练机 `$R` 不是 git 仓库（为同步副本目录，无 `.git`），训练机侧状态核对以 `sha256` 与 `data/` 下 mtime/大小快照为准，不使用 git 校验；「与 Git HEAD 一致」指按 Mac HEAD 的文件集合与哈希比对。
- 归档暂存副本 `sub_video-retired-20261108/` 已于 2026-11-20 删除，见 §8。
- 后续若在训练机运行 ROI 裁剪工具，依赖 `data/roi/decisions.json`（已补同步）与 `data/roi/manifest.json`。

### 8. 暂存副本删除（2026-11-20）

新批次已生成，已按 runbook §5.1 回传本机，全量哈希核对通过（1,633/1,633）；用户已合并 PR #2，「正式准备开审」条件达成。唯一删除的目录是 `/home/liuyang/pi-workspace-backup/tensile-20261120/sub_video-retired-20261108/`，其中两个子目录的文件如下：

| 相对路径 | 字节数（B） | SHA-256 |
| --- | ---: | --- |
| `sub_video/manifest.json` | 10,511,341 | `6112f40df0ee2d50c334f6800cd4988dc2b572185801e9b18e35e7fcd5d746d1` |
| `sub_video/summary.json` | 4,820 | `28e715288f4f50bb5ee21e037da1c73d64afae9bf5f68274442b405fc1449b22` |
| `sub_video-plan/manifest.json` | 22,057,123 | `d3076c91c731cd5001de072457aecf49415cd68e8f3305544d4ade7cac8e2cd3` |
| `sub_video-plan/summary.json` | 4,697 | `1390cfd5fb2f9d7ab66a878ef2b1e2939f704208608515a904166d1f34d2596f` |

四个文件合计 32,577,981 B，删除后无法恢复。旧批次（1,621 个候选）与新批次（1,633 个候选）无关。删除后核对：训练机 `$R/data/sub_video/` 的 `manifest.json`（10,549,279 B）、`summary.json`（4,820 B）、`audit.json`（14,280 B）和 `videos/` 中的 1,633 个 mp4（合计 191,625,749 B）仍在，删除的是归档副本。

`~/pi-workspace-backup/tensile-20261120/` 下的 `pre-sync-sha256.txt` 与同步备份目录（`data/`、`docs/`、`script/`、`logs/`），以及迁移前后的两份 sha256 清单均未删除。
