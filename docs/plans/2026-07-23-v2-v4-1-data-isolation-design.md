# V2 封存与 V4.1 数据链路隔离设计

## 决策

- V2 在 Git 引用 `tensile-vlm-v2-final` 和分支 `archive/v2` 上封存，只用于历史复现。
- `main` 是唯一活跃开发分支，后续新数据只使用 `tensile-vlm/v4.1`。
- 大型视频和中间结果不由 Git 保存；两版数据使用独立的外部根目录。

```text
tensile-data/
├── archive/
│   ├── source/
│   ├── derived/
│   │   ├── subvideos/
│   │   ├── frames/
│   │   ├── merged/
│   │   └── metadata/
│   └── training_releases/
└── current/
    ├── source/
    ├── derived/
    │   ├── roi_videos/
    │   ├── subvideos/
    │   ├── frames/
    │   └── metadata/
    └── training_releases/
```

默认数据根目录是仓库同级的 `tensile-data`，可通过
`TENSILE_DATA_HOME` 覆盖。`config/data_roots.json` 是代码版本、契约版本和数据目录之间的
唯一映射。

普通目录名称不携带版本编码。版本身份记录在根目录 marker、契约文件和
`training_releases/<release_id>` 中。

每个版本根目录还在隐藏的 `.compat/workspace` 下提供兼容视图。它只链接到同一版本自己的
语义目录，不会链接到另一个契约的数据。现有制品中已经冻结的 `data/...` 相对路径因此无需
改写，也不会干扰日常浏览。

## 防串线规则

- `archive` 与 `current` 不得指向同一目录。
- 每个版本根目录包含 `.tensile-data-root.json`，记录契约、Git 引用和生命周期。
- 程序在读写前必须验证 marker；契约不一致时拒绝执行。
- V2 标记为 `frozen`，不再接收新输入和新发布。
- 发布目录生成后不可覆盖；更正数据必须创建新发布。

## 当前训练保护

2026-07-23 三折训练已经结束。V4.1 冻结训练集现位于：

`tensile-data/current/training_releases/v4.1.0-760050fad303`

## 分阶段迁移

### 阶段 1：训练期间

1. 创建 V2 封存分支和固定标签。
2. 提交独立数据根配置、初始化/校验工具和测试。
3. 初始化本地与训练机的空目录结构。
4. 不复制大型媒体，不切换任何运行中的任务。

### 阶段 2：训练结束后

1. 记录训练完成状态和最终产物路径。
2. 将 V2 输入、过程数据和发布复制到 `tensile-data/archive`，校验后设为只读。
3. 将 V4.1 所需输入和现有发布复制到 `tensile-data/current`。
4. 比较文件数量和哈希，确认新旧内容一致。
5. 修改 V4.1 数据处理入口，使其只接受当前契约对应的 marker。

2026-07-23 已完成：V2 约 16 GB、V4.1 约 6.8 GB，全部复制校验为零差异。

### 阶段 3：切换验证

1. 使用 V4.1 新目录执行只读预检。
2. 故意向 V4.1 提供 V2 根目录，确认程序拒绝执行。
3. 新训练明确指定 V4.1 发布编号。
4. 仓库内 `data` 已改为 `current` 和 `archive` 两个入口；原目录整体保存在仓库外备份中。

## 回滚

旧仓库数据保存在 `mVllm_2-data-backups/pre-semantic-portal-20260723/data`。如需回滚，
先停止数据处理任务，再恢复该目录并切回迁移前的 Git 提交。
