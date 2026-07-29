# 项目内唯一数据入口与 V4.1 全链路重建设计

> 日期：2026-07-29
>
> 状态：已按 2026-07-29 独立审查修订，待复审和实施计划
>
> 适用范围：当前 V4.1 数据、派生媒体、人工审核和训练 release
>
> 唯一活跃数据根：`<repo>/workspace/data`

## 1. 目标和范围

本轮改造解决两个已经确认的问题：

1. 项目同时存在根级 `data/`、外部 `tensile-data/current` 和
   `workspace/data` 等多个数据入口，容易误读实际权威数据；
2. 当前 release 和已有派生产物已经迁入 `workspace/data`，但从 110 个原视频和标注
   CSV 重新生成训练 release 的上游链路仍包含旧路径，无法完成 clean-room 重建。

完成后必须满足：

- `workspace/data` 是 main 唯一允许消费的活跃 V4.1 数据根；编排器只能在受控
  `workspace/data-rebuild/<id>` staging 中读写候选制品；
- `workspace/runs` 继续保存实验 checkpoint、adapter、merged、评测和日志；
- `workspace/models` 继续保存发布模型和模型归档；
- 根级 `data/` 不再承担入口、兼容或说明职责，验收后从仓库移除；
- 可以从 110 个原视频和标注 CSV 建立源数据清单，并继续执行到不可变训练 release；
- 需要人工操作的 ROI 和候选帧审核是显式暂停点，不伪装成全自动步骤；
- 开发机使用 UV，训练机的数据流水线使用 conda `agent` 环境。

## 2. 非目标

本轮不包含：

- 把 `workspace/runs` 或 `workspace/models` 改名或移动到 `data`；
- 修改 V4.1 标签协议、Prompt、采样策略或训练超参数；
- 修改现有不可变 release 的正文、路径字符串或内容 hash；
- 重新训练模型、合并模型或执行 GPU 推理；
- 重写历史 V2 数据；
- 自动替代人工 ROI 判断和候选帧审核；
- 将视频、帧、模型权重或训练输出提交到 Git。

## 3. 已确认的现状

训练机当前实际资产为：

```text
workspace/
├── data/      # 约 7.1 GB，110 个源视频、标注、派生数据和 release
├── models/    # 约 82 GB，发布模型与归档
└── runs/      # 约 309 GB，训练和评测产物
```

因此 `workspace` 是“项目本地产物根”，不是数据目录本身。把整个 `workspace` 重命名为
`data` 会错误地把模型和训练过程资产归类为数据，并破坏现有实验路径。

现有迁移校验已经证明：

- `workspace/data/source/videos` 有 110 个 MP4；
- `all_videos_tag.csv` 有 110 行，是源视频语义标签的权威输入；
- `video_mapping.csv` 有 110 行，是标准化文件名到原始文件名和来源目录的来源追踪输入；
- `workspace/data` 内没有符号链接；
- 从旧外部根迁移的 20,718 个受管文件、总字节数和 SHA-256 一致；
- `v4.1.0-ecb5aeb9657c` 的 1678 个训练样本通过完整媒体校验。

但默认 ROI 只读检查会把旧式 `data/01_videos/...` 解析为
`workspace/data/data/01_videos/...`，证明“现有产物已迁移”不等于“上游重建链路已迁移”。

开发机与训练机目前还存在一项实施前门禁：两端 `main` 的最终 tree 相同，但最近 16 个
同标题提交使用了不同 commit identity。开发机 `HEAD` 为 `aaa17c16...`，训练机
`HEAD` 为 `b6b5a61...`。在形成同时包含两端历史的协调提交前，不得同步代码或执行重建。

## 4. 方案选择

### 4.1 采用方案：保留 Workspace，固定唯一数据子根

最终结构：

```text
mVllm_2/
├── workspace/
│   ├── data/
│   │   ├── source/
│   │   │   ├── videos/
│   │   │   ├── annotations/
│   │   │   └── splits/
│   │   ├── derived/
│   │   │   ├── roi_videos/
│   │   │   ├── subvideos/
│   │   │   ├── frames/
│   │   │   └── metadata/
│   │   └── releases/
│   ├── runs/
│   └── models/
├── pipeline/
├── finetune/
└── docs/
```

根级 `data/` 中当前只有说明文件和指向外部目录的软链接。其说明内容迁入当前 runbook
后，删除该目录。删除软链接只删除链接本身，不删除链接指向的外部目录。

### 4.2 未采用：将 `workspace/data` 提升为根级 `data`

该方案语义可行，但会修改训练配置、release runtime、测试、文档和大量冻结身份引用，
而且不能带来额外能力。当前项目已经把训练和模型资产统一放入 `workspace`，继续使用
`workspace/data` 的迁移成本最低。

### 4.3 拒绝：将整个 `workspace` 重命名为 `data`

该方案会把约 391 GB 的模型和训练产物错误归类为数据，并使所有
`workspace/runs/...`、`workspace/models/...` 路径失效。

### 4.4 Promote 方案选择

采用“不可变制品逐项晋级、release 最后提交”，不替换整个 `workspace/data`：

- staging 中的 source snapshot、ROI manifest、ROI media、candidate plan、candidate
  media、review batch 和 release 都使用内容寻址目录；
- promote 在同一文件系统内把每个尚不存在的内容寻址目录原子重命名到
  `workspace/data` 对应区域；
- release 目录最后晋级，它的出现是本次 promote 的唯一提交点；
- promote 不改写 `source/videos`、`source/annotations`、现有 split、现有 release 或
  无版本目录，也不切换 `workspace/data` 本身。

未采用以下方案：

- 整体替换 `workspace/data`：目标本来存在，跨多个目录无法获得可移植的原子交换和可靠
  回滚；
- 逐文件覆盖或合并：中断后会形成新旧批次混合状态；
- 用软链接切换整个数据 generation：会改变当前物理目录约束和大量既有消费路径。

## 5. 唯一入口约束

### 5.1 数据上下文

新增根作用域的 `DataContext`，集中提供：

- `source/videos`
- `source/annotations`
- `source/splits`
- `derived/*`
- `releases/*`
- `resolve_artifact()`：把语义路径和冻结 legacy 路径解析到当前 context；
- `semantic_path()`：只生成 `source/...`、`derived/...` 或 `releases/...` 路径。

`DataContext` 有且只有两种构造方式：

1. `current_data_context(project_root)`：固定返回 `<repo>/workspace/data`，供正常活跃代码
   使用；
2. `data_context_for_root(project_root, data_root, purpose="rebuild")`：只允许显式传入
   `<repo>/workspace/data-rebuild/<rebuild-id>/data`，供编排器隔离运行。

禁止通过环境变量、marker、profile、当前工作目录或用户目录推断数据根。现有
`current_data_paths()` 保留为 `current_data_context()` 的兼容薄封装，完成调用方迁移后
再评估删除；不得继续新增 `compatibility_workspace` 语义。

source bootstrap 同时接收只读 current context 和可写 rebuild context，用于把源输入
复制进 staging；完成 `source_snapshotted` 后，所有阶段的核心函数必须显式接收同一个
rebuild `DataContext`。命令行可以默认使用
`current_data_context()`，但编排器必须显式传入 rebuild context；阶段内部不得重新调用
默认 context。这样 staging 中的 legacy `data/01_videos/...` 才会映射到同一 staging
context 的 `source/videos/...`。

### 5.2 路径约束

禁止在 main 活跃代码中新增：

- `data/current`
- `data/01_videos`
- `../tensile-data/current`
- `.compat/workspace`
- `TENSILE_DATA_HOME`
- 用户目录绝对路径

历史 manifest 中已经冻结的 `data/01_videos/...` 等字符串允许保留，但读取时必须经过
统一的 legacy-to-semantic 解析器，映射到 `workspace/data/source/videos/...`。调用者
不得自行拼接路径。对于 rebuild context，同一字符串必须映射到
`<rebuild-root>/data/source/videos/...`。绝对冻结路径只允许提取已知 legacy 后缀；
无法映射的绝对路径必须报错，不能原样回退。

### 5.3 目录与扫描约束

- Git 忽略整个 `workspace/`；
- 正常运行的新增数据输出必须位于 `workspace/data`；
- 编排器 staging 是唯一例外，只能位于
  `workspace/data-rebuild/<rebuild-id>/data`，不能成为训练或服务默认输入；
- 训练输入和输出继续位于 `workspace/runs/<experiment-id>`；
- 发布模型继续位于 `workspace/models/releases`；
- 已冻结 release 始终只读。

旧路径门禁不能只扫描 Python。CI 扫描范围包括活跃 Python、shell、YAML、JSON、
`README.md`、正式 runbook、配置生成器和测试所调用的 fixture。处理方式只有三种：

- 活跃入口：迁移为 `workspace/data` 或 `DataContext`；
- 历史入口：移动到明确的 `archive/`，并保证活跃入口不引用；
- 冻结 artifact 或专门的 legacy 映射测试：进入带文件、行号和理由的 allowlist。

`finetune/MiniCPM/config/active/` 中现存的外部根和 `.compat/workspace` 路径必须迁移；
`docs/DATA_PROCESSING_RUNBOOK.md` 中的 `data/current` 小样本输出必须迁移后，根级
`data/` 才能删除。

## 6. 重建链路

### 6.1 阶段 A：源数据初始化

新增正式 source bootstrap 入口，从以下三个物理输入开始：

```text
workspace/data/source/videos/*.mp4
workspace/data/source/annotations/all_videos_tag.csv
workspace/data/source/annotations/video_mapping.csv
```

两份 CSV 的职责固定如下：

- `all_videos_tag.csv` 是训练语义权威输入。连接键为 `id`，必须匹配
  `video_<4 digits>`；`video_path` 的 basename 必须等于 `<id>.mp4`。
- `video_mapping.csv` 是来源追踪权威输入。连接键为 `标准化文件名`，必须等于
  `<id>.mp4`；`原始文件名` 和 `来源目录` 必须非空。
- `all_videos_tag.csv` 必须包含当前 13 列：
  `id`、`video_path`、`断裂时间点`、`断裂模式`、`材料类型`、`清晰度`、`断裂位置`、
  `断裂帧数`、`视频时长`、`视频帧率`、`视频总帧数`、`has_fracture`、`is_abnormal`。
- `video_mapping.csv` 必须包含当前 8 列：
  `标准化文件名`、`原始文件名`、`来源目录`、`材料类别`、`状态`、`duration`、
  `resolution`、`codec`。`状态` 当前允许 `existing` 和 `new`，只作来源审计。
- 两表必须各有 110 个唯一连接键，并与 110 个 MP4 严格一一对应。
- `all_videos_tag.csv` 的 `材料类型` 是训练语义权威；`video_mapping.csv` 的
  `材料类别` 是历史来源描述，只做审计。当前基线已有 6 处不一致，必须进入差异报告但
  不阻断，也不得反向覆盖 `材料类型`。
- 两表中的历史 duration、resolution、codec、帧率和帧数只作为迁移审计值；
  当前媒体技术属性以本次 `ffprobe` 结果为准。差异写入报告，但不改变源语义标签，也不
  单独阻断；无法 probe、非有限值或不合法分辨率才阻断。
- 两份 CSV 的完整文件 SHA-256、逐行规范化 hash 和 schema 都进入 source inventory；
  不允许忽略 `video_mapping.csv`。

bootstrap 负责：

1. 校验视频 ID 与 CSV 一一对应，必须恰好覆盖 110 个唯一 ID；
2. 将 110 个视频和两份 CSV 以普通物理文件原子复制到 staging 的 `source/`；禁止
   symlink 和 hardlink，复制后逐文件验证 size 和 SHA-256；
3. 对 staging 副本使用 `ffprobe` 读取 fps、时长、帧数和分辨率；
4. 生成语义路径，不再生成 `data/01_videos/...`；
5. 在 staging 生成内容寻址的
   `derived/metadata/source_snapshots/<source-snapshot-id>/video_meta.json`；
6. 在同一 source snapshot 中生成 splits 和 split decision log，不覆盖当前
   `source/splits/*.json`；
7. 输出 source inventory、输入文件 hash、视频 hash 和校验报告；
8. 支持 `--check-only`，默认不复制或覆盖已有文件。

staging 中的 source 副本只用于隔离重建，不进入 promotion inventory。晋级 release
继续使用 `source/...` 语义路径，promote 前必须再次证明 current source 与 staging
source 的逐文件 hash 完全相同。ROI/review `reuse` 所需的小型冻结 decisions 和 manifest
也复制到 staging 并校验；后续阶段不得直接读取 current context。

`source-snapshot-id` 固定为 `source-snapshot-<12 hex>`。摘要输入包括按 video ID 排序的
视频 SHA-256、两份 CSV 的规范化内容、source schema、split policy，以及规范化 ffprobe
结果。fps 保存为最简整数分数，帧数和分辨率保存为整数，duration 保存为整数微秒；
禁止把本机绝对路径、mtime 或 ffprobe 日志文本写入 identity。

split 算法冻结为 `split-policy/v1`：Python 标准 `random`、`seed=42`、
`test_ratio=0.2`、`n_folds=3`；标签数不超过 2 的稀有断裂类型只进入各 fold train，
其余记录按 type/location 合并 strata 分配 test 和三折，行为与当前归档算法一致。新实现
位于活跃模块，不导入 archive 脚本。对当前 110 视频基线，生成的七个 split 必须与现有
split 的成员集合和规范化 hash 完全一致；不一致时停止并输出逐 split diff。若源数据
发生变化，则必须显式创建新 source snapshot；只有算法行为变化时才提升 split policy，
不能静默改变 v1。

golden membership hash 定义为：读取 `video_ids`，按字符串排序，以无空白 JSON array
编码并追加 LF，再计算 SHA-256。当前基线为：

| Split | 数量 | Golden membership SHA-256 |
| --- | ---: | --- |
| `fold_0_train` | 59 | `4cc0a634f62cd15c18e0f25760c994b387304faa4e91cfdf228db4f89f5d3264` |
| `fold_0_val` | 30 | `890a05ede9c01fa57fb0abc2342726cdb6c988ab0e3d6f510f6d66d808874b7a` |
| `fold_1_train` | 59 | `da29fb9b64f8b4fd053601d842213d8e7df64c9aafa8852cd721abcd42a12723` |
| `fold_1_val` | 30 | `f8846307234843a3ffd8afdeffbe1eb11a35ba2de324b9d2cd86bcbf5bed4cce` |
| `fold_2_train` | 66 | `e278f81166ddbe9db26ee55f68ebb24e8de4f6e1796d4f92d9665327c491d14b` |
| `fold_2_val` | 23 | `68aca105e1b35945bdafde8343acc36312c45910618c5692a16ae20ae890f336` |
| `test` | 21 | `553db89d302449c4d8640362db5da77678335bba109005ed480f44ded3f09e2d` |

### 6.2 阶段 B：ROI 决定和冻结

两种模式必须显式选择：

- `reuse`：复用与 110 个源视频 hash 完全匹配的冻结 ROI decisions；
- `review`：启动 Streamlit UI，重新人工确认 110 个视频的 ROI。

复用模式必须验证每个源视频的 SHA-256、尺寸和 ID。任意一项不匹配就停止，不能部分
沿用。人工模式完成前，编排器输出 `waiting_for_roi_review` 状态并退出成功，不继续生成
媒体。

`reuse` 是 fail-closed 模式：身份不匹配时返回失败，不得自动切换成 `review`。只有用户
显式传入 `--roi-mode review` 才能创建或恢复人工队列。

### 6.3 阶段 C：ROI 与候选媒体

依次执行：

1. 冻结 ROI manifest；
2. 物化保持原时间轴的 ROI 视频；
3. 生成内容寻址候选计划；
4. 生成候选 MP4；
5. 生成模型实际使用的 MiniCPM 采样帧；
6. 验证视频时长、fps、帧映射和媒体 hash。

所有旧式路径必须由统一解析器转换；`--check-only` 必须在不调用 ffmpeg 的情况下覆盖
全部 110 个源视频。

各阶段必须接收上一阶段的显式 artifact 路径，不能依赖硬编码批次 ID或
`workspace/data` 默认值。`check-only` 可以检查 `ffmpeg`/`ffprobe` 是否存在，但不得
调用 ffmpeg、加载模型权重或写入输出目录；处理器身份从冻结 manifest 读取并校验。

### 6.4 阶段 D：V4.1 审核

同样提供两种模式：

- `reuse`：复用与候选批次身份、帧 hash 和策略版本完全一致的冻结 review batch；
- `review`：生成新队列并暂停，等待人工完成 observed、incipient 和必要的异常审核。

自动稳定阴性门禁可以自动执行，但不能替代需要人工判断的队列。人工决定未完成时不得
构建 release。

`review reuse` 同样 fail closed。候选批次、帧 hash、策略版本或 source snapshot 任一
不匹配即失败；只有显式 `--review-mode review` 才生成新队列并进入
`waiting_for_candidate_review`。

### 6.5 阶段 E：不可变训练 release

release 构建必须：

1. 验证 source、ROI、候选媒体、采样帧、review batch 和标签契约的完整 provenance；
2. 生成新的内容寻址 release ID；
3. 拒绝覆盖已经存在的 release；
4. 生成三折训练和验证 JSON；
5. 执行 schema、媒体存在性、媒体 hash、split 隔离和样本计数校验；
6. 输出 machine-readable summary。

现有两个 release 只用于回归比较，不允许重建后覆盖。

release provenance 必须直接绑定 source snapshot ID，而不是只记录当前
`source/splits` 路径；这样 staging 生成的 split 和晋级后的 release 可以在不改写全局
split 的情况下复现。

## 7. 编排入口

新增唯一主入口：

```bash
python pipeline/scripts/rebuild_v4_1_data.py \
  --source-data-root workspace/data \
  --roi-mode reuse \
  --review-mode reuse \
  --run-root workspace/data-rebuild/<rebuild-id>
```

`run-root` 的固定布局为：

```text
workspace/data-rebuild/<rebuild-id>/
├── data/                   # 与正式 data 相同的语义布局，阶段只读写此 context
├── control/
│   ├── rebuild.json        # 状态机、输入身份和当前阶段
│   ├── commands.jsonl      # 规范化命令和环境身份
│   ├── promotion.json      # 晋级 inventory、journal 和提交状态
│   └── reports/
└── logs/
```

编排器职责仅限于阶段编排、状态记录和门禁，不重复实现各阶段业务逻辑。状态机固定为：

```text
initialized
→ source_validated
→ source_snapshotted
→ roi_validated | waiting_for_roi_review
→ roi_media_ready
→ candidate_media_ready
→ review_validated | waiting_for_candidate_review
→ release_validated
→ ready_to_promote
→ promoted
```

关键行为：

- 所有阶段通过 rebuild `DataContext` 写入隔离 `data/`，不覆盖当前权威数据；
- 初始化时统计 source 和待复用制品字节数，并为预计新媒体加 20% 安全余量；可用空间
  不足时在复制或 ffmpeg 前失败。每阶段开始前重复空间检查；
- 支持 `--check-only`；
- 恢复时重新计算已完成阶段的输入和输出 hash；任一漂移则从该阶段失败，不自动重跑或
  删除；
- 每阶段保存 source snapshot、输入 hash、输出 hash、规范化命令、Git commit、Python
  executable、依赖摘要、ffmpeg/ffprobe 版本和完成状态；
- 遇到人工审核阶段时明确暂停；
- 只有 `ready_to_promote` 才允许执行单独的 `promote` 子命令；
- `promote` 前再次验证 source fingerprint、Git identity 和当前权威数据未变化。

“只有一个入口”指操作入口统一，不意味着把人工步骤隐藏或自动跳过。

### 7.1 Promote 协议

命令固定为：

```bash
python pipeline/scripts/rebuild_v4_1_data.py promote \
  --run-root workspace/data-rebuild/<rebuild-id>
```

执行顺序：

1. 打开 `workspace/data/.locks/v4-1-promote.lock` 并持有 OS advisory lock；判断依据是
   锁能否获取，不是锁文件是否存在，锁已占用则失败；
2. 校验 staging 与 `workspace/data` 的 `st_dev` 相同，不同则失败，禁止退化为复制；
3. 对比启动时记录的 source 视频、两份 CSV、已复用 artifact 和 Git identity；
4. 从 `promotion.json` 读取完整 inventory，拒绝 inventory 外路径；
5. 按 source snapshot、ROI、candidate、review、release 的顺序晋级内容寻址目录；
6. 目标不存在时才执行 rename；若已存在，只在完整 tree hash 相同且 provenance 相同时
   记为 `already_present`，否则失败；
7. 每次同文件系统原子 rename 后同步写 promotion journal；
8. release 最后 rename；随后把状态改为 `promoted`，这是唯一提交点。

tree hash 统一按相对路径排序，并对每项记录类型、文件字节数和 SHA-256；不包含 mtime、
uid、gid 或绝对路径。symlink、文件 hardlink 和特殊文件直接拒绝，不能进入 inventory。

任何中断发生在 release 晋级前，都不会改变当前可消费 release。恢复命令根据 journal
重新校验并继续；已经晋级但尚未被 release 引用的内容寻址目录保留为不可达制品，不自动
删除。清理必须由单独的 `prune-orphans --check-only` 生成清单，并在用户明确确认后执行。

release 一旦晋级即保持不可变，不提供“回滚覆盖”。如果内容错误，创建新的 source
snapshot 和 release；旧 release 继续作为可追溯基线。`promote` 不修改任何 active
pointer，因此回退消费方只需继续绑定旧 release ID。

## 8. 开发机和训练机分工

### 8.1 开发机

开发机使用 UV，负责：

- 路径解析器、source bootstrap 和编排器实现；
- 单元测试、fixture、静态检查和文档；
- 使用小型假视频或 mock ffprobe 完成轻量测试；
- Git 提交和同步。

典型命令：

```bash
uv run pytest tests/<target>
uv run python pipeline/scripts/rebuild_v4_1_data.py --check-only
```

开发机不执行 110 个视频的完整媒体物化，不执行训练和 GPU 推理。

### 8.2 训练机

训练机使用 conda，不使用 UV。数据流水线固定使用：

```text
/home/liuyang/miniconda3/envs/agent/bin/python
```

该环境当前具备 pandas、Streamlit、Pillow 和 OpenCV；系统提供
`/usr/bin/ffmpeg` 与 `/usr/bin/ffprobe`。

训练、合并和 GPU 推理仍使用项目既有的 `cpm45` 环境或对应专用入口，本设计不改变其
职责。

训练机负责：

- 对 110 个真实视频执行 source bootstrap；
- 运行 ROI 和 candidate 的完整媒体校验与物化；
- 执行人工审核 UI；
- 构建和验证完整 release；
- 保存大文件和运行证据；
- 将轻量 summary、manifest 和报告同步回 Git 管理目录。

### 8.3 双机 Git 协调门禁

本轮已确认两端共同基线均为 `38ab65e9...`，两个不同 `HEAD` 的 tree 均为
`71df35fb...`。这说明内容等价，但 commit identity 不等价；不能把“同 tree”当作已经
同步。

实施前固定执行以下非破坏性协调流程：

1. 两端分别保存 branch、HEAD、status、共同基线、`git log --left-right` 和每个独有
   提交的 stable patch-id；
2. 任一工作区不干净时停止。本机现有 `README.md` 和本设计文档必须分别确认范围并形成
   有意、原子化的文档提交，不能 stash 后遗忘或覆盖；
3. 若最终 tree 或 patch-id 序列不同，先逐项审查实际 diff，不得自动协调；
4. 若 tree 相同且 patch-id 序列等价，在开发机创建临时协调分支，保留训练机 HEAD 为
   显式 ref，然后创建一个双父 merge commit；merge tree 必须仍为已验证的相同 tree；
5. 后续实现提交只建立在该协调提交之上；
6. 默认不 push。只有用户明确授权目标远端和分支后才 push；训练机随后只能
   fast-forward 到协调后的提交，禁止 force push、hard reset 或重复 cherry-pick；
7. 同步完成后再次记录两端 branch、HEAD、status，必须 HEAD 相同且工作区干净，才允许
   训练机重建。

若无法把训练机 HEAD 作为 ref 安全传入开发机，使用只含 Git objects/refs 的 bundle
传递，不使用工作区文件复制冒充 Git 同步。

## 9. 迁移与删除顺序

删除按以下顺序执行：

1. 完成 `DataContext`、source bootstrap、阶段参数化、编排器、扫描门禁、测试和文档；
2. 按 8.3 形成双机协调提交并完成授权后的 fast-forward 同步；
3. 在隔离根完成 110 个视频的全链路 `reuse` 重建；
4. 验证新 release 媒体、hash、三折隔离、样本统计和 promotion inventory；
5. 执行 promote，以新 release 目录的原子出现作为提交点；
6. 从晋级 release 再运行一次完整只读验收；
7. 扫描全部活跃代码、配置和正式文档，确认不读取根级 `data/` 或外部根；
8. 删除仓库根级 `data/current`、`data/archive` 软链接和已迁移说明文件；
9. 删除根级 `data/` 后重复开发机测试和训练机只读验收；
10. 保留外部 `tensile-data/current`，并记录文件数、总字节数和关键 manifest hash；
11. 外部 V4.1 旧副本不属于本轮自动执行范围；只有用户在查看验收证据和精确删除清单后
    再次明确授权，才可单独删除。

根级 `data/` 的删除可以随代码切换提交；外部 7.1 GB 数据删除必须在训练机完整验收后
单独执行，不与代码提交混在一起。任何清理都不能使用未解析变量、宽泛 glob 或递归删除
workspace 根。

## 10. 失败处理

- 源视频或 CSV 不满 110 个：停止，不生成部分 metadata；
- ID、视频 hash 或标注冲突：停止并输出逐项差异；
- legacy path 无法映射：停止，禁止回退到外部根；
- conda 环境缺少依赖：停止并报告缺少项，不临时使用系统 Python；
- `reuse` 模式下 ROI 或 review 冻结证据不匹配：停止；不得自动进入人工模式；
- `review` 模式下人工决定未完成：保存 waiting 状态并成功退出，不继续下游；
- ffmpeg 中途失败：保留隔离运行日志，未完成批次不得发布 manifest；
- 目标 release 已存在：拒绝覆盖；
- 当前权威数据在重建期间变化：拒绝 promote；
- Git 两端状态不一致：停止同步，不强制覆盖。
- promote 中断：release 未晋级时按 journal 恢复；不自动清理已晋级的不可达制品；
- promote 目标同名但 tree hash 或 provenance 不同：停止并保留证据。

## 11. 测试策略

### 11.1 开发机自动测试

- `current_data_paths()` 只返回 `workspace/data`；
- rebuild `DataContext` 只接受 `workspace/data-rebuild/<id>/data`，且阶段不会回落到
  `workspace/data`；
- legacy 路径映射覆盖相对路径和冻结绝对路径；
- source bootstrap 检测两份 CSV 与视频的缺失、重复、额外行、连接键和材料冲突；
- source bootstrap 输出稳定 hash 和确定性 split；
- 当前 110 视频 fixture 的七份 split 与冻结 golden hash 一致；
- ROI `--check-only` 可以解析全部 fixture；
- 编排器正确暂停和恢复人工阶段；
- release 构建拒绝覆盖；
- promote 覆盖锁竞争、跨文件系统、CAS 漂移、同名同 hash 幂等、同名异 hash 拒绝、
  中断恢复和 release-last 提交；
- 活跃 Python、shell、YAML、JSON 和正式文档扫描不出现未 allowlist 的禁用入口；
- 文档链接和命令示例有效。

### 11.2 训练机真实验收

- 110 个 MP4 与 110 条标注一一对应；
- `ffprobe` 成功覆盖全部视频；
- ROI `--check-only` 覆盖 110 个视频；
- ROI 视频和候选媒体完整生成或内容寻址复用；
- MiniCPM 实际采样帧存在且映射正确；
- review reuse 的所有身份和 hash 一致；
- 新 release 通过 `--verify-media`；
- 三折 train/val 无 source 泄漏；
- 隔离重建不读取外部 `tensile-data/current`；
- promote 前后的 source fingerprint 不变，release 是最后晋级的目录；
- main 活跃代码在根级 `data/` 删除后继续通过全部校验。

## 12. 完成标准

以下条件全部满足才称为“全链路打通”：

1. `workspace/data` 是唯一活跃数据入口；
2. 根级 `data/` 已从 main 和仓库结构中退役；
3. 当前代码不依赖外部 `tensile-data/current`；
4. source bootstrap 能从 110 个视频和标注 CSV 生成完整 metadata 与 splits；
5. ROI、候选媒体、采样帧、审核和 release 阶段都能通过统一入口执行；
6. 人工阶段能够明确暂停、复用或恢复；
7. 在训练机 conda `agent` 环境完成一次隔离 clean-room 重建；
8. 新 release 通过完整媒体、hash、schema 和 split 验收；
9. 开发机与训练机的 Git 提交和轻量证据已同步；
10. 外部旧数据根只有在上述条件完成后才进入最终删除步骤。

第 10 条只表示“具备申请删除的资格”，不构成删除授权。

## 13. 实施分解

本设计按以下顺序进入实施计划，每阶段都必须可以独立提交和验证：

1. **Git 协调准备**：生成两端 identity、patch-id 和 tree 对比报告；形成协调提交；
2. **路径基础层**：实现 `DataContext`、严格 legacy 解析和全类型旧路径扫描；
3. **Source snapshot**：实现双 CSV 契约、ffprobe inventory、split-policy/v1 和 golden
   回归；
4. **阶段参数化**：ROI、candidate、review、release 核心函数显式接收 context 和输入
   artifact，移除硬编码批次身份；
5. **编排与恢复**：实现状态机、check-only、waiting 状态、hash 恢复门禁；
6. **Promote**：实现 inventory、锁、CAS、同文件系统原子 rename、journal 和
   release-last；
7. **活动入口迁移**：更新 active YAML、runbook、README 和配置生成器，建立 allowlist
   扫描测试；
8. **训练机验收**：在 conda `agent` 环境完成隔离 rebuild、promote 和晋级后复验；
9. **根级入口退役**：删除仓库根级 `data/`，重复扫描和回归；外部副本继续保留。

实施计划不得把第 8 阶段伪装成本机可完成的测试，也不得把第 9 阶段扩展为删除外部
7.1 GB 数据。
