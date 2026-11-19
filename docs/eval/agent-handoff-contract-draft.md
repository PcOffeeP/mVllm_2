# Agent 视觉与跨仓交付契约草案（拟 `tensile-vlm/v5`）

> **状态声明：草案 / 未冻结 / 不修改现有 `tensile-vlm/v4.1` 运行时。**
> 当前 `TensileAgent` 生产与验收仍运行于 `mVllm_2` 交付的冻结契约 `tensile-vlm/v4.1`（及回滚 `v2`）。本文仅定义未来 `TensileAgent-Finetune` 向 `TensileAgent` 交付新一代视觉模型时的目标契约边界，**不构成正式冻结、不分配 `contract_hash`、不授权修改 `TensileAgent` 现有运行时代码或配置**。

**失效条件：** 本仓五类 11 叶字段输出契约（[output-contract.md](output-contract.md) 与 `script/five_label_eval/score.py`）改动；`TensileAgent` 运行时不变量或跨仓交付校验协议改动；本草案正式冻结为 `tensile-vlm/v5` JSON 契约文件并分配 `contract_hash` 后，由正式契约文件取代。以上任一发生，本文须重新核对或归档。

## 定位与适用范围

- **目标契约名**：拟称 `tensile-vlm/v5`（`contract_hash` 待正式冻结时按规范化契约 JSON 的 SHA-256 分配）。
- **上游职责（`TensileAgent-Finetune`）**：负责五类标注数据演化、新一代视觉模型微调、切片级单轮能力评测、未来新模型的推理服务封装以及轻量交付组件产出。
- **下游职责（`TensileAgent`）**：保持职责分离，仅通过 HTTP API、版本化契约和轻量交付清单消费视觉服务；不引入训练流水线、模型权重、checkpoint 或 `TensileAgent-Finetune` 的本地绝对路径。

---

## 1. 单轮视觉输出与方向语义映射

### 1.1 五类 11 叶字段结构

单轮视觉输出直接沿用本仓已定义的五类 11 叶字段（口径与 [output-contract.md](output-contract.md) 及 `script/five_label_eval/score.py` 的 `five-label-score/3` 保持一致）：

| 顶层键 | 类型 | 叶字段与允许取值 | 说明 |
| --- | --- | --- | --- |
| `断裂状态` | 字符串单值 | `未断裂` / `发生断裂` / `已断裂` / `无法判断` | 唯一方向搜索信号源 |
| `断裂模式` | 字符串单值 | `脆性断裂` / `韧性断裂` / `半脆半韧断裂` / `无法判断` | 最终投影汇总字段 |
| `断裂位置` | 字符串单值 | `标距内` / `标距外非根部` / `夹持根部` / `无法判断` | 最终投影汇总字段 |
| `异常情况` | 嵌套对象（3 叶项） | `未夹紧`、`视频异常`、`爆炸性断裂`；每叶项取值 `是` / `否` / `无法判断` | 拒判 / 复查门槛与异常汇总 |
| `断裂现象` | 嵌套对象（5 叶项） | `伸长`、`颈缩`、`开裂`、`界面分离`、`断后脱夹`；每叶项取值 `是` / `否` / `无法判断` | 前兆与过程现象汇总 |

取值纪律沿用 [output-contract.md](output-contract.md) §1：

1. 不确定值统一为 `无法判断`；片段层不含 `无`。
2. 嵌套对象（`异常情况`、`断裂现象`）必须显式给出全部叶项，不允许省略叶项，不允许用空对象或空列表代替「全部为否」。
3. 严禁同义改写、别名映射或静默归一化。

### 1.2 与 `tensile-vlm/v4.1` 的显式差异

对照 `TensileAgent` 现行冻结契约 `tensile-vlm/v4.1`：

| 维度 | `tensile-vlm/v4.1`（现行冻结） | `tensile-vlm/v5`（本草案） |
| --- | --- | --- |
| 顶层字段 | 4 个扁平英文字段：`clip_state`、`fracture_mechanism`、`fracture_site`、`special_case` | 5 个顶层中文字段（11 个叶字段）：3 个单值 + 2 个嵌套对象（`异常情况` 3 叶项、`断裂现象` 5 叶项） |
| `临界未断裂` | `clip_state` 包含 `临界未断裂`（对应 `fracture_event_is_after_clip_with_visible_precursors`） | **移除 `临界未断裂`**；前兆线索改由 `断裂现象`（如 `伸长`、`颈缩`、`开裂`）独立表达，与方向状态解耦 |
| `爆炸性断裂` / `界面脱粘` | 混在 `fracture_mechanism` 单选枚举中 | `爆炸性断裂` 归入 `异常情况.爆炸性断裂`；`界面脱粘` 改由 `断裂现象.界面分离` 独立表达；新增 `断裂现象.断后脱夹` |
| 不确定值 | `clip_state` 用 `无法判断`，其余三字段用 `null` | 全部 11 叶字段统一用 `无法判断`；片段层不含 `无` |
| 位置枚举 | 英文枚举（`inside_gauge` / `outside_gauge_non_root` / `grip_root`） | 沿用本仓中文枚举（`标距内` / `标距外非根部` / `夹持根部` / `无法判断`）；若冻结时需映射到下游严重度表，由冻结契约显式声明 |

### 1.3 `断裂状态` 到 Agent 方向搜索的映射

| `断裂状态` | Agent 搜索方向语义 | 简写 | 边界更新含义 |
| --- | --- | --- | --- |
| `未断裂` | `fracture_event_is_after_clip` | `later` | 断裂事件位于当前片段之后，可推进左边界 |
| `发生断裂` | `fracture_event_is_within_clip` | `within` | 断裂事件落在当前片段内，可在当前窗口内继续细化或收敛 |
| `已断裂` | `fracture_event_is_before_clip` | `earlier` | 断裂事件位于当前片段之前，可收紧右边界 |
| `无法判断` | `no_directional_evidence` | — | 无方向证据，不得收缩候选区间边界 |

### 1.4 运行时不变量

未来接入 `tensile-vlm/v5` 时，必须继续满足 `TensileAgent` 的核心运行时不变量：

1. **方向语义单一来源与代码单调维护**：`TensileAgent` 只从 `断裂状态` 获取方向语义；候选区间边界、覆盖检查、单调收缩、预算控制、冲突处理和终止判定（`bounds` / `coverage` / `shrinkage` / `budget` / `conflicts` / `termination`）完全由代码确定，不得由视觉模型直接决定最终时间边界。
2. **异常门槛与拒判隔离**：`异常情况`（尤其是 `未夹紧`、`视频异常`）用于拒判（`unrecognized`）或人工复查门槛，不作为方向搜索证据；基础设施错误、契约漂移或预处理元数据缺失不得伪装成 `无法判断` 或有效视觉结论。
3. **汇总字段与定位解耦**：`断裂模式`、`断裂位置`、`断裂现象` 仅用于最终投影汇总（summary projection），不参与方向搜索的区间收缩。
4. **禁止任务内静默降级**：同一任务内不得在 `tensile-vlm/v5` 与 `tensile-vlm/v4.1` 之间自动降级或混用契约。

---

## 2. HTTP 推理服务与身份接口归属

### 2.1 职责边界

- **服务提供方（`TensileAgent-Finetune`）**：负责未来新一代视觉模型的 HTTP 推理服务封装、预处理一致性（如处理器帧数与输入记录约束，见 [inference-entry.md](inference-entry.md) §7）以及契约身份暴露。
- **服务消费方（`TensileAgent`）**：保持只做 HTTP 客户端消费与 fail-closed 校验，不直接加载模型权重，也不依赖训练机源码或本地路径。

### 2.2 接口约定

1. **推理端点（OpenAI-compatible）**：`POST /v1/chat/completions`，承载单轮视觉片段推理请求与五类 11 叶字段结构化输出。
2. **契约与身份端点**：`GET /v1/tensile/contract`，暴露当前服务实例绑定的冻结契约与部署身份，供 `TensileAgent` 在启动检查与运行前校验使用。
3. **每轮 `deployment_manifest`**：服务契约端点与每轮推理元信息必须提供可校验的 `deployment_manifest`，至少包含：
   - `contract_version`（拟 `tensile-vlm/v5`）与 `contract_hash`（冻结契约 JSON 的 SHA-256）
   - 基础模型（base model）身份与摘要
   - adapter / 合并权重（checkpoint 或 merged artifact）身份与摘要
   - processor / tokenizer 身份与预处理约束（如 `max_frames` 等）
   - runtime 身份（推理引擎、精度 / 量化配置、服务版本）

### 2.3 Fail-Closed 校验与当前实施状态

- `TensileAgent` 消费侧在请求前及响应校验阶段核对 `contract_version`、`contract_hash` 与 `deployment_manifest` 完整性；任一不匹配、缺失或漂移必须 fail-closed 报错并终止当前视觉调用，不得静默降级。
- 现状说明：按 [inference-entry.md](inference-entry.md) §8，本仓 `script/five_label_eval/infer.py` 当前仅声明 `fake` 与 `transformers`，`http` backend 尚未实现；本文仅冻结接口归属草案，不代表推理服务或 `http` backend 已实现。

---

## 3. 跨仓轻量交付组件约定

未来正式交付时，由 `TensileAgent-Finetune` 产出两份轻量只读 JSON 清单组件，供 `TensileAgent` 消费：

| 交付组件 | 产出方 | 职责与核心内容 | 路径与边界约束 |
| --- | --- | --- | --- |
| `model_component.json` | `TensileAgent-Finetune` | 声明交付模型的基础模型、adapter / 合并权重、processor、摘要与来源记录 | **不再复用 `mVllm_2` 的 `workspace/models/` 历史路径**；仅包含可迁移的轻量元数据与校验摘要 |
| `service_component.json` | `TensileAgent-Finetune` | 声明推理服务入口、契约版本与 `contract_hash`、预处理 / 运行环境约束及 `/v1/tensile/contract` 端点信息 | 与 `model_component.json` 身份互相绑定，禁止包含本机或训练机私有绝对路径 |

- **`TensileAgent` `delivery/` 侧消费规则**：仅只读消费上述轻量组件，校验文件 SHA-256、组件间身份一致性以及与目标契约 `contract_hash` 的匹配；**不读取模型权重文件、checkpoint、私有训练数据或 `TensileAgent-Finetune` 的本地绝对路径**。

---

## 4. 两层评测分工与标注同步口径

### 4.1 两层评测分工

两层评测目标不同，**口径独立、结果分开报告、互不替代**：

| 评测层级 | 负责仓库 | 评测对象 | 评分口径与关注重点 |
| --- | --- | --- | --- |
| 切片级 VLM 单轮能力评测 | `TensileAgent-Finetune` | 1,621 条候选子视频 | 使用 `script/five_label_eval/score.py`（现行 `five-label-score/3`），按来源分层并列报告、不合成加权总分；关注单轮五类 11 叶字段的格式合法性、语义指标、失败三态与跨字段冲突（见 [design-test.md](../design-test.md)） |
| 整片级 Agent 端到端定位评测 | `TensileAgent` | 110 条源视频 | 覆盖迭代采样、方向搜索收敛、断裂时间区间定位误差、`fracture`/`no_fracture`/`unrecognized` 终止判定以及最终五类属性投影汇总 |

### 4.2 标注表同步口径

- 本仓新版 110 条源视频标注表位于 [data/annotation-table-full.csv](../../data/annotation-table-full.csv)。
- 未来将该标注表同步给 `TensileAgent` 用于端到端评测时，必须采用**只读快照 + SHA-256 清单**方式交接（快照文件、版本标识、生成时间、字段口径说明及文件 SHA-256 校验和），确保跨仓版本可追溯且可复核。
- `TensileAgent` 侧不得直接读取 `TensileAgent-Finetune` 工作区内的本地绝对路径。
