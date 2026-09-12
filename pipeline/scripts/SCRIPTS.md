<!-- DOCUMENT-CONTRACT
Purpose: 区分pipeline可用工具与停用入口，指向正式数据和服务用法。
Scope: 同目录命令职责、活动/历史边界与权威文档链接。
Must Preserve:
- 已停用CLI不能写作现行发布路径。
- 业务辅助工具与新体系正式写入者必须区分。
Non-goals:
- 不复述完整参数或保存本次迁移进度。
-->

# pipeline 命令与历史入口

| 文件 | 作用 |
| --- | --- |
| `roi_annotation_app.py` | ROI输入准备；必填metadata文件/output/project-root，不再解析current/LATEST或快照ID |
| `roi_freeze_decisions.py` | 冻结 ROI 决定 |
| `roi_materialize_videos.py` | 生成 ROI 视频 |
| `subvideo_build_plan.py` | 生成当前沿用的候选计划 |
| `subvideo_materialize_media.py` | 生成候选视频与实际采样帧 |
| `review_build_queue.py` | 生成 V4.1 审核队列 |
| `review_build_phase2_queues.py` | 生成阶段 2 隔离队列 |
| `review_route_from_history.py` | 按冻结历史分流审核 |
| `review_candidates_app.py` | 完整versioning-package审查界面；旧queue写入模式已停用 |
| `release_build.py` | CLI已停用；正式发布使用versioning data release |
| `release_build_phase2.py` | CLI已停用；既有Phase2对象使用显式mapping迁移 |
| `rebuild_data.py` | CLI已停用，包括run/resume/promote/source-only/check-only；历史编排仅供显式私有测试调用 |
| `build_artifact_index.py` | 扫描各产物集合目录的 `index.json`，生成数据根 `INDEX.md` 全局总览；支持 `--data-root`。覆盖历史产物集合；legacy promote 业务函数在快照移入正式 workspace 后更新 source/split 集合索引。`rebuild_data.py` CLI 已停用，保留业务函数不代表公开入口仍可执行。 |
| `serve_smoke.py` | 显式root/alias/service-mode/contract校验Registry绑定后执行HTTP检查；用法见上级SCRIPTS.md |

新正式数据流程见[数据手册第10节](../../docs/DATA_PROCESSING_RUNBOOK.md#10-现行数据入口versioning显式七阶段)和[显式输入契约](../../versioning/SCRIPTS.md#显式数据七阶段)。上表ROI/候选媒体/队列脚本中仍保留历史辅助入口，不能据此声明整个legacy包已退役。

其他旧命令另放在 [`archive/`](archive/README.md)。
