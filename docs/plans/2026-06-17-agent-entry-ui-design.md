# Agent 统一入口与本地 UI 设计

> 日期：2026-06-17
> 状态：Draft for review
> 范围：Agent 推理入口、本地可视化工作台、单/多视频执行封装

## 1. 目标与范围

当前 `agent/` 已具备 `IterativeAgent` 状态机、Native Function Calling LLM 后端、采样、推理客户端和结构化输出 schema，但还缺少一个统一入口。该入口需要同时服务两类使用方式：

1. 本地交互使用：研究者能直观看到单个或多个视频的 Agent 推理过程。
2. 自动化调用：脚本、测试和后续评估流程能复用同一套执行逻辑。

本设计选择 **本地 Streamlit UI 作为第一用户入口，`agent.runner` 作为共享执行内核，CLI 作为自动化辅助入口**。

## 2. 非目标

- 不做远程多人访问、账号权限、任务数据库或长期任务队列。
- 不引入 MCP；Agent 仍使用当前 Native Function Calling 方案。
- 不暴露或依赖模型内部隐藏推理链。
- 不在第一版实现复杂视频标注、人工修正闭环或训练数据回写。
- 不替换现有 `IterativeAgent` 状态机、schema、prompt 和推理客户端契约。

## 3. 约束与假设

- 第一版只要求在本机研究环境运行。
- 原始视频仍来自本地路径，通常位于 `data/01_videos/`，不会提交到 Git。
- Agent 动态生成的临时 clip、事件日志和结果文件写入 `data/runtime/`。
- 微调模型推理服务由用户提前启动；入口只读取配置并调用已有 `InferenceClient`。
- Agent LLM 后端继续通过 `agent/config.yaml` 选择远程或本地 OpenAI-compatible endpoint。
- 最终结果必须符合 `FinalOutput` schema，过程事件必须能追溯到每轮工具调用和状态变化。

## 4. 方案对比

### 4.1 Streamlit 本地工作台 + Runner 内核（推荐）

优点：

- 能最快形成可用界面，适合本地视频预览、表格、JSON 和进度展示。
- 与当前研究型项目匹配，不需要提前设计服务部署、鉴权和数据库。
- 可通过事件回调实时展示 Agent 工具调用、模型输出和候选区间变化。
- Runner 内核可被 CLI 和未来 API 复用，避免 UI 直接绑定 `IterativeAgent` 细节。

缺点：

- 不适合多人并发访问。
- 长任务、任务恢复和远程部署能力有限。

### 4.2 FastAPI + 前端页面

优点：

- 更适合未来服务器部署、多人访问和外部系统集成。
- 前后端边界清晰，事件流可通过 SSE 或 WebSocket 暴露。

缺点：

- 第一版成本偏高，需要处理服务生命周期、文件上传、并发任务和前端状态管理。
- 当前项目尚未证明入口交互形态，过早服务化会扩大实现范围。

### 4.3 CLI-only

优点：

- 实现最简单，最适合批量评估和自动化测试。
- 与现有 pipeline 脚本风格一致。

缺点：

- 不满足“直观简洁地看到 Agent 过程”的需求。
- 工具调用、候选区间收缩和模型输出很难被非开发视角快速理解。

## 5. 推荐架构

第一版采用三层结构：

```text
ui/agent_app.py
    |
    v
agent/runner.py
    |
    v
agent/iterative_agent.py
    |
    +--> agent.llm.AgentLLMFactory
    +--> agent.inference.create_inference_client
    +--> agent.sampling.VideoSampler / VideoClipBuilder
```

### 5.1 `agent.runner`

`agent.runner` 是统一执行内核，负责把文件路径、配置和事件回调转换为 `IterativeAgent` 可执行对象。

建议提供以下 API：

```python
def run_one(
    video_path: str,
    config_path: str = "agent/config.yaml",
    event_callback: Callable[[dict], None] | None = None,
) -> dict:
    ...


def run_batch(
    video_paths: list[str],
    config_path: str = "agent/config.yaml",
    event_callback: Callable[[dict], None] | None = None,
) -> list[dict]:
    ...
```

职责：

- 加载 YAML 配置。
- 构造最小 `video_meta`，包括 `video_id`、`video_path`、`duration`。
- 创建 Agent LLM client 和微调模型 `InferenceClient`。
- 调用 `IterativeAgent.run()`。
- 将最终结果写入可选输出路径或返回给调用方。
- 将运行过程中的事件转发给 UI / CLI。

### 5.2 `IterativeAgent` 事件流

为支持 UI 实时展示，`IterativeAgent` 应支持可选事件回调。事件是代码层可审计事实，不是模型隐藏推理链。

推荐事件类型：

| 事件 | 触发时机 | 关键字段 |
|---|---|---|
| `video_started` | 单个视频开始 | `video_id`, `video_path`, `duration` |
| `round_started` | 每轮 LLM 决策前 | `video_id`, `round`, `state`, `candidate` |
| `llm_tool_call` | LLM 输出工具调用后 | `round`, `tool_name`, `tool_args` |
| `sample_and_infer_started` | 执行采样推理前 | `round`, `sample_range`, `num_frames`, `video_fps` |
| `sample_and_infer_finished` | 微调模型返回后 | `round`, `model_output`, `inferred_time_range`, `boundary_status` |
| `state_updated` | 状态机转移后 | `round`, `previous_state`, `state`, `previous_candidate`, `candidate` |
| `termination_requested` | LLM 请求 `terminate` 后 | `round`, `allowed`, `reason`, `tool_args` |
| `video_finished` | 最终输出生成后 | `video_id`, `result` |
| `video_failed` | 单视频失败 | `video_id`, `error`, `stage` |

事件字段应保持 JSON 可序列化，便于 UI 展示、CLI 写 JSONL 和后续测试断言。

### 5.3 Streamlit UI

第一版入口命令：

```bash
streamlit run ui/agent_app.py
```

页面布局：

- 侧边栏：
  - 选择单视频或多视频模式。
  - 输入或选择视频路径。
  - 输入配置文件路径，默认 `agent/config.yaml`。
  - 运行按钮。
- 主区域：
  - 单视频模式显示视频预览、最终结果摘要、Agent 事件时间线、每轮工具调用参数、模型 JSON 输出和候选区间变化。
  - 多视频模式显示批处理进度、结果表格和当前选中视频的详细事件时间线。
  - 提供 JSON / JSONL / CSV 结果导出。

UI 展示原则：

- 展示工具调用、工具参数、模型结构化输出、状态转移和最终聚合结果。
- 不展示模型内部隐藏推理链。
- 对每轮过程生成简短说明，例如：“第 2 轮将候选区间从 `[0.00, 100.00]` 收缩到 `[48.57, 51.43]`。”
- 原始 JSON 保留在可展开区域，默认展示摘要。

### 5.4 CLI 辅助入口

CLI 主要用于自动化、测试和无界面环境。建议入口：

```bash
python3 -m agent.run --video data/01_videos/video_0001.mp4
python3 -m agent.run --input-list data/runtime/video_list.txt --output data/runtime/results.jsonl
```

CLI 与 UI 必须调用同一个 `agent.runner`，不能绕过 Runner 直接拼装 `IterativeAgent`。

## 6. 数据流

### 6.1 单视频

```text
用户选择 video_path
  -> UI 调用 runner.run_one(...)
  -> runner 加载配置并构造 video_meta
  -> IterativeAgent 多轮运行
  -> 每轮通过 event_callback 推送事件
  -> UI 增量刷新事件时间线
  -> runner 返回 FinalOutput dict
  -> UI 展示摘要并支持导出
```

### 6.2 多视频

```text
用户选择多个 video_path
  -> UI 调用 runner.run_batch(...)
  -> runner 顺序执行每个视频
  -> 单视频失败记录 video_failed，不中断整个批次
  -> UI 展示批处理进度和每个视频结果
  -> 完成后导出 JSONL / CSV
```

第一版多视频采用顺序执行，避免 GPU/模型服务并发争用和日志交错。并发执行可作为后续优化。

## 7. 失败处理与边界情况

- 配置文件不存在或 YAML 解析失败：入口直接报错，UI 显示配置错误。
- 视频文件不存在：该视频标记为失败，不进入 Agent。
- 无法读取视频时长：该视频标记为失败，错误阶段为 `metadata`。
- Agent LLM 后端配置缺失：运行前失败，提示缺少 `LLM_API_KEY`、`base_url` 或模型名。
- 微调模型服务不可用：该视频标记为失败，错误阶段为 `inference`。
- 单轮模型输出解析失败：沿用 `IterativeAgent` 现有 parse error 兜底逻辑，并通过事件展示。
- 多视频中单个视频失败：继续后续视频，最终结果中包含失败记录。
- 用户中断运行：第一版可停止 UI 当前运行，不要求恢复未完成批次。

## 8. 输出格式

单视频最终输出使用 `FinalOutput` dict。

多视频导出建议：

- JSONL：每行一个视频结果，成功结果为 `FinalOutput`，失败结果包含 `video_id`、`video_path`、`ok=false`、`error`、`stage`。
- CSV：只导出摘要字段，包括 `video_id`、`has_fracture`、`time_estimate`、`time_range`、`type`、`location`、`confidence`、`confidence_level`、`rounds`、`ok`、`error`。

事件日志可选写入：

```text
data/runtime/events/<run_id>/<video_id>.jsonl
data/runtime/results/<run_id>.jsonl
```

## 9. 测试策略

### 9.1 单元测试

- `agent.runner` 能用 mock LLM、mock sampler、mock inference client 跑通单视频。
- `run_batch` 中某个视频失败时不影响后续视频。
- 事件回调顺序至少包含 `video_started`、`round_started`、`llm_tool_call`、`video_finished`。
- 失败路径能产生 `video_failed`，且字段 JSON 可序列化。

### 9.2 Agent 回归测试

继续覆盖现有重点：

```bash
python3 -m pytest tests/test_iterative_agent.py tests/test_sampling*.py tests/test_parser.py tests/test_inference.py -q
```

### 9.3 UI 冒烟测试

- 使用 mock 模式启动 Streamlit，确认页面可加载。
- 单视频模式能展示视频路径、事件时间线和最终结果。
- 多视频模式能展示进度表和导出结果。

第一版 UI 测试可以先以手动冒烟为主；核心逻辑必须放在 `agent.runner` 和 `IterativeAgent`，由 pytest 覆盖。

## 10. 实施分解建议

1. 增加 `IterativeAgent` 可选事件回调，不改变现有 `run()` 返回值。
2. 新增 `agent/runner.py`，实现配置加载、视频 metadata 构造、单/多视频执行和失败封装。
3. 新增 `agent/run.py` CLI，调用 Runner。
4. 新增 `ui/agent_app.py` Streamlit 页面，先支持本地路径选择和事件展示。
5. 补充 README 中的入口命令和使用说明。
6. 增加 Runner 与 CLI 的测试；UI 做本地冒烟验证。

## 11. 审查结论

本设计将第一版范围限定为本地可运行的 Agent 工作台，避免过早引入远程服务、数据库和多人协作能力。核心逻辑集中在 `agent.runner` 和现有 `IterativeAgent`，UI 和 CLI 都复用同一执行内核。事件流只记录可审计过程，满足直观展示需求，同时不依赖模型内部隐藏推理链。
