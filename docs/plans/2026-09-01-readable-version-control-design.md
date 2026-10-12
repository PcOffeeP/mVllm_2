<!-- DOCUMENT-CONTRACT
Purpose: 定义 mVllm_2 已确认的可读版本控制目标架构，作为后续实施规划、迁移和验收的设计依据。
Scope: 覆盖数据、Prompt、训练、模型、测评五类版本的命名、责任边界、状态流、引用关系、双机管理、失败处理、迁移和验证；不展开文件级实施任务。
Must Preserve:
- 面向使用者的活动流程使用五类可读完整版本名，不以内容哈希、短前缀或自动 LATEST 作为日常选择方式；DVC 可以在内部保留哈希。
- 数据处理中间产物与正式版本分离；正式数据 payload 与身份字段、保留模型和正式测评封存后只增不改；数据 `release.yaml` 仅允许通过 Git 修改受控状态字段；holdout 继续保持训练禁用、真值隔离和一次性授权。
- 每个训练版本保存实际使用的数据版本、完整 Prompt 和完整训练参数；三折属于同一训练版本，独立全量训练另建一个full范围训练版本。
- 数据、训练、模型晋级和测评必须显式选择完整版本；服务必须显式选择运行模式并由 MLflow alias 解析精确 Model Version，`models/current` 只作为经过校验的本地物化缓存。
- DVC 只管理数据 pipeline 和数据产物；MLflow 管理训练运行、实际参数、模型、指标、测评和运行状态；Git 管理代码、Prompt、配置、文档及 MLflow 导出的轻量 manifest。
- YAML 配置是运行定义，MLflow 是实际训练、模型和测评结果的权威来源；`manifest.yaml` 由 MLflow 单向导出并通过 Git 跨设备同步。
- 不设置独立 `status.yaml`，不建立 YAML 与 MLflow 的双向同步或重复事实来源；训练实际输入保存在 `input/`，运行指标与大型产物由 MLflow 管理。
- 每项已确认约束在实施时必须落入权威文档、机器可读契约、程序校验或测试证据，不允许只存在于设计讨论或聊天记录中。
- MLflow Model Registry 使用稳定 Registered Model `mVllm2` 和 `candidate`/`production` 两个可变别名；正式模型沿用 `model-v<协议>-r<N>` ID并映射到唯一数值 Model Version，`models/current` 只缓存 alias 精确目标。
- 模型采用两阶段登记：训练完成后先创建无 `eval_id` 的 staging Model Version，正式 eval 必须精确引用其可读身份与数值版本；eval 通过后才绑定 `eval_id`，未绑定通过结论的模型不得进入 candidate/production。
- 设计最终确认后，迁移才可在独立分支实施；本机和训练机验证通过后仍需用户明确决定是否合并。
Non-goals:
- 本次架构不引入 Hydra、W&B、lakeFS 或其他额外配置/实验平台；采用普通 YAML、DVC 与 MLflow，不为未来工具预建兼容层。
- 不因上游版本变化自动重训模型，也不版本化每个数据处理中间阶段或 checkpoint。
- 本文不创建迁移分支、不移动现有产物、不修改运行代码，也不授权删除训练机文件。
-->

# 可读版本控制架构设计

> 状态：设计已确认；核心基础设施与正式入口迁移已按确认工程范围交付，2026-09-14 已合并 Codeup main 并同步训练机代码。本文保存设计规则及决定依据；执行状态统一见[项目TODO](../project-todo.md)。实际模型质量、GPU/服务成功路径及真实硬盘组合恢复仍未验收，不因工程迁移完成放宽门禁。

> 模型命名：经过语义化长名称和 p/d/t 短编号两轮讨论后，用户决定回到最初的 `model-v<协议>-r<N>` 方案。名称只承担模型类别、契约和顺序身份，基础模型、Prompt、数据、核心训练参数、训练 Run、fold、seed 与内部唯一性全部在 `manifest.yaml` 和 MLflow 中展示。

## 1. 目标与范围

本设计解决当前项目中代码、输入、中间产物、正式数据、训练运行、模型权重和评测证据混杂，且大量哈希身份直接暴露给使用者的问题。

目标不是建立一个更复杂的 MLOps 平台，而是让使用者能够直接回答五个问题：

1. 当前使用哪一版正式训练数据；
2. 该训练实际使用哪一版 Prompt；
3. 该训练实际使用哪一版训练方案；
4. 保留模型来自哪一次训练；
5. 正式测评评的是哪个模型、哪份数据和哪套评价规则。

成功后的活动链路为：

```text
data-v4.1-rN
      +
prompt-v4.1-rN
      +
train-v4.1-rN 中冻结的训练参数
      ↓
一次完整训练（含适用的三个 fold）
      ↓
model-v4.1-rN
      ↓
eval-v4.1-rN
```

Git 继续正常管理源码、Prompt、普通配置、测试、文档和轻量正式记录的修改历史，但不维护全局“当前版本”注册表，也不保存大型数据、模型或完整实验数据库。

现行任务依赖和受限验收边界以[项目任务台账](../project-todo.md)为准；现行数据处理的双机步骤以[数据处理运行手册](../data-workflow.md)为核对基线。本设计定义迁移后的目标，不把尚未实施的目录和命令写成当前能力。

## 2. 工具选择与责任边界

参考对话提出的核心抽象是：各类对象独立版本化，并由一次训练运行冻结实际输入，形成模型和测评的血缘。这个抽象适用于本项目，予以保留。

当前确认“人的日常入口必须可读、五类对象必须分清、实际运行输入必须可追溯”，并确认由 DVC 的 YAML 文件清晰呈现整个数据处理 pipeline，由 Git/YAML、MLflow 和单向导出的 manifest 分别承担定义、实际记录和跨设备阅读职责。需要继续区分：

- 面向人的版本名、命令和文档是否暴露哈希；
- 工具内部是否允许使用内容哈希保证缓存、完整性和复现；
- 工具引入的自动能力是否值得其部署、同步和维护成本。

各工具方向的最终状态如下：

| 工具或能力 | 最终状态 | 责任边界 |
| --- | --- | --- |
| Git | 确认保留 | 管理源码、配置、Prompt、文档、DVC 轻量文件和 MLflow 导出的正式 manifest。 |
| 人类可读的五类版本 | 确认保留 | data → DVC + 同目录 `release.yaml`；prompt → Git 正式文件；train/eval → MLflow 父 Run；model → 稳定 Registered Model 内的 Model Version；manifest → MLflow 单向导出到 Git。 |
| DVC 管理数据与流水线 | 确认采用 | `dvc.yaml` 是清晰的数据处理 pipeline 视图；DVC 只拥有数据 pipeline 和数据产物，指针文件和内部哈希不作为日常入口。 |
| MLflow 管理 Run、模型和指标 | 确认采用 | 使用内部 SQLite 和独立 artifact store，页面按需在训练机启动并由 Mac 通过 SSH 访问；三折、正式测评和模型别名按本文已确认结构组织。 |
| Hydra 管理配置组合 | 确认不引入 | 当前普通 YAML 足以表达 Prompt、训练和测评配置；不增加继承、组合和覆盖语义，也不预建兼容层。 |
| 检测上游变化、重建数据 | 确认采用“自动发现、手动执行” | DVC 自动报告过期阶段；只有使用者明确发起时才重建 working，正式数据不覆盖，训练和测评不自动启动。 |
| 正式结果 Manifest | 确认采用单向导出 | MLflow 是实际结果来源；正式训练、保留模型和正式测评完成后由 MLflow 导出只读 `manifest.yaml`，再通过 Git 同步。 |

### 2.1 已确认的 DVC 使用边界

- DVC 可以使用内部内容哈希和指针文件；使用者日常不需要阅读或手工维护这些内容。
- `dvc.yaml` 是面向使用者的数据处理 pipeline 入口，必须以清晰的阶段名称展示实际处理顺序、输入依赖、输出和所用参数。
- 人类可读的数据版本名继续承担交流和选择职责；不得要求使用者用 DVC 哈希识别某一版数据。
- DVC 的权威范围止于数据 pipeline 和数据产物，不管理模型权重、训练日志或测评结果；这些对象统一交给 MLflow。
- 人工审查在 pipeline 中明确表现为“审查材料导出 → 人工处理 → 审查结果回收与校验”。DVC 负责两侧的可执行阶段和依赖关系，不伪装成自动完成人工判断；结果未回收并通过校验时，后续数据发布不得继续。
- DVC 不跟踪数据之外的大型产物；模型权重、训练日志和测评结果统一交给 MLflow。

### 2.2 已确认的离线备份边界

- 用户私有的 1TB 移动硬盘不长期连接课题组公共训练机，也不作为日常 DVC pipeline 的默认 remote。
- 移动硬盘承担定期离线备份职责，备份范围限定为正式数据版本和明确认定的重要模型；可重建的 working、中间产物、普通 checkpoint 和本地 DVC cache 不进入常规离线备份。
- 训练机具有足够的大容量存储，继续承担日常数据工作区和 DVC 存储；具体 cache/remote 布局见下一节。
- 移动硬盘离线时不得阻断日常数据处理、训练或测评。备份失败不得改写已经形成的正式版本，也不得在硬盘 catalog 中记录为 `verified: true`。
- 移动硬盘只连接 Mac；由 Mac 主动通过 SSH 从训练机取得指定正式版本并写入移动硬盘，不要求完整数据长期落入 Mac 内置磁盘。
- 备份采用“连接时比较正式对象与硬盘 catalog”的事件驱动方式，并按本设计执行分层完整性检查与真实恢复演练。

### 2.3 已确认的训练机 DVC 存储布局

设计阶段的只读检查确认：项目位于 `/home` 文件系统，训练机另有一块独立的大容量 ext4 数据盘挂载在 `/data`。日常布局确定为：

- `/home/liuyang/文档/mVllm_2` 继续作为项目工作区，并承载项目本地 DVC cache；
- `/data/mVllm_2/dvc-remote/` 作为目标固定路径，承载训练机日常 DVC remote；
- `/home` 与 `/data` 位于不同物理磁盘，前者服务活跃工作，后者保存可由 DVC 恢复的对象；
- `/data` 仍属于同一台公共训练机，不能代替异机备份；正式数据和重要模型继续按离线备份方案复制到私人移动硬盘；
- 当前 `/data` 由系统管理员管理。创建项目目录和配置写权限属于未来实施动作，必须在获准实施后单独核对，不在设计阶段执行。

### 2.4 已确认的 DVC pipeline 主干

`dvc.yaml` 按业务流程而不是按脚本数量拆分，主干固定为七个阶段：

| DVC stage | 面向使用者的含义 |
| --- | --- |
| `source` | 原始数据整理与初始划分 |
| `roi` | ROI 准备、冻结与物化 |
| `subvideo` | 子视频生成 |
| `review_export` | 导出人工审查材料 |
| `review_import` | 回收并校验人工审查结果 |
| `release` | 生成正式数据版本 |
| `release_validate` | 验证正式数据，并准备交给训练流程 |

一个业务阶段可以调用多个内部脚本；这些脚本及其细节参数由阶段命令和配置承载，不为每个脚本额外创建顶层 DVC stage。这样既保留完整依赖关系，也让使用者打开 `dvc.yaml` 时首先看到可理解的业务流程。

DVC 的执行策略固定为“自动发现、手动执行”：

- 输入、参数或代码依赖变化时，DVC 自动判断并报告哪些阶段已经过期，但不在后台自动运行；
- 只有使用者明确发起重建时，才执行指定阶段及其必要下游，不要求无条件从原始数据全部重跑；
- `working/` 中间产物可以按依赖重建和覆盖，已封存 `data-v...` 正式数据绝不原地覆盖；需要发布变化后的结果时必须显式指定新数据版本；
- 执行到 `review_export` 后停止等待人工审查，只有 `review_import` 回收并校验通过后才允许继续 `release`；
- `release_validate` 只报告正式数据已经满足训练入口要求，不自动启动训练、模型晋级或正式测评；
- Git、Prompt 或数据变化最多提示可能需要新实验，是否创建训练或测评版本始终由使用者决定。

### 2.5 已确认的 Git、DVC 与 MLflow 权威边界

| 系统 | 权威对象 | 不负责 |
| --- | --- | --- |
| Git | 代码、Prompt、配置、文档、DVC 轻量文件及 MLflow 导出的正式 manifest | 大型数据、模型文件和指标数据库 |
| DVC | 原始数据引用、数据处理中间产物、人工审查输入/结果、正式数据版本和数据 pipeline | 训练运行、模型权重、训练指标和正式测评记录 |
| MLflow | 实际训练参数、Prompt 与数据版本引用、运行日志、训练指标、模型产物、模型晋级信息、测评指标和报告 | 数据处理 pipeline 与数据文件版本 |

三者通过 `data-v...`、`prompt-v...`、`train-v...`、`model-v...` 和 `eval-v...` 等可读版本关联。Git 负责把轻量定义和已导出的正式结果同步到 Mac 与训练机；DVC 和 MLflow 的大型对象不进入 Git。MLflow 中记录实际使用的 Git commit 和 DVC 数据版本，但不要求使用者用 DVC 哈希识别数据；重要模型的离线备份从 MLflow artifact store 取得，不再由 DVC 重复登记。

### 2.6 已确认的 Git/YAML、MLflow 与 manifest 使用方式

- Git 中的 Prompt、训练配置和测评配置定义“准备运行什么”；训练启动时仍把实际输入冻结到训练目录的 `input/`。
- MLflow 记录“实际上运行了什么以及结果是什么”，包括实际参数、运行状态、指标、日志、模型、测评结果和 Registry 别名，是这些事实的唯一权威来源。
- `manifest.yaml` 只在正式训练完成、模型决定长期保留或正式测评形成完整结论后，由导出程序从 MLflow 单向生成；技术失败、调试运行和普通开发诊断只留在 MLflow。
- 导出的 manifest 是便于人阅读和通过 Git 跨设备同步的机器生成结果快照，不是第二套运行数据库，不反向写回 MLflow，也不由人手工维护。其事实字段封存后不得原地改写；允许重新导出的情况只限下述更正策略。
- 不设置独立 `status.yaml`。训练状态、正式测评运行状态及 `candidate`、`production` 路由状态直接保存在 MLflow；不存在 YAML 与 MLflow 的双向同步或逐字段冲突解决机制。
- 正式 manifest 只回答“这是什么、实际用了什么、结果怎样、完整记录在哪里”，最小内容固定为：

| manifest | 必须包含 | 不包含 |
| --- | --- | --- |
| train | `train-v...`、`record_validity`、数据与 Prompt 版本、基础模型、核心训练参数、fold 完成情况、汇总指标、MLflow 父 Run ID | 完整日志、全部过程指标、checkpoint 清单、完整环境包列表 |
| model | `model-v...`、`record_validity`、来源训练、单折/三折/full-data 范围、基础模型、adapter/merged 产物位置、稳定 Registered Model 名、MLflow 数值 Model Version 与源 Run | 当前 `candidate`/`production` 别名、普通 checkpoint、完整训练日志 |
| eval | `eval-v...`、`record_validity`、被测模型、测评数据与配置、样本范围、核心指标、通过/失败结论、MLflow 父 Run ID | 全部逐样本记录、完整失败样例、实时运行状态 |

- “核心训练参数”和“核心指标”的具体字段由项目训练与测评契约列出；manifest 同时引用冻结配置和 MLflow Run，因此不复制所有字段。逐样本预测、图表、完整失败案例和详细环境信息继续保存在 MLflow artifacts。
- `candidate` 与 `production` 是会变化的实时路由，只从 MLflow Registry 读取，不写入不可变模型 manifest；别名变化不会导致重新导出或改写旧 manifest。
- 更正策略分三类：仅导出器格式、排序或漏字段错误时，MLflow 不变，可幂等重导同一语义 manifest；Registry aliases 和允许变化的运行标签只在 MLflow 更新，不触碰旧 manifest；正式实际输入、权重、指标、结论或来源记录错误时，旧 Run 或 Model Version 的 `record_validity` tag 改为 `invalid`，旧 manifest 只重导这一有效性及可选 `replacement` 字段，原事实字段保留，同时创建新的可读版本与 MLflow 对象并导出新 manifest。
- `record_validity` 的权威位置是 train/eval 父 Run tag 或模型 Model Version tag，合法值仅 `valid|invalid`。下游运行、模型晋级、正式结论引用和服务物化必须拒绝 `invalid`；不得通过改回 `valid` 复活旧事实，需要恢复用途时创建新版本。
- MLflow 使用 SQLite 单文件保存 Run、参数、指标、标签和模型关系等可查询元数据；SQLite 是内部实现，使用者不直接编辑，也不需要学习 SQL。
- 模型权重、预测结果、图表和报告保存到独立 MLflow artifact store，不写入 SQLite。
- MLflow 页面按需启动，默认只在训练机本地监听；Mac 需要查看时通过 SSH 隧道访问，不向公共网络直接开放，也不建设额外的常驻数据库服务。
- SQLite 与 artifact store 计划放在训练机 `/data/mVllm_2/mlflow/` 下的独立子目录；具体路径和权限只在获准实施后配置。

### 2.7 已确认的训练范围与 Run 结构

- 一个 `train-v<协议>-r<N>` 对应一个 MLflow 父 Run，表示一次完整训练方案。
- cross_validation范围保持三折结构：`fold0`、`fold1`、`fold2` 分别对应父 Run 下的三个子 Run，不分配彼此独立的 `train-v...` 版本。
- 父 Run 保存三折共用的数据版本、Prompt 版本、Git commit、完整训练配置、基座模型和环境信息。
- 子 Run 保存各自的数据划分、过程指标、日志、checkpoint、最佳 checkpoint、预测产物和运行状态。
- 三折汇总指标和总体结论写入父 Run；任一必需 fold 未完成时，父 Run 的项目 `workflow_state` 不得进入 `completed`，模型晋级器也不得仅凭 MLflow 原生状态放行。
- 后续 `model-v...` 必须引用父 Run，并说明晋级对象是三折模型集合、指定 fold，还是基于完整数据形成的模型；不得只凭某个子 Run 的内部 MLflow ID解释模型来源。

2026-09-13用户确认独立full训练范围，见[正式迁移Spec](../tasks/2026-09-07-readable-version-control-migration/spec.md#训练与测评事实)：全量训练另建train版本，冻结同一开发release三折划分共同覆盖的全部候选，按媒体身份去重且拒绝标签冲突；不扩展历史采样算法，不用holdout做训练中验证或选择checkpoint。full只执行一次，由父Run记录实际参数、结果和完整产物证据，不创建fold子Run，只产出full模型。仅有completed标记或把fold产物改名，均不能满足full来源门。

### 2.8 已确认的正式测评 Run 结构

- 训练过程中的 `eval_loss`、开发集诊断和 checkpoint 比较保存在训练父/子 Run 内，不获得正式 `eval-v...`。
- 每个形成长期项目结论的 `eval-v<协议>-r<N>` 对应一个独立 MLflow 父 Run，不附着或覆盖原训练 Run。
- 正式测评父 Run 明确引用被测 `model-v...`、来源 `train-v...`、测评 `data-v...`、测评配置、契约版本和 Git commit。
- 当正式测评包含三个 fold 时，fold0、fold1、fold2 作为其子 Run，分别保存预测、指标和失败样例；汇总指标、总体结论及通过/失败状态保存在父 Run。
- 同一模型更换测评数据、评价规则或指标口径时，必须创建新的 `eval-v...`，不得覆盖旧 Run 或把旧指标改写成新口径。
- holdout 正式测评继续遵守训练禁用、真值隔离、预注册和一次性授权；MLflow 只记录授权后的运行与结果，不改变这些安全边界。

### 2.9 已确认的 Model Registry 别名

- 项目只建立一个稳定的 MLflow Registered Model，名称为 `mVllm2`；每个 `model-v<协议>-r<N>` 映射为其中一个不可变的数值 Model Version，并以 `model_id` tag 保存可读模型 ID。
- Registry 中无 alias 的 staging Model Version 表示准备测评或正在验证；`candidate` 只指向已绑定 passed eval、正在等待生产晋级决定的候选模型。
- `production` 指向当前已通过规定质量门并经用户批准用于正式推理的模型。
- 两个别名均属于稳定 Registered Model `mVllm2`，指向其中一个数值 Model Version；它们是项目唯一逻辑路由，不承担不可变模型身份，切换别名不得改写原模型记录。
- 普通 checkpoint 不进入 Model Registry。正式模型 ID 沿用 `model-v<协议>-r<N>`；ID 本身不展开训练路线、fold 或 seed。

### 2.10 已确认的模型文件保存边界

- 普通训练 Run 保存配置、日志、指标和预测；checkpoint 只在训练恢复、模型诊断或选择最佳 checkpoint 仍需要时临时保留，不进入 Model Registry，也不进入常规离线备份。
- 未晋级模型永久保留 YAML/MLflow 实验记录；相关诊断完成且确认不存在恢复或复现实验需要后，权重才可列入清理候选，不能自动删除。
- `candidate` 长期保存 LoRA adapter、精确基座版本、processor/custom code、训练配置和测评证据；私人移动硬盘备份 adapter 与完整身份资料。
- `production` 在 candidate 内容基础上，同时长期保存实际部署使用的 merged 模型；私人移动硬盘同时备份 adapter、merged 模型和完整证据。
- 删除 merged 模型前必须在真实训练环境验证 adapter、精确基座与自定义代码能够重新合并，并确认重新生成结果满足既定加载与推理检查；不能用理论可恢复代替实证。
- 仅保留记录而不再保留权重的历史模型，必须明确标记为“仅证据、不可直接推理”，不得继续使用 `candidate` 或 `production` 别名。

### 2.11 已确认的离线备份与恢复验证

- 不在数据 `release.yaml`、模型 manifest 或 MLflow 中增加 `backup_pending`、`backup_complete` 字段，也不维护独立待办队列。
- 需要备份的源集合由机器计算：全部正式数据，以及带有 `offline_backup_scope` Model Version tag 的模型。模型在首次设置 alias 之前必须写入该粘性范围：进入 `candidate` 前设为 `adapter`，进入 `production` 前设为 `production_bundle`；范围只允许从缺失升级为 `adapter`、再升级为 `production_bundle`，不得因 alias 切走或一次备份完成而降级或清除。
- 移动硬盘连接 Mac 后，备份工具先枚举上述源集合，再核对 `backup_catalog.yaml` 与硬盘实际文件。待备份集合由“源集合缺失项 + catalog 条目对应文件缺失/范围不符/完整性失败项”共同组成；catalog 中存在一行记录本身不能证明备份存在。
- 正式数据备份其 DVC 对象和可读身份资料；`offline_backup_scope: adapter` 备份 adapter 与完整身份资料；`offline_backup_scope: production_bundle` 备份 adapter、merged 模型、正式测评和完整证据。源集合枚举、catalog 重建和完整性验证都必须按该粘性范围决定所需文件，不得依据当前 alias 反推历史角色。
- 每次连接时生成并备份 MLflow SQLite 的一致性快照；不得在数据库写入过程中直接复制可能不一致的文件。
- Mac 经用户确认后通过 SSH 从训练机直接写入移动硬盘，避免大型对象长期落入 Mac 内置磁盘。
- 每次连接都对 catalog 中全部既有对象和本次新复制对象核对文件存在、数量、大小、机器完整性校验和轻量身份资料与 DVC/MLflow 对应关系；底层校验值不作为对象身份或人的日常入口。任一不匹配立即视为 `verified: false` 并进入修复/重备份集合。`backup_catalog.yaml` 至少记录对象 ID、类型、来源、备份时间、备份范围和 `verified: true/false`。
- catalog 使用临时文件校验通过后原子替换，并保留上一份可读快照；catalog 损坏时必须通过硬盘对象目录和训练机源集合重新扫描生成，不能因 catalog 无法读取就假定无需备份。
- 某类正式数据、adapter、merged 模型或 MLflow SQLite 第一次备份时必须执行一次真实恢复演练；备份结构、脚本、硬盘格式或 MLflow 存储方式变化后，以及删除训练机唯一重要副本前，也必须重新演练。普通新增备份只做复制完整性检查。
- 正式数据恢复到临时目录并通过 DVC 识别与 `release_validate`；adapter 恢复后结合明确基座完成加载检查；merged 模型恢复后完成加载与最小推理；SQLite 快照恢复后必须能够查询 Run、指标和模型关系。
- 恢复演练只使用明确临时目录，不覆盖训练机正式产物。任一复制或验证失败均不得写成 `verified: true`，也不得改变训练机正式对象。
- `offline_backup_scope` 不因一次备份成功自动降级或解除。备份成功不授权自动删除训练机上的数据、模型或 MLflow 记录；清理仍需单独形成清单并由用户确认。若拟删除训练机最后一个大型副本，除本次真实恢复演练外还必须存在另一份独立已验证副本，或由用户明确接受移动硬盘成为唯一副本的残余风险。

### 2.12 已确认的单向记录边界

跨设备管理统一依靠 Git：Mac 与训练机通过 Git 同步代码、Prompt、配置、DVC 轻量文件和已经导出的正式 manifest。大型数据、模型权重、逐样本预测和完整日志不经 Git 同步，分别留在 DVC 与 MLflow 的存储中。

记录流向固定为：

```text
Git/YAML + DVC 定义输入 → 训练机实际运行 → MLflow 完整记录 → 导出只读 manifest → Git 跨设备同步
```

此前候选的独立 `status.yaml`、YAML/MLflow 双向同步、逐字段权威表和冲突解决机制均不采用。这样不是依靠额外文件防止 MLflow 出错，而是通过取消重复事实来源，从根本上减少两个系统互相矛盾的机会。

### 2.13 实施时的文档化与机器约束

设计确认不等于仅保留本文件。后续实施必须建立“设计决定 → 权威说明 → 程序约束 → 测试证据”的对应关系：

- `README.md` 提供项目介绍、初次环境准备和文档导航，具体操作由流程说明负责；
- 项目根 [`AGENTS.md`](../../AGENTS.md) 必须删除或替换与目标架构冲突的哈希数据 ID、集合 `index.json`、`LATEST` 和短哈希解析强制规则，改为本文确认的五类可读版本、DVC/MLflow/Git 边界和显式选择纪律；
- `docs/data-workflow.md` 说明 DVC pipeline、七个业务阶段、人工审查关卡、remote/cache 和常用恢复操作；
- `docs/model-workflow.md` 说明 YAML + MLflow、父子 Run、模型晋级、正式测评和 Registry 别名；
- `docs/model-workflow.md` 集中说明备份范围、catalog、一致性快照、完整性验证与隔离恢复；真实移动硬盘和大型组合恢复的验收仍由任务台账跟踪；
- `dvc.yaml`、YAML schema/数据模型、CLI 参数与校验器承担机器可读契约；
- 自动测试覆盖不可覆盖、引用冲突、状态转换、别名切换、catalog 差异计算和恢复校验；
- 实施验收表逐项记录文档位置、实现位置、验证命令、结果和训练机限制，未落到文档或机器约束的设计决定不得标记完成。

能够由程序判断的安全边界必须 fail-closed，不得仅依赖操作手册提醒。权威流程文档在实施完成后还须按项目规则接受独立核查，确认命令、路径、输入和输出与真实代码一致。

## 3. 核心原则

### 3.1 五类对象独立版本化

活动体系只使用以下五类正式版本：

| 对象 | 版本格式 | 含义 |
| --- | --- | --- |
| 正式数据 | `data-v<协议>-r<N>` | 已完成处理和人工审查、用于开发训练或独立验收的数据发布 |
| Prompt | `prompt-v<协议>-r<N>` | 一份实际进入训练输入的完整 Prompt |
| 训练 | `train-v<协议>-r<N>` | 一套实际运行的完整训练方案，包含适用的多折运行 |
| 保留模型 | `model-v<协议>-r<N>` | 从某个训练版本晋级、决定长期保留的模型 |
| 正式测评 | `eval-v<协议>-r<N>` | 对明确模型执行的一轮正式、可长期引用的测评 |

当前协议示例为 `v4.1`。五类 `rN` 各自独立递增，不要求数值相同，也不表达时间先后关系。

版本名不得追加 `final`、`new`、`fixed`、`latest`、日期、seed、fold、checkpoint 或自由文本后缀。用途、状态和完整身份写入对应 YAML、MLflow 和说明文件。

### 3.2 工作产物可变，正式版本只增不改

数据处理中间产物、模型 staging、测评 staging 和尚未结束的训练运行可以修改。正式数据 payload 与身份字段、训练输入、保留模型和正式测评一旦封存，不得原地改变实际内容。数据 `release.yaml` 中的少量生命周期字段是唯一例外，其变化由 Git 留存历史，不改变该数据版本“包含什么”。

正式版本有问题时创建下一轮 `rN`。旧版保持原样，并通过可读状态说明其已被替代或不应继续使用。

### 3.3 版本关系显式记录，不自动猜测

训练、模型和测评必须保存完整可读的上游版本名。程序不得：

- 根据目录中“最新”的项目自动选择；
- 接受短前缀或模糊匹配；
- 从文件内容推导隐式版本；
- 缺少参数时回退到旧路径；
- 因数据或 Prompt 更新而自动启动训练。

### 3.4 实际输入副本是真实训练依据

日常编辑的 Prompt 和训练配置可以继续位于现有代码目录并由 Git 正常管理；它们只是编辑来源。训练准备时复制到训练目录的 `input/`，该副本才是“本次实际使用了什么”的最终依据。

## 4. 目标目录架构

本设计不重排 `pipeline/`、`finetune/`、`tests/` 和 `LlamaFactory/` 等源码目录。主要调整 `workspace/` 的大型产物边界；正式数据目录中的 `release.yaml` 和必要说明文件是明确的 Git 跟踪例外：

```text
workspace/
├── data/
│   ├── source/                         原始视频和原始标注
│   ├── working/                        训练机权威数据处理工作区
│   │   └── round-001/                  可读工作轮次，不是正式版本
│   │       ├── round.yaml
│   │       ├── source_metadata/
│   │       ├── split/
│   │       ├── roi/
│   │       ├── candidate_videos/
│   │       ├── review/
│   │       ├── exchange/               Mac 审查导出与回传接收区
│   │       └── release_staging/
│   └── releases/
│       └── data-v4.1-r1/               正式训练数据
├── runs/
│   └── train-v4.1-r1/                  活跃训练工作目录；完成记录进入 MLflow
├── models/
│   ├── staging/                        待晋级模型
│   ├── materialized/
│   │   └── model-v4.1-r1/              从 MLflow 物化的本地部署副本
│   └── current                         指向本地部署副本的服务链接
└── evaluations/
    └── staging/                        正式测评工作区；完成记录进入 MLflow
```

MLflow 导出的轻量正式记录放在 Git 跟踪的独立目录，不与训练机大型 workspace 混放：

```text
records/
├── prompts/prompt-v4.1-r1.yaml
├── training/train-v4.1-r1/manifest.yaml
├── models/model-v4.1-r1/manifest.yaml
└── evaluations/eval-v4.1-r1/manifest.yaml
```

数据 `release.yaml` 与对应数据放在同一个正式版本目录中；同名 manifest 只由 MLflow 导出工具生成。`workspace/runs` 与 `workspace/evaluations/staging` 是执行工作区，`workspace/models/materialized` 是按需生成的部署副本；训练、模型和测评完成后的权威记录与大型产物都在 MLflow。Git 中的 manifest 只提供正式结果的可读快照和跨设备索引。

历史哈希目录不属于目标活动架构。迁移期间可只读存在，活动入口完成切换后从工作目录移出；是否删除训练机大型历史文件仍按现有授权和归档纪律单独决定。

## 5. 五类版本的责任与结构

### 5.1 数据版本

`workspace/data/source/` 保存原始输入，训练机的 `workspace/data/working/` 保存权威处理过程。source snapshot、split snapshot、ROI manifest、候选计划、候选媒体、审查队列不再分别获得正式版本。

`round-001` 只是一次可丢弃工作轮次的可读标签，不属于五类正式版本。`round.yaml` 记录该轮次的 source 批次、当前阶段、每个阶段负责人和人工审查批次。Mac 不拥有第二个权威 working；它只接收训练机导出的明确审查副本，并把结果回传给同一轮次。

只有人工审查完成、可供训练或独立验收的数据进入：

```text
workspace/data/releases/data-v4.1-r1/
├── release.yaml
├── README.md
├── datasets/
├── media/
└── review/
```

数据版本不属于 MLflow 导出的运行 manifest。DVC 发布阶段在正式数据目录中生成由 Git 跟踪的 `release.yaml`，至少说明：

```yaml
version: data-v4.1-r1
protocol: tensile-vlm/v4.1
state: sealed
purpose: development
training_allowed: true
description: 第二轮人工审查后的正式训练数据
sample_count: 1678
source_batches:
  - batch-2026-07
splits:
  fold0: {train: 1253, validation: 425}
  fold1: {train: 1014, validation: 664}
  fold2: {train: 1186, validation: 492}
```

示例数字仅展示字段含义，不在本设计中重新认定当前数据版本或真实迁移编号。

`release.yaml` 与数据 payload 描述该版本是什么，并直接携带最小生命周期状态。正常版本只需要：

```yaml
status: active               # active | superseded | invalid
```

存在明确替代版本时才增加：

```yaml
status: superseded
replacement: data-v4.1-r2
```

不为数据另建 `status.yaml` 或全局数据注册表。封存后，版本号、协议、用途、样本、标签、媒体、source、split 和 DVC 对象引用均不可修改；只有 `status` 和可选的 `replacement` 可以受控更新并提交 Git。修改时间和原因直接查看 Git 历史及对应 commit message，不在 YAML 中重复保存。发现旧数据存在质量问题时把它标为 `invalid`，DVC 发布校验和训练入口必须阻止继续选择；普通替代关系使用 `superseded`，不借用 MLflow 的训练状态。

为保证同目录但不把大型数据提交进 Git，DVC 的输出边界落在 `datasets/`、`media/`、`review/` 等 payload 子目录，Git 只跟踪同级的 `release.yaml` 和必要说明文件；不得把整个 `data-v.../` 根目录作为一个不可区分的 Git 忽略对象。

数据版本升级条件包括正式样本集合、媒体内容、标签、source 归属、fold 划分或适用协议发生变化。只改变处理代码但没有重新发布数据，不会悄悄改变已有数据版本；新训练仍只能显式选择已经存在的正式版本。

数据版本有两种用途：

```text
purpose: development   可按声明的 train/validation split 用于开发训练和开发测评
purpose: holdout       只用于一次性独立验收，training_allowed 必须为 false
```

holdout 仍属于 data 版本，不增加第六类版本。其目录将可见媒体与受限真值分开：

```text
data-v4.1-rN/
├── release.yaml                 purpose: holdout
├── media/                       评测运行可读取
├── evaluation_inputs/           不含语义真值
├── sealed_ground_truth/         仅获授权评分阶段可读取
└── authorization/               该 holdout 的全局一次性消费状态
```

训练准备入口必须拒绝 `purpose: holdout` 或 `training_allowed: false`。普通开发评测也不能读取 `sealed_ground_truth/`。holdout 的 source 隔离、人工审查、test-split binding 和真值权限是发布前置；去除哈希身份不等于取消这些安全边界。

### 5.2 Prompt 版本

可编辑来源继续使用现有 Prompt 编辑入口；决定用于正式训练时，为完整内容分配 `prompt-v4.1-rN` 并保存为 Git 跟踪的 `records/prompts/prompt-v4.1-rN.yaml`：

```yaml
version: prompt-v4.1-r1
protocol: tensile-vlm/v4.1
system_prompt: |-
  这里保存训练时实际使用的完整系统提示词文本。
user_prompt: |-
  这里保存训练时实际使用的完整用户提示词文本。
output_fields:
  - clip_state
  - fracture_mechanism
  - fracture_site
  - special_case
```

任何会改变模型实际输入的 system prompt、user prompt、模板、字段说明、枚举说明或生成约束变化都需要新的 Prompt 版本。仅修改未进入运行输入的注释或文档不升级 Prompt 版本。

正式 Prompt 文件只增不改，同一完整版本名只能对应这一份 Git 文件；不存在时拒绝训练，已存在时不得覆盖。一个 Prompt 版本可以被多个训练版本复用，但每个训练目录仍把完整内容复制到自身 `input/prompt.yaml` 并冻结，不通过共享路径作为运行时输入。准备训练时必须确认复制内容与 Git 中声明的 Prompt 版本一致；该校验使用 YAML 结构化比较，不生成或保存新的身份哈希。

### 5.3 训练版本

一个训练版本表示一套实际运行的完整训练方案，而不是可复用参数模板。范围在准备时冻结：cross_validation三折训练属于同一个版本；full另建版本，保留同样完整的冻结输入，产物位于full/adapter，父Run直接保存实际结果。以下展示三折布局：

```text
workspace/runs/train-v4.1-r1/
├── input/
│   ├── data-version.txt
│   ├── prompt.yaml
│   ├── training.yaml
│   └── environment.yaml
├── fold0/
│   ├── checkpoints/
│   ├── adapter/
│   └── logs/
├── fold1/
├── fold2/
└── diagnostics/
```

训练准备时把上游输入冻结在 `input/`；正式完成后，MLflow 将这些实际输入和结果导出到 Git 跟踪的 `records/training/train-v4.1-r1/manifest.yaml`：

```yaml
version: train-v4.1-r1
protocol: tensile-vlm/v4.1
record_validity: valid
data_version: data-v4.1-r1
prompt_version: prompt-v4.1-r1
folds: [0, 1, 2]
base_model: MiniCPM-V-4.5
```

`training.yaml` 保存本次实际使用的 LoRA、采样、seed、epoch、优化器、保存和早停参数。`environment.yaml` 保存 Python、PyTorch、LlamaFactory 和主要运行依赖的可读版本，不保存 lockfile 哈希。

训练开始前的 `prepared` 只表示本地版本已预留且 `input/` 已冻结，此时还没有 MLflow Run。执行开始后，运行状态、过程指标和汇总指标均写入 MLflow，不另设 `status.yaml` 或 `result.yaml`。MLflow 原生 RunStatus 只表达进程执行状态；项目 tag `workflow_state` 表达版本控制工作流状态，两者合法组合固定为：

| `workflow_state` | MLflow 原生 RunStatus | 含义 |
| --- | --- | --- |
| `prepared` | 无 Run | 本地版本已预留且 input 冻结，尚未开始执行 |
| `running` | `RUNNING` | 正在执行或经校验后恢复执行 |
| `partial` | `FAILED` 或 `KILLED` | 已产生部分可恢复产物，但必需工作未完成 |
| `failed` | `FAILED` 或 `KILLED` | 执行失败，尚未完成受控恢复 |
| `completed` | `FINISHED` | 所有必需 fold 和汇总均完整成功 |
| `archived` | `FINISHED` | 已完成 Run 退出活动视图，事实内容不变 |

任何其他组合都视为非法，查询、manifest 导出和模型晋级必须拒绝。父 Run 只有在所有必需子 Run 都是原生 `FINISHED` 且 `workflow_state: completed|archived`、fold 集合和汇总完整时，才允许自身进入 `completed`。

项目工作流状态流为：

```text
prepared → running → completed → archived
              ↓  ↑
           partial
              ↓  ↑
            failed
```

`partial` 或 `failed` 只能在确认冻结 input、原 Run ID 和恢复对象未变后，通过受控恢复把原生状态与 `workflow_state` 一起转换回 `RUNNING/running`，不能直接改成 `completed`。训练开始前冻结 `input/`；运行中的 checkpoint 和日志继续可写。中断后以同一输入续跑仍属于同一训练版本和 Run；无法满足同一身份恢复条件时创建新的训练版本。已经 `completed` 或 `archived` 的训练不得原地完整重跑；需要新一轮独立结果时创建新的训练版本。

改变数据版本、Prompt 版本、基座模型、采样、参数、seed 方案、fold 设计或训练日程，都产生新的训练版本。

### 5.4 模型版本

checkpoint、临时 adapter 和临时 merged 属于训练版本，不是模型版本。只有决定长期保留的模型才从 staging 登记进 MLflow Model Registry；其逻辑产物结构为：

```text
MLflow Registered Model: mVllm2
└── Model Version: <MLflow 数值版本>
    ├── tag: model_id=model-v4.1-r1
    └── artifacts/
        └── fold0/
            ├── adapter/
            └── merged/
```

一个可读模型版本映射为 `mVllm2` 下一个可长期保留的数值 Model Version，可以是单折模型、三折模型组或 full-data 模型。登记采用两阶段：完成且有效的 train 先创建带 `model_id`、`train_id` 和冻结训练输入、但尚无 `eval_id` 的 staging Model Version；正式 eval 创建时必须在线核对该 `model_id` 已存在、有效且 MLflow 数值 Model Version 精确匹配。eval 完整结束且 `outcome: passed` 后，finalize 操作才把该 `eval_id` 单向绑定到原 Model Version。绑定不得改写或更换，未绑定通过结论的 staging 模型不得设置 candidate/production alias。

`model_id` tag 在整个 Registered Model 中必须唯一；注册后不得把该数值版本改绑到另一个可读模型 ID。三折模型组在同一个版本的 `artifacts/fold0`、`fold1`、`fold2` 下保存，不为每个 fold 单独分配 model 版本。full-data 模型使用 `artifacts/full/`。该结构与训练范围一致：三折及其单折来源绑定cross_validation训练，full-data模型只能绑定独立full训练版本，不能用某折代替全量。`workspace/models/materialized/model-v...` 只是从该权威对象生成的本地部署副本，可以重新物化，不能反向修改 Registry 模型。

模型决定长期保留后，MLflow 将来源和产物索引导出到 Git 跟踪的 `records/models/model-v4.1-r1/manifest.yaml`：

```yaml
version: model-v4.1-r1
protocol: tensile-vlm/v4.1
state: sealed
record_validity: valid
registered_model: mVllm2
mlflow_model_version: 1
source_run_id: "<MLflow Run ID>"
source_training: train-v4.1-r1
source_scope: fold0
base_model: MiniCPM-V-4.5
data_version: data-v4.1-r1
prompt_version: prompt-v4.1-r1
artifacts:
  fold0:
    adapter: artifacts/fold0/adapter
    merged: artifacts/fold0/merged
deploy_target: artifacts/fold0/merged
```

三折模型组的 `source_scope` 为 `cross_validation`，列出三个 fold 且 `deploy_target` 为 `null`；full-data 模型的 `source_scope` 为 `full`。只有存在唯一 `deploy_target` 的模型版本才能成为服务当前模型。

模型内容、可读 `model_id`、数值 Model Version、已导出的 manifest 身份字段和训练输入关系不可修改；`candidate`、`production` 及其他运行状态直接由稳定 Registered Model `mVllm2` 的 aliases 和 Model Version tags 维护。别名变化不回写旧 manifest；需要查看当前路由时以 MLflow 为准。若权重或来源改变，必须创建新的可读模型版本和新的 MLflow Model Version。

### 5.5 测评版本

开发 canary、逐 checkpoint 诊断和调试推理属于 `train-v4.1-rN/diagnostics/`，不获得正式测评版本。正式测评先在 workspace staging 中运行，完整结果上传到 MLflow 后形成如下逻辑 artifact 结构：

```text
MLflow Run: eval-v4.1-r1
├── evaluation.yaml
├── summary.json
├── records.jsonl
└── failures.jsonl
```

正式测评完整结束后，MLflow 将实际输入、指标摘要和结论导出到 Git 跟踪的 `records/evaluations/eval-v4.1-r1/manifest.yaml`：

```yaml
version: eval-v4.1-r1
protocol: tensile-vlm/v4.1
state: sealed
record_validity: valid
model_version: model-v4.1-r1
data_version: data-v4.1-r1
split: validation
model_scope: fold0
sample_count: 425
outcome: failed
```

`manifest.yaml` 中的 `outcome` 是测评封存时从 MLflow 导出的不可变结论。质量未达标但流程完整的 `failed` 仍可成为正式证据；运行异常导致结果不完整时不导出正式 manifest。

`evaluation.yaml` 保存实际评分器版本说明、指标定义、生成参数、样本选择规则和阈值。指标定义、数据、划分、被测模型、生成参数或正式样本范围改变时，创建新的测评版本。

同一个模型可以对应多个正式测评版本。单折或 full-data 模型的正式测评记录一个模型 artifact；三折模型组在 MLflow 中采用固定逐 fold artifact 结构：

```text
eval-v4.1-rN/
├── evaluation.yaml
├── folds/
│   ├── fold0/{summary.json,records.jsonl,failures.jsonl}
│   ├── fold1/{summary.json,records.jsonl,failures.jsonl}
│   └── fold2/{summary.json,records.jsonl,failures.jsonl}
└── aggregate/summary.json
```

对应 `evaluation.yaml` 必须逐项绑定：

```yaml
scope: cross_validation
folds:
  fold0:
    model_artifact: artifacts/fold0/merged
    data_split: validation/fold0
    sample_count: 425
    records: folds/fold0/records.jsonl
    failures: folds/fold0/failures.jsonl
  fold1:
    model_artifact: artifacts/fold1/merged
    data_split: validation/fold1
    sample_count: 664
    records: folds/fold1/records.jsonl
    failures: folds/fold1/failures.jsonl
  fold2:
    model_artifact: artifacts/fold2/merged
    data_split: validation/fold2
    sample_count: 492
    records: folds/fold2/records.jsonl
    failures: folds/fold2/failures.jsonl
aggregate: aggregate/summary.json
```

示例数量只说明字段。封存前必须验证 fold 集合与模型 artifacts、数据 split 一一对应、无缺失和无重复，聚合结果只能由这三个 fold 结果产生。单折使用 `scope: single_fold` 且只允许一个 fold 绑定；full-data 使用 `scope: full` 且引用明确的独立验收 split。正式测评不会改写模型内容或旧模型 manifest；eval manifest 显式引用被测模型，完整关系可在 MLflow 中查询，不建立独立状态文件。

### 5.6 Holdout 正式测评授权

对 `purpose: holdout` 的 data 版本执行正式测评时，测评 staging 必须在首次模型调用前保存：

```text
evaluations/staging/eval-v4.1-rN/
├── authorization/
│   └── pre_registration.yaml
└── evaluation.yaml
```

`pre_registration.yaml` 在接触受限真值前冻结完整 eval 版本、model 版本、data 版本、split、评价规则、阈值、`one_time: true`、`tuning_use: forbidden` 和恢复规则。统一入口先把操作者提供的预注册内容原子冻结到上述 eval staging 稳定路径并设为只读，再以完整 SHA-256 绑定 claim；MLflow 保存该稳定审计路径和摘要。首次模型调用前，系统必须在该 holdout data 版本自己的 `authorization/claim.yaml` 中原子创建全局 claim，绑定相同的四元组、预注册摘要和一次执行身份；把 claim 放在 eval staging 内不能阻止另一 eval 版本再次消费，因此不作为权威位置。holdout 已有 claim 时，只有完整 eval/model/data/split 四元组、预注册摘要、claim 中的一次执行身份以及允许恢复的运行状态全部一致，才可作为同一运行恢复；新进程必须携带并验证原执行身份。跨机器恢复以冻结内容摘要为一致性标准，不要求机器本地绝对路径相同。任一身份或内容不同都拒绝，且不得创建第二个 claim 或覆盖原 claim。完成门先原子写入永久只读的消费证据，再以可恢复顺序提交 MLflow 项目状态和原生状态；正式 eval 保存 claim 的只读副本或可读引用，holdout 目录中的原 claim 永久保留。

模型推理阶段只读 holdout 媒体；评分阶段在授权边界内读取 `sealed_ground_truth/`。预注册、claim、权限、访问日志和 aggregate-only 的预公开限制继续保留，但身份字段改用完整可读版本，不使用哈希。现有已暴露 sealed-test 只作为历史证据，不得在迁移时伪装成新的未使用 holdout，也不把旧 claim 转换成可再次使用状态。

## 6. 版本引用关系

训练运行是主要绑定点：

```text
data-v4.1-r1 ───────┐
prompt-v4.1-r1 ─────┼─→ train-v4.1-r1
training.yaml ──────┘          │
                               ▼
                        model-v4.1-r1
                               │
                data + eval protocol
                               ▼
                         eval-v4.1-r1
```

关系规则：

1. 训练引用一个正式 data 版本和一个 Prompt 版本，并保存完整 Prompt 与训练参数副本；
2. 模型引用一个已完成训练版本和明确的 fold 或 full-data 范围；
3. 测评引用一个 MLflow Registered Model、一个正式数据版本和明确 split；holdout 还必须具备对应预注册和 one-time claim；
4. 旧上游版本不会因为出现新版而失效，已有下游关系保持成立；
5. 上游更新只表示可以创建新的下游版本，不自动重训或重评。

## 7. 版本选择与当前模型

数据处理发布、训练准备、模型晋级和正式测评必须显式传入完整版本名。不传版本时停止并提示可用版本；不存在、状态不允许或引用不兼容时 fail-closed。

服务的唯一逻辑路由权威是稳定 Registered Model `mVllm2` 下的 alias。production 模式固定解析 `production`；development 模式必须显式传入 `candidate` 或 `production`，不设置默认 alias。解析到精确数值 Model Version 后，物化工具下载并验证模型，再原子更新本地缓存链接：

```text
workspace/models/current
    -> materialized/model-v4.1-r1
```

每个 `materialized/model-v.../` 必须携带机器生成的本地元数据，至少记录 `registered_model: mVllm2`、MLflow 数值 Model Version、可读 `model_id` 和对应 Git manifest。`current` 不得被人工独立选择或手工切换；它只表示最近一次成功物化的 alias 精确目标。

服务启动必须打印：

```text
当前模型：model-v4.1-r1
模型状态：candidate
来源训练：train-v4.1-r1
数据版本：data-v4.1-r1
Prompt 版本：prompt-v4.1-r1
正式测评：eval-v4.1-r1 或 none
```

物化流程必须先在临时目录完成下载、模型 ID、Registered Model 名、数值 Model Version、manifest 和唯一 `deploy_target` 校验，再原子替换 `current`。下载或校验中断时保留旧链接，不得出现半物化目标。服务每次启动都重新解析所选 alias，并验证 `current` 本地元数据与 alias 当前指向的精确数值 Model Version 完全一致；alias 已变化、链接先变化、链接断裂或元数据不一致时立即拒绝启动，要求重新物化。三折模型组用于比较和聚合测评，不能直接成为服务当前模型。

服务启动必须显式提供 `service_mode: development | production`，实现时可以采用必填 CLI 参数或等价的必填部署配置，但不得设置默认模式；缺失或非法值一律拒绝启动。development 还必须显式提供 `model_alias: candidate | production`，加载 `candidate` 时打印未通过最终质量门的警告；production 只接受 `production` alias。`models/current` 只是 alias 精确目标的本地缓存，不自动改变任何 Registry alias。

## 8. 封存机制与不可覆盖规则

不同对象按自身生命周期正式化，不宣称五类对象共用一套状态机：数据为 `working → release_staging → sealed`；Prompt 为“Git 中新增不可变正式文件 → 训练 input 冻结副本”；训练为“原子预留版本 → 冻结 input → MLflow running/completed”；模型为“训练完成 → Registry staging Model Version → 正式 eval 精确引用 → passed 后绑定 eval → candidate/production”；测评为 `workspace staging → MLflow running/completed → 导出正式 manifest`。

封存前检查：

- 完整版本名合法；
- Git、DVC 或 MLflow 的对应权威位置不存在同名正式对象；
- 必要文件和可读字段齐全；
- 上游版本存在且状态允许；
- 训练三个 fold 使用根目录同一份 input；
- 模型来源训练已经完成；
- 正式测评引用的模型和数据与声明一致。

封存通过后，在同一文件系统中把 staging 整体移动到正式目录并封存 payload，同时在该正式数据目录的 `release.yaml` 写入不可变身份和初始状态；该文件只允许受控修改 `status` 和可选的 `replacement`，并由 Git 留存历史。训练、模型和测评的实际运行状态保存在 MLflow。holdout data 另允许在原本为空的 `authorization/` 中原子创建一次 `claim.yaml`，创建后同样只读。工具发现同名目录时必须停止，不自动复用、补写、覆盖或删除。

正式对象只允许三类后续变化：

1. MLflow 中允许的运行状态、标签和 Registry 别名变化，但不得改写已完成 Run 的实际参数、指标或产物；
2. holdout data 首次消费时创建一次不可覆盖的 `authorization/claim.yaml`；
3. 数据 `release.yaml` 中受控生命周期字段的 Git 记录变化，或创建新的 `rN` 并在新版本说明中记录替代关系。

不提供普通 `unseal`。人工解除文件权限属于绕过项目流程，验证工具应将正式 payload 可写视为异常。

## 9. 双机版本分配与并发

为避免本机和训练机同时创建相同 `rN`，版本产物的唯一写入权归训练机：

| 对象 | 本机职责 | 训练机职责 |
| --- | --- | --- |
| 数据 | 代码、轻量检查、人工审查界面和结果查看 | 执行重数据处理、分配并封存 data 版本 |
| Prompt | 编辑来源、代码审查 | 训练准备时确认版本并冻结实际副本 |
| 训练 | 配置和代码准备 | 分配 train 版本、运行训练、保存实际输入和结果 |
| 模型 | 注册逻辑和轻量证据检查 | 分配 model 版本、向 MLflow Registry 晋级和保存权重 |
| 测评 | 评分器代码和同步结果复核 | 分配 eval 版本、运行正式推理并把逐样本结果保存到 MLflow artifacts |

创建版本时调用方必须显式给出完整版本号。系统可以建议下一个 `rN`，但不能静默决定。训练机通过原子创建 staging 目录完成版本预留；同名 staging 或正式目录存在即失败。每一类正式集合同时只允许一个写入者。

本机通过 Git 同步训练机生成的轻量 manifest，但不得在本机手工创建或修改同名正式 manifest，也不得把本机目录视为大型产物的权威副本。

## 10. 过期、替代和状态

本架构不维护全局“最新版”或自动 stale 图，也不建立独立 `status.yaml`。状态按对象归属处理：

| 对象 | 身份与不可变内容 | 当前状态从哪里读取 | 下游使用规则 |
| --- | --- | --- | --- |
| data | DVC 正式对象及 `release.yaml` 的身份字段 | 同一 `release.yaml` 中由 Git 留痕的 `active/superseded/invalid` | `active` 可创建新训练和新测评；`superseded` 只允许恢复或复现已经明确引用它的历史训练；`invalid` 只保留历史证据，禁止训练、续跑和正式测评 |
| prompt | Git 中的 `records/prompts/prompt-v...yaml` 与训练 `input/` 冻结副本 | 无可变状态 | 新训练只接受显式存在的正式 Prompt 文件，并验证冻结副本内容一致 |
| train | 冻结 input 与 MLflow Run | MLflow 原生 RunStatus + `workflow_state`/`record_validity` tags | 模型晋级只接受 `record_validity: valid`、原生 `FINISHED`、项目 `completed|archived` 且所有子 Run 完整的父 Run |
| model | `mVllm2` 中数值 Model Version、唯一 `model_id` tag、来源 train、通过后单向绑定的 `eval_id`、权重及导出 manifest | `mVllm2` 的 Registry aliases、`record_validity` 和其他 Model Version tags | staging 可供正式 eval 精确引用；只有绑定了同一数值版本的 passed eval 后才能进入有效 `candidate`，生产只使用获批的有效 `production` |
| eval | MLflow 正式测评 Run 及导出 manifest | MLflow 原生 RunStatus + `record_validity`/结论 tags | 只有执行完整且 `record_validity: valid` 的正式测评可形成当前结论；`outcome: failed` 仍是有效质量证据 |

出现新数据或新 Prompt 时，旧训练和旧模型不会自动失效；它们只属于旧血缘。是否需要新训练由用户决定。Registry 别名或允许变化的 MLflow 标签不得覆盖旧 Run 的实际输入、模型内容或测评结论；正式事实错误时按更正策略将旧对象标记 `record_validity: invalid` 并创建新的可读版本，而不是原地改写旧事实。

## 11. 失败处理

### 11.1 数据处理失败

失败内容留在 `working/`，不创建正式 data 版本。继续处理必须从明确阶段恢复；放弃当前轮次时清理整个 working，而不是挑选部分文件继续发布。

训练机 working 是唯一权威副本。需要 Mac 人工操作时，训练机按 `round_id + review_batch_id` 导出候选清单和所需媒体到 exchange；Mac 副本只允许写指定的审查决定，不得修改 source、split 或候选集合。回传先进入训练机 incoming 临时目录，验证 round、batch、候选 ID 全集合、记录数量和状态一致后整体接收。旧轮次、部分回传、额外或缺失候选、两端同时修改同一批次时全部 fail-closed。训练机确认接收前不得发布，确认接收后 Mac 副本可删除且不再具有权威性。

### 11.2 封存失败

staging 保持非正式状态。数据只有在 DVC 发布完成、`release.yaml` 有效且正式对象校验通过后才算封存；训练、模型和测评只有在 MLflow 中满足各自完成条件后才可导出正式 manifest。部分移动、缺文件或不完整 Run 不能被活动入口读取。

### 11.3 训练部分完成

训练失败或中断时，MLflow 原生状态必须为 `FAILED` 或 `KILLED`，项目 `workflow_state` 标记为 `partial` 或 `failed`，并保留日志和已产生 checkpoint；不得晋级正式模型，也不导出正式 train manifest。确认冻结 input、原 Run ID 和恢复对象未变后，先把原生状态与项目 tag 一起恢复为 `RUNNING/running`，再经实际执行进入 `FINISHED/completed` 或再次失败；不允许只改 tag 绕过执行。

### 11.4 模型晋级失败

训练门不通过时不得登记 Model Version。已经登记但正式 eval 未通过的模型保留为无活动 alias 的 staging 证据，不得进入 candidate/production，也不能被 `models/current` 指向；不得删除后以同一版本重试。权重或来源需要修正时使用新的 model 版本。

### 11.5 正式测评失败

运行异常导致结果不完整时停留在 MLflow 的非完成状态，不获得正式 eval 版本，也不导出正式 manifest。模型质量未达标但测评过程完整时可以封存并导出，`outcome: failed` 表达真实且不可改写的有效失败证据。

### 11.6 版本冲突

同名版本在 staging、Git 正式记录、DVC 正式对象或 MLflow 中已存在时立即停止。工具不得比较内容后决定复用，也不得自动选择下一个编号；由使用者核对现有版本后明确指定新编号。

## 12. 迁移策略

迁移采用当前链路优先、旧体系只读过渡、最终删除活动兼容代码的方式。

### 阶段边界

1. 在独立迁移分支建立新目录契约、可读版本校验和封存能力，并同步改写项目根 `AGENTS.md` 中与目标架构冲突的哈希 ID、`index.json`、`LATEST` 和短哈希解析规则；不修改或删除现有正式产物；
2. 为当前仍有价值的数据、Prompt、训练、模型和正式测评建立经过人工核对的可读映射；
3. 新入口只写可读版本，必要时暂时只读旧哈希产物；
4. 训练机完成真实路径预检，确认数据读取、训练准备、模型加载、正式评测准备和服务启动均能使用新版本；
5. 活动流程全部切换后，删除 `LATEST`、短前缀解析、内容哈希身份生成和旧全局索引代码；DVC 与备份流程用于完整性校验的内部校验值继续保留，但不成为人的版本名；
6. 历史报告中仅用于旧实验审计的哈希不迁入新活动结构，详细历史交给 Git；大型旧权重和结果按单独归档清理授权处理；
7. 本机和训练机验证全部通过后提交变更清单与限制，由用户决定是否合并；不自动合并或推送。

### 迁移原则

- 不在原哈希目录中批量原地改名并假定语义正确；
- 不因目录存在就认定它是当前有效版本；
- 只迁移身份、来源和结果链能够人工确认的对象；
- 找不到权重、原始预测或对应配置时标记证据不足，不补造可读版本；
- 迁移成功不等于模型质量通过，也不解除训练、测评或删除授权限制。
- 旧 sealed-test 的真值权限、预注册、claim 和一次性使用事实必须保留为历史证据；迁移只替换身份字段，不得把已消费授权重置为可用。

## 13. 测试与验收

### 13.1 本机验证

至少覆盖：

- 五类完整版本名的合法与非法输入；
- 缺版本、短前缀、模糊名称和旧 `LATEST` 入口被拒绝；
- DVC 七阶段依赖图与 `dvc.yaml` 业务顺序准确，输入/参数/代码变化能够报告过期但不自动执行；
- DVC 只重建明确选择的 working 阶段及必要下游，人工 review 未回收时阻断 release，正式 data 目录拒绝覆盖；
- 从日常 DVC remote 拉取一个最小测试对象后能够恢复并通过 release 校验；
- staging 正式化成功、重复正式化失败、缺文件或同名 Git/DVC/MLflow 对象时失败；
- sealed payload 不可写且活动工具拒绝覆盖；
- 训练 `input/` 在开始后不可修改；
- 三个 fold 共享同一份数据、Prompt 和训练参数；
- 正式 Prompt 文件不可覆盖，训练冻结副本与 Git 中对应 Prompt 进行结构化深比较；缺失或不一致时 fail-closed；
- 临时 SQLite/artifact store 中父 Run 与三折子 Run 关系完整；失败/恢复组合符合原生 RunStatus 与 `workflow_state` 映射，非法组合被拒绝；
- 模型只能来自 `record_validity: valid` 且原生 `FINISHED`、项目 `completed|archived` 的父Run；cross_validation须三折完整，full须无fold子Run且单次全量执行的冻结输入、实际结果和产物证据完整；
- 稳定 Registered Model `mVllm2` 中 `model_id` 与数值 Model Version 一一对应，`candidate`/`production` alias 只能指向其中的有效版本；
- 单折、三折模型组和 full-data 模型结构合法，三折模型组不能成为 `models/current`；
- 三折正式测评逐 fold 绑定模型 artifact、数据 split、样本数和结果路径，聚合集合完整且无重复；
- 正式测评只能引用 MLflow Registered Model 和明确数据 split；holdout 训练禁用、预注册、one-time claim、同身份恢复和真值权限均被验证；
- data/train/model/eval 各自状态转换、`record_validity` 和下游接受门闭合，非法逆向转换被拒绝；测评执行失败与质量 `outcome: failed` 不得混淆；
- MLflow → manifest 导出包含最小字段、结果可重复生成、同名冲突阻断、非完成 Run 不导出、人工修改被检测；仅 exporter 错误可同语义重导，正式事实错误必须 invalid + 新版本；
- alias 解析后物化模型并原子切换 `models/current`；覆盖 alias 先变化、link 先变化、下载中断、断链、错误 Model Version 与本地元数据不一致，服务均不得加载错误模型；
- 服务模式缺失时拒绝启动，candidate 在 production 模式下被拒绝；
- SQLite 一致性快照与对应 artifact store 联合恢复后，可以查询父子 Run、指标、Model Version、alias 和 artifact；
- 备份源集合包含全部正式数据及所有带 `offline_backup_scope` 的模型；candidate→production 只升级备份范围，catalog 存在但文件缺失、内容损坏、alias 离线切换和 catalog 损坏重建都能按历史最高范围重新产生待备份项；
- 备份 catalog 仅在复制与校验完成后原子写入 `verified: true`，备份成功不会触发源文件删除；
- 新入口未全部通过前旧入口可回滚；删除旧解析器前新旧映射完整，回滚不得重置 holdout claim、`record_validity` 或 Registry aliases；
- 项目根 `AGENTS.md` 不再要求哈希数据 ID、集合 `index.json`、`LATEST` 或短哈希解析，并与 README、RUNBOOK、微调说明及本文的活动入口一致；
- 新活动代码不再生成哈希身份、短哈希目录、集合 `index.json` 或 `LATEST`。

### 13.2 训练机验证

在不启动未授权重训练或完整评测的前提下，至少完成：

- 两端分支、HEAD、状态和独有提交检查；
- 一个已确认当前数据对象的可读迁移 dry-run；
- 使用小型非正式样本执行 DVC 七阶段可达性、人工关卡、过期发现和 remote 恢复 smoke，不覆盖任何正式数据；
- 一次训练机到 Mac 的审查导出、回传和原子接收轻量演练；
- 训练准备 dry-run，核对真实数据路径、Prompt 和 YAML 参数副本；
- 在锁定的 MLflow/DVC 版本下执行父子 Run、Model Version、alias、manifest 导出和 SQLite/artifact 联合恢复 smoke；
- 已有模型从精确 Model Version 物化后的加载预检，不运行长 GPU 推理；
- 正式测评准备 dry-run，核对模型、数据和输出目录；
- 推理服务解析 Registry alias、核对 `models/current` 精确数值版本并完成允许范围内的轻量 smoke；
- 移动硬盘可用时，以非正式小对象演练 SSH 直写、断点失败、catalog 原子更新与损坏重建；对正式数据、adapter、merged 和 SQLite 的首次真实备份按第 2.11 节完成恢复演练；
- staging、正式目录和只读权限在训练机文件系统上的实际行为。

GPU 训练、完整推理、sealed-test 或新 holdout 使用仍需按项目现有授权单独执行，不能由版本迁移测试隐含获得。

### 13.3 合并门

满足以下条件才成为可合并候选：

- 本机相关单元测试、静态检查和文档链接检查通过；
- 训练机真实路径预检通过；
- 当前服务模型、当前正式数据和必要历史对象没有被覆盖或删除；
- 新旧映射清单经人工核对，证据不足项没有冒充完成；
- 项目任务台账、项目根 `AGENTS.md`、README、数据运行手册、微调说明和脚本索引的活动入口表述一致；
- 独立审查没有未解决的高严重度问题；
- 用户明确决定合并。

## 14. 优势、代价与残余风险

### 优势

- 使用者只需理解五类版本和它们之间的引用关系；
- 中间产物、训练过程、保留模型和正式测评边界清楚；
- 不再暴露内容哈希、短前缀、集合索引和隐式最新选择；
- 训练目录保存实际 Prompt 与参数，能够直接复盘；
- 双机写入责任明确，降低同名版本冲突；
- 除已经确认的 DVC 与 MLflow 外，不再引入额外的同步数据库或常驻公共服务，符合当前科研项目规模。

### 未采用纯本地目录/YAML 方案的取舍

- 如果不采用 DVC 或独立 checksum，失去内容自动去重和字节级身份验证；
- 如果不采用内容校验机制，不能自动判断两份同名或不同名目录是否内容相同；
- 清理 working 后不能从任意历史中间阶段直接恢复；
- 同一 Prompt 会在多个训练目录重复保存；
- 版本号需要人为选择并遵守只增不改纪律；
- 不能仅凭 Git 得知训练机实际拥有哪些大型产物。

### 主要风险及处理

| 风险 | 触发条件 | 影响 | 处理 |
| --- | --- | --- | --- |
| 同名正式版本被修改 | 人工解除权限或脚本绕过封存 | 版本语义失真，下游结论不可信 | payload 只读、拒绝覆盖、验证可写状态、修改必须新建 rN |
| 两机或两进程分配同一版本 | 未遵守训练机唯一写入或并发创建 | 目录冲突或不同内容同名 | 训练机唯一写入、原子预留 staging、显式版本、单写者 |
| working 混入旧中间产物 | 新轮次复用未清理目录 | 新数据发布来源混杂 | 新建/继续/放弃/发布四种操作分离，发布前阶段一致性检查 |
| 训练输入在运行后变化 | 训练启动后改 Prompt 或 YAML | 保存记录与实际训练不一致 | 启动前复制，运行时只读，三折只读根 input |
| 正式测评引用错模型或数据 | 手工版本参数错误 | 指标归属错误 | 显式完整版本、引用状态检查、运行前打印完整关系 |
| 本机测试通过但训练机失败 | 路径、权限、环境或真实产物差异 | 分支无法安全合并 | 训练机 dry-run 与服务 smoke 作为合并门 |
| 数据或模型发生静默磁盘损坏 | 存储介质故障，或模型权重不属于 DVC 数据对象 | 数据无法复现、模型无法加载或备份同样损坏 | 数据由 DVC 内部完整性能力检查；模型和离线备份执行机器完整性校验、真实加载与规定触发的恢复演练。仍接受两次验证之间发生未被即时发现损坏的窗口 |

纯本地目录/YAML 方案已经不再采用：它虽然最易直接阅读，但更依赖不可覆盖、权限、结构校验和人工纪律，难以查询并比较大量历史实验。当前混合方案由 Git/YAML 保存定义和 MLflow 导出的可读快照，由 DVC 和 MLflow 提供数据血缘、实验检索和复现支持，并把内部哈希与 SQLite 隐藏在日常操作之外。

## 15. 不做的事情

- 不建立统一的“整个项目 v1/v2/v3”；
- 不给每个数据处理中间阶段、checkpoint 或调试推理分配正式版本；
- 不自动选择 latest 数据、Prompt、训练或测评；
- 不自动重训或自动重评；
- 不把模型和视频数据提交到 Git；
- 不用模型目录存在代替质量门判断；
- 不在本设计阶段创建分支、修改代码、迁移或删除文件。

## 16. 最终设计结论与后续边界

最终架构是“可读五类版本 + Git/YAML 运行定义 + DVC 数据 pipeline + MLflow 实际运行记录 + 单向导出 manifest + 各对象正式化关卡 + 显式引用 + 训练机唯一写入 + Mac 私有硬盘离线备份”。独立 `status.yaml`、YAML/MLflow 双向同步、全局版本注册表、Hydra、自动 latest、自动重训和面向人的哈希身份均不采用。

核心架构决策已经收敛，没有遗留会改变系统责任、数据流或用户操作方式的待决项。具体 schema 文件、脚本命名、命令参数、测试用例、权限配置和迁移批次属于后续实施规划；规划与实施不得改变本文责任边界，遇到需要改变架构的情况必须重新与用户讨论。

本文完成独立设计核查后可作为实施规划依据，但不直接授权创建分支、修改代码、迁移数据、清理历史产物、执行训练或合并提交。实施仍须由用户明确启动；迁移必须在独立分支完成，本机与训练机验证通过后由用户决定是否合并。

<!-- DECISION-LOG
D001 — 面向使用者的活动产物使用 data/prompt/train/model/eval 五类人类可读顺序版本，不把哈希作为日常版本名或选择入口。
Why: 用户需要直接理解每一版输入和结果；现有哈希身份直接暴露已经显著增加项目认知和维护成本。
Trade-off: 当时尚未确定底层工具是否使用内容哈希；后续 D014 已确认 DVC 可以在内部使用哈希，但不得作为人的日常身份。

D003 — Prompt 和训练参数的真实运行版本保存在训练目录 input 副本中。
Why: 打开训练目录即可确认实际输入，避免跨注册表和共享路径追踪。

D004 — 数据只版本化正式 development 或 holdout 发布，中间产物统一进入可修改、可清理的 working。
Why: 使用者主要需要区分原始输入、处理过程和正式数据，不需要为每个阶段维护独立身份。
Trade-off: 清理 working 后不保证从任意历史中间阶段恢复。

D005 — 一次完整训练方案及其三折运行共用一个 train 版本。
Why: 三折是同一实验方案的整体证据，分别编号会把 fold 与独立训练方案混淆。

D006 — 只有长期保留模型和正式测评获得 model/eval 版本。
Why: checkpoint、临时 merged 和开发诊断属于训练过程，全部正式版本化会再次造成结果目录混乱。

D007 — 除 models/current 外，运行必须显式传入完整版本名。
Why: 禁止自动 latest、短前缀和隐式回退，确保使用者在运行前知道实际选择。

D008 — 各对象按自身生命周期冻结输入或从 staging 封存，正式内容只增不改且不提供普通解冻入口。
Why: 在取消哈希身份后，以拒绝覆盖、只读权限和结构校验降低同名版本内容漂移风险。

D009 — workspace 正式版本只由训练机分配和封存。
Why: 大型真实产物和 GPU 流程位于训练机，单一写入责任可以避免双机分配相同版本。

D010 — 迁移必须在独立分支完成，双机验证通过后仍由用户决定是否合并。
Why: 当前 main 和真实训练链必须保持可回退，测试通过不自动扩大为合并或推送授权。

D011 — 去除哈希身份不得削弱 holdout 的训练禁用、真值隔离、预注册和全局一次性 claim。
Why: 可读版本替换的是身份表达，不是最终独立验收的科学隔离和授权边界。

D012 — 训练机 working 是唯一权威数据处理工作区，Mac 只持有按工作轮次导出的可丢弃人工审查副本。
Why: 两台机器是独立工作区；没有单一权威位置和显式回传协议会把旧或不完整审查结果发布为正式数据。

D013 — 服务启动必须显式声明 development 或 production，缺失模式时拒绝启动。
Why: 同一 current 链接可以指向开发候选或正式发布模型，隐式默认模式可能让未通过质量门的候选进入生产。

D014 — 采用 DVC 描述整个数据处理 pipeline，允许 DVC 在内部保留哈希和指针文件，但不把它们作为使用者的日常版本入口。
Why: 用户需要的是清晰可读的 pipeline 和版本选择体验；DVC 的内部哈希不会妨碍这一目标，并可继续提供数据依赖与完整性能力。
Trade-off: 当时尚未确定的阶段粒度、remote/cache 和跟踪范围，后续已由 D016、D019、D020 与 D035 收敛。

D015 — 人工审查作为 DVC pipeline 的显式关卡，以“审查材料导出 → 人工处理 → 审查结果回收与校验”表达。
Why: 人工判断本身不能也不应伪装为自动步骤，但其输入、输出和对正式数据发布的阻断关系必须在完整 pipeline 中可见。

D016 — `dvc.yaml` 采用 source、roi、subvideo、review_export、review_import、release、release_validate 七个业务阶段作为主干。
Why: 使用者需要从 pipeline 直接理解完整数据流程；按每个脚本拆分会暴露实现噪声，而业务阶段内部仍可调用多个脚本并保留实际依赖。

D017 — 用户私有的 1TB 移动硬盘只承担正式数据和重要模型的定期离线备份，不作为公共训练机上的常驻设备或日常 DVC remote。
Why: 日常流程应使用训练机的大容量存储，避免把私人设备长期留在课题组公共电脑；离线副本则为训练机整体故障提供独立恢复边界。
Trade-off: 备份不是实时同步；后续 D036 已确定连接硬盘时按 catalog 差异触发，并采用分层验证。

D018 — 移动硬盘只连接 Mac，由 Mac 主动通过 SSH 从训练机备份指定正式版本，不把完整数据长期保存到 Mac 内置磁盘。
Why: 私人设备不接入课题组公共训练机，同时仍能取得一份与训练机物理隔离的离线副本。
Trade-off: 大型数据和模型的首次备份速度受双机网络影响，实施时必须避免产生不必要的 Mac 内置磁盘中转副本。

D019 — 训练机 `/home` 保留项目工作区和本地 DVC cache，独立的 `/data` 磁盘承载日常 DVC remote。
Why: 活跃工作与恢复存储分布在不同物理磁盘，利用训练机现有大容量空间，并减少 `/home` 的容量压力。
Trade-off: 两块磁盘仍位于同一台公共训练机；`/data` 目录和权限需要实施阶段受控配置，真正的异机恢复仍依赖私人移动硬盘中的精选离线备份。

D020 — DVC 只管理数据 pipeline 和数据产物；MLflow 统一管理训练运行、实际参数、模型、指标和测评记录；Git 管理代码、Prompt、配置和文档历史。
Why: 为每类对象设置唯一权威系统，可以分别回答数据如何产生、实验如何运行和代码如何变化，避免模型或指标被 DVC 与 MLflow 重复登记。
Trade-off: 三个系统必须通过五类可读版本、Git commit 和明确引用保持一致，实施时需要自动校验跨系统关联。

D021 — YAML 配置和 `manifest.yaml` 作为人类可读入口，MLflow 自动使用内部 SQLite 建立实验索引并按需提供页面；使用者不直接维护数据库。
Why: 保留打开文件即可理解单次运行的体验，同时利用 MLflow 查询、筛选和比较多次实验；SQLite 只是无需独立数据库服务的内部元数据文件。
Trade-off: YAML 与 MLflow 必须由同一入口基于同一冻结输入同时写入并校验，避免形成两份可独立修改的事实来源。

D022 — 一个 `train-v...` 对应一个 MLflow 父 Run，cross_validation范围的三折分别作为 fold0、fold1、fold2 子 Run；独立full范围按D042。
Why: 三折属于同一训练方案，需要共同的可读训练版本和汇总结论，同时保留每一折独立的日志、指标、checkpoint 和失败状态。
Trade-off: 模型晋级时必须明确引用父 Run 以及实际选取的 fold 或模型集合，不能只保存某个内部子 Run ID。

D023 — 每个正式 `eval-v...` 对应独立 MLflow 父 Run，三折测评作为子 Run；训练过程诊断不获得正式测评版本。
Why: 训练中的开发指标与形成长期结论的正式测评具有不同的数据、契约和证据要求，分离后才能保留同一模型在不同测评口径下的完整历史。
Trade-off: 正式测评需要单独登记输入和输出，但避免了在训练 Run 中覆盖或混用指标口径。

D024 — MLflow Model Registry 保留 `candidate` 和 `production` 两个可变别名，普通 checkpoint 不进入 Registry。
Why: 两个别名分别表达当前候选与获准正式推理的路由目标；不可变模型身份仍由 `model-v<协议>-r<N>` 表达，避免把路由状态混进模型名称。

D025 — 正式模型 ID 回到最初的 `model-v<协议>-r<N>` 方案，完整模型身份由 `manifest.yaml` 和 MLflow 展开。
Why: 语义化名称过长，p/d/t 编号又没有直接信息；当前没有兼顾长度与自解释性的更好名称，因此选择稳定、简短的顺序 ID，并把名称的有限可读性作为明确代价。

D026 — candidate 长期保存 adapter，production 同时长期保存 adapter 和 merged 模型；普通 checkpoint 与未晋级权重仅按恢复和诊断需要临时保留。
Why: 当前 adapter 约数百 MiB，而 merged 模型约十六 GiB；分级保存既保留候选模型的最低可恢复能力，也避免为每个未晋级实验长期复制完整 merged 权重。
Trade-off: 清理 merged 或其他权重前必须完成真实重新合并与加载验证；仅有参数记录不能保证重新得到完全相同的模型。

D027 — 离线备份采用 `backup_pending → backup_complete` 事件队列，在移动硬盘连接 Mac 时集中复制并验证，备份成功不触发训练机自动清理。
Why: 私人硬盘不是常驻设备，事件队列能保证正式数据和重要模型不会因错过固定日期而遗漏，同时把备份与删除授权严格分离。
Trade-off: 备份存在等待窗口；MLflow SQLite 必须生成一致性快照，不能在运行写入期间直接复制数据库文件。

D028 — 正式版本统一使用不可变 `manifest.yaml` 和可变 `status.yaml`，取消 `version.yaml`；训练过程和汇总指标不另设 `result.yaml`，统一进入 MLflow。
Why: 每类信息只保留一个明确权威位置，避免 version、manifest、result 和 MLflow 多处重复后发生不一致。
Trade-off: 实施时需要迁移现有字段并建立 manifest 与 MLflow 的自动一致性校验。

D029 — Git/YAML 只定义运行，MLflow 作为训练、模型和测评实际结果及状态的唯一权威来源；正式结果 manifest 由 MLflow 单向导出到 Git，不设置独立 `status.yaml` 或双向一致性机制。
Supersedes: D021, D028
Why: 用户的跨设备管理本来就由 Git 承担；让 manifest 仅作为 MLflow 的可读导出即可满足 Mac 上查看正式结果的需要，避免为了重复记录再建设状态文件、逐字段权威表和冲突处理。
Trade-off: Git 中只能看到已导出的正式结果快照；调试、失败和实时运行状态仍需访问 MLflow，manifest 也不能代替模型权重、完整日志或 MLflow 备份。

D030 — 每项设计约束在实施时必须映射到权威文档以及适用的机器契约、程序校验或测试证据，不允许只保留在设计文档或对话中。
Why: 本架构包含 DVC、MLflow、双机、人工关卡和离线备份，仅靠口头约定无法长期维护；文档负责解释，机器约束负责阻止可自动识别的错误。

D031 — 数据版本不设置独立 `status.yaml` 或全局注册表；`release.yaml` 与发布数据同目录，由 Git 跟踪，只保留必填 `status` 和存在明确替代版本时才出现的 `replacement`。
Why: 使用者在数据目录内即可看到身份和当前可用性；Git 已经提供修改时间与原因历史，无需在 YAML 中重复保存 `supersedes`、`replaced_by`、`status_reason` 和 `status_updated_at`。
Trade-off: DVC 必须跟踪大型 payload 子目录而不是忽略整个版本根目录；实施时还必须限制只有 `status` 和 `replacement` 可变，并验证其他身份字段与 DVC 引用没有随状态更新而变化。

D032 — `active` 数据允许新训练和新测评；`superseded` 数据只允许恢复或复现已经明确引用它的历史训练；`invalid` 数据只保留历史证据，禁止训练、续跑和正式测评。
Why: 普通替代不应破坏旧实验复现，但也不应继续产生新的正式血缘；质量失效则必须阻断所有新的模型执行，避免已知错误继续扩散。

D033 — train/model/eval manifest 只保存可读身份、实际输入、核心参数或指标、正式结论和 MLflow 定位信息，不复制完整日志、全部指标或逐样本产物，也不保存可变 Registry 别名。
Why: manifest 的用途是通过 Git 快速理解一次正式结果并找到 MLflow 完整证据，而不是复制一套 MLflow；排除大量细节和实时别名可以保持文件简短且避免导出后迅速过时。

D034 — 当前版本控制架构不引入 Hydra，继续使用普通 YAML，并且不为 Hydra 预建配置兼容层。
Why: 当前 Prompt、训练和测评配置不需要复杂组合系统；Hydra 的继承、覆盖和组合语义会增加理解“最终实际使用了什么”的成本，而冻结完整 `input/` 已能满足本项目追溯要求。
Trade-off: 将来若组合实验规模显著增长，需要届时重新评估并单独迁移，当前设计不提前承担这部分复杂度。

D035 — DVC 对过期阶段采用“自动发现、手动执行”：可重建 working，但不得覆盖正式数据，也不得自动启动训练、模型晋级或正式测评。
Why: 使用者需要 DVC 提供依赖变化和重跑范围判断，但公共训练机上的重数据处理、人工审查和 GPU 工作都必须由人明确发起；将检测与执行分开可避免意外耗时任务和正式结果漂移。
Trade-off: 过期提示不会自行恢复到最新状态，使用者需要明确选择重建目标并在人工关卡后再次继续。

D036 — 离线备份不维护 `backup_pending/backup_complete` 状态；移动硬盘连接 Mac 时由必须备份的源集合、`backup_catalog.yaml` 和硬盘实际文件共同计算待备份项，每次连接复验全部既有对象，关键类型按事件执行真实恢复演练。
Supersedes: D027
Why: 动态比较可以避免再维护一套容易失真的备份状态；粘性、只升级的 `offline_backup_scope` tag 同时保留 alias 切换历史和所需备份范围；复验实际文件和规定触发的真实恢复能够证明备份不仅在 catalog 中存在而且可用。
Trade-off: 硬盘未连接时不能即时查看缺失对象；每次连接复验全部对象会延长备份窗口，完整可恢复性仍依靠规定触发的恢复演练，而不是每次都加载大型模型。

D037 — 数据、训练、模型晋级和测评继续显式选择完整版本；服务使用稳定 Registered Model `mVllm2`，每个 `model-v...` 映射为其中一个数值 Model Version，`candidate`/`production` 是唯一逻辑路由，`models/current` 只缓存 alias 精确目标。
Supersedes: D007
Why: MLflow alias 作用于同一 Registered Model 内的 Model Version；统一模型名才能形成项目唯一 candidate/production 路由。把 current 降为经精确版本校验的物化缓存，可以避免 Registry 与本地链接各自选择后分叉。
Trade-off: 服务启动需要访问 MLflow 解析 alias，并在 alias 改变后重新物化；MLflow 不可用或本地缓存版本不匹配时服务会 fail-closed。

D038 — `prepared` 表示 MLflow Run 创建前的本地冻结状态；Run 创建后，MLflow 原生 RunStatus 只表示进程状态，项目 `workflow_state` tag 表示 running/partial/failed/completed/archived；模型晋级同时验证二者和全部子 Run。
Why: MLflow 原生状态没有项目所需的 partial、completed 或 archived 语义；显式映射避免查询、恢复和晋级分别解释同一个状态。
Trade-off: 实现必须原子维护原生状态与 tag 的合法组合，并拒绝人工或异常操作产生的非法组合。

D039 — 正式事实错误不原地修正：旧 MLflow 对象标记 `record_validity: invalid`，manifest 只更新有效性与替代引用，实际修正创建新的可读版本和 MLflow 对象。
Why: 区分导出器错误、可变路由和正式事实错误，才能同时保持 MLflow 权威、Git 可见的失效信息和不可变实验血缘。
Trade-off: Git 中会保留已失效但可审计的旧 manifest；任何下游入口都必须在线核对 MLflow `record_validity`，不能只凭旧文件存在放行。

D040 — 模型采用两阶段 Registry 生命周期：完成训练先登记 staging Model Version，正式 eval 精确引用其可读身份与数值版本，passed 后再单向绑定 `eval_id`；candidate/production 均要求该绑定有效。
Why: “eval 必须引用真实 Registry Model Version”与“模型注册必须先有 passed eval”会形成无法执行的生命周期闭环；先固定模型实体再测评，既消除闭环，也阻止测评后替换被测权重。
Trade-off: Registry 中会保留未通过或尚未完成正式测评的 staging Model Version；它们只保留证据，不能获得活动 alias。

D041 — holdout 预注册由统一入口原子冻结到 eval staging 稳定路径，claim 和 MLflow 以完整内容摘要绑定；跨机器恢复比较身份与摘要，不绑定机器本地绝对路径。
Why: 用户提供的临时路径既不适合作为长期审计位置，也会破坏双机恢复；稳定副本提供可追溯证据，摘要则同时阻止内容漂移并允许相同内容在不同机器恢复。
Trade-off: 预注册冻结后规则或阈值的任何变化都必须创建新的 eval 身份；文件系统消费证据与 MLflow 状态仍通过显式可恢复顺序协调，而不是假装存在跨系统原子事务。
D042 — 独立全量训练另建full范围train版本，使用全部开发候选去重后的冻结输入，单次实际训练只产出full模型；三折结构保持原样。
Why: 用户于2026-09-13明确接受独立全量训练范围。full模型需要合法且可验证的全量来源，不能把三折中的某个产物改名登记；训练范围、Run结构和模型产物证据必须一致。
Trade-off: full训练配置不引入验证切分或holdout训练中评测，最终质量依赖另行授权的独立holdout验收；本次代码及隔离CPU接线沿用用户“补齐”的既有实施授权，范围确认本身不自动授权实际训练或holdout使用。
-->
