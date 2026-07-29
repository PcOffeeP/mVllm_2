# 数据 staging 与语义化元数据路径设计

## 目标和范围

在不删除、不覆盖现有数据和历史 release 的前提下，简化当前 V4.1 数据目录：

- 新的隔离处理任务统一写入 `workspace/data-staging/<run-id>/`；
- 新产物使用无契约版本的语义目录，不再新增 `metadata/v3/` 或
  `metadata/v4_1/` 路径；
- source identity 与 split identity 分离；
- 现有正式数据中的 `metadata/v3/`、`metadata/v4_1/` 继续只读兼容；
- 已完成的 `workspace/data-rebuild/` run 保持只读；尚未完成的既有 run 只能按下文
  “legacy resume profile” 在原路径受控续跑，保证当前等待人工审阅的 run 可完成。

## 非目标

- 不移动、重命名或删除现有物理数据；
- 不改写既有 manifest、release 或模型注册表；
- 不把当前 chain-validation 测试 release 晋级为正式数据；
- 不在本次迁移中完成人工审阅、正式 promote、训练或 GPU 评测；
- 不自动清理旧路径或孤立制品。

## 约束和假设

- `workspace/data` 继续作为唯一正式数据根；
- `workspace/data-staging` 只保存未晋级的运行数据、状态、日志和报告；
- 现有 `workspace/data-rebuild/v4-1-clean-20260729` 必须能够按原路径和 state
  记录的 Git commit 恢复；
- 新 run 不得写历史路径；唯一写入例外是已经存在且尚未完成的 legacy run，写入范围
  仅限其原 run root 以及该 run 已冻结 promotion layout 中的目标；
- 所有正式产物仍保持内容寻址、不可覆盖和 release-last promote；
- 大型媒体和运行制品不进入 Git。

## 方案比较

### 方案 A：原地重命名

把 `data-rebuild` 改名为 `data-staging`，并把现有 `v3/`、`v4_1/` 目录原地移动。

优点是目录立刻统一；缺点是会破坏冻结 manifest、release 路径、运行状态和历史复现。
不采用。

### 方案 B：新写入切换，旧路径只读兼容

新 run 和新产物只写入新路径；解析器按“新路径优先、旧路径回退”读取现有制品，旧数据
保持原位。

优点是零破坏、可渐进迁移、历史可复现；代价是兼容期内存在两套读取路径。采用。

### 方案 C：只改展示名称

仅修改文档或 UI，不改变物理写入路径。

风险最低，但不能解决目录持续新增历史版本名的问题。不采用。

## 推荐目录

```text
workspace/
├── data/
│   ├── source/
│   │   ├── videos/
│   │   └── annotations/
│   ├── derived/
│   │   ├── roi_videos/
│   │   ├── subvideos/
│   │   ├── frames/
│   │   └── metadata/
│   │       ├── source_snapshots/
│   │       ├── split_snapshots/
│   │       ├── roi_manifests/
│   │       ├── candidate_plans/
│   │       ├── candidate_media_results/
│   │       ├── review_reference/
│   │       ├── review_queues/
│   │       └── review_decisions/
│   └── releases/
└── data-staging/
    └── <run-id>/
        ├── data/
        ├── control/
        ├── reports/
        └── logs/
```

目录只表达数据职责。schema、契约和策略版本写入 manifest，不再编码进父目录名。

## 组件职责

### DataContext

- 新建 run 时只接受 `workspace/data-staging/<run-id>/data`；
- 新布局 DataContext 不接受 `workspace/data-rebuild` 作为可写 context；只读诊断器
  可以检查其 `control/rebuild.json`、冻结 root 和 producer commit，实际恢复必须切回
  producer commit；禁止用新代码在 `data-rebuild` 下创建或续跑 run；
- 提供统一的语义 metadata collection 路径；
- 旧绝对路径和旧相对路径继续通过兼容映射解析。

DataContext 使用两个明确 layout profile：

- `semantic-staging-v2`：仅用于新建 `data-staging` run，所有新写入使用语义路径；
- `legacy-rebuild-v1`：由该 run 的 producer commit 负责恢复，保持原有
  `v3`/`v4_1` 写入位置、状态文件和 promotion target，不把半成品迁移到新布局。

当前 `v4-1-clean-20260729` 必须使用 `rebuild.json.git_commit` 记录的 producer 提交
完成剩余人工审阅和晋级；若当前 checkout 不匹配，操作方先按双机 Git 纪律切回该提交。
新布局代码只负责只读诊断并拒绝接管，不在恢复时改写 legacy state 身份。

对外 API 分离为：

- `create_staging_context(project_root, run_root)`：要求 run root 位于
  `workspace/data-staging`、不存在 state，创建 `semantic-staging-v2`；
- `resume_staging_context(project_root, run_root, git_commit)`：要求 run/state 已存在，
  验证冻结 root、layout profile 和 Git identity 后恢复；
- `inspect_legacy_context(project_root, run_root)`：只读诊断既存、非 symlink 的
  `workspace/data-rebuild/<run-id>`，验证 v1 state 并返回 producer Git commit；
  不存在的 root、伪造 state、root/data 身份不一致或 symlink 一律拒绝。

新布局代码不执行 legacy run 的剩余阶段。操作方必须在训练机原工作区按双机 Git 纪律
切回 producer commit，使用其中原有的编排器继续 run，完成后再切回新分支。因此旧
producer 不依赖、也不会调用本次迁移新增的 API。

producer commit 中的 `legacy-rebuild-v1` 允许新增或更新的路径仅包括：

- 原 run 内 `data/derived/metadata/v4_1/review_decisions/<queue-id>/<batch-id>`；
- 原 run 内 `data/releases/<release-id>`；
- 原 run 内 `control/rebuild.json`、`control/commands.jsonl` 和
  `control/promotion.json`；
- 共享正式锁文件 `workspace/data/.locks/v4-1-promote.lock`；
- producer commit 代码已确定的旧布局 promotion target allowlist，包括正式数据中的
  对应 `metadata/v3`、`metadata/v4_1` 内容寻址目录和 `releases/<release-id>`。

已有 source、ROI、candidate、queue 只能重验，不能重写。legacy promotion 必须沿用完整
旧 target 集，禁止把其中一部分切换为语义路径。当前 waiting run 尚无
`promotion.json`；该文件只能在 producer commit 完成人工 decisions 与 release 后，由
producer 编排器按其固定 allowlist 生成。promote 会把 inventory 中的 staging source
原子 rename 到旧 target；这些 source 消失和 target 新增属于 producer 协议的一部分，
必须在执行前审计实际生成的 inventory，不能由新布局代码预测或改写。

### 元数据路径解析

写入始终使用：

```text
metadata/source_snapshots
metadata/split_snapshots
metadata/roi_manifests
metadata/candidate_plans
metadata/candidate_media_results
metadata/review_reference
metadata/review_queues
metadata/review_decisions
```

兼容解析的最小单位是
`(collection, artifact_id, expected_schema[, expected_tree_hash])`，不是整个
collection。collection registry 必须声明该类 artifact 的身份字段和入口 manifest
文件；写入 API 只返回新语义 collection root，读取 API 按以下顺序解析：

1. 检查新语义路径下精确 `artifact_id`；一旦目录存在，就必须验证其为物理目录、
   basename/manifest identity、schema、manifest 声明的 exact file inventory、逐文件
   hash 和可重算 content ID，非法时立即失败，不得回退；
2. 新路径没有该 ID 时，检查对应旧路径下精确 ID，并执行同样校验；
3. 两边存在同一 ID 时，分别完成上述验证；tree hash 相同则返回新语义路径，tree hash
   不同则 fail closed；
4. `expected_tree_hash` 存在时，计算包含入口 manifest 的完整 tree hash 并与其一致；
5. collection 枚举先合并两边 artifact ID，再逐个执行上述解析，不允许直接
   `glob` 某一个物理 root 后假定结果完整。

不同 artifact ID 可以在新旧 collection 中正常共存。绝对路径、相对路径和 collection
名称都必须执行根边界检查，拒绝 `..`、symlink、hardlink 和特殊文件。

`expected_tree_hash` 的可信来源只能是已冻结的 `rebuild.json` stage output、
`promotion.json` inventory、release provenance 或显式调用参数；resume、release 构建
和 promote 时必须提供，只有无 state 的只读 discovery 可以省略。artifact 自身的入口
manifest 不保存“包含自身”的完整 tree hash，避免自引用。单副本无外部锚点时，解析器
只声明“内部 inventory/content ID 自洽”，不宣称其完整 tree hash 等于某个外部预期值；
完整 tree hash 只用于外部锚定或同 ID 新旧副本比较。

collection registry 为每一类 artifact 提供独立 validator，声明入口 manifest、身份
字段、允许的 exact file set、payload hash 字段和 content ID 重算规则。任何额外文件、
缺失文件、payload/manifest 同时篡改后无法重算原 content ID，或目录 ID 与重算 ID
不一致都必须失败。

旧路径映射包括：

```text
v3/roi_manifests          -> roi_manifests
v3/candidate_plans        -> candidate_plans
v3/candidate_media_results -> candidate_media_results
v3/review_reference       -> review_reference
v4_1/review_queues        -> review_queues
v4_1/review_decisions     -> review_decisions
```

### Source snapshot

Source snapshot 只绑定原视频、原始标注和媒体探测结果，不包含数据划分：

```text
source_snapshots/<source-snapshot-id>/
├── source_inventory.json
├── annotation_inventory.json
├── video_meta.json
└── validation_report.json
```

新 source snapshot 使用 `tensile-source-snapshot/v2`。其内容身份只包含：

- 视频 ID、大小、SHA-256 和媒体探测结果；
- 两份原始标注的文件 SHA-256、列契约与规范化行摘要；
- 规范化 `video_meta` 与 source validation 结果。

split policy、seed、成员列表和 split 文件不得进入 source snapshot identity。

source ID 的 canonical seed 固定为：

```json
{
  "schema_version": "tensile-source-snapshot/v2",
  "videos": "<按 video_id 排序的 size/sha256/probe 记录>",
  "annotations": "<按文件名排序的 file sha256/columns/normalized rows sha256>",
  "video_meta_sha256": "<规范化 video_meta.json 内容 hash>",
  "validation_report_sha256": "<规范化 validation_report.json 内容 hash>"
}
```

ID 为 `source-snapshot-` 加上述 canonical JSON SHA-256 的前 12 位。schema 参与摘要；
目录名、时间戳和绝对路径不参与，ID 不得包含自身。

### Split snapshot

数据划分形成独立内容身份：

```text
split_snapshots/<split-snapshot-id>/
├── split_manifest.json
├── split_decision.json
├── fold_0_train.json
├── fold_0_val.json
├── fold_1_train.json
├── fold_1_val.json
├── fold_2_train.json
├── fold_2_val.json
└── test.json
```

`split_manifest.json` 必须绑定 `source_snapshot_id`、划分策略版本、seed、成员 ID 摘要和
各文件 SHA-256。release 同时绑定 `source_snapshot_id` 与 `split_snapshot_id`。

新 split snapshot 使用 `tensile-split-snapshot/v1`。`split_snapshot_id` 由以下内容
共同计算：

- `source_snapshot_id`；
- split policy version、seed、test ratio、fold 数；
- 每个 split 的有序成员 ID 摘要；
- `split_decision.json` 与七个 split 文件的 SHA-256。

split ID 的 canonical seed 固定为：

```json
{
  "schema_version": "tensile-split-snapshot/v1",
  "source_snapshot_id": "<source-snapshot-id>",
  "policy": {
    "version": "<policy-version>",
    "seed": "<integer>",
    "test_ratio": "<canonical decimal>",
    "fold_count": 3
  },
  "member_ids_sha256": "<split 名排序、每组成员 ID 排序后的摘要>",
  "artifacts": "<split_decision 与七个 split 文件按相对路径排序的 SHA-256>"
}
```

ID 为 `split-snapshot-` 加 seed hash 前 12 位。`split_manifest.json` 在 ID 计算完成后
写入，声明完整 seed、artifact hash、目录 ID 和 source 绑定；manifest 自身不参与 ID，
避免自引用。

source snapshot 与 split snapshot 先分别写入临时目录并原子 rename。只有两者都完成
tree hash 校验后，编排器才在同一 stage completion record 中记录这一对身份；若中途
崩溃，已完成但未被 state 引用的单个 snapshot 只是不可达制品，不自动删除。

新 staging 的下游阶段必须显式接收 `split_snapshot` 路径，不再从
`DataContext.splits` 或 `source/splits` 隐式取值。`source/splits` 只保留给当前正式
数据与 legacy run 兼容读取。

### Legacy source/split adapter

旧 `tensile-source-snapshot/v1` 同时包含 source 与 `splits/`。兼容读取时：

- 原 `source_snapshot_id` 保持不变，不改写目录或 manifest；
- legacy run 恢复必须继续执行原 v1 combined identity 算法，不得用 v2 重算 state；
- 读取器从 `splits/`、`split_decision.json` 和旧 identity 中计算只读
  `legacy-split-snapshot-<digest>`；
- 该派生 ID 只存在于运行时 provenance adapter，不在旧目录中补写文件；
- 旧 release 没有 `split_snapshot_id` 时按 legacy schema 校验；新 release schema
  必须同时包含非空 `source_snapshot_id` 与 `split_snapshot_id`，禁止只提供其中一个。

### Release v2 identity

新 release 使用 `tensile-training-release/v4.1-v2`。canonical seed 固定包含：

- release schema；
- contract hash 与 contract 文件 hash；
- source snapshot ID、manifest hash 和完整 tree hash；
- split snapshot ID、manifest hash 和完整 tree hash；
- candidate media、review queue、正式 frozen decisions 的身份与 hash；
- `training_candidates.json` hash。

构建前必须验证 source/split 目录 basename 与 manifest ID 一致、split manifest 绑定的
source ID 一致、成员集合完整、逐文件 SHA 和 tree hash 一致。交换两个 split snapshot、
篡改 source ID、成员文件或目录名都必须失败。旧
`tensile-training-release/v4.1` release 继续由 v1 validator 按原字段校验，不补写
`split_snapshot_id`；v1 与 v2 validator 不共享宽松的可选字段路径。

## 数据流和状态

```text
workspace/data/source
  -> data-staging/<run-id>/data
  -> source snapshot
  -> split snapshot
  -> ROI manifest / ROI media
  -> candidate plan / candidate media / sampled frames
  -> review queue
  -> frozen human decisions
  -> immutable release
  -> ready_to_promote
  -> workspace/data
```

所有生成工作发生在 staging。正式 promote 只晋级 inventory 中经过 tree hash 校验的
内容寻址目录，release 仍最后晋级。

新 run 的 promotion inventory 固定按以下顺序：

1. source snapshot；
2. split snapshot；
3. ROI manifest / ROI media；
4. candidate plan / candidate media / sampled frames；
5. review queue / frozen decisions；
6. release。

legacy run 继续使用其原 promotion layout 和旧 metadata target；不得在续跑过程中把
部分 entry 改成新语义路径。

## 失败处理和边界

- 新旧路径同时包含相同内容身份但 tree hash 不一致时失败；
- 历史 run 继续把自己的 `run_root` 与 layout profile 视为不可变身份，不自动换到
  `data-staging`；
- 已完成 legacy run 和正式 legacy metadata 保持只读；未完成 legacy run 只有在 state
  路径、Git identity 和 layout profile 均验证通过后才能写原 run；
- split snapshot 与 source snapshot 不匹配时拒绝构建候选或 release；
- 未完成正式人工 decisions 时不生成正式 release；
- staging 中断、测试 release 或未引用产物不会进入正式 `workspace/data`；
- 清理旧目录必须由独立清理计划和用户再次确认，不属于本设计。

## 测试策略

- DataContext：新 staging 路径可用，任意其他路径失败；旧 rebuild 只能被只读诊断，
  禁止由新布局代码新建或续跑；
- 路径解析：按 `(collection, artifact_id)` 验证新路径优先、旧路径回退、相同
  tree hash 去重和冲突 fail closed；单副本同时篡改 payload/manifest、增加额外文件、
  删除文件和目录 ID 不匹配均失败；
- Source/Split：身份独立，改变 split seed 不改变 source ID 但必须改变 split ID；
  改变视频或标注必须改变 source ID，并使旧 split 绑定失败；
- Legacy adapter：旧 combined snapshot 和旧 release 不改写即可读取；新 release
  缺任一 snapshot ID 时失败；
- Rebuild：新 run 不再写入 `metadata/v3`、`metadata/v4_1`；
- Resume：现有 `data-rebuild` waiting run 切回记录的 producer commit 后仍可继续写
  原 run；新布局代码的只读诊断只给出 producer commit，不执行恢复；无 state 的旧
  root、symlink、伪造 state 和 layout 混写均失败；producer 生成 promotion inventory
  后须验证共享 lock、staging rename source 和旧 target allowlist；
- Promote：新语义路径按 inventory 原子晋级，release 最后；
- Promote 边界：从 `control/chain-validation`、`reports` 或 `logs` 构造 entry 必须
  失败；release 不是最后 entry、未达到 `ready_to_promote` 或直接绕过状态机必须失败；
- Human gate：没有正式 frozen human decisions 时，不得生成正式 release、
  `promotion.json` 或进入 `ready_to_promote`；
- Regression：现有 release、当前模型注册表和历史结果继续通过校验；
- Guard：active path guard 不允许新增旧路径写入；运行时拼接旧版本写路径也必须由测试
  捕获；
- Git 边界：`workspace/` 继续被 Git ignore，并检查 tracked files 中不存在
  `data-staging` 媒体或运行制品。

## 迁移和发布

迁移期间 `semantic-staging-v2` create feature gate 默认关闭；在 gate 打开前，生产入口
不得创建新 staging run。实现与发布顺序固定为：

1. 在 gate 关闭状态下增加新路径模型、collection registry 和旧路径只读兼容；
2. 完成 Source v2、Split v1、Release v2 身份与 validator；
3. 一次性切换所有活跃 writer 到无版本语义目录，并由 guard 证明没有漏网旧写路径；
4. 更新运行手册、正负向测试和 legacy 只读诊断；
5. 在临时 fixture 中显式绕过 production gate，完成 source → split → ROI →
   candidate → review gate → release → shadow promote 全链路验证；
6. 将上述代码、测试和文档作为一个原子发布单元合入后，最后打开 create gate，并把新
   run 默认目录切换为 `workspace/data-staging`；
7. 保留现有 `data-rebuild` 和历史 metadata，不执行数据移动或清理。

步骤 1–5 的任何中间提交都不得部署为可创建新 run 的版本；若 writer、双身份或 fixture
验证未全部通过，gate 必须继续关闭。
