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
| `roi_freeze_decisions.py` | CLI已停用；现行数据链使用versioning data roi；历史函数和产物保留 |
| `roi_materialize_videos.py` | CLI已停用；现行数据链使用versioning data roi；历史函数和产物保留 |
| `subvideo_build_plan.py` | CLI已停用；现行数据链使用versioning data subvideo；历史函数和产物保留 |
| `subvideo_materialize_media.py` | CLI已停用；现行数据链使用versioning data subvideo；历史函数和产物保留 |
| `review_build_queue.py` | CLI已停用；现行数据链使用versioning data review_export；历史函数和产物保留 |
| `review_build_phase2_queues.py` | CLI已停用；现行数据链使用versioning data review_export；历史函数和产物保留 |
| `review_route_from_history.py` | CLI已停用；现行数据链使用versioning data review_export；历史函数和产物保留 |
| `review_candidates_app.py` | 完整versioning-package审查界面；旧queue写入模式已停用 |
| `release_build.py` | CLI已停用；正式发布使用versioning data release |
| `release_build_phase2.py` | CLI已停用；既有Phase2对象使用显式mapping迁移 |
| `rebuild_data.py` | CLI已停用，包括run/resume/promote/source-only/check-only；历史编排仅供显式私有测试调用 |
| `build_artifact_index.py` | 扫描各产物集合目录的 `index.json`，生成数据根 `INDEX.md` 全局总览；必须显式给出现存 `--data-root`，不选择current根；只写INDEX.md报告，不注册或更新集合身份。覆盖历史产物集合；legacy promote 业务函数在快照移入正式 workspace 后更新 source/split 集合索引。`rebuild_data.py` CLI 已停用，保留业务函数不代表公开入口仍可执行。 |
| `serve_smoke.py` | 显式root/alias/service-mode/contract校验Registry绑定后执行HTTP检查；用法见上级SCRIPTS.md |

新正式数据流程见[数据手册](../../docs/data-workflow.md#2-冻结裁剪和生成待审包)和[显式输入契约](../../versioning/SCRIPTS.md#显式数据七阶段)。上表7个ROI/候选媒体/队列辅助CLI已停用；ROI输入准备及完整审查包UI仍可用，历史库和索引工具保留，不声明整个legacy包已删除。

其他旧命令另放在 [`archive/`](archive/README.md)。
