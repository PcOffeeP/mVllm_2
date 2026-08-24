# pipeline 当前命令

| 文件 | 作用 |
| --- | --- |
| `migrate_project_local_workspace.py` | 迁移并校验项目内数据目录 |
| `roi_annotation_app.py` | 标注 ROI |
| `freeze_roi_decisions.py` | 冻结 ROI 决定 |
| `materialize_roi_videos.py` | 生成 ROI 视频 |
| `subvideo_build_plan.py` | 生成当前沿用的候选计划 |
| `materialize_v3_candidate_media.py` | 生成候选视频与实际采样帧 |
| `build_v4_1_review_queue.py` | 生成 V4.1 审核队列 |
| `build_v4_1_phase2_review_queues.py` | 生成阶段 2 隔离队列 |
| `route_v4_1_review_from_history.py` | 按冻结历史分流审核 |
| `review_v4_candidates_app.py` | 打开当前审核界面 |
| `build_v4_1_training_release.py` | 构建基础 V4.1 发布 |
| `build_v4_1_phase2_training_release.py` | 构建阶段 2 发布 |
| `rebuild_v4_1_data.py` | 运行、恢复或晋升隔离的 V4.1 数据重建；`--source-only` 会初始化 run state（写 `run_root/control/rebuild.json`）并将 roi/review 模式烘焙为不可变身份，同一 run-root 续跑完整流水线时必须使用相同模式，否则需换 run-root；`--check-only` 仅校验输入并打印身份（不写文件） |
| `build_artifact_index.py` | 扫描各产物集合目录的 `index.json`，生成数据根 `INDEX.md` 全局总览；支持 `--data-root`。当前覆盖 staging 侧与 `roi_manifests`/`roi_videos`；`promote` 尚未把 `index.json` 从 source/split 快照传播到正式 workspace 集合。 |
| `smoke_tensile_vlm_service.py` | 检查当前推理服务 |

其他旧命令统一放在 [`archive/`](archive/README.md)。
