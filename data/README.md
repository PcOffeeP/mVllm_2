# 数据入口

当前 V4.1 数据的权威本地根是：

`<repo>/workspace/data`

`data/` 不再保存实际训练数据，也不是新代码的解析入口。这里的 `current`、`archive`
以及仓库外 `tensile-data` 只保留为历史兼容视图，供冻结 V2/V4.1 证据复现。

## 当前项目内 workspace

```text
workspace/data/
├── source/
│   ├── videos/
│   ├── annotations/
│   └── splits/
├── derived/
│   ├── roi_videos/
│   ├── subvideos/
│   ├── frames/
│   └── metadata/
└── releases/
    └── <immutable-release-id>/
```

目录职责：

- `source/`：原视频、原始标注和源级划分；
- `derived/`：可以由来源与处理身份重新生成的派生产物；
- `releases/`：内容寻址、不可覆盖、可直接绑定训练配置的数据发布。

`pipeline.current_data` 固定解析 `<repo>/workspace/data`，不会读取
`TENSILE_DATA_HOME`、marker、profile 或 `.compat/workspace`。新训练、审查和发布代码
不得重新依赖仓库外数据根。

## 当前冻结发布

- 基础三折发布：`workspace/data/releases/v4.1.0-760050fad303`
- 当前 development 发布：`workspace/data/releases/v4.1.0-ecb5aeb9657c`

发布目录不可覆盖。需要修正标签、媒体或 split 时，必须创建新的内容身份和 release ID。

## 从旧数据根迁移

旧 V4.1 数据根为仓库同级 `tensile-data/current`。迁移只需要执行一次：

```bash
python pipeline/scripts/migrate_project_local_workspace.py --copy
python pipeline/scripts/migrate_project_local_workspace.py
```

第一条命令物理复制受管数据，第二条执行只读复核。迁移会比较文件数、总字节和逐文件
SHA-256；不会以软链接替代新 workspace，也不会删除旧根。

迁移完成后：

- `workspace/data` 是当前权威根；
- `tensile-data/current` 是未删除的旧副本；
- 历史 JSON 中的绝对路径继续作为运行快照保留；
- `config/data_roots.json` 与 `manage_versioned_data_roots.py` 只用于历史复现。

## V2 历史数据

V2 冻结数据仍位于旧 archive 语义根，只用于回滚与复现：

`tensile-data/archive/training_releases/v2.0.0-1dab1e5e`

不得向 V2 archive 写入 V4.1 数据，也不得把 V2 的 `training_releases/` 重新设为当前活动
发布。

## 安全规则

- 原始媒体和大型派生产物不进入 Git；
- 不直接修改 `workspace/data/releases/<release-id>`；
- 不把源视频级标签静默覆盖到人工复审后的帧窗口标签；
- 不在同一实验中混用不同 release、Prompt revision 或 contract hash；
- 新实验必须把数据 release 和 manifest hash 写入 experiment contract；
- 删除旧数据根必须单独获得授权，不能因为迁移校验通过就自动清理。

迁移证据见
[项目内 Workspace 迁移报告](../docs/reports/2026-07-28-project-local-workspace-migration.md)。
