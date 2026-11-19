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

### 结果数字

- CSV：6 处字段变更落地，22452 → 22458 字节（+6），BOM 与全 CRLF 保持，111 行 × 28 列不变；改后 SHA-256 `c928bea3d769eb16ad55ed7d872a877a3b4fd327d0af5422bc2bb682c1ec354c`（提交 `51d647d`）。`断裂模式` 分布现为：韧性断裂 50、半脆半韧断裂 21、脆性断裂 20、无法判断 15、无 4。
- 划分：`test.json` 逐字节未变（`26fc3070662b8ac2c8683a50bd8dea9c78a96162ad5e4c0e83a6afc454c7d8dc`，21 条）。重跑后开发集 89 条：fold_0 train 59 / val 30、fold_1 train 59 / val 30、fold_2 train 60 / val 29。新 `manifest.json` SHA-256 `1ad84afb9a9eb122d6d7cdc13b78a975567a51667eaeacfabd5748c1055f6ae2`，`rule_version` = `explicit-source-five-task-v1`，`code_commit` = `51d647d`，`status` = `generated_split_not_model_evaluation`，`search_summary.best_seed` = 53。
- 与改前划分对比：三折 val 增删合计 80 条（fold_0 增 12 / 删 11，fold_1 增 17 / 删 17，fold_2 增 11 / 删 12），涉及换折的开发集视频 40 个；每折 train 变化数与 val 互补。
- 来源指纹：`data/split-inputs/source-groups-20261107.json` 的 `provenance.label_csv_sha256` 由 `9970d259…fa8d81` 改为 `c928bea3…c1ec354c`，分组内容未变；该文件 SHA-256 `ce96febf1a41a15a4ecc9eba0e1256ebc5c7105f15c01c22afbca80130dde28b` → `a640cd71746f508f9e904208a699b68391b54c2c5c0acb9a9ced19b0c46adaa7`（10983 字节不变，只差 1 行 1 值）。
- 已知差异：生成器产出的新 `manifest.json` 没有旧 manifest 的 `migration` 键；`inputs` 中的 6 项 `old_fold_*` 记录的是替换前的旧折指纹（可从 git 历史 `51d647d` 复核），替换后这些路径下的文件已变为新划分。`warnings` 三项：`explicit_source_table_is_user_evidence_not_media_deduplication`、`historically_exposed_test_is_not_never_used_independent_test`、`bounded_local_search_does_not_prove_global_optimality`。
