# `tensile-vlm/v4` 断裂位置分级契约设计

## 目标与范围

将 `tensile-vlm/v3` 中相互依赖的 `root_break` 与 `location` 合并为单一、互斥的
`fracture_site`，避免模型和人工审核重复判断同一空间属性。v4 单 clip 输出固定为：

- `clip_state`
- `fracture_mechanism`
- `fracture_site`
- `special_case`

本设计同步约束 mVllm_2 的标签、复检、训练数据目标契约，以及 TensileAgent 保存的消费者
artifact 和未来迁移边界。当前生产运行仍使用 `tensile-vlm/v2`，不会因 v4 artifact 存在而切换。

## 业务语义

`fracture_site` 是互斥的断裂部位分类：

- `inside_gauge`：标距内断裂，属于理想或正常断裂位置。
- `outside_gauge_non_root`：标距外但非齐根断裂，属于不理想断裂位置。
- `grip_root`：夹具根部齐根断裂，属于严重负面断裂位置。
- `null`：当前 clip 证据不足，无法可靠判断断裂部位。

视觉模型只输出可见事实，不输出质量或严重程度。未来 TensileAgent 使用确定性映射：

- `inside_gauge -> acceptable`
- `outside_gauge_non_root -> unfavorable`
- `grip_root -> severe_unfavorable`
- `null -> unavailable`

## 非目标

- 不原地修改或删除 v2、v3 artifact、审查决定和媒体证据。
- 不重新生成已通过门禁的 1617 个 MP4 或 10340 个 JPG。
- 不在 v4 模型训练和验收前修改 TensileAgent 当前 v2 Runner、HTTP 服务或状态机。
- 不把严重程度作为第五个模型输出字段。
- 不继续使用 `root_break + location` 双字段作为 v4 训练目标。

## 方案比较

1. 保留双字段并增加 `root_break=true -> location=outside_gauge` 约束：改动小，但仍要求模型重复
   回答同一空间问题，联合输出仍可能冲突。
2. 合并为三级 `fracture_site`：完整保留当前三种有效组合，消除非法组合并减少一个输出字段。
3. 删除 `root_break`、只保留标距内外：最简单，但会丢失业务上最严重的齐根断裂信息。

采用方案 2。训练机当前 73 个断裂开发源中，实际组合只有 53 个标距内、13 个标距外非齐根、
7 个齐根；`root_break=true` 全部属于 `outside_gauge`。三级字段与现有业务数据完全对应。

## v4 标签与跨字段规则

`clip_state`、`fracture_mechanism` 和 `special_case` 沿用 v3 枚举与搜索语义。
`fracture_site` 取代 `root_break` 和 `location`。

- `clip_state=未断裂` 时，其余三个字段必须为 `null`。
- `special_case` 非空时，`clip_state=无法判断`，其余两个断裂汇总字段必须为 `null`。
- `发生断裂`、`已断裂`及非特殊情况的`无法判断`允许汇总字段独立为 `null`。
- `clip_state` 仍是唯一方向性字段；`fracture_mechanism` 和 `fracture_site` 只参与最终汇总。

## v3 到 v4 的迁移

对完整、无冲突的 v3 组合执行无损映射：

| v3 `root_break` | v3 `location` | v4 `fracture_site` |
| --- | --- | --- |
| `false` | `inside_gauge` | `inside_gauge` |
| `false` | `outside_gauge` | `outside_gauge_non_root` |
| `true` | `outside_gauge` | `grip_root` |
| `null` | `null` | `null` |

`true + inside_gauge` 属于非法冲突，迁移必须失败。只有单字段证据或其他不完整组合不得猜测，
应迁移为 `null` 或进入人工复核；具体由迁移报告显式列出。

v4 队列以内容寻址 manifest 绑定以下输入：

- v3 candidate media manifest 与 `review_queue.json` 哈希；
- v4 contract hash；
- 全部 candidate ID、视频和帧图哈希；
- v3→v4 映射策略版本；
- 已迁移决定的来源批次和决定哈希。

媒体路径和媒体哈希直接复用，标签字段写入新的 v4 队列与决定目录。v3 文件保持只读。

## mVllm_2 组件

- `pipeline/contracts/tensile_vlm_v4.json`：权威四字段目标契约。
- `pipeline/v4_labels.py`：v4 标签验证、legacy/v3 位置迁移。
- v4 review decision schema：保存系统建议、历史参考、人工修正和最终标签。
- v4 queue builder：从已验证 v3 candidate media 派生不可覆盖的 v4 队列，不编码媒体。
- v4 review workflow/UI：读取 v4 队列，迁移现有 4 条决定，继续完整 598 条复检。
- v4 训练发布构建：仅在 598 条全部达到终态后启用，不读取 v3 草稿冒充 v4 决定。

## TensileAgent 组件

- `agent/contracts/tensile_vlm_v4.json` 与 mVllm_2 artifact 字节一致。
- 项目计划将 v4 标记为下一代目标契约，将 v3 标记为已废止的未部署设计。
- consumer 契约测试固定 v4 hash、四字段 schema、三级 `fracture_site` 与搜索语义。
- 当前 `agent/schema.py`、Runner、HTTP stub 和状态机继续使用 v2；模型验收前不提前迁移。
- 未来运行时迁移时，公开结果可继续保留用户层 `location`，但值域和严重程度必须由
  `fracture_site` 确定性投影，不恢复 `root_break` 双字段。

## 失败处理

- artifact hash、字段、枚举或 Prompt 漂移：拒绝消费。
- v3 标签组合非法或迁移含歧义：记录到迁移冲突报告，不生成猜测标签。
- 已迁移人工决定的 candidate ID、媒体哈希或系统建议不一致：拒绝导入该决定。
- v4 队列未完成：禁止冻结 v4 最终决定和训练发布。
- v4 模型尚未验收：TensileAgent 继续使用 v2，不能把目标 artifact 当成已部署服务。

## 验证与验收

- 两仓 v4 artifact JSON 逐字节一致，canonical contract hash 固定。
- v4 标签与迁移映射覆盖全部有效、空值和冲突组合。
- v4 队列 candidate 数仍为 598，媒体哈希与 v3 完全一致，标签分布为：
  53 个源 `inside_gauge`、13 个源 `outside_gauge_non_root`、7 个源 `grip_root`。
- 当前 4 条 v3 人工决定逐条校验后迁移，完整 v4 草稿从 4/598 继续。
- mVllm_2 与 TensileAgent 全量测试、跨仓一致性和 `git diff --check` 通过。
- v4 工作台经浏览器确认只显示四字段，默认待审核数为 594。

## 发布纪律

两个仓库分别原子提交，不 push。训练机在确认 `HEAD` 和工作区后接收 mVllm_2 提交。
v4 队列和决定写入新目录；v3 媒体、决定和证据保留。只有 v4 全量审查、质量门和训练发布完成后，
才进入模型微调与 TensileAgent 运行时迁移。
