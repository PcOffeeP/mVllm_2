# 微调模型与 Agent 接口契约

> 项目：mVllm-frame-interval-agent
> 日期：2026-06-14
> 版本：v1.0
> 状态：Current Repository Design

---

## 0. 文档地位与适用范围

本文档是 `mVllm-frame-interval-agent` 项目中**微调模型侧**与 **Agent 迭代侧**之间的**单一接口契约**。

- [`docs/model_finetuning_design.md`](./model_finetuning_design.md)：定义模型微调侧的数据管道、训练样本构建、模型训练流程及模型侧配置。
- [`docs/agent_iteration_design.md`](./agent_iteration_design.md)：定义 Agent 迭代控制器、评估体系及 Agent 侧配置。
- **本文档**：定义上述两者之间的所有交互边界，包括模型输出 JSON Schema、Tool Schema、Prompt 契约、Tool 执行层接口、最终输出 Schema、索引/时间换算规则等。

**两队并行实现时，以此文档为准。** 若本文与训练 YAML、`dataset_info.json`、CSV 标注文件或代码实现不一致，以对应权威文件为准，并优先修订本文。

---

## 1. 契约目的与范围

本契约明确微调模型（MiniCPM-V 4.6，经 LLaMA-Factory 微调）与外部迭代控制器（Meta-Agent）之间的所有接口边界，确保：

1. 模型侧输出的 JSON 格式可被 Agent 侧稳定解析。
2. Agent 侧通过标准 Tool Schema 驱动模型推理，不依赖具体 LLM 后端实现。
3. 工具执行层（视频采样、模型推理、结果解析）的输入输出语义一致。
4. Prompt 构建、索引/时间换算、最终输出结构均有统一约定。

**本文档不包含** LLM 后端类定义（如 `BaseAgentLLM`、`RemoteAPIClient`、`LocalClient` 等），这些保留在 [`docs/agent_iteration_design.md`](./agent_iteration_design.md) 中。

---

## 2. 微调模型输出 JSON Schema

微调模型对每一轮输入视频片段的推理输出必须是如下 JSON 对象。

### 2.1 Schema 定义

```json
{
  "has_fracture": true,
  "fracture_between": [17, 18],
  "type": "韧性断裂",
  "location": "inside_gauge",
  "confidence": 0.92
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `has_fracture` | boolean | 是 | 当前视频片段是否包含断裂 |
| `fracture_between` | `[int, int]` / `null` | 是 | 断裂发生在第 i 帧与第 i+1 帧之间，格式为 `[i, i+1]`，其中正常区间 `j = i + 1`；数组长度固定为 2（`minItems: 2`, `maxItems: 2`）。<br>边界哨兵 `[0, 0]` 与 `[N-1, N-1]` 表示断裂位于首采样帧之前/末采样帧之后（或恰好在边界），不代表两帧之间，评估时单独处理。 |
| `type` | string | 是 | 断裂模式或异常类别，取值须为 CSV 实际枚举之一（见 2.2 节） |
| `location` | string | 是 | 标距内/外位置判断：`inside_gauge` / `outside_gauge` / `N/A` |
| `confidence` | float | 是 | 模型对当前判断的主观置信度，范围 `[0.0, 1.0]` |

### 2.2 `type` 取值约束

`type` 全局枚举共 10 类：7 个断裂类 + 3 个非断裂/异常类，组合标签作为独立类别：

1. `韧性断裂`
2. `脆性断裂`
3. `界面脱粘`
4. `齐根断裂`
5. `爆炸性断裂`
6. `半脆半韧断裂`
7. `界面脱粘、齐根断裂`（组合标签，独立类别）
8. `未断裂`
9. `未夹紧`
10. `视频异常`

### 2.3 `location` 取值约束

| 取值 | 含义 |
|---|---|
| `inside_gauge` | 断裂发生在标距内 |
| `outside_gauge` | 断裂发生在标距外 |
| `N/A` | 不适用或异常样本 |

### 2.4 `confidence` 取值约束

- 类型：`float`
- 范围：`[0.0, 1.0]`
- 含义：模型对当前输出整体判断的主观置信度。
- 训练阶段 Ground Truth 样本统一标注为 `1.0`（详见 [`docs/model_finetuning_design.md`](./model_finetuning_design.md) 第 3.3 节）；推理时由模型自报。

### 2.5 `has_fracture = false` 时的字段规则

**本节约束的是模型推理输出 JSON 与 Agent 最终输出中的 `type` / `location`**，即对应当前输入片段的语义；训练阶段用于保留父视频真实断裂信息的 `source_type` / `source_location` 见第 2.6 节。

当模型判断当前片段无断裂时，输出必须遵守以下规则：

| 字段 | 规则 |
|---|---|
| `has_fracture` | `false` |
| `fracture_between` | `null` |
| `type` | 仅允许 `未断裂` / `未夹紧` / `视频异常` 三者之一，**不允许输出 `none`**。训练标签由样本构造器决定：人工负片段（断裂前/后裁剪）默认 `未断裂`，真实无断裂/异常样本保留其 CSV 标注；推理时由模型直接预测当前片段类别，Agent 最终输出再通过多轮预测投票/置信度聚合决定。 |
| `location` | 必须为 `"N/A"` |
| `confidence` | 仍需给出，表示对"无断裂"判断的置信度 |

负样本输出示例：

```json
{
  "has_fracture": false,
  "fracture_between": null,
  "type": "未断裂",
  "location": "N/A",
  "confidence": 0.95
}
```

### 2.6 训练样本 metadata：`source_type` / `source_location`

为消除与 [`docs/model_finetuning_design.md`](./model_finetuning_design.md) 中"断裂前/后人工负样本继承父视频 type/location"的冲突，训练样本在 LLaMA-Factory 对话格式之外额外携带以下 metadata 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_type` | string | 父视频在 CSV 中的真实断裂模式（7 个断裂类之一：`韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂`）。仅当父视频 `has_fracture = true` 时有效；否则与 `type` 一致。 |
| `source_location` | string | 父视频在 CSV 中的真实断裂位置（`inside_gauge` / `outside_gauge` / `N/A`）。仅当父视频 `has_fracture = true` 时有效；否则为 `"N/A"`。 |

使用规则：

1. **当前片段 `has_fracture = true`**：`type` / `location` 直接描述当前片段，`type` 必须且只能取 7 个断裂类之一：`韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂`；`location` 取 `inside_gauge` / `outside_gauge` / `N/A`；此时 `source_type` / `source_location` 与 `type` / `location` 相同。
2. **当前片段 `has_fracture = false` 但来自 `has_fracture = true` 的父视频**（如断裂前/后人工负样本子片段）：
   - 模型输出 JSON 中的 `type` 必须为 `未断裂` / `未夹紧` / `视频异常` 之一，`location` 必须为 `"N/A"`。
   - 训练 metadata 中的 `source_type` / `source_location` 保留父视频真实信息，用于追溯与后续评估分析，**不进入模型输出 JSON**。
3. **当前片段 `has_fracture = false` 且父视频本身无断裂**（全时长异常样本）：`source_type` / `source_location` 与 `type` / `location` 一致。

### 2.7 评估时的样本筛选规则

- **`type` macro-F1**：仅在 `has_fracture = true` 的预测样本上统计，且只在 7 个断裂类别上计算：`韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂`。其中组合标签 `界面脱粘、齐根断裂` 作为独立类别参与 macro-F1。
- **`location` 准确率**：仅在 `has_fracture = true` 的预测样本上统计。
- **异常/无断裂样本**（`未断裂` / `未夹紧` / `视频异常`）：不纳入 `type` macro-F1 与 `location` 准确率计算，改用**异常样本失败率**衡量（即 `is_abnormal = TRUE` 或 `has_fracture = false` 的样本中，模型错误地输出 `has_fracture = true` 的比例）。

---

## 3. Agent → 模型调用工具 Schema

Agent 通过 Native Function Calling 调用 `sample_and_infer` 工具，由工具执行层完成视频采样与模型推理。

### 3.1 Tool Schema

```python
{
  "type": "function",
  "function": {
    "name": "sample_and_infer",
    "description": "在指定时间区间内采样视频帧，调用微调模型进行推理",
    "parameters": {
      "type": "object",
      "properties": {
        "sample_range": {
          "type": "array",
          "items": {"type": "number"},
          "description": "采样时间区间 [start_seconds, end_seconds]"
        },
        "num_frames": {
          "type": "integer",
          "description": "视频采样帧数上限，语义等同 video_maxlen；实际帧数由视频时长、video_fps 与该上限共同决定",
          "default": 36
        },
        "video_fps": {
          "type": "number",
          "description": "视频采样帧率超参数，需与训练/推理解码配置保持一致",
          "default": 8.0
        },
        "sampling_strategy": {
          "type": "string",
          "enum": ["uniform", "adaptive"],
          "description": "采样策略：uniform=均匀采样；adaptive=自适应采样（断裂点附近更密）。首版默认仅要求 uniform。adaptive 仅在工具执行层能生成与 frames 序列完全一致的临时 .mp4 时允许，否则必须拒绝或降级为 uniform。",
          "default": "uniform"
        },
        "prompt": {
          "type": "string",
          "description": "发送给微调模型的完整 prompt"
        },
        "expected_schema": {
          "type": "object",
          "description": "期望模型输出的 JSON schema"
        }
      },
      "required": ["sample_range", "prompt"]
    }
  }
}
```

### 3.2 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `sample_range` | `[number, number]` | 是 | — | 在原始视频上的采样时间区间（秒），必须在 `[0, duration]` 范围内 |
| `num_frames` | integer | 否 | 36 | 本轮采样帧数上限，语义等同训练/推理配置中的 `video_maxlen`；实际输入帧数 `N` 由 `sample_range` 时长、`video_fps` 与该上限共同决定 |
| `video_fps` | number | 否 | 8.0 | LLaMA-Factory 视频采样帧率超参数，需与模型微调训练配置保持一致；后续可通过消融实验调整 |
| `sampling_strategy` | string | 否 | `"uniform"` | `"uniform"` 为均匀采样；`"adaptive"` 为在关注区间加密采样。首版默认仅要求实现 `uniform`；`adaptive` 仅在工具执行层能生成与 `frames` 序列完全一致的临时 `.mp4` 时允许，否则必须拒绝或降级为 `uniform` |
| `prompt` | string | 是 | — | 发送给微调模型的完整 prompt，须符合第 6 节 Prompt 契约 |
| `expected_schema` | object | 否 | 见第 2 节 | 期望模型输出的 JSON schema，工具执行层据此解析 |

---

## 4. Agent 终止工具 Schema

当 Agent 判断已定位到足够精确的断裂时刻，或确认当前视频无断裂/异常时，调用 `terminate` 工具结束迭代。

### 4.1 Tool Schema

```python
{
  "type": "function",
  "function": {
    "name": "terminate",
    "description": "终止迭代，返回最终分析结果",
    "parameters": {
      "type": "object",
      "properties": {
        "has_fracture": {
          "type": "boolean",
          "description": "是否存在断裂。false 表示当前视频/片段无断裂或属于异常样本"
        },
        "time_range": {
          "anyOf": [
            {
              "type": "array",
              "items": {"type": "number"},
              "minItems": 2,
              "maxItems": 2
            },
            {"type": "null"}
          ],
          "description": "最终断裂时间区间 [start_seconds, end_seconds]；has_fracture=false 时应置为 null"
        },
        "time_estimate": {
          "anyOf": [
            {"type": "number"},
            {"type": "null"}
          ],
          "description": "断裂时间估计值（区间中点或模型最可能值）；has_fracture=false 时应置为 null"
        },
        "frame_range": {
          "anyOf": [
            {
              "type": "array",
              "items": {"type": "integer"},
              "minItems": 2,
              "maxItems": 2
            },
            {"type": "null"}
          ],
          "description": "最终断裂帧区间 [start_frame, end_frame]；has_fracture=false 时应置为 null"
        },
        "type": {
          "type": "string",
          "description": "断裂模式或异常类别。has_fracture=true 时为 7 个断裂类别之一：`韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂`；has_fracture=false 时仅允许 `未断裂` / `未夹紧` / `视频异常` 三者之一（不允许输出 `none`）。推理最终输出由模型多轮预测投票/置信度聚合决定：若模型在多轮中明确预测 `未夹紧` 或 `视频异常` 且置信度可接受，则采用该预测；否则默认 `未断裂`，并将 `confidence_level` 降至 `中` 或 `低`（至少不为 `高`）。训练标签仍由样本构造器决定。"
        },
        "location": {
          "type": "string",
          "description": "标距内位置判断。has_fracture=true 时为 `inside_gauge` / `outside_gauge` / `N/A`；has_fracture=false 时必须为 `N/A`"
        },
        "confidence": {
          "type": "number",
          "description": "最终置信度 0-1"
        },
        "confidence_level": {
          "type": "string",
          "enum": ["高", "中", "低", "不可信"],
          "description": "置信度等级"
        }
      },
      "required": ["has_fracture", "time_range", "time_estimate", "frame_range", "type", "location", "confidence", "confidence_level"]
    }
  }
}
```

### 4.2 参数说明

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `has_fracture` | boolean | 是 | 是否存在断裂 |
| `time_range` | `[number, number]` / `null` | 是 | 最终断裂时间区间（秒） |
| `time_estimate` | number / `null` | 是 | 断裂时间估计值（秒） |
| `frame_range` | `[int, int]` / `null` | 是 | 最终断裂帧区间 |
| `type` | string | 是 | 断裂模式或异常类别；`has_fracture=true` 时为 7 个断裂类别之一，`has_fracture=false` 时仅允许 `未断裂` / `未夹紧` / `视频异常`，取值规则同第 2.2、2.5 节 |
| `location` | string | 是 | 标距位置，取值规则同第 2.3 节 |
| `confidence` | float | 是 | 最终综合置信度，`[0.0, 1.0]` |
| `confidence_level` | string | 是 | 置信度等级：`高` / `中` / `低` / `不可信` |

### 4.3 `has_fracture = false` 时的字段规则

| 字段 | 规则 |
|---|---|
| `has_fracture` | `false` |
| `time_range` | 统一填 `null` |
| `time_estimate` | 统一填 `null` |
| `frame_range` | 统一填 `null` |
| `type` | 仅允许 `未断裂` / `未夹紧` / `视频异常` 三者之一，不允许输出 `none`。训练标签由构造器决定：人工负片段默认 `未断裂`，真实无断裂/异常样本保留其标注；推理最终输出由模型多轮预测投票/置信度聚合决定：若模型在多轮中明确预测 `未夹紧` 或 `视频异常` 且置信度可接受，则采用该预测；否则默认 `未断裂`，并将 `confidence_level` 降至 `中` 或 `低`（至少不为 `高`） |
| `location` | 必须为 `"N/A"` |
| `confidence` | 仍需给出，表示对"无断裂"判断的综合置信度 |
| `confidence_level` | 按第 4.4 节分级标准填写 |

### 4.4 `confidence_level` 分级标准

Agent 调用 `terminate` 时，应综合多轮模型自报 confidence 的平均值/趋势、type 和 location 一致性、采样区间收敛性给出 `confidence`，并按以下标准分级：

| 等级 | confidence 范围 |
|---|---|
| `高` | 0.90 ~ 1.00 |
| `中` | 0.70 ~ 0.89 |
| `低` | 0.50 ~ 0.69 |
| `不可信` | 0.00 ~ 0.49 |

> **单轮 `round_confidence_level` 与最终 `confidence_level` 的区分**
>
> - 每轮模型输出仅包含数值 `confidence`；工具执行层/Agent 代码根据上述分层标准，将其映射为 `round_confidence_level`（`高`/`中`/`低`/`不可信`），供 Agent 内部冲突处理、停止条件使用。
> - `terminate` 的最终 `confidence_level` 由 Agent 综合多轮结果后给出，仍使用同一四级分层。
> - 以上范围为硬编码分层边界，Agent 内部与最终输出必须一致。

---

## 5. Tool 执行层接口

Tool 执行层为通用代码，按 Action Plan 执行，不硬编码业务逻辑。

### 5.1 `VideoSampler.sample`

`VideoSampler.sample` 返回帧序列列表，每个元素必须包含 `original_frame` / `timestamp` 等字段（见本节下文）。这些帧信息用于把模型输出的 `fracture_between` 换算回原视频时间/帧号。模型实际视觉输入使用工具层生成的临时 `.mp4` 推理片段路径（见 `SampleAndInferResult.model_video_path`）。

**签名**

```python
def sample(
    video_path: str,
    sample_range: list[float],
    num_frames: int,
    video_fps: float = 8.0,
    strategy: str = "uniform"
) -> list[dict]:
```

**输入**

| 参数 | 类型 | 说明 |
|---|---|---|
| `video_path` | string | 原始视频文件路径 |
| `sample_range` | `[float, float]` | 采样时间区间 `[start_seconds, end_seconds]` |
| `num_frames` | int | 采样帧数上限，语义等同 `video_maxlen` |
| `video_fps` | float | 视频采样帧率超参数，默认 `8.0` |
| `strategy` | string | `"uniform"` 或 `"adaptive"`；首版默认仅要求 `uniform` |

**输出**

返回帧序列列表，每个元素为字典：

```json
{
  "input_index": 0,
  "original_frame": 0,
  "timestamp": 0.0,
  "frame_path": "data/03_frames/video_0001_focus_3s_50pct/frame_0000.jpg"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `input_index` | int | 采样序号，从 0 开始，到实际采样帧数 `N - 1` |
| `original_frame` | int | 该采样帧在原始视频中的全局帧号 |
| `timestamp` | float | 该采样帧在原始视频中的时间戳（秒） |
| `frame_path` | string / `null` | 该采样帧对应的可选图文件路径，用于调试、审计或复现；不是模型主输入 |

> **训练与推理一致性**：训练阶段构造 LLaMA-Factory 多模态样本时，`videos` 字段直接引用 `.mp4` 训练子视频路径；推理阶段应向 `InferenceClient` 传入与本轮 `sample_range` 对应的临时 `.mp4` 推理片段路径。`frames` 只承担索引/时间映射职责。
> `fracture_between` 的索引必须对应模型实际看到的采样帧序列；因此工具层生成 `model_video_path` 时,必须保证 `frames` 的顺序与训练/推理解码器在 `video_fps` 与 `video_maxlen` 下送入模型的帧顺序一致。默认配置下 `video_fps=8.0`、`video_maxlen=36`，实际帧数为 `N = min(total_frames_in_clip, video_maxlen, max(1, floor(duration * video_fps)))`。


### 5.2 `VideoClipBuilder.build`

`VideoClipBuilder.build` 负责从原始视频中截取本轮模型推理所需的临时 `.mp4` 片段。该片段只服务 Agent 当前轮推理，不属于模型微调训练数据集中的持久化子视频。

**签名**

```python
def build(
    source_video: str,
    sample_range: list[float],
    frames: list[dict],
    video_fps: float = 8.0,
    video_maxlen: int = 36,
    sampling_strategy: str = "uniform"
) -> str:
```

**输入**

| 参数 | 类型 | 说明 |
|---|---|---|
| `source_video` | string | 原始视频文件路径 |
| `sample_range` | `[float, float]` | 本轮推理时间区间 |
| `frames` | list[dict] | 与模型实际采样序列一致的映射帧列表 |
| `video_fps` | float | 视频采样帧率超参数，默认 `8.0` |
| `video_maxlen` | int | 视频采样帧数上限，默认 `36` |
| `sampling_strategy` | string | 本轮采样策略，默认 `uniform` |

**输出**

- 返回本轮实际传给 `InferenceClient.infer` 的 `.mp4` 路径，建议位于运行期缓存目录，如 `data/runtime/agent_clips/{video_id}_round{n}.mp4`。
- 训练集持久化子视频位于 `data/02_subvideos/*.mp4`，只用于模型微调训练；Agent 推理阶段不复用训练子视频，而是基于原始视频和当前 `sample_range` 动态生成临时推理片段。
- 当 `sampling_strategy = "adaptive"` 时，`VideoClipBuilder` 不能只裁剪普通连续视频片段；它必须生成一个帧序列与 `frames` 完全一致的临时 `.mp4`，确保模型实际看到的帧索引与 `fracture_between` 映射一致。若暂不支持该能力，工具执行层必须拒绝 `adaptive` 或降级为 `uniform` 并在返回结果中记录实际策略。

### 5.3 `SampleAndInferResult` 结构

`_execute_sample_and_infer` 返回给 Agent Loop 的结构化结果如下：

```json
{
  "model_output": {
    "has_fracture": true,
    "fracture_between": [17, 18],
    "type": "韧性断裂",
    "location": "inside_gauge",
    "confidence": 0.92
  },
  "frames": [
    {
      "input_index": 0,
      "original_frame": 4317,
      "timestamp": 143.9,
      "frame_path": "data/03_frames/video_0001_focus_3s_50pct/frame_0000.jpg"
    }
  ],
  "model_video_path": "data/runtime/agent_clips/video_0001_round3.mp4",
  "sample_range": [143.9, 146.9],
  "video_fps": 8.0,
  "video_maxlen": 36,
  "num_sample_frames": 24,
  "sampling_strategy": "uniform",
  "inferred_time_range": [146.12, 146.25],
  "inferred_frame_range": [4384, 4387],
  "boundary_status": "none",
  "parse_error": null,
  "round_confidence_level": "高"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model_output` | dict | 是 | 经 `ResultParser` 解析后的模型输出 JSON，符合第 2 节 Schema |
| `frames` | list[dict] | 是 | 本轮 `VideoSampler.sample` 返回的完整帧序列，包含 `input_index`、`original_frame`、`timestamp`、`frame_path` |
| `model_video_path` | string | 是 | 本轮实际送入微调模型的临时 `.mp4` 推理片段路径；应与 `sample_range` 和 `frames` 映射一致 |
| `sample_range` | `[number, number]` | 是 | 本轮采样时间区间 `[start_seconds, end_seconds]` |
| `video_fps` | number | 是 | 本轮使用的视频采样帧率超参数，默认 `8.0` |
| `video_maxlen` | int | 是 | 本轮使用的视频采样帧数上限，默认 `36` |
| `num_sample_frames` | int | 是 | 本轮实际采样帧数，即 `len(frames)` |
| `sampling_strategy` | string | 是 | 本轮实际执行的采样策略，`uniform` 或 `adaptive` |
| `inferred_time_range` | `[number, number]` / `null` | 否 | 当 `model_output.has_fracture = true` 时，由 `fracture_between` 换算得到的原视频时间区间；否则为 `null` |
| `inferred_frame_range` | `[int, int]` / `null` | 否 | 当 `model_output.has_fracture = true` 时，由 `fracture_between` 与 `frames[].original_frame` 换算得到的原视频帧区间；否则为 `null` |
| `boundary_status` | string | 是 | 边界哨兵状态：`none` / `left_sentinel` / `right_sentinel`。`left_sentinel` 对应 `fracture_between = [0, 0]`，`right_sentinel` 对应 `[N-1, N-1]`；哨兵产生的区间仅为临时扩展提示，不得单独触发收敛终止 |
| `parse_error` | string / `null` | 是 | 若 `ResultParser.parse` 失败，此处为错误描述；否则为 `null` |
| `round_confidence_level` | string | 是 | 由 `model_output.confidence` 按第 4.4 节四级分层派生：`高` / `中` / `低` / `不可信`；Agent 内部冲突处理、停止条件均使用此字段 |

**使用规则**

1. `_execute_sample_and_infer` 必须按上述结构装配，字段名不得改变；`_transition` 等 Agent 内部逻辑只读取 `SampleAndInferResult` 的命名字段。
2. `inferred_time_range` 与 `inferred_frame_range` 的换算规则见第 8 节。
3. `boundary_status` 由工具执行层根据 `fracture_between` 判定：正常区间 `[i, i+1]` 为 `none`；`[0, 0]` 为 `left_sentinel`；`[N-1, N-1]` 为 `right_sentinel`。
4. 若 `parse_error` 非 `null`，Agent 侧按解析失败流程处理（重试或终止），不得继续基于 `model_output` 做状态转移。

### 5.4 `InferenceClient.infer`

**签名**

```python
def infer(
    video_path: str,
    prompt: str
) -> dict:
```

**输入**

| 参数 | 类型 | 说明 |
|---|---|---|
| `video_path` | string | 本轮送入微调模型的临时 `.mp4` 推理片段路径 |
| `prompt` | string | Agent 动态构建的完整 prompt |

**输出**

- 类型：`dict`
- 内容：符合第 2 节模型输出 JSON Schema 的结构化对象（即模型输出 JSON）。`InferenceClient` 内部可调用 `ResultParser.parse` 将原始文本响应解析为 JSON，但对外接口统一返回解析后的 dict。
- 注意：`InferenceClient.infer` 不负责对结果做 `boundary_status`、`round_confidence_level`、`inferred_time_range` 等封装；这些由 Agent 侧的 `_execute_sample_and_infer` 按第 5.3 节 `SampleAndInferResult` 结构装配。

### 5.5 `ResultParser.parse`

**签名**

```python
def parse(
    raw_text: str,
    expected_schema: dict | None = None
) -> dict | None:
```

**输入**

| 参数 | 类型 | 说明 |
|---|---|---|
| `raw_text` | string | 模型原始文本响应 |
| `expected_schema` | dict / `None` | 期望模型输出的 JSON schema；为 `None` 时默认使用第 2 节 schema |

**输出**

- 解析成功：返回符合 `expected_schema` 的结构化 JSON 对象（见第 2 节）。
- 解析失败：返回 `null`，Agent 侧需按错误处理流程重试或终止。

---

## 6. Prompt 契约

### 6.1 统一 System Prompt 模板（训练与推理共用）

微调模型（MiniCPM-V）在**训练与推理阶段使用同一套 System Prompt 模板**。Agent 不负责动态修改 system prompt，仅在此基础上追加动态构建的 user prompt。

```text
你是一个材料拉伸试验视频分析助手。你的任务是分析给定的视频片段，判断试样是否发生断裂。

如果存在断裂，请回答：
1. 断裂发生在哪两帧之间（用帧索引表示，如 [17, 18]）
2. 断裂模式（若存在断裂，has_fracture=true，type 只能从 7 个断裂类中选：韧性断裂；脆性断裂；界面脱粘；齐根断裂；爆炸性断裂；半脆半韧断裂；界面脱粘、齐根断裂。其中组合标签 `界面脱粘、齐根断裂` 作为独立类别，与单独的 `界面脱粘`、`齐根断裂` 不同。若不存在断裂，has_fracture=false，type 只能从 3 个非断裂/异常类中选：未断裂；未夹紧；视频异常）
3. 断裂位置是否在标距内（inside_gauge / outside_gauge / N/A）
4. 你对判断的置信度（confidence，0.0 ~ 1.0 的浮点数）

如果判断不存在断裂，has_fracture 为 false，fracture_between 为 null，type 只能取 `未断裂` / `未夹紧` / `视频异常` 三者之一（不允许输出 `none`；根据当前片段内容判断取值），location 填 "N/A"，confidence 仍需给出（表示你对"无断裂"判断的置信度）。

输出必须为严格合法的 JSON 格式，不要包含任何其他解释文字。confidence 字段为必填项。
输出 Schema：{"has_fracture": bool, "fracture_between": [int, int]或null, "type": str, "location": str, "confidence": float}
```

#### 训练样本格式（权威示例）

训练样本使用标准 `messages` 格式（`role` / `content`），`system` 角色的内容必须为上文统一模板，`user` 角色由 Agent 动态 prompt 逻辑生成，`assistant` 角色为符合第 2 节 Schema 的 JSON 字符串。

为与 LLaMA-Factory 视频输入格式保持一致，`videos` 字段为训练子视频路径列表：每个元素对应 `content` 中的一个 `<video>` 占位符。本方案每条训练样本通常只包含一个 `.mp4` 训练子视频路径。

```json
{
  "id": "video_0001_focus_3s_50pct",
  "videos": [
    "data/02_subvideos/video_0001_focus_3s_50pct.mp4"
  ],
  "messages": [
    {
      "role": "system",
      "content": "你是一个材料拉伸试验视频分析助手。你的任务是分析给定的视频片段，判断试样是否发生断裂。\n\n如果存在断裂，请回答：\n1. 断裂发生在哪两帧之间（用帧索引表示，如 [17, 18]）\n2. 断裂模式（若存在断裂，has_fracture=true，type 只能从 7 个断裂类中选：韧性断裂；脆性断裂；界面脱粘；齐根断裂；爆炸性断裂；半脆半韧断裂；界面脱粘、齐根断裂。其中组合标签 `界面脱粘、齐根断裂` 作为独立类别，与单独的 `界面脱粘`、`齐根断裂` 不同。若不存在断裂，has_fracture=false，type 只能从 3 个非断裂/异常类中选：未断裂；未夹紧；视频异常）\n3. 断裂位置是否在标距内（inside_gauge / outside_gauge / N/A）\n4. 你对判断的置信度（confidence，0.0 ~ 1.0 的浮点数）\n\n如果判断不存在断裂，has_fracture 为 false，fracture_between 为 null，type 只能取 `未断裂` / `未夹紧` / `视频异常` 三者之一（不允许输出 `none`；根据当前片段内容判断取值），location 填 \"N/A\"，confidence 仍需给出（表示你对\"无断裂\"判断的置信度）。\n\n输出必须为严格合法的 JSON 格式，不要包含任何其他解释文字。confidence 字段为必填项。\n输出 Schema：{\"has_fracture\": bool, \"fracture_between\": [int, int]或null, \"type\": str, \"location\": str, \"confidence\": float}"
    },
    {
      "role": "user",
      "content": "<video>\n请分析这段拉伸试验视频，判断是否存在断裂。当前区间为 [143.9, 146.9] 秒，按 video_fps=8.0 与 video_maxlen=36 实际采样 24 帧。"
    },
    {
      "role": "assistant",
      "content": "{\"has_fracture\": true, \"fracture_between\": [17, 18], \"type\": \"韧性断裂\", \"location\": \"inside_gauge\", \"confidence\": 1.0}"
    }
  ]
}
```

> - 本文档以 `messages` + `role` / `content` 为权威格式；若其他文档或旧配置中出现 `conversations` / `from` / `value` 混用，应转换为本格式。
> - `user` 角色的 `content` 中必须包含 `<video>` 占位符，与 `videos` 列表中的子视频路径一一对应。
> - 具体训练配置细节（如 LoRA 参数、学习率、`dataset_info.json` 注册字段映射）保留在 [`docs/model_finetuning_design.md`](./model_finetuning_design.md) 中。

### 6.2 Agent 动态构建 prompt 的必填要素

Agent 在生成 `sample_and_infer` 的 `parameters.prompt` 时，必须包含以下要素：

1. **角色设定**：明确模型的身份（如"你是一个材料拉伸试验视频分析助手"）。
2. **任务描述**：当前需要分析什么（如"请判断这段视频是否包含断裂"）。
3. **视觉占位符**：user prompt 中必须包含 `<video>` 占位符，与工具执行层传入模型的 `.mp4` 视频片段一一对应（训练样本格式见第 6.1 节）。
4. **输入说明**：这是一段拉伸试验视频的哪个区间（时间范围、`video_fps`、`video_maxlen`、实际采样帧数等）。
5. **输出格式要求**：严格合法的 JSON schema，包含 `has_fracture`、`fracture_between`、`type`、`location`、`confidence` 字段。
6. **可选上下文提示**：基于历史结果的提示（如"前几轮分析显示断裂可能发生在 150~160 秒区间，请重点关注"）。

Agent 可根据当前迭代阶段调整 prompt 的措辞和重点，例如初期侧重"有无断裂"，后期侧重"精确边界"。

### 6.3 Agent System Prompt 完整模板

> 本节给出 Meta-Agent 迭代控制器的 System Prompt 完整模板（中文版）。该模板在 Agent 初始化时由代码层写入 `messages` 的 `system` 角色，Agent Loop 运行期间**不得修改**。Agent 仅在此基础上动态构建每轮的 user prompt。

```text
你是一名"材料拉伸试验视频分析协调者"，负责通过多轮工具调用定位材料拉伸试验视频中试样是否断裂、断裂发生在哪两帧之间、断裂模式、断裂位置，并给出综合置信度。

## 任务目标
1. 通过调用 `sample_and_infer` 工具，在指定时间区间内采样视频帧并调用微调模型，判断该区间是否包含断裂以及断裂发生在哪两帧之间。
2. 根据模型返回的 `has_fracture`、`fracture_between`、`type`、`location` 和 `confidence`，逐步缩小候选时间区间。
3. 当满足以下任一条件时，调用 `terminate` 工具输出最终结果并结束迭代：
   - 已确认当前视频无断裂或属于异常样本；
   - 候选区间宽度 ≤ `tolerance_seconds`；
   - 已达到最大迭代轮数 `max_rounds`。

## 可用工具
你必须也只允许通过 function calling 调用以下两个工具：

- `sample_and_infer`：在指定时间区间内采样视频帧，调用微调模型（MiniCPM-V）进行推理。
  - `sample_range`：[start_seconds, end_seconds]，必须在 [0, duration] 范围内。
  - `num_frames`：采样帧数上限，默认 36，语义等同 `video_maxlen`，须与训练配置一致。
  - `video_fps`：视频采样帧率，默认 8.0，须与训练配置一致；实际采样帧数由区间时长、`video_fps` 与 `num_frames` 上限共同决定。
  - `sampling_strategy`：`uniform`（均匀采样）或 `adaptive`（在关注区间加密采样）。首版默认仅要求 `uniform`；`adaptive` 只有在工具执行层确认支持时才可使用。
  - `prompt`：发送给微调模型的完整 user prompt，须符合接口文档 Prompt 契约。
  - `expected_schema`：期望模型输出的 JSON schema。

- `terminate`：终止迭代，返回最终结果。
  - 参数包括 `has_fracture`、`time_range`、`time_estimate`、`frame_range`、`type`、`location`、`confidence`、`confidence_level`。
  - 详细 schema 与取值规则见接口文档第 4 节。

## 决策规则
- 初始候选区间为 `[0, duration]`（全视频）。
- 每轮根据当前候选区间、历史迭代记录和模型返回结果，决定下一步采样区间或是否终止。
- 如果模型返回 `has_fracture = true`，使用换算后的 `inferred_time_range` 更新候选区间，并继续向断裂点聚焦。
- 如果模型在**初始全范围采样或已扩展回全范围**后返回 `has_fracture = false` 且置信度高，可判断当前视频无断裂或异常，调用 `terminate`；若在聚焦子区间返回 `has_fracture = false`，说明候选可能错过断裂点，必须扩大采样范围继续验证，禁止直接判定无断裂。
- 可动态调整 user prompt 的措辞和重点，例如初期侧重"是否存在断裂"，后期侧重"精确边界"。
- 仅当工具执行层明确支持时，才可要求使用 `adaptive` 采样策略；否则使用 `uniform`。
- 当确认无断裂、区间宽度 ≤ `tolerance_seconds` 或达到 `max_rounds` 时，必须调用 `terminate`。
- 所有 `sample_range` 必须在视频总时长 `[0, duration]` 范围内，禁止越界。

## 最终置信度判断
调用 `terminate` 时，综合以下因素给出 0~1 的综合 `confidence`，并按等级划分：
- 多轮模型自报 `confidence` 的平均值与趋势；
- `type` 与 `location` 在多轮中的一致性；
- 候选区间是否收敛、宽度是否 ≤ `tolerance_seconds`。
置信度等级：`高`（0.90~1.00）、`中`（0.70~0.89）、`低`（0.50~0.69）、`不可信`（0.00~0.49）。

## 输出要求
- 必须通过 `tool_calls` 输出你的决策，禁止直接以文本形式回答。
- 每次调用只能选择一个工具；如需继续分析，调用 `sample_and_infer`；如需结束，调用 `terminate`。
- 不要编造模型输出，所有推理必须基于历史迭代记录。
```

#### 使用说明

1. 代码层在初始化 Agent 时，将上述模板写入 `messages[0]` 的 `role = "system"` 内容。
2. Agent Loop 不得修改 system prompt；每轮 user prompt 由代码层根据视频元信息、当前状态和历史记录动态追加。
3. `sample_and_infer` 的 `prompt` 参数须符合第 6.2 节"Agent 动态构建 prompt 的必填要素"，并与训练数据构造器生成的 user prompt 分布保持一致。

---

## 7. 最终输出 Schema

Agent 返回给下游的完整 JSON 结构如下。

### 7.1 Schema 定义

```json
{
  "video_id": "video_0001",
  "has_fracture": true,
  "time_range": [242.86, 257.14],
  "time_estimate": 250.0,
  "frame_range": [7286, 7714],
  "type": "韧性断裂",
  "location": "inside_gauge",
  "confidence": 0.79,
  "confidence_level": "中",
  "rounds": 5,
  "history": [
    {
      "round": 0,
      "model": "MiniCPM-V-4.6-finetuned",
      "reasoning": "第一轮对全范围进行采样，以确认是否存在断裂。",
      "tool_calls": [
        {
          "name": "sample_and_infer",
          "arguments": {
            "sample_range": [0.0, 500.0],
            "num_frames": 36,
            "video_fps": 8.0,
            "sampling_strategy": "uniform",
            "prompt": "...",
            "expected_schema": {...}
          }
        }
      ],
      "result": {
        "model_output": {
          "has_fracture": true,
          "fracture_between": [17, 18],
          "type": "韧性断裂",
          "location": "inside_gauge",
          "confidence": 0.92
        },
        "frames": [
          {
            "input_index": 0,
            "original_frame": 0,
            "timestamp": 0.0,
            "frame_path": "data/03_frames/video_0001/frame_0000.jpg"
          }
        ],
        "model_video_path": "data/runtime/agent_clips/video_0001_round0.mp4",
        "sample_range": [0.0, 500.0],
        "video_fps": 8.0,
        "video_maxlen": 36,
        "num_sample_frames": 36,
        "sampling_strategy": "uniform",
        "inferred_time_range": [242.86, 257.14],
        "inferred_frame_range": [7286, 7714],
        "boundary_status": "none",
        "parse_error": null,
        "round_confidence_level": "高"
      }
    }
  ]
}
```

### 7.2 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `video_id` | string | 视频唯一标识 |
| `has_fracture` | boolean | 是否存在断裂 |
| `time_range` | `[float, float]` / `null` | 最终断裂时间区间（秒） |
| `time_estimate` | float / `null` | 断裂时间估计值（秒），通常为区间中点 |
| `frame_range` | `[int, int]` / `null` | 最终断裂帧区间 |
| `type` | string | 断裂模式或异常类别 |
| `location` | string | 标距内位置判断 |
| `confidence` | float | 最终综合置信度，`[0.0, 1.0]` |
| `confidence_level` | string | 置信度等级：`高` / `中` / `低` / `不可信` |
| `rounds` | int | 实际迭代轮数 |
| `history` | list[dict] | 每轮迭代原始记录，结构与 `agent_iteration_design.md` 中 `_log_round` 输出一致：包含 `round`、`model`、`reasoning`、`tool_calls`，并将完整的 `SampleAndInferResult` 嵌套在 `result` 字段下 |

### 7.3 `has_fracture = false` 时的字段规则

同第 4.3 节：

- `time_range` / `time_estimate` / `frame_range`：统一填 `null`。
- `type`：仅允许 `未断裂` / `未夹紧` / `视频异常` 三者之一，**不允许输出 `none`**。训练标签由构造器决定：人工负片段默认 `未断裂`，真实无断裂/异常样本保留其标注。推理最终输出由模型多轮预测投票/置信度聚合决定：若模型在多轮中明确预测 `未夹紧` 或 `视频异常` 且置信度可接受，则采用该预测；否则默认 `未断裂`，并将 `confidence_level` 降至 `中` 或 `低`（至少不为 `高`）。
- `location`：必须为 `"N/A"`。

---

## 8. 索引/时间换算规则

### 8.1 符号约定

设某轮 `sample_and_infer` 调用参数为：

- `sample_range = [t_start, t_end]`（秒）
- `video_fps = 8.0`（默认值，可配置）
- `video_maxlen = num_frames = 36`（默认上限，可配置）
- `N = min(total_frames_in_clip, video_maxlen, max(1, floor((t_end - t_start) * video_fps)))`，表示模型实际看到的采样帧数
- `fps` 为原始视频帧率
- `total_frames` 为原始视频总帧数
- `strategy = "uniform"`
- `event_frame_original` 为 CSV 标注的断裂帧在原始视频中的全局帧号，采用 **0-based 索引**，有效范围为 `[0, total_frames - 1]`。

> 当 `N = 1` 时，退化情形由实现自行定义；本契约默认 `N >= 2`。

### 8.2 采样帧索引换算

VideoSampler 返回的帧序列第 `k` 个元素（`0 <= k < N`）：

```text
timestamp[k] = t_start + k * (t_end - t_start) / (N - 1)
original_frame[k] = clamp(round(timestamp[k] * fps), 0, total_frames - 1)
```

其中 `clamp(x, a, b) = min(max(x, a), b)`，保证换算后的帧号不超出原始视频范围。`original_frame[k]` 表示该采样帧在原始视频中的全局 0-based 帧号。

**`uniform` 策略**：上述公式即为闭式定义。

**`adaptive` 策略**：采样点由算法根据关注区间动态决定，无统一闭式公式。由于模型视觉输入是 `.mp4`，`adaptive` 只有在 `VideoClipBuilder` 能生成与 `frames` 序列完全一致的临时视频时才成立。`Agent` 与 `VideoSampler` 都必须以工具执行层返回的 `frames[].timestamp` 与 `frames[].original_frame` 为准，**禁止**用 `uniform` 公式反推帧号；若工具执行层不支持该能力，必须拒绝 `adaptive` 或降级为 `uniform`。

### 8.3 `fracture_between` 查找规则

给定真实断裂帧 `event_frame_original` 与采样帧的 `original_frame[0..N-1]`，按以下规则确定模型应输出的 `fracture_between = [i, i+1]`：

1. **正常区间**：找到唯一 `i`（`0 <= i < N - 1`）使得：
   ```text
   original_frame[i] <= event_frame_original < original_frame[i+1]
   ```
   此时 `fracture_between = [i, i+1]`，其中 `j = i + 1`。

2. **越界前段**：若 `event_frame_original < original_frame[0]`，取 `fracture_between = [0, 0]`，表示断裂发生在第 0 帧之前或恰好在第 0 帧。评估时将该情况单独标记为"前段越界"；工具执行层对应的 `SampleAndInferResult.boundary_status = "left_sentinel"`。

3. **越界末段**：若 `event_frame_original >= original_frame[N-1]`，取 `fracture_between = [N-1, N-1]`，表示断裂发生在最后一采样帧之后或恰好在最后一采样帧。评估时将该情况单独标记为"末段越界"；工具执行层对应的 `SampleAndInferResult.boundary_status = "right_sentinel"`。

4. **恰好命中采样帧**：若 `event_frame_original == original_frame[i]` 且 `i > 0`，取左侧区间 `fracture_between = [i-1, i]`，确保区间表示唯一；若 `i = 0`，按规则 2 取 `[0, 0]`。

### 8.4 `fracture_between` → `time_range` / `frame_range`

若模型输出 `fracture_between = [i, j]`：

- 正常情况：`j = i + 1`；
- 前段越界：`[i, j] = [0, 0]`，此时 `frames[i]` 与 `frames[j]` 为同一采样帧；
- 末段越界：`[i, j] = [N-1, N-1]`，此时 `frames[i]` 与 `frames[j]` 为同一采样帧。

则：

```text
time_range = [frames[i].timestamp, frames[j].timestamp]
frame_range = [frames[i].original_frame, frames[j].original_frame]
```

**禁止**重新用 `round(timestamp * fps)` 换算 `frame_range`，必须直接使用 `VideoSampler` 返回的 `frames[].original_frame`，避免与采样器结果出现 ±1 帧偏差。

**边界哨兵 `boundary_status`**：当 `fracture_between = [0, 0]` 或 `[N-1, N-1]` 时，按上述规则得到的 `time_range` 与 `frame_range` 为同一采样帧对应的零宽区间（`i == j`）。该区间仅为提示 Agent 向对应边界扩展的临时值，**不得单独触发收敛终止**；Agent 必须进入边界扩展分支，扩大采样区间后重新验证。工具执行层应在 `SampleAndInferResult.boundary_status` 中明确标记 `left_sentinel` / `right_sentinel`。

### 8.5 真实时间 `t_gt` 回退规则

评估时使用的真实断裂时间 `t_gt` 按以下优先级获取：

1. 优先使用 CSV 的 `event_time`（秒）。
2. 当 `event_time` 不可解析时，回退到 `event_frame_original / fps`。
3. 若两者均不可用，则该样本不参与时间相关指标计算。

### 8.6 示例

以默认配置 `video_fps = 8.0`、`video_maxlen = 36` 在区间 `[0, 500]s` 上使用 `uniform` 策略为例，由于区间较长，实际采样帧数被上限截断为 `N = 36`：

- 采样帧间隔：`500 / (36 - 1) ≈ 14.2857s`
- `fracture_between = [17, 18]`
- `timestamp[17] = 17 * 14.2857 ≈ 242.86s`
- `timestamp[18] = 18 * 14.2857 ≈ 257.14s`
- 换算后区间：`[242.86, 257.14]s`

### 8.7 `time_estimate` 计算

`time_estimate` 推荐取最终 `time_range` 的中点：

```text
time_estimate = (time_range[0] + time_range[1]) / 2
```

Agent 实现也可根据多轮结果加权融合，但输出时必须同时提供 `time_range` 与 `time_estimate`。

---

## 9. 版本与变更记录

| 版本 | 日期 | 变更说明 | 作者 |
|---|---|---|---|
| v1.0 | 2026-06-14 | 从旧版单一设计文档拆分，作为 `model_finetuning_design.md` 与 `agent_iteration_design.md` 之间的单一接口契约 | 项目团队 |
| v1.1 | 2026-06-14 | 修复阻塞级接口矛盾：引入 `source_type`/`source_location` 训练 metadata；Tool 执行层保留 `frames` 作为索引/时间映射；`terminate` schema 形式化 nullable 与数组长度约束；补充索引/时间换算边界规则与 `t_gt` 回退；统一训练与推理 System Prompt 模板并给出 `messages` 权威示例 | 项目团队 |
| v1.2 | 2026-06-15 | 修复审查阻塞/高风险问题：训练样本 `videos` 使用 `.mp4` 子视频路径并要求 `content` 含 `<video>`；明确 `fracture_between` 边界哨兵语义；统一采样帧号换算公式；补充 `adaptive` 采样约束；明确 macro-F1 只在 7 个断裂类上计算 | 项目团队 |
| v1.3 | 2026-06-15 | 修复审查阻塞/高风险问题：新增 `SampleAndInferResult` 权威结构；推理阶段禁止读取评估 CSV 原值，训练标签由构造器决定；`boundary_status` 显式化边界哨兵；统一 `round_confidence_level` 四级分层；`confidence_level` 仅用于 `terminate` 最终输出 | 项目团队 |
| v1.4 | 2026-06-15 | 明确 `video_fps=8.0` 为可配置超参数；统一 `num_frames` 为 `video_maxlen` 上限而非固定实际帧数；区分模型微调训练子视频与 Agent 临时推理片段 | 项目团队 |

---

## 10. 术语表

| 术语 | 说明 |
|---|---|
| **帧区间迭代定位** | 不直接预测断裂秒数，而是通过多轮"断裂在哪两帧之间"的问答逐步缩小时间范围 |
| **训练子视频** | 从原始视频中截取并持久化到 `data/02_subvideos/*.mp4` 的训练片段，只用于模型微调训练 |
| **临时推理片段** | Agent 推理时基于原始视频和当前 `sample_range` 动态生成的 `.mp4` 片段，只服务当前轮模型调用 |
| **局部聚焦** | 围绕断裂时刻裁剪的短片段，断裂点位于子视频内的特定位置 |
| **负样本** | 不包含断裂的视频片段，用于训练模型识别"无断裂"情况 |
| **event_frame_original** | 断裂帧在原始视频中的全局帧号 |
| **fracture_between** | 模型输出：断裂发生在第 i 帧和第 i+1 帧之间，格式为 `[i, i+1]` |

---

## 附录 A：完整数据流图

```
原始视频 (data/01_videos/*.mp4)
    + 标注 CSV (data/02_annotations/all_videos_tag.csv)
    |
    v
┌─────────────────────────────────────┐
│  模型微调侧：元数据管理               │
│  - ffprobe / cv2 提取 fps/帧数/时长   │
│  - 读取 CSV 的 event_frame_original    │
│  - 读取 location / material_type / resolution │
│  - 异常标记                            │
└─────────────────────────────────────┘
    |
    v  data/metadata/video_meta.json
┌─────────────────────────────────────┐
│  模型微调侧：划分 + 子视频生成 + 样本构建│
│  - 原始视频 3-fold 划分                │
│  - 生成 7 种类型子视频                 │
│  - ffmpeg 裁剪                        │
│  - 帧采样 + 标签计算                    │
│  - LLaMA-Factory 格式转换              │
└─────────────────────────────────────┘
    |
    +--> data/02_subvideos/*.mp4  (模型微调训练主产物)
    +--> data/03_frames/{video_id}_{crop_type}_{idx}/frame_*.jpg  (可选缓存)
    +--> data/04_merged/stratified_3_fold_*_{train,val}.json  (旧基线，冻结保留)
    +--> data/04_new_merged/fold_*_{train,val}.json
    +--> data/04_new_merged/test.json
    |
    v
┌─────────────────────────────────────┐
│  模型微调侧：Prompt 规范 + 训练配置    │
│  - Prompt 设计规范（Agent 动态构建）    │
│  - 微调模型 System Prompt 模板          │
│  - LLaMA-Factory YAML 配置            │
│  - dataset_info.json 注册             │
└─────────────────────────────────────┘
    |
    v
┌─────────────────────────────────────┐
│  模型微调侧：模型微调训练              │
│  - 3-fold 独立训练                    │
│  - 输出 checkpoints                   │
└─────────────────────────────────────┘
    |
    v  finetune/saves/minicpmv4_6/lora/new_sft_fold*/
┌─────────────────────────────────────────────────────────────┐
│  Agent 迭代侧：Meta-Agent 驱动的迭代推理框架                  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Agent Loop（迭代控制器）                              │   │
│  │ - LLM 后端：DashScope（百炼）/ Ollama（本地），可配置 │   │
│  │ - 协议：Native Function Calling（tool_calls）        │   │
│  │ 输入：视频元信息 + 历史迭代记录（messages）            │   │
│  │ 输出：tool_calls → 执行 Tool → 结果回传               │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Tool 执行层（通用代码）                               │   │
│  │ - VideoSampler：按 tool_args 抽帧                    │   │
│  │ - VideoClipBuilder：生成本轮临时推理 .mp4 片段       │   │
│  │ - InferenceClient：调用微调模型（MiniCPM-V）          │   │
│  │ - ResultParser：按 expected_schema 解析              │   │
│  └──────────────────────┬──────────────────────-────────┘   │
│                         │                                   │
│                         └──→ 结果追加到历史记录 → 回到 Agent Loop│
│                                                             │
│  终止时：Agent 输出 final_output（含综合 confidence）        │
└─────────────────────────────────────────────────────────────┘
    |
    v  预测结果 JSON
┌─────────────────────────────────────┐
│  Agent 迭代侧：评估体系               │
│  - 区间命中率 / within_1s/3s/5s       │
│  - type F1 / location 准确率          │
│  - 异常样本分析 / 置信度-误差相关性     │
│  - 与旧方案对比报告                    │
└─────────────────────────────────────┘
    |
    v  评估报告
```

> **不变量3 / 与旧方案对比口径**：与旧方案对比时，口径强制为：旧方案必须复用新方案的 video-level test split 重新生成或过滤测试输入；新旧对比只能在相同的 `video_id` 集合上进行，不允许旧方案使用自己的 test split 或全量数据。若旧 baseline 当前无独立 test 集，则需通过新方案的 test split 过滤其输出后计算指标。详见 `docs/agent_iteration_design.md` 第 4.3 节。

> 更详细的模型侧数据流见 [`docs/model_finetuning_design.md`](./model_finetuning_design.md) 附录 A。  
> 更详细的 Agent 侧数据流见 [`docs/agent_iteration_design.md`](./agent_iteration_design.md) 附录 A。
