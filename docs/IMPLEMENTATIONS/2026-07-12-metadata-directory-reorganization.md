# data/07_metadata 目录结构重组

**日期**：2026-07-12（最新修订 2026-07-13）  
**变更类型**：目录结构整理 + 硬编码路径同步更新

## 1. 变更原因

将 `data/07_metadata/` 中按轮次/用途区分的中间产物集中放到 `incremental_review/round_01/`，
把全量人工基线决策单独归档到 `review_decisions/`，而让最终交付物和原数据保持顶层直观，
减少使用时查找路径的嵌套深度。

## 2. 最终目录结构

```
data/07_metadata/
├── video_meta.json
├── test_manifest_sha256.json
├── subvideos_meta.json
├── subvideo_train_review_decisions_final.json
├── review_decisions/
│   └── subvideo_train_review_decisions.json
└── incremental_review/
    └── round_01/
        ├── incremental_review_queue.csv
        ├── incremental_review_queue_metadata.json
        ├── incremental_review_round_01_metadata.json
        ├── incremental_review_round_01_report.json
        ├── incremental_review_delta_decisions.json
        └── incremental_review_delta_decisions_resolved.json
```

## 3. 实际变更内容

本次改动仅为路径整理，未修改任何脚本逻辑、未修改任何 JSON 数据内容、未删除任何文件。

已移动/重命名的文件：

| 新位置 |
|---|
| `data/07_metadata/video_meta.json` |
| `data/07_metadata/test_manifest_sha256.json` |
| `data/07_metadata/subvideos_meta.json` |
| `data/07_metadata/subvideo_train_review_decisions_final.json` |
| `data/07_metadata/review_decisions/subvideo_train_review_decisions.json` |
| `data/07_metadata/incremental_review/round_01/incremental_review_queue.csv` |
| `data/07_metadata/incremental_review/round_01/incremental_review_queue_metadata.json` |
| `data/07_metadata/incremental_review/round_01/incremental_review_round_01_metadata.json` |
| `data/07_metadata/incremental_review/round_01/incremental_review_round_01_report.json` |
| `data/07_metadata/incremental_review/round_01/incremental_review_delta_decisions.json` |
| `data/07_metadata/incremental_review/round_01/incremental_review_delta_decisions_resolved.json` |

同步更新硬编码路径的脚本与文档：

- `docs/DATA_PROCESSING_RUNBOOK.md`
- `docs/plans/2026-07-09-finetune-data-review-and-eval-redesign.md`
- `docs/IMPLEMENTATIONS/2026-07-12-metadata-directory-reorganization.md`（本文件）
- `pipeline/scripts/apply_review_decisions.py`
- `pipeline/scripts/audit_review_decisions.py`
- `pipeline/scripts/prepare_incremental_review_queue.py`
- `pipeline/scripts/review_subvideos_app.py`

## 4. 验证

- `data/07_metadata/` 目录结构与目标结构完全一致。
- `git status --short` 中 `data/07_metadata/` 相关记录为正常的 rename 或新增，无 `RD` 或 `??` 混乱。
- 所有受影响的 Python 脚本均通过 `python3 -m py_compile` 语法检查。
- 全项目扫描（排除 `data/07_metadata/` 自身及 `__pycache__/`）未发现残留的旧子目录硬编码路径引用。
- 未修改任何 JSON 数据内容，未删除任何文件。

## 5. 说明

本次变更只涉及 `data/07_metadata/` 的路径整理与脚本/文档中的硬编码路径同步，
不引入任何新的处理逻辑、训练规则或数据校验规则。
