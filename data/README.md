# 数据入口

这里不再保存实际数据，只提供两个清晰入口：

- `current`：当前使用的数据处理链路。
- `archive`：冻结的旧版数据处理链路，只用于复现。

实际数据保存在仓库外的 `tensile-data` 目录中，避免原视频、帧画面和训练产物进入 Git。

## current 的目录含义

- `source/videos`：原视频
- `source/annotations`：原始标注
- `source/splits`：数据集划分
- `derived/roi_videos`：裁剪后的 ROI 视频
- `derived/subvideos`：子视频
- `derived/frames`：抽取帧
- `derived/metadata`：处理记录与审查结果
- `training_releases`：冻结后可直接训练的数据版本

普通目录名称不携带版本编码。只有冻结训练数据和契约文件保留明确版本号，
用于确认训练时实际使用的是哪一版数据。
