# 数据入口

这里不再保存实际数据，只提供两个清晰入口：

- `current`：`tensile-vlm/v4.1` 当前使用的数据处理链路。
- `archive`：冻结的 `tensile-vlm/v2` 数据处理链路，只用于复现。

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

## 配置与校验

默认外部数据目录是仓库同级的 `tensile-data`，可通过
`TENSILE_DATA_HOME` 指定其他位置。`config/data_roots.json` 是契约、生命周期和
目录之间的唯一映射。

```bash
python pipeline/scripts/manage_versioned_data_roots.py init --contract all
python pipeline/scripts/manage_versioned_data_roots.py check --contract all
python pipeline/scripts/manage_versioned_data_roots.py workspace \
  --contract tensile-vlm/v4.1
```

每个外部根目录都有 `.tensile-data-root.json` marker。代码在读写前会验证 marker：

- V4.1 只能访问 `current`；
- V2 只能访问 `archive`；
- `archive` 的生命周期为 `frozen`，不得写入新输入或新发布；
- 两个根目录不得指向同一位置。

隐藏目录 `.compat/workspace` 提供旧 `data/...` 相对路径的兼容视图，但所有链接只会
指向本版本自己的语义目录，不会跨版本串线。

## 当前冻结发布

- V4.1：`current/training_releases/v4.1.0-760050fad303`
- V2：`archive/training_releases/v2.0.0-1dab1e5e`

发布目录不可覆盖。需要修正数据时必须创建新发布，不能直接编辑已经冻结的文件。
迁移清单和 checksum 证据见
[`docs/reports/2026-07-23-v2-v4-1-data-migration.md`](../docs/reports/2026-07-23-v2-v4-1-data-migration.md)。
