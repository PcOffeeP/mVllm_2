# 源视频 ROI 标注工具 MVP 设计

## 目标和范围

为每个源视频人工指定一个固定 `3:4`（宽:高）矩形 ROI，或明确标记为不裁剪。工具必须支持视频播放、
按时间拖动抽帧、直接平移和缩放裁剪框、原图与裁剪预览、关键时刻检查，以及可追溯的 JSON
决定输出。

MVP 只负责生成 ROI 决定，不生成裁剪视频，不修改原始媒体、子视频 metadata、split 或
训练发布版本。

## 非目标

- 不支持随时间移动的动态 ROI。
- 不自动识别试样或自动跟踪。
- 不直接生成 `data/09_roi_media/`。
- 不把原视频和 ROI 视频直接重复加入训练集。
- 不修改已有子视频人工审核决定。

## 方案选择

考虑过三种方案：

1. 纯数值输入：实现最简单，但人工无法直接确认裁剪结果。
2. Streamlit 视频播放加抽帧预览：复用现有审核工具栈，能满足播放、拖动和可视化需求。
3. 独立前端实时叠加裁剪框：交互最好，但需要新的前端构建与组件维护。

MVP 采用方案 2，并通过 Streamlit 裁剪组件提供直接框选。视频使用浏览器原生播放器；
时间滑块负责精确抽取当前帧；人工直接平移或缩放固定 `3:4` 的红框，红框内画面就是最终 ROI。

## 数据契约

默认输入：

- `data/07_metadata/video_meta.json`
- `data/01_videos/*.mp4`

默认输出：

- `data/07_metadata/roi_decisions.json`

每条决定至少包含：

- `source_video_id`
- `mode`: `fixed_roi` 或 `no_crop`
- `review_status`: `approved` 或 `needs_review`
- `margins`: top/right/bottom/left，取值为 `[0, 1)` 的归一化比例
- `normalized_box`: x/y/width/height
- `pixel_box`: x/y/width/height，按当前源分辨率转换并规整为偶数宽高
- `target_aspect_ratio`: 固定为 `3:4`
- `aspect_ratio_strategy`: `crop_exact` 或 `pad_to_target`
- `requested_margins`: 与最终红框对应的归一化边界，兼容既有数据字段
- `interaction_mode`: `fixed_roi` 固定为 `drag_box`，`no_crop` 固定为 `no_crop`
- `source_resolution`
- `source_sha256`、文件大小和 mtime
- `reviewed_timestamps`
- `visibility_checks`：上/下夹具、完整试样、位置可判断、齐根可判断
- `roi_policy_version`
- `reviewed_at` 和备注

顶层文件包含 schema 版本、输入 metadata 路径、生成时间和所有视频决定。保存使用原子
替换，避免中途中断写坏历史决定。

## 组件与职责

`pipeline/scripts/roi_annotation_app.py` 同时提供：

- 可单测的几何、时间点、JSON 读写和决定构建函数；
- FFprobe 媒体探测和 FFmpeg 单帧提取；
- Streamlit 列表、播放器、裁剪参数、预览和保存界面。

## 交互与校验

1. 从源视频列表选择视频。
2. 播放视频或用时间滑块定位当前画面。
3. 选择 `fixed_roi` 或 `no_crop`。
4. 对固定 ROI 直接平移或缩放红色裁剪框；系统始终锁定为精确 `3:4`。
5. 红框坐标按源视频分辨率保存为偶数像素框，不再由四方向比例二次推导可见结果。
6. 检查当前帧原图、ROI 预览以及开头、25%、50%、75%、结尾和事件附近帧。
7. approved 保存前必须确认已经检查关键时刻。
8. approved 保存前必须逐项确认上/下夹具和完整试样可见，且位置、齐根仍可判断。
9. 任一方向越界、左右或上下裁剪和过大、裁剪后无法形成偶数像素 `3:4` 框时拒绝保存。

`no_crop` 也是显式决定，保存为零边距和全画面矩形，不能用缺少记录表示。
其后续媒体生成策略固定为 `pad_to_target`，将完整画面补边到 `3:4`。

ROI 策略版本升级到 `1.2`。`1.0` 和 `1.1` 决定只保留为历史证据，在界面中显示为
“旧策略待复审”，不会被自动改写或通过冻结。

## 失败处理

- metadata 不存在或非法：停止并显示错误。
- 视频缺失：保留列表项，但禁止保存 approved 决定。
- FFprobe/FFmpeg 不可用或抽帧失败：显示具体命令错误，不写决定。
- 源文件大小或 mtime 与已有决定不一致：提示决定可能失效，要求重新保存。
- 已有输出 JSON 非法：停止，避免覆盖损坏文件。

## 测试策略

单元测试覆盖：

- 拖拽框、margin 和 normalized box 的一致性校验；
- 偶数像素裁剪框转换；
- 关键审核时间点生成；
- fixed ROI 与 no-crop 决定构建；
- JSON 原子保存和历史决定保留；
- 源文件变更检测。
- 110 条决定完整覆盖、全部 approved、源哈希一致和 89/21 划分隔离；
- 内容寻址 ROI manifest 的幂等冻结与不可覆盖。

本机只运行轻量测试和实际源视频的 FFprobe/单帧抽取冒烟，不生成全量派生视频。

## 后续边界

全部人工决定完成后，先运行 `freeze_roi_decisions.py --check-only`，再冻结为内容寻址的
ROI manifest。只有冻结成功的 manifest 才能进入下一步 ROI 媒体生成。生成器必须版本化
输出、重新执行真实模型抽帧、重算新标签，并进入新的质量检查和发布链路。
