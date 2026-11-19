# 变更窗口声明：重标注定稿与开发三折重跑

- 状态：执行中，见文末「已完成 + 实际结果」
- 工作线：`work/annotate-relabel-20261119`
- 时间窗口：2026-11-19 单次连续窗口（本次执行）；窗口内 `data/annotation-table-full.csv` 与 `data/splits/three-fold/` 只由本工作线写入
- 触发：用户 2026-11-19 完成重标注定稿，`data/annotation-table-full.csv` 共 6 处字段变更，划分输入字节随之变化，需按新字节重跑开发三折；`test.json` 不重生成。

## 涉及文件

| 文件 | 动作 |
| --- | --- |
| `data/annotation-table-full.csv` | 用户重标注 5 处字段 + 按用户口径把 `video_0040` 的 `断裂模式` 由「脆性断裂」改为「半脆半韧断裂」，合计 6 处字段变更 |
| `data/splits/three-fold/` | 8 个文件重跑后整体替换（6 个 train/val + `test.json` 字节不变 + `manifest.json`） |
| `data/split-inputs/source-groups-20261107.json` | 仅更新 `provenance.label_csv_sha256` 为新 CSV 的 SHA-256，分组内容不变 |

## 备份位置

- `~/pi-workspace/annotation-backup/`：CSV 三个版本（HEAD 版、用户中间版、改后最终版）
- `~/pi-workspace/splits-backup/three-fold-<时间戳>/`：替换前 `data/splits/three-fold/` 的 8 个文件

## 回滚方式

1. 还原 CSV：用 `~/pi-workspace/annotation-backup/` 中目标版本的整份副本覆盖 `data/annotation-table-full.csv`；
2. 还原划分：用 `~/pi-workspace/splits-backup/three-fold-<时间戳>/` 中 8 个文件覆盖 `data/splits/three-fold/`；
3. 把 `data/split-inputs/source-groups-20261107.json` 的 `provenance.label_csv_sha256` 退回旧值（旧值 `9970d259e14e6321eea76282b6a206b5b907527101736fe28d3c437387fa8d81`）；
4. 复核：`git status --porcelain` 干净、各文件 SHA-256 与回滚目标一致。

## 已完成 + 实际结果

（待补）
