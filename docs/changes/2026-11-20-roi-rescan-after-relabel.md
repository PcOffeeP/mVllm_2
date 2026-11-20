# 变更窗口声明：重标注后重扫 ROI 清单

- 状态：已完成
- 时间窗口：自 2026-11-20 起，重扫及核验完成后结束。
- 动因：源标注重标注定稿且开发三折重跑后，ROI 清单中的划分摘要、逐视频折归属和标注快照已陈旧，需要重扫刷新。

## 涉及文件

仅 `data/roi/manifest.json`。

不重新生成或删除任何 ROI 视频；不修改 `data/roi/decisions.json`、`data/annotation-table-full.csv` 或 `data/splits/three-fold/` 中任何文件。

## 备份位置

- `/Users/pcoffeep/pi-workspace/tensile-finetune/backup/roi-manifest-20261120-1029.json`
- SHA-256：`de202f2091d00acf34b4e6a3a774cb3fc410ff203b841e1aa1ab6a1a893a2ad8`
- 本声明自「已完成」记录之日起保留 7 天，期满失效。

## 回滚方式

用上述备份文件覆盖 `data/roi/manifest.json`，并核对恢复文件的 SHA-256 与备份一致。

## 验证方式

重扫后逐条核对 7 份划分文件摘要、110 条逐视频 `split.folds`、逐视频 `labels` 与当前输入一致。

## 已完成 + 实际结果

- 扫描退出码 0，仅扫描，未生成视频。
- 旧 manifest：SHA-256 `de202f2091d00acf34b4e6a3a774cb3fc410ff203b841e1aa1ab6a1a893a2ad8`，1,453,872 字节，`generated_at` 为 `2026-11-08T13:20:20.164007+00:00`。
- 新 manifest：SHA-256 `24b2dfa3019462dbef27fc00314901d30ad308802a458b31d95a90e4dc6948b3`，1,453,938 字节，`generated_at` 为 `2026-11-20T02:31:08.422369+00:00`。
- 7 份划分摘要与磁盘一致（7/7，含 test.json）；按 train/val 及 test 重建的逐视频 folds 和分区一致（110/110）；CSV 全部 28 列与逐视频 labels 一致（110/110，键集合无差异）。
- 断裂模式分布（旧 → 新）：脆性断裂 21 → 20；半脆半韧断裂 20 → 21；无法确定 15 → 0、无法判断 0 → 15；韧性断裂 50 → 50；无 4 → 4。
- 新旧清单顶层和逐视频记录键集合无差异；除划分摘要、folds、labels 外，仅 `generated_at` 值发生变化，`output` 未变。110 条视频状态均为 `success`。
- `data/roi/decisions.json` SHA-256 前后均为 `58cbb6ca8d086fda1c34d27b4c9ca4c7ac3bb139304115ddf2779192ea4a9e74`。
- 扫描前后 `data/roi` 文件数均为 113、`data/roi/videos` 中 mp4 数均为 110、`du -sk data/roi` 均为 148488 KiB。`du` 为磁盘占用，不是逻辑字节总数；manifest 逻辑大小增加 66 字节。
- ROI 回归命令：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider script/roi/tests`；结果行：`181 passed, 60 warnings in 31.10s`。警告为 pytest 清理临时目录时目录非空。
