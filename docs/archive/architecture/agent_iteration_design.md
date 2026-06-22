# Agent 迭代侧设计文档

> 项目:mVllm-frame-interval-agent
> 日期:2026-06-11
> 状态:已过期
> 替代文档:[`docs/PROJECT_PLAN.md`](../../PROJECT_PLAN.md) v2

---

## 0. 文档地位与适用范围

本文档是 `mVllm-frame-interval-agent` 项目 **Agent 迭代侧**的设计文档,定义迭代控制器(Meta-Agent)的推理框架、Agent LLM 后端架构、评估体系及 Agent 侧配置参数。若本文与实际代码实现或接口契约文件不一致,以对应权威文件为准并优先修订本文。

本文只定义新 worktree 的帧区间迭代定位方案中 **Agent 侧**的实现;旧 worktree 中"直接预测断裂时间与断裂模式"的方案仅作为对比基线,不在本文范围内继续扩展。

### 与其他文档的关系

- [`docs/architecture/model_finetuning_design.md`](./model_finetuning_design.md):定义模型微调侧的数据管道、训练样本构建、模型训练流程及模型侧配置。
- [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md):定义微调模型与 Agent 之间的接口契约,包括模型输出 JSON Schema、Tool Schema、Prompt 契约、索引/时间换算规则、最终输出 Schema 等。本文在涉及这些契约时仅做引用说明,详细定义以接口契约为准。

---

## 1. 项目概述

### 1.1 目标

训练一个基于多模态大模型的**帧区间判别模型**,并配合外部**迭代控制器**,逐步缩小视频断裂时间范围,最终定位材料拉伸试验视频的断裂时刻。

### 1.2 与旧方案的根本区别

| 维度 | 旧方案 | 新方案 |
|---|---|---|
| 预测方式 | 直接输出断裂秒数(回归/分类) | 输出"断裂发生在哪两帧之间"(区间判别) |
| 推理流程 | 单轮预测 | 多轮迭代,逐步收缩时间区间 |
| 信息利用 | 一次性观看全视频 | 每轮聚焦子区间,逐层定位 |
| 失败模式 | 偏差大时无修正机制 | 每轮有置信度,可提前终止或加权融合 |

核心思想:**不直接预测精确秒数,而是通过多轮问答让模型判断"断裂在哪两帧之间",外部 Agent 据此迭代缩小范围。**

### 1.3 成功标准

| 指标 | 目标 | 说明 |
|---|---|---|
| 区间命中率 | ≥ 80% | 预测区间包含真实断裂时间的比例 |
| within_1s | ≥ 60% | 点估计(区间中点)与真实时间误差 ≤ 1s |
| within_3s | ≥ 85% | 点估计与真实时间误差 ≤ 3s |
| within_5s | ≥ 95% | 点估计与真实时间误差 ≤ 5s |
| type macro-F1 | ≥ 0.75 | 断裂类型(韧性/脆性等)分类性能 |
| location 准确率 | ≥ 0.70 | 标距内/外判断准确率,仅在 location != N/A 子集上计算 |

---

## 2. 技术决策记录(ADR)

以下决策已与项目团队确认,记录如下:

| 决策项 | 选定方案 | 理由 |
|---|---|---|
| Agent-LLM 协议 | **Native Function Calling(tool_calls)** | 标准 OpenAI 兼容协议,主流远程/本地服务均支持,无需引入额外抽象 |
| 是否引入 MCP | **不引入 MCP** | 当前工具调用链路简单(2 个工具),引入 MCP 增加复杂度而无明显收益 |
| Agent LLM 后端 | **远程 API / 本地部署可配置切换** | 开发阶段使用远程 API 快速验证;本地部署用于低成本测试与隐私场景 |
| 模型名称传递 | **完全透传,不维护硬编码模型列表** | 模型迭代快、多提供商并存;用户自主选择模型,代码只负责正确调用 |
| Agent 终止策略 | **Agent 自主决策 + 代码层多层保底** | 既保留 Agent 灵活性,又通过 tolerance、max_rounds、低置信度检测防止失控 |

---

## 3. Meta-Agent 驱动的迭代推理框架

### 3.1 Agent LLM 后端架构

Agent 与 LLM 的交互采用 **Native Function Calling** 协议:模型输出标准 `tool_calls` 字段,Agent Loop 解析 `tool_calls` 后执行对应 Tool,并将结果回传给模型。**不引入 MCP**。

开发阶段可根据需要选择远程 API 或本地部署,模型由配置决定。

**统一接口设计(抽象基类)**:

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class BaseAgentLLM(ABC):
    """Agent 大脑的统一接口,屏蔽本地/远程差异"""

    @abstractmethod
    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Any:
        """
        调用模型,支持 function calling

        Args:
            messages: OpenAI-compatible messages 列表
            tools: OpenAI-compatible tools schema 列表
            temperature: 采样温度
            max_tokens: 最大生成 token 数

        Returns:
            OpenAI-compatible ChatCompletion 对象
            包含 .choices[0].message.content 和 .choices[0].message.tool_calls
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前使用的模型名称"""
        pass
```

**远程 API Client(通用 OpenAI-compatible)**:

```python
import os
from openai import OpenAI

class RemoteAPIClient(BaseAgentLLM):
    """
    远程 API 客户端(通用 OpenAI-compatible)

    支持任意 OpenAI-compatible API 提供商,包括但不限于:
    - 阿里云百炼 (dashscope): https://dashscope.aliyuncs.com/compatible-mode/v1
    - SiliconFlow: https://api.siliconflow.cn/v1
    - OpenAI: https://api.openai.com/v1
    - Together AI: https://api.together.xyz/v1
    - 任何其他兼容 OpenAI API 格式的服务
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        provider: str = "custom"  # 仅用于日志标识,如 "dashscope", "siliconflow", "openai"
    ):
        self._model = model
        self._provider = provider
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def chat_with_tools(self, messages, tools, temperature=0.7, max_tokens=None):
        kwargs = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        return self.client.chat.completions.create(**kwargs)

    @property
    def model_name(self) -> str:
        return f"{self._provider}/{self._model}"
```

**本地部署 Client(通用 OpenAI-compatible 本地端点)**:

```python
class LocalClient(BaseAgentLLM):
    """
    本地部署客户端(通用 OpenAI-compatible 本地端点)

    支持任意提供 OpenAI-compatible API 的本地推理工具,包括但不限于:
    - Ollama: http://localhost:11434/v1
    - vLLM: http://localhost:8000/v1
    - llama.cpp (server mode): http://localhost:8080/v1
    - 任何其他兼容 OpenAI API 格式的本地端点
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434/v1",
        provider: str = "ollama"  # 仅用于日志标识,如 "ollama", "vllm", "llamacpp"
    ):
        self._model = model
        self._provider = provider
        self.client = OpenAI(api_key="EMPTY", base_url=base_url)

    def chat_with_tools(self, messages, tools, temperature=0.7, max_tokens=None):
        kwargs = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        return self.client.chat.completions.create(**kwargs)

    @property
    def model_name(self) -> str:
        return f"{self._provider}/{self._model}"
```

**工厂方法**:

```python
class AgentLLMFactory:
    """根据配置创建对应的 LLM Client"""

    @staticmethod
    def create(config: dict) -> BaseAgentLLM:
        backend = config.get("backend", "remote")

        if backend == "remote":
            api_key = config.get("api_key") or os.getenv("LLM_API_KEY")
            if not api_key:
                raise ValueError("远程模式需要提供 api_key 或设置 LLM_API_KEY 环境变量")

            return RemoteAPIClient(
                model=config["model"],  # 任意模型名,直接透传
                api_key=api_key,
                base_url=config["base_url"],
                provider=config.get("provider", "custom")
            )

        elif backend == "local":
            return LocalClient(
                model=config["model"],  # 任意模型名,直接透传
                base_url=config.get("base_url", "http://localhost:11434/v1"),
                provider=config.get("provider", "ollama")
            )

        else:
            raise ValueError(f"不支持的后端: {backend},请使用 'remote' 或 'local'")
```

**配置示例**:

```yaml
# config/agent.yaml
agent:
  # 后端类型: remote (远程API) | local (本地部署)
  backend: "remote"

  # ==========================================
  # 远程 API 配置
  # ==========================================
  remote:
    # provider: 仅用于日志标识,可选值如 dashscope, siliconflow, openai, together 等
    # 不影响实际调用,只帮助区分不同提供商的日志
    provider: "dashscope"

    # model: 模型名称,完全由提供商决定,代码直接透传
    # 百炼示例: qwen2.5-7b-instruct, qwen2.5-14b-instruct, qwen2.5-32b-instruct, qwen-max, qwen-plus...
    # SiliconFlow 示例: Qwen/Qwen2.5-14B-Instruct, deepseek-ai/DeepSeek-V3...
    # OpenAI 示例: gpt-4o, gpt-4o-mini...
    model: "qwen2.5-14b-instruct"

    # base_url: API 基础地址
    # 百炼: https://dashscope.aliyuncs.com/compatible-mode/v1
    # SiliconFlow: https://api.siliconflow.cn/v1
    # OpenAI: https://api.openai.com/v1
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # api_key: API 密钥
    # 可在此硬编码(不推荐),或从环境变量 LLM_API_KEY 读取
    api_key: null

  # ==========================================
  # 本地部署配置
  # ==========================================
  local:
    # provider: 仅用于日志标识,可选值如 ollama, vllm, llamacpp 等
    provider: "ollama"

    # model: 模型名称,由本地服务决定,代码直接透传
    # Ollama 示例: qwen2.5:7b, qwen2.5:14b, llama3.1:8b...
    # vLLM 示例: Qwen/Qwen2.5-7B-Instruct, meta-llama/Llama-3.1-8B-Instruct...
    model: "qwen2.5:7b"

    # base_url: 本地服务端点
    # Ollama: http://localhost:11434/v1
    # vLLM: http://localhost:8000/v1
    # llama.cpp: http://localhost:8080/v1
    base_url: "http://localhost:11434/v1"
```

> **关于模型选择的灵活性设计**
>
> Agent LLM 层采用"完全透传"策略,代码不维护任何硬编码的模型支持列表。原因如下:
> 1. **模型迭代快**:各大模型厂商不断更新模型版本,硬编码列表需要频繁维护
> 2. **多提供商支持**:用户可能在不同项目中使用百炼、SiliconFlow、OpenAI 等不同服务,统一接口降低切换成本
> 3. **用户自主权**:用户最了解自己需要什么模型,代码不应做不必要的限制
> 4. **责任边界**:模型可用性、function calling 能力、价格等由用户和提供商决定,代码只负责正确调用
>
> 用户在选择模型时需要自行确认:
> - 该模型是否支持 function calling(tool use)
> - 该模型在当前任务上的推理质量是否满足需求
> - API 配额和成本是否在预算内
>
> 推荐的模型组合(基于当前测试经验):
> - **开发阶段**:百炼 qwen2.5-14b-instruct(function calling 稳定,性价比高)
> - **本地测试**:Ollama qwen2.5:7b(轻量,MacBook Air M4 可流畅运行)
> - **生产增强**:百炼 qwen2.5-32b-instruct 或 qwen-max(推理能力更强,成本更高)

---

### 3.2 架构概述

```
┌─────────────────────────────────────────────────────────────┐
│              Agent Loop(迭代控制器)                         │
│                                                             │
│  1. 构建 messages(system + user context + history)         │
│  2. 调用 LLM.chat_with_tools(messages, tools)                │
│  3. 解析 response.choices[0].message.tool_calls              │
│  4. 执行 Tool → 结果回传为 tool 消息                         │
│  5. 循环直至 terminate 或达到 max_rounds                     │
│                                                             │
│  LLM 后端:DashScope(百炼)/ Ollama(本地),可配置切换      │
│                                                             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Tool 执行层(通用代码)                      │
│                                                             │
│  1. VideoSampler:根据 tool_args 抽帧 → 输出帧序列             │
│  2. VideoClipBuilder:生成本轮临时 .mp4 推理片段              │
│  3. InferenceClient:使用临时视频片段和 prompt 调用微调模型    │
│     (MiniCPM-V via LLaMA-Factory)                          │
│  4. ResultParser:按 tool_args.expected_schema 解析模型输出   │
│  5. 返回结构化结果给 Agent Loop                               │
│                                                             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
              本轮结果 → 追加到 history → 回到 Agent Loop
```

> **Tool Schema 定义**(`sample_and_infer`、`terminate`)见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 3-4 节。
> **Tool 执行层接口定义**(`VideoSampler.sample`、`VideoClipBuilder.build`、`InferenceClient.infer`、`ResultParser.parse`)见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 5 节。

---

### 3.3 Agent Loop 伪代码

```python
class IterativeAgent:
    def __init__(self, llm_client: BaseAgentLLM, video_meta: dict, config: dict):
        self.llm = llm_client
        self.video_meta = video_meta
        self.config = config
        self.history = []

        self.max_rounds = config.get("agent", {}).get("max_rounds", 10)
        self.tolerance = config.get("agent", {}).get("tolerance_seconds", 1.0)
        self.confidence_threshold = config.get("agent", {}).get("confidence_threshold", 0.5)  # 用于 low_confidence 判定（映射到 round_confidence_level）
        self.max_low_conf_rounds = config.get("agent", {}).get("max_low_conf_rounds", 2)

        # 代码层确定性状态机
        self.state = "INITIAL"
        self.candidate = [0.0, video_meta["duration"]]
        self.no_fracture_count = 0
        self.low_conf_count = 0
        self.conflict_count = 0
        self.last_boundary_status = "none"
        self.last_round_confidence_level = "不可信"
        self.best_positive_round = None

    def run(self) -> dict:
        """主循环：LLM 输出 tool_calls，状态/候选区间、边界哨兵扩展及终止权限由代码层控制。"""
        messages = self._build_system_messages()

        for round_idx in range(self.max_rounds):
            response = self.llm.chat_with_tools(
                messages=messages,
                tools=TOOLS_SCHEMA,
                temperature=0.7
            )
            message = response.choices[0].message

            # 1. 检查是否有 tool_calls
            if not message.tool_calls:
                messages.append({"role": "assistant", "content": message.content})
                messages.append({"role": "user", "content": "请使用 tool_calls 输出你的决策。"})
                continue

            tool_call = message.tool_calls[0]  # 每次只取第一个
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            # 2. terminate：代码层先判断当前状态是否允许终止
            if tool_name == "terminate":
                allowed, reason = self._can_terminate(tool_args, round_idx)
                if allowed:
                    self.state = "TERMINATED"
                    return self._finalize(tool_args)

                # 不允许终止：把拒绝原因作为 tool result 回传，让 LLM 继续迭代
                messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [{
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": tool_call.function.arguments
                        }
                    }]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"allowed": False, "reason": reason}, ensure_ascii=False)
                })
                continue

            # 3. 执行 sample_and_infer
            if tool_name == "sample_and_infer":
                result = self._execute_sample_and_infer(tool_args)
            else:
                raise ValueError(f"未知工具: {tool_name}")

            # 4. 代码层状态转移、候选区间更新、冲突处理及边界哨兵扩展
            self._transition(result)

            # 5. 补充记录本轮结果
            self._log_round(round_idx, message, result)

            # 6. 将 tool_call 与执行结果回传给 LLM
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [{
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": tool_call.function.arguments
                    }
                }]
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False)
            })

            # 7. 冲突不可调和时，代码层强制终止
            if self.state == "TERMINATED":
                return self._force_terminate()

        # 超过最大轮数，强制终止
        return self._force_terminate()

    def _can_terminate(self, args: dict, round_idx: int) -> tuple[bool, str]:
        """判断当前状态是否允许响应 terminate（优先级见第 3.3.1 节）。

        Agent 内部停止条件综合使用 `self.state`、候选区间范围与
        `self.last_round_confidence_level`，不直接依赖 `args.confidence_level`
        （该字段仅用于最终输出）。
        """
        has_fracture = args.get("has_fracture", True)

        # 无断裂路径：仅在 NO_FRACTURE 状态且候选区间覆盖全局范围时才允许终止
        if not has_fracture:
            is_global_scope = (
                self.candidate[0] <= 0.0
                and self.candidate[1] >= self.video_meta["duration"]
            )
            if self.state == "NO_FRACTURE" and is_global_scope:
                if self.no_fracture_count >= 2 or self.last_round_confidence_level == "高":
                    return True, "NO_FRACTURE 状态下连续 2 轮确认或高置信无断裂（全局范围）"
            return False, "无断裂判定尚未稳定，请继续验证（仅在 NO_FRACTURE 全局范围可终止）"

        # 有断裂路径：必须区间收敛或轮数耗尽；边界哨兵不能单独触发收敛
        if self.state in ("NARROWING", "VERIFYING"):
            if self.last_boundary_status != "none":
                return False, "边界哨兵需先扩展采样区间并重新验证，不能单独终止"
            if self.candidate[1] - self.candidate[0] <= self.tolerance:
                if self.last_round_confidence_level == "不可信":
                    return False, "区间虽收敛但最新一轮置信度不可信，请继续验证"
                return True, "候选区间宽度 ≤ tolerance"
            if round_idx >= self.max_rounds - 1:
                return True, "达到 max_rounds"

        return False, "区间尚未收敛，请继续调用 sample_and_infer"

    def _transition(self, result: dict):
        """根据 SampleAndInferResult 更新状态、候选区间、冲突处理及边界哨兵处理。

        result 为符合接口文档第 5.3 节 `SampleAndInferResult` 的结构。
        """
        model_output = result.get("model_output", {})
        has_fracture = model_output.get("has_fracture", False)
        new_range = result.get("inferred_time_range")
        boundary_status = result.get("boundary_status", "none")
        confidence_level = result.get("round_confidence_level", "不可信")

        self.last_boundary_status = boundary_status

        # ------------------------------------------------------------------
        # 无断裂路径
        # ------------------------------------------------------------------
        if not has_fracture:
            # 本轮为无断裂判定，必须覆盖旧置信度，禁止沿用上一轮正类高置信。
            self.last_round_confidence_level = confidence_level

            # 只有在"初始全范围采样"或"已扩展回全范围"时，连续高置信 false 才能进入全局 NO_FRACTURE。
            # NARROWING / VERIFYING 阶段聚焦子区间返回 false，说明候选可能错过断裂点，
            # 应进入扩展/回退/验证失败分支，不能直接进入 NO_FRACTURE。
            is_global_scope = (
                self.state == "INITIAL"
                or (self.candidate[0] <= 0.0 and self.candidate[1] >= self.video_meta["duration"])
            )

            if is_global_scope:
                self.state = "NO_FRACTURE"
                self.no_fracture_count += 1
                return

            # 聚焦子区间 false：回退并扩展候选区间，提示下一轮在更大范围内重试
            self.conflict_count += 1
            self.candidate = self._expand_candidate(self.candidate)
            result["fallback"] = "focus_false_expanded_to_parent_range"
            return

        # ------------------------------------------------------------------
        # 有断裂路径
        # ------------------------------------------------------------------
        self.no_fracture_count = 0
        if self.state in ("INITIAL", "NO_FRACTURE"):
            self.state = "NARROWING"

        # 边界哨兵处理：模型指向采样序列最前端/最末端，向对应边界扩展后继续验证
        if boundary_status == "left_sentinel":
            c0, c1 = self.candidate
            step = max(self.tolerance, (c1 - c0) * 0.1)
            self.candidate = [max(0.0, c0 - step), c1]
            result["boundary_handled"] = "expanded_left"
            self.last_round_confidence_level = confidence_level
            return
        elif boundary_status == "right_sentinel":
            c0, c1 = self.candidate
            step = max(self.tolerance, (c1 - c0) * 0.1)
            duration = self.video_meta["duration"]
            self.candidate = [c0, min(duration, c1 + step)]
            result["boundary_handled"] = "expanded_right"
            self.last_round_confidence_level = confidence_level
            return

        # 候选区间更新与冲突处理（正常区间）
        if new_range:
            c0, c1 = self.candidate
            n0, n1 = new_range

            if c0 <= n0 and n1 <= c1:
                # 正常收敛
                self.candidate = new_range
                self.conflict_count = 0
                self.low_conf_count = 0
            elif not (n1 < c0 or n0 > c1):
                # 部分重叠：取交集
                self.candidate = [max(c0, n0), min(c1, n1)]
                self.conflict_count = 0
                self.low_conf_count = 0
            else:
                # 冲突处理分支：新区间完全越界
                if confidence_level in ("低", "不可信"):
                    # 低置信：丢弃本轮结果，不更新候选区间
                    self.low_conf_count += 1
                    result["conflict_handled"] = "discarded_low_confidence"
                else:
                    # 高/中置信：扩展候选区间以包含新结果，并记录冲突
                    self.candidate = [min(c0, n0), max(c1, n1)]
                    self.conflict_count += 1
                    result["conflict_handled"] = "expanded_candidate"

                # 连续低置信触发回退/扩展
                if self.low_conf_count >= self.max_low_conf_rounds:
                    self.candidate = self._expand_candidate(self.candidate)
                    self.low_conf_count = 0
                    result["fallback"] = "expanded_to_parent_range"

        # 区间足够窄且非边界哨兵时进入 VERIFYING
        if self.state == "NARROWING" and (self.candidate[1] - self.candidate[0]) <= self.tolerance:
            self.state = "VERIFYING"

        # 连续不可调和冲突：代码层标记为 TERMINATED，最终按不可信输出
        if self.conflict_count >= 3:
            self.state = "TERMINATED"

        # 记录本轮置信度等级，供 _can_terminate 等内部逻辑使用
        self.last_round_confidence_level = confidence_level

    def _expand_candidate(self, candidate: list) -> list:
        """低置信连续时的回退示例：以当前区间为中心扩展 1.5 倍，边界不超过 [0, duration]。"""
        width = candidate[1] - candidate[0]
        center = (candidate[0] + candidate[1]) / 2
        half = width * 0.75
        return [
            max(0.0, center - half),
            min(self.video_meta["duration"], center + half)
        ]

    def _force_terminate(self) -> dict:
        """超过 max_rounds 或冲突不可调和时的强制终止。

        - 无断裂状态：输出 `has_fracture=false`，区间字段填 null。
        - 有断裂状态：`type`/`location` 必须从多轮历史最佳结果投票/加权得到；
          `frame_range` 必须从对应最佳轮次的 `frames[].original_frame` 生成；
          不能硬编码正类标签或伪造 frame_range。
        - 若没有任何有效证据，输出 `has_fracture=false` 与 `confidence_level=不可信`
          （或明确失败状态），禁止伪造正类结果。
        """
        # 收集历史中有断裂的轮次（按 SampleAndInferResult 记录）
        positive_rounds = [
            r for r in self.history
            if r.get("result", {}).get("model_output", {}).get("has_fracture", False)
        ]

        if self.state == "NO_FRACTURE" or not positive_rounds:
            return self._finalize({
                "has_fracture": False,
                "time_range": None,
                "time_estimate": None,
                "frame_range": None,
                "type": "未断裂",
                "location": "N/A",
                "confidence": 0.5,
                "confidence_level": "不可信"
            })

        # 按 round_confidence_level 加权/投票选出最佳轮次
        best_round = self._select_best_round(positive_rounds)
        best_result = best_round["result"]
        best_model_output = best_result["model_output"]
        best_frames = best_result.get("frames", [])
        best_time_range = best_result.get("inferred_time_range")
        best_frame_range = best_result.get("inferred_frame_range")

        # 若最佳轮次 frame_range 缺失但 frames 存在，按接口文档第 8 节从对应帧换算
        if best_frame_range is None and best_time_range is not None and len(best_frames) >= 2:
            # 仅作示例：从最佳轮次的 inferred_time_range 找对应 timestamp 的帧
            best_frame_range = self._time_range_to_frame_range(best_frames, best_time_range)

        # type/location 投票（示例：取历史正类结果中出现次数最多的有效值）
        voted_type = self._vote_field(
            [r["result"]["model_output"].get("type") for r in positive_rounds],
            valid_set={"韧性断裂", "脆性断裂", "界面脱粘", "齐根断裂", "爆炸性断裂", "半脆半韧断裂", "界面脱粘、齐根断裂"}
        )
        voted_location = self._vote_field(
            [r["result"]["model_output"].get("location") for r in positive_rounds],
            valid_set={"inside_gauge", "outside_gauge"}
        ) or "N/A"

        return self._finalize({
            "has_fracture": True,
            "time_range": best_time_range or self.candidate,
            "time_estimate": self._estimate_time(best_time_range or self.candidate),
            "frame_range": best_frame_range,
            "type": voted_type,
            "location": voted_location,
            "confidence": 0.5,
            "confidence_level": "不可信"
        })

    def _select_best_round(self, positive_rounds: list[dict]) -> dict:
        """从正类轮次中选出最佳轮次；示例策略：优先高置信、其次区间窄。"""
        level_score = {"高": 3, "中": 2, "低": 1, "不可信": 0}

        def score(r):
            result = r.get("result", {})
            level = result.get("round_confidence_level", "不可信")
            rng = result.get("inferred_time_range")
            width = rng[1] - rng[0] if rng else float("inf")
            return (level_score.get(level, 0), -width)

        return max(positive_rounds, key=score)

    def _vote_field(self, values: list, valid_set: set) -> str | None:
        """对有效取值进行多数投票，忽略 None / N/A / 无效值。"""
        from collections import Counter
        filtered = [v for v in values if v in valid_set]
        if not filtered:
            return None
        return Counter(filtered).most_common(1)[0][0]

    def _estimate_time(self, time_range: list) -> float:
        """区间中点作为时间估计。"""
        return (time_range[0] + time_range[1]) / 2

    def _time_range_to_frame_range(self, frames: list, time_range: list) -> list | None:
        """根据时间区间在 frames 中匹配首尾帧的 original_frame。"""
        start_frame = next((f["original_frame"] for f in frames if abs(f["timestamp"] - time_range[0]) < 1e-6), None)
        end_frame = next((f["original_frame"] for f in frames if abs(f["timestamp"] - time_range[1]) < 1e-6), None)
        if start_frame is not None and end_frame is not None:
            return [start_frame, end_frame]
        return None

    def _execute_sample_and_infer(self, args: dict) -> dict:
        """执行 sample_and_infer 工具，返回符合接口文档第 5.3 节的 SampleAndInferResult。"""
        sample_range = args["sample_range"]
        video_maxlen = args.get("num_frames", self.config.get("video_maxlen", 36))
        video_fps = args.get("video_fps", self.config.get("video_fps", 8.0))
        strategy = args.get("sampling_strategy", "uniform")

        # 视频抽帧；返回 list[dict]，每个元素必须包含 original_frame、timestamp，
        # frame_path 可作为调试/审计缓存。frames 用于把 fracture_between 映射回原视频。
        # num_frames 是 video_maxlen 上限，实际帧数由 sample_range 时长、video_fps 与上限共同决定。
        frames = VideoSampler.sample(
            video_path=self.video_meta["video_path"],
            sample_range=sample_range,
            num_frames=video_maxlen,
            video_fps=video_fps,
            strategy=strategy
        )

        # 生成本轮送入模型的临时 .mp4 推理片段；模型视觉输入以视频路径为准。
        # 训练集持久化子视频只用于模型微调训练，Agent 推理阶段不复用训练子视频。
        model_video_path = VideoClipBuilder.build(
            source_video=self.video_meta["video_path"],
            sample_range=sample_range,
            frames=frames,
            video_fps=video_fps,
            video_maxlen=video_maxlen,
            sampling_strategy=strategy
        )

        # 调用微调模型；InferenceClient.infer 以 .mp4 视频片段路径作为视觉输入载体
        # 按接口文档第 5.4 节契约，infer 直接返回解析后的模型输出 JSON dict
        model_output = InferenceClient.infer(model_video_path, args["prompt"])

        # 装配 SampleAndInferResult
        result = {
            "model_output": model_output,
            "frames": frames,
            "model_video_path": model_video_path,
            "sample_range": sample_range,
            "video_fps": video_fps,
            "video_maxlen": video_maxlen,
            "num_sample_frames": len(frames),
            "sampling_strategy": strategy,
            "inferred_time_range": None,
            "inferred_frame_range": None,
            "boundary_status": "none",
            "parse_error": None,
            "round_confidence_level": "不可信"
        }

        # 解析失败处理
        if model_output is None:
            result["parse_error"] = "InferenceClient.infer 返回 None，模型输出解析失败"
            return result

        # 数值 confidence -> round_confidence_level
        confidence = model_output.get("confidence", 0.5)
        result["round_confidence_level"] = self._confidence_to_level(confidence)

        # 换算 fracture_between 到原视频时间/帧区间；识别边界哨兵
        if model_output.get("has_fracture") and model_output.get("fracture_between"):
            fracture_between = model_output["fracture_between"]
            n = len(frames)
            if n >= 1 and fracture_between == [0, 0]:
                result["boundary_status"] = "left_sentinel"
            elif n >= 1 and fracture_between == [n - 1, n - 1]:
                result["boundary_status"] = "right_sentinel"
            else:
                result["boundary_status"] = "none"

            result["inferred_time_range"] = self._convert_to_time_range(frames, fracture_between)
            result["inferred_frame_range"] = self._convert_to_frame_range(frames, fracture_between)

        return result

    def _confidence_to_level(self, confidence: float) -> str:
        """将数值 confidence 映射为四级 round_confidence_level（与接口文档第 4.4 节一致）。"""
        if confidence >= 0.90:
            return "高"
        if confidence >= 0.70:
            return "中"
        if confidence >= 0.50:
            return "低"
        return "不可信"

    def _convert_to_time_range(self, frames: list, fracture_between: list) -> list:
        """将 fracture_between 索引换算为原视频时间区间。

        详细换算规则见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 8 节。
        """
        i, j = fracture_between
        return [frames[i]["timestamp"], frames[j]["timestamp"]]

    def _convert_to_frame_range(self, frames: list, fracture_between: list) -> list:
        """将 fracture_between 索引换算为原视频帧区间（直接使用 frames[].original_frame）。"""
        i, j = fracture_between
        return [frames[i]["original_frame"], frames[j]["original_frame"]]

    def _log_round(self, round: int, message, result: dict | None = None):
        """记录中间过程；若本工具为 sample_and_infer，将 result 一并记录供后续投票/终止使用。"""
        log_entry = {
            "round": round,
            "model": self.llm.model_name,
            "reasoning": message.content,
            "tool_calls": [
                {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                } for tc in (message.tool_calls or [])
            ]
        }
        if result is not None:
            log_entry["result"] = result
        self.history.append(log_entry)
        logger.info(f"Round {round}: {json.dumps(log_entry, ensure_ascii=False)}")

    def _finalize(self, args: dict) -> dict:
        """正常终止"""
        return {
            **args,
            "video_id": self.video_meta["video_id"],
            "rounds": len(self.history),
            "history": self.history
        }
```

---

### 3.3.1 Agent 状态机(阻塞级)

为降低 Meta-Agent 自主决策的不可控性,Agent 迭代过程在代码层维护一个确定性状态机。Agent LLM 的 `tool_calls` 仅作为驱动状态转移的输入;状态更新、候选区间管理、冲突处理和终止优先级由代码层统一控制。

#### 核心状态

| 状态 | 含义 | 候选区间 |
|---|---|---|
| `INITIAL` | 初始状态,尚未收敛到疑似断裂区间 | `[0, duration]` |
| `NARROWING` | 已至少一轮确认 `has_fracture=true`,正在按 `fracture_between` 收缩候选区间 | 当前有效候选区间 |
| `VERIFYING` | 候选区间已足够窄或已连续多轮稳定,进入重复验证 | 同上 |
| `NO_FRACTURE` | 在初始全范围采样或已扩展回全范围后，连续/高置信输出 `has_fracture=false` 时进入；聚焦子区间的单轮 `false` 不进入此状态 | 不适用 |
| `TERMINATED` | 已满足终止条件并输出最终结果 | 最终区间或 `null` |

#### 状态转移规则

```text
INITIAL
  ├─ has_fracture=true  ──> NARROWING(用本轮 inferred_time_range 初始化候选区间)
  ├─ has_fracture=false(初始全范围采样)  ──> NO_FRACTURE
  └─ 直接满足终止条件    ──> TERMINATED

NARROWING
  ├─ has_fracture=true 且结果在候选区间内 ──> NARROWING(取交集或新区间更新候选区间)
  ├─ has_fracture=true 但结果在候选区间外 ──> 见"冲突处理"
  ├─ has_fracture=true 且边界哨兵        ──> 向对应边界扩展候选区间，保持 NARROWING
  ├─ has_fracture=false(聚焦子区间)       ──> 扩展候选区间并回退，保持 NARROWING(不进入 NO_FRACTURE)
  ├─ 区间宽度 <= tolerance_seconds 且非边界哨兵 ──> VERIFYING 或直接 TERMINATED
  └─ max_rounds 到达    ──> TERMINATED

VERIFYING
  ├─ 连续验证通过(区间/type/location 稳定) ──> TERMINATED
  ├─ 验证失败(结果不一致或低置信)      ──> NARROWING
  ├─ has_fracture=false(聚焦子区间)      ──> 扩展候选区间并回退，返回 NARROWING(不进入 NO_FRACTURE)
  └─ max_rounds 到达    ──> TERMINATED

NO_FRACTURE（仅由全局范围进入）
  ├─ 全局范围下连续 2 轮 has_fracture=false，或该状态下任意一轮 round_confidence_level 为"高"且 has_fracture=false ──> TERMINATED(time_range 等填 null)
  ├─ 后续某轮 has_fracture=true(无论置信度) ──> NARROWING(扩展候选区间)
  └─ max_rounds 到达    ──> TERMINATED(按无断裂输出)
```

#### 候选区间更新

设当前候选区间为 `candidate = [t0, t1]`,本轮模型输出 `has_fracture=true` 且换算后区间为 `r = [a, b]`:

- **边界哨兵优先处理**:若 `SampleAndInferResult.boundary_status` 为 `left_sentinel` / `right_sentinel`,将候选区间向对应边界扩展一个步长(如本轮采样步长),并在下一轮继续验证;**哨兵产生的区间不得单独触发收敛终止**。
- 正常收敛:`r ⊆ candidate` 且非边界哨兵,更新 `candidate = r`。
- 边界重叠:仅部分重叠,更新 `candidate = candidate ∩ r`;若交集为空,按冲突处理。

#### 冲突处理

若新轮次的 `inferred_time_range` 落在当前候选区间外,或 `type` / `location` 与历史不一致:

- **低置信度**(`round_confidence_level` 为 `低` / `不可信`):丢弃本轮结果,不更新候选区间,重新采样验证;连续丢弃次数 +1。
- **高置信度**(`round_confidence_level` 为 `高` / `中`):扩展候选区间以包含新结果,并记录冲突;后续优先在新扩展区间内重新验证。若连续出现不可调和冲突,可标记为异常样本并在终止时给出 `confidence_level = "不可信"`。

#### 回退 / 扩展

触发条件包括:

- 连续 `max_low_conf_rounds` 轮为低置信度;
- 候选区间长期未收敛;
- `NARROWING` / `VERIFYING` 阶段对聚焦子区间采样得到 `has_fracture=false`(说明候选可能错过断裂点)。

代码层自动扩大采样范围(例如扩展到父区间的 1.5 倍或回到 `[0, duration]`),并可增加 `num_frames` / `video_maxlen` 上限。每次扩展后,低置信度计数重置。

#### 终止优先级(代码层强制)

以下优先级从高到低:

1. **确认无断裂(仅限 NO_FRACTURE 全局范围)**:只有在 `NO_FRACTURE` 状态且 `candidate` 覆盖 `[0, duration]` 时，连续 2 轮 `has_fracture=false`，或该状态下任意一轮 `round_confidence_level` 为 `高` 且 `has_fracture=false` → 立即调用 `terminate`，`time_range` / `time_estimate` / `frame_range` 填 `null`;代码层不再检查区间宽度。聚焦子区间返回的 `has_fracture=false` 不会进入 `NO_FRACTURE`，因此不允许以此触发终止。
2. **区间收敛**:候选区间宽度 `<= tolerance_seconds`、`boundary_status == none` 且最新结果 `round_confidence_level` 不为 `不可信` → 调用 `terminate`。
3. **边界扩展**:最新结果 `boundary_status != none` 时,拒绝终止,强制先扩展候选区间并重新验证。
4. **最大轮数**:`max_rounds` 到达 → 强制 `terminate`;若当前已有有效候选区间,按历史最佳正类结果投票/加权输出;否则按无断裂/异常输出,并标记 `confidence_level = "不可信"`。

---

### 3.4 Agent System Prompt 设计

Agent 的 System Prompt 完整模板由接口文档统一约定,本节仅保留 Agent 侧的角色、目标与关键约束说明。完整模板与示例见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 6.3 节。

- **角色**:Agent 是"材料拉伸试验视频分析协调者",负责驱动多轮工具调用。
- **目标**:通过调用 `sample_and_infer` 与 `terminate` 工具,逐步缩小候选区间,最终输出包含断裂时刻区间、断裂类型、位置及综合置信度的结果。
- **关键约束**:
  - System Prompt 固定使用接口文档第 6.3 节的完整模板,由代码层在初始化时写入;Agent Loop 运行期间不得修改 system prompt,仅在此基础上动态构建每轮 user prompt。
  - 必须通过 function calling(`tool_calls`)输出决策,禁止直接文本回答。
  - `sample_and_infer` 的 `prompt` 参数须符合接口文档第 6 节 Prompt 契约,并与训练数据构造器生成的 user prompt 分布一致。
  - 所有 `sample_range` 必须在视频总时长 `[0, duration]` 范围内。

---

### 3.5 Agent 输入上下文格式

每轮提交给 Meta-Agent 的完整 prompt 结构如下:

```
[视频元信息]
视频ID: {video_id}
总时长: {duration}s
FPS: {fps}
总帧数: {total_frames}

[配置参数]
容忍误差: {tolerance}s
最大迭代轮数: {max_rounds}
当前轮次: {current_round}/{max_rounds}

[历史迭代记录]
轮次1:
- 采样区间: [0, 500]s
- 模型输出: {"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.85}
- 换算后区间: [242.86, 257.14]s
...

[当前状态]
当前候选区间: [242.86, 257.14]s
区间宽度: 14.28s

> **换算说明**:以默认 `video_fps=8.0`、`video_maxlen=36` 在区间 `[0, 500]s` 上使用 `uniform` 策略为例,由于区间较长,实际采样帧数被上限截断为 36 帧,采样帧间隔为 `500 / (36 - 1) ≈ 14.2857s`。`fracture_between = [17, 18]` 对应第 17、18 号采样帧,时间戳分别为 `17 × 14.2857 ≈ 242.86s` 和 `18 × 14.2857 ≈ 257.14s`,因此换算后区间为 `[242.86, 257.14]s。

请通过 tool_calls 输出你的下一步决策。
```

---

### 3.6 停止条件(与状态机联动)

| 层级 | 条件 | 处理逻辑 |
|---|---|---|
| **Agent 层** | Agent 在 reasoning 中自主判断终止 | Agent 调用 `terminate` tool,给出最终输出参数 |
| **无断裂路径(仅限 NO_FRACTURE 全局范围)** | 仅在 `NO_FRACTURE` 状态且 `candidate` 覆盖 `[0, duration]` 时，`has_fracture=false` 且 `round_confidence_level` 为 `高`，或连续 2 轮确认 | 直接调用 `terminate`;`time_range` / `time_estimate` / `frame_range` 填 `null`;代码层不再检查区间宽度 |
| **代码层保底 1** | Agent 调用 terminate 且 `has_fracture=true`,但区间宽度 > `tolerance` 或 `boundary_status != none` | 代码层拒绝终止,在 tool result 中提示 Agent 继续迭代;不适用于无断裂路径 |
| **代码层保底 2** | 超过 `max_rounds` | 强制终止,代码层构造 `final_output`,无论区间是否收敛 |
| **代码层保底 3** | 连续 `max_low_conf_rounds` 轮模型自报 confidence < threshold | 代码层在 tool result 中提示 Agent 考虑终止;Agent 可采纳或继续 |

> **关于 `frame_range` 的必填性**:`terminate` schema 中 `frame_range` 为必填字段,但允许填 `null`(尤其是 `has_fracture=false` 时)。`time_range` / `time_estimate` 同理。

---

### 3.7 最终输出

Agent 最终输出 JSON Schema 定义见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 7 节。本节保留关键约束说明:

- 无断裂/异常样本的最终输出约束:
  - `has_fracture`: `false`
  - `time_range` / `time_estimate` / `frame_range`: 统一填 `null`。
  - `type`: 仅允许 `未断裂` / `未夹紧` / `视频异常` 三者之一,**不允许输出 `none`**。训练标签由构造器决定:人工负片段默认 `未断裂`,真实无断裂/异常样本保留其标注。推理最终输出由模型多轮预测投票/置信度聚合决定:若模型在多轮中明确预测 `未夹紧` 或 `视频异常` 且置信度可接受,则采用该预测;否则默认 `未断裂`,并将 `confidence_level` 降至 `中` 或 `低`(至少不为 `高`)。
  - `location`: 必须为 `"N/A"`。
  - `status` 字段不在最终输出 Schema 中,无需返回。

---

## 4. 评估体系

### 4.1 评估指标定义与计算

| 指标 | 定义 | 计算公式 |
|---|---|---|
| **区间命中率** | 预测区间包含真实断裂时间的比例 | `hit = (time_range[0] <= t_gt <= time_range[1])` |
| **within_1s** | 点估计与真实时间绝对误差 ≤ 1s 的比例 | `\|time_estimate - t_gt\| <= 1.0` |
| **within_3s** | 点估计与真实时间绝对误差 ≤ 3s 的比例 | `\|time_estimate - t_gt\| <= 3.0` |
| **within_5s** | 点估计与真实时间绝对误差 ≤ 5s 的比例 | `\|time_estimate - t_gt\| <= 5.0` |
| **time MAE** | 时间估计的平均绝对误差 | `MAE = mean(\|time_estimate - t_gt\|)` |
| **type accuracy** | 断裂类型分类准确率 | 仅统计 `has_fracture=true` 的预测样本,计算正确预测 type 的样本比例 |
| **type macro-F1** | 断裂类型分类宏平均 F1 | 仅统计 `has_fracture=true` 的预测样本，且只在 7 个断裂类别上计算：`韧性断裂`、`脆性断裂`、`界面脱粘`、`齐根断裂`、`爆炸性断裂`、`半脆半韧断裂`、`界面脱粘、齐根断裂`（组合标签作为独立类别）。异常/无断裂类别（`未断裂` / `未夹紧` / `视频异常`）不纳入 macro-F1，改用**异常样本失败率**衡量 |
| **location accuracy** | 标距位置判断准确率 | 仅统计 `has_fracture=true` 的预测样本;进一步在 `location != N/A` 子集上计算正确预测 location 的样本比例 |
| **异常样本失败率** | 异常样本中预测失败的占比 | `is_abnormal=TRUE` 或 `has_fracture=false` 的样本集合中,模型最终错误输出 `has_fracture=true` 的比例(与接口文档第 2.7 节定义一致) |
| **置信度-误差相关性** | 模型自报 confidence 与预测误差的相关性 | Pearson / Spearman 相关系数 |
| **不同 confidence 阈值下的区间命中率** | 在 `final_confidence ≥ threshold` 子集上计算的区间命中率 | 阈值可取 0.5 / 0.7 / 0.9 |
| **reliability diagram** | confidence vs accuracy 的校准曲线 | 横轴为 confidence 分桶,纵轴为对应桶的实际准确率 |
| **低 confidence 样本错误率** | `final_confidence < 0.5` 的样本中,预测失败(区间未命中或 type/location 错误)的比例 | 用于验证低置信度预警的有效性 |

> **真实时间回退规则**:以上时间相关指标中的 `t_gt` 优先取 `event_time`;当 `event_time` 不可解析时,回退到 `event_frame_original / fps`。这些指标仅在 `has_fracture = true` 且 `t_gt` 可计算的样本上统计。

### 4.2 置信度专项评估

1. **可靠性图(Reliability Diagram)**:将 `final_confidence` 分成若干桶(如 0.0~0.1, 0.1~0.2, ...),计算每个桶内的实际准确率。理想情况下,confidence 为 0.8 的桶准确率应接近 0.8。若模型系统性地高估自身信心(overconfidence),则实际准确率显著低于 confidence 值。
2. **阈值分析**:报告 `final_confidence ≥ 0.5 / 0.7 / 0.9` 时的区间命中率和 within_1s/3s/5s 指标,验证高置信度预测是否确实更可靠。
3. **低置信度失败率**:统计 `final_confidence < 0.5` 的样本中,真实区间未命中或 type/location 预测错误的占比。该值应显著高于高置信度样本的错误率,否则说明 confidence 信号无效。

### 4.3 对比基准

所有指标需与**旧方案在同一批 held-out test 集**上的表现进行对比,评估相对提升。口径强制为：旧方案必须复用新方案的 video-level test split 重新生成或过滤测试输入；新旧对比只能在相同的 `video_id` 集合上进行，不允许旧方案使用自己的 test split 或全量数据。若旧 baseline 当前无独立 test 集，则需通过新方案的 test split 过滤其输出后计算指标:

| 对比维度 | 说明 |
|---|---|
| 旧方案 vs 新方案(单轮) | 新方案仅使用第一轮(全时长视频)的预测结果 |
| 旧方案 vs 新方案(完整迭代) | 新方案完整迭代后的最终结果 |
| 3-fold 平均 | 报告训练集内 3-fold 交叉验证的平均指标 ± 标准差；该指标用于模型选择/调参，不能替代 held-out test 指标，最终新旧方案对比以 held-out test 为准 |

---

## 5. 数据 Schema(Agent 侧)

Agent 侧直接消费微调模型输出,并产出最终预测结果。为避免重复,本节仅做引用说明:

- **微调模型输出 JSON Schema**:详细定义与示例见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 2 节。
- **Agent 最终输出 JSON Schema**:详细定义与示例见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 第 7 节。

---

## 6. 配置参数(Agent 侧)

所有可配置参数集中管理,建议通过 YAML 文件(如 `config/frame_interval.yaml`)维护。本节仅列出与 Agent 侧直接相关的参数:

| 参数名 | 默认值 | 说明 |
|---|---|---|
| `agent.tolerance_seconds` | 1.0 | Agent 迭代停止的区间容忍误差(秒);顶层不再保留同名重复项 |
| `agent.max_rounds` | 10 | Agent 最大迭代轮数;顶层不再保留同名重复项 |
| `agent.video_fps` | 8.0 | Agent 推理阶段传给工具执行层的视频采样帧率超参数,必须与模型微调训练配置一致 |
| `agent.video_maxlen` | 36 | Agent 推理阶段的视频采样帧数上限,语义等同 `sample_and_infer.num_frames`,必须与模型微调训练配置一致 |
| `agent.confidence_threshold` | 0.5 | 低置信度判定阈值(与 `round_confidence_level` 配合使用) |
| `agent.max_low_conf_rounds` | 2 | 连续低置信度达到该轮数则回退/扩展候选区间 |
| `agent.backend` | "remote" | Agent LLM 后端:remote(百炼) / local(Ollama) |
| `agent.remote.provider` | "dashscope" | 远程提供商 |
| `agent.remote.model` | "qwen2.5-14b-instruct" | 百炼模型名,用户可自选 |
| `agent.remote.base_url` | "https://dashscope.aliyuncs.com/compatible-mode/v1" | 百炼 API 地址 |
| `agent.remote.api_key` | null | 远程 API 密钥,推荐从环境变量 `LLM_API_KEY` 读取 |
| `agent.local.provider` | "ollama" | 本地提供商 |
| `agent.local.model` | "qwen2.5:7b" | Ollama 模型名,用户可自选 |
| `agent.local.base_url` | "http://localhost:11434/v1" | Ollama API 地址 |
| `agent.temperature` | 0.7 | Agent LLM 采样温度 |

> 模型侧配置参数(如 `video_fps`、`video_maxlen`、`focus_windows`、`test_ratio` 等)见 [`docs/architecture/model_finetuning_design.md`](./model_finetuning_design.md) 第 5 节。Agent 侧的 `agent.video_fps` 与 `agent.video_maxlen` 是推理执行层镜像配置,默认与模型侧保持一致。

---

## 7. 实现顺序与里程碑

| 阶段 | 时间 | 负责模块 | 交付物 | 验收标准 |
|---|---|---|---|---|
| **Phase 3** | Week 3 | Meta-Agent 迭代推理框架 | 迭代推理 Agent 代码、预测结果 JSON | 在测试集上单视频推理成功,输出符合最终 Schema |
| **Phase 4** | Week 4 | 评估体系 | 评估报告(含旧方案对比) | 所有指标计算完毕,报告输出到 `docs/eval/` |

> Phase 1-2(数据管道与模型微调训练)见 [`docs/architecture/model_finetuning_design.md`](./model_finetuning_design.md) 第 6 节。

---

## 8. 风险与待办(Agent/评估侧)

| 风险项 | 影响 | 缓解措施 | 状态 |
|---|---|---|---|
| 模型自报 confidence 偏置 | 模型可能产生 overconfidence(高 confidence 但实际错误),导致 Agent 综合判断失真 | 在评估阶段通过 reliability diagram 和校准曲线监控;若偏置严重,考虑让 Agent 在 system prompt 中调整判断策略 | 🟡 待评估 |
| 百炼 API function calling 稳定性 | 百炼 Qwen2.5 系列的 tool_calls 输出格式和稳定性需实测验证 | 开发阶段优先用百炼远程 API 测试;若不稳定,尝试不同模型规格或调整 tool schema | 🔴 待验证 |
| Ollama function calling 效果 | Ollama + Qwen2.5-7B 的 function calling 支持程度和输出质量不确定 | 本地先测试 Qwen2.5-7B;若效果不佳,尝试更大本地模型或切换到远程后端 | 🔴 待验证 |
| Agent 模型输出质量 | Qwen 通过 tool_calls 进行迭代决策的质量直接影响收敛性 | 在 Phase 3 前做稳定性测试;若质量不稳定,考虑提升模型规格或优化 system prompt | 🔴 待验证 |
| Agent 生成不合理参数 | Agent 可能输出越界采样区间或不符合预期的 prompt | 代码层做边界校验(如区间合法性、`num_frames`/`video_maxlen` 与 `video_fps` 范围),非法时回退或提示 Agent 修正 | 🟡 待实现 |
| 本地 7B 模型决策质量 | 本地 7B 模型的推理和决策质量可能不如 14B,影响迭代效率 | 在测试中对比 7B 和 14B 的 Agent 决策质量;根据结果选择默认模型 | 🟡 待评估 |
| 本地 Qwen 推理速度 | 上下文较长时(历史记录累积),本地模型推理可能成为瓶颈 | 监控每轮 Agent 推理耗时;若过长,评估切换到远程后端或上下文截断策略 | 🟡 待评估 |

### 待办清单

- [ ] 申请百炼 API Key
- [ ] 在 MacBook Air M4 上安装 Ollama 并 pull qwen2.5:7b
- [ ] 测试百炼 Qwen2.5-14B 的 function calling 稳定性
- [ ] 测试 Ollama Qwen2.5-7B 的 function calling 稳定性
- [ ] 对比 7B 和 14B 的 Agent 决策质量
- [ ] 设计并实现 Agent 输出 JSON schema 的校验机制,非法时自动重试或降级
- [ ] Phase 4 中绘制 reliability diagram,评估模型 confidence 校准情况

---

## 附录 A:Agent 数据流图

```
LlamaFactory/saves/minicpmv4_6/lora/sft_3k*/
    |
    v
┌─────────────────────────────────────────────────────────────┐
│  Meta-Agent 驱动的迭代推理框架                                │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Agent Loop(迭代控制器)                              │   │
│  │ - LLM 后端:DashScope(百炼)/ Ollama(本地),可配置 │   │
│  │ - 协议:Native Function Calling(tool_calls)        │   │
│  │ 输入:视频元信息 + 历史迭代记录(messages)            │   │
│  │ 输出:tool_calls → 执行 Tool → 结果回传               │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Tool 执行层(通用代码)                               │   │
│  │ - VideoSampler:按 tool_args 抽帧                    │   │
│  │ - VideoClipBuilder:生成本轮临时 .mp4 推理片段       │   │
│  │ - InferenceClient:调用微调模型(MiniCPM-V)          │   │
│  │ - ResultParser:按 expected_schema 解析              │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│                         └──→ 结果追加到历史记录 → 回到 Agent Loop│
│                                                             │
│  终止时:Agent 输出 final_output(含综合 confidence)        │
└─────────────────────────────────────────────────────────────┘
    |
    v  预测结果 JSON
┌─────────────────────────────────────┐
│  评估体系                             │
│  - 区间命中率 / within_1s/3s/5s       │
│  - type F1 / location 准确率          │
│  - 异常样本分析 / 置信度-误差相关性     │
│  - 与旧方案对比报告                    │
└─────────────────────────────────────┘
    |
    v  评估报告
```

> 完整数据流图(含模型数据流)见 [`docs/architecture/model_agent_interface.md`](./model_agent_interface.md) 附录 A。
